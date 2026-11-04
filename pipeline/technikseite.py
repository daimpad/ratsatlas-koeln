"""Seite technik/: So funktioniert der Ratsatlas (Entscheidungen des Auftraggebers 03.11.2026: vier Grafiken – Überblick,
Datenfluss, Zeitplan, Technik-Stapel –, aus dem Repository erzeugt, anklickbar mit Erklärung, je Grafik zwei bis vier
Sätze, Menü „Verstehen“, ohne Laufstatus).

Aus dem Repository gelesen werden: die Schritte der Pipeline aus .github/workflows/pages.yml (Reihenfolge), Name,
Zeitpunkte und Auslöser aller Workflows, Schritte mit „montags“ oder „am 1. des Monats“ im Namen, die Module der Schritte
aus pipeline/__main__.py, Quellen und Lizenzen aus config.SOURCES, Pakete aus requirements.txt und
tests/browser/package.json, Versionen aus site/vendor und den Workflows. Die Erklärungen stehen in diesem Modul;
tests/test_technikseite.py prüft, dass jeder Schritt, jeder Workflow und jede Quelle eine hat. Keine
Erzeugungszeitpunkte (stabile Ausgabe).

Jeder Kasten ist ein Link auf seinen Eintrag in der Liste unter der Grafik (gleichwertige Fassung für Vorleseprogramme,
ohne Skript das Ziel des Links); site/technik.js zeigt die Erklärung stattdessen direkt unter der Grafik."""
import json
import re
from html import escape

from . import config

PFAD = "technik/"
REPO = "https://github.com/daimpad/ratsatlas-koeln"
CODE = REPO + "/blob/main/"
ACTIONS = REPO + "/actions"
TREE = REPO + "/tree/main/"   # Verzeichnisse (blob/ gilt nur für Dateien)
WORKFLOWS = config.ROOT / ".github" / "workflows"
BREIT, HOCH = 760, 340   # Breite der Grafiken (Seite höchstens 760 px; Telefon)

# --- Erklärungen ----------------------------------------------------------------------------------------

# Schritte der Pipeline (python -m pipeline <schritt>): Kurzname und Erklärung (Ratsatlas Köln)
SCHRITTE = {
    "fetch": ("Abruf", "Holt Vorlagen, Gremien und Sitzungen mit ihren Tagesordnungspunkten über die OParl-Schnittstelle "
                       "der Stadt Köln: nachts, mit einer Verbindung und Abstand zwischen den Anfragen, nach dem ersten "
                       "Lauf nur Geänderte. Bricht ein Abruf ab, bleibt der Stand des letzten Laufs."),
    "build": ("Datenbank und Verortung", "Baut eine SQLite-Datenbank aus Vorlagen, Beratungen, Sitzungen und Gremien, "
                                         "verortet Vorlagen nach festen Regeln und leitet den Stand jedes Vorgangs ab."),
    "export": ("Export", "Schreibt je Gebiet eine Datei für die Karte, dazu Feeds, Kalender, GeoJSON und "
                         "Prüfprotokolle."),
    "package": ("Datenpaket", "Packt Daten, Prüfprotokolle und Lizenzen in ein Zip-Paket zum Herunterladen."),
}

# Workflows (.github/workflows/<datei>): Kurzname und Erklärung
WORKFLOW_TEXT = {
    "pages.yml": ("Hauptlauf", "Holt die Daten, bereitet sie auf und veröffentlicht die Seite: auf GitHub Pages und im "
                               "Branch deploy, aus dem der Server der Hauptadresse liest. Ohne Daten der Stadt "
                               "veröffentlicht er nichts."),
    "live.yml": ("Live-Prüfung", "Prüft, ob Hauptadresse und Spiegel den neuen Stand zeigen und wichtige Seiten und "
                                 "Feeds antworten."),
    "kacheln.yml": ("Kartenkacheln", "Erzeugt vierteljährlich die grauen Kartenkacheln für Köln aus OpenStreetMap-Daten "
                                     "und legt sie im Branch kacheln ab."),
    "tests.yml": ("Tests", "Prüft jede Änderung am Code mit Tests gegen einen lokalen Testserver, ohne Anfragen an die "
                           "Stadt."),
}

# Quellen aus config.SOURCES: Kurzname und Erklärung (Lizenz aus config.SOURCES)
QUELLEN = {
    "oparl-koeln": ("Ratsinformationssystem", "Die OParl-Schnittstelle der Stadt Köln: Vorlagen, Gremien, Sitzungen "
                                              "und Tagesordnungspunkte. Hauptquelle der Karte."),
    "geo-koeln": ("Stadtteile und Stadtbezirke", "Flächen der 86 Stadtteile und 9 Stadtbezirke aus dem "
                                                 "Open-Data-Portal der Stadt."),
    "strassen-koeln": ("Straßen", "Straßen der Stadt Köln; daraus entsteht das Straßenverzeichnis je Stadtteil."),
    "adressen-koeln": ("Adressen", "Adressen der Stadt Köln: Stadtteil einer Hausnummer und, nur bei Vorlagen der "
                                   "Verwaltung und politischen Anträgen, die Hauskoordinate."),
    "osm": ("OpenStreetMap", "Daten der grauen Karte."),
}
WEITERE_QUELLEN = []

AUSGABEN = [
    ("a-karte", "Karte und Liste", "Je Gebiet eine JSON-Datei, die die Karte im Browser lädt; die Suche über ganz Köln "
                                   "hat eine eigene Datei.", ""),
    ("a-seiten", "Statische Seiten", "Gebietsseiten, Begriffe, Feeds und diese Seite, ohne Skript lesbar.", "gebiete/"),
    ("a-feeds", "Feeds und Kalender", "Atom-Feeds je Gebiet, je Vorlage und für ganz Köln, dazu ein Sitzungskalender "
                                      "(ICS).", "rss/"),
    ("a-offen", "Offene Daten", "GeoJSON der verorteten Vorlagen, Beschreibung nach DCAT-AP und Prüfprotokolle als "
                                "TSV.", None),
    ("a-paket", "Datenpaket", "Alle Daten, Prüfprotokolle und Lizenzen als Zip-Paket.", config.PAKET_URL),
    ("a-pages", "GitHub Pages", "Der Spiegel der Seite unter daimpad.github.io.", "https://daimpad.github.io/ratsatlas-koeln/"),
    ("a-server", "Hauptadresse", "Der Branch deploy enthält die fertige Seite; der Server von koeln.ratsatlas.de "
                                 "übernimmt ihn über einen Webhook.", config.SITE_URL),
]

UEBERBLICK = [
    ("Woher?", [
        ("u-ris", "Ratsinformationssystem der Stadt", "Hier stehen alle öffentlichen Vorlagen, Sitzungen und Gremien. "
                                                      "Die Stadt stellt sie über eine offene Schnittstelle bereit."),
        ("u-geo", "Karten und Flächen", "Stadtteile, Stadtbezirke, Straßen und Adressen der Stadt; der Kartenhintergrund "
                                        "aus OpenStreetMap."),
    ]),
    ("Jede Nacht", [
        ("u-holen", "Abholen", "Ein Programm holt geänderte Daten jede Nacht schonend ab; bei einem Ausfall bleibt der "
                               "letzte Stand."),
        ("u-verorten", "Verorten", "Es sucht in Titeln nach Straßen, Stadtteilen und Stadtbezirken und markiert, wie "
                                   "sicher ein Ort ist."),
        ("u-ordnen", "Ordnen", "Es ordnet Beratungen zu einer Prozesslinie, ermittelt den Stand und ordnet Themen zu."),
    ]),
    ("Die Seite", [
        ("u-karte", "Karte und Liste", "Vorlagen auf der Karte und in einer Liste, mit Filtern und Zeitleiste."),
        ("u-gebiete", "Gebietsseiten", "Eine Seite je Stadtteil und Stadtbezirk, auch ohne Skript lesbar."),
        ("u-abo", "Feeds und Kalender", "Neues abonnieren, Sitzungen im eigenen Kalender."),
        ("u-daten", "Offene Daten", "Alles zum Herunterladen und Weiterverwenden."),
    ]),
    ("Für wen?", [
        ("u-buerger", "Bürger:innen", "Sehen, was in der eigenen Nachbarschaft beraten wird, und mitwirken."),
        ("u-politik", "Politik und Verwaltung", "Vorgänge und Zuständigkeiten schneller finden."),
        ("u-presse", "Presse und Initiativen", "Verfahren verfolgen und belegen, mit Link zum Original."),
        ("u-weiter", "Weiterverwendung", "Apps, Forschung und andere Seiten nutzen die offenen Daten."),
    ]),
]

WOCHENTAG = {"0": "sonntags", "1": "montags", "2": "dienstags", "3": "mittwochs", "4": "donnerstags",
             "5": "freitags", "6": "samstags", "7": "sonntags"}
MONAT = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
         "Dezember"]


# --- aus dem Repository ---------------------------------------------------------------------------------

def workflows(ordner=None):
    """Je Workflow-Datei: Name, Zeitpunkte (cron), Auslöser, Schritte der Pipeline (Reihenfolge) und Namen der
    Schritte. Einfache Zeilenauswertung, ohne YAML-Bibliothek (die Workflows sind einheitlich geschrieben)."""
    out = []
    for p in sorted((ordner or WORKFLOWS).glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        kopf = text.split("\njobs:")[0]
        out.append({
            "datei": p.name,
            "name": re.search(r"^name:\s*(.+?)\s*$", text, re.M).group(1).strip('"'),
            "crons": re.findall(r'cron:\s*"([^"]+)"', kopf),
            "ausloeser": [k for k in ("schedule", "push", "pull_request", "workflow_run", "workflow_dispatch")
                          if re.search(rf"^\s+{k}:", kopf, re.M)],
            "schritte": list(dict.fromkeys(re.findall(r"python -m pipeline ([a-z0-9-]+)", text))),
            "namen": re.findall(r"^\s+- name:\s*(.+?)\s*$", text, re.M),
            "branches": sorted(set(re.findall(r"(?:branch|ref:)\s+([a-z]+)\b", text)) - {"main"}),
        })
    return out


def module():
    """{Schritt: Datei des Moduls} aus pipeline/__main__.py (Schritte mit lambda: dossier)."""
    text = (config.ROOT / "pipeline" / "__main__.py").read_text(encoding="utf-8")
    return {s: f"pipeline/{m}.py" for s, m in re.findall(r'^\s+"([a-z0-9-]+)":\s*(?:lambda:\s*)?([a-z_]+)\.', text, re.M)}


def versionen():
    """Versionen und Pakete für den Technik-Stapel."""
    wf = "".join(p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml")))
    python = sorted(set(re.findall(r'python-version:\s*"([0-9.]+)"', wf)))
    pakete = [re.split(r"[<>=~ ]", z.strip(), maxsplit=1)[0] for z in
              (config.ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if z.strip() and not z.startswith("#")]
    pj = config.ROOT / "tests" / "browser" / "package.json"   # in Köln (noch) keine Browser-Tests mit eigener package.json
    browser = json.loads(pj.read_text(encoding="utf-8"))["dependencies"] if pj.exists() else {}
    leaflet = re.search(r'version="([0-9.]+)"', (config.ROOT / "site" / "vendor" / "leaflet" / "leaflet.min.js")
                        .read_text(encoding="utf-8"))
    tests = len(list((config.ROOT / "tests").glob("test_*.py")))
    return {"python": python, "pakete": pakete, "browser": browser, "leaflet": leaflet.group(1) if leaflet else "",
            "tests": tests, "browsertests": len(list((config.ROOT / "tests" / "browser").glob("*.test.mjs")))}


def _zeit(m, h, versatz=0):
    return f"{(int(h) + versatz) % 24:02d}:{int(m):02d}"


def cron_text(c):
    """„17 4 * * *“ → „täglich 04:17 UTC“; nur die in den Workflows vorkommenden Formen."""
    m, h, dom, mon, dow = c.split()
    zeit = f"{_zeit(m, h)} UTC"
    if dom == mon == dow == "*":
        return f"täglich {zeit}"
    if dom == mon == "*":
        return f"{WOCHENTAG[dow]} {zeit}"
    monate = ", ".join(MONAT[int(x) - 1] for x in mon.split(",")) if mon != "*" else "jeden Monats"
    return f"am {dom}. {monate} um {zeit}"


def ortszeit(c):
    m, h, *_ = c.split()
    return f"in Köln {_zeit(m, h, 1)} Uhr, im Sommer {_zeit(m, h, 2)} Uhr"


def ausloeser_text(w):
    teile = [cron_text(c) for c in w["crons"]]
    if "workflow_run" in w["ausloeser"]:
        teile.append("nach jedem Hauptlauf")
    if "push" in w["ausloeser"]:
        teile.append("bei jeder Änderung an main")
    if "pull_request" in w["ausloeser"]:
        teile.append("bei jedem Pull Request")
    if "workflow_dispatch" in w["ausloeser"]:
        teile.append("auf Knopfdruck")
    return ", ".join(teile)


# --- Grafiken -------------------------------------------------------------------------------------------

def _zeilen(text, n):
    """Zeilenumbruch nach Wörtern, höchstens n Zeichen je Zeile."""
    out, zeile = [], ""
    for w in text.split():
        if zeile and len(zeile) + 1 + len(w) > n:
            out.append(zeile)
            zeile = w
        else:
            zeile = f"{zeile} {w}".strip()
    return out + ([zeile] if zeile else [])


def _box(e, x, y, w, h, klasse, zeilen):
    """Kasten als Link auf den Eintrag der Liste; Text mittig."""
    key, titel = e[0], e[1]
    y0 = y + h / 2 - (len(zeilen) - 1) * 8 + 5
    text = "".join(f'<text x="{x + w / 2:.0f}" y="{y0 + i * 16:.0f}" text-anchor="middle">{escape(z)}</text>'
                   for i, z in enumerate(zeilen))
    return (f'<a href="#tk-{key}" class="tk-box {klasse}" aria-label="{escape(titel)}: Erklärung anzeigen">'
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="8"/>{text}</a>')


def _pfeil(x1, y1, x2, y2, marke):
    return f'<line class="tk-pfeil" x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" marker-end="url(#{marke})"/>'


def _defs(marke):
    return (f'<defs><marker id="{marke}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="tk-spitze"/></marker></defs>')


def spalten_svg(spalten, format_, name, label):
    """Spalten mit Kästen und Pfeilen von Spalte zu Spalte. Breit: Spalten nebeneinander; hoch (Telefon): Spalten
    untereinander, Kästen zu zweit in einer Reihe, Pfeil nach unten."""
    marke = f"tk-spitze-{name}-{format_}"
    teile = []
    if format_ == "breit":
        n, rand, abstand = len(spalten), 4, 34
        bw = (BREIT - 2 * rand - (n - 1) * abstand) / n
        zeichen = int(bw / 7.4)
        hoehen = [[18 + 16 * len(_zeilen(e[1], zeichen)) for e in boxen] for _, boxen in spalten]
        hoehe = 36 + max(sum(h) + 8 * (len(h) - 1) for h in hoehen) + 8
        for i, ((kopf, boxen), hs) in enumerate(zip(spalten, hoehen)):
            x = rand + i * (bw + abstand)
            teile.append(f'<text class="tk-kopf" x="{x + bw / 2:.0f}" y="20" text-anchor="middle">{escape(kopf)}</text>')
            gesamt = sum(hs) + 8 * (len(hs) - 1)
            y = 36 + (hoehe - 44 - gesamt) / 2
            for e, h in zip(boxen, hs):
                teile.append(_box(e, x, y, bw, h, f"tk-c{i % 4}", _zeilen(e[1], zeichen)))
                y += h + 8
            if i < n - 1:
                teile.append(_pfeil(x + bw + 4, 36 + (hoehe - 44) / 2, x + bw + abstand - 4, 36 + (hoehe - 44) / 2, marke))
        w = BREIT
    else:
        rand, abstand = 4, 8
        bw = (HOCH - 2 * rand - abstand) / 2
        zeichen = int(bw / 7.4)
        y = 0
        for i, (kopf, boxen) in enumerate(spalten):
            teile.append(f'<text class="tk-kopf" x="{HOCH / 2:.0f}" y="{y + 18:.0f}" text-anchor="middle">{escape(kopf)}</text>')
            y += 28
            for k in range(0, len(boxen), 2):
                reihe = boxen[k:k + 2]
                h = max(18 + 16 * len(_zeilen(e[1], zeichen)) for e in reihe)
                for j, e in enumerate(reihe):
                    breite = bw if len(reihe) == 2 or len(boxen) > 1 else HOCH - 2 * rand
                    teile.append(_box(e, rand + j * (bw + abstand), y, breite, h, f"tk-c{i % 4}", _zeilen(e[1], zeichen)))
                y += h + abstand
            if i < len(spalten) - 1:
                teile.append(_pfeil(HOCH / 2, y + 2, HOCH / 2, y + 24, marke))
                y += 28
        w, hoehe = HOCH, y + 4
    return (f'<svg class="tk-svg hh-{format_}" viewBox="0 0 {w} {hoehe:.0f}" role="group" aria-label="{escape(label)}">'
            + _defs(marke) + "".join(teile) + "</svg>")


def zeitplan(wfs):
    """Einträge des Zeitplans: (key, Kurzname, Erklärung, Workflow, cron) je Zeitpunkt, nach Uhrzeit."""
    out = []
    for w in wfs:
        for c in w["crons"]:
            m, h, *_ = c.split()
            out.append((int(h) * 60 + int(m), w, c))
    return sorted(out, key=lambda x: (x[0], x[1]["datei"]))


def zeitplan_svg(wfs, format_):
    """Tagesachse (UTC) mit den festen Zeitpunkten und ein Jahresstreifen (vierteljährlich, monatlich)."""
    marke = f"tk-spitze-zeit-{format_}"
    termine = zeitplan(wfs)
    monatlich = [n for w in wfs if w["datei"] == "pages.yml" for n in w["namen"] if "am 1. des Monats" in n]
    teile = []
    if format_ == "breit":
        x0, x1, zeile = 250, BREIT - 16, 40
        px = lambda minuten: x0 + (x1 - x0) * minuten / 1440
        y = 34
        for st in range(0, 25, 3):
            teile.append(f'<line class="tk-raster" x1="{px(st * 60):.0f}" y1="24" x2="{px(st * 60):.0f}" '
                         f'y2="{34 + zeile * len(termine)}"/><text class="tk-achse" x="{px(st * 60):.0f}" y="18" '
                         f'text-anchor="middle">{st:02d}:00</text>')
        for minuten, w, c in termine:
            kurz = WORKFLOW_TEXT[w["datei"]][0]
            haeufig = cron_text(c).split(" ")[0] if c.split()[2] == "*" else "vierteljährlich"
            e = (f"z-{w['datei'][:-4]}-{minuten}", kurz)
            teile.append(_box(e, 4, y + 4, 230, zeile - 8, "tk-c1", [f"{kurz} ({haeufig})"]))
            teile.append(f'<circle class="tk-punkt" cx="{px(minuten):.0f}" cy="{y + zeile / 2:.0f}" r="6"/>'
                         f'<text class="tk-zeit" x="{px(minuten) + 10:.0f}" y="{y + zeile / 2 + 5:.0f}">'
                         f'{_zeit(*c.split()[:2])}</text>')
            y += zeile
        y += 30
        teile.append(f'<text class="tk-kopf" x="4" y="{y:.0f}">Im Jahr</text>')
        mx = lambda tag: x0 + (x1 - x0) * tag / 365
        for i, mname in enumerate(MONAT):
            teile.append(f'<text class="tk-achse" x="{mx(i * 30.4 + 15):.0f}" y="{y:.0f}" text-anchor="middle">{mname[:3]}</text>')
        y += 10
        streifen = []
        for minuten, w, c in termine:
            if c.split()[3] != "*":
                streifen.append((f"z-{w['datei'][:-4]}-jahr", WORKFLOW_TEXT[w["datei"]][0],
                                 [int(c.split()[2]) - 1 + (int(mo) - 1) * 30.4 for mo in c.split()[3].split(",")]))
        if monatlich:
            streifen.append(("z-monatlich", "Haltestellen (am 1.)", [mo * 30.4 for mo in range(12)]))
        for key, kurz, tage in streifen:
            teile.append(_box((key, kurz), 4, y + 4, 230, zeile - 8, "tk-c2", [kurz]))
            teile.append(f'<line class="tk-raster" x1="{x0}" y1="{y + zeile / 2:.0f}" x2="{x1}" y2="{y + zeile / 2:.0f}"/>')
            teile += [f'<circle class="tk-punkt" cx="{mx(t):.0f}" cy="{y + zeile / 2:.0f}" r="5"/>' for t in tage]
            y += zeile
        w, hoehe = BREIT, y + 6
    else:
        x0, oben, je_stunde = 52, 30, 20
        py = lambda minuten: oben + je_stunde * minuten / 60
        teile.append(f'<line class="tk-achse-linie" x1="{x0}" y1="{oben}" x2="{x0}" y2="{py(1440):.0f}"/>')
        for st in range(0, 25, 3):
            teile.append(f'<text class="tk-achse" x="{x0 - 8}" y="{py(st * 60) + 4:.0f}" text-anchor="end">{st:02d}:00</text>'
                         f'<line class="tk-raster" x1="{x0 - 4}" y1="{py(st * 60):.0f}" x2="{HOCH - 4}" y2="{py(st * 60):.0f}"/>')
        teile.append(f'<text class="tk-kopf" x="4" y="16">Am Tag (UTC)</text>')
        frei = oben
        for minuten, w, c in termine:
            kurz = WORKFLOW_TEXT[w["datei"]][0]
            yy = max(py(minuten) - 15, frei)
            teile.append(f'<circle class="tk-punkt" cx="{x0}" cy="{py(minuten):.0f}" r="6"/>')
            if yy + 15 != py(minuten):
                teile.append(f'<line class="tk-raster" x1="{x0}" y1="{py(minuten):.0f}" x2="{x0 + 18}" y2="{yy + 15:.0f}"/>')
            e = (f"z-{w['datei'][:-4]}-{minuten}", kurz)
            teile.append(_box(e, x0 + 18, yy, HOCH - x0 - 22, 30, "tk-c1", [f"{_zeit(*c.split()[:2])} {kurz}"]))
            frei = yy + 34
        y = max(py(1440), frei) + 30
        teile.append(f'<text class="tk-kopf" x="4" y="{y:.0f}">Im Jahr</text>')
        y += 8
        mx = lambda tag: 8 + (HOCH - 16) * tag / 365
        for i, mname in enumerate(MONAT):
            teile.append(f'<text class="tk-achse" x="{mx(i * 30.4 + 15):.0f}" y="{y + 12:.0f}" text-anchor="middle">{mname[0]}</text>')
        y += 20
        for minuten, w, c in termine:
            if c.split()[3] != "*":
                kurz = WORKFLOW_TEXT[w["datei"]][0]
                teile.append(_box((f"z-{w['datei'][:-4]}-jahr", kurz), 4, y, HOCH - 8, 30, "tk-c2", [kurz]))
                y += 36
                teile += [f'<circle class="tk-punkt" cx="{mx(int(c.split()[2]) - 1 + (int(mo) - 1) * 30.4):.0f}" '
                          f'cy="{y:.0f}" r="5"/>' for mo in c.split()[3].split(",")]
                y += 16
        if monatlich:
            teile.append(_box(("z-monatlich", "Haltestellen (am 1.)"), 4, y, HOCH - 8, 30, "tk-c2", ["Haltestellen (am 1.)"]))
            y += 36
            teile += [f'<circle class="tk-punkt" cx="{mx(mo * 30.4):.0f}" cy="{y:.0f}" r="5"/>' for mo in range(12)]
            y += 16
        w, hoehe = HOCH, y + 4
    return (f'<svg class="tk-svg hh-{format_}" viewBox="0 0 {w} {hoehe:.0f}" role="group" '
            f'aria-label="Zeitplan der automatischen Läufe">' + _defs(marke) + "".join(teile) + "</svg>")


def stapel_svg(schichten, format_):
    """Technik-Stapel: Schichten untereinander, je Schicht ein Name und Kästen, die umbrechen."""
    w = BREIT if format_ == "breit" else HOCH
    links = 150 if format_ == "breit" else 4
    teile, y = [], 4
    for i, (kopf, boxen) in enumerate(schichten):
        start = y
        if format_ != "breit":
            teile.append(f'<text class="tk-kopf" x="4" y="{y + 16:.0f}">{escape(kopf)}</text>')
            y += 24
        x, zeile_y = links, y + 8
        for e in boxen:
            bw = min(w - links - 8, 22 + 7.4 * len(e[1]))
            if x + bw > w - 4:
                x, zeile_y = links, zeile_y + 38
            teile.append(_box(e, x, zeile_y, bw, 30, f"tk-c{i % 4}", [e[1]]))
            x += bw + 8
        y = zeile_y + 38 + 4
        if format_ == "breit":
            teile.insert(len(teile) - len(boxen), f'<rect class="tk-schicht" x="2" y="{start:.0f}" width="{w - 4}" '
                                                   f'height="{y - start - 4:.0f}" rx="10"/><text class="tk-kopf" x="14" '
                                                   f'y="{start + (y - start) / 2 + 3:.0f}">{escape(kopf)}</text>')
        else:
            teile.insert(len(teile) - len(boxen) - 1, f'<rect class="tk-schicht" x="0" y="{start:.0f}" width="{w}" '
                                                       f'height="{y - start - 4:.0f}" rx="10"/>')
        y += 4
    return (f'<svg class="tk-svg hh-{format_}" viewBox="0 0 {w} {y:.0f}" role="group" aria-label="Technik-Stapel">'
            + "".join(teile) + "</svg>")


# --- Inhalt ---------------------------------------------------------------------------------------------

def _link(ziel, root, text="Mehr"):
    if ziel is None:
        return ""
    href = ziel if ziel.startswith("http") else root + ziel
    return f' <a href="{escape(href)}">{escape(text)}</a>'


def daten(root="../"):
    """Alles für die Seite: Kästen je Grafik mit Erklärung und Link."""
    wfs = workflows()
    mods = module()
    pages = next(w for w in wfs if w["datei"] == "pages.yml")
    v = versionen()

    def schritt(s):
        kurz, text = SCHRITTE[s]
        return (f"s-{s}", kurz, text, CODE + mods.get(s, "pipeline/__main__.py"), f"Code ({mods.get(s, '')})")

    ist_abruf = lambda s: s == "fetch" or s.startswith("fetch-")
    abruf = [schritt(s) for s in pages["schritte"] if ist_abruf(s)]
    rest = [schritt(s) for s in pages["schritte"] if not ist_abruf(s)]
    quellen = [(f"q-{k}", QUELLEN[k][0], f"{QUELLEN[k][1]} Lizenz: {config.SOURCES[k]['license']}.",
                config.SOURCES[k]["url"] if config.SOURCES[k]["url"].startswith("http") else None, "Quelle")
               for k in config.SOURCES]
    quellen += [(k, t, e, z, "Seite") for k, t, e, z in WEITERE_QUELLEN]
    ausgaben = [(k, t, e, z, "Öffnen") for k, t, e, z in AUSGABEN]
    ueberblick = [(kopf, [(k, t, e, None, "") for k, t, e in boxen]) for kopf, boxen in UEBERBLICK]

    termine = []
    for minuten, w, c in zeitplan(wfs):
        kurz, text = WORKFLOW_TEXT[w["datei"]]
        termine.append((f"z-{w['datei'][:-4]}-{minuten}", kurz,
                        f"{cron_text(c)} ({ortszeit(c)}). Auslöser: {ausloeser_text(w)}. {text}",
                        CODE + ".github/workflows/" + w["datei"], f"Workflow {w['datei']}"))
    for w in wfs:
        for c in w["crons"]:
            if c.split()[3] != "*":
                termine.append((f"z-{w['datei'][:-4]}-jahr", WORKFLOW_TEXT[w["datei"]][0],
                                f"{cron_text(c)}. {WORKFLOW_TEXT[w['datei']][1]}",
                                CODE + ".github/workflows/" + w["datei"], f"Workflow {w['datei']}"))
    woechentlich = [n for n in pages["namen"] if "montags" in n]
    monatlich = [n for n in pages["namen"] if "am 1. des Monats" in n]
    if monatlich:
        termine.append(("z-monatlich", "Haltestellen (am 1.)",
                        "Innerhalb des Hauptlaufs: " + "; ".join(monatlich) + ". Montags zusätzlich: "
                        + "; ".join(woechentlich) + ".", CODE + ".github/workflows/pages.yml", "Workflow pages.yml"))
    ohne = [(f"z-{w['datei'][:-4]}", WORKFLOW_TEXT[w["datei"]][0], f"Auslöser: {ausloeser_text(w)}. "
             f"{WORKFLOW_TEXT[w['datei']][1]}", CODE + ".github/workflows/" + w["datei"], f"Workflow {w['datei']}")
            for w in wfs if not w["crons"]]

    branches = sorted({b for w in wfs for b in w["branches"]})
    schichten = [
        ("Betrieb", [
            ("t-actions", "GitHub Actions", f"{len(wfs)} Workflows steuern Abruf, Prüfung und Veröffentlichung "
                                             f"(Grafik „Zeitplan“).", ACTIONS, "Läufe auf GitHub"),
            ("t-pages", "GitHub Pages", "Hostet den Spiegel der Seite.", "https://daimpad.github.io/ratsatlas-koeln/", "Spiegel"),
            ("t-server", "Webhosting (Plesk)", "Der Server der Hauptadresse übernimmt den Branch deploy über einen "
                                               "Webhook; .htaccess setzt Sicherheitskopfzeilen.", config.SITE_URL, "Hauptadresse"),
            ("t-branches", "Branches", "Neben main: " + ", ".join(branches) + ". Sie halten die fertige Seite und die "
                                       "Kartenkacheln getrennt vom Code.", REPO + "/branches", "Branches"),
        ]),
        ("Im Browser", [
            ("t-html", "HTML und CSS", "Statische Seiten ohne Server-Programm; Glas-Stil, WCAG 2.1 AA.", None, ""),
            ("t-js", "JavaScript", "Eigener Code ohne Framework für Karte, Liste, Zeitleiste und Tour.",
             CODE + "site/app.js", "Code (site/app.js)"),
            ("t-leaflet", f"Leaflet {v['leaflet']}".strip(), "Bibliothek für die Karte, mit Markercluster; lokal "
                                                             "eingebunden, ohne fremde Server.", "https://leafletjs.com/", "Leaflet"),
            ("t-kacheln", "Graue Kacheln", "Kartenhintergrund vom eigenen Server, erzeugt aus OpenStreetMap-Daten; "
                                           "„Farbige Karte“ lädt Kacheln von OpenStreetMap.", TREE + "pipeline/kacheln/", "Code"),
        ]),
        ("Prüfung", [
            ("t-pytest", "pytest", f"{v['tests']} Dateien mit Tests für Abruf, Aufbereitung, Verortung und Export, gegen "
                                   "einen lokalen Testserver.", REPO + "/tree/main/tests", "Tests"),
            ("t-axe", "axe-core", "Prüft die Barrierefreiheit (WCAG 2.1 A und AA) der Seite.",
             CODE + "tools/wcag_pruefen.js", "Prüfskript"),
        ]),
        ("Aufbereitung", [
            ("t-python", "Python " + ", ".join(v["python"]), "Die Pipeline in python -m pipeline, ein Schritt je "
                                                             "Aufgabe (Grafik „Datenfluss“).", TREE + "pipeline/", "Code"),
            ("t-sqlite", "SQLite", "Datenbank eines Laufs; sie wird nicht veröffentlicht, nur ihre Exporte.",
             CODE + "pipeline/build.py", "Code"),
            *[(f"t-{p}", p, f"Python-Paket aus requirements.txt: {PAKET_TEXT.get(p, '')}".rstrip(": "),
               f"https://pypi.org/project/{p}/", "PyPI") for p in v["pakete"]],
        ]),
        ("Daten", [
            ("t-oparl", "OParl (JSON)", "Offener Standard für Ratsinformationssysteme; die Stadt Köln bietet ihn an.",
             "https://oparl.org/", "OParl"),
            ("t-shapefile", "Shapefile", "Format der Kölner Geodaten (Stadtteile, Straßen, Adressen).", None, ""),
            ("t-geojson", "GeoJSON", "Flächen für die Seite und die verorteten Vorlagen.", None, ""),
        ]),
    ]
    return {"ueberblick": ueberblick, "fluss": [("Quellen", quellen), ("Abruf", abruf), ("Aufbereitung", rest),
                                                ("Ergebnis", ausgaben)],
            "termine": termine, "ohne": ohne, "wfs": wfs, "schichten": schichten}


PAKET_TEXT = {"shapely": "Geometrie, etwa ob ein Punkt in einem Stadtteil liegt",
              "pyproj": "Umrechnung zwischen Koordinatensystemen (ETRS89/UTM 32N nach WGS84)",
              "pyshp": "Lesen der Shapefiles der Stadt Köln",
              "cairosvg": "Bild der Themenseite als PNG zum Teilen"}


def _liste(eintraege, root):
    zeilen = []
    for k, t, e, ziel, linktext in eintraege:
        zeilen.append(f'        <li id="tk-{escape(k)}"><strong>{escape(t)}</strong>: {escape(e)}'
                      f'{_link(ziel, root, linktext or "Mehr")}</li>')
    return "\n".join(zeilen)


def _grafik(anker, titel, text, svgs, eintraege, root, extra=""):
    return f"""    <h2 id="{anker}">{escape(titel)}</h2>
    <p>{text}</p>
    <figure class="tk-grafik">
      {svgs}{extra}
      <div class="tk-detail" aria-live="polite" hidden></div>
      <figcaption class="meta">Ein Klick auf einen Kasten zeigt seine Erklärung.</figcaption>
    </figure>
    <details class="hh-mehr tk-liste">
      <summary>Alle Kästen erklärt</summary>
      <ul>
{_liste(eintraege, root)}
      </ul>
    </details>"""


def body(d, root):
    fluss_alle = [e for _, boxen in d["fluss"] for e in boxen]
    ueber_alle = [e for _, boxen in d["ueberblick"] for e in boxen]
    stapel_alle = [e for _, boxen in d["schichten"] for e in boxen]
    zeit_svg = zeitplan_svg(d["wfs"], "breit") + zeitplan_svg(d["wfs"], "hoch")
    ohne = "\n".join(f'        <li><a class="tk-box" href="#tk-{k}">{escape(t)}</a>: {escape(e.split(". ", 1)[0])}</li>'
                     for k, t, e, *_ in d["ohne"])
    return f"""    <h1>So funktioniert der Ratsatlas</h1>
    <p class="lead">Woher kommen die Daten des Ratsatlas, was passiert mit ihnen und wann wird die Seite neu erzeugt? Vier Grafiken zeigen es, vom Überblick bis zur Technik. Sie entstehen aus dem Code im Repository und zeigen den Aufbau, nicht den Verlauf einzelner Läufe.</p>
    <nav class="thema-sprung" aria-label="Auf dieser Seite"><span>Auf dieser Seite:</span> <a href="#ueberblick">Überblick</a> · <a href="#datenfluss">Datenfluss</a> · <a href="#zeitplan">Zeitplan</a> · <a href="#technik">Technik</a> · <a href="#grenzen">Grenzen</a></nav>
{_grafik("ueberblick", "Überblick", "Die Karte erfindet nichts: Sie holt öffentliche Daten der Stadt Köln, ordnet sie jede Nacht neu und zeigt sie so, dass man sie nach Ort, Zeit und Zuständigkeit finden kann. Was die Karte selbst erschließt, etwa den Ort einer Vorlage, ist als abgeleitet gekennzeichnet.", spalten_svg(d["ueberblick"], "breit", "ueber", "Überblick: Woher, jeden Morgen, die Seite, für wen") + spalten_svg(d["ueberblick"], "hoch", "ueber", "Überblick: Woher, jeden Morgen, die Seite, für wen"), ueber_alle, root)}
{_grafik("datenfluss", "Datenfluss", "Jeder Kasten in der Mitte ist ein Schritt der Pipeline, aufgerufen mit <code>python -m pipeline &lt;schritt&gt;</code>, in der Reihenfolge des Hauptlaufs. Links stehen die Quellen mit ihrer Lizenz, rechts die Ergebnisse. Die Liste der Schritte liest diese Seite aus dem Workflow; kommt ein Schritt hinzu, erscheint er hier.", spalten_svg(d["fluss"], "breit", "fluss", "Datenfluss: Quellen, Abruf, Aufbereitung, Ergebnis") + spalten_svg(d["fluss"], "hoch", "fluss", "Datenfluss: Quellen, Abruf, Aufbereitung, Ergebnis"), fluss_alle, root)}
{_grafik("zeitplan", "Zeitplan", "Die Läufe starten von selbst zu festen Zeiten (Cron-Aufträge in GitHub Actions). Die Zeiten sind in UTC angegeben; in Köln ist es eine Stunde später, im Sommer zwei. Abgerufen wird nur nachts zwischen 22 und 6 Uhr.", zeit_svg, d["termine"] + d["ohne"], root, extra=f'''
      <p class="tk-ohne-titel">Ohne festen Zeitpunkt:</p>
      <ul class="tk-ohne">
{ohne}
      </ul>''')}
{_grafik("technik", "Technik", "Die Karte braucht keinen eigenen Rechner, der ständig läuft: Ein Python-Programm erzeugt jede Nacht fertige Dateien, die ein einfacher Webserver ausliefert. Im Browser zeichnet Leaflet die Karte. Tests prüfen jede Änderung, bevor sie veröffentlicht wird.", stapel_svg(d["schichten"], "breit") + stapel_svg(d["schichten"], "hoch"), stapel_alle, root)}
    <h2 id="grenzen">Grenzen</h2>
    <ul>
      <li>Diese Seite zeigt den Aufbau. Ob ein Lauf gelungen ist, zeigt GitHub: <a href="{ACTIONS}">Läufe der Workflows</a>.</li>
      <li>Einmalige Schritte, etwa das Ableiten der Geodaten (<code>python -m pipeline geo-koeln</code>), laufen nicht automatisch und fehlen im Zeitplan.</li>
      <li>Der Server der Hauptadresse übernimmt den Branch deploy von sich aus; sein Zeitpunkt steht nicht im Repository.</li>
    </ul>
    <p class="meta">Quellcode unter MIT-Lizenz: <a href="{REPO}">github.com/daimpad/ratsatlas-koeln</a> · <a href="{root}begriffe/">Begriffe</a> · <a href="{root}">Zur Karte</a></p>"""


def write(site, site_url, page):
    """Schreibt technik/index.html; gibt den Pfad für die Sitemap zurück."""
    out = site / PFAD / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site_url, PFAD, "So funktioniert der Ratsatlas – Ratsatlas Köln",
                        "Woher der Ratsatlas Köln seine Daten nimmt, wie sie jede Nacht aufbereitet werden, wann die "
                        "automatischen Läufe starten und welche Technik dahintersteht, in vier Grafiken.",
                        body(daten("../"), "../"), "../", '\n  <script src="../technik.js" defer></script>'),
                   encoding="utf-8")
    return [PFAD]
