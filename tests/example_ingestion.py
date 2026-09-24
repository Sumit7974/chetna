"""Example script demonstrating the Chetna Day 2 B1 forecast ingestion and database storage.

This script demonstrates:
1. Loading and parsing offline mock Open-Meteo response data without any network calls (Requirement 9).
2. Generating structured rainfall horizons (+1h, +3h, +6h, past 24h) for Chetna's risk model.
3. Storing the 6-hour forecast in the SQLite 'forecasts' table (Day 2 B1 requirement).
4. Retrieving the stored forecast from SQLite to confirm persistence.
5. (Optional) Fetching live data from Open-Meteo when the --live flag is passed.
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.forecasts import DEFAULT_DB_PATH, get_forecast_history, get_latest_forecast
from src.ingestion.weather import (
    OpenMeteoClient,
    WeatherForecastResult,
    fetch_and_store_forecast,
    fetch_weather_forecast,
    load_mock_forecast,
    store_forecast_result,
)


def run_mock_example(mock_file: Path, db_path: Path) -> WeatherForecastResult:
    print("=" * 70)
    print("CHETNA FLOOD WARNING SYSTEM — DAY 2 B1 FORECAST & DB DEMO (MOCK)")
    print("=" * 70)
    print(f"Loading sample response from: {mock_file.name} (no internet required)...")

    result = load_mock_forecast(mock_file, reference_time="2026-09-24T00:00")

    print("\n[1] Location Metadata:")
    print(f"  • Latitude / Longitude: {result.latitude:.4f}, {result.longitude:.4f}")
    print(f"  • Timezone:             {result.timezone}")
    print(f"  • Elevation:            {result.elevation:.1f} m")
    print(f"  • Reference Time:       {result.reference_time}")
    print(f"  • Offline Cache Source: {result.from_cache}")

    print("\n[2] Aggregated 6-Hour Rainfall Horizons (Chetna Feature Inputs):")
    summary = result.summary
    print(f"  • Rain in next 1 hour  (+1h): {summary.rain_1h:6.2f} mm")
    print(f"  • Rain in next 3 hours (+3h): {summary.rain_3h:6.2f} mm")
    print(f"  • Rain in next 6 hours (+6h): {summary.rain_6h:6.2f} mm")
    print(f"  • Rain in past 24h   (-24h): {summary.rain_past_24h:6.2f} mm")

    print("\n[3] Next 6 Hours Hourly Breakdown:")
    for rec in result.next_6h_records:
        print(f"  {rec.timestamp} -> Precipitation: {rec.precipitation_mm:5.2f} mm | Rain: {rec.rain_mm:5.2f} mm")

    print(f"\n[4] Storing 6-Hour Forecast in SQLite: {db_path}...")
    row_id = store_forecast_result(result, db_path=db_path)
    print(f"  -> Successfully stored! Row ID: {row_id}")

    print("\n[5] Retrieving Latest Forecast Stored in SQLite:")
    stored = get_latest_forecast(db_path)
    print(f"  Payload from SQLite: {json.dumps(stored, indent=4)}")

    print("\n" + "=" * 70)
    print("Day 2 B1 Mock demo completed: 6-hour forecast stored and verified in DB!")
    print("=" * 70)
    return result


def run_live_example(latitude: float = 13.0827, longitude: float = 80.2707, db_path: Path = DEFAULT_DB_PATH) -> WeatherForecastResult:
    print("\n" + "=" * 70)
    print("CHETNA FLOOD WARNING SYSTEM — DAY 2 B1 FORECAST & DB DEMO (LIVE)")
    print("=" * 70)
    print(f"Querying Open-Meteo for coordinates: lat={latitude}, lon={longitude}...")

    result, row_id = fetch_and_store_forecast(
        latitude=latitude,
        longitude=longitude,
        db_path=db_path,
        cache_dir=PROJECT_ROOT / "data" / "cache",
        use_cache_on_failure=True,
    )

    print("\n[1] Live Location Metadata:")
    print(f"  • Latitude / Longitude: {result.latitude:.4f}, {result.longitude:.4f}")
    print(f"  • Timezone:             {result.timezone}")
    print(f"  • Elevation:            {result.elevation:.1f} m")
    print(f"  • Reference Time:       {result.reference_time}")
    print(f"  • From Cache Fallback:  {result.from_cache}")

    print("\n[2] Aggregated Rainfall Horizons:")
    summary = result.summary
    print(f"  • Rain in next 1 hour  (+1h): {summary.rain_1h:6.2f} mm")
    print(f"  • Rain in next 3 hours (+3h): {summary.rain_3h:6.2f} mm")
    print(f"  • Rain in next 6 hours (+6h): {summary.rain_6h:6.2f} mm")
    print(f"  • Rain in past 24h   (-24h): {summary.rain_past_24h:6.2f} mm")

    print(f"\n[3] Saved in SQLite database: Row ID {row_id}")
    stored = get_latest_forecast(db_path)
    print(f"  Payload from SQLite: {json.dumps(stored, indent=4)}")

    print("\n" + "=" * 70)
    print("Live API ingestion and DB storage completed successfully!")
    print("=" * 70)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chetna Day 2 B1 forecast ingestion and storage runner.")
    parser.add_argument("--live", action="store_true", help="Fetch live data from Open-Meteo API.")
    parser.add_argument("--lat", type=float, default=13.0827, help="Latitude (default: 13.0827 Chennai)")
    parser.add_argument("--lon", type=float, default=80.2707, help="Longitude (default: 80.2707 Chennai)")
    parser.add_argument("--db", type=str, default=str(PROJECT_ROOT / "data" / "chetna.db"), help="SQLite database path")
    args = parser.parse_args()

    default_mock_path = PROJECT_ROOT / "tests" / "fixtures" / "sample_openmeteo_response.json"
    target_db = Path(args.db)

    # Always demonstrate mock/offline execution first
    run_mock_example(default_mock_path, target_db)

    # If --live requested, run live query
    if args.live:
        run_live_example(latitude=args.lat, longitude=args.lon, db_path=target_db)
