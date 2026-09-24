"""Database package for Chetna flood early-warning system."""

from src.db.forecasts import (
    DEFAULT_DB_PATH,
    get_db_connection,
    get_forecast_by_timestamp,
    get_forecast_history,
    get_latest_forecast,
    init_db,
    save_forecast,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "get_db_connection",
    "init_db",
    "save_forecast",
    "get_latest_forecast",
    "get_forecast_history",
    "get_forecast_by_timestamp",
]
