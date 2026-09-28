import sys
sys.path.insert(0, '.')
from src.routing.router import OSMRouter, safe_route

router = OSMRouter()
# Bailey Road coordinates: 25.612, 85.06 to 25.613, 85.10
res = router.find_safe_route((25.612, 85.06), (25.613, 85.10))
print("Direct road route:", res.get("status"), len(res.get("route", [])))

# Now safe_route from near a road node
res2 = safe_route(25.612, 85.06)
print("Safe route from (25.612, 85.06):", res2.get("status"), res2.get("found"), res2.get("message"))
if res2.get("found"):
    print("  Distance:", res2.get("distance_m"), "Destination:", res2.get("destination", {}).get("name"))
