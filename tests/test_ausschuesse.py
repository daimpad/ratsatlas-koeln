"""Ausschussnamen der Zuständigkeitsordnung vom 02.06.2026 (§§ 7–23, pipeline/ausschuesse.py) und die Regeln, die
Gremiennamen auswerten: Thema (topics), Hauskoordinate und Titelmaske (geocode.gremium_ausschluss,
maske.ausgang_punktregel), Gremium aus dem Sitzungsnamen (export.gremium_der_sitzung), Abgleich mit der OParl-Liste.
Name laut Satzung und bisherige Schreibweisen werden gleich behandelt; keine Schreibweise entfällt. Erfundene Vorlagen
und Organisationen, keine Anfragen an die Stadt."""
import csv
import re
import sqlite3
from pathlib import Path

import pytest

from pipeline import ausschuesse, dossier, export, geocode, maske, topics
from pipeline.geocode import hausnummer_punkt_erlaubt, punkt_ausschluss

ROOT = Path(__file__).resolve().parents[1]
NAMEN = [(nr, n) for nr, name, andere in ausschuesse.AUSSCHUESSE for n in (name, *andere)]
B10 = "Ausschuss Bürgerbeteiligung, Anregungen und Beschwerden"         # § 10 laut Satzung
B10_BISHER = "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden"   # Testdaten, Texte, Tests bisher
VV = {"reference": "1234/2026", "paperType": "Beschlussvorlage", "name": "[Testdaten] Sanierung Musterweg 3"}


def test_liste_paragrafen_7_bis_23():
    nr = [x[0] for x in ausschuesse.AUSSCHUESSE]
    assert nr == list(range(7, 24))
    # jeder Vergleichsschlüssel gehört zu genau einem Paragrafen
    schluessel = {}
    for n, name in NAMEN:
        assert schluessel.setdefault(ausschuesse.schluessel(name), n) == n, name


@pytest.mark.parametrize("nr, name", NAMEN)
def test_abschnitt_name_laut_satzung(nr, name):
    assert ausschuesse.abschnitt(name) == nr
    assert ausschuesse.abschnitt(f"  {name.upper()} ") == nr


@pytest.mark.parametrize("name, nr", [
    # bisherige Schreibweisen im Code und in den Tests (mit „für“, Gedankenstrich, zusammengezogene Leerzeichen)
    (B10_BISHER, 10), ("Ausschuss für Kunst und Kultur", 15), ("Ausschuss für Klima, Umwelt und Grün", 14),
    ("Ausschuss für Schule und Weiterbildung", 19), ("Ausschuss für Soziales, Gesundheit, Seniorinnen und Senioren", 20),
    ("Jugendhilfeausschuss – Ausschuss für Kinder, Jugend und Familie", 13), ("Jugendhilfeausschuss", 13),
    ("Ausschuss Allgemeine Verwaltung und Rechtsfragen/Vergabe/Internationales", 8),
    # keine Ausschüsse der §§ 7–23 (frühere Namen, andere Gremien)
    ("Rat", None), ("Rat der Stadt Köln", None), ("Bezirksvertretung 1 (Innenstadt)", None),
    ("Verkehrsausschuss", None), ("Bauausschuss", None), ("Integrationsrat", None),
    ("Ausschuss für Chancengerechtigkeit und Integration", None), ("Betriebsausschuss Gebäudewirtschaft", None),
    ("Unterausschuss Kunst und Kultur", None), ("", None), (None, None),
])
def test_abschnitt_bisherige_schreibweisen(name, nr):
    assert ausschuesse.abschnitt(name) == nr


# Thema je Paragraf, wie es die Muster in topics.GREMIUM schon vor dem Abgleich ergaben (§ 7 bewusst ohne Thema, § 12
# ohne passendes Muster: offen)
THEMA = {7: None, 8: "beteiligung", 9: "bauen", 10: "beteiligung", 11: "wirtschaft", 12: None, 13: "kinder",
         14: "umwelt", 15: "kultur", 16: "wirtschaft", 17: "verkehr", 18: "wirtschaft", 19: "bildung", 20: "soziales",
         21: "kultur", 22: "bauen", 23: "wirtschaft"}
# Kurzformen in der Satzung selbst, die das Teilwort „Internationales“ nicht tragen: bisher und weiter ohne Thema
OHNE_THEMA_KURZFORM = {"Ausschuss AVR", "Ausschuss Allgemeine Verwaltung und Rechtsfragen"}


@pytest.mark.parametrize("nr, name", NAMEN)
def test_thema_name_laut_satzung(nr, name):
    erwartet = None if name in OHNE_THEMA_KURZFORM else THEMA[nr]
    assert topics._gremium_theme(name) == erwartet


@pytest.mark.parametrize("bisher, nr", [
    (B10_BISHER, 10), ("Ausschuss für Kunst und Kultur", 15), ("Ausschuss für Klima, Umwelt und Grün", 14),
    ("Ausschuss für Schule und Weiterbildung", 19), ("Ausschuss für Soziales, Gesundheit, Seniorinnen und Senioren", 20),
    ("Jugendhilfeausschuss", 13), ("Bauausschuss", 9), ("Stadtentwicklungsausschuss", 22), ("Verkehrsausschuss", 17),
    ("Gesundheitsausschuss", 20), ("Wirtschaftsausschuss", 23), ("Digitalisierungsausschuss", 23),
])
def test_thema_bisherige_schreibweise_wie_satzung(bisher, nr):
    """Bisherige und frühere Schreibweisen behalten ihr Thema; es ist dasselbe wie für den Namen laut Satzung."""
    assert topics._gremium_theme(bisher) == THEMA[nr] is not None


@pytest.mark.parametrize("gremium", [
    B10, B10_BISHER, B10.upper(), "Ausschuss Buergerbeteiligung, Anregungen und Beschwerden",
    "Ausschuss  Bürgerbeteiligung,­Anregungen und Beschwerden", "Ausschuss für Anregungen und Beschwerden",
])
def test_datenschutz_name_laut_satzung_und_bisher(gremium):
    """§ 10: Name laut Satzung und bisherige Schreibweise sperren beide die Hauskoordinate und sind Ausgangspunkt der
    Titelmaske, auch neben anderen Gremien (keine Schreibweise entfällt)."""
    assert punkt_ausschluss(VV, [gremium]) == "gremium"
    assert not hausnummer_punkt_erlaubt(VV, ["Bezirksvertretung 1 (Innenstadt)", gremium])
    assert maske.ausgang_punktregel(VV, ["Mobilitätsausschuss", gremium])
    assert geocode.gremium_ausschluss([gremium])


@pytest.mark.parametrize("nr, name", [(nr, n) for nr, n in NAMEN if nr != 10])
def test_datenschutz_andere_ausschuesse_unveraendert(nr, name):
    """Die übrigen Ausschüsse der §§ 7–23 lösen die Gremiumsregel nicht aus (das Muster bleibt so eng wie bisher)."""
    assert punkt_ausschluss(VV, [name]) is None
    assert not maske.ausgang_punktregel(VV, [name])


@pytest.mark.parametrize("sitzung, bekannt, erwartet", [
    # Sitzung ohne Organisation: der Name laut Satzung (ohne „für“) findet die Organisation mit „für“ und umgekehrt
    ("Sitzung des Ausschusses Klima, Umwelt und Grün", "Ausschuss für Klima, Umwelt und Grün",
     "Ausschuss für Klima, Umwelt und Grün"),
    ("Sitzung des Ausschusses für Schule und Weiterbildung", "Ausschuss Schule und Weiterbildung",
     "Ausschuss Schule und Weiterbildung"),
    (f"Sitzung des Ausschusses {B10[len('Ausschuss '):]}", B10_BISHER, B10_BISHER),
    ("Sitzung des Ausschusses Allgemeine Verwaltung und Rechtsfragen/Vergabe/Internationales",
     "Ausschuss Allgemeine Verwaltung und Rechtsfragen / Vergabe / Internationales",
     "Ausschuss Allgemeine Verwaltung und Rechtsfragen / Vergabe / Internationales"),
    # wie bisher: Satzzeichen, Genitiv, unbekannte Gremien bleiben beim Namen aus der Sitzung
    ("Sitzung des Jugendhilfeausschusses", "Jugendhilfeausschuss", "Jugendhilfeausschuss"),
    ("Sitzung des Ausschusses für Kinder-, Jugend und Familie", "Ausschuss für Kinder, Jugend und Familie",
     "Ausschuss für Kinder, Jugend und Familie"),
    ("Sitzung des Rates", "Rat", "Rat"),
    ("Sitzung des Liegenschaftsausschusses", "Mobilitätsausschuss", "Liegenschaftsausschuss"),
])
def test_gremium_aus_sitzungsname(sitzung, bekannt, erwartet):
    names = {"https://example.invalid/oparl/organizations/o1": bekannt}
    assert export.gremium_der_sitzung({"name": sitzung, "organization": []}, names) == erwartet
    # mit Organisation gilt immer ihr Name
    assert export.gremium_der_sitzung({"name": sitzung, "organization": list(names)}, names) == bekannt


def test_bahn_finanzausschuss():
    """Themenseiten (deaktiviert): der Kölner Finanzausschuss (§ 11) wie der Bonner Name auf der Bahn „finanz“."""
    class T:
        bahn_gremien = {}
    assert dossier.bahn(T, "Finanzausschuss") == "finanz"
    assert dossier.bahn(T, "Ausschuss für Finanzen, Beteiligungen und Vergabe") == "finanz"
    assert dossier.bahn(T, "Mobilitätsausschuss") == "fach"


ORGS = [
    {"id": "o1", "name": "Mobilitätsausschuss", "short_name": "MobA", "classification": "Ausschuss"},
    {"id": "o2", "name": B10_BISHER, "short_name": "", "classification": "Ausschuss"},
    {"id": "o3", "name": "Unterausschuss Kulturbauten", "short_name": None, "classification": "Ausschuss"},
    {"id": "o4", "name": "Bezirksvertretung 7 (Porz)", "short_name": "BV 7", "classification": "Bezirksvertretung"},
    {"id": "o5", "name": "FinA", "short_name": "Finanzausschuss", "classification": None},
]


def test_abgleich_befunde():
    zeilen = ausschuesse.abgleich(ORGS)
    befund = {(z[0], z[2]): z[-1] for z in zeilen}
    assert befund[("§ 17", "Mobilitätsausschuss")] == "gleich"
    assert befund[("§ 10", B10_BISHER)] == "Schreibvariante"
    assert befund[("§ 11", "FinA")] == "Schreibvariante"          # über den Kurznamen
    assert befund[("", "Unterausschuss Kulturbauten")] == "nur in OParl"
    assert ("", "Bezirksvertretung 7 (Porz)") not in befund         # kein Ausschuss
    fehlt = {z[0] for z in zeilen if z[-1] == "fehlt in OParl"}
    assert fehlt == {f"§ {n}" for n in range(7, 24)} - {"§ 10", "§ 11", "§ 17"}


def test_abgleich_schreiben(tmp_path, capsys):
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE organization (id TEXT PRIMARY KEY, name TEXT, short_name TEXT, org_type TEXT, "
                  "classification TEXT, label TEXT, start_date TEXT, end_date TEXT, web TEXT, source TEXT)")
        c.executemany("INSERT INTO organization (id, name, short_name, classification) VALUES (?, ?, ?, ?)",
                      [(o["id"], o["name"], o["short_name"], o["classification"]) for o in ORGS])
    ziel = tmp_path / "abgleich.tsv"
    zeilen = ausschuesse.abgleich_schreiben(db, ziel)
    gelesen = list(csv.reader(ziel.open(encoding="utf-8"), delimiter="\t"))
    assert gelesen[0] == ausschuesse.SPALTEN and len(gelesen) == len(zeilen) + 1
    assert "gleich 1" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        ausschuesse.abgleich_schreiben(tmp_path / "fehlt.sqlite", ziel)


def test_audit_nennt_jeden_paragrafen_mit_namen_laut_satzung():
    """inventur/ausschuesse_zusto.tsv führt jeden Ausschuss der §§ 7–23 mit seinem Namen laut Satzung."""
    zeilen = list(csv.DictReader((ROOT / "inventur" / "ausschuesse_zusto.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert list(zeilen[0]) == ["name_zusto", "paragraf", "name_im_code", "datei", "befund", "massnahme", "hinweis"]
    assert {z["befund"] for z in zeilen} <= {"gleich", "Schreibvariante", "fehlt im Code", "nur im Code"}
    for nr, name, _ in ausschuesse.AUSSCHUESSE:
        assert any(z["paragraf"] == f"§ {nr}" and z["name_zusto"] == name for z in zeilen), nr
    # die genannten Dateien gibt es
    pfade = {p for z in zeilen for p in re.findall(r"(?:pipeline|site|tools|tests)/[\w/.-]+\.(?:py|js|html)|\b[A-Z]+\.md",
                                                   z["datei"])}
    assert "pipeline/geocode.py" in pfade and "TECHNIK.md" in pfade
    for pfad in pfade:
        assert (ROOT / pfad).exists(), pfad
