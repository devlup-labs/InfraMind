"""
Generates sustained, VALID traffic against /predict at high concurrency --
unlike Traffic_injector.py (which sends malformed requests to trigger
4xx/5xx anomalies), this only sends well-formed requests to spike CPU and
p95 latency with no errors. That makes the anomaly read as "increased
workload," which is what the optimization agent's system prompt requires
before it will select the horizontal_pod_scaling tool.

Usage:
  TARGET_URL=http://localhost:8000 python3 load_injector.py
  LOAD_DURATION_SECONDS=90 python3 load_injector.py   # auto-stop after 90s
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8000")
# The app is single-process/single-threaded, so anything beyond ~1 request
# in flight already queues. Keep this small -- a bigger number doesn't
# increase real throughput, it just makes the backlog grow unboundedly
# once the timeout below is exceeded.
CONCURRENT_WORKERS = int(os.getenv("LOAD_WORKERS", "5"))
DURATION_SECONDS = int(os.getenv("LOAD_DURATION_SECONDS", "0")) or None

PAYLOAD_TEXT = (
    "In the rapidly evolving landscape of distributed systems, engineers "
    "must balance consistency, availability, and partition tolerance. "
) * 5


def send_request():
    try:
        # Long timeout on purpose: this makes the loop below self-pacing --
        # it waits for requests to actually finish before submitting more,
        # instead of abandoning them client-side while they keep consuming
        # server capacity, which causes the backlog to grow unbounded.
        return requests.post(
            f"{TARGET_URL}/predict",
            json={"text": PAYLOAD_TEXT},
            headers={"Content-Type": "application/json"},
            timeout=30,
        ).status_code
    except Exception:
        return "ERR"


def start_load():
    print(f"== Generating sustained valid load on {TARGET_URL}/predict "
          f"({CONCURRENT_WORKERS} concurrent workers) ==")
    stop_at = time.time() + DURATION_SECONDS if DURATION_SECONDS else None

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        try:
            while stop_at is None or time.time() < stop_at:
                futures = [executor.submit(send_request) for _ in range(CONCURRENT_WORKERS)]
                results = [f.result() for f in futures]
                print(f"[{time.strftime('%H:%M:%S')}] batch of {len(results)}, "
                      f"sample statuses: {results[:5]}")
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    start_load()
