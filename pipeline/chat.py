"""Daten für die Werkzeuge des Ratsassistenten (site/chat/tools.js), unter data/export/bonn/chat/.

- vorlagen/NNNN.json  Vorlagen je Präfix der Drucksachennummer (erste vier Ziffern; Folgevorlagen liegen
                      bei ihrer Ausgangsvorlage), gekürzt auf die Felder, die der Assistent zitieren darf
- orte.json           Ortsbezüge (Straße, Ortsteil, Stadtbezirk, Bebauungsplan) mit Vorlagen, Stufe,
                      Methode und Konfidenz; Straßenebene ohne Hausnummern
- gremien.json        Gremien und Verwaltungsbereiche mit Zählungen und Thema (abgeleitet)
- datenstand.json     Abrufzeitpunkte, Lizenzen, Umfang, Verortungsquote, bekannte Lücken
- einwohner.json      Drucksachen, deren Titel ohne Hausnummer erscheinen (Titelmaske maske.aus_db: Einwohnerschaft,
                      Bauordnung und Naturschutz samt verbundenen Vorlagen, auch über relatedPaper, und derselben
                      Drucksache); der Assistent lässt in ihren Titeln und Fundstellen Hausnummern aus
                      (site/chat/tools.js)

Die Dateien tragen keine Erzeugungszeitpunkte (stabile Ausgaben); Abrufzeitpunkte stehen nur in
datenstand.json."""
import json
import re
from collections import Counter, defaultdict
from datetime import date

from . import config, topics
from .geocode import _vergleichstexte, eingabe

PAPER_FIELDS = ("reference", "name", "paper_type", "date", "amt", "web", "main_file", "source_object", "stand",
                "parties", "plans")
LOC_FIELDS = ("level", "name", "ortsteil", "stadtbezirk", "stage", "method", "confidence", "evidence")
REL_FIELDS = ("reference", "paper_type", "name", "date")

# wie EINWOHNER und EINWOHNER_TITEL in site/chat/tools.js (Assistent, in Köln abgeschaltet; die Kölner Ergänzung um
# geocode.eingabe und den Abgleich über die Vergleichstexte in aus_einwohnerschaft() fehlt dort noch und folgt mit der
# Freigabe des Assistenten)
EINWOHNER = {"Bürgerantrag § 24 GO - Öffentlich", "Anregungen und Beschwerden", "Einwohnerfrage", "Bürgerbrief"}
EINWOHNER_TITEL = re.compile(r"bürgerantrag|einwohner|anregung|beschwerde", re.I)
# EINWOHNER als Vergleichstexte (geocode._vergleichstexte: Normalform, kleingeschrieben, „Paragraf 24“ wie „§ 24“)
_EINWOHNER_VERGLEICH = {_vergleichstexte(art)[0] for art in EINWOHNER}

LUECKEN = [
    "Vorlagen vor Oktober 2019 sind nicht enthalten.",
    "Volltexte der Dokumente (PDF) werden nur zum Teil ausgewertet: für Orte, wenn Titel und Metadaten keinen nennen, "
    "und für gekennzeichnete Kurzfassungen; nicht für jede Vorlage liegt ein Text vor, und es gibt keine Zitate.",
    "Verwaltungsinterne Abläufe vor dem Datum der Vorlage sind nicht öffentlich.",
    "Inhalte nichtöffentlicher Beratungen sind nicht einsehbar.",
    "Den Vollzug von Beschlüssen zeigt keine öffentliche Schnittstelle (Beschlusskontrolle).",
    "Ergebnisse und Sitzungstermine der Beratungen stammen aus den Sitzungen und Tagesordnungspunkten der "
    "OParl-Schnittstelle (SessionNet); nicht jede Beratung ist verknüpft.",
    "Einreichende, Themen, Parteien und Ortsbezüge der Stufe B sind abgeleitet und nicht vollständig geprüft.",
    "Das Soll nach Regelwerk ist ein vereinfachtes Modell; abgeglichen wird nur, welche Gremienarten beraten haben.",
    "Abstimmungsergebnisse einzelner Fraktionen oder Personen sind nicht enthalten.",
]


def shard_key(reference):
    return reference[:4]


def compact(p):
    """Gekürzte Vorlage für den Assistenten; Felder und Werte unverändert aus dem Export."""
    d = {k: p[k] for k in PAPER_FIELDS}
    d["responsibility"] = [{"kind": r["kind"], "label": r["label"], "name": r["name"], "derived": bool(r["derived"])}
                           for r in p["responsibility"]]
    d["originators"] = [{"actor": o["actor"], "actor_type": o["actor_type"], "derived": bool(o["derived"]),
                         "evidence": o["evidence"]} for o in p["originators"]]
    d["themes"] = p["themes"]
    d["soll"] = p.get("soll")  # Soll nach Regelwerk (pipeline/soll.py), fehlt in älteren Exporten
    if p.get("kurzfassung"):   # nur freigegebene Kurzfassungen (kurzfassung.py), abgeleitet
        d["kurzfassung"] = {"text": p["kurzfassung"]["text"], "modell": p["kurzfassung"]["modell"]}
    d["locations"] = [{k: loc[k] for k in LOC_FIELDS} for loc in p["locations"]]
    d["superordinated"] = [{k: r[k] for k in REL_FIELDS} for r in p["superordinated"]]
    d["subordinated"] = [{k: r[k] for k in REL_FIELDS} for r in p["subordinated"]]
    d["steps"] = [{k: v for k, v in s.items() if k != "source_object"} for s in p["steps"]]
    return d


def places(papers):
    """Ortsbezüge gruppiert nach Ort: [{level, name, ortsteil, stadtbezirk, lon, lat, papers: [[Drucksache,
    Stufe, Methode, Konfidenz]]}]; je Ort und Vorlage ein Eintrag."""
    groups = {}
    for p in papers:
        for loc in p["locations"]:
            key = (loc["level"], loc["name"], loc["ortsteil"], loc["stadtbezirk"])
            g = groups.setdefault(key, {"level": loc["level"], "name": loc["name"], "ortsteil": loc["ortsteil"],
                                        "stadtbezirk": loc["stadtbezirk"], "lon": loc["lon"], "lat": loc["lat"],
                                        "papers": {}})
            if g["lon"] is None and loc["lon"] is not None:
                g["lon"], g["lat"] = loc["lon"], loc["lat"]
            g["papers"].setdefault(p["reference"], [p["reference"], loc["stage"], loc["method"], loc["confidence"]])
    out = []
    for key in sorted(groups, key=lambda k: tuple(x or "" for x in k)):
        g = groups[key]
        g["papers"] = sorted(g["papers"].values(), key=lambda r: r[0], reverse=True)
        out.append(g)
    return out


def organizations(db, papers, meetings, besetzt=None):
    """Gremien und Verwaltungsbereiche der OParl-API mit Zählungen aus den Vorlagen; laufende Gremien mit Besetzung
    (Vorsitz, Sitze nach Fraktion, abgeleitet; pipeline/besetzung.py), ohne weitere Namen."""
    led = Counter()
    for p in papers:
        for r in p["responsibility"]:
            if r["kind"] == "federfuehrend" and r["name"]:
                led[r["name"]] += 1
    consulted, deciding = Counter(), Counter()
    for p in papers:
        for s in p["process"]:
            if s["gremium"]:
                consulted[s["gremium"]] += 1
                if s["authoritative"]:
                    deciding[s["gremium"]] += 1
    held = Counter(m["gremium"] for m in meetings if not m["cancelled"])
    out = []
    for o in db.execute("SELECT id, name, short_name, org_type, classification, label, start_date, end_date, web "
                        "FROM organization ORDER BY org_type, name"):
        o = dict(o)
        d = {"name": o["name"], "short_name": o["short_name"], "type": o["org_type"],
             "classification": o["classification"], "start_date": o["start_date"], "end_date": o["end_date"],
             "web": o["web"], "source_object": o["id"]}
        if o["org_type"] == "Verwaltungsbereich":
            d["amt"] = o["label"]
            d["papers_led"] = led[o["name"]]
            d["theme"] = topics._amt_theme(o["label"])
        else:
            d["consultations"] = consulted[o["name"]]
            d["deciding"] = deciding[o["name"]]
            d["meetings"] = held[o["name"]]
            d["theme"] = topics._gremium_theme(o["name"])
            b = (besetzt or {}).get("/".join(o["id"].split("/")[-2:])) if not o["end_date"] else None
            if b:
                d["besetzung"] = {
                    "mitglieder": b["sitze_gesamt"], "sitze": b["sitze"], "ohne_fraktion": b["ohne_fraktion"],
                    "sachkundig": b["sachkundig"], "stellvertretungen": b["stellvertretend"], "beratend": len(b["beratend"]),
                    "vorsitz": sorted(({"name": e["name"], "rolle": e["rolle"], "fraktion": e["fraktion"]}
                                       for e in b["ordentlich"] if e["vorsitz"]),
                                      key=lambda v: (v["rolle"] != "Vorsitz", v["rolle"]))}
        out.append(d)
    return out


def data_status(sources, papers, meetings):
    dates = sorted(p["date"] for p in papers if p["date"])
    by_stage = Counter()
    for p in papers:
        stages = {loc["stage"] for loc in p["locations"]}
        by_stage["A" if "A" in stages else "B" if stages else "ohne"] += 1
    return {
        "sources": [{k: s.get(k) for k in ("name", "url", "license", "retrieved_at")} for s in sources],
        "papers": len(papers), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
        "meetings": len(meetings),
        "meetings_range": [meetings[0]["date"], meetings[-1]["date"]] if meetings else None,
        "located": {"stufe_a": by_stage["A"], "nur_stufe_b": by_stage["B"], "ohne_ortsbezug": by_stage["ohne"]},
        "gaps": LUECKEN,
    }


def _dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def aus_einwohnerschaft(paper_type, name):
    """Ausgangsvorlage aus der Einwohnerschaft nach Art oder Titel, ohne verbundene Vorlagen (Titelmaske und
    Volltextkette: maske.kette; geocode.punkt_ausschluss über maske.titel_ohne_hausnummer). Abgeglichen wird wie in der
    Punktregel über die Vergleichstexte (geocode._vergleichstexte), nicht die gelieferte Schreibung: „Buergerantrag“,
    „Bür\u00adgerantrag“ oder „Antrag nach Paragraf 24 GO NRW“ gelten wie die übliche Schreibung (Prüfung r20)."""
    art = paper_type if isinstance(paper_type, str) else "" if paper_type is None else str(paper_type)
    return bool(any(t in _EINWOHNER_VERGLEICH for t in _vergleichstexte(art))
                or any(EINWOHNER_TITEL.search(t) for t in _vergleichstexte(name))
                # Köln: dieselben Eingaben und Vorlagen natürlicher Personen wie in der Punktregel (geocode.eingabe auf
                # Art und Titel, eine Funktion: „Eingabe nach § 24 GO NRW“, „Einwohneranfrage nach § 39 Abs. 6“,
                # „… – Bürgereingabe“), damit eine Vorlage ohne Hauskoordinate ihre Hausnummer auch nicht im Titel
                # zeigt (Generalprobe 09.11.2026)
                or eingabe(paper_type, name))


def write_chat(out, db, cache, meetings, sources, meta):
    papers = sorted(cache.values(), key=lambda p: p["reference"])
    shards = defaultdict(dict)
    for p in papers:
        shards[shard_key(p["reference"])][p["reference"]] = compact(p)
    for key, items in shards.items():
        _dump(out / "vorlagen" / f"{key}.json", {"meta": meta, "papers": items})
    _dump(out / "orte.json", {"meta": meta, "places": places(papers)})
    from . import besetzung, prozessarten   # hier, weil prozessarten über maske chat importiert
    terms = json.loads(config.LEGISLATIVE_TERMS.read_text()) if config.LEGISLATIVE_TERMS.exists() else []
    besetzt = besetzung.gremien(prozessarten._term_start(terms, date.today().isoformat()))[0]
    _dump(out / "gremien.json", {"meta": meta, "organizations": organizations(db, papers, meetings, besetzt)})
    _dump(out / "datenstand.json", data_status(sources, papers, meetings))
    # Drucksachen, deren Titel ohne Hausnummer erscheinen: dieselbe Titelmaske wie in Export und Prüfung (maske.aus_db,
    # verbundene Vorlagen auch über relatedPaper; Runde 20), beschränkt auf die exportierten Vorlagen
    from . import maske   # hier, weil maske chat importiert
    refs = maske.aus_db(db).refs
    _dump(out / "einwohner.json", {"meta": meta, "drucksachen": sorted({p["reference"] for p in papers} & refs)})
    return len(shards)
