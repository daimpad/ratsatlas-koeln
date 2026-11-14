"""Runde 18 (Seite): aria-current der Listeneinträge, Themen-Chips bei „ganz Köln“, Tourtexte nach den Freigaben,
Hinweis zu Baustellen in der Zeitleiste, Dateigrößen im Menü „Daten“. Die Prüfung im Browser (Playwright, axe) steht in
tests/browser/bedienung.js; hier die Teile, die ohne Browser laufen (node mit nachgebildetem Dokument, Python). Keine
Anfragen an Server der Stadt."""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import build, config, ebenen, export, kontext, paket, sessionnet

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
TOUR = (ROOT / "site" / "tour.js").read_text(encoding="utf-8")


def _node(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _modul(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _teil(quelle, muster):
    m = re.search(muster, quelle, re.S | re.M)
    assert m, muster
    return m.group(0)


# --- B1: aria-current immer "true" oder "false", auch an den Suchtreffern in ganz Köln (data-gref) ------------------

def test_aria_current_der_liste_true_oder_false():
    """markCurrent setzt aria-current an allen Einträgen der Liste, im Gebiet (data-ref) und in der Suche über ganz
    Köln (data-gref): genau die gewählte Vorlage "true", sonst "false"; ohne Auswahl alle "false". Bis Runde 18 blieben
    die Suchtreffer bei der Auswahl unverändert und trugen ohne Auswahl "null"."""
    teil = _teil(APP, r"^  const markCurrent = .*?;\n")
    code = """
const knoepfe = [{ ref: "1/2026" }, { gref: "2/2026" }, { gref: "AN/0003/2026" }].map((d) => ({ dataset: d, attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; } }));
// Auswahl nur nach den Attributen im Selektor (".papers button[data-ref], .papers button[data-gref]")
const document = { querySelectorAll(sel) {
  const arten = sel.split(",").map((s) => s.trim().match(/^\\.papers button\\[data-(\\w+)\\]$/)[1]);
  return knoepfe.filter((b) => arten.some((a) => a in b.dataset));
} };
""" + teil + """
const werte = () => knoepfe.map((b) => b.attrs["aria-current"]);
const aus = [];
markCurrent(null); aus.push(werte());
markCurrent("AN/0003/2026"); aus.push(werte());
markCurrent("1/2026"); aus.push(werte());
markCurrent(undefined); aus.push(werte());
console.log(JSON.stringify(aus));
"""
    assert _node(code) == [["false", "false", "false"], ["false", "false", "true"], ["true", "false", "false"],
                           ["false", "false", "false"]]


def test_aria_current_an_allen_stellen():
    """Vorlagen im Gebiet und Suchtreffer schreiben aria-current als Wahrheitswert; Auswahl einer Vorlage, eines Plans
    und einer Baustelle setzen es über markCurrent (auch an den Suchtreffern)."""
    vorlagen = re.findall(r'aria-current="\$\{(.*?)\}"', APP)
    assert vorlagen == ["selected === p", "Boolean(selected && selected.reference === r[0])"], vorlagen
    assert re.findall(r'setAttribute\("aria-current"', APP) == ['setAttribute("aria-current"'], "nur in markCurrent"
    select = _teil(APP, r"^  function select\(p, fromMap\) \{\n.*?\n  \}\n")
    assert "    markCurrent(p.reference);\n" in select
    for fn in (r"^  async function showPlan\(key\) \{\n.*?\n  \}\n", r"^  function showSite\(id\) \{\n.*?\n  \}\n",
               r"^  async function showPlanList\(\) \{\n.*?\n  \}\n", r"^  function showSiteList\(\) \{\n.*?\n  \}\n"):
        assert "    markCurrent(null);\n" in _teil(APP, fn), fn


# --- B2: Menü ☰ auf dem Telefon über offenen Überlagerungen ------------------------------------------------------------

def test_menue_ueber_ueberlagerungen_auf_dem_telefon():
    """style.css: Auf schmalen Bildschirmen liegt die Leiste mit geöffnetem Menü ☰ (body.nav-open) über Auswertung,
    Termine, Prozesse und Mitmachen (.overlay) und den Mega-Menüs; bis Runde 18 lag sie mit z-index 1000 darunter. Die
    Prüfung im Browser (Telefonmaß, Esc und Fokus) steht in tests/browser/bedienung.js."""
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    z = lambda sel: int(re.search(r"^" + re.escape(sel) + r" \{[^}]*?z-index: (\d+);", css, re.M).group(1))  # noqa: E731
    mobil = _teil(css, r"^@media \(max-width: 900px\) \{\n.*?\n\}\n")
    m = re.search(r"^  body\.nav-open \.nav \{ z-index: (\d+); \}$", mobil, re.M)
    assert m, "Regel für die Leiste mit offenem Menü fehlt in der Media-Query für Telefone"
    assert int(m.group(1)) > max(z(".overlay"), z(".mega"), z(".nav")), (m.group(1), z(".overlay"), z(".mega"))
    assert int(m.group(1)) < z(".tour")   # die Tour bleibt oben
    assert "body.nav-open .nav {" not in css.replace(mobil, "")   # breite Bildschirme unverändert


# --- B3: Themen-Chips bei „ganz Köln“ ohne Zahl ----------------------------------------------------------------------

def test_themen_chips_ohne_zahl_bei_ganz_koeln():
    """fillChips: Zahlen an den Themen nur mit geladenem Gebiet und Suche im Gebiet; bei „ganz Köln“ (noch kein Gebiet,
    keine Vorlagen geladen) und vor dem ersten Laden keine Zahl (bis Runde 18 stand „0“ an jedem Thema)."""
    teil = _teil(APP, r"^  const STADT = .*?;") + "\n" + _teil(APP, r"^  const esc = .*?;\n") \
        + _teil(APP, r"^  const THEMES = \{.*?\n  \};\n") + _teil(APP, r"^  function chip\(.*?\n  \}\n") \
        + _teil(APP, r"^  function fillChips\(\) \{\n.*?\n  \}\n")
    code = """
const el = {};
const $ = (s) => (el[s] ||= { value: "", innerHTML: "", textContent: "", options: [] });
const document = { querySelectorAll: () => [] };
let papers = [], area = null, umfang = "gebiet";
const scope = () => umfang;
""" + teil + """
const zahlen = () => [...$("#chips-theme").innerHTML.matchAll(/<button[^>]*data-theme="(\\w+)"[^>]*>.*?<\\/button>/g)]
  .map((m) => [m[1], (m[0].match(/<span class="n">(\\d+)<\\/span>/) || [])[1] ?? null]);
const aus = {};
fillChips(); aus.vorStart = zahlen();
area = { kind: STADT, key: "alle" }; fillChips(); aus.koeln = zahlen();
area = { kind: "ortsteil", key: "ehrenfeld" };
papers = [{ themes: [{ theme: "verkehr" }, { theme: "umwelt" }] }, { themes: [{ theme: "verkehr" }] }];
fillChips(); aus.gebiet = zahlen();
umfang = STADT; fillChips(); aus.sucheKoeln = zahlen();
console.log(JSON.stringify(aus));
"""
    aus = _node(code)
    themen = [k for k, _ in aus["gebiet"]]
    assert len(themen) >= 5 and {"verkehr", "umwelt"} <= set(themen)
    for zustand in ("vorStart", "koeln", "sucheKoeln"):
        assert aus[zustand] == [[k, None] for k in themen], zustand
    assert dict(aus["gebiet"]) == {k: {"verkehr": "2", "umwelt": "1"}.get(k, "0") for k in themen}


# --- B4: Tourtexte nach den Freigaben ---------------------------------------------------------------------------------

# Texte der Tour vor Runde 18 (Bonner Fassung): mit allen Freigaben unverändert; „Mitmachen“ seit dem zweiten Lauf
# (13.11.2026) mit dem Kölner Text („Alle Wege im Überblick“ zeigt die Kölner Wege, kein Bürgerantrag und keine Fristen)
BONN_TEXTE = {
    "Die Karte": (
        "Jeder Punkt ist eine Vorlage mit Ortsbezug; Zahlen fassen nahe Punkte zusammen, ein Klick zoomt "
        "hinein. Die Farbe zeigt, wie sicher der Ort ist: grün gesichert (Koordinate oder Bebauungsplan der "
        "Stadt), braun erschlossen (Name im Titel), violett unsicher. „Farbe nach Thema“ färbt die Punkte "
        "stattdessen nach Thema; die Legende erklärt die Farben. „Bebauungspläne“ blendet die "
        "Geltungsbereiche der rechtskräftigen Pläne ein; ein Klick auf eine Fläche öffnet die Planchronik. "
        "„Baustellen“ zeigt gemeldete Baustellen mit unverbindlichen Terminen. „Überschwemmungsgebiete“ und "
        "„Bodenrichtwerte“ zeigen beim Hineinzoomen Flächen des Landes zur Einordnung (abgeleitet "
        "aufbereitet, verbindlich sind die Quellen). „Farbige Karte“ schaltet den Hintergrund um. Alle diese "
        "Schaltflächen liegen unter „Ebenen“; die Zahl daneben nennt, wie viele eingeschaltet sind. Die "
        "Legenden unten links sind eingeklappt und öffnen sich mit einem Klick, darunter stehen Quellen, "
        "Lizenzen und Datenstand."),
    "Mitmachen": (
        "Kommende Sitzungen, auch als Kalenderdatei; unter „Informiert bleiben“ Feeds, die neue Vorlagen im "
        "Gebiet oder Änderungen an einem Vorgang melden; der Weg, sich mit Anregungen und Beschwerden nach § 24 "
        "GO NRW selbst an den Rat oder die Bezirksvertretung zu wenden; „Alle Wege im Überblick“ zeigt je "
        "Stadtbezirk die nächsten Sitzungen und alle Wege, sich einzubringen, von der Einwohnerfragestunde bis "
        "zum Bürgerbegehren; und ein Hinweis, wenn etwas falsch zugeordnet ist."),
    "Verstehen": (
        "Hilfen zum Lesen der Karte: der Ratsatlas in Einfacher Sprache, Begriffe wie Vorlage, Beratungsfolge"
        " oder Zuschussbedarf in einfachen Worten und wie verlässlich die Angaben sind. Diese Tour finden Sie"
        " hier wieder."),
    "Flächen ein- und ausklappen": (
        "Vorlagen (die Liste aller Vorlagen im Gebiet), Zeitleiste, Vorgang (die Einzelheiten einer Vorlage),"
        " Prozesse und Assistent lassen sich hier öffnen und schließen; die Karte bleibt darunter sichtbar. "
        "Esc schließt die Fläche, in der Sie gerade sind."),
}
# Wörter, die nur mit der Freigabe ihrer Funktion in der Tour stehen dürfen (wie tests/browser/bedienung.js)
WOERTER_JE_FUNKTION = {"baustellen": ["Baustelle"], "einfache_sprache": ["Einfache Sprache", "Einfacher Sprache"],
                       "haushalt": ["Zuschussbedarf", "Haushalt"], "mitmachen": ["Alle Wege im Überblick", "Bürgerantrag"],
                       "soll": ["Prozesse"], "chat": ["Assistent"], "themenseiten": ["Themenseiten"]}
ABGESCHALTET = [w for woerter in WOERTER_JE_FUNKTION.values() for w in woerter]
# Schalter und Karten der Zusatzthemen (app.js applyFunktionen und Schalter „Baustellen“); in der veröffentlichten Seite
# fehlen die Karten abgeschalteter Themen ganz (pipeline/seo.ohne_abgeschaltete)
SCHALTER = {".map-bau": "baustellen", '[data-funktion="einfache_sprache"]': "einfache_sprache",
            '[data-funktion="haushalt"]': "haushalt", '[data-funktion="mitmachen"]': "mitmachen",
            '.toggle[data-panel="panel-prozesse"]': "soll", ".toggle-ai": "chat"}
# Kölner Freigaben (config.ZUSATZTHEMEN) unter den Schaltern; seit 13.11.2026 mit Einfacher Sprache
KOELN = {f for f in SCHALTER.values() if config.ZUSATZTHEMEN.get(f)}


def _tour(an, telefon=False, fehlen=False, zeitleiste=True, vorschau=False):
    """Titel und Text der Schritte, die die Tour zeigt (when erfüllt), bei Freigaben `an` (Menge der Funktionen);
    `fehlen`: Elemente abgeschalteter Funktionen fehlen im Dokument statt ausgeblendet zu sein; `vorschau`:
    Kartenvorschau ohne Ratsvorlagen (Text unter vorschau, wo vorhanden, wie tour.js show)."""
    teil = _teil(TOUR, r"^  const MOBILE = matchMedia.*?\n  \];\n")
    dom = {sel: {"hidden": fn not in an} for sel, fn in SCHALTER.items() if fn in an or not fehlen}
    dom['.toggle[data-panel="timeline-wrap"]'] = {"hidden": not zeitleiste}
    dom['[data-mega="mega-auswertung"]'] = {"hidden": False}
    flaechen = [{"dataset": {"panel": p}, "hidden": p == "timeline-wrap" and not zeitleiste
                 or p == "panel-prozesse" and "soll" not in an or p == "panel-assistent" and "chat" not in an}
                for p in ("panel-list", "timeline-wrap", "panel-detail", "panel-prozesse", "panel-assistent")]
    code = f"""
const DOM = {json.dumps(dom)}, FL = {json.dumps(flaechen)};
const matchMedia = () => ({{ matches: {json.dumps(telefon)} }});
const document = {{ documentElement: {{ dataset: {json.dumps({"vorschau": "ja"} if vorschau else {})} }},
  querySelector: (sel) => DOM[sel] || null,
  querySelectorAll: (sel) => {{ if (sel.startsWith("[data-tour-")) return [];   // Sätze von Zusatzmodulen (keine geladen)
    if (sel !== ".nav-group.seg .toggle[data-panel]") throw new Error(sel); return FL; }} }};
""" + teil + """
const text = (s) => (VORSCHAU() && s.vorschau ? s.vorschau : s.text);
const aus = STEPS.filter((s) => !s.when || s.when()).map((s) => [s.title, typeof text(s) === "function" ? text(s)() : text(s)]);
console.log(JSON.stringify(aus));
"""
    return dict(_node(code))


def test_tour_nennt_keine_abgeschaltete_funktion():
    """Datenbetrieb mit den Kölner Freigaben (Baustellen, Haushalt, Prozesse und Assistent aus; Einfache Sprache und
    „Mitmachen in Köln“ seit 13.11.2026 an): kein Schritt nennt eine abgeschaltete Funktion, ob ihr Element
    ausgeblendet ist oder fehlt; an ihrer Stelle steht, was die Seite zeigt (Text der Vorschau zu § 24 GO NRW und zu
    den Begriffen)."""
    assert KOELN == {"einfache_sprache", "mitmachen"}
    aus_koeln = [w for f, woerter in WOERTER_JE_FUNKTION.items() if not config.ZUSATZTHEMEN.get(f) for w in woerter]
    for an, verboten in ((KOELN, aus_koeln), (set(), ABGESCHALTET)):
        for telefon in (False, True):
            for fehlen in (False, True):
                texte = _tour(an, telefon, fehlen)
                genannt = [(t, w) for t, x in texte.items() for w in verboten if w in t + " " + x]
                assert genannt == [], (an, telefon, fehlen, genannt)
                assert "Prozesse: Wer entscheidet was?" not in texte and "Der Ratsassistent" not in texte
                if "mitmachen" not in an:
                    # § 24 GO NRW: Rat oder Bezirksvertretung, auch ohne Freigabe „mitmachen“ (Nachprüfung 14.11.2026)
                    assert "der Weg, sich mit Anregungen und Beschwerden nach § 24 GO NRW selbst an den Rat oder die " \
                           "Bezirksvertretung zu wenden; und ein Hinweis" in texte["Mitmachen"]
                einfach = "der Ratsatlas in Einfacher Sprache, " if "einfache_sprache" in an else ""
                assert texte["Verstehen"].startswith(f"Hilfen zum Lesen der Karte: {einfach}Begriffe wie Vorlage, "
                                                     "Beratungsfolge oder Stadtbezirk in einfachen Worten")
            assert texte["Flächen ein- und ausklappen"].startswith(
                "Vorlagen (die Liste aller Vorlagen im Gebiet), Zeitleiste und Vorgang (die Einzelheiten einer "
                "Vorlage) lassen sich hier öffnen")
            assert "Planchronik. „Überschwemmungsgebiete“" in texte["Die Karte"]
    ohne_zeit = _tour(KOELN, zeitleiste=False)["Flächen ein- und ausklappen"]
    assert ohne_zeit.startswith("Vorlagen (die Liste aller Vorlagen im Gebiet) und Vorgang (die Einzelheiten einer "
                                "Vorlage) lassen sich")


def test_tour_mit_freigaben_wie_in_bonn():
    """Mit allen Freigaben zeigt die Tour die Texte der Bonner Fassung unverändert (sie kommen per Freigabe zurück);
    einzelne Freigaben schalten nur ihren Satz oder Teilsatz ein."""
    alle = set(SCHALTER.values())
    texte = _tour(alle)
    assert {t: texte[t] for t in BONN_TEXTE} == BONN_TEXTE
    assert "Prozesse: Wer entscheidet was?" in texte and "Der Ratsassistent" in texte
    einzeln = {fn: _tour({fn}) for fn in alle}
    assert "„Baustellen“ zeigt" in einzeln["baustellen"]["Die Karte"]
    assert "„Baustellen“ zeigt" not in einzeln["haushalt"]["Die Karte"]
    assert ("Einfacher Sprache, Begriffe wie Vorlage, Beratungsfolge oder Stadtbezirk"
            in einzeln["einfache_sprache"]["Verstehen"])
    assert "der Karte: Begriffe wie Vorlage, Beratungsfolge oder Zuschussbedarf" in einzeln["haushalt"]["Verstehen"]
    assert "„Alle Wege im Überblick“" in einzeln["mitmachen"]["Mitmachen"]
    assert "„Alle Wege im Überblick“" not in einzeln["chat"]["Mitmachen"]
    assert "Vorgang (die Einzelheiten einer Vorlage) und Prozesse lassen" in einzeln["soll"]["Flächen ein- und ausklappen"]
    assert "Vorgang (die Einzelheiten einer Vorlage) und Assistent lassen" in einzeln["chat"]["Flächen ein- und ausklappen"]


def test_tour_vorschau_nennt_einfache_sprache_nur_mit_freigabe():
    """Kartenvorschau ohne Ratsvorlagen: Der Schritt „Verstehen“ nennt die Einfache Sprache wie im Datenbetrieb nur, wenn
    ihre Karte sichtbar ist (13.11.2026; vorher stand der Text der Vorschau fest ohne sie)."""
    for telefon in (False, True):
        mit = _tour(KOELN, telefon, vorschau=True)["Verstehen"]
        ohne = _tour(set(), telefon, vorschau=True)["Verstehen"]
        assert mit == ("Hilfen zum Lesen der Karte: der Ratsatlas in Einfacher Sprache, Begriffe wie Vorlage, "
                       "Beratungsfolge oder Stadtbezirk in einfachen Worten und wie verlässlich die Angaben sind. Diese "
                       "Tour finden Sie hier wieder.")
        assert ohne == mit.replace("der Ratsatlas in Einfacher Sprache, ", "")
        assert "Ratsvorlagen" in _tour(KOELN, telefon, vorschau=True)["Willkommen zur Tour"]


def test_zeitleiste_hinweis_zu_baustellen_nur_mit_baustellen():
    """„Was die Zeitleiste nicht zeigt“: der Satz zu den Baustellen ist ausgeblendet und erscheint nur, wenn das Gebiet
    eine Baustellenspur hat (setSites mit Einträgen; Baustellen in Köln abgeschaltet)."""
    tl = (ROOT / "site" / "timeline.js").read_text(encoding="utf-8")
    assert '<li class="tl-bau-grenze" hidden>Baustellen vor Beginn des Archivs' in tl
    assert ('setSites(list) { sites = list || []; root.querySelector(".tl-bau-grenze").hidden = !sites.length; draw(); },'
            in tl)


# --- B6 und B7 (Ladezeit): Termine über eine Zuordnung je Sitzung, Punkte gesammelt, „Weitere“ nur für die Liste ---------

def test_termine_vorlagen_je_sitzung_wie_bisher():
    """showTermine: Die Vorlagen je Sitzung kommen aus einer einmal aufgebauten Zuordnung „Datum|Gremium“; das Ergebnis
    ist dasselbe wie bisher (Filter über alle Vorlagen je Sitzung), auch in der Reihenfolge, ohne doppelte Vorlagen und
    nur für Beratung und Entscheidung."""
    teil = _teil(APP, r"^  function vorlagenJeSitzung\(list\) \{\n.*?\n  \}\n")
    termine = _teil(APP, r"^  function showTermine\(\) \{\n.*?\n  \}\n")
    assert "    const jeSitzung = vorlagenJeSitzung(papers);\n" in termine
    code = teil + """
// erfundene Vorlagen und Sitzungen (festes Zufallsmuster), auch ohne Datum, mit anderem Schritt und doppelt
let z = 7;
const zufall = (n) => { z = (z * 1103515245 + 12345) % 2147483648; return Math.floor(z / 65536) % n; };   // obere Bits
const DATEN = ["2026-11-12", "2026-11-19", "2026-12-03", null];
const GREMIEN = ["Rat", "Bezirksvertretung Porz", "Verkehrsausschuss", undefined];
const TYP = ["beratung", "entscheidung", "einreichung", "folgevorlage"];
const papers = Array.from({ length: 300 }, (_, i) => ({ reference: `${i}/2026`, steps: Array.from({ length: zufall(5) },
  () => ({ typ: TYP[zufall(4)], date: DATEN[zufall(4)], label: GREMIEN[zufall(4)] })) }));
const meetings = DATEN.filter(Boolean).flatMap((date) => GREMIEN.map((gremium) => ({ date, gremium })));
// bisheriger Ausdruck in showTermine (bis Runde 18)
const alt = (m) => papers.filter((p) => p.steps.some((s) => (s.typ === "beratung" || s.typ === "entscheidung")
  && s.date === m.date && s.label === m.gremium));
const je = vorlagenJeSitzung(papers);
const neu = (m) => [...(je.get(`${m.date}|${m.gremium}`) || [])];
const andere = papers.filter((p) => meetings.some((m) => !alt(m).includes(p)
  && p.steps.some((s) => s.date === m.date && s.label === m.gremium))).length;
const refs = (ps) => ps.map((p) => p.reference);
console.log(JSON.stringify([meetings.map((m) => [refs(alt(m)), refs(neu(m))]), andere]));
"""
    paare, andere = _node(code)
    assert len(paare) == 12 and sum(len(a) for a, _ in paare) > 100
    assert andere > 20   # Schritte anderer Art an einer Sitzung, die dort nicht zählen
    assert all(a == n for a, n in paare), [(a, n) for a, n in paare if a != n][:2]


def test_punkte_gesammelt_und_weitere_nur_fuer_die_liste():
    """drawMarkers fügt alle Punkte mit einem Aufruf von addLayers hinzu (vorher einzeln mit addLayer), gleiche Zahl und
    Reihenfolge; „Weitere … anzeigen“ rendert nur die Liste (Karte und Zeitleiste bleiben). Im Browser: Punktzahl und
    Aufrufe in tests/browser/bedienung.js."""
    teil = _teil(APP, r"^  function drawMarkers\(list\) \{\n.*?\n  \}\n")
    code = """
let lastMarkers = [], legendEl = null;
const markers = new Map(), MARKER = { radius: 7 }, esc = (s) => s, markerColor = () => "#000";
const select = () => {}, highlight = () => {};
const areaLocs = (p) => p.locations;
const L = { circleMarker: (ll) => ({ ll, bindTooltip() { return this; }, on() { return this; } }) };
const aufrufe = [];
const cluster = { punkte: [], clearLayers() { this.punkte = []; aufrufe.push("clearLayers"); },
  addLayer(m) { this.punkte.push(m); aufrufe.push("addLayer"); },
  addLayers(a) { this.punkte.push(...a); aufrufe.push(`addLayers ${a.length}`); } };
""" + teil + """
const ort = (level, lon, name) => ({ level, lon, lat: 50.9, name });
drawMarkers([
  { reference: "1/2026", locations: [ort("strasse", 6.9, "A"), ort("ortsteil", 6.9, "B"), ort("objekt", 7.0, "C")] },
  { reference: "2/2026", locations: [ort("bebauungsplan", 6.8, "D"), ort("strasse", null, "E")] },
  { reference: "3/2026", locations: [] }]);
console.log(JSON.stringify({ aufrufe, punkte: cluster.punkte.map((m) => m.ll[1]),
  je: [...markers].map(([r, ms]) => [r, ms.length]) }));
"""
    assert _node(code) == {"aufrufe": ["clearLayers", "addLayers 3"], "punkte": [6.9, 7.0, 6.8],
                           "je": [["1/2026", 2], ["2/2026", 1], ["3/2026", 0]]}
    assert "cluster.addLayer(" not in APP
    weiter = _teil(APP, r'^      if \(e\.target\.closest\("#more"\)\) \{\n.*?\n      \}\n')
    assert "shown += LIST_STEP; render(true);" in weiter
    render = _teil(APP, r"^  function render\(nurListe\) \{\n.*?\n  \}\n")
    assert "return renderGlobal(nurListe);" in render
    assert "    if (!nurListe) {\n      drawMarkers(list);\n      if (tl) tl.setPapers(base);\n    }\n" in render
    glob = _teil(APP, r"^  function renderGlobal\(nurListe\) \{\n.*?\n  \}\n")
    assert re.search(r"    if \(!nurListe\) \{\n.*?drawMarkers\(papers\.filter.*?\n    \}\n", glob, re.S)
    # alle übrigen Aufrufe zeichnen die Karte wie bisher
    assert re.findall(r"render\(true\)", APP) == ["render(true)"]


# --- B5: Dateigrößen im Menü „Daten“ ------------------------------------------------------------------------------------

def test_groesse_text():
    g = _modul("seite_bauen").groesse_text
    erwartet = ["0 kB", "1 kB", "1 kB", "212 kB", "999 kB", "1,0 MB", "4,8 MB", "9,9 MB", "10 MB", "74 MB"]
    # gesch\u00fctztes Leerzeichen zwischen Zahl und Einheit (kein Umbruch in der Karte)
    assert [g(n) for n in (0, 1, 499, 212_000, 999_499, 999_500, 4_777_753, 9_949_999, 9_950_000, 74_123_456)] == [
        x.replace(" ", "\u00a0") for x in erwartet]


def _sed_muster():
    """Das Muster, mit dem pages.yml im Branch deploy den Link auf das Datenpaket ersetzt (sed auf index.html)."""
    yml = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    m = re.search(r'sed -i "s\|(href=\\"data/export/[^|]+\\")\|', yml)
    assert m, "Ersatz des Zip-Links in pages.yml nicht gefunden"
    return m.group(1).replace('\\"', '"')


def test_groessen_im_menue_daten(tmp_path):
    """Karten mit download im Menü „Daten“ nennen die Größe der Datei im Kartentext; fehlt die Datei, bleibt der Text
    ohne Angabe; Adresse und übriger Text bleiben, der Ersatz des Zip-Links in pages.yml greift weiter."""
    sb = _modul("seite_bauen")
    shutil.copy(ROOT / "site" / "index.html", tmp_path / "index.html")
    vorher = (tmp_path / "index.html").read_text(encoding="utf-8")
    zip_text = '<span class="card-text">Alle Exporte, Audit-Protokolle und Lizenzen{}.</span></a>'
    geo_text = '<span class="card-text">Ein Punkt je Vorlage und Ort, mit Methode, Konfidenz und Fundstelle{}.</span></a>'
    assert zip_text.format("") in vorher and geo_text.format("") in vorher
    sb.groessen_eintragen(tmp_path)   # beide Dateien fehlen: unverändert
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == vorher
    (tmp_path / "data" / "export" / "koeln").mkdir(parents=True)
    with open(tmp_path / "data" / "export" / "ratsatlas-koeln-export.zip", "wb") as f:
        f.truncate(74_123_456)
    sb.groessen_eintragen(tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert zip_text.format(" (74\u00a0MB)") in html and geo_text.format("") in html
    assert html.replace(" (74\u00a0MB)", "") == vorher
    assert _sed_muster() in html
    (tmp_path / "index.html").write_text(vorher, encoding="utf-8")
    (tmp_path / "data" / "export" / "koeln" / "vorlagen.geojson").write_bytes(b"x" * 211_907)
    sb.groessen_eintragen(tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert zip_text.format(" (74\u00a0MB)") in html and geo_text.format(" (212\u00a0kB)") in html
    # andere Links mit download (Kalender) und Karten ohne download bleiben ohne Angabe
    assert html.replace(" (74\u00a0MB)", "").replace(" (212\u00a0kB)", "") == vorher


def test_seite_bauen_traegt_groessen_ein(oparl, tmp_path):
    """tools/seite_bauen.py: die Größen stammen aus den Dateien im fertigen Ordner (Datenpaket und GeoJSON aus
    config.EXPORT); der Zip-Link bleibt für pages.yml ersetzbar."""
    sessionnet.fetch_all()
    build.build()
    export.export()
    kontext.write()
    ebenen.write()
    paket.write()
    site = tmp_path / "_site"
    sb = _modul("seite_bauen")
    sb.main(site)
    html = (site / "index.html").read_text(encoding="utf-8")
    for pfad, text in (("data/export/ratsatlas-koeln-export.zip", "Alle Exporte, Audit-Protokolle und Lizenzen"),
                       ("data/export/koeln/vorlagen.geojson",
                        "Ein Punkt je Vorlage und Ort, mit Methode, Konfidenz und Fundstelle")):
        groesse = sb.groesse_text((site / pfad).stat().st_size)
        assert f'{text} ({groesse}).</span></a>' in html, pfad
    assert _sed_muster() in html


def test_zeitleiste_ohne_bonner_grenzen():
    """site/timeline.js, „Was die Zeitleiste nicht zeigt“: keine Aussagen über das Bonner ALLRIS-Archiv oder OParl-Lite."""
    tl = (ROOT / "site" / "timeline.js").read_text(encoding="utf-8")
    grenzen = _teil(tl, r'<ul class="tl-limits">.*?</ul>')
    for bonn in ("ALLRIS", "OParl-Lite", "Oktober 2019"):
        assert bonn not in grenzen, bonn
    assert "ohne verknüpfte Sitzung" in grenzen
