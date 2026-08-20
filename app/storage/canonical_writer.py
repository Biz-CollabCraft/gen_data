"""Projection of SensorRecord values into the established inter-repo CSV contract."""

from __future__ import annotations

import csv
from pathlib import Path

from app.observation.models import SensorRecord


COMPRESSOR_COLUMNS = [
    "observed_at",
    "asset_id",
    "site_id",
    "cell_id",
    "is_operating",
    "operating_state",
    "voltage_raw",
    "rotation_raw",
    "pressure_raw",
    "vibration_raw",
    "relative_vibration_z",
    "relative_vibration_zone",
    "generator_version",
]

CNC_COLUMNS = [
    "observed_at",
    "asset_id",
    "site_id",
    "cell_id",
    "is_operating",
    "operating_state",
    "product_type",
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
    "generator_version",
]

PRODUCTION_COLUMNS = [
    "product_id",
    "cnc_asset_id",
    "cycle_started_at",
    "cycle_completed_at",
    "product_type",
    "cutting_minutes",
    "tool_wear_increment_min",
]

MAINTENANCE_COLUMNS = [
    "maintenance_id",
    "asset_id",
    "maintenance_type",
    "started_at",
    "completed_at",
    "tool_replaced",
    "source_event_id",
]

ASSET_COLUMNS = ["asset_id", "asset_type", "site_id", "cell_id"]
RELATION_COLUMNS = ["from_asset_id", "relation_type", "to_asset_id"]


class CanonicalWriter:
    """Write exactly the canonical CSV shape consumed by ontology_dashboard."""

    def __init__(self, dataset_dir: Path) -> None:
        dataset_dir.mkdir(parents=True, exist_ok=True)
        self.dataset_dir = dataset_dir
        self.asset_path = dataset_dir / "asset_master.csv"
        self.relation_path = dataset_dir / "asset_relation.csv"
        self.compressor_path = dataset_dir / "compressor_sensor_observation.csv"
        self.cnc_path = dataset_dir / "cnc_sensor_observation.csv"
        self.production_path = dataset_dir / "cnc_production_cycle.csv"
        self.maintenance_path = dataset_dir / "maintenance_event.csv"

        self._compressor_handle = self.compressor_path.open("w", newline="", encoding="utf-8")
        self._cnc_handle = self.cnc_path.open("w", newline="", encoding="utf-8")
        self._production_handle = self.production_path.open("w", newline="", encoding="utf-8")
        self._maintenance_handle = self.maintenance_path.open("w", newline="", encoding="utf-8")
        self._compressor = csv.DictWriter(self._compressor_handle, fieldnames=COMPRESSOR_COLUMNS)
        self._cnc = csv.DictWriter(self._cnc_handle, fieldnames=CNC_COLUMNS)
        self._production = csv.DictWriter(self._production_handle, fieldnames=PRODUCTION_COLUMNS)
        self._maintenance = csv.DictWriter(self._maintenance_handle, fieldnames=MAINTENANCE_COLUMNS)
        for writer in (self._compressor, self._cnc, self._production, self._maintenance):
            writer.writeheader()
        self.observation_count = 0
        self.production_count = 0
        self.maintenance_count = 0

    def write_static_contract(
        self,
        assets: list[dict[str, str]],
        relations: list[dict[str, str]],
    ) -> None:
        for path, columns, rows in (
            (self.asset_path, ASSET_COLUMNS, assets),
            (self.relation_path, RELATION_COLUMNS, relations),
        ):
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)

    def write_record(self, record: SensorRecord) -> None:
        row = {
            "observed_at": record.observed_at.isoformat(timespec="seconds"),
            "asset_id": record.asset_id,
            "site_id": record.site_id,
            "cell_id": record.cell_id,
            **record.measurements,
            "generator_version": record.generator_version,
        }
        if record.asset_type == "compressor":
            self._compressor.writerow(row)
        elif record.asset_type == "cnc":
            self._cnc.writerow(row)
        else:
            raise ValueError(f"unsupported canonical asset_type: {record.asset_type}")
        self.observation_count += 1

    def write_production(self, payload: dict[str, object]) -> None:
        self._production.writerow(payload)
        self.production_count += 1

    def write_maintenance(self, payload: dict[str, object]) -> None:
        self._maintenance.writerow(payload)
        self.maintenance_count += 1

    @property
    def paths(self) -> list[Path]:
        return [
            self.asset_path,
            self.relation_path,
            self.compressor_path,
            self.cnc_path,
            self.production_path,
            self.maintenance_path,
        ]

    def flush(self) -> None:
        for handle in self._handles:
            handle.flush()

    @property
    def _handles(self):
        return (
            self._compressor_handle,
            self._cnc_handle,
            self._production_handle,
            self._maintenance_handle,
        )

    def close(self) -> None:
        for handle in self._handles:
            if not handle.closed:
                handle.flush()
                handle.close()

    def __enter__(self) -> "CanonicalWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
