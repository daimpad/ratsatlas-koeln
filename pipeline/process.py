"""Prozessebene: Schritte je Vorlage mit Evidenzstatus (PROMPT_prozessebene_v0.1, Abschnitt 3–4).

Evidenzstatus
- belegt            Schritt ist als Datenobjekt in einer Quelle vorhanden (OParl-API der Stadt)
- abgeleitet        aus Quelldaten erschlossen (Verknüpfung von Beratung und Sitzung, Textmuster, Vererbung)
- soll              nach Regelwerk zu erwarten, nicht dokumentiert (Soll-Modell noch nicht formalisiert)
- nicht_öffentlich  findet regelmäßig statt, ist extern nicht einsehbar
- unklar            aus öffentlichen Quellen nicht bestimmbar

Lücken werden als eigene Schritte ausgegeben, nicht weggelassen.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config
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
    """Kalendertag in Köln (Europe/Berlin); Sitzungszeiten können in UTC stehen (z. B. 22:30Z = 00:30 Uhr)."""
    if not ts:
        return None
    if len(ts) == 10:
        return ts
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt.astimezone(BERLIN) if dt.tzinfo else dt).date().isoformat()


def massgeblich(tage, abgesagt=None):
    """Stelle des Eintrags, der zählt, unter Einträgen in ihrer Reihenfolge in der Beratungsfolge, je mit Sitzungstag
    (local_day) oder None (Entscheidung 17.11.2026 (15)): der späteste Sitzungstag, bei gleichem Tag der spätere
    Eintrag. Hat der letzte Eintrag keinen Sitzungstag (etwa ein neuer Termin, der noch nicht feststeht), zählt er wie
    vor der Entscheidung. `abgesagt`: je Eintrag, ob seine Sitzung abgesagt ist (`cancelled`); dann gilt die Regel nur
    unter den Einträgen ohne abgesagte Sitzung, auch für den letzten ohne Sitzungstag (Entscheidung 17.11.2026 (16)
    (A)). Sind alle abgesagt, gilt sie unter allen wie in (15) (Auslegung). None ohne Einträge."""
    if not tage:
        return None
    stellen = list(range(len(tage)))
    if abgesagt and not all(abgesagt):
        stellen = [i for i in stellen if not abgesagt[i]]
    if not tage[stellen[-1]]:
        return stellen[-1]
    return max((tage[i], i) for i in stellen if tage[i])[1]


def zaehlende(kennungen, tage, abgesagt=None):
    """Je Kennung der Beratung die Stelle ihres Eintrags, der für den Stand zählt ({Kennung: Stelle}), unter Einträgen
    in ihrer Reihenfolge in der Beratungsfolge, je mit Kennung, Sitzungstag (local_day oder None) und, wenn angegeben,
    ob die Sitzung abgesagt ist: nach massgeblich (Entscheidungen 17.11.2026 (15) (A) und (16) (A)); eine Kennung mit
    nur einem Eintrag zählt mit diesem."""
    je_kennung = {}
    for i, k in enumerate(kennungen):
        je_kennung.setdefault(k, []).append(i)
    return {k: stellen[massgeblich([tage[i] for i in stellen], abgesagt and [abgesagt[i] for i in stellen])]
            for k, stellen in je_kennung.items()}


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
        "date": None, "source": config.QUELLE_OPARL, "source_object": p["source_object"],
        "note": "sonderweg" if p["paper_type"] in SONDER_TYPES else None,
        "actors": [o["actor"] for o in p["originators"]],
        "actors_status": "abgeleitet" if p["originators"] else None,
    }]
    if kind in ("verwaltung", "sonderweg"):
        out.append({"typ": "vorbereitung", "label": "Verwaltungsinterne Vorbereitung",
                    "status": "nicht_öffentlich", "date": None, "note": "vorbereitung"})
    out.append({"typ": "veroeffentlichung", "label": "Datum der Vorlage", "status": "belegt",
                "date": p["date"], "source": config.QUELLE_OPARL, "source_object": p["source_object"],
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
            "status": "belegt", "source": config.QUELLE_OPARL,
            "date": day, "date_status": "abgeleitet" if day else "unklar",
            "date_source": config.QUELLE_SITZUNG if day else None,
            "number": s["number"], "result": s["result"], "stand": s["status"],
            "result_source": config.QUELLE_SITZUNG if s["result"] or s["number"] else None,
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
                    "date": sub.get("date"), "source": config.QUELLE_OPARL, "reference": sub["reference"],
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
    - offen: noch keine Beratung mit Ergebnis
    Bei einer Kennung mehrfach in derselben Vorlage übergibt export._paper_detail nur den Eintrag, der zählt
    (massgeblich), nach einer Vertagung also den neuen Termin."""
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


def path_key(p, kennungen):
    """Weg einer Vorlage für die Aggregatdarstellung: Gremien mit Rolle (in der Beratungsfolge), dann
    das Ergebnis der entscheidenden Beratung (wörtlich aus der Quelle) oder ersatzweise der Stand. `kennungen`: die
    Kennung der Beratung je Eintrag von p["process"] (intern, nicht im Export). Das Ende ist das Ergebnis des letzten
    entscheidenden Eintrags mit Ergebnis nach der Stelle; steht seine Kennung mehrfach in der Vorlage und hat ihr
    Eintrag, der für den Stand zählt (zaehlende, Entscheidung 17.11.2026 (15) (A), ohne abgesagte Sitzungen nach (16)
    (A)), ein Ergebnis, gilt dessen Ergebnis. Anders als vorher also nur, wenn die Einträge einer Kennung nicht nach dem
    Sitzungstag geordnet sind oder (seit (16)) wegen einer abgesagten Sitzung ein anderer Eintrag zählt; vorher
    widersprach das Ende dann dem Stand (etwa „vertagt“ bei „entschieden“)."""
    stations = [f"{s['gremium'] or '?'} ({s['role'] or '?'})" for s in p["process"]]
    zaehlt = zaehlende(kennungen, [local_day(s["start_date"]) for s in p["process"]],
                       [s.get("cancelled") for s in p["process"]])
    final = None
    for i in reversed(range(len(p["process"]))):
        s = p["process"][i]
        if s["authoritative"] and s["result"]:
            z = p["process"][zaehlt[kennungen[i]]]
            final = z["result"] if z["authoritative"] and z["result"] else s["result"]
            break
    # Stand wie im Export (export._paper_detail: bei einer Kennung mehrfach in derselben Vorlage nach dem Eintrag, der
    # zählt, massgeblich)
    return tuple(stations), final or p.get("stand") or stand(p), "ergebnis" if final else "stand"
