"""Gedrosselter HTTP-Abruf für die Exploration (Abrufpolitik CLAUDE.md 5.1).

- genau eine Verbindung zur Zeit, mindestens ABSTAND Sekunden vom Ende einer Antwort bis zur nächsten Anfrage
  (Antworten aus dem Cache zählen nicht), auch über Prozessgrenzen: Die erste Netzanfrage eines Prozesses folgt
  frühestens ABSTAND Sekunden nach dem Import und frühestens ABSTAND Sekunden nach der letzten Netzanfrage laut
  _cache/abrufe.tsv (Zeit mit Zone, nach dem Ende der Antwort geschrieben; sekundengenau, daher 1 s Zuschlag)
- offener User-Agent mit Projektadresse; Kontakt über die Umgebungsvariable RATSATLAS_KONTAKT
- Wiederholung nur bei 429/5xx, mit wachsender Pause; 401/403/404 brechen sofort ab;
  RATSATLAS_WIEDERHOLUNGEN=0 bricht auch bei 429/5xx sofort ab (Messstufen: stoppen und berichten)
- RATSATLAS_MAX_DAUER (Sekunden): eine langsamere Antwort wird noch gespeichert, danach Abbruch
- RATSATLAS_MAX_ANFRAGEN: harte Obergrenze für Anfragen ans Netz je Prozess (Cache-Treffer zählen nicht)
- Weiterleitungen (3xx) werden nicht verfolgt: jede Weiterleitung ist genau eine Anfrage, wird mit Ziel-URL
  protokolliert und bricht ab (sonst kämen ungezählte Anfragen an einen anderen Host oder Pfad hinzu)
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (wie pipeline/abruf.py; explore/ergebnisse/sessionnet_befunde.tsv)
- Antwortet der Proxy der Arbeitsumgebung auf CONNECT nicht mit 200 („Tunnel connection failed: <Code>“), zählt der
  Code (Abbruch jeweils ohne Wiederholung):
  - 403, 405, 407 (Ablehnung durch eine Richtlinie oder fehlende Anmeldung) und HTTP 407: Die Anfrage hat den
    Zielserver nicht erreicht, kein Hinweis auf eine Sperre. Eigene Art `proxy`, Status `proxy <Code>` im Protokoll
    (nicht wiederholen, berichten). Ein HTTP 403 auf eine http-Adresse (ohne Tunnel) ist nicht von einer Antwort des
    Zielservers zu unterscheiden und bleibt `http`.
  - 429, 503 (Begrenzung oder Überlastung): Art `server` wie 429/5xx des Servers, aber immer ohne Wiederholung;
    Status `tunnel <Code>`
  - alle übrigen, vor allem 502 und 504 (der Proxy erreicht den Zielserver nicht): wie Zeitüberschreitung und
    Verbindungsabbruch Art `sperre` (mögliche Sperre), Status `tunnel <Code>`
- Rohdaten-Cache: jede Antwort wird unter explore/_cache/ abgelegt und beim nächsten Lauf nicht erneut abgerufen
- Protokoll jeder Anfrage (Zeit mit Zone, URL, Status, Bytes, Dauer, Netz oder Cache, Ziel einer Weiterleitung) in
  explore/_cache/abrufe.tsv
Für Anfragen an die Stadt setzt explore/oparl_messung.py strengere Vorgaben (keine Wiederholung, höchstens 5 s je
Antwort, Abstand mindestens 2 s, Obergrenze und Kontakt Pflicht); explore/geodaten.py erzwingt Abstand und
Wiederholungen ebenso.
Nur Standardbibliothek.
"""
import datetime as dt
import hashlib
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

CACHE = Path(os.environ.get("RATSATLAS_CACHE", Path(__file__).resolve().parent / "_cache"))
ABSTAND = float(os.environ.get("RATSATLAS_ABSTAND", "2.0"))
PAUSEN = [30, 120, 600, 1800]  # Sekunden; danach Abbruch. Für den Produktivbetrieb bis zu mehreren Stunden (Phase 2).
KONTAKT = os.environ.get("RATSATLAS_KONTAKT", "")
USER_AGENT = "ratsatlas-koeln-explore/0.1 (+https://github.com/daimpad/ratsatlas-koeln" + (f"; {KONTAKT}" if KONTAKT else "") + ")"
MAX_BYTES = 250 * 1024 * 1024
# harte Obergrenze für Anfragen ans Netz je Prozess (Cache zählt nicht); 0 = ohne Grenze
MAX_ANFRAGEN = int(os.environ.get("RATSATLAS_MAX_ANFRAGEN", "0"))
# Wiederholungen nach 429/5xx (Vorgabe: alle Pausen); 0 = sofortiger Abbruch
WIEDERHOLUNGEN = int(os.environ.get("RATSATLAS_WIEDERHOLUNGEN", str(len(PAUSEN))))
# höchste zulässige Antwortzeit in Sekunden; 0 = ohne Grenze
MAX_DAUER = float(os.environ.get("RATSATLAS_MAX_DAUER", "0"))
PROTOKOLL = CACHE / "abrufe.tsv"
PROTOKOLL_SPALTEN = ("zeit", "url", "status", "bytes", "dauer_s", "quelle", "ziel")
ZEITZONE = ZoneInfo("Europe/Berlin")
_anfragen = 0
_cache_treffer = 0
_kopf_geprueft = False

# Ende der letzten Antwort (time.monotonic); beim Import gesetzt, damit auch die erste Anfrage eines Prozesses
# frühestens ABSTAND Sekunden nach dem Start folgt
_letzte = time.monotonic()
_erste_netzanfrage = True   # vor der ersten Netzanfrage zählt zusätzlich die letzte Netzanfrage laut Protokoll
# Meldung von http.client, wenn der Proxy den Tunnel (CONNECT) nicht aufbaut
_TUNNEL = re.compile(r"Tunnel connection failed: (\d{3})")
# Antworten des Proxys auf CONNECT: Ablehnung durch eine Richtlinie oder fehlende Anmeldung (Art `proxy`) …
PROXY_ABLEHNUNG = (403, 405, 407)
# … Begrenzung oder Überlastung (Art `server`, ohne Wiederholung); alle übrigen Codes, vor allem 502 und 504 (der
# Proxy erreicht den Zielserver nicht), gelten wie Zeitüberschreitung und Verbindungsabbruch als mögliche Sperre
TUNNEL_SERVER = (429, 503)


class Abbruch(Exception):
    """Antwort, auf die nicht erneut angefragt wird. `art`: http (4xx, `code` gesetzt), server (429/5xx nach allen
    Wiederholungen; CONNECT-Antwort 429/503 sofort), sperre (Zeitüberschreitung, Verbindungsabbruch, übrige
    CONNECT-Antworten wie 502/504 mit `code`), proxy (Ablehnung durch den Proxy der Arbeitsumgebung: CONNECT-Antwort
    403/405/407 oder HTTP 407, `code` gesetzt), weiterleitung (3xx, `ziel` gesetzt), obergrenze, langsam, groesse."""

    def __init__(self, meldung, art="", code=None, ziel=""):
        super().__init__(meldung)
        self.art = art
        self.code = code
        self.ziel = ziel


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Weiterleitung: urllib meldet 3xx dann als HTTPError mit dem Location-Kopf."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OEFFNER = urllib.request.build_opener(_OhneWeiterleitung)


def tunnel_status(fehler):
    """Statuscode, mit dem ein Proxy den Tunnel (CONNECT) nicht aufgebaut hat (http.client meldet „Tunnel connection
    failed: 502 Bad Gateway“), sonst None."""
    if isinstance(fehler, urllib.error.HTTPError):
        return None
    m = _TUNNEL.search(str(fehler))
    return int(m.group(1)) if m else None


def proxy_ablehnung(fehler):
    """Statuscode, mit dem ein Proxy die Verbindung durch eine Richtlinie oder mangels Anmeldung abgelehnt hat, sonst
    None: CONNECT-Antwort 403, 405 oder 407 oder HTTP 407 (Proxy Authentication Required). Die Anfrage hat den
    Zielserver dann nicht erreicht. 502 und 504 (der Proxy erreicht den Zielserver nicht) sowie 429 und 503 sind keine
    Ablehnung in diesem Sinn."""
    if isinstance(fehler, urllib.error.HTTPError):
        return fehler.code if fehler.code == 407 else None
    code = tunnel_status(fehler)
    return code if code in PROXY_ABLEHNUNG else None


def _proxy_abbruch(url, code, fehler, dauer):
    """Protokolliert die Ablehnung durch den Proxy (Status `proxy <Code>`) und liefert den Abbruch der Art `proxy`."""
    _protokoll(url, f"proxy {code}", 0, dauer, "netz")
    return Abbruch(f"Ablehnung durch den Proxy der Arbeitsumgebung (HTTP {code} beim Verbindungsaufbau); die Anfrage "
                   f"hat den Zielserver nicht erreicht, kein Hinweis auf eine Sperre: {url} ({fehler})", "proxy", code)


def zaehler() -> dict:
    """Anfragen dieses Prozesses: ans Netz (einschließlich Wiederholungen) und aus dem Cache."""
    return {"netz": _anfragen, "cache": _cache_treffer}


def protokollzeilen() -> int:
    """Anzahl der Datenzeilen in abrufe.tsv (für die Zuordnung eines Laufs zu seinen Protokollzeilen)."""
    if not PROTOKOLL.exists():
        return 0
    with PROTOKOLL.open(encoding="utf-8") as f:
        return max(sum(1 for _ in f) - 1, 0)


def letzte_netzanfrage(protokoll=None):
    """Zeitpunkt (Sekunden seit der Epoche) der letzten Netzanfrage laut Protokoll (letzte Zeile mit quelle `netz`),
    sonst None. Das Protokoll schreibt die Zeit nach dem Ende der Antwort, sekundengenau mit Zone; Zeilen ohne Zone
    (geodaten.py vom 04.11.2026) gelten als Ortszeit Köln."""
    pfad = PROTOKOLL if protokoll is None else Path(protokoll)
    if not pfad.exists():
        return None
    with pfad.open(encoding="utf-8", errors="replace") as f:
        zeilen = f.read().splitlines()
    for zeile in reversed(zeilen[1:]):
        teile = zeile.split("\t")
        if len(teile) < 6 or teile[5] != "netz":
            continue
        try:
            t = dt.datetime.fromisoformat(teile[0])
        except ValueError:
            continue
        return (t if t.tzinfo else t.replace(tzinfo=ZEITZONE)).timestamp()
    return None


def _warten():
    """Wartet bis ABSTAND Sekunden nach dem Ende der letzten Antwort dieses Prozesses (bzw. nach dem Import); vor der
    ersten Netzanfrage des Prozesses auch bis ABSTAND Sekunden nach der letzten Netzanfrage laut Protokoll (eine
    Sekunde Zuschlag, weil die Zeit dort sekundengenau steht; höchstens ABSTAND + 1 Sekunden)."""
    global _erste_netzanfrage
    warte = ABSTAND - (time.monotonic() - _letzte)
    if _erste_netzanfrage:
        _erste_netzanfrage = False
        t = letzte_netzanfrage() if ABSTAND > 0 else None
        if t is not None:
            warte = max(warte, min(ABSTAND + 1 - (time.time() - t), ABSTAND + 1))
    if warte > 0:
        time.sleep(warte)


def _cachepfad(url: str, endung: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:20]
    return CACHE / "roh" / f"{h}{endung}"


def _protokoll(url, status, n, dauer, quelle, ziel=""):
    global _kopf_geprueft
    CACHE.mkdir(parents=True, exist_ok=True)
    kopf = "\t".join(PROTOKOLL_SPALTEN) + "\n"
    if not PROTOKOLL.exists():
        PROTOKOLL.write_text(kopf, encoding="utf-8")
    elif not _kopf_geprueft:   # älteres Protokoll ohne Spalte `ziel`: nur der Kopf wird ergänzt
        with PROTOKOLL.open(encoding="utf-8") as f:
            alt, rest = f.readline(), f.read()
        if alt != kopf:
            PROTOKOLL.write_text(kopf + rest, encoding="utf-8")
    _kopf_geprueft = True
    zeit = dt.datetime.now(ZEITZONE).isoformat(timespec="seconds")   # mit Zone, z. B. 2026-11-07T23:05:00+01:00
    with PROTOKOLL.open("a", encoding="utf-8") as f:
        f.write(f"{zeit}\t{url}\t{status}\t{n}\t{dauer:.2f}\t{quelle}\t{ziel}\n")


def hole(url: str, endung: str = "", cache: bool = True) -> bytes:
    """Gibt den Inhalt zurück; nutzt den Cache, hält Abstand und wiederholt behutsam."""
    global _letzte, _anfragen, _cache_treffer
    pfad = _cachepfad(url, endung)
    if cache and pfad.exists():
        daten = pfad.read_bytes()
        _cache_treffer += 1
        _protokoll(url, "cache", len(daten), 0, "cache")
        return daten
    pausen = PAUSEN[:max(WIEDERHOLUNGEN, 0)]
    fehler = None
    for versuch in range(len(pausen) + 1):
        if MAX_ANFRAGEN and _anfragen >= MAX_ANFRAGEN:
            raise Abbruch(f"Obergrenze von {MAX_ANFRAGEN} Anfragen erreicht (RATSATLAS_MAX_ANFRAGEN): {url}",
                          "obergrenze")
        _anfragen += 1
        _warten()
        start = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with _OEFFNER.open(req, timeout=60) as r:
                daten = r.read(MAX_BYTES + 1)
                dauer = time.monotonic() - start
                _protokoll(url, r.status, len(daten), dauer, "netz")
                if len(daten) > MAX_BYTES:
                    raise Abbruch(f"größer als {MAX_BYTES} Bytes: {url}", "groesse")
                if cache:
                    pfad.parent.mkdir(parents=True, exist_ok=True)
                    pfad.write_bytes(daten)
                if MAX_DAUER and dauer > MAX_DAUER:
                    raise Abbruch(f"Antwortzeit {dauer:.1f} s über {MAX_DAUER:g} s (RATSATLAS_MAX_DAUER): {url}",
                                  "langsam")
                return daten
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:   # Weiterleitung: nicht folgen, Ziel protokollieren, abbrechen
                ort = e.headers.get("Location") if e.headers else None
                ziel = urllib.parse.urljoin(url, ort) if ort else ""
                _protokoll(url, e.code, 0, time.monotonic() - start, "netz", ziel)
                raise Abbruch(f"Weiterleitung HTTP {e.code} nach {ziel or '(ohne Ziel)'} nicht verfolgt: {url}",
                              "weiterleitung", e.code, ziel) from e
            if proxy_ablehnung(e):   # HTTP 407: Antwort des Proxys, nicht des Zielservers
                raise _proxy_abbruch(url, e.code, e, time.monotonic() - start) from e
            _protokoll(url, e.code, 0, time.monotonic() - start, "netz")
            if e.code in (429,) or e.code >= 500:
                fehler = e
            else:
                raise Abbruch(f"HTTP {e.code}: {url}", "http", e.code) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            dauer = time.monotonic() - start
            code = tunnel_status(e)
            if code in PROXY_ABLEHNUNG:   # Ablehnung durch den Proxy: keine Antwort des Zielservers, keine Sperre
                raise _proxy_abbruch(url, code, e, dauer) from e
            _protokoll(url, f"tunnel {code}" if code else type(e).__name__, 0, dauer, "netz")
            if code in TUNNEL_SERVER:   # Begrenzung oder Überlastung: wie 429/503, aber ohne Wiederholung
                raise Abbruch(f"HTTP {code} des Proxys beim Verbindungsaufbau (Begrenzung oder Überlastung), keine "
                              f"Wiederholung: {url} ({e})", "server", code) from e
            if code:   # z. B. 502/504: Der Proxy erreicht den Zielserver nicht
                raise Abbruch(f"Der Proxy erreicht den Zielserver nicht (HTTP {code} beim Verbindungsaufbau), "
                              f"mögliche Sperre: {url} ({e})", "sperre", code) from e
            raise Abbruch(f"Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre: {url} ({e})", "sperre") from e
        finally:   # der Abstand gilt ab dem Ende der Antwort, auch nach Fehlern
            _letzte = time.monotonic()
        if versuch < len(pausen):
            time.sleep(pausen[versuch])
    raise Abbruch(f"aufgegeben nach {len(pausen) + 1} Versuchen: {url} ({fehler})", "server",
                  getattr(fehler, "code", None))
