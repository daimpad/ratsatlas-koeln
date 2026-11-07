// Werkzeuge des Ratsassistenten: Abfragen über die statischen Exporte der Pipeline, unabhängig vom Modell.
// Jedes Ergebnis ist kompakt (Seiten zu höchstens 10 Treffern, Titel gekürzt) und trägt Quellen-IDs:
// Drucksachennummer je Vorlage, OParl-URL (quelle_id) je Vorlage, Sitzung und Organisation.
// Tokenbudget: ein Ergebnis bleibt unter MAX_CHARS Zeichen (etwa 3.500 Tokens); längere Listen werden
// seitenweise nachgeladen (Parameter `seite`).
// Datenschutz: Ortsangaben nur auf Straßen-, Ortsteil- oder Bezirksebene (keine Hausnummern, pipeline/check.py);
// keine Namen natürlicher Personen (pipeline/actors.py). In Titeln und Fundstellen von Vorlagen aus der Einwohnerschaft
// (Bürgeranträge, Anregungen und Beschwerden, Einwohnerfragen) und aller Vorlagen desselben Vorgangs
// (bonn/chat/einwohner.json, pipeline/chat.py) werden Hausnummern ausgelassen.

import { mitwirken } from "../mitwirken.js";
export const PAGE = 10;
export const MAX_CHARS = 12000;
const TITLE_MAX = 180;
const EINWOHNER = new Set(["Bürgerantrag § 24 GO - Öffentlich", "Anregungen und Beschwerden", "Einwohnerfrage", "Bürgerbrief"]);
const EINWOHNER_TITEL = /bürgerantrag|einwohner|anregung|beschwerde/i;
// höchstens drei Ziffern: Plannummern wie „7923-2“ sind keine Hausnummern
// Buchstabenzusatz nur als einzelner Buchstabe („12a“, „12 a“), nicht der Anfang des nächsten Wortes („33 und“)
const NR = String.raw`\d{1,3}(?:\s?[a-zA-Z](?!\p{L}))?(?:\s*(?:-|–|bis|und|u\.|/|,)\s*\d{1,3}(?:\s?[a-zA-Z](?!\p{L}))?)*(?!\d)`;
const SUFFIX = String.raw`[\p{L}.-]*(?:straße|strasse|str\.|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee|hof|markt|graben|berg|feld)`;
export const OHNE_NR = "[Hausnummer ausgelassen]";
// „Hausnummer 82“, „Haus-Nr. 264“, „(neben Haus-Nr.) 68“ (wie WORT in pipeline/maske.py; ersetzt samt dem Wort,
// eine schließende Klammer bleibt stehen; 01.11.2026)
const WORT = new RegExp(String.raw`\b(?:hausnummern?|hausnr\.?|haus-nr\.?|haus\s+nr\.?)\s*(\))?\s*${NR}`, "giu");
const STAENDE = ["entschieden", "beraten, ohne Entscheidung", "in Beratung", "offen", "ohne Beratungsfolge"];
const THEMEN = ["verkehr", "bauen", "umwelt", "bildung", "kinder", "soziales", "kultur", "wirtschaft", "sicherheit", "beteiligung"];
const KENNZAHLEN = ["einwohner", "unter_18", "ab_65", "miete", "bodenrichtwert", "haltestellen", "kitas", "kita_plaetze_u3", "kita_plaetze_ue3", "hitze", "ueberschwemmung", "wahlbeteiligung"];
const GANZ_BONN = new Set(["ganz bonn", "stadt bonn", "bundesstadt bonn", "bonn gesamt", "gesamte stadt", "gesamtstadt"]);
const DATUM = { type: "string", description: "Datum als JJJJ, JJJJ-MM oder JJJJ-MM-TT" };
const SEITE = { type: "integer", minimum: 1, description: "Ergebnisseite (je 10 Treffer), Standard 1" };
const DRUCKSACHE = { type: "string", description: "Drucksachennummer, z. B. 261798 oder 261798-01" };

export const TOOLS = [
  {
    name: "suche_vorlagen",
    description: "Sucht Vorlagen (Anträge, Beschlussvorlagen, Anfragen, Bürgeranträge …) ab Oktober 2019 nach Stichwort im Titel und Filtern. Liefert eine kompakte Trefferliste, neueste zuerst. Volltexte werden nicht durchsucht.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        stichwort: { type: "string", description: "Wörter, die alle im Titel vorkommen müssen" },
        von: DATUM, bis: DATUM,
        vorlagenart: { type: "string", description: "z. B. Antrag, Beschlussvorlage, Große Anfrage, Bürgerantrag" },
        stand: { type: "string", enum: STAENDE },
        ortsteil: { type: "string", description: "Ortsteil, z. B. Endenich" },
        stadtbezirk: { type: "string", enum: ["Bonn", "Bad Godesberg", "Beuel", "Hardtberg"] },
        thema: { type: "string", enum: THEMEN, description: "abgeleitetes Thema" },
        partei: { type: "string", description: "einreichende Fraktion oder Kategorie (abgeleitet), z. B. SPD, Verwaltung, Einwohner:innen" },
        amt: { type: "string", description: "federführendes Amt, Name oder Nummer, z. B. 61 oder Stadtplanungsamt" },
        gremium: { type: "string", description: "beratendes Gremium, z. B. Bezirksvertretung Bonn" },
        seite: SEITE,
      },
    },
  },
  {
    name: "hole_vorlage",
    description: "Details einer Vorlage: Titel, Art, Datum, Stand, federführendes Amt, Einreichende, Themen, Ortsbezüge, verbundene Vorlagen, Links zum Ratsinformationssystem und Quellen-ID; soweit vorhanden eine KI-Kurzfassung (abgeleitet).",
    parameters: { type: "object", additionalProperties: false, required: ["drucksache"], properties: { drucksache: DRUCKSACHE } },
  },
  {
    name: "hole_prozesslinie",
    description: "Prozessschritte einer Vorlage in zeitlicher Folge mit Evidenzstatus (belegt, abgeleitet, nicht_öffentlich, unklar): Initiierung, Beratungen mit Gremium, Rolle und wörtlichem Ergebnis, Folgevorlagen, Vollzug.",
    parameters: { type: "object", additionalProperties: false, required: ["drucksache"], properties: { drucksache: DRUCKSACHE } },
  },
  {
    name: "suche_ort",
    description: "Vorlagen mit Ortsbezug zu einem Ortsteil, Stadtbezirk, einer Straße oder einem Bebauungsplan, oder im Umkreis eines Punktes. Liefert je Vorlage Methode und Konfidenz der Verortung.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        ort: { type: "string", description: "Name eines Ortsteils, Stadtbezirks, einer Straße oder Bebauungsplan-Nummer" },
        lat: { type: "number" }, lon: { type: "number" },
        radius_m: { type: "integer", minimum: 50, maximum: 2000, description: "Umkreis in Metern (Standard 300)" },
        von: DATUM, bis: DATUM, seite: SEITE,
      },
    },
  },
  {
    name: "liste_sitzungen",
    description: "Sitzungen von Rat, Ausschüssen, Bezirksvertretungen und Beiräten mit Datum, Uhrzeit und Links zu Tagesordnung und Einladung. Ohne Zeitangaben: kommende Sitzungen.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        gremium: { type: "string", description: "Name oder Namensteil des Gremiums" },
        von: DATUM, bis: DATUM,
        zeitraum: { type: "string", enum: ["kommende", "vergangene", "alle"] },
        seite: SEITE,
      },
    },
  },
  {
    name: "hole_gremium_oder_amt",
    description: "Angaben zu einem Gremium (Beratungen, Sitzungen, nächste Sitzung; bei laufenden Gremien die Besetzung: Mitglieder, Vorsitz, Sitze nach Fraktion, abgeleitet) oder einem Amt bzw. Verwaltungsbereich (federführende Vorlagen). Zuständigkeiten nach Regelwerk sind nicht formalisiert.",
    parameters: { type: "object", additionalProperties: false, required: ["name"], properties: { name: { type: "string", description: "Name, Kurzname oder Amtsnummer" } } },
  },
  {
    name: "erklaere_begriff",
    description: "Glossar: Ergebnistexte (z. B. „zur Kenntnis genommen“), Rollen, Evidenzstatus, Stände und Begriffe wie Bürgerantrag, Bezirksvertretung, Dringlichkeitsentscheidung, jeweils mit Fundstelle.",
    parameters: { type: "object", additionalProperties: false, required: ["begriff"], properties: { begriff: { type: "string" } } },
  },
  {
    name: "suche_bebauungsplan",
    description: "Bebauungspläne, deren Nummer im Titel von Vorlagen steht: mit Nummer die Planchronik (Inkrafttreten mit Plan und Begründung laut Stadt Bonn, Verfahrensschritte nach BauGB als Soll mit Fundstelle, zugeordnete Vorlagen), sonst eine Liste nach Ortsteil oder Stichwort.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        nummer: { type: "string", description: "Plannummer, z. B. 6122-1" },
        ortsteil: { type: "string", description: "Ortsteil, z. B. Dransdorf" },
        stichwort: { type: "string", description: "Wörter im Titel einer zugeordneten Vorlage" },
        seite: SEITE,
      },
    },
  },
  {
    name: "suche_baustellen",
    description: "Gemeldete Baustellen der Stadt Bonn (Straße, Maßnahme, Träger, Zeitraum unverbindlich) und mögliche Umsetzungen von Beschlüssen (Indiz aus Ort, Zeit und Thema, kein Beleg). Suche nach Straße, Stadtbezirk, Drucksache oder Umkreis eines Punktes.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        ort: { type: "string", description: "Straße oder Bezeichnung der Baustelle" },
        stadtbezirk: { type: "string", enum: ["Bonn", "Bad Godesberg", "Beuel", "Hardtberg"] },
        drucksache: { type: "string", description: "Baustellen, die als mögliche Umsetzung dieser Vorlage gelten" },
        lat: { type: "number" }, lon: { type: "number" },
        radius_m: { type: "integer", minimum: 50, maximum: 2000, description: "Umkreis in Metern (Standard 300)" },
        auch_beendete: { type: "boolean", description: "auch Baustellen, die nicht mehr gemeldet sind (Archiv)" },
        seite: SEITE,
      },
    },
  },
  {
    name: "hole_kontext",
    description: "Zahlen zu einem Ortsteil, Stadtbezirk oder ganz Bonn zur Einordnung: Einwohner, Altersanteile, Nettokaltmiete (Zensus 2022), Bodenrichtwert Wohnbauland, Haltestellen, Kitas, Hitzebelastung, Überschwemmungsgebiet, Wahlbeteiligung der Ratswahl 2025 (geschätzt); je Wert Quelle, Lizenz, Stand und Methode, dazu der Vergleichswert des Stadtbezirks bzw. von ganz Bonn. Alle Werte abgeleitet (auf Gebiete umgerechnet); kein Beleg für eine Vorlage.",
    parameters: {
      type: "object", additionalProperties: false, required: ["gebiet"],
      properties: {
        gebiet: { type: "string", description: "Ortsteil (z. B. Endenich), Stadtbezirk (Bonn, Bad Godesberg, Beuel, Hardtberg) oder „ganz Bonn“" },
        kennzahlen: { type: "array", items: { type: "string", enum: KENNZAHLEN }, description: "nur diese Kennzahlen; Standard alle" },
      },
    },
  },
  {
    name: "datenstand",
    description: "Datenstand: Abrufzeitpunkte und Lizenzen der Quellen, Umfang, Anteil verorteter Vorlagen, bekannte Lücken.",
    parameters: { type: "object", additionalProperties: false, properties: {} },
  },
];

// --- Hilfen ----------------------------------------------------------------------------------------------
export const norm = (s) => String(s ?? "").toLowerCase().normalize("NFC")
  .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
  .replace(/[^\p{L}\p{N}§]+/gu, " ").trim();
const words = (s) => norm(s).split(" ").filter(Boolean);
const short = (t) => (t && t.length > TITLE_MAX ? t.slice(0, TITLE_MAX - 1) + "…" : t);
const BERLIN = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" });
const berlinToday = () => BERLIN.format(new Date());

export function dateBound(v, end) {
  if (v == null || v === "") return null;
  const m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec(String(v).trim());
  if (!m) throw new ToolError(`Ungültiges Datum „${v}“; erwartet JJJJ, JJJJ-MM oder JJJJ-MM-TT.`);
  const [, y, mo, d] = m;
  if (d) return `${y}-${mo}-${d}`;
  if (mo) return end ? `${y}-${mo}-31` : `${y}-${mo}-01`;
  return end ? `${y}-12-31` : `${y}-01-01`;
}

export class ToolError extends Error {
  constructor(message, extra = {}) { super(message); this.extra = extra; }
}

function page(items, seite, size = PAGE) {
  const n = Math.max(1, Math.floor(Number(seite) || 1));
  const pages = Math.max(1, Math.ceil(items.length / size));
  return { treffer_gesamt: items.length, seite: n, seiten: pages, items: items.slice((n - 1) * size, n * size) };
}

// Füllwörter und der Zusatz „der Stadt Bonn“ tragen nichts zur Unterscheidung bei; sonst trifft „Rat der Stadt Bonn“
// als Teilwort „Projektbeirat Behindertenpolitischer … Bundesstadt Bonn“ (Auswertung mit Mistral, 22.10.2026)
const FUELLWOERTER = new Set(["der", "die", "das", "des", "den", "dem", "fuer", "und", "von", "im", "in"]);
const ohneZusatz = (s) => norm(s).replace(/^stadtrat$/, "rat").replace(/ (der )?(bundes)?stadt bonn$/, "").trim();
const anfang = (name, w) => (" " + norm(name)).includes(" " + w);

// Suche in einer Liste von Namen: exakter Treffer vor Wortanfang vor Teilwort; mehrere Treffer je Stufe sind erlaubt
function resolve(list, query, what) {
  const q = norm(query), kurz = ohneZusatz(query);
  const exact = list.filter((x) => norm(x) === q || norm(x) === kurz);
  if (exact.length) return exact;
  const ws = words(kurz).filter((w) => !FUELLWOERTER.has(w));
  const ww = ws.length ? ws : words(query);
  const start = list.filter((x) => ww.every((w) => anfang(x, w)));
  if (start.length) return start;
  const part = list.filter((x) => ww.every((w) => norm(x).includes(w)));
  if (part.length) return part;
  throw new ToolError(`Kein(e) ${what} „${query}“ gefunden.`, { moegliche_werte: list.slice(0, 40) });
}

// --- Werkzeuge ---------------------------------------------------------------------------------------------
export function createTools({ load, today: fest = null } = {}) {
  // heute je Aufruf neu (ein über Mitternacht offenes Fenster ordnete Sitzungen sonst falsch ein); fest nur für Tests
  const today = () => fest ?? berlinToday();
  const cache = new Map();
  const get = (path) => {
    if (!cache.has(path)) cache.set(path, Promise.resolve(load(path)).catch((e) => { cache.delete(path); throw e; }));
    return cache.get(path);
  };
  const search = () => get("bonn/suche.json");
  const places = () => get("bonn/chat/orte.json");
  const status = () => get("bonn/chat/datenstand.json");
  const glossar = () => get("glossar.json");
  const plaene = () => get("bonn/plaene.json");
  const baustellen = () => get("bonn/baustellen.json");
  const sollModell = () => get("bonn/soll.json");
  const kontextDaten = () => get("bonn/kontext.json");

  // Soll nach Regelwerk (bonn/soll.json): Verfahren, Schritte mit Rechtsgrundlage, Abgleich der Gremienarten
  async function sollAngaben(p, used) {
    const s = p.soll;
    if (!s) return {};
    let d = null;
    try { d = await sollModell(); } catch (e) { d = null; }
    const v = d && s.verfahren ? d.verfahren[s.verfahren] : null;
    const name = (b) => d?.bahnen[b] ?? b;
    const o = { verfahren: v ? v.titel : null, zuordnung: s.grund, zuordnung_status: "abgeleitet", sicherheit: s.sicherheit, abgleich: s.passung };
    if (s.passung === "weicht ab") o.befund = `Beraten hat auch ${s.abweichung.map(name).join(", ")}; das Regelwerk sieht das für dieses Verfahren nicht vor. Befund, keine Bewertung.`;
    if (v) {
      const ist = new Set(s.ist);
      o.schritte = v.schritte.map((st) => {
        const gremium = ["bv", "aus", "rat"].includes(st.bahn);
        const status = gremium && ist.has(st.bahn) ? "belegt" : "soll";
        used.add(status);
        const x = { schritt: st.label, status, abgleich: status === "belegt" ? "Gremienart hat beraten" : gremium ? "keine Beratung dieser Gremienart" : "nicht abgeglichen" };
        if (st.bahn) x.wer = name(st.bahn);
        if (st.beleg) x.rechtsgrundlage = st.beleg;
        if (st.links?.length) x.links = st.links.map((l) => l.url).filter((u, i, a) => a.indexOf(u) === i);
        if (st.eigen) x.ergaenzung_ris_karte = true;
        return x;
      });
    } else if (!s.verfahren) o.hinweis = d?.ohne_soll[p.paper_type] ?? "Kein Soll angenommen.";
    if (d?.mitwirken) {
      let z = null;
      try { z = await get("bonn/zeit.json"); } catch (e) { z = null; }
      const m = mitwirken(p, d, z ? z.meetings : [], today());
      if (m.regeln.length) {
        o.mitwirken = m.regeln.map((r) => ({ hinweis: r.text, frist: r.frist, ...(r.verstrichen ? { frist_verstrichen: true } : {}),
          rechtsgrundlage: r.beleg, ...(r.sitzung?.web ? { tagesordnung: r.sitzung.web } : {}) }));
        o.mitwirken_einordnung = { status: m.kontext.status, abschluss: m.kontext.abschluss, ebene: m.kontext.ebene,
          naechster_termin: m.kontext.termin, herkunft: "abgeleitet aus Stand, Beratungen und Sitzungskalender" };
      }
    }
    if (d) o.quelle = `${d.meta.quelle}. ${d.meta.hinweis}`;
    return { soll_nach_regelwerk: o };
  }

  async function paper(ref) {
    const r = String(ref ?? "").trim();
    if (!/^\d{4}/.test(r)) throw new ToolError(`„${ref}“ ist keine Drucksachennummer (z. B. 261798).`);
    let shard;
    try { shard = await get(`bonn/chat/vorlagen/${r.slice(0, 4)}.json`); } catch (e) { shard = null; }
    const papers = shard?.papers || {};
    const hit = papers[r] || Object.values(papers).find((p) => norm(p.reference) === norm(r));
    if (!hit) throw new ToolError(`Drucksache ${r} ist in den Daten nicht enthalten.`);
    return hit;
  }

  // Hausnummern hinter bekannten Straßennamen oder Straßen-Endungen ausblenden (nur Vorlagen aus der Einwohnerschaft
  // und ihre Vorgänge; mask(text, Art, Drucksache))
  async function masker() {
    const d = await places();
    if (!d._mask) {
      let ew = new Set();
      try { ew = new Set((await get("bonn/chat/einwohner.json")).drucksachen); } catch (e) { /* ältere Exporte ohne Datei */ }
      const esc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const names = [...new Set(d.places.filter((p) => p.level === "strasse").map((p) => p.name))].sort((a, b) => b.length - a.length).map(esc);
      const rx = new RegExp(String.raw`((?:${[...names, SUFFIX].join("|")})\s+)(?:nr\.?\s*)?${NR}`, "giu");
      d._mask = (title, type, ref) => (title && (EINWOHNER.has(type) || EINWOHNER_TITEL.test(title) || ew.has(ref)) ? title.replace(rx, `$1${OHNE_NR}`).replace(WORT, (m, klammer) => OHNE_NR + (klammer || "")) : title);
    }
    return d._mask;
  }

  async function rowsByRef() {
    const s = await search();
    return (s._byRef ||= new Map(s.rows.map((r) => [r[0], r])));
  }
  const item = (s, r, mask) => ({ drucksache: r[0], titel: short(mask(r[1], s.types[r[3]], r[0])), datum: r[2], art: s.types[r[3]] ?? null, stand: s.stands[r[4]] });

  async function retrieved() {
    const d = await status();
    return d.sources.find((x) => x.name === "oparl-bonn")?.retrieved_at ?? null;
  }

  // Vorlagen je Ortsteil bzw. Stadtbezirk aus den Ortsbezügen
  async function refsWhere(pred) {
    const set = new Set();
    for (const pl of (await places()).places) if (pred(pl)) for (const x of pl.papers) set.add(x[0]);
    return set;
  }
  async function ortsteile() {
    const d = await places();
    return (d._ortsteile ||= [...new Set(d.places.map((p) => p.ortsteil).filter(Boolean))].sort());
  }

  const impl = {
    async suche_vorlagen(a) {
      const s = await search();
      const filter = {};
      const von = dateBound(a.von, false), bis = dateBound(a.bis, true);
      const terms = words(a.stichwort);
      let types = null, aemter = null, gremien = null, refs = null;
      if (a.vorlagenart) { types = new Set(resolve(s.types, a.vorlagenart, "Vorlagenart").map((t) => s.types.indexOf(t))); filter.vorlagenart = [...types].map((i) => s.types[i]); }
      if (a.amt) {
        const num = /^\d{2}$/.test(String(a.amt).trim()) ? String(a.amt).trim() : null;
        const hits = num ? s.aemter.filter((x) => x.startsWith(num + " ") || x.startsWith(num + "-")) : resolve(s.aemter, a.amt, "Amt");
        if (!hits.length) throw new ToolError(`Kein Amt mit Nummer ${num} gefunden.`, { moegliche_werte: s.aemter });
        aemter = new Set(hits.map((x) => s.aemter.indexOf(x))); filter.amt = hits;
      }
      if (a.gremium) { const hits = resolve(s.gremien, a.gremium, "Gremium"); gremien = new Set(hits.map((x) => s.gremien.indexOf(x))); filter.gremium = hits; }
      const stand = a.stand ? s.stands.indexOf(a.stand) : -1;
      if (a.stand && stand < 0) throw new ToolError(`Unbekannter Stand „${a.stand}“.`, { moegliche_werte: s.stands });
      const theme = a.thema ? s.themes.findIndex((t) => t.id === a.thema || norm(t.label).includes(norm(a.thema))) : -1;
      if (a.thema && theme < 0) throw new ToolError(`Unbekanntes Thema „${a.thema}“.`, { moegliche_werte: s.themes.map((t) => t.id) });
      if (theme >= 0) filter.thema = s.themes[theme].label;
      const party = a.partei ? s.parties.findIndex((p) => norm(p) === norm(a.partei)) : -1;
      if (a.partei && party < 0) throw new ToolError(`Keine Partei bzw. Kategorie „${a.partei}“.`, { moegliche_werte: s.parties });
      if (party >= 0) filter.partei = s.parties[party];
      if (a.ortsteil) {
        const names = resolve(await ortsteile(), a.ortsteil, "Ortsteil");
        refs = await refsWhere((pl) => names.includes(pl.ortsteil)); filter.ortsteil = names;
      }
      if (a.stadtbezirk) {
        const b = norm(a.stadtbezirk);
        const bz = await refsWhere((pl) => norm(pl.stadtbezirk) === b);
        refs = refs ? new Set([...refs].filter((x) => bz.has(x))) : bz; filter.stadtbezirk = a.stadtbezirk;
      }
      const titles = (s._titles ||= s.rows.map((r) => norm(r[1])));
      const rows = s.rows.filter((r, i) => (!terms.length || terms.every((w) => titles[i].includes(w))) &&
        (!von || (r[2] && r[2] >= von)) && (!bis || (r[2] && r[2] <= bis)) && (!types || types.has(r[3])) &&
        (stand < 0 || r[4] === stand) && (theme < 0 || r[6].includes(theme)) && (party < 0 || r[7].includes(party)) &&
        (!aemter || aemter.has(r[9])) && (!gremien || (r[10] || []).some((g) => gremien.has(g))) && (!refs || refs.has(r[0])));
      const p = page(rows, a.seite);
      const mask = await masker();
      const hinweise = [];
      if (theme >= 0 || party >= 0) hinweise.push("Themen und Parteien sind abgeleitet (Amt, Gremium, Stichwort bzw. Titel).");
      if (refs) hinweise.push("Ortsbezüge sind teils abgeleitet (Stufe B); Methode und Konfidenz liefert suche_ort oder hole_vorlage.");
      if (terms.length) hinweise.push("Gesucht wurde nur in Titeln, nicht in Dokumenttexten.");
      return { anfrage: { stichwort: a.stichwort || null, von, bis, ...filter }, treffer_gesamt: p.treffer_gesamt, seite: p.seite, seiten: p.seiten,
        treffer: p.items.map((r) => item(s, r, mask)), hinweise, quelle: "OParl-API Stadt Bonn (CC0), Suchindex des Ratsatlas" };
    },

    async hole_vorlage(a) {
      const p = await paper(a.drucksache);
      const g = await glossar();
      const mask = await masker();
      const rel = relOf(mask);
      const label = g.themen || {};
      return {
        drucksache: p.reference, titel: mask(p.name, p.paper_type, p.reference), art: p.paper_type, datum: p.date,
        stand: p.stand, stand_erklaerung: g.staende[p.stand] ?? null,
        federfuehrendes_amt: p.amt,
        zustaendigkeit: p.responsibility.map((r) => ({ amt: r.label, bereich: r.name, art: r.kind, status: r.derived ? "abgeleitet" : "belegt" })),
        einreichende: p.originators.map((o) => ({ name: o.actor, typ: o.actor_type, status: o.derived ? "abgeleitet" : "belegt", fundstelle: mask(o.evidence, p.paper_type, p.reference) })),
        themen: p.themes.map((t) => ({ thema: label[t.theme] ?? t.theme, status: "abgeleitet", methode: t.method, fundstelle: t.evidence, konfidenz: t.confidence })),
        parteien: p.parties,
        kurzfassung: p.kurzfassung ? { text: p.kurzfassung.text, status: "abgeleitet", modell: p.kurzfassung.modell,
          hinweis: "Mit einem Sprachmodell aus dem Text des Dokuments formuliert, kein Zitat. Einzelheiten können ungenau sein, etwa ob etwas beschlossen oder nur vorgeschlagen ist. Maßgeblich ist das Original." } : null,
        orte: p.locations.slice(0, 10).map(locOf(mask, p)),
        orte_gesamt: p.locations.length,
        bebauungsplaene: p.plans.map((x) => ({ nummer: x.nr, fundstelle: mask(x.evidence, p.paper_type, p.reference), geltungsbereich_bekannt: x.area, treffer: x.match || null })),
        uebergeordnet: p.superordinated.slice(0, 5).map(rel),
        folgevorlagen: p.subordinated.slice(0, 10).map(rel),
        folgevorlagen_gesamt: p.subordinated.length,
        links: { ratsinformationssystem: p.web, dokument: p.main_file },
        quelle_id: p.source_object, quelle: "OParl-API Stadt Bonn (CC0); Ergebnisse von Beratungen: OParl-Lite (CC BY 4.0)",
        abgerufen: await retrieved(),
      };
    },

    async hole_prozesslinie(a) {
      const p = await paper(a.drucksache);
      const g = await glossar();
      const mask = await masker();
      const folge = p.steps.filter((x) => x.typ === "folgevorlage");
      const steps = [...p.steps.filter((x) => x.typ !== "folgevorlage" && x.typ !== "vollzug"), ...folge.slice(0, 15), ...p.steps.filter((x) => x.typ === "vollzug")];
      const used = new Set();
      const out = steps.map((x, i) => {
        used.add(x.status);
        const o = { nr: i + 1, schritt: g.schritte[x.typ] ?? x.typ, bezeichnung: x.label, status: x.status };
        if (x.date) { o.datum = x.date; o.zeitbezug = x.date < today() ? "vergangen" : x.date === today() ? "heute" : "künftig"; }
        if (x.date_status) o.datum_status = x.date_status;
        if (x.role) o.rolle = x.role;
        if (x.result) { o.ergebnis = x.result; o.ergebnis_quelle = x.result_source; }
        if (x.number) o.top = x.number;
        if (x.stand && (x.typ === "beratung" || x.typ === "entscheidung")) o.beratungsstatus = x.stand;
        if (x.actors?.length) { o.einreichende = x.actors; o.einreichende_status = x.actors_status; }
        if (x.reference) { o.drucksache = x.reference; o.titel = short(mask(x.title, x.label, x.reference)); }
        if (x.note) o.hinweis = g.hinweise[x.note] ?? x.note;
        return o;
      });
      return {
        drucksache: p.reference, titel: short(mask(p.name, p.paper_type, p.reference)), stand: p.stand, stand_erklaerung: g.staende[p.stand] ?? null,
        heute: today(), schritte: out, folgevorlagen_gesamt: folge.length,
        ...(await sollAngaben(p, used)),
        evidenzstatus: Object.fromEntries([...used].map((k) => [k, g.evidenz[k]])),
        quelle_id: p.source_object, quelle: "Beratungsfolge: OParl-API Stadt Bonn (CC0); Sitzungsdatum und Ergebnis: OParl-Lite (CC BY 4.0)",
      };
    },

    async suche_ort(a) {
      const d = await places();
      let hit;
      if (a.ort) {
        const q = norm(a.ort);
        const ot = d.places.filter((p) => norm(p.ortsteil) === q);
        const bz = ot.length ? [] : d.places.filter((p) => norm(p.stadtbezirk) === q);
        hit = ot.length ? ot : bz.length ? bz : d.places.filter((p) => norm(p.name) === q);
        if (!hit.length) hit = d.places.filter((p) => words(a.ort).every((w) => norm(p.name).includes(w)));
        if (!hit.length) throw new ToolError(`Kein Ortsbezug zu „${a.ort}“ in den Daten. Straßen, Ortsteile und Bebauungspläne werden nur erkannt, wenn sie im Titel einer Vorlage stehen.`);
      } else if (a.lat != null && a.lon != null) {
        const r = Math.min(2000, Math.max(50, Number(a.radius_m) || 300));
        hit = d.places.filter((p) => p.lat != null && p.level !== "ortsteil" && p.level !== "stadtbezirk" && dist(a.lat, a.lon, p.lat, p.lon) <= r);
      } else throw new ToolError("Bitte `ort` oder `lat` und `lon` angeben.");
      const von = dateBound(a.von, false), bis = dateBound(a.bis, true);
      const by = new Map();
      for (const pl of hit) for (const [ref, stufe, methode, konfidenz] of pl.papers) {
        if (!by.has(ref)) by.set(ref, []);
        by.get(ref).push({ ort: pl.name, ebene: pl.level, ortsteil: pl.ortsteil, stufe, methode, konfidenz });
      }
      const s = await search();
      const rows = await rowsByRef();
      const mask = await masker();
      const list = [...by.keys()].map((ref) => rows.get(ref)).filter((r) => r && (!von || (r[2] && r[2] >= von)) && (!bis || (r[2] && r[2] <= bis)))
        .sort((x, y) => (y[2] || "").localeCompare(x[2] || "") || y[0].localeCompare(x[0]));
      const p = page(list, a.seite);
      return {
        orte: [...new Map(hit.map((x) => [`${x.level}|${x.name}|${x.ortsteil}`, { name: x.name, ebene: x.level, ortsteil: x.ortsteil, stadtbezirk: x.stadtbezirk }])).values()].slice(0, 10),
        orte_gesamt: hit.length,
        treffer_gesamt: p.treffer_gesamt, seite: p.seite, seiten: p.seiten,
        treffer: p.items.map((r) => ({ ...item(s, r, mask), verortung: by.get(r[0]).slice(0, 3) })),
        hinweise: ["Stufe A: Ort von der Stadt angegeben (hoch). Stufe B: aus dem Titel abgeleitet (mittel oder niedrig).",
          "Orte nur auf Straßen-, Ortsteil- oder Bezirksebene."],
        quelle: "Ortsbezüge des Ratsatlas (Stufe A: OParl-API Stadt Bonn, CC0; Stufe B: abgeleitet, Straßen aus OpenStreetMap, ODbL)",
      };
    },

    async liste_sitzungen(a) {
      const z = await get("bonn/zeit.json");
      const von = dateBound(a.von, false), bis = dateBound(a.bis, true);
      const zeitraum = a.zeitraum || (von || bis ? "alle" : "kommende");
      let names = null;
      if (a.gremium) names = new Set(resolve([...new Set(z.meetings.map((m) => m.gremium))].sort(), a.gremium, "Gremium"));
      let list = z.meetings.filter((m) => (!names || names.has(m.gremium)) && (!von || m.date >= von) && (!bis || m.date <= bis) &&
        (zeitraum === "alle" || (zeitraum === "kommende" ? m.date >= today() : m.date < today())));
      list = zeitraum === "kommende" ? list : [...list].reverse();
      const p = page(list, a.seite);
      return {
        anfrage: { gremium: names ? [...names] : null, von, bis, zeitraum, heute: today() },
        treffer_gesamt: p.treffer_gesamt, seite: p.seite, seiten: p.seiten,
        sitzungen: p.items.map((m) => ({ datum: m.date, uhrzeit: m.time, gremium: m.gremium, name: m.name, abgesagt: m.cancelled,
          status: m.state, tagesordnung: m.web, einladung: m.invitation, tagesordnungspunkte: m.agenda_items || null, quelle_id: m.source_object })),
        hinweise: ["Tagesordnung und Einladung erscheinen etwa zwei Wochen vor der Sitzung; künftige Termine können sich ändern."],
        quelle: "OParl-API Stadt Bonn (CC0)",
      };
    },

    async hole_gremium_oder_amt(a) {
      const orgs = (await get("bonn/chat/gremien.json")).organizations;
      const q = String(a.name ?? "").trim();
      const num = /^\d{2}$/.test(q) ? q : null;
      const key = (o) => [o.name, o.short_name, o.amt].filter(Boolean);
      let hits = num ? orgs.filter((o) => o.type === "Verwaltungsbereich" && (o.amt || "").startsWith(num))
        : orgs.filter((o) => key(o).some((k) => norm(k) === norm(q)));
      if (!hits.length) hits = orgs.filter((o) => key(o).some((k) => words(q).every((w) => norm(k).includes(w))));
      if (!hits.length) throw new ToolError(`Kein Gremium und kein Amt „${q}“ gefunden.`);
      // aktive und häufig befasste zuerst
      const weight = (o) => (o.end_date ? 0 : 1e6) + (num && o.name === o.amt ? 1e7 : 0) + (o.consultations ?? o.papers_led ?? 0);
      hits.sort((x, y) => weight(y) - weight(x));
      const label = (await glossar()).themen || {};
      const z = await get("bonn/zeit.json");
      const detail = (o) => {
        const d = { name: o.name, typ: o.type, kategorie: o.classification, aufgeloest: o.end_date || null,
          thema: o.theme ? { thema: label[o.theme], status: "abgeleitet" } : null, web: o.web, quelle_id: o.source_object };
        if (o.type === "Gremium") {
          const ms = z.meetings.filter((m) => m.gremium === o.name && !m.cancelled);
          Object.assign(d, { beratungen: o.consultations, davon_entscheidend: o.deciding, sitzungen: o.meetings,
            letzte_sitzung: ms.filter((m) => m.date < today()).at(-1)?.date ?? null,
            naechste_sitzung: ms.find((m) => m.date >= today())?.date ?? null });
          if (o.besetzung) d.besetzung = { ...o.besetzung, status: "Fraktion abgeleitet",
            hinweis: "Fraktion aus der Mitgliedschaft in einer Fraktion des Rates bzw. der Bezirksfraktion; die Quelle nennt nicht, für wen jemand im Gremium sitzt. Sachkundige Bürger:innen gehören meist keiner Fraktion an. Alle Mitglieder mit Namen im Reiter „Prozesse“." };
        } else {
          Object.assign(d, { amt: o.amt, federfuehrende_vorlagen: o.papers_led });
          if (o.name === o.amt) d.federfuehrende_vorlagen_amt_gesamt = orgs.filter((x) => x.amt === o.amt).reduce((n, x) => n + x.papers_led, 0);
        }
        return d;
      };
      return {
        treffer: detail(hits[0]),
        weitere: hits.slice(1, 8).map((o) => ({ name: o.name, typ: o.type, aufgeloest: o.end_date || null })),
        weitere_gesamt: Math.max(0, hits.length - 1),
        hinweise: ["Zuständigkeiten nach Zuständigkeitsordnung und Bezirkssatzung sind nicht formalisiert; Zählungen beruhen auf den Vorlagen ab Oktober 2019."],
        quelle: "OParl-API Stadt Bonn (CC0)",
      };
    },

    async erklaere_begriff(a) {
      const g = await glossar();
      const entries = [
        ...g.begriffe.map((b) => ({ begriff: b.begriff, erklaerung: b.erklaerung, fundstelle: b.fundstelle })),
        ...Object.entries(g.ergebnisse).map(([k, v]) => ({ begriff: k, erklaerung: v, fundstelle: "Ergebnis bzw. Rolle einer Beratung, wörtlich aus der Quelle" })),
        ...Object.entries(g.staende).map(([k, v]) => ({ begriff: `Stand: ${k}`, erklaerung: v, fundstelle: "Prozessebene des Ratsatlas" })),
        ...Object.entries(g.evidenz).map(([k, v]) => ({ begriff: `Evidenzstatus: ${k}`, erklaerung: v, fundstelle: "Prozessebene des Ratsatlas" })),
      ];
      const q = norm(a.begriff);
      let hits = entries.filter((e) => norm(e.begriff) === q || norm(e.begriff).replace(/^(stand|evidenzstatus) /, "") === q);
      if (!hits.length) hits = [...entries.filter((e) => norm(e.begriff).includes(q)), ...entries.filter((e) => q.length > 3 && !norm(e.begriff).includes(q) && q.includes(norm(e.begriff)))];
      if (!hits.length) hits = entries.filter((e) => words(a.begriff).every((w) => norm(e.begriff + " " + e.erklaerung).includes(w)));
      return hits.length
        ? { gefunden: true, eintraege: hits.slice(0, 5) }
        : { gefunden: false, hinweis: "Nicht im Glossar. Eine allgemeine Erklärung ist als solche zu kennzeichnen.", begriffe: g.begriffe.map((b) => b.begriff) };
    },

    async suche_bebauungsplan(a) {
      const d = await plaene();
      const mask = await masker();
      const vorlage = (v) => ({ drucksache: v.drucksache, datum: v.datum, art: v.art, titel: short(mask(v.titel, v.art, v.drucksache)), stand: v.stand });
      const hinweise = ["Erfasst sind Pläne, deren Nummer im Titel einer Vorlage ab Oktober 2019 steht.",
        "Verfahrensschritte: Soll nach BauGB; eine Vorlage ist einem Schritt zugeordnet, wenn ihr Titel ihn nennt (abgeleitet). „soll“ heißt: keine Vorlage nennt den Schritt – nicht, dass er fehlt. Vereinfachte Verfahren (§§ 13, 13a BauGB) haben weniger Schritte."];
      if (a.nummer) {
        const q = norm(a.nummer);
        const e = d.plaene.find((x) => norm(x.nr) === q) || d.plaene.find((x) => x.plaene.some((v) => norm(v.name) === q));
        if (!e) throw new ToolError(`Kein Bebauungsplan „${a.nummer}“ in den Titeln der Vorlagen.`, { hinweis: hinweise[0] });
        return {
          nummer: e.nr, zuordnung: e.treffer, ortsteile: e.ortsteile,
          plaene: e.plaene.map((v) => ({ plan: v.name, rechtskraeftig_seit: v.inkraft_seit, plan_pdf: v.plan, begruendung_pdf: v.begruendung, evidenz: "belegt (Stadt Bonn)" })),
          verfahrensschritte: [...d.schritte.map((st) => {
            const hits = e.vorlagen.filter((v) => (v.schritte || []).includes(st.id));
            return { schritt: st.label, fundstelle: st.fundstelle, status: hits.length ? "abgeleitet" : "soll", vorlagen: hits.map((v) => ({ drucksache: v.drucksache, datum: v.datum })) };
          }), { schritt: "Inkrafttreten (Bekanntmachung)", fundstelle: "§ 10 Abs. 3 BauGB",
            status: e.plaene.some((v) => v.inkraft_seit) ? "belegt" : "soll", datum: e.plaene.map((v) => v.inkraft_seit).filter(Boolean).sort().pop() || null }],
          vorlagen: page(e.vorlagen.map(vorlage), a.seite),
          hinweise, quelle: "Stadt Bonn, Lage der Bebauungspläne (CC0); Vorlagen: OParl-API Stadt Bonn (CC0)",
        };
      }
      let list = d.plaene;
      if (a.ortsteil) { const o = resolve([...new Set(d.plaene.flatMap((e) => e.ortsteile))].sort(), a.ortsteil, "Ortsteil"); list = list.filter((e) => e.ortsteile.some((x) => o.includes(x))); }
      if (a.stichwort) { const w = words(a.stichwort); list = list.filter((e) => e.vorlagen.some((v) => w.every((x) => norm(v.titel).includes(x)))); }
      const items = list.map((e) => ({ nummer: e.nr, zuordnung: e.treffer, ortsteile: e.ortsteile, rechtskraeftig_seit: e.plaene.map((v) => v.inkraft_seit).filter(Boolean).sort().pop() || null,
        vorlagen: e.vorlagen.length, letzte_vorlage: vorlage(e.vorlagen[e.vorlagen.length - 1]) }));
      return { ...page(items, a.seite), hinweise, quelle: "Stadt Bonn, Lage der Bebauungspläne (CC0); Vorlagen: OParl-API Stadt Bonn (CC0)" };
    },

    async suche_baustellen(a) {
      const d = await baustellen();
      const mask = await masker();
      let list = d.baustellen.filter((b) => a.auch_beendete || b.aktiv);
      if (a.ort) { const w = words(a.ort); list = list.filter((b) => w.every((x) => norm(`${b.bezeichnung} ${b.strasse || ""}`).includes(x))); }
      if (a.stadtbezirk) list = list.filter((b) => b.stadtbezirk === a.stadtbezirk);
      if (a.drucksache) list = list.filter((b) => b.kandidaten.some((c) => norm(c.drucksache) === norm(a.drucksache)));
      const near = a.lat != null && a.lon != null;
      if (near) {
        const rad = a.radius_m || 300;
        list = list.map((b) => ({ ...b, _d: dist(a.lat, a.lon, b.lat, b.lon) })).filter((b) => b._d <= rad).sort((x, y) => x._d - y._d);
      }
      const stand = (b) => (!b.aktiv ? "nicht mehr gemeldet" : b.von && b.von > today() ? "geplant" : "laufend");
      const items = list.map((b) => ({
        baustelle_id: b.id, bezeichnung: b.bezeichnung, strasse: b.strasse, stadtbezirk: b.stadtbezirk, massnahme: b.massnahme,
        traeger: b.traeger, anderer_traeger: b.fremd, von: b.von, bis: b.bis, termine: "unverbindlich", stand: stand(b),
        ...(near ? { abstand_m: Math.round(b._d) } : {}),
        moegliche_umsetzung: b.kandidaten.map((c) => ({ drucksache: c.drucksache, titel: short(mask(c.titel, null, c.drucksache)), entschieden_am: c.entschieden_am,
          abstand_m: c.abstand_m, kriterien: c.kriterien, evidenz: "abgeleitet – Indiz, kein Beleg" })),
      }));
      return { ...page(items, a.seite), archiv_beginn: d.meta.archiv_beginn, abruf: d.meta.abruf, hinweise: d.meta.hinweise,
        quelle: `Stadt Bonn, Baustellen – ${d.meta.lizenz}` };
    },

    // Kontextdaten je Gebiet (pipeline/kontext.py): Einordnung, kein Urteil, keine Rangfolge
    async hole_kontext(a) {
      const d = await kontextDaten();
      if (!a.gebiet) throw new ToolError("Bitte ein Gebiet angeben.", { beispiele: ["Endenich", "Beuel", "ganz Bonn"] });
      let ebene, name, werte, vergleich = null, vergleichName = null;
      if (GANZ_BONN.has(norm(a.gebiet))) { ebene = "stadt"; name = "ganz Bonn"; werte = d.bonn; }
      else {
        const bez = Object.keys(d.bezirke).filter((b) => norm(b) === norm(a.gebiet) || norm(`stadtbezirk ${b}`) === norm(a.gebiet));
        if (bez.length) { ebene = "stadtbezirk"; name = bez[0]; werte = d.bezirke[name]; vergleich = d.bonn; vergleichName = "ganz Bonn"; }
        else {
          const ot = resolve(Object.keys(d.ortsteile).sort(), norm(a.gebiet).replace(/^(ortsteil|stadtteil) /, ""), "Ortsteil");
          if (ot.length > 1) throw new ToolError(`„${a.gebiet}“ ist nicht eindeutig.`, { moegliche_werte: ot });
          ebene = "ortsteil"; name = ot[0]; werte = d.ortsteile[name];
          const b = d.stadtbezirk_je_ortsteil?.[name];
          if (b) { vergleich = d.bezirke[b]; vergleichName = `Stadtbezirk ${b}`; }
        }
      }
      const keys = (a.kennzahlen?.length ? a.kennzahlen : d.meta.reihenfolge).filter((k) => d.meta.kennzahlen[k]);
      const kennzahlen = keys.map((k) => {
        const m = d.meta.kennzahlen[k], q = d.meta.quellen[m.quelle] || {};
        const o = { kennzahl: m.titel, wert: werte[k] ?? null, einheit: m.einheit, ...(vergleich ? { vergleich: vergleich[k] ?? null } : {}),
          quelle: q.titel, lizenz: q.lizenz, stand: q.stand, link: q.url, methode: m.methode,
          ...(q.uebergang ? { uebergang: q.uebergang } : {}),
          ...(werte[k] == null && m.ohne_wert && !(ebene === "ortsteil" && werte.einwohner < d.meta.mindest_einwohner) ? { ohne_wert: m.ohne_wert } : {}) };
        // Bodenrichtwert: Anteil der Einwohner in einer Zone für Wohnbauland; Hinweis, wenn viele außerhalb wohnen
        const cov = werte.bodenrichtwert_abdeckung, ab = d.meta.bodenrichtwert_hinweis_ohne_zone;
        if (k === "bodenrichtwert" && cov != null) {
          o.anteil_einwohner_in_zone = cov;
          if (ab != null && 100 - cov >= ab) o.hinweis = `Gilt nur für ${Math.round(cov)} % der Einwohner; die übrigen wohnen außerhalb von Zonen für Wohnbauland (Misch- und Kerngebiete).`;
        }
        return o;
      });
      const klein = ebene === "ortsteil" && werte.einwohner < d.meta.mindest_einwohner;
      return {
        gebiet: name, ebene, ...(vergleichName ? { vergleich_mit: vergleichName } : {}),
        ...(ebene === "ortsteil" ? { stadtbezirk: d.stadtbezirk_je_ortsteil?.[name] ?? null } : {}),
        evidenz: "abgeleitet", kennzahlen,
        hinweise: [d.meta.hinweis, "Zur Einordnung, kein Beleg für eine Vorlage oder einen Beschluss; keine Rangfolge der Gebiete. Stichtage der Quellen verschieden.",
          ...(klein ? [`Unter ${d.meta.mindest_einwohner} Einwohnern keine Anteile und Mittelwerte (wert: null).`] : [])],
      };
    },

    async datenstand() {
      const d = await status();
      return { heute: today(), ...d, quelle: "Datenstand des Ratsatlas Bonn" };
    },
  };

  async function run(name, args = {}) {
    if (!Object.hasOwn(impl, name)) return { fehler: `Unbekanntes Werkzeug „${name}“.`, werkzeuge: TOOLS.map((t) => t.name) };
    try {
      return fit(await impl[name](args && typeof args === "object" ? args : {}));
    } catch (e) {
      if (e instanceof ToolError) return { fehler: e.message, ...e.extra };
      return { fehler: "Die Daten konnten nicht geladen werden.", technisch: String(e?.message || e) };
    }
  }
  return { run, tools: TOOLS };
}

const locOf = (mask, p) => (l) => ({ ort: l.name, ebene: l.level, ortsteil: l.ortsteil, stadtbezirk: l.stadtbezirk, stufe: l.stage, methode: l.method, konfidenz: l.confidence, fundstelle: mask(l.evidence, p.paper_type, p.reference) });
const relOf = (mask) => (r) => ({ drucksache: r.reference, art: r.paper_type, titel: short(mask(r.name, r.paper_type, r.reference)), datum: r.date });

function dist(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180, dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

// Begrenzung: lange Listen kürzen, bis das Ergebnis unter MAX_CHARS bleibt (gekuerzt: true)
export function fit(result) {
  if (JSON.stringify(result).length <= MAX_CHARS) return result;
  const out = { ...result, gekuerzt: true };
  const lists = Object.keys(out).filter((k) => Array.isArray(out[k])).sort((a, b) => JSON.stringify(out[b]).length - JSON.stringify(out[a]).length);
  for (const k of lists) {
    while (out[k].length > 1 && JSON.stringify(out).length > MAX_CHARS) out[k] = out[k].slice(0, Math.ceil(out[k].length * 0.7));
    if (JSON.stringify(out).length <= MAX_CHARS) break;
  }
  return out;
}
