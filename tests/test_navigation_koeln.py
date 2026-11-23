"""Pull Request 3 der Navigation (Entscheidungen 19.11.2026 (1) und 20.11.2026 (7)): Leiste mit „Themen“, „Wer
entscheidet“, „Mitmachen“ und „Über“, Menüs ohne Platzhalter, Startfenster mit „Aktuell in Köln“, Hinweise zum Stand
aus dem Sitzungsnamen auf der Seite, Wege zurück, Vorgang. Geprüft ohne Browser (node mit nachgebildetem Dokument,
Python); die Prüfung im Browser steht in tests/browser/navigation.js. Alle Daten sind erfunden; keine Anfragen nach
außen."""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline import config, seo

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
BETEILIGUNG = ROOT / "site" / "beteiligung.js"
MENUES = ("mega-themen", "mega-entscheiden", "mega-mitmachen", "mega-ueber")
FOLGT = re.compile(r"\bfolg(?:t|en)\b", re.I)


def _node(code, modul=False):
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    args = [node, "--input-type=module", "-e", code] if modul else [node, "-e", code]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _teil(quelle, muster):
    m = re.search(muster, quelle, re.S | re.M)
    assert m, muster
    return m.group(0)


def _abschnitt(html, element_id):
    """Das Element mit `element_id` samt Inhalt (section, div; gleichnamige Elemente darin gezählt)."""
    m = re.search(rf'<(\w+)[^>]*\bid="{re.escape(element_id)}"', html)
    assert m, element_id
    tag, start, tiefe = m.group(1), m.start(), 0
    for t in re.finditer(rf"<(/?){tag}\b[^>]*>", html[start:]):
        tiefe += -1 if t.group(1) else 1
        if tiefe == 0:
            return html[start:start + t.end()]
    raise AssertionError(element_id)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class _Elemente(HTMLParser):
    """Start-Tags mit Attributen in der Reihenfolge des Dokuments."""

    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags(html):
    p = _Elemente()
    p.feed(html)
    return p.tags


def _karten(abschnitt):
    """Titel der Karten (span.card-title) in der Reihenfolge des Menüs."""
    return re.findall(r'<span class="card-title">([^<]*)</span>', abschnitt)


# --- 1 Leiste ----------------------------------------------------------------------------------------------------------

def test_leiste_reihenfolge_und_beschriftung():
    """Die Leiste: Suche, dann (hinter ☰ auf dem Telefon) Gebiet, Flächen und die Menüs „Themen“, „Wer entscheidet“,
    „Mitmachen“, „Über“ in dieser Reihenfolge; „Über“ ist ein Menü (kein Dialog mehr); die früheren Menüs „Auswertung“,
    „Daten“ und „Verstehen“ gibt es nicht mehr; der Knopf „Assistent“ bleibt abgeschaltet."""
    nav = _abschnitt(INDEX, "nav-more")
    gruppe = re.search(r'<div class="nav-group" role="group" aria-label="Menü">(.*?)</div>', nav, re.S).group(1)
    knoepfe = re.findall(r'<button type="button" class="menu-btn" data-mega="([\w-]+)"[^>]*>.*?<span>([^<]+)</span>', gruppe, re.S)
    assert knoepfe == [("mega-themen", "Themen"), ("mega-entscheiden", "Wer entscheidet"), ("mega-mitmachen", "Mitmachen"),
                       ("mega-ueber", "Über")]
    # Zwischen 901 und 1599 px stehen nur Symbole: Jede Schaltfläche nennt beim Überfahren mit der Maus ihren Namen und
    # Inhalt (title wie bei den Flächen; Prüfung von Pull Request 3); „Wer entscheidet“ im HTML ohne „Gremien“ und
    # „Ämter“, mit Freigabe „gremien“ setzt app.js den Titel mit beiden (test_titel_wer_entscheidet_nach_freigabe)
    titel = dict(re.findall(r'<button type="button" class="menu-btn" data-mega="([\w-]+)"[^>]*\btitle="([^"]+)"', gruppe))
    assert titel == {"mega-themen": "Themen: Vorlagen nach Thema, Kennzahlen zum Gebiet",
                     "mega-entscheiden": "Wer entscheidet: Verfahrenswege in Zahlen",
                     "mega-mitmachen": "Mitmachen: sich einbringen und informiert bleiben",
                     "mega-ueber": "Über: Lesehilfen, Über den Ratsatlas, Daten"}
    kopf = _abschnitt(INDEX, "nav-search")
    assert INDEX.index(kopf) < INDEX.index('id="nav-more"')
    for menue in MENUES:
        assert '<section class="mega glass' in _abschnitt(INDEX, menue) and f'aria-controls="{menue}"' in gruppe
    for alt in ("mega-auswertung", "mega-daten", "mega-verstehen"):
        for quelle in (INDEX, APP, (ROOT / "site" / "tour.js").read_text(encoding="utf-8")):
            assert alt not in quelle, alt
    assert re.search(r'<button type="button" class="card" id="about-open" aria-haspopup="dialog">', INDEX)
    assert 'class="menu-btn" id="about-open"' not in INDEX
    ai = re.search(r'<button type="button" class="toggle toggle-ai"[^>]*>', INDEX).group(0)
    assert 'data-funktion="chat"' in ai and 'data-freigabe="chat"' in ai and " hidden>" in ai
    # veröffentlicht (Kölner Freigaben): kein Assistent, die vier Menüs bleiben
    aus = seo.ohne_abgeschaltete(INDEX)
    assert "toggle-ai" not in aus and all(f'data-mega="{m}"' in aus for m in MENUES)


# --- 2 Menüs ohne Platzhalter ------------------------------------------------------------------------------------------

def test_menue_inhalte():
    """Themen: Themen als Filter und „Kennzahlen zum Gebiet“ (Themenseiten und Haushalt nur mit Freigabe); Wer
    entscheidet: „Gremien“ und „Ämter“ (nur mit Freigabe „gremien“, seit Pull Request 4b), „Verfahrenswege in Zahlen“;
    Mitmachen: „Aktuell in Köln“, „Kommende Sitzungen“ samt Kalender,
    „Selbst mitwirken“, „Informiert bleiben“; Über: Lesehilfen, Über den Ratsatlas, Daten."""
    themen = _abschnitt(INDEX, "mega-themen")
    assert 'id="themen-chips" role="group" aria-label="Thema wählen"' in themen
    assert _karten(themen) == ["Kennzahlen zum Gebiet", "Themenseiten", "Haushalt auf einen Blick"]
    assert '<button type="button" class="card" data-open-tab="stats">' in themen
    assert '<a class="card" href="thema/" data-funktion="themenseiten" hidden>' in themen
    assert '<a class="card" href="haushalt/" data-funktion="haushalt" hidden>' in themen
    entscheiden = _abschnitt(INDEX, "mega-entscheiden")
    assert _karten(entscheiden) == ["Gremien", "Ämter", "Verfahrenswege in Zahlen"]
    for reiter in ("gremien", "aemter"):
        assert f'<button type="button" class="card" data-wer="{reiter}" data-funktion="gremien" data-freigabe="gremien" hidden>' in entscheiden
    assert '<button type="button" class="card" data-open-tab="wege">' in entscheiden
    mitmachen = _abschnitt(INDEX, "mega-mitmachen")
    assert _karten(mitmachen) == ["Aktuell in Köln", "Kommende Sitzungen", "Selbst mitwirken", "Informiert bleiben"]
    assert 'data-home="aktuell"' in mitmachen and 'id="cta-termine"' in mitmachen
    assert 'href="data/export/koeln/termine.ics" download' in mitmachen and "§ 24 GO NRW" in mitmachen
    assert 'id="cta-mitmachen" data-funktion="mitmachen" hidden' in mitmachen and 'id="cta-feed"' in mitmachen
    ueber = _abschnitt(INDEX, "mega-ueber")
    gruppen = re.findall(r'<h3 class="mega-label[^"]*">.*?</svg>([^<]+)</h3>', ueber)
    assert gruppen == ["Lesehilfen", "Über den Ratsatlas", "Daten"]
    assert _karten(ueber) == ["Einfache Sprache", "Begriffe erklärt", "Tour durch alle Funktionen", "Über den Ratsatlas",
                              "Wie verlässlich sind die Angaben?", "So funktioniert der Ratsatlas", "Was ist neu?",
                              "Hinweis geben", "Datenpaket (Zip)", "Verortete Vorlagen (GeoJSON)",
                              "Datensatzbeschreibung (DCAT-AP)", "Feeds abonnieren und einbinden"]
    for teil in ('data-tour>', 'data-about="pruefung"', "data-neu>", 'id="cta-report"', 'href="rss/"',
                 'href="data/export/ratsatlas-koeln-export.zip" download', 'href="data/export/koeln/dcat.jsonld"'):
        assert teil in ueber, teil
    # „Fehler melden“ ist als „Hinweis geben“ ins Menü „Über“ gewandert, nicht doppelt
    assert INDEX.count('id="cta-report"') == 1 and "Fehler melden" not in INDEX


def test_wer_entscheidet_gremien_und_aemter_nur_mit_freigabe(monkeypatch):
    """Entscheidung 20.11.2026 (7) (a) und 23.11.2026 (1): Ohne Freigabe „gremien“ steht in „Wer entscheidet“ nur die
    Karte der Verfahrenswege, ohne Erwähnung von Gremien und Ämtern (data-freigabe entfernt die Karten und die Fläche
    beim Bau); mit Freigabe dazu „Gremien“ und „Ämter“. Kein Platzhalter, keine Besetzung, kein „folgt“, keine Bonner
    Kennungen (data-pz-tab)."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    aus = seo.ohne_abgeschaltete(INDEX)
    entscheiden = _abschnitt(aus, "mega-entscheiden")
    assert _karten(entscheiden) == ["Verfahrenswege in Zahlen"]
    for wort in ("Ämter", "Gremien:", "Rat, Ausschüsse", "Besetzung", "Pull Request", "bald", "demnächst") + ("folgt", "folgen"):
        assert wort not in _text(entscheiden), wort
    assert "panel-gremien" not in aus and "data-wer=" not in aus
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", True)
    an = seo.ohne_abgeschaltete(INDEX)
    entscheiden = _abschnitt(an, "mega-entscheiden")
    assert _karten(entscheiden) == ["Gremien", "Ämter", "Verfahrenswege in Zahlen"]
    for wort in ("Besetzung", "Pull Request", "bald", "demnächst") + ("folgt", "folgen"):
        assert wort not in _text(entscheiden), wort
    assert 'id="panel-gremien"' in an
    assert "data-pz-tab" not in INDEX


def test_menues_und_startfenster_ohne_folgt():
    """Entscheidung 19.11.2026 (1) (F): keine Ankündigung mit „folgt“ oder „folgen“ in den Menüs und im Startfenster,
    auch nicht in den Hinweisen der Vorschau; ein Block ohne Daten fehlt einfach."""
    for menue in ("mega-suche",) + MENUES:
        text = _text(_abschnitt(INDEX, menue))
        assert not FOLGT.search(text), (menue, FOLGT.search(text).group(0))
    start = _teil(APP, r"^  const INTRO = \(offen\) => `.*?\n  const ZURUECK_KOELN = .*?;\n") \
        + _teil(APP, r"^  function standHinweis\(\) \{\n.*?\n  \}\n") \
        + _teil(APP, r"^  function aktuellHtml\(offen\) \{\n.*?\n  \}\n")
    assert not FOLGT.search(start)
    assert "Tagesordnung folgt" not in APP


def test_kacheln_abgeschalteter_funktionen_fehlen_in_der_veroeffentlichten_seite(monkeypatch):
    """seo.ohne_abgeschaltete entfernt die Karten abgeschalteter Funktionen auch aus den neuen Menüs (Themenseiten,
    Haushalt; ohne Freigabe auch Einfache Sprache, „So funktioniert der Ratsatlas“ und „Alle Wege im Überblick“)."""
    an = seo.ohne_abgeschaltete(INDEX)
    assert config.ZUSATZTHEMEN["einfache_sprache"] and config.ZUSATZTHEMEN["technik"]
    assert _karten(_abschnitt(an, "mega-themen")) == ["Kennzahlen zum Gebiet"]
    assert "Einfache Sprache" in _karten(_abschnitt(an, "mega-ueber"))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "einfache_sprache", False)
    monkeypatch.setitem(config.ZUSATZTHEMEN, "technik", False)
    aus = seo.ohne_abgeschaltete(INDEX)
    assert _karten(_abschnitt(aus, "mega-ueber"))[:3] == ["Begriffe erklärt", "Tour durch alle Funktionen", "Über den Ratsatlas"]
    assert "So funktioniert der Ratsatlas" not in _karten(_abschnitt(aus, "mega-ueber")) and 'href="technik/"' not in aus


# --- 3 Startfenster: „Aktuell in Köln“ und Hinweis zum Datenstand ------------------------------------------------------

def _start(index, heute="2026-11-20", zeit=True, telefon=False, offen=False):
    """standHinweis, aktuellListen und aktuellHtml aus app.js mit erfundenem index.json und festem Tag in Köln;
    `telefon`: Breite bis 900 px, `offen`: Weg über „Aktuell anzeigen“."""
    teil = "".join(_teil(APP, m) for m in (r"^  const esc = .*?;\n", r"^  const safeUrl = .*?;\n",
                                            r"^  const ISO_DAY = .*?;\n", r"^  const DATUM = .*?;\n",
                                            r"^  const fmtDate = .*?;\n"))
    teil += _teil(APP, r"^  const BERLIN_TAG = .*?\n  function aktuellHtml\(offen\) \{\n.*?\n  \}\n")
    code = f"""
const heute = () => {json.dumps(heute)};
const index = {json.dumps(index)}, zeit = {json.dumps(bool(zeit))}, MOBILE = {{ matches: {json.dumps(telefon)} }};
const QUELLE_NAME = {{}};
""" + teil + f"""
const l = aktuellListen();
console.log(JSON.stringify({{ hinweis: standHinweis(), html: aktuellHtml({json.dumps(offen)}), listen: l }}));
"""
    return _node(code)


SITZUNG = {"time": "17:00", "web": "https://example.invalid/sitzung", "source_object": "https://example.invalid/oparl/meetings/x"}
AKTUELL = {
    "sitzungen": [
        {**SITZUNG, "date": "2026-11-19", "gremium": "Beispielausschuss Vortag"},
        {**SITZUNG, "date": "2026-11-20", "gremium": "Beispielausschuss heute"},
        {**SITZUNG, "date": "2026-11-21", "gremium": "Beispielbeirat abgesagt", "cancelled": True},
        {**SITZUNG, "date": "2026-11-22", "gremium": "Beispielbeirat laut Namen", "hinweis": "abgesagt"},
        {**SITZUNG, "date": "2026-11-23", "gremium": "Beispielbeirat verschoben", "hinweis": "verschoben", "web": None},
        {**SITZUNG, "date": "2026-11-24", "gremium": "unbekannt", "time": None},
        {**SITZUNG, "date": "2026-11-25", "gremium": "Beispielausschuss vierte"},
    ],
    "vorlagen": [
        {"reference": "9001/2026", "date": "2026-11-18", "paper_type": "Mitteilung", "name": "[Test] Beispielweg Bänke",
         "area": "ortsteil:probedorf", "ort": "Probedorf", "source_object": "https://example.invalid/oparl/papers/1"},
        {"reference": "AN/9002/2026", "date": "2026-11-17", "paper_type": None, "name": "[Test] Ohne Gebiet",
         "area": None, "ort": None, "source_object": "https://example.invalid/oparl/papers/2"},
    ],
}
META = {"sources": [{"name": "oparl-koeln", "retrieved_at": "2026-11-19T23:30:00+00:00"}]}


def test_startfenster_karten_aus_index_json():
    """„Aktuell in Köln“: „Kommende Sitzungen“ ohne vergangene (Tag in Köln), ohne abgesagte (OParl `cancelled` und
    Hinweis „abgesagt“ aus dem Namen), höchstens drei; „verschoben“ als kurzer Hinweis ohne Sitzungsnamen; ein fehlendes
    Gremium in Worten; „Neu eingereicht“ öffnet die Vorlage über ihr Gebiet, ohne Gebiet nur als Text, ohne Ort ohne
    Chip; Stand der Daten nach dem Kölner Tag des Abrufs."""
    aus = _start({"meta": META, "aktuell": AKTUELL})
    html, l = aus["html"], aus["listen"]
    assert [m["gremium"] for m in l["sitzungen"]] == ["Beispielausschuss heute", "Beispielbeirat verschoben", "unbekannt"]
    for weg in ("Vortag", "Beispielbeirat abgesagt", "laut Namen", "vierte"):
        assert weg not in html, weg
    assert html.count('class="akt-sitzung"') == 3 and "heute, 17:00 Uhr" in html
    assert '<span class="akt-chip">laut Sitzungsnamen verschoben</span>' in html
    assert "Gremium unbekannt" in html and ">unbekannt<" not in html
    assert "Tagesordnung noch nicht veröffentlicht" in html   # Sitzung ohne web, kein „folgt“
    assert '<summary>Aktuell in Köln <span class="akt-stand">Stand der Daten: 20.11.2026</span></summary>' in html   # 23:30 UTC ist in Köln schon der nächste Tag
    assert html.startswith('<details class="aktuell" id="aktuell" open>')
    assert html.count("data-open-ref=") == 1
    assert '<button type="button" class="akt-open" data-open-ref="9001/2026" data-area="ortsteil:probedorf">' in html
    assert '<div class="akt-open"><span class="akt-title akt-clamp">[Test] Ohne Gebiet</span>' in html
    assert html.count("akt-chip-ort") == 1 and ">Vorlage<" in html   # ohne Art: „Vorlage“
    assert "Alle kommenden Sitzungen" in html and 'data-open-termine' in html
    assert aus["hinweis"] == ""
    # ohne zeit.json kein Link auf die Termine
    assert "data-open-termine" not in _start({"meta": META, "aktuell": AKTUELL}, zeit=False)["html"]


def test_startfenster_auf_dem_telefon_eingeklappt():
    """Auf dem Telefon ist „Aktuell in Köln“ eingeklappt (wie im Ratsatlas Bonn; aufgeklappt reichte das Startfenster
    über die Schaltfläche „Karte“), außer beim Weg über „Aktuell anzeigen“; die Karten stehen trotzdem darin."""
    zu = _start({"meta": META, "aktuell": AKTUELL}, telefon=True)["html"]
    auf = _start({"meta": META, "aktuell": AKTUELL}, telefon=True, offen=True)["html"]
    assert zu.startswith('<details class="aktuell" id="aktuell"><summary>') and "Kommende Sitzungen" in zu
    assert auf.startswith('<details class="aktuell" id="aktuell" open><summary>')
    assert auf.replace(" open>", ">", 1) == zu


def test_startfenster_karte_fehlt_ohne_liste():
    """Eine Karte fehlt, wenn index.json ihre Liste nicht nennt (ausgesetzt oder nicht aktualisiert, pipeline/export.
    _aktuell) oder der Browser alle Sitzungen ausblendet; ohne Karte fehlt der ganze Block, ebenso ohne `aktuell`
    (Kartenvorschau)."""
    nur_vorlagen = _start({"meta": META, "aktuell": {"vorlagen": AKTUELL["vorlagen"]}})["html"]
    assert "Neu eingereicht" in nur_vorlagen and "Kommende Sitzungen" not in nur_vorlagen
    nur_sitzungen = _start({"meta": META, "aktuell": {"sitzungen": AKTUELL["sitzungen"]}})["html"]
    assert "Kommende Sitzungen" in nur_sitzungen and "Neu eingereicht" not in nur_sitzungen
    vorbei = _start({"meta": META, "aktuell": {"sitzungen": AKTUELL["sitzungen"]}}, heute="2026-11-26")
    assert vorbei["html"] == "" and vorbei["listen"] is None
    assert _start({"meta": {**META, "vorschau": True}})["html"] == ""
    assert _start({"meta": META, "aktuell": {"sitzungen": [], "vorlagen": []}})["html"] == ""


def test_startfenster_hinweis_bei_nicht_aktuellen_daten():
    """Sind die Daten nicht aktuell (index.json meta.abruf_fehler, abruf_warnungen, abruf_ausgesetzt), steht im
    Startfenster ein Hinweis mit denselben Sätzen wie im Datenstand; sonst keiner."""
    fehler = _start({"meta": {**META, "abruf_fehler": {"zeit": "2026-11-19T22:40:00+00:00"}}})["hinweis"]
    assert fehler.startswith('<p class="stand-hinweis"><strong>Hinweis zum Datenstand:</strong> Der letzte Abruf am 19.11.2026 ist fehlgeschlagen')
    warnung = _start({"meta": {**META, "abruf_warnungen": {"meetings": {"stand": "2026-11-17T23:00:00+00:00"}}}})["hinweis"]
    assert "Sitzungstermine wurden beim letzten Abruf nicht aktualisiert; gezeigt wird der Stand vom 18.11.2026." in warnung
    ruht = _start({"meta": {**META, "abruf_ausgesetzt": {"papers": {"seit": "2026-11-15T22:30:00+00:00", "stand": None}}}})["hinweis"]
    assert "Der Abruf der Vorlagen ruht seit dem 15.11.2026" in ruht and " · " not in ruht
    beide = _start({"meta": {**META, "abruf_fehler": {"zeit": "2026-11-19T22:40:00+00:00"},
                             "abruf_ausgesetzt": {"meetings": {"seit": None, "stand": None}}}})["hinweis"]
    assert "fehlgeschlagen" in beide and "Sitzungstermine ruht derzeit" in beide
    for leer in ({}, {"abruf_fehler": None, "abruf_warnungen": {}}):
        assert _start({"meta": {**META, **leer}, "aktuell": AKTUELL})["hinweis"] == ""


# --- 4 Hinweise zum Stand aus dem Sitzungsnamen ---------------------------------------------------------------------------

def _termine(meetings, heute="2026-11-20"):
    """showTermine aus app.js mit erfundenen Sitzungen (zeit.json) und nachgebildetem Element #termine."""
    teil = "".join(_teil(APP, m) for m in (r"^  const esc = .*?;\n", r"^  const safeUrl = .*?;\n",
                                            r"^  const gremiumText = .*?;\n", r"^  const link = .*?;\n"))
    teil += _teil(APP, r"^  const BV_NUMMER = .*?\n  function showTermine\(\) \{\n.*?\n  \}\n")
    code = f"""
const heute = () => {json.dumps(heute)};
const zeit = {{ meetings: {json.dumps(meetings)} }}, papers = [], index = null, BONN = "data/export/koeln/";
let area = {{ kind: "koeln", key: "alle", name: "ganz Köln" }};
const box = {{ innerHTML: "", querySelector: (s) => (s === "#termine-scope" && box.innerHTML ? {{ value: "gebiet", addEventListener() {{}} }} : null) }};
const $ = (s) => (s === "#termine" ? box : null);
""" + teil + """
showTermine();
console.log(JSON.stringify(box.innerHTML));
"""
    return _node(code)


def test_kommende_sitzungen_mit_hinweis_aus_dem_namen():
    """„Kommende Sitzungen“: Plakette „laut Sitzungsnamen abgesagt“ neben der für OParl `cancelled` („abgesagt“), beide
    durchgestrichen; bei „verschoben“ die Plakette und der Sitzungsname (nach der Maske, aus zeit.json) neben dem
    Gremium; ohne Hinweis kein Name; ein fehlendes Gremium in Worten."""
    html = _termine([
        {"date": "2026-11-19", "time": "17:00", "gremium": "Beispielrat Vortag", "name": "Beispielrat Vortag"},
        {"date": "2026-11-21", "time": "17:00", "gremium": "Beispielrat A", "name": "Beispielrat A", "cancelled": True},
        {"date": "2026-11-22", "time": "17:00", "gremium": "Beispielrat B", "name": "Beispielrat B - Sitzung entfällt",
         "hinweis": "abgesagt"},
        {"date": "2026-11-23", "time": None, "gremium": "Beispielrat C",
         "name": "Beispielrat C\n-Sitzung ist auf den 30. November verschoben worden!-", "hinweis": "verschoben"},
        {"date": "2026-11-24", "time": "16:00", "gremium": "Beispielrat D", "name": "Beispielrat D Sondersitzung"},
        {"date": "2026-11-25", "time": "16:00", "gremium": "unbekannt", "name": ""},
    ])
    sitzungen = re.findall(r'<div class="meeting( cancelled)?">\s*<div class="meeting-head">(.*?)</div>', html, re.S)
    assert len(sitzungen) == 5 and "Vortag" not in html
    kopf = {re.search(r"<strong>(.*?)</strong>", k).group(1): (bool(c), k) for c, k in sitzungen}
    assert kopf["Beispielrat A"][0] and '<span class="badge">abgesagt</span>' in kopf["Beispielrat A"][1]
    assert kopf["Beispielrat B"][0] and '<span class="badge">laut Sitzungsnamen abgesagt</span>' in kopf["Beispielrat B"][1]
    assert "entfällt" not in html   # bei „abgesagt“ kein Name
    c = kopf["Beispielrat C"]
    assert not c[0] and '<span class="badge">laut Sitzungsnamen verschoben</span>' in c[1]
    assert '<span class="meeting-name">Sitzungsname: „Beispielrat C\n-Sitzung ist auf den 30. November verschoben worden!-“</span>' in c[1]
    assert "badge" not in kopf["Beispielrat D"][1] and "Sondersitzung" not in html
    assert "Gremium unbekannt" in kopf and ">unbekannt<" not in html


def test_naechste_sitzung_ohne_absage_im_namen():
    """Eine Sitzung mit Hinweis „abgesagt“ gilt nie als nächste Sitzung: participate (Vorgang), naechste in
    site/beteiligung.js und „Aktuell in Köln“ (test_startfenster_karten_aus_index_json); „verschoben“ zählt."""
    teil = _teil(APP, r"^  function participate\(p\) \{\n.*?\n  \}\n")
    assert 'zeit.meetings.find((m) => m.date >= today && !m.cancelled && m.hinweis !== "abgesagt" && gremien.has(m.gremium))' in teil
    sitzungen = [{"date": "2026-11-21", "time": "17:00", "gremium": "Beispielrat", "cancelled": True},
                 {"date": "2026-11-22", "time": "17:00", "gremium": "Beispielrat", "hinweis": "abgesagt"},
                 {"date": "2026-11-23", "time": "17:00", "gremium": "Beispielrat", "hinweis": "verschoben"},
                 {"date": "2026-11-20", "time": "17:00", "gremium": "Anderer Rat"}]
    aus = _node(f"""
import {{ naechste }} from "{BETEILIGUNG.as_uri()}";
const S = {json.dumps(sitzungen)};
console.log(JSON.stringify([naechste(S, "2026-11-20", (g) => g === "Beispielrat"), naechste(S.slice(0, 2), "2026-11-20", (g) => g === "Beispielrat")]));
""", modul=True)
    assert aus == [sitzungen[2], None]


def test_vorgang_nennt_verschoben_bei_der_naechsten_sitzung():
    """Prüfung von Pull Request 3: Ist die nächste Sitzung eines beteiligten Gremiums laut Namen verschoben, sagt der
    Vorgang das kurz wie „Aktuell in Köln“ (ohne Namen) und lässt den Satz „Sie können zuhören“ weg."""
    teil = "".join(_teil(APP, m) for m in (r"^  const esc = .*?;\n", r"^  const safeUrl = .*?;\n", r"^  const link = .*?;\n",
                                            r"^  const BUERGERANTRAG = .*?;\n", r"^  function participate\(p\) \{\n.*?\n  \}\n"))
    code = """
const heute = () => "2026-11-20", fmtDay = (d) => d, vorhanden = () => false, hasPaperFeed = () => false;
let zeit = null;
""" + teil + """
const p = { stand: "in Beratung", steps: [{ typ: "beratung", label: "Beispielrat", date: "2026-11-10" }] };
const aus = [];
for (const hinweis of ["verschoben", null]) {
  zeit = { meetings: [{ date: "2026-11-24", time: "17:00", gremium: "Beispielrat", web: null, ...(hinweis ? { hinweis } : {}) }] };
  aus.push(participate(p));
}
console.log(JSON.stringify(aus));
"""
    verschoben, normal = _node(code)
    assert '2026-11-24, 17:00 Uhr <span class="badge">laut Sitzungsnamen verschoben</span>.' in verschoben
    assert "Sie können zuhören" not in verschoben and "Sitzungsname:" not in verschoben
    assert "laut Sitzungsnamen" not in normal and "Die Sitzung ist in der Regel öffentlich; Sie können zuhören." in normal


def test_mitmachen_in_koeln_sagt_absage_statt_keine_sitzung():
    """Prüfung von Pull Request 3, site/beteiligung.js: Ist die einzige kommende Sitzung einer Bezirksvertretung laut
    Namen abgesagt, heißt es „keine kommende Sitzung ohne Absage“ statt „noch keine kommende Sitzung eingetragen“; eine
    verschobene steht mit dem kurzen Hinweis da."""
    bv = "Bezirksvertretung 3 (Beispiel)"
    def html(meetings, bz="Lindenthal"):
        return _node(f"""
import {{ inhalt }} from "{BETEILIGUNG.as_uri()}";
const bvBezirk = (g) => (g === {json.dumps(bv)} ? "Lindenthal" : null);
console.log(JSON.stringify(inhalt({json.dumps(bz)}, {{ termine: true, meetings: {json.dumps(meetings)}, heute: "2026-11-20", bvBezirk }})));
""", modul=True)
    abgesagt = html([{"date": "2026-11-27", "time": "17:00", "gremium": bv, "hinweis": "abgesagt", "web": None}])
    assert "Für die Bezirksvertretung Lindenthal ist im Sitzungskalender keine kommende Sitzung ohne Absage eingetragen." in abgesagt
    assert "Im Sitzungskalender ist keine kommende Sitzung ohne Absage eingetragen." in abgesagt
    leer = html([{"date": "2026-11-10", "time": "17:00", "gremium": bv, "web": None}])
    assert "Für die Bezirksvertretung Lindenthal ist im Sitzungskalender noch keine kommende Sitzung eingetragen." in leer
    assert "Im Sitzungskalender ist noch keine kommende Sitzung eingetragen." in leer and "ohne Absage" not in leer
    verschoben = html([{"date": "2026-11-27", "time": "17:00", "gremium": bv, "hinweis": "verschoben", "web": None}])
    assert f"{bv}; die Sitzung beginnt mit der Einwohnerfragestunde · laut Sitzungsnamen verschoben · Tagesordnung noch" in verschoben
    assert "ohne Absage" not in verschoben and "noch keine kommende Sitzung" not in verschoben


def test_themen_hinweis_je_auswahl():
    """Menü „Themen“ (fillThemen): ganz Köln ohne Zahl, ein Gebiet mit Zahl; „Vorlagen ohne Ortsbezug“ eines Jahres mit
    eigenem Satz (vorher: „… in Vorlagen ohne Ortsbezug 2026 …“, Prüfung von Pull Request 3)."""
    teil = "".join(_teil(APP, m) for m in (r"^  const esc = .*?;\n", r"^  const THEMES = \{.*?\n  \};\n",
                                            r"^  function fillThemen\(\) \{\n.*?\n  \}\n", r"^  function chip\(.*?\n  \}\n"))
    code = """
const STADT = "koeln", E = { "#f-theme": { value: "" }, "#themen-hinweis": { textContent: "" }, "#themen-chips": { innerHTML: "" } };
const $ = (s) => E[s];
const papers = [{ themes: [{ theme: "verkehr" }] }, { themes: [{ theme: "verkehr" }, { theme: "bauen" }] }];
let area = null;
""" + teil + """
const aus = [];
for (const a of [{ kind: "koeln", key: "alle", name: "ganz Köln" }, { kind: "ortsteil", key: "probedorf", name: "Probedorf" },
  { kind: "ohne", key: "2026", name: "ohne Ortsbezug 2026" }]) { area = a; fillThemen(); aus.push([E["#themen-hinweis"].textContent, E["#themen-chips"].innerHTML]); }
console.log(JSON.stringify(aus));
"""
    koeln, gebiet, ohne = _node(code)
    assert koeln[0].startswith("Ein Thema zeigt die passenden Vorlagen in ganz Köln in der Liste;") and 'class="n"' not in koeln[1]
    assert gebiet[0] == ("Ein Thema zeigt die passenden Vorlagen in Probedorf in der Liste. Die Zahl nennt die Vorlagen mit "
                         "diesem Thema im Gebiet; die Themen sind abgeleitet.")
    assert ohne[0] == ("Ein Thema zeigt die passenden Vorlagen ohne Ortsbezug aus 2026 in der Liste. Die Zahl nennt die Vorlagen "
                       "mit diesem Thema in dieser Auswahl; die Themen sind abgeleitet.")
    assert 'data-thema="verkehr">Verkehr und Mobilität <span class="n">2</span>' in ohne[1]


def test_zeitleiste_nennt_absage_aus_dem_namen():
    """site/timeline.js: Eine Sitzung mit Hinweis „abgesagt“ aus dem Namen sieht aus wie eine abgesagte (Klasse
    „cancelled“, gestrichelt) und heißt im Titel des Punkts „laut Sitzungsnamen abgesagt“, künftig und seit Pull Request
    4b auch vergangen (#47 (3); vorher blieben vergangene ohne Zusatz); bei „verschoben“ heißt eine künftige „laut
    Sitzungsnamen verschoben“ statt „geplant“ (Prüfung von Pull Request 3), eine vergangene bleibt ohne Zusatz."""
    tl = (ROOT / "site" / "timeline.js").read_text(encoding="utf-8")
    teil = _teil(tl, r"^        const kuenftig = ms > today.*?\n        el\(\"title\".*?;\n")
    code = """
const punkte = [];
const el = (tag, attr, eltern) => { const e = { tag, attr, textContent: "" }; (eltern === "svg" ? punkte : []).push(e);
  if (eltern && eltern.tag) eltern.titel = e; return e; };
const svg = "svg", x = (v) => v, y = 1, de = (ms) => new Date(ms).toISOString().slice(0, 10), today = Date.parse("2026-11-20T12:00:00Z");
const S = [{ date: "2026-11-22", gremium: "Beispielrat", hinweis: "abgesagt" }, { date: "2026-11-23", gremium: "Beispielrat", hinweis: "verschoben" },
  { date: "2026-11-24", gremium: "Beispielrat", cancelled: true }, { date: "2026-11-25", gremium: "Beispielrat" },
  { date: "2026-11-10", gremium: "Beispielrat", hinweis: "abgesagt" }, { date: "2026-11-09", gremium: "Beispielrat", hinweis: "verschoben" },
  { date: "2026-11-08", gremium: "Beispielrat" }];
for (const m of S) { const ms = Date.parse(m.date + "T00:00:00Z");
""" + teil + """
}
console.log(JSON.stringify(punkte.map((p) => [p.attr.class, p.titel.textContent])));
"""
    assert _node(code) == [["tl-meet future cancelled", "2026-11-22 · Beispielrat · laut Sitzungsnamen abgesagt"],
                           ["tl-meet future", "2026-11-23 · Beispielrat · laut Sitzungsnamen verschoben"],
                           ["tl-meet future cancelled", "2026-11-24 · Beispielrat · abgesagt"],
                           ["tl-meet future", "2026-11-25 · Beispielrat · geplant"],
                           ["tl-meet cancelled", "2026-11-10 · Beispielrat · laut Sitzungsnamen abgesagt"],
                           ["tl-meet", "2026-11-09 · Beispielrat"],
                           ["tl-meet", "2026-11-08 · Beispielrat"]]


# --- 5 Wege zurück und Fokus -----------------------------------------------------------------------------------------------

def test_rueckziel_fuer_den_fokus():
    """rueckZiel: das auslösende Element, wenn es zu sehen ist; liegt es in einem geschlossenen Menü, dessen Schaltfläche
    in der Leiste; ist auch die verborgen (Telefon, Menüs hinter ☰), die Schaltfläche „Menü“; ohne Element die
    Schaltfläche des genannten Menüs."""
    teil = _teil(APP, r"^  const sichtbarEl = .*?\);\n") + _teil(APP, r"^  function rueckZiel\(el, mega\) \{\n.*?\n  \}\n")
    code = """
const el = (name, sichtbar, mega, flaeche) => ({ name, isConnected: true, getClientRects: () => (sichtbar.an ? [1] : []),
  closest: (sel) => (sel === ".mega" && mega ? { id: mega } : sel === "[hidden]" && flaeche ? flaeche : null), flaeche });
// geschlossene Fläche (.panel[hidden]): Layout bleibt (getClientRects nicht leer), nur visibility: hidden
const getComputedStyle = (e) => ({ visibility: e.flaeche ? "hidden" : "visible" });
const leiste = { an: true }, telefon = { an: false };
const knopf = el("knopf", leiste), burger = el("burger", telefon);
const document = { querySelector: (sel) => (sel === '[data-mega="mega-themen"]' ? knopf : null),
  getElementById: (id) => (id === "mega-themen" ? { id } : null) };
""" + teil + """
const aus = [];
aus.push(rueckZiel(el("karte", { an: true }, "mega-themen")).name);
aus.push(rueckZiel(el("karte", { an: false }, "mega-themen")).name);
aus.push(rueckZiel(undefined, "mega-themen").name);
leiste.an = false; telefon.an = true;
aus.push(rueckZiel(el("karte", { an: false }, "mega-themen")).name);
telefon.an = false;
aus.push(rueckZiel(el("karte", { an: false }, "mega-themen")));
// in einer geschlossenen Fläche (Telefon: „Los geht's“ unter „Kommende Sitzungen“): nicht zu sehen, Ersatz greift
telefon.an = true;
aus.push(rueckZiel(el("knopf in der Fläche", { an: true }, null, { hidden: true }), "mega-mitmachen").name);
console.log(JSON.stringify(aus));
"""
    assert _node(code) == ["karte", "knopf", "knopf", "burger", None, "burger"]


def test_wege_zurueck_und_schliessen():
    """„Zurück zu Köln“ in Liste und Startfenster eines Gebiets, „Zurück zur Liste“ im Vorgang; closePanel gibt den
    Fokus über rueckZiel zurück („In Zahlen“ zu „Themen“ oder „Wer entscheidet“ je Reiter); die Fenster „Über“ und „Was
    ist neu?“ ebenso; Escape schließt Menüs und Flächen; Wortmarke, Seitentitel und „Aktuell anzeigen“ führen zu „Los
    geht's“."""
    assert '<button type="button" class="link-btn" data-zurueck-koeln><span aria-hidden="true">← </span>Zurück zu Köln</button>' in INDEX
    assert _teil(APP, r"^  const INTRO = \(offen\) => `.*?`;\n").count("area && area.kind !== STADT ? ZURUECK_KOELN") == 1
    assert '$("#zurueck-koeln").hidden = !area || area.kind === STADT;' in APP
    assert "data-zurueck-liste><span aria-hidden=\"true\">← </span>Zurück zur Liste</button>" in APP
    schliessen = _teil(APP, r"^  function closePanel\(id\) \{\n.*?\n  \}\n")
    assert '"panel-auswertung": $("#stats").hidden ? "mega-entscheiden" : "mega-themen"' in schliessen
    assert "const back = sichtbarEl(t) ? t : rueckZiel(o, mega);" in schliessen
    assert 'rueckZiel(dialogOpener, "mega-ueber")' in APP
    esc = _teil(APP, r'^  document\.addEventListener\("keydown", \(e\) => \{\n    if \(e\.key !== "Escape".*?\n  \}\);\n')
    assert "if (openMegaId) return closeMega(true);" in esc and "if (overlay) return closePanel(overlay);" in esc
    assert INDEX.count(" data-home aria-label=") == 2 and 'data-home="aktuell"' in INDEX
    home = _teil(APP, r"^  function goHome\(zuAktuell\) \{\n.*?\n  \}\n")
    for teil in ("closeMega();", "setNav(false);", "selected = null;", "showIntro(zuAktuell);", 'setPanel("panel-detail", true);'):
        assert teil in home, teil


def _schliessen(telefon, flaeche_des_ausloesers):
    """closePanel aus app.js mit nachgebildeten Flächen: „Kommende Sitzungen“ (Überlagerung) war aus einer Schaltfläche
    in `flaeche_des_ausloesers` geöffnet; auf dem Telefon ist dabei jede andere Fläche zugegangen."""
    teil = _teil(APP, r"^  const sichtbarEl = .*?\);\n") + _teil(APP, r"^  function rueckZiel\(el, mega\) \{\n.*?\n  \}\n") \
        + _teil(APP, r"^  function closePanel\(id\) \{\n.*?\n  \}\n")
    code = f"""
const MOBILE = {{ matches: {json.dumps(telefon)} }};
const SHEETS = ["panel-list", "panel-detail", "panel-auswertung", "panel-termine", "panel-mitmachen", "timeline-wrap"];
const OVERLAYS = ["panel-auswertung", "panel-termine", "panel-mitmachen"];
const P = Object.fromEntries(SHEETS.map((id) => [id, {{ id, hidden: true, contains: (e) => e.flaeche === id }}]));
const document = {{ activeElement: null, getElementById: (id) => P[id] || null, querySelector: () => null }};
const knopf = (name, flaeche, sichtbar = true) => ({{ name, flaeche, isConnected: true,
  getClientRects: () => (sichtbar ? [1] : []), closest: (sel) => (sel === "[hidden]" && flaeche && P[flaeche].hidden ? P[flaeche] : null),
  focus() {{ if (sichtbarEl(this)) document.activeElement = this; }} }});
const getComputedStyle = (e) => ({{ visibility: e.flaeche && P[e.flaeche].hidden ? "hidden" : "visible" }});
const burger = knopf("Menü", null, MOBILE.matches);
const $ = (s) => (s === "#stats" ? {{ hidden: true }} : null);
const toggleFor = () => null;
const aufrufe = [];
function setPanel(id, open) {{ aufrufe.push([id, open]); P[id].hidden = !open;
  if (open && MOBILE.matches) for (const s of SHEETS) if (s !== id) P[s].hidden = true; }}
const ausloeser = knopf("Auslöser", {json.dumps(flaeche_des_ausloesers)});
const opener = {{ "panel-termine": ausloeser, "panel-detail": "vorher" }};
P[{json.dumps(flaeche_des_ausloesers)}].hidden = !!MOBILE.matches;   // Telefon: beim Öffnen zugegangen
P["panel-termine"].hidden = false;
""" + teil + """
closePanel("panel-termine");
console.log(JSON.stringify({ fokus: document.activeElement && document.activeElement.name, aufrufe,
  offen: SHEETS.filter((s) => !P[s].hidden), opener: opener["panel-detail"] }));
"""
    return _node(code)


def test_schliessen_gibt_den_fokus_auch_auf_dem_telefon_zurueck():
    """Prüfung von Pull Request 3: Auf dem Telefon schließt das Öffnen von „Kommende Sitzungen“ die Fläche, aus der es
    kam (etwa „Los geht's“ mit „Alle kommenden Sitzungen“ oder der Vorgang). Beim Schließen geht diese Fläche wieder auf
    und der Fokus auf den Auslöser (vorher lag er auf <body>, weil die geschlossene Fläche nur visibility: hidden ist).
    Kam der Auslöser aus einer Überlagerung („Mitmachen in Köln“ baut sich beim Öffnen neu auf), geht der Fokus auf
    „Menü“. Auf breiten Bildschirmen bleibt alles, wie es ist."""
    tel = _schliessen(True, "panel-detail")
    assert tel["fokus"] == "Auslöser" and tel["offen"] == ["panel-detail"] and tel["opener"] == "vorher"
    assert tel["aufrufe"] == [["panel-termine", False], ["panel-detail", True]]
    aus_ueberlagerung = _schliessen(True, "panel-mitmachen")
    assert aus_ueberlagerung["fokus"] == "Menü" and aus_ueberlagerung["offen"] == []
    breit = _schliessen(False, "panel-detail")
    assert breit["fokus"] == "Auslöser" and breit["aufrufe"] == [["panel-termine", False]] and breit["offen"] == ["panel-detail"]


# --- 6 Vorgang ------------------------------------------------------------------------------------------------------------

def test_leerer_ortsname_fester_text():
    """Entscheidung 20.11.2026 (1) (c): Eine Ortsangabe der Stadt ohne Straße, Beschreibung und Kölner Stadtteil heißt im
    Vorgang „Ortsangabe der Stadt ohne Kölner Stadtteil“ statt einer leeren Zeile; andere Namen bleiben."""
    teil = _teil(APP, r"^  const ORT_OHNE_STADTTEIL = .*?;\n") + _teil(APP, r"^  const ortName = .*?;\n")
    orte = [{"name": None, "ortsteil": None, "stadtbezirk": None, "method": "oparl_location"},
            {"name": "", "ortsteil": None, "stadtbezirk": None, "method": "oparl_sublocality"},
            {"name": "  ", "ortsteil": None, "stadtbezirk": None, "method": "oparl_location"},
            {"name": "Beispielweg", "ortsteil": "Probedorf", "stadtbezirk": "Musterbezirk", "method": "oparl_location"},
            {"name": None, "ortsteil": "Probedorf", "stadtbezirk": "Musterbezirk", "method": "oparl_sublocality"},
            {"name": None, "ortsteil": None, "stadtbezirk": "Musterbezirk", "method": "district_from_committee"},
            {"name": None, "ortsteil": None, "stadtbezirk": None, "method": "strasse"}]
    aus = _node(teil + f"console.log(JSON.stringify({json.dumps(orte)}.map(ortName)));")
    fest = "Ortsangabe der Stadt ohne Kölner Stadtteil"
    assert aus == [fest, fest, fest, "Beispielweg", "Probedorf", "Musterbezirk", ""]
    sel = _teil(APP, r"^  function select\(p, fromMap\) \{\n.*?\n  \}\n")
    assert "const n = ortName(l); return `<li>${n ? `<strong>${esc(n)}</strong>" in sel
    assert "l.name || l.ortsteil || l.stadtbezirk)" not in sel


def _schritte(faelle, da=True, soll=False):
    """stepHtml aus app.js mit erfundenen Schritten; `da`: Freigabe „gremien“ zur Laufzeit und Fläche vorhanden
    (werDa), `soll`: Bonner Freigabe „soll“."""
    teil = _teil(APP, r"^  const STATUS = \{.*?\n  \};\n") + _teil(APP, r"^  const esc = .*?;\n") \
        + _teil(APP, r"^  function stepHtml\(s\) \{\n.*?\n  \}\n")
    code = f"""
const index = {{}}, NOTES = {{}}, STEP_LABEL = {{ beratung: "Beratung", entscheidung: "Entscheidung", initiierung: "Eingereicht" }};
const fmtDate = (d) => d, werDa = () => {json.dumps(da)};
let funktionen = {json.dumps({"soll": soll})};
""" + teil + f"""
console.log(JSON.stringify({json.dumps(faelle)}.map(stepHtml)));
"""
    return _node(code)


def test_gremium_im_vorgang_link_nur_mit_kennung():
    """Entscheidungen 19.11.2026 (1) (H), 21.11.2026 (2) (F12) und 23.11.2026 (1) (E1): Der Name eines Gremiums im
    Vorgang ist ein Link in den Reiter „Gremien“ nur mit der Kennung am Schritt (gremium_key aus der Station), mit
    Freigabe „gremien“ zur Laufzeit und vorhandener Fläche (werDa); ohne Kennung (frühere Wahlperiode, Gremium aus dem
    Sitzungsnamen, „Gremium unbekannt“) und ohne Freigabe Text. Der Bonner Link in den Reiter „Prozesse“ über den Namen
    bleibt unter „soll“ (in Köln aus) und gilt nur ohne Kennung."""
    s = {"typ": "beratung", "label": "Beispielausschuss", "status": "belegt", "date": "2026-11-20", "role": "Vorberatung"}
    mit, ohne, entscheidung, leer, initiierung = _schritte([
        {**s, "gremium_key": "beispielausschuss"}, s, {**s, "typ": "entscheidung", "gremium_key": "rat", "label": "Rat"},
        {**s, "label": None, "gremium_key": "x"}, {"typ": "initiierung", "label": "Antrag", "status": "belegt", "gremium_key": "x"}])
    assert 'Beratung: <button type="button" class="link-btn" data-gremium-key="beispielausschuss">Beispielausschuss</button>' in mit
    assert "data-gremium" not in ohne and "Beratung: Beispielausschuss<span" in ohne
    assert 'data-gremium-key="rat">Rat</button>' in entscheidung
    assert "data-gremium" not in leer and "Beratung<span" in leer   # ohne Gremium: nur die Art der Station
    assert "data-gremium" not in initiierung
    aus = _schritte([{**s, "gremium_key": "beispielausschuss"}], da=False)[0]
    assert "data-gremium" not in aus and "Beratung: Beispielausschuss<span" in aus
    bonn = _schritte([s, {**s, "gremium_key": "beispielausschuss"}], da=False, soll=True)
    assert 'data-gremium-name="Beispielausschuss"' in bonn[0] and 'data-gremium-name="Beispielausschuss"' in bonn[1]
    assert 'data-gremium-key="beispielausschuss"' in _schritte([{**s, "gremium_key": "beispielausschuss"}], soll=True)[0]
    assert config.ZUSATZTHEMEN["soll"] is False and config.ZUSATZTHEMEN["gremien"] is True
    klick = _teil(APP, r'^  \$\("#detail"\)\.addEventListener\("click", \(e\) => \{\n.*?\n  \}\);\n')
    # das öffnende Element gilt auch bei schon offener Fläche (Esc führt zum zuletzt gewählten Link; Nachprüfung Bedienung)
    assert ('if (werDa()) { setPanel("panel-gremien", true); opener["panel-gremien"] = gk; focusPanel("panel-gremien"); '
            'openGremien({ tab: "gremien", kennung: gk.dataset.gremiumKey, fokus: true }); }') in klick


def test_plakette_an_der_station():
    """F10 und (10) aus 21.11.2026 (1) (c), E1: Trägt der Schritt den Hinweis aus dem Sitzungsnamen (hinweis, aus der
    Station), steht im Kopf die Plakette „laut Sitzungsnamen abgesagt“ bzw. „… verschoben“; Stand, Evidenzstatus und
    Ergebnis bleiben unverändert, ohne Hinweis keine Plakette. Nach der Plakette ein Leerzeichen vor dem Status
    (Umbruchstelle und Vorlesen; Nachprüfung Bedienung)."""
    s = {"typ": "beratung", "label": "Beispielrat", "status": "belegt", "date": "2026-11-20", "role": "Beratung",
         "result": "vertagt", "gremium_key": "beispielrat"}
    abgesagt, verschoben, ohne, anders = _schritte([{**s, "hinweis": "abgesagt"}, {**s, "hinweis": "verschoben"}, s,
                                                    {**s, "hinweis": "anders"}])
    assert '</button> <span class="badge">laut Sitzungsnamen abgesagt</span> <span class="step-status">belegt</span>' in abgesagt
    assert '<span class="badge">laut Sitzungsnamen verschoben</span> <span class="step-status">belegt</span>' in verschoben
    assert '</button><span class="step-status">belegt</span>' in ohne   # ohne Plakette unverändert
    for html in (ohne, anders):
        assert "badge" not in html
    for html in (abgesagt, verschoben, ohne):
        assert "Ergebnis: <q>vertagt</q>" in html and 'data-status="belegt"' in html


# --- 7 Kleineres -------------------------------------------------------------------------------------------------------------

def test_wortmarke_und_seitentitel():
    """Die Wortmarke ist ein Link zu „Los geht's“ und behält zwischen 901 und 1100 px ihren Namen („Köln“ nur für
    Bildschirmleser statt display: none); der Seitentitel ist bis 900 px ein sichtbarer Link (mit der Tastatur
    erreichbar), auf breiten Bildschirmen nur Text für Bildschirmleser ohne Link."""
    name = 'aria-label="Ratsatlas Köln: zu „Los geht\'s“"'
    brand = re.search(rf'<a class="brand" href="\./" data-home {name}>(.*?)</a>', INDEX).group(1)
    assert _text(brand) == "Ratsatlas Köln" and '<span class="ort">Köln</span>' in brand and "aria-hidden" not in brand
    schmal = _teil(CSS, r"^@media \(min-width: 901px\) and \(max-width: 1100px\) \{\n.*?\n\}\n")
    assert ".brand .ort { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);" in schmal
    assert "display: none" not in schmal.split(".nav-area")[0]
    titel = re.search(r'<h1 class="site-title">(.*?)</h1>', INDEX).group(1)
    assert titel.startswith(f'<span class="titel-text">Ratsatlas Köln</span><a class="titel-link" href="./" data-home {name}>')
    assert ".site-title .titel-link { display: none; }" in CSS
    telefon = _teil(CSS, r"^@media \(max-width: 900px\) \{\n  :root \{ --nav-h: 0px; \}.*?\n\}\n")
    assert ".site-title .titel-text { display: none; }" in telefon
    assert ".site-title .titel-link { display: inline-flex;" in telefon


def test_neu_eingereicht_oeffnet_ueber_open_global():
    """„Neu eingereicht“: Vorlage mit Gebiet über openGlobal (Gebiet laden, Vorgang öffnen, wie ein Suchtreffer; ohne
    Suchindex), danach Fokus auf den Titel des Vorgangs."""
    klick = _teil(APP, r'^  \$\("#detail"\)\.addEventListener\("click", \(e\) => \{\n.*?\n  \}\);\n')
    assert 'if (ref && ref.dataset.area) { openGlobal(ref.dataset.openRef, ref.dataset.area).then(() => $("#detail h3")?.focus()); return; }' in klick


def test_keine_bonner_reste_im_koelner_quelltext():
    """Entscheidung 19.11.2026 (1) (H): keine Beispielfragen des Assistenten mit Bonner Straße und Drucksachennummer;
    keine Bonner Orte in index.html."""
    for wort in ("Endenich", "261798", "Godesberg", "Beuel", "Hardtberg", "bonn.de", "Poppelsdorf"):
        assert wort not in INDEX, wort
    beispiele = _abschnitt(INDEX, "chat-examples")
    assert beispiele.count('class="chip"') == 2


# --- 8 Kartenvorschau --------------------------------------------------------------------------------------------------------

def test_kartenvorschau():
    """Vorschau ohne Ratsvorlagen (index.json meta.vorschau, ohne `aktuell`): „Themen“, „Wer entscheidet“ und „Kommende
    Sitzungen“ tragen data-vorschau="aus" (app.js applyFunktionen blendet sie aus); „Aktuell in Köln“ fehlt
    (test_startfenster_karte_fehlt_ohne_liste); die Kachel im Menü „Mitmachen“ erscheint nur mit Karten."""
    for menue in ("mega-themen", "mega-entscheiden"):
        knopf = re.search(rf'<button type="button" class="menu-btn" data-mega="{menue}"[^>]*>', INDEX).group(0)
        assert 'data-vorschau="aus"' in knopf, menue
    mitmachen = _abschnitt(INDEX, "mega-mitmachen")
    assert '<div class="card static" data-vorschau="aus">\n          <span class="card-icon"><svg class="icon" aria-hidden="true"><use href="#i-calendar"/>' in mitmachen
    assert '<div class="card static" id="karte-aktuell" hidden>' in mitmachen
    assert '$("#karte-aktuell").hidden = !l;' in APP
    assert 'data-vorschau="nur"' not in mitmachen
    assert ".card[hidden] { display: none; }" in CSS
    # Telefon: Der Hinweis „Vorschau“ (wie „Testdaten“, z-index 3000) lag über „Mitmachen“ und „Über“ im Blatt ☰; solange
    # das Blatt offen ist, tritt er zurück (Prüfung im Browser: tests/browser/navigation.js, Kartenvorschau)
    telefon = re.findall(r"^@media \(max-width: 900px\) \{\n  \.testdaten \{.*?\n\}\n", CSS, re.S | re.M)
    assert len(telefon) == 1 and "  body.nav-open .testdaten { display: none; }\n" in telefon[0]
