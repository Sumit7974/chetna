"""Open-Meteo Historical Archive rainfall downloader utility for Chetna M1.

Queries Open-Meteo ERA5 / Copernicus historical weather reanalysis API
to collect past rainfall series for model training and backtesting.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Union

from src.static_risk.hotspots import HistoricalRainfallRecord, HistoricalRainfallSeries

logger = logging.getLogger(__name__)

OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_archive_rainfall(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    event_id: str = "CUSTOM_HISTORICAL_EVENT",
    event_name: str = "Historical Rain Event",
    city: str = "Chennai",
    timezone_str: str = "Asia/Kolkata",
    timeout: float = 15.0,
    save_path: Optional[Union[str, Path]] = None,
) -> HistoricalRainfallSeries:
    """Fetches historical hourly rainfall data from the Open-Meteo Archive API.
    
    Args:
        latitude: Target location latitude.
        longitude: Target location longitude.
        start_date: Start date string 'YYYY-MM-DD'.
        end_date: End date string 'YYYY-MM-DD'.
        event_id: Unique identifier for this historical series.
        event_name: Human readable event name.
        city: City name.
        timezone_str: Timezone (default: 'Asia/Kolkata').
        timeout: HTTP timeout in seconds.
        save_path: Optional file path to save formatted JSON.
        
    Returns:
        Structured HistoricalRainfallSeries instance.
    """
    params = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "precipitation,rain",
        "timezone": timezone_str,
    }
    url = f"{OPENMETEO_ARCHIVE_URL}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Chetna-Flood-System/0.1", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Open-Meteo Archive HTTP error {e.code}: {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectionError(f"Failed to connect to Open-Meteo Archive: {e}") from e

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])
    rain = hourly.get("rain", precip)

    if not times:
        raise ValueError("No hourly timestamps returned from Open-Meteo Archive")

    records = [
        HistoricalRainfallRecord(
            timestamp=t,
            precipitation_mm=round(float(p or 0.0), 2),
            rain_mm=round(float(r or 0.0), 2),
        )
        for t, p, r in zip(times, precip, rain)
    ]

    clean_precip = [r.precipitation_mm for r in records]
    total_precip = round(sum(clean_precip), 2)
    peak_precip = max(clean_precip) if clean_precip else 0.0

    series = HistoricalRainfallSeries(
        event_id=event_id,
        name=event_name,
        city=city,
        latitude=float(data.get("latitude", latitude)),
        longitude=float(data.get("longitude", longitude)),
        timezone=str(data.get("timezone", timezone_str)),
        start_time=times[0],
        end_time=times[-1],
        total_hours=len(times),
        total_precipitation_mm=total_precip,
        peak_hourly_precipitation_mm=peak_precip,
        source="Open-Meteo Historical Weather Archive (ERA5 / Copernicus)",
        records=records,
    )

    if save_path:
        out_file = Path(save_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "event_id": series.event_id,
            "name": series.name,
            "city": series.city,
            "latitude": series.latitude,
            "longitude": series.longitude,
            "timezone": series.timezone,
            "start_time": series.start_time,
            "end_time": series.end_time,
            "total_hours": series.total_hours,
            "total_precipitation_mm": series.total_precipitation_mm,
            "peak_hourly_precipitation_mm": series.peak_hourly_precipitation_mm,
            "source": series.source,
            "hourly_series": [
                {"timestamp": r.timestamp, "precipitation_mm": r.precipitation_mm, "rain_mm": r.rain_mm}
                for r in series.records
            ],
        }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Saved archive rainfall series to %s", out_file)

    return series
