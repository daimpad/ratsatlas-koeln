# Mitmachen

Beiträge sind willkommen. Der Ratsatlas Köln beruht auf dem Ratsatlas Bonn ([daimpad/ratsatlas-bonn](https://github.com/daimpad/ratsatlas-bonn)).

## Grundsätze

- **Quellentreu.** Keine erfundenen Inhalte. Jede angezeigte Angabe ist auf ihr Quellobjekt rückführbar (OParl-ID, Fundstelle). Abgeleitetes trägt `method`, `confidence` und `evidence`.
- **Datenschutz.** Keine Wohnadressen oder Namen von Privatpersonen; Anregungen und Beschwerden nach § 24 GO NRW nur auf Straßen- oder Stadtteilebene. Hauskoordinaten nur bei Verwaltungsvorlagen sowie politischen Anträgen und Anfragen mit erkennbarer Vorlagenart.
- **Abrufpolitik.** Keine Abrufe der Kölner OParl-API außerhalb von `pipeline/abruf.py` (eine Verbindung, mindestens 2 s Abstand, nur im Zeitfenster 23–1 Uhr, gesperrt ohne `RATSATLAS_STADT_INFORMIERT=ja`).

## Ablauf

1. Issue anlegen oder ein vorhandenes übernehmen (Vorlagen: Verortung prüfen, Fehler, Idee).
2. Branch anlegen, ändern, Tests ergänzen.
3. Lokal prüfen, ohne Abruf der Stadt (synthetische Testdaten, nie veröffentlichen):
   ```bash
   pip install -r requirements.txt pytest
   python -m pytest tests
   python tools/testdaten.py && python -m pipeline build && python -m pipeline export
   python tools/seite_bauen.py && python -m http.server -d _site 8000
   ```
   In GitHub Actions laufen bei jedem Pull Request zwei Jobs (`.github/workflows/tests.yml`): „test“ (pytest, Syntax aller Skripte) und „browser“ (Seite mit Testdaten, Prüfungen in `tests/browser/` und `tools/wcag_pruefen.js` mit Playwright und axe-core in festen Versionen, ohne Netz). Lokal (im Wurzelverzeichnis): `(cd tests/browser && npm ci --ignore-scripts && ./node_modules/.bin/playwright install --only-shell chromium)` (`npm ci` allein lädt keinen Browser), danach ohne Netz wie im Job (`HTTP_PROXY`, `HTTPS_PROXY` und `ALL_PROXY` auf `http://127.0.0.1:9`, `NO_PROXY=127.0.0.1,localhost`, ebenso in Kleinbuchstaben; `RATSATLAS_SPERRE` auf einen eigenen leeren Ordner) die Seite mit Testdaten unter `http://127.0.0.1:8790/` bereitstellen, dann mit `NODE_PATH=$PWD/tests/browser/node_modules` und `AXE_PFAD=$PWD/tests/browser/node_modules/axe-core/axe.min.js` etwa `node tests/browser/gremien.js http://127.0.0.1:8790/`; die ganze Folge steht in `TECHNIK.md` („Browserprüfungen in CI“). Die Themenseiten prüft ein zweiter Bau mit Testdaten; die Freigabe im Repository bleibt dabei aus, der Prüfschalter `RATSATLAS_THEMEN_PRUEFUNG` wirkt nur mit Testdaten (in derselben Umgebung ohne Netz, im Wurzelverzeichnis):
   ```bash
   python tools/testdaten.py --themen
   export RATSATLAS_THEMEN_PRUEFUNG=verkehr
   python -m pipeline build && python -m pipeline export && python -m pipeline kontext && python -m pipeline ebenen
   python -m pipeline check && python -m pipeline package
   python tools/seite_bauen.py _site_themen && python tools/linkpruefung.py _site_themen
   python -m http.server --bind 127.0.0.1 8791 -d _site_themen &
   NODE_PATH=$PWD/tests/browser/node_modules AXE_PFAD=$PWD/tests/browser/node_modules/axe-core/axe.min.js \
     node tests/browser/themen.js http://127.0.0.1:8791/   # mit FOTOS=<Ordner> auch Bildschirmfotos
   ```
   Danach den Server beenden und `RATSATLAS_THEMEN_PRUEFUNG` wieder entfernen (`unset`); `_site_themen/` ist nicht versioniert.
   Prüfbogen einer Themenseite mit echten Vorlagen, ohne Netz und ohne Datenbank (vor jeder Freigabe eines Themas): ein Datenpaket (`ratsatlas-koeln-export.zip`) in einen eigenen leeren Ordner außerhalb des Repositorys entpacken, dann `python3 -I tools/themen_pruefbogen.py <Ordner> verkehr <Ausgabeordner außerhalb des Repositorys>`. Das Werkzeug schreibt nur dorthin (laufende Nummer statt Drucksache, Titel maskiert, Eingaben ohne Titel); die Schlüsseldatei mit den Drucksachen dient nur zum Nachschlagen. Nichts davon ins Repository übernehmen (`TECHNIK.md`, „Themenseiten“).
4. Pull Request mit kurzer Beschreibung: was, warum, wie geprüft.

## Einstiegsaufgaben

- Stichprobe prüfen: `data/export/stichprobe_geokodierung.tsv` (entsteht beim Export; veröffentlicht nur im Datenpaket) gegen das Original im Ratsinformationssystem, Spalte „urteil“ – sobald echte Kölner Daten vorliegen.
- Schreibvarianten Kölner Stadtteile und Straßen in `pipeline/geocode.py` ergänzen (mit Test in `tests/test_geokodierung.py`).
- Offene Punkte aus `CLAUDE.md`, Abschnitt 8.
