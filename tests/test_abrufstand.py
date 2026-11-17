"""Fortschritt des Abrufs (tools/abrufstand.py, Schritt in pages.yml gleich nach dem Sichern des Abrufzustands): nur
Zahlen und Zustände aus zustand_abruf.json, STAND.json und abrufstatistik.tsv; fehlende oder unlesbare Dateien halten
den Lauf nie an. Dateien schreibt der Test selbst (erfunden) oder der Abruf gegen den lokalen Testserver; keine
Anfragen an die Stadt."""
import csv
import importlib.util
import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import abruf, config, sessionnet

ROOT = config.ROOT
JETZT = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
# Texte, die in Meldungen stehen können, aber nie in der Ausgabe erscheinen dürfen (erfunden)
GEHEIM = ("Erfundener Titel Musterstraße 12", "geheim", "token", "anker", "nutzer")
BASIS = "https://oparl.example.invalid/oparl/bodies/stadtverwaltung_koeln"


def _modul():
    spec = importlib.util.spec_from_file_location("abrufstand", ROOT / "tools" / "abrufstand.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture
def stand(monkeypatch):
    monkeypatch.setattr(abruf, "uhr", lambda: JETZT)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return _modul()


def _pfade(tmp_path):
    return tmp_path / "zustand_abruf.json", tmp_path / "STAND.json", tmp_path / "abrufstatistik.tsv"


def _aufruf(modul, tmp_path, capsys, *weitere):
    z, s, t = _pfade(tmp_path)
    assert modul.main(["--zustand", str(z), "--stand", str(s), "--statistik", str(t), *weitere]) == 0
    return capsys.readouterr().out


def _statistik(pfad, zeilen):
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, sessionnet.STAT_SPALTEN, delimiter="\t", lineterminator="\n", restval="")
        w.writeheader()
        w.writerows(zeilen)


def _zeile(datum, liste, modus, seiten, objekte, anfragen, ergebnis, **weitere):
    return {"datum": datum, "liste": liste, "modus": modus, "seiten": seiten, "objekte": objekte,
            "anfragen": anfragen, "ergebnis": ergebnis, **weitere}


def test_ohne_dateien(stand, tmp_path, capsys, monkeypatch):
    """Erster Lauf ohne Zwischenspeicher: alles „fehlt“, kein Fehler, Zusammenfassung trotzdem geschrieben."""
    zusammenfassung = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(zusammenfassung))
    out = _aufruf(stand, tmp_path, capsys)
    assert "zustand_abruf.json fehlt; STAND.json fehlt; abrufstatistik.tsv fehlt" in out
    assert "Letzte Nacht mit Anfragen: keine in der Abrufstatistik" in out
    assert out.count("noch kein vollständiger Abruf") == 3
    assert "Verbleibende Nächte (Vorlagen): unbekannt" in out and "abruf_ok: nein" in out
    assert "Nächte mit möglicher Sperre: 0 von 3; keine Pause" in out
    md = zusammenfassung.read_text(encoding="utf-8")
    assert md.startswith("### Abrufstand") and "| Vorlagen (`papers`) | noch kein vollständiger Abruf |" in md


@pytest.mark.parametrize("zustand, stand_json, tsv", [
    ("{kaputt", "[1, 2]", b"\xff\xfe kein UTF-8"),
    ("[]", "null", "spalte\tandere\n1\t2\n"),
    ("", "", ""),
    ('{"sperre_verdacht": "x", "listenfehler": {"naechte": "drei", "zuletzt": 5}, "tlsfehler": [1], '
     '"papers_fortsetzung": [1], "meetings_fortsetzung": {"naechste": 7, "seiten": -1, "start": "gestern"}, '
     '"letzter_abbruch": 5, "nicht_vor": "morgen", "papers": "gestern", "organizations": {"a": 1}}',
     '{"abruf_ok": "irgendwann", "abruf_fehler": "Text", "abruf_hinweis": {"zeit": 3}, '
     '"abruf_uebersprungen": {"zeit": "2026-11-16T08:00:00+00:00", "grund": {"titel": "Erfundener Titel '
     'Musterstraße 12"}}, "abruf_warnungen": [1]}',
     "datum\tliste\tseiten\tobjekte\tanfragen\tergebnis\n"
     "kein datum\tpapers\tx\t-5\t\tok\n2026-11-15T22:10:00+00:00\tpapers\t\t\tviele\t\n"
     "2026-11-15T22:11:00+00:00\tpapers\t1\t2\t3\t4\t5\t6\n2026-11-15T22:12:00+00:00\n"),
    ("{}", "{}", "datum\tliste\n" + "x" * 200_000 + "\tpapers\n"),
])
def test_unlesbare_dateien_halten_den_lauf_nicht_an(stand, tmp_path, capsys, monkeypatch, zustand, stand_json, tsv):
    """Unlesbare Dateien, falsche Formen und Werte: Ausgabe mit „unlesbar“ bzw. „unbekannt“, Exit-Code 0, keine
    Meldungstexte; eine Zusammenfassung, die sich nicht schreiben lässt (Verzeichnis), nur als Warnung."""
    z, s, t = _pfade(tmp_path)
    z.write_text(zustand, encoding="utf-8")
    s.write_text(stand_json, encoding="utf-8")
    t.write_bytes(tsv) if isinstance(tsv, bytes) else t.write_text(tsv, encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))   # ein Verzeichnis: nicht schreibbar
    out = _aufruf(stand, tmp_path, capsys)
    assert out.startswith("Abrufstand") and "Abrufstand nicht ermittelt" not in out
    assert "::warning::Zusammenfassung nicht geschrieben (IsADirectoryError)" in out
    assert not any(g in out for g in GEHEIM)
    if zustand.startswith('{"sperre_verdacht"'):
        assert "Nächte mit möglicher Sperre: unlesbar; unlesbar (gilt beim nächsten Lauf als Pause)" in out
        assert "Nächte mit fehlerhafter Liste: unlesbar (gilt als 3)" in out
        assert "Retry-After: unlesbar" in out and "Letzter Abbruch: unlesbar" in out
        assert "Fortsetzung: unlesbar" in out and "Seite unbekannt (Adresse unlesbar)" in out
        assert "abruf_ok: unlesbar" in out and "Grund unlesbar" in out
        assert "Zeitpunkt des letzten Abrufs unlesbar" in out


def test_vollabruf_ueber_mehrere_naechte(stand, tmp_path, capsys, monkeypatch):
    """Vollabruf der Vorlagen in der zweiten Nacht: Anfragen und neu gelesene Objekte dieser Nacht, Seiten bisher und
    Stelle der Fortsetzung aus dem Zustand, Adresse ohne Zugangsdaten, fremde Parameter und Anker; Sperrzähler mit Pause
    nach drei Nächten; Meldungen nur mit Zeitpunkt; verbleibende Nächte nur mit angegebener Gesamtzahl."""
    z, s, t = _pfade(tmp_path)
    z.write_text(json.dumps({
        "organizations": "2026-11-15T22:10:05+00:00",
        "papers_fortsetzung": {"naechste": "https://nutzer:geheim@oparl.example.invalid/oparl/bodies/"
                                            "stadtverwaltung_koeln/papers?page=500&limit=100&token=abc#anker",
                               "seiten": 500, "start": "2026-11-14T22:10:20+00:00",
                               "gespeichert": "2026-11-16T00:00:01+00:00"},
        "sperre_verdacht": {"naechte": 3, "zuletzt": "2026-11-13T23:20:00+00:00", "art": "sperre", "code": None,
                            "meldung": "Zeitüberschreitung bei Erfundener Titel Musterstraße 12"},
        "listenfehler": {"naechte": 1, "zuletzt": "2026-11-10T23:00:00+00:00", "art": "filter", "meldung": "x"},
        "letzter_abbruch": {"zuletzt": "2026-11-13T23:20:00+00:00", "art": "sperre", "code": None,
                            "meldung": "Erfundener Titel Musterstraße 12"},
        "nicht_vor": "2026-11-20T00:00:00+00:00",
    }), encoding="utf-8")
    s.write_text(json.dumps({
        "organizations": "2026-11-15T22:10:30+00:00",
        "abruf_hinweis": {"zeit": "2026-11-16T00:00:02+00:00", "meldung": "Erfundener Titel Musterstraße 12"},
        "abruf_warnungen": {"organizations": {"zeit": "2026-11-14T22:10:30+00:00", "meldung": "geheim"}},
        "abruf_uebersprungen": {"zeit": "2026-11-16T08:30:00+00:00",
                                "grund": "außerhalb des Zeitfensters\n23-1 Uhr"},
    }), encoding="utf-8")
    _statistik(t, [
        _zeile("2026-11-14T22:10:01+00:00", "body", "", "", 1, 1, "ok"),
        _zeile("2026-11-14T22:10:05+00:00", "organizations", "voll", 1, 96, 1, "ok", neu=96),
        _zeile("2026-11-14T22:10:20+00:00", "papers", "voll", 250, 25_000, 250,
               "unterbrochen nach 250 Seiten, Fortsetzung im nächsten Lauf: Erfundener Titel Musterstraße 12"),
        _zeile("2026-11-15T22:10:01+00:00", "body", "", "", 1, 1, "ok"),
        _zeile("2026-11-15T22:10:05+00:00", "organizations", "voll", 1, 96, 1, "ok", neu=0, geaendert=2,
               geloescht=0),
        _zeile("2026-11-15T22:10:20+00:00", "papers", "voll, fortgesetzt", 500, 49_900, 251,
               "unterbrochen nach 500 Seiten, Fortsetzung im nächsten Lauf: geheim"),
    ])
    zusammenfassung = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(zusammenfassung))
    out = _aufruf(stand, tmp_path, capsys)
    md = zusammenfassung.read_text(encoding="utf-8")
    for text in (out, md):
        assert not any(g in text for g in GEHEIM), text
        assert f"{BASIS}/papers?page=500&limit=100" in text
    assert "Letzte Nacht mit Anfragen: ab 15.11.2026, 23:10 Uhr; Anfragen insgesamt 253" in out
    assert "Danach übersprungen: 16.11.2026, 09:30 Uhr: außerhalb des Zeitfensters 23-1 Uhr" in out
    # letzter_abbruch liegt vor dieser Nacht: Sie endete mit dem Zeitfenster, nicht mit dem Abbruch vom 14.11.
    assert "Ende der letzten Nacht: Ende des Zeitfensters; Fortsetzung in der nächsten Nacht" in out
    assert "Ende der letzten Nacht: Ende des Zeitfensters; Fortsetzung in der nächsten Nacht." in md
    teile = out.split("Vorlagen (papers): ")[1].split("Sitzungen (meetings): ")
    papers, rest = teile[0], teile[1]
    assert papers.startswith("Vollabruf läuft")
    assert "letzte Nacht: Anfragen 251, Objekte 24.900" in papers
    assert "Seiten bisher: 500; Objekte im laufenden Vollabruf: 49.900" in papers
    assert ("Fortsetzung: Seite 500 (" + f"{BASIS}/papers?page=500&limit=100), gespeichert 16.11.2026, 01:00 Uhr, "
            "Vollabruf begonnen 14.11.2026, 23:10 Uhr") in papers
    assert "gespeicherter Stand: keiner" in papers and "unterbrochen (Modus voll, fortgesetzt)" in papers
    meetings, orgs = rest.split("Organisationen (organizations): ")
    assert meetings.startswith("noch kein vollständiger Abruf") and "letzte Nacht: keine Anfragen" in meetings
    assert orgs.startswith("Vollabruf abgeschlossen")
    assert "letzte Nacht: Anfragen 1, Objekte 96" in orgs and "gespeicherter Stand: 96 Objekte (15.11.2026" in orgs
    assert ("Nächte mit möglicher Sperre: 3 von 3, zuletzt 14.11.2026, 00:20 Uhr, Art sperre; Pause bis "
            "21.11.2026, 00:20 Uhr") in out
    assert "Nächte mit fehlerhafter Liste: 1 von 3, zuletzt 11.11.2026, 00:00 Uhr, Art filter; keine Pause" in out
    assert "Retry-After: kein Abruf vor 20.11.2026, 01:00 Uhr" in out
    assert "Letzter Abbruch: Art sperre, 14.11.2026, 00:20 Uhr" in out
    assert "abruf_ok: nein (noch kein vollständiger Lauf)" in out
    assert ("Meldungen in STAND.json (Text dort): abruf_hinweis (16.11.2026, 01:00 Uhr), "
            "abruf_warnungen.organizations (14.11.2026, 23:10 Uhr)") in out
    assert ("Verbleibende Nächte (Vorlagen): unbekannt: Gesamtzahl der Vorlagen nicht bekannt (die Kölner API nennt in "
            "pagination keine, der Abruf speichert keine); in der letzten Nacht 24.900 Vorlagen gelesen") in out
    assert "| Vorlagen (`papers`) | Vollabruf läuft | 251 | 24.900 | 500 | 49.900 |" in md
    # mit angegebener Gesamtzahl: ⌈(100 000 − 49 900) / 24 900⌉ = 3
    out = _aufruf(stand, tmp_path, capsys, "--vorlagen-gesamt", "100000")
    assert ("Verbleibende Nächte (Vorlagen): etwa 3 bei 100.000 Vorlagen insgesamt (angegeben) und 24.900 je Nacht wie "
            "in der letzten") in out
    out = _aufruf(stand, tmp_path, capsys, "--vorlagen-gesamt", "viele")
    assert "bleibt unberücksichtigt" in out and "Verbleibende Nächte (Vorlagen): unbekannt" in out
    # unbekannte Angabe: Hinweis von argparse, Exit-Code 0
    assert stand.main(["--unbekannt"]) == 0
    assert "Aufruf unlesbar" in capsys.readouterr().out


def test_restnaechte(stand):
    assert stand.restnaechte(100_000, 49_900, 24_900) == 3
    assert stand.restnaechte(100_000, 100_500, 24_900) == 0
    assert stand.restnaechte(None, 1, 1) is None and stand.restnaechte(1, None, 1) is None
    assert stand.restnaechte(1, 0, 0) is None and stand.restnaechte(1, 0, None) is None


def test_adresse_ohne_geheimnisse(stand):
    assert stand.adresse("https://a:b@host.example.invalid:8443/p/papers?token=x&page=7&limit=100&x=page#f") == (
        "https://host.example.invalid:8443/p/papers?page=7&limit=100", 7)
    assert stand.adresse("http://127.0.0.1:5000/papers?page=2&page=x") == ("http://127.0.0.1:5000/papers?page=2", 2)
    for url in (None, 7, "", "ftp://host/papers?page=1", "https://ü.example/papers", "https://[::1/papers",
                "https://host:99999/papers"):
        assert stand.adresse(url) == (None, None), url


def test_mit_dem_abruf_gegen_den_testserver(oparl, monkeypatch, capsys):
    """Dateien, wie der Abruf sie schreibt (lokaler Testserver, erfundene Vorlagen): abgebrochener Vollabruf (HTTP 404
    auf Seite 3 der Vorlagen) mit Fortsetzung ab Seite 2, danach vollständig; keine Titel, Kennungen oder Namen der
    Objekte in der Ausgabe."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    modul = _modul()
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    assert modul.main([]) == 0
    out = capsys.readouterr().out
    inhalte = [p["name"] for p in oparl.papers] + [p["reference"] for p in oparl.papers] + [
        o["name"] for o in oparl.orgs] + [oparl.meetings[0]["name"], "Testkörperschaft", "HTTP 404:"]
    assert not any(x in out for x in inhalte), out
    assert "zustand_abruf.json gelesen; STAND.json gelesen; abrufstatistik.tsv gelesen (3 Zeilen)" in out
    papers = out.split("Vorlagen (papers): ")[1].split("Sitzungen (meetings): ")[0]
    assert papers.startswith("Vollabruf läuft") and "Seiten bisher: 2; Objekte im laufenden Vollabruf: 4" in papers
    assert f"Fortsetzung: Seite 2 ({oparl.b}/papers?page=2)" in papers
    assert "letzte Nacht: Anfragen 3, Objekte 4" in papers   # Seiten 1 bis 3, die dritte mit HTTP 404
    assert "Letzter Abbruch: Art http, HTTP 404" in out and "abruf_ok: nein" in out
    assert "Ende der letzten Nacht: Abbruch (Art http, " in out
    assert "Meldungen in STAND.json (Text dort): abruf_fehler (" in out
    # die Fortsetzung folgt in der nächsten Nacht: Zeilen des ersten Laufs einen Tag zurückdatieren
    with open(config.ABRUFSTATISTIK, encoding="utf-8", newline="") as f:
        zeilen = list(csv.DictReader(f, delimiter="\t"))
    for z in zeilen:
        z["datum"] = (datetime.fromisoformat(z["datum"]) - timedelta(days=1)).isoformat(timespec="seconds")
    _statistik(config.ABRUFSTATISTIK, zeilen)
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    sessionnet.fetch_all()
    assert modul.main([]) == 0
    out = capsys.readouterr().out
    assert not any(x in out for x in inhalte), out
    papers = out.split("Vorlagen (papers): ")[1].split("Sitzungen (meetings): ")[0]
    assert papers.startswith("Vollabruf abgeschlossen") and "Fortsetzung: –" in papers
    assert "letzte Nacht: Anfragen 2, Objekte 1" in papers   # Seite 2 wiederholt, Seite 3 neu (eine Vorlage)
    assert "gespeicherter Stand: 5 Objekte" in papers and "ok (Modus voll, fortgesetzt)" in papers
    # Seiten 1 und 2, dann 2 (Nahtstelle) und 3: vier Abrufe über beide Nächte
    assert "Seitenabrufe im Vollabruf insgesamt: 4" in papers and "Seiten im letzten Lauf" not in papers
    assert "Ende der letzten Nacht: vollständig" in out
    assert "Verbleibende Nächte (Vorlagen): keine (Vollabruf der Vorlagen abgeschlossen)" in out
    assert "abruf_ok: ja, letzter vollständiger Lauf" in out and "Letzter Abbruch: keiner vermerkt" in out
    assert "Meldungen in STAND.json (Text dort): keine" in out


def test_vollabruf_beginnt_und_endet_in_derselben_nacht(stand, tmp_path, capsys):
    """Zwei Läufe einer Nacht (der erste beginnt den Vollabruf, der zweite setzt ihn fort und beendet ihn): Anfragen
    beider Läufe, Objekte ab 0 gezählt."""
    _statistik(_pfade(tmp_path)[2], [
        _zeile("2026-11-15T22:10:20+00:00", "papers", "voll", 2, 4, 3, "unterbrochen nach 2 Seiten"),
        _zeile("2026-11-15T23:10:20+00:00", "papers", "voll, fortgesetzt", 3, 5, 2, "ok", neu=5)])
    out = _aufruf(stand, tmp_path, capsys)
    assert "letzte Nacht: Anfragen 5, Objekte 5" in out
    assert "gespeicherter Stand: 5 Objekte (16.11.2026, 00:10 Uhr)" in out


def test_nacht_umfasst_zwoelf_stunden(stand):
    """Zeilen bis 12 Stunden vor der jüngsten gehören zur letzten Nacht; ältere und Zeilen ohne lesbares Datum nicht."""
    jung = datetime(2026, 11, 16, 0, 30, tzinfo=timezone.utc)
    zeilen = [{"datum": (jung - timedelta(hours=h)).isoformat()} for h in (25, 12, 11.9, 0)] + [{"datum": "x"}]
    assert stand.letzte_nacht(zeilen) == ({2, 3}, jung - timedelta(hours=11.9))
    assert stand.letzte_nacht([{"datum": None}]) == (set(), None)


def test_fortsetzung_nach_einer_nacht_mit_programmfehler(stand, tmp_path, capsys):
    """Liegt zwischen der letzten Zeile „unterbrochen“ und der letzten Nacht eine Nacht mit „programmfehler“ derselben
    Fortsetzung, zählt der Zuwachs gegenüber der Zeile „unterbrochen“ (49 900 − 25 000); eine Zeile, die von vorn
    begann oder mit „ok“ endete, beendet die Suche."""
    t = _pfade(tmp_path)[2]
    unterbrochen = _zeile("2026-11-13T22:10:20+00:00", "papers", "voll", 250, 25_000, 250, "unterbrochen nach 250")
    fehler = _zeile("2026-11-14T22:10:20+00:00", "papers", "voll, fortgesetzt", 250, 0, 1, "programmfehler: X")
    nacht = _zeile("2026-11-15T22:10:20+00:00", "papers", "voll, fortgesetzt", 500, 49_900, 251,
                   "unterbrochen nach 500")
    _statistik(t, [unterbrochen, fehler, nacht])
    assert "letzte Nacht: Anfragen 251, Objekte 24.900" in _aufruf(stand, tmp_path, capsys)
    for trenner in (_zeile("2026-11-14T22:10:20+00:00", "papers", "voll", 1, 0, 1, "abbruch: X"),
                    _zeile("2026-11-14T22:10:20+00:00", "papers", "inkrementell", 1, 9, 1, "ok")):
        _statistik(t, [unterbrochen, trenner, nacht])
        assert "letzte Nacht: Anfragen 251, Objekte unbekannt" in _aufruf(stand, tmp_path, capsys)


@pytest.mark.parametrize("abbruch, ergebnis, erwartet", [
    ({"zuletzt": "2026-11-15T22:11:30+00:00", "art": "sperre", "code": None}, "unterbrochen nach 12 Seiten",
     "Abbruch (Art sperre, 15.11.2026, 23:11 Uhr)"),
    ({"zuletzt": "2026-11-15T23:30:00+00:00", "art": "obergrenze", "code": None}, "unterbrochen nach 300 Seiten",
     "Obergrenze je Nacht erreicht (16.11.2026, 00:30 Uhr); Fortsetzung in der nächsten Nacht"),
    ({"zuletzt": "2026-11-13T22:11:30+00:00", "art": "sperre", "code": None}, "unterbrochen nach 12 Seiten",
     "Ende des Zeitfensters; Fortsetzung in der nächsten Nacht"),
    (None, "ok", "vollständig"),
    (None, "warnung: leer", "vollständig (mit Warnung)"),
    (None, "ausgesetzt: Vorlagen ausgesetzt", "vollständig (Vorlagen ausgesetzt)"),
    (None, "programmfehler: X", "Programmfehler"),
    (None, "abbruch: X", "Abbruch"),
])
def test_ende_der_letzten_nacht(stand, tmp_path, capsys, abbruch, ergebnis, erwartet):
    """Wie die letzte Nacht endete, nur aus Zeitpunkten und Arten: Abbruch nur mit `letzter_abbruch` in dieser Nacht;
    eine ausgesetzte Liste wie eine Warnung (der Lauf ist vollständig), mit ihrem Namen."""
    z, _, t = _pfade(tmp_path)
    z.write_text(json.dumps({"letzter_abbruch": abbruch} if abbruch else {}), encoding="utf-8")
    _statistik(t, [_zeile("2026-11-15T22:10:05+00:00", "organizations", "voll", 1, 96, 1, "ok"),
                   _zeile("2026-11-15T22:10:20+00:00", "papers", "voll", 12, 1200, 13, ergebnis)])
    assert f"Ende der letzten Nacht: {erwartet}\n" in _aufruf(stand, tmp_path, capsys)


def test_ungewoehnliche_werte_wie_der_abruf(stand, tmp_path, capsys):
    """Zähler als Text gilt wie in sessionnet._zaehler_pruefen als Grenze (Pause), `nicht_vor` mehr als 30 Tage voraus
    wird wie im Abruf begrenzt, ein nicht darstellbarer Zeitpunkt erscheint als „unlesbar“ statt die Ausgabe zu
    ersetzen."""
    z = _pfade(tmp_path)[0]
    z.write_text(json.dumps({
        "sperre_verdacht": {"naechte": "2", "zuletzt": "2026-11-15T22:11:30+00:00", "art": "sperre"},
        "listenfehler": {"naechte": 1, "zuletzt": "0001-01-01T00:00:00+14:00", "art": "filter"},
        "letzter_abbruch": {"zuletzt": "0001-01-01T00:00:00+14:00", "art": "sperre"},
        "nicht_vor": "2027-06-01T00:00:00+00:00"}), encoding="utf-8")
    out = _aufruf(stand, tmp_path, capsys)
    assert "Abrufstand nicht ermittelt" not in out
    assert ("Nächte mit möglicher Sperre: unlesbar (gilt als 3), zuletzt 15.11.2026, 23:11 Uhr, Art sperre; Pause bis "
            "22.11.2026, 23:11 Uhr") in out
    assert "Nächte mit fehlerhafter Liste: 1 von 3, zuletzt unlesbar, Art filter; keine Pause" in out
    assert "Letzter Abbruch: Art sperre, unlesbar" in out
    assert "Retry-After: kein Abruf vor 16.12.2026, 10:00 Uhr (gespeichert weiter in der Zukunft, gilt als 30 Tage)" in out


def test_ende_der_nacht_nur_uebersprungen(stand, tmp_path, capsys):
    _statistik(_pfade(tmp_path)[2], [
        _zeile("2026-11-15T22:10:05+00:00", "meetings", "übersprungen", 0, 50, 0, "übersprungen: schon gelesen")])
    assert "Ende der letzten Nacht: übersprungen (in dieser Nacht schon gelesen)\n" in _aufruf(stand, tmp_path, capsys)


def test_dokumente_nur_zahlen_und_zustaende(stand, tmp_path, capsys, monkeypatch):
    """Dokumentschritt (läuft nach dem Fortschritt; gezeigt wird der Stand vor ihm): Nacht und Zahl der angefragten
    Dateien aus dem eigenen Eintrag `dokumente`, Nächte mit möglicher Sperre beim Dokumentabruf mit Pause wie
    dokumente._pause, letzte Zeile `dokumente` der Abrufstatistik nur mit Zahlen und der Art des Ergebnisses; keine
    Meldungstexte, Kennungen oder Adressen. Die Zeile `dokumente` stört die Listen nicht."""
    zusammenfassung = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(zusammenfassung))
    z, s, t = _pfade(tmp_path)
    z.write_text(json.dumps({
        "papers": "2026-11-15T22:30:00+00:00",
        "dokumente": {"nacht": "2026-11-15", "dateien": 120,
                      "verdacht": {"naechte": 1, "zuletzt": "2026-11-14T23:40:00+00:00", "art": "sperre",
                                   "code": 429}},
        "letzter_abbruch": {"zuletzt": "2026-11-14T23:40:00+00:00", "art": "sperre", "code": 429,
                            "meldung": f"Dokumente: {GEHEIM[0]} {BASIS}/files/1/{GEHEIM[1]}.pdf"}}), encoding="utf-8")
    s.write_text(json.dumps({"abruf_ok": "2026-11-15T22:30:00+00:00"}), encoding="utf-8")
    _statistik(t, [
        _zeile("2026-11-15T22:30:00+00:00", "papers", "inkrementell", 1, 64000, 2, "ok", neu=3, geaendert=4,
               geloescht=0),
        _zeile("2026-11-15T23:55:00+00:00", "dokumente", "pdf-koepfe", "", 118, 120,
               f"ok; Auswahl 300 Dateien; {GEHEIM[0]} VI/61 {BASIS}/files/2/{GEHEIM[2]}.pdf")])
    out = _aufruf(stand, tmp_path, capsys)
    teil = out.split("Dokumente (PDF-Köpfe; Stand vor dem Dokumentschritt dieses Laufs):\n", 1)[1]
    assert teil.startswith("  angefragte Dateien: 120 in der Nacht vom 15.11.2026\n"
                           "  letzte Zeile der Abrufstatistik: 16.11.2026, 00:55 Uhr, Anfragen 120, Dateien mit "
                           "Ergebnis 118, Ergebnis ok\n"
                           "  Nächte mit möglicher Sperre beim Dokumentabruf: 1 von 3, zuletzt 15.11.2026, 00:40 Uhr, "
                           "Art sperre, HTTP 429; keine Pause\n"), teil
    assert "Vorlagen (papers): Vollabruf abgeschlossen" in out and "neu 3, geändert 4, gelöscht 0" in out
    md = zusammenfassung.read_text(encoding="utf-8")
    assert ("- Dokumente (PDF-Köpfe; Stand vor dem Dokumentschritt dieses Laufs): angefragte Dateien: 120 in der Nacht "
            "vom 15.11.2026; letzte Zeile der Abrufstatistik:") in md
    for text in (out, md):
        assert not any(g in text for g in GEHEIM) and "VI/61" not in text and "/files/" not in text


@pytest.mark.parametrize("eintrag, erwartet", [
    (None, ["noch kein Lauf mit Freigabe (kein Eintrag im Zustand, keine Zeile in der Abrufstatistik)"]),
    ({"verdacht": {"naechte": 3, "zuletzt": "2026-11-14T23:40:00+00:00", "art": "zeitueberschreitung"}},
     ["angefragte Dateien: keine vermerkt", "letzte Zeile der Abrufstatistik: keine",
      "Nächte mit möglicher Sperre beim Dokumentabruf: 3 von 3, zuletzt 15.11.2026, 00:40 Uhr, Art "
      "zeitueberschreitung; Pause bis 22.11.2026, 00:40 Uhr"]),
    ({"nacht": 5, "dateien": "viele", "verdacht": "x"},
     ["angefragte Dateien: unlesbar (gilt in der Nacht des nächsten Laufs als ausgeschöpft)",
      "Nächte mit möglicher Sperre beim Dokumentabruf: unlesbar; unlesbar (gilt beim nächsten Lauf als Pause)"]),
    ({"nacht": "2026-11-15", "dateien": True}, ["angefragte Dateien: unlesbar (gilt in der Nacht des nächsten "
                                                "Laufs als ausgeschöpft)"]),
    ([1], ["angefragte Dateien: unlesbar", "Nächte mit möglicher Sperre beim Dokumentabruf: unlesbar; unlesbar"]),
])
def test_dokumente_ohne_lauf_und_unlesbar(stand, tmp_path, capsys, eintrag, erwartet):
    """Ohne Eintrag und ohne Zeile (Freigabe nie erteilt): ein Satz; unlesbare Werte wie dokumente._eigener_zustand
    („ausgeschöpft“, Zähler gilt als Grenze); eine Pause nach drei Nächten bis sieben Tage nach der letzten."""
    z = _pfade(tmp_path)[0]
    z.write_text(json.dumps({} if eintrag is None else {"dokumente": eintrag}), encoding="utf-8")
    out = _aufruf(stand, tmp_path, capsys)
    assert "Abrufstand nicht ermittelt" not in out
    teil = out.split("Dokumente (PDF-Köpfe; Stand vor dem Dokumentschritt dieses Laufs):\n", 1)[1]
    for zeile in erwartet:
        assert f"  {zeile}\n" in teil, teil


def test_dokumente_werte_wie_im_schritt(stand):
    """Schlüssel, Grenze und Pause stehen in abrufstand.py ohne Import (das Modul lädt Geokodierung und Titelmaske);
    sie gleichen denen des Dokumentschritts."""
    from pipeline import dokumente
    assert (stand.DOKUMENTE, stand.DOKUMENTE_NAECHTE, stand.DOKUMENTE_PAUSE) == (
        dokumente.SCHLUESSEL, dokumente.VERDACHT_NAECHTE, dokumente.VERDACHT_PAUSE)


# --- Aussetzen einer Liste (sessionnet.AUSSETZEN, Entscheidung 13.11.2026) und Zeilen des Dokumentschritts ----------

def _abschnitt(out, name):
    """Ausgabe einer Liste (von ihrer Kopfzeile bis zur nächsten Liste bzw. den verbleibenden Nächten)."""
    teil = out.split(f"({name}): ", 1)[1]
    for ende in ("Sitzungen (meetings): ", "Organisationen (organizations): ", "Verbleibende Nächte"):
        teil = teil.split(ende, 1)[0]
    return teil


def test_ausgesetzte_liste_mit_dem_abruf(oparl, monkeypatch, capsys, tmp_path):
    """Ablauf wie tests/test_aussetzen.py (lokaler Testserver, feste Uhr je Nacht): 10 Vorlagen vollständig; die Stadt
    liefert nur noch 8, ein Vollabruf (RATSATLAS_VOLLABRUF=papers) endet am Zeitfenster vor Seite 3; in der nächsten
    Nacht endet die Fortsetzung unter 90 % und die Vorlagen setzen aus; danach eine Nacht ohne Anfrage an die Vorlagen,
    dann RATSATLAS_KUERZER_ANNEHMEN=papers. Der Fortschritt zeigt in der Nacht des Aussetzens und der Folgenacht
    „ausgesetzt seit …“ statt „Vollabruf läuft“ (die Fortsetzung bleibt stehen), die Nacht als vollständig mit
    ausgesetzter Liste, in der Folgenacht 0 gelesene Vorlagen, `abruf_ausgesetzt` unter den Meldungen und die feste
    Abhilfe; keine Meldungstexte, Titel oder Kennungen."""
    from test_aussetzen import _Naechte   # noqa: E402  (Nächte mit fester Uhr wie im Test des Aussetzens)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    zusammenfassung = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(zusammenfassung))
    modul = _modul()
    n = _Naechte(oparl, monkeypatch)
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    n.nacht()
    oparl.papers = oparl.papers[:8]
    n.nacht(n.fenster_vor("/papers", 3), RATSATLAS_VOLLABRUF="papers")
    n.nacht()                                                        # Nacht 2 (15.11.2026): Aussetzen
    eintrag = json.loads(config.ZUSTAND.read_text(encoding="utf-8"))["papers_ausgesetzt"]
    assert (eintrag["anlass"], eintrag["seit"]) == (sessionnet.AUSSETZEN_ANLASS["fortgesetzt"],
                                                    "2026-11-15T22:15:00+00:00")
    inhalte = ([p["name"] for p in oparl.papers] + [p["reference"] for p in oparl.papers]
               + [o["name"] for o in oparl.orgs] + [oparl.meetings[0]["name"], "Testkörperschaft"]
               + [eintrag["meldung"][:40], "papers.jsonl", "unvollständige Antwort", "Vorhandener Stand bleibt",
                  "Keine Anfrage an diese Liste", "Abruf ausgesetzt seit"])
    status = "ausgesetzt seit 15.11.2026, 23:15 Uhr (8 statt bisher 10, fortgesetzter Vollabruf)"

    def fortschritt():
        capsys.readouterr()
        zusammenfassung.write_text("", encoding="utf-8")
        assert modul.main([]) == 0
        out, md = capsys.readouterr().out, zusammenfassung.read_text(encoding="utf-8")
        for text in (out, md):
            assert not any(x in text for x in inhalte), text
        assert "Vollabruf läuft" not in _abschnitt(out, "papers") and "Abrufstand nicht ermittelt" not in out
        assert "| Vorlagen (`papers`) | Vollabruf läuft" not in md
        return out, md

    out, md = fortschritt()
    papers = _abschnitt(out, "papers")
    assert papers.startswith(f"{status}\n  Abhilfe: stimmt der kürzere Stand, RATSATLAS_KUERZER_ANNEHMEN=papers")
    assert "letzte Nacht: Anfragen 3, Objekte 4" in papers               # Seite 2 wiederholt, Seiten 3 und 4 neu
    assert "Seitenabrufe im Vollabruf insgesamt: 5" in papers
    assert "Fortsetzung: Seite 2 (" in papers and "(steht, solange die Liste ausgesetzt ist)" in papers
    assert "gespeicherter Stand: 10 Objekte (13.11.2026, 23:15 Uhr)" in papers
    assert "letzte Zeile der Abrufstatistik: ausgesetzt (Modus voll, fortgesetzt)" in papers
    assert "Ende der letzten Nacht: vollständig (Vorlagen ausgesetzt)\n" in out
    assert "Letzte Nacht mit Anfragen: ab 15.11.2026, 23:15 Uhr; Anfragen insgesamt 6" in out
    assert "Verbleibende Nächte (Vorlagen): keine Schätzung: Vorlagen ausgesetzt" in out
    assert "Meldungen in STAND.json (Text dort): abruf_ausgesetzt.papers (15.11.2026, 23:15 Uhr)" in out
    assert "abruf_ok: ja" in out
    assert f"| Vorlagen (`papers`) | {status} | 3 | 4 |" in md
    assert "- Vorlagen (`papers`) ausgesetzt; Abhilfe: stimmt der kürzere Stand" in md

    n.nacht()                                                        # Nacht 3: keine Anfrage an die Vorlagen
    out, md = fortschritt()
    papers = _abschnitt(out, "papers")
    assert papers.startswith(f"{status}\n  Abhilfe: ")
    assert "letzte Nacht: Anfragen 0, Objekte 0" in papers and "Seiten im letzten Lauf: 0" in papers
    assert "letzte Zeile der Abrufstatistik: ausgesetzt (Modus ausgesetzt)" in papers
    assert "Fortsetzung: Seite 2 (" in papers and "gespeicherter Stand: 10 Objekte (13.11.2026" in papers
    assert "Ende der letzten Nacht: vollständig (Vorlagen ausgesetzt)\n" in out
    assert "Anfragen insgesamt 3" in out and "Vorlagen gelesen" not in out
    assert "abruf_ausgesetzt.papers (15.11.2026, 23:15 Uhr)" in out
    assert f"| Vorlagen (`papers`) | {status} | 0 | 0 |" in md

    n.nacht(RATSATLAS_KUERZER_ANNEHMEN="papers")                     # Nacht 4: Fortsetzung, kürzerer Stand angenommen
    inhalte.remove("Abruf ausgesetzt seit")                          # steht im Ergebnis „ok; … Aussetzen seit …“ nicht
    capsys.readouterr()
    assert modul.main([]) == 0
    out = capsys.readouterr().out
    assert not any(x in out for x in inhalte), out
    papers = _abschnitt(out, "papers")
    assert papers.startswith("Vollabruf abgeschlossen") and "Abhilfe" not in papers and "Fortsetzung: –" in papers
    assert "letzte Nacht: Anfragen 3, Objekte 4" in papers               # Zuwachs gegenüber der Zeile „unterbrochen“
    assert "gespeicherter Stand: 8 Objekte (17.11.2026, 23:15 Uhr)" in papers
    assert "Ende der letzten Nacht: vollständig\n" in out and "abruf_ausgesetzt" not in out
    assert "Verbleibende Nächte (Vorlagen): keine (Vollabruf der Vorlagen abgeschlossen)" in out


def test_ausgesetzt_unlesbar_und_nur_feste_anlaesse(stand, tmp_path, capsys):
    """Eintrag `<liste>_ausgesetzt` mit unlesbaren Werten: Stand nur aus Zahlen, Zeit und festen Anlässen, nie aus
    `meldung` oder einem fremden Anlass; ein Wert, der kein Objekt ist, gilt wie im Abruf als ausgesetzt; Listen außerhalb
    von sessionnet.AUSSETZEN setzen nie aus. `abruf_ausgesetzt` in STAND.json nur mit Zeitpunkt oder „unlesbar“."""
    z, s, _ = _pfade(tmp_path)
    z.write_text(json.dumps({
        "papers_ausgesetzt": {"seit": "gestern", "objekte": True, "bisher": "10", "anlass": GEHEIM[0],
                              "meldung": GEHEIM[0]},
        "papers_fortsetzung": {"naechste": f"{BASIS}/papers?page=3", "seiten": 3},
        "meetings_ausgesetzt": "x", "organizations_ausgesetzt": {"seit": "2026-11-15T22:15:00+00:00"},
        "organizations": "2026-11-15T22:15:00+00:00"}), encoding="utf-8")
    s.write_text(json.dumps({"abruf_ausgesetzt": {"papers": {"seit": "2026-11-15T22:15:00+00:00",
                                                             "meldung": GEHEIM[0]}, "meetings": [GEHEIM[1]]}}),
                 encoding="utf-8")
    out = _aufruf(stand, tmp_path, capsys)
    assert not any(g in out for g in GEHEIM), out
    assert "Vorlagen (papers): ausgesetzt seit unbekannt (unbekannt statt bisher 10, Anlass unbekannt)\n" in out
    assert "Sitzungen (meetings): ausgesetzt (Eintrag unlesbar; gilt im Abruf als ausgesetzt)\n" in out
    assert "Organisationen (organizations): Vollabruf abgeschlossen\n" in out
    assert "Vollabruf läuft" not in out and "Fortsetzung: Seite 3 (" in out
    assert ("Meldungen in STAND.json (Text dort): abruf_ausgesetzt.papers (15.11.2026, 23:15 Uhr), "
            "abruf_ausgesetzt.meetings (unlesbar)") in out
    s.write_text(json.dumps({"abruf_ausgesetzt": [GEHEIM[1]]}), encoding="utf-8")
    assert "Meldungen in STAND.json (Text dort): abruf_ausgesetzt (unlesbar)" in _aufruf(stand, tmp_path, capsys)


@pytest.mark.parametrize("dokumente, abbruch, erwartet", [
    ("unterbrochen: Zeitfenster endete (geheim)", None, "Abruf: vollständig; Dokumente: Ende des Zeitfensters"),
    ("ok; Auswahl 300 Dateien", None, "Abruf: vollständig; Dokumente: ohne Abbruch"),
    ("abbruch: geheim", "2026-11-15T23:41:00+00:00",
     "Abruf: vollständig; Dokumente: Abbruch (Art sperre, 16.11.2026, 00:41 Uhr)"),
    ("übersprungen: 12-Stunden-Regel", "2026-11-15T22:11:00+00:00",
     "Abruf: Abbruch (Art sperre, 15.11.2026, 23:11 Uhr); Dokumente: übersprungen"),
    ("anders", None, "Abruf: vollständig; Dokumente: Ergebnis unbekannt"),
])
def test_ende_der_nacht_mit_dokumentschritt(stand, tmp_path, capsys, dokumente, abbruch, erwartet):
    """Die Zeile `dokumente` bestimmt die Nacht nicht und zählt nicht zu ihren Anfragen; ihr Ende steht getrennt hinter
    dem des Abrufs, auch in einem späteren Lauf ohne neue Zeilen des Abrufs (Push, Knopfdruck, Pause). Ein Abbruch ab
    ihrem Beginn gilt als Abbruch des Dokumentschritts, einer davor als Abbruch des Abrufs."""
    z, _, t = _pfade(tmp_path)
    z.write_text(json.dumps({"letzter_abbruch": {"zuletzt": abbruch, "art": "sperre"}} if abbruch else {}),
                 encoding="utf-8")
    _statistik(t, [_zeile("2026-11-15T22:10:01+00:00", "body", "", "", 1, 1, "ok"),
                   _zeile("2026-11-15T22:10:05+00:00", "papers", "inkrementell", 1, 64000, 2, "ok", neu=1,
                          geaendert=0, geloescht=0),
                   _zeile("2026-11-15T22:40:00+00:00", "dokumente", "pdf-koepfe", "", 118, 280, dokumente)])
    out = _aufruf(stand, tmp_path, capsys)
    assert f"Ende der letzten Nacht: {erwartet}\n" in out
    assert "Letzte Nacht mit Anfragen: ab 15.11.2026, 23:10 Uhr; Anfragen insgesamt 3\n" in out
    assert "geheim" not in out


def test_dokumentzeile_spaeter_als_ein_uebersprungener_lauf(stand, tmp_path, capsys):
    """Ein übersprungener Abruf (etwa Pause) nach der letzten Nacht mit Anfragen erscheint auch, wenn danach noch der
    Dokumentschritt eine Zeile schrieb; die Zeile einer späteren Nacht gehört nicht zur letzten Nacht des Abrufs."""
    z, s, t = _pfade(tmp_path)
    s.write_text(json.dumps({"abruf_uebersprungen": {"zeit": "2026-11-16T22:10:00+00:00", "grund": "Pause"}}),
                 encoding="utf-8")
    _statistik(t, [_zeile("2026-11-15T22:10:05+00:00", "papers", "inkrementell", 1, 64000, 2, "ok"),
                   _zeile("2026-11-16T22:12:00+00:00", "dokumente", "pdf-koepfe", "", 0, 0, "übersprungen: Pause")])
    out = _aufruf(stand, tmp_path, capsys)
    assert "Letzte Nacht mit Anfragen: ab 15.11.2026, 23:10 Uhr; Anfragen insgesamt 2\n" in out
    assert "Ende der letzten Nacht: vollständig\n" in out
    assert "Danach übersprungen: 16.11.2026, 23:10 Uhr: Pause\n" in out
