"""Gesamtfrist je Antwort beim Abruf der Metadaten (abruf.get_json, abruf.JSON_FRIST; Prüfung dok-f, offener Punkt 8):
gegen den lokalen OParl-Testserver (127.0.0.1) und rohe lokale Server, mit erfundenen Daten.

- Nächte ohne tröpfelnde Antwort senden dieselben Anfragen und hinterlassen byte-gleich denselben Zustand, dieselbe
  STAND.json, dieselben Rohdaten und dieselbe Abrufstatistik wie 55c772e (Prüfsummen mit jenem Stand erzeugt), auch mit
  abgeschnittenen Antworten (Content-Length, chunked an und in einem Abschnitt), einer Antwort ohne Statuszeile und
  HTTP 429 mit Wiederholung. Die Nächte aus tests/test_aussetzen.py (wie 78de995) gelten unverändert.
- Eine tröpfelnde Antwort (Inhalt oder schon der Kopf) endet mit der Frist als mögliche Sperre (Art `sperre`), auch
  außerhalb des Hauptthreads (ohne Wächter: Prüfung nach jedem Block), und im Lauf wie eine Zeitüberschreitung
  (letzter_abbruch, sperre_verdacht, letzter gültiger Stand)."""
import json
import signal
import threading
import time

import pytest

from pipeline import abruf, config, sessionnet
from test_aussetzen import _Naechte  # noqa: E402  (Nächte mit fester Uhr und Prüfsumme je Nacht)


def _roh(antwort):
    """Antwort eines Pfads des Testservers als rohe Bytes (Statuszeile, Kopf, Inhalt), danach schließt er."""
    def schreiben(h):
        h.wfile.write(antwort)
    return schreiben


# Antworten, die mitten im Inhalt oder schon vor der Statuszeile scheitern (http.client.HTTPException)
CL_KURZ = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n"
           b"{\"data\": [")
CHUNKED_GRENZE = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                  b"5\r\n{\"a\":\r\n")
CHUNKED_MITTE = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
                 b"5\r\n{\"a\":\r\n20\r\n12345")


def _fall_abgeschnitten(n, oparl, mp):
    """Abgeschnittene Antworten in Vorlagen, Sitzungen, Gremien und Body (je eine Nacht, dazwischen vollständige
    Nächte): mögliche Sperre wie bisher, gleiche Meldungen (auch die Zahl der gelesenen Bytes)."""
    oparl.papers = [oparl.paper(i) for i in range(1, 8)]
    n.nacht()
    for pfad, antwort in (("/papers", CL_KURZ), ("/meetings", CHUNKED_GRENZE), ("/organizations", CHUNKED_MITTE),
                          ("/body", b"")):
        oparl.dateien[pfad] = _roh(antwort)
        n.nacht()
        del oparl.dateien[pfad]
        n.nacht()


def _fall_koeln_mit_wiederholung(n, oparl, mp):
    """Listen wie Köln (neueste zuerst, limit), HTTP 429 und 503 einmal mit Wiederholung, eine unlesbare Seite (kein
    JSON) mit Wiederholung, eine Seite chunked vollständig."""
    oparl.form, oparl.limit_wirkt = "koeln", True
    mp.setattr(config, "ABRUF_SEITENGROESSE", "3")
    mp.setattr(config, "ABRUF_PAUSEN", [0, 0])
    oparl.papers = [oparl.paper(i) for i in range(1, 9)]
    n.nacht()
    gestoert = []

    def einmal(code, pfad_soll):
        def stoerung(pfad, q):
            if pfad == pfad_soll and not gestoert:
                gestoert.append(pfad)
                return code
            return False
        return stoerung
    for code, pfad in ((429, "/papers"), (503, "/meetings")):
        gestoert.clear()
        mp.setattr(oparl, "stoerung", einmal(code, pfad))
        oparl.papers = oparl.papers + [oparl.paper(len(oparl.papers) + 1, modified="2026-11-14T10:00:00+01:00")]
        n.nacht()
    mp.setattr(oparl, "stoerung", lambda pfad, q: False)
    unlesbar = []

    def kaputt(h):   # erste Antwort kein JSON, danach die richtige Seite
        if not unlesbar:
            unlesbar.append(1)
            h.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{kein json")
            return
        h.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n"
                      + json.dumps(oparl.liste(oparl.orgs, "/organizations", {})).encode())
    oparl.dateien["/organizations"] = kaputt
    n.nacht()
    oparl.dateien["/body"] = lambda h: h.wfile.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        + b"".join(b"%x\r\n%s\r\n" % (len(t), t) for t in (json.dumps(oparl.body()).encode(), b"")))
    n.nacht()


# Prüfsummen je Nacht, erzeugt mit demselben Test gegen den Stand 55c772e (get_json ohne Gesamtfrist)
WIE_55C772E = {
    _fall_abgeschnitten: [
        "f0ca3e6894f3eca3", "756ce75c13a03b63", "5d90ba1d45941031", "582ac205ec63eb10", "5216bc377be1b152",
        "848363039f699c3e", "71a23cd5d7a3302f", "2e8509e04fe9367d", "46adf6ab9308ef3b"
    ],
    _fall_koeln_mit_wiederholung: [
        "964e87adfe601663", "e7e0217ae1f2f467", "d9647a4b71aa9a23", "b7befaf2e46a493d", "17d0ad5c6b919f68"
    ],
}


@pytest.mark.parametrize("fall", list(WIE_55C772E), ids=lambda f: f.__name__.removeprefix("_fall_"))
def test_naechte_ohne_tropfen_wie_55c772e(oparl, monkeypatch, fall):
    """Die Gesamtfrist ändert nichts an Nächten ohne tröpfelnde Antwort: dieselben Anfragen in derselben Reihenfolge,
    byte-gleich derselbe Zustand, dieselbe STAND.json, dieselben Rohdaten und dieselbe Abrufstatistik (ohne Bytes und
    Sekunden) wie 55c772e, auch bei abgeschnittenen Antworten (gleiche Meldung mit der Zahl der gelesenen Bytes) und
    nach Wiederholungen."""
    # Spalte `geaendert`: alter Vergleich wie in test_aussetzen.py::test_naechte_ohne_aussetzen_wie_78de995 (Prüfung stj)
    monkeypatch.setattr(sessionnet, "_ohne_ergaenzung", lambda o: o)
    n = _Naechte(oparl, monkeypatch)
    fall(n, oparl, monkeypatch)
    assert n.summen == WIE_55C772E[fall]


# --- tröpfelnde Antwort der Metadaten ------------------------------------------------------------------------------------

def _tropfen(teil, dauer=6):
    """JSON-Antwort, die `dauer` s lang alle 0,2 s ein Byte schickt (jeder Lesevorgang käme weit vor der
    Zeitüberschreitung des Sockets von 90 s): `teil` „inhalt“ (Kopf vollständig, der Inhalt tröpfelt) oder „kopf“
    (schon der Kopf tröpfelt)."""
    def antwort(h):
        try:
            h.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"data\": ["
                          if teil == "inhalt" else b"HTTP/1.0 200 OK\r\n")
            ende = time.monotonic() + dauer
            while time.monotonic() < ende:
                h.wfile.write(b" " if teil == "inhalt" else b"X")
                time.sleep(0.2)
        except OSError:   # der Abruf hat die Verbindung geschlossen
            pass
    return antwort


def _signal_frei():
    return signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0) and not abruf._frist_aktiv


def test_frist_der_metadaten():
    """120 s: weit über einer normalen Kölner Antwort (eine Seite mit 100 Vorlagen: 5,07 s in Stufe 2) und über der
    Zeitüberschreitung je Lesevorgang (90 s), die bei einem hängenden Server also wie bisher zuerst greift."""
    assert abruf.JSON_FRIST == 120


@pytest.mark.parametrize("teil", ["inhalt", "kopf"])
def test_troepfelnde_antwort_der_metadaten_endet_mit_der_frist(oparl, monkeypatch, teil):
    """Prüfung dok-f, Punkt 8: Eine tröpfelnde Antwort der Metadaten bricht nach der Frist ab (hier 1 s), Art `sperre`
    (mögliche Sperre wie eine Zeitüberschreitung), ohne Wiederholung; vorher hielt sie den Abruf, bis der Server schloss
    (hier 6 s, in Köln beliebig lange). Auch wenn schon der Kopf tröpfelt (Wächter). Danach ist kein Zeitgeber gesetzt,
    und eine zügige Antwort bleibt unberührt."""
    monkeypatch.setattr(abruf, "JSON_FRIST", 1)
    oparl.dateien["/papers"] = _tropfen(teil)
    vorher = abruf.statistik()
    beginn = time.monotonic()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_json(f"{oparl.b}/papers", pausen=[0, 0])
    dauer = time.monotonic() - beginn
    assert e.value.art == "sperre" and sessionnet.moegliche_sperre(e.value)
    assert "Antwort nach 1 s nicht vollständig" in str(e.value) and "mögliche Sperre" in str(e.value)
    assert 0.9 < dauer < 2.5, dauer
    nachher = abruf.statistik()
    assert (nachher["anfragen"] - vorher["anfragen"], nachher["fehler"] - vorher["fehler"],
            nachher["wiederholungen"] - vorher["wiederholungen"]) == (1, 1, 0)
    assert [p for p, _, _ in oparl.anfragen] == ["/papers"]
    assert _signal_frei()
    assert abruf.get_json(config.OPARL_BODY)["name"] == "Testkörperschaft" and _signal_frei()


def test_troepfelnde_metadaten_ohne_waechter_ausserhalb_des_hauptthreads(oparl, monkeypatch):
    """Außerhalb des Hauptthreads gibt es keinen Wächter (Signale): Der Inhalt wird in Blöcken mit höchstens einem
    Lesevorgang gelesen (read1) und die Frist nach jedem geprüft; ein tröpfelnder Inhalt endet so kurz nach der Frist."""
    monkeypatch.setattr(abruf, "JSON_FRIST", 1)
    oparl.dateien["/papers"] = _tropfen("inhalt")
    ergebnis = {}

    def lauf():
        beginn = time.monotonic()
        try:
            abruf.get_json(f"{oparl.b}/papers", pausen=[0, 0])
        except abruf.Abbruch as e:
            ergebnis.update(art=e.art, dauer=time.monotonic() - beginn)
    t = threading.Thread(target=lauf)
    t.start()
    t.join(30)
    assert ergebnis["art"] == "sperre" and ergebnis["dauer"] < 2.5, ergebnis


def test_troepfelnde_metadaten_im_lauf_wie_zeitueberschreitung(oparl, monkeypatch):
    """Im Lauf (sessionnet.fetch_all) wie eine Zeitüberschreitung: Abbruch der Nacht ohne Wiederholung, Nacht mit
    möglicher Sperre, Fehler in STAND.json, letzter gültiger Stand der Sitzungen bleibt; die nächste Nacht ohne
    tröpfelnde Antwort ist vollständig."""
    sessionnet.fetch_all()
    sitzungen = config.MEETINGS.read_bytes()
    monkeypatch.setattr(abruf, "JSON_FRIST", 1)
    oparl.dateien["/meetings"] = _tropfen("inhalt", dauer=4)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert [p for p, _, _ in oparl.anfragen].count("/meetings") == 1          # keine Wiederholung
    z = json.loads(config.ZUSTAND.read_text())
    assert (z["letzter_abbruch"]["art"], z["sperre_verdacht"]["naechte"]) == ("sperre", 1)
    assert "nicht vollständig" in z["letzter_abbruch"]["meldung"]
    assert "mögliche Sperre" in json.loads(config.STAND.read_text())["abruf_fehler"]["meldung"]
    assert config.MEETINGS.read_bytes() == sitzungen
    del oparl.dateien["/meetings"]
    sessionnet.fetch_all()
    stand = json.loads(config.STAND.read_text())
    assert "abruf_fehler" not in stand and stand["abruf_ok"]
