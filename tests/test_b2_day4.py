import pytest
from src.routing.router import OSMRouter, haversine
from src.api.routing_api import get_safe_route

@pytest.fixture
def mock_router(monkeypatch):
    router = OSMRouter()
    # Force use of mock graph
    monkeypatch.setattr("src.routing.router.HAS_OSMNX", False)
    return router

def test_haversine_distance():
    # Roughly distance between 13.0, 80.0 and 13.01, 80.0
    dist = haversine(13.0, 80.0, 13.01, 80.0)
    assert 1100 < dist < 1200  # Should be ~1.11 km

def test_basic_a_star_routing(mock_router):
    result = mock_router.find_safe_route((13.0, 80.0), (13.01, 80.01))
    assert result["status"] == "success"
    assert len(result["route"]) > 0
    assert "distance_m" in result
    assert "estimated_time_min" in result

def test_hazard_avoidance(mock_router):
    # Place a medium hazard on Node 2 (13.01, 80.0)
    # The router should prefer going through Node 3 (13.0, 80.01)
    hazard_zones = [{"lat": 13.01, "lon": 80.0, "radius_m": 100, "risk_level": "MEDIUM"}]
    
    result = mock_router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones)
    assert result["status"] == "success"
    
    # Check that route avoids Node 2. Route should be Node 1 -> Node 3 -> Node 4
    lats = [r["lat"] for r in result["route"]]
    lons = [r["lon"] for r in result["route"]]
    
    assert 13.0 in lats  # Start
    assert 13.01 in lats # End
    
    # Node 3 is (13.0, 80.01). If we avoid Node 2, the intermediate is (13.0, 80.01)
    # Node 2 is (13.01, 80.0). It should NOT be in the route.
    assert {"lat": 13.01, "lon": 80.0} not in result["route"]
    assert {"lat": 13.0, "lon": 80.01} in result["route"]

def test_blocked_road_no_safe_route(mock_router):
    # Place a HIGH hazard blocking BOTH intermediate nodes
    hazard_zones = [
        {"lat": 13.01, "lon": 80.0, "radius_m": 100, "risk_level": "HIGH"},
        {"lat": 13.0, "lon": 80.01, "radius_m": 100, "risk_level": "HIGH"}
    ]
    
    result = mock_router.find_safe_route((13.0, 80.0), (13.01, 80.01), hazard_zones)
    assert result["status"] == "error"
    assert result["message"] == "No safe route is currently available."

def test_routing_api_validation(monkeypatch):
    # Invalid lat
    res = get_safe_route(100.0, 80.0, 13.0, 80.0)
    assert res["status"] == "error"
    assert "Invalid latitude" in res["message"]
    
    # Invalid lon
    res = get_safe_route(13.0, 200.0, 13.0, 80.0)
    assert res["status"] == "error"
    assert "Invalid longitude" in res["message"]
    
    # Missing
    res = get_safe_route(None, 80.0, 13.0, 80.0)
    assert res["status"] == "error"
    assert "required" in res["message"]
