import sqlite3
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = 'simulation.db'):
        self.db_path = db_path
        
    def init_db(self, schema_path: str):
        """Initialize the database with the provided schema file."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                with open(schema_path, 'r') as f:
                    schema = f.read()
                conn.executescript(schema)
                logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def insert_reading(self, sensor_id: str, timestamp: datetime, water_level: float, 
                      rainfall_rate: float, status: str = 'OK'):
        """Persist a single sensor reading."""
        query = '''
            INSERT INTO sensor_readings (sensor_id, timestamp, water_level, rainfall_rate, source, status)
            VALUES (?, ?, ?, ?, ?, ?)
        '''
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(query, (
                    sensor_id, 
                    timestamp.isoformat(), 
                    water_level, 
                    rainfall_rate, 
                    'simulated', 
                    status
                ))
        except Exception as e:
            logger.error(f"Error inserting reading for {sensor_id}: {e}")

    def insert_forecasts(self, sensor_id: str, generated_at: datetime, forecasts: List[Dict]):
        """Persist a batch of 6-hour forecasts for a sensor."""
        query = '''
            INSERT INTO sensor_forecasts (sensor_id, forecast_timestamp, generated_at, predicted_rainfall, predicted_water_level)
            VALUES (?, ?, ?, ?, ?)
        '''
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for forecast in forecasts:
                    cursor.execute(query, (
                        sensor_id,
                        forecast['forecast_timestamp'].isoformat(),
                        generated_at.isoformat(),
                        forecast['predicted_rainfall'],
                        forecast.get('predicted_water_level')
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error inserting forecasts for {sensor_id}: {e}")
