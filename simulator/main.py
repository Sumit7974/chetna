import time
import logging
import random
from datetime import datetime, timedelta
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulator.db import DatabaseManager
from simulator.hydrology import VirtualSensor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Environmental Hydrology Simulator Engine")
    
    # Initialize DB
    db_path = 'simulation.db'
    schema_path = '../database/schema.sql'
    
    # Ensure correct relative path if running from simulator folder
    if not os.path.exists(schema_path):
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'database', 'schema.sql')
        
    db = DatabaseManager(db_path)
    db.init_db(schema_path)
    
    # 1. Instantiate 8-10 virtual sensors
    sensors = []
    for i in range(1, 11):
        sensor_id = f"SENSOR_{i:02d}"
        # Vary characteristics slightly for each location
        drainage = random.uniform(0.02, 0.1)
        catchment = random.uniform(0.8, 2.0)
        sensors.append(VirtualSensor(sensor_id, base_drainage_coeff=drainage, catchment_multiplier=catchment))
        
    logger.info(f"Initialized {len(sensors)} virtual sensors.")
    
    # Simulation parameters
    # We will simulate time steps. Realistically a step could be 1 hour or 15 mins.
    # Here we run a fast-forward simulation: 1 real second = 1 simulation hour
    time_step_hours = 1.0 
    current_sim_time = datetime.now()
    
    # Weather System State
    regional_rainfall = 0.0
    
    try:
        # Run 24 cycles for demonstration
        for cycle in range(24):
            # Global weather change (storms come and go)
            if random.random() < 0.2: # 20% chance of weather shifting drastically
                regional_rainfall = random.uniform(0.0, 30.0)
            else:
                regional_rainfall = max(0.0, regional_rainfall + random.uniform(-5.0, 5.0))
            
            logger.info(f"--- Simulation Cycle {cycle+1} | Sim Time: {current_sim_time.strftime('%Y-%m-%d %H:%M')} | Regional Rain: {regional_rainfall:.2f} mm/hr ---")
            
            for sensor in sensors:
                # Localize the rainfall (some sensors get more, some less)
                local_rainfall = max(0.0, regional_rainfall + random.uniform(-2.0, 2.0))
                sensor.apply_weather(local_rainfall)
                
                # Advance hydrology physics
                sensor.step(time_step_hours)
                
                # Determine status based on thresholds
                status = "OK"
                if sensor.water_level > 100:
                    status = "WARNING"
                if sensor.water_level > 250:
                    status = "CRITICAL"
                    
                # 3. Database Persistence (Real-time readings)
                db.insert_reading(
                    sensor_id=sensor.sensor_id,
                    timestamp=current_sim_time,
                    water_level=round(sensor.water_level, 2),
                    rainfall_rate=round(sensor.current_rainfall, 2),
                    status=status
                )
                
                # 4. 6-Hour Forecast Integration (generate and persist)
                # In real life, might not generate every tick, but let's do it every 6 ticks (hours) or just demonstrate it
                if cycle % 6 == 0:
                    forecasts = sensor.generate_6hr_forecast(current_sim_time)
                    db.insert_forecasts(sensor.sensor_id, current_sim_time, forecasts)
                    logger.debug(f"Generated forecasts for {sensor.sensor_id}")
            
            logger.info(f"Updated {len(sensors)} sensors. Latest reading for SENSOR_01: {sensors[0].water_level:.2f} mm")
            
            # Advance time
            current_sim_time += timedelta(hours=time_step_hours)
            time.sleep(1) # sleep 1 second real-time to simulate loop
            
    except KeyboardInterrupt:
        logger.info("Simulation stopped by user.")
    except Exception as e:
        logger.error(f"Simulation error: {e}")

if __name__ == "__main__":
    main()
