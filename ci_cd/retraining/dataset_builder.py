"""Turn long-format metric data into training windows and build the 70/30 mix."""
import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config

logger = logging.getLogger(__name__)


class InsufficientNewData(Exception):
    """Raised when there is not enough fresh data to retrain."""


@dataclass
class Windows:
    context: np.ndarray
    target: np.ndarray
    end_ts: np.ndarray

    def __len__(self) -> int:
        return len(self.context)

    def take(self, idx):
        return Windows(self.context[idx], self.target[idx], self.end_ts[idx])

    def tail(self, n):
        order = np.argsort(self.end_ts)[-n:]
        return self.take(np.sort(order))

    @staticmethod
    def empty():
        return Windows(
            np.empty((0, config.CONTEXT_LENGTH), np.float32),
            np.empty((0, config.PREDICTION_LENGTH), np.float32),
            np.empty((0,), np.float64),
        )

    @staticmethod
    def concat(parts):
        parts = [p for p in parts if len(p)]
        if not parts:
            return Windows.empty()
        return Windows(
            np.concatenate([p.context for p in parts]),
            np.concatenate([p.target for p in parts]),
            np.concatenate([p.end_ts for p in parts]),
        )


def split_train_val(df, val_fraction):
    train_parts, val_parts = [], []
    for _, series in df.groupby("metric"):
        series = series.sort_values("timestamp")
        cut = int(len(series) * (1 - val_fraction))
        train_parts.append(series.iloc[:cut])
        val_parts.append(series.iloc[max(cut - config.CONTEXT_LENGTH, 0):])
    return (
        pd.concat(train_parts, ignore_index=True),
        pd.concat(val_parts, ignore_index=True),
    )


def make_windows(df):
    ctx_len, pred_len = config.CONTEXT_LENGTH, config.PREDICTION_LENGTH
    total = ctx_len + pred_len
    contexts, targets, end_ts = [], [], []
    for metric, series in df.groupby("metric"):
        series = series.sort_values("timestamp")
        values = series["value"].to_numpy(np.float32)
        stamps = series["timestamp"].to_numpy(np.float64)
        if len(values) < total:
            logger.warning("Metric '%s' has only %d points, skipping.", metric, len(values))
            continue
        for i in range(0, len(values) - total + 1, config.WINDOW_STRIDE):
            contexts.append(values[i:i + ctx_len])
            targets.append(values[i + ctx_len:i + total])
            end_ts.append(stamps[i + total - 1])
    if not contexts:
        return Windows.empty()
    return Windows(np.stack(contexts), np.stack(targets), np.array(end_ts))


def mix_baseline_and_new(baseline, new, rng):
    if len(baseline) == 0:
        raise ValueError("Baseline produced zero training windows.")
    n_base, n_new = len(baseline), len(new)
    new_needed = math.ceil(n_base * config.NEW_RATIO / config.BASELINE_RATIO)
    if n_new >= new_needed:
        base_sel, new_sel = baseline, new.tail(new_needed)
    else:
        if n_new < config.MIN_NEW_WINDOWS:
            raise InsufficientNewData(
                f"Only {n_new} new windows available (need at least {config.MIN_NEW_WINDOWS})."
            )
        keep_base = int(n_new * config.BASELINE_RATIO / config.NEW_RATIO)
        idx = np.sort(rng.choice(n_base, size=keep_base, replace=False))
        base_sel, new_sel = baseline.take(idx), new
    train = Windows.concat([base_sel, new_sel])
    total = len(train)
    stats = {
        "baseline_windows": len(base_sel),
        "new_windows": len(new_sel),
        "baseline_share": round(len(base_sel) / total, 4),
        "new_share": round(len(new_sel) / total, 4),
        "baseline_windows_available": n_base,
        "new_windows_available": n_new,
    }
    logger.info("Training mix: %s", stats)
    return train, stats
