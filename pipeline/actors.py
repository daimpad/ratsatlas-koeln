"""Akteure: Einreichende aus `originatorOrganization` oder aus Vorlagenart und Titel; Federführung.

Köln (CLAUDE.md 5.3): Ob die API `originatorOrganization` und `underDirectionOf` setzt, wird nach der Information der
Stadt gemessen. Ist `originatorOrganization` gesetzt, gilt es (belegt); sonst werden Einreichende aus dem Titel
abgeleitet („Antrag der …-Fraktion“) und als abgeleitet gekennzeichnet (method, evidence). Die Federführung aus dem
Kopf der Verwaltungsvorlage („Dezernat, Dienststelle“) folgt mit dem Abruf der PDFs.
"""
import re

CO_DEZERNAT = "Co-Dezernat"

class _Arten(frozenset):
    """Vorlagenarten: genaue Namen (Bonn und die für Köln belegten) und ein Muster für Kölner Varianten, solange die
    vollständige paperType-Liste fehlt (Messung nach Information der Stadt). `in` prüft beides."""
    def __new__(cls, namen, muster):
        obj = super().__new__(cls, namen)
        obj.muster = re.compile(muster)
        return obj

    def __contains__(self, art):
        return bool(art) and (frozenset.__contains__(self, art) or bool(self.muster.search(art)))


# Reihenfolge der Prüfung: Einwohner vor Politik (eine „Anregung“ ist kein „Antrag“), dann Verwaltung
EINWOHNER_TYPES = _Arten({
    "Bürgerantrag § 24 GO - Öffentlich", "Anregungen und Beschwerden", "Einwohnerfrage",
}, r"(?i)anregung|beschwerde|§\s*24\b|einwohner|bürgerantrag")
POLITIK_TYPES = _Arten({
    "Antrag", "Änderungsantrag", "Dringlichkeitsantrag", "Große Anfrage", "Kleine Anfrage",
    "Antrag nach § 3", "Anfrage nach § 4",
    "Antrag nach § 3 der Geschäftsordnung des Rates", "Anfrage nach § 4 der Geschäftsordnung des Rates",
}, r"(?i)^(?!.*(?:anregung|beschwerde|einwohner|bürgerantrag)).*(?:antrag|anfrage)")
VERWALTUNG_TYPES = _Arten({
    "Beschlussvorlage", "Beschlussvorlage: Einleitung", "Beschlussvorlage: Auftrag", "Mitteilungsvorlage",
    "Stellungnahme der Verwaltung", "Informationsbrief", "Bürgerbrief", "Dringlichkeitsentscheidung OB",
    "Beschlussvorlage Rat", "Beschlussvorlage Ausschuss", "Mitteilung", "Mitteilung Ausschuss",
}, r"(?i)beschlussvorlage|mitteilung|stellungnahme|dringlichkeitsentscheidung")

# (Anzeigename, Muster im Titel, Muster im Namen der Fraktion/Gruppe in organizations.json). Köln: Bonner Wählergruppen
# entfernt; die Liste der Fraktionen und Gruppen im Kölner Rat (Wahlperiode ab 2025) wird nach der Messung der API
# aus den Organisationen ergänzt (CLAUDE.md 5.3).
PARTIES = [
    ("CDU", r"CDU", r"^CDU"),
    ("SPD", r"SPD", r"^SPD"),
    ("Grüne", r"(?<![\w.])(?:Grüne|GRÜNE|Bündnis 90)", r"GRÜNE|Grüne"),
    ("FDP", r"FDP", r"^FDP"),
    ("Die Linke", r"(?<!\w)(?:Linke|LINKE)", r"Linke"),
    ("Volt", r"(?<!\w)Volt(?!\w)", r"^Volt"),
    ("AfD", r"(?<!\w)AfD(?!\w)", r"^AfD|^Alternative für Deutschland"),
    ("BSW", r"(?<!\w)BSW(?!\w)", r"BSW"),
    ("Die PARTEI", r"PARTEI", r"PARTEI"),
    ("Piraten", r"Piraten", r"Piraten"),
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
    if ptype in EINWOHNER_TYPES:
        # Keine Namen natürlicher Personen (Datenschutz, CLAUDE.md 2).
        return [dict(actor="Einwohner:innen", actor_type="Einwohner:in", organization_id=None,
                     method="paper_type", evidence=ptype)]
    belegt = _from_originator(paper, orgs)
    if belegt:
        return belegt
    if ptype in VERWALTUNG_TYPES and ptype not in POLITIK_TYPES:
        org = (paper.get("underDirectionOf") or [None])[0]
        return [dict(actor="Verwaltung", actor_type="Verwaltung", organization_id=org,
                     method="paper_type", evidence=ptype)]
    if ptype not in POLITIK_TYPES:
        return []
    for seg in _segments(paper.get("name") or ""):
        rows = _from_segment(seg.strip(), orgs, date, bezirke)
        if rows:
            return rows
    # Köln: Partei oft in der Vorlagenart („FDP Antrag nach § 3“, Recherche 04.11.2026)
    return _from_segment(ptype, orgs, date, bezirke)


def _from_originator(paper, orgs):
    """Einreichende laut OParl (`originatorOrganization`), falls die Stadt das Feld setzt. `originatorPerson` wird
    nicht übernommen (keine Personennamen als Einreichende)."""
    by_id = {o["id"]: o for o in orgs}
    rows = []
    for oid in paper.get("originatorOrganization") or []:
        o = by_id.get(oid)
        if not o:
            continue
        name = next((n for n, _, pat in PARTIES if re.search(pat, o["name"])), o["name"])
        rows.append(dict(actor=name, actor_type="Fraktion/Gruppe", organization_id=oid,
                         method="originatorOrganization", evidence=o["name"]))
    return rows


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
