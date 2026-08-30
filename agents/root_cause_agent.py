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
K8S_DEPLOYMENT = os.getenv("INFRAMIND_DEPLOYMENT", "inframind-model-deployment")
CONFIGMAP_NAME = "inframind-app-config"
CONFIGMAP_TIMEOUT_KEY = "INFERENCE_TIMEOUT"


def run_kubectl(args: list[str]) -> str:
    try:
        result = subprocess.run(["kubectl"] + args, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
        return f"KUBECTL_ERROR: {result.stderr.strip()}"
    except Exception as e:
        return f"KUBECTL_ERROR: {str(e)}"


def get_kubernetes_evidence() -> str:
    evidence = []
    pods = run_kubectl(["get", "pods", "-n", K8S_NAMESPACE, "-l", "app=mock-model", "-o", "wide"])
    evidence.append(f"=== CURRENT PODS ===\n{pods}")

    configmap = run_kubectl(["get", "configmap", CONFIGMAP_NAME, "-n", K8S_NAMESPACE, "-o", "yaml"])
    evidence.append(f"=== CURRENT CONFIGMAP ===\n{configmap}")

    pod_name = run_kubectl(["get", "pods", "-n", K8S_NAMESPACE, "-l", "app=mock-model", "-o", "jsonpath={.items[0].metadata.name}"])

    if pod_name and not pod_name.startswith("KUBECTL_ERROR"):
        pod_description = run_kubectl(["describe", "pod", pod_name, "-n", K8S_NAMESPACE])
        evidence.append(f"=== POD DESCRIPTION / EVENTS ===\n{pod_description}")

        pod_logs = run_kubectl(["logs", pod_name, "-n", K8S_NAMESPACE, "--tail=200"])
        evidence.append(f"=== CURRENT APPLICATION LOGS ===\n{pod_logs}")

    deployment = run_kubectl(["get", "deployment", K8S_DEPLOYMENT, "-n", K8S_NAMESPACE, "-o", "yaml"])
    evidence.append(f"=== CURRENT DEPLOYMENT ===\n{deployment}")

    return "\n\n".join(evidence)


def get_current_resource_limits() -> dict:
    cpu = run_kubectl(["get", "deployment", K8S_DEPLOYMENT, "-n", K8S_NAMESPACE, "-o", "jsonpath={.spec.template.spec.containers[0].resources.limits.cpu}"])
    memory = run_kubectl(["get", "deployment", K8S_DEPLOYMENT, "-n", K8S_NAMESPACE, "-o", "jsonpath={.spec.template.spec.containers[0].resources.limits.memory}"])
    return {"cpu": cpu, "memory": memory}


def get_resource_usage() -> dict:
    prometheus_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    end = time.time()
    start = end - 900
    queries = {
        "cpu_usage_rate": 'rate(process_cpu_seconds_total{job="fastapi_app"}[2m])',
        "memory_usage_bytes": 'process_resident_memory_bytes{job="fastapi_app"}',
    }
    usage = {}
    for metric_name, query in queries.items():
        try:
            response = requests.get(f"{prometheus_url}/api/v1/query_range", params={"query": query, "start": start, "end": end, "step": 15}, timeout=10)
            response.raise_for_status()
            results = response.json()["data"]["result"]
            if not results:
                usage[metric_name] = []
                continue
            usage[metric_name] = [float(point[1]) for point in results[0]["values"]]
        except Exception:
            usage[metric_name] = []
    return usage


def calculate_resource_statistics(usage: dict) -> dict:
    statistics_data = {}
    for resource, values in usage.items():
        if not values:
            statistics_data[resource] = {"p95": None, "peak": None}
            continue
        sorted_values = sorted(values)
        index = int(0.95 * (len(sorted_values) - 1))
        statistics_data[resource] = {"p95": sorted_values[index], "peak": max(values)}
    return statistics_data


def calculate_resource_recommendation(stats: dict, current_cpu_limit: str, current_memory_limit: str) -> dict:
    def parse_cpu(value):
        if not value: return 0.0
        if value.endswith("m"): return float(value[:-1]) / 1000
        return float(value)

    def parse_memory(value):
        if not value: return 0.0
        if value.endswith("Gi"): return float(value[:-2]) * 1024 ** 3
        if value.endswith("Mi"): return float(value[:-2]) * 1024 ** 2
        return float(value)

    cpu_limit = parse_cpu(current_cpu_limit)
    memory_limit = parse_memory(current_memory_limit)
    cpu_stats = stats.get("cpu_usage_rate", {})
    memory_stats = stats.get("memory_usage_bytes", {})

    cpu_recommendation = None
    memory_recommendation = None

    if cpu_stats.get("peak") is not None and cpu_limit > 0 and cpu_stats.get("peak") >= cpu_limit:
        recommended_cpu = ((int(cpu_stats.get("peak") * 1000) // 100) + 1) * 100
        if recommended_cpu <= int(cpu_limit * 1000):
            recommended_cpu += 100
        cpu_recommendation = f"{recommended_cpu}m"

    if memory_stats.get("peak") is not None and memory_limit > 0 and memory_stats.get("peak") >= memory_limit:
        memory_mi = memory_stats.get("peak") / (1024 ** 2)
        recommended_mi = ((int(memory_mi) // 128) + 1) * 128
        memory_recommendation = f"{recommended_mi}Mi"

    return {
        "cpu": {"p95": cpu_stats.get("p95"), "peak": cpu_stats.get("peak"), "current_limit": current_cpu_limit, "recommended_limit": cpu_recommendation},
        "memory": {"p95": memory_stats.get("p95"), "peak": memory_stats.get("peak"), "current_limit": current_memory_limit, "recommended_limit": memory_recommendation},
    }


def extract_live_configmap_value(evidence: str, key: str) -> str | None:
    match = re.search(rf'{re.escape(key)}:\s*["\']?([^"\',\s]+)["\']?', evidence)
    return match.group(1) if match else None


def extract_timeout_observations(evidence: str) -> list[float]:
    values = []
    patterns = [r'"elapsed_seconds":\s*([0-9.]+)', r"'elapsed_seconds':\s*([0-9.]+)"]
    for pattern in patterns:
        for match in re.findall(pattern, evidence):
            try:
                values.append(float(match))
            except ValueError:
                pass
    return values


def build_config_recommendation(evidence: str) -> dict | None:
    current_timeout = extract_live_configmap_value(evidence, CONFIGMAP_TIMEOUT_KEY)
    if current_timeout is None:
        return None
    try:
        current_timeout_value = float(current_timeout)
    except ValueError:
        return None

    observations = extract_timeout_observations(evidence)
    if not observations:
        return None

    violating_observations = [value for value in observations if value > current_timeout_value]
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
        "reason": f"Live ConfigMap timeout is {current_timeout}s, while observed inference duration reached {observed_peak:.3f}s. The recommended {recommended_timeout}s timeout is derived from the observed request duration plus 1 second of measured headroom."
    }


def generate_search_query(suspect_metric: str, analysis: str) -> str:
    """LLM Call 1: Generate a targeted vector DB query."""
    prompt = f"""
    You are an SRE building a search query for a vector database.
    Suspect Metric: {suspect_metric}
    Analysis: {analysis}
    
    Generate a precise, 4-6 word search query to find the most relevant backend error logs.
    Return ONLY the raw search query string. Do not use quotes or formatting.
    """
    
    response = client.chat.completions.create(
        model="qwen/qwen3.6-27b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=50
    )
    return response.choices[0].message.content.strip()


def analyze_root_cause(analysis_data: dict, logs: list, affected_pod: str = None, *args, **kwargs) -> dict:
    suspect_metric = str(analysis_data.get("suspect_metric", "unknown"))[:200]
    analysis_text = str(analysis_data.get("analysis", "No analysis provided."))[:500]
    
    # Sanitize logs by removing explicit curly braces that confuse JSON generators
    raw_logs = str(logs)[:1500]
    log_context = raw_logs.replace("{", "[").replace("}", "]")
    
    prompt = f"""
    You are an expert SRE. 
    Metric: {suspect_metric}
    Analysis: {analysis_text}
    Affected Environment: {str(affected_pod)[:1000] if affected_pod else "unknown"}
    Logs: {log_context}
    
    Provide a structured Root Cause Analysis. Output ONLY raw JSON. Do NOT use markdown formatting (no ```json).
    {{
        "primary_cause": "Detailed explanation of the failure mechanism",
        "log_evidence": "Specific log lines or patterns confirming the cause",
        "recommended_action": "High-level strategy to fix the issue"
    }}
    """
    
    try:
        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                {"role": "system", "content": "You are a raw JSON API. Output only JSON."},
                {"role": "user", "content": prompt[:3000]}
            ],
            # Removed response_format={"type": "json_object"} to stop API crashes
            temperature=0.1,
            max_tokens=1024
        )
        
        output_text = response.choices[0].message.content.strip()
        
        # Strip markdown block if Qwen still forces it
        if output_text.startswith("```json"):
            output_text = output_text[7:]
        if output_text.endswith("```"):
            output_text = output_text[:-3]
            
        return json.loads(output_text.strip())
        
    except Exception as e:
        print(f"[WARNING] RCA Generation Failed: {e}")
        return {
            "primary_cause": "Unknown",
            "log_evidence": "None",
            "recommended_action": f"Failed to generate RCA JSON: {str(e)}"
        }

def root_cause_agent(state: dict):
    analysis = state["analysis"]

    # Step 1: LLM Call for Query
    db_query = generate_search_query(
        analysis.get("suspect_metric", "unknown"),
        analysis.get("analysis", "")
    )

    # Step 2: Retrieve Evidence
    logs = search_logs(db_query)
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

    # Step 3: LLM Call for RCA Structured JSON
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