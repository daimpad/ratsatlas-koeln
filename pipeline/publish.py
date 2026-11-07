"""Abonnieren und Nachnutzen (Ratsatlas Köln): Atom-Feeds je Gebiet und je Vorlage, Sitzungskalender (iCalendar),
GeoJSON aller verorteten Vorlagen und eine Beschreibung des Datensatzes nach DCAT-AP (JSON-LD).

Alle Dateien ändern sich nur, wenn sich ihr Inhalt ändert (keine Erzeugungszeitpunkte), damit der
Branch deploy nicht täglich vollständig neu geschrieben wird."""
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from . import config

FEED_LIMIT = 100
GANZ_BONN = f"ganz-{config.STADT}"   # Feed über alle Gebiete (Seite rss/); Name aus Bonn übernommen
TAG = f"tag:ratsatlas-{config.STADT},2026"
EXPORT_PFAD = f"data/export/{config.STADT}"
RIGHTS = ("Abgeleitet aus dem Ratsinformationssystem der Stadt Köln (OParl-API; Lizenz laut Katalog dl-de/zero 2.0, "
          "Klärung mit der Stadt offen). " + config.NAMENSNENNUNG + ". Maßgeblich ist das Original.")
LICENCE = {  # EU-Vokabular für Lizenzen (DCAT-AP)
    "cc0": "http://publications.europa.eu/resource/authority/licence/CC0",
    "cc-by": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0",
    "odbl": "http://publications.europa.eu/resource/authority/licence/ODC_BL",
    "dl-de-by": "http://dcat-ap.de/def/licenses/dl-by-de/2.0",
    "dl-de-zero": "http://dcat-ap.de/def/licenses/dl-zero-de/2.0",
}


def site_link(area, reference=None):
    url = f"{config.SITE_URL}?gebiet={quote(area, safe=':')}"
    return url + (f"#{quote(reference)}" if reference else "")


# --- Atom-Feeds --------------------------------------------------------------------------------------

def events(p, with_followups=False):
    """Ereignisse einer Vorlage: neue Vorlage, Beratungen mit Ergebnis, auf Wunsch Folgevorlagen."""
    out = []
    if p["date"]:
        out.append({"date": p["date"], "id": f"{p['source_object']}#vorlage",
                    "title": f"Neue Vorlage {p['reference']}: {p['name']}",
                    "summary": f"{p['paper_type']} · federführend: {p['amt'] or 'unbekannt'} · Stand: {p['stand']}"
                               + (f" · KI-Kurzfassung (abgeleitet, Einzelheiten können ungenau sein): {p['kurzfassung']['text']}"
                                  if p.get("kurzfassung") else "")})
    for s in p["steps"]:
        if s["typ"] in ("beratung", "entscheidung") and s.get("result") and s.get("date"):
            # ID aus Datum und Gremium, nicht aus der Position: eine neue Folgevorlage oder Beratung verschob sonst
            # die Nummern, und Feed-Reader zeigten Einträge doppelt (Code-Prüfung 23.10.2026)
            out.append({"date": s["date"], "id": f"{p['source_object']}#beratung-{s['date']}-{quote(s['label'], safe='')}",
                        "title": f"{s['label']}: „{s['result']}“ – {p['reference']} {p['name']}",
                        "summary": f"{s.get('role') or 'Beratung'} am {s['date']}; Ergebnis laut Ratsinformationssystem. "
                                   f"Stand der Vorlage: {p['stand']}"})
        if with_followups and s["typ"] == "folgevorlage" and s.get("date"):
            out.append({"date": s["date"], "id": f"{p['source_object']}#folge-{quote(s['reference'], safe='')}",
                        "title": f"{s['label']} {s['reference']}: {s['title']}",
                        "summary": f"Folgevorlage zu {p['reference']}"})
    return out


def _atom(feed_id, title, subtitle, self_url, alt_url, entries):
    entries = sorted(entries, key=lambda e: (e["date"], e["id"]), reverse=True)
    updated = (entries[0]["date"] if entries else "2019-10-01") + "T00:00:00Z"
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="de">',
             f"<id>{escape(feed_id)}</id>", f"<title>{escape(title)}</title>",
             f"<subtitle>{escape(subtitle)}</subtitle>", f"<updated>{updated}</updated>",
             f'<link rel="self" type="application/atom+xml" href={quoteattr(self_url)}/>',
             f'<link rel="alternate" type="text/html" href={quoteattr(alt_url)}/>',
             f"<author><name>{escape(config.SEITENNAME)}</name><uri>{escape(config.SITE_URL)}</uri></author>",
             f"<rights>{escape(RIGHTS)}</rights>"]
    for e in entries:
        parts += ["<entry>", f"<id>{escape(e['id'])}</id>", f"<title>{escape(e['title'])}</title>",
                  f"<updated>{e['date']}T00:00:00Z</updated>",
                  f'<link rel="alternate" type="text/html" href={quoteattr(e["link"])}/>',
                  f'<link rel="related" type="text/html" href={quoteattr(e["original"])}/>' if e.get("original") else "",
                  f"<summary>{escape(e['summary'])}</summary>", "</entry>"]
    parts.append("</feed>")
    # Steuerzeichen aus der Quelle sind in XML nicht erlaubt; sie machten den ganzen Feed ungültig
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", "\n".join(x for x in parts if x)) + "\n"


OPEN = ("in Beratung", "offen")


def has_paper_feed(p, since):
    """Feed je Vorlage nur, wo sich noch etwas ändern kann: Vorlagen ab dem Vorjahr des Datenstands
    oder noch nicht abgeschlossen (die Seite wendet dieselbe Regel an)."""
    return (p["date"] or "") >= since or p["stand"] in OPEN


def feed_url(name):
    return f"{config.SITE_URL}{EXPORT_PFAD}/feeds/{name}.xml"


def write_feeds(out, areas, cache, names, home, slug, since):
    """Je Gebiet die letzten Ereignisse, dazu ein Feed über die ganze Stadt (alle Vorlagen, jede einmal; die Einträge
    verweisen auf das Gebiet der Vorlage und tragen dieselben IDs wie in den Gebietsfeeds); je Vorlage (siehe
    has_paper_feed) alle Ereignisse."""
    base = f"{config.SITE_URL}{EXPORT_PFAD}/feeds/"
    out.mkdir(parents=True, exist_ok=True)
    for key, ids in areas.items():
        ganz = key == "gesamt"
        entries = []
        for pid in ids:
            p = cache[pid]
            for e in events(p):
                entries.append({**e, "link": site_link(home.get(pid, key) if ganz else key, p["reference"]),
                                "original": p["web"]})
        entries = sorted(entries, key=lambda e: (e["date"], e["id"]), reverse=True)[:FEED_LIMIT]
        name = GANZ_BONN if ganz else key.replace(":", "-")
        wo = f"ganz {config.STADT_NAME}" if ganz else names[key]
        (out / f"{name}.xml").write_text(_atom(
            f"{TAG}:feed/{name}", f"{config.SEITENNAME} – {wo}",
            f"Neue Vorlagen und Beratungsergebnisse: {wo}", f"{base}{name}.xml",
            site_link(f"{config.STADT}:ganz" if ganz else key), entries))
    vdir = out / "vorlagen"
    vdir.mkdir(parents=True, exist_ok=True)
    for pid, p in cache.items():
        if not has_paper_feed(p, since):
            continue
        area = home.get(pid, "gesamt")
        entries = [{**e, "link": site_link(area, p["reference"]), "original": p["web"]}
                   for e in events(p, with_followups=True)]
        name = slug(p["reference"])
        (vdir / f"{name}.xml").write_text(_atom(
            f"{TAG}:feed/vorlage/{name}", f"Vorlage {p['reference']}: {p['name']}",
            f"Verlauf der Vorlage {p['reference']}: Beratungen, Ergebnisse und Folgevorlagen",
            f"{base}vorlagen/{name}.xml", site_link(area, p["reference"]), entries))


def write_topic_feed(path, key, title, papers, home, page_url):
    """Feed einer Themenseite: letzte Ereignisse der Vorlagen aller Stränge."""
    entries = []
    for pid, p in papers:
        for e in events(p):
            entries.append({**e, "link": site_link(home.get(pid, "gesamt"), p["reference"]), "original": p["web"]})
    entries = sorted(entries, key=lambda e: (e["date"], e["id"]), reverse=True)[:FEED_LIMIT]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_atom(
        f"{TAG}:feed/thema/{key}", f"{config.SEITENNAME} – {title}",
        f"Neue Vorlagen und Beratungsergebnisse: {title} (Zuordnung abgeleitet)",
        f"{config.SITE_URL}{EXPORT_PFAD}/dossiers/{path.name}", page_url, entries))


# --- Sitzungskalender (iCalendar) --------------------------------------------------------------------

def _ics_text(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line):
    """Zeilen nach RFC 5545 auf 75 Oktette falten."""
    raw, out, limit = line.encode("utf-8"), [], 75
    while len(raw) > limit:  # Folgezeilen: Leerzeichen + 74 Oktette
        cut = limit
        while (raw[cut] & 0xC0) == 0x80:  # nicht innerhalb eines UTF-8-Zeichens trennen
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw, limit = raw[cut:], 74
    out.append(raw.decode("utf-8"))
    return "\r\n ".join(out)


def _utc(ts):
    return datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_calendar(path, meetings, today=None):
    """Sitzungen ab 30 Tage vor dem Datenstand; abgesagte mit STATUS:CANCELLED."""
    since = ((today or date.today()) - timedelta(days=30)).isoformat()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{config.SEITENNAME}//Sitzungskalender//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Sitzungen Rat\\, Ausschüsse und "
             f"Bezirksvertretungen {config.STADT_NAME}", "X-WR-TIMEZONE:Europe/Berlin"]
    for m in meetings:
        if m["date"] < since or not m.get("start") or len(m["start"]) <= 10:
            continue
        desc = [m["name"] or ""]
        desc.append(f"Tagesordnung: {m['web']}" if m.get("web") else "Tagesordnung noch nicht veröffentlicht.")
        if m.get("invitation"):
            desc.append(f"Einladung: {m['invitation']}")
        desc.append(f"Quelle: OParl-API der Stadt Köln; {config.NAMENSNENNUNG}")
        lines += ["BEGIN:VEVENT", f"UID:{m['source_object']}", f"DTSTAMP:{_utc(m['start'])}",
                  f"DTSTART:{_utc(m['start'])}"]
        if m.get("end") and m["end"][11:19] != "23:59:59":
            lines.append(f"DTEND:{_utc(m['end'])}")
        lines += [f"SUMMARY:{_ics_text(m['gremium'] + (' (abgesagt)' if m['cancelled'] else ''))}",
                  f"DESCRIPTION:{_ics_text(chr(10).join(desc))}",
                  "STATUS:CANCELLED" if m["cancelled"] else "STATUS:CONFIRMED"]
        if m.get("web"):
            lines.append(f"URL:{m['web']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(_ics_fold(x) for x in lines) + "\r\n", encoding="utf-8")


# --- Linked Open Data: GeoJSON und DCAT-AP -----------------------------------------------------------

def write_geojson(path, cache, sources):
    features = []
    for p in sorted(cache.values(), key=lambda p: (p["date"] or "", p["reference"]), reverse=True):
        for loc in p["locations"]:
            if loc["lon"] is None:
                continue
            features.append({"type": "Feature",
                             "geometry": {"type": "Point", "coordinates": [loc["lon"], loc["lat"]]},
                             "properties": {
                                 "reference": p["reference"], "name": p["name"], "paper_type": p["paper_type"],
                                 "date": p["date"], "stand": p["stand"], "amt": p["amt"],
                                 "place": loc["name"], "ortsteil": loc["ortsteil"],
                                 "stadtbezirk": loc["stadtbezirk"], "stage": loc["stage"],
                                 "method": loc["method"], "confidence": loc["confidence"],
                                 "evidence": loc["evidence"], "location_source": loc["source"],
                                 "web": p["web"], "source_object": p["source_object"]}})
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "meta": {"sources": sources, "note": "Ein Punkt je Vorlage und Ort: Straßenabschnitt, Stadtteil oder Stadtbezirk; "
                 "eine Hauskoordinate (Ebene 'adresse') nur bei Verwaltungsvorlagen und politischen Anträgen, nie bei "
                 "Anregungen und Beschwerden nach § 24 GO NRW. In Titeln von Vorlagen aus der Einwohnerschaft ist die "
                 "Hausnummer ausgeblendet, das Original verlinkt `web`. Ortsbezüge mit location_source 'osm' sind aus "
                 "OpenStreetMap abgeleitet (ODbL 1.0); übrige Felder dl-de/zero 2.0. " + config.NAMENSNENNUNG + "."},
        "features": features}, ensure_ascii=False, separators=(",", ":")))
    return len(features)


def _bbox_wkt():
    s, w, n, e = config.STADT_BBOX
    return f"POLYGON(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"


def write_dcat(path, data_start, modified, kurzfassungen=False):
    site, base = config.SITE_URL, f"{config.SITE_URL}data/export/"
    mt = "https://www.iana.org/assignments/media-types/"
    rights = ("Felder aus der OParl-API der Stadt Köln (Lizenz laut Katalog dl-de/zero 2.0, Klärung offen) und aus den "
              "Kölner Geodaten (dl-de/zero 2.0); " + config.NAMENSNENNUNG + ". Ortsbezüge aus OpenStreetMap, falls "
              "vorhanden, ODbL 1.0. Einzelheiten: " + f"{site}data/LICENSE-DATA.md")

    def dist(name, file, media, licence, desc):
        url = file if file.startswith("https://") else f"{base}{file}"
        return {"@id": url, "@type": "dcat:Distribution", "dct:title": {"@language": "de", "@value": name},
                "dct:description": {"@language": "de", "@value": desc}, "dcat:accessURL": {"@id": url},
                "dcat:downloadURL": {"@id": url}, "dcat:mediaType": {"@id": mt + media},
                "dct:license": {"@id": LICENCE[licence]}, "dct:rights": {"@type": "dct:RightsStatement", "rdfs:label": rights}}

    doc = {
        "@context": {"dcat": "http://www.w3.org/ns/dcat#", "dct": "http://purl.org/dc/terms/",
                     "foaf": "http://xmlns.com/foaf/0.1/", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                     "xsd": "http://www.w3.org/2001/XMLSchema#", "locn": "http://www.w3.org/ns/locn#"},
        "@id": f"{base}{config.STADT}/dcat.jsonld#dataset", "@type": "dcat:Dataset",
        "dct:title": {"@language": "de", "@value": f"{config.SEITENNAME} – Ratsvorlagen räumlich, zeitlich und nach Akteuren"},
        "dct:description": {"@language": "de", "@value": (
            "Vorlagen aus dem Ratsinformationssystem der Stadt Köln mit Ortsbezug "
            "(Stadtteil, Straße; Stufe A aus der OParl-API, Stufe B regelbasiert aus dem Titel), "
            "Prozessschritten mit Evidenzstatus, Beratungsfolge und Ergebnissen, federführendem Amt "
            "und abgeleiteten Einreichenden. Abgeleitete Angaben sind gekennzeichnet.")},
        "dcat:keyword": ["Ratsinformationssystem", "OParl", config.STADT_NAME, "Kommunalpolitik", "Vorlagen",
                         "Bezirksvertretung", "Stadtrat", "Bürgerbeteiligung"],
        "dcat:theme": {"@id": "http://publications.europa.eu/resource/authority/data-theme/GOVE"},
        "dct:language": {"@id": "http://publications.europa.eu/resource/authority/language/DEU"},
        "dct:accrualPeriodicity": {"@id": "http://publications.europa.eu/resource/authority/frequency/DAILY"},
        "dct:modified": {"@type": "xsd:date", "@value": modified},
        **({"dct:temporal": {"@type": "dct:PeriodOfTime", "dcat:startDate": {"@type": "xsd:date", "@value": data_start}}}
           if data_start else {}),   # Vorschau ohne Vorlagen: kein Zeitraum
        "dct:spatial": {"@type": "dct:Location", "rdfs:label": config.STADT_NAME,
                        "dcat:bbox": {"@type": "http://www.opengis.net/ont/geosparql#wktLiteral", "@value": _bbox_wkt()}},
        "dct:publisher": {"@type": "foaf:Agent", "foaf:name": config.SEITENNAME,
                          "foaf:homepage": {"@id": "https://github.com/daimpad/ratsatlas-koeln"}},
        "dct:source": [{"@id": config.OPARL_BODY}],
        "dcat:landingPage": {"@id": site},
        "dcat:distribution": [
            dist("Verortete Vorlagen (GeoJSON)", f"{config.STADT}/vorlagen.geojson", "application/geo+json", "dl-de-zero",
                 "Ein Punkt je Vorlage und Ort mit Stufe, Methode, Konfidenz und Fundstelle der Verortung."),
            dist("Datenpaket (Zip)", config.PAKET_URL, "application/zip", "dl-de-zero",
                 "Alle Exporte, Audit-Protokolle (TSV), Verifikation und Lizenzübersicht."),
            dist("Zeitleiste: Monatsaggregate (JSON)", f"{config.STADT}/zeit.json", "application/json", "dl-de-zero",
                 "Vorlagen je Monat, Gebiet und Vorlagenart; Sitzungen; Wahlperioden."),
            dist("Typische Wege je Vorlagenart (JSON)", f"{config.STADT}/prozesse.json", "application/json", "dl-de-zero",
                 "Häufigste Abfolgen von Beratungen und Ergebnissen je Vorlagenart."),
            dist("Sitzungskalender (iCalendar)", f"{config.STADT}/termine.ics", "text/calendar", "dl-de-zero",
                 "Sitzungen von Rat, Ausschüssen und Bezirksvertretungen mit Links zur Tagesordnung."),
            dist("Planregister Bebauungspläne (JSON)", f"{config.STADT}/plaene.json", "application/json", "dl-de-zero",
                 "Je Plannummer aus Vorlagentiteln: Vorlagen mit den im Titel genannten Verfahrensschritten nach BauGB "
                 "(abgeleitet); Geltungsbereiche folgen, sobald eine Bezugsquelle vorliegt."),
        ] + ([dist("KI-Kurzfassungen (TSV)", f"{config.STADT}/kurzfassungen.tsv", "text/tab-separated-values", "cc-by",
                   "Mit einem Sprachmodell aus dem Text der Hauptdokumente formulierte Kurzfassungen, abgeleitet und "
                   "gekennzeichnet; kein Zitat, Einzelheiten können ungenau sein. Maßgeblich ist das Original.")]
             if kurzfassungen else [])
          + ([dist("Kennzahlen je Stadtteil (JSON)", f"{config.STADT}/kontext.json", "application/json", "dl-de-by",
                   f"Kennzahlen je Stadtteil, Stadtbezirk und für ganz {config.STADT_NAME} zur Einordnung von Vorlagen: "
                   "Einwohner und Altersanteile und Nettokaltmiete (Zensus 2022, © Destatis), Bodenrichtwert Wohnbauland "
                   "(BORIS NRW), Haltestellen (VRS), Kitas und Schulen (Land NRW), Hitze (Klimaanalyse NRW), "
                   "Überschwemmungsgebiete (Land NRW); auf Stadtteile umgerechnet (abgeleitet), je Kennzahl mit Quelle, "
                   "Lizenz und Stand."),
              dist("Kartenebenen (JSON)", f"{config.STADT}/ebenen.json", "application/json", "dl-de-by",
                   "Verzeichnis der zuschaltbaren Kartenebenen aus offenen Daten der Stadt, des Landes und des Bundes mit "
                   "Quelle, Lizenz und Stand je Ebene; die Flächen liegen unter flaechen/ebene_*.json.")]
             if config.ZUSATZTHEMEN.get("kontext") and (config.ROOT / "data" / "kontext" / "STAND.json").exists() else []),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
