"""Regression tests for Canonical compressor fields in the real-time daemon."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from line_worker import LineWorker
from physics_engine import Episode, Runtime, build_topology, make_baseline, stable_seed


class DaemonCompressorRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        assets, _relations = build_topology()
        self.asset = next(asset for asset in assets if asset["asset_type"] == "compressor")
        self.observed_at = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
        self.worker = LineWorker.__new__(LineWorker)
        self.worker.config = SimpleNamespace(
            GEN_DATA_INTERVAL_MINUTES=10,
            GEN_DATA_PRODUCT_CYCLE_MINUTES=20,
        )

    def _runtime(self, label: str) -> Runtime:
        return Runtime(
            asset=self.asset,
            rng=random.Random(stable_seed(42, self.asset["asset_id"], label)),
            baseline=make_baseline(self.asset, 42),
        )

    def test_stream_emits_backend_model_input_contract(self) -> None:
        runtime = self._runtime("contract")
        self.worker.runtimes = {self.asset["asset_id"]: runtime}
        self.worker.episodes_by_asset = {self.asset["asset_id"]: []}

        values = self.worker._compute_physics_value(self.asset, self.observed_at)

        self.assertEqual(values["operating_state"], "running")
        self.assertTrue(values["is_operating"])
        self.assertIn(values["relative_vibration_zone"], {"A", "B", "C", "D"})
        self.assertIsInstance(values["relative_vibration_z"], float)
        self.assertTrue(values["generator_version"])

    def test_failure_episode_changes_compressor_signal(self) -> None:
        normal_runtime = self._runtime("same-seed")
        failure_runtime = self._runtime("same-seed")
        episode = Episode(
            event_id="EV-COMPRESSOR-TEST",
            issue={
                "asset_id": self.asset["asset_id"],
                "asset_type": "compressor",
                "component": "comp3",
                "signal_strength": 1.0,
            },
            degradation_started_at=self.observed_at - timedelta(hours=24),
            failure_at=self.observed_at,
            maintenance_started_at=self.observed_at + timedelta(minutes=10),
            maintenance_completed_at=self.observed_at + timedelta(minutes=40),
        )

        self.worker.runtimes = {self.asset["asset_id"]: normal_runtime}
        self.worker.episodes_by_asset = {self.asset["asset_id"]: []}
        normal = self.worker._compute_physics_value(self.asset, self.observed_at)

        self.worker.runtimes = {self.asset["asset_id"]: failure_runtime}
        self.worker.episodes_by_asset = {self.asset["asset_id"]: [episode]}
        degraded = self.worker._compute_physics_value(self.asset, self.observed_at)

        self.assertNotEqual(degraded["pressure_raw"], normal["pressure_raw"])

    def test_maintenance_tick_is_not_reported_as_running(self) -> None:
        runtime = self._runtime("maintenance")
        episode = Episode(
            event_id="EV-COMPRESSOR-MAINTENANCE",
            issue={
                "asset_id": self.asset["asset_id"],
                "asset_type": "compressor",
                "component": "comp3",
                "signal_strength": 1.0,
            },
            degradation_started_at=self.observed_at - timedelta(hours=24),
            failure_at=self.observed_at - timedelta(minutes=20),
            maintenance_started_at=self.observed_at - timedelta(minutes=10),
            maintenance_completed_at=self.observed_at + timedelta(minutes=20),
        )
        self.worker.runtimes = {self.asset["asset_id"]: runtime}
        self.worker.episodes_by_asset = {self.asset["asset_id"]: [episode]}

        values = self.worker._compute_physics_value(self.asset, self.observed_at)

        self.assertFalse(values["is_operating"])
        self.assertEqual(values["operating_state"], "maintenance")


if __name__ == "__main__":
    unittest.main()
