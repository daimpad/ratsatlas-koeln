"""Exporte für ganz Köln je Stadtteil, Stadtbezirk und Jahr (data/export/koeln, für die Webseite; wird bei der
Veröffentlichung erzeugt) und stadtweite Audits (data/export/audit_*.tsv). Jede Vorlage mit Prozesslinie, Akteuren und
Ortsbezügen samt Quelle. Bonner Zusatzthemen nur, wenn in config.ZUSATZTHEMEN freigegeben."""
import csv
import json
import random
import re
import shutil
import sqlite3
from datetime import date, datetime, timezone

from . import aemter, chat, config, dossier, flaechen, prozessbild, gebietszahlen, glossar, maske, plans, process as proc, prozessarten, publish, soll, topics
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
    process = db.execute(
        "SELECT c.position, c.role, c.authoritative, c.meeting_id, c.agenda_item_id, g.name AS gremium, "
        "m.name AS meeting, m.start_date, m.cancelled, a.number, a.result, a.public "
        "FROM consultation c LEFT JOIN organization g ON g.id = c.organization_id "
        "LEFT JOIN meeting m ON m.id = c.meeting_id LEFT JOIN agenda_item a ON a.id = c.agenda_item_id "
        "WHERE c.paper_id = ? ORDER BY c.position", (pid,)).fetchall()
    resp = db.execute(
        "SELECT r.kind, r.method, r.evidence, r.derived, o.label, o.name FROM paper_responsibility r "
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
    # Befund beheben). Ergebnisse je Tagesordnungspunkt und Sitzungsnamen je Sitzung (Offen (8) und (9) der Nachprüfung
    # der dritten Korrektur): Wird dort eine Vorlage der Maske beraten (Maske.tops, Maske.sitzungen), läuft der Text
    # bei jeder Vorlage, die ihn zeigt, mit deren Drucksache durch die Maske; die Kennung des Tagesordnungspunkts
    # bleibt intern (Datenmodell unverändert). Bei Ergebnissen gilt das für alle Punkte einer solchen Vorlage
    # (Maske.drucksache_ergebnisse, dieselbe Funktion in check): Derselbe Text auf einem zweiten Punkt blieb sonst
    # ungekürzt, und check meldete ihn im Feed der Vorlage als Befund, den die Maske nicht beheben konnte
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
        # der Status, die Zeile bleibt sonst wie zuvor
        "responsibility": [_mit_aemtertabelle({**dict(r), "evidence": m(r["evidence"], ref)}, p["date"]) for r in resp],
        "originators": fund(orig),
        "process": [{**{k: v for k, v in dict(r).items() if k != "agenda_item_id"},
                     "meeting": m(r["meeting"], m.sitzungen.get(r["meeting_id"])),
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
    d["stand"] = proc.stand(d)
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
    `underDirectionOf`, je mit dem Plan, der am Datum der Vorlage gilt. Andere Zeilen unverändert."""
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
                      "stadtteil_oder_bezirk", "konfidenz", "fundstelle", "urteil (richtig/teilweise/falsch)",
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
    Ortsbezug je Jahr; dazu index.json mit Zählungen für die Auswahl auf der Webseite."""
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
    areas, names = {}, {}

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
        names[f"ortsteil:{slug(name)}"] = name

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
    meetings = _meetings(db)
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
    # Freigaben für site/app.js (idx.meta.funktionen; ein fehlender Schlüssel gilt als aus). Die Strukturdaten stehen
    # erst mit Freigabe darin, damit index.json ohne sie unverändert bleibt (pipeline/strukturdaten_web.py)
    funktionen = {k: v for k, v in config.ZUSATZTHEMEN.items() if k != "strukturdaten" or v}
    _dump(out / "index.json", {"meta": _meta(db, stadt=config.STADT_NAME, seitenname=config.SEITENNAME,
                                             funktionen=funktionen,
                                             testdaten=bool(_stand().get("testdaten")),
                                             vorschau=bool(_stand().get("vorschau")),
                                             abruf_fehler=_abruf_fehler(_stand()),
                                             abruf_warnungen=_abruf_warnungen(_stand())), **index})
    db.close()
    print(f"{config.STADT_NAME}: {len(index['ortsteile'])} Stadtteile, {len(index['bezirke'])} Bezirke, "
          f"{len(years)} Jahre ohne Ortsbezug, {len(cache)} Vorlagen, {n_points} Punkte im GeoJSON, {n_shards} Dateien für den Assistenten → {out}")


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


# --- Suche über ganz Köln: Themen und Parteien -------------------------------------------------------

def _search_index(cache, areas, names, sources=None):
    """Kompakter Index aller Vorlagen für die Suche über ganz Köln. Je Zeile: Drucksache, Titel, Datum,
    Vorlagenart, Stand, Gebiet (zum Öffnen), Themen, eigene Parteien, Parteien der übergeordneten Vorlage
    (z. B. Stellungnahme der Verwaltung zu einem Antrag). meta.sources: Quellen mit Lizenz und Namensnennung wie in
    den Gebietsdateien (ohne Abrufzeit, Runde 19b); die Seite liest meta nicht."""
    home = {}
    for key, ids in areas.items():
        if key != "gesamt":
            for pid in ids:
                home.setdefault(pid, key)
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
# Organisation aus underDirectionOf bzw. die Kennung aus dem Kopf der Vorlage, „plan_fundstelle“ die Stelle im Plan)
FEDERFUEHRUNG_AUDIT = ["drucksache", "datum", "vorlagenart", "methode", "angabe", "abgleich", "methode_abgleich",
                       "plan_stand", "kennung", "dezernat", "dienststelle", "plan_fundstelle", "pruefstatus"]


def federfuehrung_audit_rows(papers):
    rows = []
    for p in papers:
        for r in p["responsibility"]:
            a = r.get("aemtertabelle")
            if r.get("kind") != "federfuehrend" or a is None:
                continue
            rows.append([p["reference"], p["date"] or "", p["paper_type"] or "", r.get("method") or "",
                         r.get("kennung") or r.get("name") or "", a["status"], a.get("methode") or "",
                         a.get("stand") or "", a.get("kennung", ""), a.get("dezernat_label", ""), a.get("label", ""),
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
    """Vergleich von Gremiennamen ohne Satzzeichen: „Kinder-, Jugend“ wie „Kinder, Jugend“."""
    return re.sub(r"[\s,\-–]+", " ", name or "").strip().lower()


def gremium_der_sitzung(m, names, bekannt=None):
    """Gremium einer Sitzung: aus der Organisation; fehlt sie (z. B. neue Wahlperiode, Sitzung am 25.11.2026), aus
    dem Sitzungsnamen, bei gleichem Namen ohne Satzzeichen in der Schreibweise des bekannten Gremiums."""
    org = (m.get("organization") or [None])[0]
    if names.get(org):
        return names[org]
    name = _nominativ(re.sub(r"^(Gemeinsame )?Sitzung (des|der) ", "", m.get("name") or ""))
    bekannt = bekannt if bekannt is not None else {_schluessel(n): n for n in sorted(names.values(), key=str)}
    return bekannt.get(_schluessel(name), name) or "unbekannt"


def _meetings(db):
    """Sitzungen der städtischen OParl-API (auch künftige, als Termin belegt). Wird in einer Sitzung eine Vorlage der
    Titelmaske beraten (Maske.sitzungen), läuft ihr Name durch die Maske, ebenso ein Gremium, das aus dem Namen stammt
    (Offen (9) der Nachprüfung der dritten Korrektur: zeit.json, termine.ics; check._sitzungen prüft das)."""
    if not config.MEETINGS.exists():
        return []
    names = dict(db.execute("SELECT id, name FROM organization"))
    bekannt = {_schluessel(n): n for n in sorted(names.values(), key=str)}
    mk = _maske(db)
    out = []
    for m in json.loads(config.MEETINGS.read_text()):
        if not m.get("start"):
            continue
        time = m["start"][11:16] if len(m["start"]) > 10 and m["start"][11:16] != "00:00" else None
        m = {**m, "name": mk(m.get("name"), mk.sitzungen.get(m.get("id")))}
        gremium = gremium_der_sitzung(m, names, bekannt)
        out.append({"date": proc.local_day(m["start"]), "time": time, "gremium": gremium,
                    "name": m.get("name"), "cancelled": bool(m.get("cancelled")), "state": m.get("meetingState"),
                    "web": m.get("web"), "invitation": m.get("invitation"),
                    "agenda_items": m.get("agenda_items") or 0, "start": m["start"], "end": m.get("end"),
                    "source_object": m["id"]})
    return sorted(out, key=lambda x: x["date"])


# --- Prozessebene: typische Wege je Vorlagenart ----------------------------------------------------

def _paths(db, cache, top=12):
    from collections import Counter, defaultdict
    by_type = defaultdict(Counter)
    totals = Counter()
    for p in cache.values():
        by_type[p["paper_type"]][proc.path_key(p)] += 1
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
    Beratungsdatum eine Sitzung desselben Gremiums in der OParl-API der Stadt?"""
    held = {(m["gremium"], m["date"]) for m in meetings if not m["cancelled"]}
    rows = []
    for p in papers:
        rows.append([p["reference"], "datum_vorlage", p["date"] or "", config.QUELLE_OPARL,
                     "belegt" if p["date"] else "unklar", "Bedeutung des Datums nicht dokumentiert"])
        for st in p["steps"]:
            if st["typ"] in ("beratung", "entscheidung") and st.get("role"):
                dim = f"beratung: {st['label']} ({st['role']})"
                if st.get("date"):
                    same = (st["label"], st["date"]) in held
                    rows.append([p["reference"], dim, st["date"], config.QUELLE_SITZUNG, "abgeleitet",
                                 "Sitzung des Gremiums an diesem Tag in der OParl-API der Stadt" if same
                                 else "keine Sitzung des Gremiums an diesem Tag in der OParl-API der Stadt"])
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
