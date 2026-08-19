from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone

from generation_clock import (
    accelerated_start_time,
    ceil_wall_clock_boundary,
    next_wall_clock_boundary,
)
from physics_engine import Runtime, build_topology, make_baseline, stable_seed
from state_tracker import checkpoint_wall_clock_runtimes, restore_wall_clock_runtimes


UTC = timezone.utc


class GenerationClockTest(unittest.TestCase):
    def test_wall_clock_boundary_rounds_startup_forward(self) -> None:
        now = datetime(2026, 8, 18, 9, 24, 12, tzinfo=UTC)
        self.assertEqual(
            ceil_wall_clock_boundary(now, 10),
            datetime(2026, 8, 18, 9, 30, tzinfo=UTC),
        )

    def test_exact_boundary_can_be_first_startup_emission(self) -> None:
        now = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)
        self.assertEqual(
            next_wall_clock_boundary(now, interval_minutes=10),
            now,
        )

    def test_next_cadence_is_absolute_boundary(self) -> None:
        last = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)
        now = datetime(2026, 8, 18, 9, 31, 47, tzinfo=UTC)
        self.assertEqual(
            next_wall_clock_boundary(now, interval_minutes=10, last_emitted_at=last),
            datetime(2026, 8, 18, 9, 40, tzinfo=UTC),
        )

    def test_restart_after_downtime_does_not_backfill(self) -> None:
        last = datetime(2026, 8, 18, 8, 50, tzinfo=UTC)
        now = datetime(2026, 8, 18, 9, 24, tzinfo=UTC)
        self.assertEqual(
            next_wall_clock_boundary(now, interval_minutes=10, last_emitted_at=last),
            datetime(2026, 8, 18, 9, 30, tzinfo=UTC),
        )

    def test_clock_rollback_never_reemits_older_boundary(self) -> None:
        last = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)
        rolled_back_now = datetime(2026, 8, 18, 9, 18, tzinfo=UTC)
        self.assertEqual(
            next_wall_clock_boundary(
                rolled_back_now,
                interval_minutes=10,
                last_emitted_at=last,
            ),
            datetime(2026, 8, 18, 9, 40, tzinfo=UTC),
        )

    def test_accelerated_mode_keeps_legacy_start_policy(self) -> None:
        now = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)
        self.assertEqual(
            accelerated_start_time(
                now,
                interval_minutes=10,
                backfill_hours=6,
            ),
            datetime(2026, 8, 18, 3, 30, tzinfo=UTC),
        )
        self.assertEqual(
            accelerated_start_time(
                now,
                interval_minutes=10,
                backfill_hours=6,
                last_emitted_at=datetime(2026, 8, 18, 4, 20, tzinfo=UTC),
            ),
            datetime(2026, 8, 18, 4, 30, tzinfo=UTC),
        )

    def test_wall_clock_runtime_checkpoint_restores_physics_state(self) -> None:
        assets, _ = build_topology()
        asset = next(item for item in assets if item["asset_type"] == "cnc")
        runtime = Runtime(
            asset=asset,
            rng=random.Random(stable_seed(42, asset["asset_id"], "clock-test")),
            baseline=make_baseline(asset, 42),
        )
        runtime.noise_state["torque_nm"] = 1.25
        runtime.tool_wear_min = 77.5
        runtime.product_type = "H"
        runtime.product_counter = 8
        runtime.product_started_at = datetime(2026, 8, 18, 9, 10, tzinfo=UTC)

        state: dict = {}
        checkpoint_wall_clock_runtimes(state, {asset["asset_id"]: runtime})

        restored = Runtime(
            asset=asset,
            rng=random.Random(999),
            baseline=make_baseline(asset, 42),
        )
        count = restore_wall_clock_runtimes(state, {asset["asset_id"]: restored})

        self.assertEqual(count, 1)
        self.assertEqual(restored.noise_state, {"torque_nm": 1.25})
        self.assertEqual(restored.tool_wear_min, 77.5)
        self.assertEqual(restored.product_type, "H")
        self.assertEqual(restored.product_counter, 8)
        self.assertEqual(restored.product_started_at, runtime.product_started_at)
        self.assertEqual(restored.rng.random(), runtime.rng.random())


if __name__ == "__main__":
    unittest.main()
