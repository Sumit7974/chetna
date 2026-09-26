-- Database Schema for Environmental Monitoring System

-- Table to store real-time sensor readings
CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id VARCHAR(50) NOT NULL,
    timestamp DATETIME NOT NULL,
    water_level REAL NOT NULL, -- in millimeters
    rainfall_rate REAL NOT NULL, -- in millimeters per hour
    source VARCHAR(20) NOT NULL DEFAULT 'simulated',
    status VARCHAR(20) NOT NULL
);

-- Index for querying readings by sensor and time
CREATE INDEX IF NOT EXISTS idx_sensor_readings_sensor_time ON sensor_readings(sensor_id, timestamp);

-- Table to store 6-hour forecasts
CREATE TABLE IF NOT EXISTS sensor_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id VARCHAR(50) NOT NULL,
    forecast_timestamp DATETIME NOT NULL, -- the time this forecast is valid for
    generated_at DATETIME NOT NULL,       -- the time this forecast was generated
    predicted_rainfall REAL NOT NULL,     -- predicted rainfall in mm
    predicted_water_level REAL            -- optional predicted water level based on rainfall
);

-- Index for querying forecasts
CREATE INDEX IF NOT EXISTS idx_sensor_forecasts_sensor_time ON sensor_forecasts(sensor_id, forecast_timestamp);
