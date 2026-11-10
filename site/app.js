// Ratsatlas Köln – Karte vollflächig, darüber Liste, Zeitleiste, Detail (Prozesslinie mit Evidenzstatus)
// und typische Wege. Liest die Exporte der Pipeline (data/export/koeln). Aus dem Ratsatlas Köln übernommen.
(function () {
  "use strict";
  const STADT = "koeln", STADT_NAME = "Köln";   // Gebietsart „ganze Stadt“ in Links (?gebiet=koeln:ganz) und Pfaden
  const BONN = `data/export/${STADT}/`;          // Name aus Bonn übernommen: Basispfad der Exporte
  const PILOT = null;                             // kein Pilot-Stadtteil (CLAUDE.md 2)
  // Flächen: vereinfacht aus dem Gesamtexport (pipeline/flaechen.py, rund 2 m), sonst die vollen Flächen
  const GEO = { ortsteil: "data/geo/stadtteile_koeln.geojson", bezirk: "data/geo/stadtbezirke_koeln.geojson",
    bplan: "data/geo/bebauungsplaene_koeln.geojson" };
  const GEO_LIGHT = { ortsteil: `${BONN}flaechen/ortsteile.json`, bezirk: `${BONN}flaechen/bezirke.json`,
    bplan: `${BONN}flaechen/bebauungsplaene.json` };
  const loadGeo = (k) => fetch(GEO_LIGHT[k]).then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .catch(() => fetch(GEO[k]).then((r) => r.json()));
  // Startzustand ohne Gebiet im Link: Übersicht über ganz Köln (Stadtbezirke anklickbar, noch keine Vorlagen geladen)
  const DEFAULT_AREA = `${STADT}:alle`;
  const OVERVIEW_HINT = "Ganz Köln: auf der Karte einen Stadtbezirk und dann einen Stadtteil anklicken oder oben ein Gebiet wählen. Die Suche findet Vorlagen in ganz Köln.";
  const REPO = "https://github.com/daimpad/ratsatlas-koeln";
  const RANK = { hoch: 3, mittel: 2, niedrig: 1 };
  const LIST_STEP = 50;  // Liste in Schritten zu 50 mit „Weitere … anzeigen“ (Ladezeit Schritt 2, Entscheidung 02.11.2026)
  const MOBILE = matchMedia("(max-width: 900px)");
  const NARROW = matchMedia("(max-width: 1279px)");
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const CONF = { hoch: "Ort gesichert", mittel: "Ort erschlossen", niedrig: "Ort unsicher" };
  const METHOD = {
    oparl_location: "Ortsangabe der Stadt (OParl)", oparl_sublocality: "Stadtteil laut Ortsangabe der Stadt (OParl)",
    strasse: "Straßenname im Titel",
    "strasse+hausnummer_punkt": "Straßenname mit Hausnummer im Titel, Hauskoordinate laut „Adressen Köln“ (nur Vorlagen der Verwaltung und politische Anträge)",
    ortsteil_teilname: "Teil eines Stadtteilnamens im Titel (z. B. „Heumar“ für Rath/Heumar)",
    district_from_committee: "nur in einer Bezirksvertretung beraten, Ort sonst unbekannt",
    "strasse+ortsteil": "Straßen- und Stadtteilname im Titel", "strasse+bezirk": "Straßenname im Titel, Bezirk eingegrenzt",
    "strasse+kreuzung": "Straßennamen im Titel, Stadtteil der Kreuzung",
    "strasse+hausnummer": "Straßenname mit Hausnummer im Titel, Stadtteil laut „Adressen Köln“",
    strasse_mehrdeutig: "Straßenname im Titel, mehrere Lagen", ortsteil_name: "Stadtteilname im Titel",
    ortsteil_adjektiv: "Stadtteil im Titel (z. B. „Ehrenfelder …“)",
    ortsteil_variante: "Stadtteilname im Titel, abweichende Schreibung", stadtbezirk_name: "Stadtbezirk im Titel",
    stadtbezirk_variante: "Stadtbezirk im Titel, abweichende Schreibung",
    stadtbezirk_adjektiv: "Stadtbezirk im Titel (Adjektiv)", vererbt: "von der übergeordneten Vorlage übernommen",
    bebauungsplan: "Bebauungsplan-Nummer im Titel, Geltungsbereich laut Stadt Köln",
    objekt_name: "Name eines Gebäudes oder einer Anlage im Titel, Lage laut OpenStreetMap",
  };
  const STATUS = {
    belegt: "belegt", abgeleitet: "abgeleitet", soll: "soll", "nicht_öffentlich": "nicht öffentlich", unklar: "unklar",
  };
  // Glossar, Erläuterungen und Bezeichnungen der Prozessebene: data/export/glossar.json (pipeline/glossar.py)
  const GLOSSAR_URL = "data/export/glossar.json";
  let GLOSSAR = {}, NOTES = {}, STEP_LABEL = {}, STATUS_TEXT = {}, STAND_TEXT = {}, BEGRIFF = {}, ARTEN = {}, KUERZEL = {};
  // Herkunft eines Ortsbezugs in einfachen Worten (Stufe A/B/C im Audit; Entscheidung 02.11.2026)
  const STUFE = { A: "Angabe der Stadt", B: "nach festen Regeln erschlossen", C: "mit einem Sprachmodell erschlossen" };
  const LIMITS = `<details class="acc"><summary>Was diese Darstellung nicht zeigen kann</summary><ul>
    <li>Verwaltungsinterne Abläufe vor dem Datum der Vorlage (Erarbeitung, Mitzeichnung, Freigaben).</li>
    <li>Die Umsetzung von Beschlüssen: Die Beschlusskontrolle hat keine öffentliche Schnittstelle.</li>
    <li>Ob jeder Schritt nach Regelwerk eingehalten wurde: Ein Abgleich mit der Kölner Zuständigkeitsordnung ist noch nicht eingebaut.</li>
    <li>Inhalte nichtöffentlicher Beratungen und Vorlagen, die das Ratsinformationssystem nicht über die OParl-Schnittstelle anbietet.</li>
    <li>Beratungen, deren Sitzung oder Tagesordnungspunkt in den Daten fehlt.</li></ul>
    <p class="hint">Abweichungen zwischen Regel und Ablauf sind Befunde, keine Bewertung.</p></details>`;
  // Startfenster „Los geht's“ im Vorgang, solange keine Vorlage gewählt ist; die Tour steht in site/tour.js
  const INTRO = `<div class="intro">
    <p class="intro-lead">Was Rat, Ausschüsse und Bezirksvertretungen der Stadt Köln beraten – wo, wann und wer.</p>
    <button type="button" class="btn btn-cta tour-cta" data-tour><span class="tour-cta-dot" aria-hidden="true"></span>Tour durch alle Funktionen</button>
    </div>${LIMITS}`;

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // nur http(s)-Adressen aus den Daten werden zu Links
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : null);
  // heutiges Datum in Köln (nicht UTC: zwischen 0 und 2 Uhr wäre es sonst der Vortag), bei jedem Aufruf neu
  const heute = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" }).format(new Date());
  const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
  // Formatierer einmal anlegen: toLocaleDateString mit Optionen baut sie bei jedem Aufruf neu (Ladezeit Schritt 2:
  // rund 200 ms beim Öffnen eines Gebiets, mobil gedrosselt gemessen)
  const DATUM = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", year: "numeric" });
  const fmtDate = (iso) => iso ? DATUM.format(new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso)) : "";
  // Kalendertag (JJJJ-MM-TT) eines Zeitpunkts (STAND.json, index.json; voller Zeitstempel, UTC) in Europe/Berlin:
  // 23:30 UTC ist dort schon der nächste Tag; ein Zeitstempel ohne Zone gilt als UTC (sonst hinge der Tag von der Zone
  // des Rechners ab); ist nur der Anfang lesbar, die ersten zehn Zeichen; ist auch der kein Datum (null, Zahl, Objekt,
  // „kaputt“, 2026-13-45), null statt eines RangeError
  const BERLIN_TAG = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" });
  const zeitTag = (wert) => {
    const s = typeof wert === "string" ? wert : "";
    if (!ISO_DAY.test(s.slice(0, 10))) return null;
    const voll = new Date(s.length > 10 && !/(Z|[+-]\d{2}(:?\d{2})?)$/i.test(s) ? s + "Z" : s);
    const d = Number.isNaN(voll.getTime()) ? new Date(s.slice(0, 10) + "T12:00:00Z") : voll;
    const tag = Number.isNaN(d.getTime()) ? "" : BERLIN_TAG.format(d);
    return ISO_DAY.test(tag) ? tag : null;
  };
  // Datum eines Zeitpunkts nach derselben Regel, sonst „unbekannt“
  const zeitDatum = (wert) => { const tag = zeitTag(wert); return tag ? fmtDate(tag) : "unbekannt"; };
  // Nebenlisten, die beim letzten Abruf nicht aktualisiert wurden (index.json meta.abruf_warnungen,
  // pipeline/export.py): ein Satz je Liste im Datenstand, ohne Fachbegriffe und nicht nur als Farbe
  const WARNUNG_SATZ = { meetings: "Sitzungstermine wurden", organizations: "Die Liste der Gremien wurde" };
  const standWarnungen = (w) => Object.keys(WARNUNG_SATZ).filter((k) => w && w[k]).map((k) => ` · ${WARNUNG_SATZ[k]} beim letzten Abruf nicht aktualisiert; gezeigt wird ${w[k].stand ? `der Stand vom ${zeitDatum(w[k].stand)}` : "der letzte gültige Stand"}.`).join("");
  // fehlgeschlagener Abruf (index.json meta.abruf_fehler) im Datenstand
  const standFehler = (f) => f ? ` · Der letzte Abruf am ${zeitDatum(f.zeit)} ist fehlgeschlagen; gezeigt wird der letzte gültige Datenstand.` : "";
  // Zeile im Datenstand (#stand) aus meta (Quellen, generated_at) und index.json meta (Fehler, Warnungen); alle Daten
  // nach derselben Regel (zeitDatum)
  const standText = (m, im) => {
    const quellen = (Array.isArray(m && m.sources) ? m.sources : []).filter((s) => s && s.retrieved_at)
      .map((s) => `${QUELLE_NAME[s.name] || s.name}: ${zeitDatum(s.retrieved_at)}`).join(" · ");
    return `Datenstand: ${quellen || "–"}${m && m.generated_at ? ` · erzeugt ${zeitDatum(m.generated_at)}` : ""}`
      + standFehler(im && im.abruf_fehler) + standWarnungen(im && im.abruf_warnungen);
  };
  // Datenstand als Berliner Kalendertag (Markierung in der Zeitleiste, Jahresgrenze in hasPaperFeed) nach derselben
  // Regel (zeitTag): Abruf des Ratsinformationssystems, sonst Erzeugung, sonst heute; nur lesbare Werte
  const standTag = (m) => {
    const oparl = (Array.isArray(m && m.sources) ? m.sources : []).find((s) => s && s.name === "oparl-koeln") || {};
    return zeitTag(oparl.retrieved_at) || zeitTag(m && m.generated_at) || heute();
  };
  const debounce = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };

  let index = null, zeit = null, geo = {}, meta = null, papers = [], area = null, selected = null, dataStand = null, kontext = null, anliegen = null;
  let map, cluster, outline, markers = new Map(), tl = null, range = null, loadSeq = 0, detailSeq = 0, shown = LIST_STEP, lastList = [], lastMarkers = [], colorBy = "sicherheit", legendEl = null, mapStack = null, mapSheet = null, mapToggles = [], setMapMenu = () => {}, mapMenuCount = null, planOn = false, allPlans = null, shownPlan = null;
  let bau = null, bauOn = false, bauLayer = null, shownSite = null, bauByRef = new Map();
  let kxOn = new Set(), kxData = {}, kxLayers = {}, brwBr = null, ebenenIdx = null;  // zuschaltbare Flächen (Überschwemmung, Bodenrichtwerte)
  // Kartenvorschau ohne Ratsvorlagen (index.json meta.vorschau, tools/vorschau.py): keine Zeitleiste, keine Punkte,
  // Flächen nach Kennzahlen statt nach Vorlagen; Liste und Suche nennen den Grund statt „keine Vorlage passt“
  let vorschau = false;
  const VORSCHAU_LISTE = "Die Vorschau enthält noch keine Ratsvorlagen. Sie folgen, sobald der Abruf der Stadt Köln eingerichtet ist; bis dahin zeigt die Karte Stadtteile, Kennzahlen und offene Daten (Menü „Ebenen“).";
  // Suche über ganz Köln (suche.json, erst bei Bedarf geladen)
  let search = null, searchLoading = null;
  const THEMES = {  // wie pipeline/topics.THEMES
    verkehr: "Verkehr und Mobilität", bauen: "Bauen und Stadtentwicklung", umwelt: "Umwelt, Grün und Klima",
    bildung: "Schule und Bildung", kinder: "Kinder, Jugend und Familie", soziales: "Soziales, Wohnen und Gesundheit",
    kultur: "Kultur und Sport", wirtschaft: "Wirtschaft und Finanzen", sicherheit: "Sicherheit und Ordnung",
    beteiligung: "Beteiligung, Integration und Internationales",
  };
  // Farben der Themen auf der Karte (in Anlehnung an Okabe-Ito, unterscheidbar bei Farbfehlsichtigkeit; weißer Rand)
  const THEME_COLOR = { verkehr: "#0072b2", bauen: "#d55e00", umwelt: "#009e73", bildung: "#cc79a7", kinder: "#e69f00",
    soziales: "#882255", kultur: "#56b4e9", wirtschaft: "#8c6d1f", sicherheit: "#332288", beteiligung: "#44aa99" };
  const NO_THEME = "#8a8a96";
  const THEME_METHOD = { amt: "Amt", gremium: "Gremium", stichwort: "Stichwort im Titel" };

  // --- Flächen ein- und ausklappen ---------------------------------------------------------------
  const SHEETS = ["panel-list", "panel-detail", "panel-auswertung", "panel-termine", "panel-prozesse", "panel-mitmachen", "timeline-wrap", "panel-assistent"];
  const LEFT = ["panel-list", "panel-assistent"];  // Liste und Assistent teilen sich die linke Seite
  const OVERLAYS = ["panel-auswertung", "panel-termine", "panel-prozesse", "panel-mitmachen"];
  const toggleFor = (id) => document.querySelector(`.toggle[data-panel="${id}"]`);
  // Ratsassistent (site/chat/ui.js und sechs weitere Module) erst laden, wenn die Fläche zum ersten Mal aufgeht
  // oder die Schaltfläche den Fokus bekommt; der Seitenstart braucht ihn nicht
  let chatReady = null;
  function loadChat() {
    chatReady ||= import("./chat/ui.js").catch((e) => { chatReady = null; console.error("Ratsassistent nicht geladen", e); });
    return chatReady;
  }
  const opener = {};   // Element, das eine Fläche ohne eigene Schaltfläche in der Leiste geöffnet hat (Fokus beim Schließen)
  function setPanel(id, open) {
    const el = document.getElementById(id);
    if (open && el.hidden && document.activeElement && document.activeElement !== document.body) opener[id] = document.activeElement;
    el.hidden = !open;
    document.querySelectorAll(`.toggle[data-panel="${id}"]`).forEach((b) => b.setAttribute("aria-pressed", String(open)));
    if (id === "panel-list") { document.body.classList.toggle("list-open", open); document.body.classList.toggle("list-closed", !open); }
    if (id === "panel-detail") { document.body.classList.toggle("detail-open", open); document.body.classList.toggle("detail-closed", !open); }
    if (id === "panel-assistent") { document.body.classList.toggle("chat-open", open); if (open) loadChat(); }
    if (id === "panel-prozesse") { if (open) openProzesse(); syncUrl(); }
    if (id === "panel-mitmachen") { if (open) openMitmachen(); syncUrl(); }
    if (!open) return;
    closeMega();
    // schmale Bildschirme: nur eine Fläche; mittlere Breiten: Liste oder Vorgang, damit die Zeitleiste Platz hat;
    // Auswertung und Termine liegen mittig übereinander, daher immer nur eines davon
    const others = MOBILE.matches ? SHEETS : OVERLAYS.includes(id) ? OVERLAYS
      : NARROW.matches && (id === "panel-list" || id === "panel-detail") ? ["panel-list", "panel-detail", ...(id === "panel-list" ? LEFT : [])]
      : LEFT.includes(id) ? LEFT : [];
    for (const other of others) if (other !== id && !document.getElementById(other).hidden) setPanel(other, false);
  }
  function focusPanel(id) {
    const el = document.getElementById(id);
    const target = el.querySelector("h2[tabindex], .tl-stage, summary");
    if (target) target.focus();
  }
  function showIntro() {
    detailSeq++;
    shownPlan = null;
    shownSite = null;
    if (planLayer) { planLayer.remove(); planLayer = null; }   // Umriss eines zuvor gewählten Vorgangs (Gebietswechsel)
    $("#detail-heading").textContent = "Los geht's";
    $("#detail").innerHTML = INTRO;
  }
  function closePanel(id) {
    setPanel(id, false);
    const t = toggleFor(id);
    // Auswertung, Termine und Mitmachen haben keine Schaltfläche in der Leiste: Fokus zurück auf das öffnende Element,
    // sonst auf den Eintrag im Menü (Code-Prüfung 23.10.2026: Fokus lag danach auf <body>)
    const back = t && t.offsetParent ? t : opener[id]?.isConnected && opener[id].offsetParent ? opener[id]
      : document.querySelector(`[data-mega][aria-controls="${{ "panel-auswertung": "mega-auswertung", "panel-termine": "mega-mitmachen", "panel-mitmachen": "mega-mitmachen" }[id] || ""}"]`);
    if (back) back.focus();
  }
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-panel]");
    if (t) {
      const open = document.getElementById(t.dataset.panel).hidden;
      setPanel(t.dataset.panel, open);
      if (open) focusPanel(t.dataset.panel);
    }
    const c = e.target.closest("[data-close]");
    if (c) closePanel(c.dataset.close);
    const s = e.target.closest("[data-show]");
    if (s) { setPanel(s.dataset.show, true); focusPanel(s.dataset.show); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || $("#about").open || $("#neu").open) return;
    if (openMegaId) return closeMega(true);
    if (navIsOpen()) return setNav(false, true);
    const overlay = OVERLAYS.find((id) => !document.getElementById(id).hidden);
    if (overlay) return closePanel(overlay);
    const inside = SHEETS.find((id) => document.getElementById(id).contains(document.activeElement));
    if (inside) closePanel(inside);
  });
  function applyLayout() {
    if (MOBILE.matches) {
      const open = SHEETS.filter((id) => !document.getElementById(id).hidden);
      open.slice(1).forEach((id) => setPanel(id, false));
    } else if (NARROW.matches && !$("#panel-list").hidden && !$("#panel-detail").hidden) setPanel("panel-detail", false);
    $("#timeline-wrap").classList.toggle("tl-compact", MOBILE.matches);
    if (!MOBILE.matches) setNav(false);
    clampWidths();
    if (tl) tl.select(selected);
  }

  // --- Mega-Menüs ------------------------------------------------------------------------------------
  let openMegaId = null;
  function openMega(id, trigger) {
    if (openMegaId && openMegaId !== id) closeMega();
    if (id === "mega-suche" && navIsOpen()) setNav(false);
    const el = document.getElementById(id);
    // im Hamburger-Menü klappt das Mega-Menü unter seinem Eintrag auf (Platz merken, beim Schließen zurück)
    const entry = navIsOpen() && navMore.querySelector(`[data-mega="${id}"]`);
    if (entry) { if (!megaHome.has(el)) { const mark = document.createComment(id); el.before(mark); megaHome.set(el, mark); } entry.after(el); }
    el.hidden = false;
    openMegaId = id;
    el.dataset.trigger = trigger ? trigger.id || "" : "";
    document.querySelectorAll(`[data-mega="${id}"]`).forEach((b) => b.setAttribute("aria-expanded", "true"));
    if (id === "mega-suche") fillChips();
    if (id === "mega-mitmachen") fillMitmachen();
    if (MOBILE.matches) SHEETS.forEach((s) => !document.getElementById(s).hidden && setPanel(s, false));
  }
  function closeMega(returnFocus) {
    if (!openMegaId) return;
    const id = openMegaId;
    const el = document.getElementById(id);
    el.hidden = true;
    if (megaHome.has(el)) { megaHome.get(el).replaceWith(el); megaHome.delete(el); }
    openMegaId = null;
    document.querySelectorAll(`[data-mega="${id}"]`).forEach((b) => b.setAttribute("aria-expanded", "false"));
    if (returnFocus) (id === "mega-suche" ? $("#q") : document.querySelector(`[data-mega="${id}"]`)).focus();
  }
  document.addEventListener("click", (e) => {
    const m = e.target.closest("[data-mega]");
    if (m) {
      const id = m.dataset.mega;
      if (openMegaId === id) closeMega(); else { openMega(id, m); const f = document.getElementById(id).querySelector("button, a, input"); if (f && e.detail === 0) f.focus(); }
      return;
    }
    // Klick außerhalb schließt das Menü (das Suchfeld gehört zum Suchmenü)
    // (Ziele, die beim Klick neu aufgebaut wurden, z. B. Chips, sind nicht mehr im Dokument)
    if (openMegaId && e.target.isConnected && !e.target.closest(".mega") && !e.target.closest("#nav-search")) closeMega();
  });

  // --- Hamburger-Menü auf dem Telefon: Gebiet, Flächen und Menüs als Blatt über der Leiste --------------
  // (Entscheidung 02.11.2026: sichtbar bleiben nur Suche und ☰; Menüs klappen im Blatt auf)
  const burger = $("#nav-burger"), navMore = $("#nav-more"), megaHome = new Map();
  function navIsOpen() { return document.body.classList.contains("nav-open"); }
  function setNav(open, returnFocus) {
    if (open === navIsOpen()) return;
    if (!open) closeMega();
    else setMapMenu(false);   // nicht zugleich mit dem Blatt „Karte“
    document.body.classList.toggle("nav-open", open);
    burger.setAttribute("aria-expanded", String(open));
    if (!open && (returnFocus || navMore.contains(document.activeElement))) burger.focus();
  }
  burger.addEventListener("click", () => setNav(!navIsOpen()));
  // Wahl eines Eintrags schließt das Blatt (Flächen, Seiten, Dialoge, Tour, Links)
  navMore.addEventListener("click", (e) => {
    if (MOBILE.matches && e.target.closest(".toggle, [data-show], [data-panel], #about-open, [data-about], [data-neu], [data-tour], a[href]")) setNav(false);
  });
  $("#f-area").addEventListener("change", () => { if (MOBILE.matches) setNav(false); });
  // Tippen außerhalb der Leiste schließt das Blatt
  document.addEventListener("click", (e) => {
    if (navIsOpen() && e.target.isConnected && !e.target.closest(".nav") && !e.target.closest("dialog")) setNav(false);
  });

  // --- Breite von Liste und Vorgang per Ziehgriff ---------------------------------------------------
  const WIDTH = { list: { v: "--list-w", min: 300, max: () => Math.min(680, innerWidth * 0.45), def: 360 },
    detail: { v: "--detail-w", min: 340, max: () => Math.min(760, innerWidth * 0.5), def: 420 } };
  // Breite aus dem Inline-Stil (gesetzt von setWidth oder aus dem Speicher), sonst die Vorgabe wie in style.css (:root);
  // getComputedStyle erzwang hier bei jedem Aufruf eine Stilberechnung (Ladezeit Schritt 2: rund 100 ms im Gebiet)
  const widthOf = (k) => parseFloat(document.documentElement.style.getPropertyValue(WIDTH[k].v)) || WIDTH[k].def;
  function setWidth(k, px, save) {
    const w = WIDTH[k], v = Math.round(Math.max(w.min, Math.min(w.max(), px)));
    document.documentElement.style.setProperty(w.v, v + "px");
    const r = document.querySelector(`.resizer[data-resize="${k}"]`);
    r.setAttribute("aria-valuemin", String(w.min)); r.setAttribute("aria-valuemax", String(Math.round(w.max())));
    r.setAttribute("aria-valuenow", String(v)); r.setAttribute("aria-valuetext", `${v} Pixel breit`);
    if (save) { try { localStorage.setItem("ris-breite-" + k, String(v)); } catch (e) { /* ohne Speicher */ } }
  }
  function clampWidths() { for (const k of Object.keys(WIDTH)) setWidth(k, widthOf(k)); }
  for (const k of Object.keys(WIDTH)) {
    try { const v = Number(localStorage.getItem("ris-breite-" + k)); if (v) document.documentElement.style.setProperty(WIDTH[k].v, v + "px"); } catch (e) { /* ohne Speicher */ }
  }
  document.querySelectorAll(".resizer").forEach((r) => {
    const k = r.dataset.resize, sign = k === "list" ? 1 : -1;
    r.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      r.setPointerCapture(e.pointerId);
      const x0 = e.clientX, w0 = widthOf(k);
      r.classList.add("active"); document.body.classList.add("resizing");
      const move = (ev) => setWidth(k, w0 + sign * (ev.clientX - x0));
      const up = () => { r.removeEventListener("pointermove", move); r.classList.remove("active"); document.body.classList.remove("resizing"); setWidth(k, widthOf(k), true); };
      r.addEventListener("pointermove", move);
      r.addEventListener("pointerup", up, { once: true });
      r.addEventListener("pointercancel", up, { once: true });
    });
    r.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 64 : 16;
      const map = { ArrowRight: sign * step, ArrowLeft: -sign * step };
      if (map[e.key] !== undefined) { e.preventDefault(); setWidth(k, widthOf(k) + map[e.key], true); }
      if (e.key === "Home") { e.preventDefault(); setWidth(k, WIDTH[k].def, true); }
    });
    r.addEventListener("dblclick", () => setWidth(k, WIDTH[k].def, true));
  });

  // --- Über ----------------------------------------------------------------------------------------
  $("#about-open").addEventListener("click", () => { closeMega(); $("#about").showModal(); });
  $("#about-close").addEventListener("click", () => $("#about").close());
  $("#about").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-about]");
    if (!b) return;
    closeMega();
    $("#about").showModal();
    const h = document.getElementById("about-" + b.dataset.about);
    if (h) { h.scrollIntoView({ block: "start" }); h.focus(); }
  });
  // Externe Links immer in einem neuen Tab (Entscheidung des Auftraggebers 28.10.2026); gilt auch für Links, die
  // erst zur Laufzeit entstehen (Vorgang, Prozesse, Mitmachen, Assistent)
  document.addEventListener("click", (e) => {
    const a = e.target.closest?.("a[href]");
    if (a && /^https?:$/.test(a.protocol) && a.host !== location.host && !a.target) { a.target = "_blank"; a.rel = a.rel || "noopener"; }
  }, true);
  // „Was ist neu?“ in einem eigenen Fenster (aus „Über“ und dem Menü „Daten“)
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-neu]")) { closeMega(); if ($("#about").open) $("#about").close(); $("#neu").showModal(); }
    if (e.target.closest("[data-close-dialog]")) e.target.closest("dialog").close();
  });
  $("#neu").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });

  // --- Gebiet ----------------------------------------------------------------------------------------
  function parseArea(value) {
    const [kind, key] = (value || "").split(":");
    if (!index) return { kind: STADT, key: "alle", name: `ganz ${STADT_NAME}`, file: null };  // ohne Gesamtexport kein Pilot
    if (kind === "ortsteil") {
      const o = index.ortsteile.find((x) => x.slug === key);
      if (o) return { kind, key, name: o.name, file: `${BONN}ortsteile/${key}.json` };
    }
    if (kind === "bezirk") {
      const b = index.bezirke.find((x) => x.slug === key);
      if (b) return { kind, key, name: b.name, file: `${BONN}bezirke/${key}.json` };
    }
    if (kind === STADT) return { kind, key: "alle", name: "ganz Köln", file: null };
    if (kind === "ohne" && index.ohne_ortsbezug.some((x) => x.jahr === key)) {
      return { kind, key, name: `ohne Ortsbezug ${key}`, file: `${BONN}ohne-ortsbezug/${key}.json` };
    }
    return parseArea(DEFAULT_AREA);
  }
  function fillAreaSelect() {
    const sel = $("#f-area");
    if (!index) { sel.innerHTML = `<option value="${STADT}:alle">Daten nicht verfügbar</option>`; return; }
    const groups = {};
    index.ortsteile.forEach((o) => (groups[o.stadtbezirk] ||= []).push(o));
    // Ausgangszustand „Gebiet wählen“ (zeigt ganz Köln); „Ganz Köln“ als eigener Eintrag, wenn man dorthin zurückwechselt
    let html = `<option value="${STADT}:alle" hidden>Gebiet wählen</option><option value="${STADT}:ganz">Ganz ${STADT_NAME}</option>`;
    for (const bz of Object.keys(groups).sort()) {
      html += `<optgroup label="Stadtbezirk ${esc(bz)}">` + groups[bz].sort((a, b) => a.name.localeCompare(b.name, "de"))
        .map((o) => `<option value="ortsteil:${o.slug}">${esc(o.name)}${vorschau ? "" : ` (${o.count})`}</option>`).join("");   // Vorschau: keine Zahl 0
      const b = index.bezirke.find((x) => x.name === bz);
      if (b && b.count) html += `<option value="bezirk:${b.slug}">ganzer Stadtbezirk ${esc(bz)}, ohne genaueren Ort (${b.count})</option>`;
      // Vorschau: Stadtbezirk mit seinen Kennzahlen wählbar (Feeds und Links führen auf ?gebiet=bezirk:…; ohne Eintrag blieb die Auswahl leer)
      else if (b && vorschau) html += `<option value="bezirk:${b.slug}">ganzer Stadtbezirk ${esc(bz)}</option>`;
      html += "</optgroup>";
    }
    if (index.ohne_ortsbezug.length) html += '<optgroup label="Stadtweit / ohne Ortsbezug">' + index.ohne_ortsbezug
      .map((y) => `<option value="ohne:${y.jahr}">${y.jahr} (${y.count})</option>`).join("") + "</optgroup>";
    sel.innerHTML = html;
  }
  function areaLocs(p) {
    if (area.kind === "ortsteil") return p.locations.filter((l) => l.ortsteil === area.name);
    if (area.kind === "bezirk") return p.locations.filter((l) => l.level === "stadtbezirk" && l.stadtbezirk === area.name);
    return [];
  }
  const bestConfidence = (p) => areaLocs(p).reduce((b, l) => (RANK[l.confidence] > RANK[b] ? l.confidence : b), "niedrig");

  function setLoading(on) {
    $("#papers").setAttribute("aria-busy", String(on));
    $("#panel-list").classList.toggle("loading", on);
  }
  // Gebietsdateien, die der Start schon angefordert hat (Gebiet im Link), je Adresse eine Antwort
  const vorab = new Map();
  // Stadtbezirk ohne Vorlagen „ohne genaueren Ort“ führt fillAreaSelect nicht auf; öffnet ein Link ihn (Gebietsseite,
  // Kartenvorschau), den Eintrag ergänzen, damit die Auswahl nicht leer bleibt
  function areaOption(v, next) {
    const sel = $("#f-area");
    if (next.kind !== "bezirk" || [...sel.options].some((o) => o.value === v)) return;
    const b = index.bezirke.find((x) => x.slug === next.key);
    const grp = [...sel.querySelectorAll("optgroup")].find((g) => g.label === `Stadtbezirk ${next.name}`);
    (grp || sel).append(new Option(`ganzer Stadtbezirk ${next.name}, ohne genaueren Ort (${b ? b.count : 0})`, v));
  }
  async function loadArea(value, keepState) {
    const seq = ++loadSeq;
    const next = parseArea(value);
    const v = next.kind === STADT && value === `${STADT}:ganz` ? value : `${next.kind}:${next.key}`;
    areaOption(v, next);
    $("#f-area").value = v;
    $("#count").textContent = `Lade Vorlagen für ${next.name} …`;
    setLoading(true);
    let data;
    try {
      if (next.file) {
        const r = await (vorab.get(next.file) || fetch(next.file));
        vorab.delete(next.file);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        data = await r.json();
      } else data = { meta: { sources: [] }, papers: [] };
    } catch (err) {
      if (seq !== loadSeq) return;
      setLoading(false);
      $("#count").innerHTML = `Die Vorlagen für ${esc(next.name)} konnten nicht geladen werden (${esc(err.message)}). <button type="button" class="btn btn-secondary" id="retry">Erneut versuchen</button>`;
      $("#retry").addEventListener("click", () => loadArea(value, keepState));
      return;
    }
    // ein späterer Gebietswechsel hat diese Antwort überholt
    if (seq !== loadSeq) return;
    setLoading(false);
    area = next;
    meta = data.meta;
    if (index && index.meta) meta = { ...meta, generated_at: index.meta.generated_at, sources: index.meta.sources };
    dataStand = standTag(meta);
    // vor der Zeitleiste: Der Datenstand steht auch, wenn ein späterer Schritt scheitert
    $("#stand").textContent = standText(meta, index && index.meta);
    papers = data.papers;
    document.title = area.kind === STADT ? "Ratsatlas Köln – Was Rat, Ausschüsse und Bezirksvertretungen beraten – wo, wann und wer"
      : `Ratsatlas Köln – Ratsvorlagen ${area.kind === "ohne" ? "ohne Ortsbezug " + area.key : "in " + area.name}`;
    $("#f-conf").hidden = area.kind === "ohne" || area.kind === STADT;
    fillFilters();
    drawOutline();
    selected = null;
    shown = LIST_STEP;
    if (!keepState) showIntro();
    if (tl && zeit) {
      const series = zeit.areas[`${area.kind}:${area.key}`] || zeit.areas.gesamt;
      tl.setData({ months: zeit.months, categories: zeit.categories, density: series, meetings: zeit.meetings,
        terms: zeit.terms, dataStart: zeit.data_start, dataStand });
      tl.select(null);
      tl.setSites(areaSites());
    }
    subscribeArea();
    if (!$("#panel-termine").hidden) showTermine();
    if (!$("#panel-auswertung").hidden && !$("#stats").hidden) showStats();
    render();
    syncUrl();
  }

  // --- Karte -----------------------------------------------------------------------------------------
  const MARKER = { radius: 7, weight: 2, color: "#fff", fillOpacity: 0.95 };
  // Karte mit Kacheln vor den übrigen Startdaten anlegen: Die Kacheln sind das größte Element beim Start und warteten
  // bisher auf alle Daten (Phase 0 „Verständlichkeit“: ein Viertel der Ladezeit mobil). Erster Ausschnitt aus dem
  // Umriss des Gebiets in index.json (bbox), sonst ganz Köln (Grenzen der Stadtbezirke).
  const BONN_BOUNDS = [[50.8304, 6.7725], [51.085, 7.162]];   // Name aus Bonn; Grenzen der Kölner Stadtbezirke
  let kacheln = null;
  function startBounds(idx, value) {
    const [kind, key] = String(value || "").split(":");
    const liste = !idx ? [] : kind === "ortsteil" ? idx.ortsteile : kind === "bezirk" ? idx.bezirke : [];
    const b = (liste.find((x) => x.slug === key) || {}).bbox;
    return Array.isArray(b) && b.length === 4 ? [[b[0], b[1]], [b[2], b[3]]] : BONN_BOUNDS;
  }
  // Graue Standardansicht: eigene Rasterkacheln aus OSM-Daten vom Server dieser Seite (Workflow kacheln.yml, Ausschnitt
  // aus Protomaps, ODbL; Entscheidung 02.11.2026). Kachelbereich je Zoomstufe wie pipeline/kacheln/rahmen.py, außerhalb
  // fordert die Seite nichts an; über Zoom 16 werden die Kacheln vergrößert. „Farbige Karte“: Kacheln von OpenStreetMap.
  const KACHEL_RAHMEN = { 10: [529, 340, 533, 345], 11: [1059, 681, 1067, 690], 12: [2119, 1363, 2135, 1380], 13: [4247, 2735, 4261, 2752], 14: [8495, 5471, 8522, 5504], 15: [16997, 10953, 17038, 10998], 16: [33995, 21906, 34077, 21997] };
  const OSM_LINK = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap-Mitwirkende</a> (ODbL)';
  const GrauKacheln = L.TileLayer.extend({
    _isValidTile(c) {
      const r = KACHEL_RAHMEN[c.z];
      return !!r && c.x >= r[0] && c.x <= r[2] && c.y >= r[1] && c.y <= r[3];
    },
  });
  let farbig = false;
  try { farbig = localStorage.getItem("ris-karte-farbig") === "1"; } catch (e) { /* ohne Speicher: grau */ }
  const osmKacheln = () => L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: OSM_LINK });
  function kachelnSetzen() {
    if (kacheln) map.removeLayer(kacheln);
    const el = document.getElementById("map");
    el.classList.toggle("map-grau", !farbig);
    el.classList.remove("map-gray");
    if (farbig) { kacheln = osmKacheln().addTo(map); return; }
    const grau = new GrauKacheln("kacheln/{z}/{x}/{y}.png", { minZoom: 10, maxNativeZoom: 16, maxZoom: 19, attribution: `${OSM_LINK}, Protomaps` });
    // Ohne eigene Kacheln (z. B. vor dem ersten Lauf von kacheln.yml): OSM-Kacheln grau gefiltert wie bis 02.11.2026
    let geladen = false, fehler = 0;
    grau.on("tileload", () => { geladen = true; });
    grau.on("tileerror", () => {
      if (geladen || ++fehler < 2 || kacheln !== grau) return;
      grau.fire("load");  // wartenden Start (kachelnGeladen) freigeben, statt die volle Wartezeit abzuwarten
      map.removeLayer(grau);
      el.classList.remove("map-grau");
      el.classList.add("map-gray");
      kacheln = osmKacheln().addTo(map);
    });
    kacheln = grau.addTo(map);
  }
  function createMap(bounds = BONN_BOUNDS) {
    if (map) return;
    map = L.map("map", { zoomControl: false, scrollWheelZoom: true, minZoom: 10, zoomAnimation: !REDUCED, fadeAnimation: !REDUCED, markerZoomAnimation: !REDUCED });
    kachelnSetzen();
    map.fitBounds(bounds, { ...mapPadding(), animate: false });
  }
  // Schritt 1b: Daten, die das erste Bild nicht braucht, erst anfordern, wenn die sichtbaren Kacheln geladen sind
  // (höchstens ms Millisekunden warten), damit sie die Bandbreite nicht teilen
  const kachelnGeladen = (ms) => new Promise((resolve) => {
    if (!kacheln || !kacheln.isLoading()) { resolve(); return; }
    const t = setTimeout(resolve, ms);
    kacheln.once("load", () => { clearTimeout(t); resolve(); });
  });
  function initMap() {
    createMap();
    L.control.zoom({ position: "bottomright" }).addTo(map);
    // Ganz Köln ansehen: nur die Ansicht, das Gebiet bleibt; herausgezoomt sind die Stadtbezirke anklickbar
    const Whole = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        const b = L.DomUtil.create("button", "map-style map-whole");
        b.type = "button";
        // Telefon: nur das Symbol, der Name bleibt für Bildschirmleser (Entscheidung 02.11.2026)
        b.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-fit"/></svg><span class="map-whole-text">Ganz Köln ansehen</span>';
        b.title = "Karte auf ganz Köln zoomen; Stadtbezirke und Stadtteile lassen sich anklicken";
        b.addEventListener("click", () => { navDeep = false; navFocus = null; map.fitBounds(bonnBounds || L.geoJSON(geo.bezirk).getBounds(), mapPadding()); });
        L.DomEvent.disableClickPropagation(b);
        return b;
      },
    });
    new Whole().addTo(map);
    // Kartenhintergrund standardmäßig grau, damit die Marker hervortreten; die Wahl merkt sich der Browser
    const MapStyle = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        const b = L.DomUtil.create("button", "map-style");
        b.type = "button";
        b.textContent = "Farbige Karte";
        b.setAttribute("aria-pressed", String(farbig));
        b.addEventListener("click", () => {
          farbig = !farbig;
          try { localStorage.setItem("ris-karte-farbig", farbig ? "1" : "0"); } catch (e) { /* nicht speicherbar */ }
          b.setAttribute("aria-pressed", String(farbig));
          kachelnSetzen();
        });
        L.DomEvent.disableClickPropagation(b);
        return b;
      },
    });
    new MapStyle().addTo(map);
    // Farbe der Punkte: Sicherheit der Ortsangabe (Standard) oder Thema; Legende darunter
    // (Vorschau: keine Punkte, also bleibt es bei der Sicherheit; „farbe“ fällt beim nächsten syncUrl aus der Adresse)
    colorBy = !vorschau && new URLSearchParams(location.search).get("farbe") === "thema" ? "thema" : "sicherheit";
    const ColorBy = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        const b = L.DomUtil.create("button", "map-style map-color");
        b.type = "button";
        b.textContent = "Farbe nach Thema";
        b.setAttribute("aria-pressed", String(colorBy === "thema"));
        b.hidden = vorschau;   // ohne Vorlagen keine Punkte zum Färben
        b.addEventListener("click", () => {
          colorBy = colorBy === "thema" ? "sicherheit" : "thema";
          b.setAttribute("aria-pressed", String(colorBy === "thema"));
          drawMarkers(lastMarkers);
          syncUrl();
        });
        L.DomEvent.disableClickPropagation(b);
        return b;
      },
    });
    new ColorBy().addTo(map);
    // Geltungsbereiche aller rechtskräftigen Bebauungspläne als abschaltbare Ebene (erst beim Einschalten geladen)
    planOn = new URLSearchParams(location.search).get("plaene") === "1";
    const PlanToggle = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        const b = L.DomUtil.create("button", "map-style map-plans");
        b.type = "button";
        b.textContent = "Bebauungspläne";
        b.setAttribute("aria-pressed", String(planOn));
        b.addEventListener("click", () => { planOn = !planOn; b.setAttribute("aria-pressed", String(planOn)); drawAllPlans(); syncUrl(); });
        L.DomEvent.disableClickPropagation(b);
        return b;
      },
    });
    new PlanToggle().addTo(map);
    // Baustellen der Stadt (Archiv bzw. Feeds); nur mit Gesamtexport
    bauOn = new URLSearchParams(location.search).get("baustellen") === "1";
    const BauToggle = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        const b = L.DomUtil.create("button", "map-style map-bau");
        b.type = "button";
        b.textContent = "Baustellen";
        b.setAttribute("aria-pressed", String(bauOn));
        b.hidden = !bau;
        b.addEventListener("click", () => { bauOn = !bauOn; b.setAttribute("aria-pressed", String(bauOn)); drawSites(); syncUrl(); });
        L.DomEvent.disableClickPropagation(b);
        return b;
      },
    });
    new BauToggle().addTo(map);
    // Überschwemmungsgebiete und Bodenrichtwertzonen (Kontextdaten): erst beim Einschalten geladen, ab Stadtteil-Zoom gezeichnet
    // ohne kontext.json keine Ebenen aus der Adresse: die Schalter wären ausgeblendet und die Ebene nicht abschaltbar
    kxOn = new Set((new URLSearchParams(location.search).get("ebenen") || "").split(",")
      .filter((k) => (kontext && (Object.hasOwn(KX, k) || Object.hasOwn(PX, k))) || Object.hasOwn(EX, k)));
    const schalter = [...Object.entries(KX), ...Object.entries(PX), ...Object.entries(EX).map(([k, e]) => [k, { label: e.kurz || e.titel, gruppe: `${e.gruppe}: ${e.titel}`, ex: true }])];
    for (const [k, d] of schalter) {
      const Toggle = L.Control.extend({
        options: { position: "bottomright" },
        onAdd() {
          const b = L.DomUtil.create("button", `map-style map-kx map-kx-${k}`);
          b.type = "button";
          b.textContent = d.label;
          if (d.gruppe) b.title = d.gruppe;
          b.setAttribute("aria-pressed", String(kxOn.has(k)));
          b.hidden = d.ex ? false : !kontext;
          b.addEventListener("click", () => {
            if (kxOn.has(k)) kxOn.delete(k); else kxOn.add(k);
            b.setAttribute("aria-pressed", String(kxOn.has(k)));
            drawKx(); syncUrl();
          });
          L.DomEvent.disableClickPropagation(b);
          return b;
        },
      });
      new Toggle().addTo(map);
    }
    map.on("zoomend", () => { if (kxOn.size) drawKx(); });
    if (kxOn.size) drawKx();
    // „Ebenen“: alle zuschaltbaren Ebenen und Darstellungen hinter einer Schaltfläche, damit sie die Karte nicht
    // verdecken; die Zahl nennt die eingeschalteten (Entscheidung des Auftraggebers 28.10.2026)
    const MapMenu = L.Control.extend({
      options: { position: "bottomright" },
      onAdd() {
        const b = L.DomUtil.create("button", "map-style map-menu");
        b.type = "button";
        b.setAttribute("aria-expanded", "false");
        b.title = "Ebenen und Darstellung der Karte";
        const set = (open) => {
          map.getContainer().classList.toggle("map-menu-open", open); b.setAttribute("aria-expanded", String(open));
          if (open) setNav(false);   // Telefon: nicht zugleich mit dem Hamburger-Menü
        };
        setMapMenu = set;
        // Zahl der eingeschalteten Ebenen; auf dem Telefon heißt der Knopf „Karte“ (Ebenen, Legenden und Quellen)
        mapMenuCount = () => {
          const n = [...map.getContainer().querySelectorAll('.map-style[aria-pressed="true"]:not(.map-menu)')].filter((x) => !x.hidden).length;
          b.innerHTML = `${MOBILE.matches ? "Karte" : "Ebenen"}${n ? ` <span class="map-menu-n">${n}<span class="visually-hidden"> eingeschaltet</span></span>` : ""}`;
          b.title = MOBILE.matches ? "Ebenen, Legenden und Quellen der Karte" : "Ebenen und Darstellung der Karte";
        };
        const count = mapMenuCount;
        b.addEventListener("click", () => set(b.getAttribute("aria-expanded") !== "true"));
        map.on("click", () => set(false));
        map.getContainer().addEventListener("keydown", (e) => {
          if (e.key === "Escape" && b.getAttribute("aria-expanded") === "true") { e.stopPropagation(); set(false); b.focus(); }
        });
        new MutationObserver(count).observe(map.getContainer(), { attributes: true, subtree: true, attributeFilter: ["aria-pressed", "hidden"] });
        count();
        L.DomEvent.disableClickPropagation(b);
        return b;
      },
    });
    new MapMenu().addTo(map);
    // Legenden übereinander unten links, alle eingeklappt: Flächen (initNav), Punkte, Quellen und Datenstand
    const Stack = L.Control.extend({
      options: { position: "bottomleft" },
      onAdd() {
        const d = L.DomUtil.create("div", "map-stack");
        legendEl = L.DomUtil.create("details", "map-legend", d);
        const src = document.getElementById("sources");
        if (src) d.appendChild(src);
        L.DomEvent.disableClickPropagation(d);
        L.DomEvent.disableScrollPropagation(d);
        return d;
      },
    });
    mapStack = new Stack().addTo(map).getContainer();
    // Telefon: Ebenen, Legenden und Quellen in einem Blatt über der Leiste statt rechts und unten links
    // (Entscheidung 02.11.2026); die Elemente wandern hinein und auf breiten Bildschirmen an ihren Platz zurück
    mapSheet = L.DomUtil.create("section", "map-sheet", map.getContainer());
    mapSheet.id = "map-sheet";
    mapSheet.setAttribute("aria-labelledby", "map-sheet-titel");
    mapSheet.innerHTML = '<div class="map-sheet-kopf"><h2 id="map-sheet-titel">Karte</h2>'
      + '<button type="button" class="icon-btn map-sheet-zu" aria-label="Schließen"><svg class="icon" aria-hidden="true"><use href="#i-close"/></svg></button></div>'
      + '<h3 class="map-sheet-h">Ebenen und Darstellung</h3><div class="map-sheet-ebenen"></div><h3 class="map-sheet-h">Legenden und Quellen</h3>';
    mapSheet.querySelector(".map-sheet-zu").addEventListener("click", () => { setMapMenu(false); document.querySelector(".map-menu").focus(); });
    L.DomEvent.disableClickPropagation(mapSheet);
    L.DomEvent.disableScrollPropagation(mapSheet);
    mapToggles = [...map.getContainer().querySelectorAll(".leaflet-right .map-style:not(.map-menu):not(.map-whole)")]
      .map((el) => { const mark = document.createComment("ebene"); el.before(mark); return [el, mark]; });
    { const mark = document.createComment("legenden"); mapStack.before(mark); mapToggles.push([mapStack, mark]); }
    placeMapControls();
    MOBILE.addEventListener("change", placeMapControls);
    cluster = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 40, animate: !REDUCED }).addTo(map);
  }
  function placeMapControls() {
    const mobil = MOBILE.matches;
    for (const [el, mark] of mapToggles) {
      if (mobil) (el === mapStack ? mapSheet : mapSheet.querySelector(".map-sheet-ebenen")).append(el);
      else mark.after(el);
    }
    // Quellenzeile auf dem Telefon in einer Zeile: ⓘ öffnet Quellen, Lizenzen und Datenstand im Blatt
    map.attributionControl.setPrefix(mobil ? '<a href="#sources" class="attr-info" aria-label="Quellen, Lizenzen und Datenstand">ⓘ</a>'
      : L.Control.Attribution.prototype.options.prefix);
    if (mapMenuCount) mapMenuCount();
  }
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".attr-info")) return;
    e.preventDefault();
    setMapMenu(true);
    const src = document.getElementById("sources");
    src.open = true;
    src.querySelector("summary").focus();
    src.scrollIntoView({ block: "nearest" });
  });
  function mapPadding() {
    const desktop = !MOBILE.matches;
    const left = !desktop ? 16 : !$("#panel-list").hidden ? widthOf("list") + 32 : !$("#panel-assistent").hidden ? $("#panel-assistent").offsetWidth + 32 : 16;
    const right = desktop && !$("#panel-detail").hidden ? widthOf("detail") + 32 : 16;
    const top = desktop && !$("#timeline-wrap").hidden ? 86 + $("#timeline-wrap").offsetHeight + 12 : 90;
    return { paddingTopLeft: [left, top], paddingBottomRight: [right, desktop ? 70 : 150], animate: !REDUCED };
  }
  function drawOutline() {
    if (outline) outline.remove();
    outline = null;
    if (area.kind === STADT) {
      navDeep = false;
      navFocus = null;
      map.fitBounds(L.geoJSON(geo.bezirk).getBounds(), mapPadding());
      if (navOrtsteile) updateNav(true);
      return;
    }
    let feature = null;
    if (area.kind === "ortsteil") feature = geo.ortsteil.features.find((f) => f.properties.ortsteil_bez === area.name);
    if (area.kind === "bezirk") feature = geo.bezirk.features.find((f) => f.properties.bezirk_bez === area.name);
    outline = L.geoJSON(feature || geo.bezirk, { style: { color: "#7c3aed", weight: 2, fillColor: "#c4b5fd", fillOpacity: 0.12 }, interactive: false }).addTo(map);
    map.fitBounds(outline.getBounds(), mapPadding());
  }
  // Gebiete auf der Karte wählen: herausgezoomt die Stadtbezirke als Flächen mit Namen (Klick zoomt hinein und zeigt
  // seine Stadtteile mit Namen), näher die Stadtteile (Klick lädt das Gebiet wie die Auswahl oben). Eigene Ebene unter
  // Plänen, Baustellen und Punkten; die Namen liegen in der Ebene der Tooltips und fangen keine Klicks ab.
  // Farbstärke der Flächen: Vorlagen der letzten zwölf Monate (index.json, pipeline/gebietszahlen.py) in fünf Stufen,
  // als lila Verlauf (SVG-Verläufe in der Ebene „gebiete“). Beim Überfahren: heller Glaseffekt (weißer Verlauf, Rand, Schein).
  const RAMP = [[262, 92, 0.3], [262, 82, 0.4], [264, 70, 0.5], [266, 58, 0.58], [268, 46, 0.66]];
  const klass = (n, br) => br.filter((b) => n >= b).length;
  const step = (k) => `url(#nav-c${k})`;
  const NAV_LINE = { color: "#6d28d9", weight: 1, opacity: 0.4, fillOpacity: 1 };
  const BZ_LINE = { color: "#6d28d9", weight: 2, opacity: 0.7, fillOpacity: 1 };
  const GLASS = { color: "#ffffff", weight: 2.5, opacity: 1, fillColor: "url(#nav-glass)", fillOpacity: 1 };
  const navRenderer = L.svg({ pane: "gebiete", padding: 0.3 });
  // Farbverläufe, sobald das SVG da ist: beim Start mit ?gebiet= hat die Karte bei initNav noch keine Ansicht, Leaflet
  // legt die Ebene erst danach an und updateNav lief schon (Code-Prüfung 24.10.2026: Flächen ohne Füllung)
  navRenderer.on("add", () => navDefs());
  let otBreaks = [], bzBreaks = [];
  function navDefs() {
    const svg = navRenderer._container;
    if (!svg || svg.querySelector("#nav-glass")) return;
    const stops = (list) => list.map(([o, c, a]) => `<stop offset="${o}" stop-color="${c}" stop-opacity="${a}"/>`).join("");
    const grads = RAMP.map(([h, l, a], k) => `<linearGradient id="nav-c${k}" x1="0" y1="0" x2="1" y2="1">${stops([[0, `hsl(${h},80%,${l + 6}%)`, a], [1, `hsl(${h + 6},65%,${l - 8}%)`, a * 0.8]])}</linearGradient>`).join("");
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `${grads}<linearGradient id="nav-glass" x1="0" y1="0" x2="0.6" y2="1">${stops([[0, "#ffffff", 0.62], [0.45, "#ffffff", 0.3], [1, "#ede9fe", 0.22]])}</linearGradient>
      <filter id="nav-glow" x="-15%" y="-15%" width="130%" height="130%"><feGaussianBlur in="SourceAlpha" stdDeviation="5" result="b"/>
        <feFlood flood-color="#ffffff" flood-opacity="0.9"/><feComposite in2="b" operator="in" result="g"/>
        <feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;
    svg.insertBefore(defs, svg.firstChild);
  }
  // Kontextdaten je Stadtteil (kontext.json, pipeline/kontext.py): Einordnung, kein Urteil; alle Werte abgeleitet.
  // Gefärbt werden nur Anteile und Mittelwerte – Zahlen wie Kitas oder Haltestellen bilden vor allem die Größe ab.
  const KONTEXT_FARBE = { unter_18: "Anteil unter 18 Jahren", ab_65: "Anteil ab 65 Jahren", miete: "Nettokaltmiete (Zensus 2022)",
    bodenrichtwert: "Bodenrichtwert Wohnbauland", hitze: "Hitze: dringender Handlungsbedarf", ueberschwemmung: "Im Überschwemmungsgebiet",
    wahlbeteiligung: "Wahlbeteiligung Ratswahl 2025" };
  const KONTEXT_STEP = { miete: 0.1, bodenrichtwert: 10 };
  const kKey = (m) => (m || "").startsWith("kontext-") ? m.slice(8) : null;
  function kFmt(key, v) {
    if (v == null) return "–";
    const unit = kontext.meta.kennzahlen[key].einheit;
    if (unit === "%") return `${Number(v).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;
    if (unit === "€/m²") return `${Number(v).toLocaleString("de-DE", { minimumFractionDigits: key === "miete" ? 2 : 0, maximumFractionDigits: 2 })} €/m²`;
    return de(v);
  }
  // Wert eines Gebiets aus index.json (Stadtteile tragen stadtbezirk, Stadtbezirke nicht)
  const kValue = (info, key) => ((info.stadtbezirk ? kontext.ortsteile : kontext.bezirke)[info.name] || {})[key] ?? null;
  // Stufen nach Quintilen der Stadtteile, gerundet (Prozent ganz, Miete 0,1 €, Bodenrichtwert 10 €); gleich für Stadtbezirke
  function kBreaks(key) {
    const v = Object.values(kontext.ortsteile).map((o) => o[key]).filter((x) => x != null).sort((a, b) => a - b);
    const st = KONTEXT_STEP[key] || 1;
    const br = [0.2, 0.4, 0.6, 0.8].map((q) => Math.round(Math.ceil(v[Math.floor(q * (v.length - 1))] / st) * st * 10) / 10);
    return [...new Set(br)].filter((b) => b > 0);   // keine Klasse „unter 0 %“ (viele Stadtteile ohne Überschwemmungsgebiet)
  }
  // Tabellenzelle; beim Bodenrichtwert der Anteil der Einwohner in einer Zone, wenn viele außerhalb wohnen
  // (Misch- und Kerngebiete ohne Zone für Wohnbauland; Schwelle aus kontext.json)
  function kCell(key, o) {
    const v = kFmt(key, o[key]), cov = o.bodenrichtwert_abdeckung, ab = kontext.meta.bodenrichtwert_hinweis_ohne_zone;
    const ohne = kontext.meta.kennzahlen[key]?.ohne_wert;
    if (o[key] == null && ohne && o.einwohner >= kontext.meta.mindest_einwohner) return `${v}<br><span class="kontext-note">${esc(ohne)}</span>`;
    if (key !== "bodenrichtwert" || o[key] == null || cov == null || ab == null || 100 - cov < ab) return v;
    return `${v}<br><span class="kontext-note">gilt für ${Math.round(cov)} % der Einwohner, die übrigen wohnen außerhalb von Zonen für Wohnbauland</span>`;
  }
  // fehlender Wert: Grund laut kontext.json (z. B. „ohne eigenen Stimmbezirk“), sonst die Mindestgröße
  const kOhne = (key) => `keine Angabe (${esc(kontext.meta.kennzahlen[key]?.ohne_wert || `unter ${de(kontext.meta.mindest_einwohner)} Einwohnern`)})`;
  // „8,30 bis unter 8,90 €/m²“: die Einheit nur einmal
  const kNum = (key, v) => kFmt(key, v).replace(/\s?(%|€\/m²)$/, "");
  const kRanges = (br, key) => [0, ...br].map((lo, k) => (k === 0 ? `unter ${kFmt(key, br[0])}` : k === br.length ? `ab ${kFmt(key, lo)}`
    : `${kNum(key, lo)} bis unter ${kFmt(key, br[k])}`));
  function kQuelle(key) {
    const d = kontext.meta.kennzahlen[key], q = kontext.meta.quellen[d.quelle] || {};
    return { ...d, q, stand: q.stand ? (q.stand.length === 10 ? fmtDate(q.stand) : q.stand) : "" };
  }
  // Steckbrief in der Liste: alle Kennzahlen des Gebiets neben dem Stadtbezirk (Stadtteil) bzw. ganz Köln (Stadtbezirk)
  function fillKontext() {
    const box = $("#kontext-box");
    if (!box) return;
    const own = kontext && area && (area.kind === "ortsteil" ? kontext.ortsteile[area.name] : area.kind === "bezirk" ? kontext.bezirke[area.name] : null);
    if (!own) { box.hidden = true; return; }
    const bez = area.kind === "ortsteil" ? areaBezirk() : null;
    const cmp = bez ? kontext.bezirke[bez] : kontext.stadt, cmpName = bez ? `Stadtbezirk ${bez}` : "ganz Köln";
    const klein = own.einwohner < kontext.meta.mindest_einwohner;
    const rows = (kontext.meta.reihenfolge || Object.keys(kontext.meta.kennzahlen)).map((k) => `<tr><th scope="row">${esc(kontext.meta.kennzahlen[k].titel)}</th>
      <td>${kCell(k, own)}</td><td>${kCell(k, cmp)}</td></tr>`).join("");
    const quellen = Object.values(kontext.meta.quellen).map((q) => `<li>${safeUrl(q.url) ? `<a href="${safeUrl(q.url)}">${esc(q.titel)}</a>` : esc(q.titel)}
      – ${esc(q.lizenz)}${q.stand ? `, Stand ${esc(q.stand.length === 10 ? fmtDate(q.stand) : q.stand)}` : ""}${q.uebergang ? ` (${esc(q.uebergang)})` : ""}</li>`).join("");
    const methoden = (kontext.meta.reihenfolge || Object.keys(kontext.meta.kennzahlen)).map((k) => kontext.meta.kennzahlen[k]).map((d) => `<li><strong>${esc(d.titel)}:</strong> ${esc(d.methode)}</li>`).join("");
    box.innerHTML = `<summary>Zahlen zu ${esc(area.name)}<span class="derived">abgeleitet</span></summary>
      <p class="hint">Zur Einordnung der Vorlagen, kein Urteil über das Gebiet. Alle Werte sind auf ${area.kind === "ortsteil" ? "Stadtteile" : "Stadtbezirke"} umgerechnet; Stichtage verschieden.${klein ? ` Unter ${de(kontext.meta.mindest_einwohner)} Einwohnern keine Anteile und Mittelwerte.` : ""}</p>
      <table class="kontext-table"><thead><tr><th scope="col">Kennzahl</th><th scope="col">${esc(area.name)}</th><th scope="col">${esc(cmpName)}</th></tr></thead>
      <tbody>${rows}</tbody></table>
      ${anliegenSteckbrief(bez)}
      <details class="acc"><summary>Quellen und Methode</summary><div><ul>${quellen}</ul><ul>${methoden}</ul></div></details>`;
    box.hidden = false;
  }
  // Mängelmelder (anliegen.json, pipeline/anliegen.py): Meldungen der Einwohnerschaft der letzten 90 Tage nach den
  // Gruppen der Stadt, getrennt von den Kennzahlen und den Vorlagen; kleine Werte als „unter 3“, keine Einzelmeldungen
  function anliegenSteckbrief(bez) {
    if (!anliegen) return "";
    const own = (area.kind === "ortsteil" ? anliegen.ortsteile : anliegen.bezirke)[area.name] || null;   // fehlt: keine Meldung
    const cmp = bez ? anliegen.bezirke[bez] : anliegen.stadt, cmpName = bez ? `Stadtbezirk ${bez}` : "ganz Köln";
    const m = anliegen.meta, num = (v) => (v == null ? "unter 3" : typeof v === "number" ? de(v) : esc(v));
    const rows = [...m.gruppen, "gesamt"].map((g) => `<tr><th scope="row">${g === "gesamt" ? "Zusammen" : esc(g)}</th>
      <td>${num((own || {})[g])}</td><td>${num((cmp || {})[g])}</td></tr>`).join("");
    const teil = m.unvollstaendig_vor ? ` Aufgezeichnet seit ${fmtDate(m.unvollstaendig_vor)}; frühere Meldungen nur, soweit sie an diesem Tag noch öffentlich waren.` : "";
    return `<section class="anliegen" aria-labelledby="anliegen-h"><h4 id="anliegen-h">Meldungen im Mängelmelder</h4>
      <p class="hint">${esc(m.hinweis)} Gezählt: ${fmtDate(m.von)} bis ${fmtDate(m.bis)} (${m.tage} Tage).${teil}</p>
      <table class="kontext-table"><thead><tr><th scope="col">Gruppe der Stadt</th><th scope="col">${esc(area.name)}</th><th scope="col">${esc(cmpName)}</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="hint">Quelle: <a href="${safeUrl(m.url)}">${esc(m.titel)}</a> – ${esc(m.lizenz.replace(/\s*\(.*\)$/, ""))}, Abruf ${fmtDate(m.abruf)}; nur Kategorie, Tag, Stadtteil und Status übernommen.</p></section>`;
  }
  // Vorgang: zwei bis drei Kennzahlen passend zum (abgeleiteten) Thema, nur bei genau einem Stadtteil (eigene Ortsbezüge)
  const KONTEXT_THEMA = { bauen: ["bodenrichtwert", "miete"], soziales: ["miete", "ab_65", "unter_18"],
    bildung: ["unter_18", "kitas", "kita_plaetze_ue3"], kinder: ["unter_18", "kitas", "kita_plaetze_u3"],
    verkehr: ["haltestellen", "einwohner"], umwelt: ["hitze", "ueberschwemmung"] };
  function kontextVorgang(p) {
    if (!kontext) return "";
    const own = p.locations.filter((l) => l.method !== "vererbt");
    const ots = [...new Set(own.map((l) => l.ortsteil).filter(Boolean))];
    if (ots.length !== 1 || !kontext.ortsteile[ots[0]]) return "";
    const ot = ots[0], bez = (kontext.stadtbezirk_je_ortsteil || {})[ot];
    if (!bez || own.some((l) => l.stadtbezirk && l.stadtbezirk !== bez)) return "";   // Ortsbezüge in einem anderen Stadtbezirk
    const keys = [...new Set((p.themes || []).flatMap((t) => KONTEXT_THEMA[t.theme] || []))].slice(0, 3);
    const v = kontext.ortsteile[ot], b = kontext.bezirke[bez] || {};
    if (!keys.some((k) => v[k] != null)) return "";
    const rows = keys.map((k) => `<tr><th scope="row">${esc(kontext.meta.kennzahlen[k].titel)}</th><td>${kCell(k, v)}</td><td>${kCell(k, b)}</td></tr>`).join("");
    const qs = [...new Set(keys.map((k) => kontext.meta.kennzahlen[k].quelle))].map((q) => kontext.meta.quellen[q]).filter(Boolean)
      .map((q) => `${esc(q.titel)} (${esc(q.lizenz)}${q.stand ? `, Stand ${esc(q.stand.length === 10 ? fmtDate(q.stand) : q.stand)}` : ""})`).join("; ");
    return `<section class="kontext-vorgang" aria-labelledby="kontext-h"><h4 id="kontext-h">Zum Stadtteil ${esc(ot)} <span class="derived">abgeleitet</span></h4>
      <table class="kontext-table"><thead><tr><th scope="col">Kennzahl</th><th scope="col">${esc(ot)}</th><th scope="col">Stadtbezirk ${esc(bez)}</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="hint">Einordnung, kein Beleg für die Vorlage und kein Urteil über den Stadtteil. Auswahl nach dem abgeleiteten Thema; Werte auf Stadtteile umgerechnet.${v.einwohner < kontext.meta.mindest_einwohner ? ` Unter ${de(kontext.meta.mindest_einwohner)} Einwohnern keine Anteile und Mittelwerte.` : ""} Quellen: ${qs}.</p></section>`;
  }
  // Stufengrenzen: Stadtteile nach Quintilen, Stadtbezirke in gleichen Abständen bis zum Höchstwert
  function quintiles(values) {
    const v = [...values].sort((a, b) => a - b);
    return [...new Set([0.2, 0.4, 0.6, 0.8].map((q) => v[Math.floor(q * (v.length - 1))] + 1))];
  }
  const ranges = (br) => [0, ...br].map((lo, k) => (k === br.length ? `ab ${de(lo)}` : `${de(lo)}–${de(br[k] - 1)}`));
  // Anteile in Prozent: Grenzen auf ganze Prozent gerundet
  function shareBreaks(values, quant) {
    const v = values.filter((x) => x != null).sort((a, b) => a - b);
    if (!v.length) return [];
    const br = quant ? [0.2, 0.4, 0.6, 0.8].map((q) => Math.ceil(v[Math.floor(q * (v.length - 1))]))
      : [0.2, 0.4, 0.6, 0.8].map((q) => Math.ceil(q * v[v.length - 1]));
    return [...new Set(br.filter((b) => b > 0))];
  }
  const shareRanges = (br) => [0, ...br].map((lo, k) => (k === br.length ? `ab ${pct(lo)}` : `${pct(lo)} bis unter ${pct(br[k])}`));
  function navBreaks() {
    if (kKey(navMetric)) {
      otBreaks = bzBreaks = kBreaks(kKey(navMetric));
    } else if (!navMetric) {
      otBreaks = quintiles(index.ortsteile.map((o) => o.jahr || 0));
      const maxBz = Math.max(1, ...index.bezirke.map((b) => b.jahr || 0));
      bzBreaks = [0.2, 0.4, 0.6, 0.8].map((q) => Math.round(q * maxBz) + 1);
    } else {
      otBreaks = shareBreaks(index.ortsteile.map(metricValue), true);
      bzBreaks = shareBreaks(index.bezirke.map(metricValue), false);
    }
  }
  // Zahl im Hinweis beim Überfahren und in der Beschriftung
  function navTip(info, scope) {
    if (!navMetric && vorschau) return '<span class="nav-dim">noch keine Ratsvorlagen (Vorschau)</span>';
    if (!navMetric) return `<span class="nav-big">${de(info.jahr)}</span> Vorlagen in den letzten 12 Monaten
      <br><span class="nav-dim">${de(scope === "bz" ? info.alle : info.count)} insgesamt</span>${fact(info.auffaellig)}`;
    const kk = kKey(navMetric);
    if (kk) {
      const v = kValue(info, kk), d = kQuelle(kk), b = scope === "ot" ? kontext.bezirke[info.stadtbezirk] : null;
      if (v == null) return `${esc(d.titel)}: <span class="nav-dim">${kOhne(kk)}</span>`;
      return `<span class="nav-big">${kFmt(kk, v)}</span> ${esc(d.titel)}
        <br><span class="nav-dim">${b ? `Stadtbezirk ${esc(info.stadtbezirk)} ${kFmt(kk, b[kk])} · ` : ""}ganz Köln ${kFmt(kk, kontext.stadt[kk])} · Stand ${esc(d.stand)} · abgeleitet</span>`;
    }
    const label = esc(THEMES[navMetric]), bonn = (index.zahlen?.themen_bonn || {})[navMetric] || 0;
    if (!info.themen) return `${label}: <span class="nav-dim">zu wenige Vorlagen für einen Anteil (unter ${de(index.zahlen?.themen_min || 20)})</span>`;
    const [n, share] = info.themen[navMetric] || [0, 0];
    return `<span class="nav-big">${pct(share)}</span> der Vorlagen: ${label}
      <br><span class="nav-dim">${de(n)} von ${de(scope === "bz" ? info.alle : info.count)} · ganz Köln ${pct(bonn)} · Themen abgeleitet</span>`;
  }
  const navNumber = (info) => (kKey(navMetric) ? kFmt(kKey(navMetric), kValue(info, kKey(navMetric)))
    : !navMetric ? (vorschau ? "" : de(info.jahr)) : info.themen ? pct((info.themen[navMetric] || [0, 0])[1]) : "–");
  const otInfo = (l) => index.ortsteile.find((o) => o.name === l.feature.properties.ortsteil_bez) || {};
  const bzInfo = (l) => index.bezirke.find((b) => b.name === l.feature.properties.bezirk_bez) || {};
  // Themenebene: statt der Zahl der Vorlagen der Anteil eines Themas an allen Vorlagen des Gebiets seit 2019
  // (index.json, gebietszahlen.theme_shares; Themen abgeleitet); unter der Mindestzahl grau
  // navDefault: Färbung ohne Angabe im Link (sonst Zahl der Vorlagen, in der Vorschau die erste angebotene Kennzahl)
  let navMetric = "", navDefault = "";
  const NAV_NONE = "hsl(240, 6%, 82%)";
  const metricValue = (info) => (kKey(navMetric) ? kValue(info, kKey(navMetric))
    : !navMetric ? info.jahr || 0 : info.themen ? (info.themen[navMetric] || [0, 0])[1] : null);
  const PROZENT = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
  const pct = (v) => `${PROZENT.format(Number(v))} %`;
  const navFill = (info, br) => { const v = metricValue(info); return v == null ? NAV_NONE : step(klass(v, br)); };
  const fact = (a) => (a ? `<br><span class="nav-dim">Auffällig häufig: ${esc(a.label)} (${a.anteil} % hier, ${a.anteil_bonn} % in ganz Köln)</span>` : "");
  const glassOn = (layer) => { layer.setStyle(GLASS); layer.bringToFront(); layer.getElement()?.setAttribute("filter", "url(#nav-glow)"); };
  const glassOff = (layer, style) => { layer.setStyle(style); layer.getElement()?.removeAttribute("filter"); };
  const bzStyle = (layer) => ({ ...BZ_LINE, fillColor: navFill(bzInfo(layer), bzBreaks) });
  let navBezirke = null, navOrtsteile = null, bonnBounds = null, navDeep = false, navFocus = null, navLabels = null, navMode = null, navLegend = null;
  const ZAHL = new Intl.NumberFormat("de-DE");
  const de = (n) => ZAHL.format(Number(n || 0));
  // Zoomstufe, bei der ganz Köln ins freie Kartenfeld passt; bis dahin sind die Stadtbezirke anklickbar
  function wholeZoom() {
    const p = mapPadding();
    return map.getBoundsZoom(bonnBounds, false, L.point(p.paddingTopLeft[0] + p.paddingBottomRight[0], p.paddingTopLeft[1] + p.paddingBottomRight[1]));
  }
  function chooseArea(value) {
    navDeep = false;
    navFocus = null;
    updateNav();
    range = null;
    if (tl) tl.reset();
    loadArea(value);
  }
  const otStyle = (layer) => {
    const inFocus = navFocus && layer.feature.properties.bezirk_bez === navFocus;
    return { ...NAV_LINE, opacity: inFocus ? 0.7 : 0.4, fillOpacity: navFocus && !inFocus ? 0.35 : 1, fillColor: navFill(otInfo(layer), otBreaks) };
  };
  function initNav() {
    if (!index) return;
    map.createPane("gebiete").style.zIndex = 350;
    navOrtsteile = L.geoJSON(geo.ortsteil, {
      pane: "gebiete", renderer: navRenderer, style: NAV_LINE,
      filter: (f) => index.ortsteile.some((o) => o.name === f.properties.ortsteil_bez),
      onEachFeature(f, layer) {
        const o = index.ortsteile.find((x) => x.name === f.properties.ortsteil_bez);
        const current = () => area && area.kind === "ortsteil" && area.key === o.slug;
        layer.bindTooltip(() => `<strong>${esc(o.name)}</strong><br>${navTip(o, "ot")}
          <br><span class="nav-dim">${current() ? "gewählt" : "Klick zeigt den Stadtteil"}</span>`, { sticky: true, className: "nav-tip" });
        layer.on({ mouseover: () => glassOn(layer), mouseout: () => glassOff(layer, otStyle(layer)) });
        layer.on("click", () => { if (!current()) chooseArea(`ortsteil:${o.slug}`); });
      },
    });
    navBezirke = L.geoJSON(geo.bezirk, {
      pane: "gebiete", renderer: navRenderer, style: BZ_LINE,
      onEachFeature(f, layer) {
        const name = f.properties.bezirk_bez;
        const n = index.ortsteile.filter((o) => o.stadtbezirk === name).length;
        const b = bzInfo(layer);
        layer.bindTooltip(() => `<strong>Stadtbezirk ${esc(name)}</strong> <span class="nav-dim">· ${n} Stadtteile</span><br>${navTip(b, "bz")}
          <br><span class="nav-dim">Klick zeigt die Stadtteile</span>`, { sticky: true, className: "nav-tip" });
        layer.on({ mouseover: () => glassOn(layer), mouseout: () => glassOff(layer, bzStyle(layer)) });
        layer.on("click", () => {
          navDeep = true; // die Stadtteile anbieten, auch wenn der Bezirk ganz Köln ausfüllt
          navFocus = name;
          map.fitBounds(layer.getBounds(), mapPadding());
          updateNav(true);
        });
      },
    });
    bonnBounds = navBezirke.getBounds();
    // angeboten: Themenanteile (nicht in der Vorschau, dort alle ohne Vorlagen) und Kennzahlen, die kontext.json enthält
    // (die Wahlbeteiligung fehlt ohne Wahldaten; ihre Wahl brach die Legende ab)
    const themes = !vorschau && index.zahlen?.themen_bonn ? Object.entries(THEMES) : [];
    const kx = kontext ? Object.entries(KONTEXT_FARBE).filter(([k]) => kontext.meta.kennzahlen[k]) : [];
    // Vorschau: die Zahl der Vorlagen ist überall 0; Vorgabe ist die erste angebotene Kennzahl
    navDefault = navMetric = vorschau && kx.length ? `kontext-${kx[0][0]}` : "";
    const f = new URLSearchParams(location.search).get("flaechen");
    if (themes.length && Object.hasOwn(THEMES, f || "")) navMetric = f;
    if (kx.some(([k]) => `kontext-${k}` === f)) navMetric = f;
    navBreaks();
    navBezirke.eachLayer((l) => l.setStyle(bzStyle(l)));
    // Legende der Flächen: Stufen der jeweils sichtbaren Ebene; oben im Stapel der Legenden, eingeklappt
    navLegend = L.DomUtil.create("details", "nav-legend");
    navLegend.hidden = vorschau && !navMetric;   // Vorschau ohne Kennzahlen: keine Färbung, also keine Legende
    const opt = (k, v) => `<option value="${k}"${k === navMetric ? " selected" : ""}>${esc(v)}</option>`;
    navLegend.innerHTML = `<summary></summary>${themes.length || kx.length ? `<label class="nav-metric">Flächen färben nach
      <select id="nav-metric">${vorschau ? "" : '<option value="">Zahl der Vorlagen (12 Monate)</option>'}
      ${themes.length ? `<optgroup label="Anteil eines Themas (seit 2019)">${themes.map(([k, v]) => opt(k, v)).join("")}</optgroup>` : ""}
      ${kx.length ? `<optgroup label="Zahlen zum Gebiet (abgeleitet)">${kx.map(([k, v]) => opt(`kontext-${k}`, v)).join("")}</optgroup>` : ""}</select></label>` : ""}
      <div class="nav-legend-body"></div>`;
    navLegend.querySelector("#nav-metric")?.addEventListener("change", (e) => {
      navMetric = e.target.value;
      navBreaks();
      navBezirke.eachLayer((l) => l.setStyle(bzStyle(l)));
      updateNav(true);
      syncUrl();
    });
    mapStack.prepend(navLegend);
    map.on("zoomend", () => updateNav());
    updateNav();
  }
  // Schwerpunkt der größten Teilfläche (Leaflets getCenter nimmt die erste, bei mehrteiligen Flächen oft eine kleine)
  function labelPoint(layer) {
    const rings = [];
    const walk = (x) => (x.length && x[0] instanceof L.LatLng ? rings.push(x) : x.forEach(walk));
    walk(layer.getLatLngs());
    let best = null, bestA = 0;
    for (const r of rings) {
      let a = 0, cx = 0, cy = 0;
      for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
        const f = r[j].lng * r[i].lat - r[i].lng * r[j].lat;
        a += f; cx += (r[j].lng + r[i].lng) * f; cy += (r[j].lat + r[i].lat) * f;
      }
      if (Math.abs(a) > bestA) { bestA = Math.abs(a); best = L.latLng(cy / (3 * a), cx / (3 * a)); }
    }
    return best || layer.getCenter();
  }
  // Namen als ruhende Beschriftung: Stadtbezirke in der Übersicht, Stadtteile des gewählten Bezirks
  // Bezirksnamen in die Mitte seiner Stadtteile, gewichtet nach Zahl der Vorlagen (der Bezirk Bonn reicht bis Röttgen,
  // sein geometrischer Schwerpunkt läge am Venusberg)
  function bezirkPoint(layer) {
    const name = layer.feature.properties.bezirk_bez;
    let w = 0, lat = 0, lng = 0;
    navOrtsteile.eachLayer((l) => {
      if (l.feature.properties.bezirk_bez !== name) return;
      const n = (index.ortsteile.find((o) => o.name === l.feature.properties.ortsteil_bez) || {}).count || 0, c = labelPoint(l);
      w += n; lat += c.lat * n; lng += c.lng * n;
    });
    return w ? L.latLng(lat / w, lng / w) : labelPoint(layer);
  }
  function labels(layers, cls) {
    if (navLabels) navLabels.remove();
    navLabels = L.layerGroup(layers.map((l) => L.tooltip({ permanent: true, direction: "center", className: `nav-label ${cls}`, interactive: false })
      .setLatLng(l.feature.properties.ortsteil_bez ? labelPoint(l) : bezirkPoint(l))
      .setContent(`${esc(l.feature.properties.ortsteil_bez || l.feature.properties.bezirk_bez)}<span class="nav-n">${navNumber(l.feature.properties.ortsteil_bez ? otInfo(l) : bzInfo(l))}</span>`))).addTo(map);
  }
  function updateNav(force) {
    if (!navOrtsteile) return;
    const z = map.getZoom(), whole = wholeZoom();
    if (z < whole) { navDeep = false; navFocus = null; }
    const mode = !navDeep && z <= whole ? "bezirke" : navFocus ? "fokus:" + navFocus : "ortsteile";
    if (mode === navMode && !force) return;
    navMode = mode;
    const far = mode === "bezirke";
    (far ? navOrtsteile : navBezirke).remove();
    (far ? navBezirke : navOrtsteile).addTo(map);
    navDefs();
    navOrtsteile.eachLayer((l) => l.setStyle(otStyle(l)));
    if (navLegend) {
      const z = index.zahlen || {}, br = far ? bzBreaks : otBreaks;
      const kk = kKey(navMetric), kd = kk && kQuelle(kk);
      navLegend.querySelector("summary").textContent = kk ? kd.titel : navMetric ? `Anteil: ${THEMES[navMetric]}` : "Vorlagen der letzten 12 Monate";
      navLegend.querySelector(".nav-legend-body").innerHTML = kk
        ? `<ol class="nav-ramp">${kRanges(br, kk).map((r, k) => `<li><span class="nav-sw nav-sw${k}" aria-hidden="true"></span>${r}</li>`).join("")}
            <li><span class="nav-sw nav-sw-none" aria-hidden="true"></span>${kOhne(kk)}</li></ol>
          <p>Je ${far ? "Stadtbezirk" : "Stadtteil"}, Stufen nach den Werten der Stadtteile; ganz Köln ${kFmt(kk, kontext.stadt[kk])}. ${esc(kd.methode)}.
            Quelle: ${esc(kd.q.titel || "")} (${esc(kd.q.lizenz || "")}), Stand ${esc(kd.stand)}${kd.q.uebergang ? `; ${esc(kd.q.uebergang)}` : ""}. <span class="derived">abgeleitet</span> Zur Einordnung, kein Urteil über das Gebiet.</p>`
        : navMetric
        ? `<ol class="nav-ramp">${shareRanges(br).map((r, k) => `<li><span class="nav-sw nav-sw${k}" aria-hidden="true"></span>${r}</li>`).join("")}
            <li><span class="nav-sw nav-sw-none" aria-hidden="true"></span>zu wenige Vorlagen (unter ${de(z.themen_min || 20)})</li></ol>
          <p>Anteil der Vorlagen mit diesem Thema an allen Vorlagen mit Ortsbezug je ${far ? "Stadtbezirk" : "Stadtteil"}; in ganz Köln ${pct((z.themen_bonn || {})[navMetric] || 0)}. <span class="derived">abgeleitet</span> Themen aus Amt, Ausschuss und Stichwort; eine Vorlage kann mehrere Themen haben.</p>`
        : `<ol class="nav-ramp">${ranges(br).map((r, k) => `<li><span class="nav-sw nav-sw${k}" aria-hidden="true"></span>${r}</li>`).join("")}</ol>
          <p>Je ${far ? "Stadtbezirk" : "Stadtteil"}${z.seit ? `, ${fmtDate(z.seit)} bis ${fmtDate(z.bis)}` : ""}. Gezählt werden Vorlagen mit Ortsbezug im Gebiet (Verortung teils abgeleitet); mehr als die Hälfte aller Vorlagen hat keinen. „Auffällig häufig“ beim Überfahren: Thema, das im Gebiet deutlich häufiger vorkommt als in ganz Köln (abgeleitet).</p>`;
    }
    if (far) labels(navBezirke.getLayers(), "nav-label-bz");
    else if (navFocus) labels(navOrtsteile.getLayers().filter((l) => l.feature.properties.bezirk_bez === navFocus), "nav-label-ot");
    else if (navLabels) { navLabels.remove(); navLabels = null; }
  }
  // CSS-Variablen einmal je Name lesen statt getComputedStyle je Punkt (Ladezeit Schritt 2: rund 120 ms)
  const farben = new Map();
  const color = (c) => {
    if (!farben.has(c)) farben.set(c, getComputedStyle(document.documentElement).getPropertyValue("--" + c).trim());
    return farben.get(c);
  };
  function markerColor(p, l) {
    if (colorBy !== "thema") return color(l.confidence);
    const t = (p.themes || [])[0];
    return t ? THEME_COLOR[t.theme] || NO_THEME : NO_THEME;
  }
  function drawLegend() {
    const rows = colorBy === "thema"
      ? [...Object.entries(THEMES).map(([k, v]) => [THEME_COLOR[k], v]), [NO_THEME, "ohne Thema"]]
      : [[color("hoch"), "Ort gesichert (Koordinate oder eindeutiger Bebauungsplan der Stadt)"], [color("mittel"), "Ort erschlossen (Name im Titel)"], [color("niedrig"), "Ort unsicher (mehrdeutig)"]];
    const punkte = `<summary>Legende: ${colorBy === "thema" ? "Thema" : "Sicherheit des Orts"}</summary><ul>${rows
      .map(([c, t]) => `<li><span class="swatch" style="background:${c}" aria-hidden="true"></span>${esc(t)}</li>`).join("")}</ul>
      ${colorBy === "thema" ? '<p class="hint">Bei mehreren Themen zählt das erste. Themen sind abgeleitet.</p>' : ""}`;
    // Vorschau ohne Ratsvorlagen: keine Punkte, nur die Legenden der eingeschalteten Ebenen (keine eingeschaltet: keine Legende)
    const ebenen = `${planOn ? `<ul><li><span class="swatch swatch-plan" aria-hidden="true"></span>Geltungsbereich eines rechtsverbindlichen Bebauungsplans (Bauleitplanung NRW, IT.NRW)</li></ul>
        ${planIndexUrl() && !vorschau ? '<button type="button" class="btn btn-soft" id="plan-list">Pläne im Gebiet als Liste</button>' : ""}` : ""}
      ${bauOn && bau ? `<ul><li><span class="site-icon site-aktuell" aria-hidden="true"></span>Baustelle der Stadt, laufend</li>
        <li><span class="site-icon site-geplant" aria-hidden="true"></span>Baustelle der Stadt, geplant</li>
        <li><span class="site-icon site-fremd" aria-hidden="true"></span>Baustelle anderer Träger (Versorger, Straßen NRW, Bahn)</li></ul>
        <p class="hint">Termine unverbindlich; ${bau.meta.archiv_beginn ? `Archiv seit ${fmtDate(bau.meta.archiv_beginn)}` : "aktueller Stand, ohne Archiv"}.</p>
        <button type="button" class="btn btn-soft" id="bau-list">Baustellen im Gebiet als Liste</button>` : ""}
      ${kxLegend()}`;
    legendEl.hidden = vorschau && !ebenen.trim();
    legendEl.innerHTML = vorschau ? `<summary>Legende: Ebenen</summary>${ebenen}` : `${punkte}
      ${ebenen}`;
    const b = legendEl.querySelector("#plan-list");
    if (b) b.addEventListener("click", showPlanList);
    const bl = legendEl.querySelector("#bau-list");
    if (bl) bl.addEventListener("click", showSiteList);
  }
  function drawMarkers(list) {
    lastMarkers = list;
    if (legendEl) drawLegend();
    cluster.clearLayers();
    markers.clear();
    const alle = [];
    for (const p of list) {
      const ms = areaLocs(p).filter((l) => (l.level === "strasse" || l.level === "objekt" || l.level === "bebauungsplan") && l.lon != null).map((l) => {
        const m = L.circleMarker([l.lat, l.lon], { ...MARKER, fillColor: markerColor(p, l) })
          .bindTooltip(`${esc(p.reference)} · ${esc(l.name)}`).on("click", () => select(p, true));
        m.baseColor = markerColor(p, l);
        return m;
      });
      for (const m of ms) alle.push(m);
      markers.set(p.reference, ms);
    }
    // gesammelt: die Gruppen werden einmal berechnet statt nach jedem Punkt (Runde 18)
    cluster.addLayers(alle);
    highlight();
  }
  // gewählte Vorlage auf der Karte hervorheben
  function highlight() {
    for (const [ref, ms] of markers) {
      const on = selected && ref === selected.reference;
      ms.forEach((m) => { m.setStyle(on ? { radius: 11, weight: 3, color: "#0f0f14" } : { radius: MARKER.radius, weight: MARKER.weight, color: MARKER.color }); if (on) m.bringToFront(); });
    }
  }

  // --- Liste und Filter ------------------------------------------------------------------------------
  function options(sel, values) {
    const cur = sel.value;
    sel.innerHTML = '<option value="">alle</option>' + values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    if (values.includes(cur)) sel.value = cur;
  }
  function fillFilters() {
    const uniq = (a) => [...new Set(a.filter(Boolean))].sort((x, y) => x.localeCompare(y, "de"));
    options($("#f-type"), uniq(papers.map((p) => p.paper_type)));
    options($("#f-amt"), uniq(papers.map((p) => p.amt)));
    options($("#f-gremium"), uniq(papers.flatMap((p) => p.process.map((s) => s.gremium))));
    fillParties();
  }
  function fillParties() {
    const sel = $("#f-party"), cur = sel.value;
    const list = scope() === STADT && search ? search.parties : [...new Set(papers.flatMap((p) => p.parties || []))];
    // Fraktionen und Gruppen zuerst, dann Koalition, interfraktionell, Einwohner:innen, Verwaltung
    const other = ["Koalition", "interfraktionell", "Einwohner:innen", "Verwaltung"];
    const sorted = [...list.filter((x) => !other.includes(x)).sort((a, b) => a.localeCompare(b, "de")), ...other.filter((x) => list.includes(x))];
    sel.innerHTML = '<option value="">alle</option>' + sorted.map((v) => `<option value="${esc(v)}">${esc(v === "Koalition" ? "Koalition (gemeinsamer Antrag)" : v)}</option>`).join("");
    if (sorted.includes(cur)) sel.value = cur;
  }
  const scope = () => (document.querySelector('input[name="scope"]:checked') || {}).value || "gebiet";
  function loadSearch() {
    if (search || !index) return Promise.resolve(search);
    return (searchLoading ||= fetch(BONN + "suche.json").then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => {
        d.related = new Map(d.rows.map((r) => [r[0], new Set(r[8].map((i) => d.parties[i]))]));
        search = d;
        return d;
      }).catch((err) => { searchLoading = null; $("#count").textContent = `Der Suchindex konnte nicht geladen werden (${err.message}).`; return null; }));
  }
  // Parteien der übergeordneten Vorlage (z. B. Stellungnahme der Verwaltung zu einem Antrag)
  const relatedParties = (ref) => (search && search.related.get(ref)) || new Set();
  function inRange(p) {
    if (!range) return true;
    const [a, b] = range, dim = tl ? tl.dimension() : "vorlage";
    if (dim === "vorlage") return p.date >= a && p.date <= b;
    return p.steps.some((s) => (s.typ === "beratung" || s.typ === "entscheidung") && s.date && s.date >= a && s.date <= b);
  }
  function filtered(withRange = true) {
    const text = $("#f-text").value.trim().toLowerCase(), type = $("#f-type").value, amt = $("#f-amt").value;
    const gremium = $("#f-gremium").value, standF = $("#f-stand").value;
    const theme = $("#f-theme").value, party = $("#f-party").value, rel = $("#f-related").checked;
    const confs = new Set([...document.querySelectorAll("#f-conf input:checked")].map((i) => i.value));
    return papers.filter((p) => (!type || p.paper_type === type) && (!amt || p.amt === amt) &&
      (!theme || (p.themes || []).some((t) => t.theme === theme)) &&
      (!party || (p.parties || []).includes(party) || (rel && relatedParties(p.reference).has(party))) &&
      (!gremium || p.process.some((s) => s.gremium === gremium)) && (!standF || p.stand === standF) &&
      (area.kind === "ohne" || confs.has(bestConfidence(p))) && (!withRange || inRange(p)) &&
      (!text || (p.name + " " + p.reference).toLowerCase().includes(text)));
  }
  function resetFilters() {
    const sc = scope();
    $("#filters").reset();
    document.querySelector(`input[name="scope"][value="${sc}"]`).checked = true;
    $("#f-related-wrap").hidden = true;
    range = null;
    if (tl) tl.reset();
    shown = LIST_STEP;
    render();
    syncUrl();
  }
  function itemHtml(p) {
    const c = bestConfidence(p);
    const conf = area.kind === "ohne" ? "" : `<span class="conf conf-${c}">${CONF[c]}</span>`;
    // Ort nur von der übergeordneten Vorlage übernommen (Folgevorlage ohne eigenen Ortsbezug)
    const own = areaLocs(p);
    const taken = own.length && own.every((l) => l.method === "vererbt") ? '<span class="taken">Ort übernommen</span>' : "";
    return `<li><button type="button" data-ref="${esc(p.reference)}" aria-current="${selected === p}">
      <span class="title">${esc(p.name)}</span>
      <span class="meta"><span>${esc(p.reference)}</span><span>${fmtDate(p.date)}</span><span>${esc(p.paper_type)}</span>
      <span>${esc(p.stand)}</span>${conf}${taken}${themeTags(p.themes)}</span></button></li>`;
  }
  const themeTags = (ts) => (ts || []).slice(0, 2).map((t) => `<span class="theme">${esc(THEMES[t.theme || t])}</span>`).join("");
  // aria-current der Einträge in der Liste (Gebiet: data-ref, ganz Köln: data-gref) immer als "true" oder "false";
  // ohne gewählte Vorlage "false" (bis Runde 18 stand an Suchtreffern "null"; unbekannte Werte gelten in ARIA als „true“)
  const markCurrent = (ref) => document.querySelectorAll(".papers button[data-ref], .papers button[data-gref]")
    .forEach((b) => b.setAttribute("aria-current", String((b.dataset.ref ?? b.dataset.gref) === ref)));

  // Suche über ganz Köln: Treffer aus dem Index, Öffnen lädt das Gebiet der Vorlage
  // Suche im Text der Dokumente: in Bonn über die Volltextsuche von OParl-Lite (machdenstaat). Für Köln gibt es keinen
  // solchen Dienst; die Funktion bleibt abgeschaltet (LITE = null), die Schaltfläche ist in index.html ausgeblendet.
  const LITE = null;
  const DOC_QUERY = "query($q:String!,$o:Int){ fileFullTextSearch(query:$q, limit:100, offset:$o){ totalCount pageInfo { hasNextPage } items { file { papers { reference } } } } }";
  const DOC_PAGES = 3;
  let docHits = null;
  async function docSearch(q) {
    if (!LITE) throw new Error("Suche im Text der Dokumente für Köln nicht verfügbar");
    const refs = new Set();
    let total = 0;
    for (let page = 0; page < DOC_PAGES; page++) {
      const r = await fetch(LITE, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: DOC_QUERY, variables: { q, o: page * 100 } }) });
      const d = (await r.json()).data.fileFullTextSearch;
      total = d.totalCount;
      d.items.forEach((i) => i.file.papers.forEach((p) => refs.add(p.reference)));
      if (!d.pageInfo.hasNextPage) break;
    }
    return { q: q.toLowerCase(), refs, total, more: total > DOC_PAGES * 100 };
  }
  async function runDocSearch() {
    const q = $("#q").value.trim() || $("#f-text").value.trim();
    const status = $("#doc-status");
    if (q.length < 3) { status.textContent = "Bitte mindestens drei Zeichen eingeben."; return; }
    status.textContent = "Suche im Text der Dokumente …";
    try {
      docHits = await docSearch(q);
      if (index && scope() !== STADT) setScope(STADT);
      if (!search) await loadSearch();
      shown = LIST_STEP;
      render();
      const n = search.rows.filter((r) => docHits.refs.has(r[0])).length;
      status.textContent = `${n === 0 ? "Keine Vorlage erwähnt" : n === 1 ? "1 Vorlage erwähnt" : `${n} Vorlagen erwähnen`} „${q}“ in einem Dokument${docHits.more ? ` (die ersten ${DOC_PAGES * 100} von ${docHits.total} Dokumenttreffern)` : ""}.`;
    } catch (e) {
      docHits = null;
      status.textContent = "Die Suche im Text der Dokumente ist gerade nicht erreichbar.";
    }
  }
  // nurListe: „Weitere … anzeigen“ erweitert nur die Liste; Treffer, Karte und Zeitleiste bleiben (Runde 18: bisher
  // wurden alle Punkte bei jedem Klick neu gezeichnet)
  function renderGlobal(nurListe) {
    const text = $("#f-text").value.trim().toLowerCase(), type = $("#f-type").value, standF = $("#f-stand").value;
    const doc = docHits && docHits.q === text ? docHits.refs : null;
    const inTitle = (r) => (r[1] + " " + r[0]).toLowerCase().includes(text);
    const theme = search.themes.findIndex((t) => t.id === $("#f-theme").value), party = search.parties.indexOf($("#f-party").value);
    const rel = $("#f-related").checked, ti = search.types.indexOf(type), si = search.stands.indexOf(standF);
    const rows = search.rows.filter((r) => (!type || r[3] === ti) && (!standF || r[4] === si) && (theme < 0 || r[6].includes(theme)) &&
      (party < 0 || r[7].includes(party) || (rel && r[8].includes(party))) && (!range || (r[2] && r[2] >= range[0] && r[2] <= range[1])) &&
      (!text || inTitle(r) || (doc && doc.has(r[0]))));
    const span = range ? ` · ${fmtDate(range[0])}–${fmtDate(range[1])}` : "";
    const onlyDoc = doc ? rows.filter((r) => !inTitle(r)).length : 0;
    $("#count").textContent = vorschau ? "Ganz Köln: noch keine Ratsvorlagen (Vorschau)"
      : `${rows.length} Treffer in ganz Köln${doc ? `, davon ${onlyDoc} nur im Text der Dokumente` : ""}${span}`;
    let html = rows.slice(0, shown).map((r) => `<li><button type="button" data-gref="${esc(r[0])}" data-area="${esc(search.areas[r[5]].key)}" aria-current="${Boolean(selected && selected.reference === r[0])}">
      <span class="title">${esc(r[1])}</span>
      <span class="meta"><span>${esc(r[0])}</span><span>${fmtDate(r[2])}</span><span>${esc(search.types[r[3]] || "")}</span>
      <span>${esc(search.stands[r[4]])}</span><span class="area-tag">${esc(search.areas[r[5]].name)}</span>${themeTags(r[6].slice(0, 2).map((i) => search.themes[i].id))}${doc && text && !inTitle(r) ? '<span class="doc-tag">im Dokument erwähnt</span>' : ""}</span></button></li>`).join("");
    if (rows.length > shown) html += `<li class="more"><button type="button" class="btn btn-secondary" id="more">Weitere ${Math.min(LIST_STEP, rows.length - shown)} von ${rows.length - shown} anzeigen</button></li>`;
    if (!rows.length && vorschau) html = `<li class="empty-list"><p>${esc(VORSCHAU_LISTE)}</p></li>`;
    else if (!rows.length) html = `<li class="empty-list"><p>Keine Vorlage in ganz Köln passt zu Filtern und Zeitraum.</p><button type="button" class="btn btn-secondary" id="reset-filters">Filter und Zeitraum zurücksetzen</button></li>`;
    $("#papers").innerHTML = html;
    // auf der Karte: die Treffer, die im gerade geladenen Gebiet liegen
    if (!nurListe) {
      const refs = new Set(rows.map((r) => r[0]));
      drawMarkers(papers.filter((p) => refs.has(p.reference)));
    }
    if (openMegaId === "mega-suche") $("#mega-count").textContent = $("#count").textContent;
  }
  async function openGlobal(ref, areaKey) {
    if (!area || `${area.kind}:${area.key}` !== areaKey) await loadArea(areaKey, true);
    const p = papers.find((x) => x.reference === ref);
    if (p) select(p);
  }

  function render(nurListe) {
    $("#f-related-wrap").hidden = !$("#f-party").value;
    $("#more-filters").hidden = scope() === STADT;
    if (scope() === STADT) {
      if (!search) { $("#count").textContent = "Lade den Suchindex für ganz Köln …"; loadSearch().then((d) => d && (fillParties(), render())); return; }
      return renderGlobal(nurListe);
    }
    if ($("#f-party").value && $("#f-related").checked && !search && index) { loadSearch().then((d) => d && render()); }
    const base = filtered(false);
    const list = range ? base.filter(inRange) : base;
    lastList = list;
    const where = area.kind === "ohne" ? `ohne Ortsbezug, ${area.key}` : area.name;
    const span = range ? ` · ${fmtDate(range[0])}–${fmtDate(range[1])}` : "";
    $("#count").textContent = vorschau ? `${area.kind === STADT ? "Ganz Köln" : where}: noch keine Ratsvorlagen (Vorschau)`
      : area.kind === STADT ? OVERVIEW_HINT : `${list.length} von ${papers.length} Vorlagen · ${where}${span}`;
    const active = [$("#f-amt").value, $("#f-gremium").value].filter(Boolean).length +
      (area.kind === "ohne" ? 0 : document.querySelectorAll("#f-conf input:not(:checked)").length);
    $("#active-filters").textContent = active ? ` (${active} aktiv)` : "";
    let html = list.slice(0, shown).map(itemHtml).join("");
    if (list.length > shown) html += `<li class="more"><button type="button" class="btn btn-secondary" id="more">Weitere ${Math.min(LIST_STEP, list.length - shown)} von ${list.length - shown} anzeigen</button></li>`;
    if (!list.length && vorschau) html = `<li class="empty-list"><p>${esc(VORSCHAU_LISTE)}</p></li>`;
    else if (!list.length && area.kind === STADT) html = `<li class="empty-list"><p>Noch kein Gebiet gewählt. Wählen Sie auf der Karte einen Stadtbezirk und einen Stadtteil oder oben ein Gebiet; „in ganz Köln“ sucht über alle Vorlagen.</p></li>`;
    else if (!list.length) html = `<li class="empty-list"><p>Keine Vorlage passt zu Gebiet, Filtern und Zeitraum.</p><button type="button" class="btn btn-secondary" id="reset-filters">Filter und Zeitraum zurücksetzen</button></li>`;
    $("#papers").innerHTML = html;
    if (!nurListe) {
      drawMarkers(list);
      if (tl) tl.setPapers(base);
    }
    if (openMegaId === "mega-suche") $("#mega-count").textContent = $("#count").textContent;
  }
  const renderSoon = debounce(() => { shown = LIST_STEP; render(); }, 200);

  // --- Detail: Prozesslinie mit Evidenzstatus -------------------------------------------------------
  const glossKeys = (t) => (t ? t.split(" - ").map((x) => x.trim()).filter((x) => GLOSSAR[x]) : []);
  function stepHtml(s) {
    const status = s.status;
    const mark = status === "unklar" ? "?" : "";
    const dateLine = s.date ? `${fmtDate(s.date)}${s.date_status === "abgeleitet" ? " · Datum abgeleitet (über die Sitzung)" : ""}` : "";
    const body = [];
    if (s.typ === "initiierung" && s.actors && s.actors.length) body.push(`Eingereicht von ${esc(s.actors.join(", "))} <span class="derived">abgeleitet</span>`);
    if (s.role) body.push(`${esc(s.role)}${s.typ === "entscheidung" ? " (entscheidet)" : ""}${s.number ? ` · TOP ${esc(s.number)}` : ""}`);
    if (s.result) body.push(`Ergebnis: <q>${esc(s.result)}</q>${s.schleife ? " · Schleife" : ""}`);
    if (s.typ === "folgevorlage") body.push(`${esc(s.reference)} – ${esc(s.title)}`);
    if (dateLine) body.push(dateLine);
    if (s.date) body.push(`<button type="button" class="jump" data-date="${esc(s.date)}">in der Zeitleiste zeigen</button>`);
    const box = s.note && (status === "nicht_öffentlich" || status === "unklar" || s.note === "ohne_sitzung")
      ? `<div class="blackbox">${esc(NOTES[s.note])}</div>` : (s.note ? `<div class="hint">${esc(NOTES[s.note])}</div>` : "");
    const cls = s.date_status === "abgeleitet" ? " date-derived" : "";
    const gremium = index && (s.typ === "beratung" || s.typ === "entscheidung") && s.label && s.status !== "nicht_öffentlich";
    const label = s.label && s.label !== STEP_LABEL[s.typ]
      ? ": " + (gremium ? `<button type="button" class="link-btn" data-gremium-name="${esc(s.label)}" title="Zuständigkeit und Besetzung im Reiter Prozesse">${esc(s.label)}</button>` : esc(s.label)) : "";
    return `<li class="step${cls}" data-status="${esc(status)}">
      <span class="mark mark-${esc(status)}" aria-hidden="true">${mark}</span>
      <div class="step-head">${esc(STEP_LABEL[s.typ] || s.typ)}${label}<span class="step-status">${esc(STATUS[status])}</span></div>
      <div class="step-body">${body.join("<br>")}${box}</div></li>`;
  }
  function legend() {
    return `<details class="acc"><summary>Legende Evidenzstatus</summary><div class="legend">${["belegt", "abgeleitet", "nicht_öffentlich", "unklar"]
      .concat("soll").map((s) => `<span><span class="mark mark-${s}" aria-hidden="true">${s === "unklar" ? "?" : ""}</span><strong>${STATUS[s]}</strong> – ${esc(STATUS_TEXT[s] || "")}</span>`).join("")}
      <span class="hint">Linie: durchgezogen = belegt, gestrichelt = abgeleitet, gepunktet = nicht öffentlich oder unklar.</span></div></details>`;
  }
  // Erklärung zum Aufklappen neben einem Begriff im Vorgang: Knopf „?“, ein Satz darunter (Glossar, pipeline/glossar.py)
  let erklN = 0;
  function erkl(begriff, text, anker) {
    if (!text) return "";
    const id = `erkl-${++erklN}`;
    return ` <button type="button" class="erkl-btn" aria-expanded="false" aria-controls="${id}" aria-label="Erklärung: ${esc(begriff)}">?</button>`
      + `<span class="erkl-text" id="${id}" hidden>${esc(text)}${anker ? ` <a href="begriffe/#${esc(anker)}">Mehr unter Begriffe</a>` : ""}</span>`;
  }
  const erklBegriff = (anker, label) => (BEGRIFF[anker] ? erkl(label || BEGRIFF[anker].begriff, BEGRIFF[anker].erklaerung, anker) : "");
  function glossary(p) {
    const keys = [...new Set(p.process.flatMap((s) => [...glossKeys(s.result), ...glossKeys(s.role)]))];
    if (!keys.length) return "";
    return `<details class="acc glossary"><summary>Was bedeuten die Begriffe?</summary><div><dl>${keys
      .map((k) => `<dt>${esc(k)}</dt><dd>${esc(GLOSSAR[k])}</dd>`).join("")}</dl>
      <p class="hint">Erläuterung allgemein; maßgeblich ist das Original. <a href="begriffe/">Alle Begriffe</a></p></div></details>`;
  }
  function reportLink(p) {
    const q = new URLSearchParams({ template: "verortung.yml", title: `Verortung prüfen: ${p.reference}`, drucksache: p.reference, titel: p.name, gebiet: area.name });
    return `${REPO}/issues/new?${q}`;
  }
  const link = (url, text, cls) => { const u = safeUrl(url); return u ? `<a ${cls ? `class="${cls}" ` : ""}href="${u}" target="_blank" rel="noopener">${text}</a>` : ""; };
  // Bebauungspläne: Geltungsbereiche der Stadt (CC0), erst bei Bedarf geladen
  let plansData = null, planLayer = null;
  const loadPlans = () => (plansData ||= loadGeo("bplan").catch(() => ({ features: [] })));
  async function showPlans(p, fit) {
    if (planLayer) { planLayer.remove(); planLayer = null; }
    const withArea = (p.plans || []).filter((x) => x.area);
    if (!withArea.length) return;
    const names = (x) => x.names || [x.nr];  // ältere Exporte ohne names
    const data = await loadPlans();
    if (selected !== p) return;
    const wanted = new Set(withArea.flatMap(names));
    const feats = data.features.filter((f) => wanted.has(f.properties.name));
    planLayer = L.geoJSON({ type: "FeatureCollection", features: feats }, {
      style: { color: "#0f0f14", weight: 2, dashArray: "6 4", fillColor: "#7c3aed", fillOpacity: 0.12 }, interactive: false,
    }).addTo(map);
    if (fit && feats.length) map.fitBounds(planLayer.getBounds(), { ...mapPadding(), maxZoom: 17 });
    for (const x of withArea) {
      const li = document.querySelector(`#detail .plans li[data-plan="${CSS.escape(x.nr)}"] .plan-meta`);
      if (!li) continue;
      const nr = x.nr, own = new Set(names(x));
      li.innerHTML = (x.match === "grundnummer" ? "– im Datensatz nur die Grundnummer:<br>" : x.match === "mehrdeutig" ? "– mehrere Pläne passen:<br>" : "")
        + [...new Map(feats.filter((f) => own.has(f.properties.name)).map((f) => [f.properties.name, f])).values()].map((f) =>
        `– ${f.properties.name !== nr ? esc(f.properties.name) + ", " : ""}rechtskräftig seit ${fmtDate(f.properties.inkraft_seit)} · ${link(f.properties.plan, "Plan (PDF)")}${f.properties.begruendung ? " · " + link(f.properties.begruendung, "Begründung (PDF)") : ""}`).join("<br>");
    }
  }

  // Zuschaltbare Flächen aus den Kontextdaten (pipeline/kontext.py → flaechen/*.json); Einordnung, verbindlich sind die Quellen
  const KX_ZOOM = 13;
  const UESG_STYLE = { festgesetzt: { color: "#1d4ed8", weight: 1, fillColor: "#1d4ed8", fillOpacity: 0.32 },
    "vorläufig gesichert": { color: "#1d4ed8", weight: 1, dashArray: "4 3", fillColor: "#60a5fa", fillOpacity: 0.22 } };
  const BRW_FARBE = ["#fdecd2", "#f8c98f", "#ec9f52", "#c46d22", "#7f4210"];
  const KX = {
    uesg: { label: "Überschwemmungsgebiete", file: "ueberschwemmung", quelle: "ueberschwemmung" },
    brw: { label: "Bodenrichtwerte", file: "bodenrichtwerte", quelle: "bodenrichtwerte" },
    klima: { label: "Hitze (Klimaanalyse)", file: "klima", quelle: "klima" },
  };
  const KLIMA_FARBE = { "Handlungspriorität 1": "#9f1239", "Handlungspriorität 2": "#e11d48", "Handlungspriorität 3": "#fb923c",
    "Handlungspriorität 4": "#fcd34d", "Handlungspriorität 5": "#fef3c7" };
  // Punkte aus den Kontextdaten (Land NRW, VRS): ab Stadtteil-Zoom
  const PX = {
    kitas: { label: "Kitas", file: "punkte_kitas", quelle: "kitas", farbe: "#be185d",
      text: (p) => `${esc(p.name)}<br><span class="nav-dim">Plätze unter 3 Jahren ${esc(de(p.plaetze_u3))}, ab 3 Jahren ${esc(de(p.plaetze_ue3))}</span>` },
    schulen: { label: "Schulen", file: "punkte_schulen", quelle: "schulen", farbe: "#1d4ed8",
      text: (p) => `${esc(p.name)}<br><span class="nav-dim">${esc(p.schulform || "")}${p.traeger ? `, ${esc(p.traeger)}` : ""}</span>` },
    haltestellen: { label: "Haltestellen", file: "punkte_haltestellen", quelle: "haltestellen", farbe: "#0f766e", text: (p) => esc(p.name) },
  };
  // Weitere Ebenen aus ebenen.json (pipeline/ebenen.py): Stadt, Land, Bund; Mindestzoom für große Ebenen aus ebenen.json
  // (mindestzoom), EX_ZOOM nur als Rückfall für ältere Dateien ohne diese Angabe
  const EX = {};
  const EX_ZOOM = { denkmaeler: 14, baupotenziale: 13, stimmbezirke: 12 };
  const exText = (e, p) => {
    const rows = Object.entries(e.felder || {}).filter(([k]) => p[k] != null && p[k] !== "")
      .map(([k, t]) => { const v = String(p[k]);   // Tooltips sind nicht anklickbar: Adressen als Text
        return `${esc(t)}: ${esc(/^https?:/.test(v) ? v.replace(/^https?:\/\//, "").split("/")[0] : v)}`; });
    return `<strong>${esc(e.titel)}</strong>${p._teil ? ` · ${esc(p._teil)}` : ""}${rows.length ? `<br>${rows.join("<br>")}` : ""}
      <br><span class="nav-dim">${esc(e.quelle)}${e.stand ? `, abgerufen am ${esc(fmtDate(e.stand))}` : ""}</span>`;
  };
  // Ebenen mit mehreren Arten: Farbe je Teil (Legende und Fläche)
  const EX_TEILE = {
    hochwasser: [["HQextrem", "#7dd3fc", "HQextrem (seltenes Extremhochwasser)"], ["geschützt", "#fbbf24", "HQ100, durch Hochwasserschutz geschützt"],
      ["HQ100", "#0369a1", "HQ100 (statistisch einmal in 100 Jahren)"]],
    naturschutz: [["Naturschutz", "#166534", "Naturschutzgebiet"], ["Landschaftsschutz", "#86efac", "Landschaftsschutzgebiet"], ["FFH", "#0d9488", "FFH-Gebiet (Natura 2000)"]],
  };
  const exFarbe = (e, p) => {
    const text = `${p._teil || ""} ${Object.values(p).join(" ")}`;
    const hit = (EX_TEILE[e.key] || []).find(([s]) => text.includes(s));
    return hit ? hit[1] : e.farbe;
  };
  const exStyle = (e, f) => EX_TEILE[e.key] ? { color: exFarbe(e, f.properties), weight: 1, fillColor: exFarbe(e, f.properties), fillOpacity: 0.35 }
    : e.art === "grenze" ? { color: e.farbe, weight: 1.5, fill: false }
    : e.art === "linie" ? { color: e.farbe, weight: 3, opacity: 0.9, dashArray: f.properties._teil === "in Planung" ? "6 5" : null }
    : { color: e.farbe, weight: 1, fillColor: e.farbe, fillOpacity: 0.25 };
  // Stufen nach Quintilen der Zonenwerte, auf 10 €/m² gerundet
  function brwBreaks(feats) {
    const v = feats.map((f) => f.properties.brw).filter((x) => x != null).sort((a, b) => a - b);
    return [...new Set([0.2, 0.4, 0.6, 0.8].map((q) => Math.ceil(v[Math.floor(q * (v.length - 1))] / 10) * 10))];
  }
  const brwStufe = (v, br) => br.filter((b) => v >= b).length;
  const ERGAENZUNG = { EFH: "Ein- und Zweifamilienhäuser", MFH: "Mehrfamilienhäuser" };
  const kxQuelle = (k) => (kontext && kontext.meta.quellen[(KX[k] || PX[k]).quelle]) || {};
  const minZoom = (k) => (EX[k] ? EX[k].mindestzoom || EX_ZOOM[k] || 11 : KX_ZOOM);
  async function drawKx() {
    if (legendEl) drawLegend();
    for (const k of [...Object.keys(KX), ...Object.keys(PX), ...Object.keys(EX)]) {
      const want = kxOn.has(k) && map.getZoom() >= minZoom(k);
      if (!want) { if (kxLayers[k]) { kxLayers[k].remove(); kxLayers[k] = null; } continue; }
      if (kxLayers[k]) continue;
      const datei = EX[k] ? EX[k].datei : `flaechen/${(KX[k] || PX[k]).file}.json`;
      kxData[k] ||= fetch(BONN + datei).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const data = await kxData[k];
      if (!data || kxLayers[k] || !kxOn.has(k) || map.getZoom() < minZoom(k)) continue;
      if (!map.getPane("kontextflaechen")) map.createPane("kontextflaechen").style.zIndex = 360;
      if (EX[k]) {
        const e = EX[k];
        kxLayers[k] = L.geoJSON(data, { pane: "kontextflaechen", style: (f) => exStyle(e, f),
          pointToLayer: (f, ll) => L.circleMarker(ll, { pane: "kontextflaechen", radius: 4, color: "#fff", weight: 1, fillColor: e.farbe, fillOpacity: 0.9 }),
          onEachFeature: (f, layer) => layer.bindTooltip(exText(e, f.properties), { sticky: true }).on("click", (ev) => clickOrtsteil(ev.latlng)) });
      } else if (PX[k]) {
        const d = PX[k];
        kxLayers[k] = L.geoJSON(data, { pointToLayer: (f, ll) => L.circleMarker(ll, { pane: "kontextflaechen", radius: 5, color: "#fff", weight: 1.5, fillColor: d.farbe, fillOpacity: 0.95 }),
          onEachFeature: (f, layer) => layer.bindTooltip(`${d.text(f.properties)}<br><span class="nav-dim">${esc(kxQuelle(k).titel || "")}</span>`) });
      } else if (k === "klima") {
        kxLayers[k] = L.geoJSON(data, { pane: "kontextflaechen", style: (f) => ({ stroke: false, fillColor: KLIMA_FARBE[f.properties.prioritaet] || "#e5e7eb", fillOpacity: 0.5 }),
          onEachFeature: (f, layer) => layer.bindTooltip(`${esc(f.properties.prioritaet || "")}<br><span class="nav-dim">Klimaanalyse NRW, Planungshinweiskarte</span>`, { sticky: true })
            .on("click", (e) => clickOrtsteil(e.latlng)) });
      } else if (k === "uesg") {
        kxLayers[k] = L.geoJSON(data, { pane: "kontextflaechen", interactive: false, style: (f) => UESG_STYLE[f.properties.art] || UESG_STYLE.festgesetzt });
      } else {
        const br = brwBr = brwBreaks(data.features), stand = kxQuelle(k).stand;
        kxLayers[k] = L.geoJSON(data, {
          pane: "kontextflaechen",
          style: (f) => ({ color: "#7f4210", weight: 0.8, fillColor: BRW_FARBE[brwStufe(f.properties.brw, br)], fillOpacity: 0.45 }),
          onEachFeature: (f, layer) => layer.bindTooltip(`Bodenrichtwert ${esc(de(f.properties.brw))} €/m²${f.properties.ergaenzung ? ` · ${esc(ERGAENZUNG[f.properties.ergaenzung] || f.properties.ergaenzung)}` : ""}
            <br><span class="nav-dim">Wohnbauland, Zone ${esc(f.properties.zone)} · Stichtag ${esc(fmtDate(f.properties.stichtag || stand || ""))} · BORIS NRW</span>`, { sticky: true })
            .on("click", (e) => clickOrtsteil(e.latlng)),
        });
      }
      kxLayers[k].addTo(map);
    }
    if (legendEl) drawLegend();
  }
  // Die Zonen liegen über den Stadtteilflächen; ein Klick wählt wie sonst den Stadtteil an dieser Stelle
  function clickOrtsteil(ll) {
    if (!navOrtsteile || !map.hasLayer(navOrtsteile)) return;
    navOrtsteile.eachLayer((l) => { if (inGeom(ll.lng, ll.lat, l.feature.geometry)) l.fire("click"); });
  }
  function kxLegend() {
    if (!kxOn.size) return "";
    const q = (k) => { const x = kxQuelle(k); return `${safeUrl(x.url) ? `<a href="${safeUrl(x.url)}">${esc(x.titel)}</a>` : esc(x.titel || "")}, ${esc(x.lizenz || "")}${x.stand ? `, Stand ${esc(x.stand.length === 10 ? fmtDate(x.stand) : x.stand)}` : ""}`; };
    const zoom = [...kxOn].some((k) => map.getZoom() < minZoom(k)) ? '<p class="hint">Zum Anzeigen einiger Ebenen hineinzoomen.</p>' : "";
    let h = "";
    if (kxOn.has("uesg")) h += `<ul><li><span class="swatch swatch-area" style="background:${UESG_STYLE.festgesetzt.fillColor}" aria-hidden="true"></span>Überschwemmungsgebiet, festgesetzt</li>
      <li><span class="swatch swatch-area" style="background:${UESG_STYLE["vorläufig gesichert"].fillColor}" aria-hidden="true"></span>Überschwemmungsgebiet, vorläufig gesichert</li></ul>
      <p class="hint">Einordnung, keine Aussage zu Starkregen. Verbindlich sind die Karten des Landes. Quelle: ${q("uesg")}.</p>`;
    if (kxOn.has("klima")) h += `<ul>${Object.entries(KLIMA_FARBE).map(([t, c]) => `<li><span class="swatch swatch-area" style="background:${c}" aria-hidden="true"></span>${esc(t)}</li>`).join("")}</ul>
      <p class="hint">Hitze: Handlungspriorität der Planungshinweiskarte (1 = dringend). Einordnung; verbindlich ist die Quelle. Quelle: ${q("klima")}.</p>`;
    for (const k of Object.keys(PX).filter((x) => kxOn.has(x))) h += `<ul><li><span class="swatch" style="background:${PX[k].farbe}" aria-hidden="true"></span>${esc(PX[k].label)}</li></ul><p class="hint">Quelle: ${q(k)}.</p>`;
    if (kxOn.has("brw")) {
      const br = brwBr;
      h += `${br ? `<ul>${[0, ...br].map((lo, i) => `<li><span class="swatch swatch-area" style="background:${BRW_FARBE[i]}" aria-hidden="true"></span>${i === 0 ? `unter ${de(br[0])}` : i === br.length ? `ab ${de(lo)}` : `${de(lo)} bis unter ${de(br[i])}`} €/m²</li>`).join("")}</ul>` : ""}
      <p class="hint">Bodenrichtwerte für Wohnbauland, andere Nutzungen fehlen. Einordnung, kein Urteil; verbindlich ist BORIS NRW. Quelle: ${q("brw")}.</p>`;
    }
    for (const k of Object.keys(EX).filter((x) => kxOn.has(x))) {
      const e = EX[k], u = safeUrl(e.url);
      const teile = EX_TEILE[k] || [[null, e.farbe, e.titel]];
      h += `<ul>${teile.map(([, c, label]) => `<li><span class="swatch${e.art === "flaeche" ? " swatch-area" : ""}" style="background:${c}" aria-hidden="true"></span>${esc(label)}</li>`).join("")}</ul>
        <p class="hint">Quelle: ${u ? `<a href="${u}">${esc(e.quelle)}</a>` : esc(e.quelle)}, ${esc(e.lizenz)}${e.stand ? `, abgerufen am ${esc(fmtDate(e.stand))}` : ""}.</p>`;
    }
    return h + zoom;
  }
  // Planebene: alle Geltungsbereiche; Klick öffnet die Planchronik
  const PLAN_STYLE = { color: "#0e7490", weight: 1.5, fillColor: "#0e7490", fillOpacity: 0.08 };
  async function drawAllPlans() {
    if (legendEl) drawLegend();
    if (!planOn) { if (allPlans) { allPlans.remove(); allPlans = null; } return; }
    const data = await loadPlans();
    if (!planOn || allPlans) return;
    allPlans = L.geoJSON(data, {
      style: PLAN_STYLE,
      onEachFeature: (f, layer) => layer.bindTooltip(`Bebauungsplan ${esc(f.properties.name)}`, { sticky: true })
        .on("click", () => showPlan(f.properties.name)),
    }).addTo(map);
    allPlans.bringToBack();
    if (outline) outline.bringToBack();
  }
  // Register je Plannummer (data/export/bonn/plaene.json): Vorlagen chronologisch, Verfahrensschritte abgeleitet
  let planReg = null;
  const planIndexUrl = () => (index ? BONN + "plaene.json" : null);
  const loadPlanReg = () => (planReg ||= (planIndexUrl() ? fetch(planIndexUrl()).then((r) => (r.ok ? r.json() : null)).catch(() => null) : Promise.resolve(null)));
  const PLAN_MATCH = { eindeutig: "eindeutig zugeordnet", grundnummer: "im Datensatz nur die Grundnummer", mehrdeutig: "mehrere Pläne passen",
    nicht_im_datensatz: "nicht unter den rechtskräftigen Plänen (im Verfahren oder aufgehoben)" };
  // detailSeq: eine langsam geladene Planchronik überschreibt keine neuere Auswahl (Code-Prüfung 23.10.2026)
  async function showPlan(key) {
    const seq = ++detailSeq;
    const [reg, data] = await Promise.all([loadPlanReg(), loadPlans()]);
    if (seq !== detailSeq) return;
    const entries = reg ? reg.plaene.filter((e) => e.nr === key || e.plaene.some((v) => v.name === key)) : [];
    const names = new Set([key, ...entries.flatMap((e) => e.plaene.map((v) => v.name))]);
    const feats = [...new Map(data.features.filter((f) => names.has(f.properties.name)).map((f) => [f.properties.name, f])).values()];
    if (!entries.length && !feats.length) { showIntro(); return; }   // unbekannte Plannummer (z. B. aus der Adresse)
    const vorlagen = [...new Map(entries.flatMap((e) => e.vorlagen).map((v) => [v.drucksache, v])).values()]
      .sort((a, b) => String(a.datum).localeCompare(String(b.datum)) || a.drucksache.localeCompare(b.drucksache));
    selected = null;
    shownPlan = key;
    markCurrent(null);
    if (tl) tl.select(null);
    highlight();
    if (planLayer) { planLayer.remove(); planLayer = null; }
    if (feats.length) {
      planLayer = L.geoJSON({ type: "FeatureCollection", features: feats }, {
        style: { color: "#0f0f14", weight: 2, dashArray: "6 4", fillColor: "#0e7490", fillOpacity: 0.15 }, interactive: false }).addTo(map);
      map.fitBounds(planLayer.getBounds(), { ...mapPadding(), maxZoom: 17 });
    }
    const facts = feats.map((f) => `<li><strong>${esc(f.properties.name)}</strong> – rechtskräftig seit ${fmtDate(f.properties.inkraft_seit)}
      <span class="derived">belegt, Stadt Köln</span><br>${link(f.properties.plan, "Plan (PDF)")}${f.properties.begruendung ? " · " + link(f.properties.begruendung, "Begründung (PDF)") : ""}</li>`).join("");
    const ortsteile = [...new Set(entries.flatMap((e) => e.ortsteile))];
    const match = [...new Set(entries.map((e) => e.treffer))].map((t) => PLAN_MATCH[t] || t).join("; ");
    const item = (v) => `<li><button type="button" class="link-btn" data-open-ref="${esc(v.drucksache)}">${esc(v.drucksache)}</button> · ${fmtDate(v.datum)} · ${esc(v.art || "")}<br>${esc(v.titel)}</li>`;
    const steps = (reg ? reg.schritte : []).map((st) => {
      const hits = vorlagen.filter((v) => (v.schritte || []).includes(st.id));
      const status = hits.length ? "abgeleitet" : "soll";
      return `<li class="step" data-status="${status}"><span class="mark mark-${status}" aria-hidden="true"></span>
        <div class="step-head">${esc(st.label)}<span class="step-status">${status === "soll" ? "soll, keine Vorlage zugeordnet" : "abgeleitet aus dem Titel"}</span></div>
        <div class="step-body">Fundstelle: ${esc(st.fundstelle)}${hits.length ? `<ul class="related">${hits.map(item).join("")}</ul>
          <button type="button" class="jump" data-date="${esc(hits[0].datum)}">in der Zeitleiste zeigen</button>` : ""}</div></li>`;
    }).join("");
    const inkraft = feats.map((f) => f.properties.inkraft_seit).filter(Boolean).sort().pop();
    const final = `<li class="step" data-status="${inkraft ? "belegt" : "soll"}"><span class="mark mark-${inkraft ? "belegt" : "soll"}" aria-hidden="true"></span>
      <div class="step-head">Inkrafttreten (Bekanntmachung)<span class="step-status">${inkraft ? "belegt, Stadt Köln" : "soll, nicht unter den rechtskräftigen Plänen"}</span></div>
      <div class="step-body">Fundstelle: § 10 Abs. 3 BauGB${inkraft ? `<br>${fmtDate(inkraft)}` : ""}</div></li>`;
    $("#detail-heading").textContent = "Bebauungsplan";
    $("#detail").innerHTML = `
      <h3 tabindex="-1">Bebauungsplan ${esc(key)}</h3>
      ${facts ? `<ul class="locs plans">${facts}</ul>` : '<p class="hint">Kein Geltungsbereich im Datensatz der rechtskräftigen Pläne (im Verfahren oder aufgehoben).</p>'}
      <dl class="facts">${ortsteile.length ? `<dt>Stadtteile</dt><dd>${esc(ortsteile.join(", "))}</dd>` : ""}
        ${match ? `<dt>Zuordnung</dt><dd>${esc(match)} <span class="derived">abgeleitet, Plannummer im Titel</span></dd>` : ""}</dl>
      ${reg ? `<h4>Planchronik</h4>
        <p class="hint">Verfahrensschritte nach BauGB als Soll; eine Vorlage ist einem Schritt zugeordnet, wenn ihr Titel ihn nennt (abgeleitet). Vereinfachte Verfahren (§§ 13, 13a BauGB) kennen weniger Schritte. „soll“ heißt: keine Vorlage seit Oktober 2019 nennt den Schritt – nicht, dass er fehlt.</p>
        <ol class="steps">${steps}${final}</ol>
        <h4>Vorlagen mit dieser Plannummer (${vorlagen.length})</h4>
        ${vorlagen.length ? `<ol class="related plan-papers">${vorlagen.map(item).join("")}</ol>` : "<p>Keine Vorlage nennt diese Plannummer im Titel.</p>"}` : ""}
      <details class="acc"><summary>Quellen</summary><ul>
        <li>Geltungsbereich, Inkrafttreten, Plan und Begründung: Stadt Köln, Lage der Bebauungspläne (CC0)</li>
        <li>Vorlagen: OParl-API der Stadt Köln (CC0); Zuordnung über die Plannummer im Titel (abgeleitet)</li></ul></details>`;
    $("#announce").textContent = `Bebauungsplan ${key} geöffnet`;
    if (MOBILE.matches || $("#panel-detail").hidden) setPanel("panel-detail", true);
    $("#detail").scrollTop = 0;
    syncUrl();
  }
  // Tastatur- und Listenzugang zur Planebene: Pläne mit Vorlagen im gewählten Gebiet
  async function showPlanList() {
    const seq = ++detailSeq;
    if (planLayer) { planLayer.remove(); planLayer = null; }
    const reg = await loadPlanReg();
    if (!reg || seq !== detailSeq) return;
    const inArea = (e) => area.kind !== "ortsteil" || e.ortsteile.includes(area.name);
    const refs = new Set(papers.map((p) => p.reference));
    const list = reg.plaene.filter((e) => inArea(e) && e.vorlagen.some((v) => refs.has(v.drucksache)));
    selected = null;
    shownPlan = null;
    highlight();
    markCurrent(null);
    $("#detail-heading").textContent = "Bebauungspläne";
    $("#detail").innerHTML = `<h3 tabindex="-1">Bebauungspläne mit Vorlagen · ${esc(area.name || "")}</h3>
      <p class="hint">Pläne, deren Nummer im Titel einer Vorlage dieses Gebiets steht. Die Karte zeigt alle rechtskräftigen Pläne der Stadt.</p>
      ${list.length ? `<ul class="related">${list.map((e) => `<li><button type="button" class="link-btn" data-open-plan="${esc(e.nr)}">Bebauungsplan ${esc(e.nr)}</button> · ${e.vorlagen.length} ${e.vorlagen.length === 1 ? "Vorlage" : "Vorlagen"}</li>`).join("")}</ul>` : "<p>Keine Vorlage dieses Gebiets nennt eine Plannummer.</p>"}`;
    if (MOBILE.matches || $("#panel-detail").hidden) setPanel("panel-detail", true);
    $("#detail h3").focus();
  }

  // --- Baustellen (data/export/bonn/baustellen.json, pipeline/kandidaten.py) -----------------------------
  const siteState = (b) => (!b.aktiv ? "entfallen" : b.von && b.von > heute() ? "geplant" : "aktuell");
  const SITE_STATE = { aktuell: "laufend", geplant: "geplant", entfallen: "nicht mehr gemeldet" };
  const siteClass = (b) => (b.fremd ? "site-fremd" : `site-${siteState(b)}`);
  // Punkt in Fläche (gerade-ungerade über alle Ringe, Löcher eingeschlossen)
  function inGeom(lon, lat, g) {
    const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    return polys.some((rings) => {
      let inside = false;
      for (const ring of rings) for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
      }
      return inside;
    });
  }
  function areaFeature() {
    if (area.kind === "ortsteil") return geo.ortsteil.features.find((f) => f.properties.ortsteil_bez === area.name);
    if (area.kind === "bezirk") return geo.bezirk.features.find((f) => f.properties.bezirk_bez === area.name);
    return null;
  }
  function areaSites() {
    if (!bau) return [];
    const f = area && areaFeature();
    return f ? bau.baustellen.filter((b) => inGeom(b.lon, b.lat, f.geometry)) : bau.baustellen;
  }
  function drawSites() {
    if (legendEl) drawLegend();
    if (bauLayer) { bauLayer.remove(); bauLayer = null; }
    if (!bauOn || !bau) return;
    bauLayer = L.layerGroup(bau.baustellen.filter((b) => b.aktiv).map((b) => L.marker([b.lat, b.lon], {
      icon: L.divIcon({ className: "site-marker", html: `<span class="site-icon ${siteClass(b)}"></span>`, iconSize: [18, 18], iconAnchor: [9, 9] }),
      title: `Baustelle ${b.bezeichnung} (${SITE_STATE[siteState(b)]})`, keyboard: true, riseOnHover: true,
    }).on("click", () => showSite(b.id)))).addTo(map);
  }
  const yes = (v) => (v ? "erfüllt" : "nicht erfüllt");
  function candHtml(c, withSite) {
    return `<li>${withSite ? "" : `<button type="button" class="link-btn" data-open-ref="${esc(c.drucksache)}">${esc(c.drucksache)}</button> – ${esc(c.titel)}<br>`}
      <span class="meta">Entschieden ${fmtDate(c.entschieden_am)} · Kriterien: räumlich ${yes(c.kriterien.raeumlich)} (${esc(c.abstand_m)} m, höchstens 150 m) · zeitlich ${yes(c.kriterien.zeitlich)} (Baubeginn nach der Entscheidung) · gleiche Straße ${yes(c.kriterien.strasse)} · Tiefbau oder Verkehr ${yes(c.kriterien.thema)} · Bau-Stichwort passend zur Maßnahme ${yes(c.kriterien.stichwort)}${c.kriterien.baubeschluss ? " · Baubeschluss (Beschlussvorlage) erfüllt" : ""}</span></li>`;
  }
  const UMSETZUNG_HINT = "Indiz, kein Beleg: Ort, Zeit und Thema passen zusammen; eine Stichprobe wurde von Hand geprüft. Termine der Baustellen sind laut Quelle unverbindlich.";
  function showSite(id) {
    const b = bau && bau.baustellen.find((x) => x.id === String(id));
    if (!b) return;
    detailSeq++;
    selected = null;
    shownPlan = null;
    shownSite = b.id;
    markCurrent(null);
    if (tl) tl.select(null);
    highlight();
    if (planLayer) { planLayer.remove(); planLayer = null; }
    map.setView([b.lat, b.lon], Math.max(map.getZoom(), 16), { animate: !REDUCED });
    const state = siteState(b);
    const changes = b.aenderungen.map((a) => `<li>${fmtDate(a.datum)}: ${a.feld === "von" ? "Beginn" : "Ende"} ${esc(a.alt || "–")} → ${esc(a.neu || "–")}</li>`).join("");
    $("#detail-heading").textContent = "Baustelle";
    $("#detail").innerHTML = `
      <h3 tabindex="-1">${esc(b.bezeichnung)}</h3>
      <dl class="facts">
        ${b.strasse && b.strasse !== b.bezeichnung ? `<dt>Straße</dt><dd>${esc(b.strasse)}</dd>` : ""}
        <dt>Stadtbezirk</dt><dd>${esc(b.stadtbezirk || "–")}</dd>
        <dt>Maßnahme</dt><dd>${esc(b.massnahme || "–")}</dd>
        <dt>Träger</dt><dd>${esc(b.traeger || "–")}${b.fremd ? '<br><span class="hint">Anderer Träger: setzt in der Regel keinen Ratsbeschluss um.</span>' : ""}</dd>
        <dt>Zeitraum</dt><dd>${fmtDate(b.von)} – ${fmtDate(b.bis)} <span class="derived">laut Quelle unverbindlich</span></dd>
        <dt>Stand</dt><dd>${SITE_STATE[state]}${b.entfallen ? ` (seit ${fmtDate(b.entfallen)})` : ""}</dd>
        ${b.sperrung ? `<dt>Sperrung</dt><dd>${esc(b.sperrung)}</dd>` : ""}
        <dt>Im Archiv seit</dt><dd>${fmtDate(b.seit)}${b.seit === bau.meta.archiv_beginn ? " (Beginn des Archivs)" : ""}</dd>
      </dl>
      ${changes ? `<h4>Geänderte Termine</h4><ul class="related">${changes}</ul>` : ""}
      <h4>Mögliche Umsetzung</h4>
      ${b.kandidaten.length ? `<p class="hint"><span class="derived">abgeleitet</span> ${esc(UMSETZUNG_HINT)}</p><ul class="related plan-papers">${b.kandidaten.map((c) => candHtml(c)).join("")}</ul>`
        : `<p>${b.fremd ? "Für Baustellen anderer Träger werden keine Beschlüsse gesucht." : "Kein Beschluss erfüllt alle Kriterien (räumlich, zeitlich, gleiche Straße, Tiefbau oder Verkehr, Bau-Stichwort, Baubeschluss)."}</p>`}
      <details class="acc"><summary>Was diese Angaben nicht zeigen</summary><ul>${bau.meta.hinweise.map((h) => `<li>${esc(h)}</li>`).join("")}</ul></details>
      <details class="acc"><summary>Quellen</summary><ul>
        <li>Baustellen: Stadt Köln, ${bau.meta.quelle.map((u) => link(u, esc(u.replace("https://", "")))).join(", ")} – ${esc(bau.meta.lizenz)}</li>
        <li>Abruf: ${esc(String(bau.meta.abruf || "–").slice(0, 10))} (${esc(bau.meta.herkunft)}); Baustellen-ID ${esc(b.id)}</li>
        <li>Mögliche Umsetzung: abgeleitet (pipeline/kandidaten.py), Audit ${link(REPO + "/blob/main/data/export/baustellen_kandidaten.tsv", "baustellen_kandidaten.tsv")}</li></ul></details>`;
    $("#announce").textContent = `Baustelle ${b.bezeichnung} geöffnet`;
    if (MOBILE.matches || $("#panel-detail").hidden) setPanel("panel-detail", true);
    $("#detail").scrollTop = 0;
    syncUrl();
  }
  function showSiteList() {
    detailSeq++;
    const list = areaSites().filter((b) => b.aktiv);
    selected = null;
    shownPlan = null;
    shownSite = null;
    highlight();
    markCurrent(null);
    $("#detail-heading").textContent = "Baustellen";
    $("#detail").innerHTML = `<h3 tabindex="-1">Baustellen · ${esc(area.name || "ganz Köln")}</h3>
      <p class="hint">Gemeldete Baustellen mit Einfluss auf den Verkehr; Termine unverbindlich.</p>
      ${list.length ? `<ul class="related plan-papers">${list.map((b) => `<li><button type="button" class="link-btn" data-open-site="${esc(b.id)}">${esc(b.bezeichnung)}</button> · ${esc(b.massnahme || "")} · ${fmtDate(b.von)} – ${fmtDate(b.bis)} · ${SITE_STATE[siteState(b)]}${b.fremd ? " · anderer Träger" : ""}${b.kandidaten.length ? ' · <span class="derived">mögliche Umsetzung</span>' : ""}</li>`).join("")}</ul>` : "<p>In diesem Gebiet ist derzeit keine Baustelle gemeldet.</p>"}`;
    if (MOBILE.matches || $("#panel-detail").hidden) setPanel("panel-detail", true);
    $("#detail h3").focus();
  }
  // Soll-Modell (data/export/bonn/soll.json): Verfahren nach Regelwerk aus „Bonn entscheidet“ (MIT) mit Ergänzungen;
  // abgeglichen wird je Vorgang nur, welche Gremienarten beraten haben (pipeline/soll.py)
  let sollData = null;
  const loadSoll = () => (sollData ||= index ? fetch(BONN + "soll.json").then((r) => (r.ok ? r.json() : null)).catch(() => null) : Promise.resolve(null));
  const GREMIUM_BAHN = new Set(["bv", "aus", "rat"]);
  const lawLinks = (links) => (links || []).map((l) => link(l.url, esc(l.label))).filter(Boolean).join(" · ");
  function sollStep(st, d, ist) {
    const status = GREMIUM_BAHN.has(st.bahn) && ist.has(st.bahn) ? "belegt" : "soll";
    const note = status === "belegt" ? "ein Gremium dieser Art hat beraten (belegt)" : GREMIUM_BAHN.has(st.bahn) ? "soll, kein Gremium dieser Art hat beraten" : "soll, nicht abgeglichen";
    const who = st.bahn ? `Wer: ${esc(d.bahnen[st.bahn] || st.bahn)}<br>` : "";
    return `<li class="step" data-status="${status}"><span class="mark mark-${status}" aria-hidden="true"></span>
      <div class="step-head">${esc(st.label)}<span class="step-status">${note}</span></div>
      <div class="step-body">${who}${st.was !== st.label ? esc(st.was) + "<br>" : ""}${st.links ? `Rechtsgrundlage: ${lawLinks(st.links)}` : st.beleg ? `Rechtsgrundlage: ${esc(st.beleg)}` : ""}
        ${st.eigen ? ' <span class="derived">Ergänzung des Ratsatlas</span>' : ""}</div></li>`;
  }
  function zustoHtml(p, d) {
    const names = [...new Set(p.steps.filter((s) => s.typ === "beratung" || s.typ === "entscheidung").map((s) => s.label))];
    const hits = names.filter((n) => d.zusto[n]);
    const sections = hits.map((n) => {
      const z = d.zusto[n];
      const ent = z.rechte.filter((r) => r.art === "Entscheidung");
      return `<p><strong>${esc(n)}</strong> – Zuständigkeitsordnung, Abschnitt ${esc(z.nr)}: ${z.rechte.length} Rechte, davon ${ent.length} Entscheidungen.</p>
        ${ent.length ? `<details class="acc"><summary>Entscheidungsrechte (${ent.length})</summary><ul>${ent.map((r) =>
          `<li>${esc(z.nr)} ${esc(r.nr)}: ${esc(r.inhalt)}${r.an_bezirksvertretung ? " (Empfehlung an die zuständige Bezirksvertretung)" : ""}</li>`).join("")}</ul></details>` : ""}`;
    }).join("");
    return sections ? `${sections}<p class="hint">Welches Recht im Einzelfall greift, steht nur in der Vorlage. Zuordnung über den Namen des Gremiums; frühere Ausschüsse mit anderem Namen erscheinen nicht. ${link(d.meta.zusto_url, "Zuständigkeitsordnung")}, Stand ${esc(d.meta.zusto_stand || "")}.</p>` : "";
  }
  async function showSoll(p) {
    const box = document.querySelector("#detail .soll-box");
    if (!box) return;
    const d = await loadSoll();
    if (selected !== p || !box.isConnected) return;
    if (!d) { box.innerHTML = '<p class="hint">Das Soll-Modell konnte nicht geladen werden.</p>'; return; }
    const s = p.soll;
    const ist = new Set(s.ist);
    const v = s.verfahren && d.verfahren[s.verfahren];
    const befund = s.passung === "weicht ab"
      ? `<div class="befund"><strong>Befund:</strong> Beraten hat auch ${esc(s.abweichung.map((b) => d.bahnen[b] || b).join(", "))}. Das Regelwerk sieht das für dieses Verfahren nicht vor. Das ist ein Befund, keine Bewertung; das Modell ist vereinfacht.</div>`
      : s.passung === "nur Beirat" ? '<p class="hint">Beraten hat nur ein Beirat. Beiräte bildet das Modell nicht ab; ein Abgleich entfällt.</p>'
      : s.passung === "ohne Beratung" ? '<p class="hint">In den Daten ist keine Beratung verzeichnet; ein Abgleich entfällt.</p>' : "";
    const body = v ? `<p><strong>${esc(v.titel)}</strong>${v.kurz ? ` – ${esc(v.kurz)}` : ""}<br>
        <span class="derived">Zuordnung abgeleitet: ${esc(s.grund)}; Sicherheit ${esc(s.sicherheit)}</span></p>${befund}
      <p class="hint">Schritte nach Regelwerk. Nicht jeder Schritt kommt in jedem Fall vor. Abgeglichen wird nur, ob ein Gremium dieser Art beraten hat.</p>
      <ol class="steps">${v.schritte.map((st) => sollStep(st, d, ist)).join("")}</ol>`
      : `<p>Vorlagenart „${esc(p.paper_type)}“: ${esc(d.ohne_soll[p.paper_type] || "kein Verfahren im Regelwerk; kein Soll angenommen.")}</p>`;
    const zusto = zustoHtml(p, d);
    box.innerHTML = `${body}
      <details class="acc"><summary>Wer entscheidet was?</summary><div>${zusto}<dl>${d.zustaendigkeit.map((z) =>
        `<dt>${esc(z.frage)}</dt><dd>${esc(z.antwort)}${z.links.length ? `<br><span class="meta">Fundstelle: ${lawLinks(z.links)}</span>` : ""}</dd>`).join("")}</dl></div></details>
      <details class="acc"><summary>Fristen vor einer Sitzung</summary><ul>${d.fristen.map((f) =>
        `<li><strong>${esc(f.label)}</strong>: ${esc(f.was)}${f.links.length ? ` · ${lawLinks(f.links)}` : ""}</li>`).join("")}</ul></details>
      <details class="acc"><summary>Quelle des Soll-Modells</summary><ul>
        <li>${esc(d.meta.quelle)} · ${link("https://github.com/anster2025/bonn-entscheidet", "Bonn entscheidet")}</li>
        <li>${esc(d.meta.hinweis)}</li></ul></details>`;
    fillMitwirken(p, d);
  }

  // Station „mögliche Umsetzung“ in der Prozesslinie (neben der Umsetzung durch die Verwaltung, die unklar bleibt)
  function umsetzungHtml(p) {
    const hits = bauByRef.get(p.reference) || [];
    if (!hits.length) return "";
    return `<li class="step" data-status="abgeleitet"><span class="mark mark-abgeleitet" aria-hidden="true"></span>
      <div class="step-head">Mögliche Umsetzung<span class="step-status">abgeleitet</span></div>
      <div class="step-body">${hits.map(({ b, c }) => `Baustelle <button type="button" class="link-btn" data-open-site="${esc(b.id)}">${esc(b.bezeichnung)}</button>, ${esc(b.massnahme || "")}, ${fmtDate(b.von)} – ${fmtDate(b.bis)} (unverbindlich)<ul class="related">${candHtml(c, true)}</ul>`).join("")}
        <div class="hint">${esc(UMSETZUNG_HINT)} Ob und wie die Verwaltung den Beschluss umsetzt, bleibt unklar.</div></div></li>`;
  }

  // Beteiligung: nächste Sitzung eines beteiligten Gremiums (laut Sitzungsliste der Stadt), Bürgerantrag
  // Köln: Link zur Seite der Stadt über Anregungen und Beschwerden folgt nach Prüfung (Phase 6); bis dahin ohne Link
  const BUERGERANTRAG = null;
  function participate(p) {
    const today = heute();
    const gremien = new Set(p.steps.filter((s) => s.typ === "beratung" || s.typ === "entscheidung").map((s) => s.label));
    const next = zeit && p.stand !== "entschieden"
      ? zeit.meetings.find((m) => m.date >= today && !m.cancelled && gremien.has(m.gremium)) : null;
    const onAgenda = next && p.steps.some((s) => s.label === next.gremium && s.date === next.date);
    const meeting = next ? `<li data-generic="sitzung" data-key="${esc(next.gremium)}|${esc(next.date)}">Nächste Sitzung eines beteiligten Gremiums: <strong>${esc(next.gremium)}</strong>, ${fmtDay(next.date)}${next.time ? `, ${esc(next.time)} Uhr` : ""}${onAgenda ? " – die Vorlage steht dort auf der Tagesordnung <span class=\"derived\">abgeleitet, über die Sitzung verknüpft</span>" : ""}.
      ${link(next.web, "Tagesordnung") || "Die Tagesordnung erscheint etwa zwei Wochen vorher."} Die Sitzung ist in der Regel öffentlich; Sie können zuhören.</li>` : "";
    const done = p.stand === "entschieden" ? "<li data-generic=\"done\">Das Verfahren ist entschieden. Neue Anliegen zum Thema lassen sich mit Anregungen und Beschwerden nach § 24 GO NRW einbringen.</li>" : "";
    return `<section class="participate" aria-labelledby="participate-h"><h4 id="participate-h">Selbst mitwirken</h4><ul>
      ${meeting}${done}
      ${p.soll?.verfahren === "buergerantrag" ? "" : `<li data-generic="buergerantrag">Mit Anregungen und Beschwerden nach § 24 GO NRW können Sie sich selbst an den Rat wenden; in Köln berät darüber der Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden.${BUERGERANTRAG ? ` <a href="${BUERGERANTRAG}" target="_blank" rel="noopener">Mehr dazu<span class="visually-hidden"> (Seite der Stadt Köln, neuer Tab)</span></a>` : ""}</li>`}
      ${hasPaperFeed(p) ? "<li data-generic=\"feed\">Mit dem Feed „Diesen Vorgang abonnieren“ (unten) erfahren Sie von neuen Beratungen und Ergebnissen.</li>" : ""}
    </ul><p class="hint mitwirken-hint" hidden></p></section>`;
  }
  // Mitwirkung nach Regelwerk (site/mitwirken.js): ersetzt die allgemeinen Hinweise, wo eine Regel genauer ist
  let mitwirkenMod = null;
  async function fillMitwirken(p, d) {
    const ul = document.querySelector("#detail .participate ul");
    if (!ul || !d?.mitwirken) return;
    let res;
    try { res = (await (mitwirkenMod ||= import("./mitwirken.js"))).mitwirken(p, d, zeit ? zeit.meetings : [], heute()); }
    catch (e) { mitwirkenMod = null; return; }   // beim nächsten Vorgang neu laden (Code-Prüfung 24.10.2026)
    if (selected !== p || !ul.isConnected || !res.regeln.length) return;
    const ids = new Set(res.regeln.map((r) => r.id));
    const drop = (sel) => ul.querySelector(sel)?.remove();
    const termin = res.kontext.termin;
    if (res.kontext.status === "abgeschlossen") drop('[data-generic="sitzung"]');  // Vorgang erledigt: kein Sitzungshinweis
    if (ids.has("sitzung-besuchen") && termin) drop(`[data-generic="sitzung"][data-key="${CSS.escape(termin.gremium + "|" + termin.datum)}"]`);
    if (ids.has("eigener-buergerantrag")) drop('[data-generic="buergerantrag"]');
    if (["entschieden", "abgelehnt", "erledigt"].some((x) => ids.has(x))) drop('[data-generic="done"]');
    const items = res.regeln.map((r) => `<li data-rule="${esc(r.id)}">${esc(r.text)}
      ${r.id === "eigener-buergerantrag" ? `<a href="${BUERGERANTRAG}" target="_blank" rel="noopener">Zum Bürgerantrag<span class="visually-hidden"> (Seite der Stadt Köln, neuer Tab)</span></a>` : ""}
      ${r.sitzung?.web ? link(r.sitzung.web, "Tagesordnung") : ""}
      <br><span class="meta">Frist: ${esc(r.frist)}${r.verstrichen ? " – verstrichen" : ""}${r.links.length ? ` · ${lawLinks(r.links)}` : r.beleg ? ` · ${esc(r.beleg)}` : ""}</span></li>`).join("");
    const feed = ul.querySelector('[data-generic="feed"]');
    if (feed) feed.insertAdjacentHTML("beforebegin", items); else ul.insertAdjacentHTML("beforeend", items);
    const hint = document.querySelector("#detail .mitwirken-hint");
    hint.textContent = "Hinweise nach dem Regelwerk: vereinfachtes Modell aus „Bonn entscheidet“, Anrede angepasst. Stand und Termin sind aus den Daten abgeleitet. Keine Rechtsauskunft.";
    hint.hidden = false;
  }

  function select(p, fromMap) {
    detailSeq++;
    selected = p;
    shownPlan = null;
    shownSite = null;
    markCurrent(p.reference);
    syncUrl();
    if (tl) tl.select(p);
    highlight();
    const resp = p.responsibility.map((r) => `${esc(r.label)}${r.derived ? ` <span class="derived">abgeleitet, über ${esc(r.evidence)}</span>` : ""}`).join("<br>");
    const outside = (l) => (area.kind === "ortsteil" && l.ortsteil && l.ortsteil !== area.name)
      || (area.kind === "bezirk" && l.stadtbezirk && l.stadtbezirk !== area.name);
    const locItem = (l) => `<li><strong>${esc(l.name || l.ortsteil || l.stadtbezirk)}</strong>
      ${l.ortsteil && (l.level === "strasse" || l.level === "objekt") ? `(${esc(l.ortsteil)})` : ""} – <span class="conf conf-${esc(l.confidence)}">${CONF[l.confidence] || esc(l.confidence)}</span>, ${esc(STUFE[l.stage] || `Stufe ${l.stage}`)}${outside(l) ? ' <span class="hint">außerhalb des gewählten Gebiets</span>' : ""}<br>
      <span class="meta">${methodText(l)}</span></li>`;
    // Volltext: erkannter Ort und Teil des Dokuments, kein Zitat (Rahmen laut Antwort der Stadt Köln)
    function methodText(l) {
      if (String(l.method).startsWith("llm_")) return `Mit einem Sprachmodell aus dem Text des Dokuments erkannt und mit dem Verzeichnis der Straßen, Orte, Gebäude und Anlagen abgeglichen <span class="derived">abgeleitet</span> · ${esc(l.evidence || "")}; kein Zitat`;
      if (!String(l.method).startsWith("volltext_")) return `${esc(METHOD[l.method] || l.method)}${l.evidence ? ` · Fundstelle: „${esc(l.evidence)}“` : ""}`;
      const base = METHOD[l.method.slice(9)] || "";
      return `Aus dem Text des Dokuments erschlossen <span class="derived">abgeleitet</span>${base ? ` (Regel wie „${esc(base.replace(/ im Titel/, ""))}“)` : ""} · ${esc(l.evidence || "")}; kein Zitat`;
    }
    // eigene Ortsbezüge zuerst; übernommene getrennt, damit klar bleibt, dass sie den Ursprungsvorgang betreffen
    const ownLocs = p.locations.filter((l) => l.method !== "vererbt"), takenLocs = p.locations.filter((l) => l.method === "vererbt");
    const locs = (ownLocs.length ? ownLocs.map(locItem).join("") : takenLocs.length ? "" : "<li>stadtweit / ohne Ortsbezug</li>")
      + (takenLocs.length ? `<li class="taken-group">Diese Vorlage nennt selbst keinen Ort. Übernommen von der übergeordneten Vorlage:<ul>${takenLocs.map(locItem).join("")}</ul></li>` : "");
    const rel = (arr) => arr.map((r) => `<li>${esc(r.reference)} · ${esc(r.paper_type)} – ${esc(r.name)}</li>`).join("");
    // Quellen nur aus einer Liste (sonst keine), ohne leere Einträge; Abrufdatum nach der Regel des Datenstands (zeitDatum)
    const sources = (Array.isArray(meta && meta.sources) ? meta.sources.filter(Boolean) : [])
      .map((s) => `<li>${esc(s.name)}: ${esc(s.license)}${s.retrieved_at ? ` · Abruf ${zeitDatum(s.retrieved_at)}` : ""}</li>`).join("");
    $("#detail-heading").textContent = "Vorgang";
    $("#detail").innerHTML = `
      <h3 tabindex="-1">${esc(p.name)}</h3>
      <dl class="facts">
        <dt>Vorlage</dt><dd>${esc(p.reference)}${erklBegriff(KUERZEL[(String(p.reference).match(/ ([A-Z]{2})$/) || [])[1]], `Kürzel ${(String(p.reference).match(/ ([A-Z]{2})$/) || [])[1]}`)}</dd>
        <dt>Art</dt><dd>${esc(p.paper_type)}${erklBegriff(ARTEN[p.paper_type], p.paper_type)}</dd>
        <dt>Datum</dt><dd>${fmtDate(p.date)}</dd>
        <dt>Dienststelle</dt><dd>${resp || esc(p.amt) || '<span class="hint">noch nicht ermittelt</span>'}${erklBegriff("federfuehrende-dienststelle", "federführende Dienststelle")}</dd>
        <dt>Stand</dt><dd>${esc(p.stand)}${erkl(`Stand ${p.stand}`, STAND_TEXT[p.stand], "stand-eines-vorgangs")}</dd>
        <dt>Themen</dt><dd>${(p.themes || []).length ? p.themes.map((t) => `${esc(THEMES[t.theme])} <span class="derived">abgeleitet, über ${esc(THEME_METHOD[t.method])} „${esc(t.evidence)}“</span>`).join("<br>") : "–"}</dd>
      </dl>
      <div class="links">${link(p.web, "Original im Ratsinformationssystem", "btn btn-primary")}
        ${link(p.main_file, "Dokument (PDF)", "btn btn-secondary")}</div>
      ${p.kurzfassung ? `<section class="kurz" aria-labelledby="kurz-h"><h4 id="kurz-h">Kurz gesagt</h4><p>${esc(p.kurzfassung.text)}</p>
        <p class="hint"><span class="derived">KI-Kurzfassung</span> Mit einem Sprachmodell (${esc(p.kurzfassung.modell)}) aus dem Text des Dokuments formuliert, kein Zitat. Einzelheiten können ungenau sein, etwa ob etwas beschlossen oder nur vorgeschlagen ist. Maßgeblich ist das Original.</p></section>` : ""}
      <h4>Prozesslinie</h4>
      <ol class="steps">${p.steps.map(stepHtml).join("")}${umsetzungHtml(p)}</ol>
      ${legend()}${glossary(p)}
      ${p.soll && index ? '<section class="soll" aria-labelledby="soll-h"><h4 id="soll-h">Nach Regelwerk (Soll)</h4><div class="soll-box"><p class="hint">Wird geladen …</p></div></section>' : ""}
      ${participate(p)}
      <h4>Ortsbezug</h4><ul class="locs">${locs}</ul>
      ${kontextVorgang(p)}
      ${(p.plans || []).length ? `<h4>Bebauungspläne</h4><ul class="locs plans">${p.plans.map((x) => `<li data-plan="${esc(x.nr)}"><strong>Bebauungsplan ${esc(x.nr)}</strong>
        ${x.area ? '<span class="plan-meta">– Geltungsbereich auf der Karte</span>' : " – nicht im Datensatz der rechtskräftigen Pläne (im Verfahren oder aufgehoben); keine Fläche verfügbar"}
        <br><span class="meta">Fundstelle: „${esc(x.evidence)}“</span>
        ${planIndexUrl() ? `<br><button type="button" class="link-btn" data-open-plan="${esc(x.nr)}">Planchronik öffnen</button>` : ""}</li>`).join("")}</ul>` : ""}
      <p class="links">${link(reportLink(p), "Verortung falsch? Hinweis geben", "btn btn-secondary")}
        ${hasPaperFeed(p) ? `<a class="btn btn-soft" href="${BONN}feeds/vorlagen/${slug(p.reference)}.xml" type="application/atom+xml"><svg class="icon" aria-hidden="true"><use href="#i-rss"/></svg>Diesen Vorgang abonnieren</a>` : ""}</p>
      ${p.superordinated.length ? `<details class="acc"><summary>Bezieht sich auf (${p.superordinated.length})</summary><ul class="related">${rel(p.superordinated)}</ul></details>` : ""}
      <details class="acc"><summary>Quellen dieser Vorlage</summary><ul>
        <li>Quellobjekt: ${link(p.source_object, esc(p.source_object)) || esc(p.source_object)}</li>
        <li>Original: ${link(p.web, "Ratsinformationssystem") || "–"}</li>
        ${sources}</ul></details>
      ${LIMITS}`;
    $("#announce").textContent = `Vorgang ${p.reference} geöffnet: ${p.name}`;
    fillMitmachen();
    showPlans(p, !fromMap);
    if (p.soll && index) showSoll(p);
    if (MOBILE.matches || $("#panel-detail").hidden) setPanel("panel-detail", true);
    $("#detail").scrollTop = 0;
    const ms = markers.get(p.reference) || [];
    if (fromMap) {
      const b = document.querySelector(`.papers button[data-ref="${CSS.escape(p.reference)}"]`);
      if (b) b.scrollIntoView({ block: "nearest" });
    } else {
      // mit Bebauungsplan zoomt showPlans auf die Planfläche
      if (ms.length && !(p.plans || []).some((x) => x.area)) cluster.zoomToShowLayer(ms[0], () => { highlight(); map.panTo(ms[0].getLatLng(), { animate: !REDUCED }); });
      if (MOBILE.matches) $("#detail h3").focus();
    }
  }
  $("#detail").addEventListener("click", (e) => {
    const plan = e.target.closest("[data-open-plan]");
    if (plan) { showPlan(plan.dataset.openPlan); return; }
    const site = e.target.closest("[data-open-site]");
    if (site) { showSite(site.dataset.openSite); return; }
    const ref = e.target.closest("[data-open-ref]");
    if (ref) { const p = papers.find((x) => x.reference === ref.dataset.openRef); if (p) select(p); else window.risKarte.open(ref.dataset.openRef); return; }
    const erk = e.target.closest(".erkl-btn");
    if (erk) {
      const open = erk.getAttribute("aria-expanded") !== "true";
      erk.setAttribute("aria-expanded", String(open));
      document.getElementById(erk.getAttribute("aria-controls")).hidden = !open;
      return;
    }
    const gr = e.target.closest("[data-gremium-name]");
    if (gr) { setPanel("panel-prozesse", true); openProzesse({ tab: "gremien", gremiumName: gr.dataset.gremiumName }); focusPanel("panel-prozesse"); return; }
    const b = e.target.closest(".jump");
    if (b && tl) { if ($("#timeline-wrap").hidden) setPanel("timeline-wrap", true); tl.center(b.dataset.date); }
  });

  // --- Typische Wege (Aggregat) ------------------------------------------------------------------------
  async function showWege() {
    const box = $("#wege");
    if (box.dataset.loaded) return;
    let data;
    try {
      const r = await fetch(BONN + "prozesse.json");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      data = await r.json();
    } catch (e) {
      box.innerHTML = `<p>${index ? "Die typischen Wege konnten nicht geladen werden." : "Für den Pilot nicht verfügbar."}</p>`;
      return;
    }
    box.dataset.loaded = "1";
    // ohne Vorlagenarten (Vorschau ohne Vorlagen: types leer) Hinweis statt leerer Auswahl
    const all = Array.isArray(data && data.types) ? data.types : [];
    if (!all.length) {
      box.innerHTML = `<p>${esc(vorschau ? VORSCHAU_LISTE : "Im Datenbestand gibt es noch keine Verfahrenswege.")}</p>`;
      return;
    }
    const types = all.filter((t) => t.count >= 20).length ? all.filter((t) => t.count >= 20) : all;
    box.innerHTML = `<label class="filters">Vorlagenart <select id="wege-type">${types.map((t) => `<option>${esc(t.paper_type)}</option>`).join("")}</select></label>
      <p class="hint">Weg = Folge der Beratungen (Gremium und Rolle) laut OParl-API. Am Ende steht das Ergebnis der entscheidenden Beratung, wörtlich aus der Quelle (in Anführungszeichen), oder ersatzweise der Stand des Verfahrens. Ganz Köln.</p>
      <div id="wege-list"></div>${LIMITS}`;
    const draw = () => {
      const t = types.find((x) => x.paper_type === $("#wege-type").value);
      if (!t || !Array.isArray(t.paths)) { $("#wege-list").innerHTML = ""; return; }
      const total = t.paths.reduce((s, p) => s + p.count, 0);
      const final = (p) => (p.final_kind === "stand" ? `<span class="final final-stand">Stand: ${esc(p.final)}</span>` : `<span class="final">„${esc(p.final)}“</span>`);
      $("#wege-list").innerHTML = `<p class="count">${t.count} Vorlagen, ${t.distinct_paths} verschiedene Wege; gezeigt die ${t.paths.length} häufigsten (${Math.round(100 * total / t.count)} %).</p>` +
        t.paths.map((p) => `<div class="path"><div class="path-row">${p.stations.length ? p.stations.map((s) => `<span class="station">${esc(s)}</span>`).join('<span class="arrow" aria-hidden="true">→</span>') : '<span class="station">keine Beratung</span>'}
          <span class="arrow" aria-hidden="true">⇒</span>${final(p)}</div>
          <div class="meta">${p.count} Vorlagen · ${(100 * p.count / t.count).toFixed(1)} %</div>
          <div class="share-wrap" aria-hidden="true"><div class="share" style="width:${Math.max(2, 100 * p.count / t.paths[0].count)}%"></div></div></div>`).join("");
    };
    $("#wege-type").addEventListener("change", draw);
    draw();
  }

  // --- Abonnieren (Atom-Feeds) ------------------------------------------------------------------------
  // gleiche Regeln wie pipeline/export.slug und publish.has_paper_feed (Jahresgrenze aus dem Berliner Kalendertag des
  // Datenstands, dataStand nach standTag, wie export.feed_grenze)
  const slug = (s) => String(s).toLowerCase().replace(/[äöüß]/g, (c) => ({ ä: "ae", ö: "oe", ü: "ue", ß: "ss" }[c]))
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const hasPaperFeed = (p) => Boolean(index && dataStand) &&
    ((p.date || "") >= `${Number(dataStand.slice(0, 4)) - 1}-01-01` || ["in Beratung", "offen"].includes(p.stand));
  function subscribeArea() {
    const box = $("#subscribe");
    // nur den Verweis des vorigen Gebiets entfernen; der Feed über ganz Köln steht fest im Kopf (index.html)
    document.querySelectorAll('link[rel="alternate"][data-gebiet]').forEach((l) => l.remove());
    if (!index || area.kind === STADT) {
      box.innerHTML = index ? `<a class="btn btn-soft" href="${BONN}feeds/ganz-${STADT}.xml" type="application/atom+xml"><svg class="icon" aria-hidden="true"><use href="#i-rss"/></svg>Neues aus ganz Köln abonnieren</a>` : "";
      box.hidden = !index;
      fillMitmachen(); fillKontext(); return;
    }
    const href = `${BONN}feeds/${area.kind}-${area.key}.xml`;
    const where = area.kind === "ohne" ? `Vorlagen ohne Ortsbezug ${area.key}` : area.name;
    box.innerHTML = `<a class="btn btn-soft" href="${href}" type="application/atom+xml"><svg class="icon" aria-hidden="true"><use href="#i-rss"/></svg>Neues aus ${esc(where)} abonnieren</a>`;
    box.hidden = false;
    fillMitmachen();
    fillKontext();
    const l = document.createElement("link");
    Object.assign(l, { rel: "alternate", type: "application/atom+xml", href, title: `Ratsatlas Köln – ${where}` });
    l.dataset.gebiet = `${area.kind}:${area.key}`;
    document.head.appendChild(l);
  }

  // --- Termine: kommende Sitzungen -------------------------------------------------------------------
  const isBV = (g) => /^Bezirksvertretung/.test(g || "");
  function areaBezirk() {
    if (!area || !index) return null;
    if (area.kind === "ortsteil") return (index.ortsteile.find((o) => o.slug === area.key) || {}).stadtbezirk;
    if (area.kind === "bezirk") return area.name;
    return null;
  }
  const TAG = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Berlin" });
  const MONAT = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric", timeZone: "Europe/Berlin" });
  const fmtDay = (iso) => TAG.format(new Date(iso + "T12:00:00Z"));
  // Vorlagen je Sitzung („Datum|Gremium“ einer Beratung oder Entscheidung, über die Sitzung verknüpft), je Sitzung in
  // der Reihenfolge der Liste; einmal je Aufruf von showTermine statt je Sitzung über alle Vorlagen (Runde 18,
  // Generalprobe: Rodenkirchen am Telefon 4 s → 0,4 s)
  function vorlagenJeSitzung(list) {
    const je = new Map();
    for (const p of list) {
      for (const s of p.steps) {
        if ((s.typ !== "beratung" && s.typ !== "entscheidung") || !s.date) continue;
        const k = `${s.date}|${s.label}`;
        if (!je.has(k)) je.set(k, new Set());
        je.get(k).add(p);
      }
    }
    return je;
  }
  function showTermine() {
    if (!zeit) return;
    const box = $("#termine");
    const bezirk = areaBezirk();
    const scope = box.querySelector("#termine-scope") ? box.querySelector("#termine-scope").value : "gebiet";
    const today = heute();
    const relevant = (m) => scope === "alle" || !isBV(m.gremium) || !bezirk || m.gremium === `Bezirksvertretung ${bezirk}`;
    const list = zeit.meetings.filter((m) => m.date >= today && relevant(m));
    const where = area.kind === "ohne" ? "Vorlagen ohne Ortsbezug" : area.name;
    // Vorlagen des Gebiets, deren Beratung (über die Sitzung verknüpft) auf dieser Sitzung liegt
    const jeSitzung = vorlagenJeSitzung(papers);
    const onAgenda = (m) => [...(jeSitzung.get(`${m.date}|${m.gremium}`) || [])];
    let month = "";
    const items = list.map((m) => {
      const head = m.date.slice(0, 7) !== month ? `<h3 class="month">${MONAT.format(new Date(m.date + "T12:00:00Z"))}</h3>` : "";
      month = m.date.slice(0, 7);
      const docs = [link(m.web, "Tagesordnung"), link(m.invitation, "Einladung (PDF)")].filter(Boolean).join(" · ");
      const ps = onAgenda(m);
      return `${head}<div class="meeting${m.cancelled ? " cancelled" : ""}">
        <div class="meeting-head"><span class="meeting-date">${fmtDay(m.date)}${m.time ? `, ${esc(m.time)} Uhr` : ""}</span>
          <strong>${esc(m.gremium)}</strong>${m.cancelled ? ' <span class="badge">abgesagt</span>' : ""}</div>
        <div class="meta">${docs || "Tagesordnung noch nicht veröffentlicht"}</div>
        ${ps.length ? `<div class="agenda"><span>Aus ${esc(where)} auf der Tagesordnung:</span><ul>${ps.map((p) => `<li><button type="button" class="linkish" data-ref="${esc(p.reference)}">${esc(p.reference)} – ${esc(p.name)}</button></li>`).join("")}</ul></div>` : ""}
      </div>`;
    }).join("");
    box.innerHTML = `<p class="hint">Sitzungen von Rat, Ausschüssen, Beiräten und Bezirksvertretungen laut OParl-API der Stadt. Sie sind in der Regel öffentlich; Ort und Tagesordnung stehen in der Einladung, die etwa zwei Wochen vorher erscheint.</p>
      <div class="filters termine-filters"><label>Gremien
        <select id="termine-scope"><option value="gebiet"${scope === "gebiet" ? " selected" : ""}>${bezirk ? `Rat, Ausschüsse und Bezirksvertretung ${esc(bezirk)}` : "alle (kein Stadtbezirk gewählt)"}</option>
        <option value="alle"${scope === "alle" ? " selected" : ""}>alle Gremien</option></select></label>
        <a class="btn btn-cta" href="${BONN}termine.ics" download><svg class="icon" aria-hidden="true"><use href="#i-download"/></svg>Alle Termine in den Kalender (.ics)</a></div>
      <p class="count">${list.length} kommende Sitzungen</p>
      ${items || "<p>Keine kommenden Sitzungen im Datenbestand.</p>"}`;
    box.querySelector("#termine-scope").addEventListener("change", showTermine);
  }
  $("#termine").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-ref]");
    if (b) { const p = papers.find((x) => x.reference === b.dataset.ref); if (p) { closePanel("panel-termine"); select(p); } }
  });

  // --- Menü „Mitmachen“: Abonnieren und Hinweise ----------------------------------------------------
  function fillMitmachen() {
    if (!area) return;
    const where = area.kind === "ohne" ? `Vorlagen ohne Ortsbezug ${area.key}` : area.name;
    const acts = [];
    if (index) acts.push(area.kind === STADT
      ? `<a class="btn btn-cta" href="${BONN}feeds/ganz-${STADT}.xml" type="application/atom+xml"><svg class="icon" aria-hidden="true"><use href="#i-rss"/></svg>Neues aus ganz Köln</a>`
      : `<a class="btn btn-cta" href="${BONN}feeds/${area.kind}-${area.key}.xml" type="application/atom+xml"><svg class="icon" aria-hidden="true"><use href="#i-rss"/></svg>Neues aus ${esc(where)}</a>`);
    if (selected && hasPaperFeed(selected)) acts.push(`<a class="btn btn-soft" href="${BONN}feeds/vorlagen/${slug(selected.reference)}.xml" type="application/atom+xml"><svg class="icon" aria-hidden="true"><use href="#i-rss"/></svg>Vorgang ${esc(selected.reference)}</a>`);
    acts.push('<a class="btn btn-soft" href="rss/">Alle Feeds und Anleitung</a>');
    $("#cta-feed").innerHTML = acts.join("");
    $("#cta-feed-text").textContent = `Neue Vorlagen und Beratungsergebnisse aus ${where} im Feed-Reader erhalten${selected ? ", oder nur den gewählten Vorgang" : ""}.`;
    const report = $("#cta-report");
    report.href = selected ? reportLink(selected) : `${REPO}/issues/new/choose`;
    report.lastChild.textContent = selected ? `Hinweis zu ${selected.reference}` : "Hinweis geben";
  }

  // --- Suche in der Leiste mit Schnellfiltern (Mega-Menü „Suche“) ----------------------------------
  function setScope(v) {
    const r = document.querySelector(`input[name="scope"][value="${v}"]`);
    if (r) r.checked = true;
    document.querySelectorAll(".scope-switch [data-scope]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.scope === v)));
  }
  function chip(label, pressed, data, n) {
    return `<button type="button" class="chip" aria-pressed="${pressed}" ${data}>${esc(label)}${n != null ? ` <span class="n">${n}</span>` : ""}</button>`;
  }
  function fillChips() {
    const theme = $("#f-theme").value, party = $("#f-party").value;
    const counts = {};
    for (const p of papers) for (const t of p.themes || []) counts[t.theme] = (counts[t.theme] || 0) + 1;
    // Zahlen nur mit geladenem Gebiet: bei „ganz Köln“ (noch kein Gebiet) gibt es keine Vorlagen zu zählen; bis Runde 18
    // stand an jedem Thema „0“
    const local = scope() === "gebiet" && Boolean(area) && area.kind !== STADT;
    $("#chips-theme").innerHTML = Object.entries(THEMES).map(([k, v]) => chip(v, theme === k, `data-theme="${k}"`, local ? counts[k] || 0 : null)).join("");
    const parties = [...$("#f-party").options].map((o) => o.value).filter(Boolean);
    $("#chips-party").innerHTML = parties.map((v) => chip(v === "Koalition" ? "Koalition (gemeinsam)" : v, party === v, `data-party="${esc(v)}"`)).join("")
      || '<span class="hint">Im gewählten Gebiet gibt es keine zugeordneten Einreichenden.</span>';
    document.querySelectorAll(".scope-switch [data-scope]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.scope === scope())));
    $("#mega-count").textContent = $("#count").textContent;
  }
  function applyFromBar() {
    shown = LIST_STEP;
    fillParties();
    render();
    syncUrl();
    if (openMegaId === "mega-suche") fillChips();
  }
  function initSearchBar() {
    const q = $("#q");
    q.addEventListener("focus", () => openMega("mega-suche"));
    q.addEventListener("input", debounce(() => {
      $("#f-text").value = q.value;
      $("#doc-status").textContent = "";
      if (q.value && index && scope() !== STADT) setScope(STADT);
      openMega("mega-suche");
      applyFromBar();
    }, 200));
    $("#nav-search").addEventListener("submit", (e) => {
      e.preventDefault();
      setPanel("panel-list", true);
      closeMega();
      $("#papers").focus();
    });
    $("#f-text").addEventListener("input", () => { q.value = $("#f-text").value; });
    $("#mega-suche").addEventListener("click", (e) => {
      const sc = e.target.closest("[data-scope]");
      if (sc) { setScope(sc.dataset.scope); return applyFromBar(); }
      const t = e.target.closest("[data-theme]");
      if (t) { $("#f-theme").value = $("#f-theme").value === t.dataset.theme ? "" : t.dataset.theme; return applyFromBar(); }
      const pa = e.target.closest("[data-party]");
      if (pa) { $("#f-party").value = $("#f-party").value === pa.dataset.party ? "" : pa.dataset.party; return applyFromBar(); }
    });
    $("#mega-show").addEventListener("click", () => { setPanel("panel-list", true); closeMega(); focusPanel("panel-list"); });
    $("#doc-search").addEventListener("click", runDocSearch);
    $("#mega-reset").addEventListener("click", () => { q.value = ""; resetFilters(); fillChips(); });
    if (!index) document.querySelector(".scope-switch").hidden = true;
  }

  // --- Auswertung: Kennzahlen zum Gebiet und Verfahrenswege ------------------------------------------
  function openAuswertung(tab, focusTab) {
    closeMega();
    setPanel("panel-auswertung", true);
    const stats = tab === "stats";
    $("#tab-stats").setAttribute("aria-selected", String(stats)); $("#tab-stats").tabIndex = stats ? 0 : -1;
    $("#tab-wege").setAttribute("aria-selected", String(!stats)); $("#tab-wege").tabIndex = stats ? -1 : 0;
    $("#stats").hidden = !stats; $("#wege").hidden = stats;
    if (stats) showStats(); else showWege();
    (focusTab ? document.getElementById(stats ? "tab-stats" : "tab-wege") : $("#auswertung-heading")).focus();
  }
  function bars(title, rows, attr) {
    const max = Math.max(1, ...rows.map((r) => r.n));
    return `<section class="stat-block"><h3>${esc(title)}</h3><ul class="bars">${rows.map((r) => `<li><button type="button" class="bar" ${attr}="${esc(r.key)}" aria-label="${esc(r.label)}: ${r.n} Vorlagen – Liste danach filtern">
      <span>${esc(r.label)}</span><span class="bar-track" aria-hidden="true"><span class="bar-fill" style="width:${(100 * r.n / max).toFixed(1)}%"></span></span><span class="bar-n">${r.n}</span></button></li>`).join("")}</ul></section>`;
  }
  function showStats() {
    const list = papers, where = area.kind === "ohne" ? `Vorlagen ohne Ortsbezug ${area.key}` : area.name;
    // Vorschau ohne Vorlagen: Grund nennen statt „0 Vorlagen“ mit leeren Überschriften
    if (vorschau) { $("#stats").innerHTML = `<p class="hint">${esc(VORSCHAU_LISTE)}</p>`; return; }
    if (area.kind === STADT) { $("#stats").innerHTML = `<p class="hint">Die Kennzahlen beziehen sich auf ein Gebiet. Wählen Sie auf der Karte oder oben ein Gebiet; die Verfahrenswege im Reiter daneben gelten für ganz Köln.</p>`; return; }
    const count = (f) => { const c = new Map(); for (const p of list) for (const k of f(p)) c.set(k, (c.get(k) || 0) + 1); return c; };
    const th = count((p) => (p.themes || []).map((t) => t.theme));
    const pa = count((p) => p.parties || []);
    const yr = count((p) => (p.date ? [p.date.slice(0, 4)] : []));
    const st = count((p) => [p.stand]);
    $("#stats").innerHTML = `<p class="hint">${list.length} Vorlagen in ${esc(where)}. Ein Klick auf einen Balken filtert die Liste. Themen und Parteien sind abgeleitet.</p>
      ${bars("Nach Thema", Object.keys(THEMES).filter((k) => th.get(k)).map((k) => ({ key: k, label: THEMES[k], n: th.get(k) })).sort((a, b) => b.n - a.n), "data-stat-theme")}
      ${pa.size ? bars("Nach Einreichenden (Partei, Fraktion, Verwaltung)", [...pa].map(([k, n]) => ({ key: k, label: k, n })).sort((a, b) => b.n - a.n), "data-stat-party") : ""}
      ${bars("Nach Jahr (Datum der Vorlage)", [...yr].map(([k, n]) => ({ key: k, label: k, n })).sort((a, b) => a.key.localeCompare(b.key)), "data-stat-year")}
      ${bars("Nach Stand des Verfahrens", [...st].map(([k, n]) => ({ key: k, label: k, n })).sort((a, b) => b.n - a.n), "data-stat-stand")}`;
  }
  $("#stats").addEventListener("click", (e) => {
    const b = e.target.closest(".bar");
    if (!b) return;
    // die Zahl am Balken gilt für das ganze Gebiet: übrige Filter und Zeitraum zurücksetzen
    $("#filters").reset();
    $("#q").value = "";
    range = null;
    if (tl) tl.reset();
    setScope("gebiet");
    if (b.dataset.statTheme) $("#f-theme").value = b.dataset.statTheme;
    if (b.dataset.statParty) { fillParties(); $("#f-party").value = b.dataset.statParty; }
    if (b.dataset.statStand) $("#f-stand").value = b.dataset.statStand;
    if (b.dataset.statYear && tl) { const y = b.dataset.statYear; tl.setRange(`${y}-01-01`, `${y}-12-31`); range = [`${y}-01-01`, `${y}-12-31`]; }
    shown = LIST_STEP;
    render();
    syncUrl();
    closePanel("panel-auswertung");
    setPanel("panel-list", true);
    focusPanel("panel-list");
  });

  // --- Reiter „Prozesse“ (site/prozesse.js, erst beim Öffnen geladen) ---------------------------------------
  let pzState = null, pzReady = null;
  function openProzesse(s) {
    pzReady ||= import("./prozesse.js").then(async (m) => {
      await m.init({
        BONN, loadSoll,
        onState(st) { pzState = st; syncUrl(); },
        async openRef(ref) {
          setPanel("panel-prozesse", false);
          const p = papers.find((x) => x.reference === ref);
          if (p) select(p); else await window.risKarte.open(ref);
        },
        filterGremium(name) {
          const sel = $("#f-gremium");
          if (![...sel.options].some((o) => o.value === name)) return false;
          sel.value = name;
          sel.dispatchEvent(new Event("input", { bubbles: true }));
          setPanel("panel-prozesse", false);
          setPanel("panel-list", true);
          focusPanel("panel-list");
          return true;
        },
        filterAmt(name) {
          const sel = $("#f-amt");
          if (![...sel.options].some((o) => o.value === name)) return false;
          sel.value = name;
          sel.dispatchEvent(new Event("input", { bubbles: true }));
          setPanel("panel-prozesse", false);
          setPanel("panel-list", true);
          focusPanel("panel-list");
          return true;
        },
      });
      return m;
    }).catch((e) => { pzReady = null; console.warn("Prozesse nicht geladen", e); return null; });   // beim nächsten Öffnen erneut
    return pzReady.then((m) => { if (m) m.show(s); return m; });
  }

  // --- Fläche „Mitmachen in Bonn“ (site/beteiligung.js, erst beim Öffnen geladen) --------------------------
  let mmState = null, mmReady = null;
  function openMitmachen(s) {
    mmReady ||= import("./beteiligung.js").then(async (m) => {
      await m.init({
        loadSoll,
        meetings: () => (zeit ? zeit.meetings : []),
        onState(st) { mmState = st; syncUrl(); },
        openTermine() { setPanel("panel-mitmachen", false); setPanel("panel-termine", true); showTermine(); focusPanel("panel-termine"); },
        openPlaene() {
          setPanel("panel-mitmachen", false);
          const b = document.querySelector(".map-plans");
          if (b && !planOn) b.click();
        },
        openGremium(name) {
          setPanel("panel-mitmachen", false);
          setPanel("panel-prozesse", true);
          openProzesse({ tab: "gremien", gremiumName: name });
        },
      });
      return m;
    }).catch((e) => { mmReady = null; console.warn("Mitmachen nicht geladen", e); return null; });   // beim nächsten Öffnen erneut
    return mmReady.then((m) => { if (m) m.show(s || { bezirk: mmState ? mmState.bezirk : areaBezirk() || "Innenstadt" }); return m; });
  }

  // --- URL-Zustand -----------------------------------------------------------------------------------
  function syncUrl() {
    if (!area) return;
    const url = new URL(location.href);
    if (area.kind === STADT) url.searchParams.delete("gebiet"); else url.searchParams.set("gebiet", `${area.kind}:${area.key}`);
    if (tl && range) { const s = tl.getState(); for (const k of ["von", "bis", "zoom", "achse"]) url.searchParams.set(k, s[k]); }
    else for (const k of ["von", "bis", "zoom", "achse"]) url.searchParams.delete(k);
    const state = { thema: $("#f-theme").value, partei: $("#f-party").value, suche: scope() === STADT ? STADT : "" };
    state.farbe = colorBy === "thema" ? "thema" : "";
    state.flaechen = navMetric !== navDefault ? navMetric : "";
    state.plaene = planOn ? "1" : "";
    state.plan = !selected && shownPlan ? shownPlan : "";
    state.baustellen = bauOn ? "1" : "";
    state.baustelle = !selected && shownSite ? shownSite : "";
    state.ebenen = [...Object.keys(KX), ...Object.keys(PX), ...Object.keys(EX)].filter((k) => kxOn.has(k)).join(",");
    const pz = !$("#panel-prozesse").hidden && pzState;
    state.prozesse = pz ? pz.tab : "";
    state.ansicht = pz && pz.view === "liste" ? "liste" : "";
    state.verfahren = pz && pz.tab === "verfahren" && pz.verfahren ? pz.verfahren : "";
    state.gremium = pz && pz.tab === "gremien" && pz.gremium ? pz.gremium : "";
    state.amt = pz && pz.tab === "aemter" && pz.amt ? pz.amt : "";
    const mm = !$("#panel-mitmachen").hidden && mmState;
    state.mitmachen = mm ? "1" : "";
    state.bezirk = mm ? mm.bezirk : "";
    for (const [k, v] of Object.entries(state)) (v ? url.searchParams.set(k, v) : url.searchParams.delete(k));
    url.hash = selected ? encodeURIComponent(selected.reference) : "";
    history.replaceState(null, "", url);
  }

  // --- Start -----------------------------------------------------------------------------------------
  // Elemente mit data-funktion (index.html) nur zeigen, wenn die Funktion freigegeben ist; Hinweis auf Testdaten.
  // Vorschau ohne Ratsvorlagen (Kennzeichen vorschau): data-vorschau="aus" ausblenden (Auswertung, Schnellfilter der
  // Suche, Kalender), data-vorschau="nur" zeigen (Hinweise an ihrer Stelle)
  function applyFunktionen(fn, idx) {
    document.querySelectorAll("[data-funktion]").forEach((el) => { el.hidden = !fn[el.dataset.funktion]; });
    const hinweis = $("#testdaten-hinweis");
    if (hinweis) hinweis.hidden = !(idx && idx.meta && idx.meta.testdaten);
    const vorschauHinweis = $("#vorschau-hinweis");
    if (vorschauHinweis) vorschauHinweis.hidden = !vorschau;
    // Kennzeichen für die Tour (site/tour.js): Texte der Vorschau statt Beschreibungen ausgeblendeter Funktionen
    if (vorschau) document.documentElement.dataset.vorschau = "ja";
    else delete document.documentElement.dataset.vorschau;
    if (vorschau) document.querySelectorAll('[data-vorschau="aus"]').forEach((el) => { el.hidden = true; });
    document.querySelectorAll('[data-vorschau="nur"]').forEach((el) => { el.hidden = !vorschau; });
  }
  const QUELLE_NAME = { "oparl-koeln": "Ratsinformationssystem", "geo-koeln": "Gebiete", "strassen-koeln": "Straßen",
    "adressen-koeln": "Adressen", "bplan-koeln": "Bebauungspläne", osm: "OpenStreetMap" };

  async function start() {
    // Alle Startdaten gleichzeitig anfordern (index.html lädt sie zusätzlich vorab); ohne Glossar erscheinen
    // Schlüssel statt Erläuterungen; ohne index.json (Pilot) entfallen Zeitleiste und Baustellen
    // Daten, die das erste Bild nicht braucht (Zeitleiste, Baustellen, Kontext, Mängelmelder), mit niedriger
    // Priorität, damit sie die Kacheln nicht bremsen (Priority Hints; Browser ohne Unterstützung ignorieren sie)
    const json = (url, priority = "auto") => fetch(url, { priority }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const startGebiet = new URLSearchParams(location.search).get("gebiet") || DEFAULT_AREA;
    const [gKind, gKey] = startGebiet.split(":");
    // 1. index.json (klein, vorab angefordert) gibt den ersten Ausschnitt; die Kacheln laden sofort
    const idx = await json(BONN + "index.json");
    vorschau = Boolean(idx && idx.meta && idx.meta.vorschau);
    // Bonner Zusatzthemen nur, wenn index.json sie freigibt (config.ZUSATZTHEMEN); sonst keine Anfrage
    const fn = (idx && idx.meta && idx.meta.funktionen) || {};
    // Freigaben und Vorschau-Kennzeichnung vor Karte und Kacheln anwenden, damit ausgeblendete Elemente (Auswertung,
    // Schnellfilter, Kalender, Filter) nicht kurz sichtbar sind
    applyFunktionen(fn, idx);
    $("#filters").hidden = vorschau;   // Filter ohne Vorlagen hätten nur „alle“
    createMap(startBounds(idx, startGebiet));
    // 2. alles Übrige nach den sichtbaren Kacheln (höchstens 2,5 s warten)
    await kachelnGeladen(2500);
    if ((gKind === "ortsteil" || gKind === "bezirk") && /^[a-z0-9-]+$/.test(gKey || "")) {
      const datei = `${BONN}${gKind === "ortsteil" ? "ortsteile" : "bezirke"}/${gKey}.json`;
      vorab.set(datei, fetch(datei));
    }
    const shapes = Promise.all([loadGeo("ortsteil"), loadGeo("bezirk")]);
    const opt = (an, url) => (an ? json(url, "low") : Promise.resolve(null));
    // Baustellen mit möglichen Umsetzungen (nur Konfidenz hoch); ohne Datei bleibt die Funktion ausgeblendet
    // Vorschau: keine zeit.json (pipeline/export.py schreibt sie nur mit Vorlagen), daher keine Anfrage
    const [g, z, bs, kx, an, eb] = await Promise.all([json(GLOSSAR_URL), vorschau ? null : json(BONN + "zeit.json", "low"),
      opt(fn.baustellen, BONN + "baustellen.json"), opt(fn.kontext, BONN + "kontext.json"), opt(fn.anliegen, BONN + "anliegen.json"),
      opt(fn.kontext, BONN + "ebenen.json")]);
    index = idx;
    kontext = index && kx && kx.ortsteile ? kx : null;
    for (const e of (eb && eb.ebenen) || []) EX[e.key] = e;
    ebenenIdx = Object.keys(EX).length ? eb : null;
    anliegen = kontext && an && an.ortsteile ? an : null;
    zeit = index ? z : null;
    bau = index && bs && bs.baustellen.length ? bs : null;
    for (const b of bau ? bau.baustellen : []) for (const c of b.kandidaten) {
      if (!bauByRef.has(c.drucksache)) bauByRef.set(c.drucksache, []);
      bauByRef.get(c.drucksache).push({ b, c });
    }
    if (g) {
      ({ ergebnisse: GLOSSAR, hinweise: NOTES, schritte: STEP_LABEL, evidenz: STATUS_TEXT, staende: STAND_TEXT = {}, arten: ARTEN = {}, kuerzel: KUERZEL = {} } = g);
      BEGRIFF = Object.fromEntries((g.begriffe || []).filter((b) => b.anker).map((b) => [b.anker, b]));
    }
    [geo.ortsteil, geo.bezirk] = await shapes;
    initMap();
    fillAreaSelect();
    initNav();
    if (zeit) {
      tl = Timeline.create($("#timeline-wrap"), {
        onRange(a, b) { range = [a, b]; shown = LIST_STEP; render(); syncUrl(); },
        onDate(d) { tl.center(d); },
        onSite(id) { showSite(id); },
      });
    } else {
      setPanel("timeline-wrap", false);
      toggleFor("timeline-wrap").hidden = true;
    }
    applyLayout();
    MOBILE.addEventListener("change", applyLayout);
    NARROW.addEventListener("change", applyLayout);
    $("#filters").addEventListener("submit", (e) => e.preventDefault());
    $("#filters").addEventListener("input", (e) => {
      if (e.target.id === "f-text") return renderSoon();
      shown = LIST_STEP;
      if (e.target.name === "scope") { fillParties(); setScope(e.target.value); }
      render();
      syncUrl();
    });
    $("#f-area").addEventListener("change", (e) => { range = null; if (tl) tl.reset(); loadArea(e.target.value); });
    $("#papers").addEventListener("click", (e) => {
      if (e.target.closest("#more")) {
        // Fokus auf den ersten neu gezeigten Eintrag, damit Tastatur und Vorleseprogramm an der Stelle weitermachen
        const vorher = shown;
        shown += LIST_STEP; render(true);
        const neu = $("#papers").children[vorher];
        const ziel = neu && neu.querySelector("button, a[href]");
        if (ziel) ziel.focus();
        return;
      }
      if (e.target.closest("#reset-filters")) { resetFilters(); return; }
      const g = e.target.closest("button[data-gref]");
      if (g) { openGlobal(g.dataset.gref, g.dataset.area); return; }
      const b = e.target.closest("button[data-ref]");
      if (b) select(papers.find((p) => p.reference === b.dataset.ref));
    });
    // Vorschau in der Zeitleiste nur beim Wechsel der Vorlage (mouseover feuert für jedes Kindelement erneut)
    let hoverRef = null;
    $("#papers").addEventListener("mouseover", (e) => {
      const b = e.target.closest("button[data-ref]");
      if (!b || !tl || b.dataset.ref === hoverRef) return;
      hoverRef = b.dataset.ref;
      tl.select(papers.find((p) => p.reference === hoverRef), true);
    });
    $("#papers").addEventListener("mouseleave", () => { hoverRef = null; if (tl) tl.select(selected); });
    // Menü „Mitmachen“: Termine; Menü „Auswertung“: Reiter Kennzahlen und Verfahrenswege
    if (zeit) $("#cta-termine").addEventListener("click", () => { setPanel("panel-termine", true); showTermine(); focusPanel("panel-termine"); });
    else $("#cta-termine").hidden = true;
    $("#cta-mitmachen").addEventListener("click", () => { closeMega(); setPanel("panel-mitmachen", true); focusPanel("panel-mitmachen"); });
    document.querySelectorAll("[data-open-tab]").forEach((b) => b.addEventListener("click", () => openAuswertung(b.dataset.openTab)));
    $("#tab-stats").addEventListener("click", () => openAuswertung("stats"));
    $("#tab-wege").addEventListener("click", () => openAuswertung("wege"));
    $("#panel-auswertung .tabs").addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); openAuswertung($("#tab-stats").getAttribute("aria-selected") === "true" ? "wege" : "stats", true); }
    });
    initSearchBar();
    document.querySelectorAll('.toggle[data-panel="panel-assistent"]').forEach((b) => {
      b.addEventListener("pointerenter", loadChat, { once: true });
      b.addEventListener("focus", loadChat, { once: true });
    });
    $("#f-theme").innerHTML = '<option value="">alle</option>' + Object.entries(THEMES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    if (index) $("#scope").hidden = false;
    const params = new URLSearchParams(location.search);
    // fehlerhafte Kodierung im Anker (abgeschnittener Link) darf den Start nicht verhindern (Code-Prüfung 23.10.2026)
    let ref = "";
    try { ref = decodeURIComponent(location.hash.slice(1)); } catch (e) { ref = ""; }
    if (Object.hasOwn(THEMES, params.get("thema") || "")) $("#f-theme").value = params.get("thema");
    if (index && params.get("suche") === STADT) document.querySelector(`input[name="scope"][value="${STADT}"]`).checked = true;
    if (params.get("partei")) await loadSearch();
    await loadArea(params.get("gebiet") || DEFAULT_AREA, true);
    if (params.get("partei")) { fillParties(); $("#f-party").value = params.get("partei"); render(); }
    const von = params.get("von"), bis = params.get("bis");
    // Startzustand: nur „Los geht's“; Liste und Zeitleiste öffnen sich, wenn der Link Filter oder einen Zeitraum enthält
    if (["thema", "partei", "suche"].some((k) => params.get(k))) setPanel("panel-list", true);
    if (tl && ISO_DAY.test(von || "") && ISO_DAY.test(bis || "") && !Number.isNaN(Date.parse(von)) && !Number.isNaN(Date.parse(bis))) {
      setPanel("timeline-wrap", true);
      tl.setState({ von, bis, zoom: params.get("zoom"), achse: params.get("achse") });
      const st = tl.getState();   // die Zeitleiste ordnet vertauschte Daten; Liste und Zeitleiste zeigen dasselbe
      range = [st.von, st.bis];
      render();
    }
    if (planOn) drawAllPlans();
    if (bauOn) drawSites();
    if (kxOn.size) drawKx();
    const initial = papers.find((p) => p.reference === ref);
    if (initial) select(initial);
    else if (params.get("plan")) await showPlan(params.get("plan"));
    else if (params.get("baustelle") && bau && bau.baustellen.some((b) => b.id === params.get("baustelle"))) showSite(params.get("baustelle"));
    else showIntro();
    if (params.get("mitmachen") === "1") {
      setPanel("panel-mitmachen", true);
      await openMitmachen({ bezirk: params.get("bezirk") || areaBezirk() || "Innenstadt" });
    }
    if (["verfahren", "gremien", "aemter"].includes(params.get("prozesse"))) {
      setPanel("panel-prozesse", true);
      await openProzesse({ tab: params.get("prozesse"), view: params.get("ansicht") === "liste" ? "liste" : "schaubild",
        verfahren: params.get("verfahren"), gremium: params.get("gremium"), amt: params.get("amt") });
    }
    syncUrl();
  }
  // Schnittstelle für den Ratsassistenten (site/chat/ui.js): Vorlage öffnen, Kontext der Karte
  window.risKarte = {
    async open(ref) {
      const s = await loadSearch();
      const row = s && s.rows.find((r) => r[0] === ref);
      const key = row && s.areas[row[5]] ? s.areas[row[5]].key : null;
      if (!key) return false;
      await openGlobal(ref, key);
      return selected?.reference === ref;
    },
    context() {
      return { gebiet: area ? area.name : null, von: range ? range[0] : null, bis: range ? range[1] : null };
    },
    // für die Tour (site/tour.js): Flächen und Menüs öffnen, ein Beispiel zeigen, Lage des Gebiets auf der Karte
    ui: {
      panel(id, open) { if (!toggleFor(id) || !toggleFor(id).hidden) setPanel(id, open); },
      mapMenu(open) { const b = document.querySelector(".map-menu"); if (b && (b.getAttribute("aria-expanded") === "true") !== open) b.click(); },
      menu(id) { if (id) openMega(id); else closeMega(); },
      nav(open) { if (MOBILE.matches || !open) setNav(open); },
      // Beispielgebiet der Tour vorab laden, solange die ersten Schritte laufen
      prefetch() { if (area && area.kind === STADT && index) fetch(`${BONN}ortsteile/altstadt-nord.json`).catch(() => {}); },
      async example() {
        if (selected) return true;
        // in der Übersicht ein Beispielgebiet laden
        if (area.kind === STADT) await loadArea("ortsteil:altstadt-nord", true);
        const list = filtered();
        // jüngste entschiedene Vorlage mit Ort auf der Karte, Entscheidung und Folgevorlage (selbst keine Folgevorlage)
        const has = (x, typ) => x.steps.some((s) => s.typ === typ);
        const p = list.filter((x) => x.stand === "entschieden" && !x.reference.includes("-") && has(x, "entscheidung") && has(x, "folgevorlage")
          && (markers.get(x.reference) || []).length).sort((a, b) => String(b.date).localeCompare(String(a.date)))[0] || list[0];
        if (p) select(p);
        return Boolean(p);
      },
      areaRect() {
        if (!outline) return null;
        const b = outline.getBounds(), r = map.getContainer().getBoundingClientRect();
        const nw = map.latLngToContainerPoint(b.getNorthWest()), se = map.latLngToContainerPoint(b.getSouthEast());
        return { left: r.left + nw.x, top: r.top + nw.y, right: r.left + se.x, bottom: r.top + se.y };
      },
    },
  };

  start().catch((err) => { $("#detail").innerHTML = `<p>Die Daten konnten nicht geladen werden (${esc(err.message)}).</p>`; });
})();
