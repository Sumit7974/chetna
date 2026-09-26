"""Safe-route planning interface and implementation for B2 Day 4 integration."""

import math
import logging
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any, Optional

try:
    import networkx as nx
    import osmnx as ox
    HAS_OSMNX = True
except ImportError:
    HAS_OSMNX = False

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on Earth in meters."""
    R = 6371000  # radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

class RouteService(ABC):
    """Abstract interface for safe routing requests."""
    
    @abstractmethod
    def find_safe_route(
        self,
        start_coord: Tuple[float, float],
        end_coord: Tuple[float, float],
        hazard_zones: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate a safe route avoiding specified hazards.
        """
        pass

class BasicRouter(RouteService):
    """Basic fallback router (no complex A* implementation yet)."""

    def find_safe_route(
        self,
        start_coord: Tuple[float, float],
        end_coord: Tuple[float, float],
        avoid_polygons: List[List[Tuple[float, float]]] = None
    ) -> List[Tuple[float, float]]:
        # Placeholder: Return direct line between start and end
        return [start_coord, end_coord]

class OSMRouter(RouteService):
    """Routing service using A* on an OpenStreetMap graph."""

    def __init__(self, cache_dir: str = "data/routing_cache"):
        self.cache_dir = cache_dir
        self.G = None
        # Configure osmnx cache
        if HAS_OSMNX:
            ox.settings.use_cache = True
            ox.settings.cache_folder = self.cache_dir

    def _get_graph(self, center_lat: float, center_lon: float, radius_m: int = 3000):
        """Lazy load or download the graph around the center point."""
        if not HAS_OSMNX:
            # Fallback to a mock graph for tests when osmnx is not available
            return self._create_mock_graph()
            
        if self.G is None:
            logging.info(f"Downloading/Loading OSM road graph for ({center_lat}, {center_lon})")
            try:
                self.G = ox.graph_from_point((center_lat, center_lon), dist=radius_m, network_type='walk')
            except Exception as e:
                logging.error(f"Failed to fetch OSM graph: {e}")
                return None
        return self.G

    def _create_mock_graph(self):
        """Create a tiny deterministic mock graph for testing."""
        import networkx as nx
        G = nx.MultiDiGraph()
        
        # Node 1: Start (13.0, 80.0)
        # Node 2: Intermediate Safe (13.01, 80.0)
        # Node 3: Intermediate Hazard (13.0, 80.01)
        # Node 4: Destination (13.01, 80.01)
        
        G.add_node(1, y=13.0, x=80.0)
        G.add_node(2, y=13.01, x=80.0)
        G.add_node(3, y=13.0, x=80.01)
        G.add_node(4, y=13.01, x=80.01)
        
        G.add_edge(1, 2, length=haversine(13.0, 80.0, 13.01, 80.0))
        G.add_edge(1, 3, length=haversine(13.0, 80.0, 13.0, 80.01))
        G.add_edge(2, 4, length=haversine(13.01, 80.0, 13.01, 80.01))
        G.add_edge(3, 4, length=haversine(13.0, 80.01, 13.01, 80.01))
        
        return G

    def _calculate_hazard_penalty(self, lat: float, lon: float, hazard_zones: List[Dict[str, Any]]) -> float:
        """Calculate penalty if a node falls within or near a hazard zone."""
        penalty = 0.0
        if not hazard_zones:
            return penalty
            
        for zone in hazard_zones:
            z_lat = zone.get("lat")
            z_lon = zone.get("lon")
            radius = zone.get("radius_m", 500)
            risk = zone.get("risk_level", "LOW")
            
            if z_lat is None or z_lon is None:
                continue
                
            dist = haversine(lat, lon, z_lat, z_lon)
            if dist <= radius:
                if risk == "HIGH":
                    penalty += 100000.0  # Massive penalty for flooded/high risk (virtually blocked)
                elif risk == "MEDIUM":
                    penalty += 500.0     # Moderate penalty, try to avoid
        return penalty

    def find_safe_route(
        self,
        start_coord: Tuple[float, float],
        end_coord: Tuple[float, float],
        hazard_zones: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Implementation of A* routing on the OSM graph with hazard avoidance.
        """
        start_lat, start_lon = start_coord
        end_lat, end_lon = end_coord
        
        # Midpoint for graph download
        mid_lat = (start_lat + end_lat) / 2
        mid_lon = (start_lon + end_lon) / 2
        
        G = self._get_graph(mid_lat, mid_lon)
        if G is None:
            return {"status": "error", "message": "No road graph available."}

        try:
            if HAS_OSMNX:
                orig_node = ox.nearest_nodes(G, start_lon, start_lat)
                dest_node = ox.nearest_nodes(G, end_lon, end_lat)
            else:
                # Naive nearest node for mock graph
                def dist_to(n, lat, lon):
                    return haversine(lat, lon, G.nodes[n]['y'], G.nodes[n]['x'])
                orig_node = min(G.nodes, key=lambda n: dist_to(n, start_lat, start_lon))
                dest_node = min(G.nodes, key=lambda n: dist_to(n, end_lat, end_lon))
                
            # Define heuristic (h(n))
            def heuristic(u, v):
                u_lat, u_lon = G.nodes[u]['y'], G.nodes[u]['x']
                v_lat, v_lon = G.nodes[v]['y'], G.nodes[v]['x']
                return haversine(u_lat, u_lon, v_lat, v_lon)
                
            # Define weight function (g(n) edge cost)
            def weight_func(u, v, d):
                length = d.get('length', 10.0)
                v_lat, v_lon = G.nodes[v]['y'], G.nodes[v]['x']
                penalty = self._calculate_hazard_penalty(v_lat, v_lon, hazard_zones)
                return length + penalty

            # Run A* Pathfinding
            import networkx as nx
            path = nx.astar_path(G, orig_node, dest_node, heuristic=heuristic, weight=weight_func)
            
            # Reconstruct route and calculate total weight
            route_coords = []
            total_dist = 0.0
            total_penalty = 0.0
            
            for i in range(len(path)):
                node = path[i]
                lat, lon = G.nodes[node]['y'], G.nodes[node]['x']
                route_coords.append({"lat": lat, "lon": lon})
                
                # Check penalty
                node_penalty = self._calculate_hazard_penalty(lat, lon, hazard_zones)
                total_penalty += node_penalty
                
                if i > 0:
                    prev_node = path[i-1]
                    total_dist += haversine(G.nodes[prev_node]['y'], G.nodes[prev_node]['x'], lat, lon)
            
            # If path goes through a blocked node, return no safe route
            if total_penalty >= 100000.0:
                return {"status": "error", "message": "No safe route is currently available."}
            
            # Simple time estimation assuming 5 km/h walking speed
            time_min = (total_dist / 1000) / 5.0 * 60
            
            return {
                "status": "success",
                "route": route_coords,
                "distance_m": total_dist,
                "estimated_time_min": time_min,
                "message": "Safe route found."
            }
            
        except nx.NetworkXNoPath:
            return {"status": "error", "message": "No safe route is currently available."}
        except Exception as e:
            logging.error(f"Routing failed: {e}")
            return {"status": "error", "message": "Internal routing failure."}
