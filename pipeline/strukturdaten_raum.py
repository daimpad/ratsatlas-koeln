"""Raumabgleich der Strukturdaten Köln (Phase 2; Datenvertrag „Strukturdaten“ 1.1, Entscheidungen 10.11.2026).

Eingaben (ohne Netz; aufgerufen aus pipeline/strukturdaten.py, Schritt `strukturdaten`):
- Statistische Quartiere Köln (Stadt Köln; Datei auf offenedaten-koeln.de, Datensatzseite open.nrw, Datenlizenz
  Deutschland – Zero – Version 2.0, Namensnennung wie bei allen Kölner Geodaten des Projekts): ein Shapefile im
  ZIP-Archiv, geladen von `strukturdaten-abruf` (Schlüssel `quartiere`). Gelesen nur mit zipfile und pyshp, ohne
  Entpacken auf die Platte; das Koordinatenbezugssystem kommt aus der .prj-Datei (am 10.11.2026 ETRS89/UTM 32N,
  EPSG 25832).
- Stadtteile und Stadtbezirke aus data/geo/ (pipeline/geodaten.py: Shapefiles der Stadt, WGS84, mit
  geodaten.TOLERANZ_M vereinfacht, Koordinaten auf 1e-6 Grad gerundet). Eine unvereinfachte Fassung liegt nicht im
  Repository; data/geo ist die beste verfügbare Geometrie. Wirkung: Die Grenzen weichen bis etwa TOLERANZ_M von der
  Quelle ab, an den Rändern entstehen kleine Splitter (Anteile unter SPLITTER_ANTEIL); sie werden gemeldet, nicht
  zugeordnet.

Ausgaben (Rückgabe an strukturdaten.write, das die Dateien schreibt):
- raum/stadtbezirk.geojson, raum/stadtteil.geojson: Geometrie unverändert aus data/geo; raum/quartier.geojson: aus dem
  Shapefile, in EPSG 25832 mit TOLERANZ_M vereinfacht und nach WGS84 umgerechnet wie geodaten._wgs84. Properties
  laut Vertrag: raum_id (Nummer der Quelle als Text), name, raumebene, eltern_id, quelle, lizenz. `eltern_id` steht nur,
  wenn Verschneidung, Nummer und Attribut dasselbe Ziel nennen (Prüfstatus ok); bei Stadtbezirken leer (oberste Ebene
  mit Geometrie; die Gesamtstadt steht in werte.tsv als raumebene gesamtstadt, raum_id 0, ohne Geometrie).
- zuordnung.tsv: Quartier → Stadtteil und Stadtteil → Stadtbezirk durch Verschneidung in EPSG 25832 (Quartiere
  unvereinfacht aus dem Shapefile, Stadtteile und Stadtbezirke aus data/geo zurückgerechnet); eine Zeile je Paar mit
  Flächenanteil ≥ SPLITTER_ANTEIL. `flaechenanteil` = Anteil der Fläche der Einheit, der im Ziel liegt (4 Stellen).
  `methode`: verschneidung_nummer (Ziel stimmt mit der Nummer überein: Quartier = erste drei Ziffern, Stadtteil =
  erste Ziffer) oder verschneidung (nur geometrisch). `konfidenz`: hoch (verschneidung_nummer, Anteil ≥ ANTEIL_HOCH,
  Attribut der Quelle widerspricht nicht), mittel (verschneidung_nummer sonst), niedrig (verschneidung).
- audit_raumabgleich.tsv: eine Zeile je Einheit aus Geometrie oder Blatt Daten mit Hauptziel, Ziel laut Nummer und
  laut Attribut, Übereinstimmung, weiteren Zielen, Splittern, Anteil außerhalb aller Ziele und Prüfstatus ok,
  abweichung oder nicht_zugeordnet mit Grund. Einheiten ohne Geometrie, ohne Werte oder ohne Ziel werden gemeldet, nie
  stillschweigend zugeordnet.

Keine Werte werden zwischen Raumebenen verrechnet (keine Summen, keine Anteile aus Flächen): die Zuordnung beschreibt
nur die Lage der Einheiten zueinander.
"""
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import shapefile
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape

from . import config, geodaten

QUARTIERE_URL = "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/Statistisches_Quartier_0.zip"
QUARTIERE_DATENSATZ_URL = "https://open.nrw/dataset/statistische-quartiere-koln-k"
QUARTIERE_TITEL = "Statistische Quartiere Köln"
# Stand der Ressource laut open.nrw (Metadaten gelesen am 10.11.2026); nur zur Begründung des Datenstands
QUARTIERE_STAND_PORTAL = "24.09.2026"
GEO_HERAUSGEBER = "Stadt Köln"
GEO_LIZENZ = "Datenlizenz Deutschland – Zero – Version 2.0"
GEO_LIZENZ_URL = "https://www.govdata.de/dl-de/zero-2-0"
GEO_NAMENSNENNUNG = config.NAMENSNENNUNG
LIZENZ_TEXT = f"{GEO_LIZENZ} ({GEO_LIZENZ_URL}); {GEO_NAMENSNENNUNG}"

TOLERANZ_M = geodaten.TOLERANZ_M   # Vereinfachung der Quartiersflächen wie data/geo (Meter)
UTM = 25832                         # metrisches Bezugssystem der Verschneidung (ETRS89/UTM 32N)
# Teilflächen unter diesem Anteil gelten als Randsplitter: gemeldet (audit_raumabgleich.tsv), nicht zugeordnet. Am
# 10.11.2026 war der größte Splitter eines Quartiers 0,40 % seiner Fläche, der eines Stadtteils 0,06 %; mit den
# unvereinfachten Stadtteilflächen der Stadt (einmalige Gegenprobe) gab es keine Splitter.
SPLITTER_ANTEIL = 0.01
ANTEIL_HOCH = 1 - SPLITTER_ANTEIL   # Hauptanteil für Prüfstatus ok und konfidenz hoch
MAX_ENTPACKT = 500_000_000          # Summe der entpackten Größen im ZIP-Archiv (Schutz vor überlangen Archiven)

EBENEN = {   # Ebene → (Plural für Texte, Feld des Attributs in der Geometriequelle, Bezeichnung für Texte)
    "stadtbezirk": ("Stadtbezirke", "", "Stadtbezirk"),
    "stadtteil": ("Stadtteile", "bezirk", "Stadtteil"),
    "quartier": ("Quartiere", "nr_stteil", "Quartier"),
}
PAARE = (("stadtteil", "stadtbezirk"), ("quartier", "stadtteil"))   # Reihenfolge in zuordnung.tsv und Audit

KOPF_ZUORDNUNG = ["von_ebene", "von_id", "nach_ebene", "nach_id", "flaechenanteil", "methode", "konfidenz"]
KOPF_AUDIT = ["von_ebene", "von_id", "name", "nach_ebene", "nach_id", "flaechenanteil", "methode", "konfidenz",
              "pruefstatus", "nach_id_nummer", "nach_id_attribut", "uebereinstimmung", "weitere_ziele", "splitter",
              "splitter_max_anteil", "ausserhalb_anteil", "in_geometrie", "in_werten", "grund"]
AUDIT_SPALTEN = {
    "von_ebene": "Raumebene der geprüften Einheit (quartier, stadtteil)",
    "von_id": "Nummer der Einheit aus der Quelle",
    "name": "Name laut Geometriequelle, ohne Geometrie laut Blatt Daten",
    "nach_ebene": "Zielebene (stadtteil, stadtbezirk)",
    "nach_id": "Ziel mit dem größten Flächenanteil, falls dieser mindestens splitter_anteil (meta.json) beträgt",
    "flaechenanteil": "Anteil der Fläche der Einheit in nach_id, 4 Nachkommastellen",
    "methode": "methode der Zeile in zuordnung.tsv für nach_id",
    "konfidenz": "konfidenz der Zeile in zuordnung.tsv für nach_id",
    "pruefstatus": "ok (Verschneidung, Nummer und Attribut nennen dasselbe Ziel, flaechenanteil mindestens anteil_hoch, "
                   "Werte vorhanden), abweichung (zugeordnet, mindestens eine Prüfung weicht ab; Grund in grund) oder "
                   "nicht_zugeordnet (ohne Geometrie oder ohne Ziel mit mindestens splitter_anteil)",
    "nach_id_nummer": "Ziel laut Nummer (Quartier: erste drei Ziffern = Stadtteil; Stadtteil: erste Ziffer = "
                      "Stadtbezirk)",
    "nach_id_attribut": "Ziel laut Attribut der Geometriequelle (Quartiere: Feld nr_stteil des Shapefiles; Stadtteile: "
                        "Eigenschaft bezirk in data/geo)",
    "uebereinstimmung": "ja, wenn nach_id, nach_id_nummer und (falls vorhanden) nach_id_attribut gleich sind, sonst nein",
    "weitere_ziele": "Anzahl weiterer Ziele mit mindestens splitter_anteil (je eine Zeile in zuordnung.tsv)",
    "splitter": "Anzahl der Ziele mit einem Anteil über 0 und unter splitter_anteil (nicht zugeordnet)",
    "splitter_max_anteil": "größter dieser Anteile, 4 Nachkommastellen (0.0000 = unter 0.00005); leer ohne Splitter",
    "ausserhalb_anteil": "Anteil der Fläche außerhalb aller Ziele, 4 Nachkommastellen; leer ohne Geometrie",
    "in_geometrie": "ja, wenn die Einheit in der Geometriequelle steht",
    "in_werten": "ja, wenn die Einheit im Blatt Daten des Statistischen Datenkatalogs steht",
    "grund": "Begründung des Prüfstatus",
}

_NACH_UTM = Transformer.from_crs(4326, UTM, always_xy=True)


def _anteil(wert):
    return f"{wert:.4f}"


def _sortiert(ids):
    return sorted(ids, key=lambda i: (int(i), i))


def pruefsumme(pfad):
    return hashlib.sha256(Path(pfad).read_bytes()).hexdigest()


# --- Quellen lesen ----------------------------------------------------------------------------------------------------

def _shapefile(pfad):
    """(Reader, CRS, Datum der .shp im Archiv) des einzigen Shapefiles im ZIP-Archiv; nur mit Parsern geöffnet."""
    if not zipfile.is_zipfile(pfad):
        raise ValueError("kein ZIP-Archiv")
    with zipfile.ZipFile(pfad) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > MAX_ENTPACKT:
            raise ValueError(f"ZIP-Archiv entpackt größer als {MAX_ENTPACKT} Bytes")
        shp = [i for i in infos if i.filename.lower().endswith(".shp")]
        if len(shp) != 1:
            raise ValueError(f"genau ein Shapefile im ZIP-Archiv erwartet, gefunden: {len(shp)}")
        basis = shp[0].filename[:-4]
        teile = {}
        for endung in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            treffer = [i for i in infos if i.filename.lower() == (basis + endung).lower()]
            if not treffer and endung != ".cpg":
                raise ValueError(f"{basis}{endung} fehlt im ZIP-Archiv")
            teile[endung] = z.read(treffer[0]) if treffer else None
        try:
            datum = date(*shp[0].date_time[:3])
        except ValueError:   # ungültiges Datum im ZIP-Kopf: nur nicht angegeben
            datum = None
    if teile[".cpg"] is not None and teile[".cpg"].decode("ascii", "replace").strip().upper() not in ("UTF-8", "UTF8"):
        raise ValueError(f"unerwartete Zeichenkodierung in {basis}.cpg: {teile['.cpg'][:20]!r}")
    crs = CRS.from_wkt(teile[".prj"].decode("utf-8"))   # nur WKT (auch ESRI-WKT), keine anderen Kennungen
    if not crs.is_projected:
        raise ValueError(f"{basis}.prj: kein projiziertes Koordinatenbezugssystem ({crs.name})")
    reader = shapefile.Reader(shp=io.BytesIO(teile[".shp"]), shx=io.BytesIO(teile[".shx"]),
                              dbf=io.BytesIO(teile[".dbf"]), encoding="utf-8")
    return reader, crs, datum


class Quartiere:
    """Statistische Quartiere aus dem Shapefile: {Nummer: {name, attribut, geom (EPSG 25832 oder None)}}."""

    FELDER = ("nummer", "name", "nr_stteil")

    def __init__(self, pfad):
        reader, crs, self.datum = _shapefile(pfad)
        self.crs_name, self.crs_epsg = crs.name, crs.to_epsg()
        zu_utm = None if crs.equals(CRS.from_epsg(UTM), ignore_axis_order=True) else Transformer.from_crs(
            crs, UTM, always_xy=True)
        felder = [f[0] for f in reader.fields[1:]]
        fehlen = [f for f in self.FELDER if f not in felder]
        if fehlen:
            raise ValueError(f"Shapefile ohne Felder {fehlen}")
        self.einheiten = {}
        for sr in reader.iterShapeRecords():
            a = sr.record.as_dict()
            nummer = str(a["nummer"] if a["nummer"] is not None else "").strip()
            if not re.fullmatch(r"\d{9}", nummer):
                raise ValueError(f"Shapefile: unerwartete Quartiersnummer {nummer!r} (erwartet 9 Ziffern)")
            if nummer in self.einheiten:
                raise ValueError(f"Shapefile: Quartier {nummer} doppelt")
            geom = None
            if sr.shape.shapeType != shapefile.NULL:
                if sr.shape.shapeType not in (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM):
                    raise ValueError(f"Shapefile: Quartier {nummer} ist keine Fläche (Typ {sr.shape.shapeType})")
                geom = shape(sr.shape.__geo_interface__)
                if zu_utm is not None:
                    geom = shapely.transform(geom, lambda c: np.column_stack(zu_utm.transform(c[:, 0], c[:, 1])))
                if geom.is_empty or geom.area <= 0:
                    geom = None
            self.einheiten[nummer] = {"name": " ".join(str(a["name"] or "").split()),
                                      "attribut": str(a["nr_stteil"] or "").strip(), "geom": geom,
                                      "repariert": False}
        if not self.einheiten:
            raise ValueError("Shapefile ohne Quartiere")
        for e in self.einheiten.values():
            if e["geom"] is not None and not e["geom"].is_valid:
                e["geom"], e["repariert"] = shapely.make_valid(e["geom"]), True


def anzahl_quartiere(pfad):
    """Datensätze des Shapefiles (für das Abrufprotokoll); prüft dabei Aufbau, Felder und Geometrie."""
    return len(Quartiere(pfad).einheiten)


def gebiete(pfad, ebene):
    """Stadtteile oder Stadtbezirke aus data/geo: {Nummer: {name, attribut, geometrie (GeoJSON, unverändert),
    geom (EPSG 25832)}}, dazu meta der Datei."""
    id_feld, name_feld = ("ortsteil", "ortsteil_bez") if ebene == "stadtteil" else ("bezirk", "bezirk_bez")
    attribut = EBENEN[ebene][1]
    daten = json.loads(Path(pfad).read_text(encoding="utf-8"))
    aus = {}
    for f in daten["features"]:
        p = f["properties"]
        rid = str(p[id_feld])
        if not rid.isdigit() or rid in aus:
            raise ValueError(f"{Path(pfad).name}: unerwartete oder doppelte Nummer {rid!r}")
        geom = shapely.transform(shape(f["geometry"]),
                                 lambda c: np.column_stack(_NACH_UTM.transform(c[:, 0], c[:, 1])))
        aus[rid] = {"name": p[name_feld], "attribut": str(p[attribut]) if attribut else "",
                    "geometrie": f["geometry"], "geom": geom if geom.is_valid else shapely.make_valid(geom),
                    "repariert": not geom.is_valid}
    return aus, daten.get("meta", {})


# --- Verschneidung und Prüfung ----------------------------------------------------------------------------------------

def verschneiden(geom, ziele, baum, ids, gesamt):
    """(Teile [(Anteil, Ziel)] absteigend, Anteil außerhalb aller Ziele) einer Fläche in EPSG 25832."""
    flaeche = geom.area
    teile = []
    for j in sorted(int(j) for j in baum.query(geom)):
        a = shapely.intersection(geom, ziele[ids[j]]["geom"]).area
        if a > 0:
            teile.append((a / flaeche, ids[j]))
    teile.sort(key=lambda t: (-t[0], int(t[1])))
    aussen = max(0.0, flaeche - shapely.intersection(geom, gesamt).area) / flaeche
    return teile, aussen


def nummer_ziel(von_ebene, rid):
    return rid[:3] if von_ebene == "quartier" else rid[:1]


def abgleich(von_ebene, nach_ebene, einheiten, ziele, werte_namen):
    """Zuordnungszeilen, Auditzeilen und Eltern (nur Prüfstatus ok) für alle Einheiten aus Geometrie oder Werten.

    einheiten: {Nummer: {name, attribut, geom}} (Geometriequelle); ziele: {Nummer: {geom}}; werte_namen: {Nummer: Name}
    der Einheiten mit Zeilen im Blatt Daten."""
    ids = _sortiert(ziele)
    baum = shapely.STRtree([ziele[i]["geom"] for i in ids])
    gesamt = shapely.union_all([ziele[i]["geom"] for i in ids])
    ziel_plural, _, ziel_wort = EBENEN[nach_ebene]
    attr_feld = EBENEN[von_ebene][1]
    zuordnung, audit, eltern = [], [], {}
    for rid in _sortiert(set(einheiten) | set(werte_namen)):
        e = einheiten.get(rid)
        nummer = nummer_ziel(von_ebene, rid)
        z = {"von_ebene": von_ebene, "von_id": rid, "name": (e or {}).get("name") or werte_namen.get(rid, ""),
             "nach_ebene": nach_ebene, "nach_id_nummer": nummer, "nach_id_attribut": (e or {}).get("attribut", ""),
             "in_geometrie": "ja" if e and e["geom"] is not None else "nein",
             "in_werten": "ja" if rid in werte_namen else "nein", "uebereinstimmung": "nein"}
        gruende = []
        if e is not None and e.get("repariert"):
            gruende.append("Geometrie der Quelle ungültig, mit make_valid repariert")
        if e is None or e["geom"] is None:
            z["pruefstatus"] = "nicht_zugeordnet"
            gruende.insert(0, "keine Geometrie in der Quelle" + ("" if e is None else " (leere Fläche)")
                           + ("; Werte im Blatt Daten vorhanden" if rid in werte_namen else ""))
            z["grund"] = "; ".join(gruende)
            audit.append(z)
            continue
        teile, aussen = verschneiden(e["geom"], ziele, baum, ids, gesamt)
        zugeordnet = [(a, n) for a, n in teile if a >= SPLITTER_ANTEIL]
        splitter = [(a, n) for a, n in teile if a < SPLITTER_ANTEIL]
        attribut = z["nach_id_attribut"]
        z.update({"weitere_ziele": str(max(0, len(zugeordnet) - 1)), "splitter": str(len(splitter)),
                  "splitter_max_anteil": _anteil(max(a for a, _ in splitter)) if splitter else "",
                  "ausserhalb_anteil": _anteil(aussen)})
        zeilen = []
        for a, n in zugeordnet:
            methode = "verschneidung_nummer" if n == nummer else "verschneidung"
            konfidenz = ("niedrig" if methode == "verschneidung" else
                         "hoch" if a >= ANTEIL_HOCH and attribut in ("", n) else "mittel")
            zeilen.append({"von_ebene": von_ebene, "von_id": rid, "nach_ebene": nach_ebene, "nach_id": n,
                           "flaechenanteil": _anteil(a), "methode": methode, "konfidenz": konfidenz})
        zuordnung += zeilen
        if not zugeordnet:
            z["pruefstatus"] = "nicht_zugeordnet"
            gruende.insert(0, f"kein {ziel_wort} mit Flächenanteil ≥ {SPLITTER_ANTEIL}; außerhalb aller "
                              f"{ziel_plural}: {_anteil(aussen)}; Nummer nennt {ziel_wort} {nummer}")
            z["grund"] = "; ".join(gruende)
            audit.append(z)
            continue
        haupt, ziel = zugeordnet[0]
        z.update({"nach_id": ziel, "flaechenanteil": _anteil(haupt), "methode": zeilen[0]["methode"],
                  "konfidenz": zeilen[0]["konfidenz"]})
        anteil_je = dict((n, a) for a, n in teile)
        if ziel != nummer:
            gruende.append(f"Nummer nennt {ziel_wort} {nummer}, größter Flächenanteil in {ziel_wort} {ziel}; "
                           f"Anteil in {nummer}: " + (_anteil(anteil_je[nummer]) if nummer in anteil_je else "0"))
        if attribut and attribut != ziel:
            gruende.append(f"Attribut {attr_feld} nennt {ziel_wort} {attribut}")
        if haupt < ANTEIL_HOCH:
            gruende.append(f"größter Flächenanteil {_anteil(haupt)} unter {ANTEIL_HOCH}")
            if len(zugeordnet) > 1:
                gruende.append("weitere Ziele: " + ", ".join(f"{ziel_wort} {n} ({_anteil(a)})"
                                                             for a, n in zugeordnet[1:]))
            if aussen >= SPLITTER_ANTEIL:
                gruende.append(f"außerhalb aller {ziel_plural}: {_anteil(aussen)}")
        if rid not in werte_namen:
            gruende.append("keine Zeile im Blatt Daten (Geometrie ohne Werte)")
        abweichend = [g for g in gruende if not g.startswith("Geometrie der Quelle ungültig")]
        z["uebereinstimmung"] = "ja" if ziel == nummer and attribut in ("", ziel) else "nein"
        if abweichend:
            z["pruefstatus"] = "abweichung"
        else:
            z["pruefstatus"] = "ok"
            eltern[rid] = ziel
            gruende.insert(0, f"Verschneidung, Nummer{' und Attribut' if attribut else ''} nennen {ziel_wort} "
                              f"{ziel}; Flächenanteil {_anteil(haupt)} ≥ {ANTEIL_HOCH}")
        if splitter:
            gruende.append(f"{len(splitter)} Randsplitter unter {SPLITTER_ANTEIL} nicht zugeordnet: "
                           + ", ".join(f"{ziel_wort} {n} ({_anteil(a)})" for a, n in splitter))
        z["grund"] = "; ".join(gruende)
        audit.append(z)
    return zuordnung, audit, eltern


# --- Ausgabe ----------------------------------------------------------------------------------------------------------

def _feature(rid, name, ebene, eltern, geometrie, quelle):
    return {"type": "Feature",
            "properties": {"raum_id": rid, "name": name, "raumebene": ebene, "eltern_id": eltern, "quelle": quelle,
                           "lizenz": LIZENZ_TEXT},
            "geometry": geometrie}


def geojson_text(features, meta):
    """GeoJSON wie data/geo: kompakt, UTF-8, `meta` mit Quelle und Lizenz vor den Features."""
    return json.dumps({"type": "FeatureCollection", "meta": meta, "features": features}, ensure_ascii=False,
                      separators=(",", ":")) + "\n"


def statistik(audit, zuordnung, von_ebene):
    zeilen = [a for a in audit if a["von_ebene"] == von_ebene]
    haupt = sorted(float(a["flaechenanteil"]) for a in zeilen if a.get("flaechenanteil"))
    splitter = [float(a["splitter_max_anteil"]) for a in zeilen if a.get("splitter_max_anteil")]
    stufen = {"1.0000": sum(1 for h in haupt if h >= 0.99995),
              "0.9990-0.9999": sum(1 for h in haupt if 0.999 <= h < 0.99995),
              f"{ANTEIL_HOCH:.4f}-0.9989": sum(1 for h in haupt if ANTEIL_HOCH <= h < 0.999),
              f"unter {ANTEIL_HOCH:.4f}": sum(1 for h in haupt if h < ANTEIL_HOCH)}
    return {"einheiten": len(zeilen),
            "pruefstatus": {s: sum(1 for a in zeilen if a["pruefstatus"] == s)
                            for s in ("ok", "abweichung", "nicht_zugeordnet")},
            "zeilen_zuordnung": sum(1 for z in zuordnung if z["von_ebene"] == von_ebene),
            "groesster_anteil_verteilung": stufen,
            "kleinster_groesster_anteil": _anteil(haupt[0]) if haupt else "",
            "einheiten_mit_splitter": len(splitter),
            "groesster_splitter": _anteil(max(splitter)) if splitter else ""}


def raumabgleich(quartier_pfad, quartier_beleg, stadtteil_pfad, stadtbezirk_pfad, werte_namen):
    """Alles für Phase 2: {"geojson": {Ebene: Text}, "geojson_meta": {Ebene: meta}, "zuordnung": [...],
    "audit": [...], "meta": {...}}.

    werte_namen: {Ebene: {Nummer: Name}} der Einheiten mit Zeilen im Blatt Daten; quartier_beleg: Protokollzeile des
    Abrufs der Quartiersdatei (url, zeitstempel, pruefsumme)."""
    quartiere = Quartiere(quartier_pfad)
    teile, teile_meta = gebiete(stadtteil_pfad, "stadtteil")
    bezirke, bezirke_meta = gebiete(stadtbezirk_pfad, "stadtbezirk")
    zuordnung, audit, eltern = [], [], {}
    for von, nach in PAARE:
        quelle = quartiere.einheiten if von == "quartier" else teile
        ziele = teile if nach == "stadtteil" else bezirke
        z, a, e = abgleich(von, nach, quelle, ziele, werte_namen.get(von, {}))
        zuordnung += z
        audit += a
        eltern[von] = e
    geojson, geojson_meta = {}, {}
    for ebene, einheiten, meta, pfad in (("stadtbezirk", bezirke, bezirke_meta, stadtbezirk_pfad),
                                         ("stadtteil", teile, teile_meta, stadtteil_pfad)):
        titel = "Stadtbezirke Köln" if ebene == "stadtbezirk" else "Stadtteile Köln"
        quelle = f"{GEO_HERAUSGEBER}, {titel} (offenedaten-koeln.de)"
        features = [_feature(rid, einheiten[rid]["name"], ebene, eltern.get(ebene, {}).get(rid, ""),
                             einheiten[rid]["geometrie"], quelle) for rid in _sortiert(einheiten)]
        geojson_meta[ebene] = {
            "raumebene": ebene, "quelle": quelle, "quelle_url": meta.get("source", ""),
            "abgeleitet_aus": f"data/geo/{Path(pfad).name}", "sha256": pruefsumme(pfad),
            "lizenz": GEO_LIZENZ, "lizenz_url": GEO_LIZENZ_URL, "namensnennung": GEO_NAMENSNENNUNG,
            "crs": meta.get("crs", "WGS84 (EPSG 4326)"), "vereinfacht_m": meta.get("vereinfacht_m", ""),
            "geometrie": "unverändert aus data/geo (pipeline/geodaten.py)",
            "eltern_id": ("leer: oberste Ebene mit Geometrie (Gesamtstadt in werte.tsv als raum_id 0, ohne Geometrie)"
                          if ebene == "stadtbezirk" else
                          "Stadtbezirk, nur bei Prüfstatus ok in audit_raumabgleich.tsv, sonst leer")}
        geojson[ebene] = geojson_text(features, geojson_meta[ebene])
    quelle = f"{GEO_HERAUSGEBER}, {QUARTIERE_TITEL} (offenedaten-koeln.de)"
    features = []
    for rid in _sortiert(quartiere.einheiten):
        e = quartiere.einheiten[rid]
        if e["geom"] is None:
            continue
        features.append(_feature(rid, e["name"], "quartier", eltern["quartier"].get(rid, ""),
                                 mapping(geodaten._wgs84(e["geom"], TOLERANZ_M)), quelle))
    geojson_meta["quartier"] = {
        "raumebene": "quartier", "quelle": quelle, "quelle_url": quartier_beleg["url"],
        "datensatz_url": QUARTIERE_DATENSATZ_URL, "abgerufen": quartier_beleg["zeitstempel"],
        "sha256": quartier_beleg["pruefsumme"], "lizenz": GEO_LIZENZ, "lizenz_url": GEO_LIZENZ_URL,
        "namensnennung": GEO_NAMENSNENNUNG,
        "crs": f"WGS84 (EPSG 4326), umgerechnet aus {quartiere.crs_name} (laut .prj"
               + (f", EPSG {quartiere.crs_epsg})" if quartiere.crs_epsg else ")"),
        "vereinfacht_m": TOLERANZ_M, "koordinaten": "auf 1e-6 Grad gerundet",
        "eltern_id": "Stadtteil, nur bei Prüfstatus ok in audit_raumabgleich.tsv, sonst leer"}
    geojson["quartier"] = geojson_text(features, geojson_meta["quartier"])
    ids = {"quartier": (set(quartiere.einheiten), set(werte_namen.get("quartier", {}))),
           "stadtteil": (set(teile), set(werte_namen.get("stadtteil", {}))),
           "stadtbezirk": (set(bezirke), set(werte_namen.get("stadtbezirk", {})))}
    meta = {
        "ergebnis": {f"{von}→{nach}": statistik(audit, zuordnung, von) for von, nach in PAARE},
        "id_abgleich": {e: {"geometrie": len(g), "werte": len(w), "gemeinsam": len(g & w),
                            "nur_geometrie": _sortiert(g - w), "nur_werte": _sortiert(w - g)}
                        for e, (g, w) in ids.items()},
        "quartiere_datum_archiv": quartiere.datum.strftime("%d.%m.%Y") if quartiere.datum else "unbekannt",
        "quartiere_crs": quartiere.crs_name,
        "quartiere_ohne_geometrie": _sortiert(r for r, e in quartiere.einheiten.items() if e["geom"] is None),
    }
    return {"geojson": geojson, "geojson_meta": geojson_meta, "zuordnung": zuordnung, "audit": audit, "meta": meta}
