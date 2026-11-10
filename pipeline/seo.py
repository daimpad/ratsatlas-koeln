"""Auffindbarkeit der Seite: robots.txt, sitemap.xml und absolute Adressen (canonical, Open Graph,
strukturierte Daten, Fehlerseite) für die öffentliche Adresse SITE_URL.

Die Quelldateien in site/ enthalten die Adresse von GitHub Pages; dieser Schritt ersetzt sie in der
zusammengestellten Seite (_site), damit ein Wechsel auf die eigene Domain nur SITE_URL braucht.
Ohne Zeitstempel (kein lastmod), damit sich der Branch deploy nur bei Inhaltsänderungen ändert."""
import re
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape

from . import begriffsseite, config, dossier, einfachseite, gebietsseiten, haushaltsseite, rssseite, technikseite
from .themenseiten import ALLE as THEMENSEITEN

DEFAULT_URL = "https://daimpad.github.io/ratsatlas-koeln/"  # Platzhalter in site/, wird durch SITE_URL ersetzt
PAGES = ("index.html", "404.html", "datenschutz.html")
SITEMAP = ("", "datenschutz.html")  # Pfade relativ zu SITE_URL


def robots(site_url):
    return f"User-agent: *\nAllow: /\n\nSitemap: {site_url}sitemap.xml\n"


def sitemap(site_url, extra=()):
    urls = "".join(f"  <url><loc>{escape(site_url + path)}</loc>{'' if path else '<changefreq>daily</changefreq>'}</url>\n"
                   for path in (*SITEMAP, *extra))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n")


AUS_FUNKTION = re.compile(r'\s*<a class="card" href="[^"]*" data-funktion="(\w+)" hidden>.*?</a>', re.S)
# Texte zu Zusatzthemen auf Seiten ohne Skript (datenschutz.html; Entscheidung 10.11.2026): Element mit data-funktion als
# erstem und einzigem Attribut, ohne hidden, also sichtbar, solange es da ist. Abschnitte und Listeneinträge stehen auf
# eigenen Zeilen und fallen samt Zeile heraus, einzelne Sätze als span im Fließtext. Ein solches Element darf kein
# Element derselben Art enthalten (die Suche endet am ersten schließenden Tag).
AUS_BLOCK = re.compile(r'^[ \t]*<(section|li) data-funktion="(\w+)">.*?</\1>[ \t]*\n', re.S | re.M)
AUS_SATZ = re.compile(r'<span data-funktion="(\w+)">.*?</span>', re.S)


class _Sichtbar(HTMLParser):
    """Wache nach dem Entfernen: jedes Start-Tag mit data-funktion (Wert in doppelten, einfachen oder ohne
    Anführungszeichen, an beliebiger Stelle im Tag) ohne das Attribut hidden. Kommentare und der Inhalt von script und
    style zählen nicht (HTMLParser meldet dort keine Tags); aria-hidden ist nicht hidden."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.funde = []

    def handle_starttag(self, tag, attrs):
        werte = dict(attrs)
        if "data-funktion" in werte and "hidden" not in werte:
            self.funde.append((werte["data-funktion"] or "", self.get_starttag_text()))


def sichtbare_funktionen(html):
    """(Funktion, Tag) für jedes sichtbare Element mit data-funktion (ohne hidden) in `html`."""
    p = _Sichtbar()
    p.feed(html)
    p.close()
    return p.funde


def ohne_abgeschaltete(html):
    """Karten abgeschalteter Zusatzthemen (data-funktion, config.ZUSATZTHEMEN) aus der veröffentlichten Seite entfernen,
    damit Suchmaschinen keinen Links auf nicht erzeugte Seiten folgen; ebenso Abschnitte, Listeneinträge und Sätze, die
    eine abgeschaltete Funktion beschreiben (AUS_BLOCK, AUS_SATZ). Mit Freigabe bleibt alles unverändert; die Quelle in
    site/ bleibt vollständig. Elemente mit hidden (Startseite; app.js zeigt sie nur mit Freigabe) bleiben stehen. Jedes
    andere Element einer abgeschalteten Funktion, das danach noch in der Seite steht (andere Form als AUS_BLOCK und
    AUS_SATZ, etwa weitere Attribute, einfache Anführungszeichen oder ein anderes Element), bricht den Bau ab."""
    an = config.ZUSATZTHEMEN.get
    html = AUS_FUNKTION.sub(lambda m: m.group(0) if an(m.group(1)) else "", html)
    html = AUS_BLOCK.sub(lambda m: m.group(0) if an(m.group(2)) else "", html)
    html = AUS_SATZ.sub(lambda m: m.group(0) if an(m.group(1)) else "", html)
    rest = [tag for funktion, tag in sichtbare_funktionen(html) if not an(funktion)]
    if rest:
        raise ValueError("Text einer abgeschalteten Funktion nicht entfernt (entfernt werden nur "
                         f'<section data-funktion="…">, <li data-funktion="…"> und <span data-funktion="…">): {rest}')
    return html


def write(site=Path("_site"), site_url=None):
    site_url = site_url or config.SITE_URL
    if not site_url.endswith("/"):
        site_url += "/"
    for name in PAGES:
        page = site / name
        if page.exists():
            html = page.read_text(encoding="utf-8").replace(DEFAULT_URL, site_url)
            page.write_text(gebietsseiten.neuer_tab(ohne_abgeschaltete(html)), encoding="utf-8")
    (site / "robots.txt").write_text(robots(site_url), encoding="utf-8")
    areas = gebietsseiten.write(site, site_url)
    an = lambda thema: config.ZUSATZTHEMEN.get(thema)   # Bonner Zusatzthemen nur bei Freigabe (CLAUDE.md 5.4)
    themen = []
    if an("themenseiten"):
        themen = [pfad for t in THEMENSEITEN for pfad in dossier.write(t, site, site_url, gebietsseiten._page)]
        themen = dossier.uebersicht(THEMENSEITEN, site, site_url, gebietsseiten._page) + themen
    if an("haushalt"):
        themen += haushaltsseite.write(site, site_url, gebietsseiten._page)
    themen += rssseite.write(site, site_url, gebietsseiten._page)
    themen += begriffsseite.write(site, site_url, gebietsseiten._page)
    if an("einfache_sprache"):
        themen += einfachseite.write(site, site_url, gebietsseiten._page)
    if an("technik"):   # beschreibt die Workflows; für Köln nach Phase 5
        themen += technikseite.write(site, site_url, gebietsseiten._page)
    (site / "sitemap.xml").write_text(sitemap(site_url, [*themen, *areas]), encoding="utf-8")
    print(f"robots.txt, sitemap.xml und Adressen für {site_url}")
