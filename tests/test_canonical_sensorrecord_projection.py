import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from scripts.generate_canonical_dataset import generate


def rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CanonicalSensorRecordProjectionTest(unittest.TestCase):
    def test_generated_canonical_contract_preserves_v31_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            generate(
                root=tmp_path,
                start_at=datetime.fromisoformat("2026-08-01T00:00:00+09:00"),
                days=1,
                interval_minutes=10,
                product_cycle_minutes=20,
                seed=42,
                rate_profile="balanced_demo",
            )
            generated = tmp_path / "canonical" / "dataset"
            expected_columns = {
                "compressor_sensor_observation.csv": [
                    "observed_at", "asset_id", "site_id", "cell_id", "is_operating",
                    "operating_state", "voltage_raw", "rotation_raw", "pressure_raw",
                    "vibration_raw", "relative_vibration_z", "relative_vibration_zone",
                    "generator_version",
                ],
                "cnc_sensor_observation.csv": [
                    "observed_at", "asset_id", "site_id", "cell_id", "is_operating",
                    "operating_state", "product_type", "air_temperature_k",
                    "process_temperature_k", "rotational_speed_rpm", "torque_nm",
                    "tool_wear_min", "generator_version",
                ],
            }
            for filename, expected_count in (
                ("compressor_sensor_observation.csv", 2880),
                ("cnc_sensor_observation.csv", 11520),
            ):
                generated_rows = rows(generated / filename)
                self.assertEqual(len(generated_rows), expected_count)
                self.assertEqual(list(generated_rows[0]), expected_columns[filename])
                identities = {(row["asset_id"], row["observed_at"]) for row in generated_rows}
                self.assertEqual(len(identities), expected_count)
            compressor = rows(generated / "compressor_sensor_observation.csv")
            self.assertEqual(compressor[0]["voltage_raw"], "174.3943")
            checkpoint = next(
                row
                for row in compressor
                if row["asset_id"] == "CMP-S04-L02-01"
                and row["observed_at"] == "2026-08-01T10:10:00+09:00"
            )
            self.assertEqual(checkpoint["pressure_raw"], "99.9272")
            self.assertEqual(checkpoint["vibration_raw"], "47.3745")
            manifest = json.loads((generated / "dataset_manifest.json").read_text(encoding="utf-8"))
            for filename, checksum in manifest["canonical_outputs"].items():
                self.assertEqual(digest(generated / filename), checksum)
