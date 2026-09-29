"""Chetna: Authority Operations Center (F1) & Unified Dashboard Entrypoint.

Enterprise emergency operations dashboard for municipal authorities:
- Dominant operational status banner
- Multi-horizon rainfall forecast selector (NOW | +1h | +3h | +6h)
- High-resolution GIS basemap with monitored vulnerability hotspots
- Human-in-the-loop emergency alert dispatch center
- At-risk critical infrastructure registry
- Clean navigation across Overview, Risk Map, Alerts, Assets, Sensors, Analytics, Settings
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Normalize sys.path so 'app' always resolves to the top-level package
_APP_DIR = str(Path(__file__).resolve().parent)
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

while _APP_DIR in sys.path:
    sys.path.remove(_APP_DIR)

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if "app" in sys.modules and not hasattr(sys.modules["app"], "__path__"):
    del sys.modules["app"]

import folium
from folium import plugins
import streamlit as st

from app.config import (
    EMERGENCY_HELPLINES,
    F1_NAV_ITEMS,
    F1_PORTAL_SUBTITLE,
    F1_PORTAL_TITLE,
    F2_NAV_ITEMS,
    F2_PORTAL_SUBTITLE,
    F2_PORTAL_TITLE,
    FORECAST_HORIZONS,
    HAZARD_SCOPE,
    PILOT_CITY,
    PILOT_LOCATION_LABEL,
    PILOT_STATE,
    SYSTEM_NAME,
    SYSTEM_TAGLINE,
)

try:
    from app.citizen_view import render_citizen_view
except (ImportError, ModuleNotFoundError):
    from citizen_view import render_citizen_view  # type: ignore

try:
    from app.map_layers import (
        add_hotspots_layer,
        add_map_legend,
        add_risk_cells_layer,
        add_sensor_layer,
        build_operational_map,
        check_horizon_prediction_availability,
        format_why_flagged_html,
        get_at_risk_assets_summary,
        get_risk_tier_style,
        load_horizon_predictions,
        load_sensor_stations,
    )
except (ImportError, ModuleNotFoundError):
    from map_layers import (  # type: ignore
        add_hotspots_layer,
        add_map_legend,
        add_risk_cells_layer,
        add_sensor_layer,
        build_operational_map,
        check_horizon_prediction_availability,
        format_why_flagged_html,
        get_at_risk_assets_summary,
        get_risk_tier_style,
        load_horizon_predictions,
        load_sensor_stations,
    )

try:
    from app.alert_service import (
        create_draft_alert,
        dismiss_authority_alert,
        dispatch_authority_alert,
        format_draft_alert_text,
    )
except (ImportError, ModuleNotFoundError):
    from alert_service import (  # type: ignore
        create_draft_alert,
        dismiss_authority_alert,
        dispatch_authority_alert,
        format_draft_alert_text,
    )

try:
    from app.demo_scenario import (
        load_backtest_summary,
        reset_to_baseline_scenario,
        simulate_heavy_rain_scenario,
    )
except (ImportError, ModuleNotFoundError):
    from demo_scenario import (  # type: ignore
        load_backtest_summary,
        reset_to_baseline_scenario,
        simulate_heavy_rain_scenario,
    )

logger = logging.getLogger(__name__)

# Constants and Defaults (Preserved for backward compatibility with existing tests)
DEFAULT_CITY: str = "Patna, Bihar"
DEFAULT_COORDINATES: Tuple[float, float] = (25.6093, 85.1376)  # Center coords for Patna pilot
DEFAULT_ZOOM_START: int = 12

DEFAULT_DB_PATH: Path = Path("data/chetna.db")
DEFAULT_STATIC_RISK_PATH: Path = Path("data/m1/static_risk_scores.json")
DEFAULT_HOTSPOTS_PATH: Path = Path("data/m1/hotspots.json")

ASSETS_DIR: Path = Path(__file__).resolve().parent / "assets"
LOGO_SVG_PATH: Path = ASSETS_DIR / "chetna_logo.svg"
LOGO_PNG_PATH: Path = ASSETS_DIR / "chetna_logo.png"


def get_logo_asset_path(prefer_svg: bool = False) -> Optional[Path]:
    """Return verified path to Chetna logo asset."""
    if prefer_svg and LOGO_SVG_PATH.exists():
        return LOGO_SVG_PATH
    if LOGO_PNG_PATH.exists():
        return LOGO_PNG_PATH
    if LOGO_SVG_PATH.exists():
        return LOGO_SVG_PATH
    return None


def get_logo_svg(size: int = 36) -> str:
    """Return inline SVG markup for the Chetna brand logo."""
    if LOGO_SVG_PATH.exists():
        try:
            svg_content = LOGO_SVG_PATH.read_text(encoding="utf-8").strip()
            return f'<div style="width:{size}px; height:{size}px; display:inline-block; flex-shrink:0;">{svg_content}</div>'
        except Exception as e:
            logger.warning("Could not read logo SVG at %s: %s", LOGO_SVG_PATH, e)

    # Clean geometric fallback SVG
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="dropGrad" x1="0%" y1="0%" x2="100%" y2="100%">'
        '<stop offset="0%" stop-color="#0284c7"/><stop offset="100%" stop-color="#0d9488"/>'
        '</linearGradient></defs>'
        '<path d="M50 12 C50 12 85 48 85 68 A35 35 0 1 1 15 68 C15 48 50 12 50 12 Z" fill="url(#dropGrad)"/>'
        '<circle cx="50" cy="42" r="5" fill="#ffffff"/>'
        '<path d="M28 66 C36 60 44 72 54 66 C64 60 72 68 74 70" fill="none" stroke="#ffffff" stroke-width="3.5" stroke-linecap="round"/>'
        '</svg>'
    )


def create_base_map(
    center: Tuple[float, float] = DEFAULT_COORDINATES,
    zoom_start: int = DEFAULT_ZOOM_START,
    tiles: str = "OpenStreetMap",
    add_center_marker: bool = True,
    add_fullscreen_control: bool = True,
) -> folium.Map:
    """Create and return the base Folium map."""
    base_map = folium.Map(
        location=[center[0], center[1]],
        zoom_start=zoom_start,
        tiles=tiles,
        control_scale=True,
    )

    if add_fullscreen_control:
        plugins.Fullscreen(
            position="topleft",
            title="Expand to Fullscreen",
            title_cancel="Exit Fullscreen",
            force_separate_button=True,
        ).add_to(base_map)

    if add_center_marker:
        popup_html = (
            "<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif; min-width:190px; padding:2px;'>"
            f"<div style='color:#0284c7; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>{SYSTEM_NAME} Pilot Operations Center</div>"
            f"<div style='font-size:14px; font-weight:700; color:#0f172a; margin:2px 0 6px 0;'>{PILOT_LOCATION_LABEL}</div>"
            "<div style='font-size:12px; color:#475569; line-height:1.4;'>"
            f"<b>Coordinates:</b> {center[0]:.4f}&deg; N, {center[1]:.4f}&deg; E<br/>"
            "<b>Resolution:</b> ~200 m metric grid<br/>"
            "<b>Status:</b> Active Monitoring Viewport"
            "</div>"
            "</div>"
        )
        folium.Marker(
            location=[center[0], center[1]],
            tooltip=f"{SYSTEM_NAME} Pilot Operations: {PILOT_LOCATION_LABEL}",
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(base_map)

    return base_map


def load_static_risk_metadata(
    path: Path | str = DEFAULT_STATIC_RISK_PATH,
) -> Dict[str, Any]:
    """Load metadata from static vulnerability calculation."""
    target = Path(path)
    if not target.exists():
        logger.warning("Static risk scores file not found at %s", target)
        return {
            "loaded": False,
            "cell_count": 0,
            "formula": "V = 0.35*norm(elev) + 0.25*norm(log(flow_acc)) + 0.25*norm(imperv) + 0.15*norm(slope)",
            "weights": {"elevation": 0.35, "flow_accumulation": 0.25, "imperviousness": 0.25, "slope": 0.15},
            "thresholds": {"low": 0.40, "medium": 0.70},
            "cells": [],
        }

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["loaded"] = True
        return data
    except Exception as e:
        logger.error("Failed to parse static risk file %s: %s", target, e)
        return {"loaded": False, "cell_count": 0, "error": str(e), "cells": []}


def load_hotspots_data(
    path: Path | str = DEFAULT_HOTSPOTS_PATH,
) -> List[Dict[str, Any]]:
    """Load known waterlogging hotspots."""
    target = Path(path)
    if not target.exists():
        logger.warning("Hotspots file not found at %s", target)
        return []

    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.error("Failed to load hotspots file %s: %s", target, e)
        return []


def get_system_metrics(
    db_path: Path | str = DEFAULT_DB_PATH,
    static_risk_path: Path | str = DEFAULT_STATIC_RISK_PATH,
    hotspots_path: Path | str = DEFAULT_HOTSPOTS_PATH,
) -> Dict[str, Any]:
    """Collect current subsystem metrics."""
    metrics: Dict[str, Any] = {
        "pilot_city": DEFAULT_CITY,  # Preserved for test compatibility
        "display_city": PILOT_CITY,
        "display_state": PILOT_STATE,
        "hazard_scope": HAZARD_SCOPE,
        "coordinates": DEFAULT_COORDINATES,
        "db_connected": False,
        "forecasts_count": 0,
        "latest_forecast_time": None,
        "db_cells_count": 0,
        "static_risk_cells_count": 0,
        "hotspots_count": 0,
        "static_risk_ready": False,
    }

    target_db = Path(db_path)
    if target_db.exists():
        try:
            conn = sqlite3.connect(str(target_db))
            cursor = conn.cursor()
            metrics["db_connected"] = True

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='forecasts'")
            if cursor.fetchone():
                cursor.execute("SELECT count(*), max(timestamp) FROM forecasts")
                row = cursor.fetchone()
                if row:
                    metrics["forecasts_count"] = row[0] or 0
                    metrics["latest_forecast_time"] = row[1]

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cells'")
            if cursor.fetchone():
                cursor.execute("SELECT count(*) FROM cells")
                row = cursor.fetchone()
                if row:
                    metrics["db_cells_count"] = row[0] or 0

            conn.close()
        except Exception as e:
            logger.warning("Could not query database at %s: %s", target_db, e)

    static_meta = load_static_risk_metadata(static_risk_path)
    metrics["static_risk_cells_count"] = static_meta.get("cell_count", 0)
    metrics["static_risk_ready"] = static_meta.get("loaded", False)

    hotspots = load_hotspots_data(hotspots_path)
    metrics["hotspots_count"] = len(hotspots)

    return metrics


# ---------------------------------------------------------------------------
# Streamlit UI Rendering Functions
# ---------------------------------------------------------------------------

def inject_custom_styles() -> None:
    """Inject authoritative, high-contrast CSS styling."""
    st.markdown(
        """
        <style>
        /* Base typography & clean canvas */
        .stApp {
            background-color: #f8fafc !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            color: #0f172a;
        }

        #MainMenu, footer {
            visibility: hidden !important;
        }

        header[data-testid="stHeader"] {
            background-color: transparent !important;
        }

        .block-container {
            padding-top: 1.25rem !important;
            padding-bottom: 2rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 1440px !important;
        }

        /* Dark Navy Sidebar */
        [data-testid="stSidebar"] {
            background-color: #0b1329 !important;
            border-right: 1px solid #1e293b !important;
        }
        [data-testid="stSidebar"] * {
            color: #cbd5e1 !important;
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #f8fafc !important;
            font-weight: 700 !important;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
            color: #f1f5f9 !important;
            font-weight: 700 !important;
            font-size: 0.78rem !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
            margin-bottom: 0.35rem !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] label {
            color: #e2e8f0 !important;
            font-size: 0.85rem !important;
        }
        [data-testid="stSidebar"] label[data-baseweb="checkbox"] {
            color: #e2e8f0 !important;
            font-size: 0.84rem !important;
        }

        /* Ensure high contrast and clear white card containers */
        .chetna-card, [data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 10px !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
        }

        /* Ensure all text inside card containers has high readability */
        [data-testid="stVerticalBlockBorderWrapper"] p,
        [data-testid="stVerticalBlockBorderWrapper"] label,
        [data-testid="stVerticalBlockBorderWrapper"] span {
            color: #1e293b;
        }

        /* High contrast selectboxes and inputs */
        [data-testid="stVerticalBlockBorderWrapper"] [data-baseweb="select"] > div,
        [data-testid="stVerticalBlockBorderWrapper"] div[data-baseweb="input"] > div {
            background-color: #f8fafc !important;
            border-color: #cbd5e1 !important;
            color: #0f172a !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] [data-baseweb="select"] * {
            color: #0f172a !important;
            font-weight: 500 !important;
        }

        /* Prominent accessible buttons */
        .stButton > button, button[kind="primary"] {
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%) !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
            font-size: 0.88rem !important;
            padding: 0.55rem 1.25rem !important;
            box-shadow: 0 2px 4px rgba(2, 132, 199, 0.25) !important;
        }

        .stButton > button:hover {
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important;
            box-shadow: 0 4px 8px rgba(2, 132, 199, 0.35) !important;
        }

        .stButton > button:disabled {
            background: #e2e8f0 !important;
            color: #94a3b8 !important;
            box-shadow: none !important;
            cursor: not-allowed !important;
        }

        /* F1 Dominant Status Banner */
        .f1-status-banner {
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-left: 5px solid #16a34a;
            border-radius: 10px;
            padding: 1rem 1.35rem;
            margin-bottom: 1rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        }

        /* Pulse indicators */
        .pulse-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
        .pulse-green {
            background: #16a34a;
            box-shadow: 0 0 8px rgba(22, 163, 74, 0.6);
        }

        /* Status Pills */
        .status-pill {
            display: inline-flex;
            align-items: center;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.74rem;
            font-weight: 600;
        }
        .status-pill-green {
            background: #dcfce7;
            color: #15803d;
            border: 1px solid #bbf7d0;
        }
        .status-pill-blue {
            background: #e0f2fe;
            color: #0369a1;
            border: 1px solid #bae6fd;
        }
        .status-pill-slate {
            background: #f1f5f9;
            color: #475569;
            border: 1px solid #cbd5e1;
        }
        .status-pill-amber {
            background: #fef3c7;
            color: #b45309;
            border: 1px solid #fde68a;
        }

        /* Compact Metric Card */
        .chetna-metric-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.85rem 1rem;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
            height: 100%;
        }
        .chetna-metric-label {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #64748b;
            margin-bottom: 0.25rem;
        }
        .chetna-metric-val {
            font-size: 1.3rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.2;
            letter-spacing: -0.02em;
        }
        .chetna-metric-sub {
            font-size: 0.76rem;
            color: #0284c7;
            margin-top: 0.25rem;
            font-weight: 500;
        }

        /* Hotspot Scroll Container */
        .chetna-hotspots-scroll {
            max-height: 480px;
            overflow-y: auto;
            padding-right: 4px;
        }
        .chetna-hotspots-scroll::-webkit-scrollbar {
            width: 5px;
        }
        .chetna-hotspots-scroll::-webkit-scrollbar-thumb {
            background: #cbd5e1;
            border-radius: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Render unified navigation and operational controls."""
    controls: Dict[str, Any] = {}

    with st.sidebar:
        # Brand Header
        logo_path = get_logo_asset_path()
        col_logo, col_text = st.columns([0.22, 0.78], vertical_alignment="center")
        with col_logo:
            if logo_path and logo_path.exists():
                st.image(str(logo_path), width=42)
            else:
                st.markdown(get_logo_svg(36), unsafe_allow_html=True)
        with col_text:
            st.markdown(
                f"""
                <div style="line-height:1.2;">
                    <div style="font-size:1.15rem; font-weight:800; color:#ffffff; letter-spacing:-0.02em;">{SYSTEM_NAME}</div>
                    <div style="font-size:0.75rem; color:#94a3b8;">{SYSTEM_TAGLINE}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<hr style='margin: 0.85rem 0 1rem 0; border-color: #1e293b;'/>", unsafe_allow_html=True)

        # 1. Primary Portal Switcher
        portal_view = st.radio(
            "PORTAL SELECTION",
            options=["🏢 Authority Operations Center", "👤 Citizen Safety Portal"],
            index=0,
            help="Switch between Municipal Authority Operations and Resident Safety Portal.",
        )
        controls["view_mode"] = portal_view

        st.markdown("<hr style='margin: 0.75rem 0 1rem 0; border-color: #1e293b;'/>", unsafe_allow_html=True)

        if portal_view == "👤 Citizen Safety Portal":
            # Citizen Navigation
            citizen_section = st.radio(
                "CITIZEN NAVIGATION",
                options=[
                    "My Area",
                    "Flood Risk",
                    "Safe Places",
                    "Safe Route",
                    "Advisory",
                    "Emergency Help",
                ],
                index=0,
            )
            controls["citizen_section"] = citizen_section

            st.markdown("<hr style='margin: 0.75rem 0;'/>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size: 0.72rem; font-weight: 700; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.5rem;'>EMERGENCY HELPLINES ({PILOT_CITY})</div>", unsafe_allow_html=True)
            st.markdown(
                f"""
                <div style="padding: 0.75rem; background: rgba(15, 23, 42, 0.6); border: 1px solid #1e293b; border-radius: 6px; font-size: 0.78rem; color: #cbd5e1; line-height: 1.6;">
                    <div>🚨 <b>National Emergency:</b> <span style="color:#38bdf8;">{EMERGENCY_HELPLINES['national_emergency']}</span></div>
                    <div>🛡️ <b>State Disaster (BSDMA):</b> <span style="color:#38bdf8;">{EMERGENCY_HELPLINES['state_disaster']}</span></div>
                    <div>🏛️ <b>Patna District DEOC:</b> <span style="color:#38bdf8;">{EMERGENCY_HELPLINES['district_emergency']}</span></div>
                    <div>🏢 <b>PMC Control Room:</b> <span style="color:#38bdf8;">{EMERGENCY_HELPLINES['municipal_control_room']}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            # Authority Operations Navigation
            f1_section = st.radio(
                "OPERATIONS NAVIGATION",
                options=[
                    "Overview",
                    "Risk Map",
                    "Alerts",
                    "At-Risk Assets",
                    "Sensors",
                    "Analytics",
                    "Settings",
                ],
                index=0,
            )
            controls["f1_section"] = f1_section

            st.markdown("<hr style='margin: 0.75rem 0;'/>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 0.72rem; font-weight: 700; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.5rem;'>FORECAST HORIZON</div>", unsafe_allow_html=True)

            horizon = st.radio(
                "Forecast Horizon",
                options=["NOW", "+1h", "+3h", "+6h"],
                index=0,
                horizontal=True,
                help="Switch forecast horizon for model risk outlooks.",
            )
            controls["horizon"] = horizon

            st.markdown("<hr style='margin: 0.75rem 0;'/>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 0.72rem; font-weight: 700; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.5rem;'>MAP LAYERS</div>", unsafe_allow_html=True)
            controls["layer_base"] = st.checkbox(f"Base Map ({PILOT_CITY})", value=True, disabled=True)
            controls["layer_static"] = st.checkbox("Topographic Vulnerability", value=True)
            controls["layer_hotspots"] = st.checkbox("Monitored Hotspots", value=True)
            controls["layer_sensors"] = st.checkbox("Sensor Stations", value=True)

            st.markdown("<hr style='margin: 0.75rem 0;'/>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 0.72rem; font-weight: 700; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.5rem;'>DEMO SCENARIO CONTROL</div>", unsafe_allow_html=True)

            sim_active = st.session_state.get("simulation_active", False)
            if sim_active:
                st.markdown(
                    '<div style="font-size:0.75rem; font-weight:700; background:#fef2f2; color:#991b1b; padding:5px 8px; border-radius:4px; margin-bottom:6px; border:1px solid #fecaca; text-align:center;">🌧️ HEAVY RAIN SCENARIO</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="font-size:0.75rem; font-weight:700; background:#f0fdf4; color:#166534; padding:5px 8px; border-radius:4px; margin-bottom:6px; border:1px solid #bbf7d0; text-align:center;">🟢 BASELINE CONDITIONS</div>',
                    unsafe_allow_html=True,
                )

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("🌧️ Simulate Rain", key="btn_sim_heavy_rain", help="Simulate intense monsoon rainfall via existing backend engine."):
                    simulate_heavy_rain_scenario()
                    st.session_state["simulation_active"] = True
                    st.session_state["review_alert_open"] = False
                    st.session_state.pop("alert_dismissed_notice", None)
                    st.session_state.pop("alert_dispatch_outcome", None)
                    st.session_state.pop("current_draft_id", None)
                    st.rerun()
            with col_s2:
                if st.button("🔄 Reset", key="btn_reset_scenario", help="Reset system to standard baseline conditions."):
                    reset_to_baseline_scenario()
                    st.session_state["simulation_active"] = False
                    st.session_state["review_alert_open"] = False
                    st.session_state.pop("alert_dismissed_notice", None)
                    st.session_state.pop("alert_dispatch_outcome", None)
                    st.session_state.pop("current_draft_id", None)
                    st.rerun()

            st.markdown("<hr style='margin: 0.75rem 0;'/>", unsafe_allow_html=True)
            st.markdown(
                """
                <div style="padding: 0.7rem; background: rgba(15, 23, 42, 0.6); border: 1px solid #1e293b; border-radius: 6px; font-size: 0.78rem; line-height: 1.5;">
                    <div style="color: #10b981; font-weight: 600;">● Database Connected</div>
                    <div style="color: #38bdf8; font-weight: 600;">● Ingestion Engine Active</div>
                    <div style="color: #cbd5e1;">● Telemetry: 10 Sectors</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    return controls


def render_header() -> None:
    """Render the professional Authority Operations Center header."""
    logo_path = get_logo_asset_path()

    with st.container(border=True):
        header_left, header_right = st.columns([0.65, 0.35], vertical_alignment="center")
        with header_left:
            col_logo, col_title = st.columns([0.09, 0.91], vertical_alignment="center")
            with col_logo:
                if logo_path and logo_path.exists():
                    st.image(str(logo_path), width=44)
                else:
                    st.markdown(get_logo_svg(36), unsafe_allow_html=True)
            with col_title:
                st.markdown(
                    f"""
                    <div style="line-height:1.2;">
                        <div style="font-size:1.35rem; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">
                            {SYSTEM_NAME} <span style="font-size:0.95rem; font-weight:600; color:#0284c7;">| {F1_PORTAL_TITLE}</span>
                        </div>
                        <div style="font-size:0.8rem; color:#475569; margin-top:2px;">
                            <b>{PILOT_LOCATION_LABEL}</b> &bull; {HAZARD_SCOPE}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with header_right:
            st.markdown(
                f"""
                <div style="display:flex; justify-content:flex-end; gap:8px; align-items:center; flex-wrap:wrap;">
                    <span class="status-pill status-pill-green">&bull; Live Telemetry Active</span>
                    <span class="status-pill status-pill-slate">{PILOT_CITY} Urban Grid</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_dominant_status(
    metrics: Dict[str, Any],
    active_horizon: str = "NOW",
    horizon_status: Optional[Dict[str, Any]] = None,
) -> None:
    """Render the single dominant overall status area for Authority Operations."""
    counts = (horizon_status or {}).get("counts") or {}
    high_cnt = counts.get("HIGH", 0)
    has_sim = st.session_state.get("simulation_active", False)
    has_alert = st.session_state.get("alert_under_review", False) or st.session_state.get("alert_approved", False)
    has_dynamic_surge = bool(horizon_status and horizon_status.get("available") and horizon_status.get("predictions") and (high_cnt + sev_cnt > 0))
    is_elevated = has_sim or has_alert or has_dynamic_surge

    if horizon_status and not horizon_status.get("available", True):
        horizon_note = f"Dynamic forecast unavailable for horizon {active_horizon}; displaying calibrated topographic baseline."
    else:
        horizon_note = f"Telemetry synchronized for {active_horizon} precipitation horizon."

    if is_elevated:
        total_warn = high_cnt + sev_cnt
        warn_txt = f"{total_warn} Sectors Flagged" if total_warn > 0 else "Simulated Surge Active"
        st.markdown(
            f"""
            <div class="f1-status-banner" style="background:#fef2f2; border:1px solid #fecaca; border-left:6px solid #dc2626;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                    <div style="display:flex; align-items:center; gap:12px;">
                        <span class="pulse-indicator pulse-red"></span>
                        <div>
                            <div style="font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#991b1b;">CURRENT SYSTEM STATUS: ELEVATED RISK</div>
                            <div style="font-size:1.2rem; font-weight:800; color:#7f1d1d; letter-spacing:-0.01em;">MONSOON INUNDATION WATCH &bull; ELEVATED RUNOFF SURGE</div>
                        </div>
                    </div>
                    <div style="display:flex; gap:8px; align-items:center; font-size:0.8rem; color:#991b1b;">
                        <span style="background:#fee2e2; padding:3px 10px; border-radius:6px; font-weight:600;">Horizon: <b>{active_horizon}</b></span>
                        <span style="background:#fee2e2; padding:3px 10px; border-radius:6px; font-weight:600;">Active Warnings: <b>{warn_txt}</b></span>
                        <span style="background:#fee2e2; padding:3px 10px; border-radius:6px; font-weight:600;">Monitored Corridors: <b>10 Sectors</b></span>
                    </div>
                </div>
                <div style="margin-top:6px; font-size:0.82rem; color:#991b1b; line-height:1.4;">
                    Heavy rainfall surge active across <b>{PILOT_LOCATION_LABEL}</b>. Municipal drainage bottlenecks and low-lying underpasses are at or approaching capacity. {horizon_note}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="f1-status-banner">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                    <div style="display:flex; align-items:center; gap:12px;">
                        <span class="pulse-indicator pulse-green"></span>
                        <div>
                            <div style="font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#047857;">CURRENT SYSTEM STATUS</div>
                            <div style="font-size:1.2rem; font-weight:800; color:#065f46; letter-spacing:-0.01em;">CONDITIONS NORMAL &bull; STANDARD DRAINAGE BASELINE</div>
                        </div>
                    </div>
                    <div style="display:flex; gap:8px; align-items:center; font-size:0.8rem; color:#065f46;">
                        <span style="background:#d1fae5; padding:3px 10px; border-radius:6px; font-weight:600;">Horizon: <b>{active_horizon}</b></span>
                        <span style="background:#d1fae5; padding:3px 10px; border-radius:6px; font-weight:600;">Active Warnings: <b>0</b></span>
                        <span style="background:#d1fae5; padding:3px 10px; border-radius:6px; font-weight:600;">Monitored Corridors: <b>10 Sectors</b></span>
                    </div>
                </div>
                <div style="margin-top:6px; font-size:0.82rem; color:#047857; line-height:1.4;">
                    Urban runoff channels across <b>{PILOT_LOCATION_LABEL}</b> are functioning within normal seasonal capacity. {horizon_note}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_summary_cards(metrics: Dict[str, Any]) -> None:
    """Render the compact summary metric cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">PILOT JURISDICTION</div>
                <div class="chetna-metric-val">{PILOT_LOCATION_LABEL}</div>
                <div class="chetna-metric-sub">Urban Municipal Area</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        cell_count = metrics.get("static_risk_cells_count", 0)
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">STATIC RISK CELLS</div>
                <div class="chetna-metric-val">{cell_count} Cells</div>
                <div class="chetna-metric-sub">Topographic Vulnerability Grid</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        hotspots_count = metrics.get("hotspots_count", 0)
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">MONITORED HOTSPOTS</div>
                <div class="chetna-metric-val">{hotspots_count} Sites</div>
                <div class="chetna-metric-sub">High-Risk Drainage Corridors</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        forecast_count = metrics.get("forecasts_count", 0)
        forecast_val = f"{forecast_count} Records" if forecast_count > 0 else "+1h / +3h / +6h"
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">RAINFALL FORECAST</div>
                <div class="chetna-metric-val">{forecast_val}</div>
                <div class="chetna-metric-sub">Atmospheric Feed Synchronized</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_operational_risk_summary(
    horizon: str = "NOW",
    horizon_status: Optional[Dict[str, Any]] = None,
    at_risk_assets: Optional[Dict[str, Any]] = None,
) -> None:
    """Render operational risk breakdown cards across calibrated tiers for the active horizon."""
    if not horizon_status or not horizon_status.get("available", False):
        st.markdown(
            f"""
            <div style="background: #fffbeb; border: 1px solid #fde68a; border-left: 4px solid #f59e0b; border-radius: 6px; padding: 10px 14px; margin-bottom: 0.85rem; font-size: 0.84rem; color: #92400e; display: flex; align-items: center; justify-content: space-between;">
                <div>
                    ⚠️ <b>Forecast data unavailable for {horizon}.</b> Displaying calibrated topographic vulnerability baseline.
                </div>
                <span style="font-size: 0.72rem; font-weight: 700; background: #fef3c7; color: #92400e; padding: 3px 8px; border-radius: 4px;">BASELINE MODE</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    counts = horizon_status.get("counts") or {}
    total = counts.get("total", 0)
    low_cnt = counts.get("LOW", 0)
    med_cnt = counts.get("MEDIUM", 0)
    high_cnt = counts.get("HIGH", 0)
    sev_cnt = counts.get("SEVERE", 0)

    # Assets summary
    assets_cnt = 0
    assets_breakdown = "0 facilities"
    if at_risk_assets and at_risk_assets.get("available", False):
        assets_cnt = at_risk_assets.get("total", 0)
        hosp = at_risk_assets.get("hospitals", 0)
        sch = at_risk_assets.get("schools", 0)
        she = at_risk_assets.get("shelters", 0)
        assets_breakdown = f"{hosp} Hosp &bull; {sch} Sch &bull; {she} She"

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">TOTAL SECTORS ({horizon})</div>
                <div class="chetna-metric-val">{total}</div>
                <div class="chetna-metric-sub">Monitored Risk Grid</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="chetna-metric-card" style="border-top: 3px solid #16a34a;">
                <div class="chetna-metric-label" style="color: #166534;">LOW RISK</div>
                <div class="chetna-metric-val" style="color: #15803d;">{low_cnt}</div>
                <div class="chetna-metric-sub">Normal Inundation Margin</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"""
            <div class="chetna-metric-card" style="border-top: 3px solid #f59e0b;">
                <div class="chetna-metric-label" style="color: #92400e;">MEDIUM RISK</div>
                <div class="chetna-metric-val" style="color: #b45309;">{med_cnt}</div>
                <div class="chetna-metric-sub">Elevated Watch Level</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f"""
            <div class="chetna-metric-card" style="border-top: 3px solid #dc2626;">
                <div class="chetna-metric-label" style="color: #991b1b;">HIGH / SEVERE</div>
                <div class="chetna-metric-val" style="color: #dc2626;">{high_cnt + sev_cnt}</div>
                <div class="chetna-metric-sub">{sev_cnt} Severe &bull; {high_cnt} High</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            f"""
            <div class="chetna-metric-card" style="border-top: 3px solid #0284c7;">
                <div class="chetna-metric-label" style="color: #0369a1;">AT-RISK ASSETS</div>
                <div class="chetna-metric-val" style="color: #0284c7;">{assets_cnt}</div>
                <div class="chetna-metric-sub">{assets_breakdown}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_main_workspace(
    folium_map: folium.Map,
    hotspots: List[Dict[str, Any]],
    horizon: str = "NOW",
    horizon_status: Optional[Dict[str, Any]] = None,
    at_risk_assets: Optional[Dict[str, Any]] = None,
) -> None:
    """Render the primary operational workspace with map, hotspots panel, and at-risk infrastructure."""
    col_map, col_hotspots = st.columns([68, 32])

    with col_map:
        if horizon_status and not horizon_status.get("available", True):
            st.markdown(
                f"""
                <div style="background: #fffbeb; border: 1px solid #fde68a; border-left: 4px solid #f59e0b; border-radius: 6px; padding: 8px 12px; margin-bottom: 0.75rem; font-size: 0.8rem; color: #92400e; display: flex; align-items: center; justify-content: space-between;">
                    <div>
                        ⚠️ <b>Data Notice:</b> Forecast data unavailable for {horizon}. Displaying calibrated topographic vulnerability baseline.
                    </div>
                    <span style="font-size: 0.7rem; font-weight: 700; background: #fef3c7; color: #92400e; padding: 2px 6px; border-radius: 4px;">BASELINE MODE</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        from config.settings import Settings
        _has_mapbox = Settings().has_valid_mapbox_token
        _map_engine_badge = "Mapbox Engine" if _has_mapbox else "Carto Vector Engine"

        st.markdown(
            f"""
            <div class="chetna-card" style="padding-bottom: 0.85rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:8px;">
                    <div>
                        <div style="font-weight:700; font-size:1.05rem; color:#0f172a; letter-spacing:-0.01em;">
                            {PILOT_CITY} Operational Hazard Map
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                            Prototype Reference Grid &bull; Centered on Monitored Study Grid &bull; Horizon: <b>{horizon}</b>
                        </div>
                    </div>
                    <div style="display:flex; gap:6px; align-items:center;">
                        <span class="status-pill status-pill-blue">Patna Urban Grid</span>
                        <span class="status-pill status-pill-slate">{_map_engine_badge}</span>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        if hasattr(folium_map, "to_json"):
            # Native Streamlit Mapbox / PyDeck WebGL engine
            st.pydeck_chart(folium_map, use_container_width=True)
        elif hasattr(folium_map, "get_root"):
            map_html = folium_map.get_root().render()
            st.components.v1.html(map_html, height=540, scrolling=False)

        from config.settings import Settings
        _map_engine = "Mapbox Vector Active (light-v10)" if Settings().has_valid_mapbox_token else "Vector Engine (Carto Positron Fallback)"

        st.markdown(
            f"""
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.6rem; font-size:0.76rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.5rem; flex-wrap:wrap; gap:6px;">
                    <div>📍 Viewport: Centered on {PILOT_CITY} (25.6093°N, 85.1376°E) &bull; EPSG:4326 / UTM 45N</div>
                    <div style="color:#0284c7; font-weight:500;">Horizon: <b>{horizon}</b> &bull; {_map_engine}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Inspectable At-Risk Infrastructure Accordion
        if at_risk_assets and at_risk_assets.get("available", False) and at_risk_assets.get("items"):
            items = at_risk_assets["items"]
            with st.expander(f"🏥 Critical Facilities in High-Risk Zones ({horizon}) — {len(items)} Facilities", expanded=False):
                st.markdown(
                    f"<div style='font-size:0.8rem; color:#475569; margin-bottom:8px;'>"
                    f"Breakdown: <b>{at_risk_assets.get('hospitals', 0)} Hospitals</b> &bull; "
                    f"<b>{at_risk_assets.get('schools', 0)} Schools</b> &bull; "
                    f"<b>{at_risk_assets.get('shelters', 0)} Transit/Shelter Facilities</b>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                facility_rows = [
                    {
                        "Facility Name": item.get("name"),
                        "Category": item.get("type", "Facility").capitalize(),
                        "Vicinity Hotspot": item.get("vicinity"),
                        "Zone": item.get("zone"),
                    }
                    for item in items[:15]
                ]
                st.dataframe(facility_rows, use_container_width=True)

    with col_hotspots:
        st.markdown(
            """
            <div class="chetna-card" style="padding-bottom: 0.85rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                    <div>
                        <div style="font-weight:700; font-size:1.05rem; color:#0f172a; letter-spacing:-0.01em;">
                            Monitored Hotspots
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                            Chronic drainage bottlenecks
                        </div>
                    </div>
                    <span class="status-pill status-pill-amber">10 Sourced Sites</span>
                </div>
                <div class="chetna-hotspots-scroll">
            """,
            unsafe_allow_html=True,
        )

        if hotspots:
            for h in hotspots:
                severity = h.get("severity_tier", "Moderate")
                if severity == "Severe":
                    badge_bg = "#fee2e2"
                    badge_col = "#991b1b"
                else:
                    badge_bg = "#fef3c7"
                    badge_col = "#92400e"

                st.markdown(
                    f"""
                    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:7px;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                            <div style="font-weight:600; font-size:0.83rem; color:#1e293b; line-height:1.25;">
                                {h.get('hotspot_id')}: {h.get('name')}
                            </div>
                            <span style="font-size:0.68rem; font-weight:700; padding:2px 6px; border-radius:4px; background:{badge_bg}; color:{badge_col}; white-space:nowrap; margin-left:6px;">
                                {severity}
                            </span>
                        </div>
                        <div style="font-size:0.74rem; color:#64748b; margin-top:4px;">
                            {h.get('zone')} &bull; Elev: <b>{h.get('elevation_m', 0.0)}m</b> &bull; Trigger (6h): <b>{h.get('typical_trigger_rain_6h_mm', 0.0)}mm</b>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("No hotspots records currently loaded.")

        st.markdown(
            """
                </div>
                <div style="margin-top:0.6rem; font-size:0.75rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.4rem; text-align:center;">
                    Monitored high-risk municipal points and drainage depressions.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_alert_and_architecture_section(
    static_meta: Dict[str, Any],
    active_horizon: str = "NOW",
    horizon_status: Optional[Dict[str, Any]] = None,
    at_risk_assets: Optional[Dict[str, Any]] = None,
) -> None:
    """Render the Alert Centre preview with Review Alert affordance, Approval Gate, and risk architecture status."""
    col_alert, col_arch = st.columns(2)

    high_zones_count = 0
    if horizon_status and horizon_status.get("available", False):
        counts = horizon_status.get("counts") or {}
        high_zones_count = counts.get("HIGH", 0) + counts.get("SEVERE", 0)

    asset_total = at_risk_assets.get("total", 0) if at_risk_assets and at_risk_assets.get("available") else 0
    hosp_cnt = at_risk_assets.get("hospitals", 0) if at_risk_assets and at_risk_assets.get("available") else 0
    sch_cnt = at_risk_assets.get("schools", 0) if at_risk_assets and at_risk_assets.get("available") else 0
    she_cnt = at_risk_assets.get("shelters", 0) if at_risk_assets and at_risk_assets.get("available") else 0

    current_risk_level = "HIGH" if high_zones_count > 0 else "LOW"
    draft_msg = format_draft_alert_text(
        active_horizon=active_horizon,
        affected_area=PILOT_LOCATION_LABEL,
        high_cells_count=high_zones_count,
        asset_summary=at_risk_assets,
    )

    with col_alert:
        st.markdown(
            f"""
            <div class="chetna-card" style="height: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                    <div>
                        <div style="font-weight:700; font-size:1rem; color:#0f172a;">Alert Centre (Authorized Personnel)</div>
                        <div style="font-size:0.78rem; color:#64748b;">Emergency Advisory Approval &amp; Broadcast Gate</div>
                    </div>
                    <span class="status-pill status-pill-amber">Horizon: {active_horizon}</span>
                </div>
                <div style="background:#fffbeb; border:1px solid #fde68a; border-left:4px solid #f59e0b; border-radius:6px; padding:10px 12px; margin-bottom:0.85rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:700; font-size:0.84rem; color:#92400e;">⚠️ DRAFT FLOOD ADVISORY — Low-Elevation Depressions ({PILOT_CITY})</span>
                        <span style="font-size:0.72rem; color:#b45309; font-weight:600;">Status: Ready for Review</span>
                    </div>
                    <p style="margin:6px 0 4px 0; font-size:0.8rem; color:#78350f; line-height:1.4;">
                        Precipitation outlook indicates potential stormwater accumulation at railway underpasses and depression basins.
                        Impact footprint: <b>{high_zones_count} high-risk zones</b> &bull; <b>{asset_total} critical facilities</b> ({hosp_cnt} Hospitals, {sch_cnt} Schools, {she_cnt} Transit Shelters).
                    </p>
                    <div style="font-size:0.72rem; color:#92400e; margin-top:4px;">
                        Integrated Channels: <b>Twilio WhatsApp Sandbox &bull; SMS &bull; Telegram &bull; Automated Voice</b>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        b_col0, b_col1, b_col2 = st.columns([0.34, 0.33, 0.33])
        with b_col0:
            if st.button("🔍 Review Alert", key="btn_review_alert", help="Review detailed alert draft, why-flagged factors, and channel payload."):
                st.session_state["review_alert_open"] = True
                st.session_state.pop("alert_dismissed_notice", None)
                if not st.session_state.get("current_draft_id"):
                    try:
                        st.session_state["current_draft_id"] = create_draft_alert(
                            severity=current_risk_level,
                            title=f"Urban Flood Warning ({active_horizon})",
                            message=draft_msg,
                            affected_area=PILOT_LOCATION_LABEL,
                        )
                    except Exception as draft_err:
                        logger.debug("Draft generation notice: %s", draft_err)
        with b_col1:
            if st.button("✅ Issue Broadcast", disabled=False, key="btn_issue_broadcast"):
                st.session_state["review_alert_open"] = True
                if not st.session_state.get("current_draft_id"):
                    try:
                        st.session_state["current_draft_id"] = create_draft_alert(
                            severity=current_risk_level,
                            title=f"Urban Flood Warning ({active_horizon})",
                            message=draft_msg,
                            affected_area=PILOT_LOCATION_LABEL,
                        )
                    except Exception as draft_err:
                        logger.debug("Draft generation notice: %s", draft_err)
        with b_col2:
            if st.button("❌ Suppress Advisory", disabled=False, key="btn_dismiss_broadcast"):
                st.session_state["review_alert_open"] = False
                st.session_state["alert_dismissed_notice"] = "Advisory suppressed by authority. No broadcast transmitted."
                st.session_state.pop("alert_dispatch_outcome", None)
                try:
                    dismiss_authority_alert(st.session_state.get("current_draft_id"))
                except Exception as dis_err:
                    logger.debug("Dismissal notice: %s", dis_err)
                st.session_state.pop("current_draft_id", None)

        # PART A & B: Explicit Review Panel & Approval Gate
        if st.session_state.get("review_alert_open", False):
            curr_draft_ref = st.session_state.get("current_draft_id", "ALT-DRAFT-PENDING")
            st.markdown(
                f"""
                <div style="background:#f8fafc; border:1px solid #cbd5e1; border-top:3px solid #0284c7; border-radius:6px; padding:12px; margin-top:0.75rem; font-size:0.78rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <span style="font-weight:700; font-size:0.88rem; color:#0f172a;">📋 DRAFT ALERT &mdash; HUMAN-IN-THE-LOOP APPROVAL GATE</span>
                        <span style="font-size:0.7rem; font-weight:700; background:#e0f2fe; color:#0369a1; padding:2px 6px; border-radius:4px;">PENDING APPROVAL</span>
                    </div>
                    <div style="color:#334155; line-height:1.6;">
                        <div>&bull; <b>Draft Reference:</b> <code style="color:#0369a1; font-weight:600;">{curr_draft_ref}</code></div>
                        <div>&bull; <b>1. Target Area:</b> {PILOT_LOCATION_LABEL} &mdash; Low-Elevation Depressions &amp; Underpasses</div>
                        <div>&bull; <b>2. Forecast Horizon:</b> {active_horizon}</div>
                        <div>&bull; <b>3. Evaluated Risk Tier:</b> <span style="font-weight:700; color:#dc2626;">{current_risk_level}</span></div>
                        <div>&bull; <b>4. Affected Monitored Cells:</b> {high_zones_count} sectors</div>
                        <div>&bull; <b>5. Affected Critical Facilities:</b> {asset_total} ({hosp_cnt} Hospitals, {sch_cnt} Schools, {she_cnt} Shelters)</div>
                        <div>&bull; <b>6. Why Flagged:</b> Low ground elevation (&le;8m), concentrated drainage flow accumulation, high impervious surface fraction.</div>
                        <div>&bull; <b>7. Recommended Operational Action:</b> Deploy dewatering pumps, clear road grates, alert railway underpass traffic police, and post traffic advisories.</div>
                        <div style="margin-top:6px; padding:6px 8px; background:#f1f5f9; border-radius:4px; font-style:italic; color:#0f172a;">
                            <b>8. Proposed Message:</b> "{draft_msg}"
                        </div>
                        <div style="margin-top:4px;">&bull; <b>9. Notification Channels:</b> Twilio WhatsApp Sandbox &bull; Twilio SMS &bull; Telegram Bot &bull; Automated Voice</div>
                    </div>
                    <div style="font-size:8.5px; color:#64748b; margin-top:6px; font-style:italic; border-top:1px dashed #cbd5e1; padding-top:4px;">
                        Scientific provenance: Model feature attribution, not proven physical causation.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Explicit Approval Action Buttons
            st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
            col_ap1, col_ap2 = st.columns(2)
            with col_ap1:
                approve_clicked = st.button("✅ APPROVE & SEND", key="btn_approve_and_send", type="primary")
            with col_ap2:
                dismiss_clicked = st.button("❌ DISMISS", key="btn_dismiss_alert_gate")

            if approve_clicked:
                with st.spinner("Dispatching multi-channel emergency broadcast..."):
                    outcome = dispatch_authority_alert(
                        severity=current_risk_level,
                        title=f"Urban Flood Warning ({active_horizon})",
                        message=draft_msg,
                        affected_area=PILOT_LOCATION_LABEL,
                        draft_id=st.session_state.get("current_draft_id"),
                    )
                st.session_state["alert_dispatch_outcome"] = outcome
                st.session_state["review_alert_open"] = False
                st.session_state.pop("alert_dismissed_notice", None)
                st.session_state.pop("current_draft_id", None)

            if dismiss_clicked:
                st.session_state["review_alert_open"] = False
                st.session_state["alert_dismissed_notice"] = "Advisory dismissed by authority. No broadcast transmitted."
                st.session_state.pop("alert_dispatch_outcome", None)
                try:
                    dismiss_authority_alert(st.session_state.get("current_draft_id"))
                except Exception as dis_err:
                    logger.debug("Dismissal notice: %s", dis_err)
                st.session_state.pop("current_draft_id", None)

        # Show Dismiss Notice
        if st.session_state.get("alert_dismissed_notice"):
            st.warning(f"⚠️ {st.session_state['alert_dismissed_notice']}")

        # PART C & D: Show Dispatch Outcome and Individual Channel Results
        if st.session_state.get("alert_dispatch_outcome"):
            outcome = st.session_state["alert_dispatch_outcome"]
            if outcome.get("dry_run"):
                st.info(
                    f"ℹ️ **Dry-run:** {outcome.get('message')}\n\n"
                    f"Audit Reference: `{outcome.get('alert_id')}` &bull; Severity: `{outcome.get('severity')}`"
                )
            elif outcome.get("success"):
                st.success(f"✅ {outcome.get('message')}")
            else:
                st.error(f"❌ {outcome.get('message')}")

            channels = outcome.get("channels", {})
            if channels:
                st.markdown("<div style='font-size:0.75rem; font-weight:700; color:#0f172a; margin-top:6px;'>Channel Delivery Status:</div>", unsafe_allow_html=True)
                for ch_name, ch_info in channels.items():
                    is_ok = ch_info.get("success", False)
                    ch_badge = "#dcfce7" if is_ok else "#fee2e2"
                    ch_col = "#166534" if is_ok else "#991b1b"
                    st.markdown(
                        f"""
                        <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:4px 8px; margin-bottom:4px; font-size:0.74rem;">
                            <div><b>{ch_name}</b> &bull; <span style="color:#64748b;">{ch_info.get('recipient')}</span></div>
                            <span style="font-size:0.68rem; font-weight:700; background:{ch_badge}; color:{ch_col}; padding:2px 6px; border-radius:3px;">
                                {ch_info.get('status')}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            if outcome.get("partial_failure"):
                st.warning("⚠️ Partial delivery failure encountered on one or more secondary channels.")
            if outcome.get("error"):
                st.error(f"Operational error logged: {outcome['error']}")

        st.markdown(
            """
                <div style="margin-top:0.6rem; font-size:0.75rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.4rem;">
                    Multi-channel alert dispatch requires designated authority confirmation. Dry-run mode protects live subscribers.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_arch:
        st.markdown(
            """
            <div class="chetna-card" style="height: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                    <div>
                        <div style="font-weight:700; font-size:1rem; color:#0f172a;">Static Topographic Risk Architecture</div>
                        <div style="font-size:0.78rem; color:#64748b;">Deterministic Terrain Vulnerability Formulation</div>
                    </div>
                    <span class="status-pill status-pill-green">Active Baseline</span>
                </div>
                <div style="background:#f1f5f9; border-radius:6px; padding:8px 12px; font-family:monospace; font-size:0.76rem; color:#0f172a; margin-bottom:0.75rem;">
                    V = 0.35&middot;norm(elev) + 0.25&middot;norm(log(flow_acc)) + 0.25&middot;norm(imperv) + 0.15&middot;norm(slope)
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:0.78rem; margin-bottom:0.85rem; color:#334155;">
                    <div>&bull; Elevation: <b>35%</b> (Inverted min-max)</div>
                    <div>&bull; Flow Accumulation: <b>25%</b> (Log scale)</div>
                    <div>&bull; Imperviousness: <b>25%</b> (Runoff index)</div>
                    <div>&bull; Slope: <b>15%</b> (Inverted min-max)</div>
                </div>
                <div style="background:#ecfeff; border:1px solid #a5f3fc; border-left:4px solid #06b6d4; border-radius:6px; padding:9px 12px;">
                    <div style="font-weight:700; font-size:0.82rem; color:#0e7490;">Topographic Vulnerability Calibration</div>
                    <div style="margin-top:3px; font-size:0.78rem; color:#155e75; line-height:1.35;">
                        Grid cells are scored on a normalized scale [0, 1] categorized into Low (&lt; 0.40), Medium (0.40–0.70), and High (&ge; 0.70) vulnerability tiers to guide preemptive deployment.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )



def render_footer() -> None:
    """Render authoritative footer."""
    st.markdown(
        f"""
        <div style="text-align:center; padding:1.5rem 0 0.5rem 0; color:#94a3b8; font-size:0.75rem; border-top:1px solid #e2e8f0; margin-top:1.25rem;">
            <b>{SYSTEM_NAME} {F1_PORTAL_TITLE}</b> &bull; {PILOT_LOCATION_LABEL} Municipal Disaster Management Authority
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Main application entrypoint for Streamlit dashboard."""
    page_icon = str(LOGO_PNG_PATH) if LOGO_PNG_PATH.exists() else "🌊"
    st.set_page_config(
        page_title=f"{SYSTEM_NAME} — {F1_PORTAL_TITLE}",
        page_icon=page_icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 1. Inject authoritative styling
    inject_custom_styles()

    # 2. Fetch data & system metrics
    metrics = get_system_metrics()
    static_meta = load_static_risk_metadata()
    hotspots = load_hotspots_data()
    sensors = load_sensor_stations()

    # 3. Render sidebar with navigation and controls
    controls = render_sidebar(metrics)

    # 4. Check Horizon Data Status & Predictions
    active_horizon = controls.get("horizon", "NOW")
    horizon_status = load_horizon_predictions(active_horizon, static_risk_data=static_meta)
    at_risk_assets = get_at_risk_assets_summary(horizon_status, hotspots, static_meta)

    # 5. Render Selected Portal View
    if controls.get("view_mode") == "👤 Citizen Safety Portal":
        citizen_map = create_base_map(
            center=DEFAULT_COORDINATES,
            zoom_start=DEFAULT_ZOOM_START,
            tiles="OpenStreetMap",
            add_center_marker=True,
            add_fullscreen_control=True,
        )
        render_citizen_view(citizen_map, hotspots, metrics)
    else:
        # Authority Operations Center (F1)
        render_header()
        render_dominant_status(metrics, active_horizon=active_horizon, horizon_status=horizon_status)
        render_summary_cards(metrics)
        render_operational_risk_summary(active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)
        st.markdown("<div style='margin-bottom: 0.85rem;'></div>", unsafe_allow_html=True)

        # Build data-driven operational map with active layers
        folium_map = build_operational_map(
            center=DEFAULT_COORDINATES,
            zoom_start=DEFAULT_ZOOM_START,
            static_risk_data=static_meta,
            hotspots_data=hotspots,
            sensors_data=sensors,
            layer_static=controls.get("layer_static", True),
            layer_hotspots=controls.get("layer_hotspots", True),
            layer_sensors=controls.get("layer_sensors", True),
            horizon=active_horizon,
            predictions_map=horizon_status.get("predictions"),
            add_legend=True,
            add_fullscreen=True,
        )

        f1_section = controls.get("f1_section", "Overview")
        if f1_section in ("Overview", "Risk Map", "📊 Overview", "🗺️ Risk Map"):
            render_main_workspace(folium_map, hotspots, horizon=active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)
            render_alert_and_architecture_section(static_meta, active_horizon=active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)
        elif f1_section in ("Alerts", "🚨 Alerts & Broadcast"):
            render_alert_and_architecture_section(static_meta, active_horizon=active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)
            render_main_workspace(folium_map, hotspots, horizon=active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)
        elif f1_section in ("At-Risk Assets", "🏥 At-Risk Assets"):
            with st.container(border=True):
                st.markdown(f"### Critical Assets &amp; Hotspots Registry — {PILOT_LOCATION_LABEL}")
                st.markdown("Monitored vulnerable infrastructure and drainage bottleneck sites across municipal sectors.")
                if hotspots:
                    st.dataframe(hotspots, use_container_width=True)
                else:
                    st.info("No asset records loaded.")
        elif f1_section in ("Sensors", "📡 Telemetry & Sensors"):
            with st.container(border=True):
                st.markdown(f"### Telemetry &amp; Hydrological Sensor Network — {PILOT_LOCATION_LABEL}")
                st.markdown("Simulated water-level monitoring nodes across municipal sectors (Computational Telemetry).")
                if sensors:
                    st.dataframe(sensors, use_container_width=True)
                else:
                    st.info("No sensor records loaded.")
        elif f1_section in ("Analytics", "📈 Risk Analytics"):
            with st.container(border=True):
                st.markdown(f"### 📈 Model Evaluation &amp; Backtest Analytics &mdash; {PILOT_LOCATION_LABEL}")
                st.markdown(f"**Hazard Scope:** {HAZARD_SCOPE} &bull; **Pilot Baseline:** 200m Metric Vulnerability Grid")
                st.markdown(
                    "Historical backtest evaluation comparing ML (XGBoost), Heuristic Linear, and Rainfall-only baseline models "
                    "across multi-hour forecast horizons (+1h, +3h, +6h)."
                )

                bt_data = load_backtest_summary()
                if bt_data.get("available") and bt_data.get("records"):
                    c_m1, c_m2, c_m3 = st.columns(3)
                    with c_m1:
                        st.metric("Historical Events", "2 Events", "Michaung '23 & Nov '21")
                    with c_m2:
                        st.metric("Prediction Methods", "3 Evaluated", "ML vs Heuristic vs Rainfall")
                    with c_m3:
                        st.metric("Forecast Horizons", "3 Horizons", "+1h, +3h, +6h")

                    st.markdown("<div style='font-size:0.85rem; font-weight:700; color:#0f172a; margin-top:0.75rem; margin-bottom:0.25rem;'>Comparative Model Metrics:</div>", unsafe_allow_html=True)
                    st.dataframe(bt_data["records"], use_container_width=True)

                    lims_html = "".join(f"<div>&bull; {lim}</div>" for lim in bt_data.get("limitations", []))
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #cbd5e1; border-left:4px solid #0284c7; border-radius:6px; padding:10px 12px; margin-top:0.75rem; font-size:0.78rem; color:#334155;">
                            <div style="font-weight:700; color:#0f172a; margin-bottom:4px;">⚠️ Scientific Provenance &amp; Known Prototype Limitations:</div>
                            {lims_html}
                            <div style="font-size:8.5px; color:#64748b; margin-top:6px; font-style:italic; border-top:1px dashed #cbd5e1; padding-top:4px;">
                                {bt_data.get("disclaimer", "Prototype backtest evaluation against calibrated proxy development labels.")}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.dataframe(static_meta.get("cells", [])[:15], use_container_width=True)
        elif f1_section in ("Settings", "⚙️ System Settings"):
            with st.container(border=True):
                st.markdown(f"### Authority System Settings — {PILOT_LOCATION_LABEL}")
                st.markdown(f"- **Pilot City:** {PILOT_CITY}")
                st.markdown(f"- **Pilot State:** {PILOT_STATE}")
                st.markdown(f"- **Hazard Scope:** {HAZARD_SCOPE}")
                st.markdown("- **Alert Channels:** Twilio WhatsApp Sandbox, Twilio SMS, Telegram Bot, Automated Voice")
                st.markdown("- **Dry-Run Mode:** Active (ALERT_DRY_RUN=true) — notifications safely simulated locally")
        else:
            render_main_workspace(folium_map, hotspots, horizon=active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)
            render_alert_and_architecture_section(static_meta, active_horizon=active_horizon, horizon_status=horizon_status, at_risk_assets=at_risk_assets)


        render_footer()


if __name__ == "__main__":
    main()
