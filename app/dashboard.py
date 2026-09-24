"""Chetna: Neighborhood-Scale Flood Early Warning Prototype.

F1 Day 1 UI/UX: Refined emergency-management dashboard, dark navy sidebar,
crisp light workspace, custom Chetna SVG branding, compact summary cards,
Folium Leaflet base map with fullscreen control centered on Chennai,
monitored hotspots panel, human-in-the-loop alert centre preview, and
static risk architecture readiness.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
from folium import plugins
import streamlit as st

logger = logging.getLogger(__name__)

# Constants and Defaults
DEFAULT_CITY: str = "Chennai, India"
DEFAULT_COORDINATES: Tuple[float, float] = (13.0827, 80.2707)  # Chennai center (lat, lon)
DEFAULT_ZOOM_START: int = 11

DEFAULT_DB_PATH: Path = Path("data/chetna.db")
DEFAULT_STATIC_RISK_PATH: Path = Path("data/m1/static_risk_scores.json")
DEFAULT_HOTSPOTS_PATH: Path = Path("data/m1/hotspots.json")

ASSETS_DIR: Path = Path(__file__).resolve().parent / "assets"
LOGO_SVG_PATH: Path = ASSETS_DIR / "chetna_logo.svg"
LOGO_PNG_PATH: Path = ASSETS_DIR / "chetna_logo.png"


def get_logo_asset_path(prefer_svg: bool = False) -> Optional[Path]:
    """Return verified path to Chetna logo asset.

    Parameters
    ----------
    prefer_svg : bool
        If True and SVG exists, return SVG path; otherwise return PNG path.
        Defaults to False to ensure reliable cross-browser rendering via PNG.

    Returns
    -------
    Path or None
        Path to existing logo asset, or None if neither exists.
    """
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
    """Create and return the base Folium map centered on the pilot city.

    Parameters
    ----------
    center : tuple of float
        (latitude, longitude) center coordinates. Defaults to Chennai (13.0827, 80.2707).
    zoom_start : int
        Initial zoom level for the map. Defaults to 11.
    tiles : str
        Base map tile provider. Defaults to "OpenStreetMap".
    add_center_marker : bool
        Whether to add an informative marker for the pilot city center.
    add_fullscreen_control : bool
        Whether to enable native Leaflet fullscreen control button.

    Returns
    -------
    folium.Map
        Configured Folium Map instance ready for embedding or adding layers.
    """
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
            "<div style='color:#0284c7; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>Chetna Pilot Study Area</div>"
            "<div style='font-size:14px; font-weight:700; color:#0f172a; margin:2px 0 6px 0;'>Chennai Metropolitan Area</div>"
            "<div style='font-size:12px; color:#475569; line-height:1.4;'>"
            f"<b>Coordinates:</b> {center[0]:.4f}&deg; N, {center[1]:.4f}&deg; E<br/>"
            "<b>Resolution:</b> ~200 m metric grid<br/>"
            "<b>Status:</b> F1 Day 1 Base Map Viewport"
            "</div>"
            "</div>"
        )
        folium.Marker(
            location=[center[0], center[1]],
            tooltip="Chetna Pilot Center: Chennai",
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(base_map)

    return base_map


def load_static_risk_metadata(
    path: Path | str = DEFAULT_STATIC_RISK_PATH,
) -> Dict[str, Any]:
    """Load metadata from the M1 Day 2 static vulnerability calculation.

    Returns summary information (cell count, formula, feature weights)
    to keep the architecture ready for F1 Day 2 static layer rendering.
    """
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
    """Load known waterlogging hotspots identified during M1 Day 1.

    Returns a list of hotspot records or an empty list if not found.
    """
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
    """Collect current subsystem metrics across B1, M1, and database."""
    metrics: Dict[str, Any] = {
        "pilot_city": DEFAULT_CITY,
        "coordinates": DEFAULT_COORDINATES,
        "db_connected": False,
        "forecasts_count": 0,
        "latest_forecast_time": None,
        "db_cells_count": 0,
        "static_risk_cells_count": 0,
        "hotspots_count": 0,
        "static_risk_ready": False,
    }

    # Query SQLite database if present
    target_db = Path(db_path)
    if target_db.exists():
        try:
            conn = sqlite3.connect(str(target_db))
            cursor = conn.cursor()
            metrics["db_connected"] = True

            # Check forecasts table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='forecasts'")
            if cursor.fetchone():
                cursor.execute("SELECT count(*), max(timestamp) FROM forecasts")
                row = cursor.fetchone()
                if row:
                    metrics["forecasts_count"] = row[0] or 0
                    metrics["latest_forecast_time"] = row[1]

            # Check cells table (from static risk)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cells'")
            if cursor.fetchone():
                cursor.execute("SELECT count(*) FROM cells")
                row = cursor.fetchone()
                if row:
                    metrics["db_cells_count"] = row[0] or 0

            conn.close()
        except Exception as e:
            logger.warning("Could not query database at %s: %s", target_db, e)

    # Load static risk file count
    static_meta = load_static_risk_metadata(static_risk_path)
    metrics["static_risk_cells_count"] = static_meta.get("cell_count", 0)
    metrics["static_risk_ready"] = static_meta.get("loaded", False)

    # Load hotspots count
    hotspots = load_hotspots_data(hotspots_path)
    metrics["hotspots_count"] = len(hotspots)

    return metrics


# ---------------------------------------------------------------------------
# Streamlit UI Rendering Functions
# ---------------------------------------------------------------------------

def inject_custom_styles() -> None:
    """Inject emergency ops center CSS styling."""
    st.markdown(
        """
        <style>
        /* Global Typography & Light Workspace Background */
        .stApp {
            background-color: #f8fafc !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            color: #0f172a;
        }

        /* Hide Streamlit default header and footer chrome */
        #MainMenu, footer {
            visibility: hidden !important;
        }
        header[data-testid="stHeader"] {
            background-color: transparent !important;
        }

        /* Adjust main container padding */
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
            letter-spacing: -0.01em;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
            color: #f1f5f9 !important;
            font-weight: 600 !important;
            font-size: 0.82rem !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
            margin-bottom: 0.35rem !important;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] label {
            color: #e2e8f0 !important;
            font-size: 0.84rem !important;
        }
        [data-testid="stSidebar"] label[data-baseweb="checkbox"] {
            color: #e2e8f0 !important;
            font-size: 0.84rem !important;
        }
        [data-testid="stSidebar"] hr {
            border-color: #1e293b !important;
            margin: 1rem 0 !important;
        }
        [data-testid="stSidebar"] .stCaption {
            color: #94a3b8 !important;
        }

        /* Custom Chetna Card Containers & Border Wrappers */
        .chetna-card, [data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 10px !important;
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.04), 0 1px 2px -1px rgba(0, 0, 0, 0.02) !important;
        }

        /* Ensure stImage in header and sidebar renders clearly and is not clipped */
        [data-testid="stImage"] {
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
        }
        [data-testid="stImage"] img {
            border-radius: 4px !important;
            object-fit: contain !important;
            max-width: 100% !important;
            height: auto !important;
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
            font-size: 1.35rem;
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

        /* Status Pills */
        .chetna-pill {
            display: inline-flex;
            align-items: center;
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.74rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        .chetna-pill-blue {
            background: #e0f2fe;
            color: #0369a1;
            border: 1px solid #bae6fd;
        }
        .chetna-pill-teal {
            background: #ccfbf1;
            color: #0f766e;
            border: 1px solid #99f6e4;
        }
        .chetna-pill-slate {
            background: #f1f5f9;
            color: #475569;
            border: 1px solid #e2e8f0;
        }
        .chetna-pill-amber {
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #fde68a;
        }

        /* Map Embed Container */
        .chetna-map-container {
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #e2e8f0;
        }

        /* Hotspot Scroll Container */
        .chetna-hotspots-scroll {
            max-height: 505px;
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

        /* Buttons Styling */
        .stButton button {
            border-radius: 6px !important;
            font-weight: 600 !important;
            font-size: 0.85rem !important;
            transition: all 0.15s ease !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Render the dark navy operations sidebar with Chetna logo and controls."""
    controls: Dict[str, Any] = {}
    logo_path = get_logo_asset_path()

    with st.sidebar:
        # 1. Brand Logo & Title Header
        if logo_path and logo_path.exists():
            col_logo, col_title = st.sidebar.columns([0.22, 0.78], vertical_alignment="center")
            with col_logo:
                st.image(str(logo_path), width=36)
            with col_title:
                st.markdown(
                    """
                    <div style="line-height:1.15; padding-top:2px;">
                        <div style="color:#ffffff; font-size:1.15rem; font-weight:800; letter-spacing:1.5px; margin:0;">CHETNA</div>
                        <div style="color:#38bdf8; font-size:0.72rem; font-weight:600; letter-spacing:0.5px; margin:0;">FLOOD EARLY WARNING</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.sidebar.markdown(
                """
                <div style="line-height:1.15; padding-bottom:0.5rem;">
                    <div style="color:#ffffff; font-size:1.2rem; font-weight:800; letter-spacing:1.5px;">CHETNA</div>
                    <div style="color:#38bdf8; font-size:0.72rem; font-weight:600; letter-spacing:0.5px;">FLOOD EARLY WARNING</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.sidebar.markdown("<hr style='margin: 0.85rem 0 1rem 0; border-color: #1e293b;'/>", unsafe_allow_html=True)

        # 2. Sleek Minimalist Navigation
        st.markdown(
            """
            <div style="margin-bottom: 1.25rem;">
                <div style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-bottom: 0.5rem;">NAVIGATION</div>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                    <div style="display: flex; align-items: center; gap: 10px; padding: 7px 12px; background: rgba(14, 165, 233, 0.15); border-left: 3px solid #0ea5e9; border-radius: 4px; color: #ffffff; font-weight: 600; font-size: 0.84rem;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                        Dashboard
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px; padding: 7px 12px; color: #94a3b8; font-size: 0.84rem; border-radius: 4px;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>
                        Map View
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px; padding: 7px 12px; color: #94a3b8; font-size: 0.84rem; border-radius: 4px;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                        Risk &amp; Alerts
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px; padding: 7px 12px; color: #94a3b8; font-size: 0.84rem; border-radius: 4px;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
                        Reports
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px; padding: 7px 12px; color: #94a3b8; font-size: 0.84rem; border-radius: 4px;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                        Settings
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<hr style='margin: 0.5rem 0 0.85rem 0;'/>", unsafe_allow_html=True)
        st.markdown("<div style='font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-bottom: 0.6rem;'>CONTROL CENTER</div>", unsafe_allow_html=True)

        # 3. Forecast Horizon Controls (Placeholders for Day 3)
        horizon = st.radio(
            "Forecast Horizon",
            options=["Live / Current", "+1 Hour", "+3 Hours", "+6 Hours"],
            index=0,
            help="Dynamic forecast horizon selector. Model predictions activate in Day 3.",
        )
        controls["horizon"] = horizon
        st.caption("Ingestion engine collects +1h, +3h, and +6h rainfall horizons (B1).")

        st.markdown("<hr style='margin: 0.75rem 0;'/>", unsafe_allow_html=True)

        # 4. Map Layers Toggle Placeholders
        st.markdown("<div style='font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #f1f5f9; margin-bottom: 0.35rem;'>Map Layers</div>", unsafe_allow_html=True)
        st.checkbox("Base Map (Chennai)", value=True, disabled=True, help="Active base OpenStreetMap layer.")
        controls["show_static_risk"] = st.checkbox(
            "Static Vulnerability",
            value=False,
            disabled=True,
            help="Deterministic terrain vulnerability layer (scheduled for F1 Day 2).",
        )
        controls["show_hotspots"] = st.checkbox(
            "Waterlogging Hotspots",
            value=False,
            disabled=True,
            help="Documented flood-prone locations (scheduled for F1/F2 Day 2).",
        )
        controls["show_sensors"] = st.checkbox(
            "Virtual Sensors",
            value=False,
            disabled=True,
            help="Simulated water-level sensor network (scheduled for B2 Day 2).",
        )

        # 5. System Status Box
        st.markdown(
            """
            <div style="margin-top: 1.1rem; padding: 0.85rem 0.95rem; background: rgba(15, 23, 42, 0.6); border: 1px solid #1e293b; border-radius: 8px;">
                <div style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; margin-bottom: 0.6rem;">SYSTEM STATUS</div>
                <div style="display: flex; flex-direction: column; gap: 7px; font-size: 0.8rem;">
                    <div style="display: flex; align-items: center; gap: 8px; color: #e2e8f0;">
                        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 6px rgba(16,185,129,0.5);"></span>
                        <span>Data Connected</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px; color: #e2e8f0;">
                        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 6px rgba(16,185,129,0.5);"></span>
                        <span>Forecast Available</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px; color: #94a3b8;">
                        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #f59e0b;"></span>
                        <span>Sensors: Simulated / Standby</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 6. Prototype Notice
        st.markdown(
            """
            <div style="margin-top: 1rem; text-align: center;">
                <span class="chetna-pill chetna-pill-blue" style="font-size:0.7rem;">Prototype &bull; F1 Day 1</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return controls


def render_header() -> None:
    """Render the modern professional header card with visible Chetna logo."""
    logo_path = get_logo_asset_path()

    with st.container(border=True):
        header_left, header_right = st.columns([0.65, 0.35], vertical_alignment="center")
        with header_left:
            col_logo, col_title = st.columns([0.10, 0.90], vertical_alignment="center")
            with col_logo:
                if logo_path and logo_path.exists():
                    st.image(str(logo_path), width=48)
            with col_title:
                st.markdown(
                    """
                    <div style="line-height:1.2;">
                        <div style="font-size:1.35rem; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">
                            Chetna <span style="font-size:0.92rem; font-weight:500; color:#64748b;">| Flood Early Warning System</span>
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                            Neighborhood-Scale Flood Monitoring Prototype &bull; Pilot Study: <b>Chennai, India</b>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with header_right:
            st.markdown(
                """
                <div style="display:flex; justify-content:flex-end; gap:8px; align-items:center; flex-wrap:wrap;">
                    <span class="chetna-pill chetna-pill-blue">Prototype &bull; F1 Day 1</span>
                    <span class="chetna-pill chetna-pill-slate">Pilot: Chennai (13.08&deg;N, 80.27&deg;E)</span>
                    <span class="chetna-pill chetna-pill-teal">&bull; Data Connected</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_summary_cards(metrics: Dict[str, Any]) -> None:
    """Render the 4 compact summary metric cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            """
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">PILOT CITY</div>
                <div class="chetna-metric-val">Chennai, India</div>
                <div class="chetna-metric-sub">Metropolitan Study Area</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        cell_count = metrics.get("static_risk_cells_count", 0)
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">STATIC RISK GRID</div>
                <div class="chetna-metric-val">{cell_count} Cells</div>
                <div class="chetna-metric-sub">M1 Day 2 Ready &bull; Overlay in Day 2</div>
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
                <div class="chetna-metric-sub">GCC Chronic Flood Points</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        forecast_count = metrics.get("forecasts_count", 0)
        forecast_sub = "+1h, +3h, +6h SQLite Cached (B1)"
        forecast_val = f"{forecast_count} Records" if forecast_count > 0 else "+1h / +3h / +6h"
        st.markdown(
            f"""
            <div class="chetna-metric-card">
                <div class="chetna-metric-label">RAINFALL FORECASTS</div>
                <div class="chetna-metric-val">{forecast_val}</div>
                <div class="chetna-metric-sub">{forecast_sub}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_main_workspace(
    folium_map: folium.Map,
    hotspots: List[Dict[str, Any]],
) -> None:
    """Render the primary workspace with large map card and monitored hotspots panel."""
    col_map, col_hotspots = st.columns([68, 32])

    with col_map:
        # Wrap map in a clean card container
        st.markdown(
            """
            <div class="chetna-card" style="padding-bottom: 0.85rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:8px;">
                    <div>
                        <div style="font-weight:700; font-size:1.05rem; color:#0f172a; letter-spacing:-0.01em;">
                            Chennai Pilot Operational Map
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                            Leaflet / OSM viewport centered on Chennai (13.0827&deg; N, 80.2707&deg; E) &bull; ~200 m metric grid ready
                        </div>
                    </div>
                    <div style="display:flex; gap:6px; align-items:center;">
                        <span class="chetna-pill chetna-pill-blue">Base Map Only &bull; F1 Day 1</span>
                        <span class="chetna-pill chetna-pill-slate">Fullscreen Enabled</span>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        # Render Folium map HTML inside the card
        map_html = folium_map.get_root().render()
        st.components.v1.html(map_html, height=560, scrolling=False)

        st.markdown(
            """
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.6rem; font-size:0.76rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.5rem;">
                    <div>📍 Fixed Pilot: Chennai Metropolitan Area (WGS84)</div>
                    <div style="color:#0284c7; font-weight:500;">Static risk color-coded cells will overlay in F1 Day 2</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_hotspots:
        # Monitored Hotspots Panel
        st.markdown(
            """
            <div class="chetna-card" style="padding-bottom: 0.85rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                    <div>
                        <div style="font-weight:700; font-size:1.05rem; color:#0f172a; letter-spacing:-0.01em;">
                            Monitored Hotspots (M1)
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                            10 GCC chronic flood points
                        </div>
                    </div>
                    <span class="chetna-pill chetna-pill-amber">10 Sourced</span>
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
                    Pins &amp; polygon highlights will overlay on map in F1/F2 Day 2.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_alert_and_architecture_section(static_meta: Dict[str, Any]) -> None:
    """Render the Alert Centre preview and M1 static risk architecture status."""
    col_alert, col_arch = st.columns(2)

    with col_alert:
        st.markdown(
            """
            <div class="chetna-card" style="height: 100%;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                    <div>
                        <div style="font-weight:700; font-size:1rem; color:#0f172a;">Alert Centre (Human-in-the-Loop)</div>
                        <div style="font-size:0.78rem; color:#64748b;">Emergency Advisory Dispatch Gate</div>
                    </div>
                    <span class="chetna-pill chetna-pill-amber">Draft Preview</span>
                </div>
                <div style="background:#fffbeb; border:1px solid #fde68a; border-left:4px solid #f59e0b; border-radius:6px; padding:10px 12px; margin-bottom:0.85rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:700; font-size:0.84rem; color:#92400e;">⚠️ DRAFT FLOOD ADVISORY — Zone 13 (Adyar / Velachery)</span>
                        <span style="font-size:0.72rem; color:#b45309; font-weight:600;">Status: Pending Approval</span>
                    </div>
                    <p style="margin:6px 0 4px 0; font-size:0.8rem; color:#78350f; line-height:1.4;">
                        Heavy rainfall anticipated (>60 mm in 6h). Ram Nagar depression and railway underpasses at elevated waterlogging risk. Recommended action: Divert road traffic and utilize Velachery MRTS elevated concourse.
                    </p>
                    <div style="font-size:0.72rem; color:#92400e; margin-top:4px;">
                        Target Channels: <b>Twilio WhatsApp Sandbox / SMS / Telegram</b>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        b_col1, b_col2 = st.columns(2)
        with b_col1:
            st.button("✅ Approve & Dispatch Alert", disabled=True, help="Human approval gate unlocks on Day 4.")
        with b_col2:
            st.button("❌ Dismiss Advisory", disabled=True, help="Advisory suppression unlocks on Day 4.")

        st.markdown(
            """
                <div style="margin-top:0.6rem; font-size:0.75rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.4rem;">
                    🔒 Human approval workflow and alert dispatch will be implemented on Day 4. No messages are sent in Day 1.
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
                        <div style="font-weight:700; font-size:1rem; color:#0f172a;">Static Risk Architecture</div>
                        <div style="font-size:0.78rem; color:#64748b;">M1 Day 2 Deterministic Vulnerability Formula</div>
                    </div>
                    <span class="chetna-pill chetna-pill-teal">M1 Layer Ready</span>
                </div>
                <div style="background:#f1f5f9; border-radius:6px; padding:8px 12px; font-family:monospace; font-size:0.76rem; color:#0f172a; margin-bottom:0.75rem;">
                    V = 0.35&middot;norm(elev) + 0.25&middot;norm(log(flow_acc)) + 0.25&middot;norm(imperv) + 0.15&middot;norm(slope)
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:0.78rem; margin-bottom:0.85rem; color:#334155;">
                    <div>&bull; Elevation: <b>35%</b> (Inverted min-max)</div>
                    <div>&bull; Flow Accumulation: <b>25%</b> (Log scale)</div>
                    <div>&bull; Imperviousness: <b>25%</b> (Runoff)</div>
                    <div>&bull; Slope: <b>15%</b> (Inverted min-max)</div>
                </div>
                <div style="background:#ecfeff; border:1px solid #a5f3fc; border-left:4px solid #06b6d4; border-radius:6px; padding:9px 12px;">
                    <div style="font-weight:700; font-size:0.82rem; color:#0e7490;">🎯 Next Step: F1 Day 2 Milestone</div>
                    <div style="margin-top:3px; font-size:0.78rem; color:#155e75; line-height:1.35;">
                        In F1 Day 2, the 38 scored static risk cells will be rendered directly onto this Folium map with color-coded polygons (Green &lt; 0.40, Yellow 0.40–0.70, Red &ge; 0.70) and interactive layer toggle controls.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_footer() -> None:
    """Render the bottom prototype disclaimer and EY problem statement attribution."""
    st.markdown(
        """
        <div style="text-align:center; padding:1.5rem 0 0.5rem 0; color:#94a3b8; font-size:0.75rem; border-top:1px solid #e2e8f0; margin-top:1.25rem;">
            <b>Chetna Flood Early Warning System</b> &bull; IS-12 Project Prototype &bull; Sponsor: Ernst &amp; Young (EY) &bull; Prototype Stage: F1 Day 1 (Dashboard Skeleton &amp; Base Map)
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Main application entrypoint for Streamlit dashboard."""
    page_icon = str(LOGO_PNG_PATH) if LOGO_PNG_PATH.exists() else "🌊"
    st.set_page_config(
        page_title="Chetna — Flood Early-Warning System",
        page_icon=page_icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 1. Inject emergency ops center styling
    inject_custom_styles()

    # 2. Fetch data & system metrics
    metrics = get_system_metrics()
    static_meta = load_static_risk_metadata()
    hotspots = load_hotspots_data()

    # 3. Render dark navy sidebar with logo, navigation, and controls
    render_sidebar(metrics)

    # 4. Render main workspace header
    render_header()

    # 5. Render summary metric cards
    render_summary_cards(metrics)
    st.markdown("<div style='margin-bottom: 0.85rem;'></div>", unsafe_allow_html=True)

    # 6. Create Folium base map and render main workspace (map + hotspots panel)
    folium_map = create_base_map(
        center=DEFAULT_COORDINATES,
        zoom_start=DEFAULT_ZOOM_START,
        tiles="OpenStreetMap",
        add_center_marker=True,
        add_fullscreen_control=True,
    )
    render_main_workspace(folium_map, hotspots)

    # 7. Render Alert Centre preview & static risk architecture readiness
    render_alert_and_architecture_section(static_meta)

    # 8. Render Footer
    render_footer()


if __name__ == "__main__":
    main()
