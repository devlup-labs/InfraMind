"""15-minute monitoring cycle: Prometheus -> Chronos -> prediction errors -> PostgreSQL."""
import logging
from typing import Any, Dict, List

import torch
from chronos import ChronosPipeline
from dotenv import load_dotenv

from retraining import config
from retraining.data_sources import fetch_prometheus_data
from error_calculation import calculate_error

load_dotenv()
logger = logging.getLogger(__name__)

# Cache the Chronos model so it loads only once.
_model: Any = None


def load_production_model() -> Any:
    """
    Load the Chronos forecasting model (MODEL_NAME: base model or our fine-tuned
    Hugging Face repo; a private repo needs HF_TOKEN in the environment).
    """
    global _model
    if _model is not None:
        return _model

    _model = ChronosPipeline.from_pretrained(
        config.model_name(),
        device_map="cpu",
        torch_dtype=torch.float32,
    )
    return _model


def fetch_history(lookback_hours: int = 1) -> Dict[str, List[float]]:
    """Recent per-metric series from Prometheus, oldest first."""
    df = fetch_prometheus_data(lookback_hours=lookback_hours)
    return {
        metric: group.sort_values("timestamp")["value"].tolist()
        for metric, group in df.groupby("metric")
    }


def get_model_predictions(history: Dict[str, List[float]]) -> Dict[str, float]:
    """One-step-ahead forecast per metric from its own recent history."""
    model = load_production_model()
    prediction_dict: Dict[str, float] = {}

    for metric_name, series in history.items():
        if not series:
            continue
        context = torch.tensor(series[-config.CONTEXT_LENGTH:], dtype=torch.float32)
        forecast = model.predict(context, prediction_length=1)
        prediction_dict[metric_name] = float(forecast[0].median().item())

    return prediction_dict


def monitoring_cycle() -> Dict[str, float]:
    """
    Complete 15-minute monitoring cycle (stateless, so it works in CI).

    Pipeline:
    1. Fetch recent metric history from Prometheus.
    2. Hold out the newest point of each metric as the "actual".
    3. Feed the earlier points into Chronos and forecast one step ahead.
    4. Calculate prediction errors (actual - predicted).
    5. Store errors in PostgreSQL.
    """
    history = fetch_history()
    usable = {m: s for m, s in history.items() if len(s) >= 2}

    actuals = {m: s[-1] for m, s in usable.items()}
    predictions = get_model_predictions({m: s[:-1] for m, s in usable.items()})

    errors = calculate_error(actuals, predictions)
    logger.info("Monitoring cycle stored %d errors.", len(errors))
    return errors


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    monitoring_cycle()
