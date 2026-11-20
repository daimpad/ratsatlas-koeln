"""Punkt aus der Ortsangabe der Stadt außerhalb aller Kölner Stadtteile (Entscheidung 19.11.2026 (4) (d) und (e)): Bei
einer Vorlage, die einen Punkt haben darf (Ortsangabe nicht in `grob`), verwirft build einen solchen Punkt; dann gilt die
Regel ohne Punkt: Stadtteil laut Stadt (subLocality) → Ebene Stadtteil, oparl_sublocality, mittel („Ort erkannt“), sonst
Ebene Straße, oparl_location, niedrig, ohne Koordinate und ohne Stadtteil („Ort unklar“). Ein Punkt in einem Stadtteil
bleibt „Ort genau“ (oparl_location, hoch), Ortsangaben ohne Erlaubnis bleiben wie bisher. Der verworfene Punkt steht in
keiner Datei und liefert keinen Straßenpunkt für den Gazetteer, auch nicht über den Stadtteil laut Stadt; das Log von
build nennt nur Zahlen; check meldet einen genauen Punkt der Stadt ohne Kölner Stadtteil
(check.punkte_der_stadt). Erfundene Vorlagen (tools/testdaten.py und eingefügte Vorlagen in den temporären Pfaden der
Fixture `oparl`); keine Anfragen an die Stadt."""
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from pipeline import build, check, config, export, kontext
from pipeline.geo import Ortsteile
from pipeline.geocode import Gazetteer

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"
EINGABE = "Anregungen und Beschwerden"   # Vorlagenart der Eingaben in tools/testdaten.py (ohne Hauskoordinate)
OHNE_ORT = "[Testdaten] Ergänzung ohne Ort"
UNBEKANNT = "Erfundener Außenweg"   # nicht im Straßenverzeichnis (geprüft in _einfuegen)
UNBEKANNT_ST = "Erfundener Randweg"   # ebenso, Straße der Ortsangabe mit verworfenem Punkt und Stadtteil laut Stadt
# erfundene Punkte außerhalb aller Kölner Stadtteile (geprüft in _einfuegen); auffällige Ziffern für die Suche in Dateien
AUSSEN = {"a": (6.123457, 51.234567), "b": (7.098765, 50.734567), "c": (6.654321, 50.876543),
          "d": (6.543219, 50.765437)}
LOG = ("Ortsangaben der Stadt mit Punkt außerhalb aller Kölner Stadtteile bei Vorlagen, die einen Punkt haben dürfen: "
       "{} (Punkt verworfen; davon mit Kölner Stadtteil laut Stadt {})\n")


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def testdaten(oparl, monkeypatch):
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "60"])
    _tool("testdaten").main()


def _id(key):
    return f"{B}/papers/pa-{key}"


def _ort(key, punkt, **felder):
    return {"id": f"{B}/locations/pa-{key}", **felder,
            "geojson": {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(punkt)}}}


def _vorlage(key, ref, titel=OHNE_ORT, art="Beschlussvorlage", location=()):
    return {"id": _id(key), "reference": ref, "name": titel, "paperType": art, "date": "2026-10-01",
            "web": "https://example.invalid/vorlage", "modified": "2026-10-01T10:00:00+02:00", "location": list(location),
            "consultation": [{"id": f"{B}/consultations/pa-{key}", "role": "Entscheidung",
                              "organization": [f"{B}/organizations/rat"], "authoritative": True}]}


def _einfuegen():
    """Erfundene Fälle; liefert den Punkt in einem Stadtteil (Hauskoordinate aus „Adressen Köln“) und dessen Stadtteil."""
    ortsteile = Ortsteile(config.ORTSTEILE)
    assert all(ortsteile.locate(*xy) is None for xy in AUSSEN.values())
    assert ortsteile.by_name("Ehrenfeld") and ortsteile.by_name("Nippes") and not ortsteile.by_name("Innenstadt")
    strassen = json.loads(config.STRASSEN.read_text())["streets"]
    assert UNBEKANNT not in strassen and UNBEKANNT_ST not in strassen
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    innen = tuple(next(iter(next(iter(hnr[strasse].values())).values())))
    ot = ortsteile.locate(*innen)
    assert ot
    ort_aus = _ort("aus", AUSSEN["a"], streetAddress=f"{UNBEKANNT} 3")
    faelle = [
        # erlaubt, Punkt außerhalb, ohne Stadtteil laut Stadt; eine zweite Vorlage nennt dieselbe Ortsangabe
        _vorlage("aus", "1801/2026", location=[ort_aus]),
        _vorlage("aus2", "1802/2026", location=[ort_aus]),
        # erlaubt, Punkt außerhalb, Stadtteil laut Stadt und eine Straße, die das Straßenverzeichnis nicht kennt
        _vorlage("aus_st", "1803/2026", location=[_ort("aus-st", AUSSEN["b"], subLocality="Ehrenfeld",
                                                       streetAddress=f"{UNBEKANNT_ST} 5")]),
        # erlaubt, Punkt außerhalb, subLocality ist ein Stadtbezirk, kein Stadtteil
        _vorlage("aus_bez", "1804/2026", location=[_ort("aus-bez", AUSSEN["c"], subLocality="Innenstadt")]),
        # erlaubt, Punkt in einem Stadtteil: unverändert „Ort genau“
        _vorlage("innen", "1805/2026", location=[_ort("innen", innen)]),
        # ohne Erlaubnis (Eingabe): unverändert, Punkt außerhalb ohne Koordinate bzw. Stadtteil laut Stadt
        _vorlage("grob", "1806/2026", art=EINGABE, location=[_ort("grob", AUSSEN["d"])]),
        _vorlage("grob_st", "1807/2026", art=EINGABE, location=[_ort("grob-st", AUSSEN["d"], subLocality="Nippes")]),
        # erlaubt, Straße nur aus einer Ortsangabe mit verworfenem Punkt bekannt: kein Straßenpunkt, ohne Stadtteil laut
        # Stadt (wie vorher) und mit ihm (sonst stünde die Straße auf dem Punkt der Stadtteilfläche)
        _vorlage("titel", "1808/2026", titel=f"[Testdaten] Neue Bank am {UNBEKANNT}"),
        _vorlage("titel_st", "1809/2026", titel=f"[Testdaten] Neue Bank am {UNBEKANNT_ST}"),
    ]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for p in faelle:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return innen, ot


def _orte(db, key):
    return {r for r in db.execute(
        "SELECT l.level, pl.method, pl.confidence, l.lon, l.lat, l.ortsteil FROM paper_location pl "
        "JOIN location l ON l.id = pl.location_id WHERE pl.paper_id = ?", (_id(key),))}


def _schwerpunkt(name):
    pt = Ortsteile(config.ORTSTEILE).by_name(name)[1]
    return round(pt.x, 6), round(pt.y, 6)


def test_punkt_ausserhalb_aller_stadtteile_verworfen(testdaten, capsys):
    innen, ot = _einfuegen()
    build.build()
    aus_build = capsys.readouterr().out
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    aus_check = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in aus_check
    db = sqlite3.connect(config.DB)
    erlaubt = check.erlaubnis(db)[0]
    assert erlaubt[_id("aus")] and erlaubt[_id("innen")] and not erlaubt[_id("grob")]
    # (d) und (e): ohne Stadtteil laut Stadt „Ort unklar“ ohne Koordinate und ohne Stadtteil, auch bei einem Stadtbezirk
    # als subLocality; mit Stadtteil laut Stadt „Ort erkannt“ mit der Stadtteilfläche (wie ohne Punkt)
    for key in ("aus", "aus2", "aus_bez"):
        assert _orte(db, key) == {("strasse", "oparl_location", "niedrig", None, None, None)}, key
    assert _orte(db, "aus_st") == {("ortsteil", "oparl_sublocality", "mittel", *_schwerpunkt("Ehrenfeld"), "Ehrenfeld")}
    # Punkt in einem Stadtteil: unverändert „Ort genau“ auf dem Punkt der Stadt
    assert _orte(db, "innen") == {("strasse", "oparl_location", "hoch", *innen, ot["ortsteil_bez"])}
    # ohne Erlaubnis unverändert
    assert _orte(db, "grob") == {("strasse", "oparl_location", "niedrig", None, None, None)}
    assert _orte(db, "grob_st") == {("ortsteil", "oparl_sublocality", "mittel", *_schwerpunkt("Nippes"), "Nippes")}
    # die Straße einer Ortsangabe mit verworfenem Punkt gibt keinem Titel einen Ort, auch nicht den Stadtteil laut Stadt
    assert _orte(db, "titel") == set() and _orte(db, "titel_st") == set()
    # Gegenprobe: Mit einem Straßenpunkt in einem Stadtteil erkennt der Gazetteer die Straße in diesem Titel
    gaz = Gazetteer(street_points=[(UNBEKANNT_ST, *innen)])
    assert [r for r in gaz.locate(f"[Testdaten] Neue Bank am {UNBEKANNT_ST}") if r["name"] == UNBEKANNT_ST]
    # kein verworfener Punkt in der Datenbank
    assert not [r for r in db.execute("SELECT lon, lat FROM location") if r in AUSSEN.values()]
    db.close()
    # Log: je Ortsangabe einmal (aus und aus2 teilen eine), Ortsangaben ohne Erlaubnis nicht gezählt; nur Zahlen
    assert LOG.format(3, 1) in aus_build
    zeile = next(z for z in aus_build.splitlines() if z.startswith("Ortsangaben der Stadt mit Punkt außerhalb"))
    assert UNBEKANNT not in zeile and "Ehrenfeld" not in zeile and "pa-" not in zeile and "1801" not in zeile
    # Exporte und Zwischenstände: kein verworfener Punkt in irgendeiner Datei (GeoJSON, Gebietsdateien, Audits, Suche …;
    # die Datenbank oben)
    dateien = {p: p.read_bytes() for d in (config.EXPORT, config.BUILD) for p in d.rglob("*") if p.is_file()}
    assert any(p.name == "vorlagen.geojson" for p in dateien) and any(p.suffix == ".tsv" for p in dateien)
    for lon, lat in AUSSEN.values():
        assert not [p for p, b in dateien.items() if str(lon).encode() in b or str(lat).encode() in b], (lon, lat)
    base = config.EXPORT / config.STADT
    geo = {f["properties"]["reference"]: f for f in json.loads((base / "vorlagen.geojson").read_text())["features"]
           if f["properties"]["reference"].startswith("18")}
    assert set(geo) == {"1803/2026", "1805/2026", "1807/2026"}
    assert (geo["1803/2026"]["properties"]["method"], geo["1803/2026"]["properties"]["ortsteil"],
            tuple(geo["1803/2026"]["geometry"]["coordinates"])) == ("oparl_sublocality", "Ehrenfeld",
                                                                    _schwerpunkt("Ehrenfeld"))
    assert (geo["1805/2026"]["properties"]["method"], geo["1805/2026"]["properties"]["confidence"],
            tuple(geo["1805/2026"]["geometry"]["coordinates"])) == ("oparl_location", "hoch", innen)
    # Gebietsdateien: die Vorlagen mit verworfenem Punkt ohne Stadtteil stehen bei den Vorlagen ohne Ortsbezug, ohne
    # Koordinate
    ohne = {p["reference"]: p for d in ("ohne-ortsbezug",) for f in (base / d).glob("*.json")
            for p in json.loads(f.read_text())["papers"]}
    for ref in ("1801/2026", "1802/2026", "1804/2026"):
        assert [(x["method"], x["confidence"], x["lon"], x["ortsteil"]) for x in ohne[ref]["locations"]] == [
            ("oparl_location", "niedrig", None, None)], ref
    assert ohne["1808/2026"]["locations"] == [] and ohne["1809/2026"]["locations"] == []
    # check: der Schutz zählt den genauen Punkt der Stadt in einem Stadtteil, ohne Befund
    assert ("Punkte aus der Ortsangabe der Stadt als „Ort genau“ (oparl_location, hoch) ohne Punkt in einem Kölner "
            "Stadtteil (Entscheidung 19.11.2026 (4) (d)): Datenbank 0 von 1, vorlagen.geojson 0 von 1\n") in aus_check


def test_pruefung_meldet_genauen_punkt_ausserhalb(testdaten, tmp_path, capsys):
    """check.punkte_der_stadt: ein genauer Punkt der Stadt (oparl_location, hoch) ohne Stadtteil oder außerhalb aller
    Kölner Stadtteile ist ein Befund, in der Datenbank und in vorlagen.geojson; der Befund nennt nur Zahlen."""
    innen, _ = _einfuegen()
    build.build()
    export.export()
    capsys.readouterr()
    base = config.EXPORT / config.STADT

    def pruefen(aendern):
        kopie, db_kopie = tmp_path / "exp", tmp_path / "db.sqlite"
        shutil.rmtree(kopie, ignore_errors=True)
        shutil.copytree(base, kopie)
        shutil.copy(config.DB, db_kopie)
        db = sqlite3.connect(db_kopie)
        aendern(db, kopie)
        db.commit()
        befunde = check.punkte_der_stadt(db, kopie)
        db.close()
        return befunde

    assert pruefen(lambda db, k: None) == []
    db = sqlite3.connect(config.DB)
    assert check.gebiete(db) == ([], [])
    db.close()
    text = "Gebiete: Punkt aus der Ortsangabe der Stadt als „Ort genau“ ohne Punkt in einem Kölner Stadtteil (build " \
           "verwirft ihn, Entscheidung 19.11.2026 (4) (d)): "

    def db_aussen(db, _):   # früherer Aufbau: Punkt außerhalb mit hoch, ohne Stadtteil
        db.execute("UPDATE location SET lon = ?, lat = ?, ortsteil = NULL WHERE id = ?",
                   (*AUSSEN["a"], f"{B}/locations/pa-innen"))

    assert pruefen(db_aussen) == [text + "Datenbank 1"]

    def db_ohne_stadtteil(db, _):   # Punkt im Stadtteil, aber ohne Stadtteil
        db.execute("UPDATE location SET ortsteil = NULL WHERE id = ?", (f"{B}/locations/pa-innen",))

    assert pruefen(db_ohne_stadtteil) == [text + "Datenbank 1"]

    def geo_aussen(db, k):
        doc = json.loads((k / "vorlagen.geojson").read_text())
        for f in doc["features"]:
            if f["properties"]["reference"] == "1805/2026":
                f["geometry"]["coordinates"] = list(AUSSEN["b"])
                f["properties"]["ortsteil"] = None
        (k / "vorlagen.geojson").write_text(json.dumps(doc, ensure_ascii=False))

    assert pruefen(geo_aussen) == [text + "vorlagen.geojson 1"]

    def beides(db, k):
        db_aussen(db, k)
        geo_aussen(db, k)

    befunde = pruefen(beides)
    assert befunde == [text + "Datenbank 1, vorlagen.geojson 1"]
    assert "1805" not in befunde[0] and "pa-" not in befunde[0] and str(innen[0]) not in befunde[0]
