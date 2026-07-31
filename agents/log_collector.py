import subprocess


def get_pod_name() -> str:
    """
    Returns the name of the application's Kubernetes pod.
    """

    result = subprocess.run(
        [
            "kubectl",
            "get",
            "pods",
            "-n", "monitoring",
            "-l",
            "app=mock-model",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip()


def collect_logs(tail: int = 200) -> list[str]:
    """
    Collects the last `tail` log lines from the application pod.
    """

    pod_name = get_pod_name()

    result = subprocess.run(
        [
            "kubectl",
            "logs",
            "-n", "monitoring",
            pod_name,
            f"--tail={tail}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    logs = result.stdout.strip().splitlines()

    return logs