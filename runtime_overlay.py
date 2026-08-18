"""Target-equipment Runtime Overlay engine for Closed-loop maintenance replay.

This module intentionally does not consume a Model Artifact or decide whether
history is sufficient for inference.  It owns only source-side runtime state:

Closed-loop maintenance events -> target equipment snapshot/branch clock
-> append-only ``maintenance_replay_overlay`` observations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from line_worker import LineWorker
from physics_engine import Runtime


SOURCE_KIND = "maintenance_replay_overlay"
CHECKPOINT_VERSION = 1


class OverlayContractError(ValueError):
    """Raised when a maintenance event violates the Runtime Overlay contract."""


class OverlayConflict(OverlayContractError):
    """Raised when an idempotency/version key is reused with different data."""


class StaleOverlayEvent(OverlayContractError):
    """Raised when an older state_version arrives after a newer state."""


def _parse_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise OverlayContractError(f"{field} must be an ISO-8601 timestamp")
    if result.tzinfo is None:
        raise OverlayContractError(f"{field} must include timezone information")
    return result


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _semantic_observation_hash(payload: dict[str, Any]) -> str:
    semantic = {key: value for key, value in payload.items() if key not in {"generated_at", "observation_sha256"}}
    return _payload_hash(semantic)


def _json_safe_random_state(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe_random_state(item) for item in value]
    if isinstance(value, list):
        return [_json_safe_random_state(item) for item in value]
    return value


def _tuple_random_state(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuple_random_state(item) for item in value)
    return value


def _runtime_checkpoint(runtime: Runtime) -> dict[str, Any]:
    def timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    return {
        "baseline": dict(runtime.baseline),
        "noise_state": dict(runtime.noise_state),
        "tool_wear_min": runtime.tool_wear_min,
        "tool_change_threshold_min": runtime.tool_change_threshold_min,
        "product_started_at": timestamp(runtime.product_started_at),
        "product_type": runtime.product_type,
        "product_ticks": runtime.product_ticks,
        "product_counter": runtime.product_counter,
        "planned_maintenance_until": timestamp(runtime.planned_maintenance_until),
        "tool_reset_at": timestamp(runtime.tool_reset_at),
        "rng_state": _json_safe_random_state(runtime.rng.getstate()),
    }


def _restore_runtime(asset: dict[str, str], payload: dict[str, Any]) -> Runtime:
    rng = random.Random()
    rng.setstate(_tuple_random_state(payload["rng_state"]))

    def timestamp(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    return Runtime(
        asset=asset,
        rng=rng,
        baseline={key: float(value) for key, value in payload["baseline"].items()},
        noise_state={key: float(value) for key, value in payload.get("noise_state", {}).items()},
        tool_wear_min=float(payload.get("tool_wear_min", 0.0)),
        tool_change_threshold_min=float(payload.get("tool_change_threshold_min", 210.0)),
        product_started_at=timestamp(payload.get("product_started_at")),
        product_type=str(payload.get("product_type", "L")),
        product_ticks=int(payload.get("product_ticks", 0)),
        product_counter=int(payload.get("product_counter", 0)),
        planned_maintenance_until=timestamp(payload.get("planned_maintenance_until")),
        tool_reset_at=timestamp(payload.get("tool_reset_at")),
    )


@dataclass
class OverlayBranch:
    simulation_session_id: str
    equipment_id: str
    maintenance_action_id: str
    action_code: str
    maintenance_started_at: datetime
    runtime: Runtime
    state_version: int
    phase: str = "maintenance"
    maintenance_event_id: str | None = None
    maintenance_completed_at: datetime | None = None
    restart_at: datetime | None = None
    overlay_branch_id: str | None = None
    history_segment_id: str | None = None
    next_observed_at: datetime | None = None
    generated_rows: int = 0

    @property
    def key(self) -> str:
        return ":".join(
            (self.simulation_session_id, self.equipment_id, self.maintenance_action_id)
        )


class OverlayObservationStore:
    """Append-only JSONL store with semantic replay/conflict detection."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._index: dict[Path, dict[str, str]] = {}

    @staticmethod
    def _safe(value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)

    def path_for(self, branch: OverlayBranch) -> Path:
        if not branch.overlay_branch_id:
            raise OverlayContractError("overlay_branch_id is required before writing observations")
        session = self._safe(branch.simulation_session_id)
        branch_name = self._safe(branch.overlay_branch_id)
        path = self.root / session / f"{branch_name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_index(self, path: Path) -> dict[str, str]:
        if path in self._index:
            return self._index[path]
        index: dict[str, str] = {}
        if path.exists():
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                row = json.loads(raw_line)
                index[str(row["observation_id"])] = str(row["observation_sha256"])
        self._index[path] = index
        return index

    def append(self, branch: OverlayBranch, observation: dict[str, Any]) -> bool:
        path = self.path_for(branch)
        index = self._load_index(path)
        observation_id = str(observation["observation_id"])
        semantic_hash = _semantic_observation_hash(observation)
        existing = index.get(observation_id)
        if existing is not None:
            if existing != semantic_hash:
                raise OverlayConflict(f"observation identity conflict: {observation_id}")
            return False
        observation["observation_sha256"] = semantic_hash
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(observation, ensure_ascii=False, sort_keys=True) + "\n")
        index[observation_id] = semantic_hash
        return True


class RuntimeOverlayCoordinator:
    """Owns opt-in post-maintenance branches without mutating Canonical runtimes."""

    def __init__(
        self,
        *,
        assets: list[dict[str, str]],
        canonical_runtimes: dict[str, Runtime],
        interval_minutes: int,
        product_cycle_minutes: int,
        output_root: Path,
        base_dataset_version: str = "predictive-maintenance-canonical-v3.1",
        base_source_sha256: str = "unavailable",
        generated_at: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_minutes <= 0:
            raise ValueError("interval_minutes must be positive")
        self.assets = {str(asset["asset_id"]): asset for asset in assets}
        self.canonical_runtimes = canonical_runtimes
        self.interval = timedelta(minutes=interval_minutes)
        self.worker_config = SimpleNamespace(
            GEN_DATA_INTERVAL_MINUTES=interval_minutes,
            GEN_DATA_PRODUCT_CYCLE_MINUTES=product_cycle_minutes,
        )
        self.base_dataset_version = base_dataset_version
        self.base_source_sha256 = base_source_sha256
        self.generated_at = generated_at or (lambda: datetime.now(timezone.utc))
        self.store = OverlayObservationStore(output_root / "runtime_overlay")
        self.checkpoint_path = output_root / "runtime_overlay" / "runtime_overlay_state.json"
        self.available_event_path = (
            output_root / "runtime_overlay" / "observations_available.jsonl"
        )
        self.branches: dict[str, OverlayBranch] = {}
        self.branch_by_equipment: dict[str, str] = {}
        self.processed_events: dict[str, str] = {}
        self.pending_available_events: dict[str, dict[str, Any]] = {}
        self._available_event_index: dict[str, str] | None = None
        self._restore_checkpoint()

    @property
    def active_equipment_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.branch_by_equipment))

    def _checkpoint(self) -> None:
        branches: dict[str, Any] = {}
        for key, branch in self.branches.items():
            branches[key] = {
                "simulation_session_id": branch.simulation_session_id,
                "equipment_id": branch.equipment_id,
                "maintenance_action_id": branch.maintenance_action_id,
                "action_code": branch.action_code,
                "maintenance_started_at": branch.maintenance_started_at.isoformat(),
                "state_version": branch.state_version,
                "phase": branch.phase,
                "maintenance_event_id": branch.maintenance_event_id,
                "maintenance_completed_at": branch.maintenance_completed_at.isoformat()
                if branch.maintenance_completed_at
                else None,
                "restart_at": branch.restart_at.isoformat() if branch.restart_at else None,
                "overlay_branch_id": branch.overlay_branch_id,
                "history_segment_id": branch.history_segment_id,
                "next_observed_at": branch.next_observed_at.isoformat()
                if branch.next_observed_at
                else None,
                "generated_rows": branch.generated_rows,
                "runtime": _runtime_checkpoint(branch.runtime),
            }
        payload = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "processed_events": self.processed_events,
            "pending_available_events": self.pending_available_events,
            "branches": branches,
        }
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.checkpoint_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.checkpoint_path)

    def _restore_checkpoint(self) -> None:
        if not self.checkpoint_path.exists():
            return
        payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if int(payload.get("checkpoint_version", 0)) != CHECKPOINT_VERSION:
            raise OverlayContractError("unsupported Runtime Overlay checkpoint version")
        self.processed_events = {
            str(key): str(value) for key, value in payload.get("processed_events", {}).items()
        }
        pending = payload.get("pending_available_events", {})
        if not isinstance(pending, dict):
            raise OverlayContractError("pending_available_events must be an object")
        self.pending_available_events = {
            str(event_id): dict(event)
            for event_id, event in pending.items()
            if isinstance(event, dict)
        }
        for key, item in payload.get("branches", {}).items():
            equipment_id = str(item["equipment_id"])
            asset = self.assets.get(equipment_id)
            if asset is None:
                raise OverlayContractError(f"checkpoint references unknown equipment: {equipment_id}")
            branch = OverlayBranch(
                simulation_session_id=str(item["simulation_session_id"]),
                equipment_id=equipment_id,
                maintenance_action_id=str(item["maintenance_action_id"]),
                action_code=str(item["action_code"]),
                maintenance_started_at=_parse_datetime(item["maintenance_started_at"], "maintenance_started_at"),
                runtime=_restore_runtime(asset, item["runtime"]),
                state_version=int(item["state_version"]),
                phase=str(item["phase"]),
                maintenance_event_id=item.get("maintenance_event_id"),
                maintenance_completed_at=_parse_datetime(
                    item["maintenance_completed_at"], "maintenance_completed_at"
                )
                if item.get("maintenance_completed_at")
                else None,
                restart_at=_parse_datetime(item["restart_at"], "restart_at")
                if item.get("restart_at")
                else None,
                overlay_branch_id=item.get("overlay_branch_id"),
                history_segment_id=item.get("history_segment_id"),
                next_observed_at=_parse_datetime(item["next_observed_at"], "next_observed_at")
                if item.get("next_observed_at")
                else None,
                generated_rows=int(item.get("generated_rows", 0)),
            )
            self.branches[str(key)] = branch
            self.branch_by_equipment[equipment_id] = str(key)

    @staticmethod
    def _required(event: dict[str, Any], *fields: str) -> None:
        missing = [field for field in fields if event.get(field) in (None, "")]
        if missing:
            raise OverlayContractError("missing required field(s): " + ", ".join(missing))

    def _event_replay(self, event: dict[str, Any]) -> bool:
        self._required(event, "idempotency_key")
        key = str(event["idempotency_key"])
        digest = _payload_hash(event)
        existing = self.processed_events.get(key)
        if existing is None:
            return False
        if existing != digest:
            raise OverlayConflict(f"idempotency_key_conflict: {key}")
        return True

    def _record_event(self, event: dict[str, Any]) -> None:
        self.processed_events[str(event["idempotency_key"])] = _payload_hash(event)
        self._checkpoint()

    def _branch_for_event(self, event: dict[str, Any]) -> OverlayBranch:
        key = ":".join(
            (
                str(event["simulation_session_id"]),
                str(event["equipment_id"]),
                str(event["maintenance_action_id"]),
            )
        )
        branch = self.branches.get(key)
        if branch is None:
            raise OverlayContractError(f"maintenance.started branch not found: {key}")
        return branch

    @staticmethod
    def _assert_newer_version(branch: OverlayBranch, event: dict[str, Any]) -> int:
        version = int(event["state_version"])
        if version < branch.state_version:
            raise StaleOverlayEvent(
                f"stale state_version {version}; current={branch.state_version}"
            )
        if version == branch.state_version:
            raise OverlayConflict(f"state_version_conflict: {version}")
        return version

    def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Apply one Closed-loop maintenance event to source-side overlay state."""
        self._required(
            event,
            "event_type",
            "event_id",
            "idempotency_key",
            "state_version",
            "simulation_session_id",
            "maintenance_action_id",
            "equipment_id",
        )
        event_type = str(event["event_type"])
        if event_type not in {
            "maintenance.started",
            "maintenance.completed",
            "maintenance.replay_requested",
        }:
            raise OverlayContractError(f"unsupported maintenance event: {event_type}")
        equipment_id = str(event["equipment_id"])
        if equipment_id not in self.assets or equipment_id not in self.canonical_runtimes:
            raise OverlayContractError(f"unknown equipment_id: {equipment_id}")
        if self._event_replay(event):
            branch = self._branch_for_event(event)
            return {"replayed": True, "phase": branch.phase, "state_version": branch.state_version}

        if event_type == "maintenance.started":
            self._required(event, "maintenance_started_at", "work_order_id", "action_code")
            key = ":".join(
                (
                    str(event["simulation_session_id"]),
                    equipment_id,
                    str(event["maintenance_action_id"]),
                )
            )
            if key in self.branches:
                raise OverlayConflict(f"maintenance branch already exists: {key}")
            if equipment_id in self.branch_by_equipment:
                raise OverlayConflict(f"equipment already has an active overlay branch: {equipment_id}")
            branch = OverlayBranch(
                simulation_session_id=str(event["simulation_session_id"]),
                equipment_id=equipment_id,
                maintenance_action_id=str(event["maintenance_action_id"]),
                action_code=str(event["action_code"]),
                maintenance_started_at=_parse_datetime(
                    event["maintenance_started_at"], "maintenance_started_at"
                ),
                runtime=copy.deepcopy(self.canonical_runtimes[equipment_id]),
                state_version=int(event["state_version"]),
            )
            self.branches[key] = branch
            self.branch_by_equipment[equipment_id] = key
        else:
            branch = self._branch_for_event(event)
            version = self._assert_newer_version(branch, event)
            if event_type == "maintenance.completed":
                self._required(
                    event,
                    "maintenance_event_id",
                    "maintenance_completed_at",
                    "action_code",
                    "state_patch",
                )
                if branch.phase != "maintenance":
                    raise OverlayContractError("maintenance.completed requires maintenance phase")
                completed_at = _parse_datetime(
                    event["maintenance_completed_at"], "maintenance_completed_at"
                )
                if completed_at < branch.maintenance_started_at:
                    raise OverlayContractError(
                        "maintenance_completed_at must be >= maintenance_started_at"
                    )
                self._apply_state_patch(branch, event)
                branch.maintenance_event_id = str(event["maintenance_event_id"])
                branch.maintenance_completed_at = completed_at
                branch.phase = "completed"
                branch.state_version = version
            else:
                self._required(event, "maintenance_event_id", "restart_at")
                if branch.phase != "completed" or branch.maintenance_completed_at is None:
                    raise OverlayContractError(
                        "maintenance.replay_requested requires completed maintenance"
                    )
                if str(event["maintenance_event_id"]) != branch.maintenance_event_id:
                    raise OverlayContractError("maintenance_event_id does not match completed branch")
                restart_at = _parse_datetime(event["restart_at"], "restart_at")
                if restart_at < branch.maintenance_completed_at:
                    raise OverlayContractError(
                        "restart_at must be >= maintenance_completed_at"
                    )
                branch.restart_at = restart_at
                branch.overlay_branch_id = f"{branch.maintenance_event_id}:post"
                branch.history_segment_id = f"{branch.maintenance_event_id}:post"
                branch.next_observed_at = restart_at
                branch.phase = "restarting"
                branch.state_version = version

        self._record_event(event)
        return {"replayed": False, "phase": branch.phase, "state_version": branch.state_version}

    @staticmethod
    def _apply_state_patch(branch: OverlayBranch, event: dict[str, Any]) -> None:
        action_code = str(event["action_code"])
        if action_code != branch.action_code:
            raise OverlayContractError("action_code does not match maintenance.started")
        if action_code != "TOOL_REPLACEMENT":
            raise OverlayContractError(f"unsupported MVP action_code: {action_code}")
        expected = {
            "tool_wear_min": {
                "operation": "reset",
                "value": 0,
                "unit": "min",
            }
        }
        if event["state_patch"] != expected:
            raise OverlayContractError(
                "TOOL_REPLACEMENT requires tool_wear_min reset -> 0 min"
            )
        if str(branch.runtime.asset.get("asset_type")) != "cnc":
            raise OverlayContractError("TOOL_REPLACEMENT is only valid for CNC equipment")
        branch.runtime.tool_wear_min = 0.0
        branch.runtime.tool_reset_at = None
        branch.runtime.planned_maintenance_until = None

    def canonical_observation_allowed(self, equipment_id: str, observed_at: datetime) -> bool:
        """Return false once a target equipment enters maintenance/overlay ownership."""
        key = self.branch_by_equipment.get(equipment_id)
        if key is None:
            return True
        branch = self.branches[key]
        return observed_at < branch.maintenance_started_at

    def _overlay_worker(self, branch: OverlayBranch) -> LineWorker:
        worker = LineWorker.__new__(LineWorker)
        worker.runtimes = {branch.equipment_id: branch.runtime}
        worker.episodes_by_asset = {branch.equipment_id: []}
        worker.config = self.worker_config
        return worker

    def advance_branch_to(
        self, equipment_id: str, target_virtual_time: datetime
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Fast-forward one target branch without sleeping or moving the global clock.

        ``target_virtual_time`` is a source-runtime clock boundary, not a Model
        Artifact/history requirement.  Backend remains the sole inference-readiness
        owner and may consume every available batch independently.
        """
        key = self.branch_by_equipment.get(equipment_id)
        if key is None:
            raise OverlayContractError(f"no overlay branch for equipment: {equipment_id}")
        branch = self.branches[key]
        if branch.phase not in {"restarting", "running"} or branch.next_observed_at is None:
            return [], None
        if target_virtual_time.tzinfo is None:
            raise OverlayContractError("target_virtual_time must include timezone information")

        worker = self._overlay_worker(branch)
        asset = self.assets[equipment_id]
        written: list[dict[str, Any]] = []
        while branch.next_observed_at <= target_virtual_time:
            observed_at = branch.next_observed_at
            values = worker._compute_physics_value(asset, observed_at)
            observation_id = f"OVERLAY:{branch.overlay_branch_id}:{observed_at.isoformat()}"
            observation: dict[str, Any] = {
                "observation_id": observation_id,
                "equipment_id": equipment_id,
                "asset_id": equipment_id,
                "asset_type": asset["asset_type"],
                "site_id": asset["site_id"],
                "cell_id": asset["cell_id"],
                "observed_at": observed_at.isoformat(),
                "generated_at": self.generated_at().isoformat(),
                "source_kind": SOURCE_KIND,
                "base_dataset_version": self.base_dataset_version,
                "base_source_sha256": self.base_source_sha256,
                "simulation_session_id": branch.simulation_session_id,
                "overlay_branch_id": branch.overlay_branch_id,
                "maintenance_event_id": branch.maintenance_event_id,
                "maintenance_action_id": branch.maintenance_action_id,
                "state_version": branch.state_version,
                "history_segment_id": branch.history_segment_id,
                **values,
            }
            if self.store.append(branch, observation):
                written.append(observation)
                branch.generated_rows += 1
            branch.next_observed_at = observed_at + self.interval
        if written:
            branch.phase = "running"
            available = self._available_event(branch, written)
            self.pending_available_events[str(available["event_id"])] = available
            self._checkpoint()
            return written, available
        return [], None

    def _available_event(
        self, branch: OverlayBranch, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        path = self.store.path_for(branch)
        return {
            "contract_version": "runtime-overlay-observation-v1-preview",
            "event_type": "runtime_overlay.observations.available",
            "event_id": f"OVERLAY-AVAILABLE:{branch.overlay_branch_id}:{branch.generated_rows}",
            "simulation_session_id": branch.simulation_session_id,
            "equipment_id": branch.equipment_id,
            "maintenance_action_id": branch.maintenance_action_id,
            "maintenance_event_id": branch.maintenance_event_id,
            "overlay_branch_id": branch.overlay_branch_id,
            "history_segment_id": branch.history_segment_id,
            "source_kind": SOURCE_KIND,
            "state_version": branch.state_version,
            "batch_rows": len(rows),
            "generated_rows": branch.generated_rows,
            "observed_from": rows[0]["observed_at"],
            "observed_to": rows[-1]["observed_at"],
            "storage_reference": str(path),
        }

    def persist_available_event(self, event: dict[str, Any]) -> None:
        """Append one source-side availability notification for Backend adapters.

        This JSONL file is an opt-in demo transport only.  The event meaning is
        deliberately ``available`` rather than ``ready``: gen_data does not know
        or evaluate Model Artifact history requirements.

        The append is idempotent by ``event_id``.  ``advance_branch_to`` stores
        the event in the Runtime Overlay checkpoint before returning it, so a
        daemon crash between observation persistence and this outbox append can
        be recovered on restart without losing or duplicating the handoff.
        """
        event_id = str(event.get("event_id") or "")
        if not event_id:
            raise OverlayContractError("availability event_id is required")
        digest = _payload_hash(event)
        index = self._load_available_event_index()
        existing = index.get(event_id)
        if existing is not None and existing != digest:
            raise OverlayConflict(f"availability event identity conflict: {event_id}")

        self.available_event_path.parent.mkdir(parents=True, exist_ok=True)
        if existing is None:
            with self.available_event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            index[event_id] = digest

        if event_id in self.pending_available_events:
            del self.pending_available_events[event_id]
            self._checkpoint()

    def _load_available_event_index(self) -> dict[str, str]:
        if self._available_event_index is not None:
            return self._available_event_index
        index: dict[str, str] = {}
        if self.available_event_path.exists():
            for raw_line in self.available_event_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line)
                event_id = str(event.get("event_id") or "")
                if not event_id:
                    raise OverlayContractError("stored availability event is missing event_id")
                digest = _payload_hash(event)
                existing = index.get(event_id)
                if existing is not None and existing != digest:
                    raise OverlayConflict(
                        f"stored availability event identity conflict: {event_id}"
                    )
                index[event_id] = digest
        self._available_event_index = index
        return index

    def recover_pending_available_events(self) -> int:
        """Replay checkpointed availability events into the idempotent outbox."""
        recovered = 0
        for event_id in list(self.pending_available_events):
            event = self.pending_available_events[event_id]
            self.persist_available_event(event)
            recovered += 1
        return recovered
