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
from src.db.spatial import (
    get_spatial_metadata,
    init_spatial_db,
    load_facilities,
    load_grid_cells,
    load_roads,
    record_spatial_metadata,
    save_facilities,
    save_grid_cells,
    save_roads,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "get_db_connection",
    "init_db",
    "save_forecast",
    "get_latest_forecast",
    "get_forecast_history",
    "get_forecast_by_timestamp",
    "init_spatial_db",
    "save_grid_cells",
    "load_grid_cells",
    "save_roads",
    "load_roads",
    "save_facilities",
    "load_facilities",
    "record_spatial_metadata",
    "get_spatial_metadata",
]
