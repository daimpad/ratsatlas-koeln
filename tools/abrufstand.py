"""Fortschritt des Abrufs für das Log und die Zusammenfassung des Workflows (pages.yml, gleich nach dem Sichern des
Abrufzustands, immer).

Aufruf: python tools/abrufstand.py [--zustand PFAD] [--stand PFAD] [--statistik PFAD] [--vorlagen-gesamt N]
Liest nur `data/raw/zustand_abruf.json`, `data/raw/STAND.json` und `data/export/abrufstatistik.tsv` (was davon vorhanden
ist; Vorgaben aus pipeline/config.py), schreibt nichts in data/ und sendet keine Anfrage. Ausgabe auf stdout und, in
GitHub Actions, als Markdown an `$GITHUB_STEP_SUMMARY`:
- je Liste (papers, meetings, organizations): Anfragen und Objekte der letzten Nacht mit Anfragen (Zeilen der
  Abrufstatistik bis 12 Stunden vor der jüngsten), Seiten bisher, Vollabruf läuft oder abgeschlossen, Stelle der
  Fortsetzung (Seitennummer und Adresse nur mit `page` und `limit`, ohne andere Parameter, Zugangsdaten oder Anker),
  gespeicherter Stand (Objekte der letzten Zeile mit Ergebnis `ok` oder `übersprungen`);
- wie die letzte Nacht endete (Abbruch, Ende des Zeitfensters oder vollständig; nur aus Zeitpunkten und Arten);
- Zähler der Nächte mit möglicher Sperre samt Pause von sieben Tagen (wie sessionnet._pause_grund), Nächte mit
  fehlerhafter Liste und mit Zertifikatsfehlern, Retry-After (`nicht_vor`), letzter Abbruch (Art, HTTP-Code, Zeit),
  `abruf_ok`;
- verbleibende Nächte der Vorlagen nur mit bekannter Gesamtzahl: Die Kölner API nennt in `pagination` keine
  (Stufe 1, 07.11.2026), der Abruf speichert keine; ohne `--vorlagen-gesamt` (etwa eine Angabe der Stadt) steht dort
  „unbekannt“;
- Dokumentschritt (PDF-Köpfe, pipeline/dokumente.py; läuft in pages.yml erst nach diesem Schritt, gezeigt wird also
  der Stand vor ihm): aus dem eigenen Eintrag `dokumente` im Zustand die Nacht und die Zahl der darin angefragten
  Dateien (`nacht`, `dateien`) und die Nächte mit möglicher Sperre beim Dokumentabruf samt Pause (`verdacht`); aus der
  letzten Zeile `dokumente` der Abrufstatistik Zeitpunkt, Anfragen, Dateien mit Ergebnis und die Art des Ergebnisses.
  Keine Kennungen, Adressen, Dateinamen oder Ergebnisse einzelner Dateien; wie viele Dateien insgesamt noch zu lesen
  sind, steht in keiner der drei Dateien (nur im Text der Abrufstatistik, der nicht ausgegeben wird).
Nur Zahlen und Zustände: keine Titel, Namen oder anderen Inhalte von Objekten und keine Meldungstexte (`meldung` in
Zustand und STAND.json, `ergebnis` der Abrufstatistik nur als Art wie „ok“ oder „unterbrochen“), denn sie können
Adressen und Ausschnitte enthalten; einzig der Grund eines übersprungenen Laufs (`abruf_uebersprungen.grund`, vom Abruf
aus festen Texten, Zahlen und Daten gebildet) erscheint, einzeilig und gekürzt.
Fehlende oder unlesbare Dateien und Werte erscheinen als „fehlt“ bzw. „unlesbar“; das Skript endet immer mit 0 (auch
nach einem unerwarteten Fehler: Warnung mit dem Namen des Fehlers, ohne Text), damit es den Lauf nie anhält.
"""
import argparse
import collections
import csv
import json
import math
import os
import re
import sys
import urllib.parse
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import abruf, config, sessionnet  # noqa: E402

LISTEN = ("papers", "meetings", "organizations")   # Reihenfolge der Ausgabe
NAME = {"papers": "Vorlagen", "meetings": "Sitzungen", "organizations": "Organisationen"}
# Arten des Ergebnisses einer Zeile der Abrufstatistik (Anfang der Spalte `ergebnis`, sessionnet._abruf_liste)
ERGEBNISSE = ("ok", "unterbrochen", "abbruch", "warnung", "übersprungen", "programmfehler")
MODI = ("voll", "voll, fortgesetzt", "inkrementell", "voll, Fortsetzung verworfen", "voll, Zeitfilter nicht angewandt",
        "übersprungen")
# Modi, mit denen ein Vollabruf von vorn beginnt (Seite 1)
VON_VORN = ("voll", "voll, Fortsetzung verworfen", "voll, Zeitfilter nicht angewandt")
# Parameter, die von der Adresse der Fortsetzung bleiben (Wert nur Ziffern)
PARAMETER = ("page", "limit")
MAX_ZEILEN = 5000   # letzte Zeilen der Abrufstatistik (je Lauf vier bis fünf)
NACHT = sessionnet.SPERRE_GLEICHE_NACHT   # Zeilen bis 12 Stunden vor der jüngsten gelten als dieselbe Nacht
# Dokumentschritt (pipeline/dokumente.py: SCHLUESSEL, VERDACHT_NAECHTE, VERDACHT_PAUSE; hier ohne Import, denn das Modul
# lädt Geokodierung und Titelmaske; tests/test_abrufstand.py vergleicht die Werte)
DOKUMENTE = "dokumente"
DOKUMENTE_NAECHTE = 3
DOKUMENTE_PAUSE = timedelta(days=7)
ZAEHLER = (   # Schlüssel im Zustand, Text, Grenze der Nächte, Pause danach
    ("sperre_verdacht", "Nächte mit möglicher Sperre", sessionnet.SPERRE_NAECHTE, sessionnet.SPERRE_PAUSE),
    ("listenfehler", "Nächte mit fehlerhafter Liste", sessionnet.LISTENFEHLER_NAECHTE, sessionnet.LISTENFEHLER_PAUSE),
    ("tlsfehler", "Nächte mit Zertifikatsfehler", sessionnet.TLS_NAECHTE, sessionnet.TLS_PAUSE),
)


# --- Lesen (fehlertolerant, ohne Nebenwirkung) ---------------------------------------------------------------------

def json_lesen(pfad):
    """(Objekt, Zustand der Datei): „fehlt“, „unlesbar (…)“ oder „gelesen“; kein JSON-Objekt gilt als unlesbar."""
    try:
        text = Path(pfad).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, "fehlt"
    except (OSError, ValueError) as e:   # auch UnicodeDecodeError, Verzeichnis statt Datei
        return {}, f"unlesbar ({type(e).__name__})"
    try:
        wert = json.loads(text)
    except (ValueError, RecursionError):
        return {}, "unlesbar (kein JSON)"
    if not isinstance(wert, dict):
        return {}, "unlesbar (kein JSON-Objekt)"
    return wert, "gelesen"


def statistik_lesen(pfad):
    """(Zeilen als dict, Zustand der Datei); nur die letzten MAX_ZEILEN Zeilen. Ohne Spalte `liste` unlesbar."""
    try:
        with open(pfad, encoding="utf-8", newline="") as f:
            r = csv.DictReader(f, delimiter="\t")
            if not r.fieldnames:
                return [], "leer"
            if "liste" not in r.fieldnames:
                return [], "unlesbar (Kopf ohne Spalte liste)"
            zeilen = list(collections.deque(r, maxlen=MAX_ZEILEN))
    except FileNotFoundError:
        return [], "fehlt"
    except (OSError, ValueError, csv.Error) as e:
        return [], f"unlesbar ({type(e).__name__})"
    return zeilen, f"gelesen ({len(zeilen)} Zeilen)"


def zahl(wert):
    """Nicht negative ganze Zahl aus einer Zahl oder einem Text aus Ziffern; sonst None."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, int):
        return wert if wert >= 0 else None
    if isinstance(wert, str) and re.fullmatch(r"[0-9]{1,15}", wert.strip()):
        return int(wert.strip())
    return None


def zeit(wert):
    """Zeitpunkt mit Zone (wie sessionnet._zeit), sonst None."""
    return sessionnet._zeit(wert)


def wann(t):
    """Zeitpunkt in Ortszeit Köln, etwa „16.11.2026, 23:10 Uhr“; None: „unbekannt“; nicht darstellbar (etwa
    0001-01-01T00:00+14:00): „unlesbar“."""
    if t is None:
        return "unbekannt"
    try:
        return t.astimezone(abruf.ORTSZEIT).strftime("%d.%m.%Y, %H:%M Uhr")
    except (OverflowError, ValueError, OSError):
        return "unlesbar"


def tausend(n):
    """Zahl mit Punkt als Tausendertrennzeichen; None: „unbekannt“."""
    return f"{n:,}".replace(",", ".") if n is not None else "unbekannt"


def ergebnis_art(text):
    """Art des Ergebnisses einer Zeile (ERGEBNISSE), ohne den Text dahinter; sonst „unbekannt“ (leer: „leer“)."""
    t = (text or "").strip() if isinstance(text, str) else ""
    for art in ERGEBNISSE:
        if t == art or t.startswith((art + ":", art + ";", art + " ")):
            return art
    return "unbekannt" if t else "leer"


def modus(text):
    return text if text in MODI else ("unbekannt" if text else "leer")


def art_text(wert):
    """Art eines Abbruchs aus dem Zustand (vom Code gesetzt, etwa „sperre“ oder „obergrenze“); anderes: „unlesbar“."""
    return wert if isinstance(wert, str) and re.fullmatch(r"[a-zäöü_]{1,30}", wert) else "unlesbar"


def adresse(url):
    """Adresse der Fortsetzung ohne Geheimnisse: Schema, Host, Port und Pfad, aus dem Query-Teil nur PARAMETER mit
    Ziffern; ohne Zugangsdaten und Anker. (Adresse, Seitennummer); unlesbar: (None, None)."""
    if not isinstance(url, str) or not url.isascii() or len(url) > 4000:
        return None, None
    try:
        t = urllib.parse.urlsplit(url)
        host, port = t.hostname, t.port
    except ValueError:
        return None, None
    if t.scheme not in ("http", "https") or not host:
        return None, None
    netloc = (f"[{host}]" if ":" in host else host) + (f":{port}" if port is not None else "")
    teile, seite = [], None
    for teil in t.query.split("&") if t.query else []:
        k, _, v = teil.partition("=")
        if k in PARAMETER and re.fullmatch(r"[0-9]{1,9}", v):
            teile.append(f"{k}={v}")
            if k == "page":
                seite = int(v)
    pfad = urllib.parse.quote(urllib.parse.unquote(t.path), safe="/")
    return urllib.parse.urlunsplit((t.scheme, netloc, pfad, "&".join(teile), "")), seite


# --- Auswertung --------------------------------------------------------------------------------------------------

def letzte_nacht(zeilen):
    """Indizes der Zeilen der letzten Nacht mit Anfragen (lesbares `datum` höchstens NACHT vor der jüngsten Zeile) und
    ihr Beginn; ohne lesbares Datum (set(), None)."""
    mit_zeit = [(i, t) for i, z in enumerate(zeilen) if (t := zeit(z.get("datum"))) is not None]
    if not mit_zeit:
        return set(), None
    juengste = max(t for _, t in mit_zeit)
    nacht = [(i, t) for i, t in mit_zeit if timedelta(0) <= juengste - t < NACHT]
    return {i for i, _ in nacht}, min(t for _, t in nacht)


def ausgangswert(zeilen, vorher):
    """Objekte des laufenden Vollabrufs vor der letzten Nacht: aus der letzten Zeile „unterbrochen“ davor (nur sie
    speichert eine Fortsetzung, sessionnet._abruf_liste). Dazwischen dürfen Zeilen „abbruch“, „programmfehler“ oder
    „warnung“ derselben Fortsetzung liegen; eine Zeile, die von vorn begann (VON_VORN) oder mit „ok“ endete, beendet
    die Suche (None)."""
    for i in reversed(vorher):
        z = zeilen[i]
        art = ergebnis_art(z.get("ergebnis"))
        if art == "unterbrochen":
            return zahl(z.get("objekte"))
        if art == "ok" or z.get("modus") in VON_VORN:
            return None
    return None


def liste_auswerten(name, zeilen, nacht, zustand):
    """Kennzahlen einer Liste aus Abrufstatistik (Zeilen, Indizes der letzten Nacht) und Zustand."""
    eigene = [i for i, z in enumerate(zeilen) if z.get("liste") == name]
    in_nacht = [i for i in eigene if i in nacht]
    letzte = zeilen[eigene[-1]] if eigene else None
    r = {"liste": name, "anfragen_nacht": None, "objekte_nacht": None, "aenderungen": None, "seiten": None,
         "objekte_bisher": None, "status": "", "fortsetzung": None, "gespeichert": None, "gespeichert_am": None,
         "ergebnis": ergebnis_art(letzte.get("ergebnis")) if letzte else None,
         "modus": modus(letzte.get("modus")) if letzte else None, "vollabruf_laeuft": False,
         "ohne_zeitfilter": None, "zuletzt": zeit(zustand.get(name))}
    if in_nacht:
        werte = [zahl(zeilen[i].get("anfragen")) for i in in_nacht]
        r["anfragen_nacht"] = sum(w for w in werte if w is not None) if any(w is not None for w in werte) else None
        nacht_letzte = zeilen[in_nacht[-1]]
        vorher = [i for i in eigene if i < in_nacht[0]]
        objekte = zahl(nacht_letzte.get("objekte"))
        m, art = nacht_letzte.get("modus"), ergebnis_art(nacht_letzte.get("ergebnis"))
        if m == "voll, fortgesetzt":
            # Objekte der Fortsetzung zählen über die Nächte weiter: Zuwachs gegenüber der letzten Zeile vor dieser
            # Nacht; begann der Vollabruf erst in dieser Nacht (erste Zeile der Nacht ohne Fortsetzung), ab 0
            if zeilen[in_nacht[0]].get("modus") in VON_VORN:
                basis = 0
            else:
                basis = ausgangswert(zeilen, vorher)
            r["objekte_nacht"] = objekte - basis if objekte is not None and basis is not None and objekte >= basis \
                else None
        elif m == "inkrementell" and art == "ok":
            # `objekte` ist hier der zusammengeführte Stand; gelesen wurden die Änderungen
            r["aenderungen"] = tuple(zahl(nacht_letzte.get(k)) for k in ("neu", "geaendert", "geloescht"))
        elif m == "übersprungen" or art == "übersprungen":
            r["objekte_nacht"] = 0
        else:
            r["objekte_nacht"] = objekte
    if letzte:
        r["seiten"] = zahl(letzte.get("seiten"))
        if r["ergebnis"] == "unterbrochen":
            r["objekte_bisher"] = zahl(letzte.get("objekte"))
    gespeichert = [i for i in eigene if ergebnis_art(zeilen[i].get("ergebnis")) in ("ok", "übersprungen")]
    if gespeichert:
        z = zeilen[gespeichert[-1]]
        r["gespeichert"], r["gespeichert_am"] = zahl(z.get("objekte")), zeit(z.get("datum"))
    fort = zustand.get(f"{name}_fortsetzung")
    if fort is not None:
        r["vollabruf_laeuft"] = True
        if isinstance(fort, dict):
            url, seite = adresse(fort.get("naechste"))
            r["fortsetzung"] = {"seiten": zahl(fort.get("seiten")), "start": zeit(fort.get("start")),
                                "gespeichert": zeit(fort.get("gespeichert")), "adresse": url, "seite": seite}
            if r["fortsetzung"]["seiten"] is not None:
                r["seiten"] = r["fortsetzung"]["seiten"]
        else:
            r["fortsetzung"] = "unlesbar"
        r["status"] = "Vollabruf läuft"
    elif r["zuletzt"] is not None:
        r["status"] = "Vollabruf abgeschlossen"
    elif name in zustand:
        r["status"] = "Zeitpunkt des letzten Abrufs unlesbar"
    else:
        r["status"] = "noch kein vollständiger Abruf"
    vermerk = zustand.get(f"{name}_ohne_zeitfilter")
    if isinstance(vermerk, dict):
        r["ohne_zeitfilter"] = zeit(vermerk.get("zeit")) or "unbekannt"
    return r


def ende_der_nacht(zeilen, nacht, beginn, la):
    """Wie die letzte Nacht mit Anfragen endete, nur aus Zeitpunkten und Arten: Abbruch, wenn `letzter_abbruch.zuletzt`
    in dieser Nacht liegt (jeder Abbruch außer dem Ende des Zeitfensters setzt ihn, sessionnet.abrufen); sonst mit
    einer Zeile „unterbrochen“ das Ende des Zeitfensters; sonst nach den Arten der Zeilen."""
    if beginn is None:
        return "keine Nacht mit Anfragen in der Abrufstatistik"
    if isinstance(la, dict):
        t = zeit(la.get("zuletzt"))
        if t is not None and timedelta(0) <= t - beginn < NACHT:
            if la.get("art") == "obergrenze":
                return f"Obergrenze je Nacht erreicht ({wann(t)}); Fortsetzung in der nächsten Nacht"
            return f"Abbruch (Art {art_text(la.get('art'))}, {wann(t)})"
    arten = {ergebnis_art(zeilen[i].get("ergebnis")) for i in nacht}
    if "unterbrochen" in arten:
        return "Ende des Zeitfensters; Fortsetzung in der nächsten Nacht"
    for art, text in (("programmfehler", "Programmfehler"), ("abbruch", "Abbruch")):
        if art in arten:
            return text
    if arten == {"übersprungen"}:
        return "übersprungen (in dieser Nacht schon gelesen)"
    if arten and arten <= {"ok", "übersprungen", "warnung"}:
        return "vollständig" + (" (mit Warnung)" if "warnung" in arten else "")
    return "unbekannt"


def zaehler_auswerten(zustand, schluessel, grenze, pause, jetzt):
    """Zähler der Nächte und Pause wie sessionnet._pause_grund: (Nächte als Text, Pause als Text)."""
    v = zustand.get(schluessel)
    if not v:
        return f"0 von {grenze}", "keine Pause"
    if not isinstance(v, dict):
        return "unlesbar", "unlesbar (gilt beim nächsten Lauf als Pause)"
    n, zuletzt = v.get("naechte"), zeit(v.get("zuletzt"))
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:   # wie sessionnet._zaehler_pruefen: gilt als Grenze
        n = None
    teile = [f"{n} von {grenze}" if n is not None else f"unlesbar (gilt als {grenze})"]
    if zuletzt is not None:
        teile.append(f"zuletzt {wann(zuletzt)}")
    if v.get("art") is not None:
        teile.append(f"Art {art_text(v.get('art'))}")
    code = zahl(v.get("code"))
    if code is not None and 100 <= code <= 599:
        teile.append(f"HTTP {code}")
    if n is not None and n < grenze:
        return ", ".join(teile), "keine Pause"
    if zuletzt is None or zuletzt > jetzt:
        return ", ".join(teile), f"Pause von {pause.days} Tagen ab dem nächsten Lauf (Zeitpunkt unlesbar oder künftig)"
    bis = zuletzt + pause
    return ", ".join(teile), (f"Pause bis {wann(bis)}" if jetzt < bis else "Pause abgelaufen")


def dokumente_auswerten(zustand, zeilen, jetzt):
    """Dokumentschritt nur aus Zahlen und Zuständen: Eintrag `dokumente` im Zustand (Nacht und Zahl der darin
    angefragten Dateien, Zähler `verdacht` wie dokumente._pause) und letzte Zeile `dokumente` der Abrufstatistik
    (Zeitpunkt, Anfragen, Dateien mit Ergebnis, Art des Ergebnisses). Ohne beides None (noch kein Lauf mit Freigabe:
    ohne sie schreibt der Schritt nichts)."""
    eintrag = zustand.get(DOKUMENTE)
    eigene = [z for z in zeilen if z.get("liste") == DOKUMENTE]
    if eintrag is None and not eigene:
        return None
    d = {"nacht": "keine vermerkt", "verdacht": ("–", "–"), "zeile": None}
    if eintrag is not None and not isinstance(eintrag, dict):
        d["nacht"] = "unlesbar"
        d["verdacht"] = ("unlesbar", "unlesbar")
    elif isinstance(eintrag, dict):
        nacht, dateien = eintrag.get("nacht"), zahl(eintrag.get("dateien"))
        if "nacht" in eintrag or "dateien" in eintrag:
            # wie dokumente._eigener_zustand: unlesbar gilt in der Nacht des nächsten Laufs als ausgeschöpft
            lesbar = (isinstance(nacht, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", nacht)
                      and isinstance(eintrag.get("dateien"), int) and dateien is not None)
            # die Nacht ist nach dem Abend benannt, an dem sie beginnt (dokumente._nacht: 12 bis 12 Uhr Ortszeit)
            d["nacht"] = (f"{tausend(dateien)} in der Nacht vom {nacht[8:10]}.{nacht[5:7]}.{nacht[:4]}"
                          if lesbar else "unlesbar (gilt in der Nacht des nächsten Laufs als ausgeschöpft)")
        d["verdacht"] = zaehler_auswerten(eintrag, "verdacht", DOKUMENTE_NAECHTE, DOKUMENTE_PAUSE, jetzt)
    if eigene:
        z = eigene[-1]
        d["zeile"] = {"datum": zeit(z.get("datum")), "anfragen": zahl(z.get("anfragen")),
                      "objekte": zahl(z.get("objekte")), "ergebnis": ergebnis_art(z.get("ergebnis"))}
    return d


def restnaechte(gesamt, bisher, je_nacht):
    """Verbleibende Nächte eines Vollabrufs: ⌈(Gesamtzahl − bisher gelesen) / Objekte je Nacht⌉; ohne eine der Zahlen
    oder ohne Fortschritt je Nacht None."""
    if gesamt is None or bisher is None or not je_nacht:
        return None
    return math.ceil(max(gesamt - bisher, 0) / je_nacht)


def auswerten(zustand_pfad, stand_pfad, statistik_pfad, vorlagen_gesamt=None, jetzt=None):
    """Alles für die Ausgabe als dict (nur Zahlen, Zeitpunkte und Zustände)."""
    jetzt = jetzt or abruf.uhr()
    zustand, z_datei = json_lesen(zustand_pfad)
    stand, s_datei = json_lesen(stand_pfad)
    zeilen, t_datei = statistik_lesen(statistik_pfad)
    nacht, beginn = letzte_nacht(zeilen)
    listen = {name: liste_auswerten(name, zeilen, nacht, zustand) for name in LISTEN}
    dokumente = dokumente_auswerten(zustand, zeilen, jetzt)
    a = {"dateien": {Path(zustand_pfad).name: z_datei, Path(stand_pfad).name: s_datei,
                     Path(statistik_pfad).name: t_datei},
         "nacht_beginn": beginn, "nacht_anfragen": None, "listen": listen, "jetzt": jetzt, "dokumente": dokumente}
    werte = [zahl(zeilen[i].get("anfragen")) for i in sorted(nacht)]
    if any(w is not None for w in werte):
        a["nacht_anfragen"] = sum(w for w in werte if w is not None)
    a["zaehler"] = [(text, *zaehler_auswerten(zustand, s, grenze, pause, jetzt))
                    for s, text, grenze, pause in ZAEHLER]
    nv = zustand.get("nicht_vor")
    t = zeit(nv)
    grenze = jetzt + abruf.RETRY_AFTER_HOECHSTENS   # wie sessionnet: weiter in der Zukunft gilt als 30 Tage
    a["nicht_vor"] = ("keiner" if nv is None else "unlesbar (gilt beim nächsten Lauf als 7 Tage)" if t is None
                      else f"kein Abruf vor {wann(grenze)} (gespeichert weiter in der Zukunft, gilt als "
                           f"{abruf.RETRY_AFTER_HOECHSTENS.days} Tage)" if t > grenze
                      else f"kein Abruf vor {wann(t)}" if t > jetzt else "abgelaufen")
    la = zustand.get("letzter_abbruch")
    a["ende_nacht"] = ende_der_nacht(zeilen, nacht, beginn, la)
    if not la:
        a["letzter_abbruch"] = "keiner vermerkt (seit dem letzten vollständigen Lauf oder nur Ende des Zeitfensters)"
    elif not isinstance(la, dict):
        a["letzter_abbruch"] = "unlesbar"
    else:
        code = zahl(la.get("code"))
        a["letzter_abbruch"] = (f"Art {art_text(la.get('art'))}" + (f", HTTP {code}" if code and 100 <= code <= 599
                                                                    else "") + f", {wann(zeit(la.get('zuletzt')))}")
    ok = stand.get("abruf_ok")
    a["abruf_ok"] = ("nein (noch kein vollständiger Lauf)" if ok is None else
                     f"ja, letzter vollständiger Lauf {wann(zeit(ok))}" if zeit(ok) else "unlesbar")
    a["meldungen"] = []   # nur, dass es sie gibt, und wann; der Text bleibt in STAND.json
    for k in ("abruf_fehler", "abruf_hinweis"):
        if isinstance(stand.get(k), dict):
            a["meldungen"].append(f"{k} ({wann(zeit(stand[k].get('zeit')))})")
        elif stand.get(k) is not None:
            a["meldungen"].append(f"{k} (unlesbar)")
    warnungen = stand.get("abruf_warnungen")
    if isinstance(warnungen, dict):
        for liste in LISTEN:
            if isinstance(warnungen.get(liste), dict):
                a["meldungen"].append(f"abruf_warnungen.{liste} ({wann(zeit(warnungen[liste].get('zeit')))})")
    # übersprungener Lauf nach der letzten Nacht mit Anfragen (etwa Pause, 12-Stunden-Regel, außerhalb des Fensters)
    a["uebersprungen"] = None
    u = stand.get("abruf_uebersprungen")
    if isinstance(u, dict):
        t = zeit(u.get("zeit"))
        letzte = max((zeit(z.get("datum")) for z in zeilen if zeit(z.get("datum"))), default=None)
        if t is not None and (letzte is None or t > letzte):
            grund = " ".join(u["grund"].split()) if isinstance(u.get("grund"), str) else "Grund unlesbar"
            a["uebersprungen"] = f"{wann(t)}: {grund[:300]}"
    # verbleibende Nächte (Vorlagen)
    p = listen["papers"]
    je_nacht = p["objekte_nacht"]
    if not p["vollabruf_laeuft"] and p["status"] == "Vollabruf abgeschlossen":
        a["rest"] = "keine (Vollabruf der Vorlagen abgeschlossen)"
    elif vorlagen_gesamt is None:
        a["rest"] = ("unbekannt: Gesamtzahl der Vorlagen nicht bekannt (die Kölner API nennt in pagination keine, "
                     "der Abruf speichert keine)" + (f"; in der letzten Nacht {tausend(je_nacht)} Vorlagen gelesen"
                                                    if je_nacht else ""))
    else:
        n = restnaechte(vorlagen_gesamt, p["objekte_bisher"], je_nacht)
        a["rest"] = (f"etwa {n} bei {tausend(vorlagen_gesamt)} Vorlagen insgesamt (angegeben) und "
                     f"{tausend(je_nacht)} je Nacht wie in der letzten" if n is not None else
                     f"unbekannt: bei {tausend(vorlagen_gesamt)} Vorlagen insgesamt (angegeben) fehlt der Stand des "
                     "laufenden Vollabrufs oder der Fortschritt der letzten Nacht")
    return a


# --- Ausgabe -----------------------------------------------------------------------------------------------------

def _nacht_objekte(r):
    if r["aenderungen"] is not None:
        neu, geaendert, geloescht = (tausend(x) for x in r["aenderungen"])
        return f"neu {neu}, geändert {geaendert}, gelöscht {geloescht}"
    return tausend(r["objekte_nacht"]) if r["objekte_nacht"] is not None else "unbekannt"


def _fortsetzung_text(r, markdown=False):
    f = r["fortsetzung"]
    if f is None:
        return "–"
    if f == "unlesbar":
        return "unlesbar"
    url = f["adresse"]
    if url and markdown:
        url = "`" + url.replace("`", "%60") + "`"
    seite = f"Seite {f['seite']}" if f["seite"] is not None else "Seite unbekannt"
    return (f"{seite} ({url or 'Adresse unlesbar'}), gespeichert {wann(f['gespeichert'])}, Vollabruf begonnen "
            f"{wann(f['start'])}")


def _dokumente_zeilen(d):
    """Angaben zum Dokumentschritt (ohne Überschrift), je eine Zeile."""
    if d is None:
        return ["noch kein Lauf mit Freigabe (kein Eintrag im Zustand, keine Zeile in der Abrufstatistik)"]
    out = [f"angefragte Dateien: {d['nacht']}"]
    z = d["zeile"]
    if z is None:
        out.append("letzte Zeile der Abrufstatistik: keine")
    else:
        out.append(f"letzte Zeile der Abrufstatistik: {wann(z['datum'])}, Anfragen {tausend(z['anfragen'])}, Dateien "
                   f"mit Ergebnis {tausend(z['objekte'])}, Ergebnis {z['ergebnis']}")
    naechte, pause = d["verdacht"]
    out.append(f"Nächte mit möglicher Sperre beim Dokumentabruf: {naechte}; {pause}")
    return out


DOKUMENTE_TITEL = "Dokumente (PDF-Köpfe; Stand vor dem Dokumentschritt dieses Laufs)"


def zeilen_text(a):
    """Ausgabe für das Log (Klartext, eine Angabe je Zeile)."""
    out = ["Abrufstand (nur Zahlen und Zustände, keine Inhalte der Objekte)",
           "Dateien: " + "; ".join(f"{k} {v}" for k, v in a["dateien"].items())]
    if a["nacht_beginn"] is None:
        out.append("Letzte Nacht mit Anfragen: keine in der Abrufstatistik")
    else:
        out.append(f"Letzte Nacht mit Anfragen: ab {wann(a['nacht_beginn'])}; Anfragen insgesamt "
                   f"{tausend(a['nacht_anfragen'])}")
    out.append(f"Ende der letzten Nacht: {a['ende_nacht']}")
    if a["uebersprungen"]:
        out.append(f"Danach übersprungen: {a['uebersprungen']}")
    for name in LISTEN:
        r = a["listen"][name]
        out.append(f"{NAME[name]} ({name}): {r['status']}")
        if r["anfragen_nacht"] is None:
            out.append("  letzte Nacht: keine Anfragen")
        else:
            out.append(f"  letzte Nacht: Anfragen {tausend(r['anfragen_nacht'])}, Objekte {_nacht_objekte(r)}")
        if r["vollabruf_laeuft"]:
            out.append(f"  Seiten bisher: {tausend(r['seiten'])}; Objekte im laufenden Vollabruf: "
                       f"{tausend(r['objekte_bisher'])}")
        else:
            # die Spalte `seiten` zählt über alle Nächte, die Seite an der Nahtstelle jeder Fortsetzung doppelt
            bezeichnung = ("Seitenabrufe im Vollabruf insgesamt" if r["modus"] == "voll, fortgesetzt"
                           else "Seiten im letzten Lauf")
            out.append(f"  {bezeichnung}: {tausend(r['seiten']) if r['ergebnis'] else '–'}")
        out.append(f"  Fortsetzung: {_fortsetzung_text(r)}")
        out.append("  gespeicherter Stand: " + (f"{tausend(r['gespeichert'])} Objekte ({wann(r['gespeichert_am'])})"
                                               if r["gespeichert_am"] or r["gespeichert"] is not None else "keiner"))
        if r["ergebnis"]:
            out.append(f"  letzte Zeile der Abrufstatistik: {r['ergebnis']} (Modus {r['modus']})")
        if r["ohne_zeitfilter"]:
            zeitpunkt = r["ohne_zeitfilter"] if isinstance(r["ohne_zeitfilter"], str) else wann(r["ohne_zeitfilter"])
            out.append(f"  Zeitfilter zuletzt nicht angewandt: {zeitpunkt}")
    out.append(f"Verbleibende Nächte (Vorlagen): {a['rest']}")
    for text, naechte, pause in a["zaehler"]:
        out.append(f"{text}: {naechte}; {pause}")
    out.append(f"{DOKUMENTE_TITEL}:")
    out += [f"  {z}" for z in _dokumente_zeilen(a["dokumente"])]
    out.append(f"Retry-After: {a['nicht_vor']}")
    out.append(f"Letzter Abbruch: {a['letzter_abbruch']}")
    out.append(f"abruf_ok: {a['abruf_ok']}")
    out.append("Meldungen in STAND.json (Text dort): " + (", ".join(a["meldungen"]) or "keine"))
    return out


def markdown(a):
    """Ausgabe für $GITHUB_STEP_SUMMARY."""
    zeilen = ["### Abrufstand", "",
              "Nur Zahlen und Zustände aus `zustand_abruf.json`, `STAND.json` und `abrufstatistik.tsv`; keine Inhalte "
              "der Objekte.", ""]
    if a["nacht_beginn"] is None:
        zeilen.append("Letzte Nacht mit Anfragen: keine in der Abrufstatistik.")
    else:
        zeilen.append(f"Letzte Nacht mit Anfragen: ab {wann(a['nacht_beginn'])}; Anfragen insgesamt "
                      f"{tausend(a['nacht_anfragen'])}.")
    zeilen.append(f"Ende der letzten Nacht: {a['ende_nacht']}.")
    if a["uebersprungen"]:
        zeilen.append(f"Danach übersprungen: {a['uebersprungen'].replace('|', '/')}.")
    zeilen += ["", "| Liste | Stand | Anfragen (letzte Nacht) | Objekte (letzte Nacht) | "
                   "Seiten (Vollabruf: Abrufe bisher bzw. insgesamt, sonst letzter Lauf) | Objekte im Vollabruf | Fortsetzung | "
                   "gespeicherter Stand |",
               "|---|---|---:|---:|---:|---:|---|---|"]
    for name in LISTEN:
        r = a["listen"][name]
        nacht = r["anfragen_nacht"] is not None
        gespeichert = (f"{tausend(r['gespeichert'])} ({wann(r['gespeichert_am'])})"
                       if r["gespeichert_am"] or r["gespeichert"] is not None else "keiner")
        zeilen.append(" | ".join([
            f"| {NAME[name]} (`{name}`)", r["status"], tausend(r["anfragen_nacht"]) if nacht else "–",
            _nacht_objekte(r) if nacht else "–",
            tausend(r["seiten"]) if r["ergebnis"] or r["vollabruf_laeuft"] else "–",
            tausend(r["objekte_bisher"]) if r["vollabruf_laeuft"] else "–",
            _fortsetzung_text(r, markdown=True), gespeichert]) + " |")
    zeilen += ["", f"- Verbleibende Nächte (Vorlagen): {a['rest']}"]
    zeilen += [f"- {text}: {naechte}; {pause}" for text, naechte, pause in a["zaehler"]]
    zeilen += [f"- {DOKUMENTE_TITEL}: " + "; ".join(_dokumente_zeilen(a["dokumente"]))]
    zeilen += [f"- Retry-After: {a['nicht_vor']}", f"- Letzter Abbruch: {a['letzter_abbruch']}",
               f"- `abruf_ok`: {a['abruf_ok']}",
               "- Meldungen in `STAND.json` (Text dort): " + (", ".join(a["meldungen"]) or "keine"),
               "- Dateien: " + "; ".join(f"`{k}` {v}" for k, v in a["dateien"].items()), ""]
    return "\n".join(zeilen)


def main(argv=None):
    p = argparse.ArgumentParser(description="Fortschritt des Abrufs (nur Zahlen und Zustände)")
    p.add_argument("--zustand", help="zustand_abruf.json (Vorgabe aus pipeline/config.py)")
    p.add_argument("--stand", help="STAND.json (Vorgabe aus pipeline/config.py)")
    p.add_argument("--statistik", help="abrufstatistik.tsv (Vorgabe aus pipeline/config.py)")
    p.add_argument("--vorlagen-gesamt", default=None,
                   help="Gesamtzahl der Vorlagen, falls bekannt (etwa von der Stadt); sonst „unbekannt“")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:   # --help (0) oder unbekannte Angaben: Hinweis von argparse, der Lauf geht weiter
        if e.code:
            print("::warning::Abrufstand: Aufruf unlesbar, nichts ausgegeben", flush=True)
        return 0
    try:
        gesamt = zahl(args.vorlagen_gesamt) if args.vorlagen_gesamt is not None else None
        if args.vorlagen_gesamt is not None and gesamt is None:
            print("Hinweis: --vorlagen-gesamt ist keine nicht negative ganze Zahl und bleibt unberücksichtigt",
                  flush=True)
        a = auswerten(args.zustand or config.ZUSTAND, args.stand or config.STAND,
                      args.statistik or config.ABRUFSTATISTIK, gesamt)
        print("\n".join(zeilen_text(a)), flush=True)
        ziel = os.environ.get("GITHUB_STEP_SUMMARY")
        if ziel:
            try:
                with open(ziel, "a", encoding="utf-8") as f:
                    f.write(markdown(a) + "\n")
            except OSError as e:
                print(f"::warning::Zusammenfassung nicht geschrieben ({type(e).__name__})", flush=True)
    except Exception as e:   # nie den Lauf anhalten; kein Text des Fehlers (er könnte Inhalte tragen)
        print(f"::warning::Abrufstand nicht ermittelt ({type(e).__name__})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
