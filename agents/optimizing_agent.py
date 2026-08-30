from dotenv import load_dotenv
import json
import logging
import os
import time

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

from monitoring_agent import fetch_comprehensive_metrics
from tools import (
    horizontal_pod_scaling,
    restart_pod,
    resource_limit_patch,
    config_map_patch,
    cordon_node,
    rollout_restart_deployment,
    node_drain,
    adjust_inference_concurrency
)

load_dotenv()

MAX_RETRIES = int(os.getenv("RESTART_MAX_RETRIES", "2"))
WAIT_SECONDS = int(os.getenv("RESTART_WAIT_SECONDS", "30"))

logger = logging.getLogger("inframind-optimization-agent")

SYSTEM_PROMPT = """
You are a Kubernetes Optimization Agent.

Choose at most ONE remediation category from the following list based on the Root Cause Analysis:
- "horizontal_pod_scaling": Use when evidence indicates insufficient replica capacity. (args: none)
- "restart_pod": Use only when the affected pod is actually unhealthy, crashed, hung, OOMKilled, or failing probes. (args: "pod_name")
- "cordon_node": Use ONLY if the root cause indicates a degraded, failing, or unhealthy Kubernetes worker node. (args: "node_name")
- "rollout_restart_deployment": Use ONLY if the root cause indicates deployment-wide stale connections, deadlocks, or hung cross-service dependencies. (args: "deployment_name")
- "resource_limit_patch": Use ONLY when structured evidence provides a recommended CPU or memory limit. (args: "resource", "new_limit", "deployment_name")
- "config_map_patch": Use ONLY when structured evidence explicitly provides config details. (args: "configmap_name", "key", "old_value", "new_value")
- "node_drain": Use ONLY when severe hardware failure requires immediate pod eviction. (args: "node_name")
- "adjust_inference_concurrency": Use ONLY when metrics show high latency or timeouts but CPU and memory are healthy, indicating an application-level thread bottleneck rather than scaling issues. (args: "configmap_name", "new_batch_size", "new_max_workers")
- "none": Use when no remediation is justified. (args: none)

You MUST output ONLY a valid JSON object in this exact format:
{
    "tool": "tool_name",
    "args": {
        "arg_name": "arg_value"
    },
    "justification": "Brief technical reason for selecting this tool."
}

Never invent values. Never estimate values. Never override structured recommendations.
"""

# Bind JSON object formatting to force strict structural compliance from Qwen
llm = ChatGroq(
    model="qwen/qwen3.6-27b",
    temperature=0,
).bind(response_format={"type": "json_object"})


def optimization_agent_runner(
    root_cause_log: str,
    affected_pod: str | None = None,
    resource_recommendation: dict | None = None,
    config_recommendation: dict | None = None,
    tried_tools: list[str] | None = None,
):
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"""
ROOT CAUSE ANALYSIS:
{root_cause_log}

AFFECTED ENVIRONMENT/POD:
{affected_pod or "unknown"}

STRUCTURED RESOURCE RECOMMENDATION:
{json.dumps(resource_recommendation or {}, indent=2)}

STRUCTURED CONFIGMAP RECOMMENDATION:
{json.dumps(config_recommendation or {}, indent=2)}

TOOLS ALREADY TRIED:
{json.dumps(tried_tools or [])}

Select at most one appropriate remediation tool and output as JSON.
"""),
    ]

    return llm.invoke(messages)


def _selected_tool_from_response(response) -> dict:
    try:
        decision = json.loads(response.content)
        return {
            "tool": decision.get("tool", "none"),
            "args": decision.get("args", {}),
            "justification": decision.get(
                "justification", 
                "Optimization agent selected this mitigation tool."
            ),
        }
    except Exception as e:
        logger.error(f"Failed to parse LLM JSON: {e}")
        return {
            "tool": "none",
            "args": {},
            "justification": f"JSON parse failed: {str(e)}",
        }


def optimization_node(state: dict) -> dict:
    root_cause = state.get("root_cause", "")
    affected_pod = state.get("affected_pod")
    recommendation = state.get("resource_recommendation", {})
    config_recommendation = state.get("config_recommendation")
    tried_tools = state.get("tried_tools", [])

    cpu = recommendation.get("cpu", {})
    memory = recommendation.get("memory", {})

    # Deterministic resource-limit remediation.
    if (
        "resource_limit_patch" not in tried_tools
        and cpu.get("recommended_limit")
    ):
        decision = {
            "tool": "resource_limit_patch",
            "args": {
                "resource": "cpu",
                "new_limit": cpu["recommended_limit"],
                "deployment_name": "inframind-model-deployment",
            },
            "justification": (
                "Structured Prometheus evidence shows CPU resource "
                f"constraint with calculated recommendation "
                f"{cpu['recommended_limit']}."
            ),
        }
        logger.info(
            f"Deterministic resource recommendation selected: {json.dumps(decision)}"
        )
        return {"selected_tool": decision}

    if (
        "resource_limit_patch" not in tried_tools
        and memory.get("recommended_limit")
    ):
        decision = {
            "tool": "resource_limit_patch",
            "args": {
                "resource": "memory",
                "new_limit": memory["recommended_limit"],
                "deployment_name": "inframind-model-deployment",
            },
            "justification": (
                "Structured Prometheus evidence shows memory "
                f"resource constraint with calculated recommendation "
                f"{memory['recommended_limit']}."
            ),
        }
        logger.info(
            f"Deterministic memory recommendation selected: {json.dumps(decision)}"
        )
        return {"selected_tool": decision}

    # Deterministic ConfigMap remediation.
    if (
        "config_map_patch" not in tried_tools
        and config_recommendation
        and config_recommendation.get("configmap_name")
        and config_recommendation.get("key")
        and config_recommendation.get("old_value") is not None
        and config_recommendation.get("new_value") is not None
    ):
        decision = {
            "tool": "config_map_patch",
            "args": {
                "configmap_name": config_recommendation["configmap_name"],
                "key": config_recommendation["key"],
                "old_value": str(config_recommendation["old_value"]),
                "new_value": str(config_recommendation["new_value"]),
            },
            "justification": config_recommendation.get(
                "reason",
                "RCA produced an evidence-supported ConfigMap recommendation.",
            ),
        }
        logger.info(
            f"Deterministic ConfigMap recommendation selected: {json.dumps(decision)}"
        )
        return {"selected_tool": decision}

    # LLM decision for cases without structured resource/config recommendations.
    response = optimization_agent_runner(
        root_cause_log=root_cause,
        affected_pod=affected_pod,
        resource_recommendation=recommendation,
        config_recommendation=config_recommendation,
        tried_tools=tried_tools,
    )

    decision = _selected_tool_from_response(response)

    logger.info(f"Optimization agent decision: {json.dumps(decision)}")
    return {"selected_tool": decision}


def execute_restart_node(state: dict) -> dict:
    selected_tool = state.get("selected_tool", {})
    tool_name = selected_tool.get("tool", "none")

    try:
        if tool_name == "restart_pod":
            args = selected_tool.get("args", {})
            target_pod = args.get("pod_name") or state.get("affected_pod")

            if not target_pod:
                result = {
                    "status": "skipped",
                    "reason": "No affected pod identified.",
                }
            else:
                result = restart_pod.invoke({
                    "pod_name": target_pod
                })

        elif tool_name == "horizontal_pod_scaling":
            result = horizontal_pod_scaling.invoke({})

        elif tool_name == "resource_limit_patch":
            args = selected_tool.get("args", {})
            resource = args.get("resource")
            new_limit = args.get("new_limit")
            deployment_name = args.get(
                "deployment_name",
                "inframind-model-deployment",
            )

            if resource not in {"cpu", "memory"}:
                result = {
                    "status": "failed",
                    "error": "Invalid resource selected.",
                }
            elif not new_limit:
                result = {
                    "status": "failed",
                    "error": "Missing evidence-supported new_limit.",
                }
            else:
                result = resource_limit_patch.invoke({
                    "resource": resource,
                    "new_limit": new_limit,
                    "deployment_name": deployment_name,
                })

        elif tool_name == "config_map_patch":
            args = selected_tool.get("args", {})

            required = [
                "configmap_name",
                "key",
                "old_value",
                "new_value",
            ]

            missing = [
                field for field in required
                if args.get(field) is None
            ]

            if missing:
                result = {
                    "status": "failed",
                    "error": (
                        "Missing ConfigMap recommendation fields: "
                        + ", ".join(missing)
                    ),
                }
            else:
                result = config_map_patch.invoke({
                    "configmap_name": args["configmap_name"],
                    "key": args["key"],
                    "old_value": str(args["old_value"]),
                    "new_value": str(args["new_value"]),
                })

        elif tool_name == "cordon_node":
            args = selected_tool.get("args", {})
            node_name = args.get("node_name")
            
            if not node_name:
                result = {
                    "status": "failed",
                    "error": "Missing node_name for cordon tool.",
                }
            else:
                result = cordon_node.invoke({
                    "node_name": node_name
                })
                
        elif tool_name == "rollout_restart_deployment":
            args = selected_tool.get("args", {})
            deployment_name = args.get("deployment_name", "inframind-model-deployment")
            
            result = rollout_restart_deployment.invoke({
                "deployment_name": deployment_name
            })

        elif tool_name == "node_drain":
            args = selected_tool.get("args", {})
            node_name = args.get("node_name")
            if not node_name:
                result = {"status": "failed", "error": "Missing node_name for drain tool."}
            else:
                result = node_drain.invoke({"node_name": node_name})
                
        elif tool_name == "adjust_inference_concurrency":
            args = selected_tool.get("args", {})
            if "configmap_name" not in args or "new_batch_size" not in args or "new_max_workers" not in args:
                result = {"status": "failed", "error": "Missing arguments for concurrency tuning."}
            else:
                result = adjust_inference_concurrency.invoke({
                    "configmap_name": args["configmap_name"],
                    "new_batch_size": args["new_batch_size"],
                    "new_max_workers": args["new_max_workers"]
                })

        else:
            result = {"status": "no_action"}

    except Exception as e:
        logger.exception("Mitigation tool execution failed.")
        result = {
            "status": "failed",
            "error": str(e),
        }

    tried_tools = state.get("tried_tools", []) + [tool_name]

    history_entry = {
        "attempt": len(state.get("mitigation_history", [])) + 1,
        "tool": tool_name,
        "justification": selected_tool.get("justification"),
        "result": result,
    }

    mitigation_history = (
        state.get("mitigation_history", [])
        + [history_entry]
    )

    return {
        "tried_tools": tried_tools,
        "mitigation_history": mitigation_history,
        "last_action_result": result,
    }


STABILITY_THRESHOLDS = {
    "cpu_usage_rate": 0.85,
    "http_4xx_rate": 1.0,
    "http_5xx_rate": 0.0001,
    "http_latency_p95_seconds": 1.5,
}


def is_stabilized(metrics: dict) -> bool:
    for metric_name, threshold in STABILITY_THRESHOLDS.items():
        value = metrics.get(metric_name)

        if value is None:
            continue

        if value >= threshold:
            return False

    return True


def wait_and_recheck_metrics() -> dict:
    logger.info(
        f"Waiting {WAIT_SECONDS}s before re-checking metrics..."
    )

    time.sleep(WAIT_SECONDS)

    snapshot = fetch_comprehensive_metrics()

    stabilized = is_stabilized(snapshot["metrics"])

    logger.info(
        f"Recheck metrics: {snapshot['metrics']} | "
        f"stabilized={stabilized}"
    )

    return {
        "metrics": snapshot["metrics"],
        "stabilized": stabilized,
    }


def wait_and_recheck_node(state: dict) -> dict:
    recheck = wait_and_recheck_metrics()

    retry_count = state.get("retry_count", 0) + 1

    return {
        "last_metrics": recheck["metrics"],
        "stabilized": recheck["stabilized"],
        "retry_count": retry_count,
    }


def escalation_node(state: dict) -> dict:
    escalation = {
        "incident_analysis": state.get("root_cause"),
        "suspect_metric": (
            state.get("analysis", {}).get("suspect_metric")
        ),
        "tried_tools": state.get("tried_tools", []),
        "mitigation_history": state.get("mitigation_history", []),
        "last_metrics": state.get("last_metrics"),
        "recommended_action": "ROLLBACK",
        "reason": (
            "Automated remediation did not stabilize "
            "the workload within the retry budget."
        ),
    }

    logger.warning(f"ESCALATION: {json.dumps(escalation)}")

    return {
        "final_status": "escalated_for_rollback",
        "escalation": escalation,
    }


def healthy_end_node(state: dict) -> dict:
    logger.info("System stabilized after automated remediation.")
    return {"final_status": "healthy"}


def stabilization_router(state: dict) -> str:
    if state.get("stabilized"):
        return "healthy_end"

    max_retries = state.get("max_retries", MAX_RETRIES)

    if state.get("retry_count", 0) >= max_retries:
        return "escalate"

    return "optimization"