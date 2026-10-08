#!/bin/bash
# Kills any stale port-forwards on 8000 (app) and 9090 (Prometheus) and
# starts fresh ones against the current live pods behind their Services,
# then waits until each health endpoint responds.
# Run this before every Traffic_injector.py / main.py cycle.

set -e

# ---- App (8000) ----
pkill -f "port-forward.*8000:8000" 2>/dev/null || true
sleep 1
kubectl port-forward -n monitoring svc/inframind-model-service 8000:8000 > /tmp/portforward-8000.log 2>&1 &

# ---- Prometheus (9090) ----
pkill -f "port-forward.*9090:9090" 2>/dev/null || true
sleep 1
kubectl port-forward -n monitoring svc/prometheus-service 9090:9090 > /tmp/portforward-9090.log 2>&1 &

APP_OK=0
PROM_OK=0

echo "Waiting for port-forwards to become healthy..."
for i in $(seq 1 15); do
    if [ "$APP_OK" -eq 0 ] && curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "App port-forward (8000) healthy after ${i}s."
        APP_OK=1
    fi

    if [ "$PROM_OK" -eq 0 ] && curl -sf http://localhost:9090/-/healthy > /dev/null 2>&1; then
        echo "Prometheus port-forward (9090) healthy after ${i}s."
        PROM_OK=1
    fi

    if [ "$APP_OK" -eq 1 ] && [ "$PROM_OK" -eq 1 ]; then
        exit 0
    fi

    sleep 1
done

echo "One or more port-forwards did not become healthy in time."

if [ "$APP_OK" -eq 0 ]; then
    echo "--- App (8000) log ---"
    cat /tmp/portforward-8000.log 2>/dev/null || echo "(no log file written)"
fi

if [ "$PROM_OK" -eq 0 ]; then
    echo "--- Prometheus (9090) log ---"
    cat /tmp/portforward-9090.log 2>/dev/null || echo "(no log file written)"
fi

exit 1