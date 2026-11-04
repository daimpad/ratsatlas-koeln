"""Kölner Geodaten für die Pipeline: Stadtteile, Stadtbezirke und Straßenverzeichnis (Schritt `geo-koeln`).

Quellen (dl-de/zero 2.0, Namensnennung „Datenquelle: Stadt Köln – offenedaten-koeln.de“): Shapefiles der Datensätze
„Stadtteile Köln“, „Stadtbezirke Köln“ und „Straßen Köln“ (config.GEO_DOWNLOADS), ETRS89/UTM 32N (EPSG 25832).
Die Zip-Dateien liegen in data/raw/geo/; fehlen sie, werden sie einmal geladen (eine Verbindung, Abstand wie beim
OParl-Abruf). Ausgabe in WGS84 mit den Eigenschaftsnamen des Bonner Modells:
- stadtteile_koeln.geojson:   ortsteil (Nummer), ortsteil_bez, bezirk (Nummer), bezirk_bez
- stadtbezirke_koeln.geojson: bezirk, bezirk_bez
- strassen_koeln.json:        Name → Lagen je Stadtteil (Gazetteer aus geocode.py), dazu Kreuzungen
Straßennamen werden ausgeschrieben („Aachener Str.“ → „Aachener Straße“), damit Titel mit „Straße“, „Strasse“ und
„Str.“ gleichermaßen gefunden werden. Gleichnamige Straßen nach Eingemeindungen bleiben als getrennte Lagen erhalten.
"""
import io
import json
import re
import time
import urllib.request
import zipfile

import numpy as np
import shapefile
import shapely
from pyproj import Transformer
from shapely.geometry import mapping, shape

from . import config

ROH = config.RAW / "geo"
NACH_WGS84 = Transformer.from_crs(25832, 4326, always_xy=True)
TOLERANZ_M = 2.0   # Vereinfachung der Flächen (Meter), sichtbar erst weit unter Straßenbreite


def _zip(name):
    pfad = ROH / f"{name}.zip"
    if not pfad.exists():
        ROH.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(config.GEO_DOWNLOADS[name], headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as r:
            pfad.write_bytes(r.read())
        time.sleep(config.ABRUF_ABSTAND)
    return zipfile.ZipFile(pfad)


def _reader(z, basis):
    namen = {n.split("/")[-1].lower(): n for n in z.namelist()}
    teil = lambda e: io.BytesIO(z.read(namen[f"{basis}{e}".lower()]))
    return shapefile.Reader(shp=teil(".shp"), dbf=teil(".dbf"), shx=teil(".shx"), encoding="utf-8")


def _wgs84(geom, toleranz=0.0):
    if toleranz:
        geom = geom.simplify(toleranz, preserve_topology=True)
    geom = shapely.transform(geom, lambda c: np.column_stack(NACH_WGS84.transform(c[:, 0], c[:, 1])))
    return shapely.set_precision(geom, 1e-6)


def _transform_coords(coords):
    xs, ys = zip(*coords)
    lon, lat = NACH_WGS84.transform(xs, ys)
    return [[round(a, 6), round(b, 6)] for a, b in zip(lon, lat)]


def strassenname(name):
    """Amtlicher Name ausgeschrieben: „Aachener Str.“ → „Aachener Straße“, „Edisonstr.“ → „Edisonstraße“."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    return re.sub(r"([Ss])tr\.$", r"\1traße", name)


def _flaechen(z, basis, eigenschaften, toleranz=TOLERANZ_M):
    r = _reader(z, basis)
    feats = []
    for sr in r.iterShapeRecords():
        geom = _wgs84(shape(sr.shape.__geo_interface__), toleranz)
        feats.append({"type": "Feature", "properties": eigenschaften(sr.record.as_dict()), "geometry": mapping(geom)})
    return feats


def _schreibe_geojson(pfad, feats, quelle):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps({
        "type": "FeatureCollection",
        "meta": {"source": quelle, "license": config.SOURCES[config.QUELLE_GEO]["license"],
                 "crs": "WGS84 (EPSG 4326), umgerechnet aus EPSG 25832", "vereinfacht_m": TOLERANZ_M},
        "features": feats}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def write():
    teile = _flaechen(_zip("stadtteile"), "Stadtteil", lambda a: {
        "ortsteil": int(a["nummer"]), "ortsteil_bez": a["name"].strip(),
        "bezirk": int(a["nr_stbez"]), "bezirk_bez": a["stbezirk"].strip()})
    bezirke = _flaechen(_zip("stadtbezirke"), "Stadtbezirk", lambda a: {
        "bezirk": int(a["nummer"]), "bezirk_bez": a["name"].strip()})
    if len(teile) != 86 or len(bezirke) != 9:
        raise RuntimeError(f"unerwartete Anzahl: {len(teile)} Stadtteile, {len(bezirke)} Stadtbezirke (erwartet 86/9)")
    teile.sort(key=lambda f: f["properties"]["ortsteil"])
    bezirke.sort(key=lambda f: f["properties"]["bezirk"])
    _schreibe_geojson(config.ORTSTEILE, teile, config.GEO_DOWNLOADS["stadtteile"])
    _schreibe_geojson(config.STADTBEZIRKE, bezirke, config.GEO_DOWNLOADS["stadtbezirke"])
    print(f"{len(teile)} Stadtteile → {config.ORTSTEILE}; {len(bezirke)} Stadtbezirke → {config.STADTBEZIRKE}")

    from .geocode import Gazetteer   # liest die eben geschriebenen Flächen
    r = _reader(_zip("strassen"), "Strasse")
    ways = []
    for sr in r.iterShapeRecords():
        a, s = sr.record.as_dict(), sr.shape
        grenzen = list(s.parts) + [len(s.points)]
        for i in range(len(s.parts)):
            pts = s.points[grenzen[i]:grenzen[i + 1]]
            if len(pts) >= 2:
                ways.append({"name": strassenname(a["str_amtl"] or a["name"]), "highway": None,
                             "schluessel": a["nummer"], "coords": _transform_coords(pts)})
    gaz = Gazetteer(ways=ways, street_points=())
    for eintraege in gaz.streets.values():
        for e in eintraege:
            e["source"] = config.QUELLE_STRASSEN
    kreuzungen = {f"{a}|{b}": sorted(v) for (a, b), v in sorted(gaz.crossings.items())}
    config.STRASSEN.write_text(json.dumps({
        "meta": {"source": config.GEO_DOWNLOADS["strassen"], "license": config.SOURCES[config.QUELLE_STRASSEN]["license"],
                 "note": "Ortsteile (Stadtteile) je Straße per Verschneidung mit den Stadtteilflächen; component = räumlich "
                         "getrennte Lage desselben Namens (u. a. gleichnamige Straßen nach Eingemeindungen); kreuzungen = "
                         "Stadtteile, in denen sich zwei Straßen berühren; Namen ausgeschrieben (Str. → Straße)"},
        "streets": dict(sorted(gaz.streets.items())),
        "kreuzungen": kreuzungen}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mehrfach = sum(1 for e in gaz.streets.values() if len({x["component"] for x in e}) > 1)
    print(f"{len(gaz.streets)} Straßennamen ({mehrfach} mit mehreren Lagen), {len(kreuzungen)} Kreuzungen → {config.STRASSEN}")
