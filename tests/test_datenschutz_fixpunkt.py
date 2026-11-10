"""Menge ohne Hauskoordinate als Fixpunkt (Prüfung r19, Runde 19b): eine Funktion (geocode.sperrmenge) für den Aufbau
(build.build) und die Prüfung (check.erlaubnis), abwechselnd über Beziehungen (über- und untergeordnet, relatedPaper)
und dieselbe Drucksache, bis nichts mehr hinzukommt; keine vererbte Hauskoordinate bei gesperrten Vorlagen
(build._inherited), kein genauer Punkt aus OParl-Ortsangaben gesperrter Vorlagen (Stufe A), keine Hauskoordinate neben
einem Titel, den maske.py ohne Hausnummer zeigt (Bauordnung, Naturschutz, Einwohnerschaft), und die Prüfung meldet
OParl-Punkte und Ortsnamen mit Hausnummer. Erfundene Vorlagen (tools/testdaten.py und eingefügte Vorlagen in den
temporären Pfaden der Fixture `oparl`); keine Anfragen an die Stadt."""
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from pipeline import build, check, config, export, geocode, kontext

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"
PUNKT, STRASSE_HNR = "strasse+hausnummer_punkt", "strasse+hausnummer"
EINGABE = "Anregungen und Beschwerden"
OHNE_ORT = "[Testdaten] Ergänzung ohne Ort"
UNBEKANNT = "Erfundener Prüfweg"   # nicht im Straßenverzeichnis (geprüft in _lage)


# --- geocode.sperrmenge -----------------------------------------------------------------------------------------------

def test_sperrmenge_fixpunkt():
    """Abwechselnd Beziehungen und dieselbe Drucksache, bis nichts mehr hinzukommt; der Weg je Vorlage."""
    drucksachen = {"e": "1/2026", "x": "1/2026", "c": "2/2026", "y": "3/2026", "z": "3/2026", "frei": "4/2026",
                   "p": "5/2026"}
    rel = [("x", "c"), ("c", "y"), ("p", "frei2")]
    weg = geocode.sperrmenge({"e"}, rel, drucksachen)
    # e → (Drucksache) x → (Beziehung) c → y → (Drucksache) z; „frei“ und „p“ bleiben erlaubt
    assert weg == {"e": "start", "x": "drucksache", "c": "beziehung", "y": "beziehung", "z": "drucksache"}
    # Beziehungen in beiden Richtungen, auch zu Kennungen ohne Drucksache (ausgelassene Vorlagen)
    assert geocode.sperrmenge({"ohne-nummer"}, [("ohne-nummer", "frei")], drucksachen) == {
        "ohne-nummer": "start", "frei": "beziehung"}
    assert geocode.sperrmenge({"frei2"}, rel, drucksachen) == {"frei2": "start", "p": "beziehung"}
    assert geocode.sperrmenge(set(), rel, drucksachen) == {}
    # ein Generator als Beziehungen (check liest aus der Datenbank) wird nur einmal gelesen
    assert set(geocode.sperrmenge({"e"}, iter(rel), drucksachen)) == {"e", "x", "c", "y", "z"}


# --- build._inherited ----------------------------------------------------------------------------------------------

class _Gaz:
    """Straßenverzeichnis-Ersatz für _strassenabschnitt und _add_location (erfundene Lage)."""
    streets = {"Musterstraße": [{"ortsteil": "Seeberg", "bezirk": "Chorweiler", "lon": 6.9, "lat": 51.0,
                                 "source": "strassen-koeln"},
                                {"ortsteil": "Heimersdorf", "bezirk": "Chorweiler", "lon": 6.8, "lat": 51.0,
                                 "source": "strassen-koeln"}]}
    ot_by_name = {"Seeberg": {"ortsteil": 601}, "Heimersdorf": {"ortsteil": 602}}


def _vererbung(gesperrt, strasse="Musterstraße"):
    adresse = f"adresse:{strasse} 12a|Seeberg"
    locations = {adresse: (adresse, f"{strasse} 12a", None, None, f"{strasse} 12a", 6.91, 51.01, "Seeberg", 601,
                           "Chorweiler", "adresse", config.QUELLE_ADRESSEN),
                 "ortsteil:Seeberg": ("ortsteil:Seeberg", None, None, None, "Seeberg", 6.9, 51.0, "Seeberg", 601,
                                      "Chorweiler", "ortsteil", config.QUELLE_GEO)}
    papers = [{"id": "p", "reference": "1/2026"}, {"id": "k", "reference": "2/2026", "superordinatedPaper": ["p"]}]
    own = [("p", adresse, "B", PUNKT, "hoch", "Musterstraße", "p"),
           ("p", "ortsteil:Seeberg", "B", "ortsteil_name", "mittel", "Seeberg", "p")]
    rows = build._inherited(papers, {p["id"]: p for p in papers}, own, locations, _Gaz(), gesperrt)
    return {(r[0], locations[r[1]][10], r[1], r[3], r[4]) for r in rows}, rows


def test_vererbung_ohne_hauskoordinate_bei_gesperrter_vorlage():
    """Eine gesperrte Vorlage erbt statt der Hauskoordinate den Straßenabschnitt im Stadtteil der Hausnummer (nicht
    den gleichnamigen Abschnitt in einem anderen Stadtteil); übrige Ortsbezüge erbt sie wie bisher."""
    ebenen, rows = _vererbung({"k"})
    assert ebenen == {("k", "strasse", "strasse:Musterstraße|Seeberg", "vererbt", "mittel"),
                      ("k", "ortsteil", "ortsteil:Seeberg", "vererbt", "mittel")}
    assert any("Straßenabschnitt ohne Hausnummer" in r[5] for r in rows)
    # Gegenprobe: erlaubt → die Hauskoordinate wird vererbt (wie bisher)
    assert ("k", "adresse", "adresse:Musterstraße 12a|Seeberg", "vererbt", "mittel") in _vererbung(set())[0]


def test_vererbung_ohne_strassenabschnitt_entfaellt_der_ort():
    """Kennt das Straßenverzeichnis die Straße im Stadtteil nicht, entfällt dieser Ortsbezug (kein Punkt)."""
    ebenen, _ = _vererbung({"k"}, strasse="Unbekannte Straße")
    assert ebenen == {("k", "ortsteil", "ortsteil:Seeberg", "vererbt", "mittel")}


# --- Aufbau, Export, Prüfung --------------------------------------------------------------------------------------

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


def _lage():
    """Straße mit genau einer Lage, drei Hausnummern und ihre Hauskoordinaten (wie in test_vorlagenart_punkt)."""
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    lage = next(iter(hnr[strasse]))
    nummern = sorted(hnr[strasse][lage], key=lambda n: (len(n), n))[:3]
    assert UNBEKANNT not in json.loads(config.STRASSEN.read_text())["streets"]
    return strasse, nummern, [tuple(hnr[strasse][lage][n]) for n in nummern]


def _vorlage(key, ref, titel, art="Beschlussvorlage", **felder):
    p = {"id": f"{B}/papers/fp-{key}", "reference": ref, "name": titel, "paperType": art, "date": "2026-10-01",
         "web": "https://example.invalid/vorlage", "modified": "2026-10-01T10:00:00+02:00", "location": [],
         "consultation": [{"id": f"{B}/consultations/fp-{key}", "role": "Entscheidung",
                           "organization": [f"{B}/organizations/rat"], "authoritative": True}]}
    for k, v in felder.items():
        if v is ...:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def _ort(key, strasse, punkt):
    return {"id": f"{B}/locations/fp-{key}", "streetAddress": strasse,
            "geojson": {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(punkt)}}}


def _id(key):
    return f"{B}/papers/fp-{key}"


REFS = {}   # Schlüssel → Drucksache der eingefügten Fälle (_einfuegen)


def _einfuegen():
    """Erfundene Fälle; liefert (Straße, Hausnummern, Hauskoordinaten, erwartete Ebene je Schlüssel)."""
    strasse, nr, xy = _lage()
    titel = f"[Testdaten] Sitzbänke an der {strasse} {nr[0]}"
    amt = {"id": f"{B}/organizations/fp-amt63", "name": "63 Bauaufsicht", "organizationType": "Verwaltungsbereich"}
    orgs = json.loads(config.ORGANIZATIONS.read_text())
    config.ORGANIZATIONS.write_text(json.dumps(orgs + [amt], ensure_ascii=False))
    ort_g1 = _ort("g1", f"{strasse} {nr[1]}", xy[1])
    faelle = [
        ("kontrolle", "1601/2026", titel, {}, "adresse"),
        # x10: Kopie mit derselben Drucksache wie eine Eingabe erbt von ihrer übergeordneten Vorlage
        ("p10", "1610/2026", titel, {"subordinatedPaper": [_id("x10")]}, "strasse"),
        ("e10", "1611/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("x10", "1611/2026", OHNE_ORT, {"superordinatedPaper": [_id("p10")]}, "strasse"),
        # c9: verbunden mit einer Kopie (dieselbe Drucksache wie eine Eingabe)
        ("e9", "1620/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("x9", "1620/2026", OHNE_ORT, {"subordinatedPaper": [_id("c9")]}, None),
        ("c9", "1621/2026", titel, {}, "strasse"),
        # zwei Runden: Eingabe → Drucksache → Beziehung → Drucksache
        ("e20", "1630/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("x20", "1630/2026", OHNE_ORT, {"subordinatedPaper": [_id("y20")]}, None),
        ("y20", "1631/2026", OHNE_ORT, {"paperType": "Mitteilung"}, None),
        ("z20", "1631/2026", titel, {}, "strasse"),
        # relatedPaper in beiden Richtungen, auch bei einer ausgelassenen Eingabe (ohne Drucksachennummer)
        ("e3", "1640/2026", OHNE_ORT, {"paperType": EINGABE, "relatedPaper": [_id("s3")]}, None),
        ("s3", "1641/2026", titel, {"paperType": "Mitteilung"}, "strasse"),
        ("s3b", "1642/2026", titel, {"paperType": "Mitteilung", "relatedPaper": [_id("e3b")]}, "strasse"),
        ("e3b", "1643/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("skip5", None, OHNE_ORT, {"paperType": EINGABE, "reference": ..., "relatedPaper": [_id("s5")]}, None),
        ("s5", "1650/2026", titel, {"paperType": "Mitteilung"}, "strasse"),
        # Titel ohne Hausnummer (maske.py): Bauordnungsamt federführend, „Einwohner“ im Titel
        ("bau", "1660/2026", titel, {"underDirectionOf": [amt["id"]]}, "strasse"),
        ("ew", "1661/2026", f"[Testdaten] Einwohnerversammlung an der {strasse} {nr[0]}", {"paperType": "Mitteilung"},
         "strasse"),
        # OParl-Ortsangabe mit Punkt: Eingabe, eine erlaubte Vorlage mit derselben Ortsangabe, eine erlaubte mit eigener
        ("g1", "1670/2026", OHNE_ORT, {"paperType": EINGABE, "location": [ort_g1]}, "ortsteil"),
        ("g2", "1671/2026", OHNE_ORT, {"location": [ort_g1]}, "ortsteil"),
        ("g3", "1672/2026", OHNE_ORT, {"location": [_ort("g3", f"{strasse} {nr[2]}", xy[2])]}, "strasse"),
        # Straße nur aus der Ortsangabe einer Eingabe bekannt: kein Straßenpunkt für andere Vorlagen
        ("g4", "1673/2026", OHNE_ORT, {"paperType": EINGABE, "location": [_ort("g4", f"{UNBEKANNT} 5", xy[1])]},
         "ortsteil"),
        ("g5", "1674/2026", f"[Testdaten] {UNBEKANNT}: neue Bank", {}, None),
    ]
    REFS.clear()
    REFS.update({key: ref for key, ref, *_ in faelle})
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for key, ref, t, felder, _ in faelle:
            f.write(json.dumps(_vorlage(key, ref, t, **felder), ensure_ascii=False) + "\n")
    return strasse, nr, xy, {key: ebene for key, *_, ebene in faelle}


def _orte(db, key):
    return {r for r in db.execute("SELECT l.level, pl.method, l.lon, l.lat, l.street FROM paper_location pl "
                                  "JOIN location l ON l.id = pl.location_id WHERE pl.paper_id = ?", (_id(key),))}


def _punkte_im_export():
    """(Drucksache, lon, lat) aller Punkte in vorlagen.geojson und den Gebietsdateien."""
    base = config.EXPORT / config.STADT
    out = {(f["properties"]["reference"], *f["geometry"]["coordinates"])
           for f in json.loads((base / "vorlagen.geojson").read_text())["features"]}
    for d in check.GEBIETSDATEIEN:
        for datei in (base / d).glob("*.json"):
            out |= {(p["reference"], x["lon"], x["lat"]) for p in json.loads(datei.read_text())["papers"]
                    for x in p.get("locations") or () if x.get("lon") is not None}
    return out


def test_fixpunkt_aufbau_und_pruefung(testdaten, capsys):
    """Alle Fälle in einem Aufbau: keine Hauskoordinate und kein genauer OParl-Punkt bei gesperrten Vorlagen (in keiner
    Datei), Rückfall auf den Straßenabschnitt bzw. den Stadtteil; Aufbau und check.erlaubnis urteilen gleich, check
    besteht ohne Befund; relatedPaper steht in paper_related (nicht in paper_relation) und im Log von build."""
    strasse, nr, xy, erwartet = _einfuegen()
    build.build()
    aus_build = capsys.readouterr().out
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    aus_check = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in aus_check
    db = sqlite3.connect(config.DB)
    je_id = check.erlaubnis(db)[0]
    for key, ebene in erwartet.items():
        orte = _orte(db, key)
        if key == "skip5":
            continue
        # erlaubt: Kontrolle, g2 (teilt nur die Ortsangabe mit der Eingabe g1, keine Beziehung), g3, g5
        assert je_id[_id(key)] is (key in ("kontrolle", "g2", "g3", "g5")), key
        if ebene == "adresse":
            assert {(lvl, m) for lvl, m, *_ in orte} == {("adresse", PUNKT)}, key
        elif ebene == "strasse" and key != "g3":
            assert orte and {lvl for lvl, *_ in orte} == {"strasse"}, (key, orte)
            assert {m for _, m, *_ in orte} <= {STRASSE_HNR, "vererbt"}, (key, orte)
        elif ebene == "ortsteil":   # OParl-Punkt einer gesperrten Vorlage → Stadtteil (wie subLocality)
            assert {(lvl, m) for lvl, m, *_ in orte} == {("ortsteil", "oparl_sublocality")}, (key, orte)
            assert not any((lon, lat) == xy[1] for _, _, lon, lat, _ in orte), key
    assert _orte(db, "x10") and {m for _, m, *_ in _orte(db, "x10")} == {"vererbt"}
    # erlaubte Vorlage mit eigener OParl-Ortsangabe behält den genauen Punkt; die Straße der gesperrten Ortsangabe
    # (nur dort bekannt) liefert anderen Vorlagen keinen Punkt
    assert {(lvl, m, lon, lat) for lvl, m, lon, lat, _ in _orte(db, "g3")} == {("strasse", "oparl_location", *xy[2])}
    assert not any(s == UNBEKANNT for *_, s in _orte(db, "g5")), _orte(db, "g5")
    # relatedPaper: eigene Tabelle, in beiden Richtungen ausgewertet; paper_relation (Export, maske) unverändert
    assert set(db.execute("SELECT paper_id, related_id FROM paper_related")) == {
        (_id("e3"), _id("s3")), (_id("s3b"), _id("e3b")), (_id("skip5"), _id("s5"))}
    assert not db.execute("SELECT COUNT(*) FROM paper_relation WHERE ? IN (parent_id, child_id)",
                          (_id("s3"),)).fetchone()[0]
    db.close()
    assert ("relatedPaper: 2 Vorlagen mit relatedPaper (3 Verweise); ohne Hauskoordinate nur über relatedPaper: "
            "3 Vorlagen\n") in aus_build
    assert "Titel ohne Hausnummer (Einwohnerschaft, Bauordnung, Naturschutz) 2," in aus_build
    # keine Hauskoordinate und kein genauer OParl-Punkt einer gesperrten Vorlage in einer Exportdatei (Drucksachen der
    # eingefügten Fälle; die Testdaten nutzen andere Nummern)
    gesperrt = {ref for key, ref in REFS.items() if ref and key not in ("kontrolle", "g2", "g3", "g5")}
    punkte = {(r, *p) for r, *p in _punkte_im_export() if r in REFS.values()}
    assert {r for r, *p in punkte if tuple(p) == xy[0]} == {"1601/2026"}
    assert not {r for r, *p in punkte if tuple(p) == xy[1]}
    assert {r for r, *p in punkte if tuple(p) == xy[2]} == {"1672/2026"}
    geo = [f["properties"] for f in json.loads((config.EXPORT / config.STADT / "vorlagen.geojson").read_text())[
        "features"]]
    assert {p["reference"] for p in geo} >= gesperrt - {"1611/2026", "1620/2026", "1630/2026", "1631/2026",
                                                        "1640/2026", "1643/2026"}   # verortete gesperrte Fälle
    assert not [p for p in geo if p["reference"] in gesperrt and p["method"] in (PUNKT, "oparl_location")]
    # Titel und Ortsname ohne Hausnummer bei Bauordnung und „Einwohner“ im Titel
    for p in geo:
        if p["reference"] in ("1660/2026", "1661/2026"):
            assert f"{strasse} {nr[0]}" not in p["name"] + p["place"], p


def test_pruefung_meldet_fehler_im_aufbau(testdaten, monkeypatch, capsys):
    """Fehler im Aufbau, die check meldet: der frühere einstufige Ablauf (Beziehungen, dann einmal dieselbe Drucksache),
    relatedPaper nicht ausgewertet, Titel ohne Hausnummer nicht gesperrt."""
    _einfuegen()
    echt = geocode.sperrmenge

    def einstufig(start, beziehungen, drucksachen):   # Fehler: Stand vor Runde 19b
        verbunden = geocode.ohne_hauskoordinate(start, beziehungen)
        return dict.fromkeys(verbunden | geocode.gleiche_drucksache(verbunden, drucksachen), "start")

    nur_related = {(_id("e3"), _id("s3")), (_id("s3b"), _id("e3b")), (_id("skip5"), _id("s5"))}
    faelle = [("sperrmenge", einstufig, {"1610/2026", "1621/2026", "1631/2026"}),
              ("sperrmenge", lambda s, b, d: echt(s, [x for x in b if x not in nur_related], d),
               {"1641/2026", "1642/2026", "1650/2026"}),
              ("punkt_ausschluss", lambda p, g=(), amt=None: (lambda r: None if r == "maske" else r)(
                  geocode.punkt_ausschluss(p, g, amt)), {"1660/2026", "1661/2026"})]
    for name, fehler, verstoss in faelle:
        with monkeypatch.context() as mp:
            mp.setattr(build, name, fehler)
            build.build()
        export.export()
        capsys.readouterr()
        db = sqlite3.connect(config.DB)
        erg = check.datenschutz(db)
        db.close()
        b = [x for x in erg["befunde"] if "Hauskoordinate bei Vorlagen ohne Erlaubnis (Datenbank;" in x]
        assert len(b) == 1 and f": {len(verstoss)}, z. B. {', '.join(sorted(verstoss))}" in b[0], (name, erg)
        if name == "punkt_ausschluss":   # Ortsname mit Hausnummer neben dem Titel ohne Hausnummer
            assert any("Titeln oder Ortsnamen" in x and "1660/2026, 1661/2026" in x for x in erg["befunde"]), erg


def test_pruefung_meldet_oparl_punkt_und_ortsnamen(testdaten, tmp_path, capsys):
    """Genauer OParl-Punkt bei einer gesperrten Vorlage (Datenbank, vorlagen.geojson, Gebietsdateien) und Ortsname mit
    Hausnummer neben einem Titel ohne Hausnummer (place, locations[].name): check meldet jede Stelle."""
    strasse, nr, xy, _ = _einfuegen()
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
        erg = check.datenschutz(db, kopie)
        db.close()
        return erg["befunde"]

    assert pruefen(lambda db, k: None) == []

    def db_punkt(db, _):   # Ortsangabe der Eingabe g1 wieder mit genauem Punkt
        db.execute("UPDATE location SET level = 'strasse', lon = ?, lat = ? WHERE id = ?", (*xy[1], f"{B}/locations/fp-g1"))

    b = pruefen(db_punkt)
    assert len(b) == 1 and "genauer Punkt aus der Ortsangabe der Stadt (OParl)" in b[0] and "(Datenbank;" in b[0]
    assert b[0].endswith(": 1, z. B. 1670/2026"), b   # g2 (1671/2026) ist erlaubt, ihr Punkt gilt nicht als Verstoß

    def json_aendern(datei, aendern):
        doc = json.loads(datei.read_text())
        aendern(doc)
        datei.write_text(json.dumps(doc, ensure_ascii=False))

    def geo_methode(db, k):
        json_aendern(k / "vorlagen.geojson", lambda g: [f["properties"].update(method="oparl_location")
                                                        for f in g["features"]
                                                        if f["properties"]["reference"] == "1670/2026"])

    b = pruefen(geo_methode)
    assert len(b) == 1 and "OParl" in b[0] and "(vorlagen.geojson;" in b[0] and b[0].endswith(": 1, z. B. 1670/2026")

    def gebiet(feld, wert, ref):
        def aendern(db, k):
            for datei in k.glob("ortsteile/*.json"):
                json_aendern(datei, lambda d: [x.update({feld: wert}) for p in d["papers"] if p["reference"] == ref
                                               for x in p.get("locations") or ()])
        return aendern

    b = pruefen(gebiet("method", "oparl_location", "1670/2026"))
    assert len(b) == 1 and "OParl" in b[0] and "(Gebietsdateien der Karte;" in b[0], b

    def geo_ort(db, k):
        json_aendern(k / "vorlagen.geojson", lambda g: [f["properties"].update(place=f"{strasse} {nr[0]}")
                                                        for f in g["features"]
                                                        if f["properties"]["reference"] == "1660/2026"])

    for aendern in (geo_ort, gebiet("name", f"{strasse} {nr[0]}", "1660/2026")):
        b = pruefen(aendern)
        assert len(b) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b[0] and b[0].endswith(": 1, z. B. 1660/2026")
