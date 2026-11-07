"""Messstufen der Kölner OParl-API (explore/STUFEN.md) gegen den lokalen Testserver explore/testserver.py:
Anzahl der Anfragen je Kommando, Obergrenze RATSATLAS_MAX_ANFRAGEN (Abbruch statt Überschreitung), Cache-Treffer
zählen nicht, Folgeseiten ohne URL-Kodierung, Seitengrenzen, Abbruchkriterien, Probelauf und Auswertung.
Läuft offline: Anfragen gehen nur an 127.0.0.1; Adressen der Stadt werden nie aufgerufen."""
import csv
import datetime as dt
import importlib
import json
import re
import sys
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
    assert werte["test modified_since URL-kodiert"].startswith("HTTP 404")
    seit = next(f for f in werte if f.startswith("test modified_since=") and "+00:00" in f)
    assert "filter_wirksam=ja" in werte[seit]
    assert "filter_wirksam=ja" in next(w for f, w in werte.items() if f.startswith("test created_since="))
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
    assert fehler == [] and werte == {"wiederholungen": 0, "max_dauer": 5.0, "max_anfragen": 3}
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
    befehle = re.findall(r"RATSATLAS_MAX_ANFRAGEN=(\d+)[^\n`]*?oparl_messung\.py ([a-z-]+)([^\n`]*)", text)
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
