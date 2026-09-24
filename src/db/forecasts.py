"""SQLite database helpers and schema management for Chetna forecasts.

Follows the Chetna Framework data contract:
Table: forecasts
Columns: timestamp, rain_1h, rain_3h, rain_6h

Provides safe, idempotent initialization and storage functions
reusable by downstream pipeline components.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

logger = logging.getLogger(__name__)

# Default database file path according to Chetna project layout (inside data/)
DEFAULT_DB_PATH = Path("data/chetna.db")

CREATE_FORECASTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    rain_1h REAL NOT NULL,
    rain_3h REAL NOT NULL,
    rain_6h REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_FORECASTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_forecasts_timestamp ON forecasts (timestamp);
"""


@contextmanager
def get_db_connection(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite database connection.
    
    If an existing sqlite3.Connection is passed (e.g., in unit tests), it yields it
    without closing it. If a file path or string is passed, it creates any necessary
    parent directories, opens the connection, and closes it upon exit.
    """
    if isinstance(db_path, sqlite3.Connection):
        yield db_path
    else:
        path = Path(db_path)
        if path.name != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def init_db(db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH) -> None:
    """Initializes the Chetna SQLite database schema idempotently.
    
    Safe to run repeatedly. Will not alter or drop existing tables or delete existing rows.
    """
    with get_db_connection(db_path) as conn:
        with conn:
            conn.execute(CREATE_FORECASTS_TABLE_SQL)
            conn.execute(CREATE_FORECASTS_INDEX_SQL)
    logger.debug("Initialized Chetna database schema at %s", db_path)


def _extract_forecast_record(
    record: Union[Dict[str, Any], Any],
) -> tuple[str, float, float, float]:
    """Extracts and validates timestamp, rain_1h, rain_3h, and rain_6h from diverse record types."""
    if hasattr(record, "to_db_record"):
        data = record.to_db_record()
    elif hasattr(record, "summary") and hasattr(record.summary, "to_db_record"):
        data = record.summary.to_db_record()
    elif isinstance(record, dict):
        data = record
    else:
        raise TypeError(
            f"Expected dict, RainfallSummary, or WeatherForecastResult, got {type(record).__name__}"
        )

    for field in ("timestamp", "rain_1h", "rain_3h", "rain_6h"):
        if field not in data:
            raise ValueError(f"Missing required forecast field '{field}' in {data}")

    timestamp = str(data["timestamp"]).strip()
    if not timestamp:
        raise ValueError("Forecast 'timestamp' cannot be empty")

    try:
        rain_1h = max(0.0, float(data["rain_1h"]))
        rain_3h = max(0.0, float(data["rain_3h"]))
        rain_6h = max(0.0, float(data["rain_6h"]))
    except (ValueError, TypeError) as e:
        raise ValueError(f"Rainfall values must be numeric: {e}") from e

    return timestamp, rain_1h, rain_3h, rain_6h


def save_forecast(
    record: Union[Dict[str, Any], Any],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Saves a structured forecast record into the SQLite database.
    
    Args:
        record: Dict with keys ('timestamp', 'rain_1h', 'rain_3h', 'rain_6h'),
                or a RainfallSummary / WeatherForecastResult instance.
        db_path: Target SQLite database file path or connection.
        
    Returns:
        The inserted row ID.
    """
    init_db(db_path)
    timestamp, rain_1h, rain_3h, rain_6h = _extract_forecast_record(record)

    with get_db_connection(db_path) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO forecasts (timestamp, rain_1h, rain_3h, rain_6h)
                VALUES (?, ?, ?, ?);
                """,
                (timestamp, rain_1h, rain_3h, rain_6h),
            )
            inserted_id = cursor.lastrowid

    logger.debug(
        "Saved forecast for %s (rain_1h=%.2f, rain_3h=%.2f, rain_6h=%.2f) with id=%d",
        timestamp,
        rain_1h,
        rain_3h,
        rain_6h,
        inserted_id,
    )
    return inserted_id or 0


def get_latest_forecast(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Retrieves the most recent forecast record from the database.
    
    Returns:
        Dict with keys ('id', 'timestamp', 'rain_1h', 'rain_3h', 'rain_6h', 'created_at')
        or None if no records exist.
    """
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, timestamp, rain_1h, rain_3h, rain_6h, created_at
            FROM forecasts
            ORDER BY id DESC
            LIMIT 1;
            """
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def get_forecast_history(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Retrieves chronological forecast records ordered from newest to oldest."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, timestamp, rain_1h, rain_3h, rain_6h, created_at
            FROM forecasts
            ORDER BY id DESC
            LIMIT ?;
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_forecast_by_timestamp(
    timestamp: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Retrieves a forecast record matching a specific timestamp."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, timestamp, rain_1h, rain_3h, rain_6h, created_at
            FROM forecasts
            WHERE timestamp = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (timestamp,),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
