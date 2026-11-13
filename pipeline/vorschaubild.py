"""Vorschaubild der Seite zum Teilen (Open Graph, 1200 × 630 Pixel; zweiter Lauf, Entscheidung 04.11.2026, umgesetzt am
13.11.2026). Ersetzt das Bonner Bild (site/og-image.jpg mit Kacheln aus OpenStreetMap), das nie ausgeliefert wurde.

Inhalt: Schriftzug „Ratsatlas Köln“ mit dem Zeichen aus site/favicon.svg, der Untertitel der Seite (wie im Titel von
site/index.html), Zahl der Stadtbezirke und Stadtteile und rechts eine Karte der Stadtteile mit den Grenzen der
Stadtbezirke. Die Karte zeichnet nur die Flächen aus data/geo (lückenlose Abdeckung, Stadt Köln, dl-de/zero 2.0), keine
Kartenkacheln und keine Daten aus OpenStreetMap; damit gilt für das Bild keine ODbL. Die Namensnennung
(config.NAMENSNENNUNG) steht im Bild unter der Karte, im Alternativtext und in data/LICENSE-DATA.md.

Farben und Schrift aus der Seite: Gestaltungsmerkmale (CSS-Variablen in :root) aus site/style.css, Schrift Inter aus
site/fonts/ (als data-Adresse eingebettet), Zeichen aus site/favicon.svg. Projektion ETRS89 / UTM 32N (EPSG 25832, wie
die Quelldaten der Stadt), Norden oben, Koordinaten auf 0,1 Pixel gerundet.

html() erzeugt eine vollständige Seite ohne Netzanfragen und ohne Zeitangaben (gleiche Eingaben, gleicher Text);
tools/vorschaubild.py rendert sie mit Chromium (Playwright, 1200 × 630, deviceScaleFactor 1) nach site/og-image.png und
vermerkt im PNG die Prüfsumme dieser Seite (tEXt „Ratsatlas-Eingabe“) und die Namensnennung (iTXt „Copyright“); ein
Test vergleicht die Prüfsumme mit der Seite aus dem aktuellen Stand und meldet so ein veraltetes Bild.
meta_tags() liefert die Angaben für den Kopf der Unterseiten; site/index.html führt dieselben Angaben fest (Prüfung in
tests/test_vorschaubild.py)."""
import base64
import hashlib
import json
import re
import struct
import zlib
from functools import lru_cache
from html import escape
from urllib.parse import urlsplit

from pyproj import Transformer

from . import config

DATEI = "og-image.png"
BREITE, HOEHE = 1200, 630
TYP = "image/png"
NAME = "Ratsatlas Köln"
# Untertitel wie im Titel der Startseite (site/index.html), sachlich und ohne Werbung
UNTERTITEL = "Was Rat, Ausschüsse und Bezirksvertretungen beraten – wo, wann und wer"
LIZENZ_GEBIETE = "dl-de/zero 2.0"
SITE = config.ROOT / "site"
SCHRIFT = SITE / "fonts" / "inter-latin-wght-normal.woff2"
STIL = SITE / "style.css"
ZEICHEN = SITE / "favicon.svg"
# Gestaltungsmerkmale aus site/style.css, die das Bild verwendet
MERKMALE = ("--bg", "--bg-gradient", "--text", "--text-muted", "--accent-soft", "--accent-ink", "--accent-fill",
            "--surface-strong", "--shadow-lift", "--cta-shadow", "--radius")

# Lage der Karte im Bild (Pixel): Glasfläche rechts, Karte darin mit Rand, Quellenzeile unten
KARTE_FLAECHE = (660, 36, 504, 558)       # x, y, Breite, Höhe der Glasfläche
KARTE_RAND = 22
KARTE_QUELLE_H = 30


def merkmale(css=None):
    """Werte der Gestaltungsmerkmale MERKMALE aus dem ersten :root-Block von site/style.css; ein fehlendes Merkmal
    bricht ab (das Bild soll nicht mit erfundenen Farben entstehen)."""
    css = STIL.read_text(encoding="utf-8") if css is None else css
    block = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    if not block:
        raise ValueError("site/style.css: kein :root-Block")
    werte = {m[1]: " ".join(m[2].split()) for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block[1])}
    fehlt = [k for k in MERKMALE if k not in werte]
    if fehlt:
        raise ValueError(f"site/style.css: Gestaltungsmerkmale fehlen: {fehlt}")
    return {k: werte[k] for k in MERKMALE}


def _flaechen(pfad):
    return json.loads(pfad.read_text(encoding="utf-8"))["features"]


def gebiete():
    """(Stadtteile, Stadtbezirke) aus data/geo, je Liste von Features."""
    return _flaechen(config.ORTSTEILE), _flaechen(config.STADTBEZIRKE)


@lru_cache(maxsize=1)
def zahlen():
    """(Zahl der Stadtbezirke, Zahl der Stadtteile) aus data/geo (einmal je Lauf gelesen)."""
    teile, bezirke = gebiete()
    return len(bezirke), len(teile)


def alt_text():
    """Alternativtext des Bildes (og:image:alt, twitter:image:alt) mit Namensnennung der Gebietsgrenzen."""
    n_bezirke, n_teile = zahlen()
    return (f"{NAME}: Schriftzug und der Satz „{UNTERTITEL}“ neben einer Karte der {n_bezirke} Stadtbezirke und "
            f"{n_teile} Stadtteile von Köln. Gebietsgrenzen: Stadt Köln – offenedaten-koeln.de ({LIZENZ_GEBIETE}).")


def _ringe(geometrie):
    """Alle Ringe (äußere und Löcher) einer Polygon- oder MultiPolygon-Geometrie als Koordinatenlisten."""
    if geometrie["type"] == "Polygon":
        return list(geometrie["coordinates"])
    if geometrie["type"] == "MultiPolygon":
        return [ring for polygon in geometrie["coordinates"] for ring in polygon]
    raise ValueError(f"Geometrie {geometrie['type']} ist keine Fläche")


class Abbildung:
    """WGS84 → EPSG 25832 → Pixel im Kartenfeld (Norden oben, gleicher Maßstab in beiden Richtungen, mittig)."""

    def __init__(self, features, feld):
        self._utm = Transformer.from_crs(4326, 25832, always_xy=True).transform
        punkte = [self._utm(x, y) for f in features for ring in _ringe(f["geometry"]) for x, y in ring]
        xs, ys = [p[0] for p in punkte], [p[1] for p in punkte]
        self.x0, self.y1 = min(xs), max(ys)
        fx, fy, fb, fh = feld
        self.massstab = min(fb / (max(xs) - self.x0), fh / (self.y1 - min(ys)))
        self.dx = fx + (fb - (max(xs) - self.x0) * self.massstab) / 2
        self.dy = fy + (fh - (self.y1 - min(ys)) * self.massstab) / 2

    def __call__(self, lon, lat):
        x, y = self._utm(lon, lat)
        return round(self.dx + (x - self.x0) * self.massstab, 1), round(self.dy + (self.y1 - y) * self.massstab, 1)


def pfad(geometrie, abbildung):
    """SVG-Pfad einer Fläche in Pixeln; aufeinanderfolgende gleiche Punkte (nach dem Runden) entfallen."""
    teile = []
    for ring in _ringe(geometrie):
        punkte = []
        for lon, lat in ring:
            p = abbildung(lon, lat)
            if not punkte or punkte[-1] != p:
                punkte.append(p)
        if len(punkte) >= 3:
            teile.append("M" + "L".join(f"{x:g} {y:g}" for x, y in punkte) + "Z")
    return "".join(teile)


def karte_svg():
    """Karte der Stadtteile (Fläche) mit den Grenzen der Stadtbezirke als SVG-Elemente in Bildkoordinaten."""
    teile, bezirke = gebiete()
    x, y, b, h = KARTE_FLAECHE
    feld = (x + KARTE_RAND, y + KARTE_RAND, b - 2 * KARTE_RAND, h - 2 * KARTE_RAND - KARTE_QUELLE_H)
    abbildung = Abbildung(bezirke, feld)
    # feste Reihenfolge nach Nummer, unabhängig von der Reihenfolge in der Datei
    flaechen = "".join(f'<path d="{pfad(f["geometry"], abbildung)}"/>'
                       for f in sorted(teile, key=lambda f: int(f["properties"]["ortsteil"])))
    grenzen = "".join(f'<path d="{pfad(f["geometry"], abbildung)}"/>'
                      for f in sorted(bezirke, key=lambda f: int(f["properties"]["bezirk"])))
    return (f'<g class="teile">{flaechen}</g>'
            f'<g class="bezirke">{grenzen}</g>')


def _daten_adresse(pfad, typ):
    return f"data:{typ};base64," + base64.b64encode(pfad.read_bytes()).decode("ascii")


def host():
    """Hauptadresse der Seite ohne Schema und Schrägstrich am Ende (config.SITE_URL_HAUPT, nicht die Umgebungsvariable
    SITE_URL: das Bild nennt immer koeln.ratsatlas.de), etwa „koeln.ratsatlas.de“."""
    teile = urlsplit(config.SITE_URL_HAUPT)
    return (teile.netloc + teile.path).rstrip("/")


def html():
    """Vollständige Seite des Bildes (1200 × 630) ohne Netzanfragen: Schrift und Zeichen als data-Adressen."""
    m = merkmale()
    n_bezirke, n_teile = zahlen()
    x, y, b, h = KARTE_FLAECHE
    variablen = "\n".join(f"    {k}: {v};" for k, v in m.items())
    chips = "".join(f'<span class="chip">{escape(t)}</span>'
                    for t in (f"{n_bezirke} Stadtbezirke", f"{n_teile} Stadtteile", "Karte und Zeitleiste"))
    quelle = f"{config.NAMENSNENNUNG} · {LIZENZ_GEBIETE}"
    # Umbruch nach dem Gedankenstrich: „wo, wann und wer“ bleibt zusammen
    vorn, _, hinten = UNTERTITEL.partition(" – ")
    untertitel = f"{escape(vorn)} –<br>{escape(hinten)}" if hinten else escape(UNTERTITEL)
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{escape(NAME)} – Vorschaubild</title>
<style>
  @font-face {{ font-family: "Inter"; font-style: normal; font-weight: 100 900;
    src: url("{_daten_adresse(SCHRIFT, 'font/woff2')}") format("woff2"); }}
  :root {{
{variablen}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; width: {BREITE}px; height: {HOEHE}px; overflow: hidden; }}
  body {{ position: relative; font-family: "Inter", sans-serif; color: var(--text);
    background: var(--bg-gradient), var(--bg); -webkit-font-smoothing: antialiased; }}
  .text {{ position: absolute; left: 72px; top: 0; bottom: 0; width: 548px; display: flex; flex-direction: column;
    justify-content: center; gap: 26px; }}
  .marke {{ display: flex; align-items: center; gap: 22px; }}
  .marke img {{ width: 84px; height: 84px; border-radius: 20px; box-shadow: var(--cta-shadow); }}
  h1 {{ margin: 0; font-size: 62px; line-height: 1; font-weight: 750; letter-spacing: -0.025em; white-space: nowrap; }}
  h1 span {{ color: var(--accent-ink); }}
  p {{ margin: 0; font-size: 31px; line-height: 1.28; font-weight: 600; letter-spacing: -0.01em; }}
  .chips {{ display: flex; gap: 10px; }}
  .chip {{ padding: 8px 16px; border-radius: 999px; background: color-mix(in srgb, var(--accent-fill) 11%, transparent); color: var(--accent-ink);
    font-size: 18px; font-weight: 600; white-space: nowrap; }}
  .adresse {{ position: absolute; left: 72px; bottom: 40px; font-size: 21px; font-weight: 600; color: var(--text-muted); }}
  .glas {{ position: absolute; left: {x}px; top: {y}px; width: {b}px; height: {h}px; border-radius: var(--radius);
    background: var(--surface-strong); box-shadow: var(--shadow-lift); }}
  svg {{ position: absolute; left: 0; top: 0; }}
  .teile path {{ fill: color-mix(in srgb, var(--accent-soft) 42%, #ffffff); stroke: #ffffff; stroke-width: 1.1; stroke-linejoin: round; }}
  .bezirke path {{ fill: none; stroke: var(--accent-fill); stroke-width: 2.2; stroke-linejoin: round; }}
  .quelle {{ position: absolute; left: {x + KARTE_RAND}px; width: {b - 2 * KARTE_RAND}px; top: {y + h - KARTE_RAND - 18}px;
    font-size: 15px; line-height: 18px; color: var(--text-muted); text-align: right; white-space: nowrap; }}
</style>
</head>
<body>
<div class="text">
  <div class="marke"><img src="{_daten_adresse(ZEICHEN, 'image/svg+xml')}" alt=""><h1><span>Ratsatlas</span> Köln</h1></div>
  <p>{untertitel}</p>
  <div class="chips">{chips}</div>
</div>
<div class="adresse">{escape(host())}</div>
<div class="glas"></div>
<svg width="{BREITE}" height="{HOEHE}" viewBox="0 0 {BREITE} {HOEHE}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{karte_svg()}</svg>
<div class="quelle">{escape(quelle)}</div>
</body>
</html>
"""


def meta_tags(site_url):
    """Angaben zum Vorschaubild für den Kopf einer Seite (absolute Adresse unter site_url)."""
    bild = escape(site_url + DATEI)
    alt = escape(alt_text())
    return (f'  <meta property="og:image" content="{bild}">\n'
            f'  <meta property="og:image:type" content="{TYP}">\n'
            f'  <meta property="og:image:width" content="{BREITE}">\n'
            f'  <meta property="og:image:height" content="{HOEHE}">\n'
            f'  <meta property="og:image:alt" content="{alt}">\n'
            f'  <meta name="twitter:card" content="summary_large_image">\n'
            f'  <meta name="twitter:image" content="{bild}">\n'
            f'  <meta name="twitter:image:alt" content="{alt}">\n')


# --- Vermerke im PNG -------------------------------------------------------------------------------------------------
VERMERK_EINGABE = "Ratsatlas-Eingabe"   # tEXt: SHA-256 von html()
VERMERK_RECHTE = "Copyright"            # iTXt (UTF-8): Namensnennung der Gebietsgrenzen
PNG_SIGNATUR = b"\x89PNG\r\n\x1a\n"


def pruefsumme():
    """SHA-256 der Seite des Bildes (html()): ändert sich mit Flächen, Merkmalen, Schrift, Zeichen und Texten."""
    return hashlib.sha256(html().encode("utf-8")).hexdigest()


def rechte():
    return f"Gebietsgrenzen: {config.NAMENSNENNUNG} ({LIZENZ_GEBIETE}). {NAME}, tools/vorschaubild.py"


def _bloecke(png):
    """(Art, Daten) aller Blöcke eines PNG; eine falsche Signatur oder Prüfsumme bricht ab."""
    if not png.startswith(PNG_SIGNATUR):
        raise ValueError("keine PNG-Datei")
    i, out = len(PNG_SIGNATUR), []
    while i < len(png):
        laenge, art = struct.unpack(">I4s", png[i:i + 8])
        daten = png[i + 8:i + 8 + laenge]
        (crc,) = struct.unpack(">I", png[i + 8 + laenge:i + 12 + laenge])
        if zlib.crc32(art + daten) & 0xFFFFFFFF != crc:
            raise ValueError(f"PNG-Block {art!r}: Prüfsumme falsch")
        out.append((art, daten))
        i += 12 + laenge
    return out


def _block(art, daten):
    return struct.pack(">I", len(daten)) + art + daten + struct.pack(">I", zlib.crc32(art + daten) & 0xFFFFFFFF)


def _schluessel(art, daten):
    return daten.split(b"\0", 1)[0].decode("latin-1") if art in (b"tEXt", b"iTXt") else None


def vermerke(png):
    """Texte der Blöcke tEXt und iTXt (unkomprimiert) als {Schlüssel: Text}."""
    out = {}
    for art, daten in _bloecke(png):
        if art == b"tEXt":
            k, text = daten.split(b"\0", 1)
            out[k.decode("latin-1")] = text.decode("latin-1")
        elif art == b"iTXt":
            k, rest = daten.split(b"\0", 1)
            if rest[:1] == b"\0":   # nicht komprimiert
                _, _, text = rest[2:].split(b"\0", 2)
                out[k.decode("latin-1")] = text.decode("utf-8")
    return out


def mit_vermerken(png, summe=None):
    """PNG mit den Vermerken VERMERK_EINGABE und VERMERK_RECHTE vor IEND; gleichnamige Vermerke werden ersetzt."""
    bloecke = [(a, d) for a, d in _bloecke(png) if _schluessel(a, d) not in (VERMERK_EINGABE, VERMERK_RECHTE)]
    if not bloecke or bloecke[-1][0] != b"IEND":
        raise ValueError("PNG ohne IEND am Ende")
    neu = [(b"tEXt", VERMERK_EINGABE.encode("latin-1") + b"\0" + (summe or pruefsumme()).encode("ascii")),
           (b"iTXt", VERMERK_RECHTE.encode("latin-1") + b"\0\0\0de\0\0" + rechte().encode("utf-8"))]
    return PNG_SIGNATUR + b"".join(_block(a, d) for a, d in bloecke[:-1] + neu + bloecke[-1:])


def groesse(png):
    """(Breite, Höhe) aus dem IHDR-Block."""
    art, daten = _bloecke(png)[0]
    if art != b"IHDR":
        raise ValueError("PNG ohne IHDR am Anfang")
    return struct.unpack(">II", daten[:8])
