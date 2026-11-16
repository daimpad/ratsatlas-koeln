"""Dokumente (PDF-Köpfe): federführende Dienststelle aus dem Kopf der Verwaltungsvorlagen („Dezernat, Dienststelle“,
CLAUDE.md 5.3). Gebaut und getestet, aber abgeschaltet (Entscheidung des Auftraggebers 13.11.2026): Der Auftraggeber
ruft die Stadt vorher an; danach ist die erste Nacht mit RATSATLAS_PDF_MAX=100 der Test, später gelten 300 je Nacht
(Entscheidung 13.11.2026 (c)).

Freigabe: keine Anfrage ohne RATSATLAS_STADT_INFORMIERT=ja UND RATSATLAS_PDF_FREIGEGEBEN=ja (Repository-Variablen,
auch für lokale Testserver). Ohne beide schreibt der Schritt nichts (weder Zustand noch Abrufstatistik): Nächte ohne
Freigabe sind in Anfragen und Abrufzustand gleich wie ohne diesen Schritt.

Abrufpolitik: dieselbe wie beim Abruf der Metadaten (pipeline/abruf.py, `get_datei` teilt Abstand, Zeitfenster,
Zählwerk und Fehlerbehandlung mit `get_json`): eine Verbindung, mindestens 2 s Abstand (ein eigener Prozess nach dem
Abrufschritt; der Abstand zählt ab dem Start des Prozesses, also auch zur letzten Anfrage des Abrufs), Zeitfenster
23–1 Uhr vor jedem Versuch, User-Agent mit RATSATLAS_KONTAKT (Pflicht), keine Weiterleitung, 401/403/404 sofortiger
Abbruch, 429/5xx Pausen nie über das Fenster hinaus. Vor der ersten Anfrage gelten dieselben Pausen wie für den Abruf
(sessionnet._pause_grund: 12-Stunden-Regel nach jedem Abbruch, auch einem des Abrufs in dieser Nacht, Retry-After,
sieben Tage nach drei Nächten mit möglicher Sperre). Vorrang der Metadaten: Der Schritt läuft nach dem Abruf und nur,
wenn dieser in derselben Nacht vollständig war (`abruf_ok` in STAND.json; lokal genügt ein `abruf_ok`).
Abbrüche vermerkt er im selben Zustand (zustand_abruf.json): `letzter_abbruch` (kein weiterer Lauf in derselben
Nacht, auch kein Abruf), `sperre_verdacht` nach sessionnet.moegliche_sperre, `nicht_vor` aus einem Retry-After,
`tlsfehler`; dazu eigene Zählung unter `dokumente.verdacht` (Nächte mit möglicher Sperre beim Dokumentabruf, nach drei
Nächten sieben Tage keine Dokumente; zurückgesetzt nach einem Lauf ohne Abbruch mit mindestens einer gelesenen Datei),
weil ein vollständiger Abruf der Metadaten `sperre_verdacht` jede Nacht zurücksetzt. Das Ende des Zeitfensters ist
kein Fehler. Je Datei höchstens LESEFRIST Sekunden ab dem Senden für Verbindungsaufbau, Kopf und Inhalt (Wächter in
abruf.get_datei, auch bei tröpfelnder Antwort; Prüfung dok-f).

Fehlversuche je Datei (Prüfung dok-f, bestätigt als Entscheidung 13.11.2026 (b)): Ein Abbruch, der an der Datei liegen
kann (HTTP 401, 403, 429, Weiterleitung, „aufgegeben“ nach 429/5xx, Zeitüberschreitung, Lesefrist, abgeschnittene
Antwort), und `fehler_pruefung` (der Prüfprozess scheiterte) werden zur Datei vorläufig vermerkt (Status
`abbruch_<Art>` bzw. `fehler_pruefung`, Zähler `fehlversuche`). Die Sperrlogik bleibt dabei unverändert (Abbruch der
Nacht, gemeinsame und eigene Zählung). In der nächsten Nacht steht die Datei hinter allen anderen (so hält eine einzelne
Datei mit dauerhaftem Fehler die älteren nicht auf); nach FEHLVERSUCHE_GRENZE Nächten ohne Ergebnis wird sie nicht mehr
angefragt, bis sich ihre Merkmale ändern. Abbrüche der Ausführungsumgebung (tls, proxy) zählen nicht zur Datei.

Obergrenze: höchstens RATSATLAS_PDF_MAX Dateien je Nacht (Vorgabe 300; leer oder nicht gesetzt: 300; 0, negativ oder
unlesbar: keine Anfrage). Gezählt wird jede Datei, für die eine Anfrage beginnt, im Zustand (`dokumente.nacht`,
`dokumente.dateien`; Nacht = 12 Uhr bis 12 Uhr Ortszeit), vor dem Senden: Ein zweiter Lauf in derselben Nacht (Push,
Knopfdruck) liest nur den Rest.

Auswahl (ohne Anfrage, aus papers.jsonl, organizations.json und beratungen.jsonl; fehlt eine der drei Dateien, keine
Anfrage): je Verwaltungsvorlage höchstens eine Datei: die Hauptdatei (`mainFile`); fehlt sie (in Köln bisher bei allen
gemessenen Vorlagen: Stufe 1 25 von 25, Stufe 2 100 von 100 jüngsten, nur `auxiliaryFile` mit 1–3 PDF-Dateien;
explore/BERICHT_phase1.md), nach der Entscheidung des Auftraggebers vom 13.11.2026 (a) eine Datei aus `auxiliaryFile`:
unter den PDF-Dateien (laut `mimeType`, ohne ihn nur mit der Endung „.pdf“) in der Reihenfolge der Quelle die erste,
deren `name` oder `fileName` die Drucksache (1234/2026, 1234-2026, 1234_2026) oder das Wort „Vorlage“ trägt, sonst die
erste (datei_wahl; Herkunft `quelle` im Eintrag). Verwaltungsvorlagen: Drucksache NNNN/JJJJ und Vorlagenart der
Verwaltung (actors.VERWALTUNG_TYPES, nicht actors.EINWOHNER_TYPES, als Zeichenkette geliefert). Nie: Vorlagen ohne
Erlaubnis für Hauskoordinaten oder in der Titelmaske (gesperrt(): dieselben Funktionen und Angaben wie build und check:
geocode.punkt_ausschluss mit Eingaben, Vorlagen natürlicher Personen, Ausschuss für Anregungen und Beschwerden, nicht
erkennbare Vorlagenart, maske.py; Fixpunkt geocode.sperrmenge; Titelmaske maske.kette), nicht öffentliche Beratungen
(`public` weder true noch fehlend) und Sammellisten nichtöffentlicher Punkte, und keine Datei, die auch bei einer
solchen Vorlage steht (Hauptdatei oder Anlage), auch bei einer ausgelassenen (ohne Drucksachennummer oder als gelöscht
gemeldet) und auch unter einer anderen Kennung mit derselben Adresse (Kennung, downloadUrl und accessUrl in der
Vergleichsform _adresse; Prüfung dok2). Gezählt werden Vorlagen ohne PDF-Datei (weder `mainFile` noch eine
PDF-Datei in `auxiliaryFile`). Nur Adressen auf dem Host der OParl-API (config.OPARL_BODY: Schema, Host und Port
gleich; `downloadUrl`, sonst `accessUrl`), nur PDF laut `mimeType` (falls angegeben), höchstens MAX_BYTES laut `size`;
eine gewählte Anlage, die daran scheitert, wird nicht durch eine andere ersetzt. Neueste zuerst (Datum der Vorlage,
dann `created`), Dateien mit Fehlversuch dahinter; die Obergrenze je Nacht gilt für Haupt- und Anlagedateien zusammen.
Schon verarbeitete Dateien (auch mit endgültigem Fehler) nur erneut, wenn sich `modified`, `size`, `accessUrl` oder
`downloadUrl` der Datei oder ihre Herkunft geändert haben (eine Anlage, die zur Hauptdatei wird, einmal neu).

Verarbeitung: Vor der ersten Anfrage einer Nacht prüft ein Selbsttest den Prüfprozess an einer eingebauten Probedatei
mit erfundenem Kopf (`selbsttest`); liefert er nicht das erwartete Ergebnis (pypdf fehlt in der isolierten Umgebung,
eine andere Version antwortet anders, Absturz), geht keine Anfrage hinaus (Warnung). Die Antwort bleibt im
Arbeitsspeicher (höchstens MAX_BYTES, Lesefrist LESEFRIST), wird nie auf die Platte geschrieben und nach der Prüfung
verworfen, auch bei einem Fehler. Geprüft wird in einem eigenen Prozess
(pipeline/pdfkopf.py, `python -I`, ohne Umgebungsvariablen außer PATH, Grenzen für Speicher, Rechenzeit, Dateien und
Speicherabzüge, Frist PRUEF_FRIST; nur Seite 1 mit pypdf, keine externen Werkzeuge); er gibt nur Status, Trefferart,
Kennung und den Namen einer Fehlerklasse zurück, nie Text. Gespeichert wird je Datei nur Abgeleitetes in
data/raw/dokumente_koepfe.jsonl (config.DOKUMENTE; im Zwischenspeicher des Workflows wie die übrigen Rohdaten, nicht
im Repository, nicht auf der Seite, nicht im Datenpaket): OParl-Kennung der Datei und der Vorlage, SHA-256, Größe,
Zeitpunkt, Kennung, Trefferart, Status, Fehlerklasse, Zahl der Fehlversuche, Herkunft (`quelle`: mainFile oder
auxiliaryFile) und die Merkmale der Datei zur Erkennung von Änderungen (`modified`, `size`, `accessUrl`, `downloadUrl`
aus den Metadaten). Jeder Eintrag wird vor dem Schreiben und beim Lesen gegen feste Formen geprüft (FELDER,
pdfkopf.KENNUNG_FORM). Log und Abrufstatistik nennen nur Zahlen.

Verwendung: build übernimmt die Kennung als Federführung nur ohne `underDirectionOf`, nur für die Datei, die jetzt für
die Vorlage gilt, mit derselben Herkunft wie beim Lesen (kopf_der_vorlage), nur für Verwaltungsvorlagen wie in der
Auswahl und nur bei Vorlagen mit Erlaubnis für Hauskoordinaten (actors.responsibilities, pdfkopf.VERWENDUNG): aus
`mainFile` Methode „pdf_kopf“, Konfidenz „mittel“ bzw. „niedrig“ nach Trefferart, Fundstelle „Kopf der Vorlage (S. 1):
<Kennung>“; aus `auxiliaryFile` Methode „pdf_kopf_anlage“, Konfidenz eine Stufe niedriger („niedrig“; die
ausgeschriebene Form, aus der Hauptdatei schon „niedrig“, wird aus einer Anlage nicht übernommen), Fundstelle „Kopf der
Anlage (S. 1): <Kennung>“. Erscheint später die Hauptdatei oder ändert sich die Wahl unter `auxiliaryFile`, gilt das
alte Ergebnis nicht mehr; die neue Datei wird gelesen. Die Kennung bleibt ohne Organisation der OParl-Daten; Dezernat
und Dienststelle ordnet `export` über die Ämtertabelle zu (pipeline/aemter.py: `zuordnen` mit Kennung und Datum der
Vorlage), die Seite zeigt die Kennung und darunter diese Zuordnung.
"""
import hashlib
import json
import os
import posixpath
import re
import signal
import subprocess
import sys
import urllib.parse
from collections import Counter
from datetime import timedelta
from pathlib import Path

from . import abruf, actors, config, geocode, maske, pdfkopf, sessionnet, volltext
from .fetch import _now, _write

FREIGABE = "RATSATLAS_PDF_FREIGEGEBEN"
HOECHSTENS = "RATSATLAS_PDF_MAX"
HOECHSTENS_VORGABE = 300
MAX_BYTES = 25_000_000           # je Datei (laut size, Content-Length und gelesen)
LESEFRIST = 120                  # Sekunden für eine ganze Antwort ab dem Senden (darüber: mögliche Sperre)
PRUEF_FRIST = 60                 # Sekunden für den Prüfprozess (Wanduhr)
PRUEF_CPU = 30                   # Sekunden Rechenzeit im Prüfprozess
PRUEF_SPEICHER = 1 << 30         # Adressraum des Prüfprozesses (1 GiB)
VERDACHT_NAECHTE = 3
VERDACHT_PAUSE = timedelta(days=7)
# Nächte ohne Ergebnis für dieselbe unveränderte Datei (vorläufiger Status), danach zurückgestellt bis zu einer Änderung
FEHLVERSUCHE_GRENZE = 2
SCHLUESSEL = "dokumente"         # Eintrag im Zustand (zustand_abruf.json)
RE_VERWALTUNGSVORLAGE = re.compile(r"^\d{1,4}/\d{4}$")
# Felder eines Eintrags in config.DOKUMENTE; nichts sonst wird geschrieben
FELDER = ("file", "paper", "quelle", "sha256", "groesse", "zeit", "kennung", "trefferart", "status", "fehlerart",
          "fehlversuche", "modified", "size", "accessUrl", "downloadUrl")
MERKMALE = ("modified", "size", "accessUrl", "downloadUrl")
# Herkunft der gelesenen Datei: die Hauptdatei oder, wenn sie fehlt, eine Datei aus `auxiliaryFile` (Entscheidung
# 13.11.2026 (a)); bestimmt Methode und Konfidenz der Federführung (pdfkopf.VERWENDUNG)
QUELLEN = ("mainFile", "auxiliaryFile")
# Name einer Datei in auxiliaryFile, der sie als Vorlage ausweist: das Wort „Vorlage“, auch als Wortteil
# („Beschlussvorlage“), in beliebiger Schreibung (daneben die Drucksache, _drucksache_muster)
RE_VORLAGE_WORT = re.compile(r"vorlage", re.I)
# Status je Datei: aus dem Prüfprozess (pdfkopf.STATUS) oder vom Abruf
STATUS = (*pdfkopf.STATUS, "zeitueberschreitung", "fehler_pruefung", "zu_gross", "kein_pdf", "adresse")
RE_HTTP_STATUS = re.compile(r"http_[1-5]\d\d")
# vorläufige Status (Fehlversuch, die Datei kommt in einer späteren Nacht wieder dran): Abbruch, der an der Datei
# liegen kann, und ein gescheiterter Prüfprozess
RE_ABBRUCH = re.compile(r"abbruch_(?:sperre|aufgegeben|weiterleitung|http_[1-5]\d\d)")
VORLAEUFIG = ("fehler_pruefung",)
RE_SHA256 = re.compile(r"[0-9a-f]{64}")
# Gründe, aus denen eine Vorlage oder Datei nicht ausgewählt wird (Log und Abrufstatistik)
GRUENDE = {
    "drucksache": "Drucksache nicht NNNN/JJJJ", "vorlagenart": "keine Vorlagenart der Verwaltung",
    "ohne_hauskoordinate": "ohne Hauskoordinate oder Titelmaske", "nicht_oeffentlich": "nicht öffentlich beraten",
    "ohne_datei": "ohne mainFile und ohne PDF-Datei in auxiliaryFile", "doppelt": "Datei schon ausgewählt",
    "datei_gesperrt": "Datei (Kennung oder Adresse) auch bei einer ausgeschlossenen Vorlage",
    "kein_pdf": "kein PDF laut mimeType",
    "fremder_host": "Adresse nicht auf dem Host der OParl-API", "zu_gross": f"über {MAX_BYTES // 1_000_000} MB laut size",
    "bekannt": "schon verarbeitet, unverändert",
    "fehlversuche": f"nach {FEHLVERSUCHE_GRENZE} Nächten ohne Ergebnis zurückgestellt",
}


def freigegeben():
    """Beide Freigaben gesetzt? Ohne sie keine Anfrage und kein Schreibvorgang (auch nicht für lokale Testserver)."""
    return os.environ.get("RATSATLAS_STADT_INFORMIERT") == "ja" and os.environ.get(FREIGABE) == "ja"


def hoechstens():
    """Dateien je Nacht aus RATSATLAS_PDF_MAX: nicht gesetzt oder leer → HOECHSTENS_VORGABE; eine ganze Zahl → sie
    (0 oder negativ → 0); unlesbar → 0 (keine Anfrage)."""
    wert = (os.environ.get(HOECHSTENS) or "").strip()
    if not wert:
        return HOECHSTENS_VORGABE
    return max(int(wert), 0) if re.fullmatch(r"[+-]?\d{1,9}", wert) else 0


def _nacht(jetzt):
    """Nacht eines Zeitpunkts: 12 Uhr bis 12 Uhr Ortszeit Köln, benannt nach dem Abend (wie die 12-Stunden-Regel)."""
    return (jetzt.astimezone(abruf.ORTSZEIT) - timedelta(hours=12)).date().isoformat()


def _ursprung(url):
    """(Schema, Host, Port) mit Standardport; None bei einer unlesbaren Adresse."""
    try:
        t = urllib.parse.urlsplit(url)
        port = t.port or {"http": 80, "https": 443}.get(t.scheme)
        return t.scheme, (t.hostname or "").rstrip("."), port
    except (ValueError, TypeError, AttributeError):
        return None


def auf_oparl_host(url):
    """Liegt die Adresse auf dem Host der OParl-API (config.OPARL_BODY: Schema, Host und Port gleich) und wäre sie
    sendbar (abruf.adresse_pruefen)? Sonst wird sie nicht gesendet."""
    if not isinstance(url, str) or abruf.adresse_pruefen(url):
        return False
    eigen, ziel = _ursprung(config.OPARL_BODY), _ursprung(url)
    return bool(eigen and ziel and eigen[1] and eigen == ziel)


# --- Einträge (nur Abgeleitetes) --------------------------------------------------------------------------------------

def _merkmal(wert):
    """Merkmal einer Datei aus den Metadaten: Zeichenkette (höchstens 2000 Zeichen) oder ganze Zahl, sonst None."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, int) or isinstance(wert, str) and len(wert) <= 2000:
        return wert
    return None


def vorlaeufig(status):
    """Vorläufiger Status (Fehlversuch): `fehler_pruefung` oder `abbruch_<Art>`."""
    return isinstance(status, str) and (status in VORLAEUFIG or bool(RE_ABBRUCH.fullmatch(status)))


def eintrag_gueltig(e):
    """Hat ein Eintrag genau die erlaubte Form (FELDER, Werte nach festen Mustern)? Was nicht passt, wird weder
    geschrieben noch gelesen: So gelangt kein Text des Dokuments in den Zustand."""
    if not isinstance(e, dict) or set(e) != set(FELDER):
        return False
    if not all(isinstance(e[k], str) and e[k] and len(e[k]) <= 2000 for k in ("file", "paper")):
        return False
    if e["quelle"] not in QUELLEN:
        return False
    status, art, kennung = e["status"], e["trefferart"], e["kennung"]
    if not (status in STATUS or isinstance(status, str) and RE_HTTP_STATUS.fullmatch(status) or vorlaeufig(status)):
        return False
    n = e["fehlversuche"]
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 99 or vorlaeufig(status) != (n >= 1):
        return False
    if not isinstance(art, str) or not isinstance(kennung, str) or not isinstance(e["fehlerart"], str):
        return False
    if (art and (status != "ok" or art not in pdfkopf.TREFFERARTEN) or status == "ok" and not art
            or kennung and (art not in pdfkopf.MIT_KENNUNG or not pdfkopf.KENNUNG_FORM.fullmatch(kennung))
            or art in pdfkopf.MIT_KENNUNG and not kennung):
        return False
    if e["fehlerart"] and not pdfkopf.FEHLERART.fullmatch(e["fehlerart"]):
        return False
    if not (e["sha256"] == "" or isinstance(e["sha256"], str) and RE_SHA256.fullmatch(e["sha256"])):
        return False
    if not (e["groesse"] is None or isinstance(e["groesse"], int) and not isinstance(e["groesse"], bool)
            and 0 <= e["groesse"] <= MAX_BYTES):
        return False
    if not (isinstance(e["zeit"], str) and sessionnet._zeit(e["zeit"])):
        return False
    return all(_merkmal(e[k]) == e[k] for k in MERKMALE)


def laden():
    """Einträge je Datei (der letzte gilt); ungültige Zeilen werden verworfen und gezählt (Warnung). Liefert {Datei:
    Eintrag}."""
    if not config.DOKUMENTE.exists():
        return {}
    eintraege, verworfen = {}, 0
    with open(config.DOKUMENTE, encoding="utf-8", errors="replace") as f:
        for zeile in f:
            if not zeile.strip():
                continue
            try:
                e = json.loads(zeile)
            except (ValueError, RecursionError):
                e = None
            if eintrag_gueltig(e):
                eintraege[e["file"]] = e
            else:
                verworfen += 1
    if verworfen:
        sessionnet._warnung(f"{config.DOKUMENTE.name}: {verworfen} Zeilen in unerwarteter Form verworfen")
    return eintraege


def _schreiben(eintraege):
    """Alle Einträge geordnet und ohne Doppel (atomar)."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.DOKUMENTE, "".join(json.dumps({k: e[k] for k in FELDER}, ensure_ascii=True) + "\n"
                                     for _, e in sorted(eintraege.items())))


def _anhaengen(e):
    """Einen Eintrag sofort anhängen (ein Abbruch des Prozesses verliert so höchstens die laufende Datei)."""
    if not eintrag_gueltig(e):
        raise ValueError("Eintrag der Dokumente in unerwarteter Form; nicht geschrieben")
    config.RAW.mkdir(parents=True, exist_ok=True)
    with open(config.DOKUMENTE, "a", encoding="utf-8") as f:
        f.write(json.dumps({k: e[k] for k in FELDER}, ensure_ascii=True) + "\n")


def koepfe():
    """Dateien mit erkannter Kennung (Status ok, Trefferart mit Kennung): {Datei-Kennung: Eintrag}, für build. Ohne
    Datei: {} (der Aufbau bleibt dann wie ohne diesen Schritt)."""
    return {f: e for f, e in laden().items() if e["status"] == "ok" and e["trefferart"] in pdfkopf.MIT_KENNUNG}


def kopf_der_vorlage(p, koepfe_):
    """Eintrag mit Kennung für die Datei, die jetzt für die Vorlage gilt (datei_wahl), nur wenn er für dieselbe Datei mit
    derselben Herkunft gelesen wurde, und nur für Verwaltungsvorlagen wie in der Auswahl (sonst bekäme etwa ein Antrag
    mit derselben Datei als Anlage die Kennung der Verwaltung); sonst None. So ersetzt die Hauptdatei, die später
    erscheint, das Ergebnis einer Anlage, und eine geänderte Wahl unter auxiliaryFile das bisherige, sobald die neue Datei
    gelesen ist (bis dahin keine Federführung aus einem Kopf). `p`: Vorlage nach build.einlesen; `koepfe_`: koepfe()."""
    if not (RE_VERWALTUNGSVORLAGE.match(p["reference"]) and _verwaltungsvorlage(p)):
        return None
    datei, quelle = datei_wahl(p)
    e = koepfe_.get(datei["id"]) if datei else None
    return e if e and e["quelle"] == quelle else None


# --- Auswahl (ohne Anfrage) ---------------------------------------------------------------------------------------------

def gesperrt(papers, ausgelassen, orgs_by_id):
    """Vorlagen ohne Erlaubnis für Hauskoordinaten oder in der Titelmaske, mit denselben Funktionen und Angaben wie
    build (build.angaben_roh, geocode.punkt_ausschluss, geocode.sperrmenge über geocode.beziehungen) und maske.aus_db
    (maske.kette mit maske.ausgang_punktregel). `papers`, `ausgelassen`: nach build.einlesen. Liefert die Menge der IDs
    (auch Kennungen ohne Vorlage, über die eine Beziehung läuft)."""
    from . import build   # hier: build importiert dieses Modul
    gremien, amt = build.angaben_roh(papers, orgs_by_id)
    rel, related = geocode.beziehungen(papers + ausgelassen)
    start = {p["id"] for p in papers if geocode.punkt_ausschluss(p, gremien[p["id"]], amt[p["id"]])}
    start |= {a["id"] for a in ausgelassen}
    weg = geocode.sperrmenge(start, rel + related, {p["id"]: p["reference"] for p in papers})
    vorlagen = [(p["id"], p["reference"], p.get("paperType"), p.get("name"), amt[p["id"]]) for p in papers]
    punktregel = [p["id"] for p in papers if maske.ausgang_punktregel(p, gremien[p["id"]])]
    titelmaske = maske.kette(vorlagen, [a["id"] for a in ausgelassen], rel + related, punktregel=punktregel)
    return set(weg) | set(titelmaske)


def _nicht_oeffentlich(p, oeffentlich):
    """Eine Beratung auf einem nicht öffentlichen Tagesordnungspunkt (`public` in beratungen.jsonl weder true noch
    fehlend, vorsichtig: auch ein unerwarteter Wert wie "false" als Text) oder eine Sammelliste nichtöffentlicher Punkte
    (volltext.sammelliste)?"""
    return (any(oeffentlich.get(c.get("id"), True) not in (True, None)
                for c in p.get("consultation") or () if isinstance(c, dict))
            or volltext.sammelliste(p.get("name") if isinstance(p.get("name"), str) else ""))


def _verwaltungsvorlage(p):
    art = p.get("paperType")
    return (isinstance(art, str) and not p.get(geocode.ANDERE_FORM) and art in actors.VERWALTUNG_TYPES
            and art not in actors.EINWOHNER_TYPES)


def _datei_ok(f):
    """Eintrag einer Dateiliste als Datei mit Kennung (Objekt, `id` als nicht leere Zeichenkette, nicht gelöscht)?"""
    return isinstance(f, dict) and isinstance(f.get("id"), str) and bool(f["id"]) and not f.get("deleted")


def _pdf_endung(wert):
    """Endet ein Dateiname oder der Pfad einer Adresse auf „.pdf“?"""
    if not isinstance(wert, str):
        return False
    try:
        pfad = urllib.parse.urlsplit(wert).path if "://" in wert else wert
    except ValueError:
        return False
    return pfad.lower().endswith(".pdf")


def _pdf_laut_metadaten(f):
    """Ist eine Datei aus auxiliaryFile eine PDF-Datei? Laut `mimeType`, falls angegeben (wie bei der Hauptdatei);
    fehlt er, nur mit der Endung „.pdf“ in `fileName`, `downloadUrl` oder `accessUrl`: Anlagen sind oft keine PDF-Dateien
    (Tabellen, Pläne), und eine Antwort ohne PDF-Kennung beendet die Nacht als mögliche Sperre."""
    mime = f.get("mimeType")
    if isinstance(mime, str) and mime.strip():
        return mime.split(";")[0].strip().lower() == "application/pdf"
    return any(_pdf_endung(f.get(k)) for k in ("fileName", "downloadUrl", "accessUrl"))


def _drucksache_muster(reference):
    """Muster der Drucksache NNNN/JJJJ in einem Dateinamen: Nummer (auch mit führenden Nullen), „/“, „-“ oder „_“, Jahr,
    nicht innerhalb einer längeren Zahl („11234/2026“, „1234/20261“ nicht); None für andere Drucksachen."""
    m = re.fullmatch(r"(\d{1,4})/(\d{4})", reference if isinstance(reference, str) else "")
    if not m:
        return None
    return re.compile(r"(?<![0-9])0*" + str(int(m.group(1))) + r"[/_-]" + m.group(2) + r"(?![0-9])")


def datei_wahl(p):
    """Datei, deren erste Seite für die Vorlage gelesen wird, und ihre Herkunft: (Datei, „mainFile“), sonst (Entscheidung
    des Auftraggebers 13.11.2026 (a)) höchstens eine Datei aus `auxiliaryFile`: unter den PDF-Dateien
    (_pdf_laut_metadaten) in der Reihenfolge der Quelle die erste, deren `name` oder `fileName` die Drucksache (1234/2026,
    1234-2026, 1234_2026) oder das Wort „Vorlage“ trägt, sonst die erste (Datei, „auxiliaryFile“); ohne beides (None,
    None). Eine Hauptdatei in anderer Form als PDF bleibt die Wahl (ausgeschlossen als „kein PDF laut mimeType“, keine
    Anlage ersatzweise). Eine Funktion für die Auswahl und für build (kopf_der_vorlage)."""
    mf = p.get("mainFile")
    if _datei_ok(mf):
        return mf, "mainFile"
    aux = p.get("auxiliaryFile")
    aux = [aux] if isinstance(aux, dict) else aux if isinstance(aux, list) else []
    pdfs = [f for f in aux if _datei_ok(f) and _pdf_laut_metadaten(f)]
    if not pdfs:
        return None, None
    muster = _drucksache_muster(p.get("reference"))
    for f in pdfs:
        namen = [f[k] for k in ("name", "fileName") if isinstance(f.get(k), str)]
        if any(RE_VORLAGE_WORT.search(n) or muster and muster.search(n) for n in namen):
            return f, "auxiliaryFile"
    return pdfs[0], "auxiliaryFile"


def _adresse(wert):
    """Vergleichsform einer Datei-Kennung oder Adresse, nur für den Ausschluss und daher eher zu weit als zu eng
    (Prüfung dok2: dieselbe Datei kann unter einer anderen Kennung oder in anderer Schreibung stehen): ohne Schema,
    Port, Zugangsdaten und Fragment; Host ohne abschließenden Punkt; Pfad prozentdekodiert, mehrfache „/“
    zusammengefasst, „.“ und „..“ aufgelöst; Teile der Query dekodiert und sortiert; alles in Kleinbuchstaben. None für
    anderes als eine nicht leere Zeichenkette."""
    if not isinstance(wert, str) or not wert.strip():
        return None
    wert = wert.strip()
    try:
        t = urllib.parse.urlsplit(wert)
        host, pfad, query = (t.hostname or "").rstrip("."), t.path, t.query
    except ValueError:
        host, pfad, query = "", wert, ""
    pfad = posixpath.normpath(re.sub(r"/+", "/", "/" + urllib.parse.unquote(pfad)))
    teile = sorted(x for x in urllib.parse.unquote(query).split("&") if x)
    return (host + pfad + ("?" + "&".join(teile) if teile else "")).lower()


def _adressen_der_datei(f):
    """Vergleichsformen (_adresse) von Kennung, downloadUrl und accessUrl eines Dateiobjekts."""
    return {a for a in (_adresse(f.get(k)) for k in ("id", "downloadUrl", "accessUrl")) if a}


def _dateiadressen(p):
    """Vergleichsformen aller Dateien einer Vorlage in Rohform (wie in papers.jsonl, auch einer ausgelassenen):
    Kennung, downloadUrl und accessUrl jedes Eintrags in mainFile und auxiliaryFile, als Objekt, Liste oder Verweis
    (Zeichenkette), auch als gelöscht gemeldete Einträge."""
    aus = set()
    for feld in ("mainFile", "auxiliaryFile"):
        wert = p.get(feld)
        for f in wert if isinstance(wert, list) else [wert]:
            if isinstance(f, dict):
                aus |= _adressen_der_datei(f)
            elif _adresse(f):
                aus.add(_adresse(f))
    return aus


def auswahl(roh, orgs, beratungen, eintraege):
    """Dateien zum Lesen, neueste zuerst, und Zähler der Gründe, aus denen Vorlagen oder Dateien nicht in Frage kommen
    (GRUENDE). `roh`: Vorlagen wie in papers.jsonl; `orgs`: organizations.json; `beratungen`: Zeilen aus
    beratungen.jsonl; `eintraege`: laden(). Je Vorlage höchstens eine Datei (datei_wahl: mainFile, sonst eine aus
    auxiliaryFile), mit ihrer Herkunft (`quelle`). Dateien, die auch bei einer Vorlage ohne Hauskoordinate (oder in der
    Titelmaske) oder einer nicht öffentlich beratenen stehen, werden nie gelesen (etwa eine Eingabe als Anlage einer
    Mitteilung), auch nicht die einer ausgelassenen Vorlage (ohne Drucksachennummer oder als gelöscht gemeldet; ohne
    Erlaubnis wie in gesperrt()), und auch nicht unter einer anderen Kennung mit derselben Adresse: verglichen werden
    Kennung, downloadUrl und accessUrl in der Vergleichsform _adresse (Prüfung dok2: vorher nur die Kennung, und nur bei
    Vorlagen nach build.einlesen). Eine Datei, die für eine Vorlage Hauptdatei und für eine andere Anlage ist, zählt als
    Hauptdatei. Schon verarbeitete Dateien erst wieder nach einer Änderung ihrer Merkmale oder ihrer Herkunft (eine
    Anlage, die zur Hauptdatei wird, wird einmal neu gelesen)."""
    from . import build   # hier: build importiert dieses Modul
    papers, ausgelassen, _ = build.einlesen(build._je_kennung_einmal(roh))
    orgs_by_id = {o["id"]: o for o in orgs if isinstance(o, dict) and isinstance(o.get("id"), str)}
    sperre = gesperrt(papers, ausgelassen, orgs_by_id)
    oeffentlich = {b.get("uri"): (b.get("agendaItem") or {}).get("public") for b in beratungen
                   if isinstance(b, dict) and isinstance(b.get("agendaItem"), (dict, type(None)))}
    # Dateien ausgeschlossener Vorlagen (Datenschutz, nicht öffentlich): nie lesen, auch nicht über eine andere
    # Vorlage. Aus den Rohdaten, damit die ausgelassenen Vorlagen dabei sind (`sperre` enthält ihre Kennungen,
    # build.einlesen aber nicht ihre Dateien), und aus jeder Zeile mit derselben Kennung (doppelt oder mit Löschvermerk)
    ohne = sperre | {p["id"] for p in papers if _nicht_oeffentlich(p, oeffentlich)}
    ausgeschlossen = set().union(*(_dateiadressen(r) for r in roh
                                   if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"] in ohne))
    gruende, wahl, kandidaten, gesehen = Counter(), [], [], set()
    for p in papers:
        if not RE_VERWALTUNGSVORLAGE.match(p["reference"]):
            gruende["drucksache"] += 1
        elif not _verwaltungsvorlage(p):
            gruende["vorlagenart"] += 1
        elif p["id"] in sperre:
            gruende["ohne_hauskoordinate"] += 1
        elif _nicht_oeffentlich(p, oeffentlich):
            gruende["nicht_oeffentlich"] += 1
        else:
            f, quelle = datei_wahl(p)
            if f is None:
                gruende["ohne_datei"] += 1
            else:
                wahl.append((p, f, quelle))
    wahl.sort(key=lambda w: w[2] != "mainFile")   # stabil: Hauptdateien zuerst (eine Datei, die beides ist)
    for p, f, quelle in wahl:
        mime = f.get("mimeType")
        url = f.get("downloadUrl") or f.get("accessUrl")
        size = f.get("size")
        merkmale = {k: _merkmal(f.get(k)) for k in MERKMALE}
        alt = eintraege.get(f["id"])
        unveraendert = bool(alt) and all(alt.get(k) == merkmale[k] for k in MERKMALE) and alt.get("quelle") == quelle
        # Fehlversuche zählen nur für dieselbe, unveränderte Datei
        fehlversuche = alt.get("fehlversuche", 0) if unveraendert and vorlaeufig(alt.get("status")) else 0
        if f["id"] in gesehen:
            gruende["doppelt"] += 1
        elif _adressen_der_datei(f) & ausgeschlossen:   # Kennung oder eine Adresse (auch `url`) ausgeschlossen
            gruende["datei_gesperrt"] += 1
        elif isinstance(mime, str) and mime.strip() and mime.split(";")[0].strip().lower() != "application/pdf":
            gruende["kein_pdf"] += 1
        elif not auf_oparl_host(url):
            gruende["fremder_host"] += 1
        elif isinstance(size, int) and not isinstance(size, bool) and size > MAX_BYTES:
            gruende["zu_gross"] += 1
        elif unveraendert and fehlversuche >= FEHLVERSUCHE_GRENZE:
            gruende["fehlversuche"] += 1
        elif unveraendert and not fehlversuche:
            gruende["bekannt"] += 1
        else:
            kandidaten.append({"file": f["id"], "paper": p["id"], "quelle": quelle, "url": url, **merkmale,
                               "_fehlversuche": fehlversuche,
                               "_ordnung": (str(p.get("date") or "") if isinstance(p.get("date"), str) else "",
                                            str(p.get("created") or "") if isinstance(p.get("created"), str) else "",
                                            p["id"])})
        gesehen.add(f["id"])
    kandidaten.sort(key=lambda k: k["_ordnung"], reverse=True)
    kandidaten.sort(key=lambda k: k["_fehlversuche"])   # stabil: nach einem Fehlversuch hinter allen anderen
    return kandidaten, gruende


# --- Prüfung einer Datei ------------------------------------------------------------------------------------------------

def _befehl():
    """Prüfprozess (pipeline/pdfkopf.py als Skript, isoliert: -I ohne Pfade aus der Umgebung und ohne Benutzerpakete)."""
    return [sys.executable, "-I", str(Path(pdfkopf.__file__).resolve()), str(PRUEF_SPEICHER), str(PRUEF_CPU)]


def pruefen(daten):
    """Seite 1 im eigenen Prozess prüfen: {status, trefferart, kennung, fehlerart}, nie Text. Die Standardfehlerausgabe
    des Prozesses wird verworfen (sie könnte Teile der Datei enthalten); nur PATH wird weitergegeben (keine Zugangsdaten
    aus der Umgebung). Zeitüberschreitung (Frist oder Rechenzeit): „zeitueberschreitung“; jede andere unerwartete
    Ausgabe: „fehler_pruefung“."""
    leer = {"trefferart": "", "kennung": "", "fehlerart": ""}
    try:
        r = subprocess.run(_befehl(), input=daten, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=PRUEF_FRIST, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    except subprocess.TimeoutExpired:
        return {"status": "zeitueberschreitung", **leer}
    if r.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
        return {"status": "zeitueberschreitung", **leer}
    ergebnis = pdfkopf.ergebnis_pruefen(r.stdout) if r.returncode == 0 else None
    return ergebnis or {"status": "fehler_pruefung", **leer}


def _probedatei():
    """Kleine PDF-Datei mit erfundenem Kopf für den Selbsttest (PDF 1.4, eine Seite, Helvetica, nur ASCII)."""
    strom = b"BT /F1 11 Tf 14 TL 56 780 Td (Probe) Tj T* (Dezernat, Dienststelle) Tj T* (VI/61) Tj T* ET"
    objekte = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
               b"/Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length %d >>\nstream\n" % len(strom) + strom + b"\nendstream"]
    aus, lage = b"%PDF-1.4\n", []
    for i, o in enumerate(objekte, 1):
        lage.append(len(aus))
        aus += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(aus)
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1) + b"".join(b"%010d 00000 n \n" % x for x in lage)
    return aus + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, xref)


PROBE_ERWARTET = {"status": "ok", "trefferart": "kennung", "kennung": "VI/61", "fehlerart": ""}


def selbsttest():
    """Liefert der Prüfprozess für die eingebaute Probedatei das erwartete Ergebnis? Sonst (pypdf fehlt in der isolierten
    Umgebung, eine andere Version antwortet anders, Absturz) keine Anfrage in dieser Nacht: Jede Datei käme als
    `fehler_pruefung` zurück, die Anfragen an die Stadt wären vergeudet."""
    return pruefen(_probedatei()) == PROBE_ERWARTET


# --- Zustand ------------------------------------------------------------------------------------------------------------

def _eigener_zustand(z, jetzt, grenze):
    """Eintrag `dokumente` im Zustand vorsichtig lesen: unlesbare Nacht oder Zahl → in dieser Nacht ausgeschöpft
    (`grenze`); unlesbare Zählung der Verdachtsnächte → VERDACHT_NAECHTE, unlesbarer Zeitpunkt → jetzt. Liefert (Eintrag,
    Meldungen)."""
    d = z.get(SCHLUESSEL)
    if d is None:
        return {}, []
    meldungen = []
    if not isinstance(d, dict):
        meldungen.append(f"{SCHLUESSEL} ist kein Objekt")
        d = {}
    d = dict(d)
    if not isinstance(d.get("nacht"), str) or isinstance(d.get("dateien"), bool) \
            or not isinstance(d.get("dateien"), int) or d["dateien"] < 0:
        if "nacht" in d or "dateien" in d:
            meldungen.append(f"{SCHLUESSEL}.nacht/dateien unlesbar, gilt in dieser Nacht als ausgeschöpft")
            d.update(nacht=_nacht(jetzt), dateien=grenze)
    v = d.get("verdacht")
    if v is not None:
        if not isinstance(v, dict):
            v = {}
        v = dict(v)
        n = v.get("naechte")
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            meldungen.append(f"{SCHLUESSEL}.verdacht.naechte unlesbar, gilt als {VERDACHT_NAECHTE}")
            v["naechte"] = VERDACHT_NAECHTE
        t = sessionnet._zeit(v.get("zuletzt"))
        if t is None or t > jetzt:
            meldungen.append(f"{SCHLUESSEL}.verdacht.zuletzt unlesbar oder künftig, gilt als jetzt")
            v["zuletzt"] = jetzt.isoformat(timespec="seconds")
        d["verdacht"] = v
    return d, meldungen


def _eigener_zustand_setzen(**werte):
    """Werte im Eintrag `dokumente` setzen (None entfernt), Rest des Zustands unverändert."""
    d = sessionnet._zustand().get(SCHLUESSEL)
    d = dict(d) if isinstance(d, dict) else {}
    for k, v in werte.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    sessionnet._zustand_setzen(SCHLUESSEL, d)


def _pause(d, jetzt):
    v = d.get("verdacht") or {}
    if v.get("naechte", 0) >= VERDACHT_NAECHTE:
        bis = sessionnet._zeit(v["zuletzt"]) + VERDACHT_PAUSE
        if jetzt < bis:
            return (f"Dokumentabruf pausiert bis {bis.date().isoformat()}: {v['naechte']} Nächte in Folge mit möglicher "
                    "Sperre beim Abruf der Dokumente; bitte Kontakt zur Stadt aufnehmen")
    return None


def _metadaten_dieser_nacht(lokal, jetzt):
    """Vorrang der Metadaten: War der Abruf in dieser Nacht vollständig (`abruf_ok` in STAND.json)? Lokal genügt ein
    vollständiger Abruf."""
    s = sessionnet._stand()
    t = sessionnet._zeit(s.get("abruf_ok"))
    if t is None:
        return False
    return lokal or (_nacht(t) == _nacht(jetzt) and t <= jetzt + timedelta(minutes=5))


def _abbruch_vermerken(e, jetzt):
    """Abbruch im gemeinsamen Zustand wie beim Abruf (sessionnet._abbruch_vermerken, ohne STAND.json): `letzter_abbruch`
    (in dieser Nacht keine weitere Anfrage), `sperre_verdacht` nach sessionnet.moegliche_sperre, `nicht_vor`,
    `tlsfehler`; dazu die eigene Zählung `dokumente.verdacht`. Liefert die Meldung für die Warnung."""
    z = sessionnet._zustand()
    zeit = jetzt.isoformat(timespec="seconds")
    art, code = getattr(e, "art", "") or "programmfehler", getattr(e, "code", None)
    meldung = f"Dokumente: {e}"[:300]
    neu = {"letzter_abbruch": {"zuletzt": zeit, "art": art, "code": code, "meldung": meldung}}
    if art == "tls":
        sessionnet._naechte_zaehlen(z, "tlsfehler", jetzt, {"zuletzt": zeit, "art": art, "meldung": meldung}, neu)
    zusatz = ""
    if sessionnet.moegliche_sperre(e):
        bisher = z.get("sperre_verdacht") or {}
        neu["sperre_verdacht"] = {"naechte": bisher.get("naechte", 0) + 1, "zuletzt": zeit, "art": art, "code": code,
                                  "meldung": meldung}
        d, _ = _eigener_zustand(z, jetzt, 0)
        naechte = (d.get("verdacht") or {}).get("naechte", 0) + 1
        eigen = dict(z[SCHLUESSEL]) if isinstance(z.get(SCHLUESSEL), dict) else {}
        eigen["verdacht"] = {"naechte": naechte, "zuletzt": zeit, "art": art, "code": code}
        neu[SCHLUESSEL] = eigen
        zusatz = (f" Nacht mit möglicher Sperre ({naechte}. beim Dokumentabruf; nach {VERDACHT_NAECHTE} Nächten "
                  f"{VERDACHT_PAUSE.days} Tage keine Dokumente).")
    nicht_vor = getattr(e, "nicht_vor", None)
    if nicht_vor is not None:
        alt = sessionnet._zeit(z.get("nicht_vor"))
        if alt is None or nicht_vor > alt:
            neu["nicht_vor"] = nicht_vor.isoformat(timespec="seconds")
    sessionnet._zustand_aendern(**neu)
    return f"Dokumente abgebrochen; in derselben Nacht keine weitere Anfrage.{zusatz} {e}"[:600]


# --- Schritt ------------------------------------------------------------------------------------------------------------

def _zusammenfassung(kandidaten, lauf, schon, grenze, gruende):
    ergebnisse, versucht = lauf["ergebnisse"], lauf["versucht"]
    arten = Counter(e["trefferart"] for e in ergebnisse if e["status"] == "ok")
    erkannt = sum(arten[a] for a in pdfkopf.MIT_KENNUNG)
    fehler = Counter(e["status"] for e in ergebnisse if e["status"] != "ok")
    nachrang = sum(1 for k in kandidaten if k["_fehlversuche"])
    auswahl_ = Counter(k["quelle"] for k in kandidaten)
    teile = [f"Auswahl {len(kandidaten)} Dateien (neu, geändert oder nach einem Fehlversuch erneut: {nachrang}), in "
             f"diesem Lauf {versucht} (in dieser Nacht {schon + versucht} von höchstens {grenze})",
             "Herkunft: Auswahl " + ", ".join(f"aus {q} {auswahl_[q]}" for q in QUELLEN) + "; in diesem Lauf "
             + ", ".join(f"aus {q} {lauf['quellen'][q]}" for q in QUELLEN)
             + f"; Vorlagen ohne PDF-Datei {gruende['ohne_datei']}",
             f"erkannt {erkannt} (" + ", ".join(f"{a} {arten[a]}" for a in pdfkopf.MIT_KENNUNG) + ")",
             "ohne Kennung " + ", ".join(f"{a} {arten[a]}" for a in pdfkopf.OHNE_KENNUNG),
             "nicht gelesen oder geprüft " + (", ".join(f"{s} {n}" for s, n in sorted(fehler.items())) or "0"),
             "übersprungen: " + ", ".join(f"{GRUENDE[g]} {gruende[g]}" for g in GRUENDE)]
    return "; ".join(teile)


def schritt():
    """`python -m pipeline dokumente` (pages.yml nach dem Abruf). Ohne beide Freigaben: keine Anfrage, nichts
    geschrieben. Sonst eine Zeile `dokumente` in der Abrufstatistik (Anfragen, Dateien, erkannt, übersprungen je Grund),
    auch wenn der Schritt ohne Anfrage endet. Programm- und Einstellungsfehler: vermerkt (12-Stunden-Regel) und laut
    weitergereicht."""
    if not freigegeben():
        print("Dokumente (PDF-Köpfe): abgeschaltet; ohne RATSATLAS_STADT_INFORMIERT=ja und RATSATLAS_PDF_FREIGEGEBEN=ja "
              "keine Anfrage (Entscheidung 13.11.2026).")
        return
    vorher = abruf.statistik()
    zeile = {"datum": _now(), "liste": SCHLUESSEL, "modus": "pdf-koepfe", "objekte": 0}
    try:
        zeile["ergebnis"] = _lauf(zeile)
    except Exception as e:
        zeile["ergebnis"] = f"programmfehler: {type(e).__name__}: {e}"[:300]
        try:
            _abbruch_vermerken(e, abruf.uhr())
        except Exception as f:   # den eigentlichen Fehler nicht verdrängen
            sessionnet._warnung(f"Abbruch der Dokumente nicht im Zustand vermerkt ({type(f).__name__}: {f})")
        raise
    finally:
        sessionnet._differenz(zeile, vorher)
        sessionnet._statistik_sicher(zeile)
    print(f"Dokumente (PDF-Köpfe): {zeile['ergebnis']}")


def _uebersprungen(grund, warnung=False):
    (sessionnet._warnung if warnung else print)(f"Dokumente übersprungen ({grund}); keine Anfrage.")
    return f"übersprungen: {grund}"


def _lauf(zeile):
    """Prüfungen vor der ersten Anfrage, Auswahl, Lesen und Prüfen; liefert den Text für die Abrufstatistik."""
    jetzt = abruf.uhr()
    lokal = abruf.lokal(config.OPARL_BODY)
    grenze = hoechstens()
    if grenze <= 0:
        return _uebersprungen(f"{HOECHSTENS}={os.environ.get(HOECHSTENS)!r} ist 0, negativ oder unlesbar", True)
    fehlt = [f.name for f in (config.PAPERS, config.ORGANIZATIONS, config.BERATUNGEN) if not f.exists()]
    if fehlt:   # ohne Gremien und Beratungen ließen sich Ausschuss- und Öffentlichkeitsregel nicht anwenden
        return _uebersprungen(f"Rohdaten fehlen ({', '.join(fehlt)})")
    if not lokal and not abruf.im_zeitfenster():
        return _uebersprungen(f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr")
    if not lokal and not config.KONTAKT:
        raise ValueError("RATSATLAS_KONTAKT fehlt (Kontakt im User-Agent ist Pflicht, CLAUDE.md 5.1); keine Anfrage "
                         "gesendet")
    z = sessionnet._zustand_pruefen()
    grund = sessionnet._pause_grund(z, lokal)
    if grund:
        return _uebersprungen(grund, True)
    d, meldungen = _eigener_zustand(z, jetzt, grenze)
    if meldungen:
        sessionnet._zustand_setzen(SCHLUESSEL, d)
        sessionnet._warnung(f"{config.ZUSTAND.name}: " + "; ".join(meldungen) + " (neu geschrieben)")
    grund = _pause(d, jetzt)
    if grund:
        return _uebersprungen(grund, True)
    if not _metadaten_dieser_nacht(lokal, jetzt):
        return _uebersprungen("Abruf der Metadaten in dieser Nacht nicht vollständig (Vorrang der Metadaten)")
    nacht = _nacht(jetzt)
    schon = d.get("dateien", 0) if d.get("nacht") == nacht else 0
    eintraege = laden()
    roh = [json.loads(x) for x in config.PAPERS.read_text(encoding="utf-8").splitlines() if x.strip()]
    orgs = json.loads(config.ORGANIZATIONS.read_text(encoding="utf-8"))
    beratungen = [json.loads(x) for x in config.BERATUNGEN.read_text(encoding="utf-8").splitlines() if x.strip()]
    kandidaten, gruende = auswahl(roh, orgs, beratungen, eintraege)
    anlagen = sum(1 for k in kandidaten if k["quelle"] == "auxiliaryFile")
    if anlagen or gruende["ohne_datei"]:
        print(f"Dokumente: {anlagen} Dateien aus auxiliaryFile ausgewählt (ohne mainFile, Entscheidung 13.11.2026 (a)); "
              f"{gruende['ohne_datei']} Verwaltungsvorlagen ohne mainFile und ohne PDF-Datei in auxiliaryFile")
    rest = max(grenze - schon, 0)
    lauf = {"ergebnisse": [], "versucht": 0, "quellen": Counter()}
    ergebnis = f"übersprungen: Obergrenze dieser Nacht erreicht ({schon} von höchstens {grenze})"
    try:
        if rest and kandidaten and not selbsttest():   # vor der ersten Anfrage: ohne heilen Prüfprozess keine
            ergebnis = _uebersprungen("Prüfprozess besteht den Selbsttest an der eingebauten Probedatei nicht (pypdf "
                                      "fehlt, andere Version oder Absturz)", True)
        elif rest:
            ergebnis = _lesen(kandidaten[:rest], nacht, schon, lauf, zeile)
    finally:
        if config.DOKUMENTE.exists():   # angehängte Einträge zusammenführen (je Datei einer, geordnet)
            _schreiben({**eintraege, **{e["file"]: e for e in lauf["ergebnisse"]}})
    return f"{ergebnis}; " + _zusammenfassung(kandidaten, lauf, schon, grenze, gruende)


def _lesen(auswahl_, nacht, schon, lauf, zeile):
    """Dateien nacheinander lesen und prüfen; zählt je Datei vor dem Senden (`dokumente.dateien`, `lauf["versucht"]`).
    Liefert „ok“, „unterbrochen: …“ (Zeitfenster) oder „abbruch: …“."""
    gelesen, ergebnisse = 0, lauf["ergebnisse"]
    for k in auswahl_:
        lauf["versucht"] += 1
        lauf["quellen"][k["quelle"]] += 1
        _eigener_zustand_setzen(nacht=nacht, dateien=schon + lauf["versucht"])
        daten = None
        try:
            daten = abruf.get_datei(k["url"], MAX_BYTES, LESEFRIST)
            e = pruefen(daten)
            # ein gescheiterter Prüfprozess ist kein Ergebnis der Datei: vorläufig (Fehlversuch)
            e.update(sha256=hashlib.sha256(daten).hexdigest(), groesse=len(daten),
                     fehlversuche=k["_fehlversuche"] + 1 if vorlaeufig(e["status"]) else 0)
            gelesen += 1
        except abruf.Abbruch as a:
            status = ("zu_gross" if a.art == "zu_gross" else "adresse" if a.art == "adresse"
                      else "kein_pdf" if a.art == "unlesbar"
                      else f"http_{a.code}" if a.art == "http" and a.code not in sessionnet.SPERRE_HTTP else None)
            leer = {"trefferart": "", "kennung": "", "fehlerart": "", "sha256": "", "groesse": None}
            if status:   # dateibezogene Ergebnisse: so wird die Datei erst nach einer Änderung erneut gelesen
                _vermerken(k, {"status": status, **leer, "fehlversuche": 0}, ergebnisse, zeile)
            elif _abbruch_status(a):   # kann an der Datei liegen: vorläufig, in der nächsten Nacht hinter den anderen
                _vermerken(k, {"status": _abbruch_status(a), **leer, "fehlversuche": k["_fehlversuche"] + 1},
                           ergebnisse, zeile)
            if a.art in ("zu_gross", "adresse"):
                continue
            if a.art == "zeitfenster":
                return f"unterbrochen: Zeitfenster endete ({a})"
            meldung = _abbruch_vermerken(a, abruf.uhr())
            sessionnet._warnung(meldung)
            return f"abbruch: {a}"[:300]
        finally:
            daten = None   # die Datei nur im Arbeitsspeicher, nach der Prüfung verworfen (auch bei einem Fehler)
        _vermerken(k, e, ergebnisse, zeile)
    if gelesen:   # ein Lauf ohne Abbruch mit gelesener Datei setzt die eigene Zählung zurück
        _eigener_zustand_setzen(verdacht=None)
    return "ok"


def _abbruch_status(a):
    """Vorläufiger Status einer Datei nach einem Abbruch, der an ihr liegen kann: HTTP 401/403/429
    (`abbruch_http_<Code>`), Weiterleitung, „aufgegeben“ (nach 429/5xx) und `sperre` (Zeitüberschreitung, Lesefrist,
    abgeschnittene Antwort); None für Abbrüche der Ausführungsumgebung (tls, proxy) und alle übrigen."""
    if a.art == "http" and a.code in sessionnet.SPERRE_HTTP:
        status = f"abbruch_http_{a.code}"
    elif a.art in ("sperre", "aufgegeben", "weiterleitung"):
        status = f"abbruch_{a.art}"
    else:
        return None
    return status if RE_ABBRUCH.fullmatch(status) else None


def _vermerken(k, e, ergebnisse, zeile):
    eintrag = {"file": k["file"], "paper": k["paper"], "quelle": k["quelle"], "zeit": _now(),
               **{m: k[m] for m in MERKMALE},
               **{f: e[f] for f in ("status", "trefferart", "kennung", "fehlerart", "sha256", "groesse",
                                    "fehlversuche")}}
    _anhaengen(eintrag)
    ergebnisse.append(eintrag)
    zeile["objekte"] = len(ergebnisse)
