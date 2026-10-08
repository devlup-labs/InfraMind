"""Score a pipeline on held-out windows so we only promote a model that is actually better."""
import numpy as np
import torch
from chronos import ChronosPipeline

from . import config
from .dataset_builder import Windows


def normalized_mae(pipeline: ChronosPipeline, val: Windows) -> float:
    """Scale-free MAE: |median forecast - actual| / mean(|context|), averaged over windows.
    Normalising lets latency, RPS and error-rate (very different scales) share one score."""
    if len(val) == 0:
        raise ValueError("Validation set is empty.")

    errors = []
    for i in range(0, len(val), config.EVAL_BATCH_SIZE):
        ctx = val.context[i:i + config.EVAL_BATCH_SIZE]
        tgt = val.target[i:i + config.EVAL_BATCH_SIZE]

        with torch.no_grad():
            forecast = pipeline.predict(
                torch.from_numpy(ctx),
                prediction_length=config.PREDICTION_LENGTH,
                num_samples=config.EVAL_NUM_SAMPLES,
            )
        pred = forecast.median(dim=1).values.numpy()          # (batch, prediction_length)

        denom = np.abs(ctx).mean(axis=1, keepdims=True) + 1e-6
        errors.append((np.abs(pred - tgt) / denom).mean(axis=1))

    return float(np.concatenate(errors).mean())
