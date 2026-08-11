# ──────────────────────────────────────────────
# Modbus TCP 프로토콜 어댑터 모듈
# ──────────────────────────────────────────────

import json
import struct
from .base_protocol import ProtocolAdapter
from .raw_envelope import PROTOCOL_MODBUS_TCP


# ──────────────────────────────────────────────
# Modbus TCP 어댑터 클래스
# ──────────────────────────────────────────────

class ModbusTcpAdapter(ProtocolAdapter):
    """Modbus TCP 프로토콜 인코딩/디코딩 어댑터."""

    protocol_id: int = PROTOCOL_MODBUS_TCP

    def encode_response(self, unit_or_node_map: dict, raw_values: dict) -> bytes:
        """관측 데이터를 Modbus MBAP + PDU 패킷 바이트로 인코딩."""
        payload = {
            "unit_map": unit_or_node_map,
            "values": raw_values
        }
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        transaction_id = 1
        protocol_id = 0
        unit_id = 1
        function_code = 3
        header = struct.pack(">HHHB", transaction_id, protocol_id, len(json_bytes) + 2, unit_id)
        pdu_header = struct.pack(">B", function_code)
        return header + pdu_header + json_bytes

    def decode_response(self, frame: bytes) -> dict:
        """Modbus 패킷 바이트를 디코딩하여 관측 수치 딕셔너리로 복원."""
        if len(frame) < 8:
            return {}
        json_bytes = frame[8:]
        try:
            payload = json.loads(json_bytes.decode("utf-8"))
            return payload.get("values", {})
        except Exception:
            return {}
