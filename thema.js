// Themenseiten (pipeline/prozessbild.py): breite Zeitleisten auf schmalen Bildschirmen zum Datenstand schieben,
// damit zuerst die kommenden Sitzungen sichtbar sind. Ohne Skript bleibt die Zeitleiste links verschiebbar.
document.querySelectorAll(".pb-rahmen[data-start]").forEach((el) => {
  const start = Number(el.dataset.start);
  if (el.scrollWidth > el.clientWidth && start > 0) {
    el.scrollLeft = Math.max(0, start * el.scrollWidth - el.clientWidth / 3);
  }
});

// Prozessbild zum Anklicken: ein Klick auf Punkt, Sitzung oder Planbalken öffnet das Detailfeld unter dem Bild
// (statt dem Link zu folgen), Schalter blenden Stränge aus, Bild und Liste heben sich gegenseitig hervor.
// Auswahl und Schalter stehen im Seitenlink (#auswahl=261285&straenge=haushalt,buehnen). Ohne Skript gelten
// die Links im Bild.
(() => {
  const quelle = document.getElementById("pb-daten");
  const feld = document.getElementById("pb-detail");
  const ansage = document.getElementById("pb-ansage");
  const svg = document.querySelector(".pb-svg");
  if (!quelle || !feld || !svg) return;
  let daten;
  try {
    daten = JSON.parse(quelle.textContent);
  } catch (e) {
    return;
  }
  const filter = document.querySelector(".pb-filter");
  const schalter = filter ? [...filter.querySelectorAll(".pb-schalter")] : [];
  const ziele = [...svg.querySelectorAll("a.pb-ziel[data-ziel]")];
  const zeilen = [...document.querySelectorAll(".pb-liste li[data-ziel]")];
  let aktiv = null;

  const datum = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "–");

  // kleine Bausteine; Inhalte nur als Text, nie als HTML
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const link = (href, text, extern) => {
    // nur Adressen dieser Seite und https (keine anderen Schemata aus den Daten)
    if (!/^(https:\/\/|\.\.\/|\.\/|#|\?)/.test(href || "")) return document.createTextNode("");
    const a = el("a", text, "pb-knopf pb-knopf-leise");
    a.href = href;
    if (extern) a.rel = "noopener";
    return a;
  };
  const zeile = (dl, name, wert, abgeleitet) => {
    if (!wert) return;
    dl.append(el("dt", name));
    const dd = el("dd", wert);
    if (abgeleitet) dd.append(" ", el("span", "abgeleitet", "pb-abgeleitet"));
    dl.append(dd);
  };

  function inhalt(art, n) {
    const teile = { titel: "", ansage: "", knoten: [] };
    const dl = el("dl", null, "pb-angaben");
    const aktionen = el("p", null, "pb-aktionen");
    if (art === "punkt") {
      const p = daten.punkte[n];
      if (!p) return null;
      teile.titel = `${p.nr}: ${p.reference}`;
      teile.ansage = `${p.reference} ${p.name || ""}, ${p.stand}`;
      teile.knoten.push(el("p", p.name || "", "pb-name-gross"));
      zeile(dl, "Art", p.paper_type);
      zeile(dl, "Federführend", p.amt);
      zeile(dl, "Stand", p.stand);
      zeile(dl, "Strang", p.strang && `${p.strang} (${p.grund})`, true);
      teile.knoten.push(dl);
      teile.knoten.push(el("h4", "Beratungsfolge"));
      if (p.beratungen.length) {
        const ol = el("ol", null, "pb-folge");
        for (const b of p.beratungen) {
          const li = el("li");
          li.append(el("span", datum(b.date), "pb-folge-datum"), " ", el("strong", b.gremium), ": ");
          li.append(b.cancelled ? "abgesetzt" : b.result ? el("q", b.result) : "noch ohne Ergebnis");
          ol.append(li);
        }
        teile.knoten.push(ol, el("p", "Ergebnisse wörtlich aus dem Ratsinformationssystem.", "pb-hinweis"));
      } else {
        teile.knoten.push(el("p", "Keine Beratungsfolge eingetragen.", "pb-hinweis"));
      }
      if (p.karte) aktionen.append(link(p.karte, "Vorgang auf der Karte"));
      if (p.web) aktionen.append(link(p.web, "Original im Ratsinformationssystem", true));
    } else if (art === "sitzung") {
      const s = daten.sitzungen[n];
      if (!s) return null;
      teile.titel = s.gremium;
      teile.ansage = `${s.gremium}, ${datum(s.date)}, öffentliche Sitzung`;
      zeile(dl, "Datum", datum(s.date) + (s.time ? `, ${s.time} Uhr` : ""));
      zeile(dl, "Frist für Anträge und Fragen",
        `${datum(s.frist)} (${s.frist >= daten.heute ? "noch offen" : "abgelaufen"}; 21 Tage vorher, berechnet)`, true);
      zeile(dl, "Tagesordnung", s.web ? "veröffentlicht" : "noch nicht veröffentlicht (erscheint etwa zwei Wochen vorher)");
      teile.knoten.push(dl);
      if (s.web) aktionen.append(link(s.web, "Tagesordnung", true));
      aktionen.append(link(daten.kalender, "Kalender (.ics)"), link("#sitzungen", "Alle Termine"),
        link(daten.mitmachen, "Wege und Fristen zum Mitwirken"));
    } else if (art === "phase") {
      const ph = daten.phasen[n];
      if (!ph) return null;
      teile.titel = ph.text;
      teile.ansage = `${ph.text}, ${datum(ph.von)} bis ${datum(ph.bis)}`;
      const tp = daten.terminplan;
      zeile(dl, "Zeitraum", `${datum(ph.von)} bis ${datum(ph.bis)}`);
      zeile(dl, "Grundlage", `geplant laut Terminplan${tp ? ` in Drucksache ${tp.reference}` : ""}`, true);
      if (ph.intern) zeile(dl, "Öffentlichkeit", "nicht öffentlich (Arbeit der Verwaltung)");
      teile.knoten.push(dl);
      if (tp && tp.karte) aktionen.append(link(tp.karte, `Terminplan ${tp.reference} auf der Karte`));
      if (tp && tp.web) aktionen.append(link(tp.web, "Original im Ratsinformationssystem", true));
    } else {
      return null;
    }
    teile.knoten.push(aktionen);
    return teile;
  }

  function hashLesen() {
    const h = new URLSearchParams(location.hash.slice(1));
    return { auswahl: h.get("auswahl"), straenge: h.has("straenge") ? h.get("straenge").split(",").filter(Boolean) : null };
  }

  function hashSchreiben() {
    const h = new URLSearchParams();
    if (aktiv) h.set("auswahl", aktiv.dataset.ziel.startsWith("punkt-")
      ? daten.punkte[aktiv.dataset.ziel.slice(6)].reference : aktiv.dataset.ziel);
    const aus = schalter.filter((b) => b.getAttribute("aria-pressed") === "false");
    if (aus.length) h.set("straenge", schalter.filter((b) => b.getAttribute("aria-pressed") === "true")
      .map((b) => b.dataset.strang).join(","));
    const neu = h.toString().replace(/%2C/g, ",");
    history.replaceState(null, "", neu ? `#${neu}` : location.pathname + location.search);
  }

  function zeigen(ziel, { fokus = false, schreiben = true } = {}) {
    const [art, n] = ziel.dataset.ziel.split(/-(.*)/s);
    const t = inhalt(art, n);
    if (!t) return;
    if (aktiv) aktiv.classList.remove("pb-aktiv");
    aktiv = ziel;
    ziel.classList.add("pb-aktiv");
    feld.replaceChildren();
    const kopf = el("div", null, "pb-detail-kopf");
    const h = el("h3", t.titel);
    h.id = "pb-detail-titel";
    const zu = el("button", "Schließen", "pb-schliessen");
    zu.type = "button";
    zu.setAttribute("aria-label", "Detailfeld schließen");
    zu.addEventListener("click", () => schliessen(true));
    kopf.append(h, zu);
    feld.append(kopf, ...t.knoten);
    feld.hidden = false;
    ansage.textContent = `Ausgewählt: ${t.ansage}. Angaben unter dem Bild.`;
    if (fokus) {
      ziel.scrollIntoView({ block: "nearest", inline: "center" });
      feld.scrollIntoView({ block: "nearest" });
    }
    if (schreiben) hashSchreiben();
  }

  function schliessen(fokusZurueck) {
    if (!aktiv) return;
    const war = aktiv;
    aktiv.classList.remove("pb-aktiv");
    aktiv = null;
    feld.hidden = true;
    feld.replaceChildren();
    ansage.textContent = "Detailfeld geschlossen.";
    hashSchreiben();
    if (fokusZurueck) war.focus();
  }

  function filtern(schreiben = true) {
    const an = new Set(schalter.filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.strang));
    for (const e of [...ziele, ...zeilen]) {
      if (e.dataset.strang) e.classList.toggle("pb-gedimmt", !an.has(e.dataset.strang));
    }
    if (schreiben) hashSchreiben();
  }

  function hervorheben(kennung, an) {
    for (const e of [...ziele, ...zeilen]) {
      if (e.dataset.ziel === kennung) e.classList.toggle("pb-hell", an);
    }
  }

  function anwenden() {
    const { auswahl, straenge } = hashLesen();
    if (straenge) {
      for (const b of schalter) b.setAttribute("aria-pressed", String(straenge.includes(b.dataset.strang)));
    }
    filtern(false);
    if (!auswahl) return;
    let kennung = auswahl;
    const p = Object.values(daten.punkte).find((x) => x.reference === auswahl);
    if (p) kennung = `punkt-${p.nr}`;
    const ziel = ziele.find((z) => z.dataset.ziel === kennung);
    if (ziel) zeigen(ziel, { fokus: true, schreiben: false });
  }

  for (const z of ziele) {
    z.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (aktiv === z) schliessen(false);
      else zeigen(z);
    });
    for (const [typ, an] of [["mouseenter", true], ["mouseleave", false], ["focus", true], ["blur", false]]) {
      z.addEventListener(typ, () => hervorheben(z.dataset.ziel, an));
    }
  }
  for (const li of zeilen) {
    li.addEventListener("mouseenter", () => hervorheben(li.dataset.ziel, true));
    li.addEventListener("mouseleave", () => hervorheben(li.dataset.ziel, false));
  }
  for (const b of schalter) {
    b.addEventListener("click", () => {
      b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
      filtern();
    });
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && aktiv) schliessen(true);
  });
  window.addEventListener("hashchange", anwenden);
  if (filter && schalter.length) filter.hidden = false;
  anwenden();
})();
