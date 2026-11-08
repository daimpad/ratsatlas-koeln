# Ratsatlas Köln – Technik

Technische Beschreibung von Pipeline, Seite und Betrieb. Worum es inhaltlich geht, steht in der [README](README.md); Auftrag und Entscheidungen stehen in [CLAUDE.md](CLAUDE.md).

## Aufbau des Repositorys

- `pipeline/` – Abruf (`abruf.py` Abrufpolitik, `sessionnet.py` Adapter für die Kölner OParl-API), Geodaten (`geodaten.py`), Aufbereitung (`build.py`), Geokodierung (`geocode.py`, `geo.py`, `plans.py`), Akteure (`actors.py`), Themen (`topics.py`), Prozessschritte (`process.py`), Export (`export.py`, `publish.py`), Datenpaket (`paket.py`), Seiten (`seo.py`, `gebietsseiten.py`, `begriffsseite.py`, `rssseite.py`, `technikseite.py`), Kartenkacheln (`kacheln/`). Bonner Zusatzthemen (Haushalt, Themenseiten, Baustellen, Soll-Modell, Ratsassistent u. a.) bleiben im Code, sind aber über `config.ZUSATZTHEMEN` abgeschaltet.
- `site/` – statische Seite (Leaflet, `app.js`, `timeline.js`, `tour.js`); Elemente der Zusatzthemen tragen `data-funktion` und bleiben ausgeblendet.
- `data/geo/` – Kölner Stadtteile, Stadtbezirke, Straßen- und Hausnummernverzeichnis (abgeleitet, dl-de/zero 2.0); `data/LICENSE-DATA.md`. Rohdaten (`data/raw/`) und Exporte (`data/export/`) sind nicht versioniert.
- `explore/` – Exploration (Phase 1): Messskripte für die OParl-API, Geodaten-Katalog, Anfrage an die Stadt.
- `inventur/` – Inventur der Bonner Kopie und Berichte der Phasen.
- `tests/` – Tests mit synthetischen Daten und einem lokalen OParl-Testserver; `tools/` – Testdaten, Seite zusammenstellen, WCAG-Prüfung.
- `.github/workflows/` – aktive Workflows; `.github/workflows-inaktiv/` – Bonner Workflows (laufen nicht).

## Pipeline

```bash
pip install -r requirements.txt
python -m pipeline fetch      # Abruf (gesperrt ohne RATSATLAS_STADT_INFORMIERT=ja; nur 23–1 Uhr)
python -m pipeline build      # SQLite data/build/allris.sqlite, Geokodierung, Akteure
python -m pipeline export     # data/export/koeln/, Audits, Stichprobe je Methode
python -m pipeline kontext    # Kennzahlen je Stadtteil, Flächen und Punkte (aus data/kontext/)
python -m pipeline ebenen     # Kartenebenen aus data/ebenen/ und export/koeln/ebenen.json
python -m pipeline package    # data/export/ratsatlas-koeln-export.zip
python -m pipeline kontext-ausschnitte   # einmalig: Zensus, BORIS, Klima, Überschwemmung, Kitas, Schulen, Haltestellen (Land, Bund)
python -m pipeline ebenen-laden          # einmalig: weitere Ebenen (Stadt, Land); je Datensatz höchstens 3 Anfragen
python -m pipeline bplan-koeln           # Bebauungspläne aus der OGC-API Bauleitplanung NRW
python -m pipeline geo-koeln  # Geodaten neu ableiten (lädt Zip-Dateien von offenedaten-koeln.de, falls nicht in data/raw/geo)
```

| Schritt | Ergebnis |
|---|---|
| `fetch` | Rohdaten im Bonner Format in `data/raw/`: `papers.jsonl`, `organizations.json`, `meetings.json` (und `meetings_roh.jsonl` mit TOPs), `legislative_terms.json`, `beratungen.jsonl` (Beratung → Sitzung und TOP, aus den Sitzungen abgeleitet); Zustand `zustand_abruf.json` (Zeitpunkte, Fortsetzungen, Zähler `sperre_verdacht` und `listenfehler`, `letzter_abbruch`, `nicht_vor` aus einem Retry-After); Abrufstatistik `data/export/abrufstatistik.tsv`; `STAND.json` mit Zeitpunkten, `abruf_fehler`, `abruf_uebersprungen` oder `abruf_hinweis` (ein vollständiger Lauf entfernt alle drei) |
| `build` | Tabellen Vorlage, Beratung, Sitzung, Tagesordnungspunkt, Organisation, Ort, Ortsbezug (mit Stufe, Methode, Konfidenz, Fundstelle), Einreichende, Zuständigkeit |
| `export` | je Stadtteil, Stadtbezirk und Jahr ohne Ortsbezug; `index.json`, `suche.json`, `zeit.json`, `prozesse.json`, Feeds, Kalender, GeoJSON, DCAT; stadtweite Audits `audit_*.tsv` und `stichprobe_geokodierung.tsv` |
| `seo` (über `tools/seite_bauen.py`) | Gebiets-, Begriffs-, Feed- und Technikseite, `robots.txt`, `sitemap.xml`, absolute Adressen aus `SITE_URL` |

### Abrufpolitik (CLAUDE.md 5.1)

`pipeline/abruf.py`: eine Verbindung, mindestens 2 s Abstand (`RATSATLAS_ABSTAND`, auch vor der ersten Anfrage eines Prozesses), nur im Zeitfenster 23–1 Uhr Ortszeit (`RATSATLAS_ZEITFENSTER`; laut mandari die Vorgabe der Stadt, ohne Quelle der Stadt), nach 429 und 5xx Pausen von 1 min bis 3 h (`Retry-After` als Sekunden oder HTTP-Datum wird eingehalten), sofortiger Abbruch bei 401/403/404. Eine Pause muss vor dem Ende des laufenden Zeitfensters enden (gerechnet in UTC, auch über eine Zeitumstellung); sonst, und wenn `Retry-After` länger als die längste Pause oder unlesbar ist, gibt der Abruf sofort auf („aufgegeben“), statt in einer späteren Nacht weiterzumachen. Ein solcher `Retry-After` gilt über die Nacht hinaus: Bis zu seinem Ablauf steht `nicht_vor` im Zustand und jeder Lauf wird übersprungen (höchstens 30 Tage; unlesbar 7 Tage; mehr als 12 Ziffern gelten als unendlich, also 30 Tage). Lokal (ohne Freigabe, Zeitfenster, Mindestabstand, 12-Stunden-Regel und `nicht_vor`) sind nur `http://127.0.0.1`, `http://localhost` und `http://[::1]` (Prüfung des Hosts, nicht des Anfangs der Adresse). Zeitüberschreitung, Verbindungsabbruch und abgeschnittene oder unlesbare Antworten (`http.client.HTTPException`, z. B. weniger Bytes als `Content-Length`) gelten als mögliche Sperre: Abbruch ohne Wiederholung, ebenso andere TLS-Fehler (unerwartetes Ende oder Reset im Handshake). Scheitert dagegen die Zertifikatsprüfung (`CERTIFICATE_VERIFY_FAILED`), ist das vermutlich eine Einstellung der Ausführungsumgebung (CA eines Proxys; ein Zertifikat der Gegenseite oder eine Sperrseite ist nicht ausgeschlossen): Abbruch der Art `tls` ohne Wiederholung, Warnung im Workflow-Log, gezählt als Fehler und nicht als Anfrage (die HTTP-Anfrage wurde nicht gesendet), keine Nacht mit möglicher Sperre; die 12-Stunden-Regel gilt (`letzter_abbruch`), Nächte mit `tls` zählt `tlsfehler`, nach drei Nächten ohne vollständigen Lauf dazwischen sieben Tage Pause. Eine Antwort, die kein JSON ist (auch zu tief verschachtelt), gilt wie 429/5xx. Gültiges JSON in unerwarteter Form (kein Objekt, Body ohne Listen, Listenseite ohne `data` oder mit einem nicht leeren `links`, das kein Objekt ist) bricht nach einer Anfrage ohne Wiederholung ab („unlesbar“); ein leeres `links` oder `links.next` (`null`, `""`, `[]`, `{}`; SessionNet ist in PHP geschrieben) gilt als Ende der Liste. Ungültige Adressen (Zeichen außerhalb von ASCII, ein anderes Schema als http oder https, kein Host, ungültiger Port, Leerzeichen) werden nicht gesendet und nicht gezählt; der Öffner kennt nur http und https (keine Handler für FTP, Dateien und `data:`). Andere Fehler vor dem Senden (Kopfzeile mit Zeilenumbruch oder Zeichen außerhalb von Latin-1, Host nicht als IDNA kodierbar, unlesbare Proxy-Adresse) sind Einstellungs- oder Programmfehler: laut, nicht gezählt, keine Pausen; `RATSATLAS_KONTAKT` wird ohne Leerraum am Rand übernommen. Als Nacht mit möglicher Sperre zählen außerdem HTTP 401/403/429, „aufgegeben“ nach 429/5xx oder unlesbaren Antworten, Weiterleitungen und „unlesbar“; nicht dagegen Ablehnungen durch einen Proxy der Ausführungsumgebung und ungültige Adressen (sie haben die Stadt nie erreicht) sowie ein Vollabruf mit weniger als 90 % der bisherigen Objekte (Abbruch der Art `leer`). Nach jedem Abbruch außer dem Ende des Zeitfensters (auch nach einer Ablehnung durch den Proxy, einer ungültigen Adresse oder einem Programmfehler) folgt in derselben Nacht (12 h) kein weiterer Lauf (`letzter_abbruch`); nach drei Nächten mit möglicher Sperre ohne vollständigen Lauf dazwischen sieben Tage Pause. Abbrüche wegen ungültiger Folgeadressen oder Schleifen in `links.next` (ohne Fortsetzung, also jede Nacht ein Vollabruf von vorn) zählt `listenfehler` (Nächte, nicht Läufe): Hinweis in `STAND.json` (`abruf_hinweis`), Warnung im Workflow-Log, nach drei Nächten sieben Tage Pause. Vor der ersten Anfrage wird der Zustand geprüft: Eine unlesbare Datei oder ein unlesbarer Zeitpunkt einer Liste bricht ohne Anfrage mit Fehler ab, bei jedem Lauf, bis die Datei geprüft ist (Abhilfe in GitHub Actions: den jüngsten Zwischenspeicher `raw-…` unter Actions → Caches löschen, dann nimmt der nächste Lauf den vorigen Stand; kein automatisches Neuanlegen); ein unlesbarer, zonenloser oder künftiger Zeitpunkt des letzten Sperrverdachts, Listenfehlers oder Abbruchs gilt als „jetzt“, eine unlesbare Zahl der Nächte als drei, ein unlesbares `nicht_vor` als jetzt + 7 Tage, eines mehr als 30 Tage voraus als jetzt + 30 Tage (alles neu geschrieben und gemeldet); eine unlesbare Fortsetzung wird verworfen. Programm- und Einstellungsfehler (auch ein `RuntimeError` ohne Art, etwa `RecursionError`) zählen nicht als Sperrverdacht, sondern brechen mit Traceback ab (Abrufschritt rot, die alte Seite bleibt online) und stehen in `STAND.json`. Ein vollständiger Lauf entfernt `abruf_fehler`, `abruf_hinweis` und `abruf_uebersprungen`; die Seite meldet einen fehlgeschlagenen Abruf nur, wenn er nach dem letzten vollständigen liegt. Endet das Zeitfenster während eines Vollabrufs über mehrere Nächte, ist das kein Fehler: neutraler Hinweis in `abruf_hinweis`, Fortsetzung in der nächsten Nacht. `pages.yml` sichert den Zustand gleich nach dem Abrufschritt, auch wenn ein späterer Schritt scheitert. User-Agent `ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; <RATSATLAS_KONTAKT>)`. Listen nur über `links.next` (unverändert übernommen; Parameter ohne URL-Kodierung, weil SessionNet kodierte Zeitstempel mit 404 beantwortet; Abbruch bei Seiten ohne neue Kennungen oder mehr als `RATSATLAS_MAX_SEITEN` Seiten in einem Lauf); ein abgebrochener Vollabruf wird in der nächsten Nacht fortgesetzt (die Seitengrenze zählt dort neu; über alle Fortsetzungen höchstens das Dreifache, sonst Abbruch wie bei einer Schleife). Köln liefert die Vorlagen neueste zuerst und ohne Gesamtzahlen (`pagination` nur `elementsPerPage` und `currentPage`, Stufe 1): Neue Vorlagen zwischen zwei Nächten verschieben die Seiten nach hinten; in einer Fortsetzung gelten Seiten ohne neue Kennungen bis zu vier je angefangenem Tag seit dem Speichern der Fortsetzung (`gespeichert`, höchstens 40; `verschiebung_erlaubt`; bei 25 je Seite rund 100, genauer 99 neue Vorlagen je Tag, weil die wiederholte Seite mitzählt) als Seitenverschiebung, nicht als Schleife; bricht eine Fortsetzung ab, bevor sie die verschobene Zone verlassen hat (noch keine ungelesene Vorlage, deren `created` nicht jünger ist als das der 25.-ältesten gelesenen; gleich alt genügt, bis zu 24 Platzhalterdaten unter den gelesenen stören nicht), bleibt `gespeichert` (die Verschiebung seit dann besteht weiter). Das setzt voraus, dass Köln die Liste streng nach `created` absteigend sortiert; belegt ist das nur für die erste Seite (Stufe 1), die Prüfung über mehrere Seiten ist für Stufe 3 vorgesehen. Trifft es nicht zu, gilt die Zone zu früh als verlassen (in der Folgenacht womöglich ein Listenfehler) oder nie (erlaubte Verschiebung bis 40, ein schwächerer Schutz gegen Schleifen); eine Seite, deren Kennungen alle schon in diesem Lauf kamen, und eine wiederholte Adresse bleiben eine Schleife. Die Fortsetzung beginnt eine Seite vor der Abbruchstelle (eine Anfrage mehr, zählt als Verschiebung): So gehen bis zu einer Seite (25) zwischen den Nächten gelöschter Vorlagen nicht zulasten der folgenden; bei mehr Löschungen können Vorlagen bis zum nächsten Vollabruf fehlen. Zwischen den Nächten gelöschte, schon gelesene Vorlagen bleiben bis zum nächsten Vollabruf bzw. bis zu ihrem Eintrag mit `deleted` aus `modified_since` im Stand. Doppelungen werden über die Kennung zusammengeführt, die neuen Vorlagen am Listenanfang holt der nächste inkrementelle Lauf; ab dem zweiten vollständigen Lauf `modified_since` mit einem Tag Überlappung (`RATSATLAS_VOLLABRUF=ja` erzwingt einen Vollabruf). Ein Vollabruf ersetzt den Stand nur, wenn er mindestens 90 % der bisherigen Objekte enthält. `pipeline/net.py` (aus Bonn: Wiederholungen, mehrere Verbindungen, kein Zeitfenster) verweigert Anfragen an Adressen der Stadt (stadt-koeln.de, offenedaten-koeln.de, Host der OParl-API), auch als Ziel einer Weiterleitung (ein unlesbares Ziel gilt vorsichtshalber als Adresse der Stadt); solche Abrufe, etwa `fetch-besetzung`, gehören auf `pipeline/abruf.py` umgestellt. Module, die direkt über urllib abrufen (`geodaten.py`, `ebenen.py`, `kontext.py` u. a.), erfasst dieser Schutz nicht.

### Geokodierung (CLAUDE.md 5.2)

| Methode | Ebene | Konfidenz |
|---|---|---|
| `oparl_sublocality` (Stufe A) | Stadtteil | mittel |
| `strasse`, `strasse+ortsteil`, `strasse+bezirk`, `strasse+kreuzung`, `strasse_mehrdeutig` | Straße | mittel bzw. niedrig |
| `strasse+hausnummer` (Stadtteil aus „Adressen Köln“) | Straße | mittel |
| `strasse+hausnummer_punkt` (nur Verwaltungsvorlagen und politische Anträge, `hausnummer_punkt_erlaubt`) | Adresse | hoch |
| `ortsteil_name`, `ortsteil_teilname`, `stadtbezirk_name` (nur eindeutige Bezirksformen) | Stadtteil, Stadtbezirk | mittel |
| `district_from_committee` (nur eine Bezirksvertretung, sonst kein Ort) | Stadtbezirk | niedrig |

## Lokale Entwicklung ohne Abruf

```bash
python -m pytest tests
python tools/testdaten.py && python -m pipeline build && python -m pipeline export   # synthetisch, „[Testdaten]“
python tools/vorschau.py && python -m pipeline build && python -m pipeline export   # Kartenvorschau ohne Vorlagen (wie pages.yml ohne Daten der Stadt)
python tools/seite_bauen.py && python -m http.server -d _site 8000
```

Testdaten werden nie veröffentlicht: `pages.yml` bricht ab, wenn `STAND.json` sie kennzeichnet.

## Workflows

| Datei | Zeit | Aufgabe |
|---|---|---|
| `pages.yml` | täglich 22:10 UTC, bei Push auf `main`, auf Knopfdruck | Abruf (gesperrt bis zur Repository-Variable `RATSATLAS_STADT_INFORMIERT=ja`), Aufbereitung, Export, Datenpaket; Branch `deploy` (Hauptadresse über Plesk) und Spiegel auf GitHub Pages mit Canonical auf `SITE_URL`. Ohne Daten endet der Lauf ohne Veröffentlichung. |
| `kacheln.yml` | vierteljährlich, auf Knopfdruck, bei Pull Requests zu `pipeline/kacheln/` | graue Kartenkacheln aus OSM (Protomaps-Ausschnitt Köln) in den Branch `kacheln`, danach `pages.yml` |
| `tests.yml` | Pull Requests, Push auf `main` | Tests, Syntax der Seite |
| `live.yml` | auf Knopfdruck (nach der Einrichtung in Plesk täglich) | Hauptadresse und Spiegel erreichbar, aktueller Stand, Canonical, Kopfzeilen |

Variablen (Einstellungen → Secrets and variables → Actions → Variables): `RATSATLAS_STADT_INFORMIERT`, `RATSATLAS_KONTAKT`, `SITE_URL`. Keine Zugangsdaten im Repository; Plesk zieht den Branch `deploy` (siehe [docs/PLESK.md](docs/PLESK.md)).
