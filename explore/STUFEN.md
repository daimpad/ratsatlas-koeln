# Messstufen der Kölner OParl-API

Stand 07.11.2026. Grundlage: mündliche Einwilligung der Stadt Köln (CLAUDE.md, Abschnitt 9, 07.11.2026). Abrufe nur sehr vorsichtig und gestuft, jede Stufe erst nach Bericht und Freigabe, höchstens eine Stufe je Nacht, nur 23–1 Uhr Ortszeit. Aus GitHub Actions wird nicht abgerufen (`RATSATLAS_STADT_INFORMIERT` bleibt als Repository-Variable ungesetzt).

## Für jede Stufe

Vor jeder Stufe in derselben Shell:

```bash
export RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="<Kontaktadresse des Auftraggebers>" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5
```

- Eine Verbindung, mindestens 2 s Abstand (Vorgabe von `explore/abruf.py`), User-Agent mit Projektadresse und Kontakt.
- `RATSATLAS_MAX_ANFRAGEN` gilt je Prozess und zählt nur Anfragen ans Netz; Antworten aus `explore/_cache/` zählen nicht. Die Obergrenze ist die Zahl ohne Cache und deckt damit auch eine neue Arbeitsumgebung ab.
- Nach der Stufe: `python3 explore/auswertung.py --stufe <N>` (Markdown) für den Bericht. Die TSVs in `explore/ergebnisse/` werden versioniert, `explore/_cache/` nicht. Stufe 5 überschreibt die Stichprobendateien aus Stufe 3; `oparl_laeufe.tsv` und `oparl_listen.tsv` werden fortgeschrieben.
- Die Anfragezahlen stammen aus dem Probelauf gegen den lokalen Testserver (`python3 explore/probelauf.py`, erfundene Daten, keine Anfrage an die Stadt; geprüft in `tests/test_messstufen.py`). Sie gelten für Köln, wenn der Body alle vier Listen nennt und jede Liste mindestens so viele Seiten hat wie die Seitengrenze. Sonst sind es weniger.

### Abbruchkriterien

Jeder Abbruch beendet den Lauf mit Rückgabewert 2 (Fehler: 1) und wird in `explore/ergebnisse/oparl_laeufe.tsv` vermerkt. Danach gilt: in dieser Nacht keine weitere Anfrage und keine weitere Stufe, Bericht an den Auftraggeber.

| Kriterium | Umsetzung |
|---|---|
| Antwortzeit über 5 s | `RATSATLAS_MAX_DAUER=5`: Antwort wird noch gespeichert, dann Abbruch |
| HTTP 429 oder 5xx | `RATSATLAS_WIEDERHOLUNGEN=0`: sofortiger Abbruch ohne Wiederholung |
| Zeitüberschreitung (60 s) oder Verbindungsabbruch | immer sofortiger Abbruch (mögliche Sperre) |
| HTTP 401, 403, 404 | Abbruch; die Parametertests in `kennzahlen` vermerken 400, 401 und 404 als „Parameter abgelehnt“, `pdf-koepfe` vermerkt 404 und 410 einzelner Dateien |
| Antwort ist kein JSON (z. B. HTML-Seite) | Abbruch |
| Obergrenze erreicht | Abbruch vor der nächsten Anfrage |
| außerhalb 23–1 Uhr | Prüfung vor jeder Anfrage |

Bei Verbindungsabbruch, 403 oder 429 ruhen alle Abrufe bis zur Klärung mit der Stadt.

## Übersicht

| Stufe | Kommando | Anfragen mit Cache der Vorstufen | ohne Cache | `RATSATLAS_MAX_ANFRAGEN` | Dauer bei 1 s je Antwort |
|---|---|---:|---:|---:|---|
| 1 | `test` | 3 | 3 | 3 | etwa 7 s |
| 2 | `kennzahlen` | 7 | 10 | 10 | 20–30 s |
| 3 | `organisationen` | 3 | 5 | 5 | 7–13 s |
| 3 | `stichprobe --seiten 1` | 7 | 9 | 9 | 20–25 s |
| 4 | `sitzungen --seiten 2` | 1 | 3 | 3 | unter 10 s |
| 5 | `stichprobe --seiten 3` | 16 | 25 | 25 | 45–75 s |
| 6 | `pdf-koepfe --anzahl 100` | höchstens 100 | höchstens 100 | 100 | etwa 5 min |

Dauer: (Anfragen − 1) × 2 s Abstand plus Antwortzeiten. Die Antwortzeiten misst Stufe 1.

## Stufe 1 – Erreichbarkeit (freigegeben am 07.11.2026, geplant 23:05 Uhr)

```bash
RATSATLAS_STUFE=1 RATSATLAS_MAX_ANFRAGEN=3 python3 explore/oparl_messung.py test
```

- Anfragen: System, Body, erste Seite der Vorlagenliste (3).
- Ausgewertet (`oparl_test.tsv`): Erreichbarkeit, Antwortzeit, `oparlVersion`, `vendor`, `product`, `license` (System und Body), Adresse der Vorlagenliste, `pagination` (totalElements, elementsPerPage, totalPages), Objekte der ersten Seite, Schlüssel von `links`, Form von `links.next` (Parameter, URL-Kodierung), Felder des ersten Objekts.

## Stufe 2 – Kennzahlen

```bash
RATSATLAS_STUFE=2 RATSATLAS_MAX_ANFRAGEN=10 python3 explore/oparl_messung.py kennzahlen
```

- Anfragen: System, Body, erste Seite von `paper`, `meeting`, `organization`, `person` (6) und vier Parametertests an `paper`: `modified_since` URL-kodiert (bei SessionNet anderswo HTTP 404), `limit=100`, `modified_since` vor 7 Tagen, `created_since`/`created_until` für 2025. Mit dem Cache aus Stufe 1 kommen System, Body und erste Vorlagenseite aus dem Cache (7 ans Netz).
- Ausgewertet (`oparl_kennzahlen.tsv`): Gesamtzahlen und Seitenzahl je Liste (Umfang eines Vollabrufs), ob `limit` wirkt, ob die Zeitfilter wirken (`filter_wirksam`), Body-Felder (`license`, `legislativeTerm`, Kontakt).
- Für Stufe 3: `organization` `pagination.totalPages` (reichen 4 Seiten?).

## Stufe 3 – Organisationen und kleine Stichprobe

Zwei Prozesse nacheinander in derselben Nacht, jeder mit eigener Obergrenze:

```bash
RATSATLAS_STUFE=3 RATSATLAS_MAX_ANFRAGEN=5 python3 explore/oparl_messung.py organisationen --seiten 4
RATSATLAS_STUFE=3 RATSATLAS_MAX_ANFRAGEN=9 python3 explore/oparl_messung.py stichprobe --seiten 1 --von 2019 --bis 2026
```

- `organisationen`: Body und 4 Seiten (Body und erste Seite aus dem Cache von Stufe 2: 3 ans Netz). Ohne `--seiten` gilt jetzt dieselbe Grenze von 4 Seiten; vorher lief das Kommando bis zum Ende der Liste.
- `stichprobe`: Body und je Jahr 2019–2026 eine Seite (Body und Seite 2025 aus dem Cache von Stufe 2: 7 ans Netz), bei 25 je Seite 200 Vorlagen.
- Ausgewertet: `organizationType` und ob das Listenende erreicht ist (`oparl_listen.tsv`, Spalte `ende`); je Jahr totalElements, ob `created_since`/`created_until` wirken (`created außerhalb des Filterjahres`, doppelte Kennungen), erste Feldabdeckung, `paperType`, Referenzschema.

## Stufe 4 – Sitzungen

```bash
RATSATLAS_STUFE=4 RATSATLAS_MAX_ANFRAGEN=3 python3 explore/oparl_messung.py sitzungen --seiten 2
```

- Anfragen: Body und 2 Seiten der Sitzungsliste (Body und erste Seite aus dem Cache von Stufe 2: 1 ans Netz).
- Ausgewertet (`oparl_top_ergebnisse.tsv`): Werte von `agendaItem.result`, Anteil `public`, Zahl der Sitzungen und TOPs. Offen: Sortierung der Sitzungsliste (alte oder neue Sitzungen zuerst).
- Optional, wenn Stufe 3 das Ende der Organisationsliste nicht erreicht hat: `organisationen --seiten <totalPages aus Stufe 2>` mit `RATSATLAS_MAX_ANFRAGEN` = totalPages + 1; die ersten 4 Seiten kommen aus dem Cache. Die Zahl wird nach Stufe 2 festgelegt.

## Stufe 5 – Stichprobe mit mindestens 500 Vorlagen (CLAUDE.md 7.1)

```bash
RATSATLAS_STUFE=5 RATSATLAS_MAX_ANFRAGEN=25 python3 explore/oparl_messung.py stichprobe --seiten 3 --von 2019 --bis 2026
```

- Anfragen: Body und je Jahr 3 Seiten = 25; Body und die ersten Seiten je Jahr kommen aus dem Cache von Stufe 3 (16 ans Netz). Bei 25 je Seite 600 Vorlagen.
- Weicht die Seitengröße aus Stufe 1 von 25 ab, wird `--seiten` so gewählt, dass 8 × Seiten × Seitengröße ≥ 500; Obergrenze dann 1 + 8 × Seiten.
- Ausgewertet: Abdeckung von `underDirectionOf`, `originatorPerson`, `originatorOrganization`, `mainFile`, `auxiliaryFile`, `location` und ihren Feldern, `consultation`; Listen aller `paperType`; Referenzschema; Grundlage für die Schätzung der Anteile der Stufen A/B/C und für Stufe 6.

## Stufe 6 – PDF-Köpfe (erst nach Klärung mit der Stadt)

```bash
RATSATLAS_STUFE=6 RATSATLAS_PDF_FREIGEGEBEN=ja RATSATLAS_MAX_ANFRAGEN=100 python3 explore/oparl_messung.py pdf-koepfe --anzahl 100
```

- Nur mit ausdrücklicher Freigabe des PDF-Abrufs (`RATSATLAS_PDF_FREIGEGEBEN=ja`, Frage in `ANFRAGE_stadt_koeln.md`). Laut einem Codekommentar bei mandari ist deren Dateiabruf für Köln abgeschaltet, „mit der Kommune so vereinbart“ (`ergebnisse/sessionnet_befunde.tsv`).
- Anfragen: eine je Verwaltungsvorlage mit Datei aus der Stichprobe, höchstens 100 (im Probelauf 95, weil dort einige Vorlagen keine Datei haben). Umfang laut mandari etwa 0,38 MB je Datei (Stichprobe n = 8), also rund 40 MB.
- Ausgewertet (`pdf_koepfe.tsv`): Erkennungsquote von „Dezernat, Dienststelle“ mit Kennung. Gespeichert werden nur abgeleitete Kennungen und Trefferarten, keine Textauszüge; die PDFs bleiben im Cache.
