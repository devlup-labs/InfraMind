from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = """
You are an incident-analysis assistant for a production ML/software system. 
You will be given four things:
1. An ANOMALY: a description of an abnormal condition detected by monitoring.
2. A ROOT CAUSE LOG: the log entry most likely related to the anomaly.
3. A ROOT CAUSE ANALYSIS: a preliminary analysis of the incident.
4. MITIGATION HISTORY & STATUS: What automated actions the system took to try and fix it, and the final state of the cluster.

Your job is to produce a clear, actionable incident analysis for an on-call 
engineer who has NOT yet looked at the raw data.

Output your analysis in this exact structure:

## Summary
One or two sentences: what happened, in plain English, no jargon.

## Root Cause
State the most likely root cause. Be specific — name the mechanism.

## Automated Actions Taken
Summarize the mitigation steps the system attempted (from the provided mitigation history) and the final status (e.g., stabilized, escalated, or rolled back).

## Supporting Evidence
Bullet points connecting specific details from the anomaly and the log(s) to 
your root cause claim. 

## Confidence & Caveats
State your confidence level and any gaps in the evidence.

## Recommended Fix
1-3 concrete, actionable steps. If the system already rolled back successfully, focus on what developers need to fix in the code/config before the next deployment.

Rules:
- Be concise. No filler, no restating the prompt, no unnecessary preamble.
- Write for a human reader, not a machine — plain English, minimal jargon.
- Never invent details that were not provided to you.
"""

def generate_incident_report(anomaly: str, logs: list[str], root_cause: str, mitigation_history: str, final_status: str) -> str:
    prompt = f"""
ANOMALY:
{anomaly}

ROOT CAUSE LOG(S):
{chr(10).join(logs) if logs else "No relevant logs found."}

ROOT CAUSE ANALYSIS:
{root_cause}

MITIGATION HISTORY:
{mitigation_history}

FINAL SYSTEM STATUS:
{final_status}
"""

    response = client.chat.completions.create(
        model="qwen/qwen3.6-27b",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
    )
    return response.choices[0].message.content

def reporting_agent(state: dict):

    analysis = state.get("analysis", {})
    anomaly = f"Metric: {analysis.get('suspect_metric')}\nReasoning: {analysis.get('reasoning')}"
    logs = state.get("logs", [])
    root_cause = state.get("root_cause", "No root cause generated.")
    

    history = state.get("mitigation_history", [])
    history_lines = []
    for h in history:
        attempt_num = h.get('attempt')
        tool = h.get('tool')
        result_status = h.get('result', {}).get('status', 'unknown')
        history_lines.append(f"- Attempt {attempt_num}: Used {tool} (Result: {result_status})")
    
    formatted_history = "\n".join(history_lines) if history_lines else "No automated actions attempted."
    

    rollback_result = state.get("rollback_result")
    if rollback_result:
        formatted_history += f"\n- Rollback Execution: {rollback_result.get('status')}"

    final_status = state.get("final_status", "unknown")
 
    report = generate_incident_report(
        anomaly=anomaly, 
        logs=logs, 
        root_cause=root_cause, 
        mitigation_history=formatted_history, 
        final_status=final_status
    )
    
    return {"incident_report": report}