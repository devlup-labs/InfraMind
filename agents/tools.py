import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from langchain_core.tools import tool

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

NAMESPACE = os.getenv("INFRAMIND_NAMESPACE", "monitoring")
COOLDOWN_SECONDS = int(os.getenv("RESTART_COOLDOWN_SECONDS", "60"))
MAX_ACTIONS_PER_HOUR = int(os.getenv("RESTART_MAX_PER_HOUR", "6"))
EXCLUDED_LABELS = {"critical": "true"}
AUDIT_LOG_PATH = os.getenv("RESTART_AUDIT_LOG", "restart_audit.log")

logger = logging.getLogger("inframind-restart-agent")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.FileHandler(AUDIT_LOG_PATH)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)

_core_v1 = None
_action_history: list[datetime] = []


def _load_k8s():
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return k8s_client.CoreV1Api()


def _get_core_v1():
    global _core_v1
    if _core_v1 is None:
        _core_v1 = _load_k8s()
    return _core_v1


def _in_cooldown() -> bool:
    if not _action_history:
        return False
    return (datetime.now(timezone.utc) - _action_history[-1]).total_seconds() < COOLDOWN_SECONDS


def _circuit_breaker_tripped() -> bool:
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = [t for t in _action_history if t > one_hour_ago]
    return len(recent) >= MAX_ACTIONS_PER_HOUR


def _record_action():
    _action_history.append(datetime.now(timezone.utc))


def _pod_is_excluded(pod) -> bool:
    labels = pod.metadata.labels or {}
    return all(labels.get(key) == value for key, value in EXCLUDED_LABELS.items())


@tool
def horizontal_pod_scaling():
    """
    Apply the Horizontal Pod Autoscaler for the application.
    """
    subprocess.run(
        ["kubectl", "apply", "-f", "k8s/hpa.yaml"],
        check=True
    )


@tool
def restart_pod(pod_name: str) -> dict:
    """
    Restart only the affected Kubernetes pod by deleting that single pod.
    """
    if not pod_name:
        return {
            "status": "skipped",
            "reason": "No affected pod identified."
        }

    core_v1 = _get_core_v1()

    try:
        pod = core_v1.read_namespaced_pod(
            name=pod_name,
            namespace=NAMESPACE,
        )
    except Exception:
        return {
            "status": "skipped",
            "reason": f"Pod '{pod_name}' not found."
        }

    if _pod_is_excluded(pod):
        return {
            "status": "skipped",
            "reason": f"Pod '{pod_name}' is excluded."
        }

    if _in_cooldown():
        return {"status": "cooldown"}

    if _circuit_breaker_tripped():
        return {"status": "circuit_breaker_tripped"}

    core_v1.delete_namespaced_pod(
        name=pod_name,
        namespace=NAMESPACE,
    )

    _record_action()
    logger.info(f"Restarted pod '{pod_name}' in namespace '{NAMESPACE}'.")

    return {
        "status": "success",
        "restarted_pod": pod_name,
    }

@tool
def rollback_deployment(deployment_name: str = "inframind-model-deployment") -> dict:
    """
    Rolls back a Kubernetes deployment to its previous stable revision.
    Used when scaling and pod restarts fail to stabilize the workload.
    """
    if not deployment_name:
        deployment_name = "inframind-model-deployment"

    try:
        result = subprocess.run(
            [
                "kubectl",
                "rollout",
                "undo",
                f"deployment/{deployment_name}",
                "-n",
                NAMESPACE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            logger.info(f"Successfully rolled back deployment '{deployment_name}' in namespace '{NAMESPACE}'.")
            return {
                "status": "success",
                "output": result.stdout.strip(),
            }

        logger.error(f"Failed to rollback deployment '{deployment_name}': {result.stderr.strip()}")
        return {
            "status": "failed",
            "error": result.stderr.strip(),
        }

    except Exception as e:
        logger.error(f"Exception during rollback of deployment '{deployment_name}': {str(e)}")
        return {
            "status": "failed",
            "error": str(e),
        }