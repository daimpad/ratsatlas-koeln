"""Verortung aus dem Volltext der Hauptdokumente (Regeln der Stufe B auf den Text; Methoden „volltext_…“).

Texte: OParl-Lite (aus den PDFs der Stadt extrahiert), lokal in data/raw/texte.jsonl. Rahmen laut Antwort der Stadt
Bonn: Verarbeitung zulässig, keine Zitate und keine Auszüge. Gespeichert und veröffentlicht werden deshalb nur
erkannte Orte (normierter Name, Ortsteil), der Teil des Dokuments und die Zahl der Nennungen, nie Text.

Vorgehen (Messung an 200 Vorlagen ohne Ortsbezug, CLAUDE.md Abschnitt 8):
1. Bereinigen: Kopf bis zum Ende der Beratungsfolge (nennt Gremien wie „Bezirksvertretung Beuel“), wiederholte
   Zeilen (Kopf- und Fußzeilen), Gremiennamen und Dienstadressen werden ausgeblendet; Hauptteil und Anlagen getrennt.
2. Orte mit den Regeln der Stufe B (geocode.Gazetteer, mit Vorfilter für lange Texte); Gattungsnamen („Markt“)
   zählen nur mit Hausnummer.
3. Nur für Vorlagen ohne eigenen Ortsbezug aus Titel, Ort der Stadt oder Bebauungsplan. Mehr als MAX_ORTSTEILE
   Ortsteile gelten als Liste (stadtweit), ohne Verortung. Nur der Hauptteil zählt; Orte, die nur in Anlagen stehen,
   werden nicht verortet.
   „mittel“ nur, wenn der Ort mindestens zweimal genannt ist oder im Bezirk einer befassten Bezirksvertretung liegt
   und die Regel selbst „mittel“ ergibt; sonst „niedrig“. Ein Stadtbezirk allein (ohne Straße oder Ortsteil) zählt
   nur unter derselben Bedingung; einzelne Erwähnungen („im Stadtbezirk Beuel“) sind im Text häufig und unspezifisch.
"""
import json
import re
from collections import Counter

from . import config
from .geocode import GENERIC_NAMES

MAX_ORTSTEILE = 5
MIN_BEZIRKE_STADTWEIT = 3   # so viele Stadtbezirke im Text: stadtweit, kein Bezirk als Ort
# Im Text oft Fachbegriffe statt Straßen („Schulstraße“ als Verkehrsberuhigung vor Schulen); wie die Gattungsnamen
# des Titels nur mit Hausnummer (KI-Vorprüfung der Stichprobe, 20.10.2026)
GATTUNG = set(GENERIC_NAMES) | {"Schulstraße", "Forstweg"}
# Datenschutz (CLAUDE.md 5.2): Eingaben von Bürger:innen enthalten oft deren Anschrift; sie werden nicht aus dem
# Volltext verortet (es bleibt beim Ort der Stadt und beim Titel)
OHNE_VOLLTEXT = ("Bürgerantrag", "Anregungen und Beschwerden", "Einwohner")


def allowed(paper_type):
    return not (paper_type or "").startswith(OHNE_VOLLTEXT)


def einwohner_kette(papers):
    """Ids der Vorlagen aus der Einwohnerschaft und aller mit ihnen verbundenen Vorlagen (OParl-Rohdaten; wie
    chat.einwohner): Stellungnahmen und Mitteilungen zu einem Bürgerantrag nennen oft dieselbe Anschrift und werden
    ebenfalls nicht aus dem Volltext verortet (Code-Prüfung 24.10.2026)."""
    from . import chat
    ref = {p["id"]: p.get("reference") for p in papers}
    rel = lambda p, k: [{"reference": ref[x]} for x in (p.get(k) or []) if x in ref]
    kette = set(chat.einwohner([{"reference": p.get("reference"), "paper_type": p.get("paperType"), "name": p.get("name"),
                                 "superordinated": rel(p, "superordinatedPaper"), "subordinated": rel(p, "subordinatedPaper")}
                                for p in papers]))
    return {p["id"] for p in papers if p.get("reference") in kette}


# Titel ohne gemeinsamen Ort: Sammellisten nichtöffentlicher Punkte (oft Personalfragen) und Vorlagen zu Gesellschaften,
# deren Sitz nur als Absender im Text steht (KI-Vorprüfungen der Stufe C, 21. und 22.10.2026)
SAMMELLISTE = r"\b(Tagesordnungs)?punkt\w*\b.*nicht ?öffentlich|nicht ?öffentlich\w* (Tagesordnungs)?punkt"
TITEL_OHNE_ORT = re.compile(SAMMELLISTE + r"|Jahresabschluss|Wirtschaftsplan|Aufsichtsrat|Gesellschafterversammlung|"
                            r"Beteiligungsbericht|Lagebericht", re.I)


def titel_ohne_ort(name):
    return bool(TITEL_OHNE_ORT.search(name or ""))


def sammelliste(name):
    """Sammelliste nichtöffentlicher Punkte („Punkte der nichtöffentlichen Sitzung“): ohne eigenen Inhalt."""
    return bool(re.search(SAMMELLISTE, name or "", re.I))
REPEAT_MIN = 3   # Zeilen, die so oft vorkommen, gelten als Kopf- oder Fußzeile

HEAD = re.compile(r"^(Beschlussvorschlag|Mitteilung:?|Inhalt de[sr] .*|Fragestellung|Begründung.*|Sachverhalt|"
                  r"Text der Anfrage|Beschluss:?)\s*$")
ROLE = re.compile(r"(Anhörung|Empfehlung|Entscheidung|Kenntnisnahme|Vorberatung|Beratung)\s*$|\d{2}\.\d{2}\.\d{4}")
GREMIUM = re.compile(r"(Bezirksvertretung(en)?|Bezirksverwaltungsstelle|Bezirksbürgermeister(in)?|BV)\s+"
                     r"(Bad Godesberg|Beuel|Hardtberg|Bonn)\b")
ADRESSE = re.compile(r"(Stadthaus|Berliner Platz\s*2\b[^\n]{0,30}|Altes Rathaus|Markt\s*2?,?\s*53111|Bottlerplatz\s*1)")
ANLAGE = re.compile(r"^Anlage/?n?\s*:?\s*$", re.M)


def _blank(m):
    return " " * len(m.group(0))


def header_end(text):
    """Ende des Vorlagenkopfs: nach der Beratungsfolge bis zur ersten Überschrift oder ersten längeren Zeile."""
    lines = text.split("\n")
    offset = lambda k: sum(len(x) + 1 for x in lines[:k])
    for i, line in enumerate(lines[:80]):
        if line.strip() == "Beratungsfolge":
            for j in range(i + 1, min(i + 30, len(lines))):
                s = lines[j].strip()
                if HEAD.match(s) or not (ROLE.search(lines[j]) or len(s) < 45):
                    return offset(j)
            return offset(i + 1)
    return 0


def clean(text):
    """(Hauptteil, Anlagen) mit ausgeblendetem Kopf, wiederholten Zeilen, Gremiennamen und Dienstadressen."""
    text = text or ""
    he = header_end(text)
    text = " " * he + text[he:]
    counts = Counter(l.strip() for l in text.split("\n") if len(l.strip()) > 8)
    repeated = {k for k, v in counts.items() if v >= REPEAT_MIN}
    text = "\n".join(" " * len(l) if l.strip() in repeated else l for l in text.split("\n"))
    text = ADRESSE.sub(_blank, GREMIUM.sub(_blank, text))
    m = ANLAGE.search(text, he)
    return (text[:m.start()], text[m.start():]) if m else (text, "")


def _hits(gaz, text, bv):
    if not text.strip():
        return []
    rx = gaz.street_re_for(text)
    rows = gaz.locate(text, bv, street_re=rx if rx else False)
    return [r for r in rows if not (r["name"] in GATTUNG and r["method"] != "strasse+hausnummer")]


def locate(gaz, text, bv_bezirke=()):
    """Ortsbezüge aus einem Volltext: (Zeilen wie Gazetteer.locate mit method „volltext_…“, Befund für das Audit)."""
    bv = set(bv_bezirke)
    main, annex = clean(text)
    rows, part = _hits(gaz, main, bv), "Hauptteil"
    if not rows:
        # Orte nur in den Anlagen (Adressen anderer Stellen, Teilnehmendenlisten) waren in der Stichprobe meist
        # unpassend (3 von 5); sie werden nicht verortet
        return [], {"befund": "nur in Anlagen genannt, nicht verortet" if _hits(gaz, annex, bv) else "kein Ort"}
    ortsteile = {r["ortsteil"] for r in rows if r["ortsteil"]}
    if len(ortsteile) > MAX_ORTSTEILE:
        return [], {"befund": f"Liste ({len(ortsteile)} Ortsteile), nicht verortet", "teil": part}
    seen = Counter((r["level"], r["name"], r["ortsteil"]) for r in rows)
    out, done = [], set()
    for r in rows:
        key = (r["level"], r["name"], r["ortsteil"])
        if key in done:
            continue
        done.add(key)
        n = seen[key]
        strong = n >= 2 or (bv and r["bezirk"] in bv)
        if r["level"] == "stadtbezirk" and not strong:
            continue
        conf = "mittel" if strong and r["confidence"] == "mittel" else "niedrig"
        out.append(dict(r, method=f"volltext_{r['method']}", confidence=conf, nennungen=n, teil=part,
                        evidence=f"{'im Hauptteil' if part == 'Hauptteil' else 'in den Anlagen'} des Hauptdokuments "
                                 f"genannt: {r['name']}"))
    # drei und mehr Stadtbezirke: die Vorlage betrifft die Stadt, nicht einzelne Bezirke (KI-Vorprüfung der Stufe C,
    # 21.10.2026: Einzelhandelskonzept auf drei von vier Bezirke verortet)
    bezirke = {r["name"] for r in out if r["level"] == "stadtbezirk"}
    if len(bezirke) >= MIN_BEZIRKE_STADTWEIT:
        out = [r for r in out if r["level"] != "stadtbezirk"]
        if not out:
            return [], {"befund": f"{len(bezirke)} Stadtbezirke, stadtweit, nicht verortet", "teil": part}
    if not out:
        return [], {"befund": "nur einzelne Erwähnung eines Stadtbezirks", "teil": part}
    return out, {"befund": "verortet", "teil": part, "ortsteile": len(ortsteile)}


def load_texts():
    """Datei-URI (OParl `mainFile.id`) → Text (aus data/raw/texte.jsonl; leer, wenn die Datei fehlt)."""
    if not config.TEXTE.exists():
        return {}
    return {r["uri"]: r["text"] for r in map(json.loads, open(config.TEXTE, encoding="utf-8"))}
