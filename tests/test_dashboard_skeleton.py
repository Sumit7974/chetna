"""Automated tests for Chetna F1 Day 1 Streamlit Dashboard Skeleton and Folium Base Map."""

import math
import tempfile
import unittest
from pathlib import Path

import folium
from PIL import Image

from app.dashboard import (
    DEFAULT_CITY,
    DEFAULT_COORDINATES,
    DEFAULT_ZOOM_START,
    LOGO_PNG_PATH,
    LOGO_SVG_PATH,
    create_base_map,
    get_logo_asset_path,
    get_logo_svg,
    get_system_metrics,
    load_hotspots_data,
    load_static_risk_metadata,
)


class TestDashboardSkeleton(unittest.TestCase):
    """Test suite validating F1 Day 1 dashboard skeleton, map setup, and architecture readiness."""

    def test_create_base_map_default_attributes(self):
        """Verify default base map is a Folium Map centered on Chennai with initial zoom and plugins."""
        folium_map = create_base_map()
        self.assertIsInstance(folium_map, folium.Map)

        # Check center coordinates
        lat, lon = folium_map.location
        self.assertTrue(math.isclose(lat, 13.0827, abs_tol=1e-4))
        self.assertTrue(math.isclose(lon, 80.2707, abs_tol=1e-4))

        # Check default zoom
        self.assertEqual(folium_map.options.get("zoom"), DEFAULT_ZOOM_START)

        # Check that children exist (tile layer, center marker, fullscreen plugin)
        children = folium_map._children
        self.assertTrue(len(children) > 0)

        # Verify fullscreen plugin is integrated
        html_str = folium_map.get_root().render()
        self.assertIn("fullscreen", html_str.lower())

    def test_create_base_map_custom_parameters(self):
        """Verify map creation accepts custom center, zoom level, and disables marker/fullscreen if requested."""
        custom_center = (12.9815, 80.2180)  # Velachery
        custom_zoom = 13
        m = create_base_map(
            center=custom_center,
            zoom_start=custom_zoom,
            add_center_marker=False,
            add_fullscreen_control=False,
        )

        self.assertIsInstance(m, folium.Map)
        self.assertTrue(math.isclose(m.location[0], 12.9815, abs_tol=1e-4))
        self.assertTrue(math.isclose(m.location[1], 80.2180, abs_tol=1e-4))
        self.assertEqual(m.options.get("zoom"), 13)

    def test_folium_map_html_generation(self):
        """Verify map HTML can be rendered cleanly for Streamlit component embedding."""
        folium_map = create_base_map()
        html_str = folium_map.get_root().render()

        self.assertIsInstance(html_str, str)
        self.assertGreater(len(html_str), 500)
        self.assertIn("leaflet", html_str.lower())
        self.assertIn("13.0827", html_str)
        self.assertIn("80.2707", html_str)

    def test_brand_logo_assets(self):
        """Verify brand logo SVG and PNG assets exist and are valid."""
        self.assertTrue(LOGO_SVG_PATH.exists(), "Chetna SVG logo asset should exist")
        svg_content = LOGO_SVG_PATH.read_text(encoding="utf-8")
        self.assertIn("<svg", svg_content)
        self.assertIn("</svg>", svg_content)

        self.assertTrue(LOGO_PNG_PATH.exists(), "Chetna PNG logo asset should exist")
        with Image.open(LOGO_PNG_PATH) as img:
            self.assertEqual(img.size, (128, 128))
            self.assertEqual(img.mode, "RGBA")

        # Test get_logo_asset_path helper
        resolved_path = get_logo_asset_path()
        self.assertIsNotNone(resolved_path)
        self.assertTrue(resolved_path.exists())
        self.assertTrue(str(resolved_path).endswith(".png"))

        resolved_svg = get_logo_asset_path(prefer_svg=True)
        self.assertIsNotNone(resolved_svg)
        self.assertTrue(resolved_svg.exists())
        self.assertTrue(str(resolved_svg).endswith(".svg"))

        # Test get_logo_svg helper
        markup = get_logo_svg(size=40)
        self.assertIsInstance(markup, str)
        self.assertIn("<svg", markup)
        self.assertIn("width:40px", markup)

    def test_load_static_risk_metadata_real_file(self):
        """Verify static vulnerability metadata from M1 Day 2 loads accurately."""
        real_file = Path("data/m1/static_risk_scores.json")
        if not real_file.exists():
            self.skipTest("data/m1/static_risk_scores.json not found")

        meta = load_static_risk_metadata(real_file)
        self.assertTrue(meta.get("loaded"))
        self.assertGreaterEqual(meta.get("cell_count", 0), 30)
        self.assertIn("formula", meta)
        self.assertIn("weights", meta)
        weights = meta["weights"]
        self.assertIn("elevation", weights)
        self.assertIn("slope", weights)
        self.assertIn("flow_accumulation", weights)
        self.assertIn("imperviousness", weights)

    def test_load_static_risk_metadata_missing_file_graceful(self):
        """Verify missing static risk file returns fallback dictionary without crashing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_file = Path(tmp_dir) / "non_existent.json"
            meta = load_static_risk_metadata(missing_file)

            self.assertFalse(meta.get("loaded"))
            self.assertEqual(meta.get("cell_count"), 0)
            self.assertIn("formula", meta)
            self.assertEqual(meta.get("cells"), [])

    def test_load_hotspots_data_real_file(self):
        """Verify known waterlogging hotspots from M1 Day 1 load accurately."""
        real_file = Path("data/m1/hotspots.json")
        if not real_file.exists():
            self.skipTest("data/m1/hotspots.json not found")

        hotspots = load_hotspots_data(real_file)
        self.assertIsInstance(hotspots, list)
        self.assertEqual(len(hotspots), 10)

        # Inspect required schema on first record
        first = hotspots[0]
        self.assertIn("hotspot_id", first)
        self.assertIn("name", first)
        self.assertIn("latitude", first)
        self.assertIn("longitude", first)
        self.assertIn("elevation_m", first)
        self.assertIn("severity_tier", first)

    def test_load_hotspots_data_missing_file_graceful(self):
        """Verify missing hotspots file returns empty list without error."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_file = Path(tmp_dir) / "no_hotspots.json"
            hotspots = load_hotspots_data(missing_file)
            self.assertEqual(hotspots, [])

    def test_get_system_metrics_structure(self):
        """Verify get_system_metrics returns expected dictionary schema and values."""
        metrics = get_system_metrics()
        self.assertIsInstance(metrics, dict)
        self.assertEqual(metrics["pilot_city"], DEFAULT_CITY)
        self.assertEqual(metrics["coordinates"], DEFAULT_COORDINATES)
        self.assertIn("db_connected", metrics)
        self.assertIn("forecasts_count", metrics)
        self.assertIn("static_risk_cells_count", metrics)
        self.assertIn("hotspots_count", metrics)
        self.assertIn("static_risk_ready", metrics)

        # Hotspots should be 10 if data/m1/hotspots.json is present
        if Path("data/m1/hotspots.json").exists():
            self.assertEqual(metrics["hotspots_count"], 10)

        # Static risk cells should be 38 if data/m1/static_risk_scores.json is present
        if Path("data/m1/static_risk_scores.json").exists():
            self.assertEqual(metrics["static_risk_cells_count"], 38)
            self.assertTrue(metrics["static_risk_ready"])

    def test_app_package_imports(self):
        """Verify app package exposes core functions and constants."""
        import app
        self.assertEqual(app.DEFAULT_CITY, "Chennai, India")
        self.assertEqual(app.DEFAULT_COORDINATES, (13.0827, 80.2707))
        self.assertTrue(callable(app.create_base_map))
        self.assertTrue(callable(app.get_system_metrics))
        self.assertTrue(callable(app.get_logo_svg))
        self.assertTrue(callable(app.get_logo_asset_path))


if __name__ == "__main__":
    unittest.main()
