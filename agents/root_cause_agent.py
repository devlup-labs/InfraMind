from groq import Groq
import os
import time
import requests
import subprocess
import json
import re
import math
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from qdrant_manager import search_logs

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

rca_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.1,
).bind(response_format={"type": "json_object"})

K8S_NAMESPACE = os.getenv("INFRAMIND_NAMESPACE", "default")
K8S_DEPLOYMENT = os.getenv("INFRAMIND_DEPLOYMENT", "inframind-model-deployment")
CONFIGMAP_NAME = "inframind-app-config"
CONFIGMAP_TIMEOUT_KEY = "INFERENCE_TIMEOUT"
CONFIGMAP_MANIFEST_PATH = os.path.join(
    os.path.dirname(__file__), "..", "k8s", "inframind-config.yaml"
)
# Keys checked for baseline drift, separate from the timeout key above
# (which already has its own observed-duration-driven logic).
DRIFT_TRACKED_KEYS = ["MAX_CONCURRENT_WORKERS", "MAX_BATCH_SIZE"]


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

    nodes = run_kubectl(["get", "nodes"])
    evidence.append(f"=== CURRENT NODES ===\n{nodes}")

    pods = run_kubectl(["get", "pods", "-n", K8S_NAMESPACE, "-l", "app=mock-model", "-o", "wide"])
    evidence.append(f"=== CURRENT PODS ===\n{pods}")

    configmap = run_kubectl(["get", "configmap", CONFIGMAP_NAME, "-n", K8S_NAMESPACE, "-o", "yaml"])
    evidence.append(f"=== CURRENT CONFIGMAP ===\n{configmap}")

    pod_name = run_kubectl(["get", "pods", "-n", K8S_NAMESPACE, "-l", "app=mock-model", "-o", "jsonpath={.items[0].metadata.name}"])

    if pod_name and not pod_name.startswith("KUBECTL_ERROR"):
        pod_description = run_kubectl(["describe", "pod", pod_name, "-n", K8S_NAMESPACE])
        evidence.append(f"=== POD DESCRIPTION / EVENTS ===\n{pod_description}")

        node_name = run_kubectl(["get", "pod", pod_name, "-n", K8S_NAMESPACE, "-o", "jsonpath={.spec.nodeName}"])

        if node_name and not node_name.startswith("KUBECTL_ERROR"):

            node_description = run_kubectl(["describe", "node", node_name])

            evidence.append(f"=== NODE DESCRIPTION ({node_name}) ===\n{node_description[:2500]}")

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


def _read_configmap_baseline() -> str:
    try:
        with open(CONFIGMAP_MANIFEST_PATH, "r") as f:
            return f.read()
    except Exception:
        return ""


def detect_configmap_drift(evidence: str) -> dict | None:
    """
    Compares the live ConfigMap (captured in evidence) against the manifest's
    declared baseline for keys other than INFERENCE_TIMEOUT. Flags drift left
    over from prior manual/automated patches (e.g. adjust_inference_concurrency)
    that a deployment rollback alone cannot undo, since ConfigMaps aren't part
    of Deployment revision history.
    """
    baseline_text = _read_configmap_baseline()
    if not baseline_text:
        return None

    for key in DRIFT_TRACKED_KEYS:
        live_value = extract_live_configmap_value(evidence, key)
        baseline_value = extract_live_configmap_value(baseline_text, key)

        if live_value is None or baseline_value is None:
            continue

        if live_value != baseline_value:
            return {
                "configmap_name": CONFIGMAP_NAME,
                "key": key,
                "old_value": str(live_value),
                "new_value": str(baseline_value),
                "reason": (
                    f"Live ConfigMap value for {key} ({live_value}) has drifted "
                    f"from the manifest baseline ({baseline_value}). This is "
                    f"likely leftover from a prior automated config patch that "
                    f"a deployment rollback did not revert, since ConfigMaps "
                    f"are not part of Deployment revision history."
                ),
            }

    return None


def build_config_recommendation(evidence: str) -> dict | None:
    timeout_recommendation = _build_timeout_recommendation(evidence)
    if timeout_recommendation is not None:
        return timeout_recommendation

    return detect_configmap_drift(evidence)


def _build_timeout_recommendation(evidence: str) -> dict | None:
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
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=50
    )
    return response.choices[0].message.content.strip()


def normalize_root_cause(raw: dict) -> dict:
    """
    Safety net: forces every RCA result into one fixed, terminal-friendly shape,
    regardless of which field names the model actually used this run.
    """
    def first_present(d: dict, keys: list, default=None):
        for k in keys:
            if k in d and d[k]:
                return d[k]
        return default

    def as_bullet_list(value) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, dict):
                    out.append(" - ".join(str(v) for v in item.values() if v))
                else:
                    out.append(str(item))
            return out
        if isinstance(value, dict):
            return [f"{k}: {v}" for k, v in value.items()]
        text = str(value).strip()
        return [text] if text else []

    primary_cause = first_present(
        raw, ["primary_cause", "root_cause", "summary", "analysis"], "Unknown"
    )

    evidence = as_bullet_list(
        first_present(raw, ["evidence", "log_evidence", "observations", "observed_logs", "potential_root_causes", "potentialRootCauses"])
    )

    # Pick ONLY the single highest-priority action, per the schema's intent.
    # If the model instead handed back a list of several, keep the first as
    # the action and fold the rest into evidence so nothing is silently lost.
    action_raw = first_present(
        raw, ["recommended_action", "recommended_actions", "recommendations", "next_steps"], None
    )

    if isinstance(action_raw, list) and action_raw:
        first_item = action_raw[0]
        recommended_action = (
            " - ".join(str(v) for v in first_item.values() if v)
            if isinstance(first_item, dict) else str(first_item)
        )
        evidence += as_bullet_list(action_raw[1:])
    elif isinstance(action_raw, dict):
        recommended_action = " - ".join(str(v) for v in action_raw.values() if v)
    elif action_raw:
        recommended_action = str(action_raw)
    else:
        recommended_action = "No action recommended."

    return {
        "primary_cause": str(primary_cause),
        "evidence": evidence,
        "recommended_action": str(recommended_action),
        "resource_recommendation": raw.get("resource_recommendation", {}) or {},
        "config_recommendation": raw.get("config_recommendation", {}) or {},
    }


def analyze_root_cause(analysis_data: dict, logs: list, affected_pod: str, kubernetes_evidence: str) -> dict:
    suspect_metric = str(analysis_data.get("suspect_metric", "unknown"))[:200]
    analysis_text = str(analysis_data.get("analysis", "No analysis provided."))[:500]

    raw_logs = str(logs)[:1500]
    log_context = raw_logs.replace("{", "[").replace("}", "]")

    prompt = f"""
    You are an expert SRE.
    Metric: {suspect_metric}
    Analysis: {analysis_text}
    Affected Environment: {str(affected_pod)[:1000] if affected_pod else "unknown"}
    Logs: {log_context}
    Kubernetes Evidence: {str(kubernetes_evidence)[:3000]}

    Provide a structured Root Cause Analysis based on the provided logs and Kubernetes structural evidence.

    CRITICAL DIAGNOSIS RULES:
    - If Kubernetes Evidence shows node-level faults (DiskPressure, MemoryPressure, NotReady), explicitly recommend node evacuation/cordoning.
    - If metrics show high latency but CPU/Memory are healthy, and logs show timeout or waiting patterns, diagnose a thread/concurrency bottleneck.
    - If a specific ConfigMap value is limiting performance, provide a structured config_recommendation to tune it.

    You MUST use exactly these top-level keys, no others, no renaming:
    - "primary_cause": one or two sentences, the specific failure mechanism.
    - "evidence": a JSON array of short strings (max ~15 words each), one fact per item. Do NOT write one long paragraph.
    - "recommended_action": one sentence, the single highest-priority next step.
    - "resource_recommendation": object, may be empty {{}}.
    - "config_recommendation": object, may be empty {{}}.

    Output ONLY raw JSON. Do NOT use markdown formatting (no ```json). Keep every string field under 40 words.
    """

    try:
        response = rca_llm.invoke([
            SystemMessage(content="You are a raw JSON API. Output only JSON with exactly the requested keys."),
            HumanMessage(content=prompt[:3500]),
        ])

        output_text = response.content.strip()
        if output_text.startswith("```json"):
            output_text = output_text[7:]
        if output_text.endswith("```"):
            output_text = output_text[:-3]

        parsed = json.loads(output_text.strip())
        return normalize_root_cause(parsed)

    except Exception as e:
        print(f"[WARNING] RCA Generation Failed: {e}")
        return {
            "primary_cause": "Unknown",
            "evidence": [],
            "recommended_action": f"Failed to generate RCA JSON: {str(e)}",
            "resource_recommendation": {},
            "config_recommendation": {},
        }


def root_cause_agent(state: dict):
    analysis = state["analysis"]
    affected_pod = state.get("affected_pod")

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
        affected_pod,
        combined_evidence,
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