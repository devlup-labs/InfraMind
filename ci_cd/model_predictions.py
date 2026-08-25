import os
from typing import Dict, Any

import pandas as pd
import mlflow
import mlflow.pyfunc
from dotenv import load_dotenv

load_dotenv()


_model = None


def load_production_model() -> Any:
    """
    Load the production ML model from the MLflow Model Registry.
    """
    global _model

    if _model is not None:
        return _model

    model_name = os.getenv("MODEL_NAME")
    model_url = os.getenv("MODEL_URL")

    if model_name is None:
        raise ValueError("MODEL_NAME is not set in the .env file.")

    if model_url is None:
        raise ValueError("MODEL_URL is not set in the .env file.")

    mlflow.set_tracking_uri(model_url)

    _model = mlflow.pyfunc.load_model(
        model_uri=f"models:/{model_name}/Production"
    )

    return _model


def get_model_predictions(
    input_features: Dict[str, float]
) -> Dict[str, float]:
    """
    Predict the next value for each metric.

    Args:
        input_features: Dictionary mapping metric names to observed values.

    Returns:
        Dictionary mapping metric names to predicted values.
    """
    model = load_production_model()
    prediction_dict: Dict[str, float] = {}

    for metric_name, metric_value in input_features.items():
        input_df = pd.DataFrame([{metric_name: metric_value}])

        prediction = model.predict(input_df)

        prediction_dict[metric_name] = float(prediction.item())

    return prediction_dict