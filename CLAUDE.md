# Prompt: „ratsatlas-koeln“ – Ratsinformationen der Stadt Köln räumlich, zeitlich und nach Akteuren erschließen

> Entwurf v0.1 (04.11.2026) · Zur Ausführung in Claude Code · Vorlage: Ratsatlas Bonn (`daimpad/allris-test`, künftig `daimpad/ratsatlas-bonn`)
> Vor jeder Phase (Abschnitt 7) legst du einen kurzen Plan vor und wartest auf Freigabe.

## 1. Rolle

Du arbeitest als Webentwickler:in mit Erfahrung in Open-Data-Pipelines und Geodaten **und** als Beauftragte:r für Bürgerbeteiligung. Technische Entscheidungen triffst du so, dass Bürger:innen ohne Verwaltungswissen Ratsinformationen finden, verstehen und einordnen können. Du arbeitest quellentreu: keine erfundenen Inhalte, URLs, Feldnamen oder Zahlen; jede angezeigte Information ist auf ihr Quellobjekt rückführbar. Was du nicht messen konntest, kennzeichnest du als offen.

## 2. Rahmenentscheidungen

| Punkt | Entscheidung |
|---|---|
| Repository | `daimpad/ratsatlas-koeln`, öffentlich |
| Seitenname | **Ratsatlas Köln** |
| Code-Basis | **Unabhängige Kopie** von `daimpad/allris-test` (kein Fork, eigene Historie); Herkunft (Commit-Hash) in README und `NOTICE` dokumentiert; ein gemeinsamer Kern `ratsatlas` folgt später und ist **nicht** Teil dieses Auftrags |
| Unverändert | `daimpad/allris-test` wird nur gelesen, nie verändert |
| Gestaltung | wie Ratsatlas Bonn (Glass-Stil, Tokens aus `site/style.css`, Schrift Inter lokal, kontraststarke Violetttöne); Texte und Marke auf Köln umgestellt |
| Räumlicher Umfang | Ganz Köln von Beginn an (9 Stadtbezirke, 86 Stadtteile); kein Pilot-Stadtteil |
| Veröffentlichung | Hauptadresse `https://koeln.ratsatlas.de/` (Netcup-Webhosting, Plesk-Git aus Branch `deploy` mit Webhook, `SITE_URL`); Spiegel auf GitHub Pages `https://daimpad.github.io/ratsatlas-koeln/` mit Canonical auf die Hauptadresse |
| Build | ausschließlich GitHub Actions |
| Code-Lizenz | MIT; Daten mit eigener LICENSE-Datei (`data/LICENSE-DATA.md`) |
| Sprachmodelle | zulässig für Ortsextraktion (Stufe C) und Kurzfassungen – mit Kennzeichnung, Konfidenz und Link zum Original |
| Volltexte/PDFs | bis zur Lizenzklärung (Abschnitt 8): verarbeiten nur lokal und im Workflow-Zwischenspeicher; **keine Zitate, keine Auszüge, keine PDF-Spiegelung**; im Datenpaket nur abgeleitete Verortungen mit Fundstelle als erkanntem Namen und Dokumentteil (Regel wie in Bonn) |
| Datenschutz | keine Verortung von Wohnadressen natürlicher Personen; Anregungen und Beschwerden nach § 24 GO NRW nur auf Stadtteil- oder Straßenebene |
| Auslieferung | Ergebnisse je Phase als Zip-Paket; Audit-Protokolle als TSV |
| Arbeitsweise | diese Datei als `CLAUDE.md`; eigener Skill `.claude/skills/ratsatlas-koeln/SKILL.md` (aus dem Bonner Skill abgeleitet) |

## 3. Datenquellen (recherchiert, Stand 04.11.2026 – in Phase 1 verifizieren)

### 3.1 Primärquelle: OParl-API der Stadt Köln (SessionNet, Somacos)
- System: `https://buergerinfo.stadt-koeln.de/oparl/system`
- Body: `https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln`
- Dokumente: `…/oparl/bodies/stadtverwaltung_koeln/downloadfiles/<Nummer>.pdf`
- Oberfläche: `https://ratsinformation.stadt-koeln.de/` bzw. `https://buergerinfo.stadt-koeln.de/`
- Katalog: `https://offenedaten-koeln.de/dataset/oparl-api-koeln` (Kontakt e-government@stadt-koeln.de); Fachanwendung: 12-session@stadt-koeln.de
- Bekannt aus Stichprobe (25 Vorlagen): 25 Objekte je Seite; Referenzen `AN/NNNN/JJJJ` (Anträge/Anfragen) und `NNNN/JJJJ` (Verwaltungsvorlagen); `consultation` verweist **direkt** auf `meeting` und `agendaItem` (Prozesslinie aus einer Quelle); `underDirectionOf` fehlte; `location` nur bei 3 von 25, nur `subLocality` ohne `geojson`; sehr hohe Seitennummer → HTTP 401 (Paginierung nur über `links.next`)
- **Abrufrisiko:** Die Stadt sperrt nach Angaben des Projekts mandari seit 07.09.2026 dessen IP-Bereich, vermutlich wegen zu vieler Abrufe (`github.com/mandariOSS/mandari/issues/89`, `/issues/348`). Daher gilt die Abrufpolitik in 5.1.

### 3.2 Geobasisdaten (überwiegend dl-de/zero 2.0)
| Datensatz | Quelle | Verwendung |
|---|---|---|
| Stadtteile (86) | `offenedaten-koeln.de/dataset/stadtteile-koeln` (Shapefile ETRS89/UTM32N, JSON WGS84) | Point-in-Polygon, Filter |
| Stadtbezirke (9) | `open.nrw/dataset/stadtbezirke-koln-k` | Filter, Zuordnung Bezirksvertretung |
| Stadtgebiet | `offenedaten-koeln.de/dataset/stadtgebiet-k%C3%B6ln` | Plausibilität |
| Stadtviertel, Statistische Quartiere | `offenedaten-koeln.de/dataset/stadtviertel-koeln` | optional („Veedel“-Namen) |
| Adressen Köln | `offenedaten-koeln.de/dataset/adressen-koeln` (Shapefile, WFS, XLSX; mit ALKIS-Gebäude-ID) | Hauskoordinaten Stufe B |
| Kölner Straßenverzeichnis | `offenedaten-koeln.de/dataset/koelner-strassenverzeichnis` (XLSX, Straßenschlüssel, Hausnummernbereiche je Stadtteil) | Gazetteer; doppelte Namen nach Eingemeindung über Straßenschlüssel/Bezirkszusatz trennen |
| Straßen Köln | `offenedaten-koeln.de/dataset/strassen-koeln` | Verortung „Straße ohne Hausnummer“ |
| Bebauungspläne (rechtsverbindlich, Aufstellungsbeschlüsse) | `offenedaten-koeln.de/dataset/bebauungsplaene-koeln-bauungsplaene` (JSON, WMS) | Stufe B über Plannummer (Schema z. B. „61589/03“ verifizieren) |
| Gebäudereferenzen NRW | `opengeodata.nrw.de/produkte/geobasis/lk/akt/gebref_txt/` (EPSG 25832) | Gegenprüfung Adressen |
| Geschäfts- und Dezernatsverteilungsplan | `stadt-koeln.de/mediaasset/content/verwaltung/geschaefts-und-dezernatsverteilungsplan.pdf` (Stand 01.10.2026) | Ämtertabelle, versioniert mit Gültigkeitsdatum |

OpenStreetMap (Photon/Nominatim, ODbL) nur nachrangig für Orte ohne Adresse (Plätze, Brücken), getrennt gekennzeichnet. Bonner Abhängigkeiten von OParl-Lite (machdenstaat) entfallen.

## 4. Ziel

Eine öffentliche, statisch auslieferbare Webanwendung, die die Kölner Ratsinformationen in drei Dimensionen erschließt – jeweils mit Quellenangabe:

1. **Räumlich (Wo?)** – Karte aller Vorlagen mit Ortsbezug; Filter nach Stadtbezirk und Stadtteil, wo belegbar auf Straßen- oder Objektebene.
2. **Zeitlich (Wann? Wo steht das Verfahren?)** – Prozesslinie je Vorlage: Veröffentlichung → Beratungen (Gremium, Datum, TOP, Ergebnis wörtlich) → Folgevorlagen. Kommende Sitzungen als offene Stationen.
3. **Akteursbezogen (Wer?)** – federführendes Dezernat/Amt, befasste Gremien (Rat, Fachausschüsse, 9 Bezirksvertretungen), einreichende Fraktionen.

## 5. Funktionale Anforderungen (Abweichungen von Bonn)

### 5.1 Abruf
- Neuer Quellenadapter für SessionNet anstelle von Bonner Abruf und OParl-Lite; Ausgabe im **unveränderten Bonner Datenmodell**, damit Frontend und Export möglichst unverändert bleiben
- Abrufpolitik: 1 Verbindung, mindestens 1–2 s Abstand, nächtliches Zeitfenster, inkrementell über `modified`/`modified_since` (Unterstützung in Phase 1 messen), Backoff bis zu mehreren Stunden, User-Agent mit Projektadresse und Kontakt, Zustandsdatei und Rohdaten-Cache; **erster Vollabruf erst nach Information der Stadt**
- Fällt der Abruf aus, wird der letzte gültige Datenstand ausgeliefert und als solcher angezeigt

### 5.2 Geokodierung in drei Stufen
| Stufe | Methode in Köln | Konfidenz |
|---|---|---|
| A | `location.subLocality` → Stadtteilpolygon (Darstellung als Fläche) | mittel |
| B | Straßenverzeichnis, Adressen, Hausnummern-Regex, B-Plan-Nummern, Stadtteilnamen und Schreibvarianten; Disambiguierung über Stadtteil-Kontext und beratende Bezirksvertretung; Point-in-Polygon | mittel (Hausnummer: hoch) |
| C | LLM-Extraktion aus dem Volltext nur ohne B-Treffer, Verifikation gegen B | niedrig bis mittel, gekennzeichnet |

Zusätzlich schwache Evidenz `district_from_committee` (nur eine Bezirksvertretung beraten → Stadtbezirk). Jede Verortung trägt `method`, `confidence`, `evidence`, `source_object`, `geometry_level`.

### 5.3 Akteure
- Federführung: `underDirectionOf`, sonst Kopf der Verwaltungsvorlage („Dezernat, Dienststelle“, z. B. „II/II/2“) → Abgleich mit der Ämtertabelle; Methode und Fundstelle ausweisen
- Fraktionen: `originator*`, sonst Titel- und Typmuster („Antrag nach § 3“, „Anfrage nach § 4“, „Antrag der …-Fraktion“), datumsabhängig (Wahlperiode ab Kommunalwahl 2025)

### 5.4 Funktionsumfang der ersten Auslieferung
Übernommen und auf Köln umgestellt: Karte, Liste, Vorgang mit Prozesslinie, Gebiete (Stadtbezirke/Stadtteile), Startansicht ganz Köln mit anklickbaren Stadtbezirken, Suche, Verstehen (Begriffe, Verlässlichkeit), Datenpaket, Feeds, Datenschutz, Quellen- und Lizenzhinweise, graue Kartenkacheln für das Kölner Stadtgebiet.
**Deaktiviert, nicht gelöscht** (per Konfiguration abschaltbar, spätere Freigabe einzeln): Bonn-spezifische Zusatzthemen wie Haushalt, Baustellen, Wahlen/Kandidaturen, Themenseiten, Ratsassistent (Chat) – endgültige Liste ergibt sich aus der Inventur in Phase 0.

## 6. Verbote

- keine Änderungen an `daimpad/allris-test`
- keine Bonner Daten (`data/`) in das Kölner Repository übernehmen
- keine Zugangsdaten im Repository; Netcup-Zugang nur manuell durch den Auftraggeber
- keine Volltexte, Zitate oder PDFs im Repository, auf der Seite oder im Datenpaket bis zur Lizenzklärung

## 7. Vorgehen in Phasen (nach jeder Phase Bericht und Freigabe)

0. **Kopie und Inventur**
   - `gh auth status`; Repo `daimpad/ratsatlas-koeln` anlegen; Code aus `allris-test` **ohne** `data/`, ohne Historie übernehmen (`git archive`), erster Commit „Ausgangsstand aus allris-test @<Hash>“
   - `inventur_module.tsv`: je Datei/Modul (`pipeline/*.py`, `site/*.js`, Workflows, Seitenverzeichnisse) Einordnung *generisch* / *Bonn-spezifisch, anpassen* / *Bonn-Zusatzthema, deaktivieren* / *entfernen*, mit Begründung
   - alle Fundstellen von „Bonn“, Bonner URLs, `SITE_URL`, OParl-Lite, Ortsteil- und Bezirksnamen auflisten
   - Ergebnis: Inventurbericht und Plan; noch keine Köln-Logik
1. **Exploration Köln (ohne Produktionscode, Skripte unter `explore/`)**
   - API messen (gedrosselt): Gesamtzahlen `papers`/`meetings`/`organizations`, Seitengröße, `limit`, `modified_since`, Ende von `links.next`
   - Stichprobe ≥ 500 Vorlagen über mehrere Jahre: Abdeckung `underDirectionOf`, `originator*`, `mainFile`/`auxiliaryFile`, `location`-Felder, `agendaItem.result`; Listen aller `paperType` und `organizationType`
   - 100 Verwaltungsvorlagen: Erkennungsquote „Dezernat, Dienststelle“ im PDF-Kopf
   - Geodaten laden: Feldnamen, Koordinatensystem, Stand; B-Plan-Nummernschema
   - Bericht wie Bonner `BERICHT_phase0.md`: Anteil Stufe A/B/C (Schätzung), Datenqualität, Lücken, Risiken
2. **Datenpipeline**: SessionNet-Adapter, inkrementeller Abruf, Normalisierung ins Bonner Modell, Abrufstatistik als TSV
3. **Geokodierung** nach 5.2 mit `audit_geokodierung.tsv`; manuelle Prüfung von 50 Vorlagen je Methode, Präzision im Bericht
4. **Frontend**: Texte, Marke, Startansicht, Gebiete, Glossar auf Köln; Kartenkacheln für Köln; WCAG-2.1-AA-Prüfung (axe, Tastatur, Kontrast)
5. **Repository und Deployment**: README (Ziel, Herkunft aus allris-test, Quellen, Lizenzen, Grenzen, Datenstand), LICENSE, `data/LICENSE-DATA.md`, CONTRIBUTING, Issue-Vorlagen; Workflows (täglicher Lauf, `deploy`-Branch ohne Historie, Pages-Spiegel); Plesk-Checkliste für den Auftraggeber
6. **Verifikation**: Stichprobe gegen das Kölner RIS, Linkprüfung, Lizenz- und Datenschutzhinweise vollständig, Audit-TSVs im Zip-Paket

## 8. Offene Punkte

- **Lizenz** der OParl-Daten und PDFs: Katalog nennt dl-de/zero 2.0, Portal verlangt zugleich Namensnennung („Datenquelle: Stadt Köln – offenedaten-koeln.de“), Nutzungsbedingungen nennen CC BY 3.0 DE, Body-Feld `license` leer → schriftliche Anfrage an e-government@stadt-koeln.de und 12-session@stadt-koeln.de (Lizenz, abgeleitete Daten, Abrufrate, Massenexport); bis dahin Namensnennung immer angeben
- zulässige Abrufrate; ob Abrufe aus GitHub-Actions-IP-Bereichen toleriert werden
- Abdeckung `underDirectionOf` und Qualität der PDF-Kopf-Erkennung
- Feldnamen der Geodaten, B-Plan-Nummernschema
- Umgang mit nicht öffentlichen TOPs und zurückgezogenen Vorlagen
- welche Bonner Zusatzthemen für Köln später sinnvoll sind

## 9. Entscheidungen des Auftraggebers

| Datum | Entscheidung |
|---|---|
| 04.11.2026 | Dieser Prompt v0.1 ist verbindlich; der Recherchebericht vom selben Tag dient als Hintergrund (bei Widersprüchen gilt v0.1, u. a. Repository-Name, Kern später, keine Zitate). |
| 04.11.2026 | Bonner Berichts-, Phasen-, Test- und Evaluationsverzeichnisse werden nicht übernommen. |
| 04.11.2026 | Die Stadt Köln ist noch nicht informiert: bis auf Weiteres keine Abrufe der Kölner OParl-API aus der Arbeitsumgebung oder aus Workflows; Explorationsskripte werden vorbereitet, nicht ausgeführt. |
| 04.11.2026 | Workflows sind nach `.github/workflows-inaktiv/` verschoben (nicht aktiv); `static.yml` (Pages-Vorlage für das ganze Repository) ist abgeschaltet. |
| 04.11.2026 | Repository https://github.com/daimpad/ratsatlas-koeln, Hauptadresse koeln.ratsatlas.de. |
| 04.11.2026 | Einfache Sprache, Kurzfassungen, „Mitmachen“, Gremienbesetzung und Kölner Vorschaubild folgen im zweiten Lauf; bis dahin deaktiviert. |
| 04.11.2026 | Phase 1: Messskripte für die OParl-API werden geschrieben, nicht ausgeführt; Entwurf der Anfrage an die Stadt; Geodaten einmalig laden (freigegeben). |
| 04.11.2026 | Hausnummern punktgenau nur bei Verwaltungsvorlagen und politischen Anträgen; Eingaben nach § 24 GO und Vorlagen natürlicher Personen nur auf Straßen- oder Stadtteilebene. |
| 04.11.2026 | Entwurf der Anfrage an die Stadt (`explore/ANFRAGE_stadt_koeln.md`) freigegeben; Versand durch den Auftraggeber. |
| 04.11.2026 | Phase 2 wird ohne Abrufe vorbereitet: SessionNet-Adapter mit Tests gegen einen lokalen Testserver, Kölner Gebiets- und Straßendaten aus den Geodaten. |
| 04.11.2026 | Workflow `tests.yml` aktiv (nur Tests mit synthetischen Daten, keine Anfragen an die Stadt); alle übrigen Workflows bleiben inaktiv. |
| 04.11.2026 | Phase 3 (Geokodierung) wird ohne Abrufe begonnen: Stufe A über `subLocality`, Doppelnamen, eindeutige Bezirksformen, Hausnummern-Regel, `district_from_committee`, Tests mit erfundenen Titeln. |
| 04.11.2026 | Pull Request #2 zusammengeführt; Phase 4 (Frontend) freigegeben, einmaliger OSM-Ausschnitt für die Kartenkacheln erlaubt. |
| 04.11.2026 | Phase 5 freigegeben; `kacheln.yml` aktiv. Die Anfrage an die Stadt ist noch nicht versendet; der Abruf bleibt gesperrt. |
| 04.11.2026 | Herkunft in README und NOTICE: `daimpad/ratsatlas-bonn` (umbenannt aus `daimpad/allris-test`; Commit `9eea7ea`). |
| 04.11.2026 | Pull Request #4 zusammengeführt, `kacheln.yml` auf `main` gestartet. Freigegeben: eigener Skill `ratsatlas-koeln` (Bonner Skill entfernt) und Phase 6, soweit ohne Abruf möglich (Linkprüfung, Lizenz- und Datenschutzhinweise, Datenpaket). Ämtertabelle aus dem Dezernatsverteilungsplan erst nach Information der Stadt. |
