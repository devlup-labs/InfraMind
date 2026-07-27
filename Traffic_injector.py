import requests
import time
import random
from concurrent.futures import ThreadPoolExecutor

TARGET_URL = "http://192.168.49.2:30000/predict"

def send_request(payload_type):
    headers = {"Content-Type": "application/json"}

    if payload_type == "healthy":
        payload = {"text": "This infrastructure is solid and running perfectly."}

    elif payload_type == "massive_string":
        payload = {"text": "error " * 10000} 
        

    elif payload_type == "wrong_type":
        payload = {"text": None} 

    elif payload_type == "missing_field":
        payload = {"bad_key": "where is the text field?"}

    try:
        response = requests.post(TARGET_URL, json=payload, headers=headers, timeout=10)
        print(f"[{payload_type.upper()}] Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[{payload_type.upper()}] Request crashed/timeout: {e}")

def simulate_traffic():
    print("Sending baseline healthy traffic...")
    # Send 20 healthy requests to establish a baseline in Prometheus
    with ThreadPoolExecutor(max_workers=5) as executor:
        for _ in range(20):
            executor.submit(send_request, "healthy")
            time.sleep(0.2)

    print("\nINJECTING CHAOS! Sending bad traffic...")

    bad_payloads = ["massive_string", "wrong_type", "missing_field", "healthy"] * 30
    random.shuffle(bad_payloads)

    with ThreadPoolExecutor(max_workers=15) as executor:
        for payload_type in bad_payloads:
            executor.submit(send_request, payload_type)
            time.sleep(0.05)
            
    print("\n Traffic injection complete. Check your logs and Prometheus!")

if __name__ == "__main__":
    simulate_traffic()