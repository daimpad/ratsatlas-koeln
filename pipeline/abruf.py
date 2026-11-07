"""Abruf der Kölner OParl-API nach der Abrufpolitik (CLAUDE.md 5.1); nur Standardbibliothek.

- genau eine Verbindung, mindestens `config.ABRUF_ABSTAND` Sekunden zwischen zwei Anfragen
- nur im nächtlichen Zeitfenster (`config.ABRUF_ZEITFENSTER`, Ortszeit Köln), sofern gesetzt
- nach HTTP 429, 5xx und unlesbaren Antworten wachsende Pausen (`config.ABRUF_PAUSEN`, bis zu mehreren Stunden);
  einen `Retry-After`-Kopf hält der Abruf mindestens ein; 401, 403 und 404 brechen sofort ab
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (so zeigte sich die Sperre von mandari 2026, explore/ergebnisse/sessionnet_befunde.tsv); der nächste Versuch
  folgt im nächsten Zeitfenster, nach drei solchen Nächten in Folge pausiert der Abruf (sessionnet.py)
- das Zeitfenster wird vor jedem Versuch geprüft, auch nach einer Pause
- Weiterleitungen (HTTP 3xx) werden nicht verfolgt (eigener Handler `_OhneWeiterleitung`): Abbruch der Art
  `weiterleitung` mit der Ziel-URL in Meldung und `Abbruch.ziel`, gezählt in `statistik()["weiterleitungen"]` und als
  Fehler (Abrufstatistik: Spalte `fehler`, Ziel in `ergebnis`); sonst kämen ungezählte Anfragen an einen anderen Host
  oder Pfad hinzu
- eine Ablehnung durch einen Proxy der Ausführungsumgebung (Antwort ≠ 200 auf CONNECT, „Tunnel connection failed:
  403 Forbidden“, oder HTTP 407) ist keine Antwort der Stadt: Abbruch der Art `proxy` ohne Wiederholung, gezählt in
  `statistik()["proxy"]`; sie zählt nicht als Nacht mit möglicher Sperre
- offener User-Agent mit Projektadresse und Kontakt (`RATSATLAS_KONTAKT`)
- Zählwerk je Lauf für die Abrufstatistik (`statistik()`)
- Sperre: ohne `RATSATLAS_STADT_INFORMIERT=ja` keine Anfrage an die Stadt (Entscheidung 04.11.2026)
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

_letzte = 0.0
_zaehler = {"anfragen": 0, "fehler": 0, "wiederholungen": 0, "bytes": 0, "sekunden": 0.0, "weiterleitungen": 0,
            "proxy": 0}
# Meldung von http.client, wenn der Proxy den Tunnel (CONNECT) ablehnt
_TUNNEL = re.compile(r"Tunnel connection failed: (\d{3})")


class Abbruch(RuntimeError):
    """Der Abruf wird beendet; der letzte gültige Datenstand bleibt erhalten. `art`: sperre, proxy, weiterleitung,
    zeitfenster, gesperrt, http, aufgegeben, liste oder leer; `ziel`: Ziel einer Weiterleitung."""

    def __init__(self, meldung, art="", ziel=""):
        super().__init__(meldung)
        self.art = art
        self.ziel = ziel


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Weiterleitung: urllib meldet 3xx dann als HTTPError mit dem Location-Kopf (wie explore/abruf.py)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _oeffnen(req, timeout):
    """Öffnet eine Anfrage ohne Weiterleitung über urllib.request.urlopen. Der Öffner mit `_OhneWeiterleitung` (Proxy
    aus der Umgebung) gilt nur für diesen Aufruf; danach folgen andere Module (Geodaten, Kontextdaten) wieder dem
    Standard von urllib. urlopen bleibt die eine Stelle, an der Tests das Netz ersetzen (tests/test_sessionnet.py)."""
    urllib.request.install_opener(urllib.request.build_opener(_OhneWeiterleitung))
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    finally:
        urllib.request.install_opener(None)


def proxy_ablehnung(fehler):
    """Statuscode, mit dem ein Proxy die Verbindung abgelehnt hat, sonst None: Antwort ≠ 200 auf CONNECT (http.client
    meldet „Tunnel connection failed: 403 Forbidden“) oder HTTP 407 (Proxy Authentication Required)."""
    if isinstance(fehler, urllib.error.HTTPError):
        return fehler.code if fehler.code == 407 else None
    m = _TUNNEL.search(str(fehler))
    return int(m.group(1)) if m else None


def _proxy_abbruch(url, code):
    _zaehler["proxy"] += 1
    return Abbruch(f"Ablehnung durch den Proxy der Ausführungsumgebung (HTTP {code} beim Verbindungsaufbau): {url}; "
                   "die Anfrage hat die Stadt nicht erreicht, kein Hinweis auf eine Sperre. Nicht wiederholen, "
                   "Netzfreigabe der Umgebung prüfen", "proxy")


def freigegeben(url):
    """Anfragen an Server der Stadt Köln nur nach deren Information; lokale Testserver sind immer erlaubt."""
    lokal = url.startswith(("http://127.0.0.1", "http://localhost"))
    return lokal or os.environ.get("RATSATLAS_STADT_INFORMIERT") == "ja"


def im_zeitfenster(jetzt=None):
    fenster = (config.ABRUF_ZEITFENSTER or "").strip()
    if not fenster:
        return True
    von, bis = (int(x) for x in fenster.split("-"))
    h = (jetzt or datetime.now(ZoneInfo("Europe/Berlin"))).hour
    return von <= h < bis if von < bis else (h >= von or h < bis)


def statistik():
    return dict(_zaehler)


def get_json(url, pausen=None):
    """Eine Anfrage nach der Abrufpolitik; liefert das JSON-Objekt."""
    global _letzte
    if not freigegeben(url):
        raise Abbruch("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (CLAUDE.md 9). "
                      "Freigabe mit RATSATLAS_STADT_INFORMIERT=ja.", "gesperrt")
    lokal = url.startswith(("http://127.0.0.1", "http://localhost"))
    pausen = config.ABRUF_PAUSEN if pausen is None else pausen
    letzter_fehler = None
    for versuch in range(len(pausen) + 1):
        if not lokal and not im_zeitfenster():
            raise Abbruch(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (RATSATLAS_ZEITFENSTER)",
                          "zeitfenster")
        warte = config.ABRUF_ABSTAND - (time.monotonic() - _letzte)
        if warte > 0:
            time.sleep(warte)
        start = _letzte = time.monotonic()
        _zaehler["anfragen"] += 1
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        retry_after = 0
        try:
            with _oeffnen(req, 90) as r:
                daten = r.read()
            _zaehler["bytes"] += len(daten)
            _zaehler["sekunden"] += time.monotonic() - start
            return json.loads(daten)
        except urllib.error.HTTPError as e:
            _zaehler["fehler"] += 1
            if 300 <= e.code < 400:   # Weiterleitung: nicht folgen, Ziel nennen, abbrechen
                _zaehler["weiterleitungen"] += 1
                _zaehler["sekunden"] += time.monotonic() - start
                ort = e.headers.get("Location") if e.headers else None
                ziel = urllib.parse.urljoin(url, ort) if ort else ""
                raise Abbruch(f"Weiterleitung HTTP {e.code} nach {ziel or '(ohne Ziel)'} nicht verfolgt: {url}",
                              "weiterleitung", ziel) from e
            if proxy_ablehnung(e):
                _zaehler["sekunden"] += time.monotonic() - start
                raise _proxy_abbruch(url, e.code) from e
            if e.code != 429 and e.code < 500:
                raise Abbruch(f"HTTP {e.code}: {url}", "http") from e
            letzter_fehler = e
            try:
                retry_after = int(e.headers.get("Retry-After") or 0)
            except ValueError:
                retry_after = 0
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            _zaehler["fehler"] += 1
            _zaehler["sekunden"] += time.monotonic() - start
            code = proxy_ablehnung(e)
            if code:   # der Proxy lehnt den Tunnel ab: keine Antwort der Stadt, keine Sperre
                raise _proxy_abbruch(url, code) from e
            raise Abbruch(f"Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre: {url} ({e}); "
                          "nächster Versuch im nächsten Zeitfenster", "sperre") from e
        except json.JSONDecodeError as e:
            _zaehler["fehler"] += 1
            letzter_fehler = e
        _zaehler["sekunden"] += time.monotonic() - start
        if versuch < len(pausen):
            _zaehler["wiederholungen"] += 1
            time.sleep(max(pausen[versuch], retry_after))
    raise Abbruch(f"aufgegeben nach {len(pausen) + 1} Versuchen: {url} ({letzter_fehler})", "aufgegeben")
