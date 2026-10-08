import logging
import os
from tools import rollback_deployment

logger = logging.getLogger("inframind-rollback-agent")

DEFAULT_DEPLOYMENT_NAME = os.getenv("INFRAMIND_DEPLOYMENT", "inframind-model-deployment")

def rollback_node(state: dict) -> dict:
    """
    Rollback Node: Triggered when the system escalates after retries are exhausted.
    Executes a deployment rollback to restore the previous stable configuration --
    UNLESS the Verifier agent disproved the RCA, in which case an automated
    rollback would be acting on a cause we don't actually trust. In that case
    we hold for human investigation instead of blindly rolling back.
    """
    verification = state.get("verification", {})
    verdict = verification.get("verdict", "weakened")

    if verdict == "disproven":
        logger.warning(
            "Skipping automated rollback: Verifier agent disproved the RCA "
            f"(reasoning: {verification.get('reasoning', 'n/a')}). "
            "Holding for human investigation instead."
        )

        history_entry = {
            "attempt": len(state.get("mitigation_history", [])) + 1,
            "tool": "rollback_deployment",
            "justification": (
                "Skipped: Verifier agent disproved the RCA's stated cause, "
                "so an automated rollback would not address a cause we "
                "actually trust."
            ),
            "result": {"status": "held_for_investigation", "verification": verification},
        }
        mitigation_history = state.get("mitigation_history", []) + [history_entry]

        return {
            "final_status": "held_for_investigation",
            "rollback_result": {"status": "held_for_investigation", "verification": verification},
            "mitigation_history": mitigation_history,
        }

    if state.get("rollback_approved") is False:
        logger.warning("Skipping automated rollback: human reviewer declined approval.")

        history_entry = {
            "attempt": len(state.get("mitigation_history", [])) + 1,
            "tool": "rollback_deployment",
            "justification": "Skipped: human reviewer declined the proposed rollback.",
            "result": {"status": "declined_by_human"},
        }
        mitigation_history = state.get("mitigation_history", []) + [history_entry]

        return {
            "final_status": "rollback_declined_by_human",
            "rollback_result": {"status": "declined_by_human"},
            "mitigation_history": mitigation_history,
        }

    logger.warning("Initiating automated deployment rollback...")

    result = rollback_deployment.invoke({"deployment_name": DEFAULT_DEPLOYMENT_NAME})

    history_entry = {
        "attempt": len(state.get("mitigation_history", [])) + 1,
        "tool": "rollback_deployment",
        "justification": "Escalated after pod restarts/scaling failed to stabilize metrics.",
        "result": result,
    }
    mitigation_history = state.get("mitigation_history", []) + [history_entry]

    final_status = (
        "rolled_back_successfully"
        if result.get("status") == "success"
        else "rollback_failed"
    )

    return {
        "final_status": final_status,
        "rollback_result": result,
        "mitigation_history": mitigation_history,
    }