"""
Live integration checks for InfraMind's remediation tools, run against the
real kind cluster (not mocks -- see test.py for mocked unit tests).

Preconditions:
  - kind cluster up, kubectl context pointed at it
  - inframind-model-service port-forwarded to localhost:8000
  - agents/.env configured (GROQ_API_KEY not required for these checks)

Usage:
  python3 live_verification.py restart   # restart_pod tool
  python3 live_verification.py hpa       # HPA autoscaling under real load
  python3 live_verification.py rollback  # rollback_deployment tool
  python3 live_verification.py all       # run all three, print a summary
"""
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "agents"))

from tools import restart_pod, rollback_deployment  # noqa: E402
from Traffic_injector import generate_chaos_request  # noqa: E402

NAMESPACE = "monitoring"
DEPLOYMENT = "inframind-model-deployment"
APP_URL = "http://localhost:8000"


def _kubectl(*args: str) -> str:
    result = subprocess.run(["kubectl", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _get_pod_names() -> list[str]:
    out = _kubectl(
        "get", "pods", "-n", NAMESPACE, "-l", "app=mock-model",
        "-o", "jsonpath={.items[*].metadata.name}",
    )
    return out.split()


def _revision() -> str:
    return _kubectl(
        "get", "deployment", DEPLOYMENT, "-n", NAMESPACE,
        "-o", "jsonpath={.metadata.annotations.deployment\\.kubernetes\\.io/revision}",
    )


def verify_restart_pod() -> bool:
    print("=== restart_pod live test ===")
    pods_before = _get_pod_names()
    if not pods_before:
        print("FAIL: no running app pods found")
        return False

    target = pods_before[0]
    print(f"Restarting pod: {target}")

    result = restart_pod.invoke({"pod_name": target})
    print(f"Tool result: {result}")
    if result.get("status") != "success":
        print("FAIL: restart_pod did not report success")
        return False

    deadline = time.time() + 60
    while time.time() < deadline:
        pods_now = _get_pod_names()
        if target not in pods_now and pods_now:
            print(f"PASS: '{target}' is gone, current pods: {pods_now}")
            return True
        time.sleep(2)

    print("FAIL: old pod still present / no replacement pod after 60s")
    return False


def _app_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{APP_URL}/health", timeout=2)
        return True
    except Exception:
        return False


def _ensure_port_forward() -> None:
    """kubectl port-forward targets one specific pod and dies whenever that
    pod is replaced (rollout, restart_pod, HPA scale event). Re-establish it
    if the app isn't reachable so a stale forward doesn't silently zero out
    the load this test generates."""
    if _app_reachable():
        return

    print("App not reachable on localhost:8000 -- (re)starting port-forward...")
    subprocess.run(
        ["pkill", "-f", "port-forward.*8000:8000"],
        capture_output=True,
    )
    subprocess.Popen(
        ["kubectl", "port-forward", "-n", NAMESPACE, "svc/inframind-model-service", "8000:8000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 20
    while time.time() < deadline:
        if _app_reachable():
            print("Port-forward ready.")
            return
        time.sleep(1)

    raise RuntimeError("Could not establish port-forward to inframind-model-service:8000")


def verify_hpa_scaling(duration_seconds: int = 120, workers: int = 15) -> bool:
    print("=== HPA scaling live test ===")
    _ensure_port_forward()

    # kubectl port-forward pins to a single backing pod, so with >1 replica
    # already running, synthetic load only ever reaches one of them -- the
    # other pods report no data for the custom pod metrics and the HPA
    # errors out to <unknown> instead of reading low. Reset to a known
    # single-pod baseline so the test is deterministic regardless of
    # leftover replica count from earlier runs.
    print("Resetting to a known baseline of 1 replica...")
    _kubectl("scale", "deployment", DEPLOYMENT, "-n", NAMESPACE, "--replicas=1")
    _kubectl("rollout", "status", f"deployment/{DEPLOYMENT}", "-n", NAMESPACE, "--timeout=90s")
    _ensure_port_forward()

    baseline = int(_kubectl(
        "get", "deployment", DEPLOYMENT, "-n", NAMESPACE,
        "-o", "jsonpath={.status.replicas}",
    ) or "1")
    print(f"Baseline replicas: {baseline}")
    print(f"Flooding traffic for up to {duration_seconds}s with {workers} concurrent workers...")

    stop_at = time.time() + duration_seconds
    scaled = False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while time.time() < stop_at:
            _ensure_port_forward()
            futures = [pool.submit(generate_chaos_request) for _ in range(workers)]
            [f.result() for f in futures]

            replicas = int(_kubectl(
                "get", "deployment", DEPLOYMENT, "-n", NAMESPACE,
                "-o", "jsonpath={.status.replicas}",
            ) or str(baseline))
            if replicas > baseline:
                print(f"PASS: replicas went {baseline} -> {replicas}")
                scaled = True
                break
            time.sleep(0.3)

    if not scaled:
        print(f"FAIL: replicas never exceeded baseline ({baseline}) within {duration_seconds}s")
    return scaled


def verify_rollback() -> bool:
    print("=== rollback_deployment live test ===")
    before_rev = _revision()
    print(f"Revision before forced change: {before_rev}")

    # Force a genuine new revision (pod template change) so there's
    # something real for the tool to roll back to.
    _kubectl(
        "patch", "deployment", DEPLOYMENT, "-n", NAMESPACE, "--type=json",
        "-p", f'[{{"op":"add","path":"/spec/template/metadata/annotations/live-test-bump",'
              f'"value":"{time.time()}"}}]',
    )
    _kubectl("rollout", "status", f"deployment/{DEPLOYMENT}", "-n", NAMESPACE, "--timeout=90s")

    mid_rev = _revision()
    print(f"Revision after forced change: {mid_rev}")

    result = rollback_deployment.invoke({"deployment_name": DEPLOYMENT})
    print(f"Tool result: {result}")
    if result.get("status") != "success":
        print("FAIL: rollback_deployment did not report success")
        return False

    _kubectl("rollout", "status", f"deployment/{DEPLOYMENT}", "-n", NAMESPACE, "--timeout=90s")
    after_rev = _revision()
    print(f"Revision after rollback: {after_rev}")

    if after_rev != mid_rev:
        print(f"PASS: rollback moved revision {mid_rev} -> {after_rev}")
        return True

    print("FAIL: revision did not change after rollback")
    return False


if __name__ == "__main__":
    tests = {
        "restart": verify_restart_pod,
        "hpa": verify_hpa_scaling,
        "rollback": verify_rollback,
    }
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which not in {*tests, "all"}:
        print(f"Unknown test '{which}'. Choose from: restart, hpa, rollback, all")
        sys.exit(2)

    to_run = tests.items() if which == "all" else [(which, tests[which])]

    results = {}
    for name, fn in to_run:
        results[name] = fn()
        print()

    print("=== SUMMARY ===")
    for name, ok in results.items():
        print(f"{name}: {'PASS' if ok else 'FAIL'}")

    sys.exit(0 if all(results.values()) else 1)
