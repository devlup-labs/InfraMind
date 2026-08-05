from dotenv import load_dotenv
import json
import logging
import os
import time

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

from monitoring_agent import fetch_comprehensive_metrics
from tools import horizontal_pod_scaling, restart_pod

load_dotenv()

MAX_RETRIES = int(os.getenv("RESTART_MAX_RETRIES", "2"))
WAIT_SECONDS = int(os.getenv("RESTART_WAIT_SECONDS", "30"))

logger = logging.getLogger("inframind-restart-agent")

SYSTEM_PROMPT = """
You are a Kubernetes Optimization Agent responsible for selecting the most appropriate remediation action for a Kubernetes workload.

Your task is to analyze the provided root-cause log and its accompanying explanation and determine whether an automated remediation action should be taken.

You have access to exactly two tools.

Use horizontal_pod_scaling ONLY if the issue is caused by increased workload or insufficient resources that can be mitigated by increasing the number of replicas.

Typical indicators include:
- High request rate
- High latency due to load
- CPU saturation
- Memory pressure across healthy pods
- Queue buildup
- Thread pool exhaustion
- Resource saturation
- Increased traffic

Use restart_pod ONLY if the issue is caused by an unhealthy pod or application failure.

Typical indicators include:
- CrashLoopBackOff
- OOMKilled
- Deadlock
- Hung process
- Liveness probe failures
- Readiness probe failures
- Fatal runtime exceptions
- Segmentation fault
- Corrupted application state
- Failed initialization
- Resource leak
- Repeated crashes

Decision Rules:

- Base your decision ONLY on the supplied root-cause log and explanation.
- Invoke AT MOST one tool.
- Never invoke both tools.
- If invoking restart_pod, use only the exact affected pod provided in the state.
- If neither action is justified, do not invoke any tool and instead explain why no automated remediation should be performed.
"""


llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
)


llm_with_tools = llm.bind_tools(
    [
        horizontal_pod_scaling,
        restart_pod,
    ]
)


def optimization_agent_runner(root_cause_log: str, affected_pod: str | None = None):
    """
    Determines whether to perform Horizontal Pod Scaling
    or restart a pod based on the root cause log.
    """

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=f"""
Root Cause Log:

{root_cause_log}

Affected Pod:
{affected_pod or "unknown"}
"""
        ),
    ]

    response = llm_with_tools.invoke(messages)

    return response


def _selected_tool_from_response(response) -> dict:
    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        return {
            "tool": "none",
            "justification": getattr(response, "content", "No automated remediation selected."),
        }

    tool_call = tool_calls[0]
    return {
        "tool": tool_call.get("name"),
        "args": tool_call.get("args", {}),
        "justification": "Optimization agent selected this mitigation tool.",
    }


def optimization_node(state: dict) -> dict:
    """Optimization Agent: LLM decides whether a mitigation tool is warranted."""
    response = optimization_agent_runner(
        root_cause_log=state.get("root_cause", ""),
        affected_pod=state.get("affected_pod"),
    )
    decision = _selected_tool_from_response(response)
    logger.info(f"Optimization agent decision: {json.dumps(decision)}")
    return {"selected_tool": decision}


def execute_restart_node(state: dict) -> dict:
    """Execute the selected mitigation tool."""
    selected_tool = state.get("selected_tool", {})
    tool_name = selected_tool.get("tool", "none")

    if tool_name == "restart_pod":
        affected_pod = state.get("affected_pod")
        if not affected_pod:
            result = {
                "status": "skipped",
                "reason": "No affected pod identified."
            }
        else:
            result = restart_pod.invoke({"pod_name": affected_pod})
    elif tool_name == "horizontal_pod_scaling":
        horizontal_pod_scaling.invoke({})
        result = {"status": "success", "tool": "horizontal_pod_scaling"}
    else:
        result = {"status": "no_action"}

    tried_tools = state.get("tried_tools", []) + [tool_name]
    history_entry = {
        "attempt": len(state.get("mitigation_history", [])) + 1,
        "tool": tool_name,
        "justification": selected_tool.get("justification"),
        "result": result,
    }
    mitigation_history = state.get("mitigation_history", []) + [history_entry]

    return {"tried_tools": tried_tools, "mitigation_history": mitigation_history}


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
    logger.info(f"Waiting {WAIT_SECONDS}s before re-checking metrics...")
    time.sleep(WAIT_SECONDS)

    snapshot = fetch_comprehensive_metrics()
    stabilized = is_stabilized(snapshot["metrics"])

    logger.info(f"Recheck metrics: {snapshot['metrics']} | stabilized={stabilized}")
    return {"metrics": snapshot["metrics"], "stabilized": stabilized}


def wait_and_recheck_node(state: dict) -> dict:
    """Wait & Re-check Metrics, then bump the retry counter."""
    recheck = wait_and_recheck_metrics()
    retry_count = state.get("retry_count", 0) + 1
    return {
        "last_metrics": recheck["metrics"],
        "stabilized": recheck["stabilized"],
        "retry_count": retry_count,
    }


def escalation_node(state: dict) -> dict:
    """Retry limit reached without stabilizing -- hand off, don't rollback."""
    escalation = {
        "incident_analysis": state.get("root_cause"),
        "suspect_metric": state.get("analysis", {}).get("suspect_metric"),
        "restart_attempts": state.get("tried_tools", []),
        "mitigation_history": state.get("mitigation_history", []),
        "last_metrics": state.get("last_metrics"),
        "recommended_action": "ROLLBACK",
        "reason": "Pod restart did not stabilize metrics within retry budget.",
    }

    logger.warning(f"ESCALATION -- handing off to rollback owner: {json.dumps(escalation)}")
    return {"final_status": "escalated_for_rollback", "escalation": escalation}


def healthy_end_node(state: dict) -> dict:
    """System Healthy / End."""
    logger.info("System stabilized after pod restart. No further action needed.")
    return {"final_status": "healthy"}


def stabilization_router(state: dict) -> str:
    if state.get("stabilized"):
        return "healthy_end"

    max_retries = state.get("max_retries", MAX_RETRIES)
    if state.get("retry_count", 0) >= max_retries:
        return "escalate"

    return "optimization"
