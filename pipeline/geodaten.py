"""Kölner Geodaten für die Pipeline: Stadtteile, Stadtbezirke und Straßenverzeichnis (Schritt `geo-koeln`).

Quellen (dl-de/zero 2.0, Namensnennung „Datenquelle: Stadt Köln – offenedaten-koeln.de“): Shapefiles der Datensätze
„Stadtteile Köln“, „Stadtbezirke Köln“ und „Straßen Köln“ (config.GEO_DOWNLOADS), ETRS89/UTM 32N (EPSG 25832).
Die Zip-Dateien liegen in data/raw/geo/; fehlen sie, werden sie einmal geladen (eine Verbindung, Abstand wie beim
OParl-Abruf). Ausgabe in WGS84 mit den Eigenschaftsnamen des Bonner Modells:
- stadtteile_koeln.geojson:   ortsteil (Nummer), ortsteil_bez, bezirk (Nummer), bezirk_bez
- stadtbezirke_koeln.geojson: bezirk, bezirk_bez
- strassen_koeln.json:        Name → Lagen je Stadtteil (Gazetteer aus geocode.py), dazu Kreuzungen
- hausnummern_koeln.json:     Straße → Stadtteil → Hausnummern (bestimmt den Stadtteil einer Straße, die durch
                              mehrere Stadtteile läuft) und Hauskoordinaten aus „Adressen Köln“ für die punktgenaue
                              Verortung, die nur bei Verwaltungsvorlagen und politischen Anträgen genutzt wird
                              (Entscheidung 04.11.2026; geocode.py, build.py)
Stadtteile und Stadtbezirke bilden eine lückenlose Abdeckung ohne Überlappungen (Entscheidung 13.11.2026, `abdeckung`):
Jede Fläche wird für sich um TOLERANZ_M vereinfacht und gerundet, danach werden die Stadtteile gemeinsam bereinigt
(Lücken und Überlappungen zwischen Nachbarn verteilt, gemeinsam auf GITTER gerundet; der Außenrand Kölns bleibt), die
Stadtbezirke sind die Vereinigung ihrer Stadtteile. `python -m pipeline geo-abdeckung` wendet diesen Schritt ohne
Download auf die vorhandenen Dateien in data/geo an.
Straßennamen werden ausgeschrieben („Aachener Str.“ → „Aachener Straße“), damit Titel mit „Straße“, „Strasse“ und
„Str.“ gleichermaßen gefunden werden. Gleichnamige Straßen nach Eingemeindungen bleiben als getrennte Lagen erhalten.
Abruf direkt über urllib, nicht über pipeline/net.py oder pipeline/abruf.py: deren Schutz vor Anfragen an die
Stadt (abruf.stadt, Abrufpolitik) greift hier nicht.
"""
import io
import json
import re
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict

import numpy as np
import pyproj
import shapefile
import shapely
from pyproj import Transformer
from shapely.geometry import mapping, shape

from . import config

ROH = config.RAW / "geo"
NACH_WGS84 = Transformer.from_crs(25832, 4326, always_xy=True)
NACH_UTM = Transformer.from_crs(4326, 25832, always_xy=True)
TOLERANZ_M = 2.0   # Vereinfachung der Flächen (Meter), sichtbar erst weit unter Straßenbreite
GITTER = 1e-6      # Koordinaten der Flächen in Grad (in Köln rund 7 × 11 cm), wie shapely.set_precision in _wgs84
# Lücke zwischen Stadtteilen: ganz zu einem Nachbarn, wenn keiner ihrer Punkte weiter als LUECKE_M von ihm entfernt ist;
# sonst bekommt jeder Nachbar den Teil bis LUECKE_M (so viel weicht die Vereinfachung je Fläche ohnehin ab)
LUECKE_M = TOLERANZ_M
DENSIFY = 0.25     # Hausdorff-Abstand: Segmente in Viertel geteilt (wie strukturdaten_raum.DENSIFY)


def _zip(name):
    pfad = ROH / f"{name}.zip"
    if not pfad.exists():
        ROH.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(config.GEO_DOWNLOADS[name], headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as r:
            pfad.write_bytes(r.read())
        time.sleep(config.ABRUF_ABSTAND)
    return zipfile.ZipFile(pfad)


def _reader(z, basis):
    namen = {n.split("/")[-1].lower(): n for n in z.namelist()}
    teil = lambda e: io.BytesIO(z.read(namen[f"{basis}{e}".lower()]))
    return shapefile.Reader(shp=teil(".shp"), dbf=teil(".dbf"), shx=teil(".shx"), encoding="utf-8")


def _wgs84(geom, toleranz=0.0):
    if toleranz:
        geom = geom.simplify(toleranz, preserve_topology=True)
    geom = shapely.transform(geom, lambda c: np.column_stack(NACH_WGS84.transform(c[:, 0], c[:, 1])))
    return shapely.set_precision(geom, 1e-6)


def _transform_coords(coords):
    xs, ys = zip(*coords)
    lon, lat = NACH_WGS84.transform(xs, ys)
    return [[round(a, 6), round(b, 6)] for a, b in zip(lon, lat)]


def strassenname(name):
    """Amtlicher Name ausgeschrieben: „Aachener Str.“ → „Aachener Straße“, „Edisonstr.“ → „Edisonstraße“."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    return re.sub(r"([Ss])tr\.$", r"\1traße", name)


def _flaechen(z, basis, eigenschaften, toleranz=TOLERANZ_M):
    r = _reader(z, basis)
    feats = []
    for sr in r.iterShapeRecords():
        geom = _wgs84(shape(sr.shape.__geo_interface__), toleranz)
        feats.append({"type": "Feature", "properties": eigenschaften(sr.record.as_dict()), "geometry": mapping(geom)})
    return feats


def _meta(quelle, **weitere):
    return {"source": quelle, "license": config.SOURCES[config.QUELLE_GEO]["license"],
            "crs": "WGS84 (EPSG 4326), umgerechnet aus EPSG 25832", "vereinfacht_m": TOLERANZ_M, **weitere}


def _schreibe_geojson(pfad, feats, meta):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps({"type": "FeatureCollection", "meta": meta, "features": feats},
                               ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


# --- Lückenlose Abdeckung der Stadtteile und Stadtbezirke (Entscheidung 13.11.2026) ------------------------------------
# Bis zum 13.11.2026 wurde jede Fläche für sich vereinfacht und gerundet: zwischen Nachbarn blieben schmale Lücken und
# Überlappungen (Stadtteile 415 Lücken mit 21 601 m², 169 überlappende Paare mit 19 040 m²; Stadtbezirke 161 Lücken mit
# 7 648 m², 14 Paare mit 7 775 m²; gemessen am 10.11.2026). `abdeckung` macht daraus eine Abdeckung wie bei den
# Statistischen Quartieren (strukturdaten_raum.quartiersflaechen), ohne die Quelle neu zu laden.

FLAECHEN_STADTTEILE = (
    "Jede Fläche für sich mit Douglas-Peucker um vereinfacht_m vereinfacht und auf 1e-6 Grad gerundet, danach alle "
    "Stadtteile gemeinsam als lückenlose Abdeckung bereinigt (pipeline/geodaten.abdeckung, Verfahren unter "
    "abdeckung.verfahren): Nachbarn haben an ihrer gemeinsamen Grenze dieselben Stützpunkte, ohne Lücken und "
    "Überlappungen. Der Außenrand Kölns bleibt, außer wo ein Deckel einen schmalen, zum Außenrand offenen Kanal "
    "zwischen zwei Stadtteilen schließt (abdeckung.kanaele) und um Rundungsstreifen (abdeckung.aussenrand).")
FLAECHEN_STADTBEZIRKE = (
    "Vereinigung der Stadtteile je Stadtbezirk (data/geo/stadtteile_koeln.geojson, Eigenschaft bezirk; "
    "shapely.coverage_union_all ohne neue Punkte): Stadtbezirke und Stadtteile haben dieselben Grenzen. Nummer und Name "
    "aus dem Datensatz unter source; die Fläche dieses Datensatzes (für sich vereinfacht) dient nur dem Vergleich unter "
    "abdeckung.abweichung_von_der_eingabe.")
VERFAHREN = (
    "In WGS84 auf den Koordinaten der Eingabe (auf 1e-6 Grad gerundet). (1) Ein Deckel schließt jeden schmalen Kanal "
    "zwischen zwei Stadtteilen, der zum Außenrand offen ist (kanaele: Mündung höchstens muendung_hoechstens_m breit, "
    "Weg über die Kanalspitze mindestens verhaeltnis_mindestens-mal so lang; Einbuchtungen eines einzigen Stadtteils "
    "bleiben). (2) Alle Grenzen und Deckel mit shapely.union_all verknotet, mit shapely.polygonize in Netzflächen "
    "zerlegt. Liegt eine Netzfläche zu mindestens der Hälfte in genau einem Stadtteil, gehört sie zu ihm, in mehreren "
    "(Überlappung) zu dem mit der kleineren Nummer. (3) Eine Netzfläche in keinem Stadtteil (Lücke oder Kanal) gehört "
    "ganz zu dem Nachbarn mit der längsten gemeinsamen Grenze, dem keiner ihrer Punkte weiter als luecke_hoechstens_m "
    "entfernt ist (sie liegt bis auf 0,01 m² in seinem Puffer, EPSG 25832); gibt es keinen, bekommt jeder Nachbar in "
    "dieser Reihenfolge den noch freien Teil in seinem Puffer (luecken_geteilt); bleiben mehr als 0,01 m² frei, "
    "bricht der Schritt ab. (4) Alle Grenzen gemeinsam auf 1e-6 Grad gerundet wie bei den Quartieren "
    "(shapely.union_all mit grid_size, polygonize, jede Netzfläche zu der Fläche mit dem größten Anteil vor dem Runden, "
    "bei Gleichstand die kleinere Nummer; eine Netzfläche ohne Fläche bricht ab), je Stadtteil "
    "shapely.coverage_union_all, Außenringe im Uhrzeigersinn. (5) Stadtbezirke als Vereinigung ihrer Stadtteile. "
    "Geprüft (sonst Abbruch): jede Fläche gültig, so viele Teile wie in der Eingabe und (Stadtteile) so viele "
    "Löcher, gültige Abdeckung "
    "(shapely.coverage_is_valid), keine Lücke und keine Überlappung (EPSG 25832: Lücke = Loch in der Vereinigung ohne "
    "Außenrand, Überlappung = Paar mit gemeinsamer Fläche über 0 m²), der Außenrand ändert sich außer an den Kanälen "
    "nur um Streifen bis 0,14 m Breite (Diagonale einer Gitterzelle; aussenrand: Teile, Fläche und größte Breite des "
    "Unterschieds der Fläche innerhalb des Außenrands, die Kanäle zur Fläche vorher gezählt), jeder Stadtteil nennt "
    "denselben Namen seines Stadtbezirks wie die Stadtbezirke. abweichung_von_der_eingabe: Hausdorff-Abstand je Fläche "
    "in EPSG 25832 (Segmente in Viertel geteilt) und Flächenänderung.")
RESTFLAECHE_M2 = 0.01   # freie Fläche einer geteilten Lücke, ab der der Schritt abbricht
# Kanal zwischen zwei Stadtteilen, offen zum Außenrand (Lücke, die nicht als Loch zählt): Mündung höchstens KANAL_M breit
# (zwei je für sich um TOLERANZ_M vereinfachte Grenzen liegen höchstens so weit auseinander), Weg über die Spitze
# mindestens KANAL_VERHAELTNIS-mal so lang wie die Mündung breit
KANAL_M = 2 * TOLERANZ_M
KANAL_VERHAELTNIS = 10
DECKEL_UEBERSTAND_GRAD = 3e-7   # Überstand des Deckels über die Kante (rund 2–3 cm)
# Der Außenrand Kölns bleibt: Er ändert sich nur durch das gemeinsame Runden um Streifen, die schmaler sind als die
# Diagonale einer Gitterzelle (1e-6 Grad, in Köln rund 7 × 11 cm); breitere Änderungen brechen den Schritt ab
AUSSENRAND_BREITE_M = 0.14


def _umrechnen(geom, transformer):
    return shapely.transform(geom, lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1])))


def _shapely_pruefen():
    fehlen = [f for f in ("coverage_union_all", "coverage_is_valid", "orient_polygons", "maximum_inscribed_circle")
              if not hasattr(shapely, f)]
    if fehlen or tuple(shapely.geos_version) < (3, 12, 0):
        raise RuntimeError(f"Abdeckung der Stadtteile: shapely {shapely.__version__} mit GEOS "
                           f"{shapely.geos_version_string} reicht nicht, gebraucht shapely >= 2.1 mit GEOS >= 3.12 "
                           "(requirements.txt)" + (f"; fehlt: {', '.join(fehlen)}" if fehlen else ""))


def _teile_loecher(g):
    teile = shapely.get_parts(g)
    return len(teile), sum(len(p.interiors) for p in teile if p.geom_type == "Polygon")


def _aussen(g):
    """Fläche innerhalb des Außenrands (Löcher gefüllt)."""
    return shapely.union_all([shapely.Polygon(p.exterior) for p in shapely.get_parts(g) if p.geom_type == "Polygon"])


def luecken_ueberlappungen(flaechen):
    """Lücken und Überlappungen von Flächen in WGS84, gemessen in EPSG 25832 wie am 10.11.2026: Lücke = Loch in der
    Vereinigung (der Außenrand zählt nicht), Überlappung = Paar mit gemeinsamer Fläche über 0 m²."""
    utm = [_umrechnen(g, NACH_UTM) for g in flaechen]
    loecher = [l for p in shapely.get_parts(shapely.union_all(utm)) if p.geom_type == "Polygon"
               for l in (shapely.Polygon(r) for r in p.interiors) if l.area > 0]
    baum = shapely.STRtree(utm)
    paare = [a for i, g in enumerate(utm) for j in sorted(int(j) for j in baum.query(g))
             if j > i and (a := shapely.intersection(g, utm[j]).area) > 0]
    return {"luecken_teile": len(loecher), "luecken_m2": round(sum(l.area for l in loecher), 1),
            "groesste_luecke_m2": round(max((l.area for l in loecher), default=0.0), 1),
            "ueberlappung_paare": len(paare), "ueberlappung_m2": round(sum(paare), 1)}


def gemeinsam_runden(flaechen, gitter=GITTER, rang=None):
    """Flächen einer Abdeckung gemeinsam auf `gitter` gerundet (Verfahren wie strukturdaten_raum.quartiersflaechen,
    Schritt 3): shapely.union_all mit grid_size rundet und verknotet alle Grenzen mit Snap-Rounding, shapely.polygonize
    bildet die Netzflächen; jede gehört zu der Fläche, mit der sie vor dem Runden die größte Fläche teilt (bei
    Gleichstand die mit dem kleineren `rang`), shapely.coverage_union_all setzt sie je Fläche ohne neue Punkte zusammen,
    Außenringe im Uhrzeigersinn wie data/geo. ValueError, wenn eine Netzfläche zu weniger als der Hälfte in den Flächen
    liegt (Lücke) oder eine Fläche keine Netzfläche erhält."""
    flaechen = list(flaechen)
    rang = list(range(len(flaechen))) if rang is None else list(rang)
    kanten = shapely.union_all(shapely.boundary(np.array(flaechen, dtype=object)), grid_size=gitter)
    netz = shapely.get_parts(shapely.polygonize(shapely.get_parts(kanten)))
    baum = shapely.STRtree(flaechen)
    teile, ohne = defaultdict(list), []
    for f in netz:
        anteile = [(shapely.intersection(f, flaechen[j]).area, -rang[j], j)
                   for j in sorted(int(j) for j in baum.query(f))]
        if sum(a for a, *_ in anteile) < f.area / 2:
            ohne.append(f)
            continue
        teile[max(anteile)[2]].append(f)
    if ohne:
        raise ValueError(f"{len(ohne)} Netzfläche(n) nach dem Runden ohne Fläche (Lücke), zusammen "
                         f"{sum(_umrechnen(f, NACH_UTM).area for f in ohne):.2f} m²")
    leer = [rang[i] for i in range(len(flaechen)) if not teile.get(i)]
    if leer:
        raise ValueError(f"nach dem Runden ohne Fläche: {leer}")
    return [shapely.orient_polygons(shapely.coverage_union_all(teile[i]), exterior_cw=True)
            for i in range(len(flaechen))]


def _nachbarn(g, flaechen, baum):
    """[(Länge der gemeinsamen Grenze in Metern, Index)] der Flächen, die mit g eine Grenze als Linie teilen."""
    aus = []
    for j in sorted(int(j) for j in baum.query(g)):
        laenge = _umrechnen(shapely.intersection(g.boundary, flaechen[j].boundary), NACH_UTM).length
        if laenge > 0:
            aus.append((laenge, j))
    return aus


def _abweichung(ids, vorher, nachher):
    """Abweichung je Fläche (beide Listen in WGS84, gemessen in EPSG 25832)."""
    je = {}
    for i, a, b in zip(ids, vorher, nachher):
        a, b = _umrechnen(a, NACH_UTM), _umrechnen(b, NACH_UTM)
        je[str(i)] = {"aenderung_m2": round(b.area - a.area, 1),
                      "aenderung_prozent": round((b.area - a.area) / a.area * 100, 4),
                      "abstand_m": round(shapely.hausdorff_distance(a, b, densify=DENSIFY), 2)}
    abstand = {i: v["abstand_m"] for i, v in je.items()}
    groesste = max(abstand, key=lambda i: (abstand[i], -int(i)))
    return {"abstand_max_m": abstand[groesste], "abstand_max_id": groesste,
            "abstand_median_m": round(float(np.median(list(abstand.values()))), 2),
            "abstand_ueber_1_m": sum(1 for v in abstand.values() if v > 1),
            "abstand_ueber_toleranz": {i: v for i, v in sorted(abstand.items(), key=lambda x: (-x[1], int(x[0])))
                                       if v > TOLERANZ_M},
            "aenderung_betrag_m2": round(sum(abs(v["aenderung_m2"]) for v in je.values()), 1),
            "aenderung_max_prozent": max(abs(v["aenderung_prozent"]) for v in je.values()),
            "je_flaeche": je}


def _aussenrand(vorher, nachher):
    """Unterschied der Fläche innerhalb des Außenrands (Vereinigung ohne Löcher) vor und nach der Bereinigung, in
    EPSG 25832: Teile, Fläche und größte Breite (Durchmesser des größten Inkreises eines Teils)."""
    a, b = _aussen(shapely.union_all(vorher)), _aussen(shapely.union_all(nachher))
    teile = [p for p in shapely.get_parts(_umrechnen(shapely.symmetric_difference(a, b), NACH_UTM)) if p.area > 0]
    breite = max((2 * shapely.maximum_inscribed_circle(p, 0.001).length for p in teile), default=0.0)
    return {"teile": len(teile), "flaechenunterschied_m2": round(sum(p.area for p in teile), 2),
            "groesste_breite_m": round(breite, 3)}


def _seite(ring, lab, s, nachbar, schritt, laengen):
    """Ringpunkte von s aus in Richtung schritt (+1/-1), solange sie auf dem Rand von `nachbar` liegen (bis zum
    nächsten Knoten mit weiteren Flächen): [(Index, Weg in Metern)]."""
    n, aus, weg, i = len(ring), [], 0.0, s
    while len(aus) < n:
        j = (i + schritt) % n
        weg += laengen[i if schritt > 0 else j]
        if nachbar not in lab[j]:
            break
        aus.append((j, weg))
        if len(lab[j]) > 1:
            break
        i = j
    return aus


def kanaele(quelle, kanal_m=KANAL_M, verhaeltnis=KANAL_VERHAELTNIS):
    """Deckel über schmalen Kanälen zwischen zwei Flächen, die zum Außenrand offen sind: [(Deckel als LineString in
    WGS84, Index A, Index B, Weg entlang beider Seiten in Metern, Breite der Mündung in Metern)].

    Ein Kanal entsteht, wenn zwei Nachbarn ihre gemeinsame Grenze bis zum Außenrand je für sich vereinfacht haben: Der
    Außenring der Vereinigung läuft auf dem Rand von A in den Kanal hinein, wechselt an seiner Spitze auf B und läuft
    auf B wieder hinaus. Gesucht wird je Wechsel (Ringpunkt auf A und B, davor nur A, danach nur B) die äußerste
    Engstelle: ein Ringpunkt der einen Seite, der höchstens kanal_m von der anderen Seite entfernt ist, wobei der Weg
    über die Spitze mindestens verhaeltnis-mal so lang ist wie dieser Abstand und die Strecke außerhalb der Flächen
    liegt. Der Deckel führt von diesem Punkt zum nächsten Punkt der anderen Seite (in Grad gerechnet, damit er auf
    ihrer Kante liegt) und etwa 3 cm darüber hinaus, damit die Verknotung die Kante sicher trifft; das überstehende
    Ende liegt in der Fläche und fällt beim Bilden der Netzflächen weg. Einbuchtungen einer einzigen Fläche bleiben
    unberührt."""
    vereinigung = shapely.union_all(quelle)
    baum = shapely.STRtree([g.boundary for g in quelle])
    aus = []
    for teil in shapely.get_parts(vereinigung):
        ring = np.asarray(teil.exterior.coords)[:-1]
        lab = [frozenset(int(j) for j in baum.query(p, predicate="dwithin", distance=1e-9))
               for p in shapely.points(ring)]
        utm = shapely.get_coordinates(_umrechnen(shapely.multipoints(ring), NACH_UTM))
        laengen = np.hypot(*(np.roll(utm, -1, axis=0) - utm).T)
        for s in range(len(ring)):
            vor, nach = lab[s - 1], lab[(s + 1) % len(ring)]
            if len(lab[s]) < 2 or len(vor) != 1 or len(nach) != 1 or vor == nach:
                continue
            a, b = next(iter(vor)), next(iter(nach))
            seiten = {-1: _seite(ring, lab, s, a, -1, laengen), 1: _seite(ring, lab, s, b, 1, laengen)}
            if not seiten[-1] or not seiten[1]:
                continue
            linie = {k: (shapely.LineString(utm[[s] + [i for i, _ in v]]),
                         shapely.LineString(ring[[s] + [i for i, _ in v]])) for k, v in seiten.items()}
            bester = None
            for k, v in seiten.items():
                andere, andere_grad = linie[-k]
                for i, weg in v:
                    pkt = shapely.Point(utm[i])
                    abstand, entlang = andere.distance(pkt), andere.project(pkt)
                    if abstand > kanal_m or weg + entlang < verhaeltnis * max(abstand, 0.01):
                        continue
                    # Fußpunkt auf der Linie in Grad (die Gerade in EPSG 25832 weicht davon ab)
                    fuss = np.asarray(andere_grad.interpolate(andere_grad.project(shapely.Point(ring[i]))).coords[0])
                    richtung = fuss - ring[i]
                    if np.hypot(*richtung) < 1e-12:
                        continue
                    # außerhalb der Flächen (bis auf Rundungsfehler am Fußpunkt, unter 0,1 mm)
                    if shapely.intersection(shapely.LineString([ring[i], fuss]), vereinigung).length > 1e-9:
                        continue
                    if bester is None or weg + entlang > bester[0]:
                        ende = fuss + richtung / np.hypot(*richtung) * DECKEL_UEBERSTAND_GRAD
                        bester = (weg + entlang, abstand, shapely.LineString([ring[i], ende]))
            if bester:
                aus.append((bester[2], a, b, bester[0], bester[1]))
    return aus


def abdeckung(teile, bezirke):
    """(Stadtteile, Stadtbezirke, Prüfung) als lückenlose Abdeckung aus GeoJSON-Features in WGS84 (Stadtteile mit
    ortsteil, bezirk, bezirk_bez; Stadtbezirke mit bezirk, bezirk_bez). Verfahren in VERFAHREN; Eigenschaften und
    Reihenfolge der Features bleiben, nur die Geometrie ändert sich. ValueError, wenn eine Prüfung scheitert."""
    _shapely_pruefen()
    nr = [f["properties"]["ortsteil"] for f in teile]
    if len(set(nr)) != len(nr):
        raise ValueError("Stadtteile: Nummer doppelt")
    quelle = [shape(f["geometry"]) for f in teile]
    for n, g in zip(nr, quelle):
        if g.geom_type not in ("Polygon", "MultiPolygon") or g.is_empty or not g.is_valid:
            raise ValueError(f"Stadtteil {n}: keine gültige Fläche")
    # (1) verknoten (mit Deckeln über Kanälen am Außenrand) und zuordnen
    deckel = kanaele(quelle)
    kanten = shapely.union_all(list(shapely.boundary(np.array(quelle, dtype=object))) + [d[0] for d in deckel])
    netz = [f for f in shapely.get_parts(shapely.polygonize(shapely.get_parts(kanten))) if f.area > 0]
    baum = shapely.STRtree(quelle)
    zu, luecken, zahl = {}, [], Counter()
    for k, f in enumerate(netz):
        anteile = {j: shapely.intersection(f, quelle[j]).area / f.area for j in sorted(int(j) for j in baum.query(f))}
        decken = sorted((j for j, a in anteile.items() if a >= 0.5), key=lambda j: nr[j])
        if decken:
            zu[k] = decken[0]
            zahl["eine_flaeche" if len(decken) == 1 else "ueberlappung"] += 1
        elif sum(anteile.values()) >= 0.5:
            zu[k] = max(anteile, key=lambda j: (anteile[j], -nr[j]))
            zahl["anteilig"] += 1
        else:
            luecken.append(k)
    # (2) Lücken an die Nachbarn: ganz, wenn sie vollständig im Puffer (LUECKE_M) eines Nachbarn liegen, sonst geteilt
    ref = [shapely.union_all([netz[k] for k, j in zu.items() if j == i]) for i in range(len(nr))]
    rbaum = shapely.STRtree(ref)
    puffer_utm = {}

    def puffer(j):   # Puffer um den Stadtteil j in EPSG 25832 (einmal je Stadtteil berechnet)
        if j not in puffer_utm:
            puffer_utm[j] = shapely.buffer(_umrechnen(ref[j], NACH_UTM), LUECKE_M)
        return puffer_utm[j]
    stuecke, geteilt = defaultdict(list), {}
    for k in luecken:
        g = netz[k]
        g_utm = _umrechnen(g, NACH_UTM)
        kandidaten = [j for _, j in sorted(_nachbarn(g, ref, rbaum), key=lambda t: (-t[0], nr[t[1]]))]
        punkt = g.representative_point()
        if not kandidaten:
            raise ValueError(f"Lücke ohne Nachbarn bei {punkt.x:.6f}, {punkt.y:.6f}")
        nah = [j for j in kandidaten if shapely.difference(g_utm, puffer(j)).area <= RESTFLAECHE_M2]
        if nah:
            stuecke[nah[0]].append(g)
            zahl["luecke_ganz"] += 1
            continue
        rest, verteilt = g, {}
        for j in kandidaten:
            p_wgs = _umrechnen(puffer(j), NACH_WGS84)
            teil, rest = shapely.intersection(rest, p_wgs), shapely.difference(rest, p_wgs)
            neu = [t for t in shapely.get_parts(teil) if t.geom_type == "Polygon" and t.area > 0]
            stuecke[j] += neu
            if neu:
                verteilt[str(nr[j])] = round(sum(_umrechnen(t, NACH_UTM).area for t in neu), 1)
        frei = _umrechnen(rest, NACH_UTM).area
        if frei > RESTFLAECHE_M2:
            raise ValueError(f"Lücke bei {punkt.x:.6f}, {punkt.y:.6f}: {frei:.2f} m² weiter als {LUECKE_M:g} m von "
                             "jedem Nachbarn (keine schmale Lücke zwischen Nachbarn)")
        zahl["luecke_geteilt"] += 1
        geteilt[f"{punkt.x:.6f},{punkt.y:.6f}"] = {"flaeche_m2": round(g_utm.area, 1), "teile_m2": verteilt}
    stufe1 = [shapely.union_all([netz[k] for k, j in zu.items() if j == i] + stuecke[i]) for i in range(len(nr))]
    # (3) gemeinsam runden, prüfen
    aus = gemeinsam_runden(stufe1, GITTER, nr)
    fehler = []
    for n, q, g in zip(nr, quelle, aus):
        if g.is_empty or not g.is_valid:
            fehler.append(f"Stadtteil {n} " + ("leer" if g.is_empty else f"ungültig ({shapely.is_valid_reason(g)})"))
        elif _teile_loecher(g) != _teile_loecher(q):
            fehler.append(f"Stadtteil {n} mit {_teile_loecher(g)} statt {_teile_loecher(q)} Teilen und Löchern")
    vorher, nachher = luecken_ueberlappungen(quelle), luecken_ueberlappungen(aus)
    gueltig = bool(shapely.coverage_is_valid(np.array(aus, dtype=object)))
    if not gueltig:
        fehler.append("Stadtteile keine gültige Abdeckung")
    if nachher["luecken_teile"] or nachher["ueberlappung_paare"]:
        fehler.append(f"Stadtteile: {nachher['luecken_teile']} Lücken, {nachher['ueberlappung_paare']} Überlappungen")
    innen = _aussen(shapely.union_all(quelle))
    kanal_flaechen = [netz[k] for k in luecken if not innen.contains(netz[k].representative_point())]
    rand = _aussenrand(quelle + kanal_flaechen, aus)
    if rand["groesste_breite_m"] > AUSSENRAND_BREITE_M:
        fehler.append(f"Außenrand verschoben: {rand['teile']} Teile mit {rand['flaechenunterschied_m2']} m², bis "
                      f"{rand['groesste_breite_m']} m breit (erlaubt {AUSSENRAND_BREITE_M} m)")
    # (4) Stadtbezirke als Vereinigung ihrer Stadtteile
    bz = {}
    for f in bezirke:
        b = f["properties"]["bezirk"]
        if b in bz:
            fehler.append(f"Stadtbezirk {b} doppelt")
        bz[b] = f
    gruppen = defaultdict(list)
    for i, f in enumerate(teile):
        p = f["properties"]
        if p["bezirk"] not in bz:
            fehler.append(f"Stadtteil {p['ortsteil']}: Stadtbezirk {p['bezirk']} fehlt")
        elif p["bezirk_bez"] != bz[p["bezirk"]]["properties"]["bezirk_bez"]:
            fehler.append(f"Stadtteil {p['ortsteil']}: Stadtbezirk „{p['bezirk_bez']}“, in den Stadtbezirken "
                          f"„{bz[p['bezirk']]['properties']['bezirk_bez']}“")
        gruppen[p["bezirk"]].append(i)
    fehler += [f"Stadtbezirk {b} ohne Stadtteil" for b in sorted(set(bz) - set(gruppen))]
    if fehler:
        raise ValueError("Abdeckung der Stadtteile und Stadtbezirke: " + "; ".join(fehler))
    bz_nr = [f["properties"]["bezirk"] for f in bezirke]
    bz_quelle = [shape(f["geometry"]) for f in bezirke]
    bz_aus = [shapely.orient_polygons(shapely.coverage_union_all([aus[i] for i in gruppen[b]]), exterior_cw=True)
              for b in bz_nr]
    for b, q, g in zip(bz_nr, bz_quelle, bz_aus):   # Löcher der Eingabe können Lücken sein, daher nur die Teile
        if g.is_empty or not g.is_valid or len(shapely.get_parts(g)) != len(shapely.get_parts(q)):
            fehler.append(f"Stadtbezirk {b}: ungültig oder mit {len(shapely.get_parts(g))} statt "
                          f"{len(shapely.get_parts(q))} Teilen")
    bz_vorher, bz_nachher = luecken_ueberlappungen(bz_quelle), luecken_ueberlappungen(bz_aus)
    bz_gueltig = bool(shapely.coverage_is_valid(np.array(bz_aus, dtype=object)))
    if not bz_gueltig or bz_nachher["luecken_teile"] or bz_nachher["ueberlappung_paare"]:
        fehler.append("Stadtbezirke keine lückenlose Abdeckung")
    if fehler:
        raise ValueError("Abdeckung der Stadtteile und Stadtbezirke: " + "; ".join(fehler))
    software = {"shapely": shapely.__version__, "geos": shapely.geos_version_string, "pyproj": pyproj.__version__,
                "proj": pyproj.proj_version_str}
    pruefung = {
        "stadtteile": {
            "verfahren": VERFAHREN, "gitter_grad": GITTER, "luecke_hoechstens_m": LUECKE_M,
            "netzflaechen": {"zusammen": len(netz), **{s: zahl[s] for s in (
                "eine_flaeche", "ueberlappung", "anteilig", "luecke_ganz", "luecke_geteilt")}},
            "kanaele": {"muendung_hoechstens_m": KANAL_M, "verhaeltnis_mindestens": KANAL_VERHAELTNIS,
                        "flaeche_m2": round(sum(_umrechnen(f, NACH_UTM).area for f in kanal_flaechen), 1),
                        "je_kanal": [{"stadtteile": f"{nr[a]}/{nr[b]}", "laenge_m": round(weg / 2, 1),
                                      "muendung_m": round(breite, 3)} for _, a, b, weg, breite in deckel]},
            "luecken_geteilt": geteilt,
            "eingabe": vorher, "ausgabe": nachher, "abdeckung_gueltig": gueltig, "aussenrand": rand,
            "abweichung_von_der_eingabe": _abweichung(nr, quelle, aus), "software": software},
        "stadtbezirke": {
            "verfahren": "Vereinigung der Stadtteile je Stadtbezirk (shapely.coverage_union_all); Prüfung und Messung "
                         "wie bei den Stadtteilen, verglichen mit den Flächen des Datensatzes Stadtbezirke Köln "
                         "(für sich vereinfacht)",
            "eingabe": bz_vorher, "ausgabe": bz_nachher, "abdeckung_gueltig": bz_gueltig,
            "aussenrand": _aussenrand(bz_quelle, bz_aus),
            "abweichung_von_der_eingabe": _abweichung(bz_nr, bz_quelle, bz_aus), "software": software},
    }
    feature = lambda f, g: {"type": "Feature", "properties": f["properties"], "geometry": mapping(g)}
    return ([feature(f, g) for f, g in zip(teile, aus)], [feature(f, g) for f, g in zip(bezirke, bz_aus)], pruefung)


def _ist_abdeckung(gj_teile, gj_bezirke):
    """True, wenn beide Dateien schon bereinigt sind (meta.abdeckung) und jede eine gültige Abdeckung ohne Lücke
    bildet."""
    for gj in (gj_teile, gj_bezirke):
        if "abdeckung" not in gj.get("meta", {}):
            return False
        geoms = [shape(f["geometry"]) for f in gj["features"]]
        if not shapely.coverage_is_valid(np.array(geoms, dtype=object)) or any(
                len(p.interiors) for p in shapely.get_parts(shapely.union_all(geoms)) if p.geom_type == "Polygon"):
            return False
    return True


def _schreiben(teile, bezirke, quelle_teile, quelle_bezirke):
    teile, bezirke, pruefung = abdeckung(teile, bezirke)
    _schreibe_geojson(config.ORTSTEILE, teile, _meta(quelle_teile, flaechen=FLAECHEN_STADTTEILE,
                                                    abdeckung=pruefung["stadtteile"]))
    _schreibe_geojson(config.STADTBEZIRKE, bezirke, _meta(quelle_bezirke, flaechen=FLAECHEN_STADTBEZIRKE,
                                                         abdeckung=pruefung["stadtbezirke"]))
    for name, p in (("Stadtteile", pruefung["stadtteile"]), ("Stadtbezirke", pruefung["stadtbezirke"])):
        e, a = p["eingabe"], p["abweichung_von_der_eingabe"]
        print(f"{name}: vorher {e['luecken_teile']} Lücken ({e['luecken_m2']} m²) und {e['ueberlappung_paare']} "
              f"überlappende Paare ({e['ueberlappung_m2']} m²), jetzt 0 und 0; Abstand zur Eingabe höchstens "
              f"{a['abstand_max_m']} m ({a['abstand_max_id']}), Median {a['abstand_median_m']} m")
    return pruefung


def abdeckung_schreiben():
    """Schritt `geo-abdeckung` (ohne Netz): die vorhandenen Stadtteile und Stadtbezirke in data/geo als lückenlose
    Abdeckung neu schreiben (Entscheidung 13.11.2026). Sind sie es schon, bleiben die Dateien unverändert (die Messung
    der ersten Bereinigung in meta.abdeckung bleibt erhalten)."""
    gj_teile = json.loads(config.ORTSTEILE.read_text(encoding="utf-8"))
    gj_bezirke = json.loads(config.STADTBEZIRKE.read_text(encoding="utf-8"))
    if _ist_abdeckung(gj_teile, gj_bezirke):
        print("Stadtteile und Stadtbezirke sind bereits eine lückenlose Abdeckung; data/geo unverändert")
        return None
    return _schreiben(gj_teile["features"], gj_bezirke["features"], gj_teile["meta"]["source"],
                      gj_bezirke["meta"]["source"])


def _hausnummer_basis(nr):
    m = re.match(r"\d+", nr or "")
    return int(m.group(0)) if m else None


def hausnummern():
    """Hausnummernverzeichnis aus dem Datensatz „Adressen Köln“ (161 531 Adressen, Stand 24.09.2026)."""
    r = _reader(_zip("adressen"), "Adresse")
    nummern, punkte, n = {}, {}, 0
    for sr in r.iterShapeRecords(fields=["str_amtl", "hausnr", "stteil"]):
        a = sr.record.as_dict()
        strasse, nr, teil = strassenname(a["str_amtl"]), (a["hausnr"] or "").strip().lower(), (a["stteil"] or "").strip()
        basis = _hausnummer_basis(nr)
        if not strasse or basis is None or not teil or not sr.shape.points:
            continue
        x, y = sr.shape.points[0]
        lon, lat = NACH_WGS84.transform(x, y)
        nummern.setdefault(strasse, {}).setdefault(teil, set()).add(basis)
        punkte.setdefault(strasse, {}).setdefault(teil, {})[nr] = [round(lon, 5), round(lat, 5)]
        n += 1
    config.HAUSNUMMERN.write_text(json.dumps({
        "meta": {"source": config.GEO_DOWNLOADS["adressen"], "license": config.SOURCES[config.QUELLE_ADRESSEN]["license"],
                 "adressen": n,
                 "note": "Straße (ausgeschrieben) → Stadtteil → Hausnummern ohne Zusatz; punkte: Straße → Stadtteil → "
                         "Hausnummer mit Zusatz → [lon, lat] (WGS84, 5 Nachkommastellen). Punktgenau verortet werden nur "
                         "Verwaltungsvorlagen und politische Anträge (Entscheidung 04.11.2026)."},
        "strassen": {s: {t: sorted(v) for t, v in sorted(d.items())} for s, d in sorted(nummern.items())},
        "punkte": {s: {t: dict(sorted(v.items())) for t, v in sorted(d.items())} for s, d in sorted(punkte.items())}},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{n} Adressen in {len(nummern)} Straßen → {config.HAUSNUMMERN}")


def write():
    teile = _flaechen(_zip("stadtteile"), "Stadtteil", lambda a: {
        "ortsteil": int(a["nummer"]), "ortsteil_bez": a["name"].strip(),
        "bezirk": int(a["nr_stbez"]), "bezirk_bez": a["stbezirk"].strip()})
    bezirke = _flaechen(_zip("stadtbezirke"), "Stadtbezirk", lambda a: {
        "bezirk": int(a["nummer"]), "bezirk_bez": a["name"].strip()})
    if len(teile) != 86 or len(bezirke) != 9:
        raise RuntimeError(f"unerwartete Anzahl: {len(teile)} Stadtteile, {len(bezirke)} Stadtbezirke (erwartet 86/9)")
    teile.sort(key=lambda f: f["properties"]["ortsteil"])
    bezirke.sort(key=lambda f: f["properties"]["bezirk"])
    _schreiben(teile, bezirke, config.GEO_DOWNLOADS["stadtteile"], config.GEO_DOWNLOADS["stadtbezirke"])
    print(f"{len(teile)} Stadtteile → {config.ORTSTEILE}; {len(bezirke)} Stadtbezirke → {config.STADTBEZIRKE}")

    from .geocode import Gazetteer   # liest die eben geschriebenen Flächen
    r = _reader(_zip("strassen"), "Strasse")
    ways = []
    for sr in r.iterShapeRecords():
        a, s = sr.record.as_dict(), sr.shape
        grenzen = list(s.parts) + [len(s.points)]
        for i in range(len(s.parts)):
            pts = s.points[grenzen[i]:grenzen[i + 1]]
            if len(pts) >= 2:
                ways.append({"name": strassenname(a["str_amtl"] or a["name"]), "highway": None,
                             "schluessel": a["nummer"], "coords": _transform_coords(pts)})
    gaz = Gazetteer(ways=ways, street_points=())
    for eintraege in gaz.streets.values():
        for e in eintraege:
            e["source"] = config.QUELLE_STRASSEN
    kreuzungen = {f"{a}|{b}": sorted(v) for (a, b), v in sorted(gaz.crossings.items())}
    config.STRASSEN.write_text(json.dumps({
        "meta": {"source": config.GEO_DOWNLOADS["strassen"], "license": config.SOURCES[config.QUELLE_STRASSEN]["license"],
                 "note": "Ortsteile (Stadtteile) je Straße per Verschneidung mit den Stadtteilflächen; component = räumlich "
                         "getrennte Lage desselben Namens (u. a. gleichnamige Straßen nach Eingemeindungen); kreuzungen = "
                         "Stadtteile, in denen sich zwei Straßen berühren; Namen ausgeschrieben (Str. → Straße)"},
        "streets": dict(sorted(gaz.streets.items())),
        "kreuzungen": kreuzungen}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mehrfach = sum(1 for e in gaz.streets.values() if len({x["component"] for x in e}) > 1)
    print(f"{len(gaz.streets)} Straßennamen ({mehrfach} mit mehreren Lagen), {len(kreuzungen)} Kreuzungen → {config.STRASSEN}")
    hausnummern()
