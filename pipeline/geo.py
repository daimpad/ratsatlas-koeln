"""Point-in-Polygon gegen die 86 Kölner Stadtteile (shapely); Eigenschaften im Bonner Format (ortsteil_bez …)."""
import json
import re

from shapely import STRtree
from shapely.geometry import Point, shape

from . import config


class Ortsteile:
    def __init__(self, path=config.ORTSTEILE):
        features = json.loads(path.read_text())["features"]
        self.props = [f["properties"] for f in features]
        self.geoms = [shape(f["geometry"]) for f in features]
        self.tree = STRtree(self.geoms)

    def by_name(self, name):
        """Stadtteil zu einem Namen aus der Quelle (auch „Altstadt-Nord“ für „Altstadt/Nord“, Groß-/Kleinschreibung
        egal): (Eigenschaften, Punkt in der Fläche) oder None."""
        key = lambda n: re.sub(r"[\s/-]+", " ", (n or "").strip()).casefold()
        if not hasattr(self, "_namen"):
            self._namen = {key(p["ortsteil_bez"]): i for i, p in enumerate(self.props)}
        i = self._namen.get(key(name))
        return (self.props[i], self.geoms[i].representative_point()) if i is not None else None

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
