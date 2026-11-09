"""Messung der Kölner OParl-API (Phase 1) – nur gestuft nach explore/STUFEN.md, jede Stufe erst nach Freigabe.

Aufruf (Reihenfolge und genaue Befehle mit Obergrenzen: explore/STUFEN.md):
  ... python3 explore/oparl_messung.py test        (genau 3 Anfragen: System, Body, erste Seite der Vorlagen)
  ... python3 explore/oparl_messung.py kennzahlen  (10 Anfragen)
  ... python3 explore/oparl_messung.py organisationen [--seiten 4]
  ... python3 explore/oparl_messung.py filtertest  (genau 1 Anfrage; Body nur aus dem Cache)
  ... python3 explore/oparl_messung.py stichprobe [--seiten 1] [--von 2019] [--bis 2026] [--limit 100]
  ... python3 explore/oparl_messung.py sitzungen [--seiten 2]
  ... python3 explore/oparl_messung.py pdf-koepfe [--anzahl 100]
Jede Liste hat eine Seitengrenze (--seiten, Vorgabe je Kommando; 0 = ohne Grenze, nur ausdrücklich).
Ohne RATSATLAS_STADT_INFORMIERT=ja bricht jedes Kommando vor der ersten Anfrage an die Stadt ab (Entscheidung
04.11.2026); lokale Testserver (http://127.0.0.1, http://localhost) sind ausgenommen (explore/testserver.py).
Anfragen an die Stadt nur im Zeitfenster 23–1 Uhr Ortszeit (RATSATLAS_ZEITFENSTER, wie pipeline/abruf.py), geprüft vor
jeder Anfrage und nach dem Warten auf den Abstand noch einmal unmittelbar vor dem Senden. `pdf-koepfe` lädt PDFs und
läuft zusätzlich nur mit RATSATLAS_PDF_FREIGEGEBEN=ja (laut mandari ist der automatische PDF-Abruf mit Köln so nicht
vereinbart; Frage in der Anfrage an die Stadt).
Für Anfragen an die Stadt gelten strenge Vorgaben (sichere_vorgaben): keine Wiederholung nach 429/5xx
(RATSATLAS_WIEDERHOLUNGEN, Vorgabe 0), höchstens 5 s je Antwort (RATSATLAS_MAX_DAUER, Vorgabe 5), mindestens 2 s Abstand
zwischen zwei Anfragen (RATSATLAS_ABSTAND, Vorgabe 2); RATSATLAS_MAX_ANFRAGEN und RATSATLAS_KONTAKT (ohne Platzhalter)
sind Pflicht. Lockerere Werte werden vor der ersten Anfrage abgelehnt.
Parameter werden URL-kodiert angehängt (`quote(wert, safe="")`): Köln übergeht Zeitwerte unkodiert und wendet sie
kodiert an (Stufe 2, 08.11.2026; die frühere Annahme „ohne URL-Kodierung, SessionNet: 404 bei %3A/%2B“ gilt für Köln
nicht). links.next gibt die Werte unkodiert zurück und wird vor dem Folgen normalisiert (_folgeadresse, wie
pipeline/sessionnet.folgeadresse: Query-Teil je Parameter mit quote(unquote(v), safe="") neu aufgebaut, ein fehlendes
limit ergänzt, ein anderer Host als der der Liste nicht gesendet, Art `adresse`). Ausnahme `kennzahlen` (Stufe 2,
abgeschlossen): dieselben Adressen wie in der Messung (Zeitwerte unkodiert und einmal kodiert im Vergleich), damit
die Ergebnisse nachvollziehbar bleiben.
`filtertest` (Stufe 3) stellt genau eine Anfrage: die Vorlagenliste mit kodiertem created_since/created_until für zwei
Werktage in 2025 und limit=100; den Body liest es nur aus dem Cache (fehlt er, Abbruch vor der Anfrage, Art
`voraussetzung`). Ergebnis in ergebnisse/oparl_filtertest.tsv.
`kennzahlen` beurteilt die Zeitfilter ohne weitere Anfrage aus dem Vergleich mit der ungefilterten ersten Seite
(_filter_urteil): Die Grenze für modified_since ist der Median von `modified` der ersten Hälfte dieser Seite, so dass
ein Server, der den Filter überginge, ältere Vorlagen liefern müsste; „ja“ nur, wenn die gefilterte Antwort keine
Vorlage unter der Grenze enthält, die ungefilterte Seite nachweislich nach created sortiert ist (neueste zuerst wie
Köln oder älteste zuerst; sonst „nicht unterscheidbar (Reihenfolge unbekannt …)“) und mindestens zwei Vorlagen, die
dort unter der Grenze lagen, alle in ihr fehlen (sind sie seither geändert, „nicht unterscheidbar“); bei „nein“ steht
dabei, wie weit die früheste Vorlage der Antwort vor der Grenze liegt; Objekte der Antwort mit unlesbarem Wert stehen
getrennt am Ende („; k mit unlesbarem modified“). Bei neueste zuerst zeigt die erste Seite, ob
created_until wirkt, nicht aber, ob created_since wirkt („nicht unterscheidbar“). limit=100 ist die letzte Anfrage
(eine langsame Antwort bricht ab, wenn die übrigen Messungen vorliegen). Eine 401 auf einen Parametertest gilt als
„Parameter abgelehnt“, zwei 401 in Folge brechen ab (abgelehnt oder Sperre?).
Abruf über explore/abruf.py (eine Verbindung, Abstand ≥ 2 s nach Ende der Antwort, auch vor der ersten Anfrage
eines Prozesses, Cache, Protokoll, Obergrenze RATSATLAS_MAX_ANFRAGEN, Weiterleitungen werden nicht verfolgt).
Paginierung nur über links.next, nie über konstruierte Seitennummern (HTTP 401 bei hohen Seitenzahlen); Schutz vor
Schleifen: Abbruch bei wiederholter Folgeadresse und bei einer Seite ohne neue Kennungen.
`stichprobe` bricht ab, sobald der Jahresfilter erkennbar nicht wirkt (created außerhalb des Jahres oder dieselbe
Vorlage in einem anderen Jahr), damit keine weiteren Jahreslisten abgerufen werden.
Jeder Lauf wird in ergebnisse/oparl_laeufe.tsv vermerkt (Stufe aus RATSATLAS_STUFE, Zeilen in _cache/abrufe.tsv),
jede durchlaufene Liste in ergebnisse/oparl_listen.tsv. Bei einem Abbruch endet der Lauf mit Rückgabewert 2. Lehnt der
Proxy der Arbeitsumgebung die Verbindung ab (Art `proxy`: CONNECT-Antwort 403/405/407 oder HTTP 407), hat keine
Anfrage die Stadt erreicht: nicht wiederholen, sondern berichten; der Host muss im Netz der Arbeitsumgebung erlaubt
sein (explore/STUFEN.md, Stufe 1). Meldet der Proxy 502/504 (Stadt nicht erreicht, beim Verbindungsaufbau oder als
Antwort im Tunnel) oder ist eine Antwort abgeschnitten oder unlesbar, gilt das als mögliche Sperre (Art `sperre`),
429/503 als Art `server`. Scheitert die Zertifikatsprüfung (Art `tls`), ist das vermutlich eine Einstellung der
Arbeitsumgebung (CA des Proxys; Zertifikat der Gegenseite oder Sperrseite nicht ausgeschlossen); der Lauf bricht ab.
Nach einem Abbruch gilt: in dieser Nacht keine weitere Anfrage (STUFEN.md). Vor der ersten Anfrage an eine nicht
lokale Adresse prüft main() deshalb oparl_laeufe.tsv: Endete der letzte Lauf vor weniger als 12 Stunden mit
„abbruch (…)“, „fehler (…)“ oder „unterbrochen“ (Strg+C, SIGTERM etwa nach dem Zeitlimit des aufrufenden Werkzeugs,
SIGHUP, wenn nicht ignoriert wie mit nohup; alle enden wie Strg+C, ein zweites Signal danach wird ignoriert; ein Lauf
gilt als „unterbrochen“, bis er regulär endet), bricht das Kommando ohne Anfrage ab (Rückgabewert 1). Ebenso nach
einem hart beendeten Lauf (SIGKILL, Absturz): Vor der ersten Anfrage an die Stadt legt main() die Markerdatei
_cache/lauf_offen.json an und entfernt sie erst nach dem Vermerk; liegt sie ohne Vermerk und ist der Lauf jünger als 12
Stunden oder unlesbar, gilt er als „nicht regulär beendet“ (ein unlesbarer bis zur Rücksprache); ein älterer Marker
wird gemeldet und entfernt. Weiter nur nach Rücksprache mit dem Auftraggeber: RATSATLAS_NACH_ABBRUCH=ja (der Marker
wird dann überschrieben). Ein entfernter oder überschriebener Marker ohne Vermerk wird als Zeile „nicht regulär
beendet (Marker)“ in oparl_laeufe.tsv nachgetragen (Anfragenzahl unbekannt), ohne die 12-Stunden-Regel erneut
auszulösen. Ein zweiter gleichzeitiger Prozess (auch mit anderem
Cache oder aus einer anderen Arbeitskopie) bricht vor seiner ersten Anfrage ab (Art `parallel`, Sperre
~/.cache/ratsatlas-koeln/abruf.lock in explore/abruf.py, Ort über RATSATLAS_SPERRE). Eine Antwort, die kein JSON ist,
wird aus dem Cache entfernt, auch in Listen und Parametertests (ein späterer Lauf fragt erneut, statt sie ohne Anfrage
zu lesen).
Ergebnisse als TSV unter explore/ergebnisse/; Rohdaten, PDFs und die Stichprobendatei für `pdf-koepfe`
(_cache/stichprobe_vorlagen.jsonl: nur id, reference, paperType, date, Adresse der Hauptdatei) bleiben im Cache
(nicht im Repository).
Aus PDFs werden nur abgeleitete Kennungen (Dezernat/Dienststelle) und Trefferarten gespeichert, keine Textauszüge.
"""
import argparse
import collections
import csv
import datetime as dt
import io
import json
import math
import os
import re
import signal
import sys
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import abruf  # noqa: E402
from abruf import Abbruch, hole  # noqa: E402

SYSTEM = os.environ.get("RATSATLAS_OPARL_SYSTEM", "https://buergerinfo.stadt-koeln.de/oparl/system")
BODY = os.environ.get("RATSATLAS_OPARL_BODY", "https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
ERG = Path(os.environ.get("RATSATLAS_ERGEBNISSE", Path(__file__).resolve().parent / "ergebnisse"))
# Seitengrenze je Kommando, wenn --seiten fehlt (stichprobe: je Jahr; sonst insgesamt)
SEITEN_VORGABE = {"stichprobe": 1, "organisationen": 4, "sitzungen": 2}
# Objekte je Seite für stichprobe (Köln, Stufe 2: limit=100 wirkt, rund 5 s je Antwort)
LIMIT_VORGABE = 100
# filtertest: zwei Werktage (Dienstag und Mittwoch, 3. und 4. Juni 2025; kein Feiertag und keine Schulferien in NRW),
# so eng, dass Köln (Stufe 1: 25 Vorlagen aus vier Tagen) dort deutlich weniger als 100 Vorlagen haben dürfte: Wirken
# beide Grenzen, ist die Seite nicht voll und das Ende der Liste sichtbar; wirkt created_since nicht, füllen ältere
# Vorlagen die Seite (vor der Untergrenze); wirkt created_until nicht, kommen die jüngsten Vorlagen (nach der
# Obergrenze, Köln liefert neueste zuerst). Ortszeit mit Zone, kodiert gesendet
FENSTER = ("2025-06-03T00:00:00+02:00", "2025-06-04T23:59:59+02:00")
FILTERTEST_LIMIT = 100
# Antworten, die in den Parametertests von `kennzahlen` als „Parameter abgelehnt“ gelten (kein Abbruch)
ABGELEHNT = (400, 401, 404)
# strenge Vorgaben für Anfragen an die Stadt (explore/STUFEN.md, Abbruchkriterien)
STRENG_DAUER = 5.0
STRENG_ABSTAND = 2.0   # Sekunden vom Ende einer Antwort bis zur nächsten Anfrage (CLAUDE.md 5.1)
# nach einem Abbruch oder Fehler keine weitere Anfrage an die Stadt in dieser Frist (STUFEN.md: „in dieser Nacht keine
# weitere Anfrage und keine weitere Stufe“); Freigabe nur nach Rücksprache mit RATSATLAS_NACH_ABBRUCH=ja
SPERRFRIST = dt.timedelta(hours=12)
# Ergebnisse, nach denen die Sperrfrist gilt: Abbruch, Fehler und ein unterbrochener Lauf (Strg+C, Signal oder ein Ende
# ohne regulären Abschluss)
RE_ABBRUCH = re.compile(r"^(?:(?:abbruch|fehler) \(|unterbrochen\b)")
UNTERBROCHEN = "unterbrochen"
# Signale, die einen Lauf wie Strg+C beenden (Vermerk „unterbrochen“ statt eines Endes ohne Vermerk): SIGTERM etwa nach
# dem Zeitlimit des aufrufenden Werkzeugs, SIGHUP beim Schließen des Terminals (nur, wenn nicht ignoriert wie mit nohup).
# SIGKILL lässt sich nicht abfangen.
SIGNALE = (signal.SIGTERM, signal.SIGHUP)
# fehlende Gesamtzahlen (Köln, Stufe 1: pagination nur mit elementsPerPage und currentPage)
FEHLT = "fehlt"
# Markerdatei eines laufenden Laufs an die Stadt neben _cache/abrufe.tsv (gitignoriert): angelegt vor der ersten Anfrage,
# entfernt am regulären Ende (auch nach einem Abbruch mit Vermerk). Bleibt sie nach einer harten Beendigung liegen
# (SIGKILL, Absturz der Arbeitsumgebung: kein Vermerk in oparl_laeufe.tsv), gilt der Lauf als „nicht regulär beendet“.
MARKER = "lauf_offen.json"
NICHT_REGULAER = "nicht regulär beendet"
# Vermerk für einen hart beendeten Lauf, dessen Marker entfernt oder überschrieben wird (löst die Sperrfrist nicht aus)
NICHT_REGULAER_MARKER = "nicht regulär beendet (Marker)"
# Stichprobe für pdf-koepfe: nur im Cache (nicht im Repository), ohne File-Objekte
STICHPROBE = abruf.CACHE / "stichprobe_vorlagen.jsonl"

RE_AN = re.compile(r"^AN/\d{1,4}/\d{4}$")
RE_VV = re.compile(r"^\d{1,4}/\d{4}$")
# Kopf der Verwaltungsvorlagen: „Dezernat, Dienststelle“ gefolgt von einer Kennung wie „II/II/2“ oder „VI/61“
RE_DEZ = re.compile(r"Dezernat\s*,\s*Dienststelle\s*[:\s]*([IVX]+(?:\s*/\s*[0-9IVX]+){0,3}(?:\s*/\s*\d+)?)")
RE_DEZ_LOSE = re.compile(r"Dezernat\s*,?\s*Dienststelle", re.I)

_LISTEN = []   # je durchlaufener Liste ein Eintrag für oparl_listen.tsv


def lokal(url):
    t = urllib.parse.urlsplit(url)
    return t.scheme == "http" and t.hostname in ("127.0.0.1", "localhost")


def im_zeitfenster(jetzt=None):
    fenster = os.environ.get("RATSATLAS_ZEITFENSTER", "23-1").strip()
    if not fenster:
        return True
    von, bis = (int(x) for x in fenster.split("-"))
    h = (jetzt or dt.datetime.now(ZoneInfo("Europe/Berlin"))).hour
    return von <= h < bis if von < bis else (h >= von or h < bis)


def sichere_vorgaben(umgebung=None):
    """Strenge Vorgaben für Anfragen an die Stadt; liefert (werte, fehler). Fehlende Werte werden gesetzt
    (Wiederholungen 0, höchstens 5 s je Antwort, 2 s Abstand), lockerere abgelehnt; Obergrenze und Kontakt sind
    Pflicht."""
    env = os.environ if umgebung is None else umgebung
    fehler = []
    try:
        wiederholungen = int(env.get("RATSATLAS_WIEDERHOLUNGEN") or "0")
        max_dauer = float(env.get("RATSATLAS_MAX_DAUER") or STRENG_DAUER)
        max_anfragen = int(env.get("RATSATLAS_MAX_ANFRAGEN") or "0")
        abstand = float(env.get("RATSATLAS_ABSTAND") or STRENG_ABSTAND)
    except ValueError as e:
        return {}, [f"unlesbarer Wert ({e})"]
    if wiederholungen != 0:
        fehler.append("RATSATLAS_WIEDERHOLUNGEN muss 0 sein (keine Wiederholung nach 429/5xx)")
    if not 0 < max_dauer <= STRENG_DAUER:
        fehler.append(f"RATSATLAS_MAX_DAUER muss größer als 0 und höchstens {STRENG_DAUER:g} s sein")
    if not (math.isfinite(abstand) and abstand >= STRENG_ABSTAND):
        fehler.append(f"RATSATLAS_ABSTAND muss mindestens {STRENG_ABSTAND:g} s sein (Abstand zwischen zwei Anfragen)")
    if max_anfragen <= 0:
        fehler.append("RATSATLAS_MAX_ANFRAGEN fehlt (Obergrenze der Stufe laut explore/STUFEN.md)")
    kontakt = (env.get("RATSATLAS_KONTAKT") or "").strip()
    if not kontakt or "<" in kontakt or ">" in kontakt:
        fehler.append("RATSATLAS_KONTAKT fehlt oder enthält noch den Platzhalter „<…>“")
    return {"wiederholungen": wiederholungen, "max_dauer": max_dauer, "max_anfragen": max_anfragen,
            "abstand": abstand}, fehler


def _streng_aktiv():
    """Gelten in explore/abruf.py die strengen Vorgaben? (Prüfung vor jeder Anfrage an die Stadt)"""
    return (abruf.WIEDERHOLUNGEN == 0 and 0 < abruf.MAX_DAUER <= STRENG_DAUER and abruf.MAX_ANFRAGEN > 0
            and abruf.ABSTAND >= STRENG_ABSTAND
            and bool(abruf.KONTAKT.strip()) and "<" not in abruf.KONTAKT and ">" not in abruf.KONTAKT)


def _hole(url, endung=".json"):
    """Sperre, Zeitfenster, strenge Vorgaben und PDF-Freigabe vor jeder Anfrage an die Stadt; lokale Testserver
    ausgenommen. Das Zeitfenster prüft hole() nach dem Warten auf den Abstand unmittelbar vor dem Senden noch einmal
    (`vor_dem_senden`)."""
    def fenster():
        if not im_zeitfenster():
            raise Abbruch(f"außerhalb des Zeitfensters (RATSATLAS_ZEITFENSTER): {url}", "zeitfenster")
    if lokal(url):
        return hole(url, endung)
    if os.environ.get("RATSATLAS_STADT_INFORMIERT") != "ja":
        raise Abbruch(f"Die Stadt Köln ist nicht informiert (RATSATLAS_STADT_INFORMIERT): {url}", "gesperrt")
    fenster()
    if not _streng_aktiv():
        raise Abbruch(f"strenge Vorgaben nicht aktiv (Wiederholungen 0, höchstens {STRENG_DAUER:g} s, Abstand "
                      f"mindestens {STRENG_ABSTAND:g} s, Obergrenze, Kontakt): {url}", "gesperrt")
    if endung == ".pdf" and os.environ.get("RATSATLAS_PDF_FREIGEGEBEN") != "ja":
        raise Abbruch(f"PDF-Abruf nicht freigegeben (RATSATLAS_PDF_FREIGEGEBEN): {url}", "gesperrt")
    return hole(url, endung, vor_dem_senden=fenster)


def _mit_parametern(url, kodiert=True, **params):
    """Hängt Parameter an, Werte URL-kodiert (quote(wert, safe=""), wie pipeline/sessionnet.py; Köln wendet Zeitwerte
    nur so an, Stufe 2). `kodiert=False` nur für kennzahlen (Stufe 2, abgeschlossen: dieselben Adressen wie in der
    Messung)."""
    if params:
        url += ("&" if "?" in url else "?") + "&".join(
            f"{k}={urllib.parse.quote(str(v), safe='') if kodiert else v}" for k, v in params.items())
    return url


def _port(teile):
    """Port einer zerlegten Adresse wie pipeline/sessionnet._port: der ausdrückliche Standardport (http 80, https 443)
    gilt wie keine Angabe (None). Ein unlesbarer Port: ValueError."""
    port = teile.port
    return None if (teile.scheme, port) in (("http", 80), ("https", 443)) else port


def _folgeadresse(naechste, liste_url, limit=None):
    """links.next vor dem Folgen normalisieren (wie pipeline/sessionnet.folgeadresse): Schema, Host und Pfad bleiben,
    der Query-Teil wird je Parameter als quote(unquote(v), safe="") neu aufgebaut (unquote, nicht unquote_plus: Köln
    liefert „+“ als wörtliches Plus); idempotent, Reihenfolge, page und limit unverändert. Trägt die erste Adresse
    `limit`, links.next aber nicht, wird er angehängt. Anderer Host, anderer Port oder anderes Schema als die Liste
    (der ausdrückliche Standardport, http …:80, https …:443, gilt wie keine Angabe), Zeichen außerhalb von ASCII (ein
    Umlaut im Host ginge per IDNA an einen anderen Host) oder unlesbar (ValueError, etwa „http://[::1“ oder ein Port
    über 65535): Abbruch der Art `adresse` (nicht gesendet)."""
    if not naechste.isascii():
        raise Abbruch(f"links.next enthält Zeichen außerhalb von ASCII, nicht gesendet: {naechste}", "adresse")
    try:
        teile, liste = urllib.parse.urlsplit(naechste), urllib.parse.urlsplit(liste_url)
        anders = (teile.scheme, teile.hostname, _port(teile)) != (liste.scheme, liste.hostname, _port(liste))
    except ValueError as e:
        raise Abbruch(f"links.next unlesbar ({e}), nicht gesendet: {naechste}", "adresse") from e
    if anders:
        raise Abbruch(f"links.next zeigt auf einen anderen Host als die Liste, nicht gesendet: {naechste}", "adresse")
    neu = []
    for teil in teile.query.split("&") if teile.query else []:
        k, gleich, v = teil.partition("=")
        neu.append(f"{k}={urllib.parse.quote(urllib.parse.unquote(v), safe='')}" if gleich else teil)
    if limit and not any(x.partition("=")[0] == "limit" for x in neu):
        neu.append(f"limit={limit}")
    return urllib.parse.urlunsplit(teile._replace(query="&".join(neu)))


def _json_von(adresse, lesen=None):
    """JSON der Antwort (`lesen`: Ersatz für den Abruf, z. B. aus dem Cache); eine unlesbare Antwort bleibt nicht im Cache
    (ein späterer Lauf würde sie ohne Anfrage lesen)."""
    try:
        return json.loads(lesen() if lesen else _hole(adresse))
    except ValueError:
        abruf._cachepfad(adresse, ".json").unlink(missing_ok=True)
        raise


def _json(url, **params):
    return _json_von(_mit_parametern(url, **params))


def _wert(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _schreibe(name, zeilen):
    ERG.mkdir(parents=True, exist_ok=True)
    spalten = list(dict.fromkeys(k for z in zeilen for k in z))
    with (ERG / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, spalten, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for z in zeilen:
            w.writerow({k: str(v).replace("\t", " ").replace("\n", " ") for k, v in z.items()})
    print(f"→ {ERG / name} ({len(zeilen)} Zeilen)")


def _anhaengen(name, spalten, zeilen):
    ERG.mkdir(parents=True, exist_ok=True)
    datei = ERG / name
    neu = not datei.exists()
    with datei.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, spalten, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        if neu:
            w.writeheader()
        for z in zeilen:
            w.writerow({k: str(z.get(k, "")).replace("\t", " ").replace("\n", " ") for k in spalten})


def _seiten(url, max_seiten=None, name="", **params):
    """Folgt links.next (normalisiert, _folgeadresse) und liefert (seite_nr, antwort). Endet am Ende der Liste, an der
    Seitengrenze, bei einer schon besuchten (normalisierten) Folgeadresse oder bei einer Seite ohne neue Kennungen
    (Schleifenschutz wie pipeline/sessionnet.py). Das Ende wird in _LISTEN vermerkt („abgebrochen“, solange es nicht
    erreicht ist); `erstes_next` steht dort so, wie Köln es liefert."""
    start = _mit_parametern(url, **params)
    eintrag = {"liste": name, "url": start, "grenze": max_seiten or "", "seiten": 0, "objekte": 0,
               "ende": "abgebrochen", "erstes_next": ""}
    _LISTEN.append(eintrag)
    besucht, kennungen = {start}, set()
    seite, nr = _json_von(start), 1
    while True:
        ids = {o.get("id") for o in seite.get("data") or [] if isinstance(o, dict)}
        if nr > 1 and not ids - kennungen:
            eintrag["ende"] = "Seite ohne neue Kennungen"
            return
        kennungen |= ids
        eintrag["seiten"], eintrag["objekte"] = nr, len(kennungen)
        yield nr, seite
        nxt = (seite.get("links") or {}).get("next")
        if nxt and not eintrag["erstes_next"]:
            eintrag["erstes_next"] = nxt
        if not nxt:
            eintrag["ende"] = "Ende der Liste (kein links.next)"
            return
        if max_seiten and nr >= max_seiten:
            eintrag["ende"] = f"Seitengrenze {max_seiten}"
            return
        nxt = _folgeadresse(nxt, url, params.get("limit"))
        if nxt in besucht:
            eintrag["ende"] = "links.next wiederholt"
            return
        besucht.add(nxt)
        seite, nr = _json_von(nxt), nr + 1


def _angabe(pag, schluessel):
    """Wert aus `pagination`; fehlt er oder ist er null (Köln: keine Gesamtzahlen), „fehlt“ statt None."""
    wert = (pag if isinstance(pag, dict) else {}).get(schluessel)
    return FEHLT if wert is None else wert


def _liste_kennwerte(objekt, antwort):
    pag, links = antwort.get("pagination") or {}, antwort.get("links") or {}
    zeilen = [{"objekt": objekt, "feld": f"pagination.{k}", "wert": _angabe(pag, k)}
              for k in ("totalElements", "elementsPerPage", "currentPage", "totalPages")]
    return zeilen + [
        {"objekt": objekt, "feld": "objekte_erste_seite", "wert": len(antwort.get("data") or [])},
        {"objekt": objekt, "feld": "pagination.schluessel", "wert": ",".join(sorted(pag))},
        {"objekt": objekt, "feld": "links.schluessel", "wert": ",".join(sorted(links))},
        {"objekt": objekt, "feld": "links.next", "wert": links.get("next") or ""}]


def test(_):
    """Erster Kontakt mit höchstens drei Anfragen: Erreichbarkeit, Antwortzeit, Seitengröße, Form von links.next."""
    zeilen = []
    try:
        system = _json(SYSTEM)
        zeilen.append({"objekt": "system", "feld": "id", "wert": system.get("id")})
        zeilen += [{"objekt": "system", "feld": k, "wert": _wert(system.get(k))[:200]}
                   for k in ("oparlVersion", "vendor", "product", "license")]
        body = _json(BODY)
        zeilen.append({"objekt": "body", "feld": "id", "wert": body.get("id")})
        zeilen += [{"objekt": "body", "feld": k, "wert": _wert(body.get(k))[:200]}
                   for k in ("name", "license", "paper", "modified")]
        if body.get("paper"):
            s = _json(body["paper"])
            zeilen += _liste_kennwerte("paper", s)
            zeilen.append({"objekt": "paper", "feld": "felder_erstes_objekt",
                           "wert": ",".join(sorted((s.get("data") or [{}])[0].keys()))})
    except Abbruch as e:
        zeilen.append({"objekt": "lauf", "feld": "abbruch", "wert": str(e)})
        raise
    finally:
        _schreibe("oparl_test.tsv", zeilen)


def _zeitpunkt(wert):
    """ISO-Zeitpunkt; ohne Zeitzone gilt Ortszeit Köln; unlesbar → None."""
    try:
        t = dt.datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=ZoneInfo("Europe/Berlin"))


def _utc(t):
    """Zeitpunkt in UTC, sekundengenau, mit „+00:00“ (wie pipeline/sessionnet.py; in kennzahlen unkodiert angehängt)."""
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _neueste_zuerst(objekte, umgekehrt=False):
    """Ist die Seite nach `created` absteigend sortiert (Köln, Stufe 1)? Dann stehen neue Vorlagen vorn. `umgekehrt`:
    aufsteigend (älteste zuerst, Form „bisher“ des Testservers)."""
    zeiten = [_zeitpunkt(o["created"]) if o.get("created") else None for o in objekte]
    if umgekehrt:
        zeiten.reverse()
    return (len(zeiten) >= 2 and None not in zeiten and zeiten[0] > zeiten[-1]
            and all(a >= b for a, b in zip(zeiten, zeiten[1:])))


def _grenze_modified(basis):
    """(Grenze für modified_since, Herkunft) aus der ungefilterten ersten Seite: Median von `modified` ihrer ersten
    Hälfte (bei neueste zuerst die Vorlagen, die auch nach einigen neuen Vorlagen seit Stufe 1 noch auf der ersten Seite
    stehen). Ein Server, der den Filter überginge, müsste dann Vorlagen mit älterem `modified` liefern. Ohne lesbares
    `modified`: vor 7 Tagen."""
    kopf = basis[:max(1, (len(basis) + 1) // 2)]
    zeiten = sorted(t for t in (_zeitpunkt(o["modified"]) for o in kopf if o.get("modified")) if t)
    if not zeiten:
        return _utc(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)), "vor 7 Tagen (kein lesbares modified)"
    return _utc(zeiten[len(zeiten) // 2]), (f"Median von modified der ersten {len(kopf)} Vorlagen der ungefilterten "
                                            "ersten Seite")


def _dauer_text(abstand):
    """Zeitabstand lesbar: Sekunden, Minuten, Stunden (bis 2 Tage), sonst Tage mit einer Nachkommastelle."""
    s = int(abs(abstand.total_seconds()))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 2 * 86400:
        h, m = divmod(s // 60, 60)
        return f"{h} h" + (f" {m} min" if m else "")
    return f"{s / 86400:.1f} Tage".replace(".", ",")


def _filter_urteil(basis, antwort, feld, von=None, bis=None):
    """Urteil je Grenze eines Zeitfilters ({"von": …, "bis": …}) aus der gefilterten ersten Seite `antwort` und der
    ungefilterten ersten Seite `basis`, ohne weitere Anfrage:
    - „nein“: Die Antwort enthält Objekte jenseits der Grenze; dazu Anzahl und wie weit das äußerste davon jenseits
      liegt („frühestes modified 1 h vor der Grenze“: um 1 h deutet auf einen Versatz, etwa „+“ als Leerzeichen und
      damit Ortszeit, bis 24 h auf Tagesgenauigkeit, mehr auf einen übergangenen Filter).
    - „ja“ bei „bis“: Die ungefilterte Seite enthält Objekte jenseits der Grenze (die die übrige Grenze einhalten),
      deren Kennung in der Antwort fehlt (neue Vorlagen lägen ohne Filter ebenfalls jenseits).
    - „ja (k fehlen)“ bei „von“ (etwa modified_since): Die Antwort enthält kein Objekt mit lesbarem Wert unter der
      Grenze, die ungefilterte Seite ist nachweislich nach `created` sortiert, neueste zuerst wie Köln (_neueste_zuerst)
      oder älteste zuerst (dort rücken neue Vorlagen nur hinten an; sonst „nicht unterscheidbar (Reihenfolge unbekannt
      …)“: Bei einer Seite etwa nach `modified` verdrängten seither geänderte Vorlagen auch ohne Filter die älteren),
      und sie enthält mindestens zwei Objekte unter der Grenze, die alle in der Antwort fehlen. Begründung: Ein Server
      ohne Filter lieferte dieselbe Liste wie die ungefilterte Seite, nur später. Dass dort genau die Vorlagen unter der
      Grenze fehlen und keine Vorlage unter der Grenze nachrückt, verlangte ohne Filter, dass genau diese Vorlagen
      gelöscht wurden und die Ersatzvorlagen aus Seite 2 durchweg nach der Grenze geändert sind. Mit Filter ist das der
      Normalfall, auch bei voller gefilterter Seite: Ältere, kürzlich geänderte Vorlagen füllen sie (Stufe 2: 25
      ungefiltert, davon 17 unter der Grenze; gefiltert keine darunter, 17 fehlen, 17 ältere geänderte). Der Vergleich
      mit der Zahl älterer fremder Vorlagen (bis Runde 14) machte „ja“ dann unerreichbar; eine einzelne fehlende Vorlage
      (Löschung und neue Vorlage) genügt dagegen nicht mehr. Bei neueste zuerst zählen nur die ersten Plätze, die neue
      Vorlagen seit der ungefilterten Seite (Kennungen dort nicht enthalten, created nicht älter als ihre jüngste
      Vorlage oder unlesbar) nicht verdrängt haben können (ein Server ohne Filter lieferte eine ebenso lange Seite).
    - sonst „nicht unterscheidbar“ mit Grund: keine bzw. nur eine Vorlage unter der Grenze auf der ungefilterten Seite,
      nur ein Teil davon fehlt (die übrigen stehen seither geändert in der Antwort), oder es fehlt keine (etwa alle
      modified gleich oder alle seither geändert: auch ein Server ohne Filter lieferte dieselben Kennungen; bei neueste
      zuerst created_since), dann mit dem Vergleich der Kennungen.
    Objekte der Antwort mit unlesbarem Wert (`feld` vorhanden, aber kein Zeitpunkt) zählen weder als jenseits noch
    diesseits; ihre Zahl steht getrennt am Ende jedes Urteils („; k mit unlesbarem modified“)."""
    def zeit(o):
        return _zeitpunkt(o[feld]) if o.get(feld) else None

    def jenseits(o, seite):
        t, g = zeit(o), (von if seite == "von" else bis)
        return g is not None and t is not None and (t < g if seite == "von" else t > g)

    if not antwort:
        return {s: "keine Objekte" for s, g in (("von", von), ("bis", bis)) if g is not None}
    ids, antwort_ids = {o.get("id") for o in basis}, {o.get("id") for o in antwort}
    fremd = [o for o in antwort if o.get("id") not in ids]
    juengste = max((t for t in (_zeitpunkt(o["created"]) for o in basis if o.get("created")) if t), default=None)
    neu = sum(1 for o in fremd if juengste is None or not o.get("created")
              or (_zeitpunkt(o["created"]) or juengste) >= juengste)
    neueste = _neueste_zuerst(basis)
    sortiert = neueste or _neueste_zuerst(basis, umgekehrt=True)   # nachweislich nach created sortiert
    unlesbar = sum(1 for o in antwort if o.get(feld) and zeit(o) is None)
    urteil = {}
    for seite, andere in (("von", "bis"), ("bis", "von")):
        if (von if seite == "von" else bis) is None:
            continue
        verletzt = [zeit(o) for o in antwort if jenseits(o, seite)]
        plaetze = basis[:max(len(basis) - neu, 0)] if seite == "von" and neueste else basis
        dort = [o for o in plaetze if jenseits(o, seite) and not jenseits(o, andere)]
        fehlen = sum(1 for o in dort if o.get("id") not in antwort_ids)
        if verletzt:
            richtung = "vor" if seite == "von" else "nach"
            aeusserst = min(verletzt) if seite == "von" else max(verletzt)
            urteil[seite] = (f"nein ({len(verletzt)} von {len(antwort)} {richtung} der Grenze; "
                             f"{'frühestes' if seite == 'von' else 'spätestes'} {feld} "
                             f"{_dauer_text(aeusserst - (von if seite == 'von' else bis))} {richtung} der Grenze)")
        elif fehlen and seite == "bis":
            urteil[seite] = "ja"
        elif fehlen >= 2 and fehlen == len(dort):
            urteil[seite] = f"ja ({fehlen} fehlen)" if sortiert else (
                f"nicht unterscheidbar (Reihenfolge unbekannt: {fehlen} Vorlagen unter der Grenze fehlen, die "
                "ungefilterte Seite ist nicht nachweislich nach created sortiert)")
        elif fehlen == 1 and len(dort) == 1:
            urteil[seite] = ("nicht unterscheidbar (nur eine Vorlage unter der Grenze auf der ungefilterten Seite, sie "
                             "fehlt: ebenso durch eine Löschung erklärbar)")
        elif fehlen:
            urteil[seite] = (f"nicht unterscheidbar ({fehlen} von {len(dort)} Vorlagen unter der Grenze fehlen, die "
                             f"übrigen stehen mit jüngerem {feld} in der Antwort)")
        else:
            urteil[seite] = ("nicht unterscheidbar (" + ("gleiche Kennungen wie ohne Filter" if not fremd else
                                                         f"{len(fremd)} Kennungen nicht auf der ungefilterten Seite")
                             + ("; neueste zuerst: die erste Seite zeigt nur die jüngsten Vorlagen"
                                if seite == "von" and bis is not None and neueste else "") + ")")
    if unlesbar:
        urteil = {s: f"{u}; {unlesbar} mit unlesbarem {feld}" for s, u in urteil.items()}
    return urteil


def _parametertests(url, basis, zeilen):
    """Parametertests an der Vorlagenliste, in dieser Reihenfolge: modified_since (Grenze aus der ungefilterten ersten
    Seite), created_since/created_until für 2025, modified_since URL-kodiert (bei SessionNet anderswo HTTP 404), zuletzt
    limit=100 (wirkt limit, dauert die Antwort womöglich über 5 s: Abbruch, wenn alles übrige vorliegt). HTTP 400, 401
    und 404 gelten als „Parameter abgelehnt“ (Messung geht weiter), zwei 401 in Folge brechen ab (abgelehnt oder
    Sperre?); jede andere Fehlantwort bricht nach dieser Anfrage ab."""
    basis = [o for o in basis if isinstance(o, dict)]
    seit, herkunft = _grenze_modified(basis)
    zeilen.append({"objekt": "paper", "feld": "grenze modified_since", "wert": f"{seit} ({herkunft})"})
    jahr = ("2025-01-01T00:00:00+01:00", "2025-12-31T23:59:59+01:00")
    # Stufe 2 (abgeschlossen): Zeitwerte unkodiert und einmal kodiert im Vergleich, Adressen wie in der Messung
    tests = [(f"test modified_since={seit}", _mit_parametern(url, False, modified_since=seit),
              {"von": _zeitpunkt(seit)}),
             (f"test created_since={jahr[0]}&created_until={jahr[1]}",
              _mit_parametern(url, False, created_since=jahr[0], created_until=jahr[1]),
              {"von": _zeitpunkt(jahr[0]), "bis": _zeitpunkt(jahr[1])}),
             ("test modified_since URL-kodiert",
              url + ("&" if "?" in url else "?") + urllib.parse.urlencode({"modified_since": seit}),
              {"von": _zeitpunkt(seit)}),
             ("test limit=100", _mit_parametern(url, False, limit=100), None)]
    zuvor_401 = False
    for feld, adresse, grenzen in tests:
        try:
            a = _json_von(adresse)
        except Abbruch as e:
            if e.art == "http" and e.code == 401 and zuvor_401:
                raise Abbruch(f"zweimal HTTP 401 in Folge (abgelehnt oder Sperre?): {e}", "http", 401) from e
            if e.art == "http" and e.code in ABGELEHNT:   # Parameter abgelehnt; Messung geht weiter
                zeilen.append({"objekt": "paper", "feld": feld, "wert": f"Parameter abgelehnt (HTTP {e.code})"})
                zuvor_401 = e.code == 401
                continue
            if e.art == "langsam":   # vollständig und gespeichert, aber zu langsam: Messwert vermerken, dann Abbruch
                try:
                    n = len(_json_von(adresse, abruf._cachepfad(adresse, ".json").read_bytes).get("data") or [])
                except (OSError, ValueError, AttributeError):
                    n = "?"
                zeilen.append({"objekt": "paper", "feld": feld, "wert": f"objekte={n}; {e}"})
            raise   # jede andere Fehlantwort bricht nach dieser Anfrage ab
        zuvor_401 = False
        daten = [o for o in a.get("data") or [] if isinstance(o, dict)]
        wert = f"objekte={len(daten)}; totalElements={_angabe(a.get('pagination'), 'totalElements')}"
        if grenzen and "bis" in grenzen:
            u = _filter_urteil(basis, daten, "created", **grenzen)
            wert += f"; created_until wirkt: {u['bis']}; created_since wirkt: {u['von']}"
        elif grenzen:
            wert += f"; filter_wirksam={_filter_urteil(basis, daten, 'modified', **grenzen)['von']}"
        zeilen.append({"objekt": "paper", "feld": feld, "wert": wert})


def kennzahlen(_):
    """10 Anfragen: System, Body, erste Seite von paper/meeting/organization/person, danach vier Parametertests an paper
    (_parametertests, limit=100 zuletzt)."""
    zeilen = []
    try:
        system, body = _json(SYSTEM), _json(BODY)
        zeilen += [{"objekt": "system", "feld": k, "wert": _wert(system.get(k))[:200]}
                   for k in ("oparlVersion", "name", "vendor", "product", "license", "website", "contactEmail")]
        zeilen += [{"objekt": "body", "feld": k, "wert": _wert(body.get(k))[:200]}
                   for k in ("name", "license", "licenseValidSince", "oparlSince", "contactEmail", "contactName",
                             "legislativeTerm", "modified")]
        vorlagen = None
        for name in ("paper", "meeting", "organization", "person"):
            url = body.get(name)
            if not url:
                zeilen.append({"objekt": name, "feld": "url", "wert": "fehlt im Body"})
                continue
            basis = _json(url)
            zeilen.append({"objekt": name, "feld": "url", "wert": url})
            zeilen += _liste_kennwerte(name, basis)
            if name == "paper":
                vorlagen = basis
        if vorlagen is not None:
            _parametertests(body["paper"], vorlagen.get("data") or [], zeilen)
    except Abbruch as e:
        zeilen.append({"objekt": "lauf", "feld": "abbruch", "wert": str(e)})
        raise
    finally:
        _schreibe("oparl_kennzahlen.tsv", zeilen)


def _form_links(seite):
    """(links, links.next) einer Listenseite in Worten: fehlt, leer (mit Wert), Objekt mit Schlüsseln bzw. vorhanden."""
    def leer(w):
        return w is None or (isinstance(w, (str, list, dict)) and not w)
    if "links" not in seite:
        return "fehlt", "–"
    links = seite["links"]
    if leer(links):
        return f"leer ({json.dumps(links)})", "–"
    if not isinstance(links, dict):
        return f"kein Objekt ({json.dumps(links)[:80]})", "–"
    nxt = ("fehlt" if "next" not in links else f"leer ({json.dumps(links['next'])})" if leer(links["next"])
           else f"vorhanden: {links['next']}")
    return "Objekt mit " + ",".join(sorted(links)), nxt


def _ende(n, groesse, seite):
    """Ende der Liste nach einer Seite mit `n` Objekten bei Seitengröße `groesse`, in Worten: Mit links.next geht die
    Liste weiter (bei nicht voller Seite unerwartet); ohne links.next (fehlt oder leer) ist das Ende erreicht, auch bei
    voller Seite; fehlt `links` ganz oder ist es leer, ebenso (die Pipeline liest es als Ende der Liste)."""
    links, nxt = _form_links(seite)
    voll = f"Seite voll ({n})" if n >= groesse else f"Seite nicht voll ({n} von {groesse})"
    if nxt.startswith("vorhanden"):
        weiter = "Ende nicht sichtbar" if n >= groesse else "Ende der Liste erwartet, links.next vorhanden"
        return f"{voll}: {weiter}"
    if links.startswith("kein Objekt"):
        return f"{voll}: links ist kein Objekt, Ende unklar"
    ohne = (("links fehlt ganz" if links == "fehlt" else f"links {links.split(' (')[0]}") if nxt == "–"
            else f"links.next {nxt.split(' (')[0]}")
    return f"{voll}, {ohne}: Ende erreicht" if n >= groesse else f"{voll}: Ende der Liste erwartet, {ohne}"


def _fenster_urteil(objekte, von, bis, voll):
    """Wirken created_since und created_until (Grenzen `von`, `bis`) auf einer Seite mit `objekte`? Ohne weitere
    Anfrage, je Grenze mit Abstand der äußersten Vorlage zur Grenze. `voll`: die Seite ist voll (so viele Objekte wie
    die Seitengröße).
    - created_since „nein“: Objekte vor der Untergrenze; „ja“: keines davor und die Seite nicht voll (ein Server ohne
      created_since füllte die Seite mit älteren Vorlagen); keines davor bei voller Seite: „nicht unterscheidbar“.
    - created_until „nein“: Objekte nach der Obergrenze; „ja“: keines danach (ein Server ohne created_until lieferte die
      jüngsten Vorlagen, Köln: neueste zuerst, Stufe 1 mit Vorlagen von November 2026).
    Unlesbares created wird gezählt."""
    zeiten = [_zeitpunkt(o["created"]) if o.get("created") else None for o in objekte]
    lesbar, unlesbar = [z for z in zeiten if z is not None], sum(z is None for z in zeiten)
    n = len(objekte)
    if not n:
        return {"since": "keine Objekte", "until": "keine Objekte", "unlesbar": 0}
    if not lesbar:
        return {"since": "nicht unterscheidbar (kein lesbares created)", "until": "nicht unterscheidbar (kein lesbares "
                "created)", "unlesbar": unlesbar}
    vor, nach = [z for z in lesbar if z < von], [z for z in lesbar if z > bis]
    frueh, spaet = min(lesbar), max(lesbar)
    if vor:
        since = f"nein ({len(vor)} von {n} vor der Grenze; frühestes created {_dauer_text(frueh - von)} vor der Grenze)"
    elif voll:
        since = ("nicht unterscheidbar (Seite voll, keines vor der Grenze; frühestes created "
                 f"{_dauer_text(frueh - von)} nach der Grenze)")
    else:
        since = f"ja (keines vor der Grenze; frühestes created {_dauer_text(frueh - von)} nach der Grenze)"
    until = (f"nein ({len(nach)} von {n} nach der Grenze; spätestes created {_dauer_text(spaet - bis)} nach der Grenze)"
             if nach else f"ja (keines nach der Grenze; spätestes created {_dauer_text(bis - spaet)} vor der Grenze)")
    return {"since": since, "until": until, "unlesbar": unlesbar}


def _antwortzeit(adresse):
    """Antwortzeit der letzten Anfrage an `adresse` laut _cache/abrufe.tsv („2.31 s“ bzw. „aus dem Cache“)."""
    if not abruf.PROTOKOLL.exists():
        return "unbekannt (Protokoll fehlt)"
    with abruf.PROTOKOLL.open(encoding="utf-8", newline="") as f:
        zeilen = [z for z in csv.DictReader(f, delimiter="\t") if z.get("url") == adresse]
    if not zeilen:
        return "unbekannt (nicht im Protokoll)"
    z = zeilen[-1]
    return "aus dem Cache" if z.get("quelle") == "cache" else f"{z.get('dauer_s')} s (Status {z.get('status')})"


def filtertest(_):
    """Stufe 3: genau eine Anfrage an <body.paper>?created_since=…&created_until=…&limit=100 (Werte kodiert) für das
    Fenster FENSTER (zwei Werktage in 2025, Begründung dort). Den Body liest es nur aus dem Cache (Stufe 1); fehlt er,
    Abbruch vor der Anfrage (Art `voraussetzung`), statt eine zweite Anfrage zu stellen. Auswertung ohne weitere
    Anfrage (_fenster_urteil): Zahl der Objekte, ob created_since bzw. created_until wirkt (mit Abstand zur Grenze),
    Form von links und links.next (Ende sichtbar, wenn weniger als 100 Objekte), Antwortzeit. Ist die Antwort zu
    langsam (RATSATLAS_MAX_DAUER), werden Objektzahl und Urteil aus der gespeicherten Antwort noch vermerkt, dann
    Abbruch. Ergebnis in oparl_filtertest.tsv."""
    if not abruf._cachepfad(BODY, ".json").exists():
        raise Abbruch(f"Body nicht im Cache ({BODY}); filtertest stellt nur die eine Anfrage an die Vorlagenliste, "
                      "keine für den Body (Cache aus Stufe 1 im Hauptverzeichnis oder organisationen vorher im selben "
                      "Cache)", "voraussetzung")
    body = _json(BODY)   # aus dem Cache
    if not isinstance(body.get("paper"), str) or not body["paper"]:
        raise Abbruch(f"Body ohne Liste paper (Cache): {BODY}", "voraussetzung")
    von, bis = FENSTER
    adresse = _mit_parametern(body["paper"], created_since=von, created_until=bis, limit=FILTERTEST_LIMIT)
    zeilen, langsam = [{"feld": "adresse", "wert": adresse}, {"feld": "fenster", "wert": f"{von} bis {bis}"}], None
    try:
        try:
            seite = _json_von(adresse)
        except Abbruch as e:
            if e.art != "langsam":
                raise
            langsam = e   # vollständig und gespeichert, aber zu langsam: aus dem Cache auswerten, dann Abbruch
            seite = _json_von(adresse, abruf._cachepfad(adresse, ".json").read_bytes)
        daten = [o for o in seite.get("data") or [] if isinstance(o, dict)]
        pag = seite.get("pagination") if isinstance(seite.get("pagination"), dict) else {}
        groesse = pag.get("elementsPerPage") if isinstance(pag.get("elementsPerPage"), int) else FILTERTEST_LIMIT
        u = _fenster_urteil(daten, _zeitpunkt(von), _zeitpunkt(bis), len(daten) >= groesse)
        links, nxt = _form_links(seite)
        zeilen += [{"feld": "objekte", "wert": len(daten)},
                   {"feld": "created_since wirkt", "wert": u["since"]},
                   {"feld": "created_until wirkt", "wert": u["until"]},
                   {"feld": "created unlesbar", "wert": u["unlesbar"]},
                   {"feld": "pagination", "wert": json.dumps(seite.get("pagination"), ensure_ascii=False)},
                   {"feld": "links", "wert": links}, {"feld": "links.next", "wert": nxt},
                   {"feld": "ende", "wert": _ende(len(daten), groesse, seite)},
                   {"feld": "antwortzeit", "wert": _antwortzeit(adresse)}]
        if langsam:
            zeilen.append({"feld": "abbruch", "wert": str(langsam)})
    except Abbruch as e:
        zeilen.append({"feld": "abbruch", "wert": str(e)})
        raise
    finally:
        _schreibe("oparl_filtertest.tsv", zeilen)
    print(f"filtertest: {zeilen[2]['wert']} Objekte; created_since: {u['since']}; created_until: {u['until']}")
    if langsam:
        raise langsam


def organisationen(a):
    body = _json(BODY)
    typen, zeilen = collections.Counter(), []
    for _, seite in _seiten(body["organization"], a.seiten, name="organization"):
        for o in seite.get("data", []):
            typen[o.get("organizationType") or "(leer)"] += 1
            zeilen.append({"id": o.get("id"), "name": o.get("name"), "kurz": o.get("shortName"),
                           "organizationType": o.get("organizationType"), "classification": o.get("classification"),
                           "startDate": o.get("startDate"), "endDate": o.get("endDate")})
    _schreibe("oparl_organisationen.tsv", zeilen)
    _schreibe("oparl_organisationstypen.tsv", [{"organizationType": k, "anzahl": v} for k, v in typen.most_common()])
    e = _LISTEN[-1]
    print(f"{e['objekte']} Organisationen auf {e['seiten']} Seiten; {e['ende']}")


def _bedeckung(papers):
    felder = ["underDirectionOf", "originatorPerson", "originatorOrganization", "mainFile", "auxiliaryFile",
              "location", "consultation", "relatedPaper", "superordinatedPaper", "subordinatedPaper", "date"]
    n = len(papers)
    zeilen = [{"feld": f, "vorhanden": sum(1 for p in papers if p.get(f)), "von": n} for f in felder]
    loc = collections.Counter()
    for p in papers:
        for l in p.get("location") or []:
            l = l if isinstance(l, dict) else {}
            for k in ("description", "streetAddress", "postalCode", "subLocality", "locality", "room", "geojson"):
                if l.get(k):
                    loc[k] += 1
    zeilen += [{"feld": f"location.{k}", "vorhanden": v, "von": n} for k, v in sorted(loc.items())]
    return zeilen


def _hauptdatei(p):
    """Adresse der Hauptdatei (downloadUrl, sonst accessUrl) oder None; weitere Angaben der Datei werden nicht
    übernommen (Dateiname, Volltext)."""
    f = p.get("mainFile")
    return (f.get("downloadUrl") or f.get("accessUrl")) if isinstance(f, dict) else None


def stichprobe(a):
    """Je Jahr die ersten Seiten der Vorlagenliste mit created_since/created_until (kodiert) und limit (Vorgabe 100).
    Doppelungen werden getrennt
    gezählt: im selben Jahr (Seiten verschoben, z. B. erste Seite aus dem Cache einer früheren Nacht) und aus einem
    anderen Jahr (Jahresfilter wirkt nicht). Wirkt der Filter erkennbar nicht, bricht der Lauf nach diesem Jahr ab."""
    body = _json(BODY)
    papers, gesehen, jahre = [], {}, []
    zaehl = collections.Counter()   # ausser, doppelt_jahr, doppelt_jahre
    vollstaendig = False
    try:
        for jahr in range(a.von, a.bis + 1):
            von, bis = f"{jahr}-01-01T00:00:00+01:00", f"{jahr}-12-31T23:59:59+01:00"
            grenzen = (dt.datetime.fromisoformat(von), dt.datetime.fromisoformat(bis))
            tot, vorher = "", zaehl.copy()
            for nr, seite in _seiten(body["paper"], a.seiten, name=f"paper {jahr}", created_since=von,
                                     created_until=bis, **({"limit": a.limit} if a.limit else {})):
                tot = _angabe(seite.get("pagination"), "totalElements") if nr == 1 else tot
                for p in seite.get("data", []):
                    if p.get("id") in gesehen:
                        zaehl["doppelt_jahr" if gesehen[p.get("id")] == jahr else "doppelt_jahre"] += 1
                        continue
                    gesehen[p.get("id")] = jahr
                    t = _zeitpunkt(p["created"]) if p.get("created") else None
                    if t and not grenzen[0] <= t <= grenzen[1]:
                        zaehl["ausser"] += 1
                    p["_jahr_filter"] = jahr
                    papers.append(p)
            e = _LISTEN[-1]
            jahre.append({"jahr": jahr, "objekte": sum(1 for p in papers if p["_jahr_filter"] == jahr),
                          "totalElements": tot, "seiten": e["seiten"], "ende": e["ende"]})
            ausser, fremd = zaehl["ausser"] - vorher["ausser"], zaehl["doppelt_jahre"] - vorher["doppelt_jahre"]
            if ausser or fremd:
                raise Abbruch(f"Jahresfilter wirkt nicht ({jahr}: {ausser} mit created außerhalb des Jahres, {fremd} "
                              f"schon in einem anderen Jahr geliefert); weitere Jahre nicht abgerufen", "filter")
        vollstaendig = True
    finally:
        if papers:   # Teilergebnis bei Abbruch; ohne Vorlagen bleiben frühere Ergebnisse unverändert
            _stichprobe_schreiben(papers, jahre, zaehl, vollstaendig)
    print(f"{len(papers)} verschiedene Vorlagen aus {a.von}–{a.bis}")


def _stichprobe_schreiben(papers, jahre, zaehl, vollstaendig):
    typen = collections.Counter(p.get("paperType") or "(leer)" for p in papers)
    ref = collections.Counter("AN/NNNN/JJJJ" if RE_AN.match(p.get("reference") or "") else
                              "NNNN/JJJJ" if RE_VV.match(p.get("reference") or "") else "anderes"
                              for p in papers)
    if vollstaendig:   # nur eine vollständige Stichprobe dient pdf-koepfe als Grundlage
        STICHPROBE.parent.mkdir(parents=True, exist_ok=True)
        with STICHPROBE.open("w", encoding="utf-8") as f:
            for p in papers:
                f.write(json.dumps({"id": p.get("id"), "reference": p.get("reference"),
                                    "paperType": p.get("paperType"), "date": p.get("date"),
                                    "datei": _hauptdatei(p)}, ensure_ascii=False) + "\n")
    _schreibe("oparl_stichprobe_bedeckung.tsv", _bedeckung(papers) + [
        {"feld": "created außerhalb des Filterjahres", "vorhanden": zaehl["ausser"], "von": len(papers)},
        {"feld": "doppelte Kennungen im selben Jahr (Seiten verschoben)", "vorhanden": zaehl["doppelt_jahr"],
         "von": len(papers) + zaehl["doppelt_jahr"] + zaehl["doppelt_jahre"]},
        {"feld": "doppelte Kennungen aus anderen Jahren (Jahresfilter wirkt nicht)", "vorhanden": zaehl["doppelt_jahre"],
         "von": len(papers) + zaehl["doppelt_jahr"] + zaehl["doppelt_jahre"]}])
    _schreibe("oparl_papertypen.tsv", [{"paperType": k, "anzahl": v} for k, v in typen.most_common()])
    _schreibe("oparl_referenzschema.tsv", [{"schema": k, "anzahl": v} for k, v in ref.most_common()])
    _schreibe("oparl_stichprobe_jahre.tsv", jahre)


def sitzungen(a):
    body = _json(BODY)
    ergebnisse, n_top, n_sitz, oeff = collections.Counter(), 0, 0, collections.Counter()
    for _, seite in _seiten(body["meeting"], a.seiten, name="meeting"):
        for m in seite.get("data", []):
            n_sitz += 1
            for t in m.get("agendaItem") or []:
                if not isinstance(t, dict):
                    continue
                n_top += 1
                ergebnisse[(t.get("result") or "(leer)").strip()] += 1
                oeff[str(t.get("public"))] += 1
    _schreibe("oparl_top_ergebnisse.tsv", [{"result": k, "anzahl": v} for k, v in ergebnisse.most_common()]
              + [{"result": f"public={k}", "anzahl": v} for k, v in oeff.items()]
              + [{"result": "TOPs insgesamt", "anzahl": n_top}, {"result": "Sitzungen insgesamt", "anzahl": n_sitz}])


def auswahl_je_jahr(vorlagen, anzahl):
    """Gleichmäßig über die Jahre (Jahr aus der Referenz NNNN/JJJJ): reihum je Jahr, neuere Jahre zuerst, damit ein
    Rest bei ungleicher Teilung den aktuellen Vorlagenköpfen zugutekommt."""
    je_jahr = collections.defaultdict(list)
    for p in vorlagen:
        je_jahr[p["reference"][-4:]].append(p)
    gruppen = [je_jahr[j] for j in sorted(je_jahr, reverse=True)]
    aus = [g[i] for i in range(max(map(len, gruppen), default=0)) for g in gruppen if i < len(g)]
    return aus[:anzahl]


def pdf_koepfe(a):
    from pypdf import PdfReader

    if not STICHPROBE.exists():
        raise Abbruch(f"zuerst: stichprobe ({STICHPROBE} fehlt; die Datei entsteht nur bei einer vollständigen "
                      "Stichprobe in derselben Arbeitsumgebung)", "voraussetzung")
    papers = [json.loads(z) for z in STICHPROBE.open(encoding="utf-8")]
    vv_alle = [p for p in papers if RE_VV.match(p.get("reference") or "")]
    vv = auswahl_je_jahr([p for p in vv_alle if p.get("datei")], a.anzahl)
    print(f"{len(vv_alle)} Verwaltungsvorlagen in der Stichprobe, {sum(1 for p in vv_alle if p.get('datei'))} mit "
          f"Hauptdatei; Auswahl {len(vv)}: "
          + ", ".join(f"{j} {n}" for j, n in sorted(collections.Counter(p["reference"][-4:] for p in vv).items())))
    zeilen = []
    try:
        for p in vv:
            url = p["datei"]
            z = {"id": p["id"], "reference": p["reference"], "jahr": p["reference"][-4:],
                 "paperType": p.get("paperType"), "datei": "mainFile", "treffer": "nicht abgerufen"}
            zeilen.append(z)
            try:
                inhalt = _hole(url, ".pdf")
            except Abbruch as e:
                if e.art == "http" and e.code in (404, 410):   # einzelne fehlende Datei: weiter
                    z["treffer"] = f"fehler: HTTP {e.code}"
                    continue
                raise
            try:
                r = PdfReader(io.BytesIO(inhalt))
                text = r.pages[0].extract_text() or "" if r.pages else ""
                m = RE_DEZ.search(text)
                z["treffer"] = "kennung" if m else ("nur_bezeichnung" if RE_DEZ_LOSE.search(text) else
                                                    "kein_text" if not text.strip() else "nein")
                z["kennung"] = re.sub(r"\s+", "", m.group(1)) if m else ""
            except Exception as e:  # einzelne defekte Dateien sollen die Messung nicht abbrechen
                z["treffer"] = f"fehler: {type(e).__name__}"
    finally:
        _schreibe("pdf_koepfe.tsv", zeilen)
    print(dict(collections.Counter(z["treffer"] for z in zeilen)))


KOMMANDOS = {"test": test, "kennzahlen": kennzahlen, "organisationen": organisationen, "filtertest": filtertest,
             "stichprobe": stichprobe, "sitzungen": sitzungen, "pdf-koepfe": pdf_koepfe}
LAEUFE_SPALTEN = ["lauf", "stufe", "kommando", "parameter", "start", "ende", "dauer_s", "netz", "cache",
                  "obergrenze", "protokoll_von", "protokoll_bis", "ergebnis", "meldung"]
LISTEN_SPALTEN = ["lauf", "liste", "grenze", "seiten", "objekte", "ende", "erstes_next", "url"]


def _parameter(a):
    if a.kommando in ("organisationen", "sitzungen"):
        return f"--seiten {a.seiten}"
    if a.kommando == "stichprobe":
        return f"--seiten {a.seiten} --von {a.von} --bis {a.bis} --limit {a.limit}"
    return f"--anzahl {a.anzahl}" if a.kommando == "pdf-koepfe" else ""


def _laufnummer():
    datei = ERG / "oparl_laeufe.tsv"
    if not datei.exists():
        return 1
    with datei.open(encoding="utf-8") as f:
        return max(sum(1 for _ in f), 1)


def _markerpfad():
    return abruf.PROTOKOLL.parent / MARKER


def _marker_setzen(lauf):
    """Legt die Markerdatei an (Lauf, Stufe, Kommando, Parameter, Start, Prozess); liefert ihren Inhalt."""
    text = json.dumps({**{k: lauf[k] for k in ("lauf", "stufe", "kommando", "parameter", "start")}, "pid": os.getpid()},
                      ensure_ascii=False)
    pfad = _markerpfad()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8")
    return text


def _marker_entfernen(text):
    """Entfernt die Markerdatei, wenn sie noch die dieses Laufs ist."""
    try:
        if _markerpfad().read_text(encoding="utf-8") == text:
            _markerpfad().unlink()
    except OSError:
        pass


def _marker_vermerken(eintrag, datei, jetzt):
    """Trägt einen hart beendeten Lauf (Marker ohne Vermerk), dessen Marker entfernt oder überschrieben wird, als Zeile
    NICHT_REGULAER_MARKER in oparl_laeufe.tsv nach: Anfragenzahl und Ende unbekannt. Die Zeile löst die 12-Stunden-Regel
    nicht aus (RE_ABBRUCH); sie hält nur fest, dass es den Lauf gab."""
    zeile = {k: eintrag.get(k, "") for k in ("lauf", "stufe", "kommando", "parameter", "start")}
    zeile.update(ergebnis=NICHT_REGULAER_MARKER, netz="", cache="", meldung=(
        f"hart beendet (Markerdatei ohne Vermerk, etwa nach SIGKILL), Anfragenzahl unbekannt; nachgetragen "
        f"{jetzt.isoformat(timespec='seconds')}"))
    datei.parent.mkdir(parents=True, exist_ok=True)
    neu = not datei.exists()
    with datei.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, LAEUFE_SPALTEN, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        if neu:
            w.writeheader()
        w.writerow({k: str(zeile.get(k, "")).replace("\t", " ").replace("\n", " ") for k in LAEUFE_SPALTEN})


def _marker_pruefen(marker, zeilen, jetzt, datei=None):
    """Markerdatei eines Laufs ohne Vermerk in oparl_laeufe.tsv: jünger als SPERRFRIST oder unlesbar (dann bis zur
    Rücksprache) → Eintrag wie eine Zeile mit „nicht regulär beendet“; älter → gemeldet, als NICHT_REGULAER_MARKER in
    `datei` nachgetragen (sofern gegeben) und entfernt; ein Marker, dessen Lauf vermerkt ist (Ende zwischen Vermerk
    und Entfernen), wird ebenfalls entfernt (der Vermerk gilt). Sonst None."""
    if not marker.exists():
        return None
    try:
        m = json.loads(marker.read_text(encoding="utf-8"))
        m = m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        m = {}
    if m and any(z.get("lauf") == str(m.get("lauf")) and z.get("start") == m.get("start") for z in zeilen):
        marker.unlink(missing_ok=True)
        return None
    start = _zeitpunkt(m.get("start") or "") if m else None
    eintrag = {"lauf": m.get("lauf", "?"), "stufe": m.get("stufe", ""), "kommando": m.get("kommando", "?"),
               "parameter": m.get("parameter", ""), "start": m.get("start", ""), "ende": "", "ergebnis": NICHT_REGULAER,
               "marker": str(marker), "meldung": f"Markerdatei {marker} ohne Vermerk in oparl_laeufe.tsv",
               "unlesbar": start is None}   # Marker oder sein Start unlesbar: sperrt bis zur Rücksprache
    if start is None or jetzt - start < SPERRFRIST:
        return eintrag
    print(f"Hinweis: Lauf {eintrag['lauf']} ({eintrag['kommando']}, Stufe {eintrag['stufe'] or '?'}) vom "
          f"{eintrag['start']} wurde {NICHT_REGULAER} (Markerdatei {marker} ohne Vermerk, älter als "
          f"{SPERRFRIST.total_seconds() / 3600:g} Stunden); Marker entfernt"
          + (", in oparl_laeufe.tsv nachgetragen" if datei is not None else "") + ". Im Bericht vermerken.",
          file=sys.stderr)
    if datei is not None:
        _marker_vermerken(eintrag, Path(datei), jetzt)
    marker.unlink(missing_ok=True)
    return None


def letzter_abbruch(datei=None, jetzt=None, marker=None):
    """Der letzte Lauf aus oparl_laeufe.tsv (Zeile als dict), wenn er vor weniger als SPERRFRIST mit „abbruch (…)“,
    „fehler (…)“ oder „unterbrochen“ (Strg+C, SIGTERM, SIGHUP) endete, sonst None. Maßgeblich ist `ende` (ohne Zone:
    Ortszeit Köln); fehlt es oder ist es unlesbar, gilt der Lauf vorsichtshalber als gerade beendet. Vorher die
    Markerdatei (`marker`; Vorgabe neben _cache/abrufe.tsv, nur wenn auch `datei` die Vorgabe ist): Ein Lauf ohne
    Vermerk, der vor weniger als SPERRFRIST begann (hart beendet), gilt als „nicht regulär beendet“ (_marker_pruefen)."""
    if datei is None:
        datei, marker = ERG / "oparl_laeufe.tsv", _markerpfad() if marker is None else marker
    datei, zeilen = Path(datei), []
    if datei.exists():
        with datei.open(encoding="utf-8", newline="") as f:
            zeilen = list(csv.DictReader(f, delimiter="\t"))
    jetzt = jetzt or dt.datetime.now(ZoneInfo("Europe/Berlin"))
    offen = _marker_pruefen(Path(marker), zeilen, jetzt, datei) if marker is not None else None
    if offen:
        return offen
    if not zeilen or not RE_ABBRUCH.match(zeilen[-1].get("ergebnis") or ""):
        return None
    letzter = zeilen[-1]
    ende = _zeitpunkt(letzter.get("ende") or "")
    return letzter if ende is None or jetzt - ende < SPERRFRIST else None


def _signal_beenden(nummer, _rahmen):
    """Strg+C, SIGTERM oder SIGHUP: endet wie Strg+C, damit der Lauf als „unterbrochen“ vermerkt wird (12-Stunden-Regel).
    Weitere Signale bleiben ab hier ohne Wirkung (_signal_ohne_wirkung; ein zweites kurz danach unterbräche sonst den
    Vermerk)."""
    _signale(_signal_ohne_wirkung)
    raise KeyboardInterrupt(signal.Signals(nummer).name)


def _signal_ohne_wirkung(_nummer, _rahmen):
    """Ein weiteres Signal nach dem ersten: ohne Wirkung (statt SIG_IGN, damit ein schon zugestelltes Signal keine
    Meldung „ignored due to race condition“ erzeugt)."""


def _signale(behandlung, signale=(signal.SIGINT, *SIGNALE)):
    """Setzt die Behandlung der Signale; liefert die vorige je Signal."""
    return {s: signal.signal(s, behandlung) for s in signale}


def _signale_abfangen():
    """_signal_beenden für Strg+C (nur statt der Vorgabe von Python; im Hintergrund ignoriert bleibt ignoriert), SIGTERM
    und SIGHUP (nur bei SIG_DFL: mit nohup bleibt SIGHUP ignoriert). Liefert die vorige Behandlung aller drei Signale."""
    vorher = {s: signal.getsignal(s) for s in (signal.SIGINT, *SIGNALE)}
    for s, alt in vorher.items():
        if (s == signal.SIGINT and alt is not signal.default_int_handler) or (s == signal.SIGHUP
                                                                             and alt != signal.SIG_DFL):
            continue
        signal.signal(s, _signal_beenden)
    return vorher


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("kommando", choices=list(KOMMANDOS))
    ap.add_argument("--seiten", type=int, default=None,
                    help="Seiten je Jahr (stichprobe, Vorgabe 1) bzw. insgesamt (organisationen 4, sitzungen 2); "
                         "0 = ohne Seitengrenze")
    ap.add_argument("--limit", type=int, default=LIMIT_VORGABE,
                    help="Objekte je Seite (stichprobe; Köln: limit wirkt, Stufe 2); 0 = ohne limit")
    ap.add_argument("--von", type=int, default=2019)
    ap.add_argument("--bis", type=int, default=2026)
    ap.add_argument("--anzahl", type=int, default=100)
    a = ap.parse_args(argv)
    if a.seiten is None:
        a.seiten = SEITEN_VORGABE.get(a.kommando, 3)
    if not (lokal(SYSTEM) and lokal(BODY)):
        if os.environ.get("RATSATLAS_STADT_INFORMIERT") != "ja":
            sys.exit("Abbruch: Die Stadt Köln ist noch nicht informiert (CLAUDE.md, Abschnitt 9). "
                     "Erst nach Freigabe mit RATSATLAS_STADT_INFORMIERT=ja ausführen.")
        if not im_zeitfenster():
            sys.exit(f"Abbruch: außerhalb des Zeitfensters {os.environ.get('RATSATLAS_ZEITFENSTER', '23-1')} Uhr "
                     "Ortszeit (RATSATLAS_ZEITFENSTER).")
        if a.kommando == "pdf-koepfe" and os.environ.get("RATSATLAS_PDF_FREIGEGEBEN") != "ja":
            sys.exit("Abbruch: PDF-Abruf erst nach Klärung mit der Stadt (RATSATLAS_PDF_FREIGEGEBEN=ja).")
        werte, fehler = sichere_vorgaben()
        if fehler:
            sys.exit("Abbruch vor der ersten Anfrage: " + "; ".join(fehler) + " (Befehle: explore/STUFEN.md).")
        vorher = letzter_abbruch()
        if vorher and os.environ.get("RATSATLAS_NACH_ABBRUCH") != "ja":
            grund = (f"Markerdatei {vorher['marker']} unlesbar (Marker unlesbar, sperrt bis zur Rücksprache; Lauf, "
                     "Beginn und Ende unbekannt)" if vorher.get("unlesbar") else
                     f"Lauf {vorher.get('lauf')} ({vorher.get('kommando')}) vom {vorher.get('start') or '?'} wurde "
                     f"„{NICHT_REGULAER}“ oder läuft noch (Markerdatei {vorher['marker']} ohne Vermerk in "
                     "oparl_laeufe.tsv, etwa nach SIGKILL oder einem Absturz der Arbeitsumgebung); begonnen vor "
                     f"weniger als {SPERRFRIST.total_seconds() / 3600:g} Stunden" if vorher.get("marker") else
                     f"Lauf {vorher.get('lauf')} ({vorher.get('kommando')}) endete {vorher.get('ende') or '(ohne Ende)'}"
                     f" mit „{vorher.get('ergebnis')}“, vor weniger als {SPERRFRIST.total_seconds() / 3600:g} Stunden")
            sys.exit(f"Abbruch vor der ersten Anfrage: {grund}. Nach einem Abbruch gilt: in dieser Nacht keine "
                     "weitere Anfrage und keine weitere Stufe, Bericht an den Auftraggeber (explore/STUFEN.md). "
                     "Weiter nur nach Rücksprache mit RATSATLAS_NACH_ABBRUCH=ja.")
        if vorher and vorher.get("marker"):   # nach Rücksprache: Marker wird überschrieben, den Lauf zuvor nachtragen
            _marker_vermerken(vorher, ERG / "oparl_laeufe.tsv", dt.datetime.now(ZoneInfo("Europe/Berlin")))
        abruf.WIEDERHOLUNGEN, abruf.MAX_DAUER = werte["wiederholungen"], werte["max_dauer"]
        abruf.ABSTAND = werte["abstand"]

    zeitzone = ZoneInfo("Europe/Berlin")
    lauf = {"lauf": _laufnummer(), "stufe": os.environ.get("RATSATLAS_STUFE", ""), "kommando": a.kommando,
            "parameter": _parameter(a), "start": dt.datetime.now(zeitzone).isoformat(timespec="seconds"),
            "obergrenze": abruf.MAX_ANFRAGEN or "", "protokoll_von": abruf.protokollzeilen(),
            "ergebnis": UNTERBROCHEN, "meldung": NICHT_REGULAER}   # schlechter Fall zuerst
    rueckgabe, abruf.unterbrochen = 0, ""
    # Marker vor der ersten Anfrage an die Stadt (ein hart beendeter Lauf ohne Vermerk sperrt so 12 Stunden)
    marker = None if lokal(SYSTEM) and lokal(BODY) else _marker_setzen(lauf)
    vorher = _signale_abfangen()
    try:
        KOMMANDOS[a.kommando](a)
        lauf["ergebnis"], lauf["meldung"] = "ok", ""
    except Abbruch as e:
        lauf["ergebnis"], lauf["meldung"], rueckgabe = f"abbruch ({e.art or 'sonstiges'})", str(e), 2
        if e.art == "proxy":   # Ablehnung in der Arbeitsumgebung, nicht durch die Stadt
            hinweis = (f"Der Proxy der Arbeitsumgebung hat die Verbindung abgelehnt; keine Anfrage hat die Stadt "
                       f"erreicht, kein Hinweis auf eine Sperre. Nicht wiederholen, sondern berichten: Der Host "
                       f"{urllib.parse.urlsplit(SYSTEM).hostname} muss im Netz der Arbeitsumgebung erlaubt sein "
                       f"(explore/STUFEN.md, Stufe 1).")
        elif e.art == "sperre":   # auch 502/504 des Proxys und abgeschnittene oder unlesbare Antworten
            hinweis = ("Mögliche Sperre: in dieser Nacht keine weitere Anfrage, alle Abrufe ruhen bis zur Klärung mit "
                       "der Stadt. Stoppen und berichten (explore/STUFEN.md).")
        elif e.art == "tls":   # vermutlich Einstellung der Arbeitsumgebung
            hinweis = ("Die Zertifikatsprüfung ist gescheitert: vermutlich eine Einstellung der Arbeitsumgebung "
                       "(CA des Proxys); ein Zertifikat der Gegenseite oder eine Sperrseite ist nicht ausgeschlossen. "
                       "Keine HTTP-Anfrage gesendet. Berichten, nicht wiederholen; in dieser Nacht keine weitere "
                       "Anfrage (12-Stunden-Regel).")
        elif e.art == "parallel":   # ein anderer Prozess hält die Sperre auf den Cache
            hinweis = ("Ein anderer Abrufprozess läuft noch; keine Anfrage gesendet. Prozesse nur nacheinander "
                       "starten; stoppen und berichten (explore/STUFEN.md).")
        else:
            hinweis = "Stoppen und berichten (explore/STUFEN.md)."
        print(f"Abbruch: {e}\n{hinweis}", file=sys.stderr)
    except KeyboardInterrupt as e:   # Strg+C, SIGTERM oder SIGHUP (_signal_beenden)
        grund = str(e) if str(e) in signal.Signals.__members__ else "SIGINT"
        lauf["meldung"] = (f"unterbrochen während einer Anfrage ({grund}): mögliche Sperre, stoppen; "
                           f"{abruf.unterbrochen}" if abruf.unterbrochen else f"unterbrochen ({grund})")
        lauf["ergebnis"], rueckgabe = UNTERBROCHEN, 128 + signal.Signals[grund].value
        print(f"Unterbrochen ({grund}){' während einer Anfrage: mögliche Sperre' if abruf.unterbrochen else ''}. In "
              "dieser Nacht keine weitere Anfrage und keine weitere Stufe (12-Stunden-Regel, RATSATLAS_NACH_ABBRUCH); "
              "stoppen und berichten (explore/STUFEN.md).", file=sys.stderr)
    except Exception as e:   # z. B. HTML statt JSON: ebenfalls stoppen und berichten
        lauf["ergebnis"], lauf["meldung"], rueckgabe = f"fehler ({type(e).__name__})", str(e)[:300], 1
        print(f"Fehler: {type(e).__name__}: {e}\nStoppen und berichten (explore/STUFEN.md).", file=sys.stderr)
    finally:
        _signale(signal.SIG_IGN)   # den Vermerk nicht unterbrechen
        ende = dt.datetime.now(zeitzone)
        lauf.update(abruf.zaehler(), ende=ende.isoformat(timespec="seconds"),
                    dauer_s=f"{(ende - dt.datetime.fromisoformat(lauf['start'])).total_seconds():.0f}",
                    protokoll_bis=abruf.protokollzeilen())
        _anhaengen("oparl_laeufe.tsv", LAEUFE_SPALTEN, [lauf])
        _anhaengen("oparl_listen.tsv", LISTEN_SPALTEN, [{**e, "lauf": lauf["lauf"]} for e in _LISTEN])
        if marker:   # erst nach dem Vermerk (sonst bliebe ein hart beendeter Lauf ohne Spur)
            _marker_entfernen(marker)
        print(f"Lauf {lauf['lauf']}: {lauf['netz']} Anfragen ans Netz, {lauf['cache']} aus dem Cache; "
              f"{lauf['ergebnis']}", file=sys.stderr)
        for s, behandlung in vorher.items():
            if behandlung is not None:   # None: nicht aus Python gesetzt, bleibt ignoriert
                signal.signal(s, behandlung)
    return rueckgabe


if __name__ == "__main__":
    sys.exit(main())
