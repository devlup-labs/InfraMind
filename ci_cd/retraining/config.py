"""Central configuration for the retraining pipeline. Tune everything here."""
import os
from pathlib import Path

from dotenv import load_dotenv

# ------------------------------------------------------------------ paths
CI_CD_DIR = Path(__file__).resolve().parent.parent
load_dotenv(CI_CD_DIR / ".env")            # local runs; in CI real env vars are used
DATA_DIR = CI_CD_DIR / "data"
ARTIFACT_DIR = CI_CD_DIR / "artifacts"

BASELINE_PATH = DATA_DIR / "baseline.csv"      # Chronos ORIGINAL data (replay) = the 70%. Committed, NEVER modified
REFERENCE_PATH = DATA_DIR / "reference.csv"    # own healthy Prometheus data = covariate-drift reference. Committed
MODEL_OUT_DIR = ARTIFACT_DIR / "chronos_finetuned"
REPORT_PATH = ARTIFACT_DIR / "retrain_report.json"


# -------------------------------------------------------------------- env
def model_name() -> str:
    value = os.getenv("MODEL_NAME")
    if not value:
        raise ValueError("MODEL_NAME is not set.")
    return value


def prometheus_url() -> str:
    value = os.getenv("PROMETHEUS_URL")
    if not value:
        raise ValueError("PROMETHEUS_URL is not set.")
    return value.rstrip("/")


HF_TOKEN = os.getenv("HF_TOKEN")          # optional: only needed to push the model
HF_REPO_ID = os.getenv("HF_REPO_ID")      # optional: e.g. "rudri/inframind-chronos"

# ---------------------------------------------------------------- metrics
# Single source of truth: scrape_metrics.py imports this dict.
METRIC_QUERIES = {
    "request_rate": "sum(rate(http_requests_total[5m]))",
    "cpu_usage_rate": "avg(rate(process_cpu_seconds_total[5m]))",
    "memory_usage_bytes": "avg(process_resident_memory_bytes)",   # gauge: no rate()
    "p95_latency_seconds": (
        "histogram_quantile(0.95, "
        "sum(rate(http_request_duration_seconds_bucket[5m])) by (le))"
    ),
}

STEP_SECONDS = 60                    # Prometheus resolution used for training series
MAX_POINTS_PER_QUERY = 10_000        # Prometheus caps at 11,000 points per query
NEW_DATA_LOOKBACK_HOURS = 24 * 7     # how far back to pull the "new" data (retraining)
COVARIATE_LOOKBACK_HOURS = 24        # how far back to pull "current" data (drift check)

# --------------------------------------------------------------- data mix
BASELINE_RATIO = 0.70
NEW_RATIO = 0.30
MIN_NEW_WINDOWS = 50                 # below this, skip retraining (not enough new data)
VAL_FRACTION = 0.10                  # last 10% of each series (per source) held out

# ---------------------------------------------- replay sample (build_replay.py)
REPLAY_TSMIXUP_SERIES = 200          # series sampled from Chronos' tsmixup_10m
REPLAY_KERNELSYNTH_SERIES = 100      # series sampled from Chronos' kernel_synth_1m
REPLAY_MAX_POINTS = 500              # points kept per series
REPLAY_MIN_POINTS = 100              # shorter series are skipped

# ---------------------------------------------------------------- windows
CONTEXT_LENGTH = 32
PREDICTION_LENGTH = 1                # overwritten at runtime with the model's native horizon
WINDOW_STRIDE = 1

# --------------------------------------------------------------- training
EPOCHS = 3
BATCH_SIZE = 16
LEARNING_RATE = 5e-5
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.05
GRAD_CLIP = 1.0
SEED = 42

# ------------------------------------------------------------- evaluation
EVAL_BATCH_SIZE = 64
EVAL_NUM_SAMPLES = 20
