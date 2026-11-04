// Zeitleiste (PROMPT_zeitleiste_v0.1): eigenständiges Modul ohne Abhängigkeiten, SVG.
//
// Schnittstelle
//   const tl = Timeline.create(container, options)
//     options.onRange(from, to)    gewählter Zeitraum (ISO-Datum) – entprellt
//     options.onDate(isoDate)      Klick auf einen Zeitpunkt (Sitzung, Station)
//   tl.setData({ months, density, meetings, terms, dataStart, dataStand, dimension })
//   tl.setPapers(papers)           Einzelobjekte des Gebiets (für Woche/Tag und Auswahlspur)
//   tl.select(paper | null)        Stationen einer Vorlage in der Auswahlspur zeigen
//   tl.setSites(baustellen)        Baustellen des Gebiets als eigene Spur (Zeiträume, Termine unverbindlich)
//     options.onSite(id)           Klick auf eine Baustelle
//   tl.setRange(from, to), tl.center(isoDate), tl.getState(), tl.setState(state)
//
// Spuren: Übersicht (Minimap), Dichte, Sitzungen, Kontext (Wahlperioden), Auswahl, Baustellen (falls vorhanden).
// Bedienung: Ziehen, Shift/Trackpad-Scroll, ‹ ›, + −, Strg/Cmd+Mausrad, Doppelklick, Pfeiltasten,
// Pos1/Ende; Zeitraum über zwei Schieberegler (role="slider").
(function (global) {
  "use strict";
  const DAY = 864e5;
  const LEVELS = [
    { name: "Jahr", span: 365 * 3 * DAY, bin: "month", step: 365 * DAY },
    { name: "Quartal", span: 365 * DAY, bin: "month", step: 91 * DAY },
    { name: "Monat", span: 120 * DAY, bin: "week", step: 30 * DAY },
    { name: "Woche", span: 35 * DAY, bin: "day", step: 7 * DAY },
    { name: "Tag", span: 10 * DAY, bin: "day", step: DAY },
  ];
  const PILOT_GREMIEN = ["Bezirksvertretung Bonn", "Rat", "Ausschuss für Mobilität und Verkehr",
    "Ausschuss für Wohnen, Planung und Bauen", "Hauptausschuss"];
  const SHORT = { "Bezirksvertretung Bonn": "BV Bonn", "Ausschuss für Mobilität und Verkehr": "Mobilität",
    "Ausschuss für Wohnen, Planung und Bauen": "Planung", "Hauptausschuss": "Hauptausschuss", "Rat": "Rat" };
  const NS = "http://www.w3.org/2000/svg";
  const T_CACHE = new Map();  // Datumsangaben werden bei jedem Zeichnen mehrfach umgerechnet
  const t = (iso) => {
    let v = T_CACHE.get(iso);
    if (v === undefined) {
      v = new Date(iso.length === 7 ? iso + "-01T00:00:00" : iso.slice(0, 10) + "T00:00:00").getTime();
      T_CACHE.set(iso, v);
    }
    return v;
  };
  const ORIGIN = Date.UTC(2019, 8, 30);
  // Kalendertag seit dem 30.09.2019 in Ortszeit (Fächer der Zeitleiste)
  const dayNo = (ms) => { const d = new Date(ms); return Math.round((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) - ORIGIN) / DAY); };
  const addDays = (ms, k) => { const d = new Date(ms); d.setDate(d.getDate() + k); return d.getTime(); };
  const iso = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const DE = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
  const DE_MONTH = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" });
  const DE_MON = new Intl.DateTimeFormat("de-DE", { month: "short" });
  const de = (ms) => DE.format(ms);
  const deMonth = (ms) => DE_MONTH.format(ms);
  const el = (name, attrs, parent) => {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  function create(root, options) {
    const o = Object.assign({ onRange() {}, onDate() {}, onSite() {} }, options);
    let data = null, papers = [], selected = null, preview = false, level = 1, sites = [];
    let view = [0, 1], range = [0, 1], extent = [0, 1], debounce;

    root.classList.add("tl");
    root.innerHTML = `
      <div class="tl-bar">
        <div class="tl-group" role="group" aria-label="Zeitleiste verschieben">
          <button type="button" class="tl-btn" data-act="prev" aria-label="Früher">‹</button>
          <button type="button" class="tl-btn" data-act="next" aria-label="Später">›</button>
        </div>
        <div class="tl-group" role="group" aria-label="Zoom">
          <button type="button" class="tl-btn" data-act="out" aria-label="Herauszoomen">−</button>
          <span class="tl-level" aria-live="polite"></span>
          <button type="button" class="tl-btn" data-act="in" aria-label="Hineinzoomen">+</button>
        </div>
        <div class="tl-group tl-jumps" role="group" aria-label="Springen">
          <button type="button" class="tl-chip" data-act="start">Anfang</button>
          <button type="button" class="tl-chip" data-act="today">heute</button>
          <button type="button" class="tl-chip" data-act="stand">Datenstand</button>
        </div>
        <div class="tl-group tl-presets" role="group" aria-label="Zeitraum wählen">
          <button type="button" class="tl-chip" data-preset="12m">letzte 12 Monate</button>
          <button type="button" class="tl-chip" data-preset="term">laufende Wahlperiode</button>
          <button type="button" class="tl-chip" data-preset="all">gesamter Bestand</button>
        </div>
        <label class="tl-dim">Achse
          <select data-act="dim">
            <option value="vorlage">Datum der Vorlage</option>
            <option value="sitzung">Sitzungsdatum (abgeleitet)</option>
          </select>
        </label>
      </div>
      <div class="tl-stage" tabindex="0" role="group"
           aria-label="Zeitleiste. Pfeiltasten verschieben, Plus und Minus zoomen, Pos1 und Ende springen."
           aria-describedby="tl-help">
        <svg class="tl-svg" aria-hidden="true"></svg>
        <div class="tl-handle" role="slider" tabindex="0" data-h="0" aria-label="Beginn des Zeitraums"></div>
        <div class="tl-handle" role="slider" tabindex="0" data-h="1" aria-label="Ende des Zeitraums"></div>
      </div>
      <p class="tl-range"></p>
      <p class="tl-hint">Zeitraum wählen: Griffe ziehen, eine Voreinstellung nutzen oder mit gedrückter Umschalttaste über die Balken ziehen.</p>
      <p class="visually-hidden tl-live" aria-live="polite"></p>
      <p id="tl-help" class="visually-hidden">Der gewählte Zeitraum filtert Liste und Karte.</p>
      <details class="acc tl-table"><summary>Monatsübersicht als Tabelle</summary><div class="tl-table-body" tabindex="0" role="region" aria-label="Monatsübersicht"></div></details>
      <details class="acc"><summary>Was die Zeitleiste nicht zeigt</summary>
        <ul class="tl-limits">
          <li>Vorlagen vor Oktober 2019 (nur im ALLRIS-Archiv).</li>
          <li>Verwaltungsinterne Vorlaufzeiten vor dem Datum der Vorlage.</li>
          <li>Die Umsetzung von Beschlüssen (Beschlusskontrolle ohne Schnittstelle).</li>
          <li>Sitzungsdaten von Beratungen, die OParl-Lite (noch) nicht verknüpft; sie fehlen in der Achse „Sitzungsdatum“.</li>
          <li>Baustellen vor Beginn des Archivs; ihre Termine sind laut Quelle unverbindlich (Balken mit unscharfen Enden).</li>
        </ul>
      </details>`;
    const svg = root.querySelector(".tl-svg"), stage = root.querySelector(".tl-stage");
    const handles = [...root.querySelectorAll(".tl-handle")];
    const dimSel = root.querySelector("[data-act=dim]");
    const LAYOUT = { mini: [0, 14], density: [20, 70], meet: [74, 98], ctx: [100, 110], sel: [112, 128], bau: [131, 145] };
    const H = () => (sites.length ? 146 : 130);  // Höhe der Zeichenfläche; die Baustellenspur nur bei Bedarf

    // --- Skalen ---------------------------------------------------------------------------------
    // Breite nur beim Zeichnen lesen; sonst erzwingt jede Umrechnung ein neues Layout
    let width = 600;
    const W = () => width;
    const x = (ms) => ((ms - view[0]) / (view[1] - view[0])) * W();
    const inv = (px) => view[0] + (px / W()) * (view[1] - view[0]);
    const xm = (ms) => ((ms - extent[0]) / (extent[1] - extent[0])) * W();

    function clampView(v) {
      let [a, b] = v;
      const span = b - a, pad = 60 * DAY;
      if (a < extent[0] - pad) { a = extent[0] - pad; b = a + span; }
      if (b > extent[1] + pad) { b = extent[1] + pad; a = b - span; }
      return [a, b];
    }
    function setLevel(i, center) {
      level = Math.max(0, Math.min(LEVELS.length - 1, i));
      const c = center ?? (view[0] + view[1]) / 2, half = LEVELS[level].span / 2;
      view = clampView([c - half, c + half]);
      draw();
    }
    function pan(ms) { view = clampView([view[0] + ms, view[1] + ms]); draw(); }

    // --- Bins -------------------------------------------------------------------------------------
    function bins() {
      const bin = LEVELS[level].bin, dim = dimSel.value;
      if (bin === "month" || !papers.length) {
        const d = data.density[dim];
        return data.months.map((m, i) => {
          const start = t(m), end = i + 1 < data.months.length ? t(data.months[i + 1]) : start + 31 * DAY;
          const parts = dim === "vorlage" ? Object.entries(d).map(([k, v]) => [k, v[i]]) : [["Sitzungen", d[i]]];
          return { start, end, parts, total: parts.reduce((s, p) => s + p[1], 0), label: deMonth(start) };
        });
      }
      // nach Kalendertagen zählen, nicht in festen 24-Stunden-Schritten: sonst begannen die Fächer im Winter um
      // 23 Uhr des Vortags und trugen dessen Datum (Code-Prüfung 24.10.2026)
      const n = bin === "week" ? 7 : 1, counts = new Map();
      const add = (ms) => { const k = Math.floor(dayNo(ms) / n); counts.set(k, (counts.get(k) || 0) + 1); };
      for (const p of papers) {
        if (dim === "vorlage") { if (p.date) add(t(p.date)); }
        else for (const s of p.steps) if ((s.typ === "beratung" || s.typ === "entscheidung") && s.date) add(t(s.date));
      }
      const out = [];
      for (let k = Math.floor(dayNo(view[0]) / n) - 1; ; k++) {
        const start = new Date(2019, 8, 30 + k * n).getTime();
        if (start > view[1]) break;
        const c = counts.get(k) || 0;
        out.push({ start, end: new Date(2019, 8, 30 + (k + 1) * n).getTime(), parts: [["Vorlagen", c]], total: c,
          label: bin === "week" ? `Woche ab ${de(start)}` : de(start) });
      }
      return out;
    }

    // --- Zeichnen ---------------------------------------------------------------------------------
    function draw() {
      // eingeklappt nicht zeichnen; der ResizeObserver zeichnet, sobald die Zeitleiste sichtbar wird
      if (!data || !stage.clientWidth) return;
      width = stage.clientWidth;
      const w = W();
      svg.setAttribute("viewBox", `0 0 ${w} ${H()}`);
      root.classList.toggle("tl-has-sites", sites.length > 0);
      svg.innerHTML = "";
      // Verlauf für unscharfe Enden (unverbindliche Termine)
      const defs = el("defs", {}, svg), grad = el("linearGradient", { id: "tl-fuzzy", x1: 0, x2: 1, y1: 0, y2: 0 }, defs);
      for (const [off, op] of [[0, 0.15], [0.12, 1], [0.88, 1], [1, 0.15]]) el("stop", { offset: off, "stop-color": "#c2410c", "stop-opacity": op }, grad);
      const cats = data.categories.concat(["Sitzungen", "Vorlagen"]);

      // kein Datenbestand
      const ds = t(data.dataStart);
      if (view[0] < ds) el("rect", { x: 0, y: LAYOUT.density[0], width: Math.max(0, x(ds)), height: LAYOUT.sel[1] - LAYOUT.density[0], class: "tl-nodata" }, svg);
      if (view[0] < ds && x(ds) > 60) el("text", { x: 6, y: LAYOUT.density[0] + 12, class: "tl-label" }, svg).textContent = "kein Datenbestand";

      // Achse (Jahre/Monate)
      const lv = LEVELS[level];
      const ticks = [];
      const d0 = new Date(view[0]);
      if (lv.bin === "month") for (let y = d0.getFullYear(); t(`${y}-01`) < view[1]; y++) for (let m = 1; m <= 12; m += (lv.name === "Jahr" ? 12 : 3)) ticks.push([t(`${y}-${String(m).padStart(2, "0")}`), m === 1 ? String(y) : DE_MON.format(t(`${y}-${String(m).padStart(2, "0")}`))]);
      else for (let ms = t(iso(view[0]).slice(0, 7)); ms < view[1]; ms = new Date(new Date(ms).setMonth(new Date(ms).getMonth() + 1)).getTime()) ticks.push([ms, deMonth(ms)]);
      for (const [ms, label] of ticks) {
        if (ms < view[0]) continue;
        el("line", { x1: x(ms), x2: x(ms), y1: LAYOUT.density[0], y2: LAYOUT.sel[1], class: "tl-tick" }, svg);
        el("text", { x: x(ms) + 3, y: LAYOUT.density[0] + 9, class: "tl-label" }, svg).textContent = label;
      }

      // Dichte (gestapelt)
      const bs = bins(), max = Math.max(1, ...bs.filter((b) => b.end > view[0] && b.start < view[1]).map((b) => b.total));
      const h = LAYOUT.density[1] - LAYOUT.density[0] - 12;
      for (const b of bs) {
        if (b.end < view[0] || b.start > view[1]) continue;
        let y = LAYOUT.density[1];
        const bw = Math.max(1, x(b.end) - x(b.start) - 1);
        const g = el("g", {}, svg);
        el("title", {}, g).textContent = `${b.label}: ${b.total} ${dimSel.value === "vorlage" ? "Vorlagen" : "Beratungen"}`;
        for (const [k, v] of b.parts) {
          if (!v) continue;
          const bh = (v / max) * h;
          y -= bh;
          el("rect", { x: x(b.start), y, width: bw, height: bh, class: `tl-bar-${cats.indexOf(k) % 8}` }, g);
        }
      }

      const compact = root.classList.contains("tl-compact");
      // Sitzungen je Gremium (Pilot), künftige offen, abgesagte durchgestrichen
      const rows = PILOT_GREMIEN.length, rh = (LAYOUT.meet[1] - LAYOUT.meet[0]) / rows;
      PILOT_GREMIEN.forEach((g, i) => {
        const y = LAYOUT.meet[0] + i * rh + rh / 2;
        if (lv.bin !== "month") el("text", { x: 4, y: y + 3, class: "tl-label tl-row" }, svg).textContent = SHORT[g];
      });
      const today = Date.now();
      for (const m of compact ? [] : data.meetings) {
        const i = PILOT_GREMIEN.indexOf(m.gremium);
        if (i < 0) continue;
        const ms = t(m.date);
        if (ms < view[0] || ms > view[1]) continue;
        const y = LAYOUT.meet[0] + i * rh + rh / 2;
        const c = el("circle", { cx: x(ms), cy: y, r: 2.6, class: `tl-meet${ms > today ? " future" : ""}${m.cancelled ? " cancelled" : ""}` }, svg);
        el("title", {}, c).textContent = `${de(ms)} · ${m.gremium}${m.cancelled ? " · abgesagt" : ms > today ? " · geplant" : ""}`;
      }

      // Kontext: Wahlperioden (belegt, OParl legislativeTerms)
      for (const term of compact ? [] : data.terms) {
        const a = Math.max(t(term.start), view[0]), b = Math.min(t(term.end || "2100-01-01"), view[1]);
        if (b <= a) continue;
        el("rect", { x: x(a), y: LAYOUT.ctx[0], width: x(b) - x(a), height: LAYOUT.ctx[1] - LAYOUT.ctx[0], class: "tl-term" }, svg);
        if (x(b) - x(a) > 70) el("text", { x: x(a) + 4, y: LAYOUT.ctx[1] - 2, class: "tl-label tl-term-label" }, svg).textContent = term.name;
      }

      // Auswahlspur: Stationen der gewählten Vorlage
      if (selected && !compact) {
        for (const s of selected.steps) {
          if (!s.date) continue;
          const ms = t(s.date);
          if (ms < view[0] || ms > view[1]) continue;
          const shape = s.date_status === "abgeleitet" ? "rect" : "circle";
          const y = (LAYOUT.sel[0] + LAYOUT.sel[1]) / 2;
          const m = shape === "rect"
            ? el("rect", { x: x(ms) - 4, y: y - 4, width: 8, height: 8, transform: `rotate(45 ${x(ms)} ${y})`, class: `tl-step derived${preview ? " preview" : ""}` }, svg)
            : el("circle", { cx: x(ms), cy: y, r: 4.5, class: `tl-step${preview ? " preview" : ""}` }, svg);
          el("title", {}, m).textContent = `${de(ms)} · ${s.label}${s.result ? " · „" + s.result + "“" : ""}${s.date_status === "abgeleitet" ? " (Datum abgeleitet)" : ""}`;
          m.addEventListener("click", () => o.onDate(s.date));
        }
      }

      // Baustellen: Zeitraum je Baustelle, auf bis zu drei Bahnen verteilt; gestrichelt = anderer Träger
      if (sites.length && !compact) {
        // Bahnen zuerst verteilen, dann zeichnen: wenige Baustellen erhalten breitere Balken
        const vis = [], lanes = [];
        for (const b of sites) {
          if (!b.von) continue;
          const a = t(b.von), e = b.bis ? t(b.bis) + DAY : a + DAY;
          if (e < view[0] || a > view[1]) continue;
          let lane = lanes.findIndex((end) => end < a);
          if (lane < 0) lane = lanes.length < 3 ? lanes.length : lanes.indexOf(Math.min(...lanes));
          lanes[lane] = Math.max(lanes[lane] || 0, e);
          vis.push([b, a, e, lane]);
        }
        const lh = (LAYOUT.bau[1] - LAYOUT.bau[0]) / Math.max(1, lanes.length);
        if (lv.bin !== "month") el("text", { x: 4, y: LAYOUT.bau[0] + 8, class: "tl-label tl-row" }, svg).textContent = "Baustellen";
        for (const [b, a, e, lane] of vis) {
          const x0 = Math.max(x(a), -2), x1 = Math.min(x(e), w + 2);
          const r = el("rect", { x: x0, y: LAYOUT.bau[0] + lane * lh + 0.5, width: Math.max(2, x1 - x0), height: Math.max(2, lh - 1.5), rx: 2,
            class: `tl-site${b.fremd ? " fremd" : ""}`, fill: "url(#tl-fuzzy)" }, svg);
          el("title", {}, r).textContent = `Baustelle ${b.bezeichnung}: ${de(a)} – ${b.bis ? de(t(b.bis)) : "offen"} (unverbindlich)${b.fremd ? " · anderer Träger" : ""}${b.kandidaten && b.kandidaten.length ? " · mögliche Umsetzung" : ""}`;
          r.addEventListener("click", () => o.onSite(b.id));
        }
      }

      // Brush, heute, Datenstand
      const bx0 = x(range[0]), bx1 = x(range[1]);
      el("rect", { x: bx0, y: LAYOUT.density[0], width: Math.max(0, bx1 - bx0), height: LAYOUT.sel[1] - LAYOUT.density[0], class: "tl-brush" }, svg);
      // liegen „heute“ und „Datenstand“ dicht beieinander, wandert die zweite Beschriftung eine Zeile höher
      const stand = t(data.dataStand), close = Math.abs(x(stand) - x(today)) < 70;
      for (const [ms, cls, label, dy] of [[today, "tl-today", "heute", 0], [stand, "tl-stand", "Datenstand", close ? 10 : 0]]) {
        if (ms < view[0] || ms > view[1]) continue;
        el("line", { x1: x(ms), x2: x(ms), y1: LAYOUT.mini[1] + 2, y2: sites.length ? LAYOUT.bau[1] : LAYOUT.sel[1], class: cls }, svg);
        el("text", { x: x(ms) + 3, y: LAYOUT.sel[1] - 1 - dy, class: `tl-label ${cls}-label` }, svg).textContent = label;
      }

      // Übersicht
      el("rect", { x: 0, y: LAYOUT.mini[0], width: w, height: LAYOUT.mini[1], class: "tl-mini" }, svg);
      const tot = data.months.map((m, i) => Object.values(data.density.vorlage).reduce((s, v) => s + v[i], 0));
      const mmax = Math.max(1, ...tot);
      data.months.forEach((m, i) => {
        const a = xm(t(m)), b = i + 1 < data.months.length ? xm(t(data.months[i + 1])) : a + 3;
        const hh = (tot[i] / mmax) * (LAYOUT.mini[1] - 3);
        el("rect", { x: a, y: LAYOUT.mini[1] - hh, width: Math.max(1, b - a - 0.5), height: hh, class: "tl-mini-bar" }, svg);
      });
      el("rect", { x: xm(view[0]), y: LAYOUT.mini[0], width: Math.max(4, xm(view[1]) - xm(view[0])), height: LAYOUT.mini[1], class: "tl-mini-view" }, svg);

      // Griffe (HTML, damit fokussier- und ansagbar)
      handles.forEach((hd, i) => {
        const ms = range[i];
        // außerhalb des Ausschnitts am Rand angeheftet, damit der Griff fokussierbar bleibt
        hd.style.left = `${Math.min(Math.max(x(ms), 0), w)}px`;
        hd.setAttribute("aria-valuemin", String(extent[0]));
        hd.setAttribute("aria-valuemax", String(extent[1]));
        hd.setAttribute("aria-valuenow", String(ms));
        hd.setAttribute("aria-valuetext", de(ms));
        hd.classList.toggle("tl-off", ms < view[0] || ms > view[1]);
      });
      root.querySelector(".tl-level").textContent = LEVELS[level].name;
    }

    // --- Zeitraum ---------------------------------------------------------------------------------
    function countIn(a, b) {
      const dim = dimSel.value;
      if (papers.length) return papers.filter((p) => dim === "vorlage"
        ? p.date && t(p.date) >= a && t(p.date) <= b
        : p.steps.some((s) => s.date && (s.typ === "beratung" || s.typ === "entscheidung") && t(s.date) >= a && t(s.date) <= b)).length;
      return 0;
    }
    function setRange(a, b, silent) {
      if (a > b) [a, b] = [b, a];
      range = [Math.max(extent[0], a), Math.min(extent[1], b)];
      draw();
      const text = `${de(range[0])} – ${de(range[1])} · ${countIn(range[0], range[1])} Vorlagen`;
      root.querySelector(".tl-range").textContent = `Zeitraum: ${text}`;
      clearTimeout(debounce);
      // Ansage erst, wenn die Auswahl zur Ruhe kommt, nicht bei jeder Zeigerbewegung
      if (!silent) debounce = setTimeout(() => {
        root.querySelector(".tl-live").textContent = `Zeitraum ${text}`;
        o.onRange(iso(range[0]), iso(range[1]));
      }, 180);
    }
    // „gesamter Bestand“ endet beim Datenstand; nur die Sitzungsachse reicht bis zu künftigen Terminen
    const fullEnd = () => (dimSel.value === "sitzung" ? extent[1] : Math.min(extent[1], t(data.dataStand)));
    function preset(name) {
      const now = Math.min(Date.now(), extent[1]);
      if (name === "12m") setRange(now - 365 * DAY, now);
      if (name === "all") setRange(extent[0], fullEnd());
      if (name === "term") {
        const cur = data.terms.find((tm) => t(tm.start) <= now && (!tm.end || t(tm.end) >= now)) || data.terms[data.terms.length - 1];
        if (cur) setRange(t(cur.start), Math.min(t(cur.end || "2100-01-01"), extent[1]));
      }
    }

    function table() {
      const dim = dimSel.value, d = data.density;
      const rowsHtml = data.months.map((m, i) => {
        const v = Object.values(d.vorlage).reduce((s, arr) => s + arr[i], 0);
        const meet = data.meetings.filter((x) => x.date.startsWith(m)).length;
        return `<tr><th scope="row">${deMonth(t(m))}</th><td>${v}</td><td>${d.sitzung[i]}</td><td>${meet}</td></tr>`;
      }).reverse().join("");
      root.querySelector(".tl-table-body").innerHTML = `<table><thead><tr><th scope="col">Monat</th>
        <th scope="col">Vorlagen (Datum der Vorlage)</th><th scope="col">Beratungen (Sitzungsdatum, abgeleitet)</th>
        <th scope="col">Sitzungen (alle Gremien)</th></tr></thead><tbody>${rowsHtml}</tbody></table>`;
      void dim;
    }

    // --- Interaktion --------------------------------------------------------------------------------
    root.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const act = b.dataset.act, step = LEVELS[level].step;
      if (act === "prev") pan(-step);
      if (act === "next") pan(step);
      if (act === "in") setLevel(level + 1);
      if (act === "out") setLevel(level - 1);
      if (act === "start") setLevel(level, extent[0] + LEVELS[level].span / 2);
      if (act === "today") setLevel(level, Date.now());
      if (act === "stand") setLevel(level, t(data.dataStand));
      if (b.dataset.preset) preset(b.dataset.preset);
    });
    dimSel.addEventListener("change", () => { draw(); setRange(range[0], range[1]); });

    let drag = null;
    stage.addEventListener("pointerdown", (e) => {
      if (e.target.classList.contains("tl-handle")) {
        drag = { kind: "handle", i: +e.target.dataset.h };
      } else {
        const rect = stage.getBoundingClientRect(), py = e.clientY - rect.top, px = e.clientX - rect.left;
        const scale = H() / rect.height;
        if (py * scale <= LAYOUT.mini[1]) {
          const c = extent[0] + (px / W()) * (extent[1] - extent[0]);
          setLevel(level, c);
          drag = { kind: "mini" };
        } else if (e.altKey || (py * scale >= LAYOUT.density[0] && py * scale <= LAYOUT.density[1] && e.shiftKey)) {
          drag = { kind: "brush", start: inv(px) };
        } else {
          drag = { kind: "pan", x: e.clientX, view: view.slice() };
        }
      }
      stage.setPointerCapture(e.pointerId);
    });
    let frame = 0;
    stage.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const rect = stage.getBoundingClientRect(), px = e.clientX - rect.left;
      if (drag.kind === "handle") {
        const ms = inv(px), r = range.slice();
        r[drag.i] = ms;
        setRange(r[0], r[1]);
      } else if (drag.kind === "pan") {
        const dx = e.clientX - drag.x, ms = (dx / W()) * (drag.view[1] - drag.view[0]);
        view = clampView([drag.view[0] - ms, drag.view[1] - ms]);
        if (!frame) frame = requestAnimationFrame(() => { frame = 0; draw(); });
      } else if (drag.kind === "mini") {
        setLevel(level, extent[0] + (px / W()) * (extent[1] - extent[0]));
      } else if (drag.kind === "brush") {
        setRange(drag.start, inv(px));
      }
    });
    stage.addEventListener("pointerup", () => { drag = null; });
    stage.addEventListener("dblclick", (e) => {
      const rect = stage.getBoundingClientRect();
      setLevel(level + 1, inv(e.clientX - rect.left));
    });
    stage.addEventListener("wheel", (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const rect = stage.getBoundingClientRect();
        setLevel(level + (e.deltaY < 0 ? 1 : -1), inv(e.clientX - rect.left));
      } else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        pan(((e.shiftKey ? e.deltaY : e.deltaX) / W()) * (view[1] - view[0]));
      }
    }, { passive: false });
    stage.addEventListener("keydown", (e) => {
      if (e.target !== stage) return;
      const step = LEVELS[level].step;
      const keys = { ArrowLeft: () => pan(-step), ArrowRight: () => pan(step), "+": () => setLevel(level + 1),
        "-": () => setLevel(level - 1), Home: () => setLevel(level, extent[0] + LEVELS[level].span / 2),
        End: () => setLevel(level, extent[1] - LEVELS[level].span / 2) };
      if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
    });
    handles.forEach((hd) => hd.addEventListener("keydown", (e) => {
      const i = +hd.dataset.h, r = range.slice(), step = LEVELS[level].bin === "month" ? 30 : 1;
      const map = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step, PageDown: -365, PageUp: 365 };
      if (map[e.key] !== undefined) r[i] = addDays(r[i], map[e.key]);   // Kalendertage, auch über die Zeitumstellung
      else if (e.key === "Home") r[i] = extent[0];
      else if (e.key === "End") r[i] = extent[1];
      else return;
      e.preventDefault();
      if (r[i] < view[0] || r[i] > view[1]) { view = clampView([r[i] - (view[1] - view[0]) / 2, r[i] + (view[1] - view[0]) / 2]); }
      setRange(r[0], r[1]);
    }));
    new ResizeObserver(() => draw()).observe(stage);

    return {
      setData(d) {
        data = d;
        if (d.dimension) dimSel.value = d.dimension;
        extent = [t(d.dataStart), Math.max(t(d.months[d.months.length - 1]) + 31 * DAY, Date.now())];
        if (range[0] === 0) { range = [extent[0], fullEnd()]; setLevel(level, Date.now() - LEVELS[level].span / 3); }
        table();
        setRange(range[0], range[1], true);
      },
      setPapers(p) { papers = p || []; if (data) setRange(range[0], range[1], true); },
      setSites(list) { sites = list || []; draw(); },
      // preview: nur angedeutet (Zeiger über einem Listeneintrag), nicht ausgewählt
      select(p, isPreview) { selected = p; preview = Boolean(p && isPreview); draw(); },
      reset() { if (data) setRange(extent[0], fullEnd(), true); },
      setRange(a, b) { setRange(t(a), t(b), true); },
      center(d) { setLevel(level, t(d)); },
      getState() { return { von: iso(range[0]), bis: iso(range[1]), zoom: LEVELS[level].name, achse: dimSel.value }; },
      setState(s) {
        // nur gültige Werte aus der Adresse übernehmen (unbekannte Achse oder Datum hielt sonst den Start an)
        if ([...dimSel.options].some((o) => o.value === s.achse)) dimSel.value = s.achse;
        const z = LEVELS.findIndex((l) => l.name === s.zoom);
        if (z >= 0) level = z;
        if (s.von && s.bis && Number.isFinite(t(s.von)) && Number.isFinite(t(s.bis))) {
          range = [t(s.von), t(s.bis)].sort((a, b) => a - b);
          setLevel(level, (range[0] + range[1]) / 2);
          setRange(range[0], range[1], true);
        }
      },
      dimension() { return dimSel.value; },
      reduceMotion,
    };
  }

  global.Timeline = { create };
})(window);
