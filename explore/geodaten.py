"""Geodaten Köln einmalig laden und beschreiben (Phase 1, freigegeben am 04.11.2026).

Aufruf: RATSATLAS_MAX_ANFRAGEN=<N> python3 explore/geodaten.py   (N = freigegebene Obergrenze; ohne sie kein Abruf)
1. Je Datensatz die Katalogseite auf offenedaten-koeln.de und deren DCAT-AP-Beschreibung (dcatapde.json) lesen:
   Titel, Stand, Lizenz und Distributionen → explore/ergebnisse/geodaten_katalog.tsv
2. Dateien (zip, csv, xlsx, json, geojson, gpkg) unter sites/default/files laden (Cache explore/_cache/, nicht im Repository)
3. Inhalt beschreiben: Ebenen, Feldnamen, Koordinatensystem, Anzahl, Beispielwerte → explore/ergebnisse/geodaten_felder.tsv
Die geladenen Dateien bleiben außerhalb der Versionskontrolle (siehe .gitignore).
Abruf über explore/abruf.py mit denselben Mindestwerten wie die OParl-Messung (vorgaben(), vor der ersten Anfrage
erzwungen): mindestens 2 s Abstand (RATSATLAS_ABSTAND, Vorgabe 2), keine Wiederholung nach 429/5xx
(RATSATLAS_WIEDERHOLUNGEN, Vorgabe 0) und eine Obergrenze der Anfragen ans Netz (RATSATLAS_MAX_ANFRAGEN, Pflicht; die
Zahl wird vor dem Lauf festgelegt und freigegeben); fehlende oder lockerere Werte brechen vor der ersten Anfrage ab
(Rückgabewert 1).
Weiterleitungen (HTTP 3xx) werden nicht verfolgt. Eine Weiterleitung oder ein anderer HTTP-Fehler (z. B. 404) bricht
nur den Abruf dieses Katalogs bzw. dieser Datei ab: Er wird mit der Meldung (bei einer Weiterleitung mit Ziel) in
geodaten_katalog.tsv bzw. geodaten_felder.tsv vermerkt, das Ziel steht in _cache/abrufe.tsv (Spalte ziel); die übrigen
Datensätze laufen weiter. Nach einem Abbruch der Art sperre (mögliche Sperre, auch abgeschnittene oder unlesbare
Antwort und HTTP 502/504), server (429/5xx), proxy (Ablehnung durch den Proxy der Arbeitsumgebung), obergrenze,
langsam (RATSATLAS_MAX_DAUER), parallel (ein anderer Abrufprozess läuft) oder http mit 401, 403 oder 429 endet der ganze
Lauf sofort (Rückgabewert 2): offenedaten-koeln.de liegt im selben Netz wie die OParl-API
(ergebnisse/sessionnet_befunde.tsv), und nach diesen Signalen ruhen laut explore/STUFEN.md alle Abrufe. Die
Ergebnisdateien bleiben dann unverändert. Der Lauf vom 04.11.2026 entstand noch mit urllib.request.urlopen, das
Weiterleitungen folgt (Commit 1649598); seit 07.11.2026 (Commit 092446c) gilt die Regel.
"""
import csv
import html
import io
import json
import math
import os
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import abruf  # noqa: E402
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

# Mindestwerte wie für die OParl-Messung (explore/oparl_messung.py, STRENG_ABSTAND)
STRENG_ABSTAND = 2.0
# Abbruchsarten, nach denen der ganze Lauf endet (keine weitere Anfrage an die Stadt) …
ENDE = ("sperre", "server", "proxy", "obergrenze", "langsam", "parallel")
# … ebenso HTTP-Antworten der Art `http` mit diesen Codes (STUFEN.md: nach 403 oder 429 ruhen alle Abrufe)
ENDE_HTTP = (401, 403, 429)


class _Ende(Exception):
    """Ein Abbruch aus ENDE oder ENDE_HTTP: Der ganze Lauf endet."""


def vorgaben(umgebung=None):
    """Mindestwerte für den Abruf der Geodaten; liefert (werte, fehler). Fehlende Werte werden gesetzt (Abstand 2 s,
    keine Wiederholung), lockerere abgelehnt; die Obergrenze RATSATLAS_MAX_ANFRAGEN ist Pflicht."""
    env = os.environ if umgebung is None else umgebung
    fehler = []
    try:
        wiederholungen = int(env.get("RATSATLAS_WIEDERHOLUNGEN") or "0")
        abstand = float(env.get("RATSATLAS_ABSTAND") or STRENG_ABSTAND)
        max_anfragen = int(env.get("RATSATLAS_MAX_ANFRAGEN") or "0")
    except ValueError as e:
        return {}, [f"unlesbarer Wert ({e})"]
    if wiederholungen != 0:
        fehler.append("RATSATLAS_WIEDERHOLUNGEN muss 0 sein (keine Wiederholung nach 429/5xx)")
    if not (math.isfinite(abstand) and abstand >= STRENG_ABSTAND):
        fehler.append(f"RATSATLAS_ABSTAND muss mindestens {STRENG_ABSTAND:g} s sein (Abstand zwischen zwei Anfragen)")
    if max_anfragen <= 0:
        fehler.append("RATSATLAS_MAX_ANFRAGEN fehlt (Obergrenze der Anfragen ans Netz für diesen Lauf, vor dem Lauf "
                      "festlegen und freigeben lassen)")
    return {"wiederholungen": wiederholungen, "abstand": abstand, "max_anfragen": max_anfragen}, fehler


def _pruefe_ende(e):
    """Ein Abbruch aus ENDE oder der Art http mit einem Code aus ENDE_HTTP beendet den ganzen Lauf; alle übrigen
    betreffen nur den Katalog bzw. die Datei."""
    if isinstance(e, Abbruch) and (e.art in ENDE or (e.art == "http" and e.code in ENDE_HTTP)):
        raise _Ende(e) from e


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
    werte, fehler = vorgaben()
    if fehler:
        print("Abbruch vor der ersten Anfrage: " + "; ".join(fehler), file=sys.stderr)
        return 1
    abruf.ABSTAND, abruf.WIEDERHOLUNGEN = werte["abstand"], werte["wiederholungen"]
    abruf.MAX_ANFRAGEN = werte["max_anfragen"]
    try:
        kat, felder = _laden()
    except _Ende as e:
        ursache = e.__cause__
        print(f"Abbruch ({ursache.art}): {ursache}\nDer ganze Lauf endet ohne weitere Anfrage; die Ergebnisdateien "
              f"bleiben unverändert. Stoppen und berichten.", file=sys.stderr)
        return 2
    ERG.mkdir(parents=True, exist_ok=True)
    for datei, rows in (("geodaten_katalog.tsv", kat), ("geodaten_felder.tsv", felder)):
        spalten = list(dict.fromkeys(k for r in rows for k in r))
        with (ERG / datei).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, spalten, delimiter="\t", lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: str(v).replace("\t", " ").replace("\n", " ") for k, v in r.items()})
    print(f"{len(kat)} Katalogzeilen, {len(felder)} beschriebene Ebenen → {ERG}")
    return 0


def _laden():
    """Kataloge und Dateien; liefert (Katalogzeilen, Feldzeilen). Ein Abbruch aus ENDE kommt als _Ende."""
    kat, felder = [], []
    for slug in DATENSAETZE:
        try:
            zeilen, _ = katalog(slug)
        except Abbruch as e:
            _pruefe_ende(e)
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
            except Exception as e:  # Beschreibung soll für die übrigen Dateien weiterlaufen (außer nach ENDE)
                _pruefe_ende(e)
                felder.append({"datensatz": slug, "url": url, "ebene": f"Fehler: {type(e).__name__}: {e}"[:200]})
    return kat, felder


if __name__ == "__main__":
    sys.exit(main())
