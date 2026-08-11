"""Score agent relation-reasoning claims against evaluator-only hidden truth."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


REQUIRED_FIELDS = {
    "case_id",
    "candidate_upstream_asset_id",
    "relation_type",
    "claim_status",
    "evidence_asset_ids",
    "evidence_observations",
}

REQUIRED_SENSOR_EVIDENCE_FIELDS = {
    "evidence_type",
    "asset_id",
    "sensor",
    "direction",
    "started_at",
    "ended_at",
}

REQUIRED_MAINTENANCE_EVIDENCE_FIELDS = {
    "evidence_type",
    "asset_id",
    "maintenance_id",
    "maintenance_type",
    "started_at",
    "completed_at",
    "tool_replaced",
}


def load_claims(path: Path) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = REQUIRED_FIELDS - set(row)
            if missing:
                raise ValueError(f"line {line_number} missing fields: {sorted(missing)}")
            if row["claim_status"] not in {"candidate", "unlikely", "confirmed"}:
                raise ValueError(f"line {line_number} has invalid claim_status")
            if not isinstance(row["evidence_asset_ids"], list):
                raise ValueError(f"line {line_number} evidence_asset_ids must be a list")
            if not isinstance(row["evidence_observations"], list):
                raise ValueError(f"line {line_number} evidence_observations must be a list")
            for evidence_index, evidence in enumerate(row["evidence_observations"], start=1):
                if not isinstance(evidence, dict):
                    raise ValueError(
                        f"line {line_number} evidence {evidence_index} must be an object"
                    )
                evidence_type = str(evidence.get("evidence_type", "sensor"))
                evidence["evidence_type"] = evidence_type
                if evidence_type == "sensor":
                    required_evidence_fields = REQUIRED_SENSOR_EVIDENCE_FIELDS
                elif evidence_type == "maintenance":
                    required_evidence_fields = REQUIRED_MAINTENANCE_EVIDENCE_FIELDS
                else:
                    raise ValueError(
                        f"line {line_number} evidence {evidence_index} has invalid evidence_type"
                    )
                missing_evidence = required_evidence_fields - set(evidence)
                if missing_evidence:
                    raise ValueError(
                        f"line {line_number} evidence {evidence_index} missing fields: "
                        f"{sorted(missing_evidence)}"
                    )
                started_at = datetime.fromisoformat(str(evidence["started_at"]))
                if evidence_type == "sensor":
                    if evidence["direction"] not in {"up", "down", "stable"}:
                        raise ValueError(
                            f"line {line_number} evidence {evidence_index} has invalid direction"
                        )
                    ended_at = datetime.fromisoformat(str(evidence["ended_at"]))
                    if ended_at <= started_at:
                        raise ValueError(
                            f"line {line_number} evidence {evidence_index} has non-positive duration"
                        )
                else:
                    completed_at = datetime.fromisoformat(str(evidence["completed_at"]))
                    if completed_at <= started_at:
                        raise ValueError(
                            f"line {line_number} evidence {evidence_index} has non-positive maintenance duration"
                        )
                    if not isinstance(evidence["tool_replaced"], bool):
                        raise ValueError(
                            f"line {line_number} evidence {evidence_index} tool_replaced must be boolean"
                        )
            claims.append(row)
    return claims


def overlaps_hidden_window(
    evidence: dict[str, object],
    effect_started_at: datetime,
    effect_ended_at: datetime,
) -> bool:
    evidence_start = datetime.fromisoformat(str(evidence["started_at"]))
    evidence_end = datetime.fromisoformat(str(evidence["ended_at"]))
    overlap_start = max(evidence_start, effect_started_at)
    overlap_end = min(evidence_end, effect_ended_at)
    if overlap_end <= overlap_start:
        return False
    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    shorter_window_seconds = min(
        (evidence_end - evidence_start).total_seconds(),
        (effect_ended_at - effect_started_at).total_seconds(),
    )
    return overlap_seconds / max(shorter_window_seconds, 1.0) >= 0.5


def evaluate(root: Path, claim_path: Path) -> dict[str, object]:
    hidden_path = (
        root
        / "experiments"
        / "connected_air_supply"
        / "hidden_truth"
        / "scenario_truth.csv"
    )
    with hidden_path.open(newline="", encoding="utf-8") as handle:
        truth_rows = list(csv.DictReader(handle))
    truth = {row["case_id"]: row for row in truth_rows}
    if len(truth) != len(truth_rows):
        raise ValueError("duplicate case_id in hidden truth")
    claims = load_claims(claim_path)
    maintenance_path = root / "canonical" / "dataset" / "maintenance_event.csv"
    with maintenance_path.open(newline="", encoding="utf-8") as handle:
        maintenance_rows = list(csv.DictReader(handle))
    maintenance_by_id = {row["maintenance_id"]: row for row in maintenance_rows}
    if len(maintenance_by_id) != len(maintenance_rows):
        raise ValueError("duplicate maintenance_id in canonical maintenance history")
    claim_case_ids = [str(item["case_id"]) for item in claims]
    if len(claim_case_ids) != len(set(claim_case_ids)):
        raise ValueError("duplicate case_id in claim file")
    results: list[dict[str, object]] = []

    for claim in claims:
        case_id = str(claim["case_id"])
        if case_id not in truth:
            results.append({"case_id": case_id, "valid_case": False, "score": 0.0})
            continue
        expected = truth[case_id]
        case_type = str(expected.get("case_type", "positive_upstream_relation"))
        is_negative = case_type == "negative_local_only"
        candidate_upstream = claim["candidate_upstream_asset_id"]
        normalized_candidate = (
            None
            if candidate_upstream is None
            or str(candidate_upstream).strip().upper() in {"", "NONE", "NULL"}
            else str(candidate_upstream)
        )
        expected_upstream = str(expected["injected_upstream_asset_id"]).strip()
        upstream_hit = (
            normalized_candidate is None
            if is_negative
            else normalized_candidate == expected_upstream
        )
        relation_hit = str(claim["relation_type"]) == str(expected["relation_type"])
        evidence = {str(item) for item in claim["evidence_asset_ids"]}
        expected_target = str(expected["affected_downstream_asset_id"])
        evidence_hit = (
            expected_target in evidence
            if is_negative
            else {expected_upstream, expected_target}.issubset(evidence)
        )
        effect_started_at = datetime.fromisoformat(str(expected["effect_started_at"]))
        effect_ended_at = datetime.fromisoformat(str(expected["effect_ended_at"]))
        evidence_observations = [
            item
            for item in claim["evidence_observations"]
            if isinstance(item, dict)
        ]
        sensor_evidence = [
            item
            for item in evidence_observations
            if str(item.get("evidence_type", "sensor")) == "sensor"
        ]
        maintenance_evidence = [
            item
            for item in evidence_observations
            if str(item.get("evidence_type")) == "maintenance"
        ]
        maintenance_evidence_matches: list[bool] = []
        for item in maintenance_evidence:
            canonical = maintenance_by_id.get(str(item["maintenance_id"]))
            maintenance_evidence_matches.append(
                canonical is not None
                and canonical["asset_id"] == str(item["asset_id"])
                and canonical["maintenance_type"] == str(item["maintenance_type"])
                and canonical["started_at"] == str(item["started_at"])
                and canonical["completed_at"] == str(item["completed_at"])
                and (canonical["tool_replaced"] == "1")
                == bool(item["tool_replaced"])
            )
        maintenance_evidence_valid = all(maintenance_evidence_matches)
        upstream_temporal_evidence = (
            True
            if is_negative
            else any(
                str(item["asset_id"]) == expected_upstream
                and str(item["sensor"]) == "pressure_raw"
                and str(item["direction"]) == "down"
                and overlaps_hidden_window(item, effect_started_at, effect_ended_at)
                for item in sensor_evidence
            )
        )
        target_temporal_evidence = any(
            str(item["asset_id"]) == expected_target
            and str(item["sensor"])
            in {"torque_nm", "process_temperature_k"}
            and str(item["direction"]) == "up"
            and overlaps_hidden_window(item, effect_started_at, effect_ended_at)
            for item in sensor_evidence
        )
        expected_status = str(expected.get("expected_claim_status", "candidate"))
        calibrated = claim["claim_status"] == expected_status
        false_upstream_claim = is_negative and normalized_candidate is not None
        if is_negative:
            score = (
                0.35 * int(upstream_hit)
                + 0.20 * int(relation_hit)
                + 0.15 * int(evidence_hit)
                + 0.15 * int(target_temporal_evidence)
                + 0.15 * int(calibrated)
            )
        else:
            score = (
                0.30 * int(upstream_hit)
                + 0.15 * int(relation_hit)
                + 0.10 * int(evidence_hit)
                + 0.15 * int(upstream_temporal_evidence)
                + 0.15 * int(target_temporal_evidence)
                + 0.15 * int(calibrated)
            )
        if maintenance_evidence and not maintenance_evidence_valid:
            score = 0.0
        results.append(
            {
                "case_id": case_id,
                "valid_case": True,
                "case_type": case_type,
                "upstream_hit": upstream_hit,
                "relation_hit": relation_hit,
                "evidence_coverage": evidence_hit,
                "upstream_temporal_evidence": upstream_temporal_evidence,
                "target_temporal_evidence": target_temporal_evidence,
                "maintenance_evidence_count": len(maintenance_evidence),
                "maintenance_evidence_valid": maintenance_evidence_valid,
                "causal_language_calibrated": calibrated,
                "false_upstream_claim": false_upstream_claim,
                "score": round(score, 4),
            }
        )

    valid = [item for item in results if item.get("valid_case")]
    positive = [item for item in valid if item.get("case_type") == "positive_upstream_relation"]
    negative = [item for item in valid if item.get("case_type") == "negative_local_only"]
    try:
        claim_file_display = str(claim_path.resolve().relative_to(root.resolve()))
    except ValueError:
        claim_file_display = str(claim_path)
    summary = {
        "claim_file": claim_file_display,
        "claims": len(claims),
        "valid_cases": len(valid),
        "mean_score": round(
            sum(float(item["score"]) for item in valid) / max(1, len(valid)), 4
        ),
        "upstream_accuracy": round(
            sum(bool(item.get("upstream_hit")) for item in valid) / max(1, len(valid)), 4
        ),
        "positive_upstream_accuracy": round(
            sum(bool(item.get("upstream_hit")) for item in positive)
            / max(1, len(positive)),
            4,
        ),
        "negative_rejection_accuracy": round(
            sum(
                bool(item.get("upstream_hit"))
                and bool(item.get("relation_hit"))
                and bool(item.get("causal_language_calibrated"))
                for item in negative
            )
            / max(1, len(negative)),
            4,
        ),
        "false_upstream_claim_rate": round(
            sum(bool(item.get("false_upstream_claim")) for item in negative)
            / max(1, len(negative)),
            4,
        ),
        "relation_accuracy": round(
            sum(bool(item.get("relation_hit")) for item in valid) / max(1, len(valid)), 4
        ),
        "calibration_rate": round(
            sum(bool(item.get("causal_language_calibrated")) for item in valid)
            / max(1, len(valid)),
            4,
        ),
        "temporal_evidence_rate": round(
            sum(
                bool(item.get("upstream_temporal_evidence"))
                and bool(item.get("target_temporal_evidence"))
                for item in valid
            )
            / max(1, len(valid)),
            4,
        ),
        "maintenance_evidence_claims": sum(
            int(item.get("maintenance_evidence_count", 0)) > 0 for item in valid
        ),
        "maintenance_evidence_accuracy": round(
            sum(
                bool(item.get("maintenance_evidence_valid"))
                for item in valid
                if int(item.get("maintenance_evidence_count", 0)) > 0
            )
            / max(
                1,
                sum(
                    int(item.get("maintenance_evidence_count", 0)) > 0
                    for item in valid
                ),
            ),
            4,
        ),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "results": results,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agent cause-candidate claims")
    parser.add_argument("claims")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = evaluate(Path(args.root), Path(args.claims))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

