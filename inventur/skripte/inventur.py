"""Inventur der übernommenen Dateien (Phase 0): Einordnung je Datei mit Begründung.

Aufruf: python3 inventur/skripte/inventur.py > inventur/inventur_module.tsv
Kategorien (Prompt v0.1, Abschnitt 7.0): generisch | anpassen (Bonn-spezifisch) | deaktivieren (Bonn-Zusatzthema) | entfernen.
Die Einordnung ist eine Vorlage zur Freigabe; Spalte „fundstellen“ zählt Zeilen aus fundstellen_bonn.tsv.
"""
import csv
import fnmatch
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G, A, D, E = "generisch", "Bonn-spezifisch, anpassen", "Bonn-Zusatzthema, deaktivieren", "entfernen"

# (Muster, Kategorie, Funktion laut 5.4 bzw. Rolle, Begründung) – erstes passendes Muster gilt
REGELN = [
    # Pipeline: Kern der ersten Auslieferung (5.4)
    ("pipeline/__init__.py", A, "Paket", "Paketbeschreibung nennt allris-bonn"),
    ("pipeline/__main__.py", A, "Aufruf", "Schrittliste enthält Bonner Schritte (fetch-lite, Baustellen, Wahlen); Köln-Schritte und Abschaltung ergänzen"),
    ("pipeline/config.py", A, "Konfiguration", "zentrale Stelle für Bonner URLs, Geodateien, Lizenzen, SITE_URL, PAKET_URL, Pilot-Ortsteil; wird Köln-Konfiguration inkl. Schaltern für Zusatzthemen"),
    ("pipeline/net.py", G, "Abruf", "HTTP mit Wiederholung, ohne Stadtbezug; für Köln um Abrufpolitik 5.1 erweitern (Abstand, Backoff bis Stunden, User-Agent)"),
    ("pipeline/fetch.py", A, "Abruf", "Bonner OParl-API und OParl-Lite (GraphQL); wird durch SessionNet-Adapter mit Paginierung über links.next ersetzt"),
    ("pipeline/build.py", A, "Datenmodell", "Normalisierung ins SQLite-Modell bleibt; Eingänge (Beratungen aus OParl-Lite, Bonner Nummernschema) auf Köln umstellen"),
    ("pipeline/actors.py", A, "Akteure", "Bonner Vorlagenarten, Titelmuster, „Co-Dezernat“; Köln: underDirectionOf bzw. PDF-Kopf „Dezernat, Dienststelle“, Ämtertabelle, § 3/§ 4-Muster"),
    ("pipeline/process.py", A, "Prozesslinie", "Schritte mit Evidenzstatus bleiben; Quelle in Köln consultation → meeting/agendaItem direkt"),
    ("pipeline/geo.py", A, "Geokodierung", "Point-in-Polygon generisch; Bezug auf 51 Bonner Ortsteile → 86 Kölner Stadtteile"),
    ("pipeline/geocode.py", A, "Geokodierung Stufe B", "Regeln und Gazetteer Bonn (OSM-Straßen); Köln: Straßenverzeichnis, Adressen, Straßenschlüssel, Bezirkszusatz"),
    ("pipeline/plans.py", A, "Geokodierung Stufe B", "Bonner B-Plan-Quelle und Nummernschema; Köln-Schema in Phase 1 verifizieren"),
    ("pipeline/volltext.py", A, "Geokodierung Volltext", "Volltexte in Bonn aus OParl-Lite; in Köln nur aus PDFs (Abrufrisiko, Lizenzregel 2)"),
    ("pipeline/stufe_c.py", A, "Geokodierung Stufe C", "Verfahren übernehmbar; Verifikation gegen Kölner Gazetteer"),
    ("pipeline/objekte.py", A, "Geokodierung Stufe C", "OSM-Gebäude und Anlagen für Bonn; Ausschnitt Köln, ODbL getrennt kennzeichnen"),
    ("pipeline/maske.py", G, "Datenschutz", "Hausnummern in Titeln aus der Einwohnerschaft ausblenden; ohne Stadtbezug"),
    ("pipeline/sprachmodell.py", G, "Sprachmodell", "Aufruf Mistral/Anthropic ohne Stadtbezug"),
    ("pipeline/topics.py", A, "Filter Themen/Parteien", "Themen aus Bonner Ämtern und Ausschüssen; Parteien/Fraktionen für Köln (Wahlperiode ab 2025)"),
    ("pipeline/export.py", A, "Export", "Pilot-Ortsteil Endenich, Pfad export/bonn, Ortsteil-Gliederung; Köln: ganze Stadt, Stadtteile/Stadtbezirke"),
    ("pipeline/flaechen.py", A, "Gebiete", "vereinfachte Flächen; Pfade und Gebietsebenen auf Köln"),
    ("pipeline/gebietsseiten.py", A, "Gebiete", "statische Seiten je Ortsteil/Bezirk; Köln: 86 Stadtteile, 9 Stadtbezirke"),
    ("pipeline/gebietszahlen.py", A, "Startansicht", "Kennzahlen je Gebiet für die Übersichtskarte"),
    ("pipeline/publish.py", A, "Feeds, Datenpaket", "Atom, iCalendar, GeoJSON, DCAT mit Bonner Adressen und Lizenztexten"),
    ("pipeline/rssseite.py", A, "Feeds", "Seite rss/ mit Bonner Beispielen"),
    ("pipeline/seo.py", A, "Auffindbarkeit", "robots, sitemap, canonical; Canonical des Pages-Spiegels auf koeln.ratsatlas.de"),
    ("pipeline/glossar.py", A, "Verstehen", "Begriffe mit Bonner Gremien und Verfahren; Köln: Bezirksvertretungen, § 24 GO, Ausschuss BAB"),
    ("pipeline/begriffsseite.py", A, "Verstehen", "Seite begriffe/; Texte auf Köln"),
    ("pipeline/technikseite.py", A, "Verlässlichkeit", "Seite technik/ mit Bonner Quellen und Zahlen"),
    ("pipeline/check.py", A, "Prüfung", "Kennzahlen gegen den Bonner Phase-0-Bericht; Datenschutzprüfung generisch"),
    ("pipeline/verify.py", A, "Verifikation", "Stichprobe gegen Bonner OParl-API, Haltestellen; auf Kölner RIS umstellen (Phase 6)"),
    ("pipeline/besetzung.py", D, "Akteure (Gremien)", "Mitgliedschaften aus Bonner OParl; zweiter Lauf (Entscheidung 04.11.2026), zusätzliche Abrufe gegen Abrufpolitik abwägen"),
    ("pipeline/einfachseite.py", D, "Verstehen (Einfache Sprache)", "nicht in 5.4; zweiter Lauf (Entscheidung 04.11.2026)"),
    ("pipeline/kurzfassung.py", D, "Kurzfassungen", "laut 2. zulässig, nicht in 5.4; zweiter Lauf (Entscheidung 04.11.2026), braucht Volltexte"),
    ("pipeline/chat.py", D, "Ratsassistent", "Daten für den Chat (5.4: deaktivieren)"),
    ("pipeline/anliegen.py", D, "Mängelmelder Bonn", "Archiv des Bonner Anliegenmelders, ohne Kölner Pendant"),
    ("pipeline/baustellen.py", D, "Baustellen", "Bonner Baustellenfeeds (5.4: deaktivieren)"),
    ("pipeline/kandidaten.py", D, "Baustellen", "Abgleich Beschluss ↔ Baustelle, hängt an baustellen.py"),
    ("pipeline/haushaltsplan.py", D, "Haushalt", "liest Bonner Haushaltspläne (PDF) (5.4: deaktivieren)"),
    ("pipeline/haushaltsseite.py", D, "Haushalt", "Seite haushalt/ (5.4: deaktivieren)"),
    ("pipeline/wahlen.py", D, "Wahlen", "Kommunalwahl 2025 Bonn (5.4: deaktivieren)"),
    ("pipeline/kontext.py", D, "Kontextdaten", "Kennzahlen je Bonner Ortsteil (Bodenrichtwerte, Kitas, Klima); nicht in 5.4"),
    ("pipeline/soll.py", D, "Soll-Modell", "Verfahren nach Bonner Zuständigkeitsordnung („Bonn entscheidet“); Daten nicht übernommen"),
    ("pipeline/prozessarten.py", D, "Reiter Prozesse", "Verfahrensarten aus dem Bonner Soll-Modell"),
    ("pipeline/dossier.py", D, "Themenseiten", "Themenseiten (5.4: deaktivieren)"),
    ("pipeline/prozessbild.py", D, "Themenseiten", "Prozessbild der Themenseiten"),
    ("pipeline/themenseiten/*", D, "Themenseiten", "Regeln und Texte je Bonner Thema"),
    ("pipeline/kacheln/*", A, "Kartenkacheln", "graue Kacheln aus OSM für Bonner Ausschnitt; Rahmen auf Kölner Stadtgebiet (5.4)"),
    # Seite
    ("site/app.js", A, "Karte, Liste, Vorgang, Suche", "Hauptanwendung; Bonner Texte, Gebiete, Pfade, Startansicht"),
    ("site/index.html", A, "Seite", "Marke, Texte, Quellenhinweise, Bonner Adressen"),
    ("site/404.html", A, "Seite", "Marke und Adressen"),
    ("site/datenschutz.html", A, "Datenschutz", "Bonner Quellen und Adressen; Impressum/Datenschutz für koeln.ratsatlas.de"),
    ("site/site.webmanifest", A, "Seite", "Name „Ratsatlas Bonn“"),
    ("site/tour.js", A, "Einführung", "Tour mit Bonner Texten"),
    ("site/timeline.js", A, "Prozesslinie", "Modul generisch, aber Bonner Pilot-Gremien als Konstanten (PILOT_GREMIEN)"),
    ("site/style.css", G, "Gestaltung", "Glass-Stil und Tokens bleiben (2.); nur Kommentare nennen Bonn"),
    ("site/page.css", G, "Gestaltung", "Textseiten, ohne Stadtbezug"),
    ("site/rss.js", G, "Feeds", "Kopierknöpfe, ohne Stadtbezug"),
    ("site/technik.js", G, "Verlässlichkeit", "Interaktion der Technikseite, ohne Stadtbezug"),
    ("site/beteiligung.js", D, "Mitmachen", "„Mitmachen in Bonn“; zweiter Lauf (Entscheidung 04.11.2026) mit Kölner Instrumenten (§ 24 GO, Einwohnerfragestunde, Meinung für Köln)"),
    ("site/haushalt.js", D, "Haushalt", "Seite haushalt/"),
    ("site/thema.js", D, "Themenseiten", "Themenseiten"),
    ("site/mitwirken.js", D, "Soll-Modell", "Einflussregeln aus „Bonn entscheidet“"),
    ("site/prozesse.js", D, "Reiter Prozesse", "Verfahrensarten aus dem Bonner Soll-Modell"),
    ("site/chat/*", D, "Ratsassistent", "Chat (5.4: deaktivieren)"),
    ("site/fonts/*", G, "Gestaltung", "Inter lokal mit Lizenz"),
    ("site/vendor/*", G, "Karte", "Leaflet und Markercluster mit Lizenzen"),
    ("site/favicon.svg", G, "Marke", "Ortsmarke ohne Stadtbezug; nur Kommentar nennt Bonn"),
    ("site/og-image.jpg", D, "Marke", "Bonner Vorschaubild; Kölner Bild im zweiten Lauf (Entscheidung 04.11.2026), bis dahin nicht ausliefern"),
    ("site/*.png", G, "Marke", "Symbole aus der Ortsmarke"),
    ("site/favicon.ico", G, "Marke", "Symbol aus der Ortsmarke"),
    # Betrieb
    ("deploy/htaccess", A, "Deployment", "Apache-Regeln für Plesk; Pfade export/bonn"),
    (".github/workflows-inaktiv/pages.yml", A, "Deployment", "Hauptlauf (Abruf, Build, Branch deploy, Pages); auf Köln und Abrufpolitik umstellen, Phase 5"),
    (".github/workflows-inaktiv/live.yml", A, "Deployment", "Erreichbarkeit Hauptadresse/Pages; Adressen auf Köln"),
    (".github/workflows-inaktiv/tests.yml", A, "Tests", "Tests nicht übernommen (Bonner Testdaten); für Köln neu aufbauen"),
    (".github/workflows-inaktiv/kacheln.yml", A, "Kartenkacheln", "Kachelerzeugung; Ausschnitt Köln"),
    (".github/workflows-inaktiv/quellen.yml", A, "Abruf Quelldateien", "Bonner Quellen (wahlen.bonn.de, stadtplan.bonn.de); Muster ggf. für Kölner Geodaten"),
    (".github/workflows-inaktiv/release.yml", G, "Release", "Release auf Knopfdruck; docs/releases fehlt noch"),
    (".github/workflows-inaktiv/baustellen.yml", D, "Baustellen", "täglicher Abruf der Bonner Baustellen"),
    (".github/workflows-inaktiv/eval.yml", D, "Ratsassistent", "Auswertung des Chats; eval/ nicht übernommen"),
    (".github/workflows-inaktiv/static.yml", E, "Deployment", "Vorlage, die das ganze Repository auf Pages stellt; ersetzt durch pages.yml"),
    (".github/ISSUE_TEMPLATE/config.yml", A, "Mitwirkung", "Kontaktlink „Ratsatlas Bonn“"),
    (".github/ISSUE_TEMPLATE/idee.yml", A, "Mitwirkung", "verweist auf Bonner Ideenliste in CLAUDE.md"),
    (".github/ISSUE_TEMPLATE/*", G, "Mitwirkung", "Vorlagen ohne Stadtbezug"),
    (".claude/skills/allris-bonn/SKILL.md", A, "Arbeitsweise", "wird zu .claude/skills/ratsatlas-koeln/SKILL.md (2.)"),
    ("CLAUDE.md", E, "Arbeitsweise", "Bonner Auftrag entfernt; am 04.11.2026 ersetzt durch Prompt ratsatlas-koeln v0.1 mit Entscheidungen (Abschnitt 9); verbleibende Fundstellen sind Verweise auf die Bonner Vorlage"),
    ("README.md", A, "Dokumentation", "Bonner Inhalt; Neufassung in Phase 5 (Herkunft, Quellen, Lizenzen, Grenzen)"),
    ("TECHNIK.md", A, "Dokumentation", "Bonner Pipeline und Betrieb; mit den Phasen fortschreiben"),
    ("CONTRIBUTING.md", G, "Dokumentation", "Grundsätze generisch; Hackathon-Bezug prüfen"),
    ("LICENSE", G, "Lizenz", "MIT, Damian Paderta 2026"),
    ("requirements.txt", G, "Abhängigkeiten", "shapely, pyproj, pyshp"),
    (".gitignore", A, "Repository", "Bonner Pfade (data/export/bonn, allris-bonn-export.zip)"),
    ("NOTICE", G, "Herkunft", "neu: Herkunft aus allris-test @9eea7ea"),
]


def main():
    fund = Counter()
    with open(ROOT / "inventur" / "fundstellen_bonn.tsv", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            fund[row["datei"]] += 1
    w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    w.writerow(["datei", "zeilen", "kategorie", "funktion", "begruendung", "fundstellen"])
    offen = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if not p.is_file() or rel.startswith((".git/", "inventur/", "explore/")):
            continue
        regel = next((r for r in REGELN if fnmatch.fnmatch(rel, r[0])), None)
        if regel is None:
            offen.append(rel)
            continue
        try:
            zeilen = len(p.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            zeilen = ""
        w.writerow([rel, zeilen, regel[1], regel[2], regel[3], fund.get(rel, 0)])
    if offen:
        sys.exit("ohne Einordnung: " + ", ".join(offen))


if __name__ == "__main__":
    main()
