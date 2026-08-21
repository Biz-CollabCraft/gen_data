"""Import compatibility for the retired line worker module.

Sensor calculation is owned by :class:`app.simulation.producer.SimulationProducer`.
No raw encode/decode worker is preserved here.
"""

from app.observation.models import SensorRecord
from app.simulation.producer import SimulationProducer

__all__ = ["SensorRecord", "SimulationProducer"]
