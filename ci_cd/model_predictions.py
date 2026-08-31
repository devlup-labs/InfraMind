import os
from typing import Dict

import torch
from chronos import ChronosPipeline
from dotenv import load_dotenv

load_dotenv()

# Cache the loaded model
_model = None


def load_production_model() -> ChronosPipeline:
    """
    Load the Chronos forecasting model from Hugging Face.
    The model is loaded only once and cached.
    """
    global _model

    if _model is not None:
        return _model

    model_name = os.getenv("MODEL_NAME")

    if model_name is None:
        raise ValueError("MODEL_NAME is not set in the .env file.")

    _model = ChronosPipeline.from_pretrained(
        model_name,
        device_map="cpu",            # Change to "cuda" if GPU is available
        torch_dtype=torch.bfloat16,
    )

    return _model


def get_model_predictions(
    input_features: Dict[str, float],
    prediction_length: int = 1,
) -> Dict[str, float]:
    """
    Predict the next value for each infrastructure metric using Chronos.

    Args:
        input_features: Dictionary mapping metric names to observed values.
        prediction_length: Number of future timesteps to forecast.

    Returns:
        Dictionary mapping metric names to predicted next values.
    """
    model = load_production_model()
    prediction_dict: Dict[str, float] = {}

    for metric_name, metric_value in input_features.items():
        # Chronos expects a time-series context tensor.
        context = torch.tensor([[metric_value]], dtype=torch.float32)

        forecast = model.predict(
            context=context,
            prediction_length=prediction_length,
        )

        # forecast shape: [batch_size, prediction_length]
        prediction_dict[metric_name] = float(forecast[0][0].item())

    return prediction_dict