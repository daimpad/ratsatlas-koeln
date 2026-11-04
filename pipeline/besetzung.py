"""Besetzung der Gremien aus der OParl-API der Stadt Bonn (Reiter „Prozesse“, Gremien).

Phase 0: gremien/phase0/BERICHT.md; Entscheidung 27.10.2026: Besetzung je Gremium mit Name, Rolle, Fraktion,
Beginn und Link zur Personenseite im Ratsinformationssystem, ohne Kontaktdaten.

Abruf (`fetch-besetzung`): Die Liste `persons` enthält die Mitgliedschaften jeder Person (Rolle, Gremium, Beginn, Ende;
gleich der Liste `memberships`, nur das Feld `votingRight` ist dort stets falsch und wird nicht genutzt). Gespeichert
wird in data/raw/besetzung.json nur ein Auszug der am Abruftag laufenden Mitgliedschaften:
- Name, akademischer Titel und Personenseite nur für Mitglieder und beratende Mitglieder von Rat, Ausschüssen,
  Bezirksvertretungen und Beiräten; nicht für Verwaltung und Fraktionsgeschäftsstellen, nicht für Beiräte mit
  Jugendmitgliedern (dort können Minderjährige vertreten sein), nicht für Stellvertretungen (nur gezählt)
- keine Anschrift, E-Mail, Telefonnummer, Anrede oder Geschlecht
- je Person die Fraktionen, Gruppen und Einzelmandate (Rat) und Bezirksfraktionen, um die Fraktion abzuleiten

Die Quelle nennt nicht, für welche Fraktion jemand in einem Gremium sitzt (`onBehalfOf` fehlt). Die Fraktion ist daher
abgeleitet: Mitgliedschaft in einer Fraktion des Rates bzw. in der Bezirksfraktion des Stadtbezirks. Sachkundige
Bürger:innen gehören meist keiner Fraktion an und bleiben ohne Angabe."""
import csv
import json
import re
from datetime import date

from . import config

PERSONEN_URL = f"{config.OPARL_BODY}/persons"
LIZENZ = "CC0 1.0 (OParl-API der Stadt Bonn)"
GREMIEN = {"Rat", "Ratsgremien", "Bezirksvertretungen", "Beiräte und Kommissionen"}
FRAKTIONEN_RAT = {"Fraktion", "Gruppen", "Einzelmandate"}
FRAKTIONEN_BEZIRK = {"Bezirksfraktionen (intern)"}
# Rollen laut Quelle; „Mitglied (Stv.)“ ist ein:e Stadtverordnete:r als Mitglied, keine Stellvertretung (abgeleitet)
ORDENTLICH = re.compile(r"^(?:Stadtverordnete/r|Mitglied(?: \(Stv\.\))?|Mitglied Ausschuss .+|Sachkundige/r (?:Bürger|Einwohner)/in|"
                        r"Sachk\. Bürger/in|Bezirksverordnete/r|Beiratsmitglied(?: Jugend)?|Vorsitz.*|\d\. stellv\. Vorsitz|"
                        r"Stellv\. Vorsitz|Bezirksbürgermeister/in|Stellvertretende/r Bezirksbürgermeister/in|Bürgermeister/in .+)$")
# Ratsmitglieder in der Bezirksvertretung nehmen mit beratender Stimme teil (§ 36 Abs. 6 GO NRW)
BERATEND = re.compile(r"^(?:Beratendes Mitglied.*|Stadtverordnete/r in Bezirksvertretung)$")
STELLV = re.compile(r"^Stellv\. (?:Mitglied|beratendes Mitglied)$")
SACHKUNDIG = re.compile(r"[Ss]achk")
VORSITZ = re.compile(r"Vorsitz|[Bb]ürgermeister/in")
# Gewählte Mitglieder stets mit Namen (die Quelle führt auch Stadtverordnete mit Status „Fraktionsgeschäftsstellen“);
# übrige Rollen ohne Namen, wenn die Person zur Verwaltung gehört
GEWAEHLT = re.compile(r"^(?:Stadtverordnete/r.*|Mitglied \(Stv\.\)|Bezirksverordnete/r|Vorsitz|Bürgermeister/in .+|"
                      r"Bezirksbürgermeister/in|Stellvertretende/r Bezirksbürgermeister/in)$")
OHNE_NAMEN_STATUS = {"Verwaltung"}
JUGEND = re.compile(r"Jugend")
AUDIT = "audit_besetzung.tsv"
VERBOTEN = ("email", "phone", "streetAddress", "postalCode", "locationObject", "gender", "formOfAddress")


def _kurz(oparl_id):
    """Kurze ID mit Art: „gr/45“ (Gremien und Fraktionen), „at/12“ (Verwaltungsbereiche), Personen nur die Nummer."""
    teile = (oparl_id or "").rstrip("/").split("/")
    return "/".join(teile[-2:]) if "organizations" in teile[:-2] else teile[-1]


def _num(k):
    art, _, n = k.rpartition("/")
    return (art, int(n) if n.isdigit() else 0)


def _aktiv(m, heute):
    return (m.get("startDate") or "0000") <= heute and (not m.get("endDate") or m["endDate"] >= heute)


def auszug(personen, orgs, heute):
    """Auszug der laufenden Mitgliedschaften (siehe Moduldoku); orgs: Organisationen nach OParl-ID."""
    lauf = [(p, m) for p in personen if not p.get("deleted") for m in (p.get("membership") or [])
            if not m.get("deleted") and _aktiv(m, heute) and m.get("organization") in orgs]
    jugend = {m["organization"] for _, m in lauf if JUGEND.search(m.get("role") or "")
              and orgs[m["organization"]].get("classification") == "Beiräte und Kommissionen"}
    out_p, out_m = {}, []
    for p, m in lauf:
        o = orgs[m["organization"]]
        cls, rolle = o.get("classification"), m.get("role") or ""
        pid = _kurz(p["id"])
        if cls in FRAKTIONEN_RAT | FRAKTIONEN_BEZIRK:
            if not o.get("endDate") or o["endDate"] >= heute:
                out_p.setdefault(pid, {"fraktionen": []})["fraktionen"].append(_kurz(o["id"]))
            continue
        if cls not in GREMIEN or not (ORDENTLICH.match(rolle) or BERATEND.match(rolle) or STELLV.match(rolle)):
            continue   # Schriftführung u. Ä.
        namentlich = (not STELLV.match(rolle) and m["organization"] not in jugend
                      and (GEWAEHLT.match(rolle) or not OHNE_NAMEN_STATUS & set(p.get("status") or [])))
        if namentlich:
            out_p.setdefault(pid, {"fraktionen": []}).update(
                {"name": p.get("name") or "", "titel": " ".join(p.get("title") or []), "web": p.get("web") or ""})
        out_m.append({"gremium": _kurz(o["id"]), "rolle": rolle, "seit": m.get("startDate"), "bis": m.get("endDate"),
                      "person": pid if namentlich else None,
                      **({"grund": "Beirat mit Jugendmitgliedern"} if m["organization"] in jugend else {})})
    # Personen nur mit Fraktion, aber ohne namentliche Mitgliedschaft in einem Gremium: nicht nötig
    namentlich_ids = {m["person"] for m in out_m if m["person"]}
    out_p = {k: v for k, v in out_p.items() if k in namentlich_ids}
    for v in out_p.values():
        v["fraktionen"] = sorted(set(v["fraktionen"]), key=_num)
    out_m.sort(key=lambda m: (_num(m["gremium"]), m["rolle"], m["person"] or "", m["seit"] or ""))
    return {"meta": {"quelle": PERSONEN_URL, "lizenz": LIZENZ, "stichtag": heute,
                     "hinweis": "Auszug: laufende Mitgliedschaften, ohne Kontaktdaten; Fraktion abgeleitet"},
            "personen": dict(sorted(out_p.items(), key=lambda kv: _num(kv[0]))),
            "mitgliedschaften": out_m}


def fetch():
    """Pipeline-Schritt `fetch-besetzung`: Personen mit Mitgliedschaften abrufen, Auszug in data/raw/besetzung.json."""
    from .fetch import _guard, _oparl_list, _stamp, _write
    personen = _oparl_list(PERSONEN_URL)
    orgs = {o["id"]: o for o in json.loads(config.ORGANIZATIONS.read_text())}
    doc = auszug(personen, orgs, date.today().isoformat())
    if config.BESETZUNG.exists():
        _guard("Besetzung", len(doc["mitgliedschaften"]), len(json.loads(config.BESETZUNG.read_text())["mitgliedschaften"]))
    if befunde := pruefen_auszug(doc):
        raise RuntimeError("Besetzung: " + "; ".join(befunde))
    _write(config.BESETZUNG, json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    _stamp("besetzung")
    print(f"Besetzung: {len(doc['mitgliedschaften'])} laufende Mitgliedschaften, {len(doc['personen'])} Personen namentlich")


def pruefen_auszug(doc):
    """Keine Kontaktfelder, keine Namen bei Stellvertretungen und Beiräten mit Jugendmitgliedern."""
    befunde = []
    text = json.dumps(doc, ensure_ascii=False)
    for f in VERBOTEN:
        if f'"{f}"' in text:
            befunde.append(f"Feld {f} im Auszug")
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        befunde.append("E-Mail-Adresse im Auszug")
    for m in doc["mitgliedschaften"]:
        if m["person"] and (STELLV.match(m["rolle"]) or m.get("grund")):
            befunde.append(f"Name bei {m['rolle']} ({m['gremium']})")
    return befunde


# --- Seite ---------------------------------------------------------------------------------------------------------
def _fraktion_name(o):
    name = o.get("name") or ""
    if o.get("classification") in FRAKTIONEN_BEZIRK:
        return re.sub(r"\s*Bezirksfraktion\b.*$", "", name) or name
    return re.sub(r"\s+im Rat der Stadt Bonn$", "", name)


def _bezirk(gremium_name):
    m = re.match(r"^Bezirksvertretung\s+(.+)$", gremium_name or "")
    return m.group(1) if m else None


def fraktion(person, by_id, bezirk=None):
    """Fraktion einer Person (abgeleitet): in einer Bezirksvertretung die Bezirksfraktion dieses Stadtbezirks, sonst
    die Fraktion, Gruppe oder das Einzelmandat im Rat. Gibt (Name, Hinweis) zurück; Name None, wenn keine oder mehrere.
    by_id: Organisationen nach kurzer OParl-ID."""
    kand = [by_id[f] for f in person.get("fraktionen", []) if f in by_id]
    if bezirk:
        bz = [o for o in kand if o.get("classification") in FRAKTIONEN_BEZIRK and (o.get("name") or "").endswith(bezirk)]
        if len(bz) == 1:
            return _fraktion_name(bz[0]), None
        kand = [o for o in kand if o.get("classification") == "Einzelmandate"] if not bz else bz
    else:
        kand = [o for o in kand if o.get("classification") in FRAKTIONEN_RAT]
    if len(kand) == 1:
        return _fraktion_name(kand[0]), None
    return None, ("mehrere Fraktionen" if kand else None)


def zusammenfassen(sitze, einzel):
    """Sitze nach Fraktion; ein Einzelmandat derselben Partei wie eine Fraktion oder Gruppe im selben Gremium (z. B.
    „AfD“ neben „AfD-Fraktion“) erscheint mit ihr zusammen (Entscheidung 27.10.2026), die Teile bleiben unter `aus`.
    Gruppen aus mehreren Parteien („BSW/SBI-Gruppe“) nehmen kein Einzelmandat auf."""
    gruppen = {}
    for name, n in sitze.items():
        ziel = name
        if name in einzel:
            partner = [k for k in sitze if k != name and k not in einzel and re.match(rf"{re.escape(name)}[- ]", k)]
            if len(partner) == 1:
                ziel = partner[0]
        gruppen.setdefault(ziel, []).append((name, n))
    out = []
    for ziel, teile in gruppen.items():
        n = sum(x for _, x in teile)
        if len(teile) == 1:
            out.append({"fraktion": ziel, "n": n})
            continue
        partei = next(t for t, _ in teile if t != ziel)
        out.append({"fraktion": partei, "n": n,
                    "aus": [{"fraktion": t if t == ziel else f"Einzelmandat {t}", "n": x}
                            for t, x in sorted(teile, key=lambda t: (t[0] != ziel, -t[1]))]})
    return sorted(out, key=lambda x: (-x["n"], x["fraktion"]))


def gremien(term_start, heute=None, path=None, orgs=None):
    """Besetzung je Gremium (Schlüssel: kurze OParl-ID) für prozessarten.json; Audit der ausgelassenen Einträge."""
    path = path or config.BESETZUNG
    if not path.exists():
        return {}, []
    doc = json.loads(path.read_text(encoding="utf-8"))
    orgs = orgs or {o["id"]: o for o in json.loads(config.ORGANIZATIONS.read_text())}
    by_id = {_kurz(k): v for k, v in orgs.items()}
    out, audit = {}, []
    for m in doc["mitgliedschaften"]:
        g = by_id.get(m["gremium"])
        if not g:
            continue
        gewaehlt = g.get("classification") in {"Rat", "Ratsgremien", "Bezirksvertretungen"}
        # Gremien des Rates und die Bezirksvertretungen sind mit der Wahlperiode neu besetzt; ältere Mitgliedschaften
        # ohne Enddatum sind Lücken der Quelle (Phase 0: 34 seit vor 2020)
        if g.get("endDate") and g["endDate"] < (heute or doc["meta"]["stichtag"]):
            audit.append([g.get("name"), m["rolle"], m["seit"] or "", "Gremium beendet"])
            continue
        if gewaehlt and term_start and (m["seit"] or "0000") < term_start:
            audit.append([g.get("name"), m["rolle"], m["seit"] or "", "Beginn vor der Wahlperiode"])
            continue
        b = out.setdefault(m["gremium"], {"ordentlich": [], "beratend": [], "stellvertretend": 0, "ohne_namen": 0,
                                          "ohne_namen_grund": set()})
        rolle = m["rolle"]
        if STELLV.match(rolle):
            b["stellvertretend"] += 1
            continue
        p = doc["personen"].get(m["person"]) if m["person"] else None
        fr, hinweis = fraktion(p, by_id, _bezirk(g.get("name"))) if p else (None, None)
        if not p:
            b["ohne_namen"] += 1
            b["ohne_namen_grund"].add(m.get("grund") or "Verwaltung")
            if not ORDENTLICH.match(rolle):
                continue
        eintrag = {"name": p["name"], "titel": p.get("titel") or None, "web": p.get("web") or None, "rolle": rolle,
                   "fraktion": fr, "seit": m["seit"], "sachkundig": bool(SACHKUNDIG.search(rolle)),
                   "vorsitz": bool(VORSITZ.search(rolle))} if p else {"rolle": rolle, "fraktion": None, "sachkundig": False,
                                                                       "vorsitz": bool(VORSITZ.search(rolle))}
        if hinweis:
            eintrag["fraktion_hinweis"] = hinweis
        (b["ordentlich"] if ORDENTLICH.match(rolle) else b["beratend"]).append(eintrag)
    einzel = {_fraktion_name(o) for o in orgs.values() if o.get("classification") == "Einzelmandate"}
    for gid, b in out.items():
        sitze = {}
        for e in b["ordentlich"]:
            if e["fraktion"]:
                sitze[e["fraktion"]] = sitze.get(e["fraktion"], 0) + 1
        b["sitze"] = zusammenfassen(sitze, einzel)
        b["ohne_fraktion"] = sum(1 for e in b["ordentlich"] if not e["fraktion"])
        b["sachkundig"] = sum(1 for e in b["ordentlich"] if e["sachkundig"])
        b["sitze_gesamt"] = len(b["ordentlich"])
        b["ordentlich"] = sorted([e for e in b["ordentlich"] if e.get("name")],
                                 key=lambda e: (not e["vorsitz"], e["sachkundig"], e["fraktion"] or "~", e["name"]))
        b["beratend"] = sorted([e for e in b["beratend"] if e.get("name")], key=lambda e: (e["fraktion"] or "~", e["name"]))
        b["ohne_namen_grund"] = sorted(b["ohne_namen_grund"])
        if not b["ohne_namen"]:
            del b["ohne_namen_grund"]
    return out, audit


def write_audit(audit):
    with open(config.EXPORT / AUDIT, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["gremium", "rolle", "seit", "grund"])
        wr.writerows(sorted(audit))
