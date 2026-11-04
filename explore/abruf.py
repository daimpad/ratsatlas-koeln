"""Gedrosselter HTTP-Abruf für die Exploration (Abrufpolitik CLAUDE.md 5.1).

- genau eine Verbindung zur Zeit, mindestens ABSTAND Sekunden zwischen zwei Anfragen (prozessweit)
- offener User-Agent mit Projektadresse; Kontakt über die Umgebungsvariable RATSATLAS_KONTAKT
- Wiederholung nur bei Netzfehlern und 429/5xx, mit wachsender Pause; 401/403 brechen sofort ab
- Rohdaten-Cache: jede Antwort wird unter explore/_cache/ abgelegt und beim nächsten Lauf nicht erneut abgerufen
- Protokoll jeder Anfrage (Zeit, URL, Status, Bytes, Dauer, Cache) in explore/_cache/abrufe.tsv
Nur Standardbibliothek.
"""
import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path(os.environ.get("RATSATLAS_CACHE", Path(__file__).resolve().parent / "_cache"))
ABSTAND = float(os.environ.get("RATSATLAS_ABSTAND", "2.0"))
PAUSEN = [30, 120, 600, 1800]  # Sekunden; danach Abbruch. Für den Produktivbetrieb bis zu mehreren Stunden (Phase 2).
KONTAKT = os.environ.get("RATSATLAS_KONTAKT", "")
USER_AGENT = "ratsatlas-koeln-explore/0.1 (+https://github.com/daimpad/ratsatlas-koeln" + (f"; {KONTAKT}" if KONTAKT else "") + ")"
MAX_BYTES = 250 * 1024 * 1024

_letzte = 0.0


class Abbruch(Exception):
    """Antwort, auf die nicht erneut angefragt wird (z. B. 401, 403, 404)."""


def _cachepfad(url: str, endung: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:20]
    return CACHE / "roh" / f"{h}{endung}"


def _protokoll(url, status, n, dauer, quelle):
    CACHE.mkdir(parents=True, exist_ok=True)
    datei = CACHE / "abrufe.tsv"
    neu = not datei.exists()
    with datei.open("a", encoding="utf-8") as f:
        if neu:
            f.write("zeit\turl\tstatus\tbytes\tdauer_s\tquelle\n")
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{url}\t{status}\t{n}\t{dauer:.2f}\t{quelle}\n")


def hole(url: str, endung: str = "", cache: bool = True) -> bytes:
    """Gibt den Inhalt zurück; nutzt den Cache, hält Abstand und wiederholt behutsam."""
    global _letzte
    pfad = _cachepfad(url, endung)
    if cache and pfad.exists():
        daten = pfad.read_bytes()
        _protokoll(url, "cache", len(daten), 0, "cache")
        return daten
    for versuch in range(len(PAUSEN) + 1):
        warte = ABSTAND - (time.monotonic() - _letzte)
        if warte > 0:
            time.sleep(warte)
        start = time.monotonic()
        _letzte = start
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                daten = r.read(MAX_BYTES + 1)
                if len(daten) > MAX_BYTES:
                    raise Abbruch(f"größer als {MAX_BYTES} Bytes: {url}")
                _protokoll(url, r.status, len(daten), time.monotonic() - start, "netz")
                if cache:
                    pfad.parent.mkdir(parents=True, exist_ok=True)
                    pfad.write_bytes(daten)
                return daten
        except urllib.error.HTTPError as e:
            _protokoll(url, e.code, 0, time.monotonic() - start, "netz")
            if e.code in (429,) or e.code >= 500:
                fehler = e
            else:
                raise Abbruch(f"HTTP {e.code}: {url}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _protokoll(url, type(e).__name__, 0, time.monotonic() - start, "netz")
            fehler = e
        if versuch < len(PAUSEN):
            time.sleep(PAUSEN[versuch])
    raise Abbruch(f"aufgegeben nach {len(PAUSEN) + 1} Versuchen: {url} ({fehler})")
