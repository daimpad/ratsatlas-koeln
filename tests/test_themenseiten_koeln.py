"""Kölner Themenseiten, Pilot „Verkehr und Mobilität“ (Entscheidung 24.11.2026 (3); Antworten zum Plan vom 25.11.2026,
1 A bis 5 A): Zuordnung nur über das Gremium (Kennung zur Laufzeit aus gremien.json), Wörter im Titel und Folgevorlagen;
Freigabe je Thema mit Prüfschalter nur für Testdaten; Seite und Übersicht im Bonner Aufbau mit Kölner Anpassungen;
Datenschutz und Herkunft. Alle Vorlagen, Drucksachen, Gremien und Orte sind erfunden; keine Anfragen nach außen."""
import ast
import dataclasses
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline import actors, check, config, dossier, export, freigaben, gebietsseiten, gremien, mitwirken, rssseite, seo, \
    themenseiten
from pipeline.themenseiten import verkehr

ROOT = Path(__file__).resolve().parents[1]
URL = "https://koeln.ratsatlas.de/"
T = verkehr.THEMA
P = "https://example.invalid/oparl/papers/"
O = "https://example.invalid/oparl/organizations/"
SATZUNG = "https://www.stadt-koeln.de/mediaasset/content/satzungen/zustaendigkeitsordnung_2026-06-02.pdf"


def _sitzung(tag, zeit="17:00", **zusatz):
    return {"date": tag, "time": zeit, "web": "https://example.invalid/sitzung", "source_object":
            f"https://example.invalid/oparl/meetings/{tag}", **zusatz}


def gremien_daten(mob_key="mob-1a2b3c4d", mit_mob=True, liste=None, weitere_ausschuesse=0):
    """Inhalt von gremien.json in der Form von gremien.daten (erfundene Gremien, Datenstand 21.11.2026); mit
    `weitere_ausschuesse` so viele erfundene Ausschüsse mehr (Kennung aus1, aus2, …)."""
    g = [{"key": "rat", "name": "Rat", "gruppe": "rat", "sitzungen_12m": 9, "vorlagen_12m": 200,
          "naechste_sitzung": _sitzung("2026-12-03"), "source_object": O + "rat"},
         {"key": "ha", "name": "Hauptausschuss", "gruppe": "ausschuss", "paragraf": 7, "sitzungen_12m": 4,
          "vorlagen_12m": 30, "naechste_sitzung": _sitzung("2026-11-21"), "folgende_sitzung": _sitzung("2026-12-10"),
          "source_object": O + "ha"},
         {"key": "fa", "name": "Finanzausschuss", "gruppe": "ausschuss", "paragraf": 11, "sitzungen_12m": 5,
          "vorlagen_12m": 20, "naechste_sitzung": _sitzung("2026-11-30"), "source_object": O + "fa"},
         {"key": "bv1", "name": "Bezirksvertretung 1 (Innenstadt)", "gruppe": "bezirksvertretung",
          "stadtbezirk": "Innenstadt", "sitzungen_12m": 8, "vorlagen_12m": 90,
          "naechste_sitzung": _sitzung("2026-11-26", hinweis="verschoben"), "source_object": O + "bv1"},
         {"key": "alt", "name": "[Testdaten] früherer Verkehrsausschuss", "gruppe": "uebrige", "end_date": "2025-10-31",
          "aufgeloest": True, "sitzungen_12m": 0, "vorlagen_12m": 3, "source_object": O + "alt"}]
    if mit_mob:
        g.insert(2, {"key": mob_key, "name": "Mobilitätsausschuss", "gruppe": "ausschuss", "paragraf": 17,
                     "web": "https://example.invalid/gremium", "sitzungen_12m": 6, "vorlagen_12m": 80,
                     "naechste_sitzung": _sitzung("2026-12-02", "15:00"), "source_object": O + "mob"})
    g += [{"key": f"aus{i}", "name": f"[Testdaten] Ausschuss {i}", "gruppe": "ausschuss", "paragraf": 20 + i,
           "source_object": O + f"aus{i}"} for i in range(1, weitere_ausschuesse + 1)]
    meta = {"datenstand": "2026-11-21", "zeitraum": {"seit": "2025-11-21", "bis": "2026-11-21"},
            "namensnennung": config.NAMENSNENNUNG,
            "zustaendigkeitsordnung": {"titel": "Zuständigkeitsordnung der Stadt Köln vom 02.06.2026", "url": SATZUNG}}
    if liste:
        meta["sitzungsliste_nicht_aktuell"] = liste
    return {"meta": meta, "gremien": g}


def station(key, gremium, tag, result=None, **zusatz):
    s = {"position": 0, "gremium": gremium, "start_date": f"{tag}T16:00:00+01:00", "cancelled": 0, "result": result,
         **zusatz}
    if key:
        s["gremium_key"] = key
    return s


def vorlage(ref, name, tag="2026-03-02", art="Beschlussvorlage", stationen=(), sup=(), sub=(), **zusatz):
    p = {"reference": ref, "name": f"[Testdaten] {name}", "date": tag, "paper_type": art,
         "web": "https://example.invalid/vorlage", "stand": "in Beratung", "process": list(stationen),
         "superordinated": [{"reference": r} for r in sup], "subordinated": [{"reference": r} for r in sub],
         "locations": [], "source_object": P + ref.replace("/", "-"), **zusatz}
    for i, s in enumerate(p["process"]):
        s["position"] = i
    return p


LAUF = dossier.Lauf(seit="2025-11-01", tor="mob-1a2b3c4d", tor_name="Mobilitätsausschuss",
                   gezaehlt=frozenset({"ha", "fa", "mob-1a2b3c4d"}))   # Ausschüsse wie gremien_daten()
MOB = ("mob-1a2b3c4d", "Mobilitätsausschuss")
BV = ("bv1", "Bezirksvertretung 1 (Innenstadt)")


def zu(name, stationen=(), lauf=LAUF, **k):
    return dossier.zuordnen(T, vorlage("1/2026", name, stationen=stationen, **k), lauf)


# --- Zuordnung --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("titel", ["Verkehrswertgutachten zu Tempo 30", "Mobilfunkmast an der Haltestelle",
                                   "Straßenbenennung an der Probebrücke", "Umbenennung einer Haltestelle",
                                   "Abfallbehälter am Radweg", "Verkehrssicherungspflicht an Bäumen der Probestraße"])
def test_ausschluss_vor_allen_regeln(titel):
    """Der Ausschluss gilt vor allen Regeln, auch mit Beratung im Mobilitätsausschuss und Wort eines Strangs."""
    assert zu(titel, [station(*MOB, "2026-04-01", "beschlossen")]) is None


@pytest.mark.parametrize("titel, strang, wort", [
    ("Bewohnerparken in Probestadt", "parken", "Bewohnerparken"),
    ("Parkraumbewirtschaftung an der Probestraße", "parken", "Parkraumbewirtschaftung"),
    ("Park and Ride am Stadtrand", "parken", "Park and Ride"),
    ("Taktverdichtung der Linie 13", "bus_bahn", "Taktverdichtung"),
    ("Barrierefreier Ausbau der Haltestelle Probeplatz", "bus_bahn", "Haltestelle"),
    ("KVB-Busnetz im Stadtbezirk", "bus_bahn", "KVB-Busnetz"),
    ("Radweg an der Probestraße", "rad_fuss", "Radweg"),
    ("Fahrradparken am Probeplatz", "rad_fuss", "Fahrradparken"),
    ("Neuer Zebrastreifen an der Probestraße", "rad_fuss", "Zebrastreifen"),
    ("Tempo 30 vor der Grundschule", "tempo", "Tempo 30"),
    ("Schulwegsicherung in Probestadt", "tempo", "Schulwegsicherung"),
    ("Sanierung der Probebrücke", "strassen", "Probebrücke"),
    ("Kreisverkehr an der Probestraße", "strassen", "Kreisverkehr"),
    ("Mobilitätskonzept für Probestadt", "weitere", "Mobilitätskonzept"),
    ("Ladeinfrastruktur im Stadtbezirk", "weitere", "Ladeinfrastruktur"),
    ("Lieferverkehr in der Innenstadt", "weitere", "Lieferverkehr"),
])
def test_straenge_treffer_mit_ganzem_wort(titel, strang, wort):
    """Je Strang ein Treffer; der Grund nennt das ganze Wort, ohne Beratung im Ausschuss nur den Titel."""
    assert zu(titel, [station(*BV, "2026-04-01")]) == (strang, f"Titel: „{wort}“")


@pytest.mark.parametrize("titel", [
    "Business Improvement District", "Bahnhofsmission: Zuschuss", "Richtlinie zur Förderung der Kultur",
    "Kegelbahn im Bürgerhaus", "Taktik der Verwaltung", "Kontaktstelle für Vereine", "Grad der Versiegelung",
    "Riesenrad auf dem Weihnachtsmarkt", "Fußballplatz: Kunstrasen", "Brückentag der Verwaltung",
    "Ampelkoalition im Rat", "Kita-Neubau an der Probestraße 12", "Zahlungsverkehr der Stadtkasse",
    "Geschäftsverkehr mit Banken", "Mobile Jugendarbeit", "Stadtpark: Pflege", "Gewerbepark Probestadt",
    "Umgestaltung des Probeplatzes", "Kulturticket für Studierende", "Luftverkehr am Flughafen"])
def test_fallen_ohne_zuordnung(titel):
    """Fallen der Wortlisten (und mehrdeutige Wörter ohne Beratung im Mobilitätsausschuss) ergeben keine Zuordnung."""
    assert zu(titel, [station(*BV, "2026-04-01")]) is None


def test_reihenfolge_bei_ueberschneidung():
    """Die erste passende Regel gilt (Parken, Bus und Bahn, Bauarbeiten an einer benannten Straße, Rad- und Fußverkehr,
    Tempo, Straßen, weitere): Fahrradstellplätze zählen nicht als Parken, aber der Bahnhof geht dem Fahrrad vor."""
    assert zu("Fahrradstellplätze am Bahnhof Probestadt")[0] == "bus_bahn"
    assert zu("Parkplätze an der Haltestelle Probeplatz")[0] == "parken"
    assert zu("Tempo 30 auf der Probebrücke")[0] == "tempo"
    assert zu("Radverkehr und Fahrbahnsanierung")[0] == "rad_fuss"
    assert list(dict.fromkeys(r.strang for r in T.regeln)) == ["parken", "bus_bahn", "strassen", "rad_fuss", "tempo",
                                                               "weitere"]
    assert [r.titel for r in T.regeln if r.strang == "strassen"] == [verkehr.STRASSENBAU, verkehr.STRASSEN,
                                                                    verkehr.STRASSENRECHT]


@pytest.mark.parametrize("mob_key", ["mob-1a2b3c4d", "mob", "organisation-17-neu"])
def test_gremium_tor_ueber_kennung_zur_laufzeit(mob_key):
    """Gremium-Tor: Kennung des Eintrags mit Gruppe „ausschuss“ und § 17 aus gremien.json, zur Laufzeit; eine Kennung mit
    Zusatz oder eine geänderte Kennung wird gefunden. Ohne passendes Wort führt das Tor in „weitere“, mit Grund aus dem
    Namen in gremien.json; die Beratung im Ausschuss steht auch vor einem Wort im Titel."""
    lauf = dossier.lauf(T, gremien_daten(mob_key))
    assert (lauf.tor, lauf.tor_name) == (mob_key, "Mobilitätsausschuss")
    mob = station(mob_key, "Mobilitätsausschuss", "2026-04-01", "beschlossen")
    assert zu("Sachstandsbericht der Verwaltung", [mob], lauf) == ("weitere", "Beratung im Mobilitätsausschuss")
    assert zu("Radweg an der Probestraße", [mob], lauf) == ("rad_fuss", "Beratung im Mobilitätsausschuss; Titel: „Radweg“")
    assert zu("Umgestaltung des Probeplatzes", [mob], lauf) == (
        "weitere", "Beratung im Mobilitätsausschuss; Titel: „Umgestaltung“")
    # eine Station mit anderer Kennung (alter Wert, Name gleich) öffnet das Tor nicht
    assert zu("Sachstandsbericht", [station("mob-alt", "Mobilitätsausschuss", "2026-04-01")], lauf) is None


@pytest.mark.parametrize("absage", [{"cancelled": 1}, {"hinweis": "abgesagt"}])
def test_abgesagte_station_oeffnet_das_tor_nicht(absage):
    """Eine Station in einer abgesagten Sitzung (export.absage: OParl oder laut Sitzungsnamen) zählt nicht; „verschoben“
    schon."""
    assert zu("Sachstandsbericht", [station(*MOB, "2026-12-09", **absage)]) is None
    assert zu("Sachstandsbericht", [station(*MOB, "2026-12-09", hinweis="verschoben")])[0] == "weitere"


@pytest.mark.parametrize("titel", ["Haushaltsplanentwurf 2027: Teilplan", "Stellenplan der Verwaltung",
                                   "Umbesetzung in Ausschüssen", "Nachbesetzung eines sachkundigen Mitglieds",
                                   "Sitzungskalender 2027", "Niederschrift der letzten Sitzung", "Wahl der Vertretung"])
def test_nur_ueber_das_gremium_ohne_haushalt_und_personalien(titel):
    """Nur über das Gremium nie: Haushalt, Sitzungsorganisation und Personalien (Thema.tor_ausschluss)."""
    assert zu(titel, [station(*MOB, "2026-04-01", "beschlossen")]) is None


# Personalien und Sitzungsorganisation (Prüfung der Daten, 25.11.2026): vor allen Regeln, auch wenn der Titel den
# Ausschuss oder ein Verkehrswort nennt und ohne Beratung im Ausschuss; Wahlen auch im Plural und zusammengesetzt
PERSONALIEN = ["Umbesetzung im Mobilitätsausschuss", "Wahl der stellvertretenden Vorsitzenden des Mobilitätsausschusses",
               "Wahlen zum Mobilitätsausschuss", "Sitzungskalender 2027 des Mobilitätsausschusses",
               "Wiederwahl der Beigeordneten für Mobilität",
               "Nachbesetzung eines sachkundigen Einwohners im Mobilitätsausschuss", "Wahlen der stellvertretenden Vorsitzenden",
               "Neuwahl der Schriftführung", "Wiederwahl eines Mitglieds", "Wahlvorschlag für den Aufsichtsrat der KVB",
               "Ernennung der Ausschussvorsitzenden", "Abberufung eines Vertreters im Verkehrsverbund", "Sitzungsplan 2027",
               "Terminplanung der Sitzungen 2027", "Protokoll der Sitzung vom 1. Oktober", "Neubesetzung im Radverkehrsbeirat",
               "Entsendung in den Aufsichtsrat der KVB", "Geschäftsführerin der Probe-Parkhausgesellschaft"]


@pytest.mark.parametrize("titel", PERSONALIEN)
def test_personalien_und_sitzungsorganisation_vor_allen_regeln(titel):
    for st in ([station(*MOB, "2026-04-01", "beschlossen")], [station(*BV, "2026-04-01")]):
        assert zu(titel, st) is None, st[0]["gremium"]
    # auch nicht als Folgevorlage
    w = vorlage("1/2026", "Radverkehrskonzept", sub=["2/2026"])
    c = vorlage("2/2026", titel, sup=["1/2026"])
    folge, _ = dossier.verfahren(T, _papiere(w, c), LAUF)
    assert dossier.zuordnen(T, c, LAUF, folge) is None


@pytest.mark.parametrize("titel", ["Haushaltsplanentwurf 2027, Teilplan Verkehrsflächen", "Wirtschaftsplan 2027 am Hafen",
                                   "Haushalt 2027: Umgestaltung von Plätzen"])
def test_tor_ausschluss_auch_mit_mehrdeutigem_wort(titel):
    """Haushalt und Wirtschaftspläne nie über das Gremium, auch nicht mit einem mehrdeutigen Wort (Regel „weitere“ mit
    Gremium-Tor); Wörter eines Strangs gelten weiter."""
    assert zu(titel, [station(*MOB, "2026-04-01", "beschlossen")]) is None
    assert zu("Haushalt 2027: Mittel für den Radverkehr", [station(*MOB, "2026-04-01")])[0] == "rad_fuss"


def test_personalien_ohne_fehltreffer():
    """Nicht ausgeschlossen: Bestellung von Fahrzeugen, Auswahl, Verkehrsmittelwahl, Kommunalwahl."""
    assert zu("Bestellung neuer Stadtbahnfahrzeuge", [station(*BV, "2026-04-01")]) == ("bus_bahn", "Titel: „Stadtbahnfahrzeuge“")
    assert zu("Auswahl der Buslinien für den Nachtverkehr", [station(*BV, "2026-04-01")])[0] == "bus_bahn"
    assert zu("Studie zur Verkehrsmittelwahl", [station(*BV, "2026-04-01")])[0] == "weitere"


# Fehltreffer mit Kölner Straßen- und Ortsnamen und anderen Wörtern (Prüfung der Daten, 25.11.2026)
FEHLTREFFER = ["Sanierung der Poller Wiesen", "Poller Hauptstraße: Erweiterung der Grundschule",
               "Sanierung der Grundschule Bahnhofstraße 12", "Spielplatz Am Bahnhof", "Bebauungsplan Am Alten Güterbahnhof",
               "Neugestaltung am Bahnhofsvorplatz in Probestadt", "Parkentwicklungskonzept Äußerer Grüngürtel",
               "Markierung von Grabfeldern auf dem Friedhof", "Beschilderung der Wanderwege im Königsforst",
               "Hochwasserschutz: Poller und Dammbalken", "Gedenkstele für Opfer des Unfalls", "Tunnelblick: Jugendkunstprojekt",
               "Arbeitsunfälle in der Verwaltung"]


@pytest.mark.parametrize("titel", FEHLTREFFER)
def test_fehltreffer_ohne_zuordnung(titel):
    assert zu(titel, [station(*BV, "2026-04-01")]) is None


@pytest.mark.parametrize("titel, strang, grund", [
    ("Poller an der Probestraße", "tempo", "Titel: „Poller“ und „Probestraße“"),
    ("Neue Markierung der Fahrbahn in Probestadt", "tempo", "Titel: „Markierung“ und „Fahrbahn“"),
    ("Beschilderung der Zufahrt zur Grundschule", "tempo", "Titel: „Beschilderung“ und „Zufahrt“"),
    ("Unfallschwerpunkt an der Probekreuzung", "tempo", "Titel: „Unfallschwerpunkt“"),
    ("Verkehrsunfälle vor Schulen", "tempo", "Titel: „Verkehrsunfälle“"),
    ("Umbau des Bahnhofs Probestadt", "bus_bahn", "Titel: „Bahnhofs“"),
    ("Aufzug am Bahnhof Probestadt", "bus_bahn", "Titel: „Bahnhof“"),
    ("Parkentgelte im Probeviertel", "parken", "Titel: „Parkentgelte“"),
    ("Sanierung des Probetunnels", "strassen", "Titel: „Probetunnels“"),
])
def test_treffer_nach_engeren_wortlisten(titel, strang, grund):
    assert zu(titel, [station(*BV, "2026-04-01")]) == (strang, grund)


# --- Entscheidungen 25.11.2026 nach dem Prüfbogen: Gremium-Tor bis drei Ausschüsse, neue Wortregeln, Personalien ----

def _ausschuesse(n, mob=True, **k):
    """Stationen in n verschiedenen Ausschüssen (mit Mobilitätsausschuss): Haupt-, Finanzausschuss, dann aus1, aus2, …"""
    andere = [("ha", "Hauptausschuss"), ("fa", "Finanzausschuss")] + [(f"aus{i}", f"[Testdaten] Ausschuss {i}")
                                                                      for i in range(1, 5)]
    st = [station(*MOB, "2026-04-01", "beschlossen")] if mob else []
    return st + [station(key, name, "2026-03-20", **k) for key, name in andere[:n - len(st)]]


@pytest.mark.parametrize("titel, strang", [("Sachstandsbericht der Verwaltung", "weitere"),
                                           ("Umgestaltung des Probeplatzes", "weitere")])
def test_gremium_tor_hoechstens_drei_ausschuesse(titel, strang):
    """Entscheidung 25.11.2026 (2): Die Beratung im Mobilitätsausschuss ohne passendes Wort (nur Gremium und MEHRDEUTIG
    mit Tor) ordnet nur zu, wenn höchstens drei verschiedene Ausschüsse aus gremien.json die Vorlage beraten,
    einschließlich Mobilitäts-, Haupt- und Finanzausschuss. Zählt aus gremien.json zur Laufzeit (Thema.tor_gremien)."""
    lauf = dossier.lauf(T, gremien_daten(weitere_ausschuesse=4))
    assert T.tor_hoechstens == 3 and lauf.gezaehlt == {"ha", "fa", "mob-1a2b3c4d", "aus1", "aus2", "aus3", "aus4"}
    assert zu(titel, _ausschuesse(3), lauf)[0] == strang
    assert zu(titel, _ausschuesse(4), lauf) is None
    assert zu(titel, _ausschuesse(6), lauf) is None


def test_gremium_tor_zaehlt_nur_verschiedene_ausschuesse():
    """Gezählt werden verschiedene Kennungen der Gruppe „ausschuss“: Rat, Bezirksvertretungen und aufgelöste Gremien
    nicht, derselbe Ausschuss zweimal einmal; eine abgesagte Sitzung steht in der Beratungsfolge und zählt mit (das Tor
    selbst öffnet sie nicht)."""
    lauf = dossier.lauf(T, gremien_daten(weitere_ausschuesse=2))
    rest = [station("rat", "Rat", "2026-05-01"), station(*BV, "2026-03-10"),
            station(None, "[Testdaten] früherer Verkehrsausschuss", "2026-02-01")]
    assert zu("Sachstandsbericht", _ausschuesse(3) + rest, lauf) == ("weitere", "Beratung im Mobilitätsausschuss")
    doppelt = _ausschuesse(3) + [station("ha", "Hauptausschuss", "2026-06-01")]
    assert zu("Sachstandsbericht", doppelt, lauf)[0] == "weitere"
    assert zu("Sachstandsbericht", _ausschuesse(3) + [station("aus1", "[Testdaten] Ausschuss 1", "2026-06-01",
                                                              cancelled=1)], lauf) is None
    assert dossier.breit_beraten(T, vorlage("1/2026", "x", stationen=_ausschuesse(4)), lauf)
    assert not dossier.breit_beraten(dataclasses.replace(T, tor_hoechstens=None),
                                     vorlage("1/2026", "x", stationen=_ausschuesse(6)), lauf)


def test_gremium_tor_grenze_nicht_fuer_woerter_im_titel():
    """Wörter im Titel gelten auch bei vier und mehr Ausschüssen; der Grund nennt die Beratung im Mobilitätsausschuss."""
    lauf = dossier.lauf(T, gremien_daten(weitere_ausschuesse=4))
    assert zu("Radweg an der Probestraße", _ausschuesse(5), lauf) == (
        "rad_fuss", "Beratung im Mobilitätsausschuss; Titel: „Radweg“")
    assert zu("Mobilitätskonzept für Probestadt", _ausschuesse(4), lauf)[0] == "weitere"
    assert dossier.breit_beraten(T, vorlage("1/2026", "Radweg an der Probestraße", stationen=_ausschuesse(5)), lauf)


def test_gremium_tor_grenze_in_der_seite():
    """dossier.daten rechnet mit derselben Grenze (Lauf aus gremien.json): eine Querschnittsvorlage mit vier Ausschüssen
    fehlt, mit drei steht sie in „weitere“."""
    gd = gremien_daten(weitere_ausschuesse=1)
    ps = {"a": vorlage("1/2026", "Bevölkerungsprognose für Probestadt", art="Mitteilung", stationen=_ausschuesse(4)),
          "b": vorlage("2/2026", "Bericht zur Probestadt", art="Mitteilung", stationen=_ausschuesse(3))}
    d = dossier.daten(T, ps, {"a": "gesamt", "b": "gesamt"}, gd, {}, [{"start": "2025-11-01"}])
    assert [r["reference"] for s in d["straenge"] for r in s["vorlagen"]] == ["2/2026"]


@pytest.mark.parametrize("titel, wort", [("Radverbindung zwischen Probestadt und Probedorf", "Radverbindung"),
                                         ("Neue Radverbindungen im Stadtbezirk", "Radverbindungen"),
                                         ("Radachse Probestraße: Planung", "Radachse"),
                                         ("Radverbindung Probestraße: Beschilderung und Verkehrsführung", "Radverbindung")])
def test_radverbindung_und_radachse(titel, wort):
    """Entscheidung 25.11.2026 (3) (a): Radverbindung und Radachse gehören zu Rad- und Fußverkehr (auch vor Tempo und
    Beschilderung)."""
    assert zu(titel, [station(*BV, "2026-04-01")]) == ("rad_fuss", f"Titel: „{wort}“")


@pytest.mark.parametrize("titel, grund", [
    ("Sanierung der Probestraße", "Sanierung der Probestraße"),
    ("Baubeschluss für die Generalinstandsetzung der Probestraße zwischen Probeweg und Probeplatz",
     "Generalinstandsetzung der Probestraße"),
    ("Instandsetzung des Probewegs", "Instandsetzung des Probewegs"),
    ("Endausbau der Probe-Allee in Probestadt", "Endausbau der Probe-Allee"),
    ("Erneuerung der Probestr. zwischen A und B", "Erneuerung der Probestr."),
    ("Teilerneuerung des Probener Rings", "Teilerneuerung des Probener Rings"),
    ("Umbau der Neue Probener Straße", "Umbau der Neue Probener Straße"),
    ("Neubau der Alten Probestraße", "Neubau der Alten Probestraße"),
    ("Generalsanierung der Straße „Am Probehof“ in Probestadt", "Generalsanierung der Straße „Am Probehof“"),
    ("Ausbau des Probegürtels", "Ausbau des Probegürtels"),
    ("Sanierung und Ausbau der Probestraße", "Sanierung und Ausbau der Probestraße"),
    ("Erneuerung der Fahrbahn und der Gehwege in der Probestraße", "Erneuerung der Fahrbahn und der Gehwege in der Probestraße"),
    ("Sanierung eines Teilstücks der Probestraße", "Sanierung eines Teilstücks der Probestraße"),
    ("Sanierung des Niehler Damms", "Sanierung des Niehler Damms"),            # Name im Straßenverzeichnis
    ("Sanierung des Konrad-Adenauer-Ufers", "Sanierung des Konrad-Adenauer-Ufers"),
])
def test_strassenbau_mit_strassenname(titel, grund):
    """Entscheidung 25.11.2026 (3) (b): Instandsetzung, Sanierung, Erneuerung, Aus-, Um- und Neubau (auch General-,
    Teil-, Endausbau) mit folgendem Straßenname gehören zu „Straßen und Brücken“; der Grund nennt die Stelle im Titel."""
    assert zu(titel, [station(*BV, "2026-04-01")]) == ("strassen", f"Titel: „{grund}“")


@pytest.mark.parametrize("titel", ["Teilerneuerung der Fahrbahn und Gehwege in der Probestraße",
                                   "Fahrbahn und Gehwege im Probeviertel", "Gehwege und Fahrbahn am Probeplatz",
                                   "Fahrbahn- und Gehwegsanierung im Probeviertel"])
def test_fahrbahn_und_gehwege_nicht_rad_und_fuss(titel):
    """„Fahrbahn und Gehweg(e)“, „Gehweg(e) und Fahrbahn“, „Fahrbahn- und Gehweg…“: Straßen und Brücken, nicht Rad- und
    Fußverkehr (die Regel steht vor Rad- und Fußverkehr)."""
    assert zu(titel, [station(*BV, "2026-04-01")])[0] == "strassen"
    assert verkehr.RAD_FUSS.search(titel)


@pytest.mark.parametrize("titel", [
    "Sanierung der Bezirkssportanlage Probeweg", "Generalsanierung der Sportanlage Probestraße",
    "Sanierung des Sportparks Probeweg", "Sanierung des Probe-Sportparks am Probeweg", "Endausbau Gartenlabor Probeweg",
    "Sanierung der Grundschule Probestraße", "Neubau einer Kita an der Probestraße", "Sanierung der Halle am Probeweg",
    "Sanierung des Bades an der Probestraße", "Instandsetzung des Friedhofs Probeweg",
    "Instandsetzung des Spielplatzes Probestraße", "Energetische Sanierung des Gebäudes Probestraße",
    "Sanierung des Parks am Probeweg", "Instandsetzung der Hochbeete und Grünflächen am Probeweg",
    "Neubau-Projekt Probestraße", "Kanalsanierung in der Probestraße", "Sanierung des Probedamms",
    "Sanierung des Rheinufers", "Sanierung im Grüngürtel", "Sanierung der Grundschule Alte Probestraße",
    "Neubau von Wohnungen an der Probestraße", "Sanierung der Straße", "Ausbau der Ladeinfrastruktur an der Probestraße"])
def test_strassenbau_nicht_bei_einrichtungen(titel):
    """Gegenproben: Steht zwischen Bauarbeit und Straßenname eine Einrichtung oder ein anderes Hauptwort, ist es keine
    Straßenbauarbeit; ebenso ein Damm oder Ufer, das nicht im Straßenverzeichnis steht, und „Straße“ allein. Die
    Vorlage fällt dann unter die übrigen Regeln (hier keine, außer Ladeinfrastruktur in „weitere“)."""
    erwartet = "weitere" if "Ladeinfrastruktur" in titel else None
    assert (zu(titel, [station(*BV, "2026-04-01")]) or (None,))[0] == erwartet
    assert not verkehr.STRASSENBAU.search(titel)


def test_radweg_und_sanierung_einer_strasse():
    """Ein Radweg allein bleibt Rad- und Fußverkehr, auch mit Bauarbeit („Sanierung des Radwegs an der Probestraße“: der
    Radweg steht zwischen Bauarbeit und Straßenname). Nennt der Titel Radweg und die Sanierung der Straße selbst, gilt
    die Regel zum Straßenbau, weil sie vor Rad- und Fußverkehr steht: Strang „Straßen und Brücken“."""
    assert zu("Sanierung des Radwegs an der Probestraße", [station(*BV, "2026-04-01")]) == ("rad_fuss", "Titel: „Radwegs“")
    assert zu("Neuer Radweg und Sanierung der Probestraße", [station(*BV, "2026-04-01")]) == (
        "strassen", "Titel: „Sanierung der Probestraße“")


@pytest.mark.parametrize("titel", ["Neue Fahrbahnmarkierungen in der Probestraße",
                                   "Erneuerung der Fahrbahnmarkierung in der Probestraße"])
def test_fahrbahnmarkierungen_bleiben_tempo(titel):
    """Markierungen auf der Fahrbahn bleiben im Strang Tempo (ZEICHEN mit ZEICHEN_BEZUG), auch mit Bauarbeit; Fahrbahn
    und Gehweg mit Markierung sind keine Straßenbauarbeit (dort gilt Gehweg, Rad- und Fußverkehr)."""
    assert zu(titel, [station(*BV, "2026-04-01")])[0] == "tempo"
    assert not verkehr.STRASSENBAU.search("Fahrbahn- und Gehwegmarkierungen in der Probestraße")
    assert zu("Fahrbahn- und Gehwegmarkierungen in der Probestraße", [station(*BV, "2026-04-01")])[0] == "rad_fuss"


@pytest.mark.parametrize("titel, grund", [
    ("Widmung eines Teilstücks der Probestraße", "Widmung"), ("Widmung der Straße Probeweg in Probestadt", "Widmung"),
    ("Teileinziehung der Probestraße", "Teileinziehung"), ("Beleuchtung im Straßenabschnitt der Probestraße", "Straßenabschnitt"),
    ("Umwidmung der Probestraße in eine Schulstraße", "Umwidmung der Probestraße"),
    ("Umwidmung eines Teilstücks der Probestraße", "Umwidmung eines Teilstücks der Probestraße")])
def test_strassenrecht(titel, grund):
    """Entscheidung 25.11.2026 (3) (c): Widmung, Teileinziehung und Straßenabschnitt; Umwidmung nur, wenn eine Straße folgt."""
    assert zu(titel, [station(*BV, "2026-04-01")]) == ("strassen", f"Titel: „{grund}“")


@pytest.mark.parametrize("titel", ["Umwidmung von Telefonzellen im Stadtbezirk Probestadt",
                                   "Umwidmung bestehender Unterkünfte", "Umwidmung von Unterkünften an der Probestraße",
                                   "Umwidmung des Gebäudes Probestraße", "Mittelumwidmung für die Probeschule"])
def test_umwidmung_ohne_strasse(titel):
    """Gegenproben zu Straßenrecht: Umwidmung ohne folgende Straße (Telefonzellen, Unterkünfte, Gebäude) und als Teil
    eines längeren Worts trifft STRASSENRECHT nicht, mit Straße schon."""
    assert zu(titel, [station(*BV, "2026-04-01")]) is None
    assert not verkehr.STRASSENRECHT.search(titel)
    assert verkehr.STRASSENRECHT.search(re.sub(r"Umwidmung (von |des |bestehender )?\w+", "Umwidmung der Probestraße",
                                               titel.replace("Mittelumwidmung für die", "Umwidmung von")))


PERSONALIEN_BESTELLUNG = [
    "Bestellung von städtischen Vertreterinnen und Vertretern im Probeverband für Verkehr",
    "Bestellung von Vertretern in den Organen des Probe-Verkehrsverbunds",
    "Bestellung einer Schriftführung für den Mobilitätsausschuss",
    "Bestellung der Schriftführung und der stellvertretenden Schriftführung im Verkehrsausschuss",
    "Schriftführerin im Mobilitätsausschuss", "Bestellung von Mitgliedern des Radverkehrsbeirats",
    "Bestellung eines neuen Mitglieds der Betriebsleitung der Probe-Verkehrsbetriebe",
    "Bestellung der Geschäftsführung der Probe-Parkhaus GmbH",
    "Bestellung des Abschlussprüfers der Probe-Verkehrsgesellschaft",
    "Bestellung von Arbeitnehmervertreter*innen in den Aufsichtsrat der Probe-Verkehrsbetriebe"]


@pytest.mark.parametrize("titel", PERSONALIEN_BESTELLUNG)
def test_bestellung_von_personen_vor_allen_regeln(titel):
    """Entscheidung 25.11.2026 (3) (d): Bestellung von Vertreterinnen und Vertretern, Mitgliedern, Geschäftsführung,
    Abschlussprüfern und Schriftführung (auch allgemein) im Ausschluss über PERSONALIEN, vor allen Regeln, auch mit
    Verkehrswort, Beratung im Ausschuss oder als Folgevorlage."""
    for st in ([station(*MOB, "2026-04-01", "beschlossen")], [station(*BV, "2026-04-01")]):
        assert zu(titel, st) is None
    w = vorlage("1/2026", "Radverkehrskonzept", sub=["2/2026"])
    c = vorlage("2/2026", titel, sup=["1/2026"])
    assert dossier.zuordnen(T, c, LAUF, dossier.verfahren(T, _papiere(w, c), LAUF)[0]) is None


@pytest.mark.parametrize("titel, strang, personen", [
    ("Bestellung neuer Stadtbahnfahrzeuge", "bus_bahn", "Bestellung neuer Vertreter für die Stadtbahn"),
    ("Bestellung von 20 Elektrobussen für die Linie 5", "bus_bahn",
     "Bestellung von Mitgliedern des Fahrgastbeirats für die Buslinien"),
    ("Bestellung eines Lastenrads für die Verwaltung", "rad_fuss", "Bestellung eines Prüfers für das Lastenrad-Programm")])
def test_bestellung_von_sachen_unberuehrt(titel, strang, personen):
    """Bestellungen von Sachen bleiben unberührt; dieselben Wörter mit einer Bestellung von Personen fallen heraus."""
    assert zu(titel, [station(*BV, "2026-04-01")])[0] == strang
    assert zu(personen, [station(*BV, "2026-04-01")]) is None


def test_personenbezug_mitglieder_von_rat_und_bezirksvertretung():
    """PERSONENBEZUG (Prüfbogen): auch Bezirksvertreter und Bezirksvertreterin, Ratsmitglied, Ratsherr, Ratsfrau und
    Bezirksbürgermeister(in), weil ein Titel ein Mitglied einer Bezirksvertretung mit Namen nannte; „Bezirksvertretung“
    allein nicht (sonst fiele fast jede Vorlage einer Bezirksvertretung heraus)."""
    for titel in ("Anfrage der Bezirksvertreterin Mia Musterlich zum Probeweg", "Antrag des Bezirksvertreters Probe",
                  "Anfrage des Ratsmitglieds Probe", "Ratsherr Probe: Radweg", "Ratsfrau Probe: Radweg",
                  "Bezirksbürgermeisterin Probe zum Probeplatz", "Bezirksbürgermeister Probe zum Probeplatz"):
        assert dossier.PERSONENBEZUG.search(titel), titel
    assert not dossier.PERSONENBEZUG.search("Bezirksvertretung Innenstadt: Radweg an der Probestraße")


def test_koelner_strassennamen_allein_ohne_strang():
    """Ein Kölner Straßenname allein (Straßenverzeichnis data/geo/strassen_koeln.json) trifft kein Wort eines Strangs,
    außer Brücken und Tunneln (Bauwerke des Verkehrs, Strang „Straßen und Brücken“) und der Straße „Bahnhof Heumar“."""
    namen = json.loads(config.STRASSEN.read_text(encoding="utf-8"))["streets"]
    assert len(namen) > 5000
    treffer = {n for n in namen for r in T.regeln if r.titel and not r.gremium_tor and r.titel.search(n)
               and (not r.bedingung or r.bedingung.search(n))}
    assert all(re.search(r"(?i)brücke|tunnel", n) for n in treffer - {"Bahnhof Heumar"}), sorted(treffer)
    assert not any(verkehr.TEMPO.search(n) or verkehr.ZEICHEN.search(n) for n in namen)


def test_nur_bezirksvertretung_ohne_wort():
    """Bezirksvertretungen, Rat, Haupt- und Finanzausschuss sind kein Beleg für das Thema: dort zählen nur Wörter."""
    for st in (station(*BV, "2026-04-01"), station("rat", "Rat", "2026-04-01"), station("ha", "Hauptausschuss", "2026-04-01"),
               station("fa", "Finanzausschuss", "2026-04-01")):
        assert zu("Sachstandsbericht der Verwaltung", [st]) is None
        assert zu("Radweg an der Probestraße", [st]) == ("rad_fuss", "Titel: „Radweg“")


def test_ohne_paragraf_17_kein_tor(tmp_path, monkeypatch):
    """Ohne eindeutigen Eintrag mit § 17 in gremien.json gibt es kein Tor (kein stiller Rückfall auf den Namen), und
    check meldet einen Befund."""
    gd = gremien_daten(mit_mob=False)
    lauf = dossier.lauf(T, gd)
    assert lauf.tor is None and dossier.fachausschuss(T, gd) is None
    assert zu("Sachstandsbericht", [station(*MOB, "2026-04-01", "beschlossen")], lauf) is None
    assert zu("Radweg an der Probestraße", [station(*MOB, "2026-04-01")], lauf) == ("rad_fuss", "Titel: „Radweg“")
    base = _export(tmp_path, monkeypatch, gd=gd)
    befunde, fehlend = check.dossiers(base, umgebung={})
    assert any("Fachausschuss nicht eindeutig" in b for b in befunde), befunde


def test_grenze_seit_und_wahlperiode():
    """Zeitraum ab Beginn der laufenden Wahlperiode (zeit.json terms), sonst actors.WAHLPERIODE_2025_BEGINN."""
    assert zu("Radweg an der Probestraße", tag="2025-10-31") is None
    assert zu("Radweg an der Probestraße", tag="2025-11-01")[0] == "rad_fuss"
    terms = [{"start": "2020-11-01", "end": "2025-10-31"}, {"start": "2025-11-01", "end": None}]
    assert dossier.wahlperiode_beginn(terms, "2026-11-21") == "2025-11-01"
    assert dossier.wahlperiode_beginn(terms[:1], "2026-11-21") == actors.WAHLPERIODE_2025_BEGINN
    assert dossier.wahlperiode_beginn([], "2026-11-21") == actors.WAHLPERIODE_2025_BEGINN
    assert dossier.wahlperiode_beginn([{"start": "2030-11-01"}], "2026-11-21") == actors.WAHLPERIODE_2025_BEGINN


def _papiere(*ps):
    return {p["source_object"]: p for p in ps}


def test_folgevorlagen_nur_nach_unten():
    """Antwort 1 A: Folgevorlagen erben den Strang ihrer Wurzel über superordinated und subordinated (beide Richtungen
    zusammen), nur nach unten, Grund „Folgevorlage zu <Drucksache der Wurzel>“; der Strang der Wurzel geht ihrem Wort im
    Titel vor; nach oben keine Weitergabe."""
    w = vorlage("1/2026", "Radverkehrskonzept für den Stadtbezirk", sub=["2/2026"])
    c1 = vorlage("2/2026", "Ergänzung zur Vorlage", sup=["1/2026"])
    c2 = vorlage("3/2026", "Bewohnerparken: Stellungnahme", sup=["2/2026"])       # nur von unten verknüpft
    o = vorlage("4/2026", "Mitteilung zum Sachstand", sub=["5/2026"])            # Wurzel ohne Strang
    k = vorlage("5/2026", "Tempo 30 im Probeviertel", sup=["4/2026"])
    ps = _papiere(w, c1, c2, o, k)
    folge, zahl = dossier.verfahren(T, ps, LAUF)
    assert folge == {c1["source_object"]: ("rad_fuss", "Folgevorlage zu 1/2026"),
                     c2["source_object"]: ("rad_fuss", "Folgevorlage zu 1/2026")}
    assert dossier.zuordnen(T, c2, LAUF, folge) == ("rad_fuss", "Folgevorlage zu 1/2026")
    assert dossier.zuordnen(T, o, LAUF, folge) is None              # nicht nach oben
    assert dossier.zuordnen(T, k, LAUF, folge) == ("tempo", "Titel: „Tempo 30“")
    assert zahl["folgevorlagen"] == 2 and zahl["beziehungen"] == 3


def test_folgevorlagen_zyklus_mehrdeutig_und_ausschluss():
    """Zyklus ohne Wurzel: keine Weitergabe und keine Endlosschleife; mehrdeutige Drucksache: keine Weitergabe (gezählt);
    der Ausschluss gilt auch für Folgevorlagen; Wurzel vor Beginn des Zeitraums: keine Weitergabe."""
    a = vorlage("1/2026", "Radweg an der Probestraße", sub=["2/2026"], sup=["2/2026"])
    b = vorlage("2/2026", "Ergänzung", sub=["1/2026"], sup=["1/2026"])
    folge, _ = dossier.verfahren(T, _papiere(a, b), LAUF)
    assert folge == {}
    d1 = vorlage("9/2026", "Radverkehrskonzept", sub=["10/2026"])
    d2 = dict(vorlage("9/2026", "Andere Vorlage gleicher Drucksache"), source_object=P + "9-2026-zweite")
    c = vorlage("10/2026", "Ergänzung zur Vorlage", sup=["9/2026"])
    folge, zahl = dossier.verfahren(T, _papiere(d1, d2, c), LAUF)
    assert folge == {} and zahl["mehrdeutig"] == 2
    w = vorlage("11/2026", "Radverkehrskonzept", sub=["12/2026"])
    x = vorlage("12/2026", "Straßenbenennung im Neubaugebiet", sup=["11/2026"])
    folge, _ = dossier.verfahren(T, _papiere(w, x), LAUF)
    assert dossier.zuordnen(T, x, LAUF, folge) is None
    alt = vorlage("13/2025", "Radverkehrskonzept", tag="2025-06-01", sub=["14/2026"])
    neu = vorlage("14/2026", "Ergänzung", sup=["13/2025"])
    assert dossier.verfahren(T, _papiere(alt, neu), LAUF)[0] == {}


def test_folgevorlage_vor_beginn_des_zeitraums():
    """Der Zeitraum gilt auch für Folgevorlagen (die Seite zeigt Vorlagen seit Beginn der Wahlperiode): eine
    untergeordnete Vorlage vor seit erbt nichts und zählt nicht als Folgevorlage."""
    w = vorlage("1/2026", "Radverkehrskonzept", sub=["2/2025", "3/2026"])
    alt = vorlage("2/2025", "Kita-Neubau", tag="2025-05-01", sup=["1/2026"])
    neu = vorlage("3/2026", "Ergänzung", sup=["1/2026"])
    folge, zahl = dossier.verfahren(T, _papiere(w, alt, neu), LAUF)
    assert dossier.zuordnen(T, alt, LAUF, folge) is None
    assert dossier.zuordnen(T, neu, LAUF, folge) == ("rad_fuss", "Folgevorlage zu 1/2026")
    assert zahl["folgevorlagen"] == 1


def test_eine_wurzel_mit_und_eine_ohne_strang():
    """Wie in TECHNIK beschrieben: Nur Wurzeln mit eigenem Strang zählen; erreicht eine Vorlage eine Wurzel mit und eine
    ohne Strang, erbt sie den Strang der einen (nicht „mehrere Wurzeln“)."""
    w1 = vorlage("1/2026", "Radverkehrskonzept", sub=["3/2026"])
    w2 = vorlage("2/2026", "Mitteilung der Verwaltung zum Sachstand", sub=["3/2026"])
    c = vorlage("3/2026", "Gemeinsame Stellungnahme", sup=["1/2026", "2/2026"])
    folge, zahl = dossier.verfahren(T, _papiere(w1, w2, c), LAUF)
    assert dossier.zuordnen(T, c, LAUF, folge) == ("rad_fuss", "Folgevorlage zu 1/2026") and zahl["mehrere_wurzeln"] == 0


def test_mehrere_wurzeln_keine_weitergabe():
    w1 = vorlage("1/2026", "Radweg an der Probestraße", sub=["3/2026"])
    w2 = vorlage("2/2026", "Bewohnerparken", sub=["3/2026"])
    c = vorlage("3/2026", "Gemeinsame Stellungnahme", sup=["1/2026", "2/2026"])
    folge, zahl = dossier.verfahren(T, _papiere(w1, w2, c), LAUF)
    assert folge == {} and zahl["mehrere_wurzeln"] == 1


def test_gegenprobe_kein_abgeleitetes_thema_keine_federfuehrung():
    """Entscheidung (3): abgeleitetes Thema (themes), Federführung (amt, responsibility) und relatedPaper ergeben keine
    Zuordnung; dossier.py und verkehr.py werten diese Felder im Code nicht aus (nur in Texten genannt)."""
    p = vorlage("1/2026", "Sachstandsbericht der Verwaltung", stationen=[station(*BV, "2026-04-01")],
                themes=[{"theme": "verkehr", "evidence": "Amt 66"}], amt="66 Amt für Straßen und Radwegebau",
                responsibility=[{"kind": "federfuehrend", "name": "66 Amt für Straßen und Radwegebau"}],
                related=[{"reference": "2/2026"}])
    assert dossier.zuordnen(T, p, LAUF) is None
    for datei in ("pipeline/dossier.py", "pipeline/themenseiten/verkehr.py", "pipeline/themenseiten/__init__.py"):
        baum = ast.parse((ROOT / datei).read_text(encoding="utf-8"))
        texte = {n.value for n in ast.walk(baum) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        doc = {ast.get_docstring(n) for n in ast.walk(baum)
               if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(n)}
        for feld in ("themes", "amt", "responsibility", "underDirectionOf", "under_direction_of", "relatedPaper",
                     "paper_related"):
            assert feld not in {t for t in texte if t not in doc}, (datei, feld)
    assert "topics.themes" not in (ROOT / "pipeline/dossier.py").read_text(encoding="utf-8")


# --- Daten der Seite --------------------------------------------------------------------------------------------------

def _cache():
    """Vorlagen für eine ganze Seite: Stränge, Punkte, Eingabe, Anfrage, Mitteilung, Folgevorlage, Bezirk."""
    loc = lambda b: [{"stadtbezirk": b, "level": "stadtteil"}]
    ps = [
        vorlage("1/2026", "Radweg an der Probestraße", art="Antrag nach § 3 der Geschäftsordnung des Rates",
                stationen=[station(*BV, "2026-03-10", "beschlossen"), station("rat", "Rat", "2026-04-02", "beschlossen")],
                stand="entschieden"),
        vorlage("2/2026", "Bewohnerparken in Probestadt", stationen=[station(*MOB, "2026-05-01", "beschlossen"),
                                                                     station("rat", "Rat", "2026-12-03")]),
        vorlage("3/2026", "Mobilitätskonzept für Probestadt", stationen=[station(*BV, "2026-05-02")], locations=loc("Innenstadt")),
        vorlage("4/2026", "Ladesäulen am Probeplatz", stationen=[station(*BV, "2026-05-02")], locations=loc("Innenstadt")),
        vorlage("5/2026", "Sachstandsbericht", stationen=[station(*MOB, "2026-06-01", "Kenntnis genommen")]),
        vorlage("6/2026", "Anregung nach § 24 GO NRW: Tempo 30 in der Probestraße", art="Anregungen und Beschwerden",
                stationen=[station("bab", "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden", "2026-06-02"),
                           station("rat", "Rat", "2026-06-20", "beschlossen")]),
        vorlage("AN/7/2026", "Tempo 30 vor der Schule", art="Anfrage nach § 4 der Geschäftsordnung des Rates",
                stationen=[station(*MOB, "2026-06-01")]),
        vorlage("8/2026", "Haltestelle Probeplatz: Bericht", art="Mitteilung", stationen=[station(*MOB, "2026-06-01")]),
        vorlage("9/2026", "Kreisverkehr an der Probestraße", stationen=[
            station(*MOB, "2026-12-09", hinweis="abgesagt"), station("ha", "Hauptausschuss", "2026-12-10")]),
        vorlage("10/2026", "Ergänzung zur Vorlage", sup=["1/2026"], stationen=[
            station(None, "[Testdaten] früherer Verkehrsausschuss", "2026-02-01", "beschlossen"),
            station("rat", "Rat", "2026-04-02", "beschlossen")]),
        vorlage("11/2026", "Kita-Neubau an der Probestraße 3", stationen=[station("rat", "Rat", "2026-04-02", "beschlossen")]),
    ]
    ps[0]["subordinated"] = [{"reference": "10/2026"}]
    return {p["source_object"]: p for p in ps}


def daten(gd=None):
    cache = _cache()
    return dossier.daten(T, cache, {k: "ortsteil:probestadt" for k in cache}, gd or gremien_daten(), {"note": "abgeleitet"},
                         [{"start": "2025-11-01", "end": None}])


def test_daten_straenge_punkte_sitzungen():
    d = daten()
    je = {s["key"]: [r["reference"] for r in s["vorlagen"]] for s in d["straenge"]}
    assert je == {"bus_bahn": ["8/2026"], "rad_fuss": ["10/2026", "1/2026"], "parken": ["2/2026"],
                  "tempo": ["AN/7/2026", "6/2026"], "strassen": ["9/2026"], "weitere": ["5/2026", "4/2026", "3/2026"]}
    assert set(d) <= set(check.DOSSIER_SCHLUESSEL) and d["heute"] == "2026-11-21" and d["meta"]["seit"] == "2025-11-01"
    # Punkte: nur Beschlussvorlagen und Anträge mit Beratung in Rat, Hauptausschuss oder Mobilitätsausschuss; keine
    # Eingabe, keine Anfrage, keine Mitteilung, nicht nur Bezirksvertretung
    assert [(p["reference"], p["date"], p["bahn"]) for p in d["punkte"]] == [
        ("1/2026", "2026-04-02", "rat"), ("10/2026", "2026-04-02", "rat"), ("2/2026", "2026-05-01", "mobil"),
        ("5/2026", "2026-06-01", "mobil"), ("9/2026", "2026-12-09", "mobil")]
    assert [p["nr"] for p in d["punkte"]] == list(range(1, len(d["punkte"]) + 1))
    # Lage der nächsten Beratung wie Stand und letzte Beratung nur nach OParl `cancelled` (F10); das Detailfeld nennt
    # die Absage laut Sitzungsnamen
    p9 = next(p for p in d["punkte"] if p["reference"] == "9/2026")
    assert [b.get("abgesagt") for b in p9["beratungen"]] == ["name", None]
    p10 = next(p for p in d["punkte"] if p["reference"] == "10/2026")
    assert p10["grund"] == "Folgevorlage zu 1/2026" and p10["beratungen"][0]["gremium"].startswith("[Testdaten]")
    for p in d["punkte"]:
        assert p["bahn"] in {k for k, _ in T.bahnen}
    # „weitere“ nach Stadtbezirk; Sitzungen aus gremien.json, mit folgender Sitzung am Datenstand
    assert {r["reference"]: r["bezirk"] for r in next(s for s in d["straenge"] if s["key"] == "weitere")["vorlagen"]} == {
        "3/2026": "Innenstadt", "4/2026": "Innenstadt", "5/2026": "ohne Ortsbezug"}
    assert [(m["gremium"], m["date"], m["bahn"]) for m in d["sitzungen"]] == [
        ("Hauptausschuss", "2026-11-21", "rat"), ("Bezirksvertretung 1 (Innenstadt)", "2026-11-26", "bv"),
        ("Mobilitätsausschuss", "2026-12-02", "mobil"), ("Rat", "2026-12-03", "rat"), ("Hauptausschuss", "2026-12-10", "rat")]
    assert all("frist" not in m and m["key"] for m in d["sitzungen"])
    assert d["weitere_gremien"] == ["die Bezirksvertretungen", "der Hauptausschuss", "der Rat"]
    w = d["wer_beraet_mit"]
    assert w["key"] == "mob-1a2b3c4d" and w["paragraf"] == 17 and w["satzung"]["url"] == SATZUNG
    assert set(w) <= set(gremien.FELDER) | {"zeitraum", "satzung"}


def _punkt_von(*stationen, art="Beschlussvorlage"):
    """Lage des einen Punkts einer erfundenen Beschlussvorlage mit diesen Stationen (Bezirksvertretung 2 ergänzt)."""
    p = vorlage("1/2026", "Radweg an der Probestraße", art=art, stationen=list(stationen))
    gd = gremien_daten()
    gd["gremien"].append({"key": "bv2", "name": "Bezirksvertretung 2 (Rodenkirchen)", "gruppe": "bezirksvertretung",
                          "stadtbezirk": "Rodenkirchen", "source_object": O + "bv2"})
    d = dossier.daten(T, {"a": p}, {"a": "ortsteil:probestadt"}, gd, {}, [{"start": "2025-11-01"}])
    return [(x["bahn"], x["gremium"], x["date"]) for x in d["punkte"]], d


BV2 = ("bv2", "Bezirksvertretung 2 (Rodenkirchen)")


def test_punkt_nie_auf_der_bahn_der_bezirksvertretungen():
    """Antwort 2 A: Beratungen in Bezirksvertretungen stehen in Liste, Detailfeld und Strang, nicht als Punkt. Die Lage
    folgt nur den Beratungen in Rat, Hauptausschuss und Mobilitätsausschuss: letzte mit Ergebnis dort, sonst die nächste
    dort; das Detailfeld nennt die ganze Beratungsfolge."""
    lage, d = _punkt_von(station(*MOB, "2026-04-01", "beschlossen"), station(*BV2, "2026-05-01", "zur Kenntnis genommen"))
    assert lage == [("mobil", "Mobilitätsausschuss", "2026-04-01")]
    assert [b["gremium"] for b in d["punkte"][0]["beratungen"]] == ["Mobilitätsausschuss", BV2[1]]
    # Bezirksvertretung als nächste Station, danach der Rat
    lage, _ = _punkt_von(station(*MOB, "2026-04-01"), station(*BV2, "2026-11-30"), station("rat", "Rat", "2026-12-03"))
    assert lage == [("rat", "Rat", "2026-12-03")]
    # nur vergangene Beratungen ohne Ergebnis dort: erstes Gremium des Bildes am Tag der Vorlage
    lage, _ = _punkt_von(station(*BV2, "2026-03-20", "beschlossen"), station(*MOB, "2026-04-01"))
    assert lage == [("mobil", "Mobilitätsausschuss", "2026-03-02")]
    for bahn, _, _ in _punkt_von(station(*BV2, "2026-05-01", "beschlossen"), station(*MOB, "2026-04-01", "beschlossen"))[0]:
        assert bahn != "bv"


def test_feed_nach_vorlage_nicht_nach_drucksache(tmp_path, monkeypatch):
    """Der Themenfeed nimmt die zugeordneten Vorlagen, nicht jede Vorlage mit einer Drucksache aus den Strängen:
    Drucksachen sind in Köln teils mehrfach vergeben."""
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    monkeypatch.setattr(config, "LEGISLATIVE_TERMS", tmp_path / "fehlt_terms.json")
    # Felder der Gebietsdateien, die der Feed liest (publish.events: amt wie im Export, in Köln meist leer; steps)
    rad = vorlage("1/2026", "Radweg an der Probestraße", stationen=[station(*MOB, "2026-04-01", "beschlossen")], amt=None,
                  steps=[])
    kita = dict(vorlage("1/2026", "Kita-Neubau am Probeweg", stationen=[station(*BV, "2026-04-02", "beschlossen")],
                        amt=None, steps=[]), source_object=P + "1-2026-zweite")
    cache = {"a": rad, "b": kita}
    export._themenseiten(tmp_path, cache, {"a": "ortsteil:probestadt", "b": "ortsteil:probestadt"}, [], gremien_daten(), {})
    seite = json.loads((tmp_path / "dossiers" / "verkehr.json").read_text(encoding="utf-8"))
    assert [r["name"] for s in seite["straenge"] for r in s["vorlagen"]] == [rad["name"]]
    feed = (tmp_path / "dossiers" / "verkehr.xml").read_text(encoding="utf-8")
    assert "Radweg an der Probestraße" in feed and "Kita-Neubau" not in feed


def test_themenfeed_ohne_unbekannte_federfuehrung(tmp_path, monkeypatch):
    """Entscheidung 25.11.2026 (6): Im Themenfeed entfällt „federführend: …“, wo die Federführung unbekannt ist (in den
    Kölner Daten bei jeder Vorlage); eine bekannte steht da. Die übrigen Feeds (publish.events ohne Schalter) nennen
    „federführend: unbekannt“ unverändert, bis ein eigener Pull Request sie anpasst."""
    from pipeline import publish
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    monkeypatch.setattr(config, "LEGISLATIVE_TERMS", tmp_path / "fehlt_terms.json")
    ohne = vorlage("1/2026", "Radweg an der Probestraße", stationen=[station(*MOB, "2026-04-01", "beschlossen")],
                   amt=None, steps=[])
    mit = vorlage("2/2026", "Bewohnerparken in Probestadt", stationen=[station(*BV, "2026-04-02")],
                  amt="[Testdaten] Amt für Probeverkehr", steps=[])
    export._themenseiten(tmp_path, {"a": ohne, "b": mit}, {"a": "gesamt", "b": "gesamt"}, [], gremien_daten(), {})
    feed = (tmp_path / "dossiers" / "verkehr.xml").read_text(encoding="utf-8")
    assert "<summary>Beschlussvorlage · Stand: in Beratung</summary>" in feed
    assert "unbekannt" not in feed and "federführend: [Testdaten] Amt für Probeverkehr" in feed
    assert publish.events(ohne)[0]["summary"] == "Beschlussvorlage · federführend: unbekannt · Stand: in Beratung"
    assert publish.events(ohne, federfuehrung_unbekannt=False)[0]["summary"] == "Beschlussvorlage · Stand: in Beratung"


def test_was_diese_seite_nicht_zeigt():
    """Keine falsche Aussage zu Hausnummern (Titel von Vorlagen der Verwaltung stehen wie veröffentlicht); Personalien
    und Sitzungsorganisation genannt."""
    text = " ".join(T.nicht_gezeigt)
    assert "Hausnummern und einzelne Orte" not in text and "Keine Verortung auf Hausnummern" in text
    assert "Personalien und Sitzungsorganisation" in text


def test_sitzungsliste_nicht_aktuell():
    gd = gremien_daten(liste={"stand": "2026-11-19T22:30:00+00:00", "hinweis": "…"})
    for e in gd["gremien"]:
        e.pop("naechste_sitzung", None)
        e.pop("folgende_sitzung", None)
    d = daten(gd)
    assert d["sitzungen"] == [] and d["meta"]["sitzungsliste_nicht_aktuell"]["stand"].startswith("2026-11-19")
    html = dossier.body(T, d, "../../")
    assert ("Die Liste der Sitzungen wurde beim letzten Abruf nicht aktualisiert; gezeigt wird der Stand vom 19.11.2026; "
            "deshalb fehlen die nächsten Sitzungen.") in html


def test_datenschutz_der_daten():
    """Keine Personenfelder (check.PERSONENFELD), keine entfallenen Felder (Frist, Federführung, Vorsitz), Eingaben nie
    als Punkt, Titel der Eingabe wie im Export (maskiert)."""
    d = daten()
    assert check._personenfelder(d) == 0
    assert not set(check._schluessel_rekursiv(d)) & check.DOSSIER_VERBOTEN
    eingabe = next(r for s in d["straenge"] for r in s["vorlagen"] if r["reference"] == "6/2026")
    assert eingabe["name"] == _cache()[P + "6-2026"]["name"]
    assert not any(dossier.punkt_art(p["paper_type"], p["name"]) is False for p in d["punkte"])
    for art, ja in (("Beschlussvorlage", True), ("Beschlussvorlage: Einleitung", True), ("Dringlichkeitsentscheidung OB", True),
                    ("Antrag nach § 3 der Geschäftsordnung des Rates", True), ("Änderungsantrag", True),
                    ("Dringlichkeitsantrag", True), ("Anfrage nach § 4 der Geschäftsordnung des Rates", False),
                    ("Mitteilung", False), ("Stellungnahme der Verwaltung", False), ("Anregungen und Beschwerden", False),
                    ("Einwohnerfrage", False), ("Bürgerantrag § 24 GO - Öffentlich", False), (None, False)):
        assert dossier.punkt_art(art, "Radweg") is ja, art
    assert dossier.punkt_art("Beschlussvorlage", "Anregung nach § 24 GO NRW: Radweg") is False


# --- Seite und Übersicht ----------------------------------------------------------------------------------------------

def _export(tmp_path, monkeypatch, gd=None, ebenen=False, freigabe=True):
    """Freigabe an (monkeypatch; mit freigabe=False wie im Repository), Datei dossiers/verkehr.json, .ics und .xml wie
    export, dazu suche.json und gremien.json; liefert den Ordner data/export/koeln unter tmp_path/_site."""
    if freigabe:
        monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
        monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    base = tmp_path / "_site" / "data" / "export" / "koeln"
    (base / "dossiers").mkdir(parents=True)
    gd = gd or gremien_daten()
    d = dossier.daten(T, _cache(), {k: "ortsteil:probestadt" for k in _cache()}, gd, {"note": "abgeleitet"})
    (base / "dossiers" / "verkehr.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    (base / "dossiers" / "verkehr.ics").write_text("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", encoding="utf-8")
    (base / "dossiers" / "verkehr.xml").write_text("<feed/>", encoding="utf-8")
    (base / "gremien.json").write_text(json.dumps(gd, ensure_ascii=False), encoding="utf-8")
    (base / "zeit.json").write_text(json.dumps({"meetings": []}), encoding="utf-8")
    rows = [[p["reference"], p["name"], p["date"], 0, 0, 0, [], [], [], -1, [], []] for p in _cache().values()]
    (base / "suche.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    if ebenen:
        (base / "ebenen.json").write_text(json.dumps({"ebenen": [{"key": "fahrradstrassen"}]}), encoding="utf-8")
        (base / "kontext.json").write_text(json.dumps({"ortsteile": {"x": {}}}), encoding="utf-8")
        (base / "flaechen").mkdir()
        (base / "flaechen" / "punkte_haltestellen.json").write_text("{}", encoding="utf-8")
    return base


class _Tabellen(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_vorlagen, self.zellen, self.ohne_l = False, 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.in_vorlagen = "vorlagen" in (a.get("class") or "")
        if tag == "td" and self.in_vorlagen:
            self.zellen += 1
            self.ohne_l += not a.get("data-l")


def _seite(tmp_path, monkeypatch, **k):
    base = _export(tmp_path, monkeypatch, **k)
    site = tmp_path / "_site"
    assert dossier.write(T, site, URL, gebietsseiten._page) == [T.pfad]
    return site, (site / T.pfad / "index.html").read_text(encoding="utf-8"), base


def test_seite_aufbau_wie_bonn(tmp_path, monkeypatch):
    site, html, _ = _seite(tmp_path, monkeypatch)
    folge = ['class="thema-kopf"', "<h1>Verkehr und Mobilität</h1>", 'class="lead"', '<nav class="thema-sprung"',
             "<h2>Auf einen Blick</h2>", "So ist das Bild gezeichnet", 'class="pb-filter"', '<h3 class="pb-filter-text">',
             'class="pb-bahnen"', 'class="pb-rahmen', 'class="pb-legende-bild"', 'id="pb-detail"', 'id="pb-daten"',
             'class="pb-liste"', 'class="pb-karten"', "<h3>Stand der Vorlagen je Strang</h3>",
             '<h2 id="fachausschuss" tabindex="-1">Wer berät mit: Mobilitätsausschuss</h2>',
             '<h2 id="sitzungen" tabindex="-1">Nächste Sitzungen</h2>', '<h2 id="mitwirken" tabindex="-1">Mitwirken</h2>',
             '<h2 id="vorlagen" tabindex="-1">Vorlagen nach Strang</h2>',
             "Wie die Vorlagen zugeordnet sind", '<h3 id="bus_bahn" tabindex="-1">', "Wie zugeordnet?", "Begriffe auf dieser Seite",
             "Was diese Seite nicht zeigt", "Quellen und Methode"]
    stellen = [html.find(x) for x in folge]
    assert -1 not in stellen, [x for x, i in zip(folge, stellen) if i < 0]
    assert stellen == sorted(stellen), [x for x, a, b in zip(folge, stellen, stellen[1:]) if a > b]
    nav = re.search(r'<nav class="thema-sprung" aria-labelledby="sprung-h"><h2 id="sprung-h">Auf dieser Seite</h2>'
                    r'<p>(.*?)</p></nav>', html).group(1)
    assert re.findall(r'href="#([^"]+)"', nav) == ["fachausschuss", "sitzungen", "mitwirken", "vorlagen"]
    # Sprungziele fokussierbar (tabindex="-1"): Nach dem Sprung liegt der Fokus auf der Überschrift, nicht auf body
    # (tests/browser/themen.js); ebenso die Stränge, auf die „Vorlagen nach Strang“ verweist
    for ziel in [*re.findall(r'href="#([^"]+)"', nav), *[k for k, _, _ in T.straenge if f'id="{k}"' in html]]:
        assert re.search(rf'<h[23] id="{ziel}" tabindex="-1">', html), ziel
    assert "seit Beginn der Wahlperiode (01.11.2025)" in html
    assert f'<link rel="canonical" href="{URL}{T.pfad}">' in html
    assert 'content="https://koeln.ratsatlas.de/og-image.png"' in html and "-zeitleiste." not in html
    assert '<a class="thema-alle" href="../../thema/">Alle Themen</a>' in html
    assert 'class="kachel-symbol" viewBox="0 0 24 24"' in html and 'aria-hidden="true" focusable="false"' in html
    t = _Tabellen()
    t.feed(html)
    assert t.zellen > 0 and t.ohne_l == 0
    assert "<summary>Innenstadt (2)</summary>" in html and "<summary>ohne Ortsbezug (1)</summary>" in html
    assert html.count('klasse="hh-mehr meta-acc regel-acc"') == 0 and html.count('class="hh-mehr meta-acc regel-acc"') == 6
    assert "Frist" not in html and "21 Tage" not in html and "Federführend:" not in html and "federführend:" not in html
    assert "?thema=" not in html and "Bild zum Teilen" not in html
    # Wer berät mit: aus gremien.json, ohne Personen, mit Links in die Gremienansicht und auf die Vorlagen
    assert '<a href="../../?wer=gremien&amp;kennung=mob-1a2b3c4d">' in html and 'href="../../?gremium_filter=mob-1a2b3c4d"' in html
    assert "In den 12 Monaten bis 21.11.2026: 6 Sitzungen, 80 Vorlagen beraten" in html
    assert "Vorlagen dieses Themas beraten außerdem die Bezirksvertretungen, der Hauptausschuss und der Rat" in html
    # Sitzungen: verschoben laut Name, Tagesordnung, ohne Frist
    assert ("26.11.2026, 17:00 Uhr: Bezirksvertretung 1 (Innenstadt) <small>(laut Sitzungsnamen verschoben)</small> "
            '(<a href="https://example.invalid/sitzung" target="_blank" rel="noopener">Tagesordnung</a>)') in html
    assert list((site / "data" / "export" / "koeln" / "dossiers").iterdir())
    assert not list(site.rglob("*zeitleiste*"))


def test_karten_links_nur_mit_ebene(tmp_path, monkeypatch):
    """Links zur Karte (Antwort 3 A): Fahrradstraßen und Haltestellen nur, wenn die Ebene im Bau vorliegt; die Vorlagen
    des Mobilitätsausschusses über ?gremium_filter; nie ?thema=."""
    _, ohne, _ = _seite(tmp_path / "a", monkeypatch)
    assert "?ebenen=" not in ohne and '<a class="pb-knopf pb-knopf-leise" href="../../?gremium_filter=mob-1a2b3c4d">' in ohne
    _, mit, _ = _seite(tmp_path / "b", monkeypatch, ebenen=True)
    assert 'href="../../?ebenen=fahrradstrassen">Fahrradstraßen</a>' in mit
    assert 'href="../../?ebenen=haltestellen">Haltestellen</a>' in mit
    monkeypatch.setitem(config.ZUSATZTHEMEN, "kontext", False)
    _, aus, _ = _seite(tmp_path / "c", monkeypatch, ebenen=True)
    assert "?ebenen=" not in aus


def test_uebersicht_einzahl_und_kachel(tmp_path, monkeypatch):
    site, _, _ = _seite(tmp_path, monkeypatch)
    assert dossier.uebersicht([T], site, URL, gebietsseiten._page) == ["thema/"]
    html = (site / "thema" / "index.html").read_text(encoding="utf-8")
    assert "<li><strong>1</strong> Thema</li>" in html and "Themen</li>" not in html
    # Entscheidung 25.11.2026 (7): Überschrift, Seitentitel und Link bleiben in der Mehrzahl, auch bei einem Thema
    assert "<h1>Themen</h1>" in html and "<title>Themen – Ratsatlas Köln</title>" in html
    assert "Die Themenseite ordnet Vorlagen" in html and "zeigt, wo ein Verfahren steht" in html
    assert 'content="Themenseite des Ratsatlas Köln: Verkehr und Mobilität' in html
    assert '<h2><a href="../thema/verkehr-und-mobilitaet/">Verkehr und Mobilität</a></h2>' in html
    assert 'class="kachel-symbol"' in html and 'aria-label="Stränge"' in html
    assert "Nächste Sitzung: Mobilitätsausschuss, <time datetime=\"2026-12-02\">Mi. 02.12.2026</time>" in html
    assert "Frist" not in html and "Anregungen bis" not in html and "Haushalt" not in html
    assert "Vorlagen in 6 Strängen" in html
    # Einzahl auch bei einer Vorlage in einem Strang
    d = {"straenge": [{"titel": "Bus und Bahn", "vorlagen": [{}]}], "meta": {}, "heute": "2026-11-21"}
    assert "<strong>1</strong> Vorlage in 1 Strang</p>" in dossier._kachel(T, d)


def test_uebersicht_stichprobe_nur_nach_pruefung(tmp_path, monkeypatch):
    """„an einer Stichprobe von Hand geprüft“ nur, wenn jedes gezeigte Thema geprüft ist (pruefung_text, pruefung_datum)."""
    site, _, _ = _seite(tmp_path, monkeypatch)
    ohne = dataclasses.replace(T, pruefung_text="", pruefung_datum="")
    dossier.uebersicht([ohne], site, URL, gebietsseiten._page)
    assert "Stichprobe" not in (site / "thema" / "index.html").read_text(encoding="utf-8")
    mit = dataclasses.replace(T, pruefung_text="Geprüft im Gespräch.", pruefung_datum="2026-12-01")
    dossier.uebersicht([mit], site, URL, gebietsseiten._page)
    assert "je Vorlage mit Grund, an einer Stichprobe von Hand geprüft." in (site / "thema" / "index.html").read_text(encoding="utf-8")


def test_ohne_json_keine_seite(tmp_path):
    assert dossier.write(T, tmp_path, URL, gebietsseiten._page) == []
    assert dossier.uebersicht([T], tmp_path, URL, gebietsseiten._page) == []
    assert not (tmp_path / "thema").exists()


# --- Freigabe ---------------------------------------------------------------------------------------------------------

def test_freigabe_im_repository():
    """Freigabe je Thema (Entscheidung 24.11.2026 (3) (2)): Hauptschalter genau bei nichtleerer Liste, nur zusammen mit
    „gremien“; jeder Schlüssel hat eine Datei, steht in topics.THEMES mit gleichem Titel und ist von Hand geprüft
    (pruefung_text, pruefung_datum). Gilt für den Stand im Repository (ohne Prüfschalter)."""
    from pipeline.topics import THEMES
    if config.themen_pruefung():
        pytest.skip("Prüfschalter gesetzt")
    assert bool(config.ZUSATZTHEMEN["themenseiten"]) == bool(config.THEMENSEITEN_FREIGEGEBEN)
    if config.THEMENSEITEN_FREIGEGEBEN:
        assert config.ZUSATZTHEMEN["gremien"]
    for k in config.THEMENSEITEN_FREIGEGEBEN:
        t = themenseiten.JE_SCHLUESSEL[k]
        assert themenseiten.geprueft(t) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", t.pruefung_datum), k
    for t in themenseiten.ALLE:
        assert t.titel == dict(THEMES)[t.key] and t.pfad.startswith("thema/") and t.pfad.endswith("/")


def test_freigabe_verkehr_im_repository():
    """Freigabe am 25.11.2026 nach dem Prüfbogen: ohne Prüfschalter liefert freigegeben() das Thema, es ist geprüft, und
    pruefung_text und pruefung_datum stehen wie entschieden in der Themendatei."""
    if config.themen_pruefung():
        pytest.skip("Prüfschalter gesetzt")
    assert config.THEMENSEITEN_FREIGEGEBEN == ("verkehr",) and config.ZUSATZTHEMEN["themenseiten"] is True
    assert themenseiten.freigegeben() == [T] and themenseiten.entwuerfe() == [] and themenseiten.geprueft(T)
    assert T.pruefung_datum == "2026-11-25"
    assert T.pruefung_text == ("Eine Stichprobe von 32 Vorlagen wurde am 25.11.2026 geprüft (Vorschlag einer KI, im "
                               "Gespräch von Hand bestätigt: 19 passend, 3 teilweise, 1 unpassend, 3 ohne angezeigten "
                               "Titel nicht beurteilbar; in der Gegenprobe fehlten 2 von 6), danach wurden die Regeln "
                               "ergänzt.")


def test_check_dossiers_ohne_befund_mit_freigabe_des_repositorys(tmp_path, monkeypatch):
    """check.dossiers mit der Freigabe und der Themendatei aus dem Repository (ohne Ersatz): kein Befund (nur der
    Themenkalender ist ohne Sitzungsdatei nicht prüfbar)."""
    if config.themen_pruefung():
        pytest.skip("Prüfschalter gesetzt")
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    base = _export(tmp_path, monkeypatch, freigabe=False)
    befunde, fehlend = check.dossiers(base, umgebung={})
    assert befunde == [] and len(fehlend) == 1 and "Themenkalender" in fehlend[0]


def test_seite_nennt_methode_und_pruefung(tmp_path, monkeypatch):
    """„Quellen und Methode“ beschreibt die Regeln (Thema.methode), „Wie die Vorlagen zugeordnet sind“ das Ergebnis der
    Prüfung; die Regel je Strang nennt die neuen Regeln."""
    _, html, _ = _seite(tmp_path, monkeypatch)
    quellen = html[html.index("Quellen und Methode"):]
    assert "Methode der Zuordnung: Feste Regeln in dieser Reihenfolge" in quellen
    assert "höchstens drei Ausschüsse die Vorlage beraten" in quellen
    assert "Radverbindungen, Bauarbeiten an benannten Straßen, Straßenrecht, Bestellungen von Personen" in quellen
    assert "Eine Stichprobe von 32 Vorlagen wurde am 25.11.2026 geprüft" in html
    regeln = {k: r for k, _, r in T.straenge}
    assert "Radverbindungen" in regeln["rad_fuss"] and "höchstens drei Ausschüsse" in regeln["weitere"]
    assert "Widmung, Teileinziehung, Straßenabschnitt" in regeln["strassen"] and "Einrichtung" in regeln["strassen"]
    nicht = " ".join(T.nicht_gezeigt)
    assert "Vorlagen vieler Ausschüsse" in nicht and "Bestellungen von Vertreterinnen" in nicht


def test_beschreibung_vollstaendig():
    for t in themenseiten.ALLE:
        straenge = {k for k, _, _ in t.straenge}
        bahnen = [k for k, _ in t.bahnen]
        assert {r.strang for r in t.regeln} <= straenge and set(t.punkt_straenge) <= straenge
        assert dossier.FACH in bahnen and {b for b, _ in t.bahn_regeln} <= set(bahnen)
        assert all(r.titel is not None or r.gremium_tor for r in t.regeln)
        assert set(t.nach_bezirk) <= straenge and set(t.stichprobe_je_strang) <= straenge
        assert t.kandidat and t.stichprobe_ohne and t.stichprobe_nur_gremium <= t.stichprobe_je_strang.get("weitere", 0)
        assert (t.tor_hoechstens is None) == (t.tor_gremien is None)
        assert t.tor_hoechstens is None or (t.fachausschuss and t.fachausschuss.gruppe == t.tor_gremien.gruppe)


def test_freigegeben_reihenfolge_und_hauptschalter(monkeypatch):
    zweites = dataclasses.replace(T, key="kultur", pfad="thema/kultur-und-sport/", titel="Kultur und Sport")
    monkeypatch.setitem(themenseiten.JE_SCHLUESSEL, "kultur", zweites)
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("kultur", "verkehr"))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    assert [t.key for t in themenseiten.freigegeben()] == ["kultur", "verkehr"]
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
    assert [t.key for t in themenseiten.freigegeben()] == ["verkehr"]
    assert [t.key for t in themenseiten.entwuerfe()] == []
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", False)
    assert themenseiten.freigegeben() == [] and [t.key for t in themenseiten.entwuerfe()] == ["verkehr"]
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("schule",))
    with pytest.raises(SystemExit):
        themenseiten.freigegeben()


def test_pruefschalter_nur_mit_testdaten(tmp_path):
    stand = tmp_path / "STAND.json"
    umgebung = {config.THEMEN_PRUEFUNG: " verkehr , verkehr "}
    assert config.themen_pruefung(umgebung, stand) is None                       # ohne Datei
    stand.write_text(json.dumps({"papers": "2026-11-21T22:00:00+00:00"}))
    assert config.themen_pruefung(umgebung, stand) is None                       # echte Daten
    stand.write_text(json.dumps({"testdaten": "ja"}))
    assert config.themen_pruefung(umgebung, stand) is None                       # nur true zählt
    stand.write_text(json.dumps({"testdaten": True}))
    assert config.themen_pruefung(umgebung, stand) == ("verkehr",)
    assert config.themen_pruefung({}, stand) is None


def _lauf_config(raw, schalter):
    umgebung = {"PATH": "/usr/bin:/bin", "RATSATLAS_RAW": str(raw)}
    if schalter is not None:
        umgebung[config.THEMEN_PRUEFUNG] = schalter
    return subprocess.run([sys.executable, "-c", "from pipeline import config, themenseiten; "
                           "print(config.THEMENSEITEN_FREIGEGEBEN, config.ZUSATZTHEMEN['themenseiten'], "
                           "[t.key for t in themenseiten.freigegeben()])"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120, env=umgebung)


@pytest.mark.parametrize("testdaten", [True, False])
@pytest.mark.parametrize("schalter, erwartet", [("verkehr", "('verkehr',) True ['verkehr']"), ("aus", "() False []")])
def test_pruefschalter_im_lauf(tmp_path, testdaten, schalter, erwartet):
    """Der Schalter wirkt beim Laden von config: mit Testdaten in STAND.json Liste und Hauptschalter für diesen Lauf
    („verkehr“ ein, „aus“ aus), gleich, was im Repository steht; ohne Testdaten gilt der Stand im Repository, mit
    Meldung."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "STAND.json").write_text(json.dumps({"testdaten": testdaten}))
    repository = _lauf_config(raw, None)
    assert repository.returncode == 0 and not repository.stderr, repository.stderr
    r = _lauf_config(raw, schalter)
    assert r.returncode == 0, r.stderr
    if testdaten:
        assert r.stdout.strip() == erwartet and not r.stderr
    else:
        assert r.stdout == repository.stdout and "ohne Wirkung" in r.stderr


def test_check_meldet_pruefschalter_ohne_testdaten(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ())
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", False)
    monkeypatch.setattr(config, "STAND", tmp_path / "STAND.json")
    for wert in ("verkehr", "aus"):
        befunde, _ = check.dossiers(tmp_path, umgebung={config.THEMEN_PRUEFUNG: wert})
        assert any(config.THEMEN_PRUEFUNG in b for b in befunde), wert
    befunde, fehlend = check.dossiers(tmp_path, umgebung={})
    assert befunde == [] and fehlend == []
    # mit Testdaten ist „aus“ kein Befund (erster Bau in tests.yml)
    config.STAND.write_text(json.dumps({"testdaten": True}), encoding="utf-8")
    befunde, fehlend = check.dossiers(tmp_path, umgebung={config.THEMEN_PRUEFUNG: "aus"})
    assert befunde == [] and fehlend == []


def test_check_dossiers(tmp_path, monkeypatch):
    """check.dossiers: mit Freigabe genau die Dateien des Themas, ohne Befund bei passenden Daten; ohne Prüfung von Hand
    ein Befund; eine Datei ohne Freigabe ein Befund; ein Personenfeld, ein entfallenes Feld oder ein anderer Titel als in
    suche.json je ein Befund."""
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    base = _export(tmp_path, monkeypatch)
    # ohne Prüfung von Hand, gleich, was im Repository steht
    monkeypatch.setitem(themenseiten.JE_SCHLUESSEL, "verkehr", dataclasses.replace(T, pruefung_text="", pruefung_datum=""))
    befunde, fehlend = check.dossiers(base, umgebung={})
    assert befunde == ["Themenseiten: verkehr freigegeben ohne Prüfung von Hand (pruefung_text, pruefung_datum): 1"]
    geprueft = dataclasses.replace(T, pruefung_text="Geprüft im Gespräch.", pruefung_datum="2026-12-01")
    monkeypatch.setitem(themenseiten.JE_SCHLUESSEL, "verkehr", geprueft)
    befunde, fehlend = check.dossiers(base, umgebung={})
    assert befunde == [] and len(fehlend) == 1 and "Themenkalender" in fehlend[0]
    doc = json.loads((base / "dossiers" / "verkehr.json").read_text(encoding="utf-8"))
    doc["straenge"][0]["vorlagen"][0]["name"] += " 12"
    doc["straenge"][0]["vorlagen"][0]["frist"] = "2026-12-01"
    doc["meta"]["vorsitz"] = "–"
    (base / "dossiers" / "verkehr.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    befunde, _ = check.dossiers(base, umgebung={})
    texte = " | ".join(befunde)
    for teil in ("Titel anders als in suche.json: 1", "entfallene Felder (DOSSIER_VERBOTEN): 2",
                 "Feldnamen, die auf Personen deuten: 1"):
        assert teil in texte, texte
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", False)
    befunde, _ = check.dossiers(base, umgebung={})
    assert befunde == ["Themenseiten: Dateien unter dossiers/ ohne freigegebenes Thema: 3"]


def test_ohne_freigabe_nichts(tmp_path, monkeypatch):
    """Ohne Freigabe: export schreibt keine Datei unter dossiers/, seo keine Seite thema/ und keinen Eintrag in der
    Sitemap, die Karte „Themenseiten“ fehlt in index.html, rss/ nennt keine Themenfeeds, LICENSE-DATA keinen Abschnitt."""
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ())
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", False)
    out = tmp_path / "koeln"
    export._themenseiten(out, {"x": {}}, {}, [], None, {})
    assert not (out / "dossiers").exists()
    site = tmp_path / "_site"
    (site / "data" / "export" / "koeln" / "dossiers").mkdir(parents=True)
    (site / "data" / "export" / "koeln" / "dossiers" / "verkehr.json").write_text(json.dumps(daten()))
    seo.write(site, URL)
    assert not (site / "thema").exists() and "thema/" not in (site / "sitemap.xml").read_text(encoding="utf-8")
    index = seo.ohne_abgeschaltete((ROOT / "site" / "index.html").read_text(encoding="utf-8"))
    assert 'href="thema/"' not in index
    rss = (site / "rss" / "index.html").read_text(encoding="utf-8")
    assert "dossiers/" not in rss and "Themenseite" not in rss
    assert "dossiers/" not in freigaben.text((ROOT / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8"))


def test_mit_freigabe_seite_sitemap_feed_lizenz(tmp_path, monkeypatch):
    base = _export(tmp_path, monkeypatch)
    site = tmp_path / "_site"
    seo.write(site, URL)
    assert (site / T.pfad / "index.html").exists() and (site / "thema" / "index.html").exists()
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{URL}thema/</loc>" in sitemap and f"<loc>{URL}{T.pfad}</loc>" in sitemap
    assert 'href="thema/"' in seo.ohne_abgeschaltete((ROOT / "site" / "index.html").read_text(encoding="utf-8"))
    assert "dossiers/" in freigaben.text((ROOT / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8"))
    (base / "dossiers" / "verkehr.xml").write_text("<feed><entry></entry></feed>", encoding="utf-8")
    rssseite.write(site, URL, gebietsseiten._page)
    assert "dossiers/verkehr.xml" in (site / "rss" / "index.html").read_text(encoding="utf-8")


def test_karte_und_neu_nur_mit_geschriebener_uebersicht(tmp_path, monkeypatch):
    """Startseite (Prüfung der CI und der Daten, 25.11.2026): Karte „Themenseiten“ und Eintrag in „Was ist neu?“ nur, wenn
    seo die Übersicht thema/ schreibt; mit Freigabe, aber ohne Vorlagen (Kartenvorschau) fehlen beide, und die
    Linkprüfung findet keinen Link auf eine fehlende Seite. Der Satz zu den Bonner Zusatzthemen nennt die Themenseiten
    nie."""
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    vorschau = tmp_path / "vorschau"
    vorschau.mkdir()
    (vorschau / "index.html").write_text((ROOT / "site" / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    seo.write(vorschau, URL)
    index = (vorschau / "index.html").read_text(encoding="utf-8")
    assert not (vorschau / "thema").exists() and 'href="thema/"' not in index and 'data-funktion="themenseiten"' not in index
    assert "Bonner Zusatzthemen (Haushalt, Ratsassistent und weitere)" in index and "Themenseiten" not in index
    _export(tmp_path / "mit", monkeypatch)
    site = tmp_path / "mit" / "_site"
    (site / "index.html").write_text((ROOT / "site" / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    seo.write(site, URL)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="thema/"' in index and (site / "thema" / "index.html").exists()
    assert '<li data-funktion="themenseiten">Themenseiten (Menü „Themen“)' in index
    assert "Bonner Zusatzthemen (Haushalt, Ratsassistent und weitere)" in index


def test_export_setzt_gremien_voraus(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    with pytest.raises(SystemExit, match="gremien.json"):
        export._themenseiten(tmp_path, {"x": {}}, {}, [], None, {})
    export._themenseiten(tmp_path, {}, {}, [], None, {})   # Kartenvorschau ohne Vorlagen: keine Datei
    assert not (tmp_path / "dossiers").exists()


# --- Herkunft und Texte -----------------------------------------------------------------------------------------------

DATEIEN = ["pipeline/dossier.py", "pipeline/prozessbild.py", "pipeline/akkordeon.py", "pipeline/mitwirken.py",
           *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "pipeline" / "themenseiten").glob("*.py"))]


def test_keine_bonner_reste():
    """Keine Bonner Texte, Adressen, Regeln oder Marken in den Modulen der Themenseiten (die Herkunft
    daimpad/ratsatlas-bonn bleibt genannt)."""
    for datei in DATEIEN:
        text = (ROOT / datei).read_text(encoding="utf-8")
        for wort in ("Bonn", "bonn.de", "bonn.biz", "OParl-Lite", "Bürgerantrag", "21 Tage", "GeschO § 26", "§ 27",
                     "zwei Wochen", "allris-bonn", "FRIST_TAGE", "cairosvg", 'property="og:', "Nordbrücke"):
            assert wort not in text, (datei, wort)
    assert [p.name for p in sorted((ROOT / "pipeline" / "themenseiten").glob("*.py"))] == ["__init__.py", "verkehr.py"]


def _quellen_js():
    js = (ROOT / "site" / "beteiligung.js").read_text(encoding="utf-8")
    teil = js[js.index("export const QUELLEN = {"):js.index("};", js.index("export const QUELLEN = {"))]
    return dict(re.findall(r'(\w+): \{ label: "[^"]*", wo: [^,]+,\s*url: "([^"]+)" \}', teil))


def test_adressen_wie_mitmachen_in_koeln(tmp_path, monkeypatch):
    """Adressen von „Mitwirken“ und den Karten gleich den Einträgen in site/beteiligung.js QUELLEN; auf der Seite sonst
    nur die Zuständigkeitsordnung (gremien.json) und Adressen aus den Daten; kein Link auf die veraltete Seite zur
    Einwohnerfragestunde."""
    js = _quellen_js()
    assert len(js) >= 10
    for k, (_, _, url) in mitwirken.QUELLEN.items():
        assert js.get(k) == url, k
    _, html, _ = _seite(tmp_path, monkeypatch)
    extern = set(re.findall(r'<a [^>]*href="(https?://[^"]+)"', html))
    erlaubt = set(js.values()) | {SATZUNG, "https://example.invalid/sitzung", "https://example.invalid/vorlage",
                                 "https://nozilla.de/impressum/"}
    assert extern <= erlaubt, extern - erlaubt
    assert js["fragestunde"] not in html


def test_mitwirken_ohne_berechnete_frist():
    html = mitwirken.abschnitt("../../")
    assert "spätestens am fünften Arbeitstag vor der Sitzung bis 12 Uhr" in html
    assert "§ 24 GO NRW" in html and "§ 25 GO NRW" in html and 'href="../../?mitmachen=1"' in html
    assert not re.search(r"\d{2}\.\d{2}\.\d{4}", html.replace("19.03.2026", "").replace(mitwirken.STAND, ""))


# --- Durchsicht vom 25.11.2026 (Korrekturrunde nach der Freigabe) ------------------------------------------------------

@pytest.mark.parametrize("titel, strang", [
    ("Ausbau des Radschnellwegs Probestadt–Probedorf", "rad_fuss"), ("Neubau des Radschnellweges an der Probestraße", "rad_fuss"),
    ("Instandsetzung des Fußgängerwegs Probeweg", "rad_fuss"), ("Sanierung des Fernradwegs am Probeufer", None),
    ("Sanierung des Rheinuferwegs", None), ("Ausbau des Rad-Gehwegs an der Probestraße", "rad_fuss")])
def test_zusammengesetzte_wege_sind_kein_strassenname(titel, strang):
    """Radschnellweg, Fernradweg, Fußgängerweg, Uferweg und andere zusammengesetzte allgemeine Wege gelten nicht als
    Straßenname (STRASSENBAU steht vor Rad- und Fußverkehr); die Vorlage bleibt bei Rad- und Fußverkehr oder ohne Strang."""
    assert not verkehr.STRASSENBAU.search(titel)
    assert (zu(titel, [station(*BV, "2026-04-01")]) or (None,))[0] == strang


@pytest.mark.parametrize("name", ["Rademacherweg", "Baumläuferweg", "Strandläuferweg", "Zugweg", "Kiefernweg"])
def test_namen_aus_dem_verzeichnis_bleiben_strassennamen(name):
    """Kölner Namen, die mit Rad beginnen oder auf -läuferweg enden, sind Straßennamen (Straßenverzeichnis)."""
    assert name in json.loads(config.STRASSEN.read_text(encoding="utf-8"))["streets"]
    assert zu(f"Sanierung des {name}s", [station(*BV, "2026-04-01")])[0] == "strassen"


@pytest.mark.parametrize("titel", ["Sanierung Theater Probestraße", "Neubau Hochbunker Probeweg", "Umbau Kloster Probeweg",
                                   "Neubau Container Probestraße", "Neubau Sozialhäuser Probestr."])
def test_einrichtung_auf_er_vor_dem_strassennamen(titel):
    """Ein Hauptwort auf -er zwischen Bauarbeit und Straßenname (Theater, Bunker, Kloster, Container) ist eine
    Einrichtung, kein Teil des Namens: kein Straßenbau."""
    assert not verkehr.STRASSENBAU.search(titel)
    assert zu(titel, [station(*BV, "2026-04-01")]) is None


@pytest.mark.parametrize("titel, grund", [("Generalinstandsetzung der Kalker Hauptstraße", "Generalinstandsetzung der Kalker Hauptstraße"),
                                          ("Sanierung der Alte Römerstraße", "Sanierung der Alte Römerstraße"),
                                          ("Umbau der Probener Straße", "Umbau der Probener Straße")])
def test_wort_auf_er_aus_dem_verzeichnis_vor_dem_namen(titel, grund):
    """Vor einem Namen aus einem Wort zählen Alte, Neue und Ähnliches sowie Wörter auf -er, die im Straßenverzeichnis vor
    dem letzten Wort eines Namens stehen („Kalker“); vor Straße, Weg, Ring allein jedes Wort auf -er."""
    assert zu(titel, [station(*BV, "2026-04-01")]) == ("strassen", f"Titel: „{grund}“")


@pytest.mark.parametrize("titel", ["Beantwortung einer mündlichen Anfrage von RM Probe", "Anfrage von SB Probemann zur Probestraße",
                                   "Schreiben der Bürgermeisterin Probe zum Radweg", "Oberbürgermeister Probe: Tempo 30"])
def test_personenbezug_kuerzel_und_buergermeister(titel):
    """PERSONENBEZUG (Prüfbogen) erkennt die Kürzel RM und SB und Bürgermeister(in) vor einem großgeschriebenen Wort."""
    assert dossier.PERSONENBEZUG.search(titel), titel


@pytest.mark.parametrize("titel", ["Radweg an der Probestraße", "RMV-Anschluss", "Mitteilung der Bürgermeisterin zur Sitzung",
                                   "SBahn-Haltestelle Probeplatz"])
def test_personenbezug_ohne_kuerzel(titel):
    assert not dossier.PERSONENBEZUG.search(titel), titel


BERICHT = "https://example.invalid/oparl/meetings/bericht-2026-12-31"
BERICHT_NAME = "[Testdaten] Berichtssitzung des Mobilitätsausschusses (nur für Digitales Berichtswesen)"


def _mit_berichtssitzung():
    """gremien.json mit nächster Sitzung des Mobilitätsausschusses am Datenstand und einer folgenden Sitzung nur für das
    Digitale Berichtswesen am 31.12. (ohne Uhrzeit), dazu die Sitzungen wie in zeit.json und eine Vorlage mit Station dort."""
    gd = gremien_daten()
    mob = next(e for e in gd["gremien"] if e["key"] == MOB[0])
    mob["naechste_sitzung"] = _sitzung("2026-11-21", "15:00")
    mob["folgende_sitzung"] = {"date": "2026-12-31", "time": None, "web": None, "source_object": BERICHT}
    meetings = [{"source_object": BERICHT, "name": BERICHT_NAME, "date": "2026-12-31", "time": None},
                {"source_object": "https://example.invalid/oparl/meetings/2026-11-21", "name": "[Testdaten] Sitzung",
                 "date": "2026-11-21", "time": "15:00"}]
    p = vorlage("1/2026", "Radweg an der Probestraße", stand="entschieden", stationen=[
        station(*MOB, "2026-11-21", "beschlossen"),
        station(*MOB, "2026-12-31", "für das Digitale Berichtswesen", meeting=BERICHT_NAME, meeting_id=BERICHT)])
    return gd, meetings, p


def test_berichtssitzung_keine_kommende_sitzung_und_kein_beschluss_in_der_zukunft():
    """Durchsicht vom 25.11.2026: Eine Sitzung nur für das Digitale Berichtswesen (31.12., Ergebnis „für das Digitale
    Berichtswesen“) steht nicht unter „Nächste Sitzungen“, nicht in „Wer berät mit“ und nicht als Hand im Bild; Lage des
    Punkts und letzte Beratung der Zeile folgen der letzten echten Beratung, das Detailfeld nennt beide wörtlich."""
    gd, meetings, p = _mit_berichtssitzung()
    d = dossier.daten(T, {"a": p}, {"a": "ortsteil:probestadt"}, gd, {}, [{"start": "2025-11-01"}], None, meetings)
    assert "2026-12-31" not in [m["date"] for m in d["sitzungen"]]
    assert "folgende_sitzung" not in d["wer_beraet_mit"] and d["wer_beraet_mit"]["naechste_sitzung"]["date"] == "2026-11-21"
    (x,) = d["punkte"]
    assert (x["date"], x["bahn"]) == ("2026-11-21", "mobil")
    assert [b["result"] for b in x["beratungen"]] == ["beschlossen", "für das Digitale Berichtswesen"]
    zeile = d["straenge"][[s["key"] for s in d["straenge"]].index("rad_fuss")]["vorlagen"][0]
    assert zeile["letzte_beratung"]["date"] == "2026-11-21"
    html = dossier.body(T, d, "../../")
    assert "31.12.2026: öffentliche Sitzung" not in html and "danach 31.12.2026" not in html
    assert "Digitale Berichtswesen der Stadt" in html
    # die Rechnung von check (Sitzungen aus zeit.json) ergibt dasselbe
    ohne = dossier.berichtssitzungen(meetings)
    assert ohne == {BERICHT}
    assert dossier.sitzungen(T, gd, {e["key"]: e for e in gd["gremien"]}, ohne) == d["sitzungen"]
    assert dossier.wer_beraet_mit(T, gd, ohne) == d["wer_beraet_mit"]
    # die Erkennung über den Namen der Station gilt auch ohne Sitzungsliste
    assert dossier.ohne_berichtswesen(p)["process"] == p["process"][:1]


def test_check_dossiers_mit_berichtssitzung(tmp_path, monkeypatch):
    """check.dossiers rechnet die Sitzungen ohne die Sitzungen für das Digitale Berichtswesen aus zeit.json: kein Befund
    für die Datei aus dossier.daten mit den Sitzungen, ein Befund für eine Datei, die die Berichtssitzung nennt."""
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    gd, meetings, _ = _mit_berichtssitzung()
    base = _export(tmp_path, monkeypatch, gd=gd)
    (base / "zeit.json").write_text(json.dumps({"meetings": meetings}, ensure_ascii=False), encoding="utf-8")
    d = dossier.daten(T, _cache(), {k: "ortsteil:probestadt" for k in _cache()}, gd, {"note": "abgeleitet"}, (), None,
                      meetings)
    (base / "dossiers" / "verkehr.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    befunde, _ = check.dossiers(base, umgebung={})
    assert befunde == []
    ohne_liste = dossier.daten(T, _cache(), {k: "ortsteil:probestadt" for k in _cache()}, gd, {"note": "abgeleitet"})
    (base / "dossiers" / "verkehr.json").write_text(json.dumps(ohne_liste, ensure_ascii=False), encoding="utf-8")
    befunde, _ = check.dossiers(base, umgebung={})
    assert "Themenseite verkehr: Sitzungen anders als gremien.json: 1" in befunde
    assert "Themenseite verkehr: „Wer berät mit“ anders als gremien.json: 1" in befunde


def test_themenfeed_ohne_ereignisse_nach_dem_datenstand(tmp_path, monkeypatch):
    """Der Themenfeed nennt kein Ereignis nach dem Datenstand von gremien.json (Berichtswesen mit Ergebnis am 31.12.);
    die Beratung davor steht im Feed."""
    monkeypatch.setattr(config, "THEMENSEITEN_FREIGEGEBEN", ("verkehr",))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "themenseiten", True)
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    monkeypatch.setattr(config, "LEGISLATIVE_TERMS", tmp_path / "fehlt_terms.json")
    gd, meetings, p = _mit_berichtssitzung()
    p.update(amt=None, steps=[
        {"typ": "beratung", "label": "Mobilitätsausschuss", "role": "Vorberatung", "date": "2026-11-21", "result": "beschlossen"},
        {"typ": "beratung", "label": "Mobilitätsausschuss", "role": "Vorberatung", "date": "2026-12-31",
         "result": "für das Digitale Berichtswesen"}])
    export._themenseiten(tmp_path, {"a": p}, {"a": "gesamt"}, meetings, gd, {})
    feed = (tmp_path / "dossiers" / "verkehr.xml").read_text(encoding="utf-8")
    assert "2026-12-31" not in feed and "Berichtswesen" not in feed
    assert "Mobilitätsausschuss: „beschlossen“" in feed and "<updated>2026-11-21T00:00:00Z</updated>" in feed


def test_lange_straenge_eingeklappt():
    """Stränge mit mindestens Thema.einklappen_ab Vorlagen stehen eingeklappt (Durchsicht vom 25.11.2026: mit echten Daten
    sonst über 100.000 px Seite); kürzere offen."""
    assert T.einklappen_ab == 15
    ps = {f"p{i}": vorlage(f"{i}/2026", f"Radweg an der Probestraße {i}", stationen=[station(*BV, "2026-04-01")])
          for i in range(1, 16)}
    ps["b"] = vorlage("99/2026", "Bewohnerparken in Probestadt", stationen=[station(*BV, "2026-04-01")])
    d = dossier.daten(T, ps, {k: "ortsteil:probestadt" for k in ps}, gremien_daten(), {}, [{"start": "2025-11-01"}])
    je = {s["key"]: s for s in d["straenge"]}
    assert len(je["rad_fuss"]["vorlagen"]) == 15 and je["rad_fuss"]["eingeklappt"] and not je["parken"]["eingeklappt"]
    html = dossier.body(T, d, "../../")
    start = html.index('<h3 id="rad_fuss"')
    assert "<summary>15 Vorlagen anzeigen</summary>" in html[start:html.index("<h3 ", start + 1)]
    parken = html.index('<h3 id="parken"')
    assert "anzeigen</summary>" not in html[parken:html.find("<h2", parken)]


def test_drucksache_bricht_nicht_um():
    """Durchsicht vom 25.11.2026: Drucksachen wie AN/1234/2026 brechen in der Tabelle nicht mitten in der Jahreszahl um."""
    css = (ROOT / "site" / "page.css").read_text(encoding="utf-8")
    regel = re.search(r'\.page table\.vorlagen td\[data-l="Drucksache"\] \{([^}]*)\}', css)
    assert regel and "white-space: nowrap" in regel.group(1)
    assert re.search(r"\.page table\.vorlagen th:nth-child\(2\) \{ width: 9\.5em; \}", css)


def test_sammelmarke_zweiter_knopf_zum_schliessen():
    """Durchsicht vom 25.11.2026: Das Detailfeld einer Sammelmarke hat am Ende einen zweiten Knopf zum Schließen, der
    wie „Schließen“ den Fokus auf die Marke im Bild zurückgibt."""
    js = (ROOT / "site" / "thema.js").read_text(encoding="utf-8")
    teil = js[js.index("function sammlung"):js.index("function inhalt")]
    assert '"Schließen, zurück zum Bild", "pb-knopf pb-knopf-leise pb-schliessen-unten"' in teil
    assert "schliessen(true)" in teil
