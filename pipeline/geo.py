"""Point-in-Polygon gegen die 51 Bonner Ortsteile (shapely)."""
import json

from shapely import STRtree
from shapely.geometry import Point, shape

from . import config


class Ortsteile:
    def __init__(self, path=config.ORTSTEILE):
        features = json.loads(path.read_text())["features"]
        self.props = [f["properties"] for f in features]
        self.geoms = [shape(f["geometry"]) for f in features]
        self.tree = STRtree(self.geoms)

    def locate(self, lon, lat):
        """Liefert die Eigenschaften des Ortsteils, der den Punkt enthält, oder None."""
        hits = self.tree.query(Point(lon, lat), predicate="intersects")
        return self.props[int(hits[0])] if len(hits) else None

    def overlaps(self, geom):
        """Ortsteile, die eine Fläche schneiden: (Eigenschaften, Schnittfläche, Anteil an der Fläche)."""
        out = []
        for i in self.tree.query(geom, predicate="intersects"):
            part = self.geoms[int(i)].intersection(geom)
            if not part.is_empty and geom.area:
                out.append((self.props[int(i)], part, part.area / geom.area))
        return sorted(out, key=lambda x: -x[2])
