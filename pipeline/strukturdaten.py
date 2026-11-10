"""Strukturdaten Köln im Datenvertrag „Strukturdaten v1“ (Phase 1, Adapter; Entscheidungen 10.11.2026).

Quellen:
- Statistischer Datenkatalog Köln (Stadt Köln, Amt für Stadtentwicklung und Statistik): XLSX auf offenedaten-koeln.de,
  Datensatzseite auf open.nrw, Datenlizenz Deutschland – Namensnennung – Version 2.0. Übernommen werden die Raumebenen
  Gesamtstadt, Stadtbezirke und Stadtteile; Statistische Quartiere folgen in Phase 2 mit ihrer Geometrie, Sozialräume
  sind nicht Teil des Vertrags. Quelle der Werte ist die XLSX-Datei, nicht die CSV-Ressource (dort fallen „*“ und leere
  Zellen zusammen).
- Wegweiser Kommune (Bertelsmann Stiftung, CC0 1.0): gesamtstädtische Vergleichswerte für Bonn, Köln und Wuppertal,
  nur über friendlyUrls (numerische Kennungen wechseln mit dem Datenstand).

Schritte:
- `strukturdaten-abruf` (nur auf Freigabe, nicht im täglichen Lauf): lädt höchstens `MAX_ANFRAGEN` Dateien (je
  Quelldatei eine Anfrage und eine für die OpenAPI-Beschreibung), ohne Wiederholung (auch nicht nach HTTP 429 oder 5xx),
  ohne Weiterleitungen, mit dem User-Agent des Projekts und mindestens `abruf.MINDESTABSTAND` Sekunden zwischen den
  Anfragen. Jede Anfrage an eine nicht lokale Adresse braucht `STRUKTURDATEN_ABRUF=ja` (Freigabe je Abruf durch den
  Auftraggeber). Adressen der Stadt (`abruf.stadt`) gelten wie in pipeline/abruf.py: nur mit
  `RATSATLAS_STADT_INFORMIERT=ja` und im Zeitfenster (`config.ABRUF_ZEITFENSTER`), sonst „nicht gesendet“. Zuerst wird
  `info.version` der Wegweiser-OpenAPI mit dem zuletzt veröffentlichten Stand (meta.json) verglichen; weicht sie ab,
  bricht der Lauf vor jeder weiteren Anfrage ab (Fortsetzung nach Prüfung mit
  `STRUKTURDATEN_OPENAPI_BESTAETIGT=<neue Version>`). Rohdateien liegen im Zwischenspeicher außerhalb der versionierten
  Dateien (`STRUKTURDATEN_DL`, Vorgabe _kontext_dl/strukturdaten/), das Protokoll dort in audit_abruf.tsv (quelle, url,
  zeitstempel, http_status, zeilen, pruefsumme, hinweis). Eine Datei ersetzt die vorige erst, wenn sie vollständig und
  lesbar ist.
- `strukturdaten` (ohne Netz): normalisiert die Dateien des Zwischenspeichers (einzeln überschreibbar mit
  STRUKTURDATEN_XLSX, STRUKTURDATEN_WW_EXPORT, STRUKTURDATEN_WW_INDIKATOREN, STRUKTURDATEN_WW_REGIONEN,
  STRUKTURDATEN_WW_VERSION, STRUKTURDATEN_WW_OPENAPI, STRUKTURDATEN_PROTOKOLL) nach data/strukturdaten/
  (`STRUKTURDATEN_AUS`): indikatoren.tsv, werte.tsv, gesamtstadt.tsv, meta.json, zurueckgestellt.tsv, audit_abruf.tsv.
  Jede Eingabedatei muss mit ihrer Prüfsumme im Abrufprotokoll stehen (Herkunft und Abrufdatum).

Regeln (Vertrag Abschnitt 3): Werte unverändert; „*“ → status geheim, leere Zelle → status fehlt, beide mit leerem
Wert; keine eigenen Ableitungen in Phase 1. Zahlen mit Punkt als Dezimaltrennzeichen, ohne Tausendertrennzeichen: aus
der XLSX ganze Zahlen wie gespeichert, Gleitkommazahlen in der kürzesten Schreibweise, die denselben Wert ergibt (ohne
Exponent); aus dem Wegweiser-Export die veröffentlichten Ziffern. „k.A.“ im Wegweiser-Export ergibt keine Zeile in
gesamtstadt.tsv (der Vertrag sieht dort keinen Status vor); die betroffenen Jahre nennt der Metatext des Indikators.
`quellobjekt` in werte.tsv ist die Zelle im Blatt Daten („Daten!D2“) der Datei mit der Prüfsumme aus meta.json.

Typ, Einheit sowie Zähler und Nenner der Kölner Indikatoren stammen aus Phase 0 (pipeline/strukturdaten_koeln.tsv,
abgeleitet, nicht aus der Quelle). Zähler und Nenner stehen nur dort, wo Phase 0 sie numerisch geprüft hat, und nur,
wenn die Beziehung in der aktuellen Datei weiter in jeder Zeile gilt (Abweichung höchstens eine Einheit der letzten
veröffentlichten Stelle). In Phase 0 als unsicher eingestufte Typen, Spalten ohne Klassifikation und die
Wegweiser-Indikatoren mit einem Unternehmen als Datenhalter werden zurückgestellt (zurueckgestellt.tsv).
"""
import csv
import hashlib
import http.client
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import abruf, config

VERTRAG_VERSION = "1"
KLASSIFIKATION = Path(__file__).with_name("strukturdaten_koeln.tsv")

XLSX_URL = ("https://www.offenedaten-koeln.de/sites/default/files/uploaded_resources/"
            "Stadt_K%C3%B6ln_Statistischer%20Datenkatalog_0.xlsx")
# Datensatzseite (der Slug auf offenedaten-koeln.de lieferte am 10.11.2026 HTTP 404)
DATENSATZ_URL = "https://open.nrw/dataset/statistischer-datenkatalog-koln-k"
KOELN_TITEL = "Statistischer Datenkatalog Köln"
KOELN_HERAUSGEBER = "Stadt Köln, Amt für Stadtentwicklung und Statistik"
KOELN_LIZENZ = "Datenlizenz Deutschland – Namensnennung – Version 2.0"
KOELN_LIZENZ_URL = "https://www.govdata.de/dl-de/by-2-0"
KOELN_NAMENSNENNUNG = (f"{KOELN_HERAUSGEBER} ({KOELN_TITEL}); in lange Tabellenform umgeformt, Werte unverändert")
# Stand der Ressourcen laut open.nrw (Datensatzseite, gelesen am 10.11.2026); nur zur Begründung des Datenstands
OPEN_NRW_RESSOURCEN = "06.07.2026"

WW = "https://www.wegweiser-kommune.de"
WW_TITEL = "Wegweiser Kommune (Bertelsmann Stiftung)"
WW_LIZENZ = "Creative Commons Zero 1.0 (CC0 1.0)"
WW_LIZENZ_URL = "https://creativecommons.org/publicdomain/zero/1.0/deed.de"
WW_QUELLENANGABE = "Bertelsmann Stiftung, wegweiser-kommune.de"
WW_DATENSEITE = WW + "/open-data"
# Vergleichskommunen (friendlyUrl) und Auswahl (Priorität A und wohnflaeche-pro-person; Entscheidung 10.11.2026) mit
# dem Typ nach dem Datenvertrag. Der Typ ist eine eigene Einordnung nach Name, Einheit und Berechnung laut Wegweiser
# (wie die Regeln aus Phase 0); die Veränderungsrate hat im Vertrag keinen eigenen Typ und steht als Quote.
WW_KOMMUNEN = ("bonn", "koeln", "wuppertal")
WW_AUSWAHL = {
    "bevoelkerung": "anzahl",
    "bevoelkerungsentwicklung-ueber-die-letzten-5-jahre": "quote",
    "durchschnittsalter": "mittelwert",
    "jugendquotient": "quote",
    "altenquotient": "quote",
    "sgb-ii-quote": "quote",
    "arbeitslose-an-den-svb": "quote",
    "beschaeftigungsquote": "quote",
    "auslaenderanteil": "anteil",
    "wohnflaeche-pro-person": "mittelwert",
}
# Zurückgestellt bis zur Klärung: Datenhalter ist ein Unternehmen (Nexiga GmbH); ob die Stiftung diese Werte unter CC0
# stellen darf, ist nicht belegt (Phase 0, Entscheidung 10.11.2026)
WW_ZURUECKGESTELLT = ("einpersonen-haushalte", "haushalte-mit-kindern")
WW_UNTERNEHMEN = ("Nexiga",)
WW_JAHRE = "2006-2023"
WW_EXPORT_URL = (f"{WW}/data-api/rest/export/{'+'.join((*WW_AUSWAHL, *WW_KOMMUNEN))}+{WW_JAHRE}+tabelle.csv"
                 "?charset=UTF-8")

RAUMEBENEN = {"Gesamtstadt": "gesamtstadt", "Stadtbezirke": "stadtbezirk", "Stadtteile": "stadtteil"}
NICHT_UEBERNOMMEN = {
    "Statistische Quartiere": ("quartier", "folgt in Phase 2 mit der Quartiersgeometrie (Entscheidung 10.11.2026)"),
    "Sozialräume": ("sozialraum", "nicht Teil des Datenvertrags Strukturdaten v1 (Entscheidung 10.11.2026)"),
}
EBENEN_REIHENFOLGE = ("gesamtstadt", "stadtbezirk", "stadtteil")
TYPEN = {"anzahl", "anteil", "quote", "dichte", "mittelwert", "kategorie"}
EINWOHNER = "koeln_A0355A"   # Einwohnerzahl für die Anzeige: Hauptwohnsitz (Entscheidung 10.11.2026)
# A0025A „Einwohner*innen, gesamt“ = A0355A (Hauptwohnsitz) + A0359A (Nebenwohnsitz); im Lauf nachgerechnet
GESAMT, HAUPT, NEBEN = "A0025A", "A0355A", "A0359A"

# Dateien im Zwischenspeicher: Schlüssel → (Dateiname, Umgebungsvariable, Quelle, Kennung in meta.json)
DATEIEN = {
    "xlsx": ("statistischer_datenkatalog_koeln.xlsx", "STRUKTURDATEN_XLSX"),
    "ww_openapi": ("wegweiser_openapi.json", "STRUKTURDATEN_WW_OPENAPI"),
    "ww_version": ("wegweiser_version.txt", "STRUKTURDATEN_WW_VERSION"),
    "ww_indikatoren": ("wegweiser_indikatoren.json", "STRUKTURDATEN_WW_INDIKATOREN"),
    "ww_regionen": ("wegweiser_regionen.json", "STRUKTURDATEN_WW_REGIONEN"),
    "ww_export": ("wegweiser_export.csv", "STRUKTURDATEN_WW_EXPORT"),
}
PROTOKOLL = ("audit_abruf.tsv", "STRUKTURDATEN_PROTOKOLL")
# Reihenfolge des Abrufs: zuerst die OpenAPI-Beschreibung (Prüfung von info.version), die Datei der Stadt zuletzt
ABRUFE = [
    ("ww_openapi", WW + "/openapi?format=JSON", "wegweiser-kommune"),
    ("ww_version", WW + "/data-api/rest/statistics/version", "wegweiser-kommune"),
    ("ww_indikatoren", WW + "/data-api/rest/indicator/list?max=2000", "wegweiser-kommune"),
    ("ww_regionen", WW + "/data-api/rest/region/list?types=KREISFREIE_STADT&max=500", "wegweiser-kommune"),
    ("ww_export", WW_EXPORT_URL, "wegweiser-kommune"),
    ("xlsx", XLSX_URL, "offenedaten-koeln"),
]
MAX_ANFRAGEN = len(ABRUFE)   # je Quelldatei eine Anfrage (5) und eine für die OpenAPI-Beschreibung
MAX_BYTES = 100_000_000
ZEITLIMIT = 300

KOPF_PROTOKOLL = ["quelle", "url", "zeitstempel", "http_status", "zeilen", "pruefsumme", "hinweis"]
# Spaltennamen im Protokoll der Exploration (Phase 0), ebenfalls lesbar
PROTOKOLL_ALIAS = {"zeitstempel": "zeit", "http_status": "status", "pruefsumme": "sha256"}
KOPF_INDIKATOREN = ["indikator_id", "name", "thema", "einheit", "typ", "zaehler_id", "nenner_id", "raumebenen", "jahre",
                    "quelle", "datenhalter", "lizenz", "lizenz_url", "namensnennung", "metatext", "geheimhaltung",
                    "quell_url", "abrufdatum"]
KOPF_WERTE = ["raumebene", "raum_id", "indikator_id", "jahr", "wert", "status", "quellobjekt"]
KOPF_GESAMTSTADT = ["kommune", "wegweiser_friendly_url", "indikator_id", "jahr", "wert", "abrufdatum"]
KOPF_ZURUECK = ["indikator_id", "name", "quelle", "grund", "entscheidung"]
KOPF_AUDIT = KOPF_PROTOKOLL

_SPALTE = re.compile(r"([A-Z]\d{4}[APS]) - (.+)", re.S)
_DE_ZAHL = re.compile(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?")


def ausgabe():
    return Path(os.environ.get("STRUKTURDATEN_AUS") or config.ROOT / "data" / "strukturdaten")


def zwischenspeicher():
    return Path(os.environ.get("STRUKTURDATEN_DL") or config.ROOT / "_kontext_dl" / "strukturdaten")


def eingabe(schluessel):
    name, variable = DATEIEN[schluessel]
    return Path(os.environ.get(variable) or zwischenspeicher() / name)


def protokoll_pfad():
    return Path(os.environ.get(PROTOKOLL[1]) or zwischenspeicher() / PROTOKOLL[0])


# --- gemeinsame Hilfen ------------------------------------------------------------------------------------------------

def _text(wert):
    """Feld einer TSV-Zeile: ohne Tabulatoren und Zeilenumbrüche, Leerraum am Rand entfernt."""
    return re.sub(r"[\t\r\n]+", " ", "" if wert is None else str(wert)).strip()


def _tsv_schreiben(pfad, kopf, zeilen):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(kopf) + "\n")
        fh.writelines("\t".join(_text(z.get(k, "")) for k in kopf) + "\n" for z in zeilen)
    tmp.replace(pfad)


def _tsv_lesen(pfad):
    with open(pfad, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def pruefsumme(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as fh:
        for teil in iter(lambda: fh.read(1 << 20), b""):
            h.update(teil)
    return h.hexdigest()


def zahl(wert):
    """Zahl aus einer XLSX-Zelle unverändert als Text: ganze Zahlen wie gespeichert, Gleitkommazahlen in der kürzesten
    Schreibweise, die denselben Wert ergibt, mit Punkt und ohne Exponent."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise TypeError(f"keine Zahl: {wert!r}")
    if isinstance(wert, int):
        return str(wert)
    if not math.isfinite(wert):
        raise ValueError(f"keine endliche Zahl: {wert!r}")
    text = repr(wert)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


def de_zahl(text):
    """Zahl aus dem Wegweiser-Export („1.087.353“, „-0,3“) mit Punkt als Dezimaltrennzeichen, Ziffern unverändert."""
    text = text.strip()
    if not _DE_ZAHL.fullmatch(text):
        raise ValueError(f"unerwarteter Wert im Wegweiser-Export: {text!r}")
    return text.replace(".", "").replace(",", ".")


def jahre_text(jahre):
    """Jahre als Bereiche: „2012–2025“, Lücken getrennt durch Semikolon („2012–2014;2016–2025“)."""
    jahre = sorted({int(j) for j in jahre})
    teile, start = [], None
    for i, j in enumerate(jahre):
        if start is None:
            start = j
        if i + 1 == len(jahre) or jahre[i + 1] != j + 1:
            teile.append(str(j) if start == j else f"{start}–{j}")
            start = None
    return ";".join(teile)


def _satz(text):
    """Text als Satz mit Schlusspunkt (für den Metatext aus mehreren Teilen)."""
    text = _text(text)
    return text if not text or text[-1] in ".!?" else text + "."


def _stellen(wert):
    """Nachkommastellen der veröffentlichten Zahl."""
    text = zahl(wert)
    return len(text.split(".", 1)[1]) if "." in text else 0


@contextmanager
def arbeitsmappe(pfad):
    """XLSX nur lesend (openpyxl, read_only, gespeicherte Werte statt Formeln); über einen Dateizeiger geöffnet, damit
    auch Dateien ohne Endung .xlsx lesbar sind (etwa die Antwort im Zwischenspeicher vor dem Ersetzen)."""
    import openpyxl
    with open(pfad, "rb") as fh:
        mappe = openpyxl.load_workbook(fh, read_only=True, data_only=True)
        try:
            yield mappe
        finally:
            mappe.close()


def zeilen_zaehlen(schluessel, pfad):
    """Datensätze einer Eingabedatei für das Protokoll: Zeilen im Blatt Daten ohne Kopf (XLSX), Indikatorzeilen
    (Wegweiser-Export), Einträge (Listen), sonst 1."""
    if schluessel == "xlsx":
        with arbeitsmappe(pfad) as mappe:
            return sum(1 for z in mappe["Daten"].iter_rows(min_row=2, max_col=1, values_only=True) if z and z[0])
    if schluessel == "ww_export":
        return len(_wegweiser_tabelle(pfad.read_text(encoding="utf-8"))[1])
    if schluessel in ("ww_indikatoren", "ww_regionen"):
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        return len(daten) if isinstance(daten, list) else 1
    return 1


def hinweis_zur_datei(schluessel, pfad):
    """Protokollhinweis: info.version der OpenAPI-Beschreibung, Datenversion des Wegweisers."""
    if schluessel == "ww_openapi":
        return f"info.version {openapi_version(pfad)}"
    if schluessel == "ww_version":
        return f"Datenversion {wegweiser_version(pfad)}"
    return ""


def openapi_version(pfad):
    daten = json.loads(Path(pfad).read_text(encoding="utf-8"))
    version = daten.get("info", {}).get("version") if isinstance(daten, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{pfad}: OpenAPI-Beschreibung ohne info.version")
    return version.strip()


def wegweiser_version(pfad):
    """Datenversion (Antwort von statistics/version: reiner Text, auch mit Anführungszeichen)."""
    text = Path(pfad).read_text(encoding="utf-8").strip().strip('"').strip()
    if not text or "\n" in text or len(text) > 200:
        raise ValueError(f"{pfad}: unerwartete Datenversion {text[:80]!r}")
    return text


# --- Abruf ------------------------------------------------------------------------------------------------------------

class Abbruch(RuntimeError):
    """Der Lauf endet ohne weitere Anfrage; `art`: adresse, obergrenze, http, weiterleitung, verbindung, unlesbar,
    version."""

    def __init__(self, meldung, art):
        super().__init__(meldung)
        self.art = art


class NichtGesendet(RuntimeError):
    """Die Anfrage wurde nicht gesendet (Freigabe, Sperre der Stadt, Zeitfenster, Version nicht geprüft)."""


_OEFFNER = abruf.oeffner()   # ohne Weiterleitungen (wie pipeline/abruf.py)


def letzte_openapi_version():
    """info.version des zuletzt veröffentlichten Stands (meta.json), sonst None."""
    pfad = ausgabe() / "meta.json"
    if not pfad.exists():
        return None
    for q in json.loads(pfad.read_text(encoding="utf-8")).get("quellen", []):
        if q.get("openapi_version"):
            return q["openapi_version"]
    return None


class _Lauf:
    def __init__(self, protokoll):
        self.protokoll = protokoll
        self.anfragen = 0
        self.letzte = None          # Ende der letzten Antwort (time.monotonic)
        self.version_geprueft = False
        self.ergebnis = []          # (Schlüssel, Ergebnis)

    def protokollieren(self, quelle, url, status, zeilen="", summe="", hinweis=""):
        neu = not self.protokoll.exists()
        self.protokoll.parent.mkdir(parents=True, exist_ok=True)
        zeit = abruf.uhr().astimezone(abruf.ORTSZEIT).isoformat(timespec="seconds")
        with open(self.protokoll, "a", encoding="utf-8", newline="") as fh:
            if neu:
                fh.write("\t".join(KOPF_PROTOKOLL) + "\n")
            fh.write("\t".join(_text(x) for x in (quelle, url, zeit, status, zeilen, summe, hinweis)) + "\n")

    def pruefen(self, schluessel, url):
        """Gründe gegen das Senden; NichtGesendet (Lauf geht weiter) oder Abbruch (Lauf endet)."""
        grund = abruf.adresse_pruefen(url)
        if grund:
            raise Abbruch(f"ungültige Adresse ({grund}): {url}", "adresse")
        if not abruf.lokal(url) and os.environ.get("STRUKTURDATEN_ABRUF") != "ja":
            raise NichtGesendet("ohne Freigabe (STRUKTURDATEN_ABRUF=ja)")
        if abruf.stadt(url):
            if os.environ.get("RATSATLAS_STADT_INFORMIERT") != "ja":
                raise NichtGesendet("gesperrt: Server der Stadt Köln (RATSATLAS_STADT_INFORMIERT=ja fehlt)")
            if not abruf.im_zeitfenster():
                raise NichtGesendet(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (Server der Stadt)")
        if schluessel.startswith("ww_") and schluessel != "ww_openapi" and not self.version_geprueft:
            raise NichtGesendet("info.version der Wegweiser-OpenAPI nicht geprüft")
        if self.anfragen >= MAX_ANFRAGEN:
            raise Abbruch(f"Obergrenze von {MAX_ANFRAGEN} Anfragen je Lauf erreicht", "obergrenze")

    def warten(self, url):
        """Abstand seit der letzten Antwort; für Adressen der Stadt und nicht lokale Adressen mindestens
        abruf.MINDESTABSTAND. Für die Stadt wird das Zeitfenster unmittelbar vor dem Senden erneut geprüft."""
        stadt = abruf.stadt(url)
        mindestens = abruf.abstand(abruf.lokal(url) and not stadt)
        if self.letzte is not None:
            rest = mindestens - (time.monotonic() - self.letzte)
            if rest > 0:
                time.sleep(rest)
        if stadt and not abruf.im_zeitfenster():
            raise NichtGesendet(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr (Server der Stadt)")

    def senden(self, url, tmp):
        """Eine Anfrage, Antwort nach `tmp`; (HTTP-Status, Prüfsumme, Bytes). Keine Wiederholung."""
        if any(ord(z) < 32 or ord(z) == 127 for z in config.USER_AGENT):
            raise ValueError(f"User-Agent enthält Steuerzeichen (RATSATLAS_KONTAKT prüfen): {config.USER_AGENT!r}")
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
        self.anfragen += 1
        h, n = hashlib.sha256(), 0
        try:
            with _OEFFNER.open(req, timeout=ZEITLIMIT) as antwort, open(tmp, "wb") as fh:
                status = antwort.status
                for teil in iter(lambda: antwort.read(1 << 16), b""):
                    n += len(teil)
                    if n > MAX_BYTES:
                        raise Abbruch(f"Antwort größer als {MAX_BYTES} Bytes: {url}", "unlesbar")
                    h.update(teil)
                    fh.write(teil)
        finally:
            self.letzte = time.monotonic()
        return status, h.hexdigest(), n

    def laden(self, schluessel, url, quelle):
        try:
            self.pruefen(schluessel, url)
            self.warten(url)
        except NichtGesendet as e:
            self.protokollieren(quelle, url, f"nicht gesendet ({e})")
            self.ergebnis.append((schluessel, f"nicht gesendet ({e})"))
            return
        except Abbruch as e:
            self.protokollieren(quelle, url, f"nicht gesendet ({e.art})", hinweis=str(e))
            raise
        dl = zwischenspeicher()
        dl.mkdir(parents=True, exist_ok=True)
        ziel = dl / DATEIEN[schluessel][0]
        tmp = ziel.with_name(ziel.name + ".tmp")
        try:
            status, summe, _ = self.senden(url, tmp)
        except urllib.error.HTTPError as e:
            tmp.unlink(missing_ok=True)
            art = "weiterleitung" if 300 <= e.code < 400 else "http"
            ort = e.headers.get("Location", "") if e.headers else ""
            self.protokollieren(quelle, url, str(e.code), hinweis=f"Weiterleitung nach {ort}" if ort else "")
            raise Abbruch(f"HTTP {e.code}: {url} (keine Wiederholung)", art) from e
        except Abbruch as e:
            tmp.unlink(missing_ok=True)
            self.protokollieren(quelle, url, f"abbruch ({e.art})", hinweis=str(e))
            raise
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            tmp.unlink(missing_ok=True)
            self.protokollieren(quelle, url, "abbruch (verbindung)", hinweis=type(e).__name__)
            raise Abbruch(f"Zeitüberschreitung oder Verbindungsabbruch, keine Wiederholung: {url} ({e})",
                          "verbindung") from e
        try:
            _pruefen_inhalt(schluessel, tmp)
            zeilen = zeilen_zaehlen(schluessel, tmp)
            hinweis = hinweis_zur_datei(schluessel, tmp)
        except Exception as e:   # unlesbar: vorige Datei bleibt
            tmp.unlink(missing_ok=True)
            self.protokollieren(quelle, url, str(status), "", summe, f"unlesbar: {e}")
            raise Abbruch(f"{schluessel}: unlesbare Antwort ({e}); vorige Datei bleibt", "unlesbar") from e
        if schluessel == "ww_openapi":
            neu, alt = openapi_version(tmp), letzte_openapi_version()
            if alt is not None and neu != alt and os.environ.get("STRUKTURDATEN_OPENAPI_BESTAETIGT") != neu:
                tmp.replace(ziel.with_name("wegweiser_openapi.neu.json"))
                self.protokollieren(quelle, url, str(status), zeilen, summe,
                                    f"{hinweis}; zuletzt {alt}: Lauf abgebrochen")
                raise Abbruch(f"info.version der Wegweiser-OpenAPI ist {neu}, zuletzt {alt}: Lauf abgebrochen. "
                              "Beschreibung prüfen (wegweiser_openapi.neu.json im Zwischenspeicher), dann mit "
                              f"STRUKTURDATEN_OPENAPI_BESTAETIGT={neu} wiederholen.", "version")
            if alt is None:
                hinweis += "; kein früherer Stand in meta.json"
            self.version_geprueft = True
        tmp.replace(ziel)
        self.protokollieren(quelle, url, str(status), zeilen, summe, hinweis)
        self.ergebnis.append((schluessel, f"HTTP {status}, {zeilen} Zeilen, sha256 {summe[:12]}"))


def _pruefen_inhalt(schluessel, pfad):
    """Grobe Prüfung einer Antwort vor dem Ersetzen der vorigen Datei (Dateien nur mit Parsern öffnen)."""
    with open(pfad, "rb") as fh:
        kopf = fh.read(64).lstrip().lower()
    if kopf.startswith((b"<!doctype html", b"<html")):
        raise ValueError("Webseite statt Daten")
    if schluessel == "xlsx":
        if not zipfile.is_zipfile(pfad):
            raise ValueError("keine XLSX-Datei (kein ZIP-Archiv)")
        with zipfile.ZipFile(pfad) as z:
            if "xl/workbook.xml" not in z.namelist():
                raise ValueError("keine XLSX-Datei (xl/workbook.xml fehlt)")
    elif schluessel == "ww_openapi":
        openapi_version(pfad)
    elif schluessel == "ww_version":
        wegweiser_version(pfad)
    elif schluessel in ("ww_indikatoren", "ww_regionen"):
        if not isinstance(json.loads(pfad.read_text(encoding="utf-8")), list):
            raise ValueError("JSON-Liste erwartet")
    elif schluessel == "ww_export":
        _wegweiser_tabelle(pfad.read_text(encoding="utf-8"))


def abruf_lauf():
    """Schritt `strukturdaten-abruf`: höchstens MAX_ANFRAGEN Anfragen, ohne Wiederholung."""
    lauf = _Lauf(protokoll_pfad())
    try:
        for schluessel, url, quelle in ABRUFE:
            lauf.laden(schluessel, url, quelle)
    except Abbruch as e:
        for schluessel, text in lauf.ergebnis:
            print(f"  {schluessel}: {text}")
        raise SystemExit(f"strukturdaten-abruf abgebrochen ({e.art}) nach {lauf.anfragen} Anfragen: {e}") from e
    for schluessel, text in lauf.ergebnis:
        print(f"  {schluessel}: {text}")
    print(f"{lauf.anfragen} Anfragen; Protokoll {lauf.protokoll}")
    return lauf


# --- Lesen der Quellen ------------------------------------------------------------------------------------------------

def klassifikation(pfad=None):
    zeilen = _tsv_lesen(pfad or KLASSIFIKATION)
    aus = {}
    for z in zeilen:
        if z["indikator_id"] != "koeln_" + z["code"] or z["typ"] not in TYPEN:
            raise ValueError(f"Klassifikation: unerwartete Zeile {z}")
        if z["indikator_id"] in aus:
            raise ValueError(f"Klassifikation: {z['indikator_id']} doppelt")
        aus[z["indikator_id"]] = z
    return aus


class Datenkatalog:
    """Inhalt der XLSX-Datei, soweit Phase 1 ihn braucht (Zeilen nur der übernommenen Raumebenen)."""

    def __init__(self, pfad):
        from openpyxl.utils import get_column_letter
        with arbeitsmappe(pfad) as mappe:
            self._info(mappe["Info"])
            self._quellen(mappe["Quellen"])
            self._katalog(mappe["Katalog"])
            zeilen = mappe["Daten"].iter_rows(values_only=True)
            kopf = next(zeilen)
            if [str(k).strip() if k is not None else "" for k in kopf[:3]] != ["Jahr", "Raum", "Raumebene"]:
                raise ValueError(f"Blatt Daten: unerwarteter Kopf {kopf[:3]}")
            self.spalten = []   # (Code, Name, Spaltenbuchstabe, Index)
            for i, k in enumerate(kopf[3:], start=3):
                m = _SPALTE.fullmatch(str(k or "").strip())
                if not m:
                    raise ValueError(f"Blatt Daten: unerwarteter Spaltenkopf {k!r} in Spalte "
                                     f"{get_column_letter(i + 1)}")
                self.spalten.append((m.group(1), " ".join(m.group(2).split()), get_column_letter(i + 1), i))
            if len({s[0] for s in self.spalten}) != len(self.spalten):
                raise ValueError("Blatt Daten: Spaltencode doppelt")
            self.zeilen = []    # (Zeilennummer, Raumebene, raum_id, Raumname, Jahr, Werte je Spalte)
            self.ebenen_alle = {}
            gesehen = set()
            self.n_zeilen = 0
            for nr, z in enumerate(zeilen, start=2):
                if not z or all(v is None or v == "" for v in z):
                    continue
                self.n_zeilen += 1
                jahr, raum, ebene = (str(v).strip() if v is not None else "" for v in z[:3])
                self.ebenen_alle[ebene] = self.ebenen_alle.get(ebene, 0) + 1
                if ebene in NICHT_UEBERNOMMEN:
                    continue
                if ebene not in RAUMEBENEN:
                    raise ValueError(f"Blatt Daten, Zeile {nr}: unbekannte Raumebene {ebene!r}")
                if not re.fullmatch(r"\d{4}", jahr):
                    raise ValueError(f"Blatt Daten, Zeile {nr}: unerwartetes Jahr {jahr!r}")
                nummer, _, name = raum.partition(" / ")
                if not nummer.isdigit() or not name:
                    raise ValueError(f"Blatt Daten, Zeile {nr}: unerwarteter Raum {raum!r}")
                schluessel = (RAUMEBENEN[ebene], nummer, jahr)
                if schluessel in gesehen:
                    raise ValueError(f"Blatt Daten, Zeile {nr}: {schluessel} doppelt")
                gesehen.add(schluessel)
                werte = tuple(z[i] if i < len(z) else None for _, _, _, i in self.spalten)
                self.zeilen.append((nr, RAUMEBENEN[ebene], nummer, name.strip(), jahr, werte))

    def _info(self, blatt):
        texte = [str(z[0]).strip() for z in blatt.iter_rows(values_only=True) if z and z[0] not in (None, "")]

        def nach(ueberschrift):
            if ueberschrift not in texte or texte.index(ueberschrift) + 1 >= len(texte):
                raise ValueError(f"Blatt Info: „{ueberschrift}“ fehlt")
            return texte[texte.index(ueberschrift) + 1]
        stand = nach("Auswertung erstellt am")
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", stand) or re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", stand)
        if not m:
            raise ValueError(f"Blatt Info: unlesbares Datum {stand!r}")
        teile = m.groups()
        tag, monat, jahr = teile if len(teile[0]) <= 2 else teile[::-1]
        self.stand_text = stand
        self.datenstand = f"{int(jahr):04d}-{int(monat):02d}-{int(tag):02d}"
        self.geheimhaltung = nach("Geheimhaltung")

    def _quellen(self, blatt):
        self.quellen = {}
        for z in blatt.iter_rows(min_row=2, values_only=True):
            if not z or not z[0]:
                continue
            m = _SPALTE.fullmatch(str(z[0]).strip())
            if m:
                self.quellen[m.group(1)] = (_text(z[1] if len(z) > 1 else ""), _text(z[2] if len(z) > 2 else ""))

    def _katalog(self, blatt):
        self.katalog = {}
        kopf = None
        for z in blatt.iter_rows(values_only=True):
            if kopf is None:
                if z and z[0] == "THEMA":
                    kopf = [str(k).strip() if k is not None else "" for k in z]
                continue
            eintrag = dict(zip(kopf, z))
            kennung = _text(eintrag.get("ID"))
            if not kennung:
                continue
            if kennung in self.katalog:
                raise ValueError(f"Blatt Katalog: ID {kennung} doppelt")
            self.katalog[kennung] = {"thema": _text(eintrag.get("THEMA")), "name": _text(eintrag.get("Name"))}
        if kopf is None:
            raise ValueError("Blatt Katalog: Kopfzeile mit THEMA fehlt")


def _wegweiser_tabelle(text):
    """Kopf [(Jahr, Kommunenname)] und Zeilen [(Bezeichnung „Name (Einheit)“, [Zellen])] des Wegweiser-Exports."""
    zeilen = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    try:
        k = next(i for i, z in enumerate(zeilen) if z and z[0].strip() == "Indikatoren")
    except StopIteration:
        raise ValueError("Wegweiser-Export: Kopfzeile „Indikatoren“ fehlt") from None
    kopf = []
    for zelle in zeilen[k][1:]:
        jahr, _, kommune = zelle.partition("\n")
        if not re.fullmatch(r"\d{4}", jahr.strip()) or not kommune.strip():
            raise ValueError(f"Wegweiser-Export: unerwarteter Spaltenkopf {zelle!r}")
        kopf.append((jahr.strip(), kommune.strip()))
    daten = []
    for z in zeilen[k + 1:]:
        if not z or not z[0].strip():
            break
        if len(z) != len(kopf) + 1:
            raise ValueError(f"Wegweiser-Export: Zeile {z[0]!r} mit {len(z) - 1} statt {len(kopf)} Werten")
        daten.append((z[0].strip(), [v.strip() for v in z[1:]]))
    if not daten:
        raise ValueError("Wegweiser-Export ohne Indikatorzeilen")
    return kopf, daten


class Wegweiser:
    """Export, Indikator- und Kommunenliste des Wegweisers Kommune."""

    def __init__(self, export, indikatoren, regionen, version, openapi):
        liste = json.loads(Path(indikatoren).read_text(encoding="utf-8"))
        self.indikatoren = {i["friendlyUrl"]: i for i in liste if isinstance(i, dict) and i.get("friendlyUrl")}
        for fu in (*WW_AUSWAHL, *WW_ZURUECKGESTELLT):
            if fu not in self.indikatoren:
                raise ValueError(f"Wegweiser: Indikator {fu} fehlt in der Indikatorliste")
        for fu in WW_AUSWAHL:
            if any(u in str(self.indikatoren[fu].get("source", "")) for u in WW_UNTERNEHMEN):
                raise ValueError(f"Wegweiser: {fu} hat ein Unternehmen als Datenhalter; nicht übernehmen")
        regionen = json.loads(Path(regionen).read_text(encoding="utf-8"))
        name_zu_kommune = {r["name"]: r["friendlyUrl"] for r in regionen
                           if isinstance(r, dict) and r.get("friendlyUrl") in WW_KOMMUNEN}
        self.kommunen = {fu: name for name, fu in name_zu_kommune.items()}
        if set(name_zu_kommune.values()) != set(WW_KOMMUNEN):
            raise ValueError(f"Wegweiser: Kommunen {sorted(set(WW_KOMMUNEN) - set(name_zu_kommune.values()))} fehlen")
        bezeichnung = {}
        for fu in WW_AUSWAHL:
            i = self.indikatoren[fu]
            text = f"{i['name']} ({i['unit']})" if i.get("unit") else i["name"]
            if text in bezeichnung:
                raise ValueError(f"Wegweiser: Bezeichnung {text!r} nicht eindeutig")
            bezeichnung[text] = fu
        kopf, daten = _wegweiser_tabelle(Path(export).read_text(encoding="utf-8"))
        spalten = []
        for jahr, kommune in kopf:
            if kommune not in name_zu_kommune:
                raise ValueError(f"Wegweiser-Export: unbekannte Kommune {kommune!r}")
            spalten.append((jahr, name_zu_kommune[kommune]))
        self.werte = []      # (kommune, friendlyUrl, Jahr, Wert)
        self.ka = []         # (kommune, friendlyUrl, Jahr) mit „k.A.“
        gefunden = set()
        for text, zellen in daten:
            if text not in bezeichnung:
                raise ValueError(f"Wegweiser-Export: unbekannte Zeile {text!r}")
            fu = bezeichnung[text]
            if fu in gefunden:
                raise ValueError(f"Wegweiser-Export: Zeile {text!r} doppelt")
            gefunden.add(fu)
            for (jahr, kommune), zelle in zip(spalten, zellen):
                if zelle == "k.A.":
                    self.ka.append((kommune, fu, jahr))
                else:
                    self.werte.append((kommune, fu, jahr, de_zahl(zelle)))
        if gefunden != set(WW_AUSWAHL):
            raise ValueError(f"Wegweiser-Export: Zeilen fehlen für {sorted(set(WW_AUSWAHL) - gefunden)}")
        self.n_zeilen = len(daten)
        self.version = wegweiser_version(version)
        self.openapi_version = openapi_version(openapi)


def abrufprotokoll(pfad):
    """Zeilen des Abrufprotokolls mit den Spalten von KOPF_PROTOKOLL (auch aus dem Protokoll der Exploration)."""
    aus = []
    for z in _tsv_lesen(pfad):
        aus.append({k: (z.get(k) if z.get(k) is not None else z.get(PROTOKOLL_ALIAS.get(k, ""), "")) or ""
                    for k in KOPF_PROTOKOLL})
    return aus


def herkunft(schluessel, pfad, protokoll, zeilen=None):
    """Protokollzeile der Eingabedatei (gleiche Prüfsumme, letzter erfolgreicher Abruf); sonst ValueError. `zeilen`:
    bereits gezählte Datensätze (sonst gezählt wie im Abruf)."""
    summe = pruefsumme(pfad)
    treffer = [z for z in protokoll if z["pruefsumme"] == summe and z["http_status"] == "200"]
    if not treffer:
        raise ValueError(f"{schluessel}: {pfad.name} (sha256 {summe}) steht nicht im Abrufprotokoll; Herkunft und "
                         "Abrufdatum unbelegt")
    zeile = max(treffer, key=lambda z: datetime.fromisoformat(z["zeitstempel"]))
    zeilen = zeilen_zaehlen(schluessel, pfad) if zeilen is None else zeilen
    return {**zeile, "pruefsumme": summe, "zeilen": str(zeilen),
            "hinweis": hinweis_zur_datei(schluessel, pfad)}


# --- Normalisierung ---------------------------------------------------------------------------------------------------

def _verhaeltnis(spalte, zeilen, wert, zaehler, nenner, faktor):
    """(gilt, geprüfte Zeilen): Wert = faktor × Zähler / Nenner in jeder Zeile mit drei Zahlen, Abweichung höchstens
    eine Einheit der letzten veröffentlichten Stelle des Werts."""
    iw, iz, i_n = spalte[wert], spalte[zaehler], spalte[nenner]
    n = 0
    for *_, werte in zeilen:
        w, z, d = werte[iw], werte[iz], werte[i_n]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (w, z, d)) or d == 0:
            continue
        n += 1
        if abs(w - faktor * z / d) > 10 ** -_stellen(w) + 1e-12:
            return False, n
    return n > 0, n


def _summe(spalte, zeilen, gesamt, teile):
    """(gilt, geprüfte Zeilen): gesamt = Summe der Teile in jeder Zeile, in der alle Zahlen sind."""
    if gesamt not in spalte or any(t not in spalte for t in teile):
        return False, 0
    n = 0
    for *_, werte in zeilen:
        v = [werte[spalte[c]] for c in (gesamt, *teile)]
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            continue
        n += 1
        if v[0] != sum(v[1:]):
            return False, n
    return n > 0, n


def _koeln(kat, klass, beleg):
    """(Indikatoren, Werte, Zurückgestellte, Hinweise) aus dem Statistischen Datenkatalog."""
    abrufdatum = beleg["zeitstempel"][:10]
    spalte = {code: i for i, (code, *_) in enumerate(kat.spalten)}
    name = {code: n for code, n, *_ in kat.spalten}
    zurueck, hinweise = [], []
    aufnehmen = []
    for code, n, buchstabe, _ in kat.spalten:
        iid = "koeln_" + code
        k = klass.get(iid)
        if k is None:
            zurueck.append({"indikator_id": iid, "name": n, "quelle": KOELN_TITEL,
                            "grund": "Spalte im Blatt Daten ohne Klassifikation (Typ nicht bestimmt); Werte vorhanden, "
                                     "nicht übernommen", "entscheidung": ""})
        elif k["typ_sicherheit"] == "unsicher":
            zurueck.append({"indikator_id": iid, "name": n, "quelle": KOELN_TITEL,
                            "grund": f"Typ in Phase 0 unsicher ({k['typ_begruendung']}); Werte im Blatt Daten "
                                     "vorhanden, nicht übernommen",
                            "entscheidung": "10.11.2026: unsichere Typen zurückgestellt"})
        else:
            aufnehmen.append((code, n, buchstabe, k))
    daten_codes = {s[0] for s in kat.spalten}
    for iid, k in klass.items():
        if k["typ_sicherheit"] == "unsicher" and k["code"] not in daten_codes:
            eintrag = kat.katalog.get(k["katalog_id"], {})
            zurueck.append({"indikator_id": iid, "name": eintrag.get("name", ""), "quelle": KOELN_TITEL,
                            "grund": f"Typ in Phase 0 unsicher ({k['typ_begruendung']}); im Blatt Daten ohne Werte "
                                     "(nur im Katalog)",
                            "entscheidung": "10.11.2026: unsichere Typen zurückgestellt"})
    fehlen = sorted(iid for iid, k in klass.items()
                    if k["typ_sicherheit"] != "unsicher" and k["code"] not in daten_codes)
    if fehlen:
        hinweise.append(f"{len(fehlen)} Indikatoren aus Phase 0 stehen nicht im Blatt Daten dieser Datei: "
                        f"{', '.join(fehlen[:10])}{' …' if len(fehlen) > 10 else ''}")
    codes = {c for c, *_ in aufnehmen}
    gesamt_gilt, gesamt_n = _summe(spalte, kat.zeilen, GESAMT, (HAUPT, NEBEN))
    hinweise.append(f"{GESAMT} = {HAUPT} + {NEBEN}: {'gilt' if gesamt_gilt else 'gilt nicht'} ({gesamt_n} Zeilen)")
    indikatoren, werte = [], []
    for code, n, buchstabe, k in aufnehmen:
        iid = "koeln_" + code
        i = spalte[code]
        z_id = n_id = ""
        meta = [f"{KOELN_TITEL}, Spalte {code}; Werte unverändert übernommen."]
        if k["zaehler_id"]:
            z, d = k["zaehler_id"].removeprefix("koeln_"), k["nenner_id"].removeprefix("koeln_")
            if z in codes and d in codes:
                gilt, geprueft = _verhaeltnis(spalte, kat.zeilen, code, z, d, float(k["faktor"]))
            else:
                gilt, geprueft = False, 0
            if gilt:
                z_id, n_id = k["zaehler_id"], k["nenner_id"]
                meta.append(f"Entspricht {k['faktor']} × Zähler / Nenner (nachgerechnet in {geprueft} Zeilen): "
                            f"Zähler {z_id} „{name[z]}“, Nenner {n_id} „{name[d]}“.")
                if d == GESAMT and gesamt_gilt:
                    meta.append("Bezugsgröße sind alle Einwohner*innen mit Haupt- und Nebenwohnsitz.")
            else:
                hinweise.append(f"{iid}: Zähler/Nenner aus Phase 0 gelten in dieser Datei nicht "
                                f"({geprueft} Zeilen geprüft); nicht übernommen")
        if code == GESAMT and gesamt_gilt:
            meta.append(f"Summe aus Einwohner*innen mit Hauptwohnsitz (koeln_{HAUPT}) und mit Nebenwohnsitz "
                        f"(koeln_{NEBEN}), nachgerechnet.")
        quellenangabe, anmerkung = kat.quellen.get(code, ("", ""))
        if anmerkung:
            meta.append(f"Anmerkung der Quelle: {anmerkung}")
        if not quellenangabe:
            hinweise.append(f"{iid}: keine Quellenangabe im Blatt Quellen")
        jahre, ebenen = set(), set()
        for nr, ebene, raum_id, _, jahr, zellen in kat.zeilen:
            v = zellen[i]
            ref = f"Daten!{buchstabe}{nr}"
            if isinstance(v, str) and v.strip() == "*":
                eintrag = ("", "geheim")
            elif v is None or (isinstance(v, str) and not v.strip()):
                eintrag = ("", "fehlt")
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                eintrag = (zahl(v), "ok")
            else:
                raise ValueError(f"unerwarteter Wert {v!r} in {ref}")
            if eintrag[1] != "fehlt":
                jahre.add(jahr)
                ebenen.add(ebene)
            werte.append({"raumebene": ebene, "raum_id": raum_id, "indikator_id": iid, "jahr": jahr,
                          "wert": eintrag[0], "status": eintrag[1], "quellobjekt": ref})
        indikatoren.append({
            "indikator_id": iid, "name": n, "thema": kat.katalog.get(k["katalog_id"], {}).get("thema", ""),
            "einheit": k["einheit"], "typ": k["typ"], "zaehler_id": z_id, "nenner_id": n_id,
            "raumebenen": ";".join(e for e in EBENEN_REIHENFOLGE if e in ebenen), "jahre": jahre_text(jahre),
            "quelle": KOELN_TITEL, "datenhalter": quellenangabe, "lizenz": KOELN_LIZENZ, "lizenz_url": KOELN_LIZENZ_URL,
            "namensnennung": KOELN_NAMENSNENNUNG, "metatext": " ".join(_satz(m) for m in meta),
            "geheimhaltung": kat.geheimhaltung,
            "quell_url": DATENSATZ_URL, "abrufdatum": abrufdatum})
    return indikatoren, werte, zurueck, hinweise


def _ka_text(ka, namen):
    """„2006–2015 (Bonn, Köln, Wuppertal)“: Jahre mit k.A., gruppiert nach den betroffenen Kommunen."""
    je_jahr = {}
    for kommune, _, jahr in ka:
        je_jahr.setdefault(int(jahr), set()).add(namen.get(kommune, kommune))
    gruppen = {}
    for jahr, kommunen in je_jahr.items():
        gruppen.setdefault(tuple(sorted(kommunen)), []).append(jahr)
    teile = sorted((jahre_text(j).replace(";", ", "), k) for k, j in gruppen.items())
    return "; ".join(f"{j} ({', '.join(k)})" for j, k in teile)


def _wegweiser(ww, beleg):
    abrufdatum = beleg["zeitstempel"][:10]
    indikatoren, zeilen = [], []
    for fu, typ in WW_AUSWAHL.items():
        i = ww.indikatoren[fu]
        werte = [w for w in ww.werte if w[1] == fu]
        ka = [k for k in ww.ka if k[1] == fu]
        meta = [f"Erläuterung (Wegweiser): {i.get('explanation') or '–'}"]
        if i.get("calculation"):
            meta.append(f"Berechnung (Wegweiser): {i['calculation']}")
        if i.get("hint"):
            meta.append(f"Hinweis (Wegweiser): {i['hint']}")
        meta.append("Gesamtstädtischer Vergleichswert; Definition und Stichtag können von der Kölner Stadtstatistik "
                    "abweichen, Werte nicht miteinander verrechnen.")
        if ka:
            meta.append(f"Ohne Angabe im Wegweiser („k.A.“, nicht übernommen): {_ka_text(ka, ww.kommunen)}.")
        iid = f"ww_{fu}"
        indikatoren.append({
            "indikator_id": iid, "name": i["name"], "thema": "; ".join(i.get("topics") or []),
            "einheit": i.get("unit", ""), "typ": typ, "zaehler_id": "", "nenner_id": "",
            "raumebenen": "gesamtstadt" if werte else "", "jahre": jahre_text(w[2] for w in werte),
            "quelle": WW_TITEL, "datenhalter": i.get("source", ""), "lizenz": WW_LIZENZ, "lizenz_url": WW_LIZENZ_URL,
            "namensnennung": f"{WW_QUELLENANGABE}; Datenhalter: {i.get('source', '')}",
            "metatext": " ".join(_satz(m) for m in meta),
            "geheimhaltung": "keine Angabe in der Quelle", "quell_url": WW_DATENSEITE, "abrufdatum": abrufdatum})
        zeilen += [{"kommune": k, "wegweiser_friendly_url": fu, "indikator_id": iid, "jahr": j, "wert": w,
                    "abrufdatum": abrufdatum} for k, _, j, w in werte]
    zurueck = [{"indikator_id": f"ww_{fu}", "name": ww.indikatoren[fu]["name"], "quelle": WW_TITEL,
                "grund": f"Datenhalter laut Wegweiser: {ww.indikatoren[fu].get('source', '')}; ob die Bertelsmann "
                         "Stiftung Daten eines Unternehmens unter CC0 stellen darf, ist nicht belegt",
                "entscheidung": "10.11.2026: Nexiga-Indikatoren bis zur Klärung zurückgestellt"}
               for fu in WW_ZURUECKGESTELLT]
    return indikatoren, zeilen, zurueck


def _gebietsabgleich(kat):
    """Abgleich der Stadtteile und Stadtbezirke mit data/geo (Nummer und Name); nur Hinweise."""
    hinweise = []
    for ebene, pfad, nummer, name in (("stadtteil", config.ORTSTEILE, "ortsteil", "ortsteil_bez"),
                                      ("stadtbezirk", config.STADTBEZIRKE, "bezirk", "bezirk_bez")):
        if not Path(pfad).exists():
            hinweise.append(f"Abgleich {ebene}: {pfad} fehlt")
            continue
        geo = {}
        for f in json.loads(Path(pfad).read_text(encoding="utf-8"))["features"]:
            geo[str(f["properties"][nummer])] = f["properties"][name]
        quelle = {raum_id: n for _, e, raum_id, n, *_ in sorted(
            (z for z in kat.zeilen if z[1] == ebene), key=lambda z: z[4])}   # Name aus dem jüngsten Jahr
        fehlen = sorted(set(geo) ^ set(quelle))
        anders = sorted(r for r in set(geo) & set(quelle) if geo[r] != quelle[r])
        hinweise.append(f"Abgleich {ebene} mit {Path(pfad).name}: {len(quelle)} in der Quelle, {len(geo)} in den "
                        f"Geodaten, Nummern nur auf einer Seite: {fehlen or 'keine'}, Namen verschieden: "
                        f"{anders or 'keine'}")
    return hinweise


def _meta(kat, ww, belege, indikatoren):
    q = []
    beschreibung = {
        "xlsx": ("statistischer-datenkatalog-koeln", KOELN_TITEL + " (XLSX, Blätter Info, Daten, Quellen, Katalog)"),
        "ww_export": ("wegweiser-export", "Wegweiser Kommune, Datenexport (CSV) der ausgewählten Indikatoren"),
        "ww_indikatoren": ("wegweiser-indikatoren", "Wegweiser Kommune, Indikatorliste (Name, Einheit, Erläuterung, "
                                                    "Datenhalter)"),
        "ww_regionen": ("wegweiser-kommunen", "Wegweiser Kommune, Liste der kreisfreien Städte (friendlyUrl)"),
        "ww_version": ("wegweiser-datenversion", "Wegweiser Kommune, Datenversion"),
        "ww_openapi": ("wegweiser-openapi", "Wegweiser Kommune, OpenAPI-Beschreibung (info.version)"),
    }
    for schluessel in DATEIEN:
        b = belege[schluessel]
        kennung, titel = beschreibung[schluessel]
        eintrag = {"kennung": kennung, "titel": titel, "url": b["url"], "abgerufen": b["zeitstempel"],
                   "sha256": b["pruefsumme"]}
        if schluessel == "xlsx":
            eintrag.update({"datensatz_url": DATENSATZ_URL, "herausgeber": KOELN_HERAUSGEBER, "lizenz": KOELN_LIZENZ,
                            "lizenz_url": KOELN_LIZENZ_URL, "namensnennung": KOELN_NAMENSNENNUNG,
                            "datenstand": kat.datenstand})
        else:
            eintrag.update({"datensatz_url": WW_DATENSEITE, "herausgeber": "Bertelsmann Stiftung", "lizenz": WW_LIZENZ,
                            "lizenz_url": WW_LIZENZ_URL, "namensnennung": WW_QUELLENANGABE})
            if schluessel == "ww_version":
                eintrag["datenversion"] = ww.version
            if schluessel == "ww_openapi":
                eintrag["openapi_version"] = ww.openapi_version
        q.append(eintrag)
    abrufdatum = max(b["zeitstempel"][:10] for b in belege.values())
    return {
        "vertrag_version": VERTRAG_VERSION,
        "datenstand": kat.datenstand,
        "datenstand_hinweis": (f"Datenstand des Statistischen Datenkatalogs laut Blatt Info („Auswertung erstellt am "
                               f"{kat.stand_text}“); maßgeblich ist die Angabe in der Datei, die Ressourcen auf "
                               f"open.nrw tragen den {OPEN_NRW_RESSOURCEN} (Stand der Portalangabe). Wegweiser "
                               f"Kommune: Datenversion {ww.version}."),
        "abrufdatum": abrufdatum,
        "veroeffentlichen": True,
        "lizenzstatus": "geklärt",
        "lizenzstatus_hinweis": (f"{KOELN_TITEL}: {KOELN_LIZENZ} laut open.nrw; Nutzung und Veröffentlichung hat die "
                                 "Statistikstelle laut Auftraggeber am 10.11.2026 zugestimmt. Wegweiser Kommune: "
                                 f"{WW_LIZENZ} laut Open-Data-Seite und Fußzeile des Exports; Indikatoren mit einem "
                                 "Unternehmen als Datenhalter sind zurückgestellt (zurueckgestellt.tsv)."),
        "raumebenen": list(EBENEN_REIHENFOLGE),
        "raumebenen_nicht_uebernommen": {e: g for e, g in NICHT_UEBERNOMMEN.values()},
        "einwohner_indikator": EINWOHNER if any(i["indikator_id"] == EINWOHNER for i in indikatoren) else "",
        "quellobjekt": ("werte.tsv: Zelle im Blatt Daten der XLSX-Datei mit der Prüfsumme unter quellen[] "
                        "(Daten!<Spalte><Zeile>; Spalte = Indikator, Zeile = Jahr und Raum). gesamtstadt.tsv: Zelle "
                        "des Wegweiser-Exports (Indikator, Jahr, Kommune)."),
        "gesamtstadt_ka": ("Jahre mit „k.A.“ im Wegweiser-Export stehen nicht in gesamtstadt.tsv (der Vertrag sieht "
                           "dort keinen Status vor); der Metatext des Indikators nennt sie."),
        "quellen": q,
    }


def write():
    """Schritt `strukturdaten`: Eingaben aus dem Zwischenspeicher → data/strukturdaten/ (ohne Netz)."""
    pfade = {k: eingabe(k) for k in DATEIEN}
    for k, p in pfade.items():
        if not p.exists():
            raise SystemExit(f"strukturdaten: Eingabe {k} fehlt ({p}); zuerst `strukturdaten-abruf` (mit Freigabe) "
                             f"oder {DATEIEN[k][1]} setzen")
    protokoll = abrufprotokoll(protokoll_pfad())
    klass = klassifikation()
    kat = Datenkatalog(pfade["xlsx"])
    ww = Wegweiser(pfade["ww_export"], pfade["ww_indikatoren"], pfade["ww_regionen"], pfade["ww_version"],
                   pfade["ww_openapi"])
    gezaehlt = {"xlsx": kat.n_zeilen, "ww_export": ww.n_zeilen}
    belege = {k: herkunft(k, p, protokoll, gezaehlt.get(k)) for k, p in pfade.items()}
    ind_k, werte, zur_k, hinweise = _koeln(kat, klass, belege["xlsx"])
    ind_w, gesamt, zur_w = _wegweiser(ww, belege["ww_export"])
    hinweise += _gebietsabgleich(kat)
    indikatoren = sorted(ind_k + ind_w, key=lambda i: i["indikator_id"])
    for i in indikatoren:
        if i["typ"] not in TYPEN:
            raise ValueError(f"{i['indikator_id']}: Typ {i['typ']!r} nicht im Vertrag")
    ordnung = {e: n for n, e in enumerate(EBENEN_REIHENFOLGE)}
    werte.sort(key=lambda w: (ordnung[w["raumebene"]], int(w["raum_id"]), w["indikator_id"], w["jahr"]))
    gesamt.sort(key=lambda g: (g["kommune"], g["indikator_id"], g["jahr"]))
    zurueck = sorted(zur_k + zur_w, key=lambda z: z["indikator_id"])
    aus = ausgabe()
    aus.mkdir(parents=True, exist_ok=True)
    _tsv_schreiben(aus / "indikatoren.tsv", KOPF_INDIKATOREN, indikatoren)
    _tsv_schreiben(aus / "werte.tsv", KOPF_WERTE, werte)
    _tsv_schreiben(aus / "gesamtstadt.tsv", KOPF_GESAMTSTADT, gesamt)
    _tsv_schreiben(aus / "zurueckgestellt.tsv", KOPF_ZURUECK, zurueck)
    audit = sorted(({k: b[k] for k in KOPF_AUDIT} for b in belege.values()),
                   key=lambda b: (datetime.fromisoformat(b["zeitstempel"]), b["url"]))
    _tsv_schreiben(aus / "audit_abruf.tsv", KOPF_AUDIT, audit)
    meta = _meta(kat, ww, belege, indikatoren)
    tmp = aus / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(aus / "meta.json")

    status = {}
    for w in werte:
        status[(w["raumebene"], w["status"])] = status.get((w["raumebene"], w["status"]), 0) + 1
    print(f"Blatt Daten: {kat.n_zeilen} Zeilen, je Raumebene {dict(sorted(kat.ebenen_alle.items()))}; übernommen "
          f"{len(kat.zeilen)} Zeilen")
    print(f"Indikatoren: {len(ind_k)} Köln, {len(ind_w)} Wegweiser; zurückgestellt {len(zur_k)} Köln, {len(zur_w)} "
          "Wegweiser")
    for ebene in EBENEN_REIHENFOLGE:
        teile = {s: status.get((ebene, s), 0) for s in ("ok", "geheim", "fehlt", "abgeleitet")}
        print(f"werte.tsv {ebene}: {sum(teile.values())} Zeilen, {teile}")
    print(f"gesamtstadt.tsv: {len(gesamt)} Zeilen, „k.A.“ nicht übernommen: {len(ww.ka)}")
    for h in hinweise:
        print(f"  {h}")
    for name in ("indikatoren.tsv", "werte.tsv", "gesamtstadt.tsv", "zurueckgestellt.tsv", "audit_abruf.tsv",
                 "meta.json"):
        print(f"  {name}: {(aus / name).stat().st_size} Bytes")
    return meta


def abruf_schritt():
    """Einstieg für `python -m pipeline strukturdaten-abruf`."""
    try:
        abruf_lauf()
    except ValueError as e:   # Einstellungsfehler (etwa User-Agent mit Steuerzeichen): nichts gesendet
        print(f"strukturdaten-abruf: {e}", file=sys.stderr)
        raise SystemExit(2) from e
