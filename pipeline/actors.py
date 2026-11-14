"""Akteure: Einreichende aus `originatorOrganization` oder aus Vorlagenart und Titel; Federführung.

Köln (CLAUDE.md 5.3): Ob die API `originatorOrganization` und `underDirectionOf` setzt, wird nach der Information der
Stadt gemessen. Ist `originatorOrganization` gesetzt, gilt es (belegt); sonst werden Einreichende aus dem Titel
abgeleitet („Antrag der …-Fraktion“) und als abgeleitet gekennzeichnet (method, evidence). Vorher gilt die Kölner
Vorlagenart „… BV<n> (<Fraktion>)“ (Stufe 1, 07.11.2026: „Antrag nach § 3 BV2 (CDU)“, „Änderungsantrag BV1 (Grüne)“,
auch mit Zusatz wie „(geändert)“) als strukturierte Quelle: Bezirksfraktion in der Bezirksvertretung n (Stadtbezirk n
nach der Hauptsatzung), method „paper_type“, evidence = Vorlagenart. Ohne erkannte Fraktion in Klammern („Gem.
Änderungsantrag BV3“) gelten die Fraktionen aus dem Titel als Bezirksfraktionen des Bezirks n (method „title“), nie als
Ratsfraktionen; eine Nummer außerhalb 1–9 ergibt Bezirksfraktionen ohne Bezirk. Antworten der Verwaltung („Beantwortung
einer Anfrage (BV)“) sind keine Einreichung einer Fraktion: Einreichende ist die Verwaltung (Fragesteller nicht
getrennt erfasst). Fraktionen, Gruppen und
Einzelmandate des Kölner Rates 2020–2025 und 2025–2030 stehen in PARTIES, Bezeichnungen einer Wahlperiode mit
Datumsgrenzen (Regeln dort). Die Federführung aus dem Kopf der Verwaltungsvorlage („Dezernat, Dienststelle“) folgt mit
dem Abruf der PDFs. Dezernat und Dienststelle der Federführung (Name der Organisation aus `underDirectionOf` oder Kennung
aus dem Kopf) ordnet `export` über die Ämtertabelle zu (pipeline/aemter.py: `zuordnen`, je Vorlage mit dem Plan, dessen
Stand an ihrem Datum der jüngste ist, bis zu seiner letzten Prüfung; nur eindeutige Treffer, sonst Status); die Zeilen
hier bleiben unverändert.
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
# Stadtbezirke 1–9 in der Reihenfolge ihrer Nummern (wie geocode.BEZIRKE_KOELN; hier ohne Import, damit actors ohne
# Geobibliotheken läuft)
STADTBEZIRKE = ("Innenstadt", "Rodenkirchen", "Lindenthal", "Ehrenfeld", "Nippes", "Chorweiler", "Porz", "Kalk",
                "Mülheim")
# Kölner Vorlagenart einer Bezirksvertretung: „Antrag nach § 3 BV2 (CDU)“, „Änderungsantrag BV1 (Grüne)“, „… BV2 (CDU)
# (geändert)“, „Gem. Änderungsantrag BV3“ (ohne Klammer); die erste Klammer direkt nach der Nummer nennt die Fraktion
BV_ART = re.compile(r"(?<!\w)BV\s?(\d+)(?!\w)(?:\s*\(([^()]*)\))?")
# Antworten der Verwaltung auf eine Anfrage („Beantwortung einer Anfrage (BV)“, „Antwort auf …“): keine Einreichung
# einer Fraktion. Nur am Anfang der Vorlagenart: „Anfrage nach § 4 zur schriftlichen Beantwortung“ stellt eine Fraktion
ANTWORT_ART = re.compile(r"(?i)^\s*(?:beantwortung|antwort)(?!\w)")
# „Grüne(n)“ und „Linke(n)“ in gemischter Schreibung sind auch Adjektive („Grüne Welle“, „Linke Rheinseite“, „am Linken
# Rheinufer“, „Grüne Jugend“). Sie zählen
# - nie vor einem Orts- oder Sachwort aus _SACHWORT;
# - immer nach „Die“/„die“, „der“, „Fraktion“ oder „Gruppe“ („Fraktion Die Linke Mieten am Musterweg“, „Antrag der
#   Grünen Sitzbänke“);
# - sonst nur, wenn kein großgeschriebenes Wort folgt oder eines aus _FOLGEWORT (Fraktion, Köln, Antrag, Anfrage, AA,
#   ÄA, Nr., TOP, Stadtbezirk), z. B. Vorlagenart „Grüne Antrag nach § 3“.
_SACHWORT = (r"(?!\s+(?:(?:Rheinufer|Rheinseite)\w*|(?:Welle|Wellen|Pfeil|Pfeils|Lunge|Infrastruktur|Woche|Hausnummer|"
             r"Mitte|Achse|Wege|Dächer|Fassaden?|Wände|Oasen?|Jugend|Spur|Fahrspur|Seite)(?!\w)))")
_FOLGEWORT = (r"(?!\s+(?!(?:Fraktion|Ratsfraktion|Bezirksfraktion|Köln|Antrag|Anfrage|Änderungsantrag|"
              r"Dringlichkeitsantrag|AA|ÄA|Nr|TOP|" + "|".join(STADTBEZIRKE) + r")(?!\w))[A-ZÄÖÜ])")
_PARTEI_DAVOR = r"(?:(?<=[Dd]ie )|(?<=der )|(?<=Fraktion )|(?<=Gruppe ))"


def _gemischt(wort):
    """Muster für „Grüne“/„Linke“ in gemischter Schreibung nach den Regeln oben."""
    return rf"(?:{_PARTEI_DAVOR}{wort}(?!\w){_SACHWORT}|{wort}(?!\w){_SACHWORT}{_FOLGEWORT})"


# Fraktionen, Gruppen und Einzelmandate im Kölner Rat 2020–2025 und 2025–2030 (fraktionen_rat.tsv, Bezirksvertretungen
# fraktionen_bv.tsv). Aus dem Titel erkannte Einreichende bleiben abgeleitet (method „title“, evidence = Fundstelle).
# Reihenfolge zählt: Längere Bezeichnungen stehen vor ihren Teilen; ein Treffer verdeckt seine Stelle für alle
# folgenden Einträge („FDP/KSG“ zählt nicht zusätzlich als „FDP“ oder „KSG“, „GUT & KLIMA FREUNDE“ nicht als „GUT“).
#
# Regel FDP/KSG (Fraktion FDP/KSG im Rat, konstituiert 17.09.2025 laut fdp-koeln.de):
# 1. Schreibweise „FDP/KSG“ (auch „FDP / KSG“) ab 17.09.2025 → „FDP/KSG“, nie zusätzlich „FDP“ oder KSG.
# 2. „FDP-Fraktion“, „FDP Fraktion“, „FDP-Ratsfraktion“, „Fraktion der FDP“, „Fraktion FDP“ ab Beginn der Wahlperiode
#    2025–2030 (01.11.2025) → „FDP/KSG“: Im Rat 2025–2030 ist sie die einzige Fraktion mit Mitgliedern der FDP
#    (fraktionen_rat.tsv nennt „FDP-Fraktion“ als ungeprüfte Schreibvariante). Davor (auch in der Übergangszeit ab der
#    Wahl) bleibt es die FDP-Fraktion 2020–2025. Offen: „FDP“ in Aufzählungen nach „Fraktionen“ („Antrag der Fraktionen
#    SPD und FDP“) fällt unter Regel 3.
# 3. „FDP“ ohne „/KSG“ und ohne „Fraktion“ (z. B. „Anfrage der FDP“, Vorlagenart „FDP Antrag nach § 3“) bleibt „FDP“:
#    Das kann auch ein einzelnes Mitglied einer Bezirksvertretung sein (FDP dort je höchstens 1 Sitz, fraktionen_bv.tsv).
#    Aufzählungen mit Schrägstrich („CDU/FDP“) zählen; „FDP/KSG“ schließen Regel 1 (Verdeckung) und (?!\s*/\s*KSG) aus.
# 4. „KSG“ bzw. „Kölner Stadtgesellschaft“ allein erst ab der Kommunalwahl 14.09.2025 (vorher nicht im Rat).
PARTIES = [
    Partei("FDP/KSG", r"(?<!\w)FDP\s*/\s*KSG(?!\w)", r"FDP\s*/\s*KSG", von="2025-09-17"),
    Partei("FDP/KSG", r"(?<!\w)(?:FDP[- ](?:Rats)?[Ff]raktion|Fraktion (?:der )?FDP(?!\s*/))(?!\w)", r"FDP\s*/\s*KSG",
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
    Partei("Grüne", r"(?<![\w.])(?:GRÜNEN?(?!\w)|Bündnis\s*90(?:\s*/\s*Die\s+Grünen(?!\w))?|" + _gemischt("Grünen?")
           + ")", r"GRÜNE|Grüne"),
    Partei("FDP", r"(?<!\w)FDP(?!\s*/\s*KSG)(?!\w)", r"(?<!\w)FDP(?!\s*/\s*KSG)(?!\w)"),
    Partei("Kölner Stadtgesellschaft",
           r"(?<![\w/])(?<!/\s)KSG(?:(?![\w/-])|(?=" + _FRAKTION_ZUSATZ + "))|Kölner Stadtgesellschaft",
           r"^(?:KSG|Kölner Stadtgesellschaft)", von=KOMMUNALWAHL_2025),
    # nicht „Linkes Rheinufer“, „Linke Rheinseite“ (Ortsangaben)
    Partei("Die Linke", r"(?<!\w)(?:LINKE(?!\w)|Linksfraktion|" + _gemischt("Linken?") + ")", r"Linke|LINKE"),
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
# Ganze Wörter: nicht „Koalitionsvertrag“, aber „Koalitionsfraktionen“, „Interfraktioneller Antrag“
GROUPS = [
    ("Koalition", r"(?<!\w)[Kk]oalition(?:sfraktion(?:en)?)?(?!\w)"),
    ("interfraktionell", r"(?<!\w)[Ii]nterfraktionell(?:e[mnrs]?)?(?!\w)"),
]
UNRESOLVED = r"u\.\s?w\."
KEYWORD = re.compile(r"(?:Änderungs|Dringlichkeits)?[Aa]ntrag|Anfrage|(?<!\w)(?:AA|ÄA)(?!\w)")
# Ende der Einreichenden im Titel: „Antrag der Fraktionen SPD, GRÜNE und Volt betreffend …“ (Köln), „… zur …“, „…:“,
# öffnendes Anführungszeichen (Thema in Anführungszeichen) – außer direkt nach „Fraktion(en)“ oder „…gruppe“: Dort steht
# der Name selbst in Anführungszeichen („Antrag der Gruppe „Die PARTEI“ betreffend …“), bis zum schließenden Zeichen.
STOPP = re.compile(r"\s(?:betreffend|betr\.|bezüglich|bzgl\.|zum Thema|zur|zum|zu)(?=\s)|[:„“\"»]")
_NAME_IN_ZEICHEN = re.compile(r"(?:[Ff]raktion(?:en)?|[Gg]ruppe)\s*$")
_SCHLUSSZEICHEN = re.compile(r"[“”\"«»]")
# Zwischen zwei Einreichenden stehen nur Verbindungswörter und Satzzeichen: „Fraktionen SPD, GRÜNE und Volt“, „der
# SPD-Fraktion und der Fraktion Die Linke“, „Kölner Stadtgesellschaft (KSG)“, „CDU/FDP“, „im Rat der Stadt Köln“. Jedes
# andere Wort beendet die Einreichenden („Antrag der SPD-Fraktion Neugestaltung Volksgarten u.a. mit CDU“: nur SPD).
_VERBINDUNG = re.compile(
    r"(?:[\s,;&/()\[\].„“”\"»«'–-]|(?<!\w)(?:und|sowie|der|die|den|des|dem|von|aus|im|in|gemeinsam(?:\s+mit)?|Die|DIE|"
    r"Rat|Rates|Stadt|Köln|(?:Rats|Bezirks)?[Ff]raktion(?:en)?|(?:Rats|Wähler)?[Gg]ruppen?|Einzelmandat\w*|"
    r"Ratsmitglied\w*)(?!\w))*")
# Klassen (`classification`) der Organisationen von Fraktionen, Gruppen und Einzelmandaten im Rat bzw. in den
# Bezirksvertretungen („Bezirksfraktionen (intern)“): Werte aus Bonn und der Kölner Wert „Fraktionen und Gruppen“
# (Stufe 3, 09.11.2026: 23 Organisationen, `organizationType` fehlt bei allen, keine Bezirksfraktionen darunter; auch
# „Sachkundige Bürgerinnen und Bürger“, auf das kein Muster in PARTIES passt). Ohne passende Klasse bleibt
# organization_id leer.
RAT_CLASSES = ("Fraktion", "Gruppen", "Einzelmandate", "Fraktionen und Gruppen")


def _stopp(title, pos):
    """Erstes Schlusswort bzw. -zeichen ab pos (STOPP); Namen in Anführungszeichen nach „Fraktion“/„Gruppe“ zählen
    nicht als Ende."""
    while (s := STOPP.search(title, pos)):
        if s.group() in ("„", "“", '"', "»") and _NAME_IN_ZEICHEN.search(title, 0, s.start()):
            zu = _SCHLUSSZEICHEN.search(title, s.end())
            if zu:
                pos = zu.end()
                continue
        return s
    return None


def _segments(title):
    """Abschnitte (Anfang, Anker, Ende) des Titels mit den Einreichenden: Präfix vor dem ersten Doppelpunkt, sonst
    Fenster um „Antrag“/„Anfrage“: 40 Zeichen davor, danach bis „betreffend“, „zur“ usw. (höchstens 150 Zeichen), ohne
    solches Wort 60 Zeichen. Köln nennt mehrere Fraktionen vor „betreffend“; ein festes Fenster schnitte sie ab. Ab dem
    Anker (Ende von „Antrag“ usw.; beim Präfix vor dem Doppelpunkt sein Anfang) gilt die Kette der Einreichenden
    (_kette)."""
    head, sep, _ = title.partition(":")
    if sep and len(head) <= 100:
        yield 0, 0, len(head)
    for m in KEYWORD.finditer(title):
        stopp = _stopp(title, m.end())
        ende = stopp.start() if stopp and stopp.start() - m.end() <= 150 else m.end() + 60
        yield max(0, m.start() - 40), m.end(), min(ende, len(title))


def partei_muster():
    """{Anzeigename: Muster} aller Bezeichnungen je Fraktion oder Gruppe aus PARTIES, ohne Datumsregeln und ohne
    Verdeckung – für die Frage, ob ein Text eine Fraktion überhaupt nennt (Prüfung der Kurzfassungen)."""
    muster = {}
    for p in PARTIES:
        muster.setdefault(p.name, []).append(f"(?:{p.titel})")
    return {name: "|".join(m) for name, m in muster.items()}


def _gilt(partei, date):
    """Gilt die Bezeichnung am Datum der Vorlage? Ohne Datum: ja, außer bei Umdeutungen nach dem Datum."""
    d = (date or "")[:10]
    if not d:
        return not partei.nur_mit_datum
    return (not partei.von or d >= partei.von) and (not partei.bis or d <= partei.bis)


def _treffer(text, date, a=0, b=None):
    """[(Anfang, Ende, Anzeigename, Organisationsmuster)] aller Fundstellen von Fraktionen, die im Abschnitt text[a:b]
    beginnen, nach Position. Gesucht wird im ganzen Text, damit die Wortgrenzen am Rand des Abschnitts stimmen („… und
    Linke Rheinseite“). Jeder Treffer wird für die folgenden Einträge verdeckt (längere Bezeichnung vor ihren Teilen)."""
    b = len(text) if b is None else b
    rest, hits = text, []
    for p in PARTIES:
        if not _gilt(p, date):
            continue
        for m in re.finditer(p.titel, rest):
            if a <= m.start() < b:
                hits.append((m.start(), m.end(), p.name, p.org))
            rest = rest[:m.start()] + "\0" * (m.end() - m.start()) + rest[m.end():]
    return sorted(hits)


def _kette(text, hits, anker):
    """Einreichende aus den Fundstellen: alle vor dem Anker (z. B. „SPD-Antrag“, Vorlagenart „Die Linke Antrag nach
    § 3“), ab dem Anker die erste und jede weitere, die nur durch Verbindungswörter (_VERBINDUNG) von der vorigen
    getrennt ist.
    Ergebnis: [(Anzeigename, Organisationsmuster)] je Name einmal, und das Ende der Kette ab dem Anker (oder None)."""
    namen, ende = {}, None
    for start, stop, name, org in hits:
        if start >= anker:
            if ende is not None and not _VERBINDUNG.fullmatch(text, ende, start):
                break
            ende = stop if ende is None else max(ende, stop)
        namen.setdefault(name, org)
    return list(namen.items()), ende


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


def bv_vorlagenart(ptype):
    """(Nummer, Stadtbezirk, Text der ersten Klammer nach der Nummer) aus einer Vorlagenart „… BV<n> (<Fraktion>)“,
    auch ohne Klammer (Text "") oder mit Zusatz („(geändert)“), sonst None. Nummer außerhalb 1–9: Stadtbezirk None."""
    m = BV_ART.search(ptype or "")
    if not m:
        return None
    nr = int(m.group(1))
    return nr, STADTBEZIRKE[nr - 1] if 1 <= nr <= 9 else None, (m.group(2) or "").strip()


def _bezirksfraktion(name, org_pat, orgs, date, bezirk, method, evidence):
    """Zeile einer Bezirksfraktion; ohne Bezirk ohne Organisation."""
    return dict(actor=f"{name}-Bezirksfraktion" + (f" {bezirk}" if bezirk else ""), actor_type="Bezirksfraktion",
                organization_id=_match_org(orgs, org_pat, date, ("Bezirksfraktionen (intern)",), bezirk)
                if bezirk else None, method=method, evidence=evidence)


def _aus_vorlagenart_bv(ptype, orgs, date):
    """Bezirksfraktionen aus der Klammer einer Vorlagenart „… BV<n> (<Fraktion>)“ (strukturiert, method „paper_type“);
    nur erkannte Fraktionen und Gruppen aus PARTIES (keine Personennamen), sonst []."""
    bv = bv_vorlagenart(ptype)
    if not bv or not bv[2]:
        return []
    _, bezirk, klammer = bv
    namen, _ = _kette(klammer, _treffer(klammer, date), 0)
    return [_bezirksfraktion(name, org_pat, orgs, date, bezirk, "paper_type", ptype) for name, org_pat in namen]


def originators(paper, orgs, bezirke=()):
    """Einreichende einer Vorlage als Liste von Zeilen (actor, actor_type, organization_id,
    method, evidence). `bezirke`: Stadtbezirke der befassten Bezirksvertretungen."""
    ptype, date = paper.get("paperType"), paper.get("date") or ""
    antwort = bool(ptype) and bool(ANTWORT_ART.search(ptype))   # die Verwaltung antwortet (keine Fraktion)
    if ptype in EINWOHNER_TYPES and not antwort:
        # Keine Namen natürlicher Personen (Datenschutz, CLAUDE.md 2).
        return [dict(actor="Einwohner:innen", actor_type="Einwohner:in", organization_id=None,
                     method="paper_type", evidence=ptype)]
    belegt = [] if antwort else _from_originator(paper, orgs)
    if belegt:
        return belegt
    if antwort or (ptype in VERWALTUNG_TYPES and ptype not in POLITIK_TYPES):
        org = (paper.get("underDirectionOf") or [None])[0]
        return [dict(actor="Verwaltung", actor_type="Verwaltung", organization_id=org,
                     method="paper_type", evidence=ptype)]
    if ptype not in POLITIK_TYPES:
        return []
    rows = _aus_vorlagenart_bv(ptype, orgs, date)   # Köln: „Antrag nach § 3 BV2 (CDU)“
    if rows:
        return rows
    bv = bv_vorlagenart(ptype)   # „Gem. Änderungsantrag BV3“: Fraktionen aus dem Titel als Bezirksfraktionen
    bv_bezirk = None if bv is None else (bv[1] or "")
    titel = paper.get("name") or ""
    for a, anker, b in _segments(titel):
        rows = _from_segment(titel, orgs, date, bezirke, a, b, anker, bv_bezirk, ptype)
        if rows:
            return rows
    # Köln: Partei oft in der Vorlagenart („FDP Antrag nach § 3“, Recherche 04.11.2026)
    return _from_segment(ptype, orgs, date, bezirke, bv_bezirk=bv_bezirk)


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


def _from_segment(text, orgs, date, bezirke, a=0, b=None, anker=None, bv_bezirk=None, vorlagenart=None):
    """Einreichende aus dem Abschnitt text[a:b] (Fundstelle = dieser Abschnitt); ab dem Anker als Kette (_kette).
    „Koalition“ und „interfraktionell“ zählen vor oder in der Kette oder direkt im Anschluss, nicht im Thema danach.
    `bv_bezirk`: Vorlage einer Bezirksvertretung laut Vorlagenart (Stadtbezirk, "" bei unbekannter Nummer): Fraktionen
    gelten als Bezirksfraktionen dieses Bezirks, nie als Ratsfraktionen."""
    b = len(text) if b is None else b
    seg = text[a:b].strip()
    rows = []
    bezirks_fraktion = "Bezirksfraktion" in seg or bv_bezirk is not None
    evidence = f"{seg} (Vorlagenart: {vorlagenart})" if bv_bezirk is not None and vorlagenart else seg
    namen, ende = _kette(text, _treffer(text, date, a, b), a if anker is None else anker)
    for name, org_pat in namen:
        if bezirks_fraktion:
            bezirk = (bv_bezirk or None) if bv_bezirk is not None else (
                next(iter(bezirke)) if len(bezirke) == 1 else None)
            rows.append(_bezirksfraktion(name, org_pat, orgs, date, bezirk, "title", evidence))
        else:
            org = _match_org(orgs, org_pat, date, RAT_CLASSES)
            rows.append(dict(actor=name, actor_type="Fraktion/Gruppe", organization_id=org,
                             method="title", evidence=seg))
    for name, pat in GROUPS:
        if any(a <= m.start() < b and (ende is None or m.start() < ende or _VERBINDUNG.fullmatch(text, ende, m.start()))
               for m in re.finditer(pat, text)):
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
