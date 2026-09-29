"""ONE-TIME script: build the 70% training baseline from Amazon Chronos' ORIGINAL training data.

    cd ci_cd
    pip install pyarrow huggingface_hub
    python -m retraining.build_replay

Streams a small random sample of series from the public `autogluon/chronos_datasets`
training corpus (tsmixup_10m + kernel_synth_1m) and writes data/baseline.csv in the
pipeline's long format. It reads part of ONE parquet shard per source (a few hundred MB
at most), not the whole ~90 GB corpus. Refuses to overwrite an existing baseline.
Commit data/baseline.csv to git afterwards.
"""
import argparse
import logging
import random

import numpy as np
import pandas as pd

from . import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_replay")

HF_CORPUS = "datasets/autogluon/chronos_datasets/training_corpus"


def _as_series(values) -> np.ndarray | None:
    """Clean one raw series. Returns None if it is unusable (too short, flat, multivariate)."""
    try:
        arr = np.asarray(values, dtype="float64")
    except (TypeError, ValueError):
        return None
    if arr.ndim != 1 or len(arr) < config.REPLAY_MIN_POINTS:
        return None
    arr = pd.Series(arr).replace([np.inf, -np.inf], np.nan).interpolate(limit_direction="both").to_numpy()
    arr = arr[: config.REPLAY_MAX_POINTS]
    if not np.isfinite(arr).all() or np.ptp(arr) == 0:
        return None
    return arr


def sample_series(parquet_file, n: int, rnd: random.Random) -> list[np.ndarray]:
    """Take up to n usable series from an open pyarrow ParquetFile, reading batch by batch."""
    names = parquet_file.schema_arrow.names
    col = "target" if "target" in names else next(c for c in names if c not in ("id", "timestamp"))
    out: list[np.ndarray] = []
    for batch in parquet_file.iter_batches(batch_size=512, columns=[col]):
        rows = batch.column(col).to_pylist()
        rnd.shuffle(rows)
        for values in rows:
            arr = _as_series(values)
            if arr is not None:
                out.append(arr)
            if len(out) >= n:
                return out
    return out


def to_long(series_list: list[np.ndarray], prefix: str) -> pd.DataFrame:
    """Series -> long format. Each series gets a unique metric id and a synthetic time axis."""
    frames = [
        pd.DataFrame({
            "timestamp": np.arange(len(a)) * config.STEP_SECONDS,
            "metric": f"{prefix}_{i}",
            "value": a,
        })
        for i, a in enumerate(series_list)
    ]
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tsmixup", type=int, default=config.REPLAY_TSMIXUP_SERIES)
    parser.add_argument("--kernelsynth", type=int, default=config.REPLAY_KERNELSYNTH_SERIES)
    args = parser.parse_args()

    if config.BASELINE_PATH.exists():
        raise SystemExit(f"{config.BASELINE_PATH} already exists. Baseline is fixed, not overwriting.")

    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    fs = HfFileSystem()
    rnd = random.Random(config.SEED)
    parts = []
    for source, n in (("tsmixup_10m", args.tsmixup), ("kernel_synth_1m", args.kernelsynth)):
        files = sorted(fs.glob(f"{HF_CORPUS}/{source}/*.parquet"))
        if not files:
            raise SystemExit(f"No parquet files found for {source} under {HF_CORPUS}")
        logger.info("Sampling %d series from %s", n, files[0])
        with fs.open(files[0], "rb") as f:
            series = sample_series(pq.ParquetFile(f), n, rnd)
        if not series:
            raise SystemExit(f"Could not extract any usable series from {source}")
        logger.info("Got %d series from %s", len(series), source)
        parts.append(to_long(series, source))

    df = pd.concat(parts, ignore_index=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.BASELINE_PATH, index=False, float_format="%.6g")
    print(f"Saved {len(df)} rows ({df['metric'].nunique()} series) to {config.BASELINE_PATH}")


if __name__ == "__main__":
    main()
