import math
from typing import Dict, Optional

import requests

from retraining import config
from retraining.config import METRIC_QUERIES as FEATURE_QUERIES   # single source of truth


def _query_prometheus(query: str) -> Optional[float]:
    """Execute a single PromQL query and return the metric value, or None
    if the query fails, returns no data, or returns NaN/inf."""
    url = f"{config.prometheus_url()}/api/v1/query"
    try:
        response = requests.get(url, params={"query": query}, timeout=5)
        response.raise_for_status()

        data = response.json().get("data", {}).get("result", [])
        if not data:
            return None

        value = float(data[0]["value"][1])
        return value if math.isfinite(value) else None   # histogram_quantile gives NaN w/o traffic

    except requests.RequestException as err:
        print(f"[WARN] Prometheus request failed: {err}")
    except (KeyError, ValueError, TypeError, IndexError) as err:
        print(f"[WARN] Invalid Prometheus response: {err}")

    return None


def fetch_features() -> Dict[str, Optional[float]]:
    """Fetch all monitoring features from Prometheus. Missing metrics are None."""
    return {name: _query_prometheus(query) for name, query in FEATURE_QUERIES.items()}
