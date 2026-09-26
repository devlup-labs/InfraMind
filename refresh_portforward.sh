#!/bin/bash
# Kills any stale port-forward on 8000 and starts a fresh one against the
# current live pod behind the Service, then waits until /health responds.
# Run this before every Traffic_injector.py / main.py cycle.

set -e

pkill -f "port-forward.*8000:8000" 2>/dev/null || true
sleep 1

kubectl port-forward -n monitoring svc/inframind-model-service 8000:8000 > /tmp/portforward-8000.log 2>&1 &

echo "Waiting for port-forward to become healthy..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "Port-forward healthy after ${i}s."
        exit 0
    fi
    sleep 1
done

echo "Port-forward did not become healthy in time. Log:"
cat /tmp/portforward-8000.log
exit 1
