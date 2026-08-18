# ──────────────────────────────────────────────
# 전역 단일 타임라인 상태 관리 모듈
# ──────────────────────────────────────────────

import json
import os
from pathlib import Path
from datetime import datetime

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
    """전역 상태 JSON 파일 기입."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────
# 전역 틱 시각 조회
# ──────────────────────────────────────────────

def get_global_last_tick(state: dict) -> datetime | None:
    """마지막 전역 틱 시각 조회."""
    raw = state.get("last_tick")
    return datetime.fromisoformat(raw) if raw else None


# ──────────────────────────────────────────────
# 전역 틱 시각 기입
# ──────────────────────────────────────────────

def set_global_last_tick(state: dict, observed_at: datetime) -> None:
    """전역 틱 시각 갱신."""
    state["last_tick"] = observed_at.isoformat()
