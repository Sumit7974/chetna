"""Operational map layers and spatial visualization components for Chetna F1 Authority Operations.

Provides:
- Static risk / vulnerability grid layer with calibrated risk tiers (LOW, MEDIUM, HIGH, SEVERE).
- Waterlogging hotspot markers with concise operational popups.
- Telemetry sensor station markers with real-time reading status and popups.
- Multi-horizon risk prediction loading across NOW, +1h, +3h, and +6h without synthetic data fabrication.
- Non-causal "Why flagged" explanation formatter preserving scientific disclaimers.
- Categorized at-risk critical infrastructure asset integration (Hospitals, Schools, Shelters).
- High-contrast, compact map legend control.
- Truthful spatial attribution (Prototype Baseline: Reference Spatial Grid).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import folium
from folium import plugins
import pydeck as pdk

from config.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_PILOT_CENTER: Tuple[float, float] = (25.6093, 85.1376)

# Default paths
DEFAULT_DB_PATH = Path("data/chetna.db")
DEFAULT_STATIC_RISK_PATH = Path("data/m1/static_risk_scores.json")
DEFAULT_HOTSPOTS_PATH = Path("data/m1/hotspots.json")

# Styling constants for Risk Tiers (Calibrated with M1 static & dynamic thresholds)
# LOW: < 0.40, MEDIUM: 0.40 - 0.70, HIGH: >= 0.70, SEVERE: Critical inundation (level == 'SEVERE')
RISK_STYLE_SEVERE = {
    "tier": "SEVERE",
    "fill_color": "#991b1b",      # Deep dark red
    "border_color": "#7f1d1d",    # Crimson border
    "fill_opacity": 0.55,
    "weight": 2.0,
    "badge_bg": "#fee2e2",
    "badge_color": "#7f1d1d",
}

RISK_STYLE_HIGH = {
    "tier": "HIGH",
    "fill_color": "#dc2626",      # Vivid red
    "border_color": "#991b1b",    # Dark red
    "fill_opacity": 0.45,
    "weight": 1.5,
    "badge_bg": "#fee2e2",
    "badge_color": "#991b1b",
}

RISK_STYLE_MEDIUM = {
    "tier": "MEDIUM",
    "fill_color": "#f59e0b",      # Amber / Orange
    "border_color": "#b45309",    # Dark amber
    "fill_opacity": 0.40,
    "weight": 1.5,
    "badge_bg": "#fef3c7",
    "badge_color": "#92400e",
}

RISK_STYLE_LOW = {
    "tier": "LOW",
    "fill_color": "#16a34a",      # Forest green
    "border_color": "#15803d",    # Dark green
    "fill_opacity": 0.35,
    "weight": 1.2,
    "badge_bg": "#dcfce7",
    "badge_color": "#166534",
}

# Canonical pilot telemetry monitoring stations across key Patna drainage basins
DEFAULT_PILOT_SENSORS: List[Dict[str, Any]] = [
    {
        "node_id": "SENS_PAT_01",
        "name": "Rajendra Nagar Sump Station",
        "latitude": 25.5990,
        "longitude": 85.1640,
        "water_level_cm": 24.5,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 98.2,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 40.0,
        "critical_threshold_cm": 65.0,
    },
    {
        "node_id": "SENS_PAT_02",
        "name": "Kankarbagh Colony Drain Outfall",
        "latitude": 25.5960,
        "longitude": 85.1550,
        "water_level_cm": 22.0,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 97.5,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 35.0,
        "critical_threshold_cm": 60.0,
    },
    {
        "node_id": "SENS_PAT_03",
        "name": "Saidpur Nullah Inflow Gauge",
        "latitude": 25.6030,
        "longitude": 85.1710,
        "water_level_cm": 28.0,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 99.1,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 45.0,
        "critical_threshold_cm": 70.0,
    },
    {
        "node_id": "SENS_PAT_04",
        "name": "Boring Canal Underpass Sensor",
        "latitude": 25.6180,
        "longitude": 85.1220,
        "water_level_cm": 15.5,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 96.4,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 30.0,
        "critical_threshold_cm": 50.0,
    },
    {
        "node_id": "SENS_PAT_05",
        "name": "Bailey Road Sag Station",
        "latitude": 25.6120,
        "longitude": 85.0840,
        "water_level_cm": 18.0,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 95.8,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 30.0,
        "critical_threshold_cm": 55.0,
    },
    {
        "node_id": "SENS_PAT_06",
        "name": "Gandhi Maidan South Basin",
        "latitude": 25.6180,
        "longitude": 85.1430,
        "water_level_cm": 20.0,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 98.7,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 40.0,
        "critical_threshold_cm": 65.0,
    },
    {
        "node_id": "SENS_PAT_07",
        "name": "Patliputra Industrial Drain Node",
        "latitude": 25.6250,
        "longitude": 85.1050,
        "water_level_cm": 16.5,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 94.9,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 35.0,
        "critical_threshold_cm": 60.0,
    },
    {
        "node_id": "SENS_PAT_08",
        "name": "Anisabad Golambar Sump Node",
        "latitude": 25.5800,
        "longitude": 85.1020,
        "water_level_cm": 21.0,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 96.0,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 35.0,
        "critical_threshold_cm": 60.0,
    },
    {
        "node_id": "SENS_PAT_09",
        "name": "Digha Outfall Sluice Gate Monitor",
        "latitude": 25.6420,
        "longitude": 85.0980,
        "water_level_cm": 26.0,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 97.1,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 50.0,
        "critical_threshold_cm": 80.0,
    },
    {
        "node_id": "SENS_PAT_10",
        "name": "Bazar Samiti Agricultural Market Sump",
        "latitude": 25.6050,
        "longitude": 85.1820,
        "water_level_cm": 23.5,
        "rainfall_rate_mm_h": 0.0,
        "battery_pct": 95.3,
        "status": "NORMAL",
        "source": "Simulated Telemetry (Patna Pilot)",
        "warning_threshold_cm": 40.0,
        "critical_threshold_cm": 65.0,
    },
]


def get_risk_tier_style(score: float, level: Optional[str] = None) -> Dict[str, Any]:
    """Return styling dictionary for a given vulnerability or risk probability score."""
    lvl = (level or "").strip().upper()
    if lvl == "SEVERE":
        return dict(RISK_STYLE_SEVERE)
    elif lvl == "HIGH":
        return dict(RISK_STYLE_HIGH)
    elif lvl == "MEDIUM":
        return dict(RISK_STYLE_MEDIUM)
    elif lvl == "LOW":
        return dict(RISK_STYLE_LOW)

    # Score-based classification (conforming to M1 calibrated thresholds)
    if score >= 0.85:
        return dict(RISK_STYLE_HIGH)
    elif score >= 0.70:
        return dict(RISK_STYLE_HIGH)
    elif score >= 0.40:
        return dict(RISK_STYLE_MEDIUM)
    else:
        return dict(RISK_STYLE_LOW)


def format_why_flagged_html(
    explanation: Optional[Union[Dict[str, Any], str]] = None,
    raw_features: Optional[Dict[str, Any]] = None,
    is_hotspot: bool = False,
    risk_level: str = "LOW",
) -> str:
    """Format clear, non-causal authority explanation bullets without raw ML jargon.

    Preserves the scientific disclaimer and translates model feature attributions into
    concise operational indicators.
    """
    factors_html: List[str] = []
    summary_text: Optional[str] = None

    if isinstance(explanation, str):
        try:
            explanation = json.loads(explanation)
        except Exception:
            explanation = None

    if isinstance(explanation, dict):
        summary_text = explanation.get("summary")
        top_factors = explanation.get("top_factors") or []
        for factor in top_factors:
            if isinstance(factor, str):
                factors_html.append(f"&bull; {factor}")
                continue
            if not isinstance(factor, dict):
                continue
            feat = factor.get("feature", "")
            try:
                val = float(factor.get("value", 0.0))
            except (ValueError, TypeError):
                val = 0.0
            direction = factor.get("direction", "")

            # Highlight factors contributing to risk
            if direction == "decreases_risk" and risk_level == "LOW":
                continue

            if feat == "rainfall_mm":
                if val >= 40.0:
                    factors_html.append(f"&bull; <b>High forecast rainfall:</b> {val:.1f} mm in window")
                elif val >= 15.0:
                    factors_html.append(f"&bull; <b>Moderate precipitation:</b> {val:.1f} mm in window")
                elif val > 0.0:
                    factors_html.append(f"&bull; <b>Light rain forecast:</b> {val:.1f} mm")
            elif feat == "rain_past_24h":
                if val >= 25.0:
                    factors_html.append(f"&bull; <b>Antecedent rain:</b> Prior soil saturation ({val:.1f} mm in 24h)")
                elif val >= 10.0:
                    factors_html.append(f"&bull; <b>Prior rainfall:</b> {val:.1f} mm in past 24h")
            elif feat == "elevation":
                if val <= 8.0:
                    factors_html.append(f"&bull; <b>Low elevation:</b> Low-lying depression ({val:.1f} m AMSL)")
            elif feat == "slope":
                if val <= 0.5:
                    factors_html.append(f"&bull; <b>Flat gradient:</b> Flat terrain ({val:.1f}&deg; slope) slows outfall")
            elif feat == "flow_accumulation":
                if val >= 20000.0:
                    factors_html.append(f"&bull; <b>High flow accumulation:</b> Large upstream runoff catchment ({val:,.0f} cells)")
            elif feat == "imperviousness":
                if val >= 0.70:
                    factors_html.append(f"&bull; <b>High runoff susceptibility:</b> Dense paved surface ({val*100:.0f}% impervious)")
            elif feat == "vulnerability_score":
                if val >= 0.70:
                    factors_html.append(f"&bull; <b>Topographic vulnerability:</b> Elevated baseline score ({val:.2f})")
            elif feat == "is_hotspot" and val > 0:
                factors_html.append("&bull; <b>Chronic hotspot:</b> Documented municipal waterlogging site")

    # Fallback to raw static features if explanation is empty or for static baseline
    if not factors_html and raw_features:
        elev = raw_features.get("elevation")
        slope = raw_features.get("slope")
        flow_acc = raw_features.get("flow_accumulation", raw_features.get("flow_acc"))
        imperv = raw_features.get("imperviousness")

        if elev is not None and float(elev) <= 8.0:
            factors_html.append(f"&bull; <b>Low elevation:</b> Low ground surface ({float(elev):.1f} m)")
        if flow_acc is not None and float(flow_acc) >= 20000.0:
            factors_html.append(f"&bull; <b>Catchment volume:</b> High surface flow accumulation ({float(flow_acc):,.0f} cells)")
        if imperv is not None and float(imperv) >= 0.70:
            factors_html.append(f"&bull; <b>Runoff susceptibility:</b> High paved surface fraction ({float(imperv)*100:.0f}% impervious)")
        if slope is not None and float(slope) <= 0.5:
            factors_html.append(f"&bull; <b>Flat gradient:</b> Flat terrain ({float(slope):.1f}&deg; slope)")
        if is_hotspot:
            factors_html.append("&bull; <b>Chronic hotspot:</b> Documented drainage depression corridor")

    if not factors_html:
        factors_html.append("&bull; Terrain parameters within normal municipal drainage limits.")

    bullets_str = "<br/>".join(factors_html)
    summary_html = f"<div style='margin-bottom: 4px; font-style: italic; color: #1e293b;'>{summary_text}</div>" if summary_text else ""

    return (
        f"{summary_html}"
        f"<div style='color: #334155; line-height: 1.45;'>{bullets_str}</div>"
        "<div style='font-size: 8.5px; color: #94a3b8; margin-top: 5px; font-style: italic; border-top: 1px dashed #cbd5e1; padding-top: 3px;'>"
        "Scientific provenance: Model feature attribution, not proven physical causation."
        "</div>"
    )


def load_horizon_predictions(
    horizon: Union[str, int] = "NOW",
    db_path: Union[Path, str, sqlite3.Connection] = DEFAULT_DB_PATH,
    static_risk_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load risk predictions for the selected horizon from the database or static baseline.

    Args:
        horizon: Horizon identifier ('NOW', '+1h', '+3h', '+6h' or int 0, 1, 3, 6).
        db_path: Path or connection to SQLite database.
        static_risk_data: Optional preloaded static vulnerability data for NOW counts.

    Returns:
        Dict containing:
            - 'available' (bool)
            - 'horizon' (str)
            - 'horizon_hours' (int)
            - 'timestamp' (Optional[str])
            - 'predictions' (Optional[Dict[str, Dict[str, Any]]])
            - 'counts' (Optional[Dict[str, int]])
            - 'message' (str)
    """
    h_str = str(horizon).strip()
    if h_str in ("NOW", "0", "+0h", "now"):
        # Static baseline: evaluate counts from static risk scores
        static_data = static_risk_data
        if not static_data:
            static_file = Path(DEFAULT_STATIC_RISK_PATH)
            if static_file.exists():
                try:
                    with open(static_file, "r", encoding="utf-8") as f:
                        static_data = json.load(f)
                except Exception:
                    static_data = None

        cells = (static_data or {}).get("cells", [])
        high_cnt = sum(
            1 for c in cells
            if (c.get("risk_level") or "").lower() == "high" or float(c.get("vulnerability_score", 0.0)) >= 0.70
        )
        med_cnt = sum(
            1 for c in cells
            if (c.get("risk_level") or "").lower() == "medium" or (0.40 <= float(c.get("vulnerability_score", 0.0)) < 0.70)
        )
        low_cnt = sum(
            1 for c in cells
            if (c.get("risk_level") or "").lower() == "low" or float(c.get("vulnerability_score", 0.0)) < 0.40
        )
        total_cnt = len(cells)

        counts = {
            "LOW": low_cnt,
            "MEDIUM": med_cnt,
            "HIGH": high_cnt,
            "SEVERE": 0,
            "total": total_cnt,
        }
        return {
            "available": True,
            "horizon": "NOW",
            "horizon_hours": 0,
            "timestamp": None,
            "predictions": None,
            "counts": counts,
            "message": "Calibrated static topographic vulnerability baseline active.",
        }

    horizon_hours_map = {"+1h": 1, "+3h": 3, "+6h": 6, "1": 1, "3": 3, "6": 6}
    hours = horizon_hours_map.get(h_str)
    if hours is None:
        return {
            "available": False,
            "horizon": h_str,
            "horizon_hours": -1,
            "timestamp": None,
            "predictions": None,
            "counts": None,
            "message": f"Forecast data unavailable for {h_str}.",
        }

    label = f"+{hours}h"

    # Query SQLite database for risk_predictions
    try:
        if isinstance(db_path, sqlite3.Connection):
            conn = db_path
            close_conn = False
        else:
            p = Path(db_path)
            if not p.exists():
                return {
                    "available": False,
                    "horizon": label,
                    "horizon_hours": hours,
                    "timestamp": None,
                    "predictions": None,
                    "counts": None,
                    "message": f"Forecast data unavailable for {label}.",
                }
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            close_conn = True

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='risk_predictions'")
            if not cursor.fetchone():
                return {
                    "available": False,
                    "horizon": label,
                    "horizon_hours": hours,
                    "timestamp": None,
                    "predictions": None,
                    "counts": None,
                    "message": f"Forecast data unavailable for {label}.",
                }

            # Check if explanation column exists
            cursor.execute("PRAGMA table_info(risk_predictions)")
            col_rows = cursor.fetchall()
            cols = [r[1] if isinstance(r, tuple) else r["name"] for r in col_rows]
            has_expl = "explanation" in cols

            if has_expl:
                query = (
                    "SELECT cell_id, timestamp, horizon, level, probability, explanation "
                    "FROM risk_predictions WHERE horizon = ? ORDER BY timestamp DESC"
                )
            else:
                query = (
                    "SELECT cell_id, timestamp, horizon, level, probability, NULL as explanation "
                    "FROM risk_predictions WHERE horizon = ? ORDER BY timestamp DESC"
                )

            cursor.execute(query, (hours,))
            rows = cursor.fetchall()

            if not rows:
                return {
                    "available": False,
                    "horizon": label,
                    "horizon_hours": hours,
                    "timestamp": None,
                    "predictions": None,
                    "counts": None,
                    "message": f"Forecast data unavailable for {label}.",
                }

            preds: Dict[str, Dict[str, Any]] = {}
            latest_ts = None

            for row in rows:
                cid = row[0] if isinstance(row, tuple) else row["cell_id"]
                if cid in preds:
                    continue  # Keep the most recent timestamp per cell
                ts = row[1] if isinstance(row, tuple) else row["timestamp"]
                hz = row[2] if isinstance(row, tuple) else row["horizon"]
                lvl = str(row[3] if isinstance(row, tuple) else row["level"]).strip().upper()
                prob = float(row[4] if isinstance(row, tuple) else row["probability"])
                raw_expl = row[5] if isinstance(row, tuple) else row["explanation"]

                expl = None
                if raw_expl:
                    if isinstance(raw_expl, str):
                        try:
                            expl = json.loads(raw_expl)
                        except Exception:
                            expl = {"summary": raw_expl}
                    elif isinstance(raw_expl, dict):
                        expl = raw_expl

                preds[cid] = {
                    "cell_id": cid,
                    "timestamp": ts,
                    "horizon": hz,
                    "level": lvl,
                    "probability": prob,
                    "explanation": expl,
                }
                if latest_ts is None:
                    latest_ts = ts

            low_cnt = sum(1 for p in preds.values() if p["level"] == "LOW")
            med_cnt = sum(1 for p in preds.values() if p["level"] == "MEDIUM")
            high_cnt = sum(1 for p in preds.values() if p["level"] == "HIGH")
            severe_cnt = sum(1 for p in preds.values() if p["level"] in ("SEVERE", "CRITICAL", "EMERGENCY"))

            counts = {
                "LOW": low_cnt,
                "MEDIUM": med_cnt,
                "HIGH": high_cnt,
                "SEVERE": severe_cnt,
                "total": len(preds),
            }

            return {
                "available": True,
                "horizon": label,
                "horizon_hours": hours,
                "timestamp": latest_ts,
                "predictions": preds,
                "counts": counts,
                "message": f"Forecast model active for {label} horizon.",
            }
        finally:
            if close_conn:
                conn.close()

    except Exception as exc:
        logger.warning("Error querying risk predictions for %s: %s", label, exc)
        return {
            "available": False,
            "horizon": label,
            "horizon_hours": hours,
            "timestamp": None,
            "predictions": None,
            "counts": None,
            "message": f"Forecast data unavailable for {label}.",
        }


def check_horizon_prediction_availability(
    horizon: str = "NOW",
    db_path: Union[Path, str, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Check whether forecast/prediction data exists for the selected horizon."""
    return load_horizon_predictions(horizon=horizon, db_path=db_path)


def get_at_risk_assets_summary(
    horizon_status: Dict[str, Any],
    hotspots_data: List[Dict[str, Any]],
    static_risk_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Summarize at-risk critical infrastructure assets for the active forecast horizon."""
    if not horizon_status or not horizon_status.get("available", True):
        hz_label = (horizon_status or {}).get("horizon", "active horizon")
        return {
            "available": False,
            "horizon": hz_label,
            "hospitals": 0,
            "schools": 0,
            "shelters": 0,
            "total": 0,
            "items": [],
            "message": f"At-risk asset summary unavailable: forecast data unavailable for {hz_label}.",
        }

    horizon = horizon_status.get("horizon", "NOW")
    preds = horizon_status.get("predictions")

    # Determine which cells are currently in elevated risk tiers (HIGH or SEVERE)
    high_risk_cells = set()
    if preds:
        for cid, p in preds.items():
            lvl = p.get("level", "LOW").upper()
            prob = float(p.get("probability", 0.0))
            if lvl in ("HIGH", "SEVERE", "CRITICAL", "EMERGENCY") or prob >= 0.70:
                high_risk_cells.add(cid)
    else:
        cells = (static_risk_data or {}).get("cells", [])
        if not cells and Path(DEFAULT_STATIC_RISK_PATH).exists():
            try:
                with open(DEFAULT_STATIC_RISK_PATH, "r", encoding="utf-8") as f:
                    cells = json.load(f).get("cells", [])
            except Exception:
                cells = []

        for c in cells:
            cid = c.get("cell_id") or c.get("id")
            lvl = (c.get("risk_level") or "").upper()
            score = float(c.get("vulnerability_score", c.get("vulnerability", 0.0)))
            if lvl == "HIGH" or score >= 0.70:
                high_risk_cells.add(cid)

    affected_hospitals: List[Dict[str, str]] = []
    affected_schools: List[Dict[str, str]] = []
    affected_shelters: List[Dict[str, str]] = []
    all_items: List[Dict[str, str]] = []

    for h in hotspots_data or []:
        cid = h.get("cell_id", "")
        sev = h.get("severity_tier", "Moderate")
        is_affected = (cid in high_risk_cells) or (sev in ("Severe", "High"))

        if not is_affected:
            continue

        h_name = h.get("name", "Monitored Hotspot")
        zone = h.get("zone", "Urban Sector")

        for infra in h.get("critical_infrastructure_nearby", []):
            infra_lower = infra.lower()
            rec = {
                "name": infra,
                "vicinity": h_name,
                "zone": zone,
                "cell_id": cid,
                "severity": sev,
            }
            if any(k in infra_lower for k in ["hospital", "clinic", "health", "medical"]):
                rec["type"] = "Hospital"
                affected_hospitals.append(rec)
            elif any(k in infra_lower for k in ["school", "college", "vidyalaya", "academy", "university"]):
                rec["type"] = "School"
                affected_schools.append(rec)
            else:
                rec["type"] = "Transit / Shelter"
                affected_shelters.append(rec)
            all_items.append(rec)

    total_affected = len(all_items)
    return {
        "available": True,
        "horizon": horizon,
        "hospitals": len(affected_hospitals),
        "schools": len(affected_schools),
        "shelters": len(affected_shelters),
        "total": total_affected,
        "items": all_items,
        "message": f"Identified {len(affected_hospitals)} hospitals, {len(affected_schools)} schools, {len(affected_shelters)} shelters in high-risk zones.",
    }


def load_sensor_stations(
    db_path: Union[Path, str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Load sensor stations from database, falling back to pilot monitoring nodes."""
    target_db = Path(db_path)
    if target_db.exists():
        try:
            conn = sqlite3.connect(str(target_db))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Check if sensor_nodes table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sensor_nodes'")
            if cursor.fetchone():
                cursor.execute(
                    """
                    SELECT sn.node_id, sn.name, sn.latitude, sn.longitude, sn.sensor_type,
                           sn.warning_threshold_cm, sn.critical_threshold_cm, sn.status,
                           sr.water_level_cm, sr.rainfall_rate_mm_h, sr.battery_pct
                    FROM sensor_nodes sn
                    LEFT JOIN (
                        SELECT node_id, water_level_cm, rainfall_rate_mm_h, battery_pct,
                               ROW_NUMBER() OVER (PARTITION BY node_id ORDER BY timestamp DESC) as rn
                        FROM sensor_readings
                    ) sr ON sn.node_id = sr.node_id AND sr.rn = 1
                    """
                )
                rows = cursor.fetchall()
                conn.close()
                if rows:
                    stations = []
                    for row in rows:
                        stations.append({
                            "node_id": row["node_id"],
                            "name": row["name"],
                            "latitude": float(row["latitude"]),
                            "longitude": float(row["longitude"]),
                            "water_level_cm": float(row["water_level_cm"] or 25.0),
                            "rainfall_rate_mm_h": float(row["rainfall_rate_mm_h"] or 0.0),
                            "battery_pct": float(row["battery_pct"] or 95.0),
                            "status": str(row["status"] or "ACTIVE"),
                            "source": "Physical / Database Node",
                            "warning_threshold_cm": float(row["warning_threshold_cm"] or 75.0),
                            "critical_threshold_cm": float(row["critical_threshold_cm"] or 120.0),
                        })
                    return stations
            conn.close()
        except Exception as e:
            logger.debug("Database sensor query fallback: %s", e)

    return [dict(s) for s in DEFAULT_PILOT_SENSORS]


def add_risk_cells_layer(
    folium_map: folium.Map,
    cells_data: Union[List[Dict[str, Any]], Dict[str, Any]],
    horizon: str = "NOW",
    predictions_map: Optional[Dict[str, Dict[str, Any]]] = None,
    hotspots_data: Optional[List[Dict[str, Any]]] = None,
    dynamic_predictions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> folium.FeatureGroup:
    """Add static or dynamic risk grid polygons to the Folium map.

    Args:
        folium_map: Target Folium Map.
        cells_data: Either a list of cell dicts or the static_risk_scores dict.
        horizon: Active forecast horizon ('NOW', '+1h', '+3h', '+6h').
        predictions_map: Optional mapping of cell_id -> prediction info for dynamic horizons.
        hotspots_data: Optional hotspots list to correlate chronic waterlogging sites.
        dynamic_predictions: Alias for predictions_map.

    Returns:
        The added folium.FeatureGroup.
    """
    if predictions_map is None and dynamic_predictions is not None:
        predictions_map = dynamic_predictions

    layer_name = f"Risk Grid ({horizon})" if horizon != "NOW" else "Topographic Vulnerability Grid"
    cells_group = folium.FeatureGroup(name=layer_name, show=True)

    if isinstance(cells_data, dict):
        cells = cells_data.get("cells", [])
    elif isinstance(cells_data, list):
        cells = cells_data
    else:
        cells = []

    # Map hotspot cells
    hotspot_cell_ids = set()
    if hotspots_data:
        for h in hotspots_data:
            if h.get("cell_id"):
                hotspot_cell_ids.add(h.get("cell_id"))

    for cell in cells:
        cell_id = cell.get("cell_id") or cell.get("id", "UNKNOWN_CELL")
        geometry = cell.get("geometry")
        if not geometry:
            continue

        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except Exception:
                continue

        raw = cell.get("raw_features") or {}
        elevation = raw.get("elevation", cell.get("elevation"))
        slope = raw.get("slope", cell.get("slope"))
        flow_acc = raw.get("flow_accumulation", cell.get("flow_acc"))
        imperv = raw.get("imperviousness", cell.get("imperviousness"))
        name = cell.get("name", f"Grid Cell {cell_id}")
        is_hotspot = cell_id in hotspot_cell_ids

        # Dynamic prediction vs. static baseline presentation
        if predictions_map and cell_id in predictions_map:
            pred = predictions_map[cell_id]
            raw_prob = pred.get("probability")
            if raw_prob is not None:
                try:
                    prob = float(raw_prob)
                    prob_pct = int(round(prob * 100))
                    prob_line = f"<div><b>Probability:</b> <span style='font-weight:700;'>{prob_pct}%</span></div>"
                    tooltip_prob = f" ({prob_pct}%)"
                except (ValueError, TypeError):
                    prob = 0.0
                    prob_line = ""
                    tooltip_prob = ""
            else:
                prob = 0.0
                prob_line = ""  # Omitted when probability is unavailable
                tooltip_prob = ""

            level = str(pred.get("level", "LOW")).upper()
            style = get_risk_tier_style(prob, level=level)
            ts = pred.get("timestamp")
            ts_line = f"<div><b>Timestamp:</b> {ts}</div>" if ts else ""
            expl = pred.get("explanation")
            why_flagged_html = format_why_flagged_html(expl, raw_features=raw, is_hotspot=is_hotspot, risk_level=level)
            tooltip_val = f"{level}{tooltip_prob}"
        else:
            score = float(cell.get("vulnerability_score", cell.get("vulnerability", 0.0)))
            level = str(cell.get("risk_level", "LOW")).upper()
            style = get_risk_tier_style(score, level=level)
            prob_line = ""  # Omitted when probability is unavailable
            ts_line = ""
            why_flagged_html = format_why_flagged_html(None, raw_features=raw, is_hotspot=is_hotspot, risk_level=level)
            tooltip_val = f"{level} ({score:.2f})"

        elev_str = f"{float(elevation):.1f} m" if elevation is not None else "N/A"
        slope_str = f"{float(slope):.1f}%" if slope is not None else "N/A"
        flow_str = f"{float(flow_acc):,.0f}" if flow_acc is not None else "N/A"
        imperv_str = f"{float(imperv)*100:.0f}%" if imperv is not None else "N/A"

        popup_html = (
            "<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; min-width: 240px; padding: 4px;\">"
            "<div style=\"display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;\">"
            "<span style=\"font-size:10px; font-weight:700; color:#0284c7; text-transform:uppercase; letter-spacing:0.5px;\">OPERATIONAL RISK CELL</span>"
            f"<span style=\"font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; background:{style['badge_bg']}; color:{style['badge_color']};\">{style['tier']} RISK</span>"
            "</div>"
            f"<div style=\"font-size:13px; font-weight:700; color:#0f172a; margin-bottom:2px;\">{cell_id}</div>"
            f"<div style=\"font-size:11px; color:#64748b; margin-bottom:6px;\">{name}</div>"
            "<div style=\"background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:6px 8px; font-size:11px; color:#334155; line-height:1.5; margin-bottom:6px;\">"
            f"<div><b>Risk Level:</b> <span style=\"font-weight:700; color:{style['border_color']};\">{style['tier']}</span></div>"
            f"{prob_line}"
            f"<div><b>Forecast Horizon:</b> {horizon}</div>"
            f"{ts_line}"
            f"<div><b>Elevation:</b> {elev_str} &bull; <b>Slope:</b> {slope_str}</div>"
            f"<div><b>Flow Acc:</b> {flow_str} &bull; <b>Impervious:</b> {imperv_str}</div>"
            "</div>"
            "<div style=\"background:#f1f5f9; border-radius:4px; padding:6px 8px; margin-bottom:6px;\">"
            "<div style=\"font-size:10px; font-weight:700; color:#475569; text-transform:uppercase; margin-bottom:3px;\">Why Flagged</div>"
            f"{why_flagged_html}"
            "</div>"
            "<div style=\"font-size:9.5px; color:#94a3b8; border-top:1px solid #f1f5f9; padding-top:4px;\">"
            "Prototype Baseline: Reference Spatial Grid (WGS84)"
            "</div>"
            "</div>"
        )

        folium.GeoJson(
            data={
                "type": "Feature",
                "geometry": geometry,
                "properties": {"cell_id": cell_id, "tier": style["tier"]},
            },
            style_function=lambda x, fill=style["fill_color"], border=style["border_color"], op=style["fill_opacity"], wt=style["weight"]: {
                "fillColor": fill,
                "color": border,
                "weight": wt,
                "fillOpacity": op,
            },
            tooltip=f"Cell: {cell_id} | Risk: {tooltip_val}",
            popup=folium.Popup(popup_html, max_width=320),
        ).add_to(cells_group)

    cells_group.add_to(folium_map)
    return cells_group


def add_hotspots_layer(
    folium_map: folium.Map,
    hotspots_data: List[Dict[str, Any]],
) -> folium.FeatureGroup:
    """Add chronic waterlogging hotspot markers to the Folium map.

    Args:
        folium_map: Target Folium Map.
        hotspots_data: List of hotspot dictionaries.

    Returns:
        The added folium.FeatureGroup.
    """
    hotspots_group = folium.FeatureGroup(name="Monitored Hotspots", show=True)

    for h in hotspots_data or []:
        hotspot_id = h.get("hotspot_id", "HS")
        name = h.get("name", "Unknown Hotspot")
        lat = h.get("latitude")
        lon = h.get("longitude")
        if lat is None or lon is None:
            continue

        severity = h.get("severity_tier", "Moderate")
        elevation = h.get("elevation_m", 0.0)
        trigger_6h = h.get("typical_trigger_rain_6h_mm", 0.0)
        infra_items = h.get("critical_infrastructure_nearby") or []
        cause = h.get("primary_vulnerability_cause") or "Chronic low-lying drainage depression."

        if severity == "Severe":
            fill_color = "#ef4444"
            border_color = "#991b1b"
            badge_bg = "#fee2e2"
            badge_col = "#991b1b"
            radius = 8
        else:
            fill_color = "#f59e0b"
            border_color = "#b45309"
            badge_bg = "#fef3c7"
            badge_col = "#92400e"
            radius = 7

        infra_str = ", ".join(infra_items[:2]) if infra_items else "Road corridor"

        popup_html = (
            "<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; min-width: 230px; padding: 4px;\">"
            "<div style=\"display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;\">"
            "<span style=\"font-size:10px; font-weight:700; color:#b45309; text-transform:uppercase; letter-spacing:0.5px;\">WATERLOGGING HOTSPOT</span>"
            f"<span style=\"font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; background:{badge_bg}; color:{badge_col};\">{severity}</span>"
            "</div>"
            f"<div style=\"font-size:13px; font-weight:700; color:#0f172a; margin-bottom:2px;\">{hotspot_id}: {name}</div>"
            "<div style=\"background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:6px 8px; font-size:11px; color:#334155; line-height:1.5; margin-bottom:6px;\">"
            f"<div><b>Elevation:</b> {float(elevation):.1f} m</div>"
            f"<div><b>Trigger Rain (6h):</b> {float(trigger_6h):.1f} mm</div>"
            f"<div><b>Nearby Assets:</b> {infra_str}</div>"
            "</div>"
            f"<div style=\"font-size:10.5px; color:#475569; line-height:1.35; margin-bottom:6px;\">{cause}</div>"
            "<div style=\"font-size:9.5px; color:#94a3b8; border-top:1px solid #f1f5f9; padding-top:4px;\">"
            "Prototype Baseline: Reference Spatial Grid"
            "</div>"
            "</div>"
        )

        folium.CircleMarker(
            location=[float(lat), float(lon)],
            radius=radius,
            color=border_color,
            weight=2.5,
            fill=True,
            fill_color=fill_color,
            fill_opacity=0.9,
            tooltip=f"⚠️ Hotspot: {hotspot_id} - {name} ({severity})",
            popup=folium.Popup(popup_html, max_width=320),
        ).add_to(hotspots_group)

    hotspots_group.add_to(folium_map)
    return hotspots_group


def add_sensor_layer(
    folium_map: folium.Map,
    sensors_data: List[Dict[str, Any]],
) -> folium.FeatureGroup:
    """Add hydrological sensor station markers to the Folium map.

    Args:
        folium_map: Target Folium Map.
        sensors_data: List of sensor dictionaries.

    Returns:
        The added folium.FeatureGroup.
    """
    sensor_group = folium.FeatureGroup(name="Sensor Stations", show=True)

    for s in sensors_data or []:
        node_id = s.get("node_id", "NODE")
        name = s.get("name", "Sensor Station")
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is None or lon is None:
            continue

        water_level = float(s.get("water_level_cm", 25.0))
        rain_rate = float(s.get("rainfall_rate_mm_h", 0.0))
        battery = float(s.get("battery_pct", 98.0))
        status = str(s.get("status", "NORMAL"))
        source = str(s.get("source", "Simulated Telemetry"))
        warn_th = float(s.get("warning_threshold_cm", 75.0))

        if status in ("CRITICAL", "ALARM") or water_level >= 120.0:
            badge_bg = "#fee2e2"
            badge_col = "#991b1b"
            status_label = "CRITICAL"
        elif status == "WARNING" or water_level >= warn_th:
            badge_bg = "#fef3c7"
            badge_col = "#92400e"
            status_label = "ELEVATED"
        else:
            badge_bg = "#dbeafe"
            badge_col = "#1e40af"
            status_label = "NORMAL"

        popup_html = (
            "<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; min-width: 220px; padding: 4px;\">"
            "<div style=\"display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;\">"
            "<span style=\"font-size:10px; font-weight:700; color:#0284c7; text-transform:uppercase; letter-spacing:0.5px;\">TELEMETRY SENSOR</span>"
            f"<span style=\"font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; background:{badge_bg}; color:{badge_col};\">{status_label}</span>"
            "</div>"
            f"<div style=\"font-size:13px; font-weight:700; color:#0f172a; margin-bottom:2px;\">{node_id}</div>"
            f"<div style=\"font-size:11px; color:#64748b; margin-bottom:6px;\">{name}</div>"
            "<div style=\"background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:6px 8px; font-size:11px; color:#334155; line-height:1.5; margin-bottom:6px;\">"
            f"<div><b>Water Stage:</b> <span style=\"font-weight:700; color:#0369a1;\">{water_level:.1f} cm</span> (Warn: {warn_th:.0f}cm)</div>"
            f"<div><b>Rainfall Rate:</b> {rain_rate:.1f} mm/h</div>"
            f"<div><b>Battery Level:</b> {battery:.1f}%</div>"
            f"<div><b>Source:</b> {source}</div>"
            "</div>"
            "<div style=\"font-size:9.5px; color:#94a3b8; border-top:1px solid #f1f5f9; padding-top:4px;\">"
            "Monitored Drainage Node &bull; Telemetry Feed"
            "</div>"
            "</div>"
        )

        folium.CircleMarker(
            location=[float(lat), float(lon)],
            radius=7,
            color="#0369a1",
            weight=2.5,
            fill=True,
            fill_color="#38bdf8",
            fill_opacity=0.95,
            tooltip=f"📡 Sensor: {node_id} | Stage: {water_level:.1f} cm ({status_label})",
            popup=folium.Popup(popup_html, max_width=320),
        ).add_to(sensor_group)

    sensor_group.add_to(folium_map)
    return sensor_group


def add_map_legend(folium_map: folium.Map, horizon: str = "NOW", is_dynamic: bool = False) -> None:
    """Inject a clean, compact, floating map legend into the Folium map."""
    dynamic_severe_html = (
        "<div style=\"display:flex; align-items:center; gap:6px; margin-bottom:2px;\">"
        "<span style=\"display:inline-block; width:12px; height:8px; background:#991b1b; opacity:0.85; border:1px solid #7f1d1d; border-radius:2px;\"></span>"
        "<span style=\"color:#1e293b;\">Severe Inundation</span>"
        "</div>"
    ) if is_dynamic else ""

    legend_html = f"""
    <div class="chetna-folium-legend" style="
        position: fixed;
        bottom: 22px;
        right: 22px;
        z-index: 9999;
        background: rgba(255, 255, 255, 0.96);
        backdrop-filter: blur(8px);
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 9px 12px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 11px;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.12);
        line-height: 1.45;
        max-width: 220px;
    ">
        <div style="font-weight: 700; font-size: 10px; color: #0f172a; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 5px; border-bottom: 1px solid #e2e8f0; padding-bottom: 3px;">
            Operational Risk Legend ({horizon})
        </div>
        <div style="margin-bottom: 5px;">
            <div style="font-size: 9px; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 2px;">Risk Tiers</div>
            {dynamic_severe_html}
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
                <span style="display:inline-block; width:12px; height:8px; background:#dc2626; opacity:0.8; border:1px solid #991b1b; border-radius:2px;"></span>
                <span style="color:#1e293b;">High Risk (&ge; 0.70)</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
                <span style="display:inline-block; width:12px; height:8px; background:#f59e0b; opacity:0.8; border:1px solid #b45309; border-radius:2px;"></span>
                <span style="color:#1e293b;">Medium Risk (0.40–0.70)</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:12px; height:8px; background:#16a34a; opacity:0.8; border:1px solid #15803d; border-radius:2px;"></span>
                <span style="color:#1e293b;">Low Risk (&lt; 0.40)</span>
            </div>
        </div>
        <div style="border-top: 1px solid #f1f5f9; padding-top: 4px;">
            <div style="font-size: 9px; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 2px;">Monitored Features</div>
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
                <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#ef4444; border:1.5px solid #991b1b;"></span>
                <span style="color:#1e293b;">Hotspot (Waterlogging)</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#38bdf8; border:1.5px solid #0369a1;"></span>
                <span style="color:#1e293b;">Sensor (Telemetry)</span>
            </div>
        </div>
        <div style="margin-top: 5px; font-size: 8.5px; color: #94a3b8; border-top: 1px solid #f1f5f9; padding-top: 3px;">
            Prototype Baseline: Reference Spatial Grid
        </div>
    </div>
    """
    folium_map.get_root().html.add_child(folium.Element(legend_html))


# ---------------------------------------------------------------------------
# Mapbox & PyDeck Operational Mapping Engine
# ---------------------------------------------------------------------------

def get_risk_tier_rgba(score: float, level: Optional[str] = None) -> Tuple[List[int], List[int]]:
    """Return RGBA fill and border colors for pydeck layers."""
    style = get_risk_tier_style(score, level=level)
    tier = style["tier"]
    if tier == "SEVERE":
        return [153, 27, 27, 160], [127, 29, 29, 230]
    elif tier == "HIGH":
        return [220, 38, 38, 140], [153, 27, 27, 220]
    elif tier == "MEDIUM":
        return [245, 158, 11, 120], [180, 83, 9, 210]
    else:
        return [22, 163, 74, 90], [21, 128, 61, 200]


def get_mapbox_map_style(mapbox_token: Optional[str] = None) -> Tuple[str, Optional[Dict[str, str]], bool]:
    """Determine map style and API keys based on Mapbox token availability.

    Returns:
        (map_style, api_keys_dict, is_mapbox_active)
    """
    settings = Settings()
    token = (mapbox_token or settings.mapbox_access_token or "").strip()
    is_valid = bool(
        token
        and len(token) > 15
        and not token.startswith("pk.placeholder")
        and not token.startswith("pk.your_")
    )
    if is_valid:
        return "mapbox://styles/mapbox/light-v10", {"mapbox": token}, True
    else:
        # High quality Carto Positron vector style (no token required, zero telemetry leak)
        return pdk.map_styles.CARTO_LIGHT, None, False


def build_risk_cells_deck_layer(
    cells_data: Union[List[Dict[str, Any]], Dict[str, Any]],
    horizon: str = "NOW",
    predictions_map: Optional[Dict[str, Dict[str, Any]]] = None,
    hotspots_data: Optional[List[Dict[str, Any]]] = None,
) -> Optional[pdk.Layer]:
    """Construct a pydeck PolygonLayer for spatial risk cells."""
    if isinstance(cells_data, dict):
        cells = cells_data.get("cells", [])
        if cells is None:
            cells = []
    elif isinstance(cells_data, list):
        cells = cells_data
    else:
        cells = []

    if not cells:
        return None

    hotspot_cell_ids = set()
    if hotspots_data and isinstance(hotspots_data, list):
        for h in hotspots_data:
            if isinstance(h, dict) and h.get("cell_id"):
                hotspot_cell_ids.add(h.get("cell_id"))

    records = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        cell_id = cell.get("cell_id") or cell.get("id", "UNKNOWN_CELL")
        geometry = cell.get("geometry")
        if not geometry:
            continue
        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except Exception:
                continue

        if not isinstance(geometry, dict):
            continue

        raw_coords = geometry.get("coordinates")
        coords = []
        geom_type = geometry.get("type", "")
        if geom_type == "Polygon" and isinstance(raw_coords, (list, tuple)) and len(raw_coords) > 0:
            coords = raw_coords[0]
        elif geom_type == "MultiPolygon" and isinstance(raw_coords, (list, tuple)) and len(raw_coords) > 0:
            first_poly = raw_coords[0]
            if isinstance(first_poly, (list, tuple)) and len(first_poly) > 0:
                coords = first_poly[0]

        if not coords or not isinstance(coords, (list, tuple)):
            continue

        valid_coords = []
        for pt in coords:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2 and pt[0] is not None and pt[1] is not None:
                try:
                    valid_coords.append([float(pt[0]), float(pt[1])])
                except (ValueError, TypeError):
                    continue

        if len(valid_coords) < 3:
            continue

        raw = cell.get("raw_features") if isinstance(cell.get("raw_features"), dict) else {}
        elevation = raw.get("elevation", cell.get("elevation"))
        name = cell.get("name", f"Grid Cell {cell_id}")

        if predictions_map and isinstance(predictions_map, dict) and cell_id in predictions_map:
            pred = predictions_map[cell_id] or {}
            raw_prob = pred.get("probability", 0.0)
            prob = float(raw_prob) if raw_prob is not None else 0.0
            level = str(pred.get("level", "LOW") or "LOW").upper()
            fill_rgba, border_rgba = get_risk_tier_rgba(prob, level=level)
            prob_text = f" &bull; Prob: {int(round(prob * 100))}%"
            expl = pred.get("explanation")
            why_txt = expl.get("summary", "Elevated runoff") if isinstance(expl, dict) else "Dynamic Precipitation"
        else:
            raw_score = cell.get("vulnerability_score", cell.get("vulnerability", 0.0))
            score = float(raw_score) if raw_score is not None else 0.0
            level = str(cell.get("risk_level", "LOW") or "LOW").upper()
            fill_rgba, border_rgba = get_risk_tier_rgba(score, level=level)
            prob_text = f" &bull; Score: {score:.2f}"
            why_txt = "Topographic Basin Vulnerability"

        try:
            elev_str = f"{float(elevation):.1f}m" if elevation is not None else "N/A"
        except (ValueError, TypeError):
            elev_str = "N/A"

        records.append({
            "polygon": valid_coords,
            "fill_color": fill_rgba,
            "border_color": border_rgba,
            "cell_id": cell_id,
            "name": name,
            "tier": level,
            "tooltip_title": f"Risk Cell: {cell_id} ({level})",
            "tooltip_body": f"{name}<br/>Elevation: {elev_str}{prob_text}<br/>Why: {why_txt}",
        })

    if not records:
        return None

    return pdk.Layer(
        "PolygonLayer",
        data=records,
        get_polygon="polygon",
        get_fill_color="fill_color",
        get_line_color="border_color",
        get_line_width=2,
        line_width_min_pixels=1,
        filled=True,
        stroked=True,
        pickable=True,
        auto_highlight=True,
    )


def build_hotspots_deck_layer(
    hotspots_data: Optional[List[Dict[str, Any]]],
) -> Optional[pdk.Layer]:
    """Construct a pydeck ScatterplotLayer for waterlogging hotspots."""
    if not hotspots_data or not isinstance(hotspots_data, list):
        return None

    records = []
    for h in hotspots_data:
        if not isinstance(h, dict):
            continue
        lat = h.get("latitude")
        lon = h.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            f_lat = float(lat)
            f_lon = float(lon)
        except (ValueError, TypeError):
            continue

        sev = str(h.get("severity_tier", "Moderate") or "Moderate")
        color = [220, 38, 38, 230] if sev == "Severe" else [245, 158, 11, 230]
        records.append({
            "coordinates": [f_lon, f_lat],
            "color": color,
            "radius": 170,
            "hotspot_id": h.get("hotspot_id", "HS"),
            "name": h.get("name", "Hotspot"),
            "severity": sev,
            "tooltip_title": f"Hotspot: {h.get('name')} ({h.get('hotspot_id')})",
            "tooltip_body": f"Severity: <b>{sev}</b><br/>Trigger: {h.get('typical_trigger_rain_1h_mm', 'N/A')} mm/h<br/>Cause: {h.get('primary_vulnerability_cause', 'Drainage Bottleneck')}",
        })

    if not records:
        return None

    return pdk.Layer(
        "ScatterplotLayer",
        data=records,
        get_position="coordinates",
        get_fill_color="color",
        get_line_color="[255, 255, 255, 220]",
        get_line_width=2,
        line_width_min_pixels=1.5,
        get_radius="radius",
        radius_min_pixels=6,
        radius_max_pixels=16,
        stroked=True,
        filled=True,
        pickable=True,
        auto_highlight=True,
    )


def build_sensors_deck_layer(
    sensors_data: Optional[List[Dict[str, Any]]],
) -> Optional[pdk.Layer]:
    """Construct a pydeck ScatterplotLayer for telemetry monitoring stations."""
    if not sensors_data or not isinstance(sensors_data, list):
        return None

    records = []
    for s in sensors_data:
        if not isinstance(s, dict):
            continue
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            f_lat = float(lat)
            f_lon = float(lon)
        except (ValueError, TypeError):
            continue

        status = str(s.get("status", "ACTIVE") or "ACTIVE").upper()
        try:
            raw_stage = s.get("water_level_cm", 25.0)
            stage = float(raw_stage) if raw_stage is not None else 25.0
        except (ValueError, TypeError):
            stage = 25.0

        try:
            raw_warn = s.get("warning_threshold_cm", 75.0)
            warn = float(raw_warn) if raw_warn is not None else 75.0
        except (ValueError, TypeError):
            warn = 75.0

        try:
            raw_batt = s.get("battery_pct", 95.0)
            batt = float(raw_batt) if raw_batt is not None else 95.0
        except (ValueError, TypeError):
            batt = 95.0

        if stage >= warn or status in ("WARNING", "CRITICAL"):
            color = [220, 38, 38, 240]
        else:
            color = [14, 165, 233, 230]

        records.append({
            "coordinates": [f_lon, f_lat],
            "color": color,
            "radius": 140,
            "node_id": s.get("node_id", "NODE"),
            "name": s.get("name", "Station"),
            "water_level": stage,
            "tooltip_title": f"Telemetry Node: {s.get('node_id')}",
            "tooltip_body": f"Station: {s.get('name')}<br/>Stage: <b>{stage:.1f} cm</b> (Warn: {warn:.0f} cm)<br/>Status: {status} &bull; Batt: {batt:.0f}%",
        })

    if not records:
        return None

    return pdk.Layer(
        "ScatterplotLayer",
        data=records,
        get_position="coordinates",
        get_fill_color="color",
        get_line_color="[255, 255, 255, 230]",
        get_line_width=2,
        line_width_min_pixels=1.5,
        get_radius="radius",
        radius_min_pixels=5,
        radius_max_pixels=14,
        stroked=True,
        filled=True,
        pickable=True,
        auto_highlight=True,
    )


def build_operational_deck(
    center: Tuple[float, float] = DEFAULT_PILOT_CENTER,
    zoom_start: float = 11.8,
    static_risk_data: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
    hotspots_data: Optional[List[Dict[str, Any]]] = None,
    sensors_data: Optional[List[Dict[str, Any]]] = None,
    layer_static: bool = True,
    layer_hotspots: bool = True,
    layer_sensors: bool = True,
    horizon: str = "NOW",
    predictions_map: Optional[Dict[str, Dict[str, Any]]] = None,
    mapbox_token: Optional[str] = None,
) -> pdk.Deck:
    """Construct an operational Mapbox / pydeck Deck for F1 Authority Operations Center and F2 Community Map."""
    layers: List[pdk.Layer] = []

    # 1. Risk Cells PolygonLayer
    if layer_static and static_risk_data:
        cell_layer = build_risk_cells_deck_layer(
            cells_data=static_risk_data,
            horizon=horizon,
            predictions_map=predictions_map,
            hotspots_data=hotspots_data,
        )
        if cell_layer is not None:
            layers.append(cell_layer)

    # 2. Hotspots ScatterplotLayer
    if layer_hotspots and hotspots_data:
        hotspots_layer = build_hotspots_deck_layer(hotspots_data)
        if hotspots_layer is not None:
            layers.append(hotspots_layer)

    # 3. Telemetry Sensors ScatterplotLayer
    if layer_sensors and sensors_data:
        sensors_layer = build_sensors_deck_layer(sensors_data)
        if sensors_layer is not None:
            layers.append(sensors_layer)

    # Defensive coordinate normalization
    c_lat, c_lon = DEFAULT_PILOT_CENTER
    if center and len(center) >= 2 and center[0] is not None and center[1] is not None:
        try:
            c_lat = float(center[0])
            c_lon = float(center[1])
        except (ValueError, TypeError):
            c_lat, c_lon = DEFAULT_PILOT_CENTER

    try:
        z_start = float(zoom_start) if zoom_start is not None else 11.8
    except (ValueError, TypeError):
        z_start = 11.8

    view_state = pdk.ViewState(
        latitude=c_lat,
        longitude=c_lon,
        zoom=z_start,
        pitch=0,
        bearing=0,
    )

    map_style, api_keys, _ = get_mapbox_map_style(mapbox_token)

    tooltip = {
        "html": (
            "<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11.5px; line-height: 1.45;\">"
            "<b style=\"font-size: 12.5px; color: #38bdf8;\">{tooltip_title}</b><br/>"
            "{tooltip_body}"
            "</div>"
        ),
        "style": {
            "backgroundColor": "rgba(15, 23, 42, 0.94)",
            "color": "#f8fafc",
            "padding": "9px 13px",
            "borderRadius": "7px",
            "border": "1px solid #334155",
            "boxShadow": "0 4px 14px rgba(0, 0, 0, 0.35)",
        },
    }

    return pdk.Deck(
        layers=[l for l in layers if l is not None],
        initial_view_state=view_state,
        map_style=map_style,
        api_keys=api_keys,
        tooltip=tooltip,
    )


def validate_deck(deck_obj: Any) -> bool:
    """Validate that deck_obj is an authentic, valid pdk.Deck instance with valid JSON spec.

    Verifies:
      1. isinstance(deck_obj, pdk.Deck)
      2. Not a folium.Map or branca/folium Element
      3. deck_obj.layers is a valid sequence with NO None elements
      4. deck_obj.initial_view_state is present and valid
      5. deck_obj.to_json() produces valid JSON parseable into DeckGLJsonChart schema
         (containing initialViewState with valid coords and list of layers)
    """
    if deck_obj is None:
        return False
    if not isinstance(deck_obj, pdk.Deck) or isinstance(deck_obj, folium.Map) or hasattr(deck_obj, "get_root"):
        return False
    if not hasattr(deck_obj, "layers") or not isinstance(deck_obj.layers, (list, tuple)):
        return False
    if any(layer is None for layer in deck_obj.layers):
        return False
    if not hasattr(deck_obj, "initial_view_state") or deck_obj.initial_view_state is None:
        return False

    try:
        raw_json = deck_obj.to_json()
        if not raw_json or not isinstance(raw_json, str):
            return False
        spec = json.loads(raw_json)
        if not isinstance(spec, dict):
            return False
        if "initialViewState" not in spec or not isinstance(spec["initialViewState"], dict):
            return False
        ivs = spec["initialViewState"]
        lat = ivs.get("latitude")
        lon = ivs.get("longitude")
        if lat is None or lon is None or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return False
        if "layers" not in spec or not isinstance(spec["layers"], list):
            return False
        for l in spec["layers"]:
            if not isinstance(l, dict) or "@@type" not in l:
                return False
    except Exception:
        return False

    return True


def build_citizen_route_deck(
    center: Tuple[float, float] = DEFAULT_PILOT_CENTER,
    zoom_start: float = 12.2,
    route_coords: Optional[List[Dict[str, float]]] = None,
    start_coord: Optional[Tuple[float, float]] = None,
    dest_coord: Optional[Tuple[float, float]] = None,
    dest_name: str = "Designated Shelter",
    shelters_data: Optional[List[Dict[str, Any]]] = None,
    hotspots_data: Optional[List[Dict[str, Any]]] = None,
    mapbox_token: Optional[str] = None,
) -> pdk.Deck:
    """Construct an interactive Mapbox / pydeck Deck for F2 Citizen Safety Portal safe route."""
    layers: List[pdk.Layer] = []

    # 1. Hotspot markers as contextual warning beacons
    if hotspots_data:
        hotspots_layer = build_hotspots_deck_layer(hotspots_data)
        if hotspots_layer is not None:
            layers.append(hotspots_layer)

    # 2. Safe shelters scatterplot layer
    if shelters_data:
        shelter_records = []
        for sh in shelters_data:
            lat = sh.get("latitude")
            lon = sh.get("longitude")
            if lat is not None and lon is not None:
                shelter_records.append({
                    "coordinates": [float(lon), float(lat)],
                    "name": sh.get("name", "Shelter"),
                    "color": [16, 185, 129, 230],
                    "radius": 150,
                    "tooltip_title": f"Safe Shelter: {sh.get('name')}",
                    "tooltip_body": f"Vicinity: {sh.get('vicinity', 'Elevated Facility')}<br/>Designated Safe Evacuation Ground",
                })
        if shelter_records:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=shelter_records,
                    get_position="coordinates",
                    get_fill_color="color",
                    get_line_color="[255, 255, 255, 230]",
                    get_line_width=2,
                    line_width_min_pixels=1.5,
                    get_radius="radius",
                    radius_min_pixels=5,
                    radius_max_pixels=14,
                    stroked=True,
                    filled=True,
                    pickable=True,
                )
            )

    # 3. Path Layer for the Safe Route
    if route_coords and len(route_coords) >= 2:
        path_points = []
        for p in route_coords:
            if isinstance(p, dict) and p.get("lon") is not None and p.get("lat") is not None:
                try:
                    path_points.append([float(p["lon"]), float(p["lat"])])
                except (ValueError, TypeError):
                    continue
        if len(path_points) >= 2:
            layers.append(
                pdk.Layer(
                    "PathLayer",
                    data=[{
                        "path": path_points,
                        "color": [2, 132, 199, 240],
                        "width": 6,
                        "tooltip_title": "Safe Navigation Route",
                        "tooltip_body": f"Decision-support route to {dest_name}",
                    }],
                    get_path="path",
                    get_color="color",
                    get_width="width",
                    width_min_pixels=4,
                    width_max_pixels=12,
                    pickable=True,
                )
            )

    # 4. Start & Destination Pins
    pins = []
    if start_coord and len(start_coord) >= 2 and start_coord[0] is not None and start_coord[1] is not None:
        try:
            pins.append({
                "coordinates": [float(start_coord[1]), float(start_coord[0])],
                "color": [22, 163, 74, 255],
                "radius": 180,
                "tooltip_title": "Origin Location",
                "tooltip_body": "Your selected starting position",
            })
        except (ValueError, TypeError):
            pass
    if dest_coord and len(dest_coord) >= 2 and dest_coord[0] is not None and dest_coord[1] is not None:
        try:
            pins.append({
                "coordinates": [float(dest_coord[1]), float(dest_coord[0])],
                "color": [220, 38, 38, 255],
                "radius": 200,
                "tooltip_title": f"Destination Shelter: {dest_name}",
                "tooltip_body": "Nearest accessible elevated safe haven",
            })
        except (ValueError, TypeError):
            pass
    if pins:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=pins,
                get_position="coordinates",
                get_fill_color="color",
                get_line_color="[255, 255, 255, 255]",
                get_line_width=2.5,
                line_width_min_pixels=2,
                get_radius="radius",
                radius_min_pixels=7,
                radius_max_pixels=18,
                stroked=True,
                filled=True,
                pickable=True,
            )
        )

    c_lat, c_lon = DEFAULT_PILOT_CENTER
    if center and len(center) >= 2 and center[0] is not None and center[1] is not None:
        try:
            c_lat = float(center[0])
            c_lon = float(center[1])
        except (ValueError, TypeError):
            c_lat, c_lon = DEFAULT_PILOT_CENTER

    try:
        z_start = float(zoom_start) if zoom_start is not None else 12.2
    except (ValueError, TypeError):
        z_start = 12.2

    view_state = pdk.ViewState(
        latitude=c_lat,
        longitude=c_lon,
        zoom=z_start,
        pitch=0,
        bearing=0,
    )
    map_style, api_keys, _ = get_mapbox_map_style(mapbox_token)

    tooltip = {
        "html": (
            "<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 11.5px; line-height: 1.45;\">"
            "<b style=\"font-size: 12.5px; color: #38bdf8;\">{tooltip_title}</b><br/>"
            "{tooltip_body}"
            "</div>"
        ),
        "style": {
            "backgroundColor": "rgba(15, 23, 42, 0.94)",
            "color": "#f8fafc",
            "padding": "9px 13px",
            "borderRadius": "7px",
            "border": "1px solid #334155",
            "boxShadow": "0 4px 14px rgba(0, 0, 0, 0.35)",
        },
    }

    return pdk.Deck(
        layers=[l for l in layers if l is not None],
        initial_view_state=view_state,
        map_style=map_style,
        api_keys=api_keys,
        tooltip=tooltip,
    )


def build_operational_map(
    center: Tuple[float, float] = DEFAULT_PILOT_CENTER,
    zoom_start: int = 12,
    static_risk_data: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
    hotspots_data: Optional[List[Dict[str, Any]]] = None,
    sensors_data: Optional[List[Dict[str, Any]]] = None,
    layer_static: bool = True,
    layer_hotspots: bool = True,
    layer_sensors: bool = True,
    horizon: str = "NOW",
    predictions_map: Optional[Dict[str, Dict[str, Any]]] = None,
    add_legend: bool = True,
    add_fullscreen: bool = True,
    backend: str = "pydeck",
) -> Union[pdk.Deck, folium.Map]:
    """Construct an operational map using Mapbox/PyDeck by default, with Folium fallback.

    Args:
        backend: "pydeck" (default, Mapbox WebGL engine) or "folium" (Leaflet).
    """
    if backend == "folium":
        folium_map = folium.Map(
            location=[center[0], center[1]],
            zoom_start=zoom_start,
            tiles="OpenStreetMap",
            control_scale=True,
        )

        if add_fullscreen:
            plugins.Fullscreen(
                position="topleft",
                title="Expand to Fullscreen",
                title_cancel="Exit Fullscreen",
                force_separate_button=True,
            ).add_to(folium_map)

        if layer_static and static_risk_data:
            add_risk_cells_layer(
                folium_map=folium_map,
                cells_data=static_risk_data,
                horizon=horizon,
                predictions_map=predictions_map,
                hotspots_data=hotspots_data,
            )

        if layer_hotspots and hotspots_data:
            add_hotspots_layer(
                folium_map=folium_map,
                hotspots_data=hotspots_data,
            )

        if layer_sensors and sensors_data:
            add_sensor_layer(
                folium_map=folium_map,
                sensors_data=sensors_data,
            )

        if add_legend:
            is_dynamic = bool(predictions_map)
            add_map_legend(folium_map, horizon=horizon, is_dynamic=is_dynamic)

        return folium_map

    # Primary PyDeck / Mapbox builder
    return build_operational_deck(
        center=center,
        zoom_start=float(zoom_start),
        static_risk_data=static_risk_data,
        hotspots_data=hotspots_data,
        sensors_data=sensors_data,
        layer_static=layer_static,
        layer_hotspots=layer_hotspots,
        layer_sensors=layer_sensors,
        horizon=horizon,
        predictions_map=predictions_map,
    )

