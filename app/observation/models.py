"""Internal observation contract shared by every output projection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Any


SENSOR_RECORD_SCHEMA_VERSION = "2"


@dataclass(frozen=True)
class SensorRecord:
    schema_version: str
    run_id: str
    sequence: int
    asset_id: str
    observed_at: datetime
    measurements: dict[str, Any]
    generator_version: str
    asset_type: str
    site_id: str
    cell_id: str
    source_kind: str = "simulation"
    observation_id: str = ""
    observed_at_source: str = "source"
    branch_kind: str = "canonical"
    overlay: dict[str, Any] | None = None
    record_kind: str = "full_observation"
    quality: str = "good"

    def __post_init__(self) -> None:
        if self.schema_version != SENSOR_RECORD_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported SensorRecord schema_version: {self.schema_version}"
            )
        if not self.run_id:
            raise ValueError("run_id is required")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not isinstance(self.measurements, dict) or not self.measurements:
            raise ValueError("measurements must be a non-empty mapping")
        if self.source_kind not in {"simulation", "opcua"}:
            raise ValueError(f"unsupported source_kind: {self.source_kind}")
        if self.observed_at_source not in {"source", "server", "received"}:
            raise ValueError("unsupported observed_at_source")
        if self.branch_kind not in {"canonical", "overlay"}:
            raise ValueError("unsupported branch_kind")
        if self.branch_kind == "overlay" and self.overlay is None:
            raise ValueError("overlay metadata is required for overlay branch")
        if self.record_kind not in {"full_observation", "single_measurement"}:
            raise ValueError("unsupported record_kind")
        if self.record_kind == "single_measurement" and len(self.measurements) != 1:
            raise ValueError("single_measurement records require exactly one measurement")
        if self.source_kind == "opcua" and self.record_kind != "single_measurement":
            raise ValueError("OPC UA source records must use single_measurement")
        if self.quality not in {"good", "uncertain", "bad"}:
            raise ValueError("unsupported quality")
        if not self.observation_id:
            object.__setattr__(self, "observation_id", self._stable_observation_id())

    @property
    def correlation_key(self) -> tuple[str, int, str]:
        return self.run_id, self.sequence, self.asset_id

    def _stable_observation_id(self) -> str:
        payload = {
            "asset_id": self.asset_id,
            "observed_at": self.observed_at.isoformat(timespec="seconds"),
            "measurements": self.measurements,
            "source_kind": self.source_kind,
            "record_kind": self.record_kind,
            "quality": self.quality,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"obs-{digest[:32]}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat(timespec="seconds")
        return payload
