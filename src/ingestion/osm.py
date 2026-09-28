"""Chetna OpenStreetMap (OSM) Ingestion Module.

Implements B1 Day 1 requirement for acquiring, caching, and preprocessing
critical spatial layers for the Chennai pilot study area (lat 12.915–13.111, lon 80.064–80.266):
- Roads (major and local transport corridors)
- Hospitals (critical emergency healthcare facilities)
- Schools (community institutions and potential staging sites)
- Shelters (designated emergency shelters and community relief centres)

Ensures:
- Geometries are normalized to WGS 84 (EPSG:4326) for interchange/storage
- Clean reprojection to UTM 44N (EPSG:32644) when metric calculations (lengths, buffers) are required
- Local GeoJSON caching in data/osm/
- Offline fixture fallbacks clearly labelled with 'is_synthetic: True'
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from src.ingestion.pilot_config import (
    GEOGRAPHIC_CRS,
    OSM_PROVENANCE,
    OSM_SOURCE,
    PILOT_BBOX,
    PROJECTED_CRS,
)

logger = logging.getLogger(__name__)

DEFAULT_OSM_CACHE_DIR = Path("data/osm")
FIXTURES_DIR = Path("tests/fixtures")

# OSM Tag Filters
OSM_TAGS: Dict[str, Dict[str, Any]] = {
    "roads": {
        "highway": [
            "motorway",
            "trunk",
            "primary",
            "secondary",
            "tertiary",
            "residential",
            "unclassified",
        ]
    },
    "hospitals": {"amenity": "hospital"},
    "schools": {"amenity": ["school", "college", "university"]},
    "shelters": {"amenity": ["shelter", "community_centre", "social_facility"]},
}


def _clean_gdf_for_geojson(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Flatten non-serializable columns (e.g. lists, dicts) before GeoJSON export."""
    cleaned = gdf.copy()
    for col in cleaned.columns:
        if col == "geometry":
            continue
        # Convert list or dict columns to string representation
        sample_vals = cleaned[col].dropna()
        if len(sample_vals) > 0 and any(isinstance(v, (list, dict)) for v in sample_vals):
            cleaned[col] = cleaned[col].apply(
                lambda v: ", ".join(map(str, v)) if isinstance(v, list) else (str(v) if isinstance(v, dict) else v)
            )
    return cleaned


def download_osm_layer(
    layer_name: str,
    bbox: Optional[Dict[str, float]] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> gpd.GeoDataFrame:
    """Download a spatial layer from OpenStreetMap within the pilot bounding box.

    Parameters
    ----------
    layer_name : str
        One of 'roads', 'hospitals', 'schools', 'shelters'.
    bbox : dict, optional
        Bounding box dict with 'south', 'north', 'west', 'east'. Defaults to PILOT_BBOX.
    output_path : str or Path, optional
        If provided, caches downloaded GeoDataFrame to GeoJSON.

    Returns
    -------
    gpd.GeoDataFrame
        Extracted features in EPSG:4326.
    """
    if layer_name not in OSM_TAGS:
        raise ValueError(f"Unknown layer '{layer_name}'. Available: {list(OSM_TAGS.keys())}")

    if bbox is None:
        bbox = PILOT_BBOX

    tags = OSM_TAGS[layer_name]
    # OSMnx 2.x bbox format is (left, bottom, right, top) = (west, south, east, north)
    bbox_tuple = (bbox["west"], bbox["south"], bbox["east"], bbox["north"])

    logger.info("Downloading OSM layer '%s' from Overpass API for bbox %s", layer_name, bbox_tuple)
    try:
        gdf = ox.features_from_bbox(bbox=bbox_tuple, tags=tags)
    except Exception as e:
        logger.error("OSM download failed for layer '%s': %s", layer_name, e)
        raise RuntimeError(f"Failed to download OSM data for '{layer_name}': {e}") from e

    if gdf is None or len(gdf) == 0:
        logger.warning("OSM query returned 0 features for '%s'", layer_name)
        gdf = gpd.GeoDataFrame(columns=["name", "geometry"], geometry="geometry", crs=GEOGRAPHIC_CRS)
    else:
        # Standardize CRS to EPSG:4326
        if gdf.crs != GEOGRAPHIC_CRS:
            gdf = gdf.to_crs(GEOGRAPHIC_CRS)

        # Standardize element identity
        if isinstance(gdf.index, pd.MultiIndex):
            gdf = gdf.reset_index()

        gdf["source"] = OSM_SOURCE
        gdf["is_synthetic"] = False

        # Extract lat/lon for point/polygon facilities
        if layer_name in ("hospitals", "schools", "shelters"):
            rep_pts = gdf.geometry.representative_point()
            gdf["latitude"] = rep_pts.y.round(6)
            gdf["longitude"] = rep_pts.x.round(6)

        # Calculate metric road length in UTM 44N if road layer
        if layer_name == "roads":
            gdf_metric = gdf.to_crs(PROJECTED_CRS)
            gdf["length_m"] = gdf_metric.geometry.length.round(2)

    cleaned = _clean_gdf_for_geojson(gdf)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        cleaned.to_file(str(out), driver="GeoJSON")
        logger.info("Cached %d features for '%s' to %s", len(cleaned), layer_name, out)

    return cleaned


def create_synthetic_osm_fixtures(
    bbox: Optional[Dict[str, float]] = None,
    output_dir: Union[str, Path] = FIXTURES_DIR,
) -> Dict[str, Path]:
    """Create reproducible synthetic OSM fixtures for roads, hospitals, schools, and shelters.

    Used for automated offline tests to ensure CI runs without external network dependencies.
    All records explicitly have is_synthetic=True.

    Parameters
    ----------
    bbox : dict, optional
        Bounding box. Defaults to PILOT_BBOX.
    output_dir : str or Path
        Output fixtures directory.

    Returns
    -------
    dict
        Paths to generated fixture GeoJSON files.
    """
    if bbox is None:
        bbox = PILOT_BBOX

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    west = bbox["west"]
    south = bbox["south"]
    east = bbox["east"]
    north = bbox["north"]

    paths = {}

    # 1. Hospitals fixture (representative Patna emergency healthcare centers)
    hospital_data = [
        {"osm_id": "mock_hosp_01", "name": "Patna Medical College & Hospital (PMCH)", "amenity": "hospital", "lat": 25.6210, "lon": 85.1580},
        {"osm_id": "mock_hosp_02", "name": "Nalanda Medical College & Hospital (NMCH)", "amenity": "hospital", "lat": 25.5990, "lon": 85.1950},
        {"osm_id": "mock_hosp_03", "name": "All India Institute of Medical Sciences (AIIMS) Patna", "amenity": "hospital", "lat": 25.5630, "lon": 85.0440},
        {"osm_id": "mock_hosp_04", "name": "Indira Gandhi Institute of Medical Sciences (IGIMS)", "amenity": "hospital", "lat": 25.6150, "lon": 85.0870},
        {"osm_id": "mock_hosp_05", "name": "Paras HMRI Hospital", "amenity": "hospital", "lat": 25.6130, "lon": 85.0930},
        {"osm_id": "mock_hosp_06", "name": "Kurji Holy Family Hospital", "amenity": "hospital", "lat": 25.6370, "lon": 85.1120},
    ]
    hosp_gdf = gpd.GeoDataFrame(
        [
            {
                "osm_id": h["osm_id"],
                "name": h["name"],
                "amenity": h["amenity"],
                "latitude": h["lat"],
                "longitude": h["lon"],
                "source": "Patna Reference Infrastructure Dataset",
                "is_synthetic": True,
            }
            for h in hospital_data
        ],
        geometry=[Point(h["lon"], h["lat"]) for h in hospital_data],
        crs=GEOGRAPHIC_CRS,
    )
    hosp_path = out_dir / "osm_hospitals_fixture.geojson"
    hosp_gdf.to_file(str(hosp_path), driver="GeoJSON")
    paths["hospitals"] = hosp_path

    # 2. Schools fixture (Patna colleges and educational institutions)
    school_data = [
        {"osm_id": "mock_sch_01", "name": "Patna College / Patna University", "amenity": "university", "lat": 25.6200, "lon": 85.1690},
        {"osm_id": "mock_sch_02", "name": "St. Xavier's High School Gandhi Maidan", "amenity": "school", "lat": 25.6160, "lon": 85.1410},
        {"osm_id": "mock_sch_03", "name": "Loyola High School Kurji", "amenity": "school", "lat": 25.6360, "lon": 85.1090},
        {"osm_id": "mock_sch_04", "name": "A.N. College Boring Road", "amenity": "college", "lat": 25.6230, "lon": 85.1200},
        {"osm_id": "mock_sch_05", "name": "College of Commerce, Arts and Science", "amenity": "college", "lat": 25.5980, "lon": 85.1610},
        {"osm_id": "mock_sch_06", "name": "Delhi Public School (DPS) Patna", "amenity": "school", "lat": 25.6090, "lon": 85.0520},
    ]
    sch_gdf = gpd.GeoDataFrame(
        [
            {
                "osm_id": s["osm_id"],
                "name": s["name"],
                "amenity": s["amenity"],
                "latitude": s["lat"],
                "longitude": s["lon"],
                "source": "Patna Reference Infrastructure Dataset",
                "is_synthetic": True,
            }
            for s in school_data
        ],
        geometry=[Point(s["lon"], s["lat"]) for s in school_data],
        crs=GEOGRAPHIC_CRS,
    )
    sch_path = out_dir / "osm_schools_fixture.geojson"
    sch_gdf.to_file(str(sch_path), driver="GeoJSON")
    paths["schools"] = sch_path

    # 3. Shelters fixture (elevated transit concourses and public community complexes)
    shelter_data = [
        {"osm_id": "mock_shl_01", "name": "Patna Junction Elevated Concourse", "amenity": "shelter", "lat": 25.6020, "lon": 85.1380},
        {"osm_id": "mock_shl_02", "name": "Moin-ul-Haq Stadium Complex", "amenity": "shelter", "lat": 25.6050, "lon": 85.1680},
        {"osm_id": "mock_shl_03", "name": "Pataliputra Sports Complex Kankarbagh", "amenity": "shelter", "lat": 25.5960, "lon": 85.1550},
        {"osm_id": "mock_shl_04", "name": "Gandhi Maidan Elevated Pavilion", "amenity": "community_centre", "lat": 25.6180, "lon": 85.1430},
        {"osm_id": "mock_shl_05", "name": "Patliputra Junction Elevated Station", "amenity": "shelter", "lat": 25.6250, "lon": 85.0840},
        {"osm_id": "mock_shl_06", "name": "Rajendra Nagar Terminal Concourse", "amenity": "shelter", "lat": 25.5990, "lon": 85.1640},
    ]
    shl_gdf = gpd.GeoDataFrame(
        [
            {
                "osm_id": sh["osm_id"],
                "name": sh["name"],
                "amenity": sh["amenity"],
                "latitude": sh["lat"],
                "longitude": sh["lon"],
                "source": "Patna Reference Infrastructure Dataset",
                "is_synthetic": True,
            }
            for sh in shelter_data
        ],
        geometry=[Point(sh["lon"], sh["lat"]) for sh in shelter_data],
        crs=GEOGRAPHIC_CRS,
    )
    shl_path = out_dir / "osm_shelters_fixture.geojson"
    shl_gdf.to_file(str(shl_path), driver="GeoJSON")
    paths["shelters"] = shl_path

    # 4. Roads fixture (major arterial transport routes across Patna)
    road_lines = [
        # Bailey Road (Jawaharlal Nehru Marg) - East-West spine
        {"osm_id": "mock_road_01", "name": "Bailey Road (Jawaharlal Nehru Marg)", "highway": "trunk", "coords": [(85.060, 25.612), (85.084, 25.612), (85.120, 25.612), (85.140, 25.612)]},
        # Patliputra Station Link
        {"osm_id": "mock_road_01b", "name": "Patliputra Station Road", "highway": "secondary", "coords": [(85.084, 25.612), (85.084, 25.625)]},
        # Frazer Road / Exhibition Road
        {"osm_id": "mock_road_02", "name": "Frazer Road / Exhibition Road", "highway": "primary", "coords": [(85.138, 25.602), (85.140, 25.612), (85.143, 25.618)]},
        # Gandhi Maidan to Ashok Rajpath link
        {"osm_id": "mock_road_02b", "name": "Gandhi Maidan North Connector", "highway": "secondary", "coords": [(85.143, 25.618), (85.143, 25.625)]},
        # Ashok Rajpath - Northern arterial along Ganga
        {"osm_id": "mock_road_03", "name": "Ashok Rajpath", "highway": "primary", "coords": [(85.090, 25.635), (85.130, 25.635), (85.143, 25.625), (85.168, 25.615), (85.220, 25.615)]},
        # Boring Canal Road
        {"osm_id": "mock_road_04", "name": "Boring Canal Road", "highway": "primary", "coords": [(85.120, 25.612), (85.122, 25.622), (85.130, 25.635)]},
        # Kankarbagh Main Road & Railway Overbridge to Patna Jn
        {"osm_id": "mock_road_05", "name": "Kankarbagh Main Road", "highway": "primary", "coords": [(85.138, 25.602), (85.140, 25.595), (85.155, 25.595), (85.164, 25.599), (85.185, 25.595)]},
        # Stadium Link to Ashok Rajpath
        {"osm_id": "mock_road_05b", "name": "Moin-ul-Haq Stadium Connector", "highway": "secondary", "coords": [(85.164, 25.599), (85.168, 25.605), (85.168, 25.615)]},
        # Patna New Bypass (NH 30 / NH 31)
        {"osm_id": "mock_road_06", "name": "Patna Bypass Road (NH 30)", "highway": "trunk", "coords": [(85.080, 25.570), (85.140, 25.570), (85.155, 25.570), (85.220, 25.570)]},
        # Old Bypass / Kankarbagh south link
        {"osm_id": "mock_road_06b", "name": "Old Bypass Connector", "highway": "secondary", "coords": [(85.155, 25.595), (85.155, 25.570)]},
    ]

    road_records = []
    road_geoms = []
    for r in road_lines:
        line = LineString(r["coords"])
        road_geoms.append(line)
        road_records.append(
            {
                "osm_id": r["osm_id"],
                "name": r["name"],
                "highway": r["highway"],
                "source": "Patna Reference Infrastructure Dataset",
                "is_synthetic": True,
            }
        )

    roads_gdf = gpd.GeoDataFrame(road_records, geometry=road_geoms, crs=GEOGRAPHIC_CRS)
    roads_metric = roads_gdf.to_crs(PROJECTED_CRS)
    roads_gdf["length_m"] = roads_metric.geometry.length.round(2)

    roads_path = out_dir / "osm_roads_fixture.geojson"
    roads_gdf.to_file(str(roads_path), driver="GeoJSON")
    paths["roads"] = roads_path

    logger.info("Created synthetic OSM fixtures in %s (is_synthetic=True)", out_dir)
    return paths


def load_osm_layer(
    layer_name: str,
    cache_dir: Union[str, Path] = DEFAULT_OSM_CACHE_DIR,
    fixtures_dir: Union[str, Path] = FIXTURES_DIR,
    fallback_to_fixture: bool = True,
) -> gpd.GeoDataFrame:
    """Load an OSM spatial layer from local cache or fallback test fixture.

    Parameters
    ----------
    layer_name : str
        'roads', 'hospitals', 'schools', or 'shelters'.
    cache_dir : str or Path
        Primary local cache directory (data/osm/).
    fixtures_dir : str or Path
        Test fixtures directory (tests/fixtures/).
    fallback_to_fixture : bool, default True
        If primary cache file does not exist, fall back to fixture.

    Returns
    -------
    gpd.GeoDataFrame
        Loaded spatial layer in EPSG:4326.
    """
    cache_file = Path(cache_dir) / f"chennai_{layer_name}.geojson"
    if cache_file.exists():
        logger.info("Loading cached OSM layer '%s' from %s", layer_name, cache_file)
        return gpd.read_file(str(cache_file))

    if fallback_to_fixture:
        fixture_file = Path(fixtures_dir) / f"osm_{layer_name}_fixture.geojson"
        if fixture_file.exists():
            logger.info("Loading OSM fixture for '%s' from %s", layer_name, fixture_file)
            return gpd.read_file(str(fixture_file))

    raise FileNotFoundError(
        f"OSM layer '{layer_name}' not found at {cache_file} or {fixtures_dir}"
    )


def ingest_all_osm_data(
    bbox: Optional[Dict[str, float]] = None,
    cache_dir: Union[str, Path] = DEFAULT_OSM_CACHE_DIR,
    offline_fallback: bool = True,
) -> Dict[str, gpd.GeoDataFrame]:
    """Ingest or load all 4 OSM layers: roads, hospitals, schools, and shelters.

    Attempts live Overpass API download via OSMnx. If network is unavailable or
    rate-limited and offline_fallback is True, falls back to local fixtures.

    Parameters
    ----------
    bbox : dict, optional
        Bounding box. Defaults to PILOT_BBOX.
    cache_dir : str or Path
        Cache directory for saved GeoJSON files.
    offline_fallback : bool, default True
        Whether to fall back to test fixtures on network/API failure.

    Returns
    -------
    dict
        Dictionary mapping layer name to GeoDataFrame.
    """
    if bbox is None:
        bbox = PILOT_BBOX

    results: Dict[str, gpd.GeoDataFrame] = {}
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    for layer in ["roads", "hospitals", "schools", "shelters"]:
        target_path = cache_path / f"chennai_{layer}.geojson"
        try:
            results[layer] = download_osm_layer(layer, bbox=bbox, output_path=target_path)
        except Exception as e:
            if offline_fallback:
                logger.warning(
                    "Live OSM download for '%s' failed (%s). Falling back to offline fixture.",
                    layer, e
                )
                results[layer] = load_osm_layer(layer, cache_dir=cache_path, fallback_to_fixture=True)
            else:
                raise

    return results
