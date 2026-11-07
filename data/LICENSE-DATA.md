# Lizenzen der Daten

Stand 07.11.2026. Der Code steht unter MIT (`LICENSE`). Für die Daten in `data/` gilt:

| Datei | Quelle | Lizenz | Namensnennung |
|---|---|---|---|
| `geo/stadtteile_koeln.geojson` | Stadt Köln, Datensatz „Stadtteile Köln“ (offenedaten-koeln.de), umgerechnet nach WGS84, um 2 m vereinfacht | Datenlizenz Deutschland – Zero – Version 2.0 | Datenquelle: Stadt Köln – offenedaten-koeln.de |
| `geo/stadtbezirke_koeln.geojson` | Stadt Köln, Datensatz „Stadtbezirke Köln“, umgerechnet und vereinfacht wie oben | dl-de/zero 2.0 | wie oben |
| `geo/strassen_koeln.json` | abgeleitet aus Stadt Köln, Datensatz „Straßen Köln“ (Lage je Stadtteil, Kreuzungen; Namen ausgeschrieben) | dl-de/zero 2.0 | wie oben |
| `geo/hausnummern_koeln.json` | abgeleitet aus Stadt Köln, Datensatz „Adressen Köln“ (Hausnummern je Straße und Stadtteil, Hauskoordinaten mit 5 Nachkommastellen) | dl-de/zero 2.0 | wie oben |
| `geo/bebauungsplaene_koeln.geojson` | OGC-API „Bauleitplanung in NRW (INSPIRE)“ des MHKBD NRW / IT.NRW, Datengrundlage Stadt Köln (`ogc-api.nrw.de/inspire-lu-bplan/v1`); nur rechtsverbindliche Pläne, um 0,5 m vereinfacht, Plannummer in der Schreibweise der Vorlagentitel | Datenlizenz Deutschland – Namensnennung – Version 2.0 (Angabe der Schnittstelle; die Metadaten nennen „keine Bedingungen“, geführt wird die strengere Angabe) | MHKBD NRW / IT.NRW, Bauleitplanung in NRW; Datengrundlage Stadt Köln |
| `kontext/zensus_koeln.tsv` | Zensus 2022, Gitterzellen 100 m (Destatis), Zellen mit Mittelpunkt in Köln | Datenlizenz Deutschland – Namensnennung – Version 2.0 | © Statistisches Bundesamt (Destatis), Zensus 2022 |
| `kontext/bodenrichtwerte_koeln.geojson` | BORIS NRW, Bodenrichtwerte Wohnbauland (Gutachterausschuss Köln) | dl-de/zero 2.0 | – |
| `kontext/klima_koeln.geojson` | Klimaanalyse NRW 2026, Planungshinweiskarte | dl-de/zero 2.0 | – |
| `kontext/ueberschwemmung_koeln.geojson` | Überschwemmungsgebiete NRW | dl-de/zero 2.0 | – |
| `kontext/kitas_koeln.tsv` | Kindertageseinrichtungen in NRW | dl-de/by 2.0 | Land NRW |
| `kontext/schulen_koeln.tsv` | Grunddaten der Schulen in NRW (ohne Kontaktdaten) | dl-de/by 2.0 | Ministerium für Schule und Bildung NRW |
| `kontext/haltestellen_koeln.tsv` | VRS-Fahrplandaten (GTFS), Steige zusammengefasst | dl-de/zero 2.0 | – |
| `ebenen/lebenswerte_veedel.geojson`, `sozialraeume.geojson`, `stimmbezirke.geojson`, `baupotenziale.geojson`, `fahrradstrassen.geojson`, `denkmaeler.geojson` | Stadt Köln (offenedaten-koeln.de, Geoportal); ohne Flurstücke und Eigentumsangaben | dl-de/zero 2.0 | Datenquelle: Stadt Köln – offenedaten-koeln.de |
| `ebenen/naturschutz.geojson` | LANUK NRW, INSPIRE Schutzgebiete (Natur-, Landschaftsschutz, FFH) | dl-de/zero 2.0 | – |
| `ebenen/hochwasser.geojson` | Land NRW, Hochwassergefahrenkarten (HQ100, HQextrem), je Szenario zusammengefasst, um 2 m vereinfacht | dl-de/zero 2.0 (Angabe von opengeodata.nrw.de) | – |
| `export/abrufstatistik.tsv` (entsteht beim Abruf) | eigene Protokollierung | dl-de/zero 2.0 | – |

Die Namensnennung führt der Ratsatlas immer, auch wo die Lizenz sie nicht verlangt (CLAUDE.md 8).

Noch nicht enthalten: Daten der OParl-API der Stadt Köln (Abruf erst nach Information der Stadt; Lizenz laut Katalog dl-de/zero 2.0, Klärung offen). Das Kölner Straßenverzeichnis (XLSX) steht unter dl-de/by 2.0 und wird bisher nicht verwendet. Volltexte, Auszüge und PDFs werden bis zur Lizenzklärung nicht veröffentlicht (CLAUDE.md 2 und 6).
