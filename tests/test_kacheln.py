"""Rahmen der grauen Kacheln: site/app.js (KACHEL_RAHMEN) und pipeline/kacheln/rahmen.py stimmen überein und decken
das Kölner Stadtgebiet ab."""
import json
import re
import sys
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "kacheln"))
import rahmen  # noqa: E402


def test_rahmen_gleich_in_seite_und_pipeline():
    js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"const KACHEL_RAHMEN = (\{[^\n]*\});", js)
    seite = json.loads(re.sub(r"(\d+):", r'"\1":', m.group(1)))
    assert {int(k): v for k, v in seite.items()} == {z: list(rahmen.kachelbereich(z)) for z in range(rahmen.ZMIN, rahmen.ZMAX + 1)}


def test_rahmen_umfasst_stadtgebiet():
    feats = json.loads((ROOT / "data" / "geo" / "stadtbezirke_koeln.geojson").read_text())["features"]
    lo1, la1, lo2, la2 = unary_union([shape(f["geometry"]) for f in feats]).bounds
    s = rahmen.STADT
    assert s[0] <= lo1 + 1e-3 and s[1] <= la1 + 1e-3 and s[2] >= lo2 - 1e-3 and s[3] >= la2 - 1e-3
