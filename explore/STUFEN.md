# Messstufen der Kölner OParl-API

Stand 09.11.2026. Grundlage: mündliche Einwilligung der Stadt Köln (CLAUDE.md, Abschnitt 9, 07.11.2026). Abrufe nur sehr vorsichtig und gestuft, jede Stufe erst nach Bericht und Freigabe, höchstens eine Stufe je Nacht, nur 23–1 Uhr Ortszeit. Aus GitHub Actions wird nicht abgerufen (`RATSATLAS_STADT_INFORMIERT` bleibt als Repository-Variable ungesetzt).

## Für jede Stufe

- Ausführen im Hauptcheckout `/home/user/ratsatlas-koeln` (dort liegen `explore/_cache/` mit dem Cache der Vorstufen und `explore/ergebnisse/` mit `oparl_laeufe.tsv` für die 12-Stunden-Regel), nicht in einer anderen Arbeitskopie. Vorher dort `git log -1` gegen den freigegebenen Stand prüfen (Commit laut Freigabe); weicht er ab, nicht ausführen, sondern berichten. Den Befehl im Vordergrund ausführen, nicht mit `nohup`, `&` oder als Hintergrundaufgabe.
- Jeder Befehl unten ist vollständig und wird als Ganzes übernommen (ein Block mit mehreren Befehlen als Ganzes, die Befehle sind mit `&& \` verbunden); es gibt keine Variablen „aus derselben Shell“ (jede Stufe läuft in einer anderen Nacht, meist in einer neuen Shell). Der Kontakt im User-Agent ist `contact@nozilla.de` (Projektkontakt des Auftraggebers, steht öffentlich in `README.md`); mit Platzhalter (Zeichen `<` oder `>`) oder ohne Kontakt bricht `oparl_messung.py` vor der ersten Anfrage ab.
- Strenge Vorgaben für Anfragen an die Stadt erzwingt `oparl_messung.py` auch ohne die Angaben im Befehl: keine Wiederholung nach 429/5xx (`RATSATLAS_WIEDERHOLUNGEN`, Vorgabe 0), höchstens 5 s je Antwort (`RATSATLAS_MAX_DAUER`, Vorgabe 5), mindestens 2 s Abstand zwischen zwei Anfragen (`RATSATLAS_ABSTAND`, Vorgabe 2); `RATSATLAS_MAX_ANFRAGEN` und `RATSATLAS_KONTAKT` sind Pflicht. Lockerere Werte (Wiederholungen, mehr als 5 s, Abstand unter 2 s, keine Obergrenze) werden vor der ersten Anfrage abgelehnt und vor jeder Anfrage an die Stadt erneut geprüft. Lokale Testserver (`http://127.0.0.1`, `http://localhost`) sind ausgenommen.
- Eine Verbindung, mindestens 2 s Abstand vom Ende einer Antwort bis zur nächsten Anfrage (`explore/abruf.py`), auch über Prozessgrenzen: Die erste Anfrage eines Prozesses folgt frühestens 2 s nach seinem Start und frühestens 2 s nach der letzten Netzanfrage laut `_cache/abrufe.tsv` (dort sekundengenau, daher bis zu 1 s mehr). Das gilt auch für die zwei Prozesse von Stufe 3. User-Agent mit Projektadresse und Kontakt.
- Prozesse laufen nur nacheinander: Vor seiner ersten Anfrage nimmt ein Prozess eine exklusive Sperre auf `~/.cache/ratsatlas-koeln/abruf.lock` (`fcntl.flock`, außerhalb des Checkouts; `RATSATLAS_SPERRE` ändert den Ort) und hält sie bis zu seinem Ende. Ein zweiter Prozess, der gleichzeitig läuft (auch aus einer anderen Arbeitskopie), bricht vor seiner ersten Anfrage ab (`abbruch (parallel)`).
- Mehrere Befehle einer Stufe sind mit `&&` verbunden: Der nächste läuft nur, wenn der vorige mit Rückgabewert 0 endet. Zusätzlich prüft `oparl_messung.py` vor der ersten Anfrage an die Stadt `ergebnisse/oparl_laeufe.tsv`: Endete der letzte Lauf vor weniger als 12 Stunden mit `abbruch (…)`, `fehler (…)` oder `unterbrochen` (Strg+C; SIGTERM, etwa nach dem Zeitlimit des aufrufenden Werkzeugs, und SIGHUP enden wie Strg+C und werden ebenso vermerkt, SIGHUP nur, wenn es nicht ignoriert ist wie mit `nohup`; ein zweites Signal danach wird ignoriert; ein Lauf gilt als `unterbrochen`, bis er regulär endet; SIGKILL lässt sich nicht abfangen), bricht das Kommando ohne Anfrage ab (Rückgabewert 1). Ebenso nach einem hart beendeten Lauf (SIGKILL, Absturz der Arbeitsumgebung), der keinen Vermerk schreiben konnte: Vor der ersten Anfrage legt `oparl_messung.py` die Markerdatei `_cache/lauf_offen.json` an (Lauf, Stufe, Kommando, Start) und entfernt sie erst nach dem Vermerk; liegt sie ohne Vermerk und begann der Lauf vor weniger als 12 Stunden, gilt er als „nicht regulär beendet“; ein unlesbarer Marker sperrt bis zur Rücksprache (ohne lesbaren Start keine Frist), ein älterer wird gemeldet und entfernt. Beim Entfernen und beim Überschreiben (nach Rücksprache) wird der Lauf als Zeile „nicht regulär beendet (Marker)“ in `oparl_laeufe.tsv` nachgetragen (Anfragenzahl unbekannt; die Zeile löst die 12-Stunden-Regel nicht erneut aus). Nach einem hart beendeten Lauf in dieser Nacht nicht erneut starten, sondern berichten. Weiter nur nach Rücksprache mit dem Auftraggeber, dann mit `RATSATLAS_NACH_ABBRUCH=ja` vor dem Befehl.
- Weiterleitungen (HTTP 3xx) werden nicht verfolgt: Die Weiterleitung zählt als eine Anfrage, wird mit Ziel-URL in `_cache/abrufe.tsv` (Spalte `ziel`) protokolliert, und der Lauf bricht ab. So bleibt die Obergrenze eine Obergrenze für HTTP-Anfragen, und kein anderer Host wird ungeprüft erreicht.
- `RATSATLAS_MAX_ANFRAGEN` gilt je Prozess und zählt nur Anfragen ans Netz; Antworten aus `explore/_cache/` zählen nicht.
- **Entscheidung zur Obergrenze: ohne Reserve.** Die Obergrenze ist genau die im Probelauf ermittelte Zahl ohne Cache (ungünstigster Fall, z. B. neue Arbeitsumgebung). Reicht sie nicht, bricht die Stufe ab und wird berichtet; eine höhere Grenze gibt es nur nach neuer Freigabe. Grundlage: „Abrufe nur sehr vorsichtig und gestuft“ (CLAUDE.md, Abschnitt 9, 07.11.2026).
- Nach der Stufe: `python3 explore/auswertung.py --stufe <N>` (Markdown) für den Bericht. Fehlt `_cache/abrufe.tsv` (z. B. andere Arbeitsumgebung), meldet die Auswertung Statuscodes und Antwortzeiten als „nicht prüfbar (Protokoll fehlt)“. Protokollzeilen ordnet sie einem Lauf nur zu, wenn ihre Zeit (mit Zone) zwischen Start und Ende des Laufs liegt, sonst „nicht prüfbar (Protokollzeilen passen nicht zum Lauf)“. Ablehnungen durch den Proxy der Arbeitsumgebung zeigt sie in einem eigenen Abschnitt.
- Versioniert werden nur die TSVs in `explore/ergebnisse/` (`oparl_*.tsv`, `pdf_koepfe.tsv`); `explore/_cache/` nicht. Die Stichprobendatei für Stufe 6 liegt im Cache (`_cache/stichprobe_vorlagen.jsonl`, nur `id`, `reference`, `paperType`, `date` und die Adresse der Hauptdatei, keine File-Objekte mit Dateinamen oder Volltext) und entsteht nur bei einer vollständigen Stichprobe. Die Stichprobendateien entstehen in Stufe 5; `oparl_laeufe.tsv` und `oparl_listen.tsv` werden fortgeschrieben.
- Zeiten stehen in `_cache/abrufe.tsv` und `oparl_laeufe.tsv` mit Zone (Europe/Berlin, z. B. `2026-11-07T23:05:00+01:00`); ältere Zeilen von `geodaten.py` (04.11.2026) haben keine Zone.
- Die Anfragezahlen stammen aus dem Probelauf gegen den lokalen Testserver (`python3 explore/probelauf.py`, erfundene Daten, keine Anfrage an die Stadt; geprüft in `tests/test_messstufen.py`), auch in der Kölner Antwortform aus Stufe 1 (`--form koeln`: ohne Gesamtzahlen, `links` nur `first`, `self`, `next`, neueste zuerst, ohne `mainFile`; gleiche Zahlen außer Stufe 6). Der Testserver beantwortet Parameter dabei wie Köln in Stufe 2 (nur kodierte Zeitwerte wirken, `links.next` trägt sie unkodiert, `limit` wirkt). Sie gelten für Köln, wenn der Body alle vier Listen nennt und jede Liste mindestens so viele Seiten hat wie die Seitengrenze. Sonst sind es weniger.

### Abbruchkriterien

Jeder Abbruch beendet den Lauf mit Rückgabewert 2 (Fehler: 1) und wird in `explore/ergebnisse/oparl_laeufe.tsv` vermerkt. Danach gilt: in dieser Nacht keine weitere Anfrage und keine weitere Stufe, Bericht an den Auftraggeber. `oparl_messung.py` erzwingt das für 12 Stunden (siehe oben, `RATSATLAS_NACH_ABBRUCH`).

| Kriterium | Umsetzung |
|---|---|
| Antwortzeit über 5 s | `RATSATLAS_MAX_DAUER` (Vorgabe 5): Antwort wird noch gespeichert, dann Abbruch |
| HTTP 429 oder 5xx (außer 502 und 504) | `RATSATLAS_WIEDERHOLUNGEN` (Vorgabe 0): sofortiger Abbruch ohne Wiederholung (Art `server`) |
| HTTP 502 oder 504 (ein Gateway oder der Proxy erreicht die Stadt nicht, auch als Antwort im Tunnel des Proxys) | sofortiger Abbruch der Art `sperre` (mögliche Sperre), Status `502` bzw. `504` in `_cache/abrufe.tsv` |
| Zeitüberschreitung (60 s) oder Verbindungsabbruch | immer sofortiger Abbruch (mögliche Sperre) |
| Antwort braucht insgesamt länger als 60 s (Tropf-Antwort: jeder Block kommt vor der Zeitüberschreitung, das Ganze nicht; ebenso ein hängender Verbindungsaufbau oder Kopf, ein leerer Inhalt nach langsamem Kopf, ein später Abschluss) | sofortiger Abbruch der Art `sperre` (mögliche Sperre), Status `Gesamtfrist` in `_cache/abrufe.tsv`; nichts im Cache. Ein Wächter (SIGALRM) beendet das Warten nach 60 s ab dem Senden. Hängt eine Anfrage trotzdem länger als 60 s, mit Strg+C abbrechen; das wird als mögliche Sperre vermerkt; nicht neu starten. |
| Lauf während einer gesendeten Anfrage unterbrochen (Strg+C, SIGTERM, SIGHUP) | Status `unterbrochen` in `_cache/abrufe.tsv` (die Anfrage zählt), Meldung „unterbrochen während einer Anfrage …: mögliche Sperre“ in `oparl_laeufe.tsv`; mögliche Sperre: stoppen und berichten |
| Antwort abgeschnitten oder unlesbar (weniger Bytes als `Content-Length`, chunked ohne Abschluss, unlesbare Statuszeile, auch beim Verbindungsaufbau über den Proxy) | wie Verbindungsabbruch: sofortiger Abbruch der Art `sperre`, Status `IncompleteRead`, `BadStatusLine` o. Ä. in `_cache/abrufe.tsv`; nichts im Cache |
| Zertifikatsprüfung fehlgeschlagen (TLS, `CERTIFICATE_VERIFY_FAILED`, z. B. fehlende CA des Proxys der Arbeitsumgebung) | sofortiger Abbruch der Art `tls`, Status `tls` in `_cache/abrufe.tsv`; vermutlich eine Einstellung der Arbeitsumgebung (CA des Proxys), ein Zertifikat der Gegenseite oder eine Sperrseite ist nicht ausgeschlossen; keine HTTP-Anfrage gesendet (zählt als Versuch zur Obergrenze); berichten, nicht wiederholen |
| andere TLS-Fehler (unerwartetes Ende oder Reset im Handshake) | wie Verbindungsabbruch: Art `sperre` (mögliche Sperre) |
| Proxy der Arbeitsumgebung erreicht die Stadt nicht (CONNECT-Antwort 502 oder 504, ebenso jede andere außer den unten genannten, z. B. „Tunnel connection failed: 502“) | wie Verbindungsabbruch: sofortiger Abbruch der Art `sperre` (mögliche Sperre), Status `tunnel <Code>` in `_cache/abrufe.tsv` |
| Proxy meldet Begrenzung oder Überlastung (CONNECT-Antwort 429 oder 503) | wie HTTP 429/5xx: sofortiger Abbruch der Art `server` ohne Wiederholung, Status `tunnel <Code>` |
| Ablehnung durch den Proxy der Arbeitsumgebung (CONNECT-Antwort 403, 405 oder 407, z. B. „Tunnel connection failed: 403“, oder HTTP 407: Richtlinie oder fehlende Anmeldung) | sofortiger Abbruch der Art `proxy`, Status `proxy <Code>` in `_cache/abrufe.tsv`; keine Antwort der Stadt und kein Hinweis auf eine Sperre; nichts wiederholen, berichten |
| Weiterleitung (HTTP 3xx) | nicht verfolgt; Abbruch, Ziel-URL im Protokoll |
| HTTP 401, 403, 404 | Abbruch; die Parametertests in `kennzahlen` vermerken 400, 401 und 404 als „Parameter abgelehnt“ (zwei 401 in Folge: Abbruch der Art `http`; die Auswertung kennzeichnet 401 als „abgelehnt oder Sperre?“), `pdf-koepfe` vermerkt 404 und 410 einzelner Dateien |
| Antwort ist kein JSON (z. B. HTML-Seite) | Abbruch; die Antwort wird aus dem Cache entfernt (auch in Listen und Parametertests) |
| Jahresfilter wirkt nicht (`stichprobe`) | Abbruch nach dem Jahr, in dem eine Vorlage mit `created` außerhalb des Jahres oder eine schon in einem anderen Jahr gelieferte Vorlage auftaucht |
| Obergrenze erreicht | Abbruch vor der nächsten Anfrage |
| außerhalb 23–1 Uhr | Prüfung vor jeder Anfrage |
| ein anderer Abrufprozess mit demselben Cache läuft | Abbruch vor der ersten Anfrage (Art `parallel`) |
| Lauf unterbrochen (Strg+C, SIGTERM, SIGHUP) oder ohne regulären Abschluss beendet | Vermerk `unterbrochen` in `oparl_laeufe.tsv` (Rückgabewert 128 + Signalnummer, z. B. 130 oder 143); zählt für die 12-Stunden-Regel wie ein Abbruch |
| Lauf hart beendet (SIGKILL, Absturz der Arbeitsumgebung): Markerdatei `_cache/lauf_offen.json` ohne Vermerk in `oparl_laeufe.tsv` | gilt 12 Stunden ab dem Start als „nicht regulär beendet“, ein unlesbarer Marker bis zur Rücksprache: Abbruch vor der ersten Anfrage (Rückgabewert 1); ein älterer Marker wird gemeldet, als „nicht regulär beendet (Marker)“ nachgetragen (Anfragenzahl unbekannt) und entfernt; in dieser Nacht nicht erneut starten |
| `links.next` zeigt auf einen anderen Host als die Liste, enthält Zeichen außerhalb von ASCII oder ist unlesbar | nicht gesendet, Abbruch der Art `adresse` |
| `filtertest`: Body nicht im Cache | Abbruch vor der Anfrage (Art `voraussetzung`), keine Anfrage |
| letzter Lauf vor weniger als 12 Stunden mit `abbruch (…)`, `fehler (…)` oder `unterbrochen` beendet | Abbruch vor der ersten Anfrage (Rückgabewert 1); weiter nur nach Rücksprache mit `RATSATLAS_NACH_ABBRUCH=ja` |

Bei Verbindungsabbruch, abgeschnittener oder unlesbarer Antwort (Art `sperre`, auch CONNECT-Antwort 502/504 des Proxys), 403, 429 oder 5xx (auch als CONNECT-Antwort oder als Antwort im Tunnel des Proxys) ruhen alle Abrufe bis zur Klärung mit der Stadt. Ein Abbruch der Art `proxy` betrifft nur die Arbeitsumgebung (die Anfrage hat die Stadt nicht erreicht): nichts wiederholen, sondern berichten; weiter erst, wenn der Host im Netz der Arbeitsumgebung erlaubt ist. Ebenso ein Abbruch der Art `tls` (Zertifikatsprüfung gescheitert, keine HTTP-Anfrage gesendet; vermutlich die Arbeitsumgebung, ein Zertifikat der Gegenseite oder eine Sperrseite ist nicht ausgeschlossen): berichten, weiter erst nach Klärung, frühestens nach 12 Stunden.

## Übersicht

| Stufe | Kommando | Anfragen mit Cache der Vorstufen | ohne Cache | `RATSATLAS_MAX_ANFRAGEN` | Dauer bei 1 s je Antwort |
|---|---|---:|---:|---:|---|
| 1 | `test` | 3 | 3 | 3 | etwa 9 s |
| 2 | `kennzahlen` | 7 | 10 | 10 | 20–30 s |
| 3 | `organisationen --seiten 4` | 3 | 5 | 5 | 9–15 s |
| 3 | `filtertest` | 1 | 1 (Body aus `organisationen`; allein ohne Body: 0, Abbruch) | 1 | etwa 5 s |
| 4 | `sitzungen --seiten 2` | 1 | 3 | 3 | unter 10 s |
| 5 | `stichprobe --seiten 1 --limit 100` (eigene Freigabe) | 8 | 9 | 9 | 20–30 s (bei 100 je Seite rund 5 s je Antwort: rund 1 min) |
| 6 | `pdf-koepfe --anzahl 100` | höchstens 100 | höchstens 100 | 100 | etwa 5 min |

Zusammen höchstens 131 Anfragen (bis Runde 13: 155), dazu die optionale Ergänzung in Stufe 4 (`organisationen` bis zum Ende der Liste; Köln liefert keine `totalPages`, die Seitenzahl ist unbekannt und wird nach Stufe 3 festgelegt).

Dauer: Anfragen × 2 s Abstand (auch vor der ersten Anfrage eines Prozesses) plus Antwortzeiten; der Abstand zählt ab dem Ende der vorigen Antwort. Die Antwortzeiten misst Stufe 1.

## Stufe 1 – Erreichbarkeit (freigegeben am 07.11.2026, geplant 23:05 Uhr)

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=1 RATSATLAS_MAX_ANFRAGEN=3 python3 explore/oparl_messung.py test
```

- Voraussetzung: Der Host `buergerinfo.stadt-koeln.de` muss im Netz der Arbeitsumgebung erlaubt sein. Lehnt der Proxy der Arbeitsumgebung die Verbindung ab (Lauf endet mit `abbruch (proxy)`, z. B. „Tunnel connection failed: 403“), hat keine Anfrage die Stadt erreicht: nichts wiederholen, sondern berichten. Endet der Lauf dagegen mit `abbruch (sperre)`, etwa mit „Der Proxy erreicht den Zielserver nicht (HTTP 502 bzw. 504 …)“ beim Verbindungsaufbau, mit HTTP 502/504 als Antwort im Tunnel oder mit einer abgeschnittenen oder unlesbaren Antwort, hat die Anfrage die Stadt nicht oder nicht vollständig erreicht: mögliche Sperre, alle Abrufe ruhen bis zur Klärung. Dasselbe gilt für `abbruch (server)` nach 429 oder 5xx und für `abbruch (http)` nach 403.
- Anfragen: System, Body, erste Seite der Vorlagenliste (3).
- Ausgewertet (`oparl_test.tsv`): Erreichbarkeit, Antwortzeit, `oparlVersion`, `vendor`, `product`, `license` (System und Body), Adresse der Vorlagenliste, `pagination` (totalElements, elementsPerPage, totalPages), Objekte der ersten Seite, Schlüssel von `links`, Form von `links.next` (Parameter, URL-Kodierung), Felder des ersten Objekts.

## Stufe 2 – Kennzahlen (freigegeben am 08.11.2026, geplant 23:05 Uhr)

Gelaufen am 08.11.2026, 23:08 Uhr (7 Anfragen); Ergebnis in `BERICHT_phase1.md` Abschnitt 6: Zeitfilter wirken nur URL-kodiert, `links.next` gibt sie unkodiert zurück, `limit=100` wirkt. `kennzahlen` sendet weiter dieselben Adressen wie in der Messung (nachvollziehbar).

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=2 RATSATLAS_MAX_ANFRAGEN=10 python3 explore/oparl_messung.py kennzahlen
```

- Köln liefert keine Gesamtzahlen (Stufe 1: `pagination` nur mit `elementsPerPage` und `currentPage`, ohne `totalElements` und `totalPages`; `links` nur mit `first`, `self` und `next`). Stufe 2 misst daher die Seitengröße, die Wirkung von `limit` und der Zeitfilter, die ersten Seiten der vier Listen und die Form von `links`; fehlende Gesamtzahlen stehen in `oparl_kennzahlen.tsv` und in der Auswertung als „fehlt“.
- Anfragen in dieser Reihenfolge: System, Body, erste Seite von `paper` (diese drei mit dem Cache aus Stufe 1 aus dem Cache), erste Seite von `meeting`, `organization`, `person`, dann vier Parametertests an `paper`: `modified_since` (Grenze siehe unten), `created_since`/`created_until` für 2025, `modified_since` URL-kodiert mit derselben Grenze (bei SessionNet anderswo HTTP 404), zuletzt `limit=100` (wirkt `limit`, dauert die Antwort womöglich über 5 s: Abbruch „langsam“, dann liegen alle übrigen Messungen schon vor; die Zahl der Objekte wird aus der gespeicherten Antwort noch vermerkt). Mit dem Cache aus Stufe 1 7 Anfragen ans Netz, ohne 10.
- Grenze für `modified_since` ohne weitere Anfrage aus der ungefilterten ersten Vorlagenseite (aus dem Cache von Stufe 1): Median von `modified` ihrer ersten Hälfte, in UTC mit „+00:00“, unkodiert (Zeile `grenze modified_since`). Ein Server, der den Filter überginge, müsste dann Vorlagen mit älterem `modified` liefern („nein“, dazu, wie weit die früheste Vorlage der Antwort vor der Grenze liegt: um 1 h deutet auf einen Versatz, etwa „+“ als Leerzeichen und damit Ortszeit, bis 24 h auf Tagesgenauigkeit, mehr auf einen übergangenen Filter). „ja“ nur, wenn die gefilterte Antwort keine Vorlage unter der Grenze enthält, die ungefilterte Seite nachweislich nach `created` sortiert ist und mindestens zwei Vorlagen, die laut Cache unter der Grenze lagen (auf Plätzen, die neue Vorlagen seit Stufe 1 nicht verdrängt haben können), alle in ihr fehlen (seit Runde 15; bis dahin verglich die Regel mit der Zahl älterer fremder Vorlagen, so dass eine volle gefilterte Seite nie „ja“ ergab); sonst „nicht unterscheidbar“, mit dem Vergleich der Kennungen (etwa alle `modified` gleich oder alle Vorlagen seit Stufe 1 geändert: dann liefert auch ein Server ohne Filter nur Vorlagen über der Grenze, mit denselben Kennungen, „gleiche Kennungen wie ohne Filter“). Für den inkrementellen Abruf zählt nur „ja“.
- `created_since`/`created_until`: Bei neueste zuerst zeigt die erste Seite sicher, ob `created_until` wirkt (ein Server, der es überginge, lieferte Vorlagen von 2026); ob `created_since` wirkt, ist allein aus der ersten Seite nicht unterscheidbar. Ergebnis daher „created_until wirkt: ja/nein; created_since wirkt: nicht unterscheidbar (…)“ (ein „nein“ nur, wenn Vorlagen vor 2025 kommen).
- Parametertests: HTTP 400, 401 oder 404 gelten als „Parameter abgelehnt“ (vermerkt, die Messung geht weiter); zwei 401 in Folge brechen ab (Art `http`, abgelehnt oder Sperre?); jede andere Fehlantwort bricht nach dieser Anfrage ab (Abbruchkriterien oben).
- Probelauf in Kölner Form (Testserver auf 127.0.0.2, der wie die Stadt behandelt wird, Scheinzeit 23:05 Uhr, genau der Befehl oben mit der Adresse des Testservers, `tests/test_messstufen.py`): mit dem Cache aus Stufe 1 (System, Body, erste Vorlagenseite) 7 Anfragen ans Netz, ohne Cache 10; Abstände mindestens 2 s, keine Wiederholung; um 22:59 und 01:00 Uhr keine Anfrage. Filtertests gegen Testserver, die `modified_since` bzw. `created_*` anwenden oder übergehen: „ja“ bzw. „nein“; ein Server, der `modified_since` übergeht, nachdem alle Vorlagen seit dem Cache geändert wurden: „nicht unterscheidbar (gleiche Kennungen wie ohne Filter)“.
- Ausgewertet (`oparl_kennzahlen.tsv`): Seitengröße und Form von `links` je Liste (Gesamtzahlen, falls doch geliefert), ob `limit` wirkt, ob `modified_since` wirkt (`filter_wirksam`) und ob `created_until` wirkt, Body-Felder (`license`, `legislativeTerm`, Kontakt).
- Für Stufe 3: „created_until wirkt: ja“ (für die Jahresstichprobe genügt das: bei neueste zuerst beginnen die Seiten eines Jahres mit dessen jüngsten Vorlagen; wirkt `created_since` nicht, kommen Vorlagen aus dem Vorjahr erst, wenn ein Jahr weniger Vorlagen hat, als die Seiten fassen, und `stichprobe` bricht dann ab). Die Zahl der Organisationsseiten bleibt unbekannt (keine `totalPages`).
- Ende von `links.next` ausdrücklich im Bericht notieren, sobald eine Liste mit nur einer Seite oder die letzte Seite einer Liste vorliegt (Rohantwort in `_cache/`): fehlt `links`, ist es leer (`null`, `""`, `[]`, `{}`) oder fehlt bzw. ist leer nur `links.next`? `pipeline/sessionnet.py` wertet jeden leeren Wert als Ende der Liste und nur ein nicht leeres `links`, das kein Objekt ist, als unlesbar; die Angabe aus Köln bestätigt oder widerlegt das.

## Stufe 3 – Organisationen und kodiertes Zeitfenster (freigegeben am 09.11.2026, geplant 23:05 Uhr)

Zwei Prozesse nacheinander in derselben Nacht, jeder mit eigener Obergrenze. Der zweite läuft nur, wenn der erste mit Rückgabewert 0 endet (`&&`); nach einem Abbruch des ersten lehnt `oparl_messung.py` den zweiten außerdem vor der ersten Anfrage ab (letzter Lauf in `oparl_laeufe.tsv`). Im Hauptverzeichnis `/home/user/ratsatlas-koeln` ausführen (dort liegt der Cache aus Stufe 1 und 2), im Vordergrund, nicht mit `nohup`:

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=3 RATSATLAS_MAX_ANFRAGEN=5 python3 explore/oparl_messung.py organisationen --seiten 4 && \
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=3 RATSATLAS_MAX_ANFRAGEN=1 python3 explore/oparl_messung.py filtertest
```

- `organisationen`: Body und 4 Seiten (Body und erste Seite aus dem Cache von Stufe 2: 3 ans Netz, ohne Cache 5). Ohne `--seiten` gilt dieselbe Grenze von 4 Seiten. Die Zahl der Organisationsseiten ist unbekannt (Köln liefert keine `totalPages`); die Seitengrenze 4 bleibt. Die Folgeseiten kommen über `links.next` (`…/organizations?page=2`); `oparl_messung.py` normalisiert `links.next` vor dem Folgen (Werte kodiert neu aufgebaut wie in `pipeline/sessionnet.py`; ohne Zeitwerte bleibt die Adresse gleich).
- `filtertest`: genau 1 Anfrage an `<body.paper>?created_since=2025-06-03T00%3A00%3A00%2B02%3A00&created_until=2025-06-04T23%3A59%3A59%2B02%3A00&limit=100` (Zeitwerte URL-kodiert; Stufe 2 hat nur `modified_since` kodiert gemessen, `created_*` kodiert ist ungemessen). Fenster: zwei Werktage (Dienstag und Mittwoch, 3. und 4. Juni 2025; kein Feiertag und keine Schulferien in NRW), so eng, dass Köln dort deutlich weniger als 100 Vorlagen haben dürfte (Stufe 1: 25 Vorlagen aus vier Tagen). Wirken beide Grenzen, ist die Seite nicht voll und das Ende der Liste sichtbar; wirkt `created_since` nicht, füllen ältere Vorlagen die Seite; wirkt `created_until` nicht, kommen die jüngsten Vorlagen (neueste zuerst). Den Body liest `filtertest` nur aus dem Cache (Stufe 1; `organisationen` legt ihn sonst im selben Cache ab); fehlt er, bricht es vor der Anfrage ab (`abbruch (voraussetzung)`, keine Anfrage), statt eine zweite Anfrage zu stellen.
- Ausgewertet (`oparl_filtertest.tsv`, `python3 explore/auswertung.py --stufe 3`), ohne weitere Anfrage: Zahl der Objekte; `created_since` wirkt („ja“: keine Vorlage vor der Untergrenze und Seite nicht voll; „nein“: Vorlagen davor, mit Abstand der frühesten zur Grenze; „nicht unterscheidbar“: Seite voll ohne Vorlage davor); `created_until` wirkt („ja“: keine nach der Obergrenze; „nein“ mit Abstand der spätesten); Form von `links` und `links.next` (bei weniger als 100 Objekten ist das Ende sichtbar: fehlt `links.next`, ist es leer oder vorhanden?); Antwortzeit. Dauert die Antwort über 5 s (`abbruch (langsam)`), stehen Objektzahl und Urteil aus der gespeicherten Antwort trotzdem in der Datei.
- Ende von `links.next` bei den Organisationen: Erreicht `organisationen` das Listenende (`oparl_listen.tsv`, Spalte `ende` „Ende der Liste (kein links.next)“), die Form von `links` auf der letzten Seite aus der Rohantwort in `_cache/` ausdrücklich im Bericht notieren (wie bei Stufe 2).
- Probelauf (`tests/test_messstufen.py`): genau dieser Block gegen einen Testserver in Kölner Form mit Parametern wie in Stufe 2 (nur kodierte Zeitwerte wirken, `limit` wirkt) auf 127.0.0.2 (wird wie die Stadt behandelt), Scheinzeit 23:05 Uhr. Mit einem Cache wie im Hauptverzeichnis (System, Body und erste Vorlagenseite aus Stufe 1, erste Seiten von `meetings`, `organizations` und `people` aus Stufe 2, gleiche Schlüssel wie die echten Adressen) 3 + 1 = 4 Anfragen ans Netz (`organizations?page=2`, `page=3`, `page=4`, dann die Vorlagenliste mit Fenster); ohne Cache 5 + 1 = 6 (`organisationen` holt den Body, `filtertest` liest ihn aus dem Cache); `filtertest` allein mit leerem Cache: keine Anfrage, `abbruch (voraussetzung)`. Abstände mindestens 2 s, keine Wiederholung.
- Für Stufe 5: Melden beide Grenzen „ja“, wirkt der kodierte Jahresfilter; die Stichprobe über mehrere Jahre folgt dann mit eigener Freigabe.

## Stufe 4 – Sitzungen

> Entfällt (Entscheidung vom 09.11.2026, CLAUDE.md 9): Der erste Vollabruf aus GitHub Actions liefert die Sitzungen; ob `modified_since` bei Sitzungen wirkt, zeigt die erste Nacht nach dem Vollabruf (Filterprüfung der Pipeline).

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=4 RATSATLAS_MAX_ANFRAGEN=3 python3 explore/oparl_messung.py sitzungen --seiten 2
```

- Anfragen: Body und 2 Seiten der Sitzungsliste (Body und erste Seite aus dem Cache von Stufe 2: 1 ans Netz).
- Ausgewertet (`oparl_top_ergebnisse.tsv`): Werte von `agendaItem.result`, Anteil `public`, Zahl der Sitzungen und TOPs. Offen: Sortierung der Sitzungsliste (alte oder neue Sitzungen zuerst).
- Optional, wenn Stufe 3 das Ende der Organisationsliste nicht erreicht hat (eigener Prozess, `<T>` = Seitengrenze, `<T+1>` = Seitengrenze + 1; die ersten 4 Seiten kommen aus dem Cache). Köln liefert keine `totalPages` (Stufe 1); die Grenze wird nach Stufe 3 festgelegt und freigegeben, ein Ende der Liste ist damit nicht sicher:

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=4 RATSATLAS_MAX_ANFRAGEN=<T+1> python3 explore/oparl_messung.py organisationen --seiten <T>
```

## Stufe 5 – Stichprobe über mehrere Jahre (eigene Freigabe; CLAUDE.md 7.1)

> Entfällt (Entscheidung vom 09.11.2026, CLAUDE.md 9): Die Auswertung nach CLAUDE.md 7.1 läuft auf den vollständigen Daten des ersten Vollabrufs.

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=5 RATSATLAS_MAX_ANFRAGEN=9 python3 explore/oparl_messung.py stichprobe --seiten 1 --von 2019 --bis 2026 --limit 100
```

- Nur nach eigener Freigabe und wenn `filtertest` (Stufe 3) für beide Grenzen „ja“ gemeldet hat.
- Anfragen: Body und je Jahr 2019–2026 eine Seite mit kodiertem `created_since`/`created_until` und `limit=100` = 9; der Body kommt aus dem Cache (8 ans Netz). Bei 100 je Seite 800 Vorlagen (mindestens 500, CLAUDE.md 7.1). Bis Runde 13 waren dafür zwei Stufen vorgesehen (Stufe 3: eine Seite zu 25 je Jahr, 9 Anfragen; Stufe 5: drei Seiten, 25 Anfragen).
- Offen vor der Freigabe: Eine Seite zu 100 Vorlagen dauerte in Stufe 2 5,07 s, über der Messgrenze von 5 s (`RATSATLAS_MAX_DAUER`, Abbruch „langsam“ nach der ersten Jahresseite). Zu entscheiden ist, ob die Grenze für diese Stufe angehoben wird oder `--limit` kleiner ausfällt (etwa 50 mit `--seiten 2`, dann 17 Anfragen).
- Einschränkung: Die Seiten eines Jahres kommen in derselben Nacht; neue Vorlagen fallen nicht ins Filterjahr (außer 2026). Doppelungen zählt die Auswertung getrennt als `doppelte Kennungen im selben Jahr (Seiten verschoben)`; nur `doppelte Kennungen aus anderen Jahren` und `created außerhalb des Filterjahres` zeigen, dass der Jahresfilter nicht wirkt.
- **Regel:** Weiter zu Stufe 6 nur, wenn der Jahresfilter wirkt und keine Doppelungen auftreten (alle drei Zählungen 0, „Regel Stufe 5 … erfüllt“). Sonst Bericht; eine Wiederholung gibt es nur nach neuer Freigabe.
- Ausgewertet: Abdeckung von `underDirectionOf`, `originatorPerson`, `originatorOrganization`, `mainFile`, `auxiliaryFile`, `location` und ihren Feldern, `consultation`; Listen aller `paperType`; Referenzschema; Grundlage für die Schätzung der Anteile der Stufen A/B/C und für Stufe 6.

## Stufe 6 – PDF-Köpfe (erst nach Klärung mit der Stadt)

```bash
RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT="contact@nozilla.de" RATSATLAS_WIEDERHOLUNGEN=0 RATSATLAS_MAX_DAUER=5 RATSATLAS_STUFE=6 RATSATLAS_PDF_FREIGEGEBEN=ja RATSATLAS_MAX_ANFRAGEN=100 python3 explore/oparl_messung.py pdf-koepfe --anzahl 100
```

- Nur mit ausdrücklicher Freigabe des PDF-Abrufs (`RATSATLAS_PDF_FREIGEGEBEN=ja`, Frage in `ANFRAGE_stadt_koeln.md`). Laut einem Codekommentar bei mandari ist deren Dateiabruf für Köln abgeschaltet, „mit der Kommune so vereinbart“ (`ergebnisse/sessionnet_befunde.tsv`).
- Voraussetzung: `_cache/stichprobe_vorlagen.jsonl` aus Stufe 5 in derselben Arbeitsumgebung. Fehlt die Datei (z. B. neue Cloud-Sitzung), bricht das Kommando vor der ersten Anfrage ab; Stufe 5 müsste dann erneut laufen (9 Anfragen, nur nach Freigabe).
- Auswahl: Verwaltungsvorlagen (`NNNN/JJJJ`) mit Hauptdatei, gleichmäßig über die Jahre der Referenz (reihum je Jahr, neuere Jahre zuerst). Bei 8 Jahren und 100 Dateien sind das 12 oder 13 je Jahr, sofern jedes Jahr genug Vorlagen mit Hauptdatei hat (sonst füllen die übrigen Jahre auf); die Erkennungsquote bezieht sich so nicht überwiegend auf ältere Vorlagenköpfe.
- `mainFile` fehlte in Stufe 1 bei allen 25 Vorlagen (nur `auxiliaryFile`). Fehlt es auch in der Stichprobe (Stufe 5; in Stufe 2 bei keiner der 100 jüngsten Vorlagen), wählt `pdf-koepfe` keine Datei aus (Probelauf in Kölner Form: 0 Anfragen). Die Auswahl ist dann ggf. auf `auxiliaryFile` umzustellen; Entscheidung nach Stufe 5, bis dahin keine Änderung an `pdf-koepfe`.
- Anfragen: eine je ausgewählter Hauptdatei, höchstens 100 (im Probelauf 100). Umfang laut mandari etwa 0,38 MB je Datei (Stichprobe n = 8), also rund 40 MB.
- Ausgewertet (`pdf_koepfe.tsv`): Erkennungsquote von „Dezernat, Dienststelle“ mit Kennung, je Jahr. Gespeichert werden nur abgeleitete Kennungen und Trefferarten, keine Textauszüge; die PDFs bleiben im Cache.
