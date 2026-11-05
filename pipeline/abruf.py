"""Abruf der Kölner OParl-API nach der Abrufpolitik (CLAUDE.md 5.1); nur Standardbibliothek.

- genau eine Verbindung, mindestens `config.ABRUF_ABSTAND` Sekunden zwischen zwei Anfragen
- nur im nächtlichen Zeitfenster (`config.ABRUF_ZEITFENSTER`, Ortszeit Köln), sofern gesetzt
- nach HTTP 429, 5xx und unlesbaren Antworten wachsende Pausen (`config.ABRUF_PAUSEN`, bis zu mehreren Stunden);
  einen `Retry-After`-Kopf hält der Abruf mindestens ein; 401, 403 und 404 brechen sofort ab
- Zeitüberschreitung und Verbindungsabbruch gelten als mögliche Sperre: sofortiger Abbruch ohne Wiederholung
  (so zeigte sich die Sperre von mandari 2026, explore/ergebnisse/sessionnet_befunde.tsv); der nächste Versuch
  folgt im nächsten Zeitfenster, nach drei solchen Nächten in Folge pausiert der Abruf (sessionnet.py)
- das Zeitfenster wird vor jedem Versuch geprüft, auch nach einer Pause
- offener User-Agent mit Projektadresse und Kontakt (`RATSATLAS_KONTAKT`)
- Zählwerk je Lauf für die Abrufstatistik (`statistik()`)
- Sperre: ohne `RATSATLAS_STADT_INFORMIERT=ja` keine Anfrage an die Stadt (Entscheidung 04.11.2026)
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

_letzte = 0.0
_zaehler = {"anfragen": 0, "fehler": 0, "wiederholungen": 0, "bytes": 0, "sekunden": 0.0}


class Abbruch(RuntimeError):
    """Der Abruf wird beendet; der letzte gültige Datenstand bleibt erhalten. `art`: sperre, zeitfenster, http,
    aufgegeben, liste oder leer."""

    def __init__(self, meldung, art=""):
        super().__init__(meldung)
        self.art = art


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
            with urllib.request.urlopen(req, timeout=90) as r:
                daten = r.read()
            _zaehler["bytes"] += len(daten)
            _zaehler["sekunden"] += time.monotonic() - start
            return json.loads(daten)
        except urllib.error.HTTPError as e:
            _zaehler["fehler"] += 1
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
