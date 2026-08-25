import os
from typing import Any, Dict, Optional

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


def get_model_predictions(input_features: Dict[str, Optional[float]]) -> float:
    """
    Generate a prediction from the production model given Prometheus metrics.

    Args:
        input_features: Dictionary of feature name -> value.

    Returns:
        Predicted value as a float.
    """
    clean_features = {k: v for k, v in input_features.items() if v is not None}
    input_df = pd.DataFrame([clean_features])

    model = load_production_model()
    prediction = model.predict(input_df)

    return float(prediction.item())