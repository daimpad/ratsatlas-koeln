"""Ausschnitt Köln aus einem Protomaps-Build (PMTiles v3, OSM-Daten, ODbL) über HTTP-Range-Anfragen.

Aufruf: python -I pipeline/kacheln/ausschnitt.py <ausgabe.pmtiles> <stand.json> [build]
build: Dateiname wie 20261101.pmtiles; ohne Angabe der neueste Build laut builds.json.
Es werden nur die Kacheln im Rahmen je Zoomstufe geholt (rund 70 Anfragen, 50 MB), keine Kacheln von
tile.openstreetmap.org. Benachbarte Bereiche werden zusammengefasst (Lücke bis 256 KB).
"""
import gzip
import json
import os
import sys
import urllib.request

from pmtiles.tile import TileType, deserialize_directory, deserialize_header, find_tile, zxy_to_tileid
from pmtiles.writer import Writer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rahmen import VEKTOR_MAXZOOM, kachelbereich, rahmen  # noqa: E402

BUILDS = "https://build-metadata.protomaps.dev/builds.json"
BASIS = "https://build.protomaps.com/"
UA = "ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; Ausschnitt Koeln, vierteljaehrlich)"
REQ = {"n": 0, "bytes": 0}


def neuester_build():
    req = urllib.request.Request(BUILDS, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        builds = json.load(r)
    keys = sorted(b["key"] for b in builds if b.get("key", "").endswith(".pmtiles"))
    return keys[-1]


def main(out, stand_pfad, build=None):
    build = build or neuester_build()
    url = BASIS + build

    def get(offset, length):
        req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset + length - 1}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        REQ["n"] += 1
        REQ["bytes"] += len(data)
        if len(data) != length:
            raise RuntimeError(f"Antwort unvollständig: {len(data)} statt {length} Bytes")
        return data

    h = deserialize_header(get(0, 127))
    meta = json.loads(gzip.decompress(get(h["metadata_offset"], h["metadata_length"])))
    root = deserialize_directory(get(h["root_offset"], h["root_length"]))
    blaetter = {}

    def suche(tid):
        entries = root
        for _ in range(4):
            e = find_tile(entries, tid)
            if e is None:
                return None
            if e.run_length > 0:
                return e
            key = (e.offset, e.length)
            if key not in blaetter:
                blaetter[key] = deserialize_directory(get(h["leaf_directory_offset"] + e.offset, e.length))
            entries = blaetter[key]
        return None

    gesucht = []  # (tid, z, offset, length)
    for z in range(0, VEKTOR_MAXZOOM + 1):
        x1, y1, x2, y2 = kachelbereich(z)
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                tid = zxy_to_tileid(z, x, y)
                e = suche(tid)
                if e is not None:
                    gesucht.append((tid, z, e.offset, e.length))

    bereiche = sorted({(o, ln) for _, _, o, ln in gesucht})
    daten = {}
    i = 0
    while i < len(bereiche):
        start, ln = bereiche[i]
        ende = start + ln
        j = i + 1
        while j < len(bereiche) and bereiche[j][0] - ende <= 256 * 1024 and bereiche[j][0] + bereiche[j][1] - start <= 16 * 2**20:
            ende = max(ende, bereiche[j][0] + bereiche[j][1])
            j += 1
        block = get(h["tile_data_offset"] + start, ende - start)
        for o, ll in bereiche[i:j]:
            daten[(o, ll)] = block[o - start:o - start + ll]
        i = j

    with open(out, "wb") as f:
        w = Writer(f)
        for tid, _z, o, ln in sorted(gesucht):
            w.write_tile(tid, daten[(o, ln)])
        lo1, la1, lo2, la2 = rahmen(0)  # größter Rahmen, sonst fragt MapLibre Kacheln außerhalb nicht ab
        w.finalize({
            "tile_type": TileType.MVT, "tile_compression": h["tile_compression"],
            "min_lon_e7": int(lo1 * 1e7), "min_lat_e7": int(la1 * 1e7), "max_lon_e7": int(lo2 * 1e7), "max_lat_e7": int(la2 * 1e7),
            "center_zoom": 11, "center_lon_e7": int(7.1166 * 1e7), "center_lat_e7": int(50.7036 * 1e7),
        }, meta)

    stand = {
        "build": build,
        "quelle": url,
        "osm_stand": meta.get("planetiler:osm:osmosisreplicationtime", ""),
        "basemap_version": meta.get("version", ""),
        "vektorkacheln": len(gesucht),
    }
    with open(stand_pfad, "w", encoding="utf-8") as f:
        json.dump(stand, f, ensure_ascii=False, indent=1)
    print(f"Build {build}: {len(gesucht)} Vektorkacheln, {REQ['n']} Anfragen, {REQ['bytes'] / 2**20:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
