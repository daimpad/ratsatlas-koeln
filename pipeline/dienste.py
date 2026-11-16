"""Höflicher Abruf weiterer Datendienste der Stadt Köln für Zusatzthemen: Baustellen (WFS, pipeline/baustellen.py) und
„Sag’s uns“ (Open311, pipeline/anliegen.py); nur Standardbibliothek. Vorbereitet am 16.11.2026 ohne eine einzige
Anfrage (Entscheidung 16.11.2026 (1): Adapter mit erfundenen Daten; tägliche Abrufe an weitere Server der Stadt
brauchen eine eigene Freigabe).

Eine Anfrage geht nur hinaus, wenn alles erfüllt ist; sonst `NichtGesendet` (nichts gesendet, nichts gezählt):
1. das Zusatzthema ist in `config.ZUSATZTHEMEN` eingeschaltet (gilt auch für lokale Testserver);
2. für jede nicht lokale Adresse die eigene Freigabe des täglichen Abrufs, `<THEMA>_ABRUF=ja` (`BAUSTELLEN_ABRUF`,
   `ANLIEGEN_ABRUF`; wie `STRUKTURDATEN_ABRUF` in pipeline/strukturdaten.py);
3. für Server der Stadt (`abruf.stadt`: stadt-koeln.de mit Unterdomains wie geoportal. und sags-uns.) zusätzlich
   `RATSATLAS_STADT_INFORMIERT=ja` und das Zeitfenster (`config.ABRUF_ZEITFENSTER`, Ortszeit Köln), geprüft vor der
   Anfrage und noch einmal unmittelbar vor dem Senden (das Fenster kann während des Wartens enden).
Lokal sind nur Testserver nach `abruf.lokal` (http auf 127.0.0.1, localhost, ::1); für sie entfallen 2 und 3.

Abrufpolitik wie pipeline/abruf.py und pipeline/strukturdaten.py:
- eine Verbindung: Anfragen eines Laufs nacheinander; vor der ersten Anfrage nimmt der Lauf die exklusive Sperre
  `abruf.lock` (fcntl.flock) im Ordner `RATSATLAS_SPERRE` (Vorgabe ~/.cache/ratsatlas-koeln, wie explore/abruf.py)
  und hält sie bis zum Ende; hält ein anderer Prozess sie, bricht der Lauf ohne Anfrage ab (Art `parallel`);
- User-Agent mit Projektadresse und Kontakt (`config.USER_AGENT`); ohne `RATSATLAS_KONTAKT` oder mit Steuerzeichen
  darin Einstellungsfehler (ValueError) vor der ersten Anfrage, nichts gesendet;
- mindestens `abruf.MINDESTABSTAND` (2 s) vom Ende einer Antwort bis zur nächsten Anfrage (`abruf.abstand`);
- Zeitlimit je Anfrage (`ZEITLIMIT`), Obergrenzen je Lauf (Anfragen) und je Antwort (`MAX_BYTES`);
- keine Weiterleitungen (`abruf.oeffner`), keine Wiederholung: Jeder Fehler beendet den Lauf (`Abbruch`), der nächste
  Versuch folgt im nächsten Lauf. Zeitüberschreitung, Verbindungsabbruch und abgeschnittene Antworten gelten als
  mögliche Sperre (Art `verbindung`); eine Webseite statt Daten (wie am 07.11.2026 bei ArcGIS der Stadt) als
  `unlesbar`.

Die Adapter prüfen jede Antwort, bevor sie etwas schreiben (`Schemafehler`: nichts geschrieben). So kann der erste
echte Abruf mit ungeprüften Feldnamen keine falschen Daten erzeugen.
"""
import fcntl
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import abruf, config

ZEITLIMIT = 120                  # Sekunden je Anfrage
MAX_BYTES = 50 * 1024 * 1024     # je Antwort
SPERRDATEI = "abruf.lock"        # wie explore/abruf.py


class NichtGesendet(RuntimeError):
    """Die Anfrage wurde nicht gesendet (Zusatzthema aus, ohne Freigabe, Stadt nicht informiert, Zeitfenster)."""


class Abbruch(RuntimeError):
    """Der Lauf endet. `art`: adresse, parallel, obergrenze, http, weiterleitung, tls, verbindung, unlesbar, groesse,
    leer; `code`: HTTP-Status bei http und weiterleitung."""

    def __init__(self, meldung, art="", code=None):
        super().__init__(meldung)
        self.art = art
        self.code = code


class Schemafehler(RuntimeError):
    """Die Antwort passt nicht zu den erwarteten Feldern: nichts wird geschrieben."""


def sperrort():
    """Ordner der Sperrdatei (beim Aufruf gelesen): `RATSATLAS_SPERRE`, sonst ~/.cache/ratsatlas-koeln."""
    return Path(os.environ.get("RATSATLAS_SPERRE") or Path.home() / ".cache" / "ratsatlas-koeln")


def text(wert, laenge=80):
    """Wert aus einer Antwort für eine Meldung: kurz, ohne Steuerzeichen (Namen von Feldern, nie Inhalte)."""
    s = "".join(z if z.isprintable() else "?" for z in str(wert))
    return s if len(s) <= laenge else s[:laenge - 1] + "…"


class Lauf:
    """Ein Lauf eines Zusatzthemas: Prüfungen vor jeder Anfrage, Sperre, Abstand, Zählwerk. Als Kontextmanager
    verwenden (gibt die Sperre am Ende frei)."""

    def __init__(self, thema, max_anfragen):
        self.thema = thema
        self.max_anfragen = max_anfragen
        self.anfragen = 0
        self.bytes = 0
        self.letzte = None       # Ende der letzten Antwort (time.monotonic)
        self.protokoll = []      # (Zeitpunkt, Adresse, Status, Bytes, Sekunden) je Anfrage, nur im Speicher
        self._sperre = None

    @property
    def schalter(self):
        """Name der Umgebungsvariable für die Freigabe des täglichen Abrufs (z. B. BAUSTELLEN_ABRUF)."""
        return f"{self.thema.upper()}_ABRUF"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.freigeben()

    def freigeben(self):
        if self._sperre is not None:
            self._sperre.close()   # schließt die Datei und gibt die Sperre frei
            self._sperre = None

    def pruefen(self, url):
        """Gründe gegen das Senden: NichtGesendet (Lauf übersprungen), Abbruch, ValueError (Einstellungsfehler)."""
        if not config.ZUSATZTHEMEN.get(self.thema):
            raise NichtGesendet(f"Zusatzthema „{self.thema}“ ist abgeschaltet (config.ZUSATZTHEMEN)")
        grund = abruf.adresse_pruefen(url)
        if grund:
            raise Abbruch(f"ungültige Adresse ({grund}), nicht gesendet: {text(url, 200)}", "adresse")
        lokal = abruf.lokal(url)
        if not lokal and os.environ.get(self.schalter) != "ja":
            raise NichtGesendet(f"ohne Freigabe des täglichen Abrufs ({self.schalter}=ja fehlt; Entscheidung "
                                "16.11.2026: eigene Freigabe für weitere Server der Stadt)")
        if abruf.stadt(url) and not lokal:
            if os.environ.get("RATSATLAS_STADT_INFORMIERT") != "ja":
                raise NichtGesendet("gesperrt: Server der Stadt Köln (RATSATLAS_STADT_INFORMIERT=ja fehlt)")
            if not abruf.im_zeitfenster():
                raise NichtGesendet(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (Server der Stadt)")
        if not lokal and not config.KONTAKT:
            raise ValueError("RATSATLAS_KONTAKT fehlt (Kontakt im User-Agent ist Pflicht, CLAUDE.md 5.1); keine "
                             "Anfrage gesendet")
        if any(ord(z) < 32 or ord(z) == 127 for z in config.USER_AGENT):
            raise ValueError(f"User-Agent enthält Steuerzeichen (RATSATLAS_KONTAKT prüfen): {config.USER_AGENT!r}; "
                             "keine Anfrage gesendet")
        if self.anfragen >= self.max_anfragen:
            raise Abbruch(f"Obergrenze von {self.max_anfragen} Anfragen je Lauf erreicht", "obergrenze")

    def _sperre_nehmen(self):
        if self._sperre is not None:
            return
        ort = sperrort()
        ort.mkdir(parents=True, exist_ok=True)
        datei = open(ort / SPERRDATEI, "a+")
        try:
            fcntl.flock(datei.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            datei.close()
            raise Abbruch(f"Ein anderer Prozess hält die Sperre {ort / SPERRDATEI} (RATSATLAS_SPERRE); keine Anfrage "
                          "gesendet. Läufe nur nacheinander starten.", "parallel") from e
        self._sperre = datei

    def _warten(self, url):
        stadt = abruf.stadt(url) and not abruf.lokal(url)
        mindestens = abruf.abstand(abruf.lokal(url))
        if self.letzte is not None:
            rest = mindestens - (time.monotonic() - self.letzte)
            if rest > 0:
                time.sleep(rest)
        if stadt and not abruf.im_zeitfenster():
            raise NichtGesendet(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (Server der Stadt)")

    def holen(self, url, accept="application/json"):
        """Eine Anfrage ohne Wiederholung; liefert die Antwort als Bytes."""
        self.pruefen(url)
        self._sperre_nehmen()
        self._warten(url)
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": accept})
        self.anfragen += 1
        start, daten, status = time.monotonic(), b"", ""
        try:
            with abruf._OEFFNER.open(req, timeout=ZEITLIMIT) as antwort:
                status = str(antwort.status)
                teile, n = [], 0
                for teil in iter(lambda: antwort.read(1 << 16), b""):
                    n += len(teil)
                    if n > MAX_BYTES:
                        status = "zu groß"
                        raise Abbruch(f"Antwort größer als {MAX_BYTES} Bytes: {text(url, 200)}", "groesse")
                    teile.append(teil)
                daten = b"".join(teile)
        except urllib.error.HTTPError as e:
            status = str(e.code)
            if 300 <= e.code < 400:
                ort = e.headers.get("Location", "") if e.headers else ""
                raise Abbruch(f"Weiterleitung HTTP {e.code} nach {text(ort, 200) or '(ohne Ziel)'} nicht verfolgt: "
                              f"{text(url, 200)}", "weiterleitung", e.code) from e
            raise Abbruch(f"HTTP {e.code}: {text(url, 200)} (keine Wiederholung; nächster Versuch im nächsten Lauf)",
                          "http", e.code) from e
        except Abbruch:
            raise
        except http.client.InvalidURL as e:   # vor dem Senden erkannt (z. B. Leerzeichen): nicht gesendet
            self.anfragen -= 1
            status = "nicht gesendet"
            raise Abbruch(f"ungültige Adresse, nicht gesendet: {text(url, 200)}", "adresse") from e
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            if abruf.zertifikatsfehler(e):
                status = "tls"
                raise Abbruch(f"Zertifikatsprüfung fehlgeschlagen (TLS): {text(url, 200)} ({e})", "tls") from e
            if isinstance(e, ValueError):
                self.anfragen -= 1   # vor dem Senden (Kopfzeile, Proxy-Adresse): Einstellungsfehler, nichts gesendet
                status = "nicht gesendet"
                raise
            status = "verbindung"
            raise Abbruch(f"Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre: {text(url, 200)} "
                          f"({type(e).__name__}); keine Wiederholung", "verbindung") from e
        finally:
            self.letzte = time.monotonic()
            self.bytes += len(daten)
            zeit = abruf.uhr().astimezone(abruf.ORTSZEIT).isoformat(timespec="seconds")
            self.protokoll.append((zeit, url, status, len(daten), round(self.letzte - start, 2)))
        kopf = daten.lstrip()[:15].lower()
        if kopf.startswith((b"<!doctype html", b"<html")):
            raise Abbruch(f"Webseite statt Daten: {text(url, 200)}", "unlesbar")
        return daten

    def json(self, url):
        """Eine Anfrage; liefert das gelesene JSON (Objekt oder Liste), sonst Abbruch der Art `unlesbar`."""
        daten = self.holen(url)
        try:
            return json.loads(daten)
        except (ValueError, RecursionError) as e:
            raise Abbruch(f"Antwort ist kein lesbares JSON: {text(url, 200)} ({type(e).__name__})", "unlesbar") from e


PROTOKOLL_KOPF = ["zeit", "url", "status", "bytes", "sekunden"]


def protokoll_schreiben(pfad, lauf):
    """Anfragen eines Laufs an `pfad` (TSV) anhängen; nur nach bestandener Prüfung aufgerufen."""
    pfad = Path(pfad)
    neu = not pfad.exists()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("a", encoding="utf-8") as fh:
        if neu:
            fh.write("\t".join(PROTOKOLL_KOPF) + "\n")
        for zeile in lauf.protokoll:
            fh.write("\t".join(text(x, 400).replace("\t", " ") for x in zeile) + "\n")
