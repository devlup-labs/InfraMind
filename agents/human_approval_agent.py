"""
HITL approval gate, scoped to rollback only (Phase 4).

Implemented as a blocking terminal prompt rather than LangGraph's interrupt()
primitive: interrupt() needs a checkpointer and a resume-based invoke flow,
and its exact API has shifted across langgraph versions. A synchronous input()
achieves the same practical requirement -- no rollback executes without a
human approving it -- with far less moving parts. Revisit interrupt()-based
HITL if approval ever needs to come from something other than whoever is
running main.py in a terminal (e.g. a Slack bot, a web approval queue).
"""


def human_approval_node(state: dict) -> dict:
    root_cause = state.get("root_cause", {}) or {}
    verification = state.get("verification", {}) or {}
    escalation = state.get("escalation", {}) or {}

    print("\n" + "=" * 60)
    print("HUMAN APPROVAL REQUIRED: Automated Deployment Rollback")
    print("=" * 60)
    print(f"Primary Cause: {root_cause.get('primary_cause', 'Unknown')}")
    print(f"Recommended Action (RCA): {root_cause.get('recommended_action', 'N/A')}")
    print(
        f"Verifier Verdict: {verification.get('verdict', 'unknown')} "
        f"(confidence: {verification.get('confidence', 'n/a')})"
    )
    print(f"Verifier Reasoning: {verification.get('reasoning', 'N/A')}")
    print(f"Tools already tried: {escalation.get('tried_tools', [])}")
    print(f"Escalation reason: {escalation.get('reason', 'N/A')}")
    print("=" * 60)

    while True:
        answer = input("Approve automated deployment rollback? [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            print("[Human Approval] Rollback APPROVED.")
            return {"rollback_approved": True}
        if answer in ("n", "no"):
            print("[Human Approval] Rollback DECLINED.")
            return {"rollback_approved": False}
        print("Please answer 'y' or 'n'.")