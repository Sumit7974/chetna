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
    
    result = get_current_risk("TestArea", "+1h")
    assert result["rainfall_rate_mm_h"] == 0.0
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]
    
    # Verify it still persists despite missing weather
    row = test_db_conn.execute("SELECT * FROM risk_predictions WHERE cell_id=?", ("TestArea",)).fetchone()
    assert row is not None

def test_invalid_location_handled(monkeypatch, test_db_conn, mock_weather):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: test_db_conn)
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: test_db_conn)
    
    # Just an arbitrary location name, should default to NORMAL scenario
    result = get_current_risk("Unknown Area", "+3h", simulation=False)
    assert result["location"] == "Unknown Area"
    row = test_db_conn.execute("SELECT * FROM risk_predictions WHERE cell_id=?", ("Unknown Area",)).fetchone()
    assert row is not None
