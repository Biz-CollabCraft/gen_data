"""Validate canonical separation, experiment isolation, and model contracts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from ai4i_contract import (
    AI4I_DISTRIBUTION_TARGETS,
    AI4I_RELATION_THRESHOLDS,
    failure_condition,
    power_w,
)


BANNED_CANONICAL_FIELDS = {
    "upstream_pressure_deficit",
    "upstream_asset_id",
    "supplying_compressor_id",
    "simulated_exposure_index",
    "scenario_id",
    "intervention_id",
    "torque_delta_nm",
    "process_temperature_delta_k",
    "tool_wear_rate_multiplier",
    "synthetic_upstream_torque_effect",
    "synthetic_upstream_wear_multiplier",
    "failure_probability",
    "predicted_failure_type",
    "prediction_confidence",
    "shap_value",
    "top_factors",
    "snr_profile",
    "signal_strength",
    "failure_occurred_at",
    "cycles_to_next_event",
    "min_ttf",
}

HIDDEN_FIELD_NAMES = {
    "case_type",
    "expected_claim_status",
    "local_cause",
    "injected_upstream_asset_id",
    "affected_downstream_asset_id",
    "effect_started_at",
    "effect_ended_at",
    "pressure_drop_fraction_max",
    "torque_delta_nm_max",
    "process_temperature_delta_k_max",
    "tool_wear_delta_min_max",
}

TOOL_WEAR_DECREASE_TOLERANCE_MIN = 1.0
TOOL_WEAR_RESET_MAX_MIN = 5.0


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise AssertionError(f"non-object JSONL row in {path.name}:{line_number}")
            rows.append(payload)
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def pearson(values_a: list[float], values_b: list[float]) -> float:
    if len(values_a) != len(values_b) or len(values_a) < 2:
        raise AssertionError("correlation requires equal non-empty vectors")
    mean_a = statistics.fmean(values_a)
    mean_b = statistics.fmean(values_b)
    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(values_a, values_b))
    denominator = math.sqrt(
        sum((a - mean_a) ** 2 for a in values_a)
        * sum((b - mean_b) ** 2 for b in values_b)
    )
    if denominator == 0:
        raise AssertionError("zero-variance vector in correlation")
    return numerator / denominator


def validate(root: Path) -> dict[str, object]:
    dataset_dir = root / "canonical" / "dataset"
    truth_dir = root / "canonical" / "evaluation_truth"
    experiment_root = root / "experiments" / "connected_air_supply"
    validation_dir = root / "canonical" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    required = [
        dataset_dir / "asset_master.csv",
        dataset_dir / "asset_relation.csv",
        dataset_dir / "compressor_sensor_observation.csv",
        dataset_dir / "cnc_sensor_observation.csv",
        dataset_dir / "cnc_production_cycle.csv",
        dataset_dir / "maintenance_event.csv",
        dataset_dir / "dataset_manifest.json",
        truth_dir / "failure_schedule.csv",
        truth_dir / "compressor_failure_truth.csv",
        truth_dir / "cnc_failure_truth.csv",
        experiment_root / "public_case_index.csv",
        experiment_root / "hidden_truth" / "scenario_truth.csv",
        experiment_root / "experiment_manifest.json",
        validation_dir / "agent_claims_example_evaluation.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise AssertionError(f"required outputs missing: {missing}")

    manifest = json.loads((dataset_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    experiment_manifest = json.loads(
        (experiment_root / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    agent_example_evaluation = json.loads(
        (validation_dir / "agent_claims_example_evaluation.json").read_text(
            encoding="utf-8"
        )
    )
    if agent_example_evaluation.get("positive_cases") != 1:
        raise AssertionError("agent example must include one positive case")
    if agent_example_evaluation.get("negative_cases") != 1:
        raise AssertionError("agent example must include one negative case")
    if agent_example_evaluation.get("positive_upstream_accuracy") != 1.0:
        raise AssertionError("positive agent example failed")
    if agent_example_evaluation.get("negative_rejection_accuracy") != 1.0:
        raise AssertionError("negative agent example failed")
    if agent_example_evaluation.get("false_upstream_claim_rate") != 0.0:
        raise AssertionError("negative agent example makes a false upstream claim")
    if agent_example_evaluation.get("maintenance_evidence_claims", 0) < 1:
        raise AssertionError("agent example must include maintenance evidence")
    if agent_example_evaluation.get("maintenance_evidence_accuracy") != 1.0:
        raise AssertionError("agent maintenance evidence failed canonical validation")

    canonical_paths = {
        "asset_master.csv": dataset_dir / "asset_master.csv",
        "asset_relation.csv": dataset_dir / "asset_relation.csv",
        "compressor_sensor_observation.csv": dataset_dir
        / "compressor_sensor_observation.csv",
        "cnc_sensor_observation.csv": dataset_dir / "cnc_sensor_observation.csv",
        "cnc_production_cycle.csv": dataset_dir / "cnc_production_cycle.csv",
        "maintenance_event.csv": dataset_dir / "maintenance_event.csv",
    }
    canonical_fields: dict[str, list[str]] = {}
    canonical_rows: dict[str, list[dict[str, str]]] = {}
    for name, path in canonical_paths.items():
        fields, rows = read_csv(path)
        canonical_fields[name] = fields
        canonical_rows[name] = rows
        leaked = sorted(set(fields) & BANNED_CANONICAL_FIELDS)
        if leaked:
            raise AssertionError(f"forbidden fields in canonical {name}: {leaked}")
        expected = manifest["canonical_outputs"].get(name)
        if expected != sha256(path):
            raise AssertionError(f"canonical checksum mismatch: {name}")

    truth_paths = {
        "failure_schedule.csv": truth_dir / "failure_schedule.csv",
        "compressor_failure_truth.csv": truth_dir / "compressor_failure_truth.csv",
        "cnc_failure_truth.csv": truth_dir / "cnc_failure_truth.csv",
    }
    truth_rows: dict[str, list[dict[str, str]]] = {}
    truth_fields: set[str] = set()
    for name, path in truth_paths.items():
        fields, rows = read_csv(path)
        truth_rows[name] = rows
        truth_fields |= set(fields)
        expected = manifest["evaluation_truth_outputs"].get(name)
        if expected != sha256(path):
            raise AssertionError(f"evaluation truth checksum mismatch: {name}")
    if not {"failure_occurred_at", "snr_profile", "signal_strength"}.issubset(truth_fields):
        raise AssertionError("evaluation truth provenance fields missing")

    assets = canonical_rows["asset_master.csv"]
    relations = canonical_rows["asset_relation.csv"]
    asset_ids = [row["asset_id"] for row in assets]
    if len(asset_ids) != len(set(asset_ids)):
        raise AssertionError("duplicate asset_id in asset master")
    asset_by_id = {row["asset_id"]: row for row in assets}
    asset_types = Counter(row["asset_type"] for row in assets)
    if asset_types != Counter({"compressor": 20, "cnc": 80}):
        raise AssertionError(f"unexpected topology: {asset_types}")
    if len(relations) != 80 or any(row["relation_type"] != "SUPPLIES_AIR_TO" for row in relations):
        raise AssertionError("relation topology invalid")
    for relation in relations:
        source = asset_by_id.get(relation["from_asset_id"])
        target = asset_by_id.get(relation["to_asset_id"])
        if source is None or target is None:
            raise AssertionError("relation references an unknown asset")
        if source["asset_type"] != "compressor" or target["asset_type"] != "cnc":
            raise AssertionError("relation asset types are invalid")
    supplier_counts = Counter(row["to_asset_id"] for row in relations)
    downstream_counts = Counter(row["from_asset_id"] for row in relations)
    cnc_ids = {row["asset_id"] for row in assets if row["asset_type"] == "cnc"}
    compressor_ids = {row["asset_id"] for row in assets if row["asset_type"] == "compressor"}
    if set(supplier_counts) != cnc_ids or any(count != 1 for count in supplier_counts.values()):
        raise AssertionError("each CNC must have exactly one supplying compressor")
    if set(downstream_counts) != compressor_ids or any(count != 4 for count in downstream_counts.values()):
        raise AssertionError("each compressor must supply exactly four CNC assets")

    expected_ticks = int(
        int(manifest["days"]) * 24 * 60 / int(manifest["observation_interval_minutes"])
    )
    observation_specs = [
        ("compressor_sensor_observation.csv", "compressor", 20 * expected_ticks),
        ("cnc_sensor_observation.csv", "cnc", 80 * expected_ticks),
    ]
    for name, expected_type, expected_count in observation_specs:
        rows = canonical_rows[name]
        if len(rows) != expected_count:
            raise AssertionError(f"unexpected observation row count in {name}")
        keys = {(row["asset_id"], row["observed_at"]) for row in rows}
        if len(keys) != len(rows):
            raise AssertionError(f"duplicate asset/timestamp observation in {name}")
        for row in rows:
            asset = asset_by_id.get(row["asset_id"])
            if asset is None or asset["asset_type"] != expected_type:
                raise AssertionError(f"invalid observation asset in {name}")
            if row["is_operating"] not in {"0", "1"}:
                raise AssertionError(f"invalid is_operating value in {name}")
            if (row["operating_state"] == "maintenance") != (row["is_operating"] == "0"):
                raise AssertionError(f"operating state mismatch in {name}")

    production_rows = canonical_rows["cnc_production_cycle.csv"]
    product_ids = [row["product_id"] for row in production_rows]
    if len(product_ids) != len(set(product_ids)):
        raise AssertionError("duplicate product_id")
    for row in production_rows:
        if row["cnc_asset_id"] not in cnc_ids:
            raise AssertionError("production row references non-CNC asset")
        if datetime.fromisoformat(row["cycle_completed_at"]) <= datetime.fromisoformat(
            row["cycle_started_at"]
        ):
            raise AssertionError("production cycle has non-positive duration")

    compressor_truth = truth_rows["compressor_failure_truth.csv"]
    cnc_truth = truth_rows["cnc_failure_truth.csv"]
    all_truth = compressor_truth + cnc_truth
    truth_by_event = {row["event_id"]: row for row in all_truth}
    if len(truth_by_event) != len(all_truth):
        raise AssertionError("duplicate failure event_id")
    for row in all_truth:
        if row["asset_id"] not in asset_by_id:
            raise AssertionError("failure truth references unknown asset")
        if row["snr_profile"] not in {"easy", "medium", "hard"}:
            raise AssertionError("invalid truth difficulty profile")
        if float(row["signal_strength"]) <= 0:
            raise AssertionError("non-positive truth signal strength")

    maintenance_rows = canonical_rows["maintenance_event.csv"]
    maintenance_ids = [row["maintenance_id"] for row in maintenance_rows]
    if len(maintenance_ids) != len(set(maintenance_ids)):
        raise AssertionError("duplicate maintenance_id")
    failure_maintenance: dict[str, dict[str, str]] = {}
    for row in maintenance_rows:
        if row["asset_id"] not in asset_by_id:
            raise AssertionError("maintenance references unknown asset")
        if datetime.fromisoformat(row["completed_at"]) <= datetime.fromisoformat(row["started_at"]):
            raise AssertionError("maintenance has non-positive duration")
        if row["maintenance_type"] == "failure_recovery":
            source_event_id = row["source_event_id"]
            if not source_event_id or source_event_id in failure_maintenance:
                raise AssertionError("invalid or duplicate failure maintenance source")
            failure_maintenance[source_event_id] = row
        elif row["maintenance_type"] == "planned_tool_change":
            if row["source_event_id"]:
                raise AssertionError("planned maintenance must not reference a failure event")
            if row["asset_id"] not in cnc_ids:
                raise AssertionError("planned tool change references non-CNC asset")
        else:
            raise AssertionError("unknown maintenance type")
    if set(failure_maintenance) != set(truth_by_event):
        missing_events = sorted(set(truth_by_event) - set(failure_maintenance))
        orphan_events = sorted(set(failure_maintenance) - set(truth_by_event))
        raise AssertionError(
            f"failure/maintenance coverage mismatch: missing={missing_events[:5]}, orphan={orphan_events[:5]}"
        )
    for event_id, truth in truth_by_event.items():
        maintenance = failure_maintenance[event_id]
        if maintenance["asset_id"] != truth["asset_id"]:
            raise AssertionError("failure maintenance asset mismatch")
        expected_started_at = truth.get(
            "maintenance_started_at", truth["failure_occurred_at"]
        )
        if maintenance["started_at"] != expected_started_at:
            raise AssertionError("failure maintenance start mismatch")
        if maintenance["completed_at"] != truth["maintenance_completed_at"]:
            raise AssertionError("failure maintenance completion mismatch")

    cnc_rows = canonical_rows["cnc_sensor_observation.csv"]
    cnc_rows_by_asset: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in cnc_rows:
        cnc_rows_by_asset[row["asset_id"]].append(row)

    observation_end = datetime.fromisoformat(str(manifest["end_at"]))
    tool_replacement_starts = Counter(
        (row["asset_id"], row["started_at"])
        for row in maintenance_rows
        if row["tool_replaced"] == "1"
        and datetime.fromisoformat(row["started_at"]) < observation_end
    )
    reset_transitions = Counter()
    running_reset_examples: list[dict[str, object]] = []
    reset_alignment_examples: list[dict[str, object]] = []
    running_reset_count = 0
    reset_without_matching_maintenance_count = 0

    for asset_id, rows in cnc_rows_by_asset.items():
        ordered = sorted(rows, key=lambda item: item["observed_at"])
        for previous, current in zip(ordered, ordered[1:]):
            previous_wear = float(previous["tool_wear_min"])
            current_wear = float(current["tool_wear_min"])
            decrease = previous_wear - current_wear
            if (
                previous["operating_state"] == "running"
                and current["operating_state"] == "running"
                and decrease > TOOL_WEAR_DECREASE_TOLERANCE_MIN
            ):
                running_reset_count += 1
                if len(running_reset_examples) < 10:
                    running_reset_examples.append(
                        {
                            "asset_id": asset_id,
                            "previous_observed_at": previous["observed_at"],
                            "observed_at": current["observed_at"],
                            "previous_tool_wear_min": previous_wear,
                            "tool_wear_min": current_wear,
                            "decrease_minutes": round(decrease, 6),
                        }
                    )

            reset_like_transition = (
                decrease > TOOL_WEAR_DECREASE_TOLERANCE_MIN
                and current_wear <= TOOL_WEAR_RESET_MAX_MIN
            )
            if not reset_like_transition:
                continue
            key = (asset_id, current["observed_at"])
            reset_transitions[key] += 1
            if (
                current["operating_state"] != "maintenance"
                or tool_replacement_starts[key] <= 0
            ):
                reset_without_matching_maintenance_count += 1
                if len(reset_alignment_examples) < 10:
                    reset_alignment_examples.append(
                        {
                            "asset_id": asset_id,
                            "observed_at": current["observed_at"],
                            "previous_operating_state": previous["operating_state"],
                            "operating_state": current["operating_state"],
                            "previous_tool_wear_min": previous_wear,
                            "tool_wear_min": current_wear,
                            "matching_tool_replacement_events": tool_replacement_starts[key],
                        }
                    )

    replacement_without_reset_count = sum(
        max(0, count - reset_transitions[key])
        for key, count in tool_replacement_starts.items()
    )
    tool_wear_continuity_pass = (
        running_reset_count == 0
        and reset_without_matching_maintenance_count == 0
        and replacement_without_reset_count == 0
    )
    tool_wear_continuity = {
        "tolerance_minutes": TOOL_WEAR_DECREASE_TOLERANCE_MIN,
        "reset_value_max_minutes": TOOL_WEAR_RESET_MAX_MIN,
        "running_reset_count": running_reset_count,
        "maximum_allowed": 0,
        "tool_replacement_event_count": sum(tool_replacement_starts.values()),
        "aligned_reset_transition_count": sum(
            min(count, reset_transitions[key])
            for key, count in tool_replacement_starts.items()
        ),
        "reset_without_matching_maintenance_count": (
            reset_without_matching_maintenance_count
        ),
        "replacement_without_reset_count": replacement_without_reset_count,
        "running_reset_examples": running_reset_examples,
        "reset_alignment_examples": reset_alignment_examples,
        "pass": tool_wear_continuity_pass,
    }
    if not tool_wear_continuity_pass:
        raise AssertionError(
            "tool wear continuity mismatch: "
            f"running_resets={running_reset_count}, "
            "resets_without_matching_maintenance="
            f"{reset_without_matching_maintenance_count}, "
            f"replacement_without_reset={replacement_without_reset_count}"
        )

    numeric_columns = [
        "air_temperature_k",
        "process_temperature_k",
        "rotational_speed_rpm",
        "torque_nm",
    ]
    numeric_values = {
        column: [float(row[column]) for row in cnc_rows]
        for column in numeric_columns
    }
    air_process_corr = pearson(
        numeric_values["air_temperature_k"],
        numeric_values["process_temperature_k"],
    )
    rpm_torque_corr = pearson(
        numeric_values["rotational_speed_rpm"],
        numeric_values["torque_nm"],
    )
    process_below_air_count = sum(
        float(row["process_temperature_k"]) < float(row["air_temperature_k"])
        for row in cnc_rows
    )
    process_below_air_fraction = process_below_air_count / max(1, len(cnc_rows))
    sensor_distribution: dict[str, dict[str, object]] = {}
    for column, target in AI4I_DISTRIBUTION_TARGETS.items():
        observed_std = statistics.pstdev(numeric_values[column])
        passed = float(target["min_std"]) <= observed_std <= float(target["max_std"])
        sensor_distribution[column] = {
            "mean": round(statistics.fmean(numeric_values[column]), 6),
            "std": round(observed_std, 6),
            "target_std": target["target_std"],
            "allowed_min": target["min_std"],
            "allowed_max": target["max_std"],
            "pass": passed,
        }
        if not passed:
            raise AssertionError(
                f"AI4I sensor dispersion outside tolerance: {column}={observed_std:.6f}"
            )
    if air_process_corr < float(AI4I_RELATION_THRESHOLDS["air_process_min_correlation"]):
        raise AssertionError(f"AI4I air/process correlation too weak: {air_process_corr:.6f}")
    if rpm_torque_corr > float(AI4I_RELATION_THRESHOLDS["rpm_torque_max_correlation"]):
        raise AssertionError(f"AI4I rpm/torque inverse correlation too weak: {rpm_torque_corr:.6f}")
    if process_below_air_fraction > float(
        AI4I_RELATION_THRESHOLDS["process_below_air_max_fraction"]
    ):
        raise AssertionError("process temperature falls below air temperature")

    cnc_observation_by_key = {
        (row["asset_id"], row["observed_at"]): row for row in cnc_rows
    }
    mode_counts: Counter[str] = Counter()
    mode_passes: Counter[str] = Counter()
    mode_false_positive_events: Counter[str] = Counter()
    event_condition_details: list[dict[str, object]] = []
    known_modes = ["PWF", "HDF", "OSF", "TWF", "RNF"]
    for truth in cnc_truth:
        key = (truth["asset_id"], truth["failure_occurred_at"])
        observation = cnc_observation_by_key.get(key)
        if observation is None:
            raise AssertionError(f"missing CNC observation at failure timestamp: {key}")
        component = truth["component"]
        mode_counts[component] += 1
        condition_pass = failure_condition(component, observation)
        mode_passes[component] += int(condition_pass)
        matched_conditions = [
            mode for mode in known_modes if failure_condition(mode, observation)
        ]
        for matched_mode in matched_conditions:
            if matched_mode != component and matched_mode != "RNF":
                mode_false_positive_events[matched_mode] += 1
        event_condition_details.append(
            {
                "event_id": truth["event_id"],
                "asset_id": truth["asset_id"],
                "component": component,
                "condition_variant": truth.get("condition_variant", ""),
                "condition_pass": condition_pass,
                "matched_conditions": matched_conditions,
                "power_w": round(
                    power_w(
                        float(observation["torque_nm"]),
                        float(observation["rotational_speed_rpm"]),
                    ),
                    6,
                ),
                "temperature_gap_k": round(
                    float(observation["process_temperature_k"])
                    - float(observation["air_temperature_k"]),
                    6,
                ),
                "tool_wear_min": float(observation["tool_wear_min"]),
                "torque_nm": float(observation["torque_nm"]),
                "rotational_speed_rpm": float(observation["rotational_speed_rpm"]),
                "product_type": observation["product_type"],
            }
        )
    failure_mode_conditions: dict[str, dict[str, object]] = {}
    for mode in known_modes:
        count = mode_counts[mode]
        passed = mode_passes[mode]
        pass_rate = passed / count if count else None
        failure_mode_conditions[mode] = {
            "events": count,
            "condition_passes": passed,
            "condition_pass_rate": round(pass_rate, 6) if pass_rate is not None else None,
            "other_failure_events_matching_condition": mode_false_positive_events[mode],
            "pass": count == 0 or passed == count,
        }
        if count and passed != count:
            raise AssertionError(
                f"AI4I failure condition mismatch for {mode}: {passed}/{count}"
            )

    ai4i_physics = {
        "air_process_correlation": {
            "value": round(air_process_corr, 6),
            "minimum": AI4I_RELATION_THRESHOLDS["air_process_min_correlation"],
            "pass": True,
        },
        "rpm_torque_correlation": {
            "value": round(rpm_torque_corr, 6),
            "maximum": AI4I_RELATION_THRESHOLDS["rpm_torque_max_correlation"],
            "pass": True,
        },
        "process_temperature_ordering": {
            "process_below_air_rows": process_below_air_count,
            "fraction": round(process_below_air_fraction, 8),
            "maximum_fraction": AI4I_RELATION_THRESHOLDS[
                "process_below_air_max_fraction"
            ],
            "pass": True,
        },
        "sensor_distribution": sensor_distribution,
        "failure_mode_conditions": failure_mode_conditions,
        "event_condition_details": event_condition_details,
        "tool_wear_continuity": tool_wear_continuity,
        "pass": True,
    }

    public_fields, public_cases = read_csv(experiment_root / "public_case_index.csv")
    if set(public_fields) & HIDDEN_FIELD_NAMES:
        raise AssertionError("hidden fields leaked into public case index")
    hidden_fields, hidden_rows = read_csv(experiment_root / "hidden_truth" / "scenario_truth.csv")
    if not HIDDEN_FIELD_NAMES.issubset(set(hidden_fields)):
        raise AssertionError("hidden truth is incomplete")
    public_case_ids = [row["case_id"] for row in public_cases]
    hidden_case_ids = [row["case_id"] for row in hidden_rows]
    if len(public_case_ids) != len(set(public_case_ids)):
        raise AssertionError("duplicate public experiment case_id")
    if len(hidden_case_ids) != len(set(hidden_case_ids)):
        raise AssertionError("duplicate hidden experiment case_id")
    if set(public_case_ids) != set(hidden_case_ids):
        raise AssertionError("public and hidden experiment case sets differ")
    hidden_by_case = {row["case_id"]: row for row in hidden_rows}

    if experiment_manifest.get("public_case_index_sha256") != sha256(
        experiment_root / "public_case_index.csv"
    ):
        raise AssertionError("public experiment index checksum mismatch")
    if experiment_manifest.get("hidden_truth_sha256") != sha256(
        experiment_root / "hidden_truth" / "scenario_truth.csv"
    ):
        raise AssertionError("hidden experiment truth checksum mismatch")
    if set(experiment_manifest.get("case_files", {})) != set(public_case_ids):
        raise AssertionError("experiment manifest case set mismatch")

    canonical_compressor_schema = canonical_fields["compressor_sensor_observation.csv"]
    canonical_cnc_schema = canonical_fields["cnc_sensor_observation.csv"]
    observable_pressure_changes: list[float] = []
    observable_torque_changes: list[float] = []
    negative_local_torque_deltas: list[float] = []
    canonical_compressor_by_key = {
        (row["asset_id"], row["observed_at"]): row
        for row in canonical_rows["compressor_sensor_observation.csv"]
    }
    canonical_cnc_by_key = {
        (row["asset_id"], row["observed_at"]): row
        for row in canonical_rows["cnc_sensor_observation.csv"]
    }

    for case in public_cases:
        case_id = case["case_id"]
        case_dir = experiment_root / "public_cases" / case_id
        case_payload = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        if set(case_payload) & HIDDEN_FIELD_NAMES:
            raise AssertionError(f"hidden truth leaked into {case_id}/case.json")
        if case_payload.get("data_semantics") != "synthetic_agent_evaluation_observations":
            raise AssertionError(f"public case semantics missing: {case_id}")
        if case_payload.get("canonical_source") is not False:
            raise AssertionError(f"public case incorrectly labeled canonical: {case_id}")
        if case_payload.get("hidden_truth_available_to_agent") is not False:
            raise AssertionError(f"public case exposes evaluator truth contract: {case_id}")

        expected_case_hashes = experiment_manifest["case_files"][case_id]
        for filename, expected_hash in expected_case_hashes.items():
            case_file = case_dir / filename
            if not case_file.exists() or sha256(case_file) != expected_hash:
                raise AssertionError(f"experiment case checksum mismatch: {case_id}/{filename}")

        compressor_fields, compressor_rows = read_csv(
            case_dir / "compressor_sensor_observation.csv"
        )
        cnc_fields, cnc_rows = read_csv(case_dir / "cnc_sensor_observation.csv")
        if compressor_fields != canonical_compressor_schema:
            raise AssertionError(f"compressor schema drift in {case_id}")
        if cnc_fields != canonical_cnc_schema:
            raise AssertionError(f"CNC schema drift in {case_id}")
        if set(compressor_fields + cnc_fields) & BANNED_CANONICAL_FIELDS:
            raise AssertionError(f"effect/truth field leaked into public observations: {case_id}")
        expected_experiment_version = experiment_manifest.get("experiment_version")
        if any(
            row.get("generator_version") != expected_experiment_version
            for row in compressor_rows + cnc_rows
        ):
            raise AssertionError(f"experiment observation provenance mismatch: {case_id}")

        hidden = hidden_by_case[case_id]
        case_type = hidden.get("case_type", "positive_upstream_relation")
        effect_start = datetime.fromisoformat(hidden["effect_started_at"])
        effect_end = datetime.fromisoformat(hidden["effect_ended_at"])
        upstream = hidden["injected_upstream_asset_id"]
        target = hidden["affected_downstream_asset_id"]

        if case_type == "negative_local_only":
            if upstream or hidden.get("relation_type") != "NO_UPSTREAM_RELATION":
                raise AssertionError(f"negative case hidden contract invalid: {case_id}")
            if hidden.get("expected_claim_status") != "unlikely":
                raise AssertionError(f"negative case status contract invalid: {case_id}")
            for row in compressor_rows:
                canonical = canonical_compressor_by_key.get(
                    (row["asset_id"], row["observed_at"])
                )
                if canonical is None:
                    raise AssertionError(f"negative case compressor source missing: {case_id}")
                for field in compressor_fields:
                    if field == "generator_version":
                        continue
                    if row[field] != canonical[field]:
                        raise AssertionError(
                            f"upstream compressor mutated in negative case: {case_id}/{field}"
                        )
            during_local_delta: list[float] = []
            for row in cnc_rows:
                if row["asset_id"] != target:
                    continue
                timestamp = datetime.fromisoformat(row["observed_at"])
                if not (effect_start <= timestamp <= effect_end):
                    continue
                canonical = canonical_cnc_by_key.get((row["asset_id"], row["observed_at"]))
                if canonical is None:
                    raise AssertionError(f"negative case CNC source missing: {case_id}")
                during_local_delta.append(
                    float(row["torque_nm"]) - float(canonical["torque_nm"])
                )
            if not during_local_delta or max(during_local_delta) <= 0:
                raise AssertionError(f"negative local anomaly is not observable: {case_id}")
            negative_local_torque_deltas.append(mean(during_local_delta))
            continue
        if case_type != "positive_upstream_relation":
            raise AssertionError(f"unknown experiment case type: {case_type}")

        pre_pressure: list[float] = []
        during_pressure: list[float] = []
        pre_control_pressure: list[float] = []
        during_control_pressure: list[float] = []
        for row in compressor_rows:
            timestamp = datetime.fromisoformat(row["observed_at"])
            if effect_start - (effect_end - effect_start) <= timestamp < effect_start:
                destination = (
                    pre_pressure if row["asset_id"] == upstream else pre_control_pressure
                )
                destination.append(float(row["pressure_raw"]))
            elif effect_start <= timestamp <= effect_end:
                destination = (
                    during_pressure
                    if row["asset_id"] == upstream
                    else during_control_pressure
                )
                destination.append(float(row["pressure_raw"]))

        pre_torque: list[float] = []
        during_torque: list[float] = []
        pre_control_torque: list[float] = []
        during_control_torque: list[float] = []
        for row in cnc_rows:
            timestamp = datetime.fromisoformat(row["observed_at"])
            if effect_start - (effect_end - effect_start) <= timestamp < effect_start:
                destination = pre_torque if row["asset_id"] == target else pre_control_torque
                destination.append(float(row["torque_nm"]))
            elif effect_start <= timestamp <= effect_end:
                destination = (
                    during_torque if row["asset_id"] == target else during_control_torque
                )
                destination.append(float(row["torque_nm"]))

        required_windows = [
            pre_pressure,
            during_pressure,
            pre_control_pressure,
            during_control_pressure,
            pre_torque,
            during_torque,
            pre_control_torque,
            during_control_torque,
        ]
        if any(not values for values in required_windows):
            raise AssertionError(f"experiment window incomplete: {case_id}")
        observable_pressure_changes.append(
            (mean(during_pressure) - mean(pre_pressure))
            - (mean(during_control_pressure) - mean(pre_control_pressure))
        )
        observable_torque_changes.append(
            (mean(during_torque) - mean(pre_torque))
            - (mean(during_control_torque) - mean(pre_control_torque))
        )

    if experiment_manifest["canonical_dataset_manifest_sha256"] != sha256(
        dataset_dir / "dataset_manifest.json"
    ):
        raise AssertionError("experiment references a different canonical manifest")
    if experiment_manifest.get("canonical_dataset_mutated") is not False:
        raise AssertionError("experiment manifest does not guarantee canonical immutability")
    positive_case_count = sum(
        row.get("case_type") == "positive_upstream_relation" for row in hidden_rows
    )
    negative_case_count = sum(
        row.get("case_type") == "negative_local_only" for row in hidden_rows
    )
    if experiment_manifest.get("positive_upstream_case_count") != positive_case_count:
        raise AssertionError("positive experiment count mismatch")
    if experiment_manifest.get("negative_control_case_count") != negative_case_count:
        raise AssertionError("negative experiment count mismatch")
    if negative_case_count < 4:
        raise AssertionError("at least four negative local-only cases are required")
    pressure_direction_count = sum(value < 0 for value in observable_pressure_changes)
    torque_direction_count = sum(value > 0 for value in observable_torque_changes)
    if pressure_direction_count != len(observable_pressure_changes):
        raise AssertionError("one or more upstream experiment signals are not observable")
    if torque_direction_count / max(1, len(observable_torque_changes)) < 0.75:
        raise AssertionError("downstream experiment signal is not observable in enough cases")

    model_contract_path = root / "canonical" / "model_outputs" / "model_contract.json"
    model_contract_status = "not_generated"
    model_metrics: dict[str, object] = {}
    if model_contract_path.exists():
        contract = json.loads(model_contract_path.read_text(encoding="utf-8"))
        if contract.get("asset_relation_used_as_feature") is not False:
            raise AssertionError("asset relations used as canonical model features")
        if contract.get("upstream_feature_used") is not False:
            raise AssertionError("upstream feature used by canonical model")
        if contract.get("optional_experiment_used_for_training") is not False:
            raise AssertionError("optional experiment used for canonical training")
        if contract.get("dataset_manifest_sha256") != sha256(dataset_dir / "dataset_manifest.json"):
            raise AssertionError("model outputs are stale for the canonical dataset")
        if contract.get("canonical_input_sha256") != manifest["canonical_outputs"]:
            raise AssertionError("model canonical input contract mismatch")
        if contract.get("evaluation_truth_input_sha256") != manifest["evaluation_truth_outputs"]:
            raise AssertionError("model truth input contract mismatch")
        if contract.get("right_censoring_policy") != "exclude final prediction horizon":
            raise AssertionError("model right-censoring policy missing")
        if contract.get("maintenance_rows_excluded") is not True:
            raise AssertionError("model includes maintenance rows")

        model_output_dir = root / "canonical" / "model_outputs"
        output_paths = {
            "prediction_snapshot.jsonl": model_output_dir / "prediction_snapshot.jsonl",
            "prediction_factor.jsonl": model_output_dir / "prediction_factor.jsonl",
            "prediction_timeline.jsonl": model_output_dir / "prediction_timeline.jsonl",
            "result_artifact.jsonl": model_output_dir / "result_artifact.jsonl",
            "model_metrics.json": model_output_dir / "model_metrics.json",
        }
        for name, path in output_paths.items():
            expected_hash = contract.get("output_sha256", {}).get(name)
            if not path.exists() or expected_hash != sha256(path):
                raise AssertionError(f"model output checksum mismatch: {name}")

        snapshots = read_jsonl(output_paths["prediction_snapshot.jsonl"])
        factors = read_jsonl(output_paths["prediction_factor.jsonl"])
        timeline = read_jsonl(output_paths["prediction_timeline.jsonl"])
        result_artifacts = read_jsonl(output_paths["result_artifact.jsonl"])
        prediction_ids = [str(row.get("prediction_id", "")) for row in snapshots]
        if len(snapshots) != len(assets) or len(prediction_ids) != len(set(prediction_ids)):
            raise AssertionError("prediction snapshot coverage is invalid")
        if {str(row.get("asset_id")) for row in snapshots} != set(asset_ids):
            raise AssertionError("prediction snapshots do not cover all assets")
        if len(factors) != len(snapshots) * 3:
            raise AssertionError("prediction factor count is invalid")
        factor_counts = Counter(str(row.get("prediction_id", "")) for row in factors)
        if set(factor_counts) != set(prediction_ids) or any(count != 3 for count in factor_counts.values()):
            raise AssertionError("prediction factors are not exactly Top-3 per snapshot")
        if any(row.get("source_type") != "derived_model_output" for row in factors):
            raise AssertionError("prediction factor source type is invalid")
        timeline_contract = contract.get("replay_timeline", {})
        if timeline_contract.get("uses_canonical_features_only") is not True:
            raise AssertionError("replay timeline feature contract is invalid")
        if timeline_contract.get("in_sample_for_site") is not False:
            raise AssertionError("replay timeline must use site-holdout predictions")
        if int(timeline_contract.get("row_count", -1)) != len(timeline):
            raise AssertionError("replay timeline row count mismatch")
        timeline_ids = [str(row.get("prediction_id", "")) for row in timeline]
        if not timeline or len(timeline_ids) != len(set(timeline_ids)):
            raise AssertionError("replay timeline prediction IDs are invalid")
        if any(row.get("source_type") != "derived_replay_prediction" for row in timeline):
            raise AssertionError("replay timeline source type is invalid")
        if {str(row.get("asset_id")) for row in timeline} != set(asset_ids):
            raise AssertionError("replay timeline does not cover all assets")
        result_contract = contract.get("result_artifact", {})
        if result_contract.get("schema_version") != "result-artifact-v1.0":
            raise AssertionError("result artifact schema contract is invalid")
        if int(result_contract.get("row_count", -1)) != len(result_artifacts):
            raise AssertionError("result artifact row count mismatch")
        if len(result_artifacts) != len(assets):
            raise AssertionError("result artifacts must cover all assets")
        required_result_fields = {
            "artifact_id",
            "asset_id",
            "failure_probability",
            "predicted_failure_type",
            "status_grade",
            "top_factors",
            "recommended_action",
            "provenance",
        }
        for artifact in result_artifacts:
            if not required_result_fields.issubset(artifact):
                raise AssertionError("result artifact required fields missing")
            if artifact.get("schema_version") != "result-artifact-v1.0":
                raise AssertionError("result artifact schema version mismatch")
            if len(artifact.get("top_factors", [])) != 3:
                raise AssertionError("result artifact must contain Top-3 factors")
            provenance = artifact.get("provenance", {})
            if provenance.get("source_type") != "derived_result_artifact":
                raise AssertionError("result artifact provenance invalid")
            if provenance.get("canonical_source_mutated") is not False:
                raise AssertionError("result artifact claims canonical mutation")
        sample_artifact_path = root / "result_artifact_sample.json"
        if not sample_artifact_path.exists():
            raise AssertionError("result artifact sample is missing")
        sample_artifact = json.loads(sample_artifact_path.read_text(encoding="utf-8"))
        if sample_artifact not in result_artifacts:
            raise AssertionError("result artifact sample does not match current model output")
        model_contract_status = "pass"
        metrics_path = root / "canonical" / "model_outputs" / "model_metrics.json"
        model_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    summary = {
        "valid": True,
        "canonical_source_separation": "pass",
        "canonical_checksum_integrity": "pass",
        "evaluation_truth_checksum_integrity": "pass",
        "truth_separation": "pass",
        "topology_integrity": "pass",
        "observation_key_integrity": "pass",
        "failure_maintenance_coverage": "pass",
        "tool_wear_continuity": tool_wear_continuity,
        "experiment_isolation": "pass",
        "experiment_checksum_integrity": "pass",
        "public_experiment_schema_matches_canonical": "pass",
        "hidden_truth_not_public": "pass",
        "negative_control_benchmark": "pass",
        "agent_positive_negative_evaluator": "pass",
        "model_contract": model_contract_status,
        "model_dataset_binding": model_contract_status,
        "row_counts": {
            "assets": len(assets),
            "relations": len(relations),
            "compressor_observations": len(
                canonical_rows["compressor_sensor_observation.csv"]
            ),
            "cnc_observations": len(canonical_rows["cnc_sensor_observation.csv"]),
            "production_cycles": len(canonical_rows["cnc_production_cycle.csv"]),
            "maintenance_events": len(canonical_rows["maintenance_event.csv"]),
            "failure_recovery_events": len(failure_maintenance),
            "compressor_failure_truth": len(compressor_truth),
            "cnc_failure_truth": len(cnc_truth),
            "public_agent_cases": len(public_cases),
            "positive_upstream_cases": positive_case_count,
            "negative_local_only_cases": negative_case_count,
            "prediction_timeline_rows": len(timeline) if model_contract_status == "pass" else 0,
            "result_artifact_rows": (
                len(result_artifacts) if model_contract_status == "pass" else 0
            ),
        },
        "experiment_observability": {
            "aggregate_upstream_pressure_difference_in_differences": round(
                mean(observable_pressure_changes), 6
            ),
            "aggregate_target_torque_difference_in_differences": round(
                mean(observable_torque_changes), 6
            ),
            "pressure_direction_expected": "negative",
            "torque_direction_expected": "positive",
            "pressure_direction_pass": mean(observable_pressure_changes) < 0,
            "torque_direction_pass": mean(observable_torque_changes) > 0,
            "pressure_direction_case_pass_rate": round(
                pressure_direction_count / max(1, len(observable_pressure_changes)), 6
            ),
            "torque_direction_case_pass_rate": round(
                torque_direction_count / max(1, len(observable_torque_changes)), 6
            ),
            "causal_claim_allowed": "no",
            "negative_local_torque_delta_mean": round(
                mean(negative_local_torque_deltas), 6
            ),
        },
        "ai4i_physics": ai4i_physics,
        "agent_example_evaluation": {
            "mean_score": agent_example_evaluation.get("mean_score"),
            "positive_upstream_accuracy": agent_example_evaluation.get(
                "positive_upstream_accuracy"
            ),
            "negative_rejection_accuracy": agent_example_evaluation.get(
                "negative_rejection_accuracy"
            ),
            "false_upstream_claim_rate": agent_example_evaluation.get(
                "false_upstream_claim_rate"
            ),
            "maintenance_evidence_claims": agent_example_evaluation.get(
                "maintenance_evidence_claims"
            ),
            "maintenance_evidence_accuracy": agent_example_evaluation.get(
                "maintenance_evidence_accuracy"
            ),
        },
        "model_metrics": model_metrics,
    }
    output_path = validation_dir / "package_validation.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate canonical package and agent experiments")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    print(json.dumps(validate(Path(args.root)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

