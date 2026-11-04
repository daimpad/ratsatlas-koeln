"""Archiv des Anliegen- und Mängelmelders der Stadt Bonn (Phase 1, noch ohne Anzeige auf der Seite).

Die Schnittstelle (Open311 GeoReport v2) zeigt nur einen Teil der Meldungen: Ältere Meldungen verschwinden aus der
öffentlichen Liste (Phase 0, anliegen/phase0/BERICHT.md: Mai–Aug. 2026 nur 9–14 % der vergebenen Nummern sichtbar,
Okt. 99 %). Ein täglicher Abruf hält deshalb jede Meldung fest, sobald sie sichtbar ist, und zwar nur mit
Kategorie, Tag der Meldung, Ortsteil und Status (Entscheidung 27.10.2026):
- anliegen/meldungen.tsv – je Meldung: Nummer, Tag, Kategorie, Gruppe, Ortsteil, Stadtbezirk, Status, erstes und
  letztes Auftreten in der Liste
- anliegen/abrufe.tsv – je Abruf und Monat: Zahl laut Schnittstelle, neu, Status geändert, Fehler
- anliegen/STAND.json – letzter Abruf

Beschreibung, Bildbeschreibung, Foto, Adresse, Koordinate und Statustexte werden nicht gespeichert (CLAUDE.md 5.2:
keine Wohnadressen; in den Texten stehen Namen, Kennzeichen und Hausnummern). Die Koordinate dient nur der Zuordnung
zum Ortsteil. Meldungen sind Hinweise der Einwohnerschaft an die Verwaltung, keine Ratsvorlagen.

Quelle: Stadt Bonn, https://anliegen.bonn.de, Datensatz „Anliegen- und Mängelmelder Open311“ auf opendata.bonn.de,
Lizenz CC0 1.0."""
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config

URL = "https://anliegen.bonn.de/api/georeport/v2/requests.json"
LICENSE = "CC0 1.0 (Stadt Bonn, Anliegen- und Mängelmelder, opendata.bonn.de)"
BEGINN = date(2021, 11, 1)   # erste Meldung der heutigen Nummerierung: 1-2021 vom 23.11.2021
FENSTER = 120                # Tage: tägliche Läufe holen die Monate ab heute − 120 Tagen erneut (Status, Nachzügler)
SEITE = 500                  # Höchstzahl je Anfrage laut Schnittstelle
PAUSE = 2                    # Sekunden zwischen Anfragen
# Gruppen nach der Oberkategorie der Stadt (Nummer vor dem Punkt); E-Scooter (4.0) gehört laut Stadt zu
# „Straßen und Verkehr“; „Grünüberwuchs Verkehrsraum“ (2.3) bleibt bei „Stadtbild und Grün“ (Entscheidung 27.10.2026)
GRUPPEN = {"1": "Abfall", "2": "Stadtbild und Grün", "3": "Straßen und Verkehr", "4": "Straßen und Verkehr"}
KOPF = ["nummer", "tag", "kategorie_code", "kategorie", "gruppe", "ortsteil", "stadtbezirk", "status", "status_name",
        "erstmals_gesehen", "zuletzt_gesehen"]
LOG_KOPF = ["datum", "monat", "laut_quelle", "erhalten", "neu", "status_geaendert", "fehler"]


def _laden(url):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def fetch_month(first, opener=_laden, tries=3, pause=PAUSE):
    """Alle sichtbaren Meldungen eines Kalendermonats, seitenweise. Gibt (Meldungen, Gesamtzahl) zurück; prüft die
    Zahl gegen meta.total (neue Meldungen während des Abrufs: neuer Versuch) und wirft sonst RuntimeError."""
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    last_err = None
    for i in range(tries):
        try:
            items, total, offset = [], None, 0
            while True:
                q = urllib.parse.urlencode({"start_date": first.isoformat(), "end_date": f"{last.isoformat()}T23:59:59",
                                            "extensions": "true", "meta": "true", "sort": "asc",
                                            "limit": SEITE, "offset": offset})
                data = opener(f"{URL}?{q}")
                page = data.get("requests") if isinstance(data, dict) else None
                if page is None:
                    raise ValueError("Antwort ohne „requests“")
                total = (data.get("meta") or {}).get("total", total)
                items += page
                offset += SEITE
                if len(page) < SEITE or (total is not None and len(items) >= total):
                    break
                time.sleep(pause)
            ids = {r.get("service_request_id") for r in items}
            if total is not None and len(ids) != total:
                raise ValueError(f"{total} laut Schnittstelle, {len(ids)} erhalten")
            return items, total if total is not None else len(ids)
        except Exception as err:
            last_err = err
            if i < tries - 1:
                time.sleep(pause * 5)
    raise RuntimeError(f"{first:%Y-%m}: {tries} Versuche ohne vollständige Antwort ({last_err})")


def normalize(r, ortsteile):
    """Nur Nummer, Tag, Kategorie, Ortsteil und Status; Koordinate nur zur Zuordnung, danach verworfen."""
    code = str(r.get("service_code") or "")
    ext = (r.get("extended_attributes") or {}).get("markaspot") or {}
    ot = None
    try:
        lon, lat = float(r["long"]), float(r["lat"])
        ot = ortsteile.locate(lon, lat)
    except (KeyError, TypeError, ValueError):
        pass
    return {"nummer": str(r.get("service_request_id") or ""), "tag": str(r.get("requested_datetime") or "")[:10],
            "kategorie_code": code, "kategorie": r.get("service_name") or "",
            "gruppe": GRUPPEN.get(code.split(".")[0], "sonstige"),
            "ortsteil": ot["ortsteil_bez"] if ot else "", "stadtbezirk": ot["bezirk_bez"] if ot else "",
            "status": r.get("status") or "", "status_name": ext.get("status_descriptive_name") or ""}


def _sortkey(nummer):
    n, _, jahr = nummer.partition("-")
    return (int(jahr) if jahr.isdigit() else 0, int(n) if n.isdigit() else 0, nummer)


def read_state(path):
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return {row[0]: dict(zip(head, row)) for row in (l.split("\t") for l in lines[1:] if l)}


def write_state(path, state):
    rows = ["\t".join(KOPF)] + ["\t".join(str(state[k].get(c, "")).replace("\t", " ") for c in KOPF)
                                for k in sorted(state, key=_sortkey)]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tmp.replace(path)


def update(state, items, day):
    """Meldungen eintragen; gibt (neu, Status geändert) zurück."""
    neu = geaendert = 0
    for m in items:
        cur = state.get(m["nummer"])
        if cur is None:
            state[m["nummer"]] = {**m, "erstmals_gesehen": day, "zuletzt_gesehen": day}
            neu += 1
            continue
        if (cur.get("status"), cur.get("status_name")) != (m["status"], m["status_name"]):
            geaendert += 1
        cur.update({**m, "zuletzt_gesehen": day})   # erstmals_gesehen bleibt
    return neu, geaendert


def months(start, end):
    m = start.replace(day=1)
    while m <= end:
        yield m
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)


def archive(base=None, now=None, fetcher=fetch_month, ortsteile=None):
    """Täglicher Abruf ins Archivverzeichnis (Standard: config.BAUSTELLEN_ARCHIV/anliegen). Beim ersten Lauf alle
    sichtbaren Monate ab BEGINN, danach die Monate der letzten FENSTER Tage."""
    from .geo import Ortsteile
    base = Path(base or config.BAUSTELLEN_ARCHIV) / "anliegen"
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()
    base.mkdir(parents=True, exist_ok=True)
    state_file, log_file, stand_file = base / "meldungen.tsv", base / "abrufe.tsv", base / "STAND.json"
    state = read_state(state_file)
    ortsteile = ortsteile or Ortsteile()
    start = BEGINN if not state else max(BEGINN, now.date() - timedelta(days=FENSTER))
    rows, ok, fehler = [], 0, 0
    for first in months(start, now.date()):
        try:
            raw, total = fetcher(first)
        except RuntimeError as err:
            rows.append([day, f"{first:%Y-%m}", "", "", "", "", str(err)])
            fehler += 1
            continue
        items = [normalize(r, ortsteile) for r in raw if r.get("service_request_id")]
        neu, geaendert = update(state, items, day)
        rows.append([day, f"{first:%Y-%m}", total, len(items), neu, geaendert, ""])
        ok += 1
        time.sleep(PAUSE if fetcher is fetch_month else 0)
    write_state(state_file, state)
    stand = {"abruf": now.isoformat(timespec="seconds"), "quelle": URL, "lizenz": LICENSE,
             "monate_ab": start.isoformat(), "monate_erfolgreich": ok, "monate_fehlgeschlagen": fehler,
             "meldungen": len(state), "ohne_ortsteil": sum(1 for m in state.values() if not m.get("ortsteil")),
             "archiv_beginn": min((m["erstmals_gesehen"] for m in state.values()), default=day)}
    stand_file.write_text(json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    new = not log_file.exists()
    with log_file.open("a", encoding="utf-8") as fh:
        if new:
            fh.write("\t".join(LOG_KOPF) + "\n")
        fh.writelines("\t".join(str(x).replace("\t", " ") for x in r) + "\n" for r in rows)
    print(f"Mängelmelder: {len(state)} Meldungen im Archiv, {ok} Monate abgerufen, {fehler} fehlgeschlagen → {base}")
    if not ok:
        raise SystemExit("Mängelmelder: kein Monat abrufbar")
    return rows


# --- Seite: Zahlen je Ortsteil für den Steckbrief (Schritt `anliegen-seite`, im Workflow nach dem Auschecken des
# Branches archiv). Nur Zählungen; Werte unter UNTER gerundet als „unter 3“, kein Link auf einzelne Meldungen.
SEITE_DATEI = "anliegen.json"
TAGE = 90
UNTER = 3
GRUPPEN_FOLGE = ("Abfall", "Stadtbild und Grün", "Straßen und Verkehr")


def _zaehlen(meldungen):
    z = {g: 0 for g in GRUPPEN_FOLGE}
    for m in meldungen:
        if m.get("gruppe") in z:
            z[m["gruppe"]] += 1
    z["gesamt"] = sum(z.values())
    return {k: (v if v >= UNTER else "unter 3") for k, v in z.items()}


def seite(base=None, out=None, heute=None):
    """export/bonn/anliegen.json aus dem Archiv: Meldungen der letzten TAGE Tage je Ortsteil, Stadtbezirk und ganz Bonn,
    nach Gruppe. Ohne Archiv wird nichts geschrieben (der Steckbrief zeigt dann keine Meldungen)."""
    base = Path(base or config.BAUSTELLEN_ARCHIV) / "anliegen"
    out = Path(out or config.EXPORT / "bonn" / SEITE_DATEI)
    state_file, stand_file = base / "meldungen.tsv", base / "STAND.json"
    if not state_file.exists() or not stand_file.exists():
        out.unlink(missing_ok=True)
        print("Mängelmelder: kein Archiv – übersprungen.")
        return None
    stand = json.loads(stand_file.read_text(encoding="utf-8"))
    bis = heute or date.fromisoformat(stand["abruf"][:10])
    von = bis - timedelta(days=TAGE - 1)
    sel = [m for m in read_state(state_file).values() if von.isoformat() <= m["tag"] <= bis.isoformat() and m.get("ortsteil")]
    ots, bez = {}, {}
    for m in sel:
        ots.setdefault(m["ortsteil"], []).append(m)
        bez.setdefault(m["stadtbezirk"], []).append(m)
    beginn = stand.get("archiv_beginn")
    doc = {"meta": {"titel": "Anliegen- und Mängelmelder der Stadt Bonn", "url": "https://anliegen.bonn.de",
                    "lizenz": LICENSE, "abruf": stand["abruf"][:10], "archiv_beginn": beginn,
                    "von": von.isoformat(), "bis": bis.isoformat(), "tage": TAGE, "gruppen": list(GRUPPEN_FOLGE),
                    "unvollstaendig_vor": beginn if beginn and beginn > von.isoformat() else None,
                    "hinweis": "Hinweise der Einwohnerschaft an die Verwaltung, keine Ratsvorlagen. Die Zahl hängt davon ab, "
                               "wer meldet und was veröffentlicht wird; sie ist kein Maß für den Zustand eines Gebiets."},
           "bonn": _zaehlen(sel),
           "bezirke": {n: _zaehlen(v) for n, v in sorted(bez.items())},
           "ortsteile": {n: _zaehlen(v) for n, v in sorted(ots.items())}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    if befunde := pruefen(out):   # hier statt in `check`: das Archiv liegt erst nach der Aufbereitung vor
        out.unlink()
        raise SystemExit(f"Prüfung fehlgeschlagen: Mängelmelder ({'; '.join(befunde)}).")
    print(f"Mängelmelder: {len(sel)} Meldungen vom {von:%d.%m.%Y} bis {bis:%d.%m.%Y} in {len(ots)} Ortsteilen → {out}")
    return doc


def pruefen(path=None):
    """Prüfung (Teil von `check`): nur Zählungen je Gruppe, kleine Werte als „unter 3“, keine weiteren Felder."""
    path = Path(path or config.EXPORT / "bonn" / SEITE_DATEI)
    if not path.exists():
        return []
    doc, befunde = json.loads(path.read_text(encoding="utf-8")), []
    erlaubt = set(GRUPPEN_FOLGE) | {"gesamt"}
    gebiete = [("Bonn", doc["bonn"])] + list(doc["bezirke"].items()) + list(doc["ortsteile"].items())
    for name, z in gebiete:
        if set(z) - erlaubt:
            befunde.append(f"Mängelmelder {name}: unerwartete Felder {sorted(set(z) - erlaubt)}")
        if any(not (v == "unter 3" or (isinstance(v, int) and v >= UNTER)) for v in z.values()):
            befunde.append(f"Mängelmelder {name}: Wert unter {UNTER} nicht gerundet")
    return befunde
