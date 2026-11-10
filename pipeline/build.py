"""Normalisierung der Rohdaten in eine SQLite-Datenbank (data/build/allris.sqlite)."""
import csv
import json
import re
import random
import sqlite3
from collections import Counter

from . import actors, config
from .geo import Ortsteile
from .geocode import (ANDERE_FORM, AUSSCHLUSS, WEG, Gazetteer, erkannte_arten, hausnummer_punkt_erlaubt,
                      nicht_erkannte_arten, plan_numbers, punkt_ausschluss, sperrmenge, vorlagenart_bezeichnung)
from .plans import Plans, plan_locations
from . import volltext
from .objekte import Objekte

SCHEMA = """
CREATE TABLE source (
  name TEXT PRIMARY KEY, url TEXT, license TEXT, retrieved_at TEXT);
CREATE TABLE organization (
  id TEXT PRIMARY KEY, name TEXT, short_name TEXT, org_type TEXT, classification TEXT,
  label TEXT, start_date TEXT, end_date TEXT, web TEXT, source TEXT);
CREATE TABLE paper (
  id TEXT PRIMARY KEY, reference TEXT, name TEXT, paper_type TEXT, date TEXT,
  under_direction_of TEXT REFERENCES organization, web TEXT,
  main_file_url TEXT, main_file_name TEXT, source TEXT);
CREATE TABLE paper_relation (
  parent_id TEXT, child_id TEXT, source TEXT, PRIMARY KEY (parent_id, child_id));
-- relatedPaper (wie geliefert, auch von ausgelassenen Vorlagen): nur für den Datenschutz, in beiden Richtungen eine
-- Beziehung wie paper_relation (geocode.sperrmenge in build und check.erlaubnis); Export, maske.aus_db und
-- volltext.einwohner_kette lesen nur paper_relation
CREATE TABLE paper_related (
  paper_id TEXT, related_id TEXT, source TEXT, PRIMARY KEY (paper_id, related_id));
CREATE TABLE meeting (
  id TEXT PRIMARY KEY, name TEXT, start_date TEXT, cancelled INTEGER, source TEXT);
CREATE TABLE agenda_item (
  id TEXT PRIMARY KEY, meeting_id TEXT REFERENCES meeting, number TEXT, name TEXT,
  result TEXT, public INTEGER, source TEXT);
CREATE TABLE consultation (
  id TEXT PRIMARY KEY, paper_id TEXT REFERENCES paper, position INTEGER,
  organization_id TEXT REFERENCES organization, role TEXT, authoritative INTEGER,
  meeting_id TEXT REFERENCES meeting, agenda_item_id TEXT REFERENCES agenda_item,
  source TEXT, link_source TEXT);
CREATE TABLE location (
  id TEXT PRIMARY KEY, street TEXT, postal_code TEXT, sub_locality TEXT, description TEXT,
  lon REAL, lat REAL, ortsteil TEXT, ortsteil_nr INTEGER, stadtbezirk TEXT,
  level TEXT /* adresse | strasse | ortsteil | stadtbezirk | objekt | bebauungsplan */, source TEXT);
CREATE TABLE paper_location (
  paper_id TEXT REFERENCES paper, location_id TEXT REFERENCES location, stage TEXT,
  method TEXT, confidence TEXT, evidence TEXT, source_object TEXT,
  PRIMARY KEY (paper_id, location_id, method));
CREATE TABLE paper_plan (
  paper_id TEXT REFERENCES paper, plan_nr TEXT, evidence TEXT, match TEXT,
  PRIMARY KEY (paper_id, plan_nr));
-- Ortsbezüge aus dem Titel, die einem eindeutig zugeordneten Bebauungsplan weichen (Vorrang B3, Audit)
CREATE TABLE plan_precedence (
  paper_id TEXT REFERENCES paper, location_id TEXT REFERENCES location, method TEXT, evidence TEXT);
CREATE TABLE paper_originator (
  paper_id TEXT REFERENCES paper, actor TEXT, actor_type TEXT,
  organization_id TEXT REFERENCES organization, method TEXT, evidence TEXT, derived INTEGER);
CREATE TABLE paper_responsibility (
  paper_id TEXT REFERENCES paper, organization_id TEXT REFERENCES organization, kind TEXT,
  method TEXT, evidence TEXT, derived INTEGER);
-- Vorlagen, die der Aufbau auslässt (ohne Drucksachennummer, einlesen()); Zählung in der Ausgabe von check; für den
-- Datenschutz Startmenge ohne Hauskoordinate (check.erlaubnis, maske.aus_db), ihre Beziehungen in paper_relation
CREATE TABLE skipped_paper (id TEXT PRIMARY KEY, reason TEXT, source TEXT);
-- Vorlagen, deren Vorlagenart nicht als Zeichenkette kam (Liste, Objekt; einlesen() macht Text daraus): Vorlagenart
-- gilt als nicht erkennbar, keine Hauskoordinate (Entscheidung 10.11.2026); check.erlaubnis liest sie
CREATE TABLE paper_type_other_form (paper_id TEXT PRIMARY KEY);
CREATE INDEX consultation_paper ON consultation(paper_id);
CREATE INDEX relation_child ON paper_relation(child_id);
CREATE INDEX paper_location_loc ON paper_location(location_id);
CREATE INDEX location_ortsteil ON location(ortsteil);
CREATE INDEX originator_paper ON paper_originator(paper_id);
CREATE INDEX responsibility_paper ON paper_responsibility(paper_id);
"""


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


# Listenwertige Felder einer Vorlage (OParl 1.1) und ihrer Beratungen. Kommt statt der Liste ein einzelnes Objekt bzw.
# eine einzelne Adresse, wird es zur Liste mit diesem Element, null zur leeren Liste (Gegenprüfung der Generalprobe
# 09./10.11.2026: sonst Abbruch oder Werte, die in Zeichen zerlegt werden)
LISTENFELDER = ("auxiliaryFile", "consultation", "keyword", "location", "originatorOrganization", "originatorPerson",
                "relatedPaper", "subordinatedPaper", "superordinatedPaper", "underDirectionOf")
BERATUNG_LISTENFELDER = ("keyword", "organization")
# Gründe für das Auslassen (Spalte reason in skipped_paper) und ihr Text im Log von build und in der Ausgabe von check
OHNE_NUMMER = "ohne Drucksachennummer"
NUMMER_UNERWARTET = "Drucksachennummer in unerwarteter Form"
AUSLASSUNG = {OHNE_NUMMER: "ohne Drucksachennummer", NUMMER_UNERWARTET: "mit Drucksachennummer in unerwarteter Form"}
# Listen, deren Einträge build als Objekte mit Kennung liest: andere Einträge (etwa nur eine Adresse) fallen heraus
OBJEKTLISTEN = ("consultation", "location")
# Listen von Adressen, die build als Kennung (Zeichenkette) liest; in Beratungen das Gremium. Ein eingebettetes Objekt
# zählt mit seiner `id`, Einträge ohne Kennung fallen heraus (sonst Abbruch: Objekte sind keine Schlüssel)
ADRESSLISTEN = ("originatorOrganization", "originatorPerson", "relatedPaper", "subordinatedPaper",
                "superordinatedPaper", "underDirectionOf")
BERATUNG_ADRESSLISTEN = ("organization",)
BEZIEHUNGEN = ("subordinatedPaper", "superordinatedPaper")
# weitere Beziehung nur für den Datenschutz (Tabelle paper_related)
VERWANDT = "relatedPaper"


def _als_liste(obj, feld, angeglichen):
    wert = obj.get(feld)
    if isinstance(wert, list):
        return wert
    if feld in obj:
        angeglichen[feld] += 1
    return [] if wert is None else [wert]


def _adressen(werte, feld, angeglichen):
    out = []
    for x in werte:
        if isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"]:
            angeglichen[f"{feld} (Objekt statt Adresse)"] += 1
            x = x["id"]
        if isinstance(x, str) and x:
            out.append(x)
        else:
            angeglichen[f"{feld} (Eintrag ohne Kennung)"] += 1
    return out


def _text(wert):
    """Zeichenkettenteile eines Werts in anderer Form (Liste, Objekt; Zahlen als Text) in der Reihenfolge der Quelle."""
    if isinstance(wert, str):
        return [wert.strip()] if wert.strip() else []
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return [str(wert)]
    teile = wert.values() if isinstance(wert, dict) else wert if isinstance(wert, list) else ()
    return [t for x in teile for t in _text(x)]


def einlesen(papers):
    """Vorlagen aus den Rohdaten in der Form, die build erwartet, vor jeder Verwendung (data/raw bleibt unverändert):
    listenwertige Felder als Liste (LISTENFELDER, in Beratungen BERATUNG_LISTENFELDER), in OBJEKTLISTEN nur Objekte mit
    Kennung, in ADRESSLISTEN (in Beratungen BERATUNG_ADRESSLISTEN) nur Kennungen (eingebettetes Objekt → seine `id`),
    `mainFile` nur als Objekt, `paperType` null oder fehlend wie eine leere Vorlagenart (""), in anderer Form (Liste,
    Objekt) als Text aus ihren Zeichenkettenteilen, damit die Regel für Eingaben greift (geocode.EINGABE), und mit dem
    Kennzeichen geocode.ANDERE_FORM (Vorlagenart nicht erkennbar, keine Hauskoordinate; Entscheidung 10.11.2026).
    Vorlagen ohne Drucksachennummer (`reference` fehlt, null oder leer) oder mit einer, die keine Zeichenkette ist,
    werden ausgelassen, nie mit erfundener Nummer; ihre Beziehungen (BEZIEHUNGEN und VERWANDT) bleiben für den
    Datenschutz erhalten. Liefert (Vorlagen, ausgelassene Vorlagen als {id, grund, BEZIEHUNGEN, VERWANDT}, Zähler der
    angeglichenen Felder)."""
    out, ausgelassen, angeglichen = [], [], Counter()
    for roh in papers:
        ref = roh.get("reference")
        if not isinstance(ref, str) or not ref.strip():
            ausgelassen.append({"id": roh["id"],
                                "grund": OHNE_NUMMER if ref is None or isinstance(ref, str) else NUMMER_UNERWARTET,
                                **{f: _adressen(_als_liste(roh, f, Counter()), f, Counter())
                                   for f in BEZIEHUNGEN + (VERWANDT,)}})
            continue
        p = dict(roh)
        for feld in LISTENFELDER:
            p[feld] = _als_liste(roh, feld, angeglichen)
        for feld in OBJEKTLISTEN:
            gut = [x for x in p[feld] if isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"]]
            angeglichen[f"{feld} (Eintrag ohne Objekt oder Kennung)"] += len(p[feld]) - len(gut)
            p[feld] = gut
        for feld in ADRESSLISTEN:
            p[feld] = _adressen(p[feld], feld, angeglichen)
        p["consultation"] = [{**c, **{f: _als_liste(c, f, angeglichen) for f in BERATUNG_LISTENFELDER}}
                             for c in p["consultation"]]
        for c in p["consultation"]:
            for feld in BERATUNG_ADRESSLISTEN:
                c[feld] = _adressen(c[feld], f"consultation/{feld}", angeglichen)
        if p.get("mainFile") is not None and not isinstance(p["mainFile"], dict):
            angeglichen["mainFile (kein Objekt)"] += 1
            p["mainFile"] = None
        typ = p.get("paperType")
        if typ is None:
            p["paperType"] = ""
        elif not isinstance(typ, str):
            angeglichen["paperType (keine Zeichenkette)"] += 1
            p["paperType"] = "; ".join(_text(typ))
            p[ANDERE_FORM] = True   # Vorlagenart nicht erkennbar: keine Hauskoordinate (geocode.vorlagenart_erkannt)
        out.append(p)
    return out, ausgelassen, +angeglichen


# Zahlen außer Postleitzahlen (fünfstellig, 5xxxx) gelten in Ortsangaben der Stadt als Hausnummern; check.py prüft
_NUMMER = re.compile(r"(?<!\d)(?!5\d{4}\b)\d{1,4}(?:\s?[a-zA-Z](?![a-zA-ZäöüÄÖÜß]))?"
                     r"(?:\s*(?:-|–|/|bis)\s*\d{1,4}(?:\s?[a-zA-Z](?![a-zA-ZäöüÄÖÜß]))?)?(?!\d)")


def ohne_hausnummer(text):
    """Ortsangabe der Stadt ohne Hausnummer (CLAUDE.md 5.2): bisher hätte eine Hausnummer in der Quelle die
    tägliche Veröffentlichung angehalten, statt die Straße zu zeigen (Code-Prüfung 23.10.2026)."""
    out = re.sub(r"\s+,", ",", re.sub(r"\s{2,}", " ", _NUMMER.sub("", (text or "").strip()))).strip(" ,")
    return out or None


def build():
    for path in (config.PAPERS, config.ORGANIZATIONS):
        if not path.exists():
            raise SystemExit(f"Fehlt: {path} – zuerst `python -m pipeline fetch` ausführen.")
    if not config.CONSULTATIONS_LITE.exists():
        print(f"Hinweis: {config.CONSULTATIONS_LITE} fehlt – Beratungen ohne Sitzung/TOP.")
    # dieselbe Vorlage kann beim seitenweisen Abruf zweimal vorkommen (neue Vorlagen verschieben die Seiten);
    # doppelt eingetragene Einreichende und Zuständigkeiten vermeiden (Code-Prüfung 23.10.2026)
    papers, ausgelassen, angeglichen = einlesen(
        {p["id"]: p for p in _read_jsonl(config.PAPERS) if not p.get("deleted")}.values())
    for grund, n in sorted(Counter(a["grund"] for a in ausgelassen).items()):
        print(f"{n} Vorlagen {AUSLASSUNG[grund]} ausgelassen")
    if angeglichen:
        print("Feldformen angeglichen (einzelner Wert → Liste, null → leere Liste, Objekt in einer Adressliste → seine "
              "Kennung, Einträge ohne Objekt oder Kennung entfernt, mainFile ohne Objekt → fehlend, paperType ohne "
              "Zeichenkette → Text): " + ", ".join(f"{k} {n}" for k, n in sorted(angeglichen.items())))
    orgs = json.loads(config.ORGANIZATIONS.read_text())
    lite = ({c["uri"]: c for c in _read_jsonl(config.CONSULTATIONS_LITE)}
            if config.CONSULTATIONS_LITE.exists() else {})
    stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}

    config.BUILD.mkdir(parents=True, exist_ok=True)
    config.EXPORT.mkdir(parents=True, exist_ok=True)   # Audits entstehen schon beim Aufbau
    config.DB.unlink(missing_ok=True)
    db = sqlite3.connect(config.DB)
    db.executescript(SCHEMA)

    strassen_stand = (json.loads(config.STRASSEN.read_text())["meta"].get("retrieved_at")
                      if config.STRASSEN.exists() else None)
    bplan_stand = (json.loads(config.BPLAN.read_text())["meta"].get("retrieved_at")
                   if config.BPLAN.exists() else None)
    retrieved = {
        config.QUELLE_OPARL: stand.get("papers"),
        config.QUELLE_GEO: stand.get("geo"),
        config.QUELLE_STRASSEN: stand.get("geo") or strassen_stand,
        config.QUELLE_BPLAN: stand.get("bplan") or bplan_stand,
        "osm": stand.get("objekte"),
    }
    db.executemany("INSERT INTO source VALUES (?,?,?,?)",
                   [(k, v["url"], v["license"], retrieved.get(k)) for k, v in config.SOURCES.items()])

    orgs_by_id = {o["id"]: o for o in orgs}
    db.executemany(
        f"INSERT INTO organization VALUES (?,?,?,?,?,?,?,?,?,'{config.QUELLE_OPARL}')",
        [(o["id"], o["name"], o.get("shortName"), o.get("organizationType"),
          o.get("classification"),
          actors.amt_label(o) if o.get("organizationType") == "Verwaltungsbereich" else o["name"],
          o.get("startDate"), o.get("endDate"), o.get("web")) for o in orgs])

    papers_by_id = {p["id"]: p for p in papers}
    ortsteile = Ortsteile()
    meetings, agenda, locations, bv_bezirke = {}, {}, {}, {}
    rows = {k: [] for k in ("paper", "rel", "related", "cons", "ploc", "orig", "resp", "plan")}

    # Beziehungen (auch ausgelassener Vorlagen ohne Drucksachennummer: Sie fehlen in `paper`, der Export zeigt sie
    # nicht, sie zählen aber für den Datenschutz; check.erlaubnis liest paper_relation und paper_related)
    for p in papers + ausgelassen:
        rows["rel"] += ([(p["id"], c) for c in p.get("subordinatedPaper") or []]
                        + [(o, p["id"]) for o in p.get("superordinatedPaper") or []])
        rows["related"] += [(p["id"], r) for r in p.get(VERWANDT) or []]
    gremien = {p["id"]: [(orgs_by_id.get((c.get("organization") or [None])[0]) or {}).get("name", "")
                         for c in p.get("consultation") or [] if isinstance(c, dict)] for p in papers}
    gesperrt = _ohne_hauskoordinate(papers, ausgelassen, gremien, orgs_by_id, rows["rel"], rows["related"])
    # OParl-Ortsangaben einer Vorlage ohne Erlaubnis: kein genauer Punkt (Stufe A), auch nicht für andere Vorlagen mit
    # derselben Ortsangabe (vorsichtige Auslegung)
    grob = {loc["id"] for p in papers if p["id"] in gesperrt for loc in p.get("location") or []}

    for p in papers:
        mf = p.get("mainFile") or {}
        rows["paper"].append((p["id"], p.get("reference"), p.get("name"), p.get("paperType"),
                              p.get("date"), (p.get("underDirectionOf") or [None])[0],
                              p.get("web"), mf.get("accessUrl"), mf.get("fileName")))

        bezirke = set()
        for pos, c in enumerate(p.get("consultation") or []):
            org = (c.get("organization") or [None])[0]
            name = (orgs_by_id.get(org) or {}).get("name", "")
            bz = bv_bezirk(name)
            if bz:
                bezirke.add(bz)
            lc = lite.get(c["id"]) or {}
            m, a = lc.get("meeting"), lc.get("agendaItem")
            if m:
                meetings[m["uri"]] = (m["uri"], m.get("name"), m.get("startDate"),
                                      int(bool(m.get("cancelled"))))
            if a:
                agenda[a["uri"]] = (a["uri"], m["uri"] if m else None, a.get("number"),
                                    a.get("name"), a.get("result"),
                                    None if a.get("public") is None else int(a["public"]))
            rows["cons"].append((c["id"], p["id"], pos, org, c.get("role"),
                                 int(bool(c.get("authoritative"))),
                                 m["uri"] if m else None, a["uri"] if a else None,
                                 config.QUELLE_SITZUNG if (m or a) else None))

        for loc in p.get("location") or []:
            geom = (loc.get("geojson") or {}).get("geometry") or {}
            lon = lat = ot = None
            if geom.get("type") == "Point" and loc["id"] not in grob:
                lon, lat = geom["coordinates"][:2]
                ot = ortsteile.locate(lon, lat)
                level, method, conf = "strasse", "oparl_location", "hoch"
            else:
                # Köln: Ort meist nur als subLocality (Stadtteil) ohne Geometrie → Stadtteilfläche (CLAUDE.md 5.2, Stufe A);
                # ohne Erlaubnis für Hauskoordinaten (grob) gilt ein Punkt nur für seinen Stadtteil (Stadtteilfläche wie
                # bei subLocality; Datenschutz, Prüfung r19), außerhalb der Stadtteile ohne Koordinate
                treffer = ortsteile.by_name(loc.get("subLocality"))
                if not treffer and geom.get("type") == "Point":
                    im = ortsteile.locate(*geom["coordinates"][:2])
                    treffer = ortsteile.by_name(im["ortsteil_bez"]) if im else None
                if treffer:
                    ot, pt = treffer
                    lon, lat = round(pt.x, 6), round(pt.y, 6)
                    level, method, conf = "ortsteil", "oparl_sublocality", "mittel"
                else:
                    level, method, conf = "strasse", "oparl_location", "niedrig"
            locations[loc["id"]] = (
                loc["id"], ohne_hausnummer(loc.get("streetAddress")), loc.get("postalCode"),
                loc.get("subLocality"), ohne_hausnummer(loc.get("description")), lon, lat,
                ot["ortsteil_bez"] if ot else None, ot["ortsteil"] if ot else None,
                ot["bezirk_bez"] if ot else None, level, config.QUELLE_OPARL)
            rows["ploc"].append((p["id"], loc["id"], "A", method, conf,
                                 ohne_hausnummer(loc.get("description")) or loc.get("subLocality"), loc["id"]))

        bv_bezirke[p["id"]] = bezirke
        for nr, ev in plan_numbers(p.get("name")):
            rows["plan"].append((p["id"], nr, ev))
        for r in actors.originators(p, orgs, bezirke):
            rows["orig"].append((p["id"], r["actor"], r["actor_type"], r["organization_id"],
                                 r["method"], r["evidence"], 1))
        for r in actors.responsibilities(p, orgs_by_id, papers_by_id):
            rows["resp"].append((p["id"], r["organization_id"], r["kind"], r["method"],
                                 r["evidence"], r["derived"]))

    # Straßenpunkte aus den Ortsangaben der Stadt für Namen, die im Straßenverzeichnis fehlen; ohne die auf den Stadtteil
    # zurückgeführten Ortsangaben (grob: ihr Punkt ist der Stadtteil, nicht die Straße)
    points = [(loc[1], loc[5], loc[6]) for loc in locations.values()
              if loc[-1] == config.QUELLE_OPARL and loc[0] not in grob]
    gaz = Gazetteer(street_points=points)
    rows["ploc"] += _stage_b(papers, bv_bezirke, locations, gaz, gremien, gesperrt)
    plans = Plans()
    rows["plan"] = [(pid, nr, ev, plans.classify(nr)[0]) for pid, nr, ev in rows["plan"]]
    plan_locs, plan_rows = plan_locations([r[:3] for r in rows["plan"]], ortsteile, plans)
    locations.update(plan_locs)
    # Vorrang: Bei eindeutigem Plan gilt der Geltungsbereich; Straßen- und Ortsnamen aus dem Titel treten zurück
    sure = {r[0] for r in plan_rows if r[4] == "hoch"}
    precedence = [(r[0], r[1], r[3], r[5]) for r in rows["ploc"] if r[0] in sure and r[2] == "B"]
    rows["ploc"] = [r for r in rows["ploc"] if not (r[0] in sure and r[2] == "B")]
    rows["ploc"] += plan_rows
    print(f"Bebauungspläne: {len({r[0] for r in plan_rows})} Vorlagen mit Geltungsbereich, "
          f"{len({r[0] for r in rows['plan']})} mit Plannummer im Titel, "
          f"{len(sure)} eindeutig (Vorrang vor {len(precedence)} Ortsbezügen aus dem Titel)")
    rows["ploc"] += _objects_in_titles(papers, locations, gaz, {r[0] for r in rows["ploc"]})
    rows["ploc"] += _fulltext(papers, bv_bezirke, locations, gaz, {r[0] for r in rows["ploc"]}, ausgelassen)
    rows["ploc"] += _inherited(papers, papers_by_id, rows["ploc"], locations, gaz, gesperrt)
    rows["ploc"] += _from_committee(papers, bv_bezirke, locations, gaz, {r[0] for r in rows["ploc"]})

    # OR REPLACE: ändert sich die Quelle während des seitenweisen Abrufs, kann eine Vorlage doppelt kommen
    db.executemany(f"INSERT OR REPLACE INTO paper VALUES (?,?,?,?,?,?,?,?,?,'{config.QUELLE_OPARL}')", rows["paper"])
    db.executemany(f"INSERT OR IGNORE INTO paper_relation VALUES (?,?,'{config.QUELLE_OPARL}')", rows["rel"])
    db.executemany(f"INSERT OR IGNORE INTO paper_related VALUES (?,?,'{config.QUELLE_OPARL}')", rows["related"])
    db.executemany(f"INSERT INTO meeting VALUES (?,?,?,?,'{config.QUELLE_SITZUNG}')", meetings.values())
    db.executemany(f"INSERT INTO agenda_item VALUES (?,?,?,?,?,?,'{config.QUELLE_SITZUNG}')", agenda.values())
    db.executemany(f"INSERT OR REPLACE INTO consultation VALUES (?,?,?,?,?,?,?,?,'{config.QUELLE_OPARL}',?)", rows["cons"])
    db.executemany("INSERT INTO location VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", locations.values())
    db.executemany("INSERT OR IGNORE INTO paper_plan VALUES (?,?,?,?)", rows["plan"])
    db.executemany("INSERT INTO plan_precedence VALUES (?,?,?,?)", precedence)
    db.executemany("INSERT OR IGNORE INTO paper_location VALUES (?,?,?,?,?,?,?)", rows["ploc"])
    db.executemany("INSERT INTO paper_originator VALUES (?,?,?,?,?,?,?)", rows["orig"])
    db.executemany("INSERT INTO paper_responsibility VALUES (?,?,?,?,?,?)", rows["resp"])
    db.executemany(f"INSERT OR IGNORE INTO skipped_paper VALUES (?, ?, '{config.QUELLE_OPARL}')",
                   [(a["id"], a["grund"]) for a in ausgelassen])
    db.executemany("INSERT OR IGNORE INTO paper_type_other_form VALUES (?)",
                   [(p["id"],) for p in papers if p.get(ANDERE_FORM)])
    db.commit()
    db.close()
    print(f"{len(papers)} Vorlagen, {len(rows['cons'])} Beratungen, {len(meetings)} Sitzungen, "
          f"{len(agenda)} TOPs, {len(locations)} Orte → {config.DB}")


def _ohne_hauskoordinate(papers, ausgelassen, gremien, orgs_by_id, rel, related):
    """IDs ohne Erlaubnis für Hauskoordinaten, gleiches Urteil wie check.erlaubnis (geocode.sperrmenge): Startmenge sind
    Eingaben, Vorlagen natürlicher Personen, Beratungen im Ausschuss für Anregungen und Beschwerden, Vorlagen mit leerer
    oder nicht erkennbarer Vorlagenart (Entscheidung 10.11.2026), Vorlagen, deren Titel maske.py ohne Hausnummer zeigt
    (Einwohnerschaft, Bauordnung, Naturschutz; federführende Organisation aus `underDirectionOf` wie in maske.aus_db),
    und die ausgelassenen Vorlagen (ohne Drucksachennummer keine Erlaubnis, geocode.REFERENZ_PUNKT); dazu als Fixpunkt
    alle verbundenen Vorlagen (über- und untergeordnet, relatedPaper) und alle Vorlagen mit derselben Drucksache
    (vorsichtige Auslegung: auch eine Vorlage unbekannter Art kann eine Eingabe sein und sperrt ihre Beantwortung).
    Log: Gründe, Wege, relatedPaper und die erkannten und nicht erkannten Vorlagenarten mit Anzahl (nur die Art), damit
    das Muster geocode.VORLAGENART_PUNKT nach dem Vollabruf in beide Richtungen geprüft und ergänzt werden kann."""
    amt = {p["id"]: (orgs_by_id.get((p.get("underDirectionOf") or [None])[0]) or {}).get("name") for p in papers}
    grund = {p["id"]: punkt_ausschluss(p, gremien.get(p["id"], ()), amt[p["id"]]) for p in papers}
    start = {pid for pid, g in grund.items() if g} | {a["id"] for a in ausgelassen}
    drucksachen = {p["id"]: p["reference"] for p in papers}
    weg = sperrmenge(start, rel + related, drucksachen)
    ohne_verwandt = sperrmenge(start, rel, drucksachen)
    je_grund, je_weg = Counter(grund.values()), Counter(weg[i] for i in grund if i in weg)
    print(f"Ohne Erlaubnis für Hauskoordinaten: {len(weg.keys() & grund.keys())} von {len(papers)} Vorlagen ("
          + ", ".join([f"{text} {je_grund[g]}" for g, text in AUSSCHLUSS.items()]
                      + [f"{text} {je_weg[w]}" for w, text in WEG.items()]) + ")")
    # relatedPaper: ob Köln das Feld füllt, ist ungemessen (Vollabruf); Vorlagen, die nur darüber gesperrt sind
    print(f"relatedPaper: {len({a for a, _ in related} & grund.keys())} Vorlagen mit relatedPaper "
          f"({len(set(related))} Verweise); ohne Hauskoordinate nur über relatedPaper: "
          f"{len((weg.keys() - ohne_verwandt.keys()) & grund.keys())} Vorlagen")
    print(nicht_erkannte_arten(Counter(vorlagenart_bezeichnung(p) for p in papers if grund[p["id"]] == "vorlagenart")))
    print(erkannte_arten(Counter(vorlagenart_bezeichnung(p) for p in papers if grund[p["id"]] is None)))
    return set(weg)


def _add_location(r, locations, gaz):
    """Ort einer Gazetteer-Zeile in die Ortstabelle; liefert die Orts-ID."""
    if r["level"] == "adresse":   # Hauskoordinate (nur Verwaltungsvorlagen und politische Anträge)
        loc_id, source = f"adresse:{r['name']} {r['hausnummer']}|{r['ortsteil']}", r["source"]
        nr = gaz.ot_by_name[r["ortsteil"]]["ortsteil"]
        locations[loc_id] = (loc_id, f"{r['name']} {r['hausnummer']}", None, None, f"{r['name']} {r['hausnummer']}",
                             r["lon"], r["lat"], r["ortsteil"], nr, r["bezirk"], "adresse", source)
        return loc_id
    if r["level"] == "strasse":
        loc_id, source = f"strasse:{r['name']}|{r['ortsteil']}", r["source"]
    elif r["level"] == "objekt":   # Gebäude oder Anlage aus OSM (Stufe C)
        loc_id, source = f"objekt:{r['name']}|{r['ortsteil']}", "osm"
    else:
        loc_id, source = f"{r['level']}:{r['name']}", config.QUELLE_GEO
    nr = gaz.ot_by_name[r["ortsteil"]]["ortsteil"] if r["ortsteil"] else None
    locations[loc_id] = (loc_id, r["name"] if r["level"] in ("strasse", "objekt") else None, None, None,
                         r["name"], r["lon"], r["lat"], r["ortsteil"], nr, r["bezirk"],
                         r["level"], source)
    return loc_id


def _objects_in_titles(papers, locations, gaz, placed):
    """Gebäude und Anlagen aus dem Verzeichnis (OSM) im Titel von Vorlagen ohne eigenen Ortsbezug (Stufe B, Methode
    „objekt_name“, Konfidenz „niedrig“); Audit und einmalig eine Stichprobe."""
    obj = Objekte()
    if not len(obj):
        return []
    out, audit, found = [], [], {}
    for p in papers:
        if p["id"] in placed:
            continue
        for o in obj.im_titel(p.get("name")):
            r = dict(level="objekt", name=o["name"], ortsteil=o["ortsteil"], bezirk=o["bezirk"], lon=o["lon"], lat=o["lat"])
            ev = f"Name im Titel: {o['name']}; Lage laut OpenStreetMap ({o['art']}, {o['osm']})"
            out.append((p["id"], _add_location(r, locations, gaz), "B", "objekt_name", "niedrig", ev, p["id"]))
            audit.append((p["reference"], o["name"], o["art"], o["ortsteil"], o["osm"]))
            found.setdefault(p["reference"], (p, []))[1].append(o)
    _write(config.EXPORT / "audit_objekte_titel.tsv", ["drucksache", "gebäude oder anlage", "art", "ortsteil", "osm"],
           sorted(audit))
    print(f"Gebäude und Anlagen im Titel: {len(found)} Vorlagen ohne eigenen Ortsbezug, {len(out)} Ortsbezüge")
    path = config.EXPORT / "objekte" / "stichprobe_objekte.tsv"
    if found and not path.exists():
        pick = sorted(random.Random(20261021).sample(sorted(found), min(30, len(found))))
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, ["nr", "drucksache", "titel", "link", "gebäude oder anlage (Ortsteil)", "urteil (richtig/teilweise/falsch)",
                      "anmerkung"],
               [[i, ref, found[ref][0].get("name"), found[ref][0].get("web") or "",
                 "; ".join(f"{o['name']} ({o['ortsteil']})" for o in found[ref][1]), "", ""]
                for i, ref in enumerate(pick, 1)])
        print(f"Stichprobe Gebäude und Anlagen: {len(pick)} → {path}")
    return out


def _fulltext(papers, bv_bezirke, locations, gaz, placed, ausgelassen=()):
    """Ortsbezüge aus dem Volltext der Hauptdatei (volltext.py) für Vorlagen ohne eigenen Ortsbezug; Audit und
    einmalig eine Stichprobe (ohne Textauszüge). `ausgelassen`: Vorlagen ohne Drucksachennummer (einlesen); mit ihnen
    verbundene Vorlagen werden wie die Kette der Einwohnerschaft nicht aus dem Volltext verortet."""
    texts = volltext.load_texts()
    if not texts:
        print(f"Volltext: {config.TEXTE} fehlt – keine Verortung aus Dokumenten.")
        return []
    out, audit, found = [], [], {}
    kette = volltext.einwohner_kette(papers, ausgelassen)
    for p in papers:
        text = texts.get((p.get("mainFile") or {}).get("id"))
        if not text or p["id"] in placed or not volltext.allowed(p.get("paperType")) or p["id"] in kette:
            continue
        if volltext.titel_ohne_ort(p.get("name")):
            audit.append((p["reference"], "Titel ohne gemeinsamen Ort, nicht verortet", "", "", "", "", "", ""))
            continue
        rows, info = volltext.locate(gaz, text, bv_bezirke.get(p["id"], ()))
        if not rows:
            audit.append((p["reference"], info["befund"], info.get("teil", ""), "", "", "", "", ""))
        for r in rows:
            out.append((p["id"], _add_location(r, locations, gaz), "B", r["method"], r["confidence"], r["evidence"], p["id"]))
            audit.append((p["reference"], info["befund"], r["teil"], r["method"], r["name"], r["ortsteil"] or "",
                          r["confidence"], r["nennungen"]))
        if rows:
            found[p["reference"]] = (p, rows)
    _write(config.EXPORT / "audit_volltext.tsv",
           ["drucksache", "befund", "teil", "methode", "ort", "ortsteil", "konfidenz", "nennungen"], sorted(audit, key=str))
    n_text = sum(1 for p in papers if texts.get((p.get("mainFile") or {}).get("id")))
    befunde = Counter(a[1].split(" (")[0] for a in {(a[0], a[1]) for a in audit})
    print(f"Volltext: {n_text} Vorlagen mit Text, {len(found)} neu verortet ({len(out)} Ortsbezüge); Befunde {dict(befunde)}")
    _fulltext_sample(found)
    return out


def _fulltext_sample(found):
    """30 Vorgänge mit Verortung aus dem Volltext zur Prüfung (je Vorgang eine Zeile; wird nie überschrieben)."""
    path = config.EXPORT / "volltext" / "stichprobe_volltext.tsv"
    if path.exists() or not found:
        return
    seen, cases = set(), []
    for ref in sorted(found):
        if ref[:6] not in seen:
            seen.add(ref[:6]); cases.append(ref)
    pick = sorted(random.Random(20261020).sample(cases, min(30, len(cases))))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, ["nr", "drucksache", "titel", "link", "orte (Ortsteil)", "konfidenz", "teil", "urteil (richtig/falsch/unklar)",
                  "anmerkung"],
           [[i, ref, found[ref][0].get("name"), found[ref][0].get("web") or "",
             "; ".join(f"{r['name']} ({r['ortsteil']})" if r["ortsteil"] and r["level"] == "strasse" else r["name"] for r in found[ref][1]),
             "/".join(sorted({r["confidence"] for r in found[ref][1]})), found[ref][1][0]["teil"], "", ""]
            for i, ref in enumerate(pick, 1)])
    print(f"Stichprobe Volltext: {len(pick)} → {path}")


def _write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _stage_b(papers, bv_bezirke, locations, gaz, gremien=None, gesperrt=None):
    """Stufe B: Ortsbezüge aus dem Titel (Straße, Ortsteil, Stadtbezirk); Hauskoordinate nur, wo erlaubt. `gesperrt`:
    IDs ohne Hauskoordinate (geocode.ohne_hauskoordinate, mit verbundenen Vorlagen); ohne Angabe die Regel je Vorlage."""
    if not gaz.streets:
        print(f"Hinweis: {config.STRASSEN} fehlt oder ist leer – Stufe B ohne Straßen.")
    out, hnr = [], {}
    for p in papers:
        punkt = (p["id"] not in gesperrt if gesperrt is not None
                 else hausnummer_punkt_erlaubt(p, (gremien or {}).get(p["id"], ())))
        for r in gaz.locate(p.get("name"), bv_bezirke.get(p["id"], ()), punkt_erlaubt=punkt):
            if "hnr_vorher" in r:
                hnr.setdefault((p["reference"], r["name"]), (r["hnr_vorher"], r.get("hnr_ohne_lage") or r["ortsteil"],
                                                              "hnr_ohne_lage" not in r, p))
            out.append((p["id"], _add_location(r, locations, gaz), "B", r["method"], r["confidence"], r["evidence"], p["id"]))
    print(f"Stufe B: {len({r[0] for r in out})} Vorlagen, {len(out)} Ortsbezüge")
    _hnr_audit(hnr)
    return out


def _hnr_audit(hnr):
    """Wirkung der Regel „strasse+hausnummer“ je Vorlage und Straße (ohne die Hausnummer selbst); dazu einmalig
    eine Stichprobe zur Prüfung von Hand (je Vorgang eine Zeile: alle geänderten, dazu eindeutige bis 30; wird nie
    überschrieben)."""
    def wirkung(before, after, used):
        if not used:
            return "ohne Wirkung: Abschnitt im Ortsteil fehlt im Straßenverzeichnis"
        return "bestätigt" if before == [after] else "eindeutig" if after in before else "geändert"
    rows = sorted((ref, street, "; ".join(before), after, wirkung(before, after, used))
                  for (ref, street), (before, after, used, _) in hnr.items())
    with open(config.EXPORT / "audit_hausnummern.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["drucksache", "strasse", "ortsteile_ohne_hausnummer", "ortsteil_der_hausnummer", "wirkung"])
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r[4]] = counts.get(r[4], 0) + 1
    print(f"Hausnummern: {len(rows)} Nennungen", counts)
    sample_file = config.EXPORT / "hausnummern" / "stichprobe_hausnummern.tsv"
    if sample_file.exists():
        return
    papers = {(ref, street): v[3] for (ref, street), v in hnr.items()}
    def one_per_case(rs):  # Stellungnahmen und Änderungsanträge teilen die sechsstellige Drucksachennummer
        seen, out = set(), []
        for r in rs:
            if r[0][:6] not in seen:
                seen.add(r[0][:6]); out.append(r)
        return out
    changed = one_per_case([r for r in rows if r[4] == "geändert"])
    clear = [r for r in one_per_case([r for r in rows if r[4] == "eindeutig"]) if r[0][:6] not in {c[0][:6] for c in changed}]
    pick = changed + random.Random(20261020).sample(clear, min(len(clear), 30 - len(changed)))
    sample_file.parent.mkdir(parents=True, exist_ok=True)
    with open(sample_file, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["nr", "drucksache", "titel", "link", "strasse", "ortsteile_ohne_hausnummer", "ortsteil_der_hausnummer",
                    "wirkung", "urteil (richtig/falsch/unklar)", "anmerkung"])
        for i, r in enumerate(pick, 1):
            p = papers[(r[0], r[1])]
            w.writerow([i, r[0], p.get("name"), p.get("web") or "", *r[1:], "", ""])
    print(f"Stichprobe Hausnummern: {len(pick)} → {sample_file}")


# Kurzform „BV Innenstadt“: Schreibvariante in explore/ergebnisse/gremien_koeln.tsv (Zeilen „belegt“, aus
# Sekundärquellen, Abgleich mit dem RIS offen)
BV_NAME = re.compile(r"^(?:Bezirksvertretung|BV)\s+(?:(\d+)\s*)?(?:\((.+)\)|(.+))?$")


def bv_bezirk(name):
    """Stadtbezirk einer Bezirksvertretung aus dem Gremiennamen: „Bezirksvertretung 3 (Lindenthal)“ → „Lindenthal“,
    „Bezirksvertretung 3“ → „Lindenthal“ (Nummer der Hauptsatzung), „Bezirksvertretung Porz“ → „Porz“,
    „BV Innenstadt“ → „Innenstadt“."""
    from .geocode import BEZIRKE_KOELN
    m = BV_NAME.match((name or "").strip())
    if not m:
        return None
    nr, klammer, rest = m.groups()
    if klammer or rest:
        return (klammer or rest).strip()
    return BEZIRKE_KOELN.get(int(nr)) if nr else None


def _from_committee(papers, bv_bezirke, locations, gaz, placed):
    """Schwache Evidenz `district_from_committee` (CLAUDE.md 5.2): Vorlagen ohne jeden anderen Ortsbezug, die in genau
    einer Bezirksvertretung beraten wurden, erhalten deren Stadtbezirk (Konfidenz niedrig)."""
    out = []
    for p in papers:
        bz = bv_bezirke.get(p["id"]) or set()
        if p["id"] in placed or len(bz) != 1:
            continue
        name = next(iter(bz))
        if name not in gaz.bezirk_point:
            continue
        pt = gaz.bezirk_point[name]
        r = dict(level="stadtbezirk", name=name, ortsteil=None, bezirk=name, lon=round(pt.x, 6), lat=round(pt.y, 6))
        out.append((p["id"], _add_location(r, locations, gaz), "B", "district_from_committee", "niedrig",
                    f"nur in der Bezirksvertretung {name} beraten", p["id"]))
    print(f"Stadtbezirk aus der beratenden Bezirksvertretung: {len(out)} Vorlagen")
    return out


def _strassenabschnitt(loc, locations, gaz):
    """Orts-IDs des Straßenabschnitts zu einer Hauskoordinate (Ort der Ebene „adresse“ aus _add_location): dieselbe
    Straße im Stadtteil der Hausnummer, ohne Nummer, wie die Rückfallstufe in _stage_b („strasse+hausnummer“); leer,
    wenn das Straßenverzeichnis die Straße dort nicht kennt."""
    strasse, ortsteil = loc[1].rsplit(" ", 1)[0], loc[7]   # Straße „Name Hausnummer“; die Hausnummer ohne Leerzeichen
    return sorted({_add_location(dict(level="strasse", name=strasse, ortsteil=ortsteil, bezirk=e["bezirk"], lon=e["lon"],
                                      lat=e["lat"], source=e["source"]), locations, gaz)
                   for e in gaz.streets.get(strasse, ()) if e["ortsteil"] == ortsteil})


def _inherited(papers, papers_by_id, own_rows, locations=None, gaz=None, gesperrt=frozenset()):
    """Vorlagen ohne eigenen Ortsbezug erben die Ortsbezüge der übergeordneten Vorlage. Eine Vorlage ohne Erlaubnis für
    Hauskoordinaten (`gesperrt`, geocode.sperrmenge) erbt nie eine Hauskoordinate: statt des Orts der Ebene „adresse“
    den Straßenabschnitt (_strassenabschnitt), sonst nichts von diesem Ort. Mit dem Fixpunkt ist die übergeordnete
    Vorlage einer gesperrten Vorlage selbst gesperrt und hat keine Hauskoordinate; die Regel hier sichert das zusätzlich
    ab (Prüfung r19: vorher erbte eine Kopie mit derselben Drucksache wie eine Eingabe den Punkt, check hielt an)."""
    own = {}
    for r in own_rows:
        own.setdefault(r[0], []).append(r)
    out = []
    for p in papers:
        if p["id"] in own:
            continue
        for parent_id in p.get("superordinatedPaper") or []:
            parent = papers_by_id.get(parent_id)
            ev = f"übergeordnete Vorlage {parent.get('reference') if parent else parent_id}"
            # abgeleitet, daher Stufe B; die Konfidenz liegt höchstens bei „mittel“
            for _, loc_id, _, _, conf, _, _ in own.get(parent_id, []):
                conf = "mittel" if conf == "hoch" else conf
                if p["id"] in gesperrt and locations[loc_id][10] == "adresse":
                    out += [(p["id"], abschnitt, "B", "vererbt", conf, f"{ev} (Straßenabschnitt ohne Hausnummer)",
                             parent_id) for abschnitt in _strassenabschnitt(locations[loc_id], locations, gaz)]
                    continue
                out.append((p["id"], loc_id, "B", "vererbt", conf, ev, parent_id))
    print(f"Vererbt: {len({r[0] for r in out})} Vorlagen")
    return out
