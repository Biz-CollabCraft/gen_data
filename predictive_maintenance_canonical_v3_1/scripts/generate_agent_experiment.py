"""Create optional relation-reasoning cases without adding effect columns.

Canonical source files are never modified. Each public case contains ordinary
compressor/CNC observation schemas plus topology and an investigation prompt.
Injected cause/effect parameters exist only under hidden_truth/ for scoring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


EXPERIMENT_VERSION = "relation-reasoning-agent-eval-v3.1"
PRESSURE_DROP_FRACTION = 0.16
VIBRATION_INCREASE_FRACTION = 0.05
TORQUE_DELTA_NM = 6.4
PROCESS_TEMPERATURE_DELTA_K = 0.45
LOCAL_TORQUE_DELTA_NM = 6.0
LOCAL_PROCESS_TEMPERATURE_DELTA_K = 0.90


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def average(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return sum(values) / len(values)


def envelope(observed_at: datetime, started_at: datetime, ended_at: datetime) -> float:
    if observed_at < started_at or observed_at > ended_at:
        return 0.0
    progress = (observed_at - started_at).total_seconds() / max(
        (ended_at - started_at).total_seconds(), 1.0
    )
    return math.sin(math.pi * min(1.0, max(0.0, progress)))


def generate(
    root: Path,
    seed: int,
    interventions: int,
    duration_hours: int,
    negative_cases: int = 4,
) -> dict[str, object]:
    if interventions <= 0:
        raise ValueError("interventions must be positive")
    if duration_hours <= 0:
        raise ValueError("duration_hours must be positive")
    if negative_cases < 0:
        raise ValueError("negative_cases must be non-negative")
    dataset_dir = root / "canonical" / "dataset"
    experiment_root = root / "experiments" / "connected_air_supply"
    cases_root = experiment_root / "public_cases"
    hidden_root = experiment_root / "hidden_truth"
    required = [
        dataset_dir / "asset_master.csv",
        dataset_dir / "asset_relation.csv",
        dataset_dir / "compressor_sensor_observation.csv",
        dataset_dir / "cnc_sensor_observation.csv",
        dataset_dir / "dataset_manifest.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"canonical dataset missing: {missing}")

    if experiment_root.exists():
        shutil.rmtree(experiment_root)
    cases_root.mkdir(parents=True, exist_ok=True)
    hidden_root.mkdir(parents=True, exist_ok=True)

    assets = read_rows(dataset_dir / "asset_master.csv")
    relations = [
        row
        for row in read_rows(dataset_dir / "asset_relation.csv")
        if row["relation_type"] == "SUPPLIES_AIR_TO"
    ]
    compressor_rows = read_rows(dataset_dir / "compressor_sensor_observation.csv")
    cnc_rows = read_rows(dataset_dir / "cnc_sensor_observation.csv")
    asset_by_id = {row["asset_id"]: row for row in assets}
    downstream: dict[str, list[str]] = defaultdict(list)
    supplier_by_cnc: dict[str, str] = {}
    for relation in relations:
        downstream[relation["from_asset_id"]].append(relation["to_asset_id"])
        supplier_by_cnc[relation["to_asset_id"]] = relation["from_asset_id"]

    timestamps = sorted({datetime.fromisoformat(row["observed_at"]) for row in compressor_rows})
    if not timestamps:
        raise ValueError("empty canonical observations")
    dataset_start, dataset_end = timestamps[0], timestamps[-1]
    total_hours = int((dataset_end - dataset_start).total_seconds() // 3600)
    if total_hours < duration_hours + 96:
        raise ValueError("dataset too short for public pre/during/post windows")

    compressors = [row for row in assets if row["asset_type"] == "compressor"]
    rng = random.Random(seed)
    selected = rng.sample(compressors, k=min(interventions, len(compressors)))

    compressor_by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
    cnc_by_site: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in compressor_rows:
        compressor_by_site[row["site_id"]].append(row)
    for row in cnc_rows:
        cnc_by_site[row["site_id"]].append(row)

    public_cases: list[dict[str, object]] = []
    hidden_cases: list[dict[str, object]] = []
    case_files: dict[str, dict[str, str]] = {}
    severity_sequence = [0.55, 0.75, 0.90, 0.65]
    case_counter = 0

    for intervention_index, compressor in enumerate(selected, start=1):
        spacing = total_hours / (len(selected) + 1)
        center_hour = int(spacing * intervention_index)
        started_at = dataset_start + timedelta(hours=max(36, center_hour))
        ended_at = started_at + timedelta(hours=duration_hours)
        if ended_at + timedelta(hours=24) > dataset_end:
            ended_at = dataset_end - timedelta(hours=24)
            started_at = ended_at - timedelta(hours=duration_hours)
        public_start = started_at - timedelta(hours=24)
        public_end = ended_at + timedelta(hours=24)
        severity = severity_sequence[(intervention_index - 1) % len(severity_sequence)]

        for target_index, target_id in enumerate(sorted(downstream[compressor["asset_id"]]), start=1):
            case_counter += 1
            case_id = f"CASE-RR-{case_counter:03d}"
            case_dir = cases_root / case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            target = asset_by_id[target_id]
            site_id = target["site_id"]

            case_assets = [row for row in assets if row["site_id"] == site_id]
            case_asset_ids = {row["asset_id"] for row in case_assets}
            case_relations = [
                row
                for row in relations
                if row["from_asset_id"] in case_asset_ids and row["to_asset_id"] in case_asset_ids
            ]

            public_compressor_rows: list[dict[str, object]] = []
            for source in compressor_by_site[site_id]:
                observed_at = datetime.fromisoformat(source["observed_at"])
                if not (public_start <= observed_at <= public_end):
                    continue
                row: dict[str, object] = dict(source)
                row["generator_version"] = EXPERIMENT_VERSION
                if source["asset_id"] == compressor["asset_id"]:
                    level = severity * envelope(observed_at, started_at, ended_at)
                    row["pressure_raw"] = round(
                        float(source["pressure_raw"])
                        * (1.0 - PRESSURE_DROP_FRACTION * level),
                        4,
                    )
                    row["vibration_raw"] = round(
                        float(source["vibration_raw"])
                        * (1.0 + VIBRATION_INCREASE_FRACTION * level),
                        4,
                    )
                    # Preserve the canonical asset-specific normalization. The
                    # public source exposes only the prior z-score, so update it
                    # by the injected vibration delta rather than recomputing it
                    # against a fleet-wide constant baseline.
                    vibration_delta = float(row["vibration_raw"]) - float(
                        source["vibration_raw"]
                    )
                    z_value = float(source["relative_vibration_z"]) + vibration_delta / 5.4
                    row["relative_vibration_z"] = round(z_value, 4)
                    row["relative_vibration_zone"] = (
                        "A" if abs(z_value) < 1 else "B" if abs(z_value) < 2 else "C" if abs(z_value) < 3 else "D"
                    )
                public_compressor_rows.append(row)

            target_pre: list[float] = []
            target_during: list[float] = []
            control_pre: list[float] = []
            control_during: list[float] = []
            during_envelope: list[float] = []
            comparison_duration = ended_at - started_at
            for source in cnc_by_site[site_id]:
                observed_at = datetime.fromisoformat(source["observed_at"])
                value = float(source["torque_nm"])
                if started_at - comparison_duration <= observed_at < started_at:
                    (target_pre if source["asset_id"] == target_id else control_pre).append(
                        value
                    )
                elif started_at <= observed_at <= ended_at:
                    (
                        target_during
                        if source["asset_id"] == target_id
                        else control_during
                    ).append(value)
                    if source["asset_id"] == target_id:
                        during_envelope.append(envelope(observed_at, started_at, ended_at))
            baseline_did = (
                average(target_during)
                - average(target_pre)
                - (average(control_during) - average(control_pre))
            )
            mean_effect_weight = severity * average(during_envelope)
            # Calibrate only the hidden scenario amplitude, never canonical
            # data, so each benchmark case has an observable positive DID even
            # under the wider AI4I torque distribution.
            case_torque_delta_nm = max(
                TORQUE_DELTA_NM,
                (2.0 - baseline_did) / max(mean_effect_weight, 1e-6),
            )
            case_torque_delta_nm = min(case_torque_delta_nm, 30.0)

            public_cnc_rows: list[dict[str, object]] = []
            for source in cnc_by_site[site_id]:
                observed_at = datetime.fromisoformat(source["observed_at"])
                if not (public_start <= observed_at <= public_end):
                    continue
                row = dict(source)
                row["generator_version"] = EXPERIMENT_VERSION
                if source["asset_id"] == target_id:
                    level = severity * envelope(observed_at, started_at, ended_at)
                    row["torque_nm"] = round(
                        float(source["torque_nm"]) + case_torque_delta_nm * level,
                        4,
                    )
                    row["process_temperature_k"] = round(
                        float(source["process_temperature_k"])
                        + PROCESS_TEMPERATURE_DELTA_K * level,
                        4,
                    )
                    # Tool wear is cumulative. Do not add a temporary envelope
                    # that would later make wear decrease when the intervention
                    # ends. Torque and process temperature carry the transient
                    # downstream observation for this experiment.
                public_cnc_rows.append(row)

            compressor_path = case_dir / "compressor_sensor_observation.csv"
            cnc_path = case_dir / "cnc_sensor_observation.csv"
            asset_path = case_dir / "asset_master.csv"
            relation_path = case_dir / "asset_relation.csv"
            case_path = case_dir / "case.json"
            write_rows(compressor_path, list(compressor_rows[0].keys()), public_compressor_rows)
            write_rows(cnc_path, list(cnc_rows[0].keys()), public_cnc_rows)
            write_rows(asset_path, list(assets[0].keys()), case_assets)
            write_rows(relation_path, list(relations[0].keys()), case_relations)

            case_payload = {
                "case_id": case_id,
                "data_semantics": "synthetic_agent_evaluation_observations",
                "canonical_source": False,
                "hidden_truth_available_to_agent": False,
                "target_asset_id": target_id,
                "site_id": site_id,
                "investigation_window_start": iso(public_start),
                "investigation_window_end": iso(public_end),
                "question": (
                    "Review the target CNC anomaly and identify plausible upstream or local cause candidates. "
                    "Use temporal evidence and topology; do not claim causality as confirmed from observation alone."
                ),
                "available_files": [
                    "asset_master.csv",
                    "asset_relation.csv",
                    "compressor_sensor_observation.csv",
                    "cnc_sensor_observation.csv",
                ],
            }
            case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            public_cases.append(
                {
                    "case_id": case_id,
                    "target_asset_id": target_id,
                    "site_id": site_id,
                    "investigation_window_start": iso(public_start),
                    "investigation_window_end": iso(public_end),
                    "case_path": f"public_cases/{case_id}/case.json",
                }
            )
            hidden_cases.append(
                {
                    "case_id": case_id,
                    "case_type": "positive_upstream_relation",
                    "injected_upstream_asset_id": compressor["asset_id"],
                    "affected_downstream_asset_id": target_id,
                    "relation_type": "SUPPLIES_AIR_TO",
                    "expected_claim_status": "candidate",
                    "local_cause": "",
                    "effect_started_at": iso(started_at),
                    "effect_ended_at": iso(ended_at),
                    "mechanism": "synthetic_connected_air_supply_evaluation",
                    "severity": severity,
                    "pressure_drop_fraction_max": round(
                        PRESSURE_DROP_FRACTION * severity, 6
                    ),
                    "torque_delta_nm_max": round(
                        case_torque_delta_nm * severity, 6
                    ),
                    "process_temperature_delta_k_max": round(
                        PROCESS_TEMPERATURE_DELTA_K * severity, 6
                    ),
                    "tool_wear_delta_min_max": 0.0,
                    "causal_claim_allowed": "no",
                }
            )
            case_files[case_id] = {
                "case.json": sha256(case_path),
                "asset_master.csv": sha256(asset_path),
                "asset_relation.csv": sha256(relation_path),
                "compressor_sensor_observation.csv": sha256(compressor_path),
                "cnc_sensor_observation.csv": sha256(cnc_path),
            }

    # Local-only negative controls contain a real CNC anomaly while every
    # upstream compressor remains canonical. They prevent an evaluator from
    # rewarding an agent that always blames the topology-linked compressor.
    used_target_ids = {str(case["target_asset_id"]) for case in public_cases}
    negative_candidates = [
        row
        for row in assets
        if row["asset_type"] == "cnc" and row["asset_id"] not in used_target_ids
    ]
    selected_negative_targets = rng.sample(
        negative_candidates,
        k=min(negative_cases, len(negative_candidates)),
    )
    for negative_index, target in enumerate(selected_negative_targets, start=1):
        case_counter += 1
        case_id = f"CASE-RR-{case_counter:03d}"
        target_id = target["asset_id"]
        site_id = target["site_id"]
        spacing = total_hours / (len(selected_negative_targets) + 1)
        center_hour = int(spacing * negative_index)
        started_at = dataset_start + timedelta(hours=max(36, center_hour))
        ended_at = started_at + timedelta(hours=duration_hours)
        if ended_at + timedelta(hours=24) > dataset_end:
            ended_at = dataset_end - timedelta(hours=24)
            started_at = ended_at - timedelta(hours=duration_hours)
        public_start = started_at - timedelta(hours=24)
        public_end = ended_at + timedelta(hours=24)
        severity = severity_sequence[(negative_index - 1) % len(severity_sequence)]

        case_dir = cases_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        case_assets = [row for row in assets if row["site_id"] == site_id]
        case_asset_ids = {row["asset_id"] for row in case_assets}
        case_relations = [
            row
            for row in relations
            if row["from_asset_id"] in case_asset_ids and row["to_asset_id"] in case_asset_ids
        ]

        public_compressor_rows: list[dict[str, object]] = []
        for source in compressor_by_site[site_id]:
            observed_at = datetime.fromisoformat(source["observed_at"])
            if public_start <= observed_at <= public_end:
                row: dict[str, object] = dict(source)
                row["generator_version"] = EXPERIMENT_VERSION
                public_compressor_rows.append(row)

        public_cnc_rows: list[dict[str, object]] = []
        for source in cnc_by_site[site_id]:
            observed_at = datetime.fromisoformat(source["observed_at"])
            if not (public_start <= observed_at <= public_end):
                continue
            row = dict(source)
            row["generator_version"] = EXPERIMENT_VERSION
            if source["asset_id"] == target_id:
                level = severity * envelope(observed_at, started_at, ended_at)
                row["torque_nm"] = round(
                    float(source["torque_nm"]) + LOCAL_TORQUE_DELTA_NM * level,
                    4,
                )
                row["process_temperature_k"] = round(
                    float(source["process_temperature_k"])
                    + LOCAL_PROCESS_TEMPERATURE_DELTA_K * level,
                    4,
                )
            public_cnc_rows.append(row)

        compressor_path = case_dir / "compressor_sensor_observation.csv"
        cnc_path = case_dir / "cnc_sensor_observation.csv"
        asset_path = case_dir / "asset_master.csv"
        relation_path = case_dir / "asset_relation.csv"
        case_path = case_dir / "case.json"
        write_rows(compressor_path, list(compressor_rows[0].keys()), public_compressor_rows)
        write_rows(cnc_path, list(cnc_rows[0].keys()), public_cnc_rows)
        write_rows(asset_path, list(assets[0].keys()), case_assets)
        write_rows(relation_path, list(relations[0].keys()), case_relations)

        case_payload = {
            "case_id": case_id,
            "data_semantics": "synthetic_agent_evaluation_observations",
            "canonical_source": False,
            "hidden_truth_available_to_agent": False,
            "target_asset_id": target_id,
            "site_id": site_id,
            "investigation_window_start": iso(public_start),
            "investigation_window_end": iso(public_end),
            "question": (
                "Review the target CNC anomaly and determine whether an upstream relation is supported. "
                "Reject unsupported upstream claims and identify local evidence when appropriate."
            ),
            "available_files": [
                "asset_master.csv",
                "asset_relation.csv",
                "compressor_sensor_observation.csv",
                "cnc_sensor_observation.csv",
            ],
        }
        case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        public_cases.append(
            {
                "case_id": case_id,
                "target_asset_id": target_id,
                "site_id": site_id,
                "investigation_window_start": iso(public_start),
                "investigation_window_end": iso(public_end),
                "case_path": f"public_cases/{case_id}/case.json",
            }
        )
        hidden_cases.append(
            {
                "case_id": case_id,
                "case_type": "negative_local_only",
                "injected_upstream_asset_id": "",
                "affected_downstream_asset_id": target_id,
                "relation_type": "NO_UPSTREAM_RELATION",
                "expected_claim_status": "unlikely",
                "local_cause": "local_cnc_process_anomaly",
                "effect_started_at": iso(started_at),
                "effect_ended_at": iso(ended_at),
                "mechanism": "synthetic_local_only_evaluation",
                "severity": severity,
                "pressure_drop_fraction_max": 0.0,
                "torque_delta_nm_max": round(LOCAL_TORQUE_DELTA_NM * severity, 6),
                "process_temperature_delta_k_max": round(
                    LOCAL_PROCESS_TEMPERATURE_DELTA_K * severity, 6
                ),
                "tool_wear_delta_min_max": 0.0,
                "causal_claim_allowed": "no",
            }
        )
        case_files[case_id] = {
            "case.json": sha256(case_path),
            "asset_master.csv": sha256(asset_path),
            "asset_relation.csv": sha256(relation_path),
            "compressor_sensor_observation.csv": sha256(compressor_path),
            "cnc_sensor_observation.csv": sha256(cnc_path),
        }

    public_index_path = experiment_root / "public_case_index.csv"
    hidden_truth_path = hidden_root / "scenario_truth.csv"
    write_rows(
        public_index_path,
        [
            "case_id",
            "target_asset_id",
            "site_id",
            "investigation_window_start",
            "investigation_window_end",
            "case_path",
        ],
        public_cases,
    )
    write_rows(hidden_truth_path, list(hidden_cases[0].keys()), hidden_cases)

    manifest = {
        "experiment_version": EXPERIMENT_VERSION,
        "semantics": "optional synthetic agent-evaluation asset; not canonical source and not observed causal evidence",
        "benchmark_scope": "mixed positive upstream localization and negative local-only rejection",
        "positive_upstream_case_count": sum(
            row["case_type"] == "positive_upstream_relation" for row in hidden_cases
        ),
        "negative_control_case_count": sum(
            row["case_type"] == "negative_local_only" for row in hidden_cases
        ),
        "smoke_example_case_ids": [
            next(
                row["case_id"]
                for row in hidden_cases
                if row["case_type"] == "positive_upstream_relation"
            ),
            next(
                row["case_id"]
                for row in hidden_cases
                if row["case_type"] == "negative_local_only"
            ),
        ],
        "formal_scoring_note": (
            "Exclude smoke_example_case_ids from formal benchmark reporting."
        ),
        "canonical_dataset_mutated": False,
        "public_observation_schema_contains_effect_columns": False,
        "public_case_count": len(public_cases),
        "hidden_truth_is_evaluator_only": True,
        "canonical_dataset_manifest_sha256": sha256(dataset_dir / "dataset_manifest.json"),
        "public_case_index_sha256": sha256(public_index_path),
        "hidden_truth_sha256": sha256(hidden_truth_path),
        "case_files": case_files,
    }
    manifest_path = experiment_root / "experiment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate optional agent relation-reasoning cases")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interventions", type=int, default=4)
    parser.add_argument("--duration-hours", type=int, default=24)
    parser.add_argument("--negative-cases", type=int, default=4)
    args = parser.parse_args()
    result = generate(
        root=Path(args.root),
        seed=args.seed,
        interventions=args.interventions,
        duration_hours=args.duration_hours,
        negative_cases=args.negative_cases,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
