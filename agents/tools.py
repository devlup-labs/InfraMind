import logging
import os
import subprocess
import json
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from langchain_core.tools import tool

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

NAMESPACE = os.getenv("INFRAMIND_NAMESPACE", "default")
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


HPA_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "hpa.yaml")


@tool
def horizontal_pod_scaling():
    """Apply the Horizontal Pod Autoscaler for the application."""
    subprocess.run(
        ["kubectl", "apply", "-f", HPA_MANIFEST_PATH, "-n", NAMESPACE],
        check=True
    )


@tool
def restart_pod(pod_name: str) -> dict:
    """Restart only the affected Kubernetes pod by deleting that single pod."""
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
    """Roll back a Kubernetes deployment to its previous stable revision."""
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
            logger.info(
                f"Successfully rolled back deployment '{deployment_name}' "
                f"in namespace '{NAMESPACE}'."
            )
            return {
                "status": "success",
                "output": result.stdout.strip(),
            }

        logger.error(
            f"Failed to rollback deployment '{deployment_name}': "
            f"{result.stderr.strip()}"
        )

        return {
            "status": "failed",
            "error": result.stderr.strip(),
        }

    except Exception as e:
        logger.error(
            f"Exception during rollback of deployment "
            f"'{deployment_name}': {str(e)}"
        )

        return {
            "status": "failed",
            "error": str(e),
        }


@tool
def resource_limit_patch(
    resource: str,
    new_limit: str,
    deployment_name: str = "inframind-model-deployment"
) -> dict:
    """Patch the CPU or memory limit of the application deployment."""
    if resource not in {"cpu", "memory"}:
        return {
            "status": "failed",
            "error": "resource must be 'cpu' or 'memory'"
        }

    if not new_limit:
        return {
            "status": "failed",
            "error": "new_limit is required"
        }
    if resource == "cpu" and new_limit.endswith(" cores"):
        new_limit = f"{int(float(new_limit[:-6]) * 1000)}m"

    patch = (
        '{"spec":{"template":{"spec":{"containers":[{"name":"fastapimodel",'
        f'"resources":{{"limits":{{"{resource}":"{new_limit}"}}}}'
        '}]}}}}'
    )

    try:
        result = subprocess.run(
            [
                "kubectl",
                "patch",
                "deployment",
                deployment_name,
                "-n",
                NAMESPACE,
                "--type=strategic",
                "-p",
                patch,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            logger.error(
                f"Failed to patch {resource} limit: {result.stderr.strip()}"
            )
            return {
                "status": "failed",
                "error": result.stderr.strip(),
            }

        rollout = subprocess.run(
            [
                "kubectl",
                "rollout",
                "status",
                f"deployment/{deployment_name}",
                "-n",
                NAMESPACE,
                "--timeout=120s",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if rollout.returncode != 0:
            return {
                "status": "failed",
                "error": rollout.stderr.strip(),
                "patch_output": result.stdout.strip(),
            }

        logger.info(
            f"Updated {resource} limit for '{deployment_name}' "
            f"to '{new_limit}'."
        )

        return {
            "status": "success",
            "resource": resource,
            "new_limit": new_limit,
            "deployment": deployment_name,
            "rollout": rollout.stdout.strip(),
        }

    except Exception as e:
        logger.error(f"Resource limit patch failed: {str(e)}")
        return {
            "status": "failed",
            "error": str(e),
        }
    
@tool
def config_map_patch(
    configmap_name: str,
    key: str,
    old_value: str,
    new_value: str,
) -> dict:
    """Safely replace a ConfigMap key after verifying its live current value."""

    if not configmap_name:
        return {
            "status": "failed",
            "error": "configmap_name is required",
        }

    if not key:
        return {
            "status": "failed",
            "error": "key is required",
        }

    if old_value is None:
        return {
            "status": "failed",
            "error": "old_value is required",
        }

    if new_value is None:
        return {
            "status": "failed",
            "error": "new_value is required",
        }

    try:
        # Get the LIVE ConfigMap value.
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "configmap",
                configmap_name,
                "-n",
                NAMESPACE,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            return {
                "status": "failed",
                "error": result.stderr.strip(),
            }

        configmap = json.loads(result.stdout)
        data = configmap.get("data", {})

        if key not in data:
            return {
                "status": "failed",
                "error": f"ConfigMap key '{key}' does not exist.",
            }

        live_value = str(data[key])

        # Critical safety check:
        # only patch if the value RCA analyzed is still current.
        if live_value != str(old_value):
            return {
                "status": "conflict",
                "reason": (
                    f"Live value changed. Expected '{old_value}' "
                    f"but found '{live_value}'. No patch applied."
                ),
                "configmap": configmap_name,
                "key": key,
                "live_value": live_value,
            }

        # JSON merge patch: modify ONLY this ConfigMap key.
        patch = json.dumps({
            "data": {
                key: str(new_value)
            }
        })

        patch_result = subprocess.run(
            [
                "kubectl",
                "patch",
                "configmap",
                configmap_name,
                "-n",
                NAMESPACE,
                "--type",
                "merge",
                "-p",
                patch,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if patch_result.returncode != 0:
            logger.error(
                f"Failed to patch ConfigMap '{configmap_name}' "
                f"key '{key}': {patch_result.stderr.strip()}"
            )

            return {
                "status": "failed",
                "error": patch_result.stderr.strip(),
            }

        logger.info(
            f"Updated ConfigMap '{configmap_name}' "
            f"key '{key}': '{old_value}' -> '{new_value}'."
        )

        return {
            "status": "success",
            "configmap": configmap_name,
            "key": key,
            "old_value": live_value,
            "new_value": str(new_value),
        }

    except Exception as e:
        logger.exception("ConfigMap patch failed.")

        return {
            "status": "failed",
            "error": str(e),
        }