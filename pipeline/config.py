"""Pfade, Quellen und Lizenzen der Pipeline."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
GEO = ROOT / "data" / "geo"
BUILD = ROOT / "data" / "build"
EXPORT = ROOT / "data" / "export"

PAPERS = RAW / "papers.jsonl"
ORGANIZATIONS = RAW / "organizations.json"
VERWALTUNGSBEREICHE = RAW / "verwaltungsbereiche.json"
CONSULTATIONS_LITE = RAW / "consultations_lite.jsonl"
MEETINGS = RAW / "meetings.json"
LEGISLATIVE_TERMS = RAW / "legislative_terms.json"
BESETZUNG = RAW / "besetzung.json"   # Auszug laufender Mitgliedschaften ohne Kontaktdaten (pipeline/besetzung.py)
OSM_STREETS = RAW / "osm_streets.json"
# Volltexte der Hauptdokumente (aus OParl-Lite, dort aus den PDFs der Stadt extrahiert): nur zur Verarbeitung,
# lokal und im Zwischenspeicher des Workflows; nie im Repository, auf der Seite oder im Datenpaket
TEXTE = RAW / "texte.jsonl"
OSM_TILES = RAW / "osm_tiles"
STAND = RAW / "STAND.json"
ORTSTEILE = GEO / "ortsteile_bonn.geojson"
STADTBEZIRKE = GEO / "stadtbezirke_bonn.geojson"
# Straßenverzeichnis (Name → Lagen je Ortsteil), abgeleitet aus OSM; im Repository, damit die
# Aktualisierung ohne Overpass auskommt. Neu erzeugen mit `python -m pipeline gazetteer`.
STRASSEN = GEO / "strassen_bonn.json"
BPLAN = GEO / "bebauungsplaene_bonn.geojson"
PLAN_LOG = GEO / "bebauungsplaene_protokoll.tsv"  # Änderungen zwischen Abrufen (neu, entfallen, Inkrafttreten)
BPLAN_URL = "https://stadtplan.bonn.de/geojson?Thema=20074"
# Hausnummern (Straße → Ortsteil → Nummern), reduziert aus dem georeferenzierten Verzeichnis der Stadt; dient nur
# dazu, bei Titeln mit Hausnummer den Ortsteil einer Straße zu bestimmen, die durch mehrere Ortsteile läuft.
HAUSNUMMERN = GEO / "hausnummern_bonn.json"
HAUSNUMMERN_URL = "https://stadtplan.bonn.de/geojson?OD=171"
OBJEKTE = GEO / "objekte_bonn.json"
DB = BUILD / "allris.sqlite"

OPARL_BODY = "https://www.bonn.sitzung-online.de/oparl/bodies/1"
LITE_GRAPHQL = "https://oparl.bonn.machdenstaat.de/graphql"
OVERPASS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
# Umgebendes Rechteck der 51 Ortsteile (Süd, West, Nord, Ost), für den Kachelabruf gerundet
BONN_BBOX = (50.63, 7.02, 50.78, 7.22)
USER_AGENT = "allris-bonn-pipeline (https://github.com/daimpad/allris-test)"

# Quelle je Datensatz; wird in die Datenbank und in jeden Export übernommen.
SOURCES = {
    "oparl-bonn": {
        "url": OPARL_BODY,
        "license": "CC0 1.0 (Stadt Bonn, Datensatz „Ratsinformationssystem OParl-API“)",
    },
    "oparl-lite": {
        "url": LITE_GRAPHQL,
        "license": "CC BY 4.0 (OParl-Lite Bonn, machdenstaat)",
    },
    "osm": {
        "url": "https://www.openstreetmap.org (Overpass API)",
        "license": "ODbL 1.0, © OpenStreetMap-Mitwirkende",
    },
    "geo-bonn": {
        "url": "https://opendata.bonn.de/dataset/flächen-der-ortsteile",
        "license": "CC0 1.0 (Stadt Bonn)",
    },
    "bplan-bonn": {
        "url": "https://opendata.bonn.de/dataset/lage-der-bebauungspläne",
        "license": "CC0 1.0 (Stadt Bonn, Datensatz „Lage der Bebauungspläne“)",
    },
    "hnr-bonn": {
        "url": "https://opendata.bonn.de/dataset/strassenliste-straßennamen-straßenverzeichnis-hausnummern-georeferenziert",
        "license": "CC0 1.0 (Stadt Bonn, Datensatz „Hausnummern georeferenziert“)",
    },
}

PILOT_ORTSTEIL = "Endenich"

# Archiv der Baustellen (Branch „archiv“, im Workflow nach _archiv ausgecheckt)
BAUSTELLEN_ARCHIV = Path(os.environ.get("BAUSTELLEN_ARCHIV", ROOT / "_archiv"))
# noch nicht in SOURCES, solange die Baustellen nicht auf der Seite erscheinen
BAUSTELLEN_LICENSE = ("CC0 1.0 (Stadt Bonn, Baustellen tagesaktuell und geplant; Lizenz laut Auftraggeber, die Datensätze "
                      "sind nicht mehr im Katalog von opendata.bonn.de)")

# Öffentliche Adresse der Seite (für absolute Links in Feeds, Kalender und DCAT-Beschreibung)
SITE_URL = os.environ.get("SITE_URL", "https://ris-bonn.datenatlas.de/")
# Das Datenpaket (Zip) liegt nur auf GitHub Pages; der Branch `deploy` für die Hauptadresse enthält es nicht
# (pages.yml, Schritt „Branch deploy“, setzt dieselbe Adresse in index.html und datenschutz.html)
PAKET_URL = os.environ.get("PAKET_URL", "https://daimpad.github.io/allris-test/data/export/allris-bonn-export.zip")
