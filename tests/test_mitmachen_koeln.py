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


# --- Nachprüfung vom 14.11.2026 (Befunde der Prüfung zu f683b66) ------------------------------------------------------

def _karte(html, titel):
    """Die Karte (<article class="bt-card">) mit Überschrift `titel`."""
    m = re.search(r'<article class="bt-card"><h4>' + re.escape(titel) + r"</h4>.*?</article>", html, re.S)
    assert m, titel
    return m.group(0)


def test_fragestunde_hinweis_neben_dem_link():
    """Die Seite der Stadt zur Einwohnerfragestunde beschreibt noch die Geschäftsordnung von 2020 (Antwort in der Regel
    mündlich in der Sitzung); die Karte folgt der Fassung vom 19.03.2026. Der Unterschied steht auf der Karte direkt vor
    der Zeile mit dem Link, nicht nur in TECHNIK.md – in jeder Darstellung (mit und ohne Stadtbezirk, Vorschau)."""
    url = re.escape(QUELLE_URL["fragestunde"])
    d = _darstellung()
    for name in ("innenstadt", "ohne", "vorschau"):
        karte = _karte(d[name], "Eine Frage in der Einwohnerfragestunde stellen")
        m = re.search(r'<p class="hint bt-abweichung">(.*?)</p>\s*<p class="hint">Grundlage: [^<]*<a href="' + url, karte, re.S)
        assert m, name
        hinweis = m.group(1)
        assert "Geschäftsordnung von 2020" in hinweis and "mündlich in der Sitzung" in hinweis, hinweis
        assert "Geschäftsordnung vom 19.03.2026" in hinweis and "schriftlich" in hinweis, hinweis
        # Die Karte selbst nennt die Regel von 2026 (schriftliche Antwort, möglichst innerhalb von vier Wochen)
        assert "Die Verwaltung antwortet schriftlich, nach der Geschäftsordnung möglichst innerhalb von vier Wochen." in karte
    # Der Hinweis steht nur auf dieser Karte
    assert d["innenstadt"].count("bt-abweichung") == 1
    # TECHNIK.md vermerkt, dass der Unterschied jetzt auf der Seite sichtbar ist
    assert "auf der Karte selbst" in _abschnitt_technik()


QUELLE_URL = {k: v for k, v in re.findall(r'(\w+): \{ label: "[^"]*", wo: [^,]+,\s*url: "([^"]+)"', QUELLE)}


def test_rat_oder_bezirksvertretung_nach_wortlaut():
    """§ 37 Abs. 1 Buchst. a GO NRW nennt Unterhaltung und Ausstattung der Schulen und öffentlichen Einrichtungen im
    Stadtbezirk (nicht ihre Errichtung oder Auflösung; die ist nach § 41 Abs. 1 Buchst. m Sache des Rates); am
    14.11.2026 gegen recht.nrw.de abgeglichen."""
    d = _darstellung()
    for name, wer in (("innenstadt", "Die Bezirksvertretung Innenstadt"), ("ohne", "Die Bezirksvertretung Ihres Stadtbezirks")):
        absatz = re.search(r"<p><strong>Rat oder Bezirksvertretung\?</strong>(.*?)</p>", d[name], re.S).group(1)
        assert "er entscheidet zum Beispiel, ob öffentliche Einrichtungen errichtet, erweitert oder aufgelöst werden" in absatz
        assert f"{wer} entscheidet, soweit nicht der Rat zuständig ist," in absatz
        assert "über die Unterhaltung und Ausstattung der Schulen und öffentlichen Einrichtungen im Stadtbezirk" in absatz
        assert "die Betreuung und Unterstützung örtlicher Vereine" in absatz
        assert "(§ 41 Abs. 1, § 37 Abs. 1 GO NRW)" in absatz
        assert "etwa über Schulen und öffentliche Einrichtungen" not in absatz


def test_naechste_ratssitzung_in_allen_schreibweisen():
    """Die nächste Ratssitzung wird auch unter den Schreibweisen erkannt, die site/timeline.js kennt (GREMIUM_ALIAS:
    „Rat der Stadt Köln“, „Stadtrat“); andere Gremien mit „Rat“ im Namen nicht."""
    alias = re.search(r"const GREMIUM_ALIAS = (\{.*?\});", (ROOT / "site" / "timeline.js").read_text(encoding="utf-8")).group(1)
    namen = [k for k, v in json.loads(alias).items() if v == "Rat"]
    assert set(namen) == {"Rat der Stadt Köln", "Stadtrat"}
    for name in namen:
        sitzungen = [{"date": "2026-11-26", "time": "15:30", "gremium": name, "web": None},
                     {"date": "2026-11-19", "time": "17:00", "gremium": "Integrationsrat", "web": None},
                     {"date": "2026-11-20", "time": "17:00", "gremium": "Seniorenrat", "web": None}]
        aus = _node_modul(f"""
const o = {{ termine: true, meetings: {json.dumps(sitzungen)}, heute: "2026-11-13", bvBezirk }};
console.log(JSON.stringify(m.inhalt("", o)));
""")
        liste = re.search(r'<ul class="bt-dates">(.*?)</ul>', aus, re.S).group(1)
        assert "Do., 26.11.2026, 15:30 Uhr" in liste and "Rat der Stadt Köln; Ratssitzungen" in liste, name
        assert "19.11.2026" not in liste and "20.11.2026" not in liste, name


def test_zuhoeren_in_der_vorschau_ohne_kommende_sitzungen():
    """In der Vorschau (ohne zeit.json) gibt es „Kommende Sitzungen“ noch nicht; die Karte „Zuhören und zuschauen“
    sagt dann, dass die Termine mit den Ratsvorlagen erscheinen, statt auf eine leere Fläche zu verweisen."""
    d = _darstellung()
    mit = _karte(d["innenstadt"], "Zuhören und zuschauen")
    ohne = _karte(d["vorschau"], "Zuhören und zuschauen")
    assert "Die Termine stehen im Ratsatlas unter „Kommende Sitzungen“" in mit
    assert "Die Termine stehen im Ratsatlas" not in ohne and "Tagesordnung" not in ohne
    assert "Die Termine erscheinen im Ratsatlas unter „Kommende Sitzungen“, auch als Kalenderdatei, sobald die Ratsvorlagen vorliegen." in ohne


def test_postanschrift_der_geschaeftsstelle():
    """Briefe gehen laut Seite der Geschäftsstelle an Postfach 10 35 64, 50475 Köln; die Ludwigstraße 8 ist die
    Anschrift (beides am 14.11.2026 geprüft)."""
    karte = _karte(_darstellung()["innenstadt"], "Anregungen und Beschwerden an Rat oder Bezirksvertretung")
    assert "Briefe gehen an Postfach 10 35 64, 50475 Köln" in karte
    assert "E-Mails an geschaeftsstelle-anregungen-beschwerden@stadt-koeln.de" in karte
    assert "die Geschäftsstelle selbst sitzt in der Ludwigstraße 8, 50667 Köln" in karte


def test_texte_rat_oder_bezirksvertretung_ueberall():
    """§ 24 GO NRW: Tour (mit und ohne Freigabe, Vorschau) nennt wie Glossar, Menü, Vorgang und Fläche „Rat oder
    Bezirksvertretung“; das Glossar beschreibt die Kölner Einwohnerfragestunde mit schriftlicher Antwort."""
    tour = (ROOT / "site" / "tour.js").read_text(encoding="utf-8")
    assert "§ 24 GO NRW" in tour
    for m in re.finditer(r"§ 24 GO NRW selbst an den Rat[^;,]*", tour):
        assert "oder die Bezirksvertretung" in m.group(0), m.group(0)
    assert len(re.findall(r"§ 24 GO NRW selbst an den Rat oder die Bezirksvertretung", tour)) == 3
    frage = {b[0]: b for b in glossar.BEGRIFFE}["Einwohnerfragestunde"][1]
    assert "vorher schriftlich eingereicht" in frage and "die Verwaltung antwortet schriftlich" in frage
    assert "stellen können" not in frage


def test_flaeche_merkt_sich_leere_wahl_nicht():
    """Öffnet man die Fläche ohne Stadtbezirk und wählt danach ein Gebiet, ist beim erneuten Öffnen dessen Stadtbezirk
    vorgewählt (eine leere Wahl der Fläche verdeckt das Gebiet nicht)."""
    teil = re.search(r"function openMitmachen\(s\) \{.*?\n  \}\n", APP, re.S).group(0)
    assert '(mmState && mmState.bezirk) || areaBezirk() || ""' in teil
    assert "mmState ? mmState.bezirk : areaBezirk()" not in teil


def test_wcag_pruefung_meldet_fehlende_flaeche():
    """tools/wcag_pruefen.js: Steht die Fläche im HTML (Freigabe an) und öffnet sich nicht, ist das ein Befund statt
    einer stillen Lücke mit „0 Befunde“."""
    wcag = (ROOT / "tools" / "wcag_pruefen.js").read_text(encoding="utf-8")
    assert "if (await p.$('#panel-mitmachen:not([hidden]) #bt-bezirk'))" not in wcag
    assert "if (await p.$('#panel-mitmachen'))" in wcag
    assert "rows.push(['mitmachen-flaeche', 'nicht geöffnet'" in wcag


def test_nachpruefung_vom_14_11_2026_vermerkt():
    """Die Nachprüfung am 14.11.2026 (höchstens 4 Abrufe, nur www.stadt-koeln.de und recht.nrw.de, keine OParl-API)
    steht mit Adresse, Zahl und Zweck in TECHNIK.md; jede Adresse ist eine der geprüften Adressen der Fläche."""
    abschnitt = _abschnitt_technik()
    zeilen = [z for z in abschnitt.splitlines() if z.startswith("| `") and "14.11.2026" in z]
    assert zeilen
    assert sum(int(m) for z in zeilen for m in re.findall(r"\| (\d+) \|", z)) <= 4
    for z in zeilen:
        u = re.search(r"`(https://[^`]+)`", z).group(1)
        assert re.match(r"https://([^/]+)/", u).group(1) in ERLAUBTE_HOSTS, u
        assert u in QUELLE, u
