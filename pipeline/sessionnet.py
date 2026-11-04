"""SessionNet-Adapter: Abruf der Kölner OParl-API ins Bonner Rohdatenformat (CLAUDE.md 5.1).

Erzeugt dieselben Rohdateien wie der Bonner Abruf, damit build.py, Export und Seite unverändert bleiben:
- `papers.jsonl`      Vorlagen (OParl-Objekte), zusammengeführt über die ID; gelöschte bleiben mit `deleted`
- `organizations.json` und `verwaltungsbereiche.json`
- `meetings.json`     Sitzungen im Bonner Kurzformat; vollständige Sitzungen mit TOPs in `meetings_roh.jsonl`
- `legislative_terms.json`
- `beratungen.jsonl`  Beratung → Sitzung und TOP (in Bonn aus OParl-Lite; in Köln abgeleitet, weil `consultation`
                      direkt auf `meeting` und `agendaItem` verweist und die Sitzungen ihre TOPs enthalten)

Abruf: Listen nur über `links.next`, nach dem ersten Lauf inkrementell über `modified_since` (Zustand in
`zustand_abruf.json`, mit einem Tag Überlappung). Ob der Server den Filter anwendet, wird je Lauf geprüft und in der
Abrufstatistik vermerkt. Fällt der Abruf aus, bleibt der letzte gültige Stand; der Fehler steht in `STAND.json`.
"""
import csv
import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import abruf, config
from .fetch import MIN_ANTEIL, _guard, _jsonl_count, _now, _stamp, _write

UEBERLAPPUNG = timedelta(days=1)
STAT_SPALTEN = ["datum", "liste", "modus", "seiten", "objekte", "neu", "geaendert", "geloescht", "filter_wirksam",
                "anfragen", "fehler", "wiederholungen", "bytes", "sekunden", "ergebnis"]


def _zustand():
    return json.loads(config.ZUSTAND.read_text()) if config.ZUSTAND.exists() else {}


def _zustand_setzen(schluessel, wert):
    z = _zustand()
    z[schluessel] = wert
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.ZUSTAND, json.dumps(z, ensure_ascii=False, indent=1) + "\n")


def _mit_parametern(url, **params):
    params = {k: v for k, v in params.items() if v}
    if not params:
        return url
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)


def liste(url, seit=None):
    """Alle Objekte einer OParl-Liste über links.next; `seit` setzt modified_since. Liefert (Objekte, Seiten)."""
    naechste = _mit_parametern(url, modified_since=seit, limit=config.ABRUF_SEITENGROESSE)
    objekte, seiten, gesehen = [], 0, set()
    while naechste:
        if naechste in gesehen:   # Schutz gegen zyklische Verweise
            raise abruf.Abbruch(f"links.next zeigt auf eine bereits gelesene Seite: {naechste}")
        gesehen.add(naechste)
        seite = abruf.get_json(naechste)
        seiten += 1
        objekte += seite.get("data") or []
        naechste = (seite.get("links") or {}).get("next")
    return objekte, seiten


def _seit(schluessel):
    """modified_since für den nächsten Lauf: letzter Stand minus Überlappung; None = vollständiger Abruf."""
    letzter = _zustand().get(schluessel)
    if not letzter or os.environ.get("RATSATLAS_VOLLABRUF") == "ja":
        return None
    t = datetime.fromisoformat(letzter) - UEBERLAPPUNG
    return t.strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0000", "+00:00")


def _filter_wirksam(objekte, seit):
    """Prüft, ob der Server modified_since anwendet: keine Objekte mit älterem Änderungszeitpunkt."""
    if not seit:
        return ""
    grenze = datetime.fromisoformat(seit)
    aelter = [o for o in objekte if o.get("modified") and datetime.fromisoformat(o["modified"]) < grenze]
    return "ja" if not aelter else f"nein ({len(aelter)} ältere)"


def _zusammenfuehren(pfad, neu_objekte, voll):
    """Führt Objekte über die ID mit dem vorhandenen Stand zusammen; liefert (alle, neu, geändert, gelöscht)."""
    alt = {}
    if pfad.exists():
        with open(pfad, encoding="utf-8") as f:
            alt = {o["id"]: o for o in map(json.loads, f) if o.get("id")}
    if voll:
        _guard(pfad.name, len(neu_objekte), len(alt))
    neu = sum(1 for o in neu_objekte if o["id"] not in alt)
    geaendert = sum(1 for o in neu_objekte if o["id"] in alt and o != alt[o["id"]])
    geloescht = sum(1 for o in neu_objekte if o.get("deleted"))
    stand = {} if voll else dict(alt)
    stand.update({o["id"]: o for o in neu_objekte if o.get("id")})
    return list(stand.values()), neu, geaendert, geloescht


def _statistik(zeile):
    config.EXPORT.mkdir(parents=True, exist_ok=True)
    neu = not config.ABRUFSTATISTIK.exists()
    with open(config.ABRUFSTATISTIK, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, STAT_SPALTEN, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        if neu:
            w.writeheader()
        w.writerow(zeile)


def _abruf_liste(name, url, pfad, schluessel):
    """Inkrementeller Abruf einer Liste mit Statistik; schreibt die zusammengeführten Objekte als JSONL."""
    vorher = abruf.statistik()
    start = datetime.now(timezone.utc)
    seit = _seit(schluessel)
    zeile = {"datum": _now(), "liste": name, "modus": "inkrementell" if seit else "voll"}
    try:
        objekte, seiten = liste(url, seit)
        alle, neu, geaendert, geloescht = _zusammenfuehren(pfad, objekte, voll=not seit)
        _write(pfad, "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in alle))
        _zustand_setzen(schluessel, start.isoformat(timespec="seconds"))
        zeile.update(seiten=seiten, objekte=len(alle), neu=neu, geaendert=geaendert, geloescht=geloescht,
                     filter_wirksam=_filter_wirksam(objekte, seit), ergebnis="ok")
        return alle
    except (abruf.Abbruch, RuntimeError) as e:
        zeile["ergebnis"] = f"abbruch: {e}"[:300]
        raise
    finally:
        nachher = abruf.statistik()
        zeile.update({k: (round(nachher[k] - vorher[k], 1) if k == "sekunden" else nachher[k] - vorher[k])
                      for k in ("anfragen", "fehler", "wiederholungen", "bytes", "sekunden")})
        _statistik(zeile)


def fetch_organizations(body):
    pfad = config.RAW / "organizations.jsonl"
    orgs = [o for o in _abruf_liste("organizations", body["organization"], pfad, "organizations")
            if not o.get("deleted")]
    _write(config.ORGANIZATIONS, json.dumps(orgs, ensure_ascii=False))
    vb = [o for o in orgs if o.get("organizationType") == "Verwaltungsbereich"]
    _write(config.VERWALTUNGSBEREICHE, json.dumps(vb, ensure_ascii=False))
    _stamp("organizations")
    print(f"{len(orgs)} Organisationen, davon {len(vb)} Verwaltungsbereiche")
    return orgs


def fetch_meetings(body):
    meetings = [m for m in _abruf_liste("meetings", body["meeting"], config.RAW / "meetings_roh.jsonl", "meetings") if not m.get("deleted")]
    keep = ("id", "name", "meetingState", "cancelled", "start", "end", "organization", "web")
    _write(config.MEETINGS, json.dumps(
        [{**{k: m.get(k) for k in keep}, "invitation": (m.get("invitation") or {}).get("accessUrl"),
          "agenda_items": len(m.get("agendaItem") or [])} for m in meetings], ensure_ascii=False))
    terms = body.get("legislativeTerm") or []
    terms = [t for t in terms if isinstance(t, dict)]
    _write(config.LEGISLATIVE_TERMS, json.dumps(terms, ensure_ascii=False))
    _stamp("meetings")
    print(f"{len(meetings)} Sitzungen, {len(terms)} Wahlperioden")
    return meetings


def fetch_papers(body):
    papers = _abruf_liste("papers", body["paper"], config.PAPERS, "papers")
    _stamp("papers")
    print(f"{len(papers)} Vorlagen → {config.PAPERS}")
    return papers


def beratungen(papers, meetings):
    """Beratung → Sitzung und TOP im Format, das build.py aus OParl-Lite kennt. Fehlt in der Beratung die
    Organisation, wird sie aus der Sitzung übernommen und als abgeleitet markiert (`_organization_quelle`)."""
    sitzung = {m["id"]: m for m in meetings}
    top = {}
    for m in meetings:
        for t in m.get("agendaItem") or []:
            if isinstance(t, dict) and t.get("id"):
                top[t["id"]] = (t, m)
    zeilen, ohne_sitzung, ergaenzt = [], 0, 0
    for p in papers:
        for c in p.get("consultation") or []:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            t, m_top = top.get(c.get("agendaItem"), (None, None))
            m = sitzung.get(c.get("meeting")) or m_top
            if not c.get("organization") and m and m.get("organization"):
                c["organization"] = list(m["organization"]) if isinstance(m["organization"], list) else [m["organization"]]
                c["_organization_quelle"] = "sitzung"
                ergaenzt += 1
            if not m and not t:
                ohne_sitzung += 1
                continue
            zeilen.append({
                "uri": c["id"],
                "meeting": {"uri": m["id"], "name": m.get("name"), "startDate": m.get("start"),
                            "cancelled": bool(m.get("cancelled"))} if m else None,
                "agendaItem": {"uri": t["id"], "number": t.get("number"), "name": t.get("name"),
                               "result": t.get("result"), "public": t.get("public")} if t else None,
            })
    if len(zeilen) < MIN_ANTEIL * _jsonl_count(config.BERATUNGEN):
        raise RuntimeError(f"Beratungen: nur {len(zeilen)} statt bisher {_jsonl_count(config.BERATUNGEN)}")
    _write(config.BERATUNGEN, "".join(json.dumps(z, ensure_ascii=False) + "\n" for z in zeilen))
    # Ergänzte Organisationen in papers.jsonl übernehmen, damit build.py sie liest
    _write(config.PAPERS, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in papers))
    _stamp("consultations_lite")
    print(f"{len(zeilen)} Beratungen mit Sitzung oder TOP, {ohne_sitzung} ohne, {ergaenzt} Gremien aus der Sitzung")


def fetch_all():
    """Vollständiger bzw. inkrementeller Lauf. Ein Abbruch hält den letzten gültigen Stand und vermerkt den Fehler."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    # Sperre und Zeitfenster sind kein Ausfall: der Lauf wird übersprungen, ohne den Stand als fehlgeschlagen zu markieren
    lokal = config.OPARL_BODY.startswith(("http://127.0.0.1", "http://localhost"))
    grund = ("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (RATSATLAS_STADT_INFORMIERT)"
             if not abruf.freigegeben(config.OPARL_BODY) else
             f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr" if not lokal and not abruf.im_zeitfenster()
             else None)
    if grund:
        stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
        stand["abruf_uebersprungen"] = {"zeit": _now(), "grund": grund}
        _write(config.STAND, json.dumps(stand, ensure_ascii=False, indent=1) + "\n")
        print(f"Abruf übersprungen ({grund}); letzter Stand bleibt.")
        return
    try:
        body = abruf.get_json(config.OPARL_BODY)
        fetch_organizations(body)
        papers = fetch_papers(body)
        meetings = fetch_meetings(body)
        beratungen(papers, meetings)
        _stamp("abruf_ok")
    except (abruf.Abbruch, RuntimeError) as e:
        stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
        stand["abruf_fehler"] = {"zeit": _now(), "meldung": str(e)[:300]}
        _write(config.STAND, json.dumps(stand, ensure_ascii=False, indent=1) + "\n")
        print(f"Abruf abgebrochen, letzter gültiger Stand bleibt: {e}")
        if os.environ.get("RATSATLAS_STRENG") == "ja":
            raise
