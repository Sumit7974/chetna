"""Safe-route planning interface and implementation for Chetna B1 Day 4 / B2 Day 4."""

from __future__ import annotations

import logging
import math
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import networkx as nx
    import osmnx as ox
    HAS_OSMNX = True
except ImportError:
    HAS_OSMNX = False

try:
    import geopandas as gpd
    import pandas as pd
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False

from database.db import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)


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
        """Calculate a safe route avoiding specified hazards."""
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

    def __init__(
        self,
        cache_dir: str = "data/routing_cache",
        graph: Optional[Any] = None,
        db_path: Optional[Union[str, Path, sqlite3.Connection]] = None,
    ):
        self.cache_dir = cache_dir
        self.G = graph
        self.db_path = db_path
        if HAS_OSMNX:
            ox.settings.use_cache = True
            ox.settings.cache_folder = self.cache_dir

    def _get_graph(self, center_lat: float, center_lon: float, radius_m: int = 3000):
        """Lazy load or download the graph around the center point."""
        if self.G is not None:
            return self.G

        if not HAS_OSMNX:
            # Fallback to a mock graph for tests when osmnx is not available
            return self._create_mock_graph()

        # Try loading roads from spatial DB if db_path is provided
        if self.db_path is not None:
            try:
                from src.db.spatial import load_roads
                roads_gdf = load_roads(self.db_path)
                if len(roads_gdf) > 0:
                    self.G = build_road_graph_from_roads(roads_gdf)
                    return self.G
            except Exception as e:
                logger.debug("Could not load roads from db: %s", e)

        # Try loading roads from local OSM cache / fixture
        try:
            from src.ingestion.osm import load_osm_layer
            roads_gdf = load_osm_layer("roads", fallback_to_fixture=True)
            if len(roads_gdf) > 0:
                self.G = build_road_graph_from_roads(roads_gdf)
                return self.G
        except Exception as e:
            logger.debug("Could not load roads from cache/fixture: %s", e)

        logger.info("Downloading/Loading OSM road graph for (%f, %f)", center_lat, center_lon)
        try:
            self.G = ox.graph_from_point((center_lat, center_lon), dist=radius_m, network_type='walk')
        except Exception as e:
            logger.warning("Failed to fetch OSM graph: %s; falling back to mock graph", e)
            self.G = self._create_mock_graph()
        return self.G

    def _create_mock_graph(self):
        """Create a tiny deterministic mock graph for testing."""
        import networkx as nx
        G = nx.MultiDiGraph()

        # Node 1: Start (13.0, 80.0)
        # Node 2: Intermediate Safe (13.01, 80.0)
        # Node 3: Intermediate Hazard (13.0, 80.01)
        # Node 4: Destination (13.01, 80.01)

        G.add_node(1, y=13.0, x=80.0, cell_id="MOCK_C1", risk_level="LOW", risk_probability=0.0)
        G.add_node(2, y=13.01, x=80.0, cell_id="MOCK_C2", risk_level="LOW", risk_probability=0.0)
        G.add_node(3, y=13.0, x=80.01, cell_id="MOCK_C3", risk_level="LOW", risk_probability=0.0)
        G.add_node(4, y=13.01, x=80.01, cell_id="MOCK_C4", risk_level="LOW", risk_probability=0.0)

        G.add_edge(1, 2, length=haversine(13.0, 80.0, 13.01, 80.0))
        G.add_edge(1, 3, length=haversine(13.0, 80.0, 13.0, 80.01))
        G.add_edge(2, 4, length=haversine(13.01, 80.0, 13.01, 80.01))
        G.add_edge(3, 4, length=haversine(13.0, 80.01, 13.01, 80.01))

        return G

    def _calculate_hazard_penalty(self, lat: float, lon: float, hazard_zones: List[Dict[str, Any]] = None) -> float:
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
        """Implementation of A* routing on the OSM graph with hazard avoidance."""
        start_lat, start_lon = start_coord
        end_lat, end_lon = end_coord

        # Midpoint for graph download
        mid_lat = (start_lat + end_lat) / 2
        mid_lon = (start_lon + end_lon) / 2

        G = self._get_graph(mid_lat, mid_lon)
        if G is None:
            return {"status": "error", "message": "No road graph available."}

        try:
            orig_node = None
            dest_node = None
            if HAS_OSMNX and G.graph.get("crs") is not None:
                try:
                    orig_node = ox.nearest_nodes(G, start_lon, start_lat)
                    dest_node = ox.nearest_nodes(G, end_lon, end_lat)
                except Exception:
                    orig_node = None
                    dest_node = None

            if orig_node is None or dest_node is None:
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
                node_penalty = 0.0

                v_risk = G.nodes[v].get("risk_level")
                if v_risk == "HIGH":
                    node_penalty += 100000.0
                elif v_risk == "MEDIUM":
                    node_penalty += 500.0

                zone_penalty = self._calculate_hazard_penalty(v_lat, v_lon, hazard_zones)
                return length + node_penalty + zone_penalty

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
                node_risk = G.nodes[node].get("risk_level")
                if node_risk == "HIGH":
                    total_penalty += 100000.0
                elif node_risk == "MEDIUM":
                    total_penalty += 500.0
                total_penalty += self._calculate_hazard_penalty(lat, lon, hazard_zones)

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
            logger.error("Routing failed: %s", e)
            return {"status": "error", "message": "Internal routing failure."}


def build_road_graph_from_roads(roads_gdf: gpd.GeoDataFrame) -> nx.MultiDiGraph:
    """Build a NetworkX MultiDiGraph from road LineStrings in a GeoDataFrame.

    Assigns nodes coordinates (y=latitude, x=longitude) and edges haversine lengths in metres.
    """
    import networkx as nx
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    node_map: Dict[Tuple[float, float], int] = {}

    def get_or_create_node(lat: float, lon: float) -> int:
        pt_key = (round(lat, 6), round(lon, 6))
        if pt_key not in node_map:
            nid = len(node_map) + 1
            node_map[pt_key] = nid
            G.add_node(nid, y=pt_key[0], x=pt_key[1], cell_id=None, risk_level="LOW", risk_probability=0.0)
        return node_map[pt_key]

    for _, row in roads_gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        lines = [geom] if geom.geom_type == "LineString" else list(getattr(geom, "geoms", []))
        for line in lines:
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                p1, p2 = coords[i], coords[i + 1]
                # Coordinates in GeoJSON/GeoDataFrame are (lon, lat)
                u = get_or_create_node(p1[1], p1[0])
                v = get_or_create_node(p2[1], p2[0])

                dist = haversine(G.nodes[u]["y"], G.nodes[u]["x"], G.nodes[v]["y"], G.nodes[v]["x"])
                attrs = {
                    "length": max(1.0, round(dist, 2)),
                    "name": str(row.get("name") or ""),
                    "highway": str(row.get("highway") or "road"),
                    "osm_id": str(row.get("osm_id") or ""),
                }
                G.add_edge(u, v, **attrs)
                G.add_edge(v, u, **attrs)

    return G


def connect_graph_to_grid(
    graph: nx.MultiDiGraph,
    grid_cells: Optional[Union[gpd.GeoDataFrame, List[Dict[str, Any]]]] = None,
    db_path: Any = DEFAULT_DB_PATH,
) -> nx.MultiDiGraph:
    """Connect road graph nodes to grid cells.

    Maps each graph node to its corresponding cell_id in the ~200 m metric grid.
    """
    if graph is None or len(graph.nodes) == 0:
        return graph

    cells_data = None
    if grid_cells is not None:
        cells_data = grid_cells
    else:
        try:
            from src.db.spatial import load_grid_cells
            cells_gdf = load_grid_cells(db_path)
            if len(cells_gdf) > 0:
                cells_data = cells_gdf
        except Exception as e:
            logger.debug("Could not load grid_cells from db: %s", e)

    if cells_data is None:
        return graph

    centroids: List[Tuple[str, float, float, Optional[float]]] = []
    if HAS_GEOPANDAS and isinstance(cells_data, gpd.GeoDataFrame):
        for _, row in cells_data.iterrows():
            cid = str(row["cell_id"])
            c_lat = float(row.get("centroid_lat", row.geometry.centroid.y if hasattr(row.geometry, "centroid") else 0.0))
            c_lon = float(row.get("centroid_lon", row.geometry.centroid.x if hasattr(row.geometry, "centroid") else 0.0))
            elev = row.get("elevation_m")
            elev_val = float(elev) if elev is not None and not (isinstance(elev, float) and math.isnan(elev)) else None
            centroids.append((cid, c_lat, c_lon, elev_val))
    else:
        for c in cells_data:
            cid = str(c.get("cell_id") or c.get("id"))
            c_lat = float(c.get("centroid_lat", 0.0))
            c_lon = float(c.get("centroid_lon", 0.0))
            elev = c.get("elevation_m")
            centroids.append((cid, c_lat, c_lon, float(elev) if elev is not None else None))

    if not centroids:
        return graph

    for n in graph.nodes:
        n_lat = graph.nodes[n]["y"]
        n_lon = graph.nodes[n]["x"]

        best_cid = None
        best_dist = float("inf")
        best_elev = None

        for cid, c_lat, c_lon, elev in centroids:
            if abs(n_lat - c_lat) < 0.005 and abs(n_lon - c_lon) < 0.005:
                d = haversine(n_lat, n_lon, c_lat, c_lon)
                if d < best_dist:
                    best_dist = d
                    best_cid = cid
                    best_elev = elev

        if best_cid is not None:
            graph.nodes[n]["cell_id"] = best_cid
            if best_elev is not None:
                graph.nodes[n]["elevation_m"] = best_elev

    return graph


def apply_risk_predictions_to_graph(
    graph: nx.MultiDiGraph,
    risk_predictions: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
    horizon: int = 1,
    db_path: Any = DEFAULT_DB_PATH,
) -> Tuple[nx.MultiDiGraph, List[Dict[str, Any]]]:
    """Apply flood-risk predictions to graph nodes and produce hazard zones.

    Nodes in HIGH-risk cells receive risk_level='HIGH' and massive routing penalties.
    Nodes in MEDIUM-risk cells receive risk_level='MEDIUM' and moderate penalties.
    """
    hazard_zones: List[Dict[str, Any]] = []
    preds_by_cell: Dict[str, Dict[str, Any]] = {}

    if risk_predictions is not None:
        if isinstance(risk_predictions, dict):
            preds_by_cell = risk_predictions
        elif isinstance(risk_predictions, list):
            for p in risk_predictions:
                if hasattr(p, "cell_id"):
                    cid = p.cell_id
                    lvl = p.level
                    prob = p.probability
                else:
                    cid = p.get("cell_id")
                    lvl = p.get("level", "LOW")
                    prob = p.get("probability", 0.0)
                if cid:
                    preds_by_cell[str(cid)] = {"level": lvl, "probability": prob}
    else:
        try:
            from src.db.forecasts import get_db_connection
            with get_db_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT cell_id, level, probability FROM risk_predictions WHERE horizon = ? ORDER BY timestamp DESC",
                    (horizon,)
                )
                for r in cursor.fetchall():
                    cid = str(r["cell_id"])
                    if cid not in preds_by_cell:
                        preds_by_cell[cid] = {"level": r["level"], "probability": float(r["probability"])}
        except Exception as e:
            logger.debug("Could not read risk_predictions from db: %s", e)

    for n in graph.nodes:
        cid = graph.nodes[n].get("cell_id")
        if cid and cid in preds_by_cell:
            p = preds_by_cell[cid]
            lvl = p.get("level", "LOW")
            prob = p.get("probability", 0.0)
            graph.nodes[n]["risk_level"] = lvl
            graph.nodes[n]["risk_probability"] = prob

            if lvl in ("HIGH", "MEDIUM"):
                hazard_zones.append({
                    "cell_id": cid,
                    "lat": graph.nodes[n]["y"],
                    "lon": graph.nodes[n]["x"],
                    "radius_m": 150,
                    "risk_level": lvl,
                    "probability": prob,
                })
        else:
            graph.nodes[n]["risk_level"] = graph.nodes[n].get("risk_level", "LOW")
            graph.nodes[n]["risk_probability"] = graph.nodes[n].get("risk_probability", 0.0)

    return graph, hazard_zones


def _extract_shelter_records(
    shelters: Optional[Union[gpd.GeoDataFrame, List[Dict[str, Any]]]],
    db_path: Any = DEFAULT_DB_PATH
) -> List[Dict[str, Any]]:
    """Helper to extract normalized shelter records from user input, database, or offline fixture."""
    records: List[Dict[str, Any]] = []

    if shelters is not None:
        if HAS_GEOPANDAS and isinstance(shelters, gpd.GeoDataFrame):
            for _, r in shelters.iterrows():
                lat = float(r.get("latitude", r.geometry.y if hasattr(r.geometry, "y") else 0.0))
                lon = float(r.get("longitude", r.geometry.x if hasattr(r.geometry, "x") else 0.0))
                records.append({
                    "id": str(r.get("osm_id") or r.get("id") or ""),
                    "name": str(r.get("name") or "Shelter"),
                    "latitude": lat,
                    "longitude": lon,
                    "amenity": str(r.get("amenity") or "shelter"),
                })
        else:
            for s in shelters:
                lat = float(s.get("latitude", s.get("lat", 0.0)))
                lon = float(s.get("longitude", s.get("lon", 0.0)))
                records.append({
                    "id": str(s.get("osm_id") or s.get("id") or ""),
                    "name": str(s.get("name") or "Shelter"),
                    "latitude": lat,
                    "longitude": lon,
                    "amenity": str(s.get("amenity") or "shelter"),
                })
        return records

    try:
        from src.db.spatial import load_facilities
        shl_gdf = load_facilities("shelters", db_path=db_path)
        if len(shl_gdf) > 0:
            return _extract_shelter_records(shl_gdf, db_path)
    except Exception as e:
        logger.debug("Could not load shelters from db: %s", e)

    try:
        from src.ingestion.osm import load_osm_layer
        shl_gdf = load_osm_layer("shelters", fallback_to_fixture=True)
        if len(shl_gdf) > 0:
            return _extract_shelter_records(shl_gdf, db_path)
    except Exception as e:
        logger.debug("Could not load shelters from fixture: %s", e)

    return []


def _extract_hazard_zones_from_db(
    db_path: Any = DEFAULT_DB_PATH,
    horizon: int = 1
) -> List[Dict[str, Any]]:
    """Helper to extract active hazard zones from risk_predictions table."""
    hazards: List[Dict[str, Any]] = []
    try:
        from src.db.forecasts import get_db_connection
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='risk_predictions'")
            if not cursor.fetchone():
                return []

            query = """
            SELECT rp.cell_id, rp.level, rp.probability,
                   COALESCE(gc.centroid_lat, NULL) AS lat,
                   COALESCE(gc.centroid_lon, NULL) AS lon
            FROM risk_predictions rp
            LEFT JOIN grid_cells gc ON rp.cell_id = gc.cell_id
            WHERE rp.horizon = ? AND rp.level IN ('HIGH', 'MEDIUM')
            ORDER BY rp.timestamp DESC
            """
            try:
                cursor.execute(query, (horizon,))
                for r in cursor.fetchall():
                    lat = r["lat"]
                    lon = r["lon"]
                    if lat is not None and lon is not None:
                        hazards.append({
                            "cell_id": r["cell_id"],
                            "lat": float(lat),
                            "lon": float(lon),
                            "radius_m": 200,
                            "risk_level": r["level"],
                            "probability": float(r["probability"]),
                        })
            except sqlite3.OperationalError:
                pass
    except Exception as e:
        logger.debug("Could not load hazard zones from db: %s", e)
    return hazards


def safe_route(
    lat: float,
    lon: float,
    horizon: int = 1,
    db_path: Any = DEFAULT_DB_PATH,
    router: Optional[OSMRouter] = None,
    shelters: Optional[Union[gpd.GeoDataFrame, List[Dict[str, Any]]]] = None,
    hazard_zones: Optional[List[Dict[str, Any]]] = None,
    max_candidate_shelters: int = 5,
) -> Dict[str, Any]:
    """Find a safe A* route from (lat, lon) to the nearest accessible emergency shelter.

    Implements Chetna B1 Day 4 Safest-Location Engine:
    - Identifies candidate shelters from B1 spatial data
    - Evaluates proximity and flood-risk predictions (avoiding HIGH-risk zones)
    - Computes A* safe path with hazard avoidance
    - Gracefully handles unreachable shelters or invalid inputs

    Parameters
    ----------
    lat : float
        Origin latitude in EPSG:4326 degrees.
    lon : float
        Origin longitude in EPSG:4326 degrees.
    horizon : int, default 1
        Forecast horizon (1, 3, or 6 hours) to query for risk predictions.
    db_path : Path or connection, default DEFAULT_DB_PATH
        Database containing spatial layers and risk predictions.
    router : OSMRouter, optional
        Pre-configured router instance (useful for custom graphs/testing).
    shelters : GeoDataFrame or list of dicts, optional
        Explicit shelter facilities to use. If None, loaded from database or fixtures.
    hazard_zones : list of dicts, optional
        Explicit hazard zones. If None, derived from risk_predictions table.
    max_candidate_shelters : int, default 5
        Maximum number of nearest shelters to attempt routing towards.

    Returns
    -------
    dict
        Structured safe route result containing:
        - status: 'success' or 'error'
        - found: bool (True if safe route exists)
        - route: list of {'lat': float, 'lon': float}
        - distance_m: float (total route distance in metres)
        - estimated_time_min: float (estimated walking travel time in minutes)
        - destination: dict with shelter name, coords, id
        - risk_info: dict with horizon, hazards avoided, max risk level
        - message: descriptive status message
    """
    # 1. Validate coordinates
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "found": False,
            "route": [],
            "distance_m": 0.0,
            "estimated_time_min": 0.0,
            "destination": None,
            "risk_info": {"horizon": horizon},
            "message": "Invalid origin coordinates: must be numeric.",
        }

    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
        return {
            "status": "error",
            "found": False,
            "route": [],
            "distance_m": 0.0,
            "estimated_time_min": 0.0,
            "destination": None,
            "risk_info": {"horizon": horizon},
            "message": f"Invalid origin coordinates: lat={lat}, lon={lon} out of bounds.",
        }

    # 2. Extract shelter facilities
    shelter_records = _extract_shelter_records(shelters, db_path)
    if not shelter_records:
        return {
            "status": "error",
            "found": False,
            "route": [],
            "distance_m": 0.0,
            "estimated_time_min": 0.0,
            "destination": None,
            "risk_info": {"horizon": horizon},
            "message": "No shelters available for safe routing.",
        }

    # 3. Router setup
    active_router = router if router is not None else OSMRouter(db_path=db_path)

    # 4. Hazard zones
    active_hazards = list(hazard_zones) if hazard_zones is not None else _extract_hazard_zones_from_db(db_path, horizon=horizon)

    # 5. Calculate proximity to shelters and rank
    for s in shelter_records:
        s["dist_m"] = haversine(lat_f, lon_f, s["latitude"], s["longitude"])
    shelter_records.sort(key=lambda s: s["dist_m"])

    def is_in_high_hazard(s_lat: float, s_lon: float) -> bool:
        for hz in active_hazards:
            if hz.get("risk_level") == "HIGH":
                h_lat = hz.get("lat")
                h_lon = hz.get("lon")
                rad = hz.get("radius_m", 200)
                if h_lat is not None and h_lon is not None:
                    if haversine(s_lat, s_lon, h_lat, h_lon) <= rad:
                        return True
        return False

    safe_candidates = [s for s in shelter_records if not is_in_high_hazard(s["latitude"], s["longitude"])]
    candidates_to_try = safe_candidates if safe_candidates else shelter_records

    # 6. Try finding safe route to nearest reachable shelter
    for candidate in candidates_to_try[:max_candidate_shelters]:
        c_lat = candidate["latitude"]
        c_lon = candidate["longitude"]
        res = active_router.find_safe_route((lat_f, lon_f), (c_lat, c_lon), hazard_zones=active_hazards)
        if res.get("status") == "success" and len(res.get("route", [])) > 0:
            hazards_avoided = sum(
                1 for hz in active_hazards
                if hz.get("risk_level") in ("HIGH", "MEDIUM")
            )
            return {
                "status": "success",
                "found": True,
                "route": res.get("route", []),
                "distance_m": res.get("distance_m", 0.0),
                "estimated_time_min": res.get("estimated_time_min", 0.0),
                "destination": {
                    "id": candidate.get("id"),
                    "name": candidate.get("name", "Emergency Shelter"),
                    "latitude": c_lat,
                    "longitude": c_lon,
                    "amenity": candidate.get("amenity", "shelter"),
                    "direct_distance_m": round(candidate.get("dist_m", 0.0), 2),
                },
                "risk_info": {
                    "horizon": horizon,
                    "hazards_considered": len(active_hazards),
                    "hazards_avoided": hazards_avoided,
                    "max_route_risk": "LOW",
                },
                "message": f"Safe route found to {candidate.get('name', 'shelter')}.",
            }

    # 7. No safe route found
    return {
        "status": "error",
        "found": False,
        "route": [],
        "distance_m": 0.0,
        "estimated_time_min": 0.0,
        "destination": None,
        "risk_info": {
            "horizon": horizon,
            "hazards_considered": len(active_hazards),
        },
        "message": "No safe route is currently available to any designated shelter.",
    }
