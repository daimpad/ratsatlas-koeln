"""Exporte für ganz Köln je Stadtteil, Stadtbezirk und Jahr (data/export/koeln, für die Webseite; wird bei der
Veröffentlichung erzeugt) und stadtweite Audits (data/export/audit_*.tsv). Jede Vorlage mit Prozesslinie, Akteuren und
Ortsbezügen samt Quelle. Bonner Zusatzthemen nur, wenn in config.ZUSATZTHEMEN freigegeben."""
import csv
import json
import random
import re
import shutil
import sqlite3
import unicodedata
from datetime import date, datetime, timezone

from . import aemter, ausschuesse, chat, config, dossier, flaechen, prozessbild, gebietszahlen, glossar, maske, plans, process as proc, prozessarten, publish, soll, topics
from .themenseiten import ALLE as THEMENSEITEN

DERIVED_NOTE = (
    "Einreichende (originators), fachliche Zuständigkeit (responsibility.kind = 'fachlich') und "
    "Ortsbezüge der Stufe B bzw. 'vererbt' (locations.stage, method, confidence, evidence) sind "
    "abgeleitet; alle übrigen Felder stammen unverändert aus den Quellen. VORLÄUFIGE FASSUNG: "
    "Stichprobenprüfung von Hand ausstehend."
)
AUDIT_COLUMNS = ["drucksache", "datum", "vorlagenart", "titel", "stufe", "methode", "ebene", "treffer",
                 "ortsteil", "stadtbezirk", "konfidenz", "fundstelle", "quellobjekt", "pruefstatus"]


def _status(row):
    if row["cancelled"]:
        return "abgesagt"
    if row["result"]:
        return "beraten"
    return "terminiert" if row["meeting_id"] else "offen"


_KURZ = None
KURZ_COLUMNS = ["drucksache", "kurzfassung", "modell", "erzeugt", "kennzeichnung"]
KURZ_HINWEIS = ("KI-Kurzfassung (abgeleitet): mit einem Sprachmodell aus dem Text des Dokuments formuliert, kein Zitat; "
                "Einzelheiten können ungenau sein, maßgeblich ist das Original")


def _kurzfassungen():
    """Freigegebene Kurzfassungen (kurzfassung.py); leer, solange die Stichprobe nicht geprüft ist."""
    global _KURZ
    if _KURZ is None:
        from . import kurzfassung
        _KURZ = kurzfassung.fuer_seite()
    return _KURZ


_MASKE = [None, None]


def _maske(db):
    """Hausnummern in Titeln aus der Einwohnerschaft (maske.py), je Datenbankverbindung einmal aufgebaut."""
    if _MASKE[0] is not db:
        _MASKE[:] = [db, maske.aus_db(db)]
    return _MASKE[1]


def _paper_detail(db, pid):
    p = db.execute(
        "SELECT p.*, o.label AS amt, o.name AS vb_name FROM paper p "
        "LEFT JOIN organization o ON o.id = p.under_direction_of WHERE p.id = ?", (pid,)).fetchone()
    # je Eintrag der Beratungsfolge eine Station (Entscheidung 17.11.2026 (14)); die Kennung der Beratung bleibt intern
    process = db.execute(
        "SELECT c.id AS beratung, c.position, c.role, c.authoritative, c.meeting_id, c.agenda_item_id, "
        "g.name AS gremium, m.name AS meeting, m.start_date, m.cancelled, a.number, a.result, a.public "
        "FROM consultation c LEFT JOIN organization g ON g.id = c.organization_id "
        "LEFT JOIN meeting m ON m.id = c.meeting_id LEFT JOIN agenda_item a ON a.id = c.agenda_item_id "
        "WHERE c.paper_id = ? ORDER BY c.position", (pid,)).fetchall()
    resp = db.execute(
        "SELECT r.kind, r.method, r.evidence, r.derived, r.confidence, r.kennung, o.label, o.name "
        "FROM paper_responsibility r "
        "LEFT JOIN organization o ON o.id = r.organization_id WHERE r.paper_id = ?", (pid,)).fetchall()
    orig = db.execute(
        "SELECT actor, actor_type, organization_id, method, evidence, derived "
        "FROM paper_originator WHERE paper_id = ?", (pid,)).fetchall()
    m, ref = _maske(db), p["reference"]
    # Fundstellen sind Teile des Titels (Bebauungsplan: Text zwischen Stichwort und Plannummer, Einreichende:
    # Abschnitt des Titels): dieselbe Maske wie der Titel (Prüfung r20a; vorher stand dort die Hausnummer, die der
    # Titel ausblendet), im Zusammenhang des ganzen Titels (Maske.ausschnitt; dritte Korrektur: vorher allein maskiert,
    # und „1175, Hinterhof … – Anfrage der Fraktion …“ behielt die Nummer, deren Straße vor dem Ausschnitt stand).
    # Ortsnamen und Ergebnisse der Beratungen ebenso (dritte Korrektur: check prüft sie, die Maske kann also jeden
    # Befund beheben). Ergebnisse je Tagesordnungspunkt (Offen (8) der Nachprüfung der dritten Korrektur): Wird dort
    # eine Vorlage der Maske beraten (Maske.tops), läuft das Ergebnis bei jeder Vorlage, die es zeigt, mit deren
    # Drucksache durch die Maske; die Kennung des Tagesordnungspunkts bleibt intern (Datenmodell unverändert). Das gilt
    # für alle Punkte einer solchen Vorlage (Maske.drucksache_ergebnisse, dieselbe Funktion in check): Derselbe Text auf
    # einem zweiten Punkt blieb sonst ungekürzt, und check meldete ihn im Feed der Vorlage als Befund, den die Maske
    # nicht beheben konnte. Sitzungsnamen laufen bei jeder Sitzung durch die Maske (Maske.sitzungsname, wie in
    # _meetings; Entscheidung 19.11.2026 (3) (c), vorher nur bei Sitzungen aus Maske.sitzungen, Offen (9))
    ref_ergebnisse = m.drucksache_ergebnisse(ref, [r["agenda_item_id"] for r in process])
    fund = lambda rows: [{**dict(r), "evidence": m.ausschnitt(r["evidence"], p["name"], ref)} for r in rows]
    locs = [{**r, "name": m(r["name"], ref)} for r in fund(_locations(db, pid))]
    rel = lambda sql: [{**dict(r), "name": m(r["name"], r["reference"])} for r in db.execute(sql, (pid,))]
    d = {
        "reference": ref,
        "name": m(p["name"], ref),
        "paper_type": p["paper_type"],
        "date": p["date"],
        "amt": p["amt"],
        "web": p["web"],
        "main_file": p["main_file_url"],
        # Federführung mit Zuordnung zur Ämtertabelle (pipeline/aemter.py, CLAUDE.md 5.3): Dezernat und Dienststelle
        # laut Geschäfts- und Dezernatsverteilungsplan mit Methode, Stand und Fundstelle; ohne eindeutigen Treffer nur
        # der Status, die Zeile bleibt sonst wie zuvor. confidence und kennung nur bei der Federführung aus dem Kopf der
        # Vorlage (pdf_kopf, aus einer Anlage pdf_kopf_anlage), sonst wie bisher ohne
        "responsibility": [_mit_aemtertabelle({**{k: v for k, v in dict(r).items() if v is not None or k not in ("confidence", "kennung")},
                                               "evidence": m(r["evidence"], ref)}, p["date"]) for r in resp],
        "originators": fund(orig),
        "process": [{**{k: v for k, v in dict(r).items() if k not in ("beratung", "agenda_item_id")},
                     "meeting": m.sitzungsname(r["meeting"]),
                     "result": m(r["result"], ref_ergebnisse), "status": _status(r)}
                    for r in process],
        "superordinated": rel("SELECT p.reference, p.paper_type, p.name, p.date FROM paper_relation r "
                              "JOIN paper p ON p.id = r.parent_id WHERE r.child_id = ?"),
        "subordinated": rel("SELECT p.reference, p.paper_type, p.name, p.date FROM paper_relation r "
                            "JOIN paper p ON p.id = r.child_id WHERE r.parent_id = ? "
                            "ORDER BY p.date"),
        "locations": locs,
        # Plannummern im Titel (Methode B3); match = Treffer im Datensatz der rechtskräftigen Pläne,
        # names = zugeordnete Pläne (Teilpläne, Grundnummer), area = Geltungsbereich vorhanden
        "plans": [_plan_entry(nr, m.ausschnitt(ev, p["name"], ref), match) for nr, ev, match in
                  db.execute("SELECT plan_nr, evidence, match FROM paper_plan WHERE paper_id = ?", (pid,))],
        "source_object": pid,
    }
    # Stand nach dem Eintrag jeder Beratung, der zählt (Entscheidung 17.11.2026 (15), proc.massgeblich): Steht eine
    # Kennung in derselben Vorlage mehrfach (etwa nach einer Vertagung), zählt ihr Eintrag mit dem spätesten
    # Sitzungstag, bei gleichem Tag der spätere in der Beratungsfolge; hat ihr letzter Eintrag noch keinen Sitzungstag,
    # zählt er (bis dahin immer der letzte Eintrag, Entscheidung 17.11.2026 (14)). Einträge einer abgesagten Sitzung
    # zählen dabei nicht, außer alle Einträge der Kennung sind abgesagt (Entscheidung 17.11.2026 (16) (A)). Die übrigen
    # Einträge bleiben Stationen der Prozesslinie
    zaehlt = set(proc.zaehlende([r["beratung"] for r in process], [proc.local_day(r["start_date"]) for r in process],
                                [r["cancelled"] for r in process]).values())
    d["stand"] = proc.stand({"process": [s for i, s in enumerate(d["process"]) if i in zaehlt]})
    d["themes"] = topics.themes(d)
    d["parties"] = topics.parties(d)
    d["steps"] = [{k: v for k, v in s.items() if v not in (None, [], False)} for s in proc.steps(d)]
    d["soll"] = soll.lookup(db, p["reference"]) if _an("soll") else None  # Zusatzthema (Bonner Regelwerk)
    if p["reference"] in _kurzfassungen():
        d["kurzfassung"] = _kurzfassungen()[p["reference"]]
    return d


def _mit_aemtertabelle(r, datum):
    """Zeile der Federführung (kind „federfuehrend“) mit `aemtertabelle` (aemter.fuer_export): Kennung aus dem Kopf der
    Vorlage (Spalte `kennung`, sobald der Schritt „Dokumente“ sie liefert), sonst Name der Organisation aus
    `underDirectionOf`, je mit dem Plan, dessen Stand am Datum der Vorlage der jüngste ist, wenn das Datum nicht nach
    seiner letzten Prüfung liegt (aemter.zuordnen). Andere Zeilen unverändert."""
    if r.get("kind") != "federfuehrend":
        return r
    return {**r, "aemtertabelle": aemter.fuer_export(aemter.zuordnung_federfuehrung(r, datum))}


def _locations(db, pid):
    """Ortsbezüge einer Vorlage; Stufe-B-Bezüge entfallen, wo Stufe A denselben Ortsteil belegt."""
    rows = [dict(r) for r in db.execute(
        "SELECT l.level, COALESCE(l.street, l.description) AS name, l.ortsteil, l.stadtbezirk, "
        "l.lon, l.lat, pl.stage, pl.method, pl.confidence, pl.evidence, pl.source_object, "
        "l.source FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "WHERE pl.paper_id = ? ORDER BY pl.stage, l.level", (pid,))]
    a_ortsteile = {r["ortsteil"] for r in rows if r["stage"] == "A"}
    return [r for r in rows if r["stage"] == "A" or r["ortsteil"] not in a_ortsteile
            or r["ortsteil"] is None or r["level"] == "bebauungsplan"]


def _audit_rows(db, where="", params=()):
    """Audit-Zeilen je Ortsbezug; Stufe-B-Treffer bei Vorlagen mit Stufe A gelten als geprüft."""
    a = {}
    for pid, ot in db.execute("SELECT pl.paper_id, l.ortsteil FROM paper_location pl JOIN location l "
                              "ON l.id = pl.location_id WHERE pl.stage = 'A'"):
        a.setdefault(pid, set()).add(ot)
    out = []
    for r in db.execute(
            "SELECT p.id, p.reference, p.date, p.paper_type, p.name, pl.stage, pl.method, l.level, "
            "COALESCE(l.street, l.description), l.ortsteil, l.stadtbezirk, pl.confidence, pl.evidence, "
            "pl.source_object FROM paper_location pl JOIN paper p ON p.id = pl.paper_id "
            f"JOIN location l ON l.id = pl.location_id {where} ORDER BY p.date DESC, p.reference", params):
        pid, *vals = r
        m, titel = _maske(db), vals[3]
        vals[3] = m(titel, vals[0])
        vals[7] = m(vals[7], vals[0])                        # Ortsname (Prüfung r20a, dritte Korrektur)
        vals[11] = m.ausschnitt(vals[11], titel, vals[0])    # Fundstelle (Teil des Titels; Prüfung r20a)
        status = "Quelle (Stufe A)" if vals[4] == "A" else "ungeprüft"
        if vals[4] != "A" and pid in a and vals[6] != "stadtbezirk":
            status = "bestätigt durch Stufe A" if vals[8] in a[pid] else "abweichend von Stufe A"
        out.append(vals + [status])
    return out


def _write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def export():
    config.EXPORT.mkdir(parents=True, exist_ok=True)
    (config.EXPORT / "glossar.json").write_text(json.dumps(glossar.glossar(), ensure_ascii=False, indent=1) + "\n")
    export_all()
    export_audits()


def _an(thema):
    return bool(config.ZUSATZTHEMEN.get(thema))


def export_audits():
    """Stadtweite Audits (CLAUDE.md 2: Audit-Protokolle als TSV) und die Stichprobe je Methode (7.3)."""
    db = sqlite3.connect(config.DB)
    db.row_factory = sqlite3.Row
    papers = [_paper_detail(db, r[0]) for r in db.execute("SELECT id FROM paper ORDER BY date DESC, reference")]
    _write_tsv(config.EXPORT / "audit_geokodierung.tsv", AUDIT_COLUMNS, _audit_rows(db))
    _write_tsv(config.EXPORT / "audit_bebauungsplaene.tsv", PLAN_AUDIT, plan_audit_rows(db))
    _write_tsv(config.EXPORT / "audit_prozess.tsv", PROCESS_AUDIT, process_audit_rows(papers))
    _write_tsv(config.EXPORT / "audit_zeit.tsv", TIME_AUDIT, time_audit_rows(papers, _meetings(db)))
    _write_tsv(config.EXPORT / "audit_themen.tsv", THEME_AUDIT, theme_audit_rows(papers))
    _write_tsv(config.EXPORT / "audit_federfuehrung.tsv", FEDERFUEHRUNG_AUDIT, federfuehrung_audit_rows(papers))
    print(federfuehrung_zeile(papers))
    n = _sample_methods(db, config.EXPORT / "stichprobe_geokodierung.tsv")
    _tabellen_maskieren(db)
    db.close()
    print(f"Audits: {len(papers)} Vorlagen; Stichprobe je Methode: {n} Zeilen → {config.EXPORT}")


def _tabellen_maskieren(db):
    """Jede TSV-Datei unter data/export mit der Spalte „drucksache“ (Audits, Stichproben, auch abgeschalteter
    Zusatzthemen und aus build: paket.write packt sie ins Datenpaket): Spalten mit Titel, Fundstelle oder Ortsnamen
    (maske.TEXTSPALTEN; in den Stichproben aus maske.STICHPROBEN auch die gefundenen Orte) mit derselben Maske wie
    Suche, Gebietsdateien und Audits; idempotent, eine Datei wird nur bei einer Änderung neu geschrieben.
    Vorher nur die Stichproben aus maske.STICHPROBEN (build._hnr_audit, build._fulltext_sample und
    build._objects_in_titles schreiben sie mit vollem Titel; Generalprobe 09.11.2026, Prüfung r20); seit der dritten
    Korrektur der Prüfung r20a jede Datei, die check prüft (audit_volltext.tsv „ort“, audit_objekte_titel.tsv,
    Fundstellen in audit_themen.tsv), damit check nur meldet, was die Maske nicht durchlaufen hat. Spalten nach ihrem
    Namen im Kopf, die Drucksache aus der Spalte „drucksache“; fehlt einer Stichprobe aus maske.STICHPROBEN eine
    davon, bleibt die Datei unverändert und check meldet sie (Prüfung r20a)."""
    m = _maske(db)
    konfiguriert = {config.EXPORT.joinpath(*teile): maskiert for teile, maskiert in maske.STICHPROBEN.items()}
    for pfad in sorted(p for p in config.EXPORT.rglob("*.tsv") if p.is_file()):
        maskiert = konfiguriert.get(pfad)
        with open(pfad, encoding="utf-8", newline="") as f:
            zeilen = list(csv.reader(f, delimiter="\t"))
        kopf = zeilen[0] if zeilen else []
        fehlt = [k for k in ("drucksache", *(maskiert or ())) if k not in kopf]
        if fehlt:
            if maskiert is not None:
                print(f"Hinweis: Stichprobe {pfad} ohne Spalte {', '.join(fehlt)} – nicht maskiert (check meldet sie)")
            continue
        ref = kopf.index("drucksache")
        spalten = {i for i, k in enumerate(kopf) if k in maske.TEXTSPALTEN or k in (maskiert or ())}
        neu = [[m(w, z[ref]) if i in spalten else w for i, w in enumerate(z)] if len(z) > ref else z
               for z in zeilen[1:]]
        if spalten and neu != zeilen[1:]:
            _write_tsv(pfad, kopf, neu)


def _sample_methods(db, path, n=50, seed=2026):
    """Stichprobe zur Prüfung von Hand: je Methode bis zu n Vorlagen (CLAUDE.md 7.3). Wird nur einmal gezogen; eine
    vorhandene Datei ist Prüfgrundlage und bleibt unverändert."""
    if path.exists():
        return 0
    rows, maske_ = [], _maske(db)
    methods = [r[0] for r in db.execute("SELECT DISTINCT method FROM paper_location ORDER BY method")]
    for m in methods:
        ids = [r[0] for r in db.execute("SELECT DISTINCT paper_id FROM paper_location WHERE method = ? ORDER BY paper_id",
                                        (m,))]
        for pid in sorted(random.Random(f"{seed}{m}").sample(ids, min(n, len(ids)))):
            p = list(db.execute("SELECT reference, date, paper_type, name, web FROM paper WHERE id = ?", (pid,)).fetchone())
            titel, p[3] = p[3], maske_(p[3], p[0])
            # Ort und Fundstelle wie der Titel maskiert (Prüfung r20a, zweite Korrektur: vorher nur die Fundstelle)
            locs = [(maske_(l[0], p[0]), *l[1:5], maske_.ausschnitt(l[5], titel, p[0])) for l in db.execute(
                "SELECT COALESCE(l.street, l.description, l.ortsteil, l.stadtbezirk), l.level, l.ortsteil, l.stadtbezirk, "
                "pl.confidence, pl.evidence FROM paper_location pl JOIN location l ON l.id = pl.location_id "
                "WHERE pl.paper_id = ? AND pl.method = ?", (pid, m))]
            rows.append([m, *p, "; ".join(str(l[0]) for l in locs), "; ".join(sorted({l[1] for l in locs})),
                         "; ".join(sorted({str(l[2] or l[3]) for l in locs})), "; ".join(sorted({l[4] for l in locs})),
                         "; ".join(sorted({str(l[5]) for l in locs})), "", ""])
    _write_tsv(path, ["methode", "drucksache", "datum", "vorlagenart", "titel", "link", "ort", "ebene",
                      "stadtteil_oder_bezirk", "konfidenz", "fundstelle", "urteil (richtig/teilweise/falsch/unklar)",
                      "anmerkung"], rows)
    return len(rows)


def _meta(db, stable=False, **extra):
    """Metadaten je Datei. stable=True (Gebietsdateien für ganz Bonn): ohne Erzeugungs- und
    Abrufzeitpunkte, damit sich eine Datei nur ändert, wenn sich ihr Inhalt ändert; die Zeitpunkte
    stehen in index.json."""
    sources = [dict(r) for r in db.execute("SELECT * FROM source")]
    if stable:
        return {**extra, "sources": [{k: v for k, v in s.items() if k != "retrieved_at"} for s in sources],
                "note": DERIVED_NOTE}
    return {**extra, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": sources, "note": DERIVED_NOTE}


def berliner_tag(wert):
    """Kalendertag (JJJJ-MM-TT) eines Zeitpunkts in Europe/Berlin, dieselbe Regel wie zeitTag in site/app.js: 23:30 UTC
    am 31.12. ist dort schon der 01.01.; ein Zeitstempel ohne Zone gilt als UTC; ist nur der Anfang lesbar, die ersten
    zehn Zeichen; sonst None (auch für Zahl, Objekt, „kaputt“, 2026-13-45)."""
    s = wert if isinstance(wert, str) else ""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", s[:10]):
        return None
    try:
        dt = datetime.fromisoformat(s) if len(s) > 10 else None
    except ValueError:
        dt = None
    if dt is None:
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(proc.BERLIN).date().isoformat()


def feed_grenze(stand):
    """Jahresgrenze der Vorgangs-Feeds (publish.has_paper_feed): 1. Januar des Vorjahres des Datenstands als Berliner
    Kalendertag, dieselbe Regel wie standTag und hasPaperFeed in site/app.js (Abruf des Ratsinformationssystems, sonst
    Erzeugung, also heute; nur lesbare Werte)."""
    tag = berliner_tag(stand) or datetime.now(proc.BERLIN).date().isoformat()
    return f"{int(tag[:4]) - 1}-01-01"


def slug(name):
    name = name.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def _dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def export_all():
    """Ganz Köln: je Stadtteil, je Stadtbezirk (nur Bezüge auf Bezirksebene) und Vorlagen ohne
    Ortsbezug je Jahr; dazu index.json mit Zählungen für die Auswahl auf der Webseite und „Aktuell in Köln“
    (_aktuell)."""
    db = sqlite3.connect(config.DB)
    db.row_factory = sqlite3.Row
    out = config.EXPORT / config.STADT
    shutil.rmtree(out, ignore_errors=True)
    cache = {}

    def detail(pid):
        if pid not in cache:
            cache[pid] = _paper_detail(db, pid)
        return cache[pid]

    order = "ORDER BY p.date DESC, p.reference"
    index = {"ortsteile": [], "bezirke": [], "ohne_ortsbezug": []}

    def bbox(feature):
        """Umriss als [Süd, West, Nord, Ost] für den ersten Kartenausschnitt (die Seite lädt die Flächen erst nach
        den Kacheln; Phase 0 „Verständlichkeit“, Schritt 1b)."""
        xs, ys = [], []

        def walk(c):
            if c and isinstance(c[0], (int, float)):
                xs.append(c[0])
                ys.append(c[1])
            else:
                for x in c:
                    walk(x)
        walk(feature["geometry"]["coordinates"])
        return [round(min(ys), 4), round(min(xs), 4), round(max(ys), 4), round(max(xs), 4)]
    areas, names, ortsname = {}, {}, {}   # ortsname: kurzer Name je Gebiet für „Aktuell in Köln“ (_aktuell)

    for ot in json.loads(config.ORTSTEILE.read_text())["features"]:
        name, bezirk = ot["properties"]["ortsteil_bez"], ot["properties"]["bezirk_bez"]
        ids = [r[0] for r in db.execute(
            "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
            f"JOIN paper p ON p.id = pl.paper_id WHERE l.ortsteil = ? {order}", (name,))]
        _dump(out / "ortsteile" / f"{slug(name)}.json",
              {"meta": _meta(db, True, ortsteil=name, stadtbezirk=bezirk, count=len(ids)),
               "papers": [detail(i) for i in ids]})
        index["ortsteile"].append({"name": name, "slug": slug(name), "stadtbezirk": bezirk,
                                   "count": len(ids), "bbox": bbox(ot)})
        areas[f"ortsteil:{slug(name)}"] = ids
        names[f"ortsteil:{slug(name)}"] = ortsname[f"ortsteil:{slug(name)}"] = name

    for bz in json.loads(config.STADTBEZIRKE.read_text())["features"]:
        name = bz["properties"]["bezirk_bez"]
        ids = [r[0] for r in db.execute(
            "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
            "JOIN paper p ON p.id = pl.paper_id WHERE l.level = 'stadtbezirk' AND l.stadtbezirk = ? "
            "AND pl.paper_id NOT IN (SELECT pl2.paper_id FROM paper_location pl2 JOIN location l2 "
            f"ON l2.id = pl2.location_id WHERE l2.ortsteil IS NOT NULL AND l2.stadtbezirk = ?) {order}",
            (name, name))]
        _dump(out / "bezirke" / f"{slug(name)}.json",
              {"meta": _meta(db, True, stadtbezirk=name, count=len(ids)), "papers": [detail(i) for i in ids]})
        index["bezirke"].append({"name": name, "slug": slug(name), "count": len(ids), "bbox": bbox(bz)})
        areas[f"bezirk:{slug(name)}"] = ids
        names[f"bezirk:{slug(name)}"] = f"Stadtbezirk {name}, ohne genaueren Ort"
        ortsname[f"bezirk:{slug(name)}"] = f"Stadtbezirk {name}"

    # ohne Ortsbezug: auch Vorlagen, deren Orte weder einem Ortsteil noch einem Stadtbezirk zugeordnet
    # werden konnten (z. B. Straße ohne Koordinate), damit keine Vorlage verloren geht
    placed = ("SELECT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
              "WHERE l.ortsteil IS NOT NULL OR l.level = 'stadtbezirk'")
    years = [r[0] for r in db.execute(
        f"SELECT DISTINCT substr(date, 1, 4) y FROM paper WHERE id NOT IN ({placed}) ORDER BY y DESC")]
    for year in years:
        ids = [r[0] for r in db.execute(
            f"SELECT p.id FROM paper p WHERE substr(p.date, 1, 4) = ? AND p.id NOT IN ({placed}) {order}",
            (year,))]
        _dump(out / "ohne-ortsbezug" / f"{year}.json",
              {"meta": _meta(db, True, jahr=year, count=len(ids)), "papers": [detail(i) for i in ids]})
        index["ohne_ortsbezug"].append({"jahr": year, "count": len(ids)})
        areas[f"ohne:{year}"] = ids
        names[f"ohne:{year}"] = f"stadtweit / ohne Ortsbezug {year}"
        ortsname[f"ohne:{year}"] = ORT_OHNE
    areas["gesamt"] = [r[0] for r in db.execute("SELECT id FROM paper")]
    for pid in areas["gesamt"]:
        detail(pid)
    if cache:   # Vorschau ohne Vorlagen: keine Zeitleiste (die Seite blendet sie ohne zeit.json aus)
        _dump(out / "zeit.json", _time_index(db, areas, cache))
    _dump(out / "prozesse.json", _paths(db, cache))

    _dump(out / "suche.json", _search_index(cache, areas, names, _meta(db, True)["sources"]))

    # Abonnieren und Nachnutzen (publish.py)
    home = {}
    for key, ids in areas.items():
        for pid in ids:
            home.setdefault(pid, key)
    sources = [dict(r) for r in db.execute("SELECT * FROM source")]
    stand = next((s["retrieved_at"] for s in sources if s["name"] == config.QUELLE_OPARL), None) or ""
    publish.write_feeds(out / "feeds", areas, cache, names, home, slug, feed_grenze(stand))
    zahl_sitzungen = {}
    meetings = _meetings(db, zahl_sitzungen)
    print(zeile_beginn(meetings))
    print(zeile_sitzungsnamen(zahl_sitzungen))
    print(zeile_hinweise(meetings))
    publish.write_calendar(out / "termine.ics", meetings)
    n_points = publish.write_geojson(out / "vorlagen.geojson", cache,
                                     [{k: v for k, v in s.items() if k != "retrieved_at"} for s in sources])
    # Kurzfassungen (nur freigegebene, zweiter Lauf): eigene Datei für das Datenpaket, ohne Text der Quelle
    kurz = _kurzfassungen() if _an("kurzfassungen") else {}
    if kurz:
        _write_tsv(out / "kurzfassungen.tsv", KURZ_COLUMNS,
                   [(ref, k["text"], k["modell"], k["erzeugt"], KURZ_HINWEIS) for ref, k in sorted(kurz.items())])
    publish.write_dcat(out / "dcat.jsonld", min((p["date"] for p in cache.values() if p["date"]), default=None),
                       stand[:10] or datetime.now(timezone.utc).date().isoformat(), kurzfassungen=bool(kurz),
                       orte=publish.ortsquellen(cache))
    n_shards = chat.write_chat(out / "chat", db, cache, meetings, sources, _meta(db, True)) if _an("chat") else 0
    # Bebauungspläne: Register je Plannummer (Grundlage der Planchronik); Geltungsbereich, Inkrafttreten und Link zum
    # Plan aus den Bebauungsplänen (config.QUELLE_BPLAN), sobald die Datei vorliegt; das verlinkte Plandokument ist nicht
    # Teil der Daten (Runde 19b)
    reg = plans.register(cache.values(), _plans())
    _dump(out / "plaene.json", {"meta": {**_meta(db, True), "note": "Geltungsbereich, Inkrafttreten und Link zum Plan belegt, "
                                         "Lizenz der Bebauungspläne " + config.SOURCES[config.QUELLE_BPLAN]["license"]
                                         + "; Verfahrensschritte aus dem Titel abgeleitet"}, **reg})
    # Bonner Zusatzthemen (deaktiviert, CLAUDE.md 5.4): Soll-Modell, Reiter „Prozesse“, Themenseiten
    if _an("soll"):
        _dump(out / "soll.json", soll.site_data())
        _dump(out / "prozessarten.json", prozessarten.site_data(db))
    heute = proc.local_day(stand) if stand else datetime.now(timezone.utc).date().isoformat()
    for t in (THEMENSEITEN if _an("themenseiten") else []):
        thema = dossier.daten(t, cache, home, meetings, heute, _meta(db, True))
        _dump(out / "dossiers" / f"{t.key}.json", thema)
        # Aufrufe: Kalender mit den Sitzungen der beteiligten Gremien, Feed mit den Vorlagen der Stränge, Bild
        publish.write_calendar(out / "dossiers" / f"{t.key}.ics",
                               [m for m in meetings if dossier.sitzung_im_thema(t, m["gremium"])],
                               date.fromisoformat(heute))
        prozessbild.schreibe_bild(t, thema, out / "dossiers", f"{config.SITE_URL}{t.pfad}")
        refs = {r["reference"] for s in thema["straenge"] for r in s["vorlagen"]}
        publish.write_topic_feed(out / "dossiers" / f"{t.key}.xml", t.key,
                                 t.titel, [(pid, p) for pid, p in cache.items() if p["reference"] in refs],
                                 home, f"{config.SITE_URL}{t.pfad}")

    # Vereinfachte Flächen für die Seite (Navigation, Umrisse, Bebauungspläne), komprimierbar als .json
    flaechen.write(out)
    # Übersichtskarte: Vorlagen der letzten zwölf Monate und auffälliges Thema je Gebiet
    gebietszahlen.annotate(index, areas, cache, stand or datetime.now(timezone.utc).isoformat())
    # „Aktuell in Köln“ (Entscheidung 19.11.2026 (1) (E)): nur, wenn mindestens eine Karte Daten hat
    aktuell = _aktuell(cache, _heimat(areas), ortsname, meetings, heute, _stand())
    if aktuell:
        index["aktuell"] = aktuell
    # ausgesetzte Listen (sessionnet, Entscheidung 13.11.2026) nur, wenn es welche gibt: sonst bleibt index.json gleich
    ausgesetzt = _abruf_ausgesetzt(_stand())
    _dump(out / "index.json", {"meta": _meta(db, stadt=config.STADT_NAME, seitenname=config.SEITENNAME,
                                             funktionen=funktionen(),
                                             testdaten=bool(_stand().get("testdaten")),
                                             vorschau=bool(_stand().get("vorschau")),
                                             abruf_fehler=_abruf_fehler(_stand()),
                                             abruf_warnungen=_abruf_warnungen(_stand()),
                                             **({"abruf_ausgesetzt": ausgesetzt} if ausgesetzt else {})), **index})
    db.close()
    print(f"{config.STADT_NAME}: {len(index['ortsteile'])} Stadtteile, {len(index['bezirke'])} Bezirke, "
          f"{len(years)} Jahre ohne Ortsbezug, {len(cache)} Vorlagen, {n_points} Punkte im GeoJSON, {n_shards} Dateien für den Assistenten → {out}")


# Freigaben, die index.json erst eingeschaltet nennt, damit index.json ohne sie byte-gleich bleibt: die Strukturdaten
# (pipeline/strukturdaten_web.py) und die Wahlbeteiligung je Stadtteil (pipeline/wahl_koeln.py, nur kontext.json,
# kein Bezug in site/)
FUNKTIONEN_NUR_AN = ("strukturdaten", "wahlbeteiligung")


def funktionen():
    """Freigaben für site/app.js (index.json meta.funktionen; ein fehlender Schlüssel gilt als aus)."""
    return {k: v for k, v in config.ZUSATZTHEMEN.items() if k not in FUNKTIONEN_NUR_AN or v}


def _stand():
    return json.loads(config.STAND.read_text()) if config.STAND.exists() else {}


def _abruf_fehler(stand):
    """Fehler des letzten Abrufs für die Seite („Der letzte Abruf … ist fehlgeschlagen“): nur, wenn er nach dem letzten
    vollständigen Abruf (`abruf_ok`) liegt; ein älterer Eintrag gilt nicht mehr. Unlesbare Zeitpunkte: Fehler zeigen."""
    fehler = stand.get("abruf_fehler")
    ok = stand.get("abruf_ok")
    if not fehler or not ok:
        return fehler or None
    try:
        if datetime.fromisoformat(fehler["zeit"]) <= datetime.fromisoformat(ok):
            return None
    except (TypeError, ValueError, KeyError):
        pass
    return fehler


# Nebenlisten mit Warnung in STAND.json (`abruf_warnungen`, pipeline/sessionnet.py), die die Seite zeigt
WARNUNG_LISTEN = ("meetings", "organizations")


def _abruf_warnungen(stand):
    """Warnungen der Nebenlisten für die Seite („Sitzungstermine wurden beim letzten Abruf nicht aktualisiert; gezeigt
    wird der Stand vom …“): je Liste aus WARNUNG_LISTEN `zeit`, `meldung` und `stand` (letzte reguläre Aktualisierung
    dieser Liste in STAND.json, sonst None). Nur gültige: ein Objekt mit Meldung, das nicht vor der letzten regulären
    Aktualisierung dieser Liste liegt (wie _abruf_fehler; sessionnet entfernt die Warnung dabei ohnehin, dies ist die
    Sicherung); unlesbare Zeitpunkte: Warnung zeigen."""
    warnungen = stand.get("abruf_warnungen")
    aus = {}
    for liste, w in (warnungen.items() if isinstance(warnungen, dict) else ()):
        if liste not in WARNUNG_LISTEN or not isinstance(w, dict) or not w.get("meldung"):
            continue
        letzter = stand.get(liste)
        try:
            if letzter and datetime.fromisoformat(w["zeit"]) < datetime.fromisoformat(letzter):
                continue
        except (TypeError, ValueError, KeyError):
            pass
        aus[liste] = {"zeit": w.get("zeit"), "meldung": w["meldung"],
                      "stand": letzter if isinstance(letzter, str) else None}
    return aus


# Listen, deren Abruf aussetzen kann (STAND.json `abruf_ausgesetzt`, sessionnet.AUSSETZEN), die die Seite nennt
AUSGESETZT_LISTEN = ("papers", "meetings")


def _abruf_ausgesetzt(stand):
    """Ausgesetzte Listen für die Seite („Der Abruf der Vorlagen ruht seit …; gezeigt wird der Stand vom …“): je Liste
    aus AUSGESETZT_LISTEN `seit` (Beginn des Aussetzens, unlesbar: None) und `stand` (letzte reguläre Aktualisierung
    dieser Liste in STAND.json, sonst None). Jeder Eintrag, der ein Objekt ist, gilt (auch ohne lesbaren Zeitpunkt:
    vorsichtig zeigen), außer er liegt vor der letzten regulären Aktualisierung der Liste (wie _abruf_warnungen;
    sessionnet entfernt ihn dabei ohnehin, dies ist die Sicherung). Zahlen und Abhilfe stehen nur in STAND.json und in
    der Abrufstatistik."""
    eintraege = stand.get("abruf_ausgesetzt")
    aus = {}
    for liste, a in (eintraege.items() if isinstance(eintraege, dict) else ()):
        if liste not in AUSGESETZT_LISTEN or not isinstance(a, dict):
            continue
        letzter = stand.get(liste)
        seit = a.get("seit") if isinstance(a.get("seit"), str) else None
        try:
            if letzter and seit and datetime.fromisoformat(seit) < datetime.fromisoformat(letzter):
                continue
        except (TypeError, ValueError):
            pass
        aus[liste] = {"seit": seit, "stand": letzter if isinstance(letzter, str) else None}
    return aus


def export_pilot(ortsteil=config.PILOT_ORTSTEIL):
    """Bonner Pilot-Ortsteil (in Köln nicht verwendet, CLAUDE.md 2: kein Pilot-Stadtteil)."""
    db = sqlite3.connect(config.DB)
    db.row_factory = sqlite3.Row
    ids = [r[0] for r in db.execute(
        "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "JOIN paper p ON p.id = pl.paper_id WHERE l.ortsteil = ? ORDER BY p.date DESC, p.reference",
        (ortsteil,))]
    papers = [_paper_detail(db, pid) for pid in ids]
    # ohne Zeitpunkte wie die Gebietsdateien: sonst änderte sich der Branch deploy bei jedem Lauf (Code-Prüfung 24.10.2026)
    meta = _meta(db, True, ortsteil=ortsteil, count=len(papers))
    out = config.EXPORT / ortsteil.lower()
    out.mkdir(parents=True, exist_ok=True)
    (out / "vorlagen.json").write_text(
        json.dumps({"meta": meta, "papers": papers}, ensure_ascii=False, indent=1) + "\n")

    features = [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [loc["lon"], loc["lat"]]},
         "properties": {"reference": p["reference"], "name": p["name"],
                        "paper_type": p["paper_type"], "date": p["date"], "amt": p["amt"],
                        "place": loc["name"], "level": loc["level"], "ortsteil": loc["ortsteil"],
                        "stage": loc["stage"], "method": loc["method"],
                        "confidence": loc["confidence"], "web": p["web"]}}
        for p in papers for loc in p["locations"]
        if loc["lon"] is not None and loc["ortsteil"] == ortsteil
    ]
    (out / "vorlagen.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "meta": meta, "features": features},
        ensure_ascii=False, indent=1) + "\n")
    _write_tsv(out / "audit_prozess.tsv", PROCESS_AUDIT, process_audit_rows(papers))
    _write_tsv(out / "audit_zeit.tsv", TIME_AUDIT, time_audit_rows(papers, _meetings(db)))
    _write_tsv(out / "audit_themen.tsv", THEME_AUDIT, theme_audit_rows(papers))
    _write_tsv(out / "audit_geokodierung.tsv", AUDIT_COLUMNS,
               _audit_rows(db, "WHERE p.id IN (SELECT pl2.paper_id FROM paper_location pl2 JOIN location l2 "
                               "ON l2.id = pl2.location_id WHERE l2.ortsteil = ?)", (ortsteil,)))
    _write_tsv(config.EXPORT / "audit_geokodierung_bonn.tsv", AUDIT_COLUMNS, _audit_rows(db))
    _write_tsv(config.EXPORT / "audit_bebauungsplaene.tsv", PLAN_AUDIT, plan_audit_rows(db))
    # Pilot: Vorlagen mit Plannummer, die im Ortsteil liegen oder ihn im Titel nennen
    _write_tsv(out / "audit_bebauungsplaene.tsv", PLAN_AUDIT, plan_audit_rows(
        db, "WHERE p.id IN (SELECT pl2.paper_id FROM paper_location pl2 JOIN location l2 ON l2.id = pl2.location_id "
            "WHERE l2.ortsteil = ?) OR p.name LIKE ?", (ortsteil, f"%{ortsteil}%")))
    _sample(db, out, ortsteil)
    db.close()
    print(f"{len(papers)} Vorlagen, {len(features)} Punkte → {out}")


def _sample(db, out, ortsteil, n=50, seed=2026):
    """Stichprobe zur Prüfung von Hand: Vorlagen, die nur über Stufe B/vererbt im Ortsteil liegen.
    Wird nur einmal gezogen; eine vorhandene Datei ist Prüfgrundlage und bleibt unverändert."""
    if (out / "stichprobe_pruefung.tsv").exists():
        return
    ids = [r[0] for r in db.execute(
        "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "WHERE l.ortsteil = ? AND pl.stage = 'B' AND pl.paper_id NOT IN "
        "(SELECT paper_id FROM paper_location WHERE stage = 'A') ORDER BY pl.paper_id", (ortsteil,))]
    pick = sorted(random.Random(seed).sample(ids, min(n, len(ids))))
    rows = []
    for i, pid in enumerate(pick, 1):
        p = list(db.execute("SELECT reference, date, paper_type, name, web FROM paper WHERE id = ?", (pid,)).fetchone())
        titel, p[3] = p[3], _maske(db)(p[3], p[0])
        locs = [(_maske(db)(l[0], p[0]), *l[1:3], _maske(db).ausschnitt(l[3], titel, p[0])) for l in db.execute(
            "SELECT COALESCE(l.street, l.description), pl.method, pl.confidence, pl.evidence "
            "FROM paper_location pl JOIN location l ON l.id = pl.location_id "
            "WHERE pl.paper_id = ? AND l.ortsteil = ?", (pid, ortsteil))]
        rows.append([i, *p, "; ".join(l[0] for l in locs), "; ".join(sorted({l[1] for l in locs})),
                     "; ".join(sorted({l[2] for l in locs})), "; ".join(sorted({l[3] for l in locs})),
                     "", ""])
    _write_tsv(out / "stichprobe_pruefung.tsv",
               ["nr", "drucksache", "datum", "vorlagenart", "titel", "link", "zuordnung", "methode",
                "konfidenz", "fundstelle", "urteil (richtig/falsch/unklar)", "anmerkung"], rows)


# --- „Aktuell in Köln“: kommende Sitzungen und neu eingereichte Vorlagen (index.json) --------------------------------

# Höchstzahlen je Karte; die Seite zeigt drei Sitzungen, nachdem der Browser vergangene nach dem Tag der
# Besucher:innen herausgefiltert hat. AKTUELL_SITZUNGEN zählt erst ab dem Tag nach dem Stichtag (_aktuell)
AKTUELL_SITZUNGEN, AKTUELL_VORLAGEN = 6, 5
# Felder je Karte, sonst keine (kein Sitzungsname, keine Frist, keine Namen von Personen); check._aktuell meldet jedes
# andere Feld. `hinweis` (Entscheidung 20.11.2026 (7) (b)) ist nur „verschoben“ (hinweis_sitzung, aus dem Namen
# abgeleitet, nicht der Name selbst) und fehlt ohne Hinweis
AKTUELL_FELDER = {"sitzungen": ("date", "time", "gremium", "hinweis", "web", "source_object"),
                  "vorlagen": ("reference", "date", "paper_type", "name", "area", "ort", "source_object")}
# Ort einer Vorlage ohne Ortsbezug, derselbe Wortlaut wie im Vorgang (site/app.js)
ORT_OHNE = "stadtweit / ohne Ortsbezug"


def _kalendertag(wert):
    """Kölner Kalendertag eines Zeitpunkts aus STAND.json (proc.local_day); None, wenn er fehlt oder unlesbar ist."""
    try:
        tag = proc.local_day(wert) if isinstance(wert, str) else None
        return date.fromisoformat(tag).isoformat() if tag else None
    except ValueError:
        return None


def _heimat(areas):
    """Gebiet je Vorlage zum Öffnen (Suche und „Aktuell in Köln“): das erste Gebiet in der Reihenfolge von export_all
    (Stadtteile, Stadtbezirke ohne genaueren Ort, Jahre ohne Ortsbezug), nie „gesamt“; eine Vorlage in keinem dieser
    Gebiete fehlt."""
    home = {}
    for key, ids in areas.items():
        if key != "gesamt":
            for pid in ids:
                home.setdefault(pid, key)
    return home


def _aktuell(cache, home, ortsname, meetings, heute, stand):
    """„Aktuell in Köln“ für das Startfenster (index.json `aktuell`, Entscheidung 19.11.2026 (1) (E)), nur aus dem, was
    der Export schon hat (Vorlagen aus `cache`, Sitzungen aus _meetings), ohne weitere Anfrage. `home`: Gebiet je
    Vorlage (_heimat), `ortsname`: kurzer Name je Gebiet, `heute`: Kölner Kalendertag des Abrufs der Vorlagen
    (proc.local_day von retrieved_at der Quelle config.QUELLE_OPARL), `stand`: Inhalt von STAND.json.
    - `sitzungen` („Kommende Sitzungen“): Stichtag ist der spätere der Kölner Tage `heute` und der letzten regulären
      Aktualisierung der Sitzungen (STAND.json `meetings`, _kalendertag; unlesbar oder fehlend: `heute`). Beide
      Zeitpunkte liegen vor dem Export, der spätere grenzt vergangene Sitzungen am engsten ab; ist nur die Liste der
      Vorlagen ausgesetzt, bleibt ihr Zeitpunkt stehen, die Sitzungen werden aber weiter aktualisiert. Sitzungen ab
      dem Stichtag ohne abgesagte (OParl `cancelled` oder, seit der Entscheidung 20.11.2026 (7) (b), Hinweis
      „abgesagt“ aus dem Namen, hinweis_sitzung; seit der Entscheidung 21.11.2026 (1) (c) (9) über absage, dieselbe
      Regel wie termine.ics und audit_zeit.tsv: Sie gelten nicht als nächste Sitzung und belegen keinen Platz), nach
      Tag und Uhrzeit; eine Sitzung ohne Uhrzeit (00:00 Uhr in Köln, _meetings) steht hinter denen mit Uhrzeit am
      selben Tag, sonst gilt die Reihenfolge von _meetings. Alle Sitzungen am
      Stichtag und dazu höchstens AKTUELL_SITZUNGEN spätere: Der nächtliche Lauf beginnt um 22:10 Uhr UTC, im Winter
      also um 23:10 Uhr Kölner Zeit, der Stichtag ist dann der Abend des Laufs. Seine Sitzungen sind vergangen, sobald
      Besucher:innen die Seite am nächsten Tag öffnen; zählten sie mit, könnten sie alle Plätze belegen, und die Karte
      bliebe nach dem Filter im Browser leer. Je Sitzung nur die Felder aus AKTUELL_FELDER (`date`, `time`,
      `gremium`, `hinweis`, `web`, `source_object`; `hinweis` nur „verschoben“ und nur, wenn _meetings ihn setzt):
      kein Sitzungsname, keine Frist (die 21 Tage stammen aus den Bonner Regeln), keine Namen von Personen.
      Vergangene Sitzungen filtert zusätzlich der Browser nach dem Tag der Besucher:innen.
    - `vorlagen` („Neu eingereicht“): Vorlagen aller Arten mit Datum bis `heute`, die neuesten zuerst (Datum, bei
      gleichem Datum die Drucksache absteigend als Text); höchstens AKTUELL_VORLAGEN. Je Vorlage nur die Felder aus
      AKTUELL_FELDER: `reference`, `date`, `paper_type`, `name` (Titel aus `cache`, maskiert wie in Liste und Suche),
      `area` (Gebiet zum Öffnen wie in suche.json, nie „gesamt“; None, wenn die Vorlage in keinem Gebiet steht), `ort`
      (kurzer Name dieses Gebiets: Stadtteil, „Stadtbezirk …“ oder ORT_OHNE; ohne Gebiet None) und `source_object`.
    Eine Karte fehlt, wenn ihre Liste ausgesetzt oder nicht aktualisiert ist: `sitzungen`, wenn „meetings“ in
    _abruf_ausgesetzt oder _abruf_warnungen steht oder _abruf_fehler gilt; `vorlagen`, wenn „papers“ in
    _abruf_ausgesetzt steht oder _abruf_fehler gilt. Eine Karte ohne Eintrag fehlt ebenso (Entscheidung 19.11.2026 (1)
    (F): ein Block ohne Daten fehlt). Fehlen beide Karten, in der Kartenvorschau (STAND.json `vorschau`) und ohne
    Vorlagen: None, index.json hat dann keinen Schlüssel `aktuell`."""
    if stand.get("vorschau") or not cache:
        return None
    fehler, ausgesetzt = _abruf_fehler(stand), _abruf_ausgesetzt(stand)
    karten = {}
    if not (fehler or "meetings" in ausgesetzt or "meetings" in _abruf_warnungen(stand)):
        tag = max(heute, _kalendertag(stand.get("meetings")) or heute)
        kommend = sorted((m for m in meetings if m["date"] >= tag and not absage(m)),
                         key=lambda m: (m["date"], m["time"] is None, m["time"] or ""))
        am_tag = sum(m["date"] == tag for m in kommend)   # stehen vorn: kein früherer Tag in `kommend`
        karten["sitzungen"] = [{k: m[k] for k in AKTUELL_FELDER["sitzungen"] if k in m}
                               for m in kommend[:am_tag + AKTUELL_SITZUNGEN]]
    if not (fehler or "papers" in ausgesetzt):
        neu = sorted(((pid, p) for pid, p in cache.items() if p["date"] and p["date"][:10] <= heute),
                     key=lambda x: (x[1]["date"], x[1]["reference"] or ""), reverse=True)
        mit_gebiet = [{**p, "area": home.get(pid), "ort": ortsname.get(home.get(pid))}
                      for pid, p in neu[:AKTUELL_VORLAGEN]]
        karten["vorlagen"] = [{k: p[k] for k in AKTUELL_FELDER["vorlagen"]} for p in mit_gebiet]
    karten = {k: v for k, v in karten.items() if v}
    return karten or None


# --- Suche über ganz Köln: Themen und Parteien -------------------------------------------------------

def _search_index(cache, areas, names, sources=None):
    """Kompakter Index aller Vorlagen für die Suche über ganz Köln. Je Zeile: Drucksache, Titel, Datum,
    Vorlagenart, Stand, Gebiet (zum Öffnen), Themen, eigene Parteien, Parteien der übergeordneten Vorlage
    (z. B. Stellungnahme der Verwaltung zu einem Antrag). meta.sources: Quellen mit Lizenz und Namensnennung wie in
    den Gebietsdateien (ohne Abrufzeit, Runde 19b); die Seite liest meta nicht."""
    home = _heimat(areas)
    by_ref = {p["reference"]: p for p in cache.values()}
    party_list = sorted({x for p in cache.values() for x in p["parties"]})
    area_list = sorted(set(home.values()))
    types = sorted({p["paper_type"] for p in cache.values() if p["paper_type"]})
    theme_ids = [k for k, _ in topics.THEMES]
    aemter = sorted({p["amt"] for p in cache.values() if p["amt"]})
    gremien = sorted({c["gremium"] for p in cache.values() for c in p["process"] if c["gremium"]})
    rows = []
    for pid, p in sorted(cache.items(), key=lambda x: (x[1]["date"] or "", x[1]["reference"]), reverse=True):
        related = {x for s in p["superordinated"] for x in (by_ref.get(s["reference"]) or {}).get("parties", [])}
        rows.append([p["reference"], p["name"], p["date"], types.index(p["paper_type"]) if p["paper_type"] else -1,
                     proc.STAENDE.index(p["stand"]), area_list.index(home[pid]) if pid in home else -1,
                     [theme_ids.index(t["theme"]) for t in p["themes"]],
                     [party_list.index(x) for x in p["parties"]],
                     [party_list.index(x) for x in sorted(related - set(p["parties"]))],
                     aemter.index(p["amt"]) if p["amt"] else -1,
                     sorted({gremien.index(c["gremium"]) for c in p["process"] if c["gremium"]})])
    return {"meta": {**({"sources": sources} if sources is not None else {}),
                     "note": "Themen und Parteien sind abgeleitet (siehe pipeline/topics.py); Spalten: "
                             "Drucksache, Titel, Datum, Vorlagenart, Stand, Gebiet, Themen, Parteien, "
                             "Parteien der übergeordneten Vorlage, federführendes Amt, beratende Gremien"},
            "themes": [{"id": k, "label": v} for k, v in topics.THEMES], "parties": party_list,
            "areas": [{"key": k, "name": names[k]} for k in area_list], "types": types, "stands": list(proc.STAENDE),
            "aemter": aemter, "gremien": gremien, "rows": rows}


# Federführung und Zuordnung zur Ämtertabelle je Vorlage mit Federführung (ohne Titel; „angabe“ ist der Name der
# Organisation aus underDirectionOf bzw. die Kennung aus dem Kopf der Vorlage, „plan_geprueft“ der Tag der letzten
# Prüfung des Plans, „plan_fundstelle“ die Stelle im Plan)
FEDERFUEHRUNG_AUDIT = ["drucksache", "datum", "vorlagenart", "methode", "angabe", "abgleich", "methode_abgleich",
                       "plan_stand", "plan_geprueft", "kennung", "dezernat", "dienststelle", "plan_fundstelle",
                       "pruefstatus"]


def federfuehrung_audit_rows(papers):
    rows = []
    for p in papers:
        for r in p["responsibility"]:
            a = r.get("aemtertabelle")
            if r.get("kind") != "federfuehrend" or a is None:
                continue
            rows.append([p["reference"], p["date"] or "", p["paper_type"] or "", r.get("method") or "",
                         r.get("kennung") or r.get("name") or "", a["status"], a.get("methode") or "",
                         a.get("stand") or "", a.get("geprueft") or "", a.get("kennung", ""),
                         a.get("dezernat_label", ""), a.get("label", ""),
                         a.get("fundstelle", ""), "ungeprüft"])
    return rows


def federfuehrung_zeile(papers):
    """Abdeckung im Log: Vorlagen mit Federführung (underDirectionOf oder Kennung) und das Ergebnis des Abgleichs mit
    der Ämtertabelle je Status (aemter.STATUS)."""
    status = [r["aemtertabelle"]["status"] for p in papers for r in p["responsibility"]
              if r.get("kind") == "federfuehrend" and r.get("aemtertabelle")]
    zugeordnet = sum(s in aemter.ZUGEORDNET for s in status)
    je = ", ".join(f"{s} {status.count(s)}" for s in aemter.STATUS if status.count(s))
    return (f"Federführung: {len(status)} Angaben bei {len(papers)} Vorlagen, davon {zugeordnet} der Ämtertabelle "
            f"zugeordnet" + (f" ({je})" if je else ""))


THEME_AUDIT = ["drucksache", "titel", "thema", "methode", "fundstelle", "konfidenz", "pruefstatus"]


def theme_audit_rows(papers):
    label = dict(topics.THEMES)
    return [[p["reference"], p["name"], label[t["theme"]], t["method"], t["evidence"], t["confidence"], "ungeprüft"]
            for p in papers for t in p["themes"]] + \
           [[p["reference"], p["name"], "", "", "", "", "ohne Thema"] for p in papers if not p["themes"]]


# --- Zeitleiste: Aggregate je Monat, Sitzungen, Wahlperioden --------------------------------------

def _months(first, last):
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _time_index(db, areas, cache):
    """Monatszählungen je Gebiet für zwei Zeitdimensionen: Datum der Vorlage (belegt) und
    Sitzungsdatum der Beratungen (abgeleitet über die Verknüpfung mit der Sitzung); dazu Sitzungen und Wahlperioden."""
    from collections import Counter
    meetings = _meetings(db)
    papers = list(cache.values())
    dates = [p["date"] for p in papers if p["date"]] + [m["date"] for m in meetings]
    months = _months(min(d for d in dates if d >= "2019")[:7], max(dates)[:7])
    pos = {m: i for i, m in enumerate(months)}
    types = [t for t, _ in Counter(p["paper_type"] for p in papers).most_common(6)]
    by_ref = {p["source_object"]: p for p in papers}

    def series(ids):
        vorlage = {t: [0] * len(months) for t in types + ["Sonstige"]}
        sitzung = [0] * len(months)
        for pid in ids:
            p = by_ref[pid]
            if p["date"] and p["date"][:7] in pos:
                vorlage[p["paper_type"] if p["paper_type"] in types else "Sonstige"][pos[p["date"][:7]]] += 1
            for st in p["steps"]:
                if st["typ"] in ("beratung", "entscheidung") and st.get("date") and st["date"][:7] in pos:
                    sitzung[pos[st["date"][:7]]] += 1
        return {"vorlage": {k: v for k, v in vorlage.items() if any(v)}, "sitzung": sitzung}

    terms = json.loads(config.LEGISLATIVE_TERMS.read_text()) if config.LEGISLATIVE_TERMS.exists() else []
    return {
        "meta": _meta(db, True, note="vorlage = Datum der Vorlage (OParl-API, belegt); sitzung = Sitzungsdatum "
                                "der Beratungen (über die Sitzung verknüpft, abgeleitet)"),
        "months": months, "categories": types + ["Sonstige"],
        "data_start": min(p["date"] for p in papers if p["date"]),
        "areas": {k: series(v) for k, v in areas.items()},
        "meetings": [{k: v for k, v in m.items() if k not in ("start", "end")} for m in meetings],
        "terms": [{"name": t["name"], "start": t.get("startDate"), "end": t.get("endDate"),
                   "source_object": t["id"]} for t in terms if (t.get("endDate") or "9999") >= "2014"],
    }


def _nominativ(name):
    """„Städtebau- und Gestaltungsbeirates“ → „…beirat“, „Ausschusses“ → „Ausschuss“ (Sitzungsnamen im Genitiv)."""
    name = re.sub(r"(rat)es\b", r"\1", name, flags=re.I)
    return re.sub(r"(schuss)es\b", r"\1", name, flags=re.I)


def _schluessel(name):
    """Strenger Vergleich von Gremiennamen: Leerraum, Komma, Binde- und Gedankenstrich als ein Leerzeichen, „Kinder-,
    Jugend“ wie „Kinder, Jugend“ (der einzige Vergleich bis zum 16.11.2026; erste Stufe von gremium_der_sitzung)."""
    return re.sub(r"[\s,\-–]+", " ", name or "").strip().lower()


def gremien_index(names):
    """Namen der Organisationen (`names`: OParl-Kennung → Name) für gremium_der_sitzung: je strengem Schlüssel
    (_schluessel) ein Name, bei gleichem Schlüssel wie bisher der in der Sortierung letzte; je breitem Schlüssel
    (ausschuesse.schluessel: zusätzlich ohne das Wort „für“, Schrägstrich wie Komma) die strengen Schlüssel."""
    streng, breit = {}, {}
    for n in sorted(names.values(), key=str):
        streng[_schluessel(n)] = n
        if ausschuesse.schluessel(n):
            breit.setdefault(ausschuesse.schluessel(n), set()).add(_schluessel(n))
    return streng, breit


# Vorspann eines Sitzungsnamens vor dem Gremium: bis zum 20.11.2026 nur „Sitzung des“ bzw. „der“, auch mit
# „Gemeinsame“; seit der Entscheidung 20.11.2026 (2) (a) auch mit einer Ordnungszahl davor, wie die Positivliste der
# Maske sie in Sitzungsnamen kennt (maske._SITZUNG_BEKANNT: „2.“, „5“, „5,“, „5..“), mit „Sondersitzung“ und mit
# „(konstituierende)“ oder „Konstituierende“ („2. Sondersitzung des Unterausschusses …“, „3. Gemeinsame Sondersitzung
# des …“, „1. (konstituierende) Sitzung der …“). Vorher war das Gremium bei einem solchen Namen der ganze Name, und die
# Maske kürzte darin die Ordnungszahl (Lauf nach dem Zusammenführen von #40: ein Gremium)
_VORSPANN_SITZUNG = re.compile(r"^(?:\d{1,3}(?:\.\.?|,)?\s?)?(?:Gemeinsame |\(konstituierende\) |Konstituierende )?"
                               r"(?:Sonders|S)itzung (?:des|der) ")
# Zusatz zum Stand der Sitzung am Ende der ersten Zeile eines Sitzungsnamens, hinter „ - “ oder „ – “ (Entscheidung
# 20.11.2026 (4) (b)), nur aus einer festen Liste: „Sitzung fällt aus“, „fällt aus“, „Sitzung entfällt“, „entfällt“,
# „Sitzung enfällt“ und „enfällt“ (Schreibweise der Quelle), „abgesagt“, dazu „vertagt“ und „verschoben“ samt dem Rest
# der Zeile, wenn das Wort dort endet (\b: „vertagt auf einen späteren Zeitpunkt“, „vertagt.“, „verschoben, neuer
# Termin folgt“; „vertagte Sitzung“ bleibt); dahinter nur Leerraum, „!“, „-“ oder „–“ („- Sitzung fällt aus -“). Groß-
# und Kleinschreibung wie in der Liste. Anlass: Im Lauf 57 trugen drei Gremien aus Sitzungsnamen einen solchen Zusatz,
# zwei davon neben demselben Gremium ohne Zusatz (TECHNIK.md, 20.11.2026 (4)). Ein anderes Wort hinter „ - “ bleibt
# Teil des Gremiums (keine allgemeine Kürzung hinter „ - “), ebenso ein Bindestrich ohne Leerraum davor
# („Beispiel-Museum“)
_ZUSATZ_STAND = re.compile(r"\s+[-–]\s+(?:(?:Sitzung )?(?:fällt aus|entfällt|enfällt)|abgesagt"
                           r"|(?:vertagt|verschoben)\b.*)[\s!\-–]*$")
# Hinweis zum Stand einer Sitzung aus ihrem Namen (Entscheidung 20.11.2026 (7) (b), Anlass 20.11.2026 (6) (b)): Die
# Stadt setzt OParl `cancelled` bei keiner Sitzung (Lauf 58: 0 von 3 362); dass eine Sitzung ausfällt oder verschoben
# ist, steht nur im Namen. Feste Wortliste, gesucht im ganzen Namen nach der Maske (alle Zeilen, an jeder Stelle), Groß-
# und Kleinschreibung gleich, nur ganze Wörter (davor und dahinter kein Buchstabe, keine Ziffer und kein „_“):
# - „abgesagt“: „fällt aus“ (Leerraum dazwischen beliebig), „entfällt“, „enfällt“ (Schreibweise der Quelle), „abgesagt“;
# - sonst „verschoben“: „verschoben“, „vertagt“.
# „abgesagt“ geht vor, auch wenn der Name daneben „verschoben“ oder „vertagt“ nennt. Andere Formen („abgesagte“,
# „verschobene“, „vertagte“, „gefällt aus“, „fällt ausnahmsweise“) und andere Wörter („verlegt“, „ausgefallen“) zählen
# nicht. Grenzen der Liste: Sie liest keine Verneinung und nicht, worauf sich das Wort bezieht („TOP 3 entfällt“ zählt
# wie „Sitzung entfällt“). Vor dem Vergleich Unicode-Form NFC (ein zerlegtes „ä“ gilt wie ein ganzes; anders als
# _ZUSATZ_STAND, das nur die Form NFC kennt)
_HINWEIS_ABGESAGT = re.compile(r"(?<!\w)(?:fällt\s+aus|entfällt|enfällt|abgesagt)(?!\w)", re.I)
_HINWEIS_VERSCHOBEN = re.compile(r"(?<!\w)(?:verschoben|vertagt)(?!\w)", re.I)


def hinweis_sitzung(name):
    """Hinweis zum Stand aus dem Namen einer Sitzung nach der festen Wortliste (_HINWEIS_ABGESAGT vor
    _HINWEIS_VERSCHOBEN): „abgesagt“, „verschoben“ oder None (kein Wort der Liste, kein Name). `name`: der Name nach der
    Maske (Maske.sitzungsname), wie er in zeit.json steht. Eine Regel für _meetings (zeit.json, „Aktuell in Köln“ in
    index.json, Zeile im Log) und check.hinweise_sitzungen. Unabhängig von OParl `cancelled` und vom Gremium: Auch eine
    Sitzung mit Organisation erhält den Hinweis aus ihrem Namen."""
    if not isinstance(name, str):
        return None
    text = unicodedata.normalize("NFC", name)
    if _HINWEIS_ABGESAGT.search(text):
        return "abgesagt"
    if _HINWEIS_VERSCHOBEN.search(text):
        return "verschoben"
    return None


def zeile_hinweise(meetings):
    """Zeile im Log von `export`, nur Zahlen (Entscheidung 20.11.2026 (7) (b)): Sitzungen aus _meetings (alle in
    zeit.json, auch vergangene und abgesagte) je Hinweis zum Stand aus dem Namen (hinweis_sitzung)."""
    n = {h: sum(m.get("hinweis") == h for m in meetings) for h in ("abgesagt", "verschoben")}
    return f"Sitzungen mit Hinweis zum Stand aus dem Namen: abgesagt {n['abgesagt']}, verschoben {n['verschoben']}"


# Grund einer Absage (absage) in Worten, für audit_zeit.tsv (time_audit_rows) und verifikation_zeit.tsv
# (verify.verify_time)
ABSAGE_TEXT = {"oparl": "abgesagt laut OParl (cancelled)", "name": "laut Sitzungsnamen abgesagt"}
# Rangfolge je Gremium und Tag (sitzungstage): eine Sitzung, die nicht abgesagt ist, vor einer Absage laut OParl, diese
# vor einer Absage laut Namen
_RANG_ABSAGE = {None: 0, "oparl": 1, "name": 2}


def absage(m):
    """Gilt eine Sitzung als abgesagt, und warum (Entscheidung 21.11.2026 (1) (c) (9))? „oparl“ bei OParl `cancelled`,
    sonst „name“ bei Hinweis „abgesagt“ aus dem Namen (`hinweis`, hinweis_sitzung), sonst None. `m`: eine Sitzung aus
    _meetings oder aus zeit.json (`meetings`). Der Hinweis „verschoben“ ist keine Absage. Eine Regel für _aktuell
    („Aktuell in Köln“), time_audit_rows (audit_zeit.tsv), publish.write_calendar (termine.ics), verify.verify_time und
    check.absagen_kalender; die Stadt setzt OParl `cancelled` bei keiner Sitzung (Lauf 62: 0 von 3 362), eine Absage
    steht in Köln nur im Namen."""
    if m.get("cancelled"):
        return "oparl"
    if m.get("hinweis") == "abgesagt":
        return "name"
    return None


def sitzungstage(meetings):
    """Sitzungen je Gremium und Kölner Tag für den Abgleich mit Beratungsdaten (time_audit_rows, verify.verify_time):
    {(gremium, date): None, wenn an diesem Tag mindestens eine Sitzung des Gremiums nicht abgesagt ist, sonst der Grund
    der Absage (absage; „oparl“ vor „name“, wenn beide vorkommen)}. Ein Paar ohne Eintrag: keine Sitzung des Gremiums
    an diesem Tag in den Sitzungen der OParl-API."""
    tage = {}
    for m in meetings:
        k, grund = (m["gremium"], m["date"]), absage(m)
        tage[k] = min(tage.get(k, grund), grund, key=_RANG_ABSAGE.get)
    return tage


def _gekuerzt(text):
    """Sitzungsname oder dessen erste Zeile ohne Vorspann (_VORSPANN_SITZUNG), ohne Zusatz zum Stand (_ZUSATZ_STAND),
    im Nominativ (_nominativ); für gremium_der_sitzung."""
    return _nominativ(_ZUSATZ_STAND.sub("", _VORSPANN_SITZUNG.sub("", text)))


def _bekannte_schreibweise(name, streng, breit):
    """Schreibweise eines bekannten Gremiums für `name` (gremium_der_sitzung): bei gleichem strengem Schlüssel, sonst
    bei gleichem breitem Schlüssel, wenn er genau ein Gremium ergibt; sonst None."""
    if _schluessel(name) in streng:
        return streng[_schluessel(name)] or "unbekannt"
    kandidaten = breit.get(ausschuesse.schluessel(name)) or ()
    return streng[next(iter(kandidaten))] if len(kandidaten) == 1 else None


def gremium_der_sitzung(m, names, index=None):
    """Gremium einer Sitzung: aus der Organisation (unverändert); fehlt sie (z. B. neue Wahlperiode, Sitzung am
    25.11.2026), aus dem Sitzungsnamen. Reihenfolge (Entscheidung 20.11.2026 (4) (b)): die erste Zeile mit Text
    (str.splitlines, ohne Leerraum am Ende; eine zweite Zeile wie ein Hinweis, dass die Sitzung verschoben ist, fällt
    weg), dann ohne Vorspann (_VORSPANN_SITZUNG, am Anfang dieser Zeile) und ohne Zusatz zum Stand (_ZUSATZ_STAND, an
    ihrem Ende), dann im Nominativ (_nominativ), zuletzt in der Schreibweise eines bekannten Gremiums. Weil Vorspann
    und Zusatz vor dem Vergleich wegfallen, findet „Beispielbeirat - Sitzung enfällt“ die Schreibweise
    „Beispielbeirat“; der Name der Sitzung selbst bleibt davon unberührt (_meetings, _paper_detail). Hat der Name
    mehrere Zeilen mit Text, gilt vor dem Treffer der ersten Zeile der Treffer des ganzen Namens, ebenso ohne Vorspann
    und ohne Zusatz am Ende (Nachprüfung des Pull Request; bis ab3fff9 zählte nur der ganze Name ohne Vorspann, und
    beide Schlüssel werten einen Zeilenumbruch wie ein Leerzeichen): Dann lag der Zeilenumbruch im Namen eines
    bekannten Gremiums (erfunden: „Sitzung der Bezirksvertretung“ und „Probedorf“ auf der zweiten Zeile ergibt
    „Bezirksvertretung Probedorf“, nicht „Bezirksvertretung“). Ein Hinweis auf der zweiten Zeile trifft dabei nur,
    wenn der ganze Name im strengen oder breiten Schlüssel dem Namen einer Organisation gleicht; Text der zweiten Zeile
    kommt so nie ins Gremium, nur die Schreibweise einer Organisation. Die Schreibweise eines
    bekannten Gremiums in zwei Stufen (gremien_index, _bekannte_schreibweise): zuerst bei gleichem strengem Schlüssel
    (ohne Satzzeichen; wie bis zum 16.11.2026, bisherige Treffer bleiben), sonst bei gleichem breitem Schlüssel
    (ausschuesse.schluessel, auch ohne „für“ und mit „/“ wie Komma: die Zuständigkeitsordnung schreibt „Ausschuss
    Klima, Umwelt und Grün“ und „Ausschuss für Klima, Umwelt und Grün“), aber nur, wenn er genau ein Gremium ergibt.
    Stehen Gremien der alten und der neuen Wahlperiode mit und ohne „für“ nebeneinander, gewinnt so die genau passende
    Schreibweise; ist der breite Schlüssel mehrdeutig, bleibt der Name aus der Sitzung in der gekürzten Form der ersten
    Zeile (Prüfung des Abgleichs vom 16.11.2026)."""
    org = (m.get("organization") or [None])[0]
    if names.get(org):
        return names[org]
    roh = m.get("name") or ""
    zeilen = [z.rstrip() for z in roh.splitlines() if z.strip()]
    streng, breit = index if index is not None else gremien_index(names)
    ganz = _bekannte_schreibweise(_gekuerzt(roh), streng, breit) if len(zeilen) > 1 else None
    name = _gekuerzt(zeilen[0] if zeilen else "")
    return ganz or _bekannte_schreibweise(name, streng, breit) or name or "unbekannt"


def gremium_aus_namen(gremium, organisationen):
    """Stammt das Gremium einer Sitzung aus ihrem Namen (letzte Stufe von gremium_der_sitzung)? Ja, wenn es weder der
    Name einer Organisation der Datenbank ist (`organisationen`: alle Namen aus `organization`; auch die Schreibweise
    eines bekannten Gremiums, auf die gremium_der_sitzung einen Namen abbildet) noch der Platzhalter „unbekannt“ einer
    Sitzung ohne Namen. Eine Regel für _meetings (Maske, Zeile im Log) und check (_sitzungen, _aktuell)."""
    return bool(gremium) and gremium != "unbekannt" and gremium not in organisationen


def zeile_sitzungsnamen(zahl):
    """Zeile im Log von `export`, nur Zahlen (Entscheidung 19.11.2026 (3) (c)): Sitzungen aus _meetings, deren Gremium
    aus dem Sitzungsnamen stammt (gremium_aus_namen), und Sitzungen, deren Name oder Gremium die Maske geändert hat
    (Maske.sitzungsname). `zahl`: von _meetings gefüllt."""
    return (f"Sitzungen: Gremium aus dem Sitzungsnamen {zahl.get('gremium_aus_namen', 0)}, "
            f"Namen oder Gremien von der Maske geändert {zahl.get('maske', 0)}")


def _meetings(db, zahl=None):
    """Sitzungen der städtischen OParl-API (auch künftige, als Termin belegt). Der Name jeder Sitzung läuft durch die
    Titelmaske, ebenso ein Gremium, das aus dem Namen stammt (Maske.sitzungsname, gremium_aus_namen; Entscheidung
    19.11.2026 (3) (c)): Das Gremium aus dem Namen ist dessen erste Zeile ohne Vorspann und ohne Zusatz zum Stand
    (gremium_der_sitzung, seit der Entscheidung 20.11.2026 (4) (b); vorher der ganze Name ohne Vorspann), und der ganze
    Name steht in zeit.json und in der Beschreibung in termine.ics daneben; bliebe er ungekürzt, stünde dieselbe
    Hausnummer dort weiter. Bis zur Entscheidung 19.11.2026 (3) (c) nur bei Sitzungen, in denen eine Vorlage der Maske
    beraten wird (Maske.sitzungen; Offen (9) der Nachprüfung der dritten Korrektur). check._sitzungen und
    check._aktuell prüfen mit derselben Regel (Maske.sitzungsname_offen). Das Gremium entsteht aus dem ungekürzten
    Namen und läuft, wenn es aus dem Namen stammt, selbst durch die Maske: So findet gremium_der_sitzung die
    Schreibweise eines bekannten Gremiums auch dann, wenn die Maske eine Zahl im Namen kürzt (der Name einer
    Organisation bleibt ungeprüft, wie bisher; vorher entstand das Gremium aus dem maskierten Namen). Mit `zahl` (dict)
    zählt _meetings für zeile_sitzungsnamen: `gremium_aus_namen` und `maske` (Name oder Gremium geändert). `hinweis`
    (Entscheidung 20.11.2026 (7) (b)): „abgesagt“ oder „verschoben“ aus dem Namen nach der Maske (hinweis_sitzung),
    neben `cancelled`; ohne Wort der Liste fehlt das Feld."""
    if not config.MEETINGS.exists():
        return []
    names = dict(db.execute("SELECT id, name FROM organization"))
    organisationen = {n for n in names.values() if n}
    index = gremien_index(names)
    mk = _maske(db)
    out = []
    for m in json.loads(config.MEETINGS.read_text()):
        if not m.get("start"):
            continue
        # Uhrzeit in Kölner Zeit zum selben Zeitpunkt wie das Datum; 00:00 Uhr in Köln heißt: keine Uhrzeit angegeben
        time = proc.local_time(m["start"])
        time = None if time == "00:00" else time
        gremium = gremium_der_sitzung(m, names, index)
        name = mk.sitzungsname(m.get("name"))
        geaendert = name != m.get("name")
        m = {**m, "name": name}
        aus_namen = gremium_aus_namen(gremium, organisationen)
        if aus_namen:
            maskiert = mk.sitzungsname(gremium)
            geaendert, gremium = geaendert or maskiert != gremium, maskiert
        if zahl is not None:
            zahl["gremium_aus_namen"] = zahl.get("gremium_aus_namen", 0) + aus_namen
            zahl["maske"] = zahl.get("maske", 0) + geaendert
        hinweis = hinweis_sitzung(m.get("name"))   # aus dem Namen nach der Maske; ohne Hinweis kein Feld
        out.append({"date": proc.local_day(m["start"]), "time": time, "gremium": gremium,
                    "name": m.get("name"), "cancelled": bool(m.get("cancelled")),
                    **({"hinweis": hinweis} if hinweis else {}), "state": m.get("meetingState"),
                    "web": m.get("web"), "invitation": m.get("invitation"),
                    "agenda_items": m.get("agenda_items") or 0, "start": m["start"], "end": m.get("end"),
                    "source_object": m["id"]})
    return sorted(out, key=lambda x: x["date"])


def zeile_beginn(meetings):
    """Zeile im Log von `export`, nur Zahlen (Entscheidung 19.11.2026 (1) (D)): Sitzungen aus _meetings nach der Form
    ihres Beginns in der Quelle. Ob SessionNet „Z“, einen Versatz wie „+01:00“ oder Zeiten ohne Zeitzone liefert, ist
    nicht gemessen; der nächste Lauf zeigt so, in welcher Form die Kölner Daten den Beginn tragen. Ob ein Versatz der
    Kölner Zeit entspricht (Uhrzeit unverändert) oder nicht (Uhrzeit umgerechnet), zeigt die Zeile nicht; ein Beginn
    ohne Zeitzone ändert nur termine.ics, nicht zeit.json."""
    n = {"mit Z": 0, "mit Versatz": 0, "ohne Zeitzone": 0, "nur Datum": 0}
    for m in meetings:
        s = m["start"]
        n["nur Datum" if len(s) <= 10 else "mit Z" if s.endswith("Z")
          else "mit Versatz" if datetime.fromisoformat(s).tzinfo else "ohne Zeitzone"] += 1
    return "Sitzungen nach Form des Beginns: " + ", ".join(f"{k} {v}" for k, v in n.items())


# --- Prozessebene: typische Wege je Vorlagenart ----------------------------------------------------

def _kennungen(db):
    """Kennung der Beratung je Eintrag (intern, nicht im Export) je Vorlage ({Vorlage: [Kennung, …]}), in derselben
    Reihenfolge wie p["process"] (_paper_detail: ORDER BY position); für _paths und check.stand_und_ende, damit beide
    dieselben Enden ermitteln."""
    kennungen = {}
    for pid, kennung in db.execute("SELECT paper_id, id FROM consultation ORDER BY paper_id, position"):
        kennungen.setdefault(pid, []).append(kennung)
    return kennungen


def _paths(db, cache, top=12):
    from collections import Counter, defaultdict
    by_type = defaultdict(Counter)
    totals = Counter()
    # Das Ende des Weges folgt dem Stand, je Kennung ihrem Eintrag, der für den Stand zählt (proc.path_key,
    # Entscheidungen 17.11.2026 (15) (A), 18.11.2026 (1) und (2))
    kennungen = _kennungen(db)
    for pid, p in cache.items():
        by_type[p["paper_type"]][proc.path_key(p, kennungen.get(pid, []))] += 1
        totals[p["paper_type"]] += 1
    out = []
    for ptype, n in totals.most_common():
        paths = [{"stations": list(st), "final": fin, "final_kind": kind, "count": c}
                 for (st, fin, kind), c in by_type[ptype].most_common(top)]
        out.append({"paper_type": ptype, "count": n, "distinct_paths": len(by_type[ptype]),
                    "paths": paths})
    return {"meta": _meta(db, True, note="Weg = Folge der Beratungen (Gremium, Rolle) laut OParl-API; Ende = "
                                   "Ergebnis der entscheidenden Beratung (Ratsinformationssystem) oder Stand"),
            "types": out}


PROCESS_AUDIT = ["drucksache", "schritt", "bezeichnung", "status", "datum", "datum_status", "quelle",
                 "fundstelle", "pruefvermerk"]


PLAN_AUDIT = ["drucksache", "titel", "plannummer", "fundstelle", "treffer", "geltungsbereich", "inkraft_seit",
              "ortsteile", "konfidenz", "zurueckgestellt", "pruefstatus"]
_PLANS = None


def _plans():
    global _PLANS
    if _PLANS is None:
        from .plans import Plans
        _PLANS = Plans()
    return _PLANS


def _plan_entry(nr, evidence, match):
    hits = _plans().classify(nr)[1]
    return {"nr": nr, "evidence": evidence, "match": match or "nicht_im_datensatz",
            "names": sorted({f["properties"]["name"] for f in hits}), "area": bool(hits)}


def plan_audit_rows(db, where="", args=()):
    """Je Plannummer im Titel (B3): Treffer im Datensatz der rechtskräftigen Pläne, berührte Ortsteile, Konfidenz
    und die Ortsbezüge aus dem Titel, die dem eindeutigen Plan weichen."""
    from .plans import CONFIDENCE
    out = []
    for ref, name, pid, nr, ev, match in db.execute(
            "SELECT p.reference, p.name, p.id, pp.plan_nr, pp.evidence, pp.match FROM paper_plan pp "
            f"JOIN paper p ON p.id = pp.paper_id {where} ORDER BY p.date DESC, p.reference", args):
        hits = _plans().classify(nr)[1]
        names = sorted({f["properties"]["name"] for f in hits})
        ortsteile = sorted({r[0] for n in names for r in db.execute(
            "SELECT l.ortsteil FROM paper_location pl JOIN location l ON l.id = pl.location_id "
            "WHERE pl.paper_id = ? AND pl.method = 'bebauungsplan' AND l.description = ?", (pid, f"Bebauungsplan {n}"))})
        mk = _maske(db)
        # zurückgestellte Ortsbezüge: jede Fundstelle im Zusammenhang des Titels und die zusammengesetzte Spalte noch
        # einmal als Ganzes (check prüft die Spalte als Ganzes; vorher konnte „… (strasse, Ehrenfeld); 2 Bäume“ einen
        # Befund ergeben, den die Maske nicht behob; Prüfung r20a, dritte Korrektur)
        back = mk("; ".join(f"{mk.ausschnitt(e, name, ref)} ({m}, {ot or 'ohne Ortsteil'})" for e, m, ot in db.execute(
            "SELECT DISTINCT pp.evidence, pp.method, l.ortsteil FROM plan_precedence pp JOIN location l ON l.id = pp.location_id "
            "WHERE pp.paper_id = ? ORDER BY 1, 3", (pid,))), ref)
        # Fundstelle wie der Titel maskiert (Text zwischen „Bebauungsplan“ und Plannummer; Prüfung r20a)
        out.append([ref, mk(name, ref), nr, mk.ausschnitt(ev, name, ref), match,
                    "; ".join(names) or "nicht im Datensatz",
                    "; ".join(sorted({f["properties"]["inkraft_seit"] or "" for f in hits})), "; ".join(ortsteile),
                    CONFIDENCE.get(match, "–"), back,
                    "ungeprüft" if hits else "kein rechtskräftiger Plan (Verfahren oder aufgehoben)"])
    return out


TIME_AUDIT = ["drucksache", "zeitdimension", "wert", "quelle", "status", "bemerkung"]


def time_audit_rows(papers, meetings):
    """Datumsabdeckung der Zeitleiste: woher stammt jedes Datum, und gibt es zum abgeleiteten
    Beratungsdatum eine Sitzung desselben Gremiums in der OParl-API der Stadt? Als Sitzung zählt nur eine, die nicht
    abgesagt ist (sitzungstage, absage; seit der Entscheidung 21.11.2026 (1) (c) (9) auch nicht laut Sitzungsnamen,
    vorher nur ohne OParl `cancelled`). Gibt es an dem Tag nur abgesagte Sitzungen des Gremiums, nennt die Bemerkung den
    Grund (ABSAGE_TEXT, getrennt nach OParl `cancelled` und Hinweis aus dem Namen; vorher „keine Sitzung …“)."""
    tage = sitzungstage(meetings)
    rows = []
    for p in papers:
        rows.append([p["reference"], "datum_vorlage", p["date"] or "", config.QUELLE_OPARL,
                     "belegt" if p["date"] else "unklar", "Bedeutung des Datums nicht dokumentiert"])
        for st in p["steps"]:
            if st["typ"] in ("beratung", "entscheidung") and st.get("role"):
                dim = f"beratung: {st['label']} ({st['role']})"
                if st.get("date"):
                    k = (st["label"], st["date"])
                    sitzung = "Sitzung des Gremiums an diesem Tag in der OParl-API der Stadt"
                    rows.append([p["reference"], dim, st["date"], config.QUELLE_SITZUNG, "abgeleitet",
                                 f"keine {sitzung}" if k not in tage
                                 else f"{sitzung}, {ABSAGE_TEXT[tage[k]]}" if tage[k] else sitzung])
                else:
                    rows.append([p["reference"], dim, "", "", "unklar", "Beratung ohne verknüpfte Sitzung"])
            elif st["typ"] == "folgevorlage":
                rows.append([p["reference"], f"folgevorlage: {st['reference']}", st.get("date") or "",
                             config.QUELLE_OPARL, "belegt" if st.get("date") else "unklar", st["label"]])
    return rows


def process_audit_rows(papers):
    rows = []
    for p in papers:
        for st in p["steps"]:
            ref = st.get("reference") or st.get("source_object") or p["source_object"]
            rows.append([p["reference"], st["typ"], st["label"] + (f" ({st['role']})" if st.get("role") else ""),
                         st["status"], st.get("date") or "", st.get("date_status") or "",
                         st.get("source") or "", ref if st["status"] in ("belegt", "abgeleitet") else
                         proc.NOTES.get(st.get("note"), ""), "ungeprüft"])
    return rows
