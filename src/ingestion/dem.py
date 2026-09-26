"""Chetna DEM / Elevation Ingestion and Preprocessing Module.

Implements B1 Day 1 requirement for digital elevation model (DEM) ingestion,
caching, validation, and elevation extraction for the ~200 m Chennai pilot grid.

Supports:
- Local GeoTIFF DEM raster files (Copernicus DEM GLO-30 / SRTM 30m)
- OpenTopography / public API download mechanisms with clear error handling
- Rasterio-based coordinate sampling and grid cell elevation assignment
- Offline test fixture generation with explicit 'is_synthetic' attribution
"""

from __future__ import annotations

import logging
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import affine
import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from rasterio.crs import CRS
from rasterio.sample import sample_gen
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import Point

from src.ingestion.pilot_config import (
    DEM_PROVENANCE,
    DEM_SOURCE,
    GEOGRAPHIC_CRS,
    PILOT_BBOX,
    PROJECTED_CRS,
)

logger = logging.getLogger(__name__)

DEFAULT_DEM_DIR = Path("data/dem")
DEFAULT_DEM_PATH = DEFAULT_DEM_DIR / "chennai_dem_30m.tif"


def download_dem_opentopography(
    bbox: Optional[Dict[str, float]] = None,
    output_path: Union[str, Path] = DEFAULT_DEM_PATH,
    api_key: Optional[str] = None,
    dem_type: str = "COP30",
) -> Path:
    """Download digital elevation model raster from OpenTopography API.

    Parameters
    ----------
    bbox : dict, optional
        Bounding box dict with 'south', 'north', 'west', 'east'. Defaults to PILOT_BBOX.
    output_path : str or Path
        Destination GeoTIFF path.
    api_key : str, optional
        OpenTopography API key. If not provided, inspects OPENTOPOGRAPHY_API_KEY env var.
    dem_type : str, default "COP30"
        DEM product ("COP30" for Copernicus 30m, or "SRTMGL1" for SRTM 30m).

    Returns
    -------
    Path
        Path to downloaded GeoTIFF file.
    """
    if bbox is None:
        bbox = PILOT_BBOX

    key = api_key or os.environ.get("OPENTOPOGRAPHY_API_KEY")
    if not key:
        raise ValueError(
            "OpenTopography API key is required to download global DEMs. "
            "Set OPENTOPOGRAPHY_API_KEY environment variable or download Copernicus DEM GLO-30 "
            f"manually and place the GeoTIFF at: {output_path}"
        )

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    base_url = "https://portal.opentopography.org/API/globaldem"
    params = {
        "demtype": dem_type,
        "south": bbox["south"],
        "north": bbox["north"],
        "west": bbox["west"],
        "east": bbox["east"],
        "outputFormat": "GTiff",
        "API_Key": key,
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    logger.info("Requesting DEM from OpenTopography: %s (bbox=%s)", dem_type, bbox)

    req = urllib.request.Request(url, headers={"User-Agent": "ChetnaFloodEarlyWarning/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(out_file, "wb") as f:
            f.write(resp.read())
        logger.info("Successfully downloaded DEM raster to %s", out_file)
        return out_file
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"OpenTopography HTTP error {e.code}: {e.reason}. Verify your API key and bounds."
        ) from e
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Network connection failed while downloading DEM from OpenTopography: {e.reason}"
        ) from e


def create_synthetic_dem_fixture(
    bbox: Optional[Dict[str, float]] = None,
    output_path: Union[str, Path] = "tests/fixtures/chennai_dem_fixture.tif",
    width: int = 120,
    height: int = 120,
) -> Path:
    """Create a clearly-labeled synthetic DEM GeoTIFF for testing and offline development.

    Models Chennai's general topography: coastal lowlands (2–5 m) in the east
    gently rising to upland plateaus (20–30 m) in the west/southwest.

    Parameters
    ----------
    bbox : dict, optional
        Bounding box. Defaults to PILOT_BBOX.
    output_path : str or Path
        Destination GeoTIFF path.
    width : int
        Number of pixel columns.
    height : int
        Number of pixel rows.

    Returns
    -------
    Path
        Path to generated fixture GeoTIFF.
    """
    if bbox is None:
        bbox = PILOT_BBOX

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    west = bbox["west"]
    south = bbox["south"]
    east = bbox["east"]
    north = bbox["north"]

    res_x = (east - west) / width
    res_y = (north - south) / height

    # Affine transform for pixel-to-world mapping: top-left corner is (west, north)
    transform = affine.Affine(res_x, 0.0, west, 0.0, -res_y, north)

    # Generate synthetic elevation: sloping west-to-east towards Bay of Bengal
    x_grid = np.linspace(0.0, 1.0, width)
    y_grid = np.linspace(0.0, 1.0, height)
    xx, yy = np.meshgrid(x_grid, y_grid)

    # Elevation: ~28m in west falling to ~2.5m at coast (east), with local undulations
    elevations = (1.0 - xx) * 25.0 + 3.0 + np.sin(xx * 10.0) * 1.5 + np.cos(yy * 8.0) * 1.0
    elevations = elevations.astype(np.float32)

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "nodata": -9999.0,
        "width": width,
        "height": height,
        "count": 1,
        "crs": CRS.from_string(GEOGRAPHIC_CRS),
        "transform": transform,
    }

    with rasterio.open(out_file, "w", **profile) as dst:
        dst.write(elevations, 1)
        dst.update_tags(
            is_synthetic="true",
            source="Chetna Synthetic DEM Test Fixture",
            provenance="Procedural gradient for Chennai pilot area offline tests",
        )

    logger.info("Created synthetic DEM fixture at %s (is_synthetic=True)", out_file)
    return out_file


def load_dem_metadata(raster_path: Union[str, Path]) -> Dict[str, Any]:
    """Inspect DEM raster file and return metadata, CRS, bounds, and statistics."""
    path = Path(raster_path)
    if not path.exists():
        raise FileNotFoundError(f"DEM raster file not found: {path}")

    with rasterio.open(path) as src:
        bounds = src.bounds
        crs_str = src.crs.to_string() if src.crs else "Unknown"
        data = src.read(1)
        nodata = src.nodata

        if nodata is not None:
            valid_mask = data != nodata
        else:
            valid_mask = np.isfinite(data)

        valid_elev = data[valid_mask]
        min_elev = float(np.min(valid_elev)) if len(valid_elev) > 0 else None
        max_elev = float(np.max(valid_elev)) if len(valid_elev) > 0 else None
        mean_elev = float(np.mean(valid_elev)) if len(valid_elev) > 0 else None

        tags = src.tags()
        is_synthetic = tags.get("is_synthetic", "false").lower() == "true"

        return {
            "path": str(path.resolve()),
            "crs": crs_str,
            "width": src.width,
            "height": src.height,
            "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
            "nodata": nodata,
            "min_elevation_m": min_elev,
            "max_elevation_m": max_elev,
            "mean_elevation_m": mean_elev,
            "is_synthetic": is_synthetic,
            "tags": tags,
        }


def attach_elevation_to_grid(
    grid_gdf: gpd.GeoDataFrame,
    dem_path: Union[str, Path],
    elevation_column: str = "elevation_m",
) -> gpd.GeoDataFrame:
    """Sample DEM raster at cell centroids and attach elevation values to grid cells.

    Parameters
    ----------
    grid_gdf : gpd.GeoDataFrame
        Grid GeoDataFrame with geometry and centroid coordinates.
    dem_path : str or Path
        Path to local DEM raster GeoTIFF.
    elevation_column : str, default "elevation_m"
        Name of column to assign elevation values.

    Returns
    -------
    gpd.GeoDataFrame
        Updated GeoDataFrame with the new elevation column.
    """
    path = Path(dem_path)
    if not path.exists():
        raise FileNotFoundError(f"DEM raster not found at {path}")

    gdf = grid_gdf.copy()

    with rasterio.open(path) as src:
        dem_crs = src.crs
        nodata = src.nodata

        # Ensure centroids are transformed to DEM raster CRS cleanly
        if "centroid_lon" in gdf.columns and "centroid_lat" in gdf.columns:
            pts = [Point(xy) for xy in zip(gdf["centroid_lon"], gdf["centroid_lat"])]
            centroid_series = gpd.GeoSeries(pts, crs=GEOGRAPHIC_CRS)
            if dem_crs and centroid_series.crs != dem_crs:
                centroids_dem = centroid_series.to_crs(dem_crs)
            else:
                centroids_dem = centroid_series
        else:
            metric_gdf = gdf.to_crs(PROJECTED_CRS)
            metric_centroids = metric_gdf.geometry.centroid
            if dem_crs:
                centroids_dem = metric_centroids.to_crs(dem_crs)
            else:
                centroids_dem = metric_centroids

        coords = [(pt.x, pt.y) for pt in centroids_dem]
        sampled_values = [val[0] for val in sample_gen(src, coords)]

        # Clean nodata values (replace with NaN or interpolate)
        elevations = []
        for v in sampled_values:
            val = float(v)
            if nodata is not None and math.isclose(val, nodata, abs_tol=1e-3):
                elevations.append(np.nan)
            elif not np.isfinite(val):
                elevations.append(np.nan)
            else:
                elevations.append(round(val, 2))

        gdf[elevation_column] = elevations

    # If any cell has NaN due to raster edge bounds, impute with mean valid elevation
    valid_elevs = gdf[elevation_column].dropna()
    if len(valid_elevs) > 0 and gdf[elevation_column].isna().any():
        mean_val = round(float(valid_elevs.mean()), 2)
        gdf[elevation_column] = gdf[elevation_column].fillna(mean_val)

    logger.info(
        "Attached elevation from %s to %d grid cells (min=%.2f m, max=%.2f m, mean=%.2f m)",
        path.name,
        len(gdf),
        gdf[elevation_column].min(),
        gdf[elevation_column].max(),
        gdf[elevation_column].mean(),
    )
    return gdf
