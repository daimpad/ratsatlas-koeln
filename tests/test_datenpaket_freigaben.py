"""Runde 19 (Entscheidungen des Auftraggebers vom 10.11.2026): Audit-Protokolle, Stichproben und Abrufstatistik nur im
Datenpaket, nicht als lose Dateien auf der Seite (also weder im Branch deploy noch auf dem Spiegel); Texte zu
abgeschalteten Funktionen – Ratsassistent auf der Datenschutzseite, Themenseiten und KI-Kurzfassungen auf den Seiten zu
Feeds und Technik – nur mit Freigabe (config.ZUSATZTHEMEN). Bau über den lokalen Testserver mit erfundenen Daten; keine
Anfragen an Server der Stadt."""
import fnmatch
import importlib.util
import json
import re
import subprocess
import sys
import urllib.parse
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline import build, config, ebenen, export, kontext, paket, publish, rssseite, seo, sessionnet, technikseite
from pipeline.gebietsseiten import _page

ROOT = Path(__file__).resolve().parents[1]
URL = "https://koeln.ratsatlas.de/"
# bewusst hier ausgeschrieben und nicht aus tools/seite_bauen.py übernommen (Entscheidung 10.11.2026)
NUR_IM_PAKET = ("audit_*.tsv", "stichprobe_*.tsv", "abrufstatistik.tsv")

# Was eine Seite ohne die jeweilige Freigabe nicht nennen darf (Rohtext der Seite, einschließlich Kopf und Kommentaren)
OHNE_FREIGABE = {
    "chat": {"datenschutz.html": ("Ratsassistent", "ris-assistent", "Anthropic", "Mistral", "OpenRouter",
                                  "API-Schlüssel", "Gesprächsverlauf")},
    "themenseiten": {"rss/index.html": ("Themenseite", "dossiers/", "je Thema", "oder Thema", "und Themen"),
                     "technik/index.html": ("Themenseite",)},
    "kurzfassungen": {"rss/index.html": ("Kurzfassung", "KI-")},
}
# bisherige Texte (vor Runde 19), die mit der Freigabe wieder erscheinen
RSS_THEMEN = ('<a href="#weitere">Nur ein Gebiet oder Thema abonnieren</a>',
              "<summary>Feeds für einzelne Gebiete und Themen</summary>",
              "Diese Feeds enthalten nur die Vorlagen eines Gebiets oder einer Themenseite. Für einen einzelnen Vorgang",
              "<code>feeds/vorlagen/&lt;drucksache&gt;.xml</code>, <code>dossiers/&lt;thema&gt;.xml</code>.</dd>",
              "neue Vorlagen und Beratungsergebnisse aus ganz Köln, je Gebiet und je Thema, offen und ohne Konto.")
RSS_OHNE_THEMEN = ('<a href="#weitere">Nur ein Gebiet abonnieren</a>',
                   "<summary>Feeds für einzelne Gebiete</summary>",
                   "Diese Feeds enthalten nur die Vorlagen eines Gebiets. Für einen einzelnen Vorgang",
                   "<code>feeds/vorlagen/&lt;drucksache&gt;.xml</code>.</dd>",
                   "neue Vorlagen und Beratungsergebnisse aus ganz Köln, je Gebiet, offen und ohne Konto.")
RSS_KURZ = "<code>summary</code> (Art, federführendes Amt, Stand; gekennzeichnete KI-Kurzfassung, wo vorhanden).</dd>"
RSS_OHNE_KURZ = "<code>summary</code> (Art, federführendes Amt, Stand).</dd>"
TECHNIK_THEMEN = "Python-Paket aus requirements.txt: Bild der Themenseite als PNG zum Teilen"
TECHNIK_OHNE_THEMEN = "Python-Paket aus requirements.txt: Umwandlung von SVG-Bildern in PNG, derzeit ungenutzt"


def _paketdatei(name):
    return any(fnmatch.fnmatchcase(name, m) for m in NUR_IM_PAKET)


def _seite_bauen():
    spec = importlib.util.spec_from_file_location("seite_bauen", ROOT / "tools" / "seite_bauen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ziele = []

    def handle_starttag(self, tag, attrs):
        self.ziele += [v for k, v in attrs if k in ("href", "src") and v]


def _freigaben(monkeypatch, **an):
    for k in ("chat", "themenseiten", "kurzfassungen"):
        monkeypatch.setitem(config.ZUSATZTHEMEN, k, an.get(k, False))


# --- (1) Audit-Protokolle nur im Datenpaket ---------------------------------------------------------------------------

def test_audits_nur_im_datenpaket(oparl, tmp_path):
    """tools/seite_bauen.py wie im Hauptlauf (nach `package`): keine Audits, Stichproben oder Abrufstatistik als lose
    Dateien in _site, auch nicht in Unterordnern; ein Ordner nur mit einer Stichprobe entfällt; andere TSV-Dateien
    bleiben; das Datenpaket enthält alle; keine Links darauf; Linkprüfung ohne Befund. Dazu die Texte der gebauten
    Datenschutz-, Feed- und Technikseite mit den Kölner Freigaben aus config.py."""
    sessionnet.fetch_all()   # schreibt auch die Abrufstatistik nach data/export
    build.build()
    export.export()
    kontext.write()
    ebenen.write()
    hnr = config.EXPORT / "hausnummern" / "stichprobe_hausnummern.tsv"   # Ordner nur mit einer Stichprobe
    if not hnr.exists():
        hnr.parent.mkdir(parents=True, exist_ok=True)
        hnr.write_text("drucksache\turteil\n[Testdaten]\t\n", encoding="utf-8")
    andere = config.EXPORT / "koeln" / "andere_liste.tsv"   # erfunden: keine Prüfdatei, bleibt auf der Seite
    andere.write_text("spalte\n[Testdaten]\n", encoding="utf-8")
    zip_pfad = paket.write()
    site = tmp_path / "_site"
    _seite_bauen().main(site)

    in_export = {p.relative_to(config.EXPORT).as_posix() for p in config.EXPORT.rglob("*")
                 if p.is_file() and _paketdatei(p.name)}
    assert {"abrufstatistik.tsv", "audit_geokodierung.tsv", "audit_prozess.tsv", "audit_zeit.tsv", "audit_themen.tsv",
            "stichprobe_geokodierung.tsv", "hausnummern/stichprobe_hausnummern.tsv"} <= in_export
    assert [p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file() and _paketdatei(p.name)] == []
    assert not (site / "data" / "export" / "hausnummern").exists()
    assert (site / "data" / "export" / "koeln" / "andere_liste.tsv").read_text(encoding="utf-8") == "spalte\n[Testdaten]\n"
    assert (site / "data" / "export" / "koeln" / "index.json").is_file()

    # Datenpaket: auf dem Spiegel dieselbe Datei wie aus `package`, mit allen Audits und Stichproben
    assert (site / "data" / "export" / "ratsatlas-koeln-export.zip").read_bytes() == zip_pfad.read_bytes()
    with zipfile.ZipFile(zip_pfad) as z:
        namen = set(z.namelist())
        liesmich = z.read(f"{paket.ORDNER}/LIESMICH.txt").decode("utf-8")
    assert {f"{paket.ORDNER}/{r}" for r in in_export} <= namen
    assert "nur in diesem Paket, nicht als einzelne Dateien auf der Seite" in liesmich

    # keine Links auf diese Dateien (innere wie äußere), innere Links heil
    for seite in sorted(site.rglob("*.html")):
        p = _Links()
        p.feed(seite.read_text(encoding="utf-8"))
        for ziel in p.ziele:
            assert not _paketdatei(urllib.parse.urlsplit(ziel).path.rsplit("/", 1)[-1]), (seite, ziel)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "linkpruefung.py"), str(site)], capture_output=True,
                       text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr

    # Texte zu abgeschalteten Funktionen: mit den Freigaben aus config.py
    for funktion, seiten in OHNE_FREIGABE.items():
        if config.ZUSATZTHEMEN.get(funktion):
            continue
        for rel, woerter in seiten.items():
            html = (site / rel).read_text(encoding="utf-8")
            assert [w for w in woerter if w in html] == [], (funktion, rel)
    if not config.ZUSATZTHEMEN.get("chat"):
        assert "data-funktion" not in (site / "datenschutz.html").read_text(encoding="utf-8")
        assert not (site / "chat").exists()   # Module und Bonner Systemprompt des Ratsassistenten

    # Runde 20 (tests/test_aufraeumen_runde20.py): CSP aller Seiten ohne Quellen des Assistenten, Flächen nur mit Freigabe
    richtlinien = {s.relative_to(site).as_posix(): seo.csp_richtlinien(s.read_text(encoding="utf-8"))
                   for s in site.rglob("*.html")}
    assert len([r for r in richtlinien.values() if r]) > 90 and richtlinien["index.html"]
    hosts = [seo._host(q) for q in seo.CSP_NUR_MIT_FREIGABE["chat"]]
    an_chat = bool(config.ZUSATZTHEMEN.get("chat"))
    for rel, rs in richtlinien.items():
        for r in rs:
            assert [h for h in hosts if h in r] == (hosts if an_chat and rel == "index.html" else []), rel
    index = (site / "index.html").read_text(encoding="utf-8")
    for flaeche, funktion in (("panel-assistent", "chat"), ("panel-mitmachen", "mitmachen")):
        assert (f'id="{flaeche}"' in index) == bool(config.ZUSATZTHEMEN.get(funktion)), flaeche

    # Nachbesserung: keine Bonner Dienste im Seitenkopf, Lizenz der OParl-Exporte, Beschreibung des Datenpakets
    assert "OParl-Lite" not in (site / "index.html").read_text(encoding="utf-8")
    with zipfile.ZipFile(zip_pfad) as z:
        lizenz_im_paket = z.read(f"{paket.ORDNER}/LICENSE-DATA.md").decode("utf-8")
    for lizenz in ((site / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8"), lizenz_im_paket):
        assert "Noch nicht enthalten: Daten der OParl-API" not in lizenz and "| `export/koeln/" in lizenz
    dcat = json.loads((site / "data" / "export" / config.STADT / "dcat.jsonld").read_text(encoding="utf-8"))
    (beschreibung,) = [d["dct:description"]["@value"] for d in dcat["dcat:distribution"]
                       if d["dct:title"]["@value"] == "Datenpaket (Zip)"]
    assert "Verifikation" not in beschreibung and "nur in diesem Paket" in beschreibung
    assert not any(n.startswith(f"{paket.ORDNER}/verifikation") for n in namen)


def test_hauptlauf_packt_vor_dem_zusammenstellen():
    """pages.yml: Das Datenpaket entsteht aus ganz data/export, bevor tools/seite_bauen.py die Seite ohne die Audits
    zusammenstellt; Branch deploy und Spiegel nehmen die fertige Seite (_site). Größenwache und Ersatz des Zip-Links
    prüfen tests/test_workflows.py und tests/test_seite_bedienung.py."""
    text = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    stellen = [text.index(s) for s in ("python -m pipeline export", "python -m pipeline package",
                                       "python tools/seite_bauen.py _site", "cp -r _site/. _deploy/",
                                       "rm -f _deploy/data/export/ratsatlas-koeln-export.zip", 'path: "_site"')]
    assert stellen == sorted(stellen)
    assert text.count("python -m pipeline package") == 1 and text.count("python tools/seite_bauen.py") == 1


# --- (3) Texte nur mit Freigabe -----------------------------------------------------------------------------------

def test_datenschutz_ratsassistent_nur_mit_freigabe(monkeypatch):
    """site/datenschutz.html: Abschnitt „Ratsassistent (KI)“, die Einträge zum Speicher des Assistenten und der Satz
    zu seinem Schlüssel nur mit Freigabe „chat“; mit Freigabe unverändert. Die Seite läuft durch seo.ohne_abgeschaltete
    (seo.PAGES)."""
    assert "datenschutz.html" in seo.PAGES
    quelle = (ROOT / "site" / "datenschutz.html").read_text(encoding="utf-8")
    _freigaben(monkeypatch)
    aus = seo.ohne_abgeschaltete(quelle)
    assert [w for w in OHNE_FREIGABE["chat"]["datenschutz.html"] if w in aus] == []
    assert "data-funktion" not in aus
    ueberschriften = re.findall(r"<h2>(.*?)</h2>", quelle)
    assert "Ratsassistent (KI)" in ueberschriften
    assert re.findall(r"<h2>(.*?)</h2>", aus) == [h for h in ueberschriften if h != "Ratsassistent (KI)"]
    assert ("<li><code>ris-karte-farbig</code>: ob die Karte farbig oder grau erscheint</li>\n    </ul>\n    <p>Diese "
            "Angaben verlassen Ihr Gerät nicht; sie sind für die von Ihnen gewünschten Funktionen erforderlich") in aus
    _freigaben(monkeypatch, chat=True)
    assert seo.ohne_abgeschaltete(quelle) == quelle
    _freigaben(monkeypatch, themenseiten=True, kurzfassungen=True)   # andere Freigaben ändern nichts am Assistenten
    assert seo.ohne_abgeschaltete(quelle) == aus


def test_abschalten_auf_seiten_ohne_skript(monkeypatch):
    """seo.ohne_abgeschaltete: section und li auf eigener Zeile fallen samt Zeile heraus, span im Fließtext ohne
    Leerraum davor; Elemente mit hidden (Startseite, app.js) bleiben wie bisher; ein sichtbares Element einer
    abgeschalteten Funktion in anderer Form bricht den Bau ab."""
    _freigaben(monkeypatch)
    beispiele = {
        "<main>\n  <section data-funktion=\"chat\">\n  <h2>A</h2>\n  <ul><li>x</li></ul>\n  </section>\n  <h2>B</h2>\n</main>":
            "<main>\n  <h2>B</h2>\n</main>",
        "<ul>\n  <li data-funktion=\"chat\"><code>a</code>: A</li>\n  <li>B</li>\n</ul>": "<ul>\n  <li>B</li>\n</ul>",
        "<p><span data-funktion=\"chat\">A (<code>a</code>). </span>B.</p>": "<p>B.</p>",
    }
    for html, erwartet in beispiele.items():
        assert seo.ohne_abgeschaltete(html) == erwartet
    versteckt = '<button type="button" class="toggle" data-funktion="chat" hidden>KI</button>'
    assert seo.ohne_abgeschaltete(versteckt) == versteckt
    for falsch in ('<div data-funktion="chat">A</div>', '<p data-funktion="chat">A</p>'):
        with pytest.raises(ValueError, match="abgeschalteten Funktion"):
            seo.ohne_abgeschaltete(falsch)
    _freigaben(monkeypatch, chat=True)
    for html in (*beispiele, '<div data-funktion="chat">A</div>'):
        assert seo.ohne_abgeschaltete(html) == html


# Formen, die AUS_BLOCK und AUS_SATZ nicht entfernen; sichtbar, solange sie in der Seite stehen (Nachbesserung Runde 19)
SICHTBAR_ANDERE_FORM = (
    '<p class="hinweis" data-funktion="chat">Ratsassistent</p>',   # weiteres Attribut davor
    '<section data-funktion="chat" id="ki">\n<h2>KI</h2>\n</section>',   # weiteres Attribut danach
    '<p><span data-funktion="chat" >Satz. </span>Rest.</p>',   # Leerzeichen im Tag
    "<ul>\n<li data-funktion='chat'>Eintrag</li>\n</ul>",   # einfache Anführungszeichen
    '<span data-funktion="chat" aria-hidden="true">Satz</span>',   # aria-hidden ist nicht hidden
    '<img src="a.png" alt="" data-funktion=chat>',   # ohne Anführungszeichen
    '<br data-funktion="chat"/>',   # leeres Element
)
# Was die Wache durchlässt: verborgene Elemente (app.js), Kommentare, Inhalt von script
NICHT_SICHTBAR = (
    '<div hidden data-funktion="chat">A</div>',
    '<button type="button" data-funktion=\'chat\' class="toggle" hidden="">KI</button>',
    '<!-- Elemente mit data-funktion="chat" entfernt der Bau -->',
    '<script>const t = \'<p data-funktion="chat">A</p>\';</script>',
)


@pytest.mark.parametrize("html", SICHTBAR_ANDERE_FORM)
def test_wache_findet_jede_sichtbare_form(monkeypatch, html):
    """seo.ohne_abgeschaltete: Ein sichtbares Element einer abgeschalteten Funktion bricht den Bau ab, gleich wo
    data-funktion im Tag steht und wie der Wert geschrieben ist; mit Freigabe bleibt es unverändert."""
    _freigaben(monkeypatch)
    with pytest.raises(ValueError, match="abgeschalteten Funktion"):
        seo.ohne_abgeschaltete(html)
    _freigaben(monkeypatch, chat=True)
    assert seo.ohne_abgeschaltete(html) == html


@pytest.mark.parametrize("html", NICHT_SICHTBAR)
def test_wache_laesst_verborgenes_stehen(monkeypatch, html):
    _freigaben(monkeypatch)
    assert seo.ohne_abgeschaltete(html) == html


def test_seiten_bestehen_die_wache(monkeypatch):
    """Die Quellen in seo.PAGES laufen mit allen Freigaben aus, an und wie in config.py ohne Fehler durch; mit allen
    Freigaben bleiben sie unverändert."""
    alle = list(config.ZUSATZTHEMEN)
    for wert in (False, True, None):
        for k in alle:
            if wert is not None:
                monkeypatch.setitem(config.ZUSATZTHEMEN, k, wert)
        for name in seo.PAGES:
            quelle = (ROOT / "site" / name).read_text(encoding="utf-8")
            aus = seo.ohne_abgeschaltete(quelle)
            if wert:
                assert aus == quelle, name
        monkeypatch.undo()


# --- Nachbesserung Runde 19: Ordner chat/, Beschreibung des Datenpakets, Bonner Reste, Lizenz der OParl-Exporte -----

def test_ordner_des_assistenten_nur_mit_freigabe(monkeypatch, tmp_path):
    """tools/seite_bauen.py: Ohne Freigabe „chat“ fehlt der Ordner chat/ (Module und Bonner Systemprompt des
    Ratsassistenten) in der Seite; mit Freigabe bleibt er."""
    assert (ROOT / "site" / "chat" / "systemprompt.md").is_file()   # sonst prüft der Test nichts
    mod = _seite_bauen()
    for an in (False, True):
        ziel = tmp_path / str(an)
        (ziel / "chat").mkdir(parents=True)
        (ziel / "chat" / "systemprompt.md").write_text("# [Testdaten]\n", encoding="utf-8")
        (ziel / "app.js").write_text("// [Testdaten]\n", encoding="utf-8")
        _freigaben(monkeypatch, chat=an)
        mod.ohne_abgeschaltete_ordner(ziel)
        assert (ziel / "chat").exists() == an
        assert (ziel / "app.js").is_file()


def test_dcat_beschreibt_das_datenpaket(tmp_path):
    """DCAT-Distribution „Datenpaket (Zip)“: nennt, was pipeline/paket.py hineinlegt (keine Verifikation, die im
    Kölner Lauf nicht entsteht), und dass Prüfprotokolle und Stichproben nur dort liegen."""
    publish.write_dcat(tmp_path / "dcat.jsonld", None, None)
    doc = json.loads((tmp_path / "dcat.jsonld").read_text(encoding="utf-8"))
    (text,) = [d["dct:description"]["@value"] for d in doc["dcat:distribution"]
               if d["dct:title"]["@value"] == "Datenpaket (Zip)"]
    assert "Verifikation" not in text and "Alle Exporte" not in text
    for teil in ("Exporte (ohne Feeds)", "Prüfprotokolle und Stichproben (TSV, nur in diesem Paket", "Abrufstatistik",
                 "Berichte der Projektphasen", "Lizenzübersicht"):
        assert teil in text, teil


def test_seiten_ohne_bonner_dienste():
    """Quellen der Seiten in seo.PAGES nennen OParl-Lite nicht, auch nicht im Kommentar (für Köln kein solcher
    Dienst)."""
    for name in seo.PAGES:
        assert "OParl-Lite" not in (ROOT / "site" / name).read_text(encoding="utf-8"), name


def test_lizenz_der_oparl_exporte():
    """data/LICENSE-DATA.md (auf der Seite und im Datenpaket): eine Zeile für die Exporte aus der OParl-API mit
    Lizenzangabe, offener Klärung und Namensnennung; nicht mehr „noch nicht enthalten“. Seit Runde 19b nur für die
    Dateien aus dem Ratsinformationssystem; Kennzahlen und Flächen haben eigene Zeilen (tests/test_lizenzen.py). Die
    Namensnennung beginnt mit der Stadt und nennt dazu die Bebauungspläne und OpenStreetMap, deren Lizenzen die Zeile
    führt (wie dct:rights im DCAT, Korrekturrunde 19b)."""
    text = (ROOT / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8")
    assert "Noch nicht enthalten: Daten der OParl-API" not in text
    (zeile,) = [z for z in text.splitlines() if z.startswith("| `export/koeln/` aus dem Ratsinformationssystem")]
    spalten = [s.strip() for s in zeile.strip("|").split(" | ")]
    assert len(spalten) == 4, spalten
    assert "OParl-API" in spalten[1] and "ohne Volltexte" in spalten[1]
    assert "dl-de/zero 2.0" in spalten[2] and "Klärung" in spalten[2]
    assert spalten[3].startswith(config.NAMENSNENNUNG + "; ") and "IT.NRW" in spalten[3]


@pytest.mark.parametrize("an", [{}, {"themenseiten": True}, {"kurzfassungen": True},
                                {"themenseiten": True, "kurzfassungen": True}])
def test_feedseite_themen_und_kurzfassungen_nur_mit_freigabe(monkeypatch, tmp_path, an):
    """pipeline/rssseite.py: Feeds je Themenseite (dossiers/) und die KI-Kurzfassung im Eintrag nur mit Freigabe;
    mit beiden Freigaben die bisherigen Texte."""
    _freigaben(monkeypatch, **an)
    rssseite.write(tmp_path, URL, _page)
    html = (tmp_path / "rss" / "index.html").read_text(encoding="utf-8")
    themen, kurz = an.get("themenseiten", False), an.get("kurzfassungen", False)
    for alt, neu in zip(RSS_THEMEN, RSS_OHNE_THEMEN):
        assert (alt in html, neu in html) == (themen, not themen), (alt, neu)
    assert (RSS_KURZ in html, RSS_OHNE_KURZ in html) == (kurz, not kurz)
    for funktion in ("themenseiten", "kurzfassungen"):
        if not an.get(funktion):
            assert [w for w in OHNE_FREIGABE[funktion]["rss/index.html"] if w in html] == [], funktion


@pytest.mark.parametrize("themen", [False, True])
def test_technikseite_themenseite_nur_mit_freigabe(monkeypatch, tmp_path, themen):
    """pipeline/technikseite.py: die Erklärung zu cairosvg nennt die Themenseite nur mit Freigabe; Prüfprotokolle
    stehen im Datenpaket."""
    _freigaben(monkeypatch, themenseiten=themen)
    technikseite.write(tmp_path, URL, _page)
    html = (tmp_path / "technik" / "index.html").read_text(encoding="utf-8")
    if "cairosvg" in (ROOT / "requirements.txt").read_text(encoding="utf-8"):
        assert (TECHNIK_THEMEN in html, TECHNIK_OHNE_THEMEN in html) == (themen, not themen)
    assert ("Themenseite" in html) == themen
    assert "Prüfprotokolle als TSV im Datenpaket" in html and "Kurzfassung" not in html and "Ratsassistent" not in html
