"""API endpoint for retrieving current risk prediction."""

import logging
import datetime
from typing import Dict, Any

def get_current_risk(location_name: str, horizon: str = "Current Conditions", latitude: float = 13.0827, longitude: float = 80.2707, simulation: bool = False) -> Dict[str, Any]:
    """Retrieve dynamic flood risk prediction for a location based on weather and sensor data."""
    from src.ingestion.weather import fetch_weather_forecast
    from src.sensors.interface import SimulatedSensorBackend
    from simulators.sensor_simulator import SimulationScenario, SensorReading
    from src.model.predictor import FloodRiskPredictor
    from alerts.pipeline import AlertPipeline

    try:
        weather = fetch_weather_forecast(latitude, longitude, timeout=3.0, use_cache_on_failure=True)
        if weather and weather.summary:
            if "+1h" in horizon:
                rain_rate = weather.summary.rain_1h
            elif "+3h" in horizon:
                rain_rate = weather.summary.rain_3h / 3.0
            elif "+6h" in horizon:
                rain_rate = weather.summary.rain_6h / 6.0
            else:
                rain_rate = weather.summary.rain_past_24h / 24.0
        else:
            rain_rate = 0.0
    except Exception as e:
        logging.warning(f"Weather API failed: {e}")
        rain_rate = 0.0

    try:
        scenario = SimulationScenario.FLASH_FLOOD if simulation else SimulationScenario.NORMAL
        backend = SimulatedSensorBackend(node_id=location_name, scenario=scenario)
        readings = backend.get_readings(limit=1)
        reading = readings[0] if readings else None
        if reading:
            reading.rainfall_rate_mm_h = rain_rate
            water_level = reading.water_level_cm if reading.water_level_cm is not None else 0.0
        else:
            water_level = 0.0
    except Exception as e:
        logging.warning(f"Sensor fetch failed: {e}")
        reading = None
        water_level = 0.0

    if not reading:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        reading = SensorReading(node_id=location_name, timestamp=now, water_level_cm=water_level, rainfall_rate_mm_h=rain_rate, battery_pct=100.0)

    try:
        predictor = FloodRiskPredictor()
        pred = predictor.predict(water_level_cm=water_level, rainfall_rate_mm_h=rain_rate, cell_id=location_name, persist=True)
        risk_level = pred.level
        risk_score = pred.probability
        updated_at = pred.timestamp
    except Exception as e:
        logging.error(f"Prediction failed: {e}")
        risk_level = "UNKNOWN"
        risk_score = 0.0
        updated_at = "N/A"

    try:
        pipeline = AlertPipeline()
        pipeline.process(reading, affected_area=location_name, persist=True)
    except Exception as e:
        logging.error(f"Alert pipeline failed: {e}")

    return {
        "location": location_name,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "updated_at": updated_at,
        "water_level_cm": water_level,
        "rainfall_rate_mm_h": rain_rate
    }

