"""Forecast and geospatial data ingestion package for Chetna."""

from src.ingestion.weather import (
    DataParsingError,
    HourlyForecastRecord,
    OpenMeteoAPIError,
    OpenMeteoClient,
    OpenMeteoConnectionError,
    RainfallSummary,
    WeatherForecastResult,
    WeatherIngestionError,
    fetch_weather_forecast,
    load_mock_forecast,
    parse_weather_response,
)

__all__ = [
    "OpenMeteoClient",
    "HourlyForecastRecord",
    "RainfallSummary",
    "WeatherForecastResult",
    "WeatherIngestionError",
    "OpenMeteoAPIError",
    "OpenMeteoConnectionError",
    "DataParsingError",
    "fetch_weather_forecast",
    "parse_weather_response",
    "load_mock_forecast",
]
