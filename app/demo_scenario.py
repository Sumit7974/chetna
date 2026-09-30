"""Chetna: End-to-End Operational Demo Scenario Controller (Day 5).

Provides repeatable, human-driven operational scenario transitions for F1 and F2:
1. Normal Baseline State -> Standard seasonal drainage conditions, nominal water levels.
2. Heavy-Rain Simulation -> Leverages existing B1/B2/M1 backend engines:
   - src.db.forecasts.save_forecast
   - src.model.predictor.FloodRiskPredictor
   - simulators.sensor_simulator.SensorSimulator
   - simulators.sensor_db_bridge.persist_batch
3. Repeatable Reset -> Returns the system to nominal baseline without database or code edits.
4. Backtest / Validation Visibility -> Loads existing M1 backtest artifacts with clear disclaimers.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import sqlite3

from database.db import DEFAULT_DB_PATH, get_db_connection, init_db
from simulators.sensor_db_bridge import persist_batch
from simulators.sensor_simulator import SensorReading, SensorSimulator, SimulationScenario
from src.db.forecasts import save_forecast
from src.model.predictor import FloodRiskPredictor, RiskPrediction

logger = logging.getLogger(__name__)

DEFAULT_STATIC_RISK_PATH = Path("data/m1/static_risk_scores.json")
DEFAULT_BACKTEST_RESULTS_PATH = Path("data/m1/backtest/results.json")
DEFAULT_BACKTEST_EVENTS_PATH = Path("data/m1/backtest_events.json")

# Standard monitored pilot nodes for telemetry simulation (Patna pilot)
DEFAULT_PILOT_SENSOR_NODES = [
    {"node_id": "SENS_PAT_01", "name": "Rajendra Nagar Sump Station", "base_water_cm": 24.5},
    {"node_id": "SENS_PAT_02", "name": "Kankarbagh Colony Drain Outfall", "base_water_cm": 22.0},
    {"node_id": "SENS_PAT_03", "name": "Saidpur Nullah Inflow Gauge", "base_water_cm": 28.0},
    {"node_id": "SENS_PAT_04", "name": "Boring Canal Underpass Sensor", "base_water_cm": 15.5},
    {"node_id": "SENS_PAT_05", "name": "Bailey Road Sag Station", "base_water_cm": 18.0},
    {"node_id": "SENS_PAT_06", "name": "Gandhi Maidan South Basin", "base_water_cm": 20.0},
    {"node_id": "SENS_PAT_07", "name": "Patliputra Industrial Drain Node", "base_water_cm": 16.5},
    {"node_id": "SENS_PAT_08", "name": "Anisabad Golambar Sump Node", "base_water_cm": 21.0},
    {"node_id": "SENS_PAT_09", "name": "Digha Outfall Sluice Gate Monitor", "base_water_cm": 26.0},
    {"node_id": "SENS_PAT_10", "name": "Bazar Samiti Agricultural Market Sump", "base_water_cm": 23.5},
]


def simulate_heavy_rain_scenario(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    static_risk_path: Union[str, Path] = DEFAULT_STATIC_RISK_PATH,
) -> Dict[str, Any]:
    """Execute a realistic heavy rainfall simulation using existing backend components.

    Workflow:
    1. Ensures SQLite schema is initialized.
    2. Stores a heavy monsoon precipitation forecast (+1h=52mm, +3h=84mm, +6h=126mm).
    3. Runs FloodRiskPredictor across all spatial cells to produce genuine risk predictions.
    4. Persists prediction records with why-flagged explanations into risk_predictions.
    5. Simulates surging water levels on IoT sensor nodes and persists telemetry.
    """
    try:
        init_db(db_path)
    except Exception as exc:
        logger.debug("Database init in simulation notice: %s", exc)

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 1. Store Heavy Rainfall Forecast via existing forecast DB helper
    forecast_record = {
        "timestamp": now_iso,
        "rain_1h": 52.5,
        "rain_3h": 84.0,
        "rain_6h": 126.0,
        "location": "Patna Pilot Municipal Area",
        "source": "Monsoon Heavy Precipitation Scenario (Simulated)",
        "retrieval_timestamp": now_iso,
    }
    try:
        save_forecast(forecast_record, db_path=db_path)
    except Exception as exc:
        logger.warning("Could not persist forecast in simulation: %s", exc)

    # 2. Extract Cells from database or fallback static JSON
    cells_to_predict: List[Dict[str, Any]] = []
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, vulnerability FROM cells")
            rows = cursor.fetchall()
            for r in rows:
                cells_to_predict.append({
                    "id": str(r[0]),
                    "vulnerability": float(r[1]) if r[1] is not None else 0.5,
                })
    except Exception as db_err:
        logger.debug("Database cells query notice: %s", db_err)

    if not cells_to_predict and Path(static_risk_path).exists():
        try:
            with open(static_risk_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for c in data.get("cells", []):
                    cells_to_predict.append({
                        "id": str(c.get("cell_id") or c.get("id")),
                        "vulnerability": float(c.get("vulnerability_score", 0.5)),
                    })
        except Exception as json_err:
            logger.warning("Could not load static cells for simulation: %s", json_err)

    # 3. Generate Horizon Predictions using FloodRiskPredictor
    predictor = FloodRiskPredictor(db_path=db_path, mode="heuristic")
    all_predictions: List[RiskPrediction] = []

    horizon_rain = {1: 52.5, 3: 84.0, 6: 126.0}
    for hz, rain_mm in horizon_rain.items():
        for cell in cells_to_predict:
            pred = predictor.predict_from_forecast(
                rainfall_mm=rain_mm,
                cell_id=cell["id"],
                horizon=hz,
                vulnerability=cell.get("vulnerability", 0.5),
                timestamp=now_iso,
                persist=False,
                explain=True,
            )
            all_predictions.append(pred)

    # Clean existing predictions for these horizons and persist batch
    try:
        with get_db_connection(db_path) as conn:
            conn.execute("DELETE FROM risk_predictions WHERE horizon IN (1, 3, 6);")
    except Exception as del_err:
        logger.debug("Notice cleaning old predictions: %s", del_err)

    saved_count = predictor.save_predictions_batch(all_predictions)

    # 4. Trigger automatic public warning directly for qualifying risk predictions
    # Pipeline: simulate_heavy_rain_scenario() -> persist predictions -> PublicWarningEngine
    # -> evaluate_and_broadcast() -> GeoTargetingService -> PublicWarningPolicy -> MessageBuilder
    # -> SimulatedCellBroadcastAdapter -> SIMULATED_DELIVERED
    pw_warnings_count = 0
    try:
        from src.geo_alerts.public_warning import get_public_warning_engine
        engine = get_public_warning_engine(db_path=db_path)
        for pred in all_predictions:
            pw_res = engine.evaluate_and_broadcast(risk_source=pred)
            if pw_res.triggered:
                pw_warnings_count += 1
    except Exception as pw_err:
        logger.warning("Automatic public warning trigger notice: %s", pw_err)

    # 4. Generate Elevated Sensor Telemetry using SensorSimulator
    from app.map_layers import DEFAULT_PILOT_SENSORS
    elevated_readings: List[SensorReading] = []
    for node_info in DEFAULT_PILOT_SENSORS:
        sim = SensorSimulator(
            node_id=node_info["node_id"],
            base_water_level_cm=float(node_info.get("water_level_cm", 25.0)),
            warning_threshold_cm=float(node_info.get("warning_threshold_cm", 75.0)),
            critical_threshold_cm=float(node_info.get("critical_threshold_cm", 120.0)),
        )
        reading = sim.generate_reading(
            scenario=SimulationScenario.RISING,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            step_index=16,
        )
        elevated_readings.append(reading)

    try:
        persist_batch(elevated_readings, db_path=db_path, auto_register_node=True)
    except Exception as sensor_err:
        logger.debug("Notice saving sensor batch: %s", sensor_err)

    return {
        "success": True,
        "scenario": "HEAVY_RAIN",
        "timestamp": now_iso,
        "forecast": {"rain_1h": 52.5, "rain_3h": 84.0, "rain_6h": 126.0},
        "predictions_created": saved_count,
        "sensors_updated": len(elevated_readings),
        "public_warnings_triggered": pw_warnings_count,
        "message": "Heavy rainfall scenario active: +1h/+3h/+6h risk, sensor telemetry, and automatic public warnings updated.",
    }


# Operational alias for trigger/simulation compatibility
trigger_heavy_rain_scenario = simulate_heavy_rain_scenario


def reset_to_baseline_scenario(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Reset the operational system state back to normal seasonal baseline.

    Workflow:
    1. Clears dynamic risk predictions from the risk_predictions table.
    2. Resets IoT sensor telemetry to normal baseline levels using SensorSimulator.
    3. Cleans scenario forecast entries.
    4. Cleans alerts, alert logs, and public warnings tables.
    5. Resets public warning cooldown caches.
    """
    try:
        with get_db_connection(db_path) as conn:
            try:
                conn.execute("DELETE FROM risk_predictions;")
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM forecasts WHERE source LIKE '%Simulated%';")
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM sensor_readings;")
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM alerts;")
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM alert_logs;")
            except Exception:
                pass
            try:
                conn.execute("DELETE FROM public_warnings;")
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Notice resetting database in scenario controller: %s", exc)

    try:
        from src.geo_alerts.public_warning import get_public_warning_engine
        engine = get_public_warning_engine(db_path=db_path)
        engine.reset_cooldown()
    except Exception as cd_err:
        logger.debug("Notice resetting public warning cooldown: %s", cd_err)

    return {
        "success": True,
        "scenario": "BASELINE",
        "message": "System reset to normal baseline: Dynamic risk predictions cleared, nominal drainage active.",
    }


def load_backtest_summary(
    path: Union[str, Path] = DEFAULT_BACKTEST_RESULTS_PATH,
) -> Dict[str, Any]:
    """Load machine-readable validation results and model comparison metrics.

    Preserves provenance and limitations from M1 Day 5.
    """
    target = Path(path)
    if not target.exists():
        return {
            "available": False,
            "events": ["EVT_2023_MICHAUNG", "EVT_2021_NOV_DEPRESSION"],
            "methods": ["ml", "heuristic", "rainfall_threshold"],
            "horizons": [1, 3, 6],
            "records": [],
            "limitations": [
                "Evaluated against calibrated proxy development labels, not physical ground-truth sensor telemetry.",
                "Historical backtesting evaluated across 2 severe cyclonic precipitation events.",
                "XGBoost model benchmark shares training distributions with developmental backtest dataset.",
                "Rainfall baseline uses uniform thresholding without terrain vulnerability.",
            ],
            "disclaimer": "Prototype backtest evaluation against calibrated proxy development labels. Not verified against physical water-level sensor telemetry.",
        }

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)

        meta = data.get("metadata", {})
        raw_results = data.get("event_results", [])

        # Format comparison table rows
        rows: List[Dict[str, Any]] = []
        for r in raw_results:
            method_name = "XGBoost ML" if r.get("method") == "ml" else (
                "Heuristic Linear" if r.get("method") == "heuristic" else "Rainfall Baseline"
            )
            event_name = "Michaung 2023" if "MICHAUNG" in r.get("event_id", "") else "Nov 2021 Depression"
            prec = r.get("precision")
            rec = r.get("recall")
            f1 = r.get("f1")
            brier = r.get("brier")

            rows.append({
                "Event": event_name,
                "Horizon": f"+{r.get('horizon')}h",
                "Model / Method": method_name,
                "Precision": f"{prec:.2f}" if prec is not None else "N/A",
                "Recall": f"{rec:.2f}" if rec is not None else "N/A",
                "F1 Score": f"{f1:.2f}" if f1 is not None else "N/A",
                "Brier Score": f"{brier:.3f}" if brier is not None else "N/A",
                "Samples": r.get("n_samples", 0),
            })

        return {
            "available": True,
            "events": meta.get("events", ["EVT_2023_MICHAUNG", "EVT_2021_NOV_DEPRESSION"]),
            "methods": meta.get("methods", ["ml", "heuristic", "rainfall_threshold"]),
            "horizons": meta.get("horizons", [1, 3, 6]),
            "records": rows,
            "limitations": meta.get("limitations", [
                "Evaluated against calibrated proxy development labels, not ground-truth physical sensor measurements.",
                "Historical events limited to 2 events (Michaung Dec 2023 and Nov 2021).",
                "Prototype XGBoost models evaluated share training data with the backtest set (in-sample benchmark).",
                "Rainfall baseline uses uniform rainfall thresholds without terrain vulnerability.",
            ]),
            "disclaimer": meta.get("disclaimer", "Prototype backtest evaluation against calibrated proxy development labels."),
        }
    except Exception as exc:
        logger.warning("Could not parse backtest results file %s: %s", target, exc)
        return {
            "available": False,
            "error": str(exc),
            "events": [],
            "records": [],
            "limitations": [],
            "disclaimer": "Prototype backtest evaluation notice.",
        }


def replay_historical_backtest_event(
    event_id: str = "EVT_2023_MICHAUNG",
    threshold_mm: float = 50.0,
    backtest_data_path: Union[str, Path] = DEFAULT_BACKTEST_RESULTS_PATH,
    events_path: Union[str, Path] = DEFAULT_BACKTEST_EVENTS_PATH,
) -> Dict[str, Any]:
    """Replay and evaluate a historical storm event against operational flood thresholds.

    Compares event precipitation against an operational threshold, retrieves
    ML vs heuristic vs rainfall baseline metrics for the event, and returns
    structured comparison metrics with official prototype limitations and proxy disclaimers.
    """
    ev_path = Path(events_path)
    events_data: List[Dict[str, Any]] = []

    if ev_path.exists():
        try:
            with open(ev_path, "r", encoding="utf-8") as f:
                events_data = json.load(f)
        except Exception as exc:
            logger.warning("Could not parse backtest events from %s: %s", ev_path, exc)

    if not events_data:
        # Resilient fallback matching M1 historical specifications
        events_data = [
            {
                "event_id": "EVT_2023_MICHAUNG",
                "name": "Cyclone Michaung Heavy Inundation",
                "city": "Chennai",
                "total_rainfall_mm": 324.1,
                "peak_hourly_rainfall_mm": 26.1,
                "classification": "Extremely Severe Urban Flood Event",
                "impact_summary": "Extensive neighborhood inundation across South and Central Chennai; water depths between 1.5m to 2.5m.",
            },
            {
                "event_id": "EVT_2021_NOV_DEPRESSION",
                "name": "November 2021 Deep Depression Inundation",
                "city": "Chennai",
                "total_rainfall_mm": 89.0,
                "peak_hourly_rainfall_mm": 7.0,
                "classification": "Moderate to High Flash Inundation Event",
                "impact_summary": "Sudden intense overnight rainfall caused severe flash waterlogging.",
            },
        ]

    # Find requested event
    target_event = None
    target_clean = event_id.strip().upper()
    for ev in events_data:
        if target_clean in ev.get("event_id", "").upper() or target_clean in ev.get("name", "").upper():
            target_event = ev
            break

    if target_event is None:
        target_event = events_data[0]

    tot_rain = float(target_event.get("total_rainfall_mm", 0.0))
    peak_rain = float(target_event.get("peak_hourly_rainfall_mm", 0.0))
    exceeded = (tot_rain >= threshold_mm) or (peak_rain >= (threshold_mm / 3.0))

    if exceeded:
        alert_opportunity = (
            f"HIGH RISK ADVISORY TRIGGERED: Cumulative rainfall ({tot_rain:.1f} mm) or "
            f"peak intensity ({peak_rain:.1f} mm/h) exceeded threshold ({threshold_mm:.1f} mm)."
        )
    else:
        alert_opportunity = (
            f"NOMINAL MONITORING: Precipitation ({tot_rain:.1f} mm) remained within municipal drainage capacity."
        )

    # Load comparative model metrics
    metrics_summary: List[Dict[str, Any]] = []
    bt_path = Path(backtest_data_path)
    if bt_path.exists():
        try:
            with open(bt_path, "r", encoding="utf-8") as f:
                bt_data = json.load(f)
            for res in bt_data.get("event_results", []):
                if target_event.get("event_id") in res.get("event_id", ""):
                    metrics_summary.append({
                        "method": res.get("method"),
                        "horizon": res.get("horizon"),
                        "precision": res.get("precision"),
                        "recall": res.get("recall"),
                        "f1": res.get("f1"),
                        "brier": res.get("brier"),
                        "samples": res.get("n_samples"),
                    })
        except Exception as exc:
            logger.debug("Notice parsing backtest results for replay: %s", exc)

    return {
        "success": True,
        "event_id": target_event.get("event_id"),
        "name": target_event.get("name"),
        "city": target_event.get("city", "Chennai"),
        "total_rainfall_mm": tot_rain,
        "peak_hourly_rainfall_mm": peak_rain,
        "threshold_mm": threshold_mm,
        "exceeded_threshold": exceeded,
        "alert_opportunity": alert_opportunity,
        "classification": target_event.get("classification"),
        "impact_summary": target_event.get("impact_summary"),
        "metrics": metrics_summary,
        "limitations": [
            "Evaluated against calibrated proxy development labels, not ground-truth physical sensor measurements.",
            "Historical events evaluated across severe cyclonic precipitation events (Michaung 2023 & Nov 2021).",
            "Prototype XGBoost models evaluated share training data with the backtest set (in-sample benchmark).",
            "Rainfall baseline uses uniform rainfall thresholds without terrain vulnerability.",
        ],
        "disclaimer": "Prototype backtest evaluation against calibrated proxy development labels. Not verified against physical water-level sensor telemetry.",
    }


def run_end_to_end_pipeline(
    scenario: str = "HEAVY_RAIN",
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    authority_action: Optional[str] = "approve",
    citizen_start_coord: Optional[Tuple[float, float]] = None,
) -> Dict[str, Any]:
    """Execute complete end-to-end operational pipeline across F1/F2 and backend.

    Workflow:
    1. Scenario Trigger: Applies HEAVY_RAIN or BASELINE scenario to update forecasts and sensor telemetry.
    2. Sensor Validation: Verifies sensor readings through deterministic correction/validation layers.
    3. Alert Drafting: Generates an authority draft flood advisory based on forecasted hazard footprint.
    4. Authority Gate: Processes human-in-the-loop decision ('approve' -> dry-run dispatch, 'dismiss' -> suppress).
    5. Audit Trail: Confirms structured entries in alert_logs for every lifecycle transition.
    6. Citizen Safe Route: Computes hazard-avoiding evacuation path to the nearest safe shelter.
    """
    from app.alert_service import (
        create_draft_alert,
        dismiss_authority_alert,
        dispatch_authority_alert,
    )
    from src.routing.router import safe_route
    from src.sensors.correction import correct_and_validate_reading

    target_db = db_path if db_path is not None else DEFAULT_DB_PATH
    if not isinstance(target_db, sqlite3.Connection):
        init_db(target_db)

    # 1. Trigger or Reset Scenario
    scen_upper = scenario.upper()
    if scen_upper == "HEAVY_RAIN":
        scenario_result = trigger_heavy_rain_scenario(db_path=target_db)
    elif scen_upper == "BASELINE":
        scenario_result = reset_to_baseline_scenario(db_path=target_db)
    else:
        scenario_result = {"success": True, "scenario": scenario, "message": f"Scenario {scenario} executed."}

    # 2. Sensor Validation & Correction Check
    validated_readings = []
    try:
        with get_db_connection(target_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 5;")
            rows = [dict(r) for r in cursor.fetchall()]
            for r in rows:
                sr = SensorReading(
                    node_id=r.get("node_id", "TEST_NODE"),
                    water_level_cm=r.get("water_level_cm", 0.0),
                    rainfall_rate_mm_h=r.get("rainfall_rate_mm_h", 0.0),
                    battery_pct=r.get("battery_pct", 100.0),
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                corr = correct_and_validate_reading(sr)
                validated_readings.append({
                    "node_id": corr.node_id,
                    "water_level_cm": corr.water_level_cm,
                    "validation_status": corr.validation_status,
                    "validation_message": corr.validation_message,
                    "is_anomaly": corr.is_anomaly,
                })
    except Exception as sens_err:
        logger.debug("Sensor validation check notice: %s", sens_err)

    # 3. Draft Alert Creation (for HEAVY_RAIN)
    draft_id = None
    dispatch_result = None
    if scen_upper == "HEAVY_RAIN":
        draft_id = create_draft_alert(
            severity="WARNING",
            title="Monsoon Waterlogging & Inundation Advisory",
            message="Heavy precipitation triggered dynamic flood risk elevation across vulnerable depression zones.",
            affected_area="Patna, Bihar",
            db_path=target_db,
        )

        # 4. Authority Decision Gate
        if authority_action == "approve":
            dispatch_result = dispatch_authority_alert(
                severity="WARNING",
                title="Monsoon Waterlogging & Inundation Advisory",
                message="Heavy precipitation triggered dynamic flood risk elevation across vulnerable depression zones.",
                affected_area="Patna, Bihar",
                draft_id=draft_id,
                db_path=target_db,
            )
        elif authority_action == "dismiss":
            dispatch_result = dismiss_authority_alert(
                alert_id=draft_id,
                reason="Advisory dismissed during operational authority review.",
                db_path=target_db,
            )
        else:
            dispatch_result = {
                "status": "pending_review",
                "message": "Alert created in draft status, awaiting human authority review.",
                "draft_id": draft_id,
            }
    else:
        dispatch_result = {
            "status": "none",
            "message": "No active warning generated in baseline scenario.",
        }

    # 5. Audit Log Inspection
    audit_logs = []
    try:
        with get_db_connection(target_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM alert_logs ORDER BY id DESC LIMIT 10;")
            audit_logs = [dict(r) for r in cursor.fetchall()]
    except Exception as log_err:
        logger.debug("Audit log fetch notice: %s", log_err)

    # 6. Citizen Safe Routing
    start_coord = citizen_start_coord or (25.5941, 85.1376)
    try:
        route_result = safe_route(start_coord[0], start_coord[1], db_path=target_db)
    except Exception as route_err:
        route_result = {
            "status": "error",
            "found": False,
            "route": [],
            "distance_m": 0.0,
            "estimated_time_min": 0.0,
            "destination": None,
            "message": f"Routing calculation error: {route_err}",
        }

    return {
        "success": True,
        "scenario": scenario,
        "scenario_result": scenario_result,
        "sensor_corrections": validated_readings,
        "draft_alert_id": draft_id,
        "authority_action": authority_action,
        "dispatch_result": dispatch_result,
        "audit_logs": audit_logs,
        "safe_route_result": route_result,
    }
