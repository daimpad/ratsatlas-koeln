// Browserprüfung der Bedienung mit Testdaten (Runde 18): Suchtreffer mit aria-current "true"/"false", Menü ☰ über
// offenen Überlagerungen (Telefon), Themen-Chips ohne Zahl bei „ganz Köln“, Tour ohne abgeschaltete Funktionen,
// Hinweis zu Baustellen in der Zeitleiste nur mit Baustellen, „Weitere … anzeigen“ ohne Neuzeichnen der Karte; dazu
// axe-core (WCAG 2.1 A/AA) in den geprüften Zuständen. Punktzahl und Termine je Gebiet stehen in der Ausgabe (Vergleich
// zweier Fassungen der Seite mit denselben Daten). Prüfung r20: Profile „desktop-csp“ und „telefon-csp“ ohne
// bypassCSP (wie die veröffentlichte Seite): Verstöße gegen die Content-Security-Policy in den üblichen Abläufen und auf
// den Unterseiten, axe per page.evaluate, auf dem Telefon das Blatt „Karte“ über „Los geht's“.
// Nur die lokale Seite: Anfragen an andere Hosts werden abgebrochen.
// Aufruf (Seite mit Testdaten, z. B. python3 tools/testdaten.py, Pipeline, tools/seite_bauen.py, dann
//   python3 -m http.server --bind 127.0.0.1 8790 -d _site):
//   NODE_PATH=<…/node_modules mit playwright> AXE_PFAD=<…/axe.min.js> node tests/browser/bedienung.js http://127.0.0.1:8790/ [ergebnis.json]
// Ausgabe: je Prüfung eine Zeile; Exit-Code 1 bei einem Befund.
const { chromium } = require("playwright");
const fs = require("fs");
const BASIS = process.argv[2] || "http://127.0.0.1:8790/";
const AUSGABE = process.argv[3];
const AXE = process.env.AXE_PFAD ? fs.readFileSync(process.env.AXE_PFAD, "utf8") : null;
// Wörter, die in der Tour mit den Kölner Freigaben (index.json meta.funktionen) nicht vorkommen dürfen
const ABGESCHALTET = ["Baustelle", "Einfache Sprache", "Einfacher Sprache", "Zuschussbedarf", "Alle Wege im Überblick",
  "Bürgerantrag", "Prozesse", "Assistent", "Haushalt", "Themenseiten"];
const PROFILE = {
  desktop: { viewport: { width: 1400, height: 900 } },
  telefon: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};
const ergebnisse = [], vergleich = {};
let befunde = 0;
const pruefen = (profil, name, ok, angaben) => {
  ergebnisse.push({ profil, name, ok: Boolean(ok), angaben });
  if (!ok) befunde++;
  console.log(`${ok ? "ok  " : "FEHL"} ${profil} ${name}${angaben === undefined ? "" : " " + JSON.stringify(angaben)}`);
};
const axe = async (page) => {
  if (!AXE) return null;
  await page.addScriptTag({ content: AXE });
  const r = await page.evaluate(async () => await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }));
  return r.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
};
const geladen = (page) => page.waitForFunction(() => {
  const c = document.getElementById("count");
  return c && c.textContent.trim() && !/^Lade/.test(c.textContent) && document.getElementById("f-area").options.length > 1;
}, null, { timeout: 30000 });
const aktuell = (page) => page.$$eval("#papers button[data-gref], #papers button[data-ref]",
  (bs) => bs.map((b) => [b.dataset.gref || b.dataset.ref, b.getAttribute("aria-current")]));

async function neueSeite(browser, profil, mitCsp = false) {
  // ohne CSP-Prüfung axe als Skript einfügen (bypassCSP); mit CSP-Prüfung wie die veröffentlichte Seite
  const ctx = await browser.newContext({ ...PROFILE[profil], bypassCSP: !mitCsp });
  const page = await ctx.newPage();
  const fehler = [];
  if (mitCsp) await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fehler.push(`console: ${m.text()}`); });
  await page.route((u) => !u.href.startsWith(BASIS), (r) => r.abort());
  // Aufrufe an der Gruppe der Kartenpunkte zählen (Leaflet.markercluster; die Seite legt die Gruppe nach dem Laden an)
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      const P = window.L && window.L.MarkerClusterGroup && window.L.MarkerClusterGroup.prototype;
      if (!P) return;
      window.__karte = { aufrufe: 0, gruppe: null };
      for (const k of ["addLayer", "addLayers", "clearLayers", "removeLayer", "removeLayers"]) {
        const f = P[k];
        P[k] = function (...a) { window.__karte.gruppe = this; window.__karte.aufrufe++; return f.apply(this, a); };
      }
    });
  });
  return { ctx, page, fehler };
}

async function sucheUndAuswahl(browser, profil) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  // B3: bei „ganz Köln“ (kein Gebiet geladen) keine Zahlen an den Themen
  await page.click("#q");
  await page.waitForSelector("#chips-theme .chip");
  const chipsKoeln = await page.$$eval("#chips-theme .chip", (cs) => cs.map((c) => c.querySelector(".n")?.textContent ?? null));
  pruefen(profil, "Themen-Chips bei ganz Köln ohne Zahl", chipsKoeln.length > 0 && chipsKoeln.every((n) => n === null), chipsKoeln.slice(0, 3));
  // B1: Suche in ganz Köln, Treffer mit aria-current "false"
  await page.fill("#q", "Testdaten");
  await page.waitForFunction(() => document.querySelectorAll("#papers button[data-gref]").length > 0, null, { timeout: 20000 });
  await page.waitForTimeout(400);
  const vorher = await aktuell(page);
  pruefen(profil, "Suchtreffer aria-current false (ohne Auswahl)", vorher.length > 0 && vorher.every(([, a]) => a === "false"),
    { treffer: vorher.length, werte: [...new Set(vorher.map(([, a]) => a))] });
  await page.press("#q", "Enter");
  await page.waitForSelector("#panel-list:not([hidden]) #papers button[data-gref]");
  const axeSuche = await axe(page);
  if (axeSuche) pruefen(profil, "axe Suche", axeSuche.length === 0, axeSuche);
  const erster = page.locator("#papers button[data-gref]").first();
  const ref = await erster.getAttribute("data-gref"), gebiet = await erster.getAttribute("data-area");
  await erster.click();
  await page.waitForFunction((r) => location.hash === "#" + encodeURIComponent(r) && document.querySelector("#detail h3"), ref, { timeout: 20000 });
  await page.waitForTimeout(400);
  const nachher = await aktuell(page);
  const wahr = nachher.filter(([, a]) => a === "true");
  pruefen(profil, "nach Auswahl genau ein Treffer aria-current true", nachher.every(([, a]) => a === "true" || a === "false")
    && wahr.length === 1 && wahr[0][0] === ref, { ref, wahr, werte: [...new Set(nachher.map(([, a]) => a))], gebiet });
  // „Weitere … anzeigen“ baut die Liste neu auf: die Auswahl bleibt die einzige mit "true"
  if (await page.$("#papers #more")) {
    await weitere(page, profil);
    const mehr = await aktuell(page);
    const w = mehr.filter(([, a]) => a === "true");
    pruefen(profil, "nach „Weitere anzeigen“ weiter genau ein true", w.length === 1 && w[0][0] === ref && mehr.every(([, a]) => a === "true" || a === "false"), { treffer: mehr.length });
  } else pruefen(profil, "„Weitere anzeigen“ vorhanden", false);
  if (profil === "telefon") await page.click('.toggle[data-panel="panel-list"]', { force: true }).catch(() => {});
  const axeAuswahl = await axe(page);
  if (axeAuswahl) pruefen(profil, "axe Suche mit Auswahl", axeAuswahl.length === 0, axeAuswahl);
  pruefen(profil, "keine Skriptfehler (Suche)", fehler.length === 0, fehler);
  await ctx.close();
  return gebiet;
}

const weitere = async (page, profil) => {
  if (profil === "telefon") await page.evaluate(() => document.querySelector("#papers #more").click());
  else await page.click("#papers #more");
  await page.waitForTimeout(300);
};
// Stadtteil mit den meisten Punkten in vorlagen.geojson (Testdaten): dort zeigt die Karte Punkte
const gebietMitPunkten = (page) => page.evaluate(async () => {
  const [g, idx] = await Promise.all(["vorlagen.geojson", "index.json"].map(async (d) => (await fetch("data/export/koeln/" + d)).json()));
  const n = {};
  for (const f of g.features) if (f.properties.ortsteil) n[f.properties.ortsteil] = (n[f.properties.ortsteil] || 0) + 1;
  const name = Object.keys(n).sort((a, b) => n[b] - n[a] || a.localeCompare(b))[0];
  return "ortsteil:" + idx.ortsteile.find((o) => o.name === name).slug;
});

// B7: Suche in ganz Köln in einem Stadtteil mit Punkten; „Weitere … anzeigen“ erweitert nur die Liste (keine Aufrufe an
// der Gruppe der Kartenpunkte, gleiche Punktzahl)
async function weitereOhneKarte(browser, profil, gebiet) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.fill("#q", "Testdaten");
  // erst nach der verzögerten Suche (200 ms): sie öffnet das Suchmenü und schließt auf dem Telefon die Liste
  await page.waitForFunction(() => document.querySelectorAll("#papers button[data-gref]").length > 0, null, { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.press("#q", "Enter");
  await page.waitForSelector("#panel-list:not([hidden]) #papers #more");
  await page.waitForTimeout(400);
  const vor = await page.evaluate(() => { const k = window.__karte; const n = k.gruppe.getLayers().length; k.aufrufe = 0; return n; });
  await weitere(page, profil);
  const nach = await page.evaluate(() => ({ aufrufe: window.__karte.aufrufe, punkte: window.__karte.gruppe.getLayers().length,
    liste: document.querySelectorAll("#papers button[data-gref]").length }));
  pruefen(profil, "„Weitere anzeigen“ zeichnet die Karte nicht neu (gleiche Punktzahl)", vor > 0 && nach.aufrufe === 0 && nach.punkte === vor && nach.liste > 50,
    { gebiet, punkte: [vor, nach.punkte], aufrufe: nach.aufrufe, liste: nach.liste });
  vergleich[profil + "_suche"] = { punkte: vor };
  pruefen(profil, "keine Skriptfehler (Weitere)", fehler.length === 0, fehler);
  await ctx.close();
}

async function gebietChipsUndZeitleiste(browser, profil, gebiet) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.click("#q");
  await page.waitForSelector("#chips-theme .chip");
  const n = await page.$$eval("#chips-theme .chip", (cs) => cs.map((c) => c.querySelector(".n")?.textContent ?? null));
  pruefen(profil, "Themen-Chips im Gebiet mit Zahl", n.length > 0 && n.every((x) => x !== null && /^\d+$/.test(x)) && n.some((x) => Number(x) > 0), { gebiet, n });
  await page.keyboard.press("Escape");
  // Punktzahl im Gebiet und Termine (alle Gremien) für den Vergleich zweier Fassungen
  const punkte = await page.evaluate(() => (window.__karte.gruppe ? window.__karte.gruppe.getLayers().length : null));
  await page.evaluate(() => document.getElementById("cta-termine").click());
  await page.waitForSelector("#termine .count");
  await page.selectOption("#termine-scope", "alle");
  await page.waitForTimeout(300);
  const termine = await page.$eval("#termine", (t) => ({ sitzungen: t.querySelectorAll(".meeting").length,
    tagesordnung: [...t.querySelectorAll(".agenda button[data-ref]")].map((b) => b.dataset.ref), text: t.innerText }));
  pruefen(profil, "Punkte und Termine im Gebiet", punkte > 0 && termine.sitzungen > 0, { gebiet, punkte, sitzungen: termine.sitzungen,
    tagesordnung: termine.tagesordnung.length });
  vergleich[profil] = { punkte, termine };
  await page.keyboard.press("Escape");
  const bau = await page.$$eval(".tl-bau-grenze", (ls) => ls.map((l) => l.hidden));
  pruefen(profil, "Zeitleiste: Hinweis zu Baustellen ausgeblendet (ohne Baustellen)", bau.length === 1 && bau[0] === true, bau);
  pruefen(profil, "keine Skriptfehler (Gebiet)", fehler.length === 0, fehler);
  await ctx.close();
}

// B6: Termine je Stadtbezirk und im Stadtteil der Suche (Gremien des Gebiets und alle Gremien), für den Vergleich
// zweier Fassungen der Seite mit denselben Daten; geprüft wird hier nur, dass Vorlagen auf Tagesordnungen erscheinen
async function termineJeGebiet(browser, profil, extra) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  const gebiete = [...(await page.evaluate(async () => (await (await fetch("data/export/koeln/index.json")).json()).bezirke
    .map((b) => "bezirk:" + b.slug))), extra];
  const termine = {};
  for (const gebiet of gebiete) {
    await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
    await geladen(page);
    await page.evaluate(() => document.getElementById("cta-termine").click());
    await page.waitForSelector("#termine .count");
    const lesen = () => page.$eval("#termine", (t) => ({ sitzungen: t.querySelectorAll(".meeting").length,
      tagesordnung: [...t.querySelectorAll(".agenda button[data-ref]")].map((b) => b.dataset.ref), text: t.innerText }));
    const eigene = await lesen();
    await page.selectOption("#termine-scope", "alle");
    await page.waitForTimeout(200);
    termine[gebiet] = { eigene, alle: await lesen() };
  }
  const n = Object.values(termine).reduce((a, t) => a + t.alle.tagesordnung.length, 0);
  pruefen(profil, "Termine mit Vorlagen auf der Tagesordnung", n > 0, { gebiete: gebiete.length, tagesordnung: n });
  vergleich[profil + "_termine"] = termine;
  pruefen(profil, "keine Skriptfehler (Termine)", fehler.length === 0, fehler);
  await ctx.close();
}

// B2: Telefon, Auswertung offen, dann Menü ☰: das Menü liegt oben; Esc schließt erst das Menü, dann die Auswertung
async function menueUeberAuswertung(browser, gebiet) {
  const profil = "telefon";
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.click("#nav-burger");
  await page.click('#nav-more [data-mega="mega-auswertung"]');
  await page.click('#mega-auswertung [data-open-tab="stats"]');
  await page.waitForSelector("#panel-auswertung:not([hidden])");
  await page.waitForTimeout(300);
  const zustand1 = await page.evaluate(() => {
    const h = document.getElementById("auswertung-heading").getBoundingClientRect();
    const oben = document.elementFromPoint(h.left + 10, h.top + h.height / 2);
    return { navOffen: document.body.classList.contains("nav-open"), auswertungOben: Boolean(oben && oben.closest("#panel-auswertung")) };
  });
  pruefen(profil, "Auswertung aus dem Menü geöffnet, Menü zu, Auswertung sichtbar", !zustand1.navOffen && zustand1.auswertungOben, zustand1);
  await page.click("#nav-burger");
  await page.waitForTimeout(300);
  const zustand2 = await page.evaluate(() => {
    // Hinweis „Testdaten“ (z-index 3000, nur mit Testdaten, nie veröffentlicht) liegt über dem unteren Rand des Blatts
    const hinweis = document.getElementById("testdaten-hinweis");
    if (hinweis) hinweis.hidden = true;
    const ziele = [...document.querySelectorAll("#nav-more .menu-btn, #nav-more .toggle, #f-area")].filter((e) => !e.hidden && e.getClientRects().length);
    const verdeckt = ziele.filter((e) => {
      e.scrollIntoView({ block: "nearest" });   // das Blatt scrollt (max-height); unten liegende Einträge zuerst zeigen
      const r = e.getBoundingClientRect();
      const oben = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !(oben && (oben === e || e.contains(oben)));
    }).map((e) => e.id || e.dataset.mega || e.dataset.panel);
    return { navOffen: document.body.classList.contains("nav-open"), ziele: ziele.length, verdeckt, auswertungOffen: !document.getElementById("panel-auswertung").hidden };
  });
  pruefen(profil, "Menü ☰ über der offenen Auswertung (kein Eintrag verdeckt)", zustand2.navOffen && zustand2.auswertungOffen && zustand2.ziele > 3 && zustand2.verdeckt.length === 0, zustand2);
  const axeMenue = await axe(page);
  if (axeMenue) pruefen(profil, "axe Menü über Auswertung", axeMenue.length === 0, axeMenue);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  const zustand3 = await page.evaluate(() => ({ navOffen: document.body.classList.contains("nav-open"), fokus: document.activeElement.id,
    auswertungOffen: !document.getElementById("panel-auswertung").hidden }));
  pruefen(profil, "Esc schließt zuerst das Menü (Fokus auf ☰), Auswertung bleibt", !zustand3.navOffen && zustand3.fokus === "nav-burger" && zustand3.auswertungOffen, zustand3);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  const zustand4 = await page.evaluate(() => ({ auswertungOffen: !document.getElementById("panel-auswertung").hidden }));
  pruefen(profil, "zweites Esc schließt die Auswertung", !zustand4.auswertungOffen, zustand4);
  pruefen(profil, "keine Skriptfehler (Menü)", fehler.length === 0, fehler);
  await ctx.close();
}

// Prüfung r20: ohne bypassCSP. Verstöße gegen die CSP je Ablauf (Start, Gebiet mit Liste, Vorgang, Zeitleiste und
// allen Ebenen, Menüs, ?mitmachen=1, Unterseiten); axe per page.evaluate (läuft auch unter der CSP, addScriptTag nicht)
const cspVerstoesse = (page) => page.evaluate(() => window.__csp || []);
const axeOhneBypass = async (page) => {
  if (!AXE) return null;
  await page.evaluate(AXE);
  const r = await page.evaluate(async () => await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }));
  return r.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
};

async function cspDesktop(browser, gebiet) {
  const profil = "desktop-csp";
  const { ctx, page, fehler } = await neueSeite(browser, "desktop", true);
  const verstoesse = [];
  const sammeln = async (wo) => { for (const v of await cspVerstoesse(page)) verstoesse.push(`${wo}: ${v}`); };
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await sammeln("Start");
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.click('.toggle[data-panel="panel-list"]');
  await page.waitForSelector("#panel-list:not([hidden]) #papers li button");
  await page.click("#papers li button");
  await page.waitForSelector("#detail h3", { timeout: 20000 });
  await page.click('.toggle[data-panel="timeline-wrap"]');
  await page.waitForTimeout(300);
  await page.evaluate(() => document.querySelector(".map-menu").click());   // die Zeitleiste kann „Ebenen“ verdecken
  await page.evaluate(async () => {
    for (const t of document.querySelectorAll(".leaflet-right .map-style:not(.map-menu):not(.map-whole)")) {
      if (t.offsetParent) { t.click(); await new Promise((r) => setTimeout(r, 150)); }
    }
  });
  await page.waitForTimeout(1500);
  await sammeln("Gebiet, Liste, Vorgang, Zeitleiste, alle Ebenen");
  for (const m of ["mega-auswertung", "mega-mitmachen", "mega-daten", "mega-verstehen"]) {
    await page.evaluate((m) => { const b = document.querySelector(`[data-mega="${m}"]`); if (b && b.offsetParent) b.click(); }, m);
    await page.waitForTimeout(200);
  }
  await sammeln("Menüs");
  const axeCsp = await axeOhneBypass(page);
  if (axeCsp) pruefen(profil, "axe unter der CSP (Gebiet, Vorgang, Zeitleiste, Ebenen, Menü)", axeCsp.length === 0, axeCsp);
  await page.goto(`${BASIS}?mitmachen=1`, { waitUntil: "load" });
  await geladen(page);
  await sammeln("?mitmachen=1");
  const slug = gebiet.split(":")[1];
  const bezirk = await page.evaluate(async () => (await (await fetch("data/export/koeln/index.json")).json()).bezirke[0].slug);
  const status = {};
  for (const s of ["gebiete/", "begriffe/", "rss/", "technik/", "datenschutz.html", `ortsteil/${slug}/`, `stadtbezirk/${bezirk}/`, "404.html"]) {
    const r = await page.goto(BASIS + s, { waitUntil: "load" });
    await page.waitForTimeout(200);
    status[s] = r ? r.status() : null;
    await sammeln(s);
  }
  pruefen(profil, "Unterseiten geladen", Object.values(status).every((c) => c === 200), status);
  pruefen(profil, "keine Verstöße gegen die Content-Security-Policy", verstoesse.length === 0, verstoesse.slice(0, 10));
  pruefen(profil, "keine Skriptfehler (CSP)", fehler.length === 0, fehler);
  await ctx.close();
}

// Telefon: „Los geht's“ offen, „Karte“ antippen: das Blatt liegt oben („Schließen“ trifft sich selbst), die Fläche ist
// zu; ebenso mit allen Legenden offen und ans Ende gerollt (vorher verdeckte „Detail einklappen“ das „Schließen“)
async function blattKarte(browser) {
  const profil = "telefon-csp";
  const { ctx, page, fehler } = await neueSeite(browser, "telefon", true);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const start = await page.evaluate(() => ({ detail: !document.getElementById("panel-detail").hidden,
    titel: document.getElementById("detail-heading").textContent.trim().slice(0, 40) }));
  const frei = () => page.evaluate(() => {
    const zu = document.querySelector(".map-sheet-zu");
    const r = zu.getBoundingClientRect();
    const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { blatt: document.getElementById("map").classList.contains("map-menu-open"), zuFrei: Boolean(t && (t === zu || zu.contains(t))),
      getroffen: t ? String(t.id || t.getAttribute("class") || t.tagName).slice(0, 40) : null, detailZu: document.getElementById("panel-detail").hidden };
  });
  let geklickt = true;
  await page.click(".map-menu", { timeout: 5000 }).catch(() => { geklickt = false; });
  await page.waitForTimeout(400);
  const offen = await frei();
  pruefen(profil, "Blatt „Karte“ über „Los geht's“: Schließen frei, Fläche zu", start.detail && geklickt && offen.blatt && offen.zuFrei && offen.detailZu,
    { start, geklickt, offen });
  await page.evaluate(() => document.querySelectorAll("#map-sheet details").forEach((d) => { d.open = true; }));
  await page.waitForTimeout(300);
  await page.evaluate(() => { const s = document.getElementById("map-sheet"); s.scrollTop = s.scrollHeight; });
  await page.waitForTimeout(300);
  const gerollt = await frei();
  pruefen(profil, "Blatt „Karte“ mit allen Legenden, gerollt: Schließen frei", gerollt.blatt && gerollt.zuFrei && gerollt.detailZu, gerollt);
  const axeBlatt = await axeOhneBypass(page);
  if (axeBlatt) pruefen(profil, "axe unter der CSP (Blatt „Karte“)", axeBlatt.length === 0, axeBlatt);
  let zu = true;
  await page.click(".map-sheet-zu", { timeout: 5000 }).catch(() => { zu = false; });
  await page.waitForTimeout(300);
  const danach = await page.evaluate(() => ({ blatt: document.getElementById("map").classList.contains("map-menu-open"),
    fokus: document.activeElement.className }));
  pruefen(profil, "Schließen schließt das Blatt, Fokus auf „Karte“", zu && !danach.blatt && /map-menu/.test(danach.fokus), danach);
  const v = await cspVerstoesse(page);
  pruefen(profil, "keine Verstöße gegen die Content-Security-Policy", v.length === 0, v);
  pruefen(profil, "keine Skriptfehler (Blatt)", fehler.length === 0, fehler);
  await ctx.close();
}

// B4: Tour mit den Kölner Freigaben (Datenbetrieb, vorschau=false): keine abgeschaltete Funktion, ohne Fehler bis zum Ende
async function tour(browser, profil) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  const meta = await page.evaluate(async () => (await (await fetch("data/export/koeln/index.json")).json()).meta);
  await page.evaluate(() => document.querySelector("#mega-verstehen [data-tour]").click());
  await page.waitForSelector(".tour-card");
  const schritte = [];
  for (let k = 0; k < 40; k++) {
    await page.waitForFunction(() => !document.querySelector(".tour") || !/^Einen Moment/.test(document.getElementById("tour-text").textContent), null, { timeout: 20000 });
    if (!(await page.$(".tour"))) break;
    const s = await page.evaluate(() => ({ zahl: document.getElementById("tour-count").textContent, titel: document.getElementById("tour-title").textContent,
      text: document.getElementById("tour-text").textContent }));
    if (schritte.length && schritte[schritte.length - 1].zahl === s.zahl) { await page.waitForTimeout(200); continue; }
    schritte.push(s);
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
  }
  const genannt = schritte.flatMap((s) => ABGESCHALTET.filter((w) => (s.titel + " " + s.text).includes(w)).map((w) => `${s.titel}: ${w}`));
  pruefen(profil, "Tour mit Kölner Freigaben ohne abgeschaltete Funktion", meta.vorschau === false && !(await page.$(".tour")) && schritte.length > 8 && genannt.length === 0,
    { vorschau: meta.vorschau, schritte: schritte.length, genannt, flaechen: (schritte.find((s) => s.titel === "Flächen ein- und ausklappen") || {}).text });
  pruefen(profil, "keine Skriptfehler (Tour)", fehler.length === 0, fehler);
  await ctx.close();
  return schritte;
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });
  const touren = {};
  try {
    for (const profil of ["desktop", "telefon"]) {
      const gebiet = await sucheUndAuswahl(browser, profil);
      const { ctx, page } = await neueSeite(browser, profil);
      await page.goto(BASIS, { waitUntil: "load" });
      const mitPunkten = await gebietMitPunkten(page);
      await ctx.close();
      await weitereOhneKarte(browser, profil, mitPunkten);
      await gebietChipsUndZeitleiste(browser, profil, mitPunkten);
      if (profil === "desktop") await termineJeGebiet(browser, profil, gebiet);
      if (profil === "telefon") await menueUeberAuswertung(browser, gebiet);
      touren[profil] = await tour(browser, profil);
      if (profil === "desktop") await cspDesktop(browser, mitPunkten);
      if (profil === "telefon") await blattKarte(browser);
    }
  } catch (e) {
    pruefen("-", "Ablauf", false, String(e && e.stack || e).slice(0, 600));
  }
  await browser.close();
  if (AUSGABE) fs.writeFileSync(AUSGABE, JSON.stringify({ ergebnisse, touren, vergleich }, null, 1));
  console.log(`${befunde} Befunde`);
  process.exit(befunde ? 1 : 0);
})();
