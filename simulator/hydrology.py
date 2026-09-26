import math
import random

class VirtualSensor:
    def __init__(self, sensor_id: str, base_drainage_coeff: float = 0.05, catchment_multiplier: float = 1.2):
        """
        Initialize a virtual sensor.
        :param sensor_id: Identifier (e.g., SENSOR_01)
        :param base_drainage_coeff: Rate at which water drains away (mm per timestep)
        :param catchment_multiplier: Amplifies rainfall impact to simulate terrain funneling
        """
        self.sensor_id = sensor_id
        self.water_level = 0.0  # current water level in mm
        self.drainage_coeff = base_drainage_coeff
        self.catchment_multiplier = catchment_multiplier
        
        # Local weather state
        self.current_rainfall = 0.0
        
    def apply_weather(self, rainfall: float):
        """Update current local rainfall."""
        self.current_rainfall = rainfall
        
    def step(self, time_delta_hours: float):
        """
        Advance the simulation by a time step.
        Water level changes based on rainfall inflow and drainage outflow.
        """
        # Inflow: rainfall over the time period, amplified by terrain characteristics
        inflow = self.current_rainfall * self.catchment_multiplier * time_delta_hours
        
        # Outflow: drainage based on current water level (higher water = faster drainage up to a point)
        # We use a simple proportional drainage model
        outflow = self.drainage_coeff * self.water_level * time_delta_hours
        
        # Update level
        self.water_level = max(0.0, self.water_level + inflow - outflow)
        
        # Add a tiny bit of noise for realism
        noise = random.uniform(-0.5, 0.5)
        if self.water_level > 0:
            self.water_level = max(0.0, self.water_level + noise)
            
    def generate_6hr_forecast(self, current_time) -> list:
        """
        Generate a synthetic 6-hour forecast for this location.
        Returns a list of dicts with hourly predictions.
        """
        from datetime import timedelta
        forecasts = []
        
        # Simple markov-chain-like weather trend for simulation
        trend = self.current_rainfall
        
        for hour in range(1, 7):
            # Rainfall trend fluctuates
            trend = max(0.0, trend + random.uniform(-5.0, 5.0))
            forecast_time = current_time + timedelta(hours=hour)
            
            # Estimate future water level based on simple prediction
            est_inflow = trend * self.catchment_multiplier * 1.0
            est_outflow = self.drainage_coeff * self.water_level * 1.0
            est_level = max(0.0, self.water_level + est_inflow - est_outflow)
            
            forecasts.append({
                'forecast_timestamp': forecast_time,
                'predicted_rainfall': round(trend, 2),
                'predicted_water_level': round(est_level, 2)
            })
            
        return forecasts
