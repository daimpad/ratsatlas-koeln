"""Seite zusammenstellen wie der künftige Veröffentlichungslauf (Phase 5): site/ + data/export + Geodaten → _site/.

Aufruf: python3 tools/seite_bauen.py [ziel]   (Vorgabe: _site; nicht versioniert)
Danach z. B.: python3 -m http.server -d _site 8000
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import config, seo  # noqa: E402

# Karte im Menü „Daten“ (index.html): Link mit `download` auf eine Datei unter data/export/, Kartentext bis zum Ende
KARTE_DOWNLOAD = re.compile(r'(?P<kopf><a class="card" href="(?P<href>data/export/[^"]+)" download>(?:(?!</a>).)*?'
                            r'<span class="card-text">)(?P<text>[^<]*?)(?P<punkt>\.?)</span></a>', re.S)


def groesse_text(n):
    """Dateigröße in Bytes als kurzer deutscher Text (1 MB = 1 000 000 Bytes): „74 MB“, „2,5 MB“, „830 kB“; zwischen
    Zahl und Einheit ein geschütztes Leerzeichen (kein Umbruch in der Karte)."""
    if n >= 9_950_000:
        return f"{round(n / 1_000_000)} MB"
    if n >= 999_500:
        return f"{n / 1_000_000:.1f} MB".replace(".", ",")
    return f"{max(1, round(n / 1000)) if n else 0} kB"


def groessen_eintragen(ziel):
    """Menü „Daten“: Karten zum Herunterladen nennen die Größe der Datei im fertigen Ordner `ziel` im Kartentext
    („Alle Exporte, Audit-Protokolle und Lizenzen (74 MB).“). Fehlt die Datei, bleibt der Text ohne Angabe. Die Adresse
    (href) bleibt unverändert: pages.yml schreibt den Link auf das Datenpaket für den Branch deploy auf den Spiegel um
    (GitHub Pages, gleiche Datei aus demselben Lauf)."""
    seite = Path(ziel) / "index.html"
    html = seite.read_text(encoding="utf-8")

    def eintragen(m):
        datei = Path(ziel) / m["href"]
        if not datei.is_file():
            return m[0]
        return f'{m["kopf"]}{m["text"]} ({groesse_text(datei.stat().st_size)}){m["punkt"]}</span></a>'

    neu = KARTE_DOWNLOAD.sub(eintragen, html)
    if neu != html:
        seite.write_text(neu, encoding="utf-8")


def main(ziel=ROOT / "_site"):
    ziel = Path(ziel)
    shutil.rmtree(ziel, ignore_errors=True)
    shutil.copytree(ROOT / "site", ziel)
    (ziel / "og-image.jpg").unlink(missing_ok=True)       # Bonner Vorschaubild nicht ausliefern (zweiter Lauf)
    shutil.copytree(config.EXPORT, ziel / "data" / "export")
    shutil.copy(ROOT / "data" / "LICENSE-DATA.md", ziel / "data" / "LICENSE-DATA.md")
    (ziel / "data" / "geo").mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "data" / "geo").glob("*.geojson"):
        shutil.copy(f, ziel / "data" / "geo" / f.name)
    kacheln = ROOT / "_kacheln" / "kacheln"
    if (kacheln / "stand.json").exists():
        shutil.copytree(kacheln, ziel / "kacheln")
    seo.write(ziel)
    groessen_eintragen(ziel)
    print(f"Seite → {ziel}")


if __name__ == "__main__":
    main(*sys.argv[1:])
