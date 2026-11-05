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
python -m pipeline package    # data/export/ratsatlas-koeln-export.zip
python -m pipeline geo-koeln  # Geodaten neu ableiten (lädt Zip-Dateien von offenedaten-koeln.de, falls nicht in data/raw/geo)
```

| Schritt | Ergebnis |
|---|---|
| `fetch` | Rohdaten im Bonner Format in `data/raw/`: `papers.jsonl`, `organizations.json`, `meetings.json` (und `meetings_roh.jsonl` mit TOPs), `legislative_terms.json`, `beratungen.jsonl` (Beratung → Sitzung und TOP, aus den Sitzungen abgeleitet); Zustand `zustand_abruf.json`; Abrufstatistik `data/export/abrufstatistik.tsv`; `STAND.json` mit Zeitpunkten, `abruf_fehler` oder `abruf_uebersprungen` |
| `build` | Tabellen Vorlage, Beratung, Sitzung, Tagesordnungspunkt, Organisation, Ort, Ortsbezug (mit Stufe, Methode, Konfidenz, Fundstelle), Einreichende, Zuständigkeit |
| `export` | je Stadtteil, Stadtbezirk und Jahr ohne Ortsbezug; `index.json`, `suche.json`, `zeit.json`, `prozesse.json`, Feeds, Kalender, GeoJSON, DCAT; stadtweite Audits `audit_*.tsv` und `stichprobe_geokodierung.tsv` |
| `seo` (über `tools/seite_bauen.py`) | Gebiets-, Begriffs-, Feed- und Technikseite, `robots.txt`, `sitemap.xml`, absolute Adressen aus `SITE_URL` |

### Abrufpolitik (CLAUDE.md 5.1)

`pipeline/abruf.py`: eine Verbindung, mindestens 2 s Abstand (`RATSATLAS_ABSTAND`), nur im Zeitfenster 23–1 Uhr Ortszeit (`RATSATLAS_ZEITFENSTER`; laut mandari die Vorgabe der Stadt, ohne Quelle der Stadt), nach 429 und 5xx Pausen von 1 min bis 3 h (`Retry-After` wird beachtet), sofortiger Abbruch bei 401/403/404. Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: Abbruch ohne Wiederholung, nach drei Nächten in Folge sieben Tage Pause. User-Agent `ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; <RATSATLAS_KONTAKT>)`. Listen nur über `links.next` (unverändert übernommen; Parameter ohne URL-Kodierung, weil SessionNet kodierte Zeitstempel mit 404 beantwortet; Abbruch bei Seiten ohne neue Kennungen oder mehr als `RATSATLAS_MAX_SEITEN`); ein abgebrochener Vollabruf wird in der nächsten Nacht fortgesetzt; ab dem zweiten vollständigen Lauf `modified_since` mit einem Tag Überlappung (`RATSATLAS_VOLLABRUF=ja` erzwingt einen Vollabruf). Ein Vollabruf ersetzt den Stand nur, wenn er mindestens 90 % der bisherigen Objekte enthält.

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
