import socket
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from asyncua import ua
from asyncua.sync import Server
from fastapi.testclient import TestClient

from app.main import create_app
from app.observation.models import SensorRecord
from app.protocol.opcua import OpcUaCollector, OpcUaMapping, OpcUaPublisher
from app.runtime.manager import RuntimeManager


START = datetime(2026, 8, 1, tzinfo=timezone.utc)
MAPPING_PATH = Path("mappings/opcua_nodes.v1.json")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def cnc_record(value: float, sequence: int, observed_at: datetime) -> SensorRecord:
    return SensorRecord(
        schema_version="1",
        run_id="publisher",
        sequence=sequence,
        asset_id="CNC-S01-L01-01",
        observed_at=observed_at,
        measurements={"torque_nm": value},
        generator_version="canonical-ai4i-physics-v3.1",
        asset_type="cnc",
        site_id="S01",
        cell_id="S01-L01",
    )


def wait_for(predicate, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not reached before timeout")


class OpcUaCollectorTests(unittest.TestCase):
    def test_subscription_normalizes_datavalue_and_recovers_after_server_restart(self):
        mapping = OpcUaMapping.load(MAPPING_PATH)
        port = free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/gen-data/"
        node_id = "ns=2;s=CNC-S01-L01-01.torque_nm"
        publisher = OpcUaPublisher(endpoint=endpoint, mapping=mapping)
        publisher.start()
        publisher.publish(cnc_record(51.25, 1, START))

        records = []
        provenance = []
        quarantine = []
        errors = []
        collector = OpcUaCollector(
            endpoint=endpoint,
            mapping=mapping,
            run_id="collector-run",
            node_ids=[node_id],
            on_record=records.append,
            on_provenance=provenance.append,
            on_quarantine=quarantine.append,
            on_error=errors.append,
            reconnect_seconds=0.1,
        )
        stop_event = threading.Event()
        thread = threading.Thread(target=collector.run, args=(stop_event,), daemon=True)
        thread.start()
        replacement = None
        try:
            wait_for(lambda: len(records) >= 1)
            self.assertEqual(records[0].source_kind, "opcua")
            self.assertEqual(records[0].measurements, {"torque_nm": 51.25})
            self.assertEqual(records[0].asset_id, "CNC-S01-L01-01")
            self.assertEqual(provenance[0]["direction"], "received")
            self.assertEqual(provenance[0]["status_code"], "Good")
            self.assertEqual(provenance[0]["source_timestamp"], START.isoformat(timespec="seconds"))
            self.assertIsNotNone(provenance[0]["server_timestamp"])
            self.assertIsNotNone(provenance[0]["received_at"])
            self.assertFalse(quarantine)

            publisher.publish(cnc_record(51.25, 2, START))
            time.sleep(0.4)
            self.assertEqual(len(records), 1, "same node/timestamp/value/status must be deduplicated")

            publisher.stop()
            wait_for(lambda: len(errors) >= 1)

            replacement = OpcUaPublisher(endpoint=endpoint, mapping=mapping)
            replacement.start()
            replacement.publish(cnc_record(53.75, 2, START + timedelta(minutes=1)))
            wait_for(lambda: any(record.measurements["torque_nm"] == 53.75 for record in records))
            self.assertGreaterEqual(collector.sequence, 2)
        finally:
            stop_event.set()
            thread.join(timeout=3)
            if replacement is not None:
                replacement.stop()
            else:
                publisher.stop()

    def test_runtime_manager_collects_configured_opcua_source_and_quarantines_unknown_node(self):
        mapping = OpcUaMapping.load(MAPPING_PATH)
        port = free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/gen-data/"
        node_id = "ns=2;s=CNC-S01-L01-01.torque_nm"
        publisher = OpcUaPublisher(endpoint=endpoint, mapping=mapping)
        publisher.start()
        publisher.publish(cnc_record(44.5, 1, START))
        try:
            with TemporaryDirectory() as directory:
                manager = RuntimeManager(
                    output_root=Path(directory),
                    mapping_path=MAPPING_PATH,
                    opcua_endpoint=endpoint,
                )
                manager.start_run(
                    run_id="opcua-source",
                    source_kind="opcua",
                    opcua_source_endpoint=endpoint,
                    opcua_node_ids=[node_id, "ns=2;s=UNKNOWN.not_mapped"],
                    reconnect_seconds=0.1,
                )
                wait_for(lambda: manager.status("opcua-source")["source_record_count"] >= 1)
                outputs = manager.outputs("opcua-source")
                self.assertEqual(outputs["counts"]["source_records"], 1)
                self.assertEqual(outputs["counts"]["protocol_datavalues"], 1)
                self.assertEqual(outputs["counts"]["quarantined_datavalues"], 1)
                self.assertEqual(outputs["counts"]["canonical_observations"], 0)
                source_line = Path(outputs["source"]).read_text(encoding="utf-8")
                self.assertIn('"source_kind": "opcua"', source_line)
                quarantine_line = Path(outputs["protocol_quarantine"]).read_text(encoding="utf-8")
                self.assertIn("unknown_or_ambiguous_node", quarantine_line)
                with self.assertRaisesRegex(RuntimeError, "manual tick"):
                    manager.tick("opcua-source")
                stopped = manager.stop("opcua-source")
                self.assertIn(stopped["status"], {"stopped", "partial_failure"})
        finally:
            publisher.stop()

    def test_invalid_data_type_and_unit_are_quarantined(self):
        mapping = OpcUaMapping.load(MAPPING_PATH)
        node_id = "ns=2;s=CNC-S01-L01-01.torque_nm"

        def run_case(*, value, variant_type, unit, expected_reason):
            port = free_port()
            endpoint = f"opc.tcp://127.0.0.1:{port}/gen-data/"
            server = Server()
            server.set_endpoint(endpoint)
            namespace_index = server.register_namespace(mapping.namespace_uri)
            asset = server.nodes.objects.add_object(namespace_index, "CNC-S01-L01-01")
            variable = asset.add_variable(
                ua.NodeId.from_string(node_id),
                "torque_nm",
                value,
                varianttype=variant_type,
            )
            variable.add_property(
                namespace_index,
                "engineering_unit",
                unit,
                varianttype=ua.VariantType.String,
            )
            server.start()
            records = []
            quarantine = []
            stop_event = threading.Event()
            collector = OpcUaCollector(
                endpoint=endpoint,
                mapping=mapping,
                run_id="invalid-contract",
                node_ids=[node_id],
                on_record=records.append,
                on_provenance=lambda _payload: None,
                on_quarantine=quarantine.append,
                on_error=lambda _payload: None,
                reconnect_seconds=0.1,
            )
            thread = threading.Thread(target=collector.run, args=(stop_event,), daemon=True)
            thread.start()
            try:
                wait_for(lambda: any(row["reason"] == expected_reason for row in quarantine))
                self.assertFalse(records)
            finally:
                stop_event.set()
                thread.join(timeout=3)
                server.stop()

        with self.subTest("data type"):
            run_case(
                value="not-a-double",
                variant_type=ua.VariantType.String,
                unit="N.m",
                expected_reason="invalid_data_type",
            )
        with self.subTest("unit"):
            run_case(
                value=45.0,
                variant_type=ua.VariantType.Double,
                unit="wrong-unit",
                expected_reason="invalid_unit",
            )

    def test_fastapi_can_start_and_stop_opcua_source_run(self):
        mapping = OpcUaMapping.load(MAPPING_PATH)
        port = free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/gen-data/"
        node_id = "ns=2;s=CNC-S01-L01-01.torque_nm"
        publisher = OpcUaPublisher(endpoint=endpoint, mapping=mapping)
        publisher.start()
        publisher.publish(cnc_record(47.0, 1, START))
        try:
            with TemporaryDirectory() as directory:
                manager = RuntimeManager(
                    output_root=Path(directory),
                    mapping_path=MAPPING_PATH,
                    opcua_endpoint=endpoint,
                )
                with TestClient(create_app(manager)) as client:
                    started = client.post(
                        "/api/runs",
                        json={
                            "run_id": "api-opcua-source",
                            "source_kind": "opcua",
                            "opcua_source_endpoint": endpoint,
                            "opcua_node_ids": [node_id],
                            "reconnect_seconds": 0.1,
                            "continuous": True,
                        },
                    )
                    self.assertEqual(started.status_code, 201)
                    wait_for(
                        lambda: client.get("/api/runs/api-opcua-source").json()[
                            "source_record_count"
                        ]
                        >= 1
                    )
                    outputs = client.get("/api/runs/api-opcua-source/outputs")
                    self.assertEqual(outputs.status_code, 200)
                    self.assertEqual(outputs.json()["counts"]["protocol_datavalues"], 1)
                    tick = client.post("/api/runs/api-opcua-source/tick")
                    self.assertEqual(tick.status_code, 400)
                    self.assertIn("manual tick", tick.json()["detail"])
                    stopped = client.post("/api/runs/api-opcua-source/stop")
                    self.assertEqual(stopped.status_code, 200)
        finally:
            publisher.stop()


if __name__ == "__main__":
    unittest.main()
