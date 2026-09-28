"""Chetna Pilot Area Configuration.

Authoritative constants for the Patna, Bihar rainfall-driven urban flood early-warning pilot study.

Coordinate Reference Systems
-----------------------------
Geographic CRS : EPSG:4326 (WGS 84)
    Used for GeoJSON interchange, weather API calls, Mapbox/PyDeck maps,
    and any latitude/longitude representation.

Projected CRS  : EPSG:32645 (WGS 84 / UTM Zone 45N)
    Used for metric grid generation (~200 m cells), distance
    calculations, and any geometry operation that requires metres.
    UTM Zone 45N covers 84°E–90°E which includes Patna, Bihar (~85.14°E).

Pilot Bounding Box (Patna Urban Metropolitan Area)
--------------------------------------------------
The bounding box encloses all 10 Patna urban waterlogging hotspots
(lat 25.565–25.655, lon 85.065–85.235) across the south bank of River Ganga,
including Rajendra Nagar, Kankarbagh, Saidpur, Boring Canal, Bailey Road,
and Gandhi Maidan depression basins.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Pilot Jurisdiction
# ---------------------------------------------------------------------------
PILOT_CITY: str = "Patna"
PILOT_STATE: str = "Bihar"
PILOT_COUNTRY: str = "India"
PILOT_LOCATION_LABEL: str = f"{PILOT_CITY}, {PILOT_STATE}"

# ---------------------------------------------------------------------------
# Coordinate Reference Systems
# ---------------------------------------------------------------------------

GEOGRAPHIC_CRS: str = "EPSG:4326"
"""WGS 84 geographic CRS for lat/lon coordinates and GeoJSON."""

PROJECTED_CRS: str = "EPSG:32645"
"""WGS 84 / UTM Zone 45N for metric calculations in Patna, Bihar (84°E–90°E)."""

UTM_ZONE: int = 45
"""UTM zone number for Patna pilot area."""

UTM_HEMISPHERE: str = "N"
"""UTM hemisphere for the pilot area."""

# Historical reference CRS from M1 initial benchmark
HISTORICAL_CHENNAI_PROJECTED_CRS: str = "EPSG:32644"

# ---------------------------------------------------------------------------
# Pilot Centre (Patna Central District / Gandhi Maidan)
# ---------------------------------------------------------------------------

PILOT_CENTER_LAT: float = 25.6093
PILOT_CENTER_LON: float = 85.1376
PILOT_CENTER: tuple[float, float] = (PILOT_CENTER_LAT, PILOT_CENTER_LON)

# ---------------------------------------------------------------------------
# Pilot Bounding Box (WGS 84 / EPSG:4326)
# ---------------------------------------------------------------------------
# Patna urban pilot study bounds:
#   Latitude:  25.565 – 25.655 N
#   Longitude: 85.065 – 85.235 E

PILOT_BBOX: dict[str, float] = {
    "north": 25.655,
    "south": 25.565,
    "east": 85.235,
    "west": 85.050,
}

PILOT_BBOX_TUPLE: tuple[float, float, float, float] = (
    PILOT_BBOX["south"],
    PILOT_BBOX["north"],
    PILOT_BBOX["west"],
    PILOT_BBOX["east"],
)
"""(south, north, west, east) convenience tuple."""

PILOT_BBOX_MINX_MINY_MAXX_MAXY: tuple[float, float, float, float] = (
    PILOT_BBOX["west"],
    PILOT_BBOX["south"],
    PILOT_BBOX["east"],
    PILOT_BBOX["north"],
)
"""(min_lon, min_lat, max_lon, max_lat) standard GIS envelope."""

# Historical reference bounding box (M1 initial benchmark study)
HISTORICAL_CHENNAI_BBOX: dict[str, float] = {
    "north": 13.111,
    "south": 12.915,
    "east": 80.266,
    "west": 80.064,
}

# ---------------------------------------------------------------------------
# Grid Parameters
# ---------------------------------------------------------------------------

GRID_RESOLUTION_M: int = 200
"""Target grid cell size in metres."""

GRID_ID_PREFIX: str = "CHETNA_GRID_PATNA_200M"
"""Identifier prefix for the Patna production grid."""

# ---------------------------------------------------------------------------
# Data Provenance
# ---------------------------------------------------------------------------

DEM_SOURCE: str = "Copernicus DEM GLO-30 / SRTM 30m (Patna Metropolitan Quadrangle)"
DEM_PROVENANCE: str = (
    "Reference digital elevation model for Patna urban plains (48m–55m AMSL). "
    "Synthetic fixture calibrated to Gangetic levee and southern saucer basins."
)

OSM_SOURCE: str = "OpenStreetMap via Overpass API / OSMnx (Patna Urban Jurisdiction)"
OSM_PROVENANCE: str = (
    "Reference infrastructure for Patna (PMCH, NMCH, Patna Junction Elevated Concourse, "
    "Moin-ul-Haq Stadium, Bailey Road, Kankarbagh Main Road)."
)

