"""Straßenpunkte aus den Ortsangaben der Stadt (Entscheidung 20.11.2026 (1) (b)) und Vorlagen nur mit unklarem Ort der
Stadt (20.11.2026 (1) (d)). (b): Nur eine Ortsangabe mit einem Punkt der Stadt in einem Kölner Stadtteil liefert dem
Gazetteer einen Straßenpunkt für eine Straße, die das Straßenverzeichnis nicht kennt; eine Ortsangabe ohne eigenen Punkt,
deren Zeile nur den Punkt der Stadtteilfläche trägt, liefert keinen mehr (vorher stand ein Titel mit dieser Straße auf
Ebene Straße am Punkt der Stadtteilfläche, bei einer Vorlage ohne Erlaubnis für Hauskoordinaten auf Ebene Stadtteil).
Ortsangaben ohne Erlaubnis (`grob`) bleiben wie bisher. Das Log von build zählt die Straßennamen, die so wegfallen. (d):
Das Log zählt die Vorlagen, deren Ortsbezüge alle auf eine Ortsangabe der Stadt ohne Kölner Stadtteil laut Stadt und
ohne Punkt in einem Kölner Stadtteil zeigen, davon die ohne Datum und die mit genau einer beratenden
Bezirksvertretung; diese erhalten seit 20.11.2026 (5) district_from_committee (ausführlich in
tests/test_stadtbezirk_unklarer_ort.py). Erfundene Vorlagen (tools/testdaten.py und eingefügte Vorlagen in den
temporären Pfaden der Fixture `oparl`); keine Anfragen an die Stadt."""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from pipeline import build, check, config, export, kontext
from pipeline.geo import Ortsteile

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"
EINGABE = "Anregungen und Beschwerden"   # Vorlagenart der Eingaben in tools/testdaten.py (ohne Hauskoordinate)
OHNE_ORT = "[Testdaten] Ergänzung ohne Ort"
# erfundene Straßen, die das Straßenverzeichnis nicht kennt (geprüft in _einfuegen)
FLAECHE = "Erfundener Flächenweg"   # nur aus Ortsangaben ohne eigenen Punkt (Stadtteil laut Stadt)
PUNKT = "Erfundener Punktweg"       # aus einer Ortsangabe mit Punkt der Stadt, dazu eine ohne Punkt davor
SCHUTZ = "Erfundener Schutzweg"     # nur aus der Ortsangabe einer Eingabe (grob), mit Punkt
VERWORFEN = "Erfundener Verwurfweg"   # nur aus einer Ortsangabe mit verworfenem Punkt und Stadtteil laut Stadt
NAMEN = (FLAECHE, PUNKT, SCHUTZ, VERWORFEN)
AUSSEN = (6.123457, 51.234567)   # erfundener Punkt außerhalb aller Kölner Stadtteile (geprüft in _einfuegen)
LOG_B = ("Straßennamen nur aus Ortsangaben der Stadt ohne eigenen Punkt (Punkt der Stadtteilfläche), die der Gazetteer "
         "bisher als Straßenpunkt aufnahm und jetzt nicht mehr kennt (nicht im Straßenverzeichnis, je Name einmal): {}\n")
LOG_D = ("Vorlagen nur mit unklarem Ort der Stadt (alle Ortsbezüge auf Ortsangaben der Stadt ohne Kölner Stadtteil "
         "laut Stadt und ohne Punkt in einem Kölner Stadtteil; unter „ohne Ortsbezug“, außer denen ohne Datum und "
         "denen mit Stadtbezirk aus der beratenden Bezirksvertretung): {}; davon ohne Datum (in keiner Jahresdatei "
         "„ohne Ortsbezug“): {}; davon in genau einer Bezirksvertretung eines Kölner Stadtbezirks beraten (erhalten "
         "district_from_committee, Entscheidung 20.11.2026 (5)): {}\n")
LOG_AUSSEN = ("Ortsangaben der Stadt mit Punkt außerhalb aller Kölner Stadtteile bei Vorlagen, die einen Punkt haben "
              "dürfen: {} (Punkt verworfen; davon mit Kölner Stadtteil laut Stadt {})\n")


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
    return f"{B}/papers/sp-{key}"


def _ort(key, punkt=None, **felder):
    ort = {"id": f"{B}/locations/sp-{key}", **felder}
    if punkt:
        ort["geojson"] = {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(punkt)}}
    return ort


def _vorlage(key, ref, titel=OHNE_ORT, art="Beschlussvorlage", location=(), gremien=("rat",), **felder):
    return {"id": _id(key), "reference": ref, "name": titel, "paperType": art, "date": "2026-10-01",
            "web": "https://example.invalid/vorlage", "modified": "2026-10-01T10:00:00+02:00", "location": list(location),
            "consultation": [{"id": f"{B}/consultations/sp-{key}-{k}", "role": "Beratung",
                              "organization": [f"{B}/organizations/{g}"]} for k, g in enumerate(gremien)], **felder}


def _einfuegen():
    """Erfundene Fälle; liefert den Punkt der Stadt in einem Stadtteil (Hauskoordinate aus „Adressen Köln“), dessen
    Stadtteil und eine Straße des Straßenverzeichnisses."""
    ortsteile = Ortsteile(config.ORTSTEILE)
    assert ortsteile.locate(*AUSSEN) is None
    strassen = json.loads(config.STRASSEN.read_text())["streets"]
    assert not [n for n in NAMEN if n in strassen]
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    assert strasse in strassen
    innen = tuple(next(iter(next(iter(hnr[strasse].values())).values())))
    ot = ortsteile.locate(*innen)
    assert ot and ot["ortsteil_bez"] != "Nippes"
    unklar = _ort("u-bv", description="Erfundener Platz")
    faelle = [
        # (b) erlaubt, ohne eigenen Punkt, Stadtteil laut Stadt: zweimal dieselbe unbekannte Straße (zählt einmal)
        _vorlage("fl", "1901/2026", location=[_ort("fl", subLocality="Ehrenfeld", streetAddress=f"{FLAECHE} 4")]),
        _vorlage("fl3", "1902/2026", location=[_ort("fl3", subLocality="Nippes", streetAddress=f"{FLAECHE} 10")]),
        # dieselbe Straße ohne eigenen Punkt vor der Ortsangabe mit Punkt der Stadt (zählt nicht; vorher galt der
        # Punkt der Stadtteilfläche, weil er zuerst kam)
        _vorlage("fl2", "1903/2026", location=[_ort("fl2", subLocality="Nippes", streetAddress=f"{PUNKT} 9")]),
        _vorlage("pt", "1904/2026", location=[_ort("pt", innen, streetAddress=f"{PUNKT} 6")]),
        # Straße des Verzeichnisses ohne eigenen Punkt (zählt nicht)
        _vorlage("dir", "1905/2026", location=[_ort("dir", subLocality="Nippes", streetAddress=f"{strasse} 3")]),
        # ohne Erlaubnis (Eingabe) mit Punkt in einem Stadtteil: unverändert nur Stadtteil, kein Straßenpunkt
        _vorlage("grob", "1906/2026", art=EINGABE, location=[_ort("grob", innen, streetAddress=f"{SCHUTZ} 8")]),
        # erlaubt, Punkt außerhalb verworfen, Stadtteil laut Stadt (zählt nicht, schon vorher kein Straßenpunkt)
        _vorlage("verw", "1907/2026", location=[_ort("verw", AUSSEN, subLocality="Nippes",
                                                     streetAddress=f"{VERWORFEN} 2")]),
        # Titel erlaubter Vorlagen mit diesen Straßen
        *[_vorlage(f"titel-{k}", f"191{k}/2026", titel=f"[Testdaten] Neue Bank am {n}") for k, n in enumerate(NAMEN)],
        # Titel einer Eingabe (ohne Erlaubnis) mit der Straße nur aus Ortsangaben ohne eigenen Punkt, eine
        # Bezirksvertretung (vorher Ebene Stadtteil über _stadtteil_statt_stadtpunkt)
        _vorlage("e-fl", "1914/2026", titel=f"[Testdaten] Neue Bank am {FLAECHE}", art=EINGABE, gremien=("bv4",)),
        # (d) nur ein unklarer Ort der Stadt: eine, keine, zwei Bezirksvertretungen; vererbt; mit Stadtteil im Titel
        _vorlage("u-bv", "1921/2026", location=[unklar], gremien=("bv4",)),
        _vorlage("u-rat", "1922/2026", location=[_ort("u-rat", description="Erfundener Platz")]),
        _vorlage("u-zwei", "1923/2026", location=[_ort("u-zwei")], gremien=("bv4", "bv5")),
        _vorlage("u-kind", "1924/2026", gremien=("bv4",), superordinatedPaper=[_id("u-bv")]),
        _vorlage("u-titel", "1925/2026", titel="[Testdaten] Spielplatz in Sülz", location=[_ort("u-titel")],
                 gremien=("bv3",)),
        # verworfener Punkt außerhalb aller Stadtteile ohne Stadtteil laut Stadt, eine Bezirksvertretung; ohne Datum
        _vorlage("u-aussen", "1926/2026", location=[_ort("u-aussen", AUSSEN)], gremien=("bv4",)),
        _vorlage("u-datum", "1927/2026", location=[_ort("u-datum", description="Erfundener Platz")], date=None),
    ]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for p in faelle:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return innen, ot


def _orte(db, key):
    return {r for r in db.execute(
        "SELECT l.level, pl.method, l.lon, l.lat, l.ortsteil FROM paper_location pl "
        "JOIN location l ON l.id = pl.location_id WHERE pl.paper_id = ?", (_id(key),))}


def _schwerpunkt(name):
    pt = Ortsteile(config.ORTSTEILE).by_name(name)[1]
    return round(pt.x, 6), round(pt.y, 6)


def test_strassenpunkte_nur_aus_punkten_der_stadt(testdaten, capsys):
    innen, ot = _einfuegen()
    build.build()
    aus_build = capsys.readouterr().out
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    assert "Alle Prüfungen durchgeführt, keine Befunde." in capsys.readouterr().out
    db = sqlite3.connect(config.DB)
    erlaubt = check.erlaubnis(db)[0]
    assert all(erlaubt[_id(k)] for k in ("fl", "pt", "titel-0", "titel-1", "titel-2", "u-bv", "u-aussen"))
    assert not erlaubt[_id("grob")] and not erlaubt[_id("e-fl")]
    # die Ortsangaben selbst unverändert: ohne eigenen Punkt die Stadtteilfläche, mit Punkt der Stadt „Ort genau“
    assert _orte(db, "fl") == {("ortsteil", "oparl_sublocality", *_schwerpunkt("Ehrenfeld"), "Ehrenfeld")}
    assert _orte(db, "pt") == {("strasse", "oparl_location", *innen, ot["ortsteil_bez"])}
    assert _orte(db, "grob") == {("ortsteil", "oparl_sublocality", *_schwerpunkt(ot["ortsteil_bez"]),
                                  ot["ortsteil_bez"])}
    # (b) eine Straße nur aus Ortsangaben ohne eigenen Punkt gibt dem Titel keinen Ort mehr (vorher Ebene Straße am Punkt
    # der Stadtteilfläche)
    assert _orte(db, "titel-0") == set()
    # mit Punkt der Stadt weiter der Straßenpunkt, auch wenn eine Ortsangabe ohne Punkt dieselbe Straße vorher nennt
    assert _orte(db, "titel-1") == {("strasse", "strasse", *innen, ot["ortsteil_bez"])}
    # ohne Erlaubnis und mit verworfenem Punkt wie bisher kein Straßenpunkt
    assert _orte(db, "titel-2") == set() and _orte(db, "titel-3") == set()
    # auch eine Vorlage ohne Erlaubnis bekommt über die Straße nur aus Ortsangaben ohne eigenen Punkt keinen
    # Stadtteil mehr; mit genau einer Bezirksvertretung gilt dann district_from_committee (Stadtbezirk Ehrenfeld)
    assert {r[:2] + r[4:] for r in _orte(db, "e-fl")} == {("stadtbezirk", "district_from_committee", None)}
    assert db.execute("SELECT l.stadtbezirk FROM paper_location pl JOIN location l ON l.id = pl.location_id "
                      "WHERE pl.paper_id = ?", (_id("e-fl"),)).fetchall() == [("Ehrenfeld",)]
    # (d) der unklare Ort der Stadt bleibt; mit genau einer Bezirksvertretung (bv4) dazu district_from_committee
    # (Entscheidung 20.11.2026 (5)), auch vererbt und mit verworfenem Punkt; mit keiner oder zwei nicht
    unklar = ("strasse", "oparl_location", None, None, None)
    bezirk = {("stadtbezirk", "district_from_committee", r[2], r[3], None) for r in _orte(db, "e-fl")}
    for key in ("u-rat", "u-zwei", "u-datum"):
        assert _orte(db, key) == {unklar}, key
    for key in ("u-bv", "u-aussen"):
        assert _orte(db, key) == {unklar} | bezirk, key
    assert _orte(db, "u-kind") == {("strasse", "vererbt", None, None, None)} | bezirk
    assert [r for r in _orte(db, "u-titel") if r[:2] == ("ortsteil", "ortsteil_name") and r[4] == "Sülz"]
    assert {r[0] for r in db.execute("SELECT paper_id FROM paper_location WHERE method = 'district_from_committee' "
                                     "AND paper_id LIKE ?", (f"{B}/papers/sp-%",))} == {
        _id(k) for k in ("e-fl", "u-bv", "u-kind", "u-aussen")}
    db.close()
    # Log: nur Zahlen; (b) FLAECHE einmal (fl und fl3); verworfene Punkte verw (mit Stadtteil laut Stadt) und u-aussen;
    # (d) u-bv, u-rat, u-zwei, u-kind, u-aussen und u-datum, davon ohne Datum u-datum, mit genau einer
    # Bezirksvertretung u-bv, u-kind und u-aussen
    assert LOG_B.format(1) in aus_build and LOG_AUSSEN.format(2, 1) in aus_build and LOG_D.format(6, 1, 3) in aus_build
    for anfang in ("Straßennamen nur aus Ortsangaben", "Vorlagen nur mit unklarem Ort"):
        zeilen = [z for z in aus_build.splitlines() if z.startswith(anfang)]
        assert len(zeilen) == 1, anfang
        assert not [x for x in (*NAMEN, "Ehrenfeld", "Nippes", "Sülz", "sp-", "19", "Platz") if x in zeilen[0]], anfang
    # dieselben Vorlagen mit Datum und ohne genau eine Bezirksvertretung stehen auf der Seite unter „ohne Ortsbezug“;
    # jede dort mit Ortsbezug ist eine von ihnen
    base = config.EXPORT / config.STADT
    ohne = {p["reference"]: p for f in (base / "ohne-ortsbezug").glob("*.json")
            for p in json.loads(f.read_text())["papers"]}
    mit_ort = {ref for ref, p in ohne.items() if p["locations"]}
    assert mit_ort == {"1922/2026", "1923/2026"}
    assert ohne["1910/2026"]["locations"] == []
    # die Vorlage ohne Datum steht in keiner Jahresdatei „ohne Ortsbezug“ (darum eigens gezählt)
    assert "1927/2026" not in ohne
