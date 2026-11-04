// Oberfläche des Ratsassistenten: Einstellungen (Anbieter, Modell, Schlüssel), Gespräch mit gestreamten
// Antworten, Quellenkarten, Prüfung der genannten Drucksachen, Protokoll der Werkzeugaufrufe und Kopplung
// mit Karte, Liste und Vorgang (window.risKarte aus app.js). Daten und Prompt werden erst beim ersten
// Öffnen geladen.
import { TOOLS, createTools } from "./tools.js";
import { createChat, collectRefs, sameRef } from "./core.js";
import { PROVIDERS, listModels } from "./providers.js";
import { createKeyStore } from "./keys.js";
import { loadSystemPrompt, deDate } from "./prompt.js";
import { renderMarkdown, collectUrls, esc } from "./render.js";

const $ = (s) => document.querySelector(s);
const DATA = "data/export/";
const PREFS = "ris-assistent-einstellungen";   // Anbieter, Modell, Adresse – nie der Schlüssel
const CONSENT = "ris-assistent-hinweis";
const STATIC_URLS = ["https://www.bonn.de/vv/produkte/buergerantrag-anregungen-und-beschwerden-gemaess-24-gemeindeordnung-nrw.php",
  "https://github.com/daimpad/allris-test/blob/main/site/chat/systemprompt.md"];
const TOOL_LABEL = {
  suche_vorlagen: "Vorlagen suchen", hole_vorlage: "Vorlage abrufen", hole_prozesslinie: "Prozesslinie abrufen",
  suche_ort: "Orte suchen", liste_sitzungen: "Sitzungen abrufen", hole_gremium_oder_amt: "Gremium oder Amt abrufen",
  erklaere_begriff: "Begriff nachschlagen", datenstand: "Datenstand abrufen",
  suche_bebauungsplan: "Bebauungspläne suchen", suche_baustellen: "Baustellen suchen", hole_kontext: "Zahlen zum Gebiet abrufen",
};

const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ohne Speicher */ } },
};
const keys = createKeyStore();
const prefs = { provider: "anthropic", models: {}, base: "", ...(store.get(PREFS) || {}) };

let chat = null, ready = null, controller = null, busy = false;
let conv = 0;   // zählt Gespräche; Ereignisse einer Antwort aus einem früheren Gespräch werden verworfen
const urls = new Set(STATIC_URLS);
const refs = new Set();
const cards = new Map();   // Drucksache → { titel, datum, art, links }

// --- Einstellungen ---------------------------------------------------------------------------------------------
function provider() { return PROVIDERS[prefs.provider] ? prefs.provider : "anthropic"; }
function model() { return (prefs.models[provider()] || PROVIDERS[provider()].models[0] || "").trim(); }
function savePrefs() { store.set(PREFS, { provider: prefs.provider, models: prefs.models, base: prefs.base }); }

function fillSettings() {
  const p = provider(), def = PROVIDERS[p];
  $("#chat-provider").value = p;
  $("#chat-model").value = model();
  $("#chat-models").innerHTML = def.models.map((m) => `<option value="${esc(m)}">`).join("");
  $("#chat-base-wrap").hidden = !def.local;
  $("#chat-base").value = prefs.base || "";
  $("#chat-key").value = keys.get(p);
  $("#chat-key").placeholder = def.keyOptional ? "optional" : "Schlüssel einfügen";
  $("#chat-remember").checked = keys.remembered(p);
  $("#chat-key-link").hidden = !def.keyUrl;
  if (def.keyUrl) $("#chat-key-link").href = def.keyUrl;
  if (p === "openrouter" && !def.models.length) {
    listModels("openrouter").then((list) => {
      if (provider() === "openrouter") $("#chat-models").innerHTML = list.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join("");
    }).catch(() => {});
  }
  updateState();
}

function configured() {
  const def = PROVIDERS[provider()];
  return Boolean(model() && (keys.get(provider()) || def.keyOptional));
}

function updateState() {
  const consent = Boolean(store.get(CONSENT));
  $("#chat-intro").hidden = consent;
  $("#chat-settings").hidden = !consent;
  const ok = consent && configured();
  $("#chat-input").disabled = !ok || busy;
  $("#chat-send").disabled = !ok || busy;
  $("#chat-send").hidden = busy;
  $("#chat-stop").hidden = !busy;
  $("#chat-examples").hidden = !ok || busy || $("#chat-log").children.length > 0;
  const key = keys.get(provider());
  $("#chat-settings-summary").textContent = `${PROVIDERS[provider()].label} · ${model() || "kein Modell"} · ${key ? "Schlüssel gesetzt" : PROVIDERS[provider()].keyOptional ? "ohne Schlüssel" : "kein Schlüssel"}`;
  if (consent && !configured()) $("#chat-settings").open = true;
  updateContext();
}

function contextText() {
  const c = window.risKarte?.context?.();
  if (!c || !c.gebiet) return null;
  const zeit = c.von && c.bis ? `; Zeitraum ${deDate(c.von)} bis ${deDate(c.bis)}` : "";
  return `Gebiet „${c.gebiet}“${zeit}`;
}
function updateContext() {
  const t = contextText();
  $("#chat-context-text").textContent = t ? `Kontext mitschicken: ${t}` : "Kontext der Karte mitschicken";
}

// --- Gespräch ------------------------------------------------------------------------------------------------
async function ensureChat() {
  if (chat) return chat;
  ready ||= (async () => {
    const load = (path) => fetch(DATA + path).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
    const status = await load("bonn/chat/datenstand.json");
    const prompt = await loadSystemPrompt({ loadText: (f) => fetch(f).then((r) => r.text()), status });
    const tools = createTools({ load });
    chat = createChat({
      tools: TOOLS, runTool: tools.run, system: prompt.text,
      settings: () => ({ provider: provider(), model: model(), key: keys.get(provider()), baseUrl: prefs.base }),
    });
    chat.promptVersion = prompt.version;
    return chat;
  })().catch((e) => { ready = null; throw e; });
  return ready;
}

function record(result) {
  collectUrls(result, urls);
  collectRefs(result, refs);
  const walk = (v) => {
    if (Array.isArray(v)) return v.forEach(walk);
    if (!v || typeof v !== "object") return;
    if (typeof v.drucksache === "string") {
      const c = cards.get(v.drucksache) || {};
      cards.set(v.drucksache, { ...c, titel: v.titel ?? c.titel, datum: v.datum ?? c.datum, art: v.art ?? c.art, links: v.links ?? c.links });
    }
    Object.values(v).forEach(walk);
  };
  walk(result);
}

function bubble(role, html) {
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  el.innerHTML = html;
  $("#chat-log").append(el);
  return el;
}
function scrollDown() { const b = $("#chat-body"); b.scrollTop = b.scrollHeight; }

function sourceCards(belegt) {
  const list = belegt.map((r) => [...refs].find((x) => sameRef(x, r)) || r);
  const uniq = [...new Set(list)];
  if (!uniq.length) return "";
  return `<details class="acc src-cards" open><summary>Quellen (${uniq.length})</summary><div class="src-list">${uniq.map((ref) => {
    const c = cards.get(ref) || {};
    const l = c.links || {};
    return `<article class="src-card"><p class="src-title">${esc(c.titel || "Vorlage " + ref)}</p>
      <p class="src-meta">${esc(ref)}${c.art ? " · " + esc(c.art) : ""}${c.datum ? " · " + esc(deDate(c.datum)) : ""}</p>
      <p class="src-actions"><button type="button" class="btn btn-soft ref" data-ref="${esc(ref)}">In der Karte zeigen</button>
      ${/^https:\/\//.test(l.ratsinformationssystem || "") ? `<a class="btn btn-ghost" href="${esc(l.ratsinformationssystem)}" target="_blank" rel="noopener noreferrer">Ratsinformationssystem<span class="visually-hidden"> (neuer Tab)</span></a>` : ""}
      ${/^https:\/\//.test(l.dokument || "") ? `<a class="btn btn-ghost" href="${esc(l.dokument)}" target="_blank" rel="noopener noreferrer">Dokument<span class="visually-hidden"> (neuer Tab)</span></a>` : ""}</p></article>`;
  }).join("")}</div></details>`;
}

function protocolHtml(protocol) {
  if (!protocol?.length) return "";
  return `<details class="acc protocol"><summary>Werkzeugaufrufe (${protocol.length})</summary><ol>${protocol.map((p) =>
    `<li><code>${esc(p.werkzeug)}</code> ${esc(JSON.stringify(p.parameter))} – ${p.ok ? "ok" : "Fehler"}${p.ms ? `, ${p.ms} ms` : ""}</li>`).join("")}</ol></details>`;
}

function setBusy(on) { busy = on; updateState(); }
// Sichtbarer Kurzstatus; Ansage für Bildschirmleser nur bei Werkzeugwechsel und am Ende (nicht je Wort)
function status(text, announce = text) {
  $("#chat-status").textContent = text;
  $("#chat-announce").textContent = announce;
}
const plain = (md) => md.replace(/\]\(https?:[^)\s]{0,2000}\)/g, "]").replace(/[*_`#>|[\]]/g, "").replace(/\s+/g, " ").trim();

async function ask(question) {
  const q = question.trim();
  if (!q || busy || !configured()) return;
  setBusy(true);
  const ctx = $("#chat-context").checked ? contextText() : null;
  bubble("user", `<p>${esc(q)}</p>${ctx ? `<p class="msg-ctx">mit Kontext: ${esc(ctx)}</p>` : ""}`);
  const answer = bubble("assistant", `<div class="md stream" aria-busy="true"></div><p class="tool-line" hidden></p>`);
  const stream = answer.querySelector(".md");
  const toolLine = answer.querySelector(".tool-line");
  scrollDown();
  $("#chat-input").value = "";
  status("Der Assistent arbeitet …");
  controller = new AbortController();
  const mine = conv;
  let text = "";
  try {
    const c = await ensureChat();
    const full = ctx ? `${q}\n\n[Kontext der Seite, von der Nutzer:in freigegeben: ${ctx}]` : q;
    for await (const ev of c.ask(full, { signal: controller.signal })) {
      if (mine !== conv) break;
      if (ev.type === "text") { text += ev.text; stream.textContent = text; scrollDown(); }
      else if (ev.type === "tool_start") { toolLine.hidden = false; toolLine.textContent = `${TOOL_LABEL[ev.name] || ev.name} …`; status(`Der Assistent nutzt: ${TOOL_LABEL[ev.name] || ev.name}`); }
      else if (ev.type === "tool_end") { record(ev.result); if (text && !text.endsWith("\n")) { text += "\n\n"; } }
      else if (ev.type === "notice") bubble("note", `<p>${esc(ev.text)}</p>`);
      else if (ev.type === "error") {
        stream.removeAttribute("aria-busy");
        toolLine.hidden = true;
        stream.innerHTML = `${text ? `<p class="partial">${esc(text)}</p>` : ""}<p class="msg-error" role="alert">${esc(ev.message)}</p>`;
        status(ev.message);
        if (ev.kind === "config" || ev.status === 401 || ev.status === 403) $("#chat-settings").open = true;
      } else if (ev.type === "done") {
        toolLine.hidden = true;
        stream.removeAttribute("aria-busy");
        stream.classList.remove("stream");
        stream.innerHTML = renderMarkdown(ev.text, { urls, refs });
        const unbelegt = ev.citations.unbelegt;
        answer.insertAdjacentHTML("beforeend", `${unbelegt.length ? `<p class="msg-warn">Nicht durch abgerufene Daten belegt: ${unbelegt.map(esc).join(", ")}</p>` : ""}
          ${sourceCards(ev.citations.belegt)}${protocolHtml(ev.protocol)}
          <p class="msg-foot">KI-generiert mit ${esc(ev.model || model())} · Datenstand und Originale prüfen</p>`);
        status("Antwort fertig.", `Antwort fertig: ${plain(ev.text).slice(0, 300)}`);
      }
    }
  } catch (e) {
    stream.removeAttribute("aria-busy");
    stream.innerHTML = `<p class="msg-error" role="alert">Der Assistent konnte nicht starten: ${esc(e.message)}</p>`;
    status("Fehler beim Start des Assistenten.");
  } finally {
    controller = null;
    setBusy(false);
    scrollDown();
  }
}

function newConversation(message) {
  conv++;
  controller?.abort();
  chat?.reset();
  refs.clear(); cards.clear(); urls.clear(); STATIC_URLS.forEach((u) => urls.add(u));
  $("#chat-log").innerHTML = "";
  status(message);
  updateState();
}

// --- Kopplung mit Karte, Liste und Vorgang --------------------------------------------------------------------
async function openRef(ref, button) {
  if (!window.risKarte) return;
  button?.setAttribute("aria-busy", "true");
  const ok = await window.risKarte.open(ref).catch(() => false);
  button?.removeAttribute("aria-busy");
  status(ok ? `Vorlage ${ref} in Karte und Vorgang geöffnet.` : `Vorlage ${ref} konnte auf der Karte nicht geöffnet werden.`);
}

// --- Start -------------------------------------------------------------------------------------------------------
function init() {
  $("#chat-provider").innerHTML = Object.entries(PROVIDERS).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("");
  fillSettings();
  $("#chat-consent").addEventListener("click", () => { store.set(CONSENT, true); updateState(); ($("#chat-input").disabled ? $("#chat-settings summary") : $("#chat-input")).focus(); });
  // Anbieterwechsel beginnt ein neues Gespräch: Verlauf und Werkzeug-IDs eines Anbieters passen nicht zum anderen
  $("#chat-provider").addEventListener("change", (e) => {
    prefs.provider = e.target.value; savePrefs(); fillSettings();
    if ($("#chat-log").children.length) newConversation("Anbieter gewechselt: neues Gespräch begonnen.");
  });
  $("#chat-model").addEventListener("change", (e) => { prefs.models[provider()] = e.target.value.trim(); savePrefs(); updateState(); });
  $("#chat-base").addEventListener("change", (e) => { prefs.base = e.target.value.trim(); savePrefs(); });
  const saveKey = () => { keys.set(provider(), $("#chat-key").value, { remember: $("#chat-remember").checked }); updateState(); };
  $("#chat-key").addEventListener("input", saveKey);
  $("#chat-remember").addEventListener("change", saveKey);
  $("#chat-key-clear").addEventListener("click", () => { keys.clear(provider()); $("#chat-key").value = ""; $("#chat-remember").checked = false; updateState(); status("Schlüssel gelöscht."); $("#chat-key").focus(); });
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("#chat-input").value); });
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask($("#chat-input").value); }
  });
  $("#chat-stop").addEventListener("click", () => controller?.abort());
  $("#chat-new").addEventListener("click", () => {
    newConversation("Neues Gespräch begonnen.");
    if (!$("#chat-input").disabled) $("#chat-input").focus();
  });
  $("#chat-examples").addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) ask(b.textContent); });
  $("#panel-assistent").addEventListener("click", (e) => {
    const b = e.target.closest("button.ref[data-ref]");
    if (b) openRef(b.dataset.ref, b);
  });
  // Kontextanzeige aktuell halten, wenn die Fläche geöffnet wird
  new MutationObserver(() => { if (!$("#panel-assistent").hidden) updateContext(); }).observe($("#panel-assistent"), { attributes: true, attributeFilter: ["hidden"] });
}

init();
