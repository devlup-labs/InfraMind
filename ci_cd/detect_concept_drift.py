from typing import List

from river import drift

from scrape_metrics import fetch_features
from model_predictions import get_model_predictions
from error_calculation import calculate_error


def concept_drift_detector() -> List[str]:
    """
    Detect concept drift using the prediction errors
    calculated by error_calculation.py.

    Returns:
        List of metric names where concept drift was detected.
    """

    actual_metrics = fetch_features()
    
    prediction_list = get_model_predictions(actual_metrics)
    #here actual metrics need to be replaced with some dummy metrics initially

    metric_names = list(actual_metrics.keys())

    predicted_metrics = {
        metric_name: prediction
        for metric_name, prediction in zip(
            metric_names,
            prediction_list
        )
    }

    error_dict = calculate_error(
        actual_metrics,
        predicted_metrics
    )

    drifts = []

    for metric_name, error_value in error_dict.items():

        detector = drift.ADWIN()

        detector.update(error_value)

        if detector.drift_detected:
            print(
                f"Concept drift detected in metric: {metric_name}"
            )
            drifts.append(metric_name)

    return drifts