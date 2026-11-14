"""Ämtertabelle (data/aemter/aemter_koeln.tsv, tools/aemter_tabelle.py, pipeline/aemter.py) und Zuordnung der
Federführung im Export.

Orakel: eigene Lesung des Geschäfts- und Dezernatsverteilungsplans der Stadt Köln, Stand 01.11.2026 (eine Seite A3,
gelesen am 13.11.2026 über das Textlayout und die Wortkoordinaten des PDFs, nicht über den Erzeuger): Bereiche der
Dezernate, alle 48 Dienststellen mit Dezernat und Namen, alle 26 Einheiten der Dezernate, alle 17 vierstelligen
Nummern mit Punkt, vollständige Untereinheiten von vier Dienststellen und mehrzeilige Namen. Das PDF liegt nicht im
Repository (Lizenz nicht angegeben); mit RATSATLAS_GDVP_PDF=<Pfad> prüft ein Test zusätzlich, dass der Erzeuger die
Tabelle byte-gleich wiederherstellt. Der Leser des Layouts wird außerdem an erfundenen Wortlisten geprüft. Keine
Anfragen an Server der Stadt."""
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import aemter, build, config, export

ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.stadt-koeln.de/mediaasset/content/verwaltung/geschaefts-und-dezernatsverteilungsplan.pdf"
SHA = "fdcce67dca0d9b3411b3716fb5241571b69fb0c00483bd8d1bfdb6bf552a61c4"
ABGERUFEN = "2026-11-13T22:24:35Z"


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _tool("aemter_tabelle")

# --- Orakel (eigene Lesung des Plans) ---------------------------------------------------------------------------------

BEREICHE = {"OB": "", "I": "Allgemeine Verwaltung, Personal und Digitalisierung", "II": "Finanzen und Gleichstellung",
            "III": "Mobilität", "IV": "Bildung, Jugend und Sport", "V": "Soziales, Gesundheit und Wohnen",
            "VI": "Stadtentwicklung, Wirtschaft, Planen und Bauen", "VII": "Kunst und Kultur",
            "VIII": "Klima, Umwelt, Grün und Liegenschaften", "IX": "Sicherheit, Ordnung und Recht"}
DIENSTSTELLEN = {
    "OB": {"01": "Amt des Oberbürgermeisters", "13": "Amt für Presse- und Öffentlichkeitsarbeit",
           "14": "Rechnungsprüfungsamt", "16": "Amt für Integration und Vielfalt"},
    "I": {"02-1": "Bürgeramt Innenstadt", "02-2": "Bürgeramt Rodenkirchen", "02-3": "Bürgeramt Lindenthal",
          "02-4": "Bürgeramt Ehrenfeld", "02-5": "Bürgeramt Nippes", "02-6": "Bürgeramt Chorweiler",
          "02-7": "Bürgeramt Porz", "02-8": "Bürgeramt Kalk", "02-9": "Bürgeramt Mülheim",
          "11": "Personal- und Verwaltungsmanagement", "12": "Digitalisierung und Informationstechnik (DigIT)",
          "34": "Bürgerdienste"},
    "II": {"03": "Amt für Gleichstellung von Frauen und Männern", "20": "Kämmerei", "21": "Steueramt"},
    "III": {"62": "Bauverwaltungsamt", "64": "Amt für Verkehrsmanagement", "66": "Amt für Straßen und Radwegebau",
            "68": "Amt für nachhaltige Mobilitätsentwicklung", "69": "Amt für Brücken, Tunnel und Stadtbahnbau"},
    "IV": {"40": "Amt für Schulentwicklung", "42": "Amt für Weiterbildung", "51": "Amt für Kinder, Jugend und Familie",
           "52": "Sportamt"},
    "V": {"50": "Amt für Soziales, Arbeit und Senioren", "53": "Gesundheitsamt", "56": "Amt für Wohnungswesen"},
    "VI": {"15": "Amt für Stadtentwicklung und Statistik", "26": "Gebäudewirtschaft der Stadt Köln (e. E.)",
           "48": "Stadtkonservator*in, Amt für Denkmalschutz und Denkmalpflege", "61": "Stadtplanungsamt",
           "63": "Bauaufsichtsamt"},
    "VII": {"41": "Kulturamt", "43": "Stadtbibliothek", "44": "Historisches Archiv mit Rheinischem Bildarchiv",
            "46": "Bühnen (e. E.)", "47": "Orchester (e. E.)"},
    "VIII": {"23": "Amt für Liegenschaften, Vermessung und Kataster", "57": "Umwelt- und Verbraucherschutzamt",
             "67": "Amt für Landschaftspflege und Grünflächen"},
    "IX": {"30": "Amt für Recht, Vergabe und Versicherungen", "32": "Amt für öffentliche Ordnung",
           "33": "Ausländeramt",
           "37": "Berufsfeuerwehr, Amt für Feuerschutz, Rettungsdienst und Bevölkerungsschutz"},
}
EINHEITEN = {
    "OB/1": "Büro des Oberbürgermeisters, pers. Referent", "OB/2": "Datenschutzbeauftragte*r der Stadt Köln",
    "I/1": "Dezernatsbüro", "I/2": "Betriebliches Gesundheitsmanagement", "I/3": "Strategisches Büroflächenmanagement",
    "II/1": "Dezernatsbüro",
    "II/2": "Stabsstelle für Beteiligungssteuerung und öffentliches Finanz- und Unternehmensrecht",
    "III/1": "Dezernatsbüro", "III/2": "Stabsstelle Kommunikation", "IV/1": "Dezernatsbüro",
    "IV/2": "Integrierte Jugendhilfe- und Schulentwicklungsplanung", "V/1": "Dezernatsbüro",
    "V/3": "Sozialplanung/Sozialberichterstattung", "VI/1": "Dezernatsbüro", "VI/2": "Stabsstelle Wirtschaftsförderung",
    "VI/3": "Wohnungsbauleitstelle", "VI/4": "Stadtbau im Quartier", "VI/5": "Parkstadt Süd (e.E.)",
    "VII/0": "Institutionelle Belange", "VII/1": "Dezernatsbüro",
    "VII/2": "Kulturelle Infrastruktur, Strategie, Belange der freien Szene", "VIII/1": "Dezernatsbüro",
    "VIII/2": "Koordinationsstelle Klimaschutz", "VIII/3": "e. E-Abfallwirtschaftsbetrieb (AWB)",
    "IX/1": "Dezernatsbüro", "IX/2": "Zentrum für Kriminalprävention und Sicherheit",
}
# (Dezernat, Name, Punkt, übergeordnete Dienststelle)
PUNKT = {
    "1000": ("I", "Zentrale Dienste", "•", ""), "1100": ("I", "Zusatzversorgung und Beihilfe", "•", "11"),
    "5110": ("IV", "Familienberatung und Schulpsychologischer Dienst Stadt Köln", "•", "51"),
    "5111": ("IV", "Kinder- und Jugendpädagogische Einrichtung der Stadt Köln", "•", "51"),
    "5000": ("V", "Jobcenter", "●", "50"), "4101": ("VII", "Puppenspiele", "●", "41"),
    "4510": ("VII", "Wallraf-Richartz-Museum/Fondation Corboud (e. E).", "●", ""),
    "4511": ("VII", "Museum Ludwig", "●", ""),
    "4512": ("VII", "Römisch-Germanisches Museum/Archäologische Bodendenkmalpflege", "●", ""),
    "4513": ("VII", "Rautenstrauch-Joest-Museum", "●", ""), "4514": ("VII", "Museum für Angewandte Kunst", "●", ""),
    "4515": ("VII", "Museum für Ostasiatische Kunst", "●", ""), "4516": ("VII", "Museum Schnütgen", "●", ""),
    "4518": ("VII", "Kölnisches Stadtmuseum", "●", ""), "4520": ("VII", "NS-Dokumentationszentrum", "●", ""),
    "4522": ("VII", "Museumsdienst", "●", ""), "4523": ("VII", "Kunst- und Museumsbibliothek", "●", ""),
}
# vollständige Untereinheiten einzelner Dienststellen in der Reihenfolge des Plans
UNTER = {
    "61": ["610", "611", "612", "613", "614", "615"],
    "26": ["26/0", "26/1", "260", "261", "262", "263", "264", "265", "266", "267", "268", "269"],
    "37": ["37/1", "37/2", "37/3", "37/4", "37/5", "37/6", "37/7", "370", "371", "372", "373", "374", "375", "376",
           "379"],
    "43": ["43/1", "43/2", "43/3", "430", "431", "432", "433", "435"],
}
# mehrzeilige oder besondere Namen
NAMEN = {
    "620": "Allgemeine Verwaltungs-, Grundsatz-, Erschließungs- und Straßenrechtsangelegenheiten",
    "622": "Zentrales Verwaltungsmanagement für die - Ämter 64, 66 und 68",
    "572": "Untere Immissionsschutz-, Wasser- und Abfallwirtschaftsbehörde (IWA)",
    "322": "Straßenverkehrs- und allgemeine Ordnungsangelegenheiten, Bußgeldstelle",
    "611": "Städtebauliche Planung und Bebauungsplanung für die Stadtbezirke 1, 2, 5",
    "520": "Sportentwicklungsplanung, Sportförderungspersonal, Verwaltung und Organisation",
    "02-6/4": "Schwerbehindertenrecht und Bundeselterngeld", "46/0-46/2": "Werkleitung", "47/02-09": "Orchester",
    "37/6": "Institut für Schutz und Rettung der Feuerwehr Köln", "12/2": "Koordinierungsbüro für digitale Netze und "
    "Breitbandausbau", "444": "Städtische Überlieferung seit 1815 und Grundsatzfragen",
}


@pytest.fixture(scope="module")
def zeilen():
    return aemter.lesen()


def test_tabelle_herkunft(zeilen):
    """Jede Zeile mit Stand, Fundstelle auf Seite 1, Adresse, Abrufzeit und Prüfsumme des geladenen PDFs."""
    assert zeilen and {tuple(z) for z in zeilen} == {aemter.SPALTEN}
    assert {z["gueltig_ab"] for z in zeilen} == {"2026-11-01"}
    assert {(z["quelle"], z["abgerufen"], z["sha256"]) for z in zeilen} == {(URL, ABGERUFEN, SHA)}
    for z in zeilen:
        spalte = f"Spalte Dezernat {z['dezernat']}"
        assert z["fundstelle"].startswith("Seite 1, ") and spalte in z["fundstelle"], z
        assert z["ebene"] in aemter.EBENEN
        assert z["kennung"] == (z["dezernat"] if z["ebene"] == "dezernat" else f"{z['dezernat']}/{z['dienststelle']}")


def test_dezernate_und_dienststellen_wie_gelesen(zeilen):
    dez = {z["dezernat"]: z["name"] for z in zeilen if z["ebene"] == "dezernat"}
    assert dez == BEREICHE
    ds = {}
    for z in zeilen:
        if z["ebene"] == "dienststelle":
            ds.setdefault(z["dezernat"], {})[z["dienststelle"]] = z["name"]
    assert ds == DIENSTSTELLEN
    assert sum(map(len, ds.values())) == 48
    einheiten = {z["dienststelle"]: z["name"] for z in zeilen if z["ebene"] == "dezernatseinheit"}
    assert einheiten == EINHEITEN
    punkt = {z["dienststelle"]: (z["dezernat"], z["name"], z["markierung"], z["uebergeordnet"]) for z in zeilen
             if z["ebene"] == "punktdienststelle"}
    assert punkt == PUNKT


def test_untereinheiten_wie_gelesen(zeilen):
    for ds, erwartet in UNTER.items():
        assert [z["dienststelle"] for z in zeilen if z["uebergeordnet"] == ds and z["ebene"] == "untereinheit"] \
            == erwartet, ds
    namen = {z["dienststelle"]: z["name"] for z in zeilen}
    for code, name in NAMEN.items():
        assert namen[code] == name, code
    unter = [z for z in zeilen if z["ebene"] == "untereinheit"]
    nummern = {z["dienststelle"]: z["dezernat"] for z in zeilen}
    # jede Untereinheit unter einer Dienststelle desselben Dezernats; jede Nummer einmal
    assert all(nummern.get(z["uebergeordnet"]) == z["dezernat"] for z in unter)
    assert len(nummern) == len(zeilen) - 10 + 1   # zehn Dezernate, Schlüssel "" für alle zusammen
    kurz = {z["dienststelle"]: z["kurzname"] for z in zeilen if z["kurzname"]}
    assert kurz == {"12": "DigIT", "VIII/3": "AWB", "572": "IWA"}
    ee = {z["dienststelle"] for z in zeilen if z["eigenbetriebsaehnlich"]}
    assert ee == {"26", "46", "47", "VI/5", "VIII/3", "4510"}


def test_keine_personen(zeilen):
    """Die Kopfzeilen mit Funktion und Name der Person (Schrift 8 pt) fehlen; „N.N.“ (offene Stelle) ebenso."""
    texte = " ".join(z["name"] for z in zeilen)
    for wort in ("Beigeordnete", "Stadtdirektorin", "Stadtkämmerin", "N.N.", "Prof.", "Dr."):
        assert wort not in texte


@pytest.mark.skipif(not os.environ.get("RATSATLAS_GDVP_PDF"), reason="PDF des Plans nicht im Repository")
def test_erzeuger_stellt_tabelle_wieder_her(tmp_path):
    ziel = tmp_path / "aemter.tsv"
    GEN.main(["--pdf", os.environ["RATSATLAS_GDVP_PDF"], "--url", URL, "--abgerufen", ABGERUFEN,
              "--tabelle", str(ziel)])
    assert ziel.read_bytes() == aemter.TABELLE.read_bytes()
    GEN.main(["--pdf", os.environ["RATSATLAS_GDVP_PDF"], "--url", URL, "--abgerufen", ABGERUFEN,
              "--tabelle", str(ziel)])   # zweiter Lauf ersetzt denselben Plan
    assert ziel.read_bytes() == aemter.TABELLE.read_bytes()


# --- Leser des Layouts an erfundenen Wortlisten -----------------------------------------------------------------------

def _w(x, y, text, h=5.2):
    """Wörter einer Zeile ab x (3 pt je Zeichen, 3 pt Abstand)."""
    out = []
    for t in text.split(" "):
        out.append((x, y, x + 3 * len(t), y + h, t))
        x += 3 * len(t) + 3
    return out


def _seite(spalte_ob=(), spalte_i=(), titel=True, stand="01.12.2026"):
    ws = []
    if titel:
        ws += _w(100, 15, "Geschäfts- und Dezernatsverteilungsplan der Stadt Köln", 15)
    ws += _w(900, 18, f"Stand: {stand}", 11.1)
    ws += _w(55, 39, "Dezernat OB", 6.5) + _w(180, 39, "Dezernat I", 6.5)
    # Funktion und Person (8 pt), eine offene Stelle in 7,5 pt weit über dem Bereich (wie „N.N.“ bei Dezernat IX)
    ws += _w(150, 54, "Funktion Person", 8.0) + _w(160, 55, "Erfundener", 7.5) + _w(150, 79, "Bereich", 7.5)
    for x, zeilen in ((18, spalte_ob), (134, spalte_i)):
        for dx, y, text, h in zeilen:
            ws += _w(x + dx, y, text, h)
    ws += _w(19, 620, "Fußzeile mit Angaben", 7.4) + _w(19, 640, "Legende:", 7.9) + _w(19, 662, "•", 11.1)
    return ws


OB = [(0, 110, "OB/1 Büro", 5.6), (0, 120, "01 Amt des Beispiels", 6.5), (12, 128, "mit Zusatz", 6.5),
      (0, 136, "010 Verwaltungs- und Grundsatz-", 5.2), (12, 142, "angelegenheiten", 5.2),
      (0, 148, "011 Untere Wasser-", 5.2), (12, 154, "und Abfallbehörde (UWA )", 5.2),
      (0, 160, "01/1 Teil -", 5.2), (12, 166, "Ämter 1 und 2", 5.2)]
I = [(0, 110, "I/1 Dezernatsbüro", 5.6), (0, 120, "12 Amt für Muster,", 6.5), (0, 128, "Beispiele und Proben", 6.5),
     (0, 136, "120 Abteilung", 5.2), (0, 142, "121 - 123 Bereich", 5.2), (0, 148, "•", 7.8), (5, 149.6, "1200 Dienst", 5.6),
     (0, 160, "● 4500 Museum/", 5.6), (12, 166, "Archiv (e. E).", 5.6), (0, 174, "12/0 - 12/2 Leitung", 5.2)]


def test_layout_erfunden():
    stand, zl = GEN.seite_lesen(_seite(OB, I[:3] + I[5:]))
    assert stand == "2026-12-01"
    je = {z["kennung"]: z for z in zl}
    assert je["OB"]["name"] == "" and je["I"]["name"] == "Bereich"   # nur der unterste Block in 7,5 pt
    assert je["OB/OB/1"]["ebene"] == "dezernatseinheit"
    assert je["OB/01"]["name"] == "Amt des Beispiels mit Zusatz"
    assert je["OB/010"]["name"] == "Verwaltungs- und Grundsatzangelegenheiten" and je["OB/010"]["uebergeordnet"] == "01"
    assert je["OB/011"]["name"] == "Untere Wasser- und Abfallbehörde (UWA)" and je["OB/011"]["kurzname"] == "UWA"
    assert je["OB/01/1"]["name"] == "Teil - Ämter 1 und 2"
    assert je["I/12"]["name"] == "Amt für Muster, Beispiele und Proben"   # Fortsetzung am Rand, gleiche Schrift
    assert je["I/1200"]["markierung"] == "•" and je["I/1200"]["uebergeordnet"] == "12"
    assert je["I/4500"]["markierung"] == "●" and je["I/4500"]["name"] == "Museum/Archiv (e. E)."
    assert je["I/4500"]["eigenbetriebsaehnlich"] == "ja" and je["I/4500"]["uebergeordnet"] == ""
    assert je["I/12/0-12/2"]["name"] == "Leitung" and je["I/12/0-12/2"]["uebergeordnet"] == "12"
    assert [z["kennung"] for z in zl] == ["OB", "OB/OB/1", "OB/01", "OB/010", "OB/011", "OB/01/1", "I", "I/I/1", "I/12",
                                          "I/1200", "I/4500", "I/12/0-12/2"]
    assert [z["fundstelle"] for z in zl if z["dezernat"] == "I"][:3] == [
        "Seite 1, Kopf der Spalte Dezernat I", "Seite 1, Spalte Dezernat I, Eintrag 1",
        "Seite 1, Spalte Dezernat I, Eintrag 2"]
    assert "Fußzeile" not in json.dumps(zl, ensure_ascii=False) and "Person" not in json.dumps(zl, ensure_ascii=False)


@pytest.mark.parametrize("ob, i, fehler", [
    # Untereinheit ohne Dienststelle in der Spalte
    ([(0, 110, "02 Amt", 6.5)], [(0, 110, "030 Abteilung", 5.2)], "ohne Dienststelle"),
    # Zeile am Rand ohne Nummer in anderer Schrift
    ([(0, 110, "01 Amt", 6.5), (0, 118, "Abweichend", 5.2)], [(0, 110, "12 Amt", 6.5)], "Zeile ohne Eintrag"),
    # Schriftgröße passt nicht zur Ebene
    ([(0, 110, "01 Amt", 5.2)], [(0, 110, "12 Amt", 6.5)], "passt nicht zur Ebene"),
    # Punkt ohne folgende Zeile
    ([(0, 110, "01 Amt", 6.5), (0, 130, "•", 7.8)], [(0, 110, "12 Amt", 6.5)], "Marker"),
    # Einheit eines anderen Dezernats
    ([(0, 110, "I/1 Büro", 5.6)], [(0, 110, "12 Amt", 6.5)], "eines anderen Dezernats"),
])
def test_layout_abbruch(ob, i, fehler):
    with pytest.raises(ValueError, match=fehler):
        GEN.seite_lesen(_seite(ob, i))


def test_layout_ohne_titel_oder_doppelt():
    with pytest.raises(ValueError, match="Titel"):
        GEN.seite_lesen(_seite(OB, I, titel=False))
    with pytest.raises(ValueError, match="doppelt"):
        GEN.plan_lesen([_seite([(0, 110, "12 Amt", 6.5)], [(0, 110, "12 Amt", 6.5)])])


def test_zusammenfuehren_ersetzt_nur_denselben_plan():
    alt = [{"gueltig_ab": "2026-11-01", "x": 1}, {"gueltig_ab": "2026-12-01", "x": 2}]
    neu = [{"gueltig_ab": "2026-12-01", "x": 3}, {"gueltig_ab": "2026-12-01", "x": 4}]
    assert GEN.zusammenfuehren(alt, neu) == [alt[0]] + neu
    aelter = [{"gueltig_ab": "2026-10-01", "x": 5}]
    assert GEN.zusammenfuehren(alt, aelter) == aelter + alt


def test_erneute_pruefung_verlaengert_nur_mit_gleicher_pruefsumme():
    """Dasselbe PDF mit neuer Abrufzeit ersetzt nur die Abrufzeit (der Plan ist länger belegt); ein anderes PDF unter
    demselben Stand bricht ab, außer mit ersetzen (Entscheidung von Hand)."""
    alt = [{"gueltig_ab": "2026-11-01", "abgerufen": ABGERUFEN, "sha256": SHA, "name": "A"}]
    gleich = [{**alt[0], "abgerufen": "2026-12-14T22:30:00Z"}]
    assert GEN.zusammenfuehren(alt, gleich) == gleich
    anders = [{**gleich[0], "sha256": "0" * 64, "name": "B"}]
    with pytest.raises(ValueError, match="anderes PDF"):
        GEN.zusammenfuehren(alt, anders)
    assert GEN.zusammenfuehren(alt, anders, ersetzen=True) == anders
    neuer_stand = [{**anders[0], "gueltig_ab": "2026-12-01"}]
    assert GEN.zusammenfuehren(alt, neuer_stand) == alt + neuer_stand


# --- Zuordnung ---------------------------------------------------------------------------------------------------------

# letzte Prüfung je erfundenem Plan (Abrufzeit in UTC): der frühere Plan bis zum 20.10.2026 belegt, der jüngere bis zum
# 13.11.2026
ABRUF = {"2026-10-01": "2026-10-20T21:00:00Z", "2026-11-01": "2026-11-13T22:24:35Z"}


def _zeile(stand, dez, code, ebene, name, ober="", kurz=""):
    return {"gueltig_ab": stand, "dezernat": dez, "dienststelle": code, "kennung": f"{dez}/{code}" if code else dez,
            "ebene": ebene, "uebergeordnet": ober, "name": name, "kurzname": kurz, "eigenbetriebsaehnlich": "",
            "markierung": "", "fundstelle": f"Seite 1, Spalte Dezernat {dez}", "quelle": "https://example.invalid/plan",
            "abgerufen": ABRUF.get(stand, ""), "sha256": ""}


ERFUNDEN = [
    _zeile("2026-10-01", "V", "", "dezernat", "Früherer Zuschnitt"),
    _zeile("2026-10-01", "V", "61", "dienststelle", "Stadtplanungsamt"),
    _zeile("2026-11-01", "VI", "", "dezernat", "Planen"), _zeile("2026-11-01", "II", "", "dezernat", "Finanzen"),
    _zeile("2026-11-01", "II", "II/2", "dezernatseinheit", "Stabsstelle"),
    _zeile("2026-11-01", "VI", "61", "dienststelle", "Stadtplanungsamt"),
    _zeile("2026-11-01", "VI", "610", "untereinheit", "Verwaltung", "61"),
    _zeile("2026-11-01", "VI", "61/1", "untereinheit", "Amtsweite Themen", "61"),
    _zeile("2026-11-01", "VI", "62", "dienststelle", "Bauamt (e. E.)", kurz="BA"),
    _zeile("2026-11-01", "VI", "620", "untereinheit", "Verwaltung", "62"),
]


@pytest.mark.parametrize("name, kennung, datum, status, nummer", [
    (None, "VI/61", "2026-11-05", aemter.EINDEUTIG, "61"),
    (None, " vi / 61 ", "2026-11-05", aemter.EINDEUTIG, "61"),
    (None, "VI/61/610", "2026-11-05", aemter.EINDEUTIG, "610"),
    (None, "VI/610", "2026-11-05", aemter.EINDEUTIG, "610"),
    (None, "VI/61/9", "2026-11-05", aemter.NUR_DIENSTSTELLE, "61"),
    # dreiteilig mit Nummer in der Mitte: nur bis zur Dienststelle, ob der Plan „61/1“ führt oder nicht („62/1“)
    (None, "VI/61/1", "2026-11-05", aemter.NUR_DIENSTSTELLE, "61"),
    (None, "VI/62/1", "2026-11-05", aemter.NUR_DIENSTSTELLE, "62"),
    (None, "II/61/1", "2026-11-05", aemter.DEZERNAT_WEICHT_AB, None),
    (None, "VI/61/610/2", "2026-11-05", aemter.NUR_DIENSTSTELLE, "61"),   # vierteilig ebenso
    # der Name bestätigt die Untereinheit in der Schreibweise des Plans
    ("VI/61/1 Amtsweite Themen", None, "2026-11-05", aemter.EINDEUTIG, "61/1"),
    ("VI/61/1 Stadtplanungsamt", None, "2026-11-05", aemter.NUR_DIENSTSTELLE, "61"),
    ("VI/61/1 Anderes Amt", None, "2026-11-05", aemter.NAME_WEICHT_AB, None),
    (None, "II/II/2", "2026-11-05", aemter.EINDEUTIG, "II/2"),
    (None, "II/2", "2026-11-05", aemter.EINDEUTIG, "II/2"),
    (None, "II/61", "2026-11-05", aemter.DEZERNAT_WEICHT_AB, None),
    (None, "VI/63", "2026-11-05", aemter.KEIN_TREFFER, None),
    (None, "VI", "2026-11-05", aemter.EINDEUTIG, ""),
    # dieselbe Kennung im früheren Plan: 61 gehörte zu Dezernat V, ein Dezernat VI gab es dort nicht
    (None, "VI/61", "2026-10-15", aemter.KEIN_TREFFER, None),
    (None, "V/61", "2026-10-15", aemter.EINDEUTIG, "61"),
    (None, "V/61", "2026-09-30", aemter.VOR_PLAN, None),
    # belegt nur bis zur letzten Prüfung (Tag des Abrufs eingeschlossen), auch nicht bis zum Stand des nächsten Plans
    (None, "V/61", "2026-10-20", aemter.EINDEUTIG, "61"),
    (None, "V/61", "2026-10-21", aemter.NACH_PRUEFUNG, None),
    (None, "VI/61", "2026-10-31", aemter.NACH_PRUEFUNG, None),
    (None, "VI/61", "2026-11-13", aemter.EINDEUTIG, "61"),
    (None, "VI/61", "2026-11-14", aemter.NACH_PRUEFUNG, None),
    ("Stadtplanungsamt", None, "2027-06-01", aemter.NACH_PRUEFUNG, None),
    (None, "VI/61", None, aemter.OHNE_DATUM, None),
    (None, "VI/61", "13.11.2026", aemter.OHNE_DATUM, None),
    ("61 Stadtplanungsamt", None, "2026-11-05", aemter.EINDEUTIG, "61"),
    ("61 - Stadtplanungsamt", None, "2026-11-05", aemter.EINDEUTIG, "61"),
    ("61 – Stadtplanungsamt", None, "2026-11-05", aemter.EINDEUTIG, "61"),
    ("Amt 61", None, "2026-11-05", aemter.EINDEUTIG, "61"),
    ("stadtplanungsamt", None, "2026-11-05", aemter.EINDEUTIG, "61"),
    ("VI/61 Stadtplanungsamt", None, "2026-11-05", aemter.EINDEUTIG, "61"),
    ("61 Bauamt", None, "2026-11-05", aemter.NAME_WEICHT_AB, None),
    ("Bauamt", None, "2026-11-05", aemter.EINDEUTIG, "62"),          # ohne Klammerzusatz
    ("BA", None, "2026-11-05", aemter.EINDEUTIG, "62"),              # Kurzname
    ("Verwaltung", None, "2026-11-05", aemter.MEHRDEUTIG, None),
    ("Dezernat VI", None, "2026-11-05", aemter.EINDEUTIG, ""),
    ("Amt für Anderes", None, "2026-11-05", aemter.KEIN_TREFFER, None),
    (None, None, "2026-11-05", aemter.OHNE_ANGABE, None),
    # Kennung zählt vor dem Namen
    ("Bauamt", "VI/61", "2026-11-05", aemter.EINDEUTIG, "61"),
])
def test_zuordnung(name, kennung, datum, status, nummer):
    erg = aemter.Tabelle(ERFUNDEN).zuordnen(name=name, kennung=kennung, datum=datum)
    assert erg["status"] == status
    assert (erg["eintrag"]["dienststelle"] if erg["eintrag"] else None) == nummer
    if status in aemter.ZUGEORDNET + (aemter.NACH_PRUEFUNG,):
        assert erg["stand"]
    if erg["stand"]:
        stand = "2026-10-01" if datum < "2026-11-01" else "2026-11-01"
        assert (erg["stand"], erg["geprueft"]) == (stand, ABRUF[stand][:10])
    else:
        assert erg["geprueft"] is None


def test_plan_ohne_abrufzeit_bricht_ab():
    """Ohne Abrufzeit ist offen, bis wann der Plan belegt ist: Abbruch statt einer Gültigkeit ohne Ende."""
    with pytest.raises(ValueError, match="Abrufzeit"):
        aemter.Tabelle(ERFUNDEN + [{**_zeile("2026-12-01", "VI", "", "dezernat", "Neu"), "abgerufen": ""}])


def test_zuordnung_mit_der_tabelle():
    """Beispiele aus dem Plan vom 01.11.2026 (Orakel oben)."""
    tag = "2026-11-13"
    E, D = aemter.EINDEUTIG, aemter.NUR_DIENSTSTELLE
    erwartet = {("kennung", "VI/61"): (E, "VI/61"), ("kennung", "II/II/2"): (E, "II/II/2"),
                ("kennung", "OB/14"): (E, "OB/14"), ("kennung", "IV/51/513"): (E, "IV/513"),
                # dreiteilig mit Nummer in der Mitte: gleich behandelt, ob der Plan die Untereinheit in dieser
                # Schreibweise führt („51/1“, „37/1“, „21/1“, „02-6/4“) oder nicht („61/1“)
                ("kennung", "IV/51/1"): (D, "IV/51"), ("kennung", "VI/61/1"): (D, "VI/61"),
                ("kennung", "IX/37/1"): (D, "IX/37"), ("kennung", "II/21/1"): (D, "II/21"),
                ("kennung", "I/02-6/4"): (D, "I/02-6"),
                ("name", "IX/37/1 Grundsätzliche Angelegenheiten der FF"): (E, "IX/37/1"),
                ("name", "Amt für Straßen und Radwegebau"): (E, "III/66"), ("name", "DigIT"): (E, "I/12"),
                ("name", "Gebäudewirtschaft der Stadt Köln"): (E, "VI/26"), ("name", "37 Berufsfeuerwehr, Amt für "
                "Feuerschutz, Rettungsdienst und Bevölkerungsschutz"): (E, "IX/37")}
    for (art, angabe), (status, kennung) in erwartet.items():
        erg = aemter.zuordnen(**{art: angabe}, datum=tag)
        assert (erg["status"], erg["eintrag"]["kennung"]) == (status, kennung), angabe
    assert aemter.zuordnen(name="Verwaltung", datum=tag)["status"] == aemter.MEHRDEUTIG
    assert aemter.zuordnen(kennung="III/61", datum=tag)["status"] == aemter.DEZERNAT_WEICHT_AB
    assert aemter.zuordnen(kennung="VI/61", datum="2026-10-31")["status"] == aemter.VOR_PLAN
    # belegt bis zum Abruf am 13.11.2026, danach keine Zuordnung, bis der Plan erneut geprüft ist
    for angabe in ({"name": "Mobilität"}, {"kennung": "IV/51/1"}, {"kennung": "VI/61"}):
        assert aemter.zuordnen(**angabe, datum="2026-11-13")["status"] in aemter.ZUGEORDNET
        for datum in ("2026-11-14", "2027-06-01"):
            assert aemter.fuer_export(aemter.zuordnen(**angabe, datum=datum)) == {
                "status": aemter.NACH_PRUEFUNG, "methode": next(iter(angabe)), "stand": "2026-11-01",
                "geprueft": "2026-11-13"}, (angabe, datum)
    aus = aemter.fuer_export(aemter.zuordnen(kennung="VI/612", datum=tag))
    assert aus["dezernat_label"] == "Dezernat VI – Stadtentwicklung, Wirtschaft, Planen und Bauen"
    assert aus["uebergeordnet"]["label"] == "61 Stadtplanungsamt"
    assert aus["label"] == "612 Städtebauliche Planung und Bebauungsplanung für die Stadtbezirke 3, 4, 6"
    assert aus["fundstelle"] == ("Geschäfts- und Dezernatsverteilungsplan der Stadt Köln, Stand 01.11.2026, Seite 1, "
                                 "Spalte Dezernat VI, Eintrag 30")
    assert aus["stand"] == "2026-11-01" and aus["geprueft"] == "2026-11-13"
    assert aemter.fuer_export(aemter.zuordnen(name="Verwaltung", datum=tag)) == {
        "status": aemter.MEHRDEUTIG, "methode": "name", "stand": "2026-11-01", "geprueft": "2026-11-13"}


def test_quellenangaben_folgen_der_tabelle():
    """README, LICENSE-DATA.md und Technikseite nennen Stand und letzte Prüfung des jüngsten Plans; jedes Datum neben
    dem Plan ist Stand bzw. Prüfung eines Plans der Tabelle (ein weiterer Plan macht veraltete Stellen sichtbar)."""
    from pipeline import technikseite
    t = aemter.tabelle()
    p = t.neuester()
    staende = {aemter.stand_text(x.stand) for x in t.plaene}
    pruefungen = {aemter.stand_text(x.geprueft) for x in t.plaene}
    for datei in (ROOT / "README.md", ROOT / "data" / "LICENSE-DATA.md"):
        zeilen = [z for z in datei.read_text(encoding="utf-8").splitlines() if "Dezernatsverteilungsplan" in z]
        text = "\n".join(zeilen)
        assert f"Stand {aemter.stand_text(p.stand)}" in text, datei
        assert re.search(rf"(?:geprüft|abgerufen) am {re.escape(aemter.stand_text(p.geprueft))}", text), datei
        assert set(re.findall(r"Stand (\d\d\.\d\d\.\d{4})", text)) <= staende, datei
        assert set(re.findall(r"(?:geprüft|abgerufen) am (\d\d\.\d\d\.\d{4})", text)) <= pruefungen, datei
    (eintrag,) = technikseite.weitere_quellen()
    assert aemter.quellenangabe() in eintrag[2] and eintrag[3] == p.zeilen[0]["quelle"]
    assert aemter.quellenangabe() == "Stand 01.11.2026, zuletzt geprüft am 13.11.2026"


def test_plan_mit_doppelter_nummer_bricht_ab():
    with pytest.raises(ValueError, match="doppelt"):
        aemter.Tabelle(ERFUNDEN + [_zeile("2026-11-01", "II", "61", "dienststelle", "Zweites Amt")])


# --- Export -------------------------------------------------------------------------------------------------------

@pytest.fixture
def testdaten(oparl, monkeypatch):
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    _tool("testdaten").main()


def test_export_federfuehrung_mit_aemtertabelle(testdaten, capsys):
    """Testdaten: Federführung aus underDirectionOf; ab dem 01.11.2026 der Plan, davor ohne Zuordnung (Status), in den
    Gebietsdateien, im Prüfprotokoll und im Log; unbekannte Organisation bleibt ohne Zuordnung."""
    build.build()
    export.export()
    out = capsys.readouterr().out
    db = sqlite3.connect(config.DB)
    roh = {r[0]: (r[1], r[2]) for r in db.execute(
        "SELECT p.reference, p.date, o.name FROM paper p JOIN organization o ON o.id = p.under_direction_of")}
    assert roh
    gesehen = {}
    for f in [f for d in ("ortsteile", "bezirke", "ohne-ortsbezug") for f in (config.EXPORT / config.STADT / d).glob("*.json")]:
        for p in json.loads(f.read_text())["papers"]:
            for r in p["responsibility"]:
                if r["kind"] == "federfuehrend":
                    gesehen[p["reference"]] = r
    assert set(gesehen) == set(roh)
    for ref, (datum, name) in roh.items():
        a = gesehen[ref]["aemtertabelle"]
        assert gesehen[ref]["label"] == name   # die Organisation bleibt, wie die Quelle sie nennt
        erwartet = aemter.zuordnen(name=name, datum=datum)
        assert a["status"] == erwartet["status"]
        if datum < "2026-11-01":
            assert a == {"status": aemter.VOR_PLAN, "methode": "name"}
        elif datum > "2026-11-13":   # nach dem Abruf des Plans: nicht belegt, keine Zuordnung
            assert a == {"status": aemter.NACH_PRUEFUNG, "methode": "name", "stand": "2026-11-01",
                         "geprueft": "2026-11-13"}
        else:
            assert (a["stand"], a["geprueft"]) == ("2026-11-01", "2026-11-13")
            if name == "Amt für Straßen und Radwegebau":
                assert a["kennung"] == "III/66" and a["fundstelle"].endswith("Spalte Dezernat III, Eintrag 13")
    audit = (config.EXPORT / "audit_federfuehrung.tsv").read_text(encoding="utf-8").splitlines()
    assert audit[0].split("\t") == export.FEDERFUEHRUNG_AUDIT and len(audit) == len(roh) + 1
    spalten = [dict(zip(export.FEDERFUEHRUNG_AUDIT, z.split("\t"))) for z in audit[1:]]
    assert {(z["plan_stand"], z["plan_geprueft"]) for z in spalten if z["abgleich"] in aemter.ZUGEORDNET} \
        == {("2026-11-01", "2026-11-13")}
    assert f"Federführung: {len(roh)} Angaben bei 300 Vorlagen" in out


def test_seite_zeigt_zuordnung_abgeleitet_mit_fundstelle():
    """site/app.js (aemterZeile): bei einer Zuordnung Dezernat, übergeordnete Dienststelle und Eintrag mit „abgeleitet,
    über <Fundstelle>“, Text maskiert; ohne eindeutige Zuordnung nichts."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    teile = [re.search(m, app, re.S | re.M).group(0) for m in (
        r"^  const esc = .*?;\n", r"^  const AEMTER_ZUGEORDNET = .*?;\n", r"^  const aemterZeile = \(a\) => \{.*?^  \};\n")]
    a = aemter.fuer_export(aemter.zuordnen(kennung="VI/612", datum="2026-11-13"))
    b = {**aemter.fuer_export(aemter.zuordnen(kennung="II/II/2", datum="2026-11-13")), "label": "II/2 <b>"}
    c = aemter.fuer_export(aemter.zuordnen(name="Verwaltung", datum="2026-11-13"))
    code = "".join(teile) + f"console.log(JSON.stringify([{json.dumps(a)}, {json.dumps(b)}, {json.dumps(c)}, null]" \
                            f".map(aemterZeile)));"
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    aus = json.loads(r.stdout)
    assert aus[0] == ('<span class="aemter-zeile">Dezernat VI – Stadtentwicklung, Wirtschaft, Planen und Bauen · 61 '
                      'Stadtplanungsamt · 612 Städtebauliche Planung und Bebauungsplanung für die Stadtbezirke 3, 4, 6'
                      '</span> <span class="derived">abgeleitet, über Geschäfts- und Dezernatsverteilungsplan der Stadt '
                      'Köln, Stand 01.11.2026, Seite 1, Spalte Dezernat VI, Eintrag 30</span>')
    assert "II/2 &lt;b&gt;" in aus[1] and "Dezernat II – Finanzen und Gleichstellung" in aus[1]
    assert aus[2] == aus[3] == ""
