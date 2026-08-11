"""Configuration loading for the gen_data simulator."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


def _load_local_dotenv(path: Path = ROOT_DIR / ".env") -> None:
    """Load a small KEY=VALUE .env file without requiring a third-party package."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_dotenv()

DEFAULT_OUTPUT_DIR = str(ROOT_DIR / "output")
_raw_output_dir = os.environ.get("GEN_DATA_OUTPUT_DIR", "").strip()
if _raw_output_dir:
    GEN_DATA_OUTPUT_DIR = _raw_output_dir
    OUTPUT_DIR_SOURCE = "env"
else:
    GEN_DATA_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
    OUTPUT_DIR_SOURCE = "default_fallback"

DEFAULTS: dict[str, object] = {
    "GEN_DATA_SEED": 42,
    "GEN_DATA_INTERVAL_MINUTES": 10,
    "GEN_DATA_PRODUCT_CYCLE_MINUTES": 20,
    "GEN_DATA_SPEED": 60,
    "GEN_DATA_BACKFILL_HOURS": 6,
    "GEN_DATA_MAX_PARALLEL_LINES": 20,
    "GEN_DATA_PROTOCOL": "modbus_tcp",
}


def _load_generation_settings() -> tuple[dict[str, object], str]:
    configured_path = os.environ.get("GEN_DATA_SETTING_CONFIG_PATH", "").strip()
    config_path = Path(configured_path) if configured_path else ROOT_DIR / "setting.config"
    if not config_path.exists():
        return dict(DEFAULTS), "hardcoded_default"

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"setting.config must contain a JSON object: {config_path}")
    return {**DEFAULTS, **payload}, "setting.config"


_settings, SETTINGS_SOURCE = _load_generation_settings()

_env_seed = os.environ.get("GEN_DATA_SEED")
_raw_seed = _env_seed if _env_seed is not None else _settings["GEN_DATA_SEED"]
if str(_raw_seed).strip().lower() in {"random", "-1", "none"}:
    # Resolve entropy once so every component in one run shares the same seed,
    # while a later process receives a different seed.
    GEN_DATA_SEED = secrets.SystemRandom().randrange(0, 2**63)
    SEED_SOURCE = "random"
else:
    GEN_DATA_SEED = int(_raw_seed)
    SEED_SOURCE = "env" if _env_seed is not None else SETTINGS_SOURCE

GEN_DATA_INTERVAL_MINUTES = int(_settings["GEN_DATA_INTERVAL_MINUTES"])
GEN_DATA_PRODUCT_CYCLE_MINUTES = int(_settings["GEN_DATA_PRODUCT_CYCLE_MINUTES"])
GEN_DATA_SPEED = float(_settings["GEN_DATA_SPEED"])
GEN_DATA_BACKFILL_HOURS = int(_settings["GEN_DATA_BACKFILL_HOURS"])
GEN_DATA_MAX_PARALLEL_LINES = int(_settings["GEN_DATA_MAX_PARALLEL_LINES"])
GEN_DATA_PROTOCOL = str(_settings["GEN_DATA_PROTOCOL"])
