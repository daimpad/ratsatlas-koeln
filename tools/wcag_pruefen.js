// WCAG-2.1-AA-Prüfung (Phase 4): axe-core auf den wichtigsten Zuständen und Seiten, dazu Tab-Reihenfolge der Startseite.
// Aufruf (Seite lokal unter http://127.0.0.1:8765/, axe-core 4.10.2 in einem eigenen Ordner mit node_modules):
//   node tools/wcag_pruefen.js <ergebnis.tsv> <tastatur.txt>   (AXE_PFAD=<…/axe.min.js>)
const { chromium } = require('playwright');
const fs = require('fs');
const AXE = fs.readFileSync(process.env.AXE_PFAD || __dirname + '/node_modules/axe-core/axe.min.js', 'utf8');
const B = 'http://127.0.0.1:8765/';
const run = async (p, name, rows) => {
  await p.addScriptTag({ content: AXE });
  const r = await p.evaluate(async () => await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }));
  for (const v of r.violations) rows.push([name, v.id, v.impact, v.nodes.length, v.help, v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | ')]);
  return r.violations.length;
};
(async () => {
  const b = await chromium.launch();
  const rows = [];
  const p = await b.newPage({ viewport: { width: 1400, height: 900 }, bypassCSP: true });
  await p.goto(B, { waitUntil: 'networkidle' }); await p.waitForTimeout(800); await run(p, 'start', rows);
  await p.goto(B + '?gebiet=ortsteil:ehrenfeld', { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
  await p.click('.toggle[data-panel="panel-list"]'); await p.waitForTimeout(300);
  await p.click('#papers li button'); await p.waitForTimeout(800); await run(p, 'vorgang', rows);
  await p.click('.toggle[data-panel="timeline-wrap"]'); await p.waitForTimeout(500); await run(p, 'zeitleiste', rows);
  await p.click('#about-open'); await p.waitForTimeout(300); await run(p, 'ueber', rows); await p.keyboard.press('Escape');
  await p.click('[data-mega="mega-mitmachen"]'); await p.waitForTimeout(300); await run(p, 'mitmachen', rows);
  for (const s of ['gebiete/', 'begriffe/', 'rss/', 'datenschutz.html', 'ortsteil/ehrenfeld/', '404.html']) {
    const r = await p.goto(B + s, { waitUntil: 'networkidle' }); if (r && r.status() < 400) await run(p, s, rows); else rows.push([s, 'nicht gefunden', '', '', '', '']);
  }
  // Tastatur: Tab-Reihenfolge der ersten 25 Fokusziele auf der Startseite, sichtbarer Fokus
  await p.goto(B, { waitUntil: 'networkidle' });
  const tabs = [];
  for (let i = 0; i < 25; i++) {
    await p.keyboard.press('Tab');
    tabs.push(await p.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e);
      return `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''} „${(e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 30)}“ outline=${cs.outlineStyle !== 'none' || cs.boxShadow !== 'none'}`; }));
  }
  fs.writeFileSync(process.argv[2], ['seite\tregel\tgewicht\tanzahl\thilfe\tbeispiele', ...rows.map(r => r.join('\t'))].join('\n') + '\n');
  fs.writeFileSync(process.argv[3], tabs.join('\n') + '\n');
  console.log(rows.length + ' Befunde'); rows.forEach(r => console.log(r.slice(0, 5).join(' | ')));
  await b.close();
})();
