"""Akteure: Einreichende aus `originatorOrganization` oder aus Vorlagenart und Titel; Federführung.

Köln (CLAUDE.md 5.3): Ob die API `originatorOrganization` und `underDirectionOf` setzt, wird nach der Information der
Stadt gemessen. Ist `originatorOrganization` gesetzt, gilt es (belegt); sonst werden Einreichende aus dem Titel
abgeleitet („Antrag der …-Fraktion“) und als abgeleitet gekennzeichnet (method, evidence). Fraktionen, Gruppen und
Einzelmandate des Kölner Rates 2020–2025 und 2025–2030 stehen in PARTIES, Bezeichnungen einer Wahlperiode mit
Datumsgrenzen (Regeln dort). Die Federführung aus dem Kopf der Verwaltungsvorlage („Dezernat, Dienststelle“) folgt mit
dem Abruf der PDFs.
"""
import re
from typing import NamedTuple, Optional

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

class Partei(NamedTuple):
    """Fraktion, Gruppe oder Einzelmandat im Kölner Rat (bzw. Partei einer Bezirksfraktion).

    name: Anzeigename (Filter, Vorgang). titel: Muster im Titel bzw. in der Vorlagenart (Groß- und Kleinschreibung
    zählt). org: Muster im Namen der Organisation (organizations.json). von/bis: Datum der Vorlage, ab bzw. bis zu dem
    die Bezeichnung gilt (jeweils einschließlich; Vorlagen ohne Datum: ohne Prüfung). nur_mit_datum: Umdeutung nach
    dem Datum, ohne Datum der Vorlage nicht angewendet."""
    name: str
    titel: str
    org: str
    von: Optional[str] = None
    bis: Optional[str] = None
    nur_mit_datum: bool = False


# Wahlperioden (Grundlage: explore/ergebnisse/fraktionen_rat.tsv; Abgleich mit dem Ratsinformationssystem offen)
KOMMUNALWAHL_2020 = "2020-09-13"
KOMMUNALWAHL_2025 = "2025-09-14"
# Beginn der Wahlperiode 2025–2030: angenommen 01.11.2025 (Bonner legislativeTerms, siehe pipeline/themenseiten;
# Hinweis „Integrationsrat bis 31.10.2025“ in gremien_koeln.tsv); den Kölner legislativeTerm messen wir erst mit dem
# Abruf. Zwischen Wahl und Ende der alten Wahlperiode gelten die Bezeichnungen beider Wahlperioden (neue Fraktionen
# konstituieren sich, der alte Rat tagt ggf. noch).
WAHLPERIODE_2025_BEGINN = "2025-11-01"
WAHLPERIODE_2020_ENDE = "2025-10-31"

# Wortgrenze ohne Bindestrich-Zusätze: „KSG“, nicht „KSG-Gelände“; erlaubt „KSG-Fraktion“, „KSG-Bezirksfraktion“
_FRAKTION_ZUSATZ = r"(?:-(?:Rats|Bezirks)?[Ff]raktion|-Gruppe)"
# Adjektivisch verwendbare Namen („Grüne Welle“, „Linke Rheinseite“, „am Linken Rheinufer“): kein großgeschriebenes
# Wort danach, außer Fraktion, Ratsfraktion, Bezirksfraktion oder Köln
_KEIN_NOMEN = r"(?!\s+(?!(?:Fraktion|Ratsfraktion|Bezirksfraktion|Köln)\b)[A-ZÄÖÜ])"

# Fraktionen, Gruppen und Einzelmandate im Kölner Rat 2020–2025 und 2025–2030 (fraktionen_rat.tsv, Bezirksvertretungen
# fraktionen_bv.tsv). Aus dem Titel erkannte Einreichende bleiben abgeleitet (method „title“, evidence = Fundstelle).
# Reihenfolge zählt: Längere Bezeichnungen stehen vor ihren Teilen; ein Treffer verdeckt seine Stelle für alle
# folgenden Einträge („FDP/KSG“ zählt nicht zusätzlich als „FDP“ oder „KSG“, „GUT & KLIMA FREUNDE“ nicht als „GUT“).
#
# Regel FDP/KSG (Fraktion FDP/KSG im Rat, konstituiert 17.09.2025 laut fdp-koeln.de):
# 1. Schreibweise „FDP/KSG“ (auch „FDP / KSG“) ab 17.09.2025 → „FDP/KSG“, nie zusätzlich „FDP“ oder KSG.
# 2. „FDP-Fraktion“, „FDP-Ratsfraktion“, „Fraktion der FDP“ ab Beginn der Wahlperiode 2025–2030 (01.11.2025) → „FDP/KSG“:
#    Im Rat 2025–2030 ist sie die einzige Fraktion mit Mitgliedern der FDP (fraktionen_rat.tsv nennt „FDP-Fraktion“ als
#    ungeprüfte Schreibvariante). Davor (auch in der Übergangszeit ab der Wahl) bleibt es die FDP-Fraktion 2020–2025.
# 3. „FDP“ ohne „/KSG“ und ohne „Fraktion“ (z. B. „Anfrage der FDP“, Vorlagenart „FDP Antrag nach § 3“) bleibt „FDP“:
#    Das kann auch ein einzelnes Mitglied einer Bezirksvertretung sein (FDP dort je höchstens 1 Sitz, fraktionen_bv.tsv).
# 4. „KSG“ bzw. „Kölner Stadtgesellschaft“ allein erst ab der Kommunalwahl 14.09.2025 (vorher nicht im Rat).
PARTIES = [
    Partei("FDP/KSG", r"(?<!\w)FDP\s*/\s*KSG(?!\w)", r"FDP\s*/\s*KSG", von="2025-09-17"),
    Partei("FDP/KSG", r"(?<![\w/])(?:FDP[- ](?:Rats)?[Ff]raktion|Fraktion der FDP)(?!\w)", r"FDP\s*/\s*KSG",
           von=WAHLPERIODE_2025_BEGINN, nur_mit_datum=True),
    # Wählergruppen GUT und Klima Freunde fusioniert am 29.09.2024 (fraktionen_rat.tsv, Quelle Wikipedia)
    Partei("GUT & KLIMA FREUNDE", r"(?<!\w)(?:GUT|Gut)\s*&\s*(?:KLIMA|Klima)\s+(?:FREUNDE|Freunde)(?!\w)",
           r"(?i)gut\s*&\s*klima\s*freunde", von="2024-09-29"),
    # Ratsgruppe der Wahlperiode 2020–2025, später „Klima Freunde & Gut“ (Datum offen)
    Partei("Klima Freunde", r"(?<!\w)(?<!&\s)(?<!&)(?:KLIMA|Klima)\s+(?:FREUNDE|Freunde)(?:\s*&\s*(?:GUT|Gut))?(?!\w)",
           r"(?i)(?<!&\s)(?<!&)klima\s*freunde", bis=WAHLPERIODE_2020_ENDE),
    # Ratsgruppe GUT Köln 2020–2025 (aufgelöst 2021); nur in Großbuchstaben, damit „Gut Leidenhausen“, „Gutachten“
    # nicht zählen
    Partei("GUT Köln", r"(?<![\w&])(?<!&\s)GUT(?![\w-])(?!\s*&)", r"(?<![\w&])(?<!&\s)GUT(?!\w)(?!\s*&)",
           bis=WAHLPERIODE_2020_ENDE),
    Partei("CDU", r"(?<!\w)CDU(?!\w)", r"(?<!\w)CDU(?!\w)"),
    Partei("SPD", r"(?<!\w)SPD(?!\w)", r"(?<!\w)SPD(?!\w)"),
    Partei("Grüne", r"(?<![\w.])(?:GRÜNEN?(?!\w)|Bündnis\s*90|Grünen?(?!\w)" + _KEIN_NOMEN + ")", r"GRÜNE|Grüne"),
    Partei("FDP", r"(?<![\w/])FDP(?!\s*/\s*KSG)(?!\w)", r"(?<![\w/])FDP(?!\s*/\s*KSG)(?!\w)"),
    Partei("Kölner Stadtgesellschaft",
           r"(?<![\w/])(?<!/\s)KSG(?:(?![\w/-])|(?=" + _FRAKTION_ZUSATZ + "))|Kölner Stadtgesellschaft",
           r"^(?:KSG|Kölner Stadtgesellschaft)", von=KOMMUNALWAHL_2025),
    # nicht „Linkes Rheinufer“, „Linke Rheinseite“ (Ortsangaben)
    Partei("Die Linke", r"(?<!\w)(?:LINKE(?!\w)|Linksfraktion|Linken?(?!\w)" + _KEIN_NOMEN + ")", r"Linke|LINKE"),
    Partei("Volt", r"(?<!\w)Volt(?!\w)", r"(?<!\w)Volt(?!\w)"),  # nicht „Voltaplatz“
    Partei("AfD", r"(?<!\w)AfD(?!\w)", r"(?<!\w)AfD(?!\w)|Alternative für Deutschland"),
    Partei("BSW", r"(?<!\w)BSW(?!\w)|Bündnis Sahra Wagenknecht", r"(?<!\w)BSW(?!\w)|Sahra Wagenknecht"),
    # nur in Großbuchstaben, nicht „Parteien“; 2020–2025 auch „Die FRAKTION“ und „Die PARTEI im Rat“
    Partei("Die PARTEI", r"(?<!\w)PARTEI(?!\w)", r"PARTEI|Die FRAKTION"),
    Partei("Die PARTEI", r"(?<!\w)Die FRAKTION(?!\w)", r"PARTEI|Die FRAKTION",
           von=KOMMUNALWAHL_2020, bis=WAHLPERIODE_2020_ENDE),
    # Einzelmandat 2020–2025; Zuordnung des Mandats zu FWK laut fraktionen_rat.tsv unsicher
    Partei("Freie Wähler Köln", r"(?<!\w)Freien?\s+Wähler(?!\w)|(?<!\w)FWK(?!\w)", r"Freie Wähler|(?<!\w)FWK(?!\w)",
           bis=WAHLPERIODE_2020_ENDE),
    # nicht in den Kölner Recherchetabellen 2020–2030; für ältere Wahlperioden beibehalten (ungeprüft)
    Partei("Piraten", r"(?<!\w)Piraten(?:partei)?(?!\w)", r"Piraten"),
]
GROUPS = [
    ("Koalition", r"[Kk]oalition"),
    ("interfraktionell", r"[Ii]nterfraktionell"),
]
UNRESOLVED = r"u\.\s?w\."
KEYWORD = re.compile(r"(?:Änderungs|Dringlichkeits)?[Aa]ntrag|Anfrage|(?<!\w)(?:AA|ÄA)(?!\w)")
# Ende der Einreichenden im Titel: „Antrag der Fraktionen SPD, GRÜNE und Volt betreffend …“ (Köln), „… zur …“, „…:“
STOPP = re.compile(r"\s(?:betreffend|betr\.|bezüglich|bzgl\.|zum Thema|zur|zum|zu)(?=\s)|[:„“\"»]")
RAT_CLASSES = ("Fraktion", "Gruppen", "Einzelmandate")


def _segments(title):
    """Abschnitte (Anfang, Ende) des Titels mit den Einreichenden: Präfix vor dem ersten Doppelpunkt, sonst Fenster um
    „Antrag“/„Anfrage“: 40 Zeichen davor, danach bis „betreffend“, „zur“ usw. (höchstens 150 Zeichen), ohne solches
    Wort 60 Zeichen. Köln nennt mehrere Fraktionen vor „betreffend“; ein festes Fenster schnitte sie ab."""
    head, sep, _ = title.partition(":")
    if sep and len(head) <= 100:
        yield 0, len(head)
    for m in KEYWORD.finditer(title):
        stopp = STOPP.search(title, m.end())
        ende = stopp.start() if stopp and stopp.start() - m.end() <= 150 else m.end() + 60
        yield max(0, m.start() - 40), min(ende, len(title))


def _gilt(partei, date):
    """Gilt die Bezeichnung am Datum der Vorlage? Ohne Datum: ja, außer bei Umdeutungen nach dem Datum."""
    d = (date or "")[:10]
    if not d:
        return not partei.nur_mit_datum
    return (not partei.von or d >= partei.von) and (not partei.bis or d <= partei.bis)


def _treffer(text, date, a=0, b=None):
    """[(Position, Anzeigename, Organisationsmuster)] der Fraktionen, die im Abschnitt text[a:b] beginnen, je Name
    einmal. Gesucht wird im ganzen Text, damit die Wortgrenzen am Rand des Abschnitts stimmen („… und Linke
    Rheinseite“). Jeder Treffer wird für die folgenden Einträge verdeckt (längere Bezeichnung vor ihren Teilen)."""
    b = len(text) if b is None else b
    rest, hits = text, {}
    for p in PARTIES:
        if not _gilt(p, date):
            continue
        for m in re.finditer(p.titel, rest):
            if a <= m.start() < b and (p.name not in hits or m.start() < hits[p.name][0]):
                hits[p.name] = (m.start(), p.org)
            rest = rest[:m.start()] + "\0" * (m.end() - m.start()) + rest[m.end():]
    return sorted((pos, name, org) for name, (pos, org) in hits.items())


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
    titel = paper.get("name") or ""
    for a, b in _segments(titel):
        rows = _from_segment(titel, orgs, date, bezirke, a, b)
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
        name = next((p.name for p in PARTIES if re.search(p.org, o["name"])), o["name"])
        rows.append(dict(actor=name, actor_type="Fraktion/Gruppe", organization_id=oid,
                         method="originatorOrganization", evidence=o["name"]))
    return rows


def _from_segment(text, orgs, date, bezirke, a=0, b=None):
    """Einreichende aus dem Abschnitt text[a:b] (Fundstelle = dieser Abschnitt)."""
    seg = text[a:b].strip()
    rows = []
    bezirks_fraktion = "Bezirksfraktion" in seg
    for _, name, org_pat in _treffer(text, date, a, b):
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
