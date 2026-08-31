import os
from typing import Dict

import torch
from chronos import ChronosPipeline
from dotenv import load_dotenv

from ci_cd.scrape_metrics import fetch_features
from ci_cd.error_calculation import calculate_error

load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME")

if MODEL_NAME is None:
    raise ValueError("MODEL_NAME is not set in the .env file.")

# Cache the Chronos model so it loads only once.
_model = None


def load_production_model():
    """
    Load the Amazon Chronos forecasting model from Hugging Face.
    """
    global _model

    if _model is not None:
        return _model

    _model = ChronosPipeline.from_pretrained(
        MODEL_NAME,
        device_map="cpu",          # Change to "cuda" later if needed.
        torch_dtype=torch.bfloat16,
    )

    return _model


def get_model_predictions(
    input_features: Dict[str, float],
) -> Dict[str, float]:
    """
    Generate predictions for each infrastructure metric.
    """

    model = load_production_model()

    prediction_dict: Dict[str, float] = {}

    for metric_name, metric_value in input_features.items():

        # NOTE:
        # Currently using one metric value as context.
        # Later this can be replaced with historical Prometheus values
        # using query_range().
        context = torch.tensor(
            [[metric_value]],
            dtype=torch.float32,
        )

        forecast = model.predict(
            context=context,
            prediction_length=1,
        )

        prediction_dict[metric_name] = float(forecast[0][0].item())

    return prediction_dict


def monitoring_cycle():
    """
    Complete 15-minute monitoring cycle.

    Pipeline:
    1. Fetch metrics from Prometheus.
    2. Feed metrics into Chronos.
    3. Generate predictions.
    4. Fetch Prometheus metrics again.
    5. Calculate prediction errors.
    6. Store errors in PostgreSQL.
    """

    print("=" * 60)
    print("Starting Monitoring Cycle")
    print("=" * 60)

    # STEP 1
    print("\nFetching Prometheus metrics...")

    initial_metrics = fetch_features()

    initial_metrics = {
        metric: value
        for metric, value in initial_metrics.items()
        if value is not None
    }

    print("Input Metrics:")
    print(initial_metrics)

    if not initial_metrics:
        raise RuntimeError("No Prometheus metrics were fetched.")

    # STEP 2
    print("\nGenerating Chronos predictions...")

    predicted_metrics = get_model_predictions(initial_metrics)

    print("Predicted Metrics:")
    print(predicted_metrics)

    # STEP 3
    print("\nFetching Prometheus metrics again...")

    latest_metrics = fetch_features()

    latest_metrics = {
        metric: value
        for metric, value in latest_metrics.items()
        if value is not None
    }

    print("Actual Metrics:")
    print(latest_metrics)

    if not latest_metrics:
        raise RuntimeError("Second Prometheus scrape failed.")

    # STEP 4
    print("\nCalculating prediction errors...")

    error_dict = calculate_error(
        actual_metrics=latest_metrics,
        predicted_metrics=predicted_metrics,
    )

    print("Prediction Errors:")
    print(error_dict)

    print("\nMonitoring Cycle Completed Successfully.")
    print("=" * 60)


if __name__ == "__main__":
    monitoring_cycle()