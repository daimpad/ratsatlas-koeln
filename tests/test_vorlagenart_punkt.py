"""Hauskoordinate nur bei erkennbarer Vorlagenart (Entscheidung des Auftraggebers 10.11.2026): Bei leerer oder nicht
erkennbarer Vorlagenart gibt es keine Hauskoordinate, höchstens die Straße – wie bei Eingaben nach § 24 GO NRW und
Vorlagen natürlicher Personen (Regel vom 04.11.2026). Prüft die Regel (geocode.punkt_ausschluss), den Aufbau
(build.build) mit erfundenen Vorlagen aus tools/testdaten.py und eingefügten erfundenen Vorlagen in den temporären
Pfaden der Fixture `oparl`, die Prüfung (check.erlaubnis, check.datenschutz), die Zählung der erkannten und nicht
erkannten Vorlagenarten in Log und Prüfung, andere Schreibungen (Vergleichstexte), Vorlagen mit derselben Drucksache und
die Erklärtexte. Keine Anfragen an die Stadt."""
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

from pipeline import build, check, config, export, geocode, glossar, kontext
from pipeline.geocode import hausnummer_punkt_erlaubt, punkt_ausschluss

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"
PUNKT, STRASSE_HNR = "strasse+hausnummer_punkt", "strasse+hausnummer"

# erkannt: Kölner Arten aus Stufe 1 und 2 (explore/BERICHT_phase1.md 5.7 und 6.5), Antworten der Verwaltung, Bonner bzw.
# übliche SessionNet-Arten (tools/testdaten.py, actors.POLITIK_TYPES, actors.VERWALTUNG_TYPES)
ERKANNT = ["Antrag nach § 3 der GeschO des Rates", "Anfrage nach § 4 der GeschO des Rates", "Mitteilung BV",
           "Antrag nach § 3 BV2 (CDU)", "Änderungsantrag BV1 (Grüne)", "Gem. Änderungsantrag BV3",
           "Beantwortung einer Anfrage (BV)", "Antrag nach § 3 der Geschäftsordnung des Rates", "Beschlussvorlage",
           "Mitteilung", "Mitteilungsvorlage", "Stellungnahme der Verwaltung", "Dringlichkeitsantrag",
           "Dringlichkeitsentscheidung OB", "Große Anfrage", "Informationsbrief", "BESCHLUSSVORLAGE",
           "  mitteilung bv  ", "Antwort der Verwaltung",
           # „Bürgermeister“ ist keine Einwohnerschaft (auch in anderer Schreibung)
           "Dringlichkeitsentscheidung des Oberbürgermeisters", "Mitteilung der Oberbürgermeisterin",
           "Vorlage des Bezirksbürgermeisters", "Antrag des Bezirksbürgermeisters", "Mitteilung des Buergermeisters"]
# nicht erkennbar: leer, nur Leerraum, null, unbekannt, keine Zeichenkette, Vorlagen aus der Einwohnerschaft oder von
# Privatpersonen ohne Wort einer Eingabe (auch über einen Zeilenumbruch, in anderer Schreibung oder hinter „ue“)
NICHT_ERKANNT = ["", "   ", "\t\n", None, "Sonstiges", "Information", "Bürgerbrief", "Bericht", "Vortrag",
                 ["Beschlussvorlage"], {"name": "Mitteilung"}, 17, "Einwohnervorlage",
                 "Antrag einer Bürgerin", "Antrag\nEinwohner", "Antrag einer Privatperson", "Antrag (Privat)",
                 "Anwohnerantrag", "Bauantrag", "Bauvoranfrage", "Neueinwohnervorlage"]
# seit der Prüfung r20n Eingaben nach geocode.EINGABE (Trennzeichen, Genderform, Bürgeranfrage): ohne Hauskoordinate wie
# bisher, aber mit Grund „eingabe“ statt „vorlagenart“
ALS_EINGABE = ["Bürgeranfrage", "Buergeranfrage", "Bürger*innenantrag"]
# andere Schreibungen einer Eingabe: zerlegte Umlaute, weiches Trennzeichen, Zeichen ohne Breite, Vollbreite,
# „ue“ statt „ü“, Großschreibung, „Paragraf“ statt „§“; „Neueingabe“ (das „ue“ darf „eingabe“ nicht verdecken)
WEICH, OHNE_BREITE, TREMA, VOLL_B = chr(0x00AD), chr(0x200B), chr(0x0308), chr(0xFF22)
EINGABE_SCHREIBUNGEN = ["Bu" + TREMA + "rgerantrag", "Bür" + WEICH + "gerantrag", "Bür" + OHNE_BREITE + "gerantrag",
                        VOLL_B + "ürgerantrag", "Buergerantrag", "BUERGERANTRAG",
                        "Ein" + WEICH + "wohneranfrage nach § 39 Abs. 6", "Antrag nach Paragraf 24 GO",
                        "Antrag nach Paragraph 24 GO NRW", "Neueingabe"]


def _vv(art, **felder):
    return {"reference": "1234/2026", "name": "Sitzbänke am Musterweg 3", "paperType": art, **felder}


# --- Regel ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("art", ERKANNT)
def test_erkannte_vorlagenart_erlaubt(art):
    assert punkt_ausschluss(_vv(art)) is None and hausnummer_punkt_erlaubt(_vv(art))


@pytest.mark.parametrize("art", NICHT_ERKANNT)
def test_nicht_erkennbare_vorlagenart_ohne_hauskoordinate(art):
    assert punkt_ausschluss(_vv(art)) == "vorlagenart"
    assert not hausnummer_punkt_erlaubt(_vv(art))


@pytest.mark.parametrize("art", ALS_EINGABE)
def test_eingabe_nach_der_vorlagenart_ohne_hauskoordinate(art):
    assert punkt_ausschluss(_vv(art)) == "eingabe"
    assert not hausnummer_punkt_erlaubt(_vv(art))


def test_vorlagenart_fehlt():
    p = _vv(None)
    del p["paperType"]
    assert punkt_ausschluss(p) == "vorlagenart"


def test_andere_form_gilt_als_nicht_erkennbar():
    """Kam die Vorlagenart als Liste oder Objekt (build.einlesen macht Text daraus), gilt sie als nicht erkennbar, auch
    wenn der Text passt (vorsichtige Auslegung)."""
    assert punkt_ausschluss(_vv("Beschlussvorlage", **{geocode.ANDERE_FORM: True})) == "vorlagenart"
    assert punkt_ausschluss(_vv("Beschlussvorlage", **{geocode.ANDERE_FORM: False})) is None


def test_eingaben_gehen_vor():
    """Die Ausschlüsse für Eingaben gehen der Erkennung vor: „Einwohneranfrage“ enthält „anfrage“, bleibt aber ohne
    Hauskoordinate; ebenso ein Antrag, dessen Titel eine Eingabe nennt, und ein Antrag im Beschwerdeausschuss."""
    assert punkt_ausschluss(_vv("Einwohneranfrage nach § 39 Abs. 6", reference="AN/0012/2026")) == "eingabe"
    assert punkt_ausschluss(_vv("Antrag nach § 3", name="Anregung nach § 24 GO: Musterweg 3")) == "eingabe"
    assert punkt_ausschluss(_vv("Beschlussvorlage"),
                            ["Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden"]) == "gremium"
    assert punkt_ausschluss(_vv("Beschlussvorlage", reference="AZ 191/21")) == "drucksache"


@pytest.mark.parametrize("art", EINGABE_SCHREIBUNGEN)
def test_eingabe_in_anderer_schreibung(art):
    """Eine andere Schreibung lässt eine Eingabe nicht als erkannte Vorlagenart durch (geocode._vergleichstexte)."""
    assert punkt_ausschluss(_vv(art)) == "eingabe"


def test_titel_und_gremium_in_anderer_schreibung():
    """Auch Titel und Gremien werden über den Vergleichstext abgeglichen; Datenbank und Log behalten die Schreibung."""
    assert punkt_ausschluss(_vv("Antrag nach § 4 der GeschO des Rates",
                                name="Ein" + WEICH + "wohneranfrage zum Musterweg 3")) == "eingabe"
    assert punkt_ausschluss(_vv("Beschlussvorlage"), ["Ausschuss fuer Buergerbeteiligung"]) == "gremium"
    assert punkt_ausschluss(_vv("Beschlussvorlage"), ["Ausschuss für An" + WEICH + "regungen und Beschwerden"]) == (
        "gremium")
    assert geocode.vorlagenart_bezeichnung(_vv("Bür" + WEICH + "gerbrief")) == "„Bür" + WEICH + "gerbrief“"


def test_bezeichnung_und_zeile():
    assert geocode.vorlagenart_bezeichnung(_vv("  Sonstiges ")) == "„Sonstiges“"
    assert geocode.vorlagenart_bezeichnung(_vv(" ")) == geocode.vorlagenart_bezeichnung(_vv(None)) == "(leer)"
    assert geocode.vorlagenart_bezeichnung(_vv("Mitteilung", **{geocode.ANDERE_FORM: True})) == (
        "„Mitteilung“ (als Liste oder Objekt geliefert)")
    assert len(geocode.vorlagenart_bezeichnung(_vv("x" * 200))) == 82   # 80 Zeichen samt „…“ und Anführungszeichen
    zeile = geocode.nicht_erkannte_arten(Counter({"„Sonstiges“": 2, "(leer)": 3, "„Information“": 2}))
    assert zeile.endswith(": 7 Vorlagen – (leer) 3, „Information“ 2, „Sonstiges“ 2")
    viele = geocode.nicht_erkannte_arten(Counter({f"„Art {i:02d}“": 1 for i in range(45)}), hoechstens=40)
    assert viele.count("„Art ") == 40 and viele.endswith("… und 5 weitere Arten")
    assert geocode.nicht_erkannte_arten(Counter()).endswith(": 0 Vorlagen")
    assert geocode.erkannte_arten(Counter({"„Mitteilung“": 1, "„Beschlussvorlage“": 4})) == (
        "Vorlagenart erkannt, Hauskoordinate möglich (geocode.VORLAGENART_PUNKT): 5 Vorlagen – „Beschlussvorlage“ 4, "
        "„Mitteilung“ 1")
    assert geocode.erkannte_arten(Counter({f"„Art {i:02d}“": 1 for i in range(42)})).endswith("… und 2 weitere Arten")


def test_gleiche_drucksache():
    """Vorlagen mit derselben Drucksache wie eine gesperrte (geocode.sperrmenge ohne Beziehungen)."""
    drucksachen = {"a": "1/2026", "b": "1/2026", "c": "2/2026", "d": "3/2026"}
    assert geocode.sperrmenge({"a", "x"}, [], drucksachen) == {"a": "start", "x": "start", "b": "drucksache"}
    assert geocode.sperrmenge({"c"}, [], drucksachen) == {"c": "start"}


# --- Aufbau, Export, Prüfung ------------------------------------------------------------------------------------------

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


def _adresse():
    """Straße mit genau einer Lage und eine Hausnummer dort (Hauskoordinate eindeutig; wie in test_feldformen)."""
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    lage = next(iter(hnr[strasse]))
    return strasse, sorted(hnr[strasse][lage], key=lambda n: (len(n), n))[0]


def _vorlage(nr, titel, **felder):
    """Erfundene Vorlage mit Straße und Hausnummer im Titel und einer Beratung im Rat; `felder` ersetzt oder entfernt
    (Wert ...) Felder."""
    p = {"id": f"{B}/papers/art-{nr}", "reference": f"{1500 + nr}/2026", "name": titel, "paperType": "Beschlussvorlage",
         "date": "2026-10-01", "web": "https://example.invalid/vorlage", "modified": "2026-10-01T10:00:00+02:00",
         "location": [], "consultation": [{"id": f"{B}/consultations/art-{nr}", "role": "Entscheidung",
                                           "organization": [f"{B}/organizations/rat"], "authoritative": True}]}
    for k, v in felder.items():
        if v is ...:
            p.pop(k, None)
        else:
            p[k] = v
    return p


# (Nummer, Felder, erwartete Ebene); Nummern 1–9 nicht erkennbar, 20–29 erkannt bzw. Eingabe, 30–31 verbunden
FAELLE = [
    (1, {"paperType": ""}, "strasse"),
    (2, {"paperType": "   "}, "strasse"),
    (3, {"paperType": None}, "strasse"),
    (4, {"paperType": ...}, "strasse"),
    (5, {"paperType": "Sonstiges"}, "strasse"),
    (6, {"paperType": "Information"}, "strasse"),
    (7, {"paperType": ["Beschlussvorlage"]}, "strasse"),
    (8, {"paperType": {"id": f"{B}/paperTypes/7", "name": "Mitteilung"}}, "strasse"),
    (20, {"paperType": "Antrag nach § 3 der GeschO des Rates", "reference": "AN/1520/2026"}, "adresse"),
    (21, {"paperType": "Anfrage nach § 4 der GeschO des Rates", "reference": "AN/1521/2026"}, "adresse"),
    (22, {"paperType": "Mitteilung BV"}, "adresse"),
    (23, {"paperType": "Beschlussvorlage"}, "adresse"),
    (24, {"paperType": "Antrag nach § 3 BV2 (CDU)", "reference": "AN/1524/2026"}, "adresse"),
    (25, {"paperType": "Einwohneranfrage nach § 39 Abs. 6", "reference": "AN/1525/2026"}, "strasse"),
    # Beschlussvorlage, verbunden mit einer Vorlage nicht erkennbarer Art (Ausbreitung, vorsichtige Auslegung)
    (30, {"paperType": "Beschlussvorlage", "superordinatedPaper": [f"{B}/papers/art-31"]}, "strasse"),
    (31, {"paperType": "Sonstiges", "name": "[Testdaten] Ohne Ort"}, None),
    # dieselbe Drucksache, nicht verbunden: Beschlussvorlage und eine Vorlage nicht erkennbarer Art (Exporte und
    # check.erlaubnis urteilen je Drucksache, der Aufbau ebenso)
    (40, {"paperType": "Beschlussvorlage"}, "strasse"),
    (41, {"paperType": "Sonstiges", "name": "[Testdaten] Ohne Ort", "reference": "1540/2026"}, None),
]
ERWARTETE_ZEILE = ("Vorlagenart nicht erkennbar, daher keine Hauskoordinate (höchstens Straße; "
                   "geocode.VORLAGENART_PUNKT): 10 Vorlagen – (leer) 4, „Sonstiges“ 3, "
                   "„Beschlussvorlage“ (als Liste oder Objekt geliefert) 1, „Information“ 1, "
                   "„https://example.invalid/oparl/paperTypes/7; Mitteilung“ (als Liste oder Objekt geliefert) 1")
# erkannte Arten der eingefügten Vorlagen (Erlaubnis nach eigener Angabe; 30 und 40 verlieren den Punkt erst über die
# verbundene Vorlage bzw. die gleiche Drucksache)
ERKANNT_EINGEFUEGT = Counter({"„Beschlussvorlage“": 3, "„Antrag nach § 3 der GeschO des Rates“": 1,
                              "„Anfrage nach § 4 der GeschO des Rates“": 1, "„Mitteilung BV“": 1,
                              "„Antrag nach § 3 BV2 (CDU)“": 1})


def _testdaten_arten():
    """Vorlagenarten der Vorlagen aus tools/testdaten.py (vor dem Einfügen): Counter je Art."""
    return Counter(json.loads(z)["paperType"] for z in config.PAPERS.read_text(encoding="utf-8").splitlines() if z)


def _einfuegen():
    strasse, nr = _adresse()
    titel = f"[Testdaten] Sitzbänke an der {strasse} {nr}"
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for n, felder, _ in FAELLE:
            f.write(json.dumps(_vorlage(n, titel, **felder), ensure_ascii=False) + "\n")
    return strasse, nr


def _ortsbezuege(db, pid):
    return {r for r in db.execute("SELECT l.level, pl.method FROM paper_location pl JOIN location l "
                                  "ON l.id = pl.location_id WHERE pl.paper_id = ?", (pid,))}


def test_aufbau_pruefung_und_zaehlung(testdaten, capsys):
    """Nicht erkennbare Art → Straßenabschnitt (Ebene „strasse“, Methode „strasse+hausnummer“) statt Hauskoordinate,
    auch für die mit ihr verbundene Beschlussvorlage; erkannte Kölner und Bonner Arten → Hauskoordinate
    (Ebene „adresse“, Methode „strasse+hausnummer_punkt“); Einwohneranfrage → Straße. Aufbau und check.erlaubnis
    urteilen gleich (auch bei gleicher Drucksache), check besteht ohne Befund; Log von build und Ausgabe von check
    nennen die Gründe und die erkannten und nicht erkannten Arten mit Anzahl, aber keine Titel."""
    td = _testdaten_arten()
    strasse, nr = _einfuegen()
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
    gebiete = {p["reference"]: p for f in sorted((config.EXPORT / config.STADT / "ortsteile").glob("*.json"))
               for p in json.loads(f.read_text())["papers"]}
    geo = json.loads((config.EXPORT / config.STADT / "vorlagen.geojson").read_text())
    for n, felder, ebene in FAELLE:
        pid = f"{B}/papers/art-{n}"
        ref = db.execute("SELECT reference FROM paper WHERE id = ?", (pid,)).fetchone()[0]
        fall = (n, felder.get("paperType"))
        if ebene == "adresse":
            assert _ortsbezuege(db, pid) == {("adresse", PUNKT)}, fall
            assert je_id[pid] is True, fall
            assert {x["method"] for x in gebiete[ref]["locations"]} == {PUNKT}, fall
        elif ebene == "strasse":
            assert _ortsbezuege(db, pid) == {("strasse", STRASSE_HNR)}, fall   # Rückfallstufe wie bei Eingaben
            assert je_id[pid] is False, fall
            assert [(x["level"], x["method"]) for x in gebiete[ref]["locations"]] == [("strasse", STRASSE_HNR)], fall
            assert {x["properties"]["method"] for x in geo["features"]
                    if x["properties"]["reference"] == ref} == {STRASSE_HNR}, fall
        else:
            assert je_id[pid] is False, fall
    # Vorlagenart als Liste oder Objekt: Text in der Datenbank, Kennzeichen in paper_type_other_form
    assert {r[0] for r in db.execute("SELECT paper_id FROM paper_type_other_form")} == {
        f"{B}/papers/art-7", f"{B}/papers/art-8"}
    assert db.execute("SELECT paper_type FROM paper WHERE id = ?", (f"{B}/papers/art-7",)).fetchone() == (
        "Beschlussvorlage",)
    db.close()
    # Zählung: die Testdaten haben nur erkennbare Arten oder Eingaben („Anregungen und Beschwerden“) und keine
    # Beziehungen; gezählt werden dazu die zehn eingefügten Vorlagen nicht erkennbarer Art
    assert set(td) <= {"Antrag nach § 3 der Geschäftsordnung des Rates", "Beschlussvorlage", "Mitteilung",
                       "Anregungen und Beschwerden"}, td
    eingaben = td["Anregungen und Beschwerden"] + 1   # dazu die Einwohneranfrage (25)
    alle = sum(td.values()) + len(FAELLE)
    assert (f"Ohne Erlaubnis für Hauskoordinaten: {eingaben + 10 + 2} von {alle} Vorlagen (Drucksache in anderem "
            f"Schema 0, Eingabe oder Einwohneranfrage {eingaben}, Ausschuss für Anregungen und Beschwerden 0, "
            f"Vorlagenart nicht erkennbar 10, Titel ohne Hausnummer (Einwohnerschaft, Bauordnung, Naturschutz) 0, "
            f"verbunden mit einer davon oder einer ausgelassenen Vorlage 1, mit derselben Drucksache wie eine davon 1)\n"
            ) in aus_build
    assert ERWARTETE_ZEILE + "\n" in aus_build
    assert ERWARTETE_ZEILE + "\n" in aus_check
    erkannt = Counter({f"„{art}“": n for art, n in td.items() if art != "Anregungen und Beschwerden"})
    erkannt.update(ERKANNT_EINGEFUEGT)
    assert geocode.erkannte_arten(erkannt) + "\n" in aus_build
    assert geocode.erkannte_arten(erkannt) + "\n" in aus_check
    assert "davon mit leerer oder nicht erkennbarer Vorlagenart (Entscheidung 10.11.2026): 10\n" in aus_check
    assert [z for z in aus_check.splitlines() if z.startswith("davon ohne Erlaubnis für Hauskoordinaten")][0].endswith(
        f": {eingaben + 10 + 2}")   # wie im Aufbau, samt verbundener Vorlage und gleicher Drucksache
    for aus in (aus_build, aus_check):   # Protokolle der Workflows sind öffentlich: keine Titel, keine Hausnummer
        assert "Sitzbänke" not in aus and f"{strasse} {nr}" not in aus


def test_pruefung_meldet_eingeschleusten_punkt_bei_unbekannter_art(testdaten, monkeypatch, capsys):
    """Setzt ein Fehler im Aufbau Vorlagen nicht erkennbarer Art doch auf die Hauskoordinate (Regel ohne die Erkennung
    der Vorlagenart), meldet check es in Datenbank, vorlagen.geojson und Gebietsdateien, auch die Beschlussvorlage mit
    derselben Drucksache wie eine Vorlage nicht erkennbarer Art; Eingaben bleiben gesperrt."""
    _einfuegen()
    monkeypatch.setattr(build, "punkt_ausschluss",
                        lambda p, g=(), amt=None: None if punkt_ausschluss(p, g, amt) == "vorlagenart"
                        else punkt_ausschluss(p, g, amt))
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    verstoss = {db.execute("SELECT reference FROM paper WHERE id = ?", (f"{B}/papers/art-{n}",)).fetchone()[0]
                for n, _, ebene in FAELLE if ebene == "strasse" and n != 25}
    assert all(_ortsbezuege(db, f"{B}/papers/art-{n}") == {("adresse", PUNKT)}
               for n, _, ebene in FAELLE if ebene == "strasse" and n != 25)
    assert _ortsbezuege(db, f"{B}/papers/art-25") == {("strasse", STRASSE_HNR)}   # Einwohneranfrage weiter gesperrt
    erg = check.datenschutz(db)
    db.close()
    for wo in ("Datenbank", "vorlagen.geojson", "Gebietsdateien der Karte"):
        b = [x for x in erg["befunde"] if f"Hauskoordinate bei Vorlagen ohne Erlaubnis ({wo};" in x]
        assert len(b) == 1 and f": {len(verstoss)}, z. B. {', '.join(sorted(verstoss)[:5])}" in b[0], (wo, b)
    assert erg["untersucht"]["vorlagenart_nicht_erkennbar"] == 10
    # gleiche Drucksache (40 und 41): auch in der Datenbank gemeldet, nicht nur in den Exporten
    assert "1540/2026" in verstoss


def test_erklaertexte_nennen_die_regel():
    """Begriff „Verortung“ (Begriffsseite, glossar.json) und „Verstehen“ in site/index.html nennen die Regel vom
    10.11.2026 gleich: ist die Art einer Vorlage nicht erkennbar, zeigt die Karte höchstens die Straße."""
    satz = "ist die Art einer Vorlage nicht erkennbar, zeigt die Karte höchstens die Straße"
    g = {b["begriff"]: b for b in glossar.glossar()["begriffe"]}
    assert satz in g["Verortung"]["erklaerung"]
    assert satz in (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def test_texte_nennen_anfragen():
    """Entscheidung 10.11.2026: politische Anfragen erhalten wie Anträge die Hauskoordinate; die Texte sagen das."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for datei in ("site/datenschutz.html", "site/index.html", "README.md", "pipeline/glossar.py", "site/app.js",
                  "pipeline/publish.py", "pipeline/technikseite.py"):
        text = (root / datei).read_text(encoding="utf-8").replace('"\n', "").replace('                  "', "")
        assert "Anträge und Anfragen" in text or "Anträgen und Anfragen" in text, datei
