// Tour durch die Funktionen des Ratsatlas Köln (aus Bonn übernommen): hebt nacheinander Bedienelemente hervor (abgedunkelte Umgebung,
// pulsierender Rahmen, pulsierende Punkte an erwähnten Einzelheiten) und erklärt sie in einer Karte.
// Start über Schaltflächen mit data-tour (Fenster „Los geht's“, Dialog „Über“). Bedienung: Weiter/Zurück,
// Pfeiltasten, Esc beendet. Bei reduzierter Bewegung ohne Animation (style.css). Kein Inline-Skript (CSP).
(function () {
  "use strict";
  const MOBILE = matchMedia("(max-width: 900px)");
  const $ = (s) => document.querySelector(s);
  // Kartenvorschau ohne Ratsvorlagen (index.json meta.vorschau; Kennzeichen setzt app.js applyFunktionen): dort fehlen
  // Punkte, Zeitleiste, Termine, Schnellfilter und Auswertung, Suche und Liste bleiben leer; die Tour nennt, was folgt
  const VORSCHAU = () => document.documentElement.dataset.vorschau === "ja";
  const TELEFON_LEGENDEN = MOBILE.matches ? " Auf dem Telefon stehen die Legenden hinter „Karte“; „Ganz Köln ansehen“ ist das Symbol mit den vier Ecken." : "";
  const TELEFON_KARTE = MOBILE.matches ? " Auf dem Telefon liegen Ebenen, Legenden und Quellen zusammen hinter „Karte“." : "";
  // Freigaben (index.json meta.funktionen, config.ZUSATZTHEMEN): app.js blendet Elemente mit data-funktion aus und zeigt
  // den Schalter „Baustellen“ nur mit Baustellen. Sätze über abgeschaltete Funktionen entfallen, die Texte für Bonn
  // bleiben für die spätere Freigabe stehen (Runde 18; in Köln abgeschaltet: Baustellen, Haushalt, „Alle Wege im
  // Überblick“, Prozesse, Ratsassistent; Einfache Sprache seit 13.11.2026 freigegeben)
  const sichtbar = (sel) => { const el = document.querySelector(sel); return Boolean(el) && !el.hidden; };
  const AN = {
    baustellen: () => sichtbar(".map-bau"),
    einfache_sprache: () => sichtbar('[data-funktion="einfache_sprache"]'),
    haushalt: () => sichtbar('[data-funktion="haushalt"]'),
    mitmachen: () => sichtbar('[data-funktion="mitmachen"]'),
  };
  // Sätze von Zusatzmodulen, die nur mit Freigabe geladen werden: sichtbare Elemente mit data-tour-karte bzw.
  // data-tour-liste ergänzen die Schritte „Die Karte“ und „Die Vorlagen“ (ohne solche Elemente bleibt der Text gleich)
  const ZUSATZ = (art) => [...document.querySelectorAll(`[data-tour-${art}]`)].filter((el) => !el.hidden)
    .map((el) => " " + el.getAttribute(`data-tour-${art}`)).join("");
  // Flächen der Leiste, die sichtbar sind (Prozesse und Assistent nur mit Freigabe, die Zeitleiste nur mit Daten)
  const FLAECHEN = { "panel-list": "Vorlagen (die Liste aller Vorlagen im Gebiet)", "timeline-wrap": "Zeitleiste",
    "panel-detail": "Vorgang (die Einzelheiten einer Vorlage)", "panel-prozesse": "Prozesse", "panel-assistent": "Assistent" };
  const aufzaehlung = (a) => (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} und ${a[a.length - 1]}`);

  // Schritte: target (Selektor) oder rect (Fläche aus app.js), before (Flächen öffnen), menu (Mega-Menü),
  // beacons (Selektoren für pulsierende Punkte), clip (sichtbarer Ausschnitt), when (Schritt nur, wenn verfügbar),
  // vorschau (Text in der Kartenvorschau statt text; ohne Angabe gilt text)
  const STEPS = [
    { title: "Willkommen zur Tour",
      text: "Der Ratsatlas zeigt, womit sich Rat, Bezirksvertretungen und Ausschüsse der Stadt Köln befassen: wo (Karte), wann (Zeitleiste) und wer beteiligt ist (Dienststellen, Gremien, Fraktionen). Die Tour stellt die Funktionen der Reihe nach vor. Weiter mit der Pfeiltaste nach rechts, beenden mit Esc.",
      vorschau: "Der Ratsatlas zeigt, womit sich Rat, Bezirksvertretungen und Ausschüsse der Stadt Köln befassen: wo (Karte), wann (Zeitleiste) und wer beteiligt ist (Dienststellen, Gremien, Fraktionen). Die Vorschau enthält noch keine Ratsvorlagen; sie folgen, sobald der Abruf der Stadt Köln eingerichtet ist. Bis dahin zeigt die Karte Stadtteile, Kennzahlen und offene Daten. Die Tour stellt vor, was schon verfügbar ist. Weiter mit der Pfeiltaste nach rechts, beenden mit Esc." },
    { menu: "mega-suche", target: "#mega-suche", fallback: "#nav-search", beacons: ["#q"],
      title: "Suche in ganz Köln",
      text: "Ein Stichwort oder eine Vorlagennummer eingeben, etwa „Radweg“ oder „2250/2025“. Darunter stehen Schnellfilter nach Thema und Partei; die Treffer lassen sich in der Liste anzeigen.",
      vorschau: "Das Suchfeld ist für Vorlagen in ganz Köln gedacht: nach Stichwort oder Vorlagennummer, dazu Schnellfilter nach Thema und Partei. Die Vorschau enthält noch keine Ratsvorlagen; Suche und Schnellfilter folgen, sobald der Abruf der Stadt Köln eingerichtet ist." },
    { target: "#f-area",
      title: "Gebiet wählen",
      text: "Ein Stadtteil, ein ganzer Stadtbezirk oder Vorlagen ohne Ortsbezug je Jahr. Zu Beginn zeigt die Karte ganz Köln: erst einen Stadtbezirk anklicken, dann einen Stadtteil. Herangezoomt lassen sich Stadtteile direkt anklicken; „Ganz Köln ansehen“ führt zurück. In der obersten Legende unten links lassen sich die Flächen statt nach der Zahl der Vorlagen nach dem Anteil eines Themas färben, etwa Verkehr, oder nach Zahlen zum Gebiet wie Miete, Altersanteilen oder Hitze (abgeleitet, zur Einordnung). Ist ein Stadtteil gewählt, stehen diese Zahlen auch in der Liste neben denen des Stadtbezirks. Karte, Liste und Zeitleiste zeigen jeweils das gewählte Gebiet." + TELEFON_LEGENDEN,
      vorschau: "Ein Stadtteil oder ein ganzer Stadtbezirk. Zu Beginn zeigt die Karte ganz Köln: erst einen Stadtbezirk anklicken, dann einen Stadtteil. Herangezoomt lassen sich Stadtteile direkt anklicken; „Ganz Köln ansehen“ führt zurück. In der obersten Legende unten links lassen sich die Flächen nach Zahlen zum Gebiet färben, etwa Miete, Altersanteilen oder Hitze (abgeleitet, zur Einordnung). Ist ein Stadtteil gewählt, stehen diese Zahlen auch in der Liste neben denen des Stadtbezirks. Karte und Liste zeigen jeweils das gewählte Gebiet." + TELEFON_LEGENDEN },
    // Telefon: Blatt „Karte“ geschlossen lassen, sonst verdeckt die Karte der Tour es; dort pulsiert der Knopf „Karte“
    { before: (ui) => { if (MOBILE.matches) ui.panel("panel-detail", false); ui.mapMenu(!MOBILE.matches); }, rect: (ui) => ui.areaRect(), fallback: "#map",
      beacons: [".marker-cluster, path.leaflet-interactive", ".map-menu", ".map-color", ".map-plans", ".map-legend"],
      title: "Die Karte",
      text: () => "Jeder Punkt ist eine Vorlage mit Ortsbezug; Zahlen fassen nahe Punkte zusammen, ein Klick zoomt hinein. Die Farbe zeigt, wie sicher der Ort ist: grün gesichert (Koordinate oder Bebauungsplan der Stadt), braun erschlossen (Name im Titel), violett unsicher. „Farbe nach Thema“ färbt die Punkte stattdessen nach Thema; die Legende erklärt die Farben. „Bebauungspläne“ blendet die Geltungsbereiche der rechtskräftigen Pläne ein; ein Klick auf eine Fläche öffnet die Planchronik."
        + (AN.baustellen() ? " „Baustellen“ zeigt gemeldete Baustellen mit unverbindlichen Terminen." : "")
        + " „Überschwemmungsgebiete“ und „Bodenrichtwerte“ zeigen beim Hineinzoomen Flächen des Landes zur Einordnung (abgeleitet aufbereitet, verbindlich sind die Quellen)."
        + ZUSATZ("karte") + " „Farbige Karte“ schaltet den Hintergrund um. Alle diese Schaltflächen liegen unter „Ebenen“; die Zahl daneben nennt, wie viele eingeschaltet sind. Die Legenden unten links sind eingeklappt und öffnen sich mit einem Klick, darunter stehen Quellen, Lizenzen und Datenstand." + TELEFON_KARTE,
      vorschau: () => "Die Flächen zeigen Stadtbezirke und Stadtteile, gefärbt nach der Kennzahl in der obersten Legende. Punkte für Vorlagen mit Ortsbezug folgen mit den Ratsvorlagen. Unter „Ebenen“ lassen sich offene Daten zuschalten, etwa Bebauungspläne, Überschwemmungsgebiete, Bodenrichtwerte, Schutzgebiete, Schulen, Kitas oder Haltestellen – zur Einordnung abgeleitet aufbereitet, verbindlich sind die Quellen."
        + ZUSATZ("karte") + " Ebenen mit vielen Objekten erscheinen erst beim Hineinzoomen. „Farbige Karte“ schaltet den Hintergrund um. Die Zahl neben „Ebenen“ nennt, wie viele eingeschaltet sind. Die Legenden unten links sind eingeklappt und öffnen sich mit einem Klick, darunter stehen Quellen, Lizenzen und Datenstand." + TELEFON_KARTE },
    { before: (ui) => { ui.mapMenu(false); ui.panel("panel-list", true); }, target: "#panel-list", beacons: ["#f-text", "#more-filters > summary"],
      title: "Die Vorlagen",
      text: () => "Alle Vorlagen des Gebiets als Liste – gleichwertig zur Karte und mit der Tastatur bedienbar. Filter nach Stichwort, Vorlagenart, Stand, Thema und Partei; unter „Weitere Filter“ nach Amt, Gremium und Sicherheit der Ortsangabe."
        + ZUSATZ("liste") + (MOBILE.matches ? "" : " Die Breite lässt sich am Rand ziehen."),
      vorschau: () => "Hier stehen künftig alle Vorlagen des Gebiets als Liste – gleichwertig zur Karte, mit der Tastatur bedienbar und mit Filtern nach Stichwort, Vorlagenart, Stand, Thema und Partei. Die Vorschau enthält noch keine Ratsvorlagen; sie folgen, sobald der Abruf der Stadt Köln eingerichtet ist. Ist ein Stadtteil oder Stadtbezirk gewählt, stehen hier schon jetzt die Zahlen zum Gebiet."
        + ZUSATZ("liste") + (MOBILE.matches ? "" : " Die Breite lässt sich am Rand ziehen.") },
    { when: () => !document.querySelector('.toggle[data-panel="timeline-wrap"]').hidden,
      before: (ui) => ui.panel("timeline-wrap", true), target: "#timeline-wrap", beacons: [".tl-presets"],
      title: "Die Zeitleiste",
      text: "Die Balken zeigen, wie viele Vorlagen je Monat erschienen sind; dazu Sitzungen und Wahlperioden. Mit den Griffen oder einer Voreinstellung wählen Sie einen Zeitraum – Liste und Karte folgen." },
    // Vorschau ohne Ratsvorlagen: kein Beispiel; ohne diese Bedingung lüde ui.example() das Beispielgebiet und
    // wechselte das gewählte Gebiet, ohne einen Vorgang zu zeigen (Vorgang und Prozesslinie entfallen)
    { when: () => !VORSCHAU(),
      before: async (ui) => { await ui.example(); ui.panel("panel-detail", true); }, target: "#panel-detail", requires: "#detail .steps",
      beacons: ["#detail .links .btn-primary"],
      title: "Der Vorgang",
      text: "Ein Beispiel aus dem Gebiet: Vorlagennummer, Art, Datum, federführende Dienststelle, Stand und Themen – und der Link zum Original im Ratsinformationssystem. Maßgeblich ist immer das Original." },
    { when: () => !VORSCHAU(),
      before: (ui) => ui.panel("panel-prozesse", false), target: "#detail .steps", clip: "#detail", scroll: true,
      title: "Die Prozesslinie",
      text: "Die Stationen des Verfahrens: Einreichung, Beratungen in den Gremien mit Datum und Ergebnis, Folgevorlagen. Ergebnisse stehen wörtlich wie in der Quelle. Jede Station trägt ihren Evidenzstatus: belegt, abgeleitet, nicht öffentlich oder unklar." },
    // abgeschaltete Zusatzthemen (data-funktion, config.ZUSATZTHEMEN): Schritt entfällt; die Elemente stehen im Dokument,
    // die Prüfung auf ein fehlendes Element unten greift daher nicht
    { when: () => document.querySelector('.toggle[data-panel="panel-prozesse"]')?.hidden === false,
      before: (ui) => ui.panel("panel-prozesse", true), target: "#panel-prozesse", beacons: ["#tab-pz-gremien", "#tab-pz-aemter", ".pz-view"],
      title: "Prozesse: Wer entscheidet was?",
      text: "Alle Verfahrensarten – vom Bürgerantrag bis zum Bebauungsplan – mit ihren Schritten, Fristen und Rechtsgrundlagen und der Zahl der Vorgänge in Köln. Unter „Gremien“ stehen Rat, Ausschüsse, Bezirksvertretungen und Beiräte mit ihren Zuständigkeiten und nächsten Sitzungen, unter „Ämter“ die Verwaltung mit ihren Abteilungen und den Vorlagen, für die sie federführend ist. Mit „Schaubild“ und „Liste“ wechseln Sie die Darstellung." },
    // Vorschau ohne Ratsvorlagen: Menü „Auswertung“ ausgeblendet (app.js applyFunktionen), Schritt entfällt
    { when: () => document.querySelector('[data-mega="mega-auswertung"]')?.hidden === false,
      before: (ui) => ui.panel("panel-prozesse", false), menu: "mega-auswertung", target: "#mega-auswertung",
      title: "Auswertung",
      text: "Kennzahlen zum Gebiet nach Thema, Partei, Jahr und Stand; ein Klick auf einen Balken filtert die Liste. Die Verfahrenswege zeigen für ganz Köln, welche Gremien welche Vorlagenart beraten und wie Verfahren meist enden." },
    { menu: "mega-mitmachen", target: "#mega-mitmachen", beacons: ["#cta-termine", "#cta-mitmachen", "#cta-feed .btn"],
      title: "Mitmachen",
      text: () => "Kommende Sitzungen, auch als Kalenderdatei; unter „Informiert bleiben“ Feeds, die neue Vorlagen im Gebiet oder Änderungen an einem Vorgang melden; "
        + (AN.mitmachen() ? "der Weg zum Bürgerantrag nach § 24 GO NRW; „Alle Wege im Überblick“ zeigt je Stadtbezirk die nächsten Sitzungen, die Fristen und alle Wege, sich einzubringen; "
          : "der Weg, sich mit Anregungen und Beschwerden nach § 24 GO NRW selbst an den Rat zu wenden; ")
        + "und ein Hinweis, wenn etwas falsch zugeordnet ist.",
      vorschau: "Unter „Informiert bleiben“ stehen Feeds, die neue Vorlagen im gewählten Gebiet melden; sie füllen sich, sobald Ratsvorlagen vorliegen. Kommende Sitzungen und die Kalenderdatei folgen mit den Ratsvorlagen. Außerdem: der Weg, sich mit Anregungen und Beschwerden nach § 24 GO NRW selbst an den Rat zu wenden, und ein Hinweis, wenn etwas falsch zugeordnet oder unklar ist." },
    { menu: "mega-daten", target: "#mega-daten",
      title: "Offene Daten",
      text: "Alle Daten zum Herunterladen: das Datenpaket mit Prüfprotokollen, die verorteten Vorlagen als GeoJSON und eine Datensatzbeschreibung nach DCAT-AP. Quellen, Lizenzen und Datenstand stehen auf der Karte unter den Legenden.",
      vorschau: "Alle Daten zum Herunterladen: das Datenpaket enthält schon Gebiete, Kennzahlen je Stadtteil und die Kartenebenen; die Vorlagen und ihre Prüfprotokolle folgen mit den Ratsvorlagen. Quellen, Lizenzen und Datenstand stehen auf der Karte unter den Legenden." },
    { menu: "mega-verstehen", target: "#mega-verstehen",
      title: "Verstehen",
      text: () => `Hilfen zum Lesen der Karte: ${AN.einfache_sprache() ? "der Ratsatlas in Einfacher Sprache, " : ""}Begriffe wie Vorlage, Beratungsfolge oder ${AN.haushalt() ? "Zuschussbedarf" : "Stadtbezirk"} in einfachen Worten und wie verlässlich die Angaben sind. Diese Tour finden Sie hier wieder.`,
      vorschau: () => `Hilfen zum Lesen der Karte: ${AN.einfache_sprache() ? "der Ratsatlas in Einfacher Sprache, " : ""}Begriffe wie Vorlage, Beratungsfolge oder Stadtbezirk in einfachen Worten und wie verlässlich die Angaben sind. Diese Tour finden Sie hier wieder.` },
    { when: () => document.querySelector(".toggle-ai")?.hidden === false,
      target: ".toggle-ai",
      title: "Der Ratsassistent",
      text: "Ein KI-System beantwortet Fragen zu Kölner Ratsvorgängen und stützt sich dabei nur auf die Daten dieser Seite. Er braucht einen eigenen API-Schlüssel, nennt seine Quellen und verlinkt die Originale. Antworten können Fehler enthalten." },
    { target: ".nav-group.seg",
      title: "Flächen ein- und ausklappen",
      text: () => `${aufzaehlung([...document.querySelectorAll(".nav-group.seg .toggle[data-panel]")].filter((b) => !b.hidden && FLAECHEN[b.dataset.panel]).map((b) => FLAECHEN[b.dataset.panel]))} lassen sich hier öffnen und schließen; die Karte bleibt darunter sichtbar. Esc schließt die Fläche, in der Sie gerade sind.`,
      vorschau: "Die Flächen „Vorlagen“ und „Vorgang“ lassen sich hier öffnen und schließen; die Karte bleibt darunter sichtbar. Mit den Ratsvorlagen kommt die Zeitleiste hinzu. Esc schließt die Fläche, in der Sie gerade sind." },
    { target: "#about-open",
      title: "Über die Karte",
      text: "Hier steht, woher die Daten stammen, was Stand und Sicherheit der Angaben bedeuten und was die Karte nicht zeigen kann. Viel Freude beim Erkunden." },
  ];

  let steps = [], i = 0, root = null, card = null, spot = null, raf = 0, prevFocus = null, ui = null;

  const shown = (el) => el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const first = (sel) => sel ? [...document.querySelectorAll(sel)].find((el) => shown(el) && inView(el.getBoundingClientRect())) : null;
  const inView = (r) => r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;

  function build() {
    root = document.createElement("div");
    root.className = "tour";
    root.innerHTML = `<div class="tour-block"></div><div class="tour-spot" aria-hidden="true"></div><div class="tour-beacons" aria-hidden="true"></div>
      <div class="tour-card glass" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-text">
        <div class="tour-top"><span class="tour-count" id="tour-count"></span>
          <button type="button" class="icon-btn tour-x" data-tour-act="end" aria-label="Tour beenden"><svg class="icon" aria-hidden="true"><use href="#i-close"/></svg></button></div>
        <div class="tour-bar" aria-hidden="true"><span></span></div>
        <h2 class="tour-title" id="tour-title"></h2>
        <p class="tour-text" id="tour-text"></p>
        <div class="tour-nav">
          <button type="button" class="btn btn-ghost" data-tour-act="prev">Zurück</button>
          <button type="button" class="btn btn-cta" data-tour-act="next"></button>
        </div>
        <p class="visually-hidden" id="tour-live" aria-live="polite"></p>
      </div>`;
    document.body.appendChild(root);
    card = root.querySelector(".tour-card");
    spot = root.querySelector(".tour-spot");
    // Klicks bleiben in der Tour (sonst schlösse app.js das gerade geöffnete Menü)
    root.addEventListener("click", (e) => {
      e.stopPropagation();
      const b = e.target.closest("[data-tour-act]");
      if (!b) return;
      if (busy && b.dataset.tourAct !== "end") return;
      if (b.dataset.tourAct === "next") go(i + 1, 1);
      else if (b.dataset.tourAct === "prev") go(i - 1, -1);
      else end();
    });
  }

  function start() {
    ui = window.risKarte && window.risKarte.ui;
    if (!ui || root) return;
    const about = $("#about");
    if (about && about.open) about.close();
    prevFocus = document.activeElement;
    steps = STEPS.filter((s) => !s.when || s.when());
    ui.menu(null);
    build();
    // Rest der Seite für Tastatur und Screenreader sperren, solange die Tour läuft
    document.querySelectorAll("body > header, body > main").forEach((el) => { el.inert = true; });
    document.body.classList.add("touring");
    addEventListener("keydown", onKey, true);
    addEventListener("resize", layout);
    if (ui.prefetch && !VORSCHAU()) ui.prefetch();   // Beispiel-Vorgang nur mit Vorlagen
    go(0, 1);
  }

  function end() {
    if (!root) return;
    cancelAnimationFrame(raf);
    removeEventListener("keydown", onKey, true);
    removeEventListener("resize", layout);
    document.querySelectorAll("body > header, body > main").forEach((el) => { el.inert = false; });
    document.body.classList.remove("touring");
    ui.menu(null);
    if (ui.nav) ui.nav(false);
    root.remove();
    root = null;
    const back = prevFocus && prevFocus.isConnected && shown(prevFocus) ? prevFocus : $("#detail-heading");
    if (back) back.focus();
  }

  let goSeq = 0, busy = false;
  async function go(n, dir) {
    if (n >= steps.length) return end();
    if (n < 0) return;
    const s = steps[n], seq = ++goSeq;
    const pending = s.before && s.before(ui);
    if (pending && typeof pending.then === "function") {
      // Vorbereitung dauert (Beispiel wird geladen): Hinweis zeigen, Blättern sperren
      const next = root.querySelector('[data-tour-act="next"]');
      root.querySelector("#tour-text").textContent = "Einen Moment, das Beispiel wird geladen …";
      busy = true;
      next.setAttribute("aria-disabled", "true");
      try { await pending; } finally { busy = false; next.removeAttribute("aria-disabled"); }
    }
    // während des Wartens (Beispiel wird geladen) weitergeblättert oder beendet
    if (seq !== goSeq || !root) return;
    // Telefon: Menüs und Einträge der Leiste liegen hinter ☰ (Hamburger-Menü öffnen, sonst schließen)
    if (ui.nav) {
      const el = s.target && document.querySelector(s.target);
      ui.nav(MOBILE.matches && ((s.menu && s.menu !== "mega-suche") || !!(el && el.closest("#nav-more"))));
    }
    ui.menu(s.menu || null);
    if (s.scroll) { const el = $(s.target); if (el) el.scrollIntoView({ block: "start" }); }
    // fehlt das Element (etwa ohne Vorlagen im Gebiet), in Laufrichtung überspringen
    if ((s.requires && !$(s.requires)) || (s.target && !s.fallback && !$(s.target))) {
      if (n + dir >= 0 && n + dir < steps.length) return go(n + dir, dir);
    }
    i = n;
    root.querySelector("#tour-count").textContent = `Schritt ${n + 1} von ${steps.length}`;
    root.querySelector(".tour-bar span").style.width = `${((n + 1) / steps.length) * 100}%`;
    root.querySelector("#tour-title").textContent = s.title;
    const t = VORSCHAU() && s.vorschau ? s.vorschau : s.text;
    const text = typeof t === "function" ? t() : t;
    root.querySelector("#tour-text").textContent = text;
    const prev = root.querySelector('[data-tour-act="prev"]'), next = root.querySelector('[data-tour-act="next"]');
    prev.hidden = n === 0;
    next.textContent = n === 0 ? "Los geht's" : n === steps.length - 1 ? "Fertig" : "Weiter";
    root.querySelector("#tour-live").textContent = `Schritt ${n + 1} von ${steps.length}: ${s.title}. ${text}`;
    card.classList.remove("enter");
    void card.offsetWidth;  // Einblendung neu starten
    card.classList.add("enter");
    root.querySelector(".tour-beacons").innerHTML = (s.beacons || []).map(() => '<span class="tour-beacon"></span>').join("");
    next.focus();
    // Flächen gleiten herein: Lage einige Bilder lang nachführen
    cancelAnimationFrame(raf);
    const until = performance.now() + 700;
    const tick = () => { layout(); if (performance.now() < until) raf = requestAnimationFrame(tick); };
    tick();
  }

  function targetRect(s) {
    let r = null;
    if (s.rect) r = s.rect(ui);
    if (!r && (s.target || s.fallback)) {
      const el = first(s.target) || first(s.fallback);
      if (el) r = el.getBoundingClientRect();
    }
    if (!r) return null;
    let { left, top, right, bottom } = r;
    if (s.clip) {
      const c = $(s.clip).getBoundingClientRect();
      left = Math.max(left, c.left); top = Math.max(top, c.top); right = Math.min(right, c.right); bottom = Math.min(bottom, c.bottom);
    }
    const pad = 6;
    left = Math.max(4, left - pad); top = Math.max(4, top - pad);
    right = Math.min(innerWidth - 4, right + pad); bottom = Math.min(innerHeight - 4, bottom + pad);
    if (right - left < 12 || bottom - top < 12) return null;
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  }

  function layout() {
    if (!root) return;
    const s = steps[i], r = targetRect(s);
    spot.classList.toggle("none", !r);
    const box = r || { left: innerWidth / 2, top: innerHeight / 2, width: 0, height: 0 };
    Object.assign(spot.style, { left: box.left + "px", top: box.top + "px", width: box.width + "px", height: box.height + "px" });
    // pulsierende Punkte: Mitte kleiner Elemente, sonst rechte obere Ecke
    const beacons = root.querySelectorAll(".tour-beacon");
    (s.beacons || []).forEach((sel, k) => {
      const el = first(sel), b = beacons[k];
      if (!b) return;
      b.hidden = !el;
      if (!el) return;
      const e = el.getBoundingClientRect(), small = e.width < 40 && e.height < 40;
      b.style.left = (small ? e.left + e.width / 2 : e.right - 8) + "px";
      b.style.top = (small ? e.top + e.height / 2 : e.top + 8) + "px";
    });
    placeCard(r);
  }

  function placeCard(r) {
    const vw = innerWidth, vh = innerHeight, gap = 16, m = 10;
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const clampX = (x) => Math.max(m, Math.min(vw - cw - m, x));
    const clampY = (y) => Math.max(m, Math.min(vh - ch - m, y));
    let x, y;
    if (!r) { x = (vw - cw) / 2; y = (vh - ch) / 2; }
    else if (MOBILE.matches) { x = (vw - cw) / 2; y = (r.top + r.bottom) / 2 > vh / 2 ? m : vh - ch - m; }
    else if (r.bottom + gap + ch <= vh - m && r.height < vh * 0.6) { x = clampX(r.left + r.width / 2 - cw / 2); y = r.bottom + gap; }
    else if (r.right + gap + cw <= vw - m) { x = r.right + gap; y = clampY(r.top); }
    else if (r.left - gap - cw >= m) { x = r.left - gap - cw; y = clampY(r.top); }
    else if (r.top - gap - ch >= m) { x = clampX(r.left + r.width / 2 - cw / 2); y = r.top - gap - ch; }
    else { x = clampX(r.left + r.width / 2 - cw / 2); y = vh - ch - m; }
    card.style.left = Math.round(x) + "px";
    card.style.top = Math.round(y) + "px";
  }

  function onKey(e) {
    if (!root) return;
    const keys = { Escape: end, ArrowRight: () => go(i + 1, 1), ArrowLeft: () => go(i - 1, -1) };
    if (keys[e.key]) { e.preventDefault(); e.stopPropagation(); if (!busy || e.key === "Escape") keys[e.key](); return; }
    if (e.key === "Tab") {  // Fokus bleibt in der Karte
      const f = [...card.querySelectorAll("button")].filter(shown);
      const k = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(k + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
  }

  document.addEventListener("click", (e) => { if (e.target.closest("[data-tour]")) start(); });
})();
