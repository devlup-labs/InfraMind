import json

from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from triage_agent import run_triage_agent
from log_collector import collect_logs, get_pod_name
from qdrant_manager import create_collection, store_logs
from root_cause_agent import root_cause_agent
from reporting_agent import reporting_agent
from rollback_agent import rollback_node
from human_approval_agent import human_approval_node
from incident_history import append_incident

from optimizing_agent import (
    optimization_node,
    execute_restart_node,
    wait_and_recheck_node,
    escalation_node,
    healthy_end_node,
    stabilization_router,
    MAX_RETRIES,
)


class GraphState(TypedDict, total=False):
    analysis: dict
    logs: list[str]
    root_cause: str
    verification: dict
    rollback_approved: bool
    affected_pod: str

    resource_usage: dict
    resource_statistics: dict
    resource_limits: dict
    resource_recommendation: dict
    config_recommendation: dict

    selected_tool: dict
    tried_tools: list[str]
    mitigation_history: list[dict]
    last_metrics: dict
    stabilized: bool
    retry_count: int
    max_retries: int
    final_status: str
    escalation: dict
    rollback_result: dict
    incident_report: str
  

def monitoring_node(state: GraphState):

    analysis = run_triage_agent()
    return {
        "analysis": analysis
    }


def anomaly_router(state: GraphState):

    anomaly = state["analysis"].get(
        "anomaly_detected",
        False
    )

    if isinstance(anomaly, str):
        anomaly = (
            anomaly.lower() == "true"
        )

    return (
        "collect_logs"
        if anomaly
        else END
    )


def collect_logs_node(state: GraphState):

    observations = state.get("analysis", {}).get("_observations", {})
    logs_obs = observations.get("logs", {})

    logs = logs_obs.get("logs") if logs_obs else None
    affected_pod = logs_obs.get("affected_pod") if logs_obs else None

    return {
        "logs": logs if logs is not None else collect_logs(),
        "affected_pod": affected_pod if affected_pod else get_pod_name(),
    }


def store_logs_node(state: GraphState):

    store_logs(
        state["logs"]
    )

    return {}


def init_loop_state_node(state: GraphState):

    return {
        "retry_count": 0,
        "max_retries": MAX_RETRIES,
        "tried_tools": [],
        "mitigation_history": [],
        "stabilized": False,
    }


builder = StateGraph(
    GraphState
)

builder.add_node(
    "monitoring",
    monitoring_node
)

builder.add_node(
    "collect_logs",
    collect_logs_node
)

builder.add_node(
    "store_logs",
    store_logs_node
)

builder.add_node(
    "root_cause",
    root_cause_agent
)

builder.add_node(
    "init_loop_state",
    init_loop_state_node
)

builder.add_node(
    "optimization",
    optimization_node
)

builder.add_node(
    "execute_restart",
    execute_restart_node
)

builder.add_node(
    "wait_and_recheck",
    wait_and_recheck_node
)

builder.add_node(
    "escalate",
    escalation_node
)

builder.add_node(
    "human_approval",
    human_approval_node
)

builder.add_node(
    "rollback",
    rollback_node
)

builder.add_node(
    "healthy_end",
    healthy_end_node
)

builder.add_node(
    "reporting",
    reporting_agent
)


builder.add_edge(
    START,
    "monitoring"
)


builder.add_conditional_edges(
    "monitoring",
    anomaly_router,
    {
        "collect_logs": "collect_logs",
        END: END,
    },
)


builder.add_edge(
    "collect_logs",
    "store_logs"
)

builder.add_edge(
    "store_logs",
    "root_cause"
)

builder.add_edge(
    "root_cause",
    "init_loop_state"
)

builder.add_edge(
    "init_loop_state",
    "optimization"
)

builder.add_edge(
    "optimization",
    "execute_restart"
)

builder.add_edge(
    "execute_restart",
    "wait_and_recheck"
)

builder.add_conditional_edges(
    "wait_and_recheck",
    stabilization_router,
    {
        "healthy_end": "healthy_end",
        "optimization": "optimization",
        "escalate": "escalate",
    },
)

builder.add_edge(
    "healthy_end",
    "reporting"
)

builder.add_edge(
    "escalate",
    "human_approval"
)

builder.add_edge(
    "human_approval",
    "rollback"
)

builder.add_edge(
    "rollback",
    "reporting"
)

builder.add_edge(
    "reporting",
    END
)


app = builder.compile()


if __name__ == "__main__":

    create_collection()

    result = app.invoke({})

    print("\n--- AFFECTED POD ---")
    print(
        result.get(
            "affected_pod",
            "unknown"
        )
    )

    print("\n--- ROOT CAUSE ANALYSIS ---")
    root_cause = result.get("root_cause")
    if not root_cause:
        print("No root cause was generated.")
    else:
        print(f"Primary Cause: {root_cause.get('primary_cause', 'Unknown')}")
        print(f"Recommended Action: {root_cause.get('recommended_action', 'N/A')}")
        evidence = root_cause.get("evidence", [])
        if evidence:
            print("Evidence:")
            for item in evidence:
                print(f"  - {item}")
        if root_cause.get("resource_recommendation"):
            print("Resource Recommendation:")
            print(json.dumps(root_cause["resource_recommendation"], indent=2))
        if root_cause.get("config_recommendation"):
            print("Config Recommendation:")
            print(json.dumps(root_cause["config_recommendation"], indent=2))

    print("\n--- VERIFIER AGENT ---")
    verification = result.get("verification")
    if not verification:
        print("No verification was generated.")
    else:
        print(f"Verdict: {verification.get('verdict', 'unknown')} (confidence: {verification.get('confidence', 'n/a')})")
        print(f"Reasoning: {verification.get('reasoning', 'N/A')}")
        counter_evidence = verification.get("counter_evidence", [])
        if counter_evidence:
            print("Counter-Evidence:")
            for item in counter_evidence:
                print(f"  - {item}")

    print("\n--- RESOURCE RECOMMENDATION ---")
    print(json.dumps(result.get("resource_recommendation", {}), indent=2))

    print("\n--- MITIGATION HISTORY ---")

    for entry in result.get(
        "mitigation_history",
        []
    ):
        print(
            f"  Attempt {entry['attempt']}: "
            f"{entry['tool']} -> "
            f"{entry['result']}"
        )

    print(
        f"\n--- FINAL STATUS: "
        f"{result.get('final_status', 'n/a')} ---"
    )

    if result.get("rollback_result"):

        print(
            "--- ROLLBACK RESULT ---"
        )

        print(
            result.get(
                "rollback_result"
            )
        )

    print("\n--- INCIDENT REPORT ---")

    print(
        result.get(
            "incident_report",
            "No incident report was generated."
        )
    )

    # Log this run's outcome so future runs' evidence graphs can build
    # precedence edges against it ("has this happened before, and what
    # did we do about it?").
    if result.get("analysis", {}).get("anomaly_detected"):
        rc = result.get("root_cause") or {}
        append_incident(
            deployment_name="inframind-model-deployment",
            suspect_metric=result.get("analysis", {}).get("suspect_metric", "unknown"),
            primary_cause=rc.get("primary_cause", "unknown"),
            final_status=result.get("final_status", "unknown"),
            affected_pod=result.get("affected_pod"),
        )