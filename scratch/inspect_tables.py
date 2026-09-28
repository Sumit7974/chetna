import sqlite3

conn = sqlite3.connect('data/chetna.db')
print("Hotspots:")
for r in conn.execute("SELECT hotspot_id, name, city, latitude, longitude FROM hotspots").fetchall():
    print(" ", r)

print("\nCells count:", conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0])
print("Cells sample:")
for r in conn.execute("SELECT id, elevation, slope, flow_acc, vulnerability FROM cells LIMIT 5").fetchall():
    print(" ", r)

conn.close()
