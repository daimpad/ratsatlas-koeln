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
Schutz gegen Endlosschleifen: Abbruch, wenn links.next auf eine in diesem Lauf gelesene Seite zeigt, eine Seite nur
Kennungen bringt, die in diesem Lauf schon kamen, eine Seite keine neuen Kennungen bringt (in einer Fortsetzung bis zur
erlaubten Seitenverschiebung, siehe unten), mehr als
`config.ABRUF_MAX_SEITEN` Seiten in einem Lauf folgen (eine Fortsetzung zählt neu) oder ein Vollabruf über seine
Fortsetzungen hinweg mehr als `config.ABRUF_MAX_SEITEN_FAKTOR` × `config.ABRUF_MAX_SEITEN` Seiten erreicht (Art
`liste`).
Ende der Liste: `links` oder `links.next` fehlt oder ist leer (null, "", [], {}; SessionNet ist PHP). Ob der Server
den Filter anwendet, wird je Lauf geprüft und in der Abrufstatistik vermerkt.

Ein Vollabruf, der am Ende des Zeitfensters oder durch einen Fehler abbricht, wird in der nächsten Nacht fortgesetzt
(`<liste>_fortsetzung` im Zustand mit dem Zeitpunkt `gespeichert`, Teilstand in `<datei>.teil.jsonl`), und zwar eine
Seite vor der Stelle, an der er abbrach (eine Anfrage mehr): Wurden zwischen den Nächten bis zu einer Seite (25)
gelesener Vorlagen gelöscht, rücken die folgenden nach vorn und gingen sonst verloren; bei mehr Löschungen können
Vorlagen bis zum nächsten Vollabruf fehlen. Köln liefert die Vorlagen neueste zuerst und ohne Gesamtzahlen (Stufe 1,
07.11.2026): Neue Vorlagen zwischen zwei Nächten verschieben die Seiten nach hinten, Seiten der Fortsetzung bringen dann
schon gelesene Vorlagen (zusammengeführt über die Kennung; die wiederholte Seite zählt ebenso). Solche Seiten gelten
bis zur erlaubten Seitenverschiebung nicht als Schleife: 4 Seiten je angefangenem Tag seit `gespeichert`, höchstens 40
(`verschiebung_erlaubt`; nach ausgelassenen Nächten, sieben Tagen Pause oder einem Retry-After entsprechend mehr), bei
25 je Seite also rund 100 (genauer 99: die wiederholte Seite zählt mit) neue Vorlagen je Tag. Bricht eine Fortsetzung
ab, bevor sie die verschobene Zone verlassen hat, bleibt `gespeichert` (die Verschiebung seit dann besteht weiter;
ein künftiger Wert gilt als jetzt), sonst gilt der neue Zeitpunkt. Verlassen ist die Zone erst mit einer ungelesenen
Vorlage, deren `created` älter ist als das der ältesten gelesenen (neueste zuerst heißt in Köln `created` absteigend:
neue Vorlagen sind jünger, der ungelesene Rest ist älter). So zählen nach langer Pause auch zwei Strecken gelesener
Seiten (aus der Vornacht und aus der ersten Nacht, dazwischen neue Vorlagen) zur Zone, und überwiegen Löschungen die
neuen Vorlagen, ist sie gleich mit der ersten Seite verlassen. Ohne lesbares `created` (mit Zone) bleibt
`gespeichert`. Die neuen Vorlagen am Listenanfang holt der nächste inkrementelle Lauf (modified_since ab dem Start des
Vollabrufs).
Zwischen den Nächten gelöschte, schon gelesene Vorlagen bleiben bis zum nächsten Vollabruf bzw. bis zu ihrem Eintrag
mit `deleted` aus modified_since im Stand. Keine
Fortsetzung nach einem Abbruch der Art `liste` (Schleife in links.next), `weiterleitung`, `proxy` oder `adresse`
(ungültige Adresse): Der nächste Lauf beginnt von vorn. Eine unlesbare Fortsetzung (auch eine fehlende oder unlesbare
Teildatei) wird verworfen und gemeldet; der Vollabruf beginnt dann von vorn.

Nacht mit möglicher Sperre (`moegliche_sperre`, Zähler `sperre_verdacht` im Zustand): Zeitüberschreitung,
Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht (Art `sperre`), HTTP 401,
403 oder 429 (Art `http`), `aufgegeben` nach 429, 5xx, unlesbarer Antwort oder CONNECT-Antwort 429/503 (auch sofort,
wenn die Pause nicht mehr ins Zeitfenster passt oder Retry-After zu lang oder unlesbar ist, abruf.py), außerdem
vorsichtshalber eine Weiterleitung (etwa auf die Sperrseite einer Firewall) und gültiges JSON in unerwarteter Form
(Art `unlesbar`: kein Objekt, Body ohne Listen, Seite ohne Liste `data` oder mit einem nicht leeren `links`, das kein
Objekt ist). Nach drei solchen Nächten ohne vollständigen Lauf dazwischen pausiert der Abruf sieben Tage; ein
vollständiger Lauf setzt den Zähler zurück. Nicht: Ablehnung durch den Proxy der Ausführungsumgebung (`proxy`),
ungültige Adressen (`adresse`) und eine gescheiterte Zertifikatsprüfung (`tls`, vermutlich eine Einstellung der
Ausführungsumgebung; ein Zertifikat der Gegenseite oder eine Sperrseite ist nicht ausgeschlossen), denn diese Anfragen
haben die Stadt nicht als HTTP-Anfrage erreicht, sowie ein Vollabruf deutlich kleiner als der vorhandene Stand (Art
`leer`, Regel aus Bonn: weniger als 90 %). Nächte mit `tls` zählt `tlsfehler` (wie `listenfehler`, Warnung im Log):
nach drei solchen Nächten ohne vollständigen Lauf dazwischen sieben Tage Pause.
Nach jedem Abbruch außer dem Ende des Zeitfensters (auch nach `proxy`, `adresse`, Programm- und Einstellungsfehlern)
folgt in derselben Nacht (12 Stunden, `SPERRE_GLEICHE_NACHT`) kein weiterer Lauf, etwa nach einem Push oder auf
Knopfdruck (`letzter_abbruch` im Zustand; nicht für lokale Testserver).
Retry-After über die Nacht hinaus: Gibt abruf.py wegen eines Retry-After auf, steht `nicht_vor` im Zustand (höchstens
30 Tage, unlesbarer Retry-After 7 Tage); bis dahin wird jeder Lauf übersprungen.
Abbrüche der Art `liste` oder `adresse` (dauerhaft ungültiges links.next oder Schleife: jede Nacht ein Vollabruf bis
zur selben Stelle) zählt `listenfehler` im Zustand (Nächte, nicht Läufe: ein weiterer Abbruch innerhalb von 12
Stunden zählt nicht noch einmal): Hinweis in STAND.json (`abruf_hinweis`) und Warnung im Log des Workflows; nach drei
solchen Nächten ohne vollständigen Lauf dazwischen sieben Tage Pause.
Der Zustand wird vor der ersten Anfrage geprüft: Ist die Datei oder ein Zeitpunkt des letzten Abrufs einer Liste
unlesbar, bricht der Lauf ohne Anfrage laut ab (`ZustandUnlesbar`; so jeder Lauf, bis die Datei geprüft ist). Ein
unlesbarer, zonenloser oder künftiger Zeitpunkt des letzten Sperrverdachts, Listenfehlers oder Abbruchs gilt als
„jetzt“ (in dieser Nacht kein Abruf), eine unlesbare Zahl der Nächte als drei, ein unlesbares `nicht_vor` als jetzt +
7 Tage, eines mehr als 30 Tage voraus als jetzt + 30 Tage; alles wird neu geschrieben und gemeldet. Eine unlesbare
STAND.json wird als `STAND.json.defekt` beiseitegelegt.
Programm- und Einstellungsfehler (etwa eine unerwartete Form tief in einem Objekt, ein RuntimeError ohne Art, ein
Zeilenumbruch im User-Agent) zählen nicht als Sperrverdacht: Sie stehen in STAND.json und brechen den Lauf mit
Traceback ab.
Fällt der Abruf aus, bleibt der letzte gültige Stand; der Fehler steht in `STAND.json` (`abruf_fehler`). Ein
vollständiger Lauf entfernt `abruf_fehler`, `abruf_hinweis` und `abruf_uebersprungen`. Das Ende des Zeitfensters
(etwa bei einem Vollabruf über mehrere Nächte) ist kein Fehler: neutraler Hinweis in `abruf_hinweis`, ein älteres
`abruf_fehler` entfällt. Den Zustand sichert pages.yml gleich nach dem Abrufschritt, auch wenn ein späterer Schritt
scheitert.

Abrufstatistik (`abrufstatistik.tsv`, Spalten STAT_SPALTEN): je Liste eine Zeile und eine Zeile `body` für den Abruf
des Bodys; Zähler aus abruf.statistik() als Differenz je Zeile, darunter `weiterleitungen` und `proxy`.
"""
import csv
import json
import math
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
# Nächte mit gescheiterter Zertifikatsprüfung (Zähler `tlsfehler`), danach Pause
TLS_NAECHTE = 3
TLS_PAUSE = timedelta(days=7)
# Listen mit Zeitpunkt des letzten Abrufs im Zustand
LISTEN = ("organizations", "papers", "meetings")
# Seiten ohne neue Kennungen in einer Fortsetzung, die als Seitenverschiebung gelten (neueste zuerst): je angefangenem
# Tag seit dem Speichern der Fortsetzung 4 Seiten, bei 25 je Seite rund 100 (genauer 99, die wiederholte Seite zählt
# mit) neue Vorlagen je Tag (Stufe 1: auf der ersten Seite 25 Vorlagen mit Datum 03. bis 06.11.2026), höchstens 40
# Seiten; ohne lesbaren Zeitpunkt 4. Danach gilt die Seite als Schleife.
VERSCHIEBUNG_JE_TAG = 4
VERSCHIEBUNG_HOECHSTENS = 40


class ZustandUnlesbar(RuntimeError):
    """zustand_abruf.json oder ein Zeitpunkt darin ist unlesbar: keine Anfrage, bis die Datei geprüft ist."""


def moegliche_sperre(fehler):
    """Zählt dieser Abbruch als Nacht mit möglicher Sperre? Art `sperre` (Zeitüberschreitung, Verbindungsabbruch,
    abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht), `aufgegeben` (nach 429, 5xx, unlesbarer
    Antwort oder CONNECT-Antwort 429/503) und `http` mit 401, 403 oder 429. Nicht: proxy (Ablehnung in der
    Ausführungsumgebung), tls (Zertifikatsprüfung gescheitert), liste, adresse, andere HTTP-Codes (z. B. 404). Eine
    Weiterleitung (etwa auf die Sperrseite einer vorgeschalteten Firewall) und eine unerwartete Antwortform
    (`unlesbar`) zählen vorsichtshalber mit."""
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
    except (ValueError, RecursionError) as e:   # auch UnicodeDecodeError und zu tief verschachtelt
        raise ZustandUnlesbar(f"{config.ZUSTAND.name} unlesbar ({e}); keine Anfrage an die Stadt, bis die Datei geprüft "
                              "oder entfernt ist (ohne Datei: Vollabruf, Zähler der Nächte verloren)") from e
    if not isinstance(z, dict):
        raise ZustandUnlesbar(f"{config.ZUSTAND.name} ist kein JSON-Objekt; keine Anfrage an die Stadt, bis die Datei "
                              "geprüft ist")
    return z


def _zustand_aendern(**werte):
    """Setzt Werte im Zustand (ein Schreibvorgang); None entfernt den Schlüssel."""
    z = _zustand()
    for schluessel, wert in werte.items():
        if wert is None:
            z.pop(schluessel, None)
        else:
            z[schluessel] = wert
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.ZUSTAND, json.dumps(z, ensure_ascii=False, indent=1) + "\n")


def _zustand_setzen(schluessel, wert):
    _zustand_aendern(**{schluessel: wert})


def _zaehler_pruefen(z, schluessel, grenze, jetzt):
    """Zähler der Nächte (`sperre_verdacht`, `listenfehler`) und den letzten Abbruch (`letzter_abbruch`, `grenze`
    None: ohne Zahl der Nächte) vorsichtig lesen: unlesbarer, zonenloser oder künftiger Zeitpunkt `zuletzt` → jetzt (in
    dieser Nacht kein Abruf); unlesbare Zahl der Nächte → `grenze` (Pause). Liefert den Eintrag und die Meldungen zu
    ersetzten Werten."""
    v = z.get(schluessel)
    if not v:
        return {}, []
    meldungen = []
    if not isinstance(v, dict):
        meldungen.append(f"{schluessel} ist kein Objekt ({v!r})")
        v = {}
    v = dict(v)
    n = v.get("naechte")
    if grenze is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 0):
        meldungen.append(f"{schluessel}.naechte unlesbar ({n!r}), gilt als {grenze}")
        v["naechte"] = grenze
    zuletzt = _zeit(v.get("zuletzt"))
    if zuletzt is None or zuletzt > jetzt:
        grund = "in der Zukunft" if zuletzt is not None else "unlesbar oder ohne Zone"
        meldungen.append(f"{schluessel}.zuletzt {grund} ({v.get('zuletzt')!r}), gilt als jetzt")
        v["zuletzt"] = jetzt.isoformat(timespec="seconds")
    return v, meldungen


def _nicht_vor_pruefen(wert, jetzt):
    """Zeitpunkt aus einem Retry-After (`nicht_vor`) vorsichtig lesen: unlesbar, ohne Zone oder Zahl → jetzt + 7 Tage;
    mehr als 30 Tage in der Zukunft → jetzt + 30 Tage (wie beim Speichern begrenzt). Liefert (Wert, Meldung)."""
    if wert is None:
        return None, ""
    t = _zeit(wert)
    if t is None:
        neu = (jetzt + abruf.RETRY_AFTER_UNLESBAR).isoformat(timespec="seconds")
        return neu, f"nicht_vor unlesbar oder ohne Zone ({wert!r}), gilt als {neu}"
    if t > jetzt + abruf.RETRY_AFTER_HOECHSTENS:
        neu = (jetzt + abruf.RETRY_AFTER_HOECHSTENS).isoformat(timespec="seconds")
        return neu, (f"nicht_vor mehr als {abruf.RETRY_AFTER_HOECHSTENS.days} Tage in der Zukunft ({wert!r}), gilt "
                     f"als {neu}")
    return wert, ""


def _zustand_pruefen():
    """Vor der ersten Anfrage: Zustand lesen und prüfen (siehe Moduldoku). Liefert den Zustand mit geprüften Zählern."""
    z = _zustand()
    for liste in LISTEN:
        if liste in z and _zeit(z[liste]) is None:
            raise ZustandUnlesbar(f"Zeitpunkt des letzten Abrufs von {liste} in {config.ZUSTAND.name} unlesbar oder "
                                  f"ohne Zone ({z[liste]!r}); keine Anfrage an die Stadt, bis der Wert geprüft ist")
    jetzt = abruf.uhr()
    neu, meldungen = {}, []
    for schluessel, grenze in (("sperre_verdacht", SPERRE_NAECHTE), ("listenfehler", LISTENFEHLER_NAECHTE),
                               ("tlsfehler", TLS_NAECHTE), ("letzter_abbruch", None)):
        v, m = _zaehler_pruefen(z, schluessel, grenze, jetzt)
        if m:
            neu[schluessel] = v
            meldungen += m
    v, m = _nicht_vor_pruefen(z.get("nicht_vor"), jetzt)
    if m:
        neu["nicht_vor"] = v
        meldungen.append(m)
    if neu:
        z.update(neu)
        _zustand_aendern(**neu)
        _warnung(f"{config.ZUSTAND.name}: " + "; ".join(meldungen) + " (neu geschrieben)")
    return z


def _pause_grund(z, lokal):
    """Grund, den Lauf ohne Anfrage zu überspringen (12-Stunden-Regel nach jedem Abbruch, Retry-After über die Nacht
    hinaus, Pausen nach drei Nächten), sonst None. 12-Stunden-Regel und Retry-After gelten nicht für lokale Testserver."""
    jetzt = abruf.uhr()
    verdacht = z.get("sperre_verdacht") or {}
    if verdacht and not lokal:
        # nach einer Nacht mit möglicher Sperre in derselben Nacht kein weiterer Lauf (z. B. Push oder Knopfdruck)
        seit = jetzt - _zeit(verdacht["zuletzt"])
        if seit < SPERRE_GLEICHE_NACHT:
            return (f"möglicher Sperrverdacht vor {int(seit.total_seconds() // 60)} Minuten; in derselben Nacht kein "
                    "weiterer Abruf")
    letzter = z.get("letzter_abbruch") or {}
    if letzter and not lokal:
        # nach jedem anderen Abbruch (außer dem Ende des Zeitfensters), auch nach einem Programmfehler, ebenso
        seit = jetzt - _zeit(letzter["zuletzt"])
        if seit < SPERRE_GLEICHE_NACHT:
            return (f"Abbruch ({letzter.get('art') or 'unbekannt'}) vor {int(seit.total_seconds() // 60)} Minuten; in "
                    "derselben Nacht kein weiterer Abruf")
    nicht_vor = _zeit(z.get("nicht_vor"))
    if nicht_vor is not None and not lokal and jetzt < nicht_vor:
        return (f"Retry-After der Stadt: kein Abruf vor {nicht_vor.isoformat(timespec='minutes')} "
                f"(höchstens {abruf.RETRY_AFTER_HOECHSTENS.days} Tage)")
    if verdacht.get("naechte", 0) >= SPERRE_NAECHTE:
        bis = _zeit(verdacht["zuletzt"]) + SPERRE_PAUSE
        if jetzt < bis:
            return (f"Abruf pausiert bis {bis.date().isoformat()}: {verdacht['naechte']} Nächte in Folge mit möglicher "
                    "Sperre (Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, HTTP 401/403/429, Weiterleitung "
                    "oder aufgegeben nach 429/5xx); bitte Kontakt zur Stadt aufnehmen")
    for schluessel, grenze, pause, grund in (
            ("listenfehler", LISTENFEHLER_NAECHTE, LISTENFEHLER_PAUSE, "Abbruch wegen einer fehlerhaften Liste "
             "(ungültige Folgeadresse in links.next oder Schleife); bitte die Liste prüfen"),
            ("tlsfehler", TLS_NAECHTE, TLS_PAUSE, "Zertifikatsprüfung fehlgeschlagen (vermutlich Einstellung der "
             "Ausführungsumgebung; Zertifikat der Gegenseite oder Sperrseite nicht ausgeschlossen); bitte prüfen")):
        fehler = z.get(schluessel) or {}
        if fehler.get("naechte", 0) >= grenze:
            bis = _zeit(fehler["zuletzt"]) + pause
            if jetzt < bis:
                return f"Abruf pausiert bis {bis.date().isoformat()}: {fehler['naechte']} Nächte in Folge {grund}"
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
    except (ValueError, RecursionError) as e:
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


def _stand_entfernen(*schluessel):
    """Entfernt Einträge aus STAND.json (etwa `abruf_fehler` nach einem vollständigen Lauf)."""
    s = _stand()
    if any(k in s for k in schluessel):
        for k in schluessel:
            s.pop(k, None)
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
    """Abbruch mitten in einer Liste; trägt den gelesenen Teil für die Fortsetzung (`zuletzt`: die zuletzt gelesene
    Seite, dort beginnt die Fortsetzung; `verlassen`: eine Fortsetzung hat die verschobene Zone verlassen, also eine
    ungelesene Vorlage gelesen, die älter ist als die älteste schon gelesene)."""

    def __init__(self, ursache, objekte, naechste, seiten, zuletzt=None, verlassen=False):
        super().__init__(str(ursache), getattr(ursache, "art", ""), getattr(ursache, "ziel", ""),
                         getattr(ursache, "code", None), getattr(ursache, "nicht_vor", None))
        self.objekte, self.naechste, self.seiten, self.zuletzt = objekte, naechste, seiten, zuletzt
        self.verlassen = verlassen


def verschiebung_erlaubt(gespeichert, jetzt=None):
    """Seiten ohne neue Kennungen, die in einer Fortsetzung als Seitenverschiebung gelten: VERSCHIEBUNG_JE_TAG je
    angefangenem Tag seit `gespeichert` (Zeitpunkt der Fortsetzung), höchstens VERSCHIEBUNG_HOECHSTENS; fehlt der
    Zeitpunkt, ist er unlesbar oder künftig: VERSCHIEBUNG_JE_TAG."""
    t, jetzt = _zeit(gespeichert), jetzt or abruf.uhr()
    if t is None or t > jetzt:
        return VERSCHIEBUNG_JE_TAG
    tage = max(1, math.ceil((jetzt - t) / timedelta(days=1)))
    return min(VERSCHIEBUNG_JE_TAG * tage, VERSCHIEBUNG_HOECHSTENS)


def _erstellt(objekt):
    """`created` eines Objekts als Zeitpunkt mit Zone; None, wenn es fehlt, unlesbar oder ohne Zone ist."""
    return _zeit(objekt.get("created"))


def _leer(wert):
    """Leerer Wert (null, "", [], {}): SessionNet ist in PHP geschrieben, ein leeres Objekt kann als [] ankommen."""
    return wert is None or (isinstance(wert, (str, list, dict)) and not wert)


def _seite_pruefen(seite, url):
    """Form einer Listenseite, geprüft dort, wo sie ankommt: `data` ist eine Liste von Objekten mit Kennung (Text),
    `links` fehlt, ist leer (wie fehlend) oder ein Objekt, `links.next` fehlt, ist leer (Ende der Liste) oder Text.
    Liefert die Folgeadresse oder None (Ende). Sonst Abbruch der Art `unlesbar` (gültiges JSON in unerwarteter Form,
    etwa ein nicht leeres links, das kein Objekt ist: keine Wiederholung, zählt als Nacht mit möglicher Sperre)."""
    daten, links = seite.get("data"), seite.get("links")
    if not isinstance(daten, list) or not all(isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"]
                                              for o in daten):
        grund = "data ist keine Liste von Objekten mit Kennung"
    elif _leer(links):
        return None
    elif not isinstance(links, dict):
        grund = "links ist kein Objekt"
    elif _leer(links.get("next")):
        return None
    elif isinstance(links["next"], str):
        return links["next"]
    else:
        grund = "links.next ist kein Text"
    raise abruf.Abbruch(f"unerwartete Antwortform ({grund}): {url}", "unlesbar")


def liste(url, seit=None, start=None, objekte=None, seiten=0, verschiebung=VERSCHIEBUNG_JE_TAG):
    """Alle Objekte einer OParl-Liste über links.next; `seit` setzt modified_since. `start`, `objekte` und `seiten`
    setzen einen abgebrochenen Vollabruf fort. Liefert (Objekte, Seiten); ein Abbruch kommt als Teilabbruch. `seiten`
    zählt die Seiten insgesamt (Statistik, Fortsetzung); die Grenze `config.ABRUF_MAX_SEITEN` gilt je Lauf, sonst
    erreichte ein großer Vollabruf sie in einer späteren Nacht und begänne von vorn. Über die Fortsetzungen hinweg gilt
    die Gesamtgrenze `config.ABRUF_MAX_SEITEN_FAKTOR` × `config.ABRUF_MAX_SEITEN` (Liste, die endlos neue Kennungen
    erzeugt). In einer Fortsetzung (`start`) gelten bis zu `verschiebung` Seiten ohne neue Kennungen als
    Seitenverschiebung (neue Vorlagen am Listenanfang, wiederholte erste Seite), nicht als Schleife; eine Seite, deren
    Kennungen alle schon in diesem Lauf kamen, und eine wiederholte Adresse bleiben eine Schleife. Ein Teilabbruch
    vermerkt, ob die Fortsetzung die verschobene Zone verlassen hat (`verlassen`, für `gespeichert`): erst mit einer
    ungelesenen Vorlage, deren `created` älter ist als das der ältesten gelesenen (ohne lesbares `created` nie)."""
    naechste = start or _mit_parametern(url, modified_since=seit, limit=config.ABRUF_SEITENGROESSE)
    objekte = list(objekte or [])
    ids, gesehen, dieser_lauf = {o.get("id") for o in objekte}, set(), set()
    verschoben, zuletzt = 0, None   # Seiten ohne neue Kennungen in einer Fortsetzung; zuletzt gelesene Seite
    # Fortsetzung: älteste gelesene Vorlage (created); eine ungelesene ältere liegt hinter der verschobenen Zone
    grenze = min((t for t in map(_erstellt, objekte) if t is not None), default=None) if start else None
    verlassen = False
    gesamt = config.ABRUF_MAX_SEITEN_FAKTOR * config.ABRUF_MAX_SEITEN
    while naechste:
        try:
            if naechste in gesehen:   # Schutz gegen zyklische Verweise
                raise abruf.Abbruch(f"links.next zeigt auf eine bereits gelesene Seite: {naechste}", "liste")
            if len(gesehen) >= config.ABRUF_MAX_SEITEN:   # Seiten dieses Laufs
                raise abruf.Abbruch(f"mehr als {config.ABRUF_MAX_SEITEN} Seiten in einem Lauf (RATSATLAS_MAX_SEITEN)",
                                    "liste")
            if seiten >= gesamt:   # Seiten insgesamt, auch aus früheren Läufen (Fortsetzung)
                raise abruf.Abbruch(f"mehr als {gesamt} Seiten insgesamt über Fortsetzungen hinweg "
                                    f"({config.ABRUF_MAX_SEITEN_FAKTOR} × RATSATLAS_MAX_SEITEN); die Liste erzeugt "
                                    "womöglich endlos neue Kennungen", "liste")
            gesehen.add(naechste)
            seite = abruf.get_json(naechste)
            weiter = _seite_pruefen(seite, naechste)
        except abruf.Abbruch as e:
            raise Teilabbruch(e, objekte, naechste, seiten, zuletzt, verlassen) from e
        seiten += 1
        daten = seite["data"]
        kennungen = {o["id"] for o in daten}
        neu = [o for o in daten if o["id"] not in ids]
        if daten and not neu:
            if not start or kennungen <= dieser_lauf:   # dieselben Objekte mit neuem links.next (SessionNet-Sammelserver)
                grund = f"Seite ohne neue Kennungen, links.next läuft im Kreis: {naechste}"
            elif verschoben >= verschiebung:
                grund = (f"mehr als {verschiebung} Seiten ohne neue Kennungen in der Fortsetzung (erlaubte "
                         f"Seitenverschiebung): {naechste}")
            else:
                grund = None
                verschoben += 1   # Fortsetzung: die Seiten sind durch neue Vorlagen am Listenanfang verschoben
            if grund:
                raise Teilabbruch(abruf.Abbruch(grund, "liste"), objekte, None, seiten, zuletzt, verlassen)
        elif grenze is not None and any((t := _erstellt(o)) is not None and t < grenze for o in neu):
            verlassen = True
        dieser_lauf |= kennungen
        ids.update(o.get("id") for o in neu)
        objekte += neu
        zuletzt, naechste = naechste, weiter
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
        try:
            _guard(pfad.name, len(neu_objekte), len(alt))
        except RuntimeError as e:   # Vollabruf deutlich kleiner als der vorhandene Stand: Abbruch, keine Sperre
            raise abruf.Abbruch(str(e), "leer") from e
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
        except (ValueError, RecursionError) as e:
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
            objekte, seiten = liste(url, start=fort["naechste"], objekte=bisher, seiten=fort.get("seiten", 0),
                                    verschiebung=verschiebung_erlaubt(fort.get("gespeichert")))
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
        # Vollabruf: gelesenen Teil sichern und morgen eine Seite zurück fortsetzen (fängt bis zu einer Seite
        # Löschungen ab); eine veraltete Folgeseite (HTTP 4xx gleich zu Beginn der Fortsetzung) oder ein Abbruch aus
        # OHNE_FORTSETZUNG (Schleife, Weiterleitung, Proxy, Adresse) verwirft die Fortsetzung, dann beginnt der
        # nächste Lauf von vorn
        veraltet = fort and e.art == "http" and e.seiten == fort.get("seiten", 0)
        verwerfen = veraltet or e.art in OHNE_FORTSETZUNG
        if not seit and e.naechste and e.seiten and not verwerfen:
            config.RAW.mkdir(parents=True, exist_ok=True)
            _write(_teil(pfad), "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in e.objekte))
            # `gespeichert` bleibt, solange eine Fortsetzung die verschobene Zone nicht verlassen hat (keine ungelesene
            # Vorlage, älter als die älteste gelesene): Die Verschiebung seit der ersten Speicherung besteht weiter;
            # ein künftiger Wert gilt als jetzt
            jetzt = abruf.uhr()
            alt = _zeit(fort.get("gespeichert")) if fort else None
            gespeichert = fort["gespeichert"] if alt is not None and alt <= jetzt and not e.verlassen else (
                jetzt.isoformat(timespec="seconds"))
            _zustand_setzen(f"{schluessel}_fortsetzung", {
                "naechste": e.zuletzt or e.naechste, "seiten": e.seiten, "start": start.isoformat(timespec="seconds"),
                "gespeichert": gespeichert})
            zeile["ergebnis"] = f"unterbrochen nach {e.seiten} Seiten, Fortsetzung im nächsten Lauf: {e}"[:300]
        else:
            if verwerfen:
                _zustand_setzen(f"{schluessel}_fortsetzung", None)
                _teil(pfad).unlink(missing_ok=True)
            zeile["ergebnis"] = f"abbruch: {e}"[:300]
        zeile.update(seiten=e.seiten, objekte=len(e.objekte))
        raise
    except abruf.Abbruch as e:
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
    except abruf.Abbruch as e:
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
    if len(zeilen) < MIN_ANTEIL * _jsonl_count(config.BERATUNGEN):   # unvollständig: Abbruch, keine Sperre
        raise abruf.Abbruch(f"Beratungen: nur {len(zeilen)} statt bisher {_jsonl_count(config.BERATUNGEN)}", "leer")
    _write(config.BERATUNGEN, "".join(json.dumps(z, ensure_ascii=False) + "\n" for z in zeilen))
    # Ergänzte Organisationen in papers.jsonl übernehmen, damit build.py sie liest
    _write(config.PAPERS, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in papers))
    _stamp("consultations_lite")
    print(f"{len(zeilen)} Beratungen mit Sitzung oder TOP, {ohne_sitzung} ohne, {ergaenzt} Gremien aus der Sitzung")


def fetch_all():
    """Vollständiger bzw. inkrementeller Lauf. Ein Abbruch (abruf.Abbruch) hält den letzten gültigen Stand und vermerkt
    den Fehler; Abbrüche nach `moegliche_sperre` zählen als Nacht mit möglicher Sperre, Abbrüche der Art `liste` oder
    `adresse` als Nacht mit fehlerhafter Liste, das Ende des Zeitfensters nur als Hinweis. Alles andere (auch ein
    RuntimeError ohne Art) ist ein Programm- oder Einstellungsfehler: vermerkt, laut mit Traceback, kein Sperrverdacht.
    Nach jedem Abbruch außer dem Ende des Zeitfensters folgt in derselben Nacht kein weiterer Lauf (`letzter_abbruch`)."""
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
        except ZustandUnlesbar as e:   # keine Anfrage; laut, bis jemand die Datei prüft (jeder Lauf bricht so ab)
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
        _zustand_aendern(sperre_verdacht=None, listenfehler=None, tlsfehler=None, letzter_abbruch=None, nicht_vor=None)
        # Meldungen früherer Läufe gelten nicht mehr (die Seite zeigte sonst dauerhaft „fehlgeschlagen“)
        _stand_entfernen("abruf_fehler", "abruf_hinweis", "abruf_uebersprungen")
    except abruf.Abbruch as e:
        _abbruch_vermerken(e, zustand)
    except Exception as e:
        # Programm- oder Einstellungsfehler (auch eine unerwartete Form tief in einem Objekt, ein RuntimeError ohne Art
        # wie RecursionError oder ZustandUnlesbar mitten im Lauf): kein Sperrverdacht; vermerken und mit Traceback
        # abbrechen, damit der Fehler im Workflow sichtbar wird. In derselben Nacht kein weiterer Lauf.
        try:
            _zustand_setzen("letzter_abbruch", {"zuletzt": abruf.uhr().isoformat(timespec="seconds"),
                                                "art": "programmfehler", "code": None,
                                                "meldung": f"{type(e).__name__}: {e}"[:300]})
        except Exception as f:   # z. B. Zustand unlesbar: den eigentlichen Fehler nicht verdrängen
            _warnung(f"Abbruch nicht im Zustand vermerkt ({type(f).__name__}: {f})")
        _stand_setzen(abruf_fehler={"zeit": _now(), "meldung": f"Programmfehler ({type(e).__name__}: {e})"[:300]})
        raise


def _naechte_zaehlen(zustand, schluessel, jetzt, eintrag, neu):
    """Nächte zählen, nicht Läufe (`listenfehler`, `tlsfehler`): Ein weiterer Abbruch innerhalb von 12 Stunden zählt
    nicht noch einmal. Setzt beim Zählen neu[schluessel]; liefert die Zahl der Nächte."""
    bisher = zustand.get(schluessel) or {}
    zuletzt = _zeit(bisher.get("zuletzt"))
    if zuletzt is not None and jetzt - zuletzt < SPERRE_GLEICHE_NACHT:
        return bisher.get("naechte", 1)
    neu[schluessel] = {"naechte": bisher.get("naechte", 0) + 1, **eintrag}
    return neu[schluessel]["naechte"]


def _abbruch_vermerken(e, zustand):
    """Abbruch vermerken: zuerst den Zustand (letzter Abbruch für die 12-Stunden-Regel, Nacht mit möglicher Sperre nach
    `moegliche_sperre`, Retry-After über die Nacht hinaus, Nacht mit fehlerhafter Liste nach LISTENFEHLER), dann
    STAND.json. Das Ende des Zeitfensters (etwa bei einem Vollabruf über mehrere Nächte) ist kein Fehler: nur ein
    neutraler Hinweis, keine 12-Stunden-Regel."""
    jetzt = abruf.uhr()
    zeit = jetzt.isoformat(timespec="seconds")
    art = getattr(e, "art", "")
    if art == "zeitfenster":
        hinweis = f"Das Zeitfenster endete während des Abrufs; Fortsetzung in der nächsten Nacht. {e}"[:400]
        _stand_entfernen("abruf_fehler")
        _stand_setzen(abruf_hinweis={"zeit": _now(), "meldung": hinweis})
        print(f"Abruf unterbrochen (Ende des Zeitfensters), Fortsetzung in der nächsten Nacht: {e}")
        return
    neu = {"letzter_abbruch": {"zuletzt": zeit, "art": art, "code": getattr(e, "code", None),
                               "meldung": str(e)[:300]}}
    eintrag = {"zuletzt": zeit, "art": art, "meldung": str(e)[:300]}
    if art == "tls":   # vermutlich Einstellung der Ausführungsumgebung, keine Sperrnacht: laut, damit sie behoben wird
        naechte = _naechte_zaehlen(zustand, "tlsfehler", jetzt, eintrag, neu)
        _warnung(f"Zertifikatsprüfung fehlgeschlagen ({naechte}. Nacht ohne vollständigen Lauf; nach {TLS_NAECHTE} "
                 f"Nächten {TLS_PAUSE.days} Tage Pause); vermutlich eine Einstellung der Ausführungsumgebung (CA eines "
                 f"Proxys), Zertifikat der Gegenseite oder Sperrseite nicht ausgeschlossen; in derselben Nacht kein "
                 f"weiterer Lauf. {e}"[:500])
    if moegliche_sperre(e):
        verdacht = zustand.get("sperre_verdacht") or {}
        neu["sperre_verdacht"] = {"naechte": verdacht.get("naechte", 0) + 1, "zuletzt": zeit, "art": art,
                                  "code": getattr(e, "code", None), "meldung": str(e)[:300]}
    nicht_vor = getattr(e, "nicht_vor", None)
    if nicht_vor is not None:   # Retry-After über die Nacht hinaus; ein späterer gespeicherter Zeitpunkt bleibt
        alt = _zeit(zustand.get("nicht_vor"))
        if alt is None or nicht_vor > alt:
            neu["nicht_vor"] = nicht_vor.isoformat(timespec="seconds")
    hinweis = None
    if art in LISTENFEHLER:
        naechte = _naechte_zaehlen(zustand, "listenfehler", jetzt, eintrag, neu)
        hinweis = (f"Abbruch wegen einer fehlerhaften Liste ({art}), {naechte}. Nacht ohne vollständigen Lauf; keine "
                   f"Fortsetzung, jede Nacht beginnt der Vollabruf von vorn. Nach {LISTENFEHLER_NAECHTE} Nächten "
                   f"{LISTENFEHLER_PAUSE.days} Tage Pause. {e}")[:400]
        _warnung(hinweis)
    _zustand_aendern(**neu)
    werte = {"abruf_fehler": {"zeit": _now(), "meldung": str(e)[:300]}}
    if hinweis:
        werte["abruf_hinweis"] = {"zeit": _now(), "meldung": hinweis}
    _stand_setzen(**werte)
    print(f"Abruf abgebrochen, letzter gültiger Stand bleibt: {e}")
    if os.environ.get("RATSATLAS_STRENG") == "ja":
        raise e
