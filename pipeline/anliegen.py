"""Archiv der Anliegen aus „Sag’s uns“ (Anliegenmanagement der Stadt Köln; Zusatzthema „anliegen“, abgeschaltet;
vorbereitet am 16.11.2026 ohne Abruf).

Quelle (Datensatzseite geprüft am 16.11.2026): „Sags uns Anliegenmanagement Köln“,
https://www.offenedaten-koeln.de/dataset/sags-uns-anliegenmanagement-koeln, Lizenz dl-de/zero 2.0. Schnittstelle
Open311 GeoReport v2: https://sags-uns.stadt-koeln.de/georeport/v2/requests.json (Parameter start_date); daneben eine
GeoJSON-Datei (`GEOJSON`), die dieser Adapter nicht nutzt (Feldnamen ohne Standard, ungeprüft).

Ungeprüft, weil bis zur Freigabe keine Anfrage gestellt wird: ob Köln die Felder der Spezifikation so liefert, ob die
Zeitfilter wirken, ob die Schnittstelle Ergebnisse kürzt (die Spezifikation kennt keine Seiten), die Form der Nummern
und die Kategorien. Der Adapter fragt deshalb nur mit den Parametern der Spezifikation (start_date, end_date) je
Kalendermonat und prüft jede Antwort, bevor er etwas schreibt (`schema_pruefen`): Liste von Objekten, Pflichtfelder der
Spezifikation (`PFLICHT`, Kategorie über service_code oder service_name), Status `open` oder `closed`, Zeitpunkt lesbar
und im angefragten Monat (sonst wirkt der Zeitfilter nicht), mindestens eine Meldung im letzten abgeschlossenen Monat,
keine übliche Obergrenze als Zahl (Verdacht auf Kürzung, solange `OBERGRENZE_ANTWORT` ungeprüft ist). Danach prüft
`lauf_pruefen` die Monate des Laufs zusammen (nicht alle leer, nicht dieselbe Höchstzahl in mehreren Monaten). Passt
etwas nicht, endet der Lauf mit `dienste.Schemafehler`, und es wird nichts geschrieben.

Welche Monate ein Lauf abfragt, bestimmt `plan` (neuester zuerst): jeden Monat der letzten FENSTER Tage und jeden Monat
ab dem Beginn des Archivs (beim ersten Lauf festgehalten: heute − ERSTER_ABRUF_TAGE), der noch nie geprüft wurde
(STAND.json `erstabruf_ab`, `monate_geprueft`, `monate_offen`). Ein Abbruch oder eine gestufte Sichtung hinterlässt so
keine dauerhafte Lücke: Folgeläufe holen die fehlenden Monate nach.

Gespeichert wird je Meldung nur Nummer, Tag, Kategorie (Code und Name), Gruppe, Stadtteil, Stadtbezirk und Status
(Entscheidung 16.11.2026, wie in Bonn am 27.10.2026): nie Beschreibung, Statustext, Foto, Adresse oder Koordinate (in
den Texten können Namen, Kennzeichen und Hausnummern stehen). Die Koordinate (lat, long) dient nur der Zuordnung zu
Stadtteil und Stadtbezirk (Punkt in Fläche, data/geo) und wird danach verworfen. Meldungen sind Hinweise der
Einwohnerschaft an die Verwaltung, keine Ratsvorlagen.

Dateien in `config.BAUSTELLEN_ARCHIV`/anliegen (Branch `archiv`, Workflow `.github/workflows-inaktiv/baustellen.yml`):
- meldungen.tsv – je Meldung die Spalten in KOPF, mit erstem und letztem Auftreten in der Liste
- abrufe.tsv – je Lauf und Monat: erhalten, neu, Status geändert, Fehler
- anfragen.tsv – Anfragen je Lauf (Zeit, Adresse, Status, Bytes, Sekunden)
- STAND.json – letzter Lauf, Beginn des Archivs (`erstabruf_ab`), geprüfte und noch offene Monate
"""
import json
import os
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import abruf, config, dienste

THEMA = "anliegen"
URL = "https://sags-uns.stadt-koeln.de/georeport/v2/requests.json"
GEOJSON = "https://sags-uns.stadt-koeln.de/sites/default/files/geojson/reports.json"   # nicht genutzt
DATENSATZ = "https://www.offenedaten-koeln.de/dataset/sags-uns-anliegenmanagement-koeln"
TITEL = "Sags uns Anliegenmanagement Köln"   # Titel des Datensatzes im Katalog
ERSTER_ABRUF_TAGE = 365   # Beginn des Archivs: Monat von heute − 365 Tagen beim ersten Lauf (13 Monate)
FENSTER = 120             # jeder Lauf: die Monate ab heute − 120 Tagen erneut (Status, Nachzügler; 5 Anfragen)
# höchstens Anfragen je Lauf; ANLIEGEN_MAX_ANFRAGEN kann sie nur senken (gestufte erste Sichtung: 1 = der laufende
# Monat, 2 = dazu der letzte abgeschlossene; dann Abbruch der Art `obergrenze`, die geprüften Monate werden geschrieben
# und die übrigen in den Folgeläufen nachgeholt)
MAX_ANFRAGEN = 14
# Kürzung je Antwort (ungeprüft; die Spezifikation kennt keine Seiten). None: ungeprüft – dann gelten genau eine
# übliche Obergrenze (dienste.TYPISCHE_OBERGRENZEN) in einem Monat und dieselbe Höchstzahl (ab GLEICH_AB) in mehreren
# Monaten als Verdacht, und der Lauf schreibt nichts. Nach der Klärung (Abgleich mit der GeoJSON-Datei oder Rückfrage
# bei der Stadt) eintragen: 0 = die Schnittstelle kürzt nicht; n = höchstens n Meldungen je Antwort (jede Antwort ab n
# gilt dann als gekürzt).
OBERGRENZE_ANTWORT = None
GLEICH_AB = 10


def grenze():
    """Anfragen je Lauf: MAX_ANFRAGEN oder weniger laut ANLIEGEN_MAX_ANFRAGEN (beim Aufruf gelesen; keine ganze Zahl
    ab 1: ValueError, nichts gesendet)."""
    wert = os.environ.get("ANLIEGEN_MAX_ANFRAGEN", "").strip()
    if not wert:
        return MAX_ANFRAGEN
    if not wert.isdigit() or int(wert) < 1:
        raise ValueError(f"ANLIEGEN_MAX_ANFRAGEN={wert!r} ist keine ganze Zahl ab 1; keine Anfrage gesendet")
    return min(int(wert), MAX_ANFRAGEN)

# Open311 GeoReport v2, GET requests: Felder laut Spezifikation (ob Köln sie so liefert, ist ungeprüft)
PFLICHT = ("service_request_id", "status", "requested_datetime")
KATEGORIE = ("service_code", "service_name")   # mindestens eines
STATUS = ("open", "closed")                    # Werte laut Spezifikation
# Kategorie-Code → Gruppe für die Zählung je Gebiet (UNGEPRÜFT: die Kölner Kategorien sind nicht gesichtet; laut
# Spezifikation listet services.json sie). Bis dahin leer: alle Meldungen „ohne Gruppe“, gezählt nur „gesamt“.
GRUPPEN = {}
OHNE_GRUPPE = "ohne Gruppe"
KOPF = ["nummer", "tag", "kategorie_code", "kategorie", "gruppe", "stadtteil", "stadtbezirk", "status",
        "erstmals_gesehen", "zuletzt_gesehen"]
LOG_KOPF = ["datum", "monat", "erhalten", "neu", "status_geaendert", "fehler"]


def anfrage_url(erster, url=None):
    """Meldungen eines Kalendermonats (start_date, end_date im W3C-Format laut Spezifikation, UTC)."""
    letzter = monatsende(erster)
    q = urllib.parse.urlencode({"start_date": f"{erster.isoformat()}T00:00:00Z",
                                "end_date": f"{letzter.isoformat()}T23:59:59Z"})
    return f"{url or URL}?{q}"


def monatsende(erster):
    return (erster.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def months(start, end):
    m = start.replace(day=1)
    while m <= end:
        yield m
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)


def tag(wert):
    """Tag (Ortszeit Köln) eines Zeitpunkts im W3C-Format; ValueError, wenn nicht lesbar."""
    s = str(wert or "").strip()
    if len(s) < 10:
        raise ValueError("Zeitpunkt fehlt")
    z = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (z.astimezone(abruf.ORTSZEIT) if z.tzinfo else z).date().isoformat()


def schema_pruefen(daten, erster, leer_erlaubt=True):
    """Prüft die Antwort für den Monat ab `erster`; Schemafehler mit allen Befunden (Feldnamen, keine Inhalte).
    `leer_erlaubt=False` für den letzten abgeschlossenen Monat: ohne Meldung nimmt die Schnittstelle den Zeitfilter oder
    das Datumsformat vermutlich nicht an."""
    monat = f"{erster:%Y-%m}"
    if not isinstance(daten, list) or not all(isinstance(r, dict) for r in daten):
        art = type(daten).__name__
        raise dienste.Schemafehler(f"Sag’s uns {monat}: Antwort ist keine Liste von Meldungen (Open311 GeoReport v2), "
                                   f"sondern {art}.")
    befunde, namen = [], {}
    for r in daten:
        for k in r:
            namen[k] = namen.get(k, 0) + 1
    for k in PFLICHT:
        if namen.get(k, 0) < len(daten):
            befunde.append(f"Feld {k!r} fehlt in {len(daten) - namen.get(k, 0)} von {len(daten)} Meldungen")
    ohne_kategorie = sum(1 for r in daten if not any(r.get(k) not in (None, "") for k in KATEGORIE))
    if ohne_kategorie:
        befunde.append(f"{ohne_kategorie} Meldungen ohne service_code und service_name")
    andere = sorted({dienste.text(r.get("status"), 30) for r in daten if "status" in r and r["status"] not in STATUS})
    if andere:
        befunde.append(f"Status außerhalb der Spezifikation (open, closed): {', '.join(andere[:10])}")
    ohne_nummer = sum(1 for r in daten if "service_request_id" in r and str(r["service_request_id"] or "").strip() == "")
    if ohne_nummer:
        befunde.append(f"{ohne_nummer} Meldungen mit leerer service_request_id")
    von, bis = (erster - timedelta(days=1)).isoformat(), (monatsende(erster) + timedelta(days=1)).isoformat()
    unlesbar = ausserhalb = 0
    for r in daten:
        if "requested_datetime" not in r:
            continue
        try:
            t = tag(r["requested_datetime"])
        except (ValueError, TypeError):
            unlesbar += 1
            continue
        if not von <= t <= bis:
            ausserhalb += 1
    if unlesbar:
        befunde.append(f"requested_datetime bei {unlesbar} Meldungen nicht lesbar")
    if ausserhalb:
        befunde.append(f"{ausserhalb} Meldungen außerhalb des angefragten Monats (Zeitfilter wirkt nicht)")
    if befunde:
        gezeigt = ", ".join(dienste.text(k, 40) for k in sorted(namen)[:50]) or "keine"
        raise dienste.Schemafehler(f"Sag’s uns {monat}: Antwort passt nicht zu Open311 GeoReport v2: "
                                   f"{'; '.join(befunde)}. Felder in der Antwort ({len(daten)} Meldungen): {gezeigt}.")
    if not daten and not leer_erlaubt:
        raise dienste.Schemafehler(f"Sag’s uns {monat}: keine Meldung im letzten abgeschlossenen Monat (Zeitfilter "
                                   "oder Datumsformat prüfen).")
    if kurz := dienste.kuerzung(len(daten), OBERGRENZE_ANTWORT, f"Sag’s uns {monat}"):
        raise dienste.Schemafehler(f"{'; '.join(kurz)}.")


def lauf_pruefen(geprueft):
    """Prüft die Monate eines Laufs [(erster, Antwort)] zusammen, bevor etwas geschrieben wird: nicht alle ohne Meldung
    (etwa wenn die Schnittstelle das Datumsformat nicht annimmt) und, solange OBERGRENZE_ANTWORT ungeprüft ist, nicht
    dieselbe Höchstzahl (ab GLEICH_AB) in mehreren Monaten (Verdacht auf Kürzung). Schemafehler mit den Zahlen."""
    zahlen = {f"{m:%Y-%m}": len(d) for m, d in geprueft}
    befunde = []
    if not any(zahlen.values()):
        befunde.append(f"alle {len(zahlen)} abgefragten Monate ohne Meldung (Zeitfilter oder Datumsformat prüfen)")
    hoechst = max(zahlen.values(), default=0)
    gleich = sorted(m for m, n in zahlen.items() if n == hoechst)
    if OBERGRENZE_ANTWORT is None and hoechst >= GLEICH_AB and len(gleich) > 1:
        befunde.append(f"möglicherweise gekürzt: dieselbe Höchstzahl {hoechst} in {len(gleich)} Monaten "
                       f"({', '.join(gleich)}); bis zur Klärung OBERGRENZE_ANTWORT eintragen, TECHNIK.md")
    if befunde:
        raise dienste.Schemafehler(f"Sag’s uns: {'; '.join(befunde)}.")


def _monat(text):
    return date.fromisoformat(f"{text}-01") if text else None


def plan(heute, stand=None):
    """(Monate dieses Laufs, neuester zuerst; Beginn des Archivs): jeder Monat der letzten FENSTER Tage (Status,
    Nachzügler) und jeder Monat ab dem Beginn, der noch nie geprüft wurde (`stand`: STAND.json des letzten Laufs mit
    `erstabruf_ab` und `monate_geprueft`). Ohne Stand ist der Beginn der Monat von heute − ERSTER_ABRUF_TAGE."""
    stand = stand or {}
    beginn = _monat(stand.get("erstabruf_ab")) or (heute - timedelta(days=ERSTER_ABRUF_TAGE)).replace(day=1)
    fenster = (heute - timedelta(days=FENSTER)).replace(day=1)
    geprueft = set(stand.get("monate_geprueft") or ())
    alle = list(months(min(beginn, fenster), heute))
    return [m for m in reversed(alle) if m >= fenster or f"{m:%Y-%m}" not in geprueft], beginn


def _feld(wert):
    return " ".join(str(wert if wert is not None else "").split())   # ohne Tabulatoren und Zeilenumbrüche


def normalize(r, ortsteile):
    """Nur Nummer, Tag, Kategorie, Gruppe, Stadtteil, Stadtbezirk und Status; die Koordinate nur zur Zuordnung."""
    code = _feld(r.get("service_code"))
    st = None
    try:
        lon, lat = float(r["long"]), float(r["lat"])
        st = ortsteile.locate(lon, lat)
    except (KeyError, TypeError, ValueError):
        pass
    return {"nummer": _feld(r["service_request_id"]), "tag": tag(r["requested_datetime"]),
            "kategorie_code": code, "kategorie": _feld(r.get("service_name")),
            "gruppe": GRUPPEN.get(code, OHNE_GRUPPE),
            "stadtteil": st["ortsteil_bez"] if st else "", "stadtbezirk": st["bezirk_bez"] if st else "",
            "status": r["status"]}


def _sortkey(nummer):
    teile = nummer.replace("/", "-").split("-")
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t) for t in reversed(teile))


def read_state(path):
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    return {row[0]: dict(zip(head, row)) for row in (line.split("\t") for line in lines[1:] if line)}


def write_state(path, state):
    rows = ["\t".join(KOPF)] + ["\t".join(_feld(state[k].get(c, "")) for c in KOPF)
                                for k in sorted(state, key=_sortkey)]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tmp.replace(path)


def update(state, items, day):
    """Meldungen eintragen; gibt (neu, Status geändert) zurück."""
    neu = geaendert = 0
    for m in items:
        cur = state.get(m["nummer"])
        if cur is None:
            state[m["nummer"]] = {**m, "erstmals_gesehen": day, "zuletzt_gesehen": day}
            neu += 1
            continue
        if cur.get("status") != m["status"]:
            geaendert += 1
        cur.update({**m, "zuletzt_gesehen": day})   # erstmals_gesehen bleibt
    return neu, geaendert


def archive(base=None, now=None, ortsteile=None):
    """Ein Lauf ins Archivverzeichnis (Standard: config.BAUSTELLEN_ARCHIV/anliegen) mit den Monaten aus `plan`, neuester
    zuerst: beim ersten Lauf die der letzten ERSTER_ABRUF_TAGE Tage, danach die der letzten FENSTER Tage und jeder noch
    nie geprüfte Monat ab dem Beginn des Archivs. Ohne Freigabe: übersprungen, nichts gesendet, nichts geschrieben.
    Schemafehler (auch aus `lauf_pruefen`): nichts geschrieben. Abbruch (Verbindung, HTTP, Obergrenze) oder Ende des
    Zeitfensters während des Laufs: keine weitere Anfrage; die geprüften Monate davor werden geschrieben und in
    STAND.json als geprüft vermerkt, der Lauf endet mit Exit-Code ungleich 0, Folgeläufe holen die übrigen nach."""
    from .geo import Ortsteile
    base = Path(base or config.BAUSTELLEN_ARCHIV) / "anliegen"
    now = now or datetime.now(timezone.utc)
    heute = now.date()
    day = heute.isoformat()
    state_file, log_file, stand_file = base / "meldungen.tsv", base / "abrufe.tsv", base / "STAND.json"
    state = read_state(state_file)
    stand_alt = json.loads(stand_file.read_text(encoding="utf-8")) if stand_file.exists() else {}
    monate, beginn = plan(heute, stand_alt)
    vormonat = (heute.replace(day=1) - timedelta(days=1)).replace(day=1)   # letzter abgeschlossener Monat
    geprueft, fehler_zeile, fehler = [], [], None
    lauf = dienste.Lauf(THEMA, grenze())
    try:
        with lauf:
            for erster in monate:
                try:
                    daten = lauf.json(anfrage_url(erster))
                except (dienste.Abbruch, dienste.NichtGesendet) as e:
                    if isinstance(e, dienste.NichtGesendet) and not lauf.anfragen:
                        raise   # vor der ersten Anfrage: Lauf übersprungen
                    fehler_zeile = [[day, f"{erster:%Y-%m}", "", "", "", dienste.text(e, 300)]]
                    fehler = e   # etwa Zeitfenster während des Laufs zu Ende: geprüfte Monate bleiben
                    break
                schema_pruefen(daten, erster, leer_erlaubt=erster != vormonat)
                geprueft.append((erster, daten))
            if geprueft:
                lauf_pruefen(geprueft)
    except dienste.NichtGesendet as e:
        print(f"Sag’s uns: übersprungen ({e}); nichts gesendet, nichts geschrieben.")
        dienste.hinweis_uebersprungen(e)
        return None
    except dienste.Schemafehler as e:
        zuvor = f" Zuvor Abbruch: {dienste.text(fehler, 300)}." if fehler else ""
        raise SystemExit(f"{e}{zuvor} Nichts geschrieben.") from e
    if not geprueft:
        raise SystemExit(f"Sag’s uns: kein Monat abgerufen ({fehler}); nichts geschrieben.")
    ortsteile = ortsteile or Ortsteile()
    rows = []
    for erster, daten in geprueft:
        items = {}
        for r in daten:
            m = normalize(r, ortsteile)
            items[m["nummer"]] = m
        neu, geaendert = update(state, list(items.values()), day)
        rows.append([day, f"{erster:%Y-%m}", len(items), neu, geaendert, ""])
    rows += fehler_zeile
    write_state(state_file, state)
    alle = sorted(set(stand_alt.get("monate_geprueft") or ()) | {f"{m:%Y-%m}" for m, _ in geprueft})
    offen = [f"{m:%Y-%m}" for m in months(beginn, heute) if f"{m:%Y-%m}" not in alle]
    stand = {"abruf": now.isoformat(timespec="seconds"), "quelle": URL, "datensatz": DATENSATZ,
             "lizenz": config.ANLIEGEN_LICENSE, "erstabruf_ab": f"{beginn:%Y-%m}", "monate_geprueft": alle,
             "monate_offen": offen, "monate_lauf": [f"{m:%Y-%m}" for m, _ in geprueft],
             "monate_erfolgreich": len(geprueft),
             "abbruch": dienste.text(fehler, 300) if fehler else "", "anfragen": lauf.anfragen,
             "meldungen": len(state), "ohne_stadtteil": sum(1 for m in state.values() if not m.get("stadtteil")),
             "archiv_beginn": min((m["erstmals_gesehen"] for m in state.values()), default=day)}
    stand_file.write_text(json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    neu = not log_file.exists()
    with log_file.open("a", encoding="utf-8") as fh:
        if neu:
            fh.write("\t".join(LOG_KOPF) + "\n")
        fh.writelines("\t".join(_feld(x) for x in r) + "\n" for r in rows)
    dienste.protokoll_schreiben(base / "anfragen.tsv", lauf)
    print(f"Sag’s uns: {len(state)} Meldungen im Archiv, {len(geprueft)} Monate, {lauf.anfragen} Anfragen, "
          f"{len(offen)} Monate seit {beginn:%Y-%m} noch offen → {base}")
    if fehler:
        raise SystemExit(f"Sag’s uns: Abbruch nach {len(geprueft)} Monaten ({fehler}); {len(offen)} Monate noch offen, "
                         "der nächste Lauf holt sie nach")
    return rows


def pruefen_archiv(base=None):
    """Befunde zum Archiv (Datenschutz): meldungen.tsv hat genau die Spalten in KOPF."""
    pfad = Path(base or config.BAUSTELLEN_ARCHIV) / "anliegen" / "meldungen.tsv"
    if not pfad.exists():
        return []
    kopf = pfad.read_text(encoding="utf-8").split("\n", 1)[0].split("\t")
    return [] if kopf == KOPF else [f"meldungen.tsv: Spalten {kopf} statt {KOPF}"]


# --- Seite: Zahlen je Stadtteil für den Steckbrief (Schritt `anliegen-seite`, im Workflow nach dem Auschecken des
# Branches archiv). Nur Zählungen; Werte unter UNTER als „unter 3“, kein Link auf einzelne Meldungen. Die Schlüssel
# „ortsteile“ und „stadt“ liest die Seite (site/app.js, anliegenSteckbrief).
SEITE_DATEI = "anliegen.json"
TAGE = 90
UNTER = 3


def gruppen_folge():
    """Gruppen in der Reihenfolge von GRUPPEN (ohne „ohne Gruppe“; die zählt nur in „gesamt“)."""
    return list(dict.fromkeys(GRUPPEN.values()))


def _zaehlen(meldungen):
    z = {g: 0 for g in gruppen_folge()}
    for m in meldungen:
        if m.get("gruppe") in z:
            z[m["gruppe"]] += 1
    z["gesamt"] = len(meldungen)
    return {k: (v if v >= UNTER else "unter 3") for k, v in z.items()}


def seite(base=None, out=None, heute=None):
    """export/<STADT>/anliegen.json aus dem Archiv: Meldungen der letzten TAGE Tage je Stadtteil, Stadtbezirk und für
    die ganze Stadt (Schlüssel „stadt“), nach Gruppe. Ohne Archiv wird nichts geschrieben."""
    base = Path(base or config.BAUSTELLEN_ARCHIV) / "anliegen"
    out = Path(out or config.EXPORT / config.STADT / SEITE_DATEI)
    state_file, stand_file = base / "meldungen.tsv", base / "STAND.json"
    if not state_file.exists() or not stand_file.exists():
        out.unlink(missing_ok=True)
        print("Sag’s uns: kein Archiv – übersprungen.")
        return None
    stand = json.loads(stand_file.read_text(encoding="utf-8"))
    bis = heute or date.fromisoformat(stand["abruf"][:10])
    von = bis - timedelta(days=TAGE - 1)
    sel = [m for m in read_state(state_file).values()
           if von.isoformat() <= m["tag"] <= bis.isoformat() and m.get("stadtteil")]
    sts, bez = {}, {}
    for m in sel:
        sts.setdefault(m["stadtteil"], []).append(m)
        bez.setdefault(m["stadtbezirk"], []).append(m)
    beginn = stand.get("archiv_beginn")
    doc = {"meta": {"titel": TITEL, "url": DATENSATZ, "lizenz": config.ANLIEGEN_LICENSE, "abruf": stand["abruf"][:10],
                    "archiv_beginn": beginn, "von": von.isoformat(), "bis": bis.isoformat(), "tage": TAGE,
                    "gruppen": gruppen_folge(),
                    "unvollstaendig_vor": beginn if beginn and beginn > von.isoformat() else None,
                    "hinweis": "Hinweise der Einwohnerschaft an die Verwaltung, keine Ratsvorlagen. Die Zahl hängt davon ab, "
                               "wer meldet und was veröffentlicht wird; sie ist kein Maß für den Zustand eines Gebiets."},
           "stadt": _zaehlen(sel),
           "bezirke": {n: _zaehlen(v) for n, v in sorted(bez.items())},
           "ortsteile": {n: _zaehlen(v) for n, v in sorted(sts.items())}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    if befunde := pruefen(out):   # hier statt in `check`: das Archiv liegt erst nach der Aufbereitung vor
        out.unlink()
        raise SystemExit(f"Prüfung fehlgeschlagen: Sag’s uns ({'; '.join(befunde)}).")
    print(f"Sag’s uns: {len(sel)} Meldungen vom {von:%d.%m.%Y} bis {bis:%d.%m.%Y} in {len(sts)} Stadtteilen → {out}")
    return doc


def pruefen(path=None):
    """Prüfung: nur Zählungen je Gruppe und gesamt, kleine Werte als „unter 3“, keine weiteren Felder."""
    path = Path(path or config.EXPORT / config.STADT / SEITE_DATEI)
    if not path.exists():
        return []
    doc, befunde = json.loads(path.read_text(encoding="utf-8")), []
    erlaubt = set(gruppen_folge()) | {"gesamt"}
    gebiete = [(config.STADT_NAME, doc["stadt"])] + list(doc["bezirke"].items()) + list(doc["ortsteile"].items())
    for name, z in gebiete:
        if set(z) - erlaubt:
            befunde.append(f"Sag’s uns {name}: unerwartete Felder {sorted(set(z) - erlaubt)}")
        if any(not (v == "unter 3" or (isinstance(v, int) and v >= UNTER)) for v in z.values()):
            befunde.append(f"Sag’s uns {name}: Wert unter {UNTER} nicht gerundet")
    return befunde
