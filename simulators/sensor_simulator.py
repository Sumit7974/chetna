"""Sensor simulation logic for Chetna flood early-warning system prototype.

Generates realistic telemetry for ultrasonic water-level sensors and rain gauges,
supporting multiple hydrological scenarios (normal, rising water, flash floods, sensor anomalies).
"""

from __future__ import annotations

import datetime
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Generator, List, Optional, Union
import sqlite3
from pathlib import Path


class SimulationScenario(str, Enum):
    """Hydrological scenarios for sensor emulation."""

    NORMAL = "normal"
    RISING = "rising"
    FLASH_FLOOD = "flash_flood"
    ANOMALY = "anomaly"


@dataclass
class SensorReading:
    """Dataclass representing an individual sensor observation."""

    node_id: str
    timestamp: str
    water_level_cm: float
    rainfall_rate_mm_h: float
    battery_pct: float
    is_anomaly: bool = False

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "timestamp": self.timestamp,
            "water_level_cm": round(self.water_level_cm, 2),
            "rainfall_rate_mm_h": round(self.rainfall_rate_mm_h, 2),
            "battery_pct": round(self.battery_pct, 1),
            "is_anomaly": int(self.is_anomaly),
        }


class SensorSimulator:
    """Emulates IoT sensor telemetry nodes across Chennai drainage basins."""

    def __init__(
        self,
        node_id: str = "NODE_CHN_01",
        base_water_level_cm: float = 25.0,
        warning_threshold_cm: float = 75.0,
        critical_threshold_cm: float = 120.0,
    ) -> None:
        self.node_id = node_id
        self.base_water_level_cm = base_water_level_cm
        self.warning_threshold_cm = warning_threshold_cm
        self.critical_threshold_cm = critical_threshold_cm
        self.current_water_level = base_water_level_cm
        self.battery_pct = 98.0

    def generate_reading(
        self,
        scenario: SimulationScenario = SimulationScenario.NORMAL,
        timestamp: Optional[datetime.datetime] = None,
        step_index: int = 0,
    ) -> SensorReading:
        """Generate a single point-in-time sensor reading based on the chosen scenario."""
        dt = timestamp or datetime.datetime.now(datetime.timezone.utc)
        ts_str = dt.isoformat()

        # Slight battery discharge per step
        self.battery_pct = max(10.0, self.battery_pct - random.uniform(0.01, 0.05))

        is_anomaly = False
        if scenario == SimulationScenario.NORMAL:
            # Baseline tidal or runoff noise
            noise = random.uniform(-1.5, 1.5)
            water_level = max(5.0, self.base_water_level_cm + noise)
            rain_rate = max(0.0, random.uniform(0.0, 3.0))

        elif scenario == SimulationScenario.RISING:
            # Steady continuous rise (e.g., monsoon inflow)
            rate = 3.5 + random.uniform(-0.5, 0.8)
            water_level = self.base_water_level_cm + (step_index * rate)
            rain_rate = 15.0 + random.uniform(0.0, 10.0)

        elif scenario == SimulationScenario.FLASH_FLOOD:
            # Rapid surge exceeding critical limits
            surge = (step_index**1.5) * 4.0
            water_level = self.base_water_level_cm + surge + random.uniform(0.0, 5.0)
            rain_rate = 45.0 + random.uniform(10.0, 35.0)

        elif scenario == SimulationScenario.ANOMALY:
            # Sensor glitch or acoustic echo reflection
            water_level = random.choice([-999.0, 850.0, 0.0])
            rain_rate = -5.0
            is_anomaly = True
        else:
            water_level = self.base_water_level_cm
            rain_rate = 0.0

        self.current_water_level = water_level
        return SensorReading(
            node_id=self.node_id,
            timestamp=ts_str,
            water_level_cm=water_level,
            rainfall_rate_mm_h=rain_rate,
            battery_pct=self.battery_pct,
            is_anomaly=is_anomaly,
        )

    def generate_batch(
        self,
        count: int = 10,
        interval_seconds: int = 60,
        scenario: SimulationScenario = SimulationScenario.NORMAL,
        start_time: Optional[datetime.datetime] = None,
    ) -> List[SensorReading]:
        """Generate a series of historical or projected sensor readings."""
        start = start_time or (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=count * interval_seconds)
        )
        readings = []
        for i in range(count):
            t = start + datetime.timedelta(seconds=i * interval_seconds)
            reading = self.generate_reading(scenario=scenario, timestamp=t, step_index=i)
            readings.append(reading)
        return readings

    def stream_readings(
        self,
        scenario: SimulationScenario = SimulationScenario.NORMAL,
        interval_seconds: float = 1.0,
        max_ticks: Optional[int] = None,
    ) -> Generator[SensorReading, None, None]:
        """Yield real-time simulated telemetry ticks."""
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            yield self.generate_reading(scenario=scenario, step_index=ticks)
            ticks += 1
            if interval_seconds > 0:
                time.sleep(interval_seconds)
