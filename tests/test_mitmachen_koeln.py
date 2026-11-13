"""Zweiter Lauf, „Mitmachen in Köln“ (Beginn am 13.11.2026 freigegeben): Fläche site/beteiligung.js mit Kölner Inhalt
statt der Bonner Fassung (Regelwerk aus soll.json, Bonner Stadtbezirke, Link auf bonn.de). Geprüft ohne Anfragen nach
außen: keine Bonner Reste, nur geprüfte Adressen (Liste mit Abrufdatum in TECHNIK.md), Darstellung je Stadtbezirk mit
den Kölner Gremiennamen, Unterschriften laut Bekanntmachung, keine Anfrage der Fläche (CSP connect-src 'self'),
Freigabe und Texte in Glossar, Menü und Vorgang."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import build, config, geocode, glossar, seo

ROOT = Path(__file__).resolve().parents[1]
MODUL = ROOT / "site" / "beteiligung.js"
QUELLE = MODUL.read_text(encoding="utf-8")
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
TECHNIK = (ROOT / "TECHNIK.md").read_text(encoding="utf-8")
ERLAUBTE_HOSTS = {"www.stadt-koeln.de", "recht.nrw.de"}
URL = re.compile(r"https?://[^\s\"'`<>)]+")


def _abschnitt_technik():
    m = re.search(r"^## Mitmachen in Köln.*?(?=^## )", TECHNIK, re.S | re.M)
    assert m, "TECHNIK.md: Abschnitt „Mitmachen in Köln“ fehlt"
    return m.group(0)


def _bv_bezirk_js():
    """bvBezirk und BV_NUMMER aus site/app.js (eine Quelle für Termine und Fläche)."""
    teil = re.search(r"^  const BV_NUMMER = .*?\n  function bvBezirk\(name\) \{\n.*?\n  \}\n", APP, re.S | re.M)
    assert teil, "app.js: bvBezirk fehlt"
    return teil.group(0)


def _node_modul(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    quelle = f'import * as m from "{MODUL.as_uri()}";\n{_bv_bezirk_js()}\n{code}'
    r = subprocess.run([node, "--input-type=module", "-e", quelle], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


SITZUNGEN = [
    {"date": "2026-11-20", "time": "17:00", "gremium": "Bezirksvertretung 1 (Innenstadt)", "web": "https://example.invalid/bv1"},
    {"date": "2026-11-18", "time": "17:00", "gremium": "Bezirksvertretung 4 (Ehrenfeld)", "web": "javascript:alert(1)"},
    {"date": "2026-11-16", "time": "15:30", "gremium": "Bezirksvertretung 1 (Innenstadt)", "cancelled": True, "web": "https://example.invalid/abgesagt"},
    {"date": "2026-11-10", "time": "17:00", "gremium": "Bezirksvertretung 1 (Innenstadt)", "web": "https://example.invalid/vorbei"},
    {"date": "2026-12-03", "time": "15:30", "gremium": "Rat", "web": "https://example.invalid/rat"},
    {"date": "2026-11-26", "time": "15:30", "gremium": "Rat", "web": None},
    {"date": "2026-11-24", "time": "16:00", "gremium": "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden", "web": None},
]


def _darstellung():
    return _node_modul(f"""
const S = {json.dumps(SITZUNGEN)};
const o = (termine) => ({{ termine, meetings: S, heute: "2026-11-13", bvBezirk }});
console.log(JSON.stringify({{
  innenstadt: m.inhalt("Innenstadt", o(true)), ohne: m.inhalt("", o(true)), vorschau: m.inhalt("Ehrenfeld", o(false)),
  chorweiler: m.inhalt("Chorweiler", o(true)), ehrenfeld: m.inhalt("Ehrenfeld", o(true)), fremd: m.inhalt("Bonn", o(true)),
  bezirke: m.BEZIRKE, quorum: m.QUORUM, quellen: m.QUELLEN, stand: m.STAND,
}}));
""")


def test_ohne_bonner_reste():
    """Die Fläche kennt weder das Bonner Regelwerk noch Bonner Bezirke, Adressen oder Fristen; der Code (ohne
    Kommentare) und jede Darstellung nennen Bonn nicht, auch nicht „Bürgerantrag“ (Bonner Wort für § 24 GO NRW)."""
    code = re.sub(r"^\s*//.*$", "", QUELLE, flags=re.M)
    for wort in ("Bonn", "bonn.de", "soll.json", "loadSoll", "Bürgerantrag", "21 Tage", "openGremium", "openPlaene",
                 "Bad Godesberg", "Beuel", "Hardtberg", "mitwirken.js"):
        assert wort not in code, wort
    d = _darstellung()
    for name in ("innenstadt", "ohne", "vorschau", "chorweiler", "fremd"):
        for wort in ("Bonn", "Bürgerantrag", "21 Tage", '<p class="hint">Frist:', "T ist der Sitzungstag", "abgeleitet"):
            assert wort not in d[name], (name, wort)
    # app.js: die Fläche bekommt kein Soll-Modell mehr und heißt „Mitmachen in Köln“
    teil = re.search(r"function openMitmachen\(s\) \{.*?\n  \}\n", APP, re.S).group(0)
    assert "loadSoll" not in teil and "openGremium" not in teil and "Innenstadt" not in teil
    assert "Mitmachen in Bonn" not in APP and "Mitmachen in Bonn" not in (ROOT / "site" / "style.css").read_text(encoding="utf-8")


def test_nur_gepruefte_adressen():
    """Jede Adresse der Fläche (und der Link im Vorgang) steht mit Abrufdatum 13.11.2026 in TECHNIK.md, Abschnitt
    „Mitmachen in Köln“, und liegt bei der Stadt Köln oder recht.nrw.de; nie die Hosts der OParl-API."""
    abschnitt = _abschnitt_technik()
    adressen = set(URL.findall(QUELLE))
    (vorgang,) = re.findall(r'const BUERGERANTRAG = "([^"]+)"', APP)
    adressen.add(vorgang)
    assert len(adressen) >= 10
    for u in sorted(adressen):
        host = re.match(r"https?://([^/]+)/", u).group(1)
        assert host in ERLAUBTE_HOSTS, u
        assert u.startswith("https://"), u
        zeile = next((z for z in abschnitt.splitlines() if f"`{u}`" in z), None)
        assert zeile and "13.11.2026" in zeile, u
    for verboten in ("buergerinfo.stadt-koeln.de", "ratsinformation.stadt-koeln.de", "meinungfuer.koeln"):
        assert verboten not in QUELLE
    # Höchstens 12 Abrufe laut Auftrag; die Tabelle zählt jeden Abruf einzeln
    abrufe = [z for z in abschnitt.splitlines() if z.startswith("| ") and "13.11.2026" in z]
    assert sum(int(m) for z in abrufe for m in re.findall(r"\| (\d+) \|", z)) <= 12


def test_darstellung_je_stadtbezirk():
    """Nächste Sitzungen mit den Kölner Gremiennamen („Bezirksvertretung 1 (Innenstadt)“), ohne abgesagte und
    vergangene; ohne Stadtbezirk nur Rat und Ausschuss mit Hinweis; ohne zeit.json (Vorschau) keine Termine; ein
    unbekannter Stadtbezirk gilt als keine Wahl; Sitzungsadressen nur als http(s)."""
    d = _darstellung()
    inn = d["innenstadt"]
    assert "Nächste Sitzungen für den Stadtbezirk Innenstadt" in inn
    assert "Bezirksvertretung 1 (Innenstadt); die Sitzung beginnt mit der Einwohnerfragestunde" in inn
    assert "Fr., 20.11.2026, 17:00 Uhr" in inn and "16.11.2026" not in inn and "10.11.2026" not in inn
    assert "Ehrenfeld)" not in inn
    assert "Do., 26.11.2026, 15:30 Uhr" in inn and "03.12.2026" not in inn          # nächste Ratssitzung
    assert "Di., 24.11.2026, 16:00 Uhr" in inn
    assert inn.count("Tagesordnung noch nicht veröffentlicht") == 2
    assert '<option selected>Innenstadt</option>' in inn and "Bürgeramt Innenstadt" in inn
    ohne = d["ohne"]
    assert "Wählen Sie oben Ihren Stadtbezirk" in ohne and "Bezirksvertretung 1" not in ohne
    assert '<option value="" selected>bitte wählen</option>' in ohne and "Bürgeramt Ihres Stadtbezirks" in ohne
    assert d["fremd"] == ohne
    vor = d["vorschau"]
    assert "Die Sitzungstermine erscheinen hier, sobald die Ratsvorlagen im Ratsatlas vorliegen." in vor
    assert 'id="bt-termine"' not in vor and "bt-dates" not in vor
    ehr = d["ehrenfeld"]
    assert "Bezirksvertretung 4 (Ehrenfeld)" in ehr and "javascript:" not in ehr
    assert "Für die Bezirksvertretung" not in ehr
    # Äußere Links: neuer Tab mit Hinweis für Screenreader, rel=noopener; innen nur die Seite zum Datenschutz
    for html in (inn, ohne, ehr):
        links = re.findall(r"<a [^>]*>.*?</a>", html, re.S)
        assert [a for a in links if 'href="http' not in a] == ['<a href="datenschutz.html">Datenschutz</a>']
        for a in links:
            if 'href="http' in a:
                assert 'target="_blank"' in a and 'rel="noopener"' in a and "neuer Tab" in a, a


def test_unterschriften_laut_bekanntmachung():
    """Bürgerbegehren: 3 % in ganz Köln (24.283), je Stadtbezirk 5 % bzw. 6 % (Chorweiler) laut Bekanntmachung vom
    26.02.2026; die Tabelle hebt den gewählten Stadtbezirk hervor; Stadtbezirke wie geocode.BEZIRKE_KOELN."""
    d = _darstellung()
    assert d["bezirke"] == list(geocode.BEZIRKE_KOELN.values())
    assert set(d["quorum"]) == {"Köln", *d["bezirke"]}
    assert d["quorum"]["Köln"] == [3, 24283]
    assert {b: p for b, (p, _) in d["quorum"].items() if b != "Köln"} == {b: 6 if b == "Chorweiler" else 5 for b in d["bezirke"]}
    assert "das sind 24.283 Unterschriften" in d["ohne"]
    assert "Im Stadtbezirk Chorweiler sind es 6 Prozent, also 3.411 Unterschriften." in d["chorweiler"]
    assert '<tr class="bt-hier"><th scope="row">Chorweiler</th><td>6 %</td><td>3.411</td></tr>' in d["chorweiler"]
    assert "Im Stadtbezirk" not in d["ohne"].split("bt-quorum")[0] and "bt-hier" not in d["ohne"]
    assert d["stand"] == "13.11.2026"


def test_bv_bezirk_wie_build():
    """bvBezirk (app.js; Termine und Fläche) liest die Gremiennamen wie pipeline/build.bv_bezirk."""
    namen = ["Bezirksvertretung 1 (Innenstadt)", "Bezirksvertretung 3", "Bezirksvertretung Porz", "BV 9", "BV Kalk",
             "Bezirksvertretung 6 (Chorweiler)", "Rat", "Ausschuss für Verkehr und Mobilität", "", "Bezirksvertretung 12"]
    aus = _node_modul(f"console.log(JSON.stringify({json.dumps(namen)}.map(bvBezirk)));")
    assert aus == [build.bv_bezirk(n) for n in namen]
    assert json.loads(re.search(r"const BV_NUMMER = (\[.*?\]);", APP).group(1)) == list(geocode.BEZIRKE_KOELN.values())


def test_termine_je_stadtbezirk_mit_koelner_namen():
    """Termine „Rat, Ausschüsse und Bezirksvertretung …“ vergleicht über den Stadtbezirk aus dem Gremiennamen (vorher
    mit „Bezirksvertretung <Stadtbezirk>“, die Kölner Bezirksvertretungen fehlten); kein Bonner Satz zur Einladung."""
    teil = re.search(r"function showTermine\(\) \{.*?\n  \}\n", APP, re.S).group(0)
    assert "bvBezirk(m.gremium) === bezirk" in teil and "`Bezirksvertretung ${bezirk}`" not in teil
    assert "etwa zwei Wochen" not in APP


def test_freigabe_ohne_anfragen():
    """Die Freigabe „mitmachen“ ist an; die Fläche stellt keine Anfrage (Inhalt im Modul, Sitzungen aus zeit.json über
    app.js), daher keine Quelle in connect-src; die Fläche bleibt im gebauten index.html."""
    assert config.ZUSATZTHEMEN["mitmachen"] is True
    assert "mitmachen" not in seo.CSP_NUR_MIT_FREIGABE
    assert "fetch(" not in QUELLE and "XMLHttpRequest" not in QUELLE and "import(" not in QUELLE
    assert 'id="panel-mitmachen"' in seo.ohne_abgeschaltete(INDEX)


def test_texte_im_menue_glossar_und_vorgang():
    """§ 24 GO NRW in der Fassung ab 01.01.2026: Einwohnerinnen und Einwohner seit drei Monaten, Rat oder
    Bezirksvertretung; der Vorgang verlinkt die geprüfte Seite der Stadt und, mit Fläche, „Alle Wege …“."""
    begriffe = {b[0]: b for b in glossar.BEGRIFFE}
    ab = begriffe["Anregungen und Beschwerden"][1]
    assert "seit mindestens drei Monaten" in ab and "Rat oder die Bezirksvertretung" in ab and "Jede Person" not in ab
    assert "Bezirksvertretung damit" in begriffe["Einwohnerfragestunde"][1] and begriffe["Einwohnerfragestunde"][2].endswith("§ 39")
    assert "an den Rat oder Ihre Bezirksvertretung wenden" in INDEX
    teil = re.search(r"function participate\(p\) \{.*?\n  \}\n", APP, re.S).group(0)
    assert "${BUERGERANTRAG}" in teil and 'vorhanden("panel-mitmachen")' in teil and "data-mitmachen-oeffnen" in teil
    assert re.search(r'closest\("\[data-mitmachen-oeffnen\]"\) && vorhanden\("panel-mitmachen"\)', APP)
