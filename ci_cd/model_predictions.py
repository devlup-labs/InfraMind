import os
from typing import Dict, Any

import pandas as pd
import mlflow
import mlflow.pyfunc
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME")
MODEL_URL = os.getenv("MODEL_URL")

if not MODEL_NAME:
    raise ValueError("MODEL_NAME is not set in the .env file.")

if not MODEL_URL:
    raise ValueError("MODEL_URL is not set in the .env file.")


def load_production_model() -> Any:
    """Load the production model from the MLflow Model Registry."""

    mlflow.set_tracking_uri(MODEL_URL)

    model = mlflow.pyfunc.load_model(
        model_uri=f"models:/{MODEL_NAME}/Production"
    )

    return model


def get_model_predictions(features: Dict[str, float]) -> float:
    """Generate a prediction from Prometheus metrics."""

    input_df = pd.DataFrame([features])

    model = load_production_model()
    prediction = model.predict(input_df)

    return float(prediction[0])

