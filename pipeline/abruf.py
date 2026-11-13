"""Abruf der Kölner OParl-API nach der Abrufpolitik (CLAUDE.md 5.1); nur Standardbibliothek.

- genau eine Verbindung, mindestens `config.ABRUF_ABSTAND` Sekunden vom Ende einer Antwort bis zur nächsten Anfrage
  (auch nach Fehlern); für nicht lokale Adressen mindestens `MINDESTABSTAND` (2 s): kleinere Werte von
  `RATSATLAS_ABSTAND` werden mit Hinweis angehoben. Gezählt wird ab dem Import: Auch die erste Anfrage eines Prozesses
  folgt frühestens diesen Abstand nach dem Start.
- lokal sind nur Adressen mit Schema http und Host 127.0.0.1, localhost oder ::1 (`lokal()`, über urlsplit; nicht etwa
  http://localhost.example.org/ oder http://127.0.0.1.nip.io/): nur für sie entfallen Freigabe, Zeitfenster und
  Mindestabstand
- nur im nächtlichen Zeitfenster (`config.ABRUF_ZEITFENSTER`, Ortszeit Köln), sofern gesetzt; geprüft vor jedem
  Versuch, auch nach einer Pause, und nach dem Warten auf den Abstand noch einmal unmittelbar vor dem Senden (das
  Fenster kann während des Wartens enden)
- nach HTTP 429, 5xx und unlesbaren Antworten (kein JSON, ungültiges UTF-8, auch zu tief verschachtelt; rohe
  Steuerzeichen in Zeichenketten gelten als lesbar, json.loads mit strict=False) wachsende Pausen
  (`config.ABRUF_PAUSEN`, bis zu mehreren Stunden), danach Abbruch der Art `aufgegeben`. Einen `Retry-After`-Kopf
  (Sekunden oder HTTP-Datum) hält der Abruf mindestens ein. Sofort `aufgegeben` (ohne Pause): wenn die nächste Pause
  nicht vor dem Ende des laufenden Zeitfensters endet (`fenster_offen_nach`, gerechnet in UTC, also auch über eine
  Zeitumstellung), wenn `Retry-After` länger ist als die längste Pause oder wenn `Retry-After` unlesbar ist. 401, 403
  und 404 brechen sofort ab (Art `http` mit `code`)
- `Retry-After` gilt über die Nacht hinaus: Endet ein Abruf als `aufgegeben` mit einem `Retry-After`, trägt der Abbruch
  `nicht_vor` (jetzt + Retry-After in UTC, höchstens `RETRY_AFTER_HOECHSTENS` = 30 Tage; unlesbar
  `RETRY_AFTER_UNLESBAR` = 7 Tage); sessionnet.py speichert den Zeitpunkt im Zustand und ruft vorher nicht ab. Mehr als
  12 Ziffern (ohne führende Nullen) gelten als unendlich lang (also 30 Tage)
- gültiges JSON in unerwarteter Form (null, [], Zahl, Text statt eines Objekts) ist kein Überlastungssignal: Abbruch
  der Art `unlesbar` nach einer Anfrage, ohne Wiederholung
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (so zeigte sich die Sperre von mandari 2026, explore/ergebnisse/sessionnet_befunde.tsv); der nächste Versuch
  folgt im nächsten Zeitfenster. Welche Abbrüche als Nacht mit möglicher Sperre zählen (dann nach drei Nächten in
  Folge sieben Tage Pause), regelt sessionnet.py (`moegliche_sperre`)
- ebenso eine abgeschnittene oder unlesbare Antwort (http.client.HTTPException, kein OSError: IncompleteRead bei
  weniger Bytes als Content-Length oder chunked ohne Abschluss, BadStatusLine, LineTooLong, RemoteDisconnected …),
  auch als Antwort eines Proxys auf CONNECT: Art `sperre`, keine Wiederholung
- scheitert die Zertifikatsprüfung (ssl.SSLCertVerificationError, auch als Grund eines URLError,
  „CERTIFICATE_VERIFY_FAILED“), ist das eine Einstellung der Ausführungsumgebung (Zertifikatsspeicher, CA eines
  Proxys), keine mögliche Sperre: Abbruch der Art `tls` ohne Wiederholung, laut (Warnung, sessionnet.py), gezählt als
  Fehler, nicht als Anfrage (die HTTP-Anfrage wurde nicht gesendet); die 12-Stunden-Regel gilt über
  `letzter_abbruch`. Andere TLS-Fehler (unerwartetes Ende, Reset im Handshake) können eine Sperre sein: Art `sperre`
- eine ungültige Adresse wird nicht gesendet und nicht als Anfrage gezählt: Art `adresse`, keine Sperre. Dazu zählen
  Zeichen außerhalb von ASCII (etwa Umlaute in links.next), ein anderes Schema als http oder https (auch ftp:, file:,
  data:), eine Adresse ohne Host (http:///…, https:papers), ein Port außerhalb 0–65535 und http.client.InvalidURL (z. B.
  ein Leerzeichen). Der Öffner kennt nur http und https (keine Handler für FTP, Dateien und data:)
- jeder andere ValueError vor dem Senden ist ein Einstellungs- oder Programmfehler: Kopfzeile nicht kodierbar
  (UnicodeEncodeError, etwa RATSATLAS_KONTAKT mit Zeichen außerhalb von Latin-1) oder mit Zeilenumbruch, Host nicht als
  IDNA kodierbar, unlesbare Proxy-Adresse. Nichts geht hinaus, nichts wird gezählt; der Fehler wird laut weitergereicht
  (kein Sperrverdacht, keine Pause). Einen User-Agent mit Steuerzeichen lehnt `get_json` schon vor der Anfrage ab
- Weiterleitungen (HTTP 3xx) werden nicht verfolgt (modulweiter Öffner `_OEFFNER` aus `oeffner()` mit
  `_OhneWeiterleitung`; der Standard von urllib bleibt für andere Module unverändert): Abbruch der Art `weiterleitung`
  mit der Ziel-URL in Meldung und `Abbruch.ziel`, gezählt in `statistik()["weiterleitungen"]` und als Fehler
  (Abrufstatistik: Spalten `weiterleitungen` und `fehler`, Ziel in `ergebnis`); sonst kämen ungezählte Anfragen an
  einen anderen Host oder Pfad hinzu. Ebenso bei einem unlesbaren Ziel (etwa „http://[::1“, roh übernommen): Die
  Anfrage hat die Stadt erreicht und wird gezählt, kein Programmfehler
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
- `stadt()` erkennt Adressen der Stadt (stadt-koeln.de, offenedaten-koeln.de, Host der eingestellten OParl-API);
  pipeline/net.py verweigert damit seine Anfragen an die Stadt, auch als Ziel einer Weiterleitung. Module, die
  direkt über urllib abrufen (geodaten.py, ebenen.py, kontext.py u. a.), erfasst dieser Schutz nicht
- eine Uhr für alle Zeitpunkte (`uhr()`, UTC): Zeitfenster, Retry-After und der Zustand in sessionnet.py; Tests
  ersetzen sie durch eine Scheinuhr
- Dateien (`get_datei`, nur für pipeline/dokumente.py, Entscheidung 13.11.2026): derselbe Kern wie `get_json`
  (`_anfrage`: Freigabe, Abstand ab dem Ende der letzten Antwort gleich welcher Art, Zeitfenster vor jedem Versuch,
  Pausen, Weiterleitungen, Fehlerarten, Zählwerk); zusätzlich höchstens n Byte (Content-Length oder gelesen; Abbruch
  der Art `zu_gross`, kein Sperrsignal), eine Gesamtfrist für die ganze Antwort ab dem Senden (Art `sperre`, mögliche
  Sperre wie eine Zeitüberschreitung), Zeitüberschreitung des Sockets 60 s und nur PDF-Dateien (Kennung „%PDF-“ in den
  ersten 1024 Byte, sonst Art `unlesbar` ohne Wiederholung: etwa eine Anmelde- oder Sperrseite). Die Gesamtfrist
  sichert ein Wächter (SIGALRM, wie explore/abruf.py; nur im Hauptthread), der auch einen hängenden Verbindungsaufbau
  oder tröpfelnden Kopf beendet; dazu wird der Inhalt in Blöcken mit höchstens einem Lesevorgang gelesen (read1) und
  die Frist nach jedem geprüft (ohne Wächter außerhalb des Hauptthreads: höchstens Frist plus Zeitüberschreitung des
  Sockets für den Inhalt; der Kopf ist dann nur durch die Zeitüberschreitung je Lesevorgang begrenzt; Prüfung dok-f).
- Gesamtfrist auch für die Metadaten (`get_json`, `JSON_FRIST` = 120 s ab dem Senden; Prüfung dok-f, Punkt 8): derselbe
  Wächter und dieselbe Prüfung nach jedem Block (read1) wie bei `get_datei`; Abbruch der Art `sperre` (mögliche Sperre
  wie eine Zeitüberschreitung, die Abrufpolitik bleibt gleich). Eine Seite mit 100 Vorlagen dauerte in Köln rund 5 s;
  die Frist greift nur bei einer Antwort, die insgesamt nicht fertig wird (tröpfelnd). Abgeschnittene Antworten melden
  dieselbe IncompleteRead wie vorher mit r.read() (Nächte ohne tröpfelnde Antwort bleiben in Anfragen und Zustand
  gleich, tests/test_gesamtfrist_json.py)
"""
import email.utils
import http.client
import json
import math
import os
import re
import signal
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as uhrzeit, timedelta, timezone
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
# Domains der Stadt Köln (auch Unterdomains), für `stadt()`
STADT_DOMAINS = ("stadt-koeln.de", "offenedaten-koeln.de")
ORTSZEIT = ZoneInfo("Europe/Berlin")
# Retry-After über die Nacht hinaus (`Abbruch.nicht_vor`): höchstens 30 Tage; ein unlesbarer Wert gilt als 7 Tage
RETRY_AFTER_HOECHSTENS = timedelta(days=30)
RETRY_AFTER_UNLESBAR = timedelta(days=7)


def uhr():
    """Aktuelle Zeit (UTC) für Zeitfenster, Retry-After und den Zustand des Abrufs; Tests ersetzen sie (Scheinuhr)."""
    return datetime.now(timezone.utc)


class Abbruch(RuntimeError):
    """Der Abruf wird beendet; der letzte gültige Datenstand bleibt erhalten. `art`: sperre, proxy, tls, weiterleitung,
    zeitfenster, gesperrt, http, aufgegeben, unlesbar, adresse, zu_gross (nur get_datei), liste, obergrenze, filter oder
    leer (die letzten vier aus sessionnet.py); `ziel`: Ziel einer Weiterleitung; `code`:
    HTTP-Status (bei http, bei aufgegeben nach HTTP 429/5xx oder CONNECT-Antwort 429/503, bei sperre nach einer
    CONNECT-Antwort wie 502/504), sonst None; `nicht_vor`: Zeitpunkt (UTC) aus einem Retry-After, vor dem keine
    Anfrage folgen soll, sonst None."""

    def __init__(self, meldung, art="", ziel="", code=None, nicht_vor=None):
        super().__init__(meldung)
        self.art = art
        self.ziel = ziel
        self.code = code
        self.nicht_vor = nicht_vor


class _OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Weiterleitung: urllib meldet 3xx dann als HTTPError mit dem Location-Kopf (wie explore/abruf.py).
    Die Methoden http_error_3xx selbst lesen den Kopf nicht: Die geerbten zerlegten ihn vorher (urlparse, urljoin)
    und scheiterten an einem unlesbaren Ziel wie „http://[::1“ mit ValueError, nachdem die Anfrage die Stadt erreicht
    hat."""

    def http_error_302(self, req, fp, code, msg, headers):
        return None   # HTTPDefaultErrorHandler meldet HTTPError mit dem Kopf, ohne ihn zu zerlegen

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def oeffner(proxies=None):
    """Öffner für dieses Modul: nur http und https (ohne Handler für FTP, Dateien, data: und unbekannte Schemata), ohne
    Weiterleitung. `proxies`: None = Proxy aus der Umgebung (beim Bau gelesen), {} = ohne Proxy."""
    o = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(proxies), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
              urllib.request.HTTPDefaultErrorHandler(), _OhneWeiterleitung(), urllib.request.HTTPErrorProcessor()):
        o.add_handler(h)
    return o


# modulweiter Öffner (Proxy aus der Umgebung beim Import); urllib.request.urlopen und der Standard-Öffner bleiben für
# andere Module (Geodaten, Kontextdaten) unverändert
_OEFFNER = oeffner()


def lokal(url):
    """Lokaler Testserver: Schema http und Host 127.0.0.1, localhost oder ::1 (über urlsplit). Adressen wie
    http://localhost.example.org/ oder http://127.0.0.1.nip.io/ gelten nicht als lokal."""
    try:
        teile = urllib.parse.urlsplit(url)
        return teile.scheme == "http" and teile.hostname in LOKALE_HOSTS
    except ValueError:   # z. B. unvollständige IPv6-Adresse
        return False


def stadt(url):
    """Adresse eines Servers der Stadt Köln? Host stadt-koeln.de oder offenedaten-koeln.de (auch Unterdomains) oder
    der Host der eingestellten OParl-API (`config.OPARL_BODY`, `config.OPARL_SYSTEM`), sofern dieser nicht lokal ist.
    Eine unlesbare Adresse gilt vorsichtshalber als Adresse der Stadt."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").rstrip(".")
    except (ValueError, TypeError, AttributeError):
        return True
    if any(host == d or host.endswith("." + d) for d in STADT_DOMAINS):
        return True
    eigene = set()
    for adresse in (config.OPARL_BODY, config.OPARL_SYSTEM):
        try:
            if not lokal(adresse):
                eigene.add((urllib.parse.urlsplit(adresse).hostname or "").rstrip("."))
        except ValueError:
            pass
    return bool(host) and host in eigene


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


def zertifikatsfehler(fehler):
    """Ist der Fehler eine gescheiterte Zertifikatsprüfung (ssl.SSLCertVerificationError oder ein SSL-Fehler mit
    „CERTIFICATE_VERIFY_FAILED“, auch als Grund eines URLError)? Andere SSL-Fehler (SSLEOFError, Reset im Handshake)
    zählen nicht dazu: Sie können eine Sperre sein."""
    if isinstance(fehler, urllib.error.HTTPError):
        return False
    grund = fehler.reason if isinstance(fehler, urllib.error.URLError) else fehler
    return isinstance(grund, ssl.SSLCertVerificationError) or (
        isinstance(grund, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(grund))


def _tls_abbruch(url, fehler):
    """Zertifikatsprüfung gescheitert: nicht gesendet, also keine Anfrage (der Zähler wird zurückgesetzt), aber ein
    Fehler; Art `tls`, keine mögliche Sperre."""
    _zaehler["anfragen"] -= 1
    return Abbruch(f"Zertifikatsprüfung fehlgeschlagen (TLS): {url} ({fehler}); keine HTTP-Anfrage gesendet. Vermutlich "
                   "eine Einstellung der Ausführungsumgebung (Zertifikatsspeicher, CA eines Proxys); Zertifikat der "
                   "Gegenseite oder Sperrseite nicht ausgeschlossen", "tls")


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


def _ortszeit(jetzt=None):
    """`jetzt` als Ortszeit Köln: ohne Angabe die aktuelle Zeit, ohne Zone als Ortszeit gelesen, sonst umgerechnet."""
    if jetzt is None:
        return uhr().astimezone(ORTSZEIT)
    return jetzt.replace(tzinfo=ORTSZEIT) if jetzt.tzinfo is None else jetzt.astimezone(ORTSZEIT)


def _fenster():
    """(von, bis) des Zeitfensters in vollen Stunden Ortszeit; None ohne Zeitfenster."""
    fenster = (config.ABRUF_ZEITFENSTER or "").strip()
    if not fenster:
        return None
    von, bis = (int(x) for x in fenster.split("-"))
    return von, bis


def im_zeitfenster(jetzt=None):
    f = _fenster()
    if f is None:
        return True
    von, bis = f
    h = _ortszeit(jetzt).hour
    return von <= h < bis if von < bis else (h >= von or h < bis)


def fenster_ende(jetzt=None):
    """Ende des laufenden Zeitfensters als Zeitpunkt mit Zone (Ortszeit Köln); None ohne Zeitfenster oder bei einem
    Fenster über den ganzen Tag (von = bis). Voraussetzung: `jetzt` liegt im Fenster."""
    f = _fenster()
    if f is None or f[0] == f[1]:
        return None
    von, bis = f
    ort = _ortszeit(jetzt)
    tag = ort.date()
    if von > bis and ort.hour >= von:   # Fenster über Mitternacht, jetzt vor Mitternacht: Ende am nächsten Tag
        tag += timedelta(days=1)
    tag += timedelta(days=bis // 24)
    return datetime.combine(tag, uhrzeit(bis % 24), tzinfo=ORTSZEIT)


def fenster_offen_nach(sekunden, jetzt=None):
    """Ist das Zeitfenster jetzt offen und endet eine Pause von `sekunden` vor dem Ende des laufenden Fensters? Gerechnet
    in UTC (Zeitumstellung); eine Pause, die erst im Fenster einer späteren Nacht endet, zählt nicht als offen."""
    ort = _ortszeit(jetzt)
    if not im_zeitfenster(ort):
        return False
    ende = fenster_ende(ort)
    if ende is None:
        return True
    rest = (ende.astimezone(timezone.utc) - ort.astimezone(timezone.utc)).total_seconds()
    return sekunden < rest


_SEKUNDEN = re.compile(r"[0-9]+")


def retry_after_sekunden(wert, jetzt=None):
    """`Retry-After` in Sekunden (ab `jetzt`, UTC): Sekundenzahl oder HTTP-Datum (RFC 9110); fehlt der Kopf, 0; ein
    Datum in der Vergangenheit ergibt 0. Mehr als 12 Ziffern (ohne führende Nullen): math.inf, länger als jede Pause
    (int() lehnte über 4300 Ziffern ab; gespeichert wird höchstens RETRY_AFTER_HOECHSTENS). Unlesbar (auch negativ):
    None."""
    wert = (wert or "").strip()
    if not wert:
        return 0
    if _SEKUNDEN.fullmatch(wert):
        ziffern = wert.lstrip("0") or "0"
        return int(ziffern) if len(ziffern) <= 12 else math.inf
    try:
        datum = email.utils.parsedate_to_datetime(wert)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if datum is None:
        return None
    if datum.tzinfo is None:   # „-0000“: UTC ohne Angabe der Quelle
        datum = datum.replace(tzinfo=timezone.utc)
    jetzt = jetzt or uhr()
    return max(0, math.ceil((datum - jetzt).total_seconds()))


def nicht_vor(retry_after):
    """Zeitpunkt (UTC), vor dem nach einem Retry-After keine Anfrage folgt: jetzt + Retry-After, höchstens
    RETRY_AFTER_HOECHSTENS (auch für Werte, die als Zeitspanne nicht darstellbar wären); unlesbar (None):
    RETRY_AFTER_UNLESBAR; ohne Retry-After (0): None."""
    if retry_after is None:
        return uhr() + RETRY_AFTER_UNLESBAR
    if retry_after <= 0:
        return None
    return uhr() + timedelta(seconds=min(retry_after, RETRY_AFTER_HOECHSTENS.total_seconds()))


def _aufgegeben(url, letzter_fehler, versuche, grund="", retry_after=0):
    code = getattr(letzter_fehler, "code", None) if isinstance(letzter_fehler, urllib.error.HTTPError) else \
        tunnel_status(letzter_fehler)
    return Abbruch(f"aufgegeben nach {versuche} Versuch(en){grund}: {url} ({letzter_fehler})", "aufgegeben", code=code,
                   nicht_vor=nicht_vor(retry_after))


def adresse_pruefen(url):
    """Grund, aus dem eine Adresse nicht gesendet wird, sonst None: Zeichen außerhalb von ASCII, anderes Schema als
    http oder https, kein Host, unlesbarer Port."""
    if not url.isascii():   # z. B. Umlaute in links.next: http.client scheiterte beim Kodieren
        return "Zeichen außerhalb von ASCII"
    try:
        teile = urllib.parse.urlsplit(url)
        teile.port   # Port außerhalb 0–65535 oder keine Zahl: ValueError
    except ValueError as e:
        return f"unlesbar ({e})"
    if teile.scheme not in ("http", "https"):
        return f"Schema {teile.scheme or '(fehlt)'} statt http oder https"
    if not teile.hostname:
        return "ohne Host"
    return None


def _kopf_pruefen():
    """User-Agent ohne Steuerzeichen (etwa ein Zeilenumbruch in RATSATLAS_KONTAKT): sonst ValueError vor der Anfrage,
    ein Einstellungsfehler (laut, kein Sperrverdacht)."""
    if any(ord(z) < 32 or ord(z) == 127 for z in config.USER_AGENT):
        raise ValueError(f"User-Agent enthält Steuerzeichen (RATSATLAS_KONTAKT prüfen): {config.USER_AGENT!r}; keine "
                         "Anfrage gesendet")


def statistik():
    return dict(_zaehler)


class _Grenze(Exception):
    """Grenze beim Lesen einer Antwort: `art` „zu_gross“ (nur get_datei: mehr als die erlaubte Größe laut
    Content-Length oder beim Lesen) oder „frist“ (get_json und get_datei: Antwort dauert insgesamt länger als die
    Frist). Kein OSError, kein ValueError und keine HTTPException: _anfrage wertet sie eigens aus."""

    def __init__(self, art, meldung):
        super().__init__(meldung)
        self.art = art


class _Frist(BaseException):
    """Der Wächter (SIGALRM, get_json und get_datei) meldet: Die Gesamtfrist einer Antwort ist abgelaufen.
    BaseException, damit kein `except Exception` unterwegs (urllib, http.client) sie verschluckt."""


_frist_aktiv = False   # der Wächter darf auslösen (ein verspätet zugestelltes SIGALRM danach bleibt ohne Wirkung)


def _frist_abgelaufen(_nummer, _rahmen):
    if _frist_aktiv:
        raise _Frist()


def _waechter_an(frist):
    """Wächter für die Gesamtfrist ab dem Senden (wie explore/abruf.py): SIGALRM nach `frist` Sekunden beendet das
    Warten auf Verbindungsaufbau, Handshake, Kopf oder Inhalt (_Frist). Nur im Hauptthread (Signale) und nur mit einer
    Frist; sonst ohne Wächter (dann gilt nur die Prüfung nach jedem Block in _begrenzt_lesen). Die Behandlung von
    SIGALRM bleibt danach gesetzt, ohne Wirkung (die Vorgabe für SIGALRM beendete den Prozess bei einem verspätet
    zugestellten Signal); die Pipeline nutzt SIGALRM sonst nicht. Liefert, ob der Wächter läuft."""
    global _frist_aktiv
    if not frist or frist <= 0 or not hasattr(signal, "setitimer") \
            or threading.current_thread() is not threading.main_thread():
        return False
    signal.signal(signal.SIGALRM, _frist_abgelaufen)
    _frist_aktiv = True
    signal.setitimer(signal.ITIMER_REAL, frist)
    return True


def _waechter_aus(aktiv):
    """Wächter abstellen (zuerst ohne Wirkung, dann den Zeitgeber)."""
    global _frist_aktiv
    if aktiv:
        _frist_aktiv = False
        signal.setitimer(signal.ITIMER_REAL, 0)


class _Wiederholen(Exception):
    """Antwort unlesbar (etwa kein JSON): wie HTTP 429/5xx mit Pausen wiederholen; `ursache`: der eigentliche Fehler."""

    def __init__(self, ursache):
        super().__init__(str(ursache))
        self.ursache = ursache


# Gesamtfrist je Antwort beim Abruf der Metadaten (get_json): Sekunden ab dem Senden für Verbindungsaufbau, Kopf und
# Inhalt. Gemessen dauerte eine Seite mit 100 Vorlagen in Köln rund 5 s (Stufe 2: 5,07 s, explore/STUFEN.md); 120 s
# liegen weit darüber und über der Zeitüberschreitung von 90 s je Lesevorgang, greifen also nur bei einer Antwort, die
# insgesamt nicht fertig wird (tröpfelnd: jeder Lesevorgang vor den 90 s, das Ganze nie; Prüfung dok-f, Punkt 8)
JSON_FRIST = 120
# Größe eines Blocks beim Lesen mit Frist (read1: höchstens ein Lesevorgang je Block)
BLOCK = 65536


def _json_lesen(frist):
    """Leser für get_json: der ganze Inhalt wie bisher mit r.read(), aber in Blöcken mit höchstens einem Lesevorgang
    (read1), und die Gesamtfrist `frist` ab dem Senden (`start`) wird nach jedem Block geprüft, auch nach dem letzten,
    leeren (später Abschluss); sonst _Grenze „frist“ (Art `sperre`, mögliche Sperre wie eine Zeitüberschreitung). Dazu
    der Wächter in _anfrage (Hauptthread), der auch einen tröpfelnden Kopf beendet. Abgeschnittene Antworten melden
    dieselbe http.client.IncompleteRead wie r.read() (gleiche Zahl gelesener Bytes): weniger Bytes als Content-Length
    mit allen gelesenen Bytes, chunked ohne Abschluss nur mit den vollständig gelesenen Abschnitten. So bleiben Nächte
    ohne tröpfelnde Antwort in Anfragen, Zustand und Meldungen gleich (tests/test_gesamtfrist_json.py). Eine Antwort
    ohne read1 (Scheinantworten der Tests) wird wie bisher als Ganzes gelesen, die Frist danach geprüft."""
    def lesen(r, start):
        block = getattr(r, "read1", None)
        if block is None:
            daten = r.read()
        else:
            teile, n, fertig = [], 0, 0
            while True:
                try:
                    teil = block(BLOCK)
                except http.client.IncompleteRead as e:   # chunked ohne Abschluss: wie r.read() (_read_chunked)
                    raise http.client.IncompleteRead(b"".join(teile)[:fertig]) from e
                if time.monotonic() - start > frist:
                    raise _Grenze("frist", f"Antwort nach {frist:g} s nicht vollständig")
                if not teil:
                    break
                teile.append(teil)
                n += len(teil)
                if getattr(r, "chunk_left", None) == 0:   # chunked: Abschnitt vollständig gelesen
                    fertig = n
            daten = b"".join(teile)
            # weniger Bytes als Content-Length: http.client zählt den Rest in `length` (read1 meldet ihn nicht)
            rest = getattr(r, "length", None)
            if isinstance(rest, int) and rest > 0:
                raise http.client.IncompleteRead(daten, rest)
        if time.monotonic() - start > frist:
            raise _Grenze("frist", f"Antwort nach {frist:g} s nicht vollständig")
        return daten
    return lesen


def _json_auswerten(url, daten):
    """JSON-Objekt aus der Antwort. Unlesbar (kein JSON, falsche Kodierung, zu tief verschachtelt): _Wiederholen.
    strict=False: rohe Steuerzeichen in Zeichenketten (etwa \\x0b in einem Titel) machen eine Seite nicht unlesbar
    (sonst Wiederholungen mit langen Pausen, dann „aufgegeben“ als mögliche Sperre)."""
    try:
        return json.loads(daten, strict=False)
    except (ValueError, RecursionError) as e:
        raise _Wiederholen(e) from e


def _json_pruefen(url, antwort):
    if not isinstance(antwort, dict):   # gültiges JSON in unerwarteter Form: kein Überlastungssignal
        _zaehler["fehler"] += 1
        raise Abbruch(f"unerwartete Antwortform (JSON-Objekt erwartet, erhalten: "
                      f"{type(antwort).__name__}): {url}", "unlesbar")
    return antwort


def get_json(url, pausen=None):
    """Eine Anfrage nach der Abrufpolitik; liefert das JSON-Objekt. Insgesamt höchstens JSON_FRIST Sekunden ab dem
    Senden für Verbindungsaufbau, Kopf und Inhalt (Wächter und Prüfung nach jedem Block, wie get_datei; sonst Art
    `sperre`, mögliche Sperre wie eine Zeitüberschreitung), Zeitüberschreitung des Sockets 90 s."""
    return _anfrage(url, pausen, "application/json", _json_lesen(JSON_FRIST), _json_auswerten, _json_pruefen, 90,
                    JSON_FRIST)


# Dateien (get_datei): Kennung am Anfang einer PDF-Datei; die Spezifikation erlaubt davor bis zu 1024 Byte
PDF_KENNUNG = b"%PDF-"
PDF_KENNUNG_BEREICH = 1024


def _begrenzt_lesen(hoechstens, frist):
    """Leser für get_datei: höchstens `hoechstens` Byte (sonst _Grenze „zu_gross“, ohne den Rest zu lesen; eine größere
    Content-Length schon vor dem Lesen), insgesamt höchstens `frist` Sekunden ab dem Senden (`start`; sonst _Grenze
    „frist“). Gelesen wird in Blöcken mit höchstens einem Lesevorgang (read1: kommt ein Byte, kehrt er zurück, statt auf
    den ganzen Block zu warten), die Frist wird nach jedem geprüft, auch nach dem letzten, leeren (später Abschluss).
    Ohne Wächter (außerhalb des Hauptthreads) dauert eine tröpfelnde Antwort so höchstens die Frist plus die
    Zeitüberschreitung des Sockets; mit Wächter (_waechter_an) endet sie mit der Frist. Weniger Bytes als
    Content-Length: http.client.IncompleteRead wie bei get_json (abgeschnittene Antwort, mögliche Sperre)."""
    def lesen(r, start):
        kopf = getattr(r, "headers", None)
        laenge = (kopf.get("Content-Length") or "").strip() if kopf is not None else ""
        laenge = int(laenge) if laenge.isdigit() and len(laenge) <= 15 else None
        if laenge is not None and laenge > hoechstens:
            raise _Grenze("zu_gross", f"Content-Length {laenge} Byte über der Grenze von {hoechstens} Byte")
        block = getattr(r, "read1", None) or r.read
        teile, n = [], 0
        while True:
            teil = block(min(65536, hoechstens + 1 - n))
            if time.monotonic() - start > frist:
                raise _Grenze("frist", f"Antwort nach {frist:g} s nicht vollständig")
            if not teil:
                break
            n += len(teil)
            teile.append(teil)
            if n > hoechstens:
                raise _Grenze("zu_gross", f"mehr als {hoechstens} Byte")
        if laenge is not None and n < laenge:
            raise http.client.IncompleteRead(b"", laenge - n)
        return b"".join(teile)
    return lesen


def _pdf_auswerten(url, daten):
    return daten


def _pdf_pruefen(url, daten):
    """Nur PDF-Dateien: Fehlt die Kennung „%PDF-“ in den ersten 1024 Byte (etwa eine HTML-Seite, eine Anmelde- oder
    Sperrseite mit Status 200), Abbruch der Art `unlesbar` ohne Wiederholung (in sessionnet.moegliche_sperre eine Nacht
    mit möglicher Sperre). Der Inhalt erscheint in keiner Meldung."""
    if PDF_KENNUNG not in daten[:PDF_KENNUNG_BEREICH]:
        _zaehler["fehler"] += 1
        raise Abbruch(f"keine PDF-Datei (Kennung %PDF- fehlt; etwa eine HTML-, Anmelde- oder Sperrseite): {url}",
                      "unlesbar")
    return daten


def get_datei(url, hoechstens, frist, pausen=None):
    """Eine Datei (PDF) nach derselben Abrufpolitik und mit demselben Abstand, Zeitfenster und Zählwerk wie get_json
    (pipeline/dokumente.py): Freigabe, Kontakt im User-Agent, eine Verbindung, Abstand ab dem Ende der letzten Antwort
    (auch einer JSON-Antwort desselben Prozesses), Zeitfenster vor jedem Versuch, Pausen nach 429/5xx nie über das
    Fenster hinaus, keine Weiterleitung, 401/403/404 sofortiger Abbruch. Zusätzlich: höchstens `hoechstens` Byte
    (Abbruch der Art `zu_gross`, kein Sperrsignal; die Anfrage zählt), insgesamt höchstens `frist` Sekunden ab dem
    Senden für Verbindungsaufbau, Kopf und Inhalt (Wächter und Prüfung nach jedem Block; Art `sperre`, mögliche Sperre
    wie eine Zeitüberschreitung), Zeitüberschreitung des Sockets 60 s, Antwort muss eine PDF-Datei sein (sonst Art
    `unlesbar`). Liefert die Bytes; der Aufrufer hält sie nur im Arbeitsspeicher."""
    return _anfrage(url, pausen, "application/pdf", _begrenzt_lesen(hoechstens, frist), _pdf_auswerten, _pdf_pruefen,
                    60, frist)


def _anfrage(url, pausen, accept, lesen, auswerten, pruefen, timeout, frist=None):
    """Eine Anfrage nach der Abrufpolitik (gemeinsam für get_json und get_datei): `lesen(r, start)` liest die Antwort
    (`start`: Zeitpunkt des Sendens, time.monotonic), `auswerten(url, daten)` wandelt sie um (_Wiederholen: unlesbar,
    mit Pausen wiederholen), `pruefen(url, wert)` prüft die Form (Abbruch ohne Wiederholung). `frist`: Gesamtfrist je
    Versuch ab dem Senden mit Wächter (_waechter_an; get_json JSON_FRIST, get_datei die Lesefrist)."""
    global _letzte
    if not freigegeben(url):
        raise Abbruch("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (CLAUDE.md 9). "
                      "Freigabe mit RATSATLAS_STADT_INFORMIERT=ja.", "gesperrt")
    _kopf_pruefen()   # Einstellungsfehler: laut, vor jeder Anfrage
    grund = adresse_pruefen(url)
    if grund:   # nichts ginge hinaus (oder an ein anderes Schema): nicht gesendet, nicht gezählt, keine Sperre
        _zaehler["fehler"] += 1
        raise Abbruch(f"ungültige Adresse ({grund}), nicht gesendet: {url}", "adresse")
    ist_lokal = lokal(url)
    pausen = config.ABRUF_PAUSEN if pausen is None else pausen
    mindestens = abstand(ist_lokal)
    letzter_fehler = None

    def fenster_pruefen(versuch):
        if not ist_lokal and not im_zeitfenster():
            if letzter_fehler is not None:   # nach 429/5xx/unlesbar: zählt als aufgegeben (mögliche Sperre)
                raise _aufgegeben(url, letzter_fehler, versuch, ", Zeitfenster vorbei")
            raise Abbruch(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (RATSATLAS_ZEITFENSTER)",
                          "zeitfenster")
    for versuch in range(len(pausen) + 1):
        fenster_pruefen(versuch)
        warte = mindestens - (time.monotonic() - _letzte)
        if warte > 0:
            time.sleep(warte)
            fenster_pruefen(versuch)   # unmittelbar vor dem Senden: das Fenster kann während des Wartens enden
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": accept})
        except ValueError as e:   # von adresse_pruefen nicht erkannt: nicht gesendet, keine Sperre
            _zaehler["fehler"] += 1
            raise Abbruch(f"ungültige Adresse, nicht gesendet: {url} ({e})", "adresse") from e
        _zaehler["anfragen"] += 1
        retry_after = 0
        daten = None
        gesendet = False
        try:
            waechter = _waechter_an(frist)
            try:
                with _OEFFNER.open(req, timeout=timeout) as r:
                    gesendet = True
                    daten = lesen(r, start)   # weniger Bytes als Content-Length, chunked ohne Abschluss: IncompleteRead
            except _Frist:   # Wächter: Verbindungsaufbau, Kopf oder Inhalt nach der Frist nicht vollständig
                raise _Grenze("frist", f"Antwort nach {frist:g} s nicht vollständig (Verbindungsaufbau, Kopf oder "
                                       "Inhalt)") from None
            finally:
                _waechter_aus(waechter)
        except _Grenze as e:   # Frist überschritten (mögliche Sperre) oder (get_datei) Datei zu groß (kein Sperrsignal)
            _zaehler["sekunden"] += time.monotonic() - start
            if e.art == "frist":
                _zaehler["fehler"] += 1
                raise Abbruch(f"{e}, mögliche Sperre: {url}; nächster Versuch im nächsten Zeitfenster", "sperre") from e
            raise Abbruch(f"Datei zu groß ({e}), nicht weiter gelesen: {url}", "zu_gross") from e
        except urllib.error.HTTPError as e:
            _zaehler["fehler"] += 1
            if 300 <= e.code < 400:   # Weiterleitung: nicht folgen, Ziel nennen, abbrechen
                _zaehler["weiterleitungen"] += 1
                _zaehler["sekunden"] += time.monotonic() - start
                ort = e.headers.get("Location") if e.headers else None
                try:
                    ziel = urllib.parse.urljoin(url, ort) if ort else ""
                except ValueError:   # unlesbares Ziel (etwa „http://[::1“): roh übernehmen
                    ziel = ort
                raise Abbruch(f"Weiterleitung HTTP {e.code} nach {ziel or '(ohne Ziel)'} nicht verfolgt: {url}",
                              "weiterleitung", ziel, e.code) from e
            if proxy_ablehnung(e, url):   # HTTP 407, und für die Adresse ist ein Proxy gesetzt
                _zaehler["sekunden"] += time.monotonic() - start
                raise _proxy_abbruch(url, e.code) from e
            if e.code != 429 and e.code < 500:
                _zaehler["sekunden"] += time.monotonic() - start
                raise Abbruch(f"HTTP {e.code}: {url}", "http", code=e.code) from e
            letzter_fehler = e
            retry_after = retry_after_sekunden(e.headers.get("Retry-After") if e.headers else None)
        except http.client.InvalidURL as e:   # vor dem Senden erkannt (z. B. Leerzeichen): keine Anfrage, keine Sperre
            _zaehler["anfragen"] -= 1
            _zaehler["fehler"] += 1
            raise Abbruch(f"ungültige Adresse, nicht gesendet: {url} ({e})", "adresse") from e
        except ValueError as e:
            if zertifikatsfehler(e):   # ssl.SSLCertVerificationError ist auch ein ValueError (sonst als URLError)
                _zaehler["fehler"] += 1
                _zaehler["sekunden"] += time.monotonic() - start
                raise _tls_abbruch(url, e) from e
            # vor dem Senden: Kopfzeile nicht kodierbar (UnicodeEncodeError, etwa RATSATLAS_KONTAKT außerhalb von
            # Latin-1) oder mit Zeilenumbruch, Host nicht als IDNA kodierbar, unlesbare Proxy-Adresse. Kein
            # Sperrsignal, sondern ein Einstellungs- oder Programmfehler: laut weiterreichen, nicht als „unlesbar“
            # werten (keine Pausen); nicht gesendet, also nicht gezählt
            if not gesendet:
                _zaehler["anfragen"] -= 1
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as e:
            # HTTPException (kein OSError): Antwort abgeschnitten (IncompleteRead) oder unlesbar (BadStatusLine,
            # LineTooLong …), auch als Antwort des Proxys auf CONNECT – wie ein Verbindungsabbruch
            _zaehler["fehler"] += 1
            if zertifikatsfehler(e):   # Einstellung der Ausführungsumgebung: keine HTTP-Anfrage, keine Sperre
                _zaehler["sekunden"] += time.monotonic() - start
                raise _tls_abbruch(url, e) from e
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
        finally:   # der Abstand gilt ab dem Ende der Antwort, auch nach Fehlern
            _letzte = time.monotonic()
        if daten is not None:
            _zaehler["bytes"] += len(daten)
            try:
                antwort = auswerten(url, daten)
            except _Wiederholen as e:   # unlesbar: kein JSON, falsche Kodierung, zu tief verschachtelt
                _zaehler["fehler"] += 1
                letzter_fehler = e.ursache
            else:
                _zaehler["sekunden"] += time.monotonic() - start
                return pruefen(url, antwort)
        _zaehler["sekunden"] += time.monotonic() - start
        if versuch < len(pausen):
            # Sofort aufgeben (zählt als Nacht mit möglicher Sperre), statt eine Pause abzuwarten, die nicht passt;
            # ein Retry-After gilt dann über die Nacht hinaus (Abbruch.nicht_vor)
            if retry_after is None:
                raise _aufgegeben(url, letzter_fehler, versuch + 1, ", Retry-After unlesbar", retry_after)
            if retry_after > max(pausen):
                dauer = f"{retry_after} s" if math.isfinite(retry_after) else "mit mehr als 12 Ziffern"
                raise _aufgegeben(url, letzter_fehler, versuch + 1,
                                  f", Retry-After {dauer} länger als die längste Pause ({max(pausen)} s)", retry_after)
            pause = max(pausen[versuch], retry_after)
            if not ist_lokal and not fenster_offen_nach(pause):
                raise _aufgegeben(url, letzter_fehler, versuch + 1, ", nächste Pause reicht über das Zeitfenster",
                                  retry_after)
            _zaehler["wiederholungen"] += 1
            time.sleep(pause)
    raise _aufgegeben(url, letzter_fehler, len(pausen) + 1, retry_after=retry_after)
