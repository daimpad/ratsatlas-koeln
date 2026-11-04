// Seite haushalt/ (pipeline/haushaltsseite.py): Hineinzoomen in die Kacheln und Kacheln der Aufwandsarten einer
// Produktgruppe (Entscheidung 28.10.2026). Ohne Skript führen die Links auf die Ebenen (:target), Ebene 3 zeigt Balken.
// Beim Wechsel der Ebene wächst die angeklickte Kachel auf die ganze Fläche (heraus: umgekehrt); die Lage der Kachel
// kommt aus ihrem Rechteck im SVG der übergeordneten Ebene. Bei reduzierter Bewegung wechselt die Ebene ohne Animation.
(() => {
  const wahl = document.querySelector(".hh-wahl");
  if (!wahl) return;
  const NS = "http://www.w3.org/2000/svg";
  const FORMATE = { breit: [1000, 560], hoch: [340, 640] };   // wie haushaltsseite.FORMATE
  const KURZ = { 11: "Personal", 12: "Versorgung", 13: "Sachaufwand", 14: "Abschreibungen", 15: "Transfers", 16: "Sonstige" };
  const DUNKEL = new Set(["11", "14", "16"]);   // dunkle Flächen: weiße Schrift (Kontrast ≥ 4,5)
  const ruhig = matchMedia("(prefers-reduced-motion: reduce)");

  // Squarified Treemap wie haushaltsseite.squarify; Werte absteigend
  function squarify(werte, x, y, w, h) {
    const gesamt = werte.reduce((s, v) => s + v, 0);
    if (!werte.length || gesamt <= 0) return [];
    const flaechen = werte.map((v) => (v * w * h) / gesamt);
    const schlechteste = (reihe, seite) => {
      const s = reihe.reduce((a, b) => a + b, 0);
      return Math.max(...reihe.map((r) => Math.max((seite * seite * r) / (s * s), (s * s) / (seite * seite * r))));
    };
    const out = [];
    let i = 0;
    while (i < flaechen.length) {
      const seite = Math.min(w, h);
      const reihe = [flaechen[i]];
      let j = i + 1;
      while (j < flaechen.length && schlechteste([...reihe, flaechen[j]], seite) <= schlechteste(reihe, seite)) reihe.push(flaechen[j++]);
      const s = reihe.reduce((a, b) => a + b, 0);
      if (w >= h) {
        const breite = s / h;
        let yy = y;
        for (const r of reihe) { out.push([x, yy, breite, r / breite]); yy += r / breite; }
        x += breite; w -= breite;
      } else {
        const hoehe = s / w;
        let xx = x;
        for (const r of reihe) { out.push([xx, y, r / hoehe, hoehe]); xx += r / hoehe; }
        y += hoehe; h -= hoehe;
      }
      i = j;
    }
    return out;
  }

  // Beträge wie haushaltsseite._betrag: unter 0,05 Mio. € in Euro
  const betrag = (b) => Math.abs(b) < 50000
    ? `${b.toLocaleString("de-DE")} €`
    : `${(b / 1e6).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} Mio. €`;
  const prozent = (x) => `${x.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;

  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };

  // Beschriftung wie haushaltsseite._text: Name umbrochen mit Betrag, sonst Kurzname und Betrag, sonst nichts
  function zeilen(text, max) {
    const out = [];
    for (const wort of text.split(/\s+/)) {
      if (wort.length > max) return null;
      if (out.length && out[out.length - 1].length + 1 + wort.length <= max) out[out.length - 1] += ` ${wort}`;
      else out.push(wort);
    }
    return out;
  }
  function beschriften(g, x, y, rw, rh, name, kurz, text) {
    const gr = 15;
    const zeichen = Math.floor((rw - 12) / (0.62 * gr));
    const platz = Math.floor((rh - 8) / (gr * 1.2)) - 1;
    const z = rw >= 70 ? zeilen(name, zeichen) : null;
    if (z && z.length <= platz && text.length <= zeichen + 2) {
      z.forEach((t, k) => g.append(el("text", { x: Math.round(x + 6), y: Math.round(y + 6 + gr * (1 + 1.2 * k)), class: "hh-n" }, t)));
      g.append(el("text", { x: Math.round(x + 6), y: Math.round(y + 6 + gr * (1 + 1.2 * z.length)), class: "hh-b" }, text));
    } else if (rw >= 0.6 * 13 * Math.max(kurz.length, text.length) + 12 && rh >= 2.6 * 13) {
      g.append(el("text", { x: Math.round(x + 5), y: Math.round(y + 18), class: "hh-m" }, kurz));
      g.append(el("text", { x: Math.round(x + 5), y: Math.round(y + 5 + 13 * 2.2), class: "hh-k" }, text));
    } else if (rw >= Math.max(30, 0.62 * 13 * kurz.length + 8) && rh >= gr + 6) {
      g.append(el("text", { x: Math.round(x + 4), y: Math.round(y + 3 + gr), class: "hh-m" }, kurz));
    }
  }

  const titelAnsicht = (k) => {
    const radio = wahl.querySelectorAll(".hh-radio")[k];
    const label = radio && wahl.querySelector(`label[for="${radio.id}"]`);
    return label ? label.firstChild.textContent.trim() : "";
  };

  // Ebene 3: Kacheln der Aufwandsarten aus den Balken (data-b), je Ansicht für breite und schmale Bildschirme
  function kacheln(sektion) {
    if (!sektion || sektion.dataset.kacheln) return;
    sektion.dataset.kacheln = "1";
    const namen = {};
    sektion.querySelectorAll('tr[class^="hh-z"] > th').forEach((th) => { namen[th.parentElement.className.slice(4)] = th.textContent.trim(); });
    const wer = sektion.querySelector("h2").textContent.trim();
    sektion.querySelectorAll(".hh-balken:not(.hh-eb)").forEach((balken) => {
      const v = [...balken.classList].find((c) => /^hh-v\d$/.test(c));
      const teile = [...balken.querySelectorAll("i[data-b]")].map((i) => ({ z: i.className.slice(4), b: Number(i.dataset.b) }))
        .filter((t) => t.b > 0).sort((a, b) => b.b - a.b || a.z - b.z);
      if (!v || !teile.length) return;
      const ansicht = titelAnsicht(Number(v.slice(4)));
      const summe = teile.reduce((s, t) => s + t.b, 0);
      const figur = document.createElement("figure");
      figur.className = `hh-ansicht ${v} hh-kacheln`;
      for (const [format, [w, h]] of Object.entries(FORMATE)) {
        const svg = el("svg", { class: `hh-svg hh-${format} hh-arten`, viewBox: `0 0 ${w} ${h}`, role: "img",
          "aria-label": `${ansicht}: Aufwandsarten der ${wer}` });
        squarify(teile.map((t) => t.b), 0, 0, w, h).forEach(([x, y, rw, rh], k) => {
          const t = teile[k];
          const g = el("g", { class: DUNKEL.has(t.z) ? "hh-dunkel" : "" });
          g.append(el("title", {}, `${namen[t.z] || KURZ[t.z]}: ${betrag(t.b)}, ${prozent((100 * t.b) / summe)} (${ansicht})`));
          g.append(el("rect", { x: Math.round(x), y: Math.round(y), width: Math.round(rw), height: Math.round(rh), rx: 3, class: `hh-f${t.z}` }));
          beschriften(g, x, y, rw, rh, namen[t.z] || KURZ[t.z], KURZ[t.z] || t.z, betrag(t.b));
          svg.append(g);
        });
        figur.append(svg);
      }
      balken.before(figur);
    });
    sektion.classList.add("hh-mit-kacheln");
  }

  // Ebene aus dem Seitenlink: 1 Produktbereiche, 2 #zoom-XX, 3 #pg-1-XX-YY
  const ebene = (hash) => {
    const id = decodeURIComponent(hash.replace(/^#/, ""));
    let m = id.match(/^zoom-(\d\d)$/);
    if (m) return { stufe: 2, id, pb: m[1] };
    m = id.match(/^pg-1-(\d\d)-\d+$/);
    if (m && document.getElementById(id)) return { stufe: 3, id, pb: m[1] };
    return { stufe: 1, id: "" };
  };
  const wurzel = (e) => (e.stufe === 1 ? wahl.querySelector(".hh-haupt") : document.getElementById(e.id));
  const sichtbar = (w) => w && [...w.querySelectorAll(".hh-ansicht > svg.hh-svg")].find((s) => s.getBoundingClientRect().height > 0);
  // SVG derselben Ansicht und desselben Formats in einer anderen Ebene (auch wenn diese ausgeblendet ist)
  const gleiches = (w, svg) => {
    const v = [...svg.parentElement.classList].find((c) => /^hh-v\d$/.test(c));
    const f = svg.classList.contains("hh-hoch") ? "hh-hoch" : "hh-breit";
    return w && w.querySelector(`.hh-ansicht.${v} > svg.${f}`);
  };
  // Lage einer Kachel als Anteil der Fläche: [x, y, Breite, Höhe]
  const lage = (svg, ziel) => {
    const r = svg && svg.querySelector(`a[href="#${ziel}"] > rect`);
    if (!r) return null;
    const [, , W, H] = svg.getAttribute("viewBox").split(" ").map(Number);
    return [r.x.baseVal.value / W, r.y.baseVal.value / H, r.width.baseVal.value / W, r.height.baseVal.value / H];
  };
  let laufend = null;   // bei schnellem Wechsel endet die vorige Bewegung sofort
  function zoomen(svg, f, hinein) {
    if (laufend) laufend.cancel();
    if (!svg || !f || ruhig.matches || !svg.animate || f[2] <= 0 || f[3] <= 0) return;
    const { width: w, height: h } = svg.getBoundingClientRect();
    const [fx, fy, fw, fh] = f;
    const start = hinein
      ? `translate(${fx * w}px, ${fy * h}px) scale(${fw}, ${fh})`
      : `scale(${1 / fw}, ${1 / fh}) translate(${-fx * w}px, ${-fy * h}px)`;
    svg.classList.add("hh-zoom");
    const a = svg.animate([{ transform: start }, { transform: "none" }], { duration: 450, easing: "cubic-bezier(.2, .7, .2, 1)" });
    laufend = a;
    wahl.dataset.zoom = hinein ? "hinein" : "heraus";   // letzte Bewegung, für die Browser-Prüfung
    const fertig = () => { svg.classList.remove("hh-zoom"); if (laufend === a) laufend = null; };
    a.onfinish = fertig;
    a.oncancel = fertig;
  }

  let vorher = ebene(location.hash);
  if (vorher.stufe === 3) kacheln(document.getElementById(vorher.id));
  addEventListener("hashchange", () => {
    const jetzt = ebene(location.hash);
    const alt = vorher;
    vorher = jetzt;
    if (jetzt.stufe === 3) kacheln(document.getElementById(jetzt.id));
    const verwandt = alt.stufe === 1 || jetzt.stufe === 1 || alt.pb === jetzt.pb;
    if (!verwandt || alt.stufe === jetzt.stufe) return;
    if (jetzt.stufe === alt.stufe + 1) {   // hinein: die Kachel des neuen Abschnitts in der alten Ebene wächst
      const neu = sichtbar(wurzel(jetzt));
      zoomen(neu, neu && lage(gleiches(wurzel(alt), neu), jetzt.id), true);
    } else if (jetzt.stufe < alt.stufe) {   // heraus: die neue Ebene schrumpft auf die Kachel des alten Abschnitts zurück
      const neu = sichtbar(wurzel(jetzt));
      zoomen(neu, lage(neu, jetzt.stufe === 1 ? `zoom-${alt.pb}` : alt.id), false);
    }
  });
})();
