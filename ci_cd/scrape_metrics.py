import os
from typing import Dict, Optional

import requests

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

FEATURE_QUERIES = {
    "request_rate": "sum(rate(http_requests_total[5m]))",
    "cpu_usage_rate": "avg(rate(process_cpu_seconds_total[5m]))",
    "memory_usage_bytes": "avg(process_resident_memory_bytes)",
    "p95_latency_seconds": (
        "histogram_quantile("
        "0.95, "
        "sum(rate(http_request_duration_seconds_bucket[5m])) by (le)"
        ")"
    ),
}


def _query_prometheus(query: str) -> Optional[float]:
    """Execute a single PromQL query and return the metric value, or None
    if the query fails or returns no data."""
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        response.raise_for_status()

        data = response.json().get("data", {}).get("result", [])
        if not data:
            return None

        return float(data[0]["value"][1])

    except requests.RequestException as err:
        print(f"[WARN] Prometheus request failed: {err}")
    except (KeyError, ValueError, TypeError) as err:
        print(f"[WARN] Invalid Prometheus response: {err}")

    return None


def fetch_features() -> Dict[str, Optional[float]]:
    """Fetch all monitoring features from Prometheus. Missing metrics are None."""
    return {name: _query_prometheus(query) for name, query in FEATURE_QUERIES.items()}