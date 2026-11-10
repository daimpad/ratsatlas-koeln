# Mitmachen

Beiträge sind willkommen. Der Ratsatlas Köln beruht auf dem Ratsatlas Bonn ([daimpad/ratsatlas-bonn](https://github.com/daimpad/ratsatlas-bonn)).

## Grundsätze

- **Quellentreu.** Keine erfundenen Inhalte. Jede angezeigte Angabe ist auf ihr Quellobjekt rückführbar (OParl-ID, Fundstelle). Abgeleitetes trägt `method`, `confidence` und `evidence`.
- **Datenschutz.** Keine Wohnadressen oder Namen von Privatpersonen; Anregungen und Beschwerden nach § 24 GO NRW nur auf Straßen- oder Stadtteilebene. Hauskoordinaten nur bei Verwaltungsvorlagen und politischen Anträgen.
- **Abrufpolitik.** Keine Abrufe der Kölner OParl-API außerhalb von `pipeline/abruf.py` (eine Verbindung, Absta## Ablauf

1. Issue anlegen oder ein vorhandenes übernehmen (Vorlagen: Verortung prüfen, Fehler, Idee).
2. Branch anlegen, ändern, Tests ergänzen.
3. Lokal prüfen, ohne Abruf der Stadt (synthetische Testdaten, nie veröffentlichen):
   ```bash
   pip install -r requirements.txt pytest
   python -m pytest tests
   python tools/testdaten.py && python -m pipeline build && python -m pipeline export
   python tools/seite_bauen.py && python -m http.server -d _site 8000
   ```
4. Pull Request mit kurzer Beschreibung: was, warum, wie geprüft.

## Einstiegsaufgaben

- Stichprobe prüfen: `data/export/stichprobe_geokodierung.tsv` (entsteht beim Export; veröffentlicht nur im Datenpaket) gegen das Original im Ratsinformationssystem, Spalte „urteil“ – sobald echte Kölner Daten vorliegen.
- Schreibvarianten Kölner Stadtteile und Straßen in `pipeline/geocode.py` ergänzen (mit Test in `tests/test_geokodierung.py`).
- Offene Punkte aus `CLAUDE.md`, Abschnitt 8.
