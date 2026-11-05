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
