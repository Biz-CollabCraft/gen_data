# ──────────────────────────────────────────────
# 물리 계산 엔진 모듈 (v3.1 스크립트 연동)
# ──────────────────────────────────────────────

import os
import sys
from pathlib import Path

# Canonical V3.1 source/reference baseline은 저장소 루트에 직접 수렴한다.
# 외부 기준본을 비교해야 하는 경우에만 GEN_DATA_CANONICAL_ROOT로 명시한다.
_configured_root = os.environ.get("GEN_DATA_CANONICAL_ROOT")
_canonical_root = (
    Path(_configured_root).expanduser()
    if _configured_root
    else Path(__file__).resolve().parent
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
        "Canonical V3.1 generator is unavailable under the repository root; "
        "set GEN_DATA_CANONICAL_ROOT only when validating an external baseline."
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
