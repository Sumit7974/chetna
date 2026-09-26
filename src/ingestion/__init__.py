"""Forecast and geospatial data ingestion package for Chetna."""

from src.ingestion.dem import (
    attach_elevation_to_grid,
    create_synthetic_dem_fixture,
    download_dem_opentopography,
    load_dem_metadata,
)
from src.ingestion.grid import (
    generate_pilot_grid,
    load_grid_geojson,
    save_grid_geojson,
    validate_grid,
)
from src.ingestion.osm import (
    create_synthetic_osm_fixtures,
    download_osm_layer,
    ingest_all_osm_data,
    load_osm_layer,
)
from src.ingestion.pilot_config import (
    GEOGRAPHIC_CRS,
    GRID_RESOLUTION_M,
    PILOT_BBOX,
    PILOT_BBOX_TUPLE,
    PILOT_CENTER,
    PROJECTED_CRS,
)
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
    "GEOGRAPHIC_CRS",
    "PROJECTED_CRS",
    "PILOT_BBOX",
    "PILOT_BBOX_TUPLE",
    "PILOT_CENTER",
    "GRID_RESOLUTION_M",
    "generate_pilot_grid",
    "save_grid_geojson",
    "load_grid_geojson",
    "validate_grid",
    "download_dem_opentopography",
    "create_synthetic_dem_fixture",
    "load_dem_metadata",
    "attach_elevation_to_grid",
    "download_osm_layer",
    "create_synthetic_osm_fixtures",
    "load_osm_layer",
    "ingest_all_osm_data",
]
