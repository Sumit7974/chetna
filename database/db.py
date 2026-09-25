"""Database connection and utility helpers for Chetna B2."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/chetna.db")
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def get_db_connection(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding a SQLite connection configured with Row factory.

    Accepts an existing sqlite3.Connection (useful in testing with :memory:),
    or a filepath string/Path. Parent folders are auto-created when needed.
    """
    if isinstance(db_path, sqlite3.Connection):
        yield db_path
    else:
        path = Path(db_path)
        if path.name != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    schema_path: Union[str, Path] = DEFAULT_SCHEMA_PATH,
) -> None:
    """Initialize the SQLite database with DDL tables from schema.sql idempotently."""
    schema_file = Path(schema_path)
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found at: {schema_file}")

    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection(db_path) as conn:
        conn.executescript(schema_sql)

    logger.info("Database schema initialized successfully at %s", db_path)


def register_sensor_node(
    node_id: str,
    name: str,
    latitude: float,
    longitude: float,
    sensor_type: str = "water_level",
    warning_threshold_cm: float = 75.0,
    critical_threshold_cm: float = 120.0,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Register or update metadata for a physical or simulated sensor node."""
    sql = """
    INSERT INTO sensor_nodes (
        node_id, name, latitude, longitude, sensor_type,
        warning_threshold_cm, critical_threshold_cm, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
    ON CONFLICT(node_id) DO UPDATE SET
        name=excluded.name,
        latitude=excluded.latitude,
        longitude=excluded.longitude,
        sensor_type=excluded.sensor_type,
        warning_threshold_cm=excluded.warning_threshold_cm,
        critical_threshold_cm=excluded.critical_threshold_cm;
    """
    with get_db_connection(db_path) as conn:
        conn.execute(
            sql,
            (
                node_id,
                name,
                latitude,
                longitude,
                sensor_type,
                warning_threshold_cm,
                critical_threshold_cm,
            ),
        )


def save_sensor_reading(
    node_id: str,
    timestamp: str,
    water_level_cm: Optional[float] = None,
    rainfall_rate_mm_h: Optional[float] = None,
    battery_pct: Optional[float] = None,
    is_anomaly: int = 0,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Persist an individual telemetry reading into the database."""
    sql = """
    INSERT INTO sensor_readings (
        node_id, timestamp, water_level_cm, rainfall_rate_mm_h, battery_pct, is_anomaly
    ) VALUES (?, ?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            sql,
            (
                node_id,
                timestamp,
                water_level_cm,
                rainfall_rate_mm_h,
                battery_pct,
                is_anomaly,
            ),
        )
        return int(cursor.lastrowid)


def log_alert_dispatch(
    alert_id: str,
    severity: str,
    channel: str,
    recipient: str,
    message: str,
    status: str,
    response_payload: Optional[str] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Record an alert dispatch attempt into alert_logs for auditability."""
    sql = """
    INSERT INTO alert_logs (
        alert_id, severity, channel, recipient, message, status, response_payload
    ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            sql,
            (
                alert_id,
                severity,
                channel,
                recipient,
                message,
                status,
                response_payload,
            ),
        )
        return int(cursor.lastrowid)
