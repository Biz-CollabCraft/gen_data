"""Create evaluator smoke fixtures for one positive and one negative case.

The selected case IDs are declared as examples and should be excluded from any
formal benchmark score. This script intentionally reads evaluator-only truth.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def build(root: Path) -> list[dict[str, object]]:
    truth_path = (
        root
        / "experiments"
        / "connected_air_supply"
        / "hidden_truth"
        / "scenario_truth.csv"
    )
    with truth_path.open(newline="", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    positive = next(
        row for row in truth if row["case_type"] == "positive_upstream_relation"
    )
    negative = next(row for row in truth if row["case_type"] == "negative_local_only")
    maintenance_path = root / "canonical" / "dataset" / "maintenance_event.csv"
    with maintenance_path.open(newline="", encoding="utf-8") as handle:
        maintenance_rows = list(csv.DictReader(handle))

    negative_effect_start = datetime.fromisoformat(negative["effect_started_at"])
    negative_effect_end = datetime.fromisoformat(negative["effect_ended_at"])
    negative_target = negative["affected_downstream_asset_id"]
    target_maintenance = [
        row for row in maintenance_rows if row["asset_id"] == negative_target
    ]
    overlapping_maintenance = [
        row
        for row in target_maintenance
        if datetime.fromisoformat(row["started_at"]) < negative_effect_end
        and datetime.fromisoformat(row["completed_at"]) > negative_effect_start
    ]
    maintenance_example = min(
        overlapping_maintenance or target_maintenance,
        key=lambda row: abs(
            (
                datetime.fromisoformat(row["started_at"])
                - negative_effect_start
            ).total_seconds()
        ),
        default=None,
    )

    positive_claim = {
        "case_id": positive["case_id"],
        "candidate_upstream_asset_id": positive["injected_upstream_asset_id"],
        "relation_type": "SUPPLIES_AIR_TO",
        "claim_status": "candidate",
        "evidence_asset_ids": [
            positive["injected_upstream_asset_id"],
            positive["affected_downstream_asset_id"],
        ],
        "evidence_observations": [
            {
                "evidence_type": "sensor",
                "asset_id": positive["injected_upstream_asset_id"],
                "sensor": "pressure_raw",
                "direction": "down",
                "started_at": positive["effect_started_at"],
                "ended_at": positive["effect_ended_at"],
            },
            {
                "evidence_type": "sensor",
                "asset_id": positive["affected_downstream_asset_id"],
                "sensor": "torque_nm",
                "direction": "up",
                "started_at": positive["effect_started_at"],
                "ended_at": positive["effect_ended_at"],
            },
        ],
    }
    negative_claim = {
        "case_id": negative["case_id"],
        "candidate_upstream_asset_id": None,
        "relation_type": "NO_UPSTREAM_RELATION",
        "claim_status": "unlikely",
        "evidence_asset_ids": [negative["affected_downstream_asset_id"]],
        "evidence_observations": [
            {
                "evidence_type": "sensor",
                "asset_id": negative["affected_downstream_asset_id"],
                "sensor": "torque_nm",
                "direction": "up",
                "started_at": negative["effect_started_at"],
                "ended_at": negative["effect_ended_at"],
            }
        ],
    }
    if maintenance_example is not None:
        negative_claim["evidence_observations"].append(
            {
                "evidence_type": "maintenance",
                "asset_id": maintenance_example["asset_id"],
                "maintenance_id": maintenance_example["maintenance_id"],
                "maintenance_type": maintenance_example["maintenance_type"],
                "started_at": maintenance_example["started_at"],
                "completed_at": maintenance_example["completed_at"],
                "tool_replaced": maintenance_example["tool_replaced"] == "1",
            }
        )
    claims = [positive_claim, negative_claim]
    output = root / "agent" / "agent_claims.example.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for claim in claims:
            handle.write(json.dumps(claim, ensure_ascii=False) + "\n")
    return claims


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate positive/negative evaluator examples")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    claims = build(Path(args.root))
    print(json.dumps({"example_claim_count": len(claims)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
