"""Closed-loop Runtime Overlay source-producer regression tests."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from line_worker import LineWorker
from physics_engine import Runtime, build_topology, make_baseline, stable_seed
from runtime_overlay import OverlayConflict, RuntimeOverlayCoordinator, StaleOverlayEvent


class RuntimeOverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        assets, _relations = build_topology()
        self.cnc_assets = [asset for asset in assets if asset["asset_type"] == "cnc"][:2]
        self.runtimes = {
            asset["asset_id"]: Runtime(
                asset=asset,
                rng=random.Random(stable_seed(42, asset["asset_id"], "overlay-test")),
                baseline=make_baseline(asset, 42),
            )
            for asset in self.cnc_assets
        }
        self.target = self.cnc_assets[0]
        self.other = self.cnc_assets[1]
        self.runtimes[self.target["asset_id"]].tool_wear_min = 123.4
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.output_root = Path(self.tempdir.name)
        self.started_at = datetime(2026, 8, 18, 1, 0, tzinfo=timezone.utc)
        self.completed_at = self.started_at + timedelta(minutes=30)
        self.restart_at = self.completed_at + timedelta(minutes=10)

    def coordinator(self) -> RuntimeOverlayCoordinator:
        return RuntimeOverlayCoordinator(
            assets=self.cnc_assets,
            canonical_runtimes=self.runtimes,
            interval_minutes=10,
            product_cycle_minutes=20,
            output_root=self.output_root,
            base_source_sha256="canonical-test-sha",
            generated_at=lambda: datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc),
        )

    def event(self, event_type: str, version: int, **extra: object) -> dict[str, object]:
        base: dict[str, object] = {
            "contract_version": "maintenance-replay-v1",
            "event_type": event_type,
            "event_id": f"EVT-{version}",
            "idempotency_key": f"MAINT-001:{version}",
            "state_version": version,
            "simulation_session_id": "DEMO-001",
            "maintenance_action_id": "ACTION-001",
            "equipment_id": self.target["asset_id"],
        }
        base.update(extra)
        return base

    def started(self) -> dict[str, object]:
        return self.event(
            "maintenance.started",
            1,
            work_order_id="WO-001",
            maintenance_started_at=self.started_at.isoformat(),
            action_code="TOOL_REPLACEMENT",
        )

    def completed(self) -> dict[str, object]:
        return self.event(
            "maintenance.completed",
            2,
            maintenance_event_id="MAINT-001",
            maintenance_completed_at=self.completed_at.isoformat(),
            action_code="TOOL_REPLACEMENT",
            state_patch={
                "tool_wear_min": {"operation": "reset", "value": 0, "unit": "min"}
            },
        )

    def replay_requested(self) -> dict[str, object]:
        return self.event(
            "maintenance.replay_requested",
            3,
            maintenance_event_id="MAINT-001",
            restart_at=self.restart_at.isoformat(),
        )

    def prepare_branch(self, coordinator: RuntimeOverlayCoordinator) -> None:
        coordinator.process_event(self.started())
        coordinator.process_event(self.completed())
        coordinator.process_event(self.replay_requested())

    def test_target_only_overlay_preserves_canonical_runtime(self) -> None:
        coordinator = self.coordinator()
        coordinator.process_event(self.started())

        self.assertFalse(
            coordinator.canonical_observation_allowed(self.target["asset_id"], self.started_at)
        )
        self.assertTrue(
            coordinator.canonical_observation_allowed(self.other["asset_id"], self.started_at)
        )

        coordinator.process_event(self.completed())
        branch = coordinator.branches[coordinator.branch_by_equipment[self.target["asset_id"]]]
        self.assertEqual(branch.runtime.tool_wear_min, 0.0)
        self.assertEqual(self.runtimes[self.target["asset_id"]].tool_wear_min, 123.4)

    def test_gap_has_no_observation_and_branch_fast_forward_is_local(self) -> None:
        coordinator = self.coordinator()
        coordinator.process_event(self.started())
        coordinator.process_event(self.completed())

        rows, available = coordinator.advance_branch_to(
            self.target["asset_id"], self.completed_at + timedelta(hours=1)
        )
        self.assertEqual(rows, [])
        self.assertIsNone(available)

        coordinator.process_event(self.replay_requested())
        rows, available = coordinator.advance_branch_to(
            self.target["asset_id"], self.restart_at + timedelta(minutes=20)
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [row["observed_at"] for row in rows],
            [
                self.restart_at.isoformat(),
                (self.restart_at + timedelta(minutes=10)).isoformat(),
                (self.restart_at + timedelta(minutes=20)).isoformat(),
            ],
        )
        self.assertTrue(all(row["source_kind"] == "maintenance_replay_overlay" for row in rows))
        self.assertTrue(all(row["maintenance_event_id"] == "MAINT-001" for row in rows))
        self.assertEqual(available["event_type"], "runtime_overlay.observations.available")
        self.assertNotIn("required_rows", available)
        self.assertNotIn("history_requirement", available)

    def test_event_idempotency_and_state_version_guards(self) -> None:
        coordinator = self.coordinator()
        first = coordinator.process_event(self.started())
        replayed = coordinator.process_event(self.started())
        self.assertFalse(first["replayed"])
        self.assertTrue(replayed["replayed"])

        conflict = self.started()
        conflict["work_order_id"] = "WO-DIFFERENT"
        with self.assertRaises(OverlayConflict):
            coordinator.process_event(conflict)

        coordinator.process_event(self.completed())
        stale = self.replay_requested()
        stale["state_version"] = 1
        stale["idempotency_key"] = "STALE-001"
        with self.assertRaises(StaleOverlayEvent):
            coordinator.process_event(stale)

    def test_checkpoint_resume_continues_without_duplicate_observations(self) -> None:
        coordinator = self.coordinator()
        self.prepare_branch(coordinator)
        first_rows, _available = coordinator.advance_branch_to(
            self.target["asset_id"], self.restart_at + timedelta(minutes=10)
        )
        self.assertEqual(len(first_rows), 2)

        resumed = self.coordinator()
        second_rows, available = resumed.advance_branch_to(
            self.target["asset_id"], self.restart_at + timedelta(minutes=20)
        )
        self.assertEqual(len(second_rows), 1)
        self.assertEqual(
            second_rows[0]["observed_at"],
            (self.restart_at + timedelta(minutes=20)).isoformat(),
        )
        self.assertEqual(available["generated_rows"], 3)

        branch = resumed.branches[resumed.branch_by_equipment[self.target["asset_id"]]]
        stored = resumed.store.path_for(branch).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(stored), 3)

    def test_restart_recovers_availability_event_after_checkpoint_crash_window(self) -> None:
        coordinator = self.coordinator()
        self.prepare_branch(coordinator)
        rows, available = coordinator.advance_branch_to(
            self.target["asset_id"], self.restart_at + timedelta(minutes=20)
        )
        self.assertEqual(len(rows), 3)
        self.assertIsNotNone(available)
        self.assertFalse(coordinator.available_event_path.exists())
        self.assertIn(available["event_id"], coordinator.pending_available_events)

        # Simulate process termination after observations/checkpoint are durable
        # but before daemon.persist_available_event() is called.
        resumed = self.coordinator()
        self.assertIn(available["event_id"], resumed.pending_available_events)
        self.assertEqual(resumed.recover_pending_available_events(), 1)
        self.assertEqual(resumed.pending_available_events, {})

        events = [
            json.loads(line)
            for line in resumed.available_event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], available["event_id"])
        self.assertEqual(events[0]["batch_rows"], 3)

        # A second restart must not append the same handoff again.
        second_restart = self.coordinator()
        self.assertEqual(second_restart.recover_pending_available_events(), 0)
        events_after_second_restart = [
            json.loads(line)
            for line in second_restart.available_event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(events_after_second_restart), 1)

    def test_availability_outbox_append_is_idempotent_by_event_id(self) -> None:
        coordinator = self.coordinator()
        self.prepare_branch(coordinator)
        _rows, available = coordinator.advance_branch_to(
            self.target["asset_id"], self.restart_at + timedelta(minutes=10)
        )
        self.assertIsNotNone(available)

        coordinator.persist_available_event(available)
        coordinator.persist_available_event(available)
        stored = [
            json.loads(line)
            for line in coordinator.available_event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(stored), 1)

        conflict = dict(available)
        conflict["batch_rows"] = int(conflict["batch_rows"]) + 1
        with self.assertRaises(OverlayConflict):
            coordinator.persist_available_event(conflict)

    def test_line_worker_filter_suppresses_only_target_equipment(self) -> None:
        coordinator = self.coordinator()
        coordinator.process_event(self.started())

        class CaptureAdapter:
            protocol_id = 1

            def __init__(self) -> None:
                self.values = None

            def encode_response(self, _unit_map, values):
                self.values = values
                return b"frame"

            def decode_response(self, _frame):
                return self.values

        adapter = CaptureAdapter()
        worker = LineWorker.__new__(LineWorker)
        worker.assets = self.cnc_assets
        worker.unit_map = {"1": self.target["asset_id"], "2": self.other["asset_id"]}
        worker.adapter = adapter
        worker.observation_allowed = coordinator.canonical_observation_allowed
        worker._compute_physics_value = lambda asset, _observed_at: {"asset": asset["asset_id"]}
        worker._current_raw_path = lambda _observed_at: self.output_root / "ignored.raw"
        worker._write_processed_layers = lambda _decoded, _observed_at: None

        with patch("line_worker.write_envelope"):
            worker.run_one_cycle(self.started_at)

        self.assertNotIn(self.target["asset_id"], adapter.values)
        self.assertIn(self.other["asset_id"], adapter.values)

        first_values = dict(adapter.values)
        worker.run_one_cycle(self.started_at)
        self.assertEqual(adapter.values, first_values)


if __name__ == "__main__":
    unittest.main()
