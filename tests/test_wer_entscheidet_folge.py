"""Folge zu Pull Request 4b (Entscheidung 23.11.2026 (2), Punkte 1–17 aus #50, jeweils Empfehlung A): Datenbeschreibungen
mit `folgende_sitzung`, Satz am Knopf „Vorlagen dieses Gremiums“, vergangene bekannte Sitzungen, „Tagesordnung noch nicht
veröffentlicht“, Schluss des Hinweises bei nicht aktueller Liste, „Gremium (nach Namen)“, Zusatz am Link im Vorgang,
Einleitung im Reiter „Ämter“, Quellenzeile, Parameter `gremium_filter`, Wartezeit beim Laden, Esc im Suchfeld,
fehlender Suchindex, `kennung` bei mehreren offenen Einträgen, geringe Höhe, Telefonbreite und Abschnitte ohne Namen.
Geprüft ohne Browser (node mit nachgebildetem Dokument oder als Modul, Python); die Prüfung im Browser steht in
tests/browser/gremien.js (Abschnitt FOLGE). Alle Gremien, Kennungen, Vorlagen und Adressen sind erfunden; keine
Anfragen nach außen."""
import json
import re
from pathlib import Path

from pipeline import config, gremien, paket, publish, seo
from test_wer_entscheidet_seite import (APP, GREMIEN_JS, INDEX, SELECT, _abschnitt, _modul, _node, _steuerung, _teil,
                                        _text)

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
BETEILIGUNG = (ROOT / "site" / "beteiligung.js").read_text(encoding="utf-8")


# --- (1) folgende_sitzung in DCAT, LIESMICH und LICENSE-DATA.md -----------------------------------------------------

def test_folgende_sitzung_in_den_datenbeschreibungen(tmp_path, monkeypatch):
    """(1) Das Feld folgende_sitzung von gremien.json steht wie die nächste Sitzung in der Beschreibung der Verteilung
    „Gremien (JSON)“ im DCAT-Katalog, in LIESMICH.txt (paket.LIESMICH_GREMIEN) und in der Zeile von gremien.json in
    data/LICENSE-DATA.md, jeweils mit der Bedingung (nur, wenn die nächste am Tag des Datenstands liegt); die Datei trägt
    den Stand 23.11.2026."""
    assert "folgende_sitzung" in gremien.FELDER and "naechste_sitzung" in gremien.FELDER
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", True)
    (tmp_path / "gremien.json").write_text("{}")
    publish.write_dcat(tmp_path / "dcat.jsonld", None, "2026-11-23", orte=set())
    dcat = json.loads((tmp_path / "dcat.jsonld").read_text(encoding="utf-8"))
    (gr,) = [d for d in dcat["dcat:distribution"] if d["dct:title"]["@value"] == "Gremien (JSON)"]
    assert gr["dct:description"]["@value"].endswith(
        "Sitzungen und Vorlagen in 12 Monaten, nächste Sitzung und, wenn diese am Tag des Datenstands liegt, die folgende "
        "Sitzung (abgeleitet).")
    liesmich = " ".join(paket.LIESMICH_GREMIEN.split())
    assert ("mit Sitzungen und Vorlagen in 12 Monaten, nächster Sitzung und, wenn diese am Tag des Datenstands liegt, "
            "folgender Sitzung (abgeleitet)") in liesmich
    assert all(len(z) <= 120 for z in paket.LIESMICH_GREMIEN.splitlines())
    lizenz = (ROOT / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8")
    zeile = next(z for z in lizenz.splitlines() if z.startswith("| `export/koeln/gremien.json`"))
    assert ("Sitzungen und Vorlagen in 12 Monaten, nächste Sitzung und, wenn diese am Tag des Datenstands liegt, folgende "
            "Sitzung eigene Ableitung") in zeile
    assert lizenz.splitlines()[2].startswith("Stand 23.11.2026. ")
    # README und Technikseite führen keine Feldliste von gremien.json (nur die Herkunft des Paragrafen)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "nächste Sitzung" not in readme and "naechste_sitzung" not in readme


# --- (2)–(5), (8), (17) Modul site/gremien.js -------------------------------------------------------------------------

SATZ_JAHRE = "Die Liste zeigt die Vorlagen aller Jahre; die Zahl oben zählt nur die 12 Monate."


def test_satz_am_knopf_vorlagen_dieses_gremiums():
    """(2) Neben „Vorlagen dieses Gremiums“ steht ein Satz, dass der Knopf alle Jahre zeigt und die Zahl darüber 12
    Monate zählt; aria-describedby verbindet beide (id mit der Kennung, in der Liste je Eintrag eindeutig). Frühere
    Gremien haben weder Knopf noch Satz (E4)."""
    rat, alt = _modul("[M.gremiumInhalt(G.gremien[0], G.meta, U), M.gremiumInhalt(G.gremien[4], G.meta, U)]")
    assert ('aria-describedby="wer-jahre-rat">Vorlagen dieses Gremiums<span class="visually-hidden">: Beispielrat</span></button>'
            f'\n      <span class="hint wer-jahre" id="wer-jahre-rat">{SATZ_JAHRE}</span></p>') in rat
    assert rat.index("In den 12 Monaten vom") < rat.index(SATZ_JAHRE)
    assert "wer-jahre" not in alt and "wer-filter" not in alt
    liste = _modul("M.listenteil(G, { kennung: null, q: '', frueher: true }, U)")
    ids = re.findall(r'id="(wer-jahre-[\w-]+)"', liste)
    assert ids == ["wer-jahre-rat", "wer-jahre-aus-a", "wer-jahre-bv1", "wer-jahre-beirat"] and len(set(ids)) == len(ids)
    for i in ids:
        assert liste.count(f'aria-describedby="{i}"') == 1


def test_bekannte_sitzungen_vorbei():
    """(3) Ist die Liste der Sitzungen aktuell, aber liegt jede bekannte Sitzung (nächste und folgende) vor dem Kölner
    Tag der Besucher:innen, steht ein Satz statt nichts; mit einer kommenden Sitzung diese, ohne bekannte Sitzung nichts,
    bei nicht aktueller Liste deren Hinweis. Die Kurzzeile bleibt ohne Satz."""
    vorbei, kommend, ohne, alt_liste, kurz = _modul(
        "[M.gremiumInhalt(G.gremien[0], G.meta, { ...U, heute: '2026-12-02' }), M.gremiumInhalt(G.gremien[0], G.meta, { ...U, heute: '2026-11-24' }), "
        "M.gremiumInhalt(G.gremien[2], G.meta, { ...U, heute: '2026-12-02' }), "
        "M.gremiumInhalt(G.gremien[0], { ...G.meta, sitzungsliste_nicht_aktuell: { stand: null } }, { ...U, heute: '2026-12-02' }), "
        "M.kurzzeile(G.gremien[0], G.meta, '2026-12-02')]")
    satz = "<li>Die bekannten Sitzungen sind vorbei; der nächste Abruf ergänzt die Liste der Sitzungen.</li>"
    assert satz in vorbei and "Nächste Sitzung:" not in vorbei
    assert satz not in kommend and "Nächste Sitzung: Di., 01.12.2026" in kommend
    assert "vorbei" not in ohne and "Nächste Sitzung" not in ohne
    assert "vorbei" not in alt_liste and "deshalb fehlt die nächste Sitzung" in alt_liste
    assert kurz == "" and _modul("[M.sitzungenVorbei({ naechste_sitzung: { date: 'kaputt' } }, '2026-12-02'), "
                                 "M.sitzungenVorbei({ naechste_sitzung: { date: '2026-12-02' } }, '2026-12-02')]") == [False, False]


def test_ohne_tagesordnung_derselbe_satz_wie_in_aktuell_und_termine():
    """(4) Fehlt der Link zur Tagesordnung der gezeigten nächsten Sitzung, steht „Tagesordnung noch nicht
    veröffentlicht“, derselbe Wortlaut wie in „Aktuell in Köln“ (app.js) und „Kommende Sitzungen“ der Fläche „Mitmachen
    in Köln“ (beteiligung.js); mit Link bleibt der Link."""
    ohne, mit = _modul("[M.gremiumInhalt(G.gremien[1], G.meta, U), M.gremiumInhalt(G.gremien[0], G.meta, U)]")
    satz = " · Tagesordnung noch nicht veröffentlicht"
    assert f"Nächste Sitzung: Mo., 30.11.2026{satz}</li>" in ohne
    assert satz not in mit and ">Tagesordnung<span" in mit
    assert f'{satz}"' in BETEILIGUNG and f'{satz}"' in APP


def test_hinweis_nicht_aktuelle_liste_schluss():
    """(5) Der Hinweis bei nicht aktueller Liste endet auf „; deshalb fehlt die nächste Sitzung.“ (vorher „, eine
    nächste Sitzung deshalb nicht.“); der übrige Satz bleibt."""
    mit, ohne = _modul("[M.sitzungslisteText({ sitzungsliste_nicht_aktuell: { stand: 'x' } }, (s) => 'T(' + s + ')'), "
                       "M.sitzungslisteText({ sitzungsliste_nicht_aktuell: {} }, String)]")
    assert mit == ("Die Liste der Sitzungen wurde beim letzten Abruf nicht aktualisiert; gezeigt wird der Stand vom T(x); "
                   "deshalb fehlt die nächste Sitzung.")
    assert ohne.endswith("gezeigt wird der letzte gültige Stand; deshalb fehlt die nächste Sitzung.")
    assert "eine nächste Sitzung deshalb nicht" not in GREMIEN_JS.read_text(encoding="utf-8")


def test_aemter_einleitung_ohne_untereinheiten():
    """(8) Die Einleitung im Reiter „Ämter“ sagt, dass die Untereinheiten der Dienststellen fehlen, ohne feste Zahl
    (aemter.json nennt keine)."""
    html = _modul("M.inhaltAemter(A)")
    einleitung = re.search(r'<p class="hint">Aufbau der Stadtverwaltung:[^<]*</p>', html).group(0)
    assert einleitung == ('<p class="hint">Aufbau der Stadtverwaltung: Dezernate mit ihren Einheiten, Dienststellen und '
                          'Punktdienststellen, ohne die Untereinheiten der Dienststellen.</p>')
    assert not re.search(r"\d", einleitung)


def test_abschnitte_ohne_namen_keine_landmarken():
    """(17) Die Abschnitte der Gruppen im Schaubild und der Dezernate im Reiter „Ämter“ tragen kein aria-labelledby
    (und keinen anderen Namen), sind also keine Landmarken; die Überschriften h3 bleiben in derselben Reihenfolge."""
    bild, aemter = _modul("[M.inhaltGremien(G, { kennung: null, q: '', frueher: false }, 'schaubild', U), M.inhaltAemter(A)]")
    for html in (bild, aemter):
        assert "aria-labelledby" not in html and "aria-label=" not in html and 'role="region"' not in html
        assert re.findall(r"<section[^>]*>", html) and all(re.fullmatch(r'<section class="[\w -]+">', s) for s in re.findall(r"<section[^>]*>", html))
    assert re.findall(r"<h3[^>]*>([^<]+)</h3>", bild)[:4] == ["Rat", "Ausschüsse mit Paragraf der Zuständigkeitsordnung",
                                                              "Bezirksvertretungen", "Übrige Gremien"]
    assert re.findall(r"<h3[^>]*>([^<]+)</h3>", aemter) == ["Dezernat OB", "Dezernat IX – Beispiele", "Ohne Zuordnung (im Plan „●“)"]


# --- (6) Filter über den Namen ---------------------------------------------------------------------------------------

FILTER_TEILE = (r"^  const esc = .*?;\n", r"^  const GREMIUM_NAME = .*?;\n", r"^  const gremiumArt = .*?;\n",
                r"^  function gremiumWahl\(\) \{\n.*?\n  \}\n", r"^  function fillGremien\(\) \{\n.*?\n  \}\n",
                r"^  function gremiumKennzeichen\(\) \{\n.*?\n  \}\n")
PAPERS = [{"reference": "1/2026", "process": [{"gremium": "Beispielrat", "gremium_key": "rat"}, {"gremium": "Früherer Probeausschuss"}]},
          {"reference": "2/2026", "process": [{"gremium": "Ausschuss für Beispiele", "gremium_key": "aus-a"}]},
          {"reference": "3/2026", "process": [{"gremium": "Ausschuss für Beispiele"}]}]


def test_kennzeichen_und_count_nach_namen():
    """(6) Ein Filter über den Namen (Wert „name:…“, Gruppe „nach Namen, auch frühere Gremien“) heißt im Kennzeichen
    „Gremium (nach Namen)“, über die Kennung weiter „Gremium“; #count im Gebiet und in ganz Köln nennt dieselbe
    Bezeichnung."""
    teil = "".join(_teil(APP, m) for m in FILTER_TEILE)
    code = SELECT + f"""
const sel = new Sel(), box = {{ hidden: true }}, name = {{ textContent: "" }}, art = {{ textContent: "" }};
const E = {{ "#f-gremium": sel, "#gremium-filter": box, "#gremium-filter-name": name, "#gremium-filter-art": art }};
const $ = (s) => E[s];
let papers = {json.dumps(PAPERS)};
""" + teil + """
fillGremien();
const aus = [];
for (const v of ["name:Früherer Probeausschuss", "rat", "name:Ausschuss für Beispiele"]) { sel.value = v; gremiumKennzeichen(); aus.push([art.textContent, name.textContent, box.hidden]); }
console.log(JSON.stringify(aus));
"""
    assert _node(code) == [["Gremium (nach Namen)", "Früherer Probeausschuss", False], ["Gremium", "Beispielrat", False],
                           ["Gremium (nach Namen)", "Ausschuss für Beispiele", False]]
    kennzeichen = _abschnitt(INDEX, "gremium-filter")
    assert '<span><span id="gremium-filter-art">Gremium</span>: <strong id="gremium-filter-name"></strong></span>' in kennzeichen
    render = _teil(APP, r"^  function render\(nurListe\) \{\n.*?\n  \}\n")
    glob = _teil(APP, r"^  function renderGlobal\(nurListe\) \{\n.*?\n  \}\n")
    assert "· ${gremiumArt(gw)}: ${gw.text}" in render and "· ${gremiumArt(gw)}: ${gw.text}" in glob
    assert "· Gremium: ${" not in render and "· Gremium: ${" not in glob
    import test_wer_entscheidet_seite as ws
    nach_name = ws._global(ws.SUCHE, "name:Ausschuss für Beispiele", "Ausschuss für Beispiele")
    assert nach_name["count"] == "3 Treffer in ganz Köln · Gremium (nach Namen): Ausschuss für Beispiele"
    assert nach_name["art"] == "Gremium (nach Namen)"
    assert ws._global(ws.SUCHE, "rat", "Beispielrat")["count"] == "2 Treffer in ganz Köln · Gremium: Beispielrat"


# --- (7) Link im Vorgang ---------------------------------------------------------------------------------------------

def test_link_im_vorgang_sagt_wohin():
    """(7) Der Link vom Schritt zum Gremium trägt den unsichtbaren Zusatz „(unter „Gremien“)“ (Klasse visually-hidden):
    Der zugängliche Name sagt, wohin er führt; sichtbar bleibt der Name. Ohne Kennung kein Link und kein Zusatz."""
    import test_navigation_koeln as nk
    s = {"typ": "beratung", "label": "Beispielausschuss", "status": "belegt", "date": "2026-11-20", "role": "Vorberatung"}
    mit, ohne = nk._schritte([{**s, "gremium_key": "beispielausschuss"}, s])
    knopf = re.search(r'<button type="button" class="link-btn" data-gremium-key="beispielausschuss">.*?</button>', mit).group(0)
    assert knopf.endswith('>Beispielausschuss<span class="visually-hidden"> (unter „Gremien“)</span></button>')
    assert _text(knopf) == "Beispielausschuss (unter „Gremien“)" and "unter „Gremien“" not in ohne
    assert ".visually-hidden" in CSS


# --- (9) Quellenzeile ------------------------------------------------------------------------------------------------

def test_quellenzeile_reiter_aemter_vor_der_federfuehrung(monkeypatch):
    """(9) „im Reiter „Ämter““ steht vor „zur federführenden Dienststelle“ und kann sich nicht mehr auf die Technikseite
    beziehen; alle Angaben der bisherigen Zeile bleiben (Plan ohne Lizenz, nur Nummern und Bezeichnungen, Federführung
    nur für Vorlagen aus der Zeit vom Stand bis zur letzten Prüfung, beides auf der Technikseite). Ohne Freigabe fällt
    nur der Teil zum Reiter weg."""
    an = _text(_abschnitt(INDEX, "sources"))
    erwartet = ("Dezernate und Dienststellen aus dem Geschäfts- und Dezernatsverteilungsplan der Stadt Köln (im Plan keine "
                "Lizenz angegeben, übernommen sind nur Nummern und Bezeichnungen): im Reiter „Ämter“ unter „Wer entscheidet“ "
                "und zur federführenden Dienststelle, nur für Vorlagen aus der Zeit vom Stand des Plans bis zu seiner letzten "
                "Prüfung (Stand und letzte Prüfung auf der Seite „So funktioniert der Ratsatlas“) · Paragrafen der Ausschüsse")
    assert erwartet in an
    assert an.index("im Reiter „Ämter“") < an.index("zur federführenden Dienststelle") < an.index("So funktioniert")
    assert "beides auf der Seite" not in an
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    aus = _text(_abschnitt(seo.ohne_abgeschaltete(INDEX), "sources"))
    assert ("übernommen sind nur Nummern und Bezeichnungen): zur federführenden Dienststelle, nur für Vorlagen") in aus
    assert "Reiter „Ämter“" not in aus


# --- (10) Parameter gremium_filter -----------------------------------------------------------------------------------

def _sync_filter(wert, pz=None):
    """syncUrl aus app.js mit nachgebildeter Adresse und Wert von #f-gremium; Ergebnis: Parameter und Suchteil."""
    teil = _teil(APP, r"^  function syncUrl\(\) \{\n.*?\n  \}\n")
    code = f"""
const STADT = "koeln", KX = {{}}, PX = {{}}, EX = {{}}, kxOn = new Set();
let area = {{ kind: "ortsteil", key: "probe" }}, tl = null, range = null, colorBy = "", navMetric = "a", navDefault = "a";
let planOn = false, shownPlan = null, bauOn = false, shownSite = null, selected = null, sdModul = null, mmState = null;
const pzState = {json.dumps(pz)}, werState = null;
const P = {{ "panel-prozesse": {{ hidden: {json.dumps(pz is None)} }}, "panel-gremien": {{ hidden: true }} }};
const E = {{ "#f-theme": {{ value: "" }}, "#f-party": {{ value: "" }}, "#f-gremium": {{ value: {json.dumps(wert)} }} }};
const $ = (s) => E[s] || P[s.slice(1)];
const vorhanden = (id) => id in P, scope = () => "gebiet";
let adresse = "";
const location = {{ href: "https://example.invalid/?gremium_filter=alt&gremium=bonn" }};
const history = {{ replaceState: (a, b, u) => {{ adresse = u.search; }} }};
""" + teil + """
syncUrl();
console.log(JSON.stringify([Object.fromEntries(new URLSearchParams(adresse)), adresse]));
"""
    return _node(code)


def test_gremium_filter_in_der_adresse_schreiben():
    """(10) syncUrl schreibt den Wert des Filters „Gremium“ als eigenen Parameter gremium_filter (nie den Bonner Namen
    „gremium“): Kennung oder „name:“ mit Namen, kodiert; ohne Filter fehlt er. Die Bonner Parameter bleiben der Bonner
    Fläche (hier ohne sie gelöscht)."""
    k, k_roh = _sync_filter("rat")
    assert k == {"gebiet": "ortsteil:probe", "gremium_filter": "rat"} and "gremium=" not in k_roh.replace("gremium_filter=", "")
    n, n_roh = _sync_filter("name:Ausschuss für Beispiele & Probe")
    assert n["gremium_filter"] == "name:Ausschuss für Beispiele & Probe"
    assert "gremium_filter=name%3AAusschuss+f%C3%BCr+Beispiele+%26+Probe" in n_roh
    assert _sync_filter("")[0] == {"gebiet": "ortsteil:probe"}


def _aus_adresse(ablauf, papers=PAPERS, gremien_json=None, da=True):
    """gremiumAusAdresse aus app.js mit erfundenen Vorlagen; fetch liefert `gremien_json` (None: HTTP 404)."""
    teil = "".join(_teil(APP, m) for m in FILTER_TEILE) + _teil(APP, r"^  let gremiumUnbekannt = false;\n") \
        + _teil(APP, r"^  const GREMIUM_UNBEKANNT = .*?;\n") + _teil(APP, r"^  const mitGremiumHinweis = .*?;\n") \
        + _teil(APP, r"^  async function gremiumAusAdresse\(wert\) \{\n.*?\n  \}\n")
    code = SELECT + f"""
class Option {{ constructor(t, v) {{ this.textContent = t; this.value = v; }} }}
Sel.prototype.appendChild = function (o) {{ this.opts.push(o); }};
const sel = new Sel(), box = {{ hidden: true }}, name = {{ textContent: "" }}, art = {{ textContent: "" }};
const E = {{ "#f-gremium": sel, "#gremium-filter": box, "#gremium-filter-name": name, "#gremium-filter-art": art }};
const $ = (s) => E[s];
const BONN = "data/", werDa = () => {json.dumps(da)}, abrufe = [];
globalThis.fetch = async (u) => {{ abrufe.push(u); const d = {json.dumps(gremien_json)}; return {{ ok: Boolean(d), status: d ? 200 : 404, json: async () => d }}; }};
let papers = {json.dumps(papers)};
""" + teil + """
fillGremien();
(async () => {
  const aus = {};
""" + ablauf + """
  console.log(JSON.stringify(aus));
})();
"""
    return _node(code)


def test_gremium_filter_aus_der_adresse_lesen():
    """(10) Beim Laden: Eine Kennung mit Station im Gebiet setzt den Filter ohne Abruf; sonst liefert gremien.json den
    Namen (nur mit Freigabe „gremien“); ein Name („name:“) gilt, wie er ist, auch ohne Station, in seiner Gruppe. Eine
    unbekannte Kennung setzt keinen Filter, #count sagt das wie bei der unbekannten Kennung unter „Gremien“; kein
    Absturz, auch ohne Freigabe (dann ohne Abruf und ohne „unter „Gremien““)."""
    g = {"gremien": [{"key": "bv9", "name": "Bezirksvertretung 9 (Probe)"}]}
    r = _aus_adresse("""
  await gremiumAusAdresse("aus-a"); gremiumKennzeichen(); aus.gebiet = [sel.value, art.textContent, abrufe.length, name.textContent];
  await gremiumAusAdresse("bv9"); aus.datei = [sel.value, gremiumKennzeichen().text, abrufe.slice(), sel.innerHTML.indexOf("bv9") < sel.innerHTML.indexOf("nach Namen")];
  await gremiumAusAdresse("name:Probefraktion"); gremiumKennzeichen(); aus.name = [sel.value, art.textContent, name.textContent, sel.innerHTML.indexOf("Probefraktion") > sel.innerHTML.indexOf("nach Namen")];
  aus.vorher = [gremiumUnbekannt, mitGremiumHinweis("3 von 9 Vorlagen · Probe")];
  sel.value = ""; await gremiumAusAdresse("gibt-es-nicht"); aus.unbekannt = [sel.value, gremiumUnbekannt, mitGremiumHinweis("3 von 9 Vorlagen · Probe"), mitGremiumHinweis("Ganz Köln: oben wählen.")];
""", gremien_json=g)
    assert r["gebiet"] == ["aus-a", "Gremium", 0, "Ausschuss für Beispiele"]
    assert r["datei"] == ["bv9", "Bezirksvertretung 9 (Probe)", ["data/gremien.json"], True]
    assert r["name"] == ["name:Probefraktion", "Gremium (nach Namen)", "Probefraktion", True]
    assert r["vorher"] == [False, "3 von 9 Vorlagen · Probe"]
    satz = ("Das Gremium aus dem Link ist unter „Gremien“ nicht verzeichnet; seine Kennung kann sich geändert haben. "
            "Die Liste ist nicht nach Gremium gefiltert.")
    assert r["unbekannt"] == ["", True, f"3 von 9 Vorlagen · Probe · {satz}", f"Ganz Köln: oben wählen. {satz}"]
    ohne = _aus_adresse("""
  await gremiumAusAdresse("bv9"); aus.r = [sel.value, gremiumUnbekannt, abrufe.length, GREMIUM_UNBEKANNT()];
  await gremiumAusAdresse("name:"); aus.leer = [sel.value, gremiumUnbekannt];
""", gremien_json=g, da=False)
    assert ohne["r"] == ["", True, 0, "Das Gremium aus dem Link ist nicht verzeichnet; seine Kennung kann sich geändert "
                                      "haben. Die Liste ist nicht nach Gremium gefiltert."]
    assert ohne["leer"] == ["", True]
    kaputt = _aus_adresse('await gremiumAusAdresse("bv9"); aus.r = [sel.value, gremiumUnbekannt];', gremien_json=None)
    assert kaputt["r"] == ["", True]


def test_gremium_filter_beim_start_und_hinweis_endet():
    """(10) start() liest gremium_filter nach dem Gebiet (auch mit suche=koeln, wer/darstellung/kennung und dem Vorgang
    im Anker) und öffnet die Liste; gremien.json lädt nur gremiumAusAdresse, nicht start(). Der Satz zur unbekannten
    Kennung endet mit der nächsten Änderung der Filter, mit „Vorlagen dieses Gremiums“ und mit dem Zurücksetzen;
    renderGlobal und render hängen ihn an #count."""
    start = _teil(APP, r"^  async function start\(\) \{\n.*?\n  \}\n")
    lesen = 'if (params.get("gremium_filter")) { await gremiumAusAdresse(params.get("gremium_filter")); shown = LIST_STEP; render(); }'
    assert lesen in start and "gremien.json" not in start
    assert start.index('await loadArea(params.get("gebiet") || DEFAULT_AREA, true);') < start.index(lesen) \
        < start.index("const initial = papers.find((p) => p.reference === ref);") < start.index('params.get("wer")')
    assert 'if (["thema", "partei", "suche", "gremium_filter"].some((k) => params.get(k))) setPanel("panel-list", true);' in start
    assert 'state.gremium = pz && pz.tab === "gremien"' in APP   # Bonner Name unverändert, eigener Name gremium_filter
    for teil in (_teil(APP, r"^  function resetFilters\(\) \{\n.*?\n  \}\n"), _teil(APP, r"^  function gremiumFiltern\(key, name\) \{\n.*?\n  \}\n"),
                 _teil(APP, r'^    \$\("#filters"\)\.addEventListener\("input", \(e\) => \{\n.*?\n    \}\);\n')):
        assert "gremiumUnbekannt = false;" in teil
    for f in ("render", "renderGlobal"):
        assert "$(\"#count\").textContent = mitGremiumHinweis(" in _teil(APP, rf"^  function {f}\(nurListe\) \{{\n.*?\n  \}}\n")
    import test_wer_entscheidet_seite as ws
    r = ws._global(ws.SUCHE, "", "", unbekannt=True)
    assert r["count"] == ("4 Treffer in ganz Köln · Das Gremium aus dem Link ist unter „Gremien“ nicht verzeichnet; seine "
                          "Kennung kann sich geändert haben. Die Liste ist nicht nach Gremium gefiltert.")


# --- (11) Wartezeit beim Laden ---------------------------------------------------------------------------------------

def _laden_mit_frist(oeffnen, ablauf):
    """openGremien bzw. openMitmachen aus app.js mit Wartezeit 40 ms (statt 20 s) und Importen von Hand: `importe`
    hält je Aufruf ein Objekt mit ja/nein; `ablauf` ist der Rumpf einer async-Funktion, die `ergebnis` setzt."""
    teil = _teil(APP, r"^  const WARTEZEIT = .*?;\n").replace("20000", "40") + _teil(APP, r"^  const mitFrist = .*?\n  \}\);\n")
    if oeffnen == "gremien":
        teil += _teil(APP, r"^  let werState = null, werReady = null, werModul = null, werImportFehler = 0;\n.*?^  function openGremien\(s\) \{\n.*?\n  \}\n")
    else:
        teil += _teil(APP, r"^  let mmState = null, mmReady = null, mmModul = null, mmImportFehler = 0;\n  function openMitmachen\(s\) \{\n.*?\n  \}\n")
    assert teil.count("import(modul)") == 1
    code = """
const E = { "#wer-body": { innerHTML: "alt" }, "#wer-status": { textContent: "" }, "#bt-body": { innerHTML: "alt" }, "#bt-status": { textContent: "" } };
const $ = (s) => E[s];
let funktionen = { gremien: true }, zeit = null;
const vorhanden = () => true, BONN = "data/", heute = () => "2026-11-23", zeitDatum = (s) => s, lizenzOeffentlich = (t) => t;
const MOBILE = { matches: false }, syncUrl = () => {}, gremiumFiltern = () => {}, bvBezirk = () => "", areaBezirk = () => "";
const setPanel = () => {}, showTermine = () => {}, focusPanel = () => {};
const adressen = [], importe = [], gezeigt = [], inits = [];
const modul = (nr) => ({ nr, show: (s) => gezeigt.push([nr, s]), async init(c) { inits.push([nr, c.wartezeit ?? null]); } });
const importieren = (u) => { adressen.push(u); return new Promise((ja, nein) => importe.push({ ja, nein })); };
const warten = (ms) => new Promise((r) => setTimeout(r, ms));
""" + teil.replace("import(modul)", "importieren(modul)") + """
(async () => {
  let ergebnis = null;
""" + ablauf + """
  console.log(JSON.stringify(ergebnis));
})();
"""
    return _node(code)


SATZ_GREMIEN = "Die Angaben zu Gremien und Ämtern konnten nicht geladen werden. Beim nächsten Öffnen versucht der Ratsatlas es erneut."
SATZ_MITMACHEN = "Die Fläche „Mitmachen in Köln“ konnte nicht geladen werden. Beim nächsten Öffnen versucht der Ratsatlas es erneut."


def test_wartezeit_modul_gremien():
    """(11) Antwortet gremien.js nicht in der Wartezeit, steht der Satz zum Ladefehler in der Statuszeile, das Warten
    endet, und das nächste Öffnen lädt das Modul unter einer anderen Adresse (?versuch=1). Kommt die erste Antwort
    später, bleibt sie ohne Wirkung: kein init, keine Anzeige, die Statuszeile des zweiten Versuchs bleibt."""
    r = _laden_mit_frist("gremien", """
  const erst = openGremien({ tab: "gremien" });
  const beim = E["#wer-status"].textContent;
  const r1 = await erst;
  const nach = E["#wer-status"].textContent;
  const zweit = openGremien({ tab: "aemter" });
  importe[0].ja(modul(1));   // späte Antwort des ersten Versuchs
  await warten(5);
  const zwischen = [E["#wer-status"].textContent, inits.length, gezeigt.length];
  importe[1].ja(modul(2));
  await zweit;
  ergebnis = { beim, r1, nach, zwischen, adressen, inits, gezeigt };
""")
    assert r == {"beim": "Wird geladen …", "r1": None, "nach": SATZ_GREMIEN, "zwischen": ["Wird geladen …", 0, 0],
                 "adressen": ["./gremien.js", "./gremien.js?versuch=1"], "inits": [[2, 40]], "gezeigt": [[2, {"tab": "aemter"}]]}


def test_wartezeit_mitmachen_mit_eigener_statuszeile():
    """(11) Dieselbe Regel für „Mitmachen in Köln“: eigene Statuszeile #bt-status (role=status) mit „Wird geladen …“,
    dem Satz zum Ladefehler nach der Wartezeit und leer nach dem Laden; der nächste Versuch unter ?versuch=1; eine späte
    Antwort bleibt ohne Wirkung."""
    r = _laden_mit_frist("mitmachen", """
  const erst = openMitmachen({ bezirk: "" });
  const beim = [E["#bt-status"].textContent, E["#bt-body"].innerHTML];
  await erst;
  const nach = E["#bt-status"].textContent;
  const zweit = openMitmachen({ bezirk: "" });
  importe[0].ja(modul(1));
  await warten(5);
  const zwischen = [E["#bt-status"].textContent, inits.length];
  importe[1].ja(modul(2));
  await zweit;
  ergebnis = { beim, nach, zwischen, adressen, inits: inits.map((i) => i[0]), gezeigt: gezeigt.map((g) => g[0]), danach: E["#bt-status"].textContent };
""")
    assert r == {"beim": ["Wird geladen …", ""], "nach": SATZ_MITMACHEN, "zwischen": ["Wird geladen …", 0],
                 "adressen": ["./beteiligung.js", "./beteiligung.js?versuch=1"], "inits": [2], "gezeigt": [2], "danach": ""}
    flaeche = _abschnitt(INDEX, "panel-mitmachen")
    assert '<p class="hint bt-status" id="bt-status" role="status"></p>' in flaeche
    assert flaeche.index('id="bt-status"') < flaeche.index('id="bt-body"') and "aria-live" not in flaeche
    assert '<div class="panel-body" id="bt-body"></div>' in flaeche
    assert ".wer-status, .bt-status { margin: 0 18px 6px; flex: none; }" in CSS


def test_wartezeit_daten_mit_abbruch():
    """(11) gremien.js bricht den Abruf von gremien.json und aemter.json nach der Wartezeit ab (AbortController): init
    scheitert, die Daten bleiben ungesetzt; ein neuer Versuch lädt sie. Eine Antwort nach dem Abbruch kommt nicht an."""
    r = _steuerung("""
const signale = [];
const offen = [];
globalThis.fetch = (url, o) => new Promise((ok, nein) => {
  signale.push(o && o.signal);
  o.signal.addEventListener("abort", () => nein(new Error("abgebrochen")));
  offen.push(() => ok({ ok: true, status: 200, json: async () => (url.endsWith("gremien.json") ? G : A) }));
});
const erst = M.init({ ...ctx, wartezeit: 30 });
const uhren = zeitgeber.size;
zeitAblaufen();
let fehler = null;
try { await erst; } catch (e) { fehler = e.message; }
offen.splice(0).forEach((f) => f());   // späte Antworten nach dem Abbruch
await new Promise((r) => setImmediate(r));
M.show({ tab: "gremien" });
const ohneDaten = body.gesetzt;
const zweit = M.init(ctx);
offen.splice(0).forEach((f) => f());
await zweit;
M.show({ tab: "gremien" });
ergebnis = { uhren, fehler, abgebrochen: signale.slice(0, 2).map((s) => s.aborted), ohneDaten, mitDaten: body.innerHTML.includes("org-node"), rest: zeitgeber.size };
""")
    assert r == {"uhren": 2, "fehler": "abgebrochen", "abgebrochen": [True, True], "ohneDaten": 0, "mitDaten": True, "rest": 0}
    quelle = GREMIEN_JS.read_text(encoding="utf-8")
    assert "export const WARTEZEIT = 20000;" in quelle and "ctx.wartezeit ?? WARTEZEIT" in quelle
    assert "const WARTEZEIT = 20000;" in APP and "wartezeit: WARTEZEIT," in APP


# --- (12) Esc im Suchfeld --------------------------------------------------------------------------------------------

def test_esc_im_suchfeld_leert_zuerst():
    """(12) Esc im gefüllten Suchfeld der Liste leert es (Liste und Statuszeile sofort neu) und hält das Ereignis an
    (die Fläche bleibt offen); bei leerem Feld läuft Esc weiter zu app.js, das die Fläche schließt. Andere Tasten und
    Felder bleiben unberührt."""
    r = _steuerung("""
await geladen();
M.show({ tab: "gremien", darstellung: "liste" });
const taste = (key, target) => { const e = { key, target, angehalten: false, verhindert: false,
  stopPropagation() { this.angehalten = true; }, preventDefault() { this.verhindert = true; } };
  (handler["body:keydown"] || []).forEach((f) => f(e)); return e; };
const feld = { id: "wer-q", value: "bez" };
feuern("body", "input", feld);
const vorher = liste.innerHTML;
const e1 = taste("Escape", feld);
const nach1 = { wert: feld.value, status: status.textContent, liste: liste.innerHTML !== vorher, zaehler: zeitgeber.size };
const e2 = taste("Escape", feld);
const e3 = taste("Enter", { id: "wer-q", value: "x" }), e4 = taste("Escape", { id: "anderes", value: "x" });
ergebnis = { e1: [e1.angehalten, e1.verhindert], nach1, e2: [e2.angehalten, e2.verhindert], andere: [e3.angehalten, e4.angehalten] };
""")
    assert r == {"e1": [True, True], "nach1": {"wert": "", "status": "4 Gremien", "liste": True, "zaehler": 0},
                 "e2": [False, False], "andere": [False, False]}


# --- (13) fehlender Suchindex ----------------------------------------------------------------------------------------

def _suchindex(ablauf):
    teil = _teil(APP, r"^  function loadSearch\(\) \{\n.*?\n  \}\n") + _teil(APP, r"^  function suchindexFehlt\(\) \{\n.*?\n  \}\n") \
        + _teil(APP, r"^  function sucheErneut\(\) \{\n.*?\n  \}\n")
    code = """
const E = { "#count": { textContent: "" }, "#papers": { innerHTML: "<li>alter Eintrag</li>" }, "#mega-count": { textContent: "" } };
const $ = (s) => (s === "#suche-erneut" ? (E["#papers"].innerHTML.includes('id="suche-erneut"') ? {} : null) : E[s]);
const STADT = "koeln", BONN = "data/", index = {}, plan = [];
let search = null, searchLoading = null, openMegaId = null, gerendert = 0, fokus = null;
const scope = () => STADT, fillParties = () => {}, render = () => { gerendert++; E["#papers"].innerHTML = "<li>Treffer</li>"; };
const focusPanel = (id) => { fokus = id; };
globalThis.fetch = async () => { const p = plan.shift(); if (p === "netz") throw new TypeError("Failed to fetch");
  return { ok: p === "ok", status: p === "ok" ? 200 : 503, json: async () => ({ rows: [], parties: [] }) }; };
const warten = () => new Promise((r) => setTimeout(r, 5));
""" + teil + """
(async () => {
  let ergebnis = null;
""" + ablauf + """
  console.log(JSON.stringify(ergebnis));
})();
"""
    return _node(code)


def test_suchindex_fehlt_liste_leer_und_erneut_versuchen():
    """(13) Fehlt suche.json in ganz Köln, leert sich die Liste (keine alten Einträge), #count behält einen klaren Satz
    (mit Fehlercode, ohne englische Meldung des Browsers), und „Erneut versuchen“ lädt den Index neu: Bei Erfolg die
    Liste und der Fokus auf ihrer Überschrift, bei erneutem Fehler bleibt die Schaltfläche (und mit ihr der Fokus)."""
    r = _suchindex("""
  plan.push("503", "netz", "ok");
  await loadSearch(); suchindexFehlt();
  const erst = { count: E["#count"].textContent, liste: E["#papers"].innerHTML };
  sucheErneut(); const laden = E["#count"].textContent; await warten();
  const zweit = { count: E["#count"].textContent, liste: E["#papers"].innerHTML === erst.liste, gerendert, fokus };
  sucheErneut(); await warten();
  ergebnis = { erst, laden, zweit, dritt: { gerendert, fokus, liste: E["#papers"].innerHTML, geladen: Boolean(search) } };
""")
    assert r["erst"]["count"] == "Der Suchindex konnte nicht geladen werden (HTTP 503)."
    assert r["erst"]["liste"] == ('<li class="empty-list"><p>Die Vorlagen in ganz Köln erscheinen hier, sobald der Suchindex '
                                  'geladen ist.</p><button type="button" class="btn btn-secondary" id="suche-erneut">Erneut versuchen</button></li>')
    assert r["laden"] == "Lade den Suchindex für ganz Köln …"
    assert r["zweit"] == {"count": "Der Suchindex konnte nicht geladen werden.", "liste": True, "gerendert": 0, "fokus": None}
    assert r["dritt"] == {"gerendert": 1, "fokus": "panel-list", "liste": "<li>Treffer</li>", "geladen": True}
    render = _teil(APP, r"^  function render\(nurListe\) \{\n.*?\n  \}\n")
    assert 'loadSearch().then((d) => { if (d) { fillParties(); render(); } else if (scope() === STADT) suchindexFehlt(); });' in render
    assert 'gremiumKennzeichen();\n        $("#count").textContent = "Lade den Suchindex für ganz Köln …";' in render   # Kennzeichen bleibt
    assert 'if (e.target.closest("#suche-erneut")) { sucheErneut(); return; }' in APP


# --- (14) kennung bei mehreren offenen Einträgen ---------------------------------------------------------------------

def test_kennung_folgt_dem_zuletzt_geoeffneten_offenen_eintrag():
    """(14) Sind mehrere Einträge der Liste offen, folgt `kennung` dem zuletzt geöffneten, der noch offen ist; wird er
    zugeklappt, dem davor geöffneten offenen; erst ohne offenen Eintrag fehlt sie. Einträge, die ein Neuaufbau der Liste
    geschlossen hat, zählen nicht mehr."""
    r = _steuerung("""
await geladen();
M.show({ tab: "gremien", darstellung: "liste" });
const offen = {};
const alt = body.querySelector;
body.querySelector = (s) => { const m = s.match(/^details\\.pz-item\\[data-kennung="([^"]+)"\\]$/); return m ? { open: Boolean(offen[m[1]]) } : alt(s); };
const zustaende = [];
ctx.onState = (st) => zustaende.push(st.kennung);
const kippen = (k, an) => { offen[k] = an; feuern("body", "toggle", { matches: () => true, open: an, dataset: { kennung: k } }); };
kippen("rat", true); kippen("bv1", true); kippen("beirat", true);
kippen("beirat", false);
kippen("rat", false);
kippen("aus-a", true); kippen("aus-a", false);
kippen("bv1", false);
// Neuaufbau (Suche): nur noch „beirat“ offen in der Liste, „rat“ steht nicht mehr offen da
kippen("rat", true); kippen("beirat", true); offen.rat = false; kippen("beirat", false);
ergebnis = { zustaende, ende: M.werZustand().kennung };
""")
    assert r["zustaende"] == ["rat", "bv1", "beirat", "bv1", "bv1", "aus-a", "bv1", None, "rat", "beirat", None]
    assert r["ende"] is None


# --- (15), (16) Stilregeln -------------------------------------------------------------------------------------------

def _media(bedingung):
    m = re.search(rf"^@media \({re.escape(bedingung)}\) \{{\n(.*?)\n\}}\n", CSS, re.S | re.M)
    assert m, bedingung
    return m.group(1)


def test_geringe_hoehe_ganze_ueberlagerung_rollt():
    """(15) Bei geringer Höhe (max-height: 480px, etwa 400 % Zoom mit 320 × 256 CSS-Pixeln) rollt jede Überlagerung als
    Ganzes (Kopf, Reiter, Umschalter rollen mit), ihr Inhalt nicht mehr für sich; ebenso „Über“ und „Was ist neu?“. Bei
    normaler Höhe gelten die bisherigen Regeln (overflow: hidden der Überlagerung, eigener Bildlauf des Inhalts)."""
    regeln = _media("max-height: 480px")
    for r in (".overlay { overflow-y: auto; overscroll-behavior: contain; }", ".overlay > * { flex: none; }",
              ".overlay > .panel-body { overflow: visible; }", "#about[open], #neu[open] { display: block; overflow-y: auto; }",
              ".about-body { overflow: visible; }"):
        assert r in regeln, r
    assert re.search(r"^\.overlay \{ position: fixed;[^}]*overflow: hidden;", CSS, re.M)
    assert ".panel-body { overflow: auto; padding: 0 18px 18px; flex: 1;" in CSS
    for flaeche in ("panel-auswertung", "panel-prozesse", "panel-termine", "panel-mitmachen", "panel-gremien"):
        assert re.search(rf'<section id="{flaeche}" class="glass overlay', INDEX), flaeche
    # bei der Prüfung gefunden: Reiter direkt in einer Überlagerung („In Zahlen“) brechen bei 320 px Breite um
    assert ".overlay > .tabs { flex-wrap: wrap; max-width: calc(100% - 36px); }" in CSS


def test_telefon_44_px_und_16_px():
    """(16) Auf dem Telefon (dieselbe Grenze wie MOBILE in app.js) sind die Reiter „Gremien“ und „Ämter“, der Umschalter
    „Schaubild | Liste“, das Suchfeld der Gremien und die Eingabefelder der Filter in der Liste (Stichwort, Auswahlen)
    mindestens 44 px hoch und 16 px groß geschrieben (sonst vergrößert iOS beim Fokus)."""
    assert 'const MOBILE = matchMedia("(max-width: 900px)");' in APP
    bloecke = re.findall(r"^@media \(max-width: 900px\) \{\n(.*?)\n\}\n", CSS, re.S | re.M)
    regeln = "\n".join(bloecke)
    assert "#panel-gremien .tabs [role=tab], #panel-gremien .wer-darstellung button { min-height: 44px; font-size: 16px; }" in regeln
    assert "#wer-q, .filters input[type=search], .filters select { min-height: 44px; font-size: 16px; }" in regeln
