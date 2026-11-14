"""Vorschaubild der Seite (site/og-image.png, 1200 × 630) aus den Gebietsflächen in data/geo erzeugen.

Aufruf: python3 tools/vorschaubild.py [ziel.png]   (Vorgabe: site/og-image.png)
Braucht Node.js mit Playwright und Chromium (wie tests/browser/bedienung.js; NODE_PATH und PLAYWRIGHT_BROWSERS_PATH wie
dort). Die Seite des Bildes entsteht in pipeline/vorschaubild.html() ohne Netzanfragen; Chromium rendert sie mit
1200 × 630 Pixeln und deviceScaleFactor 1. Anfragen an andere Adressen als file: und data: bricht das Skript ab, ebenso
eine nicht geladene Schrift. Gleiche Eingaben und dieselbe Chromium-Fassung ergeben dasselbe Bild; eine andere Fassung
kann Kanten minimal anders glätten. Neu erzeugen, wenn sich Gebietsflächen, Gestaltungsmerkmale, Schrift, Zeichen, Name
oder Untertitel ändern (tests/test_vorschaubild.py vergleicht die im PNG vermerkte Prüfsumme der Eingaben); danach das
Bild ansehen (Playwright oder Bildbetrachter) und mit committen.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import vorschaubild  # noqa: E402

NODE = r"""
const { chromium } = require("playwright");
const [seite, ziel, breite, hoehe] = process.argv.slice(1);
(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });
  try {
    const page = await browser.newPage({ viewport: { width: +breite, height: +hoehe }, deviceScaleFactor: 1 });
    const fremd = [];
    await page.route((u) => !/^(file|data):/.test(u.href), (r) => { fremd.push(r.request().url()); r.abort(); });
    await page.goto("file://" + seite, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    const schrift = await page.evaluate(() => [...document.fonts].map((f) => `${f.family} ${f.status}`));
    if (!schrift.length || schrift.some((s) => !s.endsWith("loaded"))) throw new Error("Schrift nicht geladen: " + schrift);
    if (fremd.length) throw new Error("Anfragen an andere Adressen: " + fremd.join(", "));
    await page.screenshot({ path: ziel, type: "png", clip: { x: 0, y: 0, width: +breite, height: +hoehe } });
    console.log(`Vorschaubild → ${ziel} (${schrift.join(", ")})`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
"""


def main(ziel=ROOT / "site" / vorschaubild.DATEI):
    ziel = Path(ziel).resolve()
    with tempfile.TemporaryDirectory() as ordner:
        seite = Path(ordner) / "vorschaubild.html"
        seite.write_text(vorschaubild.html(), encoding="utf-8")
        subprocess.run(["node", "-e", NODE, str(seite), str(ziel), str(vorschaubild.BREITE), str(vorschaubild.HOEHE)],
                       check=True)
    png = ziel.read_bytes()
    if vorschaubild.groesse(png) != (vorschaubild.BREITE, vorschaubild.HOEHE):
        raise SystemExit(f"Vorschaubild hat {vorschaubild.groesse(png)} Pixel statt {vorschaubild.BREITE} × "
                         f"{vorschaubild.HOEHE}")
    ziel.write_bytes(vorschaubild.mit_vermerken(png))   # Prüfsumme der Eingaben und Namensnennung im PNG


if __name__ == "__main__":
    main(*sys.argv[1:])
