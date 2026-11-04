# RIS-Karte Bonn – Technik

Technische Beschreibung von Pipeline, Seite und Betrieb. Worum es inhaltlich geht, steht in der [README](README.md).

## Aufbau des Repositorys

- `pipeline/` – Abruf, Aufbereitung, Geokodierung (`geocode.py`, `geo.py`, `plans.py`), Akteure (`actors.py`), Themen (`topics.py`), Prozessschritte (`process.py`), Export (`export.py`, `publish.py`, `chat.py`), Prüfung (`check.py`, `verify.py`), Auffindbarkeit (`seo.py`, `gebietsseiten.py`), Baustellen (`baustellen.py`, `kandidaten.py`)
- `site/` – statische Seite: Leaflet mit OSM-Kacheln (`app.js`), Zeitleiste (`timeline.js`), Tour (`tour.js`), Reiter „Prozesse“ (`prozesse.js`), „Mitmachen in Bonn“ (`beteiligung.js`), Ratsassistent (`chat/`)
- `data/` – Gremien, Ämter, Sitzungen (`raw/`), Flächen und Straßenverzeichnis (`geo/`), Pilot Endenich und Audits (`export/`), Lizenzen je Datei (`LICENSE-DATA.md`)
- `baustellen/` – Berichte der Phasen 0 bis 5 zu Bebauungsplänen und Baustellen, Anfrage an die Stadt
- `prozess/`, `phase0/` – Exploration der Prozessebene und der Datenquellen
- `eval/` – Fragenkatalog und Auswerteskript für den Ratsassistenten
- `tests/` – Unit-Tests (Python) und `tests/js/` (Node)
- `.github/` – Workflows und Issue-Vorlagen; `CLAUDE.md`, `docs/` – Projektprompts

## Pipeline

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pipeline all      # fetch → build → export → check → verify → package
```

| Schritt | Ergebnis |
|---|---|
| `fetch` (`fetch-papers`, `fetch-organizations`, `fetch-meetings`, `fetch-plans`, `fetch-housenumbers`, `fetch-lite`, `fetch-streets`) | Rohdaten in `data/raw/`, Geltungsbereiche in `data/geo/bebauungsplaene_bonn.geojson`, Hausnummernverzeichnis in `data/geo/hausnummern_bonn.json`, Änderungsprotokoll der Pläne; Abrufzeitpunkte in `STAND.json` |
| `gazetteer` | `data/geo/strassen_bonn.json`: Straßenverzeichnis aus OSM mit Ortsteilen je Straße |
| `build` | `data/build/allris.sqlite`: Vorlage, Beratung, Sitzung, Tagesordnungspunkt, Organisation, Vorlagenbeziehung, Ort, Ortsbezug, Einreichende, Zuständigkeit, Plannummer |
| `export` | `data/export/endenich/` (Pilot, im Repository) und `data/export/bonn/` (je Ortsteil, Bezirk und Jahr, `zeit.json`, `prozesse.json`, `suche.json`, `plaene.json`, Feeds, Kalender, GeoJSON, DCAT, Daten des Assistenten); Audits als TSV |
| `check`, `verify` | Kennzahlen, Abgleich Stufe B gegen A, Datenschutzprüfung (bricht bei Hausnummern ab); Stichprobe gegen die OParl-API |
| `package` | `data/export/allris-bonn-export.zip` mit `LIESMICH.txt` |
| `seo` | `robots.txt`, `sitemap.xml`, statische Seiten je Gebiet, absolute Adressen aus `SITE_URL` |
| `baustellen` | tägliches Archiv der Baustellen (Branch `archiv`) |
| `kandidaten`, `baustellen-seite` | Audit Beschluss ↔ Baustelle mit Stichprobe; `data/export/bonn/baustellen.json` für die Seite |

Lokale Vorschau:

```bash
mkdir -p _site/data/geo && cp -r site/. _site/ && cp -r data/export _site/data/ \
  && cp data/LICENSE-DATA.md _site/data/ && cp data/geo/*.geojson _site/data/geo/
python3 -m http.server -d _site 8000
```

Tests: `.venv/bin/python -m unittest discover tests` und `node --test "tests/js/**/*.test.mjs"`.

Browser-Prüfung der zusammengestellten Seite (Playwright mit Chromium, axe-core für WCAG 2.1 A und AA): Start mit der Übersicht, Klick auf Stadtbezirk und Ortsteil, Link mit Gebiet und Vorgang, Prozesse, Mitmachen in Bonn, Kartenmenü bei 390 px, Tour bis zum Ende. Der Workflow `tests.yml` führt sie bei jedem Pull Request aus; die Rohdaten kommen aus dem Zwischenspeicher des täglichen Laufs.

```bash
npm install --prefix tests/browser && (cd tests/browser && npx playwright install chromium)
python3 -m http.server -d _site 8765 &
node --test "tests/browser/*.test.mjs"     # andere Adresse: SITE=http://localhost:8000/
```

## Geokodierung

Die Verortung ist regelbasiert. Sie nutzt reguläre Ausdrücke und Geometrie (shapely), kein Sprachmodell, und arbeitet nur mit Titel und Metadaten der Vorlagen. Sie läuft im Schritt `build` (`pipeline/build.py`) und schreibt die Tabellen `location` (Orte) und `paper_location` (Ortsbezug je Vorlage) in die SQLite-Datenbank. `export` gibt die Ergebnisse an Seite, GeoJSON und Audits weiter.

| Stufe | Methode | Konfidenz |
|---|---|---|
| A | `location` aus der OParl-API (Punkt der Stadt; Ortsteil per Point-in-Polygon) | hoch |
| B | Straßen-, Ortsteil- und Bezirksnamen im Titel; Straßenpunkt = Mitte des längsten Abschnitts je Ortsteil (OSM); Eingrenzung mehrdeutiger Straßen über genannten Ortsteil oder befasste Bezirksvertretung; Folgevorlagen erben den Ortsbezug (`vererbt`, höchstens „mittel“) | mittel, bei Mehrdeutigkeit niedrig |
| B3 | Plannummern im Titel (Listen, Zusätze wie „Teil A“), abgeglichen mit den Geltungsbereichen: eindeutig, Grundnummer, mehrdeutig, nicht im Datensatz; Ortsteile über Überschneidung ab 5 %; ein eindeutiger Plan hat Vorrang vor Straßen- und Ortsnamen | hoch bei eindeutigem Plan, sonst niedrig |
| C | Volltext mit Sprachmodell | zurückgestellt (Lizenz der PDFs) |

### Grundlagen

- **Flächen:** 51 Ortsteile und 4 Stadtbezirke der Stadt Bonn (CC0) in `data/geo/`.
  - `pipeline/geo.py` hält sie in einem räumlichen Index (STRtree).
  - Er beantwortet zwei Fragen: In welchem Ortsteil liegt ein Punkt (Point-in-Polygon)? Welche Ortsteile schneidet eine Fläche, und zu welchem Anteil?
- **Straßenverzeichnis** (`python -m pipeline gazetteer` → `data/geo/strassen_bonn.json`, `Gazetteer._streets` in `pipeline/geocode.py`), derzeit 2.376 Straßennamen:
  1. Abruf aller benannten OSM-Ways mit `highway`-Tag im Stadtgebiet, in Kacheln über Overpass. Haltestellen, geplante, abgerissene und aufgegebene Wege bleiben außen vor (`SKIP_HIGHWAY`).
  2. Abschnitte gleichen Namens werden zusammengeführt. Abschnitte, die mehr als 150 m auseinanderliegen, gelten als getrennte Lagen (`component`). Derzeit haben 23 Namen mehr als eine Lage, zum Beispiel „Kapellenstraße“.
  3. Jede Lage wird mit den Ortsteilen verschnitten, in einer flächentreuen Projektion in Metern. Ein Ortsteil zählt, wenn mindestens 150 m oder 15 % der Straße darin liegen.
  4. Je Straße und Ortsteil gilt als Punkt die Mitte des längsten Abschnitts. Ein Straßenpunkt steht damit für die Straße im Ortsteil, nicht für ein Gebäude.
  5. Straßennamen, die nur in den OParl-Orten der Stadt vorkommen, werden zur Laufzeit ergänzt (`_add_points`, Quelle `oparl-bonn`).
  6. **Kreuzungen** (`_crossings`): Für je zwei Straßen, deren Linien sich berühren, speichert das Verzeichnis die Ortsteile der Berührungspunkte (derzeit 4.532 Paare, Schlüssel `kreuzungen`).
- **Namensvarianten der Ortsteile** (`ORTSTEIL_ALIASES`):
  - Teilnamen zusammengesetzter Ortsteile, etwa „Lessenich“ und „Meßdorf“ für „Lessenich/Meßdorf“.
  - Adjektive auf „-er“ wie „Endenicher“.
  - Für die Bezirke Bad Godesberg, Beuel und Hardtberg die Namen samt Adjektiv (`BEZIRKE`).
  - Ortsteil- und Bezirksnamen sind als Straßennamen gesperrt, damit „Beuel“ nicht als Straße gilt.

### Ablauf je Vorlage

**Stufe A – Ort der Stadt** (`pipeline/build.py`, Schleife über `location`)
- Enthält die Vorlage in der OParl-API ein Feld `location` mit Punktgeometrie, wird die Koordinate übernommen, Konfidenz „hoch“, Methode `oparl_location`.
- Der Ortsteil ergibt sich per Point-in-Polygon.
- Orte ohne Koordinate werden mit Konfidenz „niedrig“ gespeichert und erscheinen nicht auf der Karte.
- Straße und Beschreibung werden wörtlich übernommen. `check` bricht ab, sobald darin eine Ziffer außer einer Postleitzahl steht.

**Stufe B – Namen im Titel** (`Gazetteer.locate` in `pipeline/geocode.py`)
1. **Straßen:**
   - Ein regulärer Ausdruck enthält alle Straßennamen ab vier Zeichen, die längsten zuerst. So gewinnt „Marienforster Steinweg“ vor „Steinweg“.
   - Es gelten Wortgrenzen, und „Straße“ wird auch als „Strasse“ oder „Str.“ erkannt.
   - Gefundene Stellen werden im Titel ausgeblendet, damit ein Ortsteilname in einem Straßennamen nicht doppelt zählt.
2. **Ortsteile:** im verbleibenden Text, mit den Varianten oben. Auch nach einem Bindestrich wird gesucht, etwa „Bonn-Endenich“. Dazu Genitivformen („Rüngsdorfs“, „Bad Godesbergs“; nicht „Pützchens“, das in Eigennamen wie „Pützchens Markt“ steht) und Schreibvarianten aus den Titeln (R3, `ORTSTEIL_VARIANTEN` und `BEZIRK_VARIANTEN`, etwa „Poppeldorf“, „Bad-Godesberg“; Methode `ortsteil_variante` bzw. `stadtbezirk_variante`, Konfidenz wie der Name).
3. **Stadtbezirke:** ebenso im verbleibenden Text.
4. **Eingrenzung einer Straße** (`_resolve_street`), in dieser Reihenfolge:

   | Lage | Methode | Konfidenz |
   |---|---|---|
   | Auf die Straße folgt eine Hausnummer, die das Verzeichnis der Stadt genau einem Ortsteil zuordnet, und das Straßenverzeichnis hat dort einen Abschnitt (seit 20.10.2026). Ein genannter Ortsteil derselben Straße wird dann nicht zusätzlich verortet; er meint meist die Gemarkung | `strasse+hausnummer` | mittel |
   | Der Titel nennt einen Ortsteil, in dem die Straße liegt | `strasse+ortsteil` | mittel |
   | Der Titel nennt eine zweite Straße, die diese kreuzt; es gilt der Ortsteil der Kreuzung (R1, seit 20.10.2026) | `strasse+kreuzung` | mittel |
   | Mehrere getrennte Lagen; der genannte Bezirk oder der Bezirk der befassten Bezirksvertretung lässt genau eine übrig | `strasse+bezirk` | mittel |
   | Mehrere Lagen, keine Eingrenzung möglich | `strasse_mehrdeutig` | niedrig |
   | Eine Lage, die außerhalb des Bezirks der befassten Bezirksvertretung oder des genannten Bezirks liegt | `strasse` | niedrig |
   | Eine Lage ohne Widerspruch | `strasse` | mittel |

   Hausnummer: Ziffern direkt nach dem Straßennamen, auch „Nr. 12“, „12a“, „12-14“; nicht „Str. 2. Bauabschnitt“ und keine Jahreszahlen (1900–2100). Die Nummer bestimmt nur den Ortsteil: Punkt bleibt der Straßenabschnitt, die Fundstelle enthält keine Nummer. Verzeichnis: `data/geo/hausnummern_bonn.json` (`fetch-housenumbers`; Straße → Ortsteil → Nummern, Ortsteil per Point-in-Polygon, ohne Koordinaten einzelner Adressen). Wirkung je Vorlage und Straße in `data/export/audit_hausnummern.tsv` (bestätigt, eindeutig, geändert, ohne Wirkung).

   Namen, die im Titel oft keine Straße meinen („Rheinufer“, „Markt“, „Kirchberg“, „Wasserland“), erhalten stets „niedrig“.
5. **Ortsteile ohne Straßentreffer:** Ein genannter Ortsteil, für den keine Straße gefunden wurde, wird als Fläche mit innerem Punkt eingetragen.
   - Methode `ortsteil_name` oder `ortsteil_adjektiv`, Konfidenz „mittel“.
   - Die Konfidenz sinkt auf „niedrig“, wenn der Ortsteil nicht im Bezirk der befassten Bezirksvertretung liegt.
6. **Stadtbezirke ohne Treffer darunter:** Ein Bezirk, für den kein Ortsteil oder keine Straße gefunden wurde, wird eingetragen. Methode `stadtbezirk_name` mit „mittel“, `stadtbezirk_adjektiv` mit „niedrig“.

**B3 – Bebauungspläne** (`plan_numbers` in `pipeline/geocode.py`, `pipeline/plans.py`)
- **Erkennung im Titel:**
  - Eine Plannummer zählt nur hinter einem Stichwort: „Bebauungsplan“ (auch mit Tippfehlern), „B-Plan“, „Bauleitplan“, „Satzung“ oder „Vorhaben- und Erschließungsplan“.
  - Erkannt werden auch Listen („6322-2 und 6322-3“) und Zusätze („a“, „II“, „Teil A“).
  - Flurstückskennungen werden vorher entfernt.
- **Abgleich mit den 1.128 Geltungsbereichen** (`Plans.classify`):

  | Treffer | Bedeutung | Konfidenz |
  |---|---|---|
  | eindeutig | genau ein Plan | hoch |
  | grundnummer | der Titel nennt einen Zusatz, der Datensatz nur die Grundnummer | niedrig |
  | mehrdeutig | mehrere Pläne | niedrig |
  | nicht im Datensatz | kein rechtskräftiger Plan, etwa weil er noch im Verfahren ist | keine Fläche |

- **Ortsteile:** Die Planfläche wird mit den Ortsteilen verschnitten. Ein Ortsteil zählt ab 5 % der Planfläche, sonst der mit dem größten Anteil. Der Punkt ist ein innerer Punkt der Schnittfläche.
- **Vorrang:** Bei einem eindeutigen Plan entfallen die übrigen Ortsbezüge der Stufe B derselben Vorlage, weil der Geltungsbereich genauer ist als ein Straßenname im Titel.

**Volltext** (`pipeline/volltext.py`, `_fulltext` in `pipeline/build.py`, seit 20.10.2026)
- **Texte:** `fetch-texts` holt aus OParl-Lite die Liste der Hauptdokumente mit Text („Sammeldokument öffentlich“, `textExtracted`) und dann nur neue oder geänderte Texte (`textSha256`), je Anfrage 10, höchstens 3.000 je Lauf, in `data/raw/texte.jsonl`. Die Datei liegt nur lokal und im Zwischenspeicher des Workflows (`texte-…`); sie wird nicht veröffentlicht. Rahmen laut Antwort der Stadt Bonn vom 19.10.2026: Verarbeitung zulässig, keine Zitate und keine Auszüge.
- **Bereinigung:**
  - ausgeblendet werden der Kopf bis zum Ende der Beratungsfolge, Zeilen, die mindestens dreimal vorkommen (Kopf- und Fußzeilen), Gremiennamen („Bezirksvertretung Beuel“) und Dienstadressen (Stadthaus, Altes Rathaus);
  - Hauptteil und Anlagen (ab „Anlage/n“) werden getrennt gewertet.
- **Regeln:** wie Stufe B auf den Text, mit Vorfilter der Straßennamen nach ihrem ersten Wort (`Gazetteer.street_re_for`, gleiche Treffer, rund viermal schneller).
  - Gattungsnamen wie „Markt“, „Schulstraße“ und „Forstweg“ zählen nur mit Hausnummer.
  - Nur für Vorlagen ohne eigenen Ortsbezug (Ort der Stadt, Titel, Bebauungsplan); nicht für Eingaben von Bürger:innen (Bürgerantrag, Anregungen und Beschwerden, Einwohner…), weil sie oft deren Anschrift enthalten.
  - Mehr als 5 Ortsteile gelten als Liste und werden nicht verortet.
  - Nur der Hauptteil zählt; Orte, die nur in den Anlagen stehen, werden nicht verortet.
  - „mittel“ nur bei mindestens zwei Nennungen oder passender befasster Bezirksvertretung und einer Regel, die selbst „mittel“ ergibt; sonst „niedrig“. Ein Stadtbezirk allein zählt nur unter derselben Bedingung.
- **Methoden:** `volltext_` plus die Methode der Stufe B, etwa `volltext_strasse+hausnummer`; Stufe B. Fundstelle: „im Hauptteil des Hauptdokuments genannt: <Name>“, kein Text.
- **Prüfung:** `data/export/audit_volltext.tsv` enthält je Vorlage mit Text den Befund (verortet, kein Ort, Liste, einzelne Erwähnung eines Stadtbezirks), je Ort Methode, Ortsteil, Konfidenz und Nennungen. Die Stichprobe `data/export/volltext/stichprobe_volltext.tsv` (30 Vorgänge) wird nie überschrieben. Tests: `tests/test_volltext.py`.
- **Stand 20.10.2026:** 1.315 Vorlagen mit Text, davon 163 neu verortet (498 Ortsbezüge); nicht verortet: 41 mit Orten nur in den Anlagen, 19 als Liste, 21 mit einzelner Bezirksnennung; 201 Vorlagen erben einen Ortsbezug. Stichprobe und KI-Vorprüfung: `verortung/PRUEFUNG.md`.

**Vererbung** (`_inherited` in `pipeline/build.py`)
- Eine Vorlage ohne eigenen Ortsbezug, zum Beispiel eine Stellungnahme oder ein Änderungsantrag, übernimmt die Ortsbezüge ihrer übergeordneten Vorlage (`superordinatedPaper`).
- Methode `vererbt`, Stufe B, Konfidenz höchstens „mittel“.
- Als Beleg dient die Drucksachennummer der übergeordneten Vorlage.

**Zusammenführung** (`_locations` in `pipeline/export.py`)
- Belegt Stufe A einen Ortsteil, entfallen dort die Treffer der Stufe B. Bebauungspläne bleiben stehen.
- Vorlagen ganz ohne Ortsbezug stehen unter „stadtweit / ohne Ortsbezug“.

### Jeder Ortsbezug trägt

- `stage` (A, B), `method` (siehe oben), `confidence` (hoch, mittel, niedrig);
- `evidence`: die Fundstelle im Titel bzw. die Beschreibung der Stadt;
- `source_object`: die OParl-ID der Vorlage oder des Orts;
- `source` des Orts: `oparl-bonn`, `osm`, `geo-bonn` oder `bplan-bonn`; daraus folgt die Lizenzzeile.

### Kennzahlen (Stand 19.10.2026)

| Kennzahl | Wert |
|---|---|
| Vorlagen | 24.915 |
| mit Ortsbezug insgesamt | 10.781 (43,3 %) |
| Stufe A | 1.816 (7,3 %) |
| Stufe B einschließlich B3 | 10.409 (41,8 %) |
| B3 mit eindeutigem Plan | 321 von 556 Vorlagen mit Plannummer |
| vererbt | 159 |

Die Zahlen gibt `python -m pipeline check` aus.

### Prüfung

- **Gegenprobe:**
  - `check` vergleicht Stufe B mit Stufe A bei den 1.816 Vorlagen mit Ort der Stadt.
  - Für 87,1 % findet Stufe B ebenfalls einen Ortsteil.
  - Bei Straßen aus OSM stimmt der Ortsteil in 93,7 % der Fälle (1.407 von 1.501; ohne die Hausnummernregel 95,3 %).
  - Die Stufe A ist keine Prüfung auf Ebene der Hausnummer: Die Stadt gibt je Straße einen Punkt an (927 Orte für 923 Straßen; etwa für 18 Vorlagen zur Adenauerallee derselbe Punkt in Gronau, auch für Nr. 7 und Nr. 60). Die 24 Vorlagen, die mit der Hausnummernregel nicht mehr übereinstimmen, haben alle eine Hausnummer, die in einem anderen Ortsteil liegt als der Straßenpunkt der Stadt.
  - Das Audit vermerkt je Treffer „bestätigt durch Stufe A“ oder „abweichend von Stufe A“.
- **Prüfprotokolle:**
  - `data/export/audit_geokodierung_bonn.tsv` enthält eine Zeile je Ortsbezug mit Drucksache, Stufe, Methode, Treffer, Ortsteil, Konfidenz, Fundstelle, Quellobjekt und Prüfstatus.
  - `data/export/audit_bebauungsplaene.tsv` enthält eine Zeile je Plannummer mit der Trefferklasse.
  - `data/export/audit_hausnummern.tsv` enthält eine Zeile je Vorlage und Straße mit Hausnummer: Ortsteile ohne die Nummer, Ortsteil der Nummer, Wirkung (ohne die Hausnummer selbst).
- **Stichprobe:** `data/export/endenich/stichprobe_pruefung.tsv` umfasst 50 Vorlagen und wird nie überschrieben. Die KI-Vorprüfung `vorpruefung_verortung.tsv` ist gekennzeichnet und ersetzt die Prüfung von Hand nicht. Prüfung von Hand am 20.10.2026: 41 richtig, 4 teilweise, 5 falsch; Fehlerarten und mögliche Regeln in `verortung/PRUEFUNG.md`.
- **Datenschutz:**
  - Es gibt keine Hausnummern und keine Wohnadressen.
  - Bürgeranträge erscheinen nur auf Straßen- oder Ortsteilebene.
  - `check` bricht die Pipeline ab, wenn eine Ortsangabe der Stadt eine Hausnummer enthält.
- **Tests:**
  - `tests/test_geocode.py`: Abkürzungen, längster Name, Eingrenzung mehrdeutiger Straßen, Hausnummer (Vorrang, Jahreszahl, mehrdeutige Nummer, fehlender Abschnitt), Ortsteilvarianten, Konfidenz bei abweichendem Bezirk, Plannummern.
  - `tests/test_plans.py`: Einstufung, Teilpläne, Flächenanteile je Ortsteil.

### Ausgabe

- `export` schreibt die Ortsbezüge je Vorlage in die Gebietsdateien unter `data/export/bonn/`.
- Die Datei `data/export/bonn/vorlagen.geojson` (`write_geojson` in `pipeline/publish.py`) enthält einen Punkt je Vorlage und Ort, mit Stufe, Methode, Konfidenz, Fundstelle, Quelle und Link ins Ratsinformationssystem.
- Lizenzen: Orte aus OSM unter ODbL 1.0, Stand und Ergebnisse aus OParl-Lite unter CC BY 4.0, übrige Felder CC0 1.0.

### Grenzen

- Orte, die nur im Dokument stehen, fehlen, weil Stufe C zurückgestellt ist.
- Ein Straßenpunkt steht für die ganze Straße im Ortsteil.
- Ein Name im Titel kann etwas anderes meinen als einen Ort, etwa eine Einrichtung, die nach einer Straße benannt ist. Solche Fälle sollen die Stichprobe und die Rückmeldung „Verortung falsch?“ aufdecken.

## Prozessebene und Zeitleiste

- Schritte mit Evidenzstatus (`belegt`, `abgeleitet`, `soll`, `nicht_öffentlich`, `unklar`) und Stand; Sitzungsdaten auf den Kalendertag in Bonn umgerechnet. Audit: `data/export/endenich/audit_prozess.tsv`; Bericht: `prozess/BERICHT_phase0.md`.
- Planchronik: Register je Plannummer (`plaene.json`) mit Verfahrensschritten nach BauGB aus dem Titel (§ 2 Abs. 1, § 3 Abs. 1, § 3 Abs. 2, § 10 Abs. 1; Inkrafttreten § 10 Abs. 3 aus den Plandaten).
- Zeitleiste: Monatsaggregate je Gebiet (`zeit.json`), feinere Stufen aus den geladenen Vorlagen; Spur der Baustellen mit unscharfen Enden. Audit der Datumsangaben: `data/export/endenich/audit_zeit.tsv`; Abgleich mit der OParl-API: `data/export/verifikation_zeit.tsv`.

## Soll-Modell der Prozessebene

- `data/soll/`: Verfahrensmodell (13 Verfahren mit Schritten, Bahnen, Fristen, Belegen) und Zuständigkeitsordnung (18 Ausschüsse, 333 Rechte) aus „Bonn entscheidet“ (anster2025/bonn-entscheidet, Commit `26641f7`, MIT) als feste Kopie; `ergaenzungen.json` mit eigenen Schritten (Wege in Ausschuss und Bezirksvertretung, Kleine Anfrage, Anhörung der Bezirksvertretung) und drei Korrekturen, jeweils mit Beleg; `QUELLE.md`.
- `pipeline/soll.py` (`python -m pipeline soll`): ordnet jeden Vorgang (Stammnummer) einem Verfahren zu (Regeln aus `einordnung.py` übernommen), gleicht die beratenden Gremienarten mit dem Soll ab und schreibt `data/export/audit_soll.tsv` (ohne Titel). Prüfung vor der Übernahme: `soll/phase0/BERICHT.md`; Stand: `soll/PHASE1.md`, `soll/PHASE2.md`.
- Anzeige: `export` schreibt je Vorlage das Feld `soll` (Verfahren, Sicherheit, Grund, Passung, Gremienarten Ist und Abweichung) und `data/export/bonn/soll.json` (Verfahren mit Schritten und Rechtsgrundlagen als Links, Bahnen, Fristen, Zuständigkeit, Zuständigkeitsordnung je Ausschuss). Links nach `recht.py` aus „Bonn entscheidet“. Die Seite lädt `soll.json` beim ersten geöffneten Vorgang; der Assistent liefert `soll_nach_regelwerk` in `hole_prozesslinie`.
- Mitwirkung: die 14 Einflussregeln des Modells (Anrede „Sie“ über `ergaenzungen.json`, Abschnitt `anrede`, mit Prüfung des alten Wortlauts) stehen in `soll.json` unter `mitwirken`; `site/mitwirken.js` wertet sie im Browser aus (Status, Abschluss, Termin, Ebene, Ziel eines Bürgerantrags aus Stand, Beratungen und `zeit.json`) und wird von `app.js` (dynamischer Import) und `chat/tools.js` genutzt. Bericht: `soll/PHASE3.md`.
- Zuordnung und Abgleich zählen nur den Hauptweg eines Vorgangs: ohne spätere Anfragen, Einwohnerfragen und Mitteilungen anderer Art; Stellungnahmen und Änderungsanträge gehören zur vorausgehenden Vorlage.
- Passung je Vorgang: `passt`, `weicht ab` (Befund), `nur Beirat` (Beiräte bildet das Modell nicht ab), `ohne Beratung`, `ohne Soll`. Stichprobe zur Prüfung von Hand: `data/export/soll/stichprobe_soll.tsv` (`soll/phase4/stichprobe.mjs`, wird nie überschrieben) mit KI-Vorprüfung `vorpruefung_soll.tsv`; Bericht `soll/PHASE4.md`.

## Besetzung der Gremien

- `fetch-besetzung` (`pipeline/besetzung.py`, täglich nach `fetch-organizations`): Liste `persons` der OParl-API mit eingebetteten Mitgliedschaften; Auszug der laufenden Mitgliedschaften in `data/raw/besetzung.json` ohne Kontaktdaten, Anrede und Geschlecht. Namen nur für Mitglieder und beratende Mitglieder von Rat, Ausschüssen, Bezirksvertretungen und Beiräten; ohne Namen: Stellvertretungen (gezählt), Verwaltung, Beiräte mit Jugendmitgliedern. Prüfung beim Abruf und in `check` (keine Kontaktfelder, keine E-Mail-Adressen, keine Namen bei Stellvertretungen).
- `export` ergänzt in `prozessarten.json` je laufendem Gremium `besetzung`: Mitglieder mit Rolle laut Quelle und Fraktion (abgeleitet: Fraktion, Gruppe oder Einzelmandat im Rat; in Bezirksvertretungen die Bezirksfraktion des Stadtbezirks), Sitze nach Fraktion, beratende Mitglieder (Ratsmitglieder in Bezirksvertretungen, § 36 Abs. 6 GO NRW), Zahl der Stellvertretungen. Mitgliedschaften mit Beginn vor der Wahlperiode oder in beendeten Gremien entfallen (Audit `audit_besetzung.tsv`). Phase 0: `gremien/phase0/BERICHT.md`.

## Haushalt und Quellen auf Knopfdruck

- `haushalt-ausschnitt` (`pipeline/haushaltsplan.py`, einmalig, lokal mit `pdftotext`): Teilergebnispläne der 17 Produktbereiche und Gesamtergebnisplan der Haushaltspläne 2023/2024 und 2025/2026; Zeilen 10, 17, 18 je Spalte des Tabellenkopfs (Jahre chronologisch), ohne Finanzplanung; Abbruch bei leeren Zellen oder wenn die Summe der Produktbereiche den Gesamtplan um mehr als 1.500 € verfehlt. Ergebnis `data/haushalt/produktbereiche.tsv` mit Datei und Seite, `STAND.json` mit Prüfsummen der PDF. `haushalt-pruefbogen` schreibt einmalig den Prüfbogen der gezeigten Werte. Themenseiten: `Thema.produktbereich`, Abschnitt „Haushalt im Produktbereich“ (Ist aus der jüngsten Ausgabe, Plan als Ansatz des jeweiligen Haushaltsjahres), nur mit `haushaltsplan.FREIGEGEBEN`. Seite `haushalt/` (`pipeline/haushaltsseite.py`, im Schritt `seo`): Squarified Treemap der 17 Produktbereiche als SVG je Ansicht (Plan der beiden Haushaltsjahre, jüngstes Ist) und Format (breit 1000 × 560, hoch 340 × 640), Wechsel mit Auswahlknöpfen und CSS ohne Skript, Tabelle mit Fundstelle; Flächen der Themenseiten in deren dunkler Farbe. `haushalt-ebenen` (einmalig, lokal mit `pdftotext -bbox`): Aufwandsarten (Zeilen 11–16) der 17 Produktbereiche und Teilergebnispläne der 150 Produktgruppen (Zeilen 11–17, Kopf ohne verantwortliche Person) beider Ausgaben über die Wortkoordinaten, leere Zellen als 0 (Spalte `leer`); Abbruch, wenn je Spalte die Aufwandsarten Zeile 17 oder die Produktgruppen Zeile 17 des Produktbereichs um mehr als 1.500 € verfehlen → `data/haushalt/aufwandsarten.tsv`, `produktgruppen.tsv`, Schlüssel `ebenen` in `STAND.json`; `haushalt-pruefbogen-ebenen` schreibt einmalig `pruefbogen_haushalt_ebenen.tsv`. Ebenen 2 (`#zoom-XX`: Treemap der Produktgruppen, Aufwandsarten als Balken, Tabellen) und 3 (`#pg-1-XX-YY`: Balken und Tabelle) ohne Skript über `:target`, nur mit `haushaltsplan.EBENEN_FREIGEGEBEN` (Vorschau: `HAUSHALT_EBENEN=vorschau`, so in `tests.yml`); `haushalt/PHASE3.md`.
- `quellen.yml` (auf Knopfdruck): Quelldateien, die aus der Arbeitsumgebung nicht erreichbar sind, unverändert mit `STAND.json` in den Branch `quellen`; derzeit `wahlen-rohdaten` (`pipeline/wahlen.py`: Flächen der Wahl- und Stimmbezirke 2025, Seiten und Dateien von votemanager und opendata.bonn.de).

## Baustellen

- `baustellen.yml` ruft täglich um 05:23 UTC die Feeds 14403, 14698 und 14755 ab (bis zu 10 Versuche, Prüfung gegen `numberMatched`) und schreibt in den Branch `archiv`: `baustellen.json` (Zustand je Baustelle), `protokoll.tsv` (neu, geändert, entfallen), Momentaufnahmen bei Änderungen, `STAND.json`. Eine Baustelle gilt nur bei vollständigem Abruf aller Feeds als entfallen.
- Derselbe Workflow (`python -m pipeline anliegen`) archiviert den Mängelmelder im Ordner `anliegen/` des Branches `archiv`: je Meldung nur Nummer, Tag, Kategorie, Gruppe, Ortsteil (Punkt im Polygon, Koordinate danach verworfen), Status und erstes/letztes Auftreten (`meldungen.tsv`), dazu `abrufe.tsv` und `STAND.json`. Erster Lauf ab November 2021, danach die Monate der letzten 120 Tage; Abruf je Monat in Seiten zu 500, geprüft gegen `meta.total`. Scheitert eine der beiden Quellen, wird die andere gesichert und der Lauf als fehlgeschlagen gemeldet. Phase 0: `anliegen/phase0/BERICHT.md`.
- `kandidaten`: Kriterien räumlich (≤ 150 m), zeitlich, gleiche Straße, Amt 66/61-3 oder Thema Verkehr, Bau-Stichwort passend zur Maßnahme; „hoch“ nur für Baubeschlüsse (Beschlussvorlage, Dringlichkeits- oder Eilentscheidung), sonst höchstens „mittel“; Konfidenz hoch, mittel, niedrig, „fremd“ für andere Träger. Audit `data/export/baustellen_kandidaten.tsv`, Stichprobe `data/export/baustellen/stichprobe_kandidaten.tsv` (wird nie überschrieben).
- `baustellen-seite`: `baustellen.json` für die Seite aus dem Archiv, sonst aus den Feeds; Adressen ohne Hausnummer; nur Kandidaten mit Konfidenz hoch.

## Seite

- Statisch, ohne Server-Logik. Strenge Content-Security-Policy; extern nur Kacheln von `tile.openstreetmap.org` und die Anbieter des Assistenten. Leaflet 1.9.4 (BSD-2-Clause), Leaflet.markercluster 1.5.3 (MIT) in `site/vendor/`, Schrift Inter (OFL 1.1) in `site/fonts/`, jeweils mit Lizenzdatei und SRI.
- Kartensteuerung unten rechts (Bebauungspläne, Baustellen, Farbe nach Thema, Ganz Bonn ansehen, Farbige Karte): mobil (bis 900 px) hinter der Schaltfläche „Kartenoptionen“ (`aria-expanded`), ein Klick in die Karte schließt sie; die Tour öffnet sie im Schritt „Die Karte“.
- Startzustand ohne `gebiet` im Link: Übersicht über ganz Bonn (`bonn:alle`, Eintrag „Ganz Bonn – Gebiet wählen“ in der Auswahl): Karte auf ganz Bonn mit den anklickbaren Stadtbezirken, noch keine Vorlagen geladen; Liste und Auswertung weisen auf die Wahl eines Gebiets hin, „Informiert bleiben“ bietet den Feed über ganz Bonn (`feeds/ganz-bonn.xml`) und die Seite `rss/` an, die Suche „in ganz Bonn“ und die Reiter Prozesse und Termine funktionieren. Die Tour lädt für ihr Beispiel Bonn-Zentrum. Links mit `gebiet=` öffnen weiterhin direkt das Gebiet.
- Gebiete auf der Karte: eigene Ebene (`pane` „gebiete“, unter Plänen, Baustellen und Punkten) mit den Flächen der Stadt. Solange ganz Bonn ins freie Kartenfeld passt, sind die vier Stadtbezirke als Flächen mit Namen anklickbar. Die Farbstärke der Flächen zeigt die Vorlagen der letzten zwölf Monate in fünf Stufen (lila Verläufe als SVG-Verläufe im eigenen Renderer der Ebene; Ortsteile nach Quintilen, Stadtbezirke in gleichen Abständen bis zum Höchstwert; Legende oben links, mobil eingeklappt); Name und Zahl stehen als Beschriftung, beim Überfahren außerdem die Gesamtzahl und ein auffälliges Thema; beim Überfahren ein heller Glaseffekt (weißer Verlauf, weißer Rand, Schein als SVG-Filter); ein Klick zoomt auf den Bezirk und zeigt seine Ortsteile hervorgehoben und mit Namen (Beschriftungen in der Ebene der Tooltips, ohne Klickfläche; Bezirksname im nach Vorlagen gewichteten Mittel seiner Ortsteile, Ortsteilname im Schwerpunkt der größten Teilfläche). Näher herangezoomt sind die Ortsteile anklickbar; ein Klick lädt das Gebiet wie die Auswahl oben (gleicher Ablauf, URL-Zustand). „Ganz Bonn ansehen“ ändert nur die Ansicht. Ein zusammengefasstes Gebiet je Stadtbezirk gibt es nicht: `bezirk:` enthält nur Vorlagen, die auf Ebene des Bezirks verortet sind; sie bleiben über die Auswahl oben erreichbar. Für die Tastatur bleibt die Auswahl oben der Weg.
- URL-Zustand: `?gebiet=ortsteil:endenich&von=2025-10-18&bis=2026-10-18&zoom=Quartal&achse=vorlage&thema=verkehr&partei=SPD&suche=bonn&farbe=thema&plaene=1&plan=6122-1&baustellen=1&baustelle=9640#191010`; Reiter „Prozesse“: `prozesse=verfahren|gremien|aemter`, `ansicht=liste`, `verfahren=buergerantrag`, `gremium=340`, `amt=61-stadtplanungsamt`; „Mitmachen in Bonn“: `mitmachen=1`, `bezirk=Beuel`.
- Reiter „Prozesse“ (`site/prozesse.js`, beim ersten Öffnen nachgeladen): Verfahren aus `soll.json` als Bahnendiagramm (SVG, Bahnen wie im Soll-Modell; seitlich verschiebbar) oder Liste, je Verfahren Schritte mit Rechtsgrundlage, Wege zum Mitwirken (Regeln des Soll-Modells mit Frist; Bezeichnungen der RIS-Karte), Zahl der Vorgänge und drei jüngste Beispiele aus `prozessarten.json`; Gremien der laufenden Wahlperiode als Organigramm (Rat, Ausschüsse, Bezirksvertretungen, Beiräte) oder durchsuchbare Liste mit früheren Gremien, je Gremium Beratungen, Sitzungen, Zuständigkeit (Rechte der Zuständigkeitsordnung nach Art; für Rat und Bezirksvertretungen die allgemeinen Regeln des Soll-Modells) und ein Filter für die Liste; Ämter als Kacheln nach Gruppen oder durchsuchbare Liste mit früheren Ämtern, je Amt Abteilungen, federführende Vorlagen (davon aus der Politik bzw. von Einwohner:innen), fachliche Zuständigkeit laut Stellungnahmen, häufigste beratende Gremien (mit Sprung in den Reiter „Gremien“), jüngste Vorlagen und ein Filter für die Liste. Die Schaubilder haben eine gleichwertige Liste darunter bzw. als Ansicht.
- „Mitmachen in Bonn“ (`site/beteiligung.js`, Menü „Mitmachen“ → „Alle Wege im Überblick“, beim ersten Öffnen nachgeladen): je Stadtbezirk (voreingestellt der des gewählten Gebiets) die nächste Sitzung der Bezirksvertretung und des Rates sowie die nächste Einreichungsfrist für Einwohnerfragen und Bürgeranträge (Sitzungstermin aus `zeit.json` minus 21 Tage, gekennzeichnet als abgeleitet; für stadtweite Anliegen der Bürgerausschuss laut `buergerantrag_ziel`); die Fristen rund um eine Sitzung (`soll.json` → `fristen`) als Zeitstrahl; die Wege (Regeln aus `soll.json` → `mitwirken`, Texte der Regeln mit eingesetztem Gremium und Datum, Frist und Rechtsgrundlage) mit Sprung zum Bürgerantrag der Stadt, zum Gremium im Reiter „Prozesse“, zu den Terminen und zur Ebene Bebauungspläne.
- Flächen für die Seite (`pipeline/flaechen.py`, im Schritt `export`): Ortsteile, Stadtbezirke und Bebauungspläne vereinfacht (Douglas-Peucker, etwa 2 m, Topologie je Fläche erhalten; Koordinaten auf 5 Nachkommastellen) als `data/export/bonn/flaechen/*.json`. Die Endung `.json` sorgt dafür, dass auch der Server der Hauptadresse komprimiert; `.geojson` liefert er unkomprimiert aus. Übertragen werden beim Start rund 70 KB statt 600 KB, mit Bebauungsplänen weitere rund 145 KB statt 1,2 MB. Die Seite fällt auf `data/geo/*.geojson` zurück, wenn die Dateien fehlen (Pilot). Verortung und Datenpaket nutzen die vollen Flächen. Tests: `tests/test_flaechen.py`.
- Kurzfassungen (20.10.2026, vorbereitet, noch nicht auf der Seite): `pipeline/kurzfassung.py`, Schritt `kurzfassungen` im Workflow `pages.yml`.
  - Seit 26.10.2026 läuft das Erzeugen im eigenen Job `kurzfassungen` nach dem Veröffentlichen. Der Bau lädt nur den Bestand aus dem Branch, neue Kurzfassungen erscheinen mit dem nächsten Lauf.
  - Modell: Mistral (`mistral-large-latest` seit Fassung 2, vorher `mistral-small-latest`; änderbar über `KURZFASSUNG_MODELL`), Schlüssel als Secret `MISTRAL_API_KEY`; ohne Schlüssel wird nichts erzeugt.
  - Fassung 2 der Anweisung (21.10.2026, `FASSUNG`): richtiger Absender und Art der Vorlage (Antrag ist Vorschlag, Stellungnahme gibt eine Sicht wieder), Bedingungen und Kostenträger nur wie im Text, keine Orte, Zahlen oder Vermutungen über den Text hinaus; die Art der Vorlage geht mit in die Anfrage. Anlass: KI-Vorprüfung der ersten Stichprobe (`data/export/kurzfassungen/vorpruefung_kurzfassungen_v1.tsv`: 18 plausibel, 8 teilweise, 2 falsch, 2 unklar). Kurzfassungen älterer Fassung werden zuerst neu erzeugt; die Stichprobe der Fassung 2 heißt `stichprobe_kurzfassungen_v2.tsv`. Auf der Seite erscheinen nur Kurzfassungen der aktuellen Fassung.
  - Fassung 3 (21.10.2026): KI-Vorprüfung der Stichprobe v2 (`vorpruefung_kurzfassungen_v2.tsv`): 25 plausibel, 5 teilweise, keine falsch (Fassung 1: 18/8/2 falsch/2 unklar); alle 30 begannen jedoch mit einer Überschrift („Stellungnahme der Verwaltung“), und Kostenträger wurden teils ergänzt. Anweisung: direkt mit dem ersten Satz beginnen, Absender darin nennen, keine Überschrift, Kosten nur laut Text; `glaetten` entfernt vorangestellte Überschriften auch bei schon erzeugten Kurzfassungen. Stichprobe `stichprobe_kurzfassungen_v3.tsv`.
  - KI-Vorprüfung v3 (`vorpruefung_kurzfassungen_v3.tsv`): 24 plausibel, 5 teilweise, 1 falsch; keine Überschriften mehr, aber ergänzte Kostensätze (3) und eine falsch errechnete Summe. Danach zwei automatische Prüfungen: Sätze zum Kostenträger werden entfernt, wenn der Text keinen nennt (`ohne_kostensatz`); eine Zahl ab zwei Ziffern, die nicht im Text steht, führt zum Verwerfen (`fremde_zahl`). Beide gelten auch rückwirkend für vorhandene Kurzfassungen der aktuellen Fassung. Wirkung auf die Stichprobe: 27 plausibel, 2 teilweise, 1 verworfen.
  - KI-Vorprüfung v4 (`vorpruefung_kurzfassungen_v4.tsv`, 30 weitere Kurzfassungen der Fassung 3 nach den Prüfungen, 21.10.2026): 20 plausibel, 10 teilweise, keine falsch; Zahlen und Kosten ohne Fehler. Die unabhängige Stichprobe bestätigt die Schätzung aus v3 (27) nicht; keine Freigabe. Mängel: Fraktion oder Gremium ohne Beleg (3), ergänzte Fragen bei Sachstandsanfragen (2), ungenaue Einzelheiten (3), Art der Vorlage verzerrt (2). Danach Fassung 4: Fraktion oder Gremium (Rat, Ausschuss, Bezirksvertretung), die weder Titel noch Text nennen, führen zum Verwerfen (`fremder_akteur`; trifft 8 von 95 Kurzfassungen der Fassung 3); Anweisung: bei Anfragen nur die gestellten Fragen. Neue Stichprobe nach der Neuerzeugung.
  - Fassung 4 im täglichen Lauf (22.10.2026): 600 erzeugt, 468 gültig, 132 verworfen (52 Zahl nicht im Text, 43 wörtliche Übernahme, 37 Fraktion oder Gremium ohne Beleg). KI-Vorprüfung einer Stichprobe (`vorpruefung_kurzfassungen_v5.tsv`): 23 plausibel, 7 teilweise, keine falsch; keine Freigabe. Danach Fassung 5: Rolle im Verfahren (Kenntnisnahme ist kein Vorschlag), Fragen wie gestellt, keine Gründe oder Ursachen ohne Beleg, Ebene einer Zahl, „Koalition“ ohne Aufzählung der Parteien. Verworfene Entwürfe werden aufbewahrt (`entwurf`), außer sie enthalten Text der Quelle oder eine Hausnummer, und bei jedem Lauf nach den geltenden Regeln neu geprüft; sie erscheinen nirgends.
  - Wörtliche Übernahme (22.10.2026): Wiederholt die Kurzfassung den Titel der Vorlage oder den Namen eines Gremiums oder Amtes (OParl, ab drei Wörtern), zählt diese Stelle nicht als Übernahme; beides ist eine öffentliche Angabe, kein Auszug aus dem Dokument. Grund: 43 von 132 verworfenen Kurzfassungen der Fassung 4 scheiterten an der Übernahme, lange Gremiennamen wie „Ausschuss für Planung, Verkehr und Denkmalschutz“ haben allein sechs Wörter.
  - Fassung 5 (22.10.2026), KI-Vorprüfung `vorpruefung_kurzfassungen_v6.tsv`: 22 plausibel, 8 teilweise, keine falsch – keine Verbesserung gegenüber Fassung 4 (23/7/0); die Anweisung allein kommt nicht weiter. Mängel: Rolle im Verfahren (3), Zahl auf falscher Ebene (2), Fragen erweitert (2), Angekündigtes als vorliegend (1). Prüfung der aufbewahrten Entwürfe: Die Prüfung auf Fraktionen fing zweimal „Grüne“ statt „BBB“ ab (richtig); Zahlen aus dem Titel („Controllingbericht 2023“) galten als fremd – jetzt zählt der Titel mit. Sammellisten nichtöffentlicher Punkte (alle Titelformen, auch „Punkte der nichtöffentlichen Sitzung“) erhalten keine Kurzfassung und werden auch nicht verortet.
  - Fassung 6 (22.10.2026): Nach der ersten Kurzfassung liest ein zweiter Aufruf (`GEGENLESEN`, `_gegenlesen`) sie gegen den Text gegen und berichtigt Absender, Rolle im Verfahren, Zahlen und ihre Ebene, Fragen und Ergänzungen ohne Beleg; ist die Antwort leer oder kürzer als acht Wörter, bleibt die erste Fassung. Danach dieselben automatischen Prüfungen. Je Kurzfassung zwei Anfragen, daher höchstens 300 je täglichem Lauf; Feld `beim_gegenlesen_geaendert` zur Auswertung. Vorhandene Kurzfassungen zu Vorlagen, die keine mehr erhalten (Sammellisten), werden zurückgezogen.
  - Fassung 6 im Lauf (22.10.2026): 50 erzeugt, 37 gültig; 10 wegen wörtlicher Übernahme verworfen (Fassung 5: 7 von 100), alle 50 beim Gegenlesen umformuliert. KI-Vorprüfung von 30 (`vorpruefung_kurzfassungen_v7.tsv`): 22 plausibel, 8 teilweise, keine falsch – wie Fassung 5. Mängel: Zahl oder Ort auf der falschen Ebene (3), Stand des Verfahrens verzerrt (3), Folgerung ohne Beleg (2). Danach Fassung 7: Anweisung der Fassung 5 mit einer Anfrage, Gegenlesen abgeschaltet (`GEGENLESEN_AKTIV = False`), wieder bis 500 je täglichem Lauf. Über vier Stichproben (Fassungen 3 bis 6, 120 Kurzfassungen) lag der Anteil „plausibel“ zwischen 20 und 23 von 30, ohne falsche; mit der Anweisung allein ist die Schwelle von 27 nicht zu erreichen.
  - Fassung 7 im Lauf (22.10.2026): 50 erzeugt, 44 gültig. KI-Vorprüfung der Stichprobe `stichprobe_kurzfassungen_v7.tsv` (`vorpruefung_kurzfassungen_v8.tsv`): 18 plausibel, 12 teilweise, keine falsch; Mängel: Vorschlag oder Ankündigung als Ergebnis (4), Begründung verschoben (4), Regel zur Ersatzpflanzung bei Baumfällungen verzerrt (2). Die Entscheidung über die Freigabe liegt beim Auftraggeber (`ABNAHME.md`, Abschnitt 1).
  - Freigabe (22.10.2026): Prüfung von Hand derselben Stichprobe: 18 zutreffend, 12 teilweise, keine falsch (`pruefung_kurzfassungen_v7.tsv`, mit sichtbarer KI-Vorprüfung, daher nicht unabhängig von ihr). Der Auftraggeber hat die Kurzfassungen freigegeben (`FREIGEGEBEN = True`). Der Hinweis lautet überall (Vorgang, Assistent, Feeds, TSV, DCAT): Einzelheiten können ungenau sein, etwa ob etwas beschlossen oder nur vorgeschlagen ist; maßgeblich ist das Original. Angezeigt werden nur Kurzfassungen der aktuellen Fassung.
  - Freigabe vorbereitet (21.10.2026): Mit `FREIGEGEBEN = True` erscheinen die Kurzfassungen im Vorgang, im Ratsassistenten (`hole_vorlage`), in den Atom-Feeds und als `data/export/bonn/kurzfassungen.tsv` im Datenpaket (mit Kennzeichnung je Zeile) samt DCAT-Distribution; ohne Freigabe entsteht nichts davon.
  - Eingabe: Titel und bereinigter Hauptteil des Hauptdokuments (wie bei der Verortung, höchstens 12.000 Zeichen); keine Eingaben von Bürger:innen.
  - Ausgabe: zwei bis drei Sätze in einfacher Sprache. Verworfen wird jede Kurzfassung mit einer wörtlich übernommenen Folge von mehr als sechs Wörtern oder mit einer Hausnummer; Markdown-Auszeichnungen (`*…*`) werden entfernt.
  - Ablage im Branch `kurzfassungen` (`kurzfassungen.jsonl`, je `textSha256` einmal erzeugt), höchstens 500 je täglichem Lauf und 50 nach einem Merge (`KURZFASSUNG_MAX`, seit 21.10.2026; Zwischenstand alle 25 Anfragen gesichert); dort einmalig eine Stichprobe von 30 (`stichprobe_kurzfassungen.tsv`).
  - Auf der Seite („Kurz gesagt“ im Vorgang, gekennzeichnet als KI-Kurzfassung) erst, wenn `FREIGEGEBEN = True` gesetzt ist, nach Prüfung der Stichprobe von Hand. Tests: `tests/test_kurzfassung.py`.
- Stufe C (21.10.2026, vorbereitet, noch nicht auf der Seite): `pipeline/stufe_c.py`, Schritt `stufe-c` nach `build` und vor `export`; Aufruf des Modells über `pipeline/sprachmodell.py` (Mistral oder Anthropic, Umgebungsvariable `SPRACHMODELL`).
  - Modell: `mistral-large-latest` (änderbar über `STUFE_C_MODELL`), Schlüssel `MISTRAL_API_KEY` (bei Anthropic `ANTHROPIC_API_KEY`); ohne Schlüssel wird nichts angefragt.
  - Kandidaten: Vorlagen mit Text ohne eigenen Ortsbezug (alle Ortsbezüge aus dem Volltext oder vererbt), ohne Eingaben von Bürger:innen; höchstens 50 neue je Lauf (`STUFE_C_MAX`), je `textSha256` einmal.
  - Ausgabe des Modells (JSON): je Ort Name, Art (Straße, Ortsteil, Stadtbezirk, Objekt, Kreuzung) und Rolle (Gegenstand oder nur erwähnt). Gespeichert werden nur diese Angaben, ohne Ziffern (Hausnummern), im Branch `kurzfassungen` (`orte_stufe_c.jsonl`).
  - Gegenprüfung: Ein Ort zählt nur, wenn sein Name wörtlich im Hauptteil steht und das Verzeichnis der Stufe B ihn zuordnet; keine Gattungsnamen, keine Listen über 5 Ortsteile. Ort aus Stufe B als Gegenstand bestätigt → „mittel“, wenn die Regel es erlaubt; als nur erwähnt eingestuft → „niedrig“; neuer Ort nur als Gegenstand, Methode `llm_…`, Konfidenz „niedrig“ (kein Stadtbezirk allein, kein Ortsteil, in dem schon ein Ort aus Stufe B liegt). Gelöscht wird nichts.
  - Gescheiterte Anfragen (kein lesbares JSON, abgeschnitten, Netzfehler) werden in späteren Läufen wiederholt, höchstens dreimal (`versuche`). Jeder Lauf mit Anfragen schreibt eine Zeile in `laeufe.tsv` im Branch (Anfragen, Tokens, Fehler) für Kurzfassungen und Stufe C.
  - Gebäude und Anlagen (21.10.2026): `data/geo/objekte_bonn.json` aus OSM (`fetch-objects`, montags und auf Knopfdruck; rund 1.700 benannte öffentliche Einrichtungen, Grün- und Sportanlagen, Friedhöfe, Kirchen, Kitas, Bauwerke, dazu Gebäude mit Wikidata-Eintrag; ohne Kunstwerke, Gedenktafeln, Wegkreuze und soziale Einrichtungen). Abgleich in `pipeline/objekte.py`: angeglichener Name (Vorsätze wie „GGS“, „Kita“, „Städt.“, „Bonn/Bonner“ zählen nicht, „Posttower“ = „Post Tower“), nur eindeutige Ortsteile; mehrdeutige Namen nur mit dem Ortsteil aus dem Text; Teil eines Namens ab acht Zeichen; Gattungsnamen nie. Ein Gebäude oder eine Anlage, die das Modell als Gegenstand nennt, ergibt einen Punkt `llm_objekt` („niedrig“). Abgleich je Name in `audit_stufe_c_objekte.tsv`. Wirkung auf den ersten Lauf (49 Vorlagen): 10 neue Orte (vorher 0), etwa Beethovenhalle, Jupp-Gassen-Halle, Adelheidisschule.
  - Gebäude und Anlagen im Titel (Stufe B, Methode `objekt_name`, 21.10.2026): für Vorlagen ohne eigenen Ortsbezug, vor der Verortung aus dem Volltext. Strenger als in Stufe C: Name mit Vorsatz („Kita Rheinpiraten“, nicht „Rheinpiraten“), mindestens acht Zeichen, in Bonn eindeutig; keine Schutzgebiete; keine Einrichtungen ohne festen Ort (Volkshochschule, Musikschule, Universität, Sparkasse) und keine allgemeinen Wörter („Pavillon“, „Städtebau“; Liste `TITEL_OHNE_NAME` in `pipeline/objekte.py`). Konfidenz „niedrig“, Punkt am Objekt. Wirkung: 837 Vorlagen neu verortet (insgesamt 11.803 statt 10.998 mit Ortsbezug), häufig Beethovenhalle, Stadthaus, Hauptbahnhof, Godesburg, Frankenbad. Audit `data/export/audit_objekte_titel.tsv`, Stichprobe `data/export/objekte/stichprobe_objekte.tsv` (30), KI-Vorprüfung `vorpruefung_objekte.tsv` (26 plausibel, 4 teilweise).
  - Erste Stichprobe (Branch `kurzfassungen`, 21.10.2026), KI-Vorprüfung `data/export/stufe_c/vorpruefung_stufe_c.tsv`: 17 plausibel, 10 teilweise, 2 unpassend, 1 unklar. Häufigster Mangel: Orte, die nur als Beispiel oder in einer Aufzählung stehen. Danach drei Regeln: mehr als vier neue Gebäude in einer Vorlage gelten als Aufzählung (`MAX_NEUE_OBJEKTE`); Einrichtungen ohne festen Ort (`TITEL_OHNE_NAME`) gelten auch in Stufe C nicht; Namen mit Ziffer am Anfang (Tafeln, Vereine) werden nicht ins Verzeichnis übernommen. Tokens laut `laeufe.tsv`: je 50 Vorlagen rund 45.000–55.000 Eingabe- und 5.000–8.000 Ausgabe-Tokens (Stufe C, Mistral Large), rund 31.000 und 3.000 (Kurzfassungen, Mistral Small).
  - Zweite Stichprobe (`data/export/stufe_c/stichprobe_stufe_c_v2.tsv`, 30 Vorlagen außerhalb der ersten, 21.10.2026), KI-Vorprüfung `vorpruefung_stufe_c_v2.tsv`: 20 plausibel, 2 teilweise, 8 unpassend; Ortsteile ohne Fehler. Fehlermuster und Folgen: Gebäude über einen Namensteil zugeordnet („GGS Medinghoven“ → „Burg Medinghoven“) → Teiltreffer nur von der Art des Vorsatzes (`VORSATZ_ART` in `pipeline/objekte.py`); Sammellisten „Tagesordnungspunkte in nichtöffentlicher Sitzung“ → ausgenommen (`SAMMELLISTE`); drei Stadtbezirke einer stadtweiten Vorlage bestätigt → ab drei Stadtbezirken gilt eine Vorlage als stadtweit und wird nicht auf Bezirke verortet, auch in Stufe B (`volltext.MIN_BEZIRKE_STADTWEIT`; betrifft 240707 und 241671); Beispiele und Teilfragen in stadtweiten Vorlagen sowie Einrichtungen als Träger → Anweisung Fassung 2 (`FASSUNG`), ältere Antworten werden neu angefragt (bis 200 je täglichem Lauf, `STUFE_C_MAX`). Freigabe noch nicht empfohlen; nächste Stichprobe nach der Neuanfrage.
  - Dritte Stichprobe (`stichprobe_stufe_c_v3.tsv`, 20 Vorlagen mit Antworten der Fassung 2 außerhalb der früheren Stichproben, 22.10.2026), KI-Vorprüfung `vorpruefung_stufe_c_v3.tsv`: 9 plausibel, 2 teilweise, 9 unpassend. Fehlermuster: Sammellisten mit abweichender Titelform (2), Sitz einer Gesellschaft als Ort (2), Beispielorte in stadtweiten Konzepten, Sammelberichten und Gebührenvorlagen (5), Ortsteile großer Objekte (1). Danach `volltext.titel_ohne_ort`: Sammellisten nichtöffentlicher Punkte in allen Titelformen sowie Jahresabschluss, Wirtschaftsplan, Aufsichtsrat, Gesellschafterversammlung, Beteiligungs- und Lagebericht werden weder aus dem Volltext (Stufe B, 58 Vorlagen, davon 7 bisher verortet) noch mit dem Sprachmodell verortet. Beispielorte in stadtweiten Vorlagen erkennt das Modell auch mit Fassung 2 nicht verlässlich; Freigabe nicht empfohlen. Empfehlung: Stufe C allenfalls zum Herabstufen nutzen (Rolle „erwähnt“), nicht zum Bestätigen oder für neue Orte. Dafür gibt es `FREIGEGEBEN = "herabstufen"` (22.10.2026): Nur Orte aus dem Volltext, die das Modell als „nur erwähnt“ einstuft, erhalten Konfidenz „niedrig“ mit Vermerk in der Fundstelle; in den drei Stichproben schienen Herabstufungen meist richtig. Die KI-Vorprüfung aller 31 Herabstufungen (`data/export/stufe_c/pruefung_herabstufungen.tsv`, Prüfbogen für die Prüfung von Hand, 22.10.2026) ergab jedoch nur 19 richtig, 8 falsch, 4 unklar; falsch waren vor allem geförderte Projekte in Anträgen zum Feuerwehrtopf und Baustellen an der Anschrift einer Schule. Auch `"herabstufen"` ist damit nicht empfohlen. Geprüft wurde auch eine Regel „Text nennt das ganze Stadtgebiet“ für Stufe B; sie trennt nicht (auch plausible Fälle nennen das Stadtgebiet) und wurde verworfen.
  - Audit `data/export/audit_stufe_c.tsv`; einmalig eine Stichprobe von 30 im Branch (`stichprobe_stufe_c.tsv`). In die Datenbank übernommen erst mit `FREIGEGEBEN = True` nach Prüfung von Hand. Tests: `tests/test_stufe_c.py`.
- Suche im Text der Dokumente (20.10.2026): Schaltfläche „Auch im Text der Dokumente suchen“ im Suchmenü (`runDocSearch` in `app.js`). Erst nach dem Klick fragt der Browser `fileFullTextSearch` von OParl-Lite ab (`connect-src` in der CSP; OParl-Lite erlaubt beide Adressen der Seite per CORS), höchstens 3 Seiten zu 100 Treffern. Abgefragt werden nur die Drucksachen der Dateien, nicht das Feld `snippet`. Die Treffer gehen in die Suche über ganz Bonn ein (`suche.json`); Vorlagen, die nur im Dokument passen, tragen „im Dokument erwähnt“. Datenschutzerklärung: Abschnitt „Suche im Text der Dokumente“. Test: Ablauf „Suche im Text der Dokumente“ mit nachgebildeter Antwort (keine Anfrage vor dem Klick, kein `snippet`).
- Seitenstart (20.10.2026): `index.html` fordert die Startdaten (`index.json`, `zeit.json`, Flächen, Glossar, Baustellen) mit `<link rel="preload" as="fetch">` an, bevor `app.js` läuft; `start()` wartet auf alle gleichzeitig statt nacheinander. Der Ratsassistent (`site/chat/ui.js` mit sechs Modulen) wird erst geladen, wenn die Fläche aufgeht oder die Schaltfläche den Zeiger oder Fokus bekommt (`loadChat` in `app.js`). Gemessen mit 250 ms Latenz je Anfrage: Karte mit Bezirken nach 1,7 statt 2,5 bis 2,8 s, 8 Anfragen weniger.
- Kennzahlen je Gebiet in `index.json` (`pipeline/gebietszahlen.py`, im Schritt `export`): je Ortsteil `jahr` (Vorlagen mit Ortsbezug im Gebiet, deren Datum in den zwölf Monaten vor dem Datenstand liegt) und `auffaellig`; je Stadtbezirk zusätzlich `alle` (Ortsteile und Bezirksebene ohne Doppelte); `zahlen` nennt Zeitraum und Regeln. Auffällig ist das Thema mit dem größten Verhältnis von Anteil im Gebiet zu Anteil an allen verorteten Vorlagen Bonns, sofern mindestens 5 Vorlagen und 10 % im Gebiet und mindestens das 1,25-Fache des Anteils in Bonn; sonst keines. Themen sind abgeleitet (`topics.py`). Tests: `tests/test_gebietszahlen.py`.
- Themenebene (20.10.2026): `themen` je Ortsteil und Stadtbezirk mit [Zahl, Anteil in %] je Thema an allen Vorlagen mit Ortsbezug seit Oktober 2019 (`theme_shares`); unter 20 Vorlagen `null` (grau, „zu wenige Vorlagen“). In `zahlen` stehen `themen_bonn` (Anteile in ganz Bonn) und `themen_min`. In der Legende der Flächen wählt „Flächen färben nach“ zwischen der Zahl der Vorlagen (12 Monate) und dem Anteil eines Themas; Stufen bei Ortsteilen nach Quintilen der Anteile, bei Stadtbezirken in gleichen Abständen bis zum Höchstwert (ganze Prozent); Beschriftung und Hinweis beim Überfahren zeigen den Anteil, die Zahl und den Anteil in ganz Bonn; URL `flaechen=<thema>`. Unabhängig davon färbt „Farbe nach Thema“ die Punkte.
- `prozessarten.json` (`pipeline/prozessarten.py`, im Schritt `export`): Vorgänge je Verfahren (Stammnummern, Zuordnung aus `pipeline/soll.py`, davon mit Sicherheit „hoch“), Gremien mit Art (Rat, Haupt-, Fach-, Unter-, Wahlausschuss, Bezirksvertretung, Beirat), aktuell = nicht aufgelöst und in der laufenden Wahlperiode getagt oder Sitzung angesetzt; Abschnitt der Zuständigkeitsordnung bei gleichem Namen, eine abweichende Bezeichnung als gekennzeichnete Zuordnung (`ZUSTO_ALIAS`). Ämter: Verwaltungsbereiche zusammengefasst nach `classification` (bei „Co-Dezernat“ der Bereich selbst, wie `actors.amt_label`), ohne Fraktionsgeschäftsstellen („Ebene 3“); Gruppe nach der ersten Ziffer der Amtsnummer (`AMT_GRUPPEN`, abgeleitet; `subOrganizationOf` ist in der Quelle leer, eine Zuordnung zu Dezernaten fehlt), Co-Dezernat, Dezernate, Referate und Programmbüros als „Koordination und Stäbe“; aufgelöst, wenn alle Bereiche ein vergangenes Enddatum tragen; Hinweis „formal federführend“, wenn mindestens die Hälfte der Vorlagen Anträge und Anfragen der Politik oder Eingaben von Einwohner:innen sind; fachlich zuständige Ämter aus `paper_responsibility` (Stellungnahmen, abgeleitet). Tests: `tests/test_prozessarten.py`.
- Barrierefreiheit: WCAG 2.1 AA, geprüft mit axe-core auf Desktop und Mobil; Listen als Zugang ohne Maus zu Karte, Plänen und Baustellen.
- Auffindbarkeit: Favicons, Web-Manifest, canonical, Open Graph, schema.org, `noscript`, `404.html`, `robots.txt`, `sitemap.xml`, statische Seiten je Gebiet (`gebiete/`).

## Ratsassistent

Elf Werkzeuge in `site/chat/tools.js` über die statischen Exporte (`suche_vorlagen`, `hole_vorlage`, `hole_prozesslinie`, `suche_ort`, `liste_sitzungen`, `hole_gremium_oder_amt`, `erklaere_begriff`, `suche_bebauungsplan`, `suche_baustellen`, `hole_kontext`, `datenstand`). Adapter für Anthropic, Mistral, OpenRouter und lokale Modelle (`providers.js`), Chat-Kern (`core.js`), Schlüssel nur im Arbeitsspeicher oder auf Wunsch im Sitzungsspeicher (`keys.js`). Systemprompt mit Änderungsvermerk: `site/chat/systemprompt.md`. Auswertung: `eval/run.mjs`, `eval/fragen.json`.

## Offene Daten

- `data/export/bonn/vorlagen.geojson` – ein Punkt je Vorlage und Ort mit Stufe, Methode, Konfidenz, Fundstelle, OParl-ID
- `data/export/bonn/plaene.json`, `data/export/bonn/baustellen.json`
- `data/export/bonn/dcat.jsonld` – DCAT-AP mit Distributionen und Lizenzen
- `data/export/bonn/termine.ics`, `data/export/bonn/feeds/`
- Datenpaket mit allen Exporten, Audits, Protokollen und Berichten (Inhalt in `LIESMICH.txt`)

## Betrieb

- `pages.yml`: täglich 04:17 UTC und bei jedem Push auf `main`; Abruf mit Rückfall auf den zwischengespeicherten Stand, Bebauungspläne montags und auf Knopfdruck (bis zu 15 Minuten); veröffentlicht auf GitHub Pages und im Branch `deploy`.
- `live.yml`: prüft nach jeder Veröffentlichung und täglich 06:41 UTC Hauptadresse und Spiegel (Startseite, Daten, Datenschutz, `rss/`, `haushalt/`, `thema/`, eine Gebietsseite, Feed über ganz Bonn als Atom mit Einträgen, Datenstand, Stand des Branch `deploy`); Fehler meldet GitHub per E-Mail. Fehlende Kopfzeilen der Hauptadresse (nosniff, HSTS, CORS) erscheinen als Hinweis; geprüft wird mit GET, weil der Server HEAD-Anfragen auf einem anderen Weg beantwortet.
- Härtung (01.11.2026): alle GitHub-Aktionen auf feste Commits mit Versionskommentar (`# v4.4.0`); Rechte je Job, Schreiben nur in Jobs, die einen Branch schreiben (`deploy`, `kurzfassungen`, `archiv`, `quellen`, `auswertung`) oder GitHub Pages veröffentlichen.
- `tests.yml`: Unit-Tests, Syntaxprüfung, Node-Tests bei Pull Requests.
- Eigener Server (Plesk): Subdomain mit Let's-Encrypt-Zertifikat; „Git“ mit `https://github.com/daimpad/allris-test.git`, Branch `deploy`, automatische Bereitstellung; Webhook-URL in GitHub unter Settings → Webhooks (push). `SITE_URL` (Standard `https://ris-bonn.datenatlas.de/`) bestimmt die absoluten Adressen.

## Feeds und Seite rss/ (28.10.2026)
- Alle Feeds sind Atom 1.0 (`pipeline/publish.py`, `_atom`). Neu ist der Feed über ganz Bonn `data/export/bonn/feeds/ganz-bonn.xml` (`GANZ_BONN`): die letzten 100 Ereignisse aller Vorlagen, jede Vorlage einmal, Einträge mit derselben `id` wie in den Gebietsfeeds und einem Link auf das Gebiet der Vorlage.
- Seite `rss/` (`pipeline/rssseite.py`, Schritt `seo`, Sitemap): Feed-Adresse mit Kopierknopf (`site/rss.js`, Clipboard-API, Ausweichweg Markieren mit Meldung), drei Zugänge (abonnieren, einbinden, weiterverarbeiten mit Feldern, Kennungen, Abruf und Python-Beispiel, das `tests/test_rssseite.py` ausführt), Liste der Feeds je Gebiet und Thema ohne leere Feeds.
- Feed-Erkennung (`link rel="alternate"`): `index.html` und jede Seite aus `gebietsseiten._page` verweisen auf den Feed über ganz Bonn; Gebiets- und Themenseiten zusätzlich auf ihren eigenen Feed. `app.js` ergänzt den Feed des gewählten Gebiets (`data-gebiet`) und entfernt nur diesen.
- `deploy/htaccess`: `.xml` als `application/xml` mit UTF-8, Kompression und eine Stunde Zwischenspeicher; `Access-Control-Allow-Origin: *` für Feeds und offene Daten (`.xml`, `.json`, `.geojson`, `.ics`, `.tsv`, `.jsonld`), wie bei GitHub Pages.

