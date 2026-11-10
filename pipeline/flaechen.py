"""Vereinfachte Flächen für die Webseite (data/export/koeln/flaechen/*.json).

Die Seite braucht für Navigation, Umrisse und Bebauungspläne keine Zentimetergenauigkeit. Vereinfacht wird mit
etwa 2 m Toleranz (Douglas-Peucker, Topologie je Fläche erhalten), Koordinaten auf 5 Nachkommastellen (rund 1 m).
Die Dateien enden auf .json, damit Webserver sie wie die übrigen Daten komprimieren. Für Verortung und
Datenpaket bleiben die vollen Flächen in data/geo/ maßgeblich."""
import json

from shapely import make_valid
from shapely.geometry import MultiPolygon, mapping, shape

from . import config

TOLERANZ = 0.00002  # Grad, etwa 1,4 m in Nord-Süd- und 2,2 m in Ost-West-Richtung
NACHKOMMA = 5
DATEIEN = {"ortsteile": config.ORTSTEILE, "bezirke": config.STADTBEZIRKE,
           "bebauungsplaene": config.BPLAN}
# Quelle je Datei (config.SOURCES) und Bezeichnung für `meta` (Runde 19b: Lizenz und Namensnennung in jeder Datei)
QUELLE = {"ortsteile": (config.QUELLE_GEO, "Stadt Köln, Stadtteile Köln"),
          "bezirke": (config.QUELLE_GEO, "Stadt Köln, Stadtbezirke Köln"),
          "bebauungsplaene": (config.QUELLE_BPLAN, "Bauleitplanung in NRW (INSPIRE), MHKBD NRW / IT.NRW")}


def _round(o):
    if isinstance(o, float):
        return round(o, NACHKOMMA)
    if isinstance(o, (list, tuple)):
        return [_round(x) for x in o]
    return o


def _gueltig(g):
    """Flächen, die sich selbst schneiden (in den Quelldaten der Stadt z. B. Bebauungsplan 8118-1), gültig machen; aus
    einer gemischten Sammlung nach make_valid bleiben nur die Flächen."""
    if g.is_valid or g.geom_type not in ("Polygon", "MultiPolygon"):
        return g
    v = make_valid(g)
    if v.geom_type == "GeometryCollection":
        polys = [x for x in v.geoms if x.geom_type in ("Polygon", "MultiPolygon")]
        v = MultiPolygon([q for x in polys for q in (x.geoms if x.geom_type == "MultiPolygon" else [x])])
    return v


def simplify(collection, toleranz=TOLERANZ):
    """FeatureCollection mit vereinfachten Geometrien; Eigenschaften unverändert, leere Geometrien bleiben leer."""
    feats = []
    for f in collection.get("features", []):
        g = f.get("geometry")
        if g:
            s = _gueltig(shape(g))
            v = s.simplify(toleranz, preserve_topology=True)
            g = _round(mapping(v if not v.is_empty else s))
        feats.append({"type": "Feature", "properties": f.get("properties", {}), "geometry": g})
    return {"type": "FeatureCollection", "features": feats}


def meta(name, quelle_meta):
    """meta einer vereinfachten Datei: Quelle, Adresse (Bezugsquelle der Datei in data/geo/, sonst config.SOURCES),
    Lizenz mit Namensnennung aus config.SOURCES, Abrufzeit, falls die Quelle sie nennt. Die Seite liest nur `features`."""
    key, titel = QUELLE[name]
    return {"quelle": titel, "url": quelle_meta.get("source") or config.SOURCES[key]["url"],
            "lizenz": config.SOURCES[key]["license"],
            **({"stand": quelle_meta["retrieved_at"]} if quelle_meta.get("retrieved_at") else {}),
            "hinweis": "Für die Karte vereinfacht (etwa 2 m); maßgeblich sind die Flächen in data/geo/ und die Quelle."}


def write(out):
    """Schreibt die vereinfachten Flächen nach out/flaechen/; fehlende Quelldateien werden übersprungen."""
    target = out / "flaechen"
    target.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, src in DATEIEN.items():
        if not src.exists():
            continue
        quelle = json.loads(src.read_text())
        data = {**simplify(quelle), "meta": meta(name, quelle.get("meta") or {})}
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        (target / f"{name}.json").write_text(text)
        sizes[name] = len(text)
    return sizes
