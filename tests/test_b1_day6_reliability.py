"""Reliability, offline readiness, failure handling, and feature-freeze test suite for Chetna B1 Day 6.

Verifies:
1. Data validation: Patna grid bounds, CRS consistency, geometry validity, and database integrity.
2. Stale Chennai data protection: no Chennai data silently masquerading as Patna data.
3. Offline / cached data readiness: core demo operates offline using local cache.
4. Failure handling: honest error states for unavailable APIs, missing cells, invalid coords, unreachable routes.
5. Routing reliability: hazard avoidance, blocked node rejection, honest no-route states, and disclaimer integrity.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from database.db import DEFAULT_DB_PATH, init_db
from src.db.spatial import init_spatial_db, save_facilities, save_roads
from src.ingestion.pilot_config import (
    GEOGRAPHIC_CRS,
    PILOT_BBOX,
    PILOT_CENTER_LAT,
    PILOT_CENTER_LON,
    PILOT_CITY,
    PROJECTED_CRS,
)
from src.ingestion.weather import (
    OpenMeteoClient,
    OpenMeteoConnectionError,
    fetch_and_store_forecast,
)
from src.pipeline import (
    EmptyCellsError,
    ForecastUnavailableError,
    run_pipeline,
)
from src.routing.router import OSMRouter, safe_route


@pytest.fixture
def offline_db(tmp_path: Path) -> Path:
    """Create a temporary database with initialized spatial schema and sample Patna data."""
    db_file = tmp_path / "test_offline_b1_day6.db"
    init_db(db_file)
    init_spatial_db(db_file)

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            """
            INSERT INTO cells (id, geometry, elevation, slope, flow_acc, vulnerability)
            VALUES ('CELL_TEST_01', '{"type":"Polygon","coordinates":[]}', 50.0, 0.4, 60000.0, 0.85);
            """
        )
        conn.execute(
            """
            INSERT INTO grid_cells (cell_id, row, col, centroid_lat, centroid_lon, elevation_m, geometry_geojson)
            VALUES ('CELL_TEST_01', 1, 1, 25.601, 85.163, 50.0, '{"type":"Point","coordinates":[85.163,25.601]}');
            """
        )

    return db_file


# ---------------------------------------------------------------------------
# Day 6.1 — Data Validation & Stale Chennai Protection
# ---------------------------------------------------------------------------

def test_day6_patna_data_validation_in_canonical_db():
    """Verify canonical database contains authentic Patna spatial records within pilot bounds."""
    canonical_db = Path("data/chetna.db")
    if not canonical_db.exists():
        pytest.skip("Canonical database not found on disk")

    with sqlite3.connect(str(canonical_db)) as conn:
        conn.row_factory = sqlite3.Row

        # 1. Hotspots
        hotspots = conn.execute("SELECT name, latitude, longitude FROM hotspots;").fetchall()
        assert len(hotspots) == 10
        for h in hotspots:
            assert PILOT_BBOX["south"] - 0.05 <= h["latitude"] <= PILOT_BBOX["north"] + 0.05
            assert PILOT_BBOX["west"] - 0.05 <= h["longitude"] <= PILOT_BBOX["east"] + 0.05

        # 2. Shelters
        shelters = conn.execute("SELECT name, latitude, longitude FROM shelters;").fetchall()
        assert len(shelters) >= 4
        for s in shelters:
            assert PILOT_BBOX["south"] - 0.05 <= s["latitude"] <= PILOT_BBOX["north"] + 0.05
            assert PILOT_BBOX["west"] - 0.05 <= s["longitude"] <= PILOT_BBOX["east"] + 0.05

        # 3. Grid Cells
        cells = conn.execute("SELECT cell_id, centroid_lat, centroid_lon FROM grid_cells;").fetchall()
        assert len(cells) > 0
        for c in cells:
            assert PILOT_BBOX["south"] - 0.05 <= c["centroid_lat"] <= PILOT_BBOX["north"] + 0.05
            assert PILOT_BBOX["west"] - 0.05 <= c["centroid_lon"] <= PILOT_BBOX["east"] + 0.05

        # 4. Sensor Nodes
        sensors = conn.execute("SELECT node_id, latitude, longitude FROM sensor_nodes;").fetchall()
        assert len(sensors) == 10
        for sn in sensors:
            assert PILOT_BBOX["south"] - 0.05 <= sn["latitude"] <= PILOT_BBOX["north"] + 0.05
            assert PILOT_BBOX["west"] - 0.05 <= sn["longitude"] <= PILOT_BBOX["east"] + 0.05


def test_day6_crs_and_pilot_bounds_consistency():
    """Verify coordinate reference systems and pilot bounds align strictly with Patna."""
    assert PILOT_CITY == "Patna"
    assert GEOGRAPHIC_CRS == "EPSG:4326"
    assert PROJECTED_CRS == "EPSG:32645"  # UTM Zone 45N for Bihar (84°E–90°E)

    # Patna coordinates bounds
    assert PILOT_BBOX["north"] > PILOT_BBOX["south"]
    assert PILOT_BBOX["east"] > PILOT_BBOX["west"]
    assert 25.0 < PILOT_BBOX["south"] < 26.0
    assert 25.0 < PILOT_BBOX["north"] < 26.0
    assert 84.5 < PILOT_BBOX["west"] < 86.0
    assert 84.5 < PILOT_BBOX["east"] < 86.0


# ---------------------------------------------------------------------------
# Day 6.2 — Offline / Cached Data
# ---------------------------------------------------------------------------

def test_day6_offline_forecast_cache_loading():
    """Verify that OpenMeteoClient loads the cached forecast offline without network."""
    client = OpenMeteoClient(cache_dir="data/cache")

    # Simulate network down
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("No network connection")):
        raw_data, is_from_cache = client.fetch_raw_forecast(
            latitude=PILOT_CENTER_LAT,
            longitude=PILOT_CENTER_LON,
            use_cache_on_failure=True,
        )

        assert is_from_cache is True
        assert "hourly" in raw_data
        assert "precipitation" in raw_data["hourly"]

        # Parse forecast
        forecast_res = client.parse_forecast(raw_data, from_cache=is_from_cache)
        assert forecast_res.from_cache is True
        assert forecast_res.summary.rain_1h >= 0.0
        assert forecast_res.summary.rain_3h >= 0.0
        assert forecast_res.summary.rain_6h >= 0.0


def test_day6_offline_pipeline_execution(offline_db: Path):
    """Verify end-to-end pipeline operates completely offline with network blocked."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        result = run_pipeline(
            latitude=PILOT_CENTER_LAT,
            longitude=PILOT_CENTER_LON,
            db_path=offline_db,
            cache_dir="data/cache",
            use_cache_on_failure=True,
            persist=True,
        )

        assert result.cells_processed == 1
        assert result.predictions_created == 3
        assert result.used_cached_forecast is True

        with sqlite3.connect(str(offline_db)) as conn:
            cnt = conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0]
            assert cnt == 3


# ---------------------------------------------------------------------------
# Day 6.3 — Failure Handling
# ---------------------------------------------------------------------------

def test_day6_failure_forecast_unavailable_no_cache(tmp_path: Path):
    """Verify ForecastUnavailableError when network fails and no cache exists."""
    empty_cache = tmp_path / "empty_cache"
    empty_cache.mkdir()
    test_db = tmp_path / "test_no_fc.db"
    init_db(test_db)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network down")):
        with pytest.raises(ForecastUnavailableError, match="No forecast record available"):
            run_pipeline(
                latitude=PILOT_CENTER_LAT,
                longitude=PILOT_CENTER_LON,
                db_path=test_db,
                cache_dir=empty_cache,
                use_cache_on_failure=True,
            )


def test_day6_failure_missing_spatial_cells(tmp_path: Path):
    """Verify EmptyCellsError is raised when cells table is empty, without fabricating data."""
    test_db = tmp_path / "test_empty_cells.db"
    init_db(test_db)
    from src.db.forecasts import init_db as init_forecast_db
    init_forecast_db(test_db)

    # Pre-seed forecast so forecast step succeeds
    now_iso = "2026-09-30T14:00:00+00:00"
    with sqlite3.connect(str(test_db)) as conn:
        conn.execute(
            """
            INSERT INTO forecasts (timestamp, rain_1h, rain_3h, rain_6h, location, source, retrieval_timestamp)
            VALUES (?, 10.0, 20.0, 30.0, 'Patna Pilot Municipal Area', 'Test', ?);
            """,
            (now_iso, now_iso),
        )

    with pytest.raises(EmptyCellsError, match="No spatial cells found"):
        run_pipeline(db_path=test_db, persist=False)


def test_day6_failure_invalid_coordinates():
    """Verify non-numeric or out-of-bounds coordinates return honest error without crashing."""
    # 1. Non-numeric coordinates
    res1 = safe_route(lat="invalid", lon=85.138)
    assert res1["status"] == "error"
    assert res1["found"] is False
    assert res1["route"] == []
    assert "Invalid origin coordinates" in res1["message"]

    # 2. Out of bounds latitude
    res2 = safe_route(lat=95.0, lon=85.138)
    assert res2["status"] == "error"
    assert res2["found"] is False
    assert res2["route"] == []

    # 3. Out of bounds longitude
    res3 = safe_route(lat=25.6, lon=200.0)
    assert res3["status"] == "error"
    assert res3["found"] is False
    assert res3["route"] == []


# ---------------------------------------------------------------------------
# Day 6.4 — Routing Reliability & Honest No-Route States
# ---------------------------------------------------------------------------

def test_day6_routing_hazard_avoidance():
    """Verify that router avoids designated HIGH-risk hazard zones."""
    router = OSMRouter()
    G = router._create_mock_graph()
    router.G = G

    # In mock graph:
    # Node 1: Start (13.0, 80.0)
    # Node 2: Route A (13.01, 80.0)
    # Node 3: Route B (13.0, 80.01)
    # Node 4: Dest (13.01, 80.01)

    # Flag Node 2 as HIGH risk
    hazard_zones = [{"lat": 13.01, "lon": 80.0, "radius_m": 500, "risk_level": "HIGH"}]

    res = router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones=hazard_zones)
    assert res["status"] == "success"
    # Route must go through Node 3 (13.0, 80.01), avoiding Node 2
    lats = [pt["lat"] for pt in res["route"]]
    assert 13.01 not in lats[:-1]  # Intermediate node is not Node 2


def test_day6_routing_blocked_path_returns_honest_no_route():
    """Verify that when all accessible routes are flooded, router returns honest no-route state."""
    router = OSMRouter()
    G = router._create_mock_graph()
    router.G = G

    # Flag BOTH Node 2 and Node 3 as HIGH risk -> completely blocked
    hazard_zones = [
        {"lat": 13.01, "lon": 80.0, "radius_m": 500, "risk_level": "HIGH"},
        {"lat": 13.0, "lon": 80.01, "radius_m": 500, "risk_level": "HIGH"},
    ]

    res = router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones=hazard_zones)
    assert res["status"] == "error"
    assert "No safe route" in res["message"]


def test_day6_routing_disclaimer_preservation():
    """Verify that the decision-support disclaimer is present in the citizen portal."""
    from app.citizen_view import get_bilingual_messages
    msgs = get_bilingual_messages()
    assert "Decision-support navigation path only; not a guaranteed safe evacuation route." in msgs["en"]["safe_route_note"]
    assert "केवल निर्णय-सहायता नेविगेशन मार्ग" in msgs["hi"]["safe_route_note"]
