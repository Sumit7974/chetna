"""Database initialization and access layer for Chetna AI flood early-warning system.

Target database: data/flood_warning.db
Tables managed:
  1. sensor_table     - Real and simulated physical water-level telemetry
  2. alert_logs       - Dispatched notifications, status tracking, and provider logs
  3. risk_predictions - Spatial risk probabilities calculated across time horizons
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

logger = logging.getLogger(__name__)

# Default SQLite database path for flood warning operations
DEFAULT_DB_PATH = Path("data/flood_warning.db")

# ------------------------------------------------------------------------------
# DDL Schema Definitions
# ------------------------------------------------------------------------------

DDL_SENSOR_TABLE = """
CREATE TABLE IF NOT EXISTS sensor_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    level_cm REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    source TEXT NOT NULL DEFAULT 'simulated'
);
"""

DDL_ALERT_LOGS = """
CREATE TABLE IF NOT EXISTS alert_logs (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    raw_message TEXT NOT NULL
);
"""

DDL_RISK_PREDICTIONS = """
CREATE TABLE IF NOT EXISTS risk_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    horizon INTEGER NOT NULL,
    level TEXT NOT NULL,
    probability REAL NOT NULL
);
"""

# High-performance indexes for time-series and spatial queries
DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_sensor_id_time ON sensor_table (sensor_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_alert_zone_time ON alert_logs (zone_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_risk_cell_time_horizon ON risk_predictions (cell_id, timestamp, horizon);
"""


# ------------------------------------------------------------------------------
# Connection Context Manager
# ------------------------------------------------------------------------------

@contextmanager
def get_db_connection(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding a SQLite connection configured with Row factory.

    Handles connection lifecycle, auto-commit on success, rollback on error,
    and ensures proper closing. Supports passing an existing Connection for in-memory tests.
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
            with conn:
                yield conn
        finally:
            conn.close()


# ------------------------------------------------------------------------------
# Schema Initialization
# ------------------------------------------------------------------------------

def init_db(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Initialize SQLite database schema idempotently.

    Creates sensor_table, alert_logs, and risk_predictions tables along with
    their query optimization indexes.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(DDL_SENSOR_TABLE)
        cursor.execute(DDL_ALERT_LOGS)
        cursor.execute(DDL_RISK_PREDICTIONS)
        cursor.executescript(DDL_INDEXES)

    logger.info("Database schema initialized successfully at '%s'", db_path)


# ------------------------------------------------------------------------------
# Helpers: sensor_table (Insert & Query)
# ------------------------------------------------------------------------------

def insert_sensor_reading(
    sensor_id: str,
    level_cm: float,
    timestamp: Optional[Union[str, datetime.datetime]] = None,
    status: str = "ACTIVE",
    source: str = "simulated",
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Insert a single sensor observation into sensor_table.

    Returns the auto-generated primary key ID.
    """
    if timestamp is None:
        ts_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    elif isinstance(timestamp, datetime.datetime):
        ts_str = timestamp.isoformat()
    else:
        ts_str = str(timestamp)

    query = """
    INSERT INTO sensor_table (sensor_id, timestamp, level_cm, status, source)
    VALUES (?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (sensor_id, ts_str, float(level_cm), status, source))
        return int(cursor.lastrowid)


def insert_sensor_readings_batch(
    readings: List[Dict[str, Any]],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Efficiently bulk-insert a list of sensor reading dictionaries."""
    if not readings:
        return 0

    query = """
    INSERT INTO sensor_table (sensor_id, timestamp, level_cm, status, source)
    VALUES (?, ?, ?, ?, ?);
    """
    records = []
    default_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for r in readings:
        ts = r.get("timestamp", default_ts)
        if isinstance(ts, datetime.datetime):
            ts = ts.isoformat()
        records.append((
            str(r["sensor_id"]),
            str(ts),
            float(r["level_cm"]),
            str(r.get("status", "ACTIVE")),
            str(r.get("source", "simulated")),
        ))

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, records)
        return cursor.rowcount


def get_sensor_readings(
    sensor_id: Optional[str] = None,
    start_time: Optional[Union[str, datetime.datetime]] = None,
    end_time: Optional[Union[str, datetime.datetime]] = None,
    source: Optional[str] = None,
    limit: int = 100,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Query telemetry observations with optional filtering by sensor, window, and source."""
    conditions = []
    params: List[Any] = []

    if sensor_id:
        conditions.append("sensor_id = ?")
        params.append(sensor_id)
    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time.isoformat() if isinstance(start_time, datetime.datetime) else str(start_time))
    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time.isoformat() if isinstance(end_time, datetime.datetime) else str(end_time))
    if source:
        conditions.append("source = ?")
        params.append(source)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
    SELECT id, sensor_id, timestamp, level_cm, status, source
    FROM sensor_table
    {where_clause}
    ORDER BY timestamp DESC
    LIMIT ?;
    """
    params.append(limit)

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_latest_sensor_reading(
    sensor_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent reading for a given sensor."""
    results = get_sensor_readings(sensor_id=sensor_id, limit=1, db_path=db_path)
    return results[0] if results else None


# ------------------------------------------------------------------------------
# Helpers: alert_logs (Insert & Query)
# ------------------------------------------------------------------------------

def insert_alert_log(
    zone_id: str,
    status: str,
    provider: str,
    raw_message: str,
    timestamp: Optional[Union[str, datetime.datetime]] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Record an alert event into alert_logs.

    Returns the generated alert_id.
    """
    if timestamp is None:
        ts_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    elif isinstance(timestamp, datetime.datetime):
        ts_str = timestamp.isoformat()
    else:
        ts_str = str(timestamp)

    query = """
    INSERT INTO alert_logs (zone_id, timestamp, status, provider, raw_message)
    VALUES (?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (zone_id, ts_str, status, provider, raw_message))
        return int(cursor.lastrowid)


def get_alert_logs(
    zone_id: Optional[str] = None,
    status: Optional[str] = None,
    provider: Optional[str] = None,
    limit: int = 100,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve alert log audit records ordered by most recent."""
    conditions = []
    params: List[Any] = []

    if zone_id:
        conditions.append("zone_id = ?")
        params.append(zone_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if provider:
        conditions.append("provider = ?")
        params.append(provider)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
    SELECT alert_id, zone_id, timestamp, status, provider, raw_message
    FROM alert_logs
    {where_clause}
    ORDER BY timestamp DESC
    LIMIT ?;
    """
    params.append(limit)

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_alert_by_id(
    alert_id: int,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Fetch an alert log by its primary key alert_id."""
    query = """
    SELECT alert_id, zone_id, timestamp, status, provider, raw_message
    FROM alert_logs
    WHERE alert_id = ?;
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (alert_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------------------------
# Helpers: risk_predictions (Insert & Query)
# ------------------------------------------------------------------------------

def insert_risk_prediction(
    cell_id: str,
    horizon: int,
    level: str,
    probability: float,
    timestamp: Optional[Union[str, datetime.datetime]] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Insert an AI/model risk assessment prediction for a spatial cell."""
    if timestamp is None:
        ts_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    elif isinstance(timestamp, datetime.datetime):
        ts_str = timestamp.isoformat()
    else:
        ts_str = str(timestamp)

    query = """
    INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability)
    VALUES (?, ?, ?, ?, ?);
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (cell_id, ts_str, int(horizon), level, float(probability)))
        return int(cursor.lastrowid)


def get_latest_risk_predictions(
    cell_id: Optional[str] = None,
    horizon: Optional[int] = None,
    limit: int = 100,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Query recent flood risk model predictions."""
    conditions = []
    params: List[Any] = []

    if cell_id:
        conditions.append("cell_id = ?")
        params.append(cell_id)
    if horizon is not None:
        conditions.append("horizon = ?")
        params.append(horizon)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
    SELECT id, cell_id, timestamp, horizon, level, probability
    FROM risk_predictions
    {where_clause}
    ORDER BY timestamp DESC
    LIMIT ?;
    """
    params.append(limit)

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


# ------------------------------------------------------------------------------
# CLI Script Execution
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    target_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    print(f"Initializing database at: {target_path}")
    init_db(target_path)
    print("Database initialization complete.")
