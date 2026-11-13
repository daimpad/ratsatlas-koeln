"""Raumabgleich der Strukturdaten Köln (Phase 2; Datenvertrag „Strukturdaten“ 1.1, Entscheidungen 10.11.2026).

Eingaben (ohne Netz; aufgerufen aus pipeline/strukturdaten.py, Schritt `strukturdaten`):
- Statistische Quartiere Köln (Stadt Köln; Datei auf offenedaten-koeln.de, Datensatzseite open.nrw, Datenlizenz
  Deutschland – Zero – Version 2.0, Namensnennung wie bei allen Kölner Geodaten des Projekts): ein Shapefile im
  ZIP-Archiv, geladen von `strukturdaten-abruf` (Schlüssel `quartiere`). Gelesen nur mit zipfile und pyshp, ohne
  Entpacken auf die Platte; das Koordinatenbezugssystem kommt aus der .prj-Datei (am 10.11.2026 ETRS89/UTM 32N,
  EPSG 25832).
- Stadtteile und Stadtbezirke aus data/geo/ (pipeline/geodaten.py: Shapefiles der Stadt, WGS84, mit
  geodaten.TOLERANZ_M vereinfacht, jede Fläche für sich, Koordinaten auf 1e-6 Grad gerundet; seit dem 13.11.2026
  danach als lückenlose Abdeckung bereinigt, die Stadtbezirke als Vereinigung ihrer Stadtteile, geodaten.abdeckung).
  Eine unvereinfachte Fassung liegt nicht im Repository; data/geo ist die beste verfügbare Geometrie. Wirkung: Die
  Grenzen weichen von der Quelle ab (für data/geo nicht gemessen; dasselbe Verfahren ergab bei den Quartieren am
  10.11.2026 bis 12,61 m, 37 von 570 Quartieren über 2 m; die Bereinigung verschob die Grenzen um höchstens 2,21 m),
  an den Rändern der Quartiere entstehen kleine Splitter (Anteile unter SPLITTER_ANTEIL); sie werden gemeldet, nicht
  zugeordnet. data/geo hat kein Abrufprotokoll; Abrufdatum und Stand stehen nur für die Fassungen mit den Prüfsummen in
  GEO_HERKUNFT und GEO_ABGELEITET.

Ausgaben (Rückgabe an strukturdaten.write, das die Dateien schreibt):
- raum/stadtbezirk.geojson, raum/stadtteil.geojson: Geometrie unverändert aus data/geo; raum/quartier.geojson: aus dem
  Shapefile, alle Quartiere gemeinsam als lückenlose Abdeckung vereinfacht und gerundet (`quartiersflaechen`,
  Entscheidung 10.11.2026 „lückenlose Vereinfachung“): Nachbarn haben an ihrer gemeinsamen Grenze dieselben
  Stützpunkte, ohne Lücken und Überlappungen. `abweichung` misst die Abweichung von der Quelle sowie Lücken und
  Überlappungen an der veröffentlichten Geometrie, Ergebnis in meta unter abweichung_von_der_quelle, die Prüfung der
  Abdeckung unter abdeckung. Die Flächen dienen nur der Anzeige; die Verschneidung rechnet mit den unvereinfachten
  Quartieren. Properties laut Vertrag: raum_id (Nummer der Quelle als Text), name, raumebene, eltern_id, quelle,
  lizenz. `eltern_id` steht nur, wenn Verschneidung, Nummer und Attribut dasselbe Ziel nennen (Prüfstatus ok); bei
  Stadtbezirken leer (oberste Ebene mit Geometrie; die Gesamtstadt steht in werte.tsv als raumebene gesamtstadt,
  raum_id 0, ohne Geometrie).
- zuordnung.tsv: Quartier → Stadtteil und Stadtteil → Stadtbezirk durch Verschneidung in EPSG 25832 (Quartiere
  unvereinfacht aus dem Shapefile, Stadtteile und Stadtbezirke aus data/geo zurückgerechnet); eine Zeile je Paar mit
  Flächenanteil ≥ SPLITTER_ANTEIL. `flaechenanteil` = Anteil der Fläche der Einheit, der im Ziel liegt (4 Stellen).
  `methode`: verschneidung_nummer (Ziel stimmt mit der Nummer überein: Quartier = erste drei Ziffern, Stadtteil =
  erste Ziffer) oder verschneidung (nur geometrisch). `konfidenz`: hoch (verschneidung_nummer, Anteil ≥ ANTEIL_HOCH,
  Attribut der Quelle widerspricht nicht), mittel (verschneidung_nummer sonst), niedrig (verschneidung). Die Schwellen
  gelten für den veröffentlichten, auf 4 Stellen gerundeten Anteil.
- audit_raumabgleich.tsv: eine Zeile je Einheit aus Geometrie oder Blatt Daten mit Hauptziel, Ziel laut Nummer und
  laut Attribut, Übereinstimmung, weiteren Zielen, Splittern, Anteil außerhalb aller Ziele und Prüfstatus ok,
  abweichung oder nicht_zugeordnet mit Grund. Einheiten ohne Geometrie, ohne Werte oder ohne Ziel werden gemeldet, nie
  stillschweigend zugeordnet. Weicht der Name im Blatt Daten (in einem Jahr) vom Namen der Geometriequelle ab, steht
  das als Hinweis in `grund`; der Prüfstatus ändert sich dadurch nicht.

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
import pyproj
import shapefile
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape

from . import config, geodaten

QUARTIERE_URL = "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/Statistisches_Quartier_0.zip"
QUARTIERE_DATENSATZ_URL = "https://open.nrw/dataset/statistische-quartiere-koln-k"
QUARTIERE_TITEL = "Statistische Quartiere Köln"
# Stand der Ressource laut open.nrw (Metadaten gelesen am 10.11.2026); nur zur Begründung des Datenstands und nur für
# die an diesem Tag geladene Datei (Prüfsumme sha256 → (Stand, gelesen am)). Für eine andere Datei, etwa nach einem
# späteren `strukturdaten-abruf`, gilt der Portalstand als nicht geprüft (portalstand()).
QUARTIERE_STAND_PORTAL = {
    "311eb81527c6e9ba626de149634d8224536c48dc80e316c8344588e26b3f8195": ("24.09.2026", "10.11.2026"),
}
GEO_HERAUSGEBER = "Stadt Köln"
GEO_LIZENZ = "Datenlizenz Deutschland – Zero – Version 2.0"
GEO_LIZENZ_URL = "https://www.govdata.de/dl-de/zero-2-0"
GEO_NAMENSNENNUNG = config.NAMENSNENNUNG
LIZENZ_TEXT = f"{GEO_LIZENZ} ({GEO_LIZENZ_URL}); {GEO_NAMENSNENNUNG}"
# data/geo (pipeline/geodaten.py) hat kein Abrufprotokoll. Belegt ist nur die Fassung, die mit Commit 3964836 am
# 04.11.2026 ins Repository kam (Prüfsumme der Datei unter data/geo → Dateiname): Die Geodaten wurden laut
# explore/BERICHT_phase1.md (Abschnitt 1) am 04.11.2026 geladen, Stand der Ressourcen laut Katalog 24.09.2026. Für
# eine andere Fassung gilt: nicht dokumentiert (kein geschätztes Datum).
GEO_HERKUNFT = {
    "2bcc2349d2399734003ae2af4871a6534168b0f2d3d15d7eb5c83c6f29805e0c": "stadtteile_koeln.geojson",
    "21c4447b13d00a7813c0401ff584cb0e26e446acd05d50832ae72ee6eb0bbcb8": "stadtbezirke_koeln.geojson",
}
# Am 13.11.2026 (Entscheidung „lückenlose Abdeckung“) ist data/geo ohne neuen Download aus dieser Fassung abgeleitet
# worden (pipeline/geodaten.abdeckung, Schritt `geo-abdeckung`): Abrufdatum und Stand der Quelle bleiben dieselben.
GEO_ABGELEITET = {
    "ba3c7ec9cb6b4ffdc3b60efb0a793d15244c3c8e4c0ce0d645774c5661154bbe": "stadtteile_koeln.geojson",
    "f43ddc18080abc4fb0c8d4260467ec043c6ddd073382c0a4daa0c751d12e86a7": "stadtbezirke_koeln.geojson",
}
GEO_ABGERUFEN = "2026-11-04"
GEO_BELEG = ("kein Abrufprotokoll im Repository; Geodaten laut explore/BERICHT_phase1.md (Abschnitt 1) am 04.11.2026 "
             "geladen, Stand der Ressource laut Katalog 24.09.2026; data/geo/{name} in dieser Fassung (sha256) seit "
             "Commit 3964836 vom 04.11.2026")
GEO_BELEG_ABGELEITET = ("kein Abrufprotokoll im Repository; Geodaten laut explore/BERICHT_phase1.md (Abschnitt 1) am "
                        "04.11.2026 geladen, Stand der Ressource laut Katalog 24.09.2026; data/geo/{name} in dieser "
                        "Fassung (sha256) am 13.11.2026 ohne neuen Download aus der Fassung von Commit 3964836 als "
                        "lückenlose Abdeckung abgeleitet (pipeline/geodaten.abdeckung)")
GEO_OHNE_BELEG = ("data/geo/{name} weicht von der Fassung vom 04.11.2026 ab (sha256); Abrufdatum und Stand der Quelle "
                  "nicht dokumentiert")

# Toleranz der Vereinfachung der Quartiersflächen: gleicher Zahlenwert wie data/geo, andere Bedeutung (Visvalingam-Whyatt:
# etwa die Wurzel der Fläche der entfernten Dreiecke in Metern; data/geo: Douglas-Peucker, Höchstabstand in Metern)
TOLERANZ_M = geodaten.TOLERANZ_M
GITTER = 1e-6                       # Rundung der veröffentlichten Koordinaten in Grad, wie data/geo
GITTERZELLE = "rund 7 × 11 cm"      # 1e-6 Grad Länge × Breite in Köln (50,83–51,09° N: 7,01–7,05 cm × 11,12 cm, GRS80)
GEOS_MINDESTENS = (3, 12, 0)        # coverage_simplify, coverage_is_valid und coverage_invalid_edges (shapely >= 2.1)
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
    "nach_id": "Ziel mit dem größten Flächenanteil, falls dieser (auf 4 Stellen gerundet) mindestens splitter_anteil "
               "(meta.json) beträgt",
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
    "splitter": "Anzahl der Ziele mit einem Anteil über 0 und (auf 4 Stellen gerundet) unter splitter_anteil (nicht "
                "zugeordnet)",
    "splitter_max_anteil": "größter dieser Anteile, 4 Nachkommastellen (0.0000 = unter 0.00005); leer ohne Splitter",
    "ausserhalb_anteil": "Anteil der Fläche außerhalb aller Ziele, 4 Nachkommastellen; leer ohne Geometrie",
    "in_geometrie": "ja, wenn die Einheit in der Geometriequelle steht",
    "in_werten": "ja, wenn die Einheit im Blatt Daten des Statistischen Datenkatalogs steht",
    "grund": "Begründung des Prüfstatus; dazu Hinweise ohne Einfluss auf den Prüfstatus (Geometrie repariert, Name im "
             "Blatt Daten abweichend vom Namen der Geometriequelle, mit Jahren)",
}

_NACH_UTM = Transformer.from_crs(4326, UTM, always_xy=True)
DENSIFY = 0.25   # Hausdorff-Abstand: jedes Segment für die Messung in Viertel geteilt (shapely.hausdorff_distance)


def _umrechnen(geom, transformer):
    return shapely.transform(geom, lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1])))


def _anteil(wert):
    return f"{wert:.4f}"


def _gerundet(wert):
    """Anteil so, wie er veröffentlicht wird (4 Stellen): Die Schwellen SPLITTER_ANTEIL und ANTEIL_HOCH gelten für
    diesen Wert, damit veröffentlichte Zahl und Einstufung einander nicht widersprechen."""
    return float(_anteil(wert))


def _jahre(jahre):
    """Jahre als Bereiche („2012–2014, 2016“) für Hinweise im Audit."""
    jahre, teile = sorted({int(j) for j in jahre}), []
    for j in jahre:
        if teile and teile[-1][1] == j - 1:
            teile[-1][1] = j
        else:
            teile.append([j, j])
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in teile)


def _name_vergleich(name):
    return " ".join(str(name or "").split())


def namen_abweichend(name, namen):
    """{Name: Jahre} der Namen im Blatt Daten, die (ohne Unterschiede im Leerraum) vom Namen `name` der Geometriequelle
    abweichen; namen: {Name: Jahre}."""
    return {n: j for n, j in namen.items() if _name_vergleich(n) != _name_vergleich(name)}


def portalstand(tabelle, summe, portal="open.nrw"):
    """Stand der Ressource laut Portal für die Datei mit der Prüfsumme `summe` (tabelle: sha256 → (Stand, gelesen am)),
    sonst der Hinweis, dass er für diese Datei nicht geprüft ist."""
    if summe in tabelle:
        stand, gelesen = tabelle[summe]
        return f"Ressource laut {portal} zuletzt aktualisiert am {stand} (Metadaten gelesen am {gelesen})"
    return f"Stand der Ressource auf {portal} für diese Datei nicht geprüft"


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
                e["geom"], e["repariert"] = _flaechenteile(shapely.make_valid(e["geom"])), True


def _flaechenteile(geom):
    """Nur die Flächenteile einer mit make_valid reparierten Geometrie. Aus einem Sporn ohne Breite (der Ring läuft auf
    derselben Linie hin und zurück) macht make_valid eine GeometryCollection aus Fläche und Linie; Linien und Punkte
    haben keine Fläche und entfallen (die Fläche bleibt gleich)."""
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    return shapely.union_all([g for g in shapely.get_parts(geom) if g.geom_type in ("Polygon", "MultiPolygon")])


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


def abgleich(von_ebene, nach_ebene, einheiten, ziele, werte_namen, namen_jahre=None):
    """Zuordnungszeilen, Auditzeilen und Eltern (nur Prüfstatus ok) für alle Einheiten aus Geometrie oder Werten.

    einheiten: {Nummer: {name, attribut, geom}} (Geometriequelle); ziele: {Nummer: {geom}}; werte_namen: {Nummer: Name}
    der Einheiten mit Zeilen im Blatt Daten (Name aus dem jüngsten Jahr); namen_jahre: {Nummer: {Name: [Jahre]}} aus
    allen Jahren des Blatts Daten (ohne Angabe: nur werte_namen). Ein abweichender Name ist ein Hinweis in grund, keine
    Abweichung im Prüfstatus. Die Schwellen gelten für den auf 4 Stellen gerundeten Anteil (_gerundet)."""
    namen_jahre = namen_jahre if namen_jahre is not None else {r: {n: []} for r, n in werte_namen.items()}
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
        hinweise = []   # ohne Einfluss auf den Prüfstatus
        if e is not None and rid in namen_jahre:
            anders = namen_abweichend(e["name"], namen_jahre[rid])
            if anders:
                hinweise.append("Name im Blatt Daten abweichend: " + ", ".join(
                    f"„{n}“" + (f" ({_jahre(j)})" if j else "") for n, j in sorted(anders.items()))
                    + f"; Geometriequelle: „{e['name']}“")
        if e is not None and e.get("repariert"):
            gruende.append("Geometrie der Quelle ungültig, mit make_valid repariert")
        if e is None or e["geom"] is None:
            z["pruefstatus"] = "nicht_zugeordnet"
            gruende.insert(0, "keine Geometrie in der Quelle" + ("" if e is None else " (leere Fläche)")
                           + ("; Werte im Blatt Daten vorhanden" if rid in werte_namen else ""))
            z["grund"] = "; ".join(gruende + hinweise)
            audit.append(z)
            continue
        teile, aussen = verschneiden(e["geom"], ziele, baum, ids, gesamt)
        zugeordnet = [(a, n) for a, n in teile if _gerundet(a) >= SPLITTER_ANTEIL]
        splitter = [(a, n) for a, n in teile if _gerundet(a) < SPLITTER_ANTEIL]
        attribut = z["nach_id_attribut"]
        z.update({"weitere_ziele": str(max(0, len(zugeordnet) - 1)), "splitter": str(len(splitter)),
                  "splitter_max_anteil": _anteil(max(a for a, _ in splitter)) if splitter else "",
                  "ausserhalb_anteil": _anteil(aussen)})
        zeilen = []
        for a, n in zugeordnet:
            methode = "verschneidung_nummer" if n == nummer else "verschneidung"
            konfidenz = ("niedrig" if methode == "verschneidung" else
                         "hoch" if _gerundet(a) >= ANTEIL_HOCH and attribut in ("", n) else "mittel")
            zeilen.append({"von_ebene": von_ebene, "von_id": rid, "nach_ebene": nach_ebene, "nach_id": n,
                           "flaechenanteil": _anteil(a), "methode": methode, "konfidenz": konfidenz})
        zuordnung += zeilen
        if not zugeordnet:
            z["pruefstatus"] = "nicht_zugeordnet"
            gruende.insert(0, f"kein {ziel_wort} mit Flächenanteil ≥ {SPLITTER_ANTEIL}; außerhalb aller "
                              f"{ziel_plural}: {_anteil(aussen)}; Nummer nennt {ziel_wort} {nummer}")
            z["grund"] = "; ".join(gruende + hinweise)
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
        if _gerundet(haupt) < ANTEIL_HOCH:
            gruende.append(f"größter Flächenanteil {_anteil(haupt)} unter {ANTEIL_HOCH}")
            if len(zugeordnet) > 1:
                gruende.append("weitere Ziele: " + ", ".join(f"{ziel_wort} {n} ({_anteil(a)})"
                                                             for a, n in zugeordnet[1:]))
            if _gerundet(aussen) >= SPLITTER_ANTEIL:
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
        z["grund"] = "; ".join(gruende + hinweise)
        audit.append(z)
    return zuordnung, audit, eltern


# --- Veröffentlichte Quartiersflächen: gemeinsam vereinfacht und gerundet --------------------------------------------

def abdeckung_pruefen(flaechen):
    """(gültig, {Index: Länge}) einer Liste von Flächen als Abdeckung (shapely.coverage_is_valid: keine Überlappungen,
    an gemeinsamen Grenzen dieselben Stützpunkte); Länge der Kanten, die shapely.coverage_invalid_edges je Fläche
    meldet, nur für Flächen mit solchen Kanten."""
    flaechen = np.asarray(flaechen, dtype=object)
    kanten = shapely.coverage_invalid_edges(flaechen)
    return bool(shapely.coverage_is_valid(flaechen)), {i: float(k.length) for i, k in enumerate(kanten)
                                                       if not k.is_empty}


def shapely_pruefen():
    """RuntimeError, wenn shapely oder GEOS die Funktionen für Abdeckungen nicht haben (shapely >= 2.1 mit GEOS >= 3.12,
    requirements.txt); sonst bräche quartiersflaechen erst mitten im Lauf mit AttributeError oder
    UnsupportedGEOSVersionError ab."""
    fehlen = [f for f in ("coverage_simplify", "coverage_is_valid", "coverage_invalid_edges", "orient_polygons")
              if not hasattr(shapely, f)]
    if fehlen or tuple(shapely.geos_version) < GEOS_MINDESTENS:
        raise RuntimeError(f"Quartiersflächen: shapely {shapely.__version__} mit GEOS {shapely.geos_version_string} "
                           f"reicht nicht, gebraucht shapely >= 2.1 mit GEOS >= "
                           f"{'.'.join(map(str, GEOS_MINDESTENS))} (requirements.txt)"
                           + (f"; fehlt: {', '.join(fehlen)}" if fehlen else ""))


def _linienkontakt(ids, geoms):
    """Paare (a, b), a vor b in ids, deren Ränder sich in einer Linie schneiden (gemeinsame Grenze; DE-9IM: Dimension
    des Schnitts der Ränder 1); Paare, die sich nur in Punkten berühren, zählen nicht."""
    baum = shapely.STRtree(geoms)
    return {(ids[i], ids[j]) for i, g in enumerate(geoms) for j in sorted(int(j) for j in baum.query(g))
            if j > i and shapely.relate(g, geoms[j])[4] == "1"}


def _grenzlaenge(a, b, nach_utm=None):
    """Länge der gemeinsamen Grenze zweier Flächen in Metern mit 3 Stellen; nach_utm: Umrechnung nach EPSG 25832."""
    linie = shapely.intersection(a.boundary, b.boundary)
    return float(f"{(_umrechnen(linie, nach_utm) if nach_utm else linie).length:.3f}")


def quartiersflaechen(quelle, toleranz=TOLERANZ_M):
    """({Nummer: Fläche in WGS84, auf GITTER gerundet}, Prüfung) aus {Nummer: Fläche in EPSG 25832}. Die Quartiere
    werden als Abdeckung gemeinsam behandelt, damit Nachbarn ohne Lücken und Überlappungen aneinandergrenzen:

    1. shapely.coverage_simplify über alle Quartiere zusammen in EPSG 25832 (Visvalingam-Whyatt mit `toleranz`, laut
       shapely etwa die Wurzel der Fläche der entfernten Dreiecke): Jede gemeinsame Grenze wird einmal vereinfacht,
       Punkte, an denen drei und mehr Flächen zusammentreffen, bleiben. Stützpunkte entfallen nur, keiner wird
       verschoben.
    2. Umrechnung nach WGS84: gleiche Punkte ergeben gleiche Koordinaten.
    3. Rundung auf GITTER für alle Grenzen zusammen: shapely.union_all mit grid_size rundet und verknotet sie mit
       Snap-Rounding (eine Kante, die durch die Gitterzelle eines Stützpunkts läuft, wird über diesen geführt), daraus
       bildet shapely.polygonize die Netzflächen. Jede Netzfläche gehört zu dem Quartier, mit dem sie vor der Rundung
       die größte Fläche teilt (bei Gleichstand die kleinere Nummer); liegt sie zu weniger als der Hälfte in
       Quartieren, gehört sie zu keinem: Sie ist eine Lücke, der Schritt bricht ab. Je Quartier setzt
       shapely.coverage_union_all seine Netzflächen ohne neue Punkte zusammen; Außenringe im Uhrzeigersinn wie data/geo.

    Die Rundung kann Knoten zusammenlegen, die weniger als eine Gitterzelle (GITTERZELLE) auseinanderliegen: Zwei
    Quartiere mit einer gemeinsamen Grenze von wenigen Zentimetern berühren sich danach nur noch in einem Punkt oder gar
    nicht, zwei andere können neu aneinandergrenzen. Gezählt werden die Paare mit gemeinsamer Grenze (als Linie) in
    Quelle und Ausgabe; die Paare, die nur in einer der beiden eine gemeinsame Grenze haben, stehen mit deren Länge in
    der Prüfung.

    Warum nicht jedes Quartier für sich: shapely.set_precision (geodaten._wgs84) rundet mit Snap-Rounding je Fläche und
    führt eine gemeinsame Kante nur in der Fläche über einen nahen Stützpunkt, die ihn hat; der Nachbar behält die
    gerade Kante (10.11.2026 nach coverage_simplify mit 2 m: 4 überlappende Nachbarpaare mit zusammen 1,26 m², 2 Lücken
    mit 0,94 m²). Nur die Koordinaten zu runden hält die gemeinsamen Grenzen gleich, macht aber Flächen ungültig, in
    denen eine Kante wenige Millimeter bis Zentimeter an einem Stützpunkt vorbeiläuft (am 10.11.2026 zwei Quartiere mit
    Selbstüberschneidung).

    Prüfung: RuntimeError ohne shapely >= 2.1 mit GEOS >= 3.12 (shapely_pruefen); die Quelle als Abdeckung
    (abdeckung_pruefen) und ihre Lücken (Löcher in der Vereinigung ihrer Flächen), gemeldet; ValueError, wenn eine
    veröffentlichte Fläche leer oder ungültig ist (shapely.is_valid), weniger oder mehr Teile hat als in der Quelle, die
    veröffentlichten Flächen keine gültige Abdeckung bilden (Überlappung) oder eine Netzfläche zu keinem Quartier
    gehört (Lücke; auch eine Lücke der Quelle, denn eine Fläche ohne Beleg wird keinem Quartier zugeordnet)."""
    shapely_pruefen()
    ids = _sortiert(quelle)
    geoms = np.array([quelle[r] for r in ids], dtype=object)
    flaechig = shapely.get_type_id(geoms)
    if not np.isin(flaechig, (3, 6)).all():   # Polygon, MultiPolygon
        raise ValueError("Quartiersflächen: keine Fläche: " + ", ".join(r for r, t in zip(ids, flaechig)
                                                                     if t not in (3, 6)))
    quelle_gueltig, quelle_kanten = abdeckung_pruefen(geoms)
    quelle_luecken = [p for p in shapely.get_parts(_loecher(geoms)) if p.area > 0]
    wgs = np.array([_umrechnen(g, geodaten.NACH_WGS84) for g in shapely.coverage_simplify(geoms, toleranz)],
                   dtype=object)
    kanten = shapely.union_all(shapely.boundary(wgs), grid_size=GITTER)
    netz = shapely.get_parts(shapely.polygonize(shapely.get_parts(kanten)))
    baum = shapely.STRtree(wgs)
    teile, ohne = {}, []
    for f in netz:
        anteile = [(shapely.intersection(f, wgs[j]).area, -j) for j in sorted(int(j) for j in baum.query(f))]
        if sum(a for a, _ in anteile) < f.area / 2:
            ohne.append(f)
            continue
        teile.setdefault(-max(anteile)[1], []).append(f)
    aus = {r: shapely.orient_polygons(shapely.coverage_union_all(teile[i]), exterior_cw=True) if i in teile
           else shapely.Polygon() for i, r in enumerate(ids)}
    fehler = []
    for r in ids:
        g, soll = aus[r], len(shapely.get_parts(quelle[r]))
        if g.is_empty or not g.is_valid:
            fehler.append(f"{r} " + ("leer" if g.is_empty else f"ungültig ({shapely.is_valid_reason(g)})"))
        elif len(shapely.get_parts(g)) != soll:
            fehler.append(f"{r} mit {len(shapely.get_parts(g))} statt {soll} Teilen")
    veroeffentlicht_gueltig, kanten_aus = abdeckung_pruefen([aus[r] for r in ids])
    if not veroeffentlicht_gueltig:
        fehler.append("keine gültige Abdeckung, ungültige Kanten bei " + ", ".join(ids[i] for i in kanten_aus))
    if ohne:
        fehler.append(f"{len(ohne)} Netzfläche(n) ohne Quartier (Lücken, zusammen "
                      f"{sum(_umrechnen(f, _NACH_UTM).area for f in ohne):.2f} m²; Lücken der Quelle: "
                      f"{len(quelle_luecken)}, zusammen {sum(p.area for p in quelle_luecken):.2f} m²)")
    if fehler:
        raise ValueError("Quartiersflächen nach Vereinfachung und Rundung: " + "; ".join(fehler))
    linie_quelle, linie_aus = _linienkontakt(ids, list(geoms)), _linienkontakt(ids, [aus[r] for r in ids])

    def paare(menge):
        return sorted(menge, key=lambda p: (int(p[0]), int(p[1])))
    return aus, {
        "verfahren": ("shapely.coverage_is_valid und coverage_invalid_edges (Überlappungen, an gemeinsamen Grenzen "
                      f"ungleiche Stützpunkte) an der Quelle in EPSG {UTM} vor der Vereinfachung und an den "
                      "veröffentlichten, gerundeten Flächen in WGS84; Lücken der Quelle = Löcher in der Vereinigung "
                      "ihrer Flächen (ohne Außenrand); je Fläche shapely.is_valid und die Zahl der Teile im Vergleich "
                      "zur Quelle; Netzflächen der gemeinsamen Rundung, die zu keinem Quartier gehören (Lücken). "
                      "Überlappungen und Lücken der veröffentlichten Flächen, ungültige oder leere Flächen und eine "
                      "andere Zahl von Teilen brechen den Schritt ab. nachbarpaare: Paare mit gemeinsamer Grenze als "
                      "Linie (DE-9IM, Schnitt der Ränder mit Dimension 1) in der Quelle und veröffentlicht; Paare, die "
                      "nur in einer der beiden eine gemeinsame Grenze haben, mit deren Länge (Meter mit 3 Stellen, in "
                      f"EPSG {UTM}, veröffentlicht zurückgerechnet); in der anderen berühren sie sich höchstens in "
                      "einem Punkt. software: Versionen, mit denen gerechnet wurde (byte-gleiche Flächen nur mit "
                      "denselben Versionen). Kantenlängen in Metern mit 2 Stellen, Flächen in ganzen Quadratmetern."),
        "quelle_gueltig": quelle_gueltig,
        "quelle_ungueltige_kanten_m": {ids[i]: float(f"{laenge:.2f}") for i, laenge in quelle_kanten.items()},
        "quelle_luecken_teile": len(quelle_luecken),
        "quelle_luecken_m2": int(round(sum(p.area for p in quelle_luecken))),
        "veroeffentlicht_gueltig": veroeffentlicht_gueltig,
        "flaechen_gueltig": len(ids),
        "teile_wie_quelle": len(ids),
        "netzflaechen": len(netz),
        "netzflaechen_ohne_quartier": len(ohne),
        "nachbarpaare_quelle": len(linie_quelle),
        "nachbarpaare_veroeffentlicht": len(linie_aus),
        "nachbarpaare_nur_quelle": {f"{a}/{b}": _grenzlaenge(quelle[a], quelle[b])
                                    for a, b in paare(linie_quelle - linie_aus)},
        "nachbarpaare_nur_veroeffentlicht": {f"{a}/{b}": _grenzlaenge(aus[a], aus[b], _NACH_UTM)
                                             for a, b in paare(linie_aus - linie_quelle)},
        "software": {"shapely": shapely.__version__, "geos": shapely.geos_version_string,
                     "pyproj": pyproj.__version__, "proj": pyproj.proj_version_str},
    }


# --- Abweichung der veröffentlichten Flächen -------------------------------------------------------------------------

def _loecher(geoms):
    """Löcher in der Vereinigung der Flächen (innere Ringe), als eine Geometrie."""
    teile = shapely.get_parts(shapely.union_all(geoms))
    return shapely.union_all([shapely.Polygon(r) for p in teile if p.geom_type == "Polygon" for r in p.interiors])


def abweichung(quelle, veroeffentlicht, toleranz=TOLERANZ_M):
    """Gemessene Abweichung der veröffentlichten Flächen (vereinfacht, gerundet) von der Quelle; beide {Nummer: Fläche}
    in EPSG 25832 (die veröffentlichte Fläche zurückgerechnet). Je Einheit der Hausdorff-Abstand (Segmente in Viertel
    geteilt, DENSIFY), dazu Überlappungen zwischen veröffentlichten Flächen und Lücken: alle Löcher in der Vereinigung
    der veröffentlichten Flächen (der Außenrand der Stadt zählt nicht; Lücken der Quelle selbst misst quartiersflaechen
    unter quelle_luecken_*). Nicht abgezogen werden die Löcher der Quelle: Unterschiedlich vereinfachte Ränder derselben
    Lücke ergäben sonst Splitter statt der Lücke. Abstände in Metern mit 2 Stellen (Median der gerundeten Abstände),
    Flächen in ganzen Quadratmetern; verglichen wird der gerundete Wert."""
    ids = _sortiert(set(quelle) & set(veroeffentlicht))
    abstand = {r: float(f"{shapely.hausdorff_distance(quelle[r], veroeffentlicht[r], densify=DENSIFY):.2f}")
               for r in ids}
    geoms = [veroeffentlicht[r] for r in ids]
    baum = shapely.STRtree(geoms)
    paare, ueberlappung = 0, 0.0
    for i, g in enumerate(geoms):
        for j in sorted(int(j) for j in baum.query(g)):
            if j <= i:
                continue
            a = shapely.intersection(g, geoms[j]).area
            if a > 0:
                paare, ueberlappung = paare + 1, ueberlappung + a
    luecken_teile = [p for p in shapely.get_parts(_loecher(geoms)) if p.area > 0]
    groesste = max(ids, key=lambda r: (abstand[r], -int(r))) if ids else ""
    ueber = sorted((r for r in ids if abstand[r] > toleranz), key=lambda r: (-abstand[r], int(r)))
    return {
        "verfahren": (f"Hausdorff-Abstand je Einheit zwischen der Fläche der Quelle und der veröffentlichten Fläche, "
                      f"beide in EPSG {UTM} (veröffentlichte Fläche zurückgerechnet), Segmente in Viertel geteilt; "
                      "Überlappungen zwischen veröffentlichten Flächen; Lücken = alle Löcher in der Vereinigung der "
                      "veröffentlichten Flächen (ohne Außenrand; Lücken der Quelle unter abdeckung). Meter mit 2 "
                      "Stellen (Median aus den gerundeten Abständen), Flächen in ganzen Quadratmetern."),
        "einheiten": len(ids),
        "abstand_max_m": abstand[groesste] if ids else None,
        "abstand_max_raum_id": groesste,
        "abstand_median_m": float(f"{np.median([abstand[r] for r in ids]):.2f}") if ids else None,
        "bis_toleranz": sum(1 for r in ids if abstand[r] <= toleranz),
        "ueber_toleranz": {r: abstand[r] for r in ueber},
        "ueberlappung_nachbarpaare": paare,
        "ueberlappung_m2": int(round(ueberlappung)),
        "luecken_teile": len(luecken_teile),
        "luecken_m2": int(round(sum(p.area for p in luecken_teile))),
    }


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


def raumabgleich(quartier_pfad, quartier_beleg, stadtteil_pfad, stadtbezirk_pfad, werte_namen, namen_jahre=None):
    """Alles für Phase 2: {"geojson": {Ebene: Text}, "geojson_meta": {Ebene: meta}, "zuordnung": [...],
    "audit": [...], "meta": {...}}.

    werte_namen: {Ebene: {Nummer: Name}} der Einheiten mit Zeilen im Blatt Daten (Name aus dem jüngsten Jahr);
    namen_jahre: {Ebene: {Nummer: {Name: [Jahre]}}} aus allen Jahren (ohne Angabe: nur werte_namen); quartier_beleg:
    Protokollzeile des Abrufs der Quartiersdatei (url, zeitstempel, pruefsumme)."""
    if namen_jahre is None:
        namen_jahre = {e: {r: {n: []} for r, n in w.items()} for e, w in werte_namen.items()}
    quartiere = Quartiere(quartier_pfad)
    teile, teile_meta = gebiete(stadtteil_pfad, "stadtteil")
    bezirke, bezirke_meta = gebiete(stadtbezirk_pfad, "stadtbezirk")
    zuordnung, audit, eltern = [], [], {}
    for von, nach in PAARE:
        quelle = quartiere.einheiten if von == "quartier" else teile
        ziele = teile if nach == "stadtteil" else bezirke
        z, a, e = abgleich(von, nach, quelle, ziele, werte_namen.get(von, {}), namen_jahre.get(von, {}))
        zuordnung += z
        audit += a
        eltern[von] = e
    geojson, geojson_meta = {}, {}
    for ebene, einheiten, meta, pfad in (("stadtbezirk", bezirke, bezirke_meta, stadtbezirk_pfad),
                                         ("stadtteil", teile, teile_meta, stadtteil_pfad)):
        titel = "Stadtbezirke Köln" if ebene == "stadtbezirk" else "Stadtteile Köln"
        quelle = f"{GEO_HERAUSGEBER}, {titel} (offenedaten-koeln.de)"
        summe, name = pruefsumme(pfad), Path(pfad).name
        belegt, abgeleitet = GEO_HERKUNFT.get(summe) == name, GEO_ABGELEITET.get(summe) == name
        features = [_feature(rid, einheiten[rid]["name"], ebene, eltern.get(ebene, {}).get(rid, ""),
                             einheiten[rid]["geometrie"], quelle) for rid in _sortiert(einheiten)]
        geojson_meta[ebene] = {
            "raumebene": ebene, "quelle": quelle, "quelle_url": meta.get("source", ""),
            "abgeleitet_aus": f"data/geo/{name}", "sha256": summe,
            "abgerufen": GEO_ABGERUFEN if belegt or abgeleitet else "nicht dokumentiert",
            "abgerufen_beleg": (GEO_BELEG if belegt else GEO_BELEG_ABGELEITET if abgeleitet else
                                GEO_OHNE_BELEG).format(name=name),
            "lizenz": GEO_LIZENZ, "lizenz_url": GEO_LIZENZ_URL, "namensnennung": GEO_NAMENSNENNUNG,
            "crs": meta.get("crs", "WGS84 (EPSG 4326)"), "vereinfacht_m": meta.get("vereinfacht_m", ""),
            "geometrie": "unverändert aus data/geo (pipeline/geodaten.py)",
            "eltern_id": ("leer: oberste Ebene mit Geometrie (Gesamtstadt in werte.tsv als raum_id 0, ohne Geometrie)"
                          if ebene == "stadtbezirk" else
                          "Stadtbezirk, nur bei Prüfstatus ok in audit_raumabgleich.tsv, sonst leer")}
        geojson[ebene] = geojson_text(features, geojson_meta[ebene])
    quelle = f"{GEO_HERAUSGEBER}, {QUARTIERE_TITEL} (offenedaten-koeln.de)"
    mit_flaeche = {r: e["geom"] for r, e in quartiere.einheiten.items() if e["geom"] is not None}
    flaechen, abdeckung = quartiersflaechen(mit_flaeche)
    features = [_feature(rid, quartiere.einheiten[rid]["name"], "quartier", eltern["quartier"].get(rid, ""),
                         mapping(flaechen[rid]), quelle) for rid in _sortiert(flaechen)]
    gemessen = abweichung(mit_flaeche, {r: _umrechnen(g, _NACH_UTM) for r, g in flaechen.items()})
    geojson_meta["quartier"] = {
        "raumebene": "quartier", "quelle": quelle, "quelle_url": quartier_beleg["url"],
        "datensatz_url": QUARTIERE_DATENSATZ_URL, "abgerufen": quartier_beleg["zeitstempel"],
        "abgerufen_beleg": "audit_abruf.tsv (Zeile mit derselben Prüfsumme)",
        "sha256": quartier_beleg["pruefsumme"], "lizenz": GEO_LIZENZ, "lizenz_url": GEO_LIZENZ_URL,
        "namensnennung": GEO_NAMENSNENNUNG,
        "crs": f"WGS84 (EPSG 4326), umgerechnet aus {quartiere.crs_name} (laut .prj"
               + (f", EPSG {quartiere.crs_epsg})" if quartiere.crs_epsg else ")"),
        "vereinfacht_m": TOLERANZ_M, "koordinaten": "auf 1e-6 Grad gerundet",
        "geometrie": (f"alle Quartiere gemeinsam als lückenlose Abdeckung in EPSG {UTM} vereinfacht "
                      "(shapely.coverage_simplify, Visvalingam-Whyatt mit Toleranz vereinfacht_m: jede gemeinsame "
                      "Grenze einmal, Punkte, an denen drei und mehr Quartiere zusammentreffen, bleiben), nach WGS84 "
                      "umgerechnet und auf 1e-6 Grad gerundet, alle Grenzen zusammen (Snap-Rounding; daraus die "
                      "Flächen neu gebildet). Benachbarte Quartiere haben an ihrer gemeinsamen Grenze dieselben "
                      "Stützpunkte, ohne Lücken und Überlappungen (geprüft unter abdeckung, gemessen unter "
                      "abweichung_von_der_quelle; eine Lücke oder Überlappung bricht den Schritt ab). vereinfacht_m "
                      "ist hier etwa die Wurzel der Fläche der entfernten Dreiecke, kein Höchstabstand wie bei "
                      "Stadtteilen und Stadtbezirken (Douglas-Peucker). Die Abweichung von der Quelle kann "
                      "vereinfacht_m übersteigen: Die Vereinfachung entfernt kurze, schmale Ausbuchtungen, die Rundung "
                      f"auf 1e-6 Grad (Gitterzelle {GITTERZELLE}) Sporne, die schmaler sind als eine Gitterzelle. Die "
                      "Rundung kann auch Knoten zusammenlegen, die weniger als eine Gitterzelle auseinanderliegen: "
                      "Quartiere mit einer gemeinsamen Grenze von wenigen Zentimetern berühren sich danach nur noch in "
                      "einem Punkt oder gar nicht, andere grenzen neu aneinander (abdeckung, nachbarpaare_nur_quelle "
                      "und nachbarpaare_nur_veroeffentlicht); Nachbarschaften nicht aus dieser Geometrie ableiten. Die "
                      "Flächen dienen nur der Anzeige: zuordnung.tsv und audit_raumabgleich.tsv rechnen mit den "
                      "unvereinfachten Flächen der Quelle, Werte werden nicht über Flächen verrechnet."),
        "abweichung_von_der_quelle": gemessen,
        "abdeckung": abdeckung,
        "eltern_id": "Stadtteil, nur bei Prüfstatus ok in audit_raumabgleich.tsv, sonst leer"}
    geojson["quartier"] = geojson_text(features, geojson_meta["quartier"])
    ids = {"quartier": (quartiere.einheiten, set(werte_namen.get("quartier", {}))),
           "stadtteil": (teile, set(werte_namen.get("stadtteil", {}))),
           "stadtbezirk": (bezirke, set(werte_namen.get("stadtbezirk", {})))}
    meta = {
        "ergebnis": {f"{von}→{nach}": statistik(audit, zuordnung, von) for von, nach in PAARE},
        "id_abgleich": {e: {"geometrie": len(g), "werte": len(w), "gemeinsam": len(set(g) & w),
                            "nur_geometrie": _sortiert(set(g) - w), "nur_werte": _sortiert(w - set(g)),
                            "namen_abweichend": _sortiert(r for r in set(g) & set(namen_jahre.get(e, {}))
                                                          if namen_abweichend(g[r]["name"], namen_jahre[e][r]))}
                        for e, (g, w) in ids.items()},
        "quartiere_datum_archiv": quartiere.datum.strftime("%d.%m.%Y") if quartiere.datum else "unbekannt",
        "quartiere_crs": quartiere.crs_name,
        "quartiere_ohne_geometrie": _sortiert(r for r, e in quartiere.einheiten.items() if e["geom"] is None),
    }
    return {"geojson": geojson, "geojson_meta": geojson_meta, "zuordnung": zuordnung, "audit": audit, "meta": meta}
