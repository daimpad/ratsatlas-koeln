"""Abruf der Kölner OParl-API nach der Abrufpolitik (CLAUDE.md 5.1); nur Standardbibliothek.

- genau eine Verbindung, mindestens `config.ABRUF_ABSTAND` Sekunden vom Ende einer Antwort bis zur nächsten Anfrage
  (auch nach Fehlern); für nicht lokale Adressen mindestens `MINDESTABSTAND` (2 s): kleinere Werte von
  `RATSATLAS_ABSTAND` werden mit Hinweis angehoben
- nur im nächtlichen Zeitfenster (`config.ABRUF_ZEITFENSTER`, Ortszeit Köln), sofern gesetzt
- nach HTTP 429, 5xx und unlesbaren Antworten wachsende Pausen (`config.ABRUF_PAUSEN`, bis zu mehreren Stunden);
  einen `Retry-After`-Kopf hält der Abruf mindestens ein; 401, 403 und 404 brechen sofort ab
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (so zeigte sich die Sperre von mandari 2026, explore/ergebnisse/sessionnet_befunde.tsv); der nächste Versuch
  folgt im nächsten Zeitfenster, nach drei solchen Nächten in Folge pausiert der Abruf (sessionnet.py)
- das Zeitfenster wird vor jedem Versuch geprüft, auch nach einer Pause
- Weiterleitungen (HTTP 3xx) werden nicht verfolgt (modulweiter Öffner `_OEFFNER` mit `_OhneWeiterleitung`; der
  Standard von urllib bleibt für andere Module unverändert): Abbruch der Art `weiterleitung` mit der Ziel-URL in
  Meldung und `Abbruch.ziel`, gezählt in `statistik()["weiterleitungen"]` und als Fehler (Abrufstatistik: Spalten
  `weiterleitungen` und `fehler`, Ziel in `ergebnis`); sonst kämen ungezählte Anfragen an einen anderen Host oder Pfad
  hinzu
- antwortet ein Proxy der Ausführungsumgebung auf CONNECT nicht mit 200 („Tunnel connection failed: <Code>“), zählt
  der Code:
  - 403, 405, 407 (Ablehnung durch eine Richtlinie oder fehlende Anmeldung) und HTTP 407: keine Antwort der Stadt;
    Abbruch der Art `proxy` ohne Wiederholung, gezählt in `statistik()["proxy"]` (Spalte `proxy`); keine Nacht mit
    möglicher Sperre
  - 429, 503 (Begrenzung oder Überlastung): wie HTTP 429/5xx (Pausen, danach `aufgegeben`)
  - alle übrigen, vor allem 502 und 504 (der Proxy erreicht die Stadt nicht): wie Zeitüberschreitung und
    Verbindungsabbruch Art `sperre` (mögliche Sperre)
- offener User-Agent mit Projektadresse und Kontakt (`RATSATLAS_KONTAKT`)
- Zählwerk je Lauf für die Abrufstatistik (`statistik()`)
- Sperre: ohne `RATSATLAS_STADT_INFORMIERT=ja` keine Anfrage an die Stadt (Entscheidung 04.11.2026)
"""
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

MINDESTABSTAND = 2.0   # Sekunden vom Ende einer Antwort bis zur nächsten Anfrage an nicht lokale Adressen (5.1)
_letzte = 0.0          # Ende der letzten Antwort (time.monotonic)
_hinweis_abstand = False
_zaehler = {"anfragen": 0, "fehler": 0, "wiederholungen": 0, "bytes": 0, "sekunden": 0.0, "weiterleitungen": 0,
            "proxy": 0}
# Meldung von http.client, wenn der Proxy den Tunnel (CONNECT) nicht aufbaut
_TUNNEL = re.compile(r"Tunnel connection failed: (\d{3})")
# Antworten eines Proxys auf CONNECT: Ablehnung durch eine Richtlinie oder fehlende Anmeldung (Art `proxy`) …
PROXY_ABLEHNUNG = (403, 405, 407)
# … Begrenzung oder Überlastung (wie HTTP 429/5xx); alle übrigen Codes, vor allem 502 und 504 (der Proxy erreicht die
# Stadt nicht), gelten wie Zeitüberschreitung und Verbindungsabbruch als mögliche Sperre
TUNNEL_UEBERLAST = (429, 503)


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


# modulweiter Öffner ohne Weiterleitung (Proxy aus der Umgebung beim Import); urllib.request.urlopen und der
# Standard-Öffner bleiben für andere Module (Geodaten, Kontextdaten) unverändert
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
    None: CONNECT-Antwort 403, 405 oder 407 oder HTTP 407 (Proxy Authentication Required). 502 und 504 (der Proxy
    erreicht die Stadt nicht) sowie 429 und 503 sind keine Ablehnung in diesem Sinn."""
    if isinstance(fehler, urllib.error.HTTPError):
        return fehler.code if fehler.code == 407 else None
    code = tunnel_status(fehler)
    return code if code in PROXY_ABLEHNUNG else None


def _proxy_abbruch(url, code):
    _zaehler["proxy"] += 1
    return Abbruch(f"Ablehnung durch den Proxy der Ausführungsumgebung (HTTP {code} beim Verbindungsaufbau): {url}; "
                   "die Anfrage hat die Stadt nicht erreicht, kein Hinweis auf eine Sperre. Nicht wiederholen, "
                   "Netzfreigabe der Umgebung prüfen", "proxy")


def abstand(lokal):
    """Abstand in Sekunden vom Ende einer Antwort bis zur nächsten Anfrage: `config.ABRUF_ABSTAND`, für nicht lokale
    Adressen mindestens MINDESTABSTAND (kleinere oder unlesbare Werte werden mit einem Hinweis angehoben)."""
    global _hinweis_abstand
    wert = config.ABRUF_ABSTAND
    if lokal or (math.isfinite(wert) and wert >= MINDESTABSTAND):
        return wert
    if not _hinweis_abstand:
        print(f"Hinweis: RATSATLAS_ABSTAND={wert:g} s liegt unter dem Mindestabstand für Anfragen an die Stadt; "
              f"es gilt {MINDESTABSTAND:g} s (CLAUDE.md 5.1).", file=sys.stderr)
        _hinweis_abstand = True
    return MINDESTABSTAND


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
    mindestens = abstand(lokal)
    letzter_fehler = None
    for versuch in range(len(pausen) + 1):
        if not lokal and not im_zeitfenster():
            raise Abbruch(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (RATSATLAS_ZEITFENSTER)",
                          "zeitfenster")
        warte = mindestens - (time.monotonic() - _letzte)
        if warte > 0:
            time.sleep(warte)
        start = time.monotonic()
        _zaehler["anfragen"] += 1
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        retry_after = 0
        try:
            with _OEFFNER.open(req, timeout=90) as r:
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
            code = tunnel_status(e)
            if code not in TUNNEL_UEBERLAST:
                _zaehler["sekunden"] += time.monotonic() - start
                if code in PROXY_ABLEHNUNG:   # Ablehnung durch den Proxy: keine Antwort der Stadt, keine Sperre
                    raise _proxy_abbruch(url, code) from e
                grund = (f"Der Proxy erreicht die Stadt nicht (HTTP {code} beim Verbindungsaufbau)" if code
                         else "Zeitüberschreitung oder Verbindungsabbruch")
                raise Abbruch(f"{grund}, mögliche Sperre: {url} ({e}); nächster Versuch im nächsten Zeitfenster",
                              "sperre") from e
            letzter_fehler = e   # CONNECT-Antwort 429/503 (Begrenzung, Überlastung): wie HTTP 429/5xx
        except json.JSONDecodeError as e:
            _zaehler["fehler"] += 1
            letzter_fehler = e
        finally:   # der Abstand gilt ab dem Ende der Antwort, auch nach Fehlern
            _letzte = time.monotonic()
        _zaehler["sekunden"] += time.monotonic() - start
        if versuch < len(pausen):
            _zaehler["wiederholungen"] += 1
            time.sleep(max(pausen[versuch], retry_after))
    raise Abbruch(f"aufgegeben nach {len(pausen) + 1} Versuchen: {url} ({letzter_fehler})", "aufgegeben")
