"""DTSTAMP in termine.ics ist der Zeitpunkt des Aufbaus (Entscheidung 21.11.2026 (3), #47 (2)).

RFC 5545 (3.8.7.2) nennt bei einem Kalender mit METHOD (termine.ics: METHOD:PUBLISH) in DTSTAMP den Zeitpunkt, zu dem
das Objekt erstellt wurde, in UTC. Bis zum 22.11.2026 schrieb `publish.write_calendar` dort den Beginn der Sitzung in
UTC; jetzt tragen alle Termine einer Datei denselben Zeitpunkt des Aufbaus (`publish._zeitstempel`, für Tests über
`aufbau` übergeben, sonst jetzt in UTC auf die Sekunde). Alles andere im Kalender bleibt, wie es war. `check` prüft je
Termin genau eine Zeile DTSTAMP ohne Parameter, die Form und dass der Zeitpunkt in der Datei einheitlich ist
(`check.zeitstempel_kalender`), nur mit Zahlen. Alle Sitzungen, Gremien und Namen sind erfunden; keine Anfragen an die
Stadt."""
import importlib.util
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pipeline import build, check, config, export, kontext, publish

ROOT = Path(__file__).resolve().parents[1]
M = "https://example.invalid/oparl/meetings"
# erfundener Zeitpunkt des Aufbaus mit Mikrosekunden (DTSTAMP nur auf die Sekunde)
AUFBAU = datetime(2026, 11, 22, 21, 5, 7, 654321, tzinfo=timezone.utc)
STEMPEL = "20261122T210507Z"


def _sitzung(k, beginn, gremium="Probebeirat", ende=None, cancelled=False, hinweis=None, web=True):
    """Erfundene Sitzung in der Form von export._meetings."""
    m = {"date": beginn[:10], "gremium": gremium, "name": f"[Testdaten] {gremium}", "cancelled": cancelled,
         "web": f"https://example.invalid/sitzung/{k}" if web else None, "invitation": None, "start": beginn,
         "end": ende, "source_object": f"{M}/{k}"}
    return {**m, "hinweis": hinweis} if hinweis else m


# verschiedene Formen: mit Uhrzeit und Ende, ganztägig (nur Datum, 00:00 Uhr in Köln), Sommerzeit, abgesagt laut OParl
# und laut Sitzungsnamen, ohne Link
SITZUNGEN = [
    _sitzung("s1", "2026-11-25T16:00:00Z", ende="2026-11-25T19:30:00Z"),
    _sitzung("s2", "2026-11-26"),
    _sitzung("s3", "2026-11-25T23:00:00Z", gremium="Bezirksvertretung 4 (Ehrenfeld)"),
    _sitzung("s4", "2027-07-01T17:00:00+02:00", gremium="Rat"),
    _sitzung("s5", "2026-12-03T16:00:00Z", cancelled=True),
    _sitzung("s6", "2026-12-04T16:00:00Z", hinweis="abgesagt", web=False),
]


def _ereignisse(pfad):
    return {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(pfad)}


def _zeilen(pfad):
    """Physische Zeilen der Datei, wie sie geschrieben sind (CRLF, gefaltet)."""
    return pfad.read_bytes().decode("utf-8").split("\r\n")


def test_ein_zeitstempel_fuer_alle_termine(tmp_path, capsys):
    """Alle Termine der Datei tragen in DTSTAMP denselben übergebenen Zeitpunkt des Aufbaus in UTC, auf die Sekunde,
    auch ganztägige und abgesagte; je Termin genau eine Zeile DTSTAMP. Die Zeile im Log bleibt, wie sie war."""
    publish.write_calendar(tmp_path / "termine.ics", SITZUNGEN, date(2026, 11, 21), AUFBAU)
    assert capsys.readouterr().out.splitlines() == [
        "termine.ics: 6 Termine, davon ganztägig 2, abgesagt laut OParl 1, abgesagt laut Sitzungsnamen 1"]
    ics = _ereignisse(tmp_path / "termine.ics")
    assert {k: e["DTSTAMP"] for k, e in ics.items()} == {f"s{i}": STEMPEL for i in range(1, 7)}
    zeilen = _zeilen(tmp_path / "termine.ics")
    assert [z for z in zeilen if z.startswith("DTSTAMP")] == [f"DTSTAMP:{STEMPEL}"] * 6
    assert zeilen.count("BEGIN:VEVENT") == 6
    assert re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", STEMPEL) and publish._zeitstempel(AUFBAU) == STEMPEL


def test_zeitpunkt_mit_zeitzone_wird_utc_ohne_zeitzone_fehler(tmp_path, capsys):
    """Ein übergebener Zeitpunkt mit anderer Zeitzone steht in UTC da (Winter und Sommer in Köln); ohne Zeitzone bricht
    der Aufbau ab, bevor eine Datei entsteht, statt von der Zeitzone des Rechners abzuhängen."""
    berlin = ZoneInfo("Europe/Berlin")
    assert publish._zeitstempel(datetime(2026, 11, 22, 22, 5, 7, tzinfo=berlin)) == STEMPEL
    assert publish._zeitstempel(datetime(2026, 7, 1, 12, 0, 0, tzinfo=berlin)) == "20260701T100000Z"
    assert publish._zeitstempel(datetime(2026, 11, 22, 16, 5, 7, tzinfo=timezone(timedelta(hours=-5)))) == STEMPEL
    with pytest.raises(ValueError, match="ohne Zeitzone"):
        publish._zeitstempel(datetime(2026, 11, 22, 21, 5, 7))
    with pytest.raises(ValueError, match="ohne Zeitzone"):
        publish.write_calendar(tmp_path / "termine.ics", SITZUNGEN, date(2026, 11, 21), datetime(2026, 11, 22))
    assert not (tmp_path / "termine.ics").exists() and capsys.readouterr().out == ""


@pytest.fixture
def rechnerzone(request):
    """Zeitzone des Rechners, auf dem der Aufbau läuft; die Ausgabe hängt nicht von ihr ab."""
    alt = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    yield request.param
    if alt is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = alt
    time.tzset()


# erfundene Sitzungen im Januar 2000: Ihr Beginn fällt nie mit dem Zeitpunkt eines Testlaufs zusammen (Tag des Aufbaus
# 01.01.2000, das Fenster ab 30 Tagen davor schließt sie ein)
SITZUNGEN_2000 = [
    _sitzung("j1", "2000-01-10T16:00:00Z", ende="2000-01-10T19:30:00Z"),
    _sitzung("j2", "2000-01-11"),
    _sitzung("j3", "2000-01-12T17:00:00+01:00", cancelled=True),
]


@pytest.mark.parametrize("rechnerzone", ["UTC", "America/New_York", "Asia/Tokyo"], indirect=True)
def test_ohne_angabe_jetzt_in_utc(rechnerzone, tmp_path, capsys):
    """Ohne `aufbau` ist DTSTAMP jetzt in UTC auf die Sekunde, bei allen Terminen derselbe, in jeder Zeitzone des
    Rechners; nicht mehr der Beginn der Sitzung. Die erfundenen Sitzungen liegen im Januar 2000, ihr Beginn kann also
    nicht in den Zeitraum des Aufrufs fallen; so hängt das Ergebnis nicht von der Uhrzeit des Testlaufs ab."""
    vorher = datetime.now(timezone.utc).replace(microsecond=0)
    publish.write_calendar(tmp_path / "termine.ics", SITZUNGEN_2000, date(2000, 1, 1))
    nachher = datetime.now(timezone.utc)
    capsys.readouterr()
    ics = _ereignisse(tmp_path / "termine.ics")
    assert sorted(ics) == ["j1", "j2", "j3"]
    werte = {e["DTSTAMP"] for e in ics.values()}
    assert len(werte) == 1
    wert = werte.pop()
    assert re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", wert)
    assert vorher <= datetime.strptime(wert, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) <= nachher
    assert wert not in {publish._utc(m["start"]) for m in SITZUNGEN_2000}


def test_ohne_angabe_feste_uhr_auch_im_beginn_einer_sitzung(tmp_path, capsys, monkeypatch):
    """Mit einer festen Uhr genau im Beginn einer Sitzung (s1, 25.11.2026, 16:00:00,4 Uhr UTC) steht dieser Zeitpunkt
    auf die Sekunde in DTSTAMP, bei allen Terminen: Der Wert kommt von der Uhr, nicht aus dem Beginn, und fällt dann
    nur zufällig mit ihm zusammen."""
    jetzt = datetime(2026, 11, 25, 16, 0, 0, 400000, tzinfo=timezone.utc)

    class FesteUhr(datetime):
        @classmethod
        def now(cls, tz=None):
            return jetzt if tz is None else jetzt.astimezone(tz)

    monkeypatch.setattr(publish, "datetime", FesteUhr)
    publish.write_calendar(tmp_path / "termine.ics", SITZUNGEN, date(2026, 11, 21))
    capsys.readouterr()
    assert {k: e["DTSTAMP"] for k, e in _ereignisse(tmp_path / "termine.ics").items()} == {
        f"s{i}": "20261125T160000Z" for i in range(1, 7)}


def test_nur_dtstamp_haengt_vom_aufbau_ab(tmp_path, capsys):
    """Zwei Aufbauten mit verschiedenem Zeitpunkt: Die Dateien unterscheiden sich genau in den Zeilen DTSTAMP, je Termin
    einer; alles andere ist byteweise gleich."""
    publish.write_calendar(tmp_path / "a.ics", SITZUNGEN, date(2026, 11, 21), AUFBAU)
    publish.write_calendar(tmp_path / "b.ics", SITZUNGEN, date(2026, 11, 21), AUFBAU + timedelta(days=400, seconds=1))
    capsys.readouterr()
    a, b = _zeilen(tmp_path / "a.ics"), _zeilen(tmp_path / "b.ics")
    assert len(a) == len(b)
    anders = [(x, y) for x, y in zip(a, b) if x != y]
    assert anders == [(f"DTSTAMP:{STEMPEL}", "DTSTAMP:20271227T210508Z")] * 6


# Ausgabe von publish.write_calendar auf 4db8198 (vor dieser Änderung) für die drei erfundenen Sitzungen unten, Zeile für
# Zeile: DTSTAMP war der Beginn der Sitzung in UTC, beim ganztägigen Termin Mitternacht in Köln
VORHER = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Ratsatlas Köln//Sitzungskalender//DE",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Sitzungen Rat\\, Ausschüsse und Bezirksvertretungen Köln",
    "X-WR-TIMEZONE:Europe/Berlin",
    "BEGIN:VEVENT",
    "UID:https://example.invalid/oparl/meetings/g1",
    "DTSTAMP:20261125T160000Z",
    "DTSTART:20261125T160000Z",
    "DTEND:20261125T193000Z",
    "SUMMARY:Probebeirat",
    "DESCRIPTION:[Testdaten] Probebeirat\\nTagesordnung: https://example.invalid/",
    " sitzung/g1\\nEinladung: https://example.invalid/einladung/g1\\nQuelle: OParl",
    " -API der Stadt Köln\\; Datenquelle: Stadt Köln – offenedaten-koeln.de",
    "STATUS:CONFIRMED",
    "URL:https://example.invalid/sitzung/g1",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "UID:https://example.invalid/oparl/meetings/g2",
    "DTSTAMP:20261125T230000Z",
    "DTSTART;VALUE=DATE:20261126",
    "SUMMARY:Bezirksvertretung 4 (Ehrenfeld)",
    "DESCRIPTION:[Testdaten] Bezirksvertretung\\nTagesordnung noch nicht veröffe",
    " ntlicht.\\nQuelle: OParl-API der Stadt Köln\\; Datenquelle: Stadt Köln –",
    "  offenedaten-koeln.de",
    "STATUS:CONFIRMED",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "UID:https://example.invalid/oparl/meetings/g3",
    "DTSTAMP:20261127T160000Z",
    "DTSTART:20261127T160000Z",
    "SUMMARY:Arbeitskreis für Grünflächen\\, Spielplätze\\; Straßenbäume (la",
    " ut Sitzungsnamen abgesagt)",
    "DESCRIPTION:Arbeitskreis für Grünflächen - entfällt\\nTagesordnung: http",
    " s://example.invalid/sitzung/g3\\nQuelle: OParl-API der Stadt Köln\\; Datenq",
    " uelle: Stadt Köln – offenedaten-koeln.de",
    "STATUS:CANCELLED",
    "URL:https://example.invalid/sitzung/g3",
    "END:VEVENT",
    "END:VCALENDAR",
    "",
]


def test_uebrige_felder_wie_vorher(tmp_path, capsys):
    """Gegen die Ausgabe von 4db8198: Kopf, UID, DTSTART und DTEND, Zusammenfassung mit Zusatz, Beschreibung, STATUS,
    URL, Maskierung und Faltung auf 75 Oktette sind unverändert; geändert sind nur die drei Zeilen DTSTAMP."""
    sitzungen = [
        {**_sitzung("g1", "2026-11-25T16:00:00Z", ende="2026-11-25T19:30:00Z"),
         "invitation": "https://example.invalid/einladung/g1"},
        {**_sitzung("g2", "2026-11-26", gremium="Bezirksvertretung 4 (Ehrenfeld)", web=False),
         "name": "[Testdaten] Bezirksvertretung"},
        {**_sitzung("g3", "2026-11-27T16:00:00Z", gremium="Arbeitskreis für Grünflächen, Spielplätze; Straßenbäume",
                    hinweis="abgesagt"), "name": "Arbeitskreis für Grünflächen - entfällt"},
    ]
    publish.write_calendar(tmp_path / "termine.ics", sitzungen, date(2026, 11, 21), AUFBAU)
    capsys.readouterr()
    erwartet = [f"DTSTAMP:{STEMPEL}" if z.startswith("DTSTAMP:") else z for z in VORHER]
    assert _zeilen(tmp_path / "termine.ics") == erwartet
    assert sum(x != y for x, y in zip(VORHER, erwartet)) == 3


# --- check: Form und Einheitlichkeit von DTSTAMP --------------------------------------------------------------------

@pytest.mark.parametrize("wert, gueltig", [
    ("20261122T210507Z", True),
    ("20261231T235960Z", True),    # Schaltsekunde (RFC 5545, 3.3.12)
    ("20280229T120000Z", True),    # Schalttag
    ("20261122T210507", False),    # ohne „Z“: Ortszeit ohne Zone, kein Zeitpunkt in UTC
    ("20261122T210507z", False),
    ("20261122", False),           # nur ein Datum
    ("20261322T210507Z", False),   # Monat 13
    ("20260229T120000Z", False),   # 29. Februar in einem Jahr ohne Schalttag
    ("20261122T240000Z", False),   # Stunde 24
    ("20261122T216007Z", False),   # Minute 60
    ("20261122T210561Z", False),   # Sekunde 61
    ("2026-11-22T21:05:07Z", False),
    (" 20261122T210507Z", False),
    ("２０２６１１２２T210507Z", False),   # Ziffern außerhalb von ASCII
    ("", False),
    (None, False),
])
def test_utc_zeitpunkt(wert, gueltig):
    assert check._utc_zeitpunkt(wert) is gueltig


def _kalender(base, aufbau=AUFBAU):
    base.mkdir(parents=True, exist_ok=True)
    publish.write_calendar(base / "termine.ics", SITZUNGEN, date(2026, 11, 21), aufbau)


def test_check_ohne_befund(tmp_path, capsys):
    """Ein Kalender von write_calendar ergibt keinen Befund; die Ausgabe ist eine Zeile nach einer Leerzeile, nur
    Zahlen."""
    _kalender(tmp_path)
    capsys.readouterr()
    assert check.zeitstempel_kalender(tmp_path) == []
    assert capsys.readouterr().out == ("\nDTSTAMP in termine.ics (Zeitpunkt des Aufbaus in UTC): 6 Termine, ohne "
                                       "gültigen Zeitpunkt 0, verschiedene Zeitpunkte 1\n")


def _dtstamp_zeilen(pfad, neu):
    """Ersetzt die Zeile DTSTAMP je Termin durch physische Zeilen (Kennung → Liste der Zeilen, ohne CRLF; eine leere
    Liste entfernt die Zeile)."""
    teile = pfad.read_bytes().decode("utf-8").split("BEGIN:VEVENT")
    for i, teil in enumerate(teile[1:], 1):
        k = re.search(r"UID:\S+/(\w+)\r\n", teil).group(1)
        if k in neu:
            assert teil.count(f"DTSTAMP:{STEMPEL}\r\n") == 1
            teile[i] = teil.replace(f"DTSTAMP:{STEMPEL}\r\n", "".join(f"{z}\r\n" for z in neu[k]))
    pfad.write_bytes("BEGIN:VEVENT".join(teile).encode("utf-8"))


def _dtstamp_ersetzen(pfad, neu):
    """Ersetzt DTSTAMP je Termin (Kennung → neuer Wert; None entfernt die Zeile)."""
    _dtstamp_zeilen(pfad, {k: [] if v is None else [f"DTSTAMP:{v}"] for k, v in neu.items()})


def test_check_meldet_gemischte_und_ungueltige_nur_mit_zahlen(tmp_path, capsys):
    """Eingeschleust: ein anderer gültiger Zeitpunkt, eine Schaltsekunde (gültig, ebenfalls ein anderer Zeitpunkt), ein
    Wert ohne „Z“, einer mit Monat 13, einer ohne DTSTAMP. Befunde nur mit Zahlen, ohne Namen und Kennungen."""
    _kalender(tmp_path)
    _dtstamp_ersetzen(tmp_path / "termine.ics", {"s2": "20261123T080000Z", "s3": "20261231T235960Z",
                                                 "s4": "20261122T210507", "s5": "20261322T210507Z", "s6": None})
    capsys.readouterr()
    befunde = check.zeitstempel_kalender(tmp_path)
    out = capsys.readouterr().out
    assert befunde == [
        "Kalender: Termine in termine.ics ohne DTSTAMP als gültigen Zeitpunkt in UTC (JJJJMMTTTHHMMSSZ, RFC 5545): 3",
        "Kalender: DTSTAMP in termine.ics nicht bei allen Terminen derselbe Zeitpunkt des Aufbaus (verschiedene "
        "Zeitpunkte): 3"]
    assert out == ("\nDTSTAMP in termine.ics (Zeitpunkt des Aufbaus in UTC): 6 Termine, ohne gültigen Zeitpunkt 3, "
                   "verschiedene Zeitpunkte 3\n")
    for teil in ("Probebeirat", "Rat", "example.invalid", "meetings/", "s2"):
        assert teil not in out and teil not in " ".join(befunde), teil


def test_check_meldet_dtstamp_aus_dem_beginn(tmp_path, capsys):
    """Ein Kalender nach der Regel bis zum 22.11.2026 (DTSTAMP aus dem Beginn der Sitzung) ist ein Befund: sechs
    Sitzungen mit fünf verschiedenen Beginnen in UTC (s2 und s3 beginnen um Mitternacht in Köln am 26.11.2026)."""
    _kalender(tmp_path)
    _dtstamp_ersetzen(tmp_path / "termine.ics", {m["source_object"].rsplit("/", 1)[1]: publish._utc(m["start"])
                                                 for m in SITZUNGEN})
    capsys.readouterr()
    assert check.zeitstempel_kalender(tmp_path) == [
        "Kalender: DTSTAMP in termine.ics nicht bei allen Terminen derselbe Zeitpunkt des Aufbaus (verschiedene "
        "Zeitpunkte): 5"]


@pytest.mark.parametrize("zeilen, wert", [
    (["UID:x", f"DTSTAMP:{STEMPEL}", "DTSTART:20261125T160000Z"], STEMPEL),
    ([f"dtstamp:{STEMPEL}"], STEMPEL),                                  # Feldname ohne Rücksicht auf Schreibung (3.1)
    (["SUMMARY:DTSTAMP:20200101T000000Z", f"DTSTAMP:{STEMPEL}"], STEMPEL),    # nur im Text eines anderen Feldes
    ([f"DTSTAMPX:{STEMPEL}"], None),                                    # anderer Feldname, also kein DTSTAMP
    (["DTSTART:20261125T160000Z"], None),                               # kein DTSTAMP
    ([], None),
    (["DTSTAMP:20261122T210507", f"DTSTAMP:{STEMPEL}"], None),          # doppelt, der erste ungültig
    ([f"DTSTAMP:{STEMPEL}", "DTSTAMP:20200101T000000Z"], None),         # doppelt, ein anderer gültiger Zeitpunkt
    ([f"DTSTAMP:{STEMPEL}", f"DTSTAMP:{STEMPEL}"], None),               # doppelt, gleich
    ([f"DTSTAMP:{STEMPEL}", f"dtstamp:{STEMPEL}"], None),               # doppelt, anders geschrieben
    ([f"DTSTAMP;TZID=Europe/Berlin:{STEMPEL}"], None),                  # TZID bei UTC nicht erlaubt (3.2.19)
    ([f"DTSTAMP;VALUE=DATE-TIME:{STEMPEL}"], None),                     # Parameter schreibt write_calendar nie
    (["DTSTAMP"], None),
    ([f"DTSTAMP :{STEMPEL}"], None),
])
def test_dtstamp_genau_eine_zeile_ohne_parameter(zeilen, wert):
    assert check._dtstamp(zeilen) == wert


def test_check_meldet_doppelte_zeilen_und_parameter(tmp_path, capsys):
    """Eingeschleust in fünf von sechs Terminen: eine zweite Zeile DTSTAMP nach einem Wert ohne „Z“, eine zweite mit
    einem anderen gültigen Zeitpunkt, eine zweite klein geschrieben, TZID am Feldnamen, ein anderer Parameter. Jeder
    dieser Termine zählt als ohne gültigen Zeitpunkt (_ics_ereignisse sähe nur die letzte Zeile ohne Parameter); die
    zweiten Werte zählen nicht als weitere Zeitpunkte. Befunde nur mit Zahlen."""
    _kalender(tmp_path)
    _dtstamp_zeilen(tmp_path / "termine.ics", {
        "s1": ["DTSTAMP:20261122T210507", f"DTSTAMP:{STEMPEL}"],
        "s2": [f"DTSTAMP:{STEMPEL}", "DTSTAMP:20200101T000000Z"],
        "s3": [f"DTSTAMP:{STEMPEL}", f"dtstamp:{STEMPEL}"],
        "s4": [f"DTSTAMP;TZID=Europe/Berlin:{STEMPEL}"],
        "s5": [f"DTSTAMP;X-PROBE=1:{STEMPEL}"]})
    assert {e["DTSTAMP"] for e in check._ics_ereignisse(tmp_path / "termine.ics")} == {STEMPEL, "20200101T000000Z"}
    capsys.readouterr()
    befunde = check.zeitstempel_kalender(tmp_path)
    assert befunde == [
        "Kalender: Termine in termine.ics ohne DTSTAMP als gültigen Zeitpunkt in UTC (JJJJMMTTTHHMMSSZ, RFC 5545): 5"]
    assert capsys.readouterr().out == ("\nDTSTAMP in termine.ics (Zeitpunkt des Aufbaus in UTC): 6 Termine, ohne "
                                       "gültigen Zeitpunkt 5, verschiedene Zeitpunkte 1\n")


def test_check_entfaltet_zeilen(tmp_path, capsys):
    """Gezählt werden entfaltete Zeilen (RFC 5545, 3.1): eine auf zwei Zeilen gefaltete Zeile DTSTAMP zählt einmal, eine
    Fortsetzungszeile, die mit „DTSTAMP:“ beginnt, gehört zur Zeile davor und zählt nicht; ein klein geschriebener
    Feldname gilt. Kein Befund."""
    _kalender(tmp_path)
    _dtstamp_zeilen(tmp_path / "termine.ics", {
        "s1": ["DTSTA", f" MP:{STEMPEL}"],
        "s2": [f"DTSTAMP:{STEMPEL}", "X-PROBE:a", " DTSTAMP:20200101T000000Z"],
        "s3": [f"dtstamp:{STEMPEL}"]})
    capsys.readouterr()
    assert check.zeitstempel_kalender(tmp_path) == []
    assert capsys.readouterr().out == ("\nDTSTAMP in termine.ics (Zeitpunkt des Aufbaus in UTC): 6 Termine, ohne "
                                       "gültigen Zeitpunkt 0, verschiedene Zeitpunkte 1\n")


def test_check_ohne_datei_und_ohne_termine(tmp_path, capsys):
    """Ohne termine.ics und ohne Termine nichts zu prüfen, kein Befund; je eine Zeile."""
    assert check.zeitstempel_kalender(tmp_path) == []
    assert capsys.readouterr().out == "\nDTSTAMP in termine.ics: keine Datei, nichts zu prüfen\n"
    publish.write_calendar(tmp_path / "termine.ics", [], date(2026, 11, 21), AUFBAU)
    capsys.readouterr()
    assert check.zeitstempel_kalender(tmp_path) == []
    assert capsys.readouterr().out == ("\nDTSTAMP in termine.ics (Zeitpunkt des Aufbaus in UTC): 0 Termine, ohne "
                                       "gültigen Zeitpunkt 0, verschiedene Zeitpunkte 0\n")


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ganze_pruefung_mit_testdaten(oparl, monkeypatch, capsys):
    """Die ganze Prüfung (`python -m pipeline check`) enthält die Prüfung von DTSTAMP: Mit den Testdaten
    (tools/testdaten.py) tragen alle Termine den Zeitpunkt, zu dem export lief, ohne Befund; ein eingeschleuster
    anderer Zeitpunkt ist ein Befund."""
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    _tool("testdaten").main()
    build.build()
    vorher = datetime.now(timezone.utc).replace(microsecond=0)
    export.export()
    nachher = datetime.now(timezone.utc)
    kontext.write()
    capsys.readouterr()
    ics = config.EXPORT / config.STADT / "termine.ics"
    werte = {e["DTSTAMP"] for e in check._ics_ereignisse(ics)}
    assert len(werte) == 1
    assert vorher <= datetime.strptime(next(iter(werte)), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) <= nachher
    check.check()
    out = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    n = re.search(r"\nDTSTAMP in termine\.ics \(Zeitpunkt des Aufbaus in UTC\): (\d+) Termine, ohne gültigen "
                  r"Zeitpunkt 0, verschiedene Zeitpunkte 1\n", out)
    assert n and int(n.group(1)) > 1, out
    text = ics.read_bytes().decode("utf-8")
    ics.write_bytes(text.replace(f"DTSTAMP:{next(iter(werte))}", "DTSTAMP:20200101T000000Z", 1).encode("utf-8"))
    with pytest.raises(SystemExit) as e:
        check.check()
    assert ("Kalender: DTSTAMP in termine.ics nicht bei allen Terminen derselbe Zeitpunkt des Aufbaus (verschiedene "
            "Zeitpunkte): 2") in str(e.value)
