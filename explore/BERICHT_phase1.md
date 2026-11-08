# Phase 1 – Exploration Köln (Zwischenbericht, Teil Geodaten)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` 7.1 und Entscheidungen in Abschnitt 9

Den Teil zur OParl-API (Kennzahlen, Stichprobe, PDF-Köpfe) habe ich vorbereitet, aber nicht ausgeführt, weil die Stadt noch nicht informiert ist. Er wird nachgetragen. Die Anteile der Stufen A, B und C lassen sich deshalb noch nicht schätzen.

## 1. Geodaten (geladen am 04.11.2026, 56 Anfragen, etwa 350 MB im Cache)

| Datensatz | Stand | Lizenz (DCAT) | Inhalt | Felder (Auswahl) |
|---|---|---|---|---|
| Stadtteile | 24.09.2026 | dl-de/zero 2.0 | 86 Polygone, ETRS89/UTM 32N | `nummer` (z. B. 205), `name`, `nr_stbez`, `stbezirk` |
| Stadtbezirke | 24.09.2026 | dl-de/zero 2.0 | 9 Polygone | `nummer`, `name` |
| Stadtviertel | 24.09.2026 | dl-de/zero 2.0 | 374 Polygone | `nummer`, `name`, `name_lang`, `nr_stteil`, `stteil` |
| Statistische Quartiere | 24.09.2026 | dl-de/zero 2.0 | 570 Polygone | `nummer`, `name`, `nr_stteil` |
| GeoPackage Raumbezugssystem | 24.09.2026 | dl-de/zero 2.0 | 18 Ebenen, EPSG 25832, u. a. `Stadt_Koeln` (Stadtgebiet), Adresse, Straße, Wahl- und Sozialräume | – |
| Adressen | 24.09.2026 | dl-de/zero 2.0 | 161 531 Punkte | `nr_str` (Straßenschlüssel), `str`, `str_amtl`, `str_stb`, `hausnr`, `geb_alkis`, `nutz_funkt`, `nr_stteil`, `nr_stbez`, Koordinaten |
| Straßen | 24.09.2026 | dl-de/zero 2.0 | 5 633 Linien | `nummer`, `name`, `str_amtl`, `str_stb` |
| Straßenabschnitte | 24.09.2026 | dl-de/zero 2.0 | 16 082 Linien mit Hausnummernbereichen links/rechts | `nr_str`, `hsnr_vo_li` … |
| Straßenverzeichnis | 15.10.2025 (jüngste Fassung) | **dl-de/by 2.0** | Straße × Stadtteil × PLZ mit Hausnummernbereichen; Blätter „Straßen ohne Adressen“ (450), „Straßenumbenennungen“ | zweizeiliger Tabellenkopf |

## 2. Befunde

1. **Lizenzen:** Fast alle Geodaten stehen unter dl-de/zero 2.0. Das Straßenverzeichnis steht dagegen unter **dl-de/by 2.0** und verlangt damit eine Namensnennung. Der Katalogeintrag der OParl-API nennt dl-de/zero 2.0, die Unklarheit aus CLAUDE.md 8 bleibt aber bestehen.
2. **Doppelte Straßennamen:** 349 amtliche Straßennamen kommen mehrfach vor, eine Folge der Eingemeindungen. 532 Straßen tragen einen Bezirkszusatz, z. B. „Dauner Str. (Rodenkirchen)“. Eindeutig trennen lassen sie sich nur über den Straßenschlüssel und den Stadtteil- bzw. Bezirkskontext, wie in 5.2 vorgesehen.
3. **Schreibweisen:** In den Geodaten steht „Str.“ (1 402 Namen enden auf „str.“), in Vorlagentiteln meist „Straße“. 10 Stadtteile haben Doppelnamen mit Schrägstrich, z. B. „Altstadt/Nord“ oder „Rath/Heumar“. Der Gazetteer braucht für beides Schreibvarianten.
4. **Datenschutz:** 92,5 % der Adressen liegen an Wohn- oder Wohn-/Geschäftsgebäuden (`nutz_funkt`). Eine Verortung mit Hausnummer trifft also fast immer ein Wohngebäude. Ich schlage vor, Hausnummern nur bei Verwaltungsvorlagen und politischen Anträgen punktgenau zu verorten. Eingaben nach § 24 GO und Vorlagen von natürlichen Personen bleiben auf Straßen- oder Stadtteilebene (CLAUDE.md 2).
5. **Bebauungspläne offen:** Der im Katalog verlinkte ArcGIS-Dienst liefert statt JSON die Startseite der Stadt. Feldnamen und Plannummernschema sind deshalb nicht verifiziert. Die Rückfrage ist in den Anschreibentwurf aufgenommen.
6. **Kataloglücken:** Die Kennungen „stadtgebiet-köln“ und „Bebauungspläne Aufstellungsbeschlüsse“ ergaben HTTP 404. Das Stadtgebiet liegt als Ebene `Stadt_Koeln` im GeoPackage vor. Die Gebäudereferenzen NRW habe ich nicht geladen, sie werden erst für die Gegenprüfung in Phase 3 gebraucht.
7. **Kodierung:** `Liste_Stadtteile.csv` ist nicht UTF-8-kodiert. Die Shapefiles sind korrekt kodiert und daher als Quelle vorzuziehen.

## 3. Weitere Ergebnisse

- **Inventur:** Die Entscheidung „zweiter Lauf“ ist eingearbeitet. Neuer Stand: 35 generisch, 53 anpassen, 44 deaktivieren, 2 entfernen.
- **Messskripte:** `oparl_messung.py` ist gegen einen lokalen Testserver geprüft (alle fünf Kommandos). Ohne `RATSATLAS_STADT_INFORMIERT=ja` bricht es vor der ersten Anfrage ab.
- **Anschreiben:** Der Entwurf an die Stadt liegt in `explore/ANFRAGE_stadt_koeln.md`.

## 4. Recherche ohne Server der Stadt (04.11.2026)

Quellen sind Landesdienste (IT.NRW), Wahlergebnisse, Presse, Seiten der Fraktionen, Wikipedia, die OParl-Spezifikation und öffentlicher Code anderer Projekte. Server der Stadt habe ich nicht abgefragt. Was nur aus Suchausschnitten stammt, ist als „Hinweis“ gekennzeichnet. Nachgeprüft habe ich die Sitzzahlen des Rates 2025 und 2020, die Sitzzahlen der Bezirksvertretung Kalk und einen Bebauungsplan in der Landesschnittstelle.

| Ergebnis | Inhalt | Wichtigster Befund |
|---|---|---|
| `ergebnisse/fraktionen_rat.tsv` | Rat 2025–2030 und 2020–2025 (je 90 Sitze) | 7 Fraktionen, 2 Gruppen, 1 Einzelmandat ab 2025; Wechsel 2020–2025 nur teilweise belegt; Schreibvarianten erst am RIS zu prüfen |
| `ergebnisse/fraktionen_bv.tsv` | Sitze der 9 Bezirksvertretungen 2025 (je 19) | Fraktionsbildung in den Bezirksvertretungen offen |
| `ergebnisse/gremien_koeln.tsv` | Ausschüsse 2025–2030 und 2020–2025, Bezirksvertretungen 1–9 | Umbenennungen 2025 (u. a. Mobilitätsausschuss, Wirtschaft und Digitalisierung, Integrationsrat → Ausschuss für Chancengerechtigkeit und Integration); amtliche Namen erst am RIS zu prüfen |
| `ergebnisse/bplan_quellen.tsv` | Bezugswege für Bebauungspläne | OGC-API „Bauleitplanung in NRW“ von IT.NRW: 1 343 rechtsverbindliche Kölner Pläne mit Fläche, Plannummer `63429.06.000.00` ↔ Schreibweise „63429/06“ (an einem Fall belegt); keine Aufstellungsbeschlüsse; Lizenzangaben widersprüchlich |
| `ergebnisse/sessionnet_befunde.tsv` | Sperre von mandari, Verhalten von SessionNet, Spiegel | Sperre als stiller Verbindungsabbruch ohne HTTP-Code; laut mandari Abrufe in Köln nur 23–1 Uhr und kein automatischer PDF-Abruf (beides ohne Quelle der Stadt); kein aktueller, lizenzklarer Spiegel |

**Folgerungen (freigegeben 05.11.2026, umgesetzt):** Zeitfenster vorsorglich 23–1 Uhr; Zeitüberschreitung als mögliche Sperre werten (Pause über Stunden); Wiederholungen bei `links.next` erkennen; `links.next` unverändert übernehmen; Zeitfenster, PDF-Abruf und GitHub-Actions-Adressen in der Anfrage an die Stadt nennen; Bebauungspläne aus der Landesschnittstelle für Stufe B.

## 5. Messung Stufe 1 (07.11.2026, 23:07 Uhr, 3 Anfragen)

Grundlage: mündliche Einwilligung der Stadt (CLAUDE.md 9). Der Befehl aus `STUFEN.md` lief einmal; Ergebnisse in `ergebnisse/oparl_test.tsv` und `ergebnisse/oparl_laeufe.tsv`.

| Anfrage | Status | Antwortzeit | Größe |
|---|---|---|---|
| System | 200 | 1,21 s | 634 B |
| Body | 200 | 0,67 s | 2 843 B |
| Vorlagen, Seite 1 | 200 | 2,84 s | 48 431 B |

1. **Erreichbar, ohne Auffälligkeiten:** keine Weiterleitung, kein 429 oder 5xx, keine Antwort über 5 s. SessionNet mit OParl 1.1 (Somacos, `oparl=v1.6.1`).
2. **Lizenz:** `license` ist in System und Body `null`; der Body nennt nur `licenseValidSince` (31.01.2017). Die Frage aus CLAUDE.md 8 bleibt offen, die Namensnennung bleibt Pflicht.
3. **Keine Gesamtzahlen:** `pagination` enthält nur `elementsPerPage` (25) und `currentPage`; `totalElements`, `totalPages` und `links.last` fehlen. Den Umfang eines Vollabrufs liefert die Schnittstelle also nicht. Die höchste Vorlagen-Kennung ist 135557; ob die Kennungen je Objektart fortlaufen, ist offen. Eine Suche über hohe Seitennummern scheidet aus, weil sie laut Stichprobe mit HTTP 401 endet und als mögliche Sperre zählen würde.
4. **Folgeseiten:** `links` enthält `first`, `self` und `next`; `next` lautet `…/papers?page=2` (Parameter `page`, ohne URL-Kodierung).
5. **Sortierung:** neueste zuerst (`created` absteigend; Kennungen 135557 bis 135481; Datum 03. bis 06.11.2026). Bei einem Vollabruf über mehrere Nächte verschieben neue Vorlagen die Seiten nach hinten: Doppelungen sind möglich, Lücken nur bei Löschungen.
6. **Felder** (n = 25, nur die jüngsten Vorlagen): `auxiliaryFile` bei allen (1–3 PDF), `consultation` bei allen (je eine, mit `meeting`, `agendaItem`, `organization`, `role`). `mainFile`, `location`, `underDirectionOf`, `originatorPerson` und `originatorOrganization` fehlen bei allen 25. Referenzen: 18 × `AN/NNNN/JJJJ`, 7 × `NNNN/JJJJ`.
7. **`paperType` trägt Gremium und Fraktion:** 15 verschiedene Typen auf einer Seite, etwa „Antrag nach § 3 BV2 (CDU)“ oder „Änderungsantrag BV1 (Grüne)“. Das ist eine strukturierte Quelle für Fraktionen (5.3) und für die Bezirksvertretung.
8. **Body:** drei Wahlperioden (2014–2020, 2020–2025, 2025–2030 ab 01.11.2025), Kontaktangaben vorhanden, AGS 05315000.

**Folgen (zur Entscheidung):** Stufe 2 kann die Gesamtzahlen je Liste nicht aus `pagination` ablesen; die übrigen Ziele bleiben: Wirkung von `limit` (zuletzt geprüft) und `modified_since` (Grenze aus der ersten Vorlagenseite, so dass ein Server, der den Filter übergeht, ältere Vorlagen liefern müsste), erste Seiten von `meeting`, `organization`, `person`. Bei neueste zuerst zeigt die erste Seite, ob `created_until` wirkt; ob `created_since` wirkt, ist so nicht unterscheidbar (für die Jahresstichprobe in Stufe 3 genügt `created_until`). Fehlt `mainFile` auch in der Stichprobe (Stufe 3), muss die Auswahl der PDF-Köpfe (Stufe 6) auf `auxiliaryFile` umgestellt werden.

## 6. Messung Stufe 2 (08.11.2026, 23:08 Uhr, 7 Anfragen)

Grundlage: Freigabe vom 08.11.2026 (CLAUDE.md 9). Der Befehl aus `STUFEN.md` lief einmal (Code `explore/` auf Stand `f15ecc3`); System, Body und erste Vorlagenseite kamen aus dem Cache von Stufe 1. Ergebnisse in `ergebnisse/oparl_kennzahlen.tsv` und `ergebnisse/oparl_laeufe.tsv`.

| Anfrage | Status | Antwortzeit | Größe |
|---|---|---|---|
| meetings, Seite 1 | 200 | 1,46 s | 19 636 B |
| organizations, Seite 1 | 200 | 0,78 s | 26 144 B |
| people, Seite 1 | 200 | 0,93 s | 31 066 B |
| papers mit `modified_since` (unkodiert) | 200 | 2,50 s | 48 431 B |
| papers mit `created_since`/`created_until` (unkodiert) | 200 | 2,30 s | 48 431 B |
| papers mit `modified_since` (URL-kodiert) | 200 | 1,55 s | 47 635 B |
| papers mit `limit=100` | 200 | 5,07 s | 196 733 B |

Der Lauf endete wie vorgesehen mit `abbruch (langsam)` nach der letzten Anfrage (`limit=100`, 5,07 s über der Messgrenze von 5 s); alle übrigen Messungen lagen vor. Kein Neustart.

1. **Alle vier Listen** (paper, meeting, organization, person): 25 Objekte je Seite, keine Gesamtzahlen, `links` mit `first`, `self`, `next`; `next` lautet `…?page=2`. Das Ende von `links.next` war nicht sichtbar (jede Liste hat mehr als eine Seite).
2. **Zeitfilter wirken nur URL-kodiert.** Unkodiert (`+00:00` bzw. `+01:00` im Klartext) liefert Köln dieselbe Seite wie ohne Filter (gleiche 25 Kennungen in gleicher Reihenfolge) – der Filter wird übergangen; das gilt für `modified_since` und für `created_since`/`created_until`. URL-kodiert (`%3A`, `%2B`) wirkt `modified_since`: keine Vorlage unter der Grenze, 17 der 25 Vorlagen der ungefilterten Seite fehlen, dafür ältere, kürzlich geänderte Vorlagen. Das widerspricht der bisherigen Annahme aus anderen SessionNet-Installationen (dort HTTP 404 bei kodierten Werten).
3. **`links.next` verliert die Kodierung:** Auf der gefilterten Seite lautet `next` `…?page=2&modified_since=2026-11-05T11:29:44+00:00`, also unkodiert. Wer `links.next` unverändert folgt, erhält ab Seite 2 vermutlich ungefilterte Seiten. Für den inkrementellen Abruf in `pipeline/sessionnet.py` folgt daraus: Zeitwerte kodieren und den Query-Teil von `links.next` vor dem Folgen kodiert neu aufbauen (zu entscheiden, zu testen).
4. **`limit` wirkt:** `limit=100` liefert 100 Vorlagen (`elementsPerPage` 100, `next` mit `limit=100`), streng nach `created` absteigend über alle 100. Ein Vollabruf bräuchte damit ein Viertel der Anfragen, bei rund 5 s je Antwort.
5. **Vorlagen (100 jüngste):** `location` bei 4 von 100, `subordinatedPaper` bei 2, `mainFile`, `underDirectionOf` und `originator*` bei keiner. Vorlagenarten u. a. „Antrag nach § 3 der GeschO des Rates“ (20), „Anfrage nach § 4 der GeschO des Rates“ (15), „Mitteilung BV“ (6), „Einwohneranfrage nach § 39 Abs. 6“ (3; Datenschutzregel für natürliche Personen beachten).
6. **Sitzungen:** Die erste Seite enthält geplante Sitzungen von Januar bis Dezember 2027, nicht nach `start` sortiert; `meetingState` und `cancelled` fehlen.
7. **Gremien:** `organizationType` fehlt; `classification` unterscheidet „Fachausschüsse und weitere Gremien“ und „Fraktionen und Gruppen“.
8. **Personen:** Namensfelder vorhanden; sie werden nicht ausgewertet und nicht gespeichert (Gremienbesetzung erst im zweiten Lauf).

**Folgen (zur Entscheidung):** Für Stufe 3 wirkt der Jahresfilter in der vorgesehenen (unkodierten) Form nicht; nach der Regel in `STUFEN.md` entfällt die Stichprobe dieser Stufe. Möglich wären eine Stichprobe mit kodierten Jahresfiltern (Wirkung von `created_*` kodiert noch ungemessen) oder über `links.next` mit `limit=100` ohne Jahresfilter – beides nur nach neuer Freigabe.
