// Browserprüfung von „Wer entscheidet“ (Pull Request 4b, Entscheidungen 21.11.2026 (2) und 23.11.2026 (1)) mit
// Testdaten bei 1440×900, 1024×768 und auf dem iPhone 13: Karten und Titel im Menü, Fläche „Gremien und Ämter“ mit
// Reitern (←/→/Pos1/Ende, wandernder tabindex), Umschalter „Schaubild | Liste“ (Pfeiltasten, Standard nach Breite, Wahl
// in der Adresse), Schaubild mit Detailbereich, Liste mit Suche und früheren Gremien, Reiter „Ämter“, Esc und Fokus
// zurück, Link aus dem Vorgang (Fokus auf dem Eintrag, Esc zurück zum Link), Plakette an der Station, „Vorlagen dieses
// Gremiums“ im Gebiet und in ganz Köln (Kennzeichen, #count, 0 Treffer mit Satz), Adresse beim Laden (wer, darstellung,
// kennung, unbekannte Kennung), Ladefehler mit neuem Versuch, nicht aktuelle Liste der Sitzungen (Stand als Kölner Tag),
// folgende Sitzung nach einer vergangenen nächsten (E2), Wechsel der Breite, Bonner ?prozesse= ohne „soll“, Zeitleiste
// mit vergangener Absage laut Sitzungsnamen; Nachprüfung Bedienung (Fokus beim Wechsel der Breite, Wahl während des
// Ladens, gescheiterter Import, aufgelöstes Gremium, Statuszeile, 320 px); dazu axe-core (WCAG 2.1 A/AA) in jedem neuen
// Zustand und Bildschirmfotos (Umgebungsvariable FOTOS). Abweichende Daten setzt die Prüfung nur im Browser über
// page.route ein (erfundene Werte); die Dateien bleiben unverändert. Nur die lokale Seite: Anfragen an andere Hosts
// werden abgebrochen.
// Aufruf (Seite mit Testdaten, z. B. python3 tools/testdaten.py, Pipeline, tools/seite_bauen.py, dann
//   python3 -m http.server --bind 127.0.0.1 8790 -d _site):
//   NODE_PATH=<…/node_modules mit playwright> AXE_PFAD=<…/axe.min.js> FOTOS=<Ordner> node tests/browser/gremien.js http://127.0.0.1:8790/ [ergebnis.json]
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
const TITEL = "Wer entscheidet: Gremien, Ämter und Verfahrenswege in Zahlen";
const tagInKoeln = (d) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" }).format(d);
const plusTage = (tag, n) => new Date(Date.parse(tag + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const datumDe = (tag) => tag.split("-").reverse().join(".");
// erfundenes Gremium ohne Station mit Kennung (für 0 Treffer; nur im Browser in gremien.json ergänzt)
const PROBE = { key: "probebeirat", name: "[Testdaten] Probebeirat ohne Beratung", gruppe: "uebrige", sitzungen_12m: 0, vorlagen_12m: 0,
  source_object: "https://example.invalid/oparl/organizations/probebeirat" };

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
const telefon = (profil) => profil === "iphone13";

async function neueSeite(browser, profil, aenderungen = {}, zeitpunkt = null) {
  const ctx = await browser.newContext({ ...PROFILE[profil], bypassCSP: true });
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|net::ERR/.test(m.text())) fehler.push(`console: ${m.text()}`); });
  await page.route((u) => !["127.0.0.1", "localhost"].includes(u.hostname), (r) => r.abort());
  // Daten nur im Browser ändern: { "gremien.json": (j) => j, … } (Pfad unter data/export/koeln/); eine Funktion mit
  // zweitem Argument (route) darf selbst antworten
  for (const [datei, f] of Object.entries(aenderungen)) {
    await page.route((u) => u.pathname.endsWith(`/data/export/koeln/${datei}`), async (route) => {
      if (f.length > 1) return f(null, route);
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
async function menueOeffnen(page, profil, mega) {
  if (telefon(profil) && !(await page.evaluate(() => document.body.classList.contains("nav-open")))) await page.click("#nav-burger");
  await page.click(`.nav-group [data-mega="${mega}"]`);
  await page.waitForSelector(`#${mega}:not([hidden])`);
  await page.waitForTimeout(250);
}
const fokus = (page) => page.evaluate(() => {
  const e = document.activeElement, cs = getComputedStyle(e);
  return { tag: e.tagName.toLowerCase(), id: e.id, mega: e.dataset.mega || null, text: (e.getAttribute("aria-label") || e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 80),
    kennung: e.dataset.kennung || e.closest("[data-kennung]")?.dataset.kennung || e.dataset.gremiumKey || null,
    sichtbar: e.getClientRects().length > 0, rahmen: cs.outlineStyle !== "none" || cs.boxShadow !== "none" };
});
const adresse = (page) => page.evaluate(() => Object.fromEntries(new URLSearchParams(location.search)));
const flaecheBereit = (page) => page.waitForFunction(() => {
  const b = document.getElementById("wer-body");
  return b && !document.getElementById("panel-gremien").hidden && b.querySelector(".org, #wer-liste, .wer-dezernat, p");
}, null, { timeout: 20000 });
const zustand = (page) => page.evaluate(() => ({
  tabs: [...document.querySelectorAll("#panel-gremien [role=tab]")].map((t) => [t.dataset.werTab, t.getAttribute("aria-selected"), t.tabIndex]),
  darstellung: document.querySelector(".wer-darstellung").hidden ? null
    : [...document.querySelectorAll(".wer-darstellung [role=radio]")].map((b) => [b.dataset.darstellung, b.getAttribute("aria-checked"), b.tabIndex]),
  schaubild: Boolean(document.querySelector("#wer-body .org")), liste: Boolean(document.querySelector("#wer-body #wer-liste")),
  aemter: document.querySelectorAll("#wer-body .wer-dezernat").length, status: document.getElementById("wer-status").textContent,
  offen: !document.getElementById("panel-gremien").hidden, navOffen: document.body.classList.contains("nav-open"),
}));

// 1–6: Menü, Fläche, Reiter, Umschalter, Schaubild, Liste, Ämter, Esc
async function flaeche(browser, profil, gremien) {
  const { ctx, page, fehler } = await neueSeite(browser, profil);
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  await page.waitForTimeout(400);
  const titel = await page.$eval('.menu-btn[data-mega="mega-entscheiden"]', (b) => b.title);
  pruefen(profil, "Titel der Schaltfläche „Wer entscheidet“ mit Freigabe (E11)", titel === TITEL, titel);
  await menueOeffnen(page, profil, "mega-entscheiden");
  const karten = await page.$$eval("#mega-entscheiden .card", (cs) => cs.filter((c) => c.getClientRects().length).map((c) => c.querySelector(".card-title").textContent));
  pruefen(profil, "Menü „Wer entscheidet“: Gremien, Ämter, Verfahrenswege in Zahlen", JSON.stringify(karten) === '["Gremien","Ämter","Verfahrenswege in Zahlen"]', karten);
  if (telefon(profil)) await foto(page, `menue-wer-entscheidet-${profil}`);
  await axe(page, profil, "Menü „Wer entscheidet“ mit Gremien und Ämtern");
  await page.focus('#mega-entscheiden [data-wer="gremien"]');
  await page.keyboard.press("Enter");
  await flaecheBereit(page);
  await page.waitForTimeout(300);
  let z = await zustand(page), f = await fokus(page), a = await adresse(page);
  const standard = telefon(profil) ? "liste" : "schaubild";
  pruefen(profil, `Karte „Gremien“: Fläche offen, Fokus auf der Überschrift, ☰ zu, Standard ${standard}, Adresse ?wer=gremien`,
    z.offen && !z.navOffen && f.id === "gremien-heading" && z[standard] && z.tabs[0][1] === "true" && z.tabs[0][2] === 0 && z.tabs[1][2] === -1
    && JSON.stringify(a) === '{"wer":"gremien"}', { z, f, a });
  await foto(page, `gremien-${standard}-${profil}`);
  await axe(page, profil, `Gremien als ${standard === "liste" ? "Liste" : "Schaubild"}`);
  // Reiter mit der Tastatur: →, ←, Ende, Pos1; wandernder tabindex
  await page.focus("#tab-wer-gremien");
  const reiter = [];
  for (const taste of ["ArrowRight", "ArrowLeft", "End", "Home", "ArrowLeft"]) {
    await page.keyboard.press(taste);
    await page.waitForTimeout(80);
    reiter.push([(await fokus(page)).id, (await zustand(page)).tabs.map((t) => t[1] === "true" ? t[0] : "").join("")]);
  }
  pruefen(profil, "Reiter: → Ämter, ← Gremien, Ende Ämter, Pos1 Gremien, ← von vorn nach hinten", JSON.stringify(reiter) === JSON.stringify([
    ["tab-wer-aemter", "aemter"], ["tab-wer-gremien", "gremien"], ["tab-wer-aemter", "aemter"], ["tab-wer-gremien", "gremien"], ["tab-wer-aemter", "aemter"]]), reiter);
  z = await zustand(page);
  a = await adresse(page);
  pruefen(profil, "Ämter: ohne Umschalter (E9), ein Abschnitt je Dezernat und „ohne Zuordnung“, Adresse ?wer=aemter", z.darstellung === null && z.aemter >= 2
    && JSON.stringify(a) === '{"wer":"aemter"}', { z, a });
  const aemter = await page.$eval("#wer-body", (b) => ({ quelle: b.querySelector(".wer-aemter-quelle")?.innerText || "", text: b.innerText,
    ohne: [...b.querySelectorAll(".wer-dezernat h3")].map((h) => h.textContent).pop() }));
  pruefen(profil, "Ämter: Quelle mit Stand, letzter Prüfung und Lizenz; „ohne Zuordnung“ zuletzt; keine Zahlen von Vorlagen",
    /Stand \d\d\.\d\d\.\d{4}, zuletzt geprüft am \d\d\.\d\d\.\d{4}\. Lizenz: /.test(aemter.quelle) && aemter.ohne.startsWith("Ohne Zuordnung")
    && !/\d+ Vorlagen/.test(aemter.text), { quelle: aemter.quelle, ohne: aemter.ohne });
  await foto(page, `aemter-${profil}`);
  await axe(page, profil, "Ämter");
  await page.keyboard.press("Home");
  // Umschalter: Pfeiltasten wählen ausdrücklich, die Wahl steht in der Adresse
  await page.focus('.wer-darstellung [role=radio][tabindex="0"]');
  const schalter = [];
  for (const taste of ["ArrowRight", "ArrowDown", "Home", "End", "ArrowUp"]) {
    await page.keyboard.press(taste);
    await page.waitForTimeout(80);
    const s = await zustand(page);
    schalter.push([(await fokus(page)).text, s.darstellung.find((d) => d[1] === "true")[0], (await adresse(page)).darstellung || ""]);
  }
  const anders = standard === "liste" ? "schaubild" : "liste";
  const name = (d) => (d === "liste" ? "Liste" : "Schaubild");
  pruefen(profil, "Umschalter: Pfeiltasten, Pos1 und Ende, Fokus wandert, Adresse ?darstellung=", JSON.stringify(schalter) === JSON.stringify([
    [name(anders), anders, anders], [name(standard), standard, standard], ["Schaubild", "schaubild", "schaubild"], ["Liste", "liste", "liste"],
    ["Schaubild", "schaubild", "schaubild"]]), schalter);
  // Schaubild: Rat oben, übrige Gremien sichtbar, Knoten wählen → Detail mit Fokus, Kennung in der Adresse
  const bild = await page.evaluate(() => ({ oben: document.querySelector("#wer-body .org-top .org-name")?.textContent,
    gruppen: [...document.querySelectorAll("#wer-body .org-h")].map((h) => h.textContent), details: document.querySelectorAll("#wer-body details").length,
    knoten: document.querySelectorAll("#wer-body .org-node").length }));
  const aktiv = gremien.gremien.filter((g) => !g.aufgeloest);
  // Überschriften aus meta.gruppen mit großem Anfangsbuchstaben („übrige Gremien“ → „Übrige Gremien“; Nachprüfung 4b)
  const gross = (t) => t.charAt(0).toLocaleUpperCase("de") + t.slice(1);
  pruefen(profil, "Schaubild: Rat oben, Gruppen aus meta.gruppen (groß am Anfang), alle nicht aufgelösten Gremien sichtbar, nichts eingeklappt", bild.oben === aktiv.find((g) => g.gruppe === "rat").name
    && bild.knoten === aktiv.length && bild.details === 0 && bild.gruppen.includes(gross(gremien.meta.gruppen.uebrige))
    && bild.gruppen.every((h) => h === gross(h)), bild);
  const ziel = aktiv.find((g) => g.gruppe === "ausschuss") || aktiv[1];
  await page.click(`#wer-body .org-node[data-kennung="${ziel.key}"]`);
  await page.waitForTimeout(200);
  f = await fokus(page);
  a = await adresse(page);
  const det = await page.$eval("#wer-detail", (d) => ({ text: d.innerText, live: d.closest("[aria-live]") !== null || d.hasAttribute("aria-live"),
    link: d.querySelector('a[href$=".pdf"]')?.textContent || "", knopf: d.querySelector(".wer-filter")?.textContent.trim() || "" }));
  pruefen(profil, "Schaubild: Knoten wählt, Fokus auf der Überschrift im Detail (ohne Live-Region), Kennung in der Adresse",
    f.tag === "h3" && f.text === ziel.name && a.kennung === ziel.key && !det.live
    && (ziel.paragraf == null || det.link === `Zuständigkeitsordnung, § ${ziel.paragraf} (PDF, neuer Tab)`) && det.knopf === `Vorlagen dieses Gremiums: ${ziel.name}`, { f, a, det });
  await foto(page, `gremien-schaubild-detail-${profil}`);
  await axe(page, profil, "Schaubild mit gewähltem Gremium");
  // Liste: Suche, frühere Gremien, Zähler in der Statuszeile
  await page.click('.wer-darstellung [data-darstellung="liste"]');
  await page.waitForSelector("#wer-q");
  await page.fill("#wer-q", "bezirksvertretung");
  await page.waitForTimeout(600);
  const suche = await page.evaluate(() => ({ eintraege: document.querySelectorAll("#wer-liste details").length, status: document.getElementById("wer-status").textContent,
    fokus: document.activeElement.id }));
  const bv = gremien.gremien.filter((g) => !g.aufgeloest && /bezirksvertretung/i.test(g.name)).length;
  pruefen(profil, "Liste: Suche baut nur die Einträge neu, Fokus bleibt im Suchfeld, Statuszeile nennt die Zahl", suche.eintraege === bv
    && suche.status === `${bv} Gremien` && suche.fokus === "wer-q", suche);
  // Suche, die nur auf ein früheres Gremium passt, ohne „frühere Gremien zeigen“: ein Satz statt „Kein Gremium passt“,
  // die Statuszeile nennt das ausgeblendete Gremium (Nachprüfung 4b)
  const frueheres = gremien.gremien.find((g) => g.aufgeloest && !gremien.gremien.some((x) => !x.aufgeloest && x.name.toLowerCase().includes(g.name.toLowerCase())));
  if (frueheres) {
    const passend = gremien.gremien.filter((g) => g.aufgeloest && g.name.toLowerCase().includes(frueheres.name.toLowerCase())).length;
    await page.fill("#wer-q", frueheres.name);
    await page.waitForTimeout(600);
    const nur = await page.evaluate(() => ({ text: document.getElementById("wer-liste").innerText.trim(), status: document.getElementById("wer-status").textContent,
      eintraege: document.querySelectorAll("#wer-liste details").length, fokus: document.activeElement.id }));
    pruefen(profil, "Liste: Suche nur nach einem früheren Gremium nennt es (Satz und Statuszeile), Fokus bleibt im Suchfeld", nur.eintraege === 0
      && nur.text.startsWith(`Unter den aktuellen Gremien passt keines zur Suche „${frueheres.name}“; `) && nur.text.includes("Mit „frühere Gremien zeigen“")
      && nur.status === `0 Gremien; ${passend === 1 ? "1 früheres Gremium passt" : `${passend} frühere Gremien passen`}` && nur.fokus === "wer-q", nur);
    await axe(page, profil, "Liste, Suche nur nach einem früheren Gremium");
  }
  await page.fill("#wer-q", "");
  await page.waitForTimeout(500);
  const vorher = await page.$$eval("#wer-liste details", (ds) => ds.length);
  await page.check("#wer-frueher");
  await page.waitForTimeout(200);
  const nachher = await page.$$eval("#wer-liste details", (ds) => ds.map((d) => d.querySelector(".pz-meta")?.textContent || ""));
  const alt = gremien.gremien.filter((g) => g.aufgeloest).length;
  pruefen(profil, "Liste: „frühere Gremien zeigen“ ergänzt die aufgelösten, gekennzeichnet", nachher.length === vorher + alt
    && nachher.filter((m) => m.includes("aufgelöst")).length === alt && (await fokus(page)).id === "wer-frueher", { vorher, nachher: nachher.length, alt });
  if (alt) {
    await page.click("#wer-liste details:has(.pz-meta:text-matches('aufgelöst')) summary");
    await page.waitForTimeout(150);
    const altText = await page.$eval("#wer-liste details[open]:has(.pz-meta:text-matches('aufgelöst'))", (d) => ({ text: d.innerText, knopf: Boolean(d.querySelector(".wer-filter")) }));
    pruefen(profil, "früheres Gremium: Satz zur Zählung (E3), kein Knopf (E4)", altText.text.includes("einen Filter „Vorlagen dieses Gremiums“ gibt es für frühere Gremien nicht") && !altText.knopf, altText);
  }
  await foto(page, `gremien-liste-frueher-${profil}`);
  await axe(page, profil, "Liste mit früheren Gremien");
  // Esc schließt, Fokus zurück auf „Wer entscheidet“ (Telefon: ☰)
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250);
  z = await zustand(page);
  f = await fokus(page);
  a = await adresse(page);
  pruefen(profil, "Esc schließt die Fläche, Fokus zurück, Adresse ohne wer, darstellung und kennung", !z.offen
    && (telefon(profil) ? f.id === "nav-burger" : f.mega === "mega-entscheiden") && f.sichtbar && !a.wer && !a.darstellung && !a.kennung, { f, a });
  // Karte „Ämter“ öffnet den Reiter „Ämter“
  await menueOeffnen(page, profil, "mega-entscheiden");
  await page.click('#mega-entscheiden [data-wer="aemter"]');
  await flaecheBereit(page);
  z = await zustand(page);
  pruefen(profil, "Karte „Ämter“ öffnet den Reiter „Ämter“", z.offen && z.tabs[1][1] === "true" && z.aemter >= 2, z.tabs);
  await page.click('#panel-gremien [data-close="panel-gremien"]');
  pruefen(profil, "keine Skriptfehler (Fläche)", fehler.length === 0, fehler);
  await ctx.close();
}

// 7, 8: Vorgang mit Link und Plakette, Esc zurück, „Vorlagen dieses Gremiums“ im Gebiet, Kennzeichen entfernen
async function vorgangUndFilter(browser, profil, gebiet) {
  const datei = `${gebiet.split(":")[0] === "ortsteil" ? "ortsteile" : "bezirke"}/${gebiet.split(":")[1]}.json`;
  let ref = null, gremium = null, key = null;
  const s = await neueSeite(browser, profil, { [datei]: (j) => {
    const p = j.papers.find((x) => x.steps.some((st) => st.gremium_key)) || j.papers[0];
    ref = p.reference;
    const st = p.steps.find((x) => x.gremium_key);
    gremium = st.label; key = st.gremium_key;
    // erfundene Plakette: der Hinweis an Station und Schritt (beide gleich, wie die Pipeline sie schreibt; E1)
    st.hinweis = "abgesagt";
    for (const sta of p.process) if (sta.gremium_key === key && sta.gremium === gremium) { sta.hinweis = "abgesagt"; break; }
    return j;
  }, "gremien.json": (j) => ({ ...j, gremien: [...j.gremien, PROBE] }) });
  await s.page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
  await geladen(s.page);
  if (telefon(profil)) await s.page.click("#nav-burger");
  await s.page.click('.toggle[data-panel="panel-list"]');
  await s.page.waitForSelector(`#panel-list:not([hidden]) #papers button[data-ref="${ref}"]`);
  await s.page.click(`#papers button[data-ref="${ref}"]`);
  await s.page.waitForSelector("#detail .steps");
  await s.page.waitForTimeout(300);
  const v = await s.page.evaluate((k) => ({ links: document.querySelectorAll("#detail [data-gremium-key]").length,
    link: document.querySelector(`#detail [data-gremium-key="${k}"]`)?.textContent, plakette: [...document.querySelectorAll("#detail .step-head .badge")].map((b) => b.textContent),
    ohneKennung: [...document.querySelectorAll("#detail .step-head")].filter((h) => !h.querySelector("[data-gremium-key]") && /^(Beratung|Entscheidung)/.test(h.textContent)).length }), key);
  pruefen(profil, "Vorgang: Gremium mit Kennung als Link, Plakette „laut Sitzungsnamen abgesagt“ an der Station", v.links > 0 && v.link === gremium
    && JSON.stringify(v.plakette) === '["laut Sitzungsnamen abgesagt"]', v);
  // Plakette und Status durch ein Leerzeichen getrennt (Vorlesen, Umbruchstelle); auf dem Telefon bei 300 px kein
  // waagrechtes Scrollen im Vorgang (WCAG 1.4.10; Nachprüfung Bedienung)
  const kopf = await s.page.$eval("#detail .step-head:has(.badge)", (h) => h.textContent);
  let breite = null;
  if (telefon(profil)) {
    await s.page.setViewportSize({ width: 300, height: 640 });
    await s.page.waitForTimeout(300);
    breite = await s.page.$eval("#detail", (d) => [d.scrollWidth, d.clientWidth]);
    await s.page.setViewportSize(PROFILE[profil].viewport);
    await s.page.waitForTimeout(300);
  }
  pruefen(profil, "Plakette: Leerzeichen vor dem Status; Telefon bei 300 px ohne waagrechtes Scrollen im Vorgang", /laut Sitzungsnamen abgesagt \S/.test(kopf)
    && (!breite || breite[0] <= breite[1]), { kopf: kopf.replace(/^.*?(laut)/s, "$1"), breite });
  await s.page.$eval(`#detail [data-gremium-key="${key}"]`, (b) => b.scrollIntoView({ block: "center" }));
  await foto(s.page, `vorgang-link-plakette-${profil}`);
  await axe(s.page, profil, "Vorgang mit Link und Plakette");
  await s.page.focus(`#detail [data-gremium-key="${key}"]`);
  await s.page.keyboard.press("Enter");
  await flaecheBereit(s.page);
  await s.page.waitForTimeout(400);
  let f = await fokus(s.page), a = await adresse(s.page);
  const erwartet = telefon(profil) ? "summary" : "h3";
  pruefen(profil, "Link aus dem Vorgang: Reiter „Gremien“, Fokus auf dem Eintrag des Gremiums, Kennung in der Adresse", f.tag === erwartet
    && f.text.startsWith(gremium) && a.wer === "gremien" && a.kennung === key, { f, a });
  await axe(s.page, profil, "Gremium aus dem Vorgang");
  await s.page.keyboard.press("Escape");
  await s.page.waitForTimeout(300);
  f = await fokus(s.page);
  const zurueck = await s.page.evaluate(() => ({ vorgang: !document.getElementById("panel-detail").hidden && Boolean(document.querySelector("#detail .steps")),
    flaeche: !document.getElementById("panel-gremien").hidden }));
  pruefen(profil, "Esc: Fläche zu, Vorgang offen, Fokus zurück auf dem Link", zurueck.vorgang && !zurueck.flaeche && f.kennung === key && f.sichtbar, { f, zurueck });
  // „Vorlagen dieses Gremiums“ im Gebiet: Liste offen, Fokus auf ihrer Überschrift, #count nennt das Gremium, Kennzeichen
  await s.page.click(`#detail [data-gremium-key="${key}"]`);
  await flaecheBereit(s.page);
  await s.page.waitForTimeout(300);
  await s.page.click(`#wer-body .wer-filter[data-kennung="${key}"]`);
  await s.page.waitForTimeout(500);
  f = await fokus(s.page);
  const l = await s.page.evaluate((k) => ({ count: document.getElementById("count").textContent, kennzeichen: !document.getElementById("gremium-filter").hidden
    && document.getElementById("gremium-filter-name").textContent, liste: !document.getElementById("panel-list").hidden, flaeche: !document.getElementById("panel-gremien").hidden,
    wert: document.getElementById("f-gremium").value, n: document.querySelectorAll("#papers button[data-ref]").length, aktiv: document.getElementById("active-filters").textContent }), key);
  pruefen(profil, "„Vorlagen dieses Gremiums“ im Gebiet: Liste, Fokus auf der Überschrift, #count und Kennzeichen nennen das Gremium", l.liste && !l.flaeche
    && f.id === "list-heading" && l.count.includes(`· Gremium: ${gremium}`) && l.kennzeichen === gremium && l.wert === key && l.n > 0 && l.aktiv === " (1 aktiv)", { f, l });
  await foto(s.page, `liste-gremium-gebiet-${profil}`, "#panel-list");
  await axe(s.page, profil, "Liste mit Filter „Gremium“ im Gebiet");
  await s.page.click("#gremium-filter-aus");
  await s.page.waitForTimeout(200);
  f = await fokus(s.page);
  const weg = await s.page.evaluate(() => ({ count: document.getElementById("count").textContent, kennzeichen: !document.getElementById("gremium-filter").hidden }));
  pruefen(profil, "Kennzeichen entfernen: Filter weg, Fokus auf der Liste", !weg.kennzeichen && !weg.count.includes("Gremium") && f.id === "list-heading", { f, weg });
  // Gremium ohne Beratung im Gebiet: ein Satz mit „In ganz Köln suchen“, danach dieselbe Angabe in ganz Köln
  await menueOeffnen(s.page, profil, "mega-entscheiden");
  await s.page.click('#mega-entscheiden [data-wer="gremien"]');
  await flaecheBereit(s.page);
  await s.page.click('.wer-darstellung [data-darstellung="liste"]');
  await s.page.click(`#wer-liste details[data-kennung="${PROBE.key}"] summary`);
  await s.page.click(`#wer-liste details[data-kennung="${PROBE.key}"] .wer-filter`);
  await s.page.waitForTimeout(400);
  const leer = await s.page.evaluate(() => ({ count: document.getElementById("count").textContent, satz: document.querySelector("#papers .empty-list p")?.textContent || "",
    knopf: Boolean(document.getElementById("gremium-koeln")), fokus: document.activeElement.id }));
  pruefen(profil, "Gremium ohne Beratung im Gebiet: Satz und „In ganz Köln suchen“", leer.count.startsWith("0 von ") && leer.count.endsWith(`· Gremium: ${PROBE.name}`)
    && leer.satz === `Im gewählten Gebiet passt keine Vorlage mit einer Beratung in „${PROBE.name}“ zu Filtern und Zeitraum.` && leer.knopf && leer.fokus === "list-heading", leer);
  await axe(s.page, profil, "0 Treffer mit Filter „Gremium“ im Gebiet");
  await s.page.click("#gremium-koeln");
  await s.page.waitForFunction(() => /Treffer in ganz Köln/.test(document.getElementById("count").textContent), null, { timeout: 20000 });
  const koeln = await s.page.evaluate(() => ({ count: document.getElementById("count").textContent, satz: document.querySelector("#papers .empty-list p")?.textContent || "",
    fokus: document.activeElement.id }));
  pruefen(profil, "„In ganz Köln suchen“: dieselbe Angabe in ganz Köln, Satz statt leerer Liste", koeln.count === `0 Treffer in ganz Köln · Gremium: ${PROBE.name}`
    && koeln.satz === `Für „${PROBE.name}“ ist im Suchindex keine Beratung einer Vorlage verzeichnet.` && koeln.fokus === "list-heading", koeln);
  pruefen(profil, "keine Skriptfehler (Vorgang und Filter)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// 8: in ganz Köln über suche.json (Spalte 11), 0 Treffer mit Satz für ein Gremium ohne Station mit Kennung
async function ganzKoeln(browser, profil, suche) {
  const probe = PROBE;
  const s = await neueSeite(browser, profil, { "gremien.json": (j) => ({ ...j, gremien: [...j.gremien, probe] }) });
  await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste`, { waitUntil: "load" });
  await geladen(s.page);
  await flaecheBereit(s.page);
  const key = "rat", ki = suche.gremium_keys.indexOf(key);
  const erwartet = suche.rows.filter((r) => (r[11] || []).includes(ki)).length;
  await s.page.click(`#wer-liste details[data-kennung="${key}"] summary`);
  await s.page.click(`#wer-liste details[data-kennung="${key}"] .wer-filter`);
  await s.page.waitForFunction(() => /Treffer in ganz Köln/.test(document.getElementById("count").textContent), null, { timeout: 20000 });
  await s.page.waitForTimeout(300);
  const g = await s.page.evaluate(() => ({ count: document.getElementById("count").textContent, kennzeichen: !document.getElementById("gremium-filter").hidden,
    weitere: document.getElementById("more-filters").hidden, fokus: document.activeElement.id }));
  pruefen(profil, "„Vorlagen dieses Gremiums“ ohne Gebiet: ganz Köln über Spalte 11, Kennzeichen sichtbar (Weitere Filter ausgeblendet)",
    g.count.startsWith(`${erwartet} Treffer in ganz Köln · Gremium: `) && g.kennzeichen && g.weitere && g.fokus === "list-heading", { g, erwartet });
  await foto(s.page, `liste-gremium-koeln-${profil}`, "#panel-list");
  await axe(s.page, profil, "Liste mit Filter „Gremium“ in ganz Köln");
  // Gremium ohne Station mit Kennung: 0 Treffer und ein Satz
  await s.page.evaluate(() => document.querySelector('.menu-btn[data-mega="mega-entscheiden"]').scrollIntoView());
  await menueOeffnen(s.page, profil, "mega-entscheiden");
  await s.page.click('#mega-entscheiden [data-wer="gremien"]');
  await flaecheBereit(s.page);
  await s.page.click(`#wer-liste details[data-kennung="${probe.key}"] summary`);
  await s.page.click(`#wer-liste details[data-kennung="${probe.key}"] .wer-filter`);
  await s.page.waitForTimeout(400);
  const n = await s.page.evaluate(() => ({ count: document.getElementById("count").textContent, satz: document.querySelector("#papers .empty-list p")?.textContent || "" }));
  pruefen(profil, "Gremium ohne Station mit Kennung: 0 Treffer und ein Satz", n.count.startsWith(`0 Treffer in ganz Köln · Gremium: ${probe.name}`)
    && n.satz === `Für „${probe.name}“ ist im Suchindex keine Beratung einer Vorlage verzeichnet.`, n);
  await axe(s.page, profil, "0 Treffer mit Filter „Gremium“");
  pruefen(profil, "keine Skriptfehler (ganz Köln)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
}

// 9–13: Adresse beim Laden, unbekannte Kennung, Ladefehler mit neuem Versuch, nicht aktuelle Liste der Sitzungen,
// folgende Sitzung (E2), Wechsel der Breite, Bonner ?prozesse= ohne „soll“
async function adresseUndDaten(browser, profil, gremien) {
  const heute = tagInKoeln(new Date());
  const bv = gremien.gremien.find((g) => g.gruppe === "bezirksvertretung");
  let s = await neueSeite(browser, profil);
  await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste&kennung=${bv.key}`, { waitUntil: "load" });
  await geladen(s.page);
  await flaecheBereit(s.page);
  let z = await zustand(s.page);
  const offen = await s.page.$$eval("#wer-liste details[open]", (ds) => ds.map((d) => d.dataset.kennung));
  pruefen(profil, "Adresse ?wer=gremien&darstellung=liste&kennung=…: Liste mit diesem Gremium aufgeklappt", z.liste && JSON.stringify(offen) === JSON.stringify([bv.key]), { offen });
  await s.ctx.close();
  s = await neueSeite(browser, profil);
  await s.page.goto(`${BASIS}?wer=gremien&kennung=gibt-es-nicht`, { waitUntil: "load" });
  await geladen(s.page);
  await flaecheBereit(s.page);
  z = await zustand(s.page);
  pruefen(profil, "unbekannte Kennung: keine Auswahl, Satz in der Statuszeile", z.status.startsWith("Das Gremium aus dem Link ist unter „Gremien“ nicht verzeichnet")
    && !(await adresse(s.page)).kennung && (await s.page.$$eval('#wer-body [aria-pressed="true"], #wer-body details[open]', (x) => x.length)) === 0, z.status);
  await s.page.goto(`${BASIS}?prozesse=gremien`, { waitUntil: "load" });
  await geladen(s.page);
  await s.page.waitForTimeout(500);
  const bonn = await s.page.evaluate(() => ({ prozesse: !document.getElementById("panel-prozesse").hidden, modul: performance.getEntriesByType("resource").some((r) => r.name.endsWith("/prozesse.js")) }));
  pruefen(profil, "Bonner ?prozesse=gremien öffnet ohne „soll“ nichts und lädt prozesse.js nicht", !bonn.prozesse && !bonn.modul, bonn);
  await s.ctx.close();
  // Ladefehler: erster Abruf von gremien.json scheitert; ein Satz in der Statuszeile (role=status, wird angesagt; WCAG
  // 4.1.3), beim nächsten Öffnen neuer Versuch; danach wirken Reiter einmal (die Ereignisse sind nur einmal angemeldet)
  let versuche = 0;
  s = await neueSeite(browser, profil, { "gremien.json": async (j, route) => {
    versuche++;
    if (versuche === 1) return route.fulfill({ status: 503, body: "" });
    return route.continue();
  } });
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  await menueOeffnen(s.page, profil, "mega-entscheiden");
  await s.page.click('#mega-entscheiden [data-wer="gremien"]');
  await s.page.waitForFunction(() => /konnten nicht geladen werden/.test(document.getElementById("wer-status").textContent), null, { timeout: 20000 });
  const fehlerZeile = await s.page.evaluate(() => ({ status: document.getElementById("wer-status").textContent, rolle: document.getElementById("wer-status").getAttribute("role"),
    inhalt: document.getElementById("wer-body").textContent.trim() }));
  await axe(s.page, profil, "Ladefehler");
  await s.page.keyboard.press("Escape");
  await menueOeffnen(s.page, profil, "mega-entscheiden");
  await s.page.click('#mega-entscheiden [data-wer="gremien"]');
  await flaecheBereit(s.page);
  await s.page.waitForTimeout(300);
  z = await zustand(s.page);
  pruefen(profil, "Ladefehler: ein Satz in der Statuszeile (role=status), beim nächsten Öffnen neuer Versuch mit Erfolg", fehlerZeile.status === "Die Angaben zu Gremien und Ämtern konnten nicht geladen werden. Beim nächsten Öffnen versucht der Ratsatlas es erneut."
    && fehlerZeile.rolle === "status" && fehlerZeile.inhalt === "" && versuche === 2 && (z.schaubild || z.liste), { fehlerZeile, versuche });
  await s.page.focus("#tab-wer-gremien");
  await s.page.keyboard.press("ArrowRight");
  await s.page.waitForTimeout(150);
  z = await zustand(s.page);
  pruefen(profil, "nach dem neuen Versuch: → wählt einmal den nächsten Reiter", z.tabs[1][1] === "true" && z.aemter >= 2 && (await fokus(s.page)).id === "tab-wer-aemter", z.tabs);
  pruefen(profil, "keine Skriptfehler (Ladefehler)", s.fehler.length === 0, s.fehler);
  await s.ctx.close();
  // nicht aktuelle Liste der Sitzungen: Hinweis mit dem Stand als Kölner Tag (23:30 UTC ist dort der nächste Tag)
  s = await neueSeite(browser, profil, { "gremien.json": (j) => ({ ...j, meta: { ...j.meta, sitzungsliste_nicht_aktuell: { stand: "2026-11-17T23:30:00+00:00", hinweis: "x" } },
    gremien: j.gremien.map(({ naechste_sitzung, folgende_sitzung, ...g }) => g) }) });
  await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste&kennung=rat`, { waitUntil: "load" });
  await geladen(s.page);
  await flaecheBereit(s.page);
  const liste = await s.page.evaluate(() => ({ oben: document.querySelector("#wer-body .stand-hinweis")?.textContent || "",
    rat: document.querySelector('#wer-liste details[data-kennung="rat"]')?.innerText || "" }));
  pruefen(profil, "nicht aktuelle Liste der Sitzungen: Hinweis mit dem Stand vom 18.11.2026 statt der nächsten Sitzung",
    liste.oben.includes("gezeigt wird der Stand vom 18.11.2026, eine nächste Sitzung deshalb nicht.") && liste.rat.includes("Stand vom 18.11.2026")
    && !liste.rat.includes("Nächste Sitzung:"), liste);
  await axe(s.page, profil, "Liste der Sitzungen nicht aktuell");
  await s.ctx.close();
  // E2: nächste Sitzung am Datenstand ist für die Besucherin vorbei → die folgende Sitzung (erfunden) erscheint
  const morgen = plusTage(gremien.meta.datenstand, 1), danach = plusTage(gremien.meta.datenstand, 9);
  s = await neueSeite(browser, profil, { "gremien.json": (j) => ({ ...j, gremien: j.gremien.map((g) => (g.key === "rat"
    ? { ...g, naechste_sitzung: { date: j.meta.datenstand, time: "17:00", web: null, source_object: "https://example.invalid/oparl/meetings/a" },
      folgende_sitzung: { date: danach, time: "18:00", web: null, source_object: "https://example.invalid/oparl/meetings/b" } } : g)) }) },
  new Date(morgen + "T11:00:00Z"));
  await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste&kennung=rat`, { waitUntil: "load" });
  await geladen(s.page);
  await flaecheBereit(s.page);
  const rat = await s.page.$eval('#wer-liste details[data-kennung="rat"]', (d) => d.innerText);
  pruefen(profil, "E2: nächste Sitzung am Datenstand vorbei, die folgende erscheint", rat.includes(`nächste Sitzung ${datumDe(danach)}`)
    && rat.includes(`${datumDe(danach)}, 18:00 Uhr`) && !rat.includes(datumDe(gremien.meta.datenstand) + ","), rat.replace(/\s+/g, " ").slice(0, 300));
  await s.ctx.close();
  // Wechsel der Breite: ohne Wahl folgt die Darstellung der Breite (F9), eine ausdrückliche Wahl bleibt
  if (profil === "1440") {
    s = await neueSeite(browser, profil);
    await s.page.setViewportSize({ width: 390, height: 844 });
    await s.page.goto(`${BASIS}?wer=gremien`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    const schmal = await zustand(s.page);
    await s.page.setViewportSize({ width: 1440, height: 900 });
    await s.page.waitForTimeout(300);
    const breit = await zustand(s.page);
    await s.page.click('.wer-darstellung [data-darstellung="liste"]');
    await s.page.setViewportSize({ width: 390, height: 844 });
    await s.page.waitForTimeout(200);
    await s.page.setViewportSize({ width: 1440, height: 900 });
    await s.page.waitForTimeout(300);
    const gewaehlt = await zustand(s.page);
    pruefen(profil, "Breite: ohne Wahl bis 900 px Liste und ab 901 px Schaubild, eine ausdrückliche Wahl bleibt", schmal.liste && breit.schaubild
      && gewaehlt.liste && gewaehlt.offen && (await adresse(s.page)).darstellung === "liste", { schmal: schmal.liste, breit: breit.schaubild, gewaehlt: gewaehlt.liste });
    pruefen(profil, "keine Skriptfehler (Breite)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  }
  void heute;
}

// Nachprüfung Bedienung (23.11.2026): Fokus beim Wechsel der Breite, gescheiterter Import, verzögerter Zähler, Link bei
// offener Fläche, Wahl während des Ladens, aufgelöstes Gremium, Zustand aus der Adresse im Bild, „Filter und Zeitraum
// zurücksetzen“, Telefonbreite neben dem Vorgang, Höhe der Statuszeile, 320 px ohne waagrechtes Scrollen; jede Prüfung
// mit eigener Seite
const umfeld = (profil, gremien) => ({ breit: !telefon(profil), w: PROFILE[profil].viewport.width, h: PROFILE[profil].viewport.height,
  bvs: gremien.gremien.filter((g) => g.gruppe === "bezirksvertretung" && !g.aufgeloest), alt: gremien.gremien.find((g) => g.aufgeloest) });
const BEDIENUNG = {
  // Wechsel der Breite ohne ausdrückliche Wahl: gleiche Darstellung → kein Neuaufbau, Fokus bleibt; andere Darstellung →
  // Fokus auf demselben Gremium bzw. im Schaubild auf dem gewählten Optionsfeld
  async breiteFokus(browser, profil, gremien, gebiet) {
    const { breit, w, h, bvs } = umfeld(profil, gremien);
    let s;
    if (breit) {
      const bv = bvs[0], anders = w === 1440 ? 1200 : 1280;
      s = await neueSeite(browser, profil);
      await s.page.goto(`${BASIS}?wer=gremien`, { waitUntil: "load" });
      await geladen(s.page);
      await flaecheBereit(s.page);
      await s.page.focus(`#wer-body .org-node[data-kennung="${bv.key}"]`);
      await s.page.setViewportSize({ width: anders, height: h });
      await s.page.waitForTimeout(300);
      const a1 = [await fokus(s.page), (await zustand(s.page)).schaubild];
      await s.page.keyboard.press("Enter");
      await s.page.waitForTimeout(150);
      await s.page.setViewportSize({ width: w, height: h });
      await s.page.waitForTimeout(300);
      const a2 = [await fokus(s.page), (await zustand(s.page)).schaubild];
      await s.page.setViewportSize({ width: 900, height: h });
      await s.page.waitForTimeout(300);
      const a3 = [await fokus(s.page), (await zustand(s.page)).liste, await s.page.$$eval("#wer-liste details[open]", (ds) => ds.map((d) => d.dataset.kennung))];
      await s.page.focus("#wer-q");
      await s.page.setViewportSize({ width: w, height: h });
      await s.page.waitForTimeout(300);
      const a4 = [await fokus(s.page), (await zustand(s.page)).schaubild];
      pruefen(profil, `Breite ${w} → ${anders} → ${w} → 900 → ${w}: Fokus auf Knoten, Überschrift im Detail, Eintrag der Liste, Optionsfeld „Schaubild“`,
        a1[0].kennung === bv.key && a1[0].tag === "button" && a1[1] && a2[0].tag === "h3" && a2[0].text === bv.name && a2[1]
        && a3[0].tag === "summary" && a3[0].kennung === bv.key && a3[1] && JSON.stringify(a3[2]) === JSON.stringify([bv.key])
        && a4[0].text === "Schaubild" && a4[0].sichtbar && a4[1], { a1, a2, a3, a4 });
      pruefen(profil, "keine Skriptfehler (Breite und Fokus)", s.fehler.length === 0, s.fehler);
      await s.ctx.close();
    }
  },
  // gescheiterter Import von gremien.js: Satz in der Statuszeile, beim nächsten Öffnen ein neuer Abruf des Moduls
  async importUndZaehler(browser, profil, gremien, gebiet) {
    let s, z;
    let module = 0;
    s = await neueSeite(browser, profil);
    await s.page.route((u) => u.pathname.endsWith("/gremien.js"), (r) => { module++; return module === 1 ? r.fulfill({ status: 404, body: "" }) : r.continue(); });
    await s.page.goto(BASIS, { waitUntil: "load" });
    await geladen(s.page);
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.click('#mega-entscheiden [data-wer="gremien"]');
    await s.page.waitForFunction(() => /konnten nicht geladen werden/.test(document.getElementById("wer-status").textContent), null, { timeout: 20000 });
    await s.page.keyboard.press("Escape");
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.click('#mega-entscheiden [data-wer="gremien"]');
    await flaecheBereit(s.page);
    await s.page.waitForTimeout(300);
    z = await zustand(s.page);
    pruefen(profil, "gescheiterter Import: beim nächsten Öffnen neuer Abruf des Moduls mit Erfolg", module === 2 && (z.schaubild || z.liste), { module, status: z.status });
    // verzögerter Zähler der Liste: nach schnellem Wechsel zu „Ämter“ bleibt die Statuszeile leer
    await s.page.click('.wer-darstellung [data-darstellung="liste"]');
    await s.page.fill("#wer-q", "bez");
    await s.page.click("#tab-wer-aemter");
    await s.page.waitForTimeout(700);
    z = await zustand(s.page);
    pruefen(profil, "Zähler der Liste: nach Wechsel zu „Ämter“ innerhalb von 400 ms keine Zahl in der Statuszeile", z.aemter >= 2 && z.status === "", z.status);
    pruefen(profil, "keine Skriptfehler (Import und Zähler)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // Wahl während des Ladens: Klick auf „Ämter“ gilt nach dem Laden, Fokus auf dem gewählten Reiter
  async wahlBeimLaden(browser, profil, gremien, gebiet) {
    let s, z, f;
    s = await neueSeite(browser, profil, { "gremien.json": async (j, route) => { await new Promise((ok) => setTimeout(ok, 1500)); return route.continue(); } });
    await s.page.goto(BASIS, { waitUntil: "load" });
    await geladen(s.page);
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.click('#mega-entscheiden [data-wer="gremien"]');
    await s.page.waitForTimeout(200);
    const beim = (await zustand(s.page)).status;
    await s.page.click("#tab-wer-aemter");
    await s.page.waitForFunction(() => document.querySelector("#wer-body .wer-dezernat"), null, { timeout: 20000 });
    await s.page.waitForTimeout(300);
    z = await zustand(s.page);
    f = await fokus(s.page);
    pruefen(profil, "Klick auf „Ämter“ während des Ladens: nach dem Laden Reiter „Ämter“, Fokus auf ihm (tabindex 0)", beim === "Wird geladen …"
      && z.tabs[1][1] === "true" && z.tabs[1][2] === 0 && z.tabs[0][2] === -1 && f.id === "tab-wer-aemter" && (await adresse(s.page)).wer === "aemter", { beim, tabs: z.tabs, f });
    await s.ctx.close();
  },
  // aufgelöstes Gremium aus der Adresse: ohne Darstellung die Liste mit „frühere Gremien zeigen“; mit „Schaubild“ ein
  // Hinweis auf die Liste statt seiner Angaben
  async aufgeloest(browser, profil, gremien, gebiet) {
    const { alt } = umfeld(profil, gremien);
    let s, z;
    if (alt) {
      s = await neueSeite(browser, profil);
      await s.page.goto(`${BASIS}?wer=gremien&kennung=${alt.key}`, { waitUntil: "load" });
      await geladen(s.page);
      await flaecheBereit(s.page);
      z = await zustand(s.page);
      const liste = await s.page.evaluate((k) => ({ frueher: document.getElementById("wer-frueher")?.checked, offen: [...document.querySelectorAll("#wer-liste details[open]")].map((d) => d.dataset.kennung) }), alt.key);
      const a = await adresse(s.page);
      pruefen(profil, "aufgelöstes Gremium aus der Adresse: Liste mit früheren Gremien, Eintrag offen, Adresse mit darstellung=liste", z.liste && liste.frueher
        && JSON.stringify(liste.offen) === JSON.stringify([alt.key]) && a.darstellung === "liste" && a.kennung === alt.key, { liste, a });
      await s.page.goto(`${BASIS}?wer=gremien&darstellung=schaubild&kennung=${alt.key}`, { waitUntil: "load" });
      await geladen(s.page);
      await flaecheBereit(s.page);
      const bild = await s.page.evaluate(() => ({ h3: Boolean(document.querySelector("#wer-detail h3")), text: document.getElementById("wer-detail").innerText.trim(),
        gedrueckt: document.querySelectorAll('#wer-body [aria-pressed="true"]').length }));
      pruefen(profil, "aufgelöstes Gremium im Schaubild: Hinweis auf die Liste statt seiner Angaben", !bild.h3 && bild.gedrueckt === 0
        && bild.text === `Das gewählte Gremium „${alt.name}“ ist aufgelöst; es steht in der Liste unter „frühere Gremien zeigen“.`, bild);
      await axe(s.page, profil, "aufgelöstes Gremium im Schaubild");
      await s.ctx.close();
    }
  },
  // Zustand aus der Adresse: das gewählte Gremium steht im sichtbaren Teil der Fläche (ohne Fokuswechsel)
  async adresseUndStatuszeile(browser, profil, gremien, gebiet) {
    const { bvs } = umfeld(profil, gremien);
    let s;
    const letzte = bvs[bvs.length - 1];
    s = await neueSeite(browser, profil);
    await s.page.goto(`${BASIS}?wer=gremien&kennung=${letzte.key}`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    await s.page.waitForTimeout(300);
    const lage = await s.page.evaluate((k) => {
      const b = document.getElementById("wer-body").getBoundingClientRect();
      const e = (document.querySelector("#wer-detail h3") || document.querySelector(`#wer-liste details[data-kennung="${k}"] summary`)).getBoundingClientRect();
      return { flaeche: [Math.round(b.top), Math.round(b.bottom)], ziel: [Math.round(e.top), Math.round(e.bottom)] };
    }, letzte.key);
    pruefen(profil, "Adresse mit Kennung: Eintrag im sichtbaren Teil der Fläche", lage.ziel[0] >= lage.flaeche[0] && lage.ziel[1] <= lage.flaeche[1], lage);
    // Statuszeile: Hinweis zur unbekannten Kennung und Zähler der Liste mit allen Einträgen offen in voller Höhe, über dem Inhalt
    await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste&kennung=probe-unbekannt`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    const hoehe = () => s.page.evaluate(() => {
      const st = document.getElementById("wer-status"), r = st.getBoundingClientRect();
      return { box: Math.round(r.height), text: st.scrollHeight, ueber: r.bottom <= document.getElementById("wer-body").getBoundingClientRect().top + 0.5 };
    });
    const h1 = await hoehe();
    if (await s.page.$("#wer-frueher")) await s.page.check("#wer-frueher");
    await s.page.evaluate(() => document.querySelectorAll("#wer-liste details").forEach((d) => { d.open = true; }));
    await s.page.waitForTimeout(200);
    const h2 = await hoehe();
    pruefen(profil, "Statuszeile in voller Höhe über dem Inhalt (unbekannte Kennung, Liste mit allen Einträgen offen)", h1.box >= h1.text && h1.ueber && h2.box >= h2.text && h2.ueber, { h1, h2 });
    await s.ctx.close();
  },
  // 320 px (Telefon): kein waagrechtes Scrollen in der Liste mit allen Einträgen und im Detail eines Ausschusses (1.4.10)
  async schmal320(browser, profil, gremien, gebiet) {
    let s;
    if (telefon(profil)) {
      s = await neueSeite(browser, profil);
      await s.page.setViewportSize({ width: 320, height: 640 });
      await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste`, { waitUntil: "load" });
      await geladen(s.page);
      await flaecheBereit(s.page);
      if (await s.page.$("#wer-frueher")) await s.page.check("#wer-frueher");
      await s.page.evaluate(() => document.querySelectorAll("#wer-liste details").forEach((d) => { d.open = true; }));
      await s.page.waitForTimeout(200);
      const liste = await s.page.$eval("#wer-body", (b) => [b.scrollWidth, b.clientWidth]);
      const aus = gremien.gremien.find((g) => g.gruppe === "ausschuss" && g.paragraf != null && !g.aufgeloest);
      let bild = null;
      if (aus) {
        await s.page.goto(`${BASIS}?wer=gremien&darstellung=schaubild&kennung=${aus.key}`, { waitUntil: "load" });
        await geladen(s.page);
        await flaecheBereit(s.page);
        bild = await s.page.$eval("#wer-body", (b) => [b.scrollWidth, b.clientWidth]);
      }
      pruefen(profil, "320 px: kein waagrechtes Scrollen (Liste mit allen Einträgen, Detail eines Ausschusses)", liste[0] <= liste[1] && (!bild || bild[0] <= bild[1]), { liste, bild });
      await s.ctx.close();
    }
  },
  // Link im Vorgang bei schon offener Fläche (Desktop: der Vorgang bleibt daneben offen): Esc führt zum Link zurück;
  // „Filter und Zeitraum zurücksetzen“ im Satz bei 0 Treffern setzt den Fokus auf die Liste
  async linkUndZuruecksetzen(browser, profil, gremien, gebiet) {
    const { breit } = umfeld(profil, gremien);
    let s, f;
    const datei = `${gebiet.split(":")[0] === "ortsteil" ? "ortsteile" : "bezirke"}/${gebiet.split(":")[1]}.json`;
    let ref = null, key = null;
    s = await neueSeite(browser, profil, { [datei]: (j) => {
      const p = j.papers.find((x) => x.steps.some((st) => st.gremium_key));
      ref = p.reference; key = p.steps.find((x) => x.gremium_key).gremium_key;
      return j;
    }, "gremien.json": (j) => ({ ...j, gremien: [...j.gremien, PROBE] }) });
    await s.page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
    await geladen(s.page);
    if (breit) {
      await s.page.click('.toggle[data-panel="panel-list"]');
      await s.page.click(`#papers button[data-ref="${ref}"]`);
      await s.page.waitForSelector("#detail .steps");
      await menueOeffnen(s.page, profil, "mega-entscheiden");
      await s.page.click('#mega-entscheiden [data-wer="gremien"]');
      await flaecheBereit(s.page);
      await s.page.focus(`#detail [data-gremium-key="${key}"]`);
      await s.page.keyboard.press("Enter");
      await s.page.waitForTimeout(400);
      const nach = await fokus(s.page);
      await s.page.keyboard.press("Escape");
      await s.page.waitForTimeout(300);
      f = await fokus(s.page);
      pruefen(profil, "Link im Vorgang bei offener Fläche: Fokus auf dem Gremium, Esc zurück zum Link", nach.tag === "h3" && f.kennung === key && f.sichtbar, { nach, f });
    }
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.click('#mega-entscheiden [data-wer="gremien"]');
    await flaecheBereit(s.page);
    await s.page.click('.wer-darstellung [data-darstellung="liste"]');
    await s.page.click(`#wer-liste details[data-kennung="${PROBE.key}"] summary`);
    await s.page.click(`#wer-liste details[data-kennung="${PROBE.key}"] .wer-filter`);
    await s.page.waitForSelector("#papers #reset-filters");
    await s.page.focus("#reset-filters");
    await s.page.keyboard.press("Enter");
    await s.page.waitForTimeout(300);
    f = await fokus(s.page);
    const nachReset = await s.page.evaluate(() => ({ kennzeichen: !document.getElementById("gremium-filter").hidden, wert: document.getElementById("f-gremium").value }));
    pruefen(profil, "„Filter und Zeitraum zurücksetzen“ bei 0 Treffern: Filter weg, Fokus auf der Überschrift der Liste", f.id === "list-heading" && !nachReset.kennzeichen && !nachReset.wert, { f, nachReset });
    pruefen(profil, "keine Skriptfehler (Link, Zurücksetzen)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // Wechsel auf Telefonbreite neben dem Vorgang: „Gremien und Ämter“ mit dem Fokus bleibt offen, der Vorgang geht zu
  async telefonbreite(browser, profil, gremien, gebiet) {
    const { bvs } = umfeld(profil, gremien);
    let s, z, f;
    if (profil === "1440") {
      const bv = bvs[Math.min(2, bvs.length - 1)];
      s = await neueSeite(browser, profil);
      await s.page.goto(BASIS, { waitUntil: "load" });
      await geladen(s.page);
      await menueOeffnen(s.page, profil, "mega-entscheiden");
      await s.page.click('#mega-entscheiden [data-wer="gremien"]');
      await flaecheBereit(s.page);
      await s.page.click(`#wer-body .org-node[data-kennung="${bv.key}"]`);
      await s.page.waitForTimeout(200);
      const vorher = await s.page.evaluate(() => !document.getElementById("panel-detail").hidden);
      await s.page.setViewportSize({ width: 900, height: 900 });
      await s.page.waitForTimeout(300);
      z = await zustand(s.page);
      f = await fokus(s.page);
      const a = await adresse(s.page);
      const vorgang = await s.page.evaluate(() => !document.getElementById("panel-detail").hidden);
      pruefen(profil, "1440 → 900 neben dem Vorgang: Fläche mit dem Fokus bleibt offen (Liste, Eintrag fokussiert), Vorgang zu, Adresse mit wer und kennung",
        vorher && z.offen && !vorgang && z.liste && f.tag === "summary" && f.kennung === bv.key && a.wer === "gremien" && a.kennung === bv.key, { vorher, vorgang, f, a });
      pruefen(profil, "keine Skriptfehler (Telefonbreite)", s.fehler.length === 0, s.fehler);
      await s.ctx.close();
    }
  },
};
async function bedienung(browser, profil, gremien, gebiet) {
  for (const f of Object.values(BEDIENUNG)) await f(browser, profil, gremien, gebiet);
}

// Zeitleiste: vergangene Sitzung des Rates mit Hinweis „abgesagt“ aus dem Namen (erfunden) gestrichelt (#47 (3))
async function zeitleiste(browser, profil) {
  const heute = tagInKoeln(new Date());
  let ziel = null;
  const s = await neueSeite(browser, profil, { "zeit.json": (j) => {
    const vergangen = j.meetings.filter((m) => m.gremium === "Rat" && m.date < heute && !m.cancelled);
    ziel = vergangen[vergangen.length - 1];
    return { ...j, meetings: j.meetings.map((m) => (m === ziel ? { ...m, hinweis: "abgesagt", name: `${m.name} - Sitzung entfällt` } : m)) };
  } });
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  await s.page.click('.toggle[data-panel="timeline-wrap"]');
  await s.page.waitForSelector("#timeline-wrap:not([hidden]) svg");
  await s.page.waitForTimeout(400);
  const punkte = await s.page.$$eval("#timeline-wrap circle.tl-meet.cancelled", (cs) => cs.map((c) => ({ klasse: c.getAttribute("class"),
    titel: c.querySelector("title")?.textContent || "" })));
  const treffer = punkte.filter((p) => p.titel.includes("laut Sitzungsnamen abgesagt"));
  pruefen(profil, "Zeitleiste: vergangene Sitzung laut Sitzungsnamen abgesagt gestrichelt mit Titel", Boolean(ziel) && treffer.length === 1
    && treffer[0].klasse === "tl-meet cancelled" && treffer[0].titel.includes("Rat"), { ziel: ziel && ziel.date, treffer });
  await foto(s.page, `zeitleiste-vergangene-absage-${profil}`, "#timeline-wrap");
  await axe(s.page, profil, "Zeitleiste mit vergangener Absage");
  await s.ctx.close();
}

(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });
  try {
    const hilfe = await browser.newPage();
    await hilfe.route((u) => !["127.0.0.1", "localhost"].includes(u.hostname), (r) => r.abort());
    await hilfe.goto(BASIS, { waitUntil: "load" });
    const [index, gremien, suche] = await hilfe.evaluate(async () => Promise.all(["index.json", "gremien.json", "suche.json"]
      .map(async (n) => (await fetch("data/export/koeln/" + n)).json())));
    const gebiet = "ortsteil:" + index.ortsteile.slice().sort((a, b) => b.count - a.count || a.slug.localeCompare(b.slug))[0].slug;
    await hilfe.close();
    for (const profil of Object.keys(PROFILE)) {
      await flaeche(browser, profil, gremien);
      await vorgangUndFilter(browser, profil, gebiet);
      await ganzKoeln(browser, profil, suche);
      await adresseUndDaten(browser, profil, gremien);
      await bedienung(browser, profil, gremien, gebiet);
      if (profil === "1440") await zeitleiste(browser, profil);
    }
  } catch (e) {
    pruefen("-", "Ablauf", false, String(e && e.stack || e).slice(0, 800));
  }
  await browser.close();
  if (AUSGABE) fs.writeFileSync(AUSGABE, JSON.stringify({ ergebnisse }, null, 1));
  console.log(`${befunde} Befunde`);
  process.exit(befunde ? 1 : 0);
})();
