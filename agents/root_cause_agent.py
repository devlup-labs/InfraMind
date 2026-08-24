from groq import Groq
import os
import time
import requests
import subprocess
import json
import re
import math
from dotenv import load_dotenv
from qdrant_manager import search_logs

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

K8S_NAMESPACE = os.getenv("INFRAMIND_NAMESPACE", "default")
K8S_DEPLOYMENT = os.getenv(
    "INFRAMIND_DEPLOYMENT",
    "inframind-model-deployment"
)
CONFIGMAP_NAME = "inframind-app-config"
CONFIGMAP_TIMEOUT_KEY = "INFERENCE_TIMEOUT"


def run_kubectl(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return result.stdout.strip()

        return f"KUBECTL_ERROR: {result.stderr.strip()}"

    except Exception as e:
        return f"KUBECTL_ERROR: {str(e)}"


def get_kubernetes_evidence() -> str:
    evidence = []

    pods = run_kubectl([
        "get", "pods",
        "-n", K8S_NAMESPACE,
        "-l", "app=mock-model",
        "-o", "wide"
    ])

    evidence.append(f"=== CURRENT PODS ===\n{pods}")

    configmap = run_kubectl([
        "get", "configmap",
        CONFIGMAP_NAME,
        "-n", K8S_NAMESPACE,
        "-o", "yaml"
    ])

    evidence.append(f"=== CURRENT CONFIGMAP ===\n{configmap}")

    pod_name = run_kubectl([
        "get", "pods",
        "-n", K8S_NAMESPACE,
        "-l", "app=mock-model",
        "-o", "jsonpath={.items[0].metadata.name}"
    ])

    if pod_name and not pod_name.startswith("KUBECTL_ERROR"):
        pod_description = run_kubectl([
            "describe", "pod",
            pod_name,
            "-n", K8S_NAMESPACE
        ])

        evidence.append(
            f"=== POD DESCRIPTION / EVENTS ===\n{pod_description}"
        )

        pod_logs = run_kubectl([
            "logs",
            pod_name,
            "-n", K8S_NAMESPACE,
            "--tail=200"
        ])

        evidence.append(
            f"=== CURRENT APPLICATION LOGS ===\n{pod_logs}"
        )

    deployment = run_kubectl([
        "get", "deployment",
        K8S_DEPLOYMENT,
        "-n", K8S_NAMESPACE,
        "-o", "yaml"
    ])

    evidence.append(f"=== CURRENT DEPLOYMENT ===\n{deployment}")

    return "\n\n".join(evidence)


def get_current_resource_limits() -> dict:
    cpu = run_kubectl([
        "get", "deployment",
        K8S_DEPLOYMENT,
        "-n", K8S_NAMESPACE,
        "-o",
        "jsonpath={.spec.template.spec.containers[0].resources.limits.cpu}"
    ])

    memory = run_kubectl([
        "get", "deployment",
        K8S_DEPLOYMENT,
        "-n", K8S_NAMESPACE,
        "-o",
        "jsonpath={.spec.template.spec.containers[0].resources.limits.memory}"
    ])

    return {
        "cpu": cpu,
        "memory": memory,
    }


def get_resource_usage() -> dict:
    prometheus_url = os.getenv(
        "PROMETHEUS_URL",
        "http://localhost:9090"
    )

    end = time.time()
    start = end - 900

    queries = {
        "cpu_usage_rate":
            'rate(process_cpu_seconds_total{job="fastapi_app"}[2m])',
        "memory_usage_bytes":
            'process_resident_memory_bytes{job="fastapi_app"}',
    }

    usage = {}

    for metric_name, query in queries.items():
        try:
            response = requests.get(
                f"{prometheus_url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start,
                    "end": end,
                    "step": 15,
                },
                timeout=10,
            )

            response.raise_for_status()

            results = response.json()["data"]["result"]

            if not results:
                usage[metric_name] = []
                continue

            usage[metric_name] = [
                float(point[1])
                for point in results[0]["values"]
            ]

        except Exception:
            usage[metric_name] = []

    return usage


def calculate_resource_statistics(usage: dict) -> dict:
    statistics_data = {}

    for resource, values in usage.items():
        if not values:
            statistics_data[resource] = {
                "p95": None,
                "peak": None
            }
            continue

        sorted_values = sorted(values)
        index = int(0.95 * (len(sorted_values) - 1))

        statistics_data[resource] = {
            "p95": sorted_values[index],
            "peak": max(values)
        }

    return statistics_data


def calculate_resource_recommendation(
    stats: dict,
    current_cpu_limit: str,
    current_memory_limit: str
) -> dict:

    def parse_cpu(value):
        if not value:
            return 0.0

        if value.endswith("m"):
            return float(value[:-1]) / 1000

        return float(value)

    def parse_memory(value):
        if not value:
            return 0.0

        if value.endswith("Gi"):
            return float(value[:-2]) * 1024 ** 3

        if value.endswith("Mi"):
            return float(value[:-2]) * 1024 ** 2

        return float(value)

    cpu_limit = parse_cpu(current_cpu_limit)
    memory_limit = parse_memory(current_memory_limit)

    cpu_stats = stats.get("cpu_usage_rate", {})
    memory_stats = stats.get("memory_usage_bytes", {})

    cpu_p95 = cpu_stats.get("p95")
    cpu_peak = cpu_stats.get("peak")
    memory_p95 = memory_stats.get("p95")
    memory_peak = memory_stats.get("peak")

    cpu_recommendation = None
    memory_recommendation = None

    if (
        cpu_peak is not None
        and cpu_limit > 0
        and cpu_peak >= cpu_limit
    ):
        recommended_cpu = (
            (int(cpu_peak * 1000) // 100) + 1
        ) * 100

        current_millicores = int(cpu_limit * 1000)

        if recommended_cpu <= current_millicores:
            recommended_cpu += 100

        cpu_recommendation = f"{recommended_cpu}m"

    if (
        memory_peak is not None
        and memory_limit > 0
        and memory_peak >= memory_limit
    ):
        memory_mi = memory_peak / (1024 ** 2)

        recommended_mi = (
            (int(memory_mi) // 128) + 1
        ) * 128

        memory_recommendation = f"{recommended_mi}Mi"

    return {
        "cpu": {
            "p95": cpu_p95,
            "peak": cpu_peak,
            "current_limit": current_cpu_limit,
            "recommended_limit": cpu_recommendation,
        },
        "memory": {
            "p95": memory_p95,
            "peak": memory_peak,
            "current_limit": current_memory_limit,
            "recommended_limit": memory_recommendation,
        },
    }


def extract_live_configmap_value(evidence: str, key: str) -> str | None:
    match = re.search(
        rf'{re.escape(key)}:\s*["\']?([^"\',\s]+)["\']?',
        evidence
    )

    if not match:
        return None

    return match.group(1)


def extract_timeout_observations(evidence: str) -> list[float]:
    values = []

    patterns = [
        r'"elapsed_seconds":\s*([0-9.]+)',
        r"'elapsed_seconds':\s*([0-9.]+)",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, evidence):
            try:
                values.append(float(match))
            except ValueError:
                pass

    return values


def build_config_recommendation(evidence: str) -> dict | None:
    current_timeout = extract_live_configmap_value(
        evidence,
        CONFIGMAP_TIMEOUT_KEY
    )

    if current_timeout is None:
        return None

    try:
        current_timeout_value = float(current_timeout)
    except ValueError:
        return None

    observations = extract_timeout_observations(evidence)

    if not observations:
        return None

    violating_observations = [
        value
        for value in observations
        if value > current_timeout_value
    ]

    if not violating_observations:
        return None

    observed_peak = max(violating_observations)
    recommended_timeout = math.ceil(observed_peak + 1)

    if recommended_timeout <= current_timeout_value:
        return None

    return {
        "configmap_name": CONFIGMAP_NAME,
        "key": CONFIGMAP_TIMEOUT_KEY,
        "old_value": str(current_timeout),
        "new_value": str(recommended_timeout),
        "reason": (
            f"Live ConfigMap timeout is {current_timeout}s, while "
            f"observed inference duration reached {observed_peak:.3f}s. "
            f"The recommended {recommended_timeout}s timeout is derived "
            f"from the observed request duration plus 1 second of measured "
            f"headroom."
        ),
    }


def analyze_root_cause(
    analysis: dict,
    logs: list[str],
    evidence: str
) -> str:
    logs = logs[:10]
    evidence = evidence[:16000]
    prompt = f"""
You are an experienced Site Reliability Engineer.

Monitoring Agent detected:

Suspect Metric:
{analysis["suspect_metric"]}

Reason:
{analysis["reasoning"]}

Relevant Historical Logs from Qdrant:
{chr(10).join(logs)}

Live and Historical Infrastructure Evidence:
{evidence}

Analyze ALL available evidence carefully.

Identify:

1. Most likely root cause.
2. Evidence supporting the root cause.
3. Short recommendation.

4. CONFIGURATION ANALYSIS:

Determine whether a live Kubernetes ConfigMap value is contributing
to the incident.

The application logs contain actual observed inference duration and
configured timeout values.

If the structured CONFIG_RECOMMENDATION evidence supplied by the
system indicates a supported ConfigMap change, report that
recommendation exactly.

Do not invent a ConfigMap value.
Do not estimate a target value.
Do not recommend a ConfigMap change merely because a ConfigMap exists.

If no evidence-supported ConfigMap change exists, state:

CONFIG_RECOMMENDATION:
null

5. RESOURCE LIMIT ANALYSIS:

Use the supplied structured RESOURCE RECOMMENDATION evidence.

If the evidence indicates a CPU or memory resource-limit problem,
identify:
- affected resource
- current resource limit
- observed P95
- observed peak
- whether the limit is constraining
- calculated recommendation

IMPORTANT:
- Do NOT invent configuration values.
- Do NOT invent CPU or memory values.
- Treat calculated resource recommendations as evidence.
- Prefer live Kubernetes and Prometheus measurements.
- Do not output internal reasoning or <think> sections.
"""

    response = client.chat.completions.create(
        model="qwen/qwen3.6-27b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Site Reliability Engineer "
                    "specializing in Root Cause Analysis. "
                    "Return only the requested final analysis. "
                    "Never expose chain-of-thought or internal reasoning."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,
    )

    result = response.choices[0].message.content or ""

    if "<think>" in result:
        result = result.split("<think>", 1)[1]

        if "</think>" in result:
            result = result.split("</think>", 1)[1]

    return result.strip()


def root_cause_agent(state: dict):
    analysis = state["analysis"]

    query = f"""
Metric:
{analysis["suspect_metric"]}

Reason:
{analysis["reasoning"]}
"""

    logs = search_logs(query)
    kubernetes_evidence = get_kubernetes_evidence()
    resource_usage = get_resource_usage()
    resource_stats = calculate_resource_statistics(resource_usage)
    resource_limits = get_current_resource_limits()

    resource_recommendation = calculate_resource_recommendation(
        resource_stats,
        resource_limits["cpu"],
        resource_limits["memory"],
    )

    config_recommendation = build_config_recommendation(
        kubernetes_evidence
    )

    combined_evidence = (
        f"{kubernetes_evidence}\n\n"
        f"=== HISTORICAL RESOURCE USAGE ===\n"
        f"{resource_usage}\n\n"
        f"=== RESOURCE STATISTICS ===\n"
        f"{resource_stats}\n\n"
        f"=== CURRENT RESOURCE LIMITS ===\n"
        f"{resource_limits}\n\n"
        f"=== RESOURCE RECOMMENDATION ===\n"
        f"{resource_recommendation}\n\n"
        f"=== STRUCTURED CONFIG RECOMMENDATION ===\n"
        f"{config_recommendation}"
    )

    root_cause = analyze_root_cause(
        analysis,
        logs,
        combined_evidence
    )

    return {
        "root_cause": root_cause,
        "logs": logs,
        "kubernetes_evidence": kubernetes_evidence,
        "resource_usage": resource_usage,
        "resource_statistics": resource_stats,
        "resource_limits": resource_limits,
        "resource_recommendation": resource_recommendation,
        "config_recommendation": config_recommendation,
    }