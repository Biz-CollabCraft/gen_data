"""Internal observation contract shared by every output projection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


SENSOR_RECORD_SCHEMA_VERSION = "1"


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

    def __post_init__(self) -> None:
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

    @property
    def correlation_key(self) -> tuple[str, int, str]:
        return self.run_id, self.sequence, self.asset_id

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat(timespec="seconds")
        return payload
