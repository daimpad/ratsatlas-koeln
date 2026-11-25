"""Abonnieren und Nachnutzen (Ratsatlas Köln): Atom-Feeds je Gebiet und je Vorlage, Sitzungskalender (iCalendar),
GeoJSON aller verorteten Vorlagen und eine Beschreibung des Datensatzes nach DCAT-AP (JSON-LD).

Alle Dateien ändern sich nur, wenn sich ihr Inhalt ändert (keine Erzeugungszeitpunkte), damit der
Branch deploy nicht täglich vollständig neu geschrieben wird. Ausnahme sind die Kalender (termine.ics, Themenkalender):
Seit der Entscheidung 21.11.2026 (3) (#47 (2)) trägt jeder Termin in DTSTAMP den Zeitpunkt des Aufbaus, wie RFC 5545 es
bei METHOD:PUBLISH vorsieht (_zeitstempel); ein Kalender ändert sich daher bei jedem Aufbau."""
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from . import config, strukturdaten_web
from .process import BERLIN, _ortszeit, local_day, local_time

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

def events(p, with_followups=False, federfuehrung_unbekannt=True):
    """Ereignisse einer Vorlage: neue Vorlage, Beratungen mit Ergebnis, auf Wunsch Folgevorlagen. Die Zusammenfassung
    der neuen Vorlage nennt die Federführung; ist sie unbekannt (amt leer), steht dort „federführend: unbekannt“, mit
    federfuehrung_unbekannt=False nichts (Themenfeed, Entscheidung 25.11.2026 (6); die übrigen Feeds folgen später)."""
    out = []
    if p["date"]:
        fuehrung = (f" · federführend: {p['amt'] or 'unbekannt'}" if p["amt"] or federfuehrung_unbekannt else "")
        out.append({"date": p["date"], "id": f"{p['source_object']}#vorlage",
                    "title": f"Neue Vorlage {p['reference']}: {p['name']}",
                    "summary": f"{p['paper_type']}{fuehrung} · Stand: {p['stand']}"
                               + (f" · KI-Kurzfassung (abgeleitet, Einzelheiten können ungenau sein): {p['kurzfassung']['text']}"
                                  if p.get("kurzfassung") else "")})
    vergeben = set()
    for s in p["steps"]:
        if s["typ"] in ("beratung", "entscheidung") and s.get("result") and s.get("date"):
            # ID aus Datum und Gremium, nicht aus der Position: eine neue Folgevorlage oder Beratung verschob sonst
            # die Nummern, und Feed-Reader zeigten Einträge doppelt (Code-Prüfung 23.10.2026). Berät dasselbe Gremium
            # die Vorlage am selben Tag mehrmals (seit der Entscheidung 17.11.2026 (14) je Eintrag eine Station, etwa
            # dieselbe Beratung unter zwei TOPs), trägt ab der zweiten Station die ID die TOP-Nummer (fehlt sie, eine
            # laufende Nummer); die erste behält ihre ID, und Feed-Reader fassen die Einträge nicht zusammen (Prüfung bs)
            basis = f"{p['source_object']}#beratung-{s['date']}-{quote(s['label'], safe='')}"
            eid = basis
            if eid in vergeben and s.get("number"):
                eid = f"{basis}-top-{quote(str(s['number']), safe='')}"
            n = 1
            while eid in vergeben:
                n += 1
                eid = f"{basis}-{n}"
            vergeben.add(eid)
            out.append({"date": s["date"], "id": eid,
                        "title": f"{s['label']}: „{s['result']}“ – {p['reference']} {p['name']}",
                        "summary": f"{s.get('role') or 'Beratung'} am {s['date']}; Ergebnis laut Ratsinformationssystem. "
                                   f"Stand der Vorlage: {p['stand']}"})
        if with_followups and s["typ"] == "folgevorlage" and s.get("date"):
            out.append({"date": s["date"], "id": f"{p['source_object']}#folge-{quote(s['reference'], safe='')}",
                        "title": f"{s['label']} {s['reference']}: {s['title']}",
                        "summary": f"Folgevorlage zu {p['reference']}"})
    return out


# Zeichen, die XML 1.0 nicht erlaubt (alles außer Tab, Zeilenende, U+0020–U+D7FF, U+E000–U+FFFD und
# U+10000–U+10FFFF): Steuerzeichen, einzelne Ersatzzeichen (U+D800–U+DFFF) sowie U+FFFE und U+FFFF aus der Quelle
# machten den ganzen Feed ungültig und damit für check ungeprüft (Offen (6) der Nachprüfung der dritten Korrektur:
# vorher nur die Steuerzeichen). _atom entfernt sie, check._feeds vergleicht Texte in derselben Form (xml_text)
XML_UNGUELTIG = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def xml_text(text):
    """Text ohne Zeichen, die XML 1.0 nicht erlaubt (XML_UNGUELTIG); eine Regel für die Feeds und check._feeds."""
    return XML_UNGUELTIG.sub("", text)


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
    return xml_text("\n".join(x for x in parts if x)) + "\n"


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
    """Feed einer Themenseite: letzte Ereignisse der Vorlagen aller Stränge; ohne „federführend: unbekannt“, wo die
    Federführung fehlt (events, federfuehrung_unbekannt=False)."""
    entries = []
    for pid, p in papers:
        for e in events(p, federfuehrung_unbekannt=False):
            entries.append({**e, "link": site_link(home.get(pid, "gesamt"), p["reference"]), "original": p["web"]})
    entries = sorted(entries, key=lambda e: (e["date"], e["id"]), reverse=True)[:FEED_LIMIT]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_atom(
        f"{TAG}:feed/thema/{key}", f"{config.SEITENNAME} – {title}",
        f"Neue Vorlagen und Beratungsergebnisse: {title} (Zuordnung abgeleitet)",
        f"{config.SITE_URL}{EXPORT_PFAD}/dossiers/{path.name}", page_url, entries))


# --- Sitzungskalender (iCalendar) --------------------------------------------------------------------

# Zusatz am Ende der Zusammenfassung (SUMMARY) eines abgesagten Termins je Grund (export.absage; Entscheidung 21.11.2026
# (1) (c) (9)): „ (abgesagt)“ bei OParl `cancelled` wie bisher, „ (laut Sitzungsnamen abgesagt)“ beim Hinweis aus dem
# Namen. check._sitzungen nimmt ihn vor der Prüfung des Gremiums ab, check.absagen_kalender prüft ihn
ZUSATZ_ABSAGE = {"oparl": " (abgesagt)", "name": " (laut Sitzungsnamen abgesagt)"}


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


def _koeln(ts):
    """Zeitpunkt mit Zeitzone in Kölner Ortszeit (process._ortszeit); ohne Zeitzone gilt Kölner Ortszeit."""
    dt = _ortszeit(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=BERLIN)


def _utc(ts):
    """Zeitpunkt in UTC für iCalendar („…Z“). Ohne Zeitzone gilt Kölner Ortszeit wie in process.local_day, nicht die
    Zeitzone des Rechners, auf dem der Aufbau läuft (in GitHub Actions UTC; Entscheidung 19.11.2026 (1) (D))."""
    return _koeln(ts).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ganztaegig(start):
    """Sitzung ohne Uhrzeit: nur ein Datum oder 00:00 Uhr in Köln, dieselbe Regel wie `time` in zeit.json
    (export._meetings; Entscheidung 19.11.2026 (2) (a))."""
    return local_time(start) in (None, "00:00")


def _ende(start, end):
    """DTEND in UTC oder None (Entscheidung 19.11.2026 (2) (a)): kein Ende bei einem Ende ohne Uhrzeit (nur Datum), beim
    Platzhalter 23:59:59 Uhr in Kölner Ortszeit und bei einem Ende, das nicht nach dem Beginn liegt."""
    if not end or len(end) <= 10:
        return None
    ende = _koeln(end)
    if ende.strftime("%H:%M:%S") == "23:59:59" or ende <= _koeln(start):
        return None
    return _utc(end)


def _zeitstempel(aufbau=None):
    """DTSTAMP aller Termine einer Datei (Entscheidung 21.11.2026 (3), #47 (2)): der Zeitpunkt des Aufbaus in UTC auf
    die Sekunde („JJJJMMTTTHHMMSSZ“). RFC 5545 (3.8.7.2) nennt bei einem Kalender mit METHOD dort den Zeitpunkt, zu dem
    das Objekt erstellt wurde, und verlangt UTC. Ohne Angabe jetzt; ein übergebener Zeitpunkt (Tests) braucht eine
    Zeitzone, sonst hinge das Ergebnis von der Zeitzone des Rechners ab."""
    aufbau = datetime.now(timezone.utc) if aufbau is None else aufbau
    if aufbau.tzinfo is None:
        raise ValueError("Zeitpunkt des Aufbaus ohne Zeitzone")
    return aufbau.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_calendar(path, meetings, today=None, aufbau=None):
    """Sitzungen ab 30 Tagen vor `today` (ohne Angabe der Tag des Aufbaus, so für termine.ics; die Themenkalender
    übergeben den Kölner Tag des Datenstands); abgesagte mit STATUS:CANCELLED und dem Zusatz ihres Grundes in der
    Zusammenfassung (ZUSATZ_ABSAGE), sonst STATUS:CONFIRMED. Als abgesagt gilt eine Sitzung nach export.absage: OParl
    `cancelled` oder, seit der Entscheidung 21.11.2026 (1) (c) (9), Hinweis „abgesagt“ aus dem Namen (vorher nur
    `cancelled`); der Hinweis „verschoben“ ändert weder STATUS noch Zusammenfassung (offen beim Auftraggeber), der
    Name mit dem Hinweis steht ohnehin in der Beschreibung. Eine Sitzung ohne Uhrzeit (_ganztaegig) steht als
    ganztägiger Termin am Kölner Kalendertag (process.local_day) darin, ohne DTEND: Nach RFC 5545 (3.6.1) dauert ein
    Termin mit einem Datum in DTSTART ohne DTEND und DURATION einen Tag; so steht kein Ende im Kalender, das die Quelle
    nicht nennt (Entscheidung 19.11.2026 (2) (a)). DTSTAMP ist bei allen Terminen der Datei derselbe Zeitpunkt des
    Aufbaus in UTC (_zeitstempel; `aufbau` für Tests, ohne Angabe jetzt), auch bei ganztägigen Terminen; bis zum
    22.11.2026 stand dort der Beginn der Sitzung in UTC (Entscheidung 21.11.2026 (3), #47 (2)). SEQUENCE und
    LAST-MODIFIED fehlen weiter (nicht entschieden). Das Log nennt die Zahl der Termine, der ganztägigen und der
    abgesagten je Grund, nur Zahlen."""
    from .export import absage   # export importiert dieses Modul; hier erst beim Aufruf
    since = ((today or date.today()) - timedelta(days=30)).isoformat()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{config.SEITENNAME}//Sitzungskalender//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Sitzungen Rat\\, Ausschüsse und "
             f"Bezirksvertretungen {config.STADT_NAME}", "X-WR-TIMEZONE:Europe/Berlin"]
    stempel = _zeitstempel(aufbau)
    termine = ganztaegig = 0
    abgesagt = dict.fromkeys(ZUSATZ_ABSAGE, 0)
    for m in meetings:
        if m["date"] < since or not m.get("start"):
            continue
        desc = [m["name"] or ""]
        desc.append(f"Tagesordnung: {m['web']}" if m.get("web") else "Tagesordnung noch nicht veröffentlicht.")
        if m.get("invitation"):
            desc.append(f"Einladung: {m['invitation']}")
        desc.append(f"Quelle: OParl-API der Stadt Köln; {config.NAMENSNENNUNG}")
        # DTSTAMP: derselbe Zeitpunkt des Aufbaus in UTC für alle Termine der Datei (RFC 5545 verlangt dort DATE-TIME in
        # UTC), auch bei einem ganztägigen Termin
        lines += ["BEGIN:VEVENT", f"UID:{m['source_object']}", f"DTSTAMP:{stempel}"]
        termine += 1
        if _ganztaegig(m["start"]):
            ganztaegig += 1
            lines.append(f"DTSTART;VALUE=DATE:{local_day(m['start']).replace('-', '')}")
        else:
            lines.append(f"DTSTART:{_utc(m['start'])}")
            ende = _ende(m["start"], m.get("end"))
            if ende:
                lines.append(f"DTEND:{ende}")
        grund = absage(m)
        if grund:
            abgesagt[grund] += 1
        lines += [f"SUMMARY:{_ics_text(m['gremium'] + ZUSATZ_ABSAGE.get(grund, ''))}",
                  f"DESCRIPTION:{_ics_text(chr(10).join(desc))}",
                  "STATUS:CANCELLED" if grund else "STATUS:CONFIRMED"]
        if m.get("web"):
            lines.append(f"URL:{m['web']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(_ics_fold(x) for x in lines) + "\r\n", encoding="utf-8")
    print(f"{path.name}: {termine} Termine, davon ganztägig {ganztaegig}, abgesagt laut OParl {abgesagt['oparl']}, "
          f"abgesagt laut Sitzungsnamen {abgesagt['name']}")


def ics_sitzungsname(beschreibung):
    """Sitzungsname aus der Beschreibung eines Termins von write_calendar (DESCRIPTION, Text zurückgewandelt): alles vor
    der letzten Zeile, die mit „Tagesordnung“ beginnt. write_calendar schreibt den Namen samt Zeilenumbrüchen an den
    Anfang und direkt dahinter immer „Tagesordnung: …“ oder „Tagesordnung noch nicht veröffentlicht.“, danach nur
    Einladung und Quelle. check._sitzungen prüft so den ganzen Namen, den export maskiert (Nachprüfung der Entscheidung
    19.11.2026 (3): vorher nur die erste Zeile; bei einem Namen mit Zeilenumbruch meldete check einen Befund, den die
    Maske zu Recht nicht kürzt, etwa „17“ am Ende der ersten und „Uhr“ auf der zweiten Zeile, und eine Hausnummer auf
    der zweiten Zeile blieb ungeprüft). Ohne eine solche Zeile die ganze Beschreibung."""
    return (beschreibung or "").rsplit("\nTagesordnung", 1)[0]


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
                 "eine Hauskoordinate (Ebene 'adresse') nur bei Verwaltungsvorlagen sowie politischen Anträgen und Anfragen, nie bei "
                 "Anregungen und Beschwerden nach § 24 GO NRW oder bei leerer oder nicht erkennbarer Vorlagenart. In "
                 "Titeln von Vorlagen aus der Einwohnerschaft ist die Hausnummer ausgeblendet, das Original verlinkt "
                 "`web`. Ortsbezüge mit location_source 'osm' sind aus "
                 "OpenStreetMap abgeleitet (ODbL 1.0), mit location_source 'bplan-koeln' aus den Bebauungsplänen, Lizenz "
                 + config.SOURCES[config.QUELLE_BPLAN]["license"] + "; übrige Felder dl-de/zero 2.0. "
                 + config.NAMENSNENNUNG + "."},
        "features": features}, ensure_ascii=False, separators=(",", ":")))
    return len(features)


def _bbox_wkt():
    s, w, n, e = config.STADT_BBOX
    return f"POLYGON(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"


# Lizenz und Rechtehinweis je DCAT-Verteilung aus den Teilen, die sie enthält (Runde 19b). DCAT-AP.de kennt je
# Verteilung eine Lizenz; enthält eine Datei Daten unter mehreren Lizenzen, steht dort die strengste (RANG). dl-de/zero
# 2.0 erlaubt jede Nutzung ohne Bedingung, also auch die Weitergabe zusammen mit Daten unter dl-de/by 2.0; wer die
# Datei als Ganze nach dl-de/by 2.0 nutzt (mit Namensnennung), hält die Bedingungen aller Teile ein. dct:rights nennt
# Lizenz und Namensnennung jedes Teils: aus config.SOURCES, für Kennzahlen und Kartenebenen aus deren Ständen, für die
# Strukturdaten (nur mit Freigabe) aus pipeline/strukturdaten_web.py. CC0 (Wegweiser Kommune) gilt wie dl-de/zero ohne
# Bedingung und tritt hinter jede andere Lizenz zurück.
RANG = ("odbl", "dl-de-by", "dl-de-zero", "cc0")
LIZENZ_MUSTER = (("odbl", re.compile(r"ODbL")), ("dl-de-by", re.compile(r"dl-de/by")),
                 ("dl-de-zero", re.compile(r"dl-de/zero")), ("cc0", re.compile(r"\bCC0\b")))
TEIL_NAME = {config.QUELLE_OPARL: "Ratsinformationssystem der Stadt Köln (OParl-API)",
             config.QUELLE_GEO: "Stadtteile und Stadtbezirke", config.QUELLE_STRASSEN: "Straßen",
             config.QUELLE_ADRESSEN: "Adressen", config.QUELLE_BPLAN: "Bebauungspläne",
             "osm": "Ortsbezüge aus OpenStreetMap"}
RIS_TEILE = (config.QUELLE_OPARL, config.QUELLE_GEO, config.QUELLE_STRASSEN, config.QUELLE_ADRESSEN)


def _teil(name):
    """(Bezeichnung, Lizenz mit Namensnennung) einer Quelle aus config.SOURCES; bei OpenStreetMap ohne den Zusatz zum
    Kartenhintergrund, denn hier geht es um Ortsbezüge; ohne internen Verweis auf CLAUDE.md (config.lizenz_oeffentlich)."""
    lizenz = config.lizenz_oeffentlich(config.SOURCES[name]["license"])
    return TEIL_NAME[name], (lizenz.split(" (Kartenhintergrund")[0] if name == "osm" else lizenz)


def lizenz_der_teile(teile):
    """Schlüssel in LICENCE für eine Verteilung aus ihren Teilen [(Bezeichnung, Lizenztext)]: die strengste. Ein Teil
    ohne bekannte Lizenz bricht ab, statt still als dl-de/zero zu gelten."""
    if not teile:
        raise ValueError("DCAT: Verteilung ohne Teile")
    stufen = set()
    for name, text in teile:
        treffer = [k for k, m in LIZENZ_MUSTER if m.search(text)]
        if not treffer:
            raise ValueError(f"DCAT: Lizenz von „{name}“ nicht erkannt: {text}")
        stufen.add(min(treffer, key=RANG.index))
    return min(stufen, key=RANG.index)


def _rechte(teile, ohne=()):
    """Rechtehinweis: je Lizenz die Teile, die darunter stehen (gleiche Angaben zusammengefasst, getrennt durch „ · “,
    weil Bezeichnungen Kommas enthalten), dann die Teile ohne geklärte Lizenz (`ohne`, TEILE_OHNE_LIZENZ) mit dem
    Vermerk, dass die Lizenzangabe der Verteilung für sie nicht gilt, zuletzt der Verweis auf die Lizenzübersicht je
    Datei."""
    gruppen = {}
    for name, text in teile:
        gruppen.setdefault(text, []).append(name)
    ohne_text = ("; ohne geklärte Lizenz (die Lizenzangabe dieser Verteilung gilt für diese Teile nicht): "
                 + "; ".join(f"{name}: {text}" for name, text in ohne)) if ohne else ""
    return ("; ".join(f"{' · '.join(dict.fromkeys(namen))}: {text}" for text, namen in gruppen.items()) + ohne_text
            + f". Lizenzen je Datei: {config.SITE_URL}data/LICENSE-DATA.md")


# Teile ohne geklärte Lizenz (Nachprüfung 4a): Sie bestimmen die Lizenz einer Verteilung nicht
# (lizenz_der_teile verlangt je Teil eine erkannte Lizenz), stehen aber in ihrem Rechtehinweis (_rechte). Die
# Zuständigkeitsordnung liefert nur die Paragrafen der Ausschüsse in gremien.json; der Geschäfts- und
# Dezernatsverteilungsplan die Zuordnung der Federführung (responsibility[].aemtertabelle in den Gebietsdateien,
# audit_federfuehrung.tsv) und aemter.json, alle im Datenpaket. aemter.json selbst steht nicht im Katalog (write_dcat).
def _teil_zustaendigkeitsordnung():
    """(Bezeichnung, Angabe) der Zuständigkeitsordnung (ausschuesse.QUELLE) für den Rechtehinweis."""
    from . import ausschuesse
    titel = ausschuesse.QUELLE["titel"]
    return (f"{titel} (nur Paragrafen der Ausschüsse)",
            "Lizenz nicht geklärt; übernommen sind nur die Paragrafennummern, zugeordnet über den Namen der "
            f"Organisation in der OParl-API, kein Text der Satzung; Namensnennung: {titel}")


def _teil_plan():
    """(Bezeichnung, Angabe) des jüngsten Geschäfts- und Dezernatsverteilungsplans der Ämtertabelle für den
    Rechtehinweis; ohne Plan in der Tabelle None."""
    from . import aemter
    if aemter.tabelle().neuester() is None:
        return None
    return (f"{aemter.TITEL} ({aemter.quellenangabe()})",
            f"{aemter.LIZENZ_AUFBAU}; Quellenangabe: {aemter.namensnennung()}")


def _kontext_teile():
    """Quellen der Kennzahlen wie in kontext.json (meta.quellen): Titel und Lizenz aus den Ständen in data/kontext/; mit
    Freigabe „strukturdaten“ dazu der Statistische Datenkatalog Köln (Einwohnerzahl und Altersanteile, Option b)."""
    from . import kontext
    teile = [(q.get("titel") or k, q.get("lizenz") or "") for k, q in sorted(kontext.quellen_stand().items())]
    if kontext.strukturdaten_an():
        q = kontext.strukturdaten_quelle()
        teile.append((q["titel"], q["lizenz"]))
    return teile


def _ebenen_teile():
    """Quellen der Kartenebenen wie in ebenen.json (Schritt `ebenen` läuft, sobald data/ebenen/STAND.json da ist): nur
    Ebenen, deren Datei unter data/ebenen/ liegt."""
    from . import ebenen
    if not ebenen.STAND.exists():
        return []
    return [(q["quelle"], q["lizenz"]) for k, q in ebenen.QUELLEN.items() if (ebenen.EBENEN / f"{k}.geojson").exists()]


def ortsquellen(cache):
    """location_source der Punkte, die write_geojson schreibt (nur Orte mit Koordinate)."""
    return {loc["source"] for p in cache.values() for loc in p["locations"] if loc["lon"] is not None}


def _ortsquellen(ordner):
    """Ohne Angabe von export.py: location_source der Punkte in vorlagen.geojson neben dcat.jsonld. Fehlt die Datei,
    gelten die Bebauungspläne als enthalten, sobald es sie gibt (vorsichtig: dann dl-de/by 2.0)."""
    datei = Path(ordner) / "vorlagen.geojson"
    if not datei.exists():
        return {config.QUELLE_BPLAN} if config.BPLAN.exists() else set()
    return {f["properties"].get("location_source") for f in json.loads(datei.read_text(encoding="utf-8"))["features"]}


def write_dcat(path, data_start, modified, kurzfassungen=False, orte=None):
    """DCAT-Beschreibung; orte: location_source der Punkte in vorlagen.geojson (ortsquellen), sonst aus der Datei."""
    site, base = config.SITE_URL, f"{config.SITE_URL}data/export/"
    # zeit.json schreibt export.py nur mit Vorlagen (nicht in der Vorschau): nur aufführen, was daneben liegt
    zeit = (Path(path).parent / "zeit.json").exists()
    # gremien.json (Freigabe „gremien“, pipeline/gremien.py) ebenso nur, wenn die Datei daneben liegt. aemter.json steht
    # nicht im Katalog: Der Geschäfts- und Dezernatsverteilungsplan nennt keine Lizenz, DCAT verlangt eine je Verteilung
    # (lizenz_der_teile); die Datei liegt im Datenpaket, ihre Lizenzangabe in LICENSE-DATA.md, der Plan im
    # Rechtehinweis des Pakets (Teile ohne geklärte Lizenz, _teil_plan)
    gremien = (Path(path).parent / "gremien.json").exists()
    mt = "https://www.iana.org/assignments/media-types/"
    bplan = config.BPLAN.exists()
    kontext_an = config.ZUSATZTHEMEN.get("kontext") and (config.ROOT / "data" / "kontext" / "STAND.json").exists()
    orte = _ortsquellen(Path(path).parent) if orte is None else set(orte)
    ris = [_teil(n) for n in RIS_TEILE]
    teile = {
        "vorlagen": ris + [_teil(n) for n in (config.QUELLE_BPLAN, "osm") if n in orte],
        "zeit": [_teil(config.QUELLE_OPARL), _teil(config.QUELLE_GEO)],
        "oparl": [_teil(config.QUELLE_OPARL)],
        # plaene.json entsteht nach dcat.jsonld: Inkrafttreten und Link zum Plan stammen aus den Bebauungsplänen, sobald
        # es sie gibt
        "plaene": [_teil(config.QUELLE_OPARL)] + ([_teil(config.QUELLE_BPLAN)] if bplan else []),
        "kontext": ([_teil(config.QUELLE_GEO)] + _kontext_teile()) if kontext_an else [],
        "ebenen": _ebenen_teile(),
    }
    # Datenpaket: alle Exporte, Audits und data/geo (pipeline/paket.py), dazu Kennzahlen (wenn freigegeben) und Ebenen;
    # mit Freigabe „strukturdaten“ der Datenvertrag Strukturdaten (pipeline/strukturdaten_web.py)
    struktur = strukturdaten_web.lizenzteile() if strukturdaten_web.an() else []
    teile["paket"] = list(dict.fromkeys(ris + [_teil(n) for n in ("osm",) if n in orte]
                                        + ([_teil(config.QUELLE_BPLAN)] if bplan or config.QUELLE_BPLAN in orte else [])
                                        + teile["kontext"] + teile["ebenen"] + struktur))
    # gremien.json: Daten des Ratsinformationssystems, dazu die Paragrafen der Zuständigkeitsordnung (ohne geklärte
    # Lizenz). Teile ohne geklärte Lizenz je Verteilung: im Datenpaket der Plan (immer, wenn die Ämtertabelle einen
    # Plan hat: Zuordnung der Federführung in den Gebietsdateien) und mit gremien.json die Zuständigkeitsordnung
    teile["gremien"] = [_teil(config.QUELLE_OPARL)]
    plan = _teil_plan()
    ohne_lizenz = {"gremien": [_teil_zustaendigkeitsordnung()],
                   "paket": ([plan] if plan else []) + ([_teil_zustaendigkeitsordnung()] if gremien else [])}

    # Kennzahlen: mit Freigabe „strukturdaten“ Einwohnerzahl und Altersanteile aus der Stadtstatistik (Option b,
    # pipeline/kontext.py), sonst wie bisher aus dem Zensus
    kontext_text = (f"Kennzahlen je Stadtteil, Stadtbezirk und für ganz {config.STADT_NAME} zur Einordnung von Vorlagen: "
                    + ("Einwohner (Hauptwohnsitz) und Anteile unter 18 und ab 65 Jahren aus dem Statistischen "
                       "Datenkatalog Köln (Stadt Köln, Amt für Stadtentwicklung und Statistik; Werte der Stadt je Gebiet, "
                       "Altersanteile abgeleitet), Nettokaltmiete (Zensus 2022, © Destatis), Bodenrichtwert Wohnbauland "
                       "(BORIS NRW), Haltestellen (VRS), Kitas und Schulen (Land NRW), Hitze (Klimaanalyse NRW), "
                       "Überschwemmungsgebiete (Land NRW); diese übrigen auf Stadtteile umgerechnet (abgeleitet), je "
                       "Kennzahl mit Quelle, Lizenz und Stand." if strukturdaten_web.an() else
                       "Einwohner und Altersanteile und Nettokaltmiete (Zensus 2022, © Destatis), Bodenrichtwert "
                       "Wohnbauland (BORIS NRW), Haltestellen (VRS), Kitas und Schulen (Land NRW), Hitze (Klimaanalyse "
                       "NRW), Überschwemmungsgebiete (Land NRW); auf Stadtteile umgerechnet (abgeleitet), je Kennzahl mit "
                       "Quelle, Lizenz und Stand."))

    def dist(name, file, media, teil, desc, licence=None):
        url = file if file.startswith("https://") else f"{base}{file}"
        return {"@id": url, "@type": "dcat:Distribution", "dct:title": {"@language": "de", "@value": name},
                "dct:description": {"@language": "de", "@value": desc}, "dcat:accessURL": {"@id": url},
                "dcat:downloadURL": {"@id": url}, "dcat:mediaType": {"@id": mt + media},
                "dct:license": {"@id": LICENCE[licence or lizenz_der_teile(teile[teil])]},
                "dct:rights": {"@type": "dct:RightsStatement",
                               "rdfs:label": _rechte(teile[teil], ohne_lizenz.get(teil, ()))}}

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
            "(Dezernat und Bezeichnung, wo eindeutig, abgeleitet aus dem Geschäfts- und Dezernatsverteilungsplan der "
            "Stadt Köln) und abgeleiteten Einreichenden. Abgeleitete Angaben sind gekennzeichnet.")},
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
            dist("Verortete Vorlagen (GeoJSON)", f"{config.STADT}/vorlagen.geojson", "application/geo+json", "vorlagen",
                 "Ein Punkt je Vorlage und Ort mit Stufe, Methode, Konfidenz und Fundstelle der Verortung."),
            dist("Datenpaket (Zip)", config.PAKET_URL, "application/zip", "paket",
                 "Exporte (ohne Feeds), Prüfprotokolle und Stichproben (TSV, nur in diesem Paket, nicht als einzelne "
                 "Dateien auf der Seite), Abrufstatistik, abgeleitete Geodaten, Berichte der Projektphasen und "
                 "Lizenzübersicht."
                 + (" Dazu die Strukturdaten im Datenvertrag „Strukturdaten“ (Statistischer Datenkatalog Köln, "
                    "Statistische Quartiere, Vergleichswerte des Wegweisers Kommune) mit Prüfprotokollen; die Anteile "
                    "unter 18 und ab 65 Jahren sind vom Ratsatlas berechnet (abgeleitet)." if struktur else "")),
        ] + ([dist("Zeitleiste: Monatsaggregate (JSON)", f"{config.STADT}/zeit.json", "application/json", "zeit",
                   "Vorlagen je Monat, Gebiet und Vorlagenart; Sitzungen; Wahlperioden.")] if zeit else []) + [
            dist("Typische Wege je Vorlagenart (JSON)", f"{config.STADT}/prozesse.json", "application/json", "oparl",
                 "Häufigste Abfolgen von Beratungen und Ergebnissen je Vorlagenart."),
        ] + ([dist("Gremien (JSON)", f"{config.STADT}/gremien.json", "application/json", "gremien",
                   "Rat, Ausschüsse, Bezirksvertretungen und übrige Gremien ohne Fraktionen und Gruppen und ohne "
                   "Besetzung: Gruppe, Paragraf der Zuständigkeitsordnung (nur Nummer, bei eindeutigem Treffer des "
                   "Namens), Stadtbezirk der Bezirksvertretung, Sitzungen und Vorlagen in 12 Monaten, nächste Sitzung und, "
                   "wenn diese am Tag des Datenstands liegt, die folgende Sitzung (abgeleitet).")] if gremien else []) + [
            dist("Sitzungskalender (iCalendar)", f"{config.STADT}/termine.ics", "text/calendar", "oparl",
                 "Sitzungen von Rat, Ausschüssen und Bezirksvertretungen mit Links zur Tagesordnung."),
            dist("Planregister Bebauungspläne (JSON)", f"{config.STADT}/plaene.json", "application/json", "plaene",
                 "Je Plannummer aus Vorlagentiteln: Vorlagen mit den im Titel genannten Verfahrensschritten nach BauGB "
                 "(abgeleitet)" + ("; für rechtsverbindliche Pläne Inkrafttreten und Link zum Plan aus der Schnittstelle "
                                   "„Bauleitplanung in NRW“ (MHKBD NRW / IT.NRW), die Geltungsbereiche in "
                                   "flaechen/bebauungsplaene.json." if bplan else
                                   "; ohne Geltungsbereiche und Inkrafttreten (keine Bebauungspläne im Datenstand).")),
        ] + ([dist("KI-Kurzfassungen (TSV)", f"{config.STADT}/kurzfassungen.tsv", "text/tab-separated-values", "oparl",
                   "Mit einem Sprachmodell aus dem Text der Hauptdokumente formulierte Kurzfassungen, abgeleitet und "
                   "gekennzeichnet; kein Zitat, Einzelheiten können ungenau sein. Maßgeblich ist das Original.",
                   licence="cc-by")]
             if kurzfassungen else [])
          + ([dist("Kennzahlen je Stadtteil (JSON)", f"{config.STADT}/kontext.json", "application/json", "kontext",
                   kontext_text)] if kontext_an else [])
          + ([dist("Kartenebenen (JSON)", f"{config.STADT}/ebenen.json", "application/json", "ebenen",
                   "Verzeichnis der zuschaltbaren Kartenebenen aus offenen Daten der Stadt und des Landes mit Quelle, "
                   "Lizenz und Stand je Ebene; die Flächen liegen unter flaechen/ebene_*.json.")]
             if kontext_an and teile["ebenen"] else []),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
