"""Example script demonstrating the Chetna weather forecast ingestion module.

This script demonstrates:
1. Loading and parsing offline mock Open-Meteo response data without any network calls (Requirement 9).
2. Generating structured rainfall horizons (+1h, +3h, +6h, past 24h) for Chetna's risk model.
3. Formatting data ready for the Chetna SQLite 'forecasts' table.
4. (Optional) Fetching live data from Open-Meteo when the --live flag is passed.
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.weather import (
    OpenMeteoClient,
    WeatherForecastResult,
    fetch_weather_forecast,
    load_mock_forecast,
)


def run_mock_example(mock_file: Path) -> WeatherForecastResult:
    print("=" * 70)
    print("CHETNA FLOOD WARNING SYSTEM — WEATHER INGESTION (MOCK DEMO)")
    print("=" * 70)
    print(f"Loading sample response from: {mock_file.name} (no internet required)...")

    result = load_mock_forecast(mock_file, reference_time="2026-09-24T00:00")

    print("\n[1] Location Metadata:")
    print(f"  • Latitude / Longitude: {result.latitude:.4f}, {result.longitude:.4f}")
    print(f"  • Timezone:             {result.timezone}")
    print(f"  • Elevation:            {result.elevation:.1f} m")
    print(f"  • Reference Time:       {result.reference_time}")
    print(f"  • Offline Cache Source: {result.from_cache}")

    print("\n[2] Aggregated Rainfall Horizons (Chetna Feature Inputs):")
    summary = result.summary
    print(f"  • Rain in next 1 hour  (+1h): {summary.rain_1h:6.2f} mm")
    print(f"  • Rain in next 3 hours (+3h): {summary.rain_3h:6.2f} mm")
    print(f"  • Rain in next 6 hours (+6h): {summary.rain_6h:6.2f} mm")
    print(f"  • Rain in past 24h   (-24h): {summary.rain_past_24h:6.2f} mm")

    print("\n[3] SQLite 'forecasts' Table Record Contract:")
    db_record = result.to_db_record()
    print(f"  Schema: timestamp, rain_1h, rain_3h, rain_6h")
    print(f"  Payload: {json.dumps(db_record, indent=4)}")

    print("\n[4] Sample Hourly Breakdown (Next 6 Hours):")
    for rec in result.hourly_records[24:30]:
        print(f"  {rec.timestamp} -> Precipitation: {rec.precipitation_mm:5.2f} mm | Rain: {rec.rain_mm:5.2f} mm")

    print("\n" + "=" * 70)
    print("Mock ingestion demonstration completed successfully!")
    print("=" * 70)
    return result


def run_live_example(latitude: float = 13.0827, longitude: float = 80.2707) -> WeatherForecastResult:
    print("\n" + "=" * 70)
    print("CHETNA FLOOD WARNING SYSTEM — WEATHER INGESTION (LIVE API DEMO)")
    print("=" * 70)
    print(f"Querying Open-Meteo for coordinates: lat={latitude}, lon={longitude}...")

    result = fetch_weather_forecast(
        latitude=latitude,
        longitude=longitude,
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

    print("\n[3] SQLite 'forecasts' Table Record:")
    print(f"  Payload: {json.dumps(result.to_db_record(), indent=4)}")

    print("\n" + "=" * 70)
    print("Live API ingestion completed successfully!")
    print("=" * 70)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chetna weather ingestion example runner.")
    parser.add_argument("--live", action="store_true", help="Fetch live data from Open-Meteo API.")
    parser.add_argument("--lat", type=float, default=13.0827, help="Latitude (default: 13.0827 Chennai)")
    parser.add_argument("--lon", type=float, default=80.2707, help="Longitude (default: 80.2707 Chennai)")
    args = parser.parse_args()

    default_mock_path = PROJECT_ROOT / "tests" / "fixtures" / "sample_openmeteo_response.json"

    # Always demonstrate mock/offline execution first
    run_mock_example(default_mock_path)

    # If --live requested, run live query
    if args.live:
        run_live_example(latitude=args.lat, longitude=args.lon)
