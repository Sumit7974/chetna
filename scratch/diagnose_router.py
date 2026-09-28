from src.routing.router import _extract_shelter_records, OSMRouter
from src.ingestion.osm import load_osm_layer
import networkx as nx

shelters = _extract_shelter_records(None, None)
print("Shelters found:", len(shelters))
for s in shelters:
    print(" ", s)

roads = load_osm_layer("roads", fallback_to_fixture=True)
print("Roads found:", len(roads))
router = OSMRouter()
G = router._get_graph(25.6093, 85.1376)
print("Graph nodes:", len(G.nodes), "edges:", len(G.edges))
if len(G.nodes) > 0:
    first_node = list(G.nodes(data=True))[0]
    print("Sample node:", first_node)
