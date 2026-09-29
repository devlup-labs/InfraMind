"""Detect concept drift using stored prediction-error history.

GitHub Actions runs in a fresh container every time, so ADWIN can't keep state
between runs in memory. Instead, each run pulls each metric's recent error
history from Postgres and replays it through a brand-new ADWIN — this still
lets ADWIN see the distribution shift, it just repeats the replay each time
instead of streaming live. Cheap enough at a few hundred points per metric.
"""
import os
from typing import Dict, List

from river import drift

from postgres_db import get_error_history

HISTORY_PER_METRIC = 500


def concept_drift_detector(history: Dict[str, List[float]] | None = None) -> List[str]:
    """Detect concept drift using prediction errors.

    Args:
        history: optional override of {metric_name: [error_value, ...]}, oldest
            first. Defaults to reading from Postgres — pass this in tests.

    Returns:
        List of metric names where concept drift was detected.
    """
    if history is None:
        history = get_error_history(HISTORY_PER_METRIC)

    drifts: List[str] = []
    for metric_name, errors in history.items():
        detector = drift.ADWIN()
        for error_value in errors:
            detector.update(error_value)
            if detector.drift_detected:
                print(f"Concept drift detected in metric: {metric_name}")
                drifts.append(metric_name)
                break  # one detection per metric is enough

    return drifts


if __name__ == "__main__":
    drifted = concept_drift_detector()
    print(f"Concept drift metrics: {drifted}")

    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a") as f:
            f.write(f"concept_drift={'true' if drifted else 'false'}\n")