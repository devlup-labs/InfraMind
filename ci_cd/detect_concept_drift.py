from typing import Dict, List

from river import drift

from ci_cd.error_calculation import calculate_error
from ci_cd.model_predictions import get_model_predictions
from ci_cd.scrape_metrics import fetch_features

adwin_detectors: Dict[str, drift.ADWIN] = {}


def concept_drift_detector() -> List[str]:
    """
    Detect concept drift using prediction errors.

    Returns:
        List of metric names where concept drift was detected.
    """

    # Fetch latest Prometheus metrics.
    actual_metrics_raw = fetch_features()

    # Remove metrics that have missing values.
    actual_metrics: Dict[str, float] = {
        metric: value
        for metric, value in actual_metrics_raw.items()
        if value is not None
    }


    predicted_metrics = get_model_predictions(actual_metrics)
    error_dict = calculate_error(actual_metrics, predicted_metrics)

    drifts: List[str] = []

    for metric_name, error_value in error_dict.items():

        if metric_name not in adwin_detectors:
            adwin_detectors[metric_name] = drift.ADWIN()

        detector = adwin_detectors[metric_name]
        detector.update(error_value)

        if detector.drift_detected:
            print(f"Concept drift detected in metric: {metric_name}")
            drifts.append(metric_name)

    return drifts