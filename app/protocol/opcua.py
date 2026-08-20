"""OPC UA SDK publisher for generated SensorRecord values.

This module publishes DataValue objects to an asyncua Server address space. It
does not claim to capture wire packets and it does not implement a collector or
subscription path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asyncua import ua
from asyncua.sync import Server

from app.observation.models import SensorRecord


@dataclass(frozen=True)
class NodeMapping:
    node_id_template: str
    data_type: str
    unit: str


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
