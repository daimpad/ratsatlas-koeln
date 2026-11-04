---
name: allris-bonn
description: Arbeitsweise im Repository allris-bonn (RIS-Karte Bonn) – Pipeline ausführen, Daten und Seite prüfen, Konventionen zu Quellen, Lizenzen und Datenschutz, Veröffentlichung über GitHub Pages und den Branch deploy. Verwenden bei jeder Änderung an pipeline/, site/, data/ oder den Workflows.
---

# allris-bonn – Arbeitsweise

Projektauftrag, Entscheidungen und offene Punkte stehen in `CLAUDE.md` (Abschnitte 2, 8, 9). Diese Datei beschreibt, **wie** im Repository gearbeitet wird.

## Grundsätze

- **Quellentreu:** Jede angezeigte Angabe ist auf ihr Quellobjekt (OParl-ID) rückführbar. Abgeleitetes wird gekennzeichnet (`method`, `confidence`, `evidence`; Prozessschritte mit Evidenzstatus belegt / abgeleitet / nicht_öffentlich / unklar). Lücken bleiben sichtbar, nichts wird erfunden.
- **Datenschutz:** keine Wohnadressen natürlicher Personen; Bürgeranträge nur auf Straßen- oder Ortsteilebene. `python -m pipeline check` bricht ab, wenn Hausnummern in Ortsangaben auftauchen.
- **Lizenzen:** OParl-API Stadt Bonn und Geodaten der Stadt CC0; OParl-Lite (Sitzungen, TOPs, Ergebnisse) CC BY 4.0; OSM ODbL. Neue Quelle → `config.SOURCES`, `data/LICENSE-DATA.md`, README, Quellen-Akkordeon der Seite.
- **Dokumentation:** `README.md` nur inhaltlich und erklärend (für Bürger:innen, ohne Dateipfade und Befehle); Technisches (Pipeline, Dateien, URL-Parameter, Workflows, Betrieb) in `TECHNIK.md`.
- **Stabile Ausgaben:** Gebietsdateien, Feeds und Kalender tragen keine Erzeugungszeitpunkte, damit sich der Branch `deploy` nur bei Inhaltsänderungen ändert. Die Stichprobe zur Prüfung von Hand (`stichprobe_pruefung.tsv`) wird nie überschrieben.
- **Sprache:** Oberfläche, Kommentare und Commit-Nachrichten auf Deutsch, sachlich und ohne Superlative; Texte für Laien verständlich.

## Pipeline

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pipeline all            # fetch → build → export → check → verify → package
.venv/bin/python -m pipeline <schritt>      # fetch-papers | fetch-organizations | fetch-meetings | fetch-plans | fetch-lite | fetch-streets | gazetteer | build | export | check | verify | package | seo | baustellen | kandidaten | baustellen-seite
```

| Modul | Aufgabe |
|---|---|
| `fetch.py`, `net.py` | Abruf mit Wiederholung; Rohdaten in `data/raw/` (Abrufzeitpunkte in `STAND.json`) |
| `build.py` | SQLite `data/build/allris.sqlite`: Vorlagen, Beratungen, Sitzungen, TOPs, Orte, Ortsbezüge, Akteure |
| `geocode.py`, `geo.py`, `plans.py` | Stufe B (Straßen, Ortsteile, Bezirke, Bebauungspläne), Point-in-Polygon, Überschneidungen |
| `actors.py`, `process.py` | Einreichende und Zuständigkeit; Prozessschritte, Stand, Wege |
| `topics.py` | Themen (Amt, Fachausschuss, Stichwort) und Parteien je Vorlage; Themenliste mit `THEMES` in `site/app.js` abgleichen |
| `export.py`, `publish.py` | JSON je Gebiet, Zeit- und Wegeaggregate, Audits (TSV); Feeds, Kalender, GeoJSON, DCAT |
| `check.py`, `verify.py` | Kennzahlen, Datenschutz; Abgleich von Stichproben mit der OParl-API; Zip-Paket |
| `chat.py`, `glossar.py` | Daten des Ratsassistenten (`bonn/chat/`: gekürzte Vorlagen je Präfix der Drucksachennummer, Orte, Gremien, Datenstand); Glossar `data/export/glossar.json` für Seite und Assistent |

Ratsassistent (BYOK, im Aufbau; ES-Module ohne Abhängigkeiten unter `site/chat/`):
- `tools.js`: Werkzeuge über die statischen Exporte; jedes Ergebnis trägt Drucksachennummer bzw. OParl-ID, bleibt unter `MAX_CHARS` und lässt in Titeln aus der Einwohnerschaft Hausnummern aus.
- `providers.js`: Adapter für Anthropic (Header `anthropic-dangerous-direct-browser-access`, Denkblöcke werden unverändert zurückgegeben, serverseitige Ausweichmodelle bei Opus/Sonnet) und OpenAI-kompatible Dienste (Mistral, OpenRouter, lokal nur `localhost`); ohne SDK, Schlüssel nur im Header.
- `core.js`: Werkzeugschleife (höchstens 8 Aufrufe, danach `tool_choice: none`), Eingabeprüfung, Ergebnisse als abgegrenzte Daten, Verlauf nur anhängen, Quellenprüfung (`checkCitations`).
- `keys.js`: Schlüssel im Arbeitsspeicher, `sessionStorage` nur auf Wunsch, nie `localStorage`.
- `systemprompt.md` (Version und Änderungsvermerk; Text zwischen `<!-- PROMPT -->`-Markierungen) und `prompt.js` (Platzhalter aus `datenstand.json`); jede neue Fassung mit Begründung im Änderungsvermerk, Werkzeugnamen im Prompt müssen zu `tools.js` passen (Test). Entwürfe des Auftrags in `docs/`.
- `render.js` (Markdown ohne HTML, Links nur aus Werkzeugergebnissen, Drucksachen als Schaltflächen) und `ui.js` (Fläche „Assistent“ links, teilt sich den Platz mit der Liste; KI-Hinweis, Einstellungen, Quellenkarten, Protokoll; Kopplung über `window.risKarte.open(ref)` und `.context()` aus `app.js`).
- Auswertung: `eval/fragen.json` (Fragen mit Erwartungen aus den Daten), `eval/run.mjs` (Lauf mit echtem Anbieter, Schlüssel nur aus der Umgebung), `eval/score.mjs`; Ergebnisse als TSV und JSONL in `eval/ergebnisse/`. Erwartete Drucksachen werden im Test gegen den Export geprüft.
- CSP als `<meta>` in `site/index.html`: neue externe Quellen dort und in `connect-src` eintragen; CDN-Dateien mit `integrity`.

Im Repository liegen: Gremien, Ämter, Sitzungen, Wahlperioden (`data/raw/*.json`), Flächen und Straßenverzeichnis (`data/geo/`), Pilot Endenich und Audits (`data/export/`). Erzeugt und nicht eingecheckt: `data/export/bonn/`, Zip, Datenbank.

## Prüfen vor jedem Push

1. `.venv/bin/python -m unittest discover tests`, `node --check site/app.js site/timeline.js site/chat/tools.js` und `node --test "tests/js/**/*.test.mjs"` (mit vorhandenem Export auch gegen die echten Daten)
2. Bei Datenänderungen: `build`, `export`, `check`; Kennzahlen mit dem vorigen Stand vergleichen
3. Bei Oberflächenänderungen: Vorschau bauen und im Browser prüfen

```bash
mkdir -p _site/data/geo && cp -r site/. _site/ && cp -r data/export _site/data/ \
  && cp data/LICENSE-DATA.md _site/data/ && cp data/geo/*.geojson _site/data/geo/
python3 -m http.server -d _site 8765
```

   Feste Browser-Prüfung: `node --test "tests/browser/*.test.mjs"` (Seite unter `SITE`, Standard Port 8765; läuft auch im Workflow `tests.yml`). Neue Abläufe der Oberfläche dort ergänzen.
   Darüber hinaus mit Playwright (Chromium vorinstalliert) Desktop 1440 px, mittlere Breite 1024 px und Mobil 390 px prüfen; axe-core (`wcag2a`, `wcag2aa`) darf keine Verstöße melden. Typische Fälle: Gebietswechsel (auch schnell hintereinander), URL-Zustand (`?gebiet=…&von=…&bis=…&thema=…&partei=…&suche=bonn#Drucksache`), Esc und Fokus, Zeitleiste per Tastatur, Suche in der Leiste mit Chips, Mega-Menüs (öffnen, Esc, Klick außerhalb), Ziehgriffe (Maus, Pfeiltasten, gespeicherte Breite), Assistent mit nachgebildetem Anbieter (`page.route` auf den Anbieter-Endpunkt; kein echter Schlüssel nötig).

## Veröffentlichung

- Arbeitsbranch `claude/new-session-r8w4my`; nach jedem Merge von `main` neu ansetzen; jede Änderung als Pull Request.
- `.github/workflows/pages.yml`: Abruf (mit Rückfall auf den letzten Stand) → Build → Export → Prüfung → Paket → GitHub Pages und Branch `deploy` (fertige Seite plus `.htaccess`, ohne Zip).
- `SITE_URL` (Umgebungsvariable) bestimmt absolute Links in Feeds, Kalender und DCAT sowie canonical, Open Graph, strukturierte Daten, `robots.txt` und `sitemap.xml` (`python -m pipeline seo` nach dem Zusammenstellen von `_site`).
- Nach dem Merge die veröffentlichte Seite im Browser prüfen.
