from monitoring_agent import fetch_comprehensive_metrics
from optimizing_agent import STABILITY_THRESHOLDS


def run_metrics_agent() -> dict:
    """
    Observation sub-agent: fetches the live Prometheus snapshot and flags
    which tracked metrics have breached their stability threshold. Cheap and
    fast -- this is the primary signal the triage controller acts on.
    """
    snapshot = fetch_comprehensive_metrics()
    metrics = snapshot.get("metrics", {})

    
    breaches = {}
    for name, value in metrics.items():
        threshold = STABILITY_THRESHOLDS.get(name)
        if threshold is None or value is None:
            continue
        breaches[name] = {
            "value": value,
            "threshold": threshold,
            "exceeded": value >= threshold,
        }

    return {
        "timestamp": snapshot.get("timestamp"),
        "metrics": metrics,
        "breaches": breaches,
    }