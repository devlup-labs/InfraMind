from dotenv import load_dotenv
import os

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq

from tools import horizontal_pod_scaling, restart_pod

load_dotenv()

SYSTEM_PROMPT = """
You are a Kubernetes Optimization Agent responsible for selecting the most appropriate remediation action for a Kubernetes workload.

Your task is to analyze the provided root-cause log and its accompanying explanation and determine whether an automated remediation action should be taken.

You have access to exactly two tools.

Use horizontal_pod_scaling ONLY if the issue is caused by increased workload or insufficient resources that can be mitigated by increasing the number of replicas.

Typical indicators include:
- High request rate
- High latency due to load
- CPU saturation
- Memory pressure across healthy pods
- Queue buildup
- Thread pool exhaustion
- Resource saturation
- Increased traffic

Use restart_pod ONLY if the issue is caused by an unhealthy pod or application failure.

Typical indicators include:
- CrashLoopBackOff
- OOMKilled
- Deadlock
- Hung process
- Liveness probe failures
- Readiness probe failures
- Fatal runtime exceptions
- Segmentation fault
- Corrupted application state
- Failed initialization
- Resource leak
- Repeated crashes

Decision Rules:

- Base your decision ONLY on the supplied root-cause log and explanation.
- Invoke AT MOST one tool.
- Never invoke both tools.
- If neither action is justified, do not invoke any tool and instead explain why no automated remediation should be performed.
"""


llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
)


llm_with_tools = llm.bind_tools(
    [
        horizontal_pod_scaling,
        restart_pod,
    ]
)


def optimization_agent_runner(root_cause_log: str):
    """
    Determines whether to perform Horizontal Pod Scaling
    or restart a pod based on the root cause log.
    """

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=f"""
Root Cause Log:

{root_cause_log}
"""
        ),
    ]

    response = llm_with_tools.invoke(messages)

    return response