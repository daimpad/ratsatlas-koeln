"""Geokodierung Stufe B (regelbasiert, Titel): Straßen, Ortsteile, Stadtbezirke, Bebauungspläne.

Straßenverzeichnis: benannte OSM-Ways (ODbL), je Name zu Ortsteilen zugeordnet. Mehrere räumlich
getrennte Lagen desselben Namens gelten als mehrdeutig (z. B. „Kapellenstraße“). Ergänzend dienen
die Straßenpunkte der OParl-Locations (Stufe A, CC0) für Namen, die in OSM (noch) fehlen.

Kreuzungen: Für je zwei Straßen, deren Linien sich berühren, werden die Ortsteile der Berührungspunkte
gespeichert. Nennt ein Titel zwei solche Straßen, gilt der Ortsteil der Kreuzung (Regel R1,
verortung/PRUEFUNG.md).

Hausnummern: Folgt einer Straße im Titel eine Hausnummer, die das Verzeichnis der Stadt genau einem
Ortsteil zuordnet, gilt dieser Ortsteil (Vorrang vor Ortsteilname, Kreuzung und Bezirk; ein genannter
Ortsteil derselben Straße wird dann nicht zusätzlich verortet, er meint meist die Gemarkung). Die Nummer
bestimmt nur den Ortsteil; angezeigt wird weiter der Straßenabschnitt, Fundstelle ohne Nummer.
"""
import json
import math
import re
from collections import defaultdict

import shapely
from shapely import STRtree
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

from . import config

# Lokale Projektion in Metern (gleichabständig, ausreichend für Bonn)
KY = 111_320.0
KX = KY * math.cos(math.radians(50.7))
to_m = lambda geom: shapely.transform(geom, lambda c: c * (KX, KY))
to_deg = lambda geom: shapely.transform(geom, lambda c: c / (KX, KY))

# Ways ohne Straßencharakter (Haltestellen, Planungen) bleiben außen vor.
SKIP_HIGHWAY = {"platform", "bus_stop", "proposed", "construction", "elevator", "corridor", "razed",
                "abandoned", "disused"}
COMPONENT_GAP_M = 150   # Abstand, ab dem gleichnamige Abschnitte als getrennte Lagen gelten
MIN_SHARE, MIN_LENGTH_M = 0.15, 150  # Ortsteil zählt ab diesem Längenanteil bzw. dieser Länge

# Schreibvarianten der Ortsteilnamen in Titeln
ORTSTEIL_ALIASES = {
    "Lessenich/Meßdorf": ["Lessenich", "Meßdorf", "Messdorf"],
    "Pützchen/Bechlinghoven": ["Pützchen", "Bechlinghoven"],
    "Schwarzrheindorf / Vilich-Rheindorf": ["Schwarzrheindorf", "Vilich-Rheindorf"],
    "Vilich- Müldorf": ["Vilich-Müldorf", "Müldorf"],
    "Bonn-Castell": ["Bonn-Castell", "Castell"],
    "Godesberg-Villenviertel": ["Godesberg-Villenviertel", "Villenviertel"],
}
BEZIRKE = {"Bad Godesberg": ["Bad Godesberg", "Godesberg"], "Beuel": ["Beuel"], "Hardtberg": ["Hardtberg"]}
# R3 (verortung/PRUEFUNG.md): Schreibvarianten aus den Vorlagentiteln, von Hand aus den Kandidaten mit
# Editierdistanz 1–2 zu einem Ortsteilnamen ausgewählt (20.10.2026); Methode „…_variante“, Konfidenz wie der Name.
# Nicht aufgenommen: andere Orte (Medinghoven, Godesburg, Mondorf, Roisdorf) und Straßennamen (Pützchens Chaussee).
ORTSTEIL_VARIANTEN = {
    "Poppelsdorf": ["Poppeldorf"],
    "Plittersdorf": ["Plitterdorf"],
    "Pennenfeld": ["Pennefeld"],
    "Holtorf": ["Holtdorf"],
    "Schwarzrheindorf / Vilich-Rheindorf": ["Schwarz-Rheindorf"],
}
BEZIRK_VARIANTEN = {"Bad Godesberg": ["Bad-Godesberg", "Goesberg"], "Beuel": ["Beuler"]}
# „Pützchens“ ist in Titeln Teil von Eigennamen („Pützchens Markt“, „Pützchens Chaussee“ durch vier Ortsteile), kein Genitiv
GENITIV_AUSNAHMEN = {"Pützchen"}
# Namen, die im Titel oft nicht die Straße meinen (oder mehrere Lagen haben): Konfidenz niedrig
# Hausnummer direkt nach dem Straßennamen („Kennedyallee 25“, „Nr. 12a“, „12-14“); nicht „Str. 2. Bauabschnitt“
HAUSNUMMER = re.compile(r"\s+(?:Nr\.\s*)?(\d{1,4})(?=[a-zA-Z]?(?:\s|$|[,;)\-–/]))")
GENERIC_NAMES = {"Rheinufer", "Markt", "Kirchberg", "Wasserland"}
# Bebauungsplan-Nummern (Methode B3): Stichwort (auch Tippfehler, Plural, Bauleitplan, Satzung), danach eine
# oder mehrere Nummern NNNN-N(N) mit optionalem Zusatz (a, A, I, II, -A, „Teil A“); Präfix 6–8 wie im
# Plandatensatz der Stadt (Phase 0, baustellen/phase0/BERICHT.md). Flurstücke (NNNN-N-NNN) zählen nicht.
PLAN_NR = r"(?<![\d-])[6-8]\d{3}-\d{1,3}(?:\s?(?:[a-dA-D]|I{1,3}|-[A-D]|Teil [A-D])(?![\w-]))?"
PLAN = re.compile(r"(?i)(?:beba?u\w*pl[aä]n\w*|b-pl[aä]n\w*|bauleitplan\w*|satzung|vorhaben- und erschließungsplan\w*)"
                  r"[^;]{0,50}?(" + PLAN_NR + r"(?:\s*(?:,|und|/|sowie|bzw\.)\s*(?:Nr\.\s*)?" + PLAN_NR + r")*)")
PLAN_ONE = re.compile(r"(" + PLAN_NR + r")")
FLURSTUECK = re.compile(r"\d{4}-\d{1,3}-\d+")
STRASSE = re.compile(r"[Ss]traße$")


def _boundary(pattern, hyphen_before=False):
    """Wortgrenzen; bei Ortsnamen darf ein Bindestrich vorangehen („Bonn-Endenich“)."""
    before = r"(?<!\w)" if hyphen_before else r"(?<![\w-])"
    return rf"{before}(?:{pattern})(?![\w])"


def _street_pattern(name):
    """Regex für einen Straßennamen; „Straße“ auch als „Strasse“ oder „Str.“."""
    m = STRASSE.search(name)
    if not m:
        return re.escape(name)
    return re.escape(name[: m.start()]) + r"(?:[Ss]traße|[Ss]trasse|[Ss]tr\.)"


def _norm_street(text):
    """„Str.“ und „Strasse“ am Ende eines Treffers → „Straße“ (für die Rückzuordnung zum Namen)."""
    return re.sub(r"([Ss])(?:trasse|tr\.)$", r"\1traße", text)


def _word_key(name):
    """Anfang des ersten Worts (höchstens vier Buchstaben): „Im Bachele“ → „Im“, „Kaiserstraße“ → „Kais“."""
    return re.match(r"\w*", name).group(0)[:4]


def _alternation(names, pattern=re.escape, hyphen_before=False):
    """Eine Regex für alle Namen, längste zuerst (so gewinnt „Marienforster Steinweg“ vor
    „Steinweg“). Die Wortgrenzen stehen einmal um die ganze Liste statt um jeden Namen: gleiche Treffer
    (scheitert die Grenze dahinter, versucht die Regex den nächsten Namen), aber die Regex prüft die Namen
    nur an Wortanfängen; bei rund 6.000 Straßennamen etwa 40-mal schneller (Messung 26.10.2026)."""
    names = sorted(set(names), key=len, reverse=True)
    return re.compile(_boundary("|".join(pattern(n) for n in names), hyphen_before))


class Gazetteer:
    def __init__(self, ways=None, street_points=(), housenumbers=None):
        """`street_points`: (Name, lon, lat) aus den OParl-Locations der Stadt; `housenumbers`: Straße →
        Ortsteil → Nummern (Standard: Verzeichnis in data/geo, sofern vorhanden)."""
        ortsteile = json.loads(config.ORTSTEILE.read_text())["features"]
        bezirke = json.loads(config.STADTBEZIRKE.read_text())["features"]
        self.ortsteile = [f["properties"] for f in ortsteile]
        self.ot_geoms = [to_m(shape(f["geometry"])) for f in ortsteile]
        self.ot_tree = STRtree(self.ot_geoms)
        self.ot_point = {p["ortsteil_bez"]: to_deg(g.representative_point())
                         for p, g in zip(self.ortsteile, self.ot_geoms)}
        self.bezirk_point = {f["properties"]["bezirk_bez"]: shape(f["geometry"]).representative_point()
                             for f in bezirke}
        self.ot_by_name = {p["ortsteil_bez"]: p for p in self.ortsteile}
        if ways is None and config.STRASSEN.exists():
            data = json.loads(config.STRASSEN.read_text())
            self.streets = data["streets"]
            self.crossings = {tuple(k.split("|")): set(v) for k, v in data.get("kreuzungen", {}).items()}
        else:
            ways = ways if ways is not None else self._load_ways()
            self.streets = self._streets(ways)
            self.crossings = self._crossings(ways)
        self._add_points(street_points)
        if housenumbers is None and config.HAUSNUMMERN.exists():
            housenumbers = json.loads(config.HAUSNUMMERN.read_text())["strassen"]
        self.hnr = defaultdict(lambda: defaultdict(set))  # Straße → Nummer → Ortsteile
        for street, by_ot in (housenumbers or {}).items():
            for ot, numbers in by_ot.items():
                for nr in numbers:
                    self.hnr[_norm_street(street)][str(nr)].add(ot)

        # Ortsteilnamen, Varianten, Genitiv („Rüngsdorfs“) und Adjektive („Endenicher“) → Ortsteil
        self.ot_alias = {}
        for name in self.ot_by_name:
            forms = [(a, "ortsteil_name") for a in ORTSTEIL_ALIASES.get(name, [name])]
            forms += [(a, "ortsteil_variante") for a in ORTSTEIL_VARIANTEN.get(name, [])]
            for alias, method in forms:
                self.ot_alias[alias] = (name, method)
                if re.fullmatch(r"[A-ZÄÖÜ][a-zäöüß]+", alias):
                    self.ot_alias[alias + "er"] = (name, "ortsteil_adjektiv" if method == "ortsteil_name" else method)
                    if not alias.endswith(("s", "z")) and alias not in GENITIV_AUSNAHMEN:
                        self.ot_alias.setdefault(alias + "s", (name, method))
        self.bz_alias = {}
        for bezirk, aliases in BEZIRKE.items():
            for alias in aliases:
                self.bz_alias[alias] = (bezirk, "stadtbezirk_name")
                self.bz_alias[alias + "er"] = (bezirk, "stadtbezirk_adjektiv")
                self.bz_alias.setdefault(alias + "s", (bezirk, "stadtbezirk_name"))
            for alias in BEZIRK_VARIANTEN.get(bezirk, []):
                self.bz_alias[alias] = (bezirk, "stadtbezirk_variante")

        reserved = set(self.ot_alias) | set(self.bz_alias)
        street_names = [n for n in self.streets if n not in reserved and len(n) >= 4]
        self.street_re = _alternation(street_names, _street_pattern)
        # Vorfilter für lange Texte (Volltexte): Straßennamen nach dem Anfang ihres ersten Worts
        self.street_prefix = defaultdict(list)
        for n in street_names:
            self.street_prefix[_word_key(n)].append(n)
        self.ot_re = _alternation(self.ot_alias, hyphen_before=True)
        self.bz_re = _alternation(self.bz_alias, hyphen_before=True)

    @staticmethod
    def _load_ways():
        """Ways aus osm_streets.json, sonst aus den bisher zwischengespeicherten Kacheln."""
        if config.OSM_STREETS.exists():
            return json.loads(config.OSM_STREETS.read_text())["ways"]
        ways = {}
        for tile in sorted(config.OSM_TILES.glob("*.json")) if config.OSM_TILES.exists() else []:
            for el in json.loads(tile.read_text()):
                if el.get("geometry"):
                    ways[el["id"]] = {"name": el["tags"]["name"], "highway": el["tags"].get("highway"),
                                      "coords": [[q["lon"], q["lat"]] for q in el["geometry"]]}
        return list(ways.values())

    def _streets(self, ways):
        """Name → Liste von Lagen je Ortsteil: ortsteil, bezirk, lon, lat, length_m, component."""
        lines = defaultdict(list)
        for w in ways:
            if w.get("highway") in SKIP_HIGHWAY or len(w["coords"]) < 2:
                continue
            lines[w["name"].strip()].append(to_m(LineString(w["coords"])))
        streets = {}
        for name, parts in lines.items():
            merged = unary_union(parts)
            blobs = unary_union([p.buffer(COMPONENT_GAP_M / 2) for p in parts])
            comps = list(getattr(blobs, "geoms", [blobs]))
            entries = []
            for ci, comp in enumerate(comps):
                geom = merged.intersection(comp)
                total = geom.length or 1
                for idx in self.ot_tree.query(geom, predicate="intersects"):
                    part = geom.intersection(self.ot_geoms[idx])
                    if part.length < MIN_LENGTH_M and part.length / total < MIN_SHARE:
                        continue
                    longest = max(getattr(part, "geoms", [part]), key=lambda g: g.length)
                    pt = to_deg(longest.interpolate(0.5, normalized=True))
                    props = self.ortsteile[int(idx)]
                    entries.append({"ortsteil": props["ortsteil_bez"], "ortsteil_nr": props["ortsteil"],
                                    "bezirk": props["bezirk_bez"], "lon": round(pt.x, 6),
                                    "lat": round(pt.y, 6), "length_m": round(part.length),
                                    "component": ci, "source": "osm"})
            if entries:
                streets[name] = entries
        return streets

    def _crossings(self, ways):
        """(Name A, Name B) mit A < B → Ortsteile, in denen sich die beiden Straßen berühren."""
        lines = defaultdict(list)
        for w in ways:
            if w.get("highway") in SKIP_HIGHWAY or len(w["coords"]) < 2:
                continue
            lines[w["name"].strip()].append(LineString(w["coords"]))
        names = sorted(n for n in lines if n in self.streets)
        geoms = [to_m(unary_union(lines[n])) for n in names]
        if not geoms:
            return {}
        tree = STRtree(geoms)
        out = {}
        for i, j in zip(*tree.query(geoms, predicate="intersects")):
            if i >= j:
                continue
            touch = geoms[i].intersection(geoms[j])
            points = [g if g.geom_type == "Point" else g.representative_point()
                      for g in getattr(touch, "geoms", [touch]) if not g.is_empty]
            ots = set()
            for pt in points:
                for idx in self.ot_tree.query(pt, predicate="intersects"):
                    ots.add(self.ortsteile[int(idx)]["ortsteil_bez"])
            if ots:
                out[(names[i], names[j])] = ots
        return out

    def _add_points(self, street_points):
        for name, lon, lat in street_points:
            name = (name or "").strip()
            if not name or name in self.streets or lon is None:
                continue
            hits = self.ot_tree.query(to_m(Point(lon, lat)), predicate="intersects")
            if len(hits):
                props = self.ortsteile[int(hits[0])]
                self.streets[name] = [{"ortsteil": props["ortsteil_bez"], "ortsteil_nr": props["ortsteil"],
                                       "bezirk": props["bezirk_bez"], "lon": lon, "lat": lat,
                                       "length_m": None, "component": 0, "source": "oparl-bonn"}]

    # --- Erkennung im Titel ------------------------------------------------------------------

    @staticmethod
    def _find(regex, text, normalize=lambda t: t):
        return [(m.start(), m.end(), normalize(m.group(0)), m.group(0)) for m in regex.finditer(text)]

    @staticmethod
    def _mask(text, hits):
        for s, e, *_ in hits:
            text = text[:s] + " " * (e - s) + text[e:]
        return text

    def street_re_for(self, text):
        """Regex nur über die Straßennamen, deren erstes Wort (bis vier Buchstaben) im Text als Wortanfang vorkommt;
        gleiche Treffer wie street_re, bei langen Texten um ein Vielfaches schneller."""
        starts = {w[:4] for w in re.findall(r"\w{2,}", text)}
        names = [n for k in starts for n in self.street_prefix.get(k, ())]
        return _alternation(names, _street_pattern) if names else None

    def locate(self, title, bv_bezirke=(), street_re=None):
        """Ortsbezüge eines Titels als Zeilen mit level, name, ortsteil, bezirk, lon, lat,
        method, confidence, evidence. `bv_bezirke`: Stadtbezirke befasster Bezirksvertretungen;
        `street_re`: Straßen-Regex für diesen Text (street_re_for), sonst alle Straßennamen."""
        title = title or ""
        streets = self._find(street_re or self.street_re, title, _norm_street) if street_re is not False else []
        rest = self._mask(title, streets)
        ots = self._find(self.ot_re, rest)
        rest = self._mask(rest, ots)
        bzs = self._find(self.bz_re, rest)

        named_ot = {self.ot_alias[n][0] for *_, n, _ in ots}
        named_bz = {self.bz_alias[n][0] for *_, n, _ in bzs} | {self.ot_by_name[o]["bezirk_bez"] for o in named_ot}
        found = sorted({name for _, _, name, _ in streets if name in self.streets})
        rows = []
        for _, end, name, ev in streets:
            if name in self.streets:
                cross_ot = set().union(*[self.crossings.get(tuple(sorted((name, other))), set())
                                         for other in found if other != name])
                rows += self._resolve_street(name, ev, named_ot, named_bz, set(bv_bezirke), cross_ot,
                                             self._hnr_ortsteil(name, title, end))
        covered = {r["ortsteil"] for r in rows}
        # Hat die Hausnummer entschieden, gilt ein genannter Ortsteil derselben Straße als Gemarkung oder
        # Lagebezeichnung („Grundstück in Bonn-Friesdorf, Friesdorfer Straße 197“ liegt in Godesberg-Nord)
        covered |= {o for r in rows if r["method"] == "strasse+hausnummer" for o in r["hnr_vorher"]}
        for _, _, alias, ev in ots:
            ot, method = self.ot_alias[alias]
            if ot in covered:
                continue
            covered.add(ot)
            pt = self.ot_point[ot]
            conf = "mittel"
            if bv_bezirke and self.ot_by_name[ot]["bezirk_bez"] not in bv_bezirke:
                conf = "niedrig"
            rows.append(dict(level="ortsteil", name=ot, ortsteil=ot, bezirk=self.ot_by_name[ot]["bezirk_bez"],
                             lon=round(pt.x, 6), lat=round(pt.y, 6), method=method,
                             confidence=conf, evidence=ev))
        covered_bz = {r["bezirk"] for r in rows}
        for _, _, alias, ev in bzs:
            bz, method = self.bz_alias[alias]
            if bz in covered_bz:
                continue
            covered_bz.add(bz)
            pt = self.bezirk_point[bz]
            rows.append(dict(level="stadtbezirk", name=bz, ortsteil=None, bezirk=bz,
                             lon=round(pt.x, 6), lat=round(pt.y, 6), method=method,
                             confidence="mittel" if method in ("stadtbezirk_name", "stadtbezirk_variante") else "niedrig",
                             evidence=ev))
        return rows

    def _hnr_ortsteil(self, name, title, end):
        """Ortsteil der Hausnummer direkt hinter der Straße, wenn das Verzeichnis ihn eindeutig nennt."""
        m = HAUSNUMMER.match(title, end)
        if not m or 1900 <= int(m.group(1)) <= 2100:  # Jahreszahl („Kölnstraße 2025“)
            return None
        ots = self.hnr.get(name, {}).get(str(int(m.group(1))), set())
        return next(iter(ots)) if len(ots) == 1 else None

    def _resolve_street(self, name, evidence, named_ot, named_bz, bv_bezirke, cross_ot=frozenset(), hnr_ot=None):
        if hnr_ot:
            before = sorted({r["ortsteil"] for r in self._resolve_street(name, evidence, named_ot, named_bz,
                                                                         bv_bezirke, cross_ot)})
            hit = [e for e in self.streets[name] if e["ortsteil"] == hnr_ot]
            if hit:
                conf = "niedrig" if bv_bezirke and not ({e["bezirk"] for e in hit} & bv_bezirke) else "mittel"
                return [dict(level="strasse", name=name, ortsteil=e["ortsteil"], bezirk=e["bezirk"],
                             lon=e["lon"], lat=e["lat"], method="strasse+hausnummer", confidence=conf,
                             evidence=evidence, source=e["source"], hnr_vorher=before)
                        for e in hit]
            # Abschnitt im Ortsteil der Hausnummer fehlt im Straßenverzeichnis: Regel ohne Wirkung (Audit)
            return [dict(r, hnr_vorher=before, hnr_ohne_lage=hnr_ot)
                    for r in self._resolve_street(name, evidence, named_ot, named_bz, bv_bezirke, cross_ot)]
        entries = self.streets[name]
        ots = {e["ortsteil"] for e in entries}
        method, conf = "strasse", "niedrig" if name in GENERIC_NAMES else "mittel"
        if cross_ot & ots and not named_ot:
            # R1: Kreuzung mit einer anderen genannten Straße bestimmt den Ortsteil
            entries, method = [e for e in entries if e["ortsteil"] in cross_ot], "strasse+kreuzung"
        n_comp = len({e["component"] for e in entries})
        if named_ot & ots:
            entries = [e for e in entries if e["ortsteil"] in named_ot]
            method = "strasse+ortsteil"
        elif n_comp > 1:
            narrow = named_bz or bv_bezirke
            keep = [e for e in entries if e["bezirk"] in narrow] if narrow else []
            if keep and len({e["component"] for e in keep}) == 1:
                entries, method = keep, "strasse+bezirk"
            else:
                entries, method, conf = keep or entries, "strasse_mehrdeutig", "niedrig"
        elif bv_bezirke and not ({e["bezirk"] for e in entries} & bv_bezirke):
            conf = "niedrig"  # Straße liegt nicht im Bezirk der befassten Bezirksvertretung
        elif named_bz and not ({e["bezirk"] for e in entries} & named_bz):
            conf = "niedrig"  # Titel nennt einen anderen Bezirk („Beueler Rheinufer“)
        return [dict(level="strasse", name=name, ortsteil=e["ortsteil"], bezirk=e["bezirk"],
                     lon=e["lon"], lat=e["lat"], method=method, confidence=conf, evidence=evidence,
                     source=e["source"])
                for e in entries]


def plan_numbers(title):
    """[(Plannummer, Fundstelle)] aus dem Titel, je Nummer einmal."""
    text = FLURSTUECK.sub(" ", title or "")
    found = {}
    for m in PLAN.finditer(text):
        for n in PLAN_ONE.findall(m.group(1)):
            found.setdefault(re.sub(r"\s+", " ", n).strip(), m.group(0).strip())
    return list(found.items())


def write_gazetteer():
    """Straßenverzeichnis aus den OSM-Rohdaten neu berechnen und in data/geo ablegen."""
    gaz = Gazetteer(ways=Gazetteer._load_ways())
    stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
    crossings = {f"{a}|{b}": sorted(v) for (a, b), v in sorted(gaz.crossings.items())}
    config.STRASSEN.write_text(json.dumps({
        "meta": {"source": "OpenStreetMap (Overpass API), benannte Ways mit highway-Tag",
                 "license": config.SOURCES["osm"]["license"],
                 "retrieved_at": stand.get("osm_streets"),
                 "note": "Ortsteile je Straße per Verschneidung mit den Ortsteilflächen der Stadt Bonn; "
                         "component = räumlich getrennte Lage desselben Namens; kreuzungen = Ortsteile, in denen "
                         "sich zwei Straßen berühren (Schlüssel „Name A|Name B“)"},
        "streets": dict(sorted(gaz.streets.items())),
        "kreuzungen": crossings}, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(gaz.streets)} Straßennamen, {len(crossings)} Kreuzungen → {config.STRASSEN}")
