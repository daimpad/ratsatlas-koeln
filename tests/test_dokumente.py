"""Dokumente (PDF-Köpfe, pipeline/dokumente.py und pipeline/pdfkopf.py; Entscheidung 13.11.2026: gebaut, getestet,
abgeschaltet): Freigabe, Obergrenze je Nacht, Zeitfenster, Abbrüche und Sperrnächte im gemeinsamen Zustand, fremde
Hosts, zu große und unlesbare Dateien, Erkennung des Kopfs an erfundenen Köpfen, Übernahme als Federführung und dass
nichts Abgeleitetes Text enthält. Alle PDF-Dateien entstehen hier mit einem kleinen PDF-Schreiber; alle Inhalte sind
erfunden. Anfragen nur an den lokalen Testserver (conftest.py, `oparl`)."""
import csv
import hashlib
import io
import json
import os
import signal
import sqlite3
import sys
import tempfile
import threading
import time
import types
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import abruf, build, check, config, dokumente, export, pdfkopf, sessionnet

# --- erfundene PDF-Dateien -------------------------------------------------------------------------------------------


def _esc(zeile):
    return zeile.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _pdf(seiten, inhalt=None, fuellen=0):
    """Kleine PDF-Datei (PDF 1.4, Helvetica, WinAnsi): je Seite eine Liste von Zeilen. `inhalt`: eigener Datenstrom der
    ersten Seite (Bytes, samt Wörterbuch-Einträgen wie /Filter); `fuellen`: so viele Byte Kommentar am Ende."""
    objekte = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
               3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"}
    kinder, n = [], 4
    for k, zeilen in enumerate(seiten):
        if k == 0 and inhalt is not None:
            eintraege, strom = inhalt
        else:
            eintraege = b""
            strom = b"BT /F1 11 Tf 14 TL 56 780 Td " + b" ".join(b"(" + _esc(z) + b") Tj T*" for z in zeilen) + b" ET"
        objekte[n] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                      b"/Contents %d 0 R >>" % (n + 1))
        objekte[n + 1] = b"<< /Length %d %s>>\nstream\n" % (len(strom), eintraege) + strom + b"\nendstream"
        kinder.append(n)
        n += 2
    objekte[2] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kinder) + b"] /Count %d >>" % len(kinder)
    aus, lage = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n", {}
    for i in sorted(objekte):
        lage[i] = len(aus)
        aus += b"%d 0 obj\n" % i + objekte[i] + b"\nendobj\n"
    xref, groesse = len(aus), max(objekte) + 1
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % groesse + b"".join(b"%010d 00000 n \n" % lage[i]
                                                                     for i in range(1, groesse))
    aus += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (groesse, xref)
    return aus + (b"%" + b"x" * (fuellen - 2) + b"\n" if fuellen else b"")


def _bombe(mb=60):
    """Datenstrom, der entpackt `mb` MB groß wäre (gepackt rund 60 kB)."""
    z, teile = zlib.compressobj(9), []
    for _ in range(mb):
        teile.append(z.compress(b"0" * 1_000_000))
    teile.append(z.flush())
    return b"/Filter /FlateDecode ", b"".join(teile)


def _verschluesselt(zeilen):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(_pdf([zeilen]))))
    w.encrypt(user_password="geheim", owner_password="besitzer", algorithm="RC4-128")
    aus = io.BytesIO()
    w.write(aus)
    return aus.getvalue()


KOPF = ["Stadt Köln", "Beschlussvorlage", "Dezernat, Dienststelle", "VI/61", "Vorlagen-Nummer 1001/2026"]

# --- Hilfen ------------------------------------------------------------------------------------------------------------


def _datei(oparl, i, inhalt, **felder):
    """Hauptdatei der Vorlage i auf dem Testserver (Host der OParl-API) mit `inhalt` (Bytes oder (Status, Kopf, Bytes))."""
    pfad = f"/files/{i}.pdf"
    oparl.dateien[pfad] = inhalt
    roh = inhalt if isinstance(inhalt, bytes) else inhalt[2]
    return {"id": f"{oparl.b}/files/{i}", "type": "https://schema.oparl.org/1.1/File", "accessUrl": f"{oparl.b}{pfad}",
            "mimeType": "application/pdf", "size": len(roh), "modified": "2026-09-20T10:00:00+02:00", **felder}


def _vorlage(oparl, i):
    """Vorlage i aus dem Testserver (ungerade: Beschlussvorlage NNNN/JJJJ), bei Bedarf angelegt."""
    while len(oparl.papers) < i:
        oparl.papers.append(oparl.paper(len(oparl.papers) + 1))
    return oparl.papers[i - 1]


def _mit_dateien(oparl, inhalte):
    """{i: Inhalt} → Hauptdatei je Verwaltungsvorlage i (ungerade; Inhalt: Zeilen der ersten Seite, Bytes oder Tupel)."""
    for i, inhalt in inhalte.items():
        assert i % 2, "nur ungerade Nummern sind Verwaltungsvorlagen im Testserver"
        if isinstance(inhalt, list):
            inhalt = _pdf([inhalt])
        _vorlage(oparl, i)["mainFile"] = _datei(oparl, i, inhalt)


def _freigabe(monkeypatch, hoechstens=None):
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setenv("RATSATLAS_PDF_FREIGEGEBEN", "ja")
    if hoechstens is not None:
        monkeypatch.setenv("RATSATLAS_PDF_MAX", hoechstens)


def _dateianfragen(oparl):
    return [p for p, _, _ in oparl.anfragen if p.startswith("/files/")]


def _eintraege():
    return [json.loads(z) for z in config.DOKUMENTE.read_text(encoding="utf-8").splitlines()] \
        if config.DOKUMENTE.exists() else []


def _statistik(liste="dokumente"):
    with open(config.ABRUFSTATISTIK, encoding="utf-8") as f:
        return [z for z in csv.DictReader(f, delimiter="\t") if z["liste"] == liste]


def _zustand():
    return json.loads(config.ZUSTAND.read_text())


def _schnappschuss(*ordner):
    return {p: p.read_bytes() for o in ordner for p in sorted(o.rglob("*")) if p.is_file()}


# Nacht im Zeitfenster: 13.11.2026, 23:30 Uhr Ortszeit (22:30 UTC)
NACHT = datetime(2026, 11, 13, 22, 30, tzinfo=timezone.utc)


def _wie_stadt(monkeypatch, start=NACHT):
    """Testserver wie die Stadt behandeln (nicht lokal: Zeitfenster, 12-Stunden-Regel, Kontakt), Scheinuhr; der
    Mindestabstand ist 0, damit die Tests kurz bleiben (eigener Test: test_abstand_gilt_ueber_json_und_dateien)."""
    uhr = types.SimpleNamespace(t=start)
    monkeypatch.setattr(abruf, "lokal", lambda url: False)
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setattr(abruf, "_OEFFNER", abruf.oeffner({}))
    monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")
    sessionnet._stand_setzen(abruf_ok=uhr.t.isoformat(timespec="seconds"))
    return uhr


# --- Erkennung (Orakel: erfundene Köpfe mit erwarteter Trefferart und Kennung) --------------------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("Stadt Köln\nDezernat, Dienststelle\nII/II/2\nBeschlussvorlage", ("kennung", "II/II/2")),
    ("Dezernat, Dienststelle: VI/61", ("kennung", "VI/61")),
    ("Dezernat , Dienststelle  VI / 61 / 2\nVorlagen-Nummer", ("kennung", "VI/61/2")),
    ("Dezernat, Dienststelle VI/61Beschlussvorlage", ("kennung", "VI/61")),        # Zeilen ohne Leerraum aneinander
    ("Dezernat, Dienststelle\nIV/IV/1 und weiter", ("kennung", "IV/IV/1")),
    ("Dezernat VI, 61", ("dezernat_dienststelle", "VI/61")),
    ("Freigabe: Dezernat VI, Dienststelle 61/2", ("dezernat_dienststelle", "VI/61/2")),
    ("Dezernat, Dienststelle\nIntegrationsrat", ("nur_bezeichnung", "")),          # kein „I“ aus einem Wort
    ("Dezernat, Dienststelle VI/61abc", ("nur_bezeichnung", "")),                # keine kürzere Kennung „VI“
    ("Dezernat, Dienststelle OB/01", ("nur_bezeichnung", "")),                   # andere Form: offen bis zum Test
    ("dezernat, dienststelle vi/61", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle\nVorlagen-Nummer\nII/II/2", ("nur_bezeichnung", "")),  # Reihenfolge vertauscht
    ("Das Dezernat VI hat am 12.03. beraten", ("nein", "")),
    ("Dezernat VI, 2025 wurde beschlossen", ("nein", "")),
    ("Mitteilung ohne Kopf", ("nein", "")),
    ("", ("kein_text", "")),
    (" \n\t", ("kein_text", "")),
    # Prüfung dok-f: ohne „/“-Teil nur eine gültige römische Zahl vor Leerraum oder am Ende, nie ein Wortanfang
    ("Dezernat, Dienststelle\nVI\nBeschlussvorlage", ("kennung", "VI")),
    ("Dezernat, Dienststelle IX", ("kennung", "IX")),
    ("Dezernat, Dienststelle II/IIBeschlussvorlage", ("kennung", "II/II")),
    ("DEZERNAT, DIENSTSTELLE VI/61", ("kennung", "VI/61")),                       # Bezeichnung in Großbuchstaben
    ("Dezernat, Dienststelle\nVORLAGE", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle\nVERWALTUNGSVORLAGE", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle\nIII. Quartal", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle\nX-Ring", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle\nIVZ", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle\nVI. Beschluss", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle VIIII/61", ("nur_bezeichnung", "")),                # keine gültige römische Zahl
    ("Dezernat, Dienststelle IVXVIX/61", ("nur_bezeichnung", "")),
    ("Dezernat, Dienststelle VI / 61abc", ("nur_bezeichnung", "")),              # auch mit Leerraum kein „VI“
    ("Dezernat VIIII, 61", ("nein", "")),
])
def test_kopf_erkennen_an_erfundenen_koepfen(text, erwartet):
    assert pdfkopf.kopf_erkennen(text) == erwartet


@pytest.mark.parametrize("kennung, gueltig", [
    ("VI/61", True), ("II/II/2", True), ("IX", True), ("XIV/3", True), ("IV/IV/1/22/3", True),
    ("VIIII/61", False), ("IIII", False), ("IVX/61", False), ("VI/6I", False), ("VI/61/", False), ("V I", False),
    ("", False), ("VI/1234567", False)])
def test_gespeicherte_kennung_nur_in_fester_form(kennung, gueltig):
    """Form einer gespeicherten Kennung (Einträge, Aufbau, check): gültige römische Zahl, dann bis zu vier Teile nach
    „/“ aus Ziffern oder einer gültigen römischen Zahl."""
    assert bool(pdfkopf.KENNUNG_FORM.fullmatch(kennung)) == gueltig


@pytest.mark.parametrize("ausgabe", [
    b'{"status": "ok", "trefferart": "kennung", "kennung": "Musterstr. 12", "fehlerart": ""}',
    b'{"status": "ok", "trefferart": "kennung", "kennung": "VI/61", "fehlerart": "", "text": "Zitat"}',
    b'{"status": "ok", "trefferart": "zitat", "kennung": "", "fehlerart": ""}',
    b'{"status": "ok", "trefferart": "nein", "kennung": "VI/61", "fehlerart": ""}',
    b'{"status": "fehler_pdf", "trefferart": "", "kennung": "", "fehlerart": "Fehler mit Text des Dokuments"}',
    b'{"status": "geheim", "trefferart": "", "kennung": "", "fehlerart": ""}',
    b"kein JSON",
    b"[]",
])
def test_ausgabe_des_pruefprozesses_laesst_keinen_text_durch(ausgabe):
    assert pdfkopf.ergebnis_pruefen(ausgabe) is None


def test_pruefprozess_erkennt_nur_seite_1():
    """Echter Prüfprozess (pypdf in einem eigenen Prozess): Kopf auf Seite 1 erkannt, derselbe Kopf nur auf Seite 2
    nicht (es wird nur Seite 1 gelesen); eine Seite ohne Text ergibt „kein_text“."""
    assert dokumente.pruefen(_pdf([KOPF])) == {"status": "ok", "trefferart": "kennung", "kennung": "VI/61",
                                               "fehlerart": ""}
    assert dokumente.pruefen(_pdf([["Mitteilung"], KOPF]))["trefferart"] == "nein"
    leer = _pdf([[]], inhalt=(b"", b"0 0 m 100 100 l S"))
    assert dokumente.pruefen(leer)["trefferart"] == "kein_text"


@pytest.mark.parametrize("befehl, status", [
    ([sys.executable, "-c", "import time; time.sleep(30)"], "zeitueberschreitung"),
    ([sys.executable, "-c", "import sys; sys.exit(3)"], "fehler_pruefung"),
    ([sys.executable, "-c", 'print(\'{"status": "ok", "trefferart": "kennung", "kennung": "Zitronenfalter", '
                            '"fehlerart": ""}\')'], "fehler_pruefung"),
    ([sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGXCPU)"], "zeitueberschreitung"),
])
def test_pruefprozess_grenzen_und_unerwartete_ausgabe(monkeypatch, befehl, status):
    monkeypatch.setattr(dokumente, "_befehl", lambda: befehl)
    monkeypatch.setattr(dokumente, "PRUEF_FRIST", 1)
    beginn = time.monotonic()
    assert dokumente.pruefen(b"%PDF-1.4\n") == {"status": status, "trefferart": "", "kennung": "", "fehlerart": ""}
    assert time.monotonic() - beginn < 10


@pytest.mark.parametrize("befehl", [
    [sys.executable, "-I", "-c", "import pypdf_gibt_es_nicht"],                  # pypdf fehlt in der Umgebung
    [sys.executable, "-c", "import sys; sys.exit(3)"],
    [sys.executable, "-c", 'print(\'{"status": "ok", "trefferart": "nein", "kennung": "", "fehlerart": ""}\')'],
    [sys.executable, "-c", 'print(\'{"status": "fehler_pdf", "trefferart": "", "kennung": "", '
                           '"fehlerart": "AttributeError"}\')'],                # andere API von pypdf
])
def test_selbsttest_des_pruefprozesses(monkeypatch, befehl):
    """Selbsttest an einer eingebauten Probedatei mit erfundenem Kopf: Der echte Prüfprozess besteht ihn, ein fehlender,
    abstürzender oder anders antwortender nicht."""
    assert dokumente.selbsttest()
    monkeypatch.setattr(dokumente, "_befehl", lambda: befehl)
    assert not dokumente.selbsttest()


# --- Freigabe: ohne sie keine Anfrage und nichts geschrieben --------------------------------------------------------------

@pytest.mark.parametrize("umgebung", [
    {}, {"RATSATLAS_STADT_INFORMIERT": "ja"}, {"RATSATLAS_PDF_FREIGEGEBEN": "ja"},
    {"RATSATLAS_STADT_INFORMIERT": "ja", "RATSATLAS_PDF_FREIGEGEBEN": "Ja"},
    {"RATSATLAS_STADT_INFORMIERT": "ja", "RATSATLAS_PDF_FREIGEGEBEN": "", "RATSATLAS_PDF_MAX": "100"}])
def test_ohne_freigabe_keine_anfrage_und_zustand_unveraendert(oparl, monkeypatch, tmp_path, umgebung):
    """Wie pages.yml in einer Nacht ohne Freigabe: Abruf, dann der Dokumentschritt. Er sendet keine Anfrage und ändert
    keine Datei (Rohdaten, Zustand, STAND.json, Abrufstatistik byte-gleich): Anfragen und Abrufzustand sind dieselben
    wie ohne den Schritt."""
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF})
    sessionnet.fetch_all()
    for k, v in umgebung.items():
        monkeypatch.setenv(k, v)
    vorher, anfragen = _schnappschuss(tmp_path), list(oparl.anfragen)
    dokumente.schritt()
    assert oparl.anfragen == anfragen and _dateianfragen(oparl) == []
    assert _schnappschuss(tmp_path) == vorher and not config.DOKUMENTE.exists()


# --- Lauf mit Freigabe ---------------------------------------------------------------------------------------------------

def test_kennung_wird_federfuehrung_ohne_underdirectionof(oparl, monkeypatch):
    """Ende zu Ende gegen den Testserver: neueste zuerst, nur Abgeleitetes je Datei, Zeile in der Abrufstatistik;
    build übernimmt die Kennung als Federführung (pdf_kopf, Konfidenz nach Trefferart) nur ohne underDirectionOf;
    export zeigt sie mit Kennung, check besteht."""
    oparl.orgs.append({"id": f"{oparl.b}/organizations/amt61", "name": "61 Stadtplanungsamt",
                       "organizationType": "Verwaltungsbereich", "classification": "Stadtplanungsamt"})
    _mit_dateien(oparl, {1: KOPF, 3: ["Dezernat VI, 61/2"], 5: ["Mitteilung ohne Kopf"], 7: KOPF})
    _vorlage(oparl, 7)["underDirectionOf"] = [f"{oparl.b}/organizations/amt61"]
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/7.pdf", "/files/5.pdf", "/files/3.pdf", "/files/1.pdf"]
    e = {x["paper"].rsplit("/", 1)[1]: x for x in _eintraege()}
    assert set(e["1"]) == set(dokumente.FELDER)
    assert (e["1"]["status"], e["1"]["trefferart"], e["1"]["kennung"]) == ("ok", "kennung", "VI/61")
    assert e["1"]["sha256"] == hashlib.sha256(oparl.dateien["/files/1.pdf"]).hexdigest()
    assert e["1"]["groesse"] == len(oparl.dateien["/files/1.pdf"])
    assert (e["3"]["trefferart"], e["3"]["kennung"]) == ("dezernat_dienststelle", "VI/61/2")
    assert (e["5"]["trefferart"], e["5"]["kennung"]) == ("nein", "")
    zeile = _statistik()[-1]
    assert (zeile["anfragen"], zeile["objekte"], zeile["fehler"]) == ("4", "4", "0")
    assert zeile["ergebnis"].startswith("ok; Auswahl 4") and "erkannt 3 (kennung 2, dezernat_dienststelle 1)" in \
        zeile["ergebnis"]
    build.build()
    db = sqlite3.connect(config.DB)
    resp = {pid.rsplit("/", 1)[1]: r for pid, *r in db.execute(
        "SELECT paper_id, organization_id, method, evidence, derived, confidence, kennung FROM paper_responsibility")}
    assert resp["1"] == [None, "pdf_kopf", "Kopf der Vorlage (S. 1): VI/61", 1, "mittel", "VI/61"]
    assert resp["3"] == [None, "pdf_kopf", "Kopf der Vorlage (S. 1): VI/61/2", 1, "niedrig", "VI/61/2"]
    assert resp["7"][:2] == [f"{oparl.b}/organizations/amt61", "underDirectionOf"]   # Kopf nur ohne underDirectionOf
    assert "5" not in resp
    assert check.federfuehrung_kopf(db) == []
    export.export()
    papers = {p["reference"]: p for f in (config.EXPORT / config.STADT).rglob("*.json") if f.name != "index.json"
              for p in (json.loads(f.read_text()).get("papers") or []) if isinstance(p, dict) and "responsibility" in p}
    assert papers["1001/2026"]["responsibility"] == [{
        "kind": "federfuehrend", "method": "pdf_kopf", "evidence": "Kopf der Vorlage (S. 1): VI/61", "derived": 1,
        "confidence": "mittel", "kennung": "VI/61", "label": None, "name": None}]
    # ohne Kopf bleibt die Form wie bisher (ohne confidence und kennung)
    assert set(papers["1007/2026"]["responsibility"][0]) == {"kind", "method", "evidence", "derived", "label", "name"}


def test_check_meldet_federfuehrung_aus_kopf_ohne_erlaubnis(oparl, monkeypatch):
    """Gegenprobe: Eine Zeile pdf_kopf mit Text in der Fundstelle oder bei einer Vorlage ohne Erlaubnis für
    Hauskoordinaten meldet check als Befund."""
    sessionnet.fetch_all()
    build.build()
    db = sqlite3.connect(config.DB)
    pid = f"{oparl.b}/papers/1"
    db.execute("INSERT INTO paper_responsibility VALUES (?, NULL, 'federfuehrend', 'pdf_kopf', ?, 1, 'mittel', 'VI/61')",
               (pid, "Kopf der Vorlage (S. 1): VI/61 – Zitat aus dem Dokument"))
    db.commit()
    assert check.federfuehrung_kopf(db) and "1001/2026" in check.federfuehrung_kopf(db)[0]


def test_obergrenze_je_nacht_und_aenderungen(oparl, monkeypatch):
    """RATSATLAS_PDF_MAX=2: je Nacht höchstens zwei Dateien, neueste zuerst; ein zweiter Lauf derselben Nacht liest
    nichts; unveränderte Dateien werden nicht erneut gelesen, geänderte (modified) schon."""
    _mit_dateien(oparl, {i: KOPF for i in (1, 3, 5, 7, 9)})
    sessionnet.fetch_all()
    _freigabe(monkeypatch, "2")
    uhr = types.SimpleNamespace(t=NACHT)
    monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
    erwartet = [["/files/9.pdf", "/files/7.pdf"], [], ["/files/5.pdf", "/files/3.pdf"], ["/files/1.pdf"], []]
    for nacht, (tag, dateien) in enumerate(zip((0, 0, 1, 2, 3), erwartet)):
        uhr.t = NACHT + timedelta(days=tag, minutes=nacht)
        oparl.anfragen.clear()
        dokumente.schritt()
        assert _dateianfragen(oparl) == dateien, nacht
    assert _statistik()[1]["ergebnis"].startswith("übersprungen: Obergrenze dieser Nacht erreicht (2 von höchstens 2)")
    assert len(_eintraege()) == 5
    # Datei 9 geändert (modified): in der nächsten Nacht erneut gelesen
    geaendert = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    _vorlage(oparl, 9)["mainFile"]["modified"] = _vorlage(oparl, 9)["modified"] = geaendert
    sessionnet.fetch_all()
    uhr.t = NACHT + timedelta(days=4)
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/9.pdf"]
    assert len(_eintraege()) == 5   # je Datei ein Eintrag (zusammengeführt)


@pytest.mark.parametrize("wert, anzahl", [("0", 0), ("-1", 0), ("abc", 0), ("1.5", 0), ("1e3", 0), ("", 3),
                                          (" 2 ", 2)])
def test_obergrenze_unlesbar_oder_null_keine_anfrage(oparl, monkeypatch, wert, anzahl):
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch, wert)
    dokumente.schritt()
    assert len(_dateianfragen(oparl)) == anzahl
    if not anzahl:
        assert _statistik()[-1]["ergebnis"].startswith("übersprungen: RATSATLAS_PDF_MAX=")
        assert "dokumente" not in _zustand()


def test_zeitfenster_endet_waehrend_des_laufs(oparl, monkeypatch):
    """Zeitfenster 23–1 Uhr wird vor jeder Datei geprüft: Endet es nach der ersten Datei, bleibt es bei ihr; das Ende
    des Fensters ist kein Abbruch (kein letzter_abbruch). Vor dem Fenster keine Anfrage."""
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    uhr = _wie_stadt(monkeypatch, datetime(2026, 11, 13, 21, 50, tzinfo=timezone.utc))   # 22:50 Uhr Ortszeit
    dokumente.schritt()
    assert _dateianfragen(oparl) == [] and "außerhalb des Zeitfensters" in _statistik()[-1]["ergebnis"]
    uhr.t = datetime(2026, 11, 13, 23, 59, tzinfo=timezone.utc)                          # 0:59 Uhr Ortszeit
    sessionnet._stand_setzen(abruf_ok=datetime(2026, 11, 13, 22, 20, tzinfo=timezone.utc).isoformat())

    def nach_der_ersten(pfad, q):
        if pfad.startswith("/files/"):
            uhr.t = datetime(2026, 11, 14, 0, 0, 30, tzinfo=timezone.utc)                # 1:00:30 Uhr
        return False
    monkeypatch.setattr(oparl, "stoerung", nach_der_ersten)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/5.pdf"]
    assert _statistik()[-1]["ergebnis"].startswith("unterbrochen: Zeitfenster endete")
    assert "letzter_abbruch" not in _zustand() and len(_eintraege()) == 1


def test_ohne_gremien_oder_beratungen_keine_anfrage(oparl, monkeypatch):
    """Fehlen organizations.json oder beratungen.jsonl, ließen sich Ausschuss- und Öffentlichkeitsregel nicht anwenden:
    keine Anfrage."""
    _mit_dateien(oparl, {1: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    for datei in (config.BERATUNGEN, config.ORGANIZATIONS):
        datei.unlink()
        dokumente.schritt()
        assert _dateianfragen(oparl) == [] and datei.name in _statistik()[-1]["ergebnis"]


def test_vorrang_der_metadaten(oparl, monkeypatch):
    """Ohne vollständigen Abruf der Metadaten in dieser Nacht keine Anfrage; nach einem Abbruch des Abrufs in dieser
    Nacht (12-Stunden-Regel im gemeinsamen Zustand) ebenso."""
    _mit_dateien(oparl, {1: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    _wie_stadt(monkeypatch)
    sessionnet._stand_setzen(abruf_ok=(NACHT - timedelta(days=1)).isoformat())       # vollständig nur in der Vornacht
    dokumente.schritt()
    assert _dateianfragen(oparl) == [] and "Vorrang der Metadaten" in _statistik()[-1]["ergebnis"]
    sessionnet._stand_setzen(abruf_ok=NACHT.isoformat())
    sessionnet._zustand_setzen("letzter_abbruch", {"zuletzt": (NACHT - timedelta(minutes=20)).isoformat(),
                                                   "art": "sperre", "code": None, "meldung": "Abruf"})
    dokumente.schritt()
    assert _dateianfragen(oparl) == [] and "Abbruch (sperre)" in _statistik()[-1]["ergebnis"]


@pytest.mark.parametrize("antwort, art, sperrnacht, status", [
    ((403, {}, b""), "http", True, "abbruch_http_403"),
    ((404, {}, b""), "http", False, "http_404"),
    ((302, {"Location": "http://example.invalid/sperre"}, b""), "weiterleitung", True, "abbruch_weiterleitung"),
    ((200, {"Content-Type": "text/html"}, b"<html>Zugriff verweigert</html>"), "unlesbar", True, "kein_pdf"),
    ((200, {"Content-Length": "100000"}, b"%PDF-1.4\n" + b"x" * 90), "sperre", True, "abbruch_sperre"),
    ((429, {"Retry-After": "999999"}, b""), "aufgegeben", True, "abbruch_aufgegeben"),
])
def test_abbruch_wie_beim_abruf(oparl, monkeypatch, antwort, art, sperrnacht, status):
    """Abbrüche beim Dokumentabruf: sofort, ohne weitere Datei; im gemeinsamen Zustand letzter_abbruch (in derselben
    Nacht weder Dokumente noch Abruf), bei möglicher Sperre sperre_verdacht und die eigene Zählung. Dateibezogene
    Ergebnisse (404, keine PDF-Datei) werden zur Datei endgültig vermerkt, 401/403/429, Weiterleitungen und Abbrüche der
    Verbindung vorläufig (Status abbruch_<Art>, ein Fehlversuch: die Datei kommt später wieder dran, hinter den
    anderen)."""
    _mit_dateien(oparl, {1: KOPF, 3: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    _wie_stadt(monkeypatch)
    oparl.dateien["/files/3.pdf"] = antwort
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/3.pdf"]
    z = _zustand()
    assert z["letzter_abbruch"]["art"] == art and z["letzter_abbruch"]["meldung"].startswith("Dokumente: ")
    assert ("sperre_verdacht" in z) == sperrnacht
    assert (z["dokumente"].get("verdacht", {}).get("naechte") == 1) == sperrnacht
    assert [(x["status"], x["fehlversuche"]) for x in _eintraege()] == [(status, 1 if "abbruch" in status else 0)]
    assert all(dokumente.eintrag_gueltig(x) for x in _eintraege())
    if art == "aufgegeben":
        assert z["nicht_vor"]
    assert _statistik()[-1]["ergebnis"].startswith("abbruch: ")
    # in derselben Nacht kein weiterer Lauf: weder Dokumente noch Abruf
    anfragen = list(oparl.anfragen)
    dokumente.schritt()
    sessionnet.fetch_all()
    assert oparl.anfragen == anfragen
    assert "in derselben Nacht kein weiterer Abruf" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]


def test_drei_naechte_mit_sperrverdacht_sieben_tage_pause(oparl, monkeypatch):
    """Die eigene Zählung der Dokumente: Ein vollständiger Abruf setzt sperre_verdacht jede Nacht zurück; nach drei
    Nächten mit möglicher Sperre beim Dokumentabruf ruhen die Dokumente trotzdem sieben Tage. Wie bei einer echten
    Sperre scheitert jede Nacht die erste Datei (nach einem Fehlversuch steht eine Datei hinten, also jede Nacht eine
    andere); danach werden alle gelesen und die Zählung zurückgesetzt."""
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    uhr = _wie_stadt(monkeypatch)
    for i in (1, 3, 5):
        oparl.dateien[f"/files/{i}.pdf"] = (403, {}, b"")

    def nacht(tag):
        uhr.t = NACHT + timedelta(days=tag)
        sessionnet._zustand_aendern(sperre_verdacht=None, letzter_abbruch=None)      # vollständiger Abruf vorher
        sessionnet._stand_setzen(abruf_ok=uhr.t.isoformat())
        oparl.anfragen.clear()
        dokumente.schritt()
        return _dateianfragen(oparl)
    assert [nacht(t) for t in (0, 1, 2)] == [["/files/5.pdf"], ["/files/3.pdf"], ["/files/1.pdf"]]
    assert _zustand()["dokumente"]["verdacht"]["naechte"] == 3
    assert nacht(3) == [] and "Dokumentabruf pausiert bis 2026-11-22" in _statistik()[-1]["ergebnis"]
    for i in (1, 3, 5):
        oparl.dateien[f"/files/{i}.pdf"] = _pdf([KOPF])
    assert nacht(9) == ["/files/5.pdf", "/files/3.pdf", "/files/1.pdf"]
    assert "verdacht" not in _zustand()["dokumente"]                                  # zurückgesetzt nach einem Lauf
    assert [(x["status"], x["fehlversuche"]) for x in _eintraege()] == [("ok", 0)] * 3


def _tropfen(teil):
    """Antwort, die 6 s lang alle 0,2 s ein Byte schickt (jeder Lesevorgang käme weit vor der Zeitüberschreitung des
    Sockets): `teil` „inhalt“ (Kopf vollständig, der Inhalt tröpfelt) oder „kopf“ (schon der Kopf tröpfelt)."""
    def antwort(h):
        try:
            h.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/pdf\r\nContent-Length: 1000\r\n\r\n%PDF-1.4\n"
                          if teil == "inhalt" else b"HTTP/1.0 200 OK\r\n")
            ende = time.monotonic() + 6
            while time.monotonic() < ende:
                h.wfile.write(b"x" if teil == "inhalt" else b"X")
                time.sleep(0.2)
        except OSError:   # der Abruf hat die Verbindung geschlossen
            pass
    return antwort


@pytest.mark.parametrize("teil", ["inhalt", "kopf"])
def test_lesefrist_gilt_fuer_die_ganze_antwort(oparl, teil):
    """Prüfung dok-f: Eine tröpfelnde Antwort bricht nach der Frist ab (hier 1 s, Art `sperre`), nicht erst, wenn der
    Server schließt (vorher 6 s); auch wenn schon der Kopf tröpfelt (Wächter). Danach ist kein Zeitgeber gesetzt."""
    oparl.dateien["/files/1.pdf"] = _tropfen(teil)
    beginn = time.monotonic()
    with pytest.raises(abruf.Abbruch) as e:
        abruf.get_datei(f"{oparl.b}/files/1.pdf", 25_000_000, 1)
    dauer = time.monotonic() - beginn
    assert e.value.art == "sperre" and "nach 1 s nicht vollständig" in str(e.value)
    assert 0.9 < dauer < 2.5, dauer
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    # eine zügige Antwort danach: kein verspätetes Signal, Datei vollständig
    oparl.dateien["/files/3.pdf"] = _pdf([KOPF])
    assert abruf.get_datei(f"{oparl.b}/files/3.pdf", 25_000_000, 1) == oparl.dateien["/files/3.pdf"]


def test_lesefrist_ohne_waechter_ausserhalb_des_hauptthreads(oparl):
    """Außerhalb des Hauptthreads gibt es keinen Wächter (Signale). Gelesen wird in Blöcken mit höchstens einem
    Lesevorgang (read1) und die Frist nach jedem geprüft: Ein tröpfelnder Inhalt endet so kurz nach der Frist."""
    oparl.dateien["/files/1.pdf"] = _tropfen("inhalt")
    ergebnis = {}

    def lauf():
        beginn = time.monotonic()
        try:
            abruf.get_datei(f"{oparl.b}/files/1.pdf", 25_000_000, 1)
        except abruf.Abbruch as e:
            ergebnis.update(art=e.art, dauer=time.monotonic() - beginn)
    t = threading.Thread(target=lauf)
    t.start()
    t.join(30)
    assert ergebnis["art"] == "sperre" and ergebnis["dauer"] < 2.5, ergebnis


@pytest.mark.parametrize("antwort, status", [
    ((403, {}, b""), "abbruch_http_403"),
    ((401, {}, b""), "abbruch_http_401"),
    ((302, {"Location": "http://example.invalid/anmeldung"}, b""), "abbruch_weiterleitung"),
    ((500, {}, b""), "abbruch_aufgegeben"),
    ("tropfen", "abbruch_sperre"),
])
def test_dauerhafter_fehler_einer_datei_haelt_den_schritt_nicht_auf(oparl, monkeypatch, antwort, status):
    """Prüfung dok-f: Liefert die neueste Datei dauerhaft 401/403, eine Weiterleitung oder 500 oder überschreitet sie die
    Lesefrist, bricht die Nacht wie bisher ab (Sperrlogik unverändert). Die Datei steht aber in der nächsten Nacht hinter
    allen anderen und wird nach zwei Nächten nicht mehr angefragt, bis sich ihre Merkmale ändern: Die älteren Dateien
    werden gelesen, die Stadt sieht die fehlerhafte Datei in zwei Nächten, und es kommt zu keiner Pause von sieben
    Tagen."""
    monkeypatch.setattr(config, "ABRUF_PAUSEN", [0])
    monkeypatch.setattr(dokumente, "LESEFRIST", 1)
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    uhr = _wie_stadt(monkeypatch)
    oparl.dateien["/files/5.pdf"] = _tropfen("inhalt") if antwort == "tropfen" else antwort
    naechte = []
    for tag in range(6):
        uhr.t = NACHT + timedelta(days=tag)
        sessionnet._zustand_aendern(sperre_verdacht=None, letzter_abbruch=None)      # vollständiger Abruf vorher
        sessionnet._stand_setzen(abruf_ok=uhr.t.isoformat())
        oparl.anfragen.clear()
        dokumente.schritt()
        naechte.append(list(dict.fromkeys(_dateianfragen(oparl))))
    assert naechte == [["/files/5.pdf"], ["/files/3.pdf", "/files/1.pdf", "/files/5.pdf"], [], [], [], []]
    e = {x["paper"].rsplit("/", 1)[1]: x for x in _eintraege()}
    assert (e["5"]["status"], e["5"]["fehlversuche"], e["5"]["kennung"]) == (status, 2, "")
    assert (e["1"]["kennung"], e["3"]["kennung"]) == ("VI/61", "VI/61")
    assert all(dokumente.eintrag_gueltig(x) for x in e.values())
    assert _zustand()["dokumente"]["verdacht"]["naechte"] == 2
    ergebnis = _statistik()[-1]["ergebnis"]
    assert ergebnis.startswith("ok; Auswahl 0") and "nach 2 Nächten ohne Ergebnis zurückgestellt 1" in ergebnis


def test_fehler_im_pruefprozess_wird_spaeter_wiederholt(oparl, monkeypatch):
    """Prüfung dok-f: `fehler_pruefung` (der Prüfprozess scheiterte, nicht unbedingt die Datei) ist kein dauerhaftes
    Ergebnis: Die Datei kommt in der nächsten Nacht hinter den anderen wieder dran und wird dann erkannt."""
    _mit_dateien(oparl, {1: KOPF, 3: [*KOPF, "Anlage 1"]})   # verschiedene Bytes
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    uhr = types.SimpleNamespace(t=NACHT)
    monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
    echt, kaputt = dokumente.pruefen, {oparl.dateien["/files/3.pdf"]}
    monkeypatch.setattr(dokumente, "pruefen", lambda daten: {"status": "fehler_pruefung", "trefferart": "",
                                                             "kennung": "", "fehlerart": ""}
                        if daten in kaputt else echt(daten))
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/3.pdf", "/files/1.pdf"]
    assert {x["paper"].rsplit("/", 1)[1]: (x["status"], x["fehlversuche"]) for x in _eintraege()} == {
        "1": ("ok", 0), "3": ("fehler_pruefung", 1)}
    kaputt.clear()
    uhr.t = NACHT + timedelta(days=1)
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/3.pdf"]
    assert {x["paper"].rsplit("/", 1)[1]: (x["kennung"], x["fehlversuche"]) for x in _eintraege()} == {
        "1": ("VI/61", 0), "3": ("VI/61", 0)}


def test_ohne_funktionierenden_pruefprozess_keine_anfrage(oparl, monkeypatch, capsys):
    """Prüfung dok-f: Vor der ersten Anfrage ein Selbsttest des Prüfprozesses. Fehlt pypdf in der isolierten Umgebung
    (oder antwortet der Prüfprozess anders als erwartet), geht keine Anfrage hinaus und nichts wird zur Datei vermerkt;
    mit heilem Prüfprozess werden danach alle Dateien gelesen."""
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    heil = dokumente._befehl
    monkeypatch.setattr(dokumente, "_befehl", lambda: [sys.executable, "-I", "-c", "import pypdf_gibt_es_nicht"])
    dokumente.schritt()
    assert _dateianfragen(oparl) == [] and _eintraege() == []
    assert _statistik()[-1]["ergebnis"].startswith("übersprungen: Prüfprozess")
    assert "Selbsttest" in capsys.readouterr().err
    monkeypatch.setattr(dokumente, "_befehl", heil)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/5.pdf", "/files/3.pdf", "/files/1.pdf"]
    assert [x["kennung"] for x in _eintraege()] == ["VI/61"] * 3


def test_fremde_hosts_und_fehlende_hauptdatei_werden_nicht_gesendet(oparl, monkeypatch, capsys):
    """Nur Adressen auf dem Host der OParl-API (Schema, Host, Port); downloadUrl geht vor. Fehlt mainFile, wird nicht
    unter auxiliaryFile geraten: gezählt und gemeldet."""
    port = oparl.b.rsplit(":", 1)[1]
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF, 7: KOPF, 9: KOPF})
    _vorlage(oparl, 1)["mainFile"]["accessUrl"] = f"http://127.0.0.2:{port}/files/1.pdf"
    _vorlage(oparl, 3)["mainFile"]["accessUrl"] = "http://127.0.0.1:1/files/3.pdf"
    _vorlage(oparl, 5)["mainFile"]["accessUrl"] = f"https://127.0.0.1:{port}/files/5.pdf"
    _vorlage(oparl, 7)["mainFile"]["downloadUrl"] = "http://example.invalid/files/7.pdf"
    hilfs = _vorlage(oparl, 9).pop("mainFile")
    _vorlage(oparl, 9)["auxiliaryFile"] = [hilfs]
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == [] and _statistik()[-1]["anfragen"] == "0"
    ergebnis = _statistik()[-1]["ergebnis"]
    assert "Adresse nicht auf dem Host der OParl-API 4" in ergebnis and "ohne mainFile 1" in ergebnis
    assert "1 Verwaltungsvorlagen ohne mainFile; nicht unter auxiliaryFile geraten" in capsys.readouterr().err


def test_zu_grosse_und_unlesbare_dateien(oparl, monkeypatch):
    """Zu groß laut size: keine Anfrage; laut Content-Length oder beim Lesen: Anfrage, Status zu_gross, weiter mit der
    nächsten Datei. Unlesbare, abgeschnittene, verschlüsselte Dateien und eine Dekompressionsbombe brechen den Lauf
    nicht ab; keine erfundene Kennung."""
    monkeypatch.setattr(dokumente, "MAX_BYTES", 200_000)
    gross = _pdf([KOPF], fuellen=250_000)
    _mit_dateien(oparl, {
        1: KOPF,                                              # gut
        3: _pdf([KOPF])[:300],                                # abgeschnitten (ohne Seite und Verzeichnis)
        5: b"%PDF-1.4\n" + os.urandom(2000),                   # unlesbar
        7: _pdf([KOPF], inhalt=_bombe()),                     # entpackt 60 MB
        9: _verschluesselt(KOPF),                             # Kennwort nötig
        11: (200, {"Content-Length": None}, gross),           # ohne Content-Length, zu groß beim Lesen
        13: gross,                                            # zu groß laut Content-Length
        15: KOPF})
    _vorlage(oparl, 15)["mainFile"]["size"] = 10 ** 9        # zu groß laut size: nicht gesendet
    for i in (11, 13):                                        # ohne size: erst Content-Length bzw. Lesen zeigt es
        del _vorlage(oparl, i)["mainFile"]["size"]
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    beginn = time.monotonic()
    dokumente.schritt()
    assert time.monotonic() - beginn < 120
    assert sorted(_dateianfragen(oparl)) == sorted(f"/files/{i}.pdf" for i in (1, 3, 5, 7, 9, 11, 13))
    e = {x["paper"].rsplit("/", 1)[1]: x for x in _eintraege()}
    assert (e["1"]["status"], e["1"]["kennung"]) == ("ok", "VI/61")
    assert e["11"]["status"] == e["13"]["status"] == "zu_gross"
    assert e["7"]["status"] in ("fehler_pdf", "speicher") and e["9"]["status"] in ("verschluesselt", "fehler_pdf")
    assert e["5"]["kennung"] == "" and e["3"]["kennung"] in ("", "VI/61")
    assert all(dokumente.eintrag_gueltig(x) for x in e.values())
    assert "15" not in e and "MB laut size 1" in _statistik()[-1]["ergebnis"]


def test_nichts_abgeleitetes_enthaelt_text(oparl, monkeypatch, tmp_path, capfd):
    """Erfundener Geheimtext auf Seite 1 und 2: Er steht nach Dokumentschritt, build, export und check in keiner Datei
    (Rohdaten, Zustand, Datenbank, Exporte, Abrufstatistik), in keiner Ausgabe und in keiner neuen Datei im
    Temp-Verzeichnis; keine Datei enthält PDF-Inhalt."""
    geheim = ["Zitronenfalter", "Quittengelee", "Geheimgasse 17"]
    _mit_dateien(oparl, {1: [*KOPF, "Sachverhalt: Zitronenfalter und Quittengelee", "Geheimgasse 17"]})
    _vorlage(oparl, 1)["mainFile"]["fileName"] = "vorlage.pdf"
    oparl.dateien["/files/1.pdf"] = _pdf([[*KOPF, "Sachverhalt: Zitronenfalter und Quittengelee", "Geheimgasse 17"],
                                          ["Zitronenfalter auf Seite 2"]])
    _vorlage(oparl, 1)["mainFile"]["size"] = len(oparl.dateien["/files/1.pdf"])
    sessionnet.fetch_all()
    temp = set(os.listdir(tempfile.gettempdir()))
    _freigabe(monkeypatch)
    dokumente.schritt()
    build.build()
    export.export()
    check.federfuehrung_kopf(sqlite3.connect(config.DB))
    ausgabe = capfd.readouterr()
    assert [x["kennung"] for x in _eintraege()] == ["VI/61"]
    for wort in geheim:
        assert wort not in ausgabe.out and wort not in ausgabe.err
    for pfad, inhalt in _schnappschuss(tmp_path).items():
        assert b"%PDF" not in inhalt, pfad
        for wort in geheim:
            assert wort.encode() not in inhalt and wort.encode("utf-16-le") not in inhalt, (pfad, wort)
    for name in set(os.listdir(tempfile.gettempdir())) - temp:
        pfad = os.path.join(tempfile.gettempdir(), name)
        if os.path.isfile(pfad):
            with open(pfad, "rb") as f:
                inhalt = f.read()
            assert b"%PDF" not in inhalt and not any(w.encode() in inhalt for w in geheim), pfad


def test_abstand_gilt_ueber_json_und_dateien(oparl, monkeypatch):
    """Ein Zählwerk und ein Abstand für JSON und Dateien: Auch die Datei nach einer JSON-Antwort folgt frühestens den
    Mindestabstand später (über die Schritte von pages.yml hinweg zählt er ab dem Start des Prozesses, siehe
    test_sessionnet)."""
    _mit_dateien(oparl, {1: KOPF})
    monkeypatch.setattr(abruf, "lokal", lambda url: False)
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.6)
    monkeypatch.setattr(abruf, "_OEFFNER", abruf.oeffner({}))
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    eingang = []
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: eingang.append(time.monotonic()) and False)
    vorher = abruf.statistik()
    abruf.get_json(config.OPARL_BODY)
    daten = abruf.get_datei(f"{oparl.b}/files/1.pdf", 10_000, 30)
    assert daten == oparl.dateien["/files/1.pdf"] and eingang[1] - eingang[0] >= 0.55
    nachher = abruf.statistik()
    assert nachher["anfragen"] - vorher["anfragen"] == 2 and nachher["bytes"] - vorher["bytes"] > len(daten)


def test_auswahl_regeln_und_reihenfolge():
    """Auswahl ohne Anfrage: nur Hauptdateien von Verwaltungsvorlagen (NNNN/JJJJ, Vorlagenart der Verwaltung), nie
    Eingaben, Vorlagen natürlicher Personen, im Ausschuss für Anregungen und Beschwerden beratene, mit ihnen verbundene
    (auch über relatedPaper), Titel der Maske, nicht öffentlich beratene oder Sammellisten; neueste zuerst, Dateien mit
    einem Fehlversuch dahinter, nach zwei Fehlversuchen nicht mehr (bis zu einer Änderung)."""
    b = "http://127.0.0.1:8"

    def vorlage(i, ref, art="Beschlussvorlage", name=None, datum="2026-10-01", datei=True, **felder):
        p = {"id": f"{b}/papers/{i}", "reference": ref, "paperType": art, "name": name or f"Vorlage {i}",
             "date": datum, "created": f"{datum}T10:00:{i:02d}+02:00", "consultation": [], **felder}
        if datei:
            p["mainFile"] = {"id": f"{b}/files/{i}", "accessUrl": f"{b}/files/{i}.pdf", "mimeType": "application/pdf",
                             "modified": "2026-10-01T10:00:00+02:00", "size": 1000}
        return p
    bab = {"id": f"{b}/organizations/bab", "name": "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden"}
    roh = [
        vorlage(1, "2001/2026"),
        vorlage(2, "2002/2026", datum="2026-10-05"),
        vorlage(3, "AN/0003/2026", art="Antrag nach § 3 der Geschäftsordnung des Rates"),
        vorlage(4, "2004/2026", art="Anregungen und Beschwerden"),
        vorlage(5, "2005/2026", consultation=[{"id": f"{b}/c/5", "organization": [bab["id"]]}]),
        vorlage(6, "2006/2026", relatedPaper=[f"{b}/papers/4"]),
        vorlage(7, "2007/2026", name="Einwohnerversammlung zur Musterstraße 3"),
        vorlage(8, "2008/2026", consultation=[{"id": f"{b}/c/8"}, {"id": f"{b}/c/8b"}]),
        vorlage(9, "2009/2026", name="Punkte der nichtöffentlichen Sitzung"),
        vorlage(10, "2010/2026", datei=False, auxiliaryFile=[{"id": f"{b}/files/10", "accessUrl": f"{b}/f/10.pdf"}]),
        vorlage(11, "2011/2026"),
        vorlage(12, "2012/2026", art="Mitteilung"),
        vorlage(13, "2013/2026", art="Bürgerbrief"),
        vorlage(15, "2015/2026", art="Stellungnahme der Verwaltung", superordinatedPaper=[f"{b}/papers/4"]),
        vorlage(16, "2016/2026", art=["Beschlussvorlage"]),
        vorlage(17, "2017/2026"),
        vorlage(18, "2018/2026", datum="2026-10-03"),
        vorlage(19, "2019/2026"),
        vorlage(20, "2020/2026", consultation=[{"id": f"{b}/c/20"}]),      # public als Text: vorsichtig nicht öffentlich
        vorlage(21, "2021/2026", datum="2026-09-01", consultation=[{"id": f"{b}/c/21"}]),   # ohne TOP: öffentlich
        vorlage(22, "2022/2026", datum="2026-10-09"),     # ein Fehlversuch: hinter allen anderen
        vorlage(23, "2023/2026", datum="2026-10-09"),     # zwei Fehlversuche, unverändert: zurückgestellt
        vorlage(24, "2024/2026", datum="2026-10-07"),     # zwei Fehlversuche, aber geändert: wie neu
        {"id": f"{b}/papers/14", "deleted": True},
    ]
    je = {int(p["id"].rsplit("/", 1)[1]): p for p in roh}
    je[11]["mainFile"]["mimeType"] = "application/msword"
    je[12]["mainFile"] = dict(je[1]["mainFile"])                       # dieselbe Hauptdatei wie Vorlage 1
    je[19]["mainFile"]["size"] = dokumente.MAX_BYTES + 1
    beratungen = [{"uri": f"{b}/c/8", "agendaItem": {"public": True}}, {"uri": f"{b}/c/8b", "agendaItem": {"public": False}},
                  {"uri": f"{b}/c/20", "agendaItem": {"public": "false"}}, {"uri": f"{b}/c/21", "agendaItem": None}]
    # schon verarbeitet: 17 unverändert, 18 mit anderem modified (also geändert)
    eintraege = {f"{b}/files/{i}": {"file": f"{b}/files/{i}",
                                    **{k: je[i]["mainFile"].get(k) for k in dokumente.MERKMALE},
                                    **({"modified": "2026-09-01T00:00:00+02:00"} if i == 18 else {})}
                 for i in (17, 18)}
    for i, n, status in ((22, 1, "abbruch_http_403"), (23, 2, "abbruch_sperre"), (24, 2, "fehler_pruefung")):
        eintraege[f"{b}/files/{i}"] = {"file": f"{b}/files/{i}", "status": status, "fehlversuche": n,
                                       **{k: je[i]["mainFile"].get(k) for k in dokumente.MERKMALE}}
    eintraege[f"{b}/files/24"]["size"] = 999
    from unittest import mock
    with mock.patch.object(config, "OPARL_BODY", f"{b}/body"):
        kandidaten, gruende = dokumente.auswahl(roh, [bab], beratungen, eintraege)
    assert [(k["paper"].rsplit("/", 1)[1], k["_fehlversuche"]) for k in kandidaten] == [
        ("24", 0), ("2", 0), ("18", 0), ("1", 0), ("21", 0), ("22", 1)]
    assert dict(gruende) == {"drucksache": 1, "vorlagenart": 2, "ohne_hauskoordinate": 5, "nicht_oeffentlich": 3,
                             "ohne_hauptdatei": 1, "kein_pdf": 1, "doppelt": 1, "bekannt": 1, "zu_gross": 1,
                             "fehlversuche": 1}


@pytest.fixture
def testdaten(oparl, monkeypatch):
    """300 erfundene Vorlagen (tools/testdaten.py) in den umgelenkten Rohdaten, wie in tests/test_check.py."""
    import importlib.util
    from pathlib import Path
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    spec = importlib.util.spec_from_file_location(
        "testdaten", Path(__file__).resolve().parents[1] / "tools" / "testdaten.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


def test_sperre_der_auswahl_wie_check(testdaten):
    """Orakel aus der Datenbank: Die Vorlagen, die die Auswahl ausschließt (dokumente.gesperrt aus den Rohdaten), sind
    genau die ohne Erlaubnis nach check.erlaubnis (aus der Datenbank nach build) – dieselbe Regel auf zwei Wegen."""
    roh = [json.loads(z) for z in config.PAPERS.read_text(encoding="utf-8").splitlines() if z.strip()]
    papers, ausgelassen, _ = build.einlesen(build._je_kennung_einmal(roh))
    orgs = {o["id"]: o for o in json.loads(config.ORGANIZATIONS.read_text())}
    gesperrt = dokumente.gesperrt(papers, ausgelassen, orgs)
    build.build()
    je_id = check.erlaubnis(sqlite3.connect(config.DB))[0]
    assert {pid for pid, ok in je_id.items() if not ok} == gesperrt & set(je_id)
    assert 0 < len(gesperrt & set(je_id)) < len(je_id)
