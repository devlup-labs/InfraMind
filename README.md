# CI/CD Pipeline: Automated Infrastructure Monitoring, Drift Detection & Retraining

## Overview

The CI/CD pipeline in **InfraMind** continuously monitors Kubernetes infrastructure metrics, forecasts expected system behaviour using a Machine Learning model, measures prediction error, detects drift, and retrains the forecasting model when needed. The pipeline is fully automated through GitHub Actions and operates on two independent schedules:

* **Every 15 minutes:** Monitoring, forecasting, and error logging.
* **Every 24 hours:** Concept drift detection, covariate drift detection, and conditional model retraining.

This design ensures that infrastructure behaviour is continuously evaluated while retraining is performed only when the deployed forecasting model begins to drift from production data.

---

# Pipeline Architecture

```text
                    Every 15 Minutes
┌────────────────────────────────────────────────────────────┐
│                    GitHub Action Trigger                   │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
                Fetch Prometheus Metrics
                           │
                           ▼
             Chronos Forecasting Model
                           │
                           ▼
              Predicted Infrastructure Metrics
                           │
                           ▼
           Fetch Latest Prometheus Metrics
                           │
                           ▼
          Calculate Prediction Error (Actual − Predicted)
                           │
                           ▼
            Store Errors in PostgreSQL Database


                    Every 24 Hours
┌────────────────────────────────────────────────────────────┐
│                    GitHub Action Trigger                   │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
          Read Stored Error History (PostgreSQL)
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
     Concept Drift Detection      Covariate Drift Detection
          (ADWIN)                     (Evidently)
             │                           │
             └─────────────┬─────────────┘
                           ▼
              Drift Detected? ── No ──► Stop
                           │
                          Yes
                           ▼
        Build Training Set: 70% Fixed Baseline + 30% New Data
                           │
                           ▼
                Fine-tune Chronos (retrain_model.py)
                           │
                           ▼
        Evaluate on Held-out Data (Before vs After)
                           │
                           ▼
          Better? ── Yes ──► Save / Push Model to Hugging Face
                     └─ No ──► Keep Current Model
```

---

# Directory Structure

```text
InfraMind/
├── .github/
│   └── workflows/                 # must live at the repo root for GitHub Actions
│       ├── monitoring_cycle_15.yml
│       └── monitoring_cycle_24.yml
│
└── ci_cd/
    ├── scrape_metrics.py          # Fetch metrics from Prometheus.
    ├── model_predictions.py       # Chronos inference + monitoring cycle.
    ├── error_calculation.py       # Compute prediction errors.
    ├── postgres_db.py             # PostgreSQL helper functions.
    │
    ├── detect_concept_drift.py    # ADWIN concept drift detection.
    ├── detect_covariate_drift.py  # Evidently covariate drift detection.
    ├── retrain_model.py           # Retraining entry point.
    │
    ├── retraining/                # Retraining package.
    │   ├── config.py              # All retraining settings (mix ratio, epochs, queries...).
    │   ├── data_sources.py        # Load baseline CSV, pull new data from Prometheus.
    │   ├── dataset_builder.py     # Windowing, train/val split, 70/30 mixing.
    │   ├── trainer.py             # Chronos fine-tuning loop.
    │   ├── evaluate.py            # Before/after scoring on held-out windows.
    │   ├── model_io.py            # Load, save, push model to Hugging Face.
    │   └── build_baseline.py      # ONE-TIME baseline snapshot script.
    │
    ├── data/
    │   └── baseline.csv           # Fixed baseline dataset (committed, never modified).
    └── artifacts/                 # Retrained model + report (git-ignored).
```

---

# Components

## 1. Prometheus Metrics Collection (`scrape_metrics.py`)

This module acts as the data ingestion layer of the pipeline.

### Responsibilities

* Connects to the Prometheus server.
* Executes PromQL queries.
* Retrieves the latest infrastructure metrics.
* Returns metrics as a Python dictionary.

### Metrics Collected

| Metric         | Description                      |
| -------------- | -------------------------------- |
| Request Rate   | Requests processed per second.   |
| CPU Usage Rate | Average CPU utilization.         |
| Memory Usage   | Resident memory usage in bytes.  |
| P95 Latency    | 95th percentile request latency. |

Example output:

```python
{
    "request_rate": 148.72,
    "cpu_usage_rate": 0.63,
    "memory_usage_bytes": 523485184,
    "p95_latency_seconds": 0.41,
}
```

These metrics become the input features for the forecasting model.

---

## 2. Forecasting Layer (`model_predictions.py`)

InfraMind uses **Amazon Chronos**, a transformer-based time-series forecasting model, to estimate the expected behaviour of infrastructure metrics.

### Responsibilities

* Loads the Chronos model from Hugging Face.
* Receives infrastructure metrics.
* Generates predicted values.
* Executes the complete monitoring cycle every 15 minutes.

### Monitoring Cycle

Each execution performs the following sequence:

1. Fetch metrics from Prometheus.
2. Generate predicted metrics using Chronos.
3. Fetch Prometheus metrics again.
4. Compare predictions against live metrics.
5. Forward prediction errors for storage.

This module acts as the orchestrator for the complete monitoring workflow.

---

## 3. Error Calculation (`error_calculation.py`)

This module evaluates forecasting performance.

### Formula

For every infrastructure metric,

```text
Prediction Error = Actual Metric − Predicted Metric
```

### Responsibilities

* Computes prediction error for each metric.
* Logs every error independently.
* Sends errors to PostgreSQL.

Example:

| Metric       | Actual | Predicted | Error |
| ------------ | ------ | --------- | ----- |
| CPU Usage    | 0.71   | 0.66      | 0.05  |
| Request Rate | 160    | 154       | 6     |
| Latency      | 0.45   | 0.39      | 0.06  |

Each metric produces one error record.

---

## 4. PostgreSQL Storage (`postgres_db.py`)

PostgreSQL stores the historical prediction errors generated during every monitoring cycle.

### Table: `errors`

| Column      | Type             | Description                                           |
| ----------- | ---------------- | ----------------------------------------------------- |
| error_id    | BIGSERIAL (PK)   | Primary key.                                          |
| metric_name | VARCHAR(100)     | Infrastructure metric name.                           |
| time        | TIMESTAMPTZ      | Timestamp of monitoring cycle.                        |
| error_value | DOUBLE PRECISION | Prediction error.                                     |
| solved      | BOOLEAN          | Flag indicating whether the anomaly has been handled. |

### Responsibilities

* Creates the table if it does not exist (`ensure_schema()`).
* Inserts prediction errors.
* Provides historical error data for drift detection.

The database acts as the long-term memory of the monitoring pipeline.

---

# GitHub Actions Workflows

> Workflow files must be placed in `.github/workflows/` at the **repository root**. GitHub ignores workflow files anywhere else.

## Monitoring Workflow (Every 15 Minutes)

**Workflow:** `monitoring_cycle_15.yml`

### Trigger

```yaml
cron: "*/15 * * * *"
```

### Responsibilities

* Start monitoring cycle.
* Scrape Prometheus metrics.
* Generate Chronos predictions.
* Fetch live metrics.
* Calculate prediction errors.
* Store errors in PostgreSQL.

### Output

Every execution appends a new batch of prediction errors to the database.

---

## Drift Detection & Retraining Workflow (Every 24 Hours)

**Workflow:** `monitoring_cycle_24.yml`

### Trigger

```yaml
cron: "0 0 * * *"
```

### Responsibilities

* Read historical prediction errors.
* Perform concept drift detection.
* Perform covariate drift detection.
* Set `DRIFT_DETECTED=true` (via `$GITHUB_ENV`) if either detector fires.
* Run `retrain_model.py` only when `DRIFT_DETECTED == 'true'`.
* Upload the retraining report as a workflow artifact.

This workflow is completely independent of the monitoring workflow.

---

# Drift Detection

## Concept Drift Detection (`detect_concept_drift.py`)

Concept drift measures whether the forecasting model's prediction error has changed significantly over time.

### Algorithm Used

**ADWIN (Adaptive Windowing)**

ADWIN continuously monitors the stream of prediction errors and automatically detects statistically significant distribution changes.

### Input

* Historical prediction errors from PostgreSQL.

### Output

* Drift detected.
* No drift detected.

If drift is detected, the retraining workflow becomes eligible to run.

---

## Covariate Drift Detection (`detect_covariate_drift.py`)

Covariate drift measures whether the distribution of infrastructure metrics has changed.

### Library Used

**Evidently AI**

### Comparison

| Reference Dataset             | Current Dataset           |
| ----------------------------- | ------------------------- |
| Historical production metrics | Latest production metrics |

### Output

* Drift score.
* Feature-wise drift report.
* Overall drift status.

---

# Model Retraining

`retrain_model.py` is executed only when drift detection indicates that the deployed forecasting model is no longer representative of production behaviour.

### Retraining Trigger

Retraining occurs only if:

* Concept drift is detected, or
* Covariate drift exceeds the configured threshold.

This prevents unnecessary retraining and reduces operational cost.

## Training Data: 70% Baseline / 30% New

| Source       | Share | Origin                                                          |
| ------------ | ----- | --------------------------------------------------------------- |
| Baseline     | 70%   | `ci_cd/data/baseline.csv`. Fixed snapshot, never changes.       |
| New data     | 30%   | Recent metrics scraped from Prometheus (last 7 days by default).|

Both sources use the same long format: `timestamp | metric | value`.

**Mixing rules**

* Enough new data: all baseline windows + the most recent new windows, sized so new data is exactly 30% of the training set.
* Not enough new data (but at least `MIN_NEW_WINDOWS`): all new windows are kept and the baseline is subsampled (fixed seed) to preserve the 70/30 ratio.
* Fewer than `MIN_NEW_WINDOWS` new windows: retraining is skipped.

The baseline is created once with `python -m retraining.build_baseline --days 14` (run from `ci_cd/`). The script refuses to overwrite an existing file. Commit `data/baseline.csv` to git.

## Retraining Flow

1. Load the fixed baseline and fetch new data from Prometheus.
2. Split each source in time order per metric (last 10% held out for validation), then build sliding windows (`CONTEXT_LENGTH` context points, next-step target).
3. Build the 70/30 training mix.
4. Score the current model on the held-out windows (normalized MAE).
5. Fine-tune Chronos (full fine-tune, float32, CPU).
6. Score the fine-tuned model on the same held-out windows.
7. **Promote only if the new score is better.** The model is saved to `ci_cd/artifacts/chronos_finetuned/` and pushed to Hugging Face if `HF_TOKEN` and `HF_REPO_ID` are set.
8. Write `artifacts/retrain_report.json` and expose a `promoted` step output.

## Deploying the Retrained Model

The monitoring cycle loads whatever `MODEL_NAME` points to. After the first successful promotion, set `MODEL_NAME` (the repository variable and `.env`) to the value of `HF_REPO_ID`, otherwise inference keeps using the original model. If the Hugging Face repository is private, the inference environment also needs `HF_TOKEN`.

## Retraining Configuration (`retraining/config.py`)

| Setting                   | Default | Purpose                                         |
| ------------------------- | ------- | ----------------------------------------------- |
| `BASELINE_RATIO`/`NEW_RATIO` | 0.70 / 0.30 | Training mix.                              |
| `NEW_DATA_LOOKBACK_HOURS` | 168     | How far back to pull new data.                  |
| `MIN_NEW_WINDOWS`         | 50      | Minimum new windows required to retrain.        |
| `CONTEXT_LENGTH`          | 32      | Context points per training window.             |
| `PREDICTION_LENGTH`       | 1       | Forecast horizon (matches inference).           |
| `EPOCHS`/`BATCH_SIZE`/`LEARNING_RATE` | 3 / 16 / 5e-5 | Fine-tuning hyperparameters.     |
| `METRIC_QUERIES`          | -       | PromQL per metric. Keys must match `scrape_metrics.py`. |

---

# Environment Variables

Create a `.env` file inside the repository root.

```env
MODEL_NAME=amazon/chronos-t5-small

PROMETHEUS_URL=http://localhost:9090

DATABASE_URL=postgresql://postgres:<password>@localhost:5432/postgres

# Optional: only needed to publish a retrained model
HF_TOKEN=<hugging-face-token>
HF_REPO_ID=<username>/inframind-chronos
```

| Variable       | Purpose                                                  |
| -------------- | -------------------------------------------------------- |
| MODEL_NAME     | Hugging Face Chronos model identifier (or fine-tuned repo). |
| PROMETHEUS_URL | Prometheus server endpoint. Must be reachable from the GitHub runner in CI. |
| DATABASE_URL   | PostgreSQL connection string.                            |
| HF_TOKEN       | Hugging Face token used to push the retrained model.     |
| HF_REPO_ID     | Target Hugging Face repository for the retrained model.  |

In GitHub Actions, `MODEL_NAME`, `PROMETHEUS_URL` and `HF_REPO_ID` are repository **variables**; `DATABASE_URL` and `HF_TOKEN` are **secrets**.

---

# Running the Pipeline Locally

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Retraining additionally needs `chronos-forecasting`, `pandas`, `numpy`, `requests` and `huggingface_hub`.

## 2. Start PostgreSQL

```bash
sudo systemctl start postgresql
```

## 3. Start Prometheus

Ensure Prometheus is accessible at the configured URL.

## 4. Execute One Monitoring Cycle

```bash
cd ci_cd
python model_predictions.py
```

The execution performs:

1. Metric scraping.
2. Forecast generation.
3. Live metric scraping.
4. Error calculation.
5. PostgreSQL insertion.

## 5. Create the Baseline (once)

```bash
cd ci_cd
python -m retraining.build_baseline --days 14
```

## 6. Run Retraining Manually

```bash
cd ci_cd
python retrain_model.py
```

---

# CI/CD Scheduling Strategy

| Schedule         | Workflow              | Purpose                                                          |
| ---------------- | --------------------- | ---------------------------------------------------------------- |
| Every 15 minutes | Monitoring Cycle      | Forecast metrics and log prediction errors.                      |
| Every 24 hours   | Drift Detection Cycle | Detect drift and retrain the model if required.                  |

This separation keeps monitoring lightweight while allowing drift detection to analyze a sufficiently large history of production behaviour.

---

# Technologies Used

| Component               | Technology                    |
| ----------------------- | ----------------------------- |
| Metrics Collection      | Prometheus                    |
| Forecasting Model       | Amazon Chronos (Hugging Face) |
| Deep Learning Framework | PyTorch                       |
| Database                | PostgreSQL                    |
| Concept Drift           | River (ADWIN)                 |
| Covariate Drift         | Evidently AI                  |
| Model Registry          | Hugging Face Hub              |
| Automation              | GitHub Actions                |

---

# Current Pipeline Behaviour

The monitoring workflow continuously evaluates infrastructure health by comparing **expected** behaviour (Chronos predictions) against **observed** behaviour (Prometheus metrics). Prediction errors are accumulated over time and become the input signal for drift detection. When drift is confirmed, InfraMind fine-tunes its forecasting model on a fixed 70% baseline blended with 30% fresh production data, and promotes the new model only if it beats the current one on held-out data.