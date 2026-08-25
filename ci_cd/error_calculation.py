"""
Compares actual (scraped) metric values against the model's predicted
values for the same metrics, computes the per-metric error, and logs each
one to the errors table.
"""

import logging
from typing import Dict, Optional

from model_predictions import get_model_predictions
from postgres_db import add_error, ensure_schema
from scrape_metrics import fetch_features

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_error(
    actual_metrics: Dict[str, Optional[float]],
    predicted_metrics: Dict[str, Optional[float]],
) -> Dict[str, float]:
    error_dict: Dict[str, float] = {}

    for metric_name, actual_value in actual_metrics.items():
        predicted_value = predicted_metrics.get(metric_name)

        if actual_value is None or predicted_value is None:
            logger.warning(
                "Skipping metric '%s': actual=%s predicted=%s",
                metric_name, actual_value, predicted_value,
            )
            continue

        error = actual_value - predicted_value
        error_dict[metric_name] = error

        add_error(metric_name, error, solved=False)
        logger.info("metric=%s actual=%.4f predicted=%.4f error=%.4f",
                    metric_name, actual_value, predicted_value, error)

    return error_dict


