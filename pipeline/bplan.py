"""Bebauungspläne Köln aus der OGC-API „Bauleitplanung in NRW (INSPIRE)“ von IT.NRW (Schritt `bplan-koeln`).

Quelle: https://ogc-api.nrw.de/inspire-lu-bplan/v1 (Ministerium für Heimat, Kommunales, Bau und Digitalisierung NRW /
IT.NRW, Datengrundlage Stadt Köln), Lizenz laut Schnittstelle dl-de/by 2.0 (Metadaten: „keine Bedingungen“; geführt
wird die strengere Angabe). Kein Server der Stadt: Abrufe sind ohne RATSATLAS_STADT_INFORMIERT erlaubt
(explore/ergebnisse/bplan_quellen.tsv, Entscheidung 05.11.2026). Enthalten sind nur rechtsverbindliche Pläne, keine
Aufstellungsbeschlüsse.

Plannummer: In der Schnittstelle `NNNNN.NN.NNN.NN` (z. B. `63429.06.000.00`), in Vorlagentiteln „63429/06“. Belegt
ist diese Entsprechung an einem Plan (Hermeskeiler Platz); was die hinteren Stellen bedeuten, ist offen. Der Name im
Datensatz ist deshalb die Kurzform; weicht der hintere Teil von `.000.00` ab, steht die volle Nummer in Klammern
dahinter („63429/06 (63429.06.001.00)“). plans.py ordnet Titel über die Kurzform zu; mehrere Pläne mit derselben
Kurzform gelten als mehrdeutig.
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone

from shapely.geometry import mapping, shape

from . import config

ITEMS = ("https://ogc-api.nrw.de/inspire-lu-bplan/v1/collections/spatialplan/items"
         "?f=json&gkz=05315000&limit=500")
UA = "ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln)"
ABSTAND = 2.0
TOLERANZ_GRAD = 0.000005   # etwa 0,5 m; Darstellung und Verschneidung mit Stadtteilen
NR = re.compile(r"(\d{4,6})\.(\d{2})\.(\d{3})\.(\d{2})(?:\.([A-Za-z]\w{0,3}))?(?![\w.])")


def name(nr):
    """„63429.06.000.00“ → „63429/06“; „67457.03.001.00“ → „67457/03 (67457.03.001.00)“; ältere vierstellige Nummern
    („5843.03.000.00“) und Teilpläne („….T1“, „….A“) ebenso; sonst None."""
    m = NR.search(nr or "")
    if not m:
        return None
    kurz = f"{m.group(1)}/{m.group(2)}"
    return kurz if m.group(3) == "000" and m.group(4) == "00" and not m.group(5) else f"{kurz} ({m.group(0)})"


def _hole(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json, application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _gerundet(geom):
    g = shape(geom).simplify(TOLERANZ_GRAD, preserve_topology=True)
    return json.loads(json.dumps(mapping(g)), parse_float=lambda x: round(float(x), 6))


def write():
    url, seiten, feats, ohne_nr, gesehen = ITEMS, 0, [], [], set()
    while url:
        if url in gesehen or seiten > 50:
            raise RuntimeError(f"Paginierung bricht nicht ab: {url}")
        gesehen.add(url)
        if seiten:
            time.sleep(ABSTAND)
        d = _hole(url)
        seiten += 1
        for f in d.get("features") or []:
            p = f.get("properties") or {}
            nr = (p.get("nr") or "").lstrip("_'").strip()
            n = name(nr)
            if not n or not f.get("geometry"):
                ohne_nr.append(f.get("id"))
                continue
            feats.append({"type": "Feature", "geometry": _gerundet(f["geometry"]), "properties": {
                "name": n, "nr": nr, "titel": p.get("officialTitle"), "inkraft_seit": p.get("validFrom"),
                "verfahrensstand": p.get("processStepGeneral.title"), "planart": p.get("planart.title"),
                "plan": p.get("officialDocument"), "inspire_id": f.get("id")}})
        url = next((l["href"] for l in d.get("links") or [] if l.get("rel") == "next"), None)
    alt = json.loads(config.BPLAN.read_text())["features"] if config.BPLAN.exists() else []
    if len(feats) < config_min(len(alt)):
        raise RuntimeError(f"nur {len(feats)} Pläne statt bisher {len(alt)}; Stand bleibt")
    feats.sort(key=lambda f: (f["properties"]["name"], f["properties"]["nr"]))
    config.BPLAN.parent.mkdir(parents=True, exist_ok=True)
    config.BPLAN.write_text(json.dumps({
        "type": "FeatureCollection",
        "meta": {"source": ITEMS, "license": config.SOURCES[config.QUELLE_BPLAN]["license"],
                 "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "crs": "WGS84 (CRS84)", "vereinfacht_m": 0.5, "ohne_plannummer": len(ohne_nr),
                 "note": "nur rechtsverbindliche Pläne; Name = Plannummer in der Schreibweise der Vorlagentitel"},
        "features": feats}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(feats)} Bebauungspläne aus {seiten} Seiten → {config.BPLAN} ({len(ohne_nr)} ohne Plannummer)")


def config_min(alt):
    """Ein neuer Stand ersetzt den alten nur mit mindestens 90 % der bisherigen Pläne (wie beim OParl-Abruf)."""
    return int(0.9 * alt)
