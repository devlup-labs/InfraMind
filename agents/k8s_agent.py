from evidence_graph import (
    fetch_structured_pods,
    fetch_structured_nodes,
    fetch_structured_deployment,
    fetch_structured_configmap,
)
from config import K8S_NAMESPACE, K8S_DEPLOYMENT, CONFIGMAP_NAME, POD_LABEL_SELECTOR


def run_k8s_agent() -> dict:
    """
    Observation sub-agent: a fast structured snapshot of cluster state (pods,
    nodes, deployment, configmap). Reuses the same structured fetchers the
    Phase 1 evidence graph uses for RCA, but this pass is for quick triage
    signal only -- e.g. "has anything restarted or drifted" -- not the full
    deep investigation RCA does later.
    """
    pods = fetch_structured_pods(K8S_NAMESPACE, POD_LABEL_SELECTOR)
    nodes = fetch_structured_nodes()
    deployment = fetch_structured_deployment(K8S_DEPLOYMENT, K8S_NAMESPACE)
    configmap = fetch_structured_configmap(CONFIGMAP_NAME, K8S_NAMESPACE)

    unhealthy_pods = [
        p for p in pods
        if p.get("restarts", 0) > 0 or p.get("status") != "Running" or not p.get("ready")
    ]
    pressured_nodes = [n for n in nodes if n.get("pressure_conditions")]

    return {
        "pods": pods,
        "nodes": nodes,
        "deployment": deployment,
        "configmap": configmap,
        "unhealthy_pods": unhealthy_pods,
        "pressured_nodes": pressured_nodes,
    }