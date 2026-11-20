"""Stadtbezirk aus der beratenden Bezirksvertretung auch bei nur unklarem Ort der Stadt (Entscheidung 20.11.2026 (5),
Antwort „A“ auf 20.11.2026 (1) (d)): Ein unklarer Ort der Stadt (Ortsangabe ohne Kölner Stadtteil laut Stadt und ohne
Punkt in einem Kölner Stadtteil) zählt für `district_from_committee` wie kein Ort. Zeigen alle Ortsbezüge einer Vorlage
auf solche Orte (eigene oder vererbte) und hat genau eine Bezirksvertretung eines Kölner Stadtbezirks beraten, erhält
sie deren Stadtbezirk (Konfidenz niedrig), bei jeder Vorlagenart, auch bei einer Eingabe; der Ortsbezug auf den
unklaren Ort bleibt stehen. Mit zwei oder keiner Bezirksvertretung bleibt sie unter „ohne Ortsbezug“, mit einem anderen
Ortsbezug unverändert. Regel und Zählung im Log von build nutzen dieselbe Menge (build._nur_unklarer_ort). Erfundene
Vorlagen (tools/testdaten.py und eingefügte Vorlagen in den temporären Pfaden der Fixture `oparl`); keine Anfragen an
die Stadt."""
import csv
import importlib.util
import json
import re
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
AUSSEN = (6.123457, 51.234567)   # erfundener Punkt außerhalb aller Kölner Stadtteile (geprüft in _einfuegen)
UNKLAR = ("strasse", "oparl_location", "niedrig", None, None, None, None)
LOG_UNKLAR = ("Vorlagen nur mit unklarem Ort der Stadt (alle Ortsbezüge auf Ortsangaben der Stadt ohne Kölner Stadtteil "
              "laut Stadt und ohne Punkt in einem Kölner Stadtteil; unter „ohne Ortsbezug“, außer denen ohne Datum und "
              "denen mit Stadtbezirk aus der beratenden Bezirksvertretung): {}; davon ohne Datum (in keiner Jahresdatei "
              "„ohne Ortsbezug“): {}; davon in genau einer Bezirksvertretung eines Kölner Stadtbezirks beraten "
              "(erhalten district_from_committee, Entscheidung 20.11.2026 (5)): {}\n")
LOG_GREMIUM = re.compile(r"^Stadtbezirk aus der beratenden Bezirksvertretung: (\d+) Vorlagen; davon nur mit unklarem "
                         r"Ort der Stadt \(Entscheidung 20\.11\.2026 \(5\)\): (\d+)$", re.M)


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
    return f"{B}/papers/sb-{key}"


def _ort(key, punkt=None, **felder):
    ort = {"id": f"{B}/locations/sb-{key}", **felder}
    if punkt:
        ort["geojson"] = {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(punkt)}}
    return ort


def _vorlage(key, ref, titel=OHNE_ORT, art="Beschlussvorlage", location=(), gremien=("rat",), **felder):
    return {"id": _id(key), "reference": ref, "name": titel, "paperType": art, "date": "2026-10-01",
            "web": "https://example.invalid/vorlage", "modified": "2026-10-01T10:00:00+02:00", "location": list(location),
            "consultation": [{"id": f"{B}/consultations/sb-{key}-{k}", "role": "Beratung",
                              "organization": [f"{B}/organizations/{g}"]} for k, g in enumerate(gremien)], **felder}


# Gremien aus tools/testdaten.py: bv3 Lindenthal, bv4 Ehrenfeld, bv5 Nippes, bv7 Porz, bv8 Kalk
FAELLE = [
    # nur ein unklarer Ort der Stadt, genau eine Bezirksvertretung
    _vorlage("bv", "1701/2026", location=[_ort("bv", description="Erfundener Platz")], gremien=("bv4", "rat")),
    # nur ein unklarer Ort der Stadt, keine Bezirksvertretung; übergeordnete Vorlage von „kind“
    _vorlage("eltern", "1702/2026", location=[_ort("eltern", description="Erfundener Hof")]),
    # ohne eigenen Ort, erbt den unklaren Ort, genau eine Bezirksvertretung
    _vorlage("kind", "1703/2026", gremien=("bv5",), superordinatedPaper=[_id("eltern")]),
    # nur ein unklarer Ort der Stadt, zwei Bezirksvertretungen
    _vorlage("zwei", "1704/2026", location=[_ort("zwei")], gremien=("bv4", "bv5")),
    # unklarer Ort der Stadt und ein Stadtteil im Titel (Stufe B), genau eine Bezirksvertretung: unverändert
    _vorlage("titel", "1705/2026", titel="[Testdaten] Spielplatz in Sülz", location=[_ort("titel")], gremien=("bv3",)),
    # unklarer Ort der Stadt und eine Ortsangabe der Stadt mit Stadtteil (Stufe A), genau eine Bezirksvertretung
    _vorlage("stadtteil", "1706/2026", location=[_ort("st-u"), _ort("st-n", subLocality="Nippes")], gremien=("bv5",)),
    # Eingabe (ohne Erlaubnis für Hauskoordinaten): Punkt außerhalb aller Stadtteile ohne Stadtteil laut Stadt,
    # genau eine Bezirksvertretung
    _vorlage("eingabe", "1707/2026", art=EINGABE, location=[_ort("eingabe", AUSSEN, description="Erfundene Ecke")],
             gremien=("bv7",)),
    # nur ein unklarer Ort der Stadt, ohne Datum, genau eine Bezirksvertretung
    _vorlage("datum", "1708/2026", location=[_ort("datum", description="Erfundener Steg")], gremien=("bv8",), date=None),
]


def _einfuegen():
    assert Ortsteile(config.ORTSTEILE).locate(*AUSSEN) is None
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for p in FAELLE:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def _orte(db, key):
    return {r for r in db.execute(
        "SELECT l.level, pl.method, pl.confidence, l.lon, l.lat, l.ortsteil, l.stadtbezirk FROM paper_location pl "
        "JOIN location l ON l.id = pl.location_id WHERE pl.paper_id = ?", (_id(key),))}


def _bezirk(db, name):
    ort = db.execute("SELECT lon, lat FROM location WHERE level = 'stadtbezirk' AND stadtbezirk = ?",
                     (name,)).fetchone()
    assert ort, f"kein Ort auf Ebene Stadtbezirk für {name}"
    lon, lat = ort
    return ("stadtbezirk", "district_from_committee", "niedrig", lon, lat, None, name)


def _kette(capsys):
    _einfuegen()
    build.build()
    aus_build = capsys.readouterr().out
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    assert "Alle Prüfungen durchgeführt, keine Befunde." in capsys.readouterr().out
    return aus_build


def test_stadtbezirk_bei_nur_unklarem_ort(testdaten, capsys):
    aus_build = _kette(capsys)
    db = sqlite3.connect(config.DB)
    assert not check.erlaubnis(db)[0][_id("eingabe")] and check.erlaubnis(db)[0][_id("bv")]
    # genau eine Bezirksvertretung: Stadtbezirk dazu, der unklare Ort bleibt; vererbt ebenso; auch ohne Datum
    assert _orte(db, "bv") == {UNKLAR, _bezirk(db, "Ehrenfeld")}
    assert _orte(db, "kind") == {("strasse", "vererbt", "niedrig", None, None, None, None), _bezirk(db, "Nippes")}
    assert _orte(db, "datum") == {UNKLAR, _bezirk(db, "Kalk")}
    # Eingabe: nur der Stadtbezirk, kein Stadtteil und kein Punkt außer dem des Stadtbezirks
    assert _orte(db, "eingabe") == {UNKLAR, _bezirk(db, "Porz")}
    # keine oder zwei Bezirksvertretungen: unverändert nur der unklare Ort
    assert _orte(db, "eltern") == {UNKLAR} and _orte(db, "zwei") == {UNKLAR}
    # mit einem anderen Ortsbezug unverändert, ohne district_from_committee
    titel = _orte(db, "titel")
    assert UNKLAR in titel and [r for r in titel if r[1] == "ortsteil_name" and r[5] == "Sülz"]
    assert {r[1] for r in titel} == {"oparl_location", "ortsteil_name"}
    stadtteil = _orte(db, "stadtteil")
    assert {r[:3] + r[5:] for r in stadtteil} == {UNKLAR[:3] + UNKLAR[5:],
                                                  ("ortsteil", "oparl_sublocality", "mittel", "Nippes", "Nippes")}
    # Fundstelle wie bei den übrigen Vorlagen mit district_from_committee
    assert db.execute("SELECT evidence FROM paper_location WHERE paper_id = ? AND method = 'district_from_committee'",
                      (_id("bv"),)).fetchall() == [("nur in der Bezirksvertretung Ehrenfeld beraten",)]
    n_gremium = db.execute("SELECT COUNT(DISTINCT paper_id) FROM paper_location "
                           "WHERE method = 'district_from_committee'").fetchone()[0]
    db.close()

    # Export: unter dem Stadtbezirk, nicht unter „ohne Ortsbezug“; die übrigen dort wie bisher
    base = config.EXPORT / config.STADT
    ohne = {p["reference"] for f in (base / "ohne-ortsbezug").glob("*.json")
            for p in json.loads(f.read_text())["papers"] if p["reference"].startswith("17")}
    assert ohne == {"1702/2026", "1704/2026"}

    def im_bezirk(name):
        doc = json.loads((base / "bezirke" / f"{export.slug(name)}.json").read_text())
        return {p["reference"]: p for p in doc["papers"] if p["reference"].startswith("17")}

    assert set(im_bezirk("Ehrenfeld")) == {"1701/2026"} and set(im_bezirk("Nippes")) == {"1703/2026"}
    assert set(im_bezirk("Porz")) == {"1707/2026"} and set(im_bezirk("Kalk")) == {"1708/2026"}
    assert not im_bezirk("Lindenthal")
    orte = [(x["level"], x["method"], x["confidence"], x["ortsteil"], x["stadtbezirk"])
            for x in im_bezirk("Ehrenfeld")["1701/2026"]["locations"]]
    assert orte == [("strasse", "oparl_location", "niedrig", None, None),
                    ("stadtbezirk", "district_from_committee", "niedrig", None, "Ehrenfeld")]
    index = json.loads((base / "index.json").read_text())
    assert {b["name"] for b in index["bezirke"]} >= {"Ehrenfeld", "Nippes", "Porz", "Kalk"}
    # vorlagen.geojson: je Vorlage genau der Punkt des Stadtbezirks, wie bei den übrigen Vorlagen mit
    # district_from_committee; kein Punkt für die Eingabe außer ihm
    features = json.loads((base / "vorlagen.geojson").read_text())["features"]
    geo = {}
    for f in features:
        geo.setdefault(f["properties"]["reference"], []).append(f)
    for ref, name in (("1701/2026", "Ehrenfeld"), ("1703/2026", "Nippes"), ("1707/2026", "Porz"),
                      ("1708/2026", "Kalk")):
        assert [(f["properties"]["method"], f["properties"]["confidence"], f["properties"]["ortsteil"],
                 f["properties"]["stadtbezirk"]) for f in geo[ref]] == [
            ("district_from_committee", "niedrig", None, name)], ref
    gremium_geo = [f["properties"] for f in features if f["properties"]["method"] == "district_from_committee"]
    assert [x for x in gremium_geo if not x["reference"].startswith("17")]   # Vergleich mit Vorlagen der Testdaten
    assert {(x["stage"], x["location_source"], x["confidence"], x["ortsteil"]) for x in gremium_geo} == {
        ("B", config.QUELLE_GEO, "niedrig", None)}
    assert not [r for r in geo if r in ("1702/2026", "1704/2026")]
    dateien = {p: p.read_bytes() for d in (config.EXPORT, config.BUILD) for p in d.rglob("*") if p.is_file()}
    assert not [p for p, b in dateien.items() if str(AUSSEN[0]).encode() in b or str(AUSSEN[1]).encode() in b]
    # Audit: Prüfstatus wie bei den übrigen Vorlagen mit district_from_committee
    with open(config.EXPORT / "audit_geokodierung.tsv", encoding="utf-8") as f:
        audit = list(csv.DictReader(f, delimiter="\t"))
    gremium = [r for r in audit if r["methode"] == "district_from_committee"]
    assert {r["pruefstatus"] for r in gremium} == {"ungeprüft"}
    assert {(r["drucksache"], r["ebene"], r["stadtbezirk"], r["konfidenz"]) for r in gremium
            if r["drucksache"].startswith("17")} == {
        ("1701/2026", "stadtbezirk", "Ehrenfeld", "niedrig"), ("1703/2026", "stadtbezirk", "Nippes", "niedrig"),
        ("1707/2026", "stadtbezirk", "Porz", "niedrig"), ("1708/2026", "stadtbezirk", "Kalk", "niedrig")}

    # Log: nur Zahlen; nur unklarer Ort bei bv, eltern, kind, zwei, eingabe und datum, davon ohne Datum datum, mit
    # genau einer Bezirksvertretung bv, kind, eingabe und datum; dieselben vier zählt die Zeile von _from_committee
    assert LOG_UNKLAR.format(6, 1, 4) in aus_build
    treffer = LOG_GREMIUM.findall(aus_build)
    assert treffer == [(str(n_gremium), "4")]
    for anfang in ("Vorlagen nur mit unklarem Ort", "Stadtbezirk aus der beratenden"):
        zeilen = [z for z in aus_build.splitlines() if z.startswith(anfang)]
        assert len(zeilen) == 1, anfang
        assert not [x for x in ("Ehrenfeld", "Nippes", "Porz", "Kalk", "Erfunden", "sb-", "17")
                    if x in zeilen[0]], anfang


def test_menge_nur_unklarer_ort():
    """Die Menge für _from_committee und die Zeile im Log (_nur_unklarer_ort): eigene und vererbte Ortsbezüge, alle auf
    einen Ort der Stadt ohne Stadtteil und ohne Koordinate; ein weiterer Ortsbezug mit Stadtteil oder aus einer anderen
    Quelle nimmt die Vorlage heraus."""
    q = config.QUELLE_OPARL
    locations = {
        "u": ("u", None, None, None, "Erfundener Platz", None, None, None, None, None, "strasse", q),
        "st": ("st", None, None, "Nippes", None, 6.9, 50.9, "Nippes", 501, "Nippes", "ortsteil", q),
        "g": ("g", "Erfundene Straße", None, None, "Erfundene Straße", 6.9, 50.9, "Nippes", 501, "Nippes", "strasse",
              config.QUELLE_GEO),
    }
    ploc = [("a", "u", "A", "oparl_location", "niedrig", "", "a"),
            ("b", "u", "B", "vererbt", "niedrig", "", "x"),
            ("c", "u", "A", "oparl_location", "niedrig", "", "c"), ("c", "st", "A", "oparl_sublocality", "mittel", "", "c"),
            ("d", "u", "A", "oparl_location", "niedrig", "", "d"), ("d", "g", "B", "strasse", "mittel", "", "d")]
    assert build._nur_unklarer_ort(ploc, locations) == {"a", "b"}
