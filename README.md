# CI/CD Pipeline: Automated Infrastructure Monitoring & Drift Detection

## Overview

The CI/CD pipeline in **InfraMind** continuously monitors Kubernetes infrastructure metrics, forecasts expected system behaviour using a Machine Learning model, measures prediction error, and performs automated drift detection. The pipeline is fully automated through GitHub Actions and operates on two independent schedules:

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
          Trigger Retraining (Only if Drift Exists)
```

---

# Directory Structure

```text
ci_cd/
│
├── scrape_metrics.py              # Fetch metrics from Prometheus.
├── model_predictions.py           # Chronos inference + monitoring cycle.
├── error_calculation.py           # Compute prediction errors.
├── postgres_db.py                 # PostgreSQL helper functions.
│
├── detect_concept_drift.py        # ADWIN concept drift detection.
├── detect_covariate_drift.py      # Evidently covariate drift detection.
├── retrain_model.py               # Model retraining workflow.
│
└── github_actions/
    ├── monitoring_cycle_15.yml
    └── monitoring_cycle_24.yml
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

InfraMind uses **Amazon Chronos**, a transformer-based time-series forecasting model, to estimate the expected behaviour of infrastructure metrics. <Cite refs={["turn0search12","turn0search18"]}/>

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

| Column      | Description                                           |
| ----------- | ----------------------------------------------------- |
| error_id    | Primary key.                                          |
| metric_name | Infrastructure metric name.                           |
| time        | Timestamp of monitoring cycle.                        |
| error_value | Prediction error.                                     |
| solved      | Flag indicating whether the anomaly has been handled. |

### Responsibilities

* Creates the table if it does not exist.
* Inserts prediction errors.
* Provides historical error data for drift detection.

The database acts as the long-term memory of the monitoring pipeline.

---

# GitHub Actions Workflows

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

## Drift Detection Workflow (Every 24 Hours)

**Workflow:** `monitoring_cycle_24.yml`

### Trigger

Runs once every 24 hours.

### Responsibilities

* Read historical prediction errors.
* Perform concept drift detection.
* Perform covariate drift detection.
* Trigger retraining when required.

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

---

# Environment Variables

Create a `.env` file inside the repository root.

```env
MODEL_NAME=amazon/chronos-t5-small

PROMETHEUS_URL=http://localhost:9090

DATABASE_URL=postgresql://postgres:<password>@localhost:5432/postgres
```

| Variable       | Purpose                                |
| -------------- | -------------------------------------- |
| MODEL_NAME     | Hugging Face Chronos model identifier. |
| PROMETHEUS_URL | Prometheus server endpoint.            |
| DATABASE_URL   | PostgreSQL connection string.          |

---

# Running the Pipeline Locally

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

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

---

# CI/CD Scheduling Strategy

| Schedule         | Workflow              | Purpose                                                 |
| ---------------- | --------------------- | ------------------------------------------------------- |
| Every 15 minutes | Monitoring Cycle      | Forecast metrics and log prediction errors.             |
| Every 24 hours   | Drift Detection Cycle | Detect drift and decide whether retraining is required. |

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
| Automation              | GitHub Actions                |

---

# Current Pipeline Behaviour

The monitoring workflow continuously evaluates infrastructure health by comparing **expected** behaviour (Chronos predictions) against **observed** behaviour (Prometheus metrics). Prediction errors are accumulated over time and become the input signal for drift detection, allowing InfraMind to retrain its forecasting model only when production behaviour has genuinely changed.
