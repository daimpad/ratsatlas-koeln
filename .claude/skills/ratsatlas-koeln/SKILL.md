---
name: ratsatlas-koeln
description: Arbeitsweise im Repository ratsatlas-koeln (Ratsatlas Köln) – Abrufpolitik und Sperre der Kölner OParl-API, Pipeline mit Testdaten ausführen, Seite bauen und prüfen (Tests, Browser, axe), Konventionen zu Quellen, Lizenzen, Datenschutz und Hauskoordinaten, Veröffentlichung über Branch deploy und GitHub Pages. Verwenden bei jeder Änderung an pipeline/, site/, data/, tools/ oder den Workflows.
---

# ratsatlas-koeln – Arbeitsweise

Auftrag, Entscheidungen und offene Punkte stehen in `CLAUDE.md` (Abschnitte 2, 8, 9). Technik: `TECHNIK.md`. Abgeleitet aus dem Skill des Ratsatlas Bonn (`daimpad/ratsatlas-bonn`). Diese Datei beschreibt, **wie** im Repository gearbeitet wird.

## Grundsätze

- **Phasen:** Vor jeder Phase (CLAUDE.md 7) einen kurzen Plan vorlegen und auf Freigabe warten; jede Entscheidung des Auftraggebers mit Datum in CLAUDE.md Abschnitt 9 eintragen.
- **Quellentreu:** Jede angezeigte Angabe ist auf ihr Quellobjekt (OParl-ID) rückführbar. Abgeleitetes trägt `method`, `confidence`, `evidence`; Prozessschritte haben einen Evidenzstatus. Keine erfundenen URLs, Feldnamen oder Zahlen; Ungemessenes als offen kennzeichnen.
- **Abruf der Stadt:** Anfragen an Server der Stadt Köln nur über `pipeline/abruf.py` (eine Verbindung, ≥ 2 s Abstand, Zeitfenster 22–6 Uhr, Backoff bis Stunden, User-Agent mit Projektadresse). Gesperrt ohne `RATSATLAS_STADT_INFORMIERT=ja` (Repository-Variable). Aus der Arbeitsumgebung nie ohne ausdrückliche Freigabe abrufen, auch nicht einzelne Dateien von stadt-koeln.de oder offenedaten-koeln.de.
- **Datenschutz:** keine Wohnadressen natürlicher Personen. Hauskoordinaten (`strasse+hausnummer_punkt`) nur bei Verwaltungsvorlagen und politischen Anträgen (`geocode.hausnummer_punkt_erlaubt`), nie bei Anregungen und Beschwerden nach § 24 GO NRW oder Beratungen im Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden.
- **Volltexte:** bis zur Lizenzklärung keine Zitate, Auszüge oder PDFs im Repository, auf der Seite oder im Datenpaket.
- **Lizenzen:** Namensnennung „Datenquelle: Stadt Köln – offenedaten-koeln.de“ überall (`config.NAMENSNENNUNG`). Neue Quelle → `config.SOURCES`, `data/LICENSE-DATA.md`, README, Quellenzeile in `site/index.html`, Erklärung in `pipeline/technikseite.py` (Test `tests/test_workflows.py`).
- **Zusatzthemen aus Bonn:** bleiben im Code, abgeschaltet über `config.ZUSATZTHEMEN` (Pipeline) und `data-funktion` (Seite). Freigabe einzeln durch den Auftraggeber.
- **Testdaten:** `tools/testdaten.py` erzeugt erfundene Vorlagen („[Testdaten]“, `example.invalid`) nur für Entwicklung und Prüfung; nie veröffentlichen (`pages.yml` bricht ab).
- **Dokumentation:** `README.md` inhaltlich für Bürger:innen; Technisches in `TECHNIK.md`; Berichte je Phase in `inventur/BERICHT_phase*.md`, Ergebnisse je Phase als Zip-Paket, Audits als TSV.
- **Sprache:** Oberfläche, Kommentare und Commit-Nachrichten auf Deutsch, sachlich und ohne Superlative; „Stadtteil“ (nicht „Ortsteil“) in allem, was Leser:innen sehen. Interne Namen aus Bonn (`ortsteil_bez`, `BONN` als Pfadkonstante) bleiben bis zum gemeinsamen Kern.

## Pipeline

```bash
pip install -r requirements.txt pytest
python tools/testdaten.py          # nur lokal, ohne Abruf
python -m pipeline build && python -m pipeline export && python -m pipeline package
python tools/seite_bauen.py && python -m http.server -d _site 8765
```

| Modul | Aufgabe |
|---|---|
| `abruf.py`, `sessionnet.py` | Abrufpolitik; SessionNet-Adapter ins Bonner Rohdatenformat, inkrementell, Abrufstatistik; Sperre und Zeitfenster gelten als „übersprungen“ |
| `geodaten.py` | Stadtteile, Stadtbezirke, Straßen- und Hausnummernverzeichnis aus den Kölner Geodaten (`python -m pipeline geo-koeln`) |
| `build.py`, `geocode.py`, `geo.py` | SQLite, Stufe A (`subLocality`), Stufe B (Straßen, Stadtteile, eindeutige Bezirksformen, Hausnummern), `district_from_committee` |
| `actors.py`, `process.py`, `topics.py` | Einreichende, Prozessschritte, Themen |
| `export.py`, `publish.py`, `paket.py` | Exporte `data/export/koeln/`, Feeds, Kalender, GeoJSON, DCAT, Audits, Datenpaket |
| `seo.py` und Seitenmodule | Gebiets-, Begriffs-, Feed- und Technikseite, Adressen aus `SITE_URL` |

## Prüfen vor jedem Push

1. `python -m pytest tests` (lokaler OParl-Testserver, keine Anfragen an die Stadt) und `node --check` für `site/app.js`, `site/timeline.js`, `site/tour.js`.
2. Bei Änderungen an Verortung oder Akteuren: Tests mit erfundenen Titeln in `tests/test_geokodierung.py` ergänzen.
3. Bei Oberflächenänderungen: Seite mit Testdaten bauen, mit Playwright (Chromium vorinstalliert) bei 1400 px und Telefon prüfen; `tools/wcag_pruefen.js` (axe-core, WCAG 2.1 A/AA) darf keine Verstöße melden; Tab-Reihenfolge und sichtbarer Fokus.
4. `python tools/linkpruefung.py _site` meldet keine defekten inneren Links.

## Veröffentlichung

- Arbeitsbranch laut Sitzung; nach jedem Merge von `main` neu ansetzen; jede Änderung als Pull Request, Zusammenführen nur auf Wunsch des Auftraggebers.
- `.github/workflows/pages.yml`: Abruf (gesperrt bis zur Freigabe) → Build → Export → Paket → Seite → Branch `deploy` (ohne Zip, mit `.htaccess`) und Spiegel auf GitHub Pages mit Canonical auf `SITE_URL`.
- `kacheln.yml`: graue Kacheln im Branch `kacheln`; `live.yml` erst nach der Einrichtung in Plesk regelmäßig (`docs/PLESK.md`).
- Keine Zugangsdaten im Repository; Plesk richtet der Auftraggeber ein.
