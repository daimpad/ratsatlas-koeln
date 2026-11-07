// Fläche „Mitmachen in Bonn“: Wege, sich einzubringen, für einen gewählten Stadtbezirk – mit den nächsten Gelegenheiten
// aus dem Sitzungskalender (zeit.json, OParl-API der Stadt Bonn) und Fristen nach dem Regelwerk (soll.json, Soll-Modell
// nach „Bonn entscheidet“ mit Ergänzungen des Ratsatlas). Fristdaten sind abgeleitet; maßgeblich sind Einladung,
// Geschäftsordnung und Gemeindeordnung. Wird von app.js erst beim Öffnen geladen.
import { addDays, deDate } from "./mitwirken.js";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Adressen aus den Daten nur als http(s)-Link (javascript: o. Ä. würde sonst als Link eingesetzt)
const href = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? esc(u) : "#");
const BEZIRKE = ["Bonn", "Bad Godesberg", "Beuel", "Hardtberg"];
// Reihenfolge und Überschriften der Wege; Texte und Belege aus den Regeln des Soll-Modells
const WEGE = [
  ["sitzung-besuchen", "Sitzung besuchen"],
  ["einwohnerfrage", "Frage in der Einwohnerfragestunde stellen"],
  ["eigener-buergerantrag", "Eigenen Bürgerantrag einbringen"],
  ["ansprechen-bv", "Bezirksverordnete ansprechen"],
  ["ansprechen-rat", "Fraktionen oder Gruppen im Rat ansprechen"],
  ["livestream", "Ratssitzung im Livestream verfolgen"],
  ["offenlage", "Stellungnahme in der Offenlage abgeben"],
];
const BUERGERANTRAG_URL = "https://www.bonn.de/vv/produkte/buergerantrag-anregungen-und-beschwerden-gemaess-24-gemeindeordnung-nrw.php";

let ctx, soll, root, state = { bezirk: "Bonn" };

const links = (ls) => (ls || []).map((l) => `<a href="${href(l.url)}" target="_blank" rel="noopener">${esc(l.label)}<span class="visually-hidden"> (neuer Tab)</span></a>`).join(" · ");
const when = (m) => `${deDate(m.date)}${m.time ? `, ${esc(m.time)} Uhr` : ""}`;

// nächste Sitzung eines Gremiums (nicht abgesagt), optional erst ab einem Datum
function next(gremium, from) {
  return (ctx.meetings() || []).filter((m) => m.gremium === gremium && !m.cancelled && m.date >= from)
    .sort((a, b) => a.date.localeCompare(b.date))[0] || null;
}

function gelegenheiten(bz, today) {
  const bv = `Bezirksvertretung ${bz}`;
  const sitzung = next(bv, today);
  // Einreichen 21 Tage vor der Sitzung: nächste Sitzung, für die die Frist noch nicht abgelaufen ist
  const frist = next(bv, addDays(today, 21));
  const rat = next("Rat", today);
  const stadt = soll.buergerantrag_ziel?.stadt;
  const stadtSitzung = stadt ? next(stadt, addDays(today, 21)) : null;
  const row = (label, body) => `<li><span class="bt-when">${label}</span><span>${body}</span></li>`;
  const items = [
    sitzung && row(when(sitzung), `Nächste Sitzung der ${esc(bv)}${sitzung.web ? ` · <a href="${href(sitzung.web)}" target="_blank" rel="noopener">Tagesordnung<span class="visually-hidden"> (neuer Tab)</span></a>` : " · Tagesordnung noch nicht veröffentlicht"}`),
    frist && row(`bis ${deDate(addDays(frist.date, -21))}`, `Einwohnerfrage oder Bürgerantrag für die Sitzung der ${esc(bv)} am ${deDate(frist.date)} einreichen`),
    stadtSitzung && row(`bis ${deDate(addDays(stadtSitzung.date, -21))}`, `Bürgerantrag zu einem stadtweiten Anliegen für den ${esc(stadt)} am ${deDate(stadtSitzung.date)}`),
    rat && row(when(rat), "Nächste Sitzung des Rates, öffentlich und im Livestream"),
  ].filter(Boolean);
  return `<section class="bt-next" aria-labelledby="bt-next-h"><h3 id="bt-next-h">Nächste Gelegenheiten im Stadtbezirk ${esc(bz)}</h3>
    ${items.length ? `<ul class="bt-dates">${items.join("")}</ul>` : '<p class="hint">Im Sitzungskalender ist noch keine kommende Sitzung eingetragen.</p>'}
    <p class="hint"><span class="derived">abgeleitet</span> Fristen berechnet aus den Sitzungsterminen (21 Tage vor der Sitzung); maßgeblich sind Einladung und Geschäftsordnung.</p>
    <p class="bt-actions"><button type="button" class="btn btn-soft" id="bt-termine">Alle kommenden Sitzungen</button></p></section>`;
}

function zeitstrahl() {
  const fr = soll.fristen || [];
  return `<section aria-labelledby="bt-fristen-h"><h3 id="bt-fristen-h">Fristen rund um eine Sitzung</h3>
    <ol class="bt-line">${fr.map((f) => `<li class="${f.t === 0 ? "bt-day" : ""}"><span class="bt-dot" aria-hidden="true"></span><strong>${esc(f.label)}</strong><span>${esc(f.was)}</span></li>`).join("")}</ol>
    <p class="hint">T ist der Sitzungstag. Rechtsgrundlagen: ${[...new Map(fr.flatMap((f) => f.links || []).map((l) => [l.url, l])).values()].map((l) => `<a href="${href(l.url)}" target="_blank" rel="noopener">${esc(l.label.replace(/\s*§.*$/, ""))}<span class="visually-hidden"> (neuer Tab)</span></a>`).join(" · ")}</p></section>`;
}

function wege(bz, today) {
  const bv = `Bezirksvertretung ${bz}`;
  const sitzung = next(bv, today), frist = next(bv, addDays(today, 21));
  const fill = (t) => t.replace("{gremium}", bv).replace("{datum}", sitzung ? deDate(sitzung.date) : "dem nächsten Termin")
    .replace("{ziel}", `die ${bv}`).replace("{ziel_datum}", frist ? deDate(frist.date) : "der nächsten Sitzung");
  const rules = new Map((soll.mitwirken || []).map((r) => [r.id, r]));
  const extra = { "eigener-buergerantrag": `<a class="btn btn-cta" href="${BUERGERANTRAG_URL}" target="_blank" rel="noopener">Bürgerantrag stellen<span class="visually-hidden"> (Seite der Stadt Bonn, neuer Tab)</span></a>`,
    "ansprechen-bv": `<button type="button" class="btn btn-soft" data-gremium="${esc(bv)}">${esc(bv)} im Reiter Prozesse</button>`,
    "ansprechen-rat": '<button type="button" class="btn btn-soft" data-gremium="Rat">Rat im Reiter Prozesse</button>',
    offenlage: '<button type="button" class="btn btn-soft" id="bt-plaene">Bebauungspläne auf der Karte</button>' };
  return `<section aria-labelledby="bt-wege-h"><h3 id="bt-wege-h">Wege, sich einzubringen</h3><div class="bt-cards">${WEGE.filter(([id]) => rules.has(id)).map(([id, title]) => {
    const r = rules.get(id);
    return `<article class="bt-card"><h4>${esc(title)}</h4><p>${esc(fill(r.was))}</p>
      <p class="hint">Frist: ${esc(r.frist)}${r.links?.length ? ` · ${links(r.links)}` : r.beleg ? ` · ${esc(r.beleg)}` : ""}</p>
      ${extra[id] ? `<p class="bt-actions">${extra[id]}</p>` : ""}</article>`;
  }).join("")}</div></section>`;
}

function render() {
  const body = root.querySelector("#bt-body");
  if (!soll) { body.innerHTML = '<p class="hint">Das Regelwerk ist nicht verfügbar.</p>'; return; }
  // heutiges Datum in Bonn, nicht UTC
  const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Berlin" }).format(new Date()), bz = state.bezirk;
  body.innerHTML = `<label class="bt-pick">Ihr Stadtbezirk <select id="bt-bezirk">${BEZIRKE.map((b) => `<option${b === bz ? " selected" : ""}>${esc(b)}</option>`).join("")}</select></label>
    ${gelegenheiten(bz, today)}${zeitstrahl()}${wege(bz, today)}
    <p class="hint">Vereinfachte Darstellung nach der Geschäftsordnung des Rates, der Hauptsatzung, der Gemeindeordnung NRW und dem Baugesetzbuch; keine Rechtsauskunft. Welche Wege bei einem bestimmten Vorgang offen sind, zeigt dort der Abschnitt „Selbst mitwirken“.</p>`;
  ctx.onState({ ...state });
}

export async function init(c) {
  ctx = c;
  root = document.getElementById("panel-mitmachen");
  soll = await ctx.loadSoll();
  const body = root.querySelector("#bt-body");
  body.addEventListener("change", (e) => { if (e.target.id === "bt-bezirk") { state.bezirk = e.target.value; render(); root.querySelector("#bt-bezirk").focus(); } });
  body.addEventListener("click", (e) => {
    if (e.target.closest("#bt-termine")) return ctx.openTermine();
    if (e.target.closest("#bt-plaene")) return ctx.openPlaene();
    const g = e.target.closest("[data-gremium]");
    if (g) ctx.openGremium(g.dataset.gremium);
  });
}
export function show(s) {
  if (s && BEZIRKE.includes(s.bezirk)) state.bezirk = s.bezirk;
  render();
}
