# ──────────────────────────────────────────────
# 프로토콜 어댑터 패키지 초기화 모듈
# ──────────────────────────────────────────────

"""프로토콜 인코딩/디코딩 어댑터 및 raw envelope 처리 모듈."""

from gen_data.protocol.base_protocol import ProtocolAdapter
from gen_data.protocol.modbus_adapter import ModbusTcpAdapter
from gen_data.protocol.opcua_adapter import OpcUaBinaryAdapter
from gen_data.protocol.raw_envelope import (
    PROTOCOL_MODBUS_TCP,
    PROTOCOL_OPCUA_BINARY,
    write_envelope,
)

__all__ = [
    "ProtocolAdapter",
    "ModbusTcpAdapter",
    "OpcUaBinaryAdapter",
    "PROTOCOL_MODBUS_TCP",
    "PROTOCOL_OPCUA_BINARY",
    "write_envelope",
]
