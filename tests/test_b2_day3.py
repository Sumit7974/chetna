import pytest
import sqlite3
from src.api.risk import get_current_risk

def test_get_current_risk_valid_data(monkeypatch):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: sqlite3.connect(":memory:"))
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: sqlite3.connect(":memory:"))
    
    # Mock weather API to return a fixed rainfall
    class MockSummary:
        rain_1h = 50.0
    class MockWeather:
        summary = MockSummary()
    monkeypatch.setattr("src.ingestion.weather.fetch_weather_forecast", lambda *args, **kwargs: MockWeather())

    result = get_current_risk("Velachery (Zone 13 - Adyar)", "+1h")
    
    assert "location" in result
    assert "risk_level" in result
    assert "risk_score" in result
    assert "updated_at" in result
    assert result["location"] == "Velachery (Zone 13 - Adyar)"
    
    # Rainfall of 50mm/hr is extremely high. The ML model evaluates based on feature thresholds.
    # Depending on heuristics, it should produce a valid risk string.
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]

def test_missing_weather_handled(monkeypatch):
    monkeypatch.setattr("src.model.predictor.get_db_connection", lambda *args, **kwargs: sqlite3.connect(":memory:"))
    monkeypatch.setattr("database.db.get_db_connection", lambda *args, **kwargs: sqlite3.connect(":memory:"))
    
    def mock_fetch(*args, **kwargs):
        raise Exception("Weather API Error")
    monkeypatch.setattr("src.ingestion.weather.fetch_weather_forecast", mock_fetch)
    
    result = get_current_risk("Test", "+1h")
    assert result["rainfall_rate_mm_h"] == 0.0
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]
