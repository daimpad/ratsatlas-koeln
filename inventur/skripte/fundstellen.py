"""Fundstellen Bonner Bezüge im übernommenen Code (Phase 0, Inventur).

Aufruf aus dem Repository-Wurzelverzeichnis: python3 inventur/skripte/fundstellen.py > inventur/fundstellen_bonn.tsv
Durchsucht alle Textdateien außer inventur/ und .git/. Eine Zeile kann mehrere Kategorien tragen.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 51 Ortsteile und 4 Stadtbezirke Bonns (Namen laut ortsteile_bonn.geojson in allris-test @9eea7ea)
ORTSTEILE = ("Alt-Godesberg|Auerberg|Beuel-Mitte|Beuel-Ost|Bonn-Castell|Bonn-Zentrum|Brüser Berg|Buschdorf|Dottendorf|"
             "Dransdorf|Duisdorf|Endenich|Friesdorf|Geislar|Godesberg-Nord|Godesberg-Villenviertel|Graurheindorf|Gronau|"
             "Hardthöhe|Heiderhof|Hochkreuz|Hoholz|Holtorf|Holzlar|Ippendorf|Kessenich|Küdinghoven|Lannesdorf|Lengsdorf|"
             "Lessenich|Meßdorf|Limperich|Mehlem|Muffendorf|Nordstadt|Oberkassel|Pennenfeld|Plittersdorf|Poppelsdorf|"
             "Pützchen|Bechlinghoven|Ramersdorf|Röttgen|Rüngsdorf|Schwarzrheindorf|Vilich-Rheindorf|Schweinheim|Südstadt|"
             "Tannenbusch|Venusberg|Vilich|Müldorf|Weststadt|Ückesdorf").split("|")
BEZIRKE = ["Bad Godesberg", "Beuel", "Hardtberg"]

MUSTER = [
    ("url_bonn", re.compile(r"https?://[^\s\"')>]*bonn[^\s\"')>]*", re.I)),
    ("url_allris_test", re.compile(r"(daimpad\.github\.io/allris-test|github\.com/daimpad/allris-test|ris-bonn\.datenatlas\.de|bonn\.ratsatlas\.de)", re.I)),
    ("site_url", re.compile(r"\b(SITE_URL|PAKET_URL)\b")),
    ("oparl_lite", re.compile(r"(machdenstaat|OParl-Lite|oparl_lite|LITE_GRAPHQL|consultations_lite|fetch-lite)", re.I)),
    ("name_allris_bonn", re.compile(r"allris-bonn", re.I)),
    ("ortsteil_bonn", re.compile(r"\b(" + "|".join(re.escape(o) for o in ORTSTEILE) + r")\b")),
    ("bezirk_bonn", re.compile(r"\b(" + "|".join(re.escape(b) for b in BEZIRKE) + r")\b")),
    ("bonn", re.compile(r"\bBonn(er|s)?\b|_bonn\b|/bonn/|\bbonn\b", re.I)),
]


def _dateien():
    """Versionierte und neue, nicht ignorierte Dateien (ohne Caches und lokale Rohdaten)."""
    import subprocess
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [ROOT / n for n in sorted(set(out)) if n and (ROOT / n).exists()]


def main():
    out = sys.stdout
    out.write("datei\tzeile\tkategorie\ttreffer\tauszug\n")
    for p in _dateien():
        rel = p.relative_to(ROOT).as_posix()
        if not p.is_file() or rel.startswith((".git/", "inventur/", "explore/")):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for nr, zeile in enumerate(text.splitlines(), 1):
            for kat, rx in MUSTER:
                treffer = sorted({m.group(0) for m in rx.finditer(zeile)})
                if treffer:
                    auszug = zeile.strip().replace("\t", " ")[:160]
                    out.write(f"{rel}\t{nr}\t{kat}\t{' | '.join(treffer)}\t{auszug}\n")


if __name__ == "__main__":
    main()
