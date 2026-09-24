"""Static terrain and vulnerability processing package for Chetna."""

from src.static_risk.historical_rain import fetch_archive_rainfall
from src.static_risk.hotspots import (
    DEFAULT_M1_DATA_DIR,
    BacktestEvent,
    HistoricalRainfallRecord,
    HistoricalRainfallSeries,
    Hotspot,
    get_backtest_event_by_id,
    get_hotspot_by_id,
    load_backtest_events,
    load_historical_rainfall,
    load_hotspots,
)

__all__ = [
    "DEFAULT_M1_DATA_DIR",
    "Hotspot",
    "BacktestEvent",
    "HistoricalRainfallRecord",
    "HistoricalRainfallSeries",
    "load_hotspots",
    "get_hotspot_by_id",
    "load_backtest_events",
    "get_backtest_event_by_id",
    "load_historical_rainfall",
    "fetch_archive_rainfall",
]
