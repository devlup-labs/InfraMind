from typing import Dict, List, Optional

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset

from ci_cd.model_predictions import get_model_predictions
from ci_cd.scrape_metrics import fetch_features


def detect_covariate_drift() -> List[str]:
    """
    Compare current metrics against the model's predicted metric values
    using Evidently.

    Returns:
        List of metric names where drift was detected.
    """
    raw_metrics: Dict[str, Optional[float]] = fetch_features()
    reference_metrics = {k: v for k, v in raw_metrics.items() if v is not None}

    if not reference_metrics:
        raise ValueError("No valid reference metrics were found.")

    predicted_metrics = get_model_predictions(reference_metrics)

    reference_data = pd.DataFrame([reference_metrics])
    current_data = pd.DataFrame([predicted_metrics])

    report = Report(metrics=[DataDriftPreset()])
    result = report.run(reference_data=reference_data, current_data=current_data)

    drifted_columns = result.dict()["metrics"][0]["result"].get("drifted_columns", [])
    return drifted_columns