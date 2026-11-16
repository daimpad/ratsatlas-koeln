"""Archiv der Baustellen in Köln (Zusatzthema „baustellen“, abgeschaltet; vorbereitet am 16.11.2026 ohne Abruf).

Quelle (Datensatzseite geprüft am 16.11.2026): „Baustellen Köln“, https://www.offenedaten-koeln.de/dataset/baustellen-koeln,
Lizenz dl-de/zero 2.0, Amt für Verkehrsmanagement der Stadt Köln; WFS
https://geoportal.stadt-koeln.de/wss/service/baustellen_wfs/guest (dasselbe Geoportal wie pipeline/ebenen.py). Inhalt
laut Datensatzseite: Punkte verkehrsrechtlicher Genehmigungen im öffentlichen Straßenraum, ohne Autobahnen; der
Genehmigungszeitraum ist nicht zwingend der Ausführungszeitraum. Eine Baustelle ist kein Beleg für die Umsetzung eines
Beschlusses.

Ungeprüft, weil bis zur Freigabe keine Anfrage gestellt wird: Objektart (TYPENAME), Feldnamen, Datumsformat und das
Koordinatensystem der Antwort. Deshalb:
- `WFS_TYP` und `ZUORDNUNG` sind die einzige Stelle für Objektart und Feldnamen; None heißt „noch nicht festgelegt“.
- `schema_pruefen` prüft jede Antwort vor dem Schreiben (FeatureCollection, Zahl der Objekte, Punkte, jede
  zugeordnete Eigenschaft in jedem Objekt, Kennung eindeutig, Datum lesbar, Koordinaten in Köln). Passt etwas nicht,
  endet der Lauf mit `dienste.Schemafehler`; die Meldung nennt die gefundenen Eigenschaftsnamen (keine Werte), und es
  wird nichts geschrieben.

Ein Lauf (`python -m pipeline baustellen`; nur mit Freigabe, siehe pipeline/dienste.py) stellt höchstens zwei
Anfragen: ohne festgelegte Objektart zuerst GetCapabilities (genau eine angebotene Objektart wird genommen, sonst
Schemafehler mit den Namen), dann GetFeature als GeoJSON. Erst nach bestandener Prüfung schreibt er in
`config.BAUSTELLEN_ARCHIV` (Branch `archiv`, Workflow `.github/workflows-inaktiv/baustellen.yml`):
- snapshots/JJJJ/MM/TT/baustellen.json – Momentaufnahme, nur wenn sich der Inhalt geändert hat
- baustellen.json – Zustand je Baustelle: erstes und letztes Auftreten, aktuelle Angaben, Änderungen, entfallen
- protokoll.tsv – Ereignisse je Lauf: neu, geändert (Feld, alt, neu), entfallen, wieder_da
- anfragen.tsv – Anfragen je Lauf (Zeit, Adresse, Status, Bytes, Sekunden)
- STAND.json – letzter Lauf (Zeitpunkt, Objektart, Anfragen, Anzahl, Quelle, Lizenz)

Gespeichert werden nur die zugeordneten Felder: Kennung, Bezeichnung, Art, Straße (ohne Hausnummer), Beginn und Ende
der Genehmigung (ISO-Datum), der Punkt (gerundet auf 1e-5 Grad) und Stadtteil und Stadtbezirk aus data/geo
(Punkt in Fläche). Keine Antragsteller, Firmen, Personen oder Kontaktdaten; ob die Punkte auch Genehmigungen für
Privatpersonen zeigen (etwa an Wohnhäusern), ist ungeprüft und vor dem Einschalten zu klären (TECHNIK.md)."""
import functools
import hashlib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, dienste

THEMA = "baustellen"
DATENSATZ = "https://www.offenedaten-koeln.de/dataset/baustellen-koeln"
WFS = "https://geoportal.stadt-koeln.de/wss/service/baustellen_wfs/guest"
TITEL = "Baustellen Köln"
HINWEISE = [
    "Punkte verkehrsrechtlicher Genehmigungen im öffentlichen Straßenraum (ohne Autobahnen), Amt für "
    "Verkehrsmanagement der Stadt Köln.",
    "Der Genehmigungszeitraum ist nicht zwingend der Ausführungszeitraum.",
    "Eine Baustelle ist kein Beleg für die Umsetzung eines Beschlusses.",
]
MAX_ANFRAGEN = 2   # GetCapabilities (nur ohne festgelegte Objektart) und GetFeature

# --- Einzige Stelle für Objektart und Feldnamen (UNGEPRÜFT, Stand 16.11.2026: nur die Datensatzseite gesichtet) -------
# Objektart des WFS (TYPENAME, etwa „ms:…“ wie in pipeline/ebenen.py); None: aus GetCapabilities, wenn der Dienst genau
# eine Objektart anbietet. Nach der ersten Sichtung hier eintragen (dann entfällt die Anfrage GetCapabilities).
WFS_TYP = None
# interner Name → Eigenschaft im WFS (Feldname laut Antwort); None: noch nicht festgelegt. Nur Felder ohne Personen-
# oder Kontaktbezug zuordnen (keine Antragsteller, Firmen, Telefonnummern). Ein None in PFLICHT hält den Lauf vor dem
# Schreiben an (Schemafehler mit den gefundenen Eigenschaftsnamen).
ZUORDNUNG = {
    "id": None,            # eindeutige Kennung der Genehmigung oder Baustelle
    "bezeichnung": None,   # kurze Bezeichnung der Maßnahme (ohne Adresse und Namen)
    "art": None,           # Art der Maßnahme
    "strasse": None,       # Straße; eine Hausnummer am Ende entfällt (ohne_hausnummer)
    "von": None,           # Beginn der Genehmigung
    "bis": None,           # Ende der Genehmigung
}
PFLICHT = ("id", "von", "bis")
# Änderungen dieser Felder werden protokolliert
VERFOLGT = ("von", "bis", "bezeichnung", "art", "strasse")
FELDER = ("bezeichnung", "art", "strasse", "von", "bis", "lon", "lat", "stadtteil", "stadtbezirk")
LOG_KOPF = ["datum", "baustelle_id", "ereignis", "feld", "alt", "neu"]
# Rahmen für Koordinaten in Köln (Grad; config.STADT_BBOX mit 0,05 Grad Rand): darüber hinaus Schemafehler
RAND = 0.05
_TYPNAME = re.compile(r"[A-Za-z_][\w.\-]*(?::[A-Za-z_][\w.\-]*)?")


def capabilities_url(wfs=None):
    return f"{wfs or WFS}?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetCapabilities"


def getfeature_url(typ, wfs=None):
    """GetFeature als GeoJSON (Format wie bei den anderen WFS des Geoportals in pipeline/ebenen.py; für diesen Dienst
    ungeprüft)."""
    return (f"{wfs or WFS}?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature&TYPENAME={urllib.parse.quote(typ, safe=':')}"
            "&SRSNAME=EPSG:4326&OUTPUTFORMAT=" + urllib.parse.quote("application/json; subtype=geojson"))


def objektarten(daten):
    """Namen der Objektarten (FeatureType/Name, ohne Rücksicht auf Namensräume) aus einer GetCapabilities-Antwort.
    Antworten mit DOCTYPE oder ENTITY werden nicht gelesen (Schutz vor Entitäten in fremdem XML)."""
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", daten, re.I):
        raise dienste.Schemafehler("GetCapabilities enthält DOCTYPE oder ENTITY; nicht gelesen")
    try:
        wurzel = ET.fromstring(daten)
    except ET.ParseError as e:
        raise dienste.Abbruch(f"GetCapabilities ist kein lesbares XML ({e})", "unlesbar") from e
    namen = []
    for el in wurzel.iter():
        if el.tag.rsplit("}", 1)[-1] == "FeatureType":
            for kind in el:
                if kind.tag.rsplit("}", 1)[-1] == "Name" and (kind.text or "").strip():
                    namen.append(kind.text.strip())
                    break
    return namen


def objektart_waehlen(namen, typ=None):
    """Festgelegte Objektart (muss angeboten sein) oder die einzige angebotene; sonst Schemafehler."""
    gezeigt = ", ".join(dienste.text(n) for n in namen[:20]) or "keine"
    if typ is not None:
        if typ not in namen:
            raise dienste.Schemafehler(f"Objektart {typ!r} (WFS_TYP) wird nicht angeboten; angeboten: {gezeigt}")
        return typ
    if len(namen) != 1:
        raise dienste.Schemafehler(f"WFS_TYP nicht festgelegt und {len(namen)} Objektarten angeboten ({gezeigt}); "
                                   "in pipeline/baustellen.py eintragen")
    return namen[0]


# Zahl am Ende (Hausnummer, auch Bereiche wie „12-14a“ oder „7/9“), nicht nach einer Straßenklasse wie „B 55“
_HAUSNUMMER = re.compile(r"(?<!\b[ABLK])\s+\d+\s*[a-zA-Z]?(?:\s*[-–/]\s*\d+\s*[a-zA-Z]?)*\s*$")


def ohne_hausnummer(text):
    """Nur Straßenebene: eine Zahl am Ende (Hausnummer) entfällt; „Bundesstraße B 55“ bleibt."""
    t = _HAUSNUMMER.sub("", str(text or "").strip())
    return t or None


def datum(wert):
    """ISO-Datum aus einem Wert der Quelle: „JJJJ-MM-TT…“ oder „TT.MM.JJJJ…“; None bei leerem Wert; sonst ValueError."""
    if wert is None or str(wert).strip() == "":
        return None
    s = str(wert).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:$|[T ])", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:$|\s)", s)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    raise ValueError(f"Datum nicht lesbar: {dienste.text(s, 40)}")


@functools.lru_cache(maxsize=1)
def _nach_wgs84():
    from pyproj import Transformer
    return Transformer.from_crs(25832, 4326, always_xy=True)


def _punkt(geom):
    """(lon, lat) in WGS84 oder None ohne Geometrie; die WFS des Geoportals liefern trotz SRSNAME=EPSG:4326 zum Teil
    EPSG 25832 (pipeline/ebenen.py): an der Größe erkennen und umrechnen."""
    if not geom:
        return None
    x, y = (float(v) for v in geom["coordinates"][:2])
    if abs(x) > 1000:
        x, y = _nach_wgs84().transform(x, y)
    return x, y


def schema_pruefen(doc, zuordnung=None):
    """Prüft eine GetFeature-Antwort gegen die Zuordnung; Schemafehler mit allen Befunden (Namen, keine Werte)."""
    zuordnung = ZUORDNUNG if zuordnung is None else zuordnung
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
        raise dienste.Schemafehler("Antwort ist keine GeoJSON-FeatureCollection")
    feats = doc["features"]
    if any(not isinstance(f, dict) or not isinstance(f.get("properties") or {}, dict)
           or not isinstance(f.get("geometry") or {}, dict) for f in feats):
        raise dienste.Schemafehler("Objekte ohne lesbare Eigenschaften oder Geometrie (kein GeoJSON-Feature)")
    erwartet = doc.get("numberMatched", doc.get("totalFeatures"))
    if isinstance(erwartet, int) and erwartet != len(feats):
        raise dienste.Schemafehler(f"unvollständige Antwort: {erwartet} Objekte laut Quelle, {len(feats)} erhalten")
    if not feats:
        raise dienste.Abbruch("Antwort ohne Objekte (vorige Stände bleiben)", "leer")
    befunde, namen = [], {}
    for f in feats:
        for k in f.get("properties") or {}:
            namen[k] = namen.get(k, 0) + 1
    offen = [k for k in PFLICHT if not zuordnung.get(k)]
    if offen:
        befunde.append(f"nicht festgelegt (ZUORDNUNG, ungeprüft): {', '.join(offen)}")
    for intern, quelle in zuordnung.items():
        if quelle and namen.get(quelle, 0) < len(feats):
            befunde.append(f"Eigenschaft {quelle!r} für {intern} fehlt in {len(feats) - namen.get(quelle, 0)} von "
                           f"{len(feats)} Objekten")
    arten = {dienste.text((f.get("geometry") or {}).get("type")) for f in feats} - {"None"}
    if arten - {"Point"}:
        befunde.append(f"Geometrie {', '.join(sorted(arten))} statt Point")
    if not befunde:
        ids = [str((f.get("properties") or {}).get(zuordnung["id"]) or "").strip() for f in feats]
        if "" in ids:
            befunde.append(f"Kennung leer in {ids.count('')} Objekten")
        if len(set(ids)) != len(ids):
            befunde.append(f"Kennung nicht eindeutig ({len(ids) - len(set(ids))} doppelt)")
        for k in ("von", "bis"):
            schlecht = 0
            for f in feats:
                try:
                    datum((f.get("properties") or {}).get(zuordnung[k]))
                except ValueError:
                    schlecht += 1
            if schlecht:
                befunde.append(f"Datum in {zuordnung[k]!r} ({k}) bei {schlecht} Objekten nicht lesbar")
        s, w, n, o = config.STADT_BBOX
        ausserhalb = 0
        for f in feats:
            try:
                p = _punkt(f.get("geometry"))
            except (KeyError, TypeError, ValueError, IndexError):
                ausserhalb += 1
                continue
            if p and not (w - RAND <= p[0] <= o + RAND and s - RAND <= p[1] <= n + RAND):
                ausserhalb += 1
        if ausserhalb:
            befunde.append(f"{ausserhalb} Punkte unlesbar oder außerhalb Kölns (Koordinatensystem prüfen)")
    if befunde:
        gezeigt = ", ".join(dienste.text(k, 40) for k in sorted(namen)[:50]) or "keine"
        raise dienste.Schemafehler(f"Baustellen: Antwort passt nicht zur Zuordnung in pipeline/baustellen.py: "
                                   f"{'; '.join(befunde)}. Eigenschaften in der Antwort ({len(feats)} Objekte): "
                                   f"{gezeigt}.")


def normalisieren(doc, ortsteile, zuordnung=None):
    """Nach bestandener Prüfung: {Kennung: Angaben} mit genau FELDER, nach Kennung sortiert."""
    zuordnung = ZUORDNUNG if zuordnung is None else zuordnung

    def wert(p, k):
        quelle = zuordnung.get(k)
        return (str(p[quelle]).strip() or None) if quelle and p.get(quelle) is not None else None
    out = {}
    for f in doc["features"]:
        p = f.get("properties") or {}
        punkt = _punkt(f.get("geometry"))
        lon, lat = (round(punkt[0], 5), round(punkt[1], 5)) if punkt else (None, None)
        st = ortsteile.locate(lon, lat) if punkt else None
        out[str(p[zuordnung["id"]]).strip()] = {
            "bezeichnung": ohne_hausnummer(wert(p, "bezeichnung")), "art": wert(p, "art"),
            "strasse": ohne_hausnummer(wert(p, "strasse")),
            "von": datum(p.get(zuordnung["von"])), "bis": datum(p.get(zuordnung["bis"])), "lon": lon, "lat": lat,
            "stadtteil": st["ortsteil_bez"] if st else "", "stadtbezirk": st["bezirk_bez"] if st else ""}
    return dict(sorted(out.items(), key=lambda kv: (0, int(kv[0]), "") if kv[0].isdigit() else (1, 0, kv[0])))


def update(state, items, day):
    """Zustand fortschreiben (vollständiger Stand der Quelle); gibt Protokollzeilen zurück."""
    rows = []
    for bid, props in items.items():
        cur = state.get(bid)
        if cur is None:
            state[bid] = {"id": bid, "first_seen": day, "last_seen": day, "aktiv": True, "angaben": props,
                          "aenderungen": []}
            rows.append([day, bid, "neu", "", "", ""])
            continue
        for k in VERFOLGT:
            if cur["angaben"].get(k) != props.get(k):
                cur["aenderungen"].append({"datum": day, "feld": k, "alt": cur["angaben"].get(k), "neu": props.get(k)})
                rows.append([day, bid, "geaendert", k, cur["angaben"].get(k) or "", props.get(k) or ""])
        if not cur.get("aktiv"):
            rows.append([day, bid, "wieder_da", "", "", ""])
            cur.pop("entfallen", None)
        cur.update(last_seen=day, aktiv=True, angaben=props)
    for bid, cur in state.items():
        if cur.get("aktiv") and bid not in items:
            cur["aktiv"] = False
            cur["entfallen"] = day
            rows.append([day, bid, "entfallen", "", "", ""])
    return rows


def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _schreiben(pfad, text):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(pfad)


def archive(base=None, now=None, ortsteile=None):
    """Ein Lauf ins Archivverzeichnis (Standard: config.BAUSTELLEN_ARCHIV). Ohne Freigabe: übersprungen, nichts
    gesendet, nichts geschrieben. Schemafehler und Abbruch: nichts geschrieben, Exit-Code ungleich 0."""
    from .geo import Ortsteile
    base = Path(base or config.BAUSTELLEN_ARCHIV)
    now = now or datetime.now(timezone.utc)
    day, stamp = now.date().isoformat(), now.isoformat(timespec="seconds")
    lauf = dienste.Lauf(THEMA, MAX_ANFRAGEN)
    try:
        with lauf:
            typ = WFS_TYP
            if typ is None:   # eine Anfrage mehr, bis die Objektart eingetragen ist
                typ = objektart_waehlen(objektarten(lauf.holen(capabilities_url(), "application/xml")))
            if not _TYPNAME.fullmatch(typ):
                raise dienste.Schemafehler(f"Objektart {dienste.text(typ)!r} ist kein gültiger Name")
            url = getfeature_url(typ)
            doc = lauf.json(url)
            schema_pruefen(doc)
            items = normalisieren(doc, ortsteile or Ortsteile())
    except dienste.NichtGesendet as e:   # vor der ersten Anfrage oder (Zeitfenster) vor GetFeature
        print(f"Baustellen: übersprungen ({e}); {lauf.anfragen} Anfragen gesendet, nichts geschrieben.")
        return None
    except (dienste.Schemafehler, dienste.Abbruch) as e:
        raise SystemExit(f"Baustellen: {e} Nichts geschrieben.") from e
    state_file, log_file, stand_file = base / "baustellen.json", base / "protokoll.tsv", base / "STAND.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    stand = json.loads(stand_file.read_text(encoding="utf-8")) if stand_file.exists() else {}
    snap = json.dumps({"meta": {"quelle": url, "datensatz": DATENSATZ, "lizenz": config.BAUSTELLEN_LICENSE,
                                "objektart": typ}, "baustellen": items},
                      ensure_ascii=False, indent=1, sort_keys=True)
    if stand.get("inhalt") != hash_text(snap):   # nur geänderte Stände ablegen
        _schreiben(base / "snapshots" / now.strftime("%Y/%m/%d") / "baustellen.json", snap + "\n")
    rows = update(state, items, day)
    _schreiben(state_file, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    stand = {"abruf": stamp, "quelle": url, "datensatz": DATENSATZ, "lizenz": config.BAUSTELLEN_LICENSE,
             "objektart": typ, "anfragen": lauf.anfragen, "anzahl": len(items), "inhalt": hash_text(snap),
             "ohne_stadtteil": sum(1 for a in items.values() if not a["stadtteil"]),
             "archiv_beginn": min((v["first_seen"] for v in state.values()), default=day)}
    _schreiben(stand_file, json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    if rows:
        neu = not log_file.exists()
        with log_file.open("a", encoding="utf-8") as fh:
            if neu:
                fh.write("\t".join(LOG_KOPF) + "\n")
            fh.writelines("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n" for r in rows)
    dienste.protokoll_schreiben(base / "anfragen.tsv", lauf)
    aktiv = sum(1 for v in state.values() if v.get("aktiv"))
    print(f"Baustellen: {aktiv} aktiv, {len(state)} seit Archivbeginn, {len(rows)} Ereignisse, {lauf.anfragen} "
          f"Anfragen → {base}")
    return rows


def pruefen_archiv(base=None):
    """Befunde zum Archiv (Datenschutz): je Baustelle nur die Felder in FELDER, Straße und Bezeichnung ohne
    Hausnummer am Ende."""
    pfad = Path(base or config.BAUSTELLEN_ARCHIV) / "baustellen.json"
    if not pfad.exists():
        return []
    befunde = []
    for bid, v in json.loads(pfad.read_text(encoding="utf-8")).items():
        a = v.get("angaben") or {}
        if set(a) - set(FELDER):
            befunde.append(f"Baustelle {bid}: unerwartete Felder {sorted(set(a) - set(FELDER))}")
        for k in ("strasse", "bezeichnung"):
            if a.get(k) and ohne_hausnummer(a[k]) != a[k]:
                befunde.append(f"Baustelle {bid}: {k} mit Hausnummer")
    return befunde
