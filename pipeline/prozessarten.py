"""Reiter „Prozesse“: Verfahrensarten mit Zahlen aus Bonn und Gremien mit Zuständigkeit (data/export/bonn/prozessarten.json).

Die Verfahren selbst (Schritte, Bahnen, Fristen, Rechtsgrundlagen) und die Zuständigkeitsordnung stehen in soll.json;
diese Datei ergänzt je Verfahren die Zahl der Vorgänge in Bonn mit Beispielen (Zuordnung abgeleitet, pipeline/soll.py)
und je Gremium Art, Beratungen, letzte und nächste Sitzung (OParl-API der Stadt Bonn, CC0); je Amt die
Abteilungen, federführende Vorlagen und die Gremien, die sie beraten (OParl-Feld `underDirectionOf`).
Die Zuordnung der Ämter zu Dezernaten fehlt in der Quelle (`subOrganizationOf` leer); gruppiert wird nach der
Amtsnummer (abgeleitet)."""
import collections
import datetime
import json
import re
import unicodedata

from . import actors, besetzung, config, maske, soll

# Gremienarten der OParl-API, die Entscheidungen treffen oder beraten (ohne Fraktionen, Gruppen und interne Gremien)
ARTEN = {"Rat": "rat", "Ratsgremien": "ausschuss", "Bezirksvertretungen": "bezirksvertretung",
         "Beiräte und Kommissionen": "beirat"}
# Abschnitt der Zuständigkeitsordnung, dessen Titel vom Namen des Gremiums in der OParl-API abweicht
ZUSTO_ALIAS = {"Ausschuss für Soziales, Migration, Gesundheit, Wohnen und Senioren":
               "Ausschuss für Soziales, Migration, Gesundheit und Senioren"}
BEISPIELE = 3
# Gruppen der Ämter nach der ersten Ziffer der Amtsnummer (kommunales Gliederungsschema; Zuordnung abgeleitet)
AMT_GRUPPEN = [
    ("0", "Ämter 02 bis 05"),
    ("1", "Allgemeine Verwaltung"),
    ("2", "Finanzen"),
    ("3", "Recht, Sicherheit und Ordnung"),
    ("4", "Schule und Kultur"),
    ("5", "Soziales, Jugend, Gesundheit und Sport"),
    ("6", "Bauen, Verkehr und Umwelt"),
    ("8", "Gebäude und Betriebe"),
    ("koordination", "Koordination und Stäbe"),
    ("bezirk", "Bezirksverwaltungsstellen"),
    ("weitere", "Weitere Einrichtungen"),
]
# Verwaltungsbereiche ohne Amtsnummer, die die Arbeit der Verwaltungsspitze koordinieren
KOORDINATION = re.compile(r"^(Co-Dezernat|Dezernat|Geschäftsbereich OB|I{1,3}-\d|Beethoven 2020)")
HINWEIS_POLITIK = ("Formal federführend bei Anträgen und Anfragen aus der Politik, die über das Ratsbüro laufen; "
                   "fachlich zuständig ist meist ein Amt, das in einer Stellungnahme der Verwaltung antwortet.")
HINWEIS_EINWOHNER = ("Formal federführend bei Bürgeranträgen sowie Anregungen und Beschwerden; fachlich zuständig ist "
                     "meist ein Amt, das in einer Stellungnahme der Verwaltung antwortet.")
TOP_GREMIEN = 5


def art(name, classification):
    """Feinere Art eines Gremiums: rat, hauptausschuss, ausschuss, unterausschuss, wahlausschuss, bezirksvertretung, beirat."""
    a = ARTEN.get(classification)
    if a != "ausschuss":
        return a
    if name == "Hauptausschuss":
        return "hauptausschuss"
    if "Unterausschuss" in name:
        return "unterausschuss"
    if "wahl" in name.lower():
        return "wahlausschuss"
    return "ausschuss"


def _term_start(terms, today):
    """Beginn der laufenden Wahlperiode (OParl legislativeTerms)."""
    starts = [t["startDate"] for t in terms if t.get("startDate") and t["startDate"] <= today
              and (not t.get("endDate") or t["endDate"] >= today)]
    return max(starts) if starts else None


def verfahren(rows, titles):
    """Je Verfahren: Zahl der Vorgänge und die jüngsten Beispiele (Stammnummer, Titel, Datum)."""
    out = {}
    by = collections.defaultdict(list)
    for r in rows:
        if r["verfahren"]:
            by[r["verfahren"]].append(r)
    for vid, rs in by.items():
        known = [r for r in rs if r["stammnummer"] in titles]
        known.sort(key=lambda r: (titles[r["stammnummer"]][1] or "", r["stammnummer"]), reverse=True)
        out[vid] = {"vorgaenge": len(rs), "sicher": sum(r["sicherheit"] == "hoch" for r in rs),
                    "beispiele": [{"drucksache": r["stammnummer"], "titel": titles[r["stammnummer"]][0],
                                   "datum": titles[r["stammnummer"]][1]} for r in known[:BEISPIELE]]}
    return out


def gremien(db, meetings, zusto, today, term_start, besetzt=None):
    """Gremien mit Art, Zahl der Beratungen und Vorlagen, letzter und nächster Sitzung, Abschnitt der Zuständigkeitsordnung."""
    stats = {oid: (n, k, last) for oid, n, k, last in db.execute(
        "SELECT c.organization_id, COUNT(*), COUNT(DISTINCT c.paper_id), MAX(substr(m.start_date, 1, 10)) "
        "FROM consultation c LEFT JOIN meeting m ON m.id = c.meeting_id GROUP BY c.organization_id")}
    upcoming = {}
    for m in sorted(meetings, key=lambda m: m.get("start") or ""):
        day = (m.get("start") or "")[:10]
        if day < today or m.get("cancelled"):
            continue
        for oid in m.get("organization") or []:
            upcoming.setdefault(oid, {"datum": day, "web": m.get("web")})
    out = []
    for oid, name, cls, end, web in db.execute(
            "SELECT id, name, classification, end_date, web FROM organization WHERE org_type = 'Gremium'"):
        a = art(name, cls)
        if not a:
            continue
        n, k, last = stats.get(oid, (0, 0, None))
        nxt = upcoming.get(oid)
        ended = bool(end) and end < today
        # aktuell: nicht aufgelöst und in der laufenden Wahlperiode zusammengetreten oder mit angesetzter Sitzung
        aktuell = not ended and (bool(nxt) or bool(last and term_start and last >= term_start))
        key = name if name in zusto else ZUSTO_ALIAS.get(name)
        g = {"id": oid.rsplit("/", 1)[-1], "name": name, "art": a, "aktuell": aktuell, "beratungen": n, "vorlagen": k,
             "letzte": last, "naechste": nxt, "aufgeloest": end if ended else None, "web": web}
        if aktuell and (besetzt or {}).get(besetzung._kurz(oid)):
            g["besetzung"] = besetzt[besetzung._kurz(oid)]   # Mitglieder, Sitze nach Fraktion (abgeleitet)
        if key in zusto:
            g["zusto"] = key
            if key != name:
                g["zusto_hinweis"] = f"In der Zuständigkeitsordnung als „{key}“ geführt (Zuordnung abgeleitet)."
        out.append(g)
    order = ["rat", "hauptausschuss", "ausschuss", "bezirksvertretung", "beirat", "unterausschuss", "wahlausschuss"]
    out.sort(key=lambda g: (not g["aktuell"], order.index(g["art"]), -g["beratungen"], g["name"]))
    return out


def _slug(text):
    t = unicodedata.normalize("NFKD", text.replace("ß", "ss")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def amt_gruppe(label):
    """Gruppe eines Amts (Schlüssel aus AMT_GRUPPEN) nach Amtsnummer oder Bezeichnung."""
    if label.startswith("Bezirksverwaltungsstelle"):
        return "bezirk"
    if KOORDINATION.match(label) or re.match(r"^01-", label):
        return "koordination"
    m = re.match(r"^(\d)\d\b", label)
    if m and m.group(1) in dict(AMT_GRUPPEN):
        return m.group(1)
    return "weitere"


def aemter(db, today):
    """Ämter (Bezeichnung laut `classification`, bei Co-Dezernat der Verwaltungsbereich) mit Abteilungen,
    federführenden Vorlagen, beratenden Gremien und fachlicher Zuständigkeit laut Stellungnahme (abgeleitet)."""
    units = collections.OrderedDict()
    for oid, name, label, cls, end in db.execute(
            "SELECT id, name, label, classification, end_date FROM organization WHERE org_type = 'Verwaltungsbereich' "
            "ORDER BY label, name"):
        if not label or label.startswith("Ebene 3"):  # Fraktionsgeschäftsstellen: keine Verwaltung
            continue
        u = units.setdefault(label, {"bereiche": [], "ids": set(), "co": False})
        u["ids"].add(oid)
        u["co"] |= cls == actors.CO_DEZERNAT
        u["bereiche"].append({"id": oid, "name": name, "end": end})
    by_org = collections.defaultdict(list)
    m = maske.aus_db(db)
    for pid, ref, name, ptype, date, org in db.execute(
            "SELECT id, reference, name, paper_type, date, under_direction_of FROM paper"):
        by_org[org].append((pid, ref, m(name, ref), ptype, date))
    gremium_of = collections.defaultdict(set)
    gname = {}
    for pid, oid, gn in db.execute(
            "SELECT c.paper_id, c.organization_id, o.name FROM consultation c JOIN organization o ON o.id = c.organization_id "
            "WHERE o.org_type = 'Gremium'"):
        gremium_of[pid].add(oid)
        gname[oid] = gn
    fachlich = collections.Counter(oid for (oid,) in db.execute(
        "SELECT organization_id FROM paper_responsibility WHERE kind = 'fachlich'"))
    fach_von = collections.defaultdict(collections.Counter)  # Koordinationsstelle → fachlich zuständige Ämter
    for lead, label in db.execute(
            "SELECT o2.label, o.label FROM paper_responsibility r JOIN paper p ON p.id = r.paper_id "
            "JOIN organization o ON o.id = r.organization_id JOIN organization o2 ON o2.id = p.under_direction_of "
            "WHERE r.kind = 'fachlich'"):
        fach_von[lead][label] += 1
    label_of = {oid: label for label, u in units.items() for oid in u["ids"]}
    fach_unit = collections.Counter()
    for oid, n in fachlich.items():
        if oid in label_of:
            fach_unit[label_of[oid]] += n
    out = []
    for label, u in units.items():
        # feste Reihenfolge (Mengen und Gleichstände sonst je Lauf anders; Code-Prüfung 23.10.2026)
        papers = [p for oid in sorted(u["ids"]) for p in by_org.get(oid, [])]
        ended = all(b["end"] and b["end"] < today for b in u["bereiche"])
        abteilungen = sorted(({"name": b["name"], "vorlagen": len(by_org.get(b["id"], [])),
                               "aufgeloest": b["end"] if b["end"] and b["end"] < today else None}
                              for b in u["bereiche"] if b["name"] != label),
                             key=lambda a: (bool(a["aufgeloest"]), a["name"]))
        gc = collections.Counter(g for p in papers for g in sorted(gremium_of.get(p[0], ())))
        newest = sorted(papers, key=lambda p: (p[4] or "", p[1] or ""), reverse=True)
        politik = sum(p[3] in actors.POLITIK_TYPES for p in papers)
        einwohner = sum(p[3] in actors.EINWOHNER_TYPES for p in papers)
        gruppe = "koordination" if u["co"] else amt_gruppe(label)
        a = {"id": _slug(label), "name": label, "gruppe": gruppe, "aktuell": not ended and bool(papers),
             "vorlagen": len(papers), "politik": politik, "einwohner": einwohner, "letzte": newest[0][4] if newest else None,
             "aufgeloest": max(b["end"] for b in u["bereiche"]) if ended else None,
             "abteilungen": abteilungen,
             "gremien": [{"id": g.rsplit("/", 1)[-1], "name": gname[g], "vorlagen": n}
                         for g, n in sorted(gc.items(), key=lambda x: (-x[1], gname[x[0]], x[0]))[:TOP_GREMIEN]],
             "fachlich": fach_unit.get(label, 0),
             "beispiele": [{"drucksache": p[1], "titel": p[2], "datum": p[4]} for p in newest[:BEISPIELE]]}
        if gruppe == "koordination" and papers and max(politik, einwohner) / len(papers) >= 0.5:
            a["hinweis"] = HINWEIS_POLITIK if politik >= einwohner else HINWEIS_EINWOHNER
        if gruppe == "koordination" and fach_von[label]:
            a["fachlich_aemter"] = [{"name": n, "vorlagen": k}
                                    for n, k in sorted(fach_von[label].items(), key=lambda x: (-x[1], x[0]))[:TOP_GREMIEN]]
        out.append(a)
    order = [k for k, _ in AMT_GRUPPEN]
    out.sort(key=lambda a: (order.index(a["gruppe"]), a["name"]))
    return out


def site_data(db, today=None):
    today = today or datetime.date.today().isoformat()
    rows = soll.vorgaenge(db)
    m = maske.aus_db(db)   # Hausnummern in Titeln aus der Einwohnerschaft (Beispiele je Verfahren)
    titles = {ref: (m(name, ref), date) for ref, name, date in db.execute("SELECT reference, name, date FROM paper")}
    meetings = json.loads(config.MEETINGS.read_text()) if config.MEETINGS.exists() else []
    meetings = meetings.get("data", []) if isinstance(meetings, dict) else meetings
    terms = json.loads(config.LEGISLATIVE_TERMS.read_text()) if config.LEGISLATIVE_TERMS.exists() else []
    term_start = _term_start(terms, today)
    zusto = soll.site_data()["zusto"]
    besetzt, audit = besetzung.gremien(term_start, today)
    besetzung.write_audit(audit)
    return {
        "meta": {"quellen": "OParl-API der Stadt Bonn (CC0): Gremien, Beratungen, Sitzungen; Zuordnung der Vorgänge "
                            "zu Verfahren abgeleitet (Soll-Modell nach „Bonn entscheidet“, MIT)",
                 "wahlperiode_seit": term_start,
                 "hinweis": "Zahlen je Verfahren beruhen auf der abgeleiteten Zuordnung; Sicherheit „hoch“ separat ausgewiesen.",
                 "aemter_hinweis": "Ämter und Federführung aus der OParl-API (underDirectionOf); die Gruppen folgen der "
                                   "Amtsnummer (abgeleitet), da die Quelle keine Zuordnung zu Dezernaten enthält.",
                 "besetzung_hinweis": "Laufende Mitgliedschaften laut OParl-API der Stadt Bonn (CC0), ohne Kontaktdaten. "
                                      "Die Fraktion ist abgeleitet aus der Mitgliedschaft in einer Fraktion des Rates bzw. "
                                      "der Bezirksfraktion; die Quelle nennt nicht, für wen jemand im Gremium sitzt. "
                                      "Sachkundige Bürger:innen gehören meist keiner Fraktion an. Ohne Namen: "
                                      "Stellvertretungen, Verwaltung, Beiräte mit Jugendmitgliedern."},
        "verfahren": verfahren(rows, titles),
        "gremien": gremien(db, meetings, zusto, today, term_start, besetzt),
        "amt_gruppen": [{"id": k, "label": v} for k, v in AMT_GRUPPEN],
        "aemter": aemter(db, today),
    }
