"""Pull Request 4b, Seitenteil (Entscheidungen 21.11.2026 (2) (F2, F4–F12) und 23.11.2026 (1) (E1–E11)): Fläche
„Gremien und Ämter“ unter „Wer entscheidet“ (site/gremien.js), Titel der Schaltfläche, „In Zahlen“, Filter „Gremium“
über die Kennung im Gebiet und in ganz Köln, eigene Parameter in der Adresse, „Was ist neu?“, Quellenzeile und Punkt 7
der Anfrage an die Stadt (E5). Geprüft ohne Browser (node mit nachgebildetem Dokument oder als Modul, Python); die
Prüfung im Browser steht in tests/browser/gremien.js. Alle Gremien, Kennungen, Vorlagen und Adressen sind erfunden;
keine Anfragen nach außen."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import config, seo

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
GREMIEN_JS = ROOT / "site" / "gremien.js"
X = "https://example.invalid/oparl"


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


# --- erfundene gremien.json und aemter.json in der Form von pipeline/gremien.py und pipeline/aemter.py ---------------

def _sitzung(tag, **f):
    return {"date": tag, "time": "17:00", "web": f"{X}/sitzung/{tag}", "source_object": f"{X}/meetings/{tag}", **f}


GREMIEN = {
    "meta": {
        "datenstand": "2026-11-23", "zeitraum": {"seit": "2025-11-23", "bis": "2026-11-23"},
        "sources": [{"name": "oparl-koeln", "url": f"{X}/bodies/x",
                     "license": "Beispiellizenz (Klärung offen, CLAUDE.md 8); Datenquelle: Beispielstadt"}],
        "namensnennung": "Datenquelle: Beispielstadt",
        "zustaendigkeitsordnung": {"titel": "Beispielordnung vom 01.06.2026", "url": "https://example.invalid/ordnung.pdf",
                                   "hinweis": "Nur der Paragraf."},
        "gruppen": {"rat": "Rat", "ausschuss": "Ausschüsse mit Paragraf der Zuständigkeitsordnung",
                    "bezirksvertretung": "Bezirksvertretungen", "uebrige": "übrige Gremien"},
        "note": "erfunden",
    },
    "gremien": [
        {"key": "rat", "name": "Beispielrat", "gruppe": "rat", "sitzungen_12m": 12, "vorlagen_12m": 1,
         "naechste_sitzung": _sitzung("2026-11-23"), "folgende_sitzung": _sitzung("2026-12-01", hinweis="verschoben"),
         "source_object": f"{X}/organizations/rat"},
        {"key": "aus-a", "name": "Ausschuss für Beispiele", "gruppe": "ausschuss", "paragraf": 7, "sitzungen_12m": 1,
         "vorlagen_12m": 3, "naechste_sitzung": _sitzung("2026-11-30", time=None, web=None),
         "source_object": f"{X}/organizations/aus-a"},
        {"key": "bv1", "name": "Bezirksvertretung 1 (Musterbezirk)", "gruppe": "bezirksvertretung", "stadtbezirk": "Musterbezirk",
         "sitzungen_12m": 0, "vorlagen_12m": 0, "source_object": f"{X}/organizations/bv1"},
        {"key": "beirat", "name": "Beirat für Straßenbäume", "gruppe": "uebrige", "sitzungen_12m": 2, "vorlagen_12m": 2,
         "source_object": f"{X}/organizations/beirat"},
        {"key": "alt", "name": "Früherer Probeausschuss", "gruppe": "uebrige", "end_date": "2025-10-31", "aufgeloest": True,
         "sitzungen_12m": 0, "vorlagen_12m": 4, "source_object": f"{X}/organizations/alt"},
    ],
}
AEMTER = {
    "meta": {"quelle": {"titel": "Beispielplan der Verwaltung", "url": "https://example.invalid/plan.pdf",
                        "stand": "2026-11-01", "geprueft": "2026-11-13", "sha256": "0" * 64},
             "quellenangabe": "Beispielplan", "lizenz": "im Plan keine Lizenz angegeben; nur Nummern und Bezeichnungen",
             "note": "erfunden"},
    "dezernate": [
        {"dezernat": "OB", "kennung": "OB", "name": "", "label": "Dezernat OB", "fundstelle": "Seite 1", "einheiten": [
            {"nummer": "01", "kennung": "OB/01", "name": "Probeamt", "label": "01 Probeamt", "ebene": "dienststelle",
             "fundstelle": "Seite 1, Eintrag 3"}]},
        {"dezernat": "IX", "kennung": "IX", "name": "Beispiele", "label": "Dezernat IX – Beispiele", "fundstelle": "Seite 2",
         "einheiten": [
             {"nummer": "IX/1", "kennung": "IX/IX/1", "name": "Stabsstelle", "label": "IX/1 Stabsstelle",
              "ebene": "dezernatseinheit", "eigenbetriebsaehnlich": True, "fundstelle": "Seite 2, Eintrag 1"},
             {"nummer": "9100", "kennung": "IX/9100", "name": "Punktstelle", "label": "9100 Punktstelle",
              "ebene": "punktdienststelle", "fundstelle": "Seite 2, Eintrag 4"}]},
    ],
    "ohne_zuordnung": [{"nummer": "9500", "name": "Musterhaus", "label": "9500 Musterhaus", "markierung": "●",
                        "fundstelle": "Seite 2, Eintrag 9"}],
}


def _modul(ausdruck, **daten):
    """site/gremien.js als Modul laden und `ausdruck` mit den erfundenen Daten auswerten (G = gremien.json, A =
    aemter.json, U = Umgebung mit heute, zeitDatum und lizenz wie app.js)."""
    d = {"G": GREMIEN, "A": AEMTER, "heute": "2026-11-23", **daten}
    code = f"""
import * as M from "{GREMIEN_JS.as_uri()}";
const G = {json.dumps(d["G"])}, A = {json.dumps(d["A"])};
const U = {{ heute: {json.dumps(d["heute"])}, zeitDatum: (s) => "Tag(" + s + ")",
  lizenz: (t) => String(t).replace(/\\s*\\(CLAUDE\\.md \\d+\\)/g, "").replace(/,\\s*CLAUDE\\.md \\d+/g, "") }};
console.log(JSON.stringify({ausdruck}));
"""
    return _node(code, modul=True)


# --- Modul site/gremien.js --------------------------------------------------------------------------------------------

def test_zeitraum_beginnt_am_tag_nach_seit():
    """F7: `seit` zählt nicht mit, `bis` zählt mit; der Zeitraum beginnt also am Tag danach (auch über Monats- und
    Jahresgrenzen und an der Zeitumstellung); ohne lesbare Tage kein Zeitraum."""
    aus = _modul("[M.zeitraum(G.meta), M.tagDanach('2025-12-31'), M.tagDanach('2026-03-28'), M.tagDanach('2026-10-24'), "
                 "M.zeitraum({ zeitraum: { seit: 'x', bis: '2026-11-23' } }), M.zeitraum({})]")
    assert aus == [{"von": "2025-11-24", "bis": "2026-11-23"}, "2026-01-01", "2026-03-29", "2026-10-25", None, None]


def test_kommende_sitzung_nach_dem_tag_der_besucher():
    """E2: Die nächste Sitzung erscheint nur, wenn ihr Kölner Tag nicht vor heute liegt; liegt sie am Datenstand und ist
    vorbei, zeigt die Seite die folgende Sitzung; ohne beide nichts."""
    rat = GREMIEN["gremien"][0]
    aus = _modul("[M.kommendeSitzung(G.gremien[0], '2026-11-23'), M.kommendeSitzung(G.gremien[0], '2026-11-24'), "
                 "M.kommendeSitzung(G.gremien[0], '2026-12-02'), M.kommendeSitzung(G.gremien[2], '2026-11-23'), "
                 "M.kommendeSitzung({ naechste_sitzung: { date: 'kaputt' } }, '2026-11-23')]")
    assert aus == [rat["naechste_sitzung"], rat["folgende_sitzung"], None, None, None]


def test_kurzzeile_der_knoten():
    """E7: Kurzzeile aus Paragraf bzw. Stadtbezirk und nächster Sitzung (mit „verschoben“ laut Sitzungsnamen);
    aufgelöste Gremien mit „aufgelöst“; bei nicht aktueller Liste der Sitzungen ohne Sitzung."""
    nicht_aktuell = {**GREMIEN["meta"], "sitzungsliste_nicht_aktuell": {"stand": None, "hinweis": "x"}}
    aus = _modul(f"[...G.gremien.map((g) => M.kurzzeile(g, G.meta, '2026-11-24')), M.kurzzeile(G.gremien[1], {json.dumps(nicht_aktuell)}, '2026-11-24')]")
    assert aus == ["nächste Sitzung 01.12.2026, laut Sitzungsnamen verschoben", "§ 7 · nächste Sitzung 30.11.2026",
                   "Stadtbezirk Musterbezirk", "", "aufgelöst", "§ 7"]


def test_inhalt_eines_gremiums():
    """Detail eines Gremiums: Link „Zuständigkeitsordnung, § n (PDF, neuer Tab)“ auf meta.zustaendigkeitsordnung.url
    (abgeleitet gekennzeichnet), Stadtbezirk der Bezirksvertretung, Zahlen in 12 Monaten mit dem Zeitraum ab dem Tag nach
    `seit`, nächste Sitzung mit Plakette „laut Sitzungsnamen verschoben“ und Tagesordnung, Knopf „Vorlagen dieses
    Gremiums“ mit dem Namen im zugänglichen Namen, Quellobjekt; keine Zeile zu `web` des Gremiums (keines hat eine)."""
    rat, aus_a, bv, beirat = _modul("G.gremien.slice(0, 4).map((g) => M.gremiumInhalt(g, G.meta, { ...U, heute: '2026-11-24' }))")
    assert ('<a href="https://example.invalid/ordnung.pdf" target="_blank" rel="noopener">Zuständigkeitsordnung, § 7 (PDF, neuer Tab)</a>'
            ' <span class="derived">abgeleitet, über den Namen des Ausschusses</span>') in aus_a
    assert "In den 12 Monaten vom 24.11.2025 bis 23.11.2026: 1 Sitzung, 3 Vorlagen beraten" in aus_a
    # ohne Uhrzeit; ohne Adresse der Tagesordnung derselbe Satz wie in „Aktuell in Köln“ (seit 23.11.2026 (2) (4))
    assert "Nächste Sitzung: Mo., 30.11.2026 · Tagesordnung noch nicht veröffentlicht</li>" in aus_a
    assert "Nächste Sitzung: Di., 01.12.2026, 17:00 Uhr <span class=\"badge\">laut Sitzungsnamen verschoben</span> · " in rat
    assert f'<a href="{X}/sitzung/2026-12-01" target="_blank" rel="noopener">Tagesordnung<span class="visually-hidden"> (Ratsinformationssystem, neuer Tab)</span></a>' in rat
    assert "12 Sitzungen, 1 Vorlage beraten" in rat and "Zuständigkeitsordnung" not in rat
    assert 'Stadtbezirk Musterbezirk <span class="derived">abgeleitet, über den Namen der Bezirksvertretung</span>' in bv
    assert "0 Sitzungen, 0 Vorlagen beraten" in bv and "Nächste Sitzung" not in bv and "Nächste Sitzung" not in beirat
    for html, key, name in ((rat, "rat", "Beispielrat"), (aus_a, "aus-a", "Ausschuss für Beispiele"), (bv, "bv1", "Bezirksvertretung 1 (Musterbezirk)")):
        assert (f'<button type="button" class="btn btn-soft wer-filter" data-kennung="{key}" data-name="{name}" '
                f'aria-describedby="wer-jahre-{key}">Vorlagen dieses Gremiums<span class="visually-hidden">: {name}</span></button>') in html
        assert f'Quellobjekt: <a href="{X}/organizations/{key}" target="_blank" rel="noopener">' in html
    for html in (rat, aus_a, bv, beirat):
        assert "Im Ratsinformationssystem" not in html and "folgt" not in html


def test_frueheres_gremium_ohne_knopf_mit_erklaerung():
    """E3 und E4: Ein aufgelöstes Gremium behält „Vorlagen in 12 Monaten“ mit einem erklärenden Satz und zeigt keinen
    Knopf „Vorlagen dieses Gremiums“; das Enddatum steht da."""
    alt = _modul("M.gremiumInhalt(G.gremien[4], G.meta, U)")
    assert "Aufgelöst: Enddatum 31.10.2025 laut Ratsinformationssystem" in alt
    assert "0 Sitzungen, 4 Vorlagen beraten" in alt
    assert ("Gezählt sind die Vorlagen über die Beratungen dieses früheren Gremiums im Ratsinformationssystem; einen Filter "
            "„Vorlagen dieses Gremiums“ gibt es für frühere Gremien nicht.") in alt
    assert "wer-filter" not in alt


def test_sitzungsliste_nicht_aktuell():
    """Plan 7: Bei meta.sitzungsliste_nicht_aktuell steht statt der nächsten Sitzung ein Hinweis mit dem Stand der
    Liste als Kölner Tag (zeitDatum aus app.js), ohne Stand derselbe Wortlaut wie im Datenstand („der letzte gültige
    Stand“); oben im Reiter einmal als Hinweis zum Datenstand."""
    meta = {**GREMIEN["meta"], "sitzungsliste_nicht_aktuell": {"stand": "2026-11-17T23:30:00+00:00", "hinweis": "x"}}
    ohne = {**GREMIEN["meta"], "sitzungsliste_nicht_aktuell": {"stand": None, "hinweis": "x"}}
    mit_stand, ohne_stand, reiter = _modul(
        f"[M.gremiumInhalt(G.gremien[0], {json.dumps(meta)}, U), M.gremiumInhalt(G.gremien[0], {json.dumps(ohne)}, U), "
        f"M.inhaltGremien({{ ...G, meta: {json.dumps(meta)} }}, {{ kennung: null, q: '', frueher: false }}, 'schaubild', U)]")
    assert ("Die Liste der Sitzungen wurde beim letzten Abruf nicht aktualisiert; gezeigt wird der Stand vom "
            "Tag(2026-11-17T23:30:00+00:00); deshalb fehlt die nächste Sitzung.") in mit_stand   # Schluss seit 23.11.2026 (2) (5)
    assert "gezeigt wird der letzte gültige Stand; deshalb fehlt die nächste Sitzung." in ohne_stand
    for html in (mit_stand, ohne_stand):
        assert "Nächste Sitzung:" not in html
    assert '<p class="stand-hinweis"><strong>Hinweis zum Datenstand:</strong> Die Liste der Sitzungen' in reiter
    assert "nächste Sitzung 01.12" not in reiter and "nächste Sitzung 23.11" not in reiter


def test_schaubild_gruppen_und_detail():
    """E7, E8, F5: Schaubild mit dem Rat oben, Ausschüssen und Bezirksvertretungen nebeneinander und den übrigen Gremien
    in einem eigenen Abschnitt, alle sichtbar; aufgelöste Gremien nur in der Liste (Satz in der Einleitung); jeder Knoten
    ist eine Schaltfläche mit aria-pressed; der Detailbereich ohne Live-Region. Eine Gruppe ohne Gremium fehlt."""
    html, gewaehlt, ohne_bv = _modul(
        "[M.inhaltGremien(G, { kennung: null, q: '', frueher: false }, 'schaubild', U), "
        "M.inhaltGremien(G, { kennung: 'aus-a', q: '', frueher: false }, 'schaubild', U), "
        "M.inhaltGremien({ ...G, gremien: G.gremien.filter((g) => g.gruppe !== 'bezirksvertretung') }, { kennung: null, q: '', frueher: false }, 'schaubild', U)]")
    knoten = re.findall(r'<button type="button" class="org-node[^"]*" data-kennung="([\w-]+)" aria-pressed="(\w+)">', html)
    assert knoten == [("rat", "false"), ("aus-a", "false"), ("bv1", "false"), ("beirat", "false")]
    assert html.index('id="wer-h-rat"') < html.index('id="wer-h-ausschuss"') < html.index('id="wer-h-bezirksvertretung"') \
        < html.index('id="wer-h-uebrige"')
    assert '<h3 class="org-h" id="wer-h-uebrige">Übrige Gremien</h3>' in html and "<details" not in html
    assert "Früherer Probeausschuss" not in html and "frühere Gremien stehen in der Liste" in html
    detail = _abschnitt(html, "wer-detail")
    assert "aria-live" not in html and "Wählen Sie im Schaubild ein Gremium" in detail
    assert '<h3 class="pz-h" tabindex="-1">Ausschuss für Beispiele</h3>' in _abschnitt(gewaehlt, "wer-detail")
    assert 'data-kennung="aus-a" aria-pressed="true"' in gewaehlt
    assert "wer-h-bezirksvertretung" not in ohne_bv and "wer-eine-spalte" in ohne_bv
    assert "Quelle: Ratsinformationssystem der Stadt Köln (OParl-API; Beispiellizenz (Klärung offen); Datenquelle: Beispielstadt)." in html
    assert "CLAUDE.md" not in html and "Paragrafen der Ausschüsse: Beispielordnung vom 01.06.2026. Nur der Paragraf." in html


def test_liste_suche_und_fruehere_gremien():
    """F5: Liste nach Gruppen; aufgelöste Gremien nur mit „frühere Gremien zeigen“; die Suche gleicht Groß- und
    Kleinschreibung, Umlaute und ß an; ohne Treffer ein Satz; ein gewähltes Gremium ist aufgeklappt."""
    basis, frueher, suche, keine, offen = _modul(
        "[M.listenteil(G, { kennung: null, q: '', frueher: false }, U), M.listenteil(G, { kennung: null, q: '', frueher: true }, U), "
        "M.listenteil(G, { kennung: null, q: 'STRASSENBAEUME', frueher: false }, U), "
        "M.listenteil(G, { kennung: null, q: 'nichts', frueher: false }, U), M.listenteil(G, { kennung: 'bv1', q: '', frueher: false }, U)]")
    eintraege = lambda h: re.findall(r'<details class="pz-item" data-kennung="([\w-]+)"', h)  # noqa: E731
    assert eintraege(basis) == ["rat", "aus-a", "bv1", "beirat"]
    assert eintraege(frueher) == ["rat", "aus-a", "bv1", "beirat", "alt"]
    assert re.findall(r'<h3 class="pz-h">([^<]+)</h3>', basis) == ["Rat", "Ausschüsse mit Paragraf der Zuständigkeitsordnung",
                                                                   "Bezirksvertretungen", "Übrige Gremien"]
    assert _modul("M.suchform('Straßenbäume')") == "strassenbaume"
    assert eintraege(suche) == []   # „STRASSENBAEUME“ mit „ae“ statt „ä“ findet nichts
    assert eintraege(_modul("M.listenteil(G, { kennung: null, q: 'STRASSENBÄUME', frueher: false }, U)")) == ["beirat"]
    assert keine == "<p>Kein Gremium passt zur Suche „nichts“.</p>"
    assert '<details class="pz-item" data-kennung="bv1" open>' in offen


def test_gruppen_als_ueberschrift_gross():
    """Nachprüfung 4b: Die Namen der Gruppen aus meta.gruppen stehen als Überschrift mit großem Anfangsbuchstaben da
    (meta.gruppen schreibt „übrige Gremien“ für Fließtext klein; gremien.json bleibt unverändert), im Schaubild, auch
    für die unsichtbare Überschrift des Rates, und in der Liste."""
    klein = {**GREMIEN["meta"], "gruppen": {k: v[0].lower() + v[1:] for k, v in GREMIEN["meta"]["gruppen"].items()}}
    bild, liste = _modul(f"[M.inhaltGremien({{ ...G, meta: {json.dumps(klein)} }}, {{ kennung: null, q: '', frueher: false }}, 'schaubild', U), "
                         f"M.listenteil({{ ...G, meta: {json.dumps(klein)} }}, {{ kennung: null, q: '', frueher: false }}, U)]")
    assert re.findall(r'<h3 class="[^"]+" id="wer-h-\w+">([^<]+)</h3>', bild) == [
        "Rat", "Ausschüsse mit Paragraf der Zuständigkeitsordnung", "Bezirksvertretungen", "Übrige Gremien"]
    assert re.findall(r'<h3 class="pz-h">([^<]+)</h3>', liste) == [
        "Rat", "Ausschüsse mit Paragraf der Zuständigkeitsordnung", "Bezirksvertretungen", "Übrige Gremien"]


def test_liste_nennt_ausgeblendete_fruehere_gremien():
    """Nachprüfung 4b: Passt die Suche nur auf frühere Gremien und ist „frühere Gremien zeigen“ nicht gesetzt, sagt die
    Liste das (statt „Kein Gremium passt“), und die Statuszeile nennt sie; mit dem Häkchen erscheinen sie. Passt kein
    Gremium, bleibt der bisherige Satz und „0 Gremien“; passen aktuelle Gremien, nennt die Statuszeile nur sie."""
    zwei = {**GREMIEN, "gremien": [*GREMIEN["gremien"], {**GREMIEN["gremien"][4], "key": "alt2", "name": "Zweiter Probeausschuss"}]}
    eins, eins_status, mit, mit_status, mehr, mehr_status, keins, keins_status, aktiv_status = _modul(
        "[M.listenteil(G, { kennung: null, q: ' probeausschuss ', frueher: false }, U), M.listenStatus(G, { q: 'probeausschuss', frueher: false }), "
        "M.listenteil(G, { kennung: null, q: 'probeausschuss', frueher: true }, U), M.listenStatus(G, { q: 'probeausschuss', frueher: true }), "
        f"M.listenteil({json.dumps(zwei)}, {{ kennung: null, q: 'Probeausschuss', frueher: false }}, U), "
        f"M.listenStatus({json.dumps(zwei)}, {{ q: 'Probeausschuss', frueher: false }}), "
        "M.listenteil(G, { kennung: null, q: 'nichts', frueher: false }, U), M.listenStatus(G, { q: 'nichts', frueher: false }), "
        "M.listenStatus(G, { q: '', frueher: false })]")
    assert eins == ("<p>Unter den aktuellen Gremien passt keines zur Suche „probeausschuss“; 1 früheres Gremium passt. "
                    "Mit „frühere Gremien zeigen“ erscheint es in der Liste.</p>")
    assert eins_status == "0 Gremien; 1 früheres Gremium passt"
    assert re.findall(r'<details class="pz-item" data-kennung="([\w-]+)"', mit) == ["alt"] and mit_status == "1 Gremium"
    assert mehr == ("<p>Unter den aktuellen Gremien passt keines zur Suche „Probeausschuss“; 2 frühere Gremien passen. "
                    "Mit „frühere Gremien zeigen“ erscheinen sie in der Liste.</p>")
    assert mehr_status == "0 Gremien; 2 frühere Gremien passen"
    assert keins == "<p>Kein Gremium passt zur Suche „nichts“.</p>" and keins_status == "0 Gremien"
    assert aktiv_status == "4 Gremien"


def test_reiter_aemter():
    """E9, F8: ein Abschnitt je Dezernat (beim Dezernat OB nur `label`), Einheiten mit Ebene und Fundstelle, eigene
    Gruppe „ohne Zuordnung“; Quelle mit Stand, letzter Prüfung und Lizenzhinweis immer sichtbar; keine Zahlen von
    Vorlagen."""
    html = _modul("M.inhaltAemter(A)")
    assert re.findall(r'<h3 class="pz-h" id="wer-dez-[\w-]+">([^<]+)</h3>', html) == [
        "Dezernat OB", "Dezernat IX – Beispiele", "Ohne Zuordnung (im Plan „●“)"]
    assert ('Quelle: <a href="https://example.invalid/plan.pdf" target="_blank" rel="noopener">Beispielplan der Verwaltung'
            '<span class="visually-hidden"> (PDF, neuer Tab)</span></a>, Stand 01.11.2026, zuletzt geprüft am 13.11.2026. '
            'Lizenz: im Plan keine Lizenz angegeben; nur Nummern und Bezeichnungen.') in html
    assert '<span class="wer-einheit">01 Probeamt</span><span class="pz-meta">Dienststelle · Fundstelle: Seite 1, Eintrag 3</span>' in html
    assert "Einheit des Dezernats · eigenbetriebsähnlich · Fundstelle: Seite 2, Eintrag 1" in html
    assert "Punktdienststelle (im Plan „•“) · Fundstelle: Seite 2, Eintrag 4" in html
    assert '<span class="wer-einheit">9500 Musterhaus</span><span class="pz-meta">Fundstelle: Seite 2, Eintrag 9</span>' in html
    assert "der Plan erklärt das Zeichen nicht" in html
    assert not re.search(r"\d+ Vorlagen|Vorlagen dieses", html)


def test_modul_ohne_feste_adressen_und_ohne_bonn():
    """site/gremien.js nimmt Adressen nur aus den Daten (keine feste Adresse), bindet site/prozesse.js nicht ein und
    nennt keine Besetzung (F4)."""
    quelle = GREMIEN_JS.read_text(encoding="utf-8")
    code = re.sub(r"^\s*//.*$", "", quelle, flags=re.M)
    assert not re.search(r"https?://", code)
    assert "prozesse.js" not in code and "Besetzung" not in code and "Bonn" not in code
    assert "aria-live" not in code


# --- Einbindung in index.html und app.js ------------------------------------------------------------------------------

def test_flaeche_im_html():
    """Fläche nach „Mitmachen in Köln“, nur mit Freigabe „gremien“ (data-freigabe, ohne data-funktion), h2 mit
    tabindex=-1, Reiter „Gremien“ und „Ämter“ mit wanderndem tabindex, Umschalter „Schaubild | Liste“ als radiogroup,
    eine feste Statuszeile außerhalb des Inhalts, kein „Lädt …“, keine Bonner Kennungen."""
    flaeche = _abschnitt(INDEX, "panel-gremien")
    assert INDEX.index('id="panel-mitmachen"') < INDEX.index('id="panel-gremien"')
    kopf = re.match(r"<section [^>]*>", flaeche).group(0)
    assert 'data-freigabe="gremien"' in kopf and "data-funktion" not in kopf and kopf.endswith(" hidden>")
    assert '<h2 id="gremien-heading" tabindex="-1">Gremien und Ämter</h2>' in flaeche
    assert 'data-close="panel-gremien" aria-label="Gremien und Ämter schließen"' in flaeche
    tabs = re.findall(r'<button type="button" role="tab" id="(tab-wer-\w+)" data-wer-tab="(\w+)" aria-controls="wer-body" aria-selected="(\w+)"( tabindex="-1")?>', flaeche)
    assert tabs == [("tab-wer-gremien", "gremien", "true", ""), ("tab-wer-aemter", "aemter", "false", ' tabindex="-1"')]
    assert '<div class="seg pz-view wer-darstellung" role="radiogroup" aria-label="Darstellung der Gremien">' in flaeche
    assert '<p class="hint wer-status" id="wer-status" role="status"></p>' in flaeche
    assert flaeche.index('id="wer-status"') < flaeche.index('id="wer-body"')
    assert '<div class="panel-body" id="wer-body" role="tabpanel" aria-labelledby="tab-wer-gremien"></div>' in flaeche
    assert "Lädt" not in flaeche and "pz-body" not in flaeche and "data-pz-tab" not in flaeche


def test_app_bindet_die_flaeche_ein():
    """app.js: Fläche in SHEETS und OVERLAYS; setPanel lädt das Modul beim Öffnen (Ladefehler: ein Satz in der
    Statuszeile, nächstes Öffnen versucht es erneut, nach gescheitertem Import unter einer anderen Adresse; Ablauf in
    test_ladefehler_in_der_statuszeile_und_neuer_import); closePanel gibt den Fokus an „Wer entscheidet“ zurück; das Blatt ☰ schließt beim Wählen
    einer Karte; Esc, „Los geht's“ und der Rückweg auf dem Telefon über OVERLAYS."""
    assert re.search(r'const SHEETS = \[[^\]]*"panel-gremien"[^\]]*\]\.filter\(vorhanden\);', APP)
    assert re.search(r'const OVERLAYS = \[[^\]]*"panel-gremien"[^\]]*\]\.filter\(vorhanden\);', APP)
    assert 'if (id === "panel-gremien") { if (open) openGremien(); syncUrl(); }' in APP
    assert '"panel-gremien": "mega-entscheiden"' in _teil(APP, r"^  function closePanel\(id\) \{\n.*?\n  \}\n")
    assert "[data-open-tab], [data-wer], a[href]" in APP
    oeffnen = _teil(APP, r"^  function openGremien\(s\) \{\n.*?\n  \}\n")
    assert 'const modul = werImportFehler ? `./gremien.js?versuch=${werImportFehler}` : "./gremien.js";' in oeffnen
    assert "import(modul)" in oeffnen and "werReady = null;" in oeffnen
    assert "Beim nächsten Öffnen versucht der Ratsatlas es erneut." in oeffnen
    assert "if (!werDa()) return Promise.resolve(null);" in oeffnen
    assert 'import("./prozesse.js")' not in oeffnen
    # kein Vorabladen beim Start
    start = _teil(APP, r"^  async function start\(\) \{\n.*?\n  \}\n")
    assert "gremien.json" not in start and "aemter.json" not in start and "gremien.json" not in INDEX


def test_eigene_parameter_in_der_adresse():
    """E6: eigene Parameter wer, darstellung (nur bei ausdrücklicher Wahl) und kennung, die syncUrl nicht löscht, solange
    die Fläche offen ist; die Bonner Namen bleiben der Bonner Fläche; start() öffnet die Bonner Fläche bei ?prozesse= nur
    noch mit „soll“ (vorher ohne Prüfung) und die Kölner bei ?wer= nur mit Freigabe und Fläche."""
    sync = _teil(APP, r"^  function syncUrl\(\) \{\n.*?\n  \}\n")
    assert 'state.wer = wer ? wer.tab : "";' in sync
    assert 'state.darstellung = wer && wer.tab === "gremien" && wer.darstellung ? wer.darstellung : "";' in sync
    assert 'state.kennung = wer && wer.tab === "gremien" && wer.kennung ? wer.kennung : "";' in sync
    for bonn in ("prozesse", "ansicht", "verfahren", "gremium", "amt"):
        assert f"state.{bonn} = pz" in sync, bonn
    start = _teil(APP, r"^  async function start\(\) \{\n.*?\n  \}\n")
    assert 'if (funktionen.soll && ["verfahren", "gremien", "aemter"].includes(params.get("prozesse"))) {' in start
    assert ('await openGremien({ tab: params.get("wer"), darstellung: params.get("darstellung"), kennung: params.get("kennung") || undefined, zeigen: true });'
            in start)   # zeigen: Eintrag ins Bild rollen (Nachprüfung Bedienung)


def _sync(werState, offen=True, pz=None):
    """syncUrl aus app.js mit nachgebildeter Adresse; Ergebnis: die Parameter der Adresse."""
    teil = _teil(APP, r"^  function syncUrl\(\) \{\n.*?\n  \}\n")
    code = f"""
const STADT = "koeln", KX = {{}}, PX = {{}}, EX = {{}}, kxOn = new Set();
let area = {{ kind: "koeln", key: "alle" }}, tl = null, range = null, colorBy = "", navMetric = "a", navDefault = "a";
let planOn = false, shownPlan = null, bauOn = false, shownSite = null, selected = null, sdModul = null, mmState = null;
const pzState = {json.dumps(pz)}, werState = {json.dumps(werState)}, gremiumLinkOffen = () => null;
const P = {{ "panel-prozesse": {{ hidden: {json.dumps(pz is None)} }}, "panel-gremien": {{ hidden: {json.dumps(not offen)} }} }};
const E = {{ "#f-theme": {{ value: "" }}, "#f-party": {{ value: "" }}, "#f-gremium": {{ value: "" }} }};
const $ = (s) => E[s] || P[s.slice(1)];
const vorhanden = (id) => id in P, scope = () => "gebiet";
let adresse = "";
const location = {{ href: "https://example.invalid/?wer=alt&gremium=x" }};
const history = {{ replaceState: (a, b, u) => {{ adresse = u.search; }} }};
""" + teil + """
syncUrl();
console.log(JSON.stringify(Object.fromEntries(new URLSearchParams(adresse))));
"""
    return _node(code)


def test_sync_url_schreibt_und_loescht_die_kölner_parameter():
    """syncUrl: wer, darstellung und kennung bei offener Fläche; Ämter ohne Darstellung und Kennung; geschlossen keine
    davon; die Bonner Parameter (hier gremium) löschen die Kölner nicht."""
    assert _sync({"tab": "gremien", "darstellung": "liste", "kennung": "bv1"}) == {"wer": "gremien", "darstellung": "liste", "kennung": "bv1"}
    assert _sync({"tab": "gremien", "darstellung": None, "kennung": None}) == {"wer": "gremien"}
    assert _sync({"tab": "aemter", "darstellung": "liste", "kennung": "bv1"}) == {"wer": "aemter"}
    assert _sync({"tab": "gremien", "darstellung": "liste", "kennung": "bv1"}, offen=False) == {}


def test_titel_wer_entscheidet_nach_freigabe():
    """E11: applyFunktionen setzt den Titel der Schaltfläche „Wer entscheidet“ mit Gremien und Ämtern nur, wenn die
    Freigabe „gremien“ zur Laufzeit gilt und die Fläche im HTML steht; sonst wie bisher."""
    teil = _teil(APP, r"^  const WER_TITEL = .*?;\n") + _teil(APP, r"^  function applyFunktionen\(fn, idx\) \{\n.*?\n  \}\n")
    code = """
const knopf = { title: "Wer entscheidet: Verfahrenswege in Zahlen" };
let flaeche = true, vorschau = false;
const vorhanden = (id) => id === "panel-gremien" && flaeche;
const $ = () => null;
const document = { querySelectorAll: () => [], querySelector: (s) => (s === '.menu-btn[data-mega="mega-entscheiden"]' ? knopf : null),
  documentElement: { dataset: {} } };
""" + teil + """
const aus = [];
applyFunktionen({ gremien: true }); aus.push(knopf.title);
applyFunktionen({ gremien: false }); aus.push(knopf.title);
flaeche = false; applyFunktionen({ gremien: true }); aus.push(knopf.title);
console.log(JSON.stringify(aus));
"""
    assert _node(code) == ["Wer entscheidet: Gremien, Ämter und Verfahrenswege in Zahlen",
                           "Wer entscheidet: Verfahrenswege in Zahlen", "Wer entscheidet: Verfahrenswege in Zahlen"]


# --- Filter „Gremium“ im Gebiet und in ganz Köln ------------------------------------------------------------------------

FILTER_TEILE = (r"^  const esc = .*?;\n", r"^  const GREMIUM_NAME = .*?;\n", r"^  const gremiumArt = .*?;\n",
                r"^  function gremiumWahl\(\) \{\n.*?\n  \}\n",
                r"^  function fillGremien\(\) \{\n.*?\n  \}\n", r"^  function gremiumKennzeichen\(\) \{\n.*?\n  \}\n")
# nachgebildetes <select> mit Optionen und Gruppen aus innerHTML (genug für fillGremien, gremiumWahl und gremiumFiltern)
SELECT = """
class Sel {
  constructor() { this.opts = []; this.wert = ""; this.html = ""; }
  set innerHTML(h) { this.html = h; this.opts = [...h.matchAll(/<option value="([^"]*)">([^<]*)<\\/option>/g)].map((m) => ({ value: m[1].replace(/&amp;/g, "&"), textContent: m[2].replace(/&amp;/g, "&") })); }
  get innerHTML() { return this.html; }
  get options() { return this.opts; }
  get selectedOptions() { return this.opts.filter((o) => o.value === this.wert); }
  get value() { return this.wert; }
  set value(v) { this.wert = this.opts.some((o) => o.value === v) ? v : ""; }
}
"""


def _filter(papers, aktionen):
    """fillGremien, gremiumWahl und gremiumKennzeichen aus app.js mit erfundenen Vorlagen; `aktionen`: JS, das `aus`
    füllt."""
    teil = "".join(_teil(APP, m) for m in FILTER_TEILE)
    code = SELECT + f"""
const sel = new Sel(), box = {{ hidden: true }}, name = {{ textContent: "" }}, art = {{ textContent: "" }};
const E = {{ "#f-gremium": sel, "#gremium-filter": box, "#gremium-filter-name": name, "#gremium-filter-art": art }};
const $ = (s) => E[s];
let papers = {json.dumps(papers)};
""" + teil + f"""
const aus = [];
{aktionen}
console.log(JSON.stringify(aus));
"""
    return _node(code)


def _station(gremium, key=None):
    return {"gremium": gremium, **({"gremium_key": key} if key else {})}


PAPERS = [{"reference": "1/2026", "process": [_station("Beispielrat", "rat"), _station("Früherer Probeausschuss")]},
          {"reference": "2/2026", "process": [_station("Ausschuss für Beispiele", "aus-a"), _station("Beispielfraktion")]},
          {"reference": "3/2026", "process": [_station("Ausschuss für Beispiele")]}]


def test_optionen_des_gremienfilters():
    """F12: Gremien mit Kennung haben die Kennung als Wert, übrige Namen aus den Beratungen den Wert „name:“ und Name;
    gibt es beides, stehen sie in zwei Gruppen (ein Name kann in beiden stehen); ohne Kennungen (Freigabe aus) eine
    Liste nach Namen wie bisher. Eine gewählte Angabe bleibt beim Wechsel des Gebiets, auch ohne Station dort."""
    mit, ohne, bleibt, kennzeichen = _filter(PAPERS, """
fillGremien(); aus.push(sel.innerHTML);
papers = papers.map((p) => ({ ...p, process: p.process.map(({ gremium_key, ...s }) => s) })); fillGremien(); aus.push(sel.innerHTML);
papers = """ + json.dumps(PAPERS) + """; fillGremien(); sel.value = "aus-a"; papers = []; fillGremien(); aus.push([sel.value, sel.innerHTML]);
aus.push([gremiumKennzeichen(), box.hidden, name.textContent]);
""")
    assert mit == ('<option value="">alle</option><optgroup label="aktuelle Gremien"><option value="aus-a">Ausschuss für Beispiele</option>'
                   '<option value="rat">Beispielrat</option></optgroup><optgroup label="nach Namen, auch frühere Gremien">'
                   '<option value="name:Ausschuss für Beispiele">Ausschuss für Beispiele</option>'
                   '<option value="name:Beispielfraktion">Beispielfraktion</option>'
                   '<option value="name:Früherer Probeausschuss">Früherer Probeausschuss</option></optgroup>')
    assert "optgroup" not in ohne and '<option value="name:Beispielrat">Beispielrat</option>' in ohne
    assert bleibt == ["aus-a", '<option value="">alle</option><option value="aus-a">Ausschuss für Beispiele</option>']
    assert kennzeichen == [{"key": "aus-a", "text": "Ausschuss für Beispiele"}, False, "Ausschuss für Beispiele"]


def test_filter_im_gebiet_ueber_die_kennung():
    """Plan 10: Im Gebiet filtert „Gremium“ über process[].gremium_key (Kennung) bzw. über den Namen (übrige Namen, wie
    bisher alle Stationen dieses Namens); #count nennt das Gremium; ohne Treffer ein Satz mit „In ganz Köln suchen“."""
    filt = _teil(APP, r"^  function filtered\(withRange = true\) \{\n.*?\n  \}\n")
    assert "(!gremium || (p.process || []).some((s) => (gremium.key ? s.gremium_key === gremium.key : s.gremium === gremium.name)))" in filt
    teil = "".join(_teil(APP, m) for m in FILTER_TEILE) + filt
    code = SELECT + f"""
const sel = new Sel(), box = {{ hidden: true }}, name = {{ textContent: "" }}, art = {{ textContent: "" }};
const leer = {{ value: "", checked: false }};
const E = {{ "#f-gremium": sel, "#gremium-filter": box, "#gremium-filter-name": name, "#gremium-filter-art": art, "#f-text": leer, "#f-type": leer, "#f-amt": leer,
  "#f-stand": leer, "#f-theme": leer, "#f-party": leer, "#f-related": leer }};
const $ = (s) => E[s];
const document = {{ querySelectorAll: () => [] }};
const area = {{ kind: "ohne", key: "2026" }}, relatedParties = () => new Set(), bestConfidence = () => "hoch", inRange = () => true;
let papers = {json.dumps(PAPERS)};
""" + teil + """
fillGremien();
const aus = [];
for (const v of ["aus-a", "rat", "name:Ausschuss für Beispiele", "name:Beispielfraktion"]) { sel.value = v; aus.push(filtered().map((p) => p.reference)); }
console.log(JSON.stringify(aus));
"""
    assert _node(code) == [["2/2026"], ["1/2026"], ["2/2026", "3/2026"], ["2/2026"]]
    render = _teil(APP, r"^  function render\(nurListe\) \{\n.*?\n  \}\n")
    assert "${list.length} von ${papers.length} Vorlagen · ${where}${gw ? ` · ${gremiumArt(gw)}: ${gw.text}` : \"\"}${span}" in render
    assert ("Im gewählten Gebiet passt keine Vorlage mit einer Beratung in „${esc(gw.text)}“ zu Filtern und Zeitraum."
            in render) and 'id="gremium-koeln">In ganz Köln suchen</button>' in render


def _global(search, wert, gremien_wahl=None, link=None):
    """renderGlobal aus app.js mit erfundenem suche.json; `wert`: Wert von #f-gremium (mit passender Option);
    `link`: Stand des Filters aus der Adresse („unbekannt“: Kennung ohne Gremium, „fehler“: gremien.json nicht
    geladen; gremiumLink, seit 23.11.2026 (2) (10) und der Nachprüfung)."""
    teil = "".join(_teil(APP, m) for m in FILTER_TEILE) + _teil(APP, r"^  const themeTags = .*?;\n") \
        + _teil(APP, r"^  const GREMIUM_HINWEIS = \{\n.*?\n  \};\n") + _teil(APP, r"^  function gremiumLinkOffen\(\) \{\n.*?\n  \}\n") \
        + _teil(APP, r"^  const mitGremiumHinweis = \(text\) => \{\n.*?\n  \};\n") \
        + _teil(APP, r"^  function renderGlobal\(nurListe\) \{\n.*?\n  \}\n")
    code = SELECT + f"""
const sel = new Sel(), box = {{ hidden: true }}, name = {{ textContent: "" }}, art = {{ textContent: "" }}, count = {{ textContent: "" }}, liste = {{ innerHTML: "" }};
const leer = {{ value: "", checked: false }};
let gremiumLink = {json.dumps({"wert": "x", "stand": link, "filter": None} if link else None)};
const werDa = () => true;
const E = {{ "#f-gremium": sel, "#gremium-filter": box, "#gremium-filter-name": name, "#gremium-filter-art": art, "#f-text": leer, "#f-type": leer,
  "#f-stand": leer, "#f-theme": leer, "#f-party": leer, "#f-related": leer, "#count": count, "#papers": liste }};
const $ = (s) => E[s];
const search = {json.dumps(search)}, THEMES = {{}}, LIST_STEP = 50, VORSCHAU_LISTE = "";
let shown = 50, range = null, docHits = null, selected = null, vorschau = false, openMegaId = null;
const fmtDate = (d) => d, drawMarkers = () => {{}}, papers = [];
sel.innerHTML = '<option value="">alle</option><option value="{wert}">{gremien_wahl or wert}</option>';
sel.value = {json.dumps(wert)};
""" + teil + """
renderGlobal();
console.log(JSON.stringify({ count: count.textContent, html: liste.innerHTML, kennzeichen: !box.hidden, art: art.textContent }));
"""
    return _node(code)


def _zeile(ref, gebiet, namen, kennungen):
    return [ref, f"[Test] {ref}", "2026-11-01", 0, 0, gebiet, [], [], [], -1, namen, kennungen]


SUCHE = {"meta": {}, "themes": [], "parties": [], "types": ["Mitteilung"], "stands": ["offen"],
         "areas": [{"key": "ortsteil:probedorf", "name": "Probedorf"}], "aemter": [],
         "gremien": ["Ausschuss für Beispiele", "Beispielrat"], "gremium_keys": ["aus-a", "rat"],
         "rows": [_zeile("1/2026", 0, [1], [1]), _zeile("2/2026", 0, [0, 1], [0, 1]), _zeile("3/2026", -1, [0], [0]),
                  _zeile("4/2026", 0, [0], [])]}


def test_filter_in_ganz_koeln_ueber_spalte_11():
    """F11, E10: In ganz Köln filtert „Gremium“ über gremium_keys und Spalte 11 von suche.json (die Namen in Spalte 10
    haben eine andere Reihenfolge), ein Name über Spalte 10; das Kennzeichen ist sichtbar, #count nennt das Gremium;
    eine Zeile mit Gebiet −1 bricht nichts ab und erscheint ohne Schaltfläche."""
    rat = _global(SUCHE, "rat", "Beispielrat")
    assert re.findall(r'data-gref="([^"]+)"', rat["html"]) == ["1/2026", "2/2026"]
    assert rat["count"] == "2 Treffer in ganz Köln · Gremium: Beispielrat" and rat["kennzeichen"]
    aus_a = _global(SUCHE, "aus-a", "Ausschuss für Beispiele")
    assert re.findall(r'data-gref="([^"]+)"', aus_a["html"]) == ["2/2026"]
    assert '<li><div class="ohne-gebiet"><span class="title">[Test] 3/2026</span>' in aus_a["html"]
    assert "ohne Gebiet im Ratsatlas, deshalb ohne Vorgang" in aus_a["html"] and aus_a["count"].startswith("2 Treffer")
    nach_name = _global(SUCHE, "name:Ausschuss für Beispiele", "Ausschuss für Beispiele")
    assert re.findall(r'data-gref="([^"]+)"', nach_name["html"]) == ["2/2026", "4/2026"]
    ohne = _global(SUCHE, "", "")
    assert ohne["count"] == "4 Treffer in ganz Köln" and not ohne["kennzeichen"] and ohne["html"].count("data-gref=") == 3


def test_filter_in_ganz_koeln_ohne_treffer_und_ohne_spalte():
    """Ein Gremium ohne Kennung in gremium_keys (keine Station mit dieser Kennung) und eine Datei ohne gremium_keys und
    Spalte 11 (Freigabe beim Export aus): kein Absturz, 0 Treffer und ein Satz statt einer leeren Liste; mit anderen
    Filtern ohne Treffer der Satz zu Filtern und Zeitraum."""
    fehlt = _global(SUCHE, "bv9", "Bezirksvertretung 9")
    assert fehlt["count"] == "0 Treffer in ganz Köln · Gremium: Bezirksvertretung 9"
    assert "Für „Bezirksvertretung 9“ ist im Suchindex keine Beratung einer Vorlage verzeichnet." in fehlt["html"]
    ohne_spalte = {**{k: v for k, v in SUCHE.items() if k != "gremium_keys"}, "rows": [r[:11] for r in SUCHE["rows"]]}
    alt = _global(ohne_spalte, "rat", "Beispielrat")
    assert alt["count"].startswith("0 Treffer") and "keine Beratung einer Vorlage verzeichnet" in alt["html"]
    leer = _global({**SUCHE, "rows": [_zeile("9/2026", 0, [1], [0])]}, "rat", "Beispielrat")
    assert "In ganz Köln passt keine Vorlage mit einer Beratung in „Beispielrat“ zu Filtern und Zeitraum." in leer["html"]


def test_knopf_vorlagen_dieses_gremiums():
    """F11, E10: Der Knopf setzt den Filter über die Kennung (Option bei Bedarf ergänzt), setzt die übrigen Filter und
    den Zeitraum zurück, sucht im gewählten Gebiet oder ohne Gebiet in ganz Köln, schließt die Fläche und gibt der Liste
    den Fokus; das Kennzeichen hat eine Schaltfläche zum Entfernen."""
    knopf = _teil(APP, r"^  function gremiumFiltern\(key, name\) \{\n.*?\n  \}\n")
    for teil in ('setPanel("panel-gremien", false);', '$("#filters").reset();', "range = null;",
                 'setScope(area && area.kind !== STADT ? "gebiet" : STADT);', "appendChild(new Option(name || key, key))",
                 "sel.value = key;", 'setPanel("panel-list", true);', 'focusPanel("panel-list");'):
        assert teil in knopf, teil
    kennzeichen = _abschnitt(INDEX, "gremium-filter")
    assert '<button type="button" class="icon-btn" id="gremium-filter-aus" aria-label="Filter „Gremium“ entfernen">' in kennzeichen
    assert INDEX.index('id="gremium-filter"') < INDEX.index('id="count"')
    assert 'filterGremium: gremiumFiltern' in APP


# --- „In Zahlen“, „Was ist neu?“, Quellenzeile ---------------------------------------------------------------------------

def test_in_zahlen_statt_auswertung():
    """F2 und (14): Die Fläche heißt sichtbar „In Zahlen“ (Überschrift, Schaltfläche zum Schließen, Reiterleiste); die
    Kennungen bleiben; „Auswertung“ steht in index.html nur noch in einem Kommentar zur Herkunft."""
    flaeche = _abschnitt(INDEX, "panel-auswertung")
    assert '<h2 id="auswertung-heading" tabindex="-1">In Zahlen</h2>' in flaeche
    assert 'aria-label="In Zahlen schließen"' in flaeche and '<div class="tabs" role="tablist" aria-label="In Zahlen">' in flaeche
    for kennung in ('id="tab-stats"', 'id="tab-wege"', 'id="stats"', 'id="wege"'):
        assert kennung in flaeche, kennung
    ohne_kommentare = re.sub(r"<!--.*?-->", "", INDEX, flags=re.S)
    assert "Auswertung" not in ohne_kommentare
    assert "function openAuswertung(tab, focusTab)" in APP
    # Nachprüfung 4b: auch Kommentare in app.js und style.css und die Prüfnamen und Kommentare der Browserprüfungen
    # sagen „In Zahlen“; „Auswertung“ bleibt nur als Teil einer Kennung (openAuswertung, menueUeberAuswertung)
    wort = re.compile(r"(?<![\w-])Auswertung")
    for datei in ("site/app.js", "site/style.css", "tests/browser/bedienung.js", "tests/browser/navigation.js"):
        assert not wort.search((ROOT / datei).read_text(encoding="utf-8")), datei


def test_was_ist_neu():
    """„Was ist neu?“: drei neue Einträge (Kalender mit abgesagten Sitzungen laut Namen, „Wer entscheidet“ mit Gremien
    und Ämtern nur mit Freigabe „gremien“ auf eigener Zeile, „In Zahlen“); ohne Freigabe fehlt der Eintrag zu Gremien
    und Ämtern im veröffentlichten HTML, kein „folgt“."""
    neu = _abschnitt(INDEX, "neu")
    eintraege = re.findall(r"^\s*<li( data-funktion=\"\w+\")?>(.*?)</li>$", neu, re.M)
    assert len(eintraege) == 8 and eintraege[7][1].startswith("Bonner Zusatzthemen")
    assert eintraege[4] == ("", "Im Kalender (termine.ics) stehen Sitzungen, die laut Sitzungsnamen abgesagt sind, als abgesagt, "
                                "mit dem Zusatz „(laut Sitzungsnamen abgesagt)“.")
    assert eintraege[5][0] == ' data-funktion="gremien"' and eintraege[5][1].startswith("„Wer entscheidet“ mit den Reitern „Gremien“")
    # nur Schritte mit gremium_key werden zum Link, also nur aktuelle Gremien (Nachprüfung 4b)
    assert "im Vorgang führt der Name eines aktuellen Gremiums dorthin" in eintraege[5][1]
    assert eintraege[6] == ("", "Die Fläche mit den Kennzahlen zum Gebiet und den Verfahrenswegen heißt jetzt „In Zahlen“.")
    assert not re.search(r"\bfolg(t|en)\b", _text(neu))


def test_was_ist_neu_und_quellenzeile_ohne_freigabe(monkeypatch):
    """Ohne Freigabe „gremien“ entfernt der Bau den Eintrag in „Was ist neu?“ (seo.AUS_BLOCK) und die beiden Teile der
    Quellenzeile (seo.AUS_SATZ); mit Freigabe bleibt alles."""
    an = seo.ohne_abgeschaltete(INDEX)
    assert config.ZUSATZTHEMEN["gremien"] is True and an.count('data-funktion="gremien"') == INDEX.count('data-funktion="gremien"')
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    aus = seo.ohne_abgeschaltete(INDEX)
    assert 'data-funktion="gremien"' not in aus and "Zuständigkeitsordnung" not in _abschnitt(aus, "sources")
    assert "„Wer entscheidet“ mit den Reitern" not in aus
    quellen = _text(_abschnitt(aus, "sources"))
    assert ("Dezernatsverteilungsplan der Stadt Köln (im Plan keine Lizenz angegeben, übernommen sind nur Nummern und "
            "Bezeichnungen): zur federführenden Dienststelle, nur für Vorlagen aus der Zeit vom Stand des Plans bis zu seiner "
            "letzten Prüfung (Stand und letzte Prüfung auf der Seite „So funktioniert der Ratsatlas“) · Kennung der "
            "federführenden Dienststelle") in quellen


def test_anfrage_punkt_7_weiterleitung_und_standzeile():
    """E5: Punkt 7 der Anfrage bittet, die beiden Fragen weiterzuleiten, falls sie nicht in die Zuständigkeit der
    Empfänger fallen (im Brief in der Höflichkeitsform); die Standzeile richtet sich an den Auftraggeber und sagt daher
    „der Empfänger“, nicht „Ihre“ (Nachprüfung 4b)."""
    text = (ROOT / "explore" / "ANFRAGE_stadt_koeln.md").read_text(encoding="utf-8")
    stand = next(z for z in text.splitlines() if z.startswith("> Stand "))
    assert stand.startswith("> Stand 23.11.2026: Punkt 7 um die Bitte ergänzt, die Fragen an die zuständigen Stellen "
                            "weiterzuleiten, falls sie nicht in die Zuständigkeit der Empfänger fallen (")
    assert not re.search(r"\bIhr(e|en|er)?\b", stand)
    p7 = re.search(r"^7\. \*\*Geschäfts- und Dezernatsverteilungsplan und Zuständigkeitsordnung:\*\* (.+)$", text, re.M).group(1)
    assert p7.endswith("Falls diese beiden Fragen nicht in Ihre Zuständigkeit fallen, bitte ich Sie, sie an die zuständigen "
                       "Stellen weiterzuleiten.")


def test_quellenzeile():
    """Plan 13: „Nummern und Bezeichnungen“ statt „Kennungen und Bezeichnungen“ (wie aemter.LIZENZ_AUFBAU, README und
    Technikseite); mit Freigabe nennt die Zeile den Reiter „Ämter“ und die Zuständigkeitsordnung (nur der Paragraf, kein
    Text, Lizenz nicht geklärt)."""
    quellen = _abschnitt(INDEX, "sources")
    assert "Kennungen und Bezeichnungen" not in quellen and "übernommen sind nur Nummern und Bezeichnungen)" in quellen
    # seit 23.11.2026 (2) (9) vor „zur federführenden Dienststelle“, damit er sich nicht auf die Technikseite bezieht
    assert '<span data-funktion="gremien"> im Reiter „Ämter“ unter „Wer entscheidet“ und</span> zur federführenden Dienststelle' in quellen
    assert ('<span data-funktion="gremien"> · Paragrafen der Ausschüsse aus der Zuständigkeitsordnung der Stadt Köln vom '
            '02.06.2026 (zugeordnet über den Namen des Ausschusses; nur der Paragraf, kein Text; Lizenz nicht geklärt)</span>') in quellen


# --- Nachprüfung Bedienung (23.11.2026): Steuerung der Fläche, Ladefehler, Telefonbreite, Statuszeile -----------------

def _steuerung(ablauf):
    """Steuerung von site/gremien.js mit einem nachgebildeten Dokument (Reiter, Umschalter, Inhalt, Statuszeile als
    einfache Objekte), Zeitgebern und Abrufen von Hand; `ablauf` ist der Rumpf einer async-Funktion, die `ergebnis`
    setzt. Daten: die erfundenen G und A."""
    code = f"""
import * as M from "{GREMIEN_JS.as_uri()}";
const G = {json.dumps(GREMIEN)}, A = {json.dumps(AEMTER)};
const handler = {{}};
let aktiv = null;
const knoten = (name, extra = {{}}) => {{
  const e = {{ name, hidden: false, attrs: {{}}, tabIndex: 0, dataset: {{}}, gesetzt: 0, _html: "",
    setAttribute(k, v) {{ this.attrs[k] = String(v); }}, getAttribute(k) {{ return this.attrs[k] ?? null; }},
    addEventListener(typ, f) {{ (handler[name + ":" + typ] ||= []).push(f); }},
    focus() {{ aktiv = this; }}, closest() {{ return null; }}, contains(x) {{ return x === this; }},
    querySelector() {{ return null; }}, querySelectorAll() {{ return []; }}, ...extra }};
  Object.defineProperty(e, "innerHTML", {{ get() {{ return this._html; }}, set(v) {{ this._html = v; this.gesetzt++; }} }});
  return e;
}};
// Ausgangszustand wie in index.html: Reiter „Gremien“ gewählt, Optionsfeld „Schaubild“ an
const tabs = ["gremien", "aemter"].map((t, i) => knoten("tab-" + t, {{ dataset: {{ werTab: t }}, attrs: {{ "aria-selected": String(!i) }}, tabIndex: i ? -1 : 0,
  closest(s) {{ return s.startsWith("[role=tab]") ? this : null; }} }}));
const radios = ["schaubild", "liste"].map((d, i) => knoten("radio-" + d, {{ dataset: {{ darstellung: d }}, attrs: {{ "aria-checked": String(!i) }}, tabIndex: i ? -1 : 0,
  closest(s) {{ return s === "[data-darstellung]" ? this : null; }} }}));
const tabliste = knoten("tablist", {{ querySelectorAll: () => tabs }});
const schalter = knoten("schalter", {{ querySelectorAll: () => radios, contains: (x) => radios.includes(x),
  querySelector: (s) => radios.find((r) => s.includes(`"${{r.dataset.darstellung}}"`)) || null }});
const liste = knoten("liste"), drinnen = knoten("im-inhalt");
const body = knoten("body", {{ querySelector: (s) => (s === "#wer-liste" ? liste : null), contains: (x) => x === drinnen }});
const status = knoten("status");
const root = knoten("root", {{ querySelectorAll: (s) => (s === "[role=tab][data-wer-tab]" ? tabs : []),
  querySelector: (s) => ({{ "[role=tablist]": tabliste, ".wer-darstellung": schalter, "#wer-body": body, "#wer-status": status }})[s]
    || (s === '.wer-darstellung [aria-checked="true"]' ? radios.find((r) => r.attrs["aria-checked"] === "true") : null) }});
globalThis.document = {{ getElementById: (id) => (id === "panel-gremien" ? root : null), get activeElement() {{ return aktiv; }} }};
globalThis.CSS = {{ escape: (s) => s }};
const zeitgeber = new Map();
let nr = 0;
globalThis.setTimeout = (f) => {{ zeitgeber.set(++nr, f); return nr; }};
globalThis.clearTimeout = (n) => {{ zeitgeber.delete(n); }};
const zeitAblaufen = () => {{ const fs = [...zeitgeber.values()]; zeitgeber.clear(); fs.forEach((f) => f()); }};
const wartend = [];
globalThis.fetch = (url) => new Promise((ok) => wartend.push(() => ok({{ ok: true, status: 200, json: async () => (url.endsWith("gremien.json") ? G : A) }})));
const freigeben = async () => {{ wartend.splice(0).forEach((f) => f()); await new Promise((r) => setImmediate(r)); }};
let telefon = false;
const ctx = {{ basis: "", heute: () => "2026-11-23", zeitDatum: (s) => s, lizenz: (t) => t, telefon: () => telefon, onState() {{}}, filterGremium() {{}} }};
const feuern = (name, typ, target) => (handler[name + ":" + typ] || []).forEach((f) => f({{ target, preventDefault() {{}} }}));
const gewaehlt = () => tabs.find((t) => t.attrs["aria-selected"] === "true").dataset.werTab;
const geladen = async () => {{ const l = M.init(ctx); await freigeben(); await l; }};
let ergebnis = null;
await (async () => {{
{ablauf}
}})();
console.log(JSON.stringify(ergebnis));
"""
    return _node(code, modul=True)


def test_wahl_waehrend_des_ladens_gilt_danach():
    """Reiter und Umschalter wirken schon während des Ladens (vorher gingen Klicks verloren, der Fokus stand danach auf
    einem nicht gewählten Reiter): Die Wahl steht sofort an Reiter bzw. Optionsfeld, der Inhalt bleibt bis zum Laden
    leer, und nach dem Laden geht sie dem Reiter bzw. der Darstellung vor, mit denen die Fläche geöffnet wurde (app.js
    ruft show zweimal auf); ein späteres Öffnen gilt wieder."""
    r = _steuerung("""
const laden = M.init(ctx);
feuern("tablist", "click", tabs[1]);
const beim = { reiter: gewaehlt(), tabindex: tabs.map((t) => t.tabIndex), inhalt: body.gesetzt };
await freigeben(); await laden;
M.show({}); M.show({ tab: "gremien" });
const danach = { reiter: gewaehlt(), inhalt: body.innerHTML.includes("wer-dezernat") };
M.show({ tab: "gremien" });
ergebnis = { beim, danach, spaeter: gewaehlt() };
""")
    assert r == {"beim": {"reiter": "aemter", "tabindex": [-1, 0], "inhalt": 0}, "danach": {"reiter": "aemter", "inhalt": True},
                 "spaeter": "gremien"}
    r = _steuerung("""
const laden = M.init(ctx);
feuern("schalter", "click", radios[1]);
const beim = radios.map((b) => b.attrs["aria-checked"]);
await freigeben(); await laden;
M.show({}); M.show({ tab: "gremien", darstellung: "schaubild" });
ergebnis = { beim, zustand: M.werZustand(), liste: body.innerHTML.includes('id="wer-liste"') };
""")
    assert r == {"beim": ["false", "true"], "zustand": {"tab": "gremien", "darstellung": "liste", "kennung": None}, "liste": True}


def test_aufgeloestes_gremium_liste_und_hinweis_im_schaubild():
    """Ein aufgelöstes Gremium steht nur in der Liste (F5): Ohne gewählte Darstellung öffnet seine Kennung die Liste mit
    „frühere Gremien zeigen“ (darstellung=liste in der Adresse), ein aktuelles Gremium ändert die Darstellung nicht; im
    Schaubild (ausdrücklich gewählt) steht statt seiner Angaben ein Hinweis auf die Liste, ohne Überschrift."""
    r = _steuerung("""
await geladen();
M.show({ tab: "gremien", kennung: "bv1" });
const aktuell = M.werZustand();
M.show({ tab: "gremien", kennung: "alt" });
const alt = { zustand: M.werZustand(), haekchen: body.innerHTML.includes('id="wer-frueher" checked'), offen: body.innerHTML.includes('data-kennung="alt" open') };
M.show({ tab: "gremien", darstellung: "schaubild", kennung: "alt" });
ergebnis = { aktuell, alt, bild: { zustand: M.werZustand(), h3: body.innerHTML.includes(">Früherer Probeausschuss</h3>"),
  hinweis: body.innerHTML.includes('<div class="pz-detail" id="wer-detail"><p class="hint">Das gewählte Gremium „Früherer Probeausschuss“ ist aufgelöst; es steht in der Liste unter „frühere Gremien zeigen“.</p></div>') } };
""")
    assert r["aktuell"] == {"tab": "gremien", "darstellung": None, "kennung": "bv1"}
    assert r["alt"] == {"zustand": {"tab": "gremien", "darstellung": "liste", "kennung": "alt"}, "haekchen": True, "offen": True}
    assert r["bild"] == {"zustand": {"tab": "gremien", "darstellung": "schaubild", "kennung": "alt"}, "h3": False, "hinweis": True}
    detail = _modul('M.detailHtml(G, { kennung: "alt" }, U)')
    assert detail == '<p class="hint">Das gewählte Gremium „Früherer Probeausschuss“ ist aufgelöst; es steht in der Liste unter „frühere Gremien zeigen“.</p>'


def test_breite_baut_nur_bei_anderer_darstellung_neu():
    """breite() (app.js applyLayout) baut den Inhalt nur neu auf, wenn sich die Darstellung ohne ausdrückliche Wahl
    ändert (vorher bei jeder Breitengrenze, der Fokus fiel auf <body>); lag der Fokus im Inhalt, steht er danach in der
    Fläche (hier ohne Eintrag oder Suchfeld im nachgebildeten Dokument: auf dem gewählten Optionsfeld), außerhalb bleibt
    er, wo er ist. Mit ausdrücklicher Wahl und im Reiter „Ämter“ kein Neuaufbau."""
    r = _steuerung("""
await geladen();
M.show({ tab: "gremien" });
const n = [body.gesetzt];
M.breite(); n.push(body.gesetzt);
aktiv = drinnen; telefon = true; M.breite(); n.push(body.gesetzt);
const fokus1 = aktiv.name;
M.breite(); n.push(body.gesetzt);
aktiv = tabs[0]; telefon = false; M.breite(); n.push(body.gesetzt);
const fokus2 = aktiv.name;
M.show({ darstellung: "schaubild" }); n.push(body.gesetzt);
telefon = true; M.breite(); n.push(body.gesetzt);
M.show({ tab: "aemter", darstellung: undefined }); n.push(body.gesetzt);
ergebnis = { n, fokus1, fokus2 };
""")
    a = r["n"][0]
    assert r["n"] == [a, a, a + 1, a + 1, a + 2, a + 3, a + 3, a + 4]
    assert r["fokus1"] == "radio-liste" and r["fokus2"] == "tab-gremien"


def test_verzoegerter_zaehler_endet_mit_dem_wechsel():
    """Der Zähler der Liste nach dem Tippen (400 ms) endet mit jeder neuen Meldung, also auch beim Wechsel von Reiter
    oder Darstellung (vorher stand danach etwa „12 Gremien“ im Reiter „Ämter“); in der Liste zählt er weiter."""
    r = _steuerung("""
await geladen();
M.show({ tab: "gremien", darstellung: "liste" });
feuern("body", "input", { id: "wer-q", value: "bez" });
const vorher = zeitgeber.size;
feuern("tablist", "click", tabs[1]);
const nachWechsel = zeitgeber.size;
zeitAblaufen();
const aemter = status.textContent;
feuern("tablist", "click", tabs[0]);
feuern("body", "input", { id: "wer-q", value: "bez" });
zeitAblaufen();
ergebnis = { vorher, nachWechsel, aemter, liste: status.textContent };
""")
    assert r == {"vorher": 1, "nachWechsel": 0, "aemter": "", "liste": "1 Gremium"}


def _oeffnen(ablauf):
    """openGremien aus app.js mit nachgebildeten Teilen; import(modul) ruft `importieren` auf (Adressen in `adressen`)."""
    teil = _teil(APP, r"^  const WARTEZEIT = .*?;\n") + _teil(APP, r"^  const mitFrist = .*?\n  \}\);\n") \
        + _teil(APP, r"^  let werState = null, werReady = null, werModul = null, werImportFehler = 0;\n.*?^  function openGremien\(s\) \{\n.*?\n  \}\n")
    assert teil.count("import(modul)") == 1
    code = """
const E = { "#wer-body": { innerHTML: "alt" }, "#wer-status": { textContent: "" } };
const $ = (s) => E[s];
let funktionen = { gremien: true };
const vorhanden = () => true, BONN = "data/", heute = () => "2026-11-23", zeitDatum = (s) => s, lizenzOeffentlich = (t) => t;
const MOBILE = { matches: false }, syncUrl = () => {}, gremiumFiltern = () => {};
const adressen = [], gezeigt = [], plan = [];
let initFehler = 0;
const modul = { show: (s) => gezeigt.push(s), async init() { if (initFehler > 0) { initFehler--; throw new Error("Daten"); } } };
const importieren = (u) => { adressen.push(u); return plan.shift() === "fehler" ? Promise.reject(new Error("Netz")) : Promise.resolve(modul); };
""" + teil.replace("import(modul)", "importieren(modul)") + """
(async () => {
""" + ablauf + """
  console.log(JSON.stringify(ergebnis));
})();
"""
    return _node(code)


SATZ = "Die Angaben zu Gremien und Ämtern konnten nicht geladen werden. Beim nächsten Öffnen versucht der Ratsatlas es erneut."


def test_ladefehler_in_der_statuszeile_und_neuer_import():
    """Ladefehler: Der Satz steht in der Statuszeile (role=status, dort stand auch „Wird geladen …“; vorher nur im Inhalt
    ohne Live-Region, also nicht angesagt), der Inhalt bleibt leer. Nach einem gescheiterten Import lädt der nächste
    Versuch das Modul unter einer anderen Adresse (der Browser merkt sich den Fehler für dieselbe Adresse); nach einem
    Fehler beim Laden der Daten dieselbe Adresse."""
    r = _oeffnen("""
  plan.push("fehler");
  const r1 = await openGremien({ tab: "gremien" });
  const nach1 = { r: r1, status: E["#wer-status"].textContent, inhalt: E["#wer-body"].innerHTML };
  await openGremien({ tab: "aemter" });
  ergebnis = { nach1, adressen, gezeigt, status: E["#wer-status"].textContent };
""")
    assert r == {"nach1": {"r": None, "status": SATZ, "inhalt": ""}, "adressen": ["./gremien.js", "./gremien.js?versuch=1"],
                 "gezeigt": [{"tab": "aemter"}], "status": "Wird geladen …"}
    r = _oeffnen("""
  initFehler = 1;
  await openGremien({ tab: "gremien" });
  const status1 = E["#wer-status"].textContent;
  await openGremien({ tab: "gremien" });
  ergebnis = { status1, adressen, gezeigt };
""")
    assert r == {"status1": SATZ, "adressen": ["./gremien.js", "./gremien.js"], "gezeigt": [{"tab": "gremien"}]}


def test_telefonbreite_behaelt_die_flaeche_mit_dem_fokus():
    """applyLayout beim Wechsel auf Telefonbreite (nur eine Fläche): Es bleibt die Fläche mit dem Fokus, sonst eine
    offene Überlagerung, sonst die erste offene (vorher immer die erste in SHEETS: neben dem Vorgang ging „Gremien und
    Ämter“ zu, der Fokus fiel auf <body>)."""
    teil = _teil(APP, r"^  function applyLayout\(\) \{\n.*?\n  \}\n")
    code = """
const SHEETS = ["panel-list", "panel-detail", "panel-auswertung", "panel-gremien", "timeline-wrap"], OVERLAYS = ["panel-auswertung", "panel-gremien"];
const P = Object.fromEntries(SHEETS.map((id) => [id, { id, hidden: true, classList: { toggle() {} }, contains: (x) => Boolean(x) && x.in === id }]));
const $ = (s) => P[s.slice(1)];
const document = { getElementById: (id) => P[id], activeElement: null };
const MOBILE = { matches: true }, NARROW = { matches: true };
const setPanel = (id, open) => { P[id].hidden = !open; };
const setMapMenu = () => {}, setNav = () => {}, clampWidths = () => {}, vorhanden = (id) => id in P;
let tl = null, selected = null, werModul = null;
""" + teil + """
const fall = (offen, fokusIn) => { SHEETS.forEach((id) => { P[id].hidden = !offen.includes(id); }); document.activeElement = { in: fokusIn };
  applyLayout(); return SHEETS.filter((id) => !P[id].hidden); };
console.log(JSON.stringify([fall(["panel-detail", "panel-gremien"], "panel-gremien"), fall(["panel-detail", "panel-gremien"], "panel-detail"),
  fall(["panel-detail", "panel-gremien"], null), fall(["panel-list", "panel-detail"], null), fall(["panel-list", "timeline-wrap"], "timeline-wrap")]));
"""
    assert _node(code) == [["panel-gremien"], ["panel-detail"], ["panel-gremien"], ["panel-list"], ["timeline-wrap"]]


def test_statuszeile_abgeleitet_zuruecksetzen_und_adresse():
    """style.css: Die Statuszeile schrumpft in der Flex-Spalte der Überlagerung nicht (vorher min-height: 0, ihr Text
    lag über dem Inhalt); das Kennzeichen „abgeleitet, …“ in den Angaben zu einem Gremium darf umbrechen (sonst bei
    320 px waagrecht scrollen). app.js: „Filter und Zeitraum zurücksetzen“ in der leeren Liste setzt den Fokus auf die
    Liste (die Schaltfläche verschwindet); ein Gremium aus der Adresse wird ins Bild gerollt (zeigen)."""
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    # seit 23.11.2026 (2) (11) dieselbe Regel für die Statuszeile von „Mitmachen in Köln“
    assert ".wer-status, .bt-status { margin: 0 18px 6px; flex: none; }\n" in css and not re.search(r"\.wer-status[^{]*\{[^}]*min-height", css)
    assert ".pz-facts .derived { display: inline-block; max-width: 100%; white-space: normal; }\n" in css
    assert 'if (e.target.closest("#reset-filters")) { resetFilters(); focusPanel("panel-list"); return; }' in APP
    assert _teil(APP, r"^  function resetFilters\(\) \{\n.*?\n  \}\n").count("focusPanel") == 0   # „Zurücksetzen“ im Menü behält den Fokus
    gjs = GREMIEN_JS.read_text(encoding="utf-8")
    assert "else if (s.zeigen) eintragZeigen();" in gjs and 'el.scrollIntoView({ block: "nearest" })' in gjs
