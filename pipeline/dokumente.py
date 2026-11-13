"""Dokumente (PDF-Köpfe): federführende Dienststelle aus dem Kopf der Verwaltungsvorlagen („Dezernat, Dienststelle“,
CLAUDE.md 5.3). Gebaut und getestet, aber abgeschaltet (Entscheidung des Auftraggebers 13.11.2026): Der Auftraggeber
ruft die Stadt vorher an; ein einmaliger Test mit 100 Köpfen ist einfach die erste Nacht mit RATSATLAS_PDF_MAX=100.

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
kein Fehler.

Obergrenze: höchstens RATSATLAS_PDF_MAX Dateien je Nacht (Vorgabe 300; leer oder nicht gesetzt: 300; 0, negativ oder
unlesbar: keine Anfrage). Gezählt wird jede Datei, für die eine Anfrage beginnt, im Zustand (`dokumente.nacht`,
`dokumente.dateien`; Nacht = 12 Uhr bis 12 Uhr Ortszeit), vor dem Senden: Ein zweiter Lauf in derselben Nacht (Push,
Knopfdruck) liest nur den Rest.

Auswahl (ohne Anfrage, aus papers.jsonl, organizations.json und beratungen.jsonl; fehlt eine der drei Dateien, keine
Anfrage): nur die Hauptdatei (`mainFile`) von
Verwaltungsvorlagen: Drucksache NNNN/JJJJ und Vorlagenart der Verwaltung (actors.VERWALTUNG_TYPES, nicht
actors.EINWOHNER_TYPES, als Zeichenkette geliefert). Nie: Vorlagen ohne Erlaubnis für Hauskoordinaten oder in der
Titelmaske (gesperrt(): dieselben Funktionen und Angaben wie build und check: geocode.punkt_ausschluss mit Eingaben,
Vorlagen natürlicher Personen, Ausschuss für Anregungen und Beschwerden, nicht erkennbare Vorlagenart, maske.py; Fixpunkt
geocode.sperrmenge; Titelmaske maske.kette), nicht öffentliche Beratungen (`public` weder true noch fehlend)
und Sammellisten nichtöffentlicher Punkte. Fehlt `mainFile`, wird nicht unter `auxiliaryFile` geraten: gezählt und im
Log genannt (Entscheidung später; in Köln fehlte `mainFile` in Stufe 1 bei 25 Vorlagen, in Stufe 2 bei keiner der
100 jüngsten). Nur Adressen auf dem Host der OParl-API (config.OPARL_BODY: Schema, Host und Port gleich;
`downloadUrl`, sonst `accessUrl`), nur PDF laut `mimeType` (falls angegeben), höchstens MAX_BYTES laut `size`.
Neueste zuerst (Datum der Vorlage, dann `created`). Schon verarbeitete Dateien (auch mit Fehler) nur erneut, wenn sich
`modified`, `size`, `accessUrl` oder `downloadUrl` der Datei geändert haben.

Verarbeitung: Die Antwort bleibt im Arbeitsspeicher (höchstens MAX_BYTES, Lesefrist LESEFRIST), wird nie auf die Platte
geschrieben und nach der Prüfung verworfen, auch bei einem Fehler. Geprüft wird in einem eigenen Prozess
(pipeline/pdfkopf.py, `python -I`, ohne Umgebungsvariablen außer PATH, Grenzen für Speicher, Rechenzeit, Dateien und
Speicherabzüge, Frist PRUEF_FRIST; nur Seite 1 mit pypdf, keine externen Werkzeuge); er gibt nur Status, Trefferart,
Kennung und den Namen einer Fehlerklasse zurück, nie Text. Gespeichert wird je Datei nur Abgeleitetes in
data/raw/dokumente_koepfe.jsonl (config.DOKUMENTE; im Zwischenspeicher des Workflows wie die übrigen Rohdaten, nicht
im Repository, nicht auf der Seite, nicht im Datenpaket): OParl-Kennung der Datei und der Vorlage, SHA-256, Größe,
Zeitpunkt, Kennung, Trefferart, Status, Fehlerklasse und die Merkmale der Datei zur Erkennung von Änderungen
(`modified`, `size`, `accessUrl`, `downloadUrl` aus den Metadaten). Jeder Eintrag wird vor dem Schreiben und beim Lesen
gegen feste Formen geprüft (FELDER, pdfkopf.KENNUNG_FORM). Log und Abrufstatistik nennen nur Zahlen.

Verwendung: build übernimmt die Kennung als Federführung nur ohne `underDirectionOf`, nur für die aktuelle Hauptdatei
und nur bei Vorlagen mit Erlaubnis für Hauskoordinaten (actors.responsibilities, Methode „pdf_kopf“, Konfidenz
„mittel“ bzw. „niedrig“ nach Trefferart, Fundstelle „Kopf der Vorlage (S. 1): <Kennung>“). Eine versionierte
Ämtertabelle gibt es noch nicht: Die Kennung bleibt keinem Amt zugeordnet und wird als solche gezeigt.
"""
import hashlib
import json
import os
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
LESEFRIST = 120                  # Sekunden für eine ganze Antwort (darüber: mögliche Sperre)
PRUEF_FRIST = 60                 # Sekunden für den Prüfprozess (Wanduhr)
PRUEF_CPU = 30                   # Sekunden Rechenzeit im Prüfprozess
PRUEF_SPEICHER = 1 << 30         # Adressraum des Prüfprozesses (1 GiB)
VERDACHT_NAECHTE = 3
VERDACHT_PAUSE = timedelta(days=7)
SCHLUESSEL = "dokumente"         # Eintrag im Zustand (zustand_abruf.json)
RE_VERWALTUNGSVORLAGE = re.compile(r"^\d{1,4}/\d{4}$")
# Felder eines Eintrags in config.DOKUMENTE; nichts sonst wird geschrieben
FELDER = ("file", "paper", "sha256", "groesse", "zeit", "kennung", "trefferart", "status", "fehlerart", "modified",
          "size", "accessUrl", "downloadUrl")
MERKMALE = ("modified", "size", "accessUrl", "downloadUrl")
# Status je Datei: aus dem Prüfprozess (pdfkopf.STATUS) oder vom Abruf
STATUS = (*pdfkopf.STATUS, "zeitueberschreitung", "fehler_pruefung", "zu_gross", "kein_pdf", "adresse")
RE_HTTP_STATUS = re.compile(r"http_[1-5]\d\d")
RE_SHA256 = re.compile(r"[0-9a-f]{64}")
# Gründe, aus denen eine Vorlage oder Datei nicht ausgewählt wird (Log und Abrufstatistik)
GRUENDE = {
    "drucksache": "Drucksache nicht NNNN/JJJJ", "vorlagenart": "keine Vorlagenart der Verwaltung",
    "ohne_hauskoordinate": "ohne Hauskoordinate oder Titelmaske", "nicht_oeffentlich": "nicht öffentlich beraten",
    "ohne_hauptdatei": "ohne mainFile", "doppelt": "Hauptdatei schon ausgewählt", "kein_pdf": "kein PDF laut mimeType",
    "fremder_host": "Adresse nicht auf dem Host der OParl-API", "zu_gross": f"über {MAX_BYTES // 1_000_000} MB laut size",
    "bekannt": "schon verarbeitet, unverändert",
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


def eintrag_gueltig(e):
    """Hat ein Eintrag genau die erlaubte Form (FELDER, Werte nach festen Mustern)? Was nicht passt, wird weder
    geschrieben noch gelesen: So gelangt kein Text des Dokuments in den Zustand."""
    if not isinstance(e, dict) or set(e) != set(FELDER):
        return False
    if not all(isinstance(e[k], str) and e[k] and len(e[k]) <= 2000 for k in ("file", "paper")):
        return False
    status, art, kennung = e["status"], e["trefferart"], e["kennung"]
    if not (status in STATUS or isinstance(status, str) and RE_HTTP_STATUS.fullmatch(status)):
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


def auswahl(roh, orgs, beratungen, eintraege):
    """Dateien zum Lesen, neueste zuerst, und Zähler der Gründe, aus denen Vorlagen oder Dateien nicht in Frage kommen
    (GRUENDE). `roh`: Vorlagen wie in papers.jsonl; `orgs`: organizations.json; `beratungen`: Zeilen aus
    beratungen.jsonl; `eintraege`: laden()."""
    from . import build   # hier: build importiert dieses Modul
    papers, ausgelassen, _ = build.einlesen(build._je_kennung_einmal(roh))
    orgs_by_id = {o["id"]: o for o in orgs if isinstance(o, dict) and isinstance(o.get("id"), str)}
    sperre = gesperrt(papers, ausgelassen, orgs_by_id)
    oeffentlich = {b.get("uri"): (b.get("agendaItem") or {}).get("public") for b in beratungen
                   if isinstance(b, dict) and isinstance(b.get("agendaItem"), (dict, type(None)))}
    gruende, kandidaten, gesehen = Counter(), [], set()
    for p in papers:
        if not RE_VERWALTUNGSVORLAGE.match(p["reference"]):
            gruende["drucksache"] += 1
        elif not _verwaltungsvorlage(p):
            gruende["vorlagenart"] += 1
        elif p["id"] in sperre:
            gruende["ohne_hauskoordinate"] += 1
        elif _nicht_oeffentlich(p, oeffentlich):
            gruende["nicht_oeffentlich"] += 1
        elif not isinstance(p.get("mainFile"), dict) or not isinstance(p["mainFile"].get("id"), str) \
                or not p["mainFile"]["id"] or p["mainFile"].get("deleted"):
            gruende["ohne_hauptdatei"] += 1
        else:
            f = p["mainFile"]
            mime = f.get("mimeType")
            url = f.get("downloadUrl") or f.get("accessUrl")
            size = f.get("size")
            merkmale = {k: _merkmal(f.get(k)) for k in MERKMALE}
            alt = eintraege.get(f["id"])
            if f["id"] in gesehen:
                gruende["doppelt"] += 1
            elif isinstance(mime, str) and mime.strip() and mime.split(";")[0].strip().lower() != "application/pdf":
                gruende["kein_pdf"] += 1
            elif not auf_oparl_host(url):
                gruende["fremder_host"] += 1
            elif isinstance(size, int) and not isinstance(size, bool) and size > MAX_BYTES:
                gruende["zu_gross"] += 1
            elif alt and all(alt[k] == merkmale[k] for k in MERKMALE):
                gruende["bekannt"] += 1
            else:
                kandidaten.append({"file": f["id"], "paper": p["id"], "url": url, **merkmale,
                                   "_ordnung": (str(p.get("date") or "") if isinstance(p.get("date"), str) else "",
                                                str(p.get("created") or "") if isinstance(p.get("created"), str) else "",
                                                p["id"])})
            gesehen.add(f["id"])
    kandidaten.sort(key=lambda k: k["_ordnung"], reverse=True)
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

def _zusammenfassung(kandidaten, versucht, schon, grenze, ergebnisse, gruende):
    arten = Counter(e["trefferart"] for e in ergebnisse if e["status"] == "ok")
    erkannt = sum(arten[a] for a in pdfkopf.MIT_KENNUNG)
    fehler = Counter(e["status"] for e in ergebnisse if e["status"] != "ok")
    teile = [f"Auswahl {len(kandidaten)} Dateien (neu oder geändert), in diesem Lauf {versucht} (in dieser Nacht "
             f"{schon + versucht} von höchstens {grenze})",
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
    if gruende["ohne_hauptdatei"]:
        sessionnet._warnung(f"Dokumente: {gruende['ohne_hauptdatei']} Verwaltungsvorlagen ohne mainFile; nicht unter "
                            "auxiliaryFile geraten (Entscheidung offen)")
    rest = max(grenze - schon, 0)
    lauf = {"ergebnisse": [], "versucht": 0}
    ergebnis = f"übersprungen: Obergrenze dieser Nacht erreicht ({schon} von höchstens {grenze})"
    try:
        if rest:
            ergebnis = _lesen(kandidaten[:rest], nacht, schon, lauf, zeile)
    finally:
        if config.DOKUMENTE.exists():   # angehängte Einträge zusammenführen (je Datei einer, geordnet)
            _schreiben({**eintraege, **{e["file"]: e for e in lauf["ergebnisse"]}})
    return f"{ergebnis}; " + _zusammenfassung(kandidaten, lauf["versucht"], schon, grenze, lauf["ergebnisse"], gruende)


def _lesen(auswahl_, nacht, schon, lauf, zeile):
    """Dateien nacheinander lesen und prüfen; zählt je Datei vor dem Senden (`dokumente.dateien`, `lauf["versucht"]`).
    Liefert „ok“, „unterbrochen: …“ (Zeitfenster) oder „abbruch: …“."""
    gelesen, ergebnisse = 0, lauf["ergebnisse"]
    for k in auswahl_:
        lauf["versucht"] += 1
        _eigener_zustand_setzen(nacht=nacht, dateien=schon + lauf["versucht"])
        daten = None
        try:
            daten = abruf.get_datei(k["url"], MAX_BYTES, LESEFRIST)
            e = pruefen(daten)
            e.update(sha256=hashlib.sha256(daten).hexdigest(), groesse=len(daten))
            gelesen += 1
        except abruf.Abbruch as a:
            status = ("zu_gross" if a.art == "zu_gross" else "adresse" if a.art == "adresse"
                      else "kein_pdf" if a.art == "unlesbar"
                      else f"http_{a.code}" if a.art == "http" and a.code not in sessionnet.SPERRE_HTTP else None)
            if status:   # nur dateibezogene Ergebnisse: so wird die Datei erst nach einer Änderung erneut gelesen
                _vermerken(k, {"status": status, "trefferart": "", "kennung": "", "fehlerart": "", "sha256": "",
                               "groesse": None}, ergebnisse, zeile)
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


def _vermerken(k, e, ergebnisse, zeile):
    eintrag = {"file": k["file"], "paper": k["paper"], "zeit": _now(), **{m: k[m] for m in MERKMALE},
               **{f: e[f] for f in ("status", "trefferart", "kennung", "fehlerart", "sha256", "groesse")}}
    _anhaengen(eintrag)
    ergebnisse.append(eintrag)
    zeile["objekte"] = len(ergebnisse)
