// WCAG-2.1-AA-Prüfung (Phase 4): axe-core auf den wichtigsten Zuständen und Seiten, dazu Tab-Reihenfolge der Startseite.
// Aufruf (Seite lokal unter http://127.0.0.1:<PORT>/, axe-core 4.10.2 und Playwright z. B. aus tests/browser nach
// `npm ci`; ohne AXE_PFAD sucht die Prüfung axe-core in tools/node_modules):
//   [PORT=8765] [BREITE=1400] [HOEHE=900] NODE_PATH=<…/node_modules mit playwright> AXE_PFAD=<…/axe.min.js> \
//     node tools/wcag_pruefen.js <ergebnis.tsv> <tastatur.txt>
// Vorgaben ohne Umgebungsvariable: Port 8765, 1400 × 900. Bis 900 px Breite (Telefon, wie MOBILE in site/app.js)
// öffnet die Prüfung vor Zielen in der Leiste das Menü ☰ (#nav-burger); unter 400 px Höhe blendet sie nur den Hinweis
// „Testdaten“ aus (#testdaten-hinweis, nie veröffentlicht), der sonst über der Liste liegt. Im Job „browser“ von
// .github/workflows/tests.yml läuft sie in 1440 × 900, 1024 × 768, 390 × 844 und 320 × 256.
// Exit-Code 1 bei einem Befund: Verstoß laut axe, Seite nicht gefunden, Fläche trotz Freigabe nicht geöffnet, in der
// Tab-Reihenfolge Fokus auf body oder ein Ziel ohne sichtbaren Fokus (weder outline noch box-shadow); ebenso, wenn
// die Prüfung abbricht.
const { chromium } = require('playwright');
const fs = require('fs');
const AXE = fs.readFileSync(process.env.AXE_PFAD || __dirname + '/node_modules/axe-core/axe.min.js', 'utf8');
const B = `http://127.0.0.1:${process.env.PORT || 8765}/`;
const BR = Number(process.env.BREITE || 1400), HO = Number(process.env.HOEHE || 900), MOB = BR <= 900;
// Telefon: Leiste im Blatt ☰; das Menü öffnen, falls es zu ist
const burger = async (p) => { if (MOB && !(await p.evaluate(() => document.body.classList.contains('nav-open')))) await p.click('#nav-burger'); };
const run = async (p, name, rows) => {
  await p.addScriptTag({ content: AXE });
  const r = await p.evaluate(async () => await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }));
  for (const v of r.violations) rows.push([name, v.id, v.impact, v.nodes.length, v.help, v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | ')]);
  return r.violations.length;
};
(async () => {
  const b = await chromium.launch({ args: ['--no-proxy-server'] });
  const rows = [], tabs = [], tabBefunde = [];
  let pruefungen = 0;
  try {
    const p = await b.newPage({ viewport: { width: BR, height: HO }, bypassCSP: true });
    // nur die lokale Seite: Anfragen an andere Hosts abbrechen (etwa das absolut eingebundene Symbol in 404.html,
    // OpenStreetMap-Kacheln ohne lokale Kacheln); die Prüfung stellt keine Anfragen nach außen
    await p.route((u) => !u.href.startsWith(B), (r) => r.abort());
    // Hinweis „Testdaten“ (nie veröffentlicht, z-index 3000) liegt bei geringer Höhe über der Liste
    if (HO < 400) await p.addInitScript(() => document.addEventListener('DOMContentLoaded', () => { const h = document.getElementById('testdaten-hinweis'); if (h) h.style.display = 'none'; }));
    const axe = async (name) => { pruefungen++; return run(p, name, rows); };
    await p.goto(B, { waitUntil: 'networkidle' }); await p.waitForTimeout(800); await axe('start');
    await p.goto(B + '?gebiet=ortsteil:ehrenfeld', { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
    await burger(p); await p.click('.toggle[data-panel="panel-list"]'); await p.waitForTimeout(300);
    await p.click('#papers li button'); await p.waitForTimeout(800); await axe('vorgang');
    await burger(p); await p.click('.toggle[data-panel="timeline-wrap"]'); await p.waitForTimeout(500); await axe('zeitleiste');
    // Menüs der Leiste (Entscheidung 20.11.2026 (7)); der Dialog „Über den Ratsatlas“ öffnet aus dem Menü „Über“
    for (const m of ['themen', 'entscheiden', 'mitmachen', 'ueber']) {
      await burger(p); await p.click(`[data-mega="mega-${m}"]`); await p.waitForTimeout(300); await axe(`menue-${m}`);
    }
    await p.click('#about-open'); await p.waitForTimeout(300); await axe('ueber'); await p.keyboard.press('Escape');
    // Fläche „Mitmachen in Köln“ (nur mit Freigabe „mitmachen“; zweiter Lauf, 13.11.2026) mit gewähltem Stadtbezirk
    // Mit Freigabe steht #panel-mitmachen im HTML; öffnet sich die Fläche dann nicht, ist das ein Befund (keine stille Lücke)
    await p.goto(B + '?gebiet=ortsteil:ehrenfeld&mitmachen=1', { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
    if (await p.$('#panel-mitmachen')) {
      if (await p.waitForSelector('#panel-mitmachen:not([hidden]) #bt-bezirk', { timeout: 10000 }).catch(() => null)) {
        await p.click('.bt-quorum summary').catch(() => {}); await p.waitForTimeout(200); await axe('mitmachen-flaeche');
      } else rows.push(['mitmachen-flaeche', 'nicht geöffnet', '', '', 'Fläche „Mitmachen in Köln“ trotz Freigabe nicht geöffnet', '']);
    }
    // Fläche „Gremien und Ämter“ (nur mit Freigabe „gremien“; Pull Request 4b): Schaubild mit gewähltem Gremium, Liste mit
    // früheren Gremien, Reiter „Ämter“; mit Freigabe steht #panel-gremien im HTML, öffnet sie sich nicht, ist das ein Befund
    await p.goto(B + '?wer=gremien&darstellung=schaubild&kennung=rat', { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
    if (await p.$('#panel-gremien')) {
      if (await p.waitForSelector('#panel-gremien:not([hidden]) #wer-detail h3', { timeout: 10000 }).catch(() => null)) {
        await axe('gremien-schaubild');
        await p.click('.wer-darstellung [data-darstellung="liste"]'); await p.check('#wer-frueher').catch(() => {}); await p.waitForTimeout(200);
        await axe('gremien-liste');
        await p.click('#tab-wer-aemter'); await p.waitForTimeout(200); await axe('aemter');
      } else rows.push(['gremien', 'nicht geöffnet', '', '', 'Fläche „Gremien und Ämter“ trotz Freigabe nicht geöffnet', '']);
    }
    for (const s of ['gebiete/', 'begriffe/', 'einfach/', 'rss/', 'datenschutz.html', 'ortsteil/ehrenfeld/', '404.html']) {
      const r = await p.goto(B + s, { waitUntil: 'networkidle' }); if (r && r.status() < 400) await axe(s); else rows.push([s, 'nicht gefunden', '', '', '', '']);
    }
    // Tastatur: Tab-Reihenfolge der ersten 25 Fokusziele auf der Startseite; Befund bei Fokus auf body oder ohne
    // sichtbaren Fokus
    await p.goto(B, { waitUntil: 'networkidle' });
    for (let i = 0; i < 25; i++) {
      await p.keyboard.press('Tab');
      const z = await p.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e);
        return { ziel: `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''} „${(e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 30)}“`,
          body: e === document.body, outline: cs.outlineStyle !== 'none' || cs.boxShadow !== 'none' }; });
      tabs.push(`${z.ziel} outline=${z.outline}`);
      if (z.body || !z.outline) tabBefunde.push(`Tab ${i + 1}: ${z.ziel} ${z.body ? 'Fokus auf body' : 'ohne sichtbaren Fokus'}`);
    }
  } catch (e) {
    rows.push(['-', 'abgebrochen', '', '', String(e && e.message || e).split('\n')[0].slice(0, 300), '']);
  }
  await b.close();
  fs.writeFileSync(process.argv[2], ['seite\tregel\tgewicht\tanzahl\thilfe\tbeispiele', ...rows.map(r => r.join('\t'))].join('\n') + '\n');
  fs.writeFileSync(process.argv[3], tabs.join('\n') + '\n');
  console.log(`${BR} × ${HO}: ${pruefungen} Prüfungen mit axe, ${tabs.length} Tab-Schritte; ${rows.length} Befunde (axe und Abläufe), ${tabBefunde.length} Befunde der Tab-Reihenfolge`);
  rows.forEach(r => console.log(r.slice(0, 5).join(' | ')));
  tabBefunde.forEach(t => console.log(t));
  process.exit(rows.length || tabBefunde.length ? 1 : 0);
})();
