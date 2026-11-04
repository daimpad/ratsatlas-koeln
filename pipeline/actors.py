"""Akteure: Einreichende aus Vorlagenart und Titel; Auflösung der Sammelklasse „Co-Dezernat“.

Die OParl-API setzt `originatorPerson`/`originatorOrganization` nicht. Einreichende werden
deshalb abgeleitet und als abgeleitet gekennzeichnet (method, evidence).
"""
import re

CO_DEZERNAT = "Co-Dezernat"

VERWALTUNG_TYPES = {
    "Beschlussvorlage",
    "Beschlussvorlage: Einleitung",
    "Beschlussvorlage: Auftrag",
    "Mitteilungsvorlage",
    "Stellungnahme der Verwaltung",
    "Informationsbrief",
    "Bürgerbrief",
    "Dringlichkeitsentscheidung OB",
}
EINWOHNER_TYPES = {
    "Bürgerantrag § 24 GO - Öffentlich",
    "Anregungen und Beschwerden",
    "Einwohnerfrage",
}
POLITIK_TYPES = {
    "Antrag",
    "Änderungsantrag",
    "Dringlichkeitsantrag",
    "Große Anfrage",
    "Kleine Anfrage",
}

# (Anzeigename, Muster im Titel, Muster im Namen der Fraktion/Gruppe in organizations.json)
PARTIES = [
    ("CDU", r"CDU", r"^CDU"),
    ("SPD", r"SPD", r"^SPD"),
    ("Grüne", r"(?<![\w.])(?:Grüne|GRÜNE|Bündnis 90)", r"GRÜNE|Grüne"),
    ("FDP", r"FDP", r"^FDP"),
    ("BBB", r"BBB", r"^BBB"),
    ("Die Linke", r"(?<!\w)(?:Linke|LINKE)", r"Linke"),
    ("Volt", r"(?<!\w)Volt(?!\w)", r"^Volt"),
    ("AfD", r"(?<!\w)AfD(?!\w)", r"^AfD|^Alternative für Deutschland"),
    ("BSW", r"(?<!\w)BSW(?!\w)", r"BSW"),
    ("SBI", r"(?<!\w)SBI(?!\w)", r"SBI"),
    ("BIG", r"(?<!\w)BIG(?!\w)", r"^BIG"),
    ("Die PARTEI", r"PARTEI", r"PARTEI"),
    ("Piraten", r"Piraten", r"Piraten"),
    ("Allianz für Bonn", r"(?<!\w)AfB(?!\w)|Allianz für Bonn", r"Allianz für Bonn"),
    ("Rhein.Grün", r"Rhein\.Grün", r"Rhein\.Grün"),
]
GROUPS = [
    ("Koalition", r"[Kk]oalition"),
    ("interfraktionell", r"[Ii]nterfraktionell"),
]
UNRESOLVED = r"u\.\s?w\."
KEYWORD = re.compile(r"(?:Änderungs|Dringlichkeits)?[Aa]ntrag|Anfrage|(?<!\w)(?:AA|ÄA)(?!\w)")
RAT_CLASSES = ("Fraktion", "Gruppen", "Einzelmandate")


def _segments(title):
    """Präfix vor dem ersten Doppelpunkt, sonst Fenster um „Antrag“/„Anfrage“."""
    head, sep, _ = title.partition(":")
    if sep and len(head) <= 100:
        yield head
    for m in KEYWORD.finditer(title):
        yield title[max(0, m.start() - 40): m.end() + 25]


def _active(org, date):
    return (not org.get("endDate") or org["endDate"] >= date) and (
        not org.get("startDate") or org["startDate"] <= date
    )


def _match_org(orgs, pattern, date, classes, bezirk=None):
    for cls in classes:
        for o in orgs:
            if o.get("classification") != cls or not re.search(pattern, o["name"]):
                continue
            if bezirk and not o["name"].endswith(bezirk):
                continue
            if _active(o, date):
                return o["id"]
    return None


def originators(paper, orgs, bezirke=()):
    """Einreichende einer Vorlage als Liste von Zeilen (actor, actor_type, organization_id,
    method, evidence). `bezirke`: Stadtbezirke der befassten Bezirksvertretungen."""
    ptype, date = paper.get("paperType"), paper.get("date") or ""
    if ptype in VERWALTUNG_TYPES:
        org = (paper.get("underDirectionOf") or [None])[0]
        return [dict(actor="Verwaltung", actor_type="Verwaltung", organization_id=org,
                     method="paper_type", evidence=ptype)]
    if ptype in EINWOHNER_TYPES:
        # Keine Namen natürlicher Personen (Datenschutz, CLAUDE.md 5.2).
        return [dict(actor="Einwohner:innen", actor_type="Einwohner:in", organization_id=None,
                     method="paper_type", evidence=ptype)]
    if ptype not in POLITIK_TYPES:
        return []
    for seg in _segments(paper.get("name") or ""):
        rows = _from_segment(seg.strip(), orgs, date, bezirke)
        if rows:
            return rows
    return []


def _from_segment(seg, orgs, date, bezirke):
    rows = []
    bezirks_fraktion = "Bezirksfraktion" in seg
    hits = sorted((m.start(), name, org_pat) for name, title_pat, org_pat in PARTIES
                  if (m := re.search(title_pat, seg)))
    for _, name, org_pat in hits:
        if bezirks_fraktion:
            bezirk = next(iter(bezirke)) if len(bezirke) == 1 else None
            org = _match_org(orgs, org_pat, date, ("Bezirksfraktionen (intern)",), bezirk) if bezirk else None
            actor = f"{name}-Bezirksfraktion" + (f" {bezirk}" if bezirk else "")
            rows.append(dict(actor=actor, actor_type="Bezirksfraktion", organization_id=org,
                             method="title", evidence=seg))
        else:
            org = _match_org(orgs, org_pat, date, RAT_CLASSES)
            rows.append(dict(actor=name, actor_type="Fraktion/Gruppe", organization_id=org,
                             method="title", evidence=seg))
    for name, pat in GROUPS:
        if re.search(pat, seg):
            rows.append(dict(actor=name, actor_type=name, organization_id=None,
                             method="title", evidence=seg))
    if rows and re.search(UNRESOLVED, seg):
        rows.append(dict(actor="weitere (u.w., nicht aufgelöst)", actor_type="unaufgelöst",
                         organization_id=None, method="title", evidence=seg))
    return rows


def amt_label(org):
    """Anzeigename eines Verwaltungsbereichs: Amt laut `classification`; bei „Co-Dezernat“
    der Verwaltungsbereich selbst (z. B. „01-2 Ratsbüro“)."""
    if not org:
        return None
    cls = org.get("classification")
    return org["name"] if cls == CO_DEZERNAT or not cls else cls


def responsibilities(paper, orgs_by_id, papers_by_id):
    """Federführung (strukturiert) und, bei „Co-Dezernat“, fachliche Zuständigkeit aus den
    Stellungnahmen der Verwaltung (abgeleitet)."""
    lead = (paper.get("underDirectionOf") or [None])[0]
    rows = [dict(organization_id=lead, kind="federfuehrend", method="underDirectionOf",
                 evidence=None, derived=0)] if lead else []
    if not lead or (orgs_by_id.get(lead) or {}).get("classification") != CO_DEZERNAT:
        return rows
    seen = set()
    for sub_id in paper.get("subordinatedPaper") or []:
        sub = papers_by_id.get(sub_id)
        if not sub or sub.get("paperType") not in VERWALTUNG_TYPES:
            continue
        org = (sub.get("underDirectionOf") or [None])[0]
        if not org or org in seen or (orgs_by_id.get(org) or {}).get("classification") == CO_DEZERNAT:
            continue
        seen.add(org)
        rows.append(dict(organization_id=org, kind="fachlich", method="stellungnahme",
                         evidence=sub.get("reference"), derived=1))
    return rows
