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
