"""Auffindbarkeit der Seite: robots.txt, sitemap.xml und absolute Adressen (canonical, Open Graph,
strukturierte Daten, Fehlerseite) für die öffentliche Adresse SITE_URL.

Die Quelldateien in site/ enthalten die Adresse von GitHub Pages; dieser Schritt ersetzt sie in der
zusammengestellten Seite (_site), damit ein Wechsel auf die eigene Domain nur SITE_URL braucht.
Ohne Zeitstempel (kein lastmod), damit sich der Branch deploy nur bei Inhaltsänderungen ändert."""
from pathlib import Path
from xml.sax.saxutils import escape

from . import begriffsseite, config, dossier, einfachseite, gebietsseiten, haushaltsseite, rssseite, technikseite
from .themenseiten import ALLE as THEMENSEITEN

DEFAULT_URL = "https://daimpad.github.io/allris-test/"  # Platzhalter in site/, wird durch SITE_URL ersetzt
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


def write(site=Path("_site"), site_url=None):
    site_url = site_url or config.SITE_URL
    if not site_url.endswith("/"):
        site_url += "/"
    for name in PAGES:
        page = site / name
        if page.exists():
            page.write_text(gebietsseiten.neuer_tab(page.read_text(encoding="utf-8").replace(DEFAULT_URL, site_url)), encoding="utf-8")
    (site / "robots.txt").write_text(robots(site_url), encoding="utf-8")
    areas = gebietsseiten.write(site, site_url)
    themen = [pfad for t in THEMENSEITEN for pfad in dossier.write(t, site, site_url, gebietsseiten._page)]
    themen = dossier.uebersicht(THEMENSEITEN, site, site_url, gebietsseiten._page) + themen
    themen += haushaltsseite.write(site, site_url, gebietsseiten._page)
    themen += rssseite.write(site, site_url, gebietsseiten._page)
    themen += begriffsseite.write(site, site_url, gebietsseiten._page)
    themen += einfachseite.write(site, site_url, gebietsseiten._page)
    themen += technikseite.write(site, site_url, gebietsseiten._page)
    (site / "sitemap.xml").write_text(sitemap(site_url, [*themen, *areas]), encoding="utf-8")
    print(f"robots.txt, sitemap.xml und Adressen für {site_url}")
