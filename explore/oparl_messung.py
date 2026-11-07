"""Messung der Kölner OParl-API (Phase 1) – nur gestuft nach explore/STUFEN.md, jede Stufe erst nach Freigabe.

Aufruf (Reihenfolge und genaue Befehle mit Obergrenzen: explore/STUFEN.md):
  ... python3 explore/oparl_messung.py test        (genau 3 Anfragen: System, Body, erste Seite der Vorlagen)
  ... python3 explore/oparl_messung.py kennzahlen  (10 Anfragen)
  ... python3 explore/oparl_messung.py organisationen [--seiten 4]
  ... python3 explore/oparl_messung.py stichprobe [--seiten 3] [--von 2019] [--bis 2026]
  ... python3 explore/oparl_messung.py sitzungen [--seiten 2]
  ... python3 explore/oparl_messung.py pdf-koepfe [--anzahl 100]
Jede Liste hat eine Seitengrenze (--seiten, Vorgabe je Kommando; 0 = ohne Grenze, nur ausdrücklich).
Ohne RATSATLAS_STADT_INFORMIERT=ja bricht jedes Kommando vor der ersten Anfrage an die Stadt ab (Entscheidung
04.11.2026); lokale Testserver (http://127.0.0.1, http://localhost) sind ausgenommen (explore/testserver.py).
Anfragen an die Stadt nur im Zeitfenster 23–1 Uhr Ortszeit (RATSATLAS_ZEITFENSTER, wie pipeline/abruf.py), geprüft vor
jeder Anfrage. `pdf-koepfe` lädt PDFs und läuft zusätzlich nur mit RATSATLAS_PDF_FREIGEGEBEN=ja (laut mandari ist der
automatische PDF-Abruf mit Köln so nicht vereinbart; Frage in der Anfrage an die Stadt).
Für Anfragen an die Stadt gelten strenge Vorgaben (sichere_vorgaben): keine Wiederholung nach 429/5xx
(RATSATLAS_WIEDERHOLUNGEN, Vorgabe 0), höchstens 5 s je Antwort (RATSATLAS_MAX_DAUER, Vorgabe 5), mindestens 2 s Abstand
zwischen zwei Anfragen (RATSATLAS_ABSTAND, Vorgabe 2); RATSATLAS_MAX_ANFRAGEN und RATSATLAS_KONTAKT (ohne Platzhalter)
sind Pflicht. Lockerere Werte werden vor der ersten Anfrage abgelehnt.
Parameter werden ohne URL-Kodierung angehängt (SessionNet: 404 bei %3A/%2B); `kennzahlen` prüft beide Formen einmal.
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
sein (explore/STUFEN.md, Stufe 1). Meldet der Proxy 502/504 (Stadt nicht erreicht), gilt das als mögliche Sperre
(Art `sperre`), 429/503 als Art `server`.
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
SEITEN_VORGABE = {"stichprobe": 3, "organisationen": 4, "sitzungen": 2}
# Antworten, die in den Parametertests von `kennzahlen` als „Parameter abgelehnt“ gelten (kein Abbruch)
ABGELEHNT = (400, 401, 404)
# strenge Vorgaben für Anfragen an die Stadt (explore/STUFEN.md, Abbruchkriterien)
STRENG_DAUER = 5.0
STRENG_ABSTAND = 2.0   # Sekunden vom Ende einer Antwort bis zur nächsten Anfrage (CLAUDE.md 5.1)
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
    ausgenommen."""
    if not lokal(url):
        if os.environ.get("RATSATLAS_STADT_INFORMIERT") != "ja":
            raise Abbruch(f"Die Stadt Köln ist nicht informiert (RATSATLAS_STADT_INFORMIERT): {url}", "gesperrt")
        if not im_zeitfenster():
            raise Abbruch(f"außerhalb des Zeitfensters (RATSATLAS_ZEITFENSTER): {url}", "zeitfenster")
        if not _streng_aktiv():
            raise Abbruch(f"strenge Vorgaben nicht aktiv (Wiederholungen 0, höchstens {STRENG_DAUER:g} s, Abstand "
                          f"mindestens {STRENG_ABSTAND:g} s, Obergrenze, Kontakt): {url}", "gesperrt")
        if endung == ".pdf" and os.environ.get("RATSATLAS_PDF_FREIGEGEBEN") != "ja":
            raise Abbruch(f"PDF-Abruf nicht freigegeben (RATSATLAS_PDF_FREIGEGEBEN): {url}", "gesperrt")
    return hole(url, endung)


def _mit_parametern(url, **params):
    if params:   # ohne URL-Kodierung, wie pipeline/sessionnet.py
        url += ("&" if "?" in url else "?") + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def _json(url, **params):
    return json.loads(_hole(_mit_parametern(url, **params)))


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
    """Folgt links.next und liefert (seite_nr, antwort). Endet am Ende der Liste, an der Seitengrenze, bei einer
    schon besuchten Folgeadresse oder bei einer Seite ohne neue Kennungen (Schleifenschutz wie pipeline/sessionnet.py).
    Das Ende wird in _LISTEN vermerkt („abgebrochen“, solange es nicht erreicht ist)."""
    start = _mit_parametern(url, **params)
    eintrag = {"liste": name, "url": start, "grenze": max_seiten or "", "seiten": 0, "objekte": 0,
               "ende": "abgebrochen", "erstes_next": ""}
    _LISTEN.append(eintrag)
    besucht, kennungen = {start}, set()
    seite, nr = json.loads(_hole(start)), 1
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
        if nxt in besucht:
            eintrag["ende"] = "links.next wiederholt"
            return
        besucht.add(nxt)
        seite, nr = json.loads(_hole(nxt)), nr + 1


def _liste_kennwerte(objekt, antwort):
    pag, links = antwort.get("pagination") or {}, antwort.get("links") or {}
    zeilen = [{"objekt": objekt, "feld": f"pagination.{k}", "wert": pag.get(k)}
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


def _filter_wirksam(objekte, feld, von=None, bis=None):
    """Hält die Antwort den Zeitfilter ein? ja/nein/keine Objekte (ohne weitere Anfrage)."""
    if not objekte:
        return "keine Objekte"
    zeiten = [_zeitpunkt(o[feld]) for o in objekte if o.get(feld)]
    ausser = [t for t in zeiten if t and ((von and t < von) or (bis and t > bis))]
    unlesbar = sum(1 for t in zeiten if t is None)
    zusatz = f", {unlesbar} unlesbar" if unlesbar else ""
    return (f"nein ({len(ausser)} von {len(zeiten)} außerhalb{zusatz})" if ausser else
            f"ja{f' ({unlesbar} unlesbar)' if unlesbar else ''}")


def kennzahlen(_):
    """10 Anfragen: System, Body, erste Seite von paper/meeting/organization/person, vier Parametertests."""
    zeilen = []
    try:
        system, body = _json(SYSTEM), _json(BODY)
        zeilen += [{"objekt": "system", "feld": k, "wert": _wert(system.get(k))[:200]}
                   for k in ("oparlVersion", "name", "vendor", "product", "license", "website", "contactEmail")]
        zeilen += [{"objekt": "body", "feld": k, "wert": _wert(body.get(k))[:200]}
                   for k in ("name", "license", "licenseValidSince", "oparlSince", "contactEmail", "contactName",
                             "legislativeTerm", "modified")]
        vor7 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).replace(microsecond=0)
        seit = vor7.isoformat()     # „+00:00“ wie pipeline/sessionnet.py
        jahr_von = dt.datetime.fromisoformat("2025-01-01T00:00:00+01:00")
        jahr_bis = dt.datetime.fromisoformat("2025-12-31T23:59:59+01:00")
        for name in ("paper", "meeting", "organization", "person"):
            url = body.get(name)
            if not url:
                zeilen.append({"objekt": name, "feld": "url", "wert": "fehlt im Body"})
                continue
            basis = _json(url)
            zeilen.append({"objekt": name, "feld": "url", "wert": url})
            zeilen += _liste_kennwerte(name, basis)
            if name != "paper":
                continue
            # Verhalten von limit und den Zeitfiltern (OParl 1.1: created_since/_until, modified_since/_until);
            # eine Anfrage mit URL-kodiertem Zeitstempel zum Vergleich (bei SessionNet anderswo HTTP 404)
            tests = [("test modified_since URL-kodiert",
                      url + ("&" if "?" in url else "?") + urllib.parse.urlencode({"modified_since": seit}),
                      ("modified", vor7, None)),
                     ("test limit=100", _mit_parametern(url, limit=100), None),
                     (f"test modified_since={seit}", _mit_parametern(url, modified_since=seit), ("modified", vor7, None)),
                     ("test created_since=2025-01-01T00:00:00+01:00&created_until=2025-12-31T23:59:59+01:00",
                      _mit_parametern(url, created_since="2025-01-01T00:00:00+01:00",
                                      created_until="2025-12-31T23:59:59+01:00"), ("created", jahr_von, jahr_bis))]
            for feld, adresse, pruefung in tests:
                try:
                    a = json.loads(_hole(adresse))
                except Abbruch as e:
                    if e.art == "http" and e.code in ABGELEHNT:   # Parameter abgelehnt; Messung geht weiter
                        zeilen.append({"objekt": name, "feld": feld, "wert": str(e)})
                        continue
                    raise
                daten = a.get("data") or []
                wert = f"objekte={len(daten)}; totalElements={(a.get('pagination') or {}).get('totalElements')}"
                if pruefung:
                    wert += f"; filter_wirksam={_filter_wirksam(daten, *pruefung)}"
                zeilen.append({"objekt": name, "feld": feld, "wert": wert})
    except Abbruch as e:
        zeilen.append({"objekt": "lauf", "feld": "abbruch", "wert": str(e)})
        raise
    finally:
        _schreibe("oparl_kennzahlen.tsv", zeilen)


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
    """Je Jahr die ersten Seiten der Vorlagenliste mit created_since/created_until. Doppelungen werden getrennt
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
                                     created_until=bis):
                tot = (seite.get("pagination") or {}).get("totalElements") if nr == 1 else tot
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


KOMMANDOS = {"test": test, "kennzahlen": kennzahlen, "organisationen": organisationen, "stichprobe": stichprobe,
             "sitzungen": sitzungen, "pdf-koepfe": pdf_koepfe}
LAEUFE_SPALTEN = ["lauf", "stufe", "kommando", "parameter", "start", "ende", "dauer_s", "netz", "cache",
                  "obergrenze", "protokoll_von", "protokoll_bis", "ergebnis", "meldung"]
LISTEN_SPALTEN = ["lauf", "liste", "grenze", "seiten", "objekte", "ende", "erstes_next", "url"]


def _parameter(a):
    if a.kommando in ("organisationen", "sitzungen"):
        return f"--seiten {a.seiten}"
    if a.kommando == "stichprobe":
        return f"--seiten {a.seiten} --von {a.von} --bis {a.bis}"
    return f"--anzahl {a.anzahl}" if a.kommando == "pdf-koepfe" else ""


def _laufnummer():
    datei = ERG / "oparl_laeufe.tsv"
    if not datei.exists():
        return 1
    with datei.open(encoding="utf-8") as f:
        return max(sum(1 for _ in f), 1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("kommando", choices=list(KOMMANDOS))
    ap.add_argument("--seiten", type=int, default=None,
                    help="Seiten je Jahr (stichprobe, Vorgabe 3) bzw. insgesamt (organisationen 4, sitzungen 2); "
                         "0 = ohne Seitengrenze")
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
        abruf.WIEDERHOLUNGEN, abruf.MAX_DAUER = werte["wiederholungen"], werte["max_dauer"]
        abruf.ABSTAND = werte["abstand"]

    zeitzone = ZoneInfo("Europe/Berlin")
    lauf = {"lauf": _laufnummer(), "stufe": os.environ.get("RATSATLAS_STUFE", ""), "kommando": a.kommando,
            "parameter": _parameter(a), "start": dt.datetime.now(zeitzone).isoformat(timespec="seconds"),
            "obergrenze": abruf.MAX_ANFRAGEN or "", "protokoll_von": abruf.protokollzeilen(),
            "ergebnis": "ok", "meldung": ""}
    rueckgabe = 0
    try:
        KOMMANDOS[a.kommando](a)
    except Abbruch as e:
        lauf["ergebnis"], lauf["meldung"], rueckgabe = f"abbruch ({e.art or 'sonstiges'})", str(e), 2
        if e.art == "proxy":   # Ablehnung in der Arbeitsumgebung, nicht durch die Stadt
            hinweis = (f"Der Proxy der Arbeitsumgebung hat die Verbindung abgelehnt; keine Anfrage hat die Stadt "
                       f"erreicht, kein Hinweis auf eine Sperre. Nicht wiederholen, sondern berichten: Der Host "
                       f"{urllib.parse.urlsplit(SYSTEM).hostname} muss im Netz der Arbeitsumgebung erlaubt sein "
                       f"(explore/STUFEN.md, Stufe 1).")
        elif e.art == "sperre":   # auch CONNECT-Antwort 502/504: der Proxy hat die Stadt angefragt, aber nicht erreicht
            hinweis = ("Mögliche Sperre: in dieser Nacht keine weitere Anfrage, alle Abrufe ruhen bis zur Klärung mit "
                       "der Stadt. Stoppen und berichten (explore/STUFEN.md).")
        else:
            hinweis = "Stoppen und berichten (explore/STUFEN.md)."
        print(f"Abbruch: {e}\n{hinweis}", file=sys.stderr)
    except KeyboardInterrupt:
        lauf["ergebnis"], rueckgabe = "unterbrochen", 130
    except Exception as e:   # z. B. HTML statt JSON: ebenfalls stoppen und berichten
        lauf["ergebnis"], lauf["meldung"], rueckgabe = f"fehler ({type(e).__name__})", str(e)[:300], 1
        print(f"Fehler: {type(e).__name__}: {e}\nStoppen und berichten (explore/STUFEN.md).", file=sys.stderr)
    finally:
        ende = dt.datetime.now(zeitzone)
        lauf.update(abruf.zaehler(), ende=ende.isoformat(timespec="seconds"),
                    dauer_s=f"{(ende - dt.datetime.fromisoformat(lauf['start'])).total_seconds():.0f}",
                    protokoll_bis=abruf.protokollzeilen())
        _anhaengen("oparl_laeufe.tsv", LAEUFE_SPALTEN, [lauf])
        _anhaengen("oparl_listen.tsv", LISTEN_SPALTEN, [{**e, "lauf": lauf["lauf"]} for e in _LISTEN])
        print(f"Lauf {lauf['lauf']}: {lauf['netz']} Anfragen ans Netz, {lauf['cache']} aus dem Cache; "
              f"{lauf['ergebnis']}", file=sys.stderr)
    return rueckgabe


if __name__ == "__main__":
    sys.exit(main())
