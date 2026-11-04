# Phase 6 – Verifikation (Teil ohne Abruf)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` 7.6 und Entscheidungen in Abschnitt 9 · Prüfung an der mit Testdaten zusammengestellten Seite

## 1. Ergebnisse

| Prüfung | Ergebnis |
|---|---|
| Innere Links und Sprungmarken (`tools/linkpruefung.py`, 100 Seiten) | **0 defekt**. Vorher gefunden und behoben: Verweise auf abgeschaltete Seiten (`thema/`, `haushalt/`, `einfach/`) auf der Startseite, der Begriffs- und der Feedseite. Die Karten abgeschalteter Zusatzthemen entfernt `seo.py` jetzt aus der veröffentlichten Seite. |
| Äußere Links (141 Adressen geprüft, 4 nicht abgefragt) | Keine Fehler, die am Code liegen. **99 × 404** auf koeln.ratsatlas.de und **2 × 404** auf dem Pages-Spiegel sind erwartbar, weil beides noch nicht veröffentlicht ist. **6 Antworten von GitHub mit 400/403** erhält die Arbeitsumgebung bei jeder GitHub-Seite; diese Links lassen sich von hier nicht prüfen. Server der Stadt habe ich nicht abgefragt (Abrufpolitik). Behoben: Verzeichnislinks der Technikseite (`blob/` → `tree/`) und die Quellenadresse von OpenStreetMap. |
| Lizenz- und Datenschutzhinweise (`tests/test_hinweise.py`) | Jede HTML-Seite außer 404 nennt „Datenquelle: Stadt Köln – offenedaten-koeln.de“ und verlinkt Lizenzen, Impressum und Datenschutz; dafür habe ich den gemeinsamen Seitenfuß ergänzt. „Bonn“ kommt nur noch als Herkunft des Codes vor und in der Anschrift des Verantwortlichen. |
| Datenpaket | Enthält Lizenzen, LIESMICH, alle Audits (Geokodierung, Prozess, Zeit, Themen), die Stichprobe je Methode und die Abrufstatistik. Rohdaten der Schnittstelle und PDFs sind nicht enthalten (Test). |
| WCAG 2.1 AA nach den Änderungen | axe: 0 Verstöße am Desktop und in Handy-Breite. |
| Hauptlauf | `pages.yml` veröffentlicht nur nach bestandener Linkprüfung. |
| Arbeitsweise | Der eigene Skill `.claude/skills/ratsatlas-koeln/SKILL.md` ersetzt den Bonner Skill. |

Tests: 39, alle bestanden. Protokolle liegen in `inventur/phase6/`.

## 2. Offen bis nach der Information der Stadt

1. Stichprobe gegen das Kölner Ratsinformationssystem (Vorlagen, Beratungen, Ergebnisse wörtlich).
2. Prüfung der Verortung von Hand: 50 Vorlagen je Methode (`stichprobe_geokodierung.tsv`).
3. Äußere Links auf die Seiten der Stadt und in den Exporten (Feld `web`).
4. Ämtertabelle aus dem Geschäfts- und Dezernatsverteilungsplan (Entscheidung 04.11.2026: warten).
5. Live-Prüfung (`live.yml`) nach der Einrichtung in Plesk.
