"""Detect concept drift using stored prediction-error history.

GitHub Actions runs in a fresh container every time, so ADWIN can't keep state
between runs in memory. Instead, each run pulls each metric's recent error
history from Postgres and replays it through a brand-new ADWIN.

Two rules keep the daily replay from re-alerting on old news:
  * Only drift detected inside the newest RECENT_POINTS errors counts
    (96 x 15 min = the last 24h, i.e. since the previous daily run).
  * ADWIN detects a change in the MEAN, and prediction errors are signed
    (actual - predicted), so a model getting worse in both directions averages
    out to ~0. We feed it the absolute error instead.
"""
import math
import os
from typing import Dict, List, Optional

from river import drift

from postgres_db import get_error_history

HISTORY_PER_METRIC = 500
RECENT_POINTS = 96   # only drift inside the newest N points is reported
MIN_POINTS = 30      # too little history -> don't judge


def concept_drift_detector(
    history: Optional[Dict[str, List[float]]] = None,
    recent_points: int = RECENT_POINTS,
) -> List[str]:
    """Detect concept drift using prediction errors.

    Args:
        history: optional override of {metric_name: [error_value, ...]}, oldest
            first. Defaults to reading from Postgres - pass this in tests.
        recent_points: a drift only counts if ADWIN fires within this many
            newest points.

    Returns:
        List of metric names where concept drift was detected.
    """
    if history is None:
        history = get_error_history(HISTORY_PER_METRIC)

    drifts: List[str] = []
    for metric_name, raw_errors in history.items():
        errors = [abs(e) for e in raw_errors if e is not None and math.isfinite(e)]
        if len(errors) < MIN_POINTS:
            continue

        detector = drift.ADWIN()
        cutoff = len(errors) - recent_points
        for i, error_value in enumerate(errors):
            detector.update(error_value)
            if detector.drift_detected and i >= cutoff:
                print(f"Concept drift detected in metric: {metric_name}")
                drifts.append(metric_name)
                break  # one detection per metric is enough

    return drifts


if __name__ == "__main__":
    drifted = concept_drift_detector()
    print(f"Concept drift metrics: {drifted}")

    # Expose the result to later workflow steps: steps.concept.outputs.concept_drift
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as f:
            f.write(f"concept_drift={'true' if drifted else 'false'}\n")
