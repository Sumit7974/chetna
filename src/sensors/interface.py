"""Sensor interface abstractions to support both physical IoT and simulation backends."""

from abc import ABC, abstractmethod
from typing import List, Optional

from simulators.sensor_simulator import SensorReading, SensorSimulator, SimulationScenario

class SensorBackend(ABC):
    """Abstract interface for sensor data ingestion."""

    @abstractmethod
    def get_readings(self, limit: int = 1) -> List[SensorReading]:
        """Fetch the latest readings from the sensor backend."""
        pass

class SimulatedSensorBackend(SensorBackend):
    """Backend utilizing the existing SensorSimulator."""

    def __init__(self, node_id: str, scenario: SimulationScenario = SimulationScenario.NORMAL):
        self.node_id = node_id
        self.simulator = SensorSimulator(node_id=node_id)
        self.scenario = scenario

    def get_readings(self, limit: int = 1) -> List[SensorReading]:
        return self.simulator.generate_batch(count=limit, scenario=self.scenario)

class IoTSensorBackend(SensorBackend):
    """Placeholder backend for real IoT sensor hardware integration."""
    
    def __init__(self, api_endpoint: str, api_key: str):
        self.api_endpoint = api_endpoint
        self.api_key = api_key
        
    def get_readings(self, limit: int = 1) -> List[SensorReading]:
        # TODO: Implement actual HTTP/MQTT fetching
        return []
