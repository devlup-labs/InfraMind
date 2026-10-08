"""
Evidence Graph for Root Cause Analysis.

Builds a small, per-incident knowledge graph of infra/software/observability/
config entities, connected by typed, weighted edges:

  - causation:   X directly explains/produces Y   (e.g. config drift -> errors)
  - change:      X was recently modified, may have introduced Y            
  - correlation: X's behavior lines up with Y's, without proven causation
  - precedence:  a past incident resembling this one, and what happened then

Rather than feeding the LLM a giant raw-text dump of kubectl output, we parse
structured (-o json) K8s data into typed nodes, connect them with weighted
edges, then rank connections to the affected pod by weight. Only the
top-ranked, pre-filtered evidence goes into the LLM prompt -- smaller, more
signal-dense, and less prone to the schema drift we saw from dumping raw text.
"""

import json
import subprocess
import time
from datetime import datetime, timezone

import networkx as nx

from incident_history import load_recent_incidents


def run_kubectl_json(args: list[str]) -> dict | list | None:
    """Runs kubectl with -o json and parses the result. Returns None on any failure."""
    try:
        result = subprocess.run(
            ["kubectl"] + args + ["-o", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _age_minutes(creation_timestamp: str) -> float | None:
    try:
        created = datetime.fromisoformat(creation_timestamp.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - created).total_seconds() / 60.0
    except Exception:
        return None


def fetch_structured_pods(namespace: str, label_selector: str) -> list[dict]:
    data = run_kubectl_json(["get", "pods", "-n", namespace, "-l", label_selector])
    if not data:
        return []

    pods = []
    for item in data.get("items", []):
        container_statuses = item.get("status", {}).get("containerStatuses", [{}])
        cs = container_statuses[0] if container_statuses else {}
        last_state = cs.get("lastState", {})
        terminated = last_state.get("terminated", {})

        pods.append({
            "name": item.get("metadata", {}).get("name", "unknown"),
            "status": item.get("status", {}).get("phase", "Unknown"),
            "restarts": cs.get("restartCount", 0),
            "ready": cs.get("ready", False),
            "node": item.get("spec", {}).get("nodeName"),
            "age_minutes": _age_minutes(item.get("metadata", {}).get("creationTimestamp", "")),
            "last_terminated_exit_code": terminated.get("exitCode"),
            "last_terminated_reason": terminated.get("reason"),
        })
    return pods


def fetch_structured_nodes() -> list[dict]:
    data = run_kubectl_json(["get", "nodes"])
    if not data:
        return []

    nodes = []
    for item in data.get("items", []):
        conditions = item.get("status", {}).get("conditions", [])
        pressure_conditions = [
            c["type"] for c in conditions
            if c.get("status") == "True" and c["type"] != "Ready"
        ]
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)

        nodes.append({
            "name": item.get("metadata", {}).get("name", "unknown"),
            "ready": ready,
            "pressure_conditions": pressure_conditions,
        })
    return nodes


def fetch_structured_configmap(name: str, namespace: str) -> dict:
    data = run_kubectl_json(["get", "configmap", name, "-n", namespace])
    if not data:
        return {}
    return data.get("data", {}) or {}


def fetch_structured_deployment(name: str, namespace: str) -> dict:
    data = run_kubectl_json(["get", "deployment", name, "-n", namespace])
    if not data:
        return {}

    spec = data.get("spec", {})
    status = data.get("status", {})
    containers = spec.get("template", {}).get("spec", {}).get("containers", [{}])
    container = containers[0] if containers else {}

    return {
        "name": name,
        "image": container.get("image"),
        "replicas_desired": spec.get("replicas"),
        "replicas_ready": status.get("readyReplicas", 0),
        "generation": data.get("metadata", {}).get("generation"),
        "resources": container.get("resources", {}),
    }


def build_evidence_graph(
    suspect_metric: str,
    metric_value: float,
    metric_threshold: float,
    affected_pod: str,
    deployment_name: str,
    namespace: str,
    configmap_name: str,
    configmap_baseline: dict,
    logs: list[str],
) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()

    metric_node = f"metric:{suspect_metric}"
    graph.add_node(metric_node, kind="metric", value=metric_value, threshold=metric_threshold)

    pods = fetch_structured_pods(namespace, "app=mock-model")
    nodes = fetch_structured_nodes()
    live_config = fetch_structured_configmap(configmap_name, namespace)
    deployment = fetch_structured_deployment(deployment_name, namespace)

    node_by_name = {n["name"]: n for n in nodes}

    deployment_node = f"deployment:{deployment_name}"
    graph.add_node(deployment_node, kind="deployment", **deployment)

    for pod in pods:
        pod_node = f"pod:{pod['name']}"
        graph.add_node(pod_node, kind="pod", **pod)

        is_affected = pod["name"] == affected_pod

        # correlation: metric <-> pod (only meaningfully weighted for the affected pod)
        if is_affected and metric_threshold:
            over_ratio = max(0.0, min(1.0, (metric_value - metric_threshold) / max(metric_threshold, 0.01)))
            graph.add_edge(metric_node, pod_node, kind="correlation", weight=round(over_ratio, 3),
                            detail=f"{suspect_metric}={metric_value} vs threshold={metric_threshold}")

        # change: deployment -> pod, weighted by recency (newer pod = more likely caused by a recent change)
        age = pod.get("age_minutes")
        if age is not None:
            recency_weight = max(0.0, 1.0 - min(age, 60.0) / 60.0)
            graph.add_edge(deployment_node, pod_node, kind="change", weight=round(recency_weight, 3),
                            detail=f"pod age={age:.1f}min")

        # causation: pod crash/restart evidence
        if pod.get("restarts", 0) > 0 or pod.get("last_terminated_exit_code") not in (None, 0):
            graph.add_edge(pod_node, pod_node, kind="causation", weight=0.9,
                            detail=f"restarts={pod.get('restarts')}, "
                                   f"exit_code={pod.get('last_terminated_exit_code')}, "
                                   f"reason={pod.get('last_terminated_reason')}")

        # causation: node pressure -> pod
        node_info = node_by_name.get(pod.get("node"))
        if node_info and node_info.get("pressure_conditions"):
            node_node = f"node:{node_info['name']}"
            graph.add_node(node_node, kind="node", **node_info)
            graph.add_edge(node_node, pod_node, kind="causation", weight=1.0,
                            detail=f"node pressure: {', '.join(node_info['pressure_conditions'])}")

        # causation: config drift -> pod
        for key, live_value in live_config.items():
            baseline_value = configmap_baseline.get(key)
            if baseline_value is not None and str(live_value) != str(baseline_value):
                config_node = f"config:{configmap_name}.{key}"
                graph.add_node(config_node, kind="config", live_value=live_value, baseline_value=baseline_value)
                graph.add_edge(config_node, pod_node, kind="causation", weight=0.7,
                                detail=f"{key} live={live_value} baseline={baseline_value} (drifted)")

    # causation: notable log lines -> affected pod
    affected_pod_node = f"pod:{affected_pod}"
    for i, line in enumerate(logs[:10]):
        lowered = str(line).lower()
        is_error_like = any(term in lowered for term in ["error", "exception", "traceback", "fail", "timeout", "5xx", "500"])
        if is_error_like and graph.has_node(affected_pod_node):
            log_node = f"log:{i}"
            graph.add_node(log_node, kind="log", text=str(line)[:300])
            graph.add_edge(log_node, affected_pod_node, kind="causation", weight=0.6, detail=str(line)[:150])

    # precedence: past incidents on this deployment
    for incident in load_recent_incidents(deployment_name, limit=5):
        incident_node = f"incident:{incident.get('timestamp', 'unknown')}"
        graph.add_node(incident_node, kind="incident", **incident)
        similarity = 0.8 if incident.get("suspect_metric") == suspect_metric else 0.3
        if graph.has_node(deployment_node):
            graph.add_edge(incident_node, deployment_node, kind="precedence", weight=similarity,
                            detail=f"{incident.get('suspect_metric')} -> {incident.get('final_status')}")

    return graph


def rank_evidence_for_pod(graph: nx.MultiDiGraph, affected_pod: str, top_n: int = 8) -> list[dict]:
    """
    Collects every edge touching the affected pod (or its deployment, via
    precedence), sorted by weight descending. This is the compact, ranked
    evidence set that goes to the LLM instead of a raw text dump.
    """
    pod_node = f"pod:{affected_pod}"
    candidates = []

    for u, v, data in graph.edges(data=True):
        touches_pod = (u == pod_node or v == pod_node)
        touches_via_deployment = data.get("kind") == "precedence"
        if not (touches_pod or touches_via_deployment):
            continue

        source_kind = graph.nodes[u].get("kind", "unknown")
        candidates.append({
            "edge_kind": data.get("kind", "unknown"),
            "weight": data.get("weight", 0.0),
            "source": u,
            "source_type": source_kind,
            "detail": data.get("detail", ""),
        })

    candidates.sort(key=lambda c: c["weight"], reverse=True)
    return candidates[:top_n]


def format_evidence_for_prompt(candidates: list[dict]) -> str:
    if not candidates:
        return "No significant graph evidence found connected to the affected pod."

    lines = []
    for c in candidates:
        lines.append(
            f"- [{c['edge_kind']}, weight={c['weight']}] "
            f"({c['source_type']}) {c['detail']}"
        )
    return "\n".join(lines)