"""Messstufen der Kölner OParl-API (explore/STUFEN.md) gegen den lokalen Testserver explore/testserver.py:
Anzahl der Anfragen je Kommando, Obergrenze RATSATLAS_MAX_ANFRAGEN (Abbruch statt Überschreitung), Cache-Treffer
zählen nicht, Folgeseiten ohne URL-Kodierung, Seitengrenzen, Abbruchkriterien (auch Mindestabstand innerhalb eines
Prozesses und zwischen zwei Prozessen, Antworten eines lokalen Schein-Proxys auf CONNECT, abgeschnittene oder
unlesbare Antworten, Sperre gegen gleichzeitige Prozesse, keine Anfrage nach einem Abbruch), Probelauf und Auswertung;
explore/geodaten.py ohne Netz (Mindestwerte, Obergrenze, Ende nach möglicher Sperre).
Läuft offline: Anfragen gehen nur an 127.0.0.1 und 127.0.0.2 (gilt nicht als lokal und steht in Tests für die Stadt);
Adressen der Stadt werden nie aufgerufen (fremde Adressen nur unter example.invalid, über einen lokalen Schein-Proxy)."""
import contextlib
import csv
import datetime as dt
import importlib
import json
import os
import re
import shutil
import signal
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

EXPLORE = Path(__file__).resolve().parents[1] / "explore"
sys.path.insert(0, str(EXPLORE))
probelauf = importlib.import_module("probelauf")
testserver = importlib.import_module("testserver")


@pytest.fixture
def server():
    with testserver.Testserver() as s:
        yield s


def lauf(server, tmp_path, kommando, *parameter, obergrenze=0, cache="cache", **zusatz):
    return probelauf.messung(server, tmp_path / cache, tmp_path / "ergebnisse", kommando, parameter, obergrenze,
                             **zusatz)


def tsv(datei):
    with open(datei, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def protokoll(tmp_path, cache="cache"):
    return tsv(tmp_path / cache / "abrufe.tsv")


def test_test_stellt_genau_drei_anfragen(server, tmp_path):
    m = lauf(server, tmp_path, "test", obergrenze=3)
    assert m["rc"] == 0, m["stderr"]
    assert m["server"] == 3 and [p for p, *_ in server.anfragen] == [
        "/oparl/system", "/oparl/bodies/testkoerperschaft", "/oparl/bodies/testkoerperschaft/papers"]
    assert all(ua.startswith("ratsatlas-koeln-explore/") for _, _, ua, _ in server.anfragen)
    assert [z["quelle"] for z in protokoll(tmp_path)] == ["netz"] * 3
    assert (m["lauf"]["netz"], m["lauf"]["cache"], m["lauf"]["ergebnis"]) == ("3", "0", "ok")
    werte = {(z["objekt"], z["feld"]): z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_test.tsv")}
    assert werte[("paper", "pagination.elementsPerPage")] == "25" and werte[("paper", "objekte_erste_seite")] == "25"
    assert werte[("paper", "links.next")].endswith("/papers?page=2")


def test_cache_treffer_zaehlen_nicht(server, tmp_path):
    assert lauf(server, tmp_path, "test", obergrenze=3)["rc"] == 0
    zweiter = lauf(server, tmp_path, "test", obergrenze=1)        # alles aus dem Cache
    assert zweiter["rc"] == 0 and zweiter["server"] == 0
    assert (zweiter["lauf"]["netz"], zweiter["lauf"]["cache"]) == ("0", "3")
    # kennzahlen braucht 10 Anfragen, davon 3 aus dem Cache von test: Obergrenze 7 reicht
    k = lauf(server, tmp_path, "kennzahlen", obergrenze=7)
    assert k["rc"] == 0, k["stderr"]
    assert k["server"] == 7 and (k["lauf"]["netz"], k["lauf"]["cache"]) == ("7", "3")


def test_kennzahlen_stellt_zehn_anfragen(server, tmp_path):
    m = lauf(server, tmp_path, "kennzahlen", obergrenze=10)
    assert m["rc"] == 0, m["stderr"]
    assert m["server"] == 10
    status = [s for *_, s in server.anfragen]
    assert status.count(404) == 1 and status.count(200) == 9          # nur der URL-kodierte Vergleich
    werte = {z["feld"]: z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv")
             if z["objekt"] == "paper"}
    assert werte["test modified_since URL-kodiert"] == "Parameter abgelehnt (HTTP 404)"
    seit = next(f for f in werte if f.startswith("test modified_since=") and "+00:00" in f)
    assert "filter_wirksam=ja" in werte[seit]
    # älteste zuerst (Form „bisher“): created_since unterscheidbar, created_until nicht
    created = next(w for f, w in werte.items() if f.startswith("test created_since="))
    assert "created_since wirkt: ja" in created and "created_until wirkt: nicht unterscheidbar" in created
    assert werte["pagination.totalElements"] == str(len(server.daten.vorlagen))


@pytest.mark.parametrize("kommando, obergrenze", [("kennzahlen", 5), ("test", 2)])
def test_obergrenze_bricht_ab_statt_zu_ueberschreiten(server, tmp_path, kommando, obergrenze):
    m = lauf(server, tmp_path, kommando, obergrenze=obergrenze)
    assert m["rc"] == 2 and "RATSATLAS_MAX_ANFRAGEN" in m["stderr"]
    assert m["server"] == obergrenze and m["lauf"]["netz"] == str(obergrenze)
    assert m["lauf"]["ergebnis"] == "abbruch (obergrenze)"
    datei = "oparl_kennzahlen.tsv" if kommando == "kennzahlen" else "oparl_test.tsv"
    teil = tsv(tmp_path / "ergebnisse" / datei)                       # Teilergebnis mit Abbruchvermerk
    assert teil[-1]["feld"] == "abbruch" and "Obergrenze" in teil[-1]["wert"]


def test_folgeseiten_ueber_links_next_ohne_url_kodierung(server, tmp_path):
    m = lauf(server, tmp_path, "stichprobe", "--seiten", "2", "--von", "2025", "--bis", "2026", obergrenze=5)
    assert m["rc"] == 0, m["stderr"]
    assert m["server"] == 5                                            # Body + 2 Jahre × 2 Seiten
    seiten = [q for p, q, _, s in server.anfragen if p.endswith("/papers")]
    assert len(seiten) == 4 and all("%" not in q for q in seiten)
    folgeseiten = [q for q in seiten if "page=2" in q]
    assert len(folgeseiten) == 2 and all("created_since=" in q and "+01:00" in q for q in folgeseiten)
    jahre = tsv(tmp_path / "ergebnisse" / "oparl_stichprobe_jahre.tsv")
    assert [(z["jahr"], z["objekte"], z["seiten"]) for z in jahre] == [("2025", "50", "2"), ("2026", "50", "2")]
    bedeckung = {z["feld"]: z for z in tsv(tmp_path / "ergebnisse" / "oparl_stichprobe_bedeckung.tsv")}
    assert bedeckung["created außerhalb des Filterjahres"]["vorhanden"] == "0"
    assert bedeckung["consultation"]["von"] == "100"


def test_organisationen_haben_eine_seitengrenze(server, tmp_path):
    m = lauf(server, tmp_path, "organisationen", obergrenze=10)
    assert m["rc"] == 0 and m["server"] == 5                           # Body + Vorgabe 4 Seiten
    liste = tsv(tmp_path / "ergebnisse" / "oparl_listen.tsv")[-1]
    assert (liste["seiten"], liste["objekte"], liste["ende"]) == ("4", "100", "Seitengrenze 4")
    # ausdrücklich ohne Grenze: bis zum Ende von links.next; die ersten Seiten kommen aus dem Cache
    m = lauf(server, tmp_path, "organisationen", "--seiten", "0", obergrenze=10)
    assert m["rc"] == 0 and m["server"] == 2 and m["lauf"]["cache"] == "5"
    liste = tsv(tmp_path / "ergebnisse" / "oparl_listen.tsv")[-1]
    assert (liste["seiten"], liste["objekte"], liste["ende"]) == ("6", "140", "Ende der Liste (kein links.next)")


def test_429_stoppt_ohne_wiederholung(server, tmp_path):
    server.stoerung = lambda pfad, abfrage: 429 if pfad.endswith("/meetings") else None
    m = lauf(server, tmp_path, "sitzungen", obergrenze=3)
    assert m["rc"] == 2 and m["server"] == 2 and m["lauf"]["ergebnis"] == "abbruch (server)"
    assert [z["status"] for z in protokoll(tmp_path)] == ["200", "429"]


def test_langsame_antwort_stoppt(server, tmp_path):
    server.verzoegerung = 0.3
    m = lauf(server, tmp_path, "test", obergrenze=3, RATSATLAS_MAX_DAUER="0.1")
    assert m["rc"] == 2 and m["server"] == 1 and m["lauf"]["ergebnis"] == "abbruch (langsam)"


def test_html_statt_json_stoppt(server, tmp_path):
    server.stoerung = lambda pfad, abfrage: 200 if pfad.endswith("/bodies/testkoerperschaft") else None
    m = lauf(server, tmp_path, "test", obergrenze=3)
    assert m["rc"] == 1 and m["server"] == 2 and m["lauf"]["ergebnis"].startswith("fehler (JSONDecodeError")


def test_ohne_information_der_stadt_keine_anfrage(server, tmp_path):
    fremd = {"RATSATLAS_OPARL_SYSTEM": "http://example.invalid/oparl/system",
             "RATSATLAS_OPARL_BODY": "http://example.invalid/oparl/bodies/x"}
    m = lauf(server, tmp_path, "test", obergrenze=3, **fremd)
    assert m["rc"] == 1 and "nicht informiert" in m["stderr"]
    # informiert, aber außerhalb des Zeitfensters
    h = dt.datetime.now(ZoneInfo("Europe/Berlin")).hour
    m = lauf(server, tmp_path, "test", obergrenze=3, RATSATLAS_STADT_INFORMIERT="ja",
             RATSATLAS_ZEITFENSTER=f"{(h + 2) % 24}-{(h + 3) % 24}", **fremd)
    assert m["rc"] == 1 and "Zeitfenster" in m["stderr"]
    assert server.anfragen == [] and not (tmp_path / "cache" / "abrufe.tsv").exists()


def test_schleifenschutz_in_links_next(monkeypatch):
    om = importlib.import_module("oparl_messung")
    monkeypatch.setattr(om, "_LISTEN", [])
    seiten = {"http://127.0.0.1/l": {"data": [{"id": "a"}], "links": {"next": "http://127.0.0.1/l?page=2"}},
              "http://127.0.0.1/l?page=2": {"data": [{"id": "a"}], "links": {"next": "http://127.0.0.1/l?page=3"}}}
    monkeypatch.setattr(om, "_hole", lambda url, endung=".json": json.dumps(seiten[url]).encode())
    assert [nr for nr, _ in om._seiten("http://127.0.0.1/l", name="x")] == [1]
    assert om._LISTEN[-1]["ende"] == "Seite ohne neue Kennungen"
    seiten["http://127.0.0.1/l"]["links"]["next"] = "http://127.0.0.1/l"
    assert [nr for nr, _ in om._seiten("http://127.0.0.1/l", name="y")] == [1]
    assert om._LISTEN[-1]["ende"] == "links.next wiederholt"


def test_weiterleitung_wird_nicht_verfolgt(server, tmp_path):
    fremd = "http://example.invalid/oparl/bodies/x"
    server.weiterleitungen["/oparl/bodies/testkoerperschaft"] = (301, fremd)
    m = lauf(server, tmp_path, "test", obergrenze=3)
    assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (weiterleitung)" and fremd in m["lauf"]["meldung"]
    assert m["server"] == 2 and m["lauf"]["netz"] == "2"               # die Weiterleitung zählt als eine Anfrage
    z = protokoll(tmp_path)[-1]
    assert (z["status"], z["ziel"], z["quelle"]) == ("301", fremd, "netz")
    # auch ein Ziel auf demselben Server wird nicht abgerufen
    server.weiterleitungen = {"/oparl/system": (302, "/oparl/bodies/testkoerperschaft")}
    m = lauf(server, tmp_path, "test", obergrenze=3, cache="cache2")
    assert m["rc"] == 2 and m["server"] == 1
    assert [p for p, *_ in server.anfragen][-1] == "/oparl/system"
    assert protokoll(tmp_path, "cache2")[-1]["ziel"].endswith("/oparl/bodies/testkoerperschaft")
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache2", tmp_path / "ergebnisse")
    assert "Status 302 × 1 (Weiterleitung nach http://127.0.0.1:" in aus


def test_abstand_nach_ende_der_antwort_und_zeit_mit_zone(server, tmp_path):
    server.verzoegerung = 0.25
    m = lauf(server, tmp_path, "test", obergrenze=3, RATSATLAS_ABSTAND="0.3")
    assert m["rc"] == 0, m["stderr"]
    abstaende = [b - a for a, b in zip(server.eingang, server.eingang[1:])]
    assert len(abstaende) == 2 and min(abstaende) >= 0.5               # Antwortzeit 0,25 s + Abstand 0,3 s
    assert all(re.search(r"T\d\d:\d\d:\d\d[+-]\d\d:\d\d$", z["zeit"]) for z in protokoll(tmp_path))


def test_altes_protokoll_bekommt_neuen_kopf(server, tmp_path):
    (tmp_path / "cache").mkdir()
    alt = "zeit\turl\tstatus\tbytes\tdauer_s\tquelle\n2026-11-04T10:46:34\thttps://example.invalid/a\t200\t1\t0.10\tnetz\n"
    (tmp_path / "cache" / "abrufe.tsv").write_text(alt, encoding="utf-8")
    assert lauf(server, tmp_path, "test", obergrenze=3)["rc"] == 0
    zeilen = protokoll(tmp_path)
    assert list(zeilen[0]) == ["zeit", "url", "status", "bytes", "dauer_s", "quelle", "ziel"]
    assert zeilen[0]["url"] == "https://example.invalid/a" and len(zeilen) == 4


def test_strenge_vorgaben_fuer_anfragen_an_die_stadt(server, tmp_path, monkeypatch):
    om = importlib.import_module("oparl_messung")
    werte, fehler = om.sichere_vorgaben({"RATSATLAS_MAX_ANFRAGEN": "3", "RATSATLAS_KONTAKT": "kontakt@example.invalid"})
    assert fehler == [] and werte == {"wiederholungen": 0, "max_dauer": 5.0, "max_anfragen": 3, "abstand": 2.0}
    _, fehler = om.sichere_vorgaben({})
    assert any("RATSATLAS_MAX_ANFRAGEN" in f for f in fehler) and any("RATSATLAS_KONTAKT" in f for f in fehler)
    for zusatz, name in (({"RATSATLAS_WIEDERHOLUNGEN": "4"}, "WIEDERHOLUNGEN"), ({"RATSATLAS_MAX_DAUER": "0"}, "MAX_DAUER"),
                         ({"RATSATLAS_MAX_DAUER": "30"}, "MAX_DAUER"),
                         ({"RATSATLAS_KONTAKT": "<Kontaktadresse des Auftraggebers>"}, "KONTAKT")):
        env = {"RATSATLAS_MAX_ANFRAGEN": "3", "RATSATLAS_KONTAKT": "kontakt@example.invalid", **zusatz}
        assert any(name in f for f in om.sichere_vorgaben(env)[1]), zusatz
    # als Prozess: informiert und im Zeitfenster, aber Platzhalter im Kontakt und Wiederholungen → keine Anfrage
    fremd = {"RATSATLAS_OPARL_SYSTEM": "http://example.invalid/oparl/system",
             "RATSATLAS_OPARL_BODY": "http://example.invalid/oparl/bodies/x", "RATSATLAS_STADT_INFORMIERT": "ja",
             "RATSATLAS_KONTAKT": "<Kontaktadresse des Auftraggebers>", "RATSATLAS_WIEDERHOLUNGEN": "4"}
    m = lauf(server, tmp_path, "test", obergrenze=3, **fremd)
    assert m["rc"] == 1 and "RATSATLAS_KONTAKT" in m["stderr"] and "RATSATLAS_WIEDERHOLUNGEN" in m["stderr"]
    assert server.anfragen == [] and not (tmp_path / "cache" / "abrufe.tsv").exists()
    # vor jeder Anfrage an die Stadt: ohne strenge Werte kein Abruf
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setenv("RATSATLAS_ZEITFENSTER", "")
    monkeypatch.setattr(om.abruf, "WIEDERHOLUNGEN", 4)
    monkeypatch.setattr(om, "hole", lambda *a, **k: pytest.fail("darf nicht abrufen"))
    with pytest.raises(om.Abbruch, match="strenge Vorgaben"):
        om._hole("https://buergerinfo.stadt-koeln.de/oparl/system")


def test_jahresfilter_wirkt_nicht_bricht_ab(server, tmp_path):
    server.ohne_created_filter = True
    m = lauf(server, tmp_path, "stichprobe", "--seiten", "1", "--von", "2025", "--bis", "2026", obergrenze=3)
    assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (filter)" and m["server"] == 2
    jahre = tsv(tmp_path / "ergebnisse" / "oparl_stichprobe_jahre.tsv")
    assert [z["jahr"] for z in jahre] == ["2025"]
    bedeckung = {z["feld"]: z for z in tsv(tmp_path / "ergebnisse" / "oparl_stichprobe_bedeckung.tsv")}
    assert bedeckung["created außerhalb des Filterjahres"]["vorhanden"] == "25"
    assert not (tmp_path / "cache" / "stichprobe_vorlagen.jsonl").exists()   # unvollständig: keine Grundlage für PDFs
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert "Regel Stufe 3/5 (Jahresfilter wirkt, keine Doppelungen): nicht erfüllt" in aus


def _seitenfolge(monkeypatch, tmp_path, jahre_seiten):
    """oparl_messung im Prozess mit erfundenen Seiten je Jahr (ohne Netz); liefert das Modul."""
    om = importlib.import_module("oparl_messung")
    monkeypatch.setattr(om, "_LISTEN", [])
    monkeypatch.setattr(om, "ERG", tmp_path / "erg")
    monkeypatch.setattr(om, "STICHPROBE", tmp_path / "cache" / "stichprobe_vorlagen.jsonl")
    monkeypatch.setattr(om, "BODY", "http://127.0.0.1/body")
    liste, seiten = "http://127.0.0.1/papers", {}
    for jahr, folge in jahre_seiten.items():
        start = om._mit_parametern(liste, created_since=f"{jahr}-01-01T00:00:00+01:00",
                                   created_until=f"{jahr}-12-31T23:59:59+01:00")
        for i, daten in enumerate(folge):
            url = start if i == 0 else f"{start}&page={i + 1}"
            seiten[url] = {"data": daten, "links": {"next": f"{start}&page={i + 2}"} if i + 1 < len(folge) else {}}
    seiten[om.BODY] = {"paper": liste}
    monkeypatch.setattr(om, "_hole", lambda url, endung=".json": json.dumps(seiten[url]).encode())
    return om


def _vorlage(nr, jahr):
    return {"id": f"p{nr}", "reference": f"{nr:04d}/{jahr}", "paperType": "Beschlussvorlage", "date": f"{jahr}-03-01",
            "created": f"{jahr}-03-01T10:00:00+01:00",
            "mainFile": {"downloadUrl": f"http://127.0.0.1/f/{nr}.pdf", "name": "[Testdaten] Name", "text": "Volltext"},
            "auxiliaryFile": [{"downloadUrl": f"http://127.0.0.1/f/a{nr}.pdf", "fileName": "[Testdaten] Datei"}]}


def test_doppelungen_getrennt_und_stichprobe_ohne_dateiobjekte(monkeypatch, tmp_path):
    import argparse
    a = argparse.Namespace(seiten=3, von=2025, bis=2026)
    # Seite 2 von 2025 wiederholt p2 (Seiten verschoben), 2026 ist sauber
    om = _seitenfolge(monkeypatch, tmp_path, {2025: [[_vorlage(1, 2025), _vorlage(2, 2025)],
                                                     [_vorlage(2, 2025), _vorlage(3, 2025)]],
                                              2026: [[_vorlage(4, 2026)]]})
    om.stichprobe(a)
    bedeckung = {z["feld"]: z["vorhanden"] for z in tsv(tmp_path / "erg" / "oparl_stichprobe_bedeckung.tsv")}
    assert bedeckung["doppelte Kennungen im selben Jahr (Seiten verschoben)"] == "1"
    assert bedeckung["doppelte Kennungen aus anderen Jahren (Jahresfilter wirkt nicht)"] == "0"
    zeilen = [json.loads(z) for z in (tmp_path / "cache" / "stichprobe_vorlagen.jsonl").open(encoding="utf-8")]
    assert len(zeilen) == 4 and all(set(z) == {"id", "reference", "paperType", "date", "datei"} for z in zeilen)
    assert zeilen[0]["datei"] == "http://127.0.0.1/f/1.pdf" and "Volltext" not in json.dumps(zeilen)
    assert not list((tmp_path / "erg").glob("*.jsonl"))
    # dieselbe Vorlage in einem anderen Jahr: Jahresfilter wirkt nicht → Abbruch nach diesem Jahr
    om = _seitenfolge(monkeypatch, tmp_path / "b", {2025: [[_vorlage(1, 2025)]], 2026: [[_vorlage(1, 2025)]]})
    with pytest.raises(om.Abbruch) as e:
        om.stichprobe(a)
    assert e.value.art == "filter"
    bedeckung = {z["feld"]: z["vorhanden"] for z in tsv(tmp_path / "b" / "erg" / "oparl_stichprobe_bedeckung.tsv")}
    assert bedeckung["doppelte Kennungen aus anderen Jahren (Jahresfilter wirkt nicht)"] == "1"


def test_pdf_auswahl_gleichmaessig_ueber_die_jahre():
    om = importlib.import_module("oparl_messung")
    vorlagen = ([{"reference": f"{i:04d}/2024"} for i in range(10)] + [{"reference": f"{i:04d}/2025"} for i in range(2)]
                + [{"reference": f"{i:04d}/2026"} for i in range(10)])
    auswahl = om.auswahl_je_jahr(vorlagen, 9)
    zaehl = {j: sum(1 for p in auswahl if p["reference"].endswith(j)) for j in ("2024", "2025", "2026")}
    assert zaehl == {"2024": 3, "2025": 2, "2026": 4}


def test_auswertung_ohne_protokoll_und_404_hinweis(tmp_path):
    auswertung = importlib.import_module("auswertung")
    zeilen = [{"quelle": "netz", "status": "404", "url": "http://x/papers?limit=100"},
              {"quelle": "netz", "status": "404", "url": "http://x/papers?modified_since=2026-11-01T00%3A00%3A00"},
              {"quelle": "netz", "status": "200", "url": "http://x/papers"}]
    assert auswertung.status_hinweise(zeilen, "kennzahlen") == {
        ("404", ""): 1, ("404", " (erwartet: Test mit URL-kodiertem Parameter)"): 1}
    erg = tmp_path / "ergebnisse"
    erg.mkdir()
    (erg / "oparl_laeufe.tsv").write_text(
        "lauf\tstufe\tkommando\tparameter\tstart\tende\tdauer_s\tnetz\tcache\tobergrenze\tprotokoll_von\t"
        "protokoll_bis\tergebnis\tmeldung\n1\t1\ttest\t\t2026-11-07T23:05:00+01:00\t2026-11-07T23:05:09+01:00\t9\t3\t0"
        "\t3\t0\t3\tok\t\n", encoding="utf-8")
    aus = auswertung.auswertung(tmp_path / "leer", erg)
    assert "Statuscodes und Antwortzeiten nicht prüfbar (Protokoll fehlt)" in aus and "- keine (" not in aus


def test_stufenplan_befehle_sind_vollstaendig():
    text = (EXPLORE / "STUFEN.md").read_text(encoding="utf-8")
    befehle = [z for z in text.splitlines() if "oparl_messung.py" in z and z.startswith("RATSATLAS_")]
    assert len(befehle) == 8
    for b in befehle:
        for teil in ("RATSATLAS_STADT_INFORMIERT=ja ", "RATSATLAS_KONTAKT=", "RATSATLAS_WIEDERHOLUNGEN=0 ",
                     "RATSATLAS_MAX_DAUER=5 ", "RATSATLAS_STUFE=", "RATSATLAS_MAX_ANFRAGEN="):
            assert teil in b, (teil, b)
    assert "export " not in text


def test_mehrere_befehle_einer_stufe_nur_nach_rueckgabewert_0():
    """Ein bash-Block mit mehreren Befehlen (Stufe 3) wird als Ganzes übernommen: Jeder Befehl außer dem letzten endet
    mit `&& \\`, damit nach einem Abbruch (Rückgabewert 2) keiner mehr läuft."""
    text = (EXPLORE / "STUFEN.md").read_text(encoding="utf-8")
    bloecke = re.findall(r"```bash\n(.*?)```", text, re.S)
    mehrere = [b for b in bloecke if b.count("oparl_messung.py") > 1]
    assert mehrere, "Stufe 3 hat zwei Befehle"
    for block in mehrere:
        zeilen = [z for z in block.splitlines() if z.strip()]
        assert all(z.endswith(" && \\") for z in zeilen[:-1]) and not zeilen[-1].endswith("\\"), block
    # die Befehle bleiben einzeln vollständig (je Zeile alle Variablen, siehe oben)
    assert all(b.count("oparl_messung.py") == len([z for z in b.splitlines() if z.strip()]) for b in bloecke)


def test_probelauf_entspricht_stufenplan_und_auswertung(tmp_path):
    zeilen = probelauf.probelauf(tmp_path)
    assert all(z["ergebnis"] in ("ok", "übersprungen (pypdf fehlt)") for z in zeilen), zeilen
    gemessen = {(z["stufe"], z["kommando"]): (z.get("netz_folge"), z.get("netz_leer")) for z in zeilen
                if z["ergebnis"] == "ok"}
    erwartet = {("1", "test"): (3, 3), ("2", "kennzahlen"): (7, 10), ("3", "organisationen"): (3, 5),
                ("3", "stichprobe"): (7, 9), ("4", "sitzungen"): (1, 3), ("5", "stichprobe"): (16, 25)}
    if ("6", "pdf-koepfe") in gemessen:
        erwartet[("6", "pdf-koepfe")] = (100, 100)
    assert {k: v for k, v in gemessen.items() if k in erwartet} == erwartet
    # STUFEN.md nennt dieselben Befehle und Obergrenzen wie probelauf.STUFEN
    text = (EXPLORE / "STUFEN.md").read_text(encoding="utf-8")
    befehle = re.findall(r"RATSATLAS_MAX_ANFRAGEN=(\d+)[^\n`]*?oparl_messung\.py ([a-z-]+)([^\n`&\\]*)", text)
    im_plan = {(k, " ".join(p.split()), int(n)) for n, k, p in befehle}
    assert {(k, " ".join(p), n) for _, k, p, n in probelauf.STUFEN} <= im_plan
    # Auswertung der Folge
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "folge" / "cache",
                                                            tmp_path / "folge" / "ergebnisse")
    assert "erfundenen Daten" in aus and "| 1 | test | 3 | 0 | 200×3 |" in aus
    assert "| 2 | kennzahlen | 7 | 3 | 200×6, 404×1 |" in aus
    assert "erwartet: Test mit URL-kodiertem Parameter" in aus
    assert "Parameter created_since, created_until, page; URL-kodiert nein" in aus
    assert "| underDirectionOf | 0 | 600 | 0 % |" in aus
    assert "Regel Stufe 3/5 (Jahresfilter wirkt, keine Doppelungen): erfüllt" in aus
    if ("6", "pdf-koepfe") in gemessen:   # gleichmäßig über 2019–2026
        assert "je Jahr: 2019 12, 2020 12, 2021 12, 2022 12, 2023 13, 2024 13, 2025 13, 2026 13" in aus


class ScheinProxy:
    """Lokaler Schein-Proxy: beantwortet jeden Tunnel (CONNECT) mit `connect` (Vorgabe 403) und unverschlüsselte
    Anfragen mit `get` (Vorgabe 407); er leitet nichts weiter. `anfragen`: (Methode, Ziel)."""

    def __init__(self, connect=403, get=407):
        self.anfragen = []
        proxy = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ablehnen(self, code):
                proxy.anfragen.append((self.command, self.path))
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_CONNECT(self):
                self._ablehnen(connect)

            def do_GET(self):
                self._ablehnen(get)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def test_mindestabstand_fuer_anfragen_an_die_stadt(server, tmp_path, monkeypatch):
    om = importlib.import_module("oparl_messung")
    basis = {"RATSATLAS_MAX_ANFRAGEN": "3", "RATSATLAS_KONTAKT": "kontakt@example.invalid"}
    assert om.sichere_vorgaben({**basis, "RATSATLAS_ABSTAND": "3"}) == (
        {"wiederholungen": 0, "max_dauer": 5.0, "max_anfragen": 3, "abstand": 3.0}, [])
    for wert in ("1.9", "0", "-2", "nan", "inf"):
        assert any("RATSATLAS_ABSTAND" in f for f in om.sichere_vorgaben({**basis, "RATSATLAS_ABSTAND": wert})[1]), wert
    # als Prozess: alles übrige streng, aber RATSATLAS_ABSTAND=0 (aus probelauf.umgebung) → Abbruch vor der ersten Anfrage
    fremd = {"RATSATLAS_OPARL_SYSTEM": "http://example.invalid/oparl/system",
             "RATSATLAS_OPARL_BODY": "http://example.invalid/oparl/bodies/x", "RATSATLAS_STADT_INFORMIERT": "ja",
             "RATSATLAS_KONTAKT": "kontakt@example.invalid"}
    m = lauf(server, tmp_path, "test", obergrenze=3, **fremd)
    assert m["rc"] == 1 and "Abbruch vor der ersten Anfrage" in m["stderr"] and "RATSATLAS_ABSTAND" in m["stderr"]
    assert server.anfragen == [] and not (tmp_path / "cache" / "abrufe.tsv").exists()
    # vor jeder Anfrage an die Stadt: Abstand unter 2 s → kein Abruf; 2 s → Abruf
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setenv("RATSATLAS_ZEITFENSTER", "")
    for name, wert in (("WIEDERHOLUNGEN", 0), ("MAX_DAUER", 5.0), ("MAX_ANFRAGEN", 3),
                       ("KONTAKT", "kontakt@example.invalid"), ("ABSTAND", 1.0)):
        monkeypatch.setattr(om.abruf, name, wert)
    monkeypatch.setattr(om, "hole", lambda *a, **k: b"geholt")   # kein Netz
    with pytest.raises(om.Abbruch, match="Abstand mindestens 2 s"):
        om._hole("https://example.invalid/oparl/system")
    monkeypatch.setattr(om.abruf, "ABSTAND", 2.0)
    assert om._hole("https://example.invalid/oparl/system") == b"geholt"


def test_proxy_ablehnung_erkennen():
    abruf = importlib.import_module("abruf")

    def tunnel(code, text):
        return urllib.error.URLError(OSError(f"Tunnel connection failed: {code} {text}"))
    for code, text in ((403, "Forbidden"), (405, "Method Not Allowed"), (407, "Proxy Authentication Required")):
        assert abruf.proxy_ablehnung(tunnel(code, text)) == code == abruf.tunnel_status(tunnel(code, text))
    assert abruf.proxy_ablehnung(urllib.error.HTTPError("http://x/", 407, "Proxy Authentication Required", {}, None)) == 407
    assert abruf.proxy_ablehnung(urllib.error.HTTPError("http://x/", 403, "Forbidden", {}, None)) is None
    # Proxy erreicht das Ziel nicht (502, 504) oder meldet Begrenzung/Überlastung (429, 503): keine Ablehnung
    for code, text in ((502, "Bad Gateway"), (504, "Gateway Timeout"), (503, "Service Unavailable"),
                       (429, "Too Many Requests")):
        assert abruf.proxy_ablehnung(tunnel(code, text)) is None and abruf.tunnel_status(tunnel(code, text)) == code
    for fehler in (urllib.error.URLError(ConnectionResetError("reset")), TimeoutError("timed out")):
        assert abruf.proxy_ablehnung(fehler) is None and abruf.tunnel_status(fehler) is None   # mögliche Sperre


def _fremd_ueber(proxy):
    """Umgebung für oparl_messung.py: Adressen der Stadt durch example.invalid ersetzt, alles über den Schein-Proxy."""
    return {"RATSATLAS_OPARL_SYSTEM": "https://example.invalid/oparl/system",
            "RATSATLAS_OPARL_BODY": "https://example.invalid/oparl/bodies/x", "RATSATLAS_STADT_INFORMIERT": "ja",
            "RATSATLAS_KONTAKT": "kontakt@example.invalid", "RATSATLAS_ABSTAND": "2",
            "HTTPS_PROXY": proxy.url, "https_proxy": proxy.url, "HTTP_PROXY": proxy.url, "http_proxy": proxy.url,
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}


@pytest.mark.parametrize("code", [403, 407])
def test_proxy_ablehnung_ist_keine_sperre(server, tmp_path, code):
    with ScheinProxy(connect=code) as proxy:
        m = lauf(server, tmp_path, "test", obergrenze=3, **_fremd_ueber(proxy))
    assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (proxy)", m["stderr"]
    assert proxy.anfragen == [("CONNECT", "example.invalid:443")]      # genau ein Versuch, keine Wiederholung
    assert m["server"] == 0 and m["lauf"]["netz"] == "1"
    assert "keine Anfrage hat die Stadt erreicht" in m["stderr"] and "example.invalid muss im Netz" in m["stderr"]
    z = protokoll(tmp_path)[-1]
    assert (z["status"], z["quelle"]) == (f"proxy {code}", "netz")
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert "## Ablehnungen durch den Proxy der Arbeitsumgebung" in aus
    assert "Lauf 1 (test): 1 Anfrage(n) vom Proxy abgelehnt (Host example.invalid)" in aus
    assert f"Status proxy {code} × 1 (Ablehnung durch den Proxy der Arbeitsumgebung" in aus
    assert "mögliche Sperre" not in aus
    assert f"| – | test | 1 | 0 | proxy {code}×1 | – | – | 0 | abbruch (proxy) |" in aus   # keine Antwortzeit der Stadt


@pytest.mark.parametrize("code", [502, 504])
def test_proxy_erreicht_das_ziel_nicht_ist_moegliche_sperre(server, tmp_path, code):
    # 502/504 auf CONNECT: Der Proxy hat die Stadt angefragt, aber nicht erreicht – so zeigte sich die Sperre bei mandari
    with ScheinProxy(connect=code) as proxy:
        m = lauf(server, tmp_path, "test", obergrenze=3, **_fremd_ueber(proxy))
    assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (sperre)", m["stderr"]
    assert proxy.anfragen == [("CONNECT", "example.invalid:443")]      # genau ein Versuch, keine Wiederholung
    assert "mögliche Sperre" in m["lauf"]["meldung"] and "kein Hinweis auf eine Sperre" not in m["stderr"]
    z = protokoll(tmp_path)[-1]
    assert (z["status"], z["quelle"]) == (f"tunnel {code}", "netz")
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert f"Status tunnel {code} × 1 (beim Verbindungsaufbau über den Proxy: der Proxy erreicht den Server nicht; " \
           "mögliche Sperre: stoppen)" in aus
    assert "## Ablehnungen durch den Proxy der Arbeitsumgebung" not in aus


@pytest.mark.parametrize("code, art", [(403, "proxy"), (405, "proxy"), (407, "proxy"), (502, "sperre"),
                                       (504, "sperre"), (500, "sperre"), (429, "server"), (503, "server")])
def test_connect_antworten_des_proxys(tmp_path, monkeypatch, code, art):
    """Jede Antwort ≠ 200 auf CONNECT bricht ohne Wiederholung ab, auch wenn Wiederholungen nach 429/5xx erlaubt
    wären; nur 403/405/407 gelten als Ablehnung durch den Proxy (keine Sperre)."""
    abruf = importlib.import_module("abruf")
    with ScheinProxy(connect=code) as proxy:
        for name in ("HTTPS_PROXY", "https_proxy"):
            monkeypatch.setenv(name, proxy.url)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(name, "127.0.0.1,localhost")
        # Öffner neu bauen: der Proxy aus der Umgebung gilt ab dem Bau (sonst der Proxy der Arbeitsumgebung)
        monkeypatch.setattr(abruf, "_OEFFNER", urllib.request.build_opener(abruf._OhneWeiterleitung))
        for name, wert in (("CACHE", tmp_path), ("PROTOKOLL", tmp_path / "abrufe.tsv"), ("ABSTAND", 0.0),
                           ("WIEDERHOLUNGEN", 4), ("PAUSEN", [0.01] * 4), ("MAX_ANFRAGEN", 0),
                           ("_erste_netzanfrage", True), ("_sperre", None)):
            monkeypatch.setattr(abruf, name, wert)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.hole("https://example.invalid/oparl/system", ".json")
    assert (e.value.art, e.value.code) == (art, code)
    assert proxy.anfragen == [("CONNECT", "example.invalid:443")]
    assert ("mögliche Sperre" in str(e.value)) == (art == "sperre")
    assert ("kein Hinweis auf eine Sperre" in str(e.value)) == (art == "proxy")
    z = tsv(tmp_path / "abrufe.tsv")[-1]
    assert z["status"] == (f"proxy {code}" if art == "proxy" else f"tunnel {code}")


def test_mindestabstand_auch_zwischen_zwei_prozessen(server, tmp_path):
    """Zwei Prozesse nacheinander mit demselben Cache (wie Stufe 3): Auch die erste Anfrage des zweiten Prozesses folgt
    frühestens 2 s nach dem Ende der letzten Antwort des ersten, die erste des ersten frühestens 2 s nach dem Start."""
    env = probelauf.umgebung(server, tmp_path / "cache", tmp_path / "ergebnisse", 1)
    env["RATSATLAS_ABSTAND"] = "2"
    skript = "import sys; sys.path.insert(0, sys.argv[1]); import abruf; abruf.hole(sys.argv[2], '.json')"
    starts = []
    for url in (server.system_url, server.body_url):
        starts.append(time.monotonic())
        r = subprocess.run([sys.executable, "-c", skript, str(EXPLORE), url], env=env, capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stderr
    assert len(server.eingang) == 2 and len(server.ausgang) == 2
    assert server.eingang[0] - starts[0] >= 2.0                       # erste Anfrage frühestens 2 s nach dem Start
    assert server.eingang[1] - server.ausgang[0] >= 2.0               # Prozessgrenze: Abstand ab Ende der Antwort
    assert [z["quelle"] for z in protokoll(tmp_path)] == ["netz", "netz"]


def test_erste_anfrage_wartet_auf_letzte_netzanfrage_im_protokoll(tmp_path, monkeypatch):
    abruf = importlib.import_module("abruf")
    jetzt = dt.datetime.now(ZoneInfo("Europe/Berlin")).replace(microsecond=0)
    kopf = "zeit\turl\tstatus\tbytes\tdauer_s\tquelle\tziel\n"
    pfad = tmp_path / "abrufe.tsv"
    pfad.write_text(kopf + f"{jetzt.isoformat()}\thttp://127.0.0.1:1/a\t200\t1\t0.10\tnetz\t\n"
                    "2099-01-01T00:00:00+01:00\thttp://127.0.0.1:1/b\tcache\t1\t0.00\tcache\t\n", encoding="utf-8")
    assert abruf.letzte_netzanfrage(pfad) == jetzt.timestamp()       # Zeilen aus dem Cache zählen nicht
    gewartet = []
    monkeypatch.setattr(abruf, "time", types.SimpleNamespace(monotonic=time.monotonic, time=time.time,
                                                              sleep=gewartet.append))
    for name, wert in (("PROTOKOLL", pfad), ("ABSTAND", 2.0), ("_letzte", time.monotonic() - 100),
                       ("_erste_netzanfrage", True)):
        monkeypatch.setattr(abruf, name, wert)
    abruf._warten()                    # Import lange her, aber die letzte Netzanfrage laut Protokoll gerade eben
    nach = time.time()
    assert len(gewartet) == 1 and gewartet[0] <= 3.0
    # Anfrage frühestens 2 s nach dem Ende der Antwort; das Ende liegt vor jetzt + 1 s (Zeit sekundengenau)
    assert nach + gewartet[0] >= jetzt.timestamp() + 3.0 - 1e-6
    abruf._warten()                    # danach gilt nur noch der Abstand innerhalb des Prozesses
    assert len(gewartet) == 1
    # ältere Netzanfrage (vor einer Stunde): kein Warten
    pfad.write_text(kopf + f"{(jetzt - dt.timedelta(hours=1)).isoformat()}\thttp://127.0.0.1:1/a\t200\t1\t0.10\tnetz\t\n",
                    encoding="utf-8")
    monkeypatch.setattr(abruf, "_erste_netzanfrage", True)
    abruf._warten()
    assert len(gewartet) == 1


def test_geodaten_mindestwerte_und_ende_nach_sperre(tmp_path, monkeypatch):
    """explore/geodaten.py ohne Netz (hole ersetzt): Abstand ≥ 2 s, keine Wiederholung und eine Obergrenze vor der
    ersten Anfrage erzwungen; nach sperre/server/proxy/obergrenze/langsam/parallel und HTTP 401/403/429 endet der ganze
    Lauf, nach einer Weiterleitung oder HTTP 404 nur dieser Katalog."""
    geodaten = importlib.import_module("geodaten")
    abruf = importlib.import_module("abruf")
    grenze = {"RATSATLAS_MAX_ANFRAGEN": "40"}
    assert geodaten.vorgaben(grenze) == ({"wiederholungen": 0, "abstand": 2.0, "max_anfragen": 40}, [])
    assert any("RATSATLAS_MAX_ANFRAGEN" in f for f in geodaten.vorgaben({})[1])     # Obergrenze ist Pflicht
    for env in ({"RATSATLAS_ABSTAND": "1.5"}, {"RATSATLAS_ABSTAND": "nan"}, {"RATSATLAS_WIEDERHOLUNGEN": "2"},
                {"RATSATLAS_ABSTAND": "x"}, {"RATSATLAS_MAX_ANFRAGEN": "0"}, {"RATSATLAS_MAX_ANFRAGEN": "x"}):
        assert geodaten.vorgaben({**grenze, **env})[1], env
    for name in ("RATSATLAS_ABSTAND", "RATSATLAS_WIEDERHOLUNGEN", "RATSATLAS_MAX_ANFRAGEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(abruf, "ABSTAND", 0.0)
    monkeypatch.setattr(abruf, "WIEDERHOLUNGEN", 4)
    monkeypatch.setattr(abruf, "MAX_ANFRAGEN", 0)
    erg = tmp_path / "ergebnisse"
    monkeypatch.setattr(geodaten, "ERG", erg)
    aufrufe = []

    def schein(fehler_bei):
        """hole ohne Netz: Katalogseite mit DCAT-Verweis, DCAT mit einer Datei; Abbruch bei der Endung `fehler_bei`."""
        def hole(url, endung="", cache=True):
            aufrufe.append(url)
            if endung in fehler_bei:
                raise fehler_bei[endung]
            if endung == ".html":
                return b'<a href="/node/1/dcatapde.json">DCAT</a>'
            return json.dumps([{"@id": "d", "@type": [geodaten.DCAT + "Dataset"],
                                geodaten.DCAT + "distribution": [{"@id": "v"}]},
                               {"@id": "v", geodaten.DCAT + "downloadURL": [
                                   {"@value": f"{geodaten.BASIS}/sites/default/files/x.zip"}]}]).encode()
        return hole

    monkeypatch.setattr(geodaten, "hole", schein({}))
    assert geodaten.main() == 1 and aufrufe == []                     # ohne Obergrenze: Abbruch vor der ersten Anfrage
    monkeypatch.setenv("RATSATLAS_MAX_ANFRAGEN", "40")
    monkeypatch.setenv("RATSATLAS_ABSTAND", "0.5")
    assert geodaten.main() == 1 and aufrufe == []                     # zu kleiner Abstand: ebenso
    monkeypatch.delenv("RATSATLAS_ABSTAND")
    for art, code in (("sperre", None), ("server", 429), ("proxy", 403), ("obergrenze", None), ("langsam", None),
                      ("parallel", None), ("http", 401), ("http", 403), ("http", 429)):
        for endung in (".html", ".zip"):                             # Katalog oder Datei
            aufrufe.clear()
            monkeypatch.setattr(geodaten, "hole", schein({endung: abruf.Abbruch(f"Test {art}", art, code)}))
            assert geodaten.main() == 2, (art, code, endung)
            assert len(aufrufe) == (1 if endung == ".html" else 3)    # keine weitere Anfrage
            assert not erg.exists()                                   # Ergebnisdateien unverändert
    assert (abruf.ABSTAND, abruf.WIEDERHOLUNGEN, abruf.MAX_ANFRAGEN) == (2.0, 0, 40)
    # Weiterleitung und HTTP 404: nur dieser Katalog, die übrigen Datensätze laufen weiter
    weiter = abruf.Abbruch("Weiterleitung HTTP 301 nach https://example.invalid/neu nicht verfolgt", "weiterleitung",
                           301, "https://example.invalid/neu")
    for fehler, text in ((weiter, "example.invalid/neu"), (abruf.Abbruch("HTTP 404: x", "http", 404), "HTTP 404")):
        aufrufe.clear()
        monkeypatch.setattr(geodaten, "hole", schein({".html": fehler}))
        assert geodaten.main() == 0 and len(aufrufe) == len(geodaten.DATENSAETZE)
        kat = tsv(erg / "geodaten_katalog.tsv")
        assert len(kat) == len(geodaten.DATENSAETZE) and all(text in z["titel"] for z in kat)


def _laeufe(erg, *zeilen):
    kopf = ("lauf", "stufe", "kommando", "parameter", "start", "ende", "dauer_s", "netz", "cache", "obergrenze",
            "protokoll_von", "protokoll_bis", "ergebnis", "meldung")
    erg.mkdir(parents=True, exist_ok=True)
    (erg / "oparl_laeufe.tsv").write_text("\n".join("\t".join(map(str, z)) for z in (kopf, *zeilen)) + "\n",
                                          encoding="utf-8")


def test_auswertung_ordnet_protokollzeilen_nur_im_zeitraum_des_laufs_zu(tmp_path):
    auswertung = importlib.import_module("auswertung")
    cache, erg = tmp_path / "cache", tmp_path / "ergebnisse"
    cache.mkdir()
    zeilen = [("2026-11-07T23:05:01+01:00", "https://example.invalid/a"),   # Lauf 1
              ("2026-11-07T23:05:03+01:00", "https://example.invalid/b"),   # Lauf 1
              ("2026-11-08T23:05:01+01:00", "https://example.invalid/c"),   # vor dem Start von Lauf 2
              ("2026-11-09T23:05:01", "https://example.invalid/d")]         # ohne Zone (Lauf 3)
    (cache / "abrufe.tsv").write_text("zeit\turl\tstatus\tbytes\tdauer_s\tquelle\tziel\n" + "".join(
        f"{t}\t{u}\t200\t10\t0.50\tnetz\t\n" for t, u in zeilen), encoding="utf-8")
    _laeufe(erg, (1, 1, "test", "", "2026-11-07T23:05:00+01:00", "2026-11-07T23:05:09+01:00", 9, 2, 0, 3, 0, 2, "ok", ""),
            (2, 2, "kennzahlen", "", "2026-11-08T23:10:00+01:00", "2026-11-08T23:10:09+01:00", 9, 1, 0, 10, 2, 3, "ok", ""),
            (3, 3, "organisationen", "", "2026-11-09T23:05:00+01:00", "2026-11-09T23:05:09+01:00", 9, 1, 0, 5, 3, 4,
             "ok", ""),
            (4, 4, "sitzungen", "", "2026-11-10T23:05:00+01:00", "2026-11-10T23:05:09+01:00", 9, 2, 0, 3, 4, 6, "ok", ""))
    aus = auswertung.auswertung(cache, erg)
    assert "| 1 | test | 2 | 0 | 200×2 | 0.50 | 0.50 | 20 | ok |" in aus
    for nr, kommando in ((2, "kennzahlen"), (3, "organisationen"), (4, "sitzungen")):
        assert (f"Lauf {nr} ({kommando}): Statuscodes und Antwortzeiten nicht prüfbar (Protokollzeilen passen nicht "
                "zum Lauf)") in aus
    assert "| 2 | kennzahlen | 1 | 0 | nicht prüfbar (Protokollzeilen passen nicht zum Lauf) |" in aus
    assert "Weitere Zeilen im Abrufprotokoll ohne Lauf (z. B. geodaten.py oder Zeit außerhalb eines Laufs): 2" in aus
    # ohne Abrufprotokoll bleibt es bei „Protokoll fehlt“
    assert "Statuscodes und Antwortzeiten nicht prüfbar (Protokoll fehlt)" in auswertung.auswertung(tmp_path / "x", erg)


def test_regel_stufe_3_5_nur_nach_vollstaendigem_lauf(tmp_path):
    auswertung = importlib.import_module("auswertung")
    null = [{"feld": f, "vorhanden": "0", "von": "200"} for f in (
        "created außerhalb des Filterjahres", "doppelte Kennungen im selben Jahr (Seiten verschoben)",
        "doppelte Kennungen aus anderen Jahren (Jahresfilter wirkt nicht)")]
    ok = {"lauf": "4", "kommando": "stichprobe", "ergebnis": "ok"}
    abgebrochen = {"lauf": "5", "kommando": "stichprobe", "ergebnis": "abbruch (proxy)"}
    andere = {"lauf": "6", "kommando": "sitzungen", "ergebnis": "abbruch (server)"}
    assert auswertung.regel_stufe_3_5(null, [ok, andere]) == "erfüllt"
    assert auswertung.regel_stufe_3_5(null, [ok, abgebrochen]).startswith("nicht prüfbar (Lauf abgebrochen)")
    assert auswertung.regel_stufe_3_5(null, []).startswith("nicht prüfbar")
    eins = [dict(null[0], vorhanden="1")] + null[1:]
    assert auswertung.regel_stufe_3_5(eins, [ok]).startswith("nicht erfüllt")
    # in der Auswertung: Zählungen 0, aber der letzte stichprobe-Lauf ist abgebrochen
    erg = tmp_path / "ergebnisse"
    _laeufe(erg, (4, 3, "stichprobe", "", "2026-11-09T23:05:00+01:00", "2026-11-09T23:05:30+01:00", 30, 9, 0, 9, 0, 0,
                  "ok", ""),
            (5, 5, "stichprobe", "", "2026-11-11T23:05:00+01:00", "2026-11-11T23:05:01+01:00", 1, 1, 0, 25, 0, 0,
             "abbruch (proxy)", "Ablehnung durch den Proxy"))
    (erg / "oparl_stichprobe_bedeckung.tsv").write_text("feld\tvorhanden\tvon\n" + "".join(
        f"{z['feld']}\t0\t200\n" for z in null), encoding="utf-8")
    aus = auswertung.auswertung(tmp_path / "cache", erg)
    assert "Regel Stufe 3/5 (Jahresfilter wirkt, keine Doppelungen): nicht prüfbar (Lauf abgebrochen)" in aus
    assert "Regel Stufe 3/5 (Jahresfilter wirkt, keine Doppelungen): erfüllt" not in aus


def test_stufenbefehle_mit_kontakt_und_strengen_vorgaben():
    om = importlib.import_module("oparl_messung")
    text = (EXPLORE / "STUFEN.md").read_text(encoding="utf-8")
    assert "<Kontaktadresse" not in text
    befehle = [z for z in text.splitlines() if "oparl_messung.py" in z and z.startswith("RATSATLAS_")]
    assert len(befehle) == 8
    for b in befehle:
        env = {k: v.strip('"') for k, v in re.findall(r'(RATSATLAS_[A-Z_]+)=("[^"]*"|\S+)', b)}
        assert env["RATSATLAS_KONTAKT"] == "contact@nozilla.de", b
        if env["RATSATLAS_MAX_ANFRAGEN"].isdigit():   # Stufe 4 optional: Obergrenze erst nach Stufe 2
            werte, fehler = om.sichere_vorgaben(env)
            assert fehler == [] and werte["abstand"] >= 2, (b, fehler)


def _abruf_im_prozess(monkeypatch, cache, **zusatz):
    """explore/abruf.py im Testprozess: eigener Cache, Abstand 0, Wiederholungen erlaubt (um zu zeigen, dass trotzdem
    nicht wiederholt wird), Öffner ohne Proxy; die Sperrdatei des Prozesses wird nach dem Test freigegeben."""
    abruf = importlib.import_module("abruf")
    werte = {"CACHE": cache, "PROTOKOLL": cache / "abrufe.tsv", "ABSTAND": 0.0, "WIEDERHOLUNGEN": 4,
             "PAUSEN": [0.01] * 4, "MAX_ANFRAGEN": 0, "_erste_netzanfrage": True, "_sperre": None,
             "_OEFFNER": urllib.request.build_opener(abruf._OhneWeiterleitung, urllib.request.ProxyHandler({}))}
    for name, wert in {**werte, **zusatz}.items():
        monkeypatch.setattr(abruf, name, wert)
    return abruf


UNVOLLSTAENDIG = {   # (Antwort, Status im Protokoll, Bytes im Protokoll)
    "content-length": (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n"
                       b"{\"data\": [", "IncompleteRead", 10),
    "chunked": (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                b"5\r\n{\"a\":\r\n", "IncompleteRead", 5),
    "statuszeile": (b"GARBAGE\r\n\r\n", "BadStatusLine", 0),
}


@pytest.mark.parametrize("fall", list(UNVOLLSTAENDIG))
def test_abgeschnittene_oder_unlesbare_antwort_ist_moegliche_sperre(tmp_path, monkeypatch, roher_server, fall):
    """Weniger Bytes als Content-Length (read(n) meldet das nicht), chunked ohne Abschluss, unlesbare Statuszeile:
    Art `sperre`, eine Anfrage, Protokollzeile, nichts im Cache."""
    antwort, status, n = UNVOLLSTAENDIG[fall]
    server = roher_server(antwort)
    abruf = _abruf_im_prozess(monkeypatch, tmp_path)
    url = f"{server.url}/oparl/system"
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(url, ".json")
    assert e.value.art == "sperre" and "mögliche Sperre" in str(e.value)
    assert server.anfragen == ["GET /oparl/system HTTP/1.1"]          # keine Wiederholung trotz WIEDERHOLUNGEN=4
    z = tsv(tmp_path / "abrufe.tsv")[-1]
    assert (z["status"], z["bytes"], z["quelle"]) == (status, str(n), "netz")
    assert not abruf._cachepfad(url, ".json").exists()               # nichts im Cache


def test_unlesbare_connect_antwort_ist_moegliche_sperre(tmp_path, monkeypatch, roher_server):
    proxy = roher_server(b"GARBAGE\r\n\r\n")
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, proxy.url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    abruf = importlib.import_module("abruf")
    abruf = _abruf_im_prozess(monkeypatch, tmp_path, _OEFFNER=urllib.request.build_opener(abruf._OhneWeiterleitung))
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole("https://example.invalid/oparl/system", ".json")
    assert e.value.art == "sperre" and "BadStatusLine" in str(e.value)
    assert proxy.anfragen == ["CONNECT example.invalid:443 HTTP/1.1"]
    assert tsv(tmp_path / "abrufe.tsv")[-1]["status"] == "BadStatusLine"


def test_abgeschnittene_antwort_beendet_den_lauf_als_moegliche_sperre(server, tmp_path):
    server.abschneiden = lambda pfad: pfad.endswith("/bodies/testkoerperschaft")
    m = lauf(server, tmp_path, "test", obergrenze=3)
    assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (sperre)", m["stderr"]
    assert m["server"] == 2 and "Mögliche Sperre" in m["stderr"]
    assert protokoll(tmp_path)[-1]["status"] == "IncompleteRead"
    assert len(list((tmp_path / "cache" / "roh").glob("*.json"))) == 1   # nur das System, nicht der Body
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert "Status IncompleteRead × 1 (mögliche Sperre: stoppen)" in aus


@pytest.mark.parametrize("code", [502, 504])
def test_502_504_als_antwort_ist_moegliche_sperre(server, tmp_path, monkeypatch, code):
    """HTTP 502/504 als Antwort (auch im Tunnel des Proxys der Arbeitsumgebung): mögliche Sperre, keine Wiederholung;
    503 bleibt Art `server` (mit erlaubten Wiederholungen wiederholt)."""
    server.stoerung = lambda pfad, abfrage: code if pfad.endswith("/oparl/system") else None
    m = lauf(server, tmp_path, "test", obergrenze=3)
    assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (sperre)", m["stderr"]
    assert m["server"] == 1 and "Mögliche Sperre" in m["stderr"]
    assert protokoll(tmp_path)[-1]["status"] == str(code)
    abruf = _abruf_im_prozess(monkeypatch, tmp_path / "im_prozess")
    vorher = len(server.anfragen)
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(server.system_url, ".json")
    assert (e.value.art, e.value.code) == ("sperre", code) and len(server.anfragen) - vorher == 1
    server.stoerung = lambda pfad, abfrage: 503
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(server.system_url, ".json")
    assert (e.value.art, e.value.code) == ("server", 503) and len(server.anfragen) - vorher == 6


def test_zweiter_gleichzeitiger_prozess_bricht_vor_der_ersten_anfrage_ab(server, tmp_path):
    """Sperre abruf.lock (Ort RATSATLAS_SPERRE, hier tmp_path/sperre): Hält ein Prozess sie, bricht ein zweiter ohne
    Anfrage ab, auch mit anderem Cache (wie aus einer anderen Arbeitskopie)."""
    env = probelauf.umgebung(server, tmp_path / "cache", tmp_path / "ergebnisse", 3)
    assert env["RATSATLAS_SPERRE"] == str(tmp_path / "sperre")
    halter = ("import sys; sys.path.insert(0, sys.argv[1]); import abruf; abruf.sperre_halten(); "
              "print('bereit', flush=True); sys.stdin.read()")
    p = subprocess.Popen([sys.executable, "-c", halter, str(EXPLORE)], env=env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "bereit"
        m = lauf(server, tmp_path, "test", obergrenze=3, cache="anderer_cache")   # gleiche Sperre, anderer Cache
        assert m["rc"] == 2 and m["lauf"]["ergebnis"] == "abbruch (parallel)", m["stderr"]
        assert server.anfragen == [] and m["lauf"]["netz"] == "0" and "anderer Abrufprozess" in m["stderr"]
        assert not (tmp_path / "cache" / "abrufe.tsv").exists() and (tmp_path / "sperre" / "abruf.lock").exists()
    finally:
        p.stdin.close()
        p.wait(timeout=30)
    m = lauf(server, tmp_path, "test", obergrenze=3, cache="anderer_cache")   # danach ist die Sperre frei
    assert m["rc"] == 0 and m["server"] == 3, m["stderr"]
    assert len(protokoll(tmp_path, "anderer_cache")) == 3


def test_unlesbare_antwort_wird_aus_dem_cache_entfernt(server, tmp_path, monkeypatch):
    """oparl_messung._json: Eine unlesbare Antwort (HTML mit Status 200) bleibt nicht im Cache; ein späterer Lauf liest
    sie nicht ohne Anfrage als gültig, sondern fragt erneut."""
    om = importlib.import_module("oparl_messung")
    abruf = _abruf_im_prozess(monkeypatch, tmp_path / "cache")
    server.stoerung = lambda pfad, abfrage: 200 if pfad.endswith("/bodies/testkoerperschaft") else None
    pfad = abruf._cachepfad(server.body_url, ".json")
    with pytest.raises(ValueError):
        om._json(server.body_url)
    assert not pfad.exists() and len(server.anfragen) == 1
    server.stoerung = lambda pfad, abfrage: None
    assert om._json(server.body_url)["id"] == server.body_url                    # erneut gefragt, jetzt gültig
    assert len(server.anfragen) == 2 and pfad.exists()
    assert om._json(server.body_url)["id"] == server.body_url and len(server.anfragen) == 2   # aus dem Cache


def test_letzter_abbruch_innerhalb_von_12_stunden(tmp_path):
    om = importlib.import_module("oparl_messung")
    erg, jetzt = tmp_path / "erg", dt.datetime(2026, 11, 8, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    datei = erg / "oparl_laeufe.tsv"
    assert om.letzter_abbruch(datei, jetzt) is None                       # noch kein Lauf

    def zeile(nr, ende, ergebnis):
        return (nr, 3, "organisationen", "--seiten 4", ende, ende, 1, 2, 0, 5, 0, 2, ergebnis, "Test")
    for ende, ergebnis, gesperrt in (
            ("2026-11-07T23:10:00+01:00", "abbruch (server)", True),
            ("2026-11-07T23:10:00+01:00", "abbruch (proxy)", True),
            ("2026-11-07T23:10:00+01:00", "fehler (JSONDecodeError)", True),
            ("2026-11-07T23:10:00", "abbruch (sperre)", True),            # ohne Zone: Ortszeit Köln
            ("", "abbruch (sperre)", True),                               # ohne Ende: vorsichtshalber gesperrt
            ("2026-11-07T23:10:00+01:00", "ok", False),
            ("2026-11-07T23:10:00+01:00", "unterbrochen", True),          # Strg+C oder Signal (Runde 9)
            ("2026-11-07T23:10:00+01:00", "abbruch (tls)", True),         # Einstellung, aber Sperrfrist
            ("2026-11-07T12:29:00+01:00", "abbruch (server)", False)):    # vor mehr als 12 Stunden
        _laeufe(erg, zeile(1, "2026-11-06T23:10:00+01:00", "abbruch (sperre)"), zeile(2, ende, ergebnis))
        treffer = om.letzter_abbruch(datei, jetzt)
        assert (treffer is not None) == gesperrt, (ende, ergebnis)
        assert treffer is None or treffer["lauf"] == "2"                  # maßgeblich ist der letzte Lauf


def _wie_die_stadt(stadt, tmp_path, **zusatz):
    """Umgebung für oparl_messung.py gegen einen Testserver auf 127.0.0.2: gilt nicht als lokal, also gelten Freigabe,
    Zeitfenster (hier offen), strenge Vorgaben, Abstand ≥ 2 s und die Prüfung des letzten Laufs."""
    assert stadt.system_url.startswith("http://127.0.0.2:")
    keine = ",".join(x for x in (os.environ.get("NO_PROXY", ""), "127.0.0.1,127.0.0.2,localhost") if x)
    env = {k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_")}
    env.update({"RATSATLAS_OPARL_SYSTEM": stadt.system_url, "RATSATLAS_OPARL_BODY": stadt.body_url,
                "RATSATLAS_SPERRE": str(tmp_path / "sperre"),   # Sperrdatei nie in ~/.cache (echte Messung parallel)
                "RATSATLAS_STADT_INFORMIERT": "ja", "RATSATLAS_ZEITFENSTER": "",
                "RATSATLAS_KONTAKT": "kontakt@example.invalid", "RATSATLAS_WIEDERHOLUNGEN": "0",
                "RATSATLAS_MAX_DAUER": "5", "RATSATLAS_CACHE": str(tmp_path / "cache"),
                "RATSATLAS_ERGEBNISSE": str(tmp_path / "ergebnisse"), "NO_PROXY": keine, "no_proxy": keine, **zusatz})
    return env


def test_nach_abbruch_keine_weitere_anfrage_an_die_stadt(tmp_path):
    """Stufe 3 ohne `&&` ausgeführt: Der erste Prozess bricht mit 503 ab, der zweite schickt keine Anfrage (letzter Lauf
    in oparl_laeufe.tsv vor weniger als 12 Stunden abgebrochen)."""
    with testserver.Testserver(host="127.0.0.2") as stadt:
        stadt.stoerung = lambda pfad, abfrage: 503 if pfad.endswith("/organizations") else None
        skript = str(EXPLORE / "oparl_messung.py")
        erster = subprocess.run([sys.executable, skript, "organisationen", "--seiten", "4"], capture_output=True,
                                text=True, timeout=120,
                                env=_wie_die_stadt(stadt, tmp_path, RATSATLAS_STUFE="3", RATSATLAS_MAX_ANFRAGEN="5"))
        assert erster.returncode == 2 and len(stadt.anfragen) == 2, erster.stderr     # Body, Liste mit 503
        zweiter = subprocess.run([sys.executable, skript, "stichprobe", "--seiten", "1", "--von", "2019", "--bis",
                                  "2026"], capture_output=True, text=True, timeout=120,
                                 env=_wie_die_stadt(stadt, tmp_path, RATSATLAS_STUFE="3", RATSATLAS_MAX_ANFRAGEN="9"))
    assert zweiter.returncode == 1 and "RATSATLAS_NACH_ABBRUCH" in zweiter.stderr, zweiter.stderr
    assert "abbruch (server)" in zweiter.stderr
    assert len(stadt.anfragen) == 2                                           # keine Anfrage des zweiten Prozesses
    assert [z["ergebnis"] for z in tsv(tmp_path / "ergebnisse" / "oparl_laeufe.tsv")] == ["abbruch (server)"]


def test_freigabe_nach_abbruch_nur_ausdruecklich(tmp_path, monkeypatch):
    """Nach einem Abbruch vor weniger als 12 Stunden: ohne RATSATLAS_NACH_ABBRUCH keine Anfrage (Rückgabewert 1), mit
    RATSATLAS_NACH_ABBRUCH=ja geht der Lauf weiter (hier ohne Netz: hole ersetzt)."""
    om = importlib.import_module("oparl_messung")
    erg = tmp_path / "erg"
    jetzt = dt.datetime.now(ZoneInfo("Europe/Berlin")).replace(microsecond=0).isoformat()
    _laeufe(erg, (1, 3, "organisationen", "--seiten 4", jetzt, jetzt, 1, 2, 0, 5, 0, 2, "abbruch (server)", "503"))
    for name, wert in (("ERG", erg), ("SYSTEM", "https://example.invalid/oparl/system"),
                       ("BODY", "https://example.invalid/oparl/bodies/x"), ("_LISTEN", [])):
        monkeypatch.setattr(om, name, wert)
    for name, wert in (("WIEDERHOLUNGEN", 4), ("MAX_DAUER", 0.0), ("ABSTAND", 0.0), ("MAX_ANFRAGEN", 3),
                       ("KONTAKT", "kontakt@example.invalid"), ("PROTOKOLL", tmp_path / "cache" / "abrufe.tsv")):
        monkeypatch.setattr(om.abruf, name, wert)                          # main() setzt sie; danach zurück
                                                                           # (Markerdatei neben dem Protokoll in tmp_path)
    for name in ("RATSATLAS_NACH_ABBRUCH", "RATSATLAS_ABSTAND", "RATSATLAS_WIEDERHOLUNGEN", "RATSATLAS_MAX_DAUER"):
        monkeypatch.delenv(name, raising=False)
    for name, wert in (("RATSATLAS_STADT_INFORMIERT", "ja"), ("RATSATLAS_ZEITFENSTER", ""),
                       ("RATSATLAS_MAX_ANFRAGEN", "3"), ("RATSATLAS_KONTAKT", "kontakt@example.invalid")):
        monkeypatch.setenv(name, wert)
    geholt = []

    def hole(url, endung=""):
        geholt.append(url)
        raise om.Abbruch("Test: Zeitüberschreitung, mögliche Sperre", "sperre")
    monkeypatch.setattr(om, "hole", hole)
    with pytest.raises(SystemExit) as e:
        om.main(["test"])
    assert "RATSATLAS_NACH_ABBRUCH" in str(e.value.code) and geholt == []
    monkeypatch.setenv("RATSATLAS_NACH_ABBRUCH", "ja")
    assert om.main(["test"]) == 2 and geholt == ["https://example.invalid/oparl/system"]
    assert [z["ergebnis"] for z in tsv(erg / "oparl_laeufe.tsv")] == ["abbruch (server)", "abbruch (sperre)"]


# --- Runde 9: Unterbrechung (Strg+C, SIGTERM, SIGHUP), Zertifikatsprüfung (Art `tls`), Kölner Antwortform aus Stufe 1,
# Probelauf Stufe 2 ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sig, rueckgabe", [(None, 130), (signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_unterbrochener_lauf_wird_vermerkt_und_sperrt_12_stunden(tmp_path, monkeypatch, sig, rueckgabe):
    """Strg+C (KeyboardInterrupt oder SIGINT) und SIGTERM (etwa Zeitlimit des aufrufenden Werkzeugs) enden gleich:
    Vermerk „unterbrochen“ in oparl_laeufe.tsv, danach gilt die 12-Stunden-Regel (SIGHUP als Prozess:
    test_sighup_wie_strg_c_ausser_mit_nohup). Die Signalbehandlung gilt nur während des Laufs (danach wieder die
    vorige). Eine Wache fängt SIGTERM, falls main() es nicht behandelt (sonst endete der Testprozess)."""
    om = importlib.import_module("oparl_messung")

    class Wache(Exception):
        pass

    def wache(nummer, _rahmen):
        raise Wache(nummer)
    alt = {s: signal.signal(s, wache) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        def kommando(_a):
            if sig is None:
                raise KeyboardInterrupt
            os.kill(os.getpid(), sig)
            time.sleep(5)
        monkeypatch.setitem(om.KOMMANDOS, "test", kommando)
        for name, wert in (("ERG", tmp_path / "erg"), ("SYSTEM", "http://127.0.0.1:9/oparl/system"),
                           ("BODY", "http://127.0.0.1:9/oparl/bodies/x"), ("_LISTEN", [])):
            monkeypatch.setattr(om, name, wert)
        monkeypatch.setattr(om.abruf, "PROTOKOLL", tmp_path / "abrufe.tsv")
        assert om.main(["test"]) == rueckgabe
        assert all(signal.getsignal(s) is wache for s in alt)          # vorige Behandlung wiederhergestellt
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    finally:
        for s, behandlung in alt.items():
            signal.signal(s, behandlung)
    datei = tmp_path / "erg" / "oparl_laeufe.tsv"
    zeile = tsv(datei)[-1]
    name = signal.Signals(sig).name if sig else "SIGINT"
    assert (zeile["ergebnis"], zeile["meldung"]) == ("unterbrochen", f"unterbrochen ({name})")
    assert om.letzter_abbruch(datei)["lauf"] == zeile["lauf"]           # Sperrfrist 12 Stunden


def test_sigterm_beendet_den_lauf_mit_vermerk_und_ohne_weitere_anfrage(tmp_path):
    """Als Prozess gegen einen Testserver, der wie die Stadt behandelt wird (127.0.0.2): SIGTERM nach der ersten Antwort
    (während des Abstands von 2 s) → Rückgabewert 143, Vermerk „unterbrochen (SIGTERM)“; ein zweiter Lauf schickt keine
    Anfrage (12-Stunden-Regel)."""
    with testserver.Testserver(host="127.0.0.2") as stadt:
        skript = str(EXPLORE / "oparl_messung.py")
        env = _wie_die_stadt(stadt, tmp_path, RATSATLAS_STUFE="1", RATSATLAS_MAX_ANFRAGEN="3")
        p = subprocess.Popen([sys.executable, skript, "test"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        frist, protokoll_datei = time.monotonic() + 30, tmp_path / "cache" / "abrufe.tsv"
        while time.monotonic() < frist and p.poll() is None and not (
                protokoll_datei.exists() and len(protokoll_datei.read_text(encoding="utf-8").splitlines()) >= 2):
            time.sleep(0.02)                                                # erste Antwort gelesen und vermerkt
        p.send_signal(signal.SIGTERM)
        _, fehler = p.communicate(timeout=30)
        n = len(stadt.anfragen)
        assert p.returncode == 143 and "Unterbrochen (SIGTERM)" in fehler, fehler
        zeile = tsv(tmp_path / "ergebnisse" / "oparl_laeufe.tsv")[-1]
        assert (zeile["ergebnis"], zeile["meldung"], zeile["netz"]) == ("unterbrochen", "unterbrochen (SIGTERM)", str(n))
        assert 1 <= n < 3
        zweiter = subprocess.run([sys.executable, skript, "test"], env=env, capture_output=True, text=True, timeout=60)
        assert zweiter.returncode == 1 and "RATSATLAS_NACH_ABBRUCH" in zweiter.stderr and "unterbrochen" in zweiter.stderr
        assert len(stadt.anfragen) == n                                   # keine Anfrage des zweiten Laufs


def test_zertifikatsfehler_erkennen():
    abruf = importlib.import_module("abruf")
    from pipeline import abruf as pabruf
    pruefung = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                                                "self-signed certificate (_ssl.c:1000)")
    ende = ssl.SSLEOFError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")
    for modul in (abruf, pabruf):
        assert modul.zertifikatsfehler(pruefung) and modul.zertifikatsfehler(urllib.error.URLError(pruefung))
        assert modul.zertifikatsfehler(urllib.error.URLError(ssl.SSLError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] x")))
        for anderer in (ende, urllib.error.URLError(ende), urllib.error.URLError(ConnectionResetError(104, "reset")),
                        urllib.error.URLError(OSError("Tunnel connection failed: 502 Bad Gateway")), TimeoutError(),
                        urllib.error.HTTPError("https://x/", 403, "CERTIFICATE_VERIFY_FAILED", {}, None)):
            assert not modul.zertifikatsfehler(anderer), anderer


def test_zertifikatsfehler_ist_keine_moegliche_sperre(tmp_path, monkeypatch, tls_server):
    """Lokaler TLS-Server mit selbst signiertem Zertifikat, dem der Client nicht vertraut: Art `tls`, keine HTTP-Anfrage
    beim Server, Status `tls` im Protokoll, nichts im Cache, keine Wiederholung. Gegenversuch: Mit vertrautem
    Zertifikat antwortet derselbe Server."""
    abruf = _abruf_im_prozess(monkeypatch, tmp_path)
    url = f"{tls_server.url}/oparl/system"
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(url, ".json")
    assert e.value.art == "tls" and "CERTIFICATE_VERIFY_FAILED" in str(e.value)
    assert "mögliche Sperre" not in str(e.value) and "vermutlich eine Einstellung der Arbeitsumgebung" in str(e.value)
    assert "Sperrseite nicht ausgeschlossen" in str(e.value) and "Berichten, nicht wiederholen" in str(e.value)
    assert tls_server.anfragen == []                                     # keine HTTP-Anfrage gesendet
    z = tsv(tmp_path / "abrufe.tsv")[-1]
    assert (z["status"], z["quelle"]) == ("tls", "netz") and not abruf._cachepfad(url, ".json").exists()
    kontext = ssl.create_default_context(cafile=str(tls_server.zertifikat))
    oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=kontext))
    assert oeffner.open(url, timeout=10).read() == b"{}" and tls_server.anfragen == ["/oparl/system"]


@pytest.mark.parametrize("reset", [False, True])
def test_andere_tls_fehler_bleiben_moegliche_sperre(tmp_path, monkeypatch, abbrechender_server, reset):
    server = abbrechender_server(reset)
    abruf = _abruf_im_prozess(monkeypatch, tmp_path)
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(f"{server.url}/oparl/system", ".json")
    assert e.value.art == "sperre" and "mögliche Sperre" in str(e.value)
    assert len(server.verbindungen) == 1                                 # keine Wiederholung trotz WIEDERHOLUNGEN=4


def test_zertifikatsfehler_im_lauf_mit_12_stunden_regel_und_auswertung(tmp_path, tls_server):
    """Als Prozess (Adresse gilt nicht als lokal: strenge Vorgaben, Abstand 2 s): Abbruch der Art `tls`, Hinweis auf die
    Einstellung der Arbeitsumgebung, keine mögliche Sperre; der nächste Lauf schickt keine Anfrage (12-Stunden-Regel).
    Die Auswertung nennt den Status `tls` ohne „mögliche Sperre“ und ohne Antwortzeit."""
    keine = ",".join(x for x in (os.environ.get("NO_PROXY", ""), "127.0.0.1,localhost") if x)
    env = {k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_")}
    env.update({"RATSATLAS_OPARL_SYSTEM": f"{tls_server.url}/oparl/system",
                "RATSATLAS_OPARL_BODY": f"{tls_server.url}/oparl/bodies/x", "RATSATLAS_STADT_INFORMIERT": "ja",
                "RATSATLAS_ZEITFENSTER": "", "RATSATLAS_KONTAKT": "kontakt@example.invalid",
                "RATSATLAS_MAX_ANFRAGEN": "3", "RATSATLAS_STUFE": "1", "RATSATLAS_SPERRE": str(tmp_path / "sperre"),
                "RATSATLAS_CACHE": str(tmp_path / "cache"), "RATSATLAS_ERGEBNISSE": str(tmp_path / "ergebnisse"),
                "NO_PROXY": keine, "no_proxy": keine})
    skript = str(EXPLORE / "oparl_messung.py")
    r = subprocess.run([sys.executable, skript, "test"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "Zertifikatsprüfung ist gescheitert" in r.stderr, r.stderr
    assert "Mögliche Sperre" not in r.stderr and tls_server.anfragen == []
    zeile = tsv(tmp_path / "ergebnisse" / "oparl_laeufe.tsv")[-1]
    assert (zeile["ergebnis"], zeile["netz"]) == ("abbruch (tls)", "1")
    zweiter = subprocess.run([sys.executable, skript, "test"], env=env, capture_output=True, text=True, timeout=60)
    assert zweiter.returncode == 1 and "RATSATLAS_NACH_ABBRUCH" in zweiter.stderr
    assert len(tsv(tmp_path / "cache" / "abrufe.tsv")) == 1               # keine weitere Anfrage
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert ("Status tls × 1 (Zertifikatsprüfung fehlgeschlagen: vermutlich Einstellung der Arbeitsumgebung (CA des "
            "Proxys); Zertifikat der Gegenseite oder Sperrseite nicht ausgeschlossen – berichten, nicht wiederholen)") in aus
    assert "mögliche Sperre" not in aus and "| 1 | test | 1 | 0 | tls×1 | – | – | 0 | abbruch (tls) |" in aus


@pytest.fixture
def koeln_server():
    """Testserver in der Kölner Antwortform aus Stufe 1 (explore/testserver.py, form „koeln“)."""
    with testserver.Testserver(form="koeln") as s:
        yield s


def test_koelner_form_wie_stufe_1(koeln_server):
    seite = json.loads(koeln_server.antwort("/oparl/bodies/testkoerperschaft/papers", "")[2])
    assert seite["pagination"] == {"elementsPerPage": 25, "currentPage": 1}
    assert sorted(seite["links"]) == ["first", "next", "self"] and seite["links"]["next"].endswith("/papers?page=2")
    assert sorted(seite["data"][0]) == ["auxiliaryFile", "body", "consultation", "created", "date", "id", "modified",
                                        "name", "paperType", "reference", "type"]
    erstellt = [p["created"] for p in koeln_server.daten.vorlagen]
    assert erstellt == sorted(erstellt, reverse=True)                     # neueste zuerst
    assert all(len(p["consultation"]) == 1 and sorted(p["consultation"][0]) == [
        "agendaItem", "id", "meeting", "organization", "role", "type"] for p in koeln_server.daten.vorlagen)
    assert {"Antrag nach § 3 BV2 (Die Linke)", "Änderungsantrag BV1 (FDP)", "Beschlussvorlage Bezirksvertretung"} <= {
        p["paperType"] for p in koeln_server.daten.vorlagen}
    body = koeln_server.daten.body()
    assert body["license"] is None and body["person"].endswith("/people") and len(body["legislativeTerm"]) == 3


def test_kennzahlen_stichprobe_und_auswertung_in_koelner_form(koeln_server, tmp_path):
    """kennzahlen und stichprobe ohne Gesamtzahlen: „fehlt“ statt None, keine Ausnahme; auswertung.py --stufe 2."""
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10, stufe="2")
    assert m["rc"] == 0 and m["server"] == 10, m["stderr"]
    werte = {(z["objekt"], z["feld"]): z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv")}
    for liste in ("paper", "meeting", "organization", "person"):
        assert werte[(liste, "pagination.totalElements")] == werte[(liste, "pagination.totalPages")] == "fehlt"
        assert werte[(liste, "links.schluessel")] == "first,next,self"
    assert werte[("person", "url")].endswith("/people") and werte[("body", "license")] == "null"
    assert werte[("paper", "test limit=100")] == "objekte=25; totalElements=fehlt"
    assert not any("None" in w for w in werte.values())
    m = lauf(koeln_server, tmp_path, "stichprobe", "--seiten", "1", "--von", "2025", "--bis", "2026", obergrenze=2,
             stufe="3")
    assert m["rc"] == 0 and m["server"] == 1, m["stderr"]                  # Body und Seite 2025 aus dem Cache
    assert {z["totalElements"] for z in tsv(tmp_path / "ergebnisse" / "oparl_stichprobe_jahre.tsv")} == {"fehlt"}
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse", "2")
    assert "| 2 | kennzahlen | 10 | 0 | 200×9, 404×1 |" in aus
    assert "| paper | fehlt | 25 | fehlt | 25 | first,next,self | gleicher Pfad; Parameter page; URL-kodiert nein |" in aus
    assert "| modified_since URL-kodiert | Parameter abgelehnt (HTTP 404) |" in aus
    assert "2025: 25 (Gesamtzahl fehlt); 2026: 25 (Gesamtzahl fehlt)" in aus and "None" not in aus
    assert "| mainFile | 0 | 50 | 0 % |" in aus and "| auxiliaryFile | 50 | 50 | 100 % |" in aus


@pytest.mark.parametrize("code, ergebnis, anfragen", [
    (400, "ok", 10), (401, "ok", 10), (404, "ok", 10),
    (403, "abbruch (http)", 10), (429, "abbruch (server)", 10), (500, "abbruch (server)", 10),
    (502, "abbruch (sperre)", 10)])
def test_parametertests_abgelehnt_oder_abbruch(koeln_server, tmp_path, code, ergebnis, anfragen):
    """Parametertest `limit=100` (10., letzte Anfrage) mit Fehlantwort: 400, 401 und 404 gelten als „Parameter
    abgelehnt“, die Messung endet regulär; jede andere Fehlantwort bricht nach dieser Anfrage ab (keine
    Wiederholung)."""
    koeln_server.stoerung = lambda pfad, abfrage: code if abfrage == "limit=100" else None
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10)
    assert m["lauf"]["ergebnis"] == ergebnis and m["server"] == anfragen == int(m["lauf"]["netz"]), m["stderr"]
    assert [s for _, q, _, s in koeln_server.anfragen if q == "limit=100"] == [code]
    werte = {z["feld"]: z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv") if z["objekt"] == "paper"}
    if ergebnis == "ok":
        assert m["rc"] == 0 and werte["test limit=100"] == f"Parameter abgelehnt (HTTP {code})"
    else:
        assert m["rc"] == 2 and koeln_server.anfragen[-1][1] == "limit=100"


def _stufe_2_befehl():
    """Umgebung und Argumente des Befehls aus STUFEN.md, Stufe 2."""
    text = (EXPLORE / "STUFEN.md").read_text(encoding="utf-8")
    zeile = next(z for z in text.splitlines() if z.startswith("RATSATLAS_") and "RATSATLAS_STUFE=2 " in z)
    werte = {k: v.strip('"') for k, v in re.findall(r'(RATSATLAS_[A-Z_]+)=("[^"]*"|\S+)', zeile)}
    return werte, zeile.split("explore/oparl_messung.py", 1)[1].split()


def _scheinzeit(ordner, uhrzeit):
    """PYTHONTZPATH für Teilprozesse: eine per zic erzeugte Zone Europe/Berlin mit festem Abstand zu UTC, so dass es
    jetzt `uhrzeit` (hh:mm:00) Ortszeit ist (keine Änderung der Systemzeit). Ohne zic: Test übersprungen."""
    zic = shutil.which("zic")
    if not zic:
        pytest.skip("zic fehlt")
    jetzt = dt.datetime.now(dt.timezone.utc)
    h, m = (int(x) for x in uhrzeit.split(":"))
    ab = (h * 3600 + m * 60 - (jetzt.hour * 3600 + jetzt.minute * 60 + jetzt.second)) % 86400
    ab = ab - 86400 if ab > 43200 else ab
    zeichen, ab = ("-", -ab) if ab < 0 else ("", ab)
    ordner.mkdir(parents=True)
    (ordner / "quelle").write_text(f"Zone\tEurope/Berlin\t{zeichen}{ab // 3600}:{ab % 3600 // 60:02d}:{ab % 60:02d}"
                                   "\t-\tSCHEIN\n", encoding="utf-8")
    subprocess.run([zic, "-d", str(ordner / "tz"), str(ordner / "quelle")], check=True, capture_output=True, timeout=60)
    return str(ordner / "tz")


def _stufe_2_wie_im_plan(stadt, ordner, uhrzeit):
    """Startet die Zeile aus STUFEN.md, Stufe 2, unverändert in bash im Wurzelverzeichnis des Repositorys; von außen
    gesetzt sind nur die Adressen des Testservers (wie die Stadt behandelt), Cache, Ergebnisse, Sperre und HOME in
    `ordner` sowie die Scheinzeit (PYTHONTZPATH). `python3` ist der Interpreter der Tests."""
    zeile = next(z for z in (EXPLORE / "STUFEN.md").read_text(encoding="utf-8").splitlines()
                 if z.startswith("RATSATLAS_") and "RATSATLAS_STUFE=2 " in z)
    (ordner / "bin").mkdir(parents=True, exist_ok=True)
    if not (ordner / "bin" / "python3").exists():
        (ordner / "bin" / "python3").symlink_to(sys.executable)
    keine = ",".join(x for x in (os.environ.get("NO_PROXY", ""), "127.0.0.1,127.0.0.2,localhost") if x)
    env = {k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_")}
    env.update({"RATSATLAS_OPARL_SYSTEM": stadt.system_url, "RATSATLAS_OPARL_BODY": stadt.body_url,
                "RATSATLAS_CACHE": str(ordner / "cache"), "RATSATLAS_ERGEBNISSE": str(ordner / "ergebnisse"),
                "RATSATLAS_SPERRE": str(ordner / "sperre"), "HOME": str(ordner / "home"),
                "PYTHONTZPATH": _scheinzeit(ordner / "zone", uhrzeit),
                "PATH": f"{ordner / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}", "NO_PROXY": keine, "no_proxy": keine})
    return subprocess.Popen(["bash", "-c", zeile], cwd=str(EXPLORE.parent), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def test_probelauf_stufe_2_wie_die_stadt_mit_scheinzeit(tmp_path, monkeypatch):
    """Genau die Zeile aus STUFEN.md, Stufe 2, gegen Testserver in Kölner Form auf 127.0.0.2 (gilt nicht als lokal: Freigabe,
    strenge Vorgaben, Abstand 2 s, Zeitfenster 23–1 Uhr ohne RATSATLAS_ZEITFENSTER) mit Scheinzeit 23:05 Uhr: (i) mit
    einem Cache wie nach Stufe 1 (System, Body, erste Vorlagenseite) 7 Anfragen ans Netz, (ii) ohne Cache 10, in der
    Reihenfolge des Plans, limit=100 zuletzt; Abstände mindestens 2 s, keine Wiederholung. Filterurteil modified_since:
    Server wendet an → „ja“ (mit und ohne Cache), übergeht → „nein (…; frühestes modified … vor der Grenze)“, übergeht,
    nachdem alle Vorlagen seit dem Cache geändert wurden → „nicht unterscheidbar (gleiche Kennungen wie ohne Filter)“.
    Um 22:59 und 01:00 Uhr keine Anfrage."""
    werte, argumente = _stufe_2_befehl()
    assert argumente == ["kennzahlen"] and werte["RATSATLAS_MAX_ANFRAGEN"] == "10"
    assert "RATSATLAS_ABSTAND" not in werte and "RATSATLAS_ZEITFENSTER" not in werte
    laeufe = {}
    # Name → (Cache wie nach Stufe 1, modified_since übergangen, alle Vorlagen nach dem Cache geändert, Urteil)
    faelle = {"mit": (True, False, False, "ja"), "ohne": (False, False, False, "ja"),
              "uebergeht": (True, True, False, "nein ("),
              "geaendert": (True, True, True, "nicht unterscheidbar (gleiche Kennungen wie ohne Filter)")}
    with contextlib.ExitStack() as stapel:
        for name, (mit_cache, uebergeht, aendern, _) in faelle.items():
            server = stapel.enter_context(testserver.Testserver(host="127.0.0.2", form="koeln"))
            if mit_cache:   # Cache wie nach Stufe 1: System, Body, erste Seite der Vorlagen
                _cache_wie_nach_stufe_1(monkeypatch, server, tmp_path / name / "cache")
            if aendern:
                _alle_vorlagen_aendern(server)
            server.ohne_modified_filter = uebergeht
            laeufe[name] = (server, time.monotonic(), _stufe_2_wie_im_plan(server, tmp_path / name, "23:05"))
        for name, (server, start, p) in laeufe.items():
            _, fehler = p.communicate(timeout=120)
            assert p.returncode == 0, fehler
            zeile = tsv(tmp_path / name / "ergebnisse" / "oparl_laeufe.tsv")[-1]
            netz, cache = (7, 3) if faelle[name][0] else (10, 0)
            assert (len(server.anfragen), zeile["netz"], zeile["cache"], zeile["stufe"]) == (netz, str(netz), str(cache),
                                                                                         "2"), name
            assert "T23:0" in zeile["start"] and zeile["ergebnis"] == "ok"                  # Scheinzeit
            reihenfolge = [pf.rsplit("/", 1)[1] + (f"?{q.split('=')[0]}" if q else "") for pf, q, *_ in server.anfragen]
            erwartet = ["meetings", "organizations", "people", "papers?modified_since", "papers?created_since",
                        "papers?modified_since", "papers?limit"]
            assert reihenfolge == (erwartet if faelle[name][0] else ["system", "testkoerperschaft", "papers"] + erwartet)
            kodiert = [q for pf, q, *_ in server.anfragen if "%" in q]
            assert len(kodiert) == 1 and [s for pf, q, _, s in server.anfragen if q == kodiert[0]] == [404]
            assert sorted(s for *_, s in server.anfragen) == [200] * (netz - 1) + [404]
            assert len({(pf, q) for pf, q, *_ in server.anfragen}) == netz    # keine Wiederholung
            assert server.eingang[0] - start >= 2.0
            assert min(b - a for a, b in zip(server.ausgang, server.eingang[1:])) >= 2.0, name
            werte_tsv = {(z["objekt"], z["feld"]): z["wert"]
                         for z in tsv(tmp_path / name / "ergebnisse" / "oparl_kennzahlen.tsv")}
            assert werte_tsv[("paper", "test modified_since URL-kodiert")] == "Parameter abgelehnt (HTTP 404)"
            assert werte_tsv[("paper", "pagination.totalElements")] == "fehlt"
            grenze = werte_tsv[("paper", "grenze modified_since")].split(" ")[0]
            assert urllib.parse.unquote(kodiert[0]) == f"modified_since={grenze}"     # dieselbe Grenze
            urteil = werte_tsv[("paper", f"test modified_since={grenze}")].split("filter_wirksam=", 1)[1]
            assert urteil.startswith(faelle[name][3]) and ("frühestes modified" in urteil) == (name == "uebergeht"), (
                name, urteil)
    # außerhalb des Zeitfensters: keine Anfrage, kein Protokoll
    with testserver.Testserver(host="127.0.0.2", form="koeln") as stadt:
        for uhrzeit in ("22:59", "01:00"):
            ordner = tmp_path / f"um_{uhrzeit.replace(':', '')}"
            _, fehler = (p := _stufe_2_wie_im_plan(stadt, ordner, uhrzeit)).communicate(timeout=60)
            assert p.returncode == 1 and "außerhalb des Zeitfensters 23-1 Uhr" in fehler, (uhrzeit, fehler)
            assert stadt.anfragen == [] and not (ordner / "cache" / "abrufe.tsv").exists()


# --- Runde 10: Zeitfilter ohne weitere Anfrage beurteilt, Reihenfolge (limit zuletzt), zwei 401, Antworten ohne JSON,
# Tropf-Antwort und Unterbrechung während einer Anfrage, Signale ----------------------------------------------------------

@pytest.mark.parametrize("uebergeht, urteil", [(False, "ja"), (True, "nein")])
def test_zeitfilter_angewandt_oder_uebergangen(koeln_server, tmp_path, uebergeht, urteil):
    """Kölner Form (neueste zuerst, jüngste Vorlagen kürzlich geändert): Ein Server, der modified_since bzw. created_*
    anwendet, ergibt „ja“, einer, der sie übergeht, „nein“ (mit fester Grenze vor 7 Tagen hieße es fälschlich „ja“);
    created_since ist bei neueste zuerst nicht unterscheidbar. Die Grenze kommt aus der ungefilterten ersten Seite."""
    koeln_server.ohne_modified_filter = koeln_server.ohne_created_filter = uebergeht
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10)
    assert m["rc"] == 0 and m["server"] == 10, m["stderr"]
    werte = {z["feld"]: z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv") if z["objekt"] == "paper"}
    grenze, herkunft = werte["grenze modified_since"].split(" ", 1)
    assert grenze.endswith("+00:00") and "Median von modified der ersten 13 Vorlagen" in herkunft
    assert f"filter_wirksam={urteil}" in werte[f"test modified_since={grenze}"]
    created = next(w for f, w in werte.items() if f.startswith("test created_since="))
    assert f"created_until wirkt: {urteil}" in created and "created_since wirkt: nicht unterscheidbar" in created
    abfragen = [q for pf, q, *_ in koeln_server.anfragen if pf.endswith("/papers") and q]
    assert [q.split("=")[0] for q in abfragen] == ["modified_since", "created_since", "modified_since", "limit"]
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert f"created_until wirkt: {urteil}" in aus and "created_since wirkt: nicht unterscheidbar" in aus
    assert "„nicht unterscheidbar“: Die erste Seite zeigt nicht" in aus and f"Grenze modified_since: {grenze}" in aus


def test_filter_urteil_ohne_weitere_anfrage():
    om = importlib.import_module("oparl_messung")
    t0 = dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc)

    def vorlage(kennung, erstellt, geaendert):
        return {"id": kennung, "created": erstellt.isoformat(), "modified": geaendert.isoformat()}
    basis = [vorlage(f"p{n}", t0 - dt.timedelta(days=n), t0 - dt.timedelta(hours=n)) for n in range(10)]
    seit, _ = om._grenze_modified(basis)                                 # Median der ersten fünf: p2
    grenze = om._zeitpunkt(seit)
    assert seit == "2026-11-06T10:00:00+00:00"
    urteil = lambda antwort: om._filter_urteil(basis, antwort, "modified", von=grenze)["von"]   # noqa: E731
    assert urteil(basis).startswith("nein (7 von 10 vor der Grenze")    # alle Änderungen jünger als 7 Tage
    assert urteil(basis[:3]) == "ja"
    # acht neue Vorlagen seit der ungefilterten Seite: Ein Server ohne Filter zeigte sie und p0, p1 → nicht unterscheidbar
    neue = [vorlage(f"n{n}", t0 + dt.timedelta(hours=n + 1), t0 + dt.timedelta(hours=n + 1)) for n in range(8)]
    assert urteil(neue + basis[:2]).startswith("nicht unterscheidbar (8 Kennungen nicht auf der ungefilterten Seite")
    # ältere, kürzlich geänderte Vorlagen verdrängen nichts von der ersten Seite → ja
    alt = [vorlage(f"a{n}", t0 - dt.timedelta(days=100 + n), t0) for n in range(8)]
    assert urteil(basis[:3] + alt) == "ja"
    assert urteil([]) == "keine Objekte"
    # alle modified gleich: nicht unterscheidbar, mit Vergleich der Kennungen
    gleich = [dict(o, modified=t0.isoformat()) for o in basis]
    seit, _ = om._grenze_modified(gleich)
    assert om._filter_urteil(gleich, gleich, "modified", von=om._zeitpunkt(seit))["von"] == (
        "nicht unterscheidbar (gleiche Kennungen wie ohne Filter)")
    # created_since/created_until bei neueste zuerst
    jahr = {"von": om._zeitpunkt("2025-01-01T00:00:00+01:00"), "bis": om._zeitpunkt("2025-12-31T23:59:59+01:00")}
    j2025 = [vorlage(f"j{n}", dt.datetime(2025, 12, 20 - n, tzinfo=dt.timezone.utc), t0) for n in range(5)]
    u = om._filter_urteil(basis, j2025, "created", **jahr)
    assert u["bis"] == "ja" and u["von"].startswith("nicht unterscheidbar (5 Kennungen")
    assert "neueste zuerst: die erste Seite zeigt nur die jüngsten Vorlagen" in u["von"]
    u = om._filter_urteil(basis, basis, "created", **jahr)              # Filter übergangen
    assert u["bis"].startswith("nein (10 von 10 nach der Grenze") and u["von"].startswith("nicht unterscheidbar")
    j2024 = [vorlage("x", dt.datetime(2024, 5, 1, tzinfo=dt.timezone.utc), t0)]
    assert om._filter_urteil(basis, j2025 + j2024, "created", **jahr)["von"].startswith("nein (1 von 6 vor der Grenze")


@pytest.mark.parametrize("stoerung, ergebnis, anfragen", [
    (lambda q: q.startswith("created_since") or "%" in q, "abbruch (http)", 9),     # 8. und 9. Anfrage: zwei in Folge
    (lambda q: q.startswith("modified_since"), "ok", 10)])                           # 7. und 9.: nicht in Folge
def test_zwei_401_in_folge_brechen_ab(koeln_server, tmp_path, stoerung, ergebnis, anfragen):
    koeln_server.stoerung = lambda pfad, abfrage: 401 if stoerung(abfrage) else None
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10)
    assert (m["lauf"]["ergebnis"], m["server"]) == (ergebnis, anfragen), m["stderr"]
    werte = {z["feld"]: z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv") if z["objekt"] == "paper"}
    assert sum(w == "Parameter abgelehnt (HTTP 401)" for w in werte.values()) == (1 if ergebnis != "ok" else 2)
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert "Status 401 × 2 (abgelehnt oder Sperre?)" in aus and "Parameter abgelehnt (HTTP 401) – abgelehnt oder Sperre?" in aus
    if ergebnis != "ok":
        assert m["rc"] == 2 and "zweimal HTTP 401 in Folge (abgelehnt oder Sperre?)" in m["lauf"]["meldung"]


def test_antwort_ohne_json_bleibt_nicht_im_cache(koeln_server, tmp_path, monkeypatch):
    """Parametertest und Folgeseite einer Liste mit HTML statt JSON (Status 200): Fehler, die Antwort wird aus dem Cache
    entfernt (ein späterer Lauf fragt erneut), gültige Antworten bleiben."""
    koeln_server.stoerung = lambda pfad, abfrage: 200 if abfrage == "limit=100" else None
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10)
    assert m["rc"] == 1 and m["lauf"]["ergebnis"].startswith("fehler (JSONDecodeError"), m["stderr"]
    abruf = importlib.import_module("abruf")
    monkeypatch.setattr(abruf, "CACHE", tmp_path / "cache")
    assert not abruf._cachepfad(f"{koeln_server.body_url}/papers?limit=100", ".json").exists()
    assert abruf._cachepfad(f"{koeln_server.body_url}/papers", ".json").exists()
    om = importlib.import_module("oparl_messung")
    abruf = _abruf_im_prozess(monkeypatch, tmp_path / "liste")
    monkeypatch.setattr(om, "_LISTEN", [])
    koeln_server.stoerung = lambda pfad, abfrage: 200 if abfrage == "page=2" else None
    url = f"{koeln_server.body_url}/organizations"
    with pytest.raises(ValueError):
        list(om._seiten(url, 3, name="organization"))
    assert abruf._cachepfad(url, ".json").exists() and not abruf._cachepfad(f"{url}?page=2", ".json").exists()


def test_limit_zuletzt_langsame_antwort_nach_allen_messungen(koeln_server, tmp_path):
    """limit=100 ist die letzte Anfrage: Ist die Antwort zu langsam, bricht der Lauf ab („langsam“), wenn alle übrigen
    Messungen vorliegen; die Zahl der Objekte steht aus der gespeicherten Antwort im Ergebnis."""
    koeln_server.verzoegerung = lambda pfad, abfrage: 0.6 if abfrage == "limit=100" else 0
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10, RATSATLAS_MAX_DAUER="0.4")
    assert (m["rc"], m["lauf"]["ergebnis"], m["server"]) == (2, "abbruch (langsam)", 10), m["stderr"]
    assert koeln_server.anfragen[-1][1] == "limit=100"
    werte = {(z["objekt"], z["feld"]): z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv")}
    assert werte[("paper", "test limit=100")].startswith("objekte=25; Antwortzeit")
    assert ("person", "links.next") in werte and werte[("paper", "test modified_since URL-kodiert")].startswith("Parameter")
    assert any(f.startswith("test created_since=") for _, f in werte)


@pytest.fixture
def tropf_server():
    """Fabrik für lokale HTTP-Server auf 127.0.0.1: Kopf mit Content-Length, dann der Inhalt in `teile` mit `pause`
    Sekunden vor jedem Teil (verzögerte oder tropfende Antwort)."""
    gestartet = []

    def starten(teile, pause):
        inhalt = b"".join(teile)

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                daten = b""
                while b"\r\n\r\n" not in daten:
                    teil = self.request.recv(4096)
                    if not teil:
                        return
                    daten += teil
                self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
                                     b"Connection: close\r\n\r\n" % len(inhalt))
                for teil in teile:
                    time.sleep(pause)
                    try:
                        self.request.sendall(teil)
                    except OSError:
                        return

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        server.daemon_threads, server.url = True, f"http://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        gestartet.append(server)
        return server

    yield starten
    for server in gestartet:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("teile, art, status", [(3, "langsam", "200"), (12, "sperre", "Gesamtfrist")])
def test_verzoegerte_und_tropfende_antwort(tmp_path, monkeypatch, tropf_server, teile, art, status):
    """Inhalt in Blöcken gelesen: vollständig, aber über RATSATLAS_MAX_DAUER → „langsam“ (gespeichert); länger als die
    Gesamtfrist (hier 1 s statt 60 s) → Art `sperre`, Status `Gesamtfrist`, nichts im Cache, Abbruch ohne das Ende
    abzuwarten."""
    server = tropf_server([b'{"a": 1'] + [b" "] * (teile - 2) + [b"}"], 0.2)
    abruf = _abruf_im_prozess(monkeypatch, tmp_path, GESAMTFRIST=1.0, MAX_DAUER=0.3)
    url = f"{server.url}/oparl/system"
    start = time.monotonic()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(url, ".json")
    assert e.value.art == art and ("Tropf-Antwort" in str(e.value)) == (art == "sperre")
    assert time.monotonic() - start < 2.0                                # nicht bis zum Ende der Tropf-Antwort
    z = tsv(tmp_path / "abrufe.tsv")[-1]
    assert (z["status"], z["quelle"]) == (status, "netz")
    assert abruf._cachepfad(url, ".json").exists() == (art == "langsam")


def test_sigterm_waehrend_einer_anfrage_ist_moegliche_sperre(tmp_path):
    """SIGTERM, während die Antwort aussteht (etwa Zeitlimit des aufrufenden Werkzeugs bei hängender Anfrage): Die
    Anfrage steht mit Status `unterbrochen` im Protokoll (Auswertung: Netz 1, mögliche Sperre), der Lauf mit
    „unterbrochen während einer Anfrage“."""
    with testserver.Testserver(host="127.0.0.2") as stadt:
        stadt.verzoegerung = 3.0
        env = _wie_die_stadt(stadt, tmp_path, RATSATLAS_STUFE="1", RATSATLAS_MAX_ANFRAGEN="3")
        p = subprocess.Popen([sys.executable, str(EXPLORE / "oparl_messung.py"), "test"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        frist = time.monotonic() + 30
        while not stadt.eingang and time.monotonic() < frist and p.poll() is None:
            time.sleep(0.02)
        time.sleep(0.3)                                                    # die Antwort steht noch aus
        p.send_signal(signal.SIGTERM)
        _, fehler = p.communicate(timeout=30)
    assert p.returncode == 143 and "Unterbrochen (SIGTERM) während einer Anfrage: mögliche Sperre" in fehler, fehler
    zeile = tsv(tmp_path / "ergebnisse" / "oparl_laeufe.tsv")[-1]
    assert (zeile["ergebnis"], zeile["netz"]) == ("unterbrochen", "1")
    assert zeile["meldung"].startswith("unterbrochen während einer Anfrage (SIGTERM): mögliche Sperre, stoppen")
    z = protokoll(tmp_path)[-1]
    assert (z["status"], z["quelle"]) == ("unterbrochen", "netz") and z["url"] == stadt.system_url
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert "| 1 | test | 1 | 0 | unterbrochen×1 |" in aus
    assert "Status unterbrochen × 1 (Lauf während dieser Anfrage unterbrochen" in aus and "mögliche Sperre" in aus


SIGHUP_SKRIPT = """
import os, signal, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
signal.signal(signal.SIGHUP, signal.SIG_IGN if sys.argv[3] == "ignoriert" else signal.SIG_DFL)
import oparl_messung as om
om.ERG, om.SYSTEM, om.BODY = Path(sys.argv[2]), "http://127.0.0.1:9/oparl/system", "http://127.0.0.1:9/oparl/bodies/x"
def kommando(_a):
    os.kill(os.getpid(), signal.SIGHUP)
    time.sleep(2)
om.KOMMANDOS["test"] = kommando
sys.exit(om.main(["test"]))
"""


@pytest.mark.parametrize("vorher, rueckgabe, ergebnis", [("vorgabe", 129, "unterbrochen"), ("ignoriert", 0, "ok")])
def test_sighup_wie_strg_c_ausser_mit_nohup(tmp_path, vorher, rueckgabe, ergebnis):
    """SIGHUP endet wie Strg+C (Vermerk, 12-Stunden-Regel), außer es ist ignoriert wie mit nohup: dann bleibt es
    ignoriert und der Lauf geht weiter (als eigener Prozess, damit ein nicht behandeltes SIGHUP nicht die Tests
    beendet)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_")}
    env.update({"RATSATLAS_CACHE": str(tmp_path / "cache"), "RATSATLAS_SPERRE": str(tmp_path / "sperre")})
    r = subprocess.run([sys.executable, "-c", SIGHUP_SKRIPT, str(EXPLORE), str(tmp_path / "erg"), vorher], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == rueckgabe, r.stderr
    zeile = tsv(tmp_path / "erg" / "oparl_laeufe.tsv")[-1]
    assert zeile["ergebnis"] == ergebnis and (zeile["meldung"] == "unterbrochen (SIGHUP)") == (ergebnis != "ok")


def _main_mit_wache(om, monkeypatch, tmp_path, kommando):
    """om.main(["test"]) mit Ersatzkommando und einer Wache für SIGTERM (falls main() es nicht behandelt); ein Signal
    oder KeyboardInterrupt, das main() verlässt, lässt den Test scheitern (statt die Testsitzung zu beenden)."""
    class Wache(Exception):
        pass

    def wache(nummer, _rahmen):
        raise Wache(nummer)
    if signal.getsignal(signal.SIGINT) is not signal.default_int_handler:
        pytest.skip("SIGINT ist in dieser Testumgebung nicht die Vorgabe von Python")
    alt = signal.signal(signal.SIGTERM, wache)
    try:
        monkeypatch.setitem(om.KOMMANDOS, "test", kommando)
        for name, wert in (("ERG", tmp_path / "erg"), ("SYSTEM", "http://127.0.0.1:9/oparl/system"),
                           ("BODY", "http://127.0.0.1:9/oparl/bodies/x"), ("_LISTEN", [])):
            monkeypatch.setattr(om, name, wert)
        monkeypatch.setattr(om.abruf, "PROTOKOLL", tmp_path / "abrufe.tsv")
        try:
            return om.main(["test"])
        except (KeyboardInterrupt, Wache) as e:
            pytest.fail(f"Signal hat main() verlassen: {e!r}")
    finally:
        signal.signal(signal.SIGTERM, alt)
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_zwei_signale_kurz_nacheinander(tmp_path, monkeypatch):
    """Zwei Signale gleichzeitig ausstehend (SIGINT und SIGTERM): Das erste beendet den Lauf wie Strg+C, das zweite wird
    ignoriert und unterbricht den Vermerk nicht."""
    om = importlib.import_module("oparl_messung")
    # Die Signale gehen gezielt an den Hauptthread (pthread_kill), nicht an den Prozess (os.kill): Ein an den Prozess
    # gerichtetes Signal stellt der Kernel einem anderen laufenden Thread zu, wenn der Hauptthread es blockiert; Python
    # behandelt es dann schon vor dem zweiten Signal (in CI so aufgetreten, Rückgabewert 143). Der rechnende Nebenthread
    # stellt genau diese Lage her; an den Hauptthread gerichtete Signale bleiben dort ausstehend und werden nach der
    # Freigabe in aufsteigender Nummer behandelt (SIGINT vor SIGTERM).
    halt = threading.Event()

    def rechnen():
        while not halt.is_set():
            sum(range(1000))
    neben = threading.Thread(target=rechnen, daemon=True)
    neben.start()

    def kommando(_a):
        beide = {signal.SIGINT, signal.SIGTERM}
        haupt = threading.get_ident()
        signal.pthread_sigmask(signal.SIG_BLOCK, beide)
        signal.pthread_kill(haupt, signal.SIGTERM)
        signal.pthread_kill(haupt, signal.SIGINT)
        signal.pthread_sigmask(signal.SIG_UNBLOCK, beide)                 # beide zugleich zugestellt
        time.sleep(5)
    try:
        assert _main_mit_wache(om, monkeypatch, tmp_path, kommando) == 130
    finally:
        halt.set()
        neben.join(5)
    zeilen = tsv(tmp_path / "erg" / "oparl_laeufe.tsv")
    assert len(zeilen) == 1 and (zeilen[0]["ergebnis"], zeilen[0]["meldung"]) == ("unterbrochen", "unterbrochen (SIGINT)")


def test_signal_waehrend_des_vermerks_wird_ignoriert(tmp_path, monkeypatch):
    """Ein Signal, während main() den Vermerk schreibt (finally), wird ignoriert: Der Vermerk steht vollständig."""
    om = importlib.import_module("oparl_messung")
    echt = om._anhaengen

    def anhaengen(*a, **k):
        os.kill(os.getpid(), signal.SIGTERM)
        return echt(*a, **k)
    monkeypatch.setattr(om, "_anhaengen", anhaengen)
    assert _main_mit_wache(om, monkeypatch, tmp_path, lambda _a: None) == 0
    assert tsv(tmp_path / "erg" / "oparl_laeufe.tsv")[-1]["ergebnis"] == "ok"


def test_lauf_ohne_regulaeres_ende_gilt_als_unterbrochen(tmp_path, monkeypatch):
    """Schlechter Fall zuerst: Endet ein Lauf durch eine Ausnahme, die main() nicht behandelt (hier SystemExit im
    Kommando), steht „unterbrochen“ im Vermerk (12-Stunden-Regel), nicht „ok“."""
    om = importlib.import_module("oparl_messung")
    with pytest.raises(SystemExit):
        _main_mit_wache(om, monkeypatch, tmp_path, lambda _a: sys.exit("Test"))
    datei = tmp_path / "erg" / "oparl_laeufe.tsv"
    assert (tsv(datei)[-1]["ergebnis"], tsv(datei)[-1]["meldung"]) == ("unterbrochen", "nicht regulär beendet")
    assert om.letzter_abbruch(datei) is not None


# --- Runde 11: „ja“ nur, wenn eine Vorlage unter der Grenze fehlt; Abstand bei „nein“; Gesamtfrist nach dem Lesen und
# Wächter; Markerdatei gegen harte Beendigung -----------------------------------------------------------------------------

def test_filter_urteil_nach_aenderung_aller_vorlagen_und_abstand_bei_nein():
    """modified kann sich seit der ungefilterten Seite geändert haben: Sind alle Vorlagen seither geändert, liefert ein
    Server, der modified_since übergeht, dieselben Kennungen mit jüngerem modified → „nicht unterscheidbar“ (vorher
    fälschlich „ja“); ebenso ein Server, der ihn anwendet. „ja“ nur, wenn eine Vorlage fehlt, die laut ungefilterter Seite
    unter der Grenze lag. Bei „nein“ steht, wie weit die äußerste Vorlage jenseits der Grenze liegt."""
    om = importlib.import_module("oparl_messung")
    t0 = dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc)

    def vorlage(kennung, erstellt, geaendert):
        return {"id": kennung, "created": erstellt.isoformat(), "modified": geaendert.isoformat()}
    basis = [vorlage(f"p{n}", t0 - dt.timedelta(days=n), t0 - dt.timedelta(hours=n)) for n in range(10)]
    grenze = om._zeitpunkt(om._grenze_modified(basis)[0])                  # t0 − 2 h
    urteil = lambda antwort: om._filter_urteil(basis, antwort, "modified", von=grenze)["von"]   # noqa: E731
    geaendert = [dict(o, modified=(t0 + dt.timedelta(hours=1)).isoformat()) for o in basis]
    assert urteil(geaendert) == "nicht unterscheidbar (gleiche Kennungen wie ohne Filter)"   # übergangen
    assert urteil(geaendert[:3] + geaendert[5:]) == "ja"                   # p3, p4 lagen unter der Grenze und fehlen
    assert urteil(basis[:3]) == "ja"                                       # angewandt, nichts geändert
    # übergangen: frühestes modified 7 h vor der Grenze; Versatz von 1 h (etwa „+“ als Leerzeichen: Ortszeit)
    assert urteil(basis) == "nein (7 von 10 vor der Grenze; frühestes modified 7 h vor der Grenze)"
    versatz = basis[:3] + [dict(basis[3], modified=(grenze - dt.timedelta(minutes=59)).isoformat())]
    assert urteil(versatz) == "nein (1 von 4 vor der Grenze; frühestes modified 59 min vor der Grenze)"
    jahr = {"von": om._zeitpunkt("2025-01-01T00:00:00+01:00"), "bis": om._zeitpunkt("2025-12-31T23:59:59+01:00")}
    u = om._filter_urteil(basis, basis, "created", **jahr)
    assert u["bis"] == "nein (10 von 10 nach der Grenze; spätestes created 309,5 Tage nach der Grenze)"
    for sekunden, text in ((30, "30 s"), (300, "5 min"), (3600, "1 h"), (5400, "1 h 30 min"), (86340, "23 h 59 min"),
                           (2 * 86400, "2,0 Tage"), (-3600, "1 h")):
        assert om._dauer_text(dt.timedelta(seconds=sekunden)) == text


def _cache_wie_nach_stufe_1(monkeypatch, server, cache):
    """Cache wie nach Stufe 1: System, Body und erste Vorlagenseite des Servers in `cache`."""
    abruf = importlib.import_module("abruf")
    monkeypatch.setattr(abruf, "CACHE", cache)
    for url in (server.system_url, server.body_url, f"{server.body_url}/papers"):
        pfad = abruf._cachepfad(url, ".json")
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_bytes(server.antwort(url[len(server.basis):], "")[2])


def _alle_vorlagen_aendern(server):
    """Alle Vorlagen des Testservers jetzt geändert (nach dem Cache von Stufe 1)."""
    jetzt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    for o in server.daten.vorlagen:
        o["modified"], o["_m"] = jetzt.isoformat(), jetzt


@pytest.mark.parametrize("uebergeht", [True, False])
def test_modified_since_nach_aenderung_aller_vorlagen_nicht_unterscheidbar(koeln_server, tmp_path, monkeypatch,
                                                                         uebergeht):
    """kennzahlen mit dem Cache aus Stufe 1 (7 Anfragen), danach alle Vorlagen geändert: Ob der Server modified_since
    übergeht oder anwendet, ist nicht unterscheidbar (gleiche Kennungen); kein „ja“, auf das sich der inkrementelle Abruf
    stützen würde."""
    _cache_wie_nach_stufe_1(monkeypatch, koeln_server, tmp_path / "cache")
    _alle_vorlagen_aendern(koeln_server)
    koeln_server.ohne_modified_filter = uebergeht
    m = lauf(koeln_server, tmp_path, "kennzahlen", obergrenze=10)
    assert m["rc"] == 0 and m["server"] == 7, m["stderr"]
    werte = {z["feld"]: z["wert"] for z in tsv(tmp_path / "ergebnisse" / "oparl_kennzahlen.tsv") if z["objekt"] == "paper"}
    grenze = werte["grenze modified_since"].split(" ")[0]
    assert werte[f"test modified_since={grenze}"].endswith(
        "filter_wirksam=nicht unterscheidbar (gleiche Kennungen wie ohne Filter)")
    aus = importlib.import_module("auswertung").auswertung(tmp_path / "cache", tmp_path / "ergebnisse")
    assert "etwa weil alle seither geändert wurden" in aus


@pytest.fixture
def kopf_server():
    """Fabrik für lokale HTTP-Server auf 127.0.0.1: `kopf` Sekunden vor dem Kopf warten, dann ein leerer Inhalt
    (Content-Length 0) oder, mit `ende`, eine chunked-Antwort, deren Abschluss erst nach `ende` Sekunden kommt."""
    gestartet = []

    def starten(kopf, ende=None):
        class H(socketserver.BaseRequestHandler):
            def handle(self):
                daten = b""
                while b"\r\n\r\n" not in daten:
                    teil = self.request.recv(4096)
                    if not teil:
                        return
                    daten += teil
                try:
                    time.sleep(kopf)
                    if ende is None:
                        self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 0"
                                             b"\r\nConnection: close\r\n\r\n")
                        return
                    self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: "
                                         b"chunked\r\nConnection: close\r\n\r\n2\r\n{}\r\n")
                    time.sleep(ende)
                    self.request.sendall(b"0\r\n\r\n")
                except OSError:
                    return

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        server.daemon_threads, server.url = True, f"http://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        gestartet.append(server)
        return server

    yield starten
    for server in gestartet:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("kopf, ende", [(1.3, None), (0, 1.3)])
def test_gesamtfrist_nach_dem_lesen_ohne_waechter(tmp_path, monkeypatch, kopf_server, kopf, ende):
    """Ohne Wächter (etwa außerhalb des Hauptthreads): leerer Inhalt nach langsamem Kopf bzw. später Abschluss einer
    chunked-Antwort, insgesamt über der Gesamtfrist (hier 1 s) → Art `sperre`, Status `Gesamtfrist`, nichts im Cache."""
    server = kopf_server(kopf, ende)
    abruf = _abruf_im_prozess(monkeypatch, tmp_path, GESAMTFRIST=1.0)
    monkeypatch.setattr(abruf, "_waechter_an", lambda: False)
    url = f"{server.url}/oparl/system"
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(url, ".json")
    assert e.value.art == "sperre" and "Gesamtfrist 1 s" in str(e.value)
    z = tsv(tmp_path / "abrufe.tsv")[-1]
    assert (z["status"], z["quelle"]) == ("Gesamtfrist", "netz") and not abruf._cachepfad(url, ".json").exists()


def test_waechter_beendet_haengenden_kopf(tmp_path, monkeypatch, kopf_server):
    """Wächter (SIGALRM, Hauptthread): Der Kopf kommt erst nach 3 s, die Gesamtfrist (hier 1 s) beendet das Warten nach
    etwa 1 s → Art `sperre`, Status `Gesamtfrist`, nichts im Cache; danach ist kein Zeitgeber mehr gesetzt. Eine schnelle
    Antwort danach bleibt unberührt."""
    server = kopf_server(3.0)
    abruf = _abruf_im_prozess(monkeypatch, tmp_path, GESAMTFRIST=1.0)
    url = f"{server.url}/oparl/system"
    start = time.monotonic()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.hole(url, ".json")
    assert time.monotonic() - start < 2.0 and e.value.art == "sperre" and "hängender Verbindungsaufbau" in str(e.value)
    z = tsv(tmp_path / "abrufe.tsv")[-1]
    assert (z["status"], z["quelle"]) == ("Gesamtfrist", "netz") and not abruf._cachepfad(url, ".json").exists()
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0) and not abruf._frist_aktiv
    schnell = kopf_server(0, 0.1)
    assert abruf.hole(f"{schnell.url}/a", ".json") == b"{}" and signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def _marker(om, ordner, **werte):
    ordner.mkdir(parents=True, exist_ok=True)
    pfad = ordner / om.MARKER
    pfad.write_text(json.dumps({"lauf": 2, "stufe": "2", "kommando": "kennzahlen", "parameter": "", "pid": 1, **werte}),
                    encoding="utf-8")
    return pfad


def test_markerdatei_ohne_vermerk_sperrt_12_stunden(tmp_path, capsys):
    """letzter_abbruch mit Markerdatei: jünger als 12 Stunden ohne Vermerk (hart beendet) oder unlesbar → „nicht regulär
    beendet“; älter → gemeldet und entfernt; ist der Lauf vermerkt, gilt der Vermerk (Marker entfernt)."""
    om = importlib.import_module("oparl_messung")
    erg, jetzt = tmp_path / "erg", dt.datetime(2026, 11, 8, 23, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    datei = erg / "oparl_laeufe.tsv"
    _laeufe(erg, (1, 1, "test", "", "2026-11-07T23:05:00+01:00", "2026-11-07T23:05:09+01:00", 9, 3, 0, 3, 0, 3, "ok", ""))
    pfad = _marker(om, tmp_path / "cache", start="2026-11-08T23:05:00+01:00")
    assert om.letzter_abbruch(datei, jetzt) is None                       # ohne `marker`: nur oparl_laeufe.tsv
    treffer = om.letzter_abbruch(datei, jetzt, pfad)
    assert (treffer["ergebnis"], treffer["lauf"], treffer["kommando"], treffer["marker"]) == (
        "nicht regulär beendet", 2, "kennzahlen", str(pfad)) and pfad.exists()
    pfad.write_text("{kaputt", encoding="utf-8")                           # unlesbar: vorsichtshalber gesperrt
    assert om.letzter_abbruch(datei, jetzt, pfad)["ergebnis"] == "nicht regulär beendet"
    pfad = _marker(om, tmp_path / "cache", start="2026-11-08T11:00:00+01:00")   # älter als 12 Stunden
    assert om.letzter_abbruch(datei, jetzt, pfad) is None and not pfad.exists()
    assert "Lauf 2 (kennzahlen, Stufe 2) vom 2026-11-08T11:00:00+01:00 wurde nicht regulär beendet" in capsys.readouterr().err
    # Lauf 2 ist vermerkt („ok“), der Marker blieb (Ende zwischen Vermerk und Entfernen): der Vermerk gilt
    _laeufe(erg, (1, 1, "test", "", "2026-11-07T23:05:00+01:00", "2026-11-07T23:05:09+01:00", 9, 3, 0, 3, 0, 3, "ok", ""),
            (2, 2, "kennzahlen", "", "2026-11-08T23:05:00+01:00", "2026-11-08T23:05:30+01:00", 30, 7, 3, 10, 3, 13, "ok",
             ""))
    pfad = _marker(om, tmp_path / "cache", start="2026-11-08T23:05:00+01:00")
    assert om.letzter_abbruch(datei, jetzt, pfad) is None and not pfad.exists()


def test_hart_beendeter_lauf_sperrt_den_naechsten(tmp_path):
    """Als Prozess gegen einen Testserver, der wie die Stadt behandelt wird (127.0.0.2): SIGKILL während der ersten
    Anfrage → kein Vermerk, die Markerdatei bleibt; der nächste Lauf schickt keine Anfrage (Rückgabewert 1, „nicht
    regulär beendet“). Mit RATSATLAS_NACH_ABBRUCH=ja läuft er und entfernt den Marker am Ende."""
    with testserver.Testserver(host="127.0.0.2") as stadt:
        stadt.verzoegerung = 3.0
        skript = str(EXPLORE / "oparl_messung.py")
        env = _wie_die_stadt(stadt, tmp_path, RATSATLAS_STUFE="1", RATSATLAS_MAX_ANFRAGEN="3")
        marker = tmp_path / "cache" / "lauf_offen.json"
        p = subprocess.Popen([sys.executable, skript, "test"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        frist = time.monotonic() + 30
        while not stadt.eingang and time.monotonic() < frist and p.poll() is None:
            time.sleep(0.02)
        inhalt = json.loads(marker.read_text(encoding="utf-8"))
        assert (inhalt["kommando"], inhalt["stufe"], inhalt["pid"]) == ("test", "1", p.pid)
        p.kill()                                                           # SIGKILL: kein Vermerk möglich
        p.communicate(timeout=30)
        assert p.returncode == -signal.SIGKILL and marker.exists()
        assert not (tmp_path / "ergebnisse" / "oparl_laeufe.tsv").exists()
        n = len(stadt.anfragen)
        zweiter = subprocess.run([sys.executable, skript, "test"], env=env, capture_output=True, text=True, timeout=60)
        assert zweiter.returncode == 1 and "nicht regulär beendet" in zweiter.stderr, zweiter.stderr
        assert "RATSATLAS_NACH_ABBRUCH" in zweiter.stderr and len(stadt.anfragen) == n and marker.exists()
        stadt.verzoegerung = 0.0
        dritter = subprocess.run([sys.executable, skript, "test"], env={**env, "RATSATLAS_NACH_ABBRUCH": "ja"},
                                 capture_output=True, text=True, timeout=120)
        assert dritter.returncode == 0, dritter.stderr
        assert not marker.exists() and tsv(tmp_path / "ergebnisse" / "oparl_laeufe.tsv")[-1]["ergebnis"] == "ok"
