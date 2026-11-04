"""Bebauungspläne: Plannummern in Vorlagentiteln mit den Geltungsbereichen der rechtskräftigen
Pläne der Stadt Bonn (CC0) abgleichen. Der Datensatz enthält nur rechtskräftige Pläne; Pläne im
Verfahren bleiben ohne Fläche."""
import json
import re

from shapely.geometry import shape
from shapely.ops import unary_union

from . import config

MIN_SHARE = 0.05  # Ortsteile mit weniger als 5 % der Planfläche bleiben unberücksichtigt


def plan_key(name):
    """„6322-2 Teil A“ → „6322-2“ (Teilpläne gehören zur Plannummer im Titel)."""
    return (name or "").split(" ")[0]


def canonical(nr):
    """Vergleichsform: „6322-2 Teil A“, „6622-2-A“, „7722-44 a“ → „6322-2A“, „6622-2A“, „7722-44A“."""
    n = re.sub(r"\s*Teil\s*", "", (nr or "").strip(), flags=re.I).upper()
    return re.sub(r"[\s-]+(?=[A-D]$|I{1,3}$)", "", n)


def base_number(nr):
    m = re.match(r"\d{4}-\d{1,3}", nr or "")
    return m.group(0) if m else None


# Treffer einer Plannummer im Datensatz der rechtskräftigen Pläne → Konfidenz der Verortung (B3)
CONFIDENCE = {"eindeutig": "hoch", "grundnummer": "niedrig", "mehrdeutig": "niedrig"}


class Plans:
    def __init__(self, path=config.BPLAN):
        self.by_nr, self.by_full, self.by_base = {}, {}, {}
        if path.exists():
            for f in json.loads(path.read_text())["features"]:
                name = f["properties"]["name"]
                self.by_nr.setdefault(plan_key(name), []).append(f)
                self.by_full.setdefault(canonical(name), []).append(f)
                self.by_base.setdefault(base_number(name), []).append(f)

    def match(self, nr):
        return self.classify(nr)[1]

    def classify(self, nr):
        """(Klasse, Features): eindeutig (genau ein Plan, ggf. Teilplan), grundnummer (Zusatz im Titel,
        im Datensatz nur die Grundnummer), mehrdeutig (mehrere Pläne), nicht_im_datensatz."""
        full, base = canonical(nr), base_number(nr)
        hits = self.by_full.get(full)
        if not hits:
            hits = self.by_base.get(base, [])
            if hits and full != base:
                return "grundnummer", hits
        names = {f["properties"]["name"] for f in hits}
        if not hits:
            return "nicht_im_datensatz", []
        return ("eindeutig" if len(names) == 1 else "mehrdeutig"), hits


def plan_locations(plan_rows, ortsteile, plans=None):
    """plan_rows: (paper_id, plannummer, fundstelle). Liefert Orte (je Plan und berührtem Ortsteil,
    Punkt = innerer Punkt der Schnittfläche) und Ortsbezüge der Stufe B (Methode B3: Konfidenz „hoch“
    bei eindeutigem Treffer, sonst „niedrig“)."""
    plans = plans or Plans()
    locations, rows = {}, []
    for pid, nr, evidence in plan_rows:
        cls, hits = plans.classify(nr)
        if not hits:
            continue
        by_name = {}
        for f in hits:  # mehrere Flächen desselben Plans (z. B. 7219-15) zusammenführen
            by_name.setdefault(f["properties"]["name"], []).append(shape(f["geometry"]).buffer(0))
        for name, geoms in by_name.items():
            parts = ortsteile.overlaps(unary_union(geoms))
            for ot, part, _ in [x for x in parts if x[2] >= MIN_SHARE] or parts[:1]:
                pt = part.representative_point()
                loc_id = f"bplan:{name}|{ot['ortsteil_bez']}"
                locations[loc_id] = (loc_id, None, None, None, f"Bebauungsplan {name}", round(pt.x, 6),
                                     round(pt.y, 6), ot["ortsteil_bez"], ot["ortsteil"], ot["bezirk_bez"],
                                     "bebauungsplan", "bplan-bonn")
                rows.append((pid, loc_id, "B", "bebauungsplan", CONFIDENCE[cls], evidence, pid))
    return locations, rows


# Verfahrensschritte der Bauleitplanung, aus dem Titel abgeleitet; Fundstelle im BauGB. Reihenfolge = Ablauf.
STEPS = [
    # „in Aufstellung befindlich“ beschreibt nur den Stand, keinen Beschluss
    ("aufstellung", "Aufstellungsbeschluss", "§ 2 Abs. 1 BauGB",
     r"aufstellungsbeschluss|beschluss (?:zur|über die) aufstellung|(?<!in )aufstellung (?:des|der|eines)|einleitung des \w*verfahrens|einleitungsbeschluss"),
    ("fruehzeitig", "Frühzeitige Beteiligung", "§ 3 Abs. 1, § 4 Abs. 1 BauGB", r"frühzeitig"),
    ("veroeffentlichung", "Veröffentlichung (Offenlage)", "§ 3 Abs. 2, § 4 Abs. 2 BauGB", r"veröffentlichung|offenlage|offenlegung|auslegung"),
    ("satzung", "Satzungsbeschluss", "§ 10 Abs. 1 BauGB", r"satzungsbeschluss|als satzung"),
]
KINDS = [("aenderung", r"\d\.\s*änderung|änderung des bebauungsplan"), ("aufhebung", r"aufhebung")]


def title_steps(title):
    """Verfahrensschritte und Art (Änderung, Aufhebung), die der Titel nennt – abgeleitet."""
    t = (title or "").lower()
    return ([k for k, _, _, rx in STEPS if re.search(rx, t)], [k for k, rx in KINDS if re.search(rx, t)])


def register(papers, plans=None):
    """Je Plannummer aus den Titeln: zugeordnete Pläne (belegt, Stadt Bonn), berührte Ortsteile und die
    Vorlagen chronologisch mit den im Titel genannten Verfahrensschritten (abgeleitet). Grundlage für die
    Planchronik; vereinfachte Verfahren (§§ 13, 13a BauGB) haben weniger Schritte."""
    plans = plans or Plans()
    out = {}
    for p in papers:
        for x in p.get("plans") or []:
            e = out.get(x["nr"])
            if e is None:
                cls, hits = plans.classify(x["nr"])
                seen = {}
                for f in hits:
                    seen.setdefault(f["properties"]["name"], {"name": f["properties"]["name"], **{
                        k: f["properties"].get(k) for k in ("inkraft_seit", "plan", "begruendung")}})
                e = out[x["nr"]] = {"nr": x["nr"], "treffer": cls, "plaene": sorted(seen.values(), key=lambda v: v["name"]),
                                    "ortsteile": set(), "vorlagen": []}
            e["ortsteile"] |= {l["ortsteil"] for l in p["locations"] if l["method"] == "bebauungsplan" and l.get("ortsteil")
                               and (l.get("name") or "").removeprefix("Bebauungsplan ") in {v["name"] for v in e["plaene"]}}
            steps, kinds = title_steps(p["name"])
            e["vorlagen"].append({"drucksache": p["reference"], "datum": p["date"], "titel": p["name"],
                                  "art": p["paper_type"], "stand": p.get("stand"), "schritte": steps, "arten": kinds,
                                  "fundstelle": x["evidence"]})
    for e in out.values():
        e["ortsteile"] = sorted(e["ortsteile"])
        e["vorlagen"].sort(key=lambda v: (v["datum"] or "", v["drucksache"]))
    return {"schritte": [{"id": k, "label": label, "fundstelle": ref} for k, label, ref, _ in STEPS],
            "plaene": sorted(out.values(), key=lambda e: e["nr"])}
