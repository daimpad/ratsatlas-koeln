"""Absage aus dem Sitzungsnamen in termine.ics, audit_zeit.tsv und verify.py (Entscheidung 21.11.2026 (1) (c) (9)).

Die Stadt setzt OParl `cancelled` bei keiner Sitzung; eine Absage steht nur im Namen (`hinweis` „abgesagt“ aus
`export.hinweis_sitzung`). Eine Regel, `export.absage`, sagt für alle Stellen, ob und warum eine Sitzung als abgesagt
gilt: „oparl“ bei OParl `cancelled`, sonst „name“ beim Hinweis „abgesagt“, sonst keine Absage („verschoben“ ist keine).
Der Kalender trägt dann `STATUS:CANCELLED` und den Zusatz „ (abgesagt)“ bzw. „ (laut Sitzungsnamen abgesagt)“, das Log
zählt beide getrennt; audit_zeit.tsv und verifikation_zeit.tsv zählen eine abgesagte Sitzung nicht als Sitzung und
nennen den Grund; `check.absagen_kalender` prüft termine.ics gegen zeit.json, nur mit Zahlen. Aus der Nachprüfung des
Pull Request: was sich gegenüber der Regel bis 2776188 ändert (in Köln nur bisherige Treffer), die Vermerke in
TECHNIK.md und die abgeschalteten Themenseiten, die weiter nur OParl `cancelled` auswerten. Alle Gremien, Sitzungen,
Namen und Vorlagen sind erfunden (direkte Aufrufe oder lokaler Testserver); keine Anfragen an die Stadt, verify.py nur
mit Attrappen statt der OParl-API."""
import csv
import importlib.util
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

from pipeline import build, check, config, export, kontext, maske, publish, sessionnet, verify

ROOT = Path(__file__).resolve().parents[1]
M = "https://example.invalid/oparl/meetings"
SITZUNG = "Sitzung des Gremiums an diesem Tag in der OParl-API der Stadt"


def _sitzung(k, gremium="Probebeirat", name=None, cancelled=False, hinweis=None, tag="2026-12-01"):
    """Erfundene Sitzung in der Form von export._meetings (ohne Hinweis kein Feld `hinweis`)."""
    m = {"date": tag, "time": "17:00", "gremium": gremium, "name": name or f"[Testdaten] {gremium}",
         "cancelled": cancelled, "state": None, "web": f"https://example.invalid/sitzung/{k}", "invitation": None,
         "agenda_items": 0, "start": f"{tag}T16:00:00Z", "end": None, "source_object": f"{M}/{k}"}
    return {**m, "hinweis": hinweis} if hinweis else m


# Kennung → (OParl cancelled, Hinweis aus dem Namen, erwarteter Grund der Absage)
FAELLE = {
    "c": (True, None, "oparl"),
    "a": (False, "abgesagt", "name"),
    "b": (True, "abgesagt", "oparl"),
    "v": (False, "verschoben", None),
    "cv": (True, "verschoben", "oparl"),
    "n": (False, None, None),
}


def test_absage_eine_regel():
    """export.absage: OParl `cancelled` geht vor, sonst der Hinweis „abgesagt“; „verschoben“ und kein Hinweis sind keine
    Absage. Auch für Sitzungen aus zeit.json (Feld `hinweis` fehlt ohne Hinweis, `cancelled` notfalls fehlend)."""
    for k, (cancelled, hinweis, grund) in FAELLE.items():
        assert export.absage(_sitzung(k, cancelled=cancelled, hinweis=hinweis)) == grund, k
    assert export.absage({}) is None and export.absage({"hinweis": "abgesagt"}) == "name"
    assert export.absage({"cancelled": True, "hinweis": None}) == "oparl"
    assert export.ABSAGE_TEXT == {"oparl": "abgesagt laut OParl (cancelled)", "name": "laut Sitzungsnamen abgesagt"}
    assert publish.ZUSATZ_ABSAGE == {"oparl": " (abgesagt)", "name": " (laut Sitzungsnamen abgesagt)"}


def _physische_zeilen(pfad):
    return pfad.read_bytes().split(b"\r\n")


def _text(pfad):
    """iCalendar-Datei als Text mit den Zeilenenden, wie sie geschrieben sind (read_text macht aus CRLF ein LF)."""
    return pfad.read_bytes().decode("utf-8")


def test_kalender_status_zusammenfassung_und_log(tmp_path, capsys):
    """termine.ics: STATUS:CANCELLED bei jeder Absage nach export.absage, Zusatz in der Zusammenfassung nach dem Grund;
    „verschoben“ ändert weder STATUS noch Zusammenfassung (der Name mit dem Hinweis steht in der Beschreibung). Das Log
    zählt die Absagen getrennt nach Grund, nur Zahlen."""
    namen = {"a": "Probebeirat - Sitzung entfällt", "b": "Probebeirat - fällt aus", "v": "Probebeirat - verschoben",
             "cv": "Probebeirat - vertagt"}
    sitzungen = [_sitzung(k, name=namen.get(k), cancelled=c, hinweis=h) for k, (c, h, _) in FAELLE.items()]
    publish.write_calendar(tmp_path / "termine.ics", sitzungen, date(2026, 11, 21))
    assert capsys.readouterr().out.splitlines() == [
        "termine.ics: 6 Termine, davon ganztägig 0, abgesagt laut OParl 3, abgesagt laut Sitzungsnamen 1"]
    ics = {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(tmp_path / "termine.ics")}
    zusatz = {"oparl": " (abgesagt)", "name": " (laut Sitzungsnamen abgesagt)", None: ""}
    for k, (_, _, grund) in FAELLE.items():
        assert ics[k]["STATUS"] == ("CANCELLED" if grund else "CONFIRMED"), k
        assert ics[k]["SUMMARY"] == "Probebeirat" + zusatz[grund], k
        assert ics[k]["DESCRIPTION"].startswith(namen.get(k, "[Testdaten] Probebeirat") + "\n"), k
    assert ics["v"]["SUMMARY"] == "Probebeirat" and "verschoben" in ics["v"]["DESCRIPTION"]
    assert all(len(z) <= 75 for z in _physische_zeilen(tmp_path / "termine.ics"))


def test_kalender_faltung_und_maskierung_mit_zusatz(tmp_path, capsys):
    """Der Zusatz läuft durch dieselben Hilfen wie bisher: Komma und Semikolon im Gremium nach RFC 5545 maskiert, die
    Zeile auf 75 Oktette gefaltet, nie innerhalb eines UTF-8-Zeichens; entfaltet steht die Zusammenfassung vollständig
    da. Das Gremium ist so gewählt, dass die Grenze der ersten Zeile (75 Oktette) mitten im Zusatz liegt."""
    gremium = "Arbeitskreis für Grünflächen, Spielplätze; Straßenbäume"   # mit „SUMMARY:“ maskiert 71 Oktette
    sitzungen = [_sitzung("a", gremium=gremium, name=f"{gremium} - entfällt", hinweis="abgesagt"),
                 _sitzung("c", gremium=gremium, cancelled=True)]
    publish.write_calendar(tmp_path / "termine.ics", sitzungen, date(2026, 11, 21))
    capsys.readouterr()
    zeilen = _physische_zeilen(tmp_path / "termine.ics")
    assert all(len(z) <= 75 for z in zeilen)
    for z in zeilen:
        z.decode("utf-8")   # keine getrennten UTF-8-Zeichen
    text = re.sub(r"\r\n[ \t]", "", _text(tmp_path / "termine.ics"))
    roh = gremium.replace(",", "\\,").replace(";", "\\;")
    assert f"\r\nSUMMARY:{roh} (laut Sitzungsnamen abgesagt)\r\n" in text
    assert f"\r\nSUMMARY:{roh} (abgesagt)\r\n" in text
    summary = [i for i, z in enumerate(zeilen) if z.startswith(b"SUMMARY:")]
    assert [zeilen[i][-4:] for i in summary] == [b" (la", b" (ab"]   # gefaltet mitten im Zusatz
    assert all(len(zeilen[i]) == 75 and zeilen[i + 1].startswith(b" ") for i in summary)
    ics = {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(tmp_path / "termine.ics")}
    assert ics["a"]["SUMMARY"] == f"{gremium} (laut Sitzungsnamen abgesagt)" and ics["a"]["STATUS"] == "CANCELLED"
    assert ics["c"]["SUMMARY"] == f"{gremium} (abgesagt)" and ics["c"]["STATUS"] == "CANCELLED"


# --- audit_zeit.tsv und verifikation_zeit.tsv -------------------------------------------------------------------------

def test_sitzungstage_rangfolge():
    """export.sitzungstage: je Gremium und Tag None, sobald eine Sitzung nicht abgesagt ist (auch „verschoben“), sonst
    der Grund, „oparl“ vor „name“, in jeder Reihenfolge der Sitzungen."""
    s = [_sitzung("1", "A", hinweis="abgesagt", tag="2026-12-01"), _sitzung("2", "A", tag="2026-12-01"),
         _sitzung("3", "B", hinweis="abgesagt", tag="2026-12-01"), _sitzung("4", "B", cancelled=True, tag="2026-12-01"),
         _sitzung("5", "C", hinweis="abgesagt", tag="2026-12-02"), _sitzung("6", "D", hinweis="verschoben"),
         _sitzung("7", "E", cancelled=True, tag="2026-12-03")]
    erwartet = {("A", "2026-12-01"): None, ("B", "2026-12-01"): "oparl", ("C", "2026-12-02"): "name",
                ("D", "2026-12-01"): None, ("E", "2026-12-03"): "oparl"}
    assert export.sitzungstage(s) == erwartet
    assert export.sitzungstage(list(reversed(s))) == erwartet
    assert export.sitzungstage([]) == {}


# Beratungen einer erfundenen Vorlage: Gremium → (Tag, erwartete Bemerkung in audit_zeit.tsv, erwarteter Wert in
# verifikation_zeit.tsv statt der OParl-API)
BERATUNGEN = {
    "Gehalten": ("2026-12-01", SITZUNG, "2026-12-01"),
    "Verschoben": ("2026-12-02", SITZUNG, "2026-12-02"),
    "Namensabsage": ("2026-12-03", f"{SITZUNG}, laut Sitzungsnamen abgesagt", "laut Sitzungsnamen abgesagt"),
    "Oparlabsage": ("2026-12-04", f"{SITZUNG}, abgesagt laut OParl (cancelled)", "abgesagt laut OParl (cancelled)"),
    "Beides": ("2026-12-05", f"{SITZUNG}, abgesagt laut OParl (cancelled)", "abgesagt laut OParl (cancelled)"),
    "Gemischt": ("2026-12-06", SITZUNG, "2026-12-06"),
    "Ohne": ("2026-12-07", f"keine {SITZUNG}", "keine Sitzung"),
}
SITZUNGEN_TAGE = [
    _sitzung("g", "Gehalten", tag="2026-12-01"),
    _sitzung("v", "Verschoben", hinweis="verschoben", tag="2026-12-02"),
    _sitzung("a", "Namensabsage", hinweis="abgesagt", tag="2026-12-03"),
    _sitzung("c", "Oparlabsage", cancelled=True, tag="2026-12-04"),
    _sitzung("b1", "Beides", hinweis="abgesagt", tag="2026-12-05"),
    _sitzung("b2", "Beides", cancelled=True, tag="2026-12-05"),
    _sitzung("m1", "Gemischt", hinweis="abgesagt", tag="2026-12-06"),
    _sitzung("m2", "Gemischt", tag="2026-12-06"),
    _sitzung("x", "Ohne", tag="2026-12-08"),   # anderer Tag: keine Sitzung am Tag der Beratung
]


def _vorlage():
    steps = [{"typ": "beratung", "label": g, "role": "beratend", "date": tag} for g, (tag, *_) in BERATUNGEN.items()]
    steps.append({"typ": "beratung", "label": "Ohne Tag", "role": "beratend", "date": None})
    return {"reference": "9001/2026", "date": "2026-11-20", "steps": steps}


def test_audit_zeit_zaehlt_nur_sitzungen_ohne_absage():
    """audit_zeit.tsv (export.time_audit_rows): Eine Sitzung mit Hinweis „abgesagt“ aus dem Namen gilt nicht als
    Sitzung, ebenso eine mit OParl `cancelled`; die Bemerkung nennt den Grund getrennt. „verschoben“ zählt als Sitzung;
    eine nicht abgesagte Sitzung am selben Tag geht vor. Spalten unverändert."""
    zeilen = export.time_audit_rows([_vorlage()], SITZUNGEN_TAGE)
    assert export.TIME_AUDIT == ["drucksache", "zeitdimension", "wert", "quelle", "status", "bemerkung"]
    beratung = {z[1].removeprefix("beratung: ").removesuffix(" (beratend)"): z for z in zeilen[1:]}
    for g, (tag, bemerkung, _) in BERATUNGEN.items():
        assert beratung[g] == ["9001/2026", f"beratung: {g} (beratend)", tag, config.QUELLE_SITZUNG, "abgeleitet",
                               bemerkung], g
    assert beratung["Ohne Tag"][4:] == ["unklar", "Beratung ohne verknüpfte Sitzung"]
    assert zeilen[0][:2] == ["9001/2026", "datum_vorlage"] and len(zeilen) == len(BERATUNGEN) + 2


def test_verify_time_mit_attrappen(tmp_path, monkeypatch, capsys):
    """verify.verify_time zählt mit derselben Regel (export.sitzungstage, export.absage): eine laut Namen abgesagte
    Sitzung ist keine Sitzung, der Wert nennt den Grund. Ohne Netz: OParl-API, Sitzungen und Vorlage sind Attrappen, die
    Datenbank ist eine kleine erfundene Tabelle in tmp_path."""
    db = sqlite3.connect(tmp_path / "t.sqlite")
    db.executescript("CREATE TABLE location (id TEXT, ortsteil TEXT); CREATE TABLE paper_location (paper_id TEXT, "
                     "location_id TEXT); CREATE TABLE consultation (paper_id TEXT, meeting_id TEXT);"
                     "INSERT INTO location VALUES ('l1', 'Teststadtteil');"
                     "INSERT INTO paper_location VALUES ('p1', 'l1');"
                     "INSERT INTO consultation VALUES ('p1', 'm1');")
    db.commit()
    db.close()
    monkeypatch.setattr(config, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(config, "EXPORT", tmp_path)
    monkeypatch.setattr(config, "PILOT_ORTSTEIL", "Teststadtteil")
    monkeypatch.setattr(verify, "_meetings", lambda db: SITZUNGEN_TAGE)
    monkeypatch.setattr(verify, "_paper_detail", lambda db, pid: _vorlage())
    abrufe = []

    def attrappe(pid, tries=3):   # statt der OParl-API: keine Anfrage
        abrufe.append(pid)
        return {"date": "2026-11-20", "consultation": [{}] * (len(BERATUNGEN) + 1)}

    monkeypatch.setattr(verify, "get_json", attrappe)
    verify.verify_time()
    assert abrufe == ["p1"]
    with open(tmp_path / "verifikation_zeit.tsv", encoding="utf-8") as f:
        zeilen = list(csv.reader(f, delimiter="\t"))
    assert zeilen[0] == ["drucksache", "pruefung", "export", "oparl_api", "ergebnis"]
    je = {z[1]: z for z in zeilen[1:]}
    for g, (tag, _, wert) in BERATUNGEN.items():
        assert je[f"sitzung {g}"][2:] == [tag, wert, "ok" if wert == tag else "abweichend"], g
    assert je["datum_vorlage"][4] == "ok" and je["beratungen"][4] == "ok"
    assert "Zeitleiste: 0 von 1 Vorlagen ohne Abweichung" in capsys.readouterr().out


def test_vorher_nachher_bisherige_treffer_in_koeln():
    """Was sich gegenüber der Regel bis 2776188 ändert (als Sitzung zählte jede ohne OParl `cancelled`; Nachprüfung des
    Pull Request zu den Docstrings von export.time_audit_rows und verify.verify_time und zu TECHNIK.md): Vorher stand
    „keine Sitzung …“ bzw. „keine Sitzung“ nur, wenn alle Sitzungen des Gremiums an dem Tag OParl `cancelled` trugen
    (oder es keine gab); eine Sitzung mit Absage nur im Namen zählte als Treffer („Sitzung des Gremiums …“ ohne Zusatz
    bzw. das Datum). Ohne OParl `cancelled`, wie in Köln, ändern sich also nur bisherige Treffer, und die Zeilen mit
    „keine Sitzung …“ bleiben dieselben. Die Werte von verify.verify_time stehen in BERATUNGEN (geprüft in
    test_verify_time_mit_attrappen)."""
    def bisher(sitzungen):   # Regel bis 2776188: Bemerkung in audit_zeit.tsv, Wert in verifikation_zeit.tsv
        held = {(m["gremium"], m["date"]) for m in sitzungen if not m["cancelled"]}
        return {g: (SITZUNG, tag) if (g, tag) in held else (f"keine {SITZUNG}", "keine Sitzung")
                for g, (tag, *_) in BERATUNGEN.items()}

    def jetzt(sitzungen):
        zeilen = export.time_audit_rows([_vorlage()], sitzungen)
        return {z[1].removeprefix("beratung: ").removesuffix(" (beratend)"): z[5] for z in zeilen[1:] if z[2]}

    name, oparl = "laut Sitzungsnamen abgesagt", "abgesagt laut OParl (cancelled)"
    alt, neu = bisher(SITZUNGEN_TAGE), jetzt(SITZUNGEN_TAGE)
    assert {g: (alt[g][0], neu[g]) for g in BERATUNGEN if neu[g] != alt[g][0]} == {
        "Namensabsage": (SITZUNG, f"{SITZUNG}, {name}"),
        "Oparlabsage": (f"keine {SITZUNG}", f"{SITZUNG}, {oparl}"),
        "Beides": (SITZUNG, f"{SITZUNG}, {oparl}")}   # am Tag auch eine Absage nur im Namen: vorher ein Treffer
    tage = {g: tag for g, (tag, *_) in BERATUNGEN.items()}
    assert {g: (alt[g][1], wert) for g, (_, _, wert) in BERATUNGEN.items() if wert != alt[g][1]} == {
        "Namensabsage": (tage["Namensabsage"], name), "Oparlabsage": ("keine Sitzung", oparl),
        "Beides": (tage["Beides"], oparl)}
    koeln = [m for m in SITZUNGEN_TAGE if not m["cancelled"]]   # wie in Köln: OParl `cancelled` bei keiner Sitzung
    alt, neu = bisher(koeln), jetzt(koeln)
    assert {g: (alt[g][0], neu[g]) for g in BERATUNGEN if neu[g] != alt[g][0]} == {
        "Namensabsage": (SITZUNG, f"{SITZUNG}, {name}"), "Beides": (SITZUNG, f"{SITZUNG}, {name}")}
    keine = {g for g in BERATUNGEN if neu[g].startswith("keine ")}
    assert keine == {g for g in BERATUNGEN if alt[g][0].startswith("keine ")} == {"Oparlabsage", "Ohne"}


# --- check: termine.ics gegen zeit.json -------------------------------------------------------------------------------

def _export(base, sitzungen):
    """zeit.json (nur `meetings`, wie export ohne Beginn und Ende) und termine.ics aus denselben erfundenen
    Sitzungen."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "zeit.json").write_text(json.dumps(
        {"meetings": [{k: v for k, v in m.items() if k not in ("start", "end")} for m in sitzungen]},
        ensure_ascii=False))
    publish.write_calendar(base / "termine.ics", sitzungen, date(2026, 11, 21))


def _alle_faelle():
    return [_sitzung(k, gremium=f"Probebeirat {k.upper()}", cancelled=c, hinweis=h) for k, (c, h, _) in FAELLE.items()]


def test_check_kalender_ohne_befund(tmp_path, capsys):
    """check.absagen_kalender: Kalender und zeit.json aus denselben Sitzungen ergeben keinen Befund; die Ausgabe nennt
    nur Zahlen, dieselben wie die Zeile im Log von write_calendar."""
    _export(tmp_path, _alle_faelle())
    log = capsys.readouterr().out
    assert "abgesagt laut OParl 3, abgesagt laut Sitzungsnamen 1" in log
    assert check.absagen_kalender(tmp_path) == ([], [])
    out = capsys.readouterr().out
    assert out == ("\nAbsagen in termine.ics (export.absage)\n"
                   "Termine in termine.ics: 6, davon abgesagt laut OParl 3, abgesagt laut Sitzungsnamen 1\n")


def _ersetzen(pfad, alt, neu):
    text = re.sub(r"\r\n[ \t]", "", _text(pfad))
    assert text.count(alt) == 1, alt
    pfad.write_text(text.replace(alt, neu), encoding="utf-8")


def test_check_kalender_meldet_abweichungen_nur_mit_zahlen(tmp_path, capsys):
    """Eingeschleuste Abweichungen: STATUS ohne Absage, Zusatz fehlt oder nennt den falschen Grund, Zusatz ohne Absage,
    eine Absage nur in zeit.json, ein Termin ohne Sitzung in zeit.json. Befunde nur mit Zahlen, ohne Namen und
    Kennungen."""
    _export(tmp_path, _alle_faelle())
    ics = tmp_path / "termine.ics"
    _ersetzen(ics, "SUMMARY:Probebeirat A (laut Sitzungsnamen abgesagt)", "SUMMARY:Probebeirat A (abgesagt)")  # Grund
    _ersetzen(ics, "SUMMARY:Probebeirat C (abgesagt)", "SUMMARY:Probebeirat C")     # Zusatz fehlt
    _ersetzen(ics, "SUMMARY:Probebeirat N", "SUMMARY:Probebeirat N (laut Sitzungsnamen abgesagt)")   # ohne Absage
    teile = _text(ics).split("BEGIN:VEVENT")
    b = next(i for i, t in enumerate(teile) if f"UID:{M}/b\r\n" in t)
    teile[b] = teile[b].replace("STATUS:CANCELLED", "STATUS:CONFIRMED")         # STATUS falsch
    v = next(i for i, t in enumerate(teile) if f"UID:{M}/v\r\n" in t)
    teile[v] = teile[v].replace("STATUS:CONFIRMED\r\n", "")                     # STATUS fehlt (zählt als falsch)
    teile.insert(2, teile[1].replace(f"UID:{M}/c\r\n", f"UID:{M}/unbekannt\r\n"))  # ohne Sitzung in zeit.json
    ics.write_text("BEGIN:VEVENT".join(teile), encoding="utf-8")
    zeit = json.loads((tmp_path / "zeit.json").read_text())
    je = {x["source_object"].rsplit("/", 1)[1]: x for x in zeit["meetings"]}
    je["cv"]["cancelled"] = False                                               # Absage nur noch im Kalender
    (tmp_path / "zeit.json").write_text(json.dumps(zeit, ensure_ascii=False))
    capsys.readouterr()
    befunde, fehlend = check.absagen_kalender(tmp_path)
    out = capsys.readouterr().out
    assert fehlend == []
    assert befunde == [
        "Kalender: Termine in termine.ics ohne dieselbe Sitzung in zeit.json (UID): 1",
        "Kalender: Termine in termine.ics, deren STATUS nicht der Absage der Sitzung in zeit.json folgt "
        "(export.absage; STATUS:CANCELLED genau bei OParl `cancelled` oder Hinweis „abgesagt“ aus dem Namen, sonst "
        "STATUS:CONFIRMED): 3",
        "Kalender: Termine in termine.ics, deren Zusatz am Ende der Zusammenfassung nicht dem Grund der Absage der "
        "Sitzung in zeit.json folgt (publish.ZUSATZ_ABSAGE): 4"]
    assert "Termine in termine.ics: 7, davon abgesagt laut OParl 2, abgesagt laut Sitzungsnamen 1\n" in out
    for teil in ("Probebeirat", "example.invalid", "meetings/", "unbekannt"):
        assert teil not in out and teil not in " ".join(befunde), teil


def test_check_kalender_ohne_dateien(tmp_path, capsys):
    """Ohne Termine nichts zu prüfen; Termine ohne zeit.json und zeit.json ohne termine.ics: nicht durchgeführt."""
    assert check.absagen_kalender(tmp_path) == ([], [])
    publish.write_calendar(tmp_path / "termine.ics", [], date(2026, 11, 21))
    assert check.absagen_kalender(tmp_path) == ([], [])          # Kartenvorschau: Kalender ohne Termine
    publish.write_calendar(tmp_path / "termine.ics", [_sitzung("n")], date(2026, 11, 21))
    befunde, fehlend = check.absagen_kalender(tmp_path)
    assert befunde == [] and len(fehlend) == 1 and "zeit.json fehlt" in fehlend[0]
    (tmp_path / "termine.ics").unlink()
    (tmp_path / "zeit.json").write_text(json.dumps({"meetings": []}))
    befunde, fehlend = check.absagen_kalender(tmp_path)
    assert befunde == [] and len(fehlend) == 1 and "termine.ics fehlt" in fehlend[0]


def test_check_sitzungen_nimmt_beide_zusaetze_ab(tmp_path):
    """check._sitzungen (Datenschutz) nimmt vor der Prüfung des Gremiums jeden Zusatz einer Absage ab: Das Gremium mit
    dem Namen einer Organisation bleibt ungeprüft wie in zeit.json. Ohne den neuen Zusatz in der Liste gälte
    „Arbeitskreis 7 (laut Sitzungsnamen abgesagt)“ als Gremium aus dem Namen, und die Zahl wäre ein Befund."""
    publish.write_calendar(tmp_path / "termine.ics",
                           [_sitzung("a", "Arbeitskreis 7", "Arbeitskreis - entfällt", hinweis="abgesagt"),
                            _sitzung("c", "Arbeitskreis 7", "Arbeitskreis", cancelled=True)], date(2026, 11, 21))
    summary = sorted(e["SUMMARY"] for e in check._ics_ereignisse(tmp_path / "termine.ics"))
    assert summary == ["Arbeitskreis 7 (abgesagt)", "Arbeitskreis 7 (laut Sitzungsnamen abgesagt)"]
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE organization (id TEXT, name TEXT)")
    db.execute("INSERT INTO organization VALUES ('o1', 'Arbeitskreis 7')")
    ohne, zahl = {}, {}
    assert check._sitzungen(tmp_path, db, maske.Maske([]), zahl, ohne) == set()
    db.close()
    assert ohne == {} and zahl == {"sitzungen": 2}


# --- Kette auf dem lokalen Testserver ---------------------------------------------------------------------------------

class _Tag(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 21)


# erfundene Sitzungen im Dezember 2026: Kennung → (Name, OParl cancelled, erwarteter Grund der Absage)
KETTE = {
    "k1": ("Probebeirat - Sitzung entfällt", False, "name"),
    "k2": ("Probebeirat", True, "oparl"),
    "k3": ("Probebeirat\nAchtung: Die Sitzung wurde abgesagt und fällt aus!", True, "oparl"),
    "k4": ("Probebeirat - verschoben", False, None),
    "k5": ("Probebeirat", False, None),
    "k6": ("Rat - ENTFÄLLT", False, "name"),
}


def test_kette_testserver_kalender_log_und_check(oparl, monkeypatch, capsys):
    """Abruf, Aufbau und Export mit dem Testserver: termine.ics kennzeichnet jede Absage nach ihrem Grund, das Log von
    `export` zählt sie getrennt, check (Absagen im Kalender, Datenschutz) ohne Befund."""
    b = oparl.b
    for i, (k, (name, cancelled, _)) in enumerate(KETTE.items(), 1):
        oparl.meetings.append({"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting",
                               "name": name, "start": f"2026-12-{i:02d}T16:00:00Z", "cancelled": cancelled,
                               **({"organization": [f"{b}/organizations/rat"]} if k == "k6" else {}),
                               "modified": "2026-11-01T08:00:00+01:00"})
    monkeypatch.setattr(publish, "date", _Tag)
    sessionnet.fetch_all()
    build.build()
    capsys.readouterr()
    export.export()
    log = capsys.readouterr().out
    # im Fenster ab 22.10.2026 nur die sechs erfundenen Sitzungen (die des Testservers liegt am 01.10.2026)
    zeile = "termine.ics: 6 Termine, davon ganztägig 0, abgesagt laut OParl 2, abgesagt laut Sitzungsnamen 2"
    assert log.splitlines().count(zeile) == 1 and log.count("termine.ics:") == 1, log
    base = config.EXPORT / config.STADT
    ics = {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(base / "termine.ics")}
    zusatz = {"oparl": " (abgesagt)", "name": " (laut Sitzungsnamen abgesagt)", None: ""}
    for k, (_, _, grund) in KETTE.items():
        assert ics[k]["STATUS"] == ("CANCELLED" if grund else "CONFIRMED"), k
        assert ics[k]["SUMMARY"] == ("Rat" if k == "k6" else "Probebeirat") + zusatz[grund], k
    zeit = {x["source_object"].rsplit("/", 1)[1]: x for x in json.loads((base / "zeit.json").read_text())["meetings"]}
    assert {k: export.absage(zeit[k]) for k in KETTE} == {k: g for k, (*_, g) in KETTE.items()}
    capsys.readouterr()
    assert check.absagen_kalender() == ([], [])
    assert ("Termine in termine.ics: 6, davon abgesagt laut OParl 2, abgesagt laut Sitzungsnamen 2\n"
            in capsys.readouterr().out)
    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_mit_testdaten(oparl, monkeypatch, capsys):
    """Die ganze Prüfung (`python -m pipeline check`) enthält die Prüfung der Absagen im Kalender: mit den Testdaten
    (tools/testdaten.py; ohne Absage, die Sitzungen heißen wie ihr Gremium) ohne Befund; ein eingeschleuster Zusatz in
    termine.ics ist ein Befund."""
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    _tool("testdaten").main()
    build.build()
    export.export()
    kontext.write()
    log = capsys.readouterr().out
    assert re.search(r"termine\.ics: \d+ Termine, davon ganztägig \d+, abgesagt laut OParl 0, abgesagt laut "
                     r"Sitzungsnamen 0\n", log), log
    check.check()
    out = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    n = re.search(r"\nAbsagen in termine\.ics \(export\.absage\)\nTermine in termine\.ics: (\d+), davon abgesagt laut "
                  r"OParl 0, abgesagt laut Sitzungsnamen 0\n", out)
    assert n and int(n.group(1)) > 0, out
    ics = config.EXPORT / config.STADT / "termine.ics"
    ics.write_text(_text(ics).replace("STATUS:CONFIRMED", "STATUS:CANCELLED", 1), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        check.check()
    assert ("Kalender: Termine in termine.ics, deren STATUS nicht der Absage der Sitzung in zeit.json folgt "
            "(export.absage; STATUS:CANCELLED genau bei OParl `cancelled` oder Hinweis „abgesagt“ aus dem Namen, sonst "
            "STATUS:CONFIRMED): 1") in str(e.value)


# --- Nachprüfung des Pull Request: Vermerke in TECHNIK.md, abgeschaltete Themenseiten -----------------------------------

def _technik():
    return (ROOT / "TECHNIK.md").read_text(encoding="utf-8")


def test_technik_vermerke_der_aelteren_offenen_punkte():
    """TECHNIK.md: Die älteren offenen Punkte zu termine.ics und audit_zeit.tsv in den Zeilen 20.11.2026 (4) und (7) der
    Entscheidungen tragen einen Vermerk, dass (9) sie bei Hinweis „abgesagt“ erledigt; ihr Wortlaut bleibt stehen. Was
    der Vermerk sagt, prüfen die Tests oben (Zusatz und STATUS:CANCELLED im Kalender, Bemerkung in audit_zeit.tsv,
    „verschoben“ unverändert)."""
    zeilen = {z.split(" | ", 2)[1][:3]: z for z in _technik().splitlines() if z.startswith("| 20.11.2026 | (")}
    vermerk = "Vermerk: bei Hinweis „abgesagt“ aus dem Namen erledigt durch 21.11.2026 (1) (c) (9)"
    assert ("Offen (Vermerk: erledigt durch 21.11.2026 (1) (c) (9)): ob `termine.ics` eine Sitzung mit Hinweis "
            "„abgesagt“ ebenfalls als abgesagt kennzeichnet (bisher nur bei `cancelled`).") in zeilen["(7)"]
    assert ("Betroffen: die Zusammenfassung in `termine.ics` (`SUMMARY` ohne „ (abgesagt)“, `STATUS:CONFIRMED`; der "
            f"ganze Name steht weiter in `DESCRIPTION`; {vermerk}, Zusatz „ (laut Sitzungsnamen abgesagt)“ und "
            "`STATUS:CANCELLED`; bei Hinweis „verschoben“") in zeilen["(4)"]
    assert (f"Ebenso `audit_zeit.tsv` (`export.time_audit_rows`: „Sitzung des Gremiums an diesem Tag“; {vermerk}, "
            "Bemerkung „…, laut Sitzungsnamen abgesagt“; bei Hinweis „verschoben“ zählt die Sitzung weiter ohne "
            "Zusatz).") in zeilen["(4)"]


def test_themenseite_abgeschaltet_wertet_nur_cancelled_aus(tmp_path, capsys):
    """Außerhalb von (9) und abgeschaltet (Freigabe `themenseiten`), so in TECHNIK.md vermerkt: dossier.daten lässt bei
    den kommenden Sitzungen der Themenseite nur OParl `cancelled` weg. Eine Sitzung mit Hinweis „abgesagt“ aus dem Namen
    bleibt dort, während der Themenkalender (publish.write_calendar mit export.absage) sie als abgesagt kennzeichnet.
    Ändert sich dossier.daten mit der Freigabe der Themenseiten, ist der Vermerk in TECHNIK.md anzupassen."""
    from pipeline import dossier
    from pipeline.themenseiten import ALLE
    t = ALLE[0]
    sitzungen = [_sitzung("a", "Bezirksvertretung Probe", "[Testdaten] Sitzung entfällt", hinweis="abgesagt",
                          tag="2026-12-10"),
                 _sitzung("c", "Bezirksvertretung Probe", cancelled=True, tag="2026-12-11")]
    assert all(dossier.sitzung_im_thema(t, m["gremium"]) for m in sitzungen)
    thema = dossier.daten(t, {}, {}, sitzungen, "2026-11-21", {})
    assert [m["source_object"] for m in thema["sitzungen"]] == [f"{M}/a"]
    publish.write_calendar(tmp_path / f"{t.key}.ics", sitzungen, date(2026, 11, 21))
    assert capsys.readouterr().out.endswith("abgesagt laut OParl 1, abgesagt laut Sitzungsnamen 1\n")
    ics = {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(tmp_path / f"{t.key}.ics")}
    assert ics["a"]["STATUS"] == ics["c"]["STATUS"] == "CANCELLED"
    assert ics["a"]["SUMMARY"] == "Bezirksvertretung Probe (laut Sitzungsnamen abgesagt)"
    assert ("Nicht angepasst (außerhalb von (9), abgeschaltet): `dossier.daten` (kommende Sitzungen der Themenseiten "
            "in `dossiers/<thema>.json`, Freigabe `themenseiten`) und `chat.organizations`") in _technik()
