"""Zusatzthemen „baustellen“ (WFS „Baustellen Köln“) und „anliegen“ (Open311 „Sag’s uns“): Adapter mit erfundenen Daten
gegen einen lokalen Testserver (Entscheidung 16.11.2026: keine Anfrage an die Stadt). Geprüft werden die Sperren vor
jeder Anfrage (Zusatzthema, eigene Freigabe, Stadt informiert, Zeitfenster, Kontakt, Sperrdatei), die Schemaprüfung
(nichts geschrieben, wenn Felder fehlen), der Datenschutz (keine Beschreibung, Adresse oder Koordinate im Archiv) und
die Zuordnung zu Kölner Stadtteilen. Alle Feld- und Objektnamen hier sind erfunden („t_…“, „test:…“)."""
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipeline import abruf, anliegen, baustellen, config, dienste, kandidaten

JETZT = datetime(2026, 11, 16, 22, 30, tzinfo=timezone.utc)   # 23:30 Uhr in Köln (im Zeitfenster)
ZUORDNUNG_TEST = {"id": "t_id", "bezeichnung": "t_text", "art": "t_art", "strasse": "t_strasse", "von": "t_beginn",
                  "bis": "t_ende"}


@pytest.fixture
def server():
    """Lokaler Testserver: `antwort(pfad, abfrage)` → (Status, Inhalt); `anfragen` hält (Pfad, Abfrage, Kopf)."""
    class Zustand:
        anfragen = []
        antwort = staticmethod(lambda pfad, q: (404, b""))
    s = Zustand()
    s.anfragen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            teile = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(teile.query)
            s.anfragen.append((teile.path, q, dict(self.headers)))
            code, inhalt = s.antwort(teile.path, q)
            self.send_response(code)
            self.send_header("Content-Length", str(len(inhalt)))
            self.end_headers()
            self.wfile.write(inhalt)

        def log_message(self, *_):
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    s.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield s
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def an(monkeypatch):
    """Beide Zusatzthemen eingeschaltet (nur im Test), ohne Abstand für den lokalen Server."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "baustellen", True)
    monkeypatch.setitem(config.ZUSATZTHEMEN, "anliegen", True)
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)


class _KeinNetz:
    """Ersatz für den Öffner: jeder Versuch zu senden ist ein Fehler des Tests."""
    def open(self, *a, **k):
        raise AssertionError("Anfrage wäre gesendet worden")


def _dateien(ordner):
    return sorted(p.relative_to(ordner).as_posix() for p in ordner.rglob("*") if p.is_file()) if ordner.exists() else []


def _alle_texte(ordner):
    return "\n".join(p.read_text(encoding="utf-8") for p in ordner.rglob("*") if p.is_file())


# --- Sperren vor jeder Anfrage ------------------------------------------------------------------------------------------

def test_vorgabe_aus():
    assert config.ZUSATZTHEMEN["baustellen"] is False and config.ZUSATZTHEMEN["anliegen"] is False
    assert baustellen.WFS == "https://geoportal.stadt-koeln.de/wss/service/baustellen_wfs/guest"
    assert anliegen.URL == "https://sags-uns.stadt-koeln.de/georeport/v2/requests.json"
    assert abruf.stadt(baustellen.WFS) and abruf.stadt(anliegen.URL) and abruf.stadt(anliegen.GEOJSON)
    # einzige Stelle der Feldnamen: bis zur Sichtung nicht festgelegt
    assert baustellen.WFS_TYP is None and set(baustellen.ZUORDNUNG.values()) == {None}
    assert anliegen.GRUPPEN == {}


@pytest.mark.parametrize("thema", ["baustellen", "anliegen"])
def test_abgeschaltet_keine_anfrage_auch_nicht_lokal(server, tmp_path, monkeypatch, thema):
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    monkeypatch.setattr(baustellen, "WFS", server.url + "/wfs")
    monkeypatch.setattr(anliegen, "URL", server.url + "/requests.json")
    modul = baustellen if thema == "baustellen" else anliegen
    assert modul.archive(base=tmp_path / "archiv", now=JETZT) is None
    assert server.anfragen == [] and _dateien(tmp_path) == []


def test_schritt_im_aufruf_gesperrt():
    """`python -m pipeline baustellen` und `anliegen` brechen ohne Freigabe in config.ZUSATZTHEMEN vor allem ab."""
    for schritt in ("baustellen", "anliegen", "anliegen-seite", "kandidaten", "baustellen-seite"):
        r = subprocess.run([sys.executable, "-m", "pipeline", schritt], cwd=config.ROOT, capture_output=True, text=True,
                           timeout=120, env={**os.environ, "BAUSTELLEN_ARCHIV": "/nicht/vorhanden"})
        assert r.returncode != 0 and "ist deaktiviert" in r.stderr, (schritt, r.stderr[-300:])


@pytest.mark.parametrize("url", [baustellen.capabilities_url(), anliegen.anfrage_url(datetime(2026, 10, 1).date())])
def test_sperren_fuer_server_der_stadt(an, monkeypatch, url):
    """Reihenfolge der Gründe; gesendet wird nichts (der Öffner würde den Test scheitern lassen)."""
    thema = "baustellen" if "geoportal" in url else "anliegen"
    monkeypatch.setattr(abruf, "_OEFFNER", _KeinNetz())
    monkeypatch.setattr(abruf, "uhr", lambda: JETZT)
    for k in ("BAUSTELLEN_ABRUF", "ANLIEGEN_ABRUF", "RATSATLAS_STADT_INFORMIERT"):
        monkeypatch.delenv(k, raising=False)
    lauf = dienste.Lauf(thema, 5)
    with pytest.raises(dienste.NichtGesendet, match=f"{thema.upper()}_ABRUF=ja fehlt"):
        lauf.holen(url)
    monkeypatch.setenv(f"{thema.upper()}_ABRUF", "ja")
    with pytest.raises(dienste.NichtGesendet, match="RATSATLAS_STADT_INFORMIERT"):
        lauf.holen(url)
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc))
    with pytest.raises(dienste.NichtGesendet, match="Zeitfenster"):
        lauf.holen(url)
    monkeypatch.setattr(abruf, "uhr", lambda: JETZT)
    monkeypatch.setattr(config, "KONTAKT", "")
    with pytest.raises(ValueError, match="RATSATLAS_KONTAKT"):
        lauf.holen(url)
    monkeypatch.setitem(config.ZUSATZTHEMEN, thema, False)   # das Zusatzthema geht allem vor
    with pytest.raises(dienste.NichtGesendet, match="abgeschaltet"):
        lauf.holen(url)
    assert lauf.anfragen == 0 and lauf.protokoll == []


def test_alle_sperren_offen_dann_eine_anfrage_mit_kontakt(an, monkeypatch, tmp_path):
    """Mit allen Freigaben im Zeitfenster geht genau eine Anfrage an den (ersetzten) Öffner, mit Kontakt im User-Agent
    und ohne Wiederholung; ein Fehler beendet den Lauf."""
    gesendet = []

    class Antwort:
        status = 200

        def __init__(self, inhalt):
            self.teile = [inhalt]

        def read(self, n):
            return self.teile.pop(0) if self.teile else b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    class Oeffner:
        def open(self, req, timeout):
            gesendet.append((req.full_url, req.get_header("User-agent"), timeout))
            if len(gesendet) > 1:
                raise ConnectionResetError("erfunden")
            return Antwort(b"[]")
    monkeypatch.setattr(abruf, "_OEFFNER", Oeffner())
    monkeypatch.setattr(abruf, "uhr", lambda: JETZT)
    monkeypatch.setenv("ANLIEGEN_ABRUF", "ja")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")
    monkeypatch.setattr(config, "USER_AGENT", "ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; "
                                              "kontakt@example.invalid)")
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    url = anliegen.anfrage_url(datetime(2026, 10, 1).date())
    with dienste.Lauf("anliegen", 3) as lauf:
        assert lauf.json(url) == []
        with pytest.raises(dienste.Abbruch) as e:
            lauf.json(url)
    assert e.value.art == "verbindung" and lauf.anfragen == 2 and len(gesendet) == 2
    assert gesendet[0][0] == url and "kontakt@example.invalid" in gesendet[0][1] and gesendet[0][2] == dienste.ZEITLIMIT
    assert "start_date=2026-10-01T00%3A00%3A00Z" in url and "end_date=2026-10-31T23%3A59%3A59Z" in url


def test_sperrdatei_haelt_zweiten_lauf_an(server, an, tmp_path, monkeypatch):
    """Hält ein anderer Prozess abruf.lock im Ordner RATSATLAS_SPERRE, geht keine Anfrage hinaus (eine Verbindung)."""
    monkeypatch.setenv("RATSATLAS_SPERRE", str(tmp_path / "sperre"))
    (tmp_path / "sperre").mkdir()
    with open(tmp_path / "sperre" / dienste.SPERRDATEI, "a+") as fremd:
        fcntl.flock(fremd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with dienste.Lauf("anliegen", 3) as lauf, pytest.raises(dienste.Abbruch) as e:
            lauf.holen(server.url + "/x")
    assert e.value.art == "parallel" and server.anfragen == []
    server.antwort = lambda pfad, q: (200, b"[]")
    with dienste.Lauf("anliegen", 3) as lauf:   # nach dem Freigeben wieder möglich
        assert lauf.json(server.url + "/x") == []


def test_abstand_obergrenze_und_keine_weiterleitung(server, an, monkeypatch):
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.3)
    server.antwort = lambda pfad, q: (200, b"[]") if pfad != "/weiter" else (302, b"")
    zeiten = []
    with dienste.Lauf("anliegen", 2) as lauf:
        for _ in range(2):
            lauf.json(server.url + "/x")
            zeiten.append(time.monotonic())
        with pytest.raises(dienste.Abbruch) as e:
            lauf.json(server.url + "/x")
    assert e.value.art == "obergrenze" and len(server.anfragen) == 2 and zeiten[1] - zeiten[0] >= 0.29
    with dienste.Lauf("anliegen", 2) as lauf, pytest.raises(dienste.Abbruch) as e:
        lauf.json(server.url + "/weiter")
    assert e.value.art == "weiterleitung" and len(server.anfragen) == 3
    server.antwort = lambda pfad, q: (200, b"<!DOCTYPE html><html></html>")
    with dienste.Lauf("anliegen", 2) as lauf, pytest.raises(dienste.Abbruch) as e:
        lauf.json(server.url + "/x")
    assert e.value.art == "unlesbar"


# --- Baustellen (WFS) ---------------------------------------------------------------------------------------------------

def _capabilities(*namen):
    typen = "".join(f"<FeatureType><Name>{n}</Name><Title>erfunden</Title></FeatureType>" for n in namen)
    return (f'<?xml version="1.0" encoding="UTF-8"?><WFS_Capabilities xmlns="http://www.opengis.net/wfs" '
            f'version="1.0.0"><FeatureTypeList>{typen}</FeatureTypeList></WFS_Capabilities>').encode()


def _baustelle(i, lon, lat, **anders):
    p = {"t_id": i, "t_text": f"[Testdaten] Maßnahme {i}", "t_art": "Leitungsbau", "t_strasse": "Teststraße 12a",
         "t_beginn": "2026-11-01", "t_ende": "15.12.2026", "t_antragsteller": "Erika Mustermann", "t_telefon": "0221 000"}
    p.update(anders)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": p}


def _wfs(server, feats, typen=("test:erfunden",), extra=None):
    doc = {"type": "FeatureCollection", "features": feats, **(extra or {})}

    def antwort(pfad, q):
        anfrage = q.get("REQUEST", [""])[0]
        if anfrage == "GetCapabilities":
            return 200, _capabilities(*typen)
        if anfrage == "GetFeature":
            return 200, json.dumps(doc).encode()
        return 400, b""
    server.antwort = antwort


@pytest.fixture
def wfs(server, an, monkeypatch):
    monkeypatch.setattr(baustellen, "WFS", server.url + "/wss/service/test_wfs/guest")
    return server


def test_baustellen_lauf_mit_erfundenen_daten(wfs, tmp_path, monkeypatch):
    monkeypatch.setattr(baustellen, "ZUORDNUNG", ZUORDNUNG_TEST)
    feats = [_baustelle(1, 6.958, 50.941), _baustelle(2, 356538.26, 5645249.36, t_strasse="Bundesstraße B 55"),
             _baustelle("3", 7.05, 50.98, t_ende=None)]
    _wfs(wfs, feats, extra={"numberMatched": 3})
    base = tmp_path / "archiv"
    assert baustellen.archive(base=base, now=JETZT) is not None
    pfade = [(p, q.get("REQUEST", [""])[0], q.get("TYPENAME", [""])[0]) for p, q, _ in wfs.anfragen]
    assert [(r, t) for _, r, t in pfade] == [("GetCapabilities", ""), ("GetFeature", "test:erfunden")]
    assert "ratsatlas-koeln" in wfs.anfragen[0][2]["User-Agent"]
    state = json.loads((base / "baustellen.json").read_text(encoding="utf-8"))
    assert list(state) == ["1", "2", "3"]
    a1, a2, a3 = (state[k]["angaben"] for k in ("1", "2", "3"))
    assert set(a1) == set(baustellen.FELDER)
    assert (a1["stadtteil"], a1["stadtbezirk"], a1["strasse"]) == ("Altstadt/Nord", "Innenstadt", "Teststraße")
    assert (a1["von"], a1["bis"]) == ("2026-11-01", "2026-12-15") and a3["bis"] is None
    assert (a2["lon"], a2["lat"], a2["strasse"]) == (6.958, 50.941, "Bundesstraße B 55")   # aus EPSG 25832 erkannt
    assert (a3["stadtteil"], a3["stadtbezirk"]) == ("Höhenhaus", "Mülheim")
    texte = _alle_texte(base)
    assert "Mustermann" not in texte and "0221 000" not in texte and "Teststraße 12a" not in texte
    stand = json.loads((base / "STAND.json").read_text(encoding="utf-8"))
    assert stand["anfragen"] == 2 and stand["objektart"] == "test:erfunden" and stand["anzahl"] == 3
    assert stand["lizenz"] == config.BAUSTELLEN_LICENSE and config.NAMENSNENNUNG in stand["lizenz"]
    assert baustellen.pruefen_archiv(base) == []
    assert len((base / "anfragen.tsv").read_text(encoding="utf-8").splitlines()) == 3
    # zweiter Lauf: 2 entfällt, 1 mit neuem Ende; Objektart eingetragen → keine Anfrage GetCapabilities
    monkeypatch.setattr(baustellen, "WFS_TYP", "test:erfunden")
    _wfs(wfs, [_baustelle(1, 6.958, 50.941, t_ende="2027-01-31"), feats[2]])
    baustellen.archive(base=base, now=JETZT.replace(day=17))
    assert [q.get("REQUEST", [""])[0] for _, q, _ in wfs.anfragen[2:]] == ["GetFeature"]
    log = (base / "protokoll.tsv").read_text(encoding="utf-8")
    assert "2026-11-17\t1\tgeaendert\tbis\t2026-12-15\t2027-01-31" in log and "2026-11-17\t2\tentfallen" in log
    assert len(list((base / "snapshots").rglob("*.json"))) == 2
    # Kandidaten und Seitendatei lesen das Kölner Archiv (ohne eigenen Abruf)
    data = kandidaten.write_site(out=tmp_path / "export", archive=base)
    assert {b["id"]: b["stadtteil"] for b in data["baustellen"]} == {"1": "Altstadt/Nord", "2": "Altstadt/Nord",
                                                                     "3": "Höhenhaus"}
    assert data["meta"]["lizenz"] == config.BAUSTELLEN_LICENSE and "von Hand geprüft" not in json.dumps(data)


@pytest.mark.parametrize("fall, erwartet", [
    ("zuordnung_offen", "nicht festgelegt (ZUORDNUNG, ungeprüft): id, von, bis"),
    ("feld_fehlt", "Eigenschaft 't_beginn' für von fehlt in 1 von 2 Objekten"),
    ("datum", "Datum in 't_ende' (bis) bei 1 Objekten nicht lesbar"),
    ("ausserhalb", "Punkte unlesbar oder außerhalb Kölns"),
    ("doppelt", "Kennung nicht eindeutig"),
    ("linie", "Geometrie LineString, Point statt Point"),
    ("unvollstaendig", "unvollständige Antwort: 5 Objekte laut Quelle, 2 erhalten"),
    ("keine_collection", "keine GeoJSON-FeatureCollection"),
])
def test_baustellen_schemapruefung_schreibt_nichts(wfs, tmp_path, monkeypatch, fall, erwartet):
    if fall != "zuordnung_offen":
        monkeypatch.setattr(baustellen, "ZUORDNUNG", ZUORDNUNG_TEST)
    feats = [_baustelle(1, 6.958, 50.941), _baustelle(2, 6.93, 50.92)]
    extra = None
    if fall == "feld_fehlt":
        del feats[1]["properties"]["t_beginn"]
    elif fall == "datum":
        feats[1]["properties"]["t_ende"] = "Mitte Dezember"
    elif fall == "ausserhalb":
        feats[1]["geometry"]["coordinates"] = [50.92, 6.93]   # Achsen vertauscht
    elif fall == "doppelt":
        feats[1]["properties"]["t_id"] = 1
    elif fall == "linie":
        feats[1]["geometry"] = {"type": "LineString", "coordinates": [[6.93, 50.92], [6.94, 50.93]]}
    elif fall == "unvollstaendig":
        extra = {"numberMatched": 5}
    _wfs(wfs, feats, extra=extra)
    if fall == "keine_collection":
        wfs.antwort = lambda p, q: (200, _capabilities("test:erfunden")) if q.get("REQUEST") == ["GetCapabilities"] \
            else (200, b'{"features": []}')
    with pytest.raises(SystemExit) as e:
        baustellen.archive(base=tmp_path / "archiv", now=JETZT)
    meldung = str(e.value)
    assert erwartet in meldung and meldung.endswith("Nichts geschrieben.")
    if fall == "zuordnung_offen":   # gefundene Eigenschaftsnamen (nie Werte) für die Sichtung
        assert "t_antragsteller, t_art, t_beginn" in meldung and "Mustermann" not in meldung
    assert _dateien(tmp_path) == [] and len(wfs.anfragen) == 2


@pytest.mark.parametrize("typen, erwartet", [
    (("test:a", "test:b"), "WFS_TYP nicht festgelegt und 2 Objektarten angeboten (test:a, test:b)"),
    ((), "WFS_TYP nicht festgelegt und 0 Objektarten angeboten (keine)"),
    (("test:a b",), "Objektart 'test:a b' ist kein gültiger Name"),
])
def test_baustellen_objektart(wfs, tmp_path, monkeypatch, typen, erwartet):
    """Ohne festgelegte Objektart nur GetCapabilities, dann Halt; nichts geschrieben."""
    monkeypatch.setattr(baustellen, "ZUORDNUNG", ZUORDNUNG_TEST)
    _wfs(wfs, [_baustelle(1, 6.958, 50.941)], typen=typen)
    with pytest.raises(SystemExit) as e:
        baustellen.archive(base=tmp_path / "archiv", now=JETZT)
    assert erwartet in str(e.value) and len(wfs.anfragen) == 1 and _dateien(tmp_path) == []


def test_baustellen_festgelegte_objektart():
    assert baustellen.objektart_waehlen(["test:a", "test:b"], "test:b") == "test:b"
    with pytest.raises(dienste.Schemafehler, match="'test:c' \\(WFS_TYP\\) wird nicht angeboten"):
        baustellen.objektart_waehlen(["test:a"], "test:c")


def test_capabilities_ohne_entitaeten():
    boese = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><WFS_Capabilities/>'
    with pytest.raises(dienste.Schemafehler, match="DOCTYPE oder ENTITY"):
        baustellen.objektarten(boese)
    wfs2 = (b'<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"><wfs:FeatureTypeList><wfs:FeatureType>'
            b'<wfs:Name>test:zwei</wfs:Name></wfs:FeatureType></wfs:FeatureTypeList></wfs:WFS_Capabilities>')
    assert baustellen.objektarten(wfs2) == ["test:zwei"]
    with pytest.raises(dienste.Abbruch, match="kein lesbares XML"):
        baustellen.objektarten(b"<nicht")


def test_ohne_hausnummer():
    assert baustellen.ohne_hausnummer("Teststraße 12-14a") == "Teststraße"
    assert baustellen.ohne_hausnummer("Testweg 7/9") == "Testweg"
    assert baustellen.ohne_hausnummer("Bundesstraße B 55") == "Bundesstraße B 55"
    assert baustellen.ohne_hausnummer("") is None


# --- Sag’s uns (Open311 GeoReport v2) -------------------------------------------------------------------------------------

def _meldung(nr, zeit, **anders):
    r = {"service_request_id": nr, "status": "open", "service_code": "t1", "service_name": "[Testdaten] Kategorie",
         "requested_datetime": zeit, "lat": 50.941, "long": 6.958,
         "description": "Erika Mustermann meldet: Auto K-AB 123 vor Teststraße 12", "address": "Teststraße 12",
         "address_id": "t-123", "zipcode": "99999", "media_url": "https://example.invalid/foto.jpg",
         "status_notes": "Rückruf an Herrn Mustermann", "agency_responsible": "Testamt"}
    r.update(anders)
    return r


def _open311(server, je_monat):
    """je_monat: {"2026-10": [Meldungen]}; andere Monate leer."""
    def antwort(pfad, q):
        if pfad != "/georeport/v2/requests.json" or set(q) != {"start_date", "end_date"}:
            return 400, b""
        return 200, json.dumps(je_monat.get(q["start_date"][0][:7], [])).encode()
    server.antwort = antwort


@pytest.fixture
def sags(server, an, monkeypatch):
    monkeypatch.setattr(anliegen, "URL", server.url + "/georeport/v2/requests.json")
    return server


def test_anliegen_lauf_mit_erfundenen_daten(sags, tmp_path, monkeypatch):
    _open311(sags, {"2026-10": [_meldung("101", "2026-10-05T10:00:00+02:00"),
                                _meldung(102, "2026-10-31T23:30:00Z", status="closed", lat="50.92", long="6.93")],
                    "2026-11": [_meldung("103", "2026-11-02T08:00:00+01:00", lat=None, long=None)]})
    base = tmp_path / "archiv"
    anliegen.archive(base=base, now=JETZT)
    monate = [q["start_date"][0][:7] for _, q, _ in sags.anfragen]
    assert monate[0] == "2025-11" and monate[-1] == "2026-11" and len(monate) == 13 <= anliegen.MAX_ANFRAGEN
    ordner = base / "anliegen"
    zeilen = (ordner / "meldungen.tsv").read_text(encoding="utf-8").splitlines()
    assert zeilen[0].split("\t") == anliegen.KOPF and anliegen.pruefen_archiv(base) == []
    meldungen = anliegen.read_state(ordner / "meldungen.tsv")
    assert meldungen["101"]["stadtteil"] == "Altstadt/Nord" and meldungen["101"]["tag"] == "2026-10-05"
    assert meldungen["102"]["tag"] == "2026-11-01"   # 23:30 UTC ist in Köln schon der 1. November
    assert (meldungen["102"]["stadtteil"], meldungen["102"]["stadtbezirk"]) == ("Sülz", "Lindenthal")
    assert meldungen["103"]["stadtteil"] == "" and meldungen["101"]["gruppe"] == anliegen.OHNE_GRUPPE
    texte = _alle_texte(ordner)
    for geheim in ("Mustermann", "K-AB 123", "Teststraße", "99999", "foto.jpg", "t-123", "Testamt", "50.941", "6.958"):
        assert geheim not in texte, geheim
    stand = json.loads((ordner / "STAND.json").read_text(encoding="utf-8"))
    assert stand["anfragen"] == 13 and stand["meldungen"] == 3 and stand["lizenz"] == config.ANLIEGEN_LICENSE
    # Folgelauf: nur die Monate der letzten FENSTER Tage, Status geändert
    _open311(sags, {"2026-10": [_meldung("101", "2026-10-05T10:00:00+02:00", status="closed")]})
    anliegen.archive(base=base, now=JETZT.replace(day=17))
    assert [q["start_date"][0][:7] for _, q, _ in sags.anfragen[13:]] == ["2026-07", "2026-08", "2026-09", "2026-10",
                                                                          "2026-11"]
    assert anliegen.read_state(ordner / "meldungen.tsv")["101"]["status"] == "closed"
    assert "2026-11-17\t2026-10\t1\t0\t1\t" in (ordner / "abrufe.tsv").read_text(encoding="utf-8")
    # Seite: nur Zählungen; „gesamt“ zählt alle Meldungen, solange keine Gruppen festgelegt sind
    doc = anliegen.seite(base=base, out=tmp_path / "export" / "anliegen.json", heute=JETZT.date())
    assert doc["stadt"] == {"gesamt": "unter 3"} and doc["meta"]["gruppen"] == []
    assert doc["meta"]["url"] == anliegen.DATENSATZ and anliegen.pruefen(tmp_path / "export" / "anliegen.json") == []


@pytest.mark.parametrize("antwort, erwartet", [
    ({"requests": []}, "keine Liste von Meldungen"),
    ([{"service_request_id": "1", "status": "in Bearbeitung", "service_code": "t1",
       "requested_datetime": "2026-10-02T10:00:00Z"}], "Status außerhalb der Spezifikation (open, closed): in Bearbeitung"),
    ([{"service_request_id": "1", "status": "open", "service_code": "t1"}], "Feld 'requested_datetime' fehlt in 1 von 1"),
    ([{"service_request_id": "1", "status": "open", "requested_datetime": "2026-10-02T10:00:00Z"}],
     "1 Meldungen ohne service_code und service_name"),
    ([{"service_request_id": "1", "status": "open", "service_code": "t1", "requested_datetime": "2026-08-02T10:00:00Z"}],
     "außerhalb des angefragten Monats (Zeitfilter wirkt nicht)"),
    ([{"service_request_id": "1", "status": "open", "service_code": "t1", "requested_datetime": "gestern"}],
     "requested_datetime bei 1 Meldungen nicht lesbar"),
])
def test_anliegen_schemapruefung_schreibt_nichts(sags, tmp_path, antwort, erwartet):
    def antworten(pfad, q):
        return 200, json.dumps(antwort if q["start_date"][0].startswith("2026-10") else []).encode()
    sags.antwort = antworten
    with pytest.raises(SystemExit) as e:
        anliegen.archive(base=tmp_path / "archiv", now=JETZT)
    assert erwartet in str(e.value) and str(e.value).endswith("Nichts geschrieben.")
    assert _dateien(tmp_path) == []
    assert sags.anfragen[-1][1]["start_date"][0].startswith("2026-10")   # keine Anfrage nach dem Befund


def test_anliegen_abbruch_behaelt_gepruefte_monate(sags, tmp_path):
    def antwort(pfad, q):
        monat = q["start_date"][0][:7]
        if monat == "2026-10":
            return 503, b""
        return 200, json.dumps([_meldung("9", f"{monat}-03T12:00:00Z")] if monat == "2026-09" else []).encode()
    sags.antwort = antwort
    with pytest.raises(SystemExit, match="Abbruch nach 11 Monaten"):
        anliegen.archive(base=tmp_path / "archiv", now=JETZT)
    assert sags.anfragen[-1][1]["start_date"][0].startswith("2026-10")   # keine Wiederholung, kein weiterer Monat
    ordner = tmp_path / "archiv" / "anliegen"
    assert list(anliegen.read_state(ordner / "meldungen.tsv")) == ["9"]
    log = (ordner / "abrufe.tsv").read_text(encoding="utf-8").splitlines()
    assert log[-1].startswith("2026-11-16\t2026-10\t\t\t\tHTTP 503") and len(log) == 13


def test_anliegen_zeitfenster_endet_im_lauf(sags, tmp_path, monkeypatch):
    """Endet die Freigabe während des Laufs (hier: Zeitfenster vor der dritten Anfrage), bleiben die geprüften Monate."""
    echt = dienste.Lauf._warten

    def warten(self, url):
        if self.anfragen == 2:
            raise dienste.NichtGesendet("außerhalb des Zeitfensters 23-1 Uhr (Server der Stadt)")
        return echt(self, url)
    monkeypatch.setattr(dienste.Lauf, "_warten", warten)
    _open311(sags, {"2025-12": [_meldung("8", "2025-12-24T18:00:00Z")]})
    with pytest.raises(SystemExit, match="Abbruch nach 2 Monaten.*Zeitfenster"):
        anliegen.archive(base=tmp_path / "archiv", now=JETZT)
    assert len(sags.anfragen) == 2
    assert list(anliegen.read_state(tmp_path / "archiv" / "anliegen" / "meldungen.tsv")) == ["8"]


def test_baustellen_feature_ohne_form(wfs, tmp_path, monkeypatch):
    monkeypatch.setattr(baustellen, "ZUORDNUNG", ZUORDNUNG_TEST)
    _wfs(wfs, [_baustelle(1, 6.958, 50.941), ["kein", "feature"], {"type": "Feature", "properties": ["x"]}])
    with pytest.raises(SystemExit, match="kein GeoJSON-Feature"):
        baustellen.archive(base=tmp_path / "archiv", now=JETZT)
    assert _dateien(tmp_path) == []


def test_anliegen_gestufte_sichtung(sags, tmp_path, monkeypatch):
    """ANLIEGEN_MAX_ANFRAGEN=1: genau eine Anfrage, der geprüfte Monat wird geschrieben, dann Abbruch (obergrenze)."""
    monkeypatch.setenv("ANLIEGEN_MAX_ANFRAGEN", "1")
    assert anliegen.grenze() == 1
    _open311(sags, {"2025-11": [_meldung("7", "2025-11-20T09:00:00Z")]})
    with pytest.raises(SystemExit, match="Abbruch nach 1 Monaten.*Obergrenze von 1 Anfragen"):
        anliegen.archive(base=tmp_path / "archiv", now=JETZT)
    assert len(sags.anfragen) == 1
    assert list(anliegen.read_state(tmp_path / "archiv" / "anliegen" / "meldungen.tsv")) == ["7"]
    for wert, erwartet in (("99", anliegen.MAX_ANFRAGEN), ("", anliegen.MAX_ANFRAGEN)):   # nur senken
        monkeypatch.setenv("ANLIEGEN_MAX_ANFRAGEN", wert)
        assert anliegen.grenze() == erwartet
    for wert in ("0", "-1", "zwei"):
        monkeypatch.setenv("ANLIEGEN_MAX_ANFRAGEN", wert)
        with pytest.raises(ValueError, match="keine ganze Zahl ab 1"):
            anliegen.grenze()


def test_anliegen_seite_schluessel_stadt(tmp_path):
    """Gesamtwerte unter „stadt“, wie die Seite sie liest (site/app.js); mit erfundenen Gruppen."""
    archiv = tmp_path / "archiv" / "anliegen"
    zeilen = [{"nummer": f"{i}", "tag": "2026-10-01", "gruppe": "Testgruppe", "stadtteil": "Neuehrenfeld",
               "stadtbezirk": "Ehrenfeld"} for i in range(1, 5)]   # erfundene Meldungen
    anliegen.write_state(archiv / "meldungen.tsv", {z["nummer"]: z for z in zeilen})
    (archiv / "STAND.json").write_text(json.dumps({"abruf": "2026-10-02T06:00:00+00:00"}))
    out = tmp_path / "export" / "anliegen.json"
    alt = dict(anliegen.GRUPPEN)
    try:
        anliegen.GRUPPEN.update({"t1": "Testgruppe", "t2": "Andere Gruppe"})
        doc = anliegen.seite(base=tmp_path / "archiv", out=out)
        assert "stadt" in doc and "bonn" not in doc and doc["meta"]["gruppen"] == ["Testgruppe", "Andere Gruppe"]
        assert doc["stadt"] == {"Testgruppe": 4, "Andere Gruppe": "unter 3", "gesamt": 4}
        assert doc["ortsteile"]["Neuehrenfeld"]["gesamt"] == 4
        assert json.loads(out.read_text())["stadt"]["gesamt"] == 4
        assert anliegen.pruefen(out) == []
    finally:
        anliegen.GRUPPEN.clear()
        anliegen.GRUPPEN.update(alt)


def test_keine_bonner_reste_und_lizenzen():
    for modul in ("pipeline/baustellen.py", "pipeline/anliegen.py", "pipeline/dienste.py"):
        text = (config.ROOT / modul).read_text(encoding="utf-8")
        assert "bonn.de" not in text and "Stadt Bonn" not in text, modul
    assert config.BAUSTELLEN_LICENSE.startswith("dl-de/zero 2.0 (Stadt Köln, Baustellen Köln")
    assert config.ANLIEGEN_LICENSE.startswith("dl-de/zero 2.0 (Stadt Köln, Sags uns Anliegenmanagement Köln)")
    assert all(lz.endswith(config.NAMENSNENNUNG) for lz in (config.BAUSTELLEN_LICENSE, config.ANLIEGEN_LICENSE))
    wf = (config.ROOT / ".github" / "workflows-inaktiv" / "baustellen.yml").read_text(encoding="utf-8")
    assert not (config.ROOT / ".github" / "workflows" / "baustellen.yml").exists()
    for teil in ("BAUSTELLEN_ABRUF", "ANLIEGEN_ABRUF", "RATSATLAS_STADT_INFORMIERT", "RATSATLAS_KONTAKT"):
        assert teil in wf, teil
    assert "bonn" not in wf.lower()
