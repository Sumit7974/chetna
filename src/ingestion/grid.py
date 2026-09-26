"""Chetna 200m Metric Grid Generator.

Implements B1 Day 1 requirement for a uniform, deterministic, approximately 200 m
grid covering the Chennai pilot study area (lat 12.915–13.111, lon 80.064–80.266).

Uses UTM Zone 44N (EPSG:32644) as the authoritative projected CRS for metric calculations
and WGS 84 (EPSG:4326) for interchange, storage, and GeoJSON representation.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pyproj
import shapely.geometry
from shapely.geometry import Polygon, box

from src.ingestion.pilot_config import (
    GEOGRAPHIC_CRS,
    GRID_ID_PREFIX,
    GRID_RESOLUTION_M,
    PILOT_BBOX,
    PROJECTED_CRS,
)

logger = logging.getLogger(__name__)


def generate_pilot_grid(
    bbox: Optional[Dict[str, float]] = None,
    resolution_m: float = GRID_RESOLUTION_M,
    geographic_crs: str = GEOGRAPHIC_CRS,
    projected_crs: str = PROJECTED_CRS,
) -> gpd.GeoDataFrame:
    """Generate a regular, deterministic 200 m metric grid over the pilot bounding box.

    Parameters
    ----------
    bbox : dict, optional
        Bounding box dict with keys 'south', 'north', 'west', 'east' in EPSG:4326 degrees.
        Defaults to PILOT_BBOX (lat 12.915–13.111, lon 80.064–80.266).
    resolution_m : float, default 200.0
        Cell edge length in metres in the projected CRS.
    geographic_crs : str, default "EPSG:4326"
        Source and output geographic CRS (WGS 84).
    projected_crs : str, default "EPSG:32644"
        Authoritative projected CRS (UTM 44N) for metric calculations.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame in geographic_crs containing all grid cells.
        Columns:
            - cell_id: Unique deterministic ID (CELL_R{row:03d}_C{col:03d})
            - row: Integer row index (from south to north)
            - col: Integer column index (from west to east)
            - centroid_lat: Latitude of cell centroid in WGS 84
            - centroid_lon: Longitude of cell centroid in WGS 84
            - resolution_m: Nominal cell edge size (200.0 m)
            - crs: Output CRS identifier ("EPSG:4326")
            - projected_crs: Projected metric CRS identifier ("EPSG:32644")
            - geometry: Polygon in EPSG:4326
    """
    if bbox is None:
        bbox = PILOT_BBOX

    south = float(bbox["south"])
    north = float(bbox["north"])
    west = float(bbox["west"])
    east = float(bbox["east"])

    if south >= north:
        raise ValueError(f"Invalid latitude bounds: south ({south}) must be less than north ({north})")
    if west >= east:
        raise ValueError(f"Invalid longitude bounds: west ({west}) must be less than east ({east})")

    # 1. Transform WGS84 bounding box corners to projected metric CRS (EPSG:32644)
    to_utm = pyproj.Transformer.from_crs(geographic_crs, projected_crs, always_xy=True)
    to_wgs = pyproj.Transformer.from_crs(projected_crs, geographic_crs, always_xy=True)

    min_x, min_y = to_utm.transform(west, south)
    max_x, max_y = to_utm.transform(east, north)

    # 2. Compute coordinate sequences with exact step resolution_m
    x_steps = np.arange(min_x, max_x, resolution_m)
    y_steps = np.arange(min_y, max_y, resolution_m)

    n_cols = len(x_steps)
    n_rows = len(y_steps)

    logger.info(
        "Generating grid for bounds [%.4f, %.4f, %.4f, %.4f]: %d rows x %d cols = %d cells",
        west, south, east, north, n_rows, n_cols, n_rows * n_cols
    )

    # 3. Create regular square polygon boxes and attributes
    polygons_utm = []
    cell_ids = []
    rows = []
    cols = []
    centroid_lats = []
    centroid_lons = []

    for r_idx, y in enumerate(y_steps):
        for c_idx, x in enumerate(x_steps):
            cell_box = box(x, y, x + resolution_m, y + resolution_m)
            c_x = x + (resolution_m / 2.0)
            c_y = y + (resolution_m / 2.0)
            c_lon, c_lat = to_wgs.transform(c_x, c_y)

            cell_ids.append(f"CELL_R{r_idx:03d}_C{c_idx:03d}")
            rows.append(r_idx)
            cols.append(c_idx)
            centroid_lats.append(round(c_lat, 6))
            centroid_lons.append(round(c_lon, 6))
            polygons_utm.append(cell_box)

    # 4. Construct GeoDataFrame in projected CRS, then reproject to EPSG:4326 for interchange
    gdf_utm = gpd.GeoDataFrame(
        {
            "cell_id": cell_ids,
            "row": rows,
            "col": cols,
            "centroid_lat": centroid_lats,
            "centroid_lon": centroid_lons,
            "resolution_m": [float(resolution_m)] * len(cell_ids),
            "crs": [geographic_crs] * len(cell_ids),
            "projected_crs": [projected_crs] * len(cell_ids),
        },
        geometry=polygons_utm,
        crs=projected_crs,
    )

    # Reproject to WGS 84
    gdf_wgs84 = gdf_utm.to_crs(geographic_crs)
    return gdf_wgs84


def save_grid_geojson(
    gdf: gpd.GeoDataFrame,
    output_path: Union[str, Path] = "data/b1/grid_200m.geojson",
) -> Path:
    """Save grid GeoDataFrame to GeoJSON file with directory creation.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Grid GeoDataFrame.
    output_path : str or Path
        Destination path.

    Returns
    -------
    Path
        Resolved destination path.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(path), driver="GeoJSON")
    logger.info("Saved %d grid cells to %s", len(gdf), path)
    return path


def load_grid_geojson(
    input_path: Union[str, Path] = "data/b1/grid_200m.geojson",
) -> gpd.GeoDataFrame:
    """Load grid GeoDataFrame from GeoJSON file."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Grid GeoJSON not found at {path}")
    return gpd.read_file(str(path))


def validate_grid(
    gdf: gpd.GeoDataFrame,
    expected_resolution_m: float = GRID_RESOLUTION_M,
    tolerance_m: float = 5.0,
) -> Dict[str, Any]:
    """Validate grid cell count, dimensions, geometry validity, and coverage.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Grid GeoDataFrame to validate.
    expected_resolution_m : float, default 200.0
        Expected edge resolution in metres.
    tolerance_m : float, default 5.0
        Allowable tolerance in metres for reprojection distortion.

    Returns
    -------
    dict
        Summary of validation metrics.
    """
    total_cells = len(gdf)
    if total_cells == 0:
        raise ValueError("Grid is empty")

    # Verify geometries are valid polygons
    is_valid = gdf.geometry.is_valid.all()
    if not is_valid:
        invalid_count = (~gdf.geometry.is_valid).sum()
        raise ValueError(f"Grid contains {invalid_count} invalid geometries")

    # Project to metric CRS to verify metric cell area and side length
    projected = gdf.to_crs(PROJECTED_CRS)
    areas = projected.geometry.area
    expected_area = expected_resolution_m * expected_resolution_m
    mean_area = float(areas.mean())

    area_diff = abs(mean_area - expected_area)
    if area_diff > (expected_resolution_m * tolerance_m):
        raise ValueError(
            f"Mean cell area ({mean_area:.1f} m²) differs from expected ({expected_area:.1f} m²)"
        )

    return {
        "valid": True,
        "cell_count": total_cells,
        "mean_area_m2": round(mean_area, 2),
        "expected_area_m2": expected_area,
        "bounds": gdf.total_bounds.tolist(),
        "crs": str(gdf.crs),
    }
