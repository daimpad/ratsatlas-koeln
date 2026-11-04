# Mitmachen

Beiträge sind willkommen – im Hackathon „Hack den Stadtrat“ und danach.

## Grundsätze

- **Quellentreu.** Keine erfundenen Inhalte. Jede angezeigte Angabe ist auf ihr Quellobjekt rückführbar (OParl-ID, Fundstelle). Abgeleitetes trägt `method`, `confidence` und `evidence`.
- **Datenschutz.** Keine Wohnadressen oder Namen von Privatpersonen; Bürgeranträge nur auf Straßen- oder Ortsteilebene.
- **Lizenzen.** Neue Datenquellen mit Lizenz in `data/LICENSE-DATA.md` und in `pipeline/config.py` (`SOURCES`) eintragen. Code steht unter MIT.
- **Verständlich.** Die Seite richtet sich an Bürger:innen ohne Verwaltungswissen; Begriffe erklären, Barrierefreiheit (WCAG 2.1 AA) wahren.

## Ablauf

1. Issue anlegen oder ein vorhandenes übernehmen (Vorlagen: Verortung prüfen, Fehler, Idee).
2. Branch anlegen, ändern, Tests ergänzen.
3. Lokal prüfen:
   ```bash
   .venv/bin/python -m unittest discover tests
   .venv/bin/python -m pipeline build && .venv/bin/python -m pipeline export && .venv/bin/python -m pipeline check
   ```
4. Pull Request mit kurzer Beschreibung: was, warum, wie geprüft.

## Einstiegsaufgaben

- Stichprobe prüfen: `data/export/endenich/stichprobe_pruefung.tsv` gegen das Original im Ratsinformationssystem (Spalte „urteil“).
- Hinweise aus Issues mit Label `verortung` auswerten und Regeln in `pipeline/geocode.py` verbessern.
- Ideen aus `CLAUDE.md`, Abschnitt 6: Stadtteil-Abo (Atom-Feed), Sitzungskalender, Gremien- und Ämterkarte, Themen-Layer, Bebauungsplan-Flächen (WFS).
