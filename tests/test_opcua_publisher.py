import socket
from datetime import datetime, timezone
from pathlib import Path
import unittest

from asyncua import ua
from asyncua.sync import Client

from app.observation.models import SENSOR_RECORD_SCHEMA_VERSION, SensorRecord
from app.protocol.opcua import OpcUaMapping, OpcUaPublisher


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class OpcUaPublisherTest(unittest.TestCase):
    def test_asyncua_publisher_exposes_real_datavalue_with_source_timestamp(self):
        port = free_port()
        endpoint = f"opc.tcp://127.0.0.1:{port}/gen-data/"
        mapping = OpcUaMapping.load(Path("mappings/opcua_nodes.v1.json"))
        publisher = OpcUaPublisher(endpoint=endpoint, mapping=mapping)
        observed_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        record = SensorRecord(
            schema_version=SENSOR_RECORD_SCHEMA_VERSION,
            run_id="opcua-test",
            sequence=1,
            asset_id="CNC-S01-L01-01",
            observed_at=observed_at,
            measurements={"torque_nm": 51.25, "product_type": "L"},
            generator_version="canonical-ai4i-physics-v3.1",
            asset_type="cnc",
            site_id="S01",
            cell_id="S01-L01",
        )
        try:
            publisher.start()
            provenance = publisher.publish(record)
            self.assertEqual(len(provenance), 1)
            self.assertEqual(provenance[0]["node_id"], "ns=2;s=CNC-S01-L01-01.torque_nm")
            self.assertEqual(provenance[0]["status_code"], "Good")
            self.assertEqual(provenance[0]["schema_version"], "2")
            self.assertEqual(provenance[0]["observation_id"], record.observation_id)
            self.assertEqual(
                provenance[0]["source_timestamp"], observed_at.isoformat(timespec="seconds")
            )
            with Client(endpoint) as client:
                data_value = client.get_node(provenance[0]["node_id"]).read_data_value()
            self.assertEqual(data_value.Value.Value, 51.25)
            self.assertEqual(data_value.Value.VariantType, ua.VariantType.Double)
            self.assertTrue(data_value.StatusCode_.is_good())
            self.assertEqual(data_value.SourceTimestamp, observed_at)
        finally:
            publisher.stop()
