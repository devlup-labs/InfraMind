"""ONE-TIME script: snapshot a stretch of HEALTHY Prometheus data as the drift REFERENCE.

    cd ci_cd
    python -m retraining.build_baseline --days 14

This writes data/reference.csv, which detect_covariate_drift.py compares live metrics
against. (The 70% TRAINING baseline is Chronos' original data: see build_replay.py.)
Refuses to overwrite an existing file. Commit data/reference.csv to git afterwards.
"""
import argparse
import logging

from . import config
from .data_sources import fetch_prometheus_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="how many days of history to snapshot")
    args = parser.parse_args()

    if config.REFERENCE_PATH.exists():
        raise SystemExit(f"{config.REFERENCE_PATH} already exists. Reference is fixed, not overwriting.")

    df = fetch_prometheus_data(lookback_hours=args.days * 24)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.REFERENCE_PATH, index=False)
    print(f"Saved {len(df)} rows to {config.REFERENCE_PATH}")


if __name__ == "__main__":
    main()
