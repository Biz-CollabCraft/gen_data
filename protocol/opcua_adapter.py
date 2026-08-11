# ──────────────────────────────────────────────
# OPC-UA Binary 프로토콜 어댑터 모듈
# ──────────────────────────────────────────────

import json
import struct
from .base_protocol import ProtocolAdapter
from .raw_envelope import PROTOCOL_OPCUA_BINARY


# ──────────────────────────────────────────────
# OPC-UA Binary 어댑터 클래스
# ──────────────────────────────────────────────

class OpcUaBinaryAdapter(ProtocolAdapter):
    """OPC-UA Binary 프로토콜 인코딩/디코딩 어댑터."""

    protocol_id: int = PROTOCOL_OPCUA_BINARY

    def encode_response(self, unit_or_node_map: dict, raw_values: dict) -> bytes:
        """관측 데이터를 OPC-UA DataValue 인코딩 패킷으로 변환."""
        payload = {
            "node_map": unit_or_node_map,
            "values": raw_values,
            "status_code": 0
        }
        json_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        msg_type = b"MSG"
        is_final = b"F"
        body_length = len(json_bytes) + 8
        header = struct.pack("3s1sI", msg_type, is_final, body_length)
        return header + json_bytes

    def decode_response(self, frame: bytes) -> dict:
        """OPC-UA 패킷 바이트를 디코딩하여 관측 수치 딕셔너리로 복원."""
        if len(frame) < 8:
            return {}
        json_bytes = frame[8:]
        try:
            payload = json.loads(json_bytes.decode("utf-8"))
            return payload.get("values", {})
        except Exception:
            return {}
