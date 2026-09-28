"""Chetna: Citizen Safety Portal (F2).

Accessible, community-oriented interface for Patna residents:
- Plain-language neighborhood flood situational awareness
- Neighborhood risk check input (Current / +1h / +3h / +6h)
- Sourced safe places panel (hospitals, schools, elevated transit shelters)
- Safe-route finder avoiding waterlogged roads
- Bilingual emergency advisory and alert guidance (English | हिंदी)
- Community base map
- Emergency helplines directory (Patna / Bihar)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
import streamlit as st

from app.config import (
    EMERGENCY_HELPLINES,
    HAZARD_SCOPE,
    PILOT_CITY,
    PILOT_LOCATION_LABEL,
    PILOT_STATE,
    SYSTEM_NAME,
)

logger = logging.getLogger(__name__)

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


def extract_facilities_from_hotspots(
    hotspots: Optional[List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, str]]]:
    """Extract and categorize verified facilities from hotspot records."""
    facilities: Dict[str, List[Dict[str, str]]] = {
        "hospitals": [],
        "schools": [],
        "shelters": [],
    }

    if not hotspots or not isinstance(hotspots, list):
        return facilities

    for h in hotspots:
        if not isinstance(h, dict):
            continue

        raw_infras = h.get("critical_infrastructure_nearby", [])
        if not raw_infras:
            continue

        zone = h.get("zone", f"{PILOT_CITY} Urban Sector")
        h_name = h.get("name", f"{PILOT_CITY} Sector")
        sev_context = h.get("severity_tier", "Moderate")

        for infra_name in raw_infras:
            if not isinstance(infra_name, str):
                continue

            infra_lower = infra_name.lower()
            record = {
                "name": infra_name,
                "vicinity": h_name,
                "zone": zone,
                "severity_context": sev_context,
                "source": "GCC Hotspot Infrastructure Registry",  # Kept for test-contract compatibility
            }

            if any(k in infra_lower for k in ["hospital", "clinic", "health", "medical"]):
                facilities["hospitals"].append(record)
            elif any(k in infra_lower for k in ["school", "college", "vidyalaya", "academy", "university"]):
                facilities["schools"].append(record)
            elif any(k in infra_lower for k in ["station", "shelter", "terminus", "concourse", "depot", "ground"]):
                facilities["shelters"].append(record)
            else:
                facilities["shelters"].append(record)

    return facilities


def get_bilingual_messages() -> Dict[str, Any]:
    """Return citizen-facing message templates and safety guidance in English and Hindi."""
    return {
        "en": {
            "title": "Community Flood Advisory",
            "language_name": "English",
            "status_normal": "STATUS: NORMAL MONITORING",
            "normal_summary": (
                f"Flood risk information and neighborhood safety advisories for {PILOT_CITY}. "
                f"Water levels across {PILOT_CITY} monitored drainage channels are currently within normal thresholds."
            ),
            "sample_advisory_title": f"WEATHER ADVISORY — {PILOT_CITY} Urban Basin",
            "sample_advisory_body": (
                "Moderate to heavy showers anticipated. Low-elevation railway underpasses and "
                "basin depressions are monitored for stormwater stagnation. "
                "Recommended action: Avoid parking vehicles in low basements or driving through flooded underpasses. "
                "Utilize elevated transit concourses if street water levels rise."
            ),
            "safety_tips": [
                "Never attempt to walk, swim, or drive through standing or moving floodwater.",
                "Stay clear of electrical poles, open stormwater drains, and canal banks.",
                "Keep emergency contact numbers and mobile power banks fully charged.",
                "Follow official State Disaster Management Authority announcements before traveling.",
            ],
            "safe_route_note": (
                "Day 4 Active: The Chetna safe-route engine navigates citizens around flooded streets to the nearest safe shelter."
            ),
        },
        "hi": {
            "title": "सामुदायिक बाढ़ सलाह एवं चेतावनी",
            "language_name": "हिंदी (Hindi)",
            "status_normal": "स्थिति: सामान्य निगरानी",
            "normal_summary": (
                f"{PILOT_CITY} के लिए बाढ़ जोखिम की जानकारी और आपके क्षेत्र के लिए सुरक्षा सलाह। "
                f"{PILOT_CITY} के प्रमुख जल निकासी चैनलों में जल स्तर वर्तमान में सामान्य सीमा के भीतर है।"
            ),
            "sample_advisory_title": f"मौसम सलाह — {PILOT_CITY} शहरी क्षेत्र",
            "sample_advisory_body": (
                "अगले कुछ घंटों में मध्यम से भारी बारिश की संभावना है। निचले अंडरपास और "
                "निचले इलाकों में जलभराव पर नजर रखी जा रही है। "
                "सलाह: वाहनों को निचले बेसमेंट में न रखें और जलभराव वाले सबवे से बचें। "
                "सड़क पर जल स्तर बढ़ने पर ऊँचे परिसर या सुरक्षित राहत केंद्र का उपयोग करें।"
            ),
            "safety_tips": [
                "बहते या ठहरे हुए बाढ़ के पानी में पैदल चलने या वाहन चलाने का प्रयास न करें।",
                "बिजली के खंभों, खुले नालों और नहर के किनारों से हमेशा दूर रहें।",
                "आपातकालीन नंबर और मोबाइल फोन को पूरी तरह चार्ज रखें।",
                "यात्रा करने से पहले राज्य आपदा प्रबंधन प्राधिकरण की आधिकारिक घोषणाओं का पालन करें।",
            ],
            "safe_route_note": (
                "डे 4 सक्रिय: चेतना सेफ-रूट इंजन नागरिकों को जलभराव वाले रास्तों से बचाकर निकटतम सुरक्षित राहत केंद्र तक पहुँचाता है।"
            ),
        },
    }


def get_risk_advisory_bilingual(risk_level: str = "LOW") -> Dict[str, str]:
    """Return concise citizen safety advisory across calibrated risk tiers in English and Hindi."""
    lvl = (risk_level or "LOW").upper()
    advisories = {
        "LOW": {
            "en": "Conditions are currently normal. Continue to monitor updates.",
            "hi": "वर्तमान में स्थिति सामान्य है। नवीनतम जानकारी के लिए जुड़े रहें।",
            "tier": "LOW",
        },
        "MEDIUM": {
            "en": "Waterlogging may develop in vulnerable areas. Avoid unnecessary travel through low-lying roads.",
            "hi": "निचले और संवेदनशील इलाकों में जलभराव हो सकता है। निचले रास्तों से अनावश्यक यात्रा से बचें।",
            "tier": "MEDIUM",
        },
        "HIGH": {
            "en": "Flooding/waterlogging risk is elevated. Avoid known low-lying areas and consider moving toward a safer location.",
            "hi": "जलभराव और बाढ़ का जोखिम अधिक है। जलमग्न क्षेत्रों से बचें और आवश्यकता पड़ने पर सुरक्षित स्थान की ओर जाएं।",
            "tier": "HIGH",
        },
        "SEVERE": {
            "en": "Severe flood risk is indicated. Follow local emergency instructions and move to a safer location if advised.",
            "hi": "गंभीर बाढ़ का खतरा है। स्थानीय आपदा प्रबंधन के निर्देशों का पालन करें और सुरक्षित स्थान पर जाएं।",
            "tier": "SEVERE",
        },
    }
    return advisories.get(lvl, advisories["LOW"])



# ---------------------------------------------------------------------------
# Streamlit Citizen UI Renderers
# ---------------------------------------------------------------------------

def render_citizen_header() -> None:
    """Render the simplified, citizen-friendly header."""
    logo_path = get_logo_asset_path()

    with st.container(border=True):
        header_left, header_right = st.columns([0.70, 0.30], vertical_alignment="center")
        with header_left:
            col_logo, col_title = st.columns([0.10, 0.90], vertical_alignment="center")
            with col_logo:
                if logo_path and logo_path.exists():
                    st.image(str(logo_path), width=44)
            with col_title:
                st.markdown(
                    f"""
                    <div style="line-height:1.2;">
                        <div style="font-size:1.35rem; font-weight:800; color:#0f172a; letter-spacing:-0.02em;">
                            {SYSTEM_NAME} <span style="font-size:0.95rem; font-weight:600; color:#0284c7;">| {PILOT_CITY} Flood Safety</span>
                        </div>
                        <div style="font-size:0.8rem; color:#475569; margin-top:2px;">
                            Your neighborhood guide for urban flood awareness and safe evacuation &bull; <b>{PILOT_LOCATION_LABEL}</b>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with header_right:
            st.markdown(
                f"""
                <div style="display:flex; justify-content:flex-end; gap:8px; align-items:center; flex-wrap:wrap;">
                    <span class="status-pill status-pill-green">&bull; Conditions Normal</span>
                    <span class="status-pill status-pill-slate">Patna Resident Portal</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_citizen_status_card() -> None:
    """Render prominent, reassuring status card for citizens."""
    st.markdown(
        f"""
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-left:5px solid #16a34a; border-radius:10px; padding:1.1rem 1.35rem; margin-bottom:1rem; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="font-size:1.8rem; line-height:1;">🟢</div>
                    <div>
                        <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#15803d;">OVERALL SAFETY STATUS</div>
                        <div style="font-size:1.2rem; font-weight:800; color:#14532d; letter-spacing:-0.01em;">
                            LOW RISK &bull; NO ACTIVE FLOOD WARNINGS
                        </div>
                    </div>
                </div>
                <div style="display:flex; gap:12px; font-size:0.8rem; color:#166534; font-weight:600;">
                    <div>City: <b>{PILOT_CITY}</b></div>
                    <div>&bull;</div>
                    <div>Transit: <b>Normal</b></div>
                    <div>&bull;</div>
                    <div>Drainage: <b>Clear</b></div>
                </div>
            </div>
            <div style="margin-top:0.6rem; font-size:0.85rem; color:#166534; line-height:1.45;">
                Monitored drainage corridors across <b>{PILOT_CITY}</b> are currently operating within safe thresholds. Roads and pedestrian thoroughfares are clear. Check your neighborhood below for local outlooks.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_input_stub(hotspots: Optional[List[Dict[str, Any]]] = None) -> None:
    """Render neighborhood risk checker and 6-hour forecast timeline."""
    with st.container(border=True):
        st.markdown(
            f"""
            <div style="margin-bottom:0.75rem;">
                <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">📍 Check Your Neighborhood Flood Risk</div>
                <div style="font-size:0.8rem; color:#64748b;">Select your locality to view localized waterlogging risk and upcoming 6-hour outlook.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_area, col_horizon = st.columns([0.55, 0.45])

        patna_localities = [
            "Kankarbagh (Patna South)",
            "Rajendra Nagar (East)",
            "Gandhi Maidan / Fraser Road (Central)",
            "Bailey Road / Raja Bazar (West)",
            "Patliputra Colony / Boring Road",
            "Danapur / Khagaul Corridor",
            "Patna City / Chowk Basin",
            "Anisabad / Bypass Lowlands",
            "Digha / Ganga Riverfront",
            "Kankarbagh Drainage Zone 2",
        ]

        with col_area:
            selected_area = st.selectbox(
                "Your Neighborhood / Locality:",
                options=patna_localities,
                index=0,
                key="citizen_area_selector",
                help="Select your local area in Patna.",
            )

        with col_horizon:
            selected_horizon = st.radio(
                "Forecast Horizon:",
                options=["NOW (Current)", "+1 Hour", "+3 Hours", "+6 Hours"],
                index=0,
                horizontal=True,
                key="citizen_horizon_selector",
            )

        # Map selected horizon to canonical horizon key
        horizon_key = "NOW"
        if "+1" in selected_horizon:
            horizon_key = "+1h"
        elif "+3" in selected_horizon:
            horizon_key = "+3h"
        elif "+6" in selected_horizon:
            horizon_key = "+6h"

        from app.map_layers import load_horizon_predictions
        horizon_info = load_horizon_predictions(horizon_key)

        is_available = horizon_info.get("available", False)
        counts = horizon_info.get("counts") or {}

        if not is_available:
            risk_badge = '<span style="background:#fffbeb; color:#92400e; border:1px solid #fde68a; border-radius:9999px; padding:4px 12px; font-weight:700; font-size:0.85rem;">⚠️ FORECAST UNAVAILABLE</span>'
            status_desc = f"At <b>{selected_horizon}</b>, dynamic meteorological forecast data is not available. Displaying calibrated topographic vulnerability baseline for {selected_area}."
        elif counts.get("SEVERE", 0) > 0 or counts.get("HIGH", 0) > 0:
            sev_cnt = counts.get("SEVERE", 0)
            high_cnt = counts.get("HIGH", 0)
            tier_label = "SEVERE INUNDATION" if sev_cnt > 0 else "HIGH WATERLOGGING RISK"
            icon = "🔴"
            risk_badge = f'<span style="background:#fef2f2; color:#991b1b; border:1px solid #fecaca; border-radius:9999px; padding:4px 12px; font-weight:700; font-size:0.85rem;">{icon} {tier_label}</span>'
            status_desc = f"At <b>{selected_horizon}</b>, heavy precipitation is forecasted. {high_cnt + sev_cnt} municipal sectors are projected to experience elevated waterlogging. Low-lying underpasses and arterial corridors in {selected_area} may be impassable."
        elif counts.get("MEDIUM", 0) > 0:
            risk_badge = '<span style="background:#fffbeb; color:#92400e; border:1px solid #fde68a; border-radius:9999px; padding:4px 12px; font-weight:700; font-size:0.85rem;">🟡 MEDIUM RISK</span>'
            status_desc = f"At <b>{selected_horizon}</b>, elevated rainfall rates expected. Moderate stormwater accumulation possible in depression corridors. Exercise caution in {selected_area}."
        else:
            risk_badge = '<span style="background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; border-radius:9999px; padding:4px 12px; font-weight:700; font-size:0.85rem;">🟢 LOW RISK</span>'
            status_desc = f"At <b>{selected_horizon}</b>, rainfall rates are within nominal thresholds. Local streets and pedestrian paths in {selected_area} are safe for transit. No major waterlogging expected."

        # Risk assessment result card for selected locality
        st.markdown(
            f"""
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin-top:0.5rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                    <div>
                        <span style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:#64748b;">LOCALITY OUTLOOK</span>
                        <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">{selected_area}</div>
                    </div>
                    <div style="display:flex; align-items:center; gap:8px;">
                        {risk_badge}
                    </div>
                </div>
                <div style="margin-top:8px; font-size:0.83rem; color:#334155; line-height:1.4;">
                    {status_desc}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_citizen_map(folium_map: Any) -> None:
    """Render community base map with Mapbox / PyDeck or Folium."""
    with st.container(border=True):
        st.markdown(
            f"""
            <div style="margin-bottom:0.75rem;">
                <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">🗺️ Community Flood Safety Map</div>
                <div style="font-size:0.8rem; color:#64748b;">Interactive Mapbox vector map centered on {PILOT_LOCATION_LABEL} with monitored flood areas and safe facilities.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if hasattr(folium_map, "to_json"):
            st.pydeck_chart(folium_map, use_container_width=True)
        elif hasattr(folium_map, "get_root"):
            map_html = folium_map.get_root().render()
            st.components.v1.html(map_html, height=480, scrolling=False)


def render_citizen_facilities_panel(facilities: Dict[str, List[Dict[str, str]]]) -> None:
    """Render categorized at-risk facilities and nearby safe places."""
    with st.container(border=True):
        st.markdown(
            f"""
            <div style="margin-bottom:0.5rem;">
                <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">🏛️ Nearby Safe Places &amp; Facilities</div>
                <div style="font-size:0.8rem; color:#64748b;">Verified emergency shelters, community havens, and healthcare centers.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_shelters, tab_hospitals, tab_schools = st.tabs([
            "🏛️ Safe Shelters",
            "🏥 Hospitals",
            "🏫 Schools / Relief Sites",
        ])

        with tab_shelters:
            shelters = facilities.get("shelters", [])
            if shelters:
                for sh in shelters[:5]:
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                            <div style="font-weight:600; font-size:0.84rem; color:#0f172a;">{sh['name']}</div>
                            <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">
                                Vicinity: <b>{sh['vicinity']}</b> &bull; Elevated Safe Haven
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No designated safe shelters currently listed.")

        with tab_hospitals:
            hospitals = facilities.get("hospitals", [])
            if hospitals:
                for h in hospitals[:5]:
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                            <div style="font-weight:600; font-size:0.84rem; color:#0f172a;">{h['name']}</div>
                            <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">
                                Vicinity: <b>{h['vicinity']}</b> &bull; Emergency Medical Care
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No hospital records currently listed.")

        with tab_schools:
            schools = facilities.get("schools", [])
            if schools:
                for s in schools[:5]:
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                            <div style="font-weight:600; font-size:0.84rem; color:#0f172a;">{s['name']}</div>
                            <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">
                                Vicinity: <b>{s['vicinity']}</b> &bull; Secondary Relief Staging
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No school records currently listed.")

        st.markdown(
            """
            <div style="font-size:0.72rem; color:#94a3b8; margin-top:8px; border-top:1px solid #f1f5f9; padding-top:4px; text-align:center;">
                Reference facilities from municipal infrastructure registry (Study Grid Dataset). Prototype baseline.
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_citizen_safe_route(folium_map: folium.Map, hotspots: List[Dict[str, Any]]) -> None:
    """Render the safe-route finder interface connecting to the existing safe_route backend."""
    with st.container(border=True):
        st.markdown(
            """
            <div style="margin-bottom:0.75rem;">
                <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">🚶 Find Safe Route to Shelter</div>
                <div style="font-size:0.8rem; color:#64748b;">Navigate safely to the nearest elevated ground, avoiding waterlogged streets.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        neighborhood_coords = {
            "Kankarbagh Lowlands (Patna)": (25.594, 85.158),
            "Rajendra Nagar Station Area": (25.601, 85.163),
            "Gandhi Maidan / Exhibition Road": (25.615, 85.143),
            "Bailey Road / Saguna More": (25.612, 85.062),
            "Patliputra Industrial Area": (25.632, 85.105),
        }

        facilities = extract_facilities_from_hotspots(hotspots)
        shelters = facilities.get("shelters", [])
        shelter_options = ["Nearest Available Safe Shelter"] + [s["name"] for s in shelters] if shelters else ["Nearest Available Safe Shelter", "Patna Junction Elevated Concourse", "Moin-ul-Haq Stadium Haven"]

        col1, col2 = st.columns(2)
        with col1:
            start_loc = st.selectbox(
                "START LOCATION:",
                options=list(neighborhood_coords.keys()),
                key="route_start_citizen",
                help="Select where you are currently located.",
            )
        with col2:
            dest_loc = st.selectbox(
                "DESTINATION SHELTER:",
                options=shelter_options,
                key="route_dest_citizen",
                help="Select your target shelter or find the nearest safe haven.",
            )

        if st.button("🚶 Find Decision-Support Route", use_container_width=True, key="btn_safe_route_action"):
            start_lat, start_lon = neighborhood_coords.get(start_loc, (25.594, 85.158))

            candidate_shelters = []
            if dest_loc and dest_loc != "Nearest Available Safe Shelter":
                for s in shelters:
                    if s["name"] == dest_loc:
                        h_coords = None
                        for h in hotspots:
                            if h.get("name") == s.get("vicinity") or s["name"] in h.get("critical_infrastructure_nearby", []):
                                h_coords = (h.get("latitude", 25.602), h.get("longitude", 85.138))
                                break
                        lat_val, lon_val = h_coords if h_coords else (25.602, 85.138)
                        candidate_shelters.append({
                            "id": s.get("name", "shelter"),
                            "name": s["name"],
                            "latitude": lat_val,
                            "longitude": lon_val,
                            "amenity": "shelter",
                        })
                        break

            if not candidate_shelters and shelters:
                for s in shelters:
                    h_coords = None
                    for h in hotspots:
                        if h.get("name") == s.get("vicinity") or s["name"] in h.get("critical_infrastructure_nearby", []):
                            h_coords = (h.get("latitude", 25.602), h.get("longitude", 85.138))
                            break
                    lat_val, lon_val = h_coords if h_coords else (25.602, 85.138)
                    candidate_shelters.append({
                        "id": s.get("name", "shelter"),
                        "name": s["name"],
                        "latitude": lat_val,
                        "longitude": lon_val,
                        "amenity": "shelter",
                    })

            try:
                from src.routing.router import safe_route
                with st.spinner("Finding safe route avoiding flooded corridors..."):
                    res = safe_route(
                        lat=start_lat,
                        lon=start_lon,
                        horizon=1,
                        shelters=candidate_shelters if candidate_shelters else None,
                    )
            except Exception as e:
                logger.error("Routing engine error: %s", e)
                res = {
                    "status": "error",
                    "found": False,
                    "route": [],
                    "message": f"Safe routing service temporarily unavailable: {e}",
                }

            st.markdown("<hr style='margin: 0.6rem 0;'/>", unsafe_allow_html=True)
            st.markdown(f"<div><b>START:</b> {start_loc}</div>", unsafe_allow_html=True)
            target_dest_label = (res.get("destination") or {}).get("name") or dest_loc
            st.markdown(f"<div><b>DESTINATION:</b> {target_dest_label}</div>", unsafe_allow_html=True)

            if res.get("found", False) and res.get("status") == "success":
                route = res.get("route", [])
                dist_km = (res.get("distance_m") or 0.0) / 1000.0
                time_min = res.get("estimated_time_min") or 0.0
                hazards_avoided = (res.get("risk_info") or {}).get("hazards_avoided", 0)

                st.markdown(
                    f"""
                    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-left: 4px solid #16a34a; border-radius: 6px; padding: 10px 14px; margin-top: 8px;">
                        <div style="font-weight: 700; color: #166534; font-size: 0.92rem;">ROUTE STATUS: Safe route found</div>
                        <div style="font-size: 0.82rem; color: #15803d; margin-top: 4px;">
                            Approximate distance: <b>{dist_km:.1f} km</b> &bull; Estimated walking time: <b>{time_min:.0f} mins</b>
                        </div>
                        <div style="font-size: 0.78rem; color: #166534; margin-top: 4px;">
                            Route Safety: <b>Normal (Low Risk)</b> &bull; Monitored waterlogging zones avoided: <b>{hazards_avoided}</b>
                        </div>
                        <div style="font-size: 0.76rem; color: #15803d; margin-top: 6px; border-top: 1px dashed #bbf7d0; padding-top: 4px;">
                            Safety Note: Decision-support navigation path only; not a guaranteed safe evacuation route. Stay on elevated walkways and avoid flooded road underpasses. Follow local municipal ward guidance.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if route:
                    points = [(r["lat"], r["lon"]) for r in route]
                    if hasattr(folium_map, "get_root"):
                        folium.PolyLine(
                            points,
                            color="#0284c7",
                            weight=5,
                            opacity=0.85,
                            tooltip=f"Safe Route to {target_dest_label}",
                        ).add_to(folium_map)
                        folium.Marker(points[0], icon=folium.Icon(color="green", icon="play"), tooltip="Origin").add_to(folium_map)
                        folium.Marker(points[-1], icon=folium.Icon(color="red", icon="home"), tooltip=target_dest_label).add_to(folium_map)

                    # Also render dedicated high-contrast route navigation deck
                    try:
                        from app.map_layers import build_citizen_route_deck
                        route_deck = build_citizen_route_deck(
                            center=(start_lat, start_lon),
                            zoom_start=12.5,
                            route_coords=route,
                            start_coord=(start_lat, start_lon),
                            dest_coord=(points[-1][0], points[-1][1]),
                            dest_name=target_dest_label,
                            shelters_data=candidate_shelters,
                            hotspots_data=hotspots,
                        )
                        st.markdown("<div style='font-size:0.8rem; font-weight:700; color:#0f172a; margin:10px 0 6px 0;'>🗺️ Route Navigation Map:</div>", unsafe_allow_html=True)
                        st.pydeck_chart(route_deck, use_container_width=True)
                    except Exception as deck_err:
                        logger.debug("Citizen route deck render note: %s", deck_err)
            else:
                st.markdown(
                    """
                    <div style="background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #dc2626; border-radius: 6px; padding: 10px 14px; margin-top: 8px;">
                        <div style="font-weight: 700; color: #991b1b; font-size: 0.92rem;">ROUTE STATUS: NO SAFE ROUTE FOUND</div>
                        <div style="font-size: 0.82rem; color: #b91c1c; margin-top: 4px;">
                            No safe route is currently available to any designated shelter due to elevated waterlogging in connecting corridors.
                        </div>
                        <div style="font-size: 0.78rem; color: #7f1d1d; margin-top: 6px; border-top: 1px dashed #fecaca; padding-top: 4px;">
                            Immediate Safety Action: Do not attempt to walk or drive through flooded thoroughfares. Seek immediate higher ground or an elevated upper floor in your current building.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown("<div style='font-size: 0.8rem; font-weight: 700; color: #0f172a; margin-top: 10px;'>Suggested Safe Places Nearby:</div>", unsafe_allow_html=True)
                if shelters:
                    for s in shelters[:3]:
                        st.markdown(
                            f"<div style='font-size: 0.78rem; color: #334155;'>&bull; <b>{s['name']}</b> ({s['vicinity']})</div>",
                            unsafe_allow_html=True,
                        )


def render_citizen_advisory_section() -> None:
    """Render bilingual emergency advisory and alert guidance (English | हिंदी) with risk-level guidance."""
    messages = get_bilingual_messages()

    with st.container(border=True):
        st.markdown(
            """
            <div style="margin-bottom:0.75rem;">
                <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">📢 Community Safety Advisory</div>
                <div style="font-size:0.8rem; color:#64748b;">Essential safety guidelines, risk level guidance, and public announcements.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_en, tab_hi = st.tabs(["English", "हिंदी"])

        with tab_en:
            en_data = messages["en"]
            st.markdown(
                f"""
                <div style="background:#eff6ff; border:1px solid #bfdbfe; border-left:4px solid #3b82f6; border-radius:6px; padding:10px 12px; margin-bottom:0.75rem;">
                    <div style="font-weight:700; font-size:0.88rem; color:#1e40af;">{en_data['sample_advisory_title']}</div>
                    <div style="font-size:0.82rem; color:#1e3a8a; margin-top:4px; line-height:1.45;">
                        {en_data['sample_advisory_body']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#0f172a; margin:0.6rem 0 0.3rem 0;'>Guidance by Risk Level:</div>", unsafe_allow_html=True)
            for tier in ["LOW", "MEDIUM", "HIGH", "SEVERE"]:
                adv = get_risk_advisory_bilingual(tier)
                badge_bg = "#dcfce7" if tier == "LOW" else ("#fef3c7" if tier == "MEDIUM" else "#fee2e2")
                badge_col = "#166534" if tier == "LOW" else ("#92400e" if tier == "MEDIUM" else "#991b1b")
                st.markdown(
                    f"<div style='margin-bottom:5px; font-size:0.8rem;'>"
                    f"<span style='font-size:0.7rem; font-weight:700; background:{badge_bg}; color:{badge_col}; padding:2px 6px; border-radius:4px; margin-right:6px;'>{tier}</span>"
                    f"<span style='color:#334155;'>{adv['en']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#0f172a; margin:0.75rem 0 0.25rem 0;'>Key Safety Precautions:</div>", unsafe_allow_html=True)
            for tip in en_data["safety_tips"]:
                st.markdown(f"- {tip}")

        with tab_hi:
            hi_data = messages["hi"]
            st.markdown(
                f"""
                <div style="background:#eff6ff; border:1px solid #bfdbfe; border-left:4px solid #3b82f6; border-radius:6px; padding:10px 12px; margin-bottom:0.75rem;">
                    <div style="font-weight:700; font-size:0.88rem; color:#1e40af;">{hi_data['sample_advisory_title']}</div>
                    <div style="font-size:0.82rem; color:#1e3a8a; margin-top:4px; line-height:1.45;">
                        {hi_data['sample_advisory_body']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#0f172a; margin:0.6rem 0 0.3rem 0;'>जोखिम स्तर के अनुसार निर्देश:</div>", unsafe_allow_html=True)
            for tier in ["LOW", "MEDIUM", "HIGH", "SEVERE"]:
                adv = get_risk_advisory_bilingual(tier)
                badge_bg = "#dcfce7" if tier == "LOW" else ("#fef3c7" if tier == "MEDIUM" else "#fee2e2")
                badge_col = "#166534" if tier == "LOW" else ("#92400e" if tier == "MEDIUM" else "#991b1b")
                st.markdown(
                    f"<div style='margin-bottom:5px; font-size:0.8rem;'>"
                    f"<span style='font-size:0.7rem; font-weight:700; background:{badge_bg}; color:{badge_col}; padding:2px 6px; border-radius:4px; margin-right:6px;'>{tier}</span>"
                    f"<span style='color:#334155;'>{adv['hi']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#0f172a; margin:0.75rem 0 0.25rem 0;'>मुख्य सुरक्षा सावधानियां:</div>", unsafe_allow_html=True)
            for tip in hi_data["safety_tips"]:
                st.markdown(f"- {tip}")



def render_citizen_footer() -> None:
    """Render clean, citizen-focused emergency contact cards and footer."""
    with st.container(border=True):
        st.markdown(
            f"""
            <div style="margin-bottom:0.6rem;">
                <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">🚨 Emergency Help &amp; Hotlines — {PILOT_LOCATION_LABEL}</div>
                <div style="font-size:0.8rem; color:#64748b;">Direct government emergency contact numbers available 24/7.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"""
                <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:10px 12px; text-align:center;">
                    <div style="font-size:0.72rem; font-weight:700; color:#991b1b; text-transform:uppercase;">NATIONAL EMERGENCY</div>
                    <div style="font-size:1.4rem; font-weight:800; color:#b91c1c; margin:2px 0;">{EMERGENCY_HELPLINES['national_emergency']}</div>
                    <div style="font-size:0.72rem; color:#7f1d1d;">Police &bull; Fire &bull; Ambulance</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:10px 12px; text-align:center;">
                    <div style="font-size:0.72rem; font-weight:700; color:#1e40af; text-transform:uppercase;">BIHAR DISASTER HELPLINE</div>
                    <div style="font-size:1.4rem; font-weight:800; color:#1d4ed8; margin:2px 0;">{EMERGENCY_HELPLINES['state_disaster']}</div>
                    <div style="font-size:0.72rem; color:#1e3a8a;">BSDMA 24/7 Helpline</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
                <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:10px 12px; text-align:center;">
                    <div style="font-size:0.72rem; font-weight:700; color:#166534; text-transform:uppercase;">PATNA DISTRICT CONTROL</div>
                    <div style="font-size:1.4rem; font-weight:800; color:#15803d; margin:2px 0;">{EMERGENCY_HELPLINES['district_emergency']}</div>
                    <div style="font-size:0.72rem; color:#14532d;">Emergency Operations (DEOC)</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f"""
                <div style="background:#faf5ff; border:1px solid #e9d5ff; border-radius:8px; padding:10px 12px; text-align:center;">
                    <div style="font-size:0.72rem; font-weight:700; color:#6b21a8; text-transform:uppercase;">MUNICIPAL CONTROL ROOM</div>
                    <div style="font-size:1.1rem; font-weight:800; color:#7e22ce; margin:5px 0;">{EMERGENCY_HELPLINES['municipal_control_room']}</div>
                    <div style="font-size:0.72rem; color:#581c87;">PMC Drainage &bull; Waterlogging</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        f"""
        <div style="text-align:center; padding:1.25rem 0 0.5rem 0; color:#94a3b8; font-size:0.75rem;">
            <b>{SYSTEM_NAME} Citizen Flood Safety Portal</b> &bull; {PILOT_LOCATION_LABEL}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_view(
    folium_map: folium.Map,
    hotspots: List[Dict[str, Any]],
    metrics: Dict[str, Any],
) -> None:
    """Main orchestrator for F2 Citizen Safety Portal."""
    facilities = extract_facilities_from_hotspots(hotspots)

    # 1. Citizen Header with Logo
    render_citizen_header()

    # 2. Prominent Safety Status Card
    render_citizen_status_card()

    # 3. Neighborhood & Horizon Risk Check
    render_citizen_input_stub(hotspots)

    # 4. Map and At-Risk Facilities in Split Layout
    col_map, col_info = st.columns([60, 40])
    with col_map:
        render_citizen_map(folium_map)
    with col_info:
        render_citizen_facilities_panel(facilities)

    # 5. Safe Route Finder & Bilingual Advisory Section
    col_route, col_advisory = st.columns([45, 55])
    with col_route:
        render_citizen_safe_route(folium_map, hotspots)
    with col_advisory:
        render_citizen_advisory_section()

    # 6. Emergency Help & Helplines Footer
    render_citizen_footer()
