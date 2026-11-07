// Systemprompt des Ratsassistenten: Text aus systemprompt.md (zwischen den Markierungen), Platzhalter
// aus dem Datenstand. Eine Quelle für Seite, Tests und Auswertung.
import { MAX_TOOL_CALLS } from "./core.js";

export const PROMPT_FILE = "chat/systemprompt.md";
const START = "<!-- PROMPT -->", END = "<!-- /PROMPT -->";

export function extractPrompt(markdown) {
  const a = markdown.indexOf(START), b = markdown.indexOf(END);
  if (a < 0 || b < a) throw new Error("Systemprompt: Markierungen fehlen.");
  return markdown.slice(a + START.length, b).trim();
}

export function version(markdown) {
  return /\(v(\d+\.\d+)\)/.exec(markdown)?.[1] ?? null;
}

// JJJJ-MM-TT oder ISO-Zeitpunkt → TT.MM.JJJJ (Kalendertag in Bonn)
export function deDate(value) {
  if (!value) return "unbekannt";
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00Z`) : new Date(value);
  if (Number.isNaN(d.getTime())) return "unbekannt";
  return new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", year: "numeric" }).format(d);
}

export function fillPrompt(template, { heute, datenstand, datenbeginn, maxToolCalls = MAX_TOOL_CALLS }) {
  const values = { HEUTE: heute, DATENSTAND: datenstand, DATENBEGINN: datenbeginn, MAX_WERKZEUGAUFRUFE: String(maxToolCalls) };
  const out = template.replace(/\{([A-ZÄÖÜ_]+)\}/g, (m, k) => (k in values ? values[k] : m));
  const left = out.match(/\{[A-ZÄÖÜ_]+\}/g);
  if (left) throw new Error(`Systemprompt: Platzhalter ohne Wert: ${left.join(", ")}`);
  return out;
}

// Werte aus datenstand.json (Abruf der OParl-API der Stadt) und dem heutigen Tag
export function promptValues(status, now = new Date()) {
  const oparl = status?.sources?.find((s) => s.name === "oparl-bonn");
  return { heute: deDate(now.toISOString()), datenstand: deDate(oparl?.retrieved_at), datenbeginn: deDate(status?.first_date) };
}

export async function loadSystemPrompt({ loadText, status, now }) {
  const md = await loadText(PROMPT_FILE);
  return { text: fillPrompt(extractPrompt(md), promptValues(status, now)), version: version(md) };
}
