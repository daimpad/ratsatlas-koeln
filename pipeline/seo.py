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

# Flächen der Startseite, die nur mit Freigabe im HTML stehen (Runde 20, Entscheidung 10.11.2026): Element mit
# data-freigabe="<Funktion>" samt Inhalt, ohne Freigabe in config.ZUSATZTHEMEN entfernt (index.html: Fläche
# „Ratsassistent“ mit „chat“, „Mitmachen in Köln“ mit „mitmachen“). Eigenes Attribut statt data-funktion, weil app.js
# (applyFunktionen) Elemente mit data-funktion bei Freigabe einblendet und style.css sie ohne Freigabe mit display: none
# überschreibt; eine Fläche startet auch mit Freigabe geschlossen und behält ihre Bewegung.
FREIGABE_ATTR = "data-freigabe"

# Content-Security-Policy (Runde 20, Entscheidung 10.11.2026): Quellen in connect-src, die nur eine Funktion braucht;
# beim Ratsassistenten die Anbieter von Sprachmodellen und lokale Modelle (site/chat/providers.js). Die Quelle in site/
# führt sie vollständig für eine spätere Freigabe; ohne Freigabe entfernt der Bau sie aus jeder Seite mit CSP
# (csp_ohne_abgeschaltete).
CSP_NUR_MIT_FREIGABE = {"chat": ("https://api.anthropic.com", "https://api.mistral.ai", "https://openrouter.ai",
                                 "http://localhost:*", "http://127.0.0.1:*")}
CSP_META = re.compile(r'(<meta http-equiv="Content-Security-Policy" content=")([^"]*)(")')


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


class _Bereiche(HTMLParser):
    """Elemente mit FREIGABE_ATTR: (Funktion, Anfang, Ende) als Zeichenstellen in `html`, das Ende hinter dem passenden
    schließenden Tag (gleichnamige Elemente darin werden mitgezählt). Kommentare und der Inhalt von script und style
    zählen nicht. `offen`: Elemente ohne schließendes Tag."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self._html = html
        self._zeilen = [0] + [m.end() for m in re.finditer("\n", html)]
        self.bereiche, self.offen = [], []   # offen: [Tag, Funktion, Anfang, Tiefe gleichnamiger Elemente darin]

    def _stelle(self):
        zeile, spalte = self.getpos()
        return self._zeilen[zeile - 1] + spalte

    def _ende(self):
        """Stelle hinter dem schließenden Tag, an dem der Parser steht (`</name>` hat keine Attribute)."""
        return self._html.index(">", self._stelle()) + 1

    def handle_starttag(self, tag, attrs):
        for o in self.offen:
            if o[0] == tag:
                o[3] += 1
        werte = dict(attrs)
        if FREIGABE_ATTR in werte:
            self.offen.append([tag, werte[FREIGABE_ATTR] or "", self._stelle(), 0])

    def handle_startendtag(self, tag, attrs):
        werte = dict(attrs)
        if FREIGABE_ATTR in werte:
            anfang = self._stelle()
            self.bereiche.append((werte[FREIGABE_ATTR] or "", anfang, anfang + len(self.get_starttag_text())))

    def handle_endtag(self, tag):
        for o in list(self.offen):
            if o[0] != tag:
                continue
            if o[3]:
                o[3] -= 1
            else:
                self.offen.remove(o)
                self.bereiche.append((o[1], o[2], self._ende()))


def bereiche_mit_freigabe(html):
    """(Funktion, Anfang, Ende) für jedes Element mit FREIGABE_ATTR in `html`; ein Element ohne schließendes Tag bricht
    den Bau ab."""
    p = _Bereiche(html)
    p.feed(html)
    p.close()
    if p.offen:
        raise ValueError(f"Element mit {FREIGABE_ATTR} ohne schließendes Tag: "
                         f"{[html[o[2]:html.index('>', o[2]) + 1] for o in p.offen]}")
    return sorted(p.bereiche, key=lambda b: b[1])


def ohne_abgeschaltete_bereiche(html):
    """Elemente mit FREIGABE_ATTR, deren Funktion nicht freigegeben ist (config.ZUSATZTHEMEN), samt Inhalt entfernen;
    steht das Element allein auf seinen Zeilen, fallen die Zeilen mit heraus (und eine Leerzeile, wenn davor schon eine
    steht). Mit Freigabe bleibt die Seite unverändert. Steht danach noch ein solches Element in der Seite, bricht der Bau
    ab."""
    an = config.ZUSATZTHEMEN.get
    weg = []
    for funktion, anfang, ende in bereiche_mit_freigabe(html):
        if not an(funktion) and not (weg and anfang < weg[-1][1]):   # in einem schon entfernten Element enthalten
            weg.append((anfang, ende))
    for anfang, ende in reversed(weg):
        zeile = html.rfind("\n", 0, anfang) + 1
        schluss = html.find("\n", ende)
        schluss = len(html) if schluss < 0 else schluss + 1
        if not html[zeile:anfang].strip() and not html[ende:schluss].strip():
            anfang, ende = zeile, schluss
            if html[:anfang].endswith("\n\n") and html[ende:].startswith("\n"):
                ende += 1
        html = html[:anfang] + html[ende:]
    rest = [html[a:html.index(">", a) + 1] for f, a, _ in bereiche_mit_freigabe(html) if not an(f)]
    if rest:
        raise ValueError(f"Fläche einer abgeschalteten Funktion nicht entfernt ({FREIGABE_ATTR}): {rest}")
    return html


class _Richtlinien(HTMLParser):
    """Inhalt jedes <meta http-equiv="Content-Security-Policy"> (Groß- und Kleinschreibung, Reihenfolge und
    Anführungszeichen der Attribute gleich)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.richtlinien = []

    def handle_starttag(self, tag, attrs):
        werte = {k: v or "" for k, v in attrs}
        if tag == "meta" and werte.get("http-equiv", "").strip().lower() == "content-security-policy":
            self.richtlinien.append(werte.get("content", ""))

    handle_startendtag = handle_starttag


def csp_richtlinien(html):
    """Inhalt aller Content-Security-Policy-Angaben (meta http-equiv) in `html`."""
    p = _Richtlinien()
    p.feed(html)
    p.close()
    return p.richtlinien


def _host(quelle):
    """Host einer Quelle aus CSP_NUR_MIT_FREIGABE („https://api.anthropic.com“ → „api.anthropic.com“)."""
    return quelle.split("://", 1)[1].split(":", 1)[0].split("/", 1)[0].lower()


def csp_ohne_abgeschaltete(html):
    """connect-src jeder Content-Security-Policy in `html` ohne die Quellen abgeschalteter Funktionen
    (CSP_NUR_MIT_FREIGABE, config.ZUSATZTHEMEN); bleibt keine Quelle, gilt 'none'. Mit Freigabe und auf Seiten ohne
    solche Quellen bleibt `html` unverändert. Nennt eine Richtlinie danach noch den Host einer solchen Quelle (andere
    Direktive, Schreibweise oder Form des meta-Elements), bricht der Bau ab."""
    aus = [q for f, quellen in CSP_NUR_MIT_FREIGABE.items() if not config.ZUSATZTHEMEN.get(f) for q in quellen]
    if not aus:
        return html

    def richtlinie(m):
        teile = m[2].split(";")
        for i, teil in enumerate(teile):
            worte = teil.split()
            if worte and worte[0].lower() == "connect-src":
                bleibt = [w for w in worte[1:] if w not in aus]
                if len(bleibt) < len(worte) - 1:
                    vorn = teil[:len(teil) - len(teil.lstrip())]
                    teile[i] = vorn + " ".join([worte[0], *(bleibt or ["'none'"])])
        return m[1] + ";".join(teile) + m[3]

    html = CSP_META.sub(richtlinie, html)
    hosts = {_host(q) for q in aus}
    rest = sorted({w for r in csp_richtlinien(html) for w in r.lower().split() for h in hosts if h in w})
    if rest:
        raise ValueError(f"Content-Security-Policy nennt noch Quellen einer abgeschalteten Funktion: {rest}")
    return html


def csp_alle(site):
    """csp_ohne_abgeschaltete auf jede HTML-Datei unter `site` anwenden (geschrieben nur bei Änderung); Zahl der
    geänderten Dateien."""
    n = 0
    for seite in sorted(Path(site).rglob("*.html")):
        html = seite.read_text(encoding="utf-8")
        neu = csp_ohne_abgeschaltete(html)
        if neu != html:
            seite.write_text(neu, encoding="utf-8")
            n += 1
    return n


def ohne_abgeschaltete(html):
    """Karten abgeschalteter Zusatzthemen (data-funktion, config.ZUSATZTHEMEN) aus der veröffentlichten Seite entfernen,
    damit Suchmaschinen keinen Links auf nicht erzeugte Seiten folgen; ebenso Abschnitte, Listeneinträge und Sätze, die
    eine abgeschaltete Funktion beschreiben (AUS_BLOCK, AUS_SATZ). Mit Freigabe bleibt alles unverändert; die Quelle in
    site/ bleibt vollständig. Elemente mit hidden (Startseite; app.js zeigt sie nur mit Freigabe) bleiben stehen. Jedes
    andere Element einer abgeschalteten Funktion, das danach noch in der Seite steht (andere Form als AUS_BLOCK und
    AUS_SATZ, etwa weitere Attribute, einfache Anführungszeichen oder ein anderes Element), bricht den Bau ab. Flächen
    mit FREIGABE_ATTR fallen ohne Freigabe ganz heraus (ohne_abgeschaltete_bereiche, Runde 20)."""
    an = config.ZUSATZTHEMEN.get
    html = ohne_abgeschaltete_bereiche(html)
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
    # zuletzt, über alle Seiten (auch die hier erzeugten): CSP ohne Quellen abgeschalteter Funktionen
    n = csp_alle(site)
    print(f"robots.txt, sitemap.xml und Adressen für {site_url}"
          + (f"; Content-Security-Policy ohne abgeschaltete Funktionen in {n} Seiten" if n else ""))
