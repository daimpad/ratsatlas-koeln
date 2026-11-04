"""Archiv der Baustellen der Stadt Bonn (Phase 2, ohne Anzeige auf der Seite).

Die Schnittstellen liefern nur den aktuellen Stand, beendete Baustellen fallen heraus, und der Dienst antwortet
zeitweise mit HTTP 400 und leerem Inhalt (Phase 0, baustellen/phase0/BERICHT.md). Ein täglicher Abruf hält
deshalb fest:
- snapshots/JJJJ/MM/TT/thema_NNNNN.json – Momentaufnahme je Feed, nur wenn sich der Inhalt geändert hat
- baustellen.json – Zustand je Baustelle: Feeds, erstes und letztes Auftreten, aktuelle Angaben, Änderungen
- protokoll.tsv – Ereignisse je Abruf: neu, geändert (Feld, alt, neu), entfallen, Abruf fehlgeschlagen
- STAND.json – letzter Abruf je Feed (Zeitpunkt, Versuche, Anzahl, Erfolg)

Quelle: Stadt Bonn, stadtplan.bonn.de (Lizenz CC0 laut Auftraggeber, 19.10.2026). Termine sind laut Quelle
unverbindlich; erfasst sind nur Baustellen mit nennenswertem Einfluss auf den Verkehr. Eine Baustelle ist kein
Beleg für die Umsetzung eines Beschlusses."""
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config

FEEDS = {14403: "tagesaktuell", 14698: "geplant_1_jahr", 14755: "geplant_30_tage"}
URL = "https://stadtplan.bonn.de/geojson?Thema={}"
FIELDS = ("bezeichnung", "stadtbezirk_bez", "adresse", "von", "bis", "traeger", "massnahme", "sperrung")
TRACKED = ("von", "bis", "sperrung", "massnahme", "traeger", "adresse", "bezeichnung")  # Änderungen protokollieren
LOG_HEAD = ["datum", "baustelle_id", "ereignis", "feld", "alt", "neu", "feeds"]


def fetch(thema, tries=10, pause=3, opener=None):
    """Feed abrufen und prüfen (FeatureCollection, Anzahl wie numberMatched). Gibt (Features, Versuche) zurück;
    wirft nach erfolglosen Versuchen RuntimeError."""
    opener = opener or (lambda url: json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT}), timeout=60)))
    last = None
    for i in range(1, tries + 1):
        try:
            data = opener(URL.format(thema))
            feats = data.get("features") if isinstance(data, dict) else None
            expected = data.get("numberMatched", data.get("totalFeatures")) if isinstance(data, dict) else None
            if data.get("type") == "FeatureCollection" and feats is not None and (expected is None or expected == len(feats)):
                return feats, i
            last = f"unvollständige Antwort ({expected} erwartet, {len(feats or [])} erhalten)"
        except Exception as err:  # HTTP 400 mit „{}“ kommt sporadisch
            last = str(err)
        if i < tries:
            time.sleep(pause)
    raise RuntimeError(f"Thema {thema}: {tries} Versuche ohne gültige Antwort ({last})")


def normalize(features):
    """Feature-Liste je Baustelle (ID als Text), Koordinaten gerundet, nach ID sortiert."""
    out = {}
    for f in features:
        p = f.get("properties") or {}
        if p.get("baustelle_id") is None:
            continue
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") if geom.get("type") == "Point" else None
        out[str(p["baustelle_id"])] = {
            **{k: p.get(k) for k in FIELDS},
            "lon": round(coords[0], 6) if coords else None, "lat": round(coords[1], 6) if coords else None}
    return dict(sorted(out.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0]))


def update(state, results, day):
    """Zustand fortschreiben. results: {Feedname: {id: Angaben}} nur für erfolgreich abgerufene Feeds. Fehlt ein
    Feed (Abruf fehlgeschlagen), wird keine Baustelle als entfallen gewertet. Gibt Protokollzeilen zurück."""
    rows = []
    complete = set(results) == set(FEEDS.values())
    seen = {}
    for feed, items in results.items():
        for bid, props in items.items():
            seen.setdefault(bid, (props, set()))[1].add(feed)
    for bid, (props, feeds) in seen.items():
        cur = state.get(bid)
        if cur is None:
            state[bid] = {"id": bid, "first_seen": day, "last_seen": day, "feeds": sorted(feeds), "aktiv": True,
                          "angaben": props, "aenderungen": []}
            rows.append([day, bid, "neu", "", "", "", ",".join(sorted(feeds))])
            continue
        for k in TRACKED:
            if cur["angaben"].get(k) != props.get(k):
                cur["aenderungen"].append({"datum": day, "feld": k, "alt": cur["angaben"].get(k), "neu": props.get(k)})
                rows.append([day, bid, "geaendert", k, cur["angaben"].get(k) or "", props.get(k) or "", ",".join(sorted(feeds))])
        if not cur.get("aktiv"):
            rows.append([day, bid, "wieder_da", "", "", "", ",".join(sorted(feeds))])
        cur.update(last_seen=day, aktiv=True, angaben=props, feeds=sorted(set(cur["feeds"]) | feeds))
    if complete:  # nur bei vollständigem Abruf aller Feeds als entfallen werten
        for bid, cur in state.items():
            if cur.get("aktiv") and bid not in seen:
                cur["aktiv"] = False
                cur["entfallen"] = day
                rows.append([day, bid, "entfallen", "", "", "", ""])
    return rows


def archive(base=None, now=None, fetcher=fetch):
    """Täglicher Abruf ins Archivverzeichnis (Standard: config.BAUSTELLEN_ARCHIV)."""
    base = Path(base or config.BAUSTELLEN_ARCHIV)
    now = now or datetime.now(timezone.utc)
    day, stamp = now.date().isoformat(), now.isoformat(timespec="seconds")
    base.mkdir(parents=True, exist_ok=True)
    state_file, log_file, stand_file = base / "baustellen.json", base / "protokoll.tsv", base / "STAND.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    stand = json.loads(stand_file.read_text(encoding="utf-8")) if stand_file.exists() else {}
    results, rows = {}, []
    for thema, feed in FEEDS.items():
        try:
            feats, tries = fetcher(thema)
        except RuntimeError as err:
            stand[feed] = {**stand.get(feed, {}), "versuch": stamp, "erfolg": False, "fehler": str(err)}
            rows.append([day, "", "abruf_fehlgeschlagen", feed, "", "", ""])
            continue
        items = normalize(feats)
        results[feed] = items
        snap = json.dumps({"meta": {"thema": thema, "feed": feed, "quelle": URL.format(thema),
                                                                 "lizenz": config.BAUSTELLEN_LICENSE},
                           "baustellen": items}, ensure_ascii=False, indent=1, sort_keys=True)
        if stand.get(feed, {}).get("inhalt") != hash_text(snap):  # nur geänderte Stände ablegen
            path = base / "snapshots" / now.strftime("%Y/%m/%d") / f"thema_{thema}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(snap + "\n", encoding="utf-8")
        stand[feed] = {"thema": thema, "abruf": stamp, "versuche": tries, "anzahl": len(items), "erfolg": True,
                       "inhalt": hash_text(snap)}
    rows += update(state, results, day)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    stand_file.write_text(json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if rows:
        new = not log_file.exists()
        with log_file.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("\t".join(LOG_HEAD) + "\n")
            fh.writelines("\t".join(str(x).replace("\t", " ") for x in r) + "\n" for r in rows)
    active = sum(1 for v in state.values() if v.get("aktiv"))
    print(f"Baustellen: {active} aktiv, {len(state)} insgesamt seit Archivbeginn, {len(rows)} Ereignisse → {base}")
    if not results:
        raise SystemExit("Baustellen: kein Feed abrufbar")
    return rows


def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
