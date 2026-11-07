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
Adresse): Der nächste Lauf beginnt von vorn. Eine unlesbare Fortsetzung (auch eine fehlende oder unlesbare Teildatei)
wird verworfen und gemeldet; der Vollabruf beginnt dann von vorn.

Nacht mit möglicher Sperre (`moegliche_sperre`, Zähler `sperre_verdacht` im Zustand): Zeitüberschreitung,
Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht (Art `sperre`), HTTP 401,
403 oder 429 (Art `http`), `aufgegeben` nach 429, 5xx, unlesbarer Antwort oder CONNECT-Antwort 429/503 (auch sofort,
wenn die Pause nicht mehr ins Zeitfenster passt oder Retry-After zu lang oder unlesbar ist, abruf.py), außerdem
vorsichtshalber eine Weiterleitung (etwa auf die Sperrseite einer Firewall) und gültiges JSON in unerwarteter Form
(Art `unlesbar`: kein Objekt, Body ohne Listen, Seite ohne Liste `data` oder mit unlesbarem `links`). Nicht: Ablehnung
durch den Proxy der Ausführungsumgebung (`proxy`) und ungültige Adressen (`adresse`): Diese Anfragen haben die Stadt
nie erreicht.
- nach einem Sperrverdacht kein weiterer Lauf in derselben Nacht (12 Stunden, `SPERRE_GLEICHE_NACHT`), etwa nach einem
  Push oder auf Knopfdruck
- nach drei solchen Nächten ohne vollständigen Lauf dazwischen pausiert der Abruf sieben Tage; ein vollständiger Lauf
  setzt den Zähler zurück
Abbrüche der Art `liste` oder `adresse` (dauerhaft ungültiges links.next oder Schleife: jede Nacht ein Vollabruf bis
zur selben Stelle) zählt `listenfehler` im Zustand: Hinweis in STAND.json (`abruf_hinweis`) und Warnung im Log des
Workflows; nach drei solchen Nächten ohne vollständigen Lauf dazwischen sieben Tage Pause.
Der Zustand wird vor der ersten Anfrage geprüft: Ist die Datei oder ein Zeitpunkt des letzten Abrufs einer Liste
unlesbar, bricht der Lauf ohne Anfrage laut ab (`ZustandUnlesbar`). Ein unlesbarer, zonenloser oder künftiger
Zeitpunkt des letzten Sperrverdachts gilt als „jetzt“ (in dieser Nacht kein Abruf), eine unlesbare Zahl der Nächte als
drei; beides wird neu geschrieben und gemeldet. Eine unlesbare STAND.json wird als `STAND.json.defekt` beiseitegelegt.
Programmfehler (etwa eine unerwartete Form tief in einem Objekt) zählen nicht als Sperrverdacht: Sie stehen in
STAND.json und brechen den Lauf mit Traceback ab.
Fällt der Abruf aus, bleibt der letzte gültige Stand; der Fehler steht in `STAND.json`. Den Zustand sichert
pages.yml gleich nach dem Abrufschritt, auch wenn ein späterer Schritt scheitert.

Abrufstatistik (`abrufstatistik.tsv`, Spalten STAT_SPALTEN): je Liste eine Zeile und eine Zeile `body` für den Abruf
des Bodys; Zähler aus abruf.statistik() als Differenz je Zeile, darunter `weiterleitungen` und `proxy`.
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from . import abruf, config
from .fetch import MIN_ANTEIL, _guard, _jsonl_count, _now, _write

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
# Abbruchsarten, die auf eine dauerhaft fehlerhafte Liste deuten (Zähler `listenfehler`), und deren Grenze
LISTENFEHLER = ("liste", "adresse")
LISTENFEHLER_NAECHTE = 3
LISTENFEHLER_PAUSE = timedelta(days=7)
# Listen mit Zeitpunkt des letzten Abrufs im Zustand
LISTEN = ("organizations", "papers", "meetings")


class ZustandUnlesbar(RuntimeError):
    """zustand_abruf.json oder ein Zeitpunkt darin ist unlesbar: keine Anfrage, bis die Datei geprüft ist."""


def moegliche_sperre(fehler):
    """Zählt dieser Abbruch als Nacht mit möglicher Sperre? Art `sperre` (Zeitüberschreitung, Verbindungsabbruch,
    abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht), `aufgegeben` (nach 429, 5xx, unlesbarer
    Antwort oder CONNECT-Antwort 429/503) und `http` mit 401, 403 oder 429. Nicht: proxy (Ablehnung in der
    Ausführungsumgebung), liste, adresse, andere HTTP-Codes (z. B. 404). Eine Weiterleitung (etwa auf die Sperrseite
    einer vorgeschalteten Firewall) und eine unerwartete Antwortform (`unlesbar`) zählen vorsichtshalber mit."""
    art = getattr(fehler, "art", "")
    return art in ("sperre", "aufgegeben", "weiterleitung", "unlesbar") or (
        art == "http" and getattr(fehler, "code", None) in SPERRE_HTTP)


def _warnung(text):
    """Warnung auf stderr; in GitHub Actions als Anmerkung (::warning::), damit sie im Workflow sichtbar wird."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{text}", file=sys.stderr, flush=True)
    else:
        print(f"Warnung: {text}", file=sys.stderr, flush=True)


def _zeit(wert):
    """Zeitpunkt mit Zone aus einem ISO-Text; None, wenn kein Text, unlesbar oder ohne Zone."""
    if not isinstance(wert, str):
        return None
    try:
        t = datetime.fromisoformat(wert)
    except ValueError:
        return None
    return t if t.utcoffset() is not None else None


def _zustand():
    """Zustand des Abrufs; unlesbare Datei: ZustandUnlesbar (der Lauf bricht ohne Anfrage ab)."""
    if not config.ZUSTAND.exists():
        return {}
    try:
        z = json.loads(config.ZUSTAND.read_text(encoding="utf-8"))
    except ValueError as e:   # auch UnicodeDecodeError
        raise ZustandUnlesbar(f"{config.ZUSTAND.name} unlesbar ({e}); keine Anfrage an die Stadt, bis die Datei geprüft "
                              "oder entfernt ist (ohne Datei: Vollabruf, Zähler der Nächte verloren)") from e
    if not isinstance(z, dict):
        raise ZustandUnlesbar(f"{config.ZUSTAND.name} ist kein JSON-Objekt; keine Anfrage an die Stadt, bis die Datei "
                              "geprüft ist")
    return z


def _zustand_setzen(schluessel, wert):
    z = _zustand()
    if wert is None:
        z.pop(schluessel, None)
    else:
        z[schluessel] = wert
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.ZUSTAND, json.dumps(z, ensure_ascii=False, indent=1) + "\n")


def _zaehler_pruefen(z, schluessel, grenze, jetzt):
    """Zähler der Nächte (`sperre_verdacht`, `listenfehler`) vorsichtig lesen: unlesbarer, zonenloser oder künftiger
    Zeitpunkt `zuletzt` → jetzt (in dieser Nacht kein Abruf); unlesbare Zahl der Nächte → `grenze` (Pause). Liefert den
    Zähler und die Meldungen zu ersetzten Werten."""
    v = z.get(schluessel)
    if not v:
        return {}, []
    meldungen = []
    if not isinstance(v, dict):
        meldungen.append(f"{schluessel} ist kein Objekt ({v!r})")
        v = {}
    v = dict(v)
    n = v.get("naechte")
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        meldungen.append(f"{schluessel}.naechte unlesbar ({n!r}), gilt als {grenze}")
        v["naechte"] = grenze
    zuletzt = _zeit(v.get("zuletzt"))
    if zuletzt is None or zuletzt > jetzt:
        grund = "in der Zukunft" if zuletzt is not None else "unlesbar oder ohne Zone"
        meldungen.append(f"{schluessel}.zuletzt {grund} ({v.get('zuletzt')!r}), gilt als jetzt")
        v["zuletzt"] = jetzt.isoformat(timespec="seconds")
    return v, meldungen


def _zustand_pruefen():
    """Vor der ersten Anfrage: Zustand lesen und prüfen (siehe Moduldoku). Liefert den Zustand mit geprüften Zählern."""
    z = _zustand()
    for liste in LISTEN:
        if liste in z and _zeit(z[liste]) is None:
            raise ZustandUnlesbar(f"Zeitpunkt des letzten Abrufs von {liste} in {config.ZUSTAND.name} unlesbar oder "
                                  f"ohne Zone ({z[liste]!r}); keine Anfrage an die Stadt, bis der Wert geprüft ist")
    jetzt = datetime.now(timezone.utc)
    for schluessel, grenze in (("sperre_verdacht", SPERRE_NAECHTE), ("listenfehler", LISTENFEHLER_NAECHTE)):
        v, meldungen = _zaehler_pruefen(z, schluessel, grenze, jetzt)
        if meldungen:
            z[schluessel] = v
            _zustand_setzen(schluessel, v)
            _warnung(f"{config.ZUSTAND.name}: " + "; ".join(meldungen) + " (neu geschrieben)")
    return z


def _pause_grund(z, lokal):
    """Grund, den Lauf ohne Anfrage zu überspringen (12-Stunden-Regel, Pausen nach drei Nächten), sonst None."""
    jetzt = datetime.now(timezone.utc)
    verdacht = z.get("sperre_verdacht") or {}
    if verdacht and not lokal:
        # nach einer Nacht mit möglicher Sperre in derselben Nacht kein weiterer Lauf (z. B. Push oder Knopfdruck)
        seit = jetzt - _zeit(verdacht["zuletzt"])
        if seit < SPERRE_GLEICHE_NACHT:
            return (f"möglicher Sperrverdacht vor {int(seit.total_seconds() // 60)} Minuten; in derselben Nacht kein "
                    "weiterer Abruf")
    if verdacht.get("naechte", 0) >= SPERRE_NAECHTE:
        bis = _zeit(verdacht["zuletzt"]) + SPERRE_PAUSE
        if jetzt < bis:
            return (f"Abruf pausiert bis {bis.date().isoformat()}: {verdacht['naechte']} Nächte in Folge mit möglicher "
                    "Sperre (Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, HTTP 401/403/429, Weiterleitung "
                    "oder aufgegeben nach 429/5xx); bitte Kontakt zur Stadt aufnehmen")
    fehler = z.get("listenfehler") or {}
    if fehler.get("naechte", 0) >= LISTENFEHLER_NAECHTE:
        bis = _zeit(fehler["zuletzt"]) + LISTENFEHLER_PAUSE
        if jetzt < bis:
            return (f"Abruf pausiert bis {bis.date().isoformat()}: {fehler['naechte']} Nächte in Folge Abbruch wegen "
                    "einer fehlerhaften Liste (ungültige Folgeadresse in links.next oder Schleife); bitte die Liste "
                    "prüfen")
    return None


def _stand():
    """STAND.json; eine unlesbare Datei wird als STAND.json.defekt beiseitegelegt (mit Warnung) und neu begonnen."""
    if not config.STAND.exists():
        return {}
    try:
        s = json.loads(config.STAND.read_text(encoding="utf-8"))
        if isinstance(s, dict):
            return s
        grund = "kein JSON-Objekt"
    except ValueError as e:
        grund = str(e)
    defekt = config.STAND.with_name(config.STAND.name + ".defekt")
    os.replace(config.STAND, defekt)
    _warnung(f"{config.STAND.name} unlesbar ({grund}); beiseitegelegt als {defekt.name}, neu begonnen")
    return {}


def _stand_setzen(**werte):
    s = _stand()
    s.update(werte)
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.STAND, json.dumps(s, ensure_ascii=False, indent=1) + "\n")


def _stamp(schluessel):
    _stand_setzen(**{schluessel: _now()})


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


def _seite_pruefen(seite, url):
    """Form einer Listenseite, geprüft dort, wo sie ankommt: `data` ist eine Liste von Objekten mit Kennung (Text),
    `links` fehlt oder ist ein Objekt, `links.next` fehlt oder ist Text. Sonst Abbruch der Art `unlesbar` (gültiges JSON
    in unerwarteter Form: keine Wiederholung, zählt als Nacht mit möglicher Sperre)."""
    daten, links = seite.get("data"), seite.get("links")
    if not isinstance(daten, list) or not all(isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"]
                                              for o in daten):
        grund = "data ist keine Liste von Objekten mit Kennung"
    elif links is not None and not isinstance(links, dict):
        grund = "links ist kein Objekt"
    elif links and links.get("next") is not None and not isinstance(links["next"], str):
        grund = "links.next ist kein Text"
    else:
        return
    raise abruf.Abbruch(f"unerwartete Antwortform ({grund}): {url}", "unlesbar")


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
            _seite_pruefen(seite, naechste)
        except abruf.Abbruch as e:
            raise Teilabbruch(e, objekte, naechste, seiten) from e
        seiten += 1
        daten = seite["data"]
        neu = [o for o in daten if o["id"] not in ids]
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
    t = _zeit(letzter)
    if t is None:   # vor der ersten Anfrage geprüft (_zustand_pruefen); hier nur zur Sicherheit
        raise ZustandUnlesbar(f"Zeitpunkt des letzten Abrufs von {schluessel} unlesbar: {letzter!r}")
    t = t.astimezone(timezone.utc) - UEBERLAPPUNG
    return t.strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0000", "+00:00")


def _filter_wirksam(objekte, seit):
    """Prüft, ob der Server modified_since anwendet: keine Objekte mit älterem Änderungszeitpunkt. Ein unlesbares oder
    zonenloses `modified` (Angabe der Quelle) wird gezählt, nicht als Fehler behandelt."""
    if not seit:
        return ""
    grenze = datetime.fromisoformat(seit)
    aelter = unlesbar = 0
    for o in objekte:
        if o.get("modified") in (None, ""):
            continue
        t = _zeit(o["modified"])
        if t is None:
            unlesbar += 1
        elif t < grenze:
            aelter += 1
    ergebnis = "ja" if not aelter else f"nein ({aelter} ältere)"
    return ergebnis + (f"; {unlesbar} mit unlesbarem modified" if unlesbar else "")


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


def _statistik_sicher(zeile):
    """Wie _statistik, aber ein Schreibfehler (OSError) verdrängt nicht den eigentlichen Abbruch (der sonst nicht als
    Nacht mit möglicher Sperre gezählt würde): nur eine Warnung."""
    try:
        _statistik(zeile)
    except OSError as e:
        _warnung(f"Abrufstatistik nicht geschrieben ({e}); Zeile: {zeile}")


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


def _fortsetzung(schluessel, pfad):
    """Gespeicherte Fortsetzung eines Vollabrufs und der gelesene Teil: (Fortsetzung, Objekte, Meldung). Ist sie
    unlesbar (Form, Zeitpunkt, fehlende oder unlesbare Teildatei), wird sie verworfen: (None, None, Meldung)."""
    fort = _zustand().get(f"{schluessel}_fortsetzung")
    if fort is None:
        return None, None, ""
    teil, grund, bisher = _teil(pfad), "", []
    seiten = fort.get("seiten", 0) if isinstance(fort, dict) else None
    if not isinstance(fort, dict):
        grund = "kein Objekt"
    elif not isinstance(fort.get("naechste"), str) or not fort["naechste"]:
        grund = "Folgeadresse fehlt"
    elif isinstance(seiten, bool) or not isinstance(seiten, int) or seiten < 0:
        grund = f"Seitenzahl unlesbar ({seiten!r})"
    elif _zeit(fort.get("start")) is None:
        grund = f"Startzeitpunkt unlesbar ({fort.get('start')!r})"
    elif seiten and not teil.exists():
        grund = f"Teildatei {teil.name} fehlt"
    elif teil.exists():
        try:
            bisher = [json.loads(z) for z in teil.read_text(encoding="utf-8").splitlines() if z.strip()]
            if not all(isinstance(o, dict) and isinstance(o.get("id"), str) for o in bisher):
                grund = f"Teildatei {teil.name} enthält Zeilen ohne Kennung"
        except ValueError as e:
            grund = f"Teildatei {teil.name} unlesbar ({e})"
    if not grund:
        return fort, bisher, ""
    meldung = f"Fortsetzung von {schluessel} verworfen ({grund}); der Vollabruf beginnt von vorn"
    _warnung(meldung)
    _zustand_setzen(f"{schluessel}_fortsetzung", None)
    teil.unlink(missing_ok=True)
    return None, None, meldung


def _abruf_liste(name, url, pfad, schluessel):
    """Inkrementeller Abruf einer Liste mit Statistik; schreibt die zusammengeführten Objekte als JSONL.
    Ein abgebrochener Vollabruf wird beim nächsten Lauf an der gelesenen Stelle fortgesetzt."""
    vorher = abruf.statistik()
    start = datetime.now(timezone.utc)
    fort, bisher, verworfen = _fortsetzung(schluessel, pfad)
    seit = None if fort else _seit(schluessel)
    zeile = {"datum": _now(), "liste": name, "modus": "voll, fortgesetzt" if fort else "inkrementell" if seit else
             "voll, Fortsetzung verworfen" if verworfen else "voll"}
    try:
        if fort:
            start = _zeit(fort["start"])
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
    except Exception as e:
        zeile["ergebnis"] = f"programmfehler: {type(e).__name__}: {e}"[:300]
        raise
    finally:
        _differenz(zeile, vorher)
        _statistik_sicher(zeile)


def _abruf_body():
    """Abruf des Bodys mit eigener Zeile `body` in der Abrufstatistik. Der Body muss die Listen `paper`, `meeting` und
    `organization` als Adressen nennen, sonst Abbruch der Art `unlesbar`."""
    vorher = abruf.statistik()
    zeile = {"datum": _now(), "liste": "body"}
    try:
        body = abruf.get_json(config.OPARL_BODY)
        fehlt = [f for f in ("paper", "meeting", "organization") if not isinstance(body.get(f), str) or not body[f]]
        if fehlt:
            raise abruf.Abbruch(f"unerwartete Antwortform (Body ohne Liste {', '.join(fehlt)}): {config.OPARL_BODY}",
                                "unlesbar")
        zeile.update(objekte=1, ergebnis="ok")
        return body
    except (abruf.Abbruch, RuntimeError) as e:
        zeile["ergebnis"] = f"abbruch: {e}"[:300]
        raise
    except Exception as e:
        zeile["ergebnis"] = f"programmfehler: {type(e).__name__}: {e}"[:300]
        raise
    finally:
        _differenz(zeile, vorher)
        _statistik_sicher(zeile)


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


def _einladung(m):
    inv = m.get("invitation")
    return inv.get("accessUrl") if isinstance(inv, dict) else None


def _kennung(wert):
    """Verweis als Schlüssel: nur Text (eine Liste oder ein Objekt an dieser Stelle ergibt keinen Treffer)."""
    return wert if isinstance(wert, str) else None


def fetch_meetings(body):
    meetings = [m for m in _abruf_liste("meetings", body["meeting"], config.RAW / "meetings_roh.jsonl", "meetings") if not m.get("deleted")]
    keep = ("id", "name", "meetingState", "cancelled", "start", "end", "organization", "web")
    _write(config.MEETINGS, json.dumps(
        [{**{k: m.get(k) for k in keep}, "invitation": _einladung(m),
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
            if isinstance(t, dict) and _kennung(t.get("id")):
                top[t["id"]] = (t, m)
    zeilen, ohne_sitzung, ergaenzt = [], 0, 0
    for p in papers:
        for c in p.get("consultation") or []:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            t, m_top = top.get(_kennung(c.get("agendaItem")), (None, None))
            m = sitzung.get(_kennung(c.get("meeting"))) or m_top
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
    Abbrüche nach `moegliche_sperre` zählen als Nacht mit möglicher Sperre, Abbrüche der Art `liste` oder `adresse` als
    Nacht mit fehlerhafter Liste. Programmfehler werden vermerkt und brechen laut ab (kein Sperrverdacht)."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    # Sperre und Zeitfenster sind kein Ausfall: der Lauf wird übersprungen, ohne den Stand als fehlgeschlagen zu markieren
    lokal = abruf.lokal(config.OPARL_BODY)
    grund = ("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (RATSATLAS_STADT_INFORMIERT)"
             if not abruf.freigegeben(config.OPARL_BODY) else
             f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr" if not lokal and not abruf.im_zeitfenster()
             else None)
    zustand = {}
    if not grund:
        try:
            zustand = _zustand_pruefen()
        except ZustandUnlesbar as e:   # keine Anfrage; laut, bis jemand die Datei prüft
            _stand_setzen(abruf_fehler={"zeit": _now(), "meldung": str(e)[:300]})
            raise
        grund = _pause_grund(zustand, lokal)
    if grund:
        _stand_setzen(abruf_uebersprungen={"zeit": _now(), "grund": grund})
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
        _zustand_setzen("listenfehler", None)
    except (abruf.Abbruch, RuntimeError) as e:
        _abbruch_vermerken(e, zustand)
    except Exception as e:
        # Programmfehler (auch eine unerwartete Form tief in einem Objekt): kein Sperrverdacht; vermerken und mit
        # Traceback abbrechen, damit der Fehler im Workflow sichtbar wird
        _stand_setzen(abruf_fehler={"zeit": _now(), "meldung": f"Programmfehler ({type(e).__name__}: {e})"[:300]})
        raise


def _abbruch_vermerken(e, zustand):
    """Abbruch vermerken: zuerst die Zähler im Zustand (Nacht mit möglicher Sperre nach `moegliche_sperre`, Nacht mit
    fehlerhafter Liste nach LISTENFEHLER), dann STAND.json."""
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    art = getattr(e, "art", "")
    if moegliche_sperre(e):
        verdacht = zustand.get("sperre_verdacht") or {}
        _zustand_setzen("sperre_verdacht", {
            "naechte": verdacht.get("naechte", 0) + 1, "zuletzt": jetzt,
            "art": art, "code": getattr(e, "code", None), "meldung": str(e)[:300]})
    hinweis = None
    if art in LISTENFEHLER:
        naechte = (zustand.get("listenfehler") or {}).get("naechte", 0) + 1
        _zustand_setzen("listenfehler", {"naechte": naechte, "zuletzt": jetzt, "art": art, "meldung": str(e)[:300]})
        hinweis = (f"Abbruch wegen einer fehlerhaften Liste ({art}), {naechte}. Nacht ohne vollständigen Lauf; keine "
                   f"Fortsetzung, jede Nacht beginnt der Vollabruf von vorn. Nach {LISTENFEHLER_NAECHTE} Nächten "
                   f"{LISTENFEHLER_PAUSE.days} Tage Pause. {e}")[:400]
        _warnung(hinweis)
    werte = {"abruf_fehler": {"zeit": _now(), "meldung": str(e)[:300]}}
    if hinweis:
        werte["abruf_hinweis"] = {"zeit": _now(), "meldung": hinweis}
    _stand_setzen(**werte)
    print(f"Abruf abgebrochen, letzter gültiger Stand bleibt: {e}")
    if os.environ.get("RATSATLAS_STRENG") == "ja":
        raise e
