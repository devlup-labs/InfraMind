"""Deterministically normalize Terraform's machine-readable plan format."""

import json
from pathlib import Path

def parse_plan_file(plan_path):
    """Load a terraform show -json tfplan.json file and extract normalized resource changes."""
    with Path(plan_path).open(encoding="utf-8") as f:
        plan = json.load(f)
    
    normalized = []
    for change in plan.get("resource_changes", []):
        change_info = change.get("change", {})
        normalized.append({
            "address": change.get("address"),
            "resource_type": change.get("type"),
            "resource_name": change.get("name"),
            "provider_name": change.get("provider_name"),
            "actions": change_info.get("actions", []),
            "before": change_info.get("before", {}),
            "after": change_info.get("after", {}),
            "after_unknown": change_info.get("after_unknown", {})
        })
    return normalized

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Normalize a Terraform JSON plan")
    parser.add_argument("plan_path", help="Path to terraform plan json file")
    args = parser.parse_args()
    print(json.dumps(parse_plan_file(args.plan_path), indent=2))
