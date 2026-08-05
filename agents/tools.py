#the tool name is horizontal_pod_scaling, restart_pod
from langchain_core.tools import tool
import subprocess


@tool
def horizontal_pod_scaling():
    """
    Apply the Horizontal Pod Autoscaler for the application.
    """
    subprocess.run(
        ["kubectl", "apply", "-f", "k8s/hpa.yaml"],
        check=True
    )

