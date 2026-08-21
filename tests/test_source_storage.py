import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from app.observation.models import SENSOR_RECORD_SCHEMA_VERSION, SensorRecord
from app.storage.source_writer import SourceRecordWriter


def record(run_id: str, sequence: int) -> SensorRecord:
    return SensorRecord(
        schema_version=SENSOR_RECORD_SCHEMA_VERSION,
        run_id=run_id,
        sequence=sequence,
        asset_id="CNC-S01-L01-01",
        observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        measurements={"torque_nm": 40.5},
        generator_version="canonical-ai4i-physics-v3.1",
        asset_type="cnc",
        site_id="S01",
        cell_id="S01-L01",
    )


class SourceStorageTest(unittest.TestCase):
    def test_source_writer_appends_serialized_records_and_isolates_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            left = tmp_path / "run-a" / "source.jsonl"
            right = tmp_path / "run-b" / "source.jsonl"
            with SourceRecordWriter(left) as writer:
                writer.write(record("run-a", 1))
                writer.write(record("run-a", 2))
            with SourceRecordWriter(right) as writer:
                writer.write(record("run-b", 1))
            left_rows = [json.loads(line) for line in left.read_text(encoding="utf-8").splitlines()]
            right_rows = [json.loads(line) for line in right.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["sequence"] for row in left_rows], [1, 2])
            self.assertEqual({row["run_id"] for row in left_rows}, {"run-a"})
            self.assertEqual({row["run_id"] for row in right_rows}, {"run-b"})
            self.assertEqual({row["schema_version"] for row in left_rows}, {"2"})
            self.assertTrue(all(row["observation_id"].startswith("obs-") for row in left_rows))
            self.assertEqual({row["branch_kind"] for row in left_rows}, {"canonical"})
