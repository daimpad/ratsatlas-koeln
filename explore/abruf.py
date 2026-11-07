"""Gedrosselter HTTP-Abruf für die Exploration (Abrufpolitik CLAUDE.md 5.1).

- genau eine Verbindung zur Zeit, mindestens ABSTAND Sekunden vom Ende einer Antwort bis zur nächsten Anfrage
  (prozessweit; Antworten aus dem Cache zählen nicht)
- offener User-Agent mit Projektadresse; Kontakt über die Umgebungsvariable RATSATLAS_KONTAKT
- Wiederholung nur bei 429/5xx, mit wachsender Pause; 401/403/404 brechen sofort ab;
  RATSATLAS_WIEDERHOLUNGEN=0 bricht auch bei 429/5xx sofort ab (Messstufen: stoppen und berichten)
- RATSATLAS_MAX_DAUER (Sekunden): eine langsamere Antwort wird noch gespeichert, danach Abbruch
- RATSATLAS_MAX_ANFRAGEN: harte Obergrenze für Anfragen ans Netz je Prozess (Cache-Treffer zählen nicht)
- Weiterleitungen (3xx) werden nicht verfolgt: jede Weiterleitung ist genau eine Anfrage, wird mit Ziel-URL
  protokolliert und bricht ab (sonst kämen ungezählte Anfragen an einen anderen Host oder Pfad hinzu)
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (wie pipeline/abruf.py; explore/ergebnisse/sessionnet_befunde.tsv)
- Rohdaten-Cache: jede Antwort wird unter explore/_cache/ abgelegt und beim nächsten Lauf nicht erneut abgerufen
- Protokoll jeder Anfrage (Zeit mit Zone, URL, Status, Bytes, Dauer, Netz oder Cache, Ziel einer Weiterleitung) in
  explore/_cache/abrufe.tsv
Für Anfragen an die Stadt setzt explore/oparl_messung.py strengere Vorgaben (keine Wiederholung, höchstens 5 s je
Antwort, Obergrenze und Kontakt Pflicht).
Nur Standardbibliothek.
"""
import datetime as dt
import hashlib
import os
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

_letzte = 0.0


class Abbruch(Exception):
    """Antwort, auf die nicht erneut angefragt wird. `art`: http (4xx, `code` gesetzt), server (429/5xx nach allen
    Wiederholungen), sperre (Zeitüberschreitung, Verbindungsabbruch), weiterleitung (3xx, `ziel` gesetzt),
    obergrenze, langsam, groesse."""

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


def zaehler() -> dict:
    """Anfragen dieses Prozesses: ans Netz (einschließlich Wiederholungen) und aus dem Cache."""
    return {"netz": _anfragen, "cache": _cache_treffer}


def protokollzeilen() -> int:
    """Anzahl der Datenzeilen in abrufe.tsv (für die Zuordnung eines Laufs zu seinen Protokollzeilen)."""
    if not PROTOKOLL.exists():
        return 0
    with PROTOKOLL.open(encoding="utf-8") as f:
        return max(sum(1 for _ in f) - 1, 0)


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
        warte = ABSTAND - (time.monotonic() - _letzte)
        if warte > 0:
            time.sleep(warte)
        start = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with _OEFFNER.open(req, timeout=60) as r:
                daten = r.read(MAX_BYTES + 1)
                if len(daten) > MAX_BYTES:
                    raise Abbruch(f"größer als {MAX_BYTES} Bytes: {url}", "groesse")
                dauer = time.monotonic() - start
                _protokoll(url, r.status, len(daten), dauer, "netz")
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
            _protokoll(url, e.code, 0, time.monotonic() - start, "netz")
            if e.code in (429,) or e.code >= 500:
                fehler = e
            else:
                raise Abbruch(f"HTTP {e.code}: {url}", "http", e.code) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            _protokoll(url, type(e).__name__, 0, time.monotonic() - start, "netz")
            raise Abbruch(f"Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre: {url} ({e})", "sperre") from e
        finally:   # der Abstand gilt ab dem Ende der Antwort, auch nach Fehlern
            _letzte = time.monotonic()
        if versuch < len(pausen):
            time.sleep(pausen[versuch])
    raise Abbruch(f"aufgegeben nach {len(pausen) + 1} Versuchen: {url} ({fehler})", "server",
                  getattr(fehler, "code", None))
