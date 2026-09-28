import json
import sqlite3
from pathlib import Path
import geopandas as gpd
from src.db.spatial import save_roads, save_facilities, save_grid_cells, init_spatial_db
from src.ingestion.osm import load_osm_layer

DB_PATH = Path("data/chetna.db")

def sync():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 1. Initialize schema
    with open("database/schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    init_spatial_db(conn)

    # 2. Hotspots
    with open("data/m1/hotspots.json", "r", encoding="utf-8") as f:
        hotspots_data = json.load(f)
    conn.execute("DELETE FROM hotspots")
    for h in hotspots_data:
        conn.execute("""
            INSERT INTO hotspots (
                hotspot_id, name, city, state, zone, ward, latitude, longitude,
                elevation_m, hotspot_type, severity_tier, typical_trigger_rain_1h_mm,
                typical_trigger_rain_6h_mm, historical_inundation_depth_m,
                primary_vulnerability_cause, source_reference, cell_id, is_real_sourced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h["hotspot_id"], h["name"], h["city"], h.get("state", "Bihar"),
            h["zone"], h["ward"], h["latitude"], h["longitude"],
            h["elevation_m"], h["hotspot_type"], h["severity_tier"],
            h["typical_trigger_rain_1h_mm"], h["typical_trigger_rain_6h_mm"],
            h["historical_inundation_depth_m"], h["primary_vulnerability_cause"],
            h["source_reference"], h["cell_id"], 1
        ))
    print(f"Synced {len(hotspots_data)} Patna hotspots to database.")

    # 3. Clean cells table: keep ONLY Patna cells (CELL_PAT_*)
    conn.execute("DELETE FROM cells WHERE id NOT LIKE 'CELL_PAT_%'")
    with open("data/m1/static_risk_scores.json", "r", encoding="utf-8") as f:
        cells_data = json.load(f)["cells"]
    for c in cells_data:
        conn.execute("""
            INSERT OR REPLACE INTO cells (id, geometry, elevation, slope, flow_acc, vulnerability)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            c["cell_id"], json.dumps(c.get("geometry")),
            c.get("elevation_m"), c.get("slope_deg"), c.get("flow_acc_m2"),
            c.get("vulnerability_score", c.get("vulnerability"))
        ))
    remaining_cells = conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
    print(f"Synced {remaining_cells} Patna cells in database.")

    # 4. Sensor Nodes (10 Patna simulated sensors)
    conn.execute("DELETE FROM sensor_nodes")
    patna_sensors = [
        {"node_id": "SENS_PAT_01", "name": "Rajendra Nagar Sump Station", "latitude": 25.5990, "longitude": 85.1640, "type": "water_level", "warning": 40.0, "critical": 65.0},
        {"node_id": "SENS_PAT_02", "name": "Kankarbagh Colony Drain Outfall", "latitude": 25.5960, "longitude": 85.1550, "type": "water_level", "warning": 35.0, "critical": 60.0},
        {"node_id": "SENS_PAT_03", "name": "Saidpur Nullah Inflow Gauge", "latitude": 25.6030, "longitude": 85.1710, "type": "water_level", "warning": 45.0, "critical": 70.0},
        {"node_id": "SENS_PAT_04", "name": "Boring Canal Underpass Sensor", "latitude": 25.6180, "longitude": 85.1220, "type": "water_level", "warning": 30.0, "critical": 50.0},
        {"node_id": "SENS_PAT_05", "name": "Bailey Road Sag Station", "latitude": 25.6120, "longitude": 85.0840, "type": "water_level", "warning": 30.0, "critical": 55.0},
        {"node_id": "SENS_PAT_06", "name": "Gandhi Maidan South Basin", "latitude": 25.6180, "longitude": 85.1430, "type": "combined", "warning": 40.0, "critical": 65.0},
        {"node_id": "SENS_PAT_07", "name": "Patliputra Industrial Drain Node", "latitude": 25.6250, "longitude": 85.1050, "type": "water_level", "warning": 35.0, "critical": 60.0},
        {"node_id": "SENS_PAT_08", "name": "Anisabad Golambar Sump Node", "latitude": 25.5800, "longitude": 85.1020, "type": "water_level", "warning": 35.0, "critical": 60.0},
        {"node_id": "SENS_PAT_09", "name": "Digha Outfall Sluice Gate Monitor", "latitude": 25.6420, "longitude": 85.0980, "type": "water_level", "warning": 50.0, "critical": 80.0},
        {"node_id": "SENS_PAT_10", "name": "Bazar Samiti Agricultural Market Sump", "latitude": 25.6050, "longitude": 85.1820, "type": "water_level", "warning": 40.0, "critical": 65.0},
    ]
    for s in patna_sensors:
        conn.execute("""
            INSERT INTO sensor_nodes (node_id, name, latitude, longitude, sensor_type, warning_threshold_cm, critical_threshold_cm, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """, (s["node_id"], s["name"], s["latitude"], s["longitude"], s["type"], s["warning"], s["critical"]))
    print(f"Synced {len(patna_sensors)} Patna sensor nodes to database.")

    # 5. Populate Roads, Hospitals, Schools, Shelters, Grid Cells
    conn.execute("DELETE FROM roads")
    conn.execute("DELETE FROM hospitals")
    conn.execute("DELETE FROM schools")
    conn.execute("DELETE FROM shelters")
    conn.execute("DELETE FROM grid_cells")
    conn.commit()
    conn.close()

    roads_gdf = load_osm_layer("roads", fallback_to_fixture=True)
    save_roads(roads_gdf, db_path=DB_PATH)

    hosps_gdf = load_osm_layer("hospitals", fallback_to_fixture=True)
    save_facilities(hosps_gdf, "hospitals", db_path=DB_PATH)

    schools_gdf = load_osm_layer("schools", fallback_to_fixture=True)
    save_facilities(schools_gdf, "schools", db_path=DB_PATH)

    shelters_gdf = load_osm_layer("shelters", fallback_to_fixture=True)
    save_facilities(shelters_gdf, "shelters", db_path=DB_PATH)

    with open("data/m1/synthetic_grid_features.json", "r", encoding="utf-8") as f:
        grid_features = json.load(f)["cells"]
    for idx, c in enumerate(grid_features):
        c["row"] = idx // 6
        c["col"] = idx % 6
        c["centroid_lat"] = c["latitude"]
        c["centroid_lon"] = c["longitude"]
        c["elevation_m"] = c["elevation"]
    save_grid_cells(grid_features, db_path=DB_PATH)
    print("Populated spatial DB with Patna roads, hospitals, schools, shelters, and grid cells.")

    # 6. Reset alerts and logs for clean nominal startup
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM alert_logs")
    conn.execute("DELETE FROM risk_predictions")
    conn.commit()
    conn.close()
    print("Cleared stale alerts, logs, and risk_predictions for clean nominal baseline startup.")

if __name__ == "__main__":
    sync()
