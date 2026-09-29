"""Comprehensive integration and replay test suite for Chetna B1 Day 5.

Verifies:
1. Replay pipeline execution with Patna-specific spatial cells, grid, and CRS.
2. Deterministic and repeatable Simulate Heavy Rain scenario.
3. Clean reset / baseline mechanism with zero transient residue.
4. Full B1 integration: forecast -> features -> prediction -> database -> routing.
5. Honest failure handling: no fabricated routes, no fabricated risk, no silent Chennai fallback.
6. Stale city protection: pilot coordinates, bounds, CRS, and location labels.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.alert_service import create_draft_alert
from app.demo_scenario import (
    reset_to_baseline_scenario,
    run_end_to_end_pipeline,
    simulate_heavy_rain_scenario,
)
from database.db import init_db
from src.db.spatial import init_spatial_db
from src.db.forecasts import get_latest_forecast
from src.ingestion.pilot_config import (
    GEOGRAPHIC_CRS,
    PILOT_BBOX,
    PILOT_CENTER_LAT,
    PILOT_CENTER_LON,
    PILOT_CITY,
    PILOT_LOCATION_LABEL,
    PROJECTED_CRS,
)
from src.model.predictor import FloodRiskPredictor
from src.pipeline import (
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    EmptyCellsError,
    ForecastUnavailableError,
    PipelineResult,
    run_pipeline,
)
from src.routing.router import safe_route


@pytest.fixture
def patna_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database seeded with authentic Patna spatial baseline."""
    db_file = tmp_path / "test_patna_b1_day5.db"
    init_db(db_file)
    init_spatial_db(db_file)

    # Seed representative Patna cells
    patna_cells = [
        ("CELL_RAJ_01", '{"type":"Polygon","coordinates":[]}', 49.5, 0.3, 75000.0, 0.88),
        ("CELL_KAN_02", '{"type":"Polygon","coordinates":[]}', 50.2, 0.4, 62000.0, 0.74),
        ("CELL_SAI_03", '{"type":"Polygon","coordinates":[]}', 48.0, 0.2, 90000.0, 0.92),
        ("CELL_BOR_04", '{"type":"Polygon","coordinates":[]}', 51.5, 0.6, 35000.0, 0.45),
        ("CELL_BAI_05", '{"type":"Polygon","coordinates":[]}', 53.0, 0.8, 22000.0, 0.30),
    ]

    patna_shelters = [
        ("mock_shl_01", "Patna Junction Elevated Concourse", 25.602, 85.138, "shelter"),
        ("mock_shl_02", "Moin-ul-Haq Stadium Complex", 25.605, 85.168, "shelter"),
        ("mock_shl_03", "Pataliputra Sports Complex Kankarbagh", 25.596, 85.155, "shelter"),
        ("mock_shl_06", "Rajendra Nagar Terminal Concourse", 25.599, 85.164, "shelter"),
    ]

    with sqlite3.connect(str(db_file)) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO cells (id, geometry, elevation, slope, flow_acc, vulnerability)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            patna_cells,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO grid_cells (cell_id, row, col, centroid_lat, centroid_lon, elevation_m, geometry_geojson)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            [
                ("CELL_RAJ_01", 1, 1, 25.6012, 85.1634, 49.5, '{"type":"Point","coordinates":[85.1634,25.6012]}'),
                ("CELL_KAN_02", 1, 2, 25.5945, 85.1582, 50.2, '{"type":"Point","coordinates":[85.1582,25.5945]}'),
                ("CELL_SAI_03", 2, 1, 25.6121, 85.1754, 48.0, '{"type":"Point","coordinates":[85.1754,25.6121]}'),
                ("CELL_BOR_04", 2, 2, 25.6150, 85.1200, 51.5, '{"type":"Point","coordinates":[85.1200,25.6150]}'),
                ("CELL_BAI_05", 3, 1, 25.6120, 85.0840, 53.0, '{"type":"Point","coordinates":[85.0840,25.6120]}'),
            ],
        )

    # Populate shelters and roads via authoritative B1 spatial loaders
    import geopandas as gpd
    from src.db.spatial import save_facilities, save_roads
    shl_path = Path("data/osm/osm_shelters_fixture.geojson")
    roads_path = Path("data/osm/osm_roads_fixture.geojson")
    if shl_path.exists():
        save_facilities(gpd.read_file(str(shl_path)), "shelters", db_file, is_synthetic=True)
    if roads_path.exists():
        save_roads(gpd.read_file(str(roads_path)), db_file, is_synthetic=True)

    return db_file


def test_b1_day5_replay_pipeline_patna(patna_db: Path):
    """Verify B1 forecast-to-risk pipeline executes reproducibly for Patna pilot."""
    # Pre-seed forecast
    now_iso = "2026-09-30T10:00:00+00:00"
    with sqlite3.connect(str(patna_db)) as conn:
        conn.execute(
            """
            INSERT INTO forecasts (timestamp, rain_1h, rain_3h, rain_6h, location, source, retrieval_timestamp)
            VALUES (?, 45.0, 75.0, 110.0, 'Patna Pilot Municipal Area', 'Replay Ingestion', ?);
            """,
            (now_iso, now_iso),
        )

    with patch("src.pipeline.fetch_and_store_forecast") as mock_fetch:
        mock_fetch.side_effect = RuntimeError("Offline replay mode")

        result = run_pipeline(
            latitude=PILOT_CENTER_LAT,
            longitude=PILOT_CENTER_LON,
            db_path=patna_db,
            use_cache_on_failure=True,
            persist=True,
        )

    assert isinstance(result, PipelineResult)
    assert result.cells_processed == 5
    assert result.predictions_created == 15  # 5 cells * 3 horizons
    assert result.horizons_processed == [1, 3, 6]
    assert result.forecast_rain_1h == 45.0
    assert result.forecast_rain_3h == 75.0
    assert result.forecast_rain_6h == 110.0

    # Verify risk_predictions table received records
    with sqlite3.connect(str(patna_db)) as conn:
        count = conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0]
        assert count == 15

        # Check high-vulnerability cell produced elevated risk
        high_risk = conn.execute(
            "SELECT level, probability FROM risk_predictions WHERE cell_id = 'CELL_SAI_03' AND horizon = 6;"
        ).fetchone()
        assert high_risk[0] == "HIGH"
        assert high_risk[1] >= 0.70


def test_b1_day5_simulate_heavy_rain_repeatability(patna_db: Path):
    """Verify deterministic repeatability of Simulate Heavy Rain scenario."""
    fixed_ts = "2026-09-30T12:00:00+00:00"

    # Run 1
    res1 = simulate_heavy_rain_scenario(db_path=patna_db)
    with sqlite3.connect(str(patna_db)) as conn:
        conn.row_factory = sqlite3.Row
        preds1 = [dict(r) for r in conn.execute("SELECT cell_id, horizon, level, probability FROM risk_predictions ORDER BY cell_id, horizon;").fetchall()]
        fc1 = dict(conn.execute("SELECT rain_1h, rain_3h, rain_6h, location FROM forecasts ORDER BY id DESC LIMIT 1;").fetchone())

    # Reset
    reset_to_baseline_scenario(db_path=patna_db)
    with sqlite3.connect(str(patna_db)) as conn:
        assert conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0] == 0

    # Run 2
    res2 = simulate_heavy_rain_scenario(db_path=patna_db)
    with sqlite3.connect(str(patna_db)) as conn:
        conn.row_factory = sqlite3.Row
        preds2 = [dict(r) for r in conn.execute("SELECT cell_id, horizon, level, probability FROM risk_predictions ORDER BY cell_id, horizon;").fetchall()]
        fc2 = dict(conn.execute("SELECT rain_1h, rain_3h, rain_6h, location FROM forecasts ORDER BY id DESC LIMIT 1;").fetchone())

    # Strict repeatability assertions
    assert res1["predictions_created"] == res2["predictions_created"] == 15
    assert res1["sensors_updated"] == res2["sensors_updated"] == 10
    assert fc1 == fc2
    assert fc1["location"] == "Patna Pilot Municipal Area"
    assert len(preds1) == len(preds2) == 15
    for p1, p2 in zip(preds1, preds2):
        assert p1["cell_id"] == p2["cell_id"]
        assert p1["horizon"] == p2["horizon"]
        assert p1["level"] == p2["level"]
        assert round(p1["probability"], 4) == round(p2["probability"], 4)


def test_b1_day5_clean_reset_cycle(patna_db: Path):
    """Verify NORMAL -> SIMULATE HEAVY RAIN -> RISK ELEVATION -> ALERT -> RESET -> NORMAL."""
    # 1. NORMAL Baseline
    with sqlite3.connect(str(patna_db)) as conn:
        assert conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM sensor_readings;").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM alerts;").fetchone()[0] == 0
        static_cell_count = conn.execute("SELECT count(*) FROM cells;").fetchone()[0]
        assert static_cell_count == 5

    # 2. SIMULATE HEAVY RAIN
    sim_res = simulate_heavy_rain_scenario(db_path=patna_db)
    assert sim_res["success"] is True

    # 3. RISK ELEVATION
    with sqlite3.connect(str(patna_db)) as conn:
        pred_cnt = conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0]
        assert pred_cnt == 15
        sensor_cnt = conn.execute("SELECT count(*) FROM sensor_readings;").fetchone()[0]
        assert sensor_cnt > 0

    # 4. ALERT STATE
    draft_id = create_draft_alert(
        severity="WARNING",
        title="Patna Monsoon Inundation Advisory",
        message="Critical sump surge detected in Rajendra Nagar basin.",
        affected_area=PILOT_LOCATION_LABEL,
        db_path=patna_db,
    )
    assert draft_id.startswith("ALT-DRAFT-")

    # 5. RESET
    rst_res = reset_to_baseline_scenario(db_path=patna_db)
    assert rst_res["success"] is True
    assert rst_res["scenario"] == "BASELINE"

    # 6. NORMAL Verified
    with sqlite3.connect(str(patna_db)) as conn:
        assert conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM sensor_readings;").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM alerts;").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM alert_logs;").fetchone()[0] == 0
        # Spatial static infrastructure must be completely unharmed
        assert conn.execute("SELECT count(*) FROM cells;").fetchone()[0] == static_cell_count
        assert conn.execute("SELECT count(*) FROM shelters;").fetchone()[0] >= 4


def test_b1_day5_routing_integration(patna_db: Path):
    """Verify routing integrates with B1 spatial data, avoids high-risk zones, and outputs honest routes."""
    # Origin: Boring Canal / Patliputra sector (25.620, 85.110)
    res = safe_route(lat=25.620, lon=85.110, horizon=1, db_path=patna_db)
    assert res["status"] == "success"
    assert res["found"] is True
    assert len(res["route"]) >= 2
    assert res["distance_m"] > 0
    assert res["destination"] is not None
    assert "Patna" in res["destination"]["name"] or "Patliputra" in res["destination"]["name"] or "Stadium" in res["destination"]["name"] or "Shelter" in res["destination"]["name"]

    # Verify no fabricated coordinates outside bounds
    for pt in res["route"]:
        assert PILOT_BBOX["south"] - 0.1 <= pt["lat"] <= PILOT_BBOX["north"] + 0.1
        assert PILOT_BBOX["west"] - 0.1 <= pt["lon"] <= PILOT_BBOX["east"] + 0.1


def test_b1_day5_honest_failure_handling(patna_db: Path):
    """Verify system produces honest no-route and no-data states without fabricating geometry or risk."""
    # 1. Invalid coordinates
    res_inv = safe_route(lat="invalid", lon=85.138, db_path=patna_db)
    assert res_inv["status"] == "error"
    assert res_inv["found"] is False
    assert res_inv["route"] == []
    assert "Invalid origin coordinates" in res_inv["message"]

    # 2. Out of bounds coordinates
    res_oob = safe_route(lat=100.0, lon=85.138, db_path=patna_db)
    assert res_oob["status"] == "error"
    assert res_oob["found"] is False
    assert res_oob["route"] == []

    # 3. Empty shelters
    res_no_shl = safe_route(lat=25.601, lon=85.163, db_path=patna_db, shelters=[])
    assert res_no_shl["status"] == "error"
    assert res_no_shl["found"] is False
    assert res_no_shl["route"] == []
    assert "No shelters available" in res_no_shl["message"]

    # 4. Empty cells table in pipeline raises EmptyCellsError without fabricating risk
    empty_db = patna_db.parent / "empty_cells.db"
    init_db(empty_db)
    with patch("src.pipeline.fetch_and_store_forecast", return_value=(None, 1)):
        with patch("src.pipeline.get_latest_forecast", return_value={"timestamp": "now", "rain_1h": 10, "rain_3h": 20, "rain_6h": 30}):
            with pytest.raises(EmptyCellsError, match="No spatial cells found"):
                run_pipeline(db_path=empty_db)


def test_b1_day5_stale_city_protection():
    """Verify authoritative pilot configuration protects against stale Chennai artifacts."""
    assert PILOT_CITY == "Patna"
    assert PROJECTED_CRS == "EPSG:32645"
    assert GEOGRAPHIC_CRS == "EPSG:4326"
    assert round(DEFAULT_LATITUDE, 4) == round(PILOT_CENTER_LAT, 4)
    assert round(DEFAULT_LONGITUDE, 4) == round(PILOT_CENTER_LON, 4)
    assert 25.5 <= PILOT_CENTER_LAT <= 25.7
    assert 85.0 <= PILOT_CENTER_LON <= 85.3
