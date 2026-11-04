"""Soll-Modell der Prozessebene: Verfahren nach Regelwerk und Abgleich mit den Beratungen (Ist).

Übernommen aus „Bonn entscheidet“ (anster2025/bonn-entscheidet, Commit 26641f7, MIT): Verfahrensmodell
(data/soll/verfahren.json), Zuständigkeitsordnung (data/soll/zustaendigkeitsordnung.json) und die Zuordnungsregeln
aus einordnung.py (assign). Eigene Ergänzungen und Korrekturen mit Belegen: data/soll/ergaenzungen.json.
Ein Vorgang umfasst alle Vorlagen einer Stammnummer (Drucksache ohne Zusatz „-NN XX“). Abweichungen zwischen
Soll und Ist sind Befunde, keine Bewertung."""
import collections
import copy
import csv
import json
import re
import sqlite3

from . import config

SOLL = config.ROOT / "data" / "soll"
SIDE = ("Stellungnahme der Verwaltung", "Änderungsantrag")
BAHN = {"Bezirksvertretungen": "bv", "Ratsgremien": "aus", "Rat": "rat"}  # Gremienart (OParl classification) → Bahn
BAULEIT_RE = re.compile(r"Bebauungsplan|Satzungsbeschluss|Aufstellungsbeschluss|Offenlage|"
                        r"Flächennutzungsplan|frühzeitige[nr]? (Öffentlichkeits)?[Bb]eteiligung", re.I)
BAULEIT_SICHER = re.compile(r"Bebauungsplan|Flächennutzungsplan(änderung)?\b.*(Aufstellung|"
                            r"Offenlage|Satzung|Beteiligung|Änderung)", re.I)
# Rechtsgrundlagen als Links (nach recht.py in bonn-entscheidet, MIT): Kurzform → (Name, Adresse)
_ORTSRECHT = "https://www.bonn.de/service-bieten/stadtpolitik-ortsrecht/ortsrecht/"
GESETZE = {
    "GeschO": ("Geschäftsordnung des Rates", _ORTSRECHT + "rat-ausschuesse-allgemeines/geschaeftsordnung-des-rates-der-bundesstadt-bonn.php"),
    "HS": ("Hauptsatzung", _ORTSRECHT + "rat-ausschuesse-allgemeines/hauptsatzung.php"),
    "BezS": ("Bezirkssatzung", _ORTSRECHT + "rat-ausschuesse-allgemeines/bezirkssatzung.php"),
    "ZustO": ("Zuständigkeitsordnung", _ORTSRECHT + "rat-ausschuesse-allgemeines/zustaendigkeitsordnung-ratsausschuesse.php"),
    "Satzung": ("Satzung Einwohnerantrag und Bürgerbegehren", _ORTSRECHT + "recht-sicherheit/"
                "satzung-zum-verfahren-bei-einwohnerantraegen-buergerbegehren-und-buergerentscheiden.php"),
    "Leitlinien": ("Leitlinien Beteiligung", "https://www.bonn.de/medien-global/amt-30/ortsrecht/Bonn_Leitlinien_fuer_Beteiligung_2026.pdf"),
    "GO NRW": ("Gemeindeordnung NRW", "https://recht.nrw.de/lrgv/gesetz/"
               "01012026-gemeindeordnung-fuer-das-land-nordrhein-westfalen-bekanntmachung-der/"),
    "BauGB": ("Baugesetzbuch", "https://www.gesetze-im-internet.de/bbaug/"),
}
_PREFIX = ("GeschO", "HS", "BezS", "ZustO", "Satzung", "Leitlinien")
_SUFFIX_RE = re.compile(r"(§§?\s*[^;§]*?)\s*\b(GO NRW|BauGB)\b")
# Abweichend vom Original reicht ein Verweis bis zum nächsten Gesetz oder Semikolon, damit „GeschO § 22 Abs. 1, § 7 Abs. 5“
# beide Paragrafen behält
_PREFIX_RE = re.compile(r"\b(" + "|".join(_PREFIX) + r")\b\s*(.*?)(?=\s*[,;]\s*\b(?:" + "|".join(_PREFIX) + r")\b|\s*;|\s*$)")


def rechtsgrundlagen(beleg):
    """„§ 24 GO NRW, GeschO § 27“ → [{label, url}] in der Reihenfolge des Vorkommens; Unbekanntes entfällt."""
    if not beleg:
        return []
    found, rest = [], beleg
    for m in _SUFFIX_RE.finditer(beleg):
        found.append((m.start(), m.group(2), m.group(1).strip(" ,(")))
        rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
    for m in _PREFIX_RE.finditer(rest):
        found.append((m.start(), m.group(1), m.group(2).strip(" ,;)")))
    out, seen = [], set()
    for _, kurz, para in sorted(found):
        name, url = GESETZE[kurz]
        label = f"{name} {para}".strip()
        if label not in seen:
            seen.add(label)
            out.append({"label": label, "url": url})
    return out


AUDIT = ["stammnummer", "jahr", "typ", "verfahren", "sicherheit", "grund", "dokumente", "ist_bahnen",
         "soll_bahnen", "passung", "abweichung"]


class Modell:
    """Verfahren mit Schritten (übernommene und eigene, `eigen: true`), Zuständigkeitsordnung, Korrekturen."""

    def __init__(self, base=SOLL):
        load = lambda n: json.loads((base / n).read_text(encoding="utf-8"))
        self.quelle, self.zusto, self.extra = load("verfahren.json"), load("zustaendigkeitsordnung.json"), load("ergaenzungen.json")
        self.quelle, self.zusto = copy.deepcopy(self.quelle), copy.deepcopy(self.zusto)
        self.korrigiert = [self._korrigiere(k) for k in self.extra["korrekturen"]]
        self.verfahren = {v["id"]: v for v in self.quelle["verfahren"]}
        for v in self.quelle["einordnung_extra"]["verfahren"]:  # Mitteilung, nichtöffentlich: in jedem Gremium möglich
            self.verfahren[v["id"]] = dict(v, jedes_gremium=True)
        for vid, steps in self.extra["zusaetzliche_schritte"].items():
            self.verfahren[vid]["schritte"] = self.verfahren[vid]["schritte"] + [dict(s, eigen=True) for s in steps]
        self.ohne_soll = self.extra["ohne_soll"]
        # Einflussregeln (Mitwirkung) in der Anrede der Seite; der alte Wortlaut wird geprüft wie bei den Korrekturen
        self.regeln = copy.deepcopy(self.quelle["einfluss_regeln"])
        by_id = {r["id"]: r for r in self.regeln}
        for a in self.extra["anrede"]["regeln"]:
            r = by_id[a["id"]]
            if r["was"] != a["alt"]:
                raise ValueError(f"Umformulierung passt nicht zur Quelle: {a['id']}")
            r["was"], r["umformuliert"] = a["neu"], True
        for b in self.extra.get("regel_bedingungen", {}).get("regeln", []):
            w = by_id[b["id"]]["wenn"]
            for k, v in b["wenn"].items():
                if k in w and not k.startswith("nicht_"):
                    raise ValueError(f"Bedingung besteht schon in der Quelle: {b['id']} {k}")
                w[k] = w.get(k, []) + [x for x in v if x not in w.get(k, [])]  # Ausschlüsse nur erweitern
            by_id[b["id"]]["bedingung_ergaenzt"] = b["grund"]

    def _korrigiere(self, k):
        if k["datei"] == "zustaendigkeitsordnung.json":
            a = next(x for x in self.zusto["ausschuesse"] if x["nr"] == k["ausschuss"])
            r = next(x for x in a["rechte"] if x["nr"] == k["nr"])
        else:
            v = next(x for x in self.quelle["verfahren"] if x["id"] == k["verfahren"])
            r = next(x for x in v["ausgaenge"] if x["wenn"] == k["ausgang"])
        if r[k["feld"]] != k["alt"]:
            raise ValueError(f"Korrektur passt nicht zur Quelle: {k}")
        r[k["feld"]] = k["neu"]
        r["korrigiert"] = k["beleg"]
        return k

    def bahnen(self, vid):
        v = self.verfahren.get(vid)
        if not v:
            return set()
        if v.get("jedes_gremium"):
            return set(BAHN.values())
        return {s.get("bahn") for s in v["schritte"]} & set(BAHN.values())


def assign(typ, titel, arts, entsch, ohne_soll=()):
    """Verfahren eines Vorgangs nach Vorlagenart der Hauptvorlage, Gremienarten und Titel: (id, sicherheit, grund).
    Regeln wie assign() in bonn-entscheidet/einordnung.py; ohne Soll (z. B. Bürgerbrief) → (None, None, grund)."""
    typ, titel = typ or "", titel or ""
    if typ in ohne_soll:
        return None, None, f"kein Verfahren im Regelwerk für „{typ}“"
    if typ == "Anregungen und Beschwerden" or typ.startswith("Bürgerantrag"):
        return "buergerantrag", "hoch", f"Vorlagenart „{typ}“ (§ 24 GO NRW)"
    fixed = {"Einwohnerfrage": "einwohnerfrage", "Große Anfrage": "grosse-anfrage", "Kleine Anfrage": "kleine-anfrage",
             "Mitteilungsvorlage": "mitteilung", "Informationsbrief": "mitteilung", "Dringlichkeitsantrag": "dringlichkeitsantrag"}
    if typ in fixed:
        return fixed[typ], "hoch", f"Vorlagenart „{typ}“"
    if typ.startswith(("Dringlichkeitsentscheidung", "Eilentscheidung")):
        return "dringlichkeitsentscheidung", "hoch", f"Vorlagenart „{typ}“"
    if typ.startswith("Tagesordnungspunkte in nichtöffentlicher"):
        return "nichtoeffentlich", "hoch", "nichtöffentliche Tagesordnungspunkte"
    if typ in ("Antrag", "Änderungsantrag"):
        sure = "hoch" if typ == "Antrag" else "mittel"
        if arts and arts <= {"Bezirksvertretungen"}:
            return "antrag-bv", sure, "Antrag, beraten nur in Bezirksvertretungen"
        if arts & {"Rat", "Ratsgremien"}:
            return "antrag-rat", sure, "Antrag mit Beratung in Rat oder Ausschuss"
        if re.search(r"Bezirks(fraktion|verordnete|vertretung)|\bBV\b", titel):
            return "antrag-bv", "mittel", "Antrag ohne bekanntes Gremium; der Titel nennt die Bezirksebene"
        return "antrag-rat", "mittel", "Antrag ohne bekanntes Gremium; angenommen: Rat oder Ausschuss"
    if typ.startswith("Beschlussvorlage"):
        if BAULEIT_RE.search(titel):
            return "bauleitplanung", "hoch" if BAULEIT_SICHER.search(titel) else "mittel", "Bauleitplanung (Titel)"
        if entsch and entsch <= {"Ratsgremien"}:
            return "ausschuss-entscheidung", "hoch", "verbindlich entscheidet ein Ausschuss"
        if "Rat" in entsch:
            return "beschlussvorlage", "hoch", "verbindlich entscheidet der Rat"
        if entsch and entsch <= {"Bezirksvertretungen"}:
            return "beschlussvorlage", "mittel", "die Bezirksvertretung entscheidet selbst"
        return "beschlussvorlage", "mittel", "entscheidendes Gremium noch nicht bekannt"
    return "beschlussvorlage", "mittel", f"kein eigenes Verfahren für „{typ}“"


def stammnummer(reference):
    return (reference or "").split("-")[0].strip()


def folge(typ):
    """Fragen und Berichte, die einem Vorgang folgen (wie is_followup in vorgang.py des Originals)."""
    t = typ or ""
    return t.startswith(("Mitteilungsvorlage", "Informationsbrief")) or "Anfrage" in t or "Einwohnerfrage" in t


def hauptweg(ps, head):
    """Vorlagen eines Vorgangs, die für Zuordnung und Abgleich zählen (Phase 4): ohne spätere Fragen und Berichte
    anderer Art; Stellungnahmen und Änderungsanträge gehören zur vorausgehenden Vorlage."""
    weg, zaehlt = [], True
    for p in sorted(ps, key=lambda p: p[1]):
        if p[3] not in SIDE:
            zaehlt = p is head or p[3] == head[3] or not folge(p[3])
        if zaehlt:
            weg.append(p)
    return weg


def abgleich(db, modell):
    """Je Vorgang: Verfahren, Sicherheit, Gremien (Ist/Soll) und Passung; Gremien nur aus dem Hauptweg."""
    cons = collections.defaultdict(list)
    for pid, cls, role in db.execute("SELECT c.paper_id, o.classification, c.role FROM consultation c "
                                     "JOIN organization o ON o.id = c.organization_id"):
        cons[pid].append((cls, role))
    groups = collections.defaultdict(list)
    for p in db.execute("SELECT id, reference, name, paper_type, date FROM paper"):
        groups[stammnummer(p[1])].append(p)
    rows = []
    for st, ps in sorted(groups.items()):
        head = next((p for p in ps if p[1].strip() == st), None) or next((p for p in ps if p[3] not in SIDE), ps[0])
        weg = hauptweg(ps, head)
        arts = {c for p in weg for c, _ in cons[p[0]] if c}
        entsch = {c for p in weg for c, r in cons[p[0]] if c and r == "Entscheidung"}
        vid, sure, why = assign(head[3], head[2], arts, entsch, modell.ohne_soll)
        ist, soll = {BAHN[a] for a in arts if a in BAHN}, modell.bahnen(vid)
        # Beiräte bildet das Modell nicht ab: Vorgänge, die nur dort beraten wurden, werden nicht abgeglichen
        passung = ("ohne Soll" if vid is None else ("nur Beirat" if arts else "ohne Beratung") if not ist
                   else "passt" if ist <= soll else "weicht ab")
        rows.append({"stammnummer": st, "jahr": (head[4] or "")[:4], "typ": head[3], "verfahren": vid or "",
                     "sicherheit": sure or "", "grund": why, "dokumente": len(ps), "ist_bahnen": ",".join(sorted(ist)),
                     "soll_bahnen": ",".join(sorted(soll)), "passung": passung,
                     "abweichung": ",".join(sorted(ist - soll)) if passung == "weicht ab" else ""})
    return rows


_INDEX = {"db": None, "rows": {}}


def vorgaenge(db):
    """Abgleich aller Vorgänge, einmal je Datenbankverbindung berechnet."""
    if _INDEX["db"] is not db:
        _INDEX.update(db=db, rows={r["stammnummer"]: r for r in abgleich(db, Modell())})
    return list(_INDEX["rows"].values())


def lookup(db, reference):
    """Soll-Angaben zum Vorgang einer Vorlage (für den Export)."""
    vorgaenge(db)
    r = _INDEX["rows"].get(stammnummer(reference))
    if not r:
        return None
    return {"verfahren": r["verfahren"] or None, "sicherheit": r["sicherheit"] or None, "grund": r["grund"],
            "passung": r["passung"], "ist": r["ist_bahnen"].split(",") if r["ist_bahnen"] else [],
            "abweichung": r["abweichung"].split(",") if r["abweichung"] else []}


def site_data(modell=None):
    """Verfahren, Bahnen, Fristen und Zuständigkeit für die Seite (data/export/bonn/soll.json)."""
    m = modell or Modell()
    step = lambda s: {k: v for k, v in {"id": s["id"], "label": s.get("label") or s["was"], "was": s["was"],
                                         "bahn": s.get("bahn"), "beleg": s.get("beleg"),
                                         "links": rechtsgrundlagen(s.get("beleg")), "eigen": s.get("eigen")}.items() if v}
    verfahren = {vid: {"titel": v["titel"], "kurz": v.get("kurz"), "jedes_gremium": v.get("jedes_gremium", False),
                       "schritte": [step(s) for s in v["schritte"]]} for vid, v in m.verfahren.items()}
    # Zuordnung zum Gremium nur bei gleichem Namen; frühere Ausschüsse (andere Namen) erhalten keinen Abschnitt
    zusto = {a["titel"]: {"nr": a["nr"], "rechte": [{k: r[k] for k in ("nr", "art", "inhalt", "an_bezirksvertretung")}
                                                     for r in a["rechte"]]}
             for a in m.zusto["ausschuesse"] if a["rechte"]}
    return {
        "meta": {"quelle": "Verfahrensmodell und Zuständigkeitsordnung aus „Bonn entscheidet“ von Thomas (anster2025/bonn-entscheidet, "
                           "Commit 26641f7, MIT) mit Ergänzungen und Korrekturen des Ratsatlas Bonn",
                 "zusto_stand": m.zusto.get("stand"), "zusto_url": GESETZE["ZustO"][1],
                 "hinweis": "Vereinfachtes Modell des Regelwerks, keine Rechtsauskunft. Abweichungen sind Befunde, keine Bewertung."},
        "bahnen": {b["id"]: b["name"] for b in m.quelle["bahnen"]},
        "verfahren": verfahren,
        "fristen": [dict(f, links=rechtsgrundlagen(f.get("beleg"))) for f in m.quelle["fristen"]],
        "zustaendigkeit": [dict(z, links=rechtsgrundlagen(z.get("beleg"))) for z in m.quelle["zustaendigkeit"]],
        "zusto": zusto,
        "ohne_soll": m.ohne_soll,
        # Mitwirkung: Regeln werden im Browser ausgewertet (site/mitwirken.js), weil Fristen vom Tag abhängen
        "mitwirken": [{k: v for k, v in {"id": r["id"], "wenn": r["wenn"], "was": r["was"], "frist": r["frist"],
                                         "bezug": r.get("bezug"), "tage": r.get("tage", 0), "beleg": r.get("beleg"),
                                         "links": rechtsgrundlagen(r.get("beleg")), "note": r.get("note")}.items()
                       if v is not None} for r in m.regeln],
        "buergerantrag_ziel": {"bezirk": "Bezirksvertretung {bezirk}",
                               "stadt": "Ausschuss für Beteiligung der Bürgerinnen und Bürger"},
    }


def write():
    """Audit des Soll-Ist-Abgleichs: data/export/audit_soll.tsv (ohne Titel; Datenschutz)."""
    modell = Modell()
    db = sqlite3.connect(config.DB)
    rows = abgleich(db, modell)
    db.close()
    path = config.EXPORT / "audit_soll.tsv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=AUDIT, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    c = collections.Counter
    print(f"Soll-Modell: {len(rows)} Vorgänge; Sicherheit {dict(c(r['sicherheit'] or 'ohne' for r in rows))}; "
          f"Passung {dict(c(r['passung'] for r in rows))}; {len(modell.korrigiert)} Korrekturen → {path}")
    return rows
