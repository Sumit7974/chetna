-- ==============================================================================
-- Chetna AI Flood Early-Warning System: Database Schema
-- Target Engine: SQLite 3.x
-- ==============================================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------------------
-- Table: forecasts (Open-Meteo & Weather Ingestion)
-- Preserves backward-compatibility with Day 2 pipeline contract
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    rain_1h REAL NOT NULL,
    rain_3h REAL NOT NULL,
    rain_6h REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_forecasts_timestamp ON forecasts (timestamp);

-- ------------------------------------------------------------------------------
-- Table: sensor_nodes (Telemetry metadata for river gauges, street monitors)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_nodes (
    node_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    sensor_type TEXT NOT NULL,           -- 'water_level', 'rain_gauge', 'combined'
    warning_threshold_cm REAL DEFAULT 75.0,
    critical_threshold_cm REAL DEFAULT 120.0,
    status TEXT DEFAULT 'ACTIVE',        -- 'ACTIVE', 'MAINTENANCE', 'OFFLINE'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sensor_nodes_status ON sensor_nodes (status);

-- ------------------------------------------------------------------------------
-- Table: sensor_readings (Time-series observations)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    water_level_cm REAL,
    rainfall_rate_mm_h REAL,
    battery_pct REAL,
    is_anomaly INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (node_id) REFERENCES sensor_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_readings_node_timestamp ON sensor_readings (node_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON sensor_readings (timestamp);

-- ------------------------------------------------------------------------------
-- Table: alert_subscribers (Residents, municipal emergency officers)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone_number TEXT,
    telegram_chat_id TEXT,
    alert_tier TEXT DEFAULT 'CRITICAL',  -- 'INFO', 'WARNING', 'CRITICAL', 'ALL'
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_subscribers_active ON alert_subscribers (is_active);

-- ------------------------------------------------------------------------------
-- Table: cells (M1 Static Flood Vulnerability Scores)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cells (
    id TEXT PRIMARY KEY,
    geometry TEXT,
    elevation REAL,
    slope REAL,
    flow_acc REAL,
    vulnerability REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cells_vulnerability ON cells (vulnerability);

-- ------------------------------------------------------------------------------
-- Table: risk_predictions (Spatial dynamic flood risk predictions across horizons)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    horizon INTEGER NOT NULL,
    level TEXT NOT NULL,
    probability REAL NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_risk_cell_time_horizon ON risk_predictions (cell_id, timestamp, horizon);

-- ------------------------------------------------------------------------------
-- Table: alerts (Lifecycle tracking: generated -> dispatched -> acknowledged -> resolved)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT UNIQUE NOT NULL,
    node_id TEXT,
    severity TEXT NOT NULL,              -- 'INFO', 'WARNING', 'CRITICAL', 'EMERGENCY'
    lifecycle_status TEXT NOT NULL DEFAULT 'generated', -- 'generated', 'dispatched', 'acknowledged', 'resolved', 'suppressed'
    title TEXT,
    message TEXT NOT NULL,
    affected_area TEXT,
    reason TEXT,
    suppressed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_lifecycle ON alerts (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_alerts_node_id ON alerts (node_id);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts (severity);

-- ------------------------------------------------------------------------------
-- Table: alert_logs (Audit trail for dispatched notifications and attempts)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    zone_id TEXT,                        -- affected area or zone ID
    severity TEXT NOT NULL DEFAULT 'INFO', -- 'INFO', 'WARNING', 'CRITICAL', 'EMERGENCY'
    channel TEXT NOT NULL DEFAULT 'SYSTEM', -- 'TWILIO_SMS', 'TWILIO_VOICE', 'TELEGRAM', 'SYSTEM'
    provider TEXT,                       -- external provider or service name
    recipient TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    raw_message TEXT,                    -- original unformatted payload
    status TEXT NOT NULL,                -- 'SENT', 'FAILED', 'DRY_RUN', 'FALLBACK_SENT', 'SUPPRESSED'
    response_payload TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alert_logs_alert_id ON alert_logs (alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_logs_zone_id ON alert_logs (zone_id);
CREATE INDEX IF NOT EXISTS idx_alert_logs_timestamp ON alert_logs (timestamp);

-- ------------------------------------------------------------------------------
-- Table: sensor_table (Compatibility table for legacy telemetry queries)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    level_cm REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    source TEXT NOT NULL DEFAULT 'simulated'
);

CREATE INDEX IF NOT EXISTS idx_sensor_table_sensor_time ON sensor_table (sensor_id, timestamp);
