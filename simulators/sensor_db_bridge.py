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
from src.sensors.correction import (
    ValidatedReading,
    correct_and_validate_reading,
)

logger = logging.getLogger(__name__)


def persist_reading(
    reading: Union[SensorReading, ValidatedReading],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    auto_register_node: bool = True,
) -> int:
    """Persist a single SensorReading to the canonical B2 database.

    Runs reading through deterministic correction and validation, preserving
    both raw values and corrected values in the database.

    Args:
        reading: SensorReading or ValidatedReading from sensor simulator.
        db_path: Path to the SQLite database or an in-memory connection.
        auto_register_node: If True, auto-register an unknown node_id with
            default coordinates before inserting the reading.

    Returns:
        The database row ID of the inserted reading.
    """
    if auto_register_node:
        _ensure_node_registered(reading.node_id, db_path=db_path)

    validated = (
        reading
        if isinstance(reading, ValidatedReading)
        else correct_and_validate_reading(reading)
    )

    row_id = save_sensor_reading(
        node_id=validated.node_id,
        timestamp=validated.timestamp,
        water_level_cm=validated.water_level_cm,
        rainfall_rate_mm_h=validated.rainfall_rate_mm_h,
        battery_pct=validated.battery_pct,
        is_anomaly=int(validated.is_anomaly or validated.validation_status == "ANOMALY"),
        raw_water_level_cm=validated.raw_water_level_cm,
        raw_rainfall_rate_mm_h=validated.raw_rainfall_rate_mm_h,
        validation_status=validated.validation_status,
        validation_message=validated.validation_message,
        source=getattr(validated, "source", "simulated"),
        db_path=db_path,
    )
    logger.debug(
        "Persisted reading for node %s (raw=%.1f cm, corr=%s cm, status=%s) -> row_id=%d",
        validated.node_id,
        validated.raw_water_level_cm if validated.raw_water_level_cm is not None else -999.0,
        f"{validated.water_level_cm:.1f}" if validated.water_level_cm is not None else "None",
        validated.validation_status,
        row_id,
    )
    return row_id


def persist_batch(
    readings: Sequence[Union[SensorReading, ValidatedReading]],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    auto_register_node: bool = True,
) -> int:
    """Persist a list of SensorReadings to the canonical B2 database with validation.

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
        persist_reading(
            reading=reading,
            db_path=db_path,
            auto_register_node=False,
        )
        count += 1

    logger.info("Persisted %d validated sensor readings to database.", count)
    return count


def _ensure_node_registered(
    node_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Auto-register a sensor node with default metadata if it does not exist.

    Uses UPSERT semantics in register_sensor_node — safe to call repeatedly.
    """
    try:
        from app.map_layers import DEFAULT_PILOT_SENSORS
        node_meta = next((s for s in DEFAULT_PILOT_SENSORS if s.get("node_id") == node_id), None)
    except Exception:
        node_meta = None

    if node_meta:
        name = node_meta.get("name", f"Auto-registered: {node_id}")
        lat = float(node_meta.get("latitude", 25.6093))
        lon = float(node_meta.get("longitude", 85.1376))
    else:
        name = f"Auto-registered: {node_id}"
        lat = 25.6093
        lon = 85.1376

    register_sensor_node(
        node_id=node_id,
        name=name,
        latitude=lat,
        longitude=lon,
        sensor_type="combined",
        db_path=db_path,
    )
