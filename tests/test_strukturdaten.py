"""Strukturdaten (pipeline/strukturdaten.py, pipeline/strukturdaten_raum.py): Normalisierung in den Datenvertrag
„Strukturdaten“ 1.1, Raumabgleich und Abruf.

Alle Eingaben sind erfunden: eine XLSX-Datei mit dem Aufbau des Statistischen Datenkatalogs Köln (Blätter Info, Daten,
Quellen, Katalog), ein Shapefile der Statistischen Quartiere im ZIP-Archiv (mit pyshp geschrieben, quadratische
Testflächen), Stadtteile und Stadtbezirke als GeoJSON wie data/geo und ein Wegweiser-Export im Format der echten CSV,
mit ausgedachten Zahlen. Der Abruf läuft nur gegen einen lokalen Testserver (127.0.0.1); Adressen der Stadt werden vor
dem Senden abgewiesen."""
import csv
import gzip
import hashlib
import json
import math
import re
import threading
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

openpyxl = pytest.importorskip("openpyxl")

shapefile = pytest.importorskip("shapefile")
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from pipeline import abruf, config, geodaten, strukturdaten, strukturdaten_raum  # noqa: E402

GEHEIM = "Werte zwischen 1 und 4 und zugehörige Anteilswerte werden nicht veröffentlicht (*). [Testdaten]"
SPALTEN = ["A0025A - Einwohner*innen, gesamt", "A0355A - Einwohner*innen, mit Hauptwohnsitz",
           "A0359A - Einwohner*innen, mit Nebenwohnsitz", "A0109A - Einwohner, männlich",
           "A0109P - Anteil männlicher Einwohner an allen Einwohnern",
           "A0022S - Durchschnittsalter der Gesamtbevölkerung",
           "A0008S - Einwohner*innenentwicklung (zum Vorjahr)", "Z9999A - Neue Spalte ohne Klassifikation"]
RAEUME = [("0 / Stadt Köln", "Gesamtstadt"), ("1 / Innenstadt", "Stadtbezirke"), ("2 / Rodenkirchen", "Stadtbezirke"),
          ("10001 / Testsozialraum", "Sozialräume"), ("101 / Teststadtteil A", "Stadtteile"),
          ("102 / Teststadtteil B", "Stadtteile"), ("201 / Teststadtteil C", "Stadtteile"),
          ("101010001 / Testquartier", "Statistische Quartiere")]

# Raumabgleich (Phase 2): Rechtecke in EPSG 25832, Meter relativ zu einem Punkt in Köln; (x0, y0, x1, y1)
X0, Y0 = 356000.0, 5645000.0
STADTTEILE = {"101": ("Teststadtteil A", "1", (0, 0, 1000, 1000)), "102": ("Teststadtteil B", "1", (1000, 0, 2000, 1000)),
              "201": ("Teststadtteil C", "2", (0, 1000, 2000, 2000))}
STADTBEZIRKE = {"1": ("Innenstadt", (0, 0, 2000, 1000)), "2": ("Rodenkirchen", (0, 1000, 2000, 2000))}
# Quartiere im Shapefile: Nummer → (Name, nr_stteil, Rechteck)
QUARTIERE = {
    "101010001": ("Testquartier", "101", (100, 100, 400, 400)),                  # ganz in 101
    "101010002": ("Testquartier Grenze", "101", (700, 100, 1100, 400)),          # 75 % in 101, 25 % in 102
    "101010003": ("Testquartier Rand", "101", (500, 600, 800, 1003)),            # 3 m Splitter in 201 (0,74 %)
    "102010001": ("Testquartier B", "102", (1300, 100, 1600, 400)),              # ganz in 102
    "201010001": ("Testquartier Nummer", "201", (1300, 500, 1600, 800)),         # Nummer 201, liegt in 102
    "102020001": ("Testquartier außerhalb", "102", (5000, 0, 5300, 300)),        # außerhalb aller Stadtteile
}
# weitere Quartierszeilen im Blatt Daten (nach den Zeilen aus RAEUME, Zeilen 18–27)
QUARTIERE_ZUSATZ = [f"{n} / {QUARTIERE[n][0]}" for n in QUARTIERE if n != "101010001"]
PRJ_25832 = ('PROJCS["ETRS_1989_UTM_Zone_32N",GEOGCS["GCS_ETRS_1989",DATUM["D_ETRS_1989",SPHEROID["GRS_1980",'
             '6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION['
             '"Transverse_Mercator"],PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],PARAMETER['
             '"Central_Meridian",9.0],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],UNIT['
             '"Meter",1.0]]')


def _ring(rechteck):
    """Rechteck (x0, y0, x1, y1) oder Liste von Punkten im Uhrzeigersinn als geschlossener Ring im Uhrzeigersinn
    (äußerer Ring im Shapefile), absolute Koordinaten in EPSG 25832."""
    if len(rechteck) == 4 and not isinstance(rechteck[0], tuple):
        x0, y0, x1, y1 = rechteck
        rechteck = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
    return [(X0 + x, Y0 + y) for x, y in [*rechteck, rechteck[0]]]


def quartiere_zip(pfad, quartiere=None, prj=PRJ_25832, umrechnen=None):
    """ZIP-Archiv wie Statistisches_Quartier_0.zip (Shapefile, .prj, .cpg) mit pyshp geschrieben; `umrechnen`:
    Umrechnung der Koordinaten aus EPSG 25832 in das Bezugssystem von `prj`."""
    quartiere = QUARTIERE if quartiere is None else quartiere
    ordner = pfad.parent / (pfad.name + "_shp")
    ordner.mkdir(parents=True, exist_ok=True)
    basis = ordner / "Statistisches_Quartier"
    w = shapefile.Writer(str(basis), shapeType=shapefile.POLYGON, encoding="utf-8")
    for name, groesse in (("nummer", 9), ("name", 100), ("nr_stteil", 254), ("stteil", 254)):
        w.field(name, "C", size=groesse)
    for nummer, (name, teil, rechteck) in quartiere.items():
        ring = _ring(rechteck)
        w.poly([[umrechnen(x, y) for x, y in ring] if umrechnen else ring])
        w.record(nummer, name, teil, STADTTEILE.get(teil, ("",))[0])
    w.close()
    with zipfile.ZipFile(pfad, "w") as z:
        for endung in (".shp", ".shx", ".dbf"):
            z.write(basis.with_suffix(endung), "Statistisches_Quartier" + endung)
        z.writestr("Statistisches_Quartier.prj", prj)
        z.writestr("Statistisches_Quartier.cpg", "UTF-8")


def geo_schreiben(ordner):
    """Stadtteile und Stadtbezirke wie data/geo (WGS84, Eigenschaften des Bonner Modells); liefert die Pfade."""
    nach = Transformer.from_crs(25832, 4326, always_xy=True)

    def flaeche(rechteck):
        return {"type": "Polygon", "coordinates": [[list(nach.transform(x, y)) for x, y in _ring(rechteck)[::-1]]]}
    ordner.mkdir(parents=True, exist_ok=True)
    meta = {"source": "https://example.invalid/Stadtteil_0.zip [Testdaten]", "license": "dl-de/zero 2.0 [Testdaten]",
            "crs": "WGS84 (EPSG 4326), umgerechnet aus EPSG 25832", "vereinfacht_m": 2.0}
    teile = [{"type": "Feature", "properties": {"ortsteil": int(n), "ortsteil_bez": name, "bezirk": int(b),
                                                "bezirk_bez": STADTBEZIRKE[b][0]}, "geometry": flaeche(r)}
             for n, (name, b, r) in STADTTEILE.items()]
    bezirke = [{"type": "Feature", "properties": {"bezirk": int(n), "bezirk_bez": name}, "geometry": flaeche(r)}
               for n, (name, r) in STADTBEZIRKE.items()]
    pfade = {"stadtteil": ordner / "stadtteile_koeln.geojson", "stadtbezirk": ordner / "stadtbezirke_koeln.geojson"}
    for ebene, feats in (("stadtteil", teile), ("stadtbezirk", bezirke)):
        pfade[ebene].write_text(json.dumps({"type": "FeatureCollection", "meta": meta, "features": feats},
                                           ensure_ascii=False), encoding="utf-8")
    return pfade

WW_LISTE = [
    ("bevoelkerung", "Bevölkerung", "Anzahl", "Statistische Ämter der Länder"),
    ("bevoelkerungsentwicklung-ueber-die-letzten-5-jahre", "Bevölkerungsentwicklung über die letzten 5 Jahre", "%",
     "Statistische Ämter der Länder, ZEFIR, eigene Berechnungen"),
    ("durchschnittsalter", "Durchschnittsalter", "Jahre", "Statistische Ämter der Länder, ZEFIR, eigene Berechnungen"),
    ("jugendquotient", "Jugendquotient", "unter 20-Jährige je 100 Pers. der AG 20-64", "Testdatenhalter"),
    ("altenquotient", "Altenquotient", "ab 65-Jährige je 100 Pers. der AG 20-64", "Testdatenhalter"),
    ("sgb-ii-quote", "SGB II-Quote", "%", "Testdatenhalter"),
    ("arbeitslose-an-den-svb", "Arbeitslose an den SvB", "%", "Testdatenhalter"),
    ("beschaeftigungsquote", "Beschäftigungsquote", "%", "Testdatenhalter"),
    ("auslaenderanteil", "Anteil Ausländer:innen", "%", "Testdatenhalter"),
    ("wohnflaeche-pro-person", "Wohnfläche pro Person", "m²", "Testdatenhalter"),
]


def _werte(raum, jahr):
    """Erfundene Werte einer Zeile; Gesamt = Haupt + Neben, Anteil = 100 × Männer / Gesamt (6 Stellen)."""
    nummer = int(raum.split(" / ")[0]) % 1000
    haupt, neben = 1000 + 37 * nummer + jahr % 10, 11 + nummer % 7
    gesamt = haupt + neben
    maenner = gesamt // 2 + nummer % 5
    return [gesamt, haupt, neben, maenner, round(100 * maenner / gesamt, 6), 40.5 + nummer / 1000, 3, 7]


def xlsx_bauen(pfad, aendern=None):
    mappe = openpyxl.Workbook()
    info = mappe.active
    info.title = "Info"
    for text in ("#VALUE!", "Statistischer Datenkatalog Köln [Testdaten]", "Auswertung erstellt am", "15.10.2026",
                 "Geheimhaltung", GEHEIM, "Kontakt", "test@example.invalid"):
        info.append([text])
    daten = mappe.create_sheet("Daten")
    daten.append(["Jahr", "Raum", "Raumebene", *SPALTEN])
    for jahr in (2025, 2024):
        for raum, ebene in RAEUME:
            daten.append([str(jahr), raum, ebene, *_werte(raum, jahr)])
    # Zeilen: 2–9 Jahr 2025, 10–17 Jahr 2024, je in der Reihenfolge von RAEUME (0, 1, 2, 10001, 101, 102, 201, Quartier)
    # Sonderfälle: geheim („*“), leer (leere Zeichenkette und fehlende Zelle), Gleitkommazahlen
    daten["G6"], daten["H6"] = "*", "*"                # 101 / 2025: Männer und Anteil geheim
    daten["I9"] = ""                                    # Quartier 2025 (nicht übernommen)
    daten["I16"] = ""                                   # 201 / 2024: leere Zeichenkette
    daten["F16"] = None                                 # 201 / 2024: fehlende Zelle
    daten["I2"] = 0.1234567890123456                    # Gesamtstadt 2025: 16 Stellen (openpyxl schreibt %.16g)
    daten["I3"] = 1e-05                                 # Bezirk 1 / 2025: ohne Exponent schreiben
    for jahr in (2025, 2024):                           # Zeilen 18–22 (2025) und 23–27 (2024): weitere Quartiere
        for raum in QUARTIERE_ZUSATZ:
            daten.append([str(jahr), raum, "Statistische Quartiere", *_werte(raum, jahr)])
    daten["G18"] = "*"                                  # 101010002 / 2025: Männer geheim
    if aendern:
        aendern(daten)
    quellen = mappe.create_sheet("Quellen")
    quellen.append(["Indikator", "Quellenangabe", "Anmerkung"])
    for s in SPALTEN:
        quellen.append([s, "Stadt Köln - Testamt (eigene Berechnung)",
                        "Testanmerkung zur Berechnung." if s.startswith("A0022S") else None])
    katalog = mappe.create_sheet("Katalog")
    katalog.append(["Indikator", None, None, None, "Formate", None, None, "Verfügbarkeit"])
    katalog.append(["THEMA", "UNTERTHEMA", "ID", "Name", "abs", "%", "andere", *range(2010, 2026)])
    for kennung, name, formate in (("A0025", "Einwohner*innen, gesamt", "X//"),
                                   ("A0355", "Einwohner*innen, mit Hauptwohnsitz", "X//"),
                                   ("A0359", "Einwohner*innen, mit Nebenwohnsitz", "X//"),
                                   ("A0109", "Einwohner, männlich", "XX/"), ("A0022", "Durchschnittsalter", "//X"),
                                   ("A0008", "Einwohner*innenentwicklung (zum Vorjahr)", "X/X"),
                                   ("A0547", "Bevölkerungsentwicklung (Veränderungsrate)", "//X")):
        katalog.append(["Bevölkerung und Haushalte", "Bevölkerung", kennung, name,
                        *[("X" if f == "X" else None) for f in formate.split("/")], *["3"] * 16])
    katalog.append(["Testthema", "Test", "Z9999", "Neue Spalte", "X", None, None, *["2"] * 16])
    mappe.save(pfad)


def export_text(zeilen=None):
    kopf = ";".join(["Indikatoren"] + [f'"{j}\n{k}"' for j in (2022, 2023) for k in ("Bonn", "Köln", "Wuppertal")])
    zeilen = zeilen or {
        "bevoelkerung": ["335.789", "1.087.353", "358.938", "336.001", "1.090.002", "359.003"],
        "bevoelkerungsentwicklung-ueber-die-letzten-5-jahre": ["k.A.", "k.A.", "k.A.", "1,5", "-0,3", "0,2"],
    }
    text = ("Bevölkerung, Bevölkerungsentwicklung über die letzten 5 Jahre und 8 weitere\n"
            "Bonn, kreisfreie Stadt, Köln, kreisfreie Stadt, ...\n\n" + kopf + "\n")
    for fu, name, einheit, _ in WW_LISTE:
        werte = zeilen.get(fu, ["10,0", "11,1", "12,2", "13,3", "14,4", "15,5"])
        text += f"{name} ({einheit});" + ";".join(werte) + "\n"
    return text + ('\n"k.A. = keine Angaben [Testdaten]"\n"Lizenz: Creative Commons Zero 1.0 (CC0 1.0)\n'
                   'https://creativecommons.org/publicdomain/zero/1.0/deed.de"\n')


def indikatorliste():
    liste = [{"id": i, "friendlyUrl": fu, "name": name, "unit": einheit, "source": quelle, "topics": ["Testthema"],
              "explanation": f"Erläuterung {name} [Testdaten]", "calculation": "Zähler / Nenner * 100", "hint": "",
              "years": [2022, 2023], "type": "COMMUNAL_DATA"} for i, (fu, name, einheit, quelle) in enumerate(WW_LISTE)]
    liste += [{"id": 90, "friendlyUrl": "einpersonen-haushalte", "name": "Einpersonen-Haushalte", "unit": "%",
               "source": "Nexiga GmbH, ZEFIR, eigene Berechnungen"},
              {"id": 91, "friendlyUrl": "haushalte-mit-kindern", "name": "Haushalte mit Kindern", "unit": "%",
               "source": "Nexiga GmbH, ZEFIR, eigene Berechnungen"},
              # gleicher Name und gleiche Einheit wie altenquotient (im Wegweiser gibt es solche Doppel)
              {"id": 92, "friendlyUrl": "altenquotient-prognose", "name": "Altenquotient",
               "unit": "ab 65-Jährige je 100 Pers. der AG 20-64", "source": "Test"}]
    return liste


REGIONEN = [{"friendlyUrl": "bonn", "name": "Bonn"}, {"friendlyUrl": "koeln", "name": "Köln"},
            {"friendlyUrl": "wuppertal", "name": "Wuppertal"}, {"friendlyUrl": "testhausen", "name": "Testhausen"}]


def dateien_schreiben(ordner, openapi="3.12.0"):
    """Eingaben mit den Standardnamen des Zwischenspeichers; liefert {Schlüssel: Pfad}."""
    ordner.mkdir(parents=True, exist_ok=True)
    p = {k: ordner / name for k, (name, _) in strukturdaten.DATEIEN.items()}
    xlsx_bauen(p["xlsx"])
    quartiere_zip(p["quartiere"])
    p["ww_export"].write_text(export_text(), encoding="utf-8")
    p["ww_indikatoren"].write_text(json.dumps(indikatorliste(), ensure_ascii=False), encoding="utf-8")
    p["ww_regionen"].write_text(json.dumps(REGIONEN, ensure_ascii=False), encoding="utf-8")
    p["ww_version"].write_text("2026-10-15T08:45:18.099083Z-test", encoding="utf-8")
    p["ww_openapi"].write_text(json.dumps({"openapi": "3.0.3", "info": {"version": openapi}}), encoding="utf-8")
    return p


def protokoll_schreiben(ordner, pfade, weglassen=()):
    zeilen = ["\t".join(strukturdaten.KOPF_PROTOKOLL)]
    for k, url, quelle in strukturdaten.ABRUFE:
        if k in weglassen:
            continue
        summe = hashlib.sha256(pfade[k].read_bytes()).hexdigest()
        zeilen.append("\t".join([quelle, url, "2026-11-10T10:45:58+01:00", "200", "", summe, ""]))
    (ordner / "audit_abruf.tsv").write_text("\n".join(zeilen) + "\n", encoding="utf-8")


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    dl, aus = tmp_path / "dl", tmp_path / "aus"
    monkeypatch.setenv("STRUKTURDATEN_DL", str(dl))
    monkeypatch.setenv("STRUKTURDATEN_AUS", str(aus))
    for _, variable in (*strukturdaten.DATEIEN.values(), strukturdaten.PROTOKOLL):
        monkeypatch.delenv(variable, raising=False)
    for variable in ("STRUKTURDATEN_ABRUF", "RATSATLAS_STADT_INFORMIERT", "STRUKTURDATEN_OPENAPI_BESTAETIGT"):
        monkeypatch.delenv(variable, raising=False)
    for ebene, pfad in geo_schreiben(tmp_path / "geo").items():
        monkeypatch.setenv(strukturdaten.GEO[ebene][1], str(pfad))
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    return dl, aus


def _lesen(pfad):
    with open(pfad, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def _normalisieren(dl, aus):
    pfade = dateien_schreiben(dl)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    return pfade, {n: _lesen(aus / n) for n in ("indikatoren.tsv", "werte.tsv", "gesamtstadt.tsv",
                                                "zurueckgestellt.tsv", "audit_abruf.tsv")}


# --- Hilfen -----------------------------------------------------------------------------------------------------------

def test_zahlen_unveraendert():
    assert strukturdaten.zahl(1100076) == "1100076"
    assert strukturdaten.zahl(48.861624) == "48.861624"
    assert strukturdaten.zahl(0.1 + 0.2) == "0.30000000000000004"   # kürzeste Schreibweise desselben Werts
    assert strukturdaten.zahl(1e-05) == "0.00001" and strukturdaten.zahl(-0.0) == "-0.0"
    with pytest.raises(TypeError):
        strukturdaten.zahl(True)
    assert strukturdaten.de_zahl("1.087.353") == "1087353"
    assert strukturdaten.de_zahl("-0,3") == "-0.3" and strukturdaten.de_zahl("5,0") == "5.0"
    for unlesbar in ("1.08", "k.A.", "", "1,2,3", "12.3456"):
        with pytest.raises(ValueError):
            strukturdaten.de_zahl(unlesbar)


def test_jahre_als_bereiche():
    assert strukturdaten.jahre_text(["2025", "2024", "2023"]) == "2023-2025"
    assert strukturdaten.jahre_text([2012, 2013, 2015, 2017, 2018]) == "2012-2013;2015;2017-2018"
    assert strukturdaten.jahre_text([2012, 2013, 2015], "–") == "2012–2013;2015"   # Fließtext im Metatext
    assert strukturdaten.jahre_text([]) == ""


def test_adressen_der_quellen():
    """Die Datei des Katalogs liegt auf einem Server der Stadt (Schutz wie pipeline/abruf.py), der Wegweiser nicht; je
    Quelldatei eine Anfrage und eine für die OpenAPI-Beschreibung."""
    assert abruf.stadt(strukturdaten.XLSX_URL) and abruf.stadt(strukturdaten_raum.QUARTIERE_URL)
    assert not any(abruf.stadt(u) for k, u, _ in strukturdaten.ABRUFE if k not in ("xlsx", "quartiere"))
    assert strukturdaten.MAX_ANFRAGEN == 7 == len(strukturdaten.DATEIEN)
    assert [k for k, *_ in strukturdaten.ABRUFE][-2:] == ["xlsx", "quartiere"]   # Dateien der Stadt zuletzt
    assert strukturdaten.ABRUFE[0][0] == "ww_openapi"   # Versionsprüfung vor allen Daten des Wegweisers
    assert strukturdaten.WW_EXPORT_URL == (
        "https://www.wegweiser-kommune.de/data-api/rest/export/bevoelkerung+bevoelkerungsentwicklung-ueber-die-"
        "letzten-5-jahre+durchschnittsalter+jugendquotient+altenquotient+sgb-ii-quote+arbeitslose-an-den-svb+"
        "beschaeftigungsquote+auslaenderanteil+wohnflaeche-pro-person+bonn+koeln+wuppertal+2006-2023+tabelle.csv"
        "?charset=UTF-8")


def test_klassifikation_aus_phase0():
    k = strukturdaten.klassifikation()
    assert len(k) == 211 and sum(z["typ_sicherheit"] == "unsicher" for z in k.values()) == 39
    assert sum(bool(z["zaehler_id"]) for z in k.values()) == 34
    assert all(z["beleg_zaehler_nenner"].startswith("Phase 0 (10.11.2026), numerisch geprüft")
               for z in k.values() if z["zaehler_id"])


# --- Normalisierung ---------------------------------------------------------------------------------------------------

def test_werte_status_und_quellobjekt(umgebung):
    dl, aus = umgebung
    _, t = _normalisieren(dl, aus)
    werte = {(w["raumebene"], w["raum_id"], w["indikator_id"], w["jahr"]): w for w in t["werte.tsv"]}
    # nur Gesamtstadt, Stadtbezirke, Stadtteile; keine Quartiere, keine Sozialräume
    assert {w["raumebene"] for w in t["werte.tsv"]} == {"gesamtstadt", "stadtbezirk", "stadtteil"}
    assert {w["raum_id"] for w in t["werte.tsv"]} == {"0", "1", "2", "101", "102", "201"}
    # 6 Räume × 2 Jahre × 6 übernommene Indikatoren, je Kombination genau eine Zeile
    assert len(t["werte.tsv"]) == len(werte) == 6 * 2 * 6
    w = werte[("gesamtstadt", "0", "koeln_A0025A", "2025")]
    assert (w["wert"], w["status"], w["quellobjekt"]) == (str(_werte("0 / Stadt Köln", 2025)[0]), "ok", "Daten!D2")
    assert werte[("gesamtstadt", "0", "koeln_A0022S", "2025")]["wert"] == "0.1234567890123456"
    assert werte[("stadtbezirk", "1", "koeln_A0022S", "2025")]["wert"] == "0.00001"
    g = werte[("stadtteil", "101", "koeln_A0109P", "2025")]
    assert (g["wert"], g["status"], g["quellobjekt"]) == ("", "geheim", "Daten!H6")
    assert werte[("stadtteil", "101", "koeln_A0109A", "2025")]["status"] == "geheim"
    f = werte[("stadtteil", "201", "koeln_A0022S", "2024")]
    assert (f["wert"], f["status"], f["quellobjekt"]) == ("", "fehlt", "Daten!I16")
    f = werte[("stadtteil", "201", "koeln_A0359A", "2024")]
    assert (f["wert"], f["status"], f["quellobjekt"]) == ("", "fehlt", "Daten!F16")
    from collections import Counter
    assert Counter(w["status"] for w in t["werte.tsv"]) == {"ok": 68, "geheim": 2, "fehlt": 2}
    assert werte[("stadtbezirk", "2", "koeln_A0109P", "2024")]["wert"] == repr(_werte("2 / Rodenkirchen", 2024)[4])
    # Reihenfolge: Ebene, Raum, Indikator, Jahr
    schluessel = [(w["raumebene"], int(w["raum_id"]), w["indikator_id"], w["jahr"]) for w in t["werte.tsv"]]
    ordnung = {"gesamtstadt": 0, "stadtbezirk": 1, "stadtteil": 2}
    assert schluessel == sorted(schluessel, key=lambda s: (ordnung[s[0]], *s[1:]))


def test_indikatoren_und_zurueckgestellte(umgebung):
    dl, aus = umgebung
    pfade, t = _normalisieren(dl, aus)
    ind = {i["indikator_id"]: i for i in t["indikatoren.tsv"]}
    assert list(t["indikatoren.tsv"][0]) == strukturdaten.KOPF_INDIKATOREN
    assert set(ind) == {f"koeln_{c}" for c in ("A0025A", "A0355A", "A0359A", "A0109A", "A0109P", "A0022S")} | {
        f"ww_{fu}" for fu, *_ in WW_LISTE}
    a = ind["koeln_A0109P"]
    assert (a["typ"], a["einheit"], a["zaehler_id"], a["nenner_id"]) == ("anteil", "%", "koeln_A0109A", "koeln_A0025A")
    assert "Haupt- und Nebenwohnsitz" in a["metatext"] and a["thema"] == "Bevölkerung und Haushalte"
    assert (a["raumebenen"], a["jahre"], a["abrufdatum"]) == ("gesamtstadt;stadtbezirk;stadtteil;quartier",
                                                               "2024-2025", "2026-11-10")
    assert a["geheimhaltung"] == GEHEIM and a["quell_url"] == strukturdaten.DATENSATZ_URL
    assert a["datenhalter"] == "Stadt Köln - Testamt (eigene Berechnung)"
    assert "Nebenwohnsitz (koeln_A0359A)" in ind["koeln_A0025A"]["metatext"]
    assert "Anmerkung der Quelle: Testanmerkung zur Berechnung." in ind["koeln_A0022S"]["metatext"]
    assert "Schätz" not in " ".join(i["metatext"] for i in ind.values())   # die Quelle sagt dazu nichts
    for i in ind.values():
        assert i["typ"] in strukturdaten.TYPEN and i["lizenz"] and i["lizenz_url"] and i["namensnennung"]
    zur = {z["indikator_id"]: z for z in t["zurueckgestellt.tsv"]}
    assert "Werte im Blatt Daten vorhanden" in zur["koeln_A0008S"]["grund"]
    assert "ohne Klassifikation" in zur["koeln_Z9999A"]["grund"]
    assert "ohne Werte (nur im Katalog)" in zur["koeln_A0547S"]["grund"]
    assert zur["koeln_A0547S"]["name"] == "Bevölkerungsentwicklung (Veränderungsrate)"
    unsicher = {k for k, z in strukturdaten.klassifikation().items() if z["typ_sicherheit"] == "unsicher"}
    assert unsicher <= set(zur) and len(unsicher) == 39
    assert {"ww_einpersonen-haushalte", "ww_haushalte-mit-kindern"} <= set(zur)
    assert not set(zur) & set(ind)
    assert not {w["indikator_id"] for w in t["werte.tsv"]} & set(zur)


def test_verhaeltnis_das_nicht_gilt_entfaellt(umgebung):
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)

    def falsch(daten):
        daten["H3"] = 12.5   # Anteil passt nicht zu Männer / Gesamt
    xlsx_bauen(pfade["xlsx"], falsch)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    a = next(i for i in _lesen(aus / "indikatoren.tsv") if i["indikator_id"] == "koeln_A0109P")
    assert (a["zaehler_id"], a["nenner_id"]) == ("", "") and "Zähler" not in a["metatext"]


def test_gesamtstadt_und_ka(umgebung):
    dl, aus = umgebung
    _, t = _normalisieren(dl, aus)
    g = t["gesamtstadt.tsv"]
    assert list(g[0]) == strukturdaten.KOPF_GESAMTSTADT
    zeile = {(z["kommune"], z["indikator_id"], z["jahr"]): z for z in g}
    k = zeile[("koeln", "ww_bevoelkerung", "2022")]
    assert (k["wegweiser_friendly_url"], k["wert"], k["abrufdatum"]) == ("bevoelkerung", "1087353", "2026-11-10")
    assert zeile[("koeln", "ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre", "2023")]["wert"] == "-0.3"
    assert zeile[("wuppertal", "ww_durchschnittsalter", "2023")]["wert"] == "15.5"
    # „k.A.“: keine Zeile (der Vertrag kennt in gesamtstadt.tsv keinen Status), im Metatext genannt
    assert ("bonn", "ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre", "2022") not in zeile
    assert len(g) == 10 * 6 - 3 and all(z["wert"] for z in g)
    assert {z["kommune"] for z in g} == {"bonn", "koeln", "wuppertal"}
    ind = {i["indikator_id"]: i for i in t["indikatoren.tsv"]}
    e = ind["ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"]
    assert "„k.A.“, nicht übernommen): 2022 (Bonn, Köln, Wuppertal)" in e["metatext"]
    assert (e["jahre"], e["raumebenen"], e["typ"]) == ("2023", "gesamtstadt", "quote")
    b = ind["ww_bevoelkerung"]
    assert (b["typ"], b["einheit"], b["datenhalter"], b["lizenz_url"]) == (
        "anzahl", "Anzahl", "Statistische Ämter der Länder", strukturdaten.WW_LIZENZ_URL)
    assert b["namensnennung"].startswith("Bertelsmann Stiftung, wegweiser-kommune.de")


def test_meta_und_audit(umgebung):
    dl, aus = umgebung
    pfade, t = _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert meta["vertrag_version"] == "1.1" and meta["datenstand"] == "2026-10-15"
    assert meta["abrufdatum"] == "2026-11-10" and meta["veroeffentlichen"] is True
    assert meta["lizenzstatus"] == "geklärt" and meta["einwohner_indikator"] == "koeln_A0355A"
    assert meta["raumebenen"] == ["gesamtstadt", "stadtbezirk", "stadtteil", "quartier"]
    summen = {q["kennung"]: q for q in meta["quellen"]}
    assert summen["statistischer-datenkatalog-koeln"]["sha256"] == hashlib.sha256(
        pfade["xlsx"].read_bytes()).hexdigest()
    assert summen["statistischer-datenkatalog-koeln"]["lizenz_url"] == "https://www.govdata.de/dl-de/by-2-0"
    assert summen["wegweiser-openapi"]["openapi_version"] == "3.12.0"
    assert all(q["url"] and q["lizenz"] and q["namensnennung"] and len(q["sha256"]) == 64 for q in meta["quellen"])
    audit = t["audit_abruf.tsv"]
    assert list(audit[0]) == strukturdaten.KOPF_AUDIT and len(audit) == 7
    text = (aus / "audit_abruf.tsv").read_text(encoding="utf-8")
    assert str(dl) not in text and "/tmp" not in text   # ohne lokale Pfade
    zeilen = {a["url"]: a for a in audit}
    assert zeilen[strukturdaten.XLSX_URL]["zeilen"] == str(2 * (len(RAEUME) + len(QUARTIERE_ZUSATZ)))
    assert zeilen[strukturdaten_raum.QUARTIERE_URL]["zeilen"] == str(len(QUARTIERE))
    assert zeilen[strukturdaten.WW_EXPORT_URL]["zeilen"] == "10"
    assert "info.version 3.12.0" in {a["hinweis"] for a in audit}


def _dateien(aus):
    return {p.relative_to(aus).as_posix(): p.read_bytes() for p in sorted(aus.rglob("*")) if p.is_file()}


def test_ausgabe_deterministisch(umgebung):
    dl, aus = umgebung
    _normalisieren(dl, aus)
    erst = _dateien(aus)
    strukturdaten.write()
    assert _dateien(aus) == erst
    assert set(erst) == {"indikatoren.tsv", "werte.tsv", "werte_quartier.tsv.gz", "raum/stadtbezirk.geojson",
                         "raum/stadtteil.geojson", "raum/quartier.geojson", "zuordnung.tsv", "gesamtstadt.tsv",
                         "zurueckgestellt.tsv", "audit_abruf.tsv", "audit_raumabgleich.tsv", "meta.json"}
    assert {d["datei"] for d in json.loads(erst["meta.json"])["dateien"]} == set(erst)


def test_eingabe_ohne_protokoll_abgelehnt(umgebung):
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    protokoll_schreiben(dl, pfade, weglassen={"ww_export"})
    with pytest.raises(ValueError, match="nicht im Abrufprotokoll"):
        strukturdaten.write()
    assert not (aus / "werte.tsv").exists()


def test_protokoll_der_exploration_lesbar(umgebung, monkeypatch):
    """Das Protokoll aus Phase 0 hat die Spalten zeit, status, sha256 (und pfad); die Ausgabe enthält keine Pfade."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    zeilen = ["quelle\turl\tzeit\tstatus\tbytes\tsha256\tpfad"]
    for k, url, quelle in strukturdaten.ABRUFE:
        zeilen.append("\t".join([quelle, url, "2026-11-10T10:46:28+01:00", "200", "1",
                                 hashlib.sha256(pfade[k].read_bytes()).hexdigest(), str(pfade[k])]))
    (dl / "phase0.tsv").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    monkeypatch.setenv("STRUKTURDATEN_PROTOKOLL", str(dl / "phase0.tsv"))
    strukturdaten.write()
    audit = _lesen(aus / "audit_abruf.tsv")
    assert {a["zeitstempel"] for a in audit} == {"2026-11-10T10:46:28+01:00"} and len(audit) == 7
    assert "pfad" not in audit[0] and str(dl) not in (aus / "audit_abruf.tsv").read_text(encoding="utf-8")


def test_unerwarteter_wert_bricht_ab(umgebung):
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    xlsx_bauen(pfade["xlsx"], lambda d: d.__setitem__("D4", "12,5"))
    protokoll_schreiben(dl, pfade)
    with pytest.raises(ValueError, match=r"Daten!D4"):
        strukturdaten.write()


# --- Abruf (nur lokaler Testserver) -----------------------------------------------------------------------------------

PFADE = {"ww_openapi": "/openapi", "ww_version": "/version", "ww_indikatoren": "/indikatoren",
         "ww_regionen": "/regionen", "ww_export": "/export.csv", "xlsx": "/katalog.xlsx", "quartiere": "/quartiere.zip"}


@pytest.fixture
def server(tmp_path, umgebung, monkeypatch):
    """Lokaler Server mit den erfundenen Dateien; `status` je Pfad überschreibbar, `anfragen` = (Pfad, User-Agent)."""
    inhalt = {PFADE[k]: p.read_bytes() for k, p in dateien_schreiben(tmp_path / "quelle").items()}
    zustand = {"anfragen": [], "status": {}, "inhalt": inhalt}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            zustand["anfragen"].append((self.path, self.headers.get("User-Agent")))
            status = zustand["status"].get(self.path, 200)
            if status != 200:
                self.send_response(status)
                if 300 <= status < 400:
                    self.send_header("Location", "/anderswo")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            daten = zustand["inhalt"][self.path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    basis = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(strukturdaten, "ABRUFE", [(k, basis + PFADE[k], q) for k, _, q in strukturdaten.ABRUFE])
    zustand["basis"] = basis
    yield zustand
    srv.shutdown()
    srv.server_close()


def _protokoll(dl):
    return _lesen(dl / "audit_abruf.tsv")


def test_abruf_vollstaendig_und_danach_normalisierbar(server, umgebung):
    dl, aus = umgebung
    lauf = strukturdaten.abruf_lauf()
    assert lauf.anfragen == 7 == len(server["anfragen"])
    assert [p for p, _ in server["anfragen"]] == [PFADE[k] for k, *_ in strukturdaten.ABRUFE]
    assert {ua for _, ua in server["anfragen"]} == {config.USER_AGENT}
    zeilen = _protokoll(dl)
    assert [z["http_status"] for z in zeilen] == ["200"] * 7 and list(zeilen[0]) == strukturdaten.KOPF_PROTOKOLL
    for k, (name, _) in strukturdaten.DATEIEN.items():
        inhalt = server["inhalt"][PFADE[k]]
        assert (dl / name).read_bytes() == inhalt
        assert next(z for z in zeilen if z["url"].endswith(PFADE[k]))["pruefsumme"] == hashlib.sha256(
            inhalt).hexdigest()
    assert next(z for z in zeilen if z["url"].endswith("/katalog.xlsx"))["zeilen"] == str(
        2 * (len(RAEUME) + len(QUARTIERE_ZUSATZ)))
    assert next(z for z in zeilen if z["url"].endswith("/quartiere.zip"))["zeilen"] == str(len(QUARTIERE))
    strukturdaten.write()   # die geladenen Dateien stehen mit Prüfsumme im Protokoll
    assert (aus / "werte.tsv").exists()


def test_obergrenze_der_anfragen(server, umgebung, monkeypatch):
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "MAX_ANFRAGEN", 3)
    with pytest.raises(SystemExit, match="obergrenze"):
        strukturdaten.abruf_lauf()
    assert len(server["anfragen"]) == 3
    status = [z["http_status"] for z in _protokoll(dl)]
    # danach die drei geladenen Wegweiser-Dateien als verworfen (nur gemeinsam mit allen fünf übernommen)
    assert status == ["200"] * 3 + ["nicht gesendet (obergrenze)"] + [strukturdaten.VERWORFEN] * 3
    assert not any((dl / name).exists() for name, _ in strukturdaten.DATEIEN.values())


def test_keine_wiederholung_nach_503(server, umgebung):
    dl, _ = umgebung
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "wegweiser_export.csv").write_text("vorher", encoding="utf-8")
    server["status"]["/export.csv"] = 503
    with pytest.raises(SystemExit, match="HTTP 503"):
        strukturdaten.abruf_lauf()
    pfade = [p for p, _ in server["anfragen"]]
    assert pfade.count("/export.csv") == 1 and "/katalog.xlsx" not in pfade   # keine Wiederholung, Lauf beendet
    assert (dl / "wegweiser_export.csv").read_text(encoding="utf-8") == "vorher"   # vorige Datei bleibt
    assert [z["http_status"] for z in _protokoll(dl)][4:] == ["503"] + [strukturdaten.VERWORFEN] * 4
    assert not (dl / "wegweiser_version.txt").exists()   # Wegweiser-Dateien nur gemeinsam übernommen


def test_weiterleitung_nicht_verfolgt(server, umgebung):
    dl, _ = umgebung
    server["status"]["/openapi"] = 302
    with pytest.raises(SystemExit, match="weiterleitung"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]


def test_versionswechsel_bricht_ab(server, umgebung, monkeypatch):
    dl, aus = umgebung
    aus.mkdir(parents=True)
    (aus / "meta.json").write_text(json.dumps({"quellen": [{"openapi_version": "3.11.0"}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="info.version der Wegweiser-OpenAPI ist 3.12.0, zuletzt 3.11.0"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]   # keine weitere Anfrage
    assert (dl / "wegweiser_openapi.neu.json").exists() and not (dl / "wegweiser_openapi.json").exists()
    assert "zuletzt 3.11.0" in _protokoll(dl)[-1]["hinweis"]
    # nach Prüfung bestätigt: Lauf geht weiter
    monkeypatch.setenv("STRUKTURDATEN_OPENAPI_BESTAETIGT", "3.12.0")
    assert strukturdaten.abruf_lauf().anfragen == 7


class _KeinNetz:
    def open(self, *a, **k):
        raise AssertionError("keine Anfrage erwartet")


def test_stadt_und_freigabe_ohne_anfrage(server, umgebung, monkeypatch):
    """Die echte Adresse der Stadt wird ohne RATSATLAS_STADT_INFORMIERT und außerhalb des Zeitfensters nicht gesendet;
    Wegweiser-Adressen (nicht lokal) nicht ohne STRUKTURDATEN_ABRUF. Kein Versuch einer Verbindung."""
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "_OEFFNER", _KeinNetz())
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("xlsx", strukturdaten.XLSX_URL, "offenedaten-koeln")])
    monkeypatch.setenv("STRUKTURDATEN_ABRUF", "ja")
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    strukturdaten.abruf_lauf()
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc))   # 12 Uhr in Köln
    strukturdaten.abruf_lauf()
    monkeypatch.delenv("STRUKTURDATEN_ABRUF")
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("ww_openapi", strukturdaten.WW + "/openapi?format=JSON",
                                                   "wegweiser-kommune")])
    strukturdaten.abruf_lauf()
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status[0].startswith("nicht gesendet (gesperrt: Server der Stadt Köln")
    assert status[1].startswith("nicht gesendet (außerhalb des Zeitfensters 23-1 Uhr")
    assert status[2] == "nicht gesendet (ohne Freigabe (STRUKTURDATEN_ABRUF=ja))"
    assert not server["anfragen"]


def test_stadtschutz_mit_lokalem_server(server, umgebung, monkeypatch):
    """Der lokale Server gilt als Server der Stadt: gesendet nur mit RATSATLAS_STADT_INFORMIERT=ja im Zeitfenster."""
    dl, _ = umgebung
    monkeypatch.setattr(abruf, "STADT_DOMAINS", ("127.0.0.1",))
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setattr(config, "KONTAKT", "test@example.invalid")   # Pflicht für Server der Stadt
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("xlsx", server["basis"] + "/katalog.xlsx", "offenedaten-koeln")])
    assert abruf.stadt(server["basis"] + "/katalog.xlsx")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc))   # 23:30 in Köln
    strukturdaten.abruf_lauf()
    assert not server["anfragen"]
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))
    strukturdaten.abruf_lauf()
    assert not server["anfragen"]
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc))
    assert strukturdaten.abruf_lauf().anfragen == 1 and len(server["anfragen"]) == 1
    assert [z["http_status"][:14] for z in _protokoll(dl)] == ["nicht gesendet"] * 2 + ["200"]


# --- Prüfung r1 (10.11.2026): Kontakt, Abstand, Zeitfenster, Version, Größe, unlesbare Antwort, gemischter Stand -----

KONTAKT = "test@example.invalid"


def _als_stadt(server, monkeypatch, abrufe, kontakt=KONTAKT):
    """Der lokale Server gilt als Server der Stadt (Freigabe gesetzt, 23:30 Uhr in Köln, Zeitfenster 23–1 Uhr);
    `abrufe`: Schlüssel, deren Pfade der Lauf lädt. `kontakt` leer: User-Agent ohne Kontakt."""
    monkeypatch.setattr(abruf, "STADT_DOMAINS", ("127.0.0.1",))
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    monkeypatch.setattr(config, "KONTAKT", kontakt)
    monkeypatch.setattr(config, "USER_AGENT", "ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln"
                        + (f"; {kontakt}" if kontakt else "") + ")")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    uhr = {"jetzt": datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc)}   # 23:30 in Köln
    monkeypatch.setattr(abruf, "uhr", lambda: uhr["jetzt"])
    quelle = dict((k, q) for k, _, q in strukturdaten.ABRUFE)
    monkeypatch.setattr(strukturdaten, "ABRUFE", [(k, server["basis"] + PFADE[k], quelle[k]) for k in abrufe])
    return uhr


def test_ohne_kontakt_keine_anfrage(server, umgebung, monkeypatch):
    """Ohne RATSATLAS_KONTAKT geht keine Anfrage an einen Server der Stadt (CLAUDE.md 5.1, wie sessionnet): laut als
    Einstellungsfehler (ValueError, Ausstieg 2), nicht gezählt, im Protokoll vermerkt. Mit Kontakt steht er im
    User-Agent."""
    dl, _ = umgebung
    _als_stadt(server, monkeypatch, ["xlsx"], kontakt="")
    with pytest.raises(ValueError, match="RATSATLAS_KONTAKT fehlt"):
        strukturdaten.abruf_lauf()
    with pytest.raises(SystemExit) as aus:
        strukturdaten.abruf_schritt()
    assert aus.value.code == 2 and not server["anfragen"]
    assert [z["http_status"] for z in _protokoll(dl)] == ["nicht gesendet (einstellung)"] * 2
    _als_stadt(server, monkeypatch, ["xlsx"])
    assert strukturdaten.abruf_lauf().anfragen == 1
    assert server["anfragen"] == [("/katalog.xlsx", f"ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; "
                                                     f"{KONTAKT})")]


def test_ohne_kontakt_auch_nicht_an_den_wegweiser(umgebung, monkeypatch):
    """Auch nicht lokale Adressen außerhalb der Stadt (Wegweiser) nur mit Kontakt; kein Versuch einer Verbindung."""
    monkeypatch.setattr(strukturdaten, "_OEFFNER", _KeinNetz())
    monkeypatch.setattr(config, "KONTAKT", "")
    monkeypatch.setenv("STRUKTURDATEN_ABRUF", "ja")
    with pytest.raises(ValueError, match="RATSATLAS_KONTAKT fehlt"):
        strukturdaten.abruf_lauf()
    assert [z["http_status"] for z in _protokoll(umgebung[0])] == ["nicht gesendet (einstellung)"]


def test_mindestabstand_zwischen_anfragen(server, umgebung, monkeypatch):
    """Zwischen zwei Anfragen an die Stadt liegen mindestens abruf.MINDESTABSTAND Sekunden, auch mit
    RATSATLAS_ABSTAND=0 (time.sleep protokolliert statt gewartet)."""
    _als_stadt(server, monkeypatch, ["ww_openapi", "ww_version"])
    pausen = []
    monkeypatch.setattr(strukturdaten.time, "sleep", pausen.append)
    assert strukturdaten.abruf_lauf().anfragen == 2 and len(server["anfragen"]) == 2
    assert len(pausen) == 1 and abruf.MINDESTABSTAND - 0.5 < pausen[0] <= abruf.MINDESTABSTAND


def test_zeitfenster_endet_beim_warten(server, umgebung, monkeypatch):
    """Endet das Zeitfenster während des Wartens auf den Abstand, wird die Anfrage nicht gesendet (Prüfung unmittelbar
    vor dem Senden)."""
    dl, _ = umgebung
    uhr = _als_stadt(server, monkeypatch, ["ww_openapi", "ww_version"])

    def warten(sekunden):
        uhr["jetzt"] = datetime(2026, 11, 11, 0, 0, 1, tzinfo=timezone.utc)   # 01:00:01 in Köln
    monkeypatch.setattr(strukturdaten.time, "sleep", warten)
    assert strukturdaten.abruf_lauf().anfragen == 1
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]
    assert _protokoll(dl)[1]["http_status"].startswith("nicht gesendet (außerhalb des Zeitfensters 23-1 Uhr")


def test_wegweiser_nur_nach_versionspruefung(server, umgebung, monkeypatch):
    """Ohne geprüfte info.version keine Anfrage an den Wegweiser; die Datei der Stadt (hier lokal) bleibt unberührt."""
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "ABRUFE", [a for a in strukturdaten.ABRUFE if a[0] != "ww_openapi"])
    assert strukturdaten.abruf_lauf().anfragen == 2
    assert [p for p, _ in server["anfragen"]] == ["/katalog.xlsx", "/quartiere.zip"]
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status == ["nicht gesendet (info.version der Wegweiser-OpenAPI nicht geprüft)"] * 4 + ["200", "200"]


def test_groessenobergrenze(server, umgebung, monkeypatch):
    dl, _ = umgebung
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "wegweiser_openapi.json").write_text("vorher", encoding="utf-8")
    monkeypatch.setattr(strukturdaten, "MAX_BYTES", 10)
    with pytest.raises(SystemExit, match=r"abgebrochen \(unlesbar\).*größer als 10 Bytes"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]
    assert (dl / "wegweiser_openapi.json").read_text(encoding="utf-8") == "vorher"
    assert not list(dl.rglob("*.tmp")) and _protokoll(dl)[-1]["http_status"] == "abbruch (unlesbar)"


@pytest.mark.parametrize("schluessel", ["ww_export", "xlsx", "quartiere"])
def test_unlesbare_antwort_vorige_datei_bleibt(server, umgebung, monkeypatch, schluessel):
    """Eine Webseite statt der Daten: Lauf endet (unlesbar), die vorige Datei bleibt, keine weitere Anfrage."""
    dl, _ = umgebung
    dl.mkdir(parents=True, exist_ok=True)
    name, pfad = strukturdaten.DATEIEN[schluessel][0], PFADE[schluessel]
    (dl / name).write_text("vorher", encoding="utf-8")
    server["inhalt"][pfad] = b"<!DOCTYPE html><html><body>Wartung</body></html>"
    if schluessel in ("xlsx", "quartiere"):
        monkeypatch.setattr(strukturdaten, "ABRUFE", [a for a in strukturdaten.ABRUFE if a[0] == schluessel])
    with pytest.raises(SystemExit, match=r"abgebrochen \(unlesbar\)"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]][-1] == pfad
    assert (dl / name).read_text(encoding="utf-8") == "vorher" and not list(dl.rglob("*.tmp"))
    zeilen = [z for z in _protokoll(dl) if z["url"].endswith(pfad)]
    assert zeilen[0]["hinweis"].startswith("unlesbar: Webseite statt Daten") and len(zeilen) == 1


def test_unternehmen_als_datenhalter_abgelehnt(tmp_path):
    pfade = dateien_schreiben(tmp_path)
    liste = indikatorliste()
    liste[3]["source"] = "Nexiga GmbH, ZEFIR, eigene Berechnungen"   # jugendquotient
    pfade["ww_indikatoren"].write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="jugendquotient hat ein Unternehmen als Datenhalter"):
        strukturdaten.Wegweiser(pfade["ww_export"], pfade["ww_indikatoren"], pfade["ww_regionen"],
                                pfade["ww_version"], pfade["ww_openapi"])


@pytest.mark.parametrize("pfad", ["/kätalog.xlsx", "ftp://127.0.0.1/katalog.xlsx"])
def test_ungueltige_adresse_nicht_gesendet(server, umgebung, monkeypatch, pfad):
    dl, _ = umgebung
    url = pfad if "://" in pfad else server["basis"] + pfad
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("xlsx", url, "offenedaten-koeln")])
    with pytest.raises(SystemExit, match=r"abgebrochen \(adresse\)"):
        strukturdaten.abruf_lauf()
    assert not server["anfragen"] and _protokoll(dl)[-1]["http_status"] == "nicht gesendet (adresse)"


def test_abgebrochener_lauf_mischt_keine_staende(server, umgebung, monkeypatch):
    """Die Wegweiser-Dateien eines Laufs ersetzen die vorigen nur gemeinsam: Bricht der Lauf vor dem Export ab, bleiben
    Datenversion, Listen und Export aus dem vorigen vollständigen Lauf; meta.json nennt die passende Datenversion."""
    dl, aus = umgebung
    uhr = {"jetzt": datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(abruf, "uhr", lambda: uhr["jetzt"])
    strukturdaten.abruf_lauf()
    uhr["jetzt"] = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    vorher = {name: (dl / name).read_bytes() for name, _ in strukturdaten.DATEIEN.values()}
    server["inhalt"]["/version"] = b"2027-05-01T00:00:00Z-neu"
    server["status"]["/export.csv"] = 503
    with pytest.raises(SystemExit, match="HTTP 503"):
        strukturdaten.abruf_lauf()
    assert {name: (dl / name).read_bytes() for name in vorher} == vorher
    assert not (dl / strukturdaten.STUFE).exists()
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status[7:] == ["200", "200", "200", "200", "503"] + [strukturdaten.VERWORFEN] * 4
    meta = strukturdaten.write()
    assert "Datenversion 2026-10-15T08:45:18.099083Z-test" in meta["datenstand_hinweis"]
    beleg = {q["kennung"]: q for q in meta["quellen"]}["wegweiser-openapi"]
    erster = next(z for z in _protokoll(dl) if z["url"].endswith("/openapi"))
    assert beleg["abgerufen"] == erster["zeitstempel"]   # nicht der verworfene Abruf mit gleichem Inhalt
    # vollständiger Lauf: alle fünf Dateien neu, die XLSX unabhängig davon
    del server["status"]["/export.csv"]
    server["status"]["/katalog.xlsx"] = 503
    uhr["jetzt"] = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)
    with pytest.raises(SystemExit, match="HTTP 503"):
        strukturdaten.abruf_lauf()
    assert (dl / "wegweiser_version.txt").read_bytes() == b"2027-05-01T00:00:00Z-neu"
    assert (dl / "statistischer_datenkatalog_koeln.xlsx").read_bytes() == vorher[
        "statistischer_datenkatalog_koeln.xlsx"]
    assert "Datenversion 2027-05-01T00:00:00Z-neu" in strukturdaten.write()["datenstand_hinweis"]


# --- Prüfung r1: Kennzeichnung eigener Einordnungen, Formate, Metatext A0025A ------------------------------------------

def test_eigene_einordnungen_und_formate_gekennzeichnet(umgebung):
    dl, aus = umgebung
    _, t = _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert "eigene Einordnung" in meta["typ_einordnung"] and "strukturdaten_koeln.tsv" in meta["typ_einordnung"]
    vorl = meta["typ_vorlaeufig"]
    assert set(vorl) == {"ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"}
    assert "Veränderungsrate" in vorl["ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"]
    ind = {i["indikator_id"]: i for i in t["indikatoren.tsv"]}
    e = ind["ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"]
    assert e["typ"] == "quote" and "vorläufig" in e["metatext"] and "Veränderungsrate" in e["metatext"]
    assert "vorläufig" not in ind["ww_altenquotient"]["metatext"]
    assert set(meta["formate"]) >= {"jahre", "raumebenen", "wert", "dateien"}
    assert "2012-2014;2016" in meta["formate"]["jahre"]
    assert "geheim" in meta["geheimhaltung_hinweis"]
    assert all(i["jahre"].isascii() for i in t["indikatoren.tsv"])
    assert ind["koeln_A0109P"]["jahre"] == "2024-2025"


def test_metatext_summe_nennt_nicht_pruefbare_zeilen(umgebung):
    """A0025A = A0355A + A0359A: der Metatext nennt geprüfte und nicht prüfbare Zeilen (Testdaten: A0359A fehlt für
    201/2024, für 102/2025 geheim)."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    xlsx_bauen(pfade["xlsx"], lambda d: d.__setitem__("F7", "*"))
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    a = next(i for i in _lesen(aus / "indikatoren.tsv") if i["indikator_id"] == "koeln_A0025A")
    # 24 Zeilen: 12 aus werte.tsv und 12 Quartierszeilen (die Prüfung gilt für jede veröffentlichte Zeile)
    assert ("nachgerechnet in 22 von 24 Zeilen; nicht prüfbar: 1 Zeile mit geheim gehaltenem Wert, 1 Zeile mit "
            "fehlendem Wert") in a["metatext"]


# --- Raumabgleich (Phase 2, Vertrag 1.1) -------------------------------------------------------------------------------

def _geojson(aus, ebene):
    return json.loads((aus / "raum" / f"{ebene}.geojson").read_text(encoding="utf-8"))


def _werte_quartier(aus):
    with gzip.open(aus / "werte_quartier.tsv.gz", "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def test_raum_geojson_properties_und_eltern(umgebung):
    """Properties laut Vertrag; eltern_id nur, wo Verschneidung, Nummer und Attribut übereinstimmen (Prüfstatus ok);
    Stadtteile und Stadtbezirke mit unveränderter Geometrie aus data/geo, Quartiere in WGS84 auf 1e-6 Grad gerundet."""
    dl, aus = umgebung
    pfade, _ = _normalisieren(dl, aus)
    eltern = {}
    for ebene in ("stadtbezirk", "stadtteil", "quartier"):
        d = _geojson(aus, ebene)
        assert d["type"] == "FeatureCollection" and d["meta"]["lizenz_url"] == strukturdaten_raum.GEO_LIZENZ_URL
        assert d["meta"]["namensnennung"] == "Datenquelle: Stadt Köln – offenedaten-koeln.de"
        for f in d["features"]:
            p = f["properties"]
            assert list(p) == ["raum_id", "name", "raumebene", "eltern_id", "quelle", "lizenz"]
            assert p["raumebene"] == ebene and isinstance(p["raum_id"], str) and p["quelle"]
            assert "Datenlizenz Deutschland – Zero – Version 2.0" in p["lizenz"]
            eltern[(ebene, p["raum_id"])] = p["eltern_id"]
    assert {k: v for k, v in eltern.items() if k[0] != "quartier"} == {
        ("stadtbezirk", "1"): "", ("stadtbezirk", "2"): "", ("stadtteil", "101"): "1", ("stadtteil", "102"): "1",
        ("stadtteil", "201"): "2"}
    assert {k[1]: v for k, v in eltern.items() if k[0] == "quartier"} == {
        "101010001": "101", "101010002": "", "101010003": "101", "102010001": "102", "201010001": "", "102020001": ""}
    geo = json.loads(strukturdaten.geo_pfad("stadtteil").read_text(encoding="utf-8"))
    assert {str(f["properties"]["ortsteil"]): f["geometry"] for f in geo["features"]} == {
        f["properties"]["raum_id"]: f["geometry"] for f in _geojson(aus, "stadtteil")["features"]}
    q = _geojson(aus, "quartier")
    assert q["meta"]["sha256"] == hashlib.sha256(pfade["quartiere"].read_bytes()).hexdigest()
    assert q["meta"]["vereinfacht_m"] == strukturdaten_raum.TOLERANZ_M == 2.0
    punkte = [c for f in q["features"] for ring in f["geometry"]["coordinates"] for c in ring]
    assert all(6.8 < x < 7.2 and 50.8 < y < 51.1 for x, y in punkte)
    assert all(round(v, 6) == v for c in punkte for v in c)


def test_zuordnung_flaechenanteile_und_audit(umgebung):
    """Anteile aus der Verschneidung; Splitter unter 1 % gemeldet, nicht zugeordnet; abweichende Nummer und Lage
    außerhalb gemeldet, nicht stillschweigend zugeordnet."""
    dl, aus = umgebung
    _normalisieren(dl, aus)
    zuordnung = _lesen(aus / "zuordnung.tsv")
    assert list(zuordnung[0]) == strukturdaten_raum.KOPF_ZUORDNUNG
    zeilen = [(z["von_ebene"], z["von_id"], z["nach_ebene"], z["nach_id"], z["flaechenanteil"], z["methode"],
               z["konfidenz"]) for z in zuordnung]
    assert zeilen == [
        ("stadtteil", "101", "stadtbezirk", "1", "1.0000", "verschneidung_nummer", "hoch"),
        ("stadtteil", "102", "stadtbezirk", "1", "1.0000", "verschneidung_nummer", "hoch"),
        ("stadtteil", "201", "stadtbezirk", "2", "1.0000", "verschneidung_nummer", "hoch"),
        ("quartier", "101010001", "stadtteil", "101", "1.0000", "verschneidung_nummer", "hoch"),
        ("quartier", "101010002", "stadtteil", "101", "0.7500", "verschneidung_nummer", "mittel"),
        ("quartier", "101010002", "stadtteil", "102", "0.2500", "verschneidung", "niedrig"),
        ("quartier", "101010003", "stadtteil", "101", "0.9926", "verschneidung_nummer", "hoch"),
        ("quartier", "102010001", "stadtteil", "102", "1.0000", "verschneidung_nummer", "hoch"),
        ("quartier", "201010001", "stadtteil", "102", "1.0000", "verschneidung", "niedrig")]
    roh = _lesen(aus / "audit_raumabgleich.tsv")
    assert list(roh[0]) == strukturdaten_raum.KOPF_AUDIT
    audit = {a["von_id"]: a for a in roh}
    assert {k: a["pruefstatus"] for k, a in audit.items()} == {
        "101": "ok", "102": "ok", "201": "ok", "101010001": "ok", "101010002": "abweichung", "101010003": "ok",
        "102010001": "ok", "201010001": "abweichung", "102020001": "nicht_zugeordnet"}
    a = audit["101010003"]
    assert (a["nach_id"], a["splitter"], a["splitter_max_anteil"], a["konfidenz"]) == ("101", "1", "0.0074", "hoch")
    assert "Randsplitter unter 0.01 nicht zugeordnet: Stadtteil 201 (0.0074)" in a["grund"]
    a = audit["101010002"]
    assert (a["weitere_ziele"], a["uebereinstimmung"]) == ("1", "ja")
    assert "größter Flächenanteil 0.7500 unter 0.99; weitere Ziele: Stadtteil 102 (0.2500)" in a["grund"]
    a = audit["201010001"]
    assert (a["nach_id"], a["nach_id_nummer"], a["nach_id_attribut"], a["uebereinstimmung"]) == (
        "102", "201", "201", "nein")
    assert "Nummer nennt Stadtteil 201" in a["grund"] and "Attribut nr_stteil nennt Stadtteil 201" in a["grund"]
    a = audit["102020001"]
    assert (a["nach_id"], a["flaechenanteil"], a["methode"], a["ausserhalb_anteil"], a["in_geometrie"]) == (
        "", "", "", "1.0000", "ja")
    assert "außerhalb aller Stadtteile: 1.0000" in a["grund"]
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    erg = meta["raumabgleich"]["ergebnis"]["quartier→stadtteil"]
    assert erg["pruefstatus"] == {"ok": 3, "abweichung": 2, "nicht_zugeordnet": 1} and erg["zeilen_zuordnung"] == 6
    assert erg["groesster_splitter"] == "0.0074"
    assert meta["raumabgleich"]["id_abgleich"]["quartier"] == {"geometrie": 6, "werte": 6, "gemeinsam": 6,
                                                             "nur_geometrie": [], "nur_werte": [],
                                                             "namen_abweichend": []}


def test_nummern_nur_auf_einer_seite_gemeldet(umgebung):
    """Quartier nur im Blatt Daten: nicht zugeordnet, Werte bleiben (quellentreu); Quartier nur im Shapefile:
    Geometrie ohne Werte, Prüfstatus abweichung; beide in meta.json (id_abgleich) und im Audit."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    xlsx_bauen(pfade["xlsx"], lambda d: d.append(["2025", "909990001 / Testquartier ohne Fläche",
                                                  "Statistische Quartiere", *_werte("909990001 / x", 2025)]))
    quartiere_zip(pfade["quartiere"], {**QUARTIERE, "102030001": ("Testquartier ohne Werte", "102",
                                                                  (1700, 100, 1900, 300))})
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    audit = {a["von_id"]: a for a in _lesen(aus / "audit_raumabgleich.tsv")}
    a = audit["909990001"]
    assert (a["in_geometrie"], a["in_werten"], a["pruefstatus"], a["nach_id"], a["nach_id_nummer"]) == (
        "nein", "ja", "nicht_zugeordnet", "", "909")
    assert a["grund"].startswith("keine Geometrie in der Quelle") and a["name"] == "Testquartier ohne Fläche"
    a = audit["102030001"]
    assert (a["in_geometrie"], a["in_werten"], a["pruefstatus"], a["nach_id"]) == ("ja", "nein", "abweichung", "102")
    assert "keine Zeile im Blatt Daten" in a["grund"]
    assert "909990001" not in {z["von_id"] for z in _lesen(aus / "zuordnung.tsv")}
    features = {f["properties"]["raum_id"]: f["properties"] for f in _geojson(aus, "quartier")["features"]}
    assert "909990001" not in features and features["102030001"]["eltern_id"] == ""
    assert {w["raum_id"] for w in _werte_quartier(aus)} == set(QUARTIERE) | {"909990001"}
    ids = json.loads((aus / "meta.json").read_text(encoding="utf-8"))["raumabgleich"]["id_abgleich"]["quartier"]
    assert ids == {"geometrie": 7, "werte": 7, "gemeinsam": 6, "nur_geometrie": ["102030001"],
                   "nur_werte": ["909990001"], "namen_abweichend": []}


def test_werte_quartier_unveraendert_aus_der_zelle(umgebung):
    """Jeder Wert der Quartiere steht unverändert in seiner Zelle (keine Summen, keine Umrechnung über Raumebenen);
    werte.tsv bleibt ohne Quartiere, zuordnung.tsv ohne Werte."""
    dl, aus = umgebung
    pfade, t = _normalisieren(dl, aus)
    zeilen = _werte_quartier(aus)
    assert list(zeilen[0]) == strukturdaten.KOPF_WERTE
    assert {z["raumebene"] for z in zeilen} == {"quartier"} and len(zeilen) == len(QUARTIERE) * 2 * 6
    mappe = openpyxl.load_workbook(pfade["xlsx"], read_only=True, data_only=True)
    daten = {i: z for i, z in enumerate(mappe["Daten"].iter_rows(values_only=True), start=1)}
    kopf = daten[1]
    from openpyxl.utils import column_index_from_string
    for z in zeilen:
        spalte, zeile = re.fullmatch(r"Daten!([A-Z]+)(\d+)", z["quellobjekt"]).groups()
        quelle = daten[int(zeile)]
        assert (quelle[0], quelle[2]) == (z["jahr"], "Statistische Quartiere")
        assert quelle[1].startswith(z["raum_id"] + " / ")
        assert kopf[column_index_from_string(spalte) - 1].startswith(z["indikator_id"].removeprefix("koeln_") + " - ")
        v = quelle[column_index_from_string(spalte) - 1]
        erwartet = (("", "geheim") if v == "*" else ("", "fehlt") if v in (None, "") else (strukturdaten.zahl(v), "ok"))
        assert (z["wert"], z["status"]) == erwartet
    mappe.close()
    from collections import Counter
    assert Counter(z["status"] for z in zeilen) == {"ok": 70, "geheim": 1, "fehlt": 1}
    schluessel = [(int(z["raum_id"]), z["indikator_id"], z["jahr"]) for z in zeilen]
    assert schluessel == sorted(schluessel)
    assert "quartier" not in {w["raumebene"] for w in t["werte.tsv"]}
    assert set(_lesen(aus / "zuordnung.tsv")[0]) == set(strukturdaten_raum.KOPF_ZUORDNUNG)


def test_gzip_deterministisch(umgebung, tmp_path, monkeypatch):
    """werte_quartier.tsv.gz ohne Dateinamen und mit Änderungszeit 0: an anderem Ort und später byte-gleich."""
    dl, aus = umgebung
    _normalisieren(dl, aus)
    roh = (aus / "werte_quartier.tsv.gz").read_bytes()
    assert roh[:4] == b"\x1f\x8b\x08\x00" and roh[4:8] == b"\x00\x00\x00\x00"   # FLG 0 (kein FNAME), MTIME 0
    assert roh[8:10] == b"\x02\xff"   # XFL 2: höchste Stufe (9, wie in meta.json zugesagt); OS 255 (unbekannt, fest)
    monkeypatch.setenv("STRUKTURDATEN_AUS", str(tmp_path / "anderer_ort"))
    strukturdaten.write()
    assert (tmp_path / "anderer_ort" / "werte_quartier.tsv.gz").read_bytes() == roh
    assert gzip.decompress(roh).decode("utf-8").startswith("\t".join(strukturdaten.KOPF_WERTE) + "\n")


def test_meta_vertrag_1_1(umgebung):
    dl, aus = umgebung
    pfade, t = _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert meta["vertrag_version"] == "1.1" and "werte_quartier.tsv.gz" in meta["vertrag_aenderungen"]["1.1"]
    dateien = {d["datei"]: d["vertrag"] for d in meta["dateien"]}
    assert dateien["werte_quartier.tsv.gz"] is True and dateien["raum/quartier.geojson"] is True
    assert dateien["audit_raumabgleich.tsv"] is False and dateien["zurueckgestellt.tsv"] is False
    assert meta["raumebenen_dateien"] == {"gesamtstadt": "werte.tsv", "stadtbezirk": "werte.tsv",
                                          "stadtteil": "werte.tsv", "quartier": "werte_quartier.tsv.gz"}
    assert set(meta["raumebenen_nicht_uebernommen"]) == {"sozialraum"}
    q = {q["kennung"]: q for q in meta["quellen"]}["statistische-quartiere-koeln"]
    assert q["sha256"] == hashlib.sha256(pfade["quartiere"].read_bytes()).hexdigest()
    assert (q["url"], q["lizenz"], q["lizenz_url"], q["namensnennung"]) == (
        strukturdaten_raum.QUARTIERE_URL, "Datenlizenz Deutschland – Zero – Version 2.0",
        "https://www.govdata.de/dl-de/zero-2-0", "Datenquelle: Stadt Köln – offenedaten-koeln.de")
    assert q["datensatz_url"] == "https://open.nrw/dataset/statistische-quartiere-koln-k"
    r = meta["raumabgleich"]
    assert (r["splitter_anteil"], r["anteil_hoch"]) == (0.01, 0.99)
    assert set(meta["audit_raumabgleich_spalten"]) == set(strukturdaten_raum.KOPF_AUDIT)
    assert "gesamtstadt;stadtbezirk;stadtteil;quartier" in meta["formate"]["raumebenen"]
    zeile = next(a for a in t["audit_abruf.tsv"] if a["url"] == strukturdaten_raum.QUARTIERE_URL)
    assert (zeile["http_status"], zeile["zeilen"]) == ("200", str(len(QUARTIERE)))


def test_quartiere_in_anderem_bezugssystem(umgebung):
    """Das Bezugssystem kommt aus der .prj-Datei: dieselben Flächen in Gauß-Krüger (EPSG 31466) ergeben dieselben
    Anteile (Umrechnung nach EPSG 25832 vor der Verschneidung)."""
    from pyproj import CRS
    from pyproj.enums import WktVersion
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    gk = Transformer.from_crs(25832, 31466, always_xy=True)
    quartiere_zip(pfade["quartiere"], prj=CRS.from_epsg(31466).to_wkt(WktVersion.WKT1_ESRI), umrechnen=gk.transform)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    anteile = {(z["von_id"], z["nach_id"]): z["flaechenanteil"] for z in _lesen(aus / "zuordnung.tsv")}
    assert anteile[("101010001", "101")] == "1.0000"
    assert abs(float(anteile[("101010002", "101")]) - 0.75) < 0.0005
    assert "Gauss" in _geojson(aus, "quartier")["meta"]["crs"]   # Name des Bezugssystems aus der .prj-Datei


@pytest.mark.parametrize("fall", ["ohne_shp", "zwei_shp", "geografisch", "zu_gross", "nummer"])
def test_quartiere_unlesbar(tmp_path, monkeypatch, fall):
    """Das ZIP-Archiv wird nur mit zipfile und pyshp gelesen; unerwarteter Aufbau bricht mit ValueError ab."""
    pfad = tmp_path / "q.zip"
    quartiere_zip(pfad)
    inhalt = {n: zipfile.ZipFile(pfad).read(n) for n in zipfile.ZipFile(pfad).namelist()}
    if fall == "ohne_shp":
        inhalt = {n: b for n, b in inhalt.items() if not n.endswith(".shp")}
    elif fall == "zwei_shp":
        inhalt["Kopie.shp"] = inhalt["Statistisches_Quartier.shp"]
    elif fall == "geografisch":
        inhalt["Statistisches_Quartier.prj"] = b'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",' \
                                               b'6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",' \
                                               b'0.0174532925199433]]'
    elif fall == "zu_gross":
        monkeypatch.setattr(strukturdaten_raum, "MAX_ENTPACKT", 100)
    elif fall == "nummer":
        quartiere_zip(pfad, {"1010": ("kurz", "101", (0, 0, 10, 10))})
        inhalt = {n: zipfile.ZipFile(pfad).read(n) for n in zipfile.ZipFile(pfad).namelist()}
    with zipfile.ZipFile(pfad, "w") as z:
        for n, b in inhalt.items():
            z.writestr(n, b)
    meldung = {"ohne_shp": "genau ein Shapefile", "zwei_shp": "genau ein Shapefile", "geografisch": "kein projiziertes",
               "zu_gross": "entpackt größer", "nummer": "unerwartete Quartiersnummer"}[fall]
    with pytest.raises(ValueError, match=meldung):
        strukturdaten_raum.Quartiere(pfad)


def test_quartiere_obergrenze_der_anfragen(server, umgebung, monkeypatch):
    """Die Quartiersdatei zählt gegen die Obergrenze: mit 6 statt 7 Anfragen wird sie nicht mehr gesendet."""
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "MAX_ANFRAGEN", 6)
    with pytest.raises(SystemExit, match="obergrenze"):
        strukturdaten.abruf_lauf()
    assert "/quartiere.zip" not in [p for p, _ in server["anfragen"]] and len(server["anfragen"]) == 6
    letzte = _protokoll(dl)[-1]
    assert (letzte["url"].endswith("/quartiere.zip"), letzte["http_status"]) == (True, "nicht gesendet (obergrenze)")
    assert not (dl / strukturdaten.DATEIEN["quartiere"][0]).exists()


def test_quartiere_stadtschutz_ohne_anfrage(umgebung, monkeypatch):
    """Die echte Adresse der Quartiersdatei liegt bei der Stadt: ohne RATSATLAS_STADT_INFORMIERT und außerhalb des
    Zeitfensters nicht gesendet, kein Versuch einer Verbindung."""
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "_OEFFNER", _KeinNetz())
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("quartiere", strukturdaten_raum.QUARTIERE_URL, "offenedaten-koeln")])
    monkeypatch.setenv("STRUKTURDATEN_ABRUF", "ja")
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    strukturdaten.abruf_lauf()
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc))   # 12 Uhr in Köln
    strukturdaten.abruf_lauf()
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status[0].startswith("nicht gesendet (gesperrt: Server der Stadt Köln")
    assert status[1].startswith("nicht gesendet (außerhalb des Zeitfensters 23-1 Uhr")


def test_quartiere_vom_lokalen_server_als_stadt(server, umgebung, monkeypatch):
    """Mit Freigabe im Zeitfenster genau eine Anfrage; Datei und Protokoll (570 → hier 6 Datensätze) wie bei der XLSX."""
    dl, _ = umgebung
    _als_stadt(server, monkeypatch, ["quartiere"])
    assert strukturdaten.abruf_lauf().anfragen == 1
    assert server["anfragen"] == [("/quartiere.zip", config.USER_AGENT)]
    zeile = _protokoll(dl)[-1]
    assert (zeile["http_status"], zeile["zeilen"]) == ("200", str(len(QUARTIERE)))
    assert (dl / strukturdaten.DATEIEN["quartiere"][0]).read_bytes() == server["inhalt"]["/quartiere.zip"]


# --- Korrekturen nach der Prüfung von Phase 2 -------------------------------------------------------------------------

def _box(x0, y0, x1, y1):
    from shapely.geometry import box
    return box(x0, y0, x1, y1)


def test_schwellen_gelten_fuer_den_gerundeten_anteil():
    """Die Schwellen 0,99 und 0,01 gelten für den veröffentlichten, auf 4 Stellen gerundeten Anteil: Ein Anteil von
    0,98996 erscheint als „0.9900“ und gilt damit als vollständige Lage (konfidenz hoch, ok), ein Teil von 0,009996
    erscheint als „0.0100“ und gilt nicht als Randsplitter."""
    einheit = {"101010001": {"name": "Testquartier", "attribut": "101", "geom": _box(0, 0, 100000, 1)}}
    namen = {"101010001": "Testquartier"}
    ziele = {"101": {"geom": _box(0, 0, 98996, 10)}, "102": {"geom": _box(98996, 0, 200000, 10)}}
    zuordnung, audit, eltern = strukturdaten_raum.abgleich("quartier", "stadtteil", einheit, ziele, namen)
    assert [(z["nach_id"], z["flaechenanteil"], z["konfidenz"]) for z in zuordnung] == [
        ("101", "0.9900", "hoch"), ("102", "0.0100", "niedrig")]
    (a,) = audit
    assert (a["pruefstatus"], a["weitere_ziele"], a["splitter"]) == ("ok", "1", "0") and eltern == {"101010001": "101"}
    assert "unter 0.99" not in a["grund"]
    ziele = {"101": {"geom": _box(0, 0, 99000.4, 10)}, "102": {"geom": _box(99000.4, 0, 200000, 10)}}
    zuordnung, audit, _ = strukturdaten_raum.abgleich("quartier", "stadtteil", einheit, ziele, namen)
    assert [(z["nach_id"], z["flaechenanteil"]) for z in zuordnung] == [("101", "0.9900"), ("102", "0.0100")]
    assert (audit[0]["splitter"], audit[0]["splitter_max_anteil"], audit[0]["weitere_ziele"]) == ("0", "", "1")
    assert "Randsplitter" not in audit[0]["grund"]
    # knapp darunter bleibt es bei der Abweichung bzw. beim Randsplitter (gerundet 0.9899 und 0.0099)
    ziele = {"101": {"geom": _box(0, 0, 98994, 10)}, "102": {"geom": _box(98994, 0, 99000, 10)}}
    zuordnung, audit, eltern = strukturdaten_raum.abgleich("quartier", "stadtteil", einheit, ziele, namen)
    assert [(z["nach_id"], z["flaechenanteil"], z["konfidenz"]) for z in zuordnung] == [("101", "0.9899", "mittel")]
    assert audit[0]["pruefstatus"] == "abweichung" and eltern == {}
    assert "größter Flächenanteil 0.9899 unter 0.99" in audit[0]["grund"]
    assert "Randsplitter unter 0.01 nicht zugeordnet: Stadtteil 102 (0.0001)" in audit[0]["grund"]
    assert "außerhalb aller Stadtteile: 0.0100" in audit[0]["grund"]


FINGER = [(600, 500), (600, 800), (900, 800), (900, 651), (1300, 651), (1300, 650), (900, 650), (900, 500)]
SPORN = [(100, 500), (100, 800), (400, 800), (400, 650.01), (430, 650.01), (430, 650), (400, 650), (400, 500)]


def test_verschneidung_mit_unvereinfachten_quartieren(tmp_path):
    """Die Verschneidung rechnet mit den Flächen der Quelle: Ein 1 m breiter Fortsatz über die Stadtteilgrenze ergibt
    genau 300 m² von 90 400 m² in Stadtteil 102 (vereinfacht wären es weniger). Eine Nummer, die einen anderen
    Stadtteil nennt als Lage und Attribut, ergibt uebereinstimmung „nein“. Die veröffentlichte Fläche weicht dagegen
    ab: Die Vereinfachung entfernt einen 30 m langen Sporn von 1 cm Breite (Dreiecksfläche 0,15 m²); meta nennt die
    Abweichung."""
    geo = geo_schreiben(tmp_path / "geo")
    quartiere = {"101010001": ("Testquartier Fortsatz", "101", FINGER),
                 "101010002": ("Testquartier Sporn", "101", SPORN),
                 "201010002": ("Testquartier Nummer", "102", (1300, 100, 1600, 400))}
    quartiere_zip(tmp_path / "q.zip", quartiere)
    beleg = {"url": "https://example.invalid/q.zip", "zeitstempel": "2026-11-10T10:00:00+01:00", "pruefsumme": "0"}
    r = strukturdaten_raum.raumabgleich(tmp_path / "q.zip", beleg, geo["stadtteil"], geo["stadtbezirk"],
                                        {"quartier": {n: q[0] for n, q in quartiere.items()}})
    audit = {a["von_id"]: a for a in r["audit"] if a["von_ebene"] == "quartier"}
    a = audit["101010001"]
    assert (a["nach_id"], a["flaechenanteil"], a["splitter"], a["splitter_max_anteil"], a["pruefstatus"]) == (
        "101", f"{90100 / 90400:.4f}", "1", f"{300 / 90400:.4f}", "ok")
    assert f"Stadtteil 102 ({300 / 90400:.4f})" in a["grund"]
    a = audit["201010002"]
    assert (a["nach_id"], a["nach_id_nummer"], a["nach_id_attribut"], a["uebereinstimmung"], a["pruefstatus"],
            a["methode"], a["konfidenz"]) == ("102", "201", "102", "nein", "abweichung", "verschneidung", "niedrig")
    assert "Attribut" not in a["grund"] and "Nummer nennt Stadtteil 201" in a["grund"]
    assert audit["101010002"]["flaechenanteil"] == "1.0000"
    gemessen = r["geojson_meta"]["quartier"]["abweichung_von_der_quelle"]
    assert gemessen["abstand_max_raum_id"] == "101010002" and 29.9 < gemessen["abstand_max_m"] < 30.1
    assert list(gemessen["ueber_toleranz"]) == ["101010002"] and gemessen["bis_toleranz"] == 2
    assert (gemessen["einheiten"], gemessen["ueberlappung_nachbarpaare"], gemessen["luecken_teile"]) == (3, 0, 0)
    sporn = next(f for f in json.loads(r["geojson"]["quartier"])["features"]
                 if f["properties"]["raum_id"] == "101010002")
    nach_utm = Transformer.from_crs(4326, 25832, always_xy=True)
    rechts = max(nach_utm.transform(x, y)[0] for x, y in sporn["geometry"]["coordinates"][0]) - X0
    assert 399 < rechts < 401   # Sporn (bis x = 430) entfernt, das Quadrat (bis x = 400) bleibt
    assert "Sporne" in r["geojson_meta"]["quartier"]["geometrie"]


def test_abweichung_misst_luecken_und_ueberlappungen():
    """strukturdaten_raum.abweichung: Hausdorff-Abstand je Einheit, Überlappungen zwischen Nachbarn und Löcher in der
    Vereinigung, die die Quelle nicht hat (der Außenrand zählt nicht)."""
    quelle = {"1": _box(0, 0, 10, 10), "2": _box(10, 0, 20, 10), "3": _box(0, 10, 10, 20), "4": _box(10, 10, 20, 20)}
    aus = {"1": _box(0, 0, 10.5, 10), "2": _box(10, 0, 20, 10),
           "3": _box(0, 10, 10, 20).difference(_box(9, 10, 10, 11)),   # Kerbe an der Ecke: 1 m² Lücke im Inneren
           "4": _box(10, 10, 20, 19)}   # 4: am Außenrand gekürzt (keine Lücke im Inneren)
    a = strukturdaten_raum.abweichung(quelle, aus, toleranz=0.75)
    assert (a["einheiten"], a["abstand_max_m"], a["abstand_max_raum_id"], a["abstand_median_m"]) == (4, 1.0, "3", 0.75)
    assert a["ueber_toleranz"] == {"3": 1.0, "4": 1.0} and a["bis_toleranz"] == 2
    assert (a["ueberlappung_nachbarpaare"], a["ueberlappung_m2"], a["luecken_teile"], a["luecken_m2"]) == (1, 5, 1, 1)
    gleich = strukturdaten_raum.abweichung(quelle, quelle)
    assert (gleich["abstand_max_m"], gleich["abstand_median_m"], gleich["ueber_toleranz"], gleich["ueberlappung_m2"],
            gleich["luecken_m2"]) == (0.0, 0.0, {}, 0, 0)


# --- Lückenlose Vereinfachung der Quartiere (Entscheidung 10.11.2026) -------------------------------------------------

def _welle(k, n):
    """Erfundene Auslenkung einer gewellten Grenze in Metern (bis etwa 3,7 m) am k-ten von n Abschnitten, an beiden
    Enden 0."""
    return 0.0 if k in (0, n) else round(2.5 * math.sin(1.3 * k) + 1.2 * math.sin(3.7 * k), 2)


WAAG = [(100 + 10 * k, 500 + _welle(k, 80)) for k in range(81)]   # (100, 500) → (900, 500), Stützpunkte alle 10 m
KNOTEN = WAAG[40]                                                  # (500, 502.06): hier treffen drei Quartiere zusammen
SENK = [KNOTEN] + [(500 + _welle(k, 40), 500 + 10 * k) for k in range(1, 41)]   # KNOTEN → (500, 900)
# Drei Quartiere mit gewellten gemeinsamen Grenzen (Ringe im Uhrzeigersinn wie im Shapefile): unten eines über die
# ganze Breite, oben zwei, die sich in KNOTEN auf der unteren Grenze treffen. Jedes Quartier für sich vereinfacht,
# behält das untere den Knoten nicht unbedingt (er liegt für es mitten auf der Grenze), die oberen schon.
WELLEN = {
    "101010001": ("Testquartier unten", "101", [(100, 100), *WAAG, (900, 100)]),
    "101010002": ("Testquartier oben links", "101", [(100, 500), (100, 900), *SENK[::-1], *WAAG[39:0:-1]]),
    "101010003": ("Testquartier oben rechts", "101", [*SENK, (900, 900), *WAAG[80:40:-1]]),
}


def _befunde(flaechen):
    """Was einer lückenlosen Abdeckung widerspricht, für {Nummer: Fläche in WGS84}: ungültige oder leere Flächen,
    Nachbarpaare, deren Verschneidung eine Fläche hat, Unterschied zwischen der Summe der Flächen und ihrer
    Vereinigung, Löcher in der Vereinigung (Lücken; die Testflächen haben keine) und Nachbarpaare, bei denen die
    Stützpunkte der einen Fläche auf der Grenze der anderen nicht dieselben sind wie umgekehrt. Gerechnet ohne Gitter
    (shapely.set_precision hängt den Flächen eines an, mit dem die Verschneidung schmale Überlappungen wegrundet)."""
    flaechen = {r: shapely.set_precision(f, 0) for r, f in flaechen.items()}
    ids = sorted(flaechen)
    befunde = {"ungueltig": [r for r in ids if flaechen[r].is_empty or not flaechen[r].is_valid],
               "ueberlappungen": [], "stuetzpunkte_verschieden": []}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            fa, fb = flaechen[a], flaechen[b]
            if shapely.intersection(fa, fb).area > 0:
                befunde["ueberlappungen"].append((a, b))
            pa, pb = ({tuple(p) for p in shapely.get_coordinates(f)} for f in (fa, fb))
            if ({p for p in pa if shapely.distance(shapely.Point(p), fb.boundary) == 0}
                    != {p for p in pb if shapely.distance(shapely.Point(p), fa.boundary) == 0}):
                befunde["stuetzpunkte_verschieden"].append((a, b))
    vereinigt = shapely.union_all([flaechen[r] for r in ids])
    summe = sum(flaechen[r].area for r in ids)
    befunde["summe_minus_vereinigung"] = abs(summe - vereinigt.area) > 1e-9 * summe
    befunde["loecher"] = sum(len(p.interiors) for p in shapely.get_parts(vereinigt))
    return befunde


KEINE_BEFUNDE = {"ungueltig": [], "ueberlappungen": [], "stuetzpunkte_verschieden": [],
                 "summe_minus_vereinigung": False, "loecher": 0}


def _veroeffentlicht(r):
    return {f["properties"]["raum_id"]: shape(f["geometry"]) for f in json.loads(r["geojson"]["quartier"])["features"]}


def test_quartiere_lueckenlos_vereinfacht(tmp_path):
    """Entscheidung 10.11.2026 („lückenlose Vereinfachung“): Drei Quartiere mit gewellten gemeinsamen Grenzen werden
    gemeinsam vereinfacht und gerundet. Veröffentlicht: alle Flächen gültig, keine Überlappung (Verschneidung je Paar
    ohne Fläche, Summe der Flächen gleich der Vereinigung), keine Lücke (kein Loch in der Vereinigung), jede
    gemeinsame Grenze als Linie in beiden Flächen mit denselben Stützpunkten, Koordinaten auf 1e-6 Grad; meta meldet
    0/0 und eine gültige Abdeckung. Gegenprobe: Die bisherige Vereinfachung jedes Quartiers für sich
    (geodaten._wgs84) erzeugt aus derselben Quelle Überlappungen und Lücken."""
    geo = geo_schreiben(tmp_path / "geo")
    quartiere_zip(tmp_path / "q.zip", WELLEN)
    beleg = {"url": "https://example.invalid/q.zip", "zeitstempel": "2026-11-10T10:00:00+01:00", "pruefsumme": "0"}
    r = strukturdaten_raum.raumabgleich(tmp_path / "q.zip", beleg, geo["stadtteil"], geo["stadtbezirk"],
                                        {"quartier": {n: q[0] for n, q in WELLEN.items()}})
    flaechen = _veroeffentlicht(r)
    assert sorted(flaechen) == sorted(WELLEN)
    assert _befunde(flaechen) == KEINE_BEFUNDE
    assert all(f.geom_type == "Polygon" and not f.exterior.is_ccw for f in flaechen.values())   # wie data/geo
    punkte = shapely.get_coordinates(list(flaechen.values()))
    assert (np.round(punkte, 6) == punkte).all()
    utm = {rid: strukturdaten_raum._umrechnen(f, strukturdaten_raum._NACH_UTM) for rid, f in flaechen.items()}
    for a, b, laenge in (("101010001", "101010002", 400), ("101010001", "101010003", 400),
                         ("101010002", "101010003", 398)):   # gemeinsame Grenze mindestens so lang wie ihre Sehne
        assert shapely.intersection(utm[a].boundary, utm[b].boundary).length > laenge - 1, (a, b)
    quelle = strukturdaten_raum.Quartiere(tmp_path / "q.zip").einheiten
    for rid, f in flaechen.items():   # die gewellten Grenzen sind vereinfacht, aber nicht begradigt
        assert 10 < shapely.get_num_coordinates(f) < shapely.get_num_coordinates(quelle[rid]["geom"])
    meta = r["geojson_meta"]["quartier"]
    gemessen = meta["abweichung_von_der_quelle"]
    assert (gemessen["einheiten"], gemessen["ueberlappung_nachbarpaare"], gemessen["ueberlappung_m2"],
            gemessen["luecken_teile"], gemessen["luecken_m2"]) == (3, 0, 0, 0, 0)
    assert 0 < gemessen["abstand_median_m"] <= gemessen["abstand_max_m"]
    d = meta["abdeckung"]
    assert (d["quelle_gueltig"], d["quelle_ungueltige_kanten_m"], d["veroeffentlicht_gueltig"],
            d["netzflaechen_ohne_quartier"]) == (True, {}, True, 0)
    assert "gemeinsam" in meta["geometrie"] and "für sich" not in meta["geometrie"]

    alt = {rid: geodaten._wgs84(e["geom"], strukturdaten_raum.TOLERANZ_M) for rid, e in quelle.items()}
    befunde = _befunde(alt)
    assert befunde["ueberlappungen"] and befunde["loecher"] and befunde["summe_minus_vereinigung"]


# Drei Knoten und ein Keil, dessen Kante 2 cm an einem Stützpunkt vorbeiläuft (wie zwei Kölner Quartiere am
# 10.11.2026): Punkte in Einheiten von 1e-6 Grad um (6,95; 50,92), Ringe im Uhrzeigersinn. P11 (0,45 | −0,55) liegt
# 0,21 Einheiten über der Kante P12–P13; gerundet (0 | −1) liegt er 0,2 Einheiten darunter.
LAENGE0, BREITE0 = 6.95, 50.92
P10, P11, P12, P13 = (-1000, 600), (0.45, -0.55), (10, 0), (-1000, -80.8)
KEIL = {
    "101010001": ("Testquartier Keil", "101", [P10, P11, P12, P13]),
    "101010002": ("Testquartier oben links", "101", [P10, (-1000, 1000), (0.45, 1000), P11]),
    "101010003": ("Testquartier oben rechts", "101", [(0.45, 1000), (1000, 1000), (1000, 0), P12, P11]),
    "101010004": ("Testquartier unten", "101", [P13, P12, (1000, 0), (1000, -1000), (-1000, -1000)]),
}


def _keil_quartiere():
    """KEIL in Metern relativ zu (X0, Y0) in EPSG 25832 (wie quartiere_zip sie erwartet)."""
    nach = Transformer.from_crs(4326, 25832, always_xy=True)

    def utm(p):
        x, y = nach.transform(LAENGE0 + p[0] * 1e-6, BREITE0 + p[1] * 1e-6)
        return (x - X0, y - Y0)
    return {n: (name, teil, [utm(p) for p in ring]) for n, (name, teil, ring) in KEIL.items()}


def test_rundung_gemeinsam_ohne_ueberlappung(tmp_path):
    """Die Rundung auf 1e-6 Grad läuft für alle Grenzen zusammen (Snap-Rounding): Die Kante P12–P13 wird über den
    gerundeten Knoten P11 geführt, in beiden Quartieren an der Kante; der Keil verliert seine Spitze und bleibt gültig.
    Gegenproben auf derselben gemeinsam vereinfachten Quelle: Nur die Koordinaten zu runden macht den Keil ungültig
    (Selbstüberschneidung); shapely.set_precision je Quartier (wie geodaten._wgs84) führt die Kante nur im Keil über
    P11 und erzeugt eine Überlappung mit dem Quartier darunter."""
    quartiere = _keil_quartiere()
    quartiere_zip(tmp_path / "q.zip", quartiere)
    quelle = {rid: e["geom"] for rid, e in strukturdaten_raum.Quartiere(tmp_path / "q.zip").einheiten.items()}
    assert strukturdaten_raum.abdeckung_pruefen([quelle[r] for r in sorted(quelle)]) == (True, {})
    flaechen, pruefung = strukturdaten_raum.quartiersflaechen(quelle)
    assert _befunde(flaechen) == KEINE_BEFUNDE
    assert (pruefung["veroeffentlicht_gueltig"], pruefung["teile_wie_quelle"]) == (True, 4)
    p11 = (round(LAENGE0, 6), round(BREITE0 - 1e-6, 6))   # P11 gerundet
    for rid in ("101010001", "101010002", "101010003", "101010004"):
        assert p11 in {tuple(p) for p in shapely.get_coordinates(flaechen[rid])}, rid

    vereinfacht = shapely.coverage_simplify([quelle[r] for r in sorted(quelle)], strukturdaten_raum.TOLERANZ_M)
    assert [shapely.get_num_coordinates(g) for g in vereinfacht] == [5, 5, 6, 6]   # nichts entfernt
    wgs = {r: strukturdaten_raum._umrechnen(g, geodaten.NACH_WGS84) for r, g in zip(sorted(quelle), vereinfacht)}
    nur_koordinaten = {r: shapely.transform(g, lambda c: np.round(c, 6)) for r, g in wgs.items()}
    assert _befunde(nur_koordinaten)["ungueltig"] == ["101010001"]
    je_flaeche = {r: shapely.set_precision(g, 1e-6) for r, g in wgs.items()}
    assert ("101010001", "101010004") in _befunde(je_flaeche)["ueberlappungen"]


def test_quartiersflaechen_pruefungen():
    """quartiersflaechen meldet eine ungültige Abdeckung der Quelle (Überlappung) und löst sie auf: Die Netzfläche der
    Überlappung gehört zu genau einem der beiden Quartiere. Verliert ein Quartier durch die Rundung einen Teil (Insel
    von 1 cm), bricht der Schritt ab, statt die Fläche ohne den Teil zu veröffentlichen."""
    links, rechts = _box(X0, Y0, X0 + 100, Y0 + 100), _box(X0 + 90, Y0, X0 + 200, Y0 + 100)
    flaechen, pruefung = strukturdaten_raum.quartiersflaechen({"101010002": rechts, "101010001": links})
    assert pruefung["quelle_gueltig"] is False and set(pruefung["quelle_ungueltige_kanten_m"]) == {"101010001",
                                                                                                   "101010002"}
    assert _befunde(flaechen) == KEINE_BEFUNDE and pruefung["veroeffentlicht_gueltig"]
    flaeche = {r: strukturdaten_raum._umrechnen(f, strukturdaten_raum._NACH_UTM).area for r, f in flaechen.items()}
    assert abs(flaeche["101010001"] + flaeche["101010002"] - 20000) < 20
    assert min(abs(flaeche["101010001"] - 9000), abs(flaeche["101010001"] - 10000)) < 20   # Überlappung links/rechts
    insel = shapely.MultiPolygon([links, _box(X0 + 300, Y0, X0 + 300.01, Y0 + 0.01)])
    with pytest.raises(ValueError, match="101010001 mit 1 statt 2 Teilen"):
        strukturdaten_raum.quartiersflaechen({"101010001": insel})


def test_abweichender_name_als_hinweis(umgebung):
    """Namen der Quartiere werden zwischen Shapefile und Blatt Daten in allen Jahren verglichen: ein abweichender Name
    steht mit Jahr als Hinweis im Audit und in meta.json (id_abgleich), der Prüfstatus bleibt."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)

    def umbenennen(daten):
        daten["B17"] = "101010001 / Testquartier (alter Name)"   # 2024; 2025 wie im Shapefile
    xlsx_bauen(pfade["xlsx"], umbenennen)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    audit = {a["von_id"]: a for a in _lesen(aus / "audit_raumabgleich.tsv")}
    a = audit["101010001"]
    assert (a["pruefstatus"], a["name"]) == ("ok", "Testquartier")
    assert a["grund"].endswith("Name im Blatt Daten abweichend: „Testquartier (alter Name)“ (2024); Geometriequelle: "
                               "„Testquartier“")
    assert all("Name im Blatt Daten" not in b["grund"] for k, b in audit.items() if k != "101010001")
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert meta["raumabgleich"]["id_abgleich"]["quartier"]["namen_abweichend"] == ["101010001"]
    assert meta["raumabgleich"]["id_abgleich"]["stadtteil"]["namen_abweichend"] == []
    assert "Name" in meta["audit_raumabgleich_spalten"]["grund"]


def test_portalstand_nur_fuer_die_gepruefte_datei(umgebung, monkeypatch):
    """Der Stand laut open.nrw gilt nur für die Datei mit der am 10.11.2026 geprüften Prüfsumme; für eine andere Datei
    (etwa nach einem späteren Abruf) steht „nicht geprüft“ statt eines veralteten Datums."""
    dl, aus = umgebung
    pfade, _ = _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    q = {q["kennung"]: q for q in meta["quellen"]}["statistische-quartiere-koeln"]
    assert q["datenstand_hinweis"].startswith("Stand der Ressource auf open.nrw für diese Datei nicht geprüft; ")
    assert "24.09.2026" not in json.dumps(meta, ensure_ascii=False)
    assert "06.07.2026" not in meta["datenstand_hinweis"] and "open.nrw für diese Datei nicht geprüft" in meta[
        "datenstand_hinweis"]
    summe = {k: hashlib.sha256(pfade[k].read_bytes()).hexdigest() for k in ("quartiere", "xlsx")}
    monkeypatch.setattr(strukturdaten_raum, "QUARTIERE_STAND_PORTAL",
                        {summe["quartiere"]: ("01.02.2026", "03.02.2026")})
    monkeypatch.setattr(strukturdaten, "OPEN_NRW_RESSOURCEN", {summe["xlsx"]: ("04.05.2026", "03.02.2026")})
    strukturdaten.write()
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    q = {q["kennung"]: q for q in meta["quellen"]}["statistische-quartiere-koeln"]
    assert q["datenstand_hinweis"].startswith("Ressource laut open.nrw zuletzt aktualisiert am 01.02.2026 (Metadaten "
                                              "gelesen am 03.02.2026); Shapefile im Archiv vom ")
    assert "die Ressourcen auf open.nrw tragen den 04.05.2026" in meta["datenstand_hinweis"]


def test_herkunft_der_gebiete_aus_data_geo(umgebung, monkeypatch):
    """raum/stadtteil.geojson und raum/stadtbezirk.geojson: Abrufdatum nur für die belegte Fassung von data/geo
    (Prüfsumme), sonst „nicht dokumentiert“; kein geschätztes Datum."""
    dl, aus = umgebung
    _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    for ebene in ("stadtteil", "stadtbezirk"):
        r = meta["raum"][ebene]
        assert r["abgerufen"] == "nicht dokumentiert" and "Abrufdatum und Stand der Quelle nicht dokumentiert" in r[
            "abgerufen_beleg"]
        assert _geojson(aus, ebene)["meta"]["abgerufen"] == "nicht dokumentiert"
    assert meta["raum"]["quartier"]["abgerufen"] == "2026-11-10T10:45:58+01:00"
    monkeypatch.setattr(strukturdaten_raum, "GEO_HERKUNFT", {
        hashlib.sha256(strukturdaten.geo_pfad(e).read_bytes()).hexdigest(): strukturdaten.geo_pfad(e).name
        for e in ("stadtteil", "stadtbezirk")})
    strukturdaten.write()
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    r = meta["raum"]["stadtteil"]
    assert r["abgerufen"] == "2026-11-04" and "explore/BERICHT_phase1.md" in r["abgerufen_beleg"]
    assert "data/geo/stadtteile_koeln.geojson in dieser Fassung" in r["abgerufen_beleg"]
    # die Prüfsummen in GEO_HERKUNFT sind die der Dateien unter data/geo, die mit Commit 3964836 kamen
    assert set(strukturdaten_raum.GEO_HERKUNFT.values()) == {"stadtteile_koeln.geojson", "stadtbezirke_koeln.geojson"}


def test_geheim_aber_ableitbar_gemeldet(umgebung):
    """Ist genau ein Wert einer geprüften Beziehung geheim und folgt er aus den veröffentlichten Werten derselben Zeile,
    zählt meta.json die Zeilen (geheimhaltung_ableitbar) und nennt sie im Hinweis; die Werte bleiben unverändert und
    nichts wird ausgerechnet."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)

    def nebenwohnsitz_geheim(daten):
        daten["F19"] = "*"    # 101010003 / 2025: Nebenwohnsitz geheim, Gesamt und Hauptwohnsitz veröffentlicht
        daten["E7"], daten["F7"] = "*", "*"   # 102 / 2025: zwei Werte der Summe geheim, nicht ableitbar
    xlsx_bauen(pfade["xlsx"], nebenwohnsitz_geheim)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    zeilen = meta["geheimhaltung_ableitbar"]["zeilen"]
    assert zeilen == [
        {"beziehung": "koeln_A0025A = koeln_A0355A + koeln_A0359A", "geheim": "koeln_A0359A",
         "aus": ["koeln_A0025A", "koeln_A0355A"], "raumebene": "quartier", "zeilen": 1},
        # G18 „*“ (Männer im Quartier 101010002, 2025), Anteil und Gesamtzahl veröffentlicht
        {"beziehung": "koeln_A0109P = 100 × koeln_A0109A / koeln_A0025A", "geheim": "koeln_A0109A",
         "aus": ["koeln_A0109P", "koeln_A0025A"], "raumebene": "quartier", "zeilen": 1}]
    assert "Summe koeln_A0025A = koeln_A0355A + koeln_A0359A" in meta["geheimhaltung_ableitbar"]["geprueft"]
    hinweis = meta["geheimhaltung_hinweis"]
    assert "In 2 Zeilen folgt ein geheim gehaltener Wert" in hinweis and "keine sekundäre Geheimhaltung" in hinweis
    assert "koeln_A0359A aus koeln_A0025A und koeln_A0355A: quartier 1" in hinweis
    werte = {(w["raum_id"], w["indikator_id"], w["jahr"]): w for w in _werte_quartier(aus)}
    assert (werte[("101010003", "koeln_A0359A", "2025")]["wert"], werte[("101010003", "koeln_A0359A", "2025")][
        "status"]) == ("", "geheim")
    assert {w["status"] for w in _werte_quartier(aus)} <= {"ok", "geheim", "fehlt"}


def test_dokumentation_vertrag_1_1():
    """TECHNIK.md, README und data/LICENSE-DATA.md passen zu Vertrag 1.1: Reihenfolge der Raumebenen mit quartier,
    quellobjekt auch für werte_quartier.tsv.gz, Datenstand der Quartiersgeometrie, Namensnennung des Datenkatalogs für
    audit_raumabgleich.tsv (Spalten in_werten und Namen aus dem Blatt Daten)."""
    root = config.ROOT
    technik = (root / "TECHNIK.md").read_text(encoding="utf-8")
    abschnitt = technik.split("### Strukturdaten", 1)[1].split("\n## ", 1)[0]
    schreibweise = next(z for z in abschnitt.splitlines() if z.startswith("- **Schreibweise**"))
    assert f"`{';'.join(strukturdaten.EBENEN_REIHENFOLGE)}`" in schreibweise
    assert "werte_quartier.tsv.gz" in schreibweise.split("`quellobjekt`", 1)[1]
    readme = (root / "README.md").read_text(encoding="utf-8").split("## Datenstand", 1)[1].split("\n## ", 1)[0]
    assert "Statistische Quartiere" in readme
    lizenz = (root / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8").splitlines()
    (zeile,) = [z for z in lizenz if z.startswith("| `strukturdaten/audit_raumabgleich.tsv`")]
    assert strukturdaten.KOELN_LIZENZ in zeile and "Statistischer Datenkatalog Köln" in zeile
    assert config.NAMENSNENNUNG in zeile
    (zeile,) = [z for z in lizenz if z.startswith("| `strukturdaten/zuordnung.tsv`")]
    assert "Datenlizenz Deutschland – Namensnennung" not in zeile
