"""SessionNet-Adapter gegen den lokalen Testserver: Paginierung, inkrementeller Abruf, abgeleitete Beratungen,
Abrufstatistik, Sperre und Anschluss an build.py (Bonner Datenmodell)."""
import csv
import json
import sqlite3
from datetime import datetime

import pytest

from pipeline import abruf, build, config, sessionnet


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
    monkeypatch.setattr(abruf.urllib.request, "urlopen", haengt)
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
