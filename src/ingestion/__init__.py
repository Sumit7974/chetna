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
    fetch_and_store_forecast,
    fetch_weather_forecast,
    load_mock_forecast,
    parse_weather_response,
    store_forecast_result,
    store_mock_forecast,
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
    "fetch_and_store_forecast",
    "store_forecast_result",
    "store_mock_forecast",
    "parse_weather_response",
    "load_mock_forecast",
]
