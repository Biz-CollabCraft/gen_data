"""Compatibility namespace exposing the real SDK-backed OPC UA boundary.

The former custom Modbus/OPC-UA-shaped frame adapters were removed.  New code
should import from :mod:`app.protocol` directly.
"""

from app.protocol import OpcUaCollector, OpcUaMapping, OpcUaPublisher

__all__ = ["OpcUaCollector", "OpcUaMapping", "OpcUaPublisher"]
