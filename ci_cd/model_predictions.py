import os
from typing import Any, Dict, Optional , List

import mlflow
import mlflow.pyfunc
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def load_production_model() -> Any:
    """Load the production ML model from the MLflow Model Registry."""
    model_name = os.getenv("MODEL_NAME")
    model_url = os.getenv("MODEL_URL")

    if model_name is None:
        raise ValueError("MODEL_NAME is not set in the .env file.")
    if model_url is None:
        raise ValueError("MODEL_URL is not set in the .env file.")

    mlflow.set_tracking_uri(model_url)
    return mlflow.pyfunc.load_model(model_uri=f"models:/{model_name}/Production")

def get_model_predictions(
    input_features: Dict[str, Optional[float]]
) -> List[float]:
    """
    Generate one prediction for each metric.

    Returns:
        List of predicted metric values.
    """

    prediction_list = []

    model = load_production_model()

    for metric_name, metric_value in input_features.items():

        if metric_value is None:
            continue

        input_df = pd.DataFrame([
            {metric_name: metric_value}
        ])

        prediction = model.predict(input_df)

        prediction_list.append(float(prediction.item()))

    return prediction_list