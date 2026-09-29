"""Loading the fixed baseline dataset and pulling fresh metrics from Prometheus.

Both sources are returned in the same long format:
    timestamp (unix seconds) | metric (str) | value (float)
"""
import logging
import time

import numpy as np
import pandas as pd
import requests

from . import config

logger = logging.getLogger(__name__)

COLUMNS = ["timestamp", "metric", "value"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[COLUMNS].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df.loc[~np.isfinite(df["value"]), "value"] = np.nan
    df = df.drop_duplicates(subset=["metric", "timestamp"])
    df = df.sort_values(["metric", "timestamp"])
    # fill short gaps (max 3 steps) then drop whatever is still missing
    df["value"] = df.groupby("metric")["value"].transform(lambda s: s.ffill(limit=3))
    return df.dropna(subset=["value"]).reset_index(drop=True)


def load_baseline() -> pd.DataFrame:
    """Load the fixed baseline dataset (committed to the repo, never changes)."""
    if not config.BASELINE_PATH.exists():
        raise FileNotFoundError(
            f"{config.BASELINE_PATH} not found. Create it once with "
            "`python -m retraining.build_baseline` and commit it."
        )
    df = pd.read_csv(config.BASELINE_PATH)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Baseline file is missing columns: {sorted(missing)}")
    df = _clean(df)
    logger.info("Baseline loaded: %d rows, %d metrics", len(df), df["metric"].nunique())
    return df


def _query_range(query: str, start: float, end: float, step: int) -> list[tuple[float, float]]:
    """Run a Prometheus range query, chunked to stay under the point limit."""
    url = f"{config.prometheus_url()}/api/v1/query_range"
    span = config.MAX_POINTS_PER_QUERY * step
    points: list[tuple[float, float]] = []

    t = start
    while t < end:
        chunk_end = min(t + span, end)
        resp = requests.get(
            url,
            params={"query": query, "start": t, "end": chunk_end, "step": step},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()["data"]["result"]
        if len(result) > 1:
            logger.warning("Query returned %d series, using the first one: %s", len(result), query)
        if result:
            points.extend((float(ts), float(v)) for ts, v in result[0]["values"])
        t = chunk_end + step
    return points


def fetch_prometheus_data(lookback_hours: int, end: float | None = None) -> pd.DataFrame:
    """Pull every metric in config.METRIC_QUERIES for the given lookback window."""
    end = end or time.time()
    start = end - lookback_hours * 3600

    frames = []
    for name, query in config.METRIC_QUERIES.items():
        points = _query_range(query, start, end, config.STEP_SECONDS)
        if not points:
            logger.warning("No data returned for metric '%s'", name)
            continue
        frame = pd.DataFrame(points, columns=["timestamp", "value"])
        frame["metric"] = name
        frames.append(frame)

    if not frames:
        raise RuntimeError("Prometheus returned no data for any metric.")

    df = _clean(pd.concat(frames, ignore_index=True))
    logger.info("Prometheus data fetched: %d rows, %d metrics", len(df), df["metric"].nunique())
    return df


def fetch_new_data() -> pd.DataFrame:
    """The 'new' 30% source: recent metrics scraped by Prometheus."""
    return fetch_prometheus_data(config.NEW_DATA_LOOKBACK_HOURS)