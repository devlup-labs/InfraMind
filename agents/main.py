from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from monitoring_agent import run_monitoring_agent
from log_collector import collect_logs
from qdrant_manager import create_collection, store_logs
from root_cause_agent import root_cause_agent
from reporting_agent import reporting_agent
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
    affected_pod: str

    selected_tool: dict
    tried_tools: list[str]
    mitigation_history: list[dict]
    last_metrics: dict
    stabilized: bool
    retry_count: int
    max_retries: int
    final_status: str
    escalation: dict

    incident_report: str


def monitoring_node(state: GraphState):
    analysis = run_monitoring_agent()
    return {"analysis": analysis}


def anomaly_router(state: GraphState):
    anomaly = state["analysis"].get("anomaly_detected", False)
    if isinstance(anomaly, str):
        anomaly = anomaly.lower() == "true"
    return "collect_logs" if anomaly else END


def collect_logs_node(state: GraphState):
    return {"logs": collect_logs()}


def store_logs_node(state: GraphState):
    store_logs(state["logs"])
    return {}


def init_loop_state_node(state: GraphState):
    return {
        "retry_count": 0,
        "max_retries": MAX_RETRIES,
        "tried_tools": [],
        "mitigation_history": [],
    }


builder = StateGraph(GraphState)

builder.add_node("monitoring", monitoring_node)
builder.add_node("collect_logs", collect_logs_node)
builder.add_node("store_logs", store_logs_node)
builder.add_node("root_cause", root_cause_agent)
builder.add_node("init_loop_state", init_loop_state_node)
builder.add_node("optimization", optimization_node)
builder.add_node("execute_restart", execute_restart_node)
builder.add_node("wait_and_recheck", wait_and_recheck_node)
builder.add_node("escalate", escalation_node)
builder.add_node("healthy_end", healthy_end_node)
builder.add_node("reporting", reporting_agent)

builder.add_edge(START, "monitoring")

builder.add_conditional_edges(
    "monitoring",
    anomaly_router,
    {"collect_logs": "collect_logs", END: END},
)

builder.add_edge("collect_logs", "store_logs")
builder.add_edge("store_logs", "root_cause")
builder.add_edge("root_cause", "init_loop_state")
builder.add_edge("init_loop_state", "optimization")

builder.add_edge("optimization", "execute_restart")
builder.add_edge("execute_restart", "wait_and_recheck")

builder.add_conditional_edges(
    "wait_and_recheck",
    stabilization_router,
    {
        "healthy_end": "healthy_end",
        "optimization": "optimization",   # loop back
        "escalate": "escalate",
    },
)

builder.add_edge("healthy_end", "reporting")
builder.add_edge("escalate", "reporting")
builder.add_edge("reporting", END)

app = builder.compile()


if __name__ == "__main__":
    create_collection()
    result = app.invoke({})

    print("\n--- ROOT CAUSE ANALYSIS ---")
    print(result.get("root_cause", "No root cause was generated."))

    print("\n--- RESTART ATTEMPTS ---")
    for entry in result.get("mitigation_history", []):
        print(f"  Attempt {entry['attempt']}: {entry['tool']} -> {entry['result']}")

    print(f"\n--- FINAL STATUS: {result.get('final_status', 'n/a')} ---")
    if result.get("final_status") == "escalated_for_rollback":
        print("--- ESCALATION PAYLOAD (for rollback owner) ---")
        print(result.get("escalation"))

    print("\n--- INCIDENT REPORT ---")
    print(result.get("incident_report", "No incident report was generated."))
