"""Automated test suite verifying Model Performance and Accuracy Percentage on Chetna website.

Verifies:
1. The Analytics page displays the actual evaluation accuracy (held-out Patna evaluation).
2. The displayed value matches the evaluation artifact exactly.
3. Precision, Recall, and F1 Score match the artifact.
4. Test sample count is displayed correctly.
5. No fabricated fallback percentage is displayed.
6. Missing evaluation data produces an honest "Evaluation data unavailable" state rather than a fake number.
7. Existing F1 and F2 functionality remains unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.dashboard import render_model_performance
from app.demo_scenario import (
    DEFAULT_MODEL_PERFORMANCE_PATH,
    load_backtest_summary,
    load_model_performance,
    reset_to_baseline_scenario,
)


class TestModelPerformanceUI:
    """Test suite for Model Performance section in F1 Analytics."""

    @classmethod
    def setup_class(cls) -> None:
        reset_to_baseline_scenario()

    def test_analytics_page_displays_actual_evaluation_accuracy(self) -> None:
        """1. The Analytics page displays the actual reproducible evaluation accuracy."""
        perf = load_model_performance()
        assert perf["available"] is True
        assert perf["accuracy"] is not None
        # Must be genuine held-out evaluation accuracy (92.90% for primary +1h horizon)
        assert pytest.approx(perf["accuracy"], rel=1e-3) == 0.929002
        assert perf["accuracy_pct"] == "92.90%"

        # Test rendering captures Accuracy metric
        metrics_called = {}
        mock_st = MagicMock()
        def fake_metric(label, value, *args, **kwargs):
            metrics_called[label] = value

        mock_st.metric.side_effect = fake_metric
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()]

        # Patch streamlit in dashboard
        with patch("app.dashboard.st.metric", side_effect=fake_metric), \
             patch("app.dashboard.st.columns", return_value=[MagicMock() for _ in range(6)]), \
             patch("app.dashboard.st.markdown"), \
             patch("app.dashboard.st.radio", return_value="+1h (Lead Time 1h)"):
            render_model_performance(perf_data=perf)

        assert "Accuracy" in metrics_called
        assert metrics_called["Accuracy"] == "92.90%"

    def test_displayed_value_matches_evaluation_artifact(self) -> None:
        """2. The displayed value matches the evaluation artifact directly."""
        artifact_path = Path("data/m1/backtest/patna_held_out_metrics.json")
        assert artifact_path.exists(), f"Missing artifact: {artifact_path}"

        with open(artifact_path, "r", encoding="utf-8") as f:
            artifact_data = json.load(f)

        perf = load_model_performance(path=artifact_path)
        assert perf["available"] is True
        assert pytest.approx(perf["accuracy"], rel=1e-4) == artifact_data["accuracy"]
        assert perf["accuracy_pct"] == artifact_data["accuracy_pct"]
        assert perf["accuracy_pct"] == "92.90%"

        # Test metric render matches artifact exactly
        metrics_called = {}
        def fake_metric(label, value, *args, **kwargs):
            metrics_called[label] = value

        with patch("app.dashboard.st.metric", side_effect=fake_metric), \
             patch("app.dashboard.st.columns", return_value=[MagicMock() for _ in range(6)]), \
             patch("app.dashboard.st.markdown"), \
             patch("app.dashboard.st.radio", return_value="+1h (Lead Time 1h)"):
            render_model_performance(perf_data=perf)

        assert metrics_called["Accuracy"] == artifact_data["accuracy_pct"]

    def test_precision_recall_f1_match_artifact(self) -> None:
        """3. Precision/recall/F1 match the artifact."""
        artifact_path = Path("data/m1/backtest/patna_held_out_metrics.json")
        with open(artifact_path, "r", encoding="utf-8") as f:
            artifact_data = json.load(f)

        perf = load_model_performance(path=artifact_path)
        assert perf["available"] is True
        assert pytest.approx(perf["precision"], rel=1e-3) == artifact_data["precision"]
        assert pytest.approx(perf["recall"], rel=1e-3) == artifact_data["recall"]
        assert pytest.approx(perf["f1_score"], rel=1e-3) == artifact_data["f1_score"]

        assert perf["precision_pct"] == artifact_data["precision_pct"]  # "17.14%"
        assert perf["recall_pct"] == artifact_data["recall_pct"]        # "64.00%"
        assert perf["f1_pct"] == artifact_data["f1_pct"]                # "27.04%"

        metrics_called = {}
        def fake_metric(label, value, *args, **kwargs):
            metrics_called[label] = value

        with patch("app.dashboard.st.metric", side_effect=fake_metric), \
             patch("app.dashboard.st.columns", return_value=[MagicMock() for _ in range(6)]), \
             patch("app.dashboard.st.markdown"), \
             patch("app.dashboard.st.radio", return_value="+1h (Lead Time 1h)"):
            render_model_performance(perf_data=perf)

        assert metrics_called["Precision"] == artifact_data["precision_pct"]
        assert metrics_called["Recall"] == artifact_data["recall_pct"]
        assert metrics_called["F1 Score"] == artifact_data["f1_pct"]
        assert metrics_called["Evaluation"] == "Patna held-out test set"

    def test_sample_count_displayed_correctly(self) -> None:
        """4. Test sample count is displayed correctly."""
        artifact_path = Path("data/m1/backtest/patna_held_out_metrics.json")
        with open(artifact_path, "r", encoding="utf-8") as f:
            artifact_data = json.load(f)

        perf = load_model_performance(path=artifact_path)
        assert perf["test_samples"] == artifact_data["test_samples"]
        assert perf["test_samples"] == 3648

        metrics_called = {}
        def fake_metric(label, value, *args, **kwargs):
            metrics_called[label] = value

        with patch("app.dashboard.st.metric", side_effect=fake_metric), \
             patch("app.dashboard.st.columns", return_value=[MagicMock() for _ in range(6)]), \
             patch("app.dashboard.st.markdown"), \
             patch("app.dashboard.st.radio", return_value="+1h (Lead Time 1h)"):
            render_model_performance(perf_data=perf)

        # 3,648 samples formatted cleanly
        assert metrics_called["Test Samples"] in ("3,648", "3648")

        # Also verify multi-horizon aggregate samples (3648 * 3 = 10,944)
        with patch("app.dashboard.st.metric", side_effect=fake_metric), \
             patch("app.dashboard.st.columns", return_value=[MagicMock() for _ in range(6)]), \
             patch("app.dashboard.st.markdown"), \
             patch("app.dashboard.st.radio", return_value="All Horizons Combined"):
            render_model_performance(perf_data=perf)

        assert metrics_called["Test Samples"] in ("10,944", "10944")

    def test_no_fabricated_fallback_percentage(self) -> None:
        """5. No fabricated fallback percentage is displayed."""
        # When path is missing, no fallback numbers (like 95% or 0.0%) are fabricated
        perf_missing = load_model_performance(path="non_existent_results.json")
        assert perf_missing["available"] is False
        assert perf_missing["accuracy"] is None
        assert perf_missing["accuracy_pct"] is None
        assert perf_missing["precision"] is None
        assert perf_missing["recall"] is None
        assert perf_missing["f1_score"] is None

        # Verify no exaggerated claims exist in code
        dash_code = Path("app/dashboard.py").read_text(encoding="utf-8")
        demo_code = Path("app/demo_scenario.py").read_text(encoding="utf-8")
        backtest_code = Path("src/model/ml_backtest.py").read_text(encoding="utf-8")

        forbidden_phrases = [
            "chetna is 95% accurate",
            "95% prediction guarantee",
            "95% real-world accuracy",
            "95% accurate",
        ]
        for phrase in forbidden_phrases:
            assert phrase not in dash_code.lower()
            assert phrase not in demo_code.lower()
            assert phrase not in backtest_code.lower()


    def test_missing_evaluation_data_honest_unavailable_state(self) -> None:
        """6. Missing evaluation data produces an honest 'Evaluation data unavailable' state."""
        perf_missing = load_model_performance(path="non_existent_file_path_xyz.json")
        assert perf_missing["available"] is False
        assert perf_missing["status_text"] == "Evaluation data unavailable"

        info_calls = []
        metric_calls = []

        with patch("app.dashboard.st.info", side_effect=lambda msg: info_calls.append(msg)), \
             patch("app.dashboard.st.metric", side_effect=lambda l, v: metric_calls.append((l, v))), \
             patch("app.dashboard.st.markdown"):
            render_model_performance(perf_data=perf_missing)

        # Must report unavailable state cleanly
        assert any("Evaluation data unavailable" in msg for msg in info_calls)
        # Must NOT render any fake metrics
        assert len(metric_calls) == 0

    def test_existing_f1_f2_functionality_remains_unchanged(self) -> None:
        """7. Existing F1/F2 functionality remains unchanged."""
        import app.dashboard as db
        import app.citizen_view as cv

        # F1 helpers exist
        assert callable(db.render_header)
        assert callable(db.render_dominant_status)
        assert callable(db.render_summary_cards)
        assert callable(db.render_main_workspace)
        assert callable(db.render_alert_and_architecture_section)
        assert callable(db.render_footer)
        assert callable(db.render_sidebar)
        assert callable(db.render_model_performance)

        # F2 helpers exist
        assert callable(cv.render_citizen_header)
        assert callable(cv.render_citizen_status_card)
        assert callable(cv.render_citizen_view)

        # Backtest summary loading still works as expected
        bt_data = load_backtest_summary()
        assert "available" in bt_data
        assert "limitations" in bt_data
        assert "disclaimer" in bt_data

    def test_streamlit_apptest_analytics_model_performance(self) -> None:
        """Integration test using Streamlit AppTest for F1 -> Analytics -> Model Performance."""
        from streamlit.testing.v1 import AppTest

        root_entry = Path(__file__).resolve().parent.parent / "run_dashboard.py"
        at = AppTest.from_file(str(root_entry), default_timeout=30)
        at.run()
        assert not at.exception


        # Navigate to Analytics
        nav = [r for r in at.radio if r.label == "OPERATIONS NAVIGATION"][0]
        nav.set_value("Analytics").run()
        assert not at.exception

        m_dict = {m.label: m.value for m in at.metric}
        assert m_dict.get("Accuracy") == "92.90%"
        assert m_dict.get("Precision") == "17.14%"
        assert m_dict.get("Recall") == "64.00%"
        assert m_dict.get("F1 Score") == "27.04%"
        assert m_dict.get("Test Samples") == "3,648"
        assert m_dict.get("Evaluation") == "Patna held-out test set"

        # Test Horizon controls
        perf_radio = at.radio(key="model_perf_horizon_radio")
        assert perf_radio is not None

        # Switch to +3h
        perf_radio.set_value("+3h (Lead Time 3h)").run()
        assert not at.exception
        m_dict3 = {m.label: m.value for m in at.metric}
        assert m_dict3.get("Accuracy") == "93.67%"
        assert m_dict3.get("Precision") == "17.50%"
        assert m_dict3.get("Recall") == "56.00%"
        assert m_dict3.get("F1 Score") == "26.67%"
        assert m_dict3.get("Test Samples") == "3,648"

        # Switch to +6h
        perf_radio.set_value("+6h (Lead Time 6h)").run()
        assert not at.exception
        m_dict6 = {m.label: m.value for m in at.metric}
        assert m_dict6.get("Accuracy") == "94.33%"
        assert m_dict6.get("Precision") == "18.57%"
        assert m_dict6.get("Recall") == "52.00%"
        assert m_dict6.get("F1 Score") == "27.37%"
        assert m_dict6.get("Test Samples") == "3,648"

        # Switch to All Horizons Combined
        perf_radio.set_value("All Horizons Combined").run()
        assert not at.exception
        m_dict_all = {m.label: m.value for m in at.metric}
        assert m_dict_all.get("Accuracy") == "93.63%"
        assert m_dict_all.get("Precision") == "17.67%"
        assert m_dict_all.get("Recall") == "57.33%"
        assert m_dict_all.get("F1 Score") == "27.02%"
        assert m_dict_all.get("Test Samples") == "10,944"

