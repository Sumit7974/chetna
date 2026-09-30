"""Database connection and utility helpers for Chetna B2."""

from __future__ import annotations

import datetime
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
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(sensor_readings);")
            sr_cols = [row["name"] for row in cursor.fetchall()]
            if sr_cols:
                if "raw_water_level_cm" not in sr_cols:
                    conn.execute("ALTER TABLE sensor_readings ADD COLUMN raw_water_level_cm REAL;")
                if "raw_rainfall_rate_mm_h" not in sr_cols:
                    conn.execute("ALTER TABLE sensor_readings ADD COLUMN raw_rainfall_rate_mm_h REAL;")
                if "validation_status" not in sr_cols:
                    conn.execute("ALTER TABLE sensor_readings ADD COLUMN validation_status TEXT DEFAULT 'VALID';")
                if "validation_message" not in sr_cols:
                    conn.execute("ALTER TABLE sensor_readings ADD COLUMN validation_message TEXT;")
                if "source" not in sr_cols:
                    conn.execute("ALTER TABLE sensor_readings ADD COLUMN source TEXT DEFAULT 'simulated';")
        except Exception as exc:
            logger.debug("Pre-migration check: %s", exc)

        conn.executescript(schema_sql)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(risk_predictions);")
            cols = [row["name"] for row in cursor.fetchall()]
            if cols and "explanation" not in cols:
                conn.execute("ALTER TABLE risk_predictions ADD COLUMN explanation TEXT;")
        except Exception as exc:
            logger.debug("Column migration check: %s", exc)

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
    raw_water_level_cm: Optional[float] = None,
    raw_rainfall_rate_mm_h: Optional[float] = None,
    validation_status: str = "VALID",
    validation_message: Optional[str] = None,
    source: str = "simulated",
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Persist an individual telemetry reading into the database with auditability."""
    # Preserve raw values for backwards compatibility if not explicitly supplied
    if raw_water_level_cm is None and water_level_cm is not None:
        raw_water_level_cm = water_level_cm
    if raw_rainfall_rate_mm_h is None and rainfall_rate_mm_h is not None:
        raw_rainfall_rate_mm_h = rainfall_rate_mm_h

    sql = """
    INSERT INTO sensor_readings (
        node_id, timestamp, water_level_cm, rainfall_rate_mm_h, battery_pct, is_anomaly,
        raw_water_level_cm, raw_rainfall_rate_mm_h, validation_status, validation_message, source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                raw_water_level_cm,
                raw_rainfall_rate_mm_h,
                validation_status,
                validation_message,
                source,
            ),
        )
        return int(cursor.lastrowid)


def get_sensor_readings(
    node_id: Optional[str] = None,
    validation_status: Optional[str] = None,
    limit: int = 100,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Query recent sensor readings with optional node and validation filters."""
    conditions = []
    params: List[Any] = []
    if node_id:
        conditions.append("node_id = ?")
        params.append(node_id)
    if validation_status:
        conditions.append("validation_status = ?")
        params.append(validation_status)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
    SELECT id, node_id, timestamp, water_level_cm, rainfall_rate_mm_h, battery_pct,
           is_anomaly, raw_water_level_cm, raw_rainfall_rate_mm_h, validation_status,
           validation_message, source, created_at
    FROM sensor_readings
    {where_clause}
    ORDER BY id DESC
    LIMIT ?;
    """
    params.append(limit)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def get_latest_sensor_reading(
    node_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent reading for a given sensor node."""
    rows = get_sensor_readings(node_id=node_id, limit=1, db_path=db_path)
    return rows[0] if rows else None


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


def create_alert_record(
    alert_id: str,
    severity: str,
    title: str,
    message: str,
    affected_area: str,
    lifecycle_status: str = "draft",
    suppressed: int = 0,
    node_id: Optional[str] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Insert or replace an alert record in the alerts table."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    sql = """
    INSERT INTO alerts (
        alert_id, node_id, severity, lifecycle_status,
        title, message, affected_area, reason, suppressed, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(alert_id) DO UPDATE SET
        lifecycle_status=excluded.lifecycle_status,
        suppressed=excluded.suppressed,
        updated_at=excluded.updated_at;
    """
    with get_db_connection(db_path) as conn:
        conn.execute(
            sql,
            (
                alert_id,
                node_id,
                severity,
                lifecycle_status,
                title,
                message,
                affected_area,
                message,
                suppressed,
                now,
                now,
            ),
        )


def update_alert_lifecycle(
    alert_id: str,
    lifecycle_status: str,
    suppressed: Optional[int] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Update lifecycle_status and optionally suppressed flag for an alert."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    supp = 1 if lifecycle_status in ("suppressed", "dismissed") else 0
    if suppressed is not None:
        supp = suppressed
    sql = """
    UPDATE alerts SET lifecycle_status=?, suppressed=?, updated_at=?
    WHERE alert_id=?;
    """
    with get_db_connection(db_path) as conn:
        conn.execute(sql, (lifecycle_status, supp, now, alert_id))


def get_alert_by_id(
    alert_id: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Retrieve an alert record by alert_id."""
    sql = "SELECT * FROM alerts WHERE alert_id=? LIMIT 1;"
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, (alert_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_recent_public_warnings(
    limit: int = 10,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve recent simulated public warnings for dashboard and citizen view."""
    sql = """
    SELECT * FROM public_warnings
    ORDER BY id DESC
    LIMIT ?;
    """
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (limit,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        logger.debug("Could not query public_warnings: %s", exc)
        return []
