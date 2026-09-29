"""Local tests for the InfraMind retraining pipeline and drift detectors.

Run from ci_cd/:

    pip install pytest
    pytest test.py -v                     # pure logic, offline, no services needed
    DATABASE_URL=<url> pytest test.py -v  # + Postgres roundtrip test
    RUN_MODEL_TESTS=1 pytest test.py -v   # + real Chronos fine-tune/eval (slow, downloads
                                           #   amazon/chronos-t5-tiny, needs network)

Everything except the two opt-in groups above runs with no Prometheus, no
Postgres, and no model download — data is synthetic and injected directly.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# pytest already puts this file's directory on sys.path when there's no
# __init__.py next to it, but keep this so `python test.py` also works.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# postgres_db.py reads DATABASE_URL at import time (os.environ[...]); set a
# placeholder so importing detect_concept_drift / error_calculation doesn't
# crash before any test even runs. No connection is attempted until a DB
# function is actually called (ensure_schema is lazy) - see postgres_db.py.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

from retraining import config  # noqa: E402
from retraining.data_sources import _clean  # noqa: E402
from retraining.dataset_builder import (  # noqa: E402
    InsufficientNewData,
    make_windows,
    mix_baseline_and_new,
    split_train_val,
)


def _synthetic_series(n=200, metric="request_rate", start=0.0, step=60, seed=0):
    rng = np.random.default_rng(seed)
    ts = start + np.arange(n) * step
    values = 100 + rng.normal(0, 1, n)
    return pd.DataFrame({"timestamp": ts, "metric": metric, "value": values})


# ---------------------------------------------------------------------------
# data_sources._clean
# ---------------------------------------------------------------------------

def test_clean_fills_short_gaps_and_drops_duplicates():
    df = _synthetic_series(20)
    df.loc[5, "value"] = np.nan            # short gap (<=3 points): should be filled
    df = pd.concat([df, df.iloc[[0]]])     # exact duplicate row: should be dropped
    cleaned = _clean(df)
    assert cleaned["value"].isna().sum() == 0
    assert cleaned.duplicated(subset=["metric", "timestamp"]).sum() == 0


def test_clean_drops_points_with_long_gaps():
    df = _synthetic_series(20)
    df.loc[5:10, "value"] = np.nan         # 6-point gap, longer than the fill limit
    cleaned = _clean(df)
    assert len(cleaned) < len(df)


# ---------------------------------------------------------------------------
# dataset_builder.make_windows
# ---------------------------------------------------------------------------

def test_make_windows_shapes():
    df = _synthetic_series(200)
    windows = make_windows(df)
    expected_n = 200 - (config.CONTEXT_LENGTH + config.PREDICTION_LENGTH) + 1
    assert len(windows) == expected_n
    assert windows.context.shape == (len(windows), config.CONTEXT_LENGTH)
    assert windows.target.shape == (len(windows), config.PREDICTION_LENGTH)


def test_make_windows_skips_series_shorter_than_one_window():
    df = _synthetic_series(config.CONTEXT_LENGTH)  # one point short of a full window
    windows = make_windows(df)
    assert len(windows) == 0


def test_make_windows_handles_multiple_metrics_independently():
    too_short = config.CONTEXT_LENGTH + config.PREDICTION_LENGTH - 1  # one point shy of a window
    df = pd.concat([
        _synthetic_series(200, metric="request_rate", seed=0),
        _synthetic_series(too_short, metric="cpu_usage_rate", seed=1),  # gets skipped
    ])
    windows = make_windows(df)
    assert len(windows) == 200 - (config.CONTEXT_LENGTH + config.PREDICTION_LENGTH) + 1


# ---------------------------------------------------------------------------
# dataset_builder.split_train_val
# ---------------------------------------------------------------------------

def test_split_train_val_targets_dont_overlap_with_train():
    df = _synthetic_series(300)
    train_df, val_df = split_train_val(df, config.VAL_FRACTION)
    assert train_df["timestamp"].max() < val_df["timestamp"].max()
    # val_df's first CONTEXT_LENGTH rows are borrowed history for its first
    # window's context only - the actual held-out targets start after that.
    val_targets_only = set(val_df["timestamp"].iloc[config.CONTEXT_LENGTH:])
    assert not val_targets_only & set(train_df["timestamp"])


# ---------------------------------------------------------------------------
# dataset_builder.mix_baseline_and_new (the 70/30 logic)
# ---------------------------------------------------------------------------

def test_mix_uses_all_baseline_when_new_data_is_plentiful():
    rng = np.random.default_rng(0)
    baseline = make_windows(_synthetic_series(500, seed=1))
    new = make_windows(_synthetic_series(500, seed=2))
    train, stats = mix_baseline_and_new(baseline, new, rng)
    assert stats["baseline_windows"] == len(baseline)
    assert abs(stats["baseline_share"] - config.BASELINE_RATIO) < 0.02
    assert abs(stats["new_share"] - config.NEW_RATIO) < 0.02
    assert len(train) == stats["baseline_windows"] + stats["new_windows"]


def test_mix_subsamples_baseline_when_new_data_is_scarce_but_enough():
    rng = np.random.default_rng(0)
    baseline = make_windows(_synthetic_series(500, seed=1))
    new_points = config.MIN_NEW_WINDOWS + 5 + config.CONTEXT_LENGTH + config.PREDICTION_LENGTH - 1
    new = make_windows(_synthetic_series(new_points, seed=2))
    train, stats = mix_baseline_and_new(baseline, new, rng)
    assert stats["new_windows"] == len(new)
    assert stats["baseline_windows"] < len(baseline)
    assert abs(stats["baseline_share"] - config.BASELINE_RATIO) < 0.02


def test_mix_raises_when_new_data_is_too_scarce():
    rng = np.random.default_rng(0)
    baseline = make_windows(_synthetic_series(500, seed=1))
    tiny_new = make_windows(
        _synthetic_series(config.CONTEXT_LENGTH + config.PREDICTION_LENGTH, seed=2)
    )
    with pytest.raises(InsufficientNewData):
        mix_baseline_and_new(baseline, tiny_new, rng)


# ---------------------------------------------------------------------------
# detect_concept_drift (ADWIN over injected error history - no Postgres needed)
# ---------------------------------------------------------------------------

def test_concept_drift_flags_a_clear_error_jump():
    from detect_concept_drift import concept_drift_detector

    stable = list(np.random.default_rng(0).normal(0, 0.1, 200))
    jump = list(np.random.default_rng(1).normal(5, 0.1, 200))
    history = {"request_rate": stable + jump, "cpu_usage_rate": stable}

    drifted = concept_drift_detector(history)
    assert "request_rate" in drifted
    assert "cpu_usage_rate" not in drifted


def test_concept_drift_empty_history_returns_no_drift():
    from detect_concept_drift import concept_drift_detector

    assert concept_drift_detector({}) == []


# ---------------------------------------------------------------------------
# detect_covariate_drift (pure pivot helper - Evidently call itself is
# exercised via mocked data_sources so no live Prometheus is needed)
# ---------------------------------------------------------------------------

def test_to_wide_pivots_long_format_and_aligns_metrics():
    from detect_covariate_drift import _to_wide

    df = pd.concat([
        _synthetic_series(50, metric="request_rate", seed=0),
        _synthetic_series(50, metric="cpu_usage_rate", seed=1),
    ])
    wide = _to_wide(df)
    assert set(wide.columns) == {"request_rate", "cpu_usage_rate"}
    assert wide.isna().sum().sum() == 0


def test_detect_covariate_drift_flags_a_shifted_distribution(monkeypatch):
    import detect_covariate_drift as dcd

    reference = _synthetic_series(300, metric="request_rate", seed=0)
    shifted = _synthetic_series(300, metric="request_rate", seed=1)
    shifted["value"] += 50  # obvious distribution shift

    monkeypatch.setattr(dcd, "load_baseline", lambda: reference)
    monkeypatch.setattr(dcd, "fetch_prometheus_data", lambda hours: shifted)

    drifted = dcd.detect_covariate_drift()
    assert "request_rate" in drifted


def test_detect_covariate_drift_no_drift_when_distributions_match(monkeypatch):
    import detect_covariate_drift as dcd

    reference = _synthetic_series(300, metric="request_rate", seed=0)
    similar = _synthetic_series(300, metric="request_rate", seed=1)  # same mean/std

    monkeypatch.setattr(dcd, "load_baseline", lambda: reference)
    monkeypatch.setattr(dcd, "fetch_prometheus_data", lambda hours: similar)

    drifted = dcd.detect_covariate_drift()
    assert drifted == []


# ---------------------------------------------------------------------------
# Postgres-dependent: only runs if DATABASE_URL points at a reachable DB.
# ---------------------------------------------------------------------------

def _postgres_reachable() -> bool:
    if os.getenv("DATABASE_URL") in (None, "postgresql://test:test@localhost:5432/test"):
        return False
    try:
        import postgres_db
        postgres_db.ensure_schema()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _postgres_reachable(), reason="set a real DATABASE_URL to run this")
def test_add_error_and_get_error_history_roundtrip():
    import postgres_db

    postgres_db.add_error("test_metric_pytest", 1.23)
    history = postgres_db.get_error_history(limit_per_metric=5)
    assert "test_metric_pytest" in history
    assert 1.23 in history["test_metric_pytest"]


# ---------------------------------------------------------------------------
# Model-dependent: downloads a real (tiny) Chronos model. Slow, needs network.
#     RUN_MODEL_TESTS=1 pytest test.py -k model -v
# ---------------------------------------------------------------------------

RUN_MODEL_TESTS = os.getenv("RUN_MODEL_TESTS") == "1"
TINY_MODEL = "amazon/chronos-t5-tiny"


@pytest.mark.skipif(not RUN_MODEL_TESTS, reason="set RUN_MODEL_TESTS=1 (downloads a model)")
def test_model_fine_tune_runs_and_returns_finite_loss():
    from retraining.model_io import load_pipeline, prediction_length
    from retraining.trainer import fine_tune

    pipeline = load_pipeline(TINY_MODEL)

    original_epochs = config.EPOCHS
    original_batch = config.BATCH_SIZE
    original_pred_len = config.PREDICTION_LENGTH
    try:
        # Chronos asserts training targets match the model's own native
        # horizon - can't use our arbitrary default here, must read it off
        # the loaded model (same fix applied in retrain_model.py).
        config.PREDICTION_LENGTH = prediction_length(pipeline)
        config.EPOCHS, config.BATCH_SIZE = 1, 8
        windows = make_windows(_synthetic_series(300, seed=3))
        losses = fine_tune(pipeline, windows)
    finally:
        config.EPOCHS, config.BATCH_SIZE = original_epochs, original_batch
        config.PREDICTION_LENGTH = original_pred_len

    assert len(losses) == 1
    assert np.isfinite(losses[0])


@pytest.mark.skipif(not RUN_MODEL_TESTS, reason="set RUN_MODEL_TESTS=1 (downloads a model)")
def test_evaluate_normalized_mae_is_nonnegative():
    from retraining.evaluate import normalized_mae
    from retraining.model_io import load_pipeline, prediction_length

    pipeline = load_pipeline(TINY_MODEL)
    original_pred_len = config.PREDICTION_LENGTH
    try:
        config.PREDICTION_LENGTH = prediction_length(pipeline)
        val = make_windows(_synthetic_series(200, seed=4))
        score = normalized_mae(pipeline, val)
    finally:
        config.PREDICTION_LENGTH = original_pred_len

    assert score >= 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))