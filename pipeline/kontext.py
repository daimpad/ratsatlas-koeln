"""Kontextdaten je Ortsteil (kontext/KONZEPT.md, Phase 1): Kennzahlen zur Einordnung von Vorlagen.

Einordnung, kein Urteil: keine Rangfolge der Ortsteile. Alle Werte sind auf Ortsteile umgerechnet und damit abgeleitet;
jede Kennzahl trägt Quelle, Lizenz, Stichtag und Methode (kontext/phase0/BERICHT.md).

Schritte:
- `kontext-ausschnitte` (einmalig, lokal; neu nur bei neuem Stand einer Quelle): lädt Zensus 2022, Bodenrichtwerte,
  Klimaanalyse, Überschwemmungsgebiete und Kitas, schneidet Bonn aus und legt die Ausschnitte in data/kontext/ ab.
  Die Downloads (bis 2 GB) bleiben außerhalb des Repositorys (KONTEXT_DL, Vorgabe _kontext_dl/).
- `fetch-haltestellen` (monatlich im Workflow): Haltestellen aus dem Fahrplan des VRS (GTFS).
- `kontext` (täglich, nach export): Kennzahlen je Ortsteil, Stadtbezirk und für ganz Bonn → export/bonn/kontext.json,
  Audit export/audit_kontext.tsv.
"""
import csv
import io
import json
import math
import os
import shutil
import sqlite3
import statistics
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from shapely import STRtree, from_wkb, make_valid, prepare, union_all
from shapely.geometry import Point, mapping, shape

from . import config, flaechen

KONTEXT = config.ROOT / "data" / "kontext"
DL = Path(os.environ.get("KONTEXT_DL", config.ROOT / "_kontext_dl"))
STAND = KONTEXT / "STAND.json"
HALT_STAND = KONTEXT / "haltestellen_stand.json"   # eigene Datei: monatlich im Workflow erneuert (Zwischenspeicher)
ZENSUS, BRW, KLIMA, UESG, KITAS, HALT = (KONTEXT / n for n in (
    "zensus_bonn.tsv", "bodenrichtwerte_bonn.geojson", "klima_bonn.geojson", "ueberschwemmung_bonn.geojson",
    "kitas_bonn.tsv", "haltestellen_bonn.tsv"))
WAHL_SB, WAHL_ZU = KONTEXT / "wahl2025_stimmbezirke.tsv", KONTEXT / "wahl2025_zuordnung.tsv"   # pipeline/wahlen.py
OUT = "kontext.json"
AUDIT = "audit_kontext.tsv"
AUDIT_WAHL = "audit_wahlbeteiligung.tsv"
MIN_EINWOHNER = 100          # darunter keine Anteile und Mittelwerte (Hardthöhe: 20 Einwohner)
# Bodenrichtwert: Hinweis, wenn mindestens so viele Prozent der Einwohner in keiner Zone für Wohnbauland wohnen
# (Misch- und Kerngebiete; Entscheidung des Auftraggebers 24.10.2026)
BRW_HINWEIS_OHNE_ZONE = 33
DRINGEND = {"Handlungspriorität 1", "Handlungspriorität 2"}   # Wortlaut der Karte: „dringender Handlungsbedarf“
UESG_GESAMT = "festgesetzt oder vorläufig gesichert"
VEREINFACHUNG = 0.00001      # etwa 1 m, für die Ausschnitte der Flächen

Z = "https://www.destatis.de/static/DE/zensus/gitterdaten/"
O = "https://www.opengeodata.nrw.de/produkte/"
QUELLEN = {
    "zensus": {"titel": "Zensus 2022, Gitterzellen 100 m", "url": "https://www.zensus2022.de/DE/Ergebnisse-des-Zensus/gitterzellen.html",
               "lizenz": "dl-de/by-2.0, © Statistisches Bundesamt (Destatis), Zensus 2022", "stand": "2022-05-15",
               "dateien": {"bev.zip": Z + "Zensus2022_Bevoelkerungszahl.zip", "u18.zip": Z + "Anteil_unter_18-jaehrige_in_Gitterzellen.zip",
                           "a65.zip": Z + "Anteil_ab_65-jaehrige_in_Gitterzellen.zip",
                           "miete.zip": Z + "Durchschnittliche_Nettokaltmiete_und_Anzahl_der_Wohnungen.zip"}},
    "bodenrichtwerte": {"titel": "BORIS NRW, Bodenrichtwerte (Gutachterausschuss für Grundstückswerte in der Stadt Bonn)",
                        "url": O + "infrastruktur_bauen_wohnen/boris/BRW/", "lizenz": "dl-de/zero-2.0",
                        "stand": "2026-01-01", "dateien": {"brw.zip": O + "infrastruktur_bauen_wohnen/boris/BRW/BRW_EPSG25832_Shape.zip"}},
    "klima": {"titel": "Klimaanalyse NRW 2026, Planungshinweiskarte (Handlungspriorität)",
              "url": O + "umwelt_klima/klima/klimaanalyse/planunghinweis/", "lizenz": "dl-de/zero-2.0", "stand": "2026-04-08",
              "dateien": {"phk.zip": O + "umwelt_klima/klima/klimaanalyse/planunghinweis/Klimaanalyse-Planungshinweiskarte_2026_EPSG25832_GeoPackage.zip"}},
    "ueberschwemmung": {"titel": "Überschwemmungsgebiete NRW (festgesetzt und vorläufig gesichert)",
                        "url": O + "umwelt_klima/wasser/hochwasser/uesg/", "lizenz": "dl-de/zero-2.0", "stand": None,
                        "dateien": {"uesg.zip": O + "umwelt_klima/wasser/hochwasser/uesg/uesg_EPSG25832_Shape.zip"}},
    "kitas": {"titel": "Kindertageseinrichtungen in NRW", "url": O + "bildung_wissenschaft/kitas/",
              "lizenz": "dl-de/by-2.0, Land NRW", "stand": None,
              "dateien": {"kitas.csv": O + "bildung_wissenschaft/kitas/KiTasNRW_EPSG4326_CSV.csv"}},
    "haltestellen": {"titel": "VRS-Fahrplandaten (GTFS)", "url": "https://www.vrs.de/fuer-unternehmen/open-data-service",
                     "lizenz": "dl-de/zero-2.0", "stand": None,
                     "dateien": {"gtfs.zip": "https://download.vrsinfo.de/gtfs/GTFS_VRS_mit_SPNV.zip"}},
}

# Kennzahlen: Schlüssel → Beschreibung für Seite, Assistent und DCAT
KENNZAHLEN = {
    "einwohner": ("Einwohnerinnen und Einwohner", "Personen", "zensus", "Summe der 100-m-Zellen, deren Mittelpunkt im Gebiet liegt"),
    "unter_18": ("Anteil unter 18 Jahren", "%", "zensus", "Anteil je Zelle, gewichtet nach Einwohnern; geheim gehaltene Zellen zählen mit 0"),
    "ab_65": ("Anteil ab 65 Jahren", "%", "zensus", "wie „unter 18“"),
    "miete": ("durchschnittliche Nettokaltmiete", "€/m²", "zensus", "Mittel der Zellen, gewichtet nach Wohnungen (Bestandsmieten, kein Mietspiegel)"),
    "bodenrichtwert": ("Bodenrichtwert Wohnbauland (Median)", "€/m²", "bodenrichtwerte",
                       "Zone, in der eine Zelle liegt (bei überlagerten Zonen zu gleichen Teilen); Median nach Einwohnern; nur baureifes Wohnbauland, ohne bebaute Flächen im Außenbereich; bodenrichtwert_abdeckung: Anteil der Einwohner in einer solchen Zone"),
    "haltestellen": ("Haltestellen", "Anzahl", "haltestellen", "Haltestellen (Steige zusammengefasst) im Gebiet"),
    "kitas": ("Kindertageseinrichtungen", "Anzahl", "kitas", "Einrichtungen im Gebiet"),
    "kita_plaetze_u3": ("Kita-Plätze unter 3 Jahren", "Anzahl", "kitas", "Summe der Einrichtungen im Gebiet"),
    "kita_plaetze_ue3": ("Kita-Plätze ab 3 Jahren", "Anzahl", "kitas", "Summe der Einrichtungen im Gebiet"),
    "hitze": ("Anteil der Einwohner in Flächen mit dringendem Handlungsbedarf (Hitze)", "%", "klima",
              "Einwohner laut Karte in Flächen der Handlungspriorität 1–2, anteilig nach Fläche"),
    "ueberschwemmung": ("Anteil der Einwohner im Überschwemmungsgebiet", "%", "ueberschwemmung",
                        "Einwohner in Zellen, deren Mittelpunkt im Überschwemmungsgebiet liegt"),
    "wahlbeteiligung": ("Wahlbeteiligung Ratswahl 2025 (geschätzt)", "%", "wahl2025",
                        "Wähler je Stimmbezirk an der Urne, dazu die Briefwähler des Wahlbezirks im Verhältnis der "
                        "Wahlberechtigten mit Sperrvermerk „W“ (Briefwahlschein); Stimmbezirke anteilig nach Adressen "
                        "auf Ortsteile verteilt (Straßenverzeichnis 2020); geschätzt, Abweichung bis etwa 3 Prozentpunkte; "
                        "ganz Bonn amtlich; kein Wert für Ortsteile ohne eigenen Stimmbezirk"),
}
OHNE_WERT = {"wahlbeteiligung": "ohne eigenen Stimmbezirk"}   # Grund, wenn ein Ortsteil keinen Wert hat (sonst Mindestgröße)
ANTEILE = {"unter_18", "ab_65", "miete", "bodenrichtwert", "bodenrichtwert_abdeckung", "hitze", "ueberschwemmung",
           "wahlbeteiligung"}   # erst ab MIN_EINWOHNER


def _num(s):
    s = (s or "").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _gebiete():
    """[(Ortsteil, Stadtbezirk, Fläche)] und ein Finder für Punkte (WGS84)."""
    gj = json.loads(config.ORTSTEILE.read_text())
    ots = sorted((f["properties"]["ortsteil_bez"], f["properties"]["bezirk_bez"], shape(f["geometry"])) for f in gj["features"])
    tree = STRtree([g for *_, g in ots])
    for *_, g in ots:
        prepare(g)
    def finde(lon, lat):
        p = Point(lon, lat)
        for i in tree.query(p):
            if ots[i][2].contains(p):
                return ots[i][0]
        return None
    return ots, finde


# --- Ausschnitte (einmalig) -----------------------------------------------------------------------------------------

def _laden(name, url):
    DL.mkdir(parents=True, exist_ok=True)
    path = DL / name
    if not path.exists():
        print(f"  lade {url}")
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=600) as r, open(path.with_suffix(".tmp"), "wb") as f:
            shutil.copyfileobj(r, f)
        path.with_suffix(".tmp").replace(path)
    return path


def _datum(url):
    """Stand einer Datei laut Server (Last-Modified), sonst None."""
    from email.utils import parsedate_to_datetime
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            return parsedate_to_datetime(r.headers["Last-Modified"]).date().isoformat()
    except Exception:
        return None


def _csv_aus_zip(path, teil):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if teil in n and n.endswith(".csv"))
        with z.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";")


def _geojson(path, features, meta):
    path.write_text(json.dumps({"type": "FeatureCollection", "meta": meta, "features": features},
                               ensure_ascii=False, separators=(",", ":")) + "\n")


def _flaeche(g, nach_wgs):
    from shapely import transform
    g = transform(g, nach_wgs, interleaved=False).simplify(VEREINFACHUNG, preserve_topology=True)
    return json.loads(json.dumps(mapping(g)), parse_float=lambda x: round(float(x), 6))


def ausschnitte(nur=None):
    """Ausschnitte für Bonn erzeugen (pyproj und pyshp nötig). nur: Quellen, die neu geschnitten werden
    (Umgebungsvariable KONTEXT_NUR, z. B. „ueberschwemmung“); Standard alle."""
    nur = set(filter(None, (nur if nur is not None else os.environ.get("KONTEXT_NUR", "")).split(",")))
    teil = lambda k: not nur or k in nur
    import shapefile
    from pyproj import Transformer
    KONTEXT.mkdir(parents=True, exist_ok=True)
    ots, finde = _gebiete()
    stand = json.loads(STAND.read_text()) if STAND.exists() else {}
    heute = datetime.now(timezone.utc).date().isoformat()
    def vermerk(key, **extra):
        q = QUELLEN[key]
        stand[key] = {"titel": q["titel"], "url": q["url"], "lizenz": q["lizenz"], "stand": q["stand"], "abgerufen": heute, **extra}
    von3035 = Transformer.from_crs(3035, 4326, always_xy=True)
    von25832 = Transformer.from_crs(25832, 4326, always_xy=True)
    nach25832 = Transformer.from_crs(4326, 25832, always_xy=True)
    bonn = union_all([g for *_, g in ots])
    w, s, e, n = bonn.bounds

    if teil("zensus"):
        # Zensus: Zellen mit Mittelpunkt in Bonn
        dl = {k: _laden(k, u) for k, u in QUELLEN["zensus"]["dateien"].items()}
        zellen = {}
        def zelle(row):
            x, y = float(row["x_mp_100m"]), float(row["y_mp_100m"])
            lon, lat = von3035.transform(x, y)
            if not (w <= lon <= e and s <= lat <= n):
                return None
            gid = row.get("GITTER_ID_100m") or row.get("GITTER_ID_100M")
            if gid not in zellen:
                if not finde(lon, lat):
                    return None
                zellen[gid] = {"gitter_id": gid, "lon": round(lon, 6), "lat": round(lat, 6), "einwohner": 0,
                               "unter_18": "", "ab_65": "", "miete": "", "wohnungen": ""}
            return zellen[gid]
        for row in _csv_aus_zip(dl["bev.zip"], "100m"):
            if (z := zelle(row)) is not None:
                z["einwohner"] = int(row["Einwohner"])
        for key, datei, spalte in (("unter_18", "u18.zip", "AnteilUnter18"), ("ab_65", "a65.zip", None)):
            for row in _csv_aus_zip(dl[datei], "100m"):
                gid = row.get("GITTER_ID_100m") or row.get("GITTER_ID_100M")
                if gid in zellen:
                    col = spalte or next(k for k in row if k.startswith("Anteil"))
                    v = _num(row[col])
                    zellen[gid][key] = "" if v is None else v
        for row in _csv_aus_zip(dl["miete.zip"], "100m"):
            if (z := zelle(row)) is not None:
                m, n_whg = _num(row["durchschnMieteQM"]), _num(row["AnzahlWohnungen"])
                z["miete"], z["wohnungen"] = ("" if m is None else m), ("" if n_whg is None else int(n_whg))
        with open(ZENSUS, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=["gitter_id", "lon", "lat", "einwohner", "unter_18", "ab_65", "miete", "wohnungen"],
                                delimiter="\t", lineterminator="\n")
            wr.writeheader()
            wr.writerows(sorted(zellen.values(), key=lambda z: z["gitter_id"]))
        vermerk("zensus", zellen=len(zellen))
        print(f"Zensus: {len(zellen)} Zellen, {sum(z['einwohner'] for z in zellen.values())} Einwohner → {ZENSUS}")

    if teil("bodenrichtwerte"):
        # Bodenrichtwerte: Wohnbauland (NUTA W*), baureif, ohne bebaute Flächen im Außenbereich (ASB)
        path = _laden("brw.zip", QUELLEN["bodenrichtwerte"]["dateien"]["brw.zip"])
        ziel = DL / "brw"
        with zipfile.ZipFile(path) as z:
            z.extractall(ziel)
        shp = next(ziel.glob("*.shp"))
        r = shapefile.Reader(str(shp.with_suffix("")))
        names = [f[0] for f in r.fields[1:]]
        feats = []
        for sr in r.iterShapeRecords():
            d = dict(zip(names, sr.record))
            if d["GENA"] == "Bonn" and d["NUTA"].startswith("W") and d["ENTW"] == "B" and d["ERGNUTA"] != "ASB":
                feats.append({"type": "Feature", "properties": {"zone": d["BRWZNR"], "brw": _num(d["BRW"]), "nutzung": d["NUTA"],
                                                                 "ergaenzung": d["ERGNUTA"], "ortsteil_boris": d["ORTST"], "stichtag": d["STAG"]},
                              "geometry": _flaeche(shape(sr.shape.__geo_interface__), von25832.transform)})
        feats.sort(key=lambda f: (f["properties"]["zone"], f["properties"]["brw"]))
        meta = {"quelle": QUELLEN["bodenrichtwerte"]["titel"], "lizenz": QUELLEN["bodenrichtwerte"]["lizenz"]}
        _geojson(BRW, feats, meta)
        vermerk("bodenrichtwerte", zonen=len(feats), stand=feats[0]["properties"]["stichtag"] if feats else None)
        print(f"Bodenrichtwerte: {len(feats)} Zonen → {BRW}")

    if teil("klima"):
        # Klimaanalyse: Flächen mit Handlungspriorität in Bonn (GeoPackage)
        path = _laden("phk.zip", QUELLEN["klima"]["dateien"]["phk.zip"])
        ziel = DL / "phk"
        if not any(ziel.glob("*.gpkg")):
            with zipfile.ZipFile(path) as z:
                z.extractall(ziel)
        db = sqlite3.connect(next(ziel.glob("*.gpkg")))
        feats = []
        for fid, blob, hp, ew in db.execute("SELECT fid, geom, Handlungspriorität, Einwohnerzahl FROM PL_KY_PHK_HP "
                                            "WHERE GN = 'Bonn' ORDER BY fid"):
            env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 7]
            g = from_wkb(bytes(blob[8 + env:])).buffer(0)
            feats.append({"type": "Feature", "properties": {"id": fid, "prioritaet": hp, "einwohner": round(ew or 0, 1)},
                          "geometry": _flaeche(g, von25832.transform)})
        _geojson(KLIMA, feats, {"quelle": QUELLEN["klima"]["titel"], "lizenz": QUELLEN["klima"]["lizenz"]})
        vermerk("klima", flaechen=len(feats))
        print(f"Klimaanalyse: {len(feats)} Flächen → {KLIMA}")

    if teil("ueberschwemmung"):
        # Überschwemmungsgebiete: festgesetzt und vorläufig gesichert, auf Bonn zugeschnitten
        path = _laden("uesg.zip", QUELLEN["ueberschwemmung"]["dateien"]["uesg.zip"])
        ziel = DL / "uesg"
        with zipfile.ZipFile(path) as z:
            z.extractall(ziel)
        from shapely import transform
        bonn25832 = transform(bonn, nach25832.transform, interleaved=False).buffer(100)
        # Gesamtfläche (für die Kennzahl, ohne innere Grenzen) und die vorläufig gesicherten Teile, die nicht zugleich
        # festgesetzt sind (nur für die Karte; getrennt vereinfachte Teilflächen ließen an gemeinsamen Grenzen Spalten)
        arten = {}
        for art, name in (("festgesetzt", "festgesetzte_Ueberschwemmungsgebiete"),
                          ("vorläufig gesichert", "vorlaeufig_gesicherte_Ueberschwemmungsgebiete")):
            teile = []
            for sh in shapefile.Reader(str(ziel / name)).iterShapes():
                g = shape(sh.__geo_interface__)
                if g.intersects(bonn25832):
                    teile.append(g.buffer(0).intersection(bonn25832))
            arten[art] = teile
        gesamt = union_all(arten["festgesetzt"] + arten["vorläufig gesichert"])
        vorlaeufig = union_all(arten["vorläufig gesichert"]).difference(union_all(arten["festgesetzt"]))
        teile = [(UESG_GESAMT, gesamt)] + ([("vorläufig gesichert", vorlaeufig)] if not vorlaeufig.is_empty else [])
        _geojson(UESG, [{"type": "Feature", "properties": {"art": art}, "geometry": _flaeche(g, von25832.transform)}
                        for art, g in teile],
                 {"quelle": QUELLEN["ueberschwemmung"]["titel"], "lizenz": QUELLEN["ueberschwemmung"]["lizenz"]})
        # die Datei des Landes wird jede Nacht neu erzeugt; ihr Datum ist daher der Tag des Abrufs, kein Stand der Daten
        # (Code-Prüfung 24.10.2026)
        vermerk("ueberschwemmung", stand=f"laufend aktualisiert, Abruf {datetime.now(timezone.utc):%d.%m.%Y}")
        print(f"Überschwemmungsgebiete: {len(teile)} Flächen → {UESG}")

    if teil("kitas"):
        # Kitas: Einrichtungen in Bonn
        path = _laden("kitas.csv", QUELLEN["kitas"]["dateien"]["kitas.csv"])
        rows = []
        with open(path, encoding="utf-8-sig") as f:
            for k in csv.DictReader(f, delimiter=";"):
                try:
                    lat, lon = map(float, k["Geokoordinate"].split(","))
                except ValueError:
                    continue
                if finde(lon, lat):
                    rows.append({"id": k["Id"], "name": k["Einrichtung Name"], "lon": round(lon, 6), "lat": round(lat, 6),
                                 "plaetze_u3": int(_num(k["U3-Plätze"]) or 0), "plaetze_ue3": int(_num(k["Ü3-Plätze"]) or 0)})
        rows.sort(key=lambda r: int(r["id"]))
        with open(KITAS, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
            wr.writeheader()
            wr.writerows(rows)
        vermerk("kitas", einrichtungen=len(rows), stand=_datum(QUELLEN["kitas"]["dateien"]["kitas.csv"]))
        print(f"Kitas: {len(rows)} → {KITAS}")

    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    if teil("haltestellen"):
        fetch_haltestellen()


def fetch_haltestellen():
    """Haltestellen in Bonn aus dem GTFS des VRS: Steige gleichen Namens zu einem Punkt zusammengefasst."""
    path = DL / "gtfs.zip"
    if path.exists():
        path.unlink()   # monatlich neu
    path = _laden("gtfs.zip", QUELLEN["haltestellen"]["dateien"]["gtfs.zip"])
    ots, finde = _gebiete()
    punkte = defaultdict(list)
    with zipfile.ZipFile(path) as z:
        for s in csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), encoding="utf-8-sig")):
            if s.get("location_type") not in ("", "0", None):
                continue
            lon, lat = float(s["stop_lon"]), float(s["stop_lat"])
            if (ot := finde(lon, lat)):
                punkte[(s["stop_name"], ot)].append((lon, lat))
    if len(punkte) < 300:
        raise RuntimeError(f"Haltestellen: nur {len(punkte)} in Bonn – Abruf unvollständig, Stand bleibt")
    q = QUELLEN["haltestellen"]
    # ohne Last-Modified gilt der Tag des Abrufs; ein leerer Stand hielte sonst die Prüfung in check bis zum
    # nächsten monatlichen Abruf an (Code-Prüfung 24.10.2026)
    stand = _datum(q["dateien"]["gtfs.zip"]) or datetime.now(timezone.utc).date().isoformat()
    with open(HALT, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["name", "ortsteil", "lon", "lat", "steige"])
        for (name, ot), pts in sorted(punkte.items()):
            wr.writerow([name, ot, round(statistics.fmean(p[0] for p in pts), 6), round(statistics.fmean(p[1] for p in pts), 6), len(pts)])
    HALT_STAND.write_text(json.dumps({"titel": q["titel"], "url": q["url"], "lizenz": q["lizenz"],
                                      "stand": stand, "haltestellen": len(punkte)},
                                     ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"Haltestellen: {len(punkte)} in Bonn → {HALT}")


# --- Kennzahlen (täglich) -------------------------------------------------------------------------------------------

def _wmedian(paare):
    """Gewichteter Median; liegt die Hälfte genau auf der Grenze zweier Werte, deren Mittel (Code-Prüfung
    24.10.2026: Zellen in zwei überlagerten Zonen zu gleichen Teilen ergaben sonst stets die günstigere Zone)."""
    paare, acc = sorted(paare), 0
    gesamt = sum(g for _, g in paare)
    for i, (v, g) in enumerate(paare):
        acc += g
        if math.isclose(acc, gesamt / 2) and i + 1 < len(paare):
            return round((v + paare[i + 1][0]) / 2, 1)
        if acc >= gesamt / 2:
            return v
    return None


def wahlbeteiligung():
    """Wahlbeteiligung der Ratswahl 2025 (wahlen/phase0/BERICHT.md): je Urnenstimmbezirk die Wähler an der Urne und die
    Briefwähler des Wahlbezirks im Verhältnis des Sperrvermerks „W“; je Gruppe des Straßenverzeichnisses anteilig nach
    Adressen auf Ortsteile verteilt. ({Ortsteil: [Wahlberechtigte, Wähler]}, Ortsteile mit eigenem Stimmbezirk
    (Hauptanteil der Adressen), Bonn [Wahlberechtigte, Wähler] amtlich, Audit-Zeilen je Gruppe) oder None ohne Ausschnitt."""
    if not (WAHL_SB.exists() and WAHL_ZU.exists()):
        return None
    with open(WAHL_SB, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    brief, sperr = defaultdict(int), defaultdict(int)
    for r in rows:
        if r["art"] == "Brief":
            brief[r["wahlbezirk"]] += int(r["waehler"])
        else:
            sperr[r["wahlbezirk"]] += int(r["sperrvermerk_w"])
    sb = {int(r["stimmbezirk"]): (int(r["wahlberechtigte"]), int(r["waehler"]),
                                  int(r["sperrvermerk_w"]) * brief[r["wahlbezirk"]] / sperr[r["wahlbezirk"]] if sperr[r["wahlbezirk"]] else 0)
          for r in rows if r["art"] == "Urne"}
    zu = defaultdict(dict)
    with open(WAHL_ZU, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            zu[r["stimmbezirke"]][r["ortsteil"]] = int(r["adressen"])
    ot, eigen, audit, gesehen = defaultdict(lambda: [0.0, 0.0]), set(), [], set()
    for g, d in sorted(zu.items(), key=lambda x: [int(t) for t in x[0].split("/")]):
        teile = [int(t) for t in g.split("/")]
        gesehen |= set(teile)
        a = sum(sb[t][0] for t in teile)
        urne = sum(sb[t][1] for t in teile)
        b = sum(sb[t][2] for t in teile)
        n = sum(d.values())
        haupt = max(d, key=lambda k: (d[k], k))
        eigen.add(haupt)
        for name, c in d.items():
            ot[name][0] += a * c / n
            ot[name][1] += (urne + b) * c / n
        audit.append([g, a, urne, round(b), round(100 * (urne + b) / a, 1) if a else "", haupt, round(d[haupt] / n, 2),
                      "; ".join(f"{k} {v}" for k, v in sorted(d.items()) if k != haupt)])
    if set(sb) - gesehen:
        raise RuntimeError(f"Wahlbeteiligung: Stimmbezirke ohne Zuordnung {sorted(set(sb) - gesehen)}")
    bonn = [sum(int(r["wahlberechtigte"]) for r in rows), sum(int(r["waehler"]) for r in rows)]
    return ot, eigen, bonn, audit


def kennzahlen():
    """Kennzahlen je Ortsteil, Stadtbezirk und ganz Bonn aus den Ausschnitten: ({Gebiet: Werte}, Audit-Zeilen)."""
    ots, finde = _gebiete()
    bezirk = {n: b for n, b, _ in ots}
    gebiete = lambda ot: (("ortsteil", ot), ("bezirk", bezirk[ot]), ("bonn", "Bonn"))
    acc = defaultdict(lambda: defaultdict(float))
    brw = defaultdict(list)
    # gerundete Koordinaten der Ausschnitte können Flächen ungültig machen: beim Einlesen gültig machen
    flaeche = lambda f: make_valid(shape(f["geometry"]))
    zonen = json.loads(BRW.read_text())["features"]
    zgeo = [flaeche(f) for f in zonen]
    ztree = STRtree(zgeo)
    # Kennzahl aus der Gesamtfläche; die Teilfläche „vorläufig gesichert“ dient nur der Karte
    uesg = union_all([flaeche(f) for f in json.loads(UESG.read_text())["features"] if f["properties"]["art"] == UESG_GESAMT])
    prepare(uesg)
    with open(ZENSUS, encoding="utf-8") as f:
        for z in csv.DictReader(f, delimiter="\t"):
            lon, lat, e = float(z["lon"]), float(z["lat"]), int(z["einwohner"])
            ot = finde(lon, lat)
            if not ot:
                continue
            p = Point(lon, lat)
            # Zonen können sich überlagern (etwa Ein- und Zweifamilienhäuser und Geschosswohnungsbau im selben Gebiet):
            # die Einwohner der Zelle verteilen sich gleichmäßig auf alle Zonen, in denen sie liegt
            zone = sorted(zonen[i]["properties"]["brw"] for i in ztree.query(p) if zgeo[i].contains(p))
            drin = e and uesg.contains(p)
            for g in gebiete(ot):
                a = acc[g]
                a["einwohner"] += e
                for k in ("unter_18", "ab_65"):
                    if z[k] == "":
                        a[f"{k}_geheim"] += e
                    else:
                        a[k] += float(z[k]) * e
                if z["miete"] != "" and z["wohnungen"] not in ("", "0"):
                    a["miete_summe"] += float(z["miete"]) * int(z["wohnungen"])
                    a["wohnungen"] += int(z["wohnungen"])
                if e and zone:
                    brw[g] += [(v, e / len(zone)) for v in zone]
                    a["brw_ueberlagert"] += e if len(zone) > 1 else 0
                elif e:
                    a["brw_ohne_zone"] += e
                if drin:
                    a["ueberschwemmung"] += e
    with open(HALT, encoding="utf-8") as f:
        halt = defaultdict(set)
        for h in csv.DictReader(f, delimiter="\t"):
            if h["ortsteil"] in bezirk:
                for g in gebiete(h["ortsteil"]):
                    halt[g].add(h["name"])
    with open(KITAS, encoding="utf-8") as f:
        for k in csv.DictReader(f, delimiter="\t"):
            if (ot := finde(float(k["lon"]), float(k["lat"]))):
                for g in gebiete(ot):
                    acc[g]["kitas"] += 1
                    acc[g]["kita_plaetze_u3"] += int(k["plaetze_u3"])
                    acc[g]["kita_plaetze_ue3"] += int(k["plaetze_ue3"])
    otgeo = {n: g for n, _, g in ots}
    otree = STRtree([g for *_, g in ots])
    for fl in json.loads(KLIMA.read_text())["features"]:
        g = flaeche(fl)
        if g.is_empty or not g.area:
            continue
        for i in otree.query(g):
            n = ots[i][0]
            anteil = otgeo[n].intersection(g).area / g.area
            if anteil <= 0:
                continue
            ew = fl["properties"]["einwohner"] * anteil
            for gb in gebiete(n):
                acc[gb]["klima_ew"] += ew
                if fl["properties"]["prioritaet"] in DRINGEND:
                    acc[gb]["klima_dringend"] += ew

    wahl = wahlbeteiligung()
    if wahl:
        for name, (a, w) in wahl[0].items():
            if name in bezirk:
                for g in gebiete(name)[:2]:   # Ortsteil und Stadtbezirk; ganz Bonn amtlich (unten)
                    acc[g]["wahl_a"] += a
                    acc[g]["wahl_w"] += w
    werte, audit = {}, []
    for g, a in sorted(acc.items()):
        e = int(a["einwohner"])
        v = {"einwohner": e, "haltestellen": len(halt[g]), "kitas": int(a["kitas"]),
             "kita_plaetze_u3": int(a["kita_plaetze_u3"]), "kita_plaetze_ue3": int(a["kita_plaetze_ue3"])}
        if e >= MIN_EINWOHNER:
            v["unter_18"] = round(a["unter_18"] / e, 1)
            v["ab_65"] = round(a["ab_65"] / e, 1)
            v["miete"] = round(a["miete_summe"] / a["wohnungen"], 2) if a["wohnungen"] else None
            v["bodenrichtwert"] = _wmedian(brw[g])
            v["bodenrichtwert_abdeckung"] = round(100 - 100 * a["brw_ohne_zone"] / e, 1)   # Anteil der Einwohner in einer Zone
            v["hitze"] = round(100 * a["klima_dringend"] / a["klima_ew"], 1) if a["klima_ew"] else None
            v["ueberschwemmung"] = round(100 * a["ueberschwemmung"] / e, 1)
            if wahl and g[0] == "bonn":
                v["wahlbeteiligung"] = round(100 * wahl[2][1] / wahl[2][0], 1)
            elif wahl and a["wahl_a"] and (g[0] == "bezirk" or g[1] in wahl[1]):
                v["wahlbeteiligung"] = round(100 * a["wahl_w"] / a["wahl_a"])   # geschätzt: ganze Prozent
        werte[g] = v
        geheim = max(a["unter_18_geheim"], a["ab_65_geheim"])
        audit.append([g[0], g[1], e, round(100 * geheim / e, 1) if e else "", int(a["wohnungen"]),
                      round(100 * a["brw_ohne_zone"] / e, 1) if e else "", round(100 * a["brw_ueberlagert"] / e, 1) if e else "",
                      round(a["klima_ew"]),
                      "ja" if e < MIN_EINWOHNER else ""])
    return werte, audit, (wahl[3] if wahl else None)


# Zuschaltbare Flächen der Karte (nur beim Einschalten geladen): Überschwemmungsgebiete je Art, Bodenrichtwertzonen.
# Gröber vereinfacht als die Gebietsflächen (etwa 5 m), weil sie nur zur Einordnung dienen; verbindlich sind die Quellen.
FLAECHEN = {"ueberschwemmung": (UESG, ("art",)), "bodenrichtwerte": (BRW, ("zone", "brw", "ergaenzung", "stichtag"))}
FLAECHEN_TOLERANZ = 0.00005


def _uesg_karte(gj):
    """Für die Karte: festgesetzt (Gesamtfläche ohne vorläufig gesicherte Teile) und vorläufig gesichert."""
    fs = {f["properties"]["art"]: make_valid(shape(f["geometry"])) for f in gj["features"]}
    v = fs.get("vorläufig gesichert")
    teile = [("festgesetzt", fs[UESG_GESAMT].difference(v) if v else fs[UESG_GESAMT])] + ([("vorläufig gesichert", v)] if v else [])
    return {"features": [{"type": "Feature", "properties": {"art": a}, "geometry": mapping(g)} for a, g in teile]}


def zuschaltbar(ziel):
    ziel.mkdir(parents=True, exist_ok=True)
    for name, (src, felder) in FLAECHEN.items():
        gj = json.loads(src.read_text())
        if name == "ueberschwemmung":
            gj = _uesg_karte(gj)
        gj = {"features": [{**f, "properties": {k: f["properties"].get(k) for k in felder}} for f in gj["features"]]}
        data = flaechen.simplify(gj, FLAECHEN_TOLERANZ)
        (ziel / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def write():
    """Pipeline-Schritt `kontext`: export/bonn/kontext.json und export/audit_kontext.tsv."""
    if not all(p.exists() for p in (ZENSUS, BRW, KLIMA, UESG, KITAS, HALT, STAND, HALT_STAND)):
        print("Kontextdaten: Ausschnitte fehlen (python -m pipeline kontext-ausschnitte) – übersprungen.")
        return
    werte, audit, audit_wahl = kennzahlen()
    zuordnung = {n: b for n, b, _ in _gebiete()[0]}
    stand = {**json.loads(STAND.read_text()), "haltestellen": json.loads(HALT_STAND.read_text())}
    meta = {"hinweis": "Einordnung, kein Urteil. Alle Werte sind auf Ortsteile umgerechnet (abgeleitet).",
            "mindest_einwohner": MIN_EINWOHNER,
            "bodenrichtwert_hinweis_ohne_zone": BRW_HINWEIS_OHNE_ZONE,
            "reihenfolge": [k for k in KENNZAHLEN if k != "wahlbeteiligung" or audit_wahl],   # Reihenfolge für Steckbrief und Assistent (die Schlüssel werden sortiert)
            "quellen": {k: {f: stand[k].get(f) for f in ("titel", "url", "lizenz", "stand", "uebergang") if f != "uebergang" or stand[k].get(f)}
                        for k in sorted(stand)},
            "kennzahlen": {k: {"titel": t, "einheit": u, "quelle": q, "methode": m, **({"ohne_wert": OHNE_WERT[k]} if k in OHNE_WERT else {})}
                           for k, (t, u, q, m) in KENNZAHLEN.items() if k != "wahlbeteiligung" or audit_wahl}}
    doc = {"meta": meta,
           "bonn": werte[("bonn", "Bonn")],
           "bezirke": {n: v for (art, n), v in werte.items() if art == "bezirk"},
           "ortsteile": {n: v for (art, n), v in werte.items() if art == "ortsteil"},
           "stadtbezirk_je_ortsteil": zuordnung}
    out = config.EXPORT / "bonn" / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    zuschaltbar(config.EXPORT / "bonn" / "flaechen")
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    with open(config.EXPORT / AUDIT, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["ebene", "gebiet", "einwohner", "alter_geheim_prozent", "wohnungen_mit_miete",
                     "bodenrichtwert_ohne_zone_prozent", "bodenrichtwert_zonen_ueberlagert_prozent", "einwohner_laut_klimakarte", "unter_mindestgroesse"])
        wr.writerows(audit)
    if audit_wahl:
        with open(config.EXPORT / AUDIT_WAHL, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f, delimiter="\t", lineterminator="\n")
            wr.writerow(["stimmbezirke", "wahlberechtigte", "waehler_urne", "briefwaehler_geschaetzt", "beteiligung_geschaetzt_prozent",
                         "hauptortsteil", "anteil_adressen_hauptortsteil", "weitere_ortsteile_adressen"])
            wr.writerows(audit_wahl)
    print(f"Kontextdaten: {len(doc['ortsteile'])} Ortsteile, {len(doc['bezirke'])} Stadtbezirke, "
          f"Bonn {doc['bonn']['einwohner']} Einwohner → {out}")


# Bevölkerung Bonn am 31.12.2022 auf Basis des Zensus 2022 (IT.NRW, Kommunalprofil Bonn, Stand 15.01.2026)
AMTLICH_EINWOHNER = 322221
# Wahlbeteiligung der Ratswahl 2025 in Bonn laut Heft 3 der Stadt (160.220 von 247.052 Wahlberechtigten)
AMTLICH_WAHLBETEILIGUNG = 64.9


def pruefen(path=None):
    """Prüfung (Teil von `check`): Einwohnersumme nahe am amtlichen Wert, jede Kennzahl mit Quelle, Lizenz und Stand,
    keine Anteile unter der Mindestgröße. Liefert eine Liste von Befunden (leer = in Ordnung)."""
    path = Path(path or config.EXPORT / "bonn" / OUT)
    if not path.exists():
        print("Kontextdaten: nicht erzeugt – keine Prüfung.")
        return []
    doc = json.loads(path.read_text())
    befunde = []
    ew = doc["bonn"]["einwohner"]
    if abs(ew - AMTLICH_EINWOHNER) / AMTLICH_EINWOHNER > 0.03:
        befunde.append(f"Einwohner Bonn {ew} weicht mehr als 3 % vom amtlichen Wert {AMTLICH_EINWOHNER} ab")
    for k, d in doc["meta"]["kennzahlen"].items():
        q = doc["meta"]["quellen"].get(d["quelle"]) or {}
        if not q.get("lizenz") or not q.get("stand"):
            befunde.append(f"Kennzahl {k}: Quelle {d['quelle']} ohne Lizenz oder Stand")
    wb = doc["bonn"].get("wahlbeteiligung")
    if wb is not None and wb != AMTLICH_WAHLBETEILIGUNG:
        befunde.append(f"Wahlbeteiligung Bonn {wb} % weicht vom amtlichen Wert {AMTLICH_WAHLBETEILIGUNG} % ab")
    for n, v in doc["ortsteile"].items():
        if v.get("wahlbeteiligung") is not None and not 20 <= v["wahlbeteiligung"] <= 95:
            befunde.append(f"{n}: Wahlbeteiligung {v['wahlbeteiligung']} % außerhalb des plausiblen Bereichs")
        if v["einwohner"] < doc["meta"]["mindest_einwohner"] and ANTEILE & set(v):
            befunde.append(f"{n}: Anteile trotz {v['einwohner']} Einwohnern")
    print(f"Kontextdaten: Einwohner Bonn {ew} (amtlich 31.12.2022: {AMTLICH_EINWOHNER}), "
          f"{len(doc['ortsteile'])} Ortsteile; Befunde: {befunde or 'keine'}")
    return befunde
