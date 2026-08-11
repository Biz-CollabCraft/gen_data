# ──────────────────────────────────────────────
# 프로토콜 무관 RAW 캡처 엔벨롭 모듈
# ──────────────────────────────────────────────

import struct
from pathlib import Path

PROTOCOL_MODBUS_TCP: int = 1
PROTOCOL_OPCUA_BINARY: int = 2


# ──────────────────────────────────────────────
# RAW 파일 엔벨롭 패킹 및 기입
# ──────────────────────────────────────────────

def write_envelope(raw_path: Path, capture_timestamp: float, protocol_id: int, frame: bytes) -> None:
    """캡처 타임스탬프 및 프로토콜 ID와 함께 바이너리 엔벨롭 아펜드 기입."""
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("ab") as f:
        f.write(struct.pack(">dBI", capture_timestamp, protocol_id, len(frame)))
        f.write(frame)
