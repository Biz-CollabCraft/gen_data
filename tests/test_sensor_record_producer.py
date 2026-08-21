from datetime import datetime, timedelta, timezone
import unittest

from app.observation.models import SENSOR_RECORD_SCHEMA_VERSION, SensorRecord
from app.simulation.producer import SimulationProducer


START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def make_producer(run_id: str = "test") -> SimulationProducer:
    return SimulationProducer(
        run_id=run_id,
        start_at=START,
        end_at=START + timedelta(hours=1),
        interval_minutes=10,
        product_cycle_minutes=20,
        seed=42,
    )


class SensorRecordProducerTest(unittest.TestCase):
    def test_sensor_record_required_contract_and_sequence_uniqueness(self):
        producer = make_producer()
        tick = producer.produce_tick(START)
        self.assertEqual(len(tick.records), 100)
        self.assertTrue(all(isinstance(record, SensorRecord) for record in tick.records))
        self.assertEqual([record.sequence for record in tick.records], list(range(1, 101)))
        self.assertEqual(len({record.correlation_key for record in tick.records}), 100)
        first = tick.records[0]
        self.assertEqual(first.schema_version, SENSOR_RECORD_SCHEMA_VERSION)
        self.assertEqual(first.observed_at_source, "source")
        self.assertEqual(first.branch_kind, "canonical")
        self.assertIsNone(first.overlay)
        self.assertTrue(first.observation_id.startswith("obs-"))
        self.assertEqual(first.generator_version, "canonical-ai4i-physics-v3.1")
        self.assertEqual(first.measurements["voltage_raw"], 174.3943)

    def test_same_seed_and_config_are_deterministic_but_run_id_is_not_deduped(self):
        left = make_producer("run-a")
        right = make_producer("run-b")
        for offset in (0, 10):
            observed_at = START + timedelta(minutes=offset)
            left_records = left.produce_tick(observed_at).records
            right_records = right.produce_tick(observed_at).records
            self.assertEqual(
                [record.measurements for record in left_records],
                [record.measurements for record in right_records],
            )
            self.assertEqual(
                [record.asset_id for record in left_records],
                [record.asset_id for record in right_records],
            )
            self.assertEqual({record.run_id for record in left_records}, {"run-a"})
            self.assertEqual({record.run_id for record in right_records}, {"run-b"})
            self.assertEqual(
                [record.observation_id for record in left_records],
                [record.observation_id for record in right_records],
            )
