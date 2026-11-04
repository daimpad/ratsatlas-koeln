"""Geodaten Köln einmalig laden und beschreiben (Phase 1, freigegeben am 04.11.2026).

Aufruf: python3 explore/geodaten.py
1. Je Datensatz die Katalogseite auf offenedaten-koeln.de und deren DCAT-AP-Beschreibung (dcatapde.json) lesen:
   Titel, Stand, Lizenz und Distributionen → explore/ergebnisse/geodaten_katalog.tsv
2. Dateien (zip, csv, xlsx, json, geojson, gpkg) unter sites/default/files laden (Cache explore/_cache/, nicht im Repository)
3. Inhalt beschreiben: Ebenen, Feldnamen, Koordinatensystem, Anzahl, Beispielwerte → explore/ergebnisse/geodaten_felder.tsv
Die geladenen Dateien bleiben außerhalb der Versionskontrolle (siehe .gitignore).
"""
import csv
import html
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from abruf import Abbruch, hole  # noqa: E402

BASIS = "https://www.offenedaten-koeln.de"
ERG = Path(__file__).resolve().parent / "ergebnisse"

# Kennungen der Katalogseiten laut CLAUDE.md 3.2 und Recherchebericht; nicht gefundene werden als solche protokolliert
DATENSAETZE = [
    "stadtteile-koeln",
    "stadtbezirke-koeln",
    "stadtgebiet-k%C3%B6ln",
    "stadtviertel-koeln",
    "statistische-quartiere-koeln",
    "geopackage-raumbezugssystem-koeln",
    "adressen-koeln",
    "koelner-strassenverzeichnis",
    "strassen-koeln",
    "strassenabschnitte-koeln",
    "bebauungsplaene-koeln-bauungsplaene",
    "bebauungspl%C3%A4ne-k%C3%B6ln-aufstellungsbeschl%C3%BCsse",
    "oparl-api-koeln",  # nur Katalogangaben (Lizenz), keine Abrufe der Schnittstelle
]
ENDUNGEN = (".zip", ".csv", ".xlsx", ".json", ".geojson", ".gpkg")

DCAT = "http://www.w3.org/ns/dcat#"
DCT = "http://purl.org/dc/terms/"


def _werte(knoten, schluessel):
    out = []
    for v in knoten.get(schluessel, []):
        out.append(v.get("@value") or v.get("@id") or "")
    return out


def katalog(slug):
    seite = hole(f"{BASIS}/dataset/{slug}", ".html").decode("utf-8", "replace")
    m = re.search(r'href="(/node/\d+/dcatapde\.json)"', seite)
    if not m:
        return [], seite
    graph = json.loads(hole(BASIS + m.group(1), ".json"))
    knoten = {k["@id"]: k for k in graph}
    zeilen = []
    for k in graph:
        if DCAT + "Dataset" not in k.get("@type", []):
            continue
        ds_titel = "; ".join(_werte(k, DCT + "title"))
        ds_stand = "; ".join(_werte(k, DCT + "modified"))
        ds_lizenz = "; ".join(_werte(k, DCT + "license"))
        for ref in _werte(k, DCAT + "distribution"):
            d = knoten.get(ref, {})
            zeilen.append({
                "datensatz": slug,
                "titel": ds_titel,
                "stand_datensatz": ds_stand,
                "lizenz_datensatz": ds_lizenz,
                "distribution": "; ".join(_werte(d, DCT + "title")),
                "format": "; ".join(_werte(d, DCT + "format")),
                "lizenz_distribution": "; ".join(_werte(d, DCT + "license")),
                "namensnennung": "; ".join(_werte(d, "http://dcat-ap.de/def/dcatde/licenseAttributionByText")),
                "stand_distribution": "; ".join(_werte(d, DCT + "modified")),
                "download_url": "; ".join(_werte(d, DCAT + "downloadURL")),
                "access_url": "; ".join(_werte(d, DCAT + "accessURL")),
            })
    return zeilen, seite


def _prj_name(text):
    m = re.search(r'(?:PROJCS|GEOGCS|PROJCRS|GEOGCRS)\["([^"]+)"', text)
    return m.group(1) if m else text[:60]


def beschreibe(url, daten):
    """Liefert Zeilen (ebene, crs, anzahl, felder, beispiel) für eine geladene Datei."""
    import openpyxl
    import shapefile

    out = []
    name = url.rsplit("/", 1)[-1]
    if name.lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(daten))
        namen = z.namelist()
        for shp in [n for n in namen if n.lower().endswith(".shp")]:
            basis = shp[:-4]
            teile = {e: z.read(n) for n in namen for e in (".shp", ".dbf", ".shx", ".prj", ".cpg")
                     if n.lower() == (basis + e).lower()}
            r = shapefile.Reader(shp=io.BytesIO(teile[".shp"]), dbf=io.BytesIO(teile[".dbf"]),
                                 shx=io.BytesIO(teile[".shx"]) if ".shx" in teile else None,
                                 encoding=(teile.get(".cpg", b"utf-8").decode().strip() or "utf-8"))
            felder = [f[0] for f in r.fields[1:]]
            beispiel = dict(zip(felder, r.record(0))) if len(r) else {}
            out.append((shp, _prj_name(teile.get(".prj", b"").decode("latin-1")), len(r), r.shapeTypeName,
                        felder, beispiel))
        for n in namen:
            if n.lower().endswith((".csv", ".xlsx", ".json", ".geojson")):
                out += [(f"{shp_}", *rest) for shp_, *rest in beschreibe(n, z.read(n))]
        if not out:
            out.append((name, "", "", "", namen[:20], {}))
    elif name.lower().endswith(".csv"):
        text = daten.decode("utf-8-sig", "replace")
        trenner = ";" if text.count(";") > text.count(",") else ","
        zeilen = list(csv.reader(io.StringIO(text), delimiter=trenner))
        kopf = zeilen[0] if zeilen else []
        out.append((name, "", len(zeilen) - 1, "Tabelle", kopf, dict(zip(kopf, zeilen[1])) if len(zeilen) > 1 else {}))
    elif name.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(daten), read_only=True)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            kopf = [str(c) for c in next(it, ()) if c is not None]
            erste = next(it, ())
            n = 1 + sum(1 for _ in it) if erste else 0
            out.append((f"{name}:{ws.title}", "", n, "Tabelle", kopf, dict(zip(kopf, erste or ()))))
    elif name.lower().endswith((".json", ".geojson")):
        d = json.loads(daten)
        if isinstance(d, dict) and "features" in d:
            f0 = d["features"][0] if d["features"] else {}
            props = f0.get("properties") or f0.get("attributes") or {}
            crs = json.dumps(d.get("crs") or d.get("spatialReference") or "")[:80]
            geom = (f0.get("geometry") or {}).get("type", "") if isinstance(f0.get("geometry"), dict) else ""
            out.append((name, crs, len(d["features"]), geom, list(props), props))
        else:
            out.append((name, "", "", type(d).__name__, list(d)[:30] if isinstance(d, dict) else [], {}))
    return out


def main():
    ERG.mkdir(parents=True, exist_ok=True)
    kat, felder = [], []
    for slug in DATENSAETZE:
        try:
            zeilen, _ = katalog(slug)
        except Abbruch as e:
            print(f"Katalog {slug}: {e}")
            kat.append({"datensatz": slug, "titel": f"nicht gefunden ({e})"})
            continue
        if not zeilen:
            kat.append({"datensatz": slug, "titel": "keine DCAT-Beschreibung gefunden"})
        kat += zeilen
        if slug == "oparl-api-koeln":
            continue
        for z in zeilen:
            url = html.unescape(z.get("download_url") or z.get("access_url") or "")
            if "/sites/default/files/" not in url or not url.lower().endswith(ENDUNGEN):
                continue
            try:
                daten = hole(url, Path(url).suffix.lower())
                for ebene, crs, n, typ, f, beispiel in beschreibe(url, daten):
                    felder.append({"datensatz": slug, "url": url, "bytes": len(daten), "ebene": ebene, "crs": crs,
                                   "anzahl": n, "typ": typ, "felder": " | ".join(map(str, f)),
                                   "beispiel": json.dumps(beispiel, ensure_ascii=False, default=str)[:300]})
            except Exception as e:  # Beschreibung soll für die übrigen Dateien weiterlaufen
                felder.append({"datensatz": slug, "url": url, "ebene": f"Fehler: {type(e).__name__}: {e}"[:200]})
    for datei, rows in (("geodaten_katalog.tsv", kat), ("geodaten_felder.tsv", felder)):
        spalten = list(dict.fromkeys(k for r in rows for k in r))
        with (ERG / datei).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, spalten, delimiter="\t", lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: str(v).replace("\t", " ").replace("\n", " ") for k, v in r.items()})
    print(f"{len(kat)} Katalogzeilen, {len(felder)} beschriebene Ebenen → {ERG}")


if __name__ == "__main__":
    main()
