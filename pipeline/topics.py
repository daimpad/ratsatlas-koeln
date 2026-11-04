"""Themen und Parteien je Vorlage (abgeleitet, mit Fundstelle).

Themen: zehn übergeordnete Themen aus drei Hinweisen, jeweils mit Methode, Fundstelle und Konfidenz:
- Amt: federführendes oder fachlich zuständiges Amt (Amtsnummer bzw. Name) – „mittel“
- Gremium: beratender Fachausschuss oder Beirat (ohne Rat, Hauptausschuss, Bezirksvertretungen) – „mittel“
- Stichwort im Titel – „niedrig“
Parteien: aus den abgeleiteten Einreichenden; Bezirksfraktionen zählen zu ihrer Partei, Koalitions- und
interfraktionelle Anträge bleiben eigene Kategorien (die Quelle nennt die beteiligten Fraktionen nicht)."""
import re

THEMES = [
    ("verkehr", "Verkehr und Mobilität"),
    ("bauen", "Bauen und Stadtentwicklung"),
    ("umwelt", "Umwelt, Grün und Klima"),
    ("bildung", "Schule und Bildung"),
    ("kinder", "Kinder, Jugend und Familie"),
    ("soziales", "Soziales, Wohnen und Gesundheit"),
    ("kultur", "Kultur und Sport"),
    ("wirtschaft", "Wirtschaft und Finanzen"),
    ("sicherheit", "Sicherheit und Ordnung"),
    ("beteiligung", "Beteiligung, Integration und Internationales"),
]
RANK = {"mittel": 2, "niedrig": 1}

# Amtsnummer (erste zwei Ziffern der Klassifikation) → Thema
AMT = {"02": "beteiligung", "03": "wirtschaft", "05": "beteiligung", "20": "wirtschaft", "21": "wirtschaft",
       "32": "sicherheit", "37": "sicherheit", "40": "bildung", "41": "kultur", "46": "kultur", "50": "soziales",
       "51": "kinder", "52": "kultur", "56": "umwelt", "61": "bauen", "62": "bauen", "63": "bauen", "66": "verkehr",
       "67": "umwelt", "68": "umwelt", "85": "bauen"}
AMT_NAME = [(re.compile(r"Seniorenzentren"), "soziales")]
# Abteilungen, deren Thema vom Amt abweicht (Stichprobe 19.10.2026: 61-3 Stadtverkehr gehört zum Stadtplanungsamt,
# bearbeitet aber Verkehrsplanung)
AMT_UNIT = {"61-3": "verkehr"}

# Gremium (Name) → Thema; Reihenfolge zählt („Soziales, … Wohnen“ vor „Wohnen, Planung“).
# Sonderfälle in GREMIUM_SPECIAL werden vorher geprüft.
GREMIUM = [
    (r"Soziales|Senioren", "soziales"),
    (r"Mobilität|Verkehr", "verkehr"),
    (r"Planung|Planen|Bauen|Wohnen", "bauen"),
    (r"Umwelt|Klima|Baumkommission|Naturschutz", "umwelt"),
    (r"Schul", "bildung"),
    (r"Kinder|Jugend", "kinder"),
    (r"Sport|Kultur", "kultur"),
    (r"Finanzen|Wirtschaft|Liegenschaften|Rechnungsprüfung", "wirtschaft"),
    (r"Sicherheit|Ordnung|Katastrophenschutz", "sicherheit"),
    (r"Beteiligung der Bürger|Bürgerbeteiligung|Integration|Chancengerechtigkeit|Internationales|Europa", "beteiligung"),
]
GREMIUM_SPECIAL = [  # Namen, die sonst falsch zugeordnet würden
    (r"Betriebsausschuss SGB|Bau- und Vergabe|Denkmal", "bauen"),  # SGB = Städtisches Gebäudemanagement Bonn
    (r"Beethovenhalle", "kultur"),
]
NO_THEME_GREMIEN = re.compile(r"^(Rat|Hauptausschuss|Bezirksvertretung)\b")

# Stichworte im Titel (Kleinschreibung); Wortanfänge, damit z. B. „Baumaßnahme“ nicht als „Baum“ gilt
KEYWORDS = {
    "verkehr": r"radweg|radverkehr|fahrrad|\bparken|parkpl[aä]tz|parkraum|anwohnerpark|haltestelle|\bbus(se|linie|spur)?\b|"
               r"ampel|tempo ?30|\bverkehr|verkehrs|straßenbahn|stadtbahn|öpnv|kreuzung|gehweg|fußweg|zebrastreifen|"
               r"querungshilfe|carsharing|scooter|mobilität|einbahnstraße|umweltspur|sonderspur|fahrspur|ladezone|lieferzone",
    "bauen": r"bebauungsplan|flächennutzungsplan|bauvorhaben|neubau|wohnungsbau|bauleitpl|denkmal|städtebau|"
             r"quartiersentwicklung|baugenehmigung|bauantrag",
    "umwelt": r"\bbäume\b|\bbaum\b|baumfäll|baumschutz|baumpflanz|straßenbäume|klima|umwelt(?!spur)|naturschutz|grünfläche|"
              r"grünanlage|biotop|lärm|abfall|\bmüll|luftqualität|hochwasser|insekt|blühwiese|begrünung",
    "bildung": r"schule|gymnasium|\bogs\b|schulhof|schulweg|bildung",
    "kinder": r"\bkita|kindertages|spielplatz|jugend|\bkinder",
    "soziales": r"senior|obdach|wohnungslos|\bsozial|pflege|armut|gesundheit|geflüchtet|flüchtling|wohngeld|"
                r"bezahlbare[nr]? wohn|barriere",
    "kultur": r"kultur|museum|theater|\boper\b|beethoven|\bsport|schwimm|hallenbad|freibad|bibliothek|bücherei",
    "wirtschaft": r"haushalt|gebühr|steuer|wirtschaft|finanz|\bvergabe",
    "sicherheit": r"feuerwehr|ordnungsdienst|(?<!verkehrs)sicherheit|kriminal|rettungs|katastroph|videoüberwach",
    "beteiligung": r"bürgerbeteiligung|beteiligungsverfahren|integration|migration|partnerstadt|städtepartner|"
                   r"internationa|ehrenamt|einwohnerfrage",
}
KEYWORD_RX = {k: re.compile(v) for k, v in KEYWORDS.items()}


def _amt_theme(label, name=None):
    unit = re.match(r"(\d\d-\d)", name or "")
    if unit and unit.group(1) in AMT_UNIT:
        return AMT_UNIT[unit.group(1)]
    m = re.match(r"(\d\d)", label or "")
    if m and m.group(1) in AMT:
        return AMT[m.group(1)]
    return next((t for rx, t in AMT_NAME if rx.search(label or "")), None)


def _gremium_theme(name):
    if not name or NO_THEME_GREMIEN.match(name):
        return None
    for rx, t in GREMIUM_SPECIAL:
        if re.search(rx, name):
            return t
    return next((t for rx, t in GREMIUM if re.search(rx, name)), None)


def themes(p):
    """Themen einer exportierten Vorlage: [{theme, method, evidence, confidence}], je Thema der stärkste Hinweis."""
    hints = []
    for r in p["responsibility"]:
        t = _amt_theme(r.get("label"), r.get("name"))
        if t:
            unit = (r.get("name") or "")[:4] in AMT_UNIT
            hints.append((t, "amt", r["name"] if unit else r["label"], "mittel"))
    for s in p["process"]:
        t = _gremium_theme(s.get("gremium"))
        if t:
            hints.append((t, "gremium", s["gremium"], "mittel"))
    title = (p["name"] or "").lower()
    for t, rx in KEYWORD_RX.items():
        m = rx.search(title)
        if m:
            hints.append((t, "stichwort", m.group(0).strip(), "niedrig"))
    best = {}
    for t, method, evidence, conf in hints:
        if t not in best or RANK[conf] > RANK[best[t]["confidence"]]:
            best[t] = {"theme": t, "method": method, "evidence": evidence, "confidence": conf}
    order = [k for k, _ in THEMES]
    return sorted(best.values(), key=lambda x: order.index(x["theme"]))


def party(actor, actor_type):
    """Partei bzw. Kategorie für die Suche; None für nicht aufgelöste Einreichende."""
    if actor_type == "Bezirksfraktion":
        return actor.split("-Bezirksfraktion")[0]
    if actor_type == "unaufgelöst":
        return None
    return actor


def parties(p):
    return sorted({x for x in (party(o["actor"], o["actor_type"]) for o in p["originators"]) if x})
