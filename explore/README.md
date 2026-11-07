# Exploration Köln (Phase 1)

Skripte ohne Produktionscode. Rohdaten, PDFs und geladene Geodaten liegen nur in `explore/_cache/` und werden nicht versioniert.

| Skript | Zweck | Stand |
|---|---|---|
| `abruf.py` | gedrosselter Abruf: eine Verbindung, ≥ 2 s Abstand nach Ende der Antwort, auch vor der ersten Anfrage eines Prozesses (ab Start und ab der letzten Netzanfrage im Protokoll), Backoff, User-Agent, Cache, Protokoll `_cache/abrufe.tsv` (Zeit mit Zone), Obergrenze `RATSATLAS_MAX_ANFRAGEN`, Abbruch bei langsamer Antwort (`RATSATLAS_MAX_DAUER`), 429/5xx (`RATSATLAS_WIEDERHOLUNGEN=0`) oder Weiterleitung (nicht verfolgt, Ziel im Protokoll); Ablehnung durch den Proxy der Arbeitsumgebung (CONNECT-Antwort 403/405/407, HTTP 407) als eigene Art `proxy` (keine Antwort des Servers, keine Sperre); CONNECT-Antwort 502/504 (Proxy erreicht den Server nicht) wie ein Verbindungsabbruch als mögliche Sperre, 429/503 als `server` ohne Wiederholung | genutzt |
| `geodaten.py` | Katalog (DCAT-AP), Lizenzen, Felder und Koordinatensysteme der Kölner Geodaten → `ergebnisse/geodaten_*.tsv`; Weiterleitungen werden nicht verfolgt (seit 07.11.2026, über `abruf.py`); erzwingt vor der ersten Anfrage dieselben Mindestwerte wie die OParl-Messung (Abstand ≥ 2 s, keine Wiederholung); nach möglicher Sperre, 429/5xx, Ablehnung durch den Proxy oder Obergrenze endet der ganze Lauf, die Ergebnisdateien bleiben unverändert | ausgeführt am 04.11.2026 (damals folgte der Abruf Weiterleitungen noch) |
| `oparl_messung.py` | Test, Kennzahlen, Organisationen, Stichprobe ≥ 500 Vorlagen, TOP-Ergebnisse, PDF-Köpfe; Seitengrenze je Liste; Laufprotokoll `ergebnisse/oparl_laeufe.tsv` und `oparl_listen.tsv` | **nicht ausgeführt**; gestuft nach `STUFEN.md`; läuft erst mit `RATSATLAS_STADT_INFORMIERT=ja`, nur 23–1 Uhr; `pdf-koepfe` zusätzlich erst mit `RATSATLAS_PDF_FREIGEGEBEN=ja` |
| `STUFEN.md` | Stufenplan: Befehle, Anfragen, Obergrenzen, Dauer, Abbruchkriterien | Stufe 1 freigegeben am 07.11.2026 |
| `auswertung.py` | Zusammenfassung je Stufe aus `_cache/abrufe.tsv` und `ergebnisse/` als Markdown (ohne Netz) | – |
| `testserver.py`, `probelauf.py` | lokaler OParl-Testserver mit erfundenen Daten; Probelauf aller Stufen ohne Anfrage an die Stadt (`tests/test_messstufen.py`) | – |
| `ergebnisse/fraktionen_*.tsv`, `gremien_koeln.tsv`, `bplan_quellen.tsv`, `sessionnet_befunde.tsv` | Recherche ohne Server der Stadt (Bericht Abschnitt 4) | 04.11.2026 |
| `ANFRAGE_stadt_koeln.md` | Entwurf der Anfrage an die Stadt | zur Versendung durch den Auftraggeber |

Weiterleitungen (HTTP 3xx) werden nicht verfolgt (`abruf.py`, damit auch `geodaten.py` und `oparl_messung.py`): Jede Weiterleitung zählt als eine Anfrage, steht mit Ziel in `_cache/abrufe.tsv` (Spalte `ziel`) und bricht den Abruf dieser Adresse ab: `oparl_messung.py` beendet damit den ganzen Lauf; `geodaten.py` vermerkt sie beim betroffenen Katalog bzw. bei der betroffenen Datei und setzt mit den übrigen Datensätzen fort.

Umgebungsvariablen: `RATSATLAS_KONTAKT` (Kontakt im User-Agent), `RATSATLAS_ABSTAND` (Sekunden, Vorgabe 2; für Anfragen an die Stadt in `oparl_messung.py` und `geodaten.py` mindestens 2), `RATSATLAS_CACHE`, `RATSATLAS_ERGEBNISSE`, `RATSATLAS_OPARL_SYSTEM`, `RATSATLAS_OPARL_BODY` (für Tests gegen einen lokalen Server).

Umgebungsvariablen der Messstufen: `RATSATLAS_MAX_ANFRAGEN` (Obergrenze je Prozess, Cache zählt nicht), `RATSATLAS_MAX_DAUER` (Sekunden), `RATSATLAS_WIEDERHOLUNGEN` (0 = Abbruch bei 429/5xx), `RATSATLAS_STUFE` (Vermerk im Laufprotokoll), `RATSATLAS_ZEITFENSTER` (Vorgabe `23-1`). Für Anfragen an die Stadt erzwingt `oparl_messung.py` Wiederholungen 0, höchstens 5 s je Antwort und mindestens 2 s Abstand und verlangt Obergrenze und Kontakt (ohne Platzhalter; in den Befehlen von `STUFEN.md` `contact@nozilla.de`).

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

Zusammen höchstens 155 Anfragen über mindestens sechs Nächte, dazu die optionale Ergänzung in Stufe 4 (`organisationen` bis zum Ende der Liste, totalPages + 1 Anfragen). Obergrenzen ohne Reserve: Reicht eine nicht, bricht die Stufe ab und wird berichtet. Nach jeder Stufe: `python3 explore/auswertung.py --stufe <N>`. Die Stichprobendatei für Stufe 6 (`_cache/stichprobe_vorlagen.jsonl`, ohne File-Objekte) bleibt im Cache.
