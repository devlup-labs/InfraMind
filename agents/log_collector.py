import subprocess
import os

import requests


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")


def get_pod_name() -> str:
    """
    Returns the app pod with the highest recent HTTP error rate, falling back
    to the first running app pod when Prometheus has no recent error data.
    """
    query = (
        'topk(1, sum(rate(http_requests_total{job="fastapi_app",status=~"4xx|5xx"}[2m])) by (pod))'
    )
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        response.raise_for_status()
        results = response.json()["data"]["result"]
        if results:
            pod_name = results[0]["metric"].get("pod")
            if pod_name:
                return pod_name
    except Exception as exc:
        print(f"[WARNING] Could not select pod from Prometheus: {exc}")

    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n", "monitoring",
            "-l",
            "app=mock-model",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip()


def collect_logs(tail: int = 200) -> list[str]:
    """
    Collects the last `tail` log lines from the application pod.
    """

    pod_name = get_pod_name()

    result = subprocess.run(
        [
            "kubectl",
            "logs",
            "-n", "monitoring",
            pod_name,
            f"--tail={tail}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    logs = result.stdout.strip().splitlines()

    return logs
