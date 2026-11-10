// Strukturdaten der Kölner Stadtstatistik (Datenvertrag „Strukturdaten“ 1.1; Auslieferung pipeline/strukturdaten_web.py
// unter data/strukturdaten/): Kontext-Panel je Gebiet (Liste) und kompakt im Vorgang, Flächenfarben auf der Karte mit
// gleichwertiger Tabelle. Nur mit Freigabe „strukturdaten“ (config.ZUSATZTHEMEN, Entscheidung des Auftraggebers vom
// 10.11.2026): app.js lädt dieses Modul erst dann, ohne Freigabe fehlt der Ordner auf der Seite (tools/seite_bauen.py).
//
// Quellentreu: Das Modul liest nur den Datenvertrag. Jede angezeigte Zahl ist eine Zeile aus raumwerte/ oder karte/
// (Spalten wie werte.tsv: raumebene, raum_id, indikator_id, jahr, wert, status, quellobjekt) und nennt Jahr, Quelle und
// Lizenz; der genaue Wert und das Quellobjekt stehen je Wert in der aufklappbaren Erläuterung. Keine Summen,
// Differenzen, Schätzungen oder Umrechnungen zwischen Raumebenen (meta.json geheimhaltung_hinweis): Vergleichswerte
// für Stadtbezirk und ganz Köln kommen aus ihren eigenen Zeilen, Werte des Wegweisers Kommune stehen getrennt daneben.
// Keine Rangfolgen: Tabellen lassen sich sortieren, tragen aber keine Platzziffer.

const ORT = "data/strukturdaten/";
const SPALTEN = ["raumebene", "raum_id", "indikator_id", "jahr", "wert", "status", "quellobjekt"];
const MIT_WERT = new Set(["ok", "abgeleitet"]);
// Farbfolge der Flächen: ColorBrewer YlGnBu, 5 Stufen (sequenziell, für Farbfehlsichtigkeit geeignet; hell = niedrig)
export const FARBEN = ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"];
const FEHLT_FARBE = "#d4d4d8";
const EBENE = {
  gesamtstadt: { ein: "ganz Köln", viele: "ganz Köln" },
  // der: Genitiv Plural („Zahl der …“)
  stadtbezirk: { ein: "Stadtbezirk", viele: "Stadtbezirke", der: "Stadtbezirke", je: "je Stadtbezirk" },
  stadtteil: { ein: "Stadtteil", viele: "Stadtteile", der: "Stadtteile", je: "je Stadtteil" },
  quartier: { ein: "Statistisches Quartier", viele: "Statistische Quartiere", der: "Statistischen Quartiere", je: "je Statistischem Quartier" },
};
// Gebietsart in app.js → Raumebene des Datenvertrags
const ART_EBENE = { ortsteil: "stadtteil", bezirk: "stadtbezirk" };

// --- reine Hilfen (ohne Dokument; tests/test_strukturdaten_seite.py prüft sie mit node) ---------------------------------
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : null);
const ZAHL = [0, 1, 2].map((d) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));
const DATUM = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", year: "numeric" });
export const datum = (iso) => (/^\d{4}-\d{2}-\d{2}/.test(String(iso || "")) ? DATUM.format(new Date(String(iso).slice(0, 10) + "T12:00:00Z")) : "");

// TSV des Datenvertrags (UTF-8, Tabulator, LF, ohne Anführungszeichen) → Zeilen als Objekte; mit `spalten` muss der
// Kopf genau so lauten (sonst Fehler statt falscher Zuordnung)
export function tsv(text, spalten) {
  const zeilen = String(text).split("\n");
  if (zeilen.length && zeilen[zeilen.length - 1] === "") zeilen.pop();
  const kopf = (zeilen.shift() || "").split("\t");
  if (spalten && kopf.join("\t") !== spalten.join("\t")) throw new Error(`unerwarteter Kopf: ${kopf.join(", ")}`);
  return zeilen.map((z) => {
    const f = z.split("\t"), o = {};
    kopf.forEach((k, i) => { o[k] = f[i] ?? ""; });
    return o;
  });
}
// Zeile mit veröffentlichtem oder abgeleitetem Wert (status ok oder abgeleitet, Feld wert nicht leer)
export const hatWert = (z) => Boolean(z) && MIT_WERT.has(z.status) && z.wert !== "" && Number.isFinite(Number(z.wert));
// jüngste Zeile mit Wert einer nach Jahr geordneten Reihe; ohne Wert null
export function juengsteMitWert(reihe) {
  for (let i = (reihe || []).length - 1; i >= 0; i--) if (hatWert(reihe[i])) return reihe[i];
  return null;
}
// Nachkommastellen der Anzeige: Anzahlen ganz, alles andere eine Stelle (der genaue Wert steht in der Erläuterung)
export const stellenFuer = (typ) => (typ === "anzahl" ? 0 : 1);
export function zahl(wert, stellen) {
  const n = Number(wert);
  return Number.isFinite(n) ? ZAHL[Math.max(0, Math.min(2, stellen))].format(n) : "–";
}
// genauer Wert der Datei, nur mit Komma statt Punkt (nicht gerundet)
export const genau = (wert) => String(wert).replace(".", ",");
// Einheit hinter der Zahl; „Anzahl“ ohne Einheit
export const einheitText = (einheit) => (einheit && einheit !== "Anzahl" ? einheit : "");

// Wert, wie ihn die Anzeige mit `stellen` Nachkommastellen zeigt: dieselbe Rundung wie zahl() (Intl.NumberFormat, nur
// ohne Tausenderpunkt und mit Dezimalpunkt). Nicht toFixed: das rundet den Binärwert (0,35 → 0,3), die Anzeige die
// Dezimalzahl (0,35 → 0,4)
const ROH = [0, 1, 2].map((d) => new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: false }));
export const gerundet = (wert, stellen) => Number(ROH[Math.max(0, Math.min(2, stellen))].format(Number(wert)));
// Klassengrenzen für die Flächenfarben: 20-, 40-, 60- und 80-%-Quantil der Werte (Index ⌊q·(n−1)⌋ der aufsteigend
// sortierten Werte, wie die übrigen Flächenfarben in app.js), gerundet auf eine Nachkommastelle (zwei, wenn sonst
// Grenzen zusammenfallen); gleiche Grenzen fallen zusammen, Grenzen, die nicht über dem gerundeten Minimum liegen,
// entfallen. Eingeordnet wird der angezeigte, ebenso gerundete Wert (klasse mit `stellen`): Klasse k = Zahl der Grenzen
// ≤ Wert, ein Wert, der gerundet auf der Grenze liegt, gehört zur oberen Klasse. So stimmen Zahl, Farbe und Legende
// überein, und keine Klasse bleibt leer (jede Grenze ist selbst ein gerundeter Wert der Reihe).
export function grenzen(werte) {
  const v = werte.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return { grenzen: [], stellen: 1 };
  const mit = (stellen) => {
    const unten = gerundet(v[0], stellen);
    return [...new Set([0.2, 0.4, 0.6, 0.8].map((q) => gerundet(v[Math.floor(q * (v.length - 1))], stellen)))]
      .filter((x) => x > unten);
  };
  const eine = mit(1), zwei = eine.length < 4 ? mit(2) : eine;
  return zwei.length > eine.length ? { grenzen: zwei, stellen: 2 } : { grenzen: eine, stellen: 1 };
}
// Klasse eines Werts; mit `stellen` der angezeigte (gerundete) Wert, ohne der genaue
export const klasse = (wert, g, stellen) => {
  const x = stellen == null ? Number(wert) : gerundet(wert, stellen);
  return g.filter((b) => x >= b).length;
};
// Farbe der Klasse k bei n Klassen: über die ganze Farbfolge verteilt (5 Klassen: alle Stufen; 3 Klassen: hell, mittel,
// dunkel), damit auch wenige Klassen deutlich unterscheidbar bleiben
export const farbIndex = (k, n) => (n <= 1 ? 2 : Math.round((k * (FARBEN.length - 1)) / (n - 1)));
// Beschriftung der Klassen: „unter a“, „a bis unter b“, „ab c“ (Zahlen mit den Stellen der Grenzen)
export function klassenText(g, stellen, einheit) {
  const e = einheitText(einheit), mit = (x) => (e && e.length <= 5 ? `${zahl(x, stellen)} ${e}` : zahl(x, stellen));
  if (!g.length) return ["alle Werte"];
  return [0, ...g].map((lo, k) => (k === 0 ? `unter ${mit(g[0])}` : k === g.length ? `ab ${mit(lo)}`
    : `${zahl(lo, stellen)} bis unter ${mit(g[k])}`));
}
// Jahr des Vergleichs im Wegweiser: jüngstes Jahr, für das alle Kommunen einen Wert haben (sonst null)
export function gemeinsamesJahr(zeilen, kommunen) {
  const je = new Map();
  for (const z of zeilen) {
    if (!je.has(z.jahr)) je.set(z.jahr, new Set());
    je.get(z.jahr).add(z.kommune);
  }
  const jahre = [...je].filter(([, k]) => kommunen.every((x) => k.has(x))).map(([j]) => j).sort();
  return jahre.length ? jahre[jahre.length - 1] : null;
}
// Sortierung der Tabelle (keine Rangfolge): Name nach deutschem Alphabet; Wert numerisch, Zeilen ohne Wert immer am
// Ende; Status nach Text; bei Gleichstand nach Name
export function sortiert(zeilen, schluessel, richtung) {
  const r = richtung === "absteigend" ? -1 : 1;
  const name = (a, b) => a.name.localeCompare(b.name, "de");
  return [...zeilen].sort((a, b) => {
    if (schluessel === "wert") {
      const x = a.wert == null, y = b.wert == null;
      if (x || y) return x === y ? name(a, b) : x ? 1 : -1;
      return (a.wert - b.wert) * r || name(a, b);
    }
    if (schluessel === "status") return a.statusText.localeCompare(b.statusText, "de") * r || name(a, b);
    return name(a, b) * r;
  });
}
// kleine Zeitreihe als SVG-Pfade (Linie nur zwischen aufeinanderfolgenden Jahren mit Wert; Lücken bei geheim/fehlt)
export function linie(reihe, breite = 96, hoehe = 28) {
  const jahre = reihe.map((z) => Number(z.jahr));
  const werte = reihe.map((z) => (hatWert(z) ? Number(z.wert) : null));
  const da = werte.filter((x) => x != null);
  if (!reihe.length || !da.length) return { pfade: [], punkte: [] };
  const j0 = Math.min(...jahre), j1 = Math.max(...jahre), lo = Math.min(...da), hi = Math.max(...da);
  const x = (j) => (j1 === j0 ? breite / 2 : 2 + ((j - j0) / (j1 - j0)) * (breite - 4));
  const y = (v) => (hi === lo ? hoehe / 2 : hoehe - 3 - ((v - lo) / (hi - lo)) * (hoehe - 6));
  const pfade = [], punkte = [];
  let teil = [];
  reihe.forEach((z, i) => {
    if (werte[i] == null) { if (teil.length) pfade.push(teil); teil = []; return; }
    teil.push([x(jahre[i]), y(werte[i])]);
  });
  if (teil.length) pfade.push(teil);
  const runde = (p) => p.map(([a, b]) => [Math.round(a * 10) / 10, Math.round(b * 10) / 10]);
  for (const p of pfade) if (p.length === 1) punkte.push(runde(p)[0]);
  const letzte = reihe.map((z, i) => [z, i]).filter(([, i]) => werte[i] != null).pop();
  return { pfade: pfade.filter((p) => p.length > 1).map((p) => runde(p).map(([a, b], i) => `${i ? "L" : "M"}${a} ${b}`).join(" ")),
    punkte, letzter: letzte ? runde([[x(jahre[letzte[1]]), y(werte[letzte[1]])]])[0] : null };
}

// --- Daten laden (je Datei einmal, im Speicher) ----------------------------------------------------------------------
const cache = new Map();
function holen(pfad, art) {
  if (!cache.has(pfad)) {
    const p = fetch(ORT + pfad).then((r) => {
      if (!r.ok) throw new Error(`${pfad}: HTTP ${r.status}`);
      return art === "json" ? r.json() : r.text();
    });
    p.catch(() => cache.delete(pfad));   // beim nächsten Mal erneut versuchen
    cache.set(pfad, p);
  }
  return cache.get(pfad);
}
const gemerkt = new Map();
const einmal = (k, f) => { if (!gemerkt.has(k)) { const p = f(); p.catch(() => gemerkt.delete(k)); gemerkt.set(k, p); } return gemerkt.get(k); };
const anzeige = () => holen("anzeige.json", "json");
const metaJson = () => holen("meta.json", "json");
// meta.json erst, wenn Panel, Vorgang, Flächenfarben oder die Quellenzeile ihn brauchen (nicht beim Seitenstart)
const metaLaden = async () => { M = M || await metaJson(); return M; };
const indikatoren = () => einmal("ind", async () => new Map(tsv(await holen("indikatoren.tsv")).map((z) => [z.indikator_id, z])));
const gesamtstadt = () => einmal("ww", async () => tsv(await holen("gesamtstadt.tsv")));
// Flächen und Namen einer Raumebene (Namen wie ortsteil_bez/bezirk_bez in data/geo, Eltern über eltern_id); nur für die
// Flächenfarben
const raum = (ebene) => einmal(`raum:${ebene}`, async () => {
  const geo = await holen(`raum/${ebene}.geojson`, "json");
  const nachId = new Map(), nachName = new Map();
  for (const f of geo.features) { nachId.set(String(f.properties.raum_id), f.properties); nachName.set(f.properties.name, f.properties); }
  return { geo, nachId, nachName };
});
// Namen und Eltern der Stadtbezirke und Stadtteile ohne Geometrie (anzeige.json raeume, aus raum/<ebene>.geojson);
// Quartiere und ältere Fassungen von anzeige.json über die Geometrie
const namen = (ebene) => einmal(`namen:${ebene}`, async () => {
  const r = A.raeume, liste = r && r[ebene];
  if (!liste) { const g = await raum(ebene); return { nachId: g.nachId, nachName: g.nachName }; }
  const nachId = new Map(), nachName = new Map();
  for (const z of liste) {
    const p = Object.fromEntries(r.spalten.map((k, i) => [k, z[i]]));
    nachId.set(String(p.raum_id), p);
    nachName.set(p.name, p);
  }
  return { nachId, nachName };
});
// alle Zeilen einer Einheit, je Indikator nach Jahr (Reihenfolge wie werte.tsv)
const raumwerte = (ebene, id) => einmal(`rw:${ebene}:${id}`, async () => {
  const je = new Map();
  for (const z of tsv(await holen(`raumwerte/${ebene}/${id}.tsv`), SPALTEN)) {
    if (!je.has(z.indikator_id)) je.set(z.indikator_id, []);
    je.get(z.indikator_id).push(z);
  }
  for (const r of je.values()) r.sort((a, b) => a.jahr.localeCompare(b.jahr));
  return je;
});
const karte = (ebene, ind) => einmal(`k:${ebene}:${ind}`, async () => tsv(await holen(`karte/${ebene}/${ind}.tsv`), SPALTEN));

// --- Steuerung -------------------------------------------------------------------------------------------------------
let ctx = null, A = null, M = null;
const quelleStat = () => (M.quellen || []).find((q) => q.kennung === "statistischer-datenkatalog-koeln") || {};
const quelleQuartiere = () => (M.quellen || []).find((q) => q.kennung === "statistische-quartiere-koeln") || {};
const quelleWw = () => (M.quellen || []).find((q) => q.kennung === "wegweiser-indikatoren") || {};
const abgeleitet = (id) => Boolean(M && M.abgeleitet && M.abgeleitet.indikatoren && M.abgeleitet.indikatoren[id]);
// Status in Worten; bei abgeleiteten Anteilen ohne Wert (status fehlt) hat die Quelle Werte, nur der Anteil ist nicht
// bildbar (Eingangswert fehlt oder Bezugsgröße 0)
const statusText = (z) => (!z ? A.texte.fehlt : z.status === "geheim" ? A.texte.geheim
  : z.status === "fehlt" ? (abgeleitet(z.indikator_id) && A.texte.fehlt_abgeleitet ? A.texte.fehlt_abgeleitet : A.texte.fehlt)
  : z.status === "abgeleitet" ? "abgeleitet" : "Wert der Quelle");
// Abzeichen „abgeleitet“ nur, wenn der Name es nicht schon sagt (die Namen der abgeleiteten Indikatoren enden auf
// „(abgeleitet)“)
const abzeichen = (id, ind) => (abgeleitet(id) && !/\(abgeleitet\)/.test((ind && ind.name) || "") ? ' <span class="derived">abgeleitet</span>' : "");
// Formel und Hinweis eines abgeleiteten Indikators (meta.json abgeleitet, anzeige.json texte.abgeleitet)
const formelText = (id) => (abgeleitet(id) ? `${A.texte.abgeleitet || "abgeleitet"}. Formel: ${M.abgeleitet.indikatoren[id].formel}; ${M.abgeleitet.indikatoren[id].stellen} Nachkommastellen, kaufmännisch gerundet.` : "");
const link = (url, text) => { const u = safeUrl(url); return u ? `<a href="${u}" target="_blank" rel="noopener">${text}<span class="visually-hidden"> (neuer Tab)</span></a>` : text; };
const begriff = (anker, text) => (ctx.begriffDa(anker) ? `<a href="begriffe/#${esc(anker)}">${esc(text)}</a>` : esc(text));
// Texte des Schalters und der Tour (tour.js liest data-tour-karte und data-tour-liste sichtbarer Elemente)
const SCHALTER = {
  text: "Strukturdaten",
  titel: "Flächenfarben nach Kennzahlen der Kölner Stadtstatistik",
  tourKarte: "„Strukturdaten“ färbt Stadtteile, Stadtbezirke oder Statistische Quartiere nach einer Kennzahl der Kölner Stadtstatistik, mit Legende und gleichwertiger Tabelle; zur Einordnung, kein Urteil über ein Gebiet.",
  tourListe: "Unter „Strukturdaten zu …“ stehen Zahlen der Stadtstatistik zum gewählten Gebiet mit Jahr, Zeitreihe und Quelle.",
};

export async function init(api) {
  ctx = api;
  A = await anzeige();
  if (!document.querySelector('link[data-strukturdaten]')) {
    const css = document.createElement("link");
    Object.assign(css, { rel: "stylesheet", href: "strukturdaten/strukturdaten.css" });
    css.dataset.strukturdaten = "";
    document.head.appendChild(css);
  }
  schalterEinrichten();
  fusszeile();
  return { gebiet, vorgang, ebene, an: () => lage.an, zustand, start };
}

// Schalter „Strukturdaten“ im Menü „Ebenen“: app.js legt ihn verborgen und ohne Text an (damit er mit den übrigen
// Schaltern ins Blatt „Karte“ wandert); Beschriftung, Bedienung und Sichtbarkeit kommen von hier
function schalterEinrichten() {
  const b = schalter();
  if (!b || b.dataset.bereit) return;
  b.dataset.bereit = "1";
  b.textContent = SCHALTER.text;
  b.title = SCHALTER.titel;
  b.dataset.tourKarte = SCHALTER.tourKarte;
  b.dataset.tourListe = SCHALTER.tourListe;
  b.addEventListener("click", async () => {
    const an = !lage.an;
    await ebene(an);
    if (!an) { ctx.ansage("Flächenfarben der Strukturdaten ausgeschaltet."); return; }
    // Tastatur: Auswahl und Legende erscheinen unten links bzw. im Blatt „Karte“; dorthin führen und es ansagen
    ctx.ansage("Flächenfarben eingeschaltet. Auswahl und Legende unter „Flächenfarben: Strukturdaten“.");
    const s = legende && legende.querySelector("summary");
    if (s && lage.an) s.focus();
  });
  b.hidden = false;
}

// Quellen, Lizenzen und Datenstand (Fußzeile der Karte): ersetzt den festen Text aus index.html durch die Angaben aus
// meta.json, sobald die Quellenzeile aufgeht (nur mit Freigabe; ohne Freigabe entfernt seo.ohne_abgeschaltete den Satz)
function fusszeile() {
  const el = document.querySelector('#sources [data-funktion="strukturdaten"]');
  const quellen = document.getElementById("sources");
  if (!el || !quellen) return;
  const fuellen2 = async () => {
    if (el.dataset.gefuellt) return;
    try { await metaLaden(); } catch { return; }   // fester Text aus index.html bleibt
    el.dataset.gefuellt = "1";
    const s = quelleStat(), q = quelleQuartiere(), w = quelleWw();
    el.innerHTML = ` · Strukturdaten: ${link(s.datensatz_url, "Statistischer Datenkatalog Köln")} (${esc(s.herausgeber || "")}; ${link(s.lizenz_url, esc(s.lizenz || ""))}), Datenstand ${esc(datum(M.datenstand))}; Statistische Quartiere (${esc(q.herausgeber || "")}, ${esc(q.lizenz || "")}); Vergleich der Städte aus dem ${link(w.datensatz_url, "Wegweiser Kommune")} (${esc(w.herausgeber || "")}, ${esc(w.lizenz || "")}). Altersanteile vom Ratsatlas berechnet (abgeleitet)`;
  };
  if (quellen.open) fuellen2();
  else quellen.addEventListener("toggle", () => { if (quellen.open) fuellen2(); });
}
function quelleZeile() {
  const s = quelleStat();
  return `Quelle: ${link(s.datensatz_url, "Statistischer Datenkatalog Köln")} – ${esc(s.herausgeber || "")}, ${link(s.lizenz_url, esc(s.lizenz || ""))}; Datenstand ${esc(datum(M.datenstand))}. Altersanteile vom Ratsatlas aus veröffentlichten Altersgruppen berechnet (abgeleitet). <a href="data/LICENSE-DATA.md">Lizenzen der Daten</a>`;
}

// --- Kontext-Panel in der Liste (Gebiet) -----------------------------------------------------------------------------
let box = null, boxSeq = 0, boxFuer = "";
// Einheit des Gebiets in app.js: {ebene, id, name, eltern} oder null (ohne Ortsbezug); Namen ohne Geometrie
async function einheit(gebiet) {
  if (!gebiet) return null;
  if (gebiet.kind === ctx.stadt) return { ebene: "gesamtstadt", id: "0", name: "ganz Köln" };
  const ebene = ART_EBENE[gebiet.kind];
  if (!ebene) return null;
  const r = await namen(ebene), p = r.nachName.get(gebiet.name);
  if (!p) return null;
  let eltern = null;
  if (ebene === "stadtteil" && p.eltern_id) {
    const b = (await namen("stadtbezirk")).nachId.get(String(p.eltern_id));
    if (b) eltern = { ebene: "stadtbezirk", id: String(b.raum_id), name: b.name };
  }
  return { ebene, id: String(p.raum_id), name: p.name, eltern };
}
function gebiet() {
  const g = ctx.gebiet();
  const sichtbar = g && (g.kind === ctx.stadt || ART_EBENE[g.kind]);
  if (!box) {
    const ort = document.getElementById("kontext-box");
    if (!ort) return;
    box = document.createElement("details");
    box.className = "acc kontext sd-box";
    box.id = "sd-box";
    box.innerHTML = '<summary></summary><div class="sd-inhalt"></div>';
    box.addEventListener("toggle", () => { if (box.open && boxFuer !== schluessel(ctx.gebiet())) fuellen(); });
    ort.after(box);
  }
  box.hidden = !sichtbar;
  if (!sichtbar) return;
  const name = g.kind === ctx.stadt ? "ganz Köln" : g.name;
  box.querySelector("summary").innerHTML = `Strukturdaten zu ${esc(name)}<span class="derived">Stadtstatistik</span>`;
  if (box.open) fuellen(); else boxFuer = "";
}
const schluessel = (g) => (g ? `${g.kind}:${g.key}` : "");
async function fuellen() {
  const seq = ++boxSeq, g = ctx.gebiet(), inhalt = box.querySelector(".sd-inhalt");
  boxFuer = schluessel(g);
  inhalt.innerHTML = '<p class="hint" role="status">Strukturdaten werden geladen …</p>';
  try {
    const [e] = await Promise.all([einheit(g), metaLaden()]);
    if (seq !== boxSeq) return;
    if (!e) { inhalt.innerHTML = `<p class="hint">Für dieses Gebiet gibt es keine Strukturdaten.</p>`; return; }
    const [I, eigen, eltern, stadt] = await Promise.all([indikatoren(), raumwerte(e.ebene, e.id),
      e.eltern ? raumwerte(e.eltern.ebene, e.eltern.id) : null, e.ebene === "gesamtstadt" ? null : raumwerte("gesamtstadt", "0")]);
    if (seq !== boxSeq) return;
    const d = { e, I, eigen, eltern, stadt };
    const themen = A.kern.themen.map((t) => `<section class="sd-thema" aria-labelledby="sd-t-${esc(slug(t.thema))}">
      <h4 id="sd-t-${esc(slug(t.thema))}">${esc(t.thema)}</h4><ul class="sd-liste">${t.indikatoren.map((id) => eintrag(id, d)).join("")}</ul></section>`).join("");
    const kern = new Set(A.kern.themen.flatMap((t) => t.indikatoren));
    const weitere = A.weitere.themen.map((t) => ({ t, ids: [...I.values()].filter((i) => i.indikator_id.startsWith("koeln_")
      && !kern.has(i.indikator_id) && i.thema === t).map((i) => i.indikator_id) })).filter((x) => x.ids.length);
    const n = weitere.reduce((s, x) => s + x.ids.length, 0);
    inhalt.innerHTML = `<p class="hint">${esc(A.texte.einordnung)} ${esc(A.texte.fehlschluss)} (${begriff("oekologischer-fehlschluss", "ökologischer Fehlschluss")})</p>
      <p class="hint">Je Kennzahl das jüngste Jahr mit Wert${e.ebene === "gesamtstadt" ? "" : `; daneben ${e.eltern ? `Stadtbezirk ${esc(e.eltern.name)} und ` : ""}ganz Köln im selben Jahr`}, jeweils wie von der Stadt veröffentlicht oder daraus abgeleitet (gekennzeichnet), nicht umgerechnet. Die kleine Linie zeigt den Verlauf zwischen kleinstem und größtem Wert der Reihe, ohne Maßstab; die Zahlen stehen unter „Zeitreihe und Erläuterung“.</p>
      ${themen}
      <details class="acc sd-weitere"><summary>Weitere Kennzahlen (${n})</summary><div>${weitere.map((x) =>
        `<details class="acc sd-gruppe" data-thema="${esc(x.t)}"><summary>${esc(x.t)} (${x.ids.length})</summary><ul class="sd-liste" data-ids="${esc(x.ids.join(" "))}"></ul></details>`).join("")}</div></details>
      ${await vergleich()}
      <p class="hint sd-quelle">${quelleZeile()}</p>`;
    if (seq !== boxSeq) return;
    // weitere Kennzahlen erst beim Aufklappen (je Thema)
    inhalt.querySelectorAll(".sd-gruppe").forEach((g2) => g2.addEventListener("toggle", () => {
      const ul = g2.querySelector("ul");
      if (g2.open && !ul.childElementCount) ul.innerHTML = ul.dataset.ids.split(" ").map((id) => eintrag(id, d)).join("");
    }));
  } catch (err) {
    if (seq !== boxSeq) return;
    boxFuer = "";
    inhalt.innerHTML = `<p class="hint">Die Strukturdaten konnten nicht geladen werden (${esc(err.message)}).</p>`;
  }
}
const slug = (s) => String(s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
let eintragN = 0;
// Wert einer Einheit für die Anzeige: Zeile mit Wert (jüngstes Jahr) oder die jüngste Zeile ohne Wert (Status)
function eintrag(id, d) {
  const ind = d.I.get(id);
  if (!ind) return "";
  const reihe = d.eigen.get(id) || [], z = juengsteMitWert(reihe) || reihe[reihe.length - 1] || null;
  const jahr = z ? z.jahr : null, st = stellenFuer(ind.typ), ein = einheitText(ind.einheit);
  // lange Einheiten („je 1000 Einwohner*innen“) in der Tabelle nur einmal über den Spalten, nicht in jeder Zelle
  const kurz = Boolean(ein) && ein.length <= 5;
  const imJahr = (m) => (m && jahr ? (m.get(id) || []).find((x) => x.jahr === jahr) || null : null);
  const bz = imJahr(d.eltern), st0 = imJahr(d.stadt);
  const wert = (x) => (hatWert(x) ? zahl(x.wert, st) + (ein ? ` ${esc(ein)}` : "") : `<span class="sd-ohne">${esc(statusText(x))}</span>`);
  const zelle = (x) => (hatWert(x) ? zahl(x.wert, st) + (kurz ? ` ${esc(ein)}` : "") : `<span class="sd-ohne">${esc(statusText(x))}</span>`);
  // spätere Jahre ohne Wert (geheim oder keine Angabe) nennen, damit das gezeigte Jahr nicht als jüngstes erscheint
  const spaeter = reihe.filter((x) => jahr && x.jahr > jahr).map((x) => `${esc(x.jahr)}: ${esc(statusText(x))}`).join("; ");
  const nr = ++eintragN;
  const vgl = [d.eltern ? `Stadtbezirk ${esc(d.e.eltern.name)}: ${wert(bz)}` : "", d.stadt ? `ganz Köln: ${wert(st0)}` : ""].filter(Boolean).join(" · ");
  const l = linie(reihe);
  const svg = l.pfade.length || l.punkte.length ? `<svg class="sd-linie" viewBox="0 0 96 28" width="96" height="28" aria-hidden="true" focusable="false">
      ${l.pfade.map((p) => `<path d="${p}"/>`).join("")}${l.punkte.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.6"/>`).join("")}
      ${l.letzter ? `<circle class="sd-letzter" cx="${l.letzter[0]}" cy="${l.letzter[1]}" r="2.4"/>` : ""}</svg>` : "";
  const abg = abgeleitet(id) ? `<p class="hint">${esc(formelText(id))}</p>` : "";
  const ww = A.vergleich.gegenstueck[id] && d.I.get(A.vergleich.gegenstueck[id]);
  const herkunft = (x, wo) => (x ? `<li>${esc(wo)}, ${esc(x.jahr)}: ${hatWert(x) ? esc(genau(x.wert)) : esc(statusText(x))} (Status ${esc(x.status)}, Quellobjekt ${esc(x.quellobjekt)})</li>` : "");
  const zeilen = reihe.map((x) => `<tr><th scope="row">${esc(x.jahr)}</th><td>${zelle(x)}</td>${d.eltern ? `<td>${zelle((d.eltern.get(id) || []).find((y) => y.jahr === x.jahr))}</td>` : ""}${d.stadt ? `<td>${zelle((d.stadt.get(id) || []).find((y) => y.jahr === x.jahr))}</td>` : ""}</tr>`).join("");
  return `<li class="sd-wert">
    <div class="sd-kopf"><span class="sd-name" id="sd-n-${nr}">${esc(ind.name)}</span>${abzeichen(id, ind)}</div>
    <div class="sd-zeile"><span class="sd-zahl">${hatWert(z) ? esc(zahl(z.wert, st)) : `<span class="sd-ohne">${esc(statusText(z))}</span>`}</span>${hatWert(z) && ein ? `<span class="sd-einheit">${esc(ein)}</span>` : ""}${jahr ? `<span class="sd-jahr">${esc(jahr)}</span>` : ""}${svg}</div>
    ${vgl ? `<p class="sd-vgl">${vgl}</p>` : ""}
    ${spaeter ? `<p class="sd-vgl">${spaeter}</p>` : ""}
    <details class="sd-mehr"><summary>Zeitreihe und Erläuterung<span class="visually-hidden">: ${esc(ind.name)}</span></summary>
      ${reihe.length ? `${ein && !kurz ? `<p class="hint">Einheit der Tabelle: ${esc(ein)}</p>` : ""}<table class="kontext-table sd-reihe"><caption class="visually-hidden">Zeitreihe ${esc(ind.name)}${ein ? `, ${esc(ein)}` : ""}</caption>
        <thead><tr><th scope="col">Jahr</th><th scope="col">${esc(d.e.name)}</th>${d.eltern ? `<th scope="col">Stadtbezirk ${esc(d.e.eltern.name)}</th>` : ""}${d.stadt ? '<th scope="col">ganz Köln</th>' : ""}</tr></thead>
        <tbody>${zeilen}</tbody></table>` : `<p class="hint">${esc(A.texte.fehlt)}</p>`}
      <p>${esc(ind.metatext)}</p>${abg}
      ${ww ? `<p class="hint">Gegenstück im Wegweiser Kommune: ${esc(ww.name)} (Tabelle „Köln, Bonn und Wuppertal“). ${esc(A.texte.vergleich)}</p>` : ""}
      <p class="hint">Einheit: ${esc(ind.einheit)} · Jahre: ${esc(ind.jahre)} · Datenhalter: ${esc(ind.datenhalter)} · Lizenz: ${link(ind.lizenz_url, esc(ind.lizenz))} · Namensnennung: ${esc(ind.namensnennung)} · abgerufen am ${esc(datum(ind.abrufdatum))}</p>
      <p class="hint">Geheimhaltung: ${esc(ind.geheimhaltung)}</p>
      <p class="hint">Herkunft der gezeigten Werte (Zeile im Datenvertrag, genauer Wert):</p>
      <ul class="sd-herkunft">${herkunft(z, d.e.name)}${herkunft(bz, d.e.eltern ? `Stadtbezirk ${d.e.eltern.name}` : "")}${herkunft(st0, "ganz Köln")}</ul>
    </details></li>`;
}
// Vergleich Bonn, Köln, Wuppertal aus dem Wegweiser Kommune (gesamtstadt.tsv): eigene Tabelle, eigene Quelle; je
// Kennzahl eine aufklappbare Erläuterung mit Datenhalter, Metatext und Namensnennung aus indikatoren.tsv
async function vergleich() {
  const [I, zeilen] = await Promise.all([indikatoren(), gesamtstadt()]);
  const kommunen = A.vergleich.kommunen.map((k) => k.kommune);
  const rows = A.vergleich.indikatoren.map((id) => {
    const ind = I.get(id);
    if (!ind) return "";
    const eigene = zeilen.filter((z) => z.indikator_id === id), jahr = gemeinsamesJahr(eigene, kommunen);
    const st = stellenFuer(ind.typ);
    const zelle = (k) => { const z = eigene.find((x) => x.kommune === k && x.jahr === jahr); return `<td>${z ? esc(zahl(z.wert, st)) : "–"}</td>`; };
    return `<tr><th scope="row">${esc(ind.name)}<span class="sd-einheit-klein">${esc(ind.einheit)}, ${jahr ? esc(jahr) : "kein gemeinsames Jahr"}</span></th>${kommunen.map(zelle).join("")}</tr>`;
  }).join("");
  const erl = A.vergleich.indikatoren.map((id) => {
    const ind = I.get(id);
    return ind ? `<li><details class="sd-mehr"><summary>${esc(ind.name)}<span class="visually-hidden">: Erläuterung und Datenhalter</span></summary>
      <p>Datenhalter laut Wegweiser Kommune: ${esc(ind.datenhalter || "–")}</p>
      <p>${esc(ind.metatext)}</p>
      <p class="hint">Einheit: ${esc(ind.einheit)} · Jahre: ${esc(ind.jahre)} · Lizenz: ${link(ind.lizenz_url, esc(ind.lizenz))} · Namensnennung: ${esc(ind.namensnennung)} · abgerufen am ${esc(datum(ind.abrufdatum))}</p></details></li>` : "";
  }).join("");
  const w = quelleWw();
  const halter = [...new Set(A.vergleich.indikatoren.flatMap((id) => String((I.get(id) || {}).datenhalter || "").split(/,\s*/)).filter(Boolean))];
  const paare = Object.entries(A.vergleich.gegenstueck).filter(([k, ww]) => I.get(k) && I.get(ww))
    .map(([k, ww]) => `<li>${esc(I.get(ww).name)}: ${esc(I.get(k).name)}</li>`).join("");
  return `<details class="acc sd-vergleich"><summary>Köln, Bonn und Wuppertal (Wegweiser Kommune)</summary><div>
    <p class="hint">${esc(A.texte.vergleich)} Je Kennzahl das jüngste Jahr, für das alle drei Städte einen Wert haben.</p>
    <div class="sd-scroll" tabindex="0" role="region" aria-label="Vergleich der Städte (Tabelle, seitlich verschiebbar)">
    <table class="kontext-table sd-ww"><caption class="visually-hidden">Vergleich der Städte laut Wegweiser Kommune</caption>
      <thead><tr><th scope="col">Kennzahl, Einheit, Jahr</th>${A.vergleich.kommunen.map((k) => `<th scope="col">${esc(k.name)}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody></table></div>
    ${erl ? `<p class="hint">Erläuterung und Datenhalter je Kennzahl:</p><ul class="sd-erl">${erl}</ul>` : ""}
    ${paare ? `<p class="hint">Ähnliche Kennzahlen der Kölner Stadtstatistik (oben, andere Quelle; nur nebeneinander, nicht verrechnet):</p><ul class="sd-herkunft">${paare}</ul>` : ""}
    <p class="hint">Quelle: ${link(w.datensatz_url, "Bertelsmann Stiftung, wegweiser-kommune.de")}, Lizenz ${link(w.lizenz_url, esc(w.lizenz || ""))}; Datenhalter aller Kennzahlen zusammen: ${esc(halter.join("; "))} (je Kennzahl in der Erläuterung). Abgerufen am ${esc(datum(M.abrufdatum))}.</p></div></details>`;
}

// --- kompakt im Vorgang (ein Stadtteil laut Verortung) ---------------------------------------------------------------
async function vorgang(platz, stadtteil) {
  if (!platz || !stadtteil) return;
  const r = await namen("stadtteil").catch(() => null);
  if (!platz.isConnected || !r || !r.nachName.has(stadtteil)) return;
  platz.innerHTML = `<details class="acc kontext sd-box sd-vorgang"><summary>Strukturdaten zum Stadtteil ${esc(stadtteil)}</summary><div class="sd-inhalt"></div></details>`;
  const det = platz.firstElementChild;
  det.addEventListener("toggle", async () => {
    const inhalt = det.querySelector(".sd-inhalt");
    if (!det.open || inhalt.childElementCount) return;
    inhalt.innerHTML = '<p class="hint" role="status">Strukturdaten werden geladen …</p>';
    try {
      const [e] = await Promise.all([einheit({ kind: "ortsteil", name: stadtteil }), metaLaden()]);
      const [I, eigen, eltern, stadt] = await Promise.all([indikatoren(), raumwerte(e.ebene, e.id), e.eltern ? raumwerte(e.eltern.ebene, e.eltern.id) : null, raumwerte("gesamtstadt", "0")]);
      const zeile = (id) => {
        const ind = I.get(id);
        if (!ind) return "";
        const reihe = eigen.get(id) || [], z = juengsteMitWert(reihe) || reihe[reihe.length - 1] || null, jahr = z && z.jahr;
        const st = stellenFuer(ind.typ), ein = einheitText(ind.einheit);
        const zelle = (x) => `<td>${hatWert(x) ? esc(zahl(x.wert, st)) + (ein && ein.length <= 5 ? ` ${esc(ein)}` : "") : `<span class="kontext-note">${esc(statusText(x))}</span>`}</td>`;
        const im = (m) => (m && jahr ? (m.get(id) || []).find((x) => x.jahr === jahr) : null);
        // lange Einheit hinter dem Namen, außer der Name nennt sie schon („Zuzüge je 100 Einwohner*innen“)
        const nachName = ein && ein.length > 5 && !ind.name.includes(ein) ? `, ${esc(ein)}` : "";
        return `<tr><th scope="row">${esc(ind.name)}${nachName} (${esc(jahr || "–")})${abzeichen(id, ind)}</th>${zelle(z)}${e.eltern ? zelle(im(eltern)) : ""}${zelle(im(stadt))}</tr>`;
      };
      inhalt.innerHTML = `<p class="hint">${esc(A.texte.einordnung)} ${esc(A.texte.fehlschluss)} Kein Beleg für die Vorlage.</p>
        <p class="hint">Stadtteil ${esc(e.name)}${e.eltern ? `, Stadtbezirk ${esc(e.eltern.name)}` : ""} und ganz Köln.</p>
        <table class="kontext-table sd-kompakt"><caption class="visually-hidden">Strukturdaten zum Stadtteil ${esc(e.name)}${e.eltern ? `, zum Stadtbezirk ${esc(e.eltern.name)}` : ""} und zu ganz Köln</caption>
        <thead><tr><th scope="col">Kennzahl (Jahr)</th><th scope="col">Stadtteil</th>${e.eltern ? '<th scope="col">Stadtbezirk</th>' : ""}<th scope="col">ganz Köln</th></tr></thead>
        ${A.kern.themen.map((t) => `<tbody><tr class="sd-gruppenzeile"><th scope="rowgroup" colspan="${e.eltern ? 4 : 3}">${esc(t.thema)}</th></tr>${t.indikatoren.map(zeile).join("")}</tbody>`).join("")}</table>
        <p class="hint">Je Kennzahl das jüngste Jahr mit Wert für den Stadtteil; Stadtbezirk und ganz Köln im selben Jahr aus ihren eigenen Zeilen. Zeitreihen, Erläuterungen und genaue Werte in der Liste unter „Strukturdaten“.</p>
        <p class="hint sd-quelle">${quelleZeile()}</p>`;
    } catch (err) {
      inhalt.innerHTML = `<p class="hint">Die Strukturdaten konnten nicht geladen werden (${esc(err.message)}).</p>`;
    }
  });
}

// --- Flächenfarben (Choroplethen) -----------------------------------------------------------------------------------
const lage = { an: false, ind: null, ebene: null, jahr: null, klassen: "quantile" };
let schicht = null, legende = null, renderer = null, zeichenSeq = 0, gewaehlt = null, aktuell = null, warte = null;
// Hinweis zur Fläche nach Klick oder Tippen: höchstens einer offen; ein Klick daneben schließt ihn (Telefon ohne Maus).
// festBis: kurz nach dem Öffnen aus der Tabelle (Telefon) keine Hinweise anderer Flächen durch Mausereignisse, die der
// Browser nach dem Schließen des Bereichs „Vorgang“ unter dem Finger auslöst
let tippOffen = null, klickAufFlaeche = false, festBis = 0;
const SCHRAFFUR = "sd-schraffur", PUNKTE = "sd-punkte";
function defs() {
  const svg = renderer && renderer._container;
  if (!svg || svg.querySelector(`#${SCHRAFFUR}`)) return;
  const d = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  // geheim: schraffiert; keine Angabe: grau mit Punkten (nicht nur über die Helligkeit von den Klassen zu trennen)
  d.innerHTML = `<pattern id="${SCHRAFFUR}" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
    <rect width="6" height="6" fill="#f4f4f5"/><line x1="0" y1="0" x2="0" y2="6" stroke="#52525b" stroke-width="2"/></pattern>
    <pattern id="${PUNKTE}" patternUnits="userSpaceOnUse" width="6" height="6">
    <rect width="6" height="6" fill="${FEHLT_FARBE}"/><circle cx="3" cy="3" r="0.9" fill="#52525b"/></pattern>`;
  svg.insertBefore(d, svg.firstChild);
}
const schalter = () => document.querySelector(".map-sd");
// offene Tabelle der Flächenfarben im Bereich „Vorgang“ (nach dem Ausschalten ohne Bezug)
const tabelleOffen = () => document.getElementById("sd-tabelle");
async function ebene(an, wunsch = {}) {
  const map = ctx.karte();
  lage.an = Boolean(an);
  const b = schalter();
  if (b) b.setAttribute("aria-pressed", String(lage.an));
  if (!lage.an) {
    zeichenSeq++;
    clearTimeout(warte);
    if (schicht) { schicht.remove(); schicht = null; }
    if (legende) { legende.remove(); legende = null; }
    tippOffen = null;
    gewaehlt = null;
    aktuell = null;
    ctx.flaechen(false);
    // die Tabelle gehört zu den Flächenfarben: nicht ohne sie stehen lassen
    if (tabelleOffen()) ctx.detail("Flächenfarben ausgeschaltet", `<h3 tabindex="-1">Flächenfarben ausgeschaltet</h3>
      <p class="hint">Die Tabelle gehörte zu den Flächenfarben der Strukturdaten. Unter „Ebenen“ lassen sie sich mit „Strukturdaten“ wieder einschalten.</p>`, true);
    ctx.syncUrl();
    return;
  }
  ctx.kxAus();   // nur eine Flächenfarbe zugleich: Bodenrichtwerte und Hitze aus
  ctx.flaechen(true);
  const K = A.karte;
  lage.ebene = K.ebenen.includes(wunsch.ebene) ? wunsch.ebene : lage.ebene || K.vorgabe_ebene;
  lage.ind = K.indikatoren.includes(wunsch.ind) ? wunsch.ind : lage.ind || K.indikatoren[0];
  if (!(K.dateien[lage.ebene] || []).includes(lage.ind)) lage.ind = K.indikatoren.find((i) => (K.dateien[lage.ebene] || []).includes(i));
  if (wunsch.jahr) lage.jahr = wunsch.jahr;
  if (wunsch.klassen === "fest" || wunsch.klassen === "quantile") lage.klassen = wunsch.klassen;
  if (!map.getPane("strukturdaten")) map.createPane("strukturdaten").style.zIndex = 355;   // unter den Vorlagenpunkten
  if (!renderer) {
    renderer = ctx.L.svg({ pane: "strukturdaten", padding: 0.3 });
    renderer.on("add", defs);
    map.on("click", () => { if (!klickAufFlaeche && tippOffen) { tippOffen.closeTooltip(); tippOffen = null; } klickAufFlaeche = false; });
    // Hinweise an den Flächen mit Escape schließen (WCAG 1.4.13)
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !schicht) return;
      schicht.eachLayer((l) => { if (l.isTooltipOpen()) l.closeTooltip(); });
      tippOffen = null;
    });
  }
  if (!legende) {
    legende = document.createElement("details");
    legende.className = "map-legend sd-legende";
    legende.open = true;
    legendeAufbauen();
    ctx.stapel().prepend(legende);
  }
  await zeichnen();
  ctx.syncUrl();
}
const opt = (v, t, an) => `<option value="${esc(v)}"${an ? " selected" : ""}>${esc(t)}</option>`;
// Legende einmal aufbauen: Auswahlfelder bleiben stehen (Fokus und Zusammenhang für Tastatur und Screenreader), nur
// Optionen und der Teil darunter (.sd-dyn) werden neu geschrieben
function legendeAufbauen() {
  const K = A.karte;
  legende.innerHTML = `<summary>Flächenfarben: Strukturdaten</summary>
    <div class="sd-steuer">
    <label for="sd-ind">Kennzahl</label><select id="sd-ind"></select>
    <label for="sd-jahr">Jahr</label><select id="sd-jahr"></select>
    <label for="sd-ebene">Raumebene</label><select id="sd-ebene">${K.ebenen.map((e) => opt(e, EBENE[e].viele, e === lage.ebene)).join("")}</select>
    <label for="sd-klassen">Klassen</label><select id="sd-klassen">${opt("quantile", "5 Klassen nach Quantilen dieses Jahres", lage.klassen === "quantile")}${opt("fest", "feste Grenzen über alle Jahre", lage.klassen === "fest")}</select>
    </div><div class="sd-dyn"></div>`;
  const feld = (id) => legende.querySelector(`#${id}`);
  // kurz warten, damit Pfeiltasten in einer Auswahl nicht für jeden Schritt eine Datei laden
  const spaeter = () => { clearTimeout(warte); warte = setTimeout(neu, 250); };
  feld("sd-ind").addEventListener("change", (e) => { lage.ind = e.target.value; spaeter(); });
  feld("sd-jahr").addEventListener("change", (e) => { lage.jahr = e.target.value; spaeter(); });
  feld("sd-ebene").addEventListener("change", (e) => {
    lage.ebene = e.target.value;
    if (!(A.karte.dateien[lage.ebene] || []).includes(lage.ind)) lage.ind = A.karte.indikatoren.find((i) => (A.karte.dateien[lage.ebene] || []).includes(i));
    gewaehlt = null;
    spaeter();
  });
  feld("sd-klassen").addEventListener("change", (e) => { lage.klassen = e.target.value; spaeter(); });
}
// Optionen der Auswahlfelder zum aktuellen Stand; neu geschrieben nur, wenn sich die Liste ändert
function auswahlFuellen(I, jahre) {
  const K = A.karte, kern = new Map(A.kern.themen.flatMap((t) => t.indikatoren.map((id) => [id, t.thema])));
  const ind = legende.querySelector("#sd-ind"), jahr = legende.querySelector("#sd-jahr");
  if (ind.dataset.fuer !== lage.ebene) {
    const gruppen = [];
    for (const id of K.indikatoren.filter((i) => (K.dateien[lage.ebene] || []).includes(i))) {
      const g = kern.has(id) ? `Kernauswahl: ${kern.get(id)}` : `Weitere: ${(I.get(id) || {}).thema || ""}`;
      if (!gruppen.length || gruppen[gruppen.length - 1][0] !== g) gruppen.push([g, []]);
      gruppen[gruppen.length - 1][1].push(id);
    }
    ind.innerHTML = gruppen.map(([g, ids]) => `<optgroup label="${esc(g)}">${ids.map((id) => opt(id, (I.get(id) || {}).name || id)).join("")}</optgroup>`).join("");
    ind.dataset.fuer = lage.ebene;
  }
  const liste = [...jahre].reverse().join(",");
  if (jahr.dataset.fuer !== liste) {
    jahr.innerHTML = [...jahre].reverse().map((j) => opt(j, j)).join("");
    jahr.dataset.fuer = liste;
  }
  ind.value = lage.ind;
  jahr.value = lage.jahr || "";
  legende.querySelector("#sd-ebene").value = lage.ebene;
  legende.querySelector("#sd-klassen").value = lage.klassen;
}
async function zeichnen() {
  const seq = ++zeichenSeq, dyn = legende.querySelector(".sd-dyn");
  dyn.innerHTML = '<p class="hint" role="status">Wird geladen …</p>';
  let I, R, zeilen, stadt;
  try {
    [I, R, zeilen, stadt] = await Promise.all([indikatoren(), raum(lage.ebene), karte(lage.ebene, lage.ind), raumwerte("gesamtstadt", "0"), metaLaden()]);
  } catch (err) {
    if (seq === zeichenSeq && legende) legende.querySelector(".sd-dyn").innerHTML = `<p class="hint">Die Daten konnten nicht geladen werden (${esc(err.message)}).</p>`;
    return;
  }
  if (seq !== zeichenSeq || !lage.an) return;
  const ind = I.get(lage.ind);
  const jahre = [...new Set(zeilen.filter(hatWert).map((z) => z.jahr))].sort();
  jahrVorgabe = jahre[jahre.length - 1] || null;
  if (!jahre.includes(lage.jahr)) lage.jahr = jahrVorgabe;
  auswahlFuellen(I, jahre);
  const imJahr = new Map(zeilen.filter((z) => z.jahr === lage.jahr).map((z) => [z.raum_id, z]));
  const basis = (lage.klassen === "fest" ? zeilen : [...imJahr.values()]).filter(hatWert).map((z) => Number(z.wert));
  const { grenzen: g, stellen } = grenzen(basis);
  // angezeigte Stellen (Legende, Hinweis, Info, Tabelle) = Stellen, mit denen eingeordnet wird
  const st = Math.max(stellen, stellenFuer(ind.typ));
  const kl = (z) => klasse(z.wert, g, st);
  const texte = klassenText(g, st, ind.einheit);
  const farbe = (k) => FARBEN[farbIndex(k, g.length + 1)];
  const zaehl = new Array(g.length + 1).fill(0);
  let geheim = 0, fehlt = 0;
  for (const f of R.geo.features) {
    const z = imJahr.get(String(f.properties.raum_id));
    if (hatWert(z)) zaehl[kl(z)]++; else if (z && z.status === "geheim") geheim++; else fehlt++;
  }
  aktuell = { I, R, ind, imJahr, g, st, stadt: (stadt.get(lage.ind) || []).find((z) => z.jahr === lage.jahr) || null };
  const stil = (f) => {
    const z = imJahr.get(String(f.properties.raum_id)), an = String(f.properties.raum_id) === gewaehlt;
    const rand = an ? { color: "#0f0f14", weight: 3, opacity: 1 } : { color: "#ffffff", weight: lage.ebene === "quartier" ? 0.6 : 1.2, opacity: 0.9 };
    if (hatWert(z)) return { ...rand, fillColor: farbe(kl(z)), fillOpacity: 0.8 };
    if (z && z.status === "geheim") return { ...rand, fillColor: `url(#${SCHRAFFUR})`, fillOpacity: 1 };
    return { ...rand, fillColor: `url(#${PUNKTE})`, fillOpacity: 0.85 };
  };
  if (schicht) schicht.remove();
  tippOffen = null;
  // smoothFactor 0: Leaflet vereinfacht die Pfade nicht noch einmal je Fläche; sonst entfallen bei Nachbarn
  // verschiedene Punkte derselben Grenze, und zwischen den lückenlosen Quartieren erscheinen Fugen bis 1 Bildpunkt
  schicht = ctx.L.geoJSON(R.geo, {
    pane: "strukturdaten", renderer, style: stil, smoothFactor: 0,
    onEachFeature(f, layer) {
      layer.bindTooltip(() => tipp(String(f.properties.raum_id)), { sticky: true, direction: "top", className: "nav-tip sd-tipp" });
      layer.on("tooltipopen", () => { if (tippOffen && tippOffen !== layer && Date.now() < festBis) layer.closeTooltip(); });
      layer.on("click", (ev) => {
        if (tippOffen && tippOffen !== layer) tippOffen.closeTooltip();
        tippOffen = layer;
        klickAufFlaeche = true;
        waehlen(String(f.properties.raum_id));
        layer.openTooltip(ev.latlng);
      });
    },
  }).addTo(ctx.karte());
  schicht.stil = stil;
  defs();
  const verfahren = lage.klassen === "fest"
    ? `Feste Klassengrenzen: 20-, 40-, 60- und 80-%-Quantil aller Werte der Jahre ${esc(jahre[0] || "")}–${esc(jahre[jahre.length - 1] || "")} ${esc(EBENE[lage.ebene].je)}; dieselben Farben bedeuten in jedem Jahr dasselbe.`
    : `Klassengrenzen: 20-, 40-, 60- und 80-%-Quantil der Werte ${esc(lage.jahr || "")} (etwa gleich viele Flächen je Klasse).`;
  const s = quelleStat(), q = quelleQuartiere();
  const fehltText = abgeleitet(lage.ind) && A.texte.fehlt_abgeleitet ? A.texte.fehlt_abgeleitet : A.texte.fehlt;
  legende.querySelector(".sd-dyn").innerHTML = `<p class="sd-legende-titel"><strong>${esc(ind.name)}</strong>${abzeichen(lage.ind, ind)}<br>
      ${esc(EBENE[lage.ebene].je)}, ${esc(lage.jahr || "–")}${einheitText(ind.einheit) ? `; Einheit: ${esc(ind.einheit)}` : ""}</p>
    <ol class="nav-ramp sd-ramp">${texte.map((t, k) => `<li><span class="nav-sw sd-sw" style="background:${farbe(k)}" aria-hidden="true"></span>${esc(t)} <span class="sd-n">(${zaehl[k]})</span></li>`).join("")}
      <li><span class="nav-sw sd-sw sd-sw-geheim" aria-hidden="true"></span>${esc(A.texte.geheim)} <span class="sd-n">(${geheim})</span></li>
      <li><span class="nav-sw sd-sw sd-sw-fehlt" aria-hidden="true"></span>${esc(fehltText)} <span class="sd-n">(${fehlt})</span></li></ol>
    <p>In Klammern: Zahl der ${esc(EBENE[lage.ebene].der)}. ${verfahren} Grenzen und Werte gerundet wie angezeigt; ein Wert auf der Grenze gehört zur oberen Klasse.
      ${aktuell.stadt ? `Ganz Köln ${esc(lage.jahr)}: ${hatWert(aktuell.stadt) ? esc(zahl(aktuell.stadt.wert, st)) + (einheitText(ind.einheit) ? ` ${esc(ind.einheit)}` : "") : esc(statusText(aktuell.stadt))} (eigene Zeile der Stadtstatistik).` : ""}</p>
    ${abgeleitet(lage.ind) ? `<p>${esc(formelText(lage.ind))}</p>` : ""}
    <p>${esc(A.texte.einordnung)} ${esc(A.texte.fehlschluss)} ${esc(A.texte.raumebenen)}</p>
    <p>Quelle: ${link(s.datensatz_url, "Statistischer Datenkatalog Köln")} – ${esc(s.herausgeber || "")}, ${link(s.lizenz_url, esc(s.lizenz || ""))}; Datenstand ${esc(datum(M.datenstand))}. Flächen: Stadt Köln (${esc(q.lizenz || "")}).</p>
    <div class="sd-info" aria-live="polite"></div>
    <button type="button" class="btn btn-soft sd-tabelle-auf">Als Tabelle zeigen</button>`;
  legende.querySelector(".sd-tabelle-auf").addEventListener("click", tabelle);
  if (gewaehlt) info(gewaehlt);
  // offene Tabelle zum neuen Stand
  if (tabelleOffen()) tabelle(null, true);
}
async function neu() {
  if (!lage.an || !legende) return;
  await zeichnen();
  ctx.syncUrl();
}
function wertText(z) {
  const ind = aktuell.ind, ein = einheitText(ind.einheit);
  return hatWert(z) ? `${zahl(z.wert, aktuell.st)}${ein ? ` ${ein}` : ""}` : statusText(z);
}
// Status nur bei Zeilen mit Wert nennen; ohne Wert steht er schon an der Stelle des Werts
const statusZusatz = (z, trenner) => (hatWert(z) ? `${trenner}${statusText(z)}` : "");
function tipp(id) {
  if (!aktuell) return "";
  const p = aktuell.R.nachId.get(id), z = aktuell.imJahr.get(id);
  return `<strong>${esc(p ? p.name : id)}</strong> <span class="nav-dim">${esc(EBENE[lage.ebene].ein)}</span><br>
    <span class="nav-big">${esc(wertText(z))}</span><br>
    <span class="nav-dim">${esc(lage.jahr || "")}${esc(statusZusatz(z, " · "))} · Statistischer Datenkatalog Köln</span>`;
}
// Fläche auswählen (Klick oder Tabelle): Rand hervorheben, Angaben in der Legende (vorgelesen); `hinweis`: den Hinweis
// an der Fläche öffnen (Tabelle auf dem Telefon, wo die Legende im geschlossenen Blatt „Karte“ liegt)
async function waehlen(id, zoomen, hinweis) {
  gewaehlt = id;
  if (schicht) schicht.eachLayer((l) => {
    l.setStyle(schicht.stil(l.feature));
    if (String(l.feature.properties.raum_id) !== id) return;
    l.bringToFront();
    if (zoomen) { ctx.karte().invalidateSize(); ctx.karte().fitBounds(l.getBounds(), { ...ctx.padding(), maxZoom: 15 }); }
    if (hinweis) {
      schicht.eachLayer((x) => { if (x !== l && x.isTooltipOpen()) x.closeTooltip(); });
      tippOffen = l;
      festBis = Date.now() + 1000;
      l.openTooltip(l.getBounds().getCenter());
    }
  });
  await info(id);
}
async function info(id) {
  const box2 = legende && legende.querySelector(".sd-info");
  if (!box2 || !aktuell) return;
  const p = aktuell.R.nachId.get(id), z = aktuell.imJahr.get(id);
  if (!p) { box2.innerHTML = ""; return; }
  let oben = null;
  if (p.eltern_id && lage.ebene !== "stadtbezirk") {
    const r = await namen(lage.ebene === "quartier" ? "stadtteil" : "stadtbezirk");
    oben = r.nachId.get(String(p.eltern_id)) || null;
  }
  const oeffnen = lage.ebene === "quartier" ? (oben ? { art: "ortsteil", name: oben.name } : null)
    : { art: lage.ebene === "stadtteil" ? "ortsteil" : "bezirk", name: p.name };
  const ziel = oeffnen && ctx.slug(oeffnen.art, oeffnen.name);
  // Kartenvorschau ohne Ratsvorlagen: der Knopf öffnet das Gebiet mit seinen Zahlen
  const knopf = oeffnen && ctx.vorschau && ctx.vorschau() ? `Zahlen zu ${oeffnen.name} zeigen` : oeffnen ? `Vorlagen in ${oeffnen.name} zeigen` : "";
  box2.innerHTML = `<p><strong>${esc(p.name)}</strong> (${esc(EBENE[lage.ebene].ein)}${oben ? `, ${lage.ebene === "quartier" ? "Stadtteil" : "Stadtbezirk"} ${esc(oben.name)}` : ""}):
    ${esc(wertText(z))}, ${esc(lage.jahr || "")}${esc(statusZusatz(z, ", "))}${z ? `; Quellobjekt ${esc(z.quellobjekt)}` : ""}. Quelle: Statistischer Datenkatalog Köln.</p>
    ${ziel ? `<button type="button" class="btn btn-soft sd-oeffnen" data-gebiet="${esc(oeffnen.art)}:${esc(ziel)}">${esc(knopf)}</button>` : ""}`;
  const b = box2.querySelector(".sd-oeffnen");
  if (b) b.addEventListener("click", () => ctx.oeffnen(b.dataset.gebiet));
}

// gleichwertige Tabelle (WCAG 2.1 AA): alle Flächen der Raumebene mit Wert, Status und Jahr; sortierbar über die
// Spaltenköpfe (aria-sort), Vorgabe nach Name; keine Rangspalte. Wie der Vergleich der Städte in einem seitlich
// verschiebbaren Bereich (bei 320 px Breite rollt nur die Tabelle, nicht der ganze Bereich „Vorgang“)
let sortierung = { s: "name", r: "aufsteigend" };
function tabelle(ev, still) {
  if (!aktuell) return;
  const { R, ind } = aktuell;
  const zeilen = R.geo.features.map((f) => {
    const id = String(f.properties.raum_id), z = aktuell.imJahr.get(id);
    return { id, name: f.properties.name, eltern: f.properties.eltern_id, wert: hatWert(z) ? Number(z.wert) : null, z, statusText: statusText(z) };
  });
  const kopf = (s, text) => {
    const an = sortierung.s === s;
    return `<th scope="col" aria-sort="${an ? (sortierung.r === "aufsteigend" ? "ascending" : "descending") : "none"}"><button type="button" class="sd-sort" data-sort="${s}">${text}<span aria-hidden="true">${an ? (sortierung.r === "aufsteigend" ? " ▲" : " ▼") : ""}</span></button></th>`;
  };
  const telefon = ctx.telefon && ctx.telefon();
  const html = `<h3 tabindex="-1">${esc(ind.name)}</h3>
    <p class="hint">${esc(EBENE[lage.ebene].viele)}, ${esc(lage.jahr || "")}${einheitText(ind.einheit) ? `; Einheit: ${esc(ind.einheit)}` : ""}. Gleiche Angaben wie die Flächenfarben auf der Karte. Sortieren über die Spaltenköpfe; die Reihenfolge ist keine Rangfolge. ${telefon ? "Ein Tippen auf den Namen schließt die Tabelle und zeigt die Fläche mit ihrem Wert auf der Karte." : "Ein Klick auf den Namen zeigt die Fläche auf der Karte."}</p>
    <p class="hint">${esc(A.texte.einordnung)} ${esc(A.texte.fehlschluss)}</p>
    <div class="sd-scroll" tabindex="0" role="region" aria-label="Tabelle der Flächenfarben (seitlich verschiebbar)">
    <table class="kontext-table sd-tabelle" id="sd-tabelle"><caption class="visually-hidden">${esc(ind.name)}, ${esc(EBENE[lage.ebene].je)}, ${esc(lage.jahr || "")}</caption>
      <thead><tr>${kopf("name", "Gebiet")}${kopf("wert", "Wert")}${kopf("status", "Status")}<th scope="col">Jahr</th></tr></thead>
      <tbody>${sortiert(zeilen, sortierung.s, sortierung.r).map((x) => `<tr><th scope="row"><button type="button" class="link-btn" data-raum="${esc(x.id)}">${esc(x.name)}</button></th>
        <td>${hatWert(x.z) ? esc(zahl(x.z.wert, aktuell.st)) : "–"}</td><td>${esc(x.statusText)}</td><td>${esc(lage.jahr || "")}</td></tr>`).join("")}</tbody></table></div>
    <p class="hint sd-quelle">${quelleZeile()}</p>`;
  const el = ctx.detail(`Tabelle: ${EBENE[lage.ebene].viele}`, html, still);
  const t = el.querySelector("#sd-tabelle");
  t.addEventListener("click", (e) => {
    const s = e.target.closest(".sd-sort");
    if (s) {
      sortierung = { s: s.dataset.sort, r: sortierung.s === s.dataset.sort && sortierung.r === "aufsteigend" ? "absteigend" : "aufsteigend" };
      tabelle(null, true);
      const neu2 = document.querySelector(`#sd-tabelle .sd-sort[data-sort="${s.dataset.sort}"]`);
      if (neu2) neu2.focus();
      ctx.ansage(`Sortiert nach ${neu2 ? neu2.textContent.replace(/[▲▼]/g, "").trim() : ""}, ${sortierung.r}`);
      return;
    }
    const b = e.target.closest("[data-raum]");
    if (!b) return;
    // Telefon: die Tabelle verdeckt die Karte; Karte freilegen und den Hinweis an der Fläche öffnen
    if (ctx.telefon && ctx.telefon()) {
      const id = b.dataset.raum, p = aktuell.R.nachId.get(id), z = aktuell.imJahr.get(id);
      ctx.zurKarte();
      waehlen(id, true, true);
      ctx.ansage(`${p ? p.name : id}: ${wertText(z)}, ${lage.jahr || ""}${statusZusatz(z, ", ")}. Auf der Karte gezeigt.`);
      ctx.karte().getContainer().focus({ preventScroll: true });
    } else waehlen(b.dataset.raum, true);
  });
}

// --- Adresse (URL) ---------------------------------------------------------------------------------------------------
function zustand() {
  if (!A) return {};
  const K = A.karte;
  return { struktur: lage.an ? lage.ind : "", struktur_ebene: lage.an && lage.ebene !== K.vorgabe_ebene ? lage.ebene : "",
    struktur_jahr: lage.an && lage.jahr && lage.jahr !== jahrVorgabe ? lage.jahr : "", struktur_klassen: lage.an && lage.klassen === "fest" ? "fest" : "" };
}
let jahrVorgabe = null;
// Seitenstart: Panel zum Gebiet und Flächenfarben aus der Adresse (ohne Fokus zu setzen)
function start(params) {
  gebiet();
  const ind = params.get("struktur");
  if (ind && A.karte.indikatoren.includes(ind)) ebene(true, { ind, ebene: params.get("struktur_ebene"), jahr: params.get("struktur_jahr"), klassen: params.get("struktur_klassen") });
}
