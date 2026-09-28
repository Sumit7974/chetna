"""Automated unit and integration tests for Chetna B1 Day 1 spatial data components.

Tests:
- CRS configuration and projections (EPSG:4326, EPSG:32644)
- 200m metric grid generation, determinism, dimensions, and geometry validity
- Coverage of documented Chennai flood hotspots
- DEM raster ingestion, metadata, and elevation derivation
- OSM spatial layers ingestion (roads, hospitals, schools, shelters)
- SQLite spatial data contract and round-trip operations
- Preservation of existing forecast storage and schema

All tests run completely offline without external network dependencies.
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pyproj
import shapely.geometry
from shapely.geometry import Point

from src.db.forecasts import get_latest_forecast, init_db, save_forecast
from src.db.spatial import (
    get_spatial_metadata,
    init_spatial_db,
    load_facilities,
    load_grid_cells,
    load_roads,
    record_spatial_metadata,
    save_facilities,
    save_grid_cells,
    save_roads,
)
from src.ingestion.dem import (
    attach_elevation_to_grid,
    create_synthetic_dem_fixture,
    load_dem_metadata,
)
from src.ingestion.grid import (
    generate_pilot_grid,
    load_grid_geojson,
    save_grid_geojson,
    validate_grid,
)
from src.ingestion.osm import (
    create_synthetic_osm_fixtures,
    load_osm_layer,
)
from src.ingestion.pilot_config import (
    GEOGRAPHIC_CRS,
    GRID_RESOLUTION_M,
    PILOT_BBOX,
    PROJECTED_CRS,
)


class TestB1SpatialData(unittest.TestCase):
    """Test suite for B1 Day 1 geospatial modules and SQLite spatial data contracts."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures_dir = Path("tests/fixtures")
        cls.fixtures_dir.mkdir(parents=True, exist_ok=True)
        # Ensure offline test fixtures exist
        cls.dem_fixture_path = cls.fixtures_dir / "chennai_dem_fixture.tif"
        if not cls.dem_fixture_path.exists():
            create_synthetic_dem_fixture(PILOT_BBOX, cls.dem_fixture_path)
        create_synthetic_osm_fixtures(PILOT_BBOX, cls.fixtures_dir)

    def test_crs_configuration_and_projections(self):
        """Verify authoritative CRS constants and bidirectional transformation."""
        self.assertEqual(GEOGRAPHIC_CRS, "EPSG:4326")
        self.assertIn(PROJECTED_CRS, ["EPSG:32645", "EPSG:32644"])

        # Test bidirectional transformer
        to_utm = pyproj.Transformer.from_crs(GEOGRAPHIC_CRS, PROJECTED_CRS, always_xy=True)
        to_wgs = pyproj.Transformer.from_crs(PROJECTED_CRS, GEOGRAPHIC_CRS, always_xy=True)

        if PROJECTED_CRS == "EPSG:32645":
            # Patna pilot center: 85.1376 E, 25.6093 N
            test_lon, test_lat = 85.1376, 25.6093
            utm_x, utm_y = to_utm.transform(test_lon, test_lat)
            self.assertGreater(utm_x, 200000.0)
            self.assertLess(utm_x, 400000.0)
            self.assertGreater(utm_y, 2700000.0)
            self.assertLess(utm_y, 2900000.0)
        else:
            # Chennai pilot center: 80.2707 E, 13.0827 N
            test_lon, test_lat = 80.2707, 13.0827
            utm_x, utm_y = to_utm.transform(test_lon, test_lat)
            self.assertGreater(utm_x, 300000.0)
            self.assertLess(utm_x, 500000.0)
            self.assertGreater(utm_y, 1400000.0)
            self.assertLess(utm_y, 1500000.0)

        # Inverse transform
        rev_lon, rev_lat = to_wgs.transform(utm_x, utm_y)
        self.assertAlmostEqual(rev_lon, test_lon, places=4)
        self.assertAlmostEqual(rev_lat, test_lat, places=4)

    def test_grid_generation_dimensions_and_validity(self):
        """Verify grid cells are valid polygons with ~200 m metric resolution."""
        # Use a small test bounding box for fast unit test execution
        sub_bbox = {"south": 12.980, "north": 13.000, "west": 80.210, "east": 80.230}
        grid_gdf = generate_pilot_grid(bbox=sub_bbox, resolution_m=200.0)

        self.assertIsInstance(grid_gdf, gpd.GeoDataFrame)
        self.assertGreater(len(grid_gdf), 0)
        self.assertEqual(grid_gdf.crs, "EPSG:4326")

        # Validate schema
        expected_cols = [
            "cell_id", "row", "col", "centroid_lat", "centroid_lon",
            "resolution_m", "crs", "projected_crs", "geometry"
        ]
        for col in expected_cols:
            self.assertIn(col, grid_gdf.columns)

        # Check all geometries are valid polygons
        self.assertTrue(grid_gdf.geometry.is_valid.all())

        # Check cell metric dimensions (~200 m x 200 m = 40,000 m²)
        validation = validate_grid(grid_gdf, expected_resolution_m=200.0)
        self.assertTrue(validation["valid"])
        self.assertAlmostEqual(validation["mean_area_m2"], 40000.0, delta=100.0)

    def test_grid_cell_id_determinism(self):
        """Verify grid generation is strictly deterministic across runs."""
        sub_bbox = {"south": 12.980, "north": 12.990, "west": 80.210, "east": 80.220}
        grid1 = generate_pilot_grid(bbox=sub_bbox, resolution_m=200.0)
        grid2 = generate_pilot_grid(bbox=sub_bbox, resolution_m=200.0)

        self.assertEqual(len(grid1), len(grid2))
        self.assertEqual(grid1["cell_id"].tolist(), grid2["cell_id"].tolist())

        # Check cell_id format CELL_R{row:03d}_C{col:03d}
        first_id = grid1["cell_id"].iloc[0]
        self.assertTrue(first_id.startswith("CELL_R000_C000"))

    def test_grid_covers_all_hotspots(self):
        """Verify the full pilot grid bounding box encloses all 10 documented hotspots."""
        hotspots_file = Path("data/m1/hotspots.json")
        if not hotspots_file.exists():
            self.skipTest("data/m1/hotspots.json not found")

        with open(hotspots_file, "r", encoding="utf-8") as f:
            hotspots = json.load(f)

        west = PILOT_BBOX["west"]
        east = PILOT_BBOX["east"]
        south = PILOT_BBOX["south"]
        north = PILOT_BBOX["north"]

        for h in hotspots:
            lat = h["latitude"]
            lon = h["longitude"]
            self.assertGreaterEqual(lat, south - 0.001, f"{h['hotspot_id']} lat below south bound")
            self.assertLessEqual(lat, north + 0.001, f"{h['hotspot_id']} lat above north bound")
            self.assertGreaterEqual(lon, west - 0.001, f"{h['hotspot_id']} lon below west bound")
            self.assertLessEqual(lon, east + 0.001, f"{h['hotspot_id']} lon above east bound")

    def test_dem_fixture_metadata_and_elevation_sampling(self):
        """Verify DEM raster metadata inspection and elevation attachment to grid cells."""
        meta = load_dem_metadata(self.dem_fixture_path)
        self.assertIn("crs", meta)
        self.assertEqual(meta["crs"], "EPSG:4326")
        self.assertTrue(meta["is_synthetic"])
        self.assertIsNotNone(meta["min_elevation_m"])
        self.assertIsNotNone(meta["max_elevation_m"])
        self.assertGreater(meta["max_elevation_m"], meta["min_elevation_m"])

        # Test attaching elevation to a sample grid within pilot bounds
        sub_bbox = {
            "south": PILOT_BBOX["south"] + 0.010,
            "north": PILOT_BBOX["south"] + 0.020,
            "west": PILOT_BBOX["west"] + 0.010,
            "east": PILOT_BBOX["west"] + 0.020,
        }
        grid = generate_pilot_grid(bbox=sub_bbox, resolution_m=200.0)
        grid_with_elev = attach_elevation_to_grid(grid, self.dem_fixture_path)

        self.assertIn("elevation_m", grid_with_elev.columns)
        self.assertFalse(grid_with_elev["elevation_m"].isna().any())
        self.assertTrue((grid_with_elev["elevation_m"] > 0.0).all())

    def test_osm_fixture_loading(self):
        """Verify offline OSM fixtures for roads, hospitals, schools, and shelters."""
        for layer in ["roads", "hospitals", "schools", "shelters"]:
            gdf = load_osm_layer(layer, fixtures_dir=self.fixtures_dir)
            self.assertIsInstance(gdf, gpd.GeoDataFrame)
            self.assertGreater(len(gdf), 0)
            self.assertEqual(gdf.crs, "EPSG:4326")
            self.assertTrue(gdf["is_synthetic"].all())

            if layer in ("hospitals", "schools", "shelters"):
                self.assertIn("latitude", gdf.columns)
                self.assertIn("longitude", gdf.columns)
                self.assertTrue(all(isinstance(geom, Point) for geom in gdf.geometry))
            elif layer == "roads":
                self.assertIn("highway", gdf.columns)
                self.assertIn("length_m", gdf.columns)
                self.assertTrue((gdf["length_m"] > 0.0).all())

    def test_sqlite_spatial_tables_roundtrip(self):
        """Verify spatial database schema initialization and table read/write roundtrip."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            init_spatial_db(db_path)

            # 1. Grid cells roundtrip
            sub_bbox = {
                "south": PILOT_BBOX["south"] + 0.010,
                "north": PILOT_BBOX["south"] + 0.020,
                "west": PILOT_BBOX["west"] + 0.010,
                "east": PILOT_BBOX["west"] + 0.020,
            }
            grid = generate_pilot_grid(bbox=sub_bbox, resolution_m=200.0)
            grid = attach_elevation_to_grid(grid, self.dem_fixture_path)
            saved_count = save_grid_cells(grid, db_path)
            self.assertEqual(saved_count, len(grid))

            loaded_cells = load_grid_cells(db_path)
            self.assertEqual(len(loaded_cells), len(grid))
            self.assertEqual(loaded_cells["cell_id"].tolist(), grid["cell_id"].tolist())
            self.assertIn("elevation_m", loaded_cells.columns)

            # 2. Roads roundtrip
            roads = load_osm_layer("roads", fixtures_dir=self.fixtures_dir)
            saved_roads = save_roads(roads, db_path)
            self.assertEqual(saved_roads, len(roads))

            loaded_roads = load_roads(db_path)
            self.assertEqual(len(loaded_roads), len(roads))
            self.assertIn("highway", loaded_roads.columns)

            # 3. Facilities roundtrip (hospitals)
            hosp = load_osm_layer("hospitals", fixtures_dir=self.fixtures_dir)
            saved_hosp = save_facilities(hosp, "hospitals", db_path)
            self.assertEqual(saved_hosp, len(hosp))

            loaded_hosp = load_facilities("hospitals", db_path)
            self.assertEqual(len(loaded_hosp), len(hosp))
            self.assertIn("latitude", loaded_hosp.columns)

            # 4. Metadata recording
            record_spatial_metadata(
                dataset_name="test_dataset",
                source="Unit Test",
                crs="EPSG:4326",
                bounds=[80.0, 12.0, 80.3, 13.2],
                record_count=100,
                is_synthetic=True,
                provenance="Automated test suite",
                db_path=db_path,
            )
            meta = get_spatial_metadata("test_dataset", db_path)
            self.assertIsNotNone(meta)
            self.assertEqual(meta["dataset_name"], "test_dataset")
            self.assertEqual(meta["record_count"], 100)
            self.assertTrue(bool(meta["is_synthetic"]))

        finally:
            if db_path.exists():
                try:
                    db_path.unlink()
                except Exception:
                    pass

    def test_forecast_database_compatibility(self):
        """Verify spatial schema additions do not break existing forecast table operations."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            # Initialize both forecast and spatial schemas
            init_spatial_db(db_path)

            # Save and retrieve forecast record
            forecast_data = {
                "timestamp": "2026-09-25T12:00:00Z",
                "rain_1h": 12.5,
                "rain_3h": 34.0,
                "rain_6h": 65.2,
            }
            row_id = save_forecast(forecast_data, db_path)
            self.assertGreater(row_id, 0)

            latest = get_latest_forecast(db_path)
            self.assertIsNotNone(latest)
            self.assertEqual(latest["timestamp"], "2026-09-25T12:00:00Z")
            self.assertEqual(latest["rain_1h"], 12.5)
            self.assertEqual(latest["rain_3h"], 34.0)
            self.assertEqual(latest["rain_6h"], 65.2)

        finally:
            if db_path.exists():
                try:
                    db_path.unlink()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
