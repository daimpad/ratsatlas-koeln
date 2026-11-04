"""Zerlegt die gezeichneten Blöcke in Kacheln z/x/y.png in 16 Graustufen (4-Bit-PNG) und legt Lizenz und Stand dazu.

Aufruf: python -I pipeline/kacheln/zerlegen.py <blockordner> <kachelordner> <stand.json>
Das Grau folgt der bisherigen grauen Ansicht der Seite (CSS grayscale(1) contrast(.9) brightness(1.08) auf den
OSM-Kacheln), damit Punkte und Flächen wie bisher hervortreten.
"""
import io
import json
import os
import sys

from PIL import Image

PAL = []
for i in range(16):
    PAL += [i * 17] * 3


def grauwert(v):
    """Leuchtdichte 0–255 → Stufe 0–15 wie CSS contrast(.9) brightness(1.08)."""
    w = ((v / 255 - 0.5) * 0.9 + 0.5) * 1.08
    w = min(max(w, 0.0), 1.0) * 255
    return int((w + 8.5) // 17)


TABELLE = [grauwert(v) for v in range(256)]


def grau16(im):
    # Leuchtdichte nach CSS grayscale(1) (Rec. 709)
    lum = im.convert("RGB").convert("L", (0.2126, 0.7152, 0.0722, 0))
    p = Image.frombytes("P", lum.size, lum.point(TABELLE).tobytes())
    p.putpalette(PAL)
    return p


def png(p):
    b = io.BytesIO()
    p.save(b, "PNG", optimize=True, bits=4)
    return b.getvalue()


LIZENZ = """# Kartenkacheln der grauen Ansicht

Graue Rasterkacheln des Ratsatlas Köln, erzeugt aus OpenStreetMap-Daten über einen Ausschnitt aus dem
Protomaps-Build {build} (OSM-Stand {osm_stand}).

- Daten: © OpenStreetMap-Mitwirkende, Open Database License (ODbL) 1.0 – https://www.openstreetmap.org/copyright
- Vektorkacheln: Protomaps (https://protomaps.com); darin außerdem Küsten- und Wasserflächen von
  osmdata.openstreetmap.de (ODbL) und Natural Earth (gemeinfrei)
- Gestaltung: „light“ aus @protomaps/basemaps (Code BSD-3-Clause, Gestaltung CC0), hier in Graustufen
  umgewandelt; es handelt sich um eine veränderte Fassung, nicht um die Karte von Protomaps
- Schrift der Beschriftung: Noto Sans, SIL Open Font License 1.1

Die Kacheln sind ein abgeleitetes Werk (Produced Work) im Sinne der ODbL. Erzeugt mit dem Workflow kacheln.yml
im Repository daimpad/allris-test (Code MIT).
"""


def main(quelle, ziel, stand_pfad):
    stat = {}
    einfarbig = 0
    with open(os.path.join(quelle, "bloecke.tsv"), encoding="utf-8") as f:
        zeilen = f.read().split("\n")
    for zeile in filter(None, zeilen):
        z, bx, by, ex, ey = map(int, zeile.split())
        im = Image.open(os.path.join(quelle, f"{z}_{bx}_{by}.png")).convert("RGB")
        for x in range(bx, ex + 1):
            for y in range(by, ey + 1):
                ox, oy = (x - bx + 1) * 256, (y - by + 1) * 256
                k = grau16(im.crop((ox, oy, ox + 256, oy + 256)))
                if len(k.getcolors(16) or []) == 1:
                    einfarbig += 1
                daten = png(k)
                os.makedirs(os.path.join(ziel, str(z), str(x)), exist_ok=True)
                with open(os.path.join(ziel, str(z), str(x), f"{y}.png"), "wb") as f:
                    f.write(daten)
                s = stat.setdefault(z, [0, 0])
                s[0] += 1
                s[1] += len(daten)
    anzahl = sum(s[0] for s in stat.values())
    # Ein Zeichenfehler (leere Karte) zeigt sich als viele einfarbige Kacheln; Wasser und Wald allein bleiben darunter
    if not anzahl or einfarbig > anzahl * 0.25:
        sys.exit(f"Abbruch: {einfarbig} von {anzahl} Kacheln einfarbig")
    with open(stand_pfad, encoding="utf-8") as f:
        stand = json.load(f)
    stand["rasterkacheln"] = {str(z): s[0] for z, s in sorted(stat.items())}
    stand["bytes"] = sum(s[1] for s in stat.values())
    with open(os.path.join(ziel, "stand.json"), "w", encoding="utf-8") as f:
        json.dump(stand, f, ensure_ascii=False, indent=1)
    with open(os.path.join(ziel, "LIZENZ.md"), "w", encoding="utf-8") as f:
        f.write(LIZENZ.format(build=stand.get("build", "?"), osm_stand=stand.get("osm_stand", "?") or "?"))
    print("Zoom\tKacheln\tKB")
    for z, (n, b) in sorted(stat.items()):
        print(f"{z}\t{n}\t{b / 1024:.0f}")
    print(f"Summe\t{anzahl}\t{stand['bytes'] / 1024:.0f}\t(einfarbig {einfarbig})")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
