"""Seite einfach/ (Einfache Sprache, pipeline/einfachseite.py; für Köln neu geschrieben und freigegeben am 13.11.2026):
keine Bonner Reste, Angaben aus dem Repository (Stadtbezirke und Stadtteile aus data/geo, Wörter wie im Glossar mit
Sprungmarken auf begriffe/), Regeln der Einfachen Sprache (kurze Sätze, keine Abkürzungen außerhalb der Zeilen „Für
Fachleute“), Sätze zu abgeschalteten Themen nur mit Freigabe, Vorschau-Hinweis, Bau über seo.write mit Sitemap und
Karte im Menü „Verstehen“. Keine Anfragen an Server der Stadt."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline import begriffsseite, config, einfachseite, glossar, seo
from pipeline.gebietsseiten import _page

ROOT = Path(__file__).resolve().parents[1]
URL = "https://koeln.ratsatlas.de/"


class _Text(HTMLParser):
    """Sichtbarer Text je Absatz (p, li, dt, dd, h1, h2) ohne die Zeilen „Für Fachleute“ und die Fußzeile (meta)."""

    BLOCK = {"p", "li", "dt", "dd", "h1", "h2"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bloecke, self._jetzt, self._aus = [], None, 0
        self.ids, self.hrefs = set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag == "p" and (a.get("class") or "") in ("einfach-fach", "meta"):
            self._aus += 1
            return
        if tag in self.BLOCK and not self._aus:
            self._jetzt = []

    def handle_endtag(self, tag):
        if tag == "p" and self._aus:
            self._aus -= 1
            return
        if tag in self.BLOCK and self._jetzt is not None and not self._aus:
            text = " ".join("".join(self._jetzt).split())
            if text:
                self.bloecke.append(text)
            self._jetzt = None

    def handle_data(self, data):
        if self._jetzt is not None and not self._aus:
            self._jetzt.append(data)


def _lesen(html):
    p = _Text()
    p.feed(html)
    p.close()
    return p


def _saetze(text):
    """Sätze eines Absatzes (Trennung nach . ! ? und Doppelpunkt am Satzende; Zahlen wie 2250/2025 bleiben)."""
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ„])", text) if s]


@pytest.fixture
def freigaben(monkeypatch):
    """Freigaben für einen Test ändern, ohne config.ZUSATZTHEMEN der anderen Tests zu berühren."""
    werte = dict(config.ZUSATZTHEMEN)
    monkeypatch.setattr(config, "ZUSATZTHEMEN", werte)
    return werte


def test_freigabe_eingeschaltet():
    """Entscheidung 13.11.2026 (zweiter Lauf jetzt): Die Einfache Sprache ist für Köln freigegeben."""
    assert config.ZUSATZTHEMEN["einfache_sprache"] is True


def test_keine_bonner_reste():
    """Kein Bonn, keine Bonner Adressen, Gremien, Zahlen oder Wege mehr (Bonner Fassung: „Wer entscheidet in Bonn?“,
    4 Stadtbezirke, bonn.de, Hackathon, OParl-Lite, Drucksachennummer, Einwohnerfragestunde mit 21 Tagen, „jeden
    Morgen“, „ab Oktober 2019“, Ortsteil); auch der Quelltext des Moduls nicht."""
    html = einfachseite.body("../")
    quelle = (ROOT / "pipeline" / "einfachseite.py").read_text(encoding="utf-8")
    for wort in ("Bonn", "bonn.de", "Hack den Stadtrat", "OParl-Lite", "Drucksachennummer", "Bürgerantrag",
                 "Einwohnerfragestunde", "21 Tage", "jeden Morgen", "2019", "Ortsteil", "Bad Godesberg", "Beuel",
                 "Hardtberg", "RIS", "CC0", "CC BY 4.0"):
        assert wort not in html, wort
    assert "Bonn" not in quelle.replace("aus Bonn übernommen", "")
    assert not hasattr(einfachseite, "BUERGERANTRAG")


def test_angaben_aus_dem_repository():
    """Stadtbezirke nach Nummer und Zahl der Stadtteile aus data/geo; Gremien, Fundstellen und Namensnennung wie im
    Glossar und in config."""
    bezirke = json.loads(config.STADTBEZIRKE.read_text(encoding="utf-8"))["features"]
    namen = [f["properties"]["bezirk_bez"] for f in sorted(bezirke, key=lambda f: int(f["properties"]["bezirk"]))]
    n_teile = len(json.loads(config.ORTSTEILE.read_text(encoding="utf-8"))["features"])
    assert (len(namen), n_teile) == (9, 86)
    assert einfachseite.stadtbezirke() == (namen, 86)
    html = einfachseite.body("../")
    assert ("Köln hat 9 Stadtbezirke: Innenstadt, Rodenkirchen, Lindenthal, Ehrenfeld, Nippes, Chorweiler, Porz, Kalk "
            "und Mülheim.") in html
    assert "Die 9 Stadtbezirke sind in 86 Stadtteile geteilt." in html
    assert "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden" in html
    assert "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden" in dict(
        (b, e) for b, e, _ in glossar.BEGRIFFE)["Anregungen und Beschwerden"]
    assert config.NAMENSNENNUNG in html and glossar.GEBIETE in html and glossar.HAUPTSATZUNG in html
    # Beispiele wie im Glossar und auf der Seite
    assert "2250/2025" in html and "AN/1756/2026" in html
    assert "2250/2025" in dict((b, e) for b, e, _ in glossar.BEGRIFFE)["Vorlagennummer"]


def test_woerter_wie_im_glossar_mit_sprungmarke():
    """Jedes Wort mit Begriff steht im Glossar (Begriff, Ergebnis) und verweist auf seine Sprungmarke auf begriffe/;
    die Sprungmarke gibt es dort."""
    namen = {b for b, _, _ in glossar.BEGRIFFE} | set(glossar.ERGEBNISSE)
    begriffe_html = begriffsseite.body("../")
    ids = set(re.findall(r'id="([^"]+)"', begriffe_html))
    html = einfachseite.body("../")
    mit = [(w, b) for w, _, b in einfachseite.WOERTER if b]
    assert len(mit) >= 12
    for wort, begriff in mit:
        assert begriff in namen, begriff
        marke = glossar.anker(begriff)
        assert marke in ids, marke
        assert f'<dt><a href="../begriffe/#{marke}">{wort}</a></dt>' in html
    for wort, _, begriff in einfachseite.WOERTER:
        if not begriff:
            assert f"<dt>{wort}</dt>" in html


def test_regeln_der_einfachen_sprache():
    """Kurze Sätze (höchstens 18 Wörter) und keine Abkürzungen im Text für alle; Fundstellen und Fachbegriffe stehen nur
    in den Zeilen „Für Fachleute“. Jeder Abschnitt der Sprungleiste hat seine Überschrift."""
    p = _lesen(einfachseite.body("../"))
    lang = [(len(s.split()), s) for b in p.bloecke for s in _saetze(b) if len(s.split()) > 18]
    assert lang == [], lang
    text = " ".join(p.bloecke)
    for kuerzel in ("GO NRW", "OParl", "z. B.", "bzw.", "u. a.", "BV ", "OB ", "TOP ", "RIS", "dl-de", "GeschO"):
        assert kuerzel not in text, kuerzel
    sprung = [h[1:] for h in p.hrefs if h.startswith("#")]
    assert len(sprung) >= 12 and set(sprung) <= p.ids
    assert text.count("Für Fachleute") == 0
    assert einfachseite.body("../").count('<p class="einfach-fach"><strong>Für Fachleute:</strong>') >= 6


def test_offenes_als_offen_gekennzeichnet():
    """Ohne geprüften Link zur Seite der Stadt über Anregungen und Beschwerden (wie site/app.js) kein Link, sondern der
    Hinweis; die Prüfung von Hand steht noch aus; das zuständige Amt nur, wenn die Daten es zeigen."""
    html = einfachseite.body("../")
    assert "Einen geprüften Link dazu ergänzen wir noch." in html
    assert "Die Orte sind noch nicht von Hand geprüft." in html
    assert "Wenn die Daten es zeigen, nennt der Ratsatlas das zuständige Amt." in html
    externe = [h for h in _lesen(html).hrefs if h.startswith("http")]
    assert externe == []
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert "Link zur Seite der Stadt über Anregungen und Beschwerden folgt nach Prüfung" in app


def test_datenschutz_wie_auf_der_seite():
    """Die Sätze zum Datenschutz sagen nichts anderes als datenschutz.html und die Regel zu Hausnummern."""
    html = einfachseite.body("../")
    ds = (ROOT / "site" / "datenschutz.html").read_text(encoding="utf-8")
    assert "setzt keine Cookies" in ds and "Der Ratsatlas setzt keine Cookies." in html
    assert "Zugriffsprotokoll" in ds and "ein Protokoll der Aufrufe" in html
    assert "Was Sie eingeben, wird nicht übertragen." in ds and "Was Sie in die Suche eingeben, bleibt auf Ihrem Gerät." in html
    assert "höchstens auf Ebene der Straße oder des Stadtteils" in ds
    assert "höchstens mit Straße oder Stadtteil. Nie mit Hausnummer." in html
    assert 'href="../datenschutz.html"' in html


def test_saetze_zu_abgeschalteten_themen_nur_mit_freigabe(freigaben):
    """Kurzfassungen (aus) und Kartenebenen (Freigabe „kontext“) erscheinen nur mit ihrer Freigabe."""
    assert freigaben["kurzfassungen"] is False
    html = einfachseite.body("../")
    assert "Zusammenfassung" not in html and "Computerprogramm" not in html
    freigaben["kurzfassungen"] = True
    assert "Ein Computerprogramm hat sie geschrieben." in einfachseite.body("../")
    assert ("Im Menü „Ebenen“ gibt es noch mehr Daten." in html) == bool(freigaben["kontext"])
    freigaben["kontext"] = False
    assert "Im Menü „Ebenen“ gibt es noch mehr Daten." not in einfachseite.body("../")


def test_vorschau_hinweis(tmp_path):
    """In der Kartenvorschau (index.json meta.vorschau) steht oben ein Hinweis; ohne Vorschau und ohne lesbares
    index.json nicht."""
    def schreiben(meta):
        ordner = tmp_path / "data" / "export" / "koeln"
        ordner.mkdir(parents=True, exist_ok=True)
        if meta is None:
            (ordner / "index.json").write_text("{kaputt", encoding="utf-8")
        else:
            (ordner / "index.json").write_text(json.dumps({"meta": meta}), encoding="utf-8")
        einfachseite.write(tmp_path, URL, _page)
        return (tmp_path / "einfach" / "index.html").read_text(encoding="utf-8")
    hinweis = "<strong>Vorschau:</strong> Auf der Karte fehlen noch die Vorlagen der Stadt Köln."
    assert hinweis in schreiben({"vorschau": "2026-11-13T22:00:00+00:00"})
    assert hinweis not in schreiben({"vorschau": None})
    assert hinweis not in schreiben(None)


def test_bau_mit_sitemap_und_kopf(tmp_path):
    """seo.write schreibt einfach/ mit Freigabe und nimmt die Seite in die Sitemap auf; Titel und Beschreibung nennen
    Köln, der Kopf trägt das Kölner Vorschaubild."""
    seo.write(tmp_path, URL)
    seite = (tmp_path / "einfach" / "index.html").read_text(encoding="utf-8")
    assert "<title>Der Ratsatlas Köln in Einfacher Sprache – Ratsatlas Köln</title>" in seite
    assert f'<link rel="canonical" href="{URL}einfach/">' in seite
    assert f'<meta property="og:image" content="{URL}og-image.png">' in seite
    assert "Bonn" not in seite
    assert f"<loc>{URL}einfach/</loc>" in (tmp_path / "sitemap.xml").read_text(encoding="utf-8")


def test_ohne_freigabe_keine_seite(tmp_path, freigaben):
    """Ohne Freigabe weder Seite noch Eintrag in der Sitemap noch Link in der Fußzeile der Unterseiten."""
    freigaben["einfache_sprache"] = False
    seo.write(tmp_path, URL)
    assert not (tmp_path / "einfach").exists()
    assert "einfach/" not in (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert "einfach/" not in (tmp_path / "begriffe" / "index.html").read_text(encoding="utf-8")


def test_fusszeile_der_unterseiten_mit_link():
    """Mit Freigabe verweist die Fußzeile jeder Unterseite (gebietsseiten._page) auf die Einfache Sprache."""
    html = _page(URL, "gebiete/", "T", "B", "<h1>x</h1>", "../../")
    assert '<a href="../../begriffe/">Begriffe</a> · <a href="../../einfach/">Einfache Sprache</a> · ' in html


def test_karte_und_eintrag_auf_der_startseite(freigaben):
    """Mit Freigabe bleiben Karte (Menü „Verstehen“) und Einträge in den Dialogen „Über“ und „Was ist neu?“ in der
    veröffentlichten Startseite, ohne Freigabe fallen alle heraus (seo.ohne_abgeschaltete)."""
    index = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    karte = '<a class="card" href="einfach/" data-funktion="einfache_sprache" hidden>'
    eintrag = '<li data-funktion="einfache_sprache"><a href="einfach/">Einfache Sprache</a>'
    neu = '<li data-funktion="einfache_sprache">Der Ratsatlas in Einfacher Sprache:'
    an = seo.ohne_abgeschaltete(index)
    assert karte in an and eintrag in an and neu in an
    freigaben["einfache_sprache"] = False
    aus = seo.ohne_abgeschaltete(index)
    assert karte not in aus and eintrag not in aus and neu not in aus and 'href="einfach/"' not in aus
    assert "Einfache Sprache" not in aus and "Einfacher Sprache" not in aus


def test_woerter_ohne_markup():
    """Die Erklärungen der Wörter sind reiner Text (die Seite setzt sie mit escape); keine doppelten Leerzeichen."""
    for wort, text, _ in einfachseite.WOERTER:
        assert "<" not in wort + text and "  " not in text, wort
