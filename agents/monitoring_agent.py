from datetime import datetime, timezone
import json
import os
from dotenv import load_dotenv
from groq import Groq
import requests

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

groq_client = Groq(api_key=GROQ_API_KEY)

# 1. Comprehensive Telemetry Queries (Clean PromQL Syntax)
PROMETHEUS_QUERIES = {
    # CPU usage of FastAPI process
    "cpu_usage_rate": (
        'rate(process_cpu_seconds_total{job="fastapi_app"}[2m])'
    ),

    # Resident memory usage
    "memory_usage_bytes": (
        'process_resident_memory_bytes{job="fastapi_app"}'
    ),

    # HTTP 4xx error rate
    "http_4xx_rate": (
        'sum(rate(http_requests_total{job="fastapi_app",status="4xx"}[2m])) or vector(0)'
    ),

    # HTTP 5xx error rate
    "http_5xx_rate": (
        'sum(rate(http_requests_total{job="fastapi_app",status="5xx"}[2m])) or vector(0)'
    ),

    # P95 latency
    "http_latency_p95_seconds": (
        'histogram_quantile(0.95, '
        'sum(rate(http_request_duration_seconds_bucket{job="fastapi_app",handler="/predict"}[2m])) by (le)) '
        'or vector(0)'
    )
}

# 2. System Prompt & Few-Shot Instruction Set
SYSTEM_PROMPT = """
You are an expert SRE Monitoring Agent running inside a Kubernetes/Infrastructure environment. 
Your job is to analyze real-time metric snapshots and immediately flag operational anomalies.

### Operational Threshold Baselines:

- cpu_usage_rate:
  Normal < 0.8
  High >= 0.85

- memory_usage_bytes:
  Sudden continuous increase may indicate a memory leak.

- http_5xx_rate:
  Normal = 0
  Anomaly > 0

- http_4xx_rate:
  Normal < 1
  Anomaly >= 1

- http_latency_p95_seconds:
  Normal < 0.5s
  High >= 1.5s

### Output Formatting Requirements:
You MUST respond with a valid JSON object containing:
- `timestamp`: (Pass through the exact ISO timestamp provided in the input)
- `anomaly_detected`: true / false
- `suspect_metric`: Name of the primary offending metric or "none"
- `reasoning`: Concise 1-sentence technical explanation

--- FEW-SHOT EXAMPLES ---

Example 1 (Healthy State):
Input: 
{
  "timestamp": "2026-07-28T14:00:00Z",
  "metrics": {
    "cpu_usage_rate": 0.12,
    "memory_utilization_pct": 45.2,
    "http_5xx_rate": 0.0,
    "http_4xx_rate": 0.1,
    "http_latency_p95_seconds": 0.15,
    "pod_restart_count": 0
  }
}
Output:
{
  "timestamp": "2026-07-28T14:00:00Z",
  "anomaly_detected": false,
  "suspect_metric": "none",
  "reasoning": "All system metrics are operating within healthy baseline bounds."
}

Example 2 (Injected Bad Traffic / 4xx Flood):
Input: 
{
  "timestamp": "2026-07-28T14:05:00Z",
  "metrics": {
    "cpu_usage_rate": 0.45,
    "memory_utilization_pct": 52.0,
    "http_5xx_rate": 0.0,
    "http_4xx_rate": 15.4,
    "http_latency_p95_seconds": 0.32,
    "pod_restart_count": 0
  }
}
Output:
{
  "timestamp": "2026-07-28T14:05:00Z",
  "anomaly_detected": true,
  "suspect_metric": "http_4xx_rate",
  "reasoning": "Severe spike in 4xx error rate indicating malformed traffic injection attack."
}

Example 3 (Server Crash / 5xx Spike):
Input: 
{
  "timestamp": "2026-07-28T14:15:00Z",
  "metrics": {
    "cpu_usage_rate": 0.98,
    "memory_utilization_pct": 65.0,
    "http_5xx_rate": 8.2,
    "http_4xx_rate": 1.1,
    "http_latency_p95_seconds": 3.42,
    "pod_restart_count": 0
  }
}
Output:
{
  "timestamp": "2026-07-28T14:15:00Z",
  "anomaly_detected": true,
  "suspect_metric": "http_5xx_rate",
  "reasoning": "Critical 5xx response rate spike indicating backend server failure."
}
"""


def fetch_comprehensive_metrics():
    """Fetches all metrics from Prometheus."""

    timestamp = datetime.now(timezone.utc).isoformat()

    metrics_snapshot = {
        "timestamp": timestamp,
        "metrics": {}
    }

    for metric_name, query in PROMETHEUS_QUERIES.items():
        try:
            response = requests.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
                timeout=5,
            )

            response.raise_for_status()

            results = response.json()["data"]["result"]

            if len(results) == 0:
                metrics_snapshot["metrics"][metric_name] = None
                continue

            value = float(results[0]["value"][1])

            metrics_snapshot["metrics"][metric_name] = round(value, 4)

        except Exception as e:
            print(f"[WARNING] {metric_name}: {e}")
            metrics_snapshot["metrics"][metric_name] = None

    return metrics_snapshot

def analyze_metrics_with_groq(snapshot_payload):
    """Executes LLM Call with JSON enforcement."""
    user_prompt = f"Evaluate this metric snapshot:\n{json.dumps(snapshot_payload, indent=2)}"

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        print(f"[ERROR] Groq API call failed: {e}")
        return {
            "timestamp": snapshot_payload.get("timestamp"),
            "anomaly_detected": False,
            "suspect_metric": "none",
            "reasoning": f"Pipeline failure: {str(e)}",
        }


def run_monitoring_agent():
    print("[Monitoring Agent] Fetching full metric telemetry...")
    snapshot = fetch_comprehensive_metrics()

    print("\n--- RAW PROMETHEUS SNAPSHOT ---")
    print(json.dumps(snapshot, indent=2))
    print("-------------------------------\n")

    analysis = analyze_metrics_with_groq(snapshot)
    print(f"[Monitoring Agent] Output:\n{json.dumps(analysis, indent=2)}")
    return analysis


if __name__ == "__main__":
    run_monitoring_agent()
