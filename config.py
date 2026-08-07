# ──────────────────────────────────────────────
# gen_data 환경 설정 모듈
# ──────────────────────────────────────────────

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DEFAULT_OUTPUT_DIR = r"C:\kosa\project\final\gen_data\output"

GEN_DATA_OUTPUT_DIR = os.environ.get("GEN_DATA_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
if not GEN_DATA_OUTPUT_DIR:
    GEN_DATA_OUTPUT_DIR = DEFAULT_OUTPUT_DIR

GEN_DATA_SEED: int = int(os.environ.get("GEN_DATA_SEED", "42"))
GEN_DATA_INTERVAL_MINUTES: int = int(os.environ.get("GEN_DATA_INTERVAL_MINUTES", "10"))
GEN_DATA_SPEED: float = float(os.environ.get("GEN_DATA_SPEED", "60"))
GEN_DATA_BACKFILL_HOURS: int = int(os.environ.get("GEN_DATA_BACKFILL_HOURS", "6"))
GEN_DATA_MAX_PARALLEL_LINES: int = int(os.environ.get("GEN_DATA_MAX_PARALLEL_LINES", "20"))
GEN_DATA_PROTOCOL: str = os.environ.get("GEN_DATA_PROTOCOL", "modbus_tcp")
