"""SessionNet-Adapter gegen den lokalen Testserver: Paginierung, inkrementeller Abruf, abgeleitete Beratungen,
Abrufstatistik, Sperre und Anschluss an build.py (Bonner Datenmodell)."""
import contextlib
import csv
import io
import json
import math
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipeline import abruf, build, config, sessionnet

# Öffner ohne Proxy für Tests gegen lokale Server (unabhängig von den Proxy-Variablen der Umgebung)
OHNE_PROXY = abruf.oeffner({})


def _jsonl(path):
    return [json.loads(z) for z in path.read_text(encoding="utf-8").splitlines() if z.strip()]


def _statistik():
    with open(config.ABRUFSTATISTIK, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_vollabruf_folgt_links_next_und_leitet_beratungen_ab(oparl):
    sessionnet.fetch_all()
    papers = _jsonl(config.PAPERS)
    assert len(papers) == 5                                   # drei Seiten zu je höchstens zwei Objekten
    assert all("page=" not in q.get("page", "") for _, q, _ in oparl.anfragen)
    beratungen = {b["uri"]: b for b in _jsonl(config.BERATUNGEN)}
    b1 = beratungen[f"{oparl.b}/consultations/1"]
    assert b1["meeting"]["startDate"] == "2026-10-01T17:00:00+02:00"
    assert b1["agendaItem"] == {"uri": f"{oparl.b}/agendaitems/1", "number": "8.1", "name": "TOP 1",
                                "result": "ungeändert beschlossen", "public": True}
    # Gremium fehlt in der Beratung → aus der Sitzung übernommen und als abgeleitet markiert
    c = papers[0]["consultation"][0]
    assert c["organization"] == [f"{oparl.b}/organizations/bv4"] and c["_organization_quelle"] == "sitzung"
    assert json.loads(config.LEGISLATIVE_TERMS.read_text())[0]["name"] == "2025–2030"
    stat = {z["liste"]: z for z in _statistik()}
    assert stat["papers"]["modus"] == "voll" and stat["papers"]["seiten"] == "3" and stat["papers"]["ergebnis"] == "ok"
    # eigene Zeile für den Abruf des Bodys; Spalten für Weiterleitungen und Proxy-Ablehnungen
    assert (stat["body"]["anfragen"], stat["body"]["objekte"], stat["body"]["ergebnis"]) == ("1", "1", "ok")
    assert all((z["weiterleitungen"], z["proxy"]) == ("0", "0") for z in stat.values())
    assert all(ua.startswith("ratsatlas-koeln/") for _, _, ua in oparl.anfragen)


def test_zweiter_lauf_ist_inkrementell_und_fuehrt_zusammen(oparl):
    sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    zeit = datetime.fromisoformat(zustand["papers"])
    # eine Vorlage wird geändert, eine kommt hinzu (Änderungszeitpunkt nach dem ersten Lauf)
    neu = (zeit.isoformat(timespec="seconds"))
    oparl.papers[1] = oparl.paper(2, name="Geänderter Titel", modified=neu)
    oparl.papers.append(oparl.paper(6, modified=neu))
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    gesendet = [q for p, q, _ in oparl.anfragen if p == "/papers"]
    assert gesendet and all("modified_since" in q for q in gesendet)
    papers = {p["id"]: p for p in _jsonl(config.PAPERS)}
    assert len(papers) == 6 and papers[f"{oparl.b}/papers/2"]["name"] == "Geänderter Titel"
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["neu"], z["geaendert"], z["filter_wirksam"]) == ("inkrementell", "1", "1", "ja")


def test_sperre_ohne_information_der_stadt(oparl, monkeypatch):
    monkeypatch.setattr(config, "OPARL_BODY", "https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
    with pytest.raises(abruf.Abbruch, match="nicht informiert"):
        abruf.get_json(config.OPARL_BODY)
    sessionnet.fetch_all()    # überspringt den Abruf, ohne ihn als Fehler zu vermerken
    stand = json.loads(config.STAND.read_text())
    assert "nicht informiert" in stand["abruf_uebersprungen"]["grund"] and "abruf_fehler" not in stand
    assert not config.PAPERS.exists() and oparl.anfragen == []


def test_ausserhalb_des_zeitfensters_wird_uebersprungen(oparl, monkeypatch):
    monkeypatch.setattr(config, "OPARL_BODY", "https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: False)
    sessionnet.fetch_all()
    stand = json.loads(config.STAND.read_text())
    assert "Zeitfenster" in stand["abruf_uebersprungen"]["grund"] and "abruf_fehler" not in stand


def test_abbruch_haelt_letzten_stand(oparl, monkeypatch):
    sessionnet.fetch_all()
    vorher = config.PAPERS.read_text()
    monkeypatch.setattr(config, "OPARL_BODY", f"{oparl.b}/gibt-es-nicht")
    sessionnet.fetch_all()
    assert config.PAPERS.read_text() == vorher
    assert "HTTP 404" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    assert "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())   # 404 ist kein Sperrsignal


def test_zeitfenster(monkeypatch):
    assert config.ABRUF_ZEITFENSTER == "23-1"     # laut mandari erlaubt die Stadt Abrufe nur 23–1 Uhr
    assert abruf.im_zeitfenster(datetime(2026, 11, 4, 23))
    assert abruf.im_zeitfenster(datetime(2026, 11, 5, 0, 59))
    assert not abruf.im_zeitfenster(datetime(2026, 11, 5, 1))
    assert not abruf.im_zeitfenster(datetime(2026, 11, 4, 22, 59))
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "22-6")
    assert abruf.im_zeitfenster(datetime(2026, 11, 4, 3))
    assert not abruf.im_zeitfenster(datetime(2026, 11, 4, 12))
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")
    assert abruf.im_zeitfenster(datetime(2026, 11, 4, 12))


def test_build_liest_kölner_rohdaten(oparl):
    sessionnet.fetch_all()
    build.build()
    db = sqlite3.connect(config.DB)
    one = lambda q: db.execute(q).fetchone()[0]
    assert one("SELECT COUNT(*) FROM paper") == 5
    assert one("SELECT COUNT(*) FROM consultation WHERE meeting_id IS NOT NULL AND agenda_item_id IS NOT NULL") == 5
    assert one("SELECT COUNT(*) FROM agenda_item WHERE result = 'ungeändert beschlossen'") == 3
    assert one("SELECT DISTINCT source FROM paper") == config.QUELLE_OPARL
    assert one("SELECT DISTINCT source FROM meeting") == config.QUELLE_SITZUNG
    # Stufe B aus dem Titel: „Venloer Straße“ mit Stadtteil „Ehrenfeld“ aus dem Kölner Straßenverzeichnis
    orte = db.execute("SELECT l.ortsteil, pl.method FROM paper_location pl JOIN location l ON l.id = pl.location_id "
                      "WHERE pl.paper_id LIKE '%/papers/1'").fetchall()
    assert ("Ehrenfeld", ) in [(o,) for o, _ in orte]
    # Stufe A: subLocality „Neuehrenfeld“ → Stadtteilfläche
    a = db.execute("SELECT l.level, l.ortsteil, pl.method, pl.confidence FROM paper_location pl JOIN location l "
                   "ON l.id = pl.location_id WHERE pl.paper_id LIKE '%/papers/3' AND pl.stage = 'A'").fetchall()
    assert a == [("ortsteil", "Neuehrenfeld", "oparl_sublocality", "mittel")]
    # schwache Evidenz: nur in der Bezirksvertretung 4 (Ehrenfeld) beraten, sonst kein Ortsbezug
    schwach = db.execute("SELECT pl.paper_id, l.stadtbezirk, pl.confidence FROM paper_location pl JOIN location l "
                         "ON l.id = pl.location_id WHERE pl.method = 'district_from_committee'").fetchall()
    assert {p.rsplit("/", 1)[1] for p, _, _ in schwach} == {"2", "4", "5"}
    assert {(b, c) for _, b, c in schwach} == {("Ehrenfeld", "niedrig")}


def test_export_koeln(oparl, monkeypatch):
    from pipeline import export
    sessionnet.fetch_all()
    build.build()
    export.export()
    out = config.EXPORT / config.STADT
    index = json.loads((out / "index.json").read_text())
    assert len(index["ortsteile"]) == 86 and len(index["bezirke"]) == 9
    an = {k for k, v in index["meta"]["funktionen"].items() if v}
    assert index["meta"]["stadt"] == "Köln" and an == {"technik", "kontext"}   # Technikseite (Phase 5), Kennzahlen (07.11.2026)
    for datei in ("suche.json", "zeit.json", "vorlagen.geojson", "termine.ics", "dcat.jsonld", "feeds/ganz-koeln.xml"):
        text = (out / datei).read_text(encoding="utf-8")
        assert "Bonn" not in text and "OParl-Lite" not in text, datei
    assert f"{config.STADT}/zeit.json" in (out / "dcat.jsonld").read_text()   # mit Vorlagen: Zeitleiste im DCAT-Katalog
    # deaktivierte Zusatzthemen erzeugen keine Dateien
    assert not (out / "soll.json").exists() and not (out / "chat").exists() and not (out / "dossiers").exists()
    assert (config.EXPORT / "audit_geokodierung.tsv").exists() and (config.EXPORT / "stichprobe_geokodierung.tsv").exists()


def test_zeitwerte_url_kodiert(oparl):
    """modified_since geht URL-kodiert hinaus (%3A, %2B): Köln wendet ihn nur so an (Stufe 2; der Testserver liest die
    Abfrage wie PHP: „+“ unkodiert wird Leerzeichen, der Filter übergangen)."""
    sessionnet.fetch_all()
    oparl.roh.clear()
    sessionnet.fetch_all()
    roh = [q for p, q in oparl.roh if p == "/papers"]
    assert roh and all(re.fullmatch(r"modified_since=\d{4}-\d\d-\d\dT\d\d%3A\d\d%3A\d\d%2B00%3A00", q) for q in roh)
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["filter_wirksam"], z["ergebnis"]) == ("inkrementell", "ja", "ok")
    assert "abruf_fehler" not in json.loads(config.STAND.read_text())


def test_zeitueberschreitung_gilt_als_moegliche_sperre(monkeypatch):
    aufrufe = []

    def haengt(*a, **k):
        aufrufe.append(1)
        raise TimeoutError("timed out")
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=haengt))   # die eine Stelle zum Netz
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json("http://127.0.0.1:9/body", pausen=[3600, 3600])
    assert e.value.art == "sperre" and "mögliche Sperre" in str(e.value)
    assert len(aufrufe) == 1                       # keine Wiederholung in derselben Nacht


def test_nach_drei_naechten_mit_abbruch_pausiert_der_abruf(oparl, monkeypatch):
    def sperre(url, pausen=None):
        raise abruf.Abbruch("Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre", "sperre")
    monkeypatch.setattr(abruf, "get_json", sperre)
    for _ in range(3):
        sessionnet.fetch_all()
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["naechte"] == 3
    monkeypatch.setattr(abruf, "get_json", lambda *a, **k: pytest.fail("darf nicht abrufen"))
    sessionnet.fetch_all()
    assert "pausiert" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]


def test_abbruch_und_pause_als_warnung_im_workflow(oparl, monkeypatch, capsys):
    """Generalprobe 09.11.2026: Ein Abbruch mit möglicher Sperre (etwa HTTP 401 auf die inkrementelle Sitzungsliste)
    und die Pause nach drei Nächten („bitte Kontakt zur Stadt aufnehmen“) standen nur als einfache Zeile im grünen
    Abrufschritt. Jetzt als Warnung (in GitHub Actions ::warning::), mit der Zahl der Nächte."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def abgelehnt(url, pausen=None):
        raise abruf.Abbruch(f"HTTP 401: {url}", "http", code=401)
    monkeypatch.setattr(abruf, "get_json", abgelehnt)
    for nacht in range(1, 4):
        sessionnet.fetch_all()
        out, err = capsys.readouterr()
        assert "::warning::Abruf abgebrochen, letzter gültiger Stand bleibt" in err
        assert f"Nacht mit möglicher Sperre ({nacht}. ohne vollständigen Lauf; nach 3 Nächten 7 Tage Pause)" in err
        assert "Abruf abgebrochen" not in out
    monkeypatch.setattr(abruf, "get_json", lambda *a, **k: pytest.fail("darf nicht abrufen"))
    sessionnet.fetch_all()
    err = capsys.readouterr().err
    assert "::warning::Abruf übersprungen (Abruf pausiert bis" in err and "Kontakt zur Stadt" in err


def test_abbruch_ohne_sperre_als_warnung_ende_des_fensters_ohne(oparl, monkeypatch, capsys):
    """Jeder andere Abbruch (hier HTTP 404, keine Sperrnacht) ebenfalls als Warnung, ohne Zusatz zur Sperre; das Ende
    des Zeitfensters und ein Lauf außerhalb des Zeitfensters (Push tagsüber) bleiben ohne Warnung."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def nicht_gefunden(url, pausen=None):
        raise abruf.Abbruch(f"HTTP 404: {url}", "http", code=404)

    def fenster_zu(url, pausen=None):
        raise abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr (RATSATLAS_ZEITFENSTER)", "zeitfenster")
    monkeypatch.setattr(abruf, "get_json", nicht_gefunden)
    sessionnet.fetch_all()
    err = capsys.readouterr().err
    assert "::warning::Abruf abgebrochen" in err and "möglicher Sperre" not in err
    config.ZUSTAND.unlink()
    monkeypatch.setattr(abruf, "get_json", fenster_zu)
    sessionnet.fetch_all()
    out, err = capsys.readouterr()
    assert "::warning::" not in err and "Abruf unterbrochen (Das Zeitfenster endete" in out
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(config, "OPARL_BODY", "https://oparl.example.invalid/body")   # nicht lokal, nie gesendet
    monkeypatch.setattr(abruf, "get_json", lambda *a, **k: pytest.fail("darf nicht abrufen"))
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: False)
    sessionnet.fetch_all()
    out, err = capsys.readouterr()
    assert "::warning::" not in err and "Abruf übersprungen (außerhalb des Zeitfensters" in out


def test_abgebrochener_vollabruf_wird_fortgesetzt(oparl, monkeypatch):
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    # Fortsetzung eine Seite zurück (Seite 2), damit Löschungen zwischen den Nächten nichts überspringen
    assert zustand["papers_fortsetzung"]["seiten"] == 2 and "page=2" in zustand["papers_fortsetzung"]["naechste"]
    assert sessionnet._zeit(zustand["papers_fortsetzung"]["gespeichert"]) is not None
    assert not config.PAPERS.exists() and len(_jsonl(config.RAW / "papers.teil.jsonl")) == 4
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["2", "3"]   # die letzte und die fehlende
    assert len(_jsonl(config.PAPERS)) == 5 and not (config.RAW / "papers.teil.jsonl").exists()
    z = [r for r in _statistik() if r["liste"] == "papers"]
    assert z[0]["ergebnis"].startswith("unterbrochen") and (z[-1]["modus"], z[-1]["ergebnis"]) == ("voll, fortgesetzt", "ok")
    assert "papers_fortsetzung" not in json.loads(config.ZUSTAND.read_text())


def test_seite_ohne_neue_kennungen_bricht_ab(monkeypatch):
    seiten = iter(range(2, 100))
    monkeypatch.setattr(abruf, "get_json", lambda url, pausen=None: {
        "data": [{"id": "x/1"}, {"id": "x/2"}], "links": {"next": f"http://127.0.0.1/l?page={next(seiten)}"}})
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l")
    assert e.value.art == "liste" and len(e.value.objekte) == 2 and e.value.seiten == 2


def _lokaler_server(antwort, host="127.0.0.1"):
    """Lokaler Hilfsserver: `antwort(methode, pfad)` liefert (Status, Kopfzeilen, Inhalt); Anfragen in `server.anfragen`,
    Eingangszeiten (time.monotonic) in `server.eingang`. `host`: Loopback-Adresse (127.0.0.2 gilt nicht als lokal)."""
    assert host.startswith("127.")
    anfragen, eingang = [], []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _antworten(self):
            eingang.append(time.monotonic())
            anfragen.append((self.command, self.path))
            status, kopf, inhalt = antwort(self.command, self.path)
            self.send_response(status)
            for k, v in {**kopf, "Content-Length": str(len(inhalt))}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(inhalt)

        do_GET = do_CONNECT = _antworten

    server = ThreadingHTTPServer((host, 0), H)
    server.anfragen, server.eingang, server.url = anfragen, eingang, f"http://{host}:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_weiterleitung_wird_nicht_verfolgt(oparl, monkeypatch):
    # jede Adresse außer /ziel leitet nach /ziel weiter; /ziel selbst antwortet mit JSON
    server = _lokaler_server(lambda methode, pfad: (200, {"Content-Type": "application/json"}, b"{}")
                             if pfad == "/ziel" else (301, {"Location": "/ziel"}, b""))
    ziel = f"{server.url}/ziel"
    try:
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/papers", pausen=[0, 0])
        assert e.value.art == "weiterleitung" and e.value.ziel == ziel and ziel in str(e.value)
        assert server.anfragen == [("GET", "/papers")]                # Ziel nicht abgerufen, keine Wiederholung
        nachher = abruf.statistik()
        assert (nachher["weiterleitungen"] - vorher["weiterleitungen"], nachher["fehler"] - vorher["fehler"]) == (1, 1)
        # andere Module folgen Weiterleitungen weiter nach dem Standard von urllib (kein install_opener)
        with urllib.request.urlopen(f"{server.url}/anderes", timeout=10) as r:
            assert r.status == 200 and r.geturl() == ziel
        # im Lauf: Abbruch mit Ziel in Abrufstatistik und STAND.json, aber keine Nacht mit möglicher Sperre
        body = oparl.body()
        monkeypatch.setattr(oparl, "body", lambda: {**body, "paper": f"{server.url}/papers"})
        server.anfragen.clear()
        sessionnet.fetch_all()
        assert [urllib.parse.urlsplit(z).path for _, z in server.anfragen] == ["/papers"]
    finally:
        server.shutdown()
        server.server_close()
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert z["ergebnis"].startswith("abbruch: Weiterleitung HTTP 301 nach") and ziel in z["ergebnis"]
    assert (z["anfragen"], z["fehler"], z["weiterleitungen"], z["proxy"]) == ("1", "1", "1", "0")
    assert ziel in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    # eine Weiterleitung (etwa auf die Sperrseite einer Firewall) zählt vorsichtshalber als Nacht mit möglicher Sperre
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["art"] == "weiterleitung"


def _schein_proxy(monkeypatch, connect, get=407):
    """Lokaler Schein-Proxy für alle fremden Adressen: CONNECT mit `connect`, unverschlüsselte Anfragen mit `get`; er
    leitet nichts weiter. Der modulweite Öffner wird neu gebaut, weil er den Proxy beim Bau aus der Umgebung liest
    (sonst gälte der Proxy der Arbeitsumgebung). Mindestabstand 0 nur hier, um die Tests kurz zu halten (eigener Test:
    test_mindestabstand_fuer_fremde_adressen)."""
    proxy = _lokaler_server(lambda methode, pfad: (connect, {}, b"") if methode == "CONNECT" else (get, {}, b""))
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, proxy.url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    monkeypatch.setattr(abruf, "_OEFFNER", abruf.oeffner())
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")   # Pflicht vor Anfragen an nicht lokale Ziele
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")
    return proxy


@pytest.mark.parametrize("code", [403, 405, 407])
def test_proxy_ablehnung_ist_keine_sperre(oparl, monkeypatch, code):
    # Schein-Proxy: lehnt jeden Tunnel (CONNECT) ab und unverschlüsselte Anfragen mit 407
    proxy = _schein_proxy(monkeypatch, code)
    try:
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json("https://example.invalid/oparl/body", pausen=[0, 0])
        assert e.value.art == "proxy" and f"HTTP {code}" in str(e.value) and "nicht erreicht" in str(e.value)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json("http://example.invalid/oparl/body", pausen=[0, 0])
        assert e.value.art == "proxy" and "HTTP 407" in str(e.value)
        assert abruf.statistik()["proxy"] - vorher["proxy"] == 2
        # genau ein Versuch je Anfrage, keine Wiederholung
        assert proxy.anfragen == [("CONNECT", "example.invalid:443"), ("GET", "http://example.invalid/oparl/body")]
        # im Lauf: Fehler vermerkt, aber keine Nacht mit möglicher Sperre
        monkeypatch.setattr(config, "OPARL_BODY", "https://example.invalid/oparl/body")
        sessionnet.fetch_all()
    finally:
        proxy.shutdown()
        proxy.server_close()
    assert "Proxy" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    assert not config.ZUSTAND.exists() or "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())
    z = [r for r in _statistik() if r["liste"] == "body"][-1]      # eigene Zeile für den Body
    assert (z["anfragen"], z["fehler"], z["proxy"], z["weiterleitungen"]) == ("1", "1", "1", "0")
    assert z["ergebnis"].startswith("abbruch: Ablehnung durch den Proxy")


@pytest.mark.parametrize("code", [502, 504])
def test_proxy_erreicht_die_stadt_nicht_ist_moegliche_sperre(oparl, monkeypatch, code):
    # 502/504 auf CONNECT: Der Proxy hat die Stadt angefragt, aber nicht erreicht (wie die Sperre bei mandari)
    proxy = _schein_proxy(monkeypatch, code)
    try:
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json("https://example.invalid/oparl/body", pausen=[0, 0])
        assert e.value.art == "sperre" and "mögliche Sperre" in str(e.value) and f"HTTP {code}" in str(e.value)
        assert proxy.anfragen == [("CONNECT", "example.invalid:443")]      # keine Wiederholung
        assert abruf.statistik()["proxy"] == vorher["proxy"]
        monkeypatch.setattr(config, "OPARL_BODY", "https://example.invalid/oparl/body")
        sessionnet.fetch_all()
        _nacht_spaeter()                                                    # nächste Nacht (sonst: gleiche Nacht, kein Lauf)
        sessionnet.fetch_all()
    finally:
        proxy.shutdown()
        proxy.server_close()
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["naechte"] == 2    # Nächte mit möglicher Sperre
    assert "mögliche Sperre" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    z = [r for r in _statistik() if r["liste"] == "body"][-1]
    assert (z["anfragen"], z["fehler"], z["proxy"]) == ("1", "1", "0") and "mögliche Sperre" in z["ergebnis"]


def test_proxy_ueberlastet_wie_429_5xx(oparl, monkeypatch):
    # 503 auf CONNECT (Begrenzung, Überlastung): wie HTTP 429/5xx mit Pausen, danach „aufgegeben“; keine Ablehnung
    # durch den Proxy, aber eine Nacht mit möglicher Sperre (Squid/Envoy melden so auch ein unerreichbares Ziel)
    proxy = _schein_proxy(monkeypatch, 503)
    try:
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json("https://example.invalid/oparl/body", pausen=[0, 0])
        assert (e.value.art, e.value.code) == ("aufgegeben", 503) and len(proxy.anfragen) == 3
        nachher = abruf.statistik()
        assert (nachher["wiederholungen"] - vorher["wiederholungen"], nachher["proxy"] - vorher["proxy"]) == (2, 0)
        monkeypatch.setattr(config, "ABRUF_PAUSEN", [0, 0])
        monkeypatch.setattr(config, "OPARL_BODY", "https://example.invalid/oparl/body")
        sessionnet.fetch_all()
    finally:
        proxy.shutdown()
        proxy.server_close()
    verdacht = json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]
    assert (verdacht["naechte"], verdacht["art"], verdacht["code"]) == (1, "aufgegeben", 503)


def test_mindestabstand_fuer_fremde_adressen(monkeypatch, capsys):
    """Abstand vom Ende der Antwort; für nicht lokale Adressen mindestens 2 s, auch wenn RATSATLAS_ABSTAND kleiner ist."""
    uhr = {"t": 1000.0}
    gewartet = []

    def schlafen(s):
        gewartet.append(round(s, 3))
        uhr["t"] += s

    class Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            uhr["t"] += 5.0              # Antwort dauert 5 s (länger als der Abstand)
            return b"{}"

    monkeypatch.setattr(abruf, "time", types.SimpleNamespace(monotonic=lambda: uhr["t"], sleep=schlafen))
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=lambda req, timeout: Antwort()))
    monkeypatch.setattr(abruf, "_letzte", 0.0)
    monkeypatch.setattr(abruf, "_hinweis_abstand", False)
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.5)
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    assert abruf.abstand(lokal=False) == 2.0 and abruf.abstand(lokal=True) == 0.5
    assert "RATSATLAS_ABSTAND=0.5 s liegt unter dem Mindestabstand" in capsys.readouterr().err
    abruf.get_json("https://example.invalid/a")
    abruf.get_json("https://example.invalid/b")
    assert gewartet == [2.0]             # gemessen vom Ende der 5 s langen Antwort, auf 2 s angehoben
    abruf.get_json("http://127.0.0.1:9/c")
    assert gewartet == [2.0, 0.5]        # lokaler Testserver: eingestellter Wert
    for wert in (float("nan"), float("inf"), -1.0):
        monkeypatch.setattr(config, "ABRUF_ABSTAND", wert)
        assert abruf.abstand(lokal=False) == 2.0
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 3.0)
    assert abruf.abstand(lokal=False) == 3.0


def test_teilabbruch_uebernimmt_ziel(monkeypatch):
    def weiter(url, pausen=None):
        raise abruf.Abbruch("Weiterleitung HTTP 301 nach https://example.invalid/neu nicht verfolgt", "weiterleitung",
                            "https://example.invalid/neu")
    monkeypatch.setattr(abruf, "get_json", weiter)
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l")
    assert (e.value.art, e.value.ziel) == ("weiterleitung", "https://example.invalid/neu")


@pytest.mark.parametrize("art", ["weiterleitung", "proxy", "adresse"])
def test_keine_fortsetzung_nach_weiterleitung_oder_proxy(oparl, monkeypatch, art):
    echt = abruf.get_json
    seite_3 = {"aktiv": False}

    def get_json(url, pausen=None):
        if seite_3["aktiv"] and "/papers" in url and "page=3" in url:
            raise abruf.Abbruch(f"Test {art}", art, "https://example.invalid/neu" if art == "weiterleitung" else "")
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)
    # erster Lauf: HTTP 404 auf Seite 3 → Fortsetzung gespeichert (wie test_abgebrochener_vollabruf_wird_fortgesetzt)
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    assert "papers_fortsetzung" in json.loads(config.ZUSTAND.read_text())
    # Fortsetzung bricht mit Weiterleitung bzw. Proxy ab → verworfen; der nächste Lauf beginnt von vorn
    seite_3["aktiv"] = True
    sessionnet.fetch_all()
    assert "papers_fortsetzung" not in json.loads(config.ZUSTAND.read_text())
    assert not (config.RAW / "papers.teil.jsonl").exists()
    # Vollabruf von vorn: Abbruch nach zwei Seiten speichert keine Fortsetzung
    sessionnet.fetch_all()
    assert "papers_fortsetzung" not in json.loads(config.ZUSTAND.read_text())
    assert not (config.RAW / "papers.teil.jsonl").exists()
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["seiten"], z["objekte"]) == ("voll", "2", "4") and z["ergebnis"] == f"abbruch: Test {art}"


def test_alte_abrufstatistik_bekommt_neue_spalten(oparl):
    alt = ["datum", "liste", "modus", "seiten", "objekte", "neu", "geaendert", "geloescht", "filter_wirksam",
           "anfragen", "fehler", "wiederholungen", "bytes", "sekunden", "ergebnis"]
    config.EXPORT.mkdir(parents=True, exist_ok=True)
    config.ABRUFSTATISTIK.write_text("\t".join(alt) + "\n" + "\t".join(
        ["2026-11-01T22:30:00+00:00", "papers", "voll", "3", "5", "5", "0", "0", "", "3", "0", "0", "100", "1.0",
         "ok"]) + "\n", encoding="utf-8")
    sessionnet.fetch_all()
    with open(config.ABRUFSTATISTIK, encoding="utf-8") as f:
        assert f.readline().rstrip("\n").split("\t") == sessionnet.STAT_SPALTEN
    zeilen = _statistik()
    assert (zeilen[0]["datum"], zeilen[0]["ergebnis"], zeilen[0]["bytes"], zeilen[0]["weiterleitungen"]) == (
        "2026-11-01T22:30:00+00:00", "ok", "100", "")
    assert [z["liste"] for z in zeilen[1:]] == ["body", "organizations", "papers", "meetings"]


# Antworten, die mitten im Inhalt oder schon in der Statuszeile scheitern (http.client.HTTPException, kein OSError)
UNVOLLSTAENDIG = {
    "content-length": (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n"
                       b"{\"data\": [", "IncompleteRead"),
    "chunked": (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                b"5\r\n{\"a\":\r\n", "IncompleteRead"),
    "statuszeile": (b"GARBAGE\r\n\r\n", "BadStatusLine"),
}


@pytest.mark.parametrize("fall", list(UNVOLLSTAENDIG))
def test_abgeschnittene_oder_unlesbare_antwort_ist_moegliche_sperre(oparl, monkeypatch, roher_server, fall):
    """Abgeschnittener Inhalt (Content-Length, chunked ohne Abschluss) und unlesbare Statuszeile: Art `sperre` ohne
    Wiederholung; im Lauf kein Traceback, Fehler in STAND.json, Nacht mit möglicher Sperre gezählt."""
    antwort, name = UNVOLLSTAENDIG[fall]
    server = roher_server(antwort)
    monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json(f"{server.url}/body", pausen=[0, 0])
    assert e.value.art == "sperre" and "mögliche Sperre" in str(e.value) and name in str(e.value)
    assert server.anfragen == ["GET /body HTTP/1.1"]                    # keine Wiederholung
    monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
    sessionnet.fetch_all()                                              # kein Traceback
    sessionnet.fetch_all()
    assert len(server.anfragen) == 3
    verdacht = json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]
    assert (verdacht["naechte"], verdacht["art"]) == (2, "sperre")
    assert "mögliche Sperre" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    z = [r for r in _statistik() if r["liste"] == "body"][-1]
    assert (z["anfragen"], z["fehler"], z["wiederholungen"]) == ("1", "1", "0") and "mögliche Sperre" in z["ergebnis"]


def test_unlesbare_antwort_des_proxys_auf_connect_ist_moegliche_sperre(oparl, monkeypatch, roher_server):
    # Schein-Proxy antwortet auf CONNECT mit einer unlesbaren Statuszeile (BadStatusLine beim Tunnelaufbau)
    proxy = roher_server(b"GARBAGE\r\n\r\n")
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, proxy.url)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    monkeypatch.setattr(abruf, "_OEFFNER", abruf.oeffner())
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")   # Pflicht vor Anfragen an nicht lokale Ziele
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json("https://example.invalid/oparl/body", pausen=[0, 0])
    assert e.value.art == "sperre" and "BadStatusLine" in str(e.value)
    assert proxy.anfragen == ["CONNECT example.invalid:443 HTTP/1.1"]   # keine Wiederholung
    monkeypatch.setattr(config, "OPARL_BODY", "https://example.invalid/oparl/body")
    sessionnet.fetch_all()
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["naechte"] == 1


def test_ungueltige_adresse_wird_nicht_gesendet(monkeypatch):
    monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    for url in ("http://127.0.0.1:9/papers?page=2 x", "http://127.0.0.1:9/papers?page=2&ort=Köln"):
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(url, pausen=[0, 0])
        assert e.value.art == "adresse" and not sessionnet.moegliche_sperre(e.value), url
        assert abruf.statistik()["anfragen"] == vorher["anfragen"]


def test_moegliche_sperre():
    def abbruch(art, code=None):
        return abruf.Abbruch("Test", art, code=code)
    for e in (abbruch("sperre"), abbruch("aufgegeben"), abbruch("aufgegeben", 503), abbruch("http", 401),
              abbruch("http", 403), abbruch("http", 429), abbruch("weiterleitung", 301), abbruch("unlesbar")):
        assert sessionnet.moegliche_sperre(e), (e.art, e.code)
    for e in (abbruch("http", 404), abbruch("http", 407), abbruch("proxy", 407), abbruch("leer"),
              abbruch("liste"), abbruch("adresse"), abbruch("zeitfenster"), RuntimeError("Beratungen: nur 0"),
              KeyError("feld"), TypeError("x")):
        assert not sessionnet.moegliche_sperre(e), (getattr(e, "art", ""), getattr(e, "code", None))
    # Teilabbruch übernimmt Art und Code
    t = sessionnet.Teilabbruch(abbruch("http", 403), [], None, 0)
    assert (t.art, t.code) == ("http", 403) and sessionnet.moegliche_sperre(t)


@pytest.mark.parametrize("status, inhalt, art, anfragen_je_nacht", [
    (401, b"", "http", 1), (403, b"", "http", 1), (429, b"", "aufgegeben", 3), (503, b"", "aufgegeben", 3),
    (200, b"<html><body>Zugriff gesperrt</body></html>", "aufgegeben", 3)])
def test_sperrsignale_zaehlen_als_nacht_mit_moeglicher_sperre(oparl, monkeypatch, status, inhalt, art,
                                                              anfragen_je_nacht):
    """HTTP 401/403 und „aufgegeben“ nach 429, 5xx oder unlesbarer Antwort (z. B. HTML-Sperrseite mit 200): nach drei
    Nächten in Folge pausiert der Abruf sieben Tage."""
    server = _lokaler_server(lambda methode, pfad: (status, {"Content-Type": "text/html"}, inhalt))
    monkeypatch.setattr(config, "ABRUF_PAUSEN", [0, 0])
    monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
    try:
        for nacht in range(1, 4):
            sessionnet.fetch_all()
            verdacht = json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]
            assert (verdacht["naechte"], verdacht["art"]) == (nacht, art)
        assert len(server.anfragen) == 3 * anfragen_je_nacht
        sessionnet.fetch_all()                                   # vierte Nacht: pausiert, keine Anfrage
        assert len(server.anfragen) == 3 * anfragen_je_nacht
    finally:
        server.shutdown()
        server.server_close()
    assert "pausiert" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]


def test_407_ohne_proxy_kommt_von_der_gegenseite(oparl, monkeypatch):
    """HTTP 407 gilt nur als Ablehnung durch den Proxy, wenn für das Schema ein Proxy gesetzt ist und der Host nicht
    ausgenommen ist (GitHub Actions: kein Proxy, dann kommt 407 vom Server)."""
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    server = _lokaler_server(lambda methode, pfad: (407, {}, b""))
    url = f"{server.url}/body"
    try:
        monkeypatch.setattr(abruf, "_OEFFNER", abruf.oeffner())
        assert not abruf.proxy_gesetzt(url)
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(url, pausen=[0, 0])
        assert (e.value.art, e.value.code) == ("http", 407) and abruf.statistik()["proxy"] == vorher["proxy"]
        # Proxy gesetzt, aber 127.0.0.1 ausgenommen: die Anfrage geht direkt, der 407 kommt vom Server
        for name in ("HTTP_PROXY", "http_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(name, "127.0.0.1,localhost")
        monkeypatch.setattr(abruf, "_OEFFNER", abruf.oeffner())
        assert not abruf.proxy_gesetzt(url) and abruf.proxy_gesetzt("http://example.invalid/body")
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(url, pausen=[0, 0])
        assert (e.value.art, e.value.code) == ("http", 407)
        assert len(server.anfragen) == 2
        monkeypatch.setattr(config, "OPARL_BODY", url)
        sessionnet.fetch_all()
    finally:
        server.shutdown()
        server.server_close()
    assert not config.ZUSTAND.exists() or "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())
    assert "HTTP 407" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]


def test_lokal_nur_ueber_schema_und_host(oparl, monkeypatch):
    """Nur http mit Host 127.0.0.1, localhost oder ::1 ist lokal; localhost.example.org oder 127.0.0.1.nip.io sind
    fremde Adressen: Freigabe, Zeitfenster und Mindestabstand gelten. Keine echte Anfrage (Öffner ersetzt)."""
    for url in ("http://127.0.0.1:8080/x", "http://localhost/", "http://LOCALHOST:1/", "http://[::1]:9/"):
        assert abruf.lokal(url), url
    fremd = ("http://localhost.example.org/oparl/body", "http://127.0.0.1.nip.io/oparl/body")
    for url in (*fremd, "https://127.0.0.1/", "http://127.0.0.1@example.invalid/", "http://[::1/", "http://127.0.0.2/"):
        assert not abruf.lokal(url), url
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=lambda *a, **k: pytest.fail("keine Anfrage")))
    # ohne Freigabe: gesperrt vor der Anfrage, im Lauf übersprungen
    for url in fremd:
        assert not abruf.freigegeben(url)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(url)
        assert e.value.art == "gesperrt"
        monkeypatch.setattr(config, "OPARL_BODY", url)
        sessionnet.fetch_all()
        assert "nicht informiert" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    # mit Freigabe gilt das Zeitfenster
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: False)
    for url in fremd:
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(url)
        assert e.value.art == "zeitfenster"
        monkeypatch.setattr(config, "OPARL_BODY", url)
        sessionnet.fetch_all()
        assert "Zeitfenster" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    # und der Mindestabstand (Scheinuhr, Scheinöffner): 2 s trotz RATSATLAS_ABSTAND=0, lokal 0
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    uhr, gewartet = {"t": 500.0}, []

    def schlafen(s):
        gewartet.append(round(s, 3))
        uhr["t"] += s

    class Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"
    monkeypatch.setattr(abruf, "time", types.SimpleNamespace(monotonic=lambda: uhr["t"], sleep=schlafen))
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=lambda req, timeout: Antwort()))
    monkeypatch.setattr(abruf, "_letzte", uhr["t"])                 # wie beim Import: gerade eben
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    for url in fremd:
        abruf.get_json(url)
    abruf.get_json("http://127.0.0.1:9/lokal")
    assert gewartet == [2.0, 2.0]


def test_erste_anfrage_eines_prozesses_folgt_frühestens_2_s_nach_dem_start():
    """Neuer Prozess (pipeline.abruf frisch importiert) gegen einen Server auf 127.0.0.2, der nicht als lokal gilt:
    Die erste Anfrage kommt frühestens 2 s nach dem Import, auch mit RATSATLAS_ABSTAND=0."""
    server = _lokaler_server(lambda methode, pfad: (200, {"Content-Type": "application/json"}, b"{}"), "127.0.0.2")
    keine = ",".join(x for x in (os.environ.get("NO_PROXY", ""), "127.0.0.1,127.0.0.2,localhost") if x)
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_")},
           "RATSATLAS_SPERRE": os.environ["RATSATLAS_SPERRE"],   # Sperrdatei der Messskripte nie in ~/.cache
           "RATSATLAS_STADT_INFORMIERT": "ja", "RATSATLAS_ZEITFENSTER": "", "RATSATLAS_ABSTAND": "0",
           "NO_PROXY": keine, "no_proxy": keine, "PYTHONPATH": str(config.ROOT)}
    skript = ("import sys, time; t = time.monotonic(); from pipeline import abruf; abruf.get_json(sys.argv[1]); "
              "print(t)")
    try:
        r = subprocess.run([sys.executable, "-c", skript, f"{server.url}/body"], env=env, cwd=config.ROOT,
                           capture_output=True, text=True, timeout=60)
    finally:
        server.shutdown()
        server.server_close()
    assert r.returncode == 0, r.stderr
    assert len(server.eingang) == 1 and server.eingang[0] - float(r.stdout.strip()) >= 2.0
    assert "RATSATLAS_ABSTAND=0 s liegt unter dem Mindestabstand" in r.stderr


def _nacht_spaeter(stunden=13):
    """Letzten Sperrverdacht, Listenfehler und Abbruch um `stunden` zurückdatieren (simuliert die nächste Nacht)."""
    z = json.loads(config.ZUSTAND.read_text())
    for schluessel in ("sperre_verdacht", "listenfehler", "letzter_abbruch"):
        if schluessel in z:
            zuletzt = datetime.fromisoformat(z[schluessel]["zuletzt"]) - timedelta(hours=stunden)
            z[schluessel]["zuletzt"] = zuletzt.isoformat(timespec="seconds")
    config.ZUSTAND.write_text(json.dumps(z))


def _nicht_lokal(monkeypatch):
    """Lokalen Testserver wie einen Server der Stadt behandeln (Freigabe, Zeitfenster, Mindestabstand 0 für die Tests,
    Kontakt im User-Agent wie in GitHub Actions: ohne ihn keine Anfrage an ein nicht lokales Ziel)."""
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")
    monkeypatch.setattr(abruf, "lokal", lambda url: False)
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)


def test_kein_zweiter_lauf_in_derselben_nacht_nach_sperrverdacht(oparl, monkeypatch):
    _nicht_lokal(monkeypatch)
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    config.RAW.mkdir(parents=True, exist_ok=True)
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    config.ZUSTAND.write_text(json.dumps({"sperre_verdacht": {"naechte": 1, "zuletzt": jetzt, "art": "sperre"}}))
    monkeypatch.setattr(abruf, "get_json", lambda *a, **k: pytest.fail("darf in derselben Nacht nicht abrufen"))
    sessionnet.fetch_all()
    assert "derselben Nacht" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    assert oparl.anfragen == []


def test_aufgeben_wenn_die_naechste_pause_ueber_das_zeitfenster_reicht(monkeypatch):
    """429/503 kurz vor Ende des Zeitfensters: sofort „aufgegeben“ (zählt als Nacht mit möglicher Sperre), statt die
    Pause abzuwarten und nur „Zeitfenster vorbei“ zu melden."""
    server = _lokaler_server(lambda methode, pfad: (503, {}, b""))
    try:
        _nicht_lokal(monkeypatch)
        monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
        monkeypatch.setattr(abruf, "fenster_offen_nach", lambda sekunden, jetzt=None: sekunden < 600)
        monkeypatch.setattr(abruf.time, "sleep", lambda s: None)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/body", pausen=[60, 300, 1800, 3600])
        assert e.value.art == "aufgegeben" and e.value.code == 503 and "Zeitfenster" in str(e.value)
        assert len(server.anfragen) == 3            # Versuche nach 60 s und 300 s, die 1800-s-Pause passt nicht mehr
        assert sessionnet.moegliche_sperre(e.value)
    finally:
        server.shutdown()
        server.server_close()


def test_fenster_offen_nach(monkeypatch):
    """Die Pause muss vor dem Ende des laufenden Fensters enden (in UTC gerechnet); eine Pause, die im Fenster einer
    späteren Nacht endet (Umlauf ≥ 22 h), zählt nicht."""
    berlin, utc = ZoneInfo("Europe/Berlin"), timezone.utc
    assert config.ABRUF_ZEITFENSTER == "23-1"
    jetzt = datetime(2026, 11, 7, 23, 10, tzinfo=berlin)                 # Fensterende 01:00, noch 6600 s
    assert abruf.fenster_ende(jetzt) == datetime(2026, 11, 8, 1, 0, tzinfo=berlin)
    assert abruf.fenster_offen_nach(600, jetzt) and abruf.fenster_offen_nach(6599, jetzt)
    assert not abruf.fenster_offen_nach(6600, jetzt)
    for umlauf in (22 * 3600, 86400 - 600, 86400, 2 * 86400 - 600, 10 ** 12):   # endet in einer späteren Nacht
        assert not abruf.fenster_offen_nach(umlauf, jetzt), umlauf
    assert not abruf.fenster_offen_nach(3600, datetime(2026, 11, 8, 0, 30, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(60, datetime(2026, 11, 7, 12, 0, tzinfo=berlin))
    # Grenzen: 00:59 noch offen (59 s), 01:00 und 22:59 geschlossen
    assert abruf.fenster_offen_nach(59, datetime(2026, 11, 8, 0, 59, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(60, datetime(2026, 11, 8, 0, 59, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(0, datetime(2026, 11, 8, 1, 0, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(0, datetime(2026, 11, 7, 22, 59, tzinfo=berlin))
    # ohne Zone als Ortszeit gelesen, in UTC umgerechnet (23:10 MEZ = 22:10 UTC)
    assert abruf.fenster_offen_nach(6599, datetime(2026, 11, 7, 23, 10))
    assert abruf.fenster_offen_nach(6599, datetime(2026, 11, 7, 22, 10, tzinfo=utc))
    assert not abruf.fenster_offen_nach(6600, datetime(2026, 11, 7, 22, 10, tzinfo=utc))
    # Zeitumstellung im Fenster 23–1: 25.10.2026 00:30 MESZ, Ende 01:00 MESZ (nicht MEZ)
    jetzt = datetime(2026, 10, 24, 22, 30, tzinfo=utc)
    assert abruf.fenster_offen_nach(1799, jetzt) and not abruf.fenster_offen_nach(1800, jetzt)
    # Fenster über die Zeitumstellung (22–6): im Herbst 9 h echte Zeit, im Frühjahr 7 h
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "22-6")
    herbst = datetime(2026, 10, 24, 22, 0, tzinfo=berlin)                # 22:00 MESZ → 06:00 MEZ
    assert abruf.fenster_offen_nach(8.5 * 3600, herbst) and abruf.fenster_offen_nach(32399, herbst)
    assert not abruf.fenster_offen_nach(32400, herbst)
    fruehjahr = datetime(2026, 3, 28, 22, 0, tzinfo=berlin)              # 22:00 MEZ → 06:00 MESZ
    assert abruf.fenster_offen_nach(25199, fruehjahr) and not abruf.fenster_offen_nach(7.5 * 3600, fruehjahr)
    # Fenster am Tag (9–17): Ende am selben Tag
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "9-17")
    assert abruf.fenster_offen_nach(3599, datetime(2026, 11, 7, 16, 0, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(3600, datetime(2026, 11, 7, 16, 0, tzinfo=berlin))
    # ohne Zeitfenster (leer) und über den ganzen Tag (von = bis): immer offen, kein Ende; lange Pausen begrenzt dann
    # die Regel „Retry-After länger als die längste Pause“ (test_retry_after_laenger_als_die_laengste_pause)
    for fenster in ("", " ", "5-5"):
        monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", fenster)
        assert abruf.fenster_ende(jetzt) is None and abruf.fenster_offen_nach(10 ** 12, jetzt), fenster


def _scheinzeit(monkeypatch):
    """Schlafen ohne Warten (nur in abruf); liefert die Liste der Pausen."""
    gewartet = []
    monkeypatch.setattr(abruf, "time", types.SimpleNamespace(monotonic=time.monotonic, sleep=gewartet.append))
    return gewartet


def test_zeitfenster_vorbei_nach_der_pause_gilt_als_aufgegeben(monkeypatch):
    """Fallback: Ist das Fenster nach der Pause doch geschlossen (etwa weil die Pause länger dauerte), endet der Abruf
    als „aufgegeben“ (Nacht mit möglicher Sperre) ohne weitere Anfrage."""
    server = _lokaler_server(lambda methode, pfad: (503, {}, b""))
    try:
        _nicht_lokal(monkeypatch)
        offen = iter([True, False])
        monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: next(offen))
        monkeypatch.setattr(abruf, "fenster_offen_nach", lambda sekunden, jetzt=None: True)
        gewartet = _scheinzeit(monkeypatch)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/body", pausen=[60, 300])
        assert (e.value.art, e.value.code) == ("aufgegeben", 503) and "Zeitfenster vorbei" in str(e.value)
        assert len(server.anfragen) == 1 and gewartet == [60] and sessionnet.moegliche_sperre(e.value)
    finally:
        server.shutdown()
        server.server_close()


def test_retry_after_sekunden():
    jetzt = datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc)
    assert abruf.retry_after_sekunden("120") == 120 and abruf.retry_after_sekunden(" 7 ") == 7
    assert abruf.retry_after_sekunden(None) == 0 and abruf.retry_after_sekunden("") == 0
    assert abruf.retry_after_sekunden("999999999999") == 999999999999
    # mehr als 12 Ziffern (ohne führende Nullen): unendlich lang, kein ValueError aus int() (über 4300 Ziffern)
    assert abruf.retry_after_sekunden("9" * 5000) == math.inf == abruf.retry_after_sekunden("1" + "0" * 12)
    assert abruf.retry_after_sekunden("0" * 5000 + "5") == 5 and abruf.retry_after_sekunden("000") == 0
    # HTTP-Datum (RFC 9110): Sekunden bis dahin; Vergangenheit 0; „-0000“ als UTC
    assert abruf.retry_after_sekunden("Wed, 21 Oct 2026 07:28:00 GMT", jetzt) == 1680
    assert abruf.retry_after_sekunden("Wed, 21 Oct 2026 09:28:00 +0200", jetzt) == 1680
    assert abruf.retry_after_sekunden("Wed, 21 Oct 2026 07:28:00 -0000", jetzt) == 1680
    assert abruf.retry_after_sekunden("Fri, 31 Dec 1999 23:59:59 GMT", jetzt) == 0
    for unlesbar in ("-5", "1.5", "bald", "٣", "Wed, 32 Oct 2026 07:28:00 GMT", "0x10"):
        assert abruf.retry_after_sekunden(unlesbar, jetzt) is None, unlesbar


def test_retry_after_als_datum_wird_eingehalten(monkeypatch):
    """Retry-After als HTTP-Datum zwei Stunden voraus: Pause 2 h statt der ersten Pause (60 s)."""
    datum = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    antworten = iter([(503, {"Retry-After": datum}, b""), (200, {"Content-Type": "application/json"}, b"{}")])
    server = _lokaler_server(lambda methode, pfad: next(antworten))
    try:
        _nicht_lokal(monkeypatch)
        monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
        monkeypatch.setattr(abruf, "fenster_offen_nach", lambda sekunden, jetzt=None: True)
        gewartet = _scheinzeit(monkeypatch)
        assert abruf.get_json(f"{server.url}/body", pausen=[60, 3 * 3600]) == {}
        assert len(server.anfragen) == 2 and len(gewartet) == 1 and 7100 <= gewartet[0] <= 7201
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("wert, grund", [("999999999999", "länger als die längste Pause"),
                                         ("14400", "länger als die längste Pause"),
                                         ("bald", "Retry-After unlesbar"),
                                         ("Wed, 32 Oct 2026 07:28:00 GMT", "Retry-After unlesbar")])
def test_retry_after_laenger_als_die_laengste_pause(oparl, monkeypatch, wert, grund):
    """Retry-After länger als die längste Pause (auch absurd lang) oder unlesbar: sofort aufgegeben, eine Anfrage, keine
    Pause; im Lauf eine Nacht mit möglicher Sperre (kein Traceback durch Überlauf)."""
    server = _lokaler_server(lambda methode, pfad: (429, {"Retry-After": wert}, b""))
    try:
        monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")      # ohne Zeitfenster: nur diese Regel begrenzt
        _nicht_lokal(monkeypatch)
        gewartet = _scheinzeit(monkeypatch)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/body", pausen=[60, 300, 1800, 3600, 3 * 3600])
        assert (e.value.art, e.value.code) == ("aufgegeben", 429) and grund in str(e.value)
        assert len(server.anfragen) == 1 and gewartet == []
        monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
        sessionnet.fetch_all()
    finally:
        server.shutdown()
        server.server_close()
    verdacht = json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]
    assert (verdacht["naechte"], verdacht["art"], verdacht["code"]) == (1, "aufgegeben", 429)
    assert len(server.anfragen) == 2 and gewartet == []


@pytest.mark.parametrize("inhalt", [b"[]", b"null", b"3", b'"Text"', b'{"a": 1}', b'{"paper": [], "meeting": "x"}'])
def test_unerwartete_antwortform_ohne_traceback(oparl, monkeypatch, inhalt):
    """Gültiges JSON in unerwarteter Form (kein Objekt, Body ohne Listen) ist kein Überlastungssignal: eine Anfrage, keine
    Wiederholung, Art „unlesbar“; zählt als Nacht mit möglicher Sperre."""
    server = _lokaler_server(lambda methode, pfad: (200, {"Content-Type": "application/json"}, inhalt))
    try:
        monkeypatch.setattr(config, "ABRUF_PAUSEN", [0, 0, 0])
        monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
        sessionnet.fetch_all()                                   # kein Traceback
    finally:
        server.shutdown()
        server.server_close()
    assert len(server.anfragen) == 1
    verdacht = json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]
    assert (verdacht["naechte"], verdacht["art"]) == (1, "unlesbar")
    assert "unerwartete Antwortform" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    z = [r for r in _statistik() if r["liste"] == "body"][-1]
    assert (z["anfragen"], z["wiederholungen"]) == ("1", "0") and "unerwartete Antwortform" in z["ergebnis"]


@pytest.mark.parametrize("seite_2", [{"data": {"id": "x"}}, {"links": {}}, {"data": [{"name": "ohne Kennung"}]},
                                     {"data": ["x"]}, {"data": [], "links": "weiter"},
                                     {"data": [], "links": {"next": ["x"]}}])
def test_unerwartete_listenseite_ist_unlesbar(oparl, monkeypatch, seite_2):
    """Form einer Listenseite dort geprüft, wo sie ankommt: Abbruch „unlesbar“ ohne Wiederholung und ohne Traceback;
    der Vollabruf wird eine Seite davor fortgesetzt (Seite 1)."""
    echt = oparl.liste

    def liste(objekte, pfad, q, groesse=2):
        return seite_2 if pfad == "/papers" and q.get("page") == "2" else echt(objekte, pfad, q, groesse)
    monkeypatch.setattr(oparl, "liste", liste)
    sessionnet.fetch_all()
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == [None, "2"]
    zustand = json.loads(config.ZUSTAND.read_text())
    assert (zustand["sperre_verdacht"]["art"], zustand["papers_fortsetzung"]["seiten"]) == ("unlesbar", 1)
    assert zustand["papers_fortsetzung"]["naechste"] == f"{oparl.b}/papers"


def test_unerwartete_form_tief_im_objekt_ist_kein_sperrverdacht(oparl, monkeypatch):
    """Verweise als Liste statt Text in einer Beratung: kein Treffer, kein Traceback; eine Einladung als Text statt
    Objekt: ohne Adresse."""
    oparl.papers[0]["consultation"][0].update(meeting=[f"{oparl.b}/meetings/1"], agendaItem={"id": "x"})
    oparl.meetings[0]["invitation"] = "Einladung"
    sessionnet.fetch_all()
    stand = json.loads(config.STAND.read_text())
    assert "abruf_ok" in stand and "abruf_fehler" not in stand
    assert json.loads(config.MEETINGS.read_text())[0]["invitation"] is None
    assert f"{oparl.b}/consultations/1" not in {b["uri"] for b in _jsonl(config.BERATUNGEN)}


def test_programmfehler_bricht_laut_ab_ohne_sperrverdacht(oparl, monkeypatch):
    """Ein Programmfehler (hier KeyError in beratungen) ist kein Sperrsignal: vermerkt in STAND.json, Traceback, kein
    Zähler."""
    def kaputt(papers, meetings, *weitere):
        raise KeyError("feld")
    monkeypatch.setattr(sessionnet, "beratungen", kaputt)
    with pytest.raises(KeyError):
        sessionnet.fetch_all()
    assert "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())
    assert json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"].startswith("Programmfehler (KeyError")


def test_kopfzeile_nicht_kodierbar_bricht_laut_ab(oparl, monkeypatch):
    """RATSATLAS_KONTAKT mit Zeichen außerhalb von Latin-1: nichts gesendet, nicht gezählt, kein „unlesbar“ und keine
    Pausen, sondern ein lauter Abbruch (UnicodeEncodeError) ohne Sperrverdacht."""
    monkeypatch.setattr(config, "USER_AGENT", "ratsatlas-koeln/0.1 (Kontakt ☃)")
    vorher = abruf.statistik()
    with pytest.raises(UnicodeEncodeError):
        abruf.get_json(f"{oparl.b}/body", pausen=[0, 0])
    assert abruf.statistik()["anfragen"] == vorher["anfragen"] and oparl.anfragen == []
    with pytest.raises(UnicodeEncodeError):
        sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert oparl.anfragen == [] and "sperre_verdacht" not in zustand
    assert zustand["letzter_abbruch"]["art"] == "programmfehler"          # 12-Stunden-Regel, aber keine Sperrnacht
    assert "Programmfehler (UnicodeEncodeError" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]


def test_folgeadresse_ausserhalb_von_ascii_wird_nicht_gesendet(oparl, monkeypatch, capsys):
    """links.next mit Umlauten: Art „adresse“, nicht gesendet und nicht gezählt, keine Sperrnacht. Dauerhaft ungültig:
    Zähler `listenfehler`, Hinweis in STAND.json und Warnung; nach drei Nächten sieben Tage Pause; ein vollständiger
    Lauf setzt den Zähler zurück."""
    echt = oparl.liste

    def liste(objekte, pfad, q, groesse=2):
        seite = echt(objekte, pfad, q, groesse)
        if pfad == "/papers" and seite["links"].get("next"):
            seite["links"]["next"] = f"{oparl.b}/papers?page=2&straße=Bürgerstraße"
        return seite
    monkeypatch.setattr(oparl, "liste", liste)
    vorher = abruf.statistik()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json(f"{oparl.b}/papers?straße=ü")
    assert e.value.art == "adresse" and not sessionnet.moegliche_sperre(e.value) and oparl.anfragen == []
    nachher = abruf.statistik()
    assert (nachher["anfragen"] - vorher["anfragen"], nachher["fehler"] - vorher["fehler"]) == (0, 1)
    for nacht in range(1, 4):
        if nacht > 1:
            _nacht_spaeter()
        # zwei Läufe in derselben Nacht (lokal erlaubt) zählen als eine Nacht; nach der dritten Nacht gilt die Pause
        for lauf in range(2 if nacht < 3 else 1):
            oparl.anfragen.clear()
            sessionnet.fetch_all()
            assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == [None]   # nur Seite 1 gesendet
            zustand = json.loads(config.ZUSTAND.read_text())
            assert zustand["listenfehler"]["naechte"] == nacht and zustand["listenfehler"]["art"] == "adresse"
            assert "sperre_verdacht" not in zustand and "papers_fortsetzung" not in zustand
            hinweis = json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"]
            assert f"{nacht}. Nacht" in hinweis and "fehlerhaften Liste" in capsys.readouterr().err
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["anfragen"], z["fehler"]) == ("1", "1") and "nicht gesendet" in z["ergebnis"]
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                  # vierte Nacht: Pause, keine Anfrage
    assert oparl.anfragen == []
    assert "fehlerhaften Liste" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    # nach der Pause, Liste wieder in Ordnung: vollständiger Lauf setzt den Zähler zurück
    z = json.loads(config.ZUSTAND.read_text())
    z["listenfehler"]["zuletzt"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    config.ZUSTAND.write_text(json.dumps(z))
    monkeypatch.setattr(oparl, "liste", echt)
    sessionnet.fetch_all()
    assert "listenfehler" not in json.loads(config.ZUSTAND.read_text()) and len(_jsonl(config.PAPERS)) == 5


@pytest.mark.parametrize("inhalt", ["{kaputt", "[]", '{"papers": "gestern"}', '{"papers": "2026-11-07T22:10:00"}',
                                    '{"meetings": 1762553400}'])
def test_unlesbarer_zustand_bricht_ohne_anfrage_ab(oparl, inhalt):
    """Unlesbarer Zustand oder unlesbarer Zeitpunkt einer Liste: keine Anfrage, lauter Abbruch, Datei unverändert."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.ZUSTAND.write_text(inhalt, encoding="utf-8")
    with pytest.raises(sessionnet.ZustandUnlesbar):
        sessionnet.fetch_all()
    assert oparl.anfragen == [] and config.ZUSTAND.read_text(encoding="utf-8") == inhalt
    assert "keine Anfrage" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]


@pytest.mark.parametrize("zuletzt", ["2026-11-07T23:10:00", "kaputt", 1762553400, None, "2999-01-01T00:00:00+00:00"])
def test_unlesbarer_oder_kuenftiger_sperrverdacht_gilt_als_jetzt(oparl, monkeypatch, capsys, zuletzt):
    """12-Stunden-Regel: Zeitpunkt ohne Zone, unlesbar, als Zahl, fehlend oder in der Zukunft gilt als „jetzt“ (in
    dieser Nacht kein Abruf), wird neu geschrieben und gemeldet; kein Traceback, keine stille Dauersperre."""
    _nicht_lokal(monkeypatch)
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    echt = abruf.get_json
    monkeypatch.setattr(abruf, "get_json", lambda *a, **k: pytest.fail("darf in derselben Nacht nicht abrufen"))
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.ZUSTAND.write_text(json.dumps({"sperre_verdacht": {"naechte": 1, "zuletzt": zuletzt, "art": "sperre"}}))
    sessionnet.fetch_all()
    assert "derselben Nacht" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    neu = datetime.fromisoformat(json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["zuletzt"])
    assert abs(neu - datetime.now(timezone.utc)) < timedelta(minutes=1)
    assert "gilt als jetzt" in capsys.readouterr().err
    # 13 Stunden später läuft der Abruf wieder (keine Dauersperre)
    _nacht_spaeter()
    monkeypatch.setattr(abruf, "get_json", echt)
    sessionnet.fetch_all()
    assert "abruf_ok" in json.loads(config.STAND.read_text()) and oparl.anfragen


@pytest.mark.parametrize("naechte", ["drei", -1, True, None, 2.5])
def test_unlesbare_zahl_der_naechte_gilt_als_drei(oparl, monkeypatch, naechte):
    config.RAW.mkdir(parents=True, exist_ok=True)
    zuletzt = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat(timespec="seconds")
    config.ZUSTAND.write_text(json.dumps({"sperre_verdacht": {"naechte": naechte, "zuletzt": zuletzt}}))
    sessionnet.fetch_all()
    assert oparl.anfragen == []
    assert "pausiert" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["naechte"] == sessionnet.SPERRE_NAECHTE


@pytest.mark.parametrize("fall", ["teil_fehlt", "teil_kaputt", "start_kaputt", "ohne_adresse"])
def test_unlesbare_fortsetzung_wird_verworfen(oparl, monkeypatch, capsys, fall):
    """Unlesbare Fortsetzung (fehlende oder unlesbare Teildatei, unlesbarer Start, keine Folgeadresse): verworfen und
    gemeldet, der Vollabruf beginnt von vorn – nie mit einem unvollständigen Teilstand."""
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    teil = config.RAW / "papers.teil.jsonl"
    z = json.loads(config.ZUSTAND.read_text())
    if fall == "teil_fehlt":
        teil.unlink()
    elif fall == "teil_kaputt":
        teil.write_text(teil.read_text() + "{kaputt\n")
    else:
        z["papers_fortsetzung"].update({"start": "gestern"} if fall == "start_kaputt" else {"naechste": None})
        config.ZUSTAND.write_text(json.dumps(z))
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == [None, "2", "3"]   # von vorn
    assert len(_jsonl(config.PAPERS)) == 5 and not teil.exists()
    assert "Fortsetzung von papers verworfen" in capsys.readouterr().err
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll, Fortsetzung verworfen", "ok")


def test_unlesbare_stand_json_wird_beiseitegelegt(oparl, capsys):
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.STAND.write_text("{kaputt", encoding="utf-8")
    sessionnet.fetch_all()
    assert "abruf_ok" in json.loads(config.STAND.read_text())
    assert (config.RAW / "STAND.json.defekt").read_text(encoding="utf-8") == "{kaputt"
    assert "STAND.json unlesbar" in capsys.readouterr().err


def test_unlesbares_modified_wird_gezaehlt(oparl):
    """Ein unlesbares oder zonenloses `modified` der Quelle bricht den Lauf nicht ab (vorher ValueError bzw. TypeError
    als Sperrverdacht), sondern steht in der Abrufstatistik."""
    sessionnet.fetch_all()
    zeit = datetime.fromisoformat(json.loads(config.ZUSTAND.read_text())["papers"])
    oparl.papers += [oparl.paper(6, modified="kaputt"),
                     oparl.paper(7, modified=zeit.replace(tzinfo=None).isoformat(timespec="seconds"))]
    sessionnet.fetch_all()
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["filter_wirksam"], z["ergebnis"]) == ("inkrementell", "ja; 2 mit unlesbarem modified", "ok")
    assert len(_jsonl(config.PAPERS)) == 7 and "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())


def test_schreibfehler_der_statistik_verdraengt_den_abbruch_nicht(oparl, monkeypatch, capsys):
    """Scheitert das Schreiben der Abrufstatistik (OSError, z. B. voller Datenträger), zählt die Nacht trotzdem als
    Nacht mit möglicher Sperre."""
    def sperre(url, pausen=None):
        raise abruf.Abbruch("Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre", "sperre")

    def voll(zeile):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(abruf, "get_json", sperre)
    monkeypatch.setattr(sessionnet, "_statistik", voll)
    sessionnet.fetch_all()
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["naechte"] == 1
    assert "Abrufstatistik nicht geschrieben" in capsys.readouterr().err


def test_net_verweigert_anfragen_an_die_stadt(monkeypatch):
    """pipeline/net.py (Wiederholungen, mehrere Verbindungen, kein Zeitfenster) verweigert Adressen der Stadt vor dem
    Senden, auch für `fetch-besetzung`; andere Hosts und lokale Testserver bleiben unverändert. Keine echte Anfrage."""
    from pipeline import besetzung, net
    monkeypatch.setattr(net, "_OEFFNER", types.SimpleNamespace(open=lambda *a, **k: pytest.fail("keine Anfrage")))
    monkeypatch.setattr(config, "OPARL_BODY", "https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
    for url in (f"{config.OPARL_BODY}/persons?page=1&size=100", "https://www.offenedaten-koeln.de/x.json",
                "https://OFFENEDATEN-KOELN.DE./x", "https://stadt-koeln.de/", "http://geoportal.stadt-koeln.de/a"):
        with pytest.raises(net.AbrufVerweigert, match="pipeline/abruf.py"):
            net.get_json(url)
    with pytest.raises(net.AbrufVerweigert):
        net.post_graphql("https://buergerinfo.stadt-koeln.de/graphql", "{x}")
    with pytest.raises(net.AbrufVerweigert):
        net.post_form("https://www.stadt-koeln.de/suche", {"q": "x"})
    monkeypatch.setattr(besetzung, "PERSONEN_URL", f"{config.OPARL_BODY}/persons")
    with pytest.raises(net.AbrufVerweigert):
        besetzung.fetch()
    # Host der eingestellten OParl-API, auch außerhalb der Domains der Stadt (sofern nicht lokal)
    monkeypatch.setattr(config, "OPARL_BODY", "https://ris.example.invalid/oparl/body")
    with pytest.raises(net.AbrufVerweigert):
        net.get_json("https://ris.example.invalid/oparl/body/persons")
    monkeypatch.setattr(config, "OPARL_BODY", "http://127.0.0.1:9/body")
    monkeypatch.setattr(net, "_OEFFNER", types.SimpleNamespace(open=lambda req, timeout: io.BytesIO(b'{"ok": 1}')))
    for url in ("https://overpass.example.invalid/api", "http://127.0.0.1:9/body/persons",
                "https://stadt-koeln.de.example.invalid/"):
        assert not abruf.stadt(url) and net.get_json(url) == {"ok": 1}, url


def test_adresse_ohne_schema_wird_nicht_gesendet(monkeypatch):
    """Ein links.next ohne gültiges Schema wird nicht gesendet (Art „adresse“, keine Sperre, kein Traceback)."""
    _nicht_lokal(monkeypatch)
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    monkeypatch.setattr(abruf._OEFFNER, "open", lambda *a, **k: pytest.fail("darf nicht senden"))
    vorher = abruf.statistik()["anfragen"]
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json("buergerinfo.example.invalid/oparl/papers?page=2")
    assert e.value.art == "adresse" and not sessionnet.moegliche_sperre(e.value)
    assert abruf.statistik()["anfragen"] == vorher


# --- Runde 7: Retry-After über die Nacht hinaus, Meldungen nach einem vollständigen Lauf, 12-Stunden-Regel nach jedem
# Abbruch, Fehler vor dem Senden, leeres links, Weiterleitungen in net.py, Seitengrenze je Lauf --------------------------

NACHT_0 = datetime(2026, 11, 9, 22, 15, tzinfo=timezone.utc)        # 23:15 Uhr Ortszeit, im Zeitfenster 23–1 Uhr


def _scheinuhr(monkeypatch, start=NACHT_0):
    """Scheinuhr für Zeitfenster, Retry-After und Zustand (abruf.uhr); `uhr.t` lässt sich weiterstellen."""
    uhr = types.SimpleNamespace(t=start)
    monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
    return uhr


def _nacht(n):
    """Lauf des Workflows in der n-ten Nacht nach NACHT_0 (22:10 UTC wie der Zeitplan in pages.yml)."""
    return datetime(2026, 11, 9, 22, 10, tzinfo=timezone.utc) + timedelta(days=n)


@pytest.mark.parametrize("wert, erste_nacht", [
    ("86400", 2),                               # nicht vor Nacht 1 22:15 UTC: der Lauf um 22:10 entfällt
    ("172800", 3),
    ("Wed, 11 Nov 2026 22:15:00 GMT", 3),       # HTTP-Datum, 48 h nach der Antwort
    ("14400", 1),                               # länger als die längste Pause, aber vor der nächsten Nacht abgelaufen
    ("999999999", 31),                          # begrenzt auf 30 Tage
    ("9" * 5000, 31),                           # mehr als 12 Ziffern: unendlich, begrenzt auf 30 Tage
    ("bald", 8)])                               # unlesbar: 7 Tage
def test_retry_after_gilt_ueber_die_nacht_hinaus(oparl, monkeypatch, wert, erste_nacht):
    """429 mit langem Retry-After: aufgegeben, `nicht_vor` im Zustand; bis dahin keine Anfrage (Scheinuhr über mehrere
    Nächte, echtes Zeitfenster 23–1 Uhr), danach wieder ein Abruf."""
    server = _lokaler_server(lambda methode, pfad: (429, {"Retry-After": wert}, b""))
    try:
        _nicht_lokal(monkeypatch)
        uhr = _scheinuhr(monkeypatch)
        gewartet = _scheinzeit(monkeypatch)
        monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
        sessionnet.fetch_all()
        assert len(server.anfragen) == 1 and gewartet == []
        nicht_vor = datetime.fromisoformat(json.loads(config.ZUSTAND.read_text())["nicht_vor"])
        assert nicht_vor <= NACHT_0 + timedelta(days=30)
        for n in range(1, erste_nacht):
            uhr.t = _nacht(n)
            sessionnet.fetch_all()
            assert len(server.anfragen) == 1 and gewartet == [], n
            assert "Retry-After" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
        uhr.t = _nacht(erste_nacht)
        sessionnet.fetch_all()
        # danach wieder ein Abruf (ein HTTP-Datum in der Vergangenheit gilt dann als 0: übliche Pausen)
        assert len(server.anfragen) >= 2
    finally:
        server.shutdown()
        server.server_close()


def test_retry_after_aus_dem_zustand_bleibt_bis_zum_spaeteren_zeitpunkt(oparl, monkeypatch):
    """Ein späteres gespeichertes `nicht_vor` wird von einem kürzeren Retry-After nicht verkürzt; ein vollständiger Lauf
    nach Ablauf entfernt es."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch)
    spaeter = (NACHT_0 + timedelta(days=5)).isoformat(timespec="seconds")
    sessionnet._zustand_setzen("nicht_vor", spaeter)
    e = abruf.Abbruch("aufgegeben", "aufgegeben", code=429, nicht_vor=NACHT_0 + timedelta(days=1))
    sessionnet._abbruch_vermerken(e, sessionnet._zustand())
    assert json.loads(config.ZUSTAND.read_text())["nicht_vor"] == spaeter
    uhr.t = _nacht(4)
    sessionnet.fetch_all()
    assert oparl.anfragen == []
    uhr.t = _nacht(5) + timedelta(minutes=10)
    sessionnet.fetch_all()
    assert oparl.anfragen and "nicht_vor" not in json.loads(config.ZUSTAND.read_text())


@pytest.mark.parametrize("wert, tage", [("kaputt", 7), ("2026-11-12T00:00:00", 7), (1762553400, 7), ("", 7),
                                        ("2999-01-01T00:00:00+00:00", 30)])
def test_unlesbares_nicht_vor(oparl, monkeypatch, capsys, wert, tage):
    """`nicht_vor` unlesbar, ohne Zone oder als Zahl: jetzt + 7 Tage; mehr als 30 Tage voraus: jetzt + 30 Tage; neu
    geschrieben und gemeldet, keine Anfrage."""
    _nicht_lokal(monkeypatch)
    _scheinuhr(monkeypatch)
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.ZUSTAND.write_text(json.dumps({"nicht_vor": wert}))
    sessionnet.fetch_all()
    assert oparl.anfragen == [] and "nicht_vor" in capsys.readouterr().err
    neu = datetime.fromisoformat(json.loads(config.ZUSTAND.read_text())["nicht_vor"])
    assert neu == NACHT_0 + timedelta(days=tage)


def test_meldungen_entfallen_nach_vollstaendigem_lauf(oparl, monkeypatch):
    """Abbruch, dann vollständiger Lauf: weder STAND.json noch index.json melden danach einen Fehler (die Seite zeigte
    sonst dauerhaft „Der letzte Abruf … ist fehlgeschlagen“); Hinweis und übersprungener Lauf entfallen ebenso."""
    from pipeline import export
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    assert "HTTP 404" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    sessionnet._stand_setzen(abruf_hinweis={"zeit": "2026-11-01T22:30:00+00:00", "meldung": "alt"},
                             abruf_uebersprungen={"zeit": "2026-11-02T22:30:00+00:00", "grund": "alt"})
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    sessionnet.fetch_all()
    stand = json.loads(config.STAND.read_text())
    assert "abruf_ok" in stand and not {"abruf_fehler", "abruf_hinweis", "abruf_uebersprungen"} & set(stand)
    assert not {"letzter_abbruch", "nicht_vor"} & set(json.loads(config.ZUSTAND.read_text()))
    build.build()
    export.export()
    assert json.loads((config.EXPORT / config.STADT / "index.json").read_text())["meta"]["abruf_fehler"] is None


def test_export_zeigt_nur_fehler_nach_dem_letzten_vollstaendigen_abruf():
    from pipeline import export
    fehler = {"zeit": "2026-11-08T22:30:00+00:00", "meldung": "HTTP 404"}
    assert export._abruf_fehler({"abruf_fehler": fehler, "abruf_ok": "2026-11-09T22:40:00+00:00"}) is None
    assert export._abruf_fehler({"abruf_fehler": fehler, "abruf_ok": "2026-11-07T22:40:00+00:00"}) == fehler
    assert export._abruf_fehler({"abruf_fehler": fehler}) == fehler
    assert export._abruf_fehler({"abruf_ok": "2026-11-07T22:40:00+00:00"}) is None
    kaputt = {"zeit": "gestern", "meldung": "x"}
    assert export._abruf_fehler({"abruf_fehler": kaputt, "abruf_ok": "2026-11-07T22:40:00+00:00"}) == kaputt


def _nach_seite(monkeypatch, seite, fehler, einmal=True):
    """abruf.get_json, das bei Seite `seite` der Vorlagen `fehler()` auslöst (nur beim ersten Mal, wenn `einmal`)."""
    echt, aktiv = abruf.get_json, {"ja": True}

    def get_json(url, pausen=None):
        if aktiv["ja"] and "/papers" in url and f"page={seite}" in url:
            aktiv["ja"] = not einmal
            raise fehler()
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)


def test_ende_des_zeitfensters_ist_kein_fehler(oparl, monkeypatch):
    """Vollabruf über mehrere Nächte: Das Ende des Zeitfensters ist ein neutraler Hinweis (kein „fehlgeschlagen“, ein
    älterer Fehler entfällt) und löst keine 12-Stunden-Regel aus."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch)
    sessionnet._stand_setzen(abruf_fehler={"zeit": "2026-11-08T22:30:00+00:00", "meldung": "älterer Fehler"})
    _nach_seite(monkeypatch, 2, lambda: abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster"))
    sessionnet.fetch_all()
    stand, zustand = json.loads(config.STAND.read_text()), json.loads(config.ZUSTAND.read_text())
    assert "abruf_fehler" not in stand and "nächsten Nacht" in stand["abruf_hinweis"]["meldung"]
    assert "letzter_abbruch" not in zustand and "sperre_verdacht" not in zustand and "papers_fortsetzung" in zustand
    uhr.t += timedelta(minutes=30)                         # dieselbe Nacht: erlaubt, setzt eine Seite zurück fort
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == [None, "2", "3"]
    assert "abruf_hinweis" not in json.loads(config.STAND.read_text())


@pytest.mark.parametrize("fall", ["programmfehler", "adresse", "http", "proxy", "leer"])
def test_kein_zweiter_lauf_in_derselben_nacht_nach_jedem_abbruch(oparl, monkeypatch, fall):
    """Nach jedem Abbruch außer dem Ende des Zeitfensters, auch nach einem Programmfehler und ohne Sperrverdacht, folgt
    in derselben Nacht (12 h) kein weiterer Lauf; in der nächsten Nacht wieder."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch)
    if fall == "programmfehler":
        monkeypatch.setattr(sessionnet, "beratungen", lambda papers, meetings, *weitere: {}["feld"])
    elif fall == "adresse":
        _nach_seite(monkeypatch, 2, lambda: abruf.Abbruch("ungültige Adresse", "adresse"), einmal=False)
    elif fall == "http":
        monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "2")
    elif fall == "proxy":
        _nach_seite(monkeypatch, 2, lambda: abruf.Abbruch("Ablehnung durch den Proxy", "proxy", code=403),
                    einmal=False)
    else:   # Vollabruf deutlich kleiner als der vorhandene Stand (Regel aus Bonn): Abbruch, kein Programmfehler
        sessionnet.fetch_all()
        oparl.papers[:] = oparl.papers[:1]
        monkeypatch.setenv("RATSATLAS_VOLLABRUF", "ja")
    if fall == "programmfehler":
        with pytest.raises(KeyError):
            sessionnet.fetch_all()
    else:
        sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert "sperre_verdacht" not in zustand
    assert zustand["letzter_abbruch"]["art"] == fall
    if fall == "leer":
        assert "nur 1 statt bisher 5" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    uhr.t += timedelta(minutes=40)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                 # dieselbe Nacht: übersprungen, keine Anfrage
    assert oparl.anfragen == []
    assert "derselben Nacht" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    uhr.t = _nacht(1)                                      # nächste Nacht (Scheinuhr)
    if fall == "programmfehler":
        monkeypatch.setattr(sessionnet, "beratungen", lambda papers, meetings, *weitere: None)
    sessionnet.fetch_all()                                 # nächste Nacht: wieder ein Abruf
    assert oparl.anfragen


@pytest.mark.parametrize("fehler", [RecursionError("zu tief"), RuntimeError("ohne Art")])
def test_runtimeerror_ohne_art_ist_programmfehler(oparl, monkeypatch, fehler):
    """Ein RuntimeError ohne Art (auch RecursionError) ist kein Abbruch: laut mit Traceback, kein Sperrverdacht."""
    def kaputt(papers, meetings, *weitere):
        raise fehler
    monkeypatch.setattr(sessionnet, "beratungen", kaputt)
    with pytest.raises(type(fehler)):
        sessionnet.fetch_all()
    assert "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())
    meldung = json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    assert meldung.startswith(f"Programmfehler ({type(fehler).__name__}")
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert z["ergebnis"] == "ok"                           # die Liste selbst war vollständig


def test_zu_tief_verschachtelte_antwort_ist_unlesbar(oparl, monkeypatch):
    """json.loads löst bei tief verschachteltem JSON RecursionError aus (kein ValueError): wie eine unlesbare Antwort
    (Pausen, danach aufgegeben, Nacht mit möglicher Sperre), kein stiller Abbruch ohne Art."""
    server = _lokaler_server(lambda methode, pfad: (200, {"Content-Type": "application/json"}, b"[" * 200000))
    try:
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/body", pausen=[0, 0])
        assert e.value.art == "aufgegeben" and "recursion" in str(e.value) and len(server.anfragen) == 3
        monkeypatch.setattr(config, "ABRUF_PAUSEN", [0, 0])
        monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
        sessionnet.fetch_all()                                   # kein Traceback
    finally:
        server.shutdown()
        server.server_close()
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["art"] == "aufgegeben"


def test_steuerzeichen_im_user_agent_bricht_laut_ab(oparl, monkeypatch):
    """Zeilenumbruch im User-Agent (etwa aus RATSATLAS_KONTAKT): ValueError vor der Anfrage, nicht gezählt, keine
    Pausen, keine Sperrnacht."""
    monkeypatch.setattr(config, "USER_AGENT", "ratsatlas-koeln/0.1 (kontakt@example.invalid\nX-Test: 1)")
    vorher = abruf.statistik()
    with pytest.raises(ValueError, match="Steuerzeichen"):
        abruf.get_json(f"{oparl.b}/body", pausen=[0, 0])
    assert abruf.statistik() == vorher and oparl.anfragen == []
    with pytest.raises(ValueError):
        sessionnet.fetch_all()
    assert oparl.anfragen == [] and "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())
    assert "Programmfehler (ValueError" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]


def test_kontakt_ohne_leerraum_am_rand():
    """RATSATLAS_KONTAKT mit Zeilenumbruch am Ende (Repository-Variable): ohne Leerraum im User-Agent."""
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_")},
           "RATSATLAS_SPERRE": os.environ["RATSATLAS_SPERRE"], "RATSATLAS_KONTAKT": " kontakt@example.invalid\n",
           "PYTHONPATH": str(config.ROOT)}
    r = subprocess.run([sys.executable, "-c", "from pipeline import config; print(config.USER_AGENT)"], env=env,
                       cwd=config.ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; kontakt@example.invalid)\n"


def test_valueerror_vor_dem_senden_ist_einstellungsfehler(monkeypatch):
    """Andere ValueError vor dem Senden (Kopfzeile, IDNA, Proxy-Adresse): laut weitergereicht, nicht gezählt, keine
    Pausen, nicht „unlesbar“. Keine Anfrage an fremde Server: Scheinöffner bzw. IDNA-Fehler vor jeder Namensauflösung."""
    _nicht_lokal(monkeypatch)
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    gewartet = _scheinzeit(monkeypatch)

    def kopf(req, timeout):
        raise ValueError("Invalid header value b'x\\r\\ny'")
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=kopf))
    vorher = abruf.statistik()
    with pytest.raises(ValueError, match="Invalid header value"):
        abruf.get_json("https://example.invalid/oparl/body", pausen=[0, 0])
    assert abruf.statistik() == vorher and gewartet == []
    monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)     # leeres Namensglied: UnicodeError vor der Namensauflösung
    with pytest.raises(UnicodeError):
        abruf.get_json("http://a..example.invalid/oparl/body", pausen=[0, 0])
    assert abruf.statistik() == vorher and gewartet == []


@pytest.mark.parametrize("url", ["htp://example.invalid/papers", "ftp://example.invalid/papers", "file:///etc/hostname",
                                 "http:///papers", "https:papers?page=2", "data:,{}", "http://example.invalid:99999/",
                                 "http://example.invalid:abc/papers"])
def test_schema_und_host_werden_vor_dem_senden_geprueft(monkeypatch, url):
    """Nur http und https mit Host und gültigem Port: sonst Art „adresse“, nicht gesendet, nicht gezählt, keine Sperre
    (vorher teils URLError = Art „sperre“, file: las eine lokale Datei)."""
    _nicht_lokal(monkeypatch)
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=lambda *a, **k: pytest.fail("nicht senden")))
    vorher = abruf.statistik()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json(url)
    assert e.value.art == "adresse" and "nicht gesendet" in str(e.value) and not sessionnet.moegliche_sperre(e.value)
    assert abruf.statistik()["anfragen"] == vorher["anfragen"]


def test_oeffner_kennt_nur_http_und_https():
    o = abruf.oeffner({})
    verboten = (urllib.request.FileHandler, urllib.request.FTPHandler, urllib.request.DataHandler,
                urllib.request.UnknownHandler)
    assert not any(isinstance(h, verboten) for h in o.handlers)
    assert not any(isinstance(h, verboten) for h in abruf._OEFFNER.handlers)
    assert o.open("file:///etc/hostname") is None and o.open("data:,{}") is None   # nichts gelesen


@pytest.mark.parametrize("links", ["fehlt", None, [], {}, "", {"next": None}, {"next": ""}, {"next": []}])
def test_leeres_links_ist_ende_der_liste(oparl, monkeypatch, links):
    """SessionNet (PHP) kann ein leeres Objekt als [] senden: leeres links oder links.next gilt als Ende der Liste, nicht
    als unlesbar (sonst Sperrnacht auf der letzten Seite und nie ein vollständiger Abruf)."""
    echt = oparl.liste

    def liste(objekte, pfad, q, groesse=2):
        seite = echt(objekte, pfad, q, groesse)
        if not seite["links"]:
            if links == "fehlt":
                del seite["links"]
            else:
                seite["links"] = links
        return seite
    monkeypatch.setattr(oparl, "liste", liste)
    sessionnet.fetch_all()
    stand = json.loads(config.STAND.read_text())
    assert "abruf_ok" in stand and "abruf_fehler" not in stand and len(_jsonl(config.PAPERS)) == 5
    assert "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())


def test_schreibfehler_der_statistik_in_der_liste_verdraengt_den_abbruch_nicht(oparl, monkeypatch, capsys):
    """Abbruch der Art `sperre` auf Seite 2 der Vorlagen und scheiternde Abrufstatistik: Nacht mit möglicher Sperre
    gezählt, Fortsetzung gespeichert, nur Warnungen (auch für die Zeilen body und organizations)."""
    def voll(zeile):
        raise OSError(28, "No space left on device")
    _nach_seite(monkeypatch, 2, lambda: abruf.Abbruch("Zeitüberschreitung, mögliche Sperre", "sperre"))
    monkeypatch.setattr(sessionnet, "_statistik", voll)
    sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["sperre_verdacht"]["naechte"] == 1 and zustand["papers_fortsetzung"]["seiten"] == 1
    assert capsys.readouterr().err.count("Abrufstatistik nicht geschrieben") == 3


def test_seitengrenze_gilt_je_lauf(oparl, monkeypatch):
    """RATSATLAS_MAX_OBJEKTE (in Seiten der tatsächlichen Größe) zählt die Seiten eines Laufs, nicht die einer
    Fortsetzung insgesamt (sonst begänne ein großer Vollabruf in einer späteren Nacht von vorn und würde nie fertig)."""
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 6)                     # 3 Seiten zu 2
    monkeypatch.setattr(sessionnet, "max_objekte_mindestens", lambda: 4)    # skaliert: 2 Seiten zu 2
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "2")
    sessionnet.fetch_all()                                   # Nacht 1: Seite 1, dann HTTP 404
    assert json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]["seiten"] == 1
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                   # Nacht 2: Seiten 1 (eine zurück), 2 und 3 in diesem Lauf
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == [None, "2", "3"]
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["seiten"], z["ergebnis"]) == ("voll, fortgesetzt", "4", "ok")
    # die Grenze gilt weiter je Lauf (unter der Gesamtgrenze, test_gesamtgrenze_der_seiten_ueber_fortsetzungen): ab der
    # vierten Seite dieses Laufs endet ein Vollabruf mit `obergrenze` (Fortsetzung in der nächsten Nacht, Runde 15), ein
    # inkrementeller Lauf mit `liste`
    monkeypatch.setattr(abruf, "get_json", lambda url, pausen=None: {"data": [{"id": url}, {"id": url + "b"}],
                                                                     "links": {"next": url + "x"}})
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?p", objekte=[{"id": "a"}], seiten=1)
    assert e.value.art == "obergrenze" and not sessionnet.moegliche_sperre(e.value)
    assert "Obergrenze je Nacht erreicht: 3 Seiten in diesem Lauf (6 Objekte bei 2 je Seite" in str(e.value)
    assert (e.value.seiten, e.value.naechste, e.value.zuletzt) == (4, "http://127.0.0.1/l?pxxx",
                                                                    "http://127.0.0.1/l?pxx")
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", seit="2026-11-01T00:00:00+00:00")
    assert e.value.art == "liste" and "mehr als 3 Seiten in einem inkrementellen Lauf" in str(e.value)


def test_net_prueft_das_ziel_einer_weiterleitung(monkeypatch):
    """pipeline/net.py folgt einer Weiterleitung nicht, wenn ihr Ziel eine Adresse der Stadt ist (hier ein lokaler
    Server auf 127.0.0.2 als eingestellte OParl-API), und wiederholt die Anfrage nicht; andere Ziele bleiben erlaubt."""
    from pipeline import net
    json_kopf = {"Content-Type": "application/json"}
    stadt = _lokaler_server(lambda methode, pfad: (200, json_kopf, b'{"stadt": 1}'), "127.0.0.2")
    ziele = {"/stadt": f"{stadt.url}/oparl/persons", "/weiter": "/ziel"}
    start = _lokaler_server(lambda methode, pfad: (302, {"Location": ziele[pfad]}, b"") if pfad in ziele
                            else (200, json_kopf, b'{"ok": 2}'))
    try:
        monkeypatch.setattr(config, "OPARL_BODY", f"{stadt.url}/oparl/body")
        monkeypatch.setattr(net, "_OEFFNER", net._oeffner({}))
        monkeypatch.setattr(net, "time", types.SimpleNamespace(sleep=lambda s: pytest.fail("keine Wiederholung")))
        assert abruf.stadt(f"{stadt.url}/x") and not abruf.stadt(f"{start.url}/x")
        with pytest.raises(net.AbrufVerweigert, match="pipeline/abruf.py"):
            net.get_json(f"{start.url}/stadt")
        assert start.anfragen == [("GET", "/stadt")] and stadt.anfragen == []
        assert net.get_json(f"{start.url}/weiter") == {"ok": 2}
        assert start.anfragen[1:] == [("GET", "/weiter"), ("GET", "/ziel")]
    finally:
        for server in (stadt, start):
            server.shutdown()
            server.server_close()


# --- Runde 8: unlesbares Ziel einer Weiterleitung, Prüfung von letzter_abbruch, Fehleranzeige im Export, zu tief
# verschachtelter Zustand, Retry-After auf dem letzten Versuch, Gesamtgrenze der Seiten über Fortsetzungen -------------

WEITERLEITUNGEN = [301, 302, 303, 307, 308]


@pytest.mark.parametrize("code", WEITERLEITUNGEN)
@pytest.mark.parametrize("ort", ["http://[::1", "http://[blocked]/"])
def test_weiterleitung_mit_unlesbarem_ziel(oparl, monkeypatch, ort, code):
    """3xx mit unlesbarem Location-Kopf: Die Anfrage hat die Gegenseite erreicht und wird gezählt; Art
    `weiterleitung` mit dem Ziel im Rohtext (kein ValueError als Programmfehler), Nacht mit möglicher Sperre."""
    server = _lokaler_server(lambda methode, pfad: (code, {"Location": ort}, b""))
    try:
        monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
        vorher = abruf.statistik()
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/body", pausen=[0, 0])
        assert (e.value.art, e.value.code, e.value.ziel) == ("weiterleitung", code, ort) and ort in str(e.value)
        assert sessionnet.moegliche_sperre(e.value) and server.anfragen == [("GET", "/body")]
        nachher = abruf.statistik()
        assert {k: nachher[k] - vorher[k] for k in ("anfragen", "fehler", "weiterleitungen")} == \
            {"anfragen": 1, "fehler": 1, "weiterleitungen": 1}
        monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
        sessionnet.fetch_all()                                   # kein Traceback
    finally:
        server.shutdown()
        server.server_close()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["sperre_verdacht"]["art"] == zustand["letzter_abbruch"]["art"] == "weiterleitung"
    z = [r for r in _statistik() if r["liste"] == "body"][-1]
    assert (z["anfragen"], z["weiterleitungen"]) == ("1", "1") and z["ergebnis"].startswith("abbruch: Weiterleitung")


@pytest.mark.parametrize("code", WEITERLEITUNGEN)
@pytest.mark.parametrize("ort", ["http://[::1", "http://[blocked]/"])
def test_net_bricht_bei_unlesbarem_ziel_ohne_wiederholung_ab(monkeypatch, ort, code):
    """pipeline/net.py: Ein unlesbares Ziel einer Weiterleitung (alle 3xx-Codes) gilt vorsichtshalber als Adresse
    der Stadt (AbrufVerweigert); eine Anfrage, keine Wiederholung, kein ValueError."""
    from pipeline import net
    server = _lokaler_server(lambda methode, pfad: (code, {"Location": ort}, b""))
    try:
        monkeypatch.setattr(net, "_OEFFNER", net._oeffner({}))
        monkeypatch.setattr(net, "time", types.SimpleNamespace(sleep=lambda s: pytest.fail("keine Wiederholung")))
        with pytest.raises(net.AbrufVerweigert, match="unlesbarem Ziel"):
            net.get_json(f"{server.url}/x")
        assert server.anfragen == [("GET", "/x")]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("eintrag", [
    {"zuletzt": "2026-11-09T23:10:00", "art": "http"},           # ohne Zone
    {"zuletzt": "kaputt", "art": "http"}, {"zuletzt": 1762726500}, {"zuletzt": None}, {"art": "proxy"},
    {"zuletzt": "2999-01-01T00:00:00+00:00", "art": "http"},     # in der Zukunft
    "kaputt", ["2026-11-09T22:00:00+00:00"], 5])                 # kein Objekt
def test_unlesbarer_oder_kuenftiger_letzter_abbruch_gilt_als_jetzt(oparl, monkeypatch, capsys, eintrag):
    """12-Stunden-Regel nach jedem Abbruch: ein unlesbarer, zonenloser, fehlender oder künftiger Zeitpunkt und ein
    Eintrag, der kein Objekt ist, gelten als „jetzt“ (in dieser Nacht keine Anfrage), werden neu geschrieben und
    gemeldet; kein Traceback, keine Dauersperre (in der nächsten Nacht wieder ein Abruf)."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch)
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.ZUSTAND.write_text(json.dumps({"letzter_abbruch": eintrag}))
    sessionnet.fetch_all()
    assert oparl.anfragen == []
    assert "derselben Nacht" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    neu = json.loads(config.ZUSTAND.read_text())["letzter_abbruch"]
    assert neu["zuletzt"] == NACHT_0.isoformat(timespec="seconds")
    assert "letzter_abbruch" in capsys.readouterr().err
    uhr.t = _nacht(1)
    sessionnet.fetch_all()
    assert oparl.anfragen and "abruf_ok" in json.loads(config.STAND.read_text())


def test_export_zeigt_im_index_nur_fehler_nach_dem_letzten_vollstaendigen_abruf(oparl):
    """index.json (meta.abruf_fehler) aus STAND.json: ein Fehler vor dem letzten vollständigen Abruf entfällt, ein
    späterer wird gezeigt."""
    from pipeline import export
    sessionnet.fetch_all()
    build.build()
    fehler = {"zeit": "2026-11-08T22:30:00+00:00", "meldung": "HTTP 404"}
    for ok, erwartet in (("2026-11-09T22:40:00+00:00", None), ("2026-11-07T22:40:00+00:00", fehler)):
        sessionnet._stand_setzen(abruf_fehler=fehler, abruf_ok=ok)
        export.export()
        assert json.loads((config.EXPORT / config.STADT / "index.json").read_text())["meta"]["abruf_fehler"] == erwartet


def test_zu_tief_verschachtelter_zustand_bricht_ohne_anfrage_ab(oparl):
    """zustand_abruf.json zu tief verschachtelt (json.loads: RecursionError): ZustandUnlesbar, keine Anfrage, Fehler in
    STAND.json, Datei unverändert."""
    inhalt = "[" * 100000 + "]" * 100000
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.ZUSTAND.write_text(inhalt, encoding="utf-8")
    with pytest.raises(sessionnet.ZustandUnlesbar):
        sessionnet.fetch_all()
    assert oparl.anfragen == [] and config.ZUSTAND.read_text(encoding="utf-8") == inhalt
    assert "keine Anfrage" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]


@pytest.mark.parametrize("pausen, antworten", [
    ([], [(429, {"Retry-After": "bald"}, b"")]),
    ([0], [(429, {}, b""), (429, {"Retry-After": "bald"}, b"")]),
    ([0], [(503, {}, b""), (429, {"Retry-After": "Wed, 32 Oct 2026 07:28:00 GMT"}, b"")])])
def test_unlesbarer_retry_after_auf_dem_letzten_versuch(monkeypatch, pausen, antworten):
    """Unlesbarer Retry-After auf dem letzten Versuch (auch ganz ohne Pausen): aufgegeben mit `nicht_vor` = jetzt +
    7 Tage, wie auf einem früheren Versuch."""
    antworten = iter(antworten)
    server = _lokaler_server(lambda methode, pfad: next(antworten))
    try:
        monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
        _nicht_lokal(monkeypatch)
        _scheinuhr(monkeypatch)
        gewartet = _scheinzeit(monkeypatch)
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/body", pausen=pausen)
        assert (e.value.art, e.value.code) == ("aufgegeben", 429) and len(server.anfragen) == len(pausen) + 1
        assert e.value.nicht_vor == NACHT_0 + abruf.RETRY_AFTER_UNLESBAR and gewartet == pausen
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("rest", [1, 2])
def test_gesamtgrenze_der_seiten_ueber_fortsetzungen(oparl, monkeypatch, rest):
    """Ein Vollabruf über Fortsetzungen hinweg liest höchstens ABRUF_MAX_OBJEKTE_GESAMT / g Seiten (Schutz gegen eine
    Liste, die endlos neue Kennungen erzeugt): danach Art `liste`, Fortsetzung verworfen, Listenfehler. Geprüft ab der
    zweiten Anfrage eines Laufs (vorher ist die Seitengröße unbekannt) und vor der Grenze je Lauf: Erreicht der Lauf
    beide zugleich (`rest` 2, die Grenze je Lauf ist 2 Seiten), gilt die Gesamtgrenze (keine Fortsetzung)."""
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 4)                     # 2 Seiten zu 2 je Lauf
    monkeypatch.setattr(sessionnet, "max_objekte_mindestens", lambda: 4)    # skaliert: 2 Seiten zu 2
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE_GESAMT", 12)             # 6 Seiten zu 2 insgesamt
    gesamt = 6
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    config.RAW.mkdir(parents=True, exist_ok=True)
    teil = config.RAW / "papers.teil.jsonl"
    teil.write_text("".join(json.dumps(p) + "\n" for p in oparl.papers[:2]))
    config.ZUSTAND.write_text(json.dumps({"papers_fortsetzung": {
        "naechste": f"{oparl.b}/papers?page=2", "seiten": gesamt - rest, "start": "2026-11-08T22:10:00+00:00"}}))
    sessionnet.fetch_all()
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["2", "3"][:rest]   # dann Schluss
    zustand = json.loads(config.ZUSTAND.read_text())
    assert "papers_fortsetzung" not in zustand and not teil.exists()
    assert zustand["listenfehler"]["naechte"] == 1 and zustand["letzter_abbruch"]["art"] == "liste"
    assert "sperre_verdacht" not in zustand
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert z["seiten"] == str(gesamt) and f"mehr als {gesamt} Seiten insgesamt" in z["ergebnis"]
    assert "fehlerhaften Liste" in json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"]


# --- Runde 9: Zertifikatsprüfung (Art `tls`), Kölner Antwortform aus Stufe 1 (ohne Gesamtzahlen, neueste zuerst) ------

def _tls_bereit(monkeypatch):
    """Adressen mit https auf 127.0.0.1 gelten nicht als lokal: Freigabe, Zeitfenster offen, Mindestabstand 0 (nur hier,
    um die Tests kurz zu halten), Öffner ohne Proxy, Kontakt im User-Agent."""
    monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")


def test_zertifikatsfehler_ist_keine_sperre_und_keine_anfrage(oparl, monkeypatch, capsys, tls_server):
    """Selbst signiertes Zertifikat, dem der Client nicht vertraut: Art `tls` ohne Wiederholung, keine HTTP-Anfrage beim
    Server, gezählt als Fehler und nicht als Anfrage. Im Lauf: Warnung (laut), Fehler in STAND.json, `letzter_abbruch`
    mit Art `tls` (12-Stunden-Regel), keine Nacht mit möglicher Sperre."""
    _tls_bereit(monkeypatch)
    vorher = abruf.statistik()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json(f"{tls_server.url}/body", pausen=[0, 0])
    assert e.value.art == "tls" and "CERTIFICATE_VERIFY_FAILED" in str(e.value) and "mögliche Sperre" not in str(e.value)
    assert "Vermutlich eine Einstellung der Ausführungsumgebung" in str(e.value)
    assert not sessionnet.moegliche_sperre(e.value) and tls_server.anfragen == []
    nachher = abruf.statistik()
    assert (nachher["anfragen"] - vorher["anfragen"], nachher["fehler"] - vorher["fehler"],
            nachher["wiederholungen"] - vorher["wiederholungen"]) == (0, 1, 0)
    monkeypatch.setattr(config, "OPARL_BODY", f"{tls_server.url}/body")
    sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["letzter_abbruch"]["art"] == "tls" and "sperre_verdacht" not in zustand
    assert "listenfehler" not in zustand
    assert "Zertifikatsprüfung" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    err = capsys.readouterr().err
    assert "Zertifikatsprüfung fehlgeschlagen (1. Nacht" in err and "vermutlich eine Einstellung" in err
    assert "Sperrseite nicht ausgeschlossen" in err and zustand["tlsfehler"]["naechte"] == 1
    z = [r for r in _statistik() if r["liste"] == "body"][-1]
    assert (z["anfragen"], z["fehler"], z["wiederholungen"]) == ("0", "1", "0")
    sessionnet.fetch_all()                                                # dieselbe Nacht: kein weiterer Lauf
    assert "Abbruch (tls)" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
    assert tls_server.anfragen == []


def test_zertifikatsfehler_ohne_urlerror(monkeypatch):
    """ssl.SSLCertVerificationError ist auch ein ValueError: auch ungekapselt Art `tls`, kein Einstellungsfehler mit
    Traceback; nicht als Anfrage gezählt (Scheinöffner, kein Netz)."""
    def oeffnen(req, timeout=None):
        raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=oeffnen))
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    vorher = abruf.statistik()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json("http://127.0.0.1:9/body", pausen=[0, 0])
    assert e.value.art == "tls" and abruf.statistik()["anfragen"] == vorher["anfragen"]


@pytest.mark.parametrize("reset", [False, True])
def test_andere_tls_fehler_sind_moegliche_sperre(oparl, monkeypatch, abbrechender_server, reset):
    """Handshake endet unerwartet (SSLEOFError) oder wird zurückgesetzt: mögliche Sperre, keine Wiederholung."""
    server = abbrechender_server(reset)
    _tls_bereit(monkeypatch)
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json(f"{server.url}/body", pausen=[0, 0])
    assert e.value.art == "sperre" and sessionnet.moegliche_sperre(e.value) and len(server.verbindungen) == 1


def _koeln_seite(oparl, pfad, abfrage=""):
    """Eine Listenseite des Testservers in Kölner Form (direkt, ohne Abrufpolitik)."""
    with OHNE_PROXY.open(f"{oparl.b}{pfad}" + (f"?{abfrage}" if abfrage else ""), timeout=10) as r:
        return json.loads(r.read())


def test_koelner_form_vollabruf_ohne_gesamtzahlen(oparl, monkeypatch):
    """Ohne totalElements und totalPages, neueste zuerst: Vollabruf, Mengenprüfung beim zweiten Vollabruf und Statistik
    ohne falsche Sperre und ohne falschen Abbruch."""
    oparl.form = "koeln"
    seite = _koeln_seite(oparl, "/papers")
    assert seite["pagination"] == {"elementsPerPage": 2, "currentPage": 1} and sorted(seite["links"]) == [
        "first", "next", "self"]
    assert [p["id"].rsplit("/", 1)[1] for p in seite["data"]] == ["5", "4"]   # neueste zuerst
    sessionnet.fetch_all()
    assert sorted(p["id"] for p in _jsonl(config.PAPERS)) == sorted(p["id"] for p in oparl.papers)
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "ja")
    sessionnet.fetch_all()                                                 # Mengenprüfung (90 %) ohne Gesamtzahlen
    zustand = json.loads(config.ZUSTAND.read_text())
    assert not {"sperre_verdacht", "listenfehler", "letzter_abbruch"} & set(zustand)
    assert "abruf_fehler" not in json.loads(config.STAND.read_text())
    z = [r for r in _statistik() if r["liste"] == "papers"]
    assert [(r["modus"], r["seiten"], r["objekte"], r["ergebnis"]) for r in z] == [("voll", "3", "5", "ok")] * 2


def test_koelner_form_fortsetzung_mit_seitenverschiebung(oparl, monkeypatch):
    """Neueste zuerst, Vollabruf über zwei Nächte: Zwischen den Nächten kommen vier Vorlagen hinzu und verschieben die
    Seiten. Die Fortsetzung beginnt eine Seite zurück (Seite 2, jetzt mit zwei neuen Vorlagen); die Seiten 3 und 4
    bringen nur schon gelesene Vorlagen (keine Schleife, kein Listenfehler), Doppelungen werden zusammengeführt; die
    übrigen neuen Vorlagen holt der nächste inkrementelle Lauf (ohne Löschungen geht so keine verloren)."""
    oparl.form = "koeln"
    _nach_seite(monkeypatch, 3, lambda: abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster"))
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–2 (5, 4, 3, 2)
    fort = json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]
    assert fort["seiten"] == 2 and fort["naechste"].endswith("/papers?page=2")
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    oparl.papers += [oparl.paper(i, modified=jetzt) for i in range(6, 10)]   # neue Vorlagen am Listenanfang
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Fortsetzung ab Seite 2
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["2", "3", "4", "5"]
    ids = [p["id"] for p in _jsonl(config.PAPERS)]
    assert len(ids) == len(set(ids)) == 7                                   # 5, 4, 3, 2 doppelt gelesen, einmal gespeichert
    zustand = json.loads(config.ZUSTAND.read_text())
    assert not {"sperre_verdacht", "listenfehler", "letzter_abbruch", "papers_fortsetzung"} & set(zustand)
    z = [r for r in _statistik() if r["liste"] == "papers"]
    assert (z[-1]["modus"], z[-1]["seiten"], z[-1]["objekte"], z[-1]["ergebnis"]) == ("voll, fortgesetzt", "6", "7", "ok")
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 3: inkrementell
    assert all("modified_since" in q for p, q, _ in oparl.anfragen if p == "/papers")
    assert sorted(p["id"] for p in _jsonl(config.PAPERS)) == sorted(p["id"] for p in oparl.papers)   # alle 9


def test_fortsetzung_eine_seite_zurueck_faengt_loeschungen_ab(oparl, monkeypatch):
    """Zwischen zwei Nächten werden zwei schon gelesene Vorlagen gelöscht (aus der Liste entfernt): Die folgenden rücken
    eine Seite nach vorn. Weil die Fortsetzung eine Seite zurück beginnt, fehlt keine (bis zu einer Seite Löschungen)."""
    oparl.form = "koeln"
    oparl.papers = [oparl.paper(i) for i in range(1, 8)]                  # Seiten 7, 6 | 5, 4 | 3, 2 | 1
    _nach_seite(monkeypatch, 3, lambda: abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster"))
    sessionnet.fetch_all()                                                 # Nacht 1: 7, 6, 5, 4
    oparl.papers = [p for p in oparl.papers if not p["id"].endswith(("/7", "/6"))]   # jetzt 5, 4 | 3, 2 | 1
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: ab Seite 2 (3, 2), dann 1
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["2", "3"]
    gespeichert = {p["id"].rsplit("/", 1)[1] for p in _jsonl(config.PAPERS)}
    assert {"1", "2", "3"} <= gespeichert                                  # ab Seite 3 wären 3 und 2 übersprungen


def _verschiebung_in_seiten(monkeypatch, groesse):
    """Seitenverschiebung wie vor Runde 14 in Seiten: 4 Seiten je Tag, höchstens 40 (in Vorlagen 4 bzw. 40 × `groesse`;
    die Vorgabe von 100 bzw. 1000 Vorlagen ergibt bei 25 je Seite dasselbe)."""
    monkeypatch.setattr(sessionnet, "VERSCHIEBUNG_JE_TAG", 4 * groesse)
    monkeypatch.setattr(sessionnet, "VERSCHIEBUNG_HOECHSTENS", 40 * groesse)


@pytest.mark.parametrize("tage, ergebnis", [(9.5, "ok"), (3.5, "liste")])
def test_seitenverschiebung_ueber_mehrere_tage(oparl, monkeypatch, tage, ergebnis):
    """Neueste zuerst, 5 je Seite: Nacht 1 liest 20 Seiten (110 bis 11), dann ausgelassene Nächte mit 9 neuen Vorlagen je
    Tag (90). Die Fortsetzung (ab Seite 20) bringt 19 Seiten nur schon gelesener Vorlagen. Erlaubt sind 4 Seiten je
    angefangenem Tag seit `gespeichert`: nach 10 Tagen 40 (Lauf vollständig, die neuen Vorlagen holt der inkrementelle
    Lauf), nach 4 Tagen 16 (Abbruch der Art `liste`); mit fest 4 Seiten bräche auch der erste Fall ab."""
    oparl.form, oparl.groesse = "koeln", 5
    _verschiebung_in_seiten(monkeypatch, 5)
    oparl.papers = [oparl.paper(i) for i in range(1, 111)]
    _nach_seite(monkeypatch, 21, lambda: abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster"))
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–20
    z = json.loads(config.ZUSTAND.read_text())
    assert (z["papers_fortsetzung"]["seiten"], z["papers_fortsetzung"]["naechste"][-8:]) == (20, "?page=20")
    z["papers_fortsetzung"]["gespeichert"] = (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat(
        timespec="seconds")
    config.ZUSTAND.write_text(json.dumps(z))
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    oparl.papers += [oparl.paper(i, modified=jetzt) for i in range(111, 201)]   # 9 je Tag an 10 Tagen
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Fortsetzung ab Seite 20
    seiten = [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"]
    zustand = json.loads(config.ZUSTAND.read_text())
    if ergebnis == "ok":
        assert seiten == [str(n) for n in range(20, 41)]                    # 19 verschobene Seiten, dann 10 bis 1
        assert not {"listenfehler", "letzter_abbruch", "papers_fortsetzung"} & set(zustand)
        assert len(_jsonl(config.PAPERS)) == 110
        sessionnet.fetch_all()                                             # Nacht 3: inkrementell, die 90 neuen
        assert len(_jsonl(config.PAPERS)) == 200
    else:
        assert seiten == [str(n) for n in range(20, 37)]                    # 16 erlaubt, die 17. bricht ab
        assert zustand["listenfehler"]["naechte"] == 1 and "papers_fortsetzung" not in zustand
        z = [r for r in _statistik() if r["liste"] == "papers"][-1]
        assert "mehr als 16 Seiten ohne neue Kennungen in der Fortsetzung" in z["ergebnis"]


def test_echte_schleife_auch_in_der_fortsetzung(monkeypatch):
    """In einer Fortsetzung bleibt eine Schleife eine Schleife: eine Seite, deren Kennungen alle schon in diesem Lauf
    kamen (auch mit neuem links.next), und eine wiederholte Adresse; die erlaubte Verschiebung (hier 40) gilt nur für
    Seiten mit Vorlagen aus früheren Nächten und ist begrenzt."""
    seiten = iter(range(3, 100))
    abrufe = []

    def get_json(url, pausen=None):
        abrufe.append(url)
        return {"data": [{"id": "x/1"}, {"id": "x/2"}], "links": {"next": f"http://127.0.0.1/l?page={next(seiten)}"}}
    monkeypatch.setattr(abruf, "get_json", get_json)
    alt = [{"id": "x/1"}, {"id": "x/2"}]
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?page=2", objekte=alt, seiten=1, verschiebung=40)
    assert e.value.art == "liste" and "im Kreis" in str(e.value) and len(abrufe) == 2
    # wiederholte Adresse
    abrufe.clear()
    monkeypatch.setattr(abruf, "get_json", lambda url, pausen=None: abrufe.append(url) or {
        "data": [{"id": f"y/{len(abrufe)}"}], "links": {"next": "http://127.0.0.1/l?page=2"}})
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?page=2", objekte=alt, seiten=1, verschiebung=40)
    assert e.value.art == "liste" and "bereits gelesene Seite" in str(e.value) and len(abrufe) == 1
    # nach einer Seite mit neuen Kennungen dieselbe Seite noch einmal: sofort Schleife
    abrufe.clear()
    monkeypatch.setattr(abruf, "get_json", lambda url, pausen=None: abrufe.append(url) or {
        "data": [{"id": "x/3"}], "links": {"next": f"http://127.0.0.1/l?page={next(seiten)}"}})
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?page=2", objekte=alt, seiten=1, verschiebung=40)
    assert e.value.art == "liste" and len(abrufe) == 2
    # verschiedene Seiten aus früheren Nächten: bis zur erlaubten Verschiebung, dann Abbruch
    abrufe.clear()
    alt = [{"id": f"z/{n}"} for n in range(10)]
    monkeypatch.setattr(abruf, "get_json", lambda url, pausen=None: abrufe.append(url) or {
        "data": [{"id": f"z/{len(abrufe)}"}], "links": {"next": f"http://127.0.0.1/l?page={next(seiten)}"}})
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?page=2", objekte=alt, seiten=1, verschiebung=3)
    assert e.value.art == "liste" and "mehr als 3 Seiten ohne neue Kennungen" in str(e.value) and len(abrufe) == 4
    # ohne Fortsetzung gilt der Schutz sofort
    abrufe.clear()
    monkeypatch.setattr(abruf, "get_json", get_json)
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l")
    assert e.value.art == "liste" and len(abrufe) == 2


def test_verschiebung_je_angefangenem_tag():
    jetzt = datetime(2026, 11, 9, 22, 15, tzinfo=timezone.utc)
    for gespeichert, vorlagen in ((None, 100), ("gestern", 100), ("2026-11-09T22:00:00", 100),   # fehlt, unlesbar, ohne
                                  ((jetzt + timedelta(hours=1)).isoformat(), 100),                # Zone; in der Zukunft
                                  ((jetzt - timedelta(hours=12)).isoformat(), 100),
                                  ((jetzt - timedelta(hours=25)).isoformat(), 200),
                                  ((jetzt - timedelta(days=9, hours=12)).isoformat(), 1000),
                                  ((jetzt - timedelta(days=30)).isoformat(), 1000)):             # höchstens 1000
        assert sessionnet.verschiebung_erlaubt(gespeichert, jetzt) == vorlagen, gespeichert


def test_tls_naechte_pausieren_sieben_tage(oparl, monkeypatch):
    """Gescheiterte Zertifikatsprüfung: keine Sperrnacht, aber gezählt (`tlsfehler`, Nächte, nicht Läufe); nach drei
    Nächten ohne vollständigen Lauf sieben Tage Pause ohne Anfrage; ein vollständiger Lauf setzt den Zähler zurück."""
    versuche = []

    def oeffnen(req, timeout=None):
        versuche.append(req.full_url)
        raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=oeffnen))
    uhr = _scheinuhr(monkeypatch)
    for nacht in range(1, 4):
        for _ in range(2 if nacht == 1 else 1):                            # zwei Läufe in einer Nacht (lokal erlaubt)
            sessionnet.fetch_all()
        zustand = json.loads(config.ZUSTAND.read_text())
        assert zustand["tlsfehler"]["naechte"] == nacht and "sperre_verdacht" not in zustand
        uhr.t += timedelta(days=1)
    n = len(versuche)
    sessionnet.fetch_all()                                                 # vierte Nacht: Pause, kein Versuch
    assert len(versuche) == n and "Zertifikatsprüfung" in json.loads(config.STAND.read_text())["abruf_uebersprungen"][
        "grund"]
    uhr.t += timedelta(days=7)
    monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
    sessionnet.fetch_all()                                                 # nach der Pause: vollständig, Zähler weg
    assert "tlsfehler" not in json.loads(config.ZUSTAND.read_text()) and len(_jsonl(config.PAPERS)) == 5


# --- Runde 11: `gespeichert` bleibt, solange eine Fortsetzung die verschobene Zone nicht verlassen hat ------------------

def _vorlagenseite_stoert(monkeypatch, stoerungen):
    """abruf.get_json, das für die Vorlagenseite mit genau dieser Nummer (Parameter `page`, ohne: 1) einmal
    `stoerungen[nummer]()` auslöst."""
    echt = abruf.get_json

    def get_json(url, pausen=None):
        teile = urllib.parse.urlsplit(url)
        seite = dict(x.partition("=")[::2] for x in teile.query.split("&") if x).get("page", "1")
        if teile.path.endswith("/papers") and seite in stoerungen:
            raise stoerungen.pop(seite)()
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)


def _neue_vorlagen(oparl, anzahl):
    """`anzahl` neue Vorlagen am Listenanfang (neueste zuerst), jetzt geändert."""
    start = max(int(p["id"].rsplit("/", 1)[1]) for p in oparl.papers) + 1
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    oparl.papers += [oparl.paper(i, modified=jetzt) for i in range(start, start + anzahl)]


def _ende_fenster():
    return abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster")


def _zeitueberschreitung():
    return abruf.Abbruch("Zeitüberschreitung oder Verbindungsabbruch, mögliche Sperre", "sperre")


@pytest.mark.parametrize("abbruch_bei, bleibt", [("30", True), ("31", True), ("51", False)])
def test_gespeichert_bleibt_in_der_verschobenen_zone(oparl, monkeypatch, abbruch_bei, bleibt):
    """Neueste zuerst, 5 je Seite: Nacht 1 liest 30 Seiten (200 bis 51) und bricht ab; 12 Tage ohne Lauf mit 8 neuen
    Vorlagen je Tag (96: die Seiten 30–49 bringen nur schon gelesene). Nacht 2 bricht vor der ersten Seite (Anfrage an
    Seite 30), nach der ersten (Seite 31) oder erst nach der ersten Seite mit neuen Kennungen ab (Seite 51): In den
    ersten beiden Fällen bleibt `gespeichert` bei Nacht 1, sonst gilt Nacht 2. Nacht 3 (8 weitere) ist vollständig, ohne
    Listenfehler; mit `gespeichert` aus Nacht 2 erlaubte sie in den ersten Fällen nur 4 statt der nötigen 21 verschobenen
    Seiten."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 5
    _verschiebung_in_seiten(monkeypatch, 5)
    oparl.papers = [oparl.paper(i) for i in range(1, 201)]
    _vorlagenseite_stoert(monkeypatch, {"31": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–30
    fort = json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]
    assert (fort["seiten"], fort["naechste"][-8:], fort["gespeichert"]) == (30, "?page=30", _nacht(0).isoformat())
    _neue_vorlagen(oparl, 12 * 8)                                          # 12 Tage ohne Lauf, 8 neue je Tag
    uhr.t = _nacht(12)
    _vorlagenseite_stoert(monkeypatch, {abbruch_bei: _zeitueberschreitung})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Abbruch
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == [str(n) for n in range(30, int(abbruch_bei))]
    zustand = json.loads(config.ZUSTAND.read_text())
    fort = zustand["papers_fortsetzung"]
    assert fort["gespeichert"] == (_nacht(0) if bleibt else _nacht(12)).isoformat()
    assert fort["naechste"].endswith(f"?page={max(30, int(abbruch_bei) - 1)}")
    assert zustand["sperre_verdacht"]["naechte"] == 1 and "listenfehler" not in zustand
    _neue_vorlagen(oparl, 8)
    uhr.t = _nacht(13)
    sessionnet.fetch_all()                                                 # Nacht 3: vollständig
    zustand = json.loads(config.ZUSTAND.read_text())
    assert not {"listenfehler", "letzter_abbruch", "sperre_verdacht", "papers_fortsetzung"} & set(zustand)
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll, fortgesetzt", "ok")
    assert len(_jsonl(config.PAPERS)) == 200                               # die neuen holt der inkrementelle Lauf


def test_gespeichert_bleibt_nach_retry_after_von_30_tagen(oparl, monkeypatch):
    """Nacht 1 liest 40 Seiten (250 bis 51) und gibt nach 429 mit Retry-After von 30 Tagen auf (`nicht_vor`); bis dahin
    keine Anfrage, 6 neue Vorlagen je Tag. Nacht 2 (Tag 30, 180 neue) bricht nach 3 Seiten in der verschobenen Zone ab:
    `gespeichert` bleibt bei Nacht 1. Nacht 3 (186 neue) bringt 36 verschobene Seiten (erlaubt 40, mit `gespeichert` aus
    Nacht 2 nur 4) und ist vollständig."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 5
    _verschiebung_in_seiten(monkeypatch, 5)
    oparl.papers = [oparl.paper(i) for i in range(1, 251)]
    _vorlagenseite_stoert(monkeypatch, {"41": lambda: abruf.Abbruch(
        "aufgegeben nach HTTP 429 (Retry-After 30 Tage)", "aufgegeben", code=429,
        nicht_vor=_nacht(0) + timedelta(days=30))})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–40, dann aufgegeben
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["papers_fortsetzung"]["seiten"] == 40 and "nicht_vor" in zustand
    for tag in range(1, 30):
        _neue_vorlagen(oparl, 6)
        uhr.t = _nacht(tag)
        oparl.anfragen.clear()
        sessionnet.fetch_all()                                             # Retry-After: übersprungen
        assert oparl.anfragen == [], tag
    _neue_vorlagen(oparl, 6)
    uhr.t = _nacht(30)
    _vorlagenseite_stoert(monkeypatch, {"43": _ende_fenster})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Seiten 40–42, Ende des Fensters
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["40", "41", "42"]
    fort = json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]
    assert fort["gespeichert"] == _nacht(0).isoformat() and fort["naechste"].endswith("?page=42")
    _neue_vorlagen(oparl, 6)
    uhr.t = _nacht(31)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 3: vollständig
    zustand = json.loads(config.ZUSTAND.read_text())
    assert not {"listenfehler", "papers_fortsetzung"} & set(zustand)
    assert [r for r in _statistik() if r["liste"] == "papers"][-1]["ergebnis"] == "ok"
    seiten = [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"]
    assert seiten[0] == "42" and len(_jsonl(config.PAPERS)) == 250


def test_gespeichert_bleibt_bei_neuen_vorlagen_vor_der_verschobenen_zone(oparl, monkeypatch):
    """Mehr neue Vorlagen, als vor der Stelle der Fortsetzung lagen: Nacht 1 liest nur 15 Seiten (200 bis 126), dann 12
    Tage mit 8 neuen je Tag (96). In Nacht 2 bringen die ersten Seiten der Fortsetzung (ab Seite 15) neue Vorlagen, erst
    danach folgen 14 Seiten nur schon gelesener. Bricht Nacht 2 nach 3 Seiten mit neuen Vorlagen ab, hat sie die
    verschobene Zone noch nicht erreicht: `gespeichert` bleibt bei Nacht 1, Nacht 3 ist vollständig (mit `gespeichert`
    aus Nacht 2 erlaubte sie nur 4 verschobene Seiten)."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 5
    _verschiebung_in_seiten(monkeypatch, 5)
    oparl.papers = [oparl.paper(i) for i in range(1, 201)]
    _vorlagenseite_stoert(monkeypatch, {"16": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–15
    _neue_vorlagen(oparl, 12 * 8)
    uhr.t = _nacht(12)
    _vorlagenseite_stoert(monkeypatch, {"18": _ende_fenster})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Seiten 15–17, nur neue Vorlagen
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["15", "16", "17"]
    fort = json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]
    assert fort["gespeichert"] == _nacht(0).isoformat() and fort["naechste"].endswith("?page=17")
    assert len(_jsonl(config.RAW / "papers.teil.jsonl")) == 75 + 15            # 15 neue Vorlagen schon gelesen
    _neue_vorlagen(oparl, 8)
    uhr.t = _nacht(13)
    sessionnet.fetch_all()                                                 # Nacht 3: vollständig
    zustand = json.loads(config.ZUSTAND.read_text())
    assert not {"listenfehler", "papers_fortsetzung"} & set(zustand)
    assert [r for r in _statistik() if r["liste"] == "papers"][-1]["ergebnis"] == "ok"


# --- Runde 12: Die verschobene Zone ist erst mit einer ungelesenen Vorlage verlassen, die älter ist als die älteste
# gelesene (`created`); `gespeichert` in der Zukunft ---------------------------------------------------------------------

def _seiten_papers(oparl):
    return [q.get("page", "1") for p, q, _ in oparl.anfragen if p == "/papers"]


def _fortsetzung_papers():
    return json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]


def _vollstaendig_ohne_listenfehler():
    zustand = json.loads(config.ZUSTAND.read_text())
    assert not {"listenfehler", "letzter_abbruch", "sperre_verdacht", "papers_fortsetzung"} & set(zustand)
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll, fortgesetzt", "ok")


@pytest.mark.parametrize("seiten_nacht_3", [2, 3])
def test_lange_pause_zwei_strecken_gelesener_seiten(oparl, monkeypatch, seiten_nacht_3):
    """Neueste zuerst, 25 je Seite: Nacht 1 liest 10 Seiten (400 bis 151) und bricht ab; 40 Tage ohne Lauf mit 8 neuen
    Vorlagen je Tag (320, mehr als Nacht 1 las). Nacht 2 liest 2 Seiten nur neuer Vorlagen; Nacht 3 (8 weitere, 2 oder
    3 Seiten) beginnt mit einer Seite aus Nacht 2 und liest dann wieder neue Vorlagen: Die Strecke aus Nacht 1 kommt
    erst noch, `gespeichert` bleibt bei Nacht 1. Nacht 4 (8 weitere) bringt 10 Seiten nur gelesener Vorlagen (erlaubt
    40, mit `gespeichert` aus Nacht 3 nur 4) und ist vollständig, ohne Listenfehler; Nacht 5 (inkrementell) holt die
    neuen Vorlagen: keine fehlt, keine doppelt."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 25
    oparl.papers = [oparl.paper(i) for i in range(1, 401)]
    _vorlagenseite_stoert(monkeypatch, {"11": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–10
    _neue_vorlagen(oparl, 40 * 8)
    uhr.t = _nacht(40)
    _vorlagenseite_stoert(monkeypatch, {"12": _ende_fenster})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Seiten 10–11, nur neue
    assert _seiten_papers(oparl) == ["10", "11"]
    fort = _fortsetzung_papers()
    assert fort["gespeichert"] == _nacht(0).isoformat() and fort["naechste"].endswith("?page=11")
    _neue_vorlagen(oparl, 8)
    uhr.t = _nacht(41)
    ende = 11 + seiten_nacht_3
    _vorlagenseite_stoert(monkeypatch, {str(ende): _ende_fenster})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 3: Seite aus Nacht 2, dann neue
    assert _seiten_papers(oparl) == [str(n) for n in range(11, ende)]
    assert _fortsetzung_papers()["gespeichert"] == _nacht(0).isoformat()
    _neue_vorlagen(oparl, 8)
    uhr.t = _nacht(42)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 4: vollständig
    _vollstaendig_ohne_listenfehler()
    assert {p["id"] for p in oparl.papers[:400]} <= {p["id"] for p in _jsonl(config.PAPERS)}
    uhr.t = _nacht(43)
    sessionnet.fetch_all()                                                 # Nacht 5: inkrementell
    ids = [p["id"] for p in _jsonl(config.PAPERS)]
    assert len(ids) == len(set(ids)) and set(ids) == {p["id"] for p in oparl.papers}


def test_loeschungen_ueberwiegen_gespeichert_wird_nachgezogen(oparl, monkeypatch):
    """Neueste zuerst, 25 je Seite: Nacht 1 liest 10 Seiten (400 bis 151). Vor jeder weiteren Nacht werden 20 gelesene
    Vorlagen gelöscht, 5 neue kommen hinzu: Die Seiten rücken nach vorn, die Fortsetzung (eine Seite zurück) liest gleich
    ungelesene Vorlagen, älter als die älteste gelesene. `gespeichert` folgt so jeder Nacht (sonst wüchse die erlaubte
    Verschiebung bis 40, ein schwächerer Schutz gegen Schleifen). Nächte 2 bis 4 mit je 2 Seiten, Nacht 5 vollständig,
    Nacht 6 inkrementell: Es fehlt keine Vorlage, die gelöschten bleiben bis zum nächsten Vollabruf."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 25
    oparl.papers = [oparl.paper(i) for i in range(1, 401)]
    _vorlagenseite_stoert(monkeypatch, {"11": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–10
    geloescht = set()
    for nacht in (2, 3, 4):
        gelesen = {p["id"] for p in _jsonl(config.RAW / "papers.teil.jsonl")}
        weg = [p["id"] for p in oparl.papers[::-1] if p["id"] in gelesen][:20]
        geloescht.update(weg)
        oparl.papers = [p for p in oparl.papers if p["id"] not in weg]
        _neue_vorlagen(oparl, 5)
        uhr.t = _nacht(nacht)
        ab = int(_fortsetzung_papers()["naechste"].rsplit("=", 1)[1])
        _vorlagenseite_stoert(monkeypatch, {str(ab + 2): _ende_fenster})
        sessionnet.fetch_all()                                             # 2 Seiten ab der Fortsetzung
        assert _fortsetzung_papers()["gespeichert"] == _nacht(nacht).isoformat(), nacht
    uhr.t = _nacht(5)
    sessionnet.fetch_all()                                                 # Nacht 5: vollständig
    _vollstaendig_ohne_listenfehler()
    uhr.t = _nacht(6)
    sessionnet.fetch_all()                                                 # Nacht 6: inkrementell
    ids = [p["id"] for p in _jsonl(config.PAPERS)]
    assert len(ids) == len(set(ids)) and set(ids) == {p["id"] for p in oparl.papers} | geloescht


def test_gespeichert_in_der_zukunft_gilt_als_jetzt(oparl, monkeypatch):
    """`gespeichert` in der Zukunft (etwa nach einer falsch gehenden Uhr): Nacht 2 (50 neue Vorlagen) erlaubt 4
    verschobene Seiten und bricht nach 2 Seiten in der Zone ab; `gespeichert` gilt dann als jetzt, nicht als der künftige
    Wert. Nacht 3 drei Tage später (240 weitere) bringt 9 Seiten nur gelesener Vorlagen: erlaubt 12 (4 je Tag ab Nacht
    2), mit dem künftigen Wert nur 4 (Listenfehler)."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 25
    oparl.papers = [oparl.paper(i) for i in range(1, 401)]
    _vorlagenseite_stoert(monkeypatch, {"11": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–10
    z = json.loads(config.ZUSTAND.read_text())
    z["papers_fortsetzung"]["gespeichert"] = _nacht(30).isoformat()
    config.ZUSTAND.write_text(json.dumps(z))
    _neue_vorlagen(oparl, 50)
    uhr.t = _nacht(1)
    _vorlagenseite_stoert(monkeypatch, {"12": _ende_fenster})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Seiten 10–11, nur gelesene
    assert _seiten_papers(oparl) == ["10", "11"]
    fort = _fortsetzung_papers()
    assert fort["gespeichert"] == _nacht(1).isoformat() and fort["naechste"].endswith("?page=11")
    assert sessionnet.verschiebung_erlaubt(fort["gespeichert"], _nacht(4)) == 300           # 12 Seiten zu 25
    _neue_vorlagen(oparl, 240)
    uhr.t = _nacht(4)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 3: vollständig
    _vollstaendig_ohne_listenfehler()
    assert _seiten_papers(oparl) == [str(n) for n in range(11, 29)]         # 11, 12 neue; 13–21 nur gelesene; 22–28
    assert {p["id"] for p in oparl.papers[:400]} <= {p["id"] for p in _jsonl(config.PAPERS)}


def _verlassen(monkeypatch, gelesen, ungelesen):
    """liste() als Fortsetzung mit `gelesen` aus früheren Nächten: Seite 2 (25 Objekte, bei weniger gelesenen
    entsprechend weniger) bringt die ältesten gelesenen und `ungelesen`, danach endet das Zeitfenster. Liefert
    Teilabbruch.verlassen (Grenze: created der 25.-ältesten gelesenen, eine Seite)."""
    def get_json(url, pausen=None):
        if url.endswith("page=2"):
            return {"data": [*gelesen[-(25 - len(ungelesen)):], *ungelesen],
                    "links": {"next": "http://127.0.0.1/l?page=3"}}
        raise abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster")
    monkeypatch.setattr(abruf, "get_json", get_json)
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?page=2", objekte=gelesen, seiten=1)
    assert e.value.seiten == 2
    return e.value.verlassen


@pytest.mark.parametrize("gelesen_created, neu_created, verlassen", [
    ("2026-09-01T10:00:00+02:00", [None], False),                           # ungelesene ohne created
    ("2026-09-01T10:00:00+02:00", ["gestern"], False),                      # unlesbar
    ("2026-09-01T10:00:00+02:00", ["2026-08-31T10:00:00"], False),          # ohne Zone
    ("2026-09-01T10:00:00+02:00", ["2026-09-02T08:00:01+00:00"], False),    # eine Sekunde jünger als die Grenze
    ("2026-09-01T10:00:00+02:00", ["2026-11-09T22:00:00+00:00"], False),    # neuer: neue Vorlage am Listenanfang
    ("2026-09-01T10:00:00+02:00", ["2026-09-02T08:00:00+00:00"], True),     # so alt wie die Grenze (gleiches created)
    ("2026-09-01T10:00:00+02:00", ["2026-08-31T10:00:00+02:00"], True),     # älter als alle gelesenen
    ("2026-09-01T10:00:00+02:00", ["2026-11-09T22:00:00+00:00",             # gemischte Seite: eine jüngere und eine
                                   "2026-08-31T10:00:00+02:00"], True),     # ältere ungelesene
    ("1970-01-01T01:00:00+01:00", ["2026-08-31T10:00:00+02:00"], True),     # Platzhalterdatum unter den gelesenen
    (None, ["2026-08-31T10:00:00+02:00"], False)])                          # alle gelesenen ohne created
def test_verlassen_nur_nach_einer_aelteren_ungelesenen_vorlage(monkeypatch, gelesen_created, neu_created, verlassen):
    """Eine Fortsetzung verlässt die verschobene Zone erst mit einer ungelesenen Vorlage, die nicht jünger ist als die
    Grenze (created der 25.-ältesten gelesenen; hier nur zwei gelesene, also die jüngere: x/1, 02.09. 10 Uhr); ohne
    lesbares `created` (mit Zone) bleibt `gespeichert` (Teilabbruch.verlassen falsch)."""
    alt = [{"id": "x/1", "created": "2026-09-02T10:00:00+02:00"}, {"id": "x/2", "created": gelesen_created}]
    if gelesen_created is None:
        alt = [{"id": "x/1"}, {"id": "x/2", "created": "gestern"}]
    neu = [{"id": f"x/{3 + i}", **({"created": c} if c else {})} for i, c in enumerate(neu_created)]
    assert _verlassen(monkeypatch, alt, neu) is verlassen


# --- Runde 13: Grenze ist die 25.-älteste gelesene Vorlage; gleich alt genügt (Massenimport), Ausreißer stören nicht --

@pytest.mark.parametrize("platzhalter, stunden, verlassen", [
    (0, 24, True), (0, 24 + 1 / 3600, False),   # Grenze: die 25.-älteste gelesene (24 Stunden nach der ältesten)
    (24, 24, True),                             # 24 Platzhalterdaten verschieben die Grenze nicht
    (25, 24, False)])                           # ab 25 ist die Grenze ein Platzhalterdatum (Moduldoku)
def test_grenze_ist_die_25_aelteste_gelesene(monkeypatch, platzhalter, stunden, verlassen):
    """30 gelesene Vorlagen im Abstand von einer Stunde, die ältesten `platzhalter` mit Platzhalterdatum (1970); eine
    ungelesene Vorlage `stunden` nach der ältesten gelesenen."""
    erste = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    gelesen = [{"id": f"x/{i}", "created": ("1970-01-01T00:00:00+00:00" if i < platzhalter else
                                            (erste + timedelta(hours=i)).isoformat())} for i in range(30)][::-1]
    neu = {"id": "x/neu", "created": (erste + timedelta(hours=stunden)).isoformat()}
    assert _verlassen(monkeypatch, gelesen, [neu]) is verlassen


@pytest.mark.parametrize("altbestand", ["gleiches created", "Ausreißer"])
def test_zone_verlassen_bei_gleichem_created_und_ausreisser(oparl, monkeypatch, altbestand):
    """Neueste zuerst, 25 je Seite: 400 Vorlagen im Altbestand, alle mit demselben `created` (Massenimport) oder eine
    gelesene (Vorlage 300) mit Platzhalterdatum. Nacht 1 liest 10 Seiten (400 bis 151); 50 neue verschieben die Seiten
    um zwei. Nacht 2 liest die Seiten 10–12 (nur gelesene) und 13 (ungelesene aus dem Altbestand) und bricht ab: Die
    Zone ist verlassen, `gespeichert` gilt Nacht 2 (mit „älter als die älteste gelesene“ bliebe Nacht 1 und die
    erlaubte Verschiebung wüchse weiter). Nacht 3 ist vollständig, ohne Listenfehler; Nacht 4 (inkrementell) holt die
    neuen Vorlagen: keine fehlt, keine doppelt."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    oparl.form, oparl.groesse = "koeln", 25
    oparl.papers = [oparl.paper(i) for i in range(1, 401)]
    if altbestand == "gleiches created":
        for p in oparl.papers:
            p["created"] = "2026-08-01T10:00:00+02:00"
    else:
        oparl.papers[299]["created"] = "1970-01-01T01:00:00+01:00"
    _vorlagenseite_stoert(monkeypatch, {"11": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–10
    _neue_vorlagen(oparl, 50)
    uhr.t = _nacht(1)
    _vorlagenseite_stoert(monkeypatch, {"14": _ende_fenster})
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Seiten 10–13
    assert _seiten_papers(oparl) == ["10", "11", "12", "13"]
    assert _fortsetzung_papers()["gespeichert"] == _nacht(1).isoformat()
    uhr.t = _nacht(2)
    sessionnet.fetch_all()                                                 # Nacht 3: vollständig
    _vollstaendig_ohne_listenfehler()
    assert {p["id"] for p in oparl.papers[:400]} <= {p["id"] for p in _jsonl(config.PAPERS)}
    uhr.t = _nacht(3)
    sessionnet.fetch_all()                                                 # Nacht 4: inkrementell
    ids = [p["id"] for p in _jsonl(config.PAPERS)]
    assert len(ids) == len(set(ids)) and set(ids) == {p["id"] for p in oparl.papers}


# --- Runde 14: Zeitwerte URL-kodiert, links.next vor dem Folgen normalisiert, limit=100, Grenzen in Objekten ---------

def test_folgeadresse_normalisiert_den_query_teil():
    """links.next: je Parameter `quote(unquote(v), safe="")`, Reihenfolge, page und limit unverändert, idempotent;
    „+“ ist ein wörtliches Plus (unquote, nicht unquote_plus). Anderer Host oder anderes Schema als die Liste:
    Abbruch der Art `adresse`. Außerhalb von ASCII unverändert (get_json lehnt ab). Ein fehlendes limit wird ergänzt,
    wenn die erste Adresse des Laufs es trug."""
    liste = "https://buergerinfo.example.invalid/oparl/bodies/k/papers"
    roh = f"{liste}?page=2&modified_since=2026-11-05T11:29:44+00:00&limit=100"
    kodiert = f"{liste}?page=2&modified_since=2026-11-05T11%3A29%3A44%2B00%3A00&limit=100"
    assert sessionnet.folgeadresse(roh, liste) == kodiert
    assert sessionnet.folgeadresse(kodiert, liste) == kodiert                       # idempotent
    assert sessionnet.folgeadresse(f"{liste}?page=3", liste) == f"{liste}?page=3"
    assert sessionnet.folgeadresse(f"{liste}?page=3", liste, "100") == f"{liste}?page=3&limit=100"
    assert sessionnet.folgeadresse(f"{liste}?limit=50&page=3", liste, "100") == f"{liste}?limit=50&page=3"
    assert sessionnet.folgeadresse(f"{liste}?a=x%20y&b", liste) == f"{liste}?a=x%20y&b"
    assert sessionnet.folgeadresse(f"{liste}?straße=ü", liste) == f"{liste}?straße=ü"   # außerhalb von ASCII
    for fremd in ("https://andere.example.invalid/oparl/bodies/k/papers?page=2",
                  "http://buergerinfo.example.invalid/oparl/bodies/k/papers?page=2",
                  "https://buergerinfo.example.invalid:8443/oparl/bodies/k/papers?page=2"):
        with pytest.raises(abruf.Abbruch) as e:
            sessionnet.folgeadresse(fremd, liste)
        assert e.value.art == "adresse" and "anderen Host" in str(e.value) and not sessionnet.moegliche_sperre(e.value)
    assert os.environ.get("RATSATLAS_LIMIT") or config.ABRUF_SEITENGROESSE == "100"      # Vorgabe für Köln
    assert sessionnet._mit_parametern(liste, modified_since="2026-11-05T11:29:44+00:00", limit="100") == (
        f"{liste}?modified_since=2026-11-05T11%3A29%3A44%2B00%3A00&limit=100")


def test_schleifenschutz_auf_der_normalisierten_adresse(monkeypatch):
    """links.next zeigt auf die gelesene erste Seite, nur unkodiert: nach dem Normalisieren dieselbe Adresse, also
    sofort eine Schleife (ohne zweite Anfrage)."""
    abrufe = []
    erste = "http://127.0.0.1/l?modified_since=2026-11-05T11%3A29%3A44%2B00%3A00&limit=100"

    def get_json(url, pausen=None):
        abrufe.append(url)
        return {"data": [{"id": "x/1"}], "links": {"next": "http://127.0.0.1/l?modified_since=2026-11-05T11:29:44+00:00"
                                                           "&limit=100"}}
    monkeypatch.setattr(abruf, "get_json", get_json)
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "100")
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", seit="2026-11-05T11:29:44+00:00")
    assert abrufe == [erste] and e.value.art == "liste" and "bereits gelesene Seite" in str(e.value)


def test_fortsetzung_speichert_die_normalisierte_adresse(oparl, monkeypatch):
    """Trägt links.next kein limit, speichert die Fortsetzung die normalisierte Adresse mit limit (sonst ginge es in
    der nächsten Nacht mit Seiten zu 25 weiter)."""
    _koeln_mit_limit(oparl, monkeypatch, 450)
    echt = oparl.liste

    def ohne_limit(objekte, pfad, q, groesse=None):
        seite = echt(objekte, pfad, q, groesse)
        if seite["links"].get("next"):
            adresse, _, abfrage = seite["links"]["next"].partition("?")
            seite["links"]["next"] = adresse + "?" + "&".join(x for x in abfrage.split("&")
                                                               if not x.startswith("limit="))
        return seite
    monkeypatch.setattr(oparl, "liste", ohne_limit)
    _nach_seite(monkeypatch, 4, lambda: abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster"))
    sessionnet.fetch_all()                                                 # Seiten 1–3, dann Ende des Zeitfensters
    assert _fortsetzung_papers()["naechste"] == f"{oparl.b}/papers?page=3&limit=100"
    oparl.roh.clear()
    sessionnet.fetch_all()                                                 # Fortsetzung ab Seite 3, Seiten zu 100
    assert [q for p, q in oparl.roh if p == "/papers"] == ["page=3&limit=100", "page=4&limit=100", "page=5&limit=100"]
    assert len(_jsonl(config.PAPERS)) == 450


def _koeln_mit_limit(oparl, monkeypatch, anzahl, limit="100"):
    """Testserver in Kölner Form mit `anzahl` Vorlagen; limit wirkt (Stufe 2), die Pipeline sendet `limit`."""
    oparl.form, oparl.limit_wirkt = "koeln", True
    oparl.papers = [oparl.paper(i) for i in range(1, anzahl + 1)]
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", limit)


def test_inkrementell_filtert_ueber_alle_seiten(oparl, monkeypatch):
    """Köln (Stufe 2): Zeitwerte wirken nur kodiert, links.next trägt sie unkodiert. Der inkrementelle Abruf
    normalisiert links.next und bleibt so auf allen Seiten gefiltert (unverändert gefolgt wäre Seite 2 ungefiltert)."""
    _koeln_mit_limit(oparl, monkeypatch, 250, limit="20")
    sessionnet.fetch_all()                                                 # Vollabruf: 13 Seiten zu 20
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    for i in range(0, 250, 5):                                             # 50 Vorlagen geändert
        oparl.papers[i] = dict(oparl.papers[i], name="geändert", modified=zeit)
    oparl.anfragen.clear()
    oparl.roh.clear()
    sessionnet.fetch_all()
    roh = [q for p, q in oparl.roh if p == "/papers"]
    assert len(roh) == 3 and roh[0].startswith("modified_since=") and "limit=20" in roh[0]
    assert all("%2B00%3A00" in q and "+" not in q for q in roh)            # auch Seite 2 und 3 kodiert
    assert [q.get("page", "1") for p, q, _ in oparl.anfragen if p == "/papers"] == ["1", "2", "3"]
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["seiten"], z["neu"], z["geaendert"], z["filter_wirksam"], z["ergebnis"]) == (
        "inkrementell", "3", "0", "50", "ja", "ok")
    assert sum(p["name"] == "geändert" for p in _jsonl(config.PAPERS)) == 50
    assert not {"listenfehler", "letzter_abbruch"} & set(json.loads(config.ZUSTAND.read_text()))   # Prüfung je Seite


def test_limit_100_und_fehlendes_limit_in_links_next(oparl, monkeypatch):
    """limit=100 an der ersten Listenadresse; trägt links.next ihn nicht, wird er angehängt (sonst kämen ab Seite 2
    Seiten zu 25 mit schon gelesenen Vorlagen: Schleife)."""
    _koeln_mit_limit(oparl, monkeypatch, 250)
    echt = oparl.liste

    def ohne_limit(objekte, pfad, q, groesse=None):
        seite = echt(objekte, pfad, q, groesse)
        if seite["links"].get("next"):
            adresse, _, abfrage = seite["links"]["next"].partition("?")
            seite["links"]["next"] = adresse + "?" + "&".join(x for x in abfrage.split("&")
                                                               if not x.startswith("limit="))
        return seite
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "ja")
    for liste, erwartet in ((echt, ["limit=100", "limit=100&page=2", "limit=100&page=3"]),
                            (ohne_limit, ["limit=100", "page=2&limit=100", "page=3&limit=100"])):
        monkeypatch.setattr(oparl, "liste", liste)
        oparl.roh.clear()
        sessionnet.fetch_all()
        assert [q for p, q in oparl.roh if p == "/papers"] == erwartet
        z = [r for r in _statistik() if r["liste"] == "papers"][-1]
        assert (z["seiten"], z["objekte"], z["ergebnis"]) == ("3", "250", "ok")


@pytest.mark.parametrize("neu, tage, ergebnis", [(99, 1, "ok"), (101, 1, "liste"), (101, 2, "ok")])
def test_fortsetzung_ueber_naechte_mit_100er_seiten(oparl, monkeypatch, neu, tage, ergebnis):
    """Kölner Form, 100 je Seite (Scheinuhr): Nacht 1 liest die Seiten 1–4 (1000 bis 601) und bricht am Ende des
    Zeitfensters ab; die Fortsetzung speichert die normalisierte Adresse mit limit. Bis Nacht 2 kommen `neu` Vorlagen
    hinzu. Erlaubt sind 100 Vorlagen je angefangenem Tag, in Seiten zu 100 aufgerundet: 99 neue in einem Tag ergeben
    eine Seite ohne neue Kennungen (die wiederholte), 101 zwei (Listenfehler), nach zwei Tagen sind zwei erlaubt.
    Danach holt der inkrementelle Lauf die neuen Vorlagen: keine fehlt, keine doppelt."""
    _nicht_lokal(monkeypatch)
    uhr = _scheinuhr(monkeypatch, _nacht(0))
    _koeln_mit_limit(oparl, monkeypatch, 1000)
    _vorlagenseite_stoert(monkeypatch, {"5": _ende_fenster})
    sessionnet.fetch_all()                                                 # Nacht 1: Seiten 1–4
    fort = _fortsetzung_papers()
    assert (fort["seiten"], fort["naechste"]) == (4, f"{oparl.b}/papers?limit=100&page=4")
    _neue_vorlagen(oparl, neu)
    uhr.t = _nacht(tage)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht 2: Fortsetzung ab Seite 4
    zustand = json.loads(config.ZUSTAND.read_text())
    if ergebnis == "liste":
        assert _seiten_papers(oparl) == ["4", "5"] and zustand["listenfehler"]["naechte"] == 1
        z = [r for r in _statistik() if r["liste"] == "papers"][-1]
        assert ("mehr als 1 Seiten ohne neue Kennungen in der Fortsetzung (erlaubte Seitenverschiebung 100 Vorlagen "
                "bei 100 je Seite)") in z["ergebnis"]
        return
    _vollstaendig_ohne_listenfehler()
    assert _seiten_papers(oparl) == [str(n) for n in range(4, math.ceil((1000 + neu) / 100) + 1)]
    uhr.t = _nacht(tage + 1)
    sessionnet.fetch_all()                                                 # Nacht 3: inkrementell
    ids = [p["id"] for p in _jsonl(config.PAPERS)]
    assert len(ids) == len(set(ids)) == 1000 + neu


@pytest.mark.parametrize("platzhalter, sekunden, verlassen", [
    (0, 0, True), (0, 1, False),     # Grenze: created der 100.-ältesten gelesenen (eine Seite zu 100)
    (99, 0, True),                   # 99 Platzhalterdaten verschieben sie nicht
    (100, 0, False)])                # ab 100 ist die Grenze ein Platzhalterdatum
def test_grenze_ist_eine_seite_der_tatsaechlichen_groesse(monkeypatch, platzhalter, sekunden, verlassen):
    """Grenze der verschobenen Zone bei 100 je Seite: created der 100.-ältesten gelesenen Vorlage (Seitengröße aus der
    gelesenen Seite, nicht fest 25). 120 gelesene im Abstand von einer Stunde, die ältesten `platzhalter` mit
    Platzhalterdatum; Seite 2 bringt 99 gelesene und eine ungelesene, `sekunden` nach der 100.-ältesten."""
    erste = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    gelesen = [{"id": f"x/{i}", "created": ("1970-01-01T00:00:00+00:00" if i < platzhalter else
                                            (erste + timedelta(hours=i)).isoformat())} for i in range(120)][::-1]
    neu = {"id": "x/neu", "created": (erste + timedelta(hours=99, seconds=sekunden)).isoformat()}

    def get_json(url, pausen=None):
        if url.endswith("page=2"):
            return {"data": [*gelesen[-99:], neu], "links": {"next": "http://127.0.0.1/l?page=3"}}
        raise abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster")
    monkeypatch.setattr(abruf, "get_json", get_json)
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?page=2", objekte=gelesen, seiten=1)
    assert e.value.verlassen is verlassen


# --- Runde 15: Obergrenze je Nacht mit Fortsetzung, Gesamtgrenze für 500 000 Objekte, Zeitfilter auf Folgeseiten,
# Zeitfenster unmittelbar vor dem Senden, Standardport in links.next ---------------------------------------------------

class _Scheinnetz:
    """Antworten des Testservers `oparl` ohne Netz: abruf.get_json läuft unverändert (Zeitfenster 23–1 Uhr, Abstand
    2 s, Zählung), nur der Öffner antwortet direkt aus `oparl`, und jede Antwort dauert `dauer` Sekunden auf der
    Scheinuhr, die abruf.uhr, time.monotonic und time.sleep (Abstand) in abruf.py treibt."""

    def __init__(self, oparl, monkeypatch, start, dauer):
        self.oparl, self.dauer, self.t, self.anfragen = oparl, dauer, start, []
        monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
        monkeypatch.setattr(abruf, "lokal", lambda url: False)
        monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")   # Pflicht vor Anfragen an nicht lokale Ziele
        monkeypatch.setattr(config, "ABRUF_ABSTAND", 2.0)
        monkeypatch.setattr(abruf, "uhr", lambda: self.t)
        monkeypatch.setattr(abruf, "time", types.SimpleNamespace(monotonic=lambda: self.t.timestamp(),
                                                                 sleep=self.warten))
        monkeypatch.setattr(abruf, "_letzte", start.timestamp())
        monkeypatch.setattr(abruf, "_OEFFNER", self)

    def warten(self, sekunden):
        self.t += timedelta(seconds=sekunden)

    def open(self, req, timeout=None):
        teile = urllib.parse.urlsplit(req.full_url)
        q = {k: urllib.parse.unquote_plus(v) for k, _, v in (x.partition("=") for x in teile.query.split("&") if x)}
        self.anfragen.append((self.t, teile.path, q))
        self.t += timedelta(seconds=self.dauer)
        d = self.oparl
        antwort = d.body() if teile.path == "/body" else d.liste(
            {"/papers": d.papers, "/meetings": d.meetings, "/organizations": d.orgs}[teile.path], teile.path, q)
        return contextlib.nullcontext(io.BytesIO(json.dumps(antwort).encode()))


@pytest.mark.parametrize("vorlagen, nacht_0, gesamt, naechte", [
    (13_500, datetime(2026, 11, 9, 22, 10, tzinfo=timezone.utc), None, 2),       # 135 000 skaliert, Winter
    (50_000, datetime(2026, 7, 9, 22, 10, tzinfo=timezone.utc), 60_000, 9)])    # 500 000 skaliert, Sommer (0:10 Uhr)
def test_vollabruf_ueber_mehrere_naechte_mit_obergrenze_je_nacht(oparl, monkeypatch, vorlagen, nacht_0, gesamt,
                                                                 naechte):
    """Scheinuhr, echtes Zeitfenster 23–1 Uhr, Abstand 2 s, schnelle Antworten (3 s): Im Winter (Start 23:10 Uhr) passen
    rund 1300 Seiten ins Fenster, die Grenze je Nacht (1000 Seiten) greift vorher. Ein Vollabruf endet dann wie am Ende
    des Zeitfensters (Art `obergrenze`: Fortsetzung, neutraler Hinweis, kein Listenfehler, kein Sperrverdacht; in
    derselben Nacht kein weiterer Lauf) und wird fertig. Skaliert mit 10 je Seite (Grenzen in Objekten durch 10,
    gleiche Seitenzahlen): 135 000 Vorlagen in zwei Nächten; 500 000 im Sommer (Start 0:10 Uhr, rund 600 Seiten je
    Nacht) in neun Nächten unter der Gesamtgrenze (600 000, skaliert 60 000)."""
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 10_000)                # 1000 Seiten zu 10 je Liste und Nacht
    if gesamt:
        monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE_GESAMT", gesamt)
    oparl.form, oparl.limit_wirkt = "koeln", True
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "10")
    erste = datetime(2026, 1, 1, tzinfo=timezone.utc)
    oparl.papers = [{"id": f"{oparl.b}/papers/{i}", "created": (erste + timedelta(minutes=i)).isoformat(),
                     "modified": "2026-10-01T10:00:00+02:00"} for i in range(1, vorlagen + 1)]
    netz = _Scheinnetz(oparl, monkeypatch, nacht_0, 3.0)
    for nacht in range(naechte):
        netz.t = max(netz.t, nacht_0 + timedelta(days=nacht))
        vorher = len(netz.anfragen)
        sessionnet.fetch_all()
        diese = netz.anfragen[vorher:]
        assert diese and all(t.astimezone(abruf.ORTSZEIT).hour in (23, 0) for t, _, _ in diese), nacht
        assert sum(p == "/papers" for _, p, _ in diese) <= 1000, nacht
        zustand, stand = json.loads(config.ZUSTAND.read_text()), json.loads(config.STAND.read_text())
        assert not {"listenfehler", "sperre_verdacht"} & set(zustand), nacht
        z = [r for r in _statistik() if r["liste"] == "papers"][-1]
        if nacht == 0 and gesamt is None:                                  # Winter: die Grenze je Nacht greift
            assert z["ergebnis"].startswith("unterbrochen nach 1000 Seiten, Fortsetzung im nächsten Lauf: Obergrenze "
                                            "je Nacht erreicht: 1000 Seiten in diesem Lauf"), z["ergebnis"]
            assert stand["abruf_hinweis"]["meldung"].startswith(
                "Obergrenze je Nacht erreicht, Fortsetzung in der nächsten Nacht.") and "abruf_fehler" not in stand
            assert zustand["letzter_abbruch"]["art"] == "obergrenze" and zustand["papers_fortsetzung"]["seiten"] == 1000
            netz.t += timedelta(minutes=10)                                # dieselbe Nacht: kein weiterer Lauf
            sessionnet.fetch_all()
            assert len(netz.anfragen) == vorher + len(diese)
            assert "Abbruch (obergrenze)" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]
        if nacht < naechte - 1:
            assert "papers_fortsetzung" in zustand and z["ergebnis"].startswith("unterbrochen"), (nacht, z)
    assert (z["modus"], z["ergebnis"]) == ("voll, fortgesetzt", "ok") and "papers_fortsetzung" not in zustand
    assert int(z["seiten"]) < math.ceil(config.ABRUF_MAX_OBJEKTE_GESAMT / 10)
    ids = [p["id"] for p in _jsonl(config.PAPERS)]
    assert len(ids) == len(set(ids)) == vorlagen


def test_gesamtgrenze_reicht_fuer_500_000_objekte():
    """Vorgaben: höchstens 1000 Seiten zu 100 je Liste und Nacht; die Gesamtgrenze lässt einem Vollabruf mit 500 000
    Objekten Spielraum für die wiederholte Seite je Fortsetzung und die Seitenverschiebung (bei 25 je Seite ebenso)."""
    assert config.ABRUF_MAX_OBJEKTE == 100_000 and config.ABRUF_MAX_OBJEKTE_GESAMT >= 500_000
    for groesse in (100, 25):
        seiten = 500_000 // groesse
        naechte = math.ceil(seiten / min(400, config.ABRUF_MAX_OBJEKTE // groesse))   # Sommer: rund 400 je Nacht
        # je Fortsetzung die wiederholte Seite und bis zu 1000 Vorlagen Verschiebung
        spielraum = naechte * (1 + math.ceil(sessionnet.VERSCHIEBUNG_HOECHSTENS / groesse))
        assert seiten + spielraum < math.ceil(config.ABRUF_MAX_OBJEKTE_GESAMT / groesse), groesse


def _nur_seite_1_gefiltert(oparl, monkeypatch):
    """Server wendet modified_since nur auf Seite 1 der Vorlagen an (ungemessen, ob Köln es auf Seite 2 tut)."""
    echt = oparl.liste

    def liste(objekte, pfad, q, groesse=None):
        if pfad == "/papers" and q.get("page", "1") != "1":
            q = {k: v for k, v in q.items() if k != "modified_since"}
        return echt(objekte, pfad, q, groesse)
    monkeypatch.setattr(oparl, "liste", liste)


def test_zeitfilter_nur_auf_seite_1_bricht_nach_seite_2_ab(oparl, monkeypatch):
    """Inkrementeller Lauf gegen einen Server, der modified_since nur auf Seite 1 anwendet: Seite 2 bringt Vorlagen mit
    modified vor der Grenze. Abbruch nach dieser Seite (2 Anfragen statt der ganzen Liste bis zum Fensterende), Art
    `filter`: zählt wie ein Listenfehler, kein Sperrverdacht, nichts zusammengeführt; Abrufstatistik und STAND.json
    nennen es, filter_wirksam aus den gelesenen Seiten. Filtert der Server alle Seiten, läuft der Lauf durch
    (test_inkrementell_filtert_ueber_alle_seiten)."""
    _koeln_mit_limit(oparl, monkeypatch, 250, limit="20")
    sessionnet.fetch_all()                                                 # Vollabruf: 13 Seiten zu 20
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    for i in range(0, 250, 5):                                             # 50 Vorlagen geändert (3 Seiten)
        oparl.papers[i] = dict(oparl.papers[i], name="geändert", modified=zeit)
    _nur_seite_1_gefiltert(oparl, monkeypatch)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _seiten_papers(oparl) == ["1", "2"] and not [p for p, *_ in oparl.anfragen if p == "/meetings"]
    zustand, stand = json.loads(config.ZUSTAND.read_text()), json.loads(config.STAND.read_text())
    assert zustand["listenfehler"]["naechte"] == 1 and zustand["letzter_abbruch"]["art"] == "filter"
    assert "sperre_verdacht" not in zustand
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    # Seite 2 ungefiltert: 20 Vorlagen, davon 4 geänderte schon von Seite 1 (36 verschiedene), 16 vor der Grenze
    assert (z["modus"], z["seiten"], z["objekte"]) == ("inkrementell", "2", "36")
    assert z["ergebnis"].startswith("abbruch: Zeitfilter auf Seite 2 nicht angewandt: 16 von 20 Objekten mit modified "
                                    "vor modified_since=") and z["filter_wirksam"] == "nein (16 ältere)"
    assert stand["abruf_fehler"]["meldung"].startswith("Zeitfilter auf Seite 2 nicht angewandt")
    hinweis = stand["abruf_hinweis"]["meldung"]
    assert "fehlerhaften Liste (filter)" in hinweis and "Zeitfilter nicht angewandt" in hinweis
    assert sum(p.get("name") == "geändert" for p in _jsonl(config.PAPERS)) == 0   # nichts zusammengeführt


def test_filterpruefung_je_seite_an_der_grenze(monkeypatch):
    """Geprüft wird `modified` gegen modified_since selbst (die Überlappung ist dort schon abgezogen): gleich der
    Grenze, später, fehlend, unlesbar oder ohne Zone löst nichts aus; eine Sekunde davor bricht nach dieser Seite ab
    (die Objekte der Seite sind gelesen, keine Fortsetzung)."""
    seit = "2026-11-08T22:10:00+00:00"
    seiten = {"1": [{"id": "a", "modified": seit}, {"id": "b", "modified": "2026-11-09T10:00:00+01:00"}, {"id": "c"},
                    {"id": "d", "modified": "gestern"}, {"id": "e", "modified": "2026-11-08T22:00:00"}],
              "2": [{"id": "f", "modified": "2026-11-08T23:09:59+01:00"}, {"id": "g", "modified": seit}],
              "3": [{"id": "h", "modified": seit}]}

    def get_json(url, pausen=None):
        seite = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("page", ["1"])[0]
        links = {"next": f"http://127.0.0.1/l?page={int(seite) + 1}"} if seite != "3" else {}
        return {"data": seiten[seite], "links": links}
    monkeypatch.setattr(abruf, "get_json", get_json)
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "")
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", seit=seit)
    assert (e.value.art, e.value.seiten, e.value.naechste) == ("filter", 2, None)
    assert [o["id"] for o in e.value.objekte] == list("abcdefg")
    assert str(e.value).startswith(f"Zeitfilter auf Seite 2 nicht angewandt: 1 von 2 Objekten mit modified vor "
                                   f"modified_since={seit} (frühestes 2026-11-08T23:09:59+01:00)")
    seiten["2"][0]["modified"] = seit                                      # gleich der Grenze: kein Abbruch
    objekte, n = sessionnet.liste("http://127.0.0.1/l", seit=seit)
    assert n == 3 and len(objekte) == 8


def test_hinweis_am_fensterende_eines_inkrementellen_laufs(oparl, monkeypatch):
    """Ein inkrementeller Lauf speichert keine Fortsetzung: Endet das Zeitfenster dort, sagt der Hinweis, dass er in
    der nächsten Nacht erneut beginnt (nicht „Fortsetzung“)."""
    sessionnet.fetch_all()
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    oparl.papers = [dict(p, modified=zeit) for p in oparl.papers]          # alle geändert: 3 Seiten zu 2
    _nach_seite(monkeypatch, 2, _ende_fenster)
    sessionnet.fetch_all()
    hinweis = json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"]
    assert hinweis.startswith("Das Zeitfenster endete während des Abrufs, der inkrementelle Abruf beginnt in der "
                              "nächsten Nacht erneut (ein inkrementeller Lauf speichert keine Fortsetzung).")
    assert "papers_fortsetzung" not in json.loads(config.ZUSTAND.read_text())


@pytest.mark.parametrize("letzte, offen", [(datetime(2026, 11, 9, 23, 59, 59, tzinfo=timezone.utc), False),
                                           (datetime(2026, 11, 9, 23, 59, 57, tzinfo=timezone.utc), True)])
def test_zeitfenster_nach_dem_warten_unmittelbar_vor_dem_senden(monkeypatch, letzte, offen):
    """Ende der vorigen Antwort um 00:59:59 Ortszeit, Abstand 2 s: Vor dem Warten ist das Fenster offen, beim Senden
    (01:00:01) zu: Abbruch `zeitfenster`, nichts gesendet, nichts gezählt. Um 00:59:57 bleibt es bis zum Senden
    offen."""
    uhr = types.SimpleNamespace(t=letzte)
    monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
    monkeypatch.setattr(abruf, "time", types.SimpleNamespace(
        monotonic=lambda: uhr.t.timestamp(), sleep=lambda s: setattr(uhr, "t", uhr.t + timedelta(seconds=s))))
    monkeypatch.setattr(abruf, "_letzte", letzte.timestamp())
    gesendet = []
    monkeypatch.setattr(abruf, "_OEFFNER", types.SimpleNamespace(open=lambda req, timeout=None: gesendet.append(
        (uhr.t, req.full_url)) or contextlib.nullcontext(io.BytesIO(b"{}"))))
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    assert config.ABRUF_ZEITFENSTER == "23-1" and abruf.im_zeitfenster(letzte)
    vorher = abruf.statistik()
    if offen:
        assert abruf.get_json("https://oparl.example.invalid/body") == {}
        assert gesendet == [(letzte + timedelta(seconds=2), "https://oparl.example.invalid/body")]
        return
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json("https://oparl.example.invalid/body")
    assert e.value.art == "zeitfenster" and gesendet == [] and uhr.t == letzte + timedelta(seconds=2)
    assert abruf.statistik()["anfragen"] == vorher["anfragen"]


def test_folgeadresse_ausdruecklicher_standardport():
    """links.next mit ausdrücklichem Standardport (https …:443, http …:80) gilt als derselbe Host wie ohne Port (und
    umgekehrt); ein anderer Port bleibt ein anderer Host (Art `adresse`)."""
    h = "buergerinfo.example.invalid"
    for liste, nxt in ((f"https://{h}/l", f"https://{h}:443/l?page=2"), (f"https://{h}:443/l", f"https://{h}/l?page=2"),
                       (f"http://{h}/l", f"http://{h}:80/l?page=2"), (f"http://{h}:80/l", f"http://{h}/l?page=2")):
        assert sessionnet.folgeadresse(nxt, liste) == nxt, (liste, nxt)
    for liste, nxt in ((f"https://{h}/l", f"https://{h}:8443/l?page=2"), (f"https://{h}/l", f"https://{h}:80/l?page=2"),
                       (f"http://{h}/l", f"http://{h}:443/l?page=2"),
                       (f"https://{h}:443/l", f"http://{h}:443/l?page=2")):
        with pytest.raises(abruf.Abbruch) as e:
            sessionnet.folgeadresse(nxt, liste)
        assert e.value.art == "adresse", (liste, nxt)


# --- Runde 16: organizations ohne Zeitfilter, Zeitfilter bei Sitzungen nur mit Warnung, Löschungen ohne Filterprüfung,
# RATSATLAS_MAX_OBJEKTE beim Start geprüft, `obergrenze` nur mit Fortschritt, Hinweise aus dem Zustand -----------------

def _ohne_zeitfilter(oparl, monkeypatch, *pfade):
    """Der Server übergeht modified_since für diese Listen (liefert sie ungefiltert); liefert die echte Liste zurück."""
    echt = oparl.liste

    def liste(objekte, pfad, q, groesse=None):
        if pfad in pfade:
            q = {k: v for k, v in q.items() if k != "modified_since"}
        return echt(objekte, pfad, q, groesse)
    monkeypatch.setattr(oparl, "liste", liste)
    return echt


def test_organisationen_ohne_zeitfilter_blockieren_die_vorlagen_nicht(oparl, monkeypatch):
    """Server übergeht modified_since bei organizations (Organisationen mit altem modified): Die Organisationen kommen
    immer ohne Zeitfilter und vollständig, auch in der Fortsetzung und im inkrementellen Lauf (keine Filterprüfung). Der
    Vollabruf der Vorlagen über zwei Nächte wird fertig, danach ein inkrementeller Lauf; kein Listenfehler, keine Pause
    (bis Runde 15: Abbruch `filter` bei den Organisationen in jeder Nacht, die Vorlagen nie erreicht)."""
    _ohne_zeitfilter(oparl, monkeypatch, "/organizations")
    _nach_seite(monkeypatch, 2, _ende_fenster)
    sessionnet.fetch_all()                                                 # Nacht 1: Vorlagen bis Seite 1
    assert "papers_fortsetzung" in json.loads(config.ZUSTAND.read_text())
    for nacht in (2, 3):                                                   # Fortsetzung fertig, dann inkrementell
        oparl.roh.clear()
        sessionnet.fetch_all()
        zustand = json.loads(config.ZUSTAND.read_text())
        assert not {"listenfehler", "letzter_abbruch", "sperre_verdacht", "papers_fortsetzung"} & set(zustand), nacht
        assert [q for p, q in oparl.roh if p == "/organizations"] == [""], nacht   # ohne modified_since
        assert any(p == "/papers" for p, q in oparl.roh), nacht
    assert all(q.startswith("modified_since=") for p, q in oparl.roh if p in ("/papers", "/meetings"))
    z = [r for r in _statistik() if r["liste"] == "organizations"][-1]
    assert (z["modus"], z["filter_wirksam"], z["objekte"], z["ergebnis"]) == ("voll", "", "2", "ok")
    assert [r["modus"] for r in _statistik() if r["liste"] == "papers"][-2:] == ["voll, fortgesetzt", "inkrementell"]
    assert len(json.loads(config.ORGANIZATIONS.read_text())) == 2 and "abruf_hinweis" not in json.loads(
        config.STAND.read_text())


def test_unvollstaendige_organisationen_blockieren_die_vorlagen_nicht(oparl, monkeypatch):
    """Die Organisationen kommen jede Nacht vollständig, also gilt für sie jede Nacht die Regel aus Bonn (Vollabruf
    unter 90 % des Stands, Art `leer`). Weil sie vor den Vorlagen kommen, endet dann nur diese Liste mit Warnung: Rohdaten,
    organizations.json und Zeitstempel bleiben (letzter gültiger Stand), Vorlagen und Sitzungen laufen, kein Abbruch,
    kein Listenfehler, Hinweis in STAND.json. Mit vollständiger Liste wieder aktualisiert, der Hinweis entfällt. Endet
    so eine Fortsetzung der Organisationen, wird sie verworfen (sonst läse jede Nacht dieselbe Fortsetzung bis zum Ende
    und endete wieder so)."""
    alle = oparl.orgs + [dict(oparl.orgs[1], id=f"{oparl.b}/organizations/{i}", name=f"Gremium {i}") for i in range(8)]
    oparl.orgs = list(alle)                                                # 10 Organisationen
    sessionnet.fetch_all()
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    frueher = (datetime.fromisoformat(zeit) - timedelta(hours=1)).isoformat(timespec="seconds")
    sessionnet._zustand_setzen("organizations", frueher)                   # Zeitstempel unterscheidbar
    sessionnet._stand_setzen(organizations=frueher)
    roh = {f: (config.RAW / f).read_bytes() for f in ("organizations.json", "organizations.jsonl")}
    oparl.orgs = alle[:8]                                                  # 8 von 10: unter 90 %
    oparl.papers[0] = dict(oparl.papers[0], name="geändert", modified=zeit)
    sessionnet.fetch_all()
    zustand, stand = json.loads(config.ZUSTAND.read_text()), json.loads(config.STAND.read_text())
    assert not {"listenfehler", "letzter_abbruch", "sperre_verdacht", "organizations_fortsetzung"} & set(zustand)
    assert zustand["organizations"] == stand["organizations"] == frueher and "abruf_fehler" not in stand
    assert roh == {f: (config.RAW / f).read_bytes() for f in roh}
    assert "abruf_hinweis" not in stand and stand["abruf_warnungen"]["organizations"]["meldung"].startswith(
        "Organisationen unvollständig (unter 90 % des Stands), nicht aktualisiert (letzter gültiger Stand bleibt, kein "
        "Listenfehler): organizations.jsonl: nur 8 statt bisher 10")
    z = [r for r in _statistik() if r["liste"] == "organizations"][-1]
    assert (z["modus"], z["objekte"]) == ("voll", "8") and z["ergebnis"].startswith("warnung: Organisationen")
    assert [(r["liste"], r["ergebnis"]) for r in _statistik()[-2:]] == [("papers", "ok"), ("meetings", "ok")]
    assert sum(x["name"] == "geändert" for x in _jsonl(config.PAPERS)) == 1
    oparl.orgs = alle                                                      # wieder vollständig
    sessionnet.fetch_all()
    assert not {"abruf_hinweis", "abruf_warnungen"} & set(json.loads(config.STAND.read_text()))
    assert json.loads(config.ZUSTAND.read_text())["organizations"] != frueher
    echt, einmal = abruf.get_json, []

    def get_json(url, pausen=None):   # Ende des Zeitfensters vor Seite 2 der Organisationen, einmal
        if "/organizations" in url and "page=2" in url and not einmal:
            einmal.append(url)
            raise _ende_fenster()
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)
    oparl.orgs = alle[:8]
    sessionnet.fetch_all()                                                 # Fortsetzung ab Seite 1 gespeichert
    assert "organizations_fortsetzung" in json.loads(config.ZUSTAND.read_text())
    sessionnet.fetch_all()                                                 # bis zum Ende: 8 von 10, Warnung
    assert "organizations_fortsetzung" not in json.loads(config.ZUSTAND.read_text())
    assert not (config.RAW / "organizations.teil.jsonl").exists()
    assert json.loads(config.STAND.read_text())["abruf_warnungen"]["organizations"]["meldung"].startswith(
        "Organisationen unvollständig")


def test_sitzungen_ohne_zeitfilter_nur_warnung(oparl, monkeypatch):
    """Server übergeht modified_since bei meetings: Der inkrementelle Lauf liest die erste Seite der Sitzungen, findet
    Sitzungen mit modified vor der Grenze und beendet nur diese Liste (keine weiteren Seiten). Warnung in STAND.json und
    Abrufstatistik („Zeitfilter bei Sitzungen nicht angewandt, Sitzungen nicht aktualisiert“), filter_wirksam „nein“;
    die Sitzungen bleiben auf dem letzten gültigen Stand (Rohdaten, meetings.json und Zeitstempel unverändert, die
    geänderte Sitzung nicht übernommen). Kein Listenfehler, keine Pause; die Vorlagen laufen, Beratungen abgeleitet,
    der Lauf gilt als vollständig. Ein späterer Lauf mit angewandtem Filter aktualisiert und entfernt den Hinweis."""
    m = oparl.meetings[0]
    oparl.meetings = [dict(m, id=f"{oparl.b}/meetings/{i}", name=f"Sitzung {i}") for i in (2, 3)] + [m]   # 2 Seiten
    sessionnet.fetch_all()                                                 # Vollabruf
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    frueher = (datetime.fromisoformat(zeit) - timedelta(hours=1)).isoformat(timespec="seconds")
    sessionnet._zustand_setzen("meetings", frueher)                        # Zeitstempel unterscheidbar
    sessionnet._stand_setzen(meetings=frueher)
    roh = {f: (config.RAW / f).read_bytes() for f in ("meetings.json", "meetings_roh.jsonl")}
    oparl.papers[0] = dict(oparl.papers[0], name="geändert", modified=zeit)
    oparl.meetings[2] = dict(m, name="Sitzung geändert", modified=zeit)
    echt = _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [q.get("page", "1") for p, q, _ in oparl.anfragen if p == "/meetings"] == ["1"]   # nur die Seite mit Befund
    neu_zustand, neu_stand = json.loads(config.ZUSTAND.read_text()), json.loads(config.STAND.read_text())
    assert not {"listenfehler", "letzter_abbruch", "sperre_verdacht", "meetings_fortsetzung"} & set(neu_zustand)
    assert neu_zustand["meetings"] == neu_stand["meetings"] == frueher and neu_zustand["papers"] != frueher
    assert roh == {f: (config.RAW / f).read_bytes() for f in roh}
    assert not {"abruf_fehler", "abruf_hinweis"} & set(neu_stand)
    assert neu_stand["abruf_warnungen"]["meetings"]["meldung"].startswith(
        "Zeitfilter bei Sitzungen nicht angewandt, Sitzungen nicht aktualisiert (letzter gültiger Stand bleibt, kein "
        "Listenfehler): Zeitfilter auf Seite 1 nicht angewandt: 2 von 2 Objekten")
    z = [r for r in _statistik() if r["liste"] == "meetings"][-1]
    assert (z["modus"], z["seiten"], z["filter_wirksam"]) == ("inkrementell", "1", "nein (2 ältere)")
    assert z["ergebnis"].startswith("warnung: Zeitfilter bei Sitzungen nicht angewandt, Sitzungen nicht aktualisiert")
    p = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (p["modus"], p["geaendert"], p["ergebnis"]) == ("inkrementell", "1", "ok")
    assert sum(x["name"] == "geändert" for x in _jsonl(config.PAPERS)) == 1 and len(_jsonl(config.BERATUNGEN)) == 5
    monkeypatch.setattr(oparl, "liste", echt)                              # Filter angewandt
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "meetings")                 # Runde 17: erst ein Vollabruf liest sie
    sessionnet.fetch_all()
    assert "abruf_warnungen" not in json.loads(config.STAND.read_text())
    assert "Sitzung geändert" in [x["name"] for x in json.loads(config.MEETINGS.read_text())]


def test_vorlagen_ohne_zeitfilter_brechen_weiter_ab(oparl, monkeypatch):
    """Übergeht der Server modified_since bei den Vorlagen, bleibt es beim Abbruch `filter` nach der ersten Seite (wie
    Runde 15): Listenfehler, keine Sitzungen in diesem Lauf, der Hinweis nennt den nicht angewandten Zeitfilter."""
    sessionnet.fetch_all()
    _ohne_zeitfilter(oparl, monkeypatch, "/papers")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _seiten_papers(oparl) == ["1"] and not [p for p, *_ in oparl.anfragen if p == "/meetings"]
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["listenfehler"]["naechte"] == 1 and zustand["letzter_abbruch"]["art"] == "filter"
    hinweis = json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"]
    assert ("fehlerhaften Liste (filter), 1. Nacht ohne vollständigen Lauf; Zeitfilter nicht angewandt, Abbruch nach "
            "der ersten ungefilterten Seite; der inkrementelle Abruf beginnt in der nächsten Nacht erneut") in hinweis


def test_geloeschtes_objekt_mit_altem_modified_ohne_alarm(monkeypatch):
    """Eine Löschung (deleted: true) in der Antwort auf modified_since kann ein altes modified tragen: kein Abbruch
    `filter`, filter_wirksam „ja“. Dasselbe Objekt ohne deleted bricht nach dieser Seite ab."""
    seit = "2026-11-08T22:10:00+00:00"
    alt = {"id": "b", "deleted": True, "modified": "2020-01-01T00:00:00+00:00"}
    seiten = {"1": [{"id": "a", "modified": seit}, alt], "2": [{"id": "c", "modified": seit}]}

    def get_json(url, pausen=None):
        seite = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("page", ["1"])[0]
        return {"data": seiten[seite], "links": {"next": "http://127.0.0.1/l?page=2"} if seite == "1" else {}}
    monkeypatch.setattr(abruf, "get_json", get_json)
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "")
    objekte, n = sessionnet.liste("http://127.0.0.1/l", seit=seit)
    assert (n, [o["id"] for o in objekte]) == (2, ["a", "b", "c"])
    assert sessionnet._filter_wirksam(objekte, seit) == "ja"
    alt.pop("deleted")
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", seit=seit)
    assert (e.value.art, e.value.seiten) == ("filter", 1)
    assert sessionnet._filter_wirksam(e.value.objekte, seit) == "nein (1 ältere)"


@pytest.mark.parametrize("wert", [0, -100, 1199])
def test_max_objekte_fehleinstellung_beim_start_abgelehnt(oparl, monkeypatch, wert):
    """RATSATLAS_MAX_OBJEKTE unter 1200 (zwei Seiten zu 100 plus die größte Seitenverschiebung): Einstellungsfehler vor
    der ersten Anfrage, laut (ValueError mit Traceback), vermerkt in STAND.json, kein Sperrverdacht. 1200 geht."""
    assert sessionnet.max_objekte_mindestens() == 1200
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", wert)
    with pytest.raises(ValueError, match=rf"RATSATLAS_MAX_OBJEKTE={wert} liegt unter 1200 \(zwei Seiten zu 100"):
        sessionnet.fetch_all()
    assert oparl.anfragen == []
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["letzter_abbruch"]["art"] == "programmfehler" and "sperre_verdacht" not in zustand
    assert "RATSATLAS_MAX_OBJEKTE" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    config.ZUSTAND.unlink()
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 1200)
    sessionnet.fetch_all()
    assert [r["ergebnis"] for r in _statistik() if r["liste"] == "papers"][-1] == "ok"


@pytest.mark.parametrize("seite_3, art", [(["x4", "x5"], "liste"), (["x4", "n2"], "obergrenze")])
def test_obergrenze_nur_mit_neuen_objekten_ueber_die_wiederholte_seite_hinaus(monkeypatch, seite_3, art):
    """Fortsetzung, Grenze je Lauf 3 Seiten zu 2: Die wiederholte Seite bringt eine neue Vorlage (Löschungen rücken
    nach), die Seiten 2 und 3 nur schon gelesene (Verschiebung). Ohne neue Objekte über die wiederholte Seite hinaus
    endet der Lauf an der Grenze mit Art `liste` (die Fortsetzung käme nie voran), sonst mit `obergrenze`."""
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 6)
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "")
    seiten = {"p": ["n1", "x1"], "q": ["x2", "x3"], "r": seite_3, "s": ["x6", "x7"]}
    folge = {"p": "q", "q": "r", "r": "s", "s": "t"}

    def get_json(url, pausen=None):
        k = url.rsplit("=", 1)[1]
        return {"data": [{"id": i} for i in seiten[k]], "links": {"next": f"http://127.0.0.1/l?s={folge[k]}"}}
    monkeypatch.setattr(abruf, "get_json", get_json)
    gelesen = [{"id": f"x{i}"} for i in range(1, 11)]
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l", start="http://127.0.0.1/l?s=p", objekte=gelesen, seiten=5)
    assert (e.value.art, e.value.seiten) == (art, 8)
    if art == "liste":
        assert "ohne neue Objekte über die wiederholte Seite hinaus" in str(e.value)
        assert not sessionnet.moegliche_sperre(e.value) and "liste" in sessionnet.OHNE_FORTSETZUNG


def test_hinweis_aus_dem_zustand_fortsetzung_einer_anderen_liste(oparl, monkeypatch):
    """Hinweis am Ende des Zeitfensters aus dem Zustand, nicht aus der abbrechenden Liste: Steht eine Fortsetzung der
    Sitzungen aus, während der inkrementelle Lauf der Vorlagen am Fensterende abbricht, heißt es „Fortsetzung in der
    nächsten Nacht“ (bis Runde 15: „beginnt erneut“). Ohne Fortsetzung und ohne inkrementelle Liste (Fensterende beim
    Body): „der Abruf beginnt in der nächsten Nacht erneut“ (bis Runde 15: „Fortsetzung“)."""
    sessionnet.fetch_all()                                                 # Vorlagen und Sitzungen vollständig
    m = oparl.meetings[0]
    oparl.meetings = [dict(m, id=f"{oparl.b}/meetings/{i}") for i in (2, 3)] + [m]
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    oparl.papers = [dict(p, modified=zeit) for p in oparl.papers]          # 3 Seiten im inkrementellen Lauf
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "ja")
    echt = abruf.get_json

    def get_json(url, pausen=None):
        if "/meetings" in url and "page=2" in url:
            raise _ende_fenster()
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)
    sessionnet.fetch_all()                                                 # Sitzungen: Fortsetzung ab Seite 1
    assert "meetings_fortsetzung" in json.loads(config.ZUSTAND.read_text())
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    _nach_seite(monkeypatch, 2, _ende_fenster)                             # Vorlagen (inkrementell): Fensterende
    sessionnet.fetch_all()
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert z["modus"] == "inkrementell" and "Zeitfensters" in z["ergebnis"]
    assert json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"].startswith(
        "Das Zeitfenster endete während des Abrufs, Fortsetzung in der nächsten Nacht.")
    config.ZUSTAND.unlink()

    def body_fensterende(url, pausen=None):
        raise _ende_fenster()
    monkeypatch.setattr(abruf, "get_json", body_fensterende)
    sessionnet.fetch_all()
    assert json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"].startswith(
        "Das Zeitfenster endete während des Abrufs, der Abruf beginnt in der nächsten Nacht erneut.")


def test_inkrementeller_lauf_an_der_grenze_je_lauf_verweist_auf_vollabruf(oparl, monkeypatch):
    """Ein inkrementeller Lauf, der die Grenze je Lauf erreicht (Art `liste`), bekommt einen eigenen Hinweis mit
    RATSATLAS_VOLLABRUF=ja statt „jede Nacht beginnt der Vollabruf von vorn“."""
    sessionnet.fetch_all()
    zeit = json.loads(config.ZUSTAND.read_text())["papers"]
    oparl.papers = [dict(p, modified=zeit) for p in oparl.papers]          # 3 Seiten zu 2
    monkeypatch.setattr(sessionnet, "max_objekte_mindestens", lambda: 4)    # skaliert: 2 Seiten zu 2
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 4)
    sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["listenfehler"]["naechte"] == 1 and zustand["letzter_abbruch"]["art"] == "liste"
    hinweis = json.loads(config.STAND.read_text())["abruf_hinweis"]["meldung"]
    assert ("ein inkrementeller Lauf erreichte die Grenze je Lauf (RATSATLAS_MAX_OBJEKTE) und beginnt jede Nacht "
            "erneut; Abhilfe: einmal mit RATSATLAS_VOLLABRUF=ja") in hinweis and "von vorn" not in hinweis


# --- Runde 17: Warnungen der Nebenlisten dauerhaft und sichtbar, Sitzungen ohne Zeitfilter ohne Anfrage, kürzerer Stand
# ausdrücklich, Untergrenze aus der Seitengröße, Testlücken -------------------------------------------------------------

def _stand():
    return json.loads(config.STAND.read_text())


def _zustand():
    return json.loads(config.ZUSTAND.read_text())


def _papers_inkrementell_geaendert(oparl, name):
    """Eine Vorlage seit dem letzten Lauf geändert (für den inkrementellen Lauf)."""
    oparl.papers[0] = dict(oparl.papers[0], name=name, modified=_zustand()["papers"])


@pytest.mark.parametrize("abbruch", ["filter", "zeitfenster"])
def test_warnung_der_sitzungen_bleibt_bis_zur_regulaeren_aktualisierung(oparl, monkeypatch, abbruch):
    """Die Warnung der Sitzungen (Zeitfilter nicht angewandt) steht in STAND.json unter `abruf_warnungen`, nicht in
    `abruf_hinweis`. Ein späterer Abbruch der Vorlagen (Zeitfilter nicht angewandt oder Ende des Zeitfensters,
    _abbruch_vermerken) und ein vollständiger Lauf (Sitzungen übersprungen) lassen sie unverändert stehen; erst die
    reguläre Aktualisierung der Sitzungen (Vollabruf RATSATLAS_VOLLABRUF=meetings) entfernt sie."""
    sessionnet.fetch_all()
    echt = _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    sessionnet.fetch_all()                                                 # Befund bei den Sitzungen
    warnung = _stand()["abruf_warnungen"]["meetings"]
    assert warnung["meldung"].startswith("Zeitfilter bei Sitzungen nicht angewandt, Sitzungen nicht aktualisiert")
    assert "RATSATLAS_VOLLABRUF=meetings" in warnung["meldung"] and "abruf_hinweis" not in _stand()
    if abbruch == "filter":
        _ohne_zeitfilter(oparl, monkeypatch, "/papers")
    else:
        oparl.papers = [dict(p, modified=_zustand()["papers"]) for p in oparl.papers]   # 3 Seiten
        _nach_seite(monkeypatch, 2, _ende_fenster)
    sessionnet.fetch_all()                                                 # Abbruch bei den Vorlagen
    stand = _stand()
    assert stand["abruf_warnungen"] == {"meetings": warnung}
    assert ("fehlerhaften Liste (filter)" if abbruch == "filter" else "Zeitfenster endete") in stand[
        "abruf_hinweis"]["meldung"]
    monkeypatch.setattr(oparl, "liste", echt)                              # Vorlagen wieder gefiltert
    sessionnet.fetch_all()                                                 # vollständig, Sitzungen übersprungen
    stand = _stand()
    assert "abruf_hinweis" not in stand and "abruf_fehler" not in stand
    assert stand["abruf_warnungen"]["meetings"]["meldung"].startswith(
        "Zeitfilter bei Sitzungen nicht angewandt, Sitzungen nicht aktualisiert (Befund vom ")
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "meetings")
    sessionnet.fetch_all()                                                 # Sitzungen regulär aktualisiert
    assert "abruf_warnungen" not in _stand() and "meetings_ohne_zeitfilter" not in _zustand()


def test_warnung_der_organisationen_bleibt_bei_abbruch_der_vorlagen(oparl, monkeypatch):
    """Bis Runde 16 schrieb erst das Ende eines vollständigen Laufs die Warnung der Organisationen: Brachen danach die
    Vorlagen ab, ging sie verloren. Jetzt steht sie gleich in STAND.json (`abruf_warnungen`) und bleibt, bis die
    Organisationen wieder regulär aktualisiert sind."""
    alle = oparl.orgs + [dict(oparl.orgs[1], id=f"{oparl.b}/organizations/{i}", name=f"Gremium {i}") for i in range(8)]
    oparl.orgs = list(alle)
    sessionnet.fetch_all()
    oparl.orgs = alle[:8]                                                  # unter 90 %: Warnung
    echt = _ohne_zeitfilter(oparl, monkeypatch, "/papers")                 # Vorlagen: Abbruch `filter`
    sessionnet.fetch_all()
    stand = _stand()
    assert stand["abruf_warnungen"]["organizations"]["meldung"].startswith("Organisationen unvollständig")
    assert "abruf_fehler" in stand and "fehlerhaften Liste (filter)" in stand["abruf_hinweis"]["meldung"]
    oparl.orgs = alle
    monkeypatch.setattr(oparl, "liste", echt)
    sessionnet.fetch_all()
    assert not {"abruf_warnungen", "abruf_hinweis", "abruf_fehler"} & set(_stand())


@pytest.mark.parametrize("vollabruf", ["meetings", "ja"])
def test_sitzungen_ohne_zeitfilter_folgenaechte_ohne_anfrage(oparl, monkeypatch, vollabruf):
    """Nach dem Befund „Zeitfilter bei Sitzungen nicht angewandt“ steht `meetings_ohne_zeitfilter` mit Zeitpunkt im
    Zustand. In der zweiten und dritten Nacht danach keine Anfrage an die Sitzungen (Zeile `übersprungen`, 0 Anfragen;
    bis Runde 16 jede Nacht die Seiten bis zum Befund, nach einem Jahr rund 30), die Vorlagen laufen inkrementell, die
    Beratungen kommen aus dem letzten gültigen Stand, Warnung bleibt, kein Listenfehler. Ein Lauf mit
    RATSATLAS_VOLLABRUF=meetings (nur die Sitzungen vollständig, Vorlagen inkrementell) oder =ja liest die Sitzungen
    vollständig und setzt Vermerk und Warnung zurück."""
    m = oparl.meetings[0]
    oparl.meetings = [dict(m, id=f"{oparl.b}/meetings/{i}", name=f"Sitzung {i}") for i in (2, 3)] + [m]   # 2 Seiten
    sessionnet.fetch_all()
    beratungen = config.BERATUNGEN.read_bytes()
    _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht mit Befund: eine Seite
    assert [q.get("page", "1") for p, q, _ in oparl.anfragen if p == "/meetings"] == ["1"]
    vermerk = _zustand()["meetings_ohne_zeitfilter"]
    assert vermerk["meldung"].startswith("Zeitfilter auf Seite 1 nicht angewandt") and sessionnet._zeit(vermerk["zeit"])
    for nacht in (2, 3):
        _papers_inkrementell_geaendert(oparl, f"geändert {nacht}")
        oparl.anfragen.clear()
        sessionnet.fetch_all()
        assert not [p for p, *_ in oparl.anfragen if p == "/meetings"], nacht
        assert [q for p, q, _ in oparl.anfragen if p == "/papers"] and all(
            "modified_since" in q for p, q, _ in oparl.anfragen if p == "/papers")
        z = [r for r in _statistik() if r["liste"] == "meetings"][-1]
        assert (z["modus"], z["seiten"], z["anfragen"]) == ("übersprungen", "0", "0")
        assert z["ergebnis"].startswith("warnung: Zeitfilter bei Sitzungen nicht angewandt, Sitzungen nicht "
                                        f"aktualisiert (Befund vom {vermerk['zeit'][:10]}; ohne Anfrage übersprungen")
        p = [r for r in _statistik() if r["liste"] == "papers"][-1]
        assert (p["modus"], p["ergebnis"]) == ("inkrementell", "ok")
        assert sum(x["name"] == f"geändert {nacht}" for x in _jsonl(config.PAPERS)) == 1
        assert config.BERATUNGEN.read_bytes() == beratungen
        zustand, stand = _zustand(), _stand()
        assert not {"listenfehler", "letzter_abbruch", "sperre_verdacht"} & set(zustand)
        assert zustand["meetings_ohne_zeitfilter"] == vermerk and "abruf_ok" in stand and "abruf_hinweis" not in stand
        assert "ohne Anfrage übersprungen" in stand["abruf_warnungen"]["meetings"]["meldung"]
        # Runde 17c: auch die Meldung ohne Anfrage (_ohne_anfrage) nennt die Abhilfe
        assert ("übersprungen, letzter gültiger Stand bleibt) – bis die Liste einmal vollständig gelesen ist (Abhilfe: "
                "ein Lauf mit RATSATLAS_VOLLABRUF=meetings; =ja erreicht die Sitzungen erst nach dem fertigen Vollabruf "
                "der Vorlagen)") in stand["abruf_warnungen"]["meetings"]["meldung"]
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", vollabruf)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [q.get("page", "1") for p, q, _ in oparl.anfragen if p == "/meetings"] == ["1", "2"]
    assert not any("modified_since" in q for p, q, _ in oparl.anfragen if p == "/meetings")
    assert all(("modified_since" in q) == (vollabruf == "meetings") for p, q, _ in oparl.anfragen if p == "/papers")
    assert "meetings_ohne_zeitfilter" not in _zustand() and "abruf_warnungen" not in _stand()
    z = [r for r in _statistik() if r["liste"] == "meetings"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll", "ok")


def test_nur_warnung_liefert_den_letzten_gueltigen_stand(oparl, monkeypatch):
    """Endet die Sitzungsliste mit Warnung (Zeitfilter nicht angewandt), erhält beratungen() die Sitzungen des letzten
    gültigen Stands, nicht die gelesene ungefilterte Seite 1: Dort tragen die Sitzungen andere TOP-Kennungen. Die
    Beratungen bleiben unverändert."""
    sessionnet.fetch_all()
    vorher, roh = config.BERATUNGEN.read_bytes(), _jsonl(config.RAW / "meetings_roh.jsonl")
    m = oparl.meetings[0]
    oparl.meetings = [dict(m, agendaItem=[dict(t, id=t["id"] + "-neu") for t in m["agendaItem"]])]
    _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    erhalten, echt = [], sessionnet.beratungen

    def beratungen(papers, meetings, *weitere):
        erhalten.append(meetings)
        return echt(papers, meetings, *weitere)
    monkeypatch.setattr(sessionnet, "beratungen", beratungen)
    sessionnet.fetch_all()
    assert [r for r in _statistik() if r["liste"] == "meetings"][-1]["ergebnis"].startswith("warnung: Zeitfilter")
    assert erhalten == [roh] and not any(t["id"].endswith("-neu") for t in erhalten[0][0]["agendaItem"])
    assert config.BERATUNGEN.read_bytes() == vorher


@pytest.mark.parametrize("seite_1, art, seiten", [([], "liste", 6), (["a", "b"], "obergrenze", 3)])
def test_frischer_vollabruf_ohne_neue_objekte_bis_zur_grenze(monkeypatch, seite_1, art, seiten):
    """Frischer Vollabruf (keine Fortsetzung), Grenze je Lauf 6 Objekte: Bringen alle Seiten bis zur Grenze keine
    Objekte (leere Seiten mit links.next; g gilt als 1, also 6 Seiten), endet der Lauf mit Art `liste` (eine
    Fortsetzung käme nie voran), nicht mit `obergrenze`. Bringt nur die erste Seite neue Objekte, zählen sie als
    Fortschritt (ein frischer Lauf hat keine wiederholte Seite): `obergrenze` nach 3 Seiten zu 2."""
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", 6)
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "")

    def get_json(url, pausen=None):
        n = int(url.rsplit("=", 1)[1]) if "?s=" in url else 1
        return {"data": [{"id": i} for i in seite_1] if n == 1 else [],
                "links": {"next": f"http://127.0.0.1/l?s={n + 1}"}}
    monkeypatch.setattr(abruf, "get_json", get_json)
    with pytest.raises(sessionnet.Teilabbruch) as e:
        sessionnet.liste("http://127.0.0.1/l")
    assert (e.value.art, e.value.seiten, len(e.value.objekte)) == (art, seiten, len(seite_1))


def test_kuerzerer_stand_der_organisationen_ausdruecklich_angenommen(oparl, monkeypatch, capsys):
    """Organisationen unter 90 % des Stands: Die Warnung nennt die Abhilfe RATSATLAS_KUERZER_ANNEHMEN=organizations. Mit
    dieser Einstellung nimmt ein Lauf den kürzeren Stand an: organizations.json aktualisiert, Warnung entfällt,
    Vermerk im Log und in der Abrufstatistik. Danach (ohne Einstellung) gilt die 90-%-Regel gegenüber dem neuen
    Stand."""
    alle = oparl.orgs + [dict(oparl.orgs[1], id=f"{oparl.b}/organizations/{i}", name=f"Gremium {i}") for i in range(8)]
    oparl.orgs = list(alle)
    sessionnet.fetch_all()
    oparl.orgs = alle[:8]
    sessionnet.fetch_all()
    assert ("– Abhilfe, wenn der kürzere Stand stimmt (nicht bei 0 Objekten): ein Lauf mit "
            "RATSATLAS_KUERZER_ANNEHMEN=organizations" in _stand()["abruf_warnungen"]["organizations"]["meldung"])
    assert len(json.loads(config.ORGANIZATIONS.read_text())) == 10
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "organizations")
    capsys.readouterr()
    sessionnet.fetch_all()
    assert len(json.loads(config.ORGANIZATIONS.read_text())) == 8 and "abruf_warnungen" not in _stand()
    z = [r for r in _statistik() if r["liste"] == "organizations"][-1]
    assert z["ergebnis"] == "ok; kürzerer Stand angenommen: 8 statt bisher 10 (RATSATLAS_KUERZER_ANNEHMEN)"
    assert "organizations.jsonl: kürzerer Stand angenommen: 8 statt bisher 10" in capsys.readouterr().err
    monkeypatch.delenv("RATSATLAS_KUERZER_ANNEHMEN")
    oparl.orgs = alle[:7]                                                  # 7 von 8: wieder unter 90 %
    sessionnet.fetch_all()
    assert "nur 7 statt bisher 8" in _stand()["abruf_warnungen"]["organizations"]["meldung"]
    assert len(json.loads(config.ORGANIZATIONS.read_text())) == 8


@pytest.mark.parametrize("variable, wert, meldung", [
    ("RATSATLAS_KUERZER_ANNEHMEN", "organisationen", "RATSATLAS_KUERZER_ANNEHMEN: unbekannte Liste organisationen"),
    ("RATSATLAS_KUERZER_ANNEHMEN", "ja", "RATSATLAS_KUERZER_ANNEHMEN: unbekannte Liste ja (erlaubt: organizations, "
     "papers, meetings); keine Anfrage gesendet"),
    ("RATSATLAS_VOLLABRUF", "sitzungen", "RATSATLAS_VOLLABRUF: unbekannte Liste sitzungen"),
    ("RATSATLAS_VOLLABRUF", "ja,meetings", "RATSATLAS_VOLLABRUF: unbekannte Liste ja"),
    ("RATSATLAS_LIMIT", "0", "RATSATLAS_LIMIT='0' ist keine positive ganze Zahl"),
    ("RATSATLAS_LIMIT", "hundert", "RATSATLAS_LIMIT='hundert' ist keine positive ganze Zahl")])
def test_einstellungsfehler_vor_der_ersten_anfrage(oparl, monkeypatch, variable, wert, meldung):
    """Unbekannte Listen in RATSATLAS_KUERZER_ANNEHMEN oder RATSATLAS_VOLLABRUF (außer „ja“) und ein RATSATLAS_LIMIT,
    das keine positive ganze Zahl ist: Einstellungsfehler vor der ersten Anfrage (laut, kein Sperrverdacht)."""
    if variable == "RATSATLAS_LIMIT":
        monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", wert)
    else:
        monkeypatch.setenv(variable, wert)
    with pytest.raises(ValueError, match=re.escape(meldung)):
        sessionnet.fetch_all()
    assert oparl.anfragen == [] and "sperre_verdacht" not in _zustand()


@pytest.mark.parametrize("limit, mindestens", [("100", 1200), ("150", 1350), ("", 1200)])
def test_untergrenze_der_obergrenze_aus_der_seitengroesse(oparl, monkeypatch, limit, mindestens):
    """Untergrenze von RATSATLAS_MAX_OBJEKTE aus der eingestellten Seitengröße g: (ceil(1000 / g) + 2) · g, bei 100 also
    1200, bei 150 1350 (7 Seiten Verschiebung plus 2); ohne limit wie 100. Darunter Einstellungsfehler vor der ersten
    Anfrage, die Meldung nennt die Annahme; die Untergrenze selbst geht."""
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", limit)
    assert sessionnet.max_objekte_mindestens() == mindestens
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", mindestens - 1)
    g = limit or "100"
    with pytest.raises(ValueError, match=re.escape(
            f"RATSATLAS_MAX_OBJEKTE={mindestens - 1} liegt unter {mindestens} (zwei Seiten zu {g} plus die größte "
            f"Seitenverschiebung von 1000 Objekten, aufgerundet auf Seiten zu {g}; Annahme: der Server liefert {g} "
            "Objekte je Seite wie verlangt, RATSATLAS_LIMIT")):
        sessionnet.fetch_all()
    assert oparl.anfragen == []
    config.ZUSTAND.unlink()
    monkeypatch.setattr(config, "ABRUF_MAX_OBJEKTE", mindestens)
    sessionnet.fetch_all()
    assert [r["ergebnis"] for r in _statistik() if r["liste"] == "papers"][-1] == "ok"


def test_export_uebernimmt_gueltige_warnungen_der_nebenlisten(oparl, monkeypatch):
    """index.json (meta.abruf_warnungen) aus STAND.json: je Liste Zeitpunkt, Meldung und Stand der Liste (letzte
    reguläre Aktualisierung). Nur gültige: eine Warnung vor der letzten regulären Aktualisierung ihrer Liste entfällt,
    unbekannte Listen und Einträge ohne Meldung ebenso; ein unlesbarer Zeitpunkt wird gezeigt."""
    from pipeline import export
    w = {"zeit": "2026-11-09T22:30:00+00:00", "meldung": "Zeitfilter bei Sitzungen nicht angewandt"}
    stand = {"meetings": "2026-11-08T22:20:00+00:00", "organizations": "2026-11-09T22:40:00+00:00",
             "abruf_warnungen": {"meetings": w, "organizations": dict(w), "papers": dict(w), "x": "kaputt"}}
    assert export._abruf_warnungen(stand) == {"meetings": {**w, "stand": "2026-11-08T22:20:00+00:00"}}
    kaputt = {"zeit": "gestern", "meldung": "x"}
    assert export._abruf_warnungen({"organizations": "2026-11-09T22:40:00+00:00", "abruf_warnungen": {
        "organizations": kaputt, "meetings": {"zeit": w["zeit"]}}}) == {
        "organizations": {**kaputt, "stand": "2026-11-09T22:40:00+00:00"}}
    assert export._abruf_warnungen({}) == {} and export._abruf_warnungen({"abruf_warnungen": []}) == {}
    sessionnet.fetch_all()
    _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    sessionnet.fetch_all()                                                 # Warnung der Sitzungen
    build.build()
    export.export()
    meta = json.loads((config.EXPORT / config.STADT / "index.json").read_text())["meta"]
    assert list(meta["abruf_warnungen"]) == ["meetings"] and meta["abruf_fehler"] is None
    assert meta["abruf_warnungen"]["meetings"]["stand"] == _stand()["meetings"]
    assert meta["abruf_warnungen"]["meetings"]["meldung"].startswith("Zeitfilter bei Sitzungen nicht angewandt")


def test_seite_zeigt_warnungen_der_nebenlisten_im_datenstand():
    """site/app.js (standWarnungen, standFehler): je Liste ein Satz in einfacher Sprache im Datenstand, mit dem Stand
    der Liste oder „der letzte gültige Stand“; ohne Warnung und ohne Fehler nichts (der Text des Datenstands bleibt
    unverändert). Das Datum kommt aus dem vollen Zeitstempel in Europe/Berlin (Runde 17b; bis dahin die ersten zehn
    Zeichen des UTC-Werts: 23:30 UTC am 09.11. ergab 09.11. statt 10.11.); unlesbare Werte wie bisher (die ersten zehn
    Zeichen). Ausgeführt mit node (Funktionen und Formatierer aus app.js, Rechnerzone UTC und New York)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    js = (Path(__file__).resolve().parents[1] / "site" / "app.js").read_text(encoding="utf-8")
    teil = re.search(r"^  const ISO_DAY = .*?\n  const standFehler = .*?;\n", js, re.S | re.M)
    assert teil, "standWarnungen oder standFehler fehlt in site/app.js"
    # im Datenstand (Runde 17c: über standText, test_datenstand_mit_einer_datumsregel)
    assert "    $(\"#stand\").textContent = standText(meta, index && index.meta);\n" in js
    warnungen = [None, {}, {"papers": {"stand": "2026-11-08"}}, {"meetings": {"stand": "2026-11-08T22:20:00+00:00"}},
                 {"organizations": {"stand": None}, "meetings": {"stand": "2026-11-08T22:20:00+00:00"}},
                 {"meetings": {"stand": "2026-11-09T23:30:00+00:00"}}, {"meetings": {"stand": "2026-11-09"}},
                 {"organizations": {"stand": "2026-11-09 kaputt"}}]
    fehler = [None, {"zeit": "2026-11-09T23:30:00+00:00"}, {"zeit": "2026-11-09T22:59:59+00:00"},
              {"zeit": "2026-11-09 kaputt"}]
    code = (teil.group(0) + f"console.log(JSON.stringify([{json.dumps(warnungen)}.map(standWarnungen), "
                            f"{json.dumps(fehler)}.map(standFehler)]));")
    sitzungen = " · Sitzungstermine wurden beim letzten Abruf nicht aktualisiert; gezeigt wird "
    gremien = " · Die Liste der Gremien wurde beim letzten Abruf nicht aktualisiert; gezeigt wird "
    fehlgeschlagen = " ist fehlgeschlagen; gezeigt wird der letzte gültige Datenstand."
    for zone in ("UTC", "America/New_York"):
        r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "TZ": zone})
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout) == [
            ["", "", "", sitzungen + "der Stand vom 08.11.2026.",
             sitzungen + "der Stand vom 08.11.2026." + gremien + "der letzte gültige Stand.",
             sitzungen + "der Stand vom 10.11.2026.", sitzungen + "der Stand vom 09.11.2026.",
             gremien + "der Stand vom 09.11.2026."],
            ["", " · Der letzte Abruf am 10.11.2026" + fehlgeschlagen,
             " · Der letzte Abruf am 09.11.2026" + fehlgeschlagen,
             " · Der letzte Abruf am 09.11.2026" + fehlgeschlagen]], zone


# --- Runde 17b: RATSATLAS_KUERZER_ANNEHMEN enger (nie 0 Objekte; Beratungen nur nach einem in diesem Lauf angenommenen
# kürzeren Stand der Vorlagen oder Sitzungen), Fortsetzung der Sitzungen nach dem Befund ohne Zeitfilter ---------------

def _gremien(oparl, anzahl=10):
    """`anzahl` Organisationen: die zwei des Testservers und erfundene Gremien."""
    return oparl.orgs[:2] + [dict(oparl.orgs[1], id=f"{oparl.b}/organizations/{i}", name=f"Gremium {i}")
                             for i in range(anzahl - 2)]


def test_kuerzer_annehmen_lockert_nur_die_genannte_liste(oparl, monkeypatch):
    """RATSATLAS_KUERZER_ANNEHMEN=organizations lockert nur die Organisationen: Ein Vollabruf der Vorlagen unter 90 %
    des Stands (RATSATLAS_VOLLABRUF=papers, 3 von 5) bricht weiter ab (Art `leer`); papers.jsonl und Beratungen
    bleiben."""
    sessionnet.fetch_all()
    vorher = {f: f.read_bytes() for f in (config.PAPERS, config.BERATUNGEN)}
    oparl.papers = oparl.papers[:3]
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "organizations")
    sessionnet.fetch_all()
    assert vorher == {f: f.read_bytes() for f in vorher}
    assert _stand()["abruf_fehler"]["meldung"] == ("papers.jsonl: nur 3 statt bisher 5 – unvollständige Antwort? "
                                                   "Vorhandener Stand bleibt.")
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert z["modus"] == "voll" and z["ergebnis"].startswith("abbruch: papers.jsonl: nur 3 statt bisher 5")


@pytest.mark.parametrize("kuerzer", ["organizations", "papers", "organizations,papers,meetings"])
def test_beratungen_nur_nach_angenommenem_kuerzerem_stand_gelockert(oparl, monkeypatch, kuerzer):
    """Die 90-%-Prüfung der Beratungen entfällt nur, wenn dieser Lauf für papers oder meetings tatsächlich einen
    kürzeren Stand angenommen hat (Runde 17: schon, wenn papers oder meetings in RATSATLAS_KUERZER_ANNEHMEN stand).
    Inkrementeller Lauf, drei Vorlagen ohne Beratung (2 von 5 Beratungen), Vorlagen und Sitzungen nicht kürzer: Abbruch
    `leer`, beratungen.jsonl bleibt. Ein angenommener kürzerer Stand der Organisationen lockert sie nicht."""
    oparl.orgs = _gremien(oparl)
    sessionnet.fetch_all()
    beratungen, zeit = config.BERATUNGEN.read_bytes(), _zustand()["papers"]
    for i in range(3):
        oparl.papers[i] = dict(oparl.papers[i], consultation=[], modified=zeit)
    if "organizations" in kuerzer:
        oparl.orgs = oparl.orgs[:8]                                        # 8 von 10, angenommen
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", kuerzer)
    sessionnet.fetch_all()
    assert config.BERATUNGEN.read_bytes() == beratungen
    assert _stand()["abruf_fehler"]["meldung"] == "Beratungen: nur 2 statt bisher 5"
    orgs = "ok; kürzerer Stand angenommen: 8 statt bisher 10 (RATSATLAS_KUERZER_ANNEHMEN)"
    assert [(r["liste"], r["modus"], r["ergebnis"]) for r in _statistik()[-3:]] == [
        ("organizations", "voll", orgs if "organizations" in kuerzer else "ok"), ("papers", "inkrementell", "ok"),
        ("meetings", "inkrementell", "ok")]
    assert len(json.loads(config.ORGANIZATIONS.read_text())) == (8 if "organizations" in kuerzer else 10)
    assert "beratungen_kuerzer_erlaubt" not in _zustand()   # Runde 17c: nur genannt oder Organisationen: kein Vermerk


def test_kuerzerer_stand_der_vorlagen_mit_beratungen_angenommen(oparl, monkeypatch, capsys):
    """RATSATLAS_KUERZER_ANNEHMEN=papers mit einem kürzeren Vollabruf der Vorlagen (RATSATLAS_VOLLABRUF=papers, 3 von
    5): Vorlagen und die daraus abgeleiteten Beratungen (3 von 5) gelten, vermerkt in Abrufstatistik und Log; der Lauf
    ist vollständig."""
    sessionnet.fetch_all()
    oparl.papers = oparl.papers[:3]
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "papers")
    capsys.readouterr()
    sessionnet.fetch_all()
    assert len(_jsonl(config.PAPERS)) == 3 and len(_jsonl(config.BERATUNGEN)) == 3
    assert "abruf_fehler" not in _stand() and "letzter_abbruch" not in _zustand()
    z = [r for r in _statistik() if r["liste"] == "papers"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll", "ok; kürzerer Stand angenommen: 3 statt bisher 5 "
                                                   "(RATSATLAS_KUERZER_ANNEHMEN)")
    fehler = capsys.readouterr().err
    assert "papers.jsonl: kürzerer Stand angenommen: 3 statt bisher 5 (RATSATLAS_KUERZER_ANNEHMEN)" in fehler
    assert "Beratungen: kürzerer Stand angenommen: 3 statt bisher 5 (RATSATLAS_KUERZER_ANNEHMEN)" in fehler


@pytest.mark.parametrize("geloescht", [False, True])
@pytest.mark.parametrize("liste", ["organizations", "papers"])
def test_leerer_vollabruf_wird_nie_angenommen(oparl, monkeypatch, liste, geloescht):
    """Ein Vollabruf ohne Objekte gilt nie, auch nicht mit RATSATLAS_KUERZER_ANNEHMEN für diese Liste (Art `leer`): Die
    Organisationen enden mit Warnung (letzter gültiger Stand, Vorlagen und Sitzungen laufen), die Vorlagen brechen ab;
    der Stand bleibt. Runde 17c: Es zählen nur nicht gelöschte Objekte; ein Vollabruf nur mit `deleted: true` (so viele
    wie bisher, über 90 %) gilt als leer."""
    sessionnet.fetch_all()
    datei, bisher = (config.ORGANIZATIONS, 2) if liste == "organizations" else (config.PAPERS, 5)
    vorher = datei.read_bytes()
    if liste == "organizations":
        oparl.orgs = [dict(o, deleted=True) for o in oparl.orgs] if geloescht else []
    else:
        oparl.papers = [dict(p, deleted=True) for p in oparl.papers] if geloescht else []
        monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", liste)
    sessionnet.fetch_all()
    assert datei.read_bytes() == vorher
    text = (f"{liste}.jsonl: nur 0 statt bisher {bisher} – unvollständige Antwort? Vorhandener Stand bleibt. "
            + (f"Geliefert: nur gelöschte Objekte ({bisher}). " if geloescht else "")
            + "Ein leerer Vollabruf wird nie angenommen, auch nicht mit RATSATLAS_KUERZER_ANNEHMEN.")
    stand = _stand()
    if liste == "organizations":
        assert text in stand["abruf_warnungen"]["organizations"]["meldung"] and "abruf_fehler" not in stand
        assert [(r["liste"], r["ergebnis"]) for r in _statistik()[-2:]] == [("papers", "ok"), ("meetings", "ok")]
    else:
        assert stand["abruf_fehler"]["meldung"] == text


def test_vollabruf_der_sitzungen_ueber_eine_fortsetzung_hebt_den_befund_auf(oparl, monkeypatch):
    """Vermerk meetings_ohne_zeitfilter, dann ein Lauf mit RATSATLAS_VOLLABRUF=meetings, der am Ende des Zeitfensters
    vor Seite 2 der Sitzungen abbricht (Fortsetzung gespeichert, Vermerk und Warnung bleiben), dann eine Nacht ohne
    Einstellung: Die Fortsetzung fragt die Sitzungen an (Seite 1 wiederholt, dann Seite 2, ohne modified_since), statt
    sie wegen des Vermerks ohne Anfrage zu überspringen; danach sind Fortsetzung, Vermerk und Warnung entfernt. Die
    Warnung nennt als Abhilfe RATSATLAS_VOLLABRUF=meetings und =ja nur mit Zusatz."""
    m = oparl.meetings[0]
    oparl.meetings = [dict(m, id=f"{oparl.b}/meetings/{i}", name=f"Sitzung {i}") for i in (2, 3)] + [m]   # 2 Seiten
    sessionnet.fetch_all()
    _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    sessionnet.fetch_all()                                                 # Befund: Vermerk und Warnung
    assert "meetings_ohne_zeitfilter" in _zustand()
    assert ("(Abhilfe: ein Lauf mit RATSATLAS_VOLLABRUF=meetings; =ja erreicht die Sitzungen erst nach dem fertigen "
            "Vollabruf der Vorlagen)") in _stand()["abruf_warnungen"]["meetings"]["meldung"]
    echt, einmal = abruf.get_json, []

    def get_json(url, pausen=None):   # Ende des Zeitfensters vor Seite 2 der Sitzungen, einmal
        if "/meetings" in url and "page=2" in url and not einmal:
            einmal.append(url)
            raise _ende_fenster()
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "meetings")
    sessionnet.fetch_all()                                                 # Vollabruf der Sitzungen bis Seite 1
    zustand, stand = _zustand(), _stand()
    assert einmal and {"meetings_fortsetzung", "meetings_ohne_zeitfilter"} <= set(zustand)
    assert "meetings" in stand["abruf_warnungen"] and "Zeitfenster endete" in stand["abruf_hinweis"]["meldung"]
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                                 # Nacht ohne Einstellung: Fortsetzung
    assert [q.get("page", "1") for p, q, _ in oparl.anfragen if p == "/meetings"] == ["1", "2"]
    assert not any("modified_since" in q for p, q, _ in oparl.anfragen if p == "/meetings")
    zustand, stand = _zustand(), _stand()
    assert not {"meetings_fortsetzung", "meetings_ohne_zeitfilter"} & set(zustand)
    assert not {"abruf_warnungen", "abruf_hinweis", "abruf_fehler"} & set(stand)
    z = [r for r in _statistik() if r["liste"] == "meetings"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll, fortgesetzt", "ok")


# --- Runde 17c: Ein angenommener kürzerer Stand der Vorlagen oder Sitzungen blockiert die Beratungen nicht dauerhaft
# (Vermerk beratungen_kuerzer_erlaubt), RATSATLAS_KUERZER_ANNEHMEN=meetings, leere Beratungen nie --------------------

def _sitzungen_enden_am_fenster(monkeypatch):
    """abruf.get_json, das vor jeder Anfrage an die Sitzungen das Ende des Zeitfensters meldet (nach dem Schreiben von
    papers.jsonl, vor beratungen()); liefert die echte Funktion."""
    echt = abruf.get_json

    def get_json(url, pausen=None):
        if "/meetings" in url:
            raise _ende_fenster()
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)
    return echt


def _kuerzere_vorlagen_angenommen(oparl, monkeypatch, vorlagen):
    """Lauf mit RATSATLAS_VOLLABRUF=papers und RATSATLAS_KUERZER_ANNEHMEN=papers, Vorlagen `vorlagen` (unter 90 %);
    danach beide Einstellungen entfernt."""
    oparl.papers = vorlagen
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "papers")
    sessionnet.fetch_all()
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    monkeypatch.delenv("RATSATLAS_KUERZER_ANNEHMEN")


@pytest.mark.parametrize("abbrueche, vermerk", [(1, True), (2, True), (1, False)])
def test_angenommener_kuerzerer_stand_blockiert_die_beratungen_nicht(oparl, monkeypatch, capsys, abbrueche, vermerk):
    """Vorlagen 3 von 5 mit RATSATLAS_KUERZER_ANNEHMEN=papers angenommen und geschrieben, dann enden die Sitzungen am
    Ende des Zeitfensters (vor beratungen()). Der Vermerk beratungen_kuerzer_erlaubt (Zeit, Listen) steht im Zustand
    und bleibt bei einem erneuten Abbruch vor beratungen() in einer Folgenacht ohne Einstellung stehen. Die erste Nacht
    ohne Einstellung, die die Beratungen erreicht, leitet sie ab (3 von 5; bis Runde 17b jede Folgenacht `leer`) und
    entfernt den Vermerk erst danach. Ohne Vermerk (hier entfernt) und ohne Annahme in diesem Lauf weiter `leer`."""
    sessionnet.fetch_all()
    beratungen = config.BERATUNGEN.read_bytes()
    echt = _sitzungen_enden_am_fenster(monkeypatch)
    _kuerzere_vorlagen_angenommen(oparl, monkeypatch, oparl.papers[:3])
    for _ in range(abbrueche - 1):                                        # Folgenacht ohne Einstellung, Abbruch
        sessionnet.fetch_all()
    assert len(_jsonl(config.PAPERS)) == 3 and config.BERATUNGEN.read_bytes() == beratungen
    eintrag = _zustand()["beratungen_kuerzer_erlaubt"]
    assert eintrag["listen"] == ["papers"] and sessionnet._zeit(eintrag["zeit"])
    assert "Zeitfenster endete" in _stand()["abruf_hinweis"]["meldung"] and "abruf_fehler" not in _stand()
    if not vermerk:
        sessionnet._zustand_setzen("beratungen_kuerzer_erlaubt", None)
    monkeypatch.setattr(abruf, "get_json", echt)
    capsys.readouterr()
    sessionnet.fetch_all()                                                 # Nacht ohne Einstellung bis beratungen()
    if not vermerk:
        assert config.BERATUNGEN.read_bytes() == beratungen
        assert _stand()["abruf_fehler"]["meldung"] == "Beratungen: nur 3 statt bisher 5"
        return
    assert len(_jsonl(config.BERATUNGEN)) == 3 and "beratungen_kuerzer_erlaubt" not in _zustand()
    assert not {"abruf_fehler", "abruf_hinweis"} & set(_stand())
    assert ("Beratungen: kürzerer Stand angenommen: 3 statt bisher 5 (RATSATLAS_KUERZER_ANNEHMEN; Vermerk "
            "beratungen_kuerzer_erlaubt eines früheren Laufs: papers)") in capsys.readouterr().err


@pytest.mark.parametrize("liste", ["papers", "meetings"])
def test_vermerk_bleibt_bis_beratungen_geschrieben_sind(oparl, monkeypatch, liste):
    """Scheitert das Schreiben von beratungen.jsonl (hier OSError, Programmfehler), bleibt der Vermerk
    beratungen_kuerzer_erlaubt stehen; der nächste Lauf ohne Einstellung leitet die Beratungen ab und entfernt ihn.
    Ebenso für die Sitzungen (Runde 17d: RATSATLAS_VOLLABRUF=meetings und RATSATLAS_KUERZER_ANNEHMEN=meetings,
    Sitzungen 8 von 10 angenommen, der Lauf endet vor dem Schreiben der Beratungen 3 von 5)."""
    if liste == "meetings":
        _sitzungen_je_vorlage(oparl)
    sessionnet.fetch_all()
    echt = sessionnet._write

    def schreiben(pfad, text):
        if pfad == config.BERATUNGEN:
            raise OSError("Datenträger voll (Test)")
        return echt(pfad, text)
    monkeypatch.setattr(sessionnet, "_write", schreiben)
    with pytest.raises(OSError):
        if liste == "papers":
            _kuerzere_vorlagen_angenommen(oparl, monkeypatch, oparl.papers[:3])
        else:
            oparl.meetings = [m for m in oparl.meetings if not m["id"].endswith(("/meetings/4", "/meetings/5"))]
            monkeypatch.setenv("RATSATLAS_VOLLABRUF", "meetings")
            monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "meetings")
            sessionnet.fetch_all()
    if liste == "meetings":
        assert len(json.loads(config.MEETINGS.read_text())) == 8
    assert _zustand()["beratungen_kuerzer_erlaubt"]["listen"] == [liste] and len(_jsonl(config.BERATUNGEN)) == 5
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    monkeypatch.delenv("RATSATLAS_KUERZER_ANNEHMEN")
    monkeypatch.setattr(sessionnet, "_write", echt)
    sessionnet.fetch_all()
    assert len(_jsonl(config.BERATUNGEN)) == 3 and "beratungen_kuerzer_erlaubt" not in _zustand()


@pytest.mark.parametrize("wert", ["x", {"listen": "papers"}, {"listen": ["organizations"]}])
def test_unpassender_vermerk_lockert_die_beratungen_nicht(oparl, monkeypatch, wert):
    """Runde 17d: Ein von Hand gesetzter Vermerk beratungen_kuerzer_erlaubt ohne papers oder meetings in einer Liste
    (kein Objekt, `listen` als Zeichenkette, nur organizations) lockert die 90-%-Prüfung der Beratungen nicht.
    Inkrementeller Lauf, drei Vorlagen ohne Beratung (2 von 5): Abbruch `leer`, beratungen.jsonl und Vermerk bleiben."""
    sessionnet.fetch_all()
    beratungen, zeit = config.BERATUNGEN.read_bytes(), _zustand()["papers"]
    for i in range(3):
        oparl.papers[i] = dict(oparl.papers[i], consultation=[], modified=zeit)
    sessionnet._zustand_setzen("beratungen_kuerzer_erlaubt", wert)
    sessionnet.fetch_all()
    assert config.BERATUNGEN.read_bytes() == beratungen
    assert _stand()["abruf_fehler"]["meldung"] == "Beratungen: nur 2 statt bisher 5"
    assert _zustand()["beratungen_kuerzer_erlaubt"] == wert


def test_leerer_beratungsstand_wird_nie_angenommen(oparl, monkeypatch):
    """Vorlagen 3 von 5 angenommen (RATSATLAS_KUERZER_ANNEHMEN=papers), aber ohne Beratungen: 0 statt bisher 5 gilt
    nie, auch gelockert nicht (Abbruch `leer`, beratungen.jsonl bleibt); der Vermerk bleibt stehen."""
    sessionnet.fetch_all()
    beratungen = config.BERATUNGEN.read_bytes()
    _kuerzere_vorlagen_angenommen(oparl, monkeypatch, [dict(p, consultation=[]) for p in oparl.papers[:3]])
    assert len(_jsonl(config.PAPERS)) == 3 and config.BERATUNGEN.read_bytes() == beratungen
    assert _stand()["abruf_fehler"]["meldung"] == ("Beratungen: nur 0 statt bisher 5 (ein leerer Stand wird nie "
                                                   "angenommen, auch nicht mit RATSATLAS_KUERZER_ANNEHMEN)")
    assert _zustand()["beratungen_kuerzer_erlaubt"]["listen"] == ["papers"]


def _sitzungen_je_vorlage(oparl, anzahl=10):
    """Je Vorlage i eine Sitzung i mit TOP i (die Beratung der Vorlage verweist darauf), dazu Sitzungen ohne TOP bis
    `anzahl`."""
    m, tops = oparl.meetings[0], oparl.meetings[0]["agendaItem"]
    oparl.meetings = [dict(m, id=f"{oparl.b}/meetings/{i}", name=f"Sitzung {i}",
                           agendaItem=[tops[i - 1]] if i <= len(tops) else []) for i in range(1, anzahl + 1)]
    for i, p in enumerate(oparl.papers, 1):
        p["consultation"] = [dict(p["consultation"][0], meeting=f"{oparl.b}/meetings/{i}")]


def test_kuerzerer_stand_der_sitzungen_mit_beratungen_angenommen(oparl, monkeypatch, capsys):
    """RATSATLAS_VOLLABRUF=meetings und RATSATLAS_KUERZER_ANNEHMEN=meetings, Sitzungen 8 von 10 und daraus Beratungen 3
    von 5 (Sitzungen der Vorlagen 4 und 5 fehlen): beide angenommen, vermerkt in Log und Abrufstatistik; der Lauf ist
    vollständig, kein Vermerk bleibt im Zustand."""
    _sitzungen_je_vorlage(oparl)
    sessionnet.fetch_all()
    assert len(_jsonl(config.BERATUNGEN)) == 5
    oparl.meetings = [m for m in oparl.meetings if not m["id"].endswith(("/meetings/4", "/meetings/5"))]
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "meetings")
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "meetings")
    capsys.readouterr()
    sessionnet.fetch_all()
    assert len(json.loads(config.MEETINGS.read_text())) == 8 and len(_jsonl(config.BERATUNGEN)) == 3
    assert not {"abruf_fehler", "abruf_hinweis"} & set(_stand())
    assert not {"letzter_abbruch", "beratungen_kuerzer_erlaubt"} & set(_zustand())
    z = [r for r in _statistik() if r["liste"] == "meetings"][-1]
    assert (z["modus"], z["ergebnis"]) == ("voll", "ok; kürzerer Stand angenommen: 8 statt bisher 10 "
                                                   "(RATSATLAS_KUERZER_ANNEHMEN)")
    fehler = capsys.readouterr().err
    assert "meetings_roh.jsonl: kürzerer Stand angenommen: 8 statt bisher 10 (RATSATLAS_KUERZER_ANNEHMEN)" in fehler
    assert "Beratungen: kürzerer Stand angenommen: 3 statt bisher 5 (RATSATLAS_KUERZER_ANNEHMEN)\n" in fehler


def test_datenstand_mit_einer_datumsregel():
    """site/app.js (standText, zeitDatum; Runde 17c): Im Datenstand stehen auch das Abrufdatum der Quellen
    („Ratsinformationssystem: …“, retrieved_at) und „erzeugt …“ (generated_at) als Datum des vollen Zeitstempels in
    Europe/Berlin (23:30 UTC am 09.11. → 10.11.2026), wie Fehler und Warnungen. Ist ein Wert auch in den ersten zehn
    Zeichen kein Datum (null, undefined, „kaputt“, 2026-13-45), „unbekannt“ statt eines RangeError; der Datenstand
    entsteht immer. Ohne Warnung und Fehler ist der Text bis auf die Datumsregel unverändert (Vergleich mit der Formel
    bis Runde 17b bei Werten am Tag). Ausgeführt mit node (Rechnerzone UTC und New York)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    js = (Path(__file__).resolve().parents[1] / "site" / "app.js").read_text(encoding="utf-8")
    teil = re.search(r"^  const ISO_DAY = .*?\n  const standText = .*?\n  };\n", js, re.S | re.M)
    namen = re.search(r"^  const QUELLE_NAME = .*?;\n", js, re.S | re.M)
    assert teil and namen, "standText, zeitDatum oder QUELLE_NAME fehlt in site/app.js"
    # Formel bis Runde 17b (ohne Fehler und Warnungen): erste zehn Zeichen des UTC-Werts
    alt = ("const alt = (m) => { const stand = m.sources.filter((s) => s.retrieved_at).map((s) => `${QUELLE_NAME[s.name] "
           "|| s.name}: ${fmtDate(String(s.retrieved_at).slice(0, 10))}`).join(\" · \"); return `Datenstand: ${stand || "
           "\"–\"}${m.generated_at ? ` · erzeugt ${fmtDate(m.generated_at.slice(0, 10))}` : \"\"}`; };\n")
    tag = [{"sources": [{"name": "oparl-koeln", "retrieved_at": "2026-11-09T12:00:00+00:00"},
                        {"name": "geo-koeln", "retrieved_at": "2026-11-04"}, {"name": "osm"},
                        {"name": "kontext-x", "retrieved_at": "2026-11-07T21:59:00+00:00"}],
            "generated_at": "2026-11-09T12:10:00+00:00"},
           {"sources": [], "generated_at": "2026-11-09T05:00:00+00:00"},
           {"sources": [{"name": "oparl-koeln", "retrieved_at": "2026-11-08"}]}]
    nacht = {"sources": [{"name": "oparl-koeln", "retrieved_at": "2026-11-09T23:30:00+00:00"}],
             "generated_at": "2026-11-09T23:45:00+00:00"}
    kaputt = {"sources": [{"name": "oparl-koeln", "retrieved_at": "kaputt"}, {"name": "geo-koeln", "retrieved_at": 7}],
              "generated_at": "2026-13-45T00:00:00+00:00"}
    code = (namen.group(0) + teil.group(0) + alt
            + f"const tag = {json.dumps(tag)};\n"
            + "console.log(JSON.stringify([tag.map((m) => [standText(m, null), standText(m, {}), alt(m)]), "
            + f"standText({json.dumps(nacht)}, {{}}), standText({json.dumps(kaputt)}, {{}}), "
            + "standText({}, {abruf_fehler: {zeit: null}}), "
            + "[null, undefined, 'kaputt', '2026-13-45', '', 0, '2026-11-09 kaputt'].map(zeitDatum)]));")
    for zone in ("UTC", "America/New_York"):
        r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "TZ": zone})
        assert r.returncode == 0, r.stderr
        gleich, n, k, ohne, werte = json.loads(r.stdout)
        assert [a for a, b, c in gleich if not a == b == c] == [], zone
        assert gleich[0][0] == ("Datenstand: Ratsinformationssystem: 09.11.2026 · Gebiete: 04.11.2026 · kontext-x: "
                                "07.11.2026 · erzeugt 09.11.2026"), zone
        assert n == "Datenstand: Ratsinformationssystem: 10.11.2026 · erzeugt 10.11.2026", zone
        assert k == "Datenstand: Ratsinformationssystem: unbekannt · Gebiete: unbekannt · erzeugt unbekannt", zone
        assert ohne == ("Datenstand: – · Der letzte Abruf am unbekannt ist fehlgeschlagen; gezeigt wird der letzte "
                        "gültige Datenstand."), zone
        assert werte == ["unbekannt"] * 6 + ["09.11.2026"], zone


# --- Runde 17d: Datenstand (#stand, dataStand) nur aus lesbaren Werten, Zeitstempel ohne Zone als UTC --------------

def _app_js_teil(muster):
    js = (Path(__file__).resolve().parents[1] / "site" / "app.js").read_text(encoding="utf-8")
    teile = [re.search(m, js, re.S | re.M) for m in muster]
    assert all(teile), f"Abschnitt fehlt in site/app.js: {muster}"
    return js, "".join(t.group(0) for t in teile)


def _node_json(code, zone):
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60, env={**os.environ, "TZ": zone})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _mit_oparl(wert, erzeugt=None):
    """meta mit einer Gebietsquelle und der OParl-Quelle (retrieved_at `wert`), generated_at nur, wenn angegeben."""
    return {"sources": [{"name": "geo-koeln", "retrieved_at": "2026-11-01"}, {"name": "oparl-koeln", "retrieved_at": wert}],
            **({"generated_at": erzeugt} if erzeugt is not None else {})}


def test_datenstand_nur_aus_lesbarem_wert():
    """site/app.js (standTag, zeitTag, loadArea): Der Datenstand (dataStand: Markierung in der Zeitleiste, Jahresgrenze
    in hasPaperFeed) ist der Berliner Kalendertag nach derselben Regel wie zeitDatum, gebildet nur aus einem lesbaren
    Wert: retrieved_at der OParl-Quelle, sonst generated_at, sonst heute. Ein unlesbares retrieved_at („kaputt“, Zahl,
    Objekt) brachte bis Runde 17c loadArea zum Absturz (`.slice` auf Zahl oder Objekt) oder ergab einen ungültigen
    Stand; #stand zeigt dann „unbekannt“ und wird vor tl.setData gesetzt. Zeitstempel ohne Zone gelten als UTC (das
    Datum hängt nicht von der Zone des Rechners ab). Ausgeführt mit node (Rechnerzone UTC und Tokio)."""
    js, teil = _app_js_teil([r"^  const QUELLE_NAME = .*?;\n", r"^  const heute = .*?\n  const standTag = .*?\n  };\n"])
    lade = re.search(r"^  async function loadArea\(.*?\n  }\n", js, re.S | re.M).group(0)
    stand = "    $(\"#stand\").textContent = standText(meta, index && index.meta);\n"
    assert "    dataStand = standTag(meta);\n" in lade and lade.count(stand) == 1
    assert lade.index("dataStand = standTag(meta);") < lade.index(stand) < lade.index("tl.setData(")
    faelle = [_mit_oparl("kaputt", "2026-11-09T23:30:00+00:00"), _mit_oparl(7, "2026-11-08T10:00:00+00:00"),
              _mit_oparl({"a": 1}, "2026-11-07"), _mit_oparl("kaputt"), _mit_oparl(20261109), _mit_oparl({}, "kaputt"),
              {}, None, {"sources": "kaputt", "generated_at": 5},
              _mit_oparl("2026-12-31T23:30:00+00:00", "kaputt"), _mit_oparl("2026-12-31T23:30:00"),
              _mit_oparl("2026-11-09T00:30:00"), _mit_oparl("2026-11-09 23:30:00"), _mit_oparl("2026-11-09"),
              _mit_oparl("2026-11-05T10:00:00+00:00", "2026-11-09T10:00:00+00:00")]
    code = (teil + f"const faelle = {json.dumps(faelle)};\n"
            + "console.log(JSON.stringify([heute(), faelle.map(standTag), "
            + "['kaputt', 7, {}].map((w) => standText({sources: [{name: 'oparl-koeln', retrieved_at: w}]}, {})), "
            + "['2026-11-09T23:30:00', '2026-11-09T00:30:00', '2026-11-09 23:30:00', '2026-11-09T23:30:00.123456', "
            + "'2026-11-09T23:30:00+09:00', '2026-11-09T23:30:00Z', '2026-11-09'].map(zeitDatum)]));")
    for zone in ("UTC", "Asia/Tokyo"):
        heute, tage, texte, daten = _node_json(code, zone)
        assert tage == ["2026-11-10", "2026-11-08", "2026-11-07", heute, heute, heute, heute, heute, heute,
                        "2027-01-01", "2027-01-01", "2026-11-09", "2026-11-10", "2026-11-09", "2026-11-05"], zone
        assert texte == ["Datenstand: Ratsinformationssystem: unbekannt"] * 3, zone
        assert daten == ["10.11.2026", "09.11.2026", "10.11.2026", "10.11.2026", "09.11.2026", "10.11.2026",
                         "09.11.2026"], zone


def test_datenstand_mit_warnung_vollstaendig():
    """site/app.js (standText mit index.json meta.abruf_warnungen und abruf_fehler): der vollständige Text des
    Datenstands mit Warnsatz, Datum des vollen Zeitstempels in Europe/Berlin (23:30 UTC am 09.11. → 10.11.2026).
    Ausgeführt mit node (Rechnerzone UTC und Tokio)."""
    _, teil = _app_js_teil([r"^  const QUELLE_NAME = .*?;\n", r"^  const ISO_DAY = .*?\n  const standText = .*?\n  };\n"])
    m = {"sources": [{"name": "oparl-koeln", "retrieved_at": "2026-11-09T22:10:00+00:00"}],
         "generated_at": "2026-11-09T22:40:00+00:00"}
    warnung = {"abruf_warnungen": {"meetings": {"stand": "2026-11-09T23:30:00+00:00", "zeit": "2026-11-09T23:35:00+00:00",
                                                "meldung": "Zeitfilter bei Sitzungen nicht angewandt"}}}
    beides = {**warnung, "abruf_fehler": {"zeit": "2026-11-09T23:50:00+00:00", "meldung": "x"}}
    code = (teil + f"console.log(JSON.stringify([standText({json.dumps(m)}, {json.dumps(warnung)}), "
            + f"standText({json.dumps(m)}, {json.dumps(beides)})]));")
    satz = "Sitzungstermine wurden beim letzten Abruf nicht aktualisiert; gezeigt wird der Stand vom 10.11.2026."
    for zone in ("UTC", "Asia/Tokyo"):
        nur, mit_fehler = _node_json(code, zone)
        assert nur == f"Datenstand: Ratsinformationssystem: 09.11.2026 · erzeugt 09.11.2026 · {satz}", zone
        assert mit_fehler == ("Datenstand: Ratsinformationssystem: 09.11.2026 · erzeugt 09.11.2026 · Der letzte Abruf "
                              f"am 10.11.2026 ist fehlgeschlagen; gezeigt wird der letzte gültige Datenstand. · {satz}"), zone


# --- Runde 17e: Jahresgrenze der Vorgangs-Feeds in Pipeline und Seite, Quellenliste im Vorgang -------------------------

def test_jahresgrenze_der_vorgangs_feeds_wie_auf_der_seite():
    """pipeline/export.py (feed_grenze, berliner_tag) und site/app.js (standTag, hasPaperFeed): Die Jahresgrenze der
    Feeds je Vorlage ist der 1. Januar des Vorjahres des Berliner Kalendertags von retrieved_at (Zeitstempel ohne Zone
    als UTC; unlesbar heute). Bis Runde 17d nahm die Pipeline das Jahr aus den ersten vier Zeichen (UTC): Ein Abruf am
    31.12.2026 um 23:30 UTC ergab dort 2026, auf der Seite 2027. Mitten im Jahr bleibt die Grenze unverändert.
    Ausgeführt mit node (Rechnerzone UTC und Tokio)."""
    from pipeline import export, publish
    quelle = (Path(__file__).resolve().parents[1] / "pipeline" / "export.py").read_text(encoding="utf-8")
    assert "publish.write_feeds(out / \"feeds\", areas, cache, names, home, slug, feed_grenze(stand))\n" in quelle
    _, teil = _app_js_teil([r"^  const heute = .*?\n  const standTag = .*?\n  };\n", r"^  const hasPaperFeed = .*?;\n"])
    werte = ["2026-12-31T23:30:00+00:00", "2026-12-31T23:30:00", "2026-12-31T22:30:00+00:00",
             "2026-06-15T10:00:00+00:00", "2026-06-15", "kaputt", "", 7, None]
    vorlagen = [{"date": d, "stand": "beschlossen"} for d in ("2025-12-31", "2026-01-01")]
    code = ("let index = {}, dataStand;\n" + teil + f"const werte = {json.dumps(werte)};\n"
            + f"const vorlagen = {json.dumps(vorlagen)};\n"
            + "console.log(JSON.stringify([heute(), werte.map((w) => { dataStand = standTag({sources: [{name: "
            + "'oparl-koeln', retrieved_at: w}]}); return [dataStand.slice(0, 4), vorlagen.map(hasPaperFeed)]; })]));")
    grenzen = [export.feed_grenze(w) for w in werte]
    assert grenzen[:5] == ["2026-01-01", "2026-01-01", "2025-01-01", "2025-01-01", "2025-01-01"]
    assert grenzen[3] == f"{int(werte[3][:4]) - 1}-01-01"   # mitten im Jahr wie bis Runde 17d
    assert [export.berliner_tag(w) for w in werte] == ["2027-01-01", "2027-01-01", "2026-12-31", "2026-06-15",
                                                       "2026-06-15", None, None, None, None]
    for zone in ("UTC", "Asia/Tokyo"):
        heute, seite = _node_json(code, zone)
        pipeline = [[(export.berliner_tag(w) or heute)[:4], [publish.has_paper_feed(p, g) for p in vorlagen]]
                    for w, g in zip(werte, grenzen)]
        assert seite == pipeline, zone
        # 31.12. 23:30 UTC: Grenze 01.01.2026 (Vorlage vom 31.12.2025 ohne Feed); eine Stunde früher und mitten im Jahr
        # Grenze 01.01.2025 (beide mit Feed)
        assert seite[0] == ["2027", [False, True]] and seite[2] == seite[3] == ["2026", [True, True]], zone


def test_quellen_im_vorgang_aus_unlesbarem_meta():
    """site/app.js (Vorgangsansicht, Quellenliste): Quellen nur aus einer Liste und ohne leere Einträge (sources
    „kaputt“ oder [null] brachten bis Runde 17d die Vorgangsansicht zum Absturz); das Abrufdatum folgt der Regel des
    Datenstands (zeitDatum, Berliner Kalendertag, unlesbar „unbekannt“), nicht mehr den ersten zehn Zeichen. Seit
    Runde 19b ohne internen Verweis auf CLAUDE.md im Lizenztext (lizenzOeffentlich)."""
    js, teil = _app_js_teil([r"^  const esc = .*?;\n", r"^  const heute = .*?\n  const standTag = .*?\n  };\n",
                             r"^  const lizenzOeffentlich = .*?;\n",
                             r"^    // Quellen nur aus einer Liste.*?\n    const sources = .*?\.join\(\"\"\);\n"])
    assert "String(s.retrieved_at).slice(0, 10)" not in js
    faelle = [{"sources": "kaputt"}, {"sources": [None]}, None, {},
              {"sources": [None, {"name": "oparl-koeln", "license": "CC BY 3.0 DE", "retrieved_at": "kaputt"}]},
              {"sources": [{"name": "oparl-koeln", "license": "L", "retrieved_at": "2026-11-09T23:30:00+00:00"},
                           {"name": "osm", "license": "ODbL"}]},
              {"sources": [{"name": "oparl-koeln", "license": config.SOURCES[config.QUELLE_OPARL]["license"]}]}]
    code = (teil.replace("    const sources = ", "    const quellen = (meta) => { const sources = ", 1)
            .rstrip("\n") + " return sources; };\n"
            + f"console.log(JSON.stringify({json.dumps(faelle)}.map(quellen)));")
    for zone in ("UTC", "Asia/Tokyo"):
        assert _node_json(code, zone) == [
            "", "", "", "", "<li>oparl-koeln: CC BY 3.0 DE · Abruf unbekannt</li>",
            "<li>oparl-koeln: L · Abruf 10.11.2026</li><li>osm: ODbL</li>",
            "<li>oparl-koeln: dl-de/zero 2.0 laut Katalog „OParl API Koeln“ (Klärung offen); " + config.NAMENSNENNUNG
            + "</li>"], zone


def test_datenstand_mit_retrieved_at_als_liste():
    """site/app.js (standText, standTag): retrieved_at als Liste (["2026-11-09"]) ist kein lesbarer Zeitpunkt; der
    Datenstand zeigt „unbekannt“ (nicht das Datum aus String(["2026-11-09"])), und dataStand fällt auf generated_at
    zurück."""
    _, teil = _app_js_teil([r"^  const QUELLE_NAME = .*?;\n", r"^  const heute = .*?\n  const standTag = .*?\n  };\n"])
    m = _mit_oparl(["2026-11-09"], "2026-11-07T10:00:00+00:00")
    code = teil + f"const m = {json.dumps(m)};\nconsole.log(JSON.stringify([standText(m, {{}}), standTag(m)]));"
    for zone in ("UTC", "Asia/Tokyo"):
        text, tag = _node_json(code, zone)
        assert text == "Datenstand: Gebiete: 01.11.2026 · Ratsinformationssystem: unbekannt · erzeugt 07.11.2026", zone
        assert tag == "2026-11-07", zone


# --- Runde 18: Fortsetzung nur bei 404/410 veraltet, Steuerzeichen in JSON, Kontakt im User-Agent Pflicht -------------

@pytest.mark.parametrize("code, verworfen", [(401, False), (403, False), (400, False), (404, True), (410, True)])
def test_fortsetzung_nur_bei_404_oder_410_veraltet(oparl, monkeypatch, code, verworfen):
    """Liefert schon die erste Seite einer Fortsetzung HTTP 404 oder 410, ist sie veraltet: verworfen, der nächste Lauf
    beginnt von vorn. 401, 403 und andere Codes behalten Fortsetzung und Teildatei (die nächste Nacht setzt dort fort);
    401 und 403 zählen wie bisher als Nacht mit möglicher Sperre (Generalprobe 09./10.11.2026)."""
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()                                   # Nacht 1: HTTP 404 auf Seite 3, Fortsetzung ab Seite 2
    fort = json.loads(config.ZUSTAND.read_text())["papers_fortsetzung"]
    teil = config.RAW / "papers.teil.jsonl"
    vorher = teil.read_bytes()
    assert fort["seiten"] == 2 and "page=2" in fort["naechste"] and len(_jsonl(teil)) == 4
    monkeypatch.setattr(oparl, "stoerung",
                        lambda pfad, q: code if pfad == "/papers" and q.get("page") == "2" else False)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                   # Nacht 2: schon die erste Fortsetzungsseite scheitert
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["2"]
    assert f"HTTP {code}" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    zustand = json.loads(config.ZUSTAND.read_text())
    if verworfen:
        assert "papers_fortsetzung" not in zustand and not teil.exists()
    else:
        assert {k: zustand["papers_fortsetzung"][k] for k in ("naechste", "seiten", "start")} == {
            k: fort[k] for k in ("naechste", "seiten", "start")}
        assert teil.read_bytes() == vorher
    assert (zustand.get("sperre_verdacht") or {}).get("naechte") == (1 if code in (401, 403) else None)
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    oparl.anfragen.clear()
    sessionnet.fetch_all()                                   # Nacht 3: von vorn bzw. an der gespeicherten Stelle
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == (
        [None, "2", "3"] if verworfen else ["2", "3"])
    assert len(_jsonl(config.PAPERS)) == 5 and not teil.exists()
    assert "sperre_verdacht" not in json.loads(config.ZUSTAND.read_text())


def _antwort_200(inhalt):
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(inhalt)).encode()
            + b"\r\n\r\n" + inhalt)


def test_steuerzeichen_in_zeichenketten_sind_lesbar(oparl, monkeypatch, roher_server):
    """Rohe Steuerzeichen in JSON-Zeichenketten (etwa \\x0b in einem Titel) machen eine Seite nicht unlesbar: eine
    Anfrage, keine Wiederholung, Titel unverändert. Ungültiges UTF-8 und kein JSON bleiben unlesbar (Wiederholungen,
    dann „aufgegeben“)."""
    monkeypatch.setattr(abruf, "_OEFFNER", OHNE_PROXY)
    titel = "Sitzbänke\x0bam\tMusterweg\x01\x1f"
    server = roher_server(_antwort_200(('{"id": "x", "name": "' + titel + '"}').encode("utf-8")))   # roh, unmaskiert
    vorher = abruf.statistik()
    assert abruf.get_json(f"{server.url}/papers", pausen=[0, 0])["name"] == titel
    assert server.anfragen == ["GET /papers HTTP/1.1"]
    assert (abruf.statistik()["fehler"] - vorher["fehler"], abruf.statistik()["wiederholungen"]
            - vorher["wiederholungen"]) == (0, 0)
    for kaputt in ('{"name": "Sitzbänke"}'.encode("latin-1"), b"<html>kein JSON</html>",
                   b'{"name": "ohne Ende'):
        server = roher_server(_antwort_200(kaputt))
        with pytest.raises(abruf.Abbruch) as e:
            abruf.get_json(f"{server.url}/papers", pausen=[0, 0])
        assert e.value.art == "aufgegeben" and len(server.anfragen) == 3, kaputt


def test_kontakt_pflicht_vor_anfragen_an_die_stadt(oparl, monkeypatch, capsys):
    """Der User-Agent nennt den Kontakt (CLAUDE.md 5.1): Ohne RATSATLAS_KONTAKT sendet ein Lauf gegen ein nicht lokales
    Ziel keine Anfrage, auch nicht die des Bodys (Einstellungsfehler wie andere: ValueError, abruf_fehler in STAND.json,
    keine Nacht mit möglicher Sperre). Mit Kontakt läuft derselbe Abruf in der nächsten Nacht; ein lokaler Testserver
    braucht keinen Kontakt."""
    _nicht_lokal(monkeypatch)
    monkeypatch.setattr(abruf, "im_zeitfenster", lambda jetzt=None: True)
    monkeypatch.setattr(config, "KONTAKT", "")
    vorher = abruf.statistik()
    with pytest.raises(ValueError, match="RATSATLAS_KONTAKT fehlt"):
        sessionnet.fetch_all()
    assert oparl.anfragen == [] and abruf.statistik()["anfragen"] == vorher["anfragen"]
    assert "keine Anfrage gesendet" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    zustand = json.loads(config.ZUSTAND.read_text())
    assert "sperre_verdacht" not in zustand and zustand["letzter_abbruch"]["art"] == "programmfehler"
    _nacht_spaeter()
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")
    sessionnet.fetch_all()
    assert oparl.anfragen and len(_jsonl(config.PAPERS)) == 5
    assert "abruf_fehler" not in json.loads(config.STAND.read_text())
    # lokaler Testserver: ohne Kontakt erlaubt
    monkeypatch.setattr(abruf, "lokal", lambda url: True)
    monkeypatch.setattr(config, "KONTAKT", "")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert oparl.anfragen and "abruf_fehler" not in json.loads(config.STAND.read_text())
