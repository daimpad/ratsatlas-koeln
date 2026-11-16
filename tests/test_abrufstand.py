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
