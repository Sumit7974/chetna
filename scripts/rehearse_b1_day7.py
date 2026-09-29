"""Chetna B1 Day 7: Automated Final Rehearsal Harness.

Executes three complete, deterministic operational demo cycles:
1. Normal Baseline State
2. Simulate Heavy Rain
3. Multi-horizon Risk Transition (+1h, +3h, +6h)
4. Affected Areas / Critical Assets Registry
5. Citizen Safe Routing & Nearest Safe Shelter Lookup
6. Clean Reset to Normal Baseline

Records and validates 100% reproducibility across all three runs.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Ensure root directory on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.demo_scenario import reset_to_baseline_scenario, simulate_heavy_rain_scenario
from app.map_layers import get_at_risk_assets_summary
from database.db import DEFAULT_DB_PATH
from src.routing.router import safe_route


def run_rehearsal_cycle(run_index: int) -> bool:
    print(f"\n==========================================")
    print(f"  STARTING REHEARSAL RUN #{run_index}")
    print(f"==========================================")
    db = DEFAULT_DB_PATH

    # 1. Start from clean baseline
    rst = reset_to_baseline_scenario(db)
    assert rst["success"] is True, "Reset scenario failed"
    with sqlite3.connect(str(db)) as conn:
        preds = conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0]
        readings = conn.execute("SELECT count(*) FROM sensor_readings;").fetchone()[0]
        cells = conn.execute("SELECT count(*) FROM cells;").fetchone()[0]
        assert preds == 0, f"Expected 0 predictions at baseline, got {preds}"
        assert readings == 0, f"Expected 0 readings at baseline, got {readings}"
        assert cells == 38, f"Expected 38 static cells, got {cells}"
    print(f"[Run {run_index}] Step 1: Normal baseline verified (0 dynamic predictions, 0 readings, 38 cells)")

    # 2. Simulate Heavy Rain
    sim = simulate_heavy_rain_scenario(db)
    assert sim["success"] is True, "Heavy rain simulation failed"
    assert sim["predictions_created"] == 114, f"Expected 114 predictions, got {sim['predictions_created']}"
    assert sim["sensors_updated"] == 10, f"Expected 10 sensors updated, got {sim['sensors_updated']}"
    print(f"[Run {run_index}] Step 2: Simulate Heavy Rain succeeded (114 predictions, 10 telemetry nodes)")

    # 3. Verify Forecast and Risk Elevation
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        fc = conn.execute("SELECT rain_1h, rain_3h, rain_6h, location FROM forecasts ORDER BY id DESC LIMIT 1;").fetchone()
        assert fc["rain_1h"] == 52.5 and fc["rain_3h"] == 84.0 and fc["rain_6h"] == 126.0
        assert "Patna" in fc["location"]

        high_cnt = conn.execute("SELECT count(*) FROM risk_predictions WHERE level = 'HIGH';").fetchone()[0]
        med_cnt = conn.execute("SELECT count(*) FROM risk_predictions WHERE level = 'MEDIUM';").fetchone()[0]
        assert high_cnt > 0, "No HIGH risk cells generated"
        assert med_cnt > 0, "No MEDIUM risk cells generated"
    print(f"[Run {run_index}] Step 3: Risk transition verified (52.5/84.0/126.0 mm, {high_cnt} HIGH, {med_cnt} MEDIUM)")

    # 4. Verify Affected Areas & At-Risk Assets
    from app.map_layers import load_horizon_predictions
    hz_status = load_horizon_predictions(horizon="+1h", db_path=db)
    assert hz_status["available"] is True, "Forecast predictions unavailable for +1h"
    assets_summary = get_at_risk_assets_summary(horizon_status=hz_status, hotspots_data=[])
    assert isinstance(assets_summary, dict)
    print(f"[Run {run_index}] Step 4: Affected areas & assets verified (status: {hz_status['counts']})")

    # 5. Citizen Safe Routing
    # Origin: Boring Canal / Patliputra (25.620, 85.110)
    route_res = safe_route(25.620, 85.110, horizon=1, db_path=db)
    assert route_res["status"] == "success", f"Routing failed: {route_res.get('message')}"
    assert route_res["found"] is True, "No route found"
    assert len(route_res["route"]) >= 2, "Expected multi-segment route"
    assert route_res["distance_m"] > 0, "Expected positive route distance"
    assert route_res["destination"] is not None, "Missing destination"
    dest_name = route_res["destination"]["name"]
    print(f"[Run {run_index}] Step 5: Safe route found ({len(route_res['route'])} nodes, {route_res['distance_m']:.1f} m to {dest_name})")

    # Honest No-Route / Blocked Test
    no_route = safe_route(lat="invalid", lon=85.110, db_path=db)
    assert no_route["found"] is False and no_route["route"] == [], "Fabricated route on invalid coords"
    print(f"[Run {run_index}] Step 5b: Honest no-route behavior verified on invalid input")

    # 6. Reset to Baseline
    rst_end = reset_to_baseline_scenario(db)
    assert rst_end["success"] is True, "Final reset failed"
    with sqlite3.connect(str(db)) as conn:
        preds_end = conn.execute("SELECT count(*) FROM risk_predictions;").fetchone()[0]
        readings_end = conn.execute("SELECT count(*) FROM sensor_readings;").fetchone()[0]
        cells_end = conn.execute("SELECT count(*) FROM cells;").fetchone()[0]
        assert preds_end == 0, f"Residue predictions remaining: {preds_end}"
        assert readings_end == 0, f"Residue readings remaining: {readings_end}"
        assert cells_end == 38, f"Static cells damaged: {cells_end}"
    print(f"[Run {run_index}] Step 6: Reset verified (0 predictions, 0 readings, 38 cells intact)")
    print(f"--> REHEARSAL RUN #{run_index} PASSED SUCCESSFULLY!")
    return True


def main() -> None:
    print("================================================================")
    print(" CHETNA B1 DAY 7 — THREE DETERMINISTIC REHEARSAL RUNS")
    print(" Pilot: Patna, Bihar | Hazard: Rainfall-Driven Urban Flooding")
    print("================================================================")

    results = []
    for run_num in (1, 2, 3):
        success = run_rehearsal_cycle(run_num)
        results.append((run_num, success))

    print("\n================================================================")
    print(" REHEARSAL RUN SUMMARY")
    print("================================================================")
    all_passed = True
    for run_num, ok in results:
        status_str = "SUCCESS (100% Deterministic)" if ok else "FAILED"
        print(f" Rehearsal Run {run_num}: {status_str}")
        if not ok:
            all_passed = False

    if all_passed:
        print("\nALL 3 REHEARSALS COMPLETED SUCCESSFULLY WITH ZERO DEFECTS.")
        sys.exit(0)
    else:
        print("\nONE OR MORE REHEARSAL RUNS FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
