"""SessionNet-Adapter: Abruf der Kölner OParl-API ins Bonner Rohdatenformat (CLAUDE.md 5.1).

Erzeugt dieselben Rohdateien wie der Bonner Abruf, damit build.py, Export und Seite unverändert bleiben:
- `papers.jsonl`      Vorlagen (OParl-Objekte), zusammengeführt über die ID; gelöschte bleiben mit `deleted`
- `organizations.json` und `verwaltungsbereiche.json`
- `meetings.json`     Sitzungen im Bonner Kurzformat; vollständige Sitzungen mit TOPs in `meetings_roh.jsonl`
- `legislative_terms.json`
- `beratungen.jsonl`  Beratung → Sitzung und TOP (in Bonn aus OParl-Lite; in Köln abgeleitet, weil `consultation`
                      direkt auf `meeting` und `agendaItem` verweist und die Sitzungen ihre TOPs enthalten)

Abruf: Listen nur über `links.next` (unverändert übernommen), nach dem ersten Lauf inkrementell über
`modified_since` (Zustand in `zustand_abruf.json`, mit einem Tag Überlappung). Parameter werden nicht URL-kodiert:
SessionNet beantwortet kodierte Zeitstempel (%3A, %2B) mit HTTP 404 (explore/ergebnisse/sessionnet_befunde.tsv).
Schutz gegen Endlosschleifen: Abbruch, wenn links.next auf eine gelesene Seite zeigt, eine Seite keine neuen
Kennungen bringt oder mehr als `config.ABRUF_MAX_SEITEN` Seiten folgen. Ob der Server den Filter anwendet, wird je
Lauf geprüft und in der Abrufstatistik vermerkt.

Ein Vollabruf, der am Ende des Zeitfensters oder durch einen Fehler abbricht, wird in der nächsten Nacht an der
gelesenen Stelle fortgesetzt (`<liste>_fortsetzung` im Zustand, Teilstand in `<datei>.teil.jsonl`). Keine Fortsetzung
nach einem Abbruch der Art `liste` (Schleife in links.next), `weiterleitung`, `proxy` oder `adresse` (ungültige
Adresse): Der nächste Lauf beginnt von vorn.

Nacht mit möglicher Sperre (`moegliche_sperre`, Zähler `sperre_verdacht` im Zustand): Zeitüberschreitung,
Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht (Art `sperre`), HTTP 401,
403 oder 429 (Art `http`) und `aufgegeben` nach 429, 5xx, unlesbarer Antwort oder CONNECT-Antwort 429/503 (abruf.py).
Nach drei solchen Nächten in Folge pausiert der Abruf sieben Tage; ein vollständiger Lauf setzt den Zähler zurück.
Fällt der Abruf aus, bleibt der letzte gültige Stand; der Fehler steht in `STAND.json`. Den Zustand sichert
pages.yml gleich nach dem Abrufschritt, auch wenn ein späterer Schritt scheitert.

Abrufstatistik (`abrufstatistik.tsv`, Spalten STAT_SPALTEN): je Liste eine Zeile und eine Zeile `body` für den Abruf
des Bodys; Zähler aus abruf.statistik() als Differenz je Zeile, darunter `weiterleitungen` und `proxy`.
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone

from . import abruf, config
from .fetch import MIN_ANTEIL, _guard, _jsonl_count, _now, _stamp, _write

UEBERLAPPUNG = timedelta(days=1)
SPERRE_NAECHTE = 3                 # Nächte in Folge mit möglicher Sperre (moegliche_sperre), danach Pause
SPERRE_PAUSE = timedelta(days=7)
SPERRE_GLEICHE_NACHT = timedelta(hours=12)   # nach einem Verdacht kein weiterer Lauf in derselben Nacht
# HTTP-Antworten, nach denen die Nacht als Nacht mit möglicher Sperre zählt (Art `http`; 429 endet sonst als
# `aufgegeben`, das ebenfalls zählt)
SPERRE_HTTP = (401, 403, 429)
STAT_SPALTEN = ["datum", "liste", "modus", "seiten", "objekte", "neu", "geaendert", "geloescht", "filter_wirksam",
                "anfragen", "fehler", "wiederholungen", "weiterleitungen", "proxy", "bytes", "sekunden", "ergebnis"]
# Zähler aus abruf.statistik(), je Zeile der Abrufstatistik als Differenz
STAT_ZAEHLER = ("anfragen", "fehler", "wiederholungen", "weiterleitungen", "proxy", "bytes", "sekunden")
# Abbruchsarten, nach denen ein Vollabruf nicht fortgesetzt wird (der nächste Lauf beginnt von vorn)
OHNE_FORTSETZUNG = ("liste", "weiterleitung", "proxy", "adresse")


def moegliche_sperre(fehler):
    """Zählt dieser Abbruch als Nacht mit möglicher Sperre? Art `sperre` (Zeitüberschreitung, Verbindungsabbruch,
    abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht), `aufgegeben` (nach 429, 5xx, unlesbarer
    Antwort oder CONNECT-Antwort 429/503) und `http` mit 401, 403 oder 429. Nicht: proxy (Ablehnung in der
    Ausführungsumgebung), liste, adresse, andere HTTP-Codes (z. B. 404). Eine Weiterleitung (etwa auf die Sperrseite
    einer vorgeschalteten Firewall) und eine unerwartete Antwortform (`unlesbar`) zählen vorsichtshalber mit."""
    art = getattr(fehler, "art", "")
    return art in ("sperre", "aufgegeben", "weiterleitung", "unlesbar") or (
        art == "http" and getattr(fehler, "code", None) in SPERRE_HTTP)


def _zustand():
    return json.loads(config.ZUSTAND.read_text()) if config.ZUSTAND.exists() else {}


def _zustand_setzen(schluessel, wert):
    z = _zustand()
    if wert is None:
        z.pop(schluessel, None)
    else:
        z[schluessel] = wert
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.ZUSTAND, json.dumps(z, ensure_ascii=False, indent=1) + "\n")


def _mit_parametern(url, **params):
    """Hängt Parameter ohne URL-Kodierung an (SessionNet, siehe oben); Werte enthalten nur Ziffern, -, :, + und T."""
    params = {k: v for k, v in params.items() if v}
    if not params:
        return url
    return url + ("&" if "?" in url else "?") + "&".join(f"{k}={v}" for k, v in params.items())


class Teilabbruch(abruf.Abbruch):
    """Abbruch mitten in einer Liste; trägt den gelesenen Teil für die Fortsetzung."""

    def __init__(self, ursache, objekte, naechste, seiten):
        super().__init__(str(ursache), getattr(ursache, "art", ""), getattr(ursache, "ziel", ""),
                         getattr(ursache, "code", None))
        self.objekte, self.naechste, self.seiten = objekte, naechste, seiten


def liste(url, seit=None, start=None, objekte=None, seiten=0):
    """Alle Objekte einer OParl-Liste über links.next; `seit` setzt modified_since. `start`, `objekte` und `seiten`
    setzen einen abgebrochenen Vollabruf fort. Liefert (Objekte, Seiten); ein Abbruch kommt als Teilabbruch."""
    naechste = start or _mit_parametern(url, modified_since=seit, limit=config.ABRUF_SEITENGROESSE)
    objekte = list(objekte or [])
    ids, gesehen = {o.get("id") for o in objekte}, set()
    while naechste:
        try:
            if naechste in gesehen:   # Schutz gegen zyklische Verweise
                raise abruf.Abbruch(f"links.next zeigt auf eine bereits gelesene Seite: {naechste}", "liste")
            if seiten >= config.ABRUF_MAX_SEITEN:
                raise abruf.Abbruch(f"mehr als {config.ABRUF_MAX_SEITEN} Seiten (RATSATLAS_MAX_SEITEN)", "liste")
            gesehen.add(naechste)
            seite = abruf.get_json(naechste)
        except abruf.Abbruch as e:
            raise Teilabbruch(e, objekte, naechste, seiten) from e
        seiten += 1
        daten = seite.get("data") or []
        neu = [o for o in daten if o.get("id") not in ids]
        if daten and not neu:   # dieselben Objekte mit neuem links.next (beobachtet bei SessionNet-Sammelservern)
            raise Teilabbruch(abruf.Abbruch(f"Seite ohne neue Kennungen, links.next läuft im Kreis: {naechste}",
                                            "liste"), objekte, None, seiten)
        ids.update(o.get("id") for o in neu)
        objekte += neu
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
    """Hängt eine Zeile an die Abrufstatistik an. Eine ältere Datei mit anderem Kopf (z. B. ohne `weiterleitungen` und
    `proxy`) wird zuvor auf STAT_SPALTEN umgestellt; fehlende Werte bleiben leer."""
    config.EXPORT.mkdir(parents=True, exist_ok=True)
    zeilen, modus = [zeile], "a"
    if not config.ABRUFSTATISTIK.exists():
        modus = "w"
    else:
        with open(config.ABRUFSTATISTIK, encoding="utf-8", newline="") as f:
            r = csv.DictReader(f, delimiter="\t")
            if r.fieldnames != STAT_SPALTEN:   # ältere Datei: neu schreiben, Werte nach Spaltennamen übernehmen
                zeilen, modus = [*r, zeile], "w"
    with open(config.ABRUFSTATISTIK, modus, encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, STAT_SPALTEN, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        if modus == "w":
            w.writeheader()
        w.writerows(zeilen)


def _differenz(zeile, vorher):
    """Trägt die Zähler aus abruf.statistik() seit `vorher` in die Zeile ein."""
    nachher = abruf.statistik()
    zeile.update({k: (round(nachher[k] - vorher[k], 1) if k == "sekunden" else nachher[k] - vorher[k])
                  for k in STAT_ZAEHLER})


def _teil(pfad):
    return pfad.with_name(pfad.name.split(".")[0] + ".teil.jsonl")


def _abruf_liste(name, url, pfad, schluessel):
    """Inkrementeller Abruf einer Liste mit Statistik; schreibt die zusammengeführten Objekte als JSONL.
    Ein abgebrochener Vollabruf wird beim nächsten Lauf an der gelesenen Stelle fortgesetzt."""
    vorher = abruf.statistik()
    start = datetime.now(timezone.utc)
    fort = _zustand().get(f"{schluessel}_fortsetzung")
    seit = None if fort else _seit(schluessel)
    zeile = {"datum": _now(), "liste": name, "modus": "voll, fortgesetzt" if fort else "inkrementell" if seit else "voll"}
    try:
        if fort:
            start = datetime.fromisoformat(fort["start"])
            teil = _teil(pfad)
            bisher = [json.loads(z) for z in teil.read_text(encoding="utf-8").splitlines()] if teil.exists() else []
            objekte, seiten = liste(url, start=fort["naechste"], objekte=bisher, seiten=fort.get("seiten", 0))
        else:
            objekte, seiten = liste(url, seit)
        alle, neu, geaendert, geloescht = _zusammenfuehren(pfad, objekte, voll=not seit)
        _write(pfad, "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in alle))
        _zustand_setzen(schluessel, start.isoformat(timespec="seconds"))
        _zustand_setzen(f"{schluessel}_fortsetzung", None)
        _teil(pfad).unlink(missing_ok=True)
        zeile.update(seiten=seiten, objekte=len(alle), neu=neu, geaendert=geaendert, geloescht=geloescht,
                     filter_wirksam=_filter_wirksam(objekte, seit), ergebnis="ok")
        return alle
    except Teilabbruch as e:
        # Vollabruf: gelesenen Teil sichern und morgen fortsetzen; eine veraltete Folgeseite (HTTP 4xx gleich zu
        # Beginn der Fortsetzung) oder ein Abbruch aus OHNE_FORTSETZUNG (Schleife, Weiterleitung, Proxy, Adresse)
        # verwirft die Fortsetzung, dann beginnt der nächste Lauf von vorn
        veraltet = fort and e.art == "http" and e.seiten == fort.get("seiten", 0)
        verwerfen = veraltet or e.art in OHNE_FORTSETZUNG
        if not seit and e.naechste and e.seiten and not verwerfen:
            config.RAW.mkdir(parents=True, exist_ok=True)
            _write(_teil(pfad), "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in e.objekte))
            _zustand_setzen(f"{schluessel}_fortsetzung", {"naechste": e.naechste, "seiten": e.seiten,
                                                         "start": start.isoformat(timespec="seconds")})
            zeile["ergebnis"] = f"unterbrochen nach {e.seiten} Seiten, Fortsetzung im nächsten Lauf: {e}"[:300]
        else:
            if verwerfen:
                _zustand_setzen(f"{schluessel}_fortsetzung", None)
                _teil(pfad).unlink(missing_ok=True)
            zeile["ergebnis"] = f"abbruch: {e}"[:300]
        zeile.update(seiten=e.seiten, objekte=len(e.objekte))
        raise
    except (abruf.Abbruch, RuntimeError) as e:
        zeile["ergebnis"] = f"abbruch: {e}"[:300]
        raise
    finally:
        _differenz(zeile, vorher)
        _statistik(zeile)


def _abruf_body():
    """Abruf des Bodys mit eigener Zeile `body` in der Abrufstatistik."""
    vorher = abruf.statistik()
    zeile = {"datum": _now(), "liste": "body"}
    try:
        body = abruf.get_json(config.OPARL_BODY)
        zeile.update(objekte=1, ergebnis="ok")
        return body
    except (abruf.Abbruch, RuntimeError) as e:
        zeile["ergebnis"] = f"abbruch: {e}"[:300]
        raise
    finally:
        _differenz(zeile, vorher)
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
    """Vollständiger bzw. inkrementeller Lauf. Ein Abbruch hält den letzten gültigen Stand und vermerkt den Fehler;
    Abbrüche nach `moegliche_sperre` zählen als Nacht mit möglicher Sperre."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    # Sperre und Zeitfenster sind kein Ausfall: der Lauf wird übersprungen, ohne den Stand als fehlgeschlagen zu markieren
    lokal = abruf.lokal(config.OPARL_BODY)
    grund = ("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (RATSATLAS_STADT_INFORMIERT)"
             if not abruf.freigegeben(config.OPARL_BODY) else
             f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr" if not lokal and not abruf.im_zeitfenster()
             else None)
    verdacht = _zustand().get("sperre_verdacht") or {}
    if not grund and verdacht.get("zuletzt") and not lokal:
        # nach einer Nacht mit möglicher Sperre in derselben Nacht kein weiterer Lauf (z. B. Push oder Knopfdruck)
        seit = datetime.now(timezone.utc) - datetime.fromisoformat(verdacht["zuletzt"])
        if seit < SPERRE_GLEICHE_NACHT:
            grund = (f"möglicher Sperrverdacht vor {int(seit.total_seconds() // 60)} Minuten; in derselben Nacht kein "
                     "weiterer Abruf")
    if not grund and verdacht.get("naechte", 0) >= SPERRE_NAECHTE:
        bis = datetime.fromisoformat(verdacht["zuletzt"]) + SPERRE_PAUSE
        if datetime.now(timezone.utc) < bis:
            grund = (f"Abruf pausiert bis {bis.date().isoformat()}: {verdacht['naechte']} Nächte in Folge mit "
                     "möglicher Sperre (Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, HTTP 401/403/429 "
                     "oder aufgegeben nach 429/5xx); bitte Kontakt zur Stadt aufnehmen")
    if grund:
        stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
        stand["abruf_uebersprungen"] = {"zeit": _now(), "grund": grund}
        _write(config.STAND, json.dumps(stand, ensure_ascii=False, indent=1) + "\n")
        print(f"Abruf übersprungen ({grund}); letzter Stand bleibt.")
        return
    try:
        body = _abruf_body()
        fetch_organizations(body)
        papers = fetch_papers(body)
        meetings = fetch_meetings(body)
        beratungen(papers, meetings)
        _stamp("abruf_ok")
        _zustand_setzen("sperre_verdacht", None)
    except (KeyError, TypeError, AttributeError) as e:   # gültiges JSON in unerwarteter Form (z. B. Body ohne Listen)
        e = abruf.Abbruch(f"unerwartete Antwortform ({type(e).__name__}: {e})", "unlesbar")
        _abbruch_vermerken(e, verdacht)
    except (abruf.Abbruch, RuntimeError) as e:
        _abbruch_vermerken(e, verdacht)


def _abbruch_vermerken(e, verdacht):
    """Abbruch in STAND.json vermerken und, falls `moegliche_sperre`, als Nacht mit möglicher Sperre zählen."""
    if moegliche_sperre(e):
        _zustand_setzen("sperre_verdacht", {
            "naechte": verdacht.get("naechte", 0) + 1,
            "zuletzt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "art": getattr(e, "art", ""), "code": getattr(e, "code", None), "meldung": str(e)[:300]})
    stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
    stand["abruf_fehler"] = {"zeit": _now(), "meldung": str(e)[:300]}
    _write(config.STAND, json.dumps(stand, ensure_ascii=False, indent=1) + "\n")
    print(f"Abruf abgebrochen, letzter gültiger Stand bleibt: {e}")
    if os.environ.get("RATSATLAS_STRENG") == "ja":
        raise e
