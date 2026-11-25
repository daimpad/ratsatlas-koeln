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


def gremien_daten(mob_key="mob-1a2b3c4d", mit_mob=True, liste=None):
    """Inhalt von gremien.json in der Form von gremien.daten (erfundene Gremien, Datenstand 21.11.2026)."""
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


LAUF = dossier.Lauf(seit="2025-11-01", tor="mob-1a2b3c4d", tor_name="Mobilitätsausschuss")
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
    """Die erste passende Regel gilt (Parken, Bus und Bahn, Rad- und Fußverkehr, Tempo, Straßen, weitere):
    Fahrradstellplätze zählen nicht als Parken, aber der Bahnhof geht dem Fahrrad vor."""
    assert zu("Fahrradstellplätze am Bahnhof Probestadt")[0] == "bus_bahn"
    assert zu("Parkplätze an der Haltestelle Probeplatz")[0] == "parken"
    assert zu("Tempo 30 auf der Probebrücke")[0] == "tempo"
    assert zu("Radverkehr und Fahrbahnsanierung")[0] == "rad_fuss"
    assert [r.strang for r in T.regeln][:6] == ["parken", "bus_bahn", "rad_fuss", "tempo", "strassen", "weitere"]


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

def _export(tmp_path, monkeypatch, gd=None, ebenen=False):
    """Freigabe an (monkeypatch), Datei dossiers/verkehr.json, .ics und .xml wie export, dazu suche.json und
    gremien.json; liefert den Ordner data/export/koeln unter tmp_path/_site."""
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
             '<h2 id="fachausschuss">Wer berät mit: Mobilitätsausschuss</h2>', '<h2 id="sitzungen">Nächste Sitzungen</h2>',
             '<h2 id="mitwirken">Mitwirken</h2>', '<h2 id="vorlagen">Vorlagen nach Strang</h2>',
             "Wie die Vorlagen zugeordnet sind", '<h3 id="bus_bahn">', "Wie zugeordnet?", "Begriffe auf dieser Seite",
             "Was diese Seite nicht zeigt", "Quellen und Methode"]
    stellen = [html.find(x) for x in folge]
    assert -1 not in stellen, [x for x, i in zip(folge, stellen) if i < 0]
    assert stellen == sorted(stellen), [x for x, a, b in zip(folge, stellen, stellen[1:]) if a > b]
    nav = re.search(r'<nav class="thema-sprung" aria-labelledby="sprung-h"><h2 id="sprung-h">Auf dieser Seite</h2>'
                    r'<p>(.*?)</p></nav>', html).group(1)
    assert re.findall(r'href="#([^"]+)"', nav) == ["fachausschuss", "sitzungen", "mitwirken", "vorlagen"]
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


def test_beschreibung_vollstaendig():
    for t in themenseiten.ALLE:
        straenge = {k for k, _, _ in t.straenge}
        bahnen = [k for k, _ in t.bahnen]
        assert {r.strang for r in t.regeln} <= straenge and set(t.punkt_straenge) <= straenge
        assert dossier.FACH in bahnen and {b for b, _ in t.bahn_regeln} <= set(bahnen)
        assert all(r.titel is not None or r.gremium_tor for r in t.regeln)
        assert set(t.nach_bezirk) <= straenge and set(t.stichprobe_je_strang) <= straenge
        assert t.kandidat and t.stichprobe_ohne and t.stichprobe_nur_gremium <= t.stichprobe_je_strang.get("weitere", 0)


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


@pytest.mark.parametrize("testdaten", [True, False])
def test_pruefschalter_im_lauf(tmp_path, testdaten):
    """Der Schalter wirkt beim Laden von config: mit Testdaten in STAND.json Liste und Hauptschalter für diesen Lauf,
    ohne Testdaten nichts, mit Meldung."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "STAND.json").write_text(json.dumps({"testdaten": testdaten}))
    r = subprocess.run([sys.executable, "-c", "from pipeline import config, themenseiten; "
                        "print(config.THEMENSEITEN_FREIGEGEBEN, config.ZUSATZTHEMEN['themenseiten'], "
                        "[t.key for t in themenseiten.freigegeben()])"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120,
                       env={"PATH": "/usr/bin:/bin", "RATSATLAS_RAW": str(raw), config.THEMEN_PRUEFUNG: "verkehr"})
    assert r.returncode == 0, r.stderr
    if testdaten:
        assert r.stdout.strip() == "('verkehr',) True ['verkehr']" and not r.stderr
    else:
        assert r.stdout.strip() == "() False []" and "ohne Wirkung" in r.stderr


def test_check_meldet_pruefschalter_ohne_testdaten(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STAND", tmp_path / "STAND.json")
    befunde, _ = check.dossiers(tmp_path, umgebung={config.THEMEN_PRUEFUNG: "verkehr"})
    assert any(config.THEMEN_PRUEFUNG in b for b in befunde)
    befunde, fehlend = check.dossiers(tmp_path, umgebung={})
    assert befunde == [] and fehlend == []


def test_check_dossiers(tmp_path, monkeypatch):
    """check.dossiers: mit Freigabe genau die Dateien des Themas, ohne Befund bei passenden Daten; ohne Prüfung von Hand
    ein Befund; eine Datei ohne Freigabe ein Befund; ein Personenfeld, ein entfallenes Feld oder ein anderer Titel als in
    suche.json je ein Befund."""
    monkeypatch.setattr(config, "MEETINGS", tmp_path / "fehlt.json")
    base = _export(tmp_path, monkeypatch)
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
