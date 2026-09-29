"""Entry point for the retraining step of the InfraMind CI/CD pipeline.

    cd ci_cd && python retrain_model.py   (or: python -m retraining.retrain_model)

Flow:
    1. load the fixed baseline (70% = Chronos original-data replay) and fetch new
       Prometheus data (30%)
    2. hold out the newest slice of the NEW data for validation (time-ordered)
    3. build the 70/30 training mix
    4. score the current model on the held-out live data, fine-tune, score again
    5. promote (save + optional HF push) only if the new model is better on LIVE data
"""
import json
import logging
import os
import sys

import numpy as np

from retraining import config
from retraining.data_sources import fetch_new_data, load_baseline
from retraining.dataset_builder import (
    InsufficientNewData,
    make_windows,
    mix_baseline_and_new,
    split_train_val,
)
from retraining.evaluate import normalized_mae
from retraining.model_io import load_pipeline, prediction_length, push_to_hub, save_pipeline
from retraining.trainer import fine_tune

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("retrain")


def set_github_output(key: str, value: str) -> None:
    """Expose a result to later workflow steps (${{ steps.<id>.outputs.<key> }})."""
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def write_report(report: dict) -> None:
    config.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_PATH.write_text(json.dumps(report, indent=2, default=float))
    logger.info("Report written to %s", config.REPORT_PATH)


def main() -> int:
    rng = np.random.default_rng(config.SEED)

    # 0. load the model FIRST. Training windows' target length must exactly match this
    #    model's native prediction_length (Chronos enforces it).
    pipeline = load_pipeline(config.model_name())
    config.PREDICTION_LENGTH = prediction_length(pipeline)
    logger.info("Model's native prediction_length=%d (used for training windows)", config.PREDICTION_LENGTH)

    # 1. data: 70% = Chronos original-data replay, 30% = fresh Prometheus data
    baseline_df = load_baseline()
    new_df = fetch_new_data()

    # 2. only the NEW (live) data is held out: promotion is judged on OUR metrics
    new_train_df, new_val_df = split_train_val(new_df, config.VAL_FRACTION)
    base_train = make_windows(baseline_df)
    new_train, new_val = make_windows(new_train_df), make_windows(new_val_df)

    # 3. 70/30 mix
    try:
        train, mix_stats = mix_baseline_and_new(base_train, new_train, rng)
    except InsufficientNewData as e:
        logger.warning("Skipping retraining: %s", e)
        write_report({"retrained": False, "promoted": False, "reason": str(e)})
        set_github_output("promoted", "false")
        return 0

    if len(new_val) == 0:
        reason = "No held-out live validation windows available."
        logger.warning("Skipping retraining: %s", reason)
        write_report({"retrained": False, "promoted": False, "reason": reason})
        set_github_output("promoted", "false")
        return 0
    val = new_val

    # 4. evaluate -> train -> evaluate
    score_before = normalized_mae(pipeline, val)
    logger.info("Val normalized MAE before: %.4f", score_before)

    losses = fine_tune(pipeline, train)

    score_after = normalized_mae(pipeline, val)
    logger.info("Val normalized MAE after:  %.4f", score_after)

    # 5. promote only if better
    promoted = score_after < score_before
    pushed = False
    if promoted:
        model_dir = save_pipeline(pipeline, config.MODEL_OUT_DIR)
        pushed = push_to_hub(model_dir)
    else:
        logger.warning("New model is not better than the current one, not promoting.")

    write_report({
        "retrained": True,
        "promoted": promoted,
        "pushed_to_hub": pushed,
        "val_windows": len(val),
        "mix": mix_stats,
        "epoch_losses": losses,
        "val_nmae_before": score_before,
        "val_nmae_after": score_after,
    })
    set_github_output("promoted", str(promoted).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
