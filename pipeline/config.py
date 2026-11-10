"""Pfade, Quellen, Lizenzen und Abrufpolitik der Pipeline (Ratsatlas Köln)."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Rohdaten; die Kartenvorschau ohne Ratsvorlagen nutzt ein eigenes Verzeichnis (RATSATLAS_RAW, tools/vorschau.py)
RAW = ROOT / os.environ.get("RATSATLAS_RAW", "data/raw")
GEO = ROOT / "data" / "geo"
BUILD = ROOT / "data" / "build"
EXPORT = ROOT / "data" / "export"

PAPERS = RAW / "papers.jsonl"
ORGANIZATIONS = RAW / "organizations.json"
VERWALTUNGSBEREICHE = RAW / "verwaltungsbereiche.json"
# Beratungen mit Sitzung und TOP (in Bonn aus OParl-Lite; in Köln vom SessionNet-Adapter aus den Sitzungen abgeleitet,
# gleiches Format: uri, meeting{uri,name,startDate,cancelled}, agendaItem{uri,number,name,result,public})
BERATUNGEN = RAW / "beratungen.jsonl"
CONSULTATIONS_LITE = BERATUNGEN
MEETINGS = RAW / "meetings.json"
LEGISLATIVE_TERMS = RAW / "legislative_terms.json"
BESETZUNG = RAW / "besetzung.json"   # Auszug laufender Mitgliedschaften ohne Kontaktdaten (pipeline/besetzung.py)
OSM_STREETS = RAW / "osm_streets.json"
# Volltexte der Hauptdokumente (in Köln aus den PDFs, Phase 3): nur zur Verarbeitung, lokal und im Zwischenspeicher
# des Workflows; nie im Repository, auf der Seite oder im Datenpaket (CLAUDE.md 2 und 6)
TEXTE = RAW / "texte.jsonl"
OSM_TILES = RAW / "osm_tiles"
STAND = RAW / "STAND.json"
# Gebiete und Straßen (Kölner Geodaten, abgeleitet mit `python -m pipeline geo-koeln`). Die Eigenschaften der
# Flächen heißen wie in Bonn (ortsteil, ortsteil_bez, bezirk, bezirk_bez); angezeigt wird „Stadtteil“ (Phase-0-Bericht 3.3)
ORTSTEILE = GEO / "stadtteile_koeln.geojson"
STADTBEZIRKE = GEO / "stadtbezirke_koeln.geojson"
# Straßenverzeichnis (Name → Lagen je Stadtteil), abgeleitet aus dem Datensatz „Straßen Köln“
STRASSEN = GEO / "strassen_koeln.json"
BPLAN = GEO / "bebauungsplaene_koeln.geojson"          # OGC-API Bauleitplanung NRW (pipeline/bplan.py)
PLAN_LOG = GEO / "bebauungsplaene_protokoll.tsv"
HAUSNUMMERN = GEO / "hausnummern_koeln.json"           # aus „Adressen Köln“ (geodaten.py)
OBJEKTE = GEO / "objekte_koeln.json"                   # folgt in Phase 3 (OSM, ODbL)
DB = BUILD / "allris.sqlite"

# OParl-API der Stadt Köln (SessionNet); Abruf nur nach Information der Stadt (CLAUDE.md 9)
OPARL_SYSTEM = os.environ.get("RATSATLAS_OPARL_SYSTEM", "https://buergerinfo.stadt-koeln.de/oparl/system")
OPARL_BODY = os.environ.get("RATSATLAS_OPARL_BODY",
                            "https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
# Zustand des inkrementellen Abrufs (letzte Änderungszeitpunkte je Liste) und Abrufstatistik je Lauf
ZUSTAND = RAW / "zustand_abruf.json"
ABRUFSTATISTIK = EXPORT / "abrufstatistik.tsv"
# Abrufpolitik (CLAUDE.md 5.1): eine Verbindung, Abstand in Sekunden, nächtliches Zeitfenster (Ortszeit Köln),
# wachsende Pausen nach Fehlern bis zu mehreren Stunden
ABRUF_ABSTAND = float(os.environ.get("RATSATLAS_ABSTAND", "2.0"))
# Zeitfenster 23–1 Uhr: laut mandari erlaubt die Stadt Abrufe nur dann (ohne Quelle der Stadt; Anfrage offen,
# explore/ergebnisse/sessionnet_befunde.tsv)
ABRUF_ZEITFENSTER = os.environ.get("RATSATLAS_ZEITFENSTER", "23-1")   # Stunden von-bis; leer = ohne Zeitfenster
# Objekte je Liste und Lauf (Höflichkeitsgrenze je Nacht), umgerechnet in Seiten mit der tatsächlichen Seitengröße des
# Laufs (sessionnet.py); eine Fortsetzung zählt in ihrem Lauf neu. 100 000 Objekte sind 1000 Seiten zu 100 (4000 zu 25),
# also höchstens rund 1000 Anfragen je Liste und Nacht. Kapazität des Zeitfensters (rund 108 Minuten nach der
# Einrichtung des Laufs, TECHNIK.md) bei 100 je Seite und 2 s Abstand: bei 5 s Antwortzeit rund 900 Seiten, bei 3 s
# rund 1300; bei schnellen Antworten greift also die Grenze vor dem Ende des Fensters. Erreicht ein Vollabruf sie, gilt
# das wie das Ende des Zeitfensters (Art `obergrenze`: Fortsetzung in der nächsten Nacht, kein Listenfehler, in
# derselben Nacht kein weiterer Lauf); ein inkrementeller Lauf bricht dort als Listenfehler ab (Art `liste`). Werte
# unter (ceil(1000 / g) + 2) · g mit g = RATSATLAS_LIMIT (sessionnet.max_objekte_mindestens(); bei 100 je Seite 1200,
# bei 150 1350) lehnt der Abruf vor der ersten Anfrage als Einstellungsfehler ab
ABRUF_MAX_OBJEKTE = int(os.environ.get("RATSATLAS_MAX_OBJEKTE", "100000"))
# Gesamtgrenze eines Vollabrufs über seine Fortsetzungen hinweg (Schutz gegen eine Liste, die endlos neue Kennungen
# erzeugt), in Objekten, umgerechnet wie oben; darüber Abbruch der Art `liste`. 600 000: Ein Vollabruf mit bis zu
# 500 000 Objekten je Liste wird sicher fertig (Kölner Gesamtzahl ungemessen; Stufe 1: höchste Kennung rund 135 000);
# der Spielraum deckt die wiederholte Seite je Fortsetzung und die Seitenverschiebung durch neue Vorlagen
ABRUF_MAX_OBJEKTE_GESAMT = 600_000
ABRUF_PAUSEN = [60, 300, 1800, 3600, 3 * 3600]
# Objekte je Seite (`limit`; Köln, Stufe 2: limit=100 wirkt, rund 5 s je Antwort); leer = Vorgabe des Servers (25)
ABRUF_SEITENGROESSE = os.environ.get("RATSATLAS_LIMIT", "100")
OVERPASS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
# Umgebendes Rechteck des Kölner Stadtgebiets (Süd, West, Nord, Ost), gerundet; aus Stadtbezirke Köln (24.09.2026)
STADT_BBOX = (50.83, 6.77, 51.09, 7.17)
# Kontakt im User-Agent; Leerraum am Rand (etwa ein Zeilenumbruch aus der Repository-Variable) entfällt, Steuerzeichen
# im Inneren lehnt abruf.get_json vor der ersten Anfrage ab
KONTAKT = os.environ.get("RATSATLAS_KONTAKT", "").strip()
USER_AGENT = ("ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln" + (f"; {KONTAKT}" if KONTAKT else "")
              + ")")

# Quellenkennungen in Datenbank und Exporten
QUELLE_OPARL = "oparl-koeln"      # Vorlagen, Organisationen, Beratungen
QUELLE_SITZUNG = "oparl-koeln"    # Sitzungen und TOPs (in Bonn aus OParl-Lite, in Köln aus derselben API)
QUELLE_GEO = "geo-koeln"
QUELLE_STRASSEN = "strassen-koeln"
QUELLE_BPLAN = "bplan-koeln"
QUELLE_ADRESSEN = "adressen-koeln"
NAMENSNENNUNG = "Datenquelle: Stadt Köln – offenedaten-koeln.de"

# Quelle je Datensatz; wird in die Datenbank und in jeden Export übernommen.
SOURCES = {
    QUELLE_OPARL: {
        "url": OPARL_BODY,
        "license": "dl-de/zero 2.0 laut Katalog „OParl API Koeln“ (Klärung offen, CLAUDE.md 8); " + NAMENSNENNUNG,
    },
    QUELLE_GEO: {
        "url": "https://www.offenedaten-koeln.de/dataset/stadtteile-koeln",
        "license": "dl-de/zero 2.0 (Stadt Köln, Stadtteile und Stadtbezirke); " + NAMENSNENNUNG,
    },
    QUELLE_STRASSEN: {
        "url": "https://www.offenedaten-koeln.de/dataset/strassen-koeln",
        "license": "dl-de/zero 2.0 (Stadt Köln, Straßen Köln); " + NAMENSNENNUNG,
    },
    QUELLE_ADRESSEN: {
        "url": "https://www.offenedaten-koeln.de/dataset/adressen-koeln",
        "license": "dl-de/zero 2.0 (Stadt Köln, Adressen Köln); " + NAMENSNENNUNG,
    },
    QUELLE_BPLAN: {
        "url": "https://ogc-api.nrw.de/inspire-lu-bplan/v1",
        "license": "dl-de/by 2.0 (Bauleitplanung in NRW, INSPIRE: MHKBD NRW / IT.NRW, Datengrundlage Stadt Köln)",
    },
    "osm": {
        "url": "https://www.openstreetmap.org/copyright",
        "license": "ODbL 1.0, © OpenStreetMap-Mitwirkende (Kartenhintergrund über Protomaps)",
    },
}
# Verweise auf Abschnitte dieser Arbeitsdatei („CLAUDE.md 8“) in Lizenztexten: nur für das Repository. Wo Leser:innen den
# Text sehen (DCAT, Technikseite; auf der Seite site/app.js lizenzOeffentlich), entfällt der Verweis (Runde 19b);
# SOURCES bleibt die gemeinsame Quelle und wird unverändert exportiert.
_INTERN = (re.compile(r"\s*\(CLAUDE\.md \d+(?:\.\d+)*\)"), re.compile(r",\s*CLAUDE\.md \d+(?:\.\d+)*"))


def lizenz_oeffentlich(text):
    """Lizenztext ohne Verweis auf CLAUDE.md: „(Klärung offen, CLAUDE.md 8)“ → „(Klärung offen)“."""
    for muster in _INTERN:
        text = muster.sub("", text)
    return text


# Bezugsquellen der Geodaten (Katalog offenedaten-koeln.de, geprüft am 04.11.2026, explore/ergebnisse)
GEO_DOWNLOADS = {
    "stadtteile": "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/Stadtteil_0.zip",
    "stadtbezirke": "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/Stadtbezirk_0.zip",
    "strassen": "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/Strasse_1.zip",
    "adressen": "https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/Adresse_0.zip",
}

# Stadt: Schlüssel für Exportpfade (data/export/koeln) und Bezeichnung auf der Seite
STADT = "koeln"
STADT_NAME = "Köln"
SEITENNAME = "Ratsatlas Köln"

# Kein Pilot-Stadtteil (CLAUDE.md 2); bleibt für Module, die den Bonner Pilot noch kennen
PILOT_ORTSTEIL = None

# Zusatzthemen aus Bonn: deaktiviert, nicht gelöscht (CLAUDE.md 5.4, Inventur Phase 0); einzeln freizugeben
ZUSATZTHEMEN = {
    "haushalt": False, "baustellen": False, "anliegen": False, "wahlen": False, "themenseiten": False,
    "kontext": True, "soll": False, "chat": False,
    # zweiter Lauf (Entscheidung 04.11.2026)
    "einfache_sprache": False, "kurzfassungen": False, "mitmachen": False, "besetzung": False,
    # Seite technik/ (aus den Workflows erzeugt; für Köln seit Phase 5)
    "technik": True,
    # Strukturdaten (Datenvertrag „Strukturdaten“, data/strukturdaten/) auf Seite und im Datenpaket, Einwohnerzahl und
    # Altersanteile der Kennzahlen aus der Stadtstatistik (Option b). Sichtung am 10.11.2026 bestätigt; eingeschaltet
    # in einem eigenen Pull Request nach der ersten Abrufnacht und nach Zusammenführung von Pull Request #19 und
    # Phase 3 (Entscheidung 10.11.2026, Abend). Ohne Freigabe bleiben Seite, Datenpaket und kontext.json wie zuvor
    # (pipeline/strukturdaten_web.py, pipeline/kontext.py)
    "strukturdaten": False,
}

# Archiv der Baustellen (Bonn, deaktiviert; Branch „archiv“, im Workflow nach _archiv ausgecheckt)
BAUSTELLEN_ARCHIV = Path(os.environ.get("BAUSTELLEN_ARCHIV", ROOT / "_archiv"))
# noch nicht in SOURCES, solange die Baustellen nicht auf der Seite erscheinen
BAUSTELLEN_LICENSE = ("CC0 1.0 (Stadt Bonn, Baustellen tagesaktuell und geplant; Lizenz laut Auftraggeber, die Datensätze "
                      "sind nicht mehr im Katalog von opendata.bonn.de)")

# Öffentliche Adresse der Seite (für absolute Links in Feeds, Kalender und DCAT-Beschreibung)
SITE_URL = os.environ.get("SITE_URL", "https://koeln.ratsatlas.de/")
# Das Datenpaket (Zip) liegt nur auf dem Pages-Spiegel; der Branch `deploy` für die Hauptadresse enthält es nicht
PAKET_URL = os.environ.get("PAKET_URL",
                           "https://daimpad.github.io/ratsatlas-koeln/data/export/ratsatlas-koeln-export.zip")
