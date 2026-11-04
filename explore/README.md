# Exploration Köln (Phase 1)

Skripte ohne Produktionscode. Rohdaten, PDFs und geladene Geodaten liegen nur in `explore/_cache/` und werden nicht versioniert.

| Skript | Zweck | Stand |
|---|---|---|
| `abruf.py` | gedrosselter Abruf: eine Verbindung, ≥ 2 s Abstand, Backoff, User-Agent, Cache, Protokoll `_cache/abrufe.tsv` | genutzt |
| `geodaten.py` | Katalog (DCAT-AP), Lizenzen, Felder und Koordinatensysteme der Kölner Geodaten → `ergebnisse/geodaten_*.tsv` | ausgeführt am 04.11.2026 |
| `oparl_messung.py` | Kennzahlen, Organisationen, Stichprobe ≥ 500 Vorlagen, TOP-Ergebnisse, PDF-Köpfe | **nicht ausgeführt**; läuft erst mit `RATSATLAS_STADT_INFORMIERT=ja` |
| `ANFRAGE_stadt_koeln.md` | Entwurf der Anfrage an die Stadt | zur Versendung durch den Auftraggeber |

Umgebungsvariablen: `RATSATLAS_KONTAKT` (Kontakt im User-Agent), `RATSATLAS_ABSTAND` (Sekunden, Vorgabe 2), `RATSATLAS_CACHE`, `RATSATLAS_ERGEBNISSE`, `RATSATLAS_OPARL_SYSTEM`, `RATSATLAS_OPARL_BODY` (für Tests gegen einen lokalen Server).

Geschätzter Umfang von `oparl_messung.py` mit den Vorgaben: Kennzahlen etwa 10 Anfragen; Organisationen eine Anfrage je Seite; Stichprobe 8 Jahre × 3 Seiten = 24 Anfragen (etwa 600 Vorlagen bei 25 je Seite); Sitzungen 3 Anfragen; PDF-Köpfe 100 Dateien. Insgesamt etwa 150–200 Anfragen, bei 2 s Abstand also unter 10 Minuten.
