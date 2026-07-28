import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
import requests

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8000")
CONCURRENT_WORKERS = 5  # Scaled down to prevent lag


def generate_chaos_request():
    scenario = random.choices(
        population=[
            "404_NOT_FOUND",
            "405_BAD_METHOD",
            "422_BAD_SCHEMA",
            "500_HEAVY",
            "200_VALID",
        ],
        weights=[30, 20, 30, 10, 10],
        k=1,
    )[0]

    headers = {"Content-Type": "application/json"}

    try:
        if scenario == "404_NOT_FOUND":
            return requests.get(
                f"{TARGET_URL}/bad-endpoint-{random.randint(1, 999)}", timeout=2
            ).status_code
        elif scenario == "405_BAD_METHOD":
            return requests.get(f"{TARGET_URL}/predict", timeout=2).status_code
        elif scenario == "422_BAD_SCHEMA":
            return requests.post(
                f"{TARGET_URL}/predict", json={}, headers=headers, timeout=2
            ).status_code
        elif scenario == "500_HEAVY":
            return requests.post(
                f"{TARGET_URL}/predict",
                json={"text": "STRESS " * 1000},
                headers=headers,
                timeout=3,
            ).status_code
        else:
            return requests.post(
                f"{TARGET_URL}/predict",
                json={"text": "normal request"},
                headers=headers,
                timeout=2,
            ).status_code
    except Exception:
        return "ERR"


def start_flood():
    print(
        f"== Running Lightweight Chaos Flood on {TARGET_URL} (No Lag) =="
    )
    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        try:
            while True:
                futures = [
                    executor.submit(generate_chaos_request) for _ in range(5)
                ]
                results = [f.result() for f in futures]
                print(
                    f"[{time.strftime('%H:%M:%S')}] Batch results: {results}"
                )
                time.sleep(0.4)  # Smooth pause so Uvicorn stays responsive
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    start_flood()