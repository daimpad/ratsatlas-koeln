// Browserprüfung der Kölner Themenseiten (Entscheidung 24.11.2026 (3), Antworten zum Plan vom 25.11.2026: Pilot
// „Verkehr und Mobilität“) mit Testdaten bei 1440×900, 1024×768, auf dem iPhone 13 und bei 320×256 (etwa 400 % Zoom).
// Die Seite entsteht in einem eigenen Bau mit tools/testdaten.py --themen und dem Prüfschalter RATSATLAS_THEMEN_PRUEFUNG
// (wirkt nur mit Testdaten; .github/workflows/tests.yml, „Seite mit Themenseiten bauen (Testdaten)“). Geprüft werden:
// - Übersicht thema/: lädt ohne Skriptfehler, Einzahl bei einem Thema, ganze Kachel klickbar, Symbol für Screenreader
//   ausgeblendet, Karte „Themenseiten“ im Menü „Themen“ der Startseite;
// - Themenseite: lädt ohne Skriptfehler, Kopfband mit „Alle Themen“, Sprungleiste (h2) mit genau den Zielen
//   #fachausschuss, #sitzungen, #mitwirken, #vorlagen (per Tastatur angesprungen), keine waagerechte Verschiebung der
//   Seite, Akkordeons per Tastatur, Zeitleiste: Punkt und Sitzung per Tastatur (Enter, Esc, Fokus zurück, Ansage,
//   Seitenlink #auswahl=…) und per Klick, Sammelmarke per Tastatur (Liste, „Angaben“, „Zurück zur Liste“, Esc), jedes
//   Ziel im Bild am eigenen Mittelpunkt treffbar (nichts verdeckt es), Detailfeld nach Klick oder Tipp im Fenster (auch
//   bei 320 × 256), Schalter mit aria-pressed und &straenge=…, Zustand aus dem Seitenlink beim Laden; Bahnnamen als stehende Spalte außerhalb des verschiebbaren Rahmens (bleiben beim Verschieben stehen, Zeilen
//   passen zu den Bahnen im Bild), Legende als HTML außerhalb des Bildes, Tabellenzellen mit data-l und auf dem Telefon
//   mit sichtbaren Spaltennamen; keine Links auf ?thema=; Links in die Karte (Gremien und Ämter, Vorlagen des
//   Gremiums, Mitmachen in Köln, Ebene Fahrradstraßen) öffnen das Erwartete (nur bei 1440×900);
// - nach jeder Bedienung liegt der Fokus nicht auf body und ist sichtbar;
// - axe-core (WCAG 2.1 A/AA) in jedem Zustand: Übersicht, Themenseite, Akkordeons offen, Detailfeld offen (Punkt und
//   Sitzung), Schalter umgeschaltet;
// - keine Anfrage an andere Hosts: Jeder Browserkontext bricht sie ab (ctx.route, auch aus neuen Fenstern), und die
//   Prüfung zählt sie auf den Themenseiten als Befund.
// Aufruf (Seite mit Themenseiten, z. B. RATSATLAS_THEMEN_PRUEFUNG=verkehr nach python3 tools/testdaten.py --themen,
//   Pipeline, tools/seite_bauen.py _site_themen, dann python3 -m http.server --bind 127.0.0.1 8791 -d _site_themen):
//   NODE_PATH=<…/node_modules mit playwright> AXE_PFAD=<…/axe.min.js> [FOTOS=<Ordner>] node tests/browser/themen.js http://127.0.0.1:8791/ [ergebnis.json]
// Ausgabe: je Prüfung eine Zeile; Exit-Code 1 bei einem Befund (auch ohne AXE_PFAD, ohne Themenseite oder bei Abbruch).
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");
const BASIS = process.argv[2] || "http://127.0.0.1:8791/";
const AUSGABE = process.argv[3];
const FOTOS = process.env.FOTOS || null;
const AXE = process.env.AXE_PFAD ? fs.readFileSync(process.env.AXE_PFAD, "utf8") : null;
const PROFILE = {
  1440: { viewport: { width: 1440, height: 900 } },
  1024: { viewport: { width: 1024, height: 768 } },
  iphone13: devices["iPhone 13"],
  klein: { viewport: { width: 320, height: 256 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const UEBERSICHT = "thema/";
const PILOT = "thema/verkehr-und-mobilitaet/";
const SPRUNGZIELE = ["fachausschuss", "sitzungen", "mitwirken", "vorlagen"];
// Legende; die Einträge der Sammelmarken nur, wenn das Bild welche zeigt, die Nummer im Punkt nur mit einzelnen
// Punkten (pipeline/prozessbild.py, legende)
const legende = (einzeln, punkte, sitzungen) => ["entschieden", "beraten, ohne abschließende Entscheidung", "offen",
  ...(einzeln ? ["Zahl im Punkt: Nummer in der Liste der Beschlüsse und Anträge"] : []),
  ...(punkte ? ["mehrere Beschlüsse und Anträge an nahen Tagen (Zahl: Anzahl)"] : []), "nächste öffentliche Sitzung",
  ...(sitzungen ? ["mehrere Sitzungen an nahen Tagen (Zahl: Anzahl)"] : []), "Datenstand"];

const ergebnisse = [];
let befunde = 0;
const pruefen = (profil, name, ok, angaben) => {
  ergebnisse.push({ profil, name, ok: Boolean(ok), angaben });
  if (!ok) befunde++;
  console.log(`${ok ? "ok  " : "FEHL"} ${profil} ${name}${angaben === undefined ? "" : " " + JSON.stringify(angaben)}`);
};
// axe-core als Skript derselben Herkunft (AXE_ADRESSE, im Kontext bedient): Die Content-Security-Policy der Seiten bleibt
// in Kraft (kein bypassCSP), so fallen auch Verstöße der Seite gegen sie als Skriptfehler auf
const AXE_ADRESSE = BASIS + "__axe-core-pruefung__.js";
const axe = async (page, profil, zustand) => {
  if (!AXE) return pruefen(profil, `axe ${zustand}`, false, "AXE_PFAD fehlt");
  await page.addScriptTag({ url: AXE_ADRESSE });
  const r = await page.evaluate(async () => await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }));
  const v = r.violations.map((x) => `${x.id} (${x.nodes.length}): ${x.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
  pruefen(profil, `axe ${zustand}`, v.length === 0, v);
};
const foto = async (page, name, wo) => {
  if (!FOTOS) return;
  if (wo) await (await page.$(wo)).screenshot({ path: path.join(FOTOS, `${name}.png`) });
  else await page.screenshot({ path: path.join(FOTOS, `${name}.png`), fullPage: false });
};
async function einzeln(profil, name, f) {
  try { await f(); } catch (e) { pruefen(profil, `${name}: Ablauf`, false, String(e && e.message || e).split("\n")[0].slice(0, 300)); }
}

const nichtLokal = (u) => !["127.0.0.1", "localhost"].includes(u.hostname);
async function neueSeite(browser, profil) {
  const ctx = await browser.newContext({ ...PROFILE[profil] });
  await ctx.route(nichtLokal, (r) => r.abort());
  const page = await ctx.newPage();
  if (AXE) await ctx.route(AXE_ADRESSE, (r) => r.fulfill({ body: AXE, contentType: "text/javascript; charset=utf-8" }));
  const fehler = [], fremd = [];
  // Anfragen an andere Hosts zählen (der Kontext bricht sie oben ab); data: und blob: zählen nicht
  ctx.on("request", (q) => { const u = new URL(q.url()); if (/^https?:$/.test(u.protocol) && nichtLokal(u)) fremd.push(u.origin + u.pathname); });
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fehler.push(`console: ${m.text()}`); });
  // Hinweis „Testdaten“ der Karte (nur mit Testdaten, z-index 3000) liegt bei geringer Höhe über den Flächen
  await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
    const h = document.getElementById("testdaten-hinweis");
    if (h) h.style.display = "none";
  }));
  return { ctx, page, fehler, fremd };
}
const telefon = (page) => page.evaluate(() => window.innerWidth <= 600);
// Fokus: Element, nicht body, mit sichtbarem Rahmen (outline oder box-shadow)
const fokus = (page) => page.evaluate(() => {
  const e = document.activeElement, cs = getComputedStyle(e);
  return { body: !e || e === document.body || e === document.documentElement, tag: e ? e.tagName.toLowerCase() : "",
    ziel: e && e.dataset ? e.dataset.ziel || e.dataset.strang || e.id || "" : "",
    text: (e.getAttribute("aria-label") || e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40),
    rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none" };
});
const fokusOk = (f) => !f.body && f.rahmen;
const ohneVerschiebung = (page) => page.evaluate(() => ({ breite: document.documentElement.scrollWidth, fenster: document.documentElement.clientWidth }));

// Übersicht thema/
async function uebersicht(browser, profil) {
  const s = await neueSeite(browser, profil);
  const r = await s.page.goto(BASIS + UEBERSICHT, { waitUntil: "load" });
  pruefen(profil, "Übersicht thema/ geladen", r && r.status() === 200, r && r.status());
  const u = await s.page.evaluate(() => ({
    h1: document.querySelector("h1")?.textContent.trim(), lead: document.querySelector(".lead")?.textContent || "",
    zahlen: [...document.querySelectorAll(".themen-zahlen li")].map((l) => l.textContent.trim().replace(/\s+/g, " ")),
    kacheln: [...document.querySelectorAll(".kachel")].map((k) => ({ titel: k.querySelector("h2 a")?.textContent.trim(),
      href: k.querySelector("h2 a")?.getAttribute("href"), symbol: k.querySelector(".kachel-symbol")?.getAttribute("aria-hidden"),
      frist: /Frist|Anregungen bis/.test(k.textContent) })),
    titel: document.title }));
  const eins = u.kacheln.length === 1;
  pruefen(profil, "Übersicht: Überschrift, Kacheln mit Link und ausgeblendetem Symbol, ohne Frist", u.h1 === "Themen" && u.kacheln.length >= 1
    && u.kacheln.every((k) => k.titel && k.href && k.symbol === "true" && !k.frist)
    && u.kacheln.some((k) => new URL(k.href, BASIS + UEBERSICHT).href === BASIS + PILOT), u.kacheln);
  pruefen(profil, "Übersicht: Einzahl bei einem Thema", !eins || (u.lead.startsWith("Die Themenseite ordnet") && u.lead.includes(" zeigt, ")
    && u.zahlen.includes("1 Thema")), { lead: u.lead.slice(0, 40), zahlen: u.zahlen });
  const v = await ohneVerschiebung(s.page);
  pruefen(profil, "Übersicht: keine waagerechte Verschiebung", v.breite <= v.fenster, v);
  await axe(s.page, profil, "Übersicht");
  await foto(s.page, `themen-uebersicht-${profil}`);
  // Tastatur: Tab erreicht den Link der Kachel mit sichtbarem Rahmen um die Kachel
  await s.page.focus(".kachel h2 a");
  const k = await s.page.evaluate(() => { const a = document.activeElement, cs = getComputedStyle(a.closest(".kachel"));
    return { link: a.matches(".kachel h2 a"), rahmen: cs.outlineStyle !== "none" && cs.outlineWidth !== "0px" }; });
  pruefen(profil, "Übersicht: Kachel mit Fokus umrandet", k.link && k.rahmen, k);
  // ganze Kachel klickbar: Klick in den farbigen Kopf (nicht auf den Link) öffnet die Themenseite
  const kopf = await s.page.$(".kachel .kachel-kopf");
  await kopf.scrollIntoViewIfNeeded();
  const box = await kopf.boundingBox();
  await Promise.all([s.page.waitForURL(BASIS + PILOT, { timeout: 15000 }), s.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)]);
  pruefen(profil, "Übersicht: Klick auf die Kachel öffnet die Themenseite", s.page.url() === BASIS + PILOT, s.page.url());
  pruefen(profil, "Übersicht: keine Skriptfehler", s.fehler.length === 0, s.fehler);
  pruefen(profil, "Übersicht: keine Anfrage an andere Hosts", s.fremd.length === 0, s.fremd.slice(0, 5));
  await s.ctx.close();
}

// Themenseite: Aufbau, Zeitleiste, Legende, Tabellen, Akkordeons
async function themenseite(browser, profil) {
  const s = await neueSeite(browser, profil);
  const { page } = s;
  const r = await page.goto(BASIS + PILOT, { waitUntil: "load" });
  pruefen(profil, "Themenseite geladen", r && r.status() === 200, r && r.status());
  await page.waitForFunction(() => !document.querySelector(".pb-filter")?.hidden, null, { timeout: 10000 });
  const a = await page.evaluate(() => ({
    titel: document.title, h1: document.querySelector(".thema-kopf h1")?.textContent.trim(),
    alle: document.querySelector(".thema-kopf a.thema-alle")?.href || "",
    symbol: document.querySelector(".thema-kopf .kachel-symbol")?.getAttribute("aria-hidden"),
    sprungH2: document.querySelector("nav.thema-sprung > h2#sprung-h")?.textContent.trim(),
    sprung: [...document.querySelectorAll("nav.thema-sprung a")].map((x) => x.getAttribute("href")),
    ziele: [...document.querySelectorAll("nav.thema-sprung a")].map((x) => document.getElementById(x.getAttribute("href").slice(1))?.tagName.toLowerCase() || null),
    thema: [...document.querySelectorAll("a[href]")].filter((x) => /[?&]thema=/.test(x.getAttribute("href"))).length,
    personen: /Vorsitz|Mitglieder mit Namen|Frist für Anträge|21 Tage|zwei Wochen/.test(document.querySelector("main").textContent) }));
  pruefen(profil, "Kopfband: Titel, Symbol ausgeblendet, „Alle Themen“ zur Übersicht", a.h1 && a.titel.startsWith(a.h1)
    && a.symbol === "true" && a.alle === BASIS + UEBERSICHT, { h1: a.h1, alle: a.alle });
  pruefen(profil, "Sprungleiste: h2 und genau die Ziele #fachausschuss, #sitzungen, #mitwirken, #vorlagen (je h2)",
    a.sprungH2 === "Auf dieser Seite" && JSON.stringify(a.sprung) === JSON.stringify(SPRUNGZIELE.map((z) => `#${z}`))
    && a.ziele.every((t) => t === "h2"), { sprung: a.sprung, ziele: a.ziele });
  pruefen(profil, "keine Links auf ?thema=, kein Vorsitz und keine berechneten Fristen", a.thema === 0 && !a.personen, { thema: a.thema, personen: a.personen });
  let v = await ohneVerschiebung(page);
  pruefen(profil, "Themenseite: keine waagerechte Verschiebung", v.breite <= v.fenster, v);
  await axe(page, profil, "Themenseite");
  await foto(page, `themen-seite-${profil}`);

  // Sprungleiste und Stränge per Tastatur: Enter springt zum Ziel, der Fokus liegt danach sichtbar auf der Überschrift
  // (tabindex="-1"; sonst läge er auf body)
  const strang = await page.$eval("main h2#vorlagen + p a[href^='#']", (x) => x.getAttribute("href").slice(1)).catch(() => null);
  for (const [z, von] of [...SPRUNGZIELE.map((x) => [x, `nav.thema-sprung a[href="#${x}"]`]), ...(strang ? [[strang, `main h2#vorlagen + p a[href="#${strang}"]`]] : [])]) {
    await page.focus(von);
    await page.keyboard.press("Enter");
    await page.waitForFunction((id) => location.hash === `#${id}`, z, { timeout: 5000 }).catch(() => {});
    const lage = await page.evaluate((id) => { const r = document.getElementById(id).getBoundingClientRect();
      return { hash: location.hash, oben: Math.round(r.top), fenster: innerHeight }; }, z);
    const f = await fokus(page);
    pruefen(profil, `Sprung zu #${z} per Tastatur: Ziel oben im Fenster, Fokus sichtbar auf der Überschrift`, lage.hash === `#${z}`
      && lage.oben >= -2 && lage.oben < lage.fenster && f.ziel === z && fokusOk(f), { ...lage, fokus: f });
  }
  await page.evaluate(() => { history.replaceState(null, "", location.pathname); window.scrollTo(0, 0); });

  // Zeitleiste: Bahnnamen als stehende Spalte außerhalb des Rahmens, Zeilen passend zum Bild
  const zl = await page.evaluate(() => {
    const rahmen = document.querySelector(".pb-zeitleiste .pb-rahmen"), svg = rahmen?.querySelector("svg.pb-svg");
    const spalte = document.querySelector(".pb-zeitleiste > .pb-bahnen");
    const namen = [...document.querySelectorAll(".pb-bahnen .pb-bahn")];
    // Bahnen im Bild: die Rechtecke direkt unter svg (eins je Bahn), so wie sie gezeichnet sind (mit Skalierung)
    const raender = [...svg.querySelectorAll(":scope > rect")].map((r) => r.getBoundingClientRect());
    return { imRahmen: Boolean(rahmen.querySelector(".pb-bahnen")), spalte: Boolean(spalte), versteckt: spalte?.getAttribute("aria-hidden"),
      bahnenImBild: raender.length,
      zeilen: namen.map((n, i) => raender[i] ? Math.round(n.getBoundingClientRect().top - raender[i].top) : null),
      hoehen: namen.map((n, i) => raender[i] ? Math.round(n.getBoundingClientRect().height - raender[i].height) : null),
      masse: [Math.round(svg.getBoundingClientRect().width), Math.round(svg.getBoundingClientRect().height)],
      soll: [Number(svg.getAttribute("width")), Number(svg.getAttribute("height"))],
      textImBild: [...svg.querySelectorAll("text")].map((t) => t.textContent).filter((t) => namen.some((n) => n.textContent === t)),
      start: Number(rahmen.dataset.start), links: rahmen.scrollLeft, breite: rahmen.scrollWidth, sicht: rahmen.clientWidth };
  });
  pruefen(profil, "Bahnnamen: eigene Spalte außerhalb des verschiebbaren Rahmens, Zeilen wie im Bild", zl.spalte && !zl.imRahmen
    && zl.versteckt === "true" && zl.zeilen.length >= 2 && zl.bahnenImBild === zl.zeilen.length
    && zl.zeilen.every((d) => d !== null && Math.abs(d) <= 1) && zl.hoehen.every((d) => d !== null && Math.abs(d) <= 1)
    && zl.masse[0] === zl.soll[0] && zl.masse[1] === zl.soll[1] && zl.textImBild.length === 0, zl);
  if (zl.breite > zl.sicht) {
    pruefen(profil, "Zeitleiste: beim Laden zum Datenstand geschoben", zl.links > 0, { links: zl.links, start: zl.start });
  }
  // nach rechts verschieben: Bahnnamen bleiben an ihrer Stelle und im Fenster sichtbar
  await page.locator(".pb-zeitleiste").scrollIntoViewIfNeeded();
  const vorher = await page.$$eval(".pb-bahn", (ns) => ns.map((n) => { const r = n.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right)]; }));
  const geschoben = await page.evaluate(() => { const r = document.querySelector(".pb-zeitleiste .pb-rahmen"); r.scrollLeft = r.scrollWidth; return r.scrollLeft; });
  const nachher = await page.evaluate(() => ({ breite: innerWidth, namen: [...document.querySelectorAll(".pb-bahn")].map((n) => {
    const r = n.getBoundingClientRect(), x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), y = r.top + r.height / 2;
    const oben = y >= 0 && y < innerHeight ? document.elementFromPoint(x, y) : null;
    return { lr: [Math.round(r.left), Math.round(r.right)], sichtbar: r.width > 40 && r.left >= 0 && r.right <= innerWidth && getComputedStyle(n).visibility === "visible",
      frei: oben === null || n.contains(oben) || oben === n }; }) }));
  pruefen(profil, "Bahnnamen bleiben beim Verschieben des Rahmens nach rechts stehen und sichtbar",
    JSON.stringify(nachher.namen.map((n) => n.lr)) === JSON.stringify(vorher) && nachher.namen.every((n) => n.sichtbar && n.frei),
    { geschoben, vorher, nachher: nachher.namen });
  await foto(page, `themen-zeitleiste-rechts-${profil}`, ".pb-zeitleiste");

  // Legende als HTML außerhalb des Bildes
  const lg = await page.evaluate(() => {
    const ul = document.querySelector("ul.pb-legende-bild"), r = ul?.getBoundingClientRect();
    const zl = document.querySelector(".pb-zeitleiste");
    return { da: Boolean(ul), imBild: Boolean(ul?.closest("svg, .pb-rahmen, .pb-zeitleiste")),
      nachBild: Boolean(ul && zl && (zl.compareDocumentPosition(ul) & Node.DOCUMENT_POSITION_FOLLOWING)),
      sichtbar: Boolean(r && r.height > 0 && getComputedStyle(ul).display !== "none"),
      texte: ul ? [...ul.querySelectorAll("li")].map((l) => l.textContent.trim()) : [],
      zeichen: ul ? [...ul.querySelectorAll("li svg")].every((z) => z.getAttribute("aria-hidden") === "true") : false,
      imSvg: [...document.querySelectorAll(".pb-svg text")].some((t) => /entschieden|Legende|Sitzung/.test(t.textContent)),
      einzeln: Boolean(document.querySelector('.pb-svg a[data-ziel^="punkt-"]')),
      punkte: Boolean(document.querySelector('.pb-svg a[data-ziel^="punkte-"]')),
      sitzungen: Boolean(document.querySelector('.pb-svg a[data-ziel^="sitzungen-"]')) };
  });
  pruefen(profil, "Legende: HTML-Liste unter dem Bild, außerhalb des SVG und des Rahmens, Zeichen ausgeblendet",
    lg.da && !lg.imBild && lg.nachBild && lg.sichtbar && JSON.stringify(lg.texte) === JSON.stringify(legende(lg.einzeln, lg.punkte, lg.sitzungen))
    && lg.zeichen && !lg.imSvg, lg);
  await foto(page, `themen-zeitleiste-${profil}`, ".pb-zeitleiste");

  // Tabellen: jede Zelle mit data-l; auf dem Telefon Kopf ausgeblendet und Spaltenname vor dem Inhalt
  const tel = await telefon(page);
  // Lange Stränge stehen eingeklappt (Thema.einklappen_ab): gemessen wird die erste sichtbare Tabelle; ist keine
  // sichtbar, wird das erste Akkordeon mit Tabelle dafür geöffnet und danach wieder geschlossen
  const geoeffnet = await page.evaluate(() => {
    if ([...document.querySelectorAll("table.vorlagen")].some((t) => t.getClientRects().length)) return false;
    const d = document.querySelector("table.vorlagen")?.closest("details");
    if (d) d.open = true;
    return Boolean(d);
  });
  const tb = await page.evaluate(() => {
    const zellen = [...document.querySelectorAll("table.vorlagen td")];
    const tabelle = [...document.querySelectorAll("table.vorlagen")].find((t) => t.getClientRects().length);
    const erste = tabelle?.querySelector("tbody tr");
    // Drucksache in einer Zeile (Durchsicht vom 25.11.2026: „…/20“ und „26“ standen untereinander)
    const ds = tabelle ? [...tabelle.querySelectorAll('td[data-l="Drucksache"]')] : [];
    return { zellen: zellen.length, ohne: zellen.filter((td) => !td.dataset.l).length, sichtbar: Boolean(tabelle),
      kopf: tabelle ? getComputedStyle(tabelle.querySelector("thead")).display : null,
      vorher: erste ? [...erste.querySelectorAll("td")].map((td) => [td.dataset.l, getComputedStyle(td, "::before").content]) : [],
      drucksache: ds.length, umbruch: ds.filter((td) => { const a = td.querySelector("a") || td;
        const r = document.createRange(); r.selectNodeContents(a); return new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size > 1
          || td.scrollWidth > td.clientWidth + 1; }).length };
  });
  pruefen(profil, tel ? "Tabellen (Telefon): Kopf ausgeblendet, Spaltenname je Zelle sichtbar" : "Tabellen: Kopf sichtbar, jede Zelle mit data-l",
    tb.zellen > 0 && tb.ohne === 0 && tb.sichtbar && (tel ? tb.kopf === "none" && tb.vorher.length === 4 && tb.vorher.every(([l, c]) => c === `"${l}: "`)
      : tb.kopf !== "none" && tb.vorher.every(([, c]) => c === "none" || c === "normal")), tb);
  pruefen(profil, "Tabellen: Drucksache ohne Umbruch und ohne Überlauf", tb.drucksache > 0 && tb.umbruch === 0,
    { drucksache: tb.drucksache, umbruch: tb.umbruch });
  if (tel) await foto(page, `themen-tabelle-${profil}`, "table.vorlagen");
  if (geoeffnet) await page.evaluate(() => { document.querySelector("table.vorlagen").closest("details").open = false; });

  // Akkordeons per Tastatur: Enter öffnet, der Fokus bleibt sichtbar auf summary
  const akk = await page.$$eval("main details > summary", (ss) => ss.map((x, i) => { x.dataset.pruefNr = String(i); return x.textContent.trim().replace(/\s+/g, " ").slice(0, 40); }));
  const auf = [];
  for (let i = 0; i < akk.length; i++) {
    const sel = `summary[data-pruef-nr="${i}"]`;
    if (!(await page.$eval(sel, (x) => x.getClientRects().length > 0))) continue;   // in einem zugeklappten Akkordeon
    await page.focus(sel);
    await page.keyboard.press("Enter");
    const z = await page.$eval(sel, (x) => x.parentElement.open);
    const f = await fokus(page);
    auf.push({ text: akk[i], offen: z, fokus: fokusOk(f) });
  }
  pruefen(profil, "Akkordeons per Tastatur geöffnet, Fokus sichtbar auf summary", auf.length >= 6 && auf.every((x) => x.offen && x.fokus),
    auf.filter((x) => !(x.offen && x.fokus)).concat([{ anzahl: auf.length }]));
  v = await ohneVerschiebung(page);
  pruefen(profil, "Akkordeons offen: keine waagerechte Verschiebung", v.breite <= v.fenster, v);
  await axe(page, profil, "Akkordeons offen");
  // wieder zu (Enter auf einem offenen summary)
  await page.focus('summary[data-pruef-nr="0"]');
  await page.keyboard.press("Enter");
  pruefen(profil, "Akkordeon per Tastatur geschlossen", !(await page.$eval('summary[data-pruef-nr="0"]', (x) => x.parentElement.open)) && fokusOk(await fokus(page)));
  pruefen(profil, "Themenseite: keine Skriptfehler", s.fehler.length === 0, s.fehler);
  pruefen(profil, "Themenseite: keine Anfrage an andere Hosts", s.fremd.length === 0, s.fremd.slice(0, 5));
  await s.ctx.close();
}

// Zeitleiste bedienen: Punkt und Sitzung per Tastatur und Klick, Schalter, Seitenlink
const detail = (page) => page.evaluate(() => {
  const f = document.getElementById("pb-detail");
  return { offen: !f.hidden, titel: document.getElementById("pb-detail-titel")?.textContent || "", text: f.innerText,
    links: [...f.querySelectorAll("a")].map((a) => ({ text: a.textContent.trim(), href: a.getAttribute("href"), ziel: a.target || "" })),
    ansage: document.getElementById("pb-ansage").textContent, auswahl: new URLSearchParams(location.hash.slice(1)).get("auswahl"),
    straenge: new URLSearchParams(location.hash.slice(1)).get("straenge") };
});
// Tab vom Rahmen der Zeitleiste bis zum ersten Ziel, dessen data-ziel mit `anfang` beginnt
async function tabBis(page, anfang) {
  await page.focus(".pb-zeitleiste .pb-rahmen");
  for (let i = 0; i < 400; i++) {
    await page.keyboard.press("Tab");
    const z = await page.evaluate(() => document.activeElement?.dataset?.ziel || null);
    if (z && z.startsWith(anfang)) return z;
  }
  return null;
}

// Detailfeld im sichtbaren Bereich des Fensters (mindestens teilweise)
const feldImFenster = (page) => page.evaluate(() => { const r = document.getElementById("pb-detail").getBoundingClientRect();
  return { oben: Math.round(r.top), unten: Math.round(r.bottom), fenster: innerHeight, ok: r.height > 0 && r.top < innerHeight && r.bottom > 0 }; });

async function zeitleiste(browser, profil) {
  const s = await neueSeite(browser, profil);
  const { page } = s;
  await page.goto(BASIS + PILOT, { waitUntil: "load" });
  await page.waitForFunction(() => !document.querySelector(".pb-filter")?.hidden, null, { timeout: 10000 });
  const daten = await page.evaluate(() => JSON.parse(document.getElementById("pb-daten").textContent));
  // jedes Ziel (Punkt, Sitzung, Sammelmarke) am eigenen Mittelpunkt treffbar: nichts verdeckt es, und es liegt im Bild
  const treffer = await page.evaluate(() => {
    const svg = document.querySelector(".pb-svg"), aus = [];
    const ziele = [...svg.querySelectorAll("a.pb-ziel[data-ziel]")];
    for (const a of ziele) {
      a.scrollIntoView({ block: "center", inline: "center" });
      const b = svg.getBoundingClientRect();
      const r = a.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
      const o = document.elementFromPoint(x, y);
      const imBild = r.left >= b.left - 0.5 && r.right <= b.right + 0.5 && r.top >= b.top - 0.5 && r.bottom <= b.bottom + 0.5;
      if (!o || !a.contains(o) || !imBild) aus.push({ ziel: a.dataset.ziel, imBild, oben: o ? (o.closest("a")?.dataset.ziel || o.tagName) : null });
    }
    window.scrollTo(0, 0);
    return { zahl: ziele.length, aus, sammel: ziele.filter((a) => /^(punkte|sitzungen)-/.test(a.dataset.ziel)).length };
  });
  pruefen(profil, "Zeitleiste: jedes Ziel am eigenen Mittelpunkt treffbar und im Bild (nichts verdeckt)", treffer.zahl > 0
    && treffer.aus.length === 0, treffer);
  // Punkt per Tastatur
  const ziel = await tabBis(page, "punkt-");
  pruefen(profil, "Zeitleiste: Punkt per Tab erreichbar", Boolean(ziel), ziel);
  if (ziel) {
    const p = daten.punkte[ziel.slice(6)];
    await page.keyboard.press("Enter");
    let d = await detail(page);
    let f = await fokus(page);
    pruefen(profil, "Punkt: Enter öffnet das Detailfeld (Titel, Ansage, #auswahl=Drucksache), Fokus bleibt auf dem Punkt",
      d.offen && d.titel === `${p.nr}: ${p.reference}` && d.ansage.startsWith(`Ausgewählt: ${p.reference}`) && d.auswahl === p.reference
      && f.ziel === ziel && fokusOk(f), { titel: d.titel, auswahl: d.auswahl, fokus: f });
    pruefen(profil, "Punkt: Detailfeld mit Stand, Strang (abgeleitet) und Beratungsfolge, ohne Frist und Federführung",
      /Stand/.test(d.text) && /Strang/.test(d.text) && /abgeleitet/.test(d.text) && /Beratungsfolge/.test(d.text)
      && !/Frist|Federführ|21 Tage|zwei Wochen/.test(d.text)
      && d.links.filter((l) => /^https?:/.test(l.href)).every((l) => l.ziel === "_blank" && /neuer Tab/.test(l.text)), d.links);
    await axe(page, profil, "Detailfeld offen (Punkt)");
    await foto(page, `themen-detail-punkt-${profil}`, "#pb-detail");
    await page.keyboard.press("Escape");
    d = await detail(page);
    f = await fokus(page);
    pruefen(profil, "Punkt: Esc schließt, Fokus zurück auf dem Punkt, Seitenlink ohne Auswahl",
      !d.offen && d.ansage === "Detailfeld geschlossen." && !d.auswahl && f.ziel === ziel && fokusOk(f), { fokus: f, hash: d.auswahl });
  }
  // Sitzung per Tastatur, Schließen über die Schaltfläche
  const sz = await tabBis(page, "sitzung-");
  pruefen(profil, "Zeitleiste: Sitzung per Tab erreichbar", Boolean(sz), sz);
  if (sz) {
    const m = daten.sitzungen[sz.slice(8)];
    await page.keyboard.press("Enter");
    let d = await detail(page);
    pruefen(profil, "Sitzung: Enter öffnet das Detailfeld mit Tagesordnung, Kalender und Wegen zum Mitwirken, ohne Frist",
      d.offen && d.titel === m.gremium && d.auswahl === sz && (!m.web || d.links.some((l) => l.text.startsWith("Tagesordnung") && l.href === m.web))
      && d.links.some((l) => l.text === "Kalender (.ics)") && d.links.some((l) => l.text === "Wege zum Mitwirken")
      && !/Frist|21 Tage|zwei Wochen/.test(d.text), { titel: d.titel, links: d.links.map((l) => l.text) });
    await axe(page, profil, "Detailfeld offen (Sitzung)");
    await page.focus("#pb-detail .pb-schliessen");
    await page.keyboard.press("Enter");
    d = await detail(page);
    const f = await fokus(page);
    pruefen(profil, "Sitzung: „Schließen“ schließt, Fokus zurück auf der Sitzung", !d.offen && f.ziel === sz && fokusOk(f), f);
  }
  // Punkt per Klick (Maus oder Finger): öffnet, zweiter Klick schließt
  const klick = await page.evaluate(() => {
    for (const a of document.querySelectorAll('.pb-svg a.pb-ziel[data-ziel^="punkt-"]')) {
      a.scrollIntoView({ block: "center", inline: "center" });
      const r = a.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
      const o = document.elementFromPoint(x, y);
      if (o && a.contains(o)) return { ziel: a.dataset.ziel, x, y };
    }
    return null;
  });
  pruefen(profil, "Zeitleiste: ein Punkt ist frei anklickbar", Boolean(klick));
  if (klick) {
    if (PROFILE[profil].hasTouch) await page.touchscreen.tap(klick.x, klick.y); else await page.mouse.click(klick.x, klick.y);
    await page.waitForTimeout(400);   // Rollen ins Bild (scrollIntoView)
    let d = await detail(page);
    const p = daten.punkte[klick.ziel.slice(6)];
    const lage = await feldImFenster(page);
    pruefen(profil, "Punkt: Klick öffnet das Detailfeld, das Feld liegt im Fenster", d.offen && d.titel === `${p.nr}: ${p.reference}`
      && !(await fokus(page)).body && lage.ok, { titel: d.titel, lage });
    // das Detailfeld kann ins Bild gerollt sein (schmale Fenster): den Punkt dafür wieder ins Fenster holen
    const pos = await page.evaluate((z) => { const a = document.querySelector(`.pb-svg a[data-ziel="${z}"]`);
      a.scrollIntoView({ block: "center", inline: "center" }); const r = a.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, klick.ziel);
    if (PROFILE[profil].hasTouch) await page.touchscreen.tap(pos.x, pos.y); else await page.mouse.click(pos.x, pos.y);
    d = await detail(page);
    pruefen(profil, "Punkt: zweiter Klick schließt, Fokus nicht auf body", !d.offen && !(await fokus(page)).body);
  }
  // Sammelmarke per Tastatur: Enter öffnet die Liste ihrer Einträge, „Angaben“ einen Eintrag (Fokus auf der Überschrift),
  // „Zurück zur Liste“ wieder die Liste (Fokus auf „Angaben“ desselben Eintrags), Esc schließt (Fokus auf der Sammelmarke)
  const gr = await tabBis(page, "punkte-");
  if (gr) {
    const eintraege = daten.gruppen[gr];
    await page.keyboard.press("Enter");
    let d = await detail(page);
    let f = await fokus(page);
    const n = await page.$$eval("#pb-detail ol.pb-gruppe > li", (ls) => ls.length);
    pruefen(profil, "Sammelmarke: Enter öffnet die Liste ihrer Beschlüsse und Anträge, Fokus bleibt auf der Marke",
      d.offen && d.titel === `${eintraege.length} Beschlüsse und Anträge` && n === eintraege.length && d.auswahl === gr
      && f.ziel === gr && fokusOk(f), { titel: d.titel, n, fokus: f });
    await axe(page, profil, "Detailfeld offen (Sammelmarke)");
    await page.focus("#pb-detail button.pb-eintrag");
    await page.keyboard.press("Enter");
    d = await detail(page);
    f = await fokus(page);
    const p = daten.punkte[eintraege[0].slice(6)];
    pruefen(profil, "Sammelmarke: „Angaben“ zeigt den Eintrag (Beratungsfolge), Fokus sichtbar auf der Überschrift",
      d.offen && d.titel === `${p.nr}: ${p.reference}` && /Beratungsfolge/.test(d.text) && d.auswahl === p.reference
      && f.ziel === "pb-detail-titel" && fokusOk(f), { titel: d.titel, fokus: f });
    await axe(page, profil, "Detailfeld offen (Eintrag einer Sammelmarke)");
    await page.focus("#pb-detail button.pb-zurueck");
    await page.keyboard.press("Enter");
    d = await detail(page);
    f = await fokus(page);
    const zurueck = await page.evaluate(() => document.activeElement?.dataset?.eintrag || null);
    pruefen(profil, "Sammelmarke: „Zurück zur Liste“ zeigt die Liste, Fokus auf „Angaben“ des Eintrags",
      d.offen && d.titel === `${eintraege.length} Beschlüsse und Anträge` && zurueck === eintraege[0] && fokusOk(f), { titel: d.titel, zurueck });
    await page.keyboard.press("Escape");
    d = await detail(page);
    f = await fokus(page);
    pruefen(profil, "Sammelmarke: Esc schließt, Fokus zurück auf der Marke", !d.offen && f.ziel === gr && fokusOk(f), f);
    // zweiter Knopf zum Schließen am Ende der Liste (Durchsicht vom 25.11.2026: große Sammelmarken)
    await page.keyboard.press("Enter");
    const unten = await page.evaluate(() => { const b = document.querySelector("#pb-detail .pb-schliessen-unten");
      return b ? { text: b.textContent, letzter: b === [...document.querySelectorAll("#pb-detail button")].pop() } : null; });
    await page.focus("#pb-detail .pb-schliessen-unten");
    await page.keyboard.press("Enter");
    d = await detail(page);
    f = await fokus(page);
    pruefen(profil, "Sammelmarke: Knopf „Schließen, zurück zum Bild“ am Ende der Liste schließt, Fokus zurück auf der Marke",
      unten && unten.letzter && !d.offen && f.ziel === gr && fokusOk(f), { unten, fokus: f });
  } else {
    pruefen(profil, "Sammelmarke im Bild (Testdaten mit vielen Beschlüssen an einem Sitzungstag)", false, "keine Sammelmarke");
  }
  // Schalter: Leertaste schaltet, aria-pressed, &straenge=…, Punkte des Strangs abgeblendet
  const schalter = await page.$$eval(".pb-schalter", (bs) => bs.map((b) => b.dataset.strang));
  if (schalter.length) {
    await page.focus(`.pb-schalter[data-strang="${schalter[0]}"]`);
    await page.keyboard.press("Space");
    const z = await page.evaluate((k) => ({ gedrueckt: document.querySelector(`.pb-schalter[data-strang="${k}"]`).getAttribute("aria-pressed"),
      straenge: new URLSearchParams(location.hash.slice(1)).get("straenge"),
      gedimmt: [...document.querySelectorAll(`.pb-svg a.pb-ziel[data-strang="${k}"]`)].every((a) => a.classList.contains("pb-gedimmt")),
      andere: [...document.querySelectorAll('.pb-svg a.pb-ziel[data-strang]:not([data-strang=""])')].filter((a) => a.dataset.strang !== k)
        .every((a) => !a.classList.contains("pb-gedimmt")) }), schalter[0]);
    const f = await fokus(page);
    pruefen(profil, "Schalter: Leertaste schaltet aus (aria-pressed, &straenge= ohne den Strang, Punkte abgeblendet), Fokus bleibt",
      z.gedrueckt === "false" && z.straenge === schalter.slice(1).join(",") && z.gedimmt && z.andere && f.ziel === schalter[0] && fokusOk(f), { ...z, fokus: f });
    await axe(page, profil, "Schalter umgeschaltet");
    await foto(page, `themen-schalter-${profil}`, ".pb-zeitleiste");
  } else {
    pruefen(profil, "Schalter vorhanden", false, "keine Schalter (keine Punkte im Bild?)");
  }
  pruefen(profil, "Zeitleiste: keine Skriptfehler", s.fehler.length === 0, s.fehler);
  pruefen(profil, "Zeitleiste: keine Anfrage an andere Hosts", s.fremd.length === 0, s.fremd.slice(0, 5));
  await s.ctx.close();

  // Seitenlink beim Laden: Auswahl und Stränge werden hergestellt
  const p = Object.values(daten.punkte)[0];
  if (p && schalter.length > 1) {
    const t = await neueSeite(browser, profil);
    const k = schalter[1];
    await t.page.goto(`${BASIS}${PILOT}#auswahl=${encodeURIComponent(p.reference)}&straenge=${k}`, { waitUntil: "load" });
    await t.page.waitForFunction(() => !document.getElementById("pb-detail").hidden, null, { timeout: 10000 }).catch(() => {});
    const d = await detail(t.page);
    const gedrueckt = await t.page.$$eval(".pb-schalter", (bs) => bs.filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.strang));
    pruefen(profil, "Seitenlink #auswahl=…&straenge=… stellt Auswahl und Schalter beim Laden her",
      d.offen && d.titel === `${p.nr}: ${p.reference}` && JSON.stringify(gedrueckt) === JSON.stringify([k]), { titel: d.titel, gedrueckt });
    // Hinweise aus den Sitzungsnamen im Detailfeld: abgesagte Beratung (export.absage „name“) und verschobene Sitzung
    const abgesagt = Object.values(daten.punkte).find((q) => q.beratungen.some((b) => b.abgesagt === "name"));
    if (abgesagt) {
      await t.page.evaluate((r) => { location.hash = `auswahl=${encodeURIComponent(r)}`; }, abgesagt.reference);
      await t.page.waitForFunction((titel) => document.getElementById("pb-detail-titel")?.textContent === titel,
        `${abgesagt.nr}: ${abgesagt.reference}`, { timeout: 5000 }).catch(() => {});
      const d2 = await detail(t.page);
      pruefen(profil, "Detailfeld: Beratung in einer laut Sitzungsnamen abgesagten Sitzung so benannt",
        d2.offen && d2.text.includes("Sitzung laut Sitzungsnamen abgesagt"), d2.titel);
    }
    const verschoben = daten.sitzungen.findIndex((m) => m.hinweis === "verschoben");
    if (verschoben >= 0) {
      await t.page.evaluate((n) => { location.hash = `auswahl=sitzung-${n}`; }, verschoben);
      await t.page.waitForFunction((titel) => document.getElementById("pb-detail-titel")?.textContent === titel,
        daten.sitzungen[verschoben].gremium, { timeout: 5000 }).catch(() => {});
      const d3 = await detail(t.page);
      pruefen(profil, "Detailfeld: Sitzung laut Sitzungsnamen verschoben", d3.offen && d3.text.includes("laut Sitzungsnamen verschoben"), d3.titel);
    }
    pruefen(profil, "Seitenlink: keine Skriptfehler", t.fehler.length === 0, t.fehler);
    await t.ctx.close();
  }
}

// Links in die Karte (nur 1440×900): Gremien und Ämter, Vorlagen des Gremiums, Mitmachen in Köln, Ebene; Karte im Menü
async function kartenLinks(browser, profil) {
  const s = await neueSeite(browser, profil);
  const { page } = s;
  await page.goto(BASIS + PILOT, { waitUntil: "load" });
  const links = await page.evaluate(() => {
    const finde = (re) => [...document.querySelectorAll("main a[href]")].find((a) => re.test(a.getAttribute("href")));
    const h = (a) => a ? { roh: a.getAttribute("href"), href: a.href, text: a.textContent.trim() } : null;
    return { wer: h(finde(/\?wer=gremien&kennung=/)), filter: h(finde(/\?gremium_filter=/)), mitmachen: h(finde(/\?mitmachen=1$/)),
      ebene: h(finde(/\?ebenen=fahrradstrassen$/)) };
  });
  pruefen(profil, "Links in die Karte vorhanden (Gremium, Vorlagen des Gremiums, Mitmachen, Ebene Fahrradstraßen)",
    links.wer && links.filter && links.mitmachen && links.ebene, links);
  const geladen = (p) => p.waitForFunction(() => {
    const c = document.getElementById("count");
    return c && c.textContent.trim() && !/^Lade/.test(c.textContent) && document.getElementById("detail").textContent.trim();
  }, null, { timeout: 30000 });
  // dem Link auf der Themenseite folgen (Klick, erster Link mit dieser Adresse)
  const folgen = async (link) => {
    await page.goto(BASIS + PILOT, { waitUntil: "load" });
    await Promise.all([page.waitForURL(link.href, { timeout: 15000 }), page.click(`main a[href="${link.roh}"]`)]);
    await geladen(page);
  };
  if (links.wer) {
    const key = new URL(links.wer.href).searchParams.get("kennung");
    await folgen(links.wer);
    const ok = await page.waitForSelector("#panel-gremien:not([hidden]) #wer-detail h3", { timeout: 15000 }).then(() => true, () => false);
    const h3 = ok ? await page.$eval("#wer-detail h3", (x) => x.textContent.trim()) : "";
    pruefen(profil, "Link „… unter Gremien und Ämter“ öffnet die Fläche mit dem Gremium", ok && h3.startsWith(links.wer.text.split(" unter ")[0]), { key, h3 });
  }
  if (links.filter) {
    const key = new URL(links.filter.href).searchParams.get("gremium_filter");
    await folgen(links.filter);
    const z = await page.waitForFunction((k) => document.getElementById("f-gremium").value === k && !document.getElementById("panel-list").hidden, key, { timeout: 15000 })
      .then(() => true, () => false);
    pruefen(profil, "Link „Vorlagen dieses Gremiums“ öffnet die Liste mit Filter Gremium", z, key);
  }
  if (links.mitmachen) {
    await folgen(links.mitmachen);
    const ok = await page.waitForSelector("#panel-mitmachen:not([hidden]) #bt-bezirk", { timeout: 20000 }).then(() => true, () => false);
    pruefen(profil, "Link „Mitmachen in Köln“ öffnet die Fläche", ok);
  }
  if (links.ebene) {
    await folgen(links.ebene);
    // Schalter der Ebene (auf schmalen Bildschirmen im eingeklappten Kartenmenü, daher nur vorhanden, nicht sichtbar)
    const ok = await page.waitForSelector('.map-kx-fahrradstrassen[aria-pressed="true"]', { state: "attached", timeout: 15000 }).then(() => true, () => false);
    pruefen(profil, "Link „Fahrradstraßen“ schaltet die Ebene ein", ok);
  }
  // Karte „Themenseiten“ im Menü „Themen“ der Startseite (mit Freigabe sichtbar, ohne Bonner Themen) führt zur Übersicht
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.click('.nav-group [data-mega="mega-themen"]');
  await page.waitForSelector("#mega-themen:not([hidden])");
  const karte = await page.$eval('#mega-themen a.card[href="thema/"]', (a) => ({ sichtbar: a.getClientRects().length > 0 && !a.hidden, text: a.innerText }))
    .catch(() => null);
  pruefen(profil, "Menü „Themen“: Karte „Themenseiten“ sichtbar, ohne Haushalt und Bonner Themen", karte && karte.sichtbar
    && /Zeitleiste/.test(karte.text) && !/Haushalt|Kultur|Digitales|Prozessbild/.test(karte.text), karte);
  if (karte) {
    await Promise.all([page.waitForURL(BASIS + UEBERSICHT, { timeout: 15000 }), page.click('#mega-themen a.card[href="thema/"]')]);
    pruefen(profil, "Karte „Themenseiten“ führt zur Übersicht", page.url() === BASIS + UEBERSICHT, page.url());
  }
  pruefen(profil, "Links in die Karte: keine Skriptfehler", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });
  try {
    if (!AXE) pruefen("-", "AXE_PFAD gesetzt", false, "ohne axe-core keine Prüfung nach WCAG");
    const hilfe = await browser.newPage();
    await hilfe.context().route(nichtLokal, (r) => r.abort());
    const r = await hilfe.goto(BASIS + PILOT, { waitUntil: "load" }).catch(() => null);
    await hilfe.close();
    if (!r || r.status() !== 200) {
      pruefen("-", "Themenseite vorhanden", false, `${BASIS + PILOT}: ${r ? r.status() : "keine Antwort"} (Bau ohne Themenseiten?)`);
    } else {
      for (const profil of Object.keys(PROFILE)) {
        await einzeln(profil, "Übersicht", () => uebersicht(browser, profil));
        await einzeln(profil, "Themenseite", () => themenseite(browser, profil));
        await einzeln(profil, "Zeitleiste", () => zeitleiste(browser, profil));
      }
      await einzeln("1440", "Links in die Karte", () => kartenLinks(browser, "1440"));
    }
  } catch (e) {
    pruefen("-", "Ablauf", false, String(e && e.stack || e).slice(0, 800));
  }
  await browser.close();
  if (AUSGABE) fs.writeFileSync(AUSGABE, JSON.stringify({ ergebnisse }, null, 1));
  console.log(`${befunde} Befunde`);
  process.exit(befunde ? 1 : 0);
})();
