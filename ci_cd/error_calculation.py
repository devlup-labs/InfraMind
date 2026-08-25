"""
Compares actual (scraped) metric values against the model's predicted
values for the same metrics, computes the per-metric error, and logs each
one to the errors table.
"""

import logging
from typing import Dict

from ci_cd.postgres_db import add_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_error(
    actual_metrics: Dict[str, float],
    predicted_metrics: Dict[str, float],
) -> Dict[str, float]:
    """
    Calculate prediction error for each metric and store it in PostgreSQL.

    Args:
        actual_metrics: Latest scraped metric values.
        predicted_metrics: ML model predictions for the same metrics.

    Returns:
        Dictionary mapping metric names to prediction errors.
    """
    error_dict: Dict[str, float] = {}

    for metric_name, actual_value in actual_metrics.items():
        predicted_value = predicted_metrics.get(metric_name)

        # Skip if prediction is missing for any metric.
        if predicted_value is None:
            logger.warning(
                "Skipping metric '%s': prediction not available.",
                metric_name,
            )
            continue

        error = actual_value - predicted_value
        error_dict[metric_name] = error

        add_error(metric_name, error, solved=False)

        logger.info(
            "metric=%s actual=%.4f predicted=%.4f error=%.4f",
            metric_name,
            actual_value,
            predicted_value,
            error,
        )

    return error_dict
