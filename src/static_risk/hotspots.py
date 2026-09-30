"""Waterlogging hotspot and historical backtesting event definitions for Chetna M1.

Provides strongly-typed data structures, geospatial validation, and loader utilities
for the 5–10 known waterlogging locations and selected backtest rainfall events.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from database.db import DEFAULT_DB_PATH, get_db_connection

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
    cell_id: Optional[str] = None
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
        properties = {
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
        }
        if self.cell_id:
            properties["cell_id"] = self.cell_id
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": properties,
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
        fallback = DEFAULT_M1_DATA_DIR / target_path.name
        if fallback.is_file():
            target_path = fallback
        else:
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


# ---------------------------------------------------------------------------
# M1 Day 1: Hotspot & Grid Cell Mapping
# ---------------------------------------------------------------------------

DEFAULT_HOTSPOT_CELL_MAPPING: Dict[str, str] = {
    "HS01": "CELL_VEL_01",
    "HS02": "CELL_MAD_01",
    "HS03": "CELL_MUD_01",
    "HS04": "CELL_TNG_01",
    "HS05": "CELL_PUL_01",
    "HS06": "CELL_VYA_01",
    "HS07": "CELL_PRM_01",
    "HS08": "CELL_KYM_01",
    "HS09": "CELL_MNP_01",
    "HS10": "CELL_PLK_01",
}


# ---------------------------------------------------------------------------
# M1 Day 1: Observations & Development Dataset Data Structures
# ---------------------------------------------------------------------------

@dataclass
class HotspotEventObservation:
    """Hourly rainfall and proxy inundation observation at a specific hotspot during a backtest event.

    IMPORTANT PROVENANCE NOTE:
    To ensure strict scientific integrity, `is_proxy` is True by default. These records
    represent proxy development labels calibrated to official GCC chronic hotspot
    thresholds and historical reanalysis, not raw physical water-depth sensor logs.
    """
    event_id: str
    hotspot_id: str
    timestamp: str
    rain_1h: float
    rain_3h: float
    rain_6h: float
    rain_past_24h: float
    waterlogged_proxy: bool
    inundation_depth_proxy_m: float
    proxy_risk_tier: str
    cell_id: Optional[str] = None
    is_proxy: bool = True
    data_source: str = "Proxy/Synthetic Development Observation (Calibrated to GCC Chronic Hotspot Trigger Thresholds)"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class M1DevelopmentDataset:
    """Complete M1 Day 1 development dataset combining hotspots, events, and observations."""
    dataset_name: str
    version: str
    created_at: str
    hotspots: List[Hotspot]
    events: List[BacktestEvent]
    observations: List[HotspotEventObservation]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "version": self.version,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "hotspots": [h.to_dict() for h in self.hotspots],
            "events": [e.to_dict() for e in self.events],
            "observations": [o.to_dict() for o in self.observations],
        }

    def save_to_json(self, filepath: Union[str, Path]) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def save_to_csv(self, filepath: Union[str, Path]) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.observations:
            return
        fieldnames = list(self.observations[0].to_dict().keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for obs in self.observations:
                writer.writerow(obs.to_dict())

    def save_to_db(self, db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH) -> Dict[str, int]:
        return save_m1_dataset_to_db(self, db_path=db_path)


# ---------------------------------------------------------------------------
# SQLite Schema and Persistence Helpers
# ---------------------------------------------------------------------------

CREATE_HOTSPOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hotspots (
    hotspot_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'Bihar',
    zone TEXT NOT NULL,
    ward INTEGER,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    elevation_m REAL,
    hotspot_type TEXT,
    severity_tier TEXT,
    typical_trigger_rain_1h_mm REAL,
    typical_trigger_rain_6h_mm REAL,
    historical_inundation_depth_m REAL,
    primary_vulnerability_cause TEXT,
    source_reference TEXT,
    cell_id TEXT,
    is_real_sourced BOOLEAN NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_BACKTEST_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_events (
    event_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'Bihar',
    country TEXT NOT NULL DEFAULT 'India',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    duration_hours INTEGER NOT NULL,
    total_rainfall_mm REAL NOT NULL,
    peak_hourly_rainfall_mm REAL NOT NULL,
    peak_hourly_timestamp TEXT NOT NULL,
    classification TEXT,
    impact_summary TEXT,
    rainfall_data_file TEXT,
    source_reference TEXT,
    is_real_sourced BOOLEAN NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_HOTSPOT_OBSERVATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hotspot_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    hotspot_id TEXT NOT NULL,
    cell_id TEXT,
    timestamp TEXT NOT NULL,
    rain_1h REAL NOT NULL,
    rain_3h REAL NOT NULL,
    rain_6h REAL NOT NULL,
    rain_past_24h REAL NOT NULL,
    waterlogged_proxy BOOLEAN NOT NULL,
    inundation_depth_proxy_m REAL NOT NULL,
    proxy_risk_tier TEXT NOT NULL,
    is_proxy BOOLEAN NOT NULL DEFAULT 1,
    data_source TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hotspot_id) REFERENCES hotspots(hotspot_id) ON DELETE CASCADE,
    FOREIGN KEY (event_id) REFERENCES backtest_events(event_id) ON DELETE CASCADE
);
"""


def init_hotspot_tables(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Initialize SQLite tables for hotspots, backtest events, and observations idempotently."""
    with get_db_connection(db_path) as conn:
        with conn:
            conn.execute(CREATE_HOTSPOTS_TABLE_SQL)
            conn.execute(CREATE_BACKTEST_EVENTS_TABLE_SQL)
            conn.execute(CREATE_HOTSPOT_OBSERVATIONS_TABLE_SQL)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hotspots_coords ON hotspots (latitude, longitude);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hotspots_severity ON hotspots (severity_tier);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_events_dates ON backtest_events (start_date, end_date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hotspot_obs_event_spot ON hotspot_observations (event_id, hotspot_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hotspot_obs_time ON hotspot_observations (timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hotspot_obs_proxy ON hotspot_observations (is_proxy);")


def save_hotspots_to_db(
    hotspots: List[Hotspot],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Stores hotspot records into the SQLite 'hotspots' table."""
    init_hotspot_tables(db_path)
    sql = """
    INSERT OR REPLACE INTO hotspots (
        hotspot_id, name, city, state, zone, ward,
        latitude, longitude, elevation_m, hotspot_type,
        severity_tier, typical_trigger_rain_1h_mm, typical_trigger_rain_6h_mm,
        historical_inundation_depth_m, primary_vulnerability_cause,
        source_reference, cell_id, is_real_sourced
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    count = 0
    with get_db_connection(db_path) as conn:
        with conn:
            for h in hotspots:
                conn.execute(
                    sql,
                    (
                        h.hotspot_id,
                        h.name,
                        h.city,
                        h.state,
                        h.zone,
                        h.ward,
                        h.latitude,
                        h.longitude,
                        h.elevation_m,
                        h.hotspot_type,
                        h.severity_tier,
                        h.typical_trigger_rain_1h_mm,
                        h.typical_trigger_rain_6h_mm,
                        h.historical_inundation_depth_m,
                        h.primary_vulnerability_cause,
                        h.source_reference,
                        h.cell_id,
                        1 if h.is_real_sourced else 0,
                    ),
                )
                count += 1
    return count


def save_backtest_events_to_db(
    events: List[BacktestEvent],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Stores backtest events into the SQLite 'backtest_events' table."""
    init_hotspot_tables(db_path)
    sql = """
    INSERT OR REPLACE INTO backtest_events (
        event_id, name, city, state, country,
        start_date, end_date, duration_hours,
        total_rainfall_mm, peak_hourly_rainfall_mm, peak_hourly_timestamp,
        classification, impact_summary, rainfall_data_file,
        source_reference, is_real_sourced
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    count = 0
    with get_db_connection(db_path) as conn:
        with conn:
            for e in events:
                conn.execute(
                    sql,
                    (
                        e.event_id,
                        e.name,
                        e.city,
                        e.state,
                        e.country,
                        e.start_date,
                        e.end_date,
                        e.duration_hours,
                        e.total_rainfall_mm,
                        e.peak_hourly_rainfall_mm,
                        e.peak_hourly_timestamp,
                        e.classification,
                        e.impact_summary,
                        e.rainfall_data_file,
                        e.source_reference,
                        1 if e.is_real_sourced else 0,
                    ),
                )
                count += 1
    return count


def save_hotspot_observations_to_db(
    observations: List[HotspotEventObservation],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Stores hourly hotspot observations into the SQLite 'hotspot_observations' table."""
    init_hotspot_tables(db_path)
    sql = """
    INSERT INTO hotspot_observations (
        event_id, hotspot_id, cell_id, timestamp,
        rain_1h, rain_3h, rain_6h, rain_past_24h,
        waterlogged_proxy, inundation_depth_proxy_m,
        proxy_risk_tier, is_proxy, data_source
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    count = 0
    with get_db_connection(db_path) as conn:
        with conn:
            for obs in observations:
                conn.execute(
                    sql,
                    (
                        obs.event_id,
                        obs.hotspot_id,
                        obs.cell_id,
                        obs.timestamp,
                        obs.rain_1h,
                        obs.rain_3h,
                        obs.rain_6h,
                        obs.rain_past_24h,
                        1 if obs.waterlogged_proxy else 0,
                        obs.inundation_depth_proxy_m,
                        obs.proxy_risk_tier,
                        1 if obs.is_proxy else 0,
                        obs.data_source,
                    ),
                )
                count += 1
    return count


def save_m1_dataset_to_db(
    dataset: M1DevelopmentDataset,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Dict[str, int]:
    """Persists all components of an M1DevelopmentDataset into SQLite."""
    n_h = save_hotspots_to_db(dataset.hotspots, db_path=db_path)
    n_e = save_backtest_events_to_db(dataset.events, db_path=db_path)
    n_o = save_hotspot_observations_to_db(dataset.observations, db_path=db_path)
    return {"hotspots": n_h, "events": n_e, "observations": n_o}


def load_hotspots_from_db(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[Hotspot]:
    """Loads all hotspot records from the SQLite database."""
    init_hotspot_tables(db_path)
    sql = """
    SELECT hotspot_id, name, city, state, zone, ward,
           latitude, longitude, elevation_m, hotspot_type,
           severity_tier, typical_trigger_rain_1h_mm, typical_trigger_rain_6h_mm,
           historical_inundation_depth_m, primary_vulnerability_cause,
           source_reference, cell_id, is_real_sourced
    FROM hotspots ORDER BY hotspot_id;
    """
    hotspots: List[Hotspot] = []
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        for row in cursor.execute(sql):
            hotspots.append(
                Hotspot(
                    hotspot_id=row["hotspot_id"],
                    name=row["name"],
                    city=row["city"],
                    state=row["state"],
                    zone=row["zone"],
                    ward=int(row["ward"]) if row["ward"] is not None else 0,
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    elevation_m=float(row["elevation_m"]) if row["elevation_m"] is not None else 0.0,
                    hotspot_type=row["hotspot_type"] or "",
                    severity_tier=row["severity_tier"] or "",
                    typical_trigger_rain_1h_mm=float(row["typical_trigger_rain_1h_mm"]) if row["typical_trigger_rain_1h_mm"] is not None else 0.0,
                    typical_trigger_rain_6h_mm=float(row["typical_trigger_rain_6h_mm"]) if row["typical_trigger_rain_6h_mm"] is not None else 0.0,
                    historical_inundation_depth_m=float(row["historical_inundation_depth_m"]) if row["historical_inundation_depth_m"] is not None else 0.0,
                    primary_vulnerability_cause=row["primary_vulnerability_cause"] or "",
                    source_reference=row["source_reference"] or "",
                    cell_id=row["cell_id"],
                    is_real_sourced=bool(row["is_real_sourced"]),
                )
            )
    return hotspots


def load_backtest_events_from_db(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[BacktestEvent]:
    """Loads all registered backtest events from SQLite."""
    init_hotspot_tables(db_path)
    sql = """
    SELECT event_id, name, city, state, country,
           start_date, end_date, duration_hours,
           total_rainfall_mm, peak_hourly_rainfall_mm, peak_hourly_timestamp,
           classification, impact_summary, rainfall_data_file,
           source_reference, is_real_sourced
    FROM backtest_events ORDER BY event_id;
    """
    events: List[BacktestEvent] = []
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        for row in cursor.execute(sql):
            events.append(
                BacktestEvent(
                    event_id=row["event_id"],
                    name=row["name"],
                    city=row["city"],
                    state=row["state"],
                    country=row["country"],
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                    timezone="Asia/Kolkata",
                    duration_hours=int(row["duration_hours"]),
                    total_rainfall_mm=float(row["total_rainfall_mm"]),
                    peak_hourly_rainfall_mm=float(row["peak_hourly_rainfall_mm"]),
                    peak_hourly_timestamp=row["peak_hourly_timestamp"],
                    classification=row["classification"] or "",
                    impact_summary=row["impact_summary"] or "",
                    rainfall_data_file=row["rainfall_data_file"] or "",
                    source_reference=row["source_reference"] or "",
                    is_real_sourced=bool(row["is_real_sourced"]),
                )
            )
    return events


def load_hotspot_observations_from_db(
    event_id: Optional[str] = None,
    hotspot_id: Optional[str] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> List[HotspotEventObservation]:
    """Loads hourly hotspot observations from SQLite with optional filtering."""
    init_hotspot_tables(db_path)
    query = """
    SELECT event_id, hotspot_id, cell_id, timestamp,
           rain_1h, rain_3h, rain_6h, rain_past_24h,
           waterlogged_proxy, inundation_depth_proxy_m,
           proxy_risk_tier, is_proxy, data_source
    FROM hotspot_observations
    """
    clauses: List[str] = []
    params: List[Any] = []
    if event_id:
        clauses.append("event_id = ?")
        params.append(event_id)
    if hotspot_id:
        clauses.append("hotspot_id = ?")
        params.append(hotspot_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY event_id, hotspot_id, timestamp;"

    observations: List[HotspotEventObservation] = []
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        for row in cursor.execute(query, tuple(params)):
            observations.append(
                HotspotEventObservation(
                    event_id=row["event_id"],
                    hotspot_id=row["hotspot_id"],
                    cell_id=row["cell_id"],
                    timestamp=row["timestamp"],
                    rain_1h=float(row["rain_1h"]),
                    rain_3h=float(row["rain_3h"]),
                    rain_6h=float(row["rain_6h"]),
                    rain_past_24h=float(row["rain_past_24h"]),
                    waterlogged_proxy=bool(row["waterlogged_proxy"]),
                    inundation_depth_proxy_m=float(row["inundation_depth_proxy_m"]),
                    proxy_risk_tier=row["proxy_risk_tier"],
                    is_proxy=bool(row["is_proxy"]),
                    data_source=row["data_source"],
                )
            )
    return observations


# ---------------------------------------------------------------------------
# Dataset Generation and Loader Functions
# ---------------------------------------------------------------------------

def generate_m1_development_dataset(
    output_dir: Optional[Union[str, Path]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> M1DevelopmentDataset:
    """Deterministically generates and saves the complete M1 Day 1 development dataset.

    Combines:
    1. 10 documented Chennai waterlogging hotspots (GCC/TNSDMA records)
    2. 2 historical heavy-rain backtest events (Michaung Dec 2023, Nov 2021)
    3. Hourly rainfall horizon calculations (+1h, +3h, +6h, past 24h)
    4. Calibrated proxy waterlogging and inundation labels (clearly marked as proxy)
    5. Association to ~200 m metric grid cells
    """
    directory = Path(output_dir) if output_dir else DEFAULT_M1_DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)

    import shutil
    for fname in ["backtest_events.json", "michaung_2023_rainfall.json", "nov_2021_rainfall.json"]:
        src_f = DEFAULT_M1_DATA_DIR / fname
        dst_f = directory / fname
        if src_f.exists() and not dst_f.exists():
            shutil.copy2(src_f, dst_f)

    hotspots = load_hotspots(directory / "hotspots.json" if (directory / "hotspots.json").exists() else None)

    for h in hotspots:
        if not h.cell_id:
            h.cell_id = DEFAULT_HOTSPOT_CELL_MAPPING.get(h.hotspot_id)

    # Save updated hotspots with cell_id
    with open(directory / "hotspots.json", "w", encoding="utf-8") as f:
        json.dump([h.to_dict() for h in hotspots], f, indent=2)

    # Save CSV version of hotspots
    if hotspots:
        fieldnames = [
            "hotspot_id", "name", "city", "state", "zone", "ward",
            "latitude", "longitude", "elevation_m", "hotspot_type",
            "severity_tier", "typical_trigger_rain_1h_mm", "typical_trigger_rain_6h_mm",
            "historical_inundation_depth_m", "primary_vulnerability_cause",
            "source_reference", "cell_id", "is_real_sourced"
        ]
        with open(directory / "hotspots.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for h in hotspots:
                d = h.to_dict()
                d.pop("critical_infrastructure_nearby", None)
                d.pop("documented_events", None)
                writer.writerow(d)

    events = load_backtest_events(directory / "backtest_events.json" if (directory / "backtest_events.json").exists() else None)
    # Restrict M1 Day 1 development dataset specifically to historical development events
    dev_events = [e for e in events if e.event_id in ("EVT_2023_MICHAUNG", "EVT_2021_NOV_DEPRESSION")]
    if dev_events:
        events = dev_events

    observations: List[HotspotEventObservation] = []
    hotspot_map = {h.hotspot_id: h for h in hotspots}

    for event in events:
        series = load_historical_rainfall(event.rainfall_data_file, data_dir=directory)
        for hid in event.affected_hotspots:
            if hid not in hotspot_map:
                continue
            h = hotspot_map[hid]
            for record in series.records:
                horizons = series.get_horizon_rain(record.timestamp)
                r1h = horizons["rain_1h"]
                r3h = horizons["rain_3h"]
                r6h = horizons["rain_6h"]
                rp24 = horizons["rain_past_24h"]

                is_wl = (r1h >= h.typical_trigger_rain_1h_mm) or (r6h >= h.typical_trigger_rain_6h_mm)
                if not is_wl and (r3h >= (h.typical_trigger_rain_1h_mm * 1.5)) and (rp24 >= 40.0):
                    is_wl = True

                if not is_wl:
                    depth = 0.0
                    tier = "Low" if r6h < (h.typical_trigger_rain_1h_mm * 0.5) else "Moderate"
                else:
                    ratio = r6h / max(h.typical_trigger_rain_6h_mm, 1.0)
                    depth = round(min(h.historical_inundation_depth_m * ratio, h.historical_inundation_depth_m * 1.2), 2)
                    tier = "High" if depth < 1.0 else "Severe"

                obs = HotspotEventObservation(
                    event_id=event.event_id,
                    hotspot_id=h.hotspot_id,
                    cell_id=h.cell_id,
                    timestamp=record.timestamp,
                    rain_1h=r1h,
                    rain_3h=r3h,
                    rain_6h=r6h,
                    rain_past_24h=rp24,
                    waterlogged_proxy=is_wl,
                    inundation_depth_proxy_m=depth,
                    proxy_risk_tier=tier,
                    is_proxy=True,
                    data_source="Proxy/Synthetic Development Observation (Calibrated to GCC Chronic Hotspot Trigger Thresholds)",
                )
                observations.append(obs)

    dataset = M1DevelopmentDataset(
        dataset_name="Chetna M1 Day 1 Hotspots and Backtest Development Dataset",
        version="1.0.0",
        created_at="2026-09-27T00:00:00Z",
        hotspots=hotspots,
        events=events,
        observations=observations,
        metadata={
            "description": "Standardized M1 Day 1 training and validation foundation connecting chronic waterlogging locations to historical backtest rainfall series.",
            "hotspot_count": len(hotspots),
            "event_count": len(events),
            "total_hourly_observations": len(observations),
            "is_proxy_observations": True,
            "hotspot_sources": [
                "Greater Chennai Corporation (GCC) Chronic Waterlogging Hotspots Registry",
                "Tamil Nadu State Disaster Management Authority (TNSDMA)",
            ],
            "rainfall_sources": [
                "Open-Meteo Historical Weather API (Copernicus ERA5 reanalysis)",
                "IMD Special Monsoon Bulletins",
            ],
        },
    )

    dataset.save_to_json(directory / "hotspot_event_observations.json")
    dataset.save_to_csv(directory / "hotspot_event_observations.csv")

    if db_path is not None:
        dataset.save_to_db(db_path=db_path)

    return dataset


def load_m1_development_dataset(
    data_dir: Optional[Union[str, Path]] = None,
) -> M1DevelopmentDataset:
    """Loads the generated M1 development dataset from disk, generating if missing."""
    directory = Path(data_dir) if data_dir else DEFAULT_M1_DATA_DIR
    obs_file = directory / "hotspot_event_observations.json"
    if not obs_file.exists():
        return generate_m1_development_dataset(output_dir=directory)

    with open(obs_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    hotspots = [Hotspot(**h) for h in data.get("hotspots", [])]
    events = [BacktestEvent(**e) for e in data.get("events", [])]
    observations = [HotspotEventObservation(**o) for o in data.get("observations", [])]

    return M1DevelopmentDataset(
        dataset_name=data.get("dataset_name", "Chetna M1 Day 1 Dataset"),
        version=data.get("version", "1.0.0"),
        created_at=data.get("created_at", ""),
        hotspots=hotspots,
        events=events,
        observations=observations,
        metadata=data.get("metadata", {}),
    )
