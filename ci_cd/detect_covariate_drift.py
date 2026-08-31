"""
Detects covariate drift by comparing the latest scraped Prometheus metrics
with the model's expected feature distribution using Evidently.
"""

from typing import Dict, List 
import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset

from ci_cd.model_predictions import get_model_predictions
from ci_cd.scrape_metrics import fetch_features


def detect_covariate_drift() -> List[str]:
    """
    Compare current metrics against the model's predicted feature values
    using Evidently DataDriftPreset.

    Returns:
        List of metric names where covariate drift was detected.
    """

  
    raw_metrics = fetch_features()

    
    reference_metrics: Dict[str, float] = {
        metric: value
        for metric, value in raw_metrics.items()
        if value is not None
    }

    if not reference_metrics:
        raise ValueError("No valid reference metrics were found.")


    predicted_metrics = get_model_predictions(reference_metrics)

    
    reference_data = pd.DataFrame([reference_metrics])
    current_data = pd.DataFrame([predicted_metrics])


    report = Report(metrics=[DataDriftPreset()])

    snapshot = report.run(
        reference_data=reference_data,
        current_data=current_data,
    )

    result = snapshot.dict()

    drifted_columns: List[str] = (
        result["metrics"][0]["result"].get("drifted_columns", [])
    )

    if drifted_columns:
        print("Covariate drift detected in:", drifted_columns)

    return drifted_columns