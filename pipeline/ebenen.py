"""Zusätzliche Kartenebenen aus offenen Daten (Schritte `ebenen-laden` und `ebenen`; Entscheidung 07.11.2026).

Ausgewählt sind Daten, die nicht in OpenStreetMap stehen und politisch unmittelbar relevant sind: Förder- und
Sanierungsgebiete, Wohnbaupotenziale, Aufstellungsbeschlüsse zu Bebauungsplänen, Sozialräume, Stimmbezirke,
Fahrradstraßen und Denkmäler (Stadt Köln, dl-de/zero 2.0) sowie Lärm, Starkregen- und Hochwassergefahr und
Schutzgebiete (Land NRW und Bund).

- `ebenen-laden` (einmalig, lokal): lädt jede Quelle höchstens einmal (Zwischenspeicher _kontext_dl/ebenen/, nicht im
  Repository), mit Abstand zwischen den Anfragen und einer festen Obergrenze je Lauf (EBENEN_MAX_ANFRAGEN, Vorgabe 20).
  Anfragen an Server der Stadt nur über diese Liste (Freigabe des Auftraggebers, je Datensatz 1–3 Anfragen).
  Ergebnis: data/ebenen/<schluessel>.geojson in WGS84, auf das Stadtgebiet zugeschnitten, mit ausgewählten Feldern
  (keine Kontaktdaten, keine Personen), und data/ebenen/STAND.json mit Quelle, Lizenz und Abrufdatum.
- `ebenen` (täglich, nach export): vereinfachte Kopien → export/<stadt>/flaechen/ebene_<schluessel>.json und das
  Verzeichnis export/<stadt>/ebenen.json (Titel, Gruppe, Darstellung, Quelle, Lizenz, Stand, Mindestzoom), aus dem die
  Karte das Menü „Ebenen“ aufbaut.

Mindestzoom: Ebenen mit vielen Objekten zeichnet die Karte erst ab dieser Zoomstufe (`mindestzoom` in QUELLEN, nur dann
in ebenen.json; ohne Angabe wie bisher 11, site/app.js). Die Gebietsseiten weisen bei diesen Ebenen auf das Hineinzoomen hin.
Abruf direkt über urllib, nicht über pipeline/net.py oder pipeline/abruf.py: deren Schutz vor Anfragen an die
Stadt (abruf.stadt, Abrufpolitik) greift hier nicht.
"""
import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone

from shapely import make_valid, union_all
from shapely.geometry import mapping, shape

from . import config, flaechen

EBENEN = config.ROOT / "data" / "ebenen"
DL = config.ROOT / "_kontext_dl" / "ebenen"
STAND = EBENEN / "STAND.json"
UA = config.USER_AGENT
ABSTAND = 2.0
MAX_ANFRAGEN = int(os.environ.get("EBENEN_MAX_ANFRAGEN", "20"))
TOLERANZ = 0.00003
RAHMEN_25832 = (340000, 5628000, 372000, 5662000)   # Köln mit Rand (EPSG 25832), Vorauswahl großer Landesdateien          # etwa 3 m für die Karte
STADT_LIZENZ = "dl-de/zero 2.0 (Stadt Köln); " + config.NAMENSNENNUNG
GEO = "https://geoportal.stadt-koeln.de"


def _wfs(dienst, typ):
    return (f"{GEO}/wss/service/{dienst}/guest?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature&TYPENAME={typ}"
            "&SRSNAME=EPSG:4326&OUTPUTFORMAT=" + urllib.parse.quote("application/json; subtype=geojson"))


def _arcgis(pfad):
    return f"{GEO}/arcgis/rest/services/{pfad}/query?where=1%3D1&outFields=*&outSR=4326&returnGeometry=true&f=geojson"


O = "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/"
NRW = "https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/hochwasser/hwrm/"
OGC_PS = "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1/collections/{}/items?bbox=6.7725,50.8304,7.1620,51.0850&f=json&limit=500"
LAND_ZERO = "dl-de/zero 2.0 (Land NRW)"
# Schlüssel → Titel, Gruppe, Darstellung, Quelle, Abrufe [(Datei, URL, Art)], Felder (Quelle → Anzeige)
QUELLEN = {
    "lebenswerte_veedel": {
        "kurz": "Lebenswerte Veedel", "titel": "Programm „Lebenswerte Veedel“ (Sozialräume mit Förderung)", "gruppe": "Förderung und Stadterneuerung",
        "art": "flaeche", "farbe": "#b45309",
        "quelle": "Stadt Köln, Programm „Lebenswerte Veedel – Bürger*innen- und Sozialraumorientierung in Köln“",
        "url": "https://open.nrw/dataset/bdfb64ad-dee9-473c-8fe0-fff8e78e3bf4", "lizenz": STADT_LIZENZ,
        "abrufe": [("veedel.geojson", _wfs("veedel_wfs", "ms:veedel"), "geojson")]},
    "sanierungsgebiete": {
        "kurz": "Sanierungsgebiete", "titel": "Sanierungsgebiete (Flächennutzungsplan)", "gruppe": "Förderung und Stadterneuerung",
        "art": "flaeche", "farbe": "#9a3412",
        "quelle": "Stadt Köln, Flächennutzungsplan Web – Sanierungsgebiete",
        "url": "https://open.nrw/dataset/flachennutzungsplan-web-sanierungsgebiete-k", "lizenz": STADT_LIZENZ,
        # ArcGIS-Dienst der Stadt lieferte am 07.11.2026 eine Webseite statt Daten (wie 04.11. bei den Bebauungsplänen)
        "abrufe": [("sanierung.geojson", _arcgis("planen_und_bauen/flaechennutzungsplan/MapServer/4"), "geojson")],
        "gesperrt": "ArcGIS-Dienst der Stadt liefert eine Webseite statt Daten (07.11.2026)"},
    "baupotenziale": {
        "kurz": "Wohnbaupotenziale", "titel": "Wohnbaupotenziale (Baulücken, Aufstockung, Umstrukturierung)", "gruppe": "Bauen und Wohnen",
        "art": "flaeche", "farbe": "#7c3aed",
        "quelle": "Stadt Köln, Baupotenziale (automatisiert ermittelt, ohne Prüfung im Einzelfall)",
        "url": "https://open.nrw/dataset/3646d09a-03c4-4079-8fad-d5a453bca22e", "lizenz": STADT_LIZENZ, "mindestzoom": 13,
        "abrufe": [("baupotenziale.geojson", _wfs("baupotenziale_extern_wfs", "ms:baupotenzial"), "geojson")]},
    "bplan_aufstellung": {
        "kurz": "B-Pläne im Verfahren", "titel": "Bebauungspläne im Verfahren (Aufstellungsbeschlüsse)", "gruppe": "Bauen und Wohnen",
        "art": "flaeche", "farbe": "#6d28d9",
        "quelle": "Stadt Köln, Bebauungspläne Köln – Aufstellungsbeschlüsse",
        "url": "https://open.nrw/dataset/bebauungsplane-koln-aufstellungsbeschlusse-k", "lizenz": STADT_LIZENZ,
        "abrufe": [("aufstellung.geojson", _arcgis("planen_und_bauen/b_plan_uebersicht/MapServer/3"), "geojson")],
        "gesperrt": "ArcGIS-Dienst der Stadt brach die Verbindung ab (07.11.2026); nicht wiederholt"},
    "sozialraeume": {
        "kurz": "Sozialräume", "titel": "Sozialräume", "gruppe": "Gebietsgliederungen", "art": "grenze", "farbe": "#475569",
        "quelle": "Stadt Köln, Sozialräume Köln", "url": "https://open.nrw/dataset/sozialraume-koln-k", "lizenz": STADT_LIZENZ,
        "abrufe": [("sozialraum.zip", O + "Sozialraum_0.zip", "shapezip")]},
    "stimmbezirke": {
        "kurz": "Stimmbezirke", "titel": "Stimmbezirke", "gruppe": "Gebietsgliederungen", "art": "grenze", "farbe": "#334155",
        "quelle": "Stadt Köln, Stimmbezirke Köln", "url": "https://open.nrw/dataset/stimmbezirke-koln-k", "lizenz": STADT_LIZENZ,
        "mindestzoom": 12, "abrufe": [("stimmbezirk.zip", O + "Stimmbezirk_1.zip", "shapezip")]},
    "fahrradstrassen": {
        "kurz": "Fahrradstraßen", "titel": "Fahrradstraßen (eingerichtet und in Planung)", "gruppe": "Verkehr", "art": "linie", "farbe": "#047857",
        "quelle": "Stadt Köln, Fahrradstraßen", "url": "https://open.nrw/dataset/c639e607-a653-4fb1-bb5f-feafd92d4fb9",
        "lizenz": STADT_LIZENZ,
        "abrufe": [("fahrrad_eingerichtet.geojson", _wfs("fahrradstrassen_wfs", "ms:eingerichtet"), "geojson"),
                   ("fahrrad_planung.geojson", _wfs("fahrradstrassen_wfs", "ms:in_planung"), "geojson")]},
    "naturschutz": {
        "kurz": "Schutzgebiete", "titel": "Natur- und Landschaftsschutzgebiete", "gruppe": "Umwelt", "art": "flaeche", "farbe": "#15803d",
        "quelle": "LANUK NRW, INSPIRE Schutzgebiete in Nordrhein-Westfalen (OGC API)",
        "url": "https://ogc-api.nrw.de/inspire-ps-schutzgebiete/v1", "lizenz": LAND_ZERO,
        "abrufe": [("nsg.geojson", OGC_PS.format("nsg"), "ogcapi"), ("lsg.geojson", OGC_PS.format("lsg"), "ogcapi"),
                   ("ffh.geojson", OGC_PS.format("ffh"), "ogcapi")]},
    "hochwasser": {
        "kurz": "Hochwassergefahr", "titel": "Hochwassergefahr (HQ100 und HQextrem)", "gruppe": "Umwelt", "art": "flaeche", "farbe": "#0369a1",
        "quelle": "Land NRW, Hochwassergefahrenkarten nach HWRM-RL, Überschwemmungsgrenzen",
        "url": NRW, "lizenz": "dl-de/zero 2.0 (Land NRW; Angabe von opengeodata.nrw.de, nicht einzeln geprüft)",
        "abrufe": [("hq100.zip", NRW + "HQ100-Ueberschwemmungsgrenzen_EPSG25832_Shape.zip", "shapezip"),
                   ("hqextrem.zip", NRW + "HQextrem-Ueberschwemmungsgrenzen_EPSG25832_Shape.zip", "shapezip")],
        # je Szenario und Art zu einer Fläche zusammengefasst und um etwa 2 m vereinfacht (Quelle: über 50 MB)
        "zusammenfassen": ("_teil", "ueberflutu", "szenario"), "vereinfachen": 0.00002},
    "denkmaeler": {
        "kurz": "Denkmäler", "titel": "Baudenkmäler (Denkmalliste)", "gruppe": "Stadtbild", "art": "flaeche", "farbe": "#a16207",
        "quelle": "Stadt Köln, Denkmalliste", "url": "https://open.nrw/dataset/41a14703-ad40-4a12-b498-2ec92a6bf903",
        "lizenz": STADT_LIZENZ, "mindestzoom": 14,
        "abrufe": [("denkmal_gebaeude.geojson", _wfs("denkmalliste_wfs", "ms:koeln_denkmal_gebaeude"), "geojson"),
                   ("denkmal_freiflaechen.geojson", _wfs("denkmalliste_wfs", "ms:koeln_denkmal_freiflaechen"), "geojson"),
                   ("denkmal_punkte.geojson", _wfs("denkmalliste_wfs", "ms:koeln_denkmal_punkte"), "geojson")]},
}

_anfragen = 0


def _hole_ogc(name, url):
    """OGC API Features: alle Seiten (rel=next) in eine Datei, höchstens 10 Seiten."""
    pfad = DL / name
    if pfad.exists():
        return pfad
    seiten, naechste = [], url
    while naechste and len(seiten) < 10:
        teil = _hole(f"{name}.{len(seiten)}", naechste)
        seite = json.loads(teil.read_text(encoding="utf-8"))
        seiten.append(seite)
        naechste = next((l["href"] for l in seite.get("links", []) if l.get("rel") == "next"), None)
    pfad.write_text(json.dumps(seiten), encoding="utf-8")
    return pfad


def _hole(name, url):
    """Eine Datei höchstens einmal laden (Zwischenspeicher), mit Abstand und Obergrenze."""
    global _anfragen
    DL.mkdir(parents=True, exist_ok=True)
    pfad = DL / name
    if pfad.exists():
        return pfad
    if _anfragen >= MAX_ANFRAGEN:
        raise RuntimeError(f"Obergrenze von {MAX_ANFRAGEN} Anfragen erreicht (EBENEN_MAX_ANFRAGEN)")
    if _anfragen:
        time.sleep(ABSTAND)
    _anfragen += 1
    print(f"  lade {url[:140]}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        daten = r.read()
    if daten.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        raise RuntimeError(f"{name}: HTML statt Daten (Dienst liefert eine Webseite)")
    pfad.write_bytes(daten)
    return pfad


def _lesen(pfad, art):
    """[(Eigenschaften, Geometrie in WGS84)]"""
    if art == "geojson":
        # die WFS der Stadt liefern trotz SRSNAME=EPSG:4326 Koordinaten in EPSG 25832: an der Größe erkennen und umrechnen
        from pyproj import Transformer
        from shapely import transform
        nach = Transformer.from_crs(25832, 4326, always_xy=True)
        gj = json.loads(pfad.read_text(encoding="utf-8"))
        out = []
        for f in gj.get("features", []):
            if not f.get("geometry"):
                continue
            g = shape(f["geometry"])
            if abs(g.bounds[0]) > 1000:
                g = transform(g, nach.transform, interleaved=False)
            out.append((f.get("properties") or {}, g))
        return out
    if art == "ogcapi":
        out = []
        for seite in json.loads(pfad.read_text(encoding="utf-8")):
            out += [(f.get("properties") or {}, shape(f["geometry"])) for f in seite.get("features", []) if f.get("geometry")]
        return out
    if art == "shapezip":
        import shapefile
        from pyproj import Transformer
        from shapely import transform
        with zipfile.ZipFile(pfad) as z:
            shp = max((n for n in z.namelist() if n.lower().endswith(".shp")), key=lambda n: z.getinfo(n).file_size)
            basis = shp[:-4]
            teile = {e: io.BytesIO(z.read(basis + "." + e)) for e in ("shp", "shx", "dbf")}
            prj = z.read(basis + ".prj").decode("latin-1") if basis + ".prj" in z.namelist() else ""
        epsg = 25832 if "UTM" in prj or "25832" in prj or not prj else 4326
        nach = Transformer.from_crs(epsg, 4326, always_xy=True)
        r = shapefile.Reader(shp=teile["shp"], shx=teile["shx"], dbf=teile["dbf"], encoding="utf-8")
        names = [f[0] for f in r.fields[1:]]
        # landesweite Dateien: nur Objekte, deren Umriss das Stadtgebiet berührt (Rahmen in EPSG 25832), vor dem Umrechnen
        x0, y0, x1, y1 = RAHMEN_25832 if epsg == 25832 else (-1e12, -1e12, 1e12, 1e12)
        out = []
        for i, s in enumerate(r.iterShapes()):
            bb = getattr(s, "bbox", None)
            if bb and (bb[2] < x0 or bb[0] > x1 or bb[3] < y0 or bb[1] > y1):
                continue
            out.append((dict(zip(names, r.record(i))), transform(shape(s.__geo_interface__), nach.transform, interleaved=False)))
        return out
    raise ValueError(art)


def _wert(v):
    if isinstance(v, (int, float, str)) or v is None:
        return v.strip() if isinstance(v, str) else v
    return str(v)


def laden(nur=None):
    """Schritt `ebenen-laden`: Quellen laden und als data/ebenen/<schluessel>.geojson ablegen."""
    nur = set(filter(None, (nur if nur is not None else os.environ.get("EBENEN_NUR", "")).split(",")))
    EBENEN.mkdir(parents=True, exist_ok=True)
    stand = json.loads(STAND.read_text()) if STAND.exists() else {}
    gebiet = union_all([shape(f["geometry"]) for f in json.loads(config.ORTSTEILE.read_text())["features"]]).buffer(0.001)
    heute = datetime.now(timezone.utc).date().isoformat()
    for key, q in QUELLEN.items():
        if nur and key not in nur:
            continue
        if q.get("gesperrt") and os.environ.get("EBENEN_GESPERRTE") != "ja":
            print(f"{key}: übersprungen ({q['gesperrt']})")
            stand[key] = {**stand.get(key, {}), "fehler": q["gesperrt"]}
            continue
        try:
            feats = []
            for datei, url, art in q["abrufe"]:
                teil = datei.rsplit(".", 1)[0]
                for props, g in _lesen((_hole_ogc if art == "ogcapi" else _hole)(datei, url), art):
                    if q.get("vereinfachen"):   # große Flächen vor dem Zuschnitt vereinfachen (Laufzeit)
                        g = g.simplify(q["vereinfachen"], preserve_topology=True)
                    g = make_valid(g)
                    if g.is_empty or not g.intersects(gebiet):
                        continue
                    if q["art"] in ("flaeche", "grenze") and g.geom_type not in ("Point", "MultiPoint"):
                        g = g.intersection(gebiet)
                    props = {k: _wert(v) for k, v in props.items() if k.lower() not in AUSLASSEN}
                    if len(q["abrufe"]) > 1:
                        props["_teil"] = teil
                    feats.append({"type": "Feature", "properties": props,
                                  "geometry": json.loads(json.dumps(mapping(g)), parse_float=lambda x: round(float(x), 6))})
            if q.get("zusammenfassen"):
                gruppen = {}
                for f in feats:
                    k = tuple(f["properties"].get(x) for x in q["zusammenfassen"])
                    gruppen.setdefault(k, []).append(make_valid(shape(f["geometry"])))
                feats = [{"type": "Feature", "properties": dict(zip(q["zusammenfassen"], k)),
                          "geometry": json.loads(json.dumps(mapping(union_all(gs).simplify(q["vereinfachen"], preserve_topology=True))),
                                                 parse_float=lambda x: round(float(x), 6))}
                         for k, gs in sorted(gruppen.items(), key=lambda x: str(x[0]))]
        except Exception as e:   # eine fehlende Quelle hält die übrigen nicht auf
            print(f"{key}: nicht geladen ({e})")
            stand[key] = {**stand.get(key, {}), "fehler": str(e)[:200], "versucht": heute}
            continue
        (EBENEN / f"{key}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "meta": {"quelle": q["quelle"], "lizenz": q["lizenz"], "abgerufen": heute},
             "features": feats}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        stand[key] = {"titel": q["titel"], "quelle": q["quelle"], "url": q["url"], "lizenz": q["lizenz"],
                      "abgerufen": heute, "objekte": len(feats)}
        print(f"{key}: {len(feats)} Objekte → data/ebenen/{key}.geojson")
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{_anfragen} Anfragen")


# Felder, die nie übernommen werden (Kontakt, interne Kennungen ohne Aussage)
AUSLASSEN = {"flurstück", "flurstueck", "eigentum", "gid", "id", "telefon", "fax", "email", "e_mail", "mail", "ansprechpartner", "shape_area", "shape_length", "shape_leng",
             "shape__area", "shape__length", "objectid", "objectid_1", "gml_id", "fid"}


def write():
    """Schritt `ebenen`: vereinfachte Kopien für die Karte und das Verzeichnis ebenen.json."""
    if not STAND.exists():
        print("Ebenen: keine Daten (python -m pipeline ebenen-laden) – übersprungen.")
        return
    stand = json.loads(STAND.read_text())
    ziel = config.EXPORT / config.STADT / "flaechen"
    ziel.mkdir(parents=True, exist_ok=True)
    verzeichnis = []
    for key, q in QUELLEN.items():
        src = EBENEN / f"{key}.geojson"
        if not src.exists():
            continue
        gj = json.loads(src.read_text(encoding="utf-8"))
        felder = ANZEIGE.get(key)
        def eigenschaften(pr):
            out = {k: WERTE.get(v, v) if isinstance(v, str) else v for k, v in pr.items()
                   if (felder is None or k in felder) and v not in ("", None)}
            if "_teil" in pr:
                out["_teil"] = TEILE.get(pr["_teil"], pr["_teil"])
            return out
        gj = {"features": [{**f, "properties": eigenschaften(f["properties"])} for f in gj["features"]]}
        data = flaechen.simplify(gj, TOLERANZ) if q["art"] != "punkt" else gj
        (ziel / f"ebene_{key}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        s = stand.get(key, {})
        verzeichnis.append({"key": key, "kurz": q.get("kurz", q["titel"]), "titel": q["titel"], "gruppe": q["gruppe"], "art": q["art"], "farbe": q["farbe"],
                            "datei": f"flaechen/ebene_{key}.json", "felder": FELDTITEL.get(key, {}),
                            "quelle": q["quelle"], "url": q["url"], "lizenz": q["lizenz"],
                            "stand": s.get("abgerufen"), "objekte": len(gj["features"]),
                            **({"mindestzoom": q["mindestzoom"]} if q.get("mindestzoom") else {})})
    out = config.EXPORT / config.STADT / "ebenen.json"
    out.write_text(json.dumps({"ebenen": verzeichnis}, ensure_ascii=False, indent=1) + "\n")
    print(f"Ebenen: {len(verzeichnis)} → {out}")


# Anzeige: welche Felder die Karte zeigt (Feldname → Beschriftung); erst nach Sichtung der geladenen Daten festgelegt
FELDTITEL = {
    "lebenswerte_veedel": {"Sozialraumgebiet": "Gebiet", "weitere_Informationen": "Weitere Informationen"},
    "baupotenziale": {"Potenzialtyp": "Art", "Flächengröße_in_m2": "Fläche (m²)", "Zulässigkeit_von_Vorhaben": "Zulässigkeit",
                      "Weitere_Hinweise": "Hinweise", "Stadtteil": "Stadtteil", "Kennung_Baupotenzial": "Kennung"},
    "sozialraeume": {"name": "Sozialraum", "stbezirk": "Stadtbezirk"},
    "stimmbezirke": {"nummer": "Stimmbezirk", "stteil": "Stadtteil", "kwbezirk": "Kommunalwahlbezirk"},
    "fahrradstrassen": {"Straßenname": "Straße", "Von_Straße": "von", "Bis_Straße": "bis", "Eingerichtet_im_Jahr": "eingerichtet",
                        "Kraftfahrzeug": "Kfz-Verkehr", "Bemerkung": "Bemerkung"},
    "naturschutz": {"siteName": "Name", "id_localId": "Kennung"},
    "hochwasser": {"szenario": "Wahrscheinlichkeit", "ueberflutu": "Fläche"},
    "denkmaeler": {"Bezeichnung": "Bezeichnung", "Adresse": "Adresse", "Baujahr": "Baujahr", "geschützt_seit": "geschützt seit",
                   "Denkmalnummer": "Denkmalnummer"},
}
ANZEIGE = {k: set(v) for k, v in FELDTITEL.items()}
# Teile einer Ebene (mehrere Abrufe) → Bezeichnung für Legende und Popup
TEILE = {"fahrrad_eingerichtet": "eingerichtet", "fahrrad_planung": "in Planung", "denkmal_gebaeude": "Gebäude",
         "denkmal_freiflaechen": "Freiflächen", "denkmal_punkte": "Einzelobjekte", "nsg": "Naturschutzgebiet",
         "lsg": "Landschaftsschutzgebiet", "ffh": "FFH-Gebiet (Natura 2000)", "hq100": "HQ100 (statistisch einmal in 100 Jahren)",
         "hqextrem": "HQextrem (seltenes Extremhochwasser)"}
# Werte der Quelle → verständliche Bezeichnung
WERTE = {"ueberflutet (blau)": "überflutet", "geschuetzt (gelb)": "durch Hochwasserschutz geschützt (bei Versagen überflutet)"}
