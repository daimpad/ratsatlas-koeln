// Anbieter-Adapter des Ratsassistenten: eine gemeinsame Schnittstelle für Nachrichten, Werkzeuge,
// Werkzeugaufrufe und Streaming. Der Browser ruft die Anbieter direkt auf (eigener Schlüssel, kein Proxy).
// Bewusst ohne SDK: statische Seite ohne Build-Schritt, strikte CSP, mehrere Anbieter mit einem Code.
// CORS geprüft am 18.10.2026 (CLAUDE.md, Abschnitt 9). Der Schlüssel geht nur in den Header an den
// gewählten Endpunkt, nie in URL, Protokoll oder Fehlermeldung.
//
// Gemeinsames Nachrichtenformat (Verlauf):
//   { role: "user", text }
//   { role: "assistant", text, toolCalls: [{ id, name, args }], raw?: { provider, content } }
//   { role: "tool", results: [{ id, name, content, isError }] }
// `raw` hält die Antwortblöcke von Anthropic unverändert (auch Denkblöcke mit Signatur); sie werden bei
// der nächsten Anfrage unverändert zurückgegeben, wie die API es bei Werkzeugschleifen verlangt.

export const PROVIDERS = {
  anthropic: {
    label: "Anthropic (Claude)", format: "anthropic", url: "https://api.anthropic.com/v1/messages",
    models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
    // serverseitige Ausweichmodelle bei Ablehnung durch Sicherheitsfilter (Beta), nur diese Modelle
    fallbackModels: ["claude-opus-5-5", "claude-sonnet-5-5"],
    keyUrl: "https://console.anthropic.com/settings/keys",
  },
  mistral: {
    label: "Mistral", format: "openai", url: "https://api.mistral.ai/v1/chat/completions",
    models: ["mistral-medium-latest", "mistral-large-latest", "mistral-small-latest"], toolName: true,
    keyUrl: "https://console.mistral.ai/api-keys",
  },
  openrouter: {
    label: "OpenRouter", format: "openai", url: "https://openrouter.ai/api/v1/chat/completions",
    models: [], modelsUrl: "https://openrouter.ai/api/v1/models", headers: { "X-Title": "Ratsatlas Bonn" },
    keyUrl: "https://openrouter.ai/settings/keys",
  },
  lokal: {
    label: "Lokales Modell (Ollama, LM Studio)", format: "openai", url: "http://localhost:11434/v1/chat/completions",
    models: [], keyOptional: true, local: true,
  },
};

const ANTHROPIC_VERSION = "2023-06-01";
const FALLBACK_BETA = "server-side-fallback-2026-07-01";
const LOCAL = /^http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?\//;
// Ersatz-ID für Werkzeugaufrufe ohne ID (manche lokale Server): eindeutig über Runden, 9 Zeichen [a-z0-9]
// wie von Mistral verlangt
let callSeq = 0;
export const newCallId = () => `c${(++callSeq).toString(36)}${Math.random().toString(36).slice(2)}`.replace(/[^a-z0-9]/g, "").slice(0, 9).padEnd(9, "0");

export class ProviderError extends Error {
  constructor(message, { status = 0, kind = "api" } = {}) { super(message); this.status = status; this.kind = kind; }
}

// Verständliche Meldung je Fehlerart; der Anbietertext wird gekürzt angehängt, der Schlüssel entfernt
export function explain(status, detail = "", key = "") {
  const d = clean(detail, key);
  if (status === 401 || status === 403) return "Der Schlüssel wurde abgelehnt (ungültig oder ohne Berechtigung).";
  if (status === 402) return "Beim Anbieter ist kein Guthaben verfügbar.";
  if (status === 404) return `Modell oder Endpunkt nicht gefunden.${d ? " " + d : ""}`;
  if (status === 429) return "Ratenlimit oder Ausgabenlimit erreicht. Bitte später erneut versuchen.";
  if (status >= 500) return "Der Dienst des Anbieters ist gerade nicht erreichbar oder überlastet.";
  return `Der Anbieter hat die Anfrage abgelehnt (${status}).${d ? " " + d : ""}`;
}
const clean = (s, key) => {
  let t = String(s || "").replace(/\s+/g, " ").trim();
  if (key) t = t.split(key).join("[Schlüssel]");
  return t.replace(/\b(sk-[\w-]{6,}|[A-Za-z0-9_-]{32,})\b/g, "[…]").slice(0, 300);
};

export function endpoint(provider, baseUrl) {
  const p = PROVIDERS[provider];
  if (!p) throw new ProviderError(`Unbekannter Anbieter „${provider}“.`, { kind: "config" });
  if (!p.local || !baseUrl) return p.url;
  const base = String(baseUrl).trim().replace(/\/+$/, "");
  if (!LOCAL.test(base + "/")) throw new ProviderError("Lokale Modelle nur unter http://localhost oder http://127.0.0.1.", { kind: "config" });
  return base + (base.endsWith("/v1") ? "" : "/v1") + "/chat/completions";
}

// --- Server-Sent Events ------------------------------------------------------------------------------------
export async function* sse(body, signal) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "", event = "", data = [];
  try {
    for (;;) {
      if (signal?.aborted) throw signal.reason ?? new DOMException("Abgebrochen", "AbortError");
      const { value, done } = await reader.read();
      buf += done ? decoder.decode() : decoder.decode(value, { stream: true });
      const lines = buf.split(/\r?\n/);
      buf = done ? "" : lines.pop();
      for (const line of lines) {
        if (line === "") {
          if (data.length) yield { event, data: data.join("\n") };
          event = ""; data = [];
        } else if (line.startsWith(":")) continue;
        else if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (done) { if (data.length) yield { event, data: data.join("\n") }; return; }
    }
  } finally { reader.releaseLock?.(); }
}

async function post(url, headers, body, { signal, key, fetchImpl }) {
  let res;
  try {
    res = await fetchImpl(url, { method: "POST", headers, body: JSON.stringify(body), signal });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new ProviderError("Keine Verbindung zum Anbieter (Netzwerk, Browser-Freigabe oder bei lokalen Modellen die erlaubte Herkunft).", { kind: "network" });
  }
  if (!res.ok) {
    let detail = "";
    try { const j = await res.json(); detail = j?.error?.message || j?.message || j?.detail || ""; } catch (e) { /* kein JSON */ }
    throw new ProviderError(explain(res.status, typeof detail === "string" ? detail : JSON.stringify(detail), key), { status: res.status });
  }
  return res;
}

// Werkzeugeingaben streng parsen; ungültiges JSON wird nicht ausgeführt, sondern als Fehler zurückgemeldet
function parseArgs(text) {
  if (!text || !text.trim()) return { args: {} };
  try {
    const v = JSON.parse(text);
    return v && typeof v === "object" && !Array.isArray(v) ? { args: v } : { invalid: text };
  } catch (e) { return { invalid: text }; }
}

// --- Anthropic Messages API ----------------------------------------------------------------------------------
export function toAnthropic(history) {
  const out = [];
  for (const m of history) {
    if (m.role === "user") out.push({ role: "user", content: m.text });
    else if (m.role === "assistant") {
      if (m.raw?.provider === "anthropic" && m.raw.content.length) out.push({ role: "assistant", content: m.raw.content });
      else {
        const content = [...(m.text ? [{ type: "text", text: m.text }] : []),
          ...(m.toolCalls || []).map((c) => ({ type: "tool_use", id: c.id, name: c.name, input: c.args ?? {} }))];
        if (content.length) out.push({ role: "assistant", content });
      }
    } else if (m.role === "tool") {
      out.push({ role: "user", content: m.results.map((r) => ({ type: "tool_result", tool_use_id: r.id, content: r.content, ...(r.isError ? { is_error: true } : {}) })) });
    }
  }
  return out;
}

async function* anthropic({ model, key, system, history, tools, toolChoice, maxTokens, signal, fetchImpl }) {
  const p = PROVIDERS.anthropic;
  const fallback = p.fallbackModels.includes(model);
  const headers = {
    "content-type": "application/json", "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
    "anthropic-dangerous-direct-browser-access": "true", ...(fallback ? { "anthropic-beta": FALLBACK_BETA } : {}),
  };
  const body = {
    model, max_tokens: maxTokens, stream: true, system, messages: toAnthropic(history),
    ...(tools?.length ? {
      tools: tools.map((t) => ({ name: t.name, description: t.description, input_schema: t.parameters, eager_input_streaming: true })),
      tool_choice: { type: toolChoice === "none" ? "none" : "auto" },
    } : {}),
    ...(fallback ? { fallbacks: "default" } : {}),
  };
  const res = await post(p.url, headers, body, { signal, key, fetchImpl });
  const blocks = [];
  const json = {};
  const closed = new Set();   // Blöcke mit content_block_stop
  let stop = null, served = model, usage = {}, ended = false;
  for await (const { data } of sse(res.body, signal)) {
    let ev;
    try { ev = JSON.parse(data); } catch (e) { continue; }
    switch (ev.type) {
      case "message_start": served = ev.message?.model || served; usage = { ...ev.message?.usage }; break;
      case "content_block_start":
        blocks[ev.index] = structuredClone(ev.content_block);
        if (ev.content_block.type === "tool_use") json[ev.index] = "";
        if (ev.content_block.type === "fallback") yield { type: "fallback", from: ev.content_block.from?.model, to: ev.content_block.to?.model };
        break;
      case "content_block_delta": {
        const b = blocks[ev.index], d = ev.delta;
        if (!b) break;
        if (d.type === "text_delta") { b.text = (b.text || "") + d.text; yield { type: "text", text: d.text }; }
        else if (d.type === "thinking_delta") b.thinking = (b.thinking || "") + d.thinking;
        else if (d.type === "signature_delta") b.signature = (b.signature || "") + d.signature;
        else if (d.type === "input_json_delta") json[ev.index] += d.partial_json;
        break;
      }
      case "content_block_stop": {
        closed.add(ev.index);
        const b = blocks[ev.index];
        if (b?.type === "tool_use") {
          const parsed = parseArgs(json[ev.index]);
          b.input = parsed.args ?? {};
          if (parsed.invalid != null) b._invalid = parsed.invalid;
        }
        break;
      }
      case "message_delta":
        stop = ev.delta?.stop_reason ?? stop;
        usage = { ...usage, ...ev.usage };
        break;
      case "message_stop": ended = true; break;
      case "error":
        throw new ProviderError(explain(ev.error?.type === "overloaded_error" ? 529 : 400, ev.error?.message, key), { status: 0 });
      default: break;
    }
  }
  // Verbindung ohne Abschluss: die Antwort ist unvollständig; ein halb übertragener Werkzeugaufruf darf nicht mit
  // leerer Eingabe ausgeführt werden (Code-Prüfung 23.10.2026)
  if (!ended && stop == null) throw new ProviderError(INCOMPLETE, { status: 0 });   // stop_reason kommt erst am Ende
  // Nach einem Wechsel auf ein Ausweichmodell: vor der letzten Grenze nur Textblöcke behalten
  const list = blocks.filter((b, i) => b && (b.type !== "tool_use" || closed.has(i)));
  const edge = list.map((b) => b.type).lastIndexOf("fallback");
  const kept = list.filter((b, i) => b.type !== "fallback" && (i > edge || b.type === "text"));
  const calls = kept.filter((b) => b.type === "tool_use");
  for (const b of calls) yield { type: "tool_call", id: b.id, name: b.name, args: b.input, ...(b._invalid != null ? { invalid: b._invalid } : {}) };
  const content = kept.map(({ _invalid, ...b }) => b).filter((b) => b.type !== "text" || b.text);
  yield {
    type: "done", model: served, usage,
    stop: { end_turn: "end", stop_sequence: "end", tool_use: "tool_use", max_tokens: "max_tokens", refusal: "refusal" }[stop] || stop || "end",
    raw: { provider: "anthropic", content },
  };
}

const INCOMPLETE = "Die Verbindung wurde unterbrochen, bevor die Antwort vollständig war. Bitte die Frage erneut stellen.";

// --- OpenAI-kompatible Chat Completions (Mistral, OpenRouter, lokale Server) ---------------------------------
export function toOpenAI(history, system, { toolName = false } = {}) {
  const out = system ? [{ role: "system", content: system }] : [];
  for (const m of history) {
    if (m.role === "user") out.push({ role: "user", content: m.text });
    else if (m.role === "assistant") {
      const calls = (m.toolCalls || []).map((c) => ({ id: c.id, type: "function", function: { name: c.name, arguments: JSON.stringify(c.args ?? {}) } }));
      if (m.text || calls.length) out.push({ role: "assistant", content: m.text || "", ...(calls.length ? { tool_calls: calls } : {}) });
    } else if (m.role === "tool") {
      for (const r of m.results) out.push({ role: "tool", tool_call_id: r.id, content: r.content, ...(toolName ? { name: r.name } : {}) });
    }
  }
  return out;
}

async function* openai({ provider, model, key, system, history, tools, toolChoice, maxTokens, signal, fetchImpl, baseUrl }) {
  const p = PROVIDERS[provider];
  const headers = { "content-type": "application/json", ...(key ? { authorization: `Bearer ${key}` } : {}), ...(p.headers || {}) };
  const body = {
    model, stream: true, max_tokens: maxTokens, messages: toOpenAI(history, system, p),
    ...(tools?.length ? {
      tools: tools.map((t) => ({ type: "function", function: { name: t.name, description: t.description, parameters: t.parameters } })),
      tool_choice: toolChoice === "none" ? "none" : "auto",
    } : {}),
  };
  const res = await post(endpoint(provider, baseUrl), headers, body, { signal, key, fetchImpl });
  let text = "", finish = null, served = model, usage = {}, done = false;
  const calls = [];
  for await (const { data } of sse(res.body, signal)) {
    if (data.trim() === "[DONE]") { done = true; break; }
    let ev;
    try { ev = JSON.parse(data); } catch (e) { continue; }
    if (ev.error) throw new ProviderError(explain(ev.error.code || 400, ev.error.message, key));
    served = ev.model || served;
    if (ev.usage) usage = ev.usage;
    const choice = ev.choices?.[0];
    if (!choice) continue;
    const d = choice.delta || {};
    if (typeof d.content === "string" && d.content) { text += d.content; yield { type: "text", text: d.content }; }
    (d.tool_calls || []).forEach((tc) => {
      // Index fehlt bei manchen Anbietern (Mistral liefert Aufrufe vollständig in einem Stück)
      let i = Number.isInteger(tc.index) ? tc.index : -1;
      if (i < 0 && tc.id) i = calls.findIndex((c) => c?.id === tc.id);
      if (i < 0) i = calls.length;
      const c = (calls[i] ||= { id: null, name: "", args: "" });
      if (tc.id) c.id = tc.id;
      if (tc.function?.name) c.name = tc.function.name;
      if (tc.function?.arguments != null) c.args += typeof tc.function.arguments === "string" ? tc.function.arguments : JSON.stringify(tc.function.arguments);
    });
    if (choice.finish_reason) finish = choice.finish_reason;
  }
  // ohne „[DONE]“ und ohne finish_reason ist die Antwort abgebrochen (siehe oben)
  if (!done && !finish) throw new ProviderError(INCOMPLETE, { status: 0 });
  const list = calls.filter(Boolean).map((c) => ({ ...c, id: c.id || newCallId() }));
  for (const c of list) {
    const parsed = parseArgs(c.args);
    yield { type: "tool_call", id: c.id, name: c.name, args: parsed.args ?? {}, ...(parsed.invalid != null ? { invalid: parsed.invalid } : {}) };
  }
  const stop = finish === "length" ? "max_tokens" : finish === "content_filter" ? "refusal" : list.length ? "tool_use" : "end";
  yield { type: "done", model: served, usage, stop, raw: null, text };
}

// --- Gemeinsamer Einstieg ------------------------------------------------------------------------------------
export function stream(opts) {
  const p = PROVIDERS[opts.provider];
  if (!p) throw new ProviderError(`Unbekannter Anbieter „${opts.provider}“.`, { kind: "config" });
  if (!opts.key && !p.keyOptional) throw new ProviderError("Bitte zuerst einen API-Schlüssel eintragen.", { kind: "config" });
  if (!opts.model) throw new ProviderError("Bitte ein Modell wählen.", { kind: "config" });
  const o = { fetchImpl: globalThis.fetch.bind(globalThis), maxTokens: 16000, toolChoice: "auto", ...opts };
  return p.format === "anthropic" ? anthropic(o) : openai(o);
}

// Modelle mit Werkzeugunterstützung (OpenRouter: öffentliche Liste; lokal: /v1/models des Servers)
export async function listModels(provider, { baseUrl, fetchImpl = globalThis.fetch.bind(globalThis) } = {}) {
  const p = PROVIDERS[provider];
  if (p.modelsUrl) {
    const d = await (await fetchImpl(p.modelsUrl)).json();
    return d.data.filter((m) => (m.supported_parameters || []).includes("tools")).map((m) => ({ id: m.id, name: m.name || m.id })).sort((a, b) => a.name.localeCompare(b.name));
  }
  if (p.local) {
    const url = endpoint(provider, baseUrl).replace(/\/chat\/completions$/, "/models");
    const d = await (await fetchImpl(url)).json();
    return (d.data || []).map((m) => ({ id: m.id, name: m.id }));
  }
  return p.models.map((id) => ({ id, name: id }));
}
