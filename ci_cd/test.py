"""
Local integration test for the CI/CD monitoring pipeline.

This file does NOT require Prometheus.
It simulates Prometheus metrics, runs the Chronos model,
calculates prediction errors, and stores them in PostgreSQL.
"""

from model_predictions import get_model_predictions
from error_calculation import calculate_error
from postgres_db import ensure_schema


def run_pipeline_test():
    print("=" * 70)
    print("InfraMind CI/CD Pipeline Test")
    print("=" * 70)

    # ------------------------------------------------------------------
    # STEP 1 — Simulated Prometheus metrics (first scrape)
    # ------------------------------------------------------------------
    initial_metrics = {
        "request_rate": 150.0,
        "cpu_usage_rate": 0.72,
        "memory_usage_bytes": 525_000_000.0,
        "p95_latency_seconds": 0.42,
    }

    print("\nSTEP 1 : Initial Prometheus Metrics")
    for k, v in initial_metrics.items():
        print(f"{k:25} : {v}")

    # ------------------------------------------------------------------
    # STEP 2 — Chronos Predictions
    # ------------------------------------------------------------------
    print("\nSTEP 2 : Generating Predictions")

    predicted_metrics = get_model_predictions(initial_metrics)

    for k, v in predicted_metrics.items():
        print(f"{k:25} : {v:.4f}")

    # ------------------------------------------------------------------
    # STEP 3 — Simulated second Prometheus scrape
    # (Pretend metrics changed slightly after prediction.)
    # ------------------------------------------------------------------
    actual_metrics = {
        "request_rate": 154.5,
        "cpu_usage_rate": 0.76,
        "memory_usage_bytes": 531_000_000.0,
        "p95_latency_seconds": 0.45,
    }

    print("\nSTEP 3 : Latest Prometheus Metrics")
    for k, v in actual_metrics.items():
        print(f"{k:25} : {v}")

    # ------------------------------------------------------------------
    # STEP 4 — Error Calculation + PostgreSQL Insert
    # ------------------------------------------------------------------
    print("\nSTEP 4 : Calculating Prediction Errors")

    ensure_schema()

    errors = calculate_error(
        actual_metrics=actual_metrics,
        predicted_metrics=predicted_metrics,
    )

    # ------------------------------------------------------------------
    # STEP 5 — Results
    # ------------------------------------------------------------------
    print("\nPrediction Errors")
    print("-" * 70)

    for metric, error in errors.items():
        print(f"{metric:25} : {error:.6f}")

    print("\nSUCCESS: Errors inserted into PostgreSQL.")
    print("=" * 70)


if __name__ == "__main__":
    run_pipeline_test()