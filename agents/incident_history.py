"""
Minimal persistent incident history. Every completed pipeline run appends one
record here; future runs read recent records for the same deployment to build
'precedence' edges in the evidence graph -- i.e. "has something like this
happened before, and what did we do about it?"

Deliberately a flat JSONL file, not a database -- this is meant to be the
simplest thing that lets the precedence edge type mean something. Can be
swapped for a real store later without changing the calling code's shape.
"""

import json
import os
from datetime import datetime, timezone

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "incident_history.jsonl")


def append_incident(
    deployment_name: str,
    suspect_metric: str,
    primary_cause: str,
    final_status: str,
    affected_pod: str | None = None,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "deployment_name": deployment_name,
        "suspect_metric": suspect_metric,
        "primary_cause": primary_cause,
        "final_status": final_status,
        "affected_pod": affected_pod,
    }
    try:
        with open(HISTORY_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[WARNING] Failed to write incident history: {e}")


def load_recent_incidents(deployment_name: str, limit: int = 5) -> list[dict]:
    if not os.path.exists(HISTORY_PATH):
        return []

    try:
        with open(HISTORY_PATH, "r") as f:
            lines = f.readlines()
    except Exception:
        return []

    records = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("deployment_name") == deployment_name:
            records.append(record)
        if len(records) >= limit:
            break

    return records