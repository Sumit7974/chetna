"""Waterlogging hotspot and historical backtesting event definitions for Chetna M1.

Provides strongly-typed data structures, geospatial validation, and loader utilities
for the 5–10 known waterlogging locations and selected backtest rainfall events.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Default directory for M1 data
DEFAULT_M1_DATA_DIR = Path("data/m1")


@dataclass
class Hotspot:
    """Represents a documented urban flood / waterlogging hotspot."""
    hotspot_id: str
    name: str
    city: str
    state: str
    zone: str
    ward: int
    latitude: float
    longitude: float
    elevation_m: float
    hotspot_type: str
    severity_tier: str
    typical_trigger_rain_1h_mm: float
    typical_trigger_rain_6h_mm: float
    historical_inundation_depth_m: float
    primary_vulnerability_cause: str
    source_reference: str
    critical_infrastructure_nearby: List[str] = field(default_factory=list)
    documented_events: List[str] = field(default_factory=list)
    is_real_sourced: bool = True

    def __post_init__(self) -> None:
        """Validate geospatial coordinates and numeric bounds."""
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Invalid latitude {self.latitude} for hotspot {self.hotspot_id}")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"Invalid longitude {self.longitude} for hotspot {self.hotspot_id}")
        if self.typical_trigger_rain_1h_mm < 0:
            raise ValueError("1-hour trigger rainfall cannot be negative")
        if self.typical_trigger_rain_6h_mm < self.typical_trigger_rain_1h_mm:
            raise ValueError("6-hour trigger rainfall should be >= 1-hour trigger")

    def to_dict(self) -> Dict[str, Any]:
        """Converts hotspot instance to serializable dictionary."""
        return asdict(self)

    def to_geojson_feature(self) -> Dict[str, Any]:
        """Formats hotspot as a standard GeoJSON Point Feature."""
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": {
                "id": self.hotspot_id,
                "name": self.name,
                "city": self.city,
                "zone": self.zone,
                "ward": self.ward,
                "elevation_m": self.elevation_m,
                "severity_tier": self.severity_tier,
                "hotspot_type": self.hotspot_type,
                "inundation_depth_m": self.historical_inundation_depth_m,
                "primary_cause": self.primary_vulnerability_cause,
                "source": self.source_reference,
            },
        }


@dataclass
class BacktestEvent:
    """Historical heavy-rainfall event selected for model validation and replay backtesting."""
    event_id: str
    name: str
    city: str
    state: str
    country: str
    start_date: str
    end_date: str
    timezone: str
    duration_hours: int
    total_rainfall_mm: float
    peak_hourly_rainfall_mm: float
    peak_hourly_timestamp: str
    classification: str
    impact_summary: str
    rainfall_data_file: str
    source_reference: str
    affected_hotspots: List[str] = field(default_factory=list)
    is_real_sourced: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HistoricalRainfallRecord:
    """Individual hourly historical rainfall entry."""
    timestamp: str
    precipitation_mm: float
    rain_mm: float


@dataclass
class HistoricalRainfallSeries:
    """Complete chronological hourly rainfall series for a historical backtesting event."""
    event_id: str
    name: str
    city: str
    latitude: float
    longitude: float
    timezone: str
    start_time: str
    end_time: str
    total_hours: int
    total_precipitation_mm: float
    peak_hourly_precipitation_mm: float
    source: str
    records: List[HistoricalRainfallRecord] = field(default_factory=list)

    def get_horizon_rain(self, reference_time: str) -> Dict[str, float]:
        """Calculates +1h, +3h, +6h forecast rain and past 24h rain at any given hour in the event replay.
        
        Args:
            reference_time: Timestamp matching 'YYYY-MM-DDTHH:00'.
            
        Returns:
            Dict with keys: rain_1h, rain_3h, rain_6h, rain_past_24h.
        """
        timestamps = [r.timestamp for r in self.records]
        values = [r.rain_mm for r in self.records]

        if reference_time not in timestamps:
            raise KeyError(f"Reference time {reference_time} not found in event series timestamps")

        idx = timestamps.index(reference_time)
        n = len(values)

        rain_1h = round(sum(values[idx : min(n, idx + 1)]), 2)
        rain_3h = round(sum(values[idx : min(n, idx + 3)]), 2)
        rain_6h = round(sum(values[idx : min(n, idx + 6)]), 2)
        past_start = max(0, idx - 24)
        rain_past_24h = round(sum(values[past_start:idx]), 2)

        return {
            "rain_1h": rain_1h,
            "rain_3h": rain_3h,
            "rain_6h": rain_6h,
            "rain_past_24h": rain_past_24h,
        }


# ---------------------------------------------------------------------------
# Loader Utilities
# ---------------------------------------------------------------------------

def load_hotspots(filepath: Optional[Union[str, Path]] = None) -> List[Hotspot]:
    """Loads and validates known flood hotspots from JSON."""
    path = Path(filepath) if filepath else DEFAULT_M1_DATA_DIR / "hotspots.json"
    if not path.is_file():
        raise FileNotFoundError(f"Hotspot file not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    if not isinstance(raw_list, list):
        raise ValueError(f"Expected list in {path}, got {type(raw_list).__name__}")

    hotspots = [Hotspot(**item) for item in raw_list]
    return hotspots


def get_hotspot_by_id(
    hotspot_id: str,
    filepath: Optional[Union[str, Path]] = None,
) -> Optional[Hotspot]:
    """Retrieves a specific hotspot by its unique identifier (e.g., 'HS01')."""
    hotspots = load_hotspots(filepath)
    for h in hotspots:
        if h.hotspot_id.upper() == hotspot_id.upper():
            return h
    return None


def load_backtest_events(filepath: Optional[Union[str, Path]] = None) -> List[BacktestEvent]:
    """Loads the registered historical heavy-rain backtest events."""
    path = Path(filepath) if filepath else DEFAULT_M1_DATA_DIR / "backtest_events.json"
    if not path.is_file():
        raise FileNotFoundError(f"Backtest events file not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    return [BacktestEvent(**item) for item in raw_list]


def get_backtest_event_by_id(
    event_id: str,
    filepath: Optional[Union[str, Path]] = None,
) -> Optional[BacktestEvent]:
    """Retrieves a registered backtest event by ID."""
    events = load_backtest_events(filepath)
    for e in events:
        if e.event_id.upper() == event_id.upper():
            return e
    return None


def load_historical_rainfall(
    event_id_or_filename: str,
    data_dir: Optional[Union[str, Path]] = None,
) -> HistoricalRainfallSeries:
    """Loads historical hourly rainfall series for a backtest event.
    
    Args:
        event_id_or_filename: E.g., 'EVT_2023_MICHAUNG' or 'michaung_2023_rainfall.json'.
        data_dir: Directory containing rainfall JSON files.
    """
    directory = Path(data_dir) if data_dir else DEFAULT_M1_DATA_DIR

    if event_id_or_filename.endswith(".json"):
        target_path = directory / event_id_or_filename
    else:
        # Look up filename from registered events
        event = get_backtest_event_by_id(event_id_or_filename, directory / "backtest_events.json")
        if not event:
            raise ValueError(f"Unknown backtest event ID '{event_id_or_filename}'")
        target_path = directory / event.rainfall_data_file

    if not target_path.is_file():
        raise FileNotFoundError(f"Historical rainfall file not found at {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    records = [
        HistoricalRainfallRecord(
            timestamp=r["timestamp"],
            precipitation_mm=float(r.get("precipitation_mm", 0.0)),
            rain_mm=float(r.get("rain_mm", 0.0)),
        )
        for r in raw.get("hourly_series", [])
    ]

    return HistoricalRainfallSeries(
        event_id=raw["event_id"],
        name=raw["name"],
        city=raw["city"],
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
        timezone=raw["timezone"],
        start_time=raw["start_time"],
        end_time=raw["end_time"],
        total_hours=int(raw["total_hours"]),
        total_precipitation_mm=float(raw["total_precipitation_mm"]),
        peak_hourly_precipitation_mm=float(raw["peak_hourly_precipitation_mm"]),
        source=raw["source"],
        records=records,
    )
