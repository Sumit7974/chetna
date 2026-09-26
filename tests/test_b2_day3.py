import pytest
import sqlite3
from src.api.risk import get_current_risk
from database.db import init_db

@pytest.fixture
def test_db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn

@pytest.fixture
def mock_weather(monkeypatch):
    class MockSummary:
        rain_1h = 50.0
    class MockWeather:
        summary = MockSummary()
    monkeypatch.setattr("src.ingestion.weather.fetch_weather_forecast", lambda *args, **kwargs: MockWeather())

def test_get_current_risk_valid_data(monkeypatch, test_db_conn, mock_weather):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)

    # Use simulation=True to simulate flash flood conditions.
    result = get_current_risk("Velachery (Zone 13 - Adyar)", "+1h", simulation=True)
    
    assert "location" in result
    assert "risk_level" in result
    assert "risk_score" in result
    assert "updated_at" in result
    assert result["location"] == "Velachery (Zone 13 - Adyar)"
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]

    # Verify database persistence
    row = test_db_conn.execute("SELECT * FROM risk_predictions WHERE cell_id=?", ("Velachery (Zone 13 - Adyar)",)).fetchone()
    assert row is not None
    assert row["level"] == result["risk_level"]
    assert row["probability"] == result["risk_score"]

def test_missing_weather_handled(monkeypatch, test_db_conn):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)
    
    def mock_fetch(*args, **kwargs):
        raise Exception("Weather API Error")
    monkeypatch.setattr("src.ingestion.weather.fetch_weather_forecast", mock_fetch)
    
    result = get_current_risk("TestArea", "+1h", latitude=13.0, longitude=80.0)
    assert result["rainfall_rate_mm_h"] == 0.0
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]
    assert result["persisted"] is True
    
    # Verify it still persists despite missing weather
    row = test_db_conn.execute("SELECT * FROM risk_predictions WHERE cell_id=?", ("TestArea",)).fetchone()
    assert row is not None

def test_invalid_location_handled(monkeypatch, test_db_conn, mock_weather):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)
    
    # Just an arbitrary location name, should default to NORMAL scenario
    result = get_current_risk("Unknown Area", "+3h", latitude=13.0, longitude=80.0, simulation=False)
    assert result["location"] == "Unknown Area"
    assert result["persisted"] is True
    row = test_db_conn.execute("SELECT * FROM risk_predictions WHERE cell_id=?", ("Unknown Area",)).fetchone()
    assert row is not None

def test_missing_coordinates(monkeypatch, test_db_conn, mock_weather):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)
    
    # Missing lat/lon should trigger warning but proceed with Chennai fallback
    result = get_current_risk("Missing Coords Area", "+1h", simulation=False)
    assert result["persisted"] is True
    assert result["location"] == "Missing Coords Area"

def test_invalid_coordinates():
    with pytest.raises(ValueError, match="Invalid latitude"):
        get_current_risk("Bad Lat", latitude=100.0, longitude=80.0)
    
    with pytest.raises(ValueError, match="Invalid longitude"):
        get_current_risk("Bad Lon", latitude=13.0, longitude=200.0)

def test_database_persistence_failure(monkeypatch, test_db_conn, mock_weather):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)
    
    # Drop the table to force a persistence error
    test_db_conn.execute("DROP TABLE risk_predictions")
    
    result = get_current_risk("Failing DB Area", "+1h", latitude=13.0, longitude=80.0, simulation=False)
    assert result["location"] == "Failing DB Area"
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]
    # The API should explicitly indicate that persistence failed
    assert result["persisted"] is False

def test_velachery_does_not_force_flash_flood(monkeypatch, test_db_conn):
    """
    Test proving that the string 'Velachery' in location_name does not 
    automatically trigger a flash flood simulation when simulation=False.
    """
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)

    # Use a weather mock that returns 0 rainfall
    class MockSummary:
        rain_1h = 0.0
        rain_3h = 0.0
        rain_6h = 0.0
        rain_past_24h = 0.0
    class MockWeather:
        summary = MockSummary()
    monkeypatch.setattr("src.ingestion.weather.fetch_weather_forecast", lambda *args, **kwargs: MockWeather())

    result = get_current_risk("Velachery (Zone 13 - Adyar)", "+1h", latitude=12.98, longitude=80.22, simulation=False)
    
    # If it was a simulation, water level or rainfall would be overridden high
    # Since it's normal and there is no rain/water, risk should be LOW
    assert result["risk_level"] == "LOW"
    # Normal simulation still has ambient noise, but it shouldn't hit flash flood levels (>60)
    assert result["water_level_cm"] < 60.0
    assert result["rainfall_rate_mm_h"] == 0.0


