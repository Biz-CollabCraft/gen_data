# ──────────────────────────────────────────────
# 전역 단일 타임라인 상태 관리 모듈
# ──────────────────────────────────────────────

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any

STATE_PATH = Path(
    os.environ.get(
        "GEN_DATA_STATE_PATH",
        str(Path(__file__).parent / ".state" / "gen_data_state.json"),
    )
).expanduser()


# ──────────────────────────────────────────────
# 상태 파일 로드
# ──────────────────────────────────────────────

def load_state() -> dict:
    """전역 상태 JSON 파일 읽기."""
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────
# 상태 파일 저장
# ──────────────────────────────────────────────

def save_state(state: dict) -> None:
    """전역 상태 JSON 파일을 원자적으로 기입."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STATE_PATH)


# ──────────────────────────────────────────────
# 전역 틱 시각 조회
# ──────────────────────────────────────────────

def get_global_last_tick(state: dict, *, mode: str | None = None) -> datetime | None:
    """마지막 전역 틱 시각 조회."""
    if mode:
        raw = (state.get("last_tick_by_mode") or {}).get(mode)
        # Legacy checkpoints only belong to the historical accelerated daemon.
        if raw is None and mode == "accelerated":
            raw = state.get("last_tick")
    else:
        raw = state.get("last_tick")
    return datetime.fromisoformat(raw) if raw else None


# ──────────────────────────────────────────────
# 전역 틱 시각 기입
# ──────────────────────────────────────────────

def set_global_last_tick(state: dict, observed_at: datetime, *, mode: str | None = None) -> None:
    """전역 틱 시각 갱신."""
    state["last_tick"] = observed_at.isoformat()
    if mode:
        by_mode = state.setdefault("last_tick_by_mode", {})
        by_mode[mode] = observed_at.isoformat()


def get_wall_clock_schedule_origin(state: dict) -> datetime | None:
    raw = state.get("wall_clock_schedule_origin")
    return datetime.fromisoformat(raw) if raw else None


def set_wall_clock_schedule_origin(state: dict, value: datetime) -> None:
    state["wall_clock_schedule_origin"] = value.isoformat()


def _json_safe_random_state(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe_random_state(item) for item in value]
    if isinstance(value, list):
        return [_json_safe_random_state(item) for item in value]
    return value


def _tuple_random_state(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuple_random_state(item) for item in value)
    return value


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def checkpoint_wall_clock_runtimes(state: dict, runtimes: dict[str, Any]) -> None:
    """Persist stateful physics/RNG state so live values remain continuous."""

    state["wall_clock_runtime_state"] = {
        asset_id: {
            "noise_state": dict(runtime.noise_state),
            "tool_wear_min": runtime.tool_wear_min,
            "tool_change_threshold_min": runtime.tool_change_threshold_min,
            "product_started_at": _timestamp(runtime.product_started_at),
            "product_type": runtime.product_type,
            "product_ticks": runtime.product_ticks,
            "product_counter": runtime.product_counter,
            "planned_maintenance_until": _timestamp(runtime.planned_maintenance_until),
            "tool_reset_at": _timestamp(runtime.tool_reset_at),
            "rng_state": _json_safe_random_state(runtime.rng.getstate()),
        }
        for asset_id, runtime in runtimes.items()
    }


def restore_wall_clock_runtimes(state: dict, runtimes: dict[str, Any]) -> int:
    """Restore persisted live physics state into freshly constructed runtimes."""

    payload = state.get("wall_clock_runtime_state") or {}
    restored = 0
    for asset_id, item in payload.items():
        runtime = runtimes.get(asset_id)
        if runtime is None or not isinstance(item, dict):
            continue
        runtime.noise_state = {
            key: float(value) for key, value in (item.get("noise_state") or {}).items()
        }
        runtime.tool_wear_min = float(item.get("tool_wear_min", runtime.tool_wear_min))
        runtime.tool_change_threshold_min = float(
            item.get("tool_change_threshold_min", runtime.tool_change_threshold_min)
        )
        runtime.product_started_at = (
            datetime.fromisoformat(item["product_started_at"])
            if item.get("product_started_at")
            else None
        )
        runtime.product_type = str(item.get("product_type", runtime.product_type))
        runtime.product_ticks = int(item.get("product_ticks", runtime.product_ticks))
        runtime.product_counter = int(item.get("product_counter", runtime.product_counter))
        runtime.planned_maintenance_until = (
            datetime.fromisoformat(item["planned_maintenance_until"])
            if item.get("planned_maintenance_until")
            else None
        )
        runtime.tool_reset_at = (
            datetime.fromisoformat(item["tool_reset_at"])
            if item.get("tool_reset_at")
            else None
        )
        if item.get("rng_state") is not None:
            runtime.rng.setstate(_tuple_random_state(item["rng_state"]))
        restored += 1
    return restored
