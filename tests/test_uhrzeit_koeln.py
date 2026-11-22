"""Uhrzeit der Sitzungen in Kölner Zeit (Entscheidung 19.11.2026 (1) (D); vorher TECHNIK.md „Offen, nicht jetzt“ (2)):
`export._meetings` nahm die Uhrzeit roh aus dem Beginn (`start[11:16]`), das Datum dagegen in Kölner Zeit
(`process.local_day`); ein Beginn in UTC wie „…T16:00:00Z“ zeigte 16:00 statt 17:00 Uhr. Jetzt kommen Datum und Uhrzeit
aus demselben Zeitpunkt in Europe/Berlin (`process.local_time`); 00:00 Uhr in Köln heißt weiter: keine Uhrzeit.
`publish._utc` (termine.ics) liest einen Beginn ohne Zeitzone als Kölner Ortszeit, nicht in der Zeitzone des Rechners
(GitHub Actions: UTC). Das Log von `export` nennt die Sitzungen nach der Form ihres Beginns, nur Zahlen.
Kalender (Entscheidung 19.11.2026 (2) (a)): Eine Sitzung ohne Uhrzeit (nur Datum oder 00:00 Uhr in Köln, dieselbe Regel
wie in zeit.json) steht in termine.ics als ganztägiger Termin am Kölner Kalendertag, ohne DTEND; ein Ende nur mit Datum,
der Platzhalter 23:59:59 Uhr in Kölner Ortszeit und ein Ende, das nicht nach dem Beginn liegt, ergeben kein DTEND.
Alle Sitzungen sind erfunden (lokaler Testserver); keine Anfragen an die Stadt."""
import importlib.util
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pipeline import build, config, export, process, publish, sessionnet


@pytest.fixture
def rechnerzone(request):
    """Zeitzone des Rechners, auf dem der Aufbau läuft (Standard UTC wie in GitHub Actions); die Ausgabe hängt nicht
    von ihr ab."""
    alt = os.environ.get("TZ")
    os.environ["TZ"] = getattr(request, "param", "UTC")
    time.tzset()
    yield os.environ["TZ"]
    if alt is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = alt
    time.tzset()


@pytest.mark.parametrize("beginn, tag, uhrzeit", [
    ("2026-11-19T16:00:00Z", "2026-11-19", "17:00"),         # Winterzeit: UTC + 1 Stunde
    ("2026-11-19T23:30:00Z", "2026-11-20", "00:30"),         # Tag und Uhrzeit aus demselben Zeitpunkt
    ("2026-07-01T16:00:00Z", "2026-07-01", "18:00"),         # Sommerzeit: UTC + 2 Stunden
    ("2026-11-19T17:00:00+01:00", "2026-11-19", "17:00"),    # Versatz wie Köln
    ("2026-07-01T17:00:00+01:00", "2026-07-01", "18:00"),    # Versatz, der im Sommer nicht Kölner Zeit ist
    ("2026-11-19T17:00:00", "2026-11-19", "17:00"),          # ohne Zeitzone: Kölner Ortszeit
    ("2026-11-19", "2026-11-19", None),                      # nur ein Datum: keine Uhrzeit
])
@pytest.mark.parametrize("rechnerzone", ["UTC", "America/New_York"], indirect=True)
def test_tag_und_uhrzeit_in_koelner_zeit(rechnerzone, beginn, tag, uhrzeit):
    assert (process.local_day(beginn), process.local_time(beginn)) == (tag, uhrzeit)


@pytest.mark.parametrize("rechnerzone", ["UTC", "America/New_York"], indirect=True)
def test_kalender_utc_ohne_zeitzone_als_koelner_zeit(rechnerzone):
    """termine.ics bleibt in UTC mit „Z“; ein Beginn ohne Zeitzone gilt als Kölner Ortszeit (vorher: Zeitzone des
    Rechners, in GitHub Actions UTC, also 17:00 Uhr statt 16:00 Uhr UTC)."""
    assert publish._utc("2026-11-19T17:00:00") == "20261119T160000Z"
    assert publish._utc("2026-07-01T18:00:00") == "20260701T160000Z"
    # mit Zeitzone wie bisher umgerechnet
    assert publish._utc("2026-11-19T17:00:00+01:00") == "20261119T160000Z"
    assert publish._utc("2026-11-19T16:00:00Z") == "20261119T160000Z"
    assert publish._utc("2026-11-19T23:30:00Z") == "20261119T233000Z"


class _Tag(date):
    """Tag des Aufbaus für das Fenster von termine.ics (ab 30 Tage davor), damit der Test nicht vom Kalender abhängt."""
    @classmethod
    def today(cls):
        return date(2026, 11, 19)


def _ereignisse(pfad):
    """VEVENT-Blöcke von termine.ics als {UID: {Feldname: Rest der Zeile mit Parametern}}, etwa „DTSTART“ →
    „;VALUE=DATE:20261121“ oder „:20261119T160000Z“ (eigener Leser des Tests). Prüft dabei die Form nach RFC 5545:
    Zeilenenden CRLF, Zeilen höchstens 75 Oktette, jedes Feld höchstens einmal je Termin."""
    roh = pfad.read_bytes()
    assert roh.endswith(b"\r\n") and b"\n" not in roh.replace(b"\r\n", b"")
    assert all(len(z) <= 75 for z in roh.split(b"\r\n"))
    out = {}
    for block in roh.decode("utf-8").replace("\r\n ", "").split("BEGIN:VEVENT")[1:]:
        zeilen = [re.match(r"([A-Z-]+)(.*)", z).groups() for z in block.split("END:VEVENT")[0].split("\r\n") if z]
        felder = dict(zeilen)
        assert len(felder) == len(zeilen), zeilen
        out[felder["UID"][1:]] = felder
    return out


# erfundene Sitzungen für den Kalender allein: Kennung → (Beginn, Ende oder None, DTSTART und DTEND als Zeile ohne
# Feldnamen oder None); Entscheidung 19.11.2026 (2) (a)
KALENDER = {
    "w0": ("2026-11-20T23:00:00Z", None, ";VALUE=DATE:20261121", None),       # 00:00 Uhr in Köln (Winter): ganztägig
    "s0": ("2026-07-01T22:00:00Z", None, ";VALUE=DATE:20260702", None),       # 00:00 Uhr in Köln (Sommer): ganztägig
    "d0": ("2026-11-22", None, ";VALUE=DATE:20261122", None),                 # nur Datum: ganztägig
    # ganztägig nie mit einem DTEND mit Uhrzeit, auch wenn die Quelle ein Ende nennt
    "w1": ("2026-11-21T00:00:00+01:00", "2026-11-21T18:00:00+01:00", ";VALUE=DATE:20261121", None),
    "d1": ("2026-11-23", "2026-11-23T18:00:00+01:00", ";VALUE=DATE:20261123", None),
    "p0": ("2026-11-20T16:00:00Z", "2026-11-20T22:59:59Z", ":20261120T160000Z", None),    # 23:59:59 Uhr in Köln
    "p1": ("2026-07-01T17:00:00+02:00", "2026-07-01T21:59:59Z", ":20260701T150000Z", None),  # ebenso im Sommer
    "p2": ("2026-11-20T17:00:00", "2026-11-20T23:59:59", ":20261120T160000Z", None),      # ohne Zeitzone: Kölner Zeit
    "e0": ("2026-11-20T16:00:00Z", "2026-11-20", ":20261120T160000Z", None),              # Ende nur mit Datum
    "e1": ("2026-11-20T16:00:00Z", "2026-11-20T15:00:00Z", ":20261120T160000Z", None),    # Ende vor dem Beginn
    "e2": ("2026-11-20T17:00:00+01:00", "2026-11-20T16:00:00Z", ":20261120T160000Z", None),  # Ende gleich Beginn
    "n0": ("2026-11-20T16:00:00Z", "2026-11-20T19:30:00Z", ":20261120T160000Z", ":20261120T193000Z"),
    "n1": ("2026-07-01T17:00:00+02:00", "2026-07-01T20:00:00+02:00", ":20260701T150000Z", ":20260701T180000Z"),
    "n2": ("2026-11-20T17:00:00", "2026-11-20T19:00:00", ":20261120T160000Z", ":20261120T180000Z"),
    # 23:59:59 Uhr in UTC ist 00:59:59 Uhr in Köln, also kein Platzhalter (vorher am Text der Quelle erkannt)
    "n3": ("2026-11-20T16:00:00Z", "2026-11-20T23:59:59Z", ":20261120T160000Z", ":20261120T235959Z"),
    # Tage der Zeitumstellung (29.03.2026 auf Sommerzeit, 25.10.2026 auf Winterzeit)
    "u0": ("2026-03-28T23:00:00Z", None, ";VALUE=DATE:20260329", None),       # 00:00 Uhr MEZ: ganztägig am 29.03.
    "u1": ("2026-10-24T22:00:00Z", None, ";VALUE=DATE:20261025", None),       # 00:00 Uhr MESZ: ganztägig am 25.10.
    "u2": ("2026-03-29T17:00:00+02:00", "2026-03-29T21:59:59Z", ":20260329T150000Z", None),  # 23:59:59 Uhr MESZ
    "u3": ("2026-10-25T17:00:00+01:00", "2026-10-25T22:59:59Z", ":20261025T160000Z", None),  # 23:59:59 Uhr MEZ
    "u4": ("2026-10-25T17:00:00+01:00", "2026-10-25T20:00:00+01:00", ":20261025T160000Z", ":20261025T190000Z"),
}


@pytest.mark.parametrize("rechnerzone", ["UTC", "America/New_York"], indirect=True)
def test_kalender_ganztaegig_und_ende(rechnerzone, tmp_path, capsys):
    """termine.ics (publish.write_calendar): ohne Uhrzeit ganztägig am Kölner Tag ohne DTEND, sonst Beginn und Ende in
    UTC; kein DTEND bei einem Ende nur mit Datum, beim Platzhalter 23:59:59 Uhr in Kölner Ortszeit und bei einem Ende,
    das nicht nach dem Beginn liegt. DTSTAMP ist der übergebene Zeitpunkt des Aufbaus in UTC, bei allen Terminen
    derselbe. Das Log nennt die Termine, nur Zahlen."""
    sitzungen = [{"date": process.local_day(beginn), "gremium": "Bezirksvertretung 4 (Ehrenfeld)",
                  "name": "[Testdaten] Sitzung", "cancelled": False, "web": None, "invitation": None,
                  "start": beginn, "end": ende, "source_object": f"https://example.invalid/oparl/meetings/{k}"}
                 for k, (beginn, ende, *_) in KALENDER.items()]
    publish.write_calendar(tmp_path / "termine.ics", sitzungen, date(2026, 3, 1),
                           datetime(2026, 11, 22, 21, 5, 7, tzinfo=timezone.utc))
    assert capsys.readouterr().out.splitlines() == [
        "termine.ics: 20 Termine, davon ganztägig 7, abgesagt laut OParl 0, abgesagt laut Sitzungsnamen 0"]
    ics = {k.rsplit("/", 1)[1]: e for k, e in _ereignisse(tmp_path / "termine.ics").items()}
    assert {k: (e["DTSTART"], e.get("DTEND")) for k, e in ics.items()} == {k: (s, e) for k, (_, _, s, e) in
                                                                           KALENDER.items()}
    # seit der Entscheidung 21.11.2026 (3) (#47 (2)) der Zeitpunkt des Aufbaus, nicht mehr der Beginn der Sitzung
    # (bis dahin hier gegen publish._utc(Beginn) geprüft; tests/test_kalender_zeitstempel.py)
    assert {k: e["DTSTAMP"] for k, e in ics.items()} == dict.fromkeys(KALENDER, ":20261122T210507Z")


# erfundene Sitzungen: Kennung → (Beginn laut Quelle, Tag und Uhrzeit in zeit.json, DTSTART in termine.ics als Zeile
# ohne „DTSTART“, mit Parametern, oder None)
SITZUNGEN = {
    "z1": ("2026-11-19T16:00:00Z", "2026-11-19", "17:00", ":20261119T160000Z"),
    "z2": ("2026-11-19T23:30:00Z", "2026-11-20", "00:30", ":20261119T233000Z"),
    # 00:00 Uhr in Köln: keine Uhrzeit in zeit.json, ganztägig in termine.ics am Kölner Tag (Entscheidung 19.11.2026 (2)
    # (a); vorher mit Beginn um Mitternacht)
    "z3": ("2026-11-20T23:00:00Z", "2026-11-21", None, ";VALUE=DATE:20261121"),
    "z4": ("2026-07-01T16:00:00Z", "2026-07-01", "18:00", None),                # vor dem Fenster von termine.ics
    "v1": ("2026-11-19T17:00:00+01:00", "2026-11-19", "17:00", ":20261119T160000Z"),
    "o1": ("2026-11-19T17:00:00", "2026-11-19", "17:00", ":20261119T160000Z"),
    "d1": ("2026-11-22", "2026-11-22", None, ";VALUE=DATE:20261122"),           # nur Datum: ganztägig (vorher nicht)
}


@pytest.mark.parametrize("rechnerzone", ["UTC", "America/New_York"], indirect=True)
def test_sitzungen_in_zeit_und_kalender(oparl, capsys, monkeypatch, rechnerzone):
    """Kette mit dem Testserver: zeit.json zeigt Tag und Uhrzeit in Kölner Zeit, termine.ics den Beginn in UTC, das Log
    von `export` einmal die Zahlen je Form des Beginns (dazu die Sitzung des Testservers mit Versatz „+02:00“)."""
    b = oparl.b
    for k, (beginn, *_) in SITZUNGEN.items():
        oparl.meetings.append({"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting",
                               "name": "Bezirksvertretung 4 (Ehrenfeld)", "start": beginn,
                               "organization": [f"{b}/organizations/bv4"], "modified": "2026-11-01T08:00:00+01:00"})
    monkeypatch.setattr(publish, "date", _Tag)
    sessionnet.fetch_all()
    build.build()
    capsys.readouterr()
    vorher = datetime.now(timezone.utc).replace(microsecond=0)
    export.export()
    nachher = datetime.now(timezone.utc)
    log = capsys.readouterr().out
    zeile = "Sitzungen nach Form des Beginns: mit Z 4, mit Versatz 2, ohne Zeitzone 1, nur Datum 1"
    assert log.splitlines().count(zeile) == 1 and log.count("Sitzungen nach Form des Beginns") == 1, log
    # Termine im Fenster: alle außer z4 und der Sitzung des Testservers (01.10.2026); ganztägig z3 und d1
    termine = "termine.ics: 6 Termine, davon ganztägig 2, abgesagt laut OParl 0, abgesagt laut Sitzungsnamen 0"
    assert log.splitlines().count(termine) == 1 and log.count("termine.ics") == 1, log
    out = config.EXPORT / config.STADT
    zeit = {m["source_object"].rsplit("/", 1)[1]: m for m in json.loads((out / "zeit.json").read_text())["meetings"]}
    assert {k: (zeit[k]["date"], zeit[k]["time"]) for k in SITZUNGEN} == {k: (t, u) for k, (_, t, u, _) in
                                                                          SITZUNGEN.items()}
    assert (zeit["1"]["date"], zeit["1"]["time"]) == ("2026-10-01", "17:00")
    ics = {k.rsplit("/", 1)[1]: e for k, e in _ereignisse(out / "termine.ics").items()}
    assert {k: e["DTSTART"] for k, e in ics.items()} == {k: s for k, (*_, s) in SITZUNGEN.items() if s}
    # DTSTAMP: seit der Entscheidung 21.11.2026 (3) (#47 (2)) bei allen Terminen derselbe Zeitpunkt in UTC, zu dem export
    # lief, auch bei ganztägigen Terminen (bis dahin der Beginn der Sitzung, hier gegen publish._utc(Beginn) geprüft,
    # bei d1 und z3 Mitternacht in Köln)
    stempel = {e["DTSTAMP"] for e in ics.values()}
    assert len(stempel) == 1 and re.fullmatch(r":\d{8}T\d{6}Z", next(iter(stempel)))
    assert vorher <= datetime.strptime(next(iter(stempel)), ":%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) <= nachher


@pytest.mark.parametrize("rechnerzone", ["UTC", "America/New_York"], indirect=True)
def test_testdaten_beginnen_um_17_uhr_koelner_zeit(oparl, monkeypatch, rechnerzone):
    """tools/testdaten.py schreibt den Beginn jeder Sitzung mit dem Versatz von Europe/Berlin für ihren Tag
    (Entscheidung 19.11.2026 (2) (b)): Alle Sitzungen beginnen um 17:00 Uhr Kölner Zeit, auch im Sommer (vorher
    „+01:00“ für jedes Datum, im Sommer also 18:00 Uhr). Die Testdaten reichen über Sommer und Winter."""
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "60"])
    spec = importlib.util.spec_from_file_location(
        "testdaten", Path(__file__).resolve().parents[1] / "tools" / "testdaten.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
    beginne = [m["start"] for m in json.loads(config.MEETINGS.read_text())]
    assert {process.local_time(b) for b in beginne} == {"17:00"}
    assert {b[-6:] for b in beginne} == {"+01:00", "+02:00"}
