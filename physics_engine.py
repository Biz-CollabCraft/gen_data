# ──────────────────────────────────────────────
# 물리 계산 엔진 모듈 (v3.1 스크립트 연동)
# ──────────────────────────────────────────────

import os
import sys
from pathlib import Path

# Canonical V3.1은 PR #2가 merge되면 이 저장소 하위에 위치한다. PR #1만
# checkout한 경우에는 GEN_DATA_CANONICAL_ROOT로 외부 기준본을 명시할 수 있다.
_configured_root = os.environ.get("GEN_DATA_CANONICAL_ROOT")
_canonical_root = (
    Path(_configured_root).expanduser()
    if _configured_root
    else Path(__file__).resolve().parent / "predictive_maintenance_canonical_v3_1"
)
V3_1_SCRIPTS = _canonical_root / "scripts"
if str(V3_1_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(V3_1_SCRIPTS))

try:
    from generate_canonical_dataset import (  # noqa: E402
        build_topology,
        build_schedule,
        build_episodes,
        make_baseline,
        coupled_cnc_values,
        ar_noise,
        operating_state,
        active_cnc_episode,
        Runtime,
        Episode,
        stable_seed,
        COMPRESSOR_BASELINE,
        CNC_BASELINE,
        GENERATOR_VERSION,
    )
except ModuleNotFoundError as exc:
    if exc.name != "generate_canonical_dataset":
        raise
    raise ModuleNotFoundError(
        "Canonical V3.1 generator is unavailable. Merge/provide "
        "predictive_maintenance_canonical_v3_1 or set GEN_DATA_CANONICAL_ROOT."
    ) from exc

__all__ = [
    "build_topology",
    "build_schedule",
    "build_episodes",
    "make_baseline",
    "coupled_cnc_values",
    "ar_noise",
    "operating_state",
    "active_cnc_episode",
    "Runtime",
    "Episode",
    "stable_seed",
    "COMPRESSOR_BASELINE",
    "CNC_BASELINE",
    "GENERATOR_VERSION",
]
