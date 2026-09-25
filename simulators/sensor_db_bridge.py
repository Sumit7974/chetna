"""Sensor-to-database integration bridge for Chetna B2.

Persists SensorReading objects from simulators.sensor_simulator
into the canonical B2 database (data/chetna.db via database/db.py).

Also provides batch insertion helpers and optional node auto-registration.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import List, Optional, Sequence, Union

from database.db import (
    DEFAULT_DB_PATH,
    init_db,
    register_sensor_node,
    save_sensor_reading,
)
from simulators.sensor_simulator import SensorReading

logger = logging.getLogger(__name__)


def persist_reading(
    reading: SensorReading,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    auto_register_node: bool = True,
) -> int:
    """Persist a single SensorReading to the canonical B2 database.

    Args:
        reading: SensorReading dataclass from the sensor simulator.
        db_path: Path to the SQLite database or an in-memory connection.
        auto_register_node: If True, auto-register an unknown node_id with
            default coordinates before inserting the reading.

    Returns:
        The database row ID of the inserted reading.
    """
    if auto_register_node:
        _ensure_node_registered(reading.node_id, db_path=db_path)

    row_id = save_sensor_reading(
        node_id=reading.node_id,
        timestamp=reading.timestamp,
        water_level_cm=reading.water_level_cm,
        rainfall_rate_mm_h=reading.rainfall_rate_mm_h,
        battery_pct=reading.battery_pct,
        is_anomaly=int(reading.is_anomaly),
        db_path=db_path,
    )
    logger.debug(
        "Persisted reading for node %s (water=%.1f cm, rain=%.1f mm/h, anomaly=%s) -> row_id=%d",
        reading.node_id,
        reading.water_level_cm,
        reading.rainfall_rate_mm_h,
        reading.is_anomaly,
        row_id,
    )
    return row_id


def persist_batch(
    readings: Sequence[SensorReading],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    auto_register_node: bool = True,
) -> int:
    """Persist a list of SensorReadings to the canonical B2 database.

    Returns the count of rows inserted.
    """
    if not readings:
        return 0

    if auto_register_node:
        seen_nodes: set = set()
        for r in readings:
            if r.node_id not in seen_nodes:
                _ensure_node_registered(r.node_id, db_path=db_path)
                seen_nodes.add(r.node_id)

    count = 0
    for reading in readings:
        save_sensor_reading(
            node_id=reading.node_id,
            timestamp=reading.timestamp,
            water_level_cm=reading.water_level_cm,
            rainfall_rate_mm_h=reading.rainfall_rate_mm_h,
            battery_pct=reading.battery_pct,
            is_anomaly=int(reading.is_anomaly),
            db_path=db_path,
        )
        count += 1

    logger.info("Persisted %d sensor readings to database.", count)
    return count


def _ensure_node_registered(
    node_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Auto-register a sensor node with default metadata if it does not exist.

    Uses UPSERT semantics in register_sensor_node — safe to call repeatedly.
    """
    register_sensor_node(
        node_id=node_id,
        name=f"Auto-registered: {node_id}",
        latitude=13.0827,   # Chennai centroid default
        longitude=80.2707,
        sensor_type="combined",
        db_path=db_path,
    )
