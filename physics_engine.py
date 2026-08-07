# ──────────────────────────────────────────────
# 물리 계산 엔진 모듈 (v3.1 스크립트 연동)
# ──────────────────────────────────────────────

import sys
from pathlib import Path

# v3.1 스크립트 경로 주입 (물리 계산 로직 재사용)
V3_1_SCRIPTS = Path(r"C:\kosa\project\final\predictive_maintenance_canonical_v3.1\scripts")
if str(V3_1_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(V3_1_SCRIPTS))

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
