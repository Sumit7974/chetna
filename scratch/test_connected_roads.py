import sys
sys.path.insert(0, '.')
import networkx as nx
from shapely.geometry import LineString
import geopandas as gpd
from src.routing.router import build_road_graph_from_roads, safe_route, OSMRouter
from src.ingestion.pilot_config import GEOGRAPHIC_CRS

# Connected road lines for Patna
road_lines = [
    # Bailey Road (Jawaharlal Nehru Marg) - East-West spine
    {"osm_id": "mock_road_01", "name": "Bailey Road (Jawaharlal Nehru Marg)", "highway": "trunk", 
     "coords": [(85.060, 25.612), (85.084, 25.612), (85.120, 25.612), (85.140, 25.612)]},
    # Patliputra Station Link
    {"osm_id": "mock_road_01b", "name": "Patliputra Station Road", "highway": "secondary",
     "coords": [(85.084, 25.612), (85.084, 25.625)]},
    # Frazer Road / Exhibition Road
    {"osm_id": "mock_road_02", "name": "Frazer Road / Exhibition Road", "highway": "primary", 
     "coords": [(85.138, 25.602), (85.140, 25.612), (85.143, 25.618)]},
    # Gandhi Maidan to Ashok Rajpath link
    {"osm_id": "mock_road_02b", "name": "Gandhi Maidan North Connector", "highway": "secondary",
     "coords": [(85.143, 25.618), (85.143, 25.625)]},
    # Ashok Rajpath - Northern arterial along Ganga
    {"osm_id": "mock_road_03", "name": "Ashok Rajpath", "highway": "primary", 
     "coords": [(85.090, 25.635), (85.130, 25.635), (85.143, 25.625), (85.168, 25.615), (85.220, 25.615)]},
    # Boring Canal Road
    {"osm_id": "mock_road_04", "name": "Boring Canal Road", "highway": "primary", 
     "coords": [(85.120, 25.612), (85.122, 25.622), (85.130, 25.635)]},
    # Kankarbagh Main Road & Railway Overbridge to Patna Jn
    {"osm_id": "mock_road_05", "name": "Kankarbagh Main Road", "highway": "primary", 
     "coords": [(85.138, 25.602), (85.140, 25.595), (85.155, 25.595), (85.164, 25.599), (85.185, 25.595)]},
    # Stadium Link to Ashok Rajpath
    {"osm_id": "mock_road_05b", "name": "Moin-ul-Haq Stadium Connector", "highway": "secondary",
     "coords": [(85.164, 25.599), (85.168, 25.605), (85.168, 25.615)]},
    # Patna New Bypass (NH 30 / NH 31)
    {"osm_id": "mock_road_06", "name": "Patna Bypass Road (NH 30)", "highway": "trunk", 
     "coords": [(85.080, 25.570), (85.140, 25.570), (85.155, 25.570), (85.220, 25.570)]},
    # Old Bypass / Kankarbagh south link
    {"osm_id": "mock_road_06b", "name": "Old Bypass Connector", "highway": "secondary",
     "coords": [(85.155, 25.595), (85.155, 25.570)]},
]

road_records = [{"osm_id": r["osm_id"], "name": r["name"], "highway": r["highway"]} for r in road_lines]
road_geoms = [LineString(r["coords"]) for r in road_lines]
roads_gdf = gpd.GeoDataFrame(road_records, geometry=road_geoms, crs=GEOGRAPHIC_CRS)

G = build_road_graph_from_roads(roads_gdf)
print("Graph nodes:", len(G.nodes), "edges:", len(G.edges))
print("Is connected:", nx.is_connected(G.to_undirected()))
print("Connected components:", nx.number_connected_components(G.to_undirected()))

# Test safe_route from various Patna neighborhoods
router = OSMRouter(graph=G)
for start_name, (lat, lon) in [
    ("Rajendra Nagar", (25.599, 85.164)),
    ("Kankarbagh", (25.596, 85.155)),
    ("Boring Road", (25.618, 85.122)),
    ("Bailey Road", (25.612, 85.084)),
    ("Gandhi Maidan", (25.618, 85.143)),
    ("Patna Junction", (25.602, 85.138)),
]:
    res = safe_route(lat, lon, router=router)
    print(f"{start_name}: found={res.get('found')}, dist={res.get('distance_m')}m, dest={res.get('destination', {}).get('name')}")
