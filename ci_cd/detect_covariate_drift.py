from typing import Dict, Optional, List
import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset

from scrape_metrics import fetch_features
from model_predictions import get_model_predictions

def detect_covariate_drift() -> List[str]:
    """
    Compare the reference Prometheus metrics against
    the model's predicted metric distributions using Evidently.

    Returns:
        List of metric names where drift was detected.
    """
    reference_metrics: Dict[str, Optional[float]] = fetch_features()

    reference_metrics = {
        name: value
        for name, value in reference_metrics.items()
        if value is not None
    }

    if not reference_metrics:
        raise ValueError(
            "No valid reference metrics were found."

    prediction_list = get_model_predictions(
        reference_metrics
    )

    metric_names = list(reference_metrics.keys())

    if len(metric_names) != len(prediction_list):
        raise ValueError(
            "Number of predictions does not match "
            "number of metrics."
        )

    predicted_metrics = {
        metric_name: prediction
        for metric_name, prediction in zip(
            metric_names,
            prediction_list
        )
    }

    reference_data = pd.DataFrame(
        [reference_metrics]
    )

    current_data = pd.DataFrame(
        [predicted_metrics]
    )
    report = Report(
        [
            DataDriftPreset()
        ]
    )

    result = report.run(
        current_data=current_data,
        reference_data=reference_data
    )

    result_dict = result.dict()

    drifted_metrics = []

    for metric in result_dict.get("metrics", []):

        value = metric.get("value", {})

        if not isinstance(value, dict):
            continue

        metric_name = value.get("column")
        drift_detected = value.get("drift_detected")

        if (
            metric_name is not None
            and drift_detected is True
        ):

    if drifted_metrics:
        print(
            "Drift detected in:"
        )

        for metric in drifted_metrics:
            print(f"  - {metric}")
    else:
        print(
            "No drift detected."
        )

    return drifted_metrics

