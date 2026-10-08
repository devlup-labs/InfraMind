from groq import Groq
import os
import json
from dotenv import load_dotenv

from metrics_agent import run_metrics_agent
from logs_agent import run_logs_agent
from k8s_agent import run_k8s_agent

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = """
You are the Triage Controller for an autonomous SRE system. You receive
observations gathered independently by three agents: Metrics, Logs, and
Kubernetes. Decide whether this cycle represents a genuine anomaly worth
escalating to full incident response, and if so, which metric is the primary
suspect.

Output ONLY raw JSON in exactly this shape:
{
    "anomaly_detected": true or false,
    "suspect_metric": "metric_name" or "none",
    "analysis": "one or two sentences, citing specific observations"
}
"""


def run_triage_agent() -> dict:
    """
    Dispatches the observation swarm (metrics, logs, k8s -- run sequentially
    for now; cheap enough that parallelizing isn't worth the complexity yet)
    and produces the anomaly_detected/suspect_metric/analysis decision that
    used to come from monitoring_agent.run_monitoring_agent(). Carries the
    full observation bundle forward under "_observations" so downstream
    nodes (e.g. collect_logs_node) can reuse it instead of re-fetching.
    """
    print("[Triage Controller] Dispatching observation swarm (metrics, logs, k8s)...")

    metrics_obs = run_metrics_agent()
    logs_obs = run_logs_agent()
    k8s_obs = run_k8s_agent()

    print("\n--- RAW PROMETHEUS SNAPSHOT ---")
    print(json.dumps({"timestamp": metrics_obs.get("timestamp"), "metrics": metrics_obs.get("metrics", {})}, indent=2))
    print("-------------------------------")

    breaches = {
        name: info for name, info in metrics_obs.get("breaches", {}).items()
        if info.get("exceeded")
    }

    observations = {"metrics": metrics_obs, "logs": logs_obs, "k8s": k8s_obs}

    print(
        f"[Triage Controller] Breaches: {list(breaches.keys()) or 'none'} | "
        f"Unhealthy pods: {len(k8s_obs.get('unhealthy_pods', []))} | "
        f"Error-like logs: {len(logs_obs.get('error_like_logs', []))}"
    )

    # Fast deterministic pre-check: most polling cycles are healthy, and a
    # cycle with zero threshold breaches never needs an LLM call at all.
    if not breaches:
        result = {
            "timestamp": metrics_obs.get("timestamp"),
            "anomaly_detected": False,
            "suspect_metric": "none",
            "analysis": "No metric breached its stability threshold this cycle.",
            "_observations": observations,
        }
        print("[Triage Controller] Output:")
        print(json.dumps({k: v for k, v in result.items() if k != "_observations"}, indent=2))
        return result

    prompt = f"""
    METRIC BREACHES: {json.dumps(breaches)}
    FULL METRICS: {json.dumps(metrics_obs.get('metrics', {}))}
    ERROR-LIKE LOGS (sample): {json.dumps(logs_obs.get('error_like_logs', [])[:5])}
    AFFECTED POD CANDIDATE: {logs_obs.get('affected_pod')}
    UNHEALTHY PODS: {json.dumps(k8s_obs.get('unhealthy_pods', []))}
    PRESSURED NODES: {json.dumps(k8s_obs.get('pressured_nodes', []))}
    """

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        result = json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        # Fail safe: a genuine threshold breach with a broken LLM call should
        # still escalate rather than silently swallow a real anomaly.
        top_breach = next(iter(breaches))
        result = {
            "anomaly_detected": True,
            "suspect_metric": top_breach,
            "analysis": (
                f"Threshold breach on {top_breach}; triage LLM call failed "
                f"({e}), escalating conservatively rather than risk missing "
                f"a real incident."
            ),
        }

    result["timestamp"] = metrics_obs.get("timestamp")
    result["_observations"] = observations

    print("[Triage Controller] Output:")
    print(json.dumps({k: v for k, v in result.items() if k != "_observations"}, indent=2))

    return result