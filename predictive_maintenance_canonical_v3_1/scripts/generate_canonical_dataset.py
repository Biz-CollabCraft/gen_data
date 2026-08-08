"""Generate the canonical independent compressor/CNC source dataset.

The generator owns hidden degradation mechanics, but source observation files
never expose failure schedules, difficulty profiles, upstream features, model
outputs, scenario identifiers, or synthetic effect values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai4i_contract import (
    HDF_RPM_MAX,
    HDF_TEMPERATURE_GAP_MAX_K,
    OVERSTRAIN_THRESHOLDS,
    POWER_HIGH_W,
    POWER_LOW_W,
    TWF_WEAR_MAX,
    TWF_WEAR_MIN,
    overstrain_threshold,
    power_w,
)


GENERATOR_VERSION = "canonical-ai4i-physics-v3.1"

COMPRESSOR_BASELINE = {
    "voltage_raw": (170.8, 15.0),
    "rotation_raw": (446.6, 40.0),
    "pressure_raw": (100.9, 6.0),
    "vibration_raw": (40.4, 5.4),
}

CNC_BASELINE = {
    "air_temperature_k": 300.0,
    "process_temperature_k": 310.0,
    "rotational_speed_rpm": 1538.0,
    "torque_nm": 40.0,
}

# AI4I-style coupled generation. Fleet-level dispersion is driven primarily by
# time-varying sensor processes, while asset offsets remain small enough not to
# swamp the target marginal distributions.
CNC_NOISE_STD = {
    "air_temperature_k": 1.95,
    "process_residual_k": 0.62,
    "torque_nm": 10.6,
    "rpm_residual": 48.0,
    "power_target_w": 180.0,
}
CNC_ASSET_VARIATION = {
    "air_temperature_k": 0.35,
    "process_temperature_k": 0.18,
    "torque_nm": 0.90,
    "power_target_w": 120.0,
}
CNC_BASE_POWER_W = 6500.0
CNC_RPM_INVERSE_BLEND = 0.30

ISSUE_PROFILES = {
    "comp1": {"voltage_raw": +0.09, "rotation_raw": -0.03},
    "comp2": {"rotation_raw": -0.13, "vibration_raw": +0.05},
    "comp3": {"pressure_raw": -0.14, "vibration_raw": +0.03},
    "comp4": {"vibration_raw": +0.18, "rotation_raw": -0.04},
}

COMPRESSOR_MODES = [
    ("comp1", "electrical_anomaly", 0.25),
    ("comp2", "drive_degradation", 0.34),
    ("comp3", "pressure_control_degradation", 0.17),
    ("comp4", "bearing_degradation", 0.24),
]

CNC_MODES = [
    ("TWF", "tool_wear_failure", 46),
    ("HDF", "heat_dissipation_failure", 115),
    ("PWF", "power_failure", 95),
    ("OSF", "overstrain_failure", 98),
    ("RNF", "random_failure", 19),
]

RATE_PROFILES = {
    "balanced_demo": {
        "compressor_interval": (2200, 5000),
        "cnc_interval": (900, 2400),
        "compressor_first_offset_max": 900,
        "cnc_first_offset_max": 1200,
        "extra_issue_probability": 0.14,
    },
    "realistic_sparse": {
        "compressor_interval": (4500, 10000),
        "cnc_interval": (2500, 6000),
        "compressor_first_offset_max": 5000,
        "cnc_first_offset_max": 4000,
        "extra_issue_probability": 0.05,
    },
    "training_dense": {
        "compressor_interval": (700, 1800),
        "cnc_interval": (350, 1000),
        "compressor_first_offset_max": 720,
        "cnc_first_offset_max": 600,
        "extra_issue_probability": 0.20,
    },
}

SNR_PROFILES = {
    "easy": (0.95, 1.20),
    "medium": (0.55, 0.82),
    "hard": (0.20, 0.42),
}

PRODUCT_WEIGHTS = {"L": 0.50, "M": 0.30, "H": 0.20}
PRODUCT_CUTTING_MINUTES = {"L": (8.0, 11.0), "M": (11.0, 14.0), "H": (14.0, 17.0)}
TOOL_WEAR_EXPOSURE_FACTOR = 0.08


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def stable_seed(*parts: object) -> int:
    raw = ":".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def write_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_topology() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    assets: list[dict[str, str]] = []
    relations: list[dict[str, str]] = []
    for site_index in range(1, 5):
        site_id = f"S{site_index:02d}"
        for cell_index in range(1, 6):
            cell_id = f"{site_id}-L{cell_index:02d}"
            compressor_id = f"CMP-{cell_id}-01"
            assets.append(
                {
                    "asset_id": compressor_id,
                    "asset_type": "compressor",
                    "site_id": site_id,
                    "cell_id": cell_id,
                }
            )
            for cnc_index in range(1, 5):
                cnc_id = f"CNC-{cell_id}-{cnc_index:02d}"
                assets.append(
                    {
                        "asset_id": cnc_id,
                        "asset_type": "cnc",
                        "site_id": site_id,
                        "cell_id": cell_id,
                    }
                )
                relations.append(
                    {
                        "from_asset_id": compressor_id,
                        "relation_type": "SUPPLIES_AIR_TO",
                        "to_asset_id": cnc_id,
                    }
                )
    return assets, relations


def choose_mode(
    rng: random.Random, asset_type: str, exclude: str | None = None
) -> tuple[str, str]:
    source = COMPRESSOR_MODES if asset_type == "compressor" else CNC_MODES
    candidates = [item for item in source if item[0] != exclude]
    component, failure_mode, _weight = rng.choices(
        candidates, weights=[item[2] for item in candidates], k=1
    )[0]
    return component, failure_mode


def make_schedule_row(
    rng: random.Random,
    asset: dict[str, str],
    profile: dict[str, object],
    index: int,
    exclude: str | None = None,
) -> dict[str, object]:
    asset_type = asset["asset_type"]
    component, failure_mode = choose_mode(rng, asset_type, exclude)
    interval_key = "compressor_interval" if asset_type == "compressor" else "cnc_interval"
    first_key = (
        "compressor_first_offset_max" if asset_type == "compressor" else "cnc_first_offset_max"
    )
    interval_min, interval_max = profile[interval_key]
    recurrence = rng.randint(int(interval_min), int(interval_max))
    precursor = rng.randint(24, 48) if asset_type == "compressor" else rng.randint(12, 36)
    first_cap = min(recurrence, int(profile[first_key]))
    first_offset = rng.randint(max(24, precursor), max(max(24, precursor), first_cap))
    downtime = rng.randint(4, 12) if asset_type == "compressor" else rng.randint(2, 8)
    snr_profile = rng.choices(["easy", "medium", "hard"], weights=[0.25, 0.55, 0.20], k=1)[0]
    signal_min, signal_max = SNR_PROFILES[snr_profile]
    signal_strength = round(rng.uniform(signal_min, signal_max), 4)
    issue_hash = hashlib.sha256(
        f"{asset['asset_id']}:{component}:{index}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "issue_id": f"ISS-{issue_hash}",
        "asset_id": asset["asset_id"],
        "asset_type": asset_type,
        "component": component,
        "failure_mode": failure_mode,
        "first_failure_offset_hours": first_offset,
        "recurrence_interval_hours": recurrence,
        "pre_failure_window_hours": precursor,
        "downtime_hours": downtime,
        "snr_profile": snr_profile,
        "signal_strength": signal_strength,
    }


def build_schedule(
    assets: list[dict[str, str]], seed: int, rate_profile: str
) -> list[dict[str, object]]:
    if rate_profile not in RATE_PROFILES:
        raise ValueError(f"unknown rate profile: {rate_profile}")
    rng = random.Random(seed)
    profile = RATE_PROFILES[rate_profile]
    rows: list[dict[str, object]] = []
    for asset in assets:
        first = make_schedule_row(rng, asset, profile, 1)
        rows.append(first)
        if rng.random() < float(profile["extra_issue_probability"]):
            rows.append(make_schedule_row(rng, asset, profile, 2, str(first["component"])))
    return rows


@dataclass(frozen=True)
class Episode:
    event_id: str
    issue: dict[str, object]
    degradation_started_at: datetime
    failure_at: datetime
    maintenance_started_at: datetime
    maintenance_completed_at: datetime


@dataclass
class Runtime:
    asset: dict[str, str]
    rng: random.Random
    baseline: dict[str, float]
    noise_state: dict[str, float] = field(default_factory=dict)
    tool_wear_min: float = 0.0
    tool_change_threshold_min: float = 210.0
    product_started_at: datetime | None = None
    product_type: str = "L"
    product_ticks: int = 0
    product_counter: int = 0
    planned_maintenance_until: datetime | None = None
    tool_reset_at: datetime | None = None


def build_episodes(
    schedule: list[dict[str, object]],
    start_at: datetime,
    end_at: datetime,
    observation_interval_minutes: int,
) -> list[Episode]:
    episodes: list[Episode] = []
    for issue in schedule:
        failure_at = start_at + timedelta(hours=int(issue["first_failure_offset_hours"]))
        index = 1
        while failure_at < end_at:
            tool_replacement_failure = (
                issue["asset_type"] == "cnc"
                and issue["component"] in {"TWF", "OSF"}
            )
            maintenance_started_at = failure_at + (
                timedelta(minutes=observation_interval_minutes)
                if tool_replacement_failure
                else timedelta(0)
            )
            episodes.append(
                Episode(
                    event_id=f"EVT-{str(issue['issue_id'])[4:]}-{index:03d}",
                    issue=issue,
                    degradation_started_at=failure_at
                    - timedelta(hours=int(issue["pre_failure_window_hours"])),
                    failure_at=failure_at,
                    maintenance_started_at=maintenance_started_at,
                    maintenance_completed_at=failure_at
                    + timedelta(hours=int(issue["downtime_hours"])),
                )
            )
            failure_at += timedelta(
                hours=int(issue["recurrence_interval_hours"]) + int(issue["downtime_hours"])
            )
            index += 1
    return episodes


def make_baseline(asset: dict[str, str], seed: int) -> dict[str, float]:
    rng = random.Random(stable_seed(seed, asset["asset_id"], "baseline"))
    if asset["asset_type"] == "compressor":
        return {
            sensor: mean * rng.uniform(0.96, 1.04)
            for sensor, (mean, _std) in COMPRESSOR_BASELINE.items()
        }
    air_offset = rng.uniform(
        -CNC_ASSET_VARIATION["air_temperature_k"],
        CNC_ASSET_VARIATION["air_temperature_k"],
    )
    process_offset = 0.25 * air_offset + rng.uniform(
        -CNC_ASSET_VARIATION["process_temperature_k"],
        CNC_ASSET_VARIATION["process_temperature_k"],
    )
    return {
        "air_temperature_k": CNC_BASELINE["air_temperature_k"] + air_offset,
        "process_temperature_k": CNC_BASELINE["process_temperature_k"] + process_offset,
        "torque_nm": CNC_BASELINE["torque_nm"]
        + rng.uniform(-CNC_ASSET_VARIATION["torque_nm"], CNC_ASSET_VARIATION["torque_nm"]),
        "power_target_w": CNC_BASE_POWER_W
        + rng.uniform(
            -CNC_ASSET_VARIATION["power_target_w"],
            CNC_ASSET_VARIATION["power_target_w"],
        ),
    }


def ar_noise(runtime: Runtime, sensor: str, std: float) -> float:
    previous = runtime.noise_state.get(sensor, 0.0)
    innovation = runtime.rng.gauss(0.0, std * math.sqrt(1 - 0.72**2))
    value = 0.72 * previous + innovation
    runtime.noise_state[sensor] = value
    return value


def episode_ramp(episode: Episode, observed_at: datetime) -> float:
    if observed_at < episode.degradation_started_at or observed_at > episode.failure_at:
        return 0.0
    total = (episode.failure_at - episode.degradation_started_at).total_seconds()
    elapsed = (observed_at - episode.degradation_started_at).total_seconds()
    return clamp(elapsed / max(total, 1.0), 0.0, 1.0)


def operating_state(episodes: list[Episode], observed_at: datetime) -> tuple[int, str]:
    for episode in episodes:
        if episode.maintenance_started_at <= observed_at < episode.maintenance_completed_at:
            return 0, "maintenance"
    return 1, "running"


def sensor_effects(episodes: list[Episode], observed_at: datetime) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for episode in episodes:
        strength = episode_ramp(episode, observed_at) * float(episode.issue["signal_strength"])
        if strength <= 0:
            continue
        component = str(episode.issue["component"])
        if component not in ISSUE_PROFILES:
            continue
        for sensor, pct in ISSUE_PROFILES[component].items():
            result[sensor] += pct * strength
    return dict(result)


def active_cnc_episode(episodes: list[Episode], observed_at: datetime) -> tuple[Episode | None, float]:
    active = [
        (episode, episode_ramp(episode, observed_at))
        for episode in episodes
        if episode.issue["asset_type"] == "cnc"
        and episode.degradation_started_at <= observed_at <= episode.failure_at
    ]
    if not active:
        return None, 0.0
    episode, ramp = max(active, key=lambda item: item[1])
    return episode, ramp


def pwf_target_power(event_id: str) -> float:
    branch = stable_seed(event_id, "pwf-branch") % 2
    return 3200.0 if branch == 0 else 9600.0


def coupled_cnc_values(
    runtime: Runtime,
    episodes: list[Episode],
    observed_at: datetime,
) -> dict[str, float]:
    air = runtime.baseline["air_temperature_k"] + ar_noise(
        runtime, "air_temperature_k", CNC_NOISE_STD["air_temperature_k"]
    )
    process_residual = ar_noise(
        runtime, "process_residual_k", CNC_NOISE_STD["process_residual_k"]
    )
    process = (
        runtime.baseline["process_temperature_k"]
        + 0.68 * (air - runtime.baseline["air_temperature_k"])
        + process_residual
    )
    # Normal operation preserves a positive process/air gap. HDF is the only
    # failure mode allowed to deliberately cross below the 8.6 K threshold.
    process = max(process, air + 8.9)

    torque = runtime.baseline["torque_nm"] + ar_noise(
        runtime, "torque_nm", CNC_NOISE_STD["torque_nm"]
    )
    torque = clamp(torque, 12.0, 72.0)
    target_power = runtime.baseline["power_target_w"] + ar_noise(
        runtime, "power_target_w", CNC_NOISE_STD["power_target_w"]
    )
    ideal_rpm = target_power * 60.0 / (2.0 * math.pi * max(torque, 1.0))
    rpm = (
        CNC_BASELINE["rotational_speed_rpm"]
        + CNC_RPM_INVERSE_BLEND
        * (ideal_rpm - CNC_BASELINE["rotational_speed_rpm"])
        + ar_noise(runtime, "rpm_residual", CNC_NOISE_STD["rpm_residual"])
    )
    rpm = clamp(rpm, 900.0, 2600.0)

    episode, ramp = active_cnc_episode(episodes, observed_at)
    if episode is None:
        return {
            "air_temperature_k": air,
            "process_temperature_k": process,
            "rotational_speed_rpm": rpm,
            "torque_nm": torque,
        }

    component = str(episode.issue["component"])
    signal_strength = float(episode.issue["signal_strength"])
    physical_ramp = clamp(ramp * (0.55 + 0.45 * signal_strength), 0.0, 1.0)
    # Difficulty controls how early/clearly the precursor appears, not whether
    # the labeled failure satisfies its defining physical condition.
    if ramp >= 0.999:
        physical_ramp = 1.0

    if component == "PWF":
        target = pwf_target_power(episode.event_id)
        if target < POWER_LOW_W:
            # Keep low-power failures inside the supported RPM envelope by
            # reducing torque before solving the exact power equation.
            torque = torque + physical_ramp * (34.0 - torque)
        normal_power = power_w(torque, rpm)
        blended_power = normal_power + physical_ramp * (target - normal_power)
        rpm = blended_power * 60.0 / (2.0 * math.pi * max(torque, 1.0))
        if ramp >= 0.999:
            rpm = target * 60.0 / (2.0 * math.pi * max(torque, 1.0))
    elif component == "HDF":
        target_gap = 7.7
        normal_gap = process - air
        process = air + normal_gap + physical_ramp * (target_gap - normal_gap)
        rpm = rpm + physical_ramp * (1280.0 - rpm)
        if ramp >= 0.999:
            process = air + 7.7
            rpm = min(rpm, 1280.0)
    elif component == "OSF":
        # Tool wear is controlled separately. Torque approaches the exact
        # overstrain threshold implied by the current product type.
        target_torque = overstrain_threshold(runtime.product_type) / 225.0 + 4.0
        torque = torque + physical_ramp * (target_torque - torque)
        target_power = runtime.baseline["power_target_w"]
        ideal_rpm = target_power * 60.0 / (2.0 * math.pi * max(torque, 1.0))
        rpm = rpm + physical_ramp * (ideal_rpm - rpm)
    elif component == "TWF":
        torque = torque + physical_ramp * (46.0 - torque)
        ideal_rpm = runtime.baseline["power_target_w"] * 60.0 / (
            2.0 * math.pi * max(torque, 1.0)
        )
        rpm = rpm + physical_ramp * (ideal_rpm - rpm)
    elif component == "RNF":
        pass

    return {
        "air_temperature_k": air,
        "process_temperature_k": process,
        "rotational_speed_rpm": clamp(rpm, 700.0, 3200.0),
        "torque_nm": clamp(torque, 8.0, 90.0),
    }


def vibration_zone(z_value: float) -> str:
    absolute = abs(z_value)
    if absolute < 1:
        return "A"
    if absolute < 2:
        return "B"
    if absolute < 3:
        return "C"
    return "D"


def choose_product(runtime: Runtime) -> str:
    labels = list(PRODUCT_WEIGHTS)
    return runtime.rng.choices(labels, weights=[PRODUCT_WEIGHTS[item] for item in labels], k=1)[0]


def truth_row(episode: Episode) -> dict[str, object]:
    component = str(episode.issue["component"])
    condition_variant = ""
    if component == "PWF":
        condition_variant = (
            "low_power" if pwf_target_power(episode.event_id) < POWER_LOW_W else "high_power"
        )
    elif component in {"HDF", "OSF", "TWF", "RNF"}:
        condition_variant = component.lower()
    return {
        "event_id": episode.event_id,
        "issue_id": episode.issue["issue_id"],
        "asset_id": episode.issue["asset_id"],
        "failure_mode": episode.issue["failure_mode"],
        "component": episode.issue["component"],
        "degradation_started_at": iso(episode.degradation_started_at),
        "failure_occurred_at": iso(episode.failure_at),
        "maintenance_started_at": iso(episode.maintenance_started_at),
        "maintenance_completed_at": iso(episode.maintenance_completed_at),
        "snr_profile": episode.issue["snr_profile"],
        "signal_strength": episode.issue["signal_strength"],
        "condition_variant": condition_variant,
    }


def generate(
    root: Path,
    start_at: datetime,
    days: int,
    interval_minutes: int,
    product_cycle_minutes: int,
    seed: int,
    rate_profile: str,
) -> dict[str, object]:
    if days <= 0 or interval_minutes <= 0:
        raise ValueError("days and interval must be positive")
    if product_cycle_minutes % interval_minutes:
        raise ValueError("product cycle must be a multiple of observation interval")

    dataset_dir = root / "canonical" / "dataset"
    truth_dir = root / "canonical" / "evaluation_truth"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    assets, relations = build_topology()
    schedule = build_schedule(assets, seed, rate_profile)
    end_at = start_at + timedelta(days=days)
    episodes = build_episodes(
        schedule,
        start_at,
        end_at,
        observation_interval_minutes=interval_minutes,
    )
    episodes_by_asset: dict[str, list[Episode]] = defaultdict(list)
    for episode in episodes:
        episodes_by_asset[str(episode.issue["asset_id"])].append(episode)

    asset_path = dataset_dir / "asset_master.csv"
    relation_path = dataset_dir / "asset_relation.csv"
    schedule_path = truth_dir / "failure_schedule.csv"
    compressor_truth_path = truth_dir / "compressor_failure_truth.csv"
    cnc_truth_path = truth_dir / "cnc_failure_truth.csv"
    compressor_sensor_path = dataset_dir / "compressor_sensor_observation.csv"
    cnc_sensor_path = dataset_dir / "cnc_sensor_observation.csv"
    production_path = dataset_dir / "cnc_production_cycle.csv"
    maintenance_path = dataset_dir / "maintenance_event.csv"

    write_rows(asset_path, ["asset_id", "asset_type", "site_id", "cell_id"], assets)
    write_rows(
        relation_path,
        ["from_asset_id", "relation_type", "to_asset_id"],
        relations,
    )
    schedule_columns = list(schedule[0].keys())
    write_rows(schedule_path, schedule_columns, schedule)

    truth_columns = [
        "event_id",
        "issue_id",
        "asset_id",
        "failure_mode",
        "component",
        "degradation_started_at",
        "failure_occurred_at",
        "maintenance_started_at",
        "maintenance_completed_at",
        "snr_profile",
        "signal_strength",
        "condition_variant",
    ]
    compressor_truth = [
        truth_row(item) for item in episodes if item.issue["asset_type"] == "compressor"
    ]
    cnc_truth = [truth_row(item) for item in episodes if item.issue["asset_type"] == "cnc"]
    write_rows(compressor_truth_path, truth_columns, compressor_truth)
    write_rows(cnc_truth_path, truth_columns, cnc_truth)

    runtimes = {
        asset["asset_id"]: Runtime(
            asset=asset,
            rng=random.Random(stable_seed(seed, asset["asset_id"], "runtime")),
            baseline=make_baseline(asset, seed),
            tool_change_threshold_min=random.Random(
                stable_seed(seed, asset["asset_id"], "tool-threshold")
            ).uniform(180, 235),
        )
        for asset in assets
    }

    compressor_columns = [
        "observed_at",
        "asset_id",
        "site_id",
        "cell_id",
        "is_operating",
        "operating_state",
        "voltage_raw",
        "rotation_raw",
        "pressure_raw",
        "vibration_raw",
        "relative_vibration_z",
        "relative_vibration_zone",
        "generator_version",
    ]
    cnc_columns = [
        "observed_at",
        "asset_id",
        "site_id",
        "cell_id",
        "is_operating",
        "operating_state",
        "product_type",
        "air_temperature_k",
        "process_temperature_k",
        "rotational_speed_rpm",
        "torque_nm",
        "tool_wear_min",
        "generator_version",
    ]
    production_columns = [
        "product_id",
        "cnc_asset_id",
        "cycle_started_at",
        "cycle_completed_at",
        "product_type",
        "cutting_minutes",
        "tool_wear_increment_min",
    ]
    maintenance_columns = [
        "maintenance_id",
        "asset_id",
        "maintenance_type",
        "started_at",
        "completed_at",
        "tool_replaced",
        "source_event_id",
    ]

    tick = timedelta(minutes=interval_minutes)
    product_ticks = product_cycle_minutes // interval_minutes
    written_failures: set[str] = set()

    with (
        compressor_sensor_path.open("w", newline="", encoding="utf-8") as compressor_handle,
        cnc_sensor_path.open("w", newline="", encoding="utf-8") as cnc_handle,
        production_path.open("w", newline="", encoding="utf-8") as production_handle,
        maintenance_path.open("w", newline="", encoding="utf-8") as maintenance_handle,
    ):
        compressor_writer = csv.DictWriter(compressor_handle, fieldnames=compressor_columns)
        cnc_writer = csv.DictWriter(cnc_handle, fieldnames=cnc_columns)
        production_writer = csv.DictWriter(production_handle, fieldnames=production_columns)
        maintenance_writer = csv.DictWriter(maintenance_handle, fieldnames=maintenance_columns)
        compressor_writer.writeheader()
        cnc_writer.writeheader()
        production_writer.writeheader()
        maintenance_writer.writeheader()

        observed_at = start_at
        while observed_at < end_at:
            for asset in assets:
                runtime = runtimes[asset["asset_id"]]
                asset_episodes = episodes_by_asset[asset["asset_id"]]
                if runtime.tool_reset_at and observed_at >= runtime.tool_reset_at:
                    runtime.tool_wear_min = runtime.rng.uniform(0.0, 4.0)
                    runtime.tool_reset_at = None
                is_operating, state = operating_state(asset_episodes, observed_at)
                if runtime.planned_maintenance_until and observed_at < runtime.planned_maintenance_until:
                    is_operating, state = 0, "maintenance"
                effects = sensor_effects(asset_episodes, observed_at)

                # Failure-recovery maintenance belongs to every asset type. Keep this
                # generic block before the compressor branch so compressor failures do
                # not disappear from maintenance_event.csv.
                for episode in asset_episodes:
                    if episode.event_id in written_failures:
                        continue
                    if observed_at <= episode.failure_at < observed_at + tick:
                        tool_replaced = int(
                            asset["asset_type"] == "cnc"
                            and episode.issue["component"] in {"TWF", "OSF"}
                        )
                        maintenance_writer.writerow(
                            {
                                "maintenance_id": f"MNT-{episode.event_id}",
                                "asset_id": asset["asset_id"],
                                "maintenance_type": "failure_recovery",
                                "started_at": iso(episode.maintenance_started_at),
                                "completed_at": iso(episode.maintenance_completed_at),
                                "tool_replaced": tool_replaced,
                                "source_event_id": episode.event_id,
                            }
                        )
                        if tool_replaced:
                            runtime.tool_reset_at = episode.maintenance_started_at
                        written_failures.add(episode.event_id)

                if asset["asset_type"] == "compressor":
                    values: dict[str, float] = {}
                    for sensor, (_mean, std) in COMPRESSOR_BASELINE.items():
                        base = runtime.baseline[sensor]
                        values[sensor] = base + ar_noise(runtime, sensor, std) + base * effects.get(sensor, 0.0)
                    vibration_z = (
                        values["vibration_raw"] - runtime.baseline["vibration_raw"]
                    ) / COMPRESSOR_BASELINE["vibration_raw"][1]
                    compressor_writer.writerow(
                        {
                            "observed_at": iso(observed_at),
                            "asset_id": asset["asset_id"],
                            "site_id": asset["site_id"],
                            "cell_id": asset["cell_id"],
                            "is_operating": is_operating,
                            "operating_state": state,
                            "voltage_raw": round(values["voltage_raw"], 4),
                            "rotation_raw": round(values["rotation_raw"], 4),
                            "pressure_raw": round(values["pressure_raw"], 4),
                            "vibration_raw": round(values["vibration_raw"], 4),
                            "relative_vibration_z": round(vibration_z, 4),
                            "relative_vibration_zone": vibration_zone(vibration_z),
                            "generator_version": GENERATOR_VERSION,
                        }
                    )
                    continue

                if runtime.product_started_at is None:
                    runtime.product_started_at = observed_at
                    runtime.product_type = choose_product(runtime)

                active_episode, active_ramp = active_cnc_episode(asset_episodes, observed_at)
                protected_failure_window = bool(
                    active_episode
                    and str(active_episode.issue["component"]) in {"TWF", "OSF"}
                )
                if active_episode and protected_failure_window:
                    signal_strength = float(active_episode.issue["signal_strength"])
                    physical_ramp = clamp(
                        active_ramp * (0.55 + 0.45 * signal_strength), 0.0, 1.0
                    )
                    if active_ramp >= 0.999:
                        physical_ramp = 1.0
                    if str(active_episode.issue["component"]) == "TWF":
                        runtime.tool_wear_min = max(
                            runtime.tool_wear_min,
                            180.0 + 40.0 * physical_ramp,
                        )
                        if active_ramp >= 0.999:
                            runtime.tool_wear_min = max(runtime.tool_wear_min, 220.0)
                    else:
                        runtime.tool_wear_min = max(
                            runtime.tool_wear_min,
                            185.0 + 40.0 * physical_ramp,
                        )
                        if active_ramp >= 0.999:
                            runtime.tool_wear_min = max(runtime.tool_wear_min, 225.0)

                values = coupled_cnc_values(runtime, asset_episodes, observed_at)
                if is_operating:
                    runtime.product_ticks += 1

                if is_operating and runtime.product_ticks >= product_ticks:
                    cutting_min, cutting_max = PRODUCT_CUTTING_MINUTES[runtime.product_type]
                    cutting_minutes = runtime.rng.uniform(cutting_min, cutting_max)
                    wear_increment = cutting_minutes * TOOL_WEAR_EXPOSURE_FACTOR
                    runtime.tool_wear_min += wear_increment
                    if (
                        active_episode
                        and str(active_episode.issue["component"]) == "TWF"
                    ):
                        # A TWF episode must reach the 200-240 minute band
                        # monotonically. Do not let production increments push
                        # the wear state above the contract and then force it
                        # backwards at the failure tick.
                        runtime.tool_wear_min = min(runtime.tool_wear_min, 220.0)
                    runtime.product_counter += 1
                    production_writer.writerow(
                        {
                            "product_id": f"PRD-{asset['asset_id']}-{runtime.product_counter:07d}",
                            "cnc_asset_id": asset["asset_id"],
                            "cycle_started_at": iso(runtime.product_started_at),
                            "cycle_completed_at": iso(observed_at + tick),
                            "product_type": runtime.product_type,
                            "cutting_minutes": round(cutting_minutes, 4),
                            "tool_wear_increment_min": round(wear_increment, 4),
                        }
                    )
                    runtime.product_started_at = observed_at + tick
                    runtime.product_ticks = 0
                    runtime.product_type = choose_product(runtime)
                    if (
                        runtime.tool_wear_min >= runtime.tool_change_threshold_min
                        and not protected_failure_window
                    ):
                        completed_at = observed_at + tick + timedelta(minutes=30)
                        maintenance_writer.writerow(
                            {
                                "maintenance_id": f"MNT-TOOL-{asset['asset_id']}-{runtime.product_counter:07d}",
                                "asset_id": asset["asset_id"],
                                "maintenance_type": "planned_tool_change",
                                "started_at": iso(observed_at + tick),
                                "completed_at": iso(completed_at),
                                "tool_replaced": 1,
                                "source_event_id": "",
                            }
                        )
                        # Keep the current running row on the old tool. The
                        # reset is applied at the next tick, which is exactly
                        # maintenance_event.started_at and is emitted with
                        # operating_state=maintenance.
                        runtime.tool_reset_at = observed_at + tick
                        runtime.tool_change_threshold_min = runtime.rng.uniform(180.0, 235.0)
                        runtime.planned_maintenance_until = completed_at

                cnc_writer.writerow(
                    {
                        "observed_at": iso(observed_at),
                        "asset_id": asset["asset_id"],
                        "site_id": asset["site_id"],
                        "cell_id": asset["cell_id"],
                        "is_operating": is_operating,
                        "operating_state": state,
                        "product_type": runtime.product_type,
                        "air_temperature_k": round(values["air_temperature_k"], 4),
                        "process_temperature_k": round(values["process_temperature_k"], 4),
                        "rotational_speed_rpm": round(values["rotational_speed_rpm"], 4),
                        "torque_nm": round(values["torque_nm"], 4),
                        "tool_wear_min": round(runtime.tool_wear_min, 4),
                        "generator_version": GENERATOR_VERSION,
                    }
                )
            observed_at += tick

    canonical_files = [
        asset_path,
        relation_path,
        compressor_sensor_path,
        cnc_sensor_path,
        production_path,
        maintenance_path,
    ]
    truth_files = [schedule_path, compressor_truth_path, cnc_truth_path]
    manifest = {
        "dataset_version": GENERATOR_VERSION,
        "created_at": iso(datetime.now(tz=start_at.tzinfo)),
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "days": days,
        "seed": seed,
        "rate_profile": rate_profile,
        "observation_interval_minutes": interval_minutes,
        "asset_counts": {"compressor": 20, "cnc": 80},
        "source_contract": {
            "compressor_and_cnc_independent": True,
            "topology_relation_is_not_causal_truth": True,
            "upstream_features_in_source": False,
            "synthetic_effect_columns_in_source": False,
            "prediction_outputs_in_source": False,
            "evaluation_truth_separate": True,
            "cnc_ai4i_physical_relations": True,
            "failure_modes_satisfy_sensor_conditions": True,
            "asset_variability_policy": "small_offsets_plus_time_varying_physical_process",
        },
        "ai4i_contract": {
            "power_formula": "torque_nm * rotational_speed_rpm * 2*pi/60",
            "power_failure_watts": {"below": POWER_LOW_W, "above": POWER_HIGH_W},
            "heat_dissipation_failure": {
                "temperature_gap_below_k": HDF_TEMPERATURE_GAP_MAX_K,
                "rpm_below": HDF_RPM_MAX,
            },
            "tool_wear_failure_minutes": {"min": TWF_WEAR_MIN, "max": TWF_WEAR_MAX},
            "overstrain_thresholds": OVERSTRAIN_THRESHOLDS,
        },
        "maintenance_contract": {
            "tool_wear_reset_state": "maintenance",
            "tool_wear_reset_timestamp": "maintenance_event.started_at",
            "running_tool_wear_decrease_tolerance_minutes": 1.0,
        },
        "canonical_outputs": {path.name: sha256(path) for path in canonical_files},
        "evaluation_truth_outputs": {path.name: sha256(path) for path in truth_files},
    }
    manifest_path = dataset_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate canonical independent source data")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--start-at", default="2026-08-01T00:00:00+09:00")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--interval-minutes", type=int, default=10)
    parser.add_argument("--product-cycle-minutes", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rate-profile", choices=sorted(RATE_PROFILES), default="balanced_demo")
    args = parser.parse_args()
    result = generate(
        root=Path(args.root),
        start_at=parse_datetime(args.start_at),
        days=args.days,
        interval_minutes=args.interval_minutes,
        product_cycle_minutes=args.product_cycle_minutes,
        seed=args.seed,
        rate_profile=args.rate_profile,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
