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
import unicodedata
from collections import defaultdict

import shapely
from shapely import STRtree
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

from . import config

# Lokale Projektion in Metern (gleichabständig, ausreichend für das Kölner Stadtgebiet)
KY = 111_320.0
KX = KY * math.cos(math.radians(50.94))
to_m = lambda geom: shapely.transform(geom, lambda c: c * (KX, KY))
to_deg = lambda geom: shapely.transform(geom, lambda c: c / (KX, KY))

# Ways ohne Straßencharakter (Haltestellen, Planungen) bleiben außen vor.
SKIP_HIGHWAY = {"platform", "bus_stop", "proposed", "construction", "elevator", "corridor", "razed",
                "abandoned", "disused"}
COMPONENT_GAP_M = 150   # Abstand, ab dem gleichnamige Abschnitte als getrennte Lagen gelten
MIN_SHARE, MIN_LENGTH_M = 0.15, 150  # Ortsteil zählt ab diesem Längenanteil bzw. dieser Länge

# Schreibvarianten der Stadtteilnamen in Titeln (Köln, vorläufig; Ausbau in Phase 3): Doppelnamen mit Schrägstrich
# auch mit Bindestrich oder Leerzeichen („Altstadt/Nord“, „Altstadt-Nord“, „Altstadt Nord“)
ORTSTEIL_ALIASES = {}


# Teile von Doppelnamen, die allein nicht eindeutig sind („Altstadt“, „Neustadt“: Nord oder Süd) oder oft etwas anderes
# meinen („Weiler“ als Gattungswort, „Humboldt“ in Eigennamen wie „Humboldt-Gymnasium“)
TEILNAMEN_AUSNAHMEN = {"Altstadt", "Neustadt", "Weiler", "Humboldt"}


def _doppelnamen(namen):
    """Doppelnamen mit Schrägstrich: ganzer Name auch mit Bindestrich oder Leerzeichen; dazu die Teilnamen
    („Rath/Heumar“ → „Rath“, „Heumar“), außer den Ausnahmen. Liefert Name → [(Alias, Methode)]."""
    out = {}
    for n in namen:
        if "/" in n:
            formen = [(f, "ortsteil_name") for f in (n, n.replace("/", "-"), n.replace("/", " "))]
            formen += [(t, "ortsteil_teilname") for t in n.split("/") if t not in TEILNAMEN_AUSNAHMEN]
            out[n] = formen
    return out


# Stadtbezirke: Acht der neun Kölner Stadtbezirke tragen den Namen eines Stadtteils (Porz, Kalk, Mülheim …), der neunte
# heißt „Innenstadt“. Der Bezirk gilt deshalb nur in eindeutiger Form als genannt: „Stadtbezirk Porz“, „Bezirk Porz“,
# „Bezirksvertretung Porz“, „Bezirksvertretung 7 (Porz)“, „BV 7“, „BV Porz“. Ein bloßes „Porz“ meint den Stadtteil.
BEZIRKE_KOELN = {1: "Innenstadt", 2: "Rodenkirchen", 3: "Lindenthal", 4: "Ehrenfeld", 5: "Nippes", 6: "Chorweiler",
                 7: "Porz", 8: "Kalk", 9: "Mülheim"}
BEZIRKE = {name: [f"Stadtbezirk {name}", f"Stadtbezirks {name}", f"Bezirk {name}", f"Bezirks {name}",
                  f"Bezirksvertretung {name}", f"Bezirksvertretung {nr} ({name})", f"Bezirksvertretung {nr}",
                  f"BV {nr}", f"BV {name}"]
           for nr, name in BEZIRKE_KOELN.items()}
ORTSTEIL_VARIANTEN = {}
BEZIRK_VARIANTEN = {}
GENITIV_AUSNAHMEN = set()
# Namen, die im Titel oft nicht die Straße meinen (oder mehrere Lagen haben): Konfidenz niedrig (Köln: Phase 3)
# Hausnummer direkt nach dem Straßennamen („Kennedyallee 25“, „Nr. 12a“, „12-14“); nicht „Str. 2. Bauabschnitt“
HAUSNUMMER = re.compile(r"\s+(?:Nr\.\s*)?(\d{1,4})(?=[a-zA-Z]?(?:\s|$|[,;)\-–/]))")
GENERIC_NAMES = {"Rheinufer", "Markt"}
# Bebauungsplan-Nummern (Methode B3): Stichwort (auch Tippfehler, Plural, Bauleitplan, Satzung), danach eine
# oder mehrere Nummern in Kölner Schreibweise NNNNN/NN (auch vier- und sechsstellig), wie sie die Landesschnittstelle
# als NNNNN.NN.000.00 führt (pipeline/bplan.py). Drucksachennummern (NNNN/JJJJ) haben vier Ziffern nach dem
# Schrägstrich und zählen nicht.
PLAN_NR = r"(?<![\d/.])\d{4,6}/\d{2}(?![\d/])"
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
    if not names:   # leere Liste (z. B. keine Bezirksnamen in Köln): nie treffen statt Leerstring treffen
        return re.compile(r"(?!x)x")
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
        aliases = _doppelnamen(self.ot_by_name)
        aliases.update({k: [(a, "ortsteil_name") for a in v] for k, v in ORTSTEIL_ALIASES.items()})
        if ways is None and config.STRASSEN.exists():
            data = json.loads(config.STRASSEN.read_text())
            self.streets = data["streets"]
            self.crossings = {tuple(k.split("|")): set(v) for k, v in data.get("kreuzungen", {}).items()}
        else:
            ways = ways if ways is not None else self._load_ways()
            self.streets = self._streets(ways)
            self.crossings = self._crossings(ways)
        self._add_points(street_points)
        self.hnr_punkte = {}   # Straße → Stadtteil → Hausnummer mit Zusatz → [lon, lat]
        if housenumbers is None and config.HAUSNUMMERN.exists():
            hnr_daten = json.loads(config.HAUSNUMMERN.read_text())
            housenumbers, self.hnr_punkte = hnr_daten["strassen"], hnr_daten.get("punkte", {})
        self.hnr = defaultdict(lambda: defaultdict(set))  # Straße → Nummer → Ortsteile
        for street, by_ot in (housenumbers or {}).items():
            for ot, numbers in by_ot.items():
                for nr in numbers:
                    self.hnr[_norm_street(street)][str(nr)].add(ot)

        # Ortsteilnamen, Varianten, Genitiv („Rüngsdorfs“) und Adjektive („Endenicher“) → Ortsteil
        self.ot_alias = {}
        for name in self.ot_by_name:
            forms = list(aliases.get(name, [(name, "ortsteil_name")]))
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
                                       "length_m": None, "component": 0, "source": config.QUELLE_OPARL}]

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

    def locate(self, title, bv_bezirke=(), street_re=None, punkt_erlaubt=False):
        """Ortsbezüge eines Titels als Zeilen mit level, name, ortsteil, bezirk, lon, lat,
        method, confidence, evidence. `bv_bezirke`: Stadtbezirke befasster Bezirksvertretungen;
        `street_re`: Straßen-Regex für diesen Text (street_re_for), sonst alle Straßennamen;
        `punkt_erlaubt`: Straße mit Hausnummer darf auf die Hauskoordinate gesetzt werden (nur Verwaltungsvorlagen
        und politische Anträge, siehe hausnummer_punkt_erlaubt)."""
        title = title or ""
        streets = self._find(street_re or self.street_re, title, _norm_street) if street_re is not False else []
        rest = self._mask(title, streets)
        # Köln: eindeutige Bezirksformen („Stadtbezirk Porz“) vor den Stadtteilnamen, sonst träfe „Porz“ den Stadtteil
        bzs = self._find(self.bz_re, rest)
        rest = self._mask(rest, bzs)
        ots = self._find(self.ot_re, rest)

        named_ot = {self.ot_alias[n][0] for *_, n, _ in ots}
        named_bz = {self.bz_alias[n][0] for *_, n, _ in bzs} | {self.ot_by_name[o]["bezirk_bez"] for o in named_ot}
        found = sorted({name for _, _, name, _ in streets if name in self.streets})
        rows = []
        for _, end, name, ev in streets:
            if name in self.streets:
                cross_ot = set().union(*[self.crossings.get(tuple(sorted((name, other))), set())
                                         for other in found if other != name])
                teil = self._resolve_street(name, ev, named_ot, named_bz, set(bv_bezirke), cross_ot,
                                            self._hnr_ortsteil(name, title, end))
                nr = self._hnr_nummer(title, end) if punkt_erlaubt else None
                rows += self._adresspunkt(name, nr, teil) or teil
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

    def _hnr_nummer(self, title, end):
        """Hausnummer mit Zusatz direkt hinter der Straße („12“, „12a“), keine Jahreszahl."""
        m = HAUSNUMMER.match(title, end)
        if not m or 1900 <= int(m.group(1)) <= 2100:
            return None
        zusatz = re.match(r"\s?([a-zA-Z])(?![a-zA-ZäöüÄÖÜß])", title[m.end(1):])
        return str(int(m.group(1))) + (zusatz.group(1).lower() if zusatz else "")

    def _adresspunkt(self, name, nr, teil):
        """Ersetzt die Straßenlagen durch die Hauskoordinate, wenn die Hausnummer in genau einem der Stadtteile
        dieser Lagen vorkommt (Methode „strasse+hausnummer_punkt“, Konfidenz hoch); sonst None."""
        if not nr or not teil:
            return None
        punkte = self.hnr_punkte.get(name, {})
        treffer = [(t, punkte[t].get(nr) or punkte[t].get(re.sub(r"\D", "", nr)))
                   for t in {r["ortsteil"] for r in teil} if t in punkte]
        treffer = [(t, xy) for t, xy in treffer if xy]
        if len(treffer) != 1:
            return None
        t, (lon, lat) = treffer[0]
        vorlage = next(r for r in teil if r["ortsteil"] == t)
        return [dict(level="adresse", name=name, hausnummer=nr, ortsteil=t, bezirk=vorlage["bezirk"], lon=lon,
                     lat=lat, method="strasse+hausnummer_punkt", confidence="hoch", evidence=vorlage["evidence"],
                     source=config.QUELLE_ADRESSEN,
                     **({"hnr_vorher": vorlage["hnr_vorher"]} if "hnr_vorher" in vorlage else {}))]

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


# Hausnummern punktgenau nur bei Verwaltungsvorlagen und politischen Anträgen (Entscheidung 04.11.2026); nie bei
# Anregungen und Beschwerden nach § 24 GO NRW oder Vorlagen natürlicher Personen
REFERENZ_PUNKT = re.compile(r"^(?:AN/)?\d{1,4}/\d{4}$")
# Eingaben und Vorlagen natürlicher Personen (Entscheidung 04.11.2026): auch Kölner Einwohneranfragen („Einwohneranfrage
# nach § 39 Abs. 6“, Stufe 2, explore/BERICHT_phase1.md 6.5; Drucksache wie Anträge AN/NNNN/JJJJ möglich) und
# Einwohnerfragen, Bürgeranträge, -anfragen und -fragen auch mit Trennzeichen und in Genderform („Bürger-Antrag“,
# „Einwohner*innenanfrage“, „Einwohner_innenanfrage“, „Bürger:innenantrag“, „Bürgerinnenantrag“, „Bürgerfragestunde“;
# Prüfung r20n). „Einwohnerbefragung“ ist hier keine Eingabe (Verwaltung), über chat.EINWOHNER_TITEL („einwohner“ im
# Titel) aber Ausgangspunkt der Titelmaske und damit ohne Hauskoordinate (Grund „maske“; Abwägung offen, TECHNIK.md).
# „§ 24“ auch ohne Leerzeichen und direkt vor Buchstaben („§24GO“, „§ 24GO NRW“; vorher verlangte \b eine Wortgrenze
# hinter der 24), nicht vor einer weiteren Ziffer („§ 240“; Prüfung r20a)
EINGABE = re.compile(r"(?i)§\s*24(?!\d)|anregung|beschwerde|eingabe|petition"
                     r"|bürger\W*(?:_?innen\W*)?(?:an)?(?:trag|frage)"
                     r"|einwohner\W*(?:_?innen\W*)?(?:an)?(?:trag|frage)")
# Hauskoordinate nur bei erkennbarer Vorlagenart (Entscheidung 10.11.2026): leer, nur Leerraum, null, nicht als Text
# geliefert oder ohne Treffer hier → keine Hauskoordinate, höchstens die Straße (wie bei Eingaben). Erkannt werden
# Verwaltungsvorlagen und politische Anträge und Anfragen, Groß- und Kleinschreibung egal, auch als Wortteil
# („Beschlussvorlage“, „Änderungsantrag“). Quellen: Köln, Stufe 1 und 2 (explore/BERICHT_phase1.md 5.7 und 6.5:
# „Antrag nach § 3 der GeschO des Rates“, „Anfrage nach § 4 der GeschO des Rates“, „Mitteilung BV“, „Antrag nach § 3
# BV2 (CDU)“, „Änderungsantrag BV1 (Grüne)“); Bonner bzw. übliche SessionNet-Arten wie in actors.POLITIK_TYPES und
# actors.VERWALTUNG_TYPES (Beschlussvorlage, Mitteilungsvorlage, Stellungnahme der Verwaltung, Informationsbrief,
# Dringlichkeitsentscheidung, Dringlichkeitsantrag, Große und Kleine Anfrage) und Antworten der Verwaltung
# („Beantwortung einer Anfrage (BV)“). Nie mit „Bürger“ (außer „Bürgermeister“, „Oberbürgermeisterin“), „Einwohner“,
# „Anwohner“, „privat“, „Bauantrag“ oder „Bauvoranfrage“ in der Art: Vorlagen aus der Einwohnerschaft oder von
# Privatpersonen („Bürgerbrief“ steht in actors.VERWALTUNG_TYPES, ist aber eine Vorlage aus der Einwohnerschaft,
# chat.EINWOHNER). EINGABE geht vor: „Einwohneranfrage nach § 39 Abs. 6“ enthält „anfrage“ und bleibt ohne
# Hauskoordinate. Abgeglichen wird der Vergleichstext (_vergleichstexte), nicht die gelieferte Schreibung. Die
# vollständige Kölner Liste fehlt bis zum Vollabruf: erkannte und nicht erkannte Arten stehen mit Anzahl im Log von
# build und in der Ausgabe von check.
# Vorlagenarten aus der Einwohnerschaft oder von Privatpersonen (in der Art „Bürger“ außer „Bürgermeister“,
# „Einwohner“, „Anwohner“, „privat“, „Bauantrag“, „Bauvoranfrage“): nie Hauskoordinate (VORLAGENART_PUNKT) und, mit
# derselben Regel (art_von_personen), Ausgangspunkt der Titelmaske (chat.aus_einwohnerschaft), auch in anderer Schreibung
# („Bürger-Antrag“, „Einwohner*innenanfrage“, „Anwohnerantrag“, „Privatantrag“, „Bürgerbriefe“; Prüfung r20n: vorher
# ohne Hauskoordinate, aber mit Hausnummer im Titel)
ART_PERSONEN = r"bürger(?!meister)|einwohner|anwohner|privat|bau(?:vor)?an(?:trag|frage)"
VORLAGENART_PUNKT = re.compile(rf"(?is)^(?!.*(?:{ART_PERSONEN}))"
                               r".*(?:vorlage|mitteilung|stellungnahme|antwort|dringlichkeitsentscheidung"
                               r"|informationsbrief|antrag|anfrage)")
_ART_PERSONEN = re.compile(ART_PERSONEN, re.I | re.S)
# Zeichen ohne Breite und weiche Trennzeichen: fallen im Vergleichstext weg („Bür\u00adgerantrag“ wie
# „Bürgerantrag“)
_UNSICHTBAR = re.compile(r"[\u00ad\u034f\u180e\u200b-\u200f\u2060-\u2064\ufeff]")
# Kennzeichen an einer Vorlage, deren Vorlagenart nicht als Zeichenkette kam (Liste, Objekt; build.einlesen macht Text
# daraus): gilt als nicht erkennbar, auch wenn der Text passt (vorsichtige Auslegung)
ANDERE_FORM = "_vorlagenart_andere_form"
# Gründe ohne Hauskoordinate (punkt_ausschluss) in der Reihenfolge der Prüfung, mit Bezeichnung im Log von build
AUSSCHLUSS = {"drucksache": "Drucksache in anderem Schema", "eingabe": "Eingabe oder Einwohneranfrage",
              "gremium": "Ausschuss für Anregungen und Beschwerden", "vorlagenart": "Vorlagenart nicht erkennbar",
              "maske": "Titel ohne Hausnummer (Einwohnerschaft, Bauordnung, Naturschutz)"}


def _vergleichstexte(text):
    """Vergleichstexte für die Regeln zur Hauskoordinate (EINGABE, Gremien, VORLAGENART_PUNKT), damit eine andere
    Schreibung eine Eingabe nicht durchlässt: Unicode-Normalform NFKC (zerlegte Umlaute, Vollbreite), ohne weiche
    Trennzeichen und Zeichen ohne Breite (_UNSICHTBAR), kleingeschrieben, Leerraum am Rand entfernt und im Text zu einem
    Leerzeichen zusammengefasst („Bürgerbrief “, „Anregungen  und Beschwerden“; Prüfung r20n), „Paragraf 24“ wie „§ 24“,
    ebenso die Abkürzungen „Par. 24“ und „Paragr. 24“ (mit Punkt vor einer Ziffer; Prüfung r20a); dazu derselbe Text
    mit „ae“, „oe“, „ue“ als „ä“, „ö“, „ü“ („Buergerantrag“). Ein Ausschluss gilt, wenn einer der beiden Texte passt,
    eine Erkennung nur, wenn beide passen (so verdeckt „ue“ kein folgendes Wort: „Neueingabe“). Nur für den Abgleich;
    Datenbank, Export und Log behalten die gelieferte Schreibung."""
    t = unicodedata.normalize("NFKC", _UNSICHTBAR.sub("", text or "")).lower()
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(?:paragra(?:f|ph)(?:en)?\.?|par(?:agr)?\.)\s*(?=\d)", "§ ", t)
    return t, t.replace("ae", "ä").replace("oe", "ö").replace("ue", "ü")


def eingabe(art, titel):
    """Hinweis auf eine Eingabe oder Einwohneranfrage (EINGABE) in Vorlagenart oder Titel, abgeglichen über die
    Vergleichstexte (_vergleichstexte; eine Vorlagenart in anderer Form gilt als Text, null als leer). Eine Regel für
    die Hauskoordinate (punkt_ausschluss, Grund „eingabe“) und die Titelmaske samt Volltextkette
    (chat.aus_einwohnerschaft), damit eine Eingabe in anderer Schreibung („Buergerantrag“, „Antrag nach Paragraf 24 GO
    NRW“, weiches Trennzeichen) weder die Hauskoordinate bekommt noch ihre Hausnummer im Titel zeigt (Prüfung r20)."""
    art = art if isinstance(art, str) else "" if art is None else str(art)
    return any(EINGABE.search(t) for t in _vergleichstexte(art) + _vergleichstexte(titel))


def art_von_personen(art):
    """Vorlagenart aus der Einwohnerschaft oder von Privatpersonen (ART_PERSONEN, in einem der Vergleichstexte; eine
    Vorlagenart in anderer Form gilt als Text, null als leer): dieselbe Regel wie der Ausschluss in VORLAGENART_PUNKT,
    für die Titelmaske (chat.aus_einwohnerschaft) und die Gegenprobe in check.datenschutz (Prüfung r20n)."""
    art = art if isinstance(art, str) else "" if art is None else str(art)
    return any(_ART_PERSONEN.search(t) for t in _vergleichstexte(art))


def vorlagenart_erkannt(paper):
    """Ist die Vorlagenart als Verwaltungsvorlage oder politischer Antrag bzw. Anfrage erkennbar (VORLAGENART_PUNKT,
    in beiden Vergleichstexten)? Nein bei null, fehlend, keiner Zeichenkette oder dem Kennzeichen ANDERE_FORM; eine
    leere oder nur aus Leerraum bestehende Vorlagenart trifft das Muster nicht (es verlangt ein Wort wie „vorlage“ oder
    „antrag“)."""
    art = paper.get("paperType")
    return (isinstance(art, str) and not paper.get(ANDERE_FORM)
            and all(VORLAGENART_PUNKT.search(t) for t in _vergleichstexte(art)))


def punkt_ausschluss(paper, gremien=(), amt=None):
    """Grund, aus dem eine Straße mit Hausnummer im Titel nicht auf die Hauskoordinate gesetzt wird (AUSSCHLUSS), oder
    None, wenn es erlaubt ist. `gremien`: Namen der beratenden Gremien; `amt`: Name der federführenden Organisation
    (`underDirectionOf`). Ausgeschlossen: andere Referenzschemata, Vorlagenart oder Titel mit Hinweis auf eine Eingabe,
    jede Beratung im Ausschuss für Anregungen und Beschwerden bzw. Bürgerbeteiligung, eine leere oder nicht erkennbare
    Vorlagenart (VORLAGENART_PUNKT) und jede Vorlage, deren Titel maske.py ohne Hausnummer zeigt (Einwohnerschaft nach
    Art oder Titel, Bauordnungsamt oder Untere Naturschutzbehörde federführend; maske.titel_ohne_hausnummer, gleiche
    Angaben wie maske.aus_db): Neben einem Titel ohne Hausnummer stünde sonst die Anschrift als Ortsname mit
    Hauskoordinate (Prüfung r19). Abgleich über die Vergleichstexte (_vergleichstexte): andere Schreibungen wie
    „Buergerantrag“ oder mit weichem Trennzeichen gelten wie die übliche."""
    if not REFERENZ_PUNKT.match(paper.get("reference") or ""):
        return "drucksache"
    if eingabe(paper.get("paperType"), paper.get("name")):
        return "eingabe"
    if any(re.search(r"(?i)anregungen und beschwerden|bürgerbeteiligung", t)
           for g in gremien for t in _vergleichstexte(g)):
        return "gremium"
    if not vorlagenart_erkannt(paper):
        return "vorlagenart"
    from . import maske   # hier: maske → chat → geocode
    return "maske" if maske.titel_ohne_hausnummer(paper.get("paperType"), paper.get("name"), amt) else None


def hausnummer_punkt_erlaubt(paper, gremien=(), amt=None):
    """Darf eine Straße mit Hausnummer im Titel auf die Hauskoordinate gesetzt werden? (punkt_ausschluss)"""
    return punkt_ausschluss(paper, gremien, amt) is None


def vorlagenart_bezeichnung(paper):
    """Vorlagenart für die Zählung der erkannten und nicht erkannten Arten (nur die Art, keine weiteren Angaben der
    Vorlage)."""
    art = paper.get("paperType")
    art = art.strip() if isinstance(art, str) else "" if art is None else str(art)
    if not art:
        return "(leer)"
    art = art if len(art) <= 80 else art[:79] + "…"
    return f"„{art}“" + (" (als Liste oder Objekt geliefert)" if paper.get(ANDERE_FORM) else "")


def _arten_zeile(kopf, zaehler, hoechstens):
    teile = [f"{art} {n}" for art, n in sorted(zaehler.items(), key=lambda x: (-x[1], x[0]))]
    if len(teile) > hoechstens:
        teile = teile[:hoechstens] + [f"… und {len(teile) - hoechstens} weitere Arten"]
    return f"{kopf}: {sum(zaehler.values())} Vorlagen" + (" – " + ", ".join(teile) if teile else "")


def nicht_erkannte_arten(zaehler, hoechstens=40):
    """Zeile für Log und Prüfung: Vorlagen ohne Hauskoordinate wegen nicht erkennbarer Vorlagenart, je Art mit Anzahl
    (häufigste zuerst), damit VORLAGENART_PUNKT nach dem Vollabruf ergänzt werden kann."""
    return _arten_zeile("Vorlagenart nicht erkennbar, daher keine Hauskoordinate (höchstens Straße; "
                        "geocode.VORLAGENART_PUNKT)", zaehler, hoechstens)


def erkannte_arten(zaehler, hoechstens=40):
    """Zeile für Log und Prüfung: Vorlagen mit Erlaubnis für die Hauskoordinate nach ihrer eigenen Angabe (Vorlagenart
    erkannt, keine Eingabe; punkt_ausschluss None), je Art mit Anzahl (häufigste zuerst), damit nach dem Vollabruf
    auch geprüft werden kann, ob eine erkannte Art von Einwohnerinnen, Einwohnern oder Privatpersonen stammt. Ob die
    Vorlage den Punkt bekommt, hängt zudem vom Titel (Straße mit Hausnummer), den verbundenen Vorlagen und den
    Vorlagen mit derselben Drucksache ab."""
    return _arten_zeile("Vorlagenart erkannt, Hauskoordinate möglich (geocode.VORLAGENART_PUNKT)", zaehler, hoechstens)


# Weg, über den eine Vorlage in die Menge ohne Hauskoordinate kommt (sperrmenge), mit Bezeichnung im Log von build
WEG = {"beziehung": "verbunden mit einer davon oder einer ausgelassenen Vorlage",
       "drucksache": "mit derselben Drucksache wie eine davon"}


def sperrmenge(start, beziehungen, drucksachen):
    """Alle Vorlagen ohne Erlaubnis für Hauskoordinaten als Fixpunkt, eine Funktion für den Aufbau (build.build) und die
    Prüfung (check.erlaubnis): Ausgehend von `start` (IDs mit Grund aus punkt_ausschluss und beim Aufbau ausgelassene
    Vorlagen) kommen abwechselnd alle verbundenen Vorlagen hinzu (über `beziehungen`, auch über mehrere Stufen: über-
    und untergeordnet und relatedPaper, Paare in beiden Richtungen; Beantwortung oder Stellungnahme zu einer Eingabe
    nennen oft dieselbe Anschrift, tragen aber weder die Art noch das Wort im Titel) und alle Vorlagen mit derselben
    Drucksache (`drucksachen`, {Vorlagen-ID: Drucksache}; vorlagen.geojson und die Gebietsdateien führen Vorlagen unter
    ihrer Drucksache), bis nichts mehr hinzukommt. So sperrt eine Kopie mit derselben Drucksache wie eine Eingabe auch
    ihre verbundenen Vorlagen, und eine Vorlage, die über eine Beziehung gesperrt ist, sperrt die Vorlagen mit ihrer
    Drucksache (Prüfung r19: vorher nur ein Schritt).
    Gerechnet als eine Breitensuche in Schichten, in linearer Zeit (Prüfung r19b: vorher je Wechsel zwischen Beziehung
    und Drucksache ein Durchlauf über alle Vorlagen, bei langen Ketten quadratisch): Nachbarn und Vorlagen je Drucksache
    werden einmal aufgestellt; eine Schicht nimmt zuerst alles hinzu, was über Beziehungen erreichbar ist, dann bilden
    die noch fehlenden Vorlagen mit der Drucksache einer Vorlage der Schicht die nächste Schicht (jede Drucksache
    einmal). Liefert {ID: Weg} mit Weg „start“, „beziehung“ oder „drucksache“ (wodurch die Vorlage hinzukam; WEG),
    gleich dem früheren Ablauf in Runden. Mit anderer Startmenge und denselben Beziehungen (beziehungen,
    beziehungen_db) rechnet maske.kette die Titelmaske und die Volltextkette (Runde 20)."""
    nachbarn = {}
    for a, b in beziehungen:
        nachbarn.setdefault(a, []).append(b)
        nachbarn.setdefault(b, []).append(a)
    je_drucksache = {}
    for i, ref in drucksachen.items():
        je_drucksache.setdefault(ref, []).append(i)
    weg = dict.fromkeys(start, "start")
    schicht, erledigt = list(weg), set()
    while schicht:
        offen = list(schicht)
        while offen:
            for n in nachbarn.get(offen.pop(), ()):
                if n not in weg:
                    weg[n] = "beziehung"
                    offen.append(n)
                    schicht.append(n)
        naechste = []
        for i in schicht:
            if i not in drucksachen or drucksachen[i] in erledigt:
                continue
            erledigt.add(drucksachen[i])
            for n in je_drucksache[drucksachen[i]]:
                if n not in weg:
                    weg[n] = "drucksache"
                    naechste.append(n)
        schicht = naechste
    return weg


def beziehungen(papers):
    """Beziehungen der Vorlagen für sperrmenge aus den Rohdaten (nach build.einlesen; auch ausgelassene Vorlagen, die nur
    Kennung und Beziehungen tragen): ([(übergeordnet, untergeordnet)] aus `subordinatedPaper` und `superordinatedPaper`,
    [(Vorlage, verwandte Vorlage)] aus `relatedPaper`), je wie geliefert. build schreibt sie in paper_relation und
    paper_related und rechnet mit beiden Listen; volltext.einwohner_kette ohne Datenbank ebenso (Runde 20)."""
    rel, related = [], []
    for p in papers:
        rel += ([(p["id"], c) for c in p.get("subordinatedPaper") or []]
                + [(o, p["id"]) for o in p.get("superordinatedPaper") or []])
        related += [(p["id"], r) for r in p.get("relatedPaper") or []]
    return rel, related


def beziehungen_db(db):
    """Dieselben Beziehungen aus der Datenbank als eine Liste von Paaren: paper_relation und, wo vorhanden (ältere
    Datenbanken ohne die Tabelle), relatedPaper aus paper_related. Eine Menge für check.erlaubnis (Hauskoordinaten) und
    maske.aus_db (Titelmaske), wie beim Aufbau (Runde 20: vorher folgte die Titelmaske nur paper_relation)."""
    def tabelle(name):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    out = db.execute("SELECT parent_id, child_id FROM paper_relation").fetchall() if tabelle("paper_relation") else []
    if tabelle("paper_related"):
        out += db.execute("SELECT paper_id, related_id FROM paper_related").fetchall()
    return out


def plan_numbers(title):
    """[(Plannummer, Fundstelle)] aus dem Titel, je Nummer einmal; nur wenn die Geltungsbereiche vorliegen
    (data/geo/bebauungsplaene_koeln.geojson aus pipeline/bplan.py)."""
    if not config.BPLAN.exists():
        return []
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
