"""Chetna Frontend Configuration Layer.

Centralizes pilot jurisdiction, hazard scope, and operational branding
for both F1 (Authority Operations Center) and F2 (Citizen Safety Portal).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Pilot Jurisdiction & Hazard Scope
# ---------------------------------------------------------------------------
PILOT_CITY: str = "Patna"
PILOT_STATE: str = "Bihar"
PILOT_COUNTRY: str = "India"
PILOT_LOCATION_LABEL: str = f"{PILOT_CITY}, {PILOT_STATE}"

HAZARD_SCOPE: str = "Rainfall-driven urban flooding and waterlogging"
SYSTEM_NAME: str = "Chetna"
SYSTEM_TAGLINE: str = "Urban Flood Early Warning & Preparedness"

# ---------------------------------------------------------------------------
# F1: Authority Operations Center Configuration
# ---------------------------------------------------------------------------
F1_PORTAL_TITLE: str = "Authority Operations Center"
F1_PORTAL_SUBTITLE: str = f"{PILOT_LOCATION_LABEL} • Disaster Management Authority"
F1_NAV_ITEMS: list[str] = [
    "Overview",
    "Risk Map",
    "Alerts",
    "At-Risk Assets",
    "Sensors",
    "Analytics",
    "Settings",
]

# ---------------------------------------------------------------------------
# F2: Citizen Safety Portal Configuration
# ---------------------------------------------------------------------------
F2_PORTAL_TITLE: str = "Flood Safety"
F2_PORTAL_SUBTITLE: str = f"{PILOT_CITY} Resident Safety & Preparedness Portal"
F2_NAV_ITEMS: list[str] = [
    "My Area",
    "Flood Risk",
    "Safe Places",
    "Safe Route",
    "Advisory",
    "Emergency Help",
]

# ---------------------------------------------------------------------------
# Emergency Contacts & Helplines (Patna, Bihar)
# ---------------------------------------------------------------------------
EMERGENCY_HELPLINES: dict[str, str] = {
    "state_disaster": "1070",              # Bihar State Disaster Management Authority (BSDMA)
    "district_emergency": "1077",          # District Emergency Operation Centre (DEOC Patna)
    "national_emergency": "112",           # National All-in-One Emergency Helpline
    "municipal_control_room": "0612-2200634",  # Patna Municipal Corporation (PMC)
    "ambulance": "108",
}

# ---------------------------------------------------------------------------
# Forecast Horizon Labels
# ---------------------------------------------------------------------------
FORECAST_HORIZONS: list[dict[str, str]] = [
    {"id": "now", "label": "NOW", "description": "Current Telemetry & Radar"},
    {"id": "h1", "label": "+1h", "description": "+1 Hour Outlook"},
    {"id": "h3", "label": "+3h", "description": "+3 Hours Outlook"},
    {"id": "h6", "label": "+6h", "description": "+6 Hours Outlook"},
]
