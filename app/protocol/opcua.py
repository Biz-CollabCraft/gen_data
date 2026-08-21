"""OPC UA SDK publisher and configured-node collector.

This module publishes DataValue objects to an asyncua Server address space. It
also provides the inverse source boundary used for real/test OPC UA Server
subscriptions. Neither direction claims to capture OPC UA wire packets.
"""

from __future__ import annotations

import json
import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from asyncua import ua
from asyncua.sync import Client, Server

from app.observation.models import SENSOR_RECORD_SCHEMA_VERSION, SensorRecord


ASSET_ID_PATTERN = re.compile(
    r"^(?P<prefix>CNC|CMP)-(?P<site>S\d{2})-(?P<line>L\d{2})-(?P<ordinal>\d{2})$"
)
ASSET_TYPE_BY_PREFIX = {
    "CNC": "cnc",
    "CMP": "compressor",
}


@dataclass(frozen=True)
class NodeMapping:
    node_id_template: str
    data_type: str
    unit: str


@dataclass(frozen=True)
class ResolvedNode:
    node_id: str
    asset_id: str
    asset_type: str
    measurement_key: str
    mapping: NodeMapping


@dataclass(frozen=True)
class OpcUaMapping:
    mapping_version: str
    namespace_uri: str
    nodes: dict[str, NodeMapping]

    @classmethod
    def load(cls, path: Path) -> "OpcUaMapping":
        payload = json.loads(path.read_text(encoding="utf-8"))
        nodes = {
            key: NodeMapping(
                node_id_template=str(value["node_id"]),
                data_type=str(value["data_type"]),
                unit=str(value["unit"]),
            )
            for key, value in payload["nodes"].items()
        }
        return cls(
            mapping_version=str(payload["mapping_version"]),
            namespace_uri=str(payload["namespace_uri"]),
            nodes=nodes,
        )

    def resolve(self, record: SensorRecord, measurement_key: str) -> NodeMapping | None:
        return self.nodes.get(f"{record.asset_type}.{measurement_key}")

    def reverse_resolve(self, node_id: str) -> ResolvedNode | None:
        candidates: list[ResolvedNode] = []
        for logical_key, mapping in self.nodes.items():
            if "{asset_id}" not in mapping.node_id_template:
                continue
            prefix, suffix = mapping.node_id_template.split("{asset_id}", 1)
            if not node_id.startswith(prefix) or not node_id.endswith(suffix):
                continue
            end = len(node_id) - len(suffix) if suffix else len(node_id)
            asset_id = node_id[len(prefix) : end]
            if not asset_id:
                continue
            asset_type, measurement_key = logical_key.split(".", 1)
            asset_identity = _asset_identity_from_id(asset_id)
            if asset_identity is None or asset_identity[0] != asset_type:
                continue
            candidates.append(
                ResolvedNode(
                    node_id=node_id,
                    asset_id=asset_id,
                    asset_type=asset_type,
                    measurement_key=measurement_key,
                    mapping=mapping,
                )
            )
        if len(candidates) == 1:
            return candidates[0]
        return None


VARIANT_TYPES = {
    "Boolean": ua.VariantType.Boolean,
    "Double": ua.VariantType.Double,
    "Int64": ua.VariantType.Int64,
    "String": ua.VariantType.String,
}


class OpcUaPublisher:
    """Own one local/test OPC UA Server and publish mapped DataValues to it."""

    def __init__(
        self,
        *,
        endpoint: str,
        mapping: OpcUaMapping,
        server_name: str = "gen_data simulation source",
    ) -> None:
        self.endpoint = endpoint
        self.mapping = mapping
        self.server_name = server_name
        self._server: Server | None = None
        self._namespace_index: int | None = None
        self._asset_nodes: dict[str, Any] = {}
        self._variables: dict[str, Any] = {}
        self._started = False

    @property
    def namespace_index(self) -> int | None:
        return self._namespace_index

    def start(self) -> None:
        if self._started:
            return
        server = Server()
        server.set_endpoint(self.endpoint)
        server.set_server_name(self.server_name)
        namespace_index = server.register_namespace(self.mapping.namespace_uri)
        self._server = server
        self._namespace_index = namespace_index
        server.start()
        self._started = True

    def stop(self) -> None:
        if not self._server:
            return
        if self._started:
            self._server.stop()
        self._started = False
        self._variables.clear()
        self._asset_nodes.clear()
        self._server = None
        self._namespace_index = None

    def publish(self, record: SensorRecord) -> list[dict[str, Any]]:
        if not self._started or self._server is None or self._namespace_index is None:
            raise RuntimeError("OPC UA publisher is not started")
        published: list[dict[str, Any]] = []
        for measurement_key, value in record.measurements.items():
            mapping = self.mapping.resolve(record, measurement_key)
            if mapping is None:
                continue
            variant_type = VARIANT_TYPES.get(mapping.data_type)
            if variant_type is None:
                raise ValueError(f"unsupported OPC UA data type: {mapping.data_type}")
            node_id = mapping.node_id_template.format(asset_id=record.asset_id)
            variable = self._ensure_variable(
                record=record,
                measurement_key=measurement_key,
                node_id=node_id,
                variant_type=variant_type,
                initial_value=value,
                unit=mapping.unit,
            )
            protocol_value = bool(value) if mapping.data_type == "Boolean" else value
            data_value = ua.DataValue(
                ua.Variant(protocol_value, variant_type),
                StatusCode_=ua.StatusCode(ua.StatusCodes.Good),
                SourceTimestamp=record.observed_at,
            )
            variable.write_value(data_value)
            published_at = datetime.now(tz=timezone.utc)
            published.append(
                {
                    "direction": "published",
                    "schema_version": record.schema_version,
                    "observation_id": record.observation_id,
                    "source_kind": record.source_kind,
                    "run_id": record.run_id,
                    "sequence": record.sequence,
                    "asset_id": record.asset_id,
                    "measurement_key": measurement_key,
                    "node_id": node_id,
                    "data_type": mapping.data_type,
                    "unit": mapping.unit,
                    "value": protocol_value,
                    "status_code": "Good",
                    "source_timestamp": record.observed_at.isoformat(timespec="seconds"),
                    "observed_at_source": record.observed_at_source,
                    "branch_kind": record.branch_kind,
                    "overlay": record.overlay,
                    "published_at": published_at.isoformat(timespec="seconds"),
                    "mapping_version": self.mapping.mapping_version,
                }
            )
        return published

    def get_node(self, node_id: str):
        if not self._server:
            raise RuntimeError("OPC UA publisher is not started")
        return self._server.get_node(node_id)

    def _ensure_variable(
        self,
        *,
        record: SensorRecord,
        measurement_key: str,
        node_id: str,
        variant_type: ua.VariantType,
        initial_value: Any,
        unit: str,
    ):
        existing = self._variables.get(node_id)
        if existing is not None:
            return existing
        if self._server is None or self._namespace_index is None:
            raise RuntimeError("OPC UA publisher is not started")
        asset_node = self._asset_nodes.get(record.asset_id)
        if asset_node is None:
            asset_node = self._server.nodes.objects.add_object(
                self._namespace_index,
                record.asset_id,
            )
            self._asset_nodes[record.asset_id] = asset_node
        protocol_value = bool(initial_value) if variant_type == ua.VariantType.Boolean else initial_value
        variable = asset_node.add_variable(
            ua.NodeId.from_string(node_id),
            measurement_key,
            protocol_value,
            varianttype=variant_type,
        )
        variable.add_property(
            self._namespace_index,
            "engineering_unit",
            unit,
            varianttype=ua.VariantType.String,
        )
        self._variables[node_id] = variable
        return variable


class OpcUaCollector:
    """Subscribe to configured OPC UA nodes and normalize DataValues.

    This is intentionally a small source adapter rather than a generic OPC UA
    gateway: nodes are explicit, mapping is versioned, reconnect recreates the
    subscription, and duplicate notifications are suppressed in-process.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        mapping: OpcUaMapping,
        run_id: str,
        node_ids: list[str],
        on_record: Callable[[SensorRecord], None],
        on_provenance: Callable[[dict[str, Any]], None],
        on_quarantine: Callable[[dict[str, Any]], None],
        on_error: Callable[[dict[str, Any]], None],
        publishing_interval_ms: float = 250.0,
        reconnect_seconds: float = 1.0,
        dedup_capacity: int = 10_000,
    ) -> None:
        if not node_ids:
            raise ValueError("at least one OPC UA node_id is required")
        self.endpoint = endpoint
        self.mapping = mapping
        self.run_id = run_id
        self.node_ids = list(dict.fromkeys(node_ids))
        self.on_record = on_record
        self.on_provenance = on_provenance
        self.on_quarantine = on_quarantine
        self.on_error = on_error
        self.publishing_interval_ms = publishing_interval_ms
        self.reconnect_seconds = reconnect_seconds
        self.dedup_capacity = max(1, dedup_capacity)
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._dedup_order: deque[tuple[Any, ...]] = deque()
        self._dedup_keys: set[tuple[Any, ...]] = set()

    @property
    def sequence(self) -> int:
        return self._sequence

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            client: Client | None = None
            subscription = None
            try:
                client = Client(self.endpoint)
                client.connect()
                subscription = client.create_subscription(self.publishing_interval_ms, self)
                nodes = []
                for node_id in self.node_ids:
                    resolved = self.mapping.reverse_resolve(node_id)
                    if resolved is None:
                        self._quarantine(node_id, "unknown_or_ambiguous_node")
                        continue
                    node = client.get_node(node_id)
                    if self._validate_configured_node(node, resolved):
                        nodes.append(node)
                if not nodes:
                    raise RuntimeError("no valid OPC UA nodes remain after mapping validation")
                handles = subscription.subscribe_data_change(nodes, queuesize=1)
                if isinstance(handles, list):
                    for node, handle in zip(nodes, handles):
                        if isinstance(handle, ua.StatusCode) and not handle.is_good():
                            self._quarantine(node.nodeid.to_string(), f"subscription_failed:{handle.name}")
                while not stop_event.wait(0.25):
                    client.check_connection()
            except Exception as exc:
                if not stop_event.is_set():
                    self.on_error(
                        {
                            "stage": "opcua_subscription",
                            "endpoint": self.endpoint,
                            "error": f"{type(exc).__name__}: {exc}",
                            "recorded_at": _iso(datetime.now(tz=timezone.utc)),
                        }
                    )
                    stop_event.wait(self.reconnect_seconds)
            finally:
                if subscription is not None:
                    try:
                        subscription.delete()
                    except Exception:
                        pass
                if client is not None:
                    try:
                        client.disconnect()
                    except Exception:
                        pass

    def datachange_notification(self, node, value: Any, data) -> None:
        node_id = node.nodeid.to_string()
        resolved = self.mapping.reverse_resolve(node_id)
        if resolved is None:
            self._quarantine(node_id, "unknown_or_ambiguous_node", value=value)
            return
        data_value = data.monitored_item.Value
        actual_type = data_value.Value.VariantType
        expected_type = VARIANT_TYPES.get(resolved.mapping.data_type)
        if expected_type is None or actual_type != expected_type:
            self._quarantine(
                node_id,
                "invalid_data_type",
                value=value,
                expected_data_type=resolved.mapping.data_type,
                actual_data_type=getattr(actual_type, "name", str(actual_type)),
            )
            return
        received_at = datetime.now(tz=timezone.utc)
        source_timestamp = _aware_utc(data_value.SourceTimestamp)
        server_timestamp = _aware_utc(data_value.ServerTimestamp)
        observed_at = source_timestamp or server_timestamp or received_at
        observed_at_source = (
            "source" if source_timestamp else "server" if server_timestamp else "received"
        )
        status = data_value.StatusCode_
        dedup_key = (
            node_id,
            _iso(source_timestamp or server_timestamp),
            repr(value),
            status.value,
        )
        if self._is_duplicate(dedup_key):
            return
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        site_id, cell_id = _location_from_asset_id(resolved.asset_id)
        record = SensorRecord(
            schema_version=SENSOR_RECORD_SCHEMA_VERSION,
            run_id=self.run_id,
            sequence=sequence,
            asset_id=resolved.asset_id,
            observed_at=observed_at,
            measurements={resolved.measurement_key: value},
            generator_version="opcua-source-v1",
            asset_type=resolved.asset_type,
            site_id=site_id,
            cell_id=cell_id,
            source_kind="opcua",
            observed_at_source=observed_at_source,
        )
        self.on_record(record)
        self.on_provenance(
            {
                "direction": "received",
                "schema_version": record.schema_version,
                "observation_id": record.observation_id,
                "source_kind": "opcua",
                "run_id": self.run_id,
                "sequence": sequence,
                "asset_id": resolved.asset_id,
                "measurement_key": resolved.measurement_key,
                "node_id": node_id,
                "data_type": actual_type.name,
                "unit": resolved.mapping.unit,
                "value": value,
                "status_code": status.name,
                "status_code_value": status.value,
                "source_timestamp": _iso(source_timestamp),
                "server_timestamp": _iso(server_timestamp),
                "received_at": _iso(received_at),
                "observed_at_source": observed_at_source,
                "branch_kind": record.branch_kind,
                "overlay": record.overlay,
                "mapping_version": self.mapping.mapping_version,
            }
        )

    def status_change_notification(self, status) -> None:
        if not status.Status.is_good():
            self.on_error(
                {
                    "stage": "opcua_subscription_status",
                    "endpoint": self.endpoint,
                    "status_code": status.Status.name,
                    "recorded_at": _iso(datetime.now(tz=timezone.utc)),
                }
            )

    def _validate_configured_node(self, node, resolved: ResolvedNode) -> bool:
        expected_type = VARIANT_TYPES.get(resolved.mapping.data_type)
        try:
            actual_type = node.read_data_type_as_variant_type()
        except Exception as exc:
            self._quarantine(resolved.node_id, f"data_type_read_failed:{type(exc).__name__}")
            return False
        if expected_type is None or actual_type != expected_type:
            self._quarantine(
                resolved.node_id,
                "invalid_data_type",
                expected_data_type=resolved.mapping.data_type,
                actual_data_type=getattr(actual_type, "name", str(actual_type)),
            )
            return False
        try:
            for prop in node.get_properties():
                browse_name = prop.read_browse_name().Name
                if browse_name not in {"engineering_unit", "EngineeringUnits"}:
                    continue
                unit_value = prop.read_value()
                if isinstance(unit_value, str) and unit_value != resolved.mapping.unit:
                    self._quarantine(
                        resolved.node_id,
                        "invalid_unit",
                        expected_unit=resolved.mapping.unit,
                        actual_unit=unit_value,
                    )
                    return False
        except Exception:
            # EngineeringUnits is optional in the small adapter. If exposed, it
            # is validated; a server that does not expose it is still usable.
            pass
        return True

    def _quarantine(self, node_id: str, reason: str, **extra: Any) -> None:
        payload = {
            "run_id": self.run_id,
            "node_id": node_id,
            "reason": reason,
            "received_at": _iso(datetime.now(tz=timezone.utc)),
            "mapping_version": self.mapping.mapping_version,
            **extra,
        }
        self.on_quarantine(payload)

    def _is_duplicate(self, key: tuple[Any, ...]) -> bool:
        if key in self._dedup_keys:
            return True
        self._dedup_keys.add(key)
        self._dedup_order.append(key)
        while len(self._dedup_order) > self.dedup_capacity:
            old = self._dedup_order.popleft()
            self._dedup_keys.discard(old)
        return False


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def _asset_identity_from_id(asset_id: str) -> tuple[str, str, str] | None:
    """Parse the repository's explicit CNC/compressor asset naming contract.

    Collector input is intentionally limited to the configured simulation
    estate.  Rejecting malformed or unexpected IDs here prevents a future
    naming change from silently producing incorrect site/cell metadata.
    """

    match = ASSET_ID_PATTERN.fullmatch(asset_id)
    if match is None:
        return None
    asset_type = ASSET_TYPE_BY_PREFIX[match.group("prefix")]
    site_id = match.group("site")
    return asset_type, site_id, f"{site_id}-{match.group('line')}"


def _location_from_asset_id(asset_id: str) -> tuple[str, str]:
    identity = _asset_identity_from_id(asset_id)
    if identity is None:
        return "unknown", "unknown"
    _asset_type, site_id, cell_id = identity
    return site_id, cell_id
