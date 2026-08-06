import logging
import os
from tools import rollback_deployment

logger = logging.getLogger("inframind-rollback-agent")

DEFAULT_DEPLOYMENT_NAME = os.getenv("INFRAMIND_DEPLOYMENT", "inframind-model-deployment")

def rollback_node(state: dict) -> dict:
    """
    Rollback Node: Triggered when the system escalates after retries are exhausted.
    Executes a deployment rollback to restore the previous stable configuration.
    """
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