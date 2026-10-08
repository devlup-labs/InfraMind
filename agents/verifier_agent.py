"""
Verifier Agent (Phase 3).

Not literal GAN/adversarial-training infrastructure -- a second LLM call with
a red-team system prompt whose only job is to argue AGAINST the RCA's
conclusion, checking the same evidence graph for contradicting signals, weak
causal links (correlation treated as causation), or a more likely alternative
explanation the RCA may have missed.

Its verdict feeds into the escalation decision: an RCA the verifier disproves
should not silently trigger an automated rollback -- see rollback_agent.py's
guard and optimizing_agent.py's escalation_node.
"""

import os
import json
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

verifier_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.3,  # slightly higher than RCA's own call -- we want it to
                       # actively explore alternatives, not just re-agree.
).bind(response_format={"type": "json_object"})

SYSTEM_PROMPT = """
You are an adversarial Verifier agent for an automated Root Cause Analysis
(RCA) system. Your ONLY job is to try to DISPROVE the given RCA -- find
contradicting evidence, weak causal links, or alternative explanations the
RCA may have missed. You are the critic, not the author. Do not simply agree
with the RCA; actively look for reasons it could be wrong.

Consider:
- Does the evidence show CORRELATION being treated as CAUSATION?
- Is there evidence in the graph that points AWAY from the stated cause?
- Could the anomaly have a different, more likely explanation?
- Is the recommended action actually likely to fix the stated cause, or is it a guess?

Output ONLY raw JSON in exactly this shape:
{
    "verdict": "supported" | "weakened" | "disproven",
    "confidence": <float 0.0 to 1.0, how much you trust the RCA's primary_cause after your review>,
    "counter_evidence": ["short strings, evidence that contradicts or weakens the RCA"],
    "reasoning": "one or two sentences explaining your verdict"
}

"supported" = your review found no significant contradicting evidence.
"weakened" = you found some contradicting evidence or weak reasoning, but the cause is still plausible.
"disproven" = the evidence graph does not actually support the stated cause, or points to a different one.
"""


def run_verifier_agent(root_cause: dict, graph_evidence_text: str) -> dict:
    prompt = f"""
    RCA UNDER REVIEW:
    Primary Cause: {root_cause.get('primary_cause', 'Unknown')}
    Evidence cited by RCA: {json.dumps(root_cause.get('evidence', []))}
    Recommended Action: {root_cause.get('recommended_action', 'N/A')}

    FULL EVIDENCE GRAPH (the same data the RCA had access to -- check whether
    it actually supports the stated cause, or whether the RCA cherry-picked
    or misread it):
    {graph_evidence_text}

    Critically review this RCA. Try to disprove it.
    """

    try:
        response = verifier_llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt[:3500]),
        ])
        output_text = response.content.strip()
        if output_text.startswith("```json"):
            output_text = output_text[7:]
        if output_text.endswith("```"):
            output_text = output_text[:-3]
        result = json.loads(output_text.strip())

        verdict = result.get("verdict", "weakened")
        if verdict not in ("supported", "weakened", "disproven"):
            verdict = "weakened"

        try:
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            "verdict": verdict,
            "confidence": confidence,
            "counter_evidence": result.get("counter_evidence", []) or [],
            "reasoning": result.get("reasoning", ""),
        }

    except Exception as e:
        print(f"[WARNING] Verifier Agent Failed: {e}")
        # Fail safe: if the verifier itself breaks, don't silently assume the
        # RCA is correct -- default to "weakened" so escalation logic treats
        # it with caution rather than full, unquestioned trust.
        return {
            "verdict": "weakened",
            "confidence": 0.5,
            "counter_evidence": [],
            "reasoning": f"Verifier agent failed to run: {str(e)}",
        }