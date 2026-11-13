# Strukturdaten Köln – Bericht Phase 0

Stand 10.11.2026 (Abschnitt 11: 13.11.2026) · Prompt „Strukturdaten als Kontext- und Kartenebene“ v0.1 · Exploration ohne Produktionscode

## 1. Zweck und Stand

Phase 0 prüft, ob Kölner Stadtstatistik und Wegweiser Kommune als Kontext- und Kartenebene zum Ratsatlas passen, an welche Raumebene sie anschließen und wie sie sich auf den Datenvertrag „Strukturdaten v1“ abbilden. Abrufe laut `audit_abruf.tsv`: 3 Anfragen an offenedaten-koeln.de (1 × HTTP 404 für die Datensatzseite mit dem Slug aus dem Prompt, 2 × HTTP 200 für XLSX und CSV), 6 Anfragen an wegweiser-kommune.de (alle HTTP 200). Metadaten über open.nrw (CKAN-API-Abruf vom Proxy abgebrochen, Datensatzseite über den Web-Leser gelesen). Keine Anfrage an die OParl-API. Prüfsummen nachgerechnet, Repository unverändert. Alle Zahlen sind aus den genannten Dateien nachgerechnet; Einzelheiten in den TSV-Dateien (Abschnitt 10).

## 2. Quellen und Lizenzen

| Quelle | Lizenz (Beleg) | Stand | Einschätzung |
|---|---|---|---|
| Statistischer Datenkatalog Köln (XLSX, CSV) | DL-DE-BY 2.0 laut open.nrw; in der Datei kein Lizenz- oder Namensnennungstext | Datei: 15.10.2026; open.nrw: Ressourcen 06.07.2026 | nutzbar; Namensnennung laut Prompt „Stadt Köln, Amt für Stadtentwicklung und Statistik“ mit Lizenzlink, Datensatz-URL und Vermerk der Veränderungen; von der Stadt noch zu bestätigen |
| Beschreibung des Datenkatalogs (3. Ressource, CSV) | DL-DE-BY 2.0 laut open.nrw | ungeprüft | nicht geladen |
| Stadtteile, Stadtbezirke (Geometrie) | dl-de/zero 2.0 (`data/LICENSE-DATA.md`) | 24.09.2026 | im Ratsatlas genutzt |
| Statistische Quartiere (Geometrie) | dl-de/zero 2.0 nur laut `explore/BERICHT_phase1.md` Z. 14 | 24.09.2026 | nicht im Repository |
| Zensus 2022, 100-m-Gitter (bestehende Kennzahlen) | dl-de/by 2.0, © Destatis | 15.05.2022 | genutzt |
| Wegweiser Kommune | CC0 1.0 (Open-Data-Seite, Exportfußzeile); Quellenangabe „Bertelsmann Stiftung www.wegweiser-kommune.de“ | Datenstand 15.10.2026; OpenAPI 3.12.0 | nutzbar, Vorbehalt Abschnitt 6 |

## 3. Statistischer Datenkatalog Köln

| Raumebene (Blatt Daten, 2012–2025) | Einheiten | Nummer | `*` geheim | leer |
|---|---|---|---|---|
| Gesamtstadt | 1 | 0 | 1,16 % | 0,37 % |
| Stadtbezirke | 9 | 1 Ziffer | 0,81 % | 0,37 % |
| Stadtteile | 86 | 3 Ziffern, 1. = Bezirk | 2,53 % | 0,42 % |
| Statistische Quartiere | 570 | 9 Ziffern, 1.–3. = Stadtteil | 4,56 % | 3,83 % |
| Sozialräume (nicht im Prompt) | 15 + 3 Sammelzeilen | 100NN | 2,23 % | 3,33 % |

| Thema (Blatt Katalog) | IDs | Vertragsindikatoren¹ | mit Werten |
|---|---|---|---|
| Bevölkerung und Haushalte | 544 | 850 | 104 |
| Gesundheit und Soziales | 111 | 201 | 3 |
| Bildung und Ausbildung | 83 | 130 | 2 |
| Bauen und Wohnen | 73 | 100 | 8 |
| Verkehr | 57 | 58 | 51 |
| Wirtschaft und Arbeitsmarkt | 51 | 81 | 4 |
| Politik; Stadtgebiet; Kultur; Umwelt | 26; 12; 9; 7 | 30; 19; 9; 7 | 0 |
| **Summe** | **973** | **1 485** | **172 (136 IDs)** |

¹ Katalogzeile × Formatflag (abs, %, andere).

- Verfügbarkeitscodes im Katalog (aus der bedingten Formatierung abgeleitet): 3 Quartier, 2 Stadtteil, 1 Bezirk, 0 Gesamtstadt; der Code nennt die feinste Ebene und stimmt für 171 von 172 Codes mit dem Blatt Daten überein. Der Katalog führt 2010–2025, die Daten beginnen 2012.
- XLSX und CSV enthalten dieselben 1 513 536 Zahlen. In der CSV fehlt A0291P, und die 68 995 `*` erscheinen als leere Zellen; Geheimhaltung und Fehlen sind dort nicht unterscheidbar. CSV: UTF-8 mit BOM, CRLF, Semikolon, Dezimalkomma, Breitformat.
- Geheimhaltung laut Blatt Info: „Werte zwischen 1 und 4“. Keine Anzahl von 1 bis 4 ist veröffentlicht; bei BA-Daten sind 132 Werte von 5 bis 9 veröffentlicht; das ist mit der Prompt-Angabe „1 bis < 10“ nicht vereinbar.
- Weder Stichtag noch Kennzeichnung von Schätz- und Verfahrenswerten stehen in den Dateien. A0025A „Einwohner*innen, gesamt“ schließt Einwohner*innen mit Nebenwohnsitz ein (für alle Jahre geprüft); städtische Bevölkerungsanteile beziehen sich auf A0025A.

## 4. Raumebenen und Abgleich

| Ebene | Vorlagen im Ratsatlas | Abgleich mit dem Katalog |
|---|---|---|
| Stadtteil (86) | Verortungsebene `ortsteil`; Straßen-, Adress- und Objektlagen tragen ihren Stadtteil; Filter, Export, `kontext.json` | 86/86: Property `ortsteil` = `S_RAUM`, Namen zeichengenau gleich |
| Stadtbezirk (9) | Ebene `stadtbezirk` | 9/9 über Property `bezirk` |
| Quartier (570) | nicht verwendet, keine Geometrie | alle 570 Nummern beginnen mit einer vorhandenen Stadtteilnummer; 1–22 je Stadtteil |
| Sozialraum | nur Grenzlinie (20 Flächen ohne Nummer) | 15 Sozialräume, Zuordnung ungeklärt |

Anzahlen summieren sich über die Nummern: Quartier → Stadtteil in 122 982 von 139 660 Vergleichen exakt, Abweichungen ohne `*` nur bei B0009A; Stadtteil → Bezirk ohne solche Abweichung. Bezirk → Gesamtstadt weicht in 612 Fällen ab (530 davon um genau den Wert von Sozialraum 10099 „keine räumliche Zuordnung“); Gesamtstadtwerte daher aus der Quelle übernehmen.

**Empfehlung:** Kontext-Panel auf Stadtteilebene (Ebene der Verortung, Schlüssel 1:1; `raum_id` über die Property `ortsteil`, da das Frontend Namen verwendet). Quartiers-Choroplethe erst nach Prüfung der Quartiersgeometrie in Phase 2.

## 5. Vergleich Zensus-Kennzahlen und Stadtstatistik

| Kennzahl | Zensus 2022 | Stadt 2022 | Stadt 2025 | Stadtteile 2022: Median rel. Abw. (Spanne) | Stadtteile > 10 % (2022/2025) |
|---|---|---|---|---|---|
| Einwohner (Stadt: A0355A) | 1 017 271 | 1 085 002 | 1 092 607 | −6,15 % (−19,82 bis −0,26) | 9 / 16 |
| Anteil unter 18 | 16,1 % | 16,17 % | 15,69 % | −0,83 % (−10,73 bis +14,86) | 3 / 7 |
| Anteil ab 65 | 17,7 % | 17,75 % | 18,29 % | −0,17 % (−21,73 bis +8,95) | 1 / 10 |

Je Stadtteil: `vergleich_zensus_stadtstatistik.tsv`; Kennwerte: `vergleich_zusammenfassung.tsv`. Gründe:
- **Niveau:** Nach Herausrechnen des stadtweiten Faktors 0,9376 beträgt der Betrag der Abweichung im Median 1,77 %; die Verteilung ist ähnlich. Der amtliche Wert 31.12.2022 (IT.NRW, 1 021 253, `pipeline/kontext.py`) liegt 0,39 % über der Zensussumme und 5,88 % unter A0355A.
- **Stichtag:** Zensus 15.05.2022, Stadt ungeprüft; eine Zunahme danach vergrößert den Abstand (Elsdorf: A0355A 2022–2025 +52,51 %, Abweichung zum Zensus −1,57 % bzw. −35,46 %).
- **Nenner:** Städtische Anteile mit Nebenwohnsitz (2022: 0,65 %).
- **Methode der Pipeline:** Zellen ohne Altersangabe zählen mit 0; ohne sie im Nenner wären es 16,8 statt 16,1 % bzw. 18,4 statt 17,7 %. Flächenanteilige statt Mittelpunkt-Zuordnung ändert die Einwohner je Stadtteil im Median um +0,02 % (Spanne −2,78 bis +6,34 %).
- **Ungeklärt:** Abstände von 10,6 bis 19,8 % in Meschenich, Bayenthal, Mülheim und Neubrück (2022); Datendifferenzen, keine Merkmale der Stadtteile.

**Optionen** (in jedem Fall beide Quellen getrennt ausweisen): (a) Zensus behalten, Stadtstatistik daneben; (b) Einwohner und Altersanteile durch die Stadtstatistik ersetzen, Zensus nur für Merkmale ohne städtisches Gegenstück (Nettokaltmiete); (c) Zensus-Kennzahlen entfernen.

## 6. Wegweiser Kommune

OpenAPI 3.0.3, `info.version` 3.12.0; Datenstand `2026-10-15T08:45:18.099083Z-ec57fa` (Text, kein JSON). 393 Indikatoren, bei 292 von 322 kommunalen ist 2023 das letzte Jahr. Köln `koeln` (AGS 05315000), Bonn `bonn`, Wuppertal `wuppertal`. Nur friendlyUrls sind über Datenstände stabil. CSV-Export mit Zeilenkopf „Name (Einheit)“, Tausenderpunkt, Dezimalkomma, „k.A.“. CC0 gilt pauschal, auch für 104 Indikatoren mit Unternehmen als Datenhalter, darunter 6 von Nexiga GmbH; ob die Stiftung diese Werte unter CC0 stellen darf, geht aus der Seite nicht hervor.

| Prio. | friendlyUrl | Köln | 2023 Wegweiser | 2023 Stadt | Unterschied | letztes Jahr |
|---|---|---|---|---|---|---|
| A | `bevoelkerung` | A0355A | 1 087 353 | 1 088 964 | Stichtag Köln ungeprüft | 2023 |
| A | `bevoelkerungsentwicklung-ueber-die-letzten-5-jahre` | aus A0025A | 0,2 | 0,51 (abgel.) | Nenner aktueller Stand | 2023 |
| A | `durchschnittsalter` | A0022S | 42,2 | 42,36 | Bezugsbevölkerung ungeprüft | 2023 |
| A | `jugendquotient` | Altersgruppen | 28,1 | 24,31 (abgel.) | Grenze 20 statt 18 | 2023 |
| A | `altenquotient` | Altersgruppen | 27,6 | 26,98 (abgel.) | Nenner 20–64 statt 18 bis unter 65 | 2023 |
| A | `sgb-ii-quote` | C0007P | 12,5 | 12,42 | Nenner unter 65 / bis Rentenalter | 2023 |
| A | `arbeitslose-an-den-svb` | D0001P | 10,7 | 8,58 | Nenner: alle zivilen Erwerbspersonen | 2023 |
| A | `beschaeftigungsquote` | D0011P | nicht abgerufen | 59,83 | Altersgrenze Zähler ungeprüft; BA-Revision | 2023 |
| A | `auslaenderanteil` | A0002P | 20,4 | 20,86 | Nenner Köln mit Nebenwohnsitz (A0025A) | 2023 |
| B | `einpersonen-haushalte` | A0273P | k.A. (2022: 48,4) | 51,74 | Nexiga; Verfahrenswerte | 2022 |
| B | `haushalte-mit-kindern` | A0275P | k.A. (2022: 26,1) | 18,00 | Nexiga; Kinderbegriff | 2022 |
| B | `wohnflaeche-pro-person` | B0022S | nicht abgerufen | 40,31 | ohne Wohnheime | 2023 |
| Res. | `kinderarmut`, `einwohnerdichte` | nur Katalog | 21,0; 26,8/ha | – | Köln je km² | 2023 |

Für Haushaltsgröße und Wohnungsbau gibt es keinen Wegweiser-Indikator. Der Wegweiser liegt zwei Jahre (Haushalte drei) hinter der Stadtstatistik. Werte nicht vermischen; Herleitung in `export_koeln_2023.tsv`, Wortlaut in `wegweiser_vorschlag.tsv`.

## 7. Abbildung auf den Datenvertrag v1

| Datei | Belegung | noch offen |
|---|---|---|
| `indikatoren.tsv` | `koeln_<ID>` + A/P/S; `typ`-Vorschlag: anzahl 882, anteil 500, quote 53, mittelwert 44, dichte 6 (39 unsicher); Zähler/Nenner für 34 der 48 veröffentlichten Nicht-Anzahlen nachgerechnet | `metatext`, Wortlaut `namensnennung`, `nenner_id` bei 456 Katalog-Anteilen, Typen für Indizes, Raten, Messwerte |
| `werte.tsv` | XLSX, lange Form; `*` → `geheim`, leer → `fehlt`, eigene Ableitungen → `abgeleitet` | Werte für 1 313 Indikatoren nur im Katalog; Sozialräume |
| `raum/*.geojson`, `zuordnung.tsv` | Stadtteile, Bezirke aus `data/geo/`; `eltern_id` aus der Nummer, durch Summenprobe bestätigt | Quartiersgeometrie, `flaechenanteil` (Phase 2) |
| `gesamtstadt.tsv` | `kommune` = `koeln`, friendlyUrl, Vorschlag `indikator_id` = `ww_<friendlyUrl>` | Abbildung von „k.A.“ |
| `meta.json` | `abrufdatum` 2026-11-10, `veroeffentlichen` = true | `datenstand` 15.10. oder 06.07.2026 |

## 8. Lücken und Risiken

- Lizenz und Namensnennung nur über das Portal belegt; Kontakt in der Datei: statistik-dwh@stadt-koeln.de.
- Stichtage, Schätzwertkennzeichnung, Bedeutung der Quartiersziffern 4–9 und Sozialraumzuordnung ungeprüft.
- Auffälligkeiten: B0009A (Stadtteil 304, 2018: 79, Quartierssumme 103); 82 Reste Gesamtstadt minus Bezirke ungleich Sozialraum 10099; leere Quartierszellen bei E0001A wirken wie 0.
- Wegweiser unversioniert, Werte gerundet, JSON-Weg ungeprüft, Berechtigung zur CC0-Freigabe von Unternehmensdaten nicht belegt.

## 9. Offene Fragen an den Auftraggeber

1. Zensus-Kennzahlen: Option (a), (b) oder (c)?
2. Falls Zensusanteile bleiben: Zellen ohne Altersangabe weiter mit 0 zählen?
3. Einwohnerzahl im Panel: A0355A (Hauptwohnsitz) oder A0025A (mit Nebenwohnsitz)?
4. `werte.tsv` aus der XLSX statt der CSV?
5. E0001A: leere Zellen als `fehlt` (Vertragsregel) oder als 0?
6. Sozialräume in eine neue Vertragsversion aufnehmen?
7. Neue `typ`-Werte für 39 unsichere Indikatoren oder zurückstellen?
8. `gesamtstadt.tsv` mit `kommune` = `koeln`, `indikator_id` = `ww_<friendlyUrl>`, „k.A.“ als leerer Wert?
9. Wegweiser: Priorität A übernehmen, Nexiga-Indikatoren bis zur Klärung zurückstellen, Stiftung über die Nutzung informieren?
10. Anfrage an die Statistikstelle (Namensnennung, Stichtage, Schätzwerte, BA-Schwelle, Quartiersnummer, B0009A, weitere Indikatoren) – Versand durch den Auftraggeber?
11. Weitere Abrufe freigeben: Beschreibungsressource, Quartiersgeometrie bzw. GeoPackage, Nutzungsbedingungen des Wegweisers (je 1 Anfrage)?
12. Prompt korrigieren: Datensatz-URL (404), BA-Schwelle, Sozialräume?

**Entscheidungen des Auftraggebers (10.11.2026):** Frage 1: Option (b). Frage 3: Einwohnerzahl aus A0355A (Hauptwohnsitz); Altersanteile aus den veröffentlichten Anteilen mit Bezug auf A0025A, Bezug im Metatext genannt. Frage 4: XLSX. Frage 5: leer gilt als `fehlt`. Frage 7: die 39 unsicheren Indikatoren werden zurückgestellt. Frage 9: Priorität A und `wohnflaeche-pro-person`; die Nexiga-Indikatoren bleiben bis zur Klärung zurückgestellt. Frage 10: Die Statistikstelle hat laut Auftraggeber Nutzung und Veröffentlichung zugestimmt; weitere Abrufe brauchen je eine Freigabe. Phase 1 schreibt alle Indikatoren mit Werten, zunächst ohne Quartiere (Speicherbedarf); die Quartiere folgen in Phase 2 mit ihrer Geometrie.

## 10. Anlagen

`audit_abruf.tsv`, `audit_quellen.tsv`; Katalog: `indikatoren_katalog.tsv` (Spalten: `spaltenbeschreibung.tsv`), `kennzahlen_katalog.tsv`, `geheimhaltung.tsv`, `datenblatt_struktur.tsv`, `verschachtelung.tsv`, `verhaeltnis_pruefung.tsv`; Raum: `raum_abgleich.tsv`, `raumebenen_ratsatlas.tsv`; Zensus: `vergleich_zensus_stadtstatistik.tsv`, `vergleich_zensus_stadtstatistik_bezirke_stadt.tsv`, `vergleich_zusammenfassung.tsv`, `zensus_zuordnung_mittelpunkt_flaeche.tsv`; Wegweiser: `wegweiser_vorschlag.tsv`, `wegweiser_endpunkte.tsv`, `export_koeln_2023.tsv`.

## 11. Phase 4: Verifikation (13.11.2026)

Prompt Phase 4: Stichprobe von 20 Werten gegen die Originalquelle, Lizenzhinweise vollständig, Datenstand dokumentiert. Ergebnis: `data/strukturdaten/audit_verifikation.tsv` (Spalten und Verfahren in `meta.json` unter `audit_verifikation_spalten` und `verifikation`), Skript `explore/strukturdaten/verifikation.py`.

**Abrufe** (je 1 Anfrage, keine an die OParl-API; das Protokoll nennt Zeit, Status, Größe und Typ; Adressen nachgetragen: XLSX wie in `meta.json` unter `quellen` (`statistischer-datenkatalog-koeln`), Wegweiser `https://www.wegweiser-kommune.de/data-api/rest/export/bevoelkerung+durchschnittsalter+sgb-ii-quote+koeln+2022-2023+tabelle.csv?charset=UTF-8`):

| Ziel | Zeit | Status | Bytes | SHA-256 |
|---|---|---|---|---|
| offenedaten-koeln.de: Statistischer Datenkatalog Köln (XLSX) | 13.11.2026, 09:41:50 MEZ | 200 | 12 329 414 | `0645793fe92d248859bb979b80fe2c854e850789c485dbca2ae644e61e473382`, gleich dem Abruf vom 10.11.2026 (`meta.json`, `quellen`); Blatt Info: „Auswertung erstellt am 15.10.2026“ |
| wegweiser-kommune.de: Datenexport (CSV) Bevölkerung, Durchschnittsalter und SGB II-Quote, Köln, 2022–2023 | 13.11.2026, 09:42:02 MEZ | 200 | 910 | `f0398bda1edc80df7b2e056c423f77309200179bbbb85b84eae4b589f50cf48d` |

**Verfahren.** Gezogen wird nur aus den veröffentlichten Dateien, mit `random.Random(20261113)` (Python 3.13). Je Raumebene 5 Plätze: `gesamtstadt` 1 abgeleiteter Anteil (`koeln_abg_unter18`) und 4 `ok`, `stadtbezirk` 1 `fehlt` und 4 `ok`, `stadtteil` 1 abgeleiteter Anteil (`koeln_abg_ab65`) und 4 `ok`, `quartier` 1 `geheim`, 1 `fehlt` und 3 `ok`. Je Platz wird gezogen, bis Indikator (in der ganzen Stichprobe) und Jahr (in der Raumebene) neu sind; so stehen 20 verschiedene Indikatoren aus 10 Jahren zwischen 2013 und 2024 in der Stichprobe. Geheim gehaltene Zellen kommen nur aus Indikatoren, die keine Anzahl sind und an keiner in `indikatoren.tsv` genannten Beziehung beteiligt sind. Das Skript importiert die Pipeline nicht, prüft die Prüfsumme der XLSX gegen `meta.json` und sucht jede Zelle selbst (Blatt Daten: Spalte nach dem Code im Kopf, Zeile nach Jahr und Raum). Verglichen werden Wert und Status, Fundstelle mit `quellobjekt`, Name des Indikators mit dem Kopf der Spalte, Einheit mit der Endung des Codes und dem Format im Blatt Katalog, Jahr, Nummer und Name der Raumeinheit mit `raum/<raumebene>.geojson`, bei Stadtteilen und Quartieren die Zuordnung in `zuordnung.tsv` und `eltern_id`. Die beiden abgeleiteten Anteile sind aus den veröffentlichten Eingangswerten derselben Zeile nachgerechnet (dezimal, kaufmännisch auf 2 Stellen), ihre Eingangszellen ebenso in der XLSX geprüft. Von geheim gehaltenen Zellen wird nur der Status verglichen; die Datei enthält dazu keinen Wert. Dazu alle 6 Werte des Wegweiser-Exports gegen `gesamtstadt.tsv`, Indikator und Einheit über den Zeilenkopf („Bevölkerung (Anzahl)“ usw.).

**Ergebnis.** 26 Zeilen: 25 gleich (15 Werte mit status `ok`, 2 abgeleitete Anteile, 2 leere Zellen mit status `fehlt`, 6 Wegweiser-Werte), 1 nur Status (`geheim`), keine Abweichung. Alle 20 selbst gesuchten Fundstellen stimmen mit `quellobjekt` überein, alle Namen, Einheiten, Jahre und Raumeinheiten mit den veröffentlichten Dateien. Eine Gegenprobe mit drei absichtlich veränderten Werten in einer Kopie der Daten meldete alle drei als abweichend. Grenzen: 20 von rund 1,62 Mio. Zeilen zeigen, dass Spalten, Zeilen, Raumeinheiten und Schreibweise richtig zugeordnet sind; einzelne seltene Fehler schließen sie nicht aus.

**Lizenzhinweise und Datenstand.** Geprüft: README, Quellenzeile der Karte (`site/index.html` und ihre Fassung aus `meta.json`), Panel, Flächenfarben und Tabelle der Strukturdaten, `data/LICENSE-DATA.md`, `LIESMICH.txt` des Datenpakets. Ergänzt: der Wortlaut der Namensnennung des Statistischen Datenkatalogs („Stadt Köln, Amt für Stadtentwicklung und Statistik (Statistischer Datenkatalog Köln); in lange Tabellenform umgeformt, Werte unverändert“) mit Link auf Lizenz und Datensatz in README, Quellenzeile, Panel und Legende; die Quellenangabe „Bertelsmann Stiftung, wegweiser-kommune.de“ in README und Quellenzeile; Abrufdatum neben dem Datenstand in Quellenzeile, Panel und Legende; Lizenz-URL und Abrufdatum des Wegweisers in `data/LICENSE-DATA.md`; eine Zeile für `audit_verifikation.tsv`. Datenstand 15.10.2026 und Abrufdatum 10.11.2026 stehen in `meta.json` (`datenstand`, `abrufdatum`, `quellen`), auf der Seite und im README; die Prüfung vom 13.11.2026 steht in `meta.json` (`verifikation`) und im README. Die Vertragsversion bleibt 1.1 (`meta.json`, `vertrag_regel`). Im Browser (Playwright, nur 127.0.0.1, Testdaten mit eingeschalteter Freigabe in einer Kopie) bei 1400 und 390 px: Quellenzeile, Panel und Legende mit allen Angaben, axe-core (WCAG 2.1 A/AA) ohne Verstoß.
