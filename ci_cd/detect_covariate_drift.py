"""Detect covariate drift by comparing the fixed REFERENCE metric distribution
against a recent window of live Prometheus metrics, using a two-sample KS test.

The reference is data/reference.csv (a healthy snapshot of our own Prometheus metrics,
built once with `python -m retraining.build_baseline`). An Evidently HTML report is
written as a best-effort extra.
"""
import os
from typing import List

import pandas as pd
from scipy.stats import ks_2samp

from retraining import config
from retraining.data_sources import fetch_prometheus_data, load_reference

KS_PVALUE_THRESHOLD = 0.05   # significance level (Bonferroni-corrected across metrics)
KS_STAT_THRESHOLD = 0.2      # also require a practically meaningful shift


def _to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Long (timestamp | metric | value) -> wide (one column per metric).
    Buckets by STEP_SECONDS so metrics scraped a few seconds apart still line up
    in the same row."""
    bucketed = df.copy()
    bucketed["bucket"] = (bucketed["timestamp"] // config.STEP_SECONDS).astype(int)
    wide = bucketed.pivot_table(index="bucket", columns="metric", values="value", aggfunc="mean")
    return wide.dropna(how="all")


def _write_evidently_report(reference_data: pd.DataFrame, current_data: pd.DataFrame) -> None:
    """Best-effort human-readable report. Never allowed to affect the drift
    decision or crash the run - if Evidently's API has moved again, skip it."""
    try:
        from evidently import Report
        from evidently.presets import DataDriftPreset

        report = Report(metrics=[DataDriftPreset()])
        snapshot = report.run(reference_data=reference_data, current_data=current_data)
        config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot.save_html(str(config.ARTIFACT_DIR / "covariate_drift_report.html"))
    except Exception as e:  # noqa: BLE001 - deliberately broad, this is optional
        print(f"[WARN] Evidently report generation skipped: {e}")


def detect_covariate_drift() -> List[str]:
    """Compare the reference metric distribution against recent production metrics.

    Returns:
        List of metric names where covariate drift was detected.
    """
    reference_data = _to_wide(load_reference())
    current_data = _to_wide(fetch_prometheus_data(config.COVARIATE_LOOKBACK_HOURS))

    shared_cols = [c for c in reference_data.columns if c in current_data.columns]
    if not shared_cols:
        raise ValueError("No metrics in common between reference and current data.")
    reference_data, current_data = reference_data[shared_cols], current_data[shared_cols]

    if len(current_data) < 2:
        raise ValueError("Not enough recent data points to assess covariate drift.")

    _write_evidently_report(reference_data, current_data)

    alpha = KS_PVALUE_THRESHOLD / len(shared_cols)   # Bonferroni across metrics
    drifted_columns: List[str] = []
    for col in shared_cols:
        ref, cur = reference_data[col].dropna(), current_data[col].dropna()
        if len(ref) < 2 or len(cur) < 2:
            continue
        stat, p_value = ks_2samp(ref, cur)
        if p_value < alpha and stat > KS_STAT_THRESHOLD:
            drifted_columns.append(col)

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
