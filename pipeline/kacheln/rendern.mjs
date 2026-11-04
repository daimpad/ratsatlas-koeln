// Zeichnet die grauen Kacheln in Blöcken von 8 × 8 Kacheln (mit einer Kachel Rand gegen abgeschnittene Beschriftung)
// mit MapLibre in Chromium. Stil: Protomaps „light“, Beschriftung deutsch; das Grau entsteht in zerlegen.py.
// Aufruf: node pipeline/kacheln/rendern.mjs <bonn.pmtiles> <plan.json> <blockordner>
// plan.json: Kachelbereich je Zoomstufe aus rahmen.py. Schrift und Symbole lädt MapLibre beim Zeichnen von
// protomaps.github.io (basemaps-assets); die Seite selbst lädt davon nichts.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { layers, namedFlavor } from '@protomaps/basemaps';

const HIER = path.dirname(fileURLToPath(import.meta.url));
const [PMTILES, PLAN, AUS] = process.argv.slice(2);
if (!AUS) { console.error('Aufruf: node rendern.mjs <bonn.pmtiles> <plan.json> <blockordner>'); process.exit(2); }
const B = 8, M = 1, V = (B + 2 * M) * 256;
const FLAVOR = 'light';

const stil = (base) => JSON.stringify({
  version: 8,
  glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
  sprite: `https://protomaps.github.io/basemaps-assets/sprites/v4/${FLAVOR}`,
  sources: { protomaps: { type: 'vector', url: `pmtiles://${base}/bonn.pmtiles` } },
  layers: layers('protomaps', namedFlavor(FLAVOR), { lang: 'de' }),
});

// Kleiner Server mit HTTP-Range (PMTiles) für render.html, node_modules und den Ausschnitt
const TYPEN = { '.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
function server() {
  return new Promise((resolve) => {
    const s = http.createServer((req, res) => {
      const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
      if (p === '/stil.json') { res.writeHead(200, { 'content-type': 'application/json' }); return res.end(stil(`http://127.0.0.1:${s.address().port}`)); }
      const f = p === '/bonn.pmtiles' ? path.resolve(PMTILES) : path.join(HIER, p);
      if (p !== '/bonn.pmtiles' && !f.startsWith(HIER + path.sep)) { res.writeHead(403); return res.end(); }
      let st; try { st = fs.statSync(f); } catch { res.writeHead(404); return res.end(); }
      const h = { 'content-type': TYPEN[path.extname(f)] || 'application/octet-stream', 'accept-ranges': 'bytes' };
      const r = req.headers.range && /^bytes=(\d+)-(\d*)$/.exec(req.headers.range);
      if (r) {
        const a = Number(r[1]), e = r[2] ? Math.min(Number(r[2]), st.size - 1) : st.size - 1;
        res.writeHead(206, { ...h, 'content-range': `bytes ${a}-${e}/${st.size}`, 'content-length': e - a + 1 });
        return fs.createReadStream(f, { start: a, end: e }).pipe(res);
      }
      res.writeHead(200, { ...h, 'content-length': st.size });
      fs.createReadStream(f).pipe(res);
    });
    s.listen(0, '127.0.0.1', () => resolve(s));
  });
}

const plan = JSON.parse(fs.readFileSync(PLAN, 'utf8'));
fs.mkdirSync(AUS, { recursive: true });
const s = await server();
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await (await browser.newContext({ viewport: { width: V, height: V }, deviceScaleFactor: 1 })).newPage();
let fehler = 0;
page.on('pageerror', (e) => { fehler++; console.error('Seitenfehler', String(e)); });
await page.goto(`http://127.0.0.1:${s.address().port}/render.html`, { waitUntil: 'load' });
await page.evaluate(() => window.__bereit);
const t0 = Date.now(); const liste = [];
for (const [zs, [x1, y1, x2, y2]] of Object.entries(plan)) {
  const z = Number(zs);
  for (let bx = x1; bx <= x2; bx += B) for (let by = y1; by <= y2; by += B) {
    const cx = (bx - M) * 256 + V / 2, cy = (by - M) * 256 + V / 2;
    await page.evaluate(([z, cx, cy]) => window.zeichne(z, cx, cy), [z, cx, cy]);
    await page.waitForTimeout(50);
    await page.screenshot({ path: path.join(AUS, `${z}_${bx}_${by}.png`), clip: { x: 0, y: 0, width: V, height: V }, timeout: 180000 });
    liste.push([z, bx, by, Math.min(bx + B - 1, x2), Math.min(by + B - 1, y2)].join('\t'));
  }
  console.error(`Zoom ${z}: ${(x2 - x1 + 1) * (y2 - y1 + 1)} Kacheln, ${liste.length} Blöcke bisher, ${((Date.now() - t0) / 1000).toFixed(0)} s`);
}
fs.writeFileSync(path.join(AUS, 'bloecke.tsv'), liste.join('\n') + '\n');
await browser.close();
s.close();
if (fehler) { console.error(`${fehler} Seitenfehler beim Zeichnen`); process.exit(1); }
console.log(`${liste.length} Blöcke in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
