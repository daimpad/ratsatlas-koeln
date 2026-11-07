# Messstufen der Kölner OParl-API

Stand 07.11.2026. Grundlage: mündliche Einwilligung der Stadt Köln (CLAUDE.md, Abschnitt 9, 07.11.2026). Abrufe nur sehr vorsichtig und gestuft, jede Stufe erst nach Bericht und Freigabe, höchstens eine Stufe je Nacht, nur 23–1 Uhr Ortszeit. Aus GitHub Actions wird nicht abgerufen (`RATSATLAS_STADT_INFORMIERT` bleibt als Repository-Variable ungesetzt).

## Für jede Stufe

- Jeder Befehl unten ist vollständig und wird als Ganzes übernommen (ein Block mit mehreren Befehlen als Ganzes, die Befehle sind mit `&& \` verbunden); es gibt keine Variablen „aus derselben Shell“ (jede Stufe läuft in einer anderen Nacht, meist in einer neuen Shell). Der Kontakt im User-Agent ist `contact@nozilla.de` (Projektkontakt des Auftraggebers, steht öffentlich in `README.md`); mit Platzhalter (Zeichen `<` oder `>`) oder ohne Kontakt bricht `oparl_messung.py` vor der ersten Anfrage ab.
- Strenge Vorgaben für Anfragen an die Stadt erzwingt `oparl_messung.py` auch ohne die Angaben im Befehl: keine Wiederholung nach 429/5xx (`RATSATLAS_WIEDERHOLUNGEN`, Vorgabe 0), höchstens 5 s je Antwort (`RATSATLAS_MAX_DAUER`, Vorgabe 5), mindestens 2 s Abstand zwischen zwei Anfragen (`RATSATLAS_ABSTAND`, Vorgabe 2); `RATSATLAS_MAX_ANFRAGEN` und `RATSATLAS_KONTAKT` sind Pflicht. Lockerere Werte (Wiederholungen, mehr als 5 s, Abstand unter 2 s, keine Obergrenze) werden vor der ersten Anfrage abgelehnt und vor jeder Anfrage an die Stadt erneut geprüft. Lokale Testserver (`http://127.0.0.1`, `http://localhost`) sind ausgenommen.
- Eine Verbindung, mindestens 2 s Abstand vom Ende einer Antwort bis zur nächsten Anfrage (`explore/abruf.py`), auch über Prozessgrenzen: Die erste Anfrage eines Prozesses folgt frühestens 2 s nach seinem Start und frühestens 2 s nach der letzten Netzanfrage laut `_cache/abrufe.tsv` (dort sekundengenau, daher bis zu 1 s mehr). Das gilt auch für die zwei Prozesse von Stufe 3. User-Agent mit Projektadresse und Kontakt.
- Prozesse laufen nur nacheinander: Vor seiner ersten Anfrage nimmt ein Prozess eine exklusive Sperre auf `~/.cache/ratsatlas-koeln/abruf.lock` (`fcntl.flock`, außerhalb des Checkouts; `RATSATLAS_SPERRE` ändert den Ort) und hält sie bis zu seinem Ende. Ein zweiter Prozess, der gleichzeitig läuft (auch aus einer anderen Arbeitskopie), bricht vor seiner ersten Anfrage ab (`abbruch (parallel)`).
- Mehrere Befehle einer Stufe sind mit `&&` verbunden: Der nächste läuft nur, wenn der vorige mit Rückgabewert 0 endet. Zusätzlich prüft `oparl_messung.py` vor der ersten Anfrage an die Stadt `ergebnisse/oparl_laeufe.tsv`: Endete der letzte Lauf vor weniger als 12 Stunden mit `abbruch (…)` oder `fehler (…)`, bricht das Kommando ohne Anfrage ab (Rückgabewert 1). Weiter nur nach Rücksprache mit dem Auftraggeber, dann mit `RATSATLAS_NACH_ABBRUCH=ja` vor dem Befehl.
- Weiterleitungen (HTTP 3xx) werden nicht verfolgt: Die Weiterleitung zählt als eine Anfrage, wird mit Ziel-URL in `_cache/abrufe.tsv` (Spalte `ziel`) protokolliert, und der Lauf bricht ab. So bleibt die Obergrenze eine Obergrenze für HTTP-Anfragen, und kein anderer Host wird ungeprüft erreicht.
- `RATSATLAS_MAX_ANFRAGEN` gilt je Prozess und zählt nur Anfragen ans Netz; Antworten aus `explore/_cache/` zählen nicht.
- **Entscheidung zur Obergrenze: ohne Reserve.** Die Obergrenze ist genau die im Probelauf ermittelte Zahl ohne Cache (ungünstigster Fall, z. B. neue Arbeitsumgebung). Reicht sie nicht, bricht die Stufe ab und wird berichtet; eine höhere Grenze gibt es nur nach neuer Freigabe. Grundlage: „Abrufe nur sehr vorsichtig und gestuft“ (CLAUDE.md, Abschnitt 9, 07.11.2026).
- Nach der Stufe: `python3 explore/auswertung.py --stufe <N>` (Markdown) für den Bericht. Fehlt `_cache/abrufe.tsv` (z. B. andere Arbeitsumgebung), meldet die Auswertung Statuscodes und Antwortzeiten als „nicht prüfbar (Protokoll fehlt)“. Protokollzeilen ordnet sie einem Lauf nur zu, wenn ihre Zeit (mit Zone) zwischen Start und Ende des Laufs liegt, sonst „nicht prüfbar (Protokollzeilen passen nicht zum Lauf)“. Ablehnungen durch den Proxy der Arbeitsumgebung zeigt sie in einem eigenen Abschnitt.
- Versioniert werden nur die TSVs in `explore/ergebnisse/` (`oparl_*.tsv`, `pdf_koepfe.tsv`); `explore/_cache/` nicht. Die Stichprobendatei für Stufe 6 liegt im Cache (`_cache/stichprobe_vorlagen.jsonl`, nur `id`, `reference`, `paperType`, `date` und die Adresse der Hauptdatei, keine File-Objekte mit Dateinamen oder Volltext) und entsteht nur bei einer vollständigen Stichprobe. Stufe 5 überschreibt die Stichprobendateien aus Stufe 3; `oparl_laeufe.tsv` und `oparl_listen.tsv` werden fortgeschrieben.
- Zeiten stehen in `_cache/abrufe.tsv` und `oparl_laeufe.tsv` mit Zone (Europe/Berlin, z. B. `2026-11-07T23:05:00+01:00`); ältere Zeilen von `geodaten.py` (04.11.2026) haben keine Zone.
- Die Anfragezahlen stammen aus dem Probelauf gegen den lokalen Testserver (`python3 explore/probelauf.py`, erfundene Daten, keine Anfrage an die Stadt; geprüft in `tests/test_messstufen.py`). Sie gelten für Köln, wenn der Body alle vier Listen nennt und jede Liste mindestens so viele Seiten hat wie die Seitengrenze. Sonst sind es weniger.

### Abbruchkriterien

Jeder Abbruch beendet den Lauf mit Rückgabewert 2 (Fehler: 1) und wird in `explore/ergebnisse/oparl_laeufe.tsv` vermerkt. Danach gilt: in dieser Nacht keine weitere Anfrage und keine weitere Stufe, Bericht an den Auftraggeber. `oparl_messung.py` erzwingt das für 12 Stunden (siehe oben, `RATSATLAS_NACH_ABBRUCH`).

| Kriterium | Umsetzung |
|---|---|
| Antwortzeit über 5 s | `RATSATLAS_MAX_DAUER` (Vorgabe 5): Antwort wird noch gespeichert, dann Abbruch |
| HTTP 429 oder 5xx (außer 502 und 504) | `RATSATLAS_WIEDERHOLUNGEN` (Vorgabe 0): sofortiger Abbruch ohne Wiederholung (Art `server`) |
| HTTP 502 oder 504 (ein Gateway oder der Proxy erreicht die Stadt nicht, auch als Antwort im Tunnel des Proxys) | sofortiger Abbruch der Art `sperre` (mögliche Sperre), Status `502` bzw. `504` in `_cache/abrufe.tsv` |
| Zeitüberschreitung (60 s) oder Verbindungsabbruch | immer sofortiger Abbruch (mögliche Sperre) |
| Antwort abgeschnitten oder unlesbar (weniger Bytes als `Content-Length`, chunked ohne Abschluss, unlesbare Statuszeile, auch beim Verbindungsaufbau über den Proxy) | wie Verbindungsabbruch: sofortiger Abbruch der Art `sperre`, Status `IncompleteRead`, `BadStatusLine` o. Ä. in `_cache/abrufe.tsv`; nichts im Cache |
| Proxy der Arbeitsumgebung erreicht die Stadt nicht (CONNECT-Antwort 502 oder 504, ebenso jede andere außer den unten genannten, z. B. „Tunnel connection failed: 502“) | wie Verbindungsabbruch: sofortiger Abbruch der Art `sperre` (mögliche Sperre), Status `tunnel <Code>` in `_cache/abrufe.tsv` |
| Proxy meldet Begrenzung oder Überlastung (CONNECT-Antwort 429 oder 503) | wie HTTP 429/5xx: sofortiger Abbruch der Art `server` ohne Wiederholung, Status `tunnel <Code>` |
| Ablehnung durch den Proxy der Arbeitsumgebung (CONNECT-Antwort 403, 405 oder 407, z. B. „Tunnel connection failed: 403“, oder HTTP 407: Richtlinie oder fehlende Anmeldung) | sofortiger Abbruch der Art `proxy`, Status `proxy <Code>` in `_cache/abrufe.tsv`; keine Antwort der Stadt und kein Hinweis auf eine Sperre; nichts wiederholen, berichten |
| Weiterleitung (HTTP 3xx) | nicht verfolgt; Abbruch, Ziel-URL im Protokoll |
| HTTP 401, 403, 404 | Abbruch; die Parametertests in `kennzahlen` vermerken 400, 401 und 404 als „Parameter abgelehnt“, `pdf-koepfe` vermerkt 404 und 410 einzelner Dateien |
| Antwort ist kein JSON (z. B. HTML-Seite) | Abbruch |
| Jahresfilter wirkt nicht (`stichprobe`) | Abbruch nach dem Jahr, in dem eine Vorlage mit `created` außerhalb des Jahres oder eine schon in einem anderen Jahr gelieferte Vorlage auftaucht |
| Obergrenze erreicht | Abbruch vor der nächsten Anfrage |
| außerhalb 23–1 Uhr | Prüfung vor jeder Anfrage |
| ein anderer Abrufprozess mit demselben Cache läuft | Abbruch vor der ersten Anfrage (Art `parallel`) |
| letzter Lauf vor weniger als 12 Stunden mit `abbruch (…)` oder `fehler (…)` beendet | Abbruch vor der ersten Anfrage (Rückgabewert 1); weiter nur nach Rücksprache mit `RATSATLAS_NACH_ABBRUCH=ja` |

Bei Verbindungsabbruch, abgeschnittener oder unlesbarer Antwort (Art `sperre`, auch CONNECT-Antwort 502/504 des Proxys), 403, 429 oder 5xx (auch als CONNECT-Antwort oder als Antwort im Tunnel des Proxys) ruhen alle Abrufe bis zur Klärung mit der Stadt. Ein Abbruch der Art `proxy` betrifft nur die Arbeitsumgebung (die Anfrage hat die Stadt nicht erreicht): nichts wiederholen, sondern berichten; weiter erst, wenn der Host im Netz der Arbeitsumgebung erlaubt ist.

## Übersicht

| Stufe | Kommando | Anfragen mit Cache der Vorstufen | ohne Cache | `RATSATLAS_MAX_ANFRAGEN` | Dauer bei 1 s je Antwort |
|---|---|---:|---:|---:|---|
| 1 | `test` | 3 | 3 | 3 | etwa 9 s |
| 2 | `kennzahlen` | 7 | 10 | 10 | 20–30 s |
| 3 | `organisationen` | 3 | 5 | 5 | 9–15 s |
| 3 | `stichprobe --seiten 1` | 7 | 9 | 9 | 20–30 s |
| 4 | `sitzungen --seiten 2` | 1 | 3 | 3 | unter 10 s |
| 5 | `stichprobe --seiten 3` | 16 | 25 | 25 | 50–75 s |
| 6 | `pdf-koepfe --anzahl 100` | höchstens 100 | höchstens 100 | 100 | etwa 5 min |

Zusammen höchstens 155 Anfragen, dazu die optionale Ergänzung in Stufe 4 (`organisationen` bis zum Ende der Liste, totalPages + 1 Anfragen; Zahl nach Stufe 2).

Dauer: Anfragen × 2 s Abstand (auch vor der ersten Anfrage eines Prozesses) plus Antwortzeiten; der Abstand zählt ab dem Ende der vorigen Antwort. Die Antwortzeiten misst Stufe 1.

## Stufe 1 – Erreichbarkeit (freigegeben am 07.11.2026, geplant 23:05 Uhr)

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=1 RATSATLAS_MAX_ANFRAGEN=3 python3 explore/oparl_messung.py test
```

- Voraussetzung: Der Host `buergerinfo.stadt-koeln.de` muss im Netz der Arbeitsumgebung erlaubt sein. Lehnt der Proxy der Arbeitsumgebung die Verbindung ab (Lauf endet mit `abbruch (proxy)`, z. B. „Tunnel connection failed: 403“), hat keine Anfrage die Stadt erreicht: nichts wiederholen, sondern berichten. Endet der Lauf dagegen mit `abbruch (sperre)`, etwa mit „Der Proxy erreicht den Zielserver nicht (HTTP 502 bzw. 504 …)“ beim Verbindungsaufbau, mit HTTP 502/504 als Antwort im Tunnel oder mit einer abgeschnittenen oder unlesbaren Antwort, hat die Anfrage die Stadt nicht oder nicht vollständig erreicht: mögliche Sperre, alle Abrufe ruhen bis zur Klärung. Dasselbe gilt für `abbruch (server)` nach 429 oder 5xx und für `abbruch (http)` nach 403.
- Anfragen: System, Body, erste Seite der Vorlagenliste (3).
- Ausgewertet (`oparl_test.tsv`): Erreichbarkeit, Antwortzeit, `oparlVersion`, `vendor`, `product`, `license` (System und Body), Adresse der Vorlagenliste, `pagination` (totalElements, elementsPerPage, totalPages), Objekte der ersten Seite, Schlüssel von `links`, Form von `links.next` (Parameter, URL-Kodierung), Felder des ersten Objekts.

## Stufe 2 – Kennzahlen

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=2 RATSATLAS_MAX_ANFRAGEN=10 python3 explore/oparl_messung.py kennzahlen
```

- Anfragen: System, Body, erste Seite von `paper`, `meeting`, `organization`, `person` (6) und vier Parametertests an `paper`: `modified_since` URL-kodiert (bei SessionNet anderswo HTTP 404), `limit=100`, `modified_since` vor 7 Tagen, `created_since`/`created_until` für 2025. Mit dem Cache aus Stufe 1 kommen System, Body und erste Vorlagenseite aus dem Cache (7 ans Netz).
- Ausgewertet (`oparl_kennzahlen.tsv`): Gesamtzahlen und Seitenzahl je Liste (Umfang eines Vollabrufs), ob `limit` wirkt, ob die Zeitfilter wirken (`filter_wirksam`), Body-Felder (`license`, `legislativeTerm`, Kontakt).
- Für Stufe 3: `organization` `pagination.totalPages` (reichen 4 Seiten?) und `filter_wirksam` des Tests `created_since`/`created_until`.

## Stufe 3 – Organisationen und kleine Stichprobe

Zwei Prozesse nacheinander in derselben Nacht, jeder mit eigener Obergrenze. Der zweite läuft nur, wenn der erste mit Rückgabewert 0 endet (`&&`); nach einem Abbruch des ersten lehnt `oparl_messung.py` den zweiten außerdem vor der ersten Anfrage ab (letzter Lauf in `oparl_laeufe.tsv`):

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=3 RATSATLAS_MAX_ANFRAGEN=5 python3 explore/oparl_messung.py organisationen --seiten 4 && \
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=3 RATSATLAS_MAX_ANFRAGEN=9 python3 explore/oparl_messung.py stichprobe --seiten 1 --von 2019 --bis 2026
```

- `stichprobe` nur, wenn Stufe 2 für `created_since`/`created_until` `filter_wirksam=ja` gemeldet hat. Lehnt Köln die Parameter ab oder wirken sie nicht, entfällt die Stichprobe dieser Stufe; eine Stichprobe über `links.next` ohne Jahresfilter (mit eigener Seitenzahl) gibt es nur nach neuer Freigabe.
- `organisationen`: Body und 4 Seiten (Body und erste Seite aus dem Cache von Stufe 2: 3 ans Netz). Ohne `--seiten` gilt dieselbe Grenze von 4 Seiten.
- `stichprobe`: Body und je Jahr 2019–2026 eine Seite (Body und Seite 2025 aus dem Cache von Stufe 2: 7 ans Netz), bei 25 je Seite 200 Vorlagen.
- Ausgewertet: `organizationType` und ob das Listenende erreicht ist (`oparl_listen.tsv`, Spalte `ende`); je Jahr totalElements, ob `created_since`/`created_until` wirken (`created außerhalb des Filterjahres`, doppelte Kennungen), erste Feldabdeckung, `paperType`, Referenzschema.
- **Regel:** Weiter zur nächsten Stufe nur, wenn der Jahresfilter wirkt und keine Doppelungen auftreten: `created außerhalb des Filterjahres`, `doppelte Kennungen im selben Jahr` und `doppelte Kennungen aus anderen Jahren` sind alle 0 (die Auswertung meldet „Regel Stufe 3/5 … erfüllt“). Sonst Bericht; die Reihe geht erst nach neuer Freigabe weiter.

## Stufe 4 – Sitzungen

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=4 RATSATLAS_MAX_ANFRAGEN=3 python3 explore/oparl_messung.py sitzungen --seiten 2
```

- Anfragen: Body und 2 Seiten der Sitzungsliste (Body und erste Seite aus dem Cache von Stufe 2: 1 ans Netz).
- Ausgewertet (`oparl_top_ergebnisse.tsv`): Werte von `agendaItem.result`, Anteil `public`, Zahl der Sitzungen und TOPs. Offen: Sortierung der Sitzungsliste (alte oder neue Sitzungen zuerst).
- Optional, wenn Stufe 3 das Ende der Organisationsliste nicht erreicht hat (eigener Prozess, `<T>` = totalPages aus Stufe 2, `<T+1>` = totalPages + 1; die ersten 4 Seiten kommen aus dem Cache). Die Zahl wird nach Stufe 2 festgelegt und freigegeben:

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=4 RATSATLAS_MAX_ANFRAGEN=<T+1> python3 explore/oparl_messung.py organisationen --seiten <T>
```

## Stufe 5 – Stichprobe mit mindestens 500 Vorlagen (CLAUDE.md 7.1)

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=5 RATSATLAS_MAX_ANFRAGEN=25 python3 explore/oparl_messung.py stichprobe --seiten 3 --von 2019 --bis 2026
```

- Nur, wenn die Regel aus Stufe 3 erfüllt ist (Jahresfilter wirkt, keine Doppelungen).
- Anfragen: Body und je Jahr 3 Seiten = 25; Body und die ersten Seiten je Jahr kommen aus dem Cache von Stufe 3 (16 ans Netz). Bei 25 je Seite 600 Vorlagen.
- Weicht die Seitengröße aus Stufe 1 von 25 ab, wird `--seiten` so gewählt, dass 8 × Seiten × Seitengröße ≥ 500; Obergrenze dann 1 + 8 × Seiten.
- Einschränkung durch den Cache: Die erste Seite je Jahr stammt aus einer früheren Nacht, die Folgeseiten sind neu. Kommen dazwischen Vorlagen hinzu und ist die Liste neu-zuerst sortiert (offen), verschieben sich die Seiten: Vorlagen erscheinen doppelt oder fehlen. Solche Doppelungen zählt die Auswertung getrennt als `doppelte Kennungen im selben Jahr (Seiten verschoben)`; nur `doppelte Kennungen aus anderen Jahren` und `created außerhalb des Filterjahres` zeigen, dass der Jahresfilter nicht wirkt.
- **Regel:** Weiter zu Stufe 6 nur, wenn der Jahresfilter wirkt und keine Doppelungen auftreten (alle drei Zählungen 0, „Regel Stufe 3/5 … erfüllt“). Sonst Bericht; eine Wiederholung ohne Cache gibt es nur nach neuer Freigabe.
- Ausgewertet: Abdeckung von `underDirectionOf`, `originatorPerson`, `originatorOrganization`, `mainFile`, `auxiliaryFile`, `location` und ihren Feldern, `consultation`; Listen aller `paperType`; Referenzschema; Grundlage für die Schätzung der Anteile der Stufen A/B/C und für Stufe 6.

## Stufe 6 – PDF-Köpfe (erst nach Klärung mit der Stadt)

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=6 RATSATLAS_PDF_FREIGEGEBEN=ja RATSATLAS_MAX_ANFRAGEN=100 python3 explore/oparl_messung.py pdf-koepfe --anzahl 100
```

- Nur mit ausdrücklicher Freigabe des PDF-Abrufs (`RATSATLAS_PDF_FREIGEGEBEN=ja`, Frage in `ANFRAGE_stadt_koeln.md`). Laut einem Codekommentar bei mandari ist deren Dateiabruf für Köln abgeschaltet, „mit der Kommune so vereinbart“ (`ergebnisse/sessionnet_befunde.tsv`).
- Voraussetzung: `_cache/stichprobe_vorlagen.jsonl` aus Stufe 5 in derselben Arbeitsumgebung. Fehlt die Datei (z. B. neue Cloud-Sitzung), bricht das Kommando vor der ersten Anfrage ab; Stufe 5 müsste dann erneut laufen (25 Anfragen, nur nach Freigabe).
- Auswahl: Verwaltungsvorlagen (`NNNN/JJJJ`) mit Hauptdatei, gleichmäßig über die Jahre der Referenz (reihum je Jahr, neuere Jahre zuerst). Bei 8 Jahren und 100 Dateien sind das 12 oder 13 je Jahr, sofern jedes Jahr genug Vorlagen mit Hauptdatei hat (sonst füllen die übrigen Jahre auf); die Erkennungsquote bezieht sich so nicht überwiegend auf ältere Vorlagenköpfe.
- Anfragen: eine je ausgewählter Hauptdatei, höchstens 100 (im Probelauf 100). Umfang laut mandari etwa 0,38 MB je Datei (Stichprobe n = 8), also rund 40 MB.
- Ausgewertet (`pdf_koepfe.tsv`): Erkennungsquote von „Dezernat, Dienststelle“ mit Kennung, je Jahr. Gespeichert werden nur abgeleitete Kennungen und Trefferarten, keine Textauszüge; die PDFs bleiben im Cache.
