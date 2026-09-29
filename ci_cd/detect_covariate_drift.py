"""Detect covariate drift by comparing the fixed baseline metric distribution
against a recent window of live Prometheus metrics, using Evidently.

Reuses the same baseline CSV and Prometheus fetcher as the retraining package
so "reference" here means exactly the same 70% baseline retraining trains on.
"""
import os
from typing import List

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset

from retraining import config
from retraining.data_sources import fetch_prometheus_data, load_baseline


def _to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Long (timestamp | metric | value) -> wide (one column per metric).
    Buckets by STEP_SECONDS so metrics scraped a few seconds apart still line up
    in the same row; Evidently needs one row per observation, one column per metric."""
    bucketed = df.copy()
    bucketed["bucket"] = (bucketed["timestamp"] // config.STEP_SECONDS).astype(int)
    wide = bucketed.pivot_table(index="bucket", columns="metric", values="value", aggfunc="mean")
    return wide.dropna(how="any")


def detect_covariate_drift() -> List[str]:
    """Compare the baseline metric distribution against recent production metrics.

    Returns:
        List of metric names where covariate drift was detected.
    """
    reference_data = _to_wide(load_baseline())
    current_data = _to_wide(fetch_prometheus_data(config.COVARIATE_LOOKBACK_HOURS))

    shared_cols = [c for c in reference_data.columns if c in current_data.columns]
    if not shared_cols:
        raise ValueError("No metrics in common between baseline and current data.")
    reference_data, current_data = reference_data[shared_cols], current_data[shared_cols]

    if len(current_data) < 2:
        raise ValueError("Not enough recent data points to assess covariate drift.")

    report = Report(metrics=[DataDriftPreset()])
    snapshot = report.run(reference_data=reference_data, current_data=current_data)
    result = snapshot.dict()

    drifted_columns: List[str] = result["metrics"][0]["result"].get("drifted_columns", [])
    if drifted_columns:
        print("Covariate drift detected in:", drifted_columns)

    return drifted_columns


if __name__ == "__main__":
    drifted = detect_covariate_drift()
    print(f"Covariate drift metrics: {drifted}")

    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as f:
            f.write(f"covariate_drift={'true' if drifted else 'false'}\n")