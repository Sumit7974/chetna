"""API endpoint for B2 Day 4 Safe Routing."""

from typing import Dict, Any, List
from src.routing.router import OSMRouter

# Singleton router instance to cache graph
_router = OSMRouter()

def get_safe_route(
    start_lat: float, 
    start_lon: float, 
    dest_lat: float, 
    dest_lon: float, 
    hazard_zones: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Retrieve a safe route avoiding hazards using A*.
    """
    if start_lat is None or start_lon is None or dest_lat is None or dest_lon is None:
        return {"status": "error", "message": "Start and destination coordinates are required."}
        
    if not (-90.0 <= start_lat <= 90.0) or not (-90.0 <= dest_lat <= 90.0):
        return {"status": "error", "message": "Invalid latitude."}
        
    if not (-180.0 <= start_lon <= 180.0) or not (-180.0 <= dest_lon <= 180.0):
        return {"status": "error", "message": "Invalid longitude."}

    result = _router.find_safe_route((start_lat, start_lon), (dest_lat, dest_lon), hazard_zones)
    return result
