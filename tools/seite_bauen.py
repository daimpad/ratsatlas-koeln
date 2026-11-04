"""Seite zusammenstellen wie der künftige Veröffentlichungslauf (Phase 5): site/ + data/export + Geodaten → _site/.

Aufruf: python3 tools/seite_bauen.py [ziel]   (Vorgabe: _site; nicht versioniert)
Danach z. B.: python3 -m http.server -d _site 8000
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import config, seo  # noqa: E402


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
    print(f"Seite → {ziel}")


if __name__ == "__main__":
    main(*sys.argv[1:])
