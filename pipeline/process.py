"""Prozessebene: Schritte je Vorlage mit Evidenzstatus (PROMPT_prozessebene_v0.1, Abschnitt 3–4).

Evidenzstatus
- belegt            Schritt ist als Datenobjekt in einer Quelle vorhanden (OParl-API der Stadt)
- abgeleitet        aus Quelldaten erschlossen (Join mit OParl-Lite, Textmuster, Vererbung)
- soll              nach Regelwerk zu erwarten, nicht dokumentiert (Soll-Modell noch nicht formalisiert)
- nicht_öffentlich  findet regelmäßig statt, ist extern nicht einsehbar
- unklar            aus öffentlichen Quellen nicht bestimmbar

Lücken werden als eigene Schritte ausgegeben, nicht weggelassen.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from .actors import EINWOHNER_TYPES, POLITIK_TYPES, VERWALTUNG_TYPES

BERLIN = ZoneInfo("Europe/Berlin")

SONDER_TYPES = {
    "Dringlichkeitsentscheidung OB": "Dringlichkeitsentscheidung der Oberbürgermeisterin bzw. des Oberbürgermeisters",
    "Dringlichkeitsentscheidung BV": "Dringlichkeitsentscheidung in der Bezirksvertretung",
    "Eilentscheidung HA": "Eilentscheidung im Hauptausschuss",
}
NICHTOEFFENTLICH_TYPE = "Tagesordnungspunkte in nichtöffentlicher Sitzung"
SCHLEIFE = ("vertagt", "verwiesen", "nicht aufgenommen", "weitere Lesung")
# Ergebnisse, die eine Beratung abschließen, ohne dass das Gremium entschieden hat (Code-Prüfung 24.10.2026:
# „nicht abgestimmt“ einer entscheidenden Beratung galt als Entscheidung, 326 Vorlagen)
KEIN_BESCHLUSS = ("nicht abgestimmt", "ohne Votum")
VOLLZUG = ("beschlossen",)

# Erläuterungen; in den Exporten steht nur der Schlüssel (`note`), die Texte stehen in der Seite.
NOTES = {
    "sonderweg": "Sonderweg: Entscheidung vor der Beratung, nachträgliche Genehmigung durch das Gremium.",
    "vorbereitung": "Erarbeitung, Mitzeichnung und Freigabe der Vorlage in der Verwaltung sind von "
                    "außen nicht einsehbar.",
    "datum": "Datum der Vorlage laut Ratsinformationssystem; ob es Erstellung, Freigabe oder "
             "Veröffentlichung bezeichnet, ist nicht dokumentiert.",
    "ohne_sitzung": "Beratung ist vorgesehen; Sitzung und Ergebnis sind (noch) nicht verknüpft.",
    "vollzug": "Ob und wann der Beschluss umgesetzt ist, steht in der Beschlusskontrolle; dafür gibt "
               "es keine öffentliche Schnittstelle.",
    "nichtoeffentlich": "Der Tagesordnungspunkt wurde nichtöffentlich beraten; Inhalte sind nicht einsehbar.",
    "datum_vor_vorlage": "Dieser Schritt liegt vor dem angegebenen Datum der Vorlage; die Quelle erklärt "
                         "die Abweichung nicht.",
}


def local_day(ts):
    """Kalendertag in Bonn; Sitzungszeiten aus OParl-Lite stehen in UTC (z. B. 22:30Z = 00:30 Uhr)."""
    if not ts:
        return None
    if len(ts) == 10:
        return ts
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt.astimezone(BERLIN) if dt.tzinfo else dt).date().isoformat()


def is_final(result):
    """Ergebnis, das die Beratung abschließt (nicht vertagt, verwiesen, nicht aufgenommen)."""
    return bool(result) and not any(k in result for k in SCHLEIFE)


def initiation_kind(paper_type):
    if paper_type in SONDER_TYPES:
        return "sonderweg"
    if paper_type == NICHTOEFFENTLICH_TYPE:
        return "nichtoeffentlich"
    if paper_type in EINWOHNER_TYPES:
        return "einwohner"
    if paper_type in POLITIK_TYPES:
        return "anfrage" if "Anfrage" in paper_type else "antrag"
    if paper_type in VERWALTUNG_TYPES:
        return "verwaltung"
    return "sonstige"


def steps(p):
    """Schrittfolge einer exportierten Vorlage (dict aus export._paper_detail)."""
    kind = initiation_kind(p["paper_type"])
    out = [{
        "typ": "initiierung", "label": p["paper_type"], "status": "belegt",
        "date": None, "source": "oparl-bonn", "source_object": p["source_object"],
        "note": "sonderweg" if p["paper_type"] in SONDER_TYPES else None,
        "actors": [o["actor"] for o in p["originators"]],
        "actors_status": "abgeleitet" if p["originators"] else None,
    }]
    if kind in ("verwaltung", "sonderweg"):
        out.append({"typ": "vorbereitung", "label": "Verwaltungsinterne Vorbereitung",
                    "status": "nicht_öffentlich", "date": None, "note": "vorbereitung"})
    out.append({"typ": "veroeffentlichung", "label": "Datum der Vorlage", "status": "belegt",
                "date": p["date"], "source": "oparl-bonn", "source_object": p["source_object"],
                "note": "datum"})
    if kind == "nichtoeffentlich":
        out.append({"typ": "beratung", "label": "Nichtöffentliche Beratung", "status": "nicht_öffentlich",
                    "date": None, "note": "nichtoeffentlich"})

    decided = False
    for s in p["process"]:
        day = local_day(s["start_date"])
        step = {
            "typ": "entscheidung" if s["authoritative"] else "beratung",
            "label": s["gremium"] or "Gremium unbekannt", "role": s["role"],
            "status": "belegt", "source": "oparl-bonn",
            "date": day, "date_status": "abgeleitet" if day else "unklar",
            "date_source": "oparl-lite" if day else None,
            "number": s["number"], "result": s["result"], "stand": s["status"],
            "result_source": "oparl-lite" if s["result"] or s["number"] else None,
            "note": None if day or s["result"] else "ohne_sitzung",
        }
        if day and p["date"] and day < p["date"]:
            step["note"] = "datum_vor_vorlage"
        if s["result"] and any(k in s["result"] for k in SCHLEIFE):
            step["schleife"] = True
        if s["authoritative"] and s["result"] and any(k in s["result"] for k in VOLLZUG):
            decided = True
        out.append(step)

    for sub in p["subordinated"]:
        early = sub.get("date") and p["date"] and sub["date"] < p["date"]
        out.append({"typ": "folgevorlage", "label": sub["paper_type"], "status": "belegt",
                    "date": sub.get("date"), "source": "oparl-bonn", "reference": sub["reference"],
                    "title": sub["name"], "note": "datum_vor_vorlage" if early else None})
    if decided:
        out.append({"typ": "vollzug", "label": "Umsetzung durch die Verwaltung", "status": "unklar",
                    "date": None, "note": "vollzug"})

    # Datierte Schritte nach Datum; eine undatierte Beratung folgt der vorigen in der Beratungsfolge,
    # undatierte Folgevorlagen stehen am Ende
    head = [s for s in out if s["typ"] in ("initiierung", "vorbereitung")]
    tail = [s for s in out if s["typ"] == "vollzug"]
    mid = [s for s in out if s not in head and s not in tail]
    keys, carry = [], p["date"] or ""
    for i, s in enumerate(mid):
        if s["date"]:
            if s["typ"] in ("beratung", "entscheidung"):
                carry = s["date"]
            keys.append((s["date"], i))
        elif s["typ"] == "folgevorlage":
            keys.append(("9999", i))
        else:
            keys.append((carry, i))
    mid = [s for _, s in sorted(zip(keys, mid), key=lambda x: x[0])]
    return head + mid + tail


STAENDE = ("entschieden", "beraten, ohne Entscheidung", "in Beratung", "offen", "ohne Beratungsfolge")


def stand(p):
    """Stand des Verfahrens (STAENDE):
    - entschieden: eine entscheidende Beratung hat ein abschließendes Ergebnis
    - beraten, ohne Entscheidung: alle Beratungen abgeschlossen, keine davon entscheidend
      (z. B. Mitteilungen und Stellungnahmen, die zur Kenntnis genommen wurden)
    - in Beratung: mindestens eine Beratung hat ein Ergebnis, andere stehen aus oder wurden vertagt
    - offen: noch keine Beratung mit Ergebnis"""
    s = p["process"]
    if not s:
        return "ohne Beratungsfolge"
    if any(x["authoritative"] and is_final(x["result"]) and not any(k in x["result"] for k in KEIN_BESCHLUSS)
           for x in s):
        return "entschieden"
    if not any(x["result"] for x in s):
        return "offen"
    if any(not is_final(x["result"]) for x in s):
        return "in Beratung"
    return "beraten, ohne Entscheidung"


def path_key(p):
    """Weg einer Vorlage für die Aggregatdarstellung: Gremien mit Rolle (in der Beratungsfolge), dann
    das Ergebnis der entscheidenden Beratung (wörtlich aus der Quelle) oder ersatzweise der Stand."""
    stations = [f"{s['gremium'] or '?'} ({s['role'] or '?'})" for s in p["process"]]
    final = next((s["result"] for s in reversed(p["process"]) if s["authoritative"] and s["result"]), None)
    return tuple(stations), final or stand(p), "ergebnis" if final else "stand"
