"""Shared AI4I-style physical contracts for generation and validation."""

from __future__ import annotations

import math
from typing import Mapping


POWER_LOW_W = 3500.0
POWER_HIGH_W = 9000.0
HDF_TEMPERATURE_GAP_MAX_K = 8.6
HDF_RPM_MAX = 1380.0
TWF_WEAR_MIN = 200.0
TWF_WEAR_MAX = 240.0
OVERSTRAIN_THRESHOLDS = {"L": 11000.0, "M": 12000.0, "H": 13000.0}


AI4I_DISTRIBUTION_TARGETS = {
    "air_temperature_k": {"target_std": 2.0, "min_std": 1.6, "max_std": 2.4},
    "process_temperature_k": {"target_std": 1.5, "min_std": 1.2, "max_std": 1.9},
    "rotational_speed_rpm": {"target_std": 179.0, "min_std": 145.0, "max_std": 220.0},
    "torque_nm": {"target_std": 9.97, "min_std": 8.5, "max_std": 11.5},
}

AI4I_RELATION_THRESHOLDS = {
    "air_process_min_correlation": 0.80,
    "rpm_torque_max_correlation": -0.60,
    "process_below_air_max_fraction": 0.0,
}


def power_w(torque_nm: float, rotational_speed_rpm: float) -> float:
    return torque_nm * rotational_speed_rpm * 2.0 * math.pi / 60.0


def overstrain_threshold(product_type: str) -> float:
    return OVERSTRAIN_THRESHOLDS.get(product_type, OVERSTRAIN_THRESHOLDS["M"])


def failure_condition(component: str, row: Mapping[str, object]) -> bool:
    torque = float(row["torque_nm"])
    rpm = float(row["rotational_speed_rpm"])
    tool_wear = float(row["tool_wear_min"])
    air = float(row["air_temperature_k"])
    process = float(row["process_temperature_k"])
    product_type = str(row.get("product_type", "M"))

    if component == "PWF":
        power = power_w(torque, rpm)
        return power < POWER_LOW_W or power > POWER_HIGH_W
    if component == "HDF":
        return (process - air) < HDF_TEMPERATURE_GAP_MAX_K and rpm < HDF_RPM_MAX
    if component == "OSF":
        return tool_wear * torque > overstrain_threshold(product_type)
    if component == "TWF":
        return TWF_WEAR_MIN <= tool_wear <= TWF_WEAR_MAX
    if component == "RNF":
        return True
    raise ValueError(f"unknown CNC component: {component}")
