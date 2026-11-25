// Themenseiten (pipeline/prozessbild.py; Herkunft daimpad/ratsatlas-bonn @730d593, Kölner Anpassungen in
// inventur/themenseiten_port.tsv): breite Zeitleisten auf schmalen Bildschirmen zum Datenstand schieben, damit zuerst
// die kommenden Sitzungen sichtbar sind. Die Namen der Bahnen stehen in einer eigenen Spalte neben dem verschiebbaren
// Rahmen (.pb-bahnen) und bleiben beim Verschieben stehen; data-start bezieht sich daher nur auf das Bild im Rahmen.
// Ohne Skript bleibt die Zeitleiste links verschiebbar.
document.querySelectorAll(".pb-rahmen[data-start]").forEach((el) => {
  const start = Number(el.dataset.start);
  if (el.scrollWidth > el.clientWidth && start > 0) {
    el.scrollLeft = Math.max(0, start * el.scrollWidth - el.clientWidth / 3);
  }
});

// Zeitleiste zum Anklicken: ein Klick auf Punkt oder Sitzung öffnet das Detailfeld unter dem Bild (statt dem Link zu
// folgen), Schalter blenden Stränge aus, Bild und Liste heben sich gegenseitig hervor. Eine Sammelmarke (mehrere Punkte
// oder Sitzungen an nahen Tagen, pipeline/prozessbild.py lage) öffnet die Liste ihrer Einträge; „Angaben“ zeigt einen
// Eintrag, „Zurück zur Liste“ wieder die Liste. Liegt das Detailfeld nach dem Öffnen nicht im Fenster (schmale oder
// niedrige Fenster, 400 % Zoom), rollt die Seite es ins Bild; der Fokus bleibt auf dem Ziel im Bild. Auswahl und Schalter
// stehen im Seitenlink (#auswahl=<Drucksache, sitzung-n oder Kennung der Sammelmarke>&straenge=<Schlüssel,…>). Ohne
// Skript gelten die Links im Bild. Keine berechneten Fristen und keine Federführung (in Köln nicht in den Daten);
// Absagen nach export.absage.
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
  let innen = null;   // Kennung des Eintrags einer Sammelmarke, der gerade im Detailfeld steht (punkt-n, sitzung-n)
  const gruppen = daten.gruppen || {};
  const gruppeVon = (kennung) => ziele.find((z) => (gruppen[z.dataset.ziel] || []).includes(kennung)) || null;

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
    if (extern) {
      // externe Seiten im neuen Tab wie die übrigen Kölner Seiten, mit Hinweis für Screenreader
      a.target = "_blank";
      a.rel = "noopener";
      a.append(el("span", ` (${extern}, neuer Tab)`, "visually-hidden"));
    }
    return a;
  };
  const RIS = "Ratsinformationssystem der Stadt Köln";
  const zeile = (dl, name, wert, abgeleitet) => {
    if (!wert) return;
    dl.append(el("dt", name));
    const dd = el("dd", wert);
    if (abgeleitet) dd.append(" ", el("span", "abgeleitet", "pb-abgeleitet"));
    dl.append(dd);
  };

  // Sammelmarke: Liste der Einträge, je mit „Angaben“ (öffnet den Eintrag im Detailfeld)
  function sammlung(art, kennung) {
    const eintraege = gruppen[kennung];
    if (!eintraege) return null;
    const punkte = art === "punkte";
    const teile = { titel: `${eintraege.length} ${punkte ? "Beschlüsse und Anträge" : "Sitzungen"}`, ansage: "", knoten: [] };
    teile.ansage = `${teile.titel} an nahen Tagen`;
    const ol = el("ol", null, "pb-gruppe");
    for (const k of eintraege) {
      const [a, n] = k.split(/-(.*)/s);
      const li = el("li");
      if (a === "punkt") {
        const p = daten.punkte[n];
        if (!p) continue;
        li.append(el("span", String(p.nr), "pb-nr"), " ", el("strong", p.reference), ` ${p.name || ""} – ${p.stand || ""}`);
      } else {
        const s = daten.sitzungen[n];
        if (!s) continue;
        li.append(el("strong", s.gremium), `, ${datum(s.date)}${s.time ? `, ${s.time} Uhr` : ""}`
          + (s.hinweis === "verschoben" ? " (laut Sitzungsnamen verschoben)" : ""));
      }
      const b = el("button", "Angaben", "pb-knopf pb-knopf-leise pb-eintrag");
      b.type = "button";
      b.dataset.eintrag = k;
      b.setAttribute("aria-label", `Angaben zu ${a === "punkt" ? `Nr. ${daten.punkte[n].nr}` : daten.sitzungen[n].gremium}`);
      b.addEventListener("click", () => eintragZeigen(k));
      li.append(" ", b);
      ol.append(li);
    }
    teile.knoten.push(ol);
    const aktionen = el("p", null, "pb-aktionen");
    if (punkte) aktionen.append(link("#pb-liste", "Alle Beschlüsse und Anträge im Bild"));
    else aktionen.append(link(daten.kalender, "Kalender (.ics)"), link("#sitzungen", "Alle Termine"),
      link(daten.mitmachen, "Wege zum Mitwirken"));
    // zweiter Knopf zum Schließen am Ende der Liste: Bei großen Sammelmarken liegt das Bild sonst weit oberhalb
    // (Durchsicht vom 25.11.2026); der Fokus geht wie bei „Schließen“ zurück auf die Marke im Bild
    const zu = el("button", "Schließen, zurück zum Bild", "pb-knopf pb-knopf-leise pb-schliessen-unten");
    zu.type = "button";
    zu.addEventListener("click", () => schliessen(true));
    aktionen.append(zu);
    teile.knoten.push(aktionen);
    return teile;
  }

  function inhalt(art, n) {
    if (art === "punkte" || art === "sitzungen") return sammlung(art, `${art}-${n}`);
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
      zeile(dl, "Stand", p.stand);
      zeile(dl, "Strang", p.strang && `${p.strang} (${p.grund})`, true);
      teile.knoten.push(dl);
      teile.knoten.push(el("h4", "Beratungsfolge"));
      if (p.beratungen.length) {
        const ol = el("ol", null, "pb-folge");
        for (const b of p.beratungen) {
          const li = el("li");
          li.append(el("span", datum(b.date), "pb-folge-datum"), " ", el("strong", b.gremium), ": ");
          // Absage nach export.absage: „oparl“ (in der Schnittstelle abgesagt) oder „name“ (Hinweis im Sitzungsnamen)
          const absage = b.abgesagt === "name" ? "Sitzung laut Sitzungsnamen abgesagt" : b.abgesagt ? "Sitzung abgesagt" : "";
          if (b.result) li.append(el("q", b.result), absage ? ` (${absage})` : "");
          else li.append(absage || "noch ohne Ergebnis");
          ol.append(li);
        }
        teile.knoten.push(ol, el("p", "Ergebnisse wörtlich aus dem Ratsinformationssystem.", "pb-hinweis"));
      } else {
        teile.knoten.push(el("p", "Keine Beratungsfolge eingetragen.", "pb-hinweis"));
      }
      if (p.karte) aktionen.append(link(p.karte, "Vorgang auf der Karte"));
      if (p.web) aktionen.append(link(p.web, "Original im Ratsinformationssystem", RIS));
    } else if (art === "sitzung") {
      const s = daten.sitzungen[n];
      if (!s) return null;
      teile.titel = s.gremium;
      teile.ansage = `${s.gremium}, ${datum(s.date)}, öffentliche Sitzung`;
      zeile(dl, "Datum", datum(s.date) + (s.time ? `, ${s.time} Uhr` : ""));
      if (s.hinweis === "verschoben") zeile(dl, "Hinweis", "laut Sitzungsnamen verschoben");
      zeile(dl, "Tagesordnung", s.web ? "veröffentlicht" : "noch nicht veröffentlicht");
      teile.knoten.push(dl);
      if (s.web) aktionen.append(link(s.web, "Tagesordnung", RIS));
      aktionen.append(link(daten.kalender, "Kalender (.ics)"), link("#sitzungen", "Alle Termine"),
        link(daten.mitmachen, "Wege zum Mitwirken"));
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
    const kennung = innen || (aktiv && aktiv.dataset.ziel);
    if (kennung) h.set("auswahl", kennung.startsWith("punkt-") ? daten.punkte[kennung.slice(6)].reference : kennung);
    const aus = schalter.filter((b) => b.getAttribute("aria-pressed") === "false");
    if (aus.length) h.set("straenge", schalter.filter((b) => b.getAttribute("aria-pressed") === "true")
      .map((b) => b.dataset.strang).join(","));
    const neu = h.toString().replace(/%2C/g, ",");
    history.replaceState(null, "", neu ? `#${neu}` : location.pathname + location.search);
  }

  const imFenster = (e) => { const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; };

  // ziel: Element im Bild; eintrag: Kennung eines Eintrags der Sammelmarke ziel (punkt-n, sitzung-n) oder null
  function zeigen(ziel, { fokus = false, schreiben = true, eintrag = null } = {}) {
    const [art, n] = (eintrag || ziel.dataset.ziel).split(/-(.*)/s);
    const t = inhalt(art, n);
    if (!t) return;
    if (aktiv) aktiv.classList.remove("pb-aktiv");
    aktiv = ziel;
    innen = eintrag;
    ziel.classList.add("pb-aktiv");
    feld.replaceChildren();
    const kopf = el("div", null, "pb-detail-kopf");
    const h = el("h3", t.titel);
    h.id = "pb-detail-titel";
    h.tabIndex = -1;
    const zu = el("button", "Schließen", "pb-schliessen");
    zu.type = "button";
    zu.setAttribute("aria-label", "Detailfeld schließen");
    zu.addEventListener("click", () => schliessen(true));
    kopf.append(h, zu);
    feld.append(kopf, ...t.knoten);
    if (eintrag) {
      const zurueck = el("button", "Zurück zur Liste", "pb-knopf pb-knopf-leise pb-zurueck");
      zurueck.type = "button";
      zurueck.addEventListener("click", () => {
        const war = innen;
        zeigen(aktiv);
        const b = feld.querySelector(`button[data-eintrag="${war}"]`);
        if (b) b.focus();
      });
      feld.append(el("p", null, "pb-aktionen"));
      feld.lastChild.append(zurueck);
    }
    feld.hidden = false;
    ansage.textContent = `Ausgewählt: ${t.ansage}. Angaben unter dem Bild.`;
    if (fokus) {
      ziel.scrollIntoView({ block: "nearest", inline: "center" });
      feld.scrollIntoView({ block: "nearest" });
    } else if (!imFenster(feld)) {
      feld.scrollIntoView({ block: "nearest" });
    }
    if (schreiben) hashSchreiben();
  }

  // Eintrag einer Sammelmarke im Detailfeld; der Fokus geht auf die Überschrift des Felds (die Schaltfläche verschwindet)
  function eintragZeigen(kennung) {
    if (!aktiv) return;
    zeigen(aktiv, { eintrag: kennung });
    document.getElementById("pb-detail-titel").focus();
  }

  function schliessen(fokusZurueck) {
    if (!aktiv) return;
    const war = aktiv;
    aktiv.classList.remove("pb-aktiv");
    aktiv = null;
    innen = null;
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
      // Sammelmarke: abgeblendet, wenn keiner ihrer Stränge eingeschaltet ist
      else if (e.dataset.straenge) e.classList.toggle("pb-gedimmt", !e.dataset.straenge.split(" ").some((k) => an.has(k)));
    }
    if (schreiben) hashSchreiben();
  }

  // Ziel im Bild und Zeile der Liste gegenseitig; ein Punkt in einer Sammelmarke hebt die Sammelmarke hervor
  function hervorheben(kennung, an) {
    for (const e of [...ziele, ...zeilen]) {
      if (e.dataset.ziel === kennung || (gruppen[e.dataset.ziel] || []).includes(kennung)
        || (gruppen[kennung] || []).includes(e.dataset.ziel)) e.classList.toggle("pb-hell", an);
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
    else if (gruppeVon(kennung)) zeigen(gruppeVon(kennung), { fokus: true, schreiben: false, eintrag: kennung });
  }

  for (const z of ziele) {
    z.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (aktiv === z && !innen) schliessen(false);
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
