"""Uhrzeit der Sitzungen in Kölner Zeit (Entscheidung 19.11.2026 (1) (D); vorher TECHNIK.md „Offen, nicht jetzt“ (2)):
`export._meetings` nahm die Uhrzeit roh aus dem Beginn (`start[11:16]`), das Datum dagegen in Kölner Zeit
(`process.local_day`); ein Beginn in UTC wie „…T16:00:00Z“ zeigte 16:00 statt 17:00 Uhr. Jetzt kommen Datum und Uhrzeit
aus demselben Zeitpunkt in Europe/Berlin (`process.local_time`); 00:00 Uhr in Köln heißt weiter: keine Uhrzeit.
`publish._utc` (termine.ics) liest einen Beginn ohne Zeitzone als Kölner Ortszeit, nicht in der Zeitzone des Rechners
(GitHub Actions: UTC). Das Log von `export` nennt die Sitzungen nach der Form ihres Beginns, nur Zahlen. Alle Sitzungen
sind erfunden (lokaler Testserver); keine Anfragen an die Stadt."""
import json
import os
import time
from datetime import date

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


# erfundene Sitzungen: Kennung → (Beginn laut Quelle, Tag und Uhrzeit in zeit.json, DTSTART in termine.ics oder None)
SITZUNGEN = {
    "z1": ("2026-11-19T16:00:00Z", "2026-11-19", "17:00", "20261119T160000Z"),
    "z2": ("2026-11-19T23:30:00Z", "2026-11-20", "00:30", "20261119T233000Z"),
    "z3": ("2026-11-20T23:00:00Z", "2026-11-21", None, "20261120T230000Z"),     # 00:00 Uhr in Köln: keine Uhrzeit
    "z4": ("2026-07-01T16:00:00Z", "2026-07-01", "18:00", None),                # vor dem Fenster von termine.ics
    "v1": ("2026-11-19T17:00:00+01:00", "2026-11-19", "17:00", "20261119T160000Z"),
    "o1": ("2026-11-19T17:00:00", "2026-11-19", "17:00", "20261119T160000Z"),
    "d1": ("2026-11-22", "2026-11-22", None, None),                             # nur Datum: nicht im Kalender
}


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
    export.export()
    log = capsys.readouterr().out
    zeile = "Sitzungen nach Form des Beginns: mit Z 4, mit Versatz 2, ohne Zeitzone 1, nur Datum 1"
    assert log.splitlines().count(zeile) == 1 and log.count("Sitzungen nach Form des Beginns") == 1, log
    out = config.EXPORT / config.STADT
    zeit = {m["source_object"].rsplit("/", 1)[1]: m for m in json.loads((out / "zeit.json").read_text())["meetings"]}
    assert {k: (zeit[k]["date"], zeit[k]["time"]) for k in SITZUNGEN} == {k: (t, u) for k, (_, t, u, _) in
                                                                          SITZUNGEN.items()}
    assert (zeit["1"]["date"], zeit["1"]["time"]) == ("2026-10-01", "17:00")
    ics = {}
    for block in (out / "termine.ics").read_bytes().decode("utf-8").split("BEGIN:VEVENT")[1:]:
        felder = dict(z.split(":", 1) for z in block.split("END:VEVENT")[0].split("\r\n") if ":" in z)
        ics[felder["UID"].rsplit("/", 1)[1]] = (felder["DTSTART"], felder["DTSTAMP"])
    assert ics == {k: (s, s) for k, (*_, s) in SITZUNGEN.items() if s}
