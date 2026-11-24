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
  // textContent mit dem unsichtbaren Zusatz „(unter „Gremien“)“ (23.11.2026 (2) (7)); sichtbar ist der Text ohne die
  // Teile mit der Klasse visually-hidden (innerText zählt sie je nach Breite mit)
  const v = await s.page.evaluate((k) => ({ links: document.querySelectorAll("#detail [data-gremium-key]").length,
    link: document.querySelector(`#detail [data-gremium-key="${k}"]`)?.textContent, sichtbar: (() => {
      const b = document.querySelector(`#detail [data-gremium-key="${k}"]`)?.cloneNode(true);
      if (!b) return null;
      b.querySelectorAll(".visually-hidden").forEach((x) => x.remove());
      return b.textContent;
    })(), plakette: [...document.querySelectorAll("#detail .step-head .badge")].map((b) => b.textContent),
    ohneKennung: [...document.querySelectorAll("#detail .step-head")].filter((h) => !h.querySelector("[data-gremium-key]") && /^(Beratung|Entscheidung)/.test(h.textContent)).length }), key);
  pruefen(profil, "Vorgang: Gremium mit Kennung als Link (Name sichtbar, Zusatz „(unter „Gremien“)“ im zugänglichen Namen), Plakette „laut Sitzungsnamen abgesagt“ an der Station", v.links > 0
    && v.link === `${gremium} (unter „Gremien“)` && v.sichtbar === gremium
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
    liste.oben.includes("gezeigt wird der Stand vom 18.11.2026; deshalb fehlt die nächste Sitzung.") && liste.rat.includes("Stand vom 18.11.2026")
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
  // Wahl während des Ladens: Klick auf „Ämter“ gilt nach dem Laden, Fokus auf dem gewählten Reiter. „Während des
  // Ladens“ heißt: gremien.js ist geladen und init hat die Bedienung angemeldet (bedienen()), gremien.json lädt noch.
  // Die Prüfung wartet auf genau diesen Zustand, die Anfrage nach gremien.json (init stellt sie direkt nach bedienen()),
  // und hält die Antwort zurück, bis der Klick ausgeführt ist. Vorher klickte sie nach festen 200 ms und hielt
  // gremien.json 1,5 s zurück; lud das Modul gremien.js länger als 200 ms, traf der Klick einen Reiter ohne Bedienung,
  // ging verloren, und das Warten auf „Ämter“ endete nach 20 s (einmal gescheitert, danach sechs Läufe ohne Befund)
  async wahlBeimLaden(browser, profil, gremien, gebiet) {
    let s, z, f;
    let angefragt, freigeben, gehalten = false, anfragen = 0;
    const anfrage = new Promise((ok) => { angefragt = ok; }), freigabe = new Promise((ok) => { freigeben = ok; });
    s = await neueSeite(browser, profil, { "gremien.json": async (j, route) => {
      if (!gehalten) return route.continue();
      anfragen++;
      angefragt();
      await freigabe;
      return route.continue();
    } });
    await s.page.goto(BASIS, { waitUntil: "load" });
    await geladen(s.page);
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    gehalten = true;
    await s.page.click('#mega-entscheiden [data-wer="gremien"]');
    const bereit = await Promise.race([anfrage.then(() => true), new Promise((ok) => setTimeout(() => ok(false), 20000))]);
    const beim = (await zustand(s.page)).status;
    if (bereit) await s.page.click("#tab-wer-aemter");
    freigeben();
    const ok = bereit && await s.page.waitForFunction(() => document.querySelector("#wer-body .wer-dezernat"), null, { timeout: 20000 }).then(() => true, () => false);
    await s.page.waitForTimeout(300);
    z = await zustand(s.page);
    f = await fokus(s.page);
    pruefen(profil, "Klick auf „Ämter“ während des Ladens: nach dem Laden Reiter „Ämter“, Fokus auf ihm (tabindex 0)", ok && anfragen === 1 && beim === "Wird geladen …"
      && z.tabs[1][1] === "true" && z.tabs[1][2] === 0 && z.tabs[0][2] === -1 && f.id === "tab-wer-aemter" && (await adresse(s.page)).wer === "aemter",
      { bereit, anfragen, beim, tabs: z.tabs, f });
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

// Entscheidung 23.11.2026 (2), Punkte 1–17 aus #50 (Folge-PR): je Punkt eine eigene Seite, axe in jedem neuen Zustand;
// (15) bei 320 × 256 CSS-Pixeln (400 % Zoom), (16) auf dem iPhone 13. Punkt (1) betrifft nur die Datenbeschreibungen
// (tests/test_wer_entscheidet_folge.py), (5) und (7) prüfen auch die angepassten Prüfungen oben.
const SATZ_JAHRE = "„Vorlagen dieses Gremiums“ zeigt die Vorlagen aller Jahre; die Zahl der Vorlagen oben gilt nur für die 12 Monate.";
const VORBEI = "Die bekannten Sitzungen sind vorbei; der nächste Abruf ergänzt die Liste der Sitzungen.";
const UNBEKANNT = "Das Gremium aus dem Link ist unter „Gremien“ nicht verzeichnet; seine Kennung kann sich geändert haben. Die Liste ist nicht nach Gremium gefiltert.";
const LADEFEHLER = "Die Angaben zu Gremien und Ämtern konnten nicht geladen werden. Beim nächsten Öffnen versucht der Ratsatlas es erneut.";
const LADEFEHLER_MM = "Die Fläche „Mitmachen in Köln“ konnte nicht geladen werden. Beim nächsten Öffnen versucht der Ratsatlas es erneut.";
const SATZ_GREMIEN_FEHLEN = "Die Angaben zum Gremium aus dem Link konnten nicht geladen werden; die Liste ist nicht nach Gremium gefiltert. Beim Neuladen der Seite versucht der Ratsatlas es erneut.";
const gebietsdatei = (gebiet) => `${gebiet.split(":")[0] === "ortsteil" ? "ortsteile" : "bezirke"}/${gebiet.split(":")[1]}.json`;
const liste = async (page, profil) => {
  if (!(await page.evaluate(() => document.getElementById("panel-list").hidden))) return;
  if (telefon(profil) && !(await page.evaluate(() => document.body.classList.contains("nav-open")))) await page.click("#nav-burger");
  await page.click('.toggle[data-panel="panel-list"]');
};
const listenStand = (page) => page.evaluate(() => ({ count: document.getElementById("count").textContent, kennzeichen: !document.getElementById("gremium-filter").hidden
  ? document.getElementById("gremium-filter").innerText.trim() : null, wert: document.getElementById("f-gremium").value,
  n: document.querySelectorAll("#papers button[data-ref], #papers button[data-gref]").length, fokus: document.activeElement.id }));
const FOLGE = {
  // (2), (4), (8), (17): Satz am Knopf mit aria-describedby, „Tagesordnung noch nicht veröffentlicht“, Einleitung
  // „Ämter“ ohne Untereinheiten, Abschnitte ohne Namen (keine Landmarken)
  async detailUndAemter(browser, profil, gremien) {
    const tag = plusTage(gremien.meta.datenstand, 5);
    const s = await neueSeite(browser, profil, { "gremien.json": (j) => ({ ...j, gremien: j.gremien.map((g) => (g.key === "rat"
      ? { ...g, naechste_sitzung: { date: tag, time: "17:00", web: null, source_object: "https://example.invalid/oparl/meetings/probe" }, folgende_sitzung: undefined } : g)) }) });
    await s.page.goto(`${BASIS}?wer=gremien&darstellung=schaubild&kennung=rat`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    const d = await s.page.evaluate(() => {
      const b = document.querySelector("#wer-detail .wer-filter"), ziel = b && document.getElementById(b.getAttribute("aria-describedby") || "-");
      return { satz: ziel ? ziel.textContent : null, sichtbar: Boolean(ziel && ziel.getClientRects().length), text: document.getElementById("wer-detail").innerText,
        regionen: document.querySelectorAll("#wer-body section[aria-labelledby], #wer-body section[aria-label], #wer-body [role=region]").length,
        h3: document.querySelectorAll("#wer-body .org-h, #wer-body h3").length };
    });
    pruefen(profil, "(2) Satz neben „Vorlagen dieses Gremiums“ über aria-describedby, sichtbar", d.satz === SATZ_JAHRE && d.sichtbar, d.satz);
    pruefen(profil, "(4) nächste Sitzung ohne Link: „Tagesordnung noch nicht veröffentlicht“", d.text.includes(`${datumDe(tag)}, 17:00 Uhr · Tagesordnung noch nicht veröffentlicht`),
      d.text.replace(/\s+/g, " ").slice(0, 300));
    pruefen(profil, "(17) Schaubild: Abschnitte ohne Namen (keine Landmarken), Überschriften gliedern", d.regionen === 0 && d.h3 >= 3, { regionen: d.regionen, h3: d.h3 });
    await axe(s.page, profil, "(2)(4) Detail mit Satz zum Knopf und ohne Tagesordnung");
    await s.page.click("#tab-wer-aemter");
    await s.page.waitForSelector("#wer-body .wer-dezernat");
    const a = await s.page.evaluate(() => ({ einleitung: document.querySelector("#wer-body > p.hint").textContent,
      regionen: document.querySelectorAll("#wer-body section[aria-labelledby], #wer-body section[aria-label], #wer-body [role=region]").length,
      h3: document.querySelectorAll("#wer-body .wer-dezernat > h3").length, abschnitte: document.querySelectorAll("#wer-body .wer-dezernat").length }));
    pruefen(profil, "(8) Einleitung „Ämter“ ohne die Untereinheiten; (17) Dezernate ohne Namen, je mit h3", a.einleitung.endsWith("Punktdienststellen, ohne die Untereinheiten der Dienststellen.")
      && a.regionen === 0 && a.h3 === a.abschnitte && a.abschnitte >= 2, a);
    await axe(s.page, profil, "(8)(17) Ämter");
    pruefen(profil, "keine Skriptfehler (Folge: Detail und Ämter)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // (3): alle bekannten Sitzungen vor dem Tag der Besucher:innen → ein Satz statt nichts
  async vorbei(browser, profil, gremien) {
    const ds = gremien.meta.datenstand;
    const s = await neueSeite(browser, profil, { "gremien.json": (j) => ({ ...j, gremien: j.gremien.map((g) => (g.key === "rat"
      ? { ...g, naechste_sitzung: { date: ds, time: "17:00", web: null, source_object: "https://example.invalid/oparl/meetings/a" },
        folgende_sitzung: { date: plusTage(ds, 1), time: "17:00", web: null, source_object: "https://example.invalid/oparl/meetings/b" } } : g)) }) },
    new Date(plusTage(ds, 3) + "T11:00:00Z"));
    await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste&kennung=rat`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    const t = await s.page.$eval('#wer-liste details[data-kennung="rat"]', (d) => d.innerText);
    pruefen(profil, "(3) bekannte Sitzungen vorbei: Satz statt nichts, keine nächste Sitzung", t.includes(VORBEI) && !t.includes("Nächste Sitzung:") && !t.includes("nächste Sitzung "), t.replace(/\s+/g, " ").slice(0, 300));
    await axe(s.page, profil, "(3) bekannte Sitzungen vorbei");
    await s.ctx.close();
  },
  // (6), (10): Filter über den Namen mit „Gremium (nach Namen)“ im Gebiet und in ganz Köln; Adresse gremium_filter beim
  // Setzen, Laden (Gebiet, ganz Köln mit wer/kennung und Vorgang), Entfernen; unbekannte Kennung; kein Eintrag im Verlauf
  async filterUndAdresse(browser, profil, gremien, gebiet) {
    const datei = gebietsdatei(gebiet);
    let ref = null, key = null, name = null;
    const aenderung = { [datei]: (j) => {
      const p = j.papers.find((x) => x.process.some((st) => st.gremium_key && st.gremium));
      const st = p.process.find((x) => x.gremium_key && x.gremium);
      ref = p.reference; key = st.gremium_key; name = st.gremium;
      // erfundene Station ohne Kennung mit demselben Namen: ergibt die Gruppe „nach Namen, auch frühere Gremien“
      const { gremium_key, ...ohne } = st;
      p.process = [...p.process, ohne];
      return j;
    } };
    let s = await neueSeite(browser, profil, aenderung);
    await s.page.goto(`${BASIS}?gebiet=${gebiet}`, { waitUntil: "load" });
    await geladen(s.page);
    await liste(s.page, profil);
    const verlauf = await s.page.evaluate(() => history.length);
    await s.page.evaluate(() => { document.getElementById("more-filters").open = true; });
    await s.page.selectOption("#f-gremium", `name:${name}`);
    await s.page.waitForTimeout(300);
    let l = await listenStand(s.page), a = await adresse(s.page);
    pruefen(profil, "(6)(10) Filter über den Namen im Gebiet: Kennzeichen und #count „Gremium (nach Namen)“, Adresse gremium_filter=name:…, kein Eintrag im Verlauf",
      l.kennzeichen === `Gremium (nach Namen): ${name}` && l.count.includes(`· Gremium (nach Namen): ${name}`) && a.gremium_filter === `name:${name}` && !("gremium" in a)
      && (await s.page.evaluate(() => history.length)) === verlauf, { l, a });
    await axe(s.page, profil, "(6) Filter „Gremium (nach Namen)“ im Gebiet");
    await s.page.check('input[name="scope"][value="koeln"]');
    await s.page.waitForFunction(() => /Treffer in ganz Köln/.test(document.getElementById("count").textContent), null, { timeout: 20000 });
    l = await listenStand(s.page);
    pruefen(profil, "(6) derselbe Filter in ganz Köln: #count „Gremium (nach Namen)“, Kennzeichen", l.count.includes(`Treffer in ganz Köln · Gremium (nach Namen): ${name}`)
      && l.kennzeichen === `Gremium (nach Namen): ${name}` && l.n > 0, l);
    await axe(s.page, profil, "(6) Filter „Gremium (nach Namen)“ in ganz Köln");
    // Kennung (im Gebiet, dort stehen die weiteren Filter): weiter „Gremium: …“; Kennzeichen mit der Tastatur entfernen →
    // Parameter weg, Fokus auf der Liste
    await s.page.check('input[name="scope"][value="gebiet"]');
    await s.page.evaluate(() => { document.getElementById("more-filters").open = true; });
    await s.page.selectOption("#f-gremium", key);
    await s.page.waitForTimeout(300);
    l = await listenStand(s.page);
    a = await adresse(s.page);
    pruefen(profil, "(6)(10) Filter über die Kennung: „Gremium: …“, Adresse gremium_filter=Kennung", l.kennzeichen === `Gremium: ${name}` && l.count.includes(`· Gremium: ${name}`)
      && a.gremium_filter === key, { l, a });
    await s.page.focus("#gremium-filter-aus");
    await s.page.keyboard.press("Enter");
    await s.page.waitForTimeout(300);
    l = await listenStand(s.page);
    a = await adresse(s.page);
    pruefen(profil, "(10) Kennzeichen mit Enter entfernt: kein gremium_filter, Fokus auf der Liste", !l.kennzeichen && !("gremium_filter" in a) && l.fokus === "list-heading", { l, a });
    await s.ctx.close();
    // Laden im Gebiet: Kennung aus der Adresse → Liste offen, Kennzeichen, Auswahl, #count
    s = await neueSeite(browser, profil, aenderung);
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&gremium_filter=${encodeURIComponent(key)}`, { waitUntil: "load" });
    await geladen(s.page);
    await s.page.waitForTimeout(300);
    l = await listenStand(s.page);
    a = await adresse(s.page);
    const offen = await s.page.evaluate(() => !document.getElementById("panel-list").hidden);
    pruefen(profil, "(10) Laden im Gebiet mit gremium_filter: Liste offen, Kennzeichen, Auswahl und #count, Parameter bleibt", offen && l.kennzeichen === `Gremium: ${name}`
      && l.wert === key && l.count.includes(`· Gremium: ${name}`) && a.gremium_filter === key && l.n > 0, { offen, l, a });
    await axe(s.page, profil, "(10) Filter aus der Adresse im Gebiet");
    // Laden in ganz Köln zusammen mit wer, kennung und dem Vorgang im Anker
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&suche=koeln&gremium_filter=${encodeURIComponent(key)}&wer=gremien&darstellung=liste&kennung=${key}#${encodeURIComponent(ref)}`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    await s.page.waitForFunction(() => /Treffer in ganz Köln/.test(document.getElementById("count").textContent), null, { timeout: 20000 });
    l = await listenStand(s.page);
    a = await adresse(s.page);
    const mehr = await s.page.evaluate(() => ({ hash: decodeURIComponent(location.hash.slice(1)), wer: !document.getElementById("panel-gremien").hidden,
      offen: [...document.querySelectorAll("#wer-liste details[open]")].map((x) => x.dataset.kennung) }));
    pruefen(profil, "(10) Laden in ganz Köln mit gremium_filter, wer, kennung und Vorgang: alles wiederhergestellt", l.count.includes(`Treffer in ganz Köln · Gremium: ${name}`)
      && l.wert === key && a.gremium_filter === key && a.suche === "koeln" && a.wer === "gremien" && a.kennung === key && mehr.hash === ref && mehr.wer
      && JSON.stringify(mehr.offen) === JSON.stringify([key]), { l, a, mehr });
    await axe(s.page, profil, "(10) Filter, Gremien und Vorgang aus der Adresse");
    // Name aus der Adresse und unbekannte Kennung
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&gremium_filter=${encodeURIComponent("name:" + name)}`, { waitUntil: "load" });
    await geladen(s.page);
    await s.page.waitForTimeout(300);
    l = await listenStand(s.page);
    pruefen(profil, "(10) Name aus der Adresse: „Gremium (nach Namen)“", l.kennzeichen === `Gremium (nach Namen): ${name}` && l.wert === `name:${name}`, l);
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&gremium_filter=gibt-es-nicht`, { waitUntil: "load" });
    await geladen(s.page);
    await s.page.waitForTimeout(500);
    l = await listenStand(s.page);
    a = await adresse(s.page);
    pruefen(profil, "(10) unbekannte Kennung: kein Filter, #count sagt es, Parameter danach weg", !l.kennzeichen && l.wert === "" && l.count.endsWith(UNBEKANNT)
      && !("gremium_filter" in a), { l, a });
    await axe(s.page, profil, "(10) unbekannte Kennung aus der Adresse");
    // die nächste Änderung der Filter beendet den Satz
    await liste(s.page, profil);
    await s.page.selectOption("#f-stand", { index: 1 });
    await s.page.waitForTimeout(300);
    l = await listenStand(s.page);
    pruefen(profil, "(10) Satz zur unbekannten Kennung endet mit der nächsten Änderung der Filter", !l.count.includes("aus dem Link"), l.count);
    pruefen(profil, "keine Skriptfehler (Folge: Filter und Adresse)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // (11): 20 s ohne Antwort (Uhr der Seite vorgestellt): Satz in der Statuszeile, neuer Versuch beim nächsten Öffnen;
  // die späte Antwort ändert nichts; ebenso „Mitmachen in Köln“
  async wartezeit(browser, profil) {
    const s = await neueSeite(browser, profil);
    const gehalten = [];
    let daten = 0, modulGremien = 0, modulMm = 0;
    const mmAdressen = [];
    await s.page.route((u) => u.pathname.endsWith("/data/export/koeln/gremien.json"), (r) => { daten++; if (daten === 1) gehalten.push(r); else r.continue(); });
    await s.page.route((u) => u.pathname.endsWith("/beteiligung.js"), (r) => { modulMm++; mmAdressen.push(new URL(r.request().url()).search); if (modulMm === 1) gehalten.push(r); else r.continue(); });
    await s.page.route((u) => u.pathname.endsWith("/gremien.js"), (r) => { modulGremien++; r.continue(); });
    await s.page.clock.install();
    await s.page.goto(BASIS, { waitUntil: "load" });
    await geladen(s.page);
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.focus('#mega-entscheiden [data-wer="gremien"]');
    await s.page.keyboard.press("Enter");
    await s.page.waitForFunction(() => document.getElementById("wer-status").textContent === "Wird geladen …" || document.querySelector("#wer-body .org, #wer-body #wer-liste"));
    await s.page.waitForTimeout(500);
    const vorher = (await zustand(s.page)).status;
    await s.page.clock.fastForward(21000);
    await s.page.waitForFunction(() => /konnten nicht geladen werden/.test(document.getElementById("wer-status").textContent), null, { timeout: 10000 });
    const fehler1 = await s.page.evaluate(() => ({ status: document.getElementById("wer-status").textContent, inhalt: document.getElementById("wer-body").textContent.trim() }));
    await axe(s.page, profil, "(11) Zeitüberschreitung „Gremien und Ämter“");
    // späte Antwort des ersten Abrufs: ohne Wirkung
    for (const r of gehalten.splice(0)) await r.continue().catch(() => {});
    await s.page.waitForTimeout(400);
    const spaet = (await zustand(s.page)).status;
    await s.page.keyboard.press("Escape");
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.focus('#mega-entscheiden [data-wer="gremien"]');
    await s.page.keyboard.press("Enter");
    await flaecheBereit(s.page);
    await s.page.waitForTimeout(400);
    const z = await zustand(s.page);
    pruefen(profil, "(11) gremien.json 20 s ohne Antwort: Satz in der Statuszeile, späte Antwort ohne Wirkung, neuer Versuch mit Erfolg", vorher === "Wird geladen …"
      && fehler1.status === LADEFEHLER && fehler1.inhalt === "" && spaet === LADEFEHLER && daten === 2 && (z.schaubild || z.liste) && z.status !== LADEFEHLER, { vorher, fehler1, spaet, daten, status: z.status });
    await s.page.keyboard.press("Escape");
    // Mitmachen: Modul 20 s ohne Antwort
    await menueOeffnen(s.page, profil, "mega-mitmachen");
    await s.page.focus("#cta-mitmachen");
    await s.page.keyboard.press("Enter");
    await s.page.waitForSelector("#panel-mitmachen:not([hidden])");
    await s.page.waitForTimeout(300);
    const mmVorher = await s.page.$eval("#bt-status", (e) => e.textContent);
    await s.page.clock.fastForward(21000);
    await s.page.waitForFunction(() => /konnte nicht geladen werden/.test(document.getElementById("bt-status").textContent), null, { timeout: 10000 });
    const mmFehler = await s.page.evaluate(() => ({ status: document.getElementById("bt-status").textContent, rolle: document.getElementById("bt-status").getAttribute("role"),
      inhalt: document.getElementById("bt-body").textContent.trim() }));
    await axe(s.page, profil, "(11) Zeitüberschreitung „Mitmachen in Köln“");
    for (const r of gehalten.splice(0)) await r.continue().catch(() => {});
    await s.page.waitForTimeout(400);
    const mmSpaet = await s.page.$eval("#bt-status", (e) => e.textContent);
    await s.page.keyboard.press("Escape");
    await menueOeffnen(s.page, profil, "mega-mitmachen");
    await s.page.focus("#cta-mitmachen");
    await s.page.keyboard.press("Enter");
    await s.page.waitForSelector("#panel-mitmachen:not([hidden]) #bt-bezirk", { timeout: 20000 });
    const mmDanach = { status: await s.page.$eval("#bt-status", (e) => e.textContent), adressen: mmAdressen };
    pruefen(profil, "(11) beteiligung.js 20 s ohne Antwort: Satz in #bt-status (role=status), späte Antwort ohne Wirkung, neuer Versuch unter ?versuch=1",
      mmVorher === "Wird geladen …" && mmFehler.status === LADEFEHLER_MM && mmFehler.rolle === "status" && mmFehler.inhalt === "" && mmSpaet === LADEFEHLER_MM
      && modulMm === 2 && mmDanach.status === "" && JSON.stringify(mmDanach.adressen) === '["","?versuch=1"]', { mmVorher, mmFehler, mmSpaet, modulMm, mmDanach });
    await axe(s.page, profil, "(11) „Mitmachen in Köln“ nach dem neuen Versuch");
    pruefen(profil, "keine Skriptfehler (Folge: Wartezeit)", s.fehler.length === 0, s.fehler);
    void modulGremien;
    await s.ctx.close();
  },
  // (12) Esc im Suchfeld: erst leeren, dann schließen; (14) kennung folgt dem zuletzt geöffneten offenen Eintrag
  async escUndKennung(browser, profil, gremien) {
    const s = await neueSeite(browser, profil);
    await s.page.goto(BASIS, { waitUntil: "load" });
    await geladen(s.page);
    await menueOeffnen(s.page, profil, "mega-entscheiden");
    await s.page.click('#mega-entscheiden [data-wer="gremien"]');
    await flaecheBereit(s.page);
    if (!(await zustand(s.page)).liste) await s.page.click('.wer-darstellung [data-darstellung="liste"]');
    await s.page.waitForSelector("#wer-q");
    // (14) mit der Tastatur: drei Einträge öffnen, in anderer Reihenfolge schließen
    const keys = gremien.gremien.filter((g) => !g.aufgeloest).slice(0, 3).map((g) => g.key);
    const umschalten = async (k) => { await s.page.focus(`#wer-liste details[data-kennung="${k}"] > summary`); await s.page.keyboard.press("Enter"); await s.page.waitForTimeout(150); return (await adresse(s.page)).kennung || null; };
    const folge = [];
    for (const k of keys) folge.push(await umschalten(k));
    folge.push(await umschalten(keys[2]), await umschalten(keys[0]), await umschalten(keys[1]));
    pruefen(profil, "(14) kennung: A, B, C öffnen → C; C zu → B; A zu → B; B zu → keine", JSON.stringify(folge) === JSON.stringify([keys[0], keys[1], keys[2], keys[1], keys[1], null]), { folge, keys });
    await axe(s.page, profil, "(14) Liste nach Auf- und Zuklappen");
    // (12)
    await s.page.focus("#wer-q");
    await s.page.keyboard.type("bez");
    await s.page.waitForTimeout(600);
    const gefiltert = (await zustand(s.page)).status;
    await s.page.keyboard.press("Escape");
    await s.page.waitForTimeout(200);
    const e1 = await s.page.evaluate(() => ({ wert: document.getElementById("wer-q")?.value, fokus: document.activeElement.id, offen: !document.getElementById("panel-gremien").hidden,
      status: document.getElementById("wer-status").textContent, eintraege: document.querySelectorAll("#wer-liste details").length }));
    const alle = gremien.gremien.filter((g) => !g.aufgeloest).length;
    pruefen(profil, "(12) erstes Esc im gefüllten Suchfeld: Feld leer, Liste und Statuszeile neu, Fläche offen, Fokus bleibt", gefiltert !== e1.status && e1.wert === "" && e1.fokus === "wer-q"
      && e1.offen && e1.status === `${alle} Gremien` && e1.eintraege === alle, { gefiltert, e1 });
    await axe(s.page, profil, "(12) Suchfeld nach Esc geleert");
    await s.page.keyboard.press("Escape");
    await s.page.waitForTimeout(250);
    const z = await zustand(s.page), f = await fokus(s.page);
    pruefen(profil, "(12) zweites Esc bei leerem Feld: Fläche zu, Fokus zurück", !z.offen && (telefon(profil) ? f.id === "nav-burger" : f.mega === "mega-entscheiden") && f.sichtbar, f);
    pruefen(profil, "keine Skriptfehler (Folge: Esc und Kennung)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // (13) Suchindex fehlt in ganz Köln: Liste leer, Satz in #count, „Erneut versuchen“ mit der Tastatur, Filter bleibt
  async suchindex(browser, profil, gremien, gebiet) {
    let aus = true, abrufe = 0;
    const s = await neueSeite(browser, profil, { "suche.json": async (j, route) => { abrufe++; return aus ? route.fulfill({ status: 503, body: "" }) : route.continue(); } });
    const g = gremien.gremien.find((x) => x.key === "rat");
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&suche=koeln&gremium_filter=rat`, { waitUntil: "load" });
    await s.page.waitForFunction(() => document.getElementById("suche-erneut"), null, { timeout: 30000 });
    await s.page.waitForTimeout(300);
    let l = await listenStand(s.page);
    const eintraege = await s.page.$$eval("#papers > li", (ls) => ls.map((x) => x.className));
    pruefen(profil, "(13) Suchindex fehlt: Liste ohne alte Einträge, Satz in #count, „Erneut versuchen“, Filter und Kennzeichen bleiben",
      l.count === "Der Suchindex konnte nicht geladen werden (HTTP 503)." && l.n === 0 && JSON.stringify(eintraege) === '["empty-list"]'
      && l.kennzeichen === `Gremium: ${g.name}` && l.wert === "rat", { l, eintraege, abrufe });
    await axe(s.page, profil, "(13) Suchindex fehlt");
    aus = false;
    await s.page.focus("#suche-erneut");
    await s.page.keyboard.press("Enter");
    await s.page.waitForFunction(() => /Treffer in ganz Köln/.test(document.getElementById("count").textContent), null, { timeout: 20000 });
    await s.page.waitForTimeout(200);
    l = await listenStand(s.page);
    pruefen(profil, "(13) „Erneut versuchen“ mit Enter: Liste mit Treffern, Fokus auf der Überschrift der Liste, Filter bleibt", l.n > 0 && l.fokus === "list-heading"
      && l.count.includes(`· Gremium: ${g.name}`) && l.kennzeichen === `Gremium: ${g.name}`, l);
    await axe(s.page, profil, "(13) Suchindex nach neuem Versuch");
    pruefen(profil, "keine Skriptfehler (Folge: Suchindex)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // Nachprüfung (10), (11): Filter aus der Adresse, wenn gremien.json nicht antwortet (Start wartet nicht, Vorgang aus
  // dem Anker, nach 20 s ein Satz in #count), spät antwortet (setzt den Filter, der inzwischen geöffnete Vorgang bleibt),
  // fehlt (eigener Satz statt „nicht verzeichnet“) oder ein aufgelöstes Gremium nennt (Filter über den Namen)
  async filterAusAdresseNachpruefung(browser, profil, gremien, gebiet) {
    const hilfe = await neueSeite(browser, profil);
    await hilfe.page.goto(BASIS, { waitUntil: "load" });
    const gebietsdaten = await hilfe.page.evaluate(async (d) => (await fetch("data/export/koeln/" + d)).json(), gebietsdatei(gebiet));
    await hilfe.ctx.close();
    const imGebiet = new Set(gebietsdaten.papers.flatMap((x) => (x.process || []).map((st) => st.gremium_key).filter(Boolean)));
    const ohne = gremien.gremien.find((g) => g.key && !g.aufgeloest && !imGebiet.has(g.key));
    const alt = gremien.gremien.find((g) => g.key && g.aufgeloest && g.name);
    const ref = gebietsdaten.papers[0].reference;
    // (a) gremien.json antwortet nie
    let s = await neueSeite(browser, profil);
    await s.page.route((u) => u.pathname.endsWith("/data/export/koeln/gremien.json"), () => {});
    await s.page.clock.install();
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&gremium_filter=${ohne.key}&wer=gremien#${encodeURIComponent(ref)}`, { waitUntil: "load" });
    await s.page.waitForSelector("#detail .steps", { state: "attached", timeout: 20000 });
    await s.page.waitForTimeout(300);
    const stand = () => s.page.evaluate(() => ({ count: document.getElementById("count").textContent, hash: decodeURIComponent(location.hash.slice(1)),
      filter: new URLSearchParams(location.search).get("gremium_filter"), kennzeichen: !document.getElementById("gremium-filter").hidden,
      wer: !document.getElementById("panel-gremien").hidden, werStatus: document.getElementById("wer-status").textContent, schritte: document.querySelectorAll("#detail .steps li").length }));
    const vorher = await stand();
    pruefen(profil, "Nachprüfung (10) gremien.json ohne Antwort: Start wartet nicht, Vorgang aus dem Anker, Fläche aus ?wer=, Anker und gremium_filter bleiben",
      vorher.schritte > 0 && vorher.hash === ref && vorher.filter === ohne.key && vorher.wer && !vorher.kennzeichen && !vorher.count.includes("aus dem Link"), vorher);
    await s.page.clock.fastForward(21000);
    await s.page.waitForFunction(() => /aus dem Link konnten nicht geladen werden/.test(document.getElementById("count").textContent), null, { timeout: 10000 }).catch(() => {});
    const nach = await stand();
    pruefen(profil, "Nachprüfung (10)(11) nach 20 s: #count sagt, dass die Angaben fehlen; kein Filter; Parameter und Anker bleiben; Statuszeile „Gremien und Ämter“ mit Ladefehler",
      nach.count.endsWith(SATZ_GREMIEN_FEHLEN) && !nach.kennzeichen && nach.filter === ohne.key && nach.hash === ref && nach.werStatus === LADEFEHLER && nach.schritte > 0, nach);
    await axe(s.page, profil, "Nachprüfung (10) gremien.json ohne Antwort");
    pruefen(profil, "keine Skriptfehler (Nachprüfung: gremien.json ohne Antwort)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
    // (b) späte Antwort: inzwischen einen Vorgang aus der Liste geöffnet (mit der Tastatur)
    s = await neueSeite(browser, profil);
    let gehalten = null;
    await s.page.route((u) => u.pathname.endsWith("/data/export/koeln/gremien.json"), (r) => { gehalten = r; });
    await s.page.goto(`${BASIS}?suche=koeln&gremium_filter=${ohne.key}`, { waitUntil: "load" });
    await s.page.waitForSelector("#papers button[data-gref]", { timeout: 20000 });
    const zuerst = await s.page.$$eval("#papers button[data-gref]", (bs) => bs.length);
    await s.page.focus("#papers button[data-gref]");
    await s.page.keyboard.press("Enter");
    await s.page.waitForSelector("#detail .steps", { state: "attached", timeout: 20000 });
    const aktiv = () => s.page.evaluate(() => { const e = document.activeElement; return e ? `${e.tagName}#${e.id}` : null; });
    const geoeffnet = await s.page.evaluate(() => decodeURIComponent(location.hash.slice(1))), fokusVorher = await aktiv();
    await gehalten.continue();
    await s.page.waitForFunction(() => !document.getElementById("gremium-filter").hidden, null, { timeout: 10000 }).catch(() => {});
    await s.page.waitForTimeout(300);
    // Kennzeichen über textContent: auf schmalen Breiten schließt der Vorgang die Liste (innerText wäre leer)
    const spaet = await s.page.evaluate(() => ({ heading: document.getElementById("detail-heading")?.textContent || "", schritte: document.querySelectorAll("#detail .steps li").length,
      hash: decodeURIComponent(location.hash.slice(1)), kennzeichen: document.getElementById("gremium-filter").hidden ? "" : document.getElementById("gremium-filter").textContent.replace(/\s+/g, " ").replace(/ ?Entfernen.*$/i, "").trim(),
      n: document.querySelectorAll("#papers button[data-gref]").length, filter: new URLSearchParams(location.search).get("gremium_filter") }));
    const fokusNachher = await aktiv();
    pruefen(profil, "Nachprüfung (10) späte Antwort: Filter gesetzt, der inzwischen geöffnete Vorgang bleibt (kein „Los geht's“), Anker bleibt, Fokus unverändert",
      geoeffnet && spaet.hash === geoeffnet && spaet.schritte > 0 && !/Los geht/.test(spaet.heading) && spaet.kennzeichen.startsWith(`Gremium: ${ohne.name}`) && spaet.filter === ohne.key
      && spaet.n <= zuerst && fokusNachher === fokusVorher, { zuerst, spaet, fokusVorher, fokusNachher });
    pruefen(profil, "keine Skriptfehler (Nachprüfung: späte Antwort)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
    // (c) gremien.json mit Fehlercode
    s = await neueSeite(browser, profil, { "gremien.json": async (j, route) => route.fulfill({ status: 503, body: "" }) });
    await s.page.goto(`${BASIS}?gebiet=${gebiet}&gremium_filter=${ohne.key}`, { waitUntil: "load" });
    await geladen(s.page);
    await s.page.waitForTimeout(500);
    let l = await listenStand(s.page), a = await adresse(s.page);
    pruefen(profil, "Nachprüfung (10) gremien.json mit Fehlercode: Satz „konnten nicht geladen werden“ statt „nicht verzeichnet“, Parameter bleibt",
      l.count.endsWith(SATZ_GREMIEN_FEHLEN) && !l.count.includes("nicht verzeichnet") && !l.kennzeichen && a.gremium_filter === ohne.key, { l, a });
    await axe(s.page, profil, "Nachprüfung (10) gremien.json mit Fehlercode");
    await s.ctx.close();
    // (d) Kennung eines aufgelösten Gremiums: Filter über den Namen (Stationen früherer Gremien tragen keine Kennung)
    if (alt) {
      s = await neueSeite(browser, profil, { "suche.json": (j) => {
        const gr = [...(j.gremien || []), alt.name], i = gr.length - 1;
        return { ...j, gremien: gr, rows: j.rows.map((r, k) => (k < 3 ? [...r.slice(0, 10), [...(r[10] || []), i], ...r.slice(11)] : r)) };
      } });
      await s.page.goto(`${BASIS}?suche=koeln&gremium_filter=${alt.key}`, { waitUntil: "load" });
      await s.page.waitForFunction(() => /Treffer in ganz Köln · Gremium/.test(document.getElementById("count").textContent), null, { timeout: 20000 }).catch(() => {});
      await s.page.waitForTimeout(300);
      l = await listenStand(s.page);
      a = await adresse(s.page);
      pruefen(profil, "Nachprüfung (10) Kennung eines aufgelösten Gremiums: Filter über den Namen, 3 Treffer, Adresse mit name:",
        l.count === `3 Treffer in ganz Köln · Gremium (nach Namen): ${alt.name}` && l.kennzeichen === `Gremium (nach Namen): ${alt.name}` && a.gremium_filter === `name:${alt.name}`, { l, a });
      await axe(s.page, profil, "Nachprüfung (10) aufgelöstes Gremium aus der Adresse");
      pruefen(profil, "keine Skriptfehler (Nachprüfung: aufgelöstes Gremium)", s.fehler.length === 0, s.fehler);
      await s.ctx.close();
    } else pruefen(profil, "Nachprüfung (10) Testdaten mit aufgelöstem Gremium", false);
  },
  // Nachprüfung (13): „Erneut versuchen“, danach Fokus und Eingabe im Feld „Stichwort“: die Antwort lässt den Fokus dort
  async suchindexFokus(browser, profil) {
    let aus = true;
    const s = await neueSeite(browser, profil, { "suche.json": async (j, route) => {
      if (aus) return route.fulfill({ status: 503, body: "" });
      await new Promise((r) => setTimeout(r, 1500));
      return route.continue();
    } });
    await s.page.goto(`${BASIS}?suche=koeln&gremium_filter=rat`, { waitUntil: "load" });
    await s.page.waitForSelector("#suche-erneut", { timeout: 30000 });
    aus = false;
    await s.page.focus("#suche-erneut");
    await s.page.keyboard.press("Enter");
    await s.page.waitForTimeout(300);
    await s.page.focus("#f-text");
    await s.page.keyboard.type("ab");
    await s.page.waitForFunction(() => /Treffer in ganz Köln/.test(document.getElementById("count").textContent), null, { timeout: 20000 });
    await s.page.waitForTimeout(400);
    const f = await s.page.evaluate(() => ({ fokus: document.activeElement.id, wert: document.getElementById("f-text").value }));
    pruefen(profil, "Nachprüfung (13) Fokus bleibt im Feld „Stichwort“, wenn der Index nach „Erneut versuchen“ eintrifft", f.fokus === "f-text" && f.wert === "ab", f);
    pruefen(profil, "keine Skriptfehler (Nachprüfung: Suchindex und Fokus)", s.fehler.length === 0, s.fehler);
    await s.ctx.close();
  },
  // (16) Telefon: Reiter, Umschalter, Suchfeld und Filter der Liste 44 px hoch mit 16 px Schrift
  async telefonMasse(browser, profil) {
    if (!telefon(profil)) return;
    const s = await neueSeite(browser, profil);
    await s.page.goto(`${BASIS}?wer=gremien&darstellung=liste`, { waitUntil: "load" });
    await geladen(s.page);
    await flaecheBereit(s.page);
    const mass = (sel) => s.page.$$eval(sel, (es) => es.filter((e) => e.getClientRects().length).map((e) => [e.id || e.textContent.trim(), Math.round(e.getBoundingClientRect().height * 10) / 10, getComputedStyle(e).fontSize]));
    const wer = await mass("#tab-wer-gremien, #tab-wer-aemter, .wer-darstellung [role=radio], #wer-q");
    await s.page.keyboard.press("Escape");
    await liste(s.page, profil);
    await s.page.evaluate(() => { document.getElementById("more-filters").open = true; });
    await s.page.waitForTimeout(200);
    const filter = await mass("#filters input[type=search], #filters select");
    const ok = (xs) => xs.length > 0 && xs.every(([, h, f]) => h >= 44 && f === "16px");
    pruefen(profil, "(16) Telefon: Reiter, Umschalter und Suchfeld der Gremien 44 px hoch, 16 px Schrift", wer.length === 5 && ok(wer), wer);
    pruefen(profil, "(16) Telefon: Stichwort und Auswahlen der Filter 44 px hoch, 16 px Schrift", filter.length >= 6 && ok(filter), filter);
    await axe(s.page, profil, "(16) Filter der Liste auf dem Telefon");
    await s.ctx.close();
  },
};
// (15) geringe Höhe: 320 × 256 CSS-Pixel (400 % Zoom von 1280 × 1024); jede Überlagerung rollt als Ganzes, mit der
// Tastatur, nichts abgeschnitten, kein waagrechtes Rollen; bei 1440 × 900 unverändert
async function geringeHoehe(browser) {
  const profil = "320x256";
  const ctx = await browser.newContext({ viewport: { width: 320, height: 256 }, bypassCSP: true });
  const page = await ctx.newPage();
  const fehler = [];
  page.on("pageerror", (e) => fehler.push(`pageerror: ${e.message}`));
  await page.route((u) => !["127.0.0.1", "localhost"].includes(u.hostname), (r) => r.abort());
  await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => { const h = document.getElementById("testdaten-hinweis"); if (h) h.style.display = "none"; }));
  const messen = (id) => page.evaluate((id) => {
    const o = document.getElementById(id), cs = getComputedStyle(o), innen = o.querySelector(":scope > .panel-body:not([hidden])");
    const kopf = o.querySelector(".panel-head").getBoundingClientRect().top;
    return { overflowY: cs.overflowY, rollt: o.scrollHeight > o.clientHeight + 1, quer: o.scrollWidth <= o.clientWidth + 1,
      innenRollt: innen ? innen.scrollHeight > innen.clientHeight + 1 : null, kopf, oben: o.getBoundingClientRect().top };
  }, id);
  const pruefeFlaeche = async (id, oeffnen, name) => {
    await oeffnen();
    await page.waitForSelector(`#${id}:not([hidden])`, { timeout: 20000 });
    await page.waitForTimeout(600);
    const m = await messen(id);
    // Tastatur: Fokus auf der Überschrift, Bild ab und Pfeil ab rollen die Überlagerung
    await page.focus(`#${id} h2`);
    await page.keyboard.press("PageDown");
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(300);
    const r = await page.evaluate((id) => { const o = document.getElementById(id); return { top: o.scrollTop, kopf: o.querySelector(".panel-head").getBoundingClientRect().top }; }, id);
    // bis ans Ende rollen: das letzte Element steht im sichtbaren Teil
    const ende = await page.evaluate((id) => {
      const o = document.getElementById(id); o.scrollTop = o.scrollHeight;
      const kids = [...o.querySelectorAll(":scope > *")].filter((k) => k.getClientRects().length);
      const letzt = kids[kids.length - 1].getBoundingClientRect(), b = o.getBoundingClientRect();
      return { unten: Math.round(letzt.bottom), rahmen: Math.round(b.bottom) };
    }, id);
    pruefen(profil, `(15) ${name}: die ganze Überlagerung rollt (Kopf rollt mit), Inhalt ohne eigenen Bildlauf, Tastatur rollt, Ende erreichbar, kein waagrechtes Rollen`,
      m.overflowY === "auto" && m.rollt && m.quer && m.innenRollt === false && r.top > 0 && r.kopf < m.kopf && ende.unten <= ende.rahmen + 1, { m, r, ende });
    await axe(page, profil, `(15) ${name} bei 320 × 256`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  };
  await page.goto(BASIS, { waitUntil: "load" });
  await geladen(page);
  const klick = (sel) => () => page.evaluate((sel) => document.querySelector(sel).click(), sel);
  await pruefeFlaeche("panel-gremien", klick('#mega-entscheiden [data-wer="gremien"]'), "Gremien (Liste)");
  await pruefeFlaeche("panel-gremien", klick('#mega-entscheiden [data-wer="aemter"]'), "Ämter");
  await pruefeFlaeche("panel-auswertung", klick('[data-open-tab="stats"]'), "In Zahlen");
  await pruefeFlaeche("panel-termine", klick("#cta-termine"), "Kommende Sitzungen");
  await pruefeFlaeche("panel-mitmachen", klick("#cta-mitmachen"), "Mitmachen in Köln");
  // Fenster „Über“ und „Was ist neu?“: rollen als Ganzes (vorher rollte der Text darin für sich, bei „Über“ zusätzlich
  // das Fenster), auch mit der Tastatur
  for (const [id, oeffner, name] of [["about", "#about-open", "„Über“"], ["neu", "[data-neu]", "„Was ist neu?“"]]) {
    await page.evaluate((sel) => document.querySelector(sel).click(), oeffner);
    await page.waitForSelector(`#${id}[open]`);
    await page.waitForTimeout(300);
    await page.focus(`#${id} .panel-head button`);
    await page.keyboard.press("PageDown");
    await page.waitForTimeout(300);
    // Pfeil rechts darf nicht waagrecht rollen (Nachprüfung: die Begriffsliste in „Über“ war bei 320 px breiter als das Fenster)
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(150);
    const f = await page.evaluate((id) => { const d = document.getElementById(id), a = d.querySelector(".about-body");
      return { overflowY: getComputedStyle(d).overflowY, rollt: d.scrollHeight > d.clientHeight + 1, top: d.scrollTop, innen: a.scrollHeight > a.clientHeight + 1,
        quer: [d.scrollWidth, d.clientWidth, a.scrollWidth, a.clientWidth], links: d.scrollLeft }; }, id);
    pruefen(profil, `(15) Fenster ${name} rollt als Ganzes, der Text darin nicht für sich, auch mit der Tastatur, nicht waagrecht`, f.overflowY === "auto" && f.rollt && f.top > 0 && !f.innen
      && f.quer[0] <= f.quer[1] + 1 && f.quer[2] <= f.quer[3] + 1 && f.links === 0, f);
    await axe(page, profil, `(15) ${name} bei 320 × 256`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  }
  // normale Höhe: unverändert (Überlagerung ohne Bildlauf, Inhalt mit eigenem)
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => document.querySelector('#mega-entscheiden [data-wer="gremien"]').click());
  await flaecheBereit(page);
  await page.waitForTimeout(300);
  const normal = await page.evaluate(() => ({ aussen: getComputedStyle(document.getElementById("panel-gremien")).overflowY, innen: getComputedStyle(document.getElementById("wer-body")).overflowY }));
  pruefen(profil, "(15) bei 1440 × 900 unverändert: Überlagerung overflow hidden, Inhalt rollt für sich", normal.aussen === "hidden" && normal.innen === "auto", normal);
  pruefen(profil, "keine Skriptfehler (geringe Höhe)", fehler.length === 0, fehler);
  await ctx.close();
}
// (9) Quellenzeile: „im Reiter „Ämter““ vor der Federführung, Stand und Prüfung auf der Technikseite
async function quellenzeile(browser, profil) {
  const s = await neueSeite(browser, profil);
  await s.page.goto(BASIS, { waitUntil: "load" });
  await geladen(s.page);
  const t = await s.page.$eval("#sources", (d) => d.textContent.replace(/\s+/g, " "));
  const i = (x) => t.indexOf(x);
  pruefen(profil, "(9) Quellenzeile: Reiter „Ämter“ vor der Federführung, Technikseite danach, alle Angaben", i("Bezeichnungen): im Reiter „Ämter“ unter „Wer entscheidet“ und zur federführenden Dienststelle") > 0
    && i("im Reiter „Ämter“") < i("(Stand und letzte Prüfung auf der Seite „So funktioniert der Ratsatlas“)") && !t.includes("beides auf der Seite"), t.slice(i("Dezernate"), i("Dezernate") + 420));
  await s.ctx.close();
}
async function folge(browser, profil, gremien, gebiet) {
  for (const f of Object.values(FOLGE)) await f(browser, profil, gremien, gebiet);
  if (profil === "1440") await quellenzeile(browser, profil);
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
      await folge(browser, profil, gremien, gebiet);
      if (profil === "1440") await zeitleiste(browser, profil);
    }
    await geringeHoehe(browser);
  } catch (e) {
    pruefen("-", "Ablauf", false, String(e && e.stack || e).slice(0, 800));
  }
  await browser.close();
  if (AUSGABE) fs.writeFileSync(AUSGABE, JSON.stringify({ ergebnisse }, null, 1));
  console.log(`${befunde} Befunde`);
  process.exit(befunde ? 1 : 0);
})();
