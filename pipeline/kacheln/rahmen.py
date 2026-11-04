"""Rahmen der grauen Kacheln je Zoomstufe (gleich in site/app.js, KACHEL_RAHMEN; geprüft in tests/test_kacheln.py).

Zoom 10–12 zeigen die Region um Bonn, Zoom 13–14 Bonn mit etwa 7 km Rand, Zoom 15–16 Bonn mit etwa 2 km Rand.
Außerhalb fordert die Seite keine Kacheln an.
"""
import math

BONN = (7.0225, 50.6327, 7.2107, 50.7744)  # lon_min, lat_min, lon_max, lat_max (Grenzen der Stadtbezirke)
ZMIN, ZMAX = 10, 16
VEKTOR_MAXZOOM = 15  # Protomaps-Builds enthalten Vektorkacheln bis Zoom 15; MapLibre zeichnet Zoom 16 daraus


def rand(z):
    """Rand in Grad (lon, lat) um Bonn je Zoomstufe der Rasterkacheln."""
    if z <= 9:
        return 1.5, 1.0
    if z <= 12:
        return 0.5, 0.35
    if z <= 14:
        return 0.1, 0.1
    return 0.03, 0.03


def rahmen(z):
    lo1, la1, lo2, la2 = BONN
    d = rand(z)
    return lo1 - d[0], la1 - d[1], lo2 + d[0], la2 + d[1]


def kachel(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def kachelbereich(z):
    """(x1, y1, x2, y2) der Kacheln im Rahmen, Grenzen eingeschlossen."""
    lo1, la1, lo2, la2 = rahmen(z)
    x1, y1 = kachel(lo1, la2, z)
    x2, y2 = kachel(lo2, la1, z)
    return x1, y1, x2, y2


if __name__ == "__main__":
    # Plan für rendern.mjs: Kachelbereich je Zoomstufe als JSON
    import json
    print(json.dumps({z: kachelbereich(z) for z in range(ZMIN, ZMAX + 1)}))
