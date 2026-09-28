"""ONE-TIME script: snapshot a long stretch of Prometheus data as the fixed baseline.

    cd ci_cd
    python -m retraining.build_baseline --days 14

Refuses to overwrite an existing baseline, so the 70% stays the same forever.
Commit data/baseline.csv to git afterwards.
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

    if config.BASELINE_PATH.exists():
        raise SystemExit(f"{config.BASELINE_PATH} already exists. Baseline is fixed, not overwriting.")

    df = fetch_prometheus_data(lookback_hours=args.days * 24)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.BASELINE_PATH, index=False)
    print(f"Saved {len(df)} rows to {config.BASELINE_PATH}")


if __name__ == "__main__":
    main()