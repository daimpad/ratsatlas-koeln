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
    marken = prozessbild.lage(T, d)
    assert len(ziele) == len(marken) and all(label for _, label in ziele)
    assert sum(len(m["eintraege"]) for m in marken) == len(d["punkte"]) + len(d["sitzungen"])
    assert ("../../?gebiet=ortsteil:probestadt#1/2026", "1: 1/2026 [Testdaten] Radweg an der Probestraße – entschieden "
            "(Rat, 02.04.2026)") in ziele
    assert ("https://example.invalid/sitzung", "Bezirksvertretung 1 (Innenstadt), 26.11.2026: öffentliche Sitzung, laut "
            "Sitzungsnamen verschoben, Tagesordnung") in ziele
    d["sitzungen"][0]["web"] = None
    assert '<a class="pb-ziel" href="#sitzungen"' in prozessbild.svg(T, d, "../../")


def test_detaildaten_ohne_frist_und_federfuehrung():
    d = daten()
    d["punkte"][0]["name"] = "[Testdaten] Titel mit </script> darin"
    d["punkte"][1]["name"] = '[Testdaten] Titel mit <!--<script> und "q" & <img src=x>'
    text = prozessbild.detaildaten(T, d, "../../")
    # kein „<“, „>“ oder „&“ im Skript-Element: weder „</script>“ noch „<!--<script>“ ändern den Zustand des Parsers
    assert not set("<>&") & set(text)
    j = json.loads(text)
    assert j["punkte"]["2"]["name"] == d["punkte"][1]["name"] and j["punkte"]["1"]["name"].endswith("</script> darin")
    assert set(j) == {"heute", "kalender", "mitmachen", "punkte", "sitzungen", "gruppen"}
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
    """Lage: letzte Beratung mit Ergebnis, sonst die nächste, beides nur in den Gremien des Bildes (Rat, Hauptausschuss,
    Mobilitätsausschuss; Antwort 2 A); die Bahn über die Kennung der Station."""
    gd = gremien_daten()
    je = {e["key"]: e for e in gd["gremien"]}
    im_bild = {e["key"] for a in T.punkt_gremien for e in dossier.gremien_auswahl(gd, a)}
    p = vorlage("1/2026", "Radweg", stationen=[station("bv1", "Bezirksvertretung 1 (Innenstadt)", "2026-03-01", "beschlossen"),
                                               station("mob-1a2b3c4d", "Mobilitätsausschuss", "2026-12-02")])
    e = {**dossier._eintrag(p, "ortsteil:x", "2026-11-21"), "grund": "Titel: „Radweg“"}
    x = dossier._punkt(T, p, e, "rad_fuss", je, "2026-11-21", im_bild)
    assert (x["bahn"], x["date"], x["gremium"]) == ("mobil", "2026-12-02", "Mobilitätsausschuss")
    assert [b["gremium"] for b in x["beratungen"]] == ["Bezirksvertretung 1 (Innenstadt)", "Mobilitätsausschuss"]
    p["process"][1]["result"] = "beschlossen"
    p["process"][1]["start_date"] = "2026-04-01T16:00:00+01:00"
    x = dossier._punkt(T, p, {**dossier._eintrag(p, None, "2026-11-21"), "grund": ""}, "rad_fuss", je, "2026-11-21", im_bild)
    assert (x["bahn"], x["date"]) == ("mobil", "2026-04-01")
    assert date.fromisoformat(x["date"])


# --- Lage der Ziele im Bild (Prüfung der Seite, 25.11.2026) -----------------------------------------------------------

# Ausdehnung je Art um die Mitte (links, rechts, oben, unten) wie in prozessbild._marke gezeichnet
AUSDEHNUNG = {"punkt": (9, 9, 9, 9), "sitzung": (10.5, 10.5, 10.5, 10.5), "punkte": (10, 10, 10, 9),
              "sitzungen": (10, 11.5, 11.5, 10.5)}


def _gedraengt(n_tag=30, heute="2026-11-21"):
    """Daten mit vielen Beschlüssen am selben Tag in einer Bahn, Punkten an aufeinanderfolgenden Tagen um den Datenstand,
    Sitzungen dicht beieinander in der Bahn der Bezirksvertretungen und Punkten am Rand der Achse."""
    d = daten()
    vorbild = d["punkte"][0]
    punkte = [{**vorbild, "date": "2026-11-05", "bahn": "mobil"} for _ in range(n_tag)]
    punkte += [{**vorbild, "date": tag, "bahn": "rat"} for tag in ("2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22",
                                                                  "2026-11-23", "2025-11-01", "2025-11-02", "2027-05-30")]
    for i, p in enumerate(punkte, 1):
        p["nr"] = i
    d["punkte"] = punkte
    s0 = d["sitzungen"][0]
    d["sitzungen"] = [{**s0, "bahn": "bv", "date": tag, "gremium": f"Bezirksvertretung {i}"}
                      for i, tag in enumerate(("2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-12-07",
                                               "2026-12-08"), 1)]
    d["sitzungen"].append({**s0, "bahn": "mobil", "date": "2026-11-26", "gremium": "Mobilitätsausschuss"})
    d["heute"] = heute
    return d


@pytest.mark.parametrize("n_tag", [1, 2, 3, 30])
def test_lage_ohne_ueberdeckung_ohne_verschiebung_im_bild(n_tag):
    """Kein Ziel überdeckt ein anderes, keines liegt außerhalb des Bildes oder seiner Bahn, keines weicht um mehr als
    eineinhalb Platzbreiten von seinem Tag ab, kein Ziel bis zum Datenstand steht rechts der Linie des Datenstands und
    keines danach links; jeder Punkt und jede Sitzung steht genau einmal im Bild, und das SVG zeichnet genau diese Ziele."""
    d = _gedraengt(n_tag)
    a = prozessbild.Achse(d)
    xh = a.x(d["heute"])
    marken = prozessbild.lage(T, d)
    punkte = sorted(p["nr"] for m in marken if m["art"] in ("punkt", "punkte") for p in m["eintraege"])
    sitzungen = sorted(i for m in marken if m["art"] in ("sitzung", "sitzungen") for i, _ in m["eintraege"])
    assert punkte == [p["nr"] for p in d["punkte"]] and sitzungen == list(range(len(d["sitzungen"])))
    boxen = []
    for m in marken:
        l, r, o, u = AUSDEHNUNG[m["art"]]
        oben = prozessbild._zeile(T, m["bahn"])
        assert 0 <= m["x"] - l and m["x"] + r <= prozessbild.W, m
        assert oben <= m["y"] - o and m["y"] + u <= oben + prozessbild.BAHN, m
        tage = [p["date"] for p in m["eintraege"]] if m["art"] in ("punkt", "punkte") else [s["date"] for _, s in m["eintraege"]]
        for tag in tage:
            assert abs(m["x"] - a.x(tag)) <= 1.5 * prozessbild.SPALT, (m["ziel"], tag)
            assert (m["x"] < xh) if tag <= d["heute"] else (m["x"] > xh), (m["ziel"], tag)
        boxen.append((m["x"] - l, m["x"] + r, m["y"] - o, m["y"] + u, m["ziel"]))
    for i, b in enumerate(boxen):
        for c in boxen[i + 1:]:
            assert b[1] <= c[0] or c[1] <= b[0] or b[3] <= c[2] or c[3] <= b[2], (b, c)
    svg = prozessbild.svg(T, d, "../../")
    assert re.findall(r'data-ziel="([^"]+)"', svg) == [m["ziel"] for m in marken]
    # viele Beschlüsse an einem Tag: eine Sammelmarke mit Zahl, nicht nach rechts geschoben
    if n_tag >= 3:
        gruppe = next(m for m in marken if m["art"] == "punkte" and m["bahn"] == "mobil")
        assert len(gruppe["eintraege"]) == n_tag and f">{n_tag}</text>" in svg
        assert f'data-punkte="{" ".join(str(i) for i in range(1, n_tag + 1))}"' in svg


def test_sammelmarken_in_detaildaten_legende_und_liste():
    d = _gedraengt(30)
    j = json.loads(prozessbild.detaildaten(T, d, "../../"))
    marken = prozessbild.lage(T, d)
    gruppen = {m["ziel"]: m for m in marken if m["art"] in ("punkte", "sitzungen")}
    assert set(j["gruppen"]) == set(gruppen) and any(k.startswith("sitzungen-") for k in gruppen)
    assert j["gruppen"]["punkte-0"][:2] == ["punkt-1", "punkt-2"]
    lg = prozessbild.legende(marken)
    assert "mehrere Beschlüsse und Anträge an nahen Tagen (Zahl)" in lg and "mehrere Sitzungen an nahen Tagen (Zahl)" in lg
    assert "mehrere" not in prozessbild.legende(prozessbild.lage(T, daten()))
    svg = prozessbild.svg(T, d, "../../")
    assert '<a class="pb-ziel" href="#pb-liste" aria-label="30 Beschlüsse und Anträge am 05.11.2026' in svg
    assert re.search(r'<a class="pb-ziel" href="#sitzungen" aria-label="\d öffentliche Sitzungen: Bezirksvertretung 1 am '
                     r'23\.11\.2026', svg)
    assert '<details class="pb-liste" id="pb-liste">' in prozessbild.liste(d, "../../")
    abschnitt = prozessbild.abschnitt(T, d, "../../")
    assert "Sammelmarke" in abschnitt and "Punkte und Sitzungen lassen sich anklicken" in abschnitt


def test_ohne_ziele_kein_satz_zum_anklicken():
    d = daten()
    d["punkte"], d["sitzungen"] = [], []
    assert "anklicken" not in prozessbild.abschnitt(T, d, "../../")
