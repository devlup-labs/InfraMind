from typing import Dict, Optional

from model_predictions import get_model_predictions
from scrape_metrics import fetch_features
from postgres_db import ensure_schema, add_error


def calculate_error(
    actual_metrics: Dict[str, Optional[float]],
    predicted_metrics: Dict[str, Optional[float]],
) -> Dict[str, float]:

    error_dict: Dict[str, float] = {}

    ensure_schema()

    for metric_name, actual_value in actual_metrics.items():
        predicted_value = predicted_metrics.get(metric_name)

        if actual_value is None or predicted_value is None:
            continue

        error = actual_value - predicted_value

        error_dict[metric_name] = error

        add_error(metric_name, error, False)

    return error_dict