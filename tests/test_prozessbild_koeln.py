"""Zeitleiste der Kölner Themenseiten (pipeline/prozessbild.py, Port aus daimpad/ratsatlas-bonn @730d593 mit Kölner
Anpassungen): Achse aus dem Datenstand, Bahnen aus gremien.json, Bahnnamen als stehende Spalte, Legende als HTML, Punkte
und Sitzungen als Links, Detaildaten ohne Frist und Federführung, Schalter und Stand je Strang. Erfundene Daten."""
import json
import re
from datetime import date

import pytest

from pipeline import dossier, prozessbild
from pipeline.themenseiten import verkehr

from test_themenseiten_koeln import daten, gremien_daten, station, vorlage

T = verkehr.THEMA


def test_achse_aus_dem_datenstand():
    """Anfang Monat der Wahlperiode, Knick drei Monate vor heute, Ende Monat nach heute plus sechs Monaten, bis zum
    spätesten kommenden Termin, höchstens zwölf Monate; auch über einen Jahreswechsel; ohne Rückblick linear."""
    assert dossier.achse("2026-11-21", "2025-11-01") == {"von": "2025-11-01", "knick": "2026-08-01", "bis": "2027-06-01",
                                                          "anteil": 0.42}
    assert dossier.achse("2026-12-31", "2025-11-14") == {"von": "2025-11-01", "knick": "2026-09-01", "bis": "2027-07-01",
                                                          "anteil": 0.42}
    assert dossier.achse("2026-12-31", "2025-11-01", ["2027-09-15"])["bis"] == "2027-10-01"
    assert dossier.achse("2026-12-31", "2025-11-01", ["2029-05-01"])["bis"] == "2028-01-01"
    assert dossier.achse("2026-12-31", "2025-11-01", ["2026-01-01"])["bis"] == "2027-07-01"   # vergangene zählen nicht
    neu = dossier.achse("2030-12-01", "2030-11-01")
    assert neu == {"von": "2030-11-01", "knick": "2030-11-01", "bis": "2031-07-01", "anteil": 0.0}
    a = prozessbild.Achse({"achse": neu})
    xs = [a.x(t) for t in ("2030-10-01", "2030-11-01", "2031-01-15", "2031-07-01", "2032-01-01")]
    assert xs == sorted(xs) and xs[0] == xs[1] == prozessbild.LINKS and xs[-1] == xs[-2] == prozessbild.W - prozessbild.RECHTS


def test_element_ausserhalb_im_text():
    d = daten()
    assert "außerhalb" not in prozessbild._beschreibung(T, d)
    d["sitzungen"].append({**d["sitzungen"][0], "date": "2028-01-15"})
    assert "1 Angabe liegt außerhalb des Zeitraums und steht am Rand des Bildes." in prozessbild._beschreibung(T, d)


def test_bahnen_aus_gremien_json():
    """Jede Station und Sitzung liegt auf einer Bahn aus t.bahnen (kein ValueError in _zeile); ein aufgelöstes Gremium
    ohne Kennung und ein Gremium ohne Eintrag liegen auf „fach“."""
    d = daten()
    keys = [k for k, _ in T.bahnen]
    for x in d["punkte"] + d["sitzungen"]:
        assert x["bahn"] in keys
        prozessbild._zeile(T, x["bahn"])
    je = {e["key"]: e for e in gremien_daten()["gremien"]}
    assert dossier.bahn(T, None, "[Testdaten] früherer Verkehrsausschuss", je) == "fach"
    assert dossier.bahn(T, "unbekannt", "Rat", je) == "fach"
    assert dossier.bahn(T, "alt", "[Testdaten] früherer Verkehrsausschuss", je) == "fach"   # aufgelöst


def test_svg_ohne_bahnnamen_und_legende_feste_masse():
    d = daten()
    svg = prozessbild.svg(T, d, "../../")
    h = prozessbild.hoehe(T)
    assert svg.startswith(f'<svg class="pb-svg" width="{prozessbild.W}" height="{h}" viewBox="0 0 {prozessbild.W} {h}" ')
    texte = re.findall(r"<text[^>]*>([^<]*)</text>", svg)
    for _, label in T.bahnen:
        assert label not in texte
    for wort in ("entschieden", "offen", "Frist", "Legende", "Sitzung"):
        assert not any(wort in t for t in texte), wort
    assert "Stand 21.11." in texte
    spalte = prozessbild.bahnen_spalte(T)
    assert spalte.count('<span class="pb-bahn">') == len(T.bahnen) and 'aria-hidden="true"' in spalte
    abschnitt = prozessbild.abschnitt(T, d, "../../")
    assert (f'<div class="pb-zeitleiste" style="--pb-oben:{prozessbild.OBEN}px;--pb-bahn:{prozessbild.BAHN}px;'
            f'--pb-breite:{prozessbild.W}px;--pb-hoehe:{h}px">') in abschnitt
    i = [abschnitt.index(x) for x in ('class="pb-bahnen"', 'class="pb-rahmen pb-breit"', '<svg class="pb-svg"',
                                      'class="pb-legende-bild"', 'id="pb-detail"')]
    assert i == sorted(i)


def test_links_nur_mit_root():
    d = daten()
    ohne = prozessbild.svg(T, d)
    assert 'role="img"' in ohne and "<a " not in ohne
    mit = prozessbild.svg(T, d, "../../")
    assert 'role="img"' not in mit
    ziele = re.findall(r'<a class="pb-ziel" href="([^"]*)" aria-label="([^"]*)"', mit)
    assert len(ziele) == len(d["punkte"]) + len(d["sitzungen"]) and all(label for _, label in ziele)
    assert ("../../?gebiet=ortsteil:probestadt#1/2026", "1: 1/2026 [Testdaten] Radweg an der Probestraße – entschieden "
            "(Rat, 02.04.2026)") in ziele
    assert ("https://example.invalid/sitzung", "Bezirksvertretung 1 (Innenstadt), 26.11.2026: öffentliche Sitzung, laut "
            "Sitzungsnamen verschoben, Tagesordnung") in ziele
    d["sitzungen"][0]["web"] = None
    assert '<a class="pb-ziel" href="#sitzungen"' in prozessbild.svg(T, d, "../../")


def test_detaildaten_ohne_frist_und_federfuehrung():
    d = daten()
    d["punkte"][0]["name"] = "[Testdaten] Titel mit </script> darin"
    text = prozessbild.detaildaten(T, d, "../../")
    assert "</" not in text
    j = json.loads(text)
    assert set(j) == {"heute", "kalender", "mitmachen", "punkte", "sitzungen"}
    assert j["kalender"] == "../../data/export/koeln/dossiers/verkehr.ics"
    for p in j["punkte"].values():
        assert "amt" not in p and "frist" not in p and p["karte"].startswith("../../?gebiet=")
    assert all(set(s) == {"gremium", "date", "time", "hinweis", "web"} for s in j["sitzungen"])
    p9 = next(p for p in j["punkte"].values() if p["reference"] == "9/2026")
    assert p9["beratungen"][0]["abgesagt"] == "name"


def test_schalter_nur_fuer_straenge_mit_punkten():
    d = daten()
    s = prozessbild.schalter(T, d)
    assert s.startswith('    <div class="pb-filter" role="group"') and " hidden>" in s
    assert '<h3 class="pb-filter-text">Stränge im Bild</h3>' in s
    mit = {p["strang"] for p in d["punkte"]}
    assert set(re.findall(r'data-strang="([^"]+)"', s)) == mit and "bus_bahn" not in mit


def test_stand_balken_und_legende_als_html():
    d = daten()
    b = prozessbild.stand_balken(d)
    assert '<ul class="pb-balken">' in b and '<p class="pb-legende">' in b
    assert b.count("<li>") == len(d["straenge"])
    lg = prozessbild.legende()
    assert lg.count("<li>") == 5 and lg.count('aria-hidden="true"') == 5
    for text in ("entschieden", "beraten, ohne abschließende Entscheidung", "offen", "nächste öffentliche Sitzung",
                 "Datenstand"):
        assert text in lg


def test_karten_ohne_frist_mit_mitmachen():
    d = daten()
    k = prozessbild.aufrufe(T, d, "../../", [("../../?ebenen=fahrradstrassen", "Fahrradstraßen")])
    assert k.count('class="pb-karte"') == 5
    assert 'href="../../data/export/koeln/dossiers/verkehr.ics" download' in k
    assert 'href="../../data/export/koeln/dossiers/verkehr.xml"' in k and 'href="../../?mitmachen=1"' in k
    assert "https://www.stadt-koeln.de/rat-live/" in k and "Frist" not in k and "21 Tage" not in k
    assert prozessbild.aufrufe(T, d, "../../").count('class="pb-karte"') == 4


@pytest.mark.parametrize("n, text", [(0, "Im Bild stehen keine Beschlüsse und Anträge."),
                                     (1, "<summary>Ein Beschluss oder Antrag im Bild</summary>")])
def test_liste_einzahl(n, text):
    d = daten()
    d["punkte"] = d["punkte"][:n]
    assert text in prozessbild.liste(d, "../../")


def test_punkt_auf_bahn_der_letzten_beratung():
    """Lage wie in Bonn: letzte Beratung mit Ergebnis, sonst die nächste; die Bahn über die Kennung der Station."""
    gd = gremien_daten()
    je = {e["key"]: e for e in gd["gremien"]}
    p = vorlage("1/2026", "Radweg", stationen=[station("bv1", "Bezirksvertretung 1 (Innenstadt)", "2026-03-01", "beschlossen"),
                                               station("mob-1a2b3c4d", "Mobilitätsausschuss", "2026-12-02")])
    e = {**dossier._eintrag(p, "ortsteil:x", "2026-11-21"), "grund": "Titel: „Radweg“"}
    x = dossier._punkt(T, p, e, "rad_fuss", je, "2026-11-21")
    assert (x["bahn"], x["date"], x["gremium"]) == ("bv", "2026-03-01", "Bezirksvertretung 1 (Innenstadt)")
    p["process"][0]["result"] = None
    x = dossier._punkt(T, p, {**dossier._eintrag(p, None, "2026-11-21"), "grund": ""}, "rad_fuss", je, "2026-11-21")
    assert (x["bahn"], x["date"]) == ("mobil", "2026-12-02")
    assert date.fromisoformat(x["date"])
