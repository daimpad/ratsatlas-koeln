// Browserprüfung des Prüfbogens tools/pruefbogen.html (Entscheidung 16.11.2026 (5)); nur lokal, nicht in CI (dort ist
// kein Chromium für Playwright zugesichert). Öffnet die Datei über file://, bricht jede Anfrage ab, die keine Datei ist,
// und zählt sie (erwartet 0); meldet Verstöße gegen die Content-Security-Policy und Fehler in der Konsole. Lädt die
// Stichprobe, beurteilt Zeilen nur mit der Tastatur (r, T, f, u, ←, Entf, n), schreibt eine Anmerkung, wählt eine
// Methode im Filter, speichert über „TSV speichern“ (Enter) und lädt die Seite neu (Zwischenstand aus dem localStorage,
// danach „Zwischenstand löschen“). axe-core (WCAG 2.1 A/AA) in drei Zuständen, wenn AXE_PFAD gesetzt ist.
// Aufruf: [NODE_PATH=<…/node_modules mit playwright>] [AXE_PFAD=<…/axe.min.js>] node tests/browser/pruefbogen.js
//   <stichprobe.tsv> <ausgabeordner>
// Ausgabe: JSON auf stdout (Zähler, Befunde, Pfad der gespeicherten Datei); den Vergleich der gespeicherten Datei
// macht tests/test_praezision.py (test_pruefbogen_im_browser, nur mit RATSATLAS_BROWSER=1).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const STICHPROBE = path.resolve(process.argv[2]);
const AUS = path.resolve(process.argv[3]);
const SEITE = 'file://' + path.resolve(__dirname, '..', '..', 'tools', 'pruefbogen.html');
const AXE = process.env.AXE_PFAD ? fs.readFileSync(process.env.AXE_PFAD, 'utf8') : null;

(async () => {
  const ergebnis = { netz: [], csp: [], konsole: [], axe: {}, schritte: [] };
  const browser = await chromium.launch();
  const kontext = await browser.newContext({ acceptDownloads: true });
  await kontext.route('**/*', (r) => {
    if (r.request().url().startsWith('file:')) return r.continue();
    ergebnis.netz.push(r.request().url());
    return r.abort();
  });
  const seite = await kontext.newPage();
  seite.on('request', (r) => { const u = r.url(); if (!/^(file|blob|data):/.test(u) && !ergebnis.netz.includes(u)) ergebnis.netz.push(u); });
  seite.on('console', (m) => { if (m.type() === 'error') ergebnis.konsole.push(m.text()); });
  seite.on('pageerror', (e) => ergebnis.konsole.push(String(e)));
  await seite.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      (window.__csp = window.__csp || []).push(e.violatedDirective + ' ' + (e.blockedURI || ''));
    });
  });
  const axe = async (name) => {
    if (!AXE) return;
    await seite.evaluate(AXE);
    const r = await seite.evaluate(async () => await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }));
    ergebnis.axe[name] = r.violations.map((v) => `${v.id} (${v.nodes.length})`);
  };
  const status = async () => (await seite.textContent('#status')).trim();
  const schritt = async (taste) => { await seite.keyboard.press(taste); ergebnis.schritte.push([taste, await status()]); };

  await seite.goto(SEITE);
  await axe('start');
  await seite.setInputFiles('#datei', STICHPROBE);
  await seite.waitForSelector('#bogen:not([hidden])');
  ergebnis.geladen = (await seite.textContent('#ladestatus')).trim();
  ergebnis.links = await seite.evaluate(() => Array.from(document.querySelectorAll('#zeile a')).map((a) => [a.protocol, a.target, a.rel]));
  ergebnis.titel_erste = (await seite.textContent('#felder-vorlage dd')).trim();
  await seite.focus('#vor');
  await seite.evaluate(() => document.activeElement.blur());
  for (const t of ['r', 'Shift+T', 'f', 'u', 'ArrowLeft', 'Delete']) await schritt(t);
  // vierte Zeile: Link ohne https erscheint nicht als Link
  ergebnis.zeile_ohne_link = await seite.evaluate(() => document.querySelectorAll('#zeile a').length);
  // Titel „<img …>“ als Text, kein Element
  ergebnis.img = await seite.evaluate(() => [document.querySelectorAll('img, iframe, object, embed').length,
    Array.from(document.querySelectorAll('#felder-vorlage dd')).some((d) => d.textContent.startsWith('<img'))]);
  ergebnis.gedrueckt = await seite.evaluate(() => Array.from(document.querySelectorAll('#urteile [aria-pressed="true"]')).map((b) => b.dataset.urteil));
  await seite.fill('#anmerkung', 'Bezirk richtig, „Stadtteil“ "falsch"\tTab\nzweite Zeile');
  await seite.focus('#vor');
  ergebnis.fokus_sichtbar = await seite.evaluate(() => { const s = getComputedStyle(document.activeElement); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2; });
  for (const t of ['n', 'r']) await schritt(t);
  await seite.click('#regeln summary');
  await axe('bogen');
  // Filter: zweite Methode
  const optionen = await seite.$$eval('#filter option', (o) => o.map((x) => x.value));
  await seite.selectOption('#filter', optionen[2]);
  ergebnis.filter = [optionen[2], (await seite.textContent('#zeile-titel')).trim()];
  await seite.focus('#zurueck');
  await seite.evaluate(() => document.activeElement.blur());
  await schritt('r');
  ergebnis.fortschritt = await seite.$$eval('#fortschritt tr', (z) => z.map((r) => Array.from(r.children).slice(0, 4).map((c) => c.textContent)));
  await seite.focus('#speichern');
  const [download] = await Promise.all([seite.waitForEvent('download'), seite.keyboard.press('Enter')]);
  ergebnis.dateiname = download.suggestedFilename();
  ergebnis.datei = path.join(AUS, ergebnis.dateiname);
  await download.saveAs(ergebnis.datei);
  ergebnis.speicherstatus = (await seite.textContent('#speicherstatus')).trim();
  ergebnis.csp = await seite.evaluate(() => window.__csp || []);
  // neu laden: Zwischenstand aus dem localStorage, dann löschen
  await seite.reload();
  await seite.setInputFiles('#datei', STICHPROBE);
  await seite.waitForSelector('#bogen:not([hidden])');
  ergebnis.wieder = (await seite.textContent('#ladestatus')).trim();
  await axe('wieder');
  seite.once('dialog', (d) => d.accept());
  await seite.click('#loeschen');
  ergebnis.geloescht = (await seite.textContent('#speicherstatus')).trim();
  ergebnis.nach_loeschen = await seite.$$eval('#fortschritt tr', (z) => z.map((r) => r.children[1].textContent));
  // Ziehen und Ablegen: dieselbe Datei als File in einem DataTransfer
  const inhalt = fs.readFileSync(STICHPROBE, 'utf8');
  await seite.evaluate((text) => {
    const dt = new DataTransfer();
    dt.items.add(new File([text], 'gezogen.tsv', { type: 'text/tab-separated-values' }));
    document.getElementById('ablage').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, inhalt);
  await seite.waitForFunction(() => document.getElementById('ladestatus').textContent.startsWith('gezogen.tsv'));
  ergebnis.gezogen = (await seite.textContent('#ladestatus')).trim();
  ergebnis.csp = ergebnis.csp.concat(await seite.evaluate(() => window.__csp || []));
  await browser.close();
  console.log(JSON.stringify(ergebnis, null, 1));
})();
