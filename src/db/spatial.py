"""SQLite Spatial Database Schema and Operations for Chetna B1 Day 1.

Extends the Chetna SQLite database to support:
- ~200 m metric grid cells with centroid coordinates and elevation
- Critical infrastructure layers: roads, hospitals, schools, shelters
- Spatial dataset metadata and provenance tracking

Follows Chetna database guidelines:
- Does NOT drop or alter existing forecast tables or records
- Uses safe, idempotent schema creation
- Supports GeoDataFrame and dict input/output with GeoJSON serialization
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely.geometry
from shapely.geometry import shape

from src.db.forecasts import DEFAULT_DB_PATH, get_db_connection, init_db
from src.ingestion.pilot_config import PROJECTED_CRS

logger = logging.getLogger(__name__)

# SQL DDL for Spatial Tables
CREATE_GRID_CELLS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS grid_cells (
    cell_id TEXT PRIMARY KEY,
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    centroid_lat REAL NOT NULL,
    centroid_lon REAL NOT NULL,
    elevation_m REAL,
    geometry_geojson TEXT NOT NULL,
    crs TEXT NOT NULL DEFAULT 'EPSG:4326',
    projected_crs TEXT NOT NULL DEFAULT '{PROJECTED_CRS}',
    resolution_m REAL NOT NULL DEFAULT 200.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_GRID_CELLS_INDICES_SQL = """
CREATE INDEX IF NOT EXISTS idx_grid_cells_row_col ON grid_cells (row, col);
CREATE INDEX IF NOT EXISTS idx_grid_cells_coords ON grid_cells (centroid_lat, centroid_lon);
"""

CREATE_ROADS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS roads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id TEXT,
    name TEXT,
    highway TEXT,
    length_m REAL,
    geometry_geojson TEXT NOT NULL,
    source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_roads_highway ON roads (highway);
"""

CREATE_HOSPITALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hospitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id TEXT,
    name TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    geometry_geojson TEXT NOT NULL,
    source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_hospitals_coords ON hospitals (latitude, longitude);
"""

CREATE_SCHOOLS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id TEXT,
    name TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    geometry_geojson TEXT NOT NULL,
    source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_schools_coords ON schools (latitude, longitude);
"""

CREATE_SHELTERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS shelters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id TEXT,
    name TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    geometry_geojson TEXT NOT NULL,
    source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_shelters_coords ON shelters (latitude, longitude);
"""

CREATE_SPATIAL_METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS spatial_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    crs TEXT NOT NULL,
    bounds TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    is_synthetic BOOLEAN NOT NULL DEFAULT 0,
    provenance TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_spatial_db(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> None:
    """Initialize the spatial tables and indices idempotently.

    Ensures both forecast tables and spatial tables exist without altering data.
    """
    # Initialize forecast tables first
    init_db(db_path)

    with get_db_connection(db_path) as conn:
        with conn:
            conn.execute(CREATE_GRID_CELLS_TABLE_SQL)
            for stmt in CREATE_GRID_CELLS_INDICES_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            for stmt in CREATE_ROADS_TABLE_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            for stmt in CREATE_HOSPITALS_TABLE_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            for stmt in CREATE_SCHOOLS_TABLE_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            for stmt in CREATE_SHELTERS_TABLE_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            conn.execute(CREATE_SPATIAL_METADATA_TABLE_SQL)

    logger.debug("Initialized Chetna spatial tables in %s", db_path)


def save_grid_cells(
    grid_gdf: Union[gpd.GeoDataFrame, List[Dict[str, Any]]],
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Save grid cells to the SQLite database.

    Parameters
    ----------
    grid_gdf : gpd.GeoDataFrame or list of dicts
        Grid cells with cell_id, row, col, centroid_lat, centroid_lon, geometry.
    db_path : Path or connection
        Target database.

    Returns
    -------
    int
        Number of cells saved.
    """
    init_spatial_db(db_path)

    records = []
    if isinstance(grid_gdf, gpd.GeoDataFrame):
        for _, row in grid_gdf.iterrows():
            geom_json = shapely.to_geojson(row["geometry"])
            elev = row.get("elevation_m")
            elev_val = float(elev) if elev is not None and not np.isnan(elev) else None
            records.append(
                (
                    str(row["cell_id"]),
                    int(row["row"]),
                    int(row["col"]),
                    float(row["centroid_lat"]),
                    float(row["centroid_lon"]),
                    elev_val,
                    geom_json,
                    str(row.get("crs", "EPSG:4326")),
                    str(row.get("projected_crs", PROJECTED_CRS)),
                    float(row.get("resolution_m", 200.0)),
                )
            )
    else:
        for r in grid_gdf:
            geom = r.get("geometry")
            geom_json = json.dumps(geom) if isinstance(geom, dict) else (shapely.to_geojson(geom) if hasattr(geom, "__geo_interface__") else str(geom))
            elev = r.get("elevation_m")
            elev_val = float(elev) if elev is not None else None
            records.append(
                (
                    str(r["cell_id"]),
                    int(r["row"]),
                    int(r["col"]),
                    float(r["centroid_lat"]),
                    float(r["centroid_lon"]),
                    elev_val,
                    geom_json,
                    str(r.get("crs", "EPSG:4326")),
                    str(r.get("projected_crs", PROJECTED_CRS)),
                    float(r.get("resolution_m", 200.0)),
                )
            )

    with get_db_connection(db_path) as conn:
        with conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO grid_cells (
                    cell_id, row, col, centroid_lat, centroid_lon, elevation_m,
                    geometry_geojson, crs, projected_crs, resolution_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                records,
            )

    logger.info("Saved %d grid cells to database", len(records))
    return len(records)


def load_grid_cells(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """Load grid cells from SQLite database as a GeoDataFrame."""
    init_spatial_db(db_path)

    query = "SELECT cell_id, row, col, centroid_lat, centroid_lon, elevation_m, geometry_geojson, crs, projected_crs, resolution_m FROM grid_cells ORDER BY row, col"
    if limit:
        query += f" LIMIT {int(limit)}"

    with get_db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        rows = cursor.fetchall()

    if not rows:
        return gpd.GeoDataFrame(
            columns=["cell_id", "row", "col", "centroid_lat", "centroid_lon", "elevation_m", "resolution_m", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )

    cell_ids, r_list, c_list, lats, lons, elevs, res_list, geoms = [], [], [], [], [], [], [], []
    for row in rows:
        cell_ids.append(row["cell_id"])
        r_list.append(row["row"])
        c_list.append(row["col"])
        lats.append(row["centroid_lat"])
        lons.append(row["centroid_lon"])
        elevs.append(row["elevation_m"])
        res_list.append(row["resolution_m"])
        geoms.append(shape(json.loads(row["geometry_geojson"])))

    return gpd.GeoDataFrame(
        {
            "cell_id": cell_ids,
            "row": r_list,
            "col": c_list,
            "centroid_lat": lats,
            "centroid_lon": lons,
            "elevation_m": elevs,
            "resolution_m": res_list,
        },
        geometry=geoms,
        crs="EPSG:4326",
    )


def save_roads(
    roads_gdf: gpd.GeoDataFrame,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    source: str = "OpenStreetMap",
    is_synthetic: bool = False,
) -> int:
    """Save road geometries into the SQLite roads table."""
    init_spatial_db(db_path)

    records = []
    for _, row in roads_gdf.iterrows():
        osm_id = str(row.get("osm_id", ""))
        name = str(row.get("name", "")) if pd.notna(row.get("name")) else None
        hwy = str(row.get("highway", "")) if pd.notna(row.get("highway")) else None
        length = float(row.get("length_m", 0.0)) if pd.notna(row.get("length_m")) else None
        geom_json = shapely.to_geojson(row["geometry"])
        src = str(row.get("source", source))
        synth = bool(row.get("is_synthetic", is_synthetic))
        records.append((osm_id, name, hwy, length, geom_json, src, synth))

    with get_db_connection(db_path) as conn:
        with conn:
            conn.executemany(
                """
                INSERT INTO roads (osm_id, name, highway, length_m, geometry_geojson, source, is_synthetic)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                records,
            )

    logger.info("Saved %d roads to database", len(records))
    return len(records)


def load_roads(
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """Load roads from SQLite database as a GeoDataFrame."""
    init_spatial_db(db_path)

    query = "SELECT id, osm_id, name, highway, length_m, geometry_geojson, source, is_synthetic FROM roads"
    if limit:
        query += f" LIMIT {int(limit)}"

    with get_db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        rows = cursor.fetchall()

    if not rows:
        return gpd.GeoDataFrame(columns=["id", "osm_id", "name", "highway", "length_m", "source", "is_synthetic", "geometry"], geometry="geometry", crs="EPSG:4326")

    data, geoms = [], []
    for r in rows:
        geoms.append(shape(json.loads(r["geometry_geojson"])))
        data.append(
            {
                "id": r["id"],
                "osm_id": r["osm_id"],
                "name": r["name"],
                "highway": r["highway"],
                "length_m": r["length_m"],
                "source": r["source"],
                "is_synthetic": bool(r["is_synthetic"]),
            }
        )

    return gpd.GeoDataFrame(data, geometry=geoms, crs="EPSG:4326")


def save_facilities(
    facilities_gdf: gpd.GeoDataFrame,
    category: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    source: str = "OpenStreetMap",
    is_synthetic: bool = False,
) -> int:
    """Save facility records (hospitals, schools, shelters) to SQLite."""
    table_name = category.lower()
    if table_name not in ("hospitals", "schools", "shelters"):
        raise ValueError(f"Invalid facility category '{category}'. Must be 'hospitals', 'schools', or 'shelters'.")

    init_spatial_db(db_path)

    records = []
    for _, row in facilities_gdf.iterrows():
        osm_id = str(row.get("osm_id", ""))
        name = str(row.get("name", "")) if pd.notna(row.get("name")) else None
        lat = float(row.get("latitude", row.geometry.y if hasattr(row.geometry, "y") else 0.0))
        lon = float(row.get("longitude", row.geometry.x if hasattr(row.geometry, "x") else 0.0))
        geom_json = shapely.to_geojson(row["geometry"])
        src = str(row.get("source", source))
        synth = bool(row.get("is_synthetic", is_synthetic))
        records.append((osm_id, name, lat, lon, geom_json, src, synth))

    with get_db_connection(db_path) as conn:
        with conn:
            conn.executemany(
                f"""
                INSERT INTO {table_name} (osm_id, name, latitude, longitude, geometry_geojson, source, is_synthetic)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                records,
            )

    logger.info("Saved %d %s to database", len(records), table_name)
    return len(records)


def load_facilities(
    category: str,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """Load facility records from SQLite database as a GeoDataFrame."""
    table_name = category.lower()
    if table_name not in ("hospitals", "schools", "shelters"):
        raise ValueError(f"Invalid facility category '{category}'.")

    init_spatial_db(db_path)

    query = f"SELECT id, osm_id, name, latitude, longitude, geometry_geojson, source, is_synthetic FROM {table_name}"
    if limit:
        query += f" LIMIT {int(limit)}"

    with get_db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        rows = cursor.fetchall()

    if not rows:
        return gpd.GeoDataFrame(columns=["id", "osm_id", "name", "latitude", "longitude", "source", "is_synthetic", "geometry"], geometry="geometry", crs="EPSG:4326")

    data, geoms = [], []
    for r in rows:
        geoms.append(shape(json.loads(r["geometry_geojson"])))
        data.append(
            {
                "id": r["id"],
                "osm_id": r["osm_id"],
                "name": r["name"],
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "source": r["source"],
                "is_synthetic": bool(r["is_synthetic"]),
            }
        )

    return gpd.GeoDataFrame(data, geometry=geoms, crs="EPSG:4326")


def record_spatial_metadata(
    dataset_name: str,
    source: str,
    crs: str,
    bounds: Optional[Union[List[float], Tuple[float, ...], str]] = None,
    record_count: int = 0,
    is_synthetic: bool = False,
    provenance: Optional[str] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> int:
    """Record dataset metadata and provenance into spatial_metadata table."""
    init_spatial_db(db_path)

    bounds_str = json.dumps(bounds) if isinstance(bounds, (list, tuple)) else (str(bounds) if bounds else None)

    with get_db_connection(db_path) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO spatial_metadata (
                    dataset_name, source, crs, bounds, record_count, is_synthetic, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_name) DO UPDATE SET
                    source=excluded.source,
                    crs=excluded.crs,
                    bounds=excluded.bounds,
                    record_count=excluded.record_count,
                    is_synthetic=excluded.is_synthetic,
                    provenance=excluded.provenance,
                    updated_at=CURRENT_TIMESTAMP;
                """,
                (dataset_name, source, crs, bounds_str, int(record_count), bool(is_synthetic), provenance),
            )
            inserted_id = cursor.lastrowid

    return inserted_id or 0


def get_spatial_metadata(
    dataset_name: Optional[str] = None,
    db_path: Union[str, Path, sqlite3.Connection] = DEFAULT_DB_PATH,
) -> Union[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retrieve spatial metadata records from database."""
    init_spatial_db(db_path)

    with get_db_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if dataset_name:
            cursor = conn.execute(
                "SELECT id, dataset_name, source, crs, bounds, record_count, is_synthetic, provenance, updated_at FROM spatial_metadata WHERE dataset_name = ?",
                (dataset_name,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        else:
            cursor = conn.execute(
                "SELECT id, dataset_name, source, crs, bounds, record_count, is_synthetic, provenance, updated_at FROM spatial_metadata ORDER BY id"
            )
            return [dict(r) for r in cursor.fetchall()]
