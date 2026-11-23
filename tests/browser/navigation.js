// Browserprüfung der Navigation (Pull Request 3, Entscheidungen 19.11.2026 (1) und 20.11.2026 (7)) mit Testdaten bei
// 1440×900, 1024×768 und auf dem iPhone 13: Reihenfolge und Beschriftung der Leiste, Inhalt der Menüs ohne „folgt“,
// Startfenster mit „Aktuell in Köln“ (vergangene Sitzungen nach dem Tag in Köln ausgeblendet, Karte fehlt bei
// ausgesetzter Liste, Hinweis bei nicht aktuellen Daten), Hinweise zum Stand aus dem Sitzungsnamen in „Kommende
// Sitzungen“, Vorgang (fester Text bei leerem Ortsnamen, Gremium mit Kennung als Link, seit Pull Request 4b; die Fläche
// „Gremien und Ämter“ prüft tests/browser/gremien.js), Wege zurück, Fokus nach dem Schließen,
// Escape, Tab-Reihenfolge, Wortmarke und Seitentitel, Kartenvorschau, Fokus nach dem Schließen einer Fläche, die aus
// „Los geht's“ oder dem Vorgang geöffnet wurde (auch auf dem Telefon), title der Menü-Schaltflächen; dazu axe-core
// (WCAG 2.1 A/AA) in jedem dieser Zustände und Bildschirmfotos (Umgebungsvariable FOTOS). Abweichende Daten (Absage
// im Namen, ausgesetzte Liste, leerer Ortsname, Vorschau) setzt die Prüfung nur im Browser über page.route ein; die
// Dateien bleiben unverändert.
// Nur die lokale Seite: Anfragen an andere Hosts werden abgebrochen.
// Aufruf (Seite mit Testdaten, z. B. python3 tools/testdaten.py, Pipeline, tools/seite_bauen.py, dann
//   python3 -m http.server --bind 127.0.0.1 8790 -d _site):
//   NODE_PATH=<…/node_modules mit playwright> AXE_PFAD=<…/axe.min.js> FOTOS=<Ordner> node tests/browser/navigation.js http://127.0.0.1:8790/ [ergebnis.json]
// Ausgabe: je Prüfung eine Zeile; Exit-Code 1 bei einem Befund.
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");
const BASIS = process.argv[2] || "http://127.0.0.1:8790/";
const AUSGABE = process.argv[3];
const FOTOS = process.env.FOTOS || null;
const AXE = process.env.AXE_PFAD ? fs.readFileSync(process.env.AXE_PFAD, "utf8") : null;
const PROFILE = {
  1440: { viewport: { width: 1440, height: 900 } },
  1024: { viewport: { width: 1024, height: 768 } },
  iphone13: devices["iPhone 13"],
};
const MENUES = [["mega-themen", "Themen"], ["mega-entscheiden", "Wer entscheidet"], ["mega-mitmachen", "Mitmachen"], ["mega-ueber", "Über"]];
const FOLGT = /\bfolg(t|en)\b/i;
const LEERER_ORT = "Ortsangabe der Stadt ohne Kölner Stadtteil";
const tagInKoeln = (d) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" }).format(d);
const plusTage = (tag, n) => new Date(Date.parse(tag + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);

const ergebnisse = [];
let befunde = 0;
const pruefen = (profil, name, ok, angaben) => {
  ergebnisse.push({ profil, name, ok: Boolean(ok), angaben });
  if (!ok) befunde++;
  console.log(`${ok ? "ok  " : "FEHL"} ${profil} ${name}${angaben === undefined ? "" : " " + JSON.stringify(angaben)}`);
};
const axe = async (page, profil, zustand) => {
  if (!AXE) return;
  await page.addScriptTag({ content: AXE });
  const r = await page.evaluate(async () => await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }));
  const v = r.violations.map((x) => `${x.id} (${x.nodes.length}): ${x.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`);
  pruefen(profil, `axe ${zustand}`, v.length === 0, v);
};
const foto = async (page, name, wo) => {
  if (!FOTOS) return;
  if (wo) await (await page.$(wo)).screenshot({ path: path.join(FOTOS, `${name}.png`) });
  else await page.screenshot({ path: path.join(FOTOS, `${name}.png`) });
};
const geladen = (page) => page.waitForFunction(() => {
  const c = document.getElementById("count");
  return c && c.textContent.trim() && !/^Lade/.test(c.textContent) && document.getElementById("f-area").options.length > 1
    && document.getElementById("detail").textContent.trim();
}, null, { timeout: 30000 });

async function neueSeite(browser, profil, aenderungen = {}, zeitpunkt = null) {
  const ctx = await browser.newContext({ ...PROFILE[profil], bypassCSP: true });
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fehler.push(`console: ${m.text()}`); });
  await page.route((u) => !["127.0.0.1", "localhost"].includes(u.hostname), (r) => r.abort());
  // Daten nur im Browser ändern: { "index.json": (j) => j, … } (Pfad unter data/export/koeln/)
  for (const [datei, f] of Object.entries(aenderungen)) {
    await page.route((u) => u.pathname.endsWith(`/data/export/koeln/${datei}`), async (route) => {
      const r = await route.fetch();
      await route.fulfill({ response: r, json: f(await r.json()) });
    });
  }
  if (zeitpunkt) await page.clock.setFixedTime(zeitpunkt);
  // Hinweis „Testdaten“ (nur mit Testdaten, nie veröffentlicht; z-index 3000) liegt auf dem Telefon über dem Blatt ☰
  await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
    const h = document.getElementById("testdaten-hinweis");
    if (h) h.style.display = "none";
  }));
  return { ctx, page, fehler };
}
const telefon = (profil) => profil === "iphone13";
// Menü öffnen wie Besucher:innen: auf dem Telefon zuerst ☰
async function menueOeffnen(page, profil, mega) {
  if (telefon(profil) && !(await page.evaluate(() => document.body.classList.contains("nav-open")))) await page.click("#nav-burger");
  await page.click(`.nav-group [data-mega="${mega}"]`);
  await page.waitForSelector(`#${mega}:not([hidden])`);
  await page.waitForTimeout(250);
}
const sichtbareMenues = (page) => page.$$eval('.nav-group[aria-label="Menü"] .menu-btn', (bs) => bs.filter((b) => !b.hidden)
  .map((b) => [b.dataset.mega, b.querySelector("span").textContent.trim()]));
const fokus = (page) => page.evaluate(() => {
  const e = document.activeElement, cs = getComputedStyle(e);
  return { tag: e.tagName.toLowerCase(), id: e.id, mega: e.dataset.mega || null, klasse: e.className || "",
    text: (e.getAttribute("aria-label") || e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 50),
    sichtbar: e.getClientRects().length > 0, rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none" };
});

// 1, 2, 3, 7: Leiste, Menüs, Startfenster; axe und Fotos
async function leisteUndMenues(browser, profil) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(500);
  const start = await page.evaluate(() => ({ titel: document.getElementById("detail-heading").textContent,
    aktuell: Boolean(document.getElementById("aktuell")), offen: document.getElementById("aktuell")?.open, karten: [...document.querySelectorAll("#aktuell .akt-h")].map((h) => h.textContent.trim()),
    sitzungen: document.querySelectorAll("#aktuell .akt-sitzung").length, text: document.getElementById("detail").innerText }));
  pruefen(profil, "Startfenster: Kölner Untertitel und „Aktuell in Köln“ mit zwei Karten", start.titel === "Los geht's"
    && start.text.includes("Was Rat, Ausschüsse und Bezirksvertretungen der Stadt Köln beraten – wo, wann und wer.")
    && start.karten.length === 2 && start.karten[0] === "Kommende Sitzungen" && start.karten[1].startsWith("Neu eingereicht")
    && start.sitzungen > 0 && start.sitzungen <= 3 && !FOLGT.test(start.text) && start.offen === !telefon(profil),
    { karten: start.karten, sitzungen: start.sitzungen, offen: start.offen });
  await foto(page, `start-${profil}`);
  // Telefon: „Aktuell in Köln“ eingeklappt; die Schaltfläche „Karte“ bleibt frei (Prüfung r20, tests/browser/bedienung.js)
  if (telefon(profil)) {
    const frei = await page.evaluate(() => { const b = document.querySelector(".map-menu"), r = b.getBoundingClientRect();
      const o = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return Boolean(o && (o === b || b.contains(o))); });
    pruefen(profil, "Telefon: Schaltfläche „Karte“ über „Los geht's“ frei", frei);
    await page.click("#aktuell > summary");
    await page.waitForTimeout(200);
    await foto(page, `start-aufgeklappt-${profil}`);
  }
  await axe(page, profil, "Start");
  if (telefon(profil)) await page.click("#nav-burger");
  const leiste = await sichtbareMenues(page);
  pruefen(profil, "Leiste: Themen, Wer entscheidet, Mitmachen, Über", JSON.stringify(leiste) === JSON.stringify(MENUES), leiste);
  // zwischen 901 und 1599 px nur Symbole: title nennt Name und Inhalt beim Überfahren mit der Maus (Prüfung von PR 3)
  const titel = await page.$$eval('.nav-group[aria-label="Menü"] .menu-btn', (bs) => bs.filter((b) => !b.hidden).map((b) => b.title));
  pruefen(profil, "Menü-Schaltflächen mit title", titel.length === 4 && titel.every((t, i) => t.startsWith(`${MENUES[i][1]}: `)), titel);
  if (!telefon(profil)) await foto(page, `leiste-${profil}`, ".nav");
  else { await foto(page, `leiste-${profil}`); await page.click("#nav-burger"); }
  const inhalte = {};
  for (const [mega, name] of MENUES) {
    await menueOeffnen(page, profil, mega);
    const m = await page.$eval(`#${mega}`, (el) => ({ text: el.innerText, karten: [...el.querySelectorAll(".card")].filter((c) => c.getClientRects().length)
      .map((c) => c.querySelector(".card-title").textContent.trim()), chips: el.querySelectorAll(".chip").length }));
    inhalte[name] = m.karten;
    pruefen(profil, `Menü „${name}“ ohne „folgt“ und ohne leere Karte`, !FOLGT.test(m.text) && m.karten.length > 0, m.karten);
    await foto(page, `menue-${mega.slice(5)}-${profil}`);
    await axe(page, profil, `Menü „${name}“`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
    const zu = await page.evaluate((id) => document.getElementById(id).hidden, mega);
    const f = await fokus(page);
    pruefen(profil, `Menü „${name}“: Esc schließt, Fokus auf der Schaltfläche`, zu && f.mega === mega && f.sichtbar, f);
    if (telefon(profil)) await page.keyboard.press("Escape");
  }
  pruefen(profil, "Inhalt der Menüs", JSON.stringify(inhalte["Wer entscheidet"]) === '["Gremien","Ämter","Verfahrenswege in Zahlen"]'
    && inhalte.Themen[0] === "Kennzahlen zum Gebiet" && inhalte.Themen.length === 1
    && JSON.stringify(inhalte.Mitmachen) === '["Aktuell in Köln","Kommende Sitzungen","Selbst mitwirken","Informiert bleiben"]'
    && JSON.stringify(inhalte["Über"]) === JSON.stringify(["Einfache Sprache", "Begriffe erklärt", "Tour durch alle Funktionen",
      "Über den Ratsatlas", "Wie verlässlich sind die Angaben?", "So funktioniert der Ratsatlas", "Was ist neu?", "Hinweis geben",
      "Datenpaket (Zip)", "Verortete Vorlagen (GeoJSON)", "Datensatzbeschreibung (DCAT-AP)", "Feeds abonnieren und einbinden"]), inhalte);
  // „Aktuell anzeigen“ im Menü „Mitmachen“ führt zu „Los geht's“, Fokus auf „Aktuell in Köln“
  await menueOeffnen(page, profil, "mega-mitmachen");
  await page.click('#mega-mitmachen [data-home="aktuell"]');
  await page.waitForTimeout(300);
  const f = await fokus(page);
  const auf = await page.evaluate(() => document.getElementById("aktuell").open);
  pruefen(profil, "„Aktuell anzeigen“: Startfenster, „Aktuell in Köln“ aufgeklappt, Fokus darauf", auf && f.tag === "summary"
    && f.text.startsWith("Aktuell in Köln") && f.sichtbar, f);
  pruefen(profil, "keine Skriptfehler (Leiste und Menüs)", fehler.length === 0, fehler);
  await ctx.close();
}

// 5, 7: Tab-Reihenfolge, Fokus nach dem Schließen von Flächen und Fenstern, Wortmarke und Seitentitel
async function tastatur(browser, profil) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(500);
  const folge = [];
  for (let i = 0; i < 14; i++) { await page.keyboard.press("Tab"); folge.push(await fokus(page)); }
  if (!telefon(profil)) {
    const menues = folge.filter((f) => f.mega && f.mega !== "mega-suche").map((f) => f.mega);
    const ersterFokus = folge[0];
    pruefen(profil, "Tab: Wortmarke, Suche, Gebiet, Flächen, dann die vier Menüs in ihrer Reihenfolge, sichtbarer Fokus",
      ersterFokus.klasse === "brand" && folge[1].id === "q" && folge.some((f) => f.id === "f-area")
      && JSON.stringify(menues.slice(0, 4)) === JSON.stringify(MENUES.map(([m]) => m)) && folge.every((f) => f.sichtbar && f.rahmen),
      folge.map((f) => f.id || f.mega || f.klasse || f.tag));
    // Wortmarke: zugänglicher Name auch zwischen 901 und 1100 px
    const marke = await page.getByRole("link", { name: "Ratsatlas Köln: zu „Los geht's“", exact: true }).count();
    const breite = await page.$eval(".brand .ort", (e) => e.getBoundingClientRect().width);
    pruefen(profil, "Wortmarke: ein sichtbarer Link mit Namen „Ratsatlas Köln: zu „Los geht's““", marke === 1
      && (profil === "1024" ? breite <= 1 : breite > 10), { marke, breite });
  } else {
    pruefen(profil, "Tab: zuerst der Seitentitel (Link zu „Los geht's“), sichtbar mit Rahmen", /titel-link/.test(folge[0].klasse)
      && folge[0].sichtbar && folge[0].rahmen && folge[0].text.startsWith("Ratsatlas Köln: zu"), folge[0]);
  }
  // Themen → Kennzahlen: Esc schließt „In Zahlen“, Fokus auf „Themen“ (Telefon: ☰)
  const zurueck = async (mega, karte, flaeche, name) => {
    await menueOeffnen(page, profil, mega);
    await page.focus(karte);
    await page.keyboard.press("Enter");
    await page.waitForSelector(`#${flaeche}:not([hidden])`);
    await page.waitForTimeout(250);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(250);
    const f = await fokus(page);
    const erwartet = telefon(profil) ? "nav-burger" : mega;
    pruefen(profil, `${name}: Esc schließt, Fokus zurück`, await page.evaluate((id) => document.getElementById(id).hidden, flaeche)
      && (f.mega === erwartet || f.id === erwartet) && f.sichtbar, f);
  };
  await zurueck("mega-themen", '#mega-themen [data-open-tab="stats"]', "panel-auswertung", "Kennzahlen zum Gebiet");
  await zurueck("mega-entscheiden", '#mega-entscheiden [data-open-tab="wege"]', "panel-auswertung", "Verfahrenswege in Zahlen");
  // seit Pull Request 4b: Gremien und Ämter aus „Wer entscheidet“
  await zurueck("mega-entscheiden", '#mega-entscheiden [data-wer="gremien"]', "panel-gremien", "Gremien");
  await zurueck("mega-entscheiden", '#mega-entscheiden [data-wer="aemter"]', "panel-gremien", "Ämter");
  await zurueck("mega-mitmachen", "#cta-termine", "panel-termine", "Kommende Sitzungen");
  // Fenster „Über den Ratsatlas“ aus dem Menü „Über“: Esc schließt, Fokus auf „Über“ (Telefon: ☰)
  await menueOeffnen(page, profil, "mega-ueber");
  await page.focus("#about-open");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(250);
  const offen = await page.evaluate(() => document.getElementById("about").open);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250);
  const f = await fokus(page);
  pruefen(profil, "Fenster „Über“: öffnet aus dem Menü, Esc schließt, Fokus zurück", offen && (telefon(profil) ? f.id === "nav-burger" : f.mega === "mega-ueber") && f.sichtbar, f);
  // „Was ist neu?“ aus dem Fenster „Über“: danach Fokus ebenso zurück
  await menueOeffnen(page, profil, "mega-ueber");
  await page.click("#about-open");
  await page.click("#about [data-neu]");
  await page.waitForTimeout(250);
  const neu = await page.evaluate(() => [document.getElementById("about").open, document.getElementById("neu").open]);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250);
  const f2 = await fokus(page);
  pruefen(profil, "„Was ist neu?“ aus dem Fenster „Über“: Esc schließt, Fokus zurück", !neu[0] && neu[1]
    && (telefon(profil) ? f2.id === "nav-burger" : f2.mega === "mega-ueber"), f2);
  // Wortmarke bzw. Seitentitel führt zu „Los geht's“
  await page.click(telefon(profil) ? ".titel-link" : "a.brand");
  await page.waitForTimeout(300);
  const heim = await page.evaluate(() => ({ titel: document.getElementById("detail-heading").textContent, fokus: document.activeElement.id,
    adresse: location.href }));
  pruefen(profil, "Wortmarke/Seitentitel: „Los geht's“ ohne neues Laden", heim.titel === "Los geht's" && heim.fokus === "detail-heading"
    && heim.adresse.startsWith(BASIS), heim);
  // „Alle kommenden Sitzungen“ in „Los geht's“ → Esc: Fokus zurück auf den Auslöser; auf dem Telefon geht das Startfenster
  // dafür wieder auf (Prüfung von Pull Request 3: vorher lag der Fokus dort auf <body>)
  if (telefon(profil)) await page.click("#aktuell > summary");
  await page.focus("#aktuell [data-open-termine]");
  await page.keyboard.press("Enter");
  await page.waitForSelector("#panel-termine:not([hidden])");
  await page.waitForTimeout(250);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  const t = await page.evaluate(() => ({ ausloeser: document.activeElement.hasAttribute("data-open-termine"),
    start: !document.getElementById("panel-detail").hidden && document.getElementById("detail-heading").textContent === "Los geht's" }));
  pruefen(profil, "„Alle kommenden Sitzungen“ → Esc: „Los geht's“ offen, Fokus auf dem Auslöser", t.ausloeser && t.start, t);
  pruefen(profil, "keine Skriptfehler (Tastatur)", fehler.length === 0, fehler);
  await ctx.close();
}

// 3: vergangene Sitzungen nach dem Tag in Köln, ausgesetzte Liste, Hinweis zum Datenstand, „verschoben“, „Neu eingereicht“
async function startfenster(browser, profil, index) {
  const a = index.aktuell;
  const erster = a.sitzungen[0].date, amErsten = a.sitzungen.filter((m) => m.date === erster).length;
  // Besuch am Tag nach der ersten Sitzung (12 Uhr in Köln): deren Sitzungen sind vergangen
  let s = await neueSeite(browser, profil, {}, new Date(plusTage(erster, 1) + "T11:00:00Z"));
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  const tage = await s.page.$$eval("#aktuell .akt-sitzung .akt-cal b", (bs) => bs.map((b) => b.textContent));
  pruefen(profil, "vergangene Sitzungen nach dem Tag in Köln ausgeblendet", tage.length > 0 && !tage.includes(String(+erster.slice(8))),
    { erster, amErsten, tage });
  pruefen(profil, "keine Skriptfehler (Tag)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
  // Liste der Sitzungen ausgesetzt (index.json ohne Karte), Daten nicht aktuell: Hinweis, keine Karte „Kommende Sitzungen“
  s = await neueSeite(browser, profil, { "index.json": (j) => ({ ...j, aktuell: { vorlagen: j.aktuell.vorlagen },
    meta: { ...j.meta, abruf_ausgesetzt: { meetings: { seit: "2026-11-18T22:30:00+00:00", stand: "2026-11-17T22:30:00+00:00" } } } }) });
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  const aus = await s.page.evaluate(() => ({ hinweis: document.querySelector(".stand-hinweis")?.innerText || "",
    karten: [...document.querySelectorAll("#aktuell .akt-h")].map((h) => h.textContent.trim()) }));
  pruefen(profil, "ausgesetzte Liste: Karte fehlt, Hinweis zum Datenstand", aus.karten.length === 1 && aus.karten[0].startsWith("Neu eingereicht")
    && aus.hinweis.startsWith("Hinweis zum Datenstand:") && aus.hinweis.includes("Der Abruf der Sitzungstermine ruht seit dem 18.11.2026"), aus);
  await foto(s.page, `start-hinweis-${profil}`, "#panel-detail");
  await axe(s.page, profil, "Startfenster mit Hinweis zum Datenstand");
  await s.ctx.close();
  // „verschoben“ aus dem Namen: kurzer Hinweis ohne Namen; ohne `aktuell` (Vorschau-artig) keine Kachel im Menü
  s = await neueSeite(browser, profil, { "index.json": (j) => ({ ...j, aktuell: { ...j.aktuell,
    sitzungen: j.aktuell.sitzungen.map((m, i) => (i === 0 ? { ...m, hinweis: "verschoben" } : m)) } }) });
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  if (telefon(profil)) await s.page.click("#aktuell > summary");   // auf dem Telefon eingeklappt
  const v = await s.page.$eval("#aktuell .akt-sitzung", (li) => li.innerText);
  pruefen(profil, "„laut Sitzungsnamen verschoben“ in „Aktuell“", v.includes("laut Sitzungsnamen verschoben"), v.replace(/\s+/g, " "));
  // „Neu eingereicht“ öffnet den Vorgang im Gebiet der Vorlage (openGlobal), Fokus auf dem Titel
  const knopf = await s.page.$("#aktuell button.akt-open");
  const ziel = await knopf.evaluate((b) => ({ area: b.dataset.area, titel: b.querySelector(".akt-title").textContent }));
  await knopf.click();
  await s.page.waitForFunction((t) => document.querySelector("#detail h3")?.textContent === t, ziel.titel, { timeout: 20000 });
  await s.page.waitForTimeout(200);
  const g = await s.page.evaluate(() => ({ gebiet: document.getElementById("f-area").value, fokus: document.activeElement.tagName,
    zurueck: Boolean(document.querySelector("#detail [data-zurueck-liste]")) }));
  pruefen(profil, "„Neu eingereicht“ öffnet Gebiet und Vorgang, Fokus auf dem Titel", g.gebiet === ziel.area && g.fokus === "H3" && g.zurueck, { ...g, ziel });
  pruefen(profil, "keine Skriptfehler (Startfenster)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// 4: Hinweise zum Stand aus dem Sitzungsnamen in „Kommende Sitzungen“ und in der Zeitleiste
async function termine(browser, profil, heute) {
  let abgesagt = null, verschoben = null;
  const s = await neueSeite(browser, profil, { "zeit.json": (j) => {
    const kuenftig = j.meetings.filter((m) => m.date > heute && !m.cancelled);
    abgesagt = kuenftig[0]; verschoben = kuenftig[1];
    return { ...j, meetings: j.meetings.map((m) => (m === abgesagt ? { ...m, hinweis: "abgesagt", name: `${m.name} - Sitzung entfällt` }
      : m === verschoben ? { ...m, hinweis: "verschoben", name: `${m.name}\n-Sitzung ist auf einen späteren Tag verschoben worden!-` } : m)) };
  } });
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  await menueOeffnen(s.page, profil, "mega-mitmachen");
  await s.page.click("#cta-termine");
  await s.page.waitForSelector("#termine .count");
  await s.page.selectOption("#termine-scope", "alle");
  await s.page.waitForTimeout(250);
  const k = await s.page.$$eval("#termine .meeting", (ms) => ms.map((m) => ({ text: m.querySelector(".meeting-head").innerText.replace(/\s+/g, " "),
    durch: m.classList.contains("cancelled") })));
  const a = k.find((x) => x.text.includes("laut Sitzungsnamen abgesagt")), v = k.find((x) => x.text.includes("laut Sitzungsnamen verschoben"));
  pruefen(profil, "Kommende Sitzungen: Plakette „laut Sitzungsnamen abgesagt“ und Name bei „verschoben“", Boolean(a) && a.durch
    && !a.text.includes("entfällt") && Boolean(v) && !v.durch && v.text.includes("Sitzungsname: „") && v.text.includes("verschoben worden!-“")
    && k.filter((x) => x.text.includes("Sitzungsname: „")).length === 1, { a, v });
  if (!telefon(profil)) await foto(s.page, `termine-${profil}`, "#panel-termine");
  await axe(s.page, profil, "Kommende Sitzungen mit Hinweisen");
  pruefen(profil, "keine Skriptfehler (Termine)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// 5, 6: Gebiet mit „Zurück zu Köln“, Vorgang mit festem Text bei leerem Ortsnamen, Gremium mit Kennung als Link (seit
// Pull Request 4b; vorher ohne Link), „Zurück zur Liste“
async function gebietUndVorgang(browser, profil, gebiet) {
  const datei = `${gebiet.split(":")[0] === "ortsteil" ? "ortsteile" : "bezirke"}/${gebiet.split(":")[1]}.json`;
  let ref = null;
  const s = await neueSeite(browser, profil, { [datei]: (j) => {
    ref = j.papers[0].reference;
    j.papers[0].locations.unshift({ level: "strasse", name: null, ortsteil: null, stadtbezirk: null, lon: null, lat: null, stage: "A",
      method: "oparl_location", confidence: "niedrig", evidence: null, source_object: null });
    return j;
  } });
  await s.page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(s.page);
  await s.page.waitForTimeout(400);
  const intro = await s.page.evaluate(() => Boolean(document.querySelector("#detail [data-zurueck-koeln]")));
  pruefen(profil, "Startfenster eines Gebiets mit „Zurück zu Köln“", intro);
  await axe(s.page, profil, "Gebiet");
  await foto(s.page, `gebiet-${profil}`);
  // Liste, Vorgang
  if (telefon(profil)) await s.page.click("#nav-burger");
  await s.page.click('.toggle[data-panel="panel-list"]');
  await s.page.waitForSelector("#panel-list:not([hidden]) #papers li button");
  const liste = await s.page.evaluate(() => !document.getElementById("zurueck-koeln").hidden);
  await s.page.click(`#papers button[data-ref="${ref}"]`);
  await s.page.waitForSelector("#detail .steps");
  await s.page.waitForTimeout(400);
  const v = await s.page.evaluate(() => ({ orte: [...document.querySelectorAll("#detail .locs > li")].map((li) => li.innerText.replace(/\s+/g, " ")),
    leer: document.querySelector("#detail .locs").innerHTML.includes("<strong></strong>"), bonnLink: document.querySelectorAll("#detail [data-gremium-name]").length,
    gremienLink: document.querySelectorAll("#detail [data-gremium-key]").length, zurueck: Boolean(document.querySelector("#detail [data-zurueck-liste]")) }));
  // Testdaten: jede Station trägt eine Kennung (alle Gremien in gremien.json, nicht aufgelöst), also ein Link je Station
  pruefen(profil, "Vorgang: fester Text bei leerem Ortsnamen, Gremien mit Kennung als Link (kein Bonner Link), „Zurück zur Liste“", liste
    && v.orte.some((o) => o.startsWith(LEERER_ORT)) && !v.leer && v.bonnLink === 0 && v.gremienLink > 0 && v.zurueck, v);
  await foto(s.page, `vorgang-${profil}`);
  await axe(s.page, profil, "Vorgang");
  // „Alle Wege, sich einzubringen“ (Fläche „Mitmachen in Köln“) → Esc: Vorgang offen, Fokus auf dem Auslöser (auf dem
  // Telefon lag er vor der Prüfung von Pull Request 3 auf <body>)
  const wege = await s.page.$("#detail [data-mitmachen-oeffnen]");
  if (wege) {
    await wege.focus();
    await s.page.keyboard.press("Enter");
    await s.page.waitForSelector("#panel-mitmachen:not([hidden])");
    await s.page.waitForTimeout(300);
    await s.page.keyboard.press("Escape");
    await s.page.waitForTimeout(300);
  }
  const w = await s.page.evaluate(() => ({ ausloeser: document.activeElement.hasAttribute("data-mitmachen-oeffnen"),
    vorgang: !document.getElementById("panel-detail").hidden && Boolean(document.querySelector("#detail .steps")) }));
  pruefen(profil, "„Alle Wege, sich einzubringen“ → Esc: Vorgang offen, Fokus auf dem Auslöser", Boolean(wege) && w.ausloeser && w.vorgang, w);
  await s.page.click("#detail [data-zurueck-liste]");
  await s.page.waitForTimeout(300);
  const f = await fokus(s.page);
  const offen = await s.page.evaluate(() => !document.getElementById("panel-list").hidden);
  pruefen(profil, "„Zurück zur Liste“: Liste offen, Fokus auf der gewählten Vorlage", offen && f.sichtbar
    && (await s.page.evaluate(() => document.activeElement.getAttribute("aria-current"))) === "true", f);
  // „Zurück zu Köln“ aus der Liste: ganz Köln, Fokus auf der Überschrift der Liste
  await s.page.click("#zurueck-koeln [data-zurueck-koeln]");
  await s.page.waitForFunction(() => document.getElementById("f-area").value === "koeln:ganz", null, { timeout: 20000 });
  await s.page.waitForTimeout(300);
  const k = await s.page.evaluate(() => ({ fokus: document.activeElement.id, zurueck: !document.getElementById("zurueck-koeln").hidden,
    adresse: location.search }));
  pruefen(profil, "„Zurück zu Köln“: ganz Köln, Weg zurück verschwindet, Fokus in der Liste", k.fokus === "list-heading" && !k.zurueck
    && !k.adresse.includes("gebiet="), k);
  pruefen(profil, "keine Skriptfehler (Gebiet und Vorgang)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// 8: Kartenvorschau (index.json mit meta.vorschau, ohne `aktuell`): Menüs ohne Themen und Wer entscheidet, keine Kachel
// „Aktuell in Köln“ und „Kommende Sitzungen“, Startfenster ohne „Aktuell in Köln“
async function vorschau(browser, profil) {
  const s = await neueSeite(browser, profil, { "index.json": (j) => { const { aktuell, ...rest } = j; return { ...rest, meta: { ...j.meta, vorschau: true, testdaten: false } }; } });
  await s.page.goto(BASIS, { waitUntil: "load" });
  await s.page.waitForFunction(() => document.getElementById("detail").textContent.includes("Los geht") || document.getElementById("detail-heading").textContent === "Los geht's", null, { timeout: 30000 });
  await s.page.waitForTimeout(800);
  if (telefon(profil)) await s.page.click("#nav-burger");
  const leiste = await sichtbareMenues(s.page);
  if (telefon(profil)) {
    // Der Hinweis „Vorschau“ (z-index 3000, unten) lag auf dem Telefon über dem unteren Teil des Blatts ☰ (vor Pull
    // Request 3 über „Verstehen“ und „Über“); seitdem tritt er zurück, solange das Blatt offen ist (style.css)
    const verdeckt = await s.page.evaluate(() => [...document.querySelectorAll("#nav-more .menu-btn, #nav-more .toggle, #f-area")]
      .filter((e) => !e.hidden && e.getClientRects().length).filter((e) => { const r = e.getBoundingClientRect();
        const o = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !(o && (o === e || e.contains(o))); })
      .map((e) => e.dataset.mega || e.dataset.panel || e.id));
    pruefen(profil, "Kartenvorschau: kein Eintrag im Blatt ☰ verdeckt", verdeckt.length === 0, verdeckt);
    await s.page.click("#nav-burger");
  }
  await menueOeffnen(s.page, profil, "mega-mitmachen");
  const karten = await s.page.$$eval("#mega-mitmachen .card", (cs) => cs.filter((c) => c.getClientRects().length).map((c) => c.querySelector(".card-title").textContent));
  const text = await s.page.$eval("#mega-mitmachen", (m) => m.innerText);
  await s.page.keyboard.press("Escape");
  const start = await s.page.evaluate(() => ({ aktuell: Boolean(document.getElementById("aktuell")), hinweis: !document.getElementById("vorschau-hinweis").hidden }));
  pruefen(profil, "Kartenvorschau: Mitmachen und Über, ohne „Aktuell in Köln“ und „Kommende Sitzungen“", JSON.stringify(leiste) === JSON.stringify(MENUES.slice(2))
    && JSON.stringify(karten) === '["Selbst mitwirken","Informiert bleiben"]' && !FOLGT.test(text) && !start.aktuell && start.hinweis, { leiste, karten, start });
  await axe(s.page, profil, "Kartenvorschau");
  pruefen(profil, "keine Skriptfehler (Vorschau)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

async function begriffe(browser, profil) {
  const s = await neueSeite(browser, profil);
  const r = await s.page.goto(BASIS + "begriffe/", { waitUntil: "load" });
  pruefen(profil, "Seite „Begriffe“ geladen", r && r.status() === 200);
  await axe(s.page, profil, "Begriffe");
  await s.ctx.close();
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });
  try {
    const hilfe = await browser.newPage();
    await hilfe.route((u) => !["127.0.0.1", "localhost"].includes(u.hostname), (r) => r.abort());
    await hilfe.goto(BASIS, { waitUntil: "load" });
    const index = await hilfe.evaluate(async () => (await fetch("data/export/koeln/index.json")).json());
    // Stadtteil mit den meisten Vorlagen (Testdaten) für Gebiet und Vorgang
    const gebiet = "ortsteil:" + index.ortsteile.slice().sort((a, b) => b.count - a.count || a.slug.localeCompare(b.slug))[0].slug;
    await hilfe.close();
    const heute = tagInKoeln(new Date());
    for (const profil of Object.keys(PROFILE)) {
      await leisteUndMenues(browser, profil);
      await tastatur(browser, profil);
      await startfenster(browser, profil, index);
      await termine(browser, profil, heute);
      await gebietUndVorgang(browser, profil, gebiet);
      await vorschau(browser, profil);
      await begriffe(browser, profil);
    }
  } catch (e) {
    pruefen("-", "Ablauf", false, String(e && e.stack || e).slice(0, 800));
  }
  await browser.close();
  if (AUSGABE) fs.writeFileSync(AUSGABE, JSON.stringify({ ergebnisse }, null, 1));
  console.log(`${befunde} Befunde`);
  process.exit(befunde ? 1 : 0);
})();
