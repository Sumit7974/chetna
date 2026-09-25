"""Database package for Chetna flood early-warning system."""

from database.init_db import (
    DEFAULT_DB_PATH,
    get_alert_by_id,
    get_alert_logs,
    get_db_connection,
    get_latest_risk_predictions,
    get_latest_sensor_reading,
    get_sensor_readings,
    init_db,
    insert_alert_log,
    insert_risk_prediction,
    insert_sensor_reading,
    insert_sensor_readings_batch,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "get_db_connection",
    "init_db",
    "insert_sensor_reading",
    "insert_sensor_readings_batch",
    "get_sensor_readings",
    "get_latest_sensor_reading",
    "insert_alert_log",
    "get_alert_logs",
    "get_alert_by_id",
    "insert_risk_prediction",
    "get_latest_risk_predictions",
]
