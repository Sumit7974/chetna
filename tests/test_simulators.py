"""Tests for Chetna sensor telemetry simulators."""

from __future__ import annotations

import unittest
from simulators.sensor_simulator import (
    SensorSimulator,
    SimulationScenario,
)


class TestSensorSimulator(unittest.TestCase):
    """Test suite for sensor data generation under various hydrological profiles."""

    def setUp(self) -> None:
        self.sim = SensorSimulator(
            node_id="NODE_CHN_ADYAR_01",
            base_water_level_cm=20.0,
            warning_threshold_cm=75.0,
            critical_threshold_cm=120.0,
        )

    def test_normal_reading_within_bounds(self) -> None:
        """Normal scenario readings fluctuate gently near base water level."""
        reading = self.sim.generate_reading(scenario=SimulationScenario.NORMAL)
        self.assertEqual(reading.node_id, "NODE_CHN_ADYAR_01")
        self.assertFalse(reading.is_anomaly)
        self.assertGreater(reading.water_level_cm, 0.0)
        self.assertLess(reading.water_level_cm, 50.0)
        self.assertLessEqual(reading.rainfall_rate_mm_h, 10.0)

    def test_rising_scenario_increases_water_level(self) -> None:
        """Rising scenario exhibits higher water levels as step count increases."""
        reading_start = self.sim.generate_reading(
            scenario=SimulationScenario.RISING, step_index=0
        )
        reading_later = self.sim.generate_reading(
            scenario=SimulationScenario.RISING, step_index=15
        )
        self.assertGreater(reading_later.water_level_cm, reading_start.water_level_cm)
        self.assertGreaterEqual(reading_later.water_level_cm, 60.0)

    def test_flash_flood_exceeds_critical_threshold(self) -> None:
        """Flash flood surge pushes stage beyond critical threshold."""
        reading = self.sim.generate_reading(
            scenario=SimulationScenario.FLASH_FLOOD, step_index=10
        )
        self.assertGreater(reading.water_level_cm, self.sim.critical_threshold_cm)
        self.assertGreater(reading.rainfall_rate_mm_h, 40.0)

    def test_anomaly_scenario_flag(self) -> None:
        """Anomaly scenario sets is_anomaly flag and anomalous telemetry values."""
        reading = self.sim.generate_reading(scenario=SimulationScenario.ANOMALY)
        self.assertTrue(reading.is_anomaly)

    def test_generate_batch(self) -> None:
        """Batch generation produces correct count and strictly sequenced records."""
        batch = self.sim.generate_batch(
            count=5, interval_seconds=30, scenario=SimulationScenario.NORMAL
        )
        self.assertEqual(len(batch), 5)
        for i in range(len(batch) - 1):
            self.assertLess(batch[i].timestamp, batch[i + 1].timestamp)

    def test_stream_readings_limit(self) -> None:
        """Stream generator correctly terminates when max_ticks is reached."""
        readings = list(
            self.sim.stream_readings(
                scenario=SimulationScenario.NORMAL,
                interval_seconds=0.0,
                max_ticks=3,
            )
        )
        self.assertEqual(len(readings), 3)
