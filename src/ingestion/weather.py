"""Open-Meteo weather and rainfall forecast ingestion module for Chetna.

This module provides data ingestion from the Open-Meteo Weather Forecast API.
It extracts hourly rainfall/precipitation, calculates critical short-term horizons
(+1h, +3h, +6h forecast rain and past 24h rain) required by the Chetna risk pipeline,
supports JSON response caching for offline resilience, and returns strongly-typed
structured records ready for SQLite persistence and downstream ML features.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WeatherIngestionError(Exception):
    """Base exception for all weather ingestion errors."""
    pass


class OpenMeteoAPIError(WeatherIngestionError):
    """Raised when the Open-Meteo API returns an HTTP error status."""

    def __init__(self, status_code: int, message: str, response_body: str = "") -> None:
        super().__init__(f"Open-Meteo API error (HTTP {status_code}): {message}")
        self.status_code = status_code
        self.message = message
        self.response_body = response_body


class OpenMeteoConnectionError(WeatherIngestionError):
    """Raised when network failures, timeouts, or DNS resolution issues occur."""
    pass


class DataParsingError(WeatherIngestionError):
    """Raised when the weather API response is malformed or missing required keys."""
    pass


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class HourlyForecastRecord:
    """Granular hourly forecast entry."""
    timestamp: str  # ISO-8601 string, e.g., '2026-09-24T10:00'
    precipitation_mm: float  # mm of precipitation in this hour
    rain_mm: float  # mm of liquid rain in this hour

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RainfallSummary:
    """Aggregated rainfall windows for Chetna flood risk predictions.
    
    Attributes:
        timestamp: Reference timestamp (ISO-8601) for this assessment window.
        rain_1h: Cumulative rainfall forecast for the next 1 hour (mm).
        rain_3h: Cumulative rainfall forecast for the next 3 hours (mm).
        rain_6h: Cumulative rainfall forecast for the next 6 hours (mm).
        rain_past_24h: Cumulative rainfall recorded over the past 24 hours (mm).
    """
    timestamp: str
    rain_1h: float
    rain_3h: float
    rain_6h: float
    rain_past_24h: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_db_record(self) -> Dict[str, Any]:
        """Returns dictionary matching Chetna SQLite 'forecasts' table schema:
        Columns: timestamp, rain_1h, rain_3h, rain_6h
        """
        return {
            "timestamp": self.timestamp,
            "rain_1h": self.rain_1h,
            "rain_3h": self.rain_3h,
            "rain_6h": self.rain_6h,
        }


@dataclass
class WeatherForecastResult:
    """Complete structured forecast result returned by the ingestion module."""
    latitude: float
    longitude: float
    timezone: str
    elevation: float
    reference_time: str
    summary: RainfallSummary
    hourly_records: List[HourlyForecastRecord] = field(default_factory=list)
    raw_response: Optional[Dict[str, Any]] = None
    from_cache: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to serializable dictionary."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone": self.timezone,
            "elevation": self.elevation,
            "reference_time": self.reference_time,
            "summary": self.summary.to_dict(),
            "hourly_records": [record.to_dict() for record in self.hourly_records],
            "from_cache": self.from_cache,
        }

    def to_db_record(self) -> Dict[str, Any]:
        """Convenience helper returning SQLite forecasts table payload."""
        return self.summary.to_db_record()


# ---------------------------------------------------------------------------
# Ingestion Client
# ---------------------------------------------------------------------------

class OpenMeteoClient:
    """Client for fetching and parsing weather forecast data from Open-Meteo."""

    DEFAULT_BASE_URL: str = "https://api.open-meteo.com/v1/forecast"
    DEFAULT_TIMEOUT: float = 10.0
    DEFAULT_USER_AGENT: str = "Chetna-Flood-Warning-System/0.1"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        cache_dir: Optional[Union[str, Path]] = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.user_agent = user_agent

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_filepath(self, latitude: float, longitude: float) -> Optional[Path]:
        """Generates standard cache path for a coordinate pair."""
        if not self.cache_dir:
            return None
        safe_lat = f"{latitude:.4f}".replace(".", "_").replace("-", "neg_")
        safe_lon = f"{longitude:.4f}".replace(".", "_").replace("-", "neg_")
        return self.cache_dir / f"forecast_{safe_lat}_{safe_lon}_latest.json"

    def _save_cache(self, filepath: Path, data: Dict[str, Any]) -> None:
        """Saves response dictionary to JSON cache file."""
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.debug("Saved forecast cache to %s", filepath)
        except OSError as e:
            logger.warning("Failed to write forecast cache to %s: %s", filepath, e)

    def _load_cache(self, filepath: Path) -> Dict[str, Any]:
        """Loads forecast dictionary from JSON cache file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise WeatherIngestionError(f"Failed to read cache file {filepath}: {e}") from e

    def fetch_raw_forecast(
        self,
        latitude: float,
        longitude: float,
        past_days: int = 1,
        forecast_days: int = 2,
        timezone_str: str = "auto",
        cache_response: bool = True,
        use_cache_on_failure: bool = True,
    ) -> tuple[Dict[str, Any], bool]:
        """Fetches raw JSON response from Open-Meteo API.
        
        Args:
            latitude: Latitude of target location (-90 to 90).
            longitude: Longitude of target location (-180 to 180).
            past_days: Number of past days of hourly weather data (default: 1 for past 24h rain).
            forecast_days: Number of forecast days (default: 2).
            timezone_str: Timezone string (default: 'auto').
            cache_response: If True and cache_dir configured, write response to cache.
            use_cache_on_failure: If True and network request fails, fall back to cached response.
            
        Returns:
            Tuple of (raw_json_dict, is_from_cache_flag).
            
        Raises:
            OpenMeteoConnectionError: On network/DNS/timeout failures.
            OpenMeteoAPIError: On HTTP error status responses from Open-Meteo.
            DataParsingError: On malformed JSON responses.
        """
        params = {
            "latitude": str(latitude),
            "longitude": str(longitude),
            "hourly": "precipitation,rain",
            "past_days": str(past_days),
            "forecast_days": str(forecast_days),
            "timezone": timezone_str,
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        cache_file = self._get_cache_filepath(latitude, longitude)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )

        try:
            logger.debug("Requesting Open-Meteo URL: %s", url)
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                status_code = response.getcode()
                response_bytes = response.read()

                if status_code != 200:
                    raise OpenMeteoAPIError(
                        status_code=status_code,
                        message=f"HTTP {status_code}",
                        response_body=response_bytes.decode("utf-8", errors="replace"),
                    )

                try:
                    data = json.loads(response_bytes.decode("utf-8"))
                except json.JSONDecodeError as err:
                    raise DataParsingError(f"Failed to decode Open-Meteo JSON: {err}") from err

                # Cache fresh response if requested
                if cache_response and cache_file:
                    self._save_cache(cache_file, data)

                return data, False

        except urllib.error.HTTPError as http_err:
            body = ""
            try:
                body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            
            # Check for fallback
            if use_cache_on_failure and cache_file and cache_file.exists():
                logger.warning(
                    "HTTP %d from Open-Meteo; falling back to cache file %s",
                    http_err.code,
                    cache_file,
                )
                return self._load_cache(cache_file), True

            raise OpenMeteoAPIError(
                status_code=http_err.code,
                message=str(http_err.reason),
                response_body=body,
            ) from http_err

        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            if use_cache_on_failure and cache_file and cache_file.exists():
                logger.warning(
                    "Network error (%s); falling back to cache file %s",
                    net_err,
                    cache_file,
                )
                return self._load_cache(cache_file), True

            raise OpenMeteoConnectionError(
                f"Failed to connect to Open-Meteo at {self.base_url}: {net_err}"
            ) from net_err

    def parse_forecast(
        self,
        raw_data: Dict[str, Any],
        reference_time: Optional[Union[datetime, str]] = None,
        from_cache: bool = False,
    ) -> WeatherForecastResult:
        """Parses raw Open-Meteo JSON payload into structured WeatherForecastResult.
        
        Args:
            raw_data: Open-Meteo JSON dictionary.
            reference_time: Time of prediction (str 'YYYY-MM-DDTHH:MM' or datetime).
                            If None, selects the current hour from timestamps or defaults
                            to the transition point where past data ends.
            from_cache: Flag indicating if data was loaded from offline cache.
            
        Returns:
            Structured WeatherForecastResult with computed rain_1h, rain_3h, rain_6h,
            and rain_past_24h.
            
        Raises:
            DataParsingError: If expected schema fields are missing.
        """
        if not isinstance(raw_data, dict):
            raise DataParsingError(f"Expected dict from Open-Meteo, got {type(raw_data).__name__}")

        # Check required top-level keys
        for key in ("latitude", "longitude", "hourly"):
            if key not in raw_data:
                raise DataParsingError(f"Missing required key '{key}' in Open-Meteo response")

        hourly = raw_data.get("hourly")
        if not isinstance(hourly, dict):
            raise DataParsingError(f"Expected 'hourly' to be a dict, got {type(hourly).__name__}")

        times: List[str] = hourly.get("time", [])
        if not times:
            raise DataParsingError("No hourly timestamps found in response")

        # Open-Meteo provides both 'precipitation' and 'rain'
        precip_list: List[Optional[float]] = hourly.get("precipitation") or hourly.get("rain") or []
        rain_list: List[Optional[float]] = hourly.get("rain") or precip_list

        if len(times) != len(precip_list):
            raise DataParsingError(
                f"Mismatch between time count ({len(times)}) and precipitation count ({len(precip_list)})"
            )

        # Build clean records
        hourly_records: List[HourlyForecastRecord] = []
        clean_rain_values: List[float] = []

        for t, p, r in zip(times, precip_list, rain_list):
            p_val = max(0.0, float(p)) if p is not None else 0.0
            r_val = max(0.0, float(r)) if r is not None else p_val
            clean_rain_values.append(r_val)
            hourly_records.append(
                HourlyForecastRecord(
                    timestamp=t,
                    precipitation_mm=round(p_val, 2),
                    rain_mm=round(r_val, 2),
                )
            )

        # Determine reference time index
        ref_idx = self._find_reference_index(times, reference_time)
        selected_ref_time = times[ref_idx]

        # Calculate horizons from ref_idx
        # rain_1h: cumulative rainfall over next 1 hour [ref_idx : ref_idx + 1]
        # rain_3h: cumulative rainfall over next 3 hours [ref_idx : ref_idx + 3]
        # rain_6h: cumulative rainfall over next 6 hours [ref_idx : ref_idx + 6]
        # rain_past_24h: cumulative rainfall over preceding 24 hours [ref_idx - 24 : ref_idx]
        total_len = len(clean_rain_values)
        
        rain_1h = round(sum(clean_rain_values[ref_idx : min(total_len, ref_idx + 1)]), 2)
        rain_3h = round(sum(clean_rain_values[ref_idx : min(total_len, ref_idx + 3)]), 2)
        rain_6h = round(sum(clean_rain_values[ref_idx : min(total_len, ref_idx + 6)]), 2)

        past_start = max(0, ref_idx - 24)
        rain_past_24h = round(sum(clean_rain_values[past_start:ref_idx]), 2)

        summary = RainfallSummary(
            timestamp=selected_ref_time,
            rain_1h=rain_1h,
            rain_3h=rain_3h,
            rain_6h=rain_6h,
            rain_past_24h=rain_past_24h,
        )

        return WeatherForecastResult(
            latitude=float(raw_data.get("latitude", 0.0)),
            longitude=float(raw_data.get("longitude", 0.0)),
            timezone=str(raw_data.get("timezone", "UTC")),
            elevation=float(raw_data.get("elevation", 0.0)),
            reference_time=selected_ref_time,
            summary=summary,
            hourly_records=hourly_records,
            raw_response=raw_data,
            from_cache=from_cache,
        )

    def _find_reference_index(
        self,
        times: List[str],
        reference_time: Optional[Union[datetime, str]],
    ) -> int:
        """Finds closest array index matching the reference time."""
        if reference_time is not None:
            if isinstance(reference_time, datetime):
                # Format to 'YYYY-MM-DDTHH:00'
                ref_str = reference_time.strftime("%Y-%m-%dT%H:00")
            else:
                ref_str = str(reference_time)
                # Normalize minutes if present
                if len(ref_str) > 13 and ref_str[13] == ":":
                    ref_str = ref_str[:13] + ":00"

            # Check exact match
            if ref_str in times:
                return times.index(ref_str)

            # Find first timestamp greater than or equal to ref_str
            for i, t in enumerate(times):
                if t >= ref_str:
                    return i
            
            # If all are earlier, return last index
            return len(times) - 1

        # When no reference time specified:
        # Check if current local/UTC hour matches any timestamp in times
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        for i, t in enumerate(times):
            if t == now_utc:
                return i

        # If data has past_days=1 (typically 24 hours past), index 24 is current hour
        if len(times) >= 48:
            return 24
        
        # Default to index 0
        return 0

    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        reference_time: Optional[Union[datetime, str]] = None,
        past_days: int = 1,
        forecast_days: int = 2,
        timezone_str: str = "auto",
        cache_response: bool = True,
        use_cache_on_failure: bool = True,
    ) -> WeatherForecastResult:
        """High-level method: fetches from Open-Meteo and returns structured forecast result."""
        raw_data, is_cache = self.fetch_raw_forecast(
            latitude=latitude,
            longitude=longitude,
            past_days=past_days,
            forecast_days=forecast_days,
            timezone_str=timezone_str,
            cache_response=cache_response,
            use_cache_on_failure=use_cache_on_failure,
        )
        return self.parse_forecast(
            raw_data=raw_data,
            reference_time=reference_time,
            from_cache=is_cache,
        )


# ---------------------------------------------------------------------------
# Convenience Functional API
# ---------------------------------------------------------------------------

def fetch_weather_forecast(
    latitude: float,
    longitude: float,
    reference_time: Optional[Union[datetime, str]] = None,
    past_days: int = 1,
    forecast_days: int = 2,
    timezone_str: str = "auto",
    cache_dir: Optional[Union[str, Path]] = "data/cache",
    timeout: float = 10.0,
    use_cache_on_failure: bool = True,
) -> WeatherForecastResult:
    """Convenience function to fetch and parse weather forecast from Open-Meteo.
    
    Args:
        latitude: Latitude of location.
        longitude: Longitude of location.
        reference_time: Optional reference time for forecast horizons.
        past_days: Days of historical hourly data to include (default: 1).
        forecast_days: Days of forecast hourly data (default: 2).
        timezone_str: Timezone (default: 'auto').
        cache_dir: Directory for storing JSON cache files.
        timeout: HTTP timeout in seconds.
        use_cache_on_failure: Whether to fallback to cache when API fails.
        
    Returns:
        Structured WeatherForecastResult.
    """
    client = OpenMeteoClient(cache_dir=cache_dir, timeout=timeout)
    return client.get_forecast(
        latitude=latitude,
        longitude=longitude,
        reference_time=reference_time,
        past_days=past_days,
        forecast_days=forecast_days,
        timezone_str=timezone_str,
        use_cache_on_failure=use_cache_on_failure,
    )


def parse_weather_response(
    raw_data: Dict[str, Any],
    reference_time: Optional[Union[datetime, str]] = None,
) -> WeatherForecastResult:
    """Parses an in-memory dictionary or mock response without making network calls."""
    client = OpenMeteoClient()
    return client.parse_forecast(raw_data=raw_data, reference_time=reference_time)


def load_mock_forecast(
    mock_filepath: Union[str, Path],
    reference_time: Optional[Union[datetime, str]] = None,
) -> WeatherForecastResult:
    """Loads a mock JSON file and returns structured WeatherForecastResult."""
    path = Path(mock_filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Mock file not found: {mock_filepath}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_weather_response(data, reference_time=reference_time)
