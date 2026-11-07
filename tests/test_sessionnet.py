"""SessionNet-Adapter gegen den lokalen Testserver: Paginierung, inkrementeller Abruf, abgeleitete Beratungen,
Abrufstatistik, Sperre und Anschluss an build.py (Bonner Datenmodell)."""
import csv
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipeline import abruf, build, config, sessionnet

# Öffner ohne Proxy für Tests gegen lokale Server (unabhängig von den Proxy-Variablen der Umgebung)
OHNE_PROXY = urllib.request.build_opener(abruf._OhneWeiterleitung, urllib.request.ProxyHandler({}))


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


def test_parameter_ohne_url_kodierung(oparl):
    sessionnet.fetch_all()
    oparl.anfragen.clear()
    sessionnet.fetch_all()     # der Testserver antwortet auf %3A/%2B wie SessionNet mit 404
    seit = [q["modified_since"] for p, q, _ in oparl.anfragen if p == "/papers"]
    assert seit and all("+00:00" in s or s.endswith("Z") for s in seit)
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


def test_abgebrochener_vollabruf_wird_fortgesetzt(oparl, monkeypatch):
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    zustand = json.loads(config.ZUSTAND.read_text())
    assert zustand["papers_fortsetzung"]["seiten"] == 2 and "page=3" in zustand["papers_fortsetzung"]["naechste"]
    assert not config.PAPERS.exists() and len(_jsonl(config.RAW / "papers.teil.jsonl")) == 4
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [q.get("page") for p, q, _ in oparl.anfragen if p == "/papers"] == ["3"]   # nur die fehlende Seite
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
    monkeypatch.setattr(abruf, "_OEFFNER", urllib.request.build_opener(abruf._OhneWeiterleitung))
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
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
    monkeypatch.setattr(abruf, "_OEFFNER", urllib.request.build_opener(abruf._OhneWeiterleitung))
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
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
    vorher = abruf.statistik()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json("http://127.0.0.1:9/papers?page=2 x", pausen=[0, 0])
    assert e.value.art == "adresse" and not sessionnet.moegliche_sperre(e.value)
    assert abruf.statistik()["anfragen"] == vorher["anfragen"]


def test_moegliche_sperre():
    def abbruch(art, code=None):
        return abruf.Abbruch("Test", art, code=code)
    for e in (abbruch("sperre"), abbruch("aufgegeben"), abbruch("aufgegeben", 503), abbruch("http", 401),
              abbruch("http", 403), abbruch("http", 429), abbruch("weiterleitung", 301), abbruch("unlesbar")):
        assert sessionnet.moegliche_sperre(e), (e.art, e.code)
    for e in (abbruch("http", 404), abbruch("http", 407), abbruch("proxy", 407),
              abbruch("liste"), abbruch("adresse"), abbruch("zeitfenster"), RuntimeError("Beratungen: nur 0")):
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
        monkeypatch.setattr(abruf, "_OEFFNER", urllib.request.build_opener(abruf._OhneWeiterleitung))
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
        monkeypatch.setattr(abruf, "_OEFFNER", urllib.request.build_opener(abruf._OhneWeiterleitung))
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
    """Den letzten Sperrverdacht um `stunden` zurückdatieren (simuliert die nächste Nacht)."""
    z = json.loads(config.ZUSTAND.read_text())
    zuletzt = datetime.fromisoformat(z["sperre_verdacht"]["zuletzt"]) - timedelta(hours=stunden)
    z["sperre_verdacht"]["zuletzt"] = zuletzt.isoformat(timespec="seconds")
    config.ZUSTAND.write_text(json.dumps(z))


def _nicht_lokal(monkeypatch):
    """Lokalen Testserver wie einen Server der Stadt behandeln (Freigabe, Zeitfenster, Mindestabstand 0 für die Tests)."""
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
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


def test_fenster_offen_nach():
    berlin = ZoneInfo("Europe/Berlin")
    assert abruf.fenster_offen_nach(600, datetime(2026, 11, 7, 23, 10, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(3600, datetime(2026, 11, 8, 0, 30, tzinfo=berlin))
    assert not abruf.fenster_offen_nach(60, datetime(2026, 11, 7, 12, 0, tzinfo=berlin))


@pytest.mark.parametrize("inhalt, art", [(b"[]", "aufgegeben"), (b"null", "aufgegeben"), (b'{"a": 1}', "unlesbar")])
def test_unerwartete_antwortform_ohne_traceback(oparl, monkeypatch, inhalt, art):
    server = _lokaler_server(lambda methode, pfad: (200, {"Content-Type": "application/json"}, inhalt))
    try:
        monkeypatch.setattr(config, "ABRUF_PAUSEN", [0])
        monkeypatch.setattr(config, "OPARL_BODY", f"{server.url}/body")
        sessionnet.fetch_all()                                   # kein Traceback
    finally:
        server.shutdown()
        server.server_close()
    assert json.loads(config.ZUSTAND.read_text())["sperre_verdacht"]["art"] == art
    assert "abruf_fehler" in json.loads(config.STAND.read_text())


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
