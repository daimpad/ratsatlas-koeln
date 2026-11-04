"""Verzeichnis der Gebäude und Anlagen (OSM, ODbL; `fetch-objects` → data/geo/objekte_bonn.json) für Stufe C.

Abgleich über den angeglichenen Namen: Groß- und Kleinschreibung, Satzzeichen, Bindestriche und typische Vorsätze
(„GGS“, „Kita“, „Städt.“, „ehem.“) zählen nicht. Ein Name zählt nur, wenn er in genau einem Ortsteil vorkommt; liegt
er in mehreren Ortsteilen („Alter Friedhof“), entscheidet der Ortsteil, den der Text nennt, sonst wird nicht
verortet. Ein kürzerer Name passt auf einen längeren, wenn er darin als ganze Wortfolge steht („Rheinaue“ →
„Freizeitpark Rheinaue“), mindestens acht Zeichen hat und dabei nur ein Ortsteil herauskommt. Nennt der Name mit
seinem Vorsatz eine Art („GGS“, „Kita“), muss ein solcher Teiltreffer von dieser Art sein („GGS Medinghoven“ ist nicht
„Burg Medinghoven“; KI-Vorprüfung der zweiten Stichprobe, 21.10.2026). Gattungsnamen („Spielplatz“, „Friedhof“)
zählen nie.
"""
import json
import re
from collections import defaultdict

from . import config

VORSAETZE = {"ggs", "kgs", "ogs", "ggs/ogs", "städt", "städtische", "städtischer", "städtisches", "kita", "kindertagesstätte",
             "ehem", "ehemalige", "ehemaliger", "ehemaliges", "die", "der", "das", "bonner"}
GATTUNG = {"spielplatz", "friedhof", "sportplatz", "turnhalle", "sporthalle", "schule", "grundschule", "kita",
           "kindergarten", "bibliothek", "stadtbibliothek", "park", "garten", "bolzplatz", "schulhof", "kirche",
           "rathaus", "schwimmbad", "hallenbad", "freibad", "feuerwache", "museum", "theater", "jugendzentrum",
           "bürgerhaus", "stadtteilbibliothek", "waldfriedhof", "parkfriedhof", "gesamtschule", "gymnasium",
           "realschule", "hauptschule", "förderschule", "mehrzweckhalle", "stadthalle", "altenheim"}
MIN_TEIL = 8
VORSATZ_ART = {"ggs": "Schule", "kgs": "Schule", "ogs": "Schule", "ggs/ogs": "Schule", "kita": "Kita",
               "kindertagesstätte": "Kita"}
# Titel (Stufe B, Methode „objekt_name“): strenger, weil kein Sprachmodell die Rolle prüft. Der Name muss mit
# Vorsatz im Titel stehen („Kita Rheinpiraten“, nicht „Rheinpiraten“), mindestens acht Zeichen lang und in Bonn
# eindeutig sein. Ausgenommen sind Schutzgebiete (große Flächen, oft über Bonn hinaus) und Namen, die im Titel meist
# eine Einrichtung meinen, nicht einen Ort.
TITEL_VORSAETZE = VORSAETZE - {"kita", "kindertagesstätte"}
TITEL_OHNE_ART = {"Schutzgebiet"}
TITEL_OHNE_NAME = {
    # Einrichtungen mit mehreren Standorten oder ohne festen Ort im Titel (Entgelte, Satzungen)
    "universität", "sparkasse kölnbonn", "volkshochschule", "ludwig van beethoven musikschule", "bundespolizei",
    "bahnhofsmission",
    # allgemeine Wörter und Personen (Prüfung der Treffer am 21.10.2026)
    "städtebau", "pavillon", "sporthallen", "spielhaus", "kreuzgang", "ludwig van beethoven",
}


def norm(name, vorsaetze=VORSAETZE):
    """Angeglichener Name; „Bonn“ und „Bonner“ zählen nirgends („Freizeitpark Bonner Rheinaue“)."""
    words = re.sub(r"[^\w/]+", " ", (name or "").lower().replace("-", " ")).split()
    while words and words[0].strip(".") in vorsaetze:
        words = words[1:]
    return " ".join(w for w in words if w not in ("bonn", "bonner"))


class Objekte:
    def __init__(self, data=None):
        if data is None:
            data = json.loads(config.OBJEKTE.read_text())["objekte"] if config.OBJEKTE.exists() else {}
        self.by_norm = defaultdict(dict)   # angeglichener Name → Ortsteil → Objekt (eines je Ortsteil)
        self.ohne_leer = {}                 # Name ohne Leerzeichen → angeglichener Name („Posttower“ → „post tower“)
        for osm, o in sorted(data.items()):
            n = norm(o["name"])
            # Namen mit Ziffer am Anfang sind meist Tafeln oder Vereine („1967 1. Bonner Fußgängerzone …“)
            if len(n) >= 4 and n not in GATTUNG and not o["name"][:1].isdigit():
                self.by_norm[n].setdefault(o["ortsteil"], dict(o, osm=osm))
                self.ohne_leer.setdefault(n.replace(" ", ""), n)
        # OSM-Kennung → Objekt (Stufe C legt Gebäude mit Kennung ab, nicht mit der Wortfolge des Modells)
        self.by_osm = {x["osm"]: x for by_ot in self.by_norm.values() for x in by_ot.values()}

    def im_titel(self, titel):
        """Gebäude und Anlagen, deren Name im Titel steht (Regeln für Titel siehe oben)."""
        if not hasattr(self, "_titel_re"):
            self.titel_by = {}
            for n, by_ot in self.by_norm.items():
                if len(by_ot) != 1 or n in TITEL_OHNE_NAME:
                    continue
                o = next(iter(by_ot.values()))
                key = norm(o["name"], TITEL_VORSAETZE)
                if len(key) >= MIN_TEIL and o["art"] not in TITEL_OHNE_ART and key not in GATTUNG:
                    self.titel_by.setdefault(key, o)
            keys = sorted(self.titel_by, key=len, reverse=True)
            self._titel_re = re.compile(r"(?:^| )(" + "|".join(map(re.escape, keys)) + r")(?= |$)") if keys else None
        if not self._titel_re:
            return []
        t, out = norm(titel, TITEL_VORSAETZE), []
        for m in self._titel_re.finditer(t):
            if self.titel_by[m.group(1)] not in out:
                out.append(self.titel_by[m.group(1)])
        return out

    def __len__(self):
        return len(self.by_norm)

    def finden(self, name, ortsteil_im_text=""):
        """(Objekt, Befund) für einen Namen; Objekt None, wenn kein eindeutiger Treffer."""
        n = norm(name)
        if len(n) < 4 or n in GATTUNG:
            return None, "Gattungsname"
        if n in TITEL_OHNE_NAME:   # Einrichtungen ohne festen Ort und allgemeine Wörter gelten auch hier nicht
            return None, "Einrichtung ohne festen Ort oder allgemeines Wort"
        cands = self.by_norm.get(n) or self.by_norm.get(self.ohne_leer.get(n.replace(" ", ""), ""))
        art = "Name"
        if not cands and len(n) >= MIN_TEIL:
            # kürzester passender Name je Ortsteil („LVR-Landesmuseum Bonn“ vor „…, Bibliothek“)
            pat = re.compile(rf"(^| ){re.escape(n)}( |$)")
            cands = {}
            for key in sorted((k for k in self.by_norm if pat.search(k)), key=len, reverse=True):
                for ot, o in self.by_norm[key].items():
                    cands[ot] = o
            art = "Teil des Namens"
            vorsatz = {VORSATZ_ART[w.strip(".")] for w in re.sub(r"[^\w/]+", " ", name.lower()).split()
                       if w.strip(".") in VORSATZ_ART}
            if vorsatz:
                cands = {ot: o for ot, o in cands.items() if o["art"] in vorsatz}
                if not cands:
                    return None, "Teil des Namens, aber andere Art als laut Vorsatz"
        if not cands:
            return None, "nicht im Verzeichnis"
        if len(cands) == 1:
            return next(iter(cands.values())), art
        if ortsteil_im_text in cands:
            return cands[ortsteil_im_text], f"{art}, Ortsteil laut Text"
        return None, f"mehrdeutig ({len(cands)} Ortsteile)"
