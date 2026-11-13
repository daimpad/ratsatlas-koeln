"""Kölner Vorschaubild (site/og-image.png, pipeline/vorschaubild.py, tools/vorschaubild.py; 13.11.2026): PNG mit
1200 × 630 Pixeln aus dem aktuellen Stand (im PNG vermerkte Prüfsumme der Eingaben), nur Flächen aus data/geo ohne
Kacheln, Farben aus site/style.css, Schrift aus site/fonts/, Namensnennung im Bild, im Alternativtext, im PNG und in
data/LICENSE-DATA.md; Angaben im Kopf von index.html und der Unterseiten mit Typ, Breite, Höhe und Alternativtext;
nirgends mehr ein Bonner Bild oder Bonn in og:, twitter: oder dem Manifest. Keine Anfragen an Server der Stadt."""
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from pipeline import config, gebietsseiten, seo, vorschaubild

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
BILD = SITE / vorschaubild.DATEI
URL = "https://koeln.ratsatlas.de/"


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("property") or a.get("name")):
            self.meta.append((a.get("property") or a.get("name"), a.get("content") or ""))

    handle_startendtag = handle_starttag


def _meta(html):
    p = _Meta()
    p.feed(html)
    p.close()
    return p.meta


def _teilen(html):
    """og:- und twitter:-Angaben als {Name: [Werte]}."""
    out = {}
    for name, wert in _meta(html):
        if name.startswith(("og:", "twitter:")):
            out.setdefault(name, []).append(wert)
    return out


def test_bild_aktuell_und_im_format():
    """Das eingecheckte Bild ist ein PNG mit 1200 × 630 Pixeln und stammt aus dem aktuellen Stand: Die vermerkte
    Prüfsumme gleicht der Seite des Bildes aus den heutigen Flächen, Merkmalen, Schrift, Zeichen und Texten
    (sonst: python3 tools/vorschaubild.py, Bild ansehen, committen)."""
    png = BILD.read_bytes()
    assert vorschaubild.groesse(png) == (1200, 630)
    vermerke = vorschaubild.vermerke(png)
    assert vermerke[vorschaubild.VERMERK_EINGABE] == vorschaubild.pruefsumme()
    assert vermerke[vorschaubild.VERMERK_RECHTE] == vorschaubild.rechte()
    assert config.NAMENSNENNUNG in vermerke[vorschaubild.VERMERK_RECHTE]
    assert len(png) < 1_000_000


def test_bonner_bild_entfernt():
    """Das Bonner Bild (Kacheln aus OpenStreetMap, „Ratsatlas Bonn“) liegt nicht mehr im Repository, und der Bau muss
    es nicht mehr entfernen."""
    assert not (SITE / "og-image.jpg").exists()
    assert "og-image.jpg" not in (ROOT / "tools" / "seite_bauen.py").read_text(encoding="utf-8")


def test_seite_des_bildes_ohne_netz_und_ohne_kacheln():
    """html(): gleiche Ausgabe bei jedem Aufruf, keine Adresse außer data:, keine Kacheln oder OpenStreetMap;
    Schrift Inter aus site/fonts/ und Zeichen aus site/favicon.svg eingebettet; 86 Stadtteile und 9 Stadtbezirke als
    Pfade; Farben aus site/style.css; Hauptadresse unabhängig von der Umgebungsvariable SITE_URL."""
    html = vorschaubild.html()
    assert html == vorschaubild.html()
    adressen = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"|url\("([^"]*)"\)', html)
    assert adressen and all((a or b).startswith("data:") for a, b in adressen)
    assert not re.search(r"https?://", html.replace('xmlns="http://www.w3.org/2000/svg"', ""))
    for wort in ("openstreetmap", "OpenStreetMap", "tile", "Protomaps", "kacheln", "Bonn"):
        assert wort not in html, wort
    assert 'font-family: "Inter"' in html and "data:font/woff2;base64," in html
    assert "data:image/svg+xml;base64," in html
    gruppen = dict(re.findall(r'<g class="(teile|bezirke)">(.*?)</g>', html))
    assert gruppen["teile"].count("<path ") == 86 and gruppen["bezirke"].count("<path ") == 9
    for name, wert in vorschaubild.merkmale().items():
        assert f"{name}: {wert};" in html
    assert "<span>Ratsatlas</span> Köln" in html and "koeln.ratsatlas.de" in html
    assert f"{config.NAMENSNENNUNG} · dl-de/zero 2.0" in html
    assert "9 Stadtbezirke" in html and "86 Stadtteile" in html


def test_merkmale_aus_style_css():
    """Fehlt ein Gestaltungsmerkmal in :root, entsteht kein Bild mit erfundenen Farben."""
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert vorschaubild.merkmale(css)["--accent-ink"] == "#6d28d9"
    with pytest.raises(ValueError, match="--accent-ink"):
        vorschaubild.merkmale(css.replace("--accent-ink:", "--accent-tinte:"))


def test_karte_im_feld_und_norden_oben():
    """Alle Punkte der Karte liegen im Kartenfeld der Glasfläche; ein Punkt von Chorweiler (ganz im Norden) liegt über
    einem von Porz (im Süden)."""
    html = vorschaubild.html()
    zahlen = [float(z) for d in re.findall(r'<path d="([^"]+)"', html) for z in re.findall(r"-?\d+(?:\.\d+)?", d)]
    xs, ys = zahlen[0::2], zahlen[1::2]
    x, y, b, h = vorschaubild.KARTE_FLAECHE
    assert x + vorschaubild.KARTE_RAND - 0.1 <= min(xs) and max(xs) <= x + b - vorschaubild.KARTE_RAND + 0.1
    assert y + vorschaubild.KARTE_RAND - 0.1 <= min(ys) and max(ys) <= y + h - vorschaubild.KARTE_RAND + 0.1
    teile, bezirke = vorschaubild.gebiete()
    abbildung = vorschaubild.Abbildung(bezirke, (0, 0, 100, 100))
    punkt = {f["properties"]["bezirk_bez"]: abbildung(*f["geometry"]["coordinates"][0][0]) for f in bezirke}
    assert punkt["Chorweiler"][1] < punkt["Porz"][1]


def test_vermerke_im_png():
    """mit_vermerken ersetzt vorhandene Vermerke (kein doppelter Block) und hält die Blöcke gültig."""
    png = BILD.read_bytes()
    zweimal = vorschaubild.mit_vermerken(vorschaubild.mit_vermerken(png, "a" * 64), "b" * 64)
    assert vorschaubild.vermerke(zweimal)[vorschaubild.VERMERK_EINGABE] == "b" * 64
    arten = [a for a, _ in vorschaubild._bloecke(zweimal)]
    assert arten[0] == b"IHDR" and arten[-1] == b"IEND" and arten.count(b"tEXt") == arten.count(b"iTXt") == 1
    with pytest.raises(ValueError, match="Prüfsumme"):
        vorschaubild._bloecke(png[:20] + bytes([png[20] ^ 1]) + png[21:])


def test_angaben_im_kopf_der_startseite():
    """index.html führt genau die Angaben aus vorschaubild.meta_tags (Typ, Breite, Höhe, Alternativtext, großes Bild);
    nach seo.write zeigen sie auf SITE_URL; keine Angabe nennt Bonn."""
    index = (SITE / "index.html").read_text(encoding="utf-8")
    assert vorschaubild.meta_tags(seo.DEFAULT_URL) in index
    t = _teilen(index)
    assert t["og:image"] == [seo.DEFAULT_URL + "og-image.png"] and t["twitter:image"] == t["og:image"]
    assert t["og:image:type"] == ["image/png"]
    assert t["og:image:width"] == ["1200"] and t["og:image:height"] == ["630"]
    assert t["twitter:card"] == ["summary_large_image"]
    assert t["og:image:alt"] == t["twitter:image:alt"] == [vorschaubild.alt_text()]
    assert "Stadt Köln – offenedaten-koeln.de (dl-de/zero 2.0)" in vorschaubild.alt_text()
    assert t["og:site_name"] == ["Ratsatlas Köln"]
    assert f"<title>{vorschaubild.NAME} – {vorschaubild.UNTERTITEL}</title>" in index   # Untertitel wie im Titel
    assert not [w for werte in t.values() for w in werte if "Bonn" in w or "bonn" in w]


def test_startseite_nach_dem_bau(tmp_path):
    """seo.write setzt SITE_URL in die Adresse des Bildes ein."""
    shutil.copy(SITE / "index.html", tmp_path / "index.html")
    seo.write(tmp_path, URL)
    t = _teilen((tmp_path / "index.html").read_text(encoding="utf-8"))
    assert t["og:image"] == t["twitter:image"] == [URL + "og-image.png"]


def test_angaben_im_kopf_der_unterseiten():
    """Unterseiten (gebietsseiten._page): vollständige Angaben zum Teilen mit dem Kölner Bild, einmal je Seite; bringt
    der Kopf eigene Open-Graph-Angaben mit (Themenseiten), bleibt es bei diesen."""
    html = gebietsseiten._page(URL, "begriffe/", "Begriffe – Ratsatlas Köln", "Erklärungen", "<h1>x</h1>", "../")
    t = _teilen(html)
    assert t["og:url"] == [URL + "begriffe/"] and t["og:title"] == ["Begriffe – Ratsatlas Köln"]
    assert t["og:image"] == [URL + "og-image.png"] and t["og:image:width"] == ["1200"]
    assert t["og:image:alt"] == [vorschaubild.alt_text()] and t["twitter:card"] == ["summary_large_image"]
    assert all(len(w) == 1 for w in t.values())
    eigen = '\n  <meta property="og:image" content="https://example.invalid/bild.png">'
    t2 = _teilen(gebietsseiten._page(URL, "thema/", "T", "B", "<h1>x</h1>", "../", eigen))
    assert t2 == {"og:image": ["https://example.invalid/bild.png"]}


def test_manifest_und_symbole_ohne_bonn():
    """Manifest und Symbole: Kölner Name, Symbole vorhanden (Zeichen „RA“ ohne Ortsnamen, aus Bonn übernommen)."""
    manifest = json.loads((SITE / "site.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "Ratsatlas Köln" and "Bonn" not in json.dumps(manifest, ensure_ascii=False)
    for symbol in manifest["icons"]:
        assert (SITE / symbol["src"]).is_file(), symbol["src"]
    assert "Bonn" not in (SITE / "favicon.svg").read_text(encoding="utf-8")


def test_namensnennung_in_den_lizenzen():
    lizenzen = (ROOT / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8")
    assert "`og-image.png`" in lizenzen and "tools/vorschaubild.py" in lizenzen
    absatz = next(z for z in lizenzen.split("\n\n") if "`og-image.png`" in z)
    assert "Datenquelle: Stadt Köln – offenedaten-koeln.de" in absatz and "keine Daten aus OpenStreetMap" in absatz


def test_rendern_mit_chromium(tmp_path):
    """Mit Node.js und Playwright: tools/vorschaubild.py rendert ein PNG mit 1200 × 630 Pixeln, geladener Schrift und
    den Vermerken (ohne Playwright übersprungen, etwa im Workflow tests.yml)."""
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("Node.js mit Playwright fehlt")
    ziel = tmp_path / "bild.png"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "vorschaubild.py"), str(ziel)], capture_output=True, text=True,
                       timeout=120)
    if r.returncode and "Executable doesn't exist" in r.stderr:
        pytest.skip("Chromium für Playwright fehlt")
    assert r.returncode == 0, r.stderr
    assert "Inter loaded" in r.stdout
    png = ziel.read_bytes()
    assert vorschaubild.groesse(png) == (1200, 630)
    assert vorschaubild.vermerke(png)[vorschaubild.VERMERK_EINGABE] == vorschaubild.pruefsumme()
