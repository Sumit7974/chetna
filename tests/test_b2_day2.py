import pytest
import sqlite3
from src.model.predictor import FloodRiskPredictor
from src.sensors.interface import SimulatedSensorBackend, IoTSensorBackend
from src.routing.router import BasicRouter
from alerts.pipeline import AlertPipeline
from simulators.sensor_simulator import SensorReading, SimulationScenario
import datetime

def test_risk_prediction_logic():
    predictor = FloodRiskPredictor(db_path=":memory:")
    
    # Test HIGH risk
    pred = predictor.predict(120, 60, persist=False)
    assert pred.level == "HIGH"
    
    # Test MEDIUM risk
    pred = predictor.predict(70, 25, persist=False)
    assert pred.level == "MEDIUM"
    
    # Test LOW risk
    pred = predictor.predict(10, 5, persist=False)
    assert pred.level == "LOW"

def test_sensor_interface():
    backend = SimulatedSensorBackend(node_id="TEST_01", scenario=SimulationScenario.NORMAL)
    readings = backend.get_readings(limit=1)
    assert len(readings) == 1
    assert readings[0].node_id == "TEST_01"

    iot_backend = IoTSensorBackend(api_endpoint="http://example.com", api_key="secret")
    assert iot_backend.api_endpoint == "http://example.com"
    assert iot_backend.get_readings() == []

def test_router_stub():
    router = BasicRouter()
    route = router.find_safe_route((13.0, 80.0), (13.1, 80.1), [])
    assert len(route) == 2
    assert route[0] == (13.0, 80.0)

def test_pipeline_integration_risk_to_alert():
    db_conn = sqlite3.connect(":memory:")
    from database.db import init_db
    init_db(db_conn)
    
    pipeline = AlertPipeline(db_path=db_conn)
    
    # HIGH risk reading (but values below warning thresholds)
    # The predictor heuristic says wl > 100 or rr > 50 -> HIGH.
    # We will pass a normal reading but manually inject a high risk? No, the predictor acts on wl, rr.
    # If wl=105, critical is 120, warning is 75. So wl=105 is WARNING natively.
    # Let's pass wl=0, rr=55. warning rain=30, critical rain=60. 55 is WARNING natively. 
    # Let's mock the predictor to return HIGH for normal data to test the integration.
    
    class MockPredictor:
        def predict(self, *args, **kwargs):
            from src.model.predictor import RiskPrediction
            return RiskPrediction(cell_id="MOCK", timestamp="ts", horizon=1, level="HIGH", probability=0.99)
            
    pipeline.predictor = MockPredictor()
    
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Below all thresholds natively (INFO level normally)
    reading = SensorReading(node_id="MOCK", timestamp=now, water_level_cm=10, rainfall_rate_mm_h=10, battery_pct=100.0)
    
    res = pipeline.process(reading, persist=False)
    # Evaluator should bump INFO to WARNING due to HIGH risk
    assert res.evaluation.severity.value == "WARNING"
    assert "AI Risk Prediction is HIGH" in res.evaluation.reason
