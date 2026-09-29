from log_collector import collect_logs, get_pod_name

ERROR_TERMS = ["error", "exception", "fail", "timeout", "5xx", "500", "traceback"]


def run_logs_agent() -> dict:
    """
    Observation sub-agent: identifies the currently affected pod and pulls
    its recent logs, pre-filtering for error-like lines so the triage
    controller doesn't have to scan raw log volume itself.
    """
    pod_name = get_pod_name()
    logs = collect_logs()

    error_like = [
        line for line in logs
        if any(term in str(line).lower() for term in ERROR_TERMS)
    ]

    return {
        "affected_pod": pod_name,
        "logs": logs,
        "error_like_logs": error_like,
    }