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
// Pull Request 5 der Navigation (Entscheidung 24.11.2026 (2), Punkte (a) bis (c)): Texte der Kartenvorschau in Tour und
// Liste ohne Ankündigung (1), Fokus nach dem Ende der Tour (2), Tab aus einem offenen Menü (3), Beschriftung der Leiste
// ab 1366 px mit Maßen bei 1366×768, 1440×900, 1536×864, 1600×900 und 1920×1080 (4), Eingabefelder mit 16 px Schrift
// und 44 px Höhe auf dem Telefon und bei 320×256 (5), Fokus nach Enter auf einem Suchtreffer in ganz Köln (6), Blätter
// „Vorlagen“ und „Vorgang“ bei geringer Höhe (320×256) (7), „Selbst mitwirken“ ohne benannten Bereich (8); axe in
// jedem neuen Zustand. Nach der Prüfung des Pull Requests: Suchmenü mit der Tastatur (Tab aus dem Suchfeld durch alle
// Bedienelemente, Schnellfilter behalten den Fokus), Leiste mit den Textabständen nach WCAG 1.4.12 und Platzhalter des
// Suchfelds (4, 5), Fokus eines Suchtreffers, wenn während des Ladens getippt wird (6).
// Kleiner UI-PR (Entscheidung 24.11.2026 (5), Punkte (1), (4) und (9)): Hinweis der Kartenvorschau und „Mitmachen in
// Köln“ ohne Termine ohne Ankündigung (1), Abschnitte im Vorgang ohne benannten Bereich (4), Tab durch die Menüs auf
// breiten Bildschirmen, Esc auf einem Schnellfilter im Suchmenü, Tab aus dem Blatt ☰ (9).
// Nur die lokale Seite: Anfragen an andere Hosts bricht jeder Browserkontext ab (ctx.route, auch aus neuen Fenstern;
// page.route erfasst diese nicht, und --no-proxy-server gilt nicht für die Kontexte von Playwright).
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
// 320×256 CSS-Pixel (etwa 400 % Zoom; nur für die Punkte 5 und 7 von Pull Request 5, nicht für die übrigen Prüfungen)
const ZUSATZPROFILE = { klein: { viewport: { width: 320, height: 256 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } };
const MENUES = [["mega-themen", "Themen"], ["mega-entscheiden", "Wer entscheidet"], ["mega-mitmachen", "Mitmachen"], ["mega-ueber", "Über"]];
const FOLGT = /\bfolg(t|en)\b/i;
const LEERER_ORT = "Ortsangabe der Stadt ohne Kölner Stadtteil";
const tagInKoeln = (d) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" }).format(d);
const plusTage = (tag, n) => new Date(Date.parse(tag + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);

const ergebnisse = [];
let befunde = 0, masseLeiste = null;
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

const nichtLokal = (u) => !["127.0.0.1", "localhost"].includes(u.hostname);
async function neueSeite(browser, profil, aenderungen = {}, zeitpunkt = null) {
  const ctx = await browser.newContext({ ...(PROFILE[profil] || ZUSATZPROFILE[profil]), bypassCSP: true });
  await ctx.route(nichtLokal, (r) => r.abort());
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fehler.push(`console: ${m.text()}`); });
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
  return { tag: e.tagName.toLowerCase(), id: e.id, mega: e.dataset.mega || null, klasse: e.className || "", suche: Boolean(e.closest("#mega-suche")),
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
  // zwischen 901 und 1365 px nur Symbole: title nennt Name und Inhalt beim Überfahren mit der Maus (Prüfung von PR 3);
  // seit Pull Request 5 ab 1366 px und auf dem Telefon mit sichtbarer Beschriftung und ohne title (sonst läsen
  // Bildschirmleser den Namen als Beschreibung ein zweites Mal)
  const titel = await page.$$eval('.nav-group[aria-label="Menü"] .menu-btn', (bs) => bs.filter((b) => !b.hidden).map((b) => b.getAttribute("title")));
  pruefen(profil, profil === "1024" ? "Menü-Schaltflächen mit title (nur Symbole)" : "Menü-Schaltflächen mit Beschriftung, ohne title",
    titel.length === 4 && titel.every((t, i) => (profil === "1024" ? Boolean(t) && t.startsWith(`${MENUES[i][1]}: `) : t === null)), titel);
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
  // Karte „Themenseiten“ im Menü „Themen“ nur mit Freigabe (index.json meta.funktionen; der Bau entfernt sie sonst)
  const themenAn = await page.evaluate(async () => Boolean(((await (await fetch("data/export/koeln/index.json")).json()).meta
    .funktionen || {}).themenseiten));
  pruefen(profil, "Inhalt der Menüs", JSON.stringify(inhalte["Wer entscheidet"]) === '["Gremien","Ämter","Verfahrenswege in Zahlen"]'
    && JSON.stringify(inhalte.Themen) === JSON.stringify(["Kennzahlen zum Gebiet", ...(themenAn ? ["Themenseiten"] : [])])
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
  // seit der Prüfung von Pull Request 5 führt Tab aus dem Suchfeld durch das offene Suchmenü (danach „Gebiet“): auf
  // breiten Bildschirmen bis zu 40 Schritte, bis die vier Menüs erreicht sind; die Elemente des Suchmenüs zählen für
  // die Reihenfolge der Leiste nicht mit
  const menueZahl = () => folge.filter((f) => f.mega && f.mega !== "mega-suche" && !f.suche).length;
  for (let i = 0; i < (telefon(profil) ? 14 : 40) && (telefon(profil) || menueZahl() < 4); i++) { await page.keyboard.press("Tab"); folge.push(await fokus(page)); }
  if (!telefon(profil)) {
    const leiste = folge.filter((f) => !f.suche);
    const menues = leiste.filter((f) => f.mega && f.mega !== "mega-suche").map((f) => f.mega);
    const ersterFokus = leiste[0];
    pruefen(profil, "Tab: Wortmarke, Suche, Gebiet, Flächen, dann die vier Menüs in ihrer Reihenfolge, sichtbarer Fokus",
      ersterFokus.klasse === "brand" && leiste[1].id === "q" && leiste[2].id === "f-area"
      && JSON.stringify(menues.slice(0, 4)) === JSON.stringify(MENUES.map(([m]) => m)) && folge.every((f) => f.sichtbar && f.rahmen),
      folge.map((f) => (f.suche ? "suche:" : "") + (f.id || f.mega || f.klasse || f.tag)));
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

// --- Pull Request 5 der Navigation (Entscheidung 24.11.2026 (2), Punkte (a) bis (c)) ------------------------------------
const mobil = (profil) => telefon(profil) || profil === "klein";
// Ankündigungen in Texten der Vorschau (Entscheidung 21.11.2026 (1) (12)); „Liste und Karte folgen“ im Schritt
// „Zeitleiste“ ist keine Ankündigung, der Schritt fehlt in der Vorschau
const ANKUENDIGUNG = /\bfolg(t|en)\b|kommt hinzu|kommen hinzu|künftig|sobald|bis dahin/i;
const VORSCHAU_DATEN = { "index.json": (j) => { const { aktuell, ...rest } = j; return { ...rest, meta: { ...j.meta, vorschau: true, testdaten: false } }; } };
// Fokus mit Lage: sichtbar heißt hier auch im Fenster (nicht nur gezeichnet)
const fokusLage = (page) => page.evaluate(() => {
  const e = document.activeElement, r = e.getBoundingClientRect(), cs = getComputedStyle(e);
  return { tag: e.tagName.toLowerCase(), id: e.id, mega: e.dataset.mega || null, text: (e.getAttribute("aria-label") || e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40),
    sichtbar: e !== document.body && e.getClientRects().length > 0 && cs.visibility !== "hidden" && r.bottom > 0 && r.top < innerHeight,
    rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none", oben: Math.round(r.top), unten: Math.round(r.bottom) };
});
// Tour Schritt für Schritt bis zum Ende; liefert Titel und Text jedes Schritts
async function tourDurch(page, { ende = "Fertig", beiSchritt = null } = {}) {
  const schritte = [];
  for (let i = 0; i < 30; i++) {
    await page.waitForFunction(() => !document.querySelector(".tour") || !/^Einen Moment/.test(document.getElementById("tour-text").textContent), null, { timeout: 20000 });
    if (!(await page.$(".tour"))) break;
    const s = await page.evaluate(() => ({ titel: document.getElementById("tour-title").textContent, text: document.getElementById("tour-text").textContent,
      letzter: document.querySelector('[data-tour-act="next"]').textContent === "Fertig" }));
    if (schritte.length && schritte[schritte.length - 1].titel === s.titel) { await page.waitForTimeout(150); continue; }
    schritte.push(s);
    if (beiSchritt) await beiSchritt(s, schritte.length);
    if (s.letzter && ende === "Fertig") { await page.focus('[data-tour-act="next"]'); await page.keyboard.press("Enter"); }
    else await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
  }
  return schritte;
}

// Eine Prüfung von Pull Request 5 bricht bei einem Fehler nur sich selbst ab (die übrigen laufen weiter, auch auf
// dem Stand vor Pull Request 5)
async function einzeln(profil, name, f) {
  try { await f(); } catch (e) { pruefen(profil, `${name}: Ablauf`, false, String(e && e.message || e).split("\n")[0].slice(0, 300)); }
}

// (1) Kartenvorschau: Tour und Satz in der Liste ohne „folgen“, „kommt hinzu“, „künftig“
async function pr5Vorschau(browser, profil) {
  const s = await neueSeite(browser, profil, VORSCHAU_DATEN);
  await s.page.goto(BASIS, { waitUntil: "load" });
  await s.page.waitForFunction(() => document.documentElement.dataset.vorschau === "ja" && document.getElementById("detail-heading").textContent === "Los geht's"
    && /Vorschau/.test(document.getElementById("count").textContent), null, { timeout: 30000 });
  await s.page.waitForTimeout(600);
  await s.page.evaluate(() => window.risKarte.ui.panel("panel-list", true));
  await s.page.waitForTimeout(400);
  const liste = await s.page.$eval("#papers", (e) => e.innerText.trim());
  pruefen(profil, "PR 5 (1) Vorschau: Satz in der Liste ohne Ankündigung", liste.startsWith("Die Vorschau enthält noch keine Ratsvorlagen.") && !ANKUENDIGUNG.test(liste), liste);
  await axe(s.page, profil, "PR 5 (1) Vorschau: Liste");
  await s.page.evaluate(() => window.risKarte.ui.panel("panel-list", false));
  await s.page.evaluate(() => document.querySelector("#mega-ueber [data-tour]").click());
  await s.page.waitForSelector(".tour-card");
  let axeGelaufen = false;
  const schritte = await tourDurch(s.page, { beiSchritt: async (x) => { if (!axeGelaufen && x.titel === "Die Vorlagen") { axeGelaufen = true; await axe(s.page, profil, "PR 5 (1) Vorschau: Tour, Schritt „Die Vorlagen“"); } } });
  const mit = schritte.filter((x) => ANKUENDIGUNG.test(x.text)).map((x) => `${x.titel}: ${x.text.match(ANKUENDIGUNG)[0]}`);
  pruefen(profil, "PR 5 (1) Vorschau: kein Schritt der Tour kündigt an", schritte.length >= 8 && mit.length === 0 && schritte.some((x) => x.titel === "Die Vorlagen")
    && !schritte.some((x) => /Zeitleiste/.test(x.titel)), { schritte: schritte.map((x) => x.titel), mit });
  pruefen(profil, "keine Skriptfehler (PR 5 Vorschau)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (2) Fokus nach dem Ende der Tour: Auslöser, wenn zu sehen, sonst Überschrift der offenen Fläche, sonst erstes Element
// der Leiste (außer dem Suchfeld); nie <body>
async function pr5TourFokus(browser, profil) {
  const erwartet = telefon(profil) ? { id: "nav-burger" } : { id: "detail-heading" };
  for (const art of ["Esc", "Schließen", "Fertig"]) {
    const s = await neueSeite(browser, profil);
    await s.page.goto(BASIS, { waitUntil: "load" });
    await geladen(s.page);
    await s.page.waitForTimeout(400);
    await menueOeffnen(s.page, profil, "mega-ueber");
    await s.page.focus("#mega-ueber [data-tour]");
    await s.page.keyboard.press("Enter");
    await s.page.waitForSelector(".tour-card");
    await s.page.waitForTimeout(400);
    if (art === "Esc") await s.page.keyboard.press("Escape");
    else if (art === "Schließen") { await s.page.focus(".tour-x"); await s.page.keyboard.press("Enter"); }
    else await tourDurch(s.page);
    await s.page.waitForTimeout(500);
    const f = await fokusLage(s.page);
    const weg = !(await s.page.$(".tour"));
    pruefen(profil, `PR 5 (2) Tour aus dem Menü „Über“, Ende mit ${art}: Fokus ${erwartet.id}`, weg && f.id === erwartet.id && f.sichtbar && f.tag !== "body", f);
    if (art === "Esc") await axe(s.page, profil, `PR 5 (2) nach dem Ende der Tour (${art})`);
    pruefen(profil, `keine Skriptfehler (PR 5 Tour, ${art})`, s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  }
  // Start aus „Los geht's“: Esc im ersten Schritt, der Auslöser ist zu sehen und bekommt den Fokus zurück
  const s = await neueSeite(browser, profil);
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  await s.page.waitForTimeout(400);
  await s.page.focus("#detail [data-tour]");
  await s.page.keyboard.press("Enter");
  await s.page.waitForSelector(".tour-card");
  await s.page.waitForTimeout(300);
  await s.page.keyboard.press("Escape");
  await s.page.waitForTimeout(400);
  const f = await s.page.evaluate(() => ({ ausloeser: Boolean(document.activeElement.closest("#detail")) && document.activeElement.hasAttribute("data-tour") }));
  pruefen(profil, "PR 5 (2) Tour aus „Los geht's“, Esc: Fokus zurück auf den Auslöser", f.ausloeser, f);
  await s.ctx.close();
}

// (3) Tab und Umschalt+Tab aus einem offenen Menü schließen es; Esc und Klicks wie bisher
async function pr5MenueTab(browser, profil) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const zustand = (mega) => page.evaluate((id) => ({ offen: !document.getElementById(id).hidden,
    imMenue: document.getElementById(id).contains(document.activeElement), aufKnopf: document.activeElement.dataset.mega === id,
    expanded: document.querySelector(`.nav-group [data-mega="${id}"]`)?.getAttribute("aria-expanded") ?? null }), mega);
  const oeffnenMitTastatur = async (mega) => {
    await page.evaluate(() => window.risKarte.ui.menu(null));   // ein noch offenes Menü (vor Pull Request 5) schließen
    if (telefon(profil) && !(await page.evaluate(() => document.body.classList.contains("nav-open")))) await page.click("#nav-burger");
    await page.focus(`.nav-group [data-mega="${mega}"]`);
    await page.keyboard.press("Enter");
    await page.waitForSelector(`#${mega}:not([hidden])`);
    await page.waitForTimeout(200);
  };
  for (const [mega, name] of MENUES) {
    for (const richtung of ["Tab", "Shift+Tab"]) {
      await oeffnenMitTastatur(mega);
      const drin = await zustand(mega);
      let z = drin, schritte = 0;
      // aus dem Menü hinaus: höchstens 60 Schritte; auf dem Telefon führt Umschalt+Tab zuerst auf die eigene Schaltfläche
      // (das Menü bleibt dabei offen), der nächste Schritt hinaus
      while ((z.imMenue || z.aufKnopf) && schritte < 60) {
        await page.keyboard.press(richtung);
        schritte++;
        z = await zustand(mega);
        if (z.aufKnopf && !z.offen) break;
      }
      const f = await fokusLage(page);
      pruefen(profil, `PR 5 (3) Menü „${name}“: ${richtung} hinaus schließt es, Fokus auf dem nächsten Ziel`, drin.imMenue && !z.offen && z.expanded === "false"
        && f.tag !== "body" && f.sichtbar, { schritte, fokus: f, drin });
      if (telefon(profil) && richtung === "Shift+Tab") {
        // die eigene Schaltfläche gehört zum Menü: Umschalt+Tab vom ersten Eintrag dorthin lässt es offen
        await oeffnenMitTastatur(mega);
        await page.keyboard.press("Shift+Tab");
        const k = await zustand(mega);
        pruefen(profil, `PR 5 (3) Menü „${name}“: Umschalt+Tab auf die eigene Schaltfläche lässt es offen`, k.aufKnopf && k.offen, k);
        await page.keyboard.press("Escape");
      }
      if (telefon(profil) && await page.evaluate(() => document.body.classList.contains("nav-open"))) { await page.keyboard.press("Escape"); await page.waitForTimeout(150); }
    }
  }
  await axe(page, profil, "PR 5 (3) nach Tab aus dem Menü");
  // Suchmenü: Esc schließt und lässt den Fokus im Suchfeld; Tab und Umschalt+Tab prüft pr5Suchmenue
  await page.focus("#q");
  await page.waitForSelector("#mega-suche:not([hidden])");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  const esc = await page.evaluate(() => ({ offen: !document.getElementById("mega-suche").hidden, fokus: document.activeElement.id }));
  pruefen(profil, "PR 5 (3) Suchmenü: Esc wie bisher (zu, Fokus im Suchfeld)", !esc.offen && esc.fokus === "q", esc);
  // Klicks wie bisher: ein Menü öffnet, ein Klick auf ein anderes wechselt, ein zweiter Klick schließt
  if (telefon(profil)) await page.click("#nav-burger");
  await page.click('.nav-group [data-mega="mega-themen"]');
  await page.waitForTimeout(150);
  await page.click('.nav-group [data-mega="mega-mitmachen"]');
  await page.waitForTimeout(250);
  const k1 = await page.evaluate(() => [document.getElementById("mega-themen").hidden, document.getElementById("mega-mitmachen").hidden]);
  await page.click('.nav-group [data-mega="mega-mitmachen"]');
  await page.waitForTimeout(250);
  const k2 = await page.evaluate(() => document.getElementById("mega-mitmachen").hidden);
  pruefen(profil, "PR 5 (3) Klicks wie bisher: Wechsel des Menüs, zweiter Klick schließt", k1[0] && !k1[1] && k2, { k1, k2 });
  pruefen(profil, "keine Skriptfehler (PR 5 Menüs)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (3) nach der Prüfung von Pull Request 5: das Suchmenü mit der Tastatur. Es steht im Dokument hinter der ganzen
// Leiste; Tab aus dem Suchfeld führt durch alle sichtbaren Bedienelemente in ihrer Reihenfolge, Tab nach dem letzten
// schließt es und führt auf das Element der Leiste nach dem Suchfeld („Gebiet“, auf dem Telefon „Menü“), Umschalt+Tab
// vom ersten zurück ins Suchfeld (offen) und aus dem Suchfeld hinaus (zu); ein Schnellfilter behält nach Enter den Fokus;
// nach Esc führt Tab direkt weiter. Auf ca73ff5 (vor den Durchsichten) schloss schon Tab aus dem Suchfeld das Menü
// (nichts darin erreichbar)
async function pr5Suchmenue(browser, profil) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const lage = () => page.evaluate(() => {
    const m = document.getElementById("mega-suche"), e = document.activeElement, cs = getComputedStyle(e);
    return { offen: !m.hidden, imMenue: m.contains(e), id: e.id, tag: e.tagName.toLowerCase(),
      schluessel: e.id || e.dataset.scope || e.dataset.theme || e.dataset.party || e.tagName.toLowerCase(),
      sichtbar: e.getClientRects().length > 0, rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none" };
  });
  const weiter = telefon(profil) ? "nav-burger" : "f-area";
  await page.focus("#q");
  await page.keyboard.type("a");
  await page.waitForTimeout(500);
  const soll = await page.evaluate(() => [...document.querySelectorAll("#mega-suche button, #mega-suche a[href], #mega-suche input, #mega-suche select")]
    .filter((e) => e.getClientRects().length && !e.closest("[hidden]") && getComputedStyle(e).visibility !== "hidden" && !e.disabled)
    .map((e) => e.id || e.dataset.scope || e.dataset.theme || e.dataset.party));
  const ist = [];
  let z = await lage();
  for (let i = 0; i < soll.length + 3; i++) {
    await page.keyboard.press("Tab");
    z = await lage();
    if (!z.imMenue) break;
    ist.push(z);
    if (i === 2) await axe(page, profil, "PR 5 (3) Suchmenü mit dem Fokus auf einem Schnellfilter");
  }
  const reihe = ist.map((x) => x.schluessel);
  pruefen(profil, "PR 5 (3) Suchmenü: Tab aus dem Suchfeld erreicht alle sichtbaren Bedienelemente in ihrer Reihenfolge, Fokus sichtbar",
    soll.length >= 4 && JSON.stringify(reihe) === JSON.stringify(soll) && ist.every((x) => x.offen && x.sichtbar && x.rahmen),
    { soll: soll.length, erreicht: ist.length, erstes: reihe[0] || null, letztes: reihe[reihe.length - 1] || null,
      abweichend: reihe.filter((k, i) => k !== soll[i]).slice(0, 3) });
  pruefen(profil, `PR 5 (3) Suchmenü: Tab nach dem letzten Element schließt es, Fokus auf ${weiter}`,
    ist.length === soll.length && !z.offen && z.id === weiter && z.sichtbar && z.rahmen, z);
  // Umschalt+Tab vom ersten Element zurück ins Suchfeld (offen), dann aus dem Suchfeld hinaus (zu)
  await page.focus("#q");
  await page.waitForTimeout(200);
  await page.keyboard.press("Tab");
  const erst = await lage();
  await page.keyboard.press("Shift+Tab");
  const zurueck = await lage();
  pruefen(profil, "PR 5 (3) Suchmenü: Umschalt+Tab vom ersten Element zurück ins Suchfeld, Menü bleibt offen",
    erst.imMenue && erst.schluessel === soll[0] && zurueck.id === "q" && zurueck.offen, { erst: erst.schluessel, zurueck: zurueck.id, offen: zurueck.offen });
  await page.keyboard.press("Shift+Tab");
  const raus = await lage();
  pruefen(profil, "PR 5 (3) Suchmenü: Umschalt+Tab aus dem Suchfeld schließt es", !raus.offen && raus.id !== "q" && raus.tag !== "body" && raus.sichtbar, raus);
  // Schnellfilter mit Enter: fillChips baut die Schnellfilter neu auf, der Fokus bleibt auf dem gewählten
  await page.focus("#q");
  await page.waitForSelector("#chips-theme .chip");
  const thema = await page.$eval("#chips-theme .chip:nth-child(2)", (c) => c.dataset.theme);
  await page.focus("#chips-theme .chip:nth-child(2)");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  const chip = await page.evaluate(() => ({ offen: !document.getElementById("mega-suche").hidden, tag: document.activeElement.tagName.toLowerCase(),
    thema: document.activeElement.dataset.theme || null, gedrueckt: document.activeElement.getAttribute("aria-pressed") }));
  pruefen(profil, "PR 5 (3) Suchmenü: Schnellfilter mit Enter gewählt, der Fokus bleibt auf ihm", chip.offen && chip.thema === thema && chip.gedrueckt === "true", chip);
  await page.keyboard.press("Enter");   // Thema wieder abwählen
  await page.waitForTimeout(300);
  // Esc schließt (Fokus im Suchfeld), danach führt Tab direkt weiter
  await page.focus("#q");
  await page.waitForTimeout(150);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Tab");
  const esc = await lage();
  pruefen(profil, `PR 5 (3) Suchmenü: nach Esc führt Tab aus dem Suchfeld direkt auf ${weiter}`, !esc.offen && esc.id === weiter, esc);
  pruefen(profil, "keine Skriptfehler (PR 5 Suchmenü)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (4) Beschriftung der Leiste ab 1366 px: Maße bei fünf Größen, dazu 1365 px (nur Symbole) als Grenze
const LEISTE_GROESSEN = [[1366, 768], [1440, 900], [1536, 864], [1600, 900], [1920, 1080], [1365, 768]];
async function pr5Beschriftung(browser) {
  const masse = {};
  for (const [w, h] of LEISTE_GROESSEN) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, bypassCSP: true });
    await ctx.route(nichtLokal, (r) => r.abort());
    const page = await ctx.newPage();
    const fehler = [];
    page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
    await page.goto(BASIS, { waitUntil: "load" });
    await geladen(page);
    await page.waitForTimeout(400);
    const m = await page.evaluate(() => {
      const nav = document.querySelector(".nav"), nr = nav.getBoundingClientRect(), ns = getComputedStyle(nav);
      const teile = [...nav.querySelectorAll(".brand, .nav-search, #f-area, .nav-group .toggle, .nav-group .menu-btn")].filter((e) => !e.hidden && e.getClientRects().length);
      const r = teile.map((e) => { const b = e.getBoundingClientRect(); return { e, l: b.left, r: b.right, m: b.top + b.height / 2 }; });
      const knoepfe = [...nav.querySelectorAll(".nav-group .toggle, .nav-group .menu-btn")].filter((e) => !e.hidden && e.getClientRects().length);
      const schild = knoepfe.map((b) => { const sp = b.querySelector(":scope > span"), sr = sp.getBoundingClientRect();
        return { text: sp.textContent.trim(), breite: Math.round(sr.width), innen: sr.left >= b.getBoundingClientRect().left - 0.5 && sr.right <= b.getBoundingClientRect().right + 0.5,
          titel: b.getAttribute("title"), label: b.getAttribute("aria-label") }; });
      let ueberlappt = 0;
      for (let i = 1; i < r.length; i++) if (r[i].l < r[i - 1].r - 0.5) ueberlappt++;
      const mitten = r.map((x) => x.m);
      return { ueberlauf: nav.scrollWidth - nav.clientWidth, rechts: Math.round(nr.right - parseFloat(ns.paddingRight) - r[r.length - 1].r),
        einzeilig: Math.max(...mitten) - Math.min(...mitten) < 2 && Math.round(nr.height) === 60, ueberlappt,
        suchfeld: Math.round(document.getElementById("q").getBoundingClientRect().width), schild };
    });
    // zugänglicher Name = sichtbare Beschriftung (genau eine Schaltfläche je Name)
    const namen = [];
    for (const x of m.schild) namen.push(await page.getByRole("button", { name: x.text, exact: true }).count());
    const beschriftet = m.schild.every((x) => x.breite > 10 && x.innen);
    const nurSymbole = m.schild.every((x) => x.breite <= 1);
    const ziel = w >= 1366;
    masse[`${w}x${h}`] = { suchfeld: m.suchfeld, rechts: m.rechts, ueberlauf: m.ueberlauf, einzeilig: m.einzeilig, ueberlappt: m.ueberlappt };
    pruefen(`${w}x${h}`, ziel ? "PR 5 (4) Leiste beschriftet, einzeilig, ohne Überlauf und Überlappung, Suchfeld mindestens 240 px"
      : "PR 5 (4) bis 1365 px nur Symbole mit title", ziel
      ? beschriftet && m.ueberlauf <= 0 && m.rechts >= 0 && m.einzeilig && m.ueberlappt === 0 && m.suchfeld >= 240
        && m.schild.every((x) => x.titel === null && !x.label) && namen.every((n) => n === 1)
      : nurSymbole && m.schild.every((x) => Boolean(x.titel) && x.titel.startsWith(x.text === "Vorgang" ? "Gewählter Vorgang" : x.text === "Vorlagen" ? "Alle Vorlagen" : x.text)),
      { ...masse[`${w}x${h}`], schild: m.schild.map((x) => `${x.text}:${x.breite}${x.titel ? " [title]" : ""}`), namen });
    // nach der Prüfung von Pull Request 5: Der Platzhalter des Suchfelds passt ins Feld (vorher bei 1366 px mitten im
    // Wort abgeschnitten); mit den Textabständen nach WCAG 1.4.12 ragt die Leiste nicht über ihren Rand und das Fenster
    const platzhalter = (abstand) => page.evaluate((abstand) => {
      let st = null;
      if (abstand) { st = document.createElement("style"); st.textContent = "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }"; document.head.append(st); }
      const nav = document.querySelector(".nav"), nr = nav.getBoundingClientRect(), q = document.getElementById("q"), cs = getComputedStyle(q);
      const ks = [...nav.querySelectorAll(".nav-group .toggle, .nav-group .menu-btn")].filter((e) => !e.hidden && e.getClientRects().length);
      const c = document.createElement("canvas").getContext("2d");
      c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const r = { ueberlauf: nav.scrollWidth - nav.clientWidth, letzter: Math.round(ks[ks.length - 1].getBoundingClientRect().right), leiste: Math.round(nr.right), fenster: innerWidth,
        suchfeld: Math.round(q.getBoundingClientRect().width), platz: Math.round(q.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)),
        platzhalter: Math.round(c.measureText(q.placeholder).width) };
      if (st) st.remove();
      return r;
    }, abstand);
    const ph = await platzhalter(false), ta = await platzhalter(true);
    masse[`${w}x${h}`].platzhalter = `${ph.platzhalter} von ${ph.platz} px`;
    masse[`${w}x${h}`].textabstaende = { suchfeld: ta.suchfeld, ueberlauf: ta.ueberlauf, bisRandLeiste: ta.leiste - ta.letzter, bisFenster: ta.fenster - ta.letzter };
    pruefen(`${w}x${h}`, "PR 5 (4) Platzhalter des Suchfelds passt ins Feld", ph.platzhalter <= ph.platz, ph);
    pruefen(`${w}x${h}`, "PR 5 (4) mit Textabständen nach WCAG 1.4.12: kein Überlauf, letzter Eintrag in der Leiste und im Fenster",
      ta.ueberlauf <= 0 && ta.letzter <= ta.leiste && ta.letzter <= ta.fenster, ta);
    if (FOTOS && w === 1366) {
      await page.addStyleTag({ content: "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }" });
      await page.waitForTimeout(150);
      await foto(page, `pr5-leiste-${w}x${h}-textabstaende`, ".nav");
      await page.reload({ waitUntil: "load" });
      await geladen(page);
      await page.waitForTimeout(400);
    }
    if (w === 1366 || w === 1440) await axe(page, `${w}x${h}`, "PR 5 (4) Leiste mit Beschriftung");
    if (FOTOS && w !== 1365) await foto(page, `pr5-leiste-${w}x${h}`, ".nav");
    pruefen(`${w}x${h}`, "keine Skriptfehler (PR 5 Leiste)", fehler.length === 0, fehler);
    await ctx.close();
  }
  return masse;
}

// (5) Eingabefelder auf dem Telefon (bis 900 px) mit mindestens 16 px Schrift und 44 px Höhe (iOS vergrößert sonst
// beim Fokus); breite Bildschirme unverändert
const felderMessen = (page) => page.evaluate(() => [...document.querySelectorAll("input, select, textarea, #panel-auswertung [role=tab]")]
  .filter((e) => e.getClientRects().length && getComputedStyle(e).visibility !== "hidden" && !["checkbox", "radio", "hidden"].includes(e.type))
  .map((e) => ({ feld: e.id || e.getAttribute("role"), px: parseFloat(getComputedStyle(e).fontSize), hoehe: Math.round(e.getBoundingClientRect().height) })));
async function pr5Eingabefelder(browser, profil, gebiet) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const gemessen = [];
  const merken = async (wo) => { for (const f of await felderMessen(page)) gemessen.push({ wo, ...f }); };
  await merken("Start");
  if (!mobil(profil)) {
    // breite Bildschirme: Suchfeld 15 px und Reiter von „In Zahlen“ 13 px wie bisher
    await page.evaluate(() => document.querySelector('[data-open-tab="stats"]').click());
    await page.waitForSelector("#panel-auswertung:not([hidden])");
    await merken("In Zahlen");
    const q = gemessen.find((x) => x.feld === "q"), reiter = gemessen.filter((x) => /^tab-/.test(x.feld));
    pruefen(profil, "PR 5 (5) breite Bildschirme unverändert (Suchfeld 15 px, Reiter von „In Zahlen“ 13 px)", q && q.px === 15 && reiter.length === 2 && reiter.every((x) => x.px === 13), { q, reiter });
    await s.ctx.close();
    return;
  }
  await page.click("#nav-burger");
  await page.waitForTimeout(250);
  await merken("Menü");
  await page.click("#nav-burger");
  await page.evaluate(() => document.querySelector('[data-open-tab="stats"]').click());
  await page.waitForSelector("#panel-auswertung:not([hidden])");
  await page.waitForTimeout(400);
  await merken("In Zahlen");
  await axe(page, profil, "PR 5 (5) „In Zahlen“");
  await foto(page, `pr5-inzahlen-${profil}`);
  await page.evaluate(() => document.getElementById("tab-wege").click());
  await page.waitForTimeout(400);
  await merken("Verfahrenswege");
  await page.keyboard.press("Escape");
  await page.evaluate(() => document.getElementById("cta-termine").click());
  await page.waitForSelector("#panel-termine:not([hidden])");
  await page.waitForTimeout(300);
  await merken("Termine");
  await page.keyboard.press("Escape");
  await page.evaluate(() => document.getElementById("cta-mitmachen").click());
  await page.waitForSelector("#panel-mitmachen:not([hidden]) #bt-bezirk", { timeout: 20000 });
  await page.waitForTimeout(300);
  await merken("Mitmachen in Köln");
  await axe(page, profil, "PR 5 (5) „Mitmachen in Köln“");
  await foto(page, `pr5-mitmachen-${profil}`);
  await page.keyboard.press("Escape");
  // Gremien und Ämter (Regel seit #51, hier zum Vergleich mit gemessen; auf dem Telefon die Liste mit Suchfeld)
  await page.evaluate(() => document.querySelector('#mega-entscheiden [data-wer="gremien"]').click());
  await page.waitForSelector("#panel-gremien:not([hidden]) #wer-q", { timeout: 20000 });
  await page.waitForTimeout(300);
  await merken("Gremien und Ämter");
  await page.keyboard.press("Escape");
  await page.evaluate(() => window.risKarte.ui.panel("panel-list", true));
  await page.waitForTimeout(300);
  await page.evaluate(() => { const d = document.getElementById("more-filters"); if (d) d.open = true; });
  await merken("Vorlagen");
  await page.evaluate(() => window.risKarte.ui.panel("panel-list", false));
  await page.click(".map-menu");
  await page.waitForTimeout(400);
  await merken("Karte");
  await axe(page, profil, "PR 5 (5) Blatt „Karte“");
  if (profil === "iphone13") {
    // nach der Prüfung von Pull Request 5: mit 16 px passt der Platzhalter ins Suchfeld (vorher „… suche“ abgeschnitten)
    const ph = await page.evaluate(() => { const q = document.getElementById("q"), cs = getComputedStyle(q), c = document.createElement("canvas").getContext("2d");
      c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      return { schrift: cs.fontSize, platz: Math.round(q.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)), platzhalter: Math.round(c.measureText(q.placeholder).width) }; });
    pruefen(profil, "PR 5 (5) Platzhalter des Suchfelds passt mit 16 px ins Feld", ph.schrift === "16px" && ph.platzhalter <= ph.platz, ph);
  }
  const zuKlein = gemessen.filter((x) => x.px < 16 || x.hoehe < 44);
  const felder = [...new Set(gemessen.map((x) => `${x.feld} ${x.px}px ${x.hoehe}`))];
  pruefen(profil, "PR 5 (5) alle Eingabefelder und Reiter von „In Zahlen“ mit 16 px und mindestens 44 px", zuKlein.length === 0
    && ["q", "f-area", "tab-stats", "tab-wege", "wege-type", "termine-scope", "bt-bezirk", "wer-q", "f-text", "nav-metric"].every((id) => gemessen.some((x) => x.feld === id)),
    { zuKlein, felder });
  pruefen(profil, "keine Skriptfehler (PR 5 Eingabefelder)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (6) Enter auf einem Suchtreffer in ganz Köln (und auf einem Eintrag im Gebiet): Fokus auf dem Eintrag, wenn die Liste
// offen bleibt, sonst auf der Überschrift des Vorgangs; (8) „Selbst mitwirken“ ohne benannten Bereich
async function pr5Treffer(browser, profil, gebiet) {
  let s = await neueSeite(browser, profil);
  await s.page.goto(`${BASIS}?suche=koeln`, { waitUntil: "load" });
  await geladen(s.page);
  await s.page.waitForSelector("#panel-list:not([hidden]) #papers button[data-gref]", { timeout: 20000 });
  const treffer = await s.page.$("#papers button[data-gref]");
  const ref = await treffer.evaluate((b) => b.dataset.gref);
  await treffer.focus();
  await s.page.keyboard.press("Enter");
  await s.page.waitForFunction(() => document.querySelector("#detail .steps"), null, { timeout: 20000 });
  await s.page.waitForTimeout(600);
  const listeOffen = await s.page.evaluate(() => !document.getElementById("panel-list").hidden);
  const f = await s.page.evaluate((r) => ({ tag: document.activeElement.tagName.toLowerCase(), eintrag: document.activeElement.dataset?.gref === r,
    aktuell: document.activeElement.getAttribute("aria-current"), titel: Boolean(document.activeElement.closest("#detail")) && document.activeElement.tagName === "H3" }), ref);
  pruefen(profil, `PR 5 (6) Suchtreffer in ganz Köln mit Enter: Fokus ${listeOffen ? "auf dem Eintrag" : "auf dem Titel des Vorgangs"}`,
    f.tag !== "body" && (listeOffen ? f.eintrag && f.aktuell === "true" : f.titel), { listeOffen, ...f });
  await axe(s.page, profil, "PR 5 (6) Vorgang aus einem Suchtreffer in ganz Köln");
  const mw = await s.page.evaluate(() => { const sec = document.querySelector("#detail .participate");
    return sec && { name: sec.getAttribute("aria-labelledby") || sec.getAttribute("aria-label") || sec.getAttribute("role"), h: sec.querySelector("h4")?.textContent,
      bereiche: [...document.querySelectorAll("#detail section[aria-labelledby], #detail section[aria-label], #detail [role=region]")].map((x) => x.className) }; });
  pruefen(profil, "PR 5 (8) „Selbst mitwirken“: Überschrift, kein benannter Bereich", mw && mw.name === null && mw.h === "Selbst mitwirken" && !mw.bereiche.includes("participate"), mw);
  pruefen(profil, "keine Skriptfehler (PR 5 Suchtreffer)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
  // im Gebiet: Enter auf einem Eintrag der Liste (bei 1024 px schließt der Vorgang die Liste; bis Pull Request 5 <body>)
  s = await neueSeite(browser, profil);
  await s.page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(s.page);
  await s.page.evaluate(() => window.risKarte.ui.panel("panel-list", true));
  await s.page.waitForSelector("#panel-list:not([hidden]) #papers button[data-ref]");
  await s.page.waitForTimeout(300);
  await s.page.focus("#papers button[data-ref]");
  await s.page.keyboard.press("Enter");
  await s.page.waitForFunction(() => document.querySelector("#detail .steps"), null, { timeout: 20000 });
  await s.page.waitForTimeout(500);
  const g = await s.page.evaluate(() => ({ liste: !document.getElementById("panel-list").hidden, tag: document.activeElement.tagName.toLowerCase(),
    eintrag: document.activeElement.hasAttribute("data-ref"), titel: Boolean(document.activeElement.closest("#detail")) && document.activeElement.tagName === "H3" }));
  pruefen(profil, "PR 5 (6) Eintrag im Gebiet mit Enter: Fokus auf dem Eintrag oder dem Titel des Vorgangs", g.tag !== "body" && (g.liste ? g.eintrag : g.titel), g);
  await s.ctx.close();
  // nach der Prüfung von Pull Request 5: Wird während des Ladens (Gebietsdatei 3 s verzögert) im Suchfeld der Leiste
  // oder in „Stichwort“ getippt, bleibt der Fokus dort; ist das Feld danach nicht mehr zu sehen (bei 1024 px schließt der
  // Vorgang die Liste), geht er auf den Titel des Vorgangs. Auf ca73ff5 (vor den Durchsichten) sprang er mitten im
  // Tippen auf den Titel. Nur breite Bildschirme: Auf dem Telefon setzt select den Fokus wie schon vor Pull Request 5
  // selbst auf den Titel
  if (mobil(profil)) return;
  for (const feld of ["#q", "#f-text"]) {
    s = await neueSeite(browser, profil);
    await s.page.route((u) => /\/data\/export\/koeln\/(ortsteile|bezirke)\/[^/]+\.json$/.test(u.pathname),
      async (r) => { await new Promise((ok) => setTimeout(ok, 3000)); await r.continue(); });
    await s.page.goto(`${BASIS}?suche=koeln`, { waitUntil: "load" });
    await geladen(s.page);
    await s.page.waitForSelector("#panel-list:not([hidden]) #papers button[data-gref]", { timeout: 20000 });
    await s.page.focus("#papers button[data-gref]");
    await s.page.keyboard.press("Enter");
    await s.page.waitForTimeout(400);
    const vorher = await s.page.evaluate(() => !document.querySelector("#detail .steps"));
    await s.page.focus(feld);
    await s.page.keyboard.type("Rad", { delay: 40 });
    await s.page.waitForFunction(() => document.querySelector("#detail .steps"), null, { timeout: 20000 });
    await s.page.waitForTimeout(800);
    const l = await s.page.evaluate((feld) => { const e = document.querySelector(feld);
      return { fokus: document.activeElement.id || document.activeElement.tagName.toLowerCase(), titel: Boolean(document.activeElement.closest("#detail")) && document.activeElement.tagName === "H3",
        feldSichtbar: Boolean(e.getClientRects().length && !e.closest("[hidden]")), wert: e.value.slice(-3) }; }, feld);
    pruefen(profil, `PR 5 (6) Suchtreffer, während des Ladens in ${feld} getippt: Fokus bleibt dort (sonst Titel des Vorgangs)`,
      vorher && l.wert === "Rad" && (l.feldSichtbar ? l.fokus === feld.slice(1) : l.titel), { vorher, ...l });
    pruefen(profil, `keine Skriptfehler (PR 5 Suchtreffer, ${feld})`, s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  }
}

// (7) Geringe Höhe (320×256): Die Blätter „Vorlagen“ und „Vorgang“ rollen als Ganzes, der Kopf rollt mit; der Fokus
// bleibt beim Tab im sichtbaren Teil des Blatts. Bei normaler Höhe unverändert (der Inhalt rollt für sich)
async function pr5GeringeHoehe(browser, profil, gebiet) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const blatt = (id) => page.evaluate((id) => { const p = document.getElementById(id), b = p.querySelector(".panel-body"), k = p.querySelector(".panel-head");
    const ps = getComputedStyle(p), bs = getComputedStyle(b);
    return { rollt: ps.overflowY, inhalt: bs.overflowY, hoehe: p.clientHeight, gesamt: p.scrollHeight, kopf: Math.round(k.getBoundingClientRect().height) }; }, id);
  if (profil !== "klein") {
    await page.evaluate(() => window.risKarte.ui.panel("panel-list", true));
    await page.waitForTimeout(400);
    const l = await blatt("panel-list");
    pruefen(profil, "PR 5 (7) normale Höhe: Blatt „Vorlagen“ unverändert (nur der Inhalt rollt)", l.rollt !== "auto" && l.inhalt === "auto", l);
    await s.ctx.close();
    return;
  }
  // Blatt „Vorlagen“ über ☰ öffnen wie Besucher:innen
  await page.click("#nav-burger");
  await page.click('.toggle[data-panel="panel-list"]');
  await page.waitForSelector("#panel-list:not([hidden]) #papers button[data-ref]");
  await page.waitForTimeout(500);
  const pruefeBlatt = async (id, name) => {
    const b = await blatt(id);
    const lagen = [];
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press("Tab");
      const l = await page.evaluate((id) => { const p = document.getElementById(id), e = document.activeElement;
        if (!p.contains(e)) return null;
        const r = e.getBoundingClientRect(), pr = p.getBoundingClientRect(), cs = getComputedStyle(e);
        return { ziel: e.id || e.tagName.toLowerCase(), innen: r.top >= pr.top - 1 && r.bottom <= pr.bottom + 1 || (r.height > pr.height && r.top < pr.bottom && r.bottom > pr.top),
          rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none", gerollt: p.scrollTop }; }, id);
      if (!l) break;
      lagen.push(l);
    }
    const kopfWeg = await page.evaluate((id) => { const p = document.getElementById(id); p.scrollTop = p.scrollHeight;
      return p.querySelector(".panel-head").getBoundingClientRect().bottom <= p.getBoundingClientRect().top + 1; }, id);
    pruefen(profil, `PR 5 (7) 320×256: Blatt „${name}“ rollt als Ganzes, Kopf rollt mit, Fokus beim Tab sichtbar`, b.rollt === "auto" && b.inhalt === "visible"
      && b.gesamt > b.hoehe && kopfWeg && lagen.length >= 3 && lagen.every((x) => x.innen && x.rahmen) && lagen.some((x) => x.gerollt > 0),
      { ...b, kopfWeg, lagen: lagen.map((x) => `${x.ziel}${x.innen ? "" : " (verdeckt)"}${x.rahmen ? "" : " (ohne Rahmen)"}`) });
    await page.evaluate((id) => { document.getElementById(id).scrollTop = 0; }, id);
    await axe(page, profil, `PR 5 (7) Blatt „${name}“ bei 320×256`);
  };
  await page.focus("#list-heading");
  await pruefeBlatt("panel-list", "Vorlagen");
  await foto(page, "pr5-vorlagen-320x256");
  await page.evaluate(() => document.querySelector("#papers button[data-ref]").click());
  await page.waitForSelector("#panel-detail:not([hidden]) #detail .steps");
  await page.waitForTimeout(500);
  await page.focus("#detail-heading");
  await pruefeBlatt("panel-detail", "Vorgang");
  await foto(page, "pr5-vorgang-320x256");
  pruefen(profil, "keine Skriptfehler (PR 5 geringe Höhe)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// --- Kleiner UI-PR (Entscheidung 24.11.2026 (5), Punkte (1), (4) und (9)) ----------------------------------------------
const UIPR = "UI-PR (24.11.2026 (5))";
const VORSCHAU_HINWEIS = "Vorschau: Die Karte zeigt Stadtteile und offene Daten (Menü „Ebenen“). Ratsvorlagen der Stadt Köln enthält diese Fassung nicht.";

// (1) Kartenvorschau ohne Ratsvorlagen: Hinweis oben beschreibt die Fassung ohne Ankündigung; „Mitmachen in Köln“ ohne
// Termine ohne den Block „Nächste Sitzungen“ (auch je Stadtbezirk) und ohne Satz zu den Terminen in „Zuhören und
// zuschauen“. Bis main e1c71c6d: „Die Ratsvorlagen … folgen nach dem ersten vollständigen Abruf“ und „Die
// Sitzungstermine erscheinen hier, sobald …“
async function uiPrVorschau(browser, profil) {
  const s = await neueSeite(browser, profil, VORSCHAU_DATEN);
  const page = s.page;
  await page.goto(BASIS, { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.dataset.vorschau === "ja" && document.getElementById("detail-heading").textContent === "Los geht's", null, { timeout: 30000 });
  await page.waitForTimeout(500);
  const h = await page.$eval("#vorschau-hinweis", (e) => ({ text: e.innerText.replace(/\s+/g, " ").trim(), sichtbar: !e.hidden && e.getClientRects().length > 0 }));
  pruefen(profil, `${UIPR} (1) Kartenvorschau: Hinweis oben beschreibt die Fassung, ohne Ankündigung`, h.sichtbar && h.text === VORSCHAU_HINWEIS && !ANKUENDIGUNG.test(h.text), h);
  await page.evaluate(() => document.getElementById("cta-mitmachen").click());
  await page.waitForSelector("#panel-mitmachen:not([hidden]) #bt-bezirk", { timeout: 20000 });
  await page.waitForTimeout(300);
  const lesen = () => page.$eval("#panel-mitmachen", (p) => {
    const zuhoeren = [...p.querySelectorAll("h3, h4")].find((x) => x.textContent.trim() === "Zuhören und zuschauen");
    const karte = zuhoeren && (zuhoeren.closest("section, article, li, .bt-weg, .card") || zuhoeren.parentElement);
    return { block: p.querySelectorAll(".bt-next, #bt-next-h").length, text: p.innerText, zuhoeren: karte ? karte.innerText.replace(/\s+/g, " ") : null };
  });
  const pruefeMitmachen = (m, wo) => pruefen(profil, `${UIPR} (1) Kartenvorschau: „Mitmachen in Köln“ ${wo} ohne „Nächste Sitzungen“ und ohne Ankündigung der Termine`,
    m.block === 0 && !/Nächste Sitzungen|Sitzungstermine/.test(m.text) && Boolean(m.zuhoeren) && !/Kommende Sitzungen|Termine/.test(m.zuhoeren)
      && !ANKUENDIGUNG.test(m.zuhoeren), { block: m.block, zuhoeren: m.zuhoeren && m.zuhoeren.slice(0, 160),
      treffer: (m.text.match(/Nächste Sitzungen[^\n]*|Sitzungstermine[^\n]*/g) || []).slice(0, 2) });
  pruefeMitmachen(await lesen(), "ohne Stadtbezirk");
  const bezirk = await page.$$eval("#bt-bezirk option", (os) => (os.find((o) => o.value) || {}).value || null);
  if (bezirk) {
    await page.selectOption("#bt-bezirk", bezirk);
    await page.waitForTimeout(400);
    pruefeMitmachen(await lesen(), `mit Stadtbezirk (${bezirk})`);
  } else pruefen(profil, `${UIPR} (1) Kartenvorschau: Stadtbezirk in „Mitmachen in Köln“ wählbar`, false);
  await axe(page, profil, `${UIPR} (1) Kartenvorschau: „Mitmachen in Köln“ ohne Termine`);
  pruefen(profil, `keine Skriptfehler (${UIPR} Vorschau)`, s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (4) Im Vorgang sind „Kurz gesagt“, „Zum Stadtteil …“, „Meldungen im Mängelmelder“ und „Nach Regelwerk (Soll)“
// Abschnitte mit Überschrift, keine benannten Bereiche (Landmarken). Die Testdaten haben keine Kurzfassungen; die
// Prüfung setzt im Browser eine erfundene in jede Gebietsdatei ein und öffnet eine Vorlage mit „Zum Stadtteil …“.
// Mängelmelder und Soll sind abgeschaltet und erscheinen mit Testdaten nicht; die Abfrage nach Namen schließt sie ein
const OHNE_LANDMARKE = /^(Zum Stadtteil|Kurz gesagt|Meldungen im Mängelmelder|Nach Regelwerk)/;
async function uiPrVorgangBereiche(browser, profil, gebiet) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  const refs = [];
  await page.route((u) => /\/data\/export\/koeln\/(ortsteile|bezirke)\/[^/]+\.json$/.test(u.pathname), async (route) => {
    const r = await route.fetch();
    const j = await r.json();
    for (const p of j.papers || []) {
      p.kurzfassung = { text: "[Prüfung] Erfundene Kurzfassung für die Browserprüfung, kein Text der Stadt.", modell: "Prüfmodell" };
      if (route.request().url().includes(gebiet.split(":")[1])) refs.push(p.reference);
    }
    await route.fulfill({ response: r, json: j });
  });
  await page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  let ref = null;
  for (const r of [...new Set(refs)].slice(0, 60)) {
    await page.evaluate((x) => window.risKarte.open(x), r);
    await page.waitForTimeout(250);
    if (await page.$("#detail .steps") && await page.$("#detail section.kontext-vorgang")) { ref = r; break; }
  }
  const lage = await page.evaluate(() => ({ kurz: document.querySelector("#detail section.kurz h4")?.textContent.trim() || null,
    stadtteil: document.querySelector("#detail section.kontext-vorgang h4")?.textContent.replace(/\s+/g, " ").trim() || null,
    benannt: [...document.querySelectorAll("#detail section.kurz, #detail section.kontext-vorgang, #detail section.anliegen, #detail section.soll")]
      .filter((x) => x.hasAttribute("aria-labelledby") || x.hasAttribute("aria-label") || x.hasAttribute("role")).map((x) => x.className) }));
  const regionen = await page.locator("#detail").getByRole("region", { name: OHNE_LANDMARKE }).count();
  const baum = await page.locator("#panel-detail").ariaSnapshot();
  const imBaum = baum.split("\n").filter((z) => /- region "(Zum Stadtteil|Kurz gesagt|Meldungen im Mängelmelder|Nach Regelwerk)/.test(z)).map((z) => z.trim());
  pruefen(profil, `${UIPR} (4) Vorgang: „Kurz gesagt“ und „Zum Stadtteil …“ mit Überschrift, keine Landmarke mit diesen Namen (role=region, Barrierefreiheitsbaum)`,
    Boolean(ref) && lage.kurz === "Kurz gesagt" && Boolean(lage.stadtteil) && lage.stadtteil.startsWith("Zum Stadtteil") && lage.benannt.length === 0
      && regionen === 0 && imBaum.length === 0, { ref, ...lage, regionen, imBaum });
  await axe(page, profil, `${UIPR} (4) Vorgang mit „Kurz gesagt“ und „Zum Stadtteil …“`);
  pruefen(profil, `keine Skriptfehler (${UIPR} Vorgang)`, s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (9 a) Breite Bildschirme: Die Menüs stehen im Dokument hinter der ganzen Leiste. Ist eines offen (per Klick, Fokus
// auf der Schaltfläche), führt Tab auf sein erstes Bedienelement, Umschalt+Tab zurück auf die Schaltfläche (offen), Tab
// durch alle Bedienelemente in ihrer Reihenfolge und vom letzten auf das Element der Leiste nach der Schaltfläche (bei
// „Über“, dem letzten Eintrag, auf das nächste Element hinter der Leiste); das Menü ist dann zu. Der Fokus liegt nie auf
// <body>. Bis main e1c71c6d führte Tab von der Schaltfläche auf die nächste Schaltfläche und schloss das Menü
async function uiPrMenueTastatur(browser, profil) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const lage = (id) => page.evaluate((id) => {
    const m = document.getElementById(id), e = document.activeElement, cs = getComputedStyle(e), r = e.getBoundingClientRect();
    return { offen: !m.hidden, expanded: document.querySelector(`.nav-group [data-mega="${id}"]`).getAttribute("aria-expanded"),
      knopf: e.dataset.mega === id, nr: e.dataset.uiprNr ?? null, ziel: e.dataset.uiprZiel === "1", imMenue: m.contains(e), inLeiste: Boolean(e.closest(".nav")),
      body: e === document.body, schluessel: e.id || e.dataset.mega || (e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30) || e.tagName.toLowerCase(),
      sichtbar: e !== document.body && e.getClientRects().length > 0 && cs.visibility !== "hidden" && r.bottom > 0 && r.top < innerHeight,
      rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none" };
  }, id);
  for (const [mega, name] of MENUES) {
    await page.evaluate(() => window.risKarte.ui.menu(null));
    await page.click(`.nav-group [data-mega="${mega}"]`);
    await page.waitForSelector(`#${mega}:not([hidden])`);
    await page.waitForTimeout(200);
    // Soll-Reihenfolge unabhängig von app.js: sichtbare, nicht abgeschaltete Bedienelemente des Menüs; Ziel danach das
    // erste sichtbare Bedienelement der Leiste hinter der Schaltfläche
    const n = await page.evaluate((id) => {
      const sicht = (e) => e.getClientRects().length > 0 && !e.closest("[hidden]") && getComputedStyle(e).visibility !== "hidden" && !e.disabled && e.tabIndex >= 0;
      const els = [...document.getElementById(id).querySelectorAll("button, a[href], input, select, textarea, summary")].filter(sicht);
      els.forEach((e, i) => { e.dataset.uiprNr = String(i); });
      const b = document.querySelector(`.nav-group [data-mega="${id}"]`);
      const z = [...document.querySelectorAll(".nav button, .nav a[href], .nav input, .nav select")].filter(sicht)
        .find((e) => (b.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) && !b.contains(e));
      if (z) z.dataset.uiprZiel = "1";
      return { els: els.length, ziel: z ? z.dataset.mega || z.id : null };
    }, mega);
    const verlauf = [];
    const schritt = async (taste) => { await page.keyboard.press(taste); const l = await lage(mega); verlauf.push(l); return l; };
    const start = await lage(mega);
    verlauf.push(start);
    const erst = await schritt("Tab");
    const zurueck = await schritt("Shift+Tab");
    const wieder = await schritt("Tab");
    const reihe = [wieder.nr];
    let l = wieder;
    for (let i = 1; i < n.els + 2 && l.imMenue; i++) { l = await schritt("Tab"); if (l.imMenue) reihe.push(l.nr); }
    const soll = Array.from({ length: n.els }, (_, i) => String(i));
    pruefen(profil, `${UIPR} (9 a) Menü „${name}“: Tab von der Schaltfläche auf das erste Bedienelement, Umschalt+Tab zurück (offen)`,
      n.els > 0 && start.knopf && start.offen && erst.nr === "0" && erst.offen && zurueck.knopf && zurueck.offen && zurueck.expanded === "true" && wieder.nr === "0",
      { els: n.els, start: start.schluessel, erst: erst.schluessel, zurueck: zurueck.schluessel, offen: zurueck.offen });
    pruefen(profil, `${UIPR} (9 a) Menü „${name}“: Tab durch alle Bedienelemente, vom letzten auf ${n.ziel || "das Element hinter der Leiste"}, Menü zu, Fokus nie auf <body>`,
      JSON.stringify(reihe) === JSON.stringify(soll) && !l.offen && l.expanded === "false" && !l.imMenue && (n.ziel ? l.ziel : !l.knopf) && l.sichtbar && l.rahmen
        && verlauf.every((x) => !x.body), { reihe: reihe.length, soll: soll.length, ende: l.schluessel, offen: l.offen, expanded: l.expanded, body: verlauf.filter((x) => x.body).length });
    await page.evaluate(() => document.querySelectorAll("[data-uipr-nr], [data-uipr-ziel]").forEach((e) => { delete e.dataset.uiprNr; delete e.dataset.uiprZiel; }));
    if (mega === "mega-themen") {
      // für das Bildschirmfoto der Freigabe: Menü offen, Fokus auf dem ersten Eintrag nach Tab
      await page.evaluate(() => window.risKarte.ui.menu(null));
      await page.click('.nav-group [data-mega="mega-themen"]');
      await page.waitForTimeout(200);
      await page.keyboard.press("Tab");
      await page.waitForTimeout(150);
      await axe(page, profil, `${UIPR} (9 a) Menü „Themen“ mit dem Fokus auf dem ersten Eintrag`);
      await foto(page, `uipr-themen-tab-${profil}`);
    }
  }
  pruefen(profil, `keine Skriptfehler (${UIPR} Menüs mit der Tastatur)`, s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (9 b) Esc mit dem Fokus auf einem Schnellfilter im Suchmenü: Menü zu, aria-expanded nirgends „true“, Fokus im
// Suchfeld, und das Menü bleibt zu. Bis main e1c71c6d öffnete der Fokuswechsel ins Suchfeld es sofort wieder
async function uiPrSucheEsc(browser, profil) {
  const s = await neueSeite(browser, profil);
  const page = s.page;
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  await page.focus("#q");
  await page.waitForSelector("#mega-suche:not([hidden]) #chips-theme .chip");
  await page.waitForTimeout(200);
  await page.focus("#chips-theme .chip");
  const vorher = await page.evaluate(() => ({ chip: document.activeElement.classList.contains("chip") && Boolean(document.activeElement.closest("#mega-suche")) }));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  const zustand = () => page.evaluate(() => ({ offen: !document.getElementById("mega-suche").hidden, fokus: document.activeElement.id || document.activeElement.tagName.toLowerCase(),
    expanded: [...document.querySelectorAll('[aria-controls="mega-suche"], [data-mega="mega-suche"]')].map((e) => e.getAttribute("aria-expanded")) }));
  const sofort = await zustand();
  await page.waitForTimeout(400);
  const spaeter = await zustand();
  pruefen(profil, `${UIPR} (9 b) Suchmenü: Esc auf einem Schnellfilter schließt es, aria-expanded nicht „true“, Fokus im Suchfeld, bleibt zu`,
    vorher.chip && !sofort.offen && !spaeter.offen && sofort.fokus === "q" && spaeter.fokus === "q" && spaeter.expanded.every((x) => x !== "true"), { vorher, sofort, spaeter });
  // danach öffnet Tippen im Suchfeld das Menü wie bisher
  await page.keyboard.type("a");
  await page.waitForTimeout(400);
  const tippen = await zustand();
  pruefen(profil, `${UIPR} (9 b) Suchmenü: nach Esc öffnet Tippen im Suchfeld es wieder`, tippen.offen && tippen.fokus === "q", tippen);
  pruefen(profil, `keine Skriptfehler (${UIPR} Suchmenü)`, s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// (9 c) Telefon: Verlässt der Fokus die Leiste mit dem offenen Blatt ☰ (Tab vom letzten Eintrag, auch aus dem im Blatt
// aufgeklappten Menü „Über“), schließt das Blatt; der Fokus bleibt auf dem neuen Ziel, nie auf <body>. Bis main
// e1c71c6d blieb das Blatt offen und lag über dem neuen Ziel
async function uiPrBlatt(browser, profil) {
  for (const art of ["letzter Eintrag", "Menü „Über“ im Blatt"]) {
    const s = await neueSeite(browser, profil);
    const page = s.page;
    await page.goto(BASIS, { waitUntil: "load" });
    await geladen(page);
    await page.waitForTimeout(400);
    await page.click("#nav-burger");
    await page.waitForTimeout(250);
    if (art === "letzter Eintrag") {
      await page.evaluate(() => { const els = [...document.querySelectorAll("#nav-more button, #nav-more a[href], #nav-more select, #nav-more input")]
        .filter((e) => e.getClientRects().length && !e.closest("[hidden]") && !e.disabled); els[els.length - 1].focus(); });
    } else {
      await page.focus('#nav-more [data-mega="mega-ueber"]');
      await page.keyboard.press("Enter");
      await page.waitForSelector("#mega-ueber:not([hidden])");
      await page.waitForTimeout(200);
      await foto(page, `uipr-blatt-ueber-${profil}`);
    }
    const lage = () => page.evaluate(() => {
      const e = document.activeElement, cs = getComputedStyle(e), r = e.getBoundingClientRect();
      return { blatt: document.body.classList.contains("nav-open"), burger: document.getElementById("nav-burger").getAttribute("aria-expanded"),
        ueber: !document.getElementById("mega-ueber").hidden, inLeiste: Boolean(e.closest(".nav")), body: e === document.body,
        ziel: e.id || e.className || e.tagName.toLowerCase(), sichtbar: e !== document.body && e.getClientRects().length > 0 && cs.visibility !== "hidden" && r.bottom > 0 && r.top < innerHeight };
    });
    const start = await lage();
    const verlauf = [start];
    let l = start;
    for (let i = 0; i < 40 && l.inLeiste; i++) { await page.keyboard.press("Tab"); l = await lage(); verlauf.push(l); }
    pruefen(profil, `${UIPR} (9 c) Blatt ☰, Tab aus dem Blatt hinaus (${art}): Blatt zu, Fokus auf dem neuen Ziel, nie auf <body>`,
      start.blatt && start.inLeiste && !l.inLeiste && !l.blatt && l.burger === "false" && !l.ueber && l.sichtbar && verlauf.every((x) => !x.body),
      { schritte: verlauf.length - 1, start: start.ziel, ende: l.ziel, blatt: l.blatt, ueber: l.ueber, sichtbar: l.sichtbar, body: verlauf.filter((x) => x.body).length });
    if (art === "letzter Eintrag") await axe(page, profil, `${UIPR} (9 c) nach Tab aus dem Blatt ☰`);
    pruefen(profil, `keine Skriptfehler (${UIPR} Blatt ☰, ${art})`, s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  }
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
    await hilfe.context().route(nichtLokal, (r) => r.abort());
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
      // Pull Request 5 der Navigation
      await einzeln(profil, "PR 5 (1)", () => pr5Vorschau(browser, profil));
      await einzeln(profil, "PR 5 (2)", () => pr5TourFokus(browser, profil));
      await einzeln(profil, "PR 5 (3)", () => pr5MenueTab(browser, profil));
      await einzeln(profil, "PR 5 (3) Suchmenü", () => pr5Suchmenue(browser, profil));
      await einzeln(profil, "PR 5 (5)", () => pr5Eingabefelder(browser, profil, gebiet));
      await einzeln(profil, "PR 5 (6) und (8)", () => pr5Treffer(browser, profil, gebiet));
      await einzeln(profil, "PR 5 (7)", () => pr5GeringeHoehe(browser, profil, gebiet));
      // kleiner UI-PR (Entscheidung 24.11.2026 (5))
      await einzeln(profil, `${UIPR} (1)`, () => uiPrVorschau(browser, profil));
      await einzeln(profil, `${UIPR} (4)`, () => uiPrVorgangBereiche(browser, profil, gebiet));
      if (!telefon(profil)) await einzeln(profil, `${UIPR} (9 a)`, () => uiPrMenueTastatur(browser, profil));
      await einzeln(profil, `${UIPR} (9 b)`, () => uiPrSucheEsc(browser, profil));
      if (telefon(profil)) await einzeln(profil, `${UIPR} (9 c)`, () => uiPrBlatt(browser, profil));
    }
    // Punkte 5 und 7 zusätzlich bei 320×256 (etwa 400 % Zoom), Punkt 4 mit eigenen Größen
    await einzeln("klein", "PR 5 (5)", () => pr5Eingabefelder(browser, "klein", gebiet));
    await einzeln("klein", "PR 5 (7)", () => pr5GeringeHoehe(browser, "klein", gebiet));
    await einzeln("Leiste", "PR 5 (4)", async () => { masseLeiste = await pr5Beschriftung(browser); });
  } catch (e) {
    pruefen("-", "Ablauf", false, String(e && e.stack || e).slice(0, 800));
  }
  await browser.close();
  if (AUSGABE) fs.writeFileSync(AUSGABE, JSON.stringify({ ergebnisse, masseLeiste }, null, 1));
  console.log(`${befunde} Befunde`);
  process.exit(befunde ? 1 : 0);
})();
