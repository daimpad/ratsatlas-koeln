// Darstellung der Modellantworten: kleines Markdown ohne HTML-Durchreichung (alles wird maskiert).
// Links nur zu Adressen, die in Werkzeugergebnissen dieses Gesprächs vorkamen; Drucksachennummern werden
// zu Schaltflächen (belegt) oder sichtbar markiert (nicht durch abgerufene Daten belegt).
import { REF_RX, sameRef } from "./core.js";

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Felder, in denen ein Werkzeugergebnis Eingaben des Modells wiederholt: daraus keine Adressen übernehmen,
// sonst könnte das Modell (etwa nach einer Anweisung in einem Titel) jede Adresse anklickbar machen
const ECHO = new Set(["anfrage", "eingabe", "fehler", "technisch", "parameter"]);
// Nur Adressen dieser Stellen werden Links (Ratsinformationssystem, Stadt Bonn, OParl-Lite, Gesetze, OSM, Projekt)
export const LINK_HOSTS = ["bonn.sitzung-online.de", "bonn.de", "oparl.bonn.machdenstaat.de", "recht.nrw.de",
  "gesetze-im-internet.de", "openstreetmap.org", "github.com"];
const hostOk = (url) => {
  try {
    const h = new URL(url).hostname;
    return LINK_HOSTS.some((d) => h === d || h.endsWith(`.${d}`));
  } catch (e) { return false; }
};

// Alle http(s)-Adressen aus einem Werkzeugergebnis (ohne wiederholte Eingaben, nur bekannte Stellen)
export function collectUrls(value, set = new Set()) {
  if (typeof value === "string") { if (/^https?:\/\/\S+$/.test(value) && hostOk(value)) set.add(value); }
  else if (Array.isArray(value)) value.forEach((v) => collectUrls(v, set));
  else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => { if (!ECHO.has(k)) collectUrls(v, set); });
  return set;
}

// Zu einer genannten Nummer die Drucksache aus den Werkzeugergebnissen (z. B. „261798-01“ → „261798-01 ST“)
export function resolveRef(ref, refs) {
  const r = ref.trim().replace(/\s+/g, " ");
  for (const x of refs) if (sameRef(x, r)) return x;
  return null;
}

function allowedUrl(url, urls) {
  try {
    const u = new URL(url);
    return (u.protocol === "https:" || u.protocol === "http:") && urls.has(url);
  } catch (e) { return false; }
}

function refsIn(html, ctx) {
  return html.replace(REF_RX, (m) => {
    const full = resolveRef(m, ctx.refs);
    return full
      ? `<button type="button" class="ref" data-ref="${esc(full)}" title="In Karte und Vorgang zeigen">${m}</button>`
      : `<mark class="unbelegt" title="Nicht durch abgerufene Daten belegt">${m}</mark>`;
  });
}

function emphasis(html) {
  return html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?!\w)/g, "$1<em>$2</em>");
}

function text(s, ctx, inLink) {
  const html = emphasis(esc(s));
  return inLink ? html : refsIn(html, ctx);
}

// Längen begrenzt: lange Folgen von „[“ in einer Antwort sollen die Seite nicht anhalten (Code-Prüfung 23.10.2026)
const LINK = /\[([^\]\n[]{1,300})\]\(([^)\s]{1,2000})\)|(https?:\/\/[^\s<>()"]{0,2000}[^\s<>()".,;:!?'])/g;

function links(s, ctx) {
  let out = "", last = 0;
  for (const m of s.matchAll(LINK)) {
    out += text(s.slice(last, m.index), ctx);
    const url = m[2] ?? m[3];
    const label = m[1] ?? m[3];
    if (allowedUrl(url, ctx.urls)) out += `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${text(label, ctx, true)}<span class="visually-hidden"> (neuer Tab)</span></a>`;
    else out += `${text(label, ctx, true)} <span class="link-removed">(Link entfernt: nicht aus den Daten)</span>`;
    last = m.index + m[0].length;
  }
  return out + text(s.slice(last), ctx);
}

function inline(s, ctx) {
  return s.split(/(`[^`\n]+`)/).map((part, i) => (i % 2 ? `<code>${esc(part.slice(1, -1))}</code>` : links(part, ctx))).join("");
}

export function renderMarkdown(source, { urls = new Set(), refs = new Set() } = {}) {
  const ctx = { urls, refs };
  const lines = String(source ?? "").replace(/\r/g, "").split("\n");
  const out = [];
  let para = [], list = null, table = null, code = null;
  const flushPara = () => { if (para.length) out.push(`<p>${para.map((l) => inline(l, ctx)).join("<br>")}</p>`); para = []; };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i, ctx)}</li>`).join("")}</${list.tag}>`); list = null; };
  const flushTable = () => {
    if (table) {
      const [head, ...rows] = table;
      out.push(`<div class="md-table"><table><thead><tr>${head.map((c) => `<th scope="col">${inline(c, ctx)}</th>`).join("")}</tr></thead><tbody>${rows
        .map((r) => `<tr>${r.map((c) => `<td>${inline(c, ctx)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
    }
    table = null;
  };
  const flush = () => { flushPara(); flushList(); flushTable(); };
  for (const line of lines) {
    if (code) {
      if (/^```/.test(line)) { out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) { flush(); code = []; continue; }
    if (!line.trim()) { flush(); continue; }
    const cells = /^\s*\|(.+)\|\s*$/.exec(line);
    if (cells) {
      flushPara(); flushList();
      if (/^[\s|:-]+$/.test(cells[1])) continue;
      (table ||= []).push(cells[1].split("|").map((c) => c.trim()));
      continue;
    }
    flushTable();
    let m;
    if ((m = /^#{1,6}\s+(.*)$/.exec(line))) { flush(); out.push(`<p class="md-h"><strong>${inline(m[1], ctx)}</strong></p>`); continue; }
    if ((m = /^\s*[-*•]\s+(.*)$/.exec(line)) || (m = /^\s*\d+[.)]\s+(.*)$/.exec(line))) {
      const tag = /^\s*\d/.test(line) ? "ol" : "ul";
      flushPara();
      if (list && list.tag !== tag) flushList();
      (list ||= { tag, items: [] }).items.push(m[1]);
      continue;
    }
    if ((m = /^>\s?(.*)$/.exec(line))) { flush(); out.push(`<blockquote>${inline(m[1], ctx)}</blockquote>`); continue; }
    if (list) flushList();
    para.push(line);
  }
  if (code) out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
  flush();
  return out.join("");
}
