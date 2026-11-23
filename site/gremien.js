// Fläche „Gremien und Ämter“ unter „Wer entscheidet“ (Entscheidungen 21.11.2026 (2) (F4–F9, F11, F12) und 23.11.2026
// (1) (E2–E4, E6–E10)): Reiter „Gremien“ aus gremien.json (pipeline/gremien.py) als Schaubild oder Liste, Reiter „Ämter“
// aus aemter.json (pipeline/aemter.py) als Liste. Eigenes Kölner Modul; vom Ratsatlas Bonn übernommen ist nur das
// Bedienmuster (Reiter, Umschalter „Schaubild | Liste“, Knoten mit Kurzzeile, Liste mit Suche). Die Bonner Fläche
// „Prozesse“ (site/prozesse.js) bleibt unter „soll“ abgeschaltet und wird nicht eingebunden. Keine Besetzung, keine
// Namen von Personen, keine Zahlen zu den Ämtern. Alle Kennungen, Namen und Zahlen stammen aus den beiden Dateien; der
// Detailbereich hat keine Live-Region (der Fokus genügt), Zähler und Meldungen stehen in einer festen Statuszeile
// (#wer-status). Wird von app.js erst beim ersten Öffnen geladen; ohne Freigabe „gremien“ fehlt die Fläche im
// veröffentlichten HTML.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Adressen aus den Daten nur als http(s)-Link (javascript: o. Ä. würde sonst als Link eingesetzt)
const href = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? esc(u) : "");
const neuerTab = (u, text, wo = "neuer Tab") => (href(u)
  ? `<a href="${href(u)}" target="_blank" rel="noopener">${text}<span class="visually-hidden"> (${esc(wo)})</span></a>` : "");

// Kalendertage (JJJJ-MM-TT) wie app.js (fmtDate, fmtDay): 12 Uhr UTC des Tages in Europe/Berlin
const ISO_TAG = /^\d{4}-\d{2}-\d{2}$/;
const DATUM = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", year: "numeric" });
const WOCHENTAG = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
const mittag = (tag) => new Date(tag + "T12:00:00Z");
const istTag = (tag) => ISO_TAG.test(String(tag ?? "")) && !Number.isNaN(mittag(tag).getTime());
export const datum = (tag) => (istTag(tag) ? DATUM.format(mittag(tag)) : "");
// Der Zeitraum „in 12 Monaten“ beginnt am Tag nach meta.zeitraum.seit (seit zählt nicht mit, bis zählt mit; F7)
export const tagDanach = (tag) => new Date(mittag(tag).getTime() + 864e5).toISOString().slice(0, 10);
export function zeitraum(meta) {
  const z = meta && meta.zeitraum;
  return z && istTag(z.seit) && istTag(z.bis) ? { von: tagDanach(z.seit), bis: z.bis } : null;
}
const anzahl = (n, eins, mehr) => `${Number(n) || 0} ${Number(n) === 1 ? eins : mehr}`;
// Suche ohne Unterschied von Groß- und Kleinschreibung, Akzenten und ß
export const suchform = (s) => String(s ?? "").toLocaleLowerCase("de").replace(/ß/g, "ss").normalize("NFD").replace(/[̀-ͯ]/g, "");

export const REITER = ["gremien", "aemter"];
export const DARSTELLUNGEN = ["schaubild", "liste"];
const GRUPPEN = ["rat", "ausschuss", "bezirksvertretung", "uebrige"];
// Name der Gruppe als Überschrift: erster Buchstabe groß (meta.gruppen schreibt „übrige Gremien“ klein, für Fließtext)
const gruppenName = (meta, k) => {
  const n = String((meta && meta.gruppen && meta.gruppen[k]) || k);
  return n.charAt(0).toLocaleUpperCase("de") + n.slice(1);
};

// Nächste Sitzung aus Sicht der Besucher:innen: die erste von naechste_sitzung und folgende_sitzung, deren Kölner Tag
// nicht vor `heute` liegt. Die Pipeline führt die folgende Sitzung nur, wenn die nächste am Tag des Datenstands liegt
// (E2); ist diese vorbei, zeigt die Seite die folgende. Bei nicht aktueller Liste der Sitzungen fehlen beide.
export function kommendeSitzung(g, heute) {
  return [g.naechste_sitzung, g.folgende_sitzung].find((m) => m && istTag(m.date) && m.date >= heute) || null;
}

// Kurzzeile eines Gremiums (E7): Paragraf bzw. Stadtbezirk, nächste Sitzung; frühere Gremien mit „aufgelöst“
export function kurzzeile(g, meta, heute) {
  const teile = [];
  if (g.gruppe === "ausschuss" && g.paragraf != null) teile.push(`§ ${g.paragraf}`);
  if (g.gruppe === "bezirksvertretung" && g.stadtbezirk) teile.push(`Stadtbezirk ${g.stadtbezirk}`);
  if (g.aufgeloest) teile.push("aufgelöst");
  const m = !(meta && meta.sitzungsliste_nicht_aktuell) && kommendeSitzung(g, heute);
  if (m) teile.push(`nächste Sitzung ${datum(m.date)}${m.hinweis === "verschoben" ? ", laut Sitzungsnamen verschoben" : ""}`);
  return teile.join(" · ");
}

// Hinweis bei nicht aktueller Liste der Sitzungen (gremien.json meta.sitzungsliste_nicht_aktuell): Stand der Liste als
// Kölner Tag (zeitDatum aus app.js, dieselbe Regel wie der Datenstand), ohne Stand derselbe Wortlaut wie dort
// (Schluss „; deshalb fehlt die nächste Sitzung“ seit der Entscheidung 23.11.2026 (2) (5))
export function sitzungslisteText(meta, zeitDatum) {
  const n = meta && meta.sitzungsliste_nicht_aktuell;
  if (!n) return "";
  return `Die Liste der Sitzungen wurde beim letzten Abruf nicht aktualisiert; gezeigt wird ${n.stand ? `der Stand vom ${zeitDatum(n.stand)}` : "der letzte gültige Stand"}; deshalb fehlt die nächste Sitzung.`;
}
// Aktuelle Liste, aber jede bekannte Sitzung (naechste_sitzung, folgende_sitzung) liegt vor dem Kölner Tag `heute`
// (Entscheidung 23.11.2026 (2) (3)): Die Seite sagt das, statt die Zeile wegzulassen
export const VORBEI = "Die bekannten Sitzungen sind vorbei; der nächste Abruf ergänzt die Liste der Sitzungen.";
export function sitzungenVorbei(g, heute) {
  const bekannt = [g.naechste_sitzung, g.folgende_sitzung].filter((m) => m && istTag(m.date));
  return bekannt.length > 0 && bekannt.every((m) => m.date < heute);
}

// Inhalt zu einem Gremium (Detailbereich im Schaubild, aufgeklappter Eintrag der Liste)
export function gremiumInhalt(g, meta, umgebung) {
  const { heute, zeitDatum } = umgebung;
  const zr = zeitraum(meta), zusto = (meta && meta.zustaendigkeitsordnung) || {};
  const zeilen = [];
  if (g.gruppe === "ausschuss" && g.paragraf != null) {
    const text = `Zuständigkeitsordnung, § ${esc(g.paragraf)} (PDF, neuer Tab)`;
    zeilen.push(`<li>${href(zusto.url) ? `<a href="${href(zusto.url)}" target="_blank" rel="noopener">${text}</a>` : esc(`Zuständigkeitsordnung, § ${g.paragraf}`)} <span class="derived">abgeleitet, über den Namen des Ausschusses</span></li>`);
  }
  if (g.gruppe === "bezirksvertretung" && g.stadtbezirk) zeilen.push(`<li>Stadtbezirk ${esc(g.stadtbezirk)} <span class="derived">abgeleitet, über den Namen der Bezirksvertretung</span></li>`);
  if (g.aufgeloest) zeilen.push(`<li>Aufgelöst${g.end_date ? `: Enddatum ${istTag(g.end_date) ? datum(g.end_date) : esc(g.end_date)} laut Ratsinformationssystem` : ""}</li>`);
  zeilen.push(`<li>${zr ? `In den 12 Monaten vom ${datum(zr.von)} bis ${datum(zr.bis)}` : "In 12 Monaten"}: ${anzahl(g.sitzungen_12m, "Sitzung", "Sitzungen")}, ${anzahl(g.vorlagen_12m, "Vorlage", "Vorlagen")} beraten <span class="hint">(abgesagte Sitzungen zählen nicht)</span>${g.aufgeloest
    ? "<br><span class=\"hint\">Gezählt sind die Vorlagen über die Beratungen dieses früheren Gremiums im Ratsinformationssystem; einen Filter „Vorlagen dieses Gremiums“ gibt es für frühere Gremien nicht.</span>" : ""}</li>`);
  const liste = sitzungslisteText(meta, zeitDatum);
  const m = !liste && kommendeSitzung(g, heute);
  if (liste) zeilen.push(`<li>${esc(liste)}</li>`);
  // ohne Link zur Tagesordnung derselbe Wortlaut wie in „Aktuell in Köln“ und „Kommende Sitzungen“ (23.11.2026 (2) (4))
  else if (m) zeilen.push(`<li>Nächste Sitzung: ${WOCHENTAG.format(mittag(m.date))}${m.time ? `, ${esc(m.time)} Uhr` : ""}${m.hinweis === "verschoben" ? ' <span class="badge">laut Sitzungsnamen verschoben</span>' : ""}${href(m.web) ? ` · ${neuerTab(m.web, "Tagesordnung", "Ratsinformationssystem, neuer Tab")}` : " · Tagesordnung noch nicht veröffentlicht"}</li>`);
  else if (sitzungenVorbei(g, heute)) zeilen.push(`<li>${VORBEI}</li>`);
  // Der Knopf zeigt die Vorlagen aller Jahre, die Zahl darüber gilt für 12 Monate: ein Satz daneben, mit dem Knopf über
  // aria-describedby verbunden (23.11.2026 (2) (2)); die Kennung macht die id eindeutig, auch in der Liste
  const knopf = !g.aufgeloest && g.key
    ? `<p class="pz-actions"><button type="button" class="btn btn-soft wer-filter" data-kennung="${esc(g.key)}" data-name="${esc(g.name)}" aria-describedby="wer-jahre-${esc(g.key)}">Vorlagen dieses Gremiums<span class="visually-hidden">: ${esc(g.name)}</span></button>
      <span class="hint wer-jahre" id="wer-jahre-${esc(g.key)}">Die Liste zeigt die Vorlagen aller Jahre; die Zahl oben zählt nur die 12 Monate.</span></p>` : "";
  const quelle = href(g.source_object) ? `<p class="hint wer-quelle">Quellobjekt: ${neuerTab(g.source_object, esc(g.source_object))}</p>` : "";
  return `<ul class="pz-facts">${zeilen.join("")}</ul>${knopf}${quelle}`;
}

const knoten = (g, meta, z, heute) => {
  const kurz = kurzzeile(g, meta, heute);
  return `<button type="button" class="org-node${g.gruppe === "rat" ? " org-rat" : ""}" data-kennung="${esc(g.key)}" aria-pressed="${z.kennung === g.key}">
    <span class="org-name">${esc(g.name)}</span>${kurz ? `<span class="org-meta">${esc(kurz)}</span>` : ""}</button>`;
};
export function detailHtml(d, z, umgebung) {
  const g = d.gremien.find((x) => x.key === z.kennung);
  // ein früheres Gremium steht nicht im Schaubild (F5): statt seiner Angaben ein Hinweis auf die Liste
  if (g && g.aufgeloest) return `<p class="hint">Das gewählte Gremium „${esc(g.name)}“ ist aufgelöst; es steht in der Liste unter „frühere Gremien zeigen“.</p>`;
  return g ? `<h3 class="pz-h" tabindex="-1">${esc(g.name)}</h3>${gremiumInhalt(g, d.meta, umgebung)}`
    : '<p class="hint">Wählen Sie im Schaubild ein Gremium; hier erscheinen dann seine Zahlen, die nächste Sitzung und die Quelle.</p>';
}

// Schaubild (E7, E8): Rat oben, darunter Ausschüsse und Bezirksvertretungen nebeneinander, übrige Gremien in einem
// eigenen Abschnitt, alle sichtbar; nur Gremien, die nicht aufgelöst sind (F5). Gruppen ohne Gremium entfallen. Die
// Abschnitte tragen keinen Namen (kein aria-labelledby), sind also keine Landmarken; die Überschriften h3 gliedern
// (23.11.2026 (2) (17)).
function schaubild(d, z, umgebung) {
  const aktiv = d.gremien.filter((g) => !g.aufgeloest), meta = d.meta;
  const von = (k) => aktiv.filter((g) => g.gruppe === k);
  const abschnitt = (k, klasse, raster = "") => (von(k).length ? `<section class="${klasse}">
      <h3 class="org-h" id="wer-h-${k}">${esc(gruppenName(meta, k))}</h3>
      <div class="org-grid${raster}">${von(k).map((g) => knoten(g, meta, z, umgebung.heute)).join("")}</div></section>` : "");
  const spalten = [abschnitt("ausschuss", "org-col"), abschnitt("bezirksvertretung", "org-col", " org-grid-1")].filter(Boolean);
  return `<div class="org wer-org">
      ${von("rat").length ? `<section class="org-top"><h3 class="visually-hidden" id="wer-h-rat">${esc(gruppenName(meta, "rat"))}</h3>${von("rat").map((g) => knoten(g, meta, z, umgebung.heute)).join("")}</section>` : ""}
      ${spalten.length ? `<div class="org-cols${spalten.length === 1 ? " wer-eine-spalte" : ""}">${spalten.join("")}</div>` : ""}
      ${abschnitt("uebrige", "org-beirat")}
    </div>
    <div class="pz-detail" id="wer-detail">${detailHtml(d, z, umgebung)}</div>`;
}

// Liste (F5): nach Gruppen, mit Suche; aufgelöste Gremien nur mit „frühere Gremien zeigen“
const passt = (g, q) => !q || suchform(g.name).includes(q);
export function listeGezeigt(d, z) {
  const q = suchform(z.q.trim());
  return d.gremien.filter((g) => (z.frueher || !g.aufgeloest) && passt(g, q));
}
// Frühere Gremien, die zur Suche passen, aber ohne „frühere Gremien zeigen“ ausgeblendet sind
export function fruehereAusgeblendet(d, z) {
  const q = suchform(z.q.trim());
  return z.frueher ? 0 : d.gremien.filter((g) => g.aufgeloest && passt(g, q)).length;
}
export function listenteil(d, z, umgebung) {
  const gezeigt = listeGezeigt(d, z);
  if (!gezeigt.length) {
    const k = fruehereAusgeblendet(d, z);
    return k ? `<p>Unter den aktuellen Gremien passt keines zur Suche „${esc(z.q.trim())}“; ${k === 1 ? "1 früheres Gremium passt"
      : `${k} frühere Gremien passen`}. Mit „frühere Gremien zeigen“ ${k === 1 ? "erscheint es" : "erscheinen sie"} in der Liste.</p>`
      : `<p>Kein Gremium passt zur Suche „${esc(z.q.trim())}“.</p>`;
  }
  return GRUPPEN.map((k) => [k, gezeigt.filter((g) => g.gruppe === k)]).filter(([, gs]) => gs.length).map(([k, gs]) =>
    `<h3 class="pz-h">${esc(gruppenName(d.meta, k))}</h3>${gs.map((g) => {
      const kurz = kurzzeile(g, d.meta, umgebung.heute);
      return `<details class="pz-item" data-kennung="${esc(g.key)}"${z.kennung === g.key ? " open" : ""}><summary><span class="pz-title">${esc(g.name)}</span>${kurz ? `<span class="pz-meta">${esc(kurz)}</span>` : ""}</summary>
        ${gremiumInhalt(g, d.meta, umgebung)}</details>`;
    }).join("")}`).join("");
}
function liste(d, z, umgebung) {
  const frueher = d.gremien.some((g) => g.aufgeloest);
  return `<div class="pz-filterbar">
      <label>Gremium suchen <input type="search" id="wer-q" value="${esc(z.q)}" autocomplete="off"></label>
      ${frueher ? `<label class="check"><input type="checkbox" id="wer-frueher"${z.frueher ? " checked" : ""}> frühere Gremien zeigen</label>` : ""}
    </div>
    <div id="wer-liste">${listenteil(d, z, umgebung)}</div>`;
}

// Reiter „Gremien“: Einleitung, Schaubild oder Liste, Quellen
export function inhaltGremien(d, z, darstellung, umgebung) {
  const meta = d.meta, zr = zeitraum(meta), zusto = meta.zustaendigkeitsordnung || {};
  const quelle = (Array.isArray(meta.sources) ? meta.sources : []).find((s) => s && s.name === "oparl-koeln");
  const liste_ = sitzungslisteText(meta, umgebung.zeitDatum);
  const einleitung = `<p class="hint">Gremien laut Ratsinformationssystem der Stadt Köln.${zr ? ` Sitzungen und beratene Vorlagen zählen für die 12 Monate vom ${datum(zr.von)} bis ${datum(zr.bis)}; abgesagte Sitzungen zählen nicht.` : ""}${darstellung === "schaubild" && d.gremien.some((g) => g.aufgeloest) ? " Das Schaubild zeigt die Gremien, die nicht aufgelöst sind; frühere Gremien stehen in der Liste." : ""} „Vorlagen dieses Gremiums“ zeigt die Vorlagen in der Liste: im gewählten Gebiet, ohne gewähltes Gebiet in ganz Köln.</p>
    ${liste_ ? `<p class="stand-hinweis"><strong>Hinweis zum Datenstand:</strong> ${esc(liste_)}</p>` : ""}`;
  const quellen = `<p class="hint wer-quellen">Quelle: Ratsinformationssystem der Stadt Köln (OParl-API${quelle && quelle.license ? `; ${esc(umgebung.lizenz(quelle.license))}` : ""}).${zusto.titel ? ` Paragrafen der Ausschüsse: ${esc(zusto.titel)}${zusto.hinweis ? `. ${esc(zusto.hinweis)}` : ""}` : ""}${meta.namensnennung && !(quelle && String(quelle.license).includes(meta.namensnennung)) ? ` ${esc(meta.namensnennung)}.` : ""}</p>`;
  return einleitung + (darstellung === "liste" ? liste(d, z, umgebung) : schaubild(d, z, umgebung)) + quellen;
}

// Reiter „Ämter“ (E9, F8): ein Abschnitt je Dezernat mit Einheiten und Ebene, eigene Gruppe „ohne Zuordnung“; Quelle,
// Stand, letzte Prüfung und Lizenzhinweis immer sichtbar; keine Zahlen. Die Abschnitte sind wie im Schaubild keine
// Landmarken, die Überschriften gliedern (23.11.2026 (2) (17))
const EBENE = { dezernatseinheit: "Einheit des Dezernats", dienststelle: "Dienststelle", punktdienststelle: "Punktdienststelle (im Plan „•“)" };
export function inhaltAemter(a) {
  const q = (a.meta && a.meta.quelle) || {};
  const titel = esc(q.titel || "Geschäfts- und Dezernatsverteilungsplan der Stadt Köln");
  const verweis = href(q.url) ? `<a href="${href(q.url)}" target="_blank" rel="noopener">${titel}<span class="visually-hidden"> (${/\.pdf$/i.test(String(q.url)) ? "PDF, " : ""}neuer Tab)</span></a>` : titel;
  const stand = [istTag(q.stand) ? `Stand ${datum(q.stand)}` : "", istTag(q.geprueft) ? `zuletzt geprüft am ${datum(q.geprueft)}` : ""].filter(Boolean).join(", ");
  const kopf = `<p class="hint">Aufbau der Stadtverwaltung: Dezernate mit ihren Einheiten, Dienststellen und Punktdienststellen, ohne die Untereinheiten der Dienststellen.</p>
    <p class="pz-note wer-aemter-quelle">Quelle: ${verweis}${stand ? `, ${stand}` : ""}.${a.meta && a.meta.lizenz ? ` Lizenz: ${esc(a.meta.lizenz)}.` : ""}</p>`;
  const meta = (e) => [EBENE[e.ebene], e.eigenbetriebsaehnlich ? "eigenbetriebsähnlich" : "", e.fundstelle ? `Fundstelle: ${e.fundstelle}` : ""].filter(Boolean).map(esc).join(" · ");
  const eintrag = (e) => `<li><span class="wer-einheit">${esc(e.label || e.name)}</span>${meta(e) ? `<span class="pz-meta">${meta(e)}</span>` : ""}</li>`;
  const dezernate = (Array.isArray(a.dezernate) ? a.dezernate : []).map((d, i) => `<section class="wer-dezernat">
      <h3 class="pz-h" id="wer-dez-${i}">${esc(d.label || d.name || d.dezernat)}</h3>
      ${(d.einheiten || []).length ? `<ul class="wer-einheiten">${d.einheiten.map(eintrag).join("")}</ul>` : ""}</section>`).join("");
  const ohne = Array.isArray(a.ohne_zuordnung) ? a.ohne_zuordnung : [];
  const ohneHtml = ohne.length ? `<section class="wer-dezernat">
      <h3 class="pz-h" id="wer-dez-ohne">Ohne Zuordnung (im Plan „●“)</h3>
      <p class="hint">Diese Einträge sind im Plan mit „●“ gekennzeichnet; der Plan erklärt das Zeichen nicht. Der Ratsatlas ordnet sie deshalb keinem Dezernat zu, auch wenn die Fundstelle die Spalte eines Dezernats nennt.</p>
      <ul class="wer-einheiten">${ohne.map((e) => `<li><span class="wer-einheit">${esc(e.label || e.name)}</span>${e.fundstelle ? `<span class="pz-meta">Fundstelle: ${esc(e.fundstelle)}</span>` : ""}</li>`).join("")}</ul></section>` : "";
  return kopf + dezernate + ohneHtml;
}

// --- Steuerung ------------------------------------------------------------------------------------------------------
let ctx = null, daten = null, root = null, body = null, status = null, zaehler = 0, bedient = false, gezeigt = null;
const zustand = { tab: "gremien", darstellung: null, kennung: null, frueher: false, q: "" };
// Kennungen der aufgeklappten Einträge der Liste in der Reihenfolge des Öffnens (23.11.2026 (2) (14)): `kennung` folgt
// dem zuletzt geöffneten Eintrag, der noch offen ist; wird er zugeklappt, dem davor geöffneten; ohne offenen Eintrag keine
let geoeffnet = [];
// Wahl in Reiter oder Umschalter, während die Daten noch laden: Sie gilt nach dem Laden vor dem Reiter bzw. der
// Darstellung, mit denen die Fläche geöffnet wurde
const beimLaden = { tab: false, darstellung: false };
// ohne ausdrückliche Wahl (Umschalter oder Adresse) Schaubild ab 901 px, Liste bis 900 px (F9)
const darstellung = () => zustand.darstellung || (ctx.telefon() ? "liste" : "schaubild");
const umgebung = () => ({ heute: ctx.heute(), zeitDatum: ctx.zeitDatum, lizenz: ctx.lizenz });
// eine neue Meldung hebt den verzögerten Zähler der Liste auf (sonst schriebe er nach einem Wechsel von Reiter oder
// Darstellung noch eine Zahl der Liste in die Statuszeile)
const melden = (text) => { clearTimeout(zaehler); status.textContent = text; };
// Statuszeile der Liste; ohne Eintrag nennt sie passende frühere Gremien, die ausgeblendet sind
export function listenStatus(d, z) {
  const n = listeGezeigt(d, z).length, k = n ? 0 : fruehereAusgeblendet(d, z);
  return `${n === 1 ? "1 Gremium" : `${n} Gremien`}${k ? `; ${k === 1 ? "1 früheres Gremium passt" : `${k} frühere Gremien passen`}` : ""}`;
}
const listeZaehlen = () => melden(listenStatus(daten.gremien, zustand));
const listeZaehlenSpaeter = () => { clearTimeout(zaehler); zaehler = setTimeout(listeZaehlen, 400); };

// Reiter, Umschalter und Inhalt zeigen; während des Ladens nur Reiter und Umschalter (die Statuszeile behält den
// Ladehinweis von app.js)
function render() {
  const tab = zustand.tab, ansicht = darstellung();
  root.querySelectorAll("[role=tab][data-wer-tab]").forEach((t) => {
    const an = t.dataset.werTab === tab;
    t.setAttribute("aria-selected", String(an));
    t.tabIndex = an ? 0 : -1;
  });
  const schalter = root.querySelector(".wer-darstellung");
  schalter.hidden = tab !== "gremien";
  schalter.querySelectorAll("[data-darstellung]").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.darstellung === ansicht));
    b.tabIndex = b.dataset.darstellung === ansicht ? 0 : -1;
  });
  body.setAttribute("aria-labelledby", `tab-wer-${tab}`);
  if (daten) {
    body.innerHTML = tab === "aemter" ? inhaltAemter(daten.aemter) : inhaltGremien(daten.gremien, zustand, ansicht, umgebung());
    gezeigt = tab === "gremien" ? ansicht : null;
    geoeffnet = gezeigt === "liste" && zustand.kennung ? [zustand.kennung] : [];
    if (tab === "gremien" && ansicht === "liste") listeZaehlen(); else melden("");
  }
  ctx.onState(werZustand());
}
export const werZustand = () => ({ tab: zustand.tab, darstellung: zustand.darstellung, kennung: zustand.tab === "gremien" ? zustand.kennung : null });

// Eintrag eines Gremiums ansteuern: im Schaubild der Detailbereich, in der Liste der aufgeklappte Eintrag
function fokusAufEintrag() {
  if (darstellung() === "liste") {
    const d = body.querySelector(`details[data-kennung="${CSS.escape(zustand.kennung || "")}"]`);
    if (d) { d.open = true; d.scrollIntoView({ block: "nearest" }); d.querySelector("summary").focus(); }
    return;
  }
  body.querySelector("#wer-detail h3")?.focus();
}
// Eintrag ins Bild rollen, ohne den Fokus zu bewegen (Zustand aus der Adresse beim Laden der Seite)
function eintragZeigen() {
  const el = darstellung() === "liste" ? body.querySelector(`details[data-kennung="${CSS.escape(zustand.kennung || "")}"]`) : body.querySelector("#wer-detail");
  if (el) el.scrollIntoView({ block: "nearest" });
}
function waehlen(kennung) {
  zustand.kennung = kennung;
  body.querySelectorAll(".org-node[data-kennung]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kennung === kennung)));
  const detail = body.querySelector("#wer-detail");
  if (detail) detail.innerHTML = detailHtml(daten.gremien, zustand, umgebung());
  ctx.onState(werZustand());
  fokusAufEintrag();
}

// Ereignisse der Fläche, einmal angemeldet und schon während des Ladens wirksam
function bedienen() {
  // Reiter: Klick, ← und →, Pos1 und Ende; die Reihenfolge aus den sichtbaren Reitern, der Fokus wandert mit
  const tabliste = root.querySelector("[role=tablist]");
  const reiter = (tab) => { zustand.tab = tab; zustand.q = ""; if (!daten) beimLaden.tab = true; render(); };
  tabliste.addEventListener("click", (e) => {
    const t = e.target.closest("[role=tab][data-wer-tab]");
    if (t && t.dataset.werTab !== zustand.tab) reiter(t.dataset.werTab);
  });
  tabliste.addEventListener("keydown", (e) => {
    const tabs = [...tabliste.querySelectorAll("[role=tab][data-wer-tab]")].filter((t) => !t.hidden);
    const i = tabs.findIndex((t) => t.dataset.werTab === zustand.tab);
    const ziel = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
    if (ziel === undefined) return;
    e.preventDefault();
    reiter(tabs[ziel].dataset.werTab);
    tabs[ziel].focus();
  });
  // Umschalter „Schaubild | Liste“ (radiogroup): Klick, Pfeiltasten, Pos1 und Ende; die Wahl gilt ausdrücklich
  const schalter = root.querySelector(".wer-darstellung");
  const setzen = (wert, fokus) => {
    zustand.darstellung = wert;
    if (!daten) beimLaden.darstellung = true;
    render();
    if (fokus) schalter.querySelector(`[data-darstellung="${wert}"]`).focus();
  };
  schalter.addEventListener("click", (e) => { const b = e.target.closest("[data-darstellung]"); if (b) setzen(b.dataset.darstellung); });
  schalter.addEventListener("keydown", (e) => {
    const i = DARSTELLUNGEN.indexOf(darstellung()), n = DARSTELLUNGEN.length;
    const ziel = { ArrowRight: (i + 1) % n, ArrowDown: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (ziel === undefined) return;
    e.preventDefault();
    setzen(DARSTELLUNGEN[ziel], true);
  });
  body.addEventListener("click", (e) => {
    const k = e.target.closest(".org-node[data-kennung]");
    if (k) { waehlen(k.dataset.kennung); return; }
    const f = e.target.closest(".wer-filter");
    if (f) ctx.filterGremium(f.dataset.kennung, f.dataset.name);
  });
  // Liste: Suche und „frühere Gremien zeigen“ bauen nur die Einträge neu auf (Suchfeld und Häkchen behalten den Fokus)
  body.addEventListener("input", (e) => {
    if (e.target.id !== "wer-q") return;
    zustand.q = e.target.value;
    body.querySelector("#wer-liste").innerHTML = listenteil(daten.gremien, zustand, umgebung());
    listeZaehlenSpaeter();
  });
  body.addEventListener("change", (e) => {
    if (e.target.id !== "wer-frueher") return;
    zustand.frueher = e.target.checked;
    body.querySelector("#wer-liste").innerHTML = listenteil(daten.gremien, zustand, umgebung());
    listeZaehlen();
  });
  body.addEventListener("toggle", (e) => {
    const d = e.target;
    if (!d.matches || !d.matches("details.pz-item[data-kennung]")) return;
    const k = d.dataset.kennung;
    // nur Einträge, die noch offen in der Liste stehen (ein Neuaufbau der Liste lässt nur das gewählte Gremium offen)
    geoeffnet = geoeffnet.filter((x) => x !== k && body.querySelector(`details.pz-item[data-kennung="${CSS.escape(x)}"]`)?.open);
    if (d.open) geoeffnet.push(k);
    zustand.kennung = geoeffnet.length ? geoeffnet[geoeffnet.length - 1] : null;
    ctx.onState(werZustand());
  }, true);
  // Esc im Suchfeld der Liste (23.11.2026 (2) (12)): Ein gefülltes Feld leert das erste Esc (Liste und Statuszeile
  // folgen sofort), die Fläche bleibt offen; ist das Feld leer, schließt Esc die Fläche wie überall (app.js)
  body.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.target.id !== "wer-q" || !e.target.value) return;
    e.preventDefault();
    e.stopPropagation();
    e.target.value = "";
    zustand.q = "";
    body.querySelector("#wer-liste").innerHTML = listenteil(daten.gremien, zustand, umgebung());
    listeZaehlen();
  });
}

// Wartezeit je Datei (23.11.2026 (2) (11)): Antwortet sie nicht in dieser Zeit, bricht der Abruf ab (AbortController),
// init scheitert, und app.js zeigt den Satz zum Ladefehler; eine spätere Antwort kommt nicht mehr an
export const WARTEZEIT = 20000;
export async function init(c) {
  ctx = c;
  root = document.getElementById("panel-gremien");
  body = root.querySelector("#wer-body");
  status = root.querySelector("#wer-status");
  if (!bedient) { bedienen(); bedient = true; }
  beimLaden.tab = beimLaden.darstellung = false;
  const laden = (name) => {
    const ab = new AbortController(), uhr = setTimeout(() => ab.abort(), ctx.wartezeit ?? WARTEZEIT);
    return fetch(ctx.basis + name, { signal: ab.signal }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .finally(() => clearTimeout(uhr));
  };
  const [gremien, aemter] = await Promise.all([laden("gremien.json"), laden("aemter.json")]);
  if (!gremien || !Array.isArray(gremien.gremien) || !gremien.meta || !aemter || !Array.isArray(aemter.dezernate)) throw new Error("Daten unvollständig");
  daten = { gremien, aemter };
}

// Zustand übernehmen und zeigen: tab, darstellung (ausdrückliche Wahl), kennung, fokus (Eintrag ansteuern, etwa aus dem
// Vorgang), zeigen (Eintrag nur ins Bild rollen, etwa aus der Adresse). Eine unbekannte Kennung (etwa aus einem älteren
// Link; F12: die Kennung kann sich ändern) wählt nichts aus. Eine Wahl während des Ladens geht dem ersten tab bzw. der
// ersten darstellung danach vor (app.js ruft show bei jedem Öffnen zweimal auf: aus setPanel ohne Angaben, danach mit
// dem Reiter).
export function show(s = {}) {
  if (REITER.includes(s.tab)) { if (!beimLaden.tab) zustand.tab = s.tab; beimLaden.tab = false; }
  if (DARSTELLUNGEN.includes(s.darstellung)) { if (!beimLaden.darstellung) zustand.darstellung = s.darstellung; beimLaden.darstellung = false; }
  let unbekannt = false;
  if (s.kennung !== undefined) {
    const g = s.kennung ? daten.gremien.gremien.find((x) => x.key === s.kennung) : null;
    unbekannt = Boolean(s.kennung) && !g;
    zustand.kennung = g ? g.key : null;
    // ein gewähltes Gremium steht in der Liste auch bei einem früheren Suchtext und als aufgelöstes Gremium da; ein
    // aufgelöstes steht nur in der Liste (F5), daher gilt ohne gewählte Darstellung die Liste als gewählt
    if (g) {
      zustand.q = "";
      if (g.aufgeloest) { zustand.frueher = true; zustand.darstellung ||= "liste"; }
    }
  }
  render();
  if (unbekannt) melden("Das Gremium aus dem Link ist unter „Gremien“ nicht verzeichnet; seine Kennung kann sich geändert haben.");
  if (zustand.tab === "gremien" && zustand.kennung) {
    if (s.fokus) fokusAufEintrag();
    else if (s.zeigen) eintragZeigen();
  }
}
// Breite geändert (app.js applyLayout): ohne ausdrückliche Wahl gilt die Darstellung der neuen Breite. Neu aufgebaut
// wird nur, wenn sich die Darstellung dabei ändert. Lag der Fokus im Inhalt oder am Umschalter, steht er danach auf
// demselben Gremium (Knoten im Schaubild, Eintrag der Liste; aus dem Detailbereich bzw. einem aufgeklappten Eintrag auf
// dessen Gegenstück), sonst in der Liste im Suchfeld und im Schaubild auf dem gewählten Optionsfeld des Umschalters.
export function breite() {
  if (!daten || zustand.darstellung || zustand.tab !== "gremien" || darstellung() === gezeigt) return;
  const a = document.activeElement;
  const drin = Boolean(a && body.contains(a)), amSchalter = Boolean(a && root.querySelector(".wer-darstellung").contains(a));
  const imDetail = drin && Boolean(a.closest("#wer-detail"));
  const kennung = imDetail ? zustand.kennung : drin ? a.closest("[data-kennung]")?.dataset.kennung || null : null;
  const imEintrag = imDetail || (drin && Boolean(a.closest("details")) && !a.closest("summary"));
  render();
  if (!drin && !amSchalter) return;
  const k = kennung && CSS.escape(kennung);
  let ziel = null;
  if (darstellung() === "liste") ziel = (k && body.querySelector(`details[data-kennung="${k}"] > summary`)) || (drin ? body.querySelector("#wer-q") : null);
  else if (k) ziel = imEintrag && kennung === zustand.kennung ? body.querySelector("#wer-detail h3") : body.querySelector(`.org-node[data-kennung="${k}"]`);
  (ziel || root.querySelector('.wer-darstellung [aria-checked="true"]')).focus();
}
