// Fläche „Mitmachen in Köln“: Wege, sich in Rat, Ausschüssen und Bezirksvertretungen der Stadt Köln einzubringen, für
// einen gewählten Stadtbezirk – mit den nächsten Sitzungen aus dem Sitzungskalender (zeit.json, OParl-API der Stadt Köln).
// Zweiter Lauf (Entscheidung 13.11.2026), ersetzt die Bonner Fassung (Regelwerk aus soll.json, Bonner Stadtbezirke und
// Links). Die Texte fassen die Gemeindeordnung NRW (Fassung ab 01.01.2026), die Geschäftsordnung des Rates und der
// Bezirksvertretungen der Stadt Köln (beschlossen am 19.03.2026) und Seiten der Stadt Köln zusammen; jede Angabe nennt
// ihre Fundstelle. Alle Adressen am 13.11.2026 abgerufen und geprüft (Liste in TECHNIK.md, „Mitmachen in Köln“; vier
// Stellen am 14.11.2026 nachgeprüft: § 37 Abs. 1 und § 41 Abs. 1 GO NRW, Seite zur Einwohnerfragestunde, Postanschrift);
// tests/test_mitmachen_koeln.py prüft, dass keine andere Adresse vorkommt. Fristen stehen als Regel da, ohne berechnetes
// Datum (Arbeitstage hängen von Feiertagen ab). Wird von app.js erst beim Öffnen geladen; ohne Freigabe „mitmachen“
// (config.ZUSATZTHEMEN) fehlt die Fläche im veröffentlichten HTML.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// Adressen aus den Daten (Sitzungen) nur als http(s)-Link (javascript: o. Ä. würde sonst als Link eingesetzt)
const href = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? esc(u) : "");

// Stadtbezirke in der Reihenfolge ihrer Nummern (Hauptsatzung; wie pipeline/geocode.BEZIRKE_KOELN)
export const BEZIRKE = ["Innenstadt", "Rodenkirchen", "Lindenthal", "Ehrenfeld", "Nippes", "Chorweiler", "Porz", "Kalk", "Mülheim"];
export const STAND = "13.11.2026";

// Fundstellen und Seiten der Stadt; `wo` nennt den Anbieter für Screenreader („neuer Tab“)
const STADT = "Seite der Stadt Köln";
export const QUELLEN = {
  ausschuss: { label: "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden", wo: STADT,
    url: "https://www.stadt-koeln.de/politik-und-verwaltung/mitwirkung-von-buergerinnen/anregungenbeschwerden" },
  geschaeftsstelle: { label: "Geschäftsstelle für Anregungen und Beschwerden", wo: STADT,
    url: "https://www.stadt-koeln.de/service/adressen/geschaeftsstelle-fuer-anregungen-und-beschwerden-rat-und-bez" },
  formular: { label: "Kontaktformular des Ausschusses", wo: STADT,
    url: "https://www.stadt-koeln.de/service/onlinedienste/kontakt-ausschuss-fuer-buergerbeteiligung-anregungen-beschwerden" },
  fragestunde: { label: "Einwohnerfragestunde", wo: STADT, url: "https://www.stadt-koeln.de/artikel/61860/index.html" },
  einwohnerantrag: { label: "Einwohnerantrag", wo: STADT,
    url: "https://www.stadt-koeln.de/politik-und-verwaltung/mitwirkung-von-buergerinnen/einwohnerantrag" },
  quorum: { label: "Bekanntmachung zum Bürgerbegehren vom 26.02.2026 (PDF)", wo: STADT,
    url: "https://www.stadt-koeln.de/mediaasset/content/bekanntmachungen/2026/2026.02.26_0032-01_quorum_buergerbegehren.pdf" },
  ratLive: { label: "Ratssitzung online", wo: STADT, url: "https://www.stadt-koeln.de/rat-live/" },
  beteiligung: { label: "Systematische Öffentlichkeitsbeteiligung", wo: STADT,
    url: "https://www.stadt-koeln.de/politik-und-verwaltung/mitwirkung/systematische-oeffentlichkeitsbeteiligung" },
  gescho: { label: "Geschäftsordnung des Rates und der Bezirksvertretungen (19.03.2026, PDF)", wo: STADT,
    url: "https://www.stadt-koeln.de/mediaasset/content/satzungen/geschaeftsordnung-rat-und-bezirksvertretungen_20260319.pdf" },
  go: { label: "Gemeindeordnung NRW", wo: "recht.nrw.de",
    url: "https://recht.nrw.de/lrgv/gesetz/01012026-gemeindeordnung-fuer-das-land-nordrhein-westfalen-bekanntmachung-der/" },
};

// Unterschriften für ein Bürgerbegehren (§ 26 Abs. 4 GO NRW): Prozent und Zahl der Kommunalwahlberechtigten laut
// Bekanntmachung der Stadt Köln vom 26.02.2026 (Stand Kommunalwahl 14.09.2025), für ganz Köln und je Stadtbezirk
export const QUORUM = { Köln: [3, 24283], Innenstadt: [5, 5225], Rodenkirchen: [5, 4261], Lindenthal: [5, 6148],
  Ehrenfeld: [5, 4161], Nippes: [5, 4394], Chorweiler: [6, 3411], Porz: [5, 4171], Kalk: [5, 4023], Mülheim: [5, 5250] };

const ZAHL = new Intl.NumberFormat("de-DE");
const TAG = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Berlin" });
const tag = (iso) => TAG.format(new Date(iso + "T12:00:00Z"));
const when = (m) => `${tag(m.date)}${m.time ? `, ${esc(m.time)} Uhr` : ""}`;
const ext = (k) => { const q = QUELLEN[k]; return `<a href="${q.url}" target="_blank" rel="noopener">${esc(q.label)}<span class="visually-hidden"> (${esc(q.wo)}, neuer Tab)</span></a>`; };
const AUSSCHUSS = /Anregungen und Beschwerden/i;
// Rat in den Schreibweisen, die site/timeline.js (GREMIUM_ALIAS) kennt; welche die Kölner API liefert, ist bis zum
// ersten Vollabruf offen (TECHNIK.md, „Mitmachen in Köln“)
const RAT = new Set(["Rat", "Rat der Stadt Köln", "Stadtrat"]);

// nächste Sitzung (nicht abgesagt, ab heute), die `passt`
function naechste(meetings, heute, passt) {
  return (meetings || []).filter((m) => m && m.date >= heute && !m.cancelled && passt(m.gremium || ""))
    .sort((a, b) => (a.date + (a.time || "")).localeCompare(b.date + (b.time || "")))[0] || null;
}

function sitzungen(bz, o) {
  const row = (m, text) => `<li><span class="bt-when">${when(m)}</span><span>${text}${href(m.web)
    ? ` · <a href="${href(m.web)}" target="_blank" rel="noopener">Tagesordnung<span class="visually-hidden"> (Ratsinformationssystem der Stadt Köln, neuer Tab)</span></a>`
    : " · Tagesordnung noch nicht veröffentlicht"}</span></li>`;
  const kopf = `<h3 id="bt-next-h">${bz ? `Nächste Sitzungen für den Stadtbezirk ${esc(bz)}` : "Nächste Sitzungen"}</h3>`;
  if (!o.termine) {
    return `<section class="bt-next" aria-labelledby="bt-next-h">${kopf}<p class="hint">Die Sitzungstermine erscheinen hier, sobald die Ratsvorlagen im Ratsatlas vorliegen.</p></section>`;
  }
  const bv = bz ? naechste(o.meetings, o.heute, (g) => o.bvBezirk(g) === bz) : null;
  const rat = naechste(o.meetings, o.heute, (g) => RAT.has(g));
  const aab = naechste(o.meetings, o.heute, (g) => AUSSCHUSS.test(g));
  const items = [
    bv ? row(bv, `${esc(bv.gremium)}; die Sitzung beginnt mit der Einwohnerfragestunde`) : "",
    rat ? row(rat, "Rat der Stadt Köln; Ratssitzungen überträgt die Stadt auch live im Internet") : "",
    aab ? row(aab, esc(aab.gremium)) : "",
  ].filter(Boolean);
  const hinweis = !bz ? '<p class="hint">Wählen Sie oben Ihren Stadtbezirk, dann steht hier auch die nächste Sitzung Ihrer Bezirksvertretung.</p>'
    : bv ? "" : `<p class="hint">Für die Bezirksvertretung ${esc(bz)} ist im Sitzungskalender noch keine kommende Sitzung eingetragen.</p>`;
  return `<section class="bt-next" aria-labelledby="bt-next-h">${kopf}
    ${items.length ? `<ul class="bt-dates">${items.join("")}</ul>` : '<p class="hint">Im Sitzungskalender ist noch keine kommende Sitzung eingetragen.</p>'}
    ${hinweis}<p class="hint">Termine laut Sitzungskalender der Stadt (OParl-Schnittstelle); maßgeblich ist die Einladung im Ratsinformationssystem.</p>
    <p class="bt-actions"><button type="button" class="btn btn-soft" id="bt-termine">Alle kommenden Sitzungen</button></p></section>`;
}

// Die Seite der Stadt zur Einwohnerfragestunde beschreibt noch die Geschäftsordnung vom 18.06.2020 (Antwort in der Regel
// mündlich in der Sitzung, 30 Minuten; am 13. und 14.11.2026 geprüft); die Karte folgt der Fassung vom 19.03.2026.
// Der Hinweis steht direkt über dem Link, damit der Unterschied dort sichtbar ist, wo man der Seite folgt.
const FRAGESTUNDE_HINWEIS = `<p class="hint bt-abweichung">Hinweis: Die Seite der Stadt zur Einwohnerfragestunde beschreibt noch die Geschäftsordnung von 2020; danach wird in der Regel mündlich in der Sitzung geantwortet. Maßgeblich ist die Geschäftsordnung vom 19.03.2026, nach der die Verwaltung schriftlich antwortet (Stand der Prüfung: 14.11.2026).</p>`;

const karte = (titel, absaetze, grundlage, links, extra = "") => `<article class="bt-card"><h4>${titel}</h4>${absaetze.map((p) => `<p>${p}</p>`).join("")}
  ${extra}<p class="hint">Grundlage: ${grundlage}${links.length ? ` · ${links.map(ext).join(" · ")}` : ""}</p></article>`;

function quorumTabelle(bz) {
  const zeilen = BEZIRKE.map((b) => `<tr${b === bz ? ' class="bt-hier"' : ""}><th scope="row">${esc(b)}</th><td>${QUORUM[b][0]} %</td><td>${ZAHL.format(QUORUM[b][1])}</td></tr>`).join("");
  return `<details class="bt-quorum"><summary>Unterschriften je Stadtbezirk</summary><table><caption class="visually-hidden">Unterschriften für ein Bürgerbegehren je Stadtbezirk</caption>
    <thead><tr><th scope="col">Stadtbezirk</th><th scope="col">Anteil</th><th scope="col">Unterschriften</th></tr></thead><tbody>${zeilen}</tbody></table></details>`;
}

function wege(bz, o) {
  const [kp, kn] = QUORUM.Köln;
  const bezirkQuorum = bz ? ` Im Stadtbezirk ${esc(bz)} sind es ${QUORUM[bz][0]} Prozent, also ${ZAHL.format(QUORUM[bz][1])} Unterschriften.` : "";
  const karten = [
    karte("Zuhören und zuschauen", [
      "Die Sitzungen des Rates sind öffentlich; für die Ausschüsse und die Bezirksvertretungen gilt das entsprechend. Sie können als Zuhörerin oder Zuhörer dabei sein. Einzelne Punkte werden nichtöffentlich beraten, etwa Personal-, Grundstücks- und Vergabeangelegenheiten.",
      "Ratssitzungen überträgt die Stadt live im Internet.",
      o.termine ? "Die Termine stehen im Ratsatlas unter „Kommende Sitzungen“, auch als Kalenderdatei; der Link „Tagesordnung“ führt ins Ratsinformationssystem der Stadt."
        : "Die Termine erscheinen im Ratsatlas unter „Kommende Sitzungen“, auch als Kalenderdatei, sobald die Ratsvorlagen vorliegen.",
    ], "§ 48 Abs. 2, § 36 Abs. 5 und § 58 Abs. 2 GO NRW; § 2 Abs. 4 der Geschäftsordnung", ["ratLive", "go"]),
    karte("Eine Frage in der Einwohnerfragestunde stellen", [
      "Jede Sitzung einer Bezirksvertretung beginnt mit der Einwohnerfragestunde. Wer im Stadtbezirk wohnt, kann dort der Verwaltung eine Frage zu einer Angelegenheit des Stadtbezirks stellen: eine Frage mit höchstens fünf Unterfragen je Sitzung.",
      "So geht es: Reichen Sie Ihre Frage schriftlich bei der Bezirksbürgermeisterin oder dem Bezirksbürgermeister ein, spätestens am fünften Arbeitstag vor der Sitzung bis 12 Uhr. Die Verwaltung antwortet schriftlich, nach der Geschäftsordnung möglichst innerhalb von vier Wochen.",
      "Nicht möglich sind Fragen zu Angelegenheiten, die nichtöffentlich beraten werden, Fragen, die schutzwürdige Interessen anderer berühren, und Fragen zu einem laufenden Verwaltungsverfahren, in dem Sie selbst Auskunft verlangen können. Fragen und Antworten stellt die Stadt ins Ratsinformationssystem.",
      `Rat und Hilfe gibt die Geschäftsstelle der Bezirksvertretung im Bürgeramt ${bz ? esc(bz) : "Ihres Stadtbezirks"}.`,
    ], "§ 39 der Geschäftsordnung", ["fragestunde", "gescho"], FRAGESTUNDE_HINWEIS),
    karte("Anregungen und Beschwerden an Rat oder Bezirksvertretung", [
      "Wenn Ihnen in Köln etwas am Herzen liegt oder Sie etwas stört, können Sie sich direkt an die Politik wenden: Wer seit mindestens drei Monaten in Köln wohnt, kann sich allein oder gemeinsam mit anderen mit einer Anregung oder Beschwerde an den Rat oder an eine Bezirksvertretung wenden.",
      "So geht es: Schreiben Sie Ihr Anliegen auf, per Brief oder E-Mail. Die Eingaben bearbeitet die Geschäftsstelle für Anregungen und Beschwerden an Rat und Bezirksvertretungen: Briefe gehen an Postfach 10 35 64, 50475 Köln, E-Mails an geschaeftsstelle-anregungen-beschwerden@stadt-koeln.de; die Geschäftsstelle selbst sitzt in der Ludwigstraße 8, 50667 Köln. Die Stadt bietet dazu auch ein Kontaktformular an.",
      "Wie es weitergeht: Zuerst nimmt die zuständige Fachverwaltung Stellung. Danach berät der Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden oder, wenn sie zuständig ist, die Bezirksvertretung. Sie werden zur Sitzung eingeladen und können Ihr Anliegen dort bis zu fünf Minuten lang erläutern. Der Ausschuss kann Empfehlungen aussprechen, etwa an den Rat oder die Verwaltung; die Bezirksvertretungen entscheiden in ihrem Bereich selbst. Über die Stellungnahme werden Sie unterrichtet.",
      "Nicht auf diesem Weg laufen Angelegenheiten mit einem eigenen Verfahren, etwa Dienstaufsichtsbeschwerden oder Fälle, in denen Sie ein Rechtsmittel wie einen Widerspruch einlegen können. Eingaben können nichtöffentlich beraten werden, wenn eine öffentliche Beratung schutzwürdige Interessen einzelner Personen gefährden könnte.",
    ], "§ 24 GO NRW; § 2 Abs. 4, § 34 Abs. 13 und § 38 Abs. 15 der Geschäftsordnung", ["ausschuss", "geschaeftsstelle", "formular"]),
    karte("Einwohnerantrag: eine Entscheidung verlangen", [
      "Mit einem Einwohnerantrag erreichen Sie, dass der Rat über ein bestimmtes Anliegen berät und entscheidet, wenn er dafür zuständig ist. Ist eine Bezirksvertretung zuständig, richtet sich der Antrag an sie.",
      "Antragsberechtigt sind Einwohnerinnen und Einwohner ab 14 Jahren, die seit mindestens drei Monaten mit Hauptwohnsitz in Köln leben. Nötig sind für den Rat mindestens 8.000 Unterschriften, für eine Bezirksvertretung mindestens 4 Prozent der Einwohnerinnen und Einwohner des Stadtbezirks.",
      "Der Antrag nennt ein bestimmtes Anliegen mit Begründung und bis zu drei Personen, die ihn vertreten; jede Unterschriftenliste enthält den vollen Wortlaut. Der Rat muss spätestens vier Monate nach Eingang entscheiden; die Vertreterinnen und Vertreter sollen den Antrag in der Sitzung erläutern können. Fragen beantwortet die Geschäftsstelle für Anregungen und Beschwerden.",
    ], "§ 25 GO NRW; § 15 der Hauptsatzung", ["einwohnerantrag", "go"]),
    karte("Bürgerbegehren und Bürgerentscheid: selbst entscheiden", [
      "Mit einem Bürgerbegehren beantragen Bürgerinnen und Bürger, dass sie anstelle des Rates selbst über eine Angelegenheit der Stadt entscheiden. Unterschreiben kann, wer in Köln bei Kommunalwahlen wählen darf.",
      `Für ganz Köln braucht es ${kp} Prozent der Kommunalwahlberechtigten, das sind ${ZAHL.format(kn)} Unterschriften. Geht es um eine Angelegenheit, für die eine Bezirksvertretung zuständig ist, ist ein Bürgerbegehren auch in einem Stadtbezirk möglich; dann unterschreiben nur die Wahlberechtigten, die dort wohnen.${bezirkQuorum} Die Zahlen hat die Stadt am 26.02.2026 bekannt gemacht.`,
      "Richtet sich das Begehren gegen einen Beschluss des Rates, gilt eine Frist: sechs Wochen nach der Bekanntmachung des Beschlusses, bei Beschlüssen ohne Bekanntmachung drei Monate nach der Sitzung. Nicht möglich ist ein Bürgerbegehren unter anderem zum Haushalt und zu Abgaben, zur inneren Organisation der Verwaltung und zu Bauleitplänen, außer zur Entscheidung, ob ein Planverfahren eingeleitet wird.",
      "Erklärt der Rat das Bürgerbegehren für zulässig und folgt ihm nicht, kommt es innerhalb von drei Monaten zum Bürgerentscheid.",
    ], "§ 26 GO NRW", ["go", "quorum"], quorumTabelle(bz)),
    karte("Bei Vorhaben der Stadt mitreden", [
      "Die Stadt beteiligt die Öffentlichkeit auch außerhalb der Sitzungen, etwa über ihr Beteiligungsportal „Meinung für Köln“. Auf ihrer Seite zur systematischen Öffentlichkeitsbeteiligung finden Sie das Portal, Ansprechpersonen im Büro für Öffentlichkeitsbeteiligung und den Weg, selbst eine Beteiligung anzuregen.",
    ], "Angaben der Stadt Köln", ["beteiligung"]),
  ];
  return `<section aria-labelledby="bt-wege-h"><h3 id="bt-wege-h">Wege, sich einzubringen</h3><div class="bt-cards">${karten.join("")}</div></section>`;
}

const DATENSCHUTZ = `<section aria-labelledby="bt-ds-h"><h3 id="bt-ds-h">Ihre Angaben und der Ratsatlas</h3>
  <p>Der Ratsatlas ist kein Angebot der Stadt Köln: Fragen, Eingaben und Anträge reichen Sie bei der Stadt ein, nicht hier. Von Eingaben zeigt der Ratsatlas nur, was die Stadt im Ratsinformationssystem öffentlich bereitstellt, und davon weniger: Anregungen und Beschwerden erscheinen auf der Karte höchstens auf Ebene der Straße oder des Stadtteils, nie an einem einzelnen Haus; Hausnummern in ihren Titeln blendet er aus, und als Einreichende nennt er nur „Einwohner:innen“, keine Namen. Möchten Sie eine Angabe zu Ihrer Person entfernt haben, schreiben Sie an contact@nozilla.de; mehr dazu unter <a href="datenschutz.html">Datenschutz</a>.</p></section>`;

// Inhalt der Fläche für Stadtbezirk `bz` ("" ohne Wahl); o: { termine, meetings, heute, bvBezirk }
export function inhalt(bz, o) {
  const b = BEZIRKE.includes(bz) ? bz : "";
  return `<p>Im Rat, in seinen Ausschüssen und in den neun Bezirksvertretungen wird über vieles entschieden, was Ihren Alltag in Köln betrifft. Sie können zuhören, Fragen stellen und eigene Anliegen einbringen. Hier finden Sie die Wege dazu, mit den Regeln aus Gemeindeordnung und Geschäftsordnung und mit Links zu den Seiten der Stadt Köln.</p>
    <label class="bt-pick">Ihr Stadtbezirk <select id="bt-bezirk"><option value=""${b ? "" : " selected"}>bitte wählen</option>${BEZIRKE.map((x) => `<option${x === b ? " selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
    <p><strong>Rat oder Bezirksvertretung?</strong> Der Rat ist für ganz Köln zuständig; er entscheidet zum Beispiel, ob öffentliche Einrichtungen errichtet, erweitert oder aufgelöst werden. Die Bezirksvertretung ${b ? esc(b) : "Ihres Stadtbezirks"} entscheidet, soweit nicht der Rat zuständig ist, über Angelegenheiten, deren Bedeutung nicht wesentlich über den Stadtbezirk hinausgeht, etwa über die Unterhaltung und Ausstattung der Schulen und öffentlichen Einrichtungen im Stadtbezirk, die Grünpflege oder die Betreuung und Unterstützung örtlicher Vereine (§ 41 Abs. 1, § 37 Abs. 1 GO NRW).</p>
    ${sitzungen(b, o)}${wege(b, o)}${DATENSCHUTZ}
    <p class="hint">Zusammengefasst aus der Gemeindeordnung NRW (Fassung ab 01.01.2026), der Geschäftsordnung des Rates und der Bezirksvertretungen der Stadt Köln (19.03.2026) und den verlinkten Seiten der Stadt Köln, Stand ${STAND}. Keine Rechtsauskunft; maßgeblich sind Gesetz, Geschäftsordnung und die Angaben der Stadt.</p>`;
}

let ctx, root, state = { bezirk: "" };

function render() {
  const body = root.querySelector("#bt-body");
  body.innerHTML = inhalt(state.bezirk, { termine: ctx.termine(), meetings: ctx.meetings(), heute: ctx.heute(), bvBezirk: ctx.bvBezirk });
  ctx.onState({ ...state });
}

export async function init(c) {
  ctx = c;
  root = document.getElementById("panel-mitmachen");
  const body = root.querySelector("#bt-body");
  body.addEventListener("change", (e) => { if (e.target.id === "bt-bezirk") { state.bezirk = e.target.value; render(); root.querySelector("#bt-bezirk").focus(); } });
  body.addEventListener("click", (e) => { if (e.target.closest("#bt-termine")) ctx.openTermine(); });
}
export function show(s) {
  if (s && (s.bezirk === "" || BEZIRKE.includes(s.bezirk))) state.bezirk = s.bezirk;
  render();
}
