"""Chetna: Neighborhood-Scale Flood Early Warning Prototype.

F2 Day 1: Citizen View foundation and wireframes.
Provides an accessible, community-oriented interface for Chennai residents:
- Simple, plain-language flood situational awareness
- Neighborhood risk check input stub (Current / +1h / +3h / +6h)
- Sourced at-risk facilities panel (hospitals, schools, transit shelters)
- Safe-route placeholder (wireframe for Day 4 routing milestone)
- Bilingual emergency advisory and alert foundation (English + Hindi)
- Community base map centered on Chennai
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
import streamlit as st

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
    hotspots: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, str]]]:
    """Extract and categorize verified facilities from GCC hotspot records.

    Uses the critical infrastructure documented in M1 Day 1 hotspots.json
    without fabricating real-world data.

    Parameters
    ----------
    hotspots : list of dict
        Hotspot records containing 'critical_infrastructure_nearby'.

    Returns
    -------
    dict
        Categorized facilities: 'hospitals', 'schools', 'shelters'.
    """
    facilities: Dict[str, List[Dict[str, str]]] = {
        "hospitals": [],
        "schools": [],
        "shelters": [],
    }

    if not hotspots or not isinstance(hotspots, list):
        return facilities

    for h in hotspots:
        zone = h.get("zone", "Chennai Metropolitan Area")
        h_name = h.get("name", "Chennai Pilot Area")
        severity = h.get("severity_tier", "Moderate")

        for inf in h.get("critical_infrastructure_nearby", []):
            if not isinstance(inf, str):
                continue

            inf_lower = inf.lower()
            item = {
                "name": inf,
                "vicinity": h_name,
                "zone": zone,
                "severity_context": severity,
                "source": "GCC Hotspot Infrastructure Registry",
            }

            if any(w in inf_lower for w in ["hospital", "health", "medical"]):
                facilities["hospitals"].append(item)
            elif any(w in inf_lower for w in ["school", "college", "institute", "arts"]):
                facilities["schools"].append(item)
            elif any(w in inf_lower for w in ["station", "terminus", "centre", "center", "hub", "depot", "bridge", "subway"]):
                facilities["shelters"].append(item)

    return facilities


def get_bilingual_messages() -> Dict[str, Dict[str, Any]]:
    """Return citizen-facing message templates and safety guidance in English and Hindi."""
    return {
        "en": {
            "title": "Community Flood Advisory & Alerts",
            "language_name": "English",
            "status_normal": "STATUS: NORMAL MONITORING",
            "normal_summary": (
                "Flood risk information and neighborhood safety advisories will appear here. "
                "Water levels across Chennai monitored drainage channels are currently within normal thresholds."
            ),
            "sample_advisory_title": "DRAFT FLOOD ADVISORY — Zone 13 (Velachery & Madipakkam)",
            "sample_advisory_body": (
                "Heavy rainfall anticipated (>60 mm in 6h). Low-elevation railway underpasses and the "
                "Ram Nagar basin are at elevated risk of stormwater stagnation. "
                "Recommended action: Avoid parking vehicles in basement areas or driving through subways. "
                "Utilize Velachery MRTS elevated concourse if street water levels rise."
            ),
            "safety_tips": [
                "Never attempt to walk, swim, or drive through standing or moving floodwater.",
                "Stay clear of electrical poles, open stormwater culverts, and canal banks.",
                "Keep emergency contact numbers and mobile power banks charged.",
                "Follow official GCC and TNSDMA announcements before traveling.",
            ],
            "safe_route_note": (
                "Route calculation will be available in a later milestone (Day 4). "
                "The Chetna routing engine will navigate citizens around flooded streets to the nearest safe shelter."
            ),
        },
        "hi": {
            "title": "सामुदायिक बाढ़ सलाह एवं चेतावनी",
            "language_name": "हिंदी (Hindi)",
            "status_normal": "स्थिति: सामान्य निगरानी",
            "normal_summary": (
                "बाढ़ जोखिम की जानकारी और आपके क्षेत्र के लिए सुरक्षा सलाह यहाँ दिखाई जाएगी। "
                "चेन्नई के प्रमुख जल निकासी चैनलों में जल स्तर वर्तमान में सामान्य सीमा के भीतर है।"
            ),
            "sample_advisory_title": "प्रारूप बाढ़ चेतावनी — ज़ोन 13 (वेलाचेरी एवं मदिपक्कम)",
            "sample_advisory_body": (
                "अगले 6 घंटों में भारी बारिश (>60 मिमी) की संभावना है। निचले रेलवे अंडरपास और "
                "राम नगर बेसिन में जलभराव का जोखिम बढ़ सकता है। "
                "सलाह: वाहनों को निचले बेसमेंट में न रखें और सबवे से बचें। "
                "सड़क पर जल स्तर बढ़ने पर वेलाचेरी एमआरटीएस स्टेशन के ऊँचे परिसर का उपयोग करें।"
            ),
            "safety_tips": [
                "बहते या ठहरे हुए बाढ़ के पानी में पैदल चलने या वाहन चलाने का प्रयास न करें।",
                "बिजली के खंभों, खुले नालों और नहर के किनारों से दूर रहें।",
                "आपातकालीन नंबर और मोबाइल फोन को चार्ज रखें।",
                "यात्रा करने से पहले आधिकारिक जीसीसी (GCC) और आपदा प्रबंधन घोषणाओं का पालन करें।",
            ],
            "safe_route_note": (
                "सुरक्षित मार्ग की गणना अगले चरण (डे 4) में उपलब्ध होगी। "
                "चेतना सेफ-रूट इंजन नागरिकों को जलभराव वाले रास्तों से बचाकर निकटतम सुरक्षित राहत केंद्र तक पहुँचाएगा।"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Streamlit Citizen UI Renderers
# ---------------------------------------------------------------------------

def render_citizen_header() -> None:
    """Render the simplified, citizen-friendly header."""
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
                            Chetna <span style="font-size:0.92rem; font-weight:500; color:#0284c7;">| Community Flood Safety Portal</span>
                        </div>
                        <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                            Neighborhood Flood Awareness &amp; Resident Safety &bull; Pilot: <b>Chennai, India</b>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with header_right:
            st.markdown(
                """
                <div style="display:flex; justify-content:flex-end; gap:8px; align-items:center; flex-wrap:wrap;">
                    <span class="chetna-pill chetna-pill-teal">&bull; Low Risk &bull; Normal</span>
                    <span class="chetna-pill chetna-pill-blue">Citizen View &bull; F2 Day 1</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_citizen_status_card() -> None:
    """Render the prominent, plain-language situational awareness banner."""
    st.markdown(
        """
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-left:5px solid #22c55e; border-radius:8px; padding:1.1rem 1.25rem; margin-bottom:1rem;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
                <div>
                    <div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#15803d; margin-bottom:3px;">
                        CURRENT COMMUNITY SITUATION
                    </div>
                    <div style="font-size:1.25rem; font-weight:800; color:#14532d; letter-spacing:-0.01em;">
                        🟢 Conditions Normal &bull; No Active Flood Warning
                    </div>
                    <p style="margin:6px 0 0 0; font-size:0.88rem; color:#166534; line-height:1.45; max-width:850px;">
                        Chennai metropolitan drainage systems and major canals are operating within safe seasonal levels.
                        The Chetna early-warning pipeline is actively monitoring multi-hour rainfall projections.
                        Select your neighborhood below to check upcoming conditions.
                    </p>
                </div>
                <div style="text-align:right; font-size:0.75rem; color:#15803d; background:#dcfce7; padding:6px 12px; border-radius:6px;">
                    <div><b>Study Area:</b> Chennai</div>
                    <div><b>Status:</b> Monitored</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_input_stub(hotspots: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Render the citizen location input and forecast horizon selector stub."""
    neighborhood_names = [
        "Velachery (Zone 13 - Adyar)",
        "Madipakkam (Zone 14 - Perungudi)",
        "Mudichur / Varadharajapuram",
        "T. Nagar (Zone 10 - Kodambakkam)",
        "Pulianthope (Zone 6 - Thiru Vi Ka Nagar)",
        "Vyasarpadi (Zone 4 - Tondiarpet)",
        "Perambur (Zone 6 - Stephenson Road)",
        "Koyambedu (Zone 8 - Anna Nagar)",
        "Manapakkam (Zone 12 - Alandur)",
        "Pallikaranai (Zone 14 - IT Corridor)",
    ]

    st.markdown(
        """
        <div class="chetna-card" style="padding-bottom:0.75rem;">
            <div style="font-weight:700; font-size:1rem; color:#0f172a; margin-bottom:2px;">
                🔍 Check Flood Conditions in Your Neighborhood
            </div>
            <div style="font-size:0.78rem; color:#64748b; margin-bottom:0.85rem;">
                Select your area and anticipated timeframe to view local risk advisory and nearby safe centers.
            </div>
        """,
        unsafe_allow_html=True,
    )

    col_area, col_horizon, col_btn = st.columns([40, 40, 20], vertical_alignment="bottom")

    with col_area:
        selected_area = st.selectbox(
            "Select Your Area / Neighborhood:",
            options=neighborhood_names,
            index=0,
            help="Select one of the 10 monitored Chennai study areas.",
        )

    with col_horizon:
        selected_horizon = st.selectbox(
            "Forecast Horizon:",
            options=["Current Conditions", "Next 1 Hour (+1h)", "Next 3 Hours (+3h)", "Next 6 Hours (+6h)"],
            index=0,
            help="Time horizon for incoming rainfall forecasts (B1).",
        )

    with col_btn:
        check_clicked = st.button("Check Risk", use_container_width=True)

    if check_clicked:
        st.markdown(
            f"""
            <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px; padding:10px 14px; margin-top:0.75rem;">
                <div style="font-weight:700; font-size:0.85rem; color:#1e40af;">
                    📍 Area Assessment: {selected_area} &bull; {selected_horizon}
                </div>
                <div style="font-size:0.8rem; color:#1e3a8a; margin-top:3px;">
                    Current rainfall forecast shows no immediate overflow risk.
                    Terrain slope and drainage channels are in monitored standby.
                </div>
                <div style="font-size:0.72rem; color:#60a5fa; margin-top:4px;">
                    ℹ️ Day 1 Prototype UI Stub &bull; Dynamic prediction and live sensor correction activate in Day 3. No browser GPS is used.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
    return selected_area, selected_horizon


def render_citizen_map(folium_map: folium.Map) -> None:
    """Render community base map."""
    st.markdown(
        """
        <div class="chetna-card" style="padding-bottom:0.75rem;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.65rem; flex-wrap:wrap; gap:8px;">
                <div>
                    <div style="font-weight:700; font-size:1.02rem; color:#0f172a;">
                        🗺️ Chennai Neighborhood Flood Map
                    </div>
                    <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                        Interactive community overview centered on Chennai (13.0827&deg; N, 80.2707&deg; E)
                    </div>
                </div>
                <span class="chetna-pill chetna-pill-blue">Base Map Only &bull; F2 Day 1</span>
            </div>
        """,
        unsafe_allow_html=True,
    )

    map_html = folium_map.get_root().render()
    st.components.v1.html(map_html, height=480, scrolling=False)

    st.markdown(
        """
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.5rem; font-size:0.75rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.4rem;">
                <div>📍 Chennai Metropolitan Area &bull; OpenStreetMap Viewport</div>
                <div style="color:#0284c7; font-weight:500;">Static vulnerability color shading will overlay in F1/F2 Day 2</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_facilities_panel(facilities: Dict[str, List[Dict[str, str]]]) -> None:
    """Render the citizen-friendly at-risk facilities and safe shelters panel."""
    st.markdown(
        """
        <div class="chetna-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem; flex-wrap:wrap; gap:8px;">
                <div>
                    <div style="font-weight:700; font-size:1rem; color:#0f172a;">
                        🏥 Important Community Facilities &amp; Safe Havens
                    </div>
                    <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                        Critical facilities and elevated transit hubs in surveyed Chennai flood-prone corridors.
                    </div>
                </div>
                <span class="chetna-pill chetna-pill-teal">GCC Sourced Data</span>
            </div>
        """,
        unsafe_allow_html=True,
    )

    tab_hospitals, tab_schools, tab_shelters = st.tabs([
        f"🏥 Hospitals ({len(facilities.get('hospitals', []))})",
        f"🏫 Schools & Institutions ({len(facilities.get('schools', []))})",
        f"🏛️ Designated Safe Transit Hubs ({len(facilities.get('shelters', []))})",
    ])

    with tab_hospitals:
        st.caption("Key medical centers and hospitals located along surveyed drainage corridors.")
        hospitals = facilities.get("hospitals", [])
        if hospitals:
            cols = st.columns(2)
            for idx, h in enumerate(hospitals):
                target_col = cols[idx % 2]
                with target_col:
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                            <div style="font-weight:600; font-size:0.83rem; color:#0f172a;">{h['name']}</div>
                            <div style="font-size:0.74rem; color:#64748b; margin-top:2px;">
                                Vicinity: <b>{h['vicinity']}</b> &bull; {h['zone']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No hospital records available.")

    with tab_schools:
        st.caption("Educational institutions within monitored flood risk zones.")
        schools = facilities.get("schools", [])
        if schools:
            cols = st.columns(2)
            for idx, s in enumerate(schools):
                target_col = cols[idx % 2]
                with target_col:
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                            <div style="font-weight:600; font-size:0.83rem; color:#0f172a;">{s['name']}</div>
                            <div style="font-size:0.74rem; color:#64748b; margin-top:2px;">
                                Vicinity: <b>{s['vicinity']}</b> &bull; {s['zone']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No school records available.")

    with tab_shelters:
        st.caption("Elevated MRTS concourses, railway junctions, and transit terminals serving as safe shelters.")
        shelters = facilities.get("shelters", [])
        if shelters:
            cols = st.columns(2)
            for idx, sh in enumerate(shelters):
                target_col = cols[idx % 2]
                with target_col:
                    st.markdown(
                        f"""
                        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
                            <div style="font-weight:600; font-size:0.83rem; color:#0f172a;">{sh['name']}</div>
                            <div style="font-size:0.74rem; color:#64748b; margin-top:2px;">
                                Vicinity: <b>{sh['vicinity']}</b> &bull; Elevated Haven / Transit Hub
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No transit shelter records available.")

    st.markdown(
        """
            <div style="margin-top:0.6rem; font-size:0.73rem; color:#64748b; border-top:1px solid #f1f5f9; padding-top:0.4rem; text-align:center;">
                Verified from GCC Chronic Hotspot Infrastructure Records &bull; Full automated OpenStreetMap facility layer overlays in F2 Day 2.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_safe_route_placeholder() -> None:
    """Render the safe-route placeholder stub (wireframe for Day 4)."""
    st.markdown(
        """
        <div class="chetna-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.65rem;">
                <div>
                    <div style="font-weight:700; font-size:1rem; color:#0f172a;">
                        🚶 Safe Route to High Ground (Shelter Finder)
                    </div>
                    <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                        Intelligent pedestrian and vehicle routing avoiding waterlogged streets.
                    </div>
                </div>
                <span class="chetna-pill chetna-pill-slate">Milestone: Day 4</span>
            </div>
            <div style="background:#f1f5f9; border-radius:6px; padding:12px 14px; margin-bottom:0.85rem;">
                <div style="font-weight:600; font-size:0.84rem; color:#334155; margin-bottom:4px;">
                    ℹ️ Route Calculation Available in a Later Milestone
                </div>
                <p style="margin:0; font-size:0.8rem; color:#64748b; line-height:1.45;">
                    The Chetna routing engine will penalize roads with high water depth or static vulnerability
                    and use A* pathfinding over OpenStreetMap networks to guide residents to the nearest safe shelter.
                </p>
            </div>
            <!-- Wireframe preview of future route steps -->
            <div style="background:#ffffff; border:1px dashed #cbd5e1; border-radius:6px; padding:10px 12px; margin-bottom:0.85rem;">
                <div style="font-size:0.72rem; font-weight:700; text-transform:uppercase; color:#94a3b8; margin-bottom:6px;">
                    PREVIEW OF FUTURE ROUTE GUIDANCE:
                </div>
                <div style="display:flex; flex-direction:column; gap:6px; font-size:0.78rem; color:#475569;">
                    <div><b>1. Current Location:</b> User-selected neighborhood origin</div>
                    <div><b>2. Hazard Avoidance:</b> Automatically bypasses submerged underpasses and canal bottlenecks</div>
                    <div><b>3. Destination:</b> Nearest elevated shelter / MRTS transit concourse</div>
                </div>
            </div>
        """,
        unsafe_allow_html=True,
    )

    st.button("🚶 Calculate Safe Route (Unlocks in Day 4)", disabled=True, use_container_width=True)

    st.markdown(
        """
            <div style="margin-top:0.5rem; font-size:0.73rem; color:#94a3b8; text-align:center;">
                🔒 Safe-route planning logic scheduled for Day 4. No routing calculations performed in Day 1.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_advisory_section() -> None:
    """Render bilingual emergency advisory and alert message foundation (English + Hindi)."""
    messages = get_bilingual_messages()

    st.markdown(
        """
        <div class="chetna-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem; flex-wrap:wrap; gap:8px;">
                <div>
                    <div style="font-weight:700; font-size:1rem; color:#0f172a;">
                        📢 Neighborhood Advisory &amp; Alert Messages (Bilingual)
                    </div>
                    <div style="font-size:0.78rem; color:#64748b; margin-top:2px;">
                        Standard emergency alerts and community safety guidance in English and Hindi.
                    </div>
                </div>
                <span class="chetna-pill chetna-pill-amber">Bilingual Foundation</span>
            </div>
        """,
        unsafe_allow_html=True,
    )

    # State selector: Normal Information vs Scenario Preview
    advisory_state = st.radio(
        "Advisory State:",
        options=["Standard Operational Guidance (Normal)", "Simulated Flood Advisory Preview (Scenario)"],
        index=0,
        horizontal=True,
        help="Toggle between normal information and emergency alert preview.",
    )

    tab_en, tab_hi = st.tabs(["🇬🇧 English", "🇮🇳 हिंदी (Hindi)"])

    with tab_en:
        msg_en = messages["en"]
        if "Normal" in advisory_state:
            st.info(f"ℹ️ {msg_en['normal_summary']}")
        else:
            st.warning(f"⚠️ **{msg_en['sample_advisory_title']}**\n\n{msg_en['sample_advisory_body']}")

        st.markdown("**Essential Community Safety Guidelines:**")
        for tip in msg_en["safety_tips"]:
            st.markdown(f"- {tip}")

    with tab_hi:
        msg_hi = messages["hi"]
        if "Normal" in advisory_state:
            st.info(f"ℹ️ {msg_hi['normal_summary']}")
        else:
            st.warning(f"⚠️ **{msg_hi['sample_advisory_title']}**\n\n{msg_hi['sample_advisory_body']}")

        st.markdown("**आवश्यक सामुदायिक सुरक्षा निर्देश:**")
        for tip in msg_hi["safety_tips"]:
            st.markdown(f"- {tip}")

    st.markdown(
        """
            <div style="margin-top:0.75rem; font-size:0.73rem; color:#94a3b8; border-top:1px solid #f1f5f9; padding-top:0.4rem; text-align:center;">
                ⚠️ Demonstration prototype only. No SMS, WhatsApp, or Telegram messages are being transmitted.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_footer() -> None:
    """Render citizen portal footer and emergency contact numbers."""
    st.markdown(
        """
        <div style="text-align:center; padding:1.25rem 0 0.5rem 0; color:#64748b; font-size:0.75rem; border-top:1px solid #e2e8f0; margin-top:1.25rem;">
            <b>Emergency Helplines (Chennai):</b> GCC Flood Control Room: <b>1913</b> &bull; National Emergency: <b>112</b> &bull; Disaster Helpline: <b>1077</b><br/>
            Chetna Community Flood Safety Portal &bull; IS-12 Project Prototype &bull; Sponsor: Ernst &amp; Young (EY) &bull; Prototype Milestone: F2 Day 1
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_citizen_view(
    folium_map: folium.Map,
    hotspots: List[Dict[str, Any]],
    metrics: Dict[str, Any],
) -> None:
    """Main orchestrator for F2 Day 1 Citizen View."""
    facilities = extract_facilities_from_hotspots(hotspots)

    # 1. Citizen Header with Logo
    render_citizen_header()

    # 2. Prominent Status Card
    render_citizen_status_card()

    # 3. Neighborhood & Horizon Selection Stub
    render_citizen_input_stub(hotspots)

    # 4. Map and At-Risk Facilities in Split Layout
    col_map, col_info = st.columns([65, 35])
    with col_map:
        render_citizen_map(folium_map)
    with col_info:
        render_citizen_facilities_panel(facilities)

    # 5. Safe Route Placeholder & Bilingual Advisory Section
    col_route, col_advisory = st.columns([40, 60])
    with col_route:
        render_citizen_safe_route_placeholder()
    with col_advisory:
        render_citizen_advisory_section()

    # 6. Citizen Footer
    render_citizen_footer()
