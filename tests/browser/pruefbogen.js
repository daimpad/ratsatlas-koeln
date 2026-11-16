// Browserprüfung des Prüfbogens tools/pruefbogen.html (Entscheidung 16.11.2026 (5)); nur lokal, nicht in CI (dort ist
// kein Chromium für Playwright zugesichert). Öffnet die Datei über file://, bricht jede Anfrage ab, die keine Datei ist,
// und zählt sie (erwartet 0); meldet Verstöße gegen die Content-Security-Policy und Fehler in der Konsole. Lädt die
// Stichprobe, beurteilt Zeilen nur mit der Tastatur (r, T, f, u, ←, Entf, n), schreibt eine Anmerkung, wählt eine
// Methode im Filter, speichert über „TSV speichern“ (Enter) und lädt die Seite neu (Zwischenstand aus dem localStorage,
// danach „Zwischenstand löschen“). Danach in einem eigenen Kontext Sonderfälle: Datei nur mit Kopfzeile, Fokus nach
// dem Laden und Tasten im Dateifeld und auf dem Kontrollkästchen, Methoden mit Namen von Objekteigenschaften
// („__proto__“, „constructor“), Sprung mit N zu einer ungültigen Zeile, Felder mit 100 000 Zeichen (Zeit, gekürzte
// Anzeige), Breite 320, 375 und 1400 px ohne seitliches Scrollen; dazu, ob eine andere lokale HTML-Datei den
// Zwischenstand lesen kann (nur gemeldet). axe-core (WCAG 2.1 A/AA) in fünf Zuständen, wenn AXE_PFAD gesetzt ist.
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
  const axe = async (name, p = seite) => {
    if (!AXE) return;
    await p.evaluate(AXE);
    const r = await p.evaluate(async () => await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }));
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

  // Sonderfälle in einem eigenen Kontext (eigener localStorage): nur Kopfzeile, Fokus nach dem Laden, Tasten im
  // Dateifeld und auf dem Kontrollkästchen, Methoden mit Namen von Objekteigenschaften, lange Felder, schmale Ansicht
  const k2 = await browser.newContext({ acceptDownloads: true });
  await k2.route('**/*', (r) => {
    if (r.request().url().startsWith('file:')) return r.continue();
    ergebnis.netz.push(r.request().url());
    return r.abort();
  });
  const s2 = await k2.newPage();
  s2.on('request', (r) => { const u = r.url(); if (!/^(file|blob|data):/.test(u) && !ergebnis.netz.includes(u)) ergebnis.netz.push(u); });
  s2.on('console', (m) => { if (m.type() === 'error') ergebnis.konsole.push(m.text()); });
  s2.on('pageerror', (e) => ergebnis.konsole.push(String(e)));
  await s2.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      (window.__csp = window.__csp || []).push(e.violatedDirective + ' ' + (e.blockedURI || ''));
    });
  });
  const kopf = fs.readFileSync(STICHPROBE, 'utf8').split('\n')[0];
  const spalten = kopf.split('\t');
  const zeile = (felder) => spalten.map((k) => (k in felder ? felder[k] : '')).join('\t');
  const nurKopf = path.join(AUS, 'nur_kopf.tsv');
  fs.writeFileSync(nurKopf, kopf + '\n');
  const urteil = spalten.find((k) => k.startsWith('urteil'));
  const lang = 'x'.repeat(100000);
  const sonder = path.join(AUS, 'sonder.tsv');
  fs.writeFileSync(sonder, [kopf,
    zeile({ methode: '__proto__', drucksache: '1/2099', titel: '[Testdaten] a', link: 'https://example.invalid/vo/1' }),
    zeile({ methode: 'constructor', drucksache: '2/2099', titel: '[Testdaten] b', [urteil]: 'vielleicht' }),
    zeile({ methode: 'toString', drucksache: '3/2099', titel: '[Testdaten] c', [urteil]: 'r' }),
    zeile({ methode: 'strasse', drucksache: '4/2099', titel: '[Testdaten] ' + lang, fundstelle: lang }),
    zeile({ methode: 'm' + 'y'.repeat(300), drucksache: '5/2099', titel: '[Testdaten] e' })].join('\n') + '\n');
  await s2.goto(SEITE);
  // nur Kopfzeile: Datei mit der Tastatur gewählt (Fokus im Dateifeld), dann N, →, r und „TSV speichern“
  await s2.focus('#datei');
  await s2.setInputFiles('#datei', nurKopf);
  await s2.waitForSelector('#bogen:not([hidden])');
  const leer = { geladen: (await s2.textContent('#ladestatus')).trim(), fokus: await s2.evaluate(() => document.activeElement.id) };
  for (const t of ['n', 'ArrowRight', 'ArrowLeft', 'r']) await s2.keyboard.press(t);
  leer.titel = (await s2.textContent('#zeile-titel')).trim();
  leer.status = (await s2.textContent('#status')).trim();
  leer.knoepfe = await s2.$$eval('#urteile button, #offen, #vor, #zurueck', (b) => b.filter((x) => !x.disabled).length);
  const [dl0] = await Promise.all([s2.waitForEvent('download'), s2.click('#speichern')]);
  const leerDatei = path.join(AUS, 'nur_kopf_beurteilt.tsv');
  await dl0.saveAs(leerDatei);
  leer.gespeichert = fs.readFileSync(leerDatei, 'utf8') === kopf + '\n';
  leer.speicherstatus = (await s2.textContent('#speicherstatus')).trim();
  await axe('leer', s2);
  ergebnis.leer = leer;
  // Sonderfälle: Laden über das Dateifeld (Fokus dort), Tasten wirken sofort und auf dem Kontrollkästchen
  const t0 = Date.now();
  await s2.focus('#datei');
  await s2.setInputFiles('#datei', sonder);
  await s2.waitForFunction(() => document.getElementById('ladestatus').textContent.startsWith('sonder.tsv'));
  const so = { laden_ms: Date.now() - t0, fokus: await s2.evaluate(() => document.activeElement.id) };
  so.filter = await s2.$$eval('#filter option', (o) => o.map((x) => x.textContent));
  so.fortschritt = await s2.$$eval('#fortschritt tr', (z) => z.map((r) => Array.from(r.children).slice(0, 4).map((c) => c.textContent)));
  so.erste = (await s2.textContent('#zeile-titel')).trim();
  await s2.focus('#datei');
  await s2.keyboard.press('u');                                 // Zeile 2 unklar, weiter zu Zeile 3
  so.nach_datei = (await s2.textContent('#zeile-titel')).trim();
  await s2.focus('#weiter');
  await s2.keyboard.press('ArrowLeft');                         // zurück zu Zeile 2
  so.nach_kontrollkaestchen = (await s2.textContent('#zeile-titel')).trim();
  await s2.keyboard.press('n');                                 // nächste ohne gültiges Urteil: Zeile 3 (ungültig)
  so.sprung = [(await s2.textContent('#zeile-titel')).trim(), (await s2.textContent('#zeile-urteil')).trim()];
  await s2.focus('#vor');
  const t1 = Date.now();
  await s2.keyboard.press('ArrowRight'); await s2.keyboard.press('ArrowRight');   // Zeile 5: sehr langer Titel
  so.lang_ms = Date.now() - t1;
  so.lang = await s2.$$eval('#zeile dd', (d) => d.map((x) => x.textContent.length));
  so.lang_ende = await s2.evaluate(() => document.querySelector('#felder-vorlage dd').textContent.slice(-40));
  await s2.keyboard.press('ArrowRight');                        // Zeile 6: sehr langer Methodenname
  so.breite = {};
  for (const b of [320, 375, 1400]) {
    await s2.setViewportSize({ width: b, height: 800 });
    so.breite[b] = await s2.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  }
  await s2.selectOption('#filter', '__proto__');
  so.filter_proto = [(await s2.textContent('#zeile-titel')).trim(), await s2.evaluate(() => document.querySelector('#zeile a') && document.querySelector('#zeile a').textContent)];
  await axe('sonder', s2);
  // Zwischenstand unter file:// in einer anderen lokalen HTML-Datei lesbar? (Befund zum Hinweis, nur gemeldet)
  const andere = path.join(AUS, 'andere.html');
  fs.writeFileSync(andere, '<!doctype html><title>x</title><p>x</p>');
  const s3 = await k2.newPage();
  await s3.goto('file://' + andere);
  so.andere_datei_liest = await s3.evaluate(() => { try { return Object.keys(localStorage).filter((k) => k.startsWith('ratsatlas-pruefbogen:')).length; } catch (e) { return 'kein Zugriff'; } });
  so.csp = await s2.evaluate(() => window.__csp || []);
  ergebnis.sonder = so;
  await browser.close();
  console.log(JSON.stringify(ergebnis, null, 1));
})();
