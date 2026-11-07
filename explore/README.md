# Exploration Köln (Phase 1)

Skripte ohne Produktionscode. Rohdaten, PDFs und geladene Geodaten liegen nur in `explore/_cache/` und werden nicht versioniert.

| Skript | Zweck | Stand |
|---|---|---|
| `abruf.py` | gedrosselter Abruf: eine Verbindung, ≥ 2 s Abstand, Backoff, User-Agent, Cache, Protokoll `_cache/abrufe.tsv`, Obergrenze `RATSATLAS_MAX_ANFRAGEN`, Abbruch bei langsamer Antwort (`RATSATLAS_MAX_DAUER`) oder 429/5xx (`RATSATLAS_WIEDERHOLUNGEN=0`) | genutzt |
| `geodaten.py` | Katalog (DCAT-AP), Lizenzen, Felder und Koordinatensysteme der Kölner Geodaten → `ergebnisse/geodaten_*.tsv` | ausgeführt am 04.11.2026 |
| `oparl_messung.py` | Test, Kennzahlen, Organisationen, Stichprobe ≥ 500 Vorlagen, TOP-Ergebnisse, PDF-Köpfe; Seitengrenze je Liste; Laufprotokoll `ergebnisse/oparl_laeufe.tsv` und `oparl_listen.tsv` | **nicht ausgeführt**; gestuft nach `STUFEN.md`; läuft erst mit `RATSATLAS_STADT_INFORMIERT=ja`, nur 23–1 Uhr; `pdf-koepfe` zusätzlich erst mit `RATSATLAS_PDF_FREIGEGEBEN=ja` |
| `STUFEN.md` | Stufenplan: Befehle, Anfragen, Obergrenzen, Dauer, Abbruchkriterien | Stufe 1 freigegeben am 07.11.2026 |
| `auswertung.py` | Zusammenfassung je Stufe aus `_cache/abrufe.tsv` und `ergebnisse/` als Markdown (ohne Netz) | – |
| `testserver.py`, `probelauf.py` | lokaler OParl-Testserver mit erfundenen Daten; Probelauf aller Stufen ohne Anfrage an die Stadt (`tests/test_messstufen.py`) | – |
| `ergebnisse/fraktionen_*.tsv`, `gremien_koeln.tsv`, `bplan_quellen.tsv`, `sessionnet_befunde.tsv` | Recherche ohne Server der Stadt (Bericht Abschnitt 4) | 04.11.2026 |
| `ANFRAGE_stadt_koeln.md` | Entwurf der Anfrage an die Stadt | zur Versendung durch den Auftraggeber |

Umgebungsvariablen: `RATSATLAS_KONTAKT` (Kontakt im User-Agent), `RATSATLAS_ABSTAND` (Sekunden, Vorgabe 2), `RATSATLAS_CACHE`, `RATSATLAS_ERGEBNISSE`, `RATSATLAS_OPARL_SYSTEM`, `RATSATLAS_OPARL_BODY` (für Tests gegen einen lokalen Server).

Umgebungsvariablen der Messstufen: `RATSATLAS_MAX_ANFRAGEN` (Obergrenze je Prozess, Cache zählt nicht), `RATSATLAS_MAX_DAUER` (Sekunden), `RATSATLAS_WIEDERHOLUNGEN` (0 = Abbruch bei 429/5xx), `RATSATLAS_STUFE` (Vermerk im Laufprotokoll), `RATSATLAS_ZEITFENSTER` (Vorgabe `23-1`).

## Messstufen

Die Messung der OParl-API läuft in sechs Stufen, jede erst nach Bericht und Freigabe (Befehle und Abbruchkriterien in `STUFEN.md`). Anfragen laut Probelauf gegen den lokalen Testserver (`python3 explore/probelauf.py`), ohne Cache / mit Cache der Vorstufen:

| Stufe | Kommando | Anfragen |
|---|---|---|
| 1 | `test` | 3 / 3 |
| 2 | `kennzahlen` | 10 / 7 |
| 3 | `organisationen --seiten 4`, `stichprobe --seiten 1` | 5 + 9 / 3 + 7 |
| 4 | `sitzungen --seiten 2` | 3 / 1 |
| 5 | `stichprobe --seiten 3` (600 Vorlagen bei 25 je Seite) | 25 / 16 |
| 6 | `pdf-koepfe --anzahl 100` (erst nach Klärung) | höchstens 100 |

Zusammen höchstens 155 Anfragen über mindestens sechs Nächte. Nach jeder Stufe: `python3 explore/auswertung.py --stufe <N>`.
