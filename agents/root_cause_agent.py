from groq import Groq
import os
import re
from qdrant_manager import search_logs


client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def analyze_root_cause(analysis:dict, logs:list[str]) -> str:
    suspect_metric=analysis["suspect_metric"]
    reasoning=analysis["reasoning"]

    prompt=f"""
You are an experienced Site Reliability Engineer.

Monitoring Agent detected:

Suspect Metric:
{suspect_metric}

Reason:
{reasoning}

Relevant Logs:
{chr(10).join(logs)}

Analyze these logs carefully.

Identify:
1. Most likely root cause.
2. Evidence from logs.
3. The single affected Kubernetes pod name, if present in the evidence.
4. Short recommendation.

Include a line in this exact format:
Affected Pod: <pod-name or unknown>
"""

    response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {"role": "system",
         "content": "You are an expert Site Reliability Engineer specializing in Root Cause Analysis."
        },
        {"role": "user","content": prompt}],
    temperature=0.1,)

    result = response.choices[0].message.content

    return result


def extract_affected_pod(root_cause: str) -> str | None:
    match = re.search(r"^Affected Pod:\s*(.+)$", root_cause, re.MULTILINE | re.IGNORECASE)
    if not match:
        return None

    affected_pod = match.group(1).strip().strip("`")
    if not affected_pod or affected_pod.lower() in {"unknown", "none", "n/a"}:
        return None

    return affected_pod

def root_cause_agent(state:dict):
    analysis = state["analysis"]

    query = f"""
Metric:
{analysis["suspect_metric"]}

Reason:
{analysis["reasoning"]}
"""

    logs=search_logs(query)
    root_cause=analyze_root_cause(analysis,logs)
    affected_pod=extract_affected_pod(root_cause)

    return {"root_cause": root_cause, "logs": logs, "affected_pod": affected_pod}


    
