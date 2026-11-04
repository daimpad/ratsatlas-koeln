// Mitwirkung: Einflussregeln des Soll-Modells (einfluss_regeln aus „Bonn entscheidet“, MIT; Anrede „Sie“ laut
// data/soll/ergaenzungen.json) für eine Vorlage auswerten. Fristen hängen vom Tag ab, daher im Browser.
// Genutzt von site/app.js (dynamischer Import) und site/chat/tools.js; Tests: tests/js/mitwirken.test.mjs.
// Übertragung auf unsere Daten (abgeleitet, Einordnung, keine Rechtsauskunft):
// - status: Stand der Vorlage (process.py) und Ergebnisse der Beratungen → offen, vertagt, abgeschlossen, unklar;
//   abschluss nach den Ergebnisgruppen des Originals (gruppe in einordnung.py); Kenntnisnahme oder Erledigung
//   (ohne ausstehende Entscheidung), Mitteilung ohne Termin und Genehmigung durch den Rat schließen den Vorgang;
//   ein offener Vorgang ohne Termin
//   und ohne Datum in den letzten 12 Monaten gilt als „unklar“ (eigene Festlegung: meist fehlt die Verknüpfung)
// - termin: nächste Beratung dieser Vorlage mit Datum ab heute ohne Ergebnis (Sitzung über OParl-Lite verknüpft)
// - ebene: „bezirk“, wenn nur Bezirksvertretungen beraten, sonst „stadt“; ohne Beratung keine Ebene
// - Ziel eines Bürgerantrags: Bezirksvertretung (Ebene Bezirk) oder Ausschuss für Beteiligung der Bürgerinnen
//   und Bürger; nächste Sitzung laut Sitzungskalender, deren Frist (21 Tage vorher) noch nicht verstrichen ist

export function gruppe(ergebnis) {
  const e = ergebnis || "";
  if (/vertagt|nicht aufgenommen|nicht behandelt/i.test(e)) return "vertagt";
  if (/abgelehnt/i.test(e)) return "abgelehnt";
  if (/beschlossen|zugestimmt/i.test(e)) return "beschlossen";
  if (/Kenntnis/i.test(e)) return "zur Kenntnis";
  if (/erledigt|zurückgezogen|beantwortet/i.test(e)) return "erledigt";
  return "offen";
}

const isBerat = (s) => s.typ === "beratung" || s.typ === "entscheidung";
export const gremienart = (name) => (/^Bezirksvertretung\b/.test(name || "") ? "Bezirksvertretungen" : name === "Rat" ? "Rat" : "Ratsgremien");
export const deDate = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "");
export function addDays(iso, n) {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

// Kontext einer Vorlage: Status, Abschluss, Verfahren, Ebene, Bezirk, nächster Termin
export function kontext(p, today) {
  const berat = (p.steps || []).filter(isBerat);
  const termin = berat.filter((s) => s.date && s.date >= today && !s.result).sort((a, b) => a.date.localeCompare(b.date))[0];
  const results = berat.filter((s) => s.result).sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  const last = results.length ? gruppe(results[results.length - 1].result) : null;
  const vid = p.soll?.verfahren || null;
  let status = "unklar", abschluss = null;
  if (p.stand === "entschieden") {
    const dec = results.filter((s) => s.typ === "entscheidung");
    const g = gruppe((dec.length ? dec[dec.length - 1] : results[results.length - 1])?.result);
    status = "abgeschlossen";
    abschluss = g === "offen" || g === "vertagt" ? null : g;
  } else if (p.stand === "beraten, ohne Entscheidung") {
    if (last === "vertagt") status = "vertagt";
  } else if (p.stand === "in Beratung" || p.stand === "offen") {
    status = last === "vertagt" ? "vertagt" : "offen";
  }
  // wie im Original (status_2026): Kenntnisnahme oder Erledigung schließt den Vorgang, ebenso eine Mitteilung ohne
  // weiteren Termin; die Genehmigung einer Dringlichkeits- oder Eilentscheidung durch den Rat ist ein Beschluss
  if (status !== "abgeschlossen" && !termin) {
    const genehmigt = results.find((s) => /Genehmigung/i.test(s.role || "") && gruppe(s.result) === "beschlossen");
    if (genehmigt) { status = "abgeschlossen"; abschluss = "beschlossen"; }
    // außer eine entscheidende Beratung steht noch aus (im Original: verbindliche Beratung ohne Sitzung)
    else if ((last === "zur Kenntnis" || last === "erledigt") && !berat.some((s) => s.typ === "entscheidung" && !s.result)) { status = "abgeschlossen"; abschluss = last; }
    else if (vid === "mitteilung") { status = "abgeschlossen"; abschluss = "zur Kenntnis"; }
  }
  const dates = [p.date, ...berat.map((s) => s.date)].filter(Boolean).sort();
  if ((status === "offen" || status === "vertagt") && !termin && dates.length && dates[dates.length - 1] < addDays(today, -365)) status = "unklar";
  // wie im Original: eine spätere Beratung hält den Vorgang offen; ein Beschluss geht der Kenntnisnahme vor
  if (status === "abgeschlossen" && termin) { status = "offen"; abschluss = null; }
  if ((abschluss === "zur Kenntnis" || abschluss === "erledigt")
    && results.some((s) => s.typ === "entscheidung" && gruppe(s.result) === "beschlossen")) abschluss = "beschlossen";
  const names = [...new Set(berat.map((s) => s.label).filter(Boolean))];
  const bvs = names.filter((n) => gremienart(n) === "Bezirksvertretungen");
  const ebene = !names.length ? null : bvs.length === names.length ? "bezirk" : "stadt";
  const bezirk = bvs.length === 1 ? bvs[0].replace(/^Bezirksvertretung\s+/, "") : null;
  return { status, abschluss, verfahren: vid, ebene, bezirk,
    termin: termin ? { datum: termin.date, gremium: termin.label, gremienart: gremienart(termin.label) } : null };
}

// Regeln auswerten; meetings: Sitzungskalender (zeit.json). Ergebnis je Regel: Text, Frist, Fristdatum, Links.
export function mitwirken(p, soll, meetings, today) {
  if (!soll?.mitwirken || !p.soll?.verfahren) return { kontext: null, regeln: [] };  // ohne Soll keine Regeln
  const ctx = kontext(p, today);
  const t = ctx.termin;
  const out = [];
  for (const r of soll.mitwirken) {
    const w = r.wenn;
    if (("status" in w && !w.status.includes(ctx.status))
      || ("verfahren" in w && !w.verfahren.includes(ctx.verfahren))
      || (w.nicht_verfahren || []).includes(ctx.verfahren)
      || ("ebene" in w && !w.ebene.includes(ctx.ebene))
      || (w.nicht_ebene || []).includes(ctx.ebene)
      || ("termin" in w && Boolean(t) !== w.termin)
      || ("termin_gremienart" in w && (!t || !w.termin_gremienart.includes(t.gremienart)))
      || ("abschluss" in w && !w.abschluss.includes(ctx.abschluss))) continue;
    const vals = t ? { gremium: t.gremium, datum: deDate(t.datum) } : {};
    let bezug = null, sitzung = null;
    if (r.bezug === "termin" && t) {
      bezug = t.datum;
      sitzung = (meetings || []).find((m) => m.gremium === t.gremium && m.date === t.datum) || null;
    } else if (r.bezug === "buergerantrag_ziel") {
      const ziel = ctx.ebene === "bezirk" && ctx.bezirk ? soll.buergerantrag_ziel.bezirk.replace("{bezirk}", ctx.bezirk) : soll.buergerantrag_ziel.stadt;
      const after = addDays(today, -(r.tage || 0));
      const mt = (meetings || []).filter((m) => m.gremium === ziel && !m.cancelled && m.date >= after).sort((a, b) => a.date.localeCompare(b.date))[0];
      if (!mt) continue;
      vals.ziel = `${gremienart(ziel) === "Bezirksvertretungen" ? "die" : "der"} ${ziel}`;
      vals.ziel_datum = deDate(mt.date);
      bezug = mt.date;
      sitzung = mt;
    }
    const missing = [...r.was.matchAll(/\{(\w+)\}/g)].some((m) => !(m[1] in vals));
    if (missing) continue;
    const text = r.was.replace(/\{(\w+)\}/g, (_, k) => vals[k]);
    let frist = r.frist, frist_datum = null;
    if (bezug) {
      frist_datum = addDays(bezug, r.tage || 0);
      frist += r.tage ? `, also bis ${deDate(frist_datum)}` : ` (${deDate(frist_datum)})`;
    }
    out.push({ id: r.id, text, frist, frist_datum, verstrichen: Boolean(frist_datum && frist_datum < today),
      beleg: r.beleg || null, links: r.links || [], sitzung: sitzung ? { gremium: sitzung.gremium, datum: sitzung.date, web: sitzung.web || null } : null });
  }
  return { kontext: ctx, regeln: out };
}
