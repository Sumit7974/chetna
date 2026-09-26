"""Chetna Pilot Area Configuration.

Authoritative constants for the Chennai flood early-warning pilot study.

Coordinate Reference Systems
-----------------------------
Geographic CRS : EPSG:4326  (WGS 84)
    Used for GeoJSON interchange, Open-Meteo API calls, Folium maps,
    and any latitude/longitude representation.

Projected CRS  : EPSG:32644 (WGS 84 / UTM Zone 44N)
    Used for metric grid generation (~200 m cells), distance
    calculations, and any geometry operation that requires metres.
    UTM Zone 44N covers 78°E–84°E which includes Chennai (~80.27°E).

Pilot Bounding Box
------------------
The bounding box encloses all 10 M1 Day 1 waterlogging hotspots
(lat 12.915–13.111, lon 80.064–80.266) with a ~1 km buffer on
each side to ensure edge cells are complete.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Coordinate Reference Systems
# ---------------------------------------------------------------------------

GEOGRAPHIC_CRS: str = "EPSG:4326"
"""WGS 84 geographic CRS for lat/lon coordinates and GeoJSON."""

PROJECTED_CRS: str = "EPSG:32644"
"""WGS 84 / UTM Zone 44N for metric calculations in Chennai."""

UTM_ZONE: int = 44
"""UTM zone number for the pilot area."""

UTM_HEMISPHERE: str = "N"
"""UTM hemisphere for the pilot area."""

# ---------------------------------------------------------------------------
# Pilot Centre (matches app/dashboard.py DEFAULT_COORDINATES)
# ---------------------------------------------------------------------------

PILOT_CENTER_LAT: float = 13.0827
PILOT_CENTER_LON: float = 80.2707
PILOT_CENTER: tuple[float, float] = (PILOT_CENTER_LAT, PILOT_CENTER_LON)

# ---------------------------------------------------------------------------
# Pilot Bounding Box (WGS 84 / EPSG:4326)
# ---------------------------------------------------------------------------
# Chennai pilot study bounds:
#   Latitude:  12.915 – 13.111 N
#   Longitude: 80.064 – 80.266 E

PILOT_BBOX: dict[str, float] = {
    "north": 13.111,
    "south": 12.915,
    "east": 80.266,
    "west": 80.064,
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

# ---------------------------------------------------------------------------
# Grid Parameters
# ---------------------------------------------------------------------------

GRID_RESOLUTION_M: int = 200
"""Target grid cell size in metres."""

GRID_ID_PREFIX: str = "CHETNA_GRID_CHENNAI_200M"
"""Identifier prefix for the production grid (not synthetic)."""

# ---------------------------------------------------------------------------
# Data Provenance
# ---------------------------------------------------------------------------

DEM_SOURCE: str = "Copernicus DEM GLO-30 / SRTM 30m (via OpenTopography or local download)"
DEM_PROVENANCE: str = (
    "Real DEM requires manual download. Fixture data is synthetic "
    "and clearly labelled. See README for download instructions."
)

OSM_SOURCE: str = "OpenStreetMap via Overpass API / OSMnx"
OSM_PROVENANCE: str = (
    "Real OSM data requires network access and osmnx. Fixture data "
    "is synthetic and clearly labelled."
)
