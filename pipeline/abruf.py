"""Abruf der Kölner OParl-API nach der Abrufpolitik (CLAUDE.md 5.1); nur Standardbibliothek.

- genau eine Verbindung, mindestens `config.ABRUF_ABSTAND` Sekunden vom Ende einer Antwort bis zur nächsten Anfrage
  (auch nach Fehlern); für nicht lokale Adressen mindestens `MINDESTABSTAND` (2 s): kleinere Werte von
  `RATSATLAS_ABSTAND` werden mit Hinweis angehoben. Gezählt wird ab dem Import: Auch die erste Anfrage eines Prozesses
  folgt frühestens diesen Abstand nach dem Start.
- lokal sind nur Adressen mit Schema http und Host 127.0.0.1, localhost oder ::1 (`lokal()`, über urlsplit; nicht etwa
  http://localhost.example.org/ oder http://127.0.0.1.nip.io/): nur für sie entfallen Freigabe, Zeitfenster und
  Mindestabstand
- nur im nächtlichen Zeitfenster (`config.ABRUF_ZEITFENSTER`, Ortszeit Köln), sofern gesetzt
- nach HTTP 429, 5xx und unlesbaren Antworten (kein JSON) wachsende Pausen (`config.ABRUF_PAUSEN`, bis zu mehreren
  Stunden), danach Abbruch der Art `aufgegeben`; einen `Retry-After`-Kopf hält der Abruf mindestens ein; 401, 403 und
  404 brechen sofort ab (Art `http` mit `code`)
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (so zeigte sich die Sperre von mandari 2026, explore/ergebnisse/sessionnet_befunde.tsv); der nächste Versuch
  folgt im nächsten Zeitfenster. Welche Abbrüche als Nacht mit möglicher Sperre zählen (dann nach drei Nächten in
  Folge sieben Tage Pause), regelt sessionnet.py (`moegliche_sperre`)
- ebenso eine abgeschnittene oder unlesbare Antwort (http.client.HTTPException, kein OSError: IncompleteRead bei
  weniger Bytes als Content-Length oder chunked ohne Abschluss, BadStatusLine, LineTooLong, RemoteDisconnected …),
  auch als Antwort eines Proxys auf CONNECT: Art `sperre`, keine Wiederholung. Eine ungültige Adresse
  (http.client.InvalidURL, z. B. ein Leerzeichen in links.next) wird nicht gesendet: Art `adresse`, keine Sperre
- das Zeitfenster wird vor jedem Versuch geprüft, auch nach einer Pause
- Weiterleitungen (HTTP 3xx) werden nicht verfolgt (modulweiter Öffner `_OEFFNER` mit `_OhneWeiterleitung`; der
  Standard von urllib bleibt für andere Module unverändert): Abbruch der Art `weiterleitung` mit der Ziel-URL in
  Meldung und `Abbruch.ziel`, gezählt in `statistik()["weiterleitungen"]` und als Fehler (Abrufstatistik: Spalten
  `weiterleitungen` und `fehler`, Ziel in `ergebnis`); sonst kämen ungezählte Anfragen an einen anderen Host oder Pfad
  hinzu
- antwortet ein Proxy der Ausführungsumgebung auf CONNECT nicht mit 200 („Tunnel connection failed: <Code>“), zählt
  der Code:
  - 403, 405, 407 (Ablehnung durch eine Richtlinie oder fehlende Anmeldung): keine Antwort der Stadt; Abbruch der Art
    `proxy` ohne Wiederholung, gezählt in `statistik()["proxy"]` (Spalte `proxy`); keine Nacht mit möglicher Sperre.
    Ein HTTP 407 gilt nur dann als Ablehnung durch den Proxy, wenn urllib für das Schema der Adresse einen Proxy meldet
    (`proxy_gesetzt()`, ohne Ausnahme aus no_proxy); sonst kommt er von der Gegenseite (Art `http`)
  - 429, 503 (Begrenzung oder Überlastung): wie HTTP 429/5xx (Pausen, danach `aufgegeben`)
  - alle übrigen, vor allem 502 und 504 (der Proxy erreicht die Stadt nicht): wie Zeitüberschreitung und
    Verbindungsabbruch Art `sperre` (mögliche Sperre)
- offener User-Agent mit Projektadresse und Kontakt (`RATSATLAS_KONTAKT`)
- Zählwerk je Lauf für die Abrufstatistik (`statistik()`)
- Sperre: ohne `RATSATLAS_STADT_INFORMIERT=ja` keine Anfrage an die Stadt (Entscheidung 04.11.2026)
"""
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

MINDESTABSTAND = 2.0   # Sekunden vom Ende einer Antwort bis zur nächsten Anfrage an nicht lokale Adressen (5.1)
# Ende der letzten Antwort (time.monotonic); beim Import gesetzt, damit auch die erste Anfrage eines Prozesses
# frühestens den Abstand nach dem Start folgt (wie explore/abruf.py)
_letzte = time.monotonic()
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
# Hosts lokaler Testserver (nur mit Schema http)
LOKALE_HOSTS = ("127.0.0.1", "localhost", "::1")


class Abbruch(RuntimeError):
    """Der Abruf wird beendet; der letzte gültige Datenstand bleibt erhalten. `art`: sperre, proxy, weiterleitung,
    zeitfenster, gesperrt, http, aufgegeben, adresse, liste oder leer; `ziel`: Ziel einer Weiterleitung; `code`:
    HTTP-Status (bei http, bei aufgegeben nach HTTP 429/5xx oder CONNECT-Antwort 429/503, bei sperre nach einer
    CONNECT-Antwort wie 502/504), sonst None."""

    def __init__(self, meldung, art="", ziel="", code=None):
        super().__init__(meldung)
        self.art = art
        self.ziel = ziel
        self.code = code


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Weiterleitung: urllib meldet 3xx dann als HTTPError mit dem Location-Kopf (wie explore/abruf.py)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# modulweiter Öffner ohne Weiterleitung (Proxy aus der Umgebung beim Import); urllib.request.urlopen und der
# Standard-Öffner bleiben für andere Module (Geodaten, Kontextdaten) unverändert
_OEFFNER = urllib.request.build_opener(_OhneWeiterleitung)


def lokal(url):
    """Lokaler Testserver: Schema http und Host 127.0.0.1, localhost oder ::1 (über urlsplit). Adressen wie
    http://localhost.example.org/ oder http://127.0.0.1.nip.io/ gelten nicht als lokal."""
    try:
        teile = urllib.parse.urlsplit(url)
        return teile.scheme == "http" and teile.hostname in LOKALE_HOSTS
    except ValueError:   # z. B. unvollständige IPv6-Adresse
        return False


def proxy_gesetzt(url):
    """Meldet urllib.request.getproxies() für das Schema der Adresse einen Proxy, ohne Ausnahme für den Host aus
    no_proxy? Nur dann kann ein HTTP 407 vom Proxy der Ausführungsumgebung stammen."""
    try:
        teile = urllib.parse.urlsplit(url)
        host = teile.hostname or ""
    except ValueError:
        return False
    proxies = urllib.request.getproxies()
    if not proxies.get(teile.scheme):
        return False
    return not urllib.request.proxy_bypass_environment(host, proxies)


def tunnel_status(fehler):
    """Statuscode, mit dem ein Proxy den Tunnel (CONNECT) nicht aufgebaut hat (http.client meldet „Tunnel connection
    failed: 502 Bad Gateway“), sonst None."""
    if isinstance(fehler, urllib.error.HTTPError):
        return None
    m = _TUNNEL.search(str(fehler))
    return int(m.group(1)) if m else None


def proxy_ablehnung(fehler, url=""):
    """Statuscode, mit dem ein Proxy die Verbindung durch eine Richtlinie oder mangels Anmeldung abgelehnt hat, sonst
    None: CONNECT-Antwort 403, 405 oder 407, oder HTTP 407 (Proxy Authentication Required), Letzteres nur, wenn für
    die Adresse (`url`, sonst die des Fehlers) ein Proxy gesetzt ist; ohne Proxy, etwa in GitHub Actions, kommt ein 407
    von der Gegenseite. 502 und 504 (der Proxy erreicht die Stadt nicht) sowie 429 und 503 sind keine Ablehnung in
    diesem Sinn."""
    if isinstance(fehler, urllib.error.HTTPError):
        return 407 if fehler.code == 407 and proxy_gesetzt(url or fehler.filename or "") else None
    code = tunnel_status(fehler)
    return code if code in PROXY_ABLEHNUNG else None


def _proxy_abbruch(url, code):
    _zaehler["proxy"] += 1
    return Abbruch(f"Ablehnung durch den Proxy der Ausführungsumgebung (HTTP {code} beim Verbindungsaufbau): {url}; "
                   "die Anfrage hat die Stadt nicht erreicht, kein Hinweis auf eine Sperre. Nicht wiederholen, "
                   "Netzfreigabe der Umgebung prüfen", "proxy", code=code)


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
    """Anfragen an Server der Stadt Köln nur nach deren Information; lokale Testserver (`lokal()`) immer."""
    return lokal(url) or os.environ.get("RATSATLAS_STADT_INFORMIERT") == "ja"


def im_zeitfenster(jetzt=None):
    fenster = (config.ABRUF_ZEITFENSTER or "").strip()
    if not fenster:
        return True
    von, bis = (int(x) for x in fenster.split("-"))
    h = (jetzt or datetime.now(ZoneInfo("Europe/Berlin"))).hour
    return von <= h < bis if von < bis else (h >= von or h < bis)


def fenster_offen_nach(sekunden, jetzt=None):
    """Ist das Zeitfenster jetzt offen und nach `sekunden` noch offen (Ende einer Pause vor dem nächsten Versuch)?"""
    jetzt = jetzt or datetime.now(ZoneInfo("Europe/Berlin"))
    return im_zeitfenster(jetzt) and im_zeitfenster(jetzt + timedelta(seconds=sekunden))


def _aufgegeben(url, letzter_fehler, versuche, grund=""):
    code = getattr(letzter_fehler, "code", None) if isinstance(letzter_fehler, urllib.error.HTTPError) else \
        tunnel_status(letzter_fehler)
    return Abbruch(f"aufgegeben nach {versuche} Versuch(en){grund}: {url} ({letzter_fehler})", "aufgegeben", code=code)


def statistik():
    return dict(_zaehler)


def get_json(url, pausen=None):
    """Eine Anfrage nach der Abrufpolitik; liefert das JSON-Objekt."""
    global _letzte
    if not freigegeben(url):
        raise Abbruch("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (CLAUDE.md 9). "
                      "Freigabe mit RATSATLAS_STADT_INFORMIERT=ja.", "gesperrt")
    ist_lokal = lokal(url)
    pausen = config.ABRUF_PAUSEN if pausen is None else pausen
    mindestens = abstand(ist_lokal)
    letzter_fehler = None
    for versuch in range(len(pausen) + 1):
        if not ist_lokal and not im_zeitfenster():
            if letzter_fehler is not None:   # nach 429/5xx/unlesbar: zählt als aufgegeben (mögliche Sperre)
                raise _aufgegeben(url, letzter_fehler, versuch, ", Zeitfenster vorbei")
            raise Abbruch(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (RATSATLAS_ZEITFENSTER)",
                          "zeitfenster")
        warte = mindestens - (time.monotonic() - _letzte)
        if warte > 0:
            time.sleep(warte)
        start = time.monotonic()
        _zaehler["anfragen"] += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        except ValueError as e:   # unbekanntes Schema o. Ä. (z. B. links.next ohne Schema): nicht gesendet, keine Sperre
            _zaehler["anfragen"] -= 1
            _zaehler["fehler"] += 1
            raise Abbruch(f"ungültige Adresse, nicht gesendet: {url} ({e})", "adresse") from e
        retry_after = 0
        try:
            with _OEFFNER.open(req, timeout=90) as r:
                daten = r.read()   # weniger Bytes als Content-Length oder chunked ohne Abschluss: IncompleteRead
            _zaehler["bytes"] += len(daten)
            _zaehler["sekunden"] += time.monotonic() - start
            antwort = json.loads(daten)
            if not isinstance(antwort, dict):   # gültiges JSON in unerwarteter Form (z. B. null, [], Fehlerseite)
                raise ValueError(f"JSON-Objekt erwartet, erhalten: {type(antwort).__name__}")
            return antwort
        except urllib.error.HTTPError as e:
            _zaehler["fehler"] += 1
            if 300 <= e.code < 400:   # Weiterleitung: nicht folgen, Ziel nennen, abbrechen
                _zaehler["weiterleitungen"] += 1
                _zaehler["sekunden"] += time.monotonic() - start
                ort = e.headers.get("Location") if e.headers else None
                ziel = urllib.parse.urljoin(url, ort) if ort else ""
                raise Abbruch(f"Weiterleitung HTTP {e.code} nach {ziel or '(ohne Ziel)'} nicht verfolgt: {url}",
                              "weiterleitung", ziel, e.code) from e
            if proxy_ablehnung(e, url):   # HTTP 407, und für die Adresse ist ein Proxy gesetzt
                _zaehler["sekunden"] += time.monotonic() - start
                raise _proxy_abbruch(url, e.code) from e
            if e.code != 429 and e.code < 500:
                _zaehler["sekunden"] += time.monotonic() - start
                raise Abbruch(f"HTTP {e.code}: {url}", "http", code=e.code) from e
            letzter_fehler = e
            try:
                retry_after = int(e.headers.get("Retry-After") or 0)
            except ValueError:
                retry_after = 0
        except http.client.InvalidURL as e:   # vor dem Senden erkannt (z. B. Leerzeichen): keine Anfrage, keine Sperre
            _zaehler["anfragen"] -= 1
            _zaehler["fehler"] += 1
            raise Abbruch(f"ungültige Adresse, nicht gesendet: {url} ({e})", "adresse") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
            # HTTPException (kein OSError): Antwort abgeschnitten (IncompleteRead) oder unlesbar (BadStatusLine,
            # LineTooLong …), auch als Antwort des Proxys auf CONNECT – wie ein Verbindungsabbruch
            _zaehler["fehler"] += 1
            code = tunnel_status(e)
            if code not in TUNNEL_UEBERLAST:
                _zaehler["sekunden"] += time.monotonic() - start
                if code in PROXY_ABLEHNUNG:   # Ablehnung durch den Proxy: keine Antwort der Stadt, keine Sperre
                    raise _proxy_abbruch(url, code) from e
                grund = (f"Der Proxy erreicht die Stadt nicht (HTTP {code} beim Verbindungsaufbau)" if code
                         else f"Antwort abgeschnitten oder unlesbar ({type(e).__name__})"
                         if isinstance(e, http.client.HTTPException)
                         else "Zeitüberschreitung oder Verbindungsabbruch")
                raise Abbruch(f"{grund}, mögliche Sperre: {url} ({e}); nächster Versuch im nächsten Zeitfenster",
                              "sperre", code=code) from e
            letzter_fehler = e   # CONNECT-Antwort 429/503 (Begrenzung, Überlastung): wie HTTP 429/5xx
        except ValueError as e:   # unlesbar: kein JSON (JSONDecodeError) oder keine gültige Kodierung
            _zaehler["fehler"] += 1
            letzter_fehler = e
        finally:   # der Abstand gilt ab dem Ende der Antwort, auch nach Fehlern
            _letzte = time.monotonic()
        _zaehler["sekunden"] += time.monotonic() - start
        if versuch < len(pausen):
            pause = max(pausen[versuch], retry_after)
            # Endet das Zeitfenster vor dem nächsten Versuch, jetzt aufgeben (zählt als Nacht mit möglicher Sperre),
            # statt die Pause abzuwarten und dann nur „Zeitfenster vorbei“ zu melden
            if not ist_lokal and not fenster_offen_nach(pause):
                raise _aufgegeben(url, letzter_fehler, versuch + 1, ", nächste Pause reicht über das Zeitfenster")
            _zaehler["wiederholungen"] += 1
            time.sleep(pause)
    raise _aufgegeben(url, letzter_fehler, len(pausen) + 1)
