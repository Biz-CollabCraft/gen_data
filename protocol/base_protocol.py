# ──────────────────────────────────────────────
# 추상 프로토콜 어댑터 모듈
# ──────────────────────────────────────────────

from abc import ABC, abstractmethod


# ──────────────────────────────────────────────
# 프로토콜 어댑터 인터페이스
# ──────────────────────────────────────────────

class ProtocolAdapter(ABC):
    """프로토콜 인코딩/디코딩 추상 클래스."""

    protocol_id: int

    @abstractmethod
    def encode_response(self, unit_or_node_map: dict, raw_values: dict) -> bytes:
        """관측 수치를 프로토콜 프레임 바이트로 인코딩."""
        pass

    @abstractmethod
    def decode_response(self, frame: bytes) -> dict:
        """프로토콜 프레임 바이트를 값 딕셔너리로 디코딩."""
        pass
