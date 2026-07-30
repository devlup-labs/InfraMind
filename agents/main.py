from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from monitoring_agent import run_monitoring_agent
from log_collector import collect_logs
from qdrant_manager import create_collection, store_logs
from root_cause_agent import root_cause_agent


class GraphState(TypedDict):
    analysis: dict
    logs: list[str]
    root_cause:str


def monitoring_node(state: GraphState):
    analysis = run_monitoring_agent()
    return {"analysis": analysis}


def anomaly_router(state: GraphState):
    anomaly = state["analysis"].get("anomaly_detected", False)

    # Handle both bool and string values
    if isinstance(anomaly, str):
        anomaly = anomaly.lower() == "true"

    if anomaly:
        return "collect_logs"

    return END


def collect_logs_node(state: GraphState):
    logs = collect_logs()   # <-- This is YOUR function
    return {"logs": logs}


def store_logs_node(state: GraphState):
    store_logs(state["logs"])   # <-- This is YOUR function
    return {}


builder = StateGraph(GraphState)

builder.add_node("monitoring", monitoring_node)
builder.add_node("collect_logs", collect_logs_node)
builder.add_node("store_logs", store_logs_node)
builder.add_node("root_cause", root_cause_agent)

builder.add_edge(START, "monitoring")

builder.add_conditional_edges(
    "monitoring",
    anomaly_router,
    {
        "collect_logs": "collect_logs",
        END: END,
    },
)

builder.add_edge("collect_logs", "store_logs")
builder.add_edge("store_logs", "root_cause")
builder.add_edge("root_cause", END)

app = builder.compile()


if __name__ == "__main__":
    create_collection()
    result = app.invoke({})
    print("\n--- ROOT CAUSE ANALYSIS ---")
    print(result.get("root_cause", "No root cause was generated."))