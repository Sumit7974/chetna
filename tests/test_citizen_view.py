"""Automated tests for Chetna F2 Day 1 Citizen View foundation and wireframes."""

import json
from pathlib import Path
import unittest

from app import (
    extract_facilities_from_hotspots,
    get_bilingual_messages,
    render_citizen_view,
)
import app.citizen_view as cv


class TestCitizenView(unittest.TestCase):
    """Test suite validating F2 Day 1 citizen view components, facility extraction, and bilingual foundation."""

    def setUp(self):
        self.hotspots_path = Path("data/m1/hotspots.json")
        self.hotspots_data = []
        if self.hotspots_path.exists():
            with open(self.hotspots_path, "r", encoding="utf-8") as f:
                self.hotspots_data = json.load(f)

    def test_extract_facilities_from_real_hotspots(self):
        """Verify facilities are extracted and categorized from real M1 Day 1 hotspot records."""
        if not self.hotspots_data:
            self.skipTest("data/m1/hotspots.json not found")

        facilities = extract_facilities_from_hotspots(self.hotspots_data)
        self.assertIsInstance(facilities, dict)
        self.assertIn("hospitals", facilities)
        self.assertIn("schools", facilities)
        self.assertIn("shelters", facilities)

        # Check hospitals category has real records
        hospitals = facilities["hospitals"]
        self.assertGreaterEqual(len(hospitals), 3)
        hospital_names = [h["name"] for h in hospitals]
        self.assertTrue(any("hospital" in name.lower() for name in hospital_names))

        # Check schools category has real records
        schools = facilities["schools"]
        self.assertGreaterEqual(len(schools), 2)
        school_names = [s["name"] for s in schools]
        self.assertTrue(any("school" in name.lower() or "college" in name.lower() for name in school_names))

        # Check shelters/transit hubs category has real records
        shelters = facilities["shelters"]
        self.assertGreaterEqual(len(shelters), 5)
        shelter_names = [sh["name"] for sh in shelters]
        self.assertTrue(any("station" in name.lower() or "terminus" in name.lower() for name in shelter_names))

        # Check facility schema integrity
        sample_item = hospitals[0]
        self.assertIn("name", sample_item)
        self.assertIn("vicinity", sample_item)
        self.assertIn("zone", sample_item)
        self.assertIn("severity_context", sample_item)
        self.assertEqual(sample_item.get("source"), "GCC Hotspot Infrastructure Registry")

    def test_extract_facilities_empty_or_malformed_input(self):
        """Verify extract_facilities_from_hotspots handles empty or malformed input gracefully."""
        # Empty list
        empty_res = extract_facilities_from_hotspots([])
        self.assertEqual(empty_res, {"hospitals": [], "schools": [], "shelters": []})

        # None input
        none_res = extract_facilities_from_hotspots(None)
        self.assertEqual(none_res, {"hospitals": [], "schools": [], "shelters": []})

        # Hotspots without infrastructure key
        partial_data = [{"hotspot_id": "HS_TEST", "name": "Test Area"}]
        partial_res = extract_facilities_from_hotspots(partial_data)
        self.assertEqual(partial_res, {"hospitals": [], "schools": [], "shelters": []})

    def test_get_bilingual_messages_structure(self):
        """Verify bilingual messages dictionary contains English and Hindi with complete schema."""
        messages = get_bilingual_messages()
        self.assertIsInstance(messages, dict)
        self.assertIn("en", messages)
        self.assertIn("hi", messages)

        required_keys = [
            "title",
            "language_name",
            "status_normal",
            "normal_summary",
            "sample_advisory_title",
            "sample_advisory_body",
            "safety_tips",
            "safe_route_note",
        ]

        for lang in ["en", "hi"]:
            lang_dict = messages[lang]
            for key in required_keys:
                self.assertIn(key, lang_dict, f"Missing key '{key}' in language '{lang}'")

            # safety_tips must be a list with at least 3 tips
            self.assertIsInstance(lang_dict["safety_tips"], list)
            self.assertGreaterEqual(len(lang_dict["safety_tips"]), 3)

        # English-specific checks
        en_dict = messages["en"]
        self.assertIn("Community Flood Advisory", en_dict["title"])
        self.assertIn("Day 4", en_dict["safe_route_note"])

        # Hindi-specific checks (Unicode)
        hi_dict = messages["hi"]
        self.assertIn("बाढ़", hi_dict["title"])
        self.assertIn("डे 4", hi_dict["safe_route_note"])

    def test_logo_asset_resolution_in_citizen_view(self):
        """Verify citizen view resolves the existing brand logo asset."""
        logo_path = cv.get_logo_asset_path()
        self.assertIsNotNone(logo_path)
        self.assertTrue(logo_path.exists())

    def test_package_exports(self):
        """Verify app package exposes the citizen view functions."""
        self.assertTrue(callable(extract_facilities_from_hotspots))
        self.assertTrue(callable(get_bilingual_messages))
        self.assertTrue(callable(render_citizen_view))

    def test_render_functions_callable(self):
        """Verify all sub-render functions in app.citizen_view are callable."""
        self.assertTrue(callable(cv.render_citizen_header))
        self.assertTrue(callable(cv.render_citizen_status_card))
        self.assertTrue(callable(cv.render_citizen_input_stub))
        self.assertTrue(callable(cv.render_citizen_map))
        self.assertTrue(callable(cv.render_citizen_facilities_panel))
        self.assertTrue(callable(cv.render_citizen_safe_route_placeholder))
        self.assertTrue(callable(cv.render_citizen_advisory_section))
        self.assertTrue(callable(cv.render_citizen_footer))
        self.assertTrue(callable(cv.render_citizen_view))


if __name__ == "__main__":
    unittest.main()
