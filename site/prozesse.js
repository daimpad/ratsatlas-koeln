// Reiter „Prozesse“: Verfahrensarten (Soll-Modell, soll.json), Gremien und Ämter (prozessarten.json) als Schaubild oder Liste.
// Verfahren und Zuständigkeitsordnung stammen aus „Bonn entscheidet“ (anster2025, MIT) mit Ergänzungen des Ratsatlas;
// Zahlen je Verfahren beruhen auf der abgeleiteten Zuordnung (pipeline/soll.py), Gremien und Sitzungen auf der
// OParl-API der Stadt Bonn (CC0); Ämter und Federführung aus `underDirectionOf`, gruppiert nach der Amtsnummer
// (abgeleitet, die Quelle nennt keine Dezernate). Wird von app.js erst beim Öffnen des Reiters geladen.
import { deDate } from "./mitwirken.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Adressen aus den Daten nur als http(s)-Link (javascript: o. Ä. würde sonst als Link eingesetzt)
const href = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? esc(u) : "#");
const num = (n) => Number(n || 0).toLocaleString("de-DE");
const LANES = ["ew", "rm", "bvm", "vw", "bv", "aus", "rat"];
const ART_PL = { rat: "Rat", hauptausschuss: "Hauptausschuss", ausschuss: "Fachausschüsse", bezirksvertretung: "Bezirksvertretungen",
  beirat: "Beiräte und Kommissionen", unterausschuss: "Unterausschüsse", wahlausschuss: "Wahlausschüsse" };
const ART = { rat: "Rat", hauptausschuss: "Hauptausschuss", ausschuss: "Fachausschuss", bezirksvertretung: "Bezirksvertretung",
  beirat: "Beirat oder Kommission", unterausschuss: "Unterausschuss", wahlausschuss: "Wahlausschuss" };
const RECHT = [["Entscheidung", "entscheidet selbst"], ["Empfehlung", "empfiehlt dem Rat"], ["Anhörung", "wird angehört"], ["Mitteilung", "erhält Mitteilungen"]];
// Wege, sich einzubringen (Regeln des Soll-Modells); kurze Bezeichnungen des Ratsatlas, Frist und Beleg aus der Quelle
const WEGE = { "sitzung-besuchen": "Sitzung besuchen", livestream: "Ratssitzung im Livestream verfolgen",
  "buergerantrag-erlaeutern": "Eigenen Bürgerantrag im Ausschuss erläutern", einwohnerfrage: "Frage in der Einwohnerfragestunde stellen",
  "ansprechen-bv": "Bezirksverordnete ansprechen", "ansprechen-rat": "Fraktionen oder Gruppen ansprechen",
  "eigener-buergerantrag": "Eigenen Bürgerantrag einbringen", offenlage: "Stellungnahme in der Offenlage abgeben" };

const TABS = ["verfahren", "gremien", "aemter"];

let ctx, soll, data, root, state = { tab: "verfahren", view: "schaubild", verfahren: null, gremium: null, amt: null, frueher: false, q: "" };

const links = (ls) => (ls || []).map((l) => `<a href="${href(l.url)}" target="_blank" rel="noopener">${esc(l.label)}<span class="visually-hidden"> (neuer Tab)</span></a>`).join(" · ");
const beleg = (x) => (x.links && x.links.length ? links(x.links) : x.beleg ? esc(x.beleg) : "");

// --- Verfahren ---------------------------------------------------------------------------------------
function lanesOf(v) {
  const used = new Set(v.schritte.map((s) => s.bahn).filter(Boolean));
  return LANES.filter((b) => used.has(b));
}
function wrap(text, max = 19) {
  const out = [];
  let line = "";
  for (const w of String(text).split(/\s+/)) {
    if (line && (line + " " + w).length > max) { out.push(line); line = w; } else line = line ? `${line} ${w}` : w;
  }
  if (line) out.push(line);
  return out.length > 3 ? [...out.slice(0, 2), out.slice(2).join(" ").slice(0, max - 1) + "…"] : out;
}
function swimlane(vid, v) {
  const lanes = lanesOf(v), LW = 150, CW = 150, LH = 58, NW = 132, NH = 44, top = 8;
  const W = LW + v.schritte.length * CW + 10, H = top + lanes.length * LH + 8;
  const pos = v.schritte.map((s, i) => ({ x: LW + i * CW + (CW - NW) / 2, y: top + Math.max(0, lanes.indexOf(s.bahn)) * LH + (LH - NH) / 2 }));
  const lanesSvg = lanes.map((b, i) => `<rect class="pz-lane${i % 2 ? " odd" : ""}" x="0" y="${top + i * LH}" width="${W}" height="${LH}"/>
    <text class="pz-lane-label" x="10" y="${top + i * LH + LH / 2}">${wrap(soll.bahnen[b] || b, 20).map((t, k, a) => `<tspan x="10" dy="${k ? 13 : -(a.length - 1) * 6.5 + 4}">${esc(t)}</tspan>`).join("")}</text>`).join("");
  const arrows = pos.slice(1).map((p, i) => {
    const a = pos[i], x1 = a.x + NW, y1 = a.y + NH / 2, x2 = p.x, y2 = p.y + NH / 2, mx = (x1 + x2) / 2;
    return `<path class="pz-arrow" d="M${x1},${y1} H${mx} V${y2} H${x2 - 2}" marker-end="url(#pz-head-${vid})"/>`;
  }).join("");
  const nodes = v.schritte.map((s, i) => {
    const p = pos[i], lines = wrap(s.label);
    return `<g class="pz-node${s.eigen ? " eigen" : ""}"><rect x="${p.x}" y="${p.y}" width="${NW}" height="${NH}" rx="10"/>
      <circle cx="${p.x}" cy="${p.y}" r="9"/><text class="pz-no" x="${p.x}" y="${p.y + 3.5}">${i + 1}</text>
      <text class="pz-label" x="${p.x + NW / 2}" y="${p.y + NH / 2}">${lines.map((t, k) => `<tspan x="${p.x + NW / 2}" dy="${k ? 12.5 : -(lines.length - 1) * 6.25 + 4}">${esc(t)}</tspan>`).join("")}</text></g>`;
  }).join("");
  const summary = `${v.titel}: ${v.schritte.map((s, i) => `${i + 1}. ${s.label} (${soll.bahnen[s.bahn] || "ohne Ebene"})`).join("; ")}`;
  return `<div class="pz-scroll" tabindex="0" role="region" aria-label="Schaubild ${esc(v.titel)}, seitlich verschiebbar"><svg class="pz-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(summary)}">
    <defs><marker id="pz-head-${vid}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="pz-head"/></marker></defs>
    ${lanesSvg}${arrows}${nodes}</svg></div>
    <p class="hint">Jede Zeile ist eine Ebene, die Kästen sind die Schritte in ihrer Reihenfolge.${v.schritte.some((s) => s.eigen) ? " Gestrichelt: vom Ratsatlas ergänzte Schritte." : ""} Dieselben Schritte stehen unten als Liste.</p>`;
}
function wegeFor(vid, v) {
  const lanes = new Set(lanesOf(v));
  return (soll.mitwirken || []).filter((r) => {
    const w = r.wenn || {};
    if (!WEGE[r.id] || !(w.status || []).includes("offen")) return false;
    if (w.verfahren && !w.verfahren.includes(vid)) return false;
    if (w.nicht_verfahren && w.nicht_verfahren.includes(vid)) return false;
    if (r.id === "livestream" && !lanes.has("rat")) return false;
    if ((r.id === "einwohnerfrage" || r.id === "ansprechen-bv") && !lanes.has("bv")) return false;
    if (r.id === "ansprechen-rat" && !lanes.has("aus") && !lanes.has("rat")) return false;
    return true;
  });
}
function verfahrenBody(vid, v) {
  const z = (data.verfahren || {})[vid];
  const steps = `<ol class="pz-steps">${v.schritte.map((s) => `<li><strong>${esc(s.label)}</strong> <span class="pz-bahn">${esc(soll.bahnen[s.bahn] || "")}</span>
      ${s.was && s.was !== s.label ? `<br>${esc(s.was)}` : ""}${s.eigen ? ' <span class="derived">ergänzt vom Ratsatlas</span>' : ""}
      ${beleg(s) ? `<br><span class="hint">Rechtsgrundlage: ${beleg(s)}</span>` : ""}</li>`).join("")}</ol>`;
  const zahl = z ? `<p><strong>In Bonn:</strong> ${num(z.vorgaenge)} Vorgänge seit Oktober 2019 <span class="derived">abgeleitet</span>
      <span class="hint">(davon ${num(z.sicher)} mit hoher Sicherheit zugeordnet)</span></p>
      ${z.beispiele.length ? `<p class="pz-examples"><span class="hint">Jüngste Beispiele:</span> ${z.beispiele.map((b) => `<button type="button" class="btn btn-soft pz-open" data-ref="${esc(b.drucksache)}">${esc(b.drucksache)} · ${esc(b.titel.length > 70 ? b.titel.slice(0, 68) + "…" : b.titel)}</button>`).join(" ")}</p>` : ""}`
    : `<p class="hint">In den Daten ist kein Vorgang diesem Verfahren zugeordnet.</p>`;
  const wege = wegeFor(vid, v);
  return `<p>${esc(v.kurz || "")}</p>${zahl}
    <h4>Schritte</h4>${steps}
    ${wege.length ? `<h4>Wege, sich einzubringen</h4><ul class="pz-wege">${wege.map((r) => `<li><strong>${esc(WEGE[r.id])}</strong> <span class="hint">Frist: ${esc(r.frist)}</span>${beleg(r) ? `<br><span class="hint">Rechtsgrundlage: ${beleg(r)}</span>` : ""}</li>`).join("")}</ul>
      <p class="hint">Welche Wege bei einem bestimmten Vorgang offen sind, zeigt dort der Abschnitt „Selbst mitwirken“.</p>` : ""}`;
}
function fristen() {
  return `<details class="pz-more"><summary>Fristen vor einer Sitzung</summary><ul class="pz-wege">${(soll.fristen || []).map((f) => `<li><strong>${esc(f.label)}</strong>: ${esc(f.was)}${beleg(f) ? ` <span class="hint">(${beleg(f)})</span>` : ""}</li>`).join("")}</ul></details>`;
}
function renderVerfahren() {
  const ids = Object.keys(soll.verfahren);
  const count = (id) => (data.verfahren[id] || {}).vorgaenge || 0;
  if (state.view === "liste") {
    return `<p class="hint">${ids.length} Verfahrensarten nach dem Regelwerk der Stadt Bonn (vereinfachtes Modell, keine Rechtsauskunft).</p>
      ${ids.map((id) => `<details class="pz-item" data-verfahren="${esc(id)}"${state.verfahren === id ? " open" : ""}><summary><span class="pz-title">${esc(soll.verfahren[id].titel)}</span>
        <span class="pz-meta">${num(count(id))} Vorgänge</span></summary>${verfahrenBody(id, soll.verfahren[id])}</details>`).join("")}${fristen()}`;
  }
  const vid = Object.hasOwn(soll.verfahren, state.verfahren || "") ? state.verfahren : "buergerantrag";
  const v = soll.verfahren[vid];
  return `<label class="pz-pick">Verfahren <select id="pz-verfahren">${ids.map((id) => `<option value="${esc(id)}"${id === vid ? " selected" : ""}>${esc(soll.verfahren[id].titel)} (${num(count(id))})</option>`).join("")}</select></label>
    <h3 class="pz-h">${esc(v.titel)}</h3>${swimlane(vid, v)}${verfahrenBody(vid, v)}${fristen()}`;
}

// --- Gremien -----------------------------------------------------------------------------------------
const meta = (g) => [g.naechste ? `nächste Sitzung ${deDate(g.naechste.datum)}` : g.letzte ? `zuletzt ${deDate(g.letzte)}` : "", g.aufgeloest ? `aufgelöst ${deDate(g.aufgeloest)}` : ""].filter(Boolean).join(" · ");
function zustaendig(g) {
  if (g.zusto && soll.zusto[g.zusto]) {
    const z = soll.zusto[g.zusto];
    const groups = RECHT.map(([art, label]) => [label, z.rechte.filter((r) => r.art === art)]).filter(([, rs]) => rs.length);
    return `<h4>Zuständigkeit laut Zuständigkeitsordnung (Abschnitt ${esc(z.nr)})</h4>
      ${g.zusto_hinweis ? `<p class="hint">${esc(g.zusto_hinweis)}</p>` : ""}
      ${groups.map(([label, rs]) => `<details class="pz-more"><summary>${esc(g.name)} ${esc(label)} (${rs.length})</summary><ul class="pz-recht">${rs.map((r) => `<li><span class="pz-nr">${esc(r.nr)}</span> ${esc(r.inhalt)}${r.an_bezirksvertretung ? ' <span class="hint">(Bezirksvertretung wird beteiligt)</span>' : ""}</li>`).join("")}</ul></details>`).join("")}
      <p class="hint">Quelle: <a href="${href(soll.meta.zusto_url)}" target="_blank" rel="noopener">Zuständigkeitsordnung der Stadt Bonn<span class="visually-hidden"> (neuer Tab)</span></a>, Stand ${esc(soll.meta.zusto_stand || "")}.</p>`;
  }
  const rule = (re) => (soll.zustaendigkeit || []).filter((z) => re.test(`${z.frage} ${z.antwort}`));
  const rules = g.art === "bezirksvertretung" ? rule(/Bezirk|BV/) : g.art === "rat" || g.art === "hauptausschuss" ? rule(/Rat|Hauptausschuss/) : [];
  if (rules.length) return `<h4>Zuständigkeit nach Regelwerk</h4><dl class="pz-zust">${rules.map((z) => `<dt>${esc(z.frage)}</dt><dd>${esc(z.antwort)}${beleg(z) ? ` <span class="hint">(${beleg(z)})</span>` : ""}</dd>`).join("")}</dl>`;
  return `<p class="hint">Für dieses Gremium enthält das Regelwerk des Ratsatlas keinen eigenen Abschnitt.</p>`;
}
// Besetzung (prozessarten.json, pipeline/besetzung.py): laufende Mitgliedschaften ohne Kontaktdaten; Fraktion abgeleitet
function besetzung(g) {
  const b = g.besetzung;
  if (!b) return "";
  const person = (e) => (e.web ? `<a href="${href(e.web)}" target="_blank" rel="noopener">${esc(e.name)}<span class="visually-hidden"> (Personenseite im Ratsinformationssystem, neuer Tab)</span></a>` : esc(e.name));
  const fr = (e) => (e.fraktion ? esc(e.fraktion) : `<span class="hint">${e.fraktion_hinweis ? esc(e.fraktion_hinweis) : "ohne Angabe"}</span>`);
  const teile = (x) => x.aus ? ` <small class="pz-teile">(${x.aus.map((t) => `${esc(t.fraktion)} ${num(t.n)}`).join(", ")})</small>` : "";
  const sitze = b.sitze.map((x) => `<li><span>${esc(x.fraktion)}${teile(x)}</span><span class="pz-n">${num(x.n)}</span></li>`).join("");
  const ohne = b.ohne_fraktion ? `<li><span>ohne Angabe einer Fraktion${b.sachkundig ? ` (darunter ${num(b.sachkundig)} sachkundige Bürger:innen und Einwohner:innen)` : ""}</span><span class="pz-n">${num(b.ohne_fraktion)}</span></li>` : "";
  const zeilen = b.ordentlich.map((e) => `<tr><th scope="row">${person(e)}</th><td>${esc(e.rolle)}</td><td>${fr(e)}</td></tr>`).join("");
  const bv = g.art === "bezirksvertretung";
  const beratend = b.beratend.length ? `<details class="pz-more"><summary>Beratende Mitglieder (${num(b.beratend.length)})</summary>
      ${bv ? '<p class="hint">Ratsmitglieder aus dem Stadtbezirk nehmen mit beratender Stimme teil, ohne Stimmrecht (§ 36 Abs. 6 GO NRW).</p>' : ""}
      <ul class="pz-recht">${b.beratend.map((e) => `<li>${person(e)} · ${esc(e.rolle)}${e.fraktion ? ` · ${esc(e.fraktion)}` : ""}</li>`).join("")}</ul></details>` : "";
  const rest = [b.stellvertretend ? `${num(b.stellvertretend)} Stellvertretungen` : "", b.ohne_namen ? `${num(b.ohne_namen)} Einträge ohne Namen (${esc((b.ohne_namen_grund || []).join(", "))})` : ""].filter(Boolean).join(" · ");
  return `<h4>Besetzung <span class="derived">Fraktion abgeleitet</span></h4>
    <p>${num(b.sitze_gesamt)} Mitglieder${b.sitze.length ? ", nach Fraktion:" : ""}</p>
    ${b.sitze.length || ohne ? `<ul class="pz-sitze">${sitze}${ohne}</ul>` : ""}
    ${zeilen ? `<details class="pz-more"><summary>Mitglieder mit Namen (${num(b.ordentlich.length)})</summary>
      <table class="kontext-table pz-mitglieder"><thead><tr><th scope="col">Name</th><th scope="col">Rolle laut Quelle</th><th scope="col">Fraktion</th></tr></thead>
      <tbody>${zeilen}</tbody></table></details>` : ""}
    ${beratend}
    ${rest ? `<p class="hint">Außerdem: ${rest}.</p>` : ""}
    ${b.ordentlich.some((e) => e.rolle === "Mitglied (Stv.)") ? '<p class="hint">„Mitglied (Stv.)“ bezeichnet laut Quelle Stadtverordnete als Mitglied des Gremiums, keine Stellvertretung (Deutung abgeleitet).</p>' : ""}
    <p class="hint">${esc(data.meta.besetzung_hinweis || "")}</p>`;
}
function gremiumBody(g) {
  return `<p><span class="pz-art">${esc(ART[g.art] || g.art)}</span>${g.aktuell ? "" : ' <span class="derived">nicht in der laufenden Wahlperiode</span>'}</p>
    <ul class="pz-facts">
      <li>${num(g.beratungen)} Beratungen zu ${num(g.vorlagen)} Vorlagen seit Oktober 2019</li>
      ${g.letzte ? `<li>Letzte Sitzung: ${deDate(g.letzte)}</li>` : ""}
      ${g.naechste ? `<li>Nächste Sitzung: ${g.naechste.web ? `<a href="${href(g.naechste.web)}" target="_blank" rel="noopener">${deDate(g.naechste.datum)}<span class="visually-hidden"> (Tagesordnung, neuer Tab)</span></a>` : deDate(g.naechste.datum)}</li>` : ""}
      ${g.aufgeloest ? `<li>Aufgelöst: ${deDate(g.aufgeloest)}</li>` : ""}
    </ul>
    ${besetzung(g)}
    ${zustaendig(g)}
    <p class="pz-actions">${g.vorlagen ? `<button type="button" class="btn btn-soft pz-filter" data-name="${esc(g.name)}">Vorlagen dieses Gremiums in der Liste</button>` : ""}
      ${g.web ? `<a class="btn btn-ghost" href="${href(g.web)}" target="_blank" rel="noopener">Im Ratsinformationssystem<span class="visually-hidden"> (neuer Tab)</span></a>` : ""}</p>
    <p class="pz-msg hint" aria-live="polite"></p>`;
}
const nodeBtn = (g) => `<button type="button" class="org-node org-${esc(g.art)}" data-gremium="${esc(g.id)}" aria-pressed="${state.gremium === g.id}">
  <span class="org-name">${esc(g.name)}</span><span class="org-meta">${esc(meta(g))}</span></button>`;
function renderGremien() {
  const all = data.gremien || [];
  const cur = all.filter((g) => g.aktuell);
  const by = (a) => cur.filter((g) => g.art === a);
  const sel = all.find((g) => g.id === state.gremium);
  const intro = `<details class="pz-more"><summary>Wer entscheidet was? Kurz erklärt</summary><dl class="pz-zust">${(soll.zustaendigkeit || []).map((z) => `<dt>${esc(z.frage)}</dt><dd>${esc(z.antwort)}${beleg(z) ? ` <span class="hint">(${beleg(z)})</span>` : ""}</dd>`).join("")}</dl></details>`;
  if (state.view === "liste") {
    const q = state.q.trim().toLowerCase();
    const shown = (state.frueher ? all : cur).filter((g) => !q || g.name.toLowerCase().includes(q));
    const groups = Object.keys(ART).map((a) => [a, shown.filter((g) => g.art === a)]).filter(([, gs]) => gs.length);
    return `${intro}<div class="pz-filterbar"><label>Gremium suchen <input type="search" id="pz-q" value="${esc(state.q)}" autocomplete="off"></label>
      <label class="check"><input type="checkbox" id="pz-frueher"${state.frueher ? " checked" : ""}> frühere Gremien zeigen</label></div>
      <p class="hint" aria-live="polite">${shown.length} Gremien</p>
      ${groups.map(([a, gs]) => `<h3 class="pz-h">${esc(ART_PL[a])}</h3>${gs.map((g) => `<details class="pz-item" data-gremium="${esc(g.id)}"${state.gremium === g.id ? " open" : ""}><summary><span class="pz-title">${esc(g.name)}</span><span class="pz-meta">${esc(meta(g))}</span></summary>${gremiumBody(g)}</details>`).join("")}`).join("")}`;
  }
  return `${intro}<div class="org" role="group" aria-label="Gremien der Stadt Bonn in der laufenden Wahlperiode">
      <div class="org-top">${by("rat").map(nodeBtn).join("")}</div>
      <div class="org-cols">
        <section class="org-col org-aus" aria-label="Ausschüsse des Rates"><h3 class="org-h">Ausschüsse des Rates</h3>
          <div class="org-haupt">${by("hauptausschuss").map(nodeBtn).join("")}</div>
          <div class="org-grid">${by("ausschuss").map(nodeBtn).join("")}</div></section>
        <section class="org-col org-bv" aria-label="Bezirksvertretungen"><h3 class="org-h">Bezirksvertretungen</h3>
          <div class="org-grid org-grid-1">${by("bezirksvertretung").map(nodeBtn).join("")}</div></section>
      </div>
      <section class="org-beirat" aria-label="Beiräte und Kommissionen"><h3 class="org-h">Beiräte und Kommissionen</h3>
        <div class="org-grid">${by("beirat").map(nodeBtn).join("")}</div></section>
      ${by("unterausschuss").length + by("wahlausschuss").length ? `<section class="org-beirat" aria-label="Weitere Gremien"><h3 class="org-h">Weitere Gremien</h3>
        <div class="org-grid">${[...by("unterausschuss"), ...by("wahlausschuss")].map(nodeBtn).join("")}</div></section>` : ""}
    </div>
    <p class="hint">Gezeigt sind die Gremien der laufenden Wahlperiode (seit ${deDate(data.meta.wahlperiode_seit)}); frühere stehen in der Liste. Der Rat entscheidet grundsätzlich; Ausschüsse und Bezirksvertretungen, soweit ihnen Aufgaben übertragen sind.</p>
    <div id="pz-detail" class="pz-detail" aria-live="polite">${sel ? `<h3 class="pz-h" tabindex="-1">${esc(sel.name)}</h3>${gremiumBody(sel)}` : `<p class="hint">Wählen Sie ein Gremium, um seine Zuständigkeit und Sitzungen zu sehen.</p>`}</div>`;
}

// --- Ämter ------------------------------------------------------------------------------------------
const gruppe = (id) => ((data.amt_gruppen || []).find((g) => g.id === id) || {}).label || id;
const amtMeta = (a) => [`${num(a.vorlagen)} Vorlagen`, a.aufgeloest ? `aufgelöst ${deDate(a.aufgeloest)}` : ""].filter(Boolean).join(" · ");
const amtId = (name) => ((data.aemter || []).find((a) => a.name === name) || {}).id;
const short = (t) => (t.length > 70 ? t.slice(0, 68) + "…" : t);
function amtBody(a) {
  const ab = a.abteilungen || [];
  const gremien = (a.gremien || []).filter((g) => (data.gremien || []).some((x) => x.id === g.id));
  const fach = (a.fachlich_aemter || []).filter((f) => amtId(f.name));
  return `<p><span class="pz-art">${esc(gruppe(a.gruppe))}</span>${a.aktuell ? "" : ' <span class="derived">nicht mehr aktiv</span>'}</p>
    ${a.hinweis ? `<p class="pz-note">${esc(a.hinweis)}</p>` : ""}
    <ul class="pz-facts">
      <li>Federführend bei ${num(a.vorlagen)} Vorlagen seit Oktober 2019${a.letzte ? `, zuletzt am ${deDate(a.letzte)}` : ""}</li>
      ${a.politik ? `<li>davon ${num(a.politik)} Anträge und Anfragen aus der Politik</li>` : ""}
      ${a.einwohner ? `<li>davon ${num(a.einwohner)} Bürgeranträge, Anregungen und Einwohnerfragen</li>` : ""}
      ${a.fachlich ? `<li>Fachlich zuständig bei weiteren ${num(a.fachlich)} Vorlagen, für die formal eine koordinierende Stelle wie das Ratsbüro oder das Bürgerbüro federführend ist <span class="derived">abgeleitet aus Stellungnahmen</span></li>` : ""}
      ${a.aufgeloest ? `<li>Aufgelöst: ${deDate(a.aufgeloest)}</li>` : ""}
    </ul>
    ${ab.length ? `<details class="pz-more"><summary>Abteilungen und Stellen (${ab.length})</summary><ul class="pz-recht">${ab.map((x) => `<li>${esc(x.name)} <span class="hint">${num(x.vorlagen)} Vorlagen${x.aufgeloest ? ` · aufgelöst ${deDate(x.aufgeloest)}` : ""}</span></li>`).join("")}</ul></details>` : ""}
    ${fach.length ? `<h4>Fachlich zuständig laut Stellungnahmen <span class="derived">abgeleitet</span></h4><p class="hint">Ämter, die zu den Vorlagen dieser Stelle in einer Stellungnahme der Verwaltung antworten (Zahl der Vorlagen)</p><p class="pz-examples">${fach.map((f) => `<button type="button" class="btn btn-soft pz-amt" data-amt="${esc(amtId(f.name))}">${esc(f.name)} · ${num(f.vorlagen)}</button>`).join(" ")}</p>` : ""}
    ${gremien.length ? `<h4>Diese Gremien beraten die Vorlagen am häufigsten</h4><p class="hint">Zahl der Vorlagen, die das Gremium davon beraten hat</p><p class="pz-examples">${gremien.map((g) => `<button type="button" class="btn btn-soft pz-gremium" data-gremium="${esc(g.id)}">${esc(g.name)} · ${num(g.vorlagen)}</button>`).join(" ")}</p>` : ""}
    ${a.beispiele.length ? `<p class="pz-examples"><span class="hint">Jüngste Vorlagen:</span> ${a.beispiele.map((b) => `<button type="button" class="btn btn-soft pz-open" data-ref="${esc(b.drucksache)}">${esc(b.drucksache)} · ${esc(short(b.titel || ""))}</button>`).join(" ")}</p>` : ""}
    <p class="pz-actions">${a.vorlagen ? `<button type="button" class="btn btn-soft pz-filter" data-kind="amt" data-name="${esc(a.name)}">Vorlagen dieses Amts in der Liste</button>` : ""}</p>
    <p class="pz-msg hint" aria-live="polite"></p>`;
}
const amtBtn = (a) => `<button type="button" class="org-node org-amt" data-amt="${esc(a.id)}" aria-pressed="${state.amt === a.id}">
  <span class="org-name">${esc(a.name)}</span><span class="org-meta">${esc(amtMeta(a))}</span></button>`;
function renderAemter() {
  const all = data.aemter || [];
  const cur = all.filter((a) => a.aktuell);
  const sel = all.find((a) => a.id === state.amt);
  const groups = (list) => (data.amt_gruppen || []).map((g) => [g, list.filter((a) => a.gruppe === g.id)]).filter(([, as]) => as.length);
  const intro = `<p class="hint">Ämter und Federführung stammen aus der OParl-API der Stadt Bonn. Die Gruppen folgen der Amtsnummer
    <span class="derived">abgeleitet</span>; eine Zuordnung zu den Dezernaten enthält die Quelle nicht.</p>`;
  if (state.view === "liste") {
    const q = state.q.trim().toLowerCase();
    const shown = (state.frueher ? all : cur).filter((a) => !q || a.name.toLowerCase().includes(q) || a.abteilungen.some((x) => x.name.toLowerCase().includes(q)));
    return `${intro}<div class="pz-filterbar"><label>Amt suchen <input type="search" id="pz-q" value="${esc(state.q)}" autocomplete="off"></label>
      <label class="check"><input type="checkbox" id="pz-frueher"${state.frueher ? " checked" : ""}> frühere Ämter zeigen</label></div>
      <p class="hint" aria-live="polite">${shown.length} Ämter und Stellen</p>
      ${groups(shown).map(([g, as]) => `<h3 class="pz-h">${esc(g.label)}</h3>${as.map((a) => `<details class="pz-item" data-amt="${esc(a.id)}"${state.amt === a.id ? " open" : ""}><summary><span class="pz-title">${esc(a.name)}</span><span class="pz-meta">${esc(amtMeta(a))}</span></summary>${amtBody(a)}</details>`).join("")}`).join("")}`;
  }
  return `${intro}<div class="org" role="group" aria-label="Ämter und Stellen der Stadtverwaltung Bonn">
      ${groups(cur).map(([g, as]) => `<section class="org-beirat" aria-label="${esc(g.label)}"><h3 class="org-h">${esc(g.label)}</h3>
        <div class="org-grid">${as.map(amtBtn).join("")}</div></section>`).join("")}
    </div>
    <p class="hint">Gezeigt sind die aktiven Ämter und Stellen; frühere stehen in der Liste. Die Zahl nennt die Vorlagen, bei denen das Amt laut Quelle federführend ist.</p>
    <div id="pz-detail" class="pz-detail" aria-live="polite">${sel ? `<h3 class="pz-h" tabindex="-1">${esc(sel.name)}</h3>${amtBody(sel)}` : `<p class="hint">Wählen Sie ein Amt, um seine Abteilungen, Vorlagen und die beratenden Gremien zu sehen.</p>`}</div>`;
}

// --- Steuerung ---------------------------------------------------------------------------------------
function render(focusDetail) {
  root.querySelectorAll("[role=tab]").forEach((t) => {
    const on = t.dataset.tab === state.tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  });
  root.querySelectorAll("[data-view]").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.view === state.view));
    b.tabIndex = b.dataset.view === state.view ? 0 : -1;
  });
  const body = root.querySelector("#pz-body");
  body.setAttribute("aria-labelledby", `tab-pz-${state.tab}`);
  body.innerHTML = !soll || !data ? '<p class="hint">Die Daten zu den Prozessen sind nicht verfügbar.</p>'
    : state.tab === "gremien" ? renderGremien() : state.tab === "aemter" ? renderAemter() : renderVerfahren();
  if (focusDetail) body.querySelector("#pz-detail h3")?.focus();
  ctx.onState({ ...state });
}
function set(patch, focusDetail) { Object.assign(state, patch); render(focusDetail); }

export async function init(c) {
  ctx = c;
  root = document.getElementById("panel-prozesse");
  [soll, data] = await Promise.all([ctx.loadSoll(), fetch(ctx.BONN + "prozessarten.json").then((r) => (r.ok ? r.json() : null)).catch(() => null)]);
  root.querySelector("[role=tablist]").addEventListener("click", (e) => { const t = e.target.closest("[role=tab]"); if (t && t.dataset.tab !== state.tab) set({ tab: t.dataset.tab, q: "" }); });
  root.querySelector("[role=tablist]").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = TABS.indexOf(state.tab) + (e.key === "ArrowRight" ? 1 : -1);
    set({ tab: TABS[(i + TABS.length) % TABS.length], q: "" });
    root.querySelector(`[role=tab][data-tab="${state.tab}"]`).focus();
  });
  root.querySelector(".pz-view").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) set({ view: b.dataset.view }); });
  root.querySelector(".pz-view").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    set({ view: state.view === "schaubild" ? "liste" : "schaubild" });
    root.querySelector(`[data-view="${state.view}"]`).focus();
  });
  const body = root.querySelector("#pz-body");
  body.addEventListener("change", (e) => {
    if (e.target.id === "pz-verfahren") set({ verfahren: e.target.value });
    if (e.target.id === "pz-frueher") set({ frueher: e.target.checked });
  });
  body.addEventListener("input", (e) => {
    if (e.target.id !== "pz-q") return;
    state.q = e.target.value;
    const pos = e.target.selectionStart;
    render();
    const q = root.querySelector("#pz-q");
    q.focus();
    q.setSelectionRange(pos, pos);
  });
  body.addEventListener("toggle", (e) => {
    const d = e.target;
    if (!d.matches?.("details.pz-item") || !d.open) return;
    if (d.dataset.verfahren) { state.verfahren = d.dataset.verfahren; ctx.onState({ ...state }); }
    if (d.dataset.gremium) { state.gremium = d.dataset.gremium; ctx.onState({ ...state }); }
    if (d.dataset.amt) { state.amt = d.dataset.amt; ctx.onState({ ...state }); }
  }, true);
  body.addEventListener("click", async (e) => {
    const n = e.target.closest(".org-node");
    if (n) return set(n.dataset.amt ? { amt: n.dataset.amt } : { gremium: n.dataset.gremium }, true);
    const ga = e.target.closest(".pz-gremium");
    if (ga) return set({ tab: "gremien", gremium: ga.dataset.gremium, q: "" }, true);
    const am = e.target.closest(".pz-amt");
    if (am) return set({ amt: am.dataset.amt, q: "" }, true);
    const o = e.target.closest(".pz-open");
    if (o) return ctx.openRef(o.dataset.ref);
    const f = e.target.closest(".pz-filter");
    if (f) {
      const amt = f.dataset.kind === "amt";
      const ok = amt ? ctx.filterAmt(f.dataset.name) : ctx.filterGremium(f.dataset.name);
      if (!ok) f.closest(".pz-item, .pz-detail").querySelector(".pz-msg").textContent = amt
        ? "Im gewählten Gebiet gibt es keine Vorlage dieses Amts. Wählen Sie oben ein anderes Gebiet, etwa einen Stadtbezirk."
        : "Im gewählten Gebiet hat dieses Gremium keine Vorlage beraten. Wählen Sie oben ein anderes Gebiet, etwa einen Stadtbezirk.";
    }
  });
}
export function show(s) {
  if (s) Object.assign(state, Object.fromEntries(Object.entries(s).filter(([k, v]) => k !== "gremiumName" && v !== undefined && v !== null)));
  // Gremium per Name (aus „Mitmachen in Bonn“)
  if (s && s.gremiumName && data) state.gremium = ((data.gremien || []).find((g) => g.name === s.gremiumName) || {}).id || state.gremium;
  render();
}
