"""Chetna B1 Day 1 Ingestion and Preprocessing Pipeline Script.

Executes the complete geospatial data preparation workflow for the Chennai pilot study:
1. Generates deterministic ~200 m metric grid (UTM 44N / EPSG:32644 reprojected to EPSG:4326)
2. Ingests DEM elevation raster and samples elevation per grid cell
3. Ingests OSM critical infrastructure (roads, hospitals, schools, shelters)
4. Persists spatial layers to SQLite database (data/chetna.db) and GeoJSON files
5. Records spatial metadata and provenance

Usage:
------
# Run with offline fixtures (no API keys or external network required):
python scripts/ingest_b1_data.py

# Optional: Run live OSM download (requires network):
python scripts/ingest_b1_data.py --live-osm

# Optional: Run live DEM download (requires OPENTOPOGRAPHY_API_KEY env var):
python scripts/ingest_b1_data.py --live-dem
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.forecasts import DEFAULT_DB_PATH
from src.db.spatial import (
    init_spatial_db,
    record_spatial_metadata,
    save_facilities,
    save_grid_cells,
    save_roads,
)
from src.ingestion.dem import (
    attach_elevation_to_grid,
    create_synthetic_dem_fixture,
    download_dem_opentopography,
    load_dem_metadata,
)
from src.ingestion.grid import (
    generate_pilot_grid,
    save_grid_geojson,
    validate_grid,
)
from src.ingestion.osm import (
    create_synthetic_osm_fixtures,
    ingest_all_osm_data,
    load_osm_layer,
)
from src.ingestion.pilot_config import (
    DEM_SOURCE,
    GEOGRAPHIC_CRS,
    GRID_RESOLUTION_M,
    OSM_SOURCE,
    PILOT_BBOX,
    PROJECTED_CRS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_b1_pipeline(
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = Path("data/b1"),
    live_dem: bool = False,
    live_osm: bool = False,
) -> Dict[str, Any]:
    """Execute the full B1 Day 1 data preparation pipeline.

    Parameters
    ----------
    db_path : Path
        Target SQLite database path.
    output_dir : Path
        Directory for exported GeoJSON files.
    live_dem : bool
        Attempt live download of DEM via OpenTopography API.
    live_osm : bool
        Attempt live download of OSM layers via OSMnx.

    Returns
    -------
    dict
        Pipeline execution summary.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dem_dir = Path("data/dem")
    dem_dir.mkdir(parents=True, exist_ok=True)
    osm_dir = Path("data/osm")
    osm_dir.mkdir(parents=True, exist_ok=True)

    logger.info("==================================================")
    logger.info("Starting Chetna B1 Day 1 Geospatial Pipeline")
    logger.info("Pilot Bounds: lat %.4f–%.4f, lon %.4f–%.4f", PILOT_BBOX["south"], PILOT_BBOX["north"], PILOT_BBOX["west"], PILOT_BBOX["east"])
    logger.info("Authoritative CRS: Geographic=%s, Metric Projected=%s", GEOGRAPHIC_CRS, PROJECTED_CRS)
    logger.info("Target Grid Resolution: %d m", GRID_RESOLUTION_M)
    logger.info("Database Path: %s", db_path)
    logger.info("==================================================")

    # Step 1: Initialize SQLite Database
    logger.info("[1/5] Initializing SQLite spatial database schema...")
    init_spatial_db(db_path)

    # Step 2: Generate ~200 m Metric Grid
    logger.info("[2/5] Generating ~200 m metric grid...")
    grid_gdf = generate_pilot_grid(bbox=PILOT_BBOX, resolution_m=GRID_RESOLUTION_M)
    grid_val = validate_grid(grid_gdf)
    logger.info("Generated %d cells (mean area=%.1f m²)", len(grid_gdf), grid_val["mean_area_m2"])

    # Step 3: Ingest DEM & Attach Elevation
    logger.info("[3/5] Ingesting DEM elevation data...")
    dem_path = dem_dir / "chennai_dem_30m.tif"
    is_dem_synthetic = False

    if live_dem:
        logger.info("Downloading live DEM from OpenTopography...")
        try:
            download_dem_opentopography(bbox=PILOT_BBOX, output_path=dem_path)
        except Exception as e:
            logger.warning("Live DEM download failed (%s). Falling back to synthetic fixture.", e)
            dem_path = Path("tests/fixtures/chennai_dem_fixture.tif")
            if not dem_path.exists():
                create_synthetic_dem_fixture(PILOT_BBOX, dem_path)
            is_dem_synthetic = True
    elif dem_path.exists():
        logger.info("Using existing local DEM raster: %s", dem_path)
    else:
        logger.info("Using synthetic DEM test fixture (offline mode)...")
        dem_path = Path("tests/fixtures/chennai_dem_fixture.tif")
        if not dem_path.exists():
            create_synthetic_dem_fixture(PILOT_BBOX, dem_path)
        is_dem_synthetic = True

    dem_meta = load_dem_metadata(dem_path)
    is_dem_synthetic = is_dem_synthetic or dem_meta.get("is_synthetic", False)

    grid_gdf = attach_elevation_to_grid(grid_gdf, dem_path, elevation_column="elevation_m")

    # Save grid cells to GeoJSON and SQLite
    grid_geojson_path = output_dir / "grid_200m.geojson"
    save_grid_geojson(grid_gdf, grid_geojson_path)
    saved_cells = save_grid_cells(grid_gdf, db_path)

    record_spatial_metadata(
        dataset_name="grid_200m",
        source=DEM_SOURCE if not is_dem_synthetic else "Chetna Synthetic DEM Test Fixture",
        crs=GEOGRAPHIC_CRS,
        bounds=grid_val["bounds"],
        record_count=saved_cells,
        is_synthetic=is_dem_synthetic,
        provenance=f"200m metric grid derived from UTM 44N with elevation sampled from {dem_path.name}",
        db_path=db_path,
    )

    # Step 4: Ingest OSM Layers
    logger.info("[4/5] Ingesting OSM spatial layers (roads, hospitals, schools, shelters)...")
    create_synthetic_osm_fixtures(PILOT_BBOX)

    osm_layers = {}
    for layer in ["roads", "hospitals", "schools", "shelters"]:
        target_geojson = osm_dir / f"chennai_{layer}.geojson"
        if live_osm:
            try:
                osm_layers[layer] = load_osm_layer(layer, cache_dir=osm_dir, fallback_to_fixture=True)
            except Exception as e:
                logger.warning("Could not download live OSM for '%s' (%s). Using fixture.", layer, e)
                osm_layers[layer] = load_osm_layer(layer, fallback_to_fixture=True)
        else:
            osm_layers[layer] = load_osm_layer(layer, cache_dir=osm_dir, fallback_to_fixture=True)

    # Step 5: Persist OSM Layers to SQLite
    logger.info("[5/5] Persisting OSM layers to SQLite database...")
    roads_gdf = osm_layers["roads"]
    is_roads_synth = bool(roads_gdf["is_synthetic"].any()) if "is_synthetic" in roads_gdf else False
    saved_roads = save_roads(roads_gdf, db_path, is_synthetic=is_roads_synth)
    record_spatial_metadata(
        dataset_name="roads",
        source=OSM_SOURCE if not is_roads_synth else "Synthetic OSM Test Fixture",
        crs=GEOGRAPHIC_CRS,
        record_count=saved_roads,
        is_synthetic=is_roads_synth,
        provenance="Road network for pilot area from OpenStreetMap",
        db_path=db_path,
    )

    for facility_cat in ["hospitals", "schools", "shelters"]:
        fac_gdf = osm_layers[facility_cat]
        is_fac_synth = bool(fac_gdf["is_synthetic"].any()) if "is_synthetic" in fac_gdf else False
        saved_fac = save_facilities(fac_gdf, facility_cat, db_path, is_synthetic=is_fac_synth)
        record_spatial_metadata(
            dataset_name=facility_cat,
            source=OSM_SOURCE if not is_fac_synth else "Synthetic OSM Test Fixture",
            crs=GEOGRAPHIC_CRS,
            record_count=saved_fac,
            is_synthetic=is_fac_synth,
            provenance=f"{facility_cat.capitalize()} extracted from OpenStreetMap",
            db_path=db_path,
        )

    summary = {
        "grid_cells_count": saved_cells,
        "grid_geojson": str(grid_geojson_path),
        "dem_path": str(dem_path),
        "dem_is_synthetic": is_dem_synthetic,
        "roads_count": saved_roads,
        "hospitals_count": len(osm_layers["hospitals"]),
        "schools_count": len(osm_layers["schools"]),
        "shelters_count": len(osm_layers["shelters"]),
        "db_path": str(db_path),
    }

    logger.info("==================================================")
    logger.info("Chetna B1 Day 1 Pipeline Complete:")
    logger.info("  - Grid Cells: %d stored in DB & %s", summary["grid_cells_count"], grid_geojson_path)
    logger.info("  - DEM: %s (synthetic=%s)", dem_path.name, is_dem_synthetic)
    logger.info("  - Roads: %d records", summary["roads_count"])
    logger.info("  - Hospitals: %d records", summary["hospitals_count"])
    logger.info("  - Schools: %d records", summary["schools_count"])
    logger.info("  - Shelters: %d records", summary["shelters_count"])
    logger.info("==================================================")
    return summary


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Chetna B1 Day 1 Geospatial Ingestion Pipeline")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--output-dir", type=Path, default=Path("data/b1"), help="Directory for exported GeoJSON files")
    parser.add_argument("--live-dem", action="store_true", help="Download live DEM via OpenTopography API")
    parser.add_argument("--live-osm", action="store_true", help="Download live OSM layers via OSMnx")
    args = parser.parse_args()

    run_b1_pipeline(
        db_path=args.db_path,
        output_dir=args.output_dir,
        live_dem=args.live_dem,
        live_osm=args.live_osm,
    )


if __name__ == "__main__":
    main()
