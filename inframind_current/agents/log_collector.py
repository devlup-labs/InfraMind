import os
import subprocess
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

NAMESPACE = os.getenv("INFRAMIND_NAMESPACE", "default")


def get_pod_name() -> str:
    result = subprocess.run(
        [
            "kubectl",
            "get", "pods",
            "-n", NAMESPACE,
            "-l", "app=mock-model",
            "-o", "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def collect_logs(tail: int = 200) -> list[str]:
    pod_name = get_pod_name()

    result = subprocess.run(
        [
            "kubectl",
            "logs",
            "-n", NAMESPACE,
            pod_name,
            f"--tail={tail}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip().splitlines()