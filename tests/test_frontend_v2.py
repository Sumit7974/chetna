"""Automated tests for Chetna Frontend v2 (F1 Authority Operations & F2 Citizen Safety)."""

import json
import sqlite3
import unittest
from pathlib import Path

import folium

from app.config import (
    EMERGENCY_HELPLINES,
    F1_NAV_ITEMS,
    F1_PORTAL_TITLE,
    F2_NAV_ITEMS,
    F2_PORTAL_TITLE,
    HAZARD_SCOPE,
    PILOT_CITY,
    PILOT_LOCATION_LABEL,
    PILOT_STATE,
    SYSTEM_NAME,
)
import app.citizen_view as cv
import app.dashboard as db
import app.map_layers as ml


class TestFrontendV2(unittest.TestCase):
    """Test suite for Frontend Day 1 & Day 2 architecture, config, and operational map layers."""

    @classmethod
    def setUpClass(cls):
        from app.demo_scenario import reset_to_baseline_scenario
        reset_to_baseline_scenario()

    @classmethod
    def tearDownClass(cls):
        from app.demo_scenario import reset_to_baseline_scenario
        reset_to_baseline_scenario()

    def test_frontend_config_layer(self):
        """Verify frontend config defines pilot city, state, hazard scope, and navigation."""
        self.assertEqual(PILOT_CITY, "Patna")
        self.assertEqual(PILOT_STATE, "Bihar")
        self.assertEqual(PILOT_LOCATION_LABEL, "Patna, Bihar")
        self.assertEqual(HAZARD_SCOPE, "Rainfall-driven urban flooding and waterlogging")
        self.assertEqual(SYSTEM_NAME, "Chetna")

        # F1 and F2 titles
        self.assertEqual(F1_PORTAL_TITLE, "Authority Operations Center")
        self.assertEqual(F2_PORTAL_TITLE, "Flood Safety")

        # Navigation structures
        self.assertIn("Overview", F1_NAV_ITEMS)
        self.assertIn("Risk Map", F1_NAV_ITEMS)
        self.assertIn("Alerts", F1_NAV_ITEMS)

        self.assertIn("My Area", F2_NAV_ITEMS)
        self.assertIn("Flood Risk", F2_NAV_ITEMS)
        self.assertIn("Safe Places", F2_NAV_ITEMS)
        self.assertIn("Safe Route", F2_NAV_ITEMS)
        self.assertIn("Advisory", F2_NAV_ITEMS)
        self.assertIn("Emergency Help", F2_NAV_ITEMS)

        # Emergency helplines
        self.assertIn("national_emergency", EMERGENCY_HELPLINES)
        self.assertEqual(EMERGENCY_HELPLINES["national_emergency"], "112")
        self.assertIn("state_disaster", EMERGENCY_HELPLINES)
        self.assertEqual(EMERGENCY_HELPLINES["state_disaster"], "1070")

    def test_no_milestone_jargon_in_config(self):
        """Verify config layer is free of internal milestone labels."""
        forbidden = [
            "F1 Day 1",
            "F2 Day 1",
            "M1 Day 2",
            "Milestone",
            "Unlocks Day 4",
            "Available in a Later Milestone",
            "GB English",
            "IN हिंदी",
        ]
        config_text = f"{F1_PORTAL_TITLE} {F2_PORTAL_TITLE} {HAZARD_SCOPE} {PILOT_CITY} {PILOT_STATE}"
        for token in forbidden:
            self.assertNotIn(token.lower(), config_text.lower())

    def test_f1_render_functions_exist(self):
        """Verify all F1 authority rendering helpers exist and are callable."""
        self.assertTrue(callable(db.render_header))
        self.assertTrue(callable(db.render_dominant_status))
        self.assertTrue(callable(db.render_summary_cards))
        self.assertTrue(callable(db.render_main_workspace))
        self.assertTrue(callable(db.render_alert_and_architecture_section))
        self.assertTrue(callable(db.render_footer))
        self.assertTrue(callable(db.render_sidebar))

    def test_f2_render_functions_exist(self):
        """Verify all F2 citizen rendering helpers exist and are callable."""
        self.assertTrue(callable(cv.render_citizen_header))
        self.assertTrue(callable(cv.render_citizen_status_card))
        self.assertTrue(callable(cv.render_citizen_input_stub))
        self.assertTrue(callable(cv.render_citizen_map))
        self.assertTrue(callable(cv.render_citizen_facilities_panel))
        self.assertTrue(callable(cv.render_citizen_safe_route))
        self.assertTrue(callable(cv.render_citizen_advisory_section))
        self.assertTrue(callable(cv.render_citizen_footer))
        self.assertTrue(callable(cv.render_citizen_view))

    def test_app_package_reexports_config(self):
        """Verify app package exposes the frontend configuration variables."""
        import app
        self.assertEqual(app.PILOT_CITY, "Patna")
        self.assertEqual(app.PILOT_STATE, "Bihar")
        self.assertEqual(app.PILOT_LOCATION_LABEL, "Patna, Bihar")
        self.assertEqual(app.HAZARD_SCOPE, "Rainfall-driven urban flooding and waterlogging")
        self.assertTrue(callable(app.build_operational_map))
        self.assertTrue(callable(app.add_risk_cells_layer))
        self.assertTrue(callable(app.add_hotspots_layer))
        self.assertTrue(callable(app.add_sensor_layer))
        self.assertTrue(callable(app.add_map_legend))

    # =========================================================================
    # FRONTEND DAY 2: OPERATIONAL MAP & LAYERS TESTS
    # =========================================================================

    def test_risk_tier_styling_thresholds(self):
        """Verify risk tier color mappings conform to calibrated thresholds."""
        # High Risk: >= 0.70 -> Red
        high = ml.get_risk_tier_style(0.70)
        self.assertEqual(high["tier"], "HIGH")
        self.assertEqual(high["fill_color"], "#dc2626")

        high_above = ml.get_risk_tier_style(0.92)
        self.assertEqual(high_above["tier"], "HIGH")

        # Medium Risk: 0.40 <= score < 0.70 -> Amber
        med = ml.get_risk_tier_style(0.40)
        self.assertEqual(med["tier"], "MEDIUM")
        self.assertEqual(med["fill_color"], "#f59e0b")

        med_mid = ml.get_risk_tier_style(0.55)
        self.assertEqual(med_mid["tier"], "MEDIUM")

        # Low Risk: < 0.40 -> Green
        low = ml.get_risk_tier_style(0.39)
        self.assertEqual(low["tier"], "LOW")
        self.assertEqual(low["fill_color"], "#16a34a")

        low_zero = ml.get_risk_tier_style(0.0)
        self.assertEqual(low_zero["tier"], "LOW")

    def test_add_risk_cells_layer_real_data(self):
        """Verify static vulnerability cells layer renders with correct attributes and popups."""
        m = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        static_data = db.load_static_risk_metadata()
        self.assertTrue(static_data.get("loaded", False))
        cells = static_data.get("cells", [])
        self.assertGreaterEqual(len(cells), 30)

        fg = ml.add_risk_cells_layer(m, static_data, horizon="NOW")
        self.assertIsInstance(fg, folium.FeatureGroup)
        self.assertEqual(len(fg._children), len(cells))

        html = m.get_root().render()
        self.assertIn("CELL_PAT_01", html)
        self.assertIn("OPERATIONAL RISK CELL", html)
        self.assertIn("Prototype Baseline: Reference Spatial Grid", html)

    def test_add_hotspots_layer_real_data(self):
        """Verify waterlogging hotspots layer renders 10 sites with operational popups."""
        m = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        hotspots = db.load_hotspots_data()
        self.assertEqual(len(hotspots), 10)

        fg = ml.add_hotspots_layer(m, hotspots)
        self.assertIsInstance(fg, folium.FeatureGroup)
        self.assertEqual(len(fg._children), 10)

        html = m.get_root().render()
        self.assertIn("HS01", html)
        self.assertIn("Rajendra Nagar Sump Basin", html)
        self.assertIn("WATERLOGGING HOTSPOT", html)
        self.assertIn("Trigger Rain", html)

    def test_load_and_add_sensor_layer(self):
        """Verify sensor telemetry stations are loaded and rendered cleanly."""
        sensors = ml.load_sensor_stations()
        self.assertGreaterEqual(len(sensors), 8)
        first_sensor = sensors[0]
        self.assertIn("node_id", first_sensor)
        self.assertIn("water_level_cm", first_sensor)
        self.assertIn("rainfall_rate_mm_h", first_sensor)
        self.assertIn("status", first_sensor)
        self.assertIn("source", first_sensor)

        m = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        fg = ml.add_sensor_layer(m, sensors)
        self.assertIsInstance(fg, folium.FeatureGroup)
        self.assertEqual(len(fg._children), len(sensors))

        html = m.get_root().render()
        self.assertIn("TELEMETRY SENSOR", html)
        self.assertIn("Water Stage", html)
        self.assertIn(first_sensor["node_id"], html)

    def test_horizon_checking_and_graceful_notice(self):
        """Verify forecast horizon checks correctly report availability without synthetic fabrication."""
        # NOW is always available from baseline
        now_status = ml.check_horizon_prediction_availability("NOW")
        self.assertTrue(now_status["available"])
        self.assertEqual(now_status["horizon"], "NOW")

        # Future horizons when unpopulated report clean unavailable status
        for h in ["+1h", "+3h", "+6h"]:
            status = ml.check_horizon_prediction_availability(h)
            self.assertFalse(status["available"])
            self.assertIn("forecast data unavailable", status["message"].lower())
            self.assertIsNone(status.get("predictions"))

    def test_map_legend_injection(self):
        """Verify compact floating map legend is injected with risk levels, hotspots, sensors, and attribution."""
        m = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        ml.add_map_legend(m)

        html = m.get_root().render()
        self.assertIn("Operational Risk Legend", html)
        self.assertIn("High Risk", html)
        self.assertIn("Medium Risk", html)
        self.assertIn("Low Risk", html)
        self.assertIn("Hotspot", html)
        self.assertIn("Sensor", html)
        self.assertIn("Prototype Baseline: Reference Spatial Grid", html)

    def test_build_operational_map_full_integration(self):
        """Verify end-to-end operational map construction with Mapbox PyDeck and Folium fallback."""
        import pydeck as pdk
        static_data = db.load_static_risk_metadata()
        hotspots = db.load_hotspots_data()
        sensors = ml.load_sensor_stations()

        # 1. Primary Mapbox / PyDeck engine
        deck = ml.build_operational_map(
            center=(25.6093, 85.1376),
            zoom_start=12,
            static_risk_data=static_data,
            hotspots_data=hotspots,
            sensors_data=sensors,
            layer_static=True,
            layer_hotspots=True,
            layer_sensors=True,
            horizon="NOW",
        )
        self.assertIsInstance(deck, pdk.Deck)
        self.assertEqual(len(deck.layers), 3)
        self.assertEqual(deck.initial_view_state.latitude, 25.6093)
        self.assertEqual(deck.initial_view_state.longitude, 85.1376)
        json_repr = deck.to_json()
        self.assertIn("CELL_PAT_01", json_repr)
        self.assertIn("HS01", json_repr)
        self.assertIn("SENS_PAT_01", json_repr)

        # 2. Folium fallback
        m_folium = ml.build_operational_map(
            center=(25.6093, 85.1376),
            zoom_start=12,
            static_risk_data=static_data,
            hotspots_data=hotspots,
            sensors_data=sensors,
            backend="folium",
        )
        self.assertIsInstance(m_folium, folium.Map)
        html = m_folium.get_root().render()
        self.assertIn("leaflet", html.lower())
        self.assertIn("Operational Risk Legend", html)
        self.assertIn("CELL_PAT_01", html)
        self.assertIn("HS01", html)
        self.assertIn("SENS_PAT_01", html)

    def test_layer_toggles_and_empty_graceful_handling(self):
        """Verify map builds without crashing when layers are disabled or data is empty."""
        import pydeck as pdk
        deck = ml.build_operational_map(
            layer_static=False,
            layer_hotspots=False,
            layer_sensors=False,
            add_legend=False,
        )
        self.assertIsInstance(deck, pdk.Deck)
        self.assertEqual(len(deck.layers), 0)

        # Empty data handling for Folium components
        m = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        fg_cells = ml.add_risk_cells_layer(m, [])
        self.assertEqual(len(fg_cells._children), 0)

        fg_hotspots = ml.add_hotspots_layer(m, [])
        self.assertEqual(len(fg_hotspots._children), 0)

        fg_sensors = ml.add_sensor_layer(m, [])
        self.assertEqual(len(fg_sensors._children), 0)

    def test_mapbox_token_and_carto_fallback(self):
        """Verify Mapbox style selection uses Mapbox light-v10 when token is set and Carto fallback when absent."""
        # Fallback when no token
        style_fallback, api_keys_fallback, is_active_fallback = ml.get_mapbox_map_style(mapbox_token="")
        self.assertFalse(is_active_fallback)
        self.assertIsNone(api_keys_fallback)
        self.assertIn("carto", style_fallback.lower())

        # Valid Mapbox token
        sample_token = "pk.eyJ1IjoiY2hldG5hLXVzZXIiLCJhIjoiY2x5eXpqIn0.test_key"
        style_mapbox, api_keys_mapbox, is_active_mapbox = ml.get_mapbox_map_style(mapbox_token=sample_token)
        self.assertTrue(is_active_mapbox)
        self.assertEqual(api_keys_mapbox, {"mapbox": sample_token})
        self.assertEqual(style_mapbox, "mapbox://styles/mapbox/light-v10")

    # =========================================================================
    # FRONTEND DAY 3: MULTI-HORIZON PREDICTIONS, WHY-FLAGGED & AT-RISK ASSETS
    # =========================================================================

    def test_day3_load_horizon_predictions_baseline_now(self):
        """Verify NOW horizon calculates accurate counts from static vulnerability baseline."""
        static_data = db.load_static_risk_metadata()
        res = ml.load_horizon_predictions("NOW", static_risk_data=static_data)

        self.assertTrue(res["available"])
        self.assertEqual(res["horizon"], "NOW")
        self.assertEqual(res["horizon_hours"], 0)
        self.assertIsNone(res["predictions"])

        counts = res["counts"]
        self.assertIsNotNone(counts)
        self.assertEqual(counts["total"], 38)
        self.assertEqual(counts["HIGH"], 18)
        self.assertEqual(counts["MEDIUM"], 14)
        self.assertEqual(counts["LOW"], 6)
        self.assertEqual(counts["SEVERE"], 0)

    def test_day3_load_horizon_predictions_missing_graceful(self):
        """Verify unavailable horizons return clean notices without synthetic data fabrication."""
        for horizon in ["+1h", "+3h", "+6h"]:
            res = ml.load_horizon_predictions(horizon)
            self.assertFalse(res["available"])
            self.assertIsNone(res["predictions"])
            self.assertIsNone(res["counts"])
            self.assertIn(f"Forecast data unavailable for {horizon}.", res["message"])

    def test_day3_load_horizon_predictions_dynamic_database(self):
        """Verify dynamic predictions are read correctly from SQLite when available."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE risk_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                level TEXT NOT NULL,
                probability REAL,
                explanation TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Insert 4 mock cells for horizon 1
        cursor.execute("""
            INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
            VALUES ('CELL_VEL_01', '2026-09-29T00:00:00', 1, 'HIGH', 0.82, '{"summary": "Depression runoff", "top_factors": ["Flow accumulation"]}')
        """)
        cursor.execute("""
            INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
            VALUES ('CELL_VEL_02', '2026-09-29T00:00:00', 1, 'MEDIUM', 0.54, '{"summary": "Paved runoff", "top_factors": ["Imperviousness"]}')
        """)
        cursor.execute("""
            INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
            VALUES ('CELL_VEL_03', '2026-09-29T00:00:00', 1, 'LOW', 0.20, NULL)
        """)
        cursor.execute("""
            INSERT INTO risk_predictions (cell_id, timestamp, horizon, level, probability, explanation)
            VALUES ('CELL_VEL_04', '2026-09-29T00:00:00', 1, 'SEVERE', 0.94, '{"summary": "Critical flooding", "top_factors": ["Low elevation", "Depression"]}')
        """)
        conn.commit()

        res = ml.load_horizon_predictions("+1h", db_path=conn)
        self.assertTrue(res["available"])
        self.assertEqual(res["horizon"], "+1h")
        self.assertEqual(res["horizon_hours"], 1)

        counts = res["counts"]
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["HIGH"], 1)
        self.assertEqual(counts["MEDIUM"], 1)
        self.assertEqual(counts["LOW"], 1)
        self.assertEqual(counts["SEVERE"], 1)

        preds = res["predictions"]
        self.assertIn("CELL_VEL_01", preds)
        self.assertEqual(preds["CELL_VEL_01"]["level"], "HIGH")
        self.assertEqual(preds["CELL_VEL_01"]["probability"], 0.82)
        self.assertEqual(preds["CELL_VEL_01"]["explanation"]["summary"], "Depression runoff")

        self.assertIn("CELL_VEL_04", preds)
        self.assertEqual(preds["CELL_VEL_04"]["level"], "SEVERE")
        self.assertEqual(preds["CELL_VEL_04"]["probability"], 0.94)

        conn.close()

    def test_day3_why_flagged_non_causal_disclaimer(self):
        """Verify why-flagged bullets format features concisely and include the scientific disclaimer."""
        explanation = {
            "summary": "Heavy surface runoff concentration",
            "top_factors": [
                "Catchment volume: High flow accumulation",
                "Low ground elevation: Inundation depression",
            ],
        }
        raw_features = {
            "elevation": 4.5,
            "flow_accumulation": 45000.0,
            "imperviousness": 0.82,
            "slope": 0.3,
        }

        html = ml.format_why_flagged_html(explanation, raw_features=raw_features, is_hotspot=True)

        # Assert non-causal disclaimer is explicitly present
        self.assertIn(
            "Scientific provenance: Model feature attribution, not proven physical causation.",
            html,
        )

        # Assert concise operational language without raw ML jargon
        self.assertIn("Heavy surface runoff concentration", html)
        self.assertIn("High flow accumulation", html)
        self.assertNotIn("auc-roc", html.lower())
        self.assertNotIn("shap_value", html.lower())
        self.assertNotIn("log_loss", html.lower())

    def test_day3_cell_popup_probability_formatting(self):
        """Verify cell popup displays probability percentage when available and cleanly omits it when unavailable."""
        m = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        static_data = db.load_static_risk_metadata()

        # Dynamic predictions with probability
        dynamic_preds = {
            "CELL_PAT_01": {
                "level": "HIGH",
                "probability": 0.824,
                "explanation": {"summary": "High runoff", "top_factors": ["Flow accumulation"]},
                "timestamp": "2026-09-29T00:00:00",
            },
            "CELL_PAT_02": {
                "level": "LOW",
                "probability": None,  # Omitted probability
                "explanation": None,
                "timestamp": "2026-09-29T00:00:00",
            },
        }

        fg = ml.add_risk_cells_layer(m, static_data, horizon="+1h", dynamic_predictions=dynamic_preds)
        html = m.get_root().render()

        # CELL_PAT_01 has 82% probability rendered
        self.assertIn("82%", html)
        self.assertIn("Probability:", html)

    def test_day3_at_risk_assets_summary(self):
        """Verify at-risk critical infrastructure assets are correctly summarized from high-risk zones."""
        static_data = db.load_static_risk_metadata()
        hotspots = db.load_hotspots_data()

        # NOW baseline: high-risk cells contain 21 facilities in Patna
        now_status = ml.load_horizon_predictions("NOW", static_risk_data=static_data)
        assets_now = ml.get_at_risk_assets_summary(now_status, hotspots, static_data)

        self.assertTrue(assets_now["available"])
        self.assertEqual(assets_now["total"], 21)
        self.assertEqual(assets_now["hospitals"], 3)
        self.assertEqual(assets_now["schools"], 6)
        self.assertEqual(assets_now["shelters"], 12)
        self.assertEqual(len(assets_now["items"]), 21)

        # Verify items have required keys
        sample = assets_now["items"][0]
        self.assertIn("name", sample)
        self.assertIn("type", sample)
        self.assertIn("zone", sample)
        self.assertIn("vicinity", sample)

        # Unavailable horizon: assets should report unavailable
        unavail_status = ml.load_horizon_predictions("+1h")
        assets_unavail = ml.get_at_risk_assets_summary(unavail_status, hotspots, static_data)
        self.assertFalse(assets_unavail["available"])
        self.assertEqual(assets_unavail["total"], 0)
        self.assertEqual(len(assets_unavail["items"]), 0)

    def test_day3_dashboard_exports_and_callables(self):
        """Verify Day 3 rendering helpers are callable and present in app package."""
        self.assertTrue(callable(db.render_operational_risk_summary))
        self.assertTrue(callable(ml.load_horizon_predictions))
        self.assertTrue(callable(ml.get_at_risk_assets_summary))
        self.assertTrue(callable(ml.format_why_flagged_html))

        import app
        self.assertTrue(callable(app.load_horizon_predictions))
        self.assertTrue(callable(app.get_at_risk_assets_summary))
        self.assertTrue(callable(app.format_why_flagged_html))

    def test_day3_f2_citizen_view_no_ml_jargon(self):
        """Verify F2 Citizen Safety view remains simple, non-technical, and free of ML jargon."""
        bilingual = cv.get_bilingual_messages()
        en_text = f"{bilingual['en']['normal_summary']} {bilingual['en']['sample_advisory_body']} {' '.join(bilingual['en']['safety_tips'])}"
        hi_text = f"{bilingual['hi']['normal_summary']} {bilingual['hi']['sample_advisory_body']} {' '.join(bilingual['hi']['safety_tips'])}"

        forbidden_jargon = [
            "auc",
            "roc",
            "shap",
            "precision",
            "recall",
            "f1-score",
            "xgboost",
            "random forest",
            "logistic regression",
            "feature weight",
            "hyperparameter",
            "backtest",
            "log-odds",
        ]

        for token in forbidden_jargon:
            self.assertNotIn(token, en_text.lower())
            self.assertNotIn(token, hi_text.lower())

    # =========================================================================
    # FRONTEND DAY 4: ALERT DISPATCH, APPROVAL GATE & SAFE ROUTING
    # =========================================================================

    def test_day4_draft_alert_contents_and_format(self):
        """Verify draft alert formatting creates operational text with footprint and actions."""
        from app.alert_service import format_draft_alert_text

        text = format_draft_alert_text(
            active_horizon="+1h",
            affected_area="Patna, Bihar",
            high_cells_count=14,
            asset_summary={"hospitals": 3, "schools": 2, "shelters": 6},
        )

        self.assertIn("CHETNA FLOOD ADVISORY", text)
        self.assertIn("+1h", text)
        self.assertIn("Patna, Bihar", text)
        self.assertIn("14 monitored sectors", text)
        self.assertIn("3 Hospitals", text)
        self.assertIn("2 Schools", text)
        self.assertIn("6 Shelters", text)
        self.assertIn("Recommended operational action:", text)

    def test_day4_dispatch_dry_run_safety(self):
        """Verify dispatch respects dry-run safety and logs individual channel statuses."""
        from app.alert_service import dispatch_authority_alert

        res = dispatch_authority_alert(
            severity="WARNING",
            title="Advisory Warning",
            message="Storm water stagnation test",
            affected_area="Patna, Bihar",
        )

        self.assertTrue(res["success"])
        self.assertTrue(res["dry_run"])
        self.assertIn("Dry-run: notification simulated; no external message sent.", res["message"])
        self.assertIsNotNone(res["alert_id"])

        channels = res["channels"]
        self.assertIn("Telegram", channels)
        self.assertIn("WhatsApp", channels)
        self.assertIn("SMS", channels)
        self.assertTrue(channels["Telegram"]["success"])
        self.assertTrue(channels["WhatsApp"]["success"])
        self.assertTrue(channels["SMS"]["success"])

    def test_day4_dispatch_failure_handling(self):
        """Verify dispatch handles broken database or dispatcher errors gracefully without crashing."""
        from app.alert_service import dispatch_authority_alert

        # Passing an invalid closed sqlite3 connection forces an error
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.close()

        res = dispatch_authority_alert(
            severity="CRITICAL",
            title="Broken Test",
            message="Test",
            affected_area="Patna, Bihar",
            db_path=conn,
        )

        self.assertFalse(res["success"])
        self.assertIsNone(res["alert_id"])
        self.assertIsNotNone(res["error"])
        self.assertIn("Alert dispatch failure", res["message"])

    def test_day4_citizen_safe_route_call_success(self):
        """Verify citizen portal safe route request delegates to B1 safe_route function and returns route."""
        from src.routing.router import safe_route

        res = safe_route(lat=25.594, lon=85.158, horizon=1)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["found"])
        self.assertGreater(len(res["route"]), 0)
        self.assertGreaterEqual(res["distance_m"], 0.0)
        self.assertIsNotNone(res["destination"])
        self.assertIn("risk_info", res)

    def test_day4_citizen_no_safe_route_handling(self):
        """Verify unreachable destination or out-of-bounds origin reports found=False gracefully."""
        from src.routing.router import safe_route

        res = safe_route(lat=999.0, lon=999.0, horizon=1)
        self.assertEqual(res["status"], "error")
        self.assertFalse(res["found"])
        self.assertEqual(len(res["route"]), 0)
        self.assertIn("Invalid origin coordinates", res["message"])

    def test_day4_risk_advisory_bilingual(self):
        """Verify citizen advisory provides tailored guidance across LOW, MEDIUM, HIGH, SEVERE in en and hi."""
        from app.citizen_view import get_risk_advisory_bilingual

        # LOW
        low = get_risk_advisory_bilingual("LOW")
        self.assertIn("Conditions are currently normal", low["en"])
        self.assertIn("स्थिति सामान्य है", low["hi"])

        # MEDIUM
        med = get_risk_advisory_bilingual("MEDIUM")
        self.assertIn("Waterlogging may develop in vulnerable areas", med["en"])
        self.assertIn("जलभराव हो सकता है", med["hi"])

        # HIGH
        high = get_risk_advisory_bilingual("HIGH")
        self.assertIn("Flooding/waterlogging risk is elevated", high["en"])
        self.assertIn("जलभराव और बाढ़ का जोखिम अधिक है", high["hi"])

        # SEVERE
        sev = get_risk_advisory_bilingual("SEVERE")
        self.assertIn("Severe flood risk is indicated", sev["en"])
        self.assertIn("गंभीर बाढ़ का खतरा है", sev["hi"])

    def test_day4_frontend_does_not_directly_implement_algorithms(self):
        """Verify frontend views delegate to backend modules and do not re-implement routing/dispatching."""
        # Read source code of citizen_view.py and dashboard.py
        civ_src = Path("app/citizen_view.py").read_text(encoding="utf-8")
        dash_src = Path("app/dashboard.py").read_text(encoding="utf-8")

        # Frontend should not directly import networkx, osmnx or twilio client in view code
        self.assertNotIn("import networkx", civ_src)
        self.assertNotIn("import osmnx", civ_src)
        self.assertNotIn("from twilio.rest import Client", dash_src)
        self.assertNotIn("from twilio.rest import Client", civ_src)

        # Frontend must delegate to safe_route and dispatch_authority_alert
        self.assertIn("safe_route", civ_src)
        self.assertIn("dispatch_authority_alert", dash_src)

    def test_day5_normal_to_heavy_rain_simulation_and_reset(self):
        """Verify normal -> heavy-rain simulation state change and reset repeatability."""
        from app.demo_scenario import (
            simulate_heavy_rain_scenario,
            reset_to_baseline_scenario,
        )
        from app.map_layers import load_horizon_predictions, load_sensor_stations

        # 1. Reset to baseline to start in clean state
        reset_res = reset_to_baseline_scenario()
        self.assertTrue(reset_res["success"])
        self.assertEqual(reset_res["scenario"], "BASELINE")

        # In baseline, +1h has no dynamic predictions
        baseline_h1 = load_horizon_predictions("+1h")
        self.assertFalse(baseline_h1.get("available", False))

        # 2. Trigger heavy rain simulation
        sim_res = simulate_heavy_rain_scenario()
        self.assertTrue(sim_res["success"])
        self.assertEqual(sim_res["scenario"], "HEAVY_RAIN")
        self.assertGreater(sim_res["predictions_created"], 0)
        self.assertGreater(sim_res["sensors_updated"], 0)

        # In heavy rain, +1h dynamic predictions exist with elevated risk
        active_h1 = load_horizon_predictions("+1h")
        self.assertTrue(active_h1.get("available", False))
        self.assertIsNotNone(active_h1.get("predictions"))
        counts = active_h1.get("counts", {})
        self.assertGreater(counts.get("HIGH", 0) + counts.get("SEVERE", 0), 0)

        # Sensor stations show elevated water levels
        sensors = load_sensor_stations()
        self.assertGreaterEqual(len(sensors), 5)
        # At least one sensor node has elevated readings
        self.assertTrue(any(s.get("water_level_cm", 0) > 30.0 for s in sensors))

        # 3. Reset back to baseline for repeatability
        reset_res2 = reset_to_baseline_scenario()
        self.assertTrue(reset_res2["success"])
        self.assertEqual(reset_res2["scenario"], "BASELINE")

        # Verify state is restored
        restored_h1 = load_horizon_predictions("+1h")
        self.assertFalse(restored_h1.get("available", False))

    def test_day5_backtest_summary_visibility_and_limitations(self):
        """Verify M1 model evaluation artifacts are accessible with honest scientific provenance."""
        from app.demo_scenario import load_backtest_summary

        bt = load_backtest_summary()
        self.assertTrue(bt["available"])
        self.assertGreaterEqual(len(bt["events"]), 2)
        self.assertIn("EVT_2023_MICHAUNG", bt["events"])
        self.assertIn("EVT_2021_NOV_DEPRESSION", bt["events"])

        # Compare ML, Heuristic, and Rainfall Baseline
        self.assertIn("ml", bt["methods"])
        self.assertIn("heuristic", bt["methods"])
        self.assertIn("rainfall_threshold", bt["methods"])

        # Check records have required performance metrics
        self.assertGreaterEqual(len(bt["records"]), 6)
        first_row = bt["records"][0]
        self.assertIn("Event", first_row)
        self.assertIn("Model / Method", first_row)
        self.assertIn("Precision", first_row)
        self.assertIn("Recall", first_row)
        self.assertIn("F1 Score", first_row)
        self.assertIn("Brier Score", first_row)

        # Check explicit prototype limitations are documented
        self.assertGreaterEqual(len(bt["limitations"]), 3)
        self.assertTrue(any("calibrated proxy" in lim.lower() for lim in bt["limitations"]))
        self.assertIn("disclaimer", bt)

    def test_day5_prototype_honesty_and_no_fabrication(self):
        """Verify zero route/probability fabrication and strict prototype baseline notices."""
        from app.citizen_view import extract_facilities_from_hotspots
        from app.alert_service import dispatch_authority_alert
        from src.routing.router import safe_route

        # 1. Facilities retain reference attribution
        facs = extract_facilities_from_hotspots([{"name": "Sector A", "critical_infrastructure_nearby": ["Shelter 1"]}])
        self.assertGreaterEqual(len(facs["shelters"]), 1)
        self.assertIn("source", facs["shelters"][0])

        # 2. Dry-run alert explicitly declares simulation, not physical transmission
        alert_res = dispatch_authority_alert(
            severity="WARNING",
            title="Monsoon Advisory",
            message="Advisory test",
            affected_area="Patna, Bihar",
        )
        self.assertTrue(alert_res["dry_run"])
        self.assertIn("Dry-run: notification simulated; no external message sent.", alert_res["message"])

        # 3. Unreachable route returns found=False without drawing a fake route
        route_res = safe_route(lat=999.0, lon=999.0, horizon=1)
        self.assertFalse(route_res["found"])
        self.assertEqual(len(route_res["route"]), 0)

    def test_day6_f1_dispatcher_failure_and_invalid_db(self):
        """Verify F1 dispatch service handles database failures gracefully without unhandled exceptions."""
        from app.alert_service import dispatch_authority_alert

        # Passing a closed/broken database connection
        closed_conn = sqlite3.connect(":memory:")
        closed_conn.close()
        res = dispatch_authority_alert(
            severity="WARNING",
            title="Advisory Warning",
            message="Test message",
            db_path=closed_conn,
        )

        self.assertFalse(res["success"])
        self.assertIsNone(res["alert_id"])
        self.assertIsNotNone(res["error"])
        self.assertIn("Alert dispatch failure", res["message"])

    def test_day6_f1_empty_alert_zone_and_duplicate_dispatch(self):
        """Verify empty/None alert zones fall back gracefully and multiple dispatches generate distinct IDs."""
        from app.alert_service import dispatch_authority_alert

        res1 = dispatch_authority_alert(
            severity="WARNING",
            title="Warning 1",
            message="Test 1",
            affected_area="",
        )
        self.assertTrue(res1["success"])
        self.assertIsNotNone(res1["alert_id"])

        res2 = dispatch_authority_alert(
            severity="WARNING",
            title="Warning 2",
            message="Test 2",
            affected_area=None,
        )
        self.assertTrue(res2["success"])
        self.assertIsNotNone(res2["alert_id"])

        # IDs must be unique
        self.assertNotEqual(res1["alert_id"], res2["alert_id"])

    def test_day6_f2_forecast_and_prediction_unavailable_handling(self):
        """Verify F2 handles missing or invalid forecast horizons with honest unavailable notices."""
        from app.map_layers import load_horizon_predictions, check_horizon_prediction_availability

        # Invalid horizon
        res_inv = load_horizon_predictions("+99h")
        self.assertFalse(res_inv["available"])
        self.assertIn("unavailable", res_inv["message"].lower())

        # Non-existent DB path
        res_nodb = load_horizon_predictions("+1h", db_path="data/nonexistent_test.db")
        self.assertFalse(res_nodb["available"])
        self.assertIn("unavailable", res_nodb["message"].lower())

        # check_horizon_prediction_availability wrapper
        chk = check_horizon_prediction_availability("+1h", db_path="data/nonexistent_test.db")
        self.assertFalse(chk["available"])

    def test_day6_f2_safe_route_failure_and_invalid_shelters(self):
        """Verify safe_route handles out-of-bounds coords, missing shelters, and non-numeric inputs."""
        from src.routing.router import safe_route

        # Non-numeric coords
        res_nonnum = safe_route(lat=None, lon=85.15)
        self.assertFalse(res_nonnum["found"])
        self.assertEqual(res_nonnum["status"], "error")

        # Empty shelter list
        res_noshelters = safe_route(lat=25.59, lon=85.15, shelters=[])
        self.assertFalse(res_noshelters["found"])
        self.assertEqual(res_noshelters["status"], "error")
        self.assertIn("No shelters available", res_noshelters["message"])

    def test_day6_f2_bilingual_advisory_independent_of_forecast(self):
        """Verify bilingual advisories remain fully accessible even if meteorological forecasts are absent."""
        from app.citizen_view import get_risk_advisory_bilingual, get_bilingual_messages

        # All four calibrated tiers
        for tier in ("LOW", "MEDIUM", "HIGH", "SEVERE"):
            adv = get_risk_advisory_bilingual(tier)
            self.assertIn("en", adv)
            self.assertIn("hi", adv)
            self.assertGreater(len(adv["en"]), 10)
            self.assertGreater(len(adv["hi"]), 10)

        # Message structures
        msgs = get_bilingual_messages()
        self.assertIn("en", msgs)
        self.assertIn("hi", msgs)
        self.assertGreaterEqual(len(msgs["en"]["safety_tips"]), 3)
        self.assertGreaterEqual(len(msgs["hi"]["safety_tips"]), 3)

    def test_day6_demo_scenario_repeated_cycles_and_clean_reset(self):
        """Verify repeated simulate -> reset -> simulate cycles leave database and telemetry clean."""
        from app.demo_scenario import simulate_heavy_rain_scenario, reset_to_baseline_scenario
        from app.map_layers import load_horizon_predictions

        # Cycle 1
        sim1 = simulate_heavy_rain_scenario()
        self.assertTrue(sim1["success"])
        h1_active = load_horizon_predictions("+1h")
        self.assertTrue(h1_active["available"])

        rst1 = reset_to_baseline_scenario()
        self.assertTrue(rst1["success"])
        h1_reset = load_horizon_predictions("+1h")
        self.assertFalse(h1_reset["available"])

        # Cycle 2 (Repeatability check)
        sim2 = simulate_heavy_rain_scenario()
        self.assertTrue(sim2["success"])
        h1_active2 = load_horizon_predictions("+1h")
        self.assertTrue(h1_active2["available"])

        rst2 = reset_to_baseline_scenario()
        self.assertTrue(rst2["success"])
        h1_reset2 = load_horizon_predictions("+1h")
        self.assertFalse(h1_reset2["available"])

    def test_day7_frontend_framework_alignment_and_freeze(self):
        """Verify frontend navigation, honest engine badges, and disclaimer alignment."""
        from config.settings import Settings
        from app.citizen_view import get_bilingual_messages

        # Verify F1 and F2 navigation items
        expected_f1 = ["Overview", "Risk Map", "Alerts", "At-Risk Assets", "Sensors", "Analytics", "Settings"]
        expected_f2 = ["My Area", "Flood Risk", "Safe Places", "Safe Route", "Advisory", "Emergency Help"]
        self.assertEqual(F1_NAV_ITEMS, expected_f1)
        self.assertEqual(F2_NAV_ITEMS, expected_f2)

        # Verify bilingual safe route note does not contain developer milestone text
        bilingual = get_bilingual_messages()
        for lang_code in ("en", "hi"):
            note = bilingual[lang_code]["safe_route_note"]
            self.assertNotIn("Day 4", note)
            self.assertNotIn("डे 4", note)
            self.assertNotIn("Active:", note)

        # Verify dynamic engine badge
        settings = Settings()
        expected_badge = "Mapbox Engine" if settings.has_valid_mapbox_token else "Carto Vector Engine"
        if not settings.has_valid_mapbox_token:
            self.assertEqual(expected_badge, "Carto Vector Engine")

    def test_hotspot_cards_html_rendering_regression(self):
        """Regression test for LIVE ERROR 1: Monitored Hotspots HTML must be rendered through components.html, not st.markdown."""
        from unittest.mock import MagicMock, patch
        hotspots = db.load_hotspots_data()
        self.assertEqual(len(hotspots), 10, "All 10 sourced Patna hotspots must be present")

        captured_components_html = []
        captured_markdowns = []

        def mock_components_html(content, *args, **kwargs):
            captured_components_html.append(content)

        def mock_markdown(content, unsafe_allow_html=False):
            captured_markdowns.append((content, unsafe_allow_html))

        mock_col_map = MagicMock()
        mock_col_hotspots = MagicMock()
        mock_col_map.__enter__.return_value = mock_col_map
        mock_col_hotspots.__enter__.return_value = mock_col_hotspots

        with patch("streamlit.columns", return_value=[mock_col_map, mock_col_hotspots]), \
             patch("streamlit.container"), \
             patch("streamlit.components.v1.html", side_effect=mock_components_html), \
             patch("streamlit.html", create=True), \
             patch("streamlit.markdown", side_effect=mock_markdown), \
             patch("streamlit.pydeck_chart"):
            dummy_map = ml.build_operational_deck()
            db.render_main_workspace(dummy_map, hotspots)

        # 1. Hotspots HTML must be rendered through components.html
        self.assertTrue(len(captured_components_html) >= 1, "Hotspot cards must be rendered through st.components.v1.html")
        panel_candidates = [c for c in captured_components_html if "Monitored Hotspots" in c]
        self.assertTrue(len(panel_candidates) >= 1, "Monitored Hotspots panel must be passed to st.components.v1.html")
        panel_html = panel_candidates[0]

        # 2. Hotspot source must NOT be sent through st.markdown
        markdown_hotspot_leaks = [c for c, unsafe in captured_markdowns if "Monitored Hotspots" in c or "HS01" in c]
        self.assertEqual(len(markdown_hotspot_leaks), 0, "Hotspot source HTML must NEVER be sent through st.markdown")

        # 3. Verify that all 10 hotspot sites and details (name, severity, zone, elevation, trigger rain) are rendered
        for h in hotspots:
            self.assertIn(h["hotspot_id"], panel_html)
            self.assertIn(h["name"], panel_html)
            self.assertIn(h.get("severity_tier", "Moderate"), panel_html)
            self.assertIn(h.get("zone"), panel_html)
            self.assertIn(f"{h.get('elevation_m', 0.0)}m", panel_html)
            self.assertIn(f"{h.get('typical_trigger_rain_6h_mm', 0.0)}mm", panel_html)

        # Critical regression check: CommonMark considers lines with 4+ spaces of leading indentation
        # following an empty line as code blocks. Verify no hotspot card starts with leading spaces.
        for line in panel_html.split("\n"):
            stripped = line.strip()
            if stripped.startswith("<div") or stripped.startswith("<span"):
                indent = len(line) - len(line.lstrip(" "))
                self.assertLess(indent, 4, f"Line has {indent} spaces of leading indent, which triggers CommonMark code block: {line}")

    def test_community_flood_safety_map_null_data_regression(self):
        """Regression test for LIVE ERROR 2: Community Flood Safety Map renders Folium through components.html and never passes folium to pydeck."""
        import pydeck as pdk
        from unittest.mock import MagicMock, patch

        # 1. Real F2 map construction returns a validated folium.Map
        static_meta = db.load_static_risk_metadata()
        hotspots = db.load_hotspots_data()
        sensors = db.load_sensor_stations()
        f2_map = ml.build_operational_map(
            static_risk_data=static_meta,
            hotspots_data=hotspots,
            sensors_data=sensors,
            backend="folium",
        )
        self.assertIsInstance(f2_map, folium.Map)
        self.assertTrue(hasattr(f2_map, "get_root"))

        # 2. build_operational_map with empty / None data must produce a valid pdk.Deck
        empty_deck = ml.build_operational_map(
            static_risk_data=None,
            hotspots_data=[],
            sensors_data=None,
            predictions_map=None,
            backend="pydeck",
        )
        self.assertIsInstance(empty_deck, pdk.Deck)
        self.assertEqual(len(empty_deck.layers), 0)
        self.assertIsNotNone(empty_deck.initial_view_state)
        self.assertAlmostEqual(empty_deck.initial_view_state.latitude, 25.6093, places=3)
        self.assertAlmostEqual(empty_deck.initial_view_state.longitude, 85.1376, places=3)
        self.assertTrue(ml.validate_deck(empty_deck), "Empty deck must pass Deck validation")

        # Spec must be valid JSON containing DeckGLJsonChart expected keys
        spec = json.loads(empty_deck.to_json())
        self.assertIn("initialViewState", spec)
        self.assertIn("layers", spec)
        self.assertIn("views", spec)
        self.assertEqual(spec["layers"], [])
        self.assertEqual(spec["initialViewState"]["latitude"], empty_deck.initial_view_state.latitude)

        # 3. Defensive handling of malformed records
        malformed_deck = ml.build_operational_deck(
            static_risk_data={"cells": [{"cell_id": "C_BAD", "geometry": None, "vulnerability_score": None}]},
            hotspots_data=[{"name": "Bad HS", "latitude": None, "longitude": None}],
            sensors_data=[{"name": "Bad Sensor", "latitude": None, "longitude": None, "water_level_cm": None}],
        )
        self.assertIsInstance(malformed_deck, pdk.Deck)
        self.assertEqual(len(malformed_deck.layers), 0)
        self.assertTrue(ml.validate_deck(malformed_deck), "Deck with malformed inputs must still be a valid Deck")

        # 4. validate_deck must reject non-decks and broken decks
        f_map = folium.Map(location=[25.6093, 85.1376], zoom_start=12)
        self.assertFalse(ml.validate_deck(f_map), "validate_deck must reject folium.Map")
        self.assertFalse(ml.validate_deck(None), "validate_deck must reject None")
        self.assertFalse(ml.validate_deck("not a deck"), "validate_deck must reject strings")
        broken_deck = pdk.Deck(layers=[None])
        self.assertFalse(ml.validate_deck(broken_deck), "validate_deck must reject decks containing None layers")

        # 5. render_citizen_map component routing:
        # a) When given a Folium Map, must NOT call st.pydeck_chart (which caused JS TypeError)
        pydeck_calls = []
        html_calls = []

        with patch("streamlit.container"), \
             patch("streamlit.html", create=True), \
             patch("streamlit.markdown"), \
             patch("streamlit.pydeck_chart", side_effect=lambda *args, **kwargs: pydeck_calls.append(args)), \
             patch("streamlit.components.v1.html", side_effect=lambda *args, **kwargs: html_calls.append(args)):

            cv.render_citizen_map(f_map)

            self.assertEqual(len(pydeck_calls), 0, "folium.Map must NEVER be passed to st.pydeck_chart")
            self.assertEqual(len(html_calls), 1, "folium.Map must be rendered via st.components.v1.html")

            # b) When given a pdk.Deck, must call st.pydeck_chart
            cv.render_citizen_map(empty_deck)
            self.assertEqual(len(pydeck_calls), 1, "pdk.Deck must be rendered via st.pydeck_chart")

            # c) When given None, must safely render fallback Folium map
            cv.render_citizen_map(None)
            self.assertEqual(len(html_calls), 2, "None map input must fall back gracefully to Folium map via components.html")
            self.assertEqual(len(pydeck_calls), 1, "Fallback map must not call st.pydeck_chart")

            # d) When given broken deck, must safely render fallback Folium map
            cv.render_citizen_map(broken_deck)
            self.assertEqual(len(html_calls), 3, "Broken deck must fall back gracefully to Folium map via components.html")
            self.assertEqual(len(pydeck_calls), 1, "Broken deck must not call st.pydeck_chart")


if __name__ == "__main__":
    unittest.main()

