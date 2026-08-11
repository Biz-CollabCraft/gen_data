"""Regression tests for CNC product/tool-wear state in the real-time daemon."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from line_worker import LineWorker
from physics_engine import Runtime, build_topology, make_baseline, stable_seed


class DaemonCncRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        assets, _relations = build_topology()
        self.asset = next(asset for asset in assets if asset["asset_type"] == "cnc")
        self.runtime = Runtime(
            asset=self.asset,
            rng=random.Random(stable_seed(42, self.asset["asset_id"], "runtime-test")),
            baseline=make_baseline(self.asset, 42),
        )
        self.worker = LineWorker.__new__(LineWorker)
        self.worker.runtimes = {self.asset["asset_id"]: self.runtime}
        self.worker.episodes_by_asset = {self.asset["asset_id"]: []}
        self.worker.config = SimpleNamespace(
            GEN_DATA_INTERVAL_MINUTES=10,
            GEN_DATA_PRODUCT_CYCLE_MINUTES=20,
        )
        self.observed_at = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)

    def test_stream_uses_runtime_product_and_tool_wear_state(self) -> None:
        self.runtime.product_started_at = self.observed_at
        self.runtime.product_type = "H"
        self.runtime.tool_wear_min = 123.4

        values = self.worker._compute_physics_value(self.asset, self.observed_at)

        self.assertEqual(values["product_type"], "H")
        self.assertEqual(values["tool_wear_min"], 123.4)

    def test_operating_cycles_increase_tool_wear(self) -> None:
        first = self.worker._compute_physics_value(self.asset, self.observed_at)
        second = self.worker._compute_physics_value(
            self.asset,
            self.observed_at.replace(minute=10),
        )

        self.assertEqual(first["tool_wear_min"], 0.0)
        self.assertGreater(second["tool_wear_min"], 0.0)
        self.assertEqual(self.runtime.product_counter, 1)


if __name__ == "__main__":
    unittest.main()
