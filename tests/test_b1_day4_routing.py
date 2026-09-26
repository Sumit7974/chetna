"""Unit and integration tests for Chetna B1 Day 4 Safe Routing / Safest-Location Engine."""

from __future__ import annotations

import sqlite3
import pytest
import geopandas as gpd
from shapely.geometry import LineString, Point

from src.routing.router import (
    OSMRouter,
    build_road_graph_from_roads,
    connect_graph_to_grid,
    apply_risk_predictions_to_graph,
    haversine,
    safe_route,
)
from src.db.spatial import (
    init_spatial_db,
    save_facilities,
    save_grid_cells,
    save_roads,
)


@pytest.fixture
def mock_router():
    """Create an OSMRouter with the deterministic 4-node mock graph."""
    router = OSMRouter()
    router.G = router._create_mock_graph()
    return router


@pytest.fixture
def sample_shelters():
    """Sample candidate emergency shelters."""
    return [
        {
            "id": "shl_01",
            "name": "Velachery Relief Shelter",
            "latitude": 13.01,
            "longitude": 80.01,
            "amenity": "shelter",
        },
        {
            "id": "shl_02",
            "name": "Alandur Metro Concourse",
            "latitude": 13.05,
            "longitude": 80.20,
            "amenity": "shelter",
        },
    ]


def test_build_road_graph_from_roads():
    """Verify that build_road_graph_from_roads creates a valid NetworkX MultiDiGraph."""
    roads_data = [
        {
            "osm_id": "r1",
            "name": "Arterial Road",
            "highway": "primary",
            "geometry": LineString([(80.0, 13.0), (80.01, 13.0), (80.01, 13.01)]),
        },
        {
            "osm_id": "r2",
            "name": "Secondary Bypass",
            "highway": "secondary",
            "geometry": LineString([(80.0, 13.0), (80.0, 13.01), (80.01, 13.01)]),
        },
    ]
    gdf = gpd.GeoDataFrame(roads_data, geometry="geometry", crs="EPSG:4326")
    G = build_road_graph_from_roads(gdf)

    assert G.number_of_nodes() == 4
    assert G.number_of_edges() >= 4  # Bidirectional segments
    for _, data in G.nodes(data=True):
        assert "y" in data and "x" in data
        assert -90.0 <= data["y"] <= 90.0
        assert -180.0 <= data["x"] <= 180.0


def test_connect_graph_to_grid_and_apply_risk():
    """Verify that graph nodes connect to ~200 m cells and receive risk levels."""
    router = OSMRouter()
    G = router._create_mock_graph()

    grid_cells = [
        {"cell_id": "CELL_001", "centroid_lat": 13.0, "centroid_lon": 80.0, "elevation_m": 8.5},
        {"cell_id": "CELL_002", "centroid_lat": 13.01, "centroid_lon": 80.0, "elevation_m": 5.2},
        {"cell_id": "CELL_003", "centroid_lat": 13.0, "centroid_lon": 80.01, "elevation_m": 9.1},
        {"cell_id": "CELL_004", "centroid_lat": 13.01, "centroid_lon": 80.01, "elevation_m": 7.0},
    ]
    G = connect_graph_to_grid(G, grid_cells)

    # Node 1 is at (13.0, 80.0) -> mapped to CELL_001
    assert G.nodes[1].get("cell_id") == "CELL_001"
    assert G.nodes[2].get("cell_id") == "CELL_002"

    # Apply HIGH risk to CELL_002 (Node 2)
    predictions = {
        "CELL_002": {"level": "HIGH", "probability": 0.88},
        "CELL_003": {"level": "LOW", "probability": 0.15},
    }
    G, hazards = apply_risk_predictions_to_graph(G, predictions)

    assert G.nodes[2]["risk_level"] == "HIGH"
    assert G.nodes[2]["risk_probability"] == 0.88
    assert G.nodes[3]["risk_level"] == "LOW"
    assert len(hazards) == 1
    assert hazards[0]["cell_id"] == "CELL_002"


def test_safe_route_valid(mock_router, sample_shelters):
    """A* returns a valid safe route to the destination shelter."""
    res = safe_route(
        lat=13.0,
        lon=80.0,
        router=mock_router,
        shelters=sample_shelters,
    )

    assert res["status"] == "success"
    assert res["found"] is True
    assert len(res["route"]) > 0
    assert res["destination"] is not None
    assert res["destination"]["name"] == "Velachery Relief Shelter"
    assert res["distance_m"] > 0
    assert res["estimated_time_min"] > 0


def test_safe_route_hazard_avoidance(mock_router):
    """A route crossing a HIGH-risk cell is avoided when an alternative safe path exists."""
    # Node 2 (13.01, 80.0) is HIGH risk
    hazard_zones = [{"lat": 13.01, "lon": 80.0, "radius_m": 100, "risk_level": "HIGH"}]
    shelters = [{"id": "s1", "name": "Safe Shelter", "latitude": 13.01, "longitude": 80.01}]

    res = safe_route(
        lat=13.0,
        lon=80.0,
        router=mock_router,
        shelters=shelters,
        hazard_zones=hazard_zones,
    )

    assert res["status"] == "success"
    assert res["found"] is True
    # The route must avoid Node 2 (13.01, 80.0) and take Node 3 (13.0, 80.01)
    route_points = [(r["lat"], r["lon"]) for r in res["route"]]
    assert (13.01, 80.0) not in route_points
    assert (13.0, 80.01) in route_points


def test_safe_route_nearest_reachable_shelter(mock_router):
    """Select the nearest reachable shelter, skipping one whose route is entirely blocked."""
    # Closer shelter at Node 2 (13.01, 80.0), but Node 2 is flooded with HIGH risk
    # Farther shelter at Node 4 (13.01, 80.01), which is safely reachable via Node 3 (13.0, 80.01)
    shelters = [
        {"id": "s_close", "name": "Flooded Shelter", "latitude": 13.01, "longitude": 80.0},
        {"id": "s_safe", "name": "Accessible Shelter", "latitude": 13.01, "longitude": 80.01},
    ]
    hazard_zones = [{"lat": 13.01, "lon": 80.0, "radius_m": 200, "risk_level": "HIGH"}]

    res = safe_route(
        lat=13.0,
        lon=80.0,
        router=mock_router,
        shelters=shelters,
        hazard_zones=hazard_zones,
    )

    assert res["status"] == "success"
    assert res["found"] is True
    assert res["destination"]["name"] == "Accessible Shelter"


def test_safe_route_no_safe_route(mock_router):
    """When all routes are blocked by HIGH-risk hazard zones, return clear structured error."""
    # Block both intermediate branches (Node 2 and Node 3)
    hazard_zones = [
        {"lat": 13.01, "lon": 80.0, "radius_m": 150, "risk_level": "HIGH"},
        {"lat": 13.0, "lon": 80.01, "radius_m": 150, "risk_level": "HIGH"},
    ]
    shelters = [{"id": "s1", "name": "Target Shelter", "latitude": 13.01, "longitude": 80.01}]

    res = safe_route(
        lat=13.0,
        lon=80.0,
        router=mock_router,
        shelters=shelters,
        hazard_zones=hazard_zones,
    )

    assert res["status"] == "error"
    assert res["found"] is False
    assert res["route"] == []
    assert res["destination"] is None
    assert "No safe route" in res["message"]


def test_safe_route_invalid_coordinates(mock_router, sample_shelters):
    """Invalid coordinates are handled cleanly without crashing."""
    # Out of latitude range
    res1 = safe_route(lat=95.0, lon=80.0, router=mock_router, shelters=sample_shelters)
    assert res1["status"] == "error"
    assert res1["found"] is False
    assert "Invalid origin coordinates" in res1["message"]

    # Out of longitude range
    res2 = safe_route(lat=13.0, lon=250.0, router=mock_router, shelters=sample_shelters)
    assert res2["status"] == "error"
    assert res2["found"] is False

    # None or non-numeric
    res3 = safe_route(lat=None, lon=80.0, router=mock_router, shelters=sample_shelters)
    assert res3["status"] == "error"
    assert res3["found"] is False


def test_safe_route_missing_shelters(mock_router):
    """Gracefully handles missing or empty shelter records."""
    res = safe_route(lat=13.0, lon=80.0, router=mock_router, shelters=[])
    assert res["status"] == "error"
    assert res["found"] is False
    assert "No shelters available" in res["message"]


def test_safe_route_sqlite_integration(tmp_path):
    """End-to-end integration test with SQLite database and risk_predictions table."""
    db_file = tmp_path / "test_routing.db"
    init_spatial_db(db_file)

    # 1. Populate shelters table
    shelters_gdf = gpd.GeoDataFrame(
        [
            {
                "osm_id": "shl_test_01",
                "name": "Integrated Test Shelter",
                "latitude": 13.01,
                "longitude": 80.01,
                "geometry": Point(80.01, 13.01),
                "source": "Test",
                "is_synthetic": True,
            }
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    save_facilities(shelters_gdf, "shelters", db_path=db_file)

    # 2. Populate grid_cells
    grid_cells = [
        {"cell_id": "C_TEST_01", "row": 0, "col": 0, "centroid_lat": 13.0, "centroid_lon": 80.0, "geometry": Point(80.0, 13.0).buffer(0.001)},
        {"cell_id": "C_TEST_02", "row": 0, "col": 1, "centroid_lat": 13.01, "centroid_lon": 80.0, "geometry": Point(80.0, 13.01).buffer(0.001)},
        {"cell_id": "C_TEST_03", "row": 1, "col": 0, "centroid_lat": 13.0, "centroid_lon": 80.01, "geometry": Point(80.01, 13.0).buffer(0.001)},
        {"cell_id": "C_TEST_04", "row": 1, "col": 1, "centroid_lat": 13.01, "centroid_lon": 80.01, "geometry": Point(80.01, 13.01).buffer(0.001)},
    ]
    save_grid_cells(gpd.GeoDataFrame(grid_cells, geometry="geometry", crs="EPSG:4326"), db_path=db_file)

    # 3. Populate risk_predictions table with HIGH risk on C_TEST_02
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                horizon INTEGER NOT NULL,
                level TEXT NOT NULL,
                probability REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            "INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability) VALUES (?, datetime('now'), ?, ?, ?)",
            ("C_TEST_02", 1, "HIGH", 0.92)
        )
    conn.close()

    # 4. Use mock router for graph topology
    mock_r = OSMRouter(db_path=db_file)
    mock_r.G = mock_r._create_mock_graph()
    mock_r.G = connect_graph_to_grid(mock_r.G, db_path=db_file)

    # 5. Run safe_route
    res = safe_route(13.0, 80.0, horizon=1, db_path=db_file, router=mock_r)

    assert res["status"] == "success"
    assert res["found"] is True
    assert res["destination"]["name"] == "Integrated Test Shelter"
    # Ensure route bypassed flooded C_TEST_02 (13.01, 80.0)
    route_coords = [(r["lat"], r["lon"]) for r in res["route"]]
    assert (13.01, 80.0) not in route_coords
