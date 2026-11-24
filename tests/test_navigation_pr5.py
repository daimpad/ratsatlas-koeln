"""Pull Request 5 der Navigation (Entscheidung 24.11.2026 (2), Punkte (a) bis (c)): Texte der Kartenvorschau ohne
Ankündigung, Fokus nach dem Ende der Tour, Tab aus einem offenen Menü, Beschriftung der Leiste ab 1366 px, Eingabefelder
mit 16 px Schrift auf dem Telefon, Fokus nach dem Öffnen eines Eintrags der Liste, Blätter bei geringer Höhe, „Selbst
mitwirken“ ohne benannten Bereich. Nach der Prüfung des Pull Requests: Suchmenü mit der Tastatur, Schnellfilter
behalten den Fokus, Textabstände nach WCAG 1.4.12 und Platzhalter, Fokus eines Suchtreffers nur, wenn er frei ist. Aus
#52, Punkt 4: Wahl in „Gremien und Ämter“, während gremien.js noch lädt, und Anzeige während des Ladens. Geprüft ohne
Browser (node mit nachgebildetem Dokument, Python); die Prüfung im Browser steht in tests/browser/navigation.js (Punkt 4
in tests/browser/gremien.js, BEDIENUNG.wahlBeimImport und anzeigeBeimLaden). Alle Daten sind erfunden; keine Anfragen
nach außen."""
import json
import re
from pathlib import Path

import test_seite_bedienung as bedienung  # noqa: E402  (Schritte der Tour mit nachgebildetem Dokument)
from test_navigation_koeln import _node, _teil  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
TOUR = (ROOT / "site" / "tour.js").read_text(encoding="utf-8")
CSS = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
ANKUENDIGUNG = re.compile(r"\bfolg(?:t|en)\b|kommt hinzu|kommen hinzu|künftig|sobald|bis dahin", re.I)


def _media(bedingung):
    """Alle Blöcke `@media <bedingung> { … }` aus style.css (Blöcke auf oberster Ebene, schließende Klammer am
    Zeilenanfang)."""
    return re.findall(r"^@media " + re.escape(bedingung) + r" \{\n.*?\n\}\n", CSS, re.S | re.M)


# --- (1) Kartenvorschau ohne Ankündigung -------------------------------------------------------------------------------

def test_tour_vorschau_ohne_ankuendigung():
    """(1) Die Texte der Tour in der Kartenvorschau beschreiben nur, was die Vorschau zeigt: kein „folgen“, „kommt
    hinzu“, „künftig“, „sobald“ oder „bis dahin“ (21.11.2026 (1) (12)); keine Punkte für Vorlagen, keine Zeitleiste,
    keine Filter der Liste (in der Vorschau ausgeblendet). Die Texte außerhalb der Vorschau bleiben, wie sie sind."""
    for an in (bedienung.KOELN, set()):
        for telefon in (False, True):
            # in der Vorschau fehlt die Zeitleiste (keine zeit.json), mit ihr der Schritt „Die Zeitleiste“
            texte = bedienung._tour(an, telefon, vorschau=True, zeitleiste=False)
            mit = {t: ANKUENDIGUNG.search(x).group(0) for t, x in texte.items() if ANKUENDIGUNG.search(x)}
            assert mit == {}, (an, telefon, mit)
            assert "Zeitleiste" not in texte["Flächen ein- und ausklappen"] and "Punkte" not in texte["Die Karte"]
            assert "Filtern" not in texte["Die Vorlagen"] and "Ratsvorlagen" in texte["Willkommen zur Tour"]
            assert "wann (Zeitleiste)" not in texte["Willkommen zur Tour"]
            assert texte["Die Vorlagen"].startswith("Die Liste der Vorlagen im Gebiet. Die Vorschau enthält noch keine "
                                                     "Ratsvorlagen, die Liste bleibt deshalb leer.")
            assert texte["Suche in ganz Köln"] == ("Das Suchfeld durchsucht die Vorlagen in ganz Köln nach Stichwort oder "
                                                   "Vorlagennummer. Die Vorschau enthält noch keine Ratsvorlagen; die Suche "
                                                   "findet deshalb nichts.")
            assert "§ 24 GO NRW" in texte["Mitmachen"] and "„Informiert bleiben“" in texte["Mitmachen"]
    # außerhalb der Vorschau unverändert, auch „Liste und Karte folgen“ (keine Ankündigung: sie passen sich an)
    daten = bedienung._tour(bedienung.KOELN)
    assert daten["Die Zeitleiste"].endswith("wählen Sie einen Zeitraum – Liste und Karte folgen.")
    assert daten["Willkommen zur Tour"].startswith("Der Ratsatlas zeigt, womit sich Rat, Bezirksvertretungen und "
                                                   "Ausschüsse der Stadt Köln befassen: wo (Karte), wann (Zeitleiste)")


def test_satz_der_vorschau_in_app_js_ohne_ankuendigung():
    """(1) VORSCHAU_LISTE (Liste, „In Zahlen“, Verfahrenswege in der Vorschau) ohne Ankündigung; die Zeilen „noch keine
    Ratsvorlagen (Vorschau)“ in #count und in der Legende bleiben als Angabe zum Stand."""
    satz = re.search(r'^  const VORSCHAU_LISTE = "([^"]+)";$', APP, re.M).group(1)
    assert satz == "Die Vorschau enthält noch keine Ratsvorlagen. Die Karte zeigt Stadtteile, Kennzahlen und offene Daten (Menü „Ebenen“)."
    assert not ANKUENDIGUNG.search(satz)
    vorschau_texte = re.findall(r"vorschau: (?:\(\) => )?[\"`](.*?)[\"`]\s*(?:\+|\})", TOUR)
    assert len(vorschau_texte) >= 8
    for t in vorschau_texte:
        assert not ANKUENDIGUNG.search(t), t


# --- (2) Fokus nach dem Ende der Tour ----------------------------------------------------------------------------------

def _tour_ziele(fall):
    """fokusZiele aus site/tour.js mit nachgebildetem Dokument: Elemente mit Sichtbarkeit; liefert die Namen der Ziele
    in ihrer Reihenfolge."""
    teil = _teil(TOUR, r"^  const shown = .*?;\n") + _teil(TOUR, r"^  const KOEPFE = .*?;\n") + _teil(TOUR, r"^  const LEISTE = .*?;\n") \
        + _teil(TOUR, r"^  const zuSehen = .*?;\n") + _teil(TOUR, r"^  function fokusZiele\(\) \{\n.*?\n  \}\n")
    code = """
const el = (name, zuSehen, inHidden = false) => ({ name, isConnected: true, getClientRects: () => (zuSehen ? [1] : []),
  closest: (sel) => (inHidden ? {} : null) });
const body = el("body", true);
const F = """ + fall + """;
const document = { body, querySelectorAll: (sel) => F.dom[sel] || [] };
const getComputedStyle = () => ({ visibility: "visible" });
let prevFocus = F.prev === "body" ? body : F.prev;
""" + teil + """
console.log(JSON.stringify(fokusZiele().map((e) => e.name)));
"""
    return _node(code)


def test_tour_fokus_nach_dem_ende():
    """(2) Nach Esc, Schließen oder „Fertig“: das auslösende Element, wenn es zu sehen ist; sonst die Überschrift einer
    offenen Fläche (Überlagerung vor Vorgang vor Liste); sonst das erste Element der Leiste außer dem Suchfeld
    (Wortmarke, auf dem Telefon „Menü“). Nie <body>, nie ein Element in einem geschlossenen Bereich."""
    sel = {"ov": ".overlay:not([hidden]) h2[tabindex]", "det": "#panel-detail:not([hidden]) h2[tabindex]",
           "pan": ".panel:not([hidden]) h2[tabindex]", "marke": ".nav a.brand", "menue": "#nav-burger"}
    def fall(prev, dom):
        return "{ prev: " + prev + ", dom: {" + ", ".join(f"{json.dumps(sel[k])}: [{v}]" for k, v in dom.items()) + "} }"
    # Auslöser zu sehen (Start aus „Los geht's“, Esc im ersten Schritt)
    assert _tour_ziele(fall('el("start", true)', {"det": 'el("vorgang", true)', "marke": 'el("marke", true)'}))[0] == "start"
    # Auslöser im geschlossenen Menü „Über“ (Desktop): Überschrift des Vorgangs bzw. „Los geht's“
    assert _tour_ziele(fall('el("karte-tour", false)', {"det": 'el("vorgang", true)', "pan": 'el("vorgang", true)',
                                                         "marke": 'el("marke", true)', "menue": 'el("menue", false)'}))[0] == "vorgang"
    # offene Überlagerung vor dem Vorgang
    assert _tour_ziele(fall("null", {"ov": 'el("termine", true)', "det": 'el("vorgang", true)'}))[:2] == ["termine", "vorgang"]
    # Telefon nach der Tour: keine Fläche offen, Wortmarke ausgeblendet, „Menü“ zu sehen
    assert _tour_ziele(fall('el("karte-tour", true, true)', {"marke": 'el("marke", false)', "menue": 'el("menue", true)'})) == ["menue"]
    # <body> als vorheriger Fokus zählt nicht
    assert _tour_ziele(fall('"body"', {"marke": 'el("marke", true)'})) == ["marke"]
    ende = _teil(TOUR, r"^  function end\(\) \{\n.*?\n  \}\n")
    assert "for (const ziel of fokusZiele())" in ende and "if (document.activeElement === ziel) break;" in ende
    assert '$("#detail-heading")' not in ende


# --- (3) Tab aus einem offenen Menü ------------------------------------------------------------------------------------

def test_menue_schliesst_wenn_der_fokus_es_verlaesst():
    """(3) focusout: Verlässt der Fokus Menü und Schaltfläche (beim Suchmenü das Suchfeld), geht das Menü zu; bleibt er
    darin oder auf der Schaltfläche, oder gibt es kein neues Ziel (relatedTarget null), bleibt es offen."""
    teil = _teil(APP, r"^  const zumMenue = .*?\n.*?;\n") + _teil(APP, r'^  document\.addEventListener\("focusout", \(e\) => \{\n.*?\n  \}\);\n')
    code = """
class Element { constructor(name, wo) { this.name = name; this.wo = wo; } closest(sel) {
  if (sel === "#nav-search") return this.wo === "suchfeld" ? this : null;
  const m = sel.match(/^\\[data-mega="(.+)"\\]$/); return m && this.wo === "knopf:" + m[1] ? this : null; } }
const MENUES = { "mega-themen": { contains: (e) => e.wo === "mega-themen" }, "mega-suche": { contains: (e) => e.wo === "mega-suche" } };
let handler = null, openMegaId = null, geschlossen = 0;
const document = { getElementById: (id) => MENUES[id], addEventListener: (typ, f) => { if (typ === "focusout") handler = f; } };
const closeMega = () => { geschlossen++; openMegaId = null; };
""" + teil + """
const E = (wo) => new Element(wo, wo);
const fall = (menue, von, nach) => { openMegaId = menue; geschlossen = 0; handler({ target: von, relatedTarget: nach }); return geschlossen; };
console.log(JSON.stringify([
  fall("mega-themen", E("mega-themen"), E("draussen")),          // Tab aus dem Menü hinaus
  fall("mega-themen", E("mega-themen"), E("mega-themen")),       // Tab im Menü
  fall("mega-themen", E("mega-themen"), E("knopf:mega-themen")), // Umschalt+Tab auf die eigene Schaltfläche
  fall("mega-themen", E("knopf:mega-themen"), E("knopf:mega-mitmachen")),  // von der Schaltfläche zur nächsten
  fall("mega-themen", E("mega-themen"), null),                   // anderes Fenster, Klick ohne Fokus
  fall("mega-themen", E("draussen"), E("draussen2")),            // Fokuswechsel außerhalb
  fall(null, E("mega-themen"), E("draussen")),                   // kein Menü offen
  fall("mega-suche", E("suchfeld"), E("draussen")),              // Tab aus dem Suchfeld
  fall("mega-suche", E("suchfeld"), E("mega-suche")),            // ins Suchmenü
  fall("mega-suche", E("mega-suche"), E("suchfeld")),            // zurück ins Suchfeld
]));
"""
    assert _node(code) == [1, 0, 0, 1, 0, 0, 0, 1, 0, 0]
    # Esc und Klicks wie bisher
    esc = _teil(APP, r'^  document\.addEventListener\("keydown", \(e\) => \{\n    if \(e\.key !== "Escape".*?\n  \}\);\n')
    assert "if (openMegaId) return closeMega(true);" in esc
    assert 'if (openMegaId && e.target.isConnected && !e.target.closest(".mega") && !e.target.closest("#nav-search")) closeMega();' in APP


def test_suchmenue_mit_der_tastatur():
    """(3) nach der Prüfung von Pull Request 5: Das Suchmenü steht im Dokument hinter der ganzen Leiste. Ist es offen,
    führt Tab aus dem Suchfeld auf sein erstes Bedienelement, Umschalt+Tab vom ersten zurück ins Suchfeld und Tab vom
    letzten auf das Element der Leiste nach dem Suchfeld (Gebiet, Telefon „Menü“). Alle übrigen Wege (Umschalt+Tab aus
    dem Suchfeld, Tab innerhalb des Menüs, anderes Menü offen, Strg/Alt) lässt die Regel dem Browser und focusout."""
    teil = _teil(APP, r'^  document\.addEventListener\("keydown", \(e\) => \{\n    if \(e\.key !== "Tab".*?\n  \}\);\n')
    code = """
const el = (name) => ({ name, focus() { doc.aktiv = this; } });
const Q = el("q"), A = el("erstes"), B = el("mitte"), C = el("letztes"), WEITER = el("gebiet"), BODY = el("body");
const doc = { aktiv: Q };
let handler = null, openMegaId = "mega-suche", ELS = [A, B, C];
const document = { get activeElement() { return doc.aktiv; }, addEventListener: (t, f) => { if (t === "keydown") handler = f; } };
const $ = (s) => (s === "#q" ? Q : null);
const imSuchmenue = () => ELS, nachSuchfeld = () => WEITER;
""" + teil + """
const fall = (von, taste, opts = {}) => { doc.aktiv = von; let verhindert = false;
  handler({ key: taste, shiftKey: Boolean(opts.shift), altKey: false, ctrlKey: Boolean(opts.ctrl), metaKey: false, preventDefault: () => { verhindert = true; } });
  return verhindert ? doc.aktiv.name : "Browser"; };
const aus = [
  fall(Q, "Tab"),                     // aus dem Suchfeld ins Menü
  fall(A, "Tab"),                     // innerhalb des Menüs: der Browser
  fall(C, "Tab"),                     // vom letzten auf „Gebiet“
  fall(A, "Tab", { shift: true }),    // vom ersten zurück ins Suchfeld
  fall(Q, "Tab", { shift: true }),    // aus dem Suchfeld zurück: der Browser (focusout schließt)
  fall(Q, "Tab", { ctrl: true }),     // Strg+Tab
  fall(Q, "Enter"),                   // andere Taste
];
openMegaId = "mega-themen"; aus.push(fall(Q, "Tab"));
openMegaId = "mega-suche"; ELS = []; aus.push(fall(Q, "Tab"));   // Vorschau: keine Bedienelemente im Menü
console.log(JSON.stringify(aus));
"""
    assert _node(code) == ["erstes", "Browser", "gebiet", "q", "Browser", "Browser", "Browser", "Browser", "Browser"]
    # sichtbare, fokussierbare Bedienelemente; das nächste Element der Leiste nach dem Suchfeld (Telefon: „Menü“)
    imm = _teil(APP, r"^  const imSuchmenue = .*?;\n")
    nach = _teil(APP, r"^  const nachSuchfeld = .*?;\n")
    assert '$("#mega-suche").querySelectorAll("button, a[href], input, select, textarea")' in imm and "sichtbarEl(el)" in imm
    assert "Node.DOCUMENT_POSITION_FOLLOWING" in nach and '!$("#nav-search").contains(el)' in nach and "sichtbarEl(el)" in nach
    # im Dokument: Suchfeld vor ☰ und „Gebiet“, Suchmenü erst hinter der Leiste
    assert INDEX.index('id="q"') < INDEX.index('id="nav-burger"') < INDEX.index('id="f-area"') < INDEX.index("</nav>") < INDEX.index('id="mega-suche"')


def test_schnellfilter_behaelt_den_fokus():
    """(3) nach der Prüfung von Pull Request 5: fillChips baut die Schnellfilter neu auf; hatte der gewählte den Fokus
    (Enter oder Leertaste), bekommt ihn sein Nachfolger, sonst läge er auf <body>."""
    teil = _teil(APP, r"^    const chipFokus = .*?;\n")
    code = """
const doc = { aktiv: null };
const mk = (name) => ({ name, focus() { doc.aktiv = this; } });
const ALT = mk("alt"), NEU = mk("neu"), BODY = mk("body");
let gebaut = 0;
const document = { get activeElement() { return doc.aktiv; } };
const applyFromBar = () => { gebaut++; if (doc.aktiv === ALT) doc.aktiv = BODY; };
const $ = () => ({ querySelector: (sel) => (sel === '[data-theme="verkehr"]' ? NEU : null) });
""" + teil + """
const aus = [];
doc.aktiv = ALT; chipFokus(ALT, '[data-theme="verkehr"]'); aus.push(doc.aktiv.name);
doc.aktiv = mk("anderes"); chipFokus(ALT, '[data-theme="verkehr"]'); aus.push(doc.aktiv.name);
doc.aktiv = ALT; chipFokus(ALT, '[data-theme="weg"]'); aus.push(doc.aktiv.name);
aus.push(gebaut);
console.log(JSON.stringify(aus));
"""
    assert _node(code) == ["neu", "anderes", "body", 3]
    klick = _teil(APP, r'^    \$\("#mega-suche"\)\.addEventListener\("click", \(e\) => \{\n.*?\n    \}\);\n')
    assert "return chipFokus(t, `[data-theme=\"${CSS.escape(t.dataset.theme)}\"]`);" in klick
    assert "return chipFokus(pa, `[data-party=\"${CSS.escape(pa.dataset.party)}\"]`);" in klick


# --- (4) Beschriftung ab 1366 px ---------------------------------------------------------------------------------------

def test_beschriftung_ab_1366_px():
    """(4) Nur Symbole zwischen 901 und 1365 px (vorher bis 1599 px); ab 1366 px stehen die Namen sichtbar neben den
    Symbolen, zwischen 1366 und 1599 px enger gesetzt (ohne Pfeil, Abstände kleiner, Gebiet höchstens 150 px)."""
    symbole = _media("(min-width: 901px) and (max-width: 1365px)")
    assert len(symbole) == 1 and ".toggle > span, .menu-btn > span { position: absolute; width: 1px;" in symbole[0]
    assert not _media("(min-width: 901px) and (max-width: 1599px)")
    eng = _media("(min-width: 1366px) and (max-width: 1599px)")
    assert len(eng) == 1 and "span" not in eng[0] and ".menu-btn .chev { display: none; }" in eng[0]
    assert ".nav-area { max-width: 150px; }" in eng[0] and ".toggle, .menu-btn { padding: 0 6px; gap: 4px; }" in eng[0]
    # keine andere Regel versteckt die Namen ab 1366 px
    assert CSS.count(".toggle > span, .menu-btn > span { position: absolute;") == 1
    assert 'const NUR_SYMBOLE = matchMedia("(min-width: 901px) and (max-width: 1365px)");' in APP


def test_textabstaende_und_platzhalter():
    """(4) nach der Prüfung von Pull Request 5: Mit den Textabständen nach WCAG 1.4.12 ragte die beschriftete Leiste bei
    1366 px um 34 px über; zwischen 1366 und 1599 px darf das Suchfeld deshalb bis 120 px schmal werden (sonst 160 px).
    Der Platzhalter „In ganz Köln suchen …“ ist ein Teil des Namens aus dem verborgenen Label (WCAG 2.5.3) und kürzer
    als der bisherige, der bei 1366 px und auf dem iPhone 13 mitten im Wort abgeschnitten war."""
    eng = _media("(min-width: 1366px) and (max-width: 1599px)")
    assert len(eng) == 1 and ".nav-search { min-width: 120px; }" in eng[0]
    assert ".nav-search { position: relative; flex: 1 1 260px; max-width: 440px; min-width: 160px; }" in CSS
    label = re.search(r'<label class="visually-hidden" for="q">([^<]+)</label>', INDEX).group(1)
    platzhalter = re.search(r'<input type="search" id="q" placeholder="([^"]+)"', INDEX).group(1)
    assert label == "Vorlagen in ganz Köln suchen" and platzhalter == "In ganz Köln suchen …"
    assert platzhalter.rstrip(" …").lower() in label.lower() and len(platzhalter) < len(label)


def test_title_nur_wo_die_leiste_nur_symbole_zeigt():
    """(4) title der Schaltflächen nur bei 901 bis 1365 px; wo die Beschriftung zu sehen ist, ist sie der Name und ein
    title fehlt (sonst läsen Bildschirmleser den Namen zweimal). Der Text bleibt in data-titel, auch der Titel von „Wer
    entscheidet“, den applyFunktionen nach der Freigabe setzt; ein Wechsel der Breite stellt ihn wieder her."""
    teil = _teil(APP, r"^  const NUR_SYMBOLE = .*?;\n").replace('matchMedia("(min-width: 901px) and (max-width: 1365px)")', "MQ") \
        + _teil(APP, r"^  function leistenTitel\(\) \{\n.*?\n  \}\n") + _teil(APP, r'^  NUR_SYMBOLE\.addEventListener\("change", leistenTitel\);\n')
    code = """
const MQ = { matches: true, addEventListener: (t, f) => { MQ.f = f; } };
const knopf = (t) => ({ attrs: { title: t }, dataset: {}, get title() { return this.attrs.title; }, set title(v) { this.attrs.title = v; },
  hasAttribute(n) { return n in this.attrs; }, removeAttribute(n) { delete this.attrs[n]; } });
const K = [knopf("Themen: Vorlagen nach Thema"), knopf("Wer entscheidet: Verfahrenswege in Zahlen")];
const document = { querySelectorAll: (sel) => (sel === ".nav .toggle, .nav .menu-btn" ? K : []) };
""" + teil + """
const aus = [];
leistenTitel(); aus.push(K.map((k) => k.attrs.title ?? null));
MQ.matches = false; MQ.f(); aus.push(K.map((k) => k.attrs.title ?? null));
K[1].title = "Wer entscheidet: Gremien, Ämter und Verfahrenswege in Zahlen"; leistenTitel(); aus.push(K.map((k) => k.attrs.title ?? null));
MQ.matches = true; MQ.f(); aus.push(K.map((k) => k.attrs.title ?? null));
console.log(JSON.stringify(aus));
"""
    assert _node(code) == [["Themen: Vorlagen nach Thema", "Wer entscheidet: Verfahrenswege in Zahlen"], [None, None], [None, None],
                           ["Themen: Vorlagen nach Thema", "Wer entscheidet: Gremien, Ämter und Verfahrenswege in Zahlen"]]
    assert re.search(r"^    applyFunktionen\(fn, idx\);\n    leistenTitel\(\);\n", APP, re.M)


# --- (5) Eingabefelder auf dem Telefon ----------------------------------------------------------------------------------

def test_eingabefelder_telefon_16_px_und_44_px():
    """(5) Auf dem Telefon (bis 900 px) haben auch das Suchfeld der Leiste, die Reiter von „In Zahlen“, die Auswahl des
    Stadtbezirks in „Mitmachen in Köln“ und die Auswahl der Kennzahl in der Legende 16 px Schrift (darunter vergrößert
    iOS beim Fokus) und mindestens 44 px Höhe (das Suchfeld ist dort schon 44 px hoch). Die Kennzahl über ihre Kennung,
    weil `.nav-metric select` weiter unten 12 px setzt."""
    telefon = "".join(_media("(max-width: 900px)"))
    assert ".nav-search input { font-size: 16px; }" in telefon and ".nav-search input { height: 44px; }" in telefon
    assert "#panel-auswertung .tabs [role=tab], #bt-bezirk, #nav-metric { min-height: 44px; font-size: 16px; }" in telefon
    # breite Bildschirme unverändert
    ohne = CSS
    for block in _media("(max-width: 900px)"):
        ohne = ohne.replace(block, "")
    assert "#bt-bezirk" not in ohne and "#nav-metric" not in ohne
    assert ".bt-pick select { min-height: 40px; }" in ohne and ".tabs [role=tab] {" in ohne and "font-size: 13px; }" in ohne


# --- (6) Fokus nach dem Öffnen eines Eintrags der Liste ----------------------------------------------------------------

def test_fokus_nach_eintrag_der_liste():
    """(6) Nach Enter auf einem Eintrag (Suchtreffer in ganz Köln oder Vorlage im Gebiet): der Eintrag selbst, wenn die
    Liste offen bleibt, sonst die Überschrift des Vorgangs; ein Suchtreffer erst, wenn das Gebiet geladen und der
    Vorgang gewählt ist."""
    teil = _teil(APP, r"^  function fokusNachListe\(ref\) \{\n.*?\n  \}\n")
    code = """
const doc = { activeElement: null };
const mk = (name, data, zuSehen) => ({ name, dataset: data, zuSehen, focus() { doc.activeElement = this; } });
let EINTRAEGE = [], TITEL = mk("titel", {}, true);
const document = { get activeElement() { return doc.activeElement; }, querySelectorAll: () => EINTRAEGE };
const $ = (s) => (s === "#detail h3" ? TITEL : null);
const sichtbarEl = (e) => Boolean(e && e.zuSehen);
""" + teil + """
const aus = [];
EINTRAEGE = [mk("a", { gref: "1/2026" }, true), mk("b", { gref: "2/2026" }, true)]; fokusNachListe("2/2026"); aus.push(doc.activeElement.name);
EINTRAEGE = [mk("c", { ref: "3/2026" }, false)]; fokusNachListe("3/2026"); aus.push(doc.activeElement.name);
EINTRAEGE = []; doc.activeElement = null; fokusNachListe("4/2026"); aus.push(doc.activeElement.name);
console.log(JSON.stringify(aus));
"""
    assert _node(code) == ["b", "titel", "titel"]
    klick = _teil(APP, r'^    \$\("#papers"\)\.addEventListener\("click", \(e\) => \{\n.*?\n    \}\);\n')
    assert ("openGlobal(ref, g.dataset.area).then(() => { if (selected?.reference === ref && fokusFrei()) fokusNachListe(ref); });" in klick)
    assert 'select(papers.find((p) => p.reference === b.dataset.ref)); fokusNachListe(b.dataset.ref);' in klick


def test_suchtreffer_nimmt_den_fokus_nur_wenn_er_frei_ist():
    """(6) nach der Prüfung von Pull Request 5: Nach dem Laden des Gebiets setzt ein Suchtreffer den Fokus nur, wenn er
    noch auf <body>, in der Liste der Treffer oder auf einem nicht mehr sichtbaren Element liegt (wie gremiumAusAdresse);
    wer inzwischen im Suchfeld weitertippt, behält ihn dort."""
    teil = _teil(APP, r"^  const fokusFrei = .*?;\n")
    code = """
const mk = (name, zuSehen = true, inListe = false) => ({ name, zuSehen, inListe });
const BODY = mk("body");
let aktiv = null;
const document = { body: BODY, get activeElement() { return aktiv; } };
const $ = () => ({ contains: (e) => Boolean(e && e.inListe) });
const sichtbarEl = (e) => Boolean(e && e.zuSehen);
""" + teil + """
const aus = [];
for (const a of [null, BODY, mk("treffer", true, true), mk("suchfeld"), mk("stichwort, Liste zu", false), mk("titel")]) { aktiv = a; aus.push(fokusFrei()); }
console.log(JSON.stringify(aus));
"""
    assert _node(code) == [True, True, True, False, True, False]


# --- (7) Blätter bei geringer Höhe -------------------------------------------------------------------------------------

def test_blaetter_bei_geringer_hoehe():
    """(7) Bei geringer Höhe (max-height: 480px, etwa 400 % Zoom, 320×256) rollen die Blätter „Vorlagen“ und „Vorgang“
    als Ganzes wie die Überlagerungen (23.11.2026 (2) (15)): Kopf und Filter rollen mit, der Inhalt rollt nicht für
    sich. Bei normaler Höhe unverändert. Ein neuer Vorgang beginnt oben, auch im ganzen Blatt."""
    niedrig = _media("(max-height: 480px)")
    assert len(niedrig) == 1
    for regel in ("#panel-list, #panel-detail { overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; }",
                  "#panel-list > *, #panel-detail > * { flex: none; }",
                  "#panel-list > .panel-body, #panel-detail > .panel-body { overflow: visible; }",
                  ".overlay { overflow-y: auto; overscroll-behavior: contain; }"):
        assert regel in niedrig[0], regel
    assert "#panel-list, #panel-detail {" not in CSS.replace(niedrig[0], "")
    assert '$("#detail").scrollTop = 0;' not in APP.replace(
        'const detailNachOben = () => { $("#detail").scrollTop = 0; $("#panel-detail").scrollTop = 0; };', "")
    assert APP.count("detailNachOben();") == 5


# --- (8) „Selbst mitwirken“ ohne benannten Bereich ---------------------------------------------------------------------

def test_selbst_mitwirken_ohne_landmarke():
    """(8) Der Abschnitt „Selbst mitwirken“ im Vorgang trägt kein aria-labelledby (kein benannter Bereich), die
    Überschrift bleibt, wie die Abschnitte in 23.11.2026 (2) (17)."""
    teil = "".join(_teil(APP, m) for m in (r"^  const esc = .*?;\n", r"^  const safeUrl = .*?;\n", r"^  const link = .*?;\n",
                                            r"^  const BUERGERANTRAG = .*?;\n", r"^  function participate\(p\) \{\n.*?\n  \}\n"))
    code = """
const heute = () => "2026-11-20", fmtDay = (d) => d, vorhanden = () => true, hasPaperFeed = () => false;
const zeit = { meetings: [] };
""" + teil + """
console.log(JSON.stringify(participate({ stand: "in Beratung", steps: [] })));
"""
    html = _node(code)
    assert html.startswith('<section class="participate"><h4>Selbst mitwirken</h4><ul>')
    assert "aria-labelledby" not in html and "aria-label=" not in html and 'role="region"' not in html
    assert "participate-h" not in APP


# --- #52, Punkt 4: Wahl in „Gremien und Ämter“, während gremien.js noch lädt -----------------------------------------

def test_init_uebernimmt_die_wahl_aus_dem_import():
    """gremien.js init übernimmt die Wahl, die app.js während des Imports angenommen hat (c.vorab), wie eine Wahl
    während des Ladens der Daten: Reiter und Umschalter zeigen sie sofort, nach dem Laden geht sie dem Reiter bzw. der
    Darstellung vor, mit denen die Fläche geöffnet wurde; ein späteres Öffnen gilt wieder. Ohne vorab wie bisher."""
    from test_wer_entscheidet_seite import _steuerung
    r = _steuerung("""
const laden = M.init({ ...ctx, vorab: { tab: "gremien", darstellung: "liste" } });
const beim = { reiter: gewaehlt(), tabindex: tabs.map((t) => t.tabIndex), radios: radios.map((b) => b.attrs["aria-checked"]), inhalt: body.gesetzt };
await freigeben(); await laden;
M.show({}); M.show({ tab: "aemter", darstellung: "schaubild" });
const danach = { zustand: M.werZustand(), liste: body.innerHTML.includes('id="wer-liste"') };
M.show({ tab: "aemter" });
ergebnis = { beim, danach, spaeter: M.werZustand().tab };
""")
    assert r == {"beim": {"reiter": "gremien", "tabindex": [0, -1], "radios": ["false", "true"], "inhalt": 0},
                 "danach": {"zustand": {"tab": "gremien", "darstellung": "liste", "kennung": None}, "liste": True},
                 "spaeter": "aemter"}
    r = _steuerung("""
const laden = M.init({ ...ctx, vorab: { tab: "aemter" } });
const beim = gewaehlt();
await freigeben(); await laden;
M.show({}); M.show({ tab: "gremien" });
ergebnis = { beim, danach: M.werZustand().tab, aemter: body.innerHTML.includes("wer-dezernat") };
""")
    assert r == {"beim": "aemter", "danach": "aemter", "aemter": True}
    r = _steuerung("""
await geladen();
M.show({}); M.show({ tab: "aemter" });
ergebnis = M.werZustand();
""")
    assert r == {"tab": "aemter", "darstellung": None, "kennung": None}


def test_init_zeigt_beim_laden_den_reiter_des_oeffnens():
    """Durchsicht zu #52, Punkt 4: init zeigt schon während des Ladens der Daten Reiter und Darstellung, mit denen app.js
    die Fläche öffnet (c.offen), ohne sie als Wahl zu zählen; eine Wahl aus dem Import (c.vorab) geht vor. Vorher stand
    bis zur ersten Wahl der Ausgangszustand („Gremien“ mit Umschalter), auch beim Öffnen über „Ämter“."""
    from test_wer_entscheidet_seite import _steuerung
    r = _steuerung("""
const laden = M.init({ ...ctx, offen: { tab: "aemter" } });
const beim = { reiter: gewaehlt(), schalter: schalter.hidden, bezug: body.attrs["aria-labelledby"], inhalt: body.gesetzt };
feuern("tablist", "click", tabs[1]);
await freigeben(); await laden;
M.show({}); M.show({ tab: "aemter" });
ergebnis = { beim, danach: M.werZustand(), aemter: body.innerHTML.includes("wer-dezernat") };
""")
    assert r == {"beim": {"reiter": "aemter", "schalter": True, "bezug": "tab-wer-aemter", "inhalt": 0},
                 "danach": {"tab": "aemter", "darstellung": None, "kennung": None}, "aemter": True}
    r = _steuerung("""
telefon = true;
const laden = M.init({ ...ctx, offen: { tab: "gremien" } });
const beim = { reiter: gewaehlt(), radios: radios.map((b) => [b.attrs["aria-checked"], b.tabIndex]), schalter: schalter.hidden };
await freigeben(); await laden;
M.show({}); M.show({ tab: "gremien" });
ergebnis = { beim, danach: M.werZustand(), liste: body.innerHTML.includes('id="wer-liste"') };
""")
    assert r == {"beim": {"reiter": "gremien", "radios": [["false", -1], ["true", 0]], "schalter": False},
                 "danach": {"tab": "gremien", "darstellung": None, "kennung": None}, "liste": True}
    r = _steuerung("""
const laden = M.init({ ...ctx, offen: { tab: "aemter" }, vorab: { tab: "gremien", darstellung: "liste" } });
const beim = gewaehlt();
await freigeben(); await laden;
M.show({}); M.show({ tab: "aemter" });
ergebnis = { beim, danach: M.werZustand() };
""")
    assert r == {"beim": "gremien", "danach": {"tab": "gremien", "darstellung": "liste", "kennung": None}}



def test_oeffnen_waehrend_des_ladens_der_daten():
    """Durchsicht zu #52, Punkt 4: Öffnet app.js die Fläche erneut, während die Daten noch laden (oeffnen), zeigen
    Reiter und Umschalter sofort den Reiter des Öffnens, und er geht einer früheren Wahl vor; eine Wahl danach gilt nach
    dem Laden (show einmal, für das letzte Öffnen). Vorher zeigte die Fläche bis zum Laden die frühere Wahl, und eine
    Wahl nach erneutem Öffnen ging verloren. Mit geladenen Daten keine Wirkung."""
    from test_wer_entscheidet_seite import _steuerung
    r = _steuerung("""
const laden = M.init({ ...ctx, offen: { tab: "gremien" } });
feuern("tablist", "click", tabs[1]);
M.oeffnen({ tab: "gremien" });
const beim = { reiter: gewaehlt(), schalter: schalter.hidden };
await freigeben(); await laden;
M.show({ tab: "gremien" });
ergebnis = { beim, danach: M.werZustand().tab };
""")
    assert r == {"beim": {"reiter": "gremien", "schalter": False}, "danach": "gremien"}
    r = _steuerung("""
const laden = M.init({ ...ctx, offen: { tab: "aemter" } });
M.oeffnen({ tab: "aemter" });
feuern("tablist", "click", tabs[0]);
feuern("schalter", "click", radios[1]);
const beim = gewaehlt();
await freigeben(); await laden;
M.show({ tab: "aemter" });
const danach = M.werZustand();
M.oeffnen({ tab: "aemter" });
ergebnis = { beim, danach, geladen: M.werZustand().tab };
""")
    assert r == {"beim": "gremien", "danach": {"tab": "gremien", "darstellung": "liste", "kennung": None}, "geladen": "gremien"}

def _vorab(ablauf):
    """openGremien und werVorabBedienen aus app.js mit nachgebildetem Dokument (Reiter, Umschalter, Inhalt) und
    Importen von Hand (`importe` je Aufruf mit ja/nein, Adressen in `adressen`, init merkt sich c.vorab in `inits` und
    c.offen in `offene`)."""
    teil = _teil(APP, r"^  const WARTEZEIT = .*?;\n") + _teil(APP, r"^  const mitFrist = .*?\n  \}\);\n") \
        + _teil(APP, r"^  let werState = null, werReady = null, werModul = null, werImportFehler = 0;\n.*?^  function openGremien\(s\) \{\n.*?\n  \}\n") \
        + _teil(APP, r"^  function werVorabBedienen\(\) \{\n.*?\n  \}\n") \
        + _teil(APP, r'^  if \(vorhanden\("panel-gremien"\)\) werVorabBedienen\(\);\n')
    assert teil.count("import(modul)") == 1
    code = """
const handler = {};
let aktiv = null;
const knoten = (name, extra = {}) => ({ name, hidden: false, attrs: {}, tabIndex: 0, dataset: {}, textContent: "", innerHTML: "",
  setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] ?? null; },
  addEventListener(typ, f) { (handler[name + ":" + typ] ||= []).push(f); }, focus() { aktiv = this; }, closest() { return null; }, ...extra });
const tabs = ["gremien", "aemter"].map((t, i) => knoten("tab-" + t, { dataset: { werTab: t }, attrs: { "aria-selected": String(!i) }, tabIndex: i ? -1 : 0,
  closest(s) { return s === "[role=tab][data-wer-tab]" ? this : null; } }));
const radios = ["schaubild", "liste"].map((d, i) => knoten("radio-" + d, { dataset: { darstellung: d }, attrs: { "aria-checked": String(!i) }, tabIndex: i ? -1 : 0,
  closest(s) { return s === "[data-darstellung]" ? this : null; } }));
const tabliste = knoten("tablist", { querySelectorAll: () => tabs });
const schalter = knoten("schalter", { querySelectorAll: () => radios });
const E = { "#wer-body": knoten("body"), "#wer-status": knoten("status"),
  "#panel-gremien": knoten("root", { querySelector: (s) => ({ "[role=tablist]": tabliste, ".wer-darstellung": schalter })[s] }) };
const $ = (s) => E[s];
let funktionen = { gremien: true };
const vorhanden = () => true, BONN = "data/", heute = () => "2026-11-24", zeitDatum = (s) => s, lizenzOeffentlich = (t) => t;
const MOBILE = { matches: false }, syncUrl = () => {}, gremiumFiltern = () => {};
const adressen = [], importe = [], inits = [], gezeigt = [];
const offene = [];
const modul = (nr) => ({ show: (s) => gezeigt.push([nr, s]), async init(c) { inits.push([nr, c.vorab]); offene.push([nr, c.offen]); } });
const importieren = (u) => { adressen.push(u); return new Promise((ja, nein) => importe.push({ ja, nein })); };
const feuern = (name, typ, e) => (handler[name + ":" + typ] || []).forEach((f) => f({ preventDefault() { this.verhindert = true; }, ...e }));
const taste = (name, key) => { const e = { key, verhindert: false, preventDefault() { e.verhindert = true; } }; (handler[name + ":keydown"] || []).forEach((f) => f(e)); return e.verhindert; };
const bild = () => ({ tabs: tabs.map((t) => [t.attrs["aria-selected"], t.tabIndex]), radios: radios.map((b) => [b.attrs["aria-checked"], b.tabIndex]),
  schalter: !schalter.hidden, body: E["#wer-body"].attrs["aria-labelledby"] || null, fokus: aktiv ? aktiv.name : null });
const warten = () => new Promise((r) => setTimeout(r, 5));
""" + teil.replace("import(modul)", "importieren(modul)") + """
(async () => {
  let ergebnis = null;
""" + ablauf + """
  console.log(JSON.stringify(ergebnis));
})();
"""
    return _node(code)


def test_wahl_waehrend_des_imports_gilt_nach_dem_laden():
    """#52, Punkt 4: Klick oder Taste an Reiter und Umschalter, während gremien.js noch lädt, gingen verloren (die
    Bedienung meldet erst init an). app.js zeigt beim Öffnen schon den Reiter des Öffnens (über „Ämter“ ohne Umschalter;
    Durchsicht), nimmt die Wahl an, zeigt sie sofort (aria-selected bzw. aria-checked, tabindex, Umschalter nur im
    Reiter „Gremien“, Fokus wandert mit Pfeil, Pos1 und Ende) und gibt sie init mit, dazu den Reiter des Öffnens
    (offen); ein Klick auf den schon angezeigten Reiter ändert nichts. Nach dem Laden zeigt nur das letzte Öffnen
    während des Imports (show einmal). Ist das Modul geladen, wirkt nur noch es."""
    r = _vorab("""
  openGremien(); const offen = openGremien({ tab: "aemter" });
  const nachOeffnen = bild();
  feuern("tablist", "click", { target: tabs[1] });
  const nachAemter = bild();
  feuern("tablist", "click", { target: tabs[0] });
  const pfeil = taste("schalter", "ArrowRight");
  const nachTasten = bild();
  importe[0].ja(modul(1));
  await offen;
  feuern("tablist", "click", { target: tabs[1] });
  const geladen = [taste("tablist", "ArrowRight"), taste("schalter", "Home"), bild()];
  openGremien({ tab: "gremien" }); await warten();
  ergebnis = { nachOeffnen, nachAemter, nachTasten, pfeil, inits, offene, gezeigt, geladen, adressen };
""")
    aemter = {"tabs": [["false", -1], ["true", 0]], "radios": [["true", 0], ["false", -1]], "schalter": False,
              "body": "tab-wer-aemter", "fokus": None}
    assert r["nachOeffnen"] == aemter and r["nachAemter"] == aemter
    assert r["pfeil"] is True
    assert r["nachTasten"] == {"tabs": [["true", 0], ["false", -1]], "radios": [["false", -1], ["true", 0]], "schalter": True,
                               "body": "tab-wer-gremien", "fokus": "radio-liste"}
    assert r["inits"] == [[1, {"tab": "gremien", "darstellung": "liste"}]] and r["offene"] == [[1, {"tab": "aemter"}]]
    assert r["gezeigt"] == [[1, {"tab": "aemter"}], [1, {"tab": "gremien"}]]
    # nach dem Import: keine Wirkung mehr aus app.js (Tasten nicht abgefangen, Anzeige wie vorher)
    assert r["geladen"] == [False, False, r["nachTasten"]] and r["adressen"] == ["./gremien.js"]


def test_wahl_beim_neuen_versuch_nach_gescheitertem_import():
    """#52, Punkt 4, neuer Versuch: Eine Wahl während eines gescheiterten Imports gilt nicht für den nächsten Versuch
    (wie init beimLaden zurücksetzt), ohne laufenden Import (Satz zum Ladefehler) nimmt app.js keine Wahl an; beim
    neuen Versuch unter ?versuch=1 gilt die Wahl wieder. Reiter und Umschalter zeigen beim neuen Versuch wieder den
    Zustand des Öffnens (Durchsicht: vorher stand dort noch die Wahl aus dem gescheiterten Versuch)."""
    r = _vorab("""
  const erst = openGremien({ tab: "gremien" });
  feuern("schalter", "click", { target: radios[1] });
  importe[0].nein(new Error("Netz"));
  await erst;
  const fehler = E["#wer-status"].textContent;
  const ohneImport = [taste("tablist", "End"), bild().tabs];
  const zweit = openGremien({ tab: "gremien" });
  const beimZweiten = bild();
  const mitImport = taste("tablist", "End");
  importe[1].ja(modul(2));
  await zweit;
  ergebnis = { fehler, ohneImport, beimZweiten, mitImport, inits, adressen };
""")
    assert r["fehler"].startswith("Die Angaben zu Gremien und Ämtern konnten nicht geladen werden.")
    assert r["ohneImport"] == [False, [["true", 0], ["false", -1]]] and r["mitImport"] is True
    assert r["beimZweiten"] == {"tabs": [["true", 0], ["false", -1]], "radios": [["true", 0], ["false", -1]], "schalter": True,
                                "body": "tab-wer-gremien", "fokus": None}
    assert r["inits"] == [[2, {"tab": "aemter"}]]
    assert r["adressen"] == ["./gremien.js", "./gremien.js?versuch=1"]



def test_app_oeffnet_beim_laden_der_daten_ueber_gremien_js():
    """Durchsicht zu #52, Punkt 4: Ist das Modul importiert und laden die Daten noch, gibt openGremien das Öffnen an
    gremien.js weiter (oeffnen) und zeigt nach dem Laden nur das letzte Öffnen; mit geladenen Daten wie bisher jedes."""
    r = _vorab("""
  let fertig;
  const geoeffnet = [];
  const m = { show: (s) => gezeigt.push([1, s]), oeffnen: (s) => geoeffnet.push(s), init: () => new Promise((ok) => { fertig = ok; }) };
  openGremien(); openGremien({ tab: "gremien" });
  importe[0].ja(m); await warten();
  openGremien(); const zweit = openGremien({ tab: "aemter" });
  const anzeige = bild().tabs;
  fertig(); await zweit;
  openGremien(); await openGremien({ tab: "gremien" });
  ergebnis = { geoeffnet, anzeige, gezeigt };
""")
    assert r == {"geoeffnet": [{"tab": "aemter"}], "anzeige": [["true", 0], ["false", -1]],
                 "gezeigt": [[1, {"tab": "aemter"}], [1, None], [1, {"tab": "gremien"}]]}

def test_oeffnen_waehrend_des_imports_zeigt_was_danach_gilt():
    """Durchsicht zu #52, Punkt 4: Während des Imports zeigen Reiter und Umschalter, was nach dem Laden gilt. Ein
    späteres Öffnen geht einer früheren Wahl des Reiters vor; eine Wahl nach erneutem Öffnen gilt (nach dem Laden zeigt
    nur das letzte Öffnen; vorher verbrauchte das erste die Wahl, das zweite setzte seinen Reiter darüber). Auf dem
    Telefon zeigt der Umschalter die Liste, wie gremien.js ohne Wahl. Die Darstellung aus der Adresse gilt wie eine
    Vorgabe."""
    r = _vorab("""
  openGremien(); openGremien({ tab: "gremien" });
  feuern("tablist", "click", { target: tabs[1] });
  const gewaehlt = bild();
  openGremien(); const zweit = openGremien({ tab: "gremien" });
  const wieder = bild();
  importe[0].ja(modul(1));
  await zweit;
  ergebnis = { gewaehlt, wieder, inits, offene, gezeigt };
""")
    assert r["gewaehlt"]["tabs"] == [["false", -1], ["true", 0]] and r["gewaehlt"]["schalter"] is False
    assert r["wieder"]["tabs"] == [["true", 0], ["false", -1]] and r["wieder"]["schalter"] is True
    assert r["inits"] == [[1, {}]] and r["offene"] == [[1, {"tab": "gremien"}]] and r["gezeigt"] == [[1, {"tab": "gremien"}]]
    r = _vorab("""
  openGremien(); openGremien({ tab: "aemter" });
  openGremien(); const zweit = openGremien({ tab: "aemter" });
  feuern("tablist", "click", { target: tabs[0] });
  feuern("schalter", "click", { target: radios[1] });
  const beim = bild();
  importe[0].ja(modul(1));
  await zweit;
  ergebnis = { beim, inits, gezeigt };
""")
    assert r["beim"]["tabs"] == [["true", 0], ["false", -1]] and r["beim"]["radios"] == [["false", -1], ["true", 0]]
    assert r["inits"] == [[1, {"tab": "gremien", "darstellung": "liste"}]] and r["gezeigt"] == [[1, {"tab": "aemter"}]]
    r = _vorab("""
  MOBILE.matches = true;
  openGremien(); openGremien({ tab: "gremien" });
  const telefon = bild().radios;
  MOBILE.matches = false;
  openGremien(); openGremien({ tab: "gremien", darstellung: "liste", kennung: "rat", zeigen: true });
  const adresse = bild().radios;
  ergebnis = { telefon, adresse, adressen };
""")
    assert r == {"telefon": [["false", -1], ["true", 0]], "adresse": [["false", -1], ["true", 0]], "adressen": ["./gremien.js"]}
