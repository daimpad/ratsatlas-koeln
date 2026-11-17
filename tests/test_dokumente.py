"""Dokumente (PDF-Köpfe, pipeline/dokumente.py und pipeline/pdfkopf.py; Entscheidung 13.11.2026: gebaut, getestet,
abgeschaltet): Freigabe, Obergrenze je Nacht, Zeitfenster, Abbrüche und Sperrnächte im gemeinsamen Zustand, fremde
Hosts, zu große und unlesbare Dateien, Erkennung des Kopfs an erfundenen Köpfen, Übernahme als Federführung und dass
nichts Abgeleitetes Text enthält; nach den Entscheidungen vom 17.11.2026 auch Regel B unter auxiliaryFile, fehlende
Dateien (HTTP 404/410), die erste Nacht mit höchstens 100 Dateien und der Zeitraum ab dem 01.11.2025. Alle
PDF-Dateien entstehen hier mit einem kleinen PDF-Schreiber; alle Inhalte sind erfunden. Anfragen nur an den lokalen
Testserver (conftest.py, `oparl`)."""
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
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import abruf, aemter, build, check, config, dokumente, export, pdfkopf, sessionnet

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
    export zeigt sie mit Kennung und ordnet sie über die Ämtertabelle zu (aemter.zuordnen mit Kennung und Datum der
    Vorlage; eine dreiteilige Kennung nur bis zur Dienststelle), check besteht."""
    oparl.orgs.append({"id": f"{oparl.b}/organizations/amt61", "name": "61 Stadtplanungsamt",
                       "organizationType": "Verwaltungsbereich", "classification": "Stadtplanungsamt"})
    _mit_dateien(oparl, {1: KOPF, 3: ["Dezernat VI, 61/2"], 5: ["Mitteilung ohne Kopf"], 7: KOPF})
    _vorlage(oparl, 7)["underDirectionOf"] = [f"{oparl.b}/organizations/amt61"]
    for i in (1, 3, 5, 7):   # im Zeitraum des Plans (Stand 01.11.2026, geprüft am 13.11.2026); Reihenfolge wie vorher
        _vorlage(oparl, i)["date"] = "2026-11-05"
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
    # Zuordnung über die Kennung (TECHNIK.md, Ämtertabelle „Schnittstelle für den Schritt Dokumente“)
    zuordnung = aemter.fuer_export(aemter.zuordnen(kennung="VI/61", datum="2026-11-05"))
    assert (zuordnung["status"], zuordnung["methode"], zuordnung["kennung"]) == (aemter.EINDEUTIG, "kennung", "VI/61")
    assert papers["1001/2026"]["responsibility"] == [{
        "kind": "federfuehrend", "method": "pdf_kopf", "evidence": "Kopf der Vorlage (S. 1): VI/61", "derived": 1,
        "confidence": "mittel", "kennung": "VI/61", "label": None, "name": None, "aemtertabelle": zuordnung}]
    # dreiteilige Kennung aus der ausgeschriebenen Form: nur bis zur Dienststelle
    dreiteilig = papers["1003/2026"]["responsibility"][0]["aemtertabelle"]
    assert dreiteilig == aemter.fuer_export(aemter.zuordnen(kennung="VI/61/2", datum="2026-11-05"))
    assert (dreiteilig["status"], dreiteilig["kennung"]) == (aemter.NUR_DIENSTSTELLE, "VI/61")
    # ohne Kopf bleibt die Form wie bisher (ohne confidence und kennung), Abgleich über den Namen der Organisation
    assert set(papers["1007/2026"]["responsibility"][0]) == {"kind", "method", "evidence", "derived", "label", "name",
                                                              "aemtertabelle"}
    assert papers["1007/2026"]["responsibility"][0]["aemtertabelle"]["methode"] == "name"
    # Prüfprotokoll: Methode der Federführung, Kennung als Angabe, Ergebnis und Methode des Abgleichs
    audit = {z.split("\t")[0]: z.split("\t") for z in
             (config.EXPORT / "audit_federfuehrung.tsv").read_text(encoding="utf-8").splitlines()[1:]}
    assert audit["1001/2026"][3:7] == ["pdf_kopf", "VI/61", aemter.EINDEUTIG, "kennung"]
    assert audit["1003/2026"][3:7] == ["pdf_kopf", "VI/61/2", aemter.NUR_DIENSTSTELLE, "kennung"]


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
    ((401, {}, b""), "http", True, "abbruch_http_401"),
    ((302, {"Location": "http://example.invalid/sperre"}, b""), "weiterleitung", True, "abbruch_weiterleitung"),
    ((200, {"Content-Type": "text/html"}, b"<html>Zugriff verweigert</html>"), "unlesbar", True, "kein_pdf"),
    ((200, {"Content-Length": "100000"}, b"%PDF-1.4\n" + b"x" * 90), "sperre", True, "abbruch_sperre"),
    ((429, {"Retry-After": "999999"}, b""), "aufgegeben", True, "abbruch_aufgegeben"),
    ((500, {}, b""), "aufgegeben", True, "abbruch_aufgegeben"),
    ((503, {}, b""), "aufgegeben", True, "abbruch_aufgegeben"),
])
def test_abbruch_wie_beim_abruf(oparl, monkeypatch, antwort, art, sperrnacht, status):
    """Abbrüche beim Dokumentabruf: sofort, ohne weitere Datei; im gemeinsamen Zustand letzter_abbruch (in derselben
    Nacht weder Dokumente noch Abruf), bei möglicher Sperre sperre_verdacht und die eigene Zählung. Dateibezogene
    Ergebnisse (keine PDF-Datei) werden zur Datei endgültig vermerkt, 401/403/429/5xx, Weiterleitungen und Abbrüche der
    Verbindung vorläufig (Status abbruch_<Art>, ein Fehlversuch: die Datei kommt später wieder dran, hinter den
    anderen). Seit der Entscheidung vom 17.11.2026 (2) gilt das alles unverändert; nur HTTP 404/410 beendet die Nacht
    erst bei der fünften Antwort (test_fehlende_dateien_*), und keine dieser Antworten zählt dazu."""
    monkeypatch.setattr(config, "ABRUF_PAUSEN", [0])   # 5xx: eine Wiederholung ohne Pause, dann aufgegeben
    _mit_dateien(oparl, {1: KOPF, 3: KOPF})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    _wie_stadt(monkeypatch)
    oparl.dateien["/files/3.pdf"] = antwort
    dokumente.schritt()
    assert list(dict.fromkeys(_dateianfragen(oparl))) == ["/files/3.pdf"]
    z = _zustand()
    assert z["letzter_abbruch"]["art"] == art and z["letzter_abbruch"]["meldung"].startswith("Dokumente: ")
    assert ("sperre_verdacht" in z) == sperrnacht and "fehlende" not in z["dokumente"]
    assert (z["dokumente"].get("verdacht", {}).get("naechte") == 1) == sperrnacht
    assert [(x["status"], x["fehlversuche"]) for x in _eintraege()] == [(status, 1 if "abbruch" in status else 0)]
    assert all(dokumente.eintrag_gueltig(x) for x in _eintraege())
    assert bool(z.get("nicht_vor")) == (antwort[0] == 429)   # nur aus dem Retry-After
    assert _statistik()[-1]["ergebnis"].startswith("abbruch: ")
    # in derselben Nacht kein weiterer Lauf: weder Dokumente noch Abruf
    anfragen = list(oparl.anfragen)
    dokumente.schritt()
    sessionnet.fetch_all()
    assert oparl.anfragen == anfragen
    assert "in derselben Nacht kein weiterer Abruf" in json.loads(config.STAND.read_text())["abruf_uebersprungen"]["grund"]


# --- Fehlende Dateien: HTTP 404 und 410 (Entscheidung des Auftraggebers 17.11.2026 (2)) -----------------------------

def _fehlende(oparl, codes, gute=1):
    """Verwaltungsvorlagen mit Hauptdatei: die neuesten antworten nacheinander mit den HTTP-Codes in `codes`, die `gute`
    ältesten mit einem Kopf. Liefert die Pfade in der Reihenfolge der Auswahl (neueste zuerst)."""
    n = len(codes) + gute
    _mit_dateien(oparl, {2 * i + 1: KOPF for i in range(n)})
    pfade = [f"/files/{2 * i + 1}.pdf" for i in reversed(range(n))]
    for pfad, code in zip(pfade, codes):
        oparl.dateien[pfad] = (code, {}, b"")
    return pfade


@pytest.mark.parametrize("code", [404, 410])
def test_fehlende_dateien_unter_der_grenze_weiter_mit_der_naechsten(oparl, monkeypatch, code):
    """Vier Antworten 404 (bzw. 410) in einer Nacht: jede Datei endgültig vermerkt (http_<Code>, kein Fehlversuch),
    weiter mit der nächsten Datei, kein letzter_abbruch, keine Nacht mit möglicher Sperre; die Zahl steht im Zustand und
    in der Abrufstatistik (nur Zahlen)."""
    pfade = _fehlende(oparl, [code] * 4)
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    _wie_stadt(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade
    z = _zustand()
    assert "letzter_abbruch" not in z and "sperre_verdacht" not in z and "verdacht" not in z["dokumente"]
    assert z["dokumente"]["fehlende"] == 4
    e = {x["file"].rsplit("/", 1)[1]: (x["status"], x["fehlversuche"]) for x in _eintraege()}
    assert e == {"9": (f"http_{code}", 0), "7": (f"http_{code}", 0), "5": (f"http_{code}", 0),
                 "3": (f"http_{code}", 0), "1": ("ok", 0)}
    ergebnis = _statistik()[-1]["ergebnis"]
    assert ergebnis.startswith("ok; ")
    assert "fehlende Dateien (HTTP 404/410): in diesem Lauf 4, in dieser Nacht 4" in ergebnis
    # erneut erst nach einer Änderung: in der nächsten Nacht keine Anfrage
    _wie_stadt(monkeypatch, NACHT + timedelta(days=1))
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == []


@pytest.mark.parametrize("codes", [[404] * 5, [410] * 5, [404, 410, 404, 410, 404]])
def test_fehlende_dateien_die_fuenfte_beendet_die_nacht_wie_bisher(oparl, monkeypatch, capsys, codes):
    """Die fünfte Antwort 404 oder 410 derselben Nacht beendet den Schritt wie vorher eine einzelne: Abbruch der Art
    http mit letzter_abbruch (in derselben Nacht weder Dokumente noch Abruf), keine Nacht mit möglicher Sperre; die
    Warnung nennt den Grund. Die übrigen Dateien bleiben für eine spätere Nacht."""
    pfade = _fehlende(oparl, codes, gute=2)
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    _wie_stadt(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade[:5]
    z = _zustand()
    assert (z["letzter_abbruch"]["art"], z["letzter_abbruch"]["code"]) == ("http", codes[-1])
    assert z["letzter_abbruch"]["meldung"].startswith("Dokumente: 5 Dateien mit HTTP 404 oder 410 in dieser Nacht")
    assert "sperre_verdacht" not in z and "verdacht" not in z["dokumente"] and z["dokumente"]["fehlende"] == 5
    assert sorted(x["status"] for x in _eintraege()) == sorted(f"http_{c}" for c in codes)
    assert _statistik()[-1]["ergebnis"].startswith("abbruch: 5 Dateien mit HTTP 404 oder 410")
    assert "vielleicht hat sich die Form der Adressen geändert" in capsys.readouterr().err
    anfragen = list(oparl.anfragen)
    dokumente.schritt()
    sessionnet.fetch_all()
    assert oparl.anfragen == anfragen


def test_fehlende_dateien_zaehlen_ueber_zwei_laeufe_derselben_nacht(oparl, monkeypatch):
    """Ein zweiter Lauf derselben Nacht (Push, Knopfdruck) zählt die Antworten 404/410 weiter: drei im ersten Lauf
    (RATSATLAS_PDF_MAX=3), die vierte und fünfte im zweiten beenden die Nacht."""
    pfade = _fehlende(oparl, [404] * 5)
    sessionnet.fetch_all()
    _freigabe(monkeypatch, "3")
    _wie_stadt(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade[:3] and _zustand()["dokumente"]["fehlende"] == 3
    assert "letzter_abbruch" not in _zustand()
    monkeypatch.setenv("RATSATLAS_PDF_MAX", "10")
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade[3:5]
    assert _zustand()["dokumente"]["fehlende"] == 5 and _zustand()["letzter_abbruch"]["code"] == 404
    ergebnis = _statistik()[-1]["ergebnis"]
    assert ergebnis.startswith("abbruch: 5 Dateien") and "in diesem Lauf 2, in dieser Nacht 5" in ergebnis


def test_fehlende_dateien_in_einer_neuen_nacht_von_vorn(oparl, monkeypatch):
    """In einer neuen Nacht beginnt die Zählung von vorn: vier Antworten 404 in der ersten Nacht, eine in der zweiten;
    beide Nächte ohne Abbruch."""
    pfade = _fehlende(oparl, [404] * 5, gute=2)
    sessionnet.fetch_all()
    _freigabe(monkeypatch, "4")
    _wie_stadt(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade[:4] and _zustand()["dokumente"]["fehlende"] == 4
    _wie_stadt(monkeypatch, NACHT + timedelta(days=1))
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade[4:]
    z = _zustand()
    assert "letzter_abbruch" not in z and z["dokumente"]["fehlende"] == 1
    assert z["dokumente"]["nacht"] == "2026-11-14" and z["dokumente"]["dateien"] == 3
    assert "in diesem Lauf 1, in dieser Nacht 1" in _statistik()[-1]["ergebnis"]


@pytest.mark.parametrize("wert", ["drei", -1, True, None, 2.5])
def test_fehlende_dateien_unlesbar_wie_vorher(oparl, monkeypatch, wert):
    """Ist die Zahl im Zustand unlesbar, gilt sie in dieser Nacht als erreicht: Die nächste Antwort 404 beendet den
    Schritt wie vor dem 17.11.2026 jede (Warnung, Zustand neu geschrieben)."""
    pfade = _fehlende(oparl, [404])
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    _wie_stadt(monkeypatch)
    sessionnet._zustand_setzen("dokumente", {"nacht": "2026-11-13", "dateien": 0, "fehlende": wert})
    dokumente.schritt()
    assert _dateianfragen(oparl) == pfade[:1] and _zustand()["letzter_abbruch"]["code"] == 404


# --- Erste Nacht mit Dokumenten (Entscheidung des Auftraggebers 17.11.2026 (3)) --------------------------------------

def _eintrag_um(zeit, i=1):
    return {"file": f"F{i}", "paper": f"P{i}", "quelle": "auxiliaryFile", "sha256": "", "groesse": None, "zeit": zeit,
            "kennung": "", "trefferart": "", "status": "http_404", "fehlerart": "", "fehlversuche": 0,
            "modified": None, "size": None, "accessUrl": None, "downloadUrl": None}


@pytest.mark.parametrize("zeiten, pdf_max, erwartet", [
    ([], None, (100, True)),                                                         # keine Datei
    (["2026-11-13T23:10:00+01:00", "2026-11-14T00:50:00+01:00"], None, (100, True)),   # nur aus dieser Nacht
    (["2026-11-13T12:00:00+01:00"], None, (100, True)),                              # Beginn dieser Nacht (12 Uhr)
    (["2026-11-13T11:59:59+01:00", "2026-11-13T23:10:00+01:00"], None, (300, False)),  # auch aus der Nacht davor
    (["2026-11-12T22:10:00+00:00"], "50", (50, False)),
    ([], "50", (50, True)),                                                          # die Variable senkt weiter
    ([], "150", (100, True)),
    (["2026-11-13T23:10:00+01:00"], "300", (100, True)),
])
def test_erste_nacht_hoechstens_100(monkeypatch, zeiten, pdf_max, erwartet):
    """Solange dokumente_koepfe.jsonl keinen Eintrag aus einer früheren Nacht (12 bis 12 Uhr Ortszeit) enthält, gelten
    höchstens 100 Dateien, gleich was RATSATLAS_PDF_MAX sagt (wirksam das Kleinere); danach hoechstens()."""
    if pdf_max is None:
        monkeypatch.delenv("RATSATLAS_PDF_MAX", raising=False)
    else:
        monkeypatch.setenv("RATSATLAS_PDF_MAX", pdf_max)
    eintraege = {f"F{i}": _eintrag_um(z, i) for i, z in enumerate(zeiten)}
    assert all(dokumente.eintrag_gueltig(e) for e in eintraege.values())
    assert dokumente.grenze_der_nacht(eintraege, "2026-11-13") == erwartet
    assert dokumente.ERSTE_NACHT == 100


def test_erste_nacht_auch_ueber_zwei_laeufe(oparl, monkeypatch, capsys):
    """Ende zu Ende (Grenze der ersten Nacht hier 2 statt 100): Der erste Lauf liest 2 Dateien und nennt den Grund im
    Log, ein zweiter Lauf derselben Nacht keine mehr (zusammen höchstens die Grenze); in der nächsten Nacht stammen die
    Einträge aus einer früheren Nacht, es gilt hoechstens()."""
    monkeypatch.setattr(dokumente, "ERSTE_NACHT", 2)
    _mit_dateien(oparl, {i: KOPF for i in (1, 3, 5, 7, 9)})
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    uhr = types.SimpleNamespace(t=NACHT)
    monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/9.pdf", "/files/7.pdf"]
    assert "erste Nacht mit Dokumenten: höchstens 2 Dateien" in capsys.readouterr().out
    assert "in dieser Nacht 2 von höchstens 2, erste Nacht mit Dokumenten" in _statistik()[-1]["ergebnis"]
    uhr.t = NACHT + timedelta(hours=1)
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == []
    assert _statistik()[-1]["ergebnis"].startswith("übersprungen: Obergrenze dieser Nacht erreicht (2 von höchstens 2)")
    assert "erste Nacht mit Dokumenten: höchstens 2 Dateien" in capsys.readouterr().out
    uhr.t = NACHT + timedelta(days=1)
    oparl.anfragen.clear()
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/5.pdf", "/files/3.pdf", "/files/1.pdf"]
    assert "erste Nacht" not in capsys.readouterr().out
    assert "in dieser Nacht 3 von höchstens 300)" in _statistik()[-1]["ergebnis"]


# --- Zeitraum: nur die laufende Wahlperiode (Entscheidung des Auftraggebers 17.11.2026 (4)) --------------------------

@pytest.mark.parametrize("vorlage, tag", [
    ({"date": "2025-11-01"}, "2025-11-01"),
    ({"date": " 2025-10-31 "}, "2025-10-31"),
    ({"date": "2025-11-01T00:30:00+01:00"}, "2025-11-01"),
    ({"date": "2025-10-31T23:30:00+00:00"}, "2025-11-01"),       # mit Zone in Ortszeit Köln: 00:30 Uhr am 1.11.
    ({"date": "2025-11-01T00:30:00+02:00"}, "2025-10-31"),       # 23:30 Uhr am 31.10. Ortszeit
    ({"date": "2025-11-01T08:00:00"}, "2025-11-01"),             # ohne Zone wie geschrieben
    ({"date": None, "created": "2025-11-02T10:00:00+01:00"}, "2025-11-02"),
    ({"created": "2025-10-30T10:00:00+01:00"}, "2025-10-30"),
    ({"date": "31.10.2025", "created": "2025-11-03T09:00:00+01:00"}, "2025-11-03"),   # unlesbar: created
    ({"date": "2025-13-01", "created": "2025-11-04"}, "2025-11-04"),
    ({"date": 20251101, "created": "2025-11-05T09:00:00Z"}, "2025-11-05"),
    ({"date": "", "created": "kaputt"}, None),
    ({}, None),
])
def test_datum_der_vorlage(vorlage, tag):
    """Datum für den Zeitraum der Auswahl: date (ISO-Datum oder Zeitpunkt), fehlt es oder ist es unlesbar created;
    Zeitpunkte mit Zone als Kalendertag in Ortszeit Köln."""
    ergebnis = dokumente.datum_der_vorlage(vorlage)
    assert (ergebnis.isoformat() if ergebnis else None) == tag


def test_auswahl_nur_ab_beginn_der_wahlperiode():
    """Nur Verwaltungsvorlagen mit Datum ab dem 01.11.2025 (Grenze 31.10./01.11., Zeitpunkt mit Zone, ohne date über
    created, ohne beides keine), gezählt als Gründe „vor_wahlperiode“ und „ohne_datum“; neueste zuerst wie bisher.
    Die Datei einer älteren ausgeschlossenen Vorlage bleibt gesperrt."""
    roh = [_vorlage_roh(1, date="2025-10-31", auxiliaryFile=[_datei_roh(10)]),
           _vorlage_roh(2, date="2025-11-01", auxiliaryFile=[_datei_roh(20)]),
           _vorlage_roh(3, date="2025-10-31T23:30:00+00:00", auxiliaryFile=[_datei_roh(30)]),
           _vorlage_roh(4, date="2025-11-01T00:30:00+02:00", auxiliaryFile=[_datei_roh(40)]),
           _vorlage_roh(5, date=None, created="2025-11-20T10:00:00+01:00", auxiliaryFile=[_datei_roh(50)]),
           _vorlage_roh(6, date=None, created=None, auxiliaryFile=[_datei_roh(60)]),
           _vorlage_roh(7, date="kaputt", created="2025-10-01T10:00:00+02:00", auxiliaryFile=[_datei_roh(70)]),
           _vorlage_roh(8, date="2026-10-02", auxiliaryFile=[_datei_roh(80)]),
           # eine ältere Eingabe mit derselben Datei wie eine neue Verwaltungsvorlage: weiter gesperrt
           _vorlage_roh(9, art="Anregungen und Beschwerden", date="2020-01-01", mainFile=_datei_roh(90)),
           _vorlage_roh(11, date="2026-01-15", auxiliaryFile=[_datei_roh(90)])]
    gelesen, gruende = _auswahl(roh)
    assert gelesen == [("80", "8"), ("20", "2"), ("30", "3"), ("50", "5")]
    assert (gruende["vor_wahlperiode"], gruende["ohne_datum"], gruende["datei_gesperrt"]) == (3, 1, 1)


def test_zeitraum_in_log_und_abrufstatistik(oparl, monkeypatch, capsys):
    """Ende zu Ende: Eine Verwaltungsvorlage vom 31.10.2025 wird nicht gelesen, eine vom 01.11.2025 schon; Log und
    Abrufstatistik nennen die Zahlen."""
    _mit_dateien(oparl, {1: KOPF, 3: KOPF})
    _vorlage(oparl, 1)["date"] = "2025-10-31"
    _vorlage(oparl, 3)["date"] = "2025-11-01"
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/3.pdf"]
    ergebnis = _statistik()[-1]["ergebnis"]
    assert "Datum vor dem 01.11.2025 (vor der Wahlperiode) 1" in ergebnis
    assert "ohne lesbares Datum (date, created) 0" in ergebnis
    assert "übergangen mit älterem Datum 1, ohne lesbares Datum 0" in capsys.readouterr().out


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


def test_fremde_hosts_und_vorlagen_ohne_pdf_werden_nicht_gesendet(oparl, monkeypatch, capsys):
    """Nur Adressen auf dem Host der OParl-API (Schema, Host, Port); downloadUrl geht vor, auch bei einer Datei aus
    auxiliaryFile (eine gewählte Anlage auf fremdem Host wird nicht durch eine andere ersetzt: höchstens eine Datei je
    Vorlage). Vorlagen ohne mainFile und ohne PDF-Datei in auxiliaryFile: gezählt und gemeldet."""
    port = oparl.b.rsplit(":", 1)[1]
    _mit_dateien(oparl, {1: KOPF, 3: KOPF, 5: KOPF, 7: KOPF, 9: KOPF, 11: KOPF})
    _vorlage(oparl, 1)["mainFile"]["accessUrl"] = f"http://127.0.0.2:{port}/files/1.pdf"
    _vorlage(oparl, 3)["mainFile"]["accessUrl"] = "http://127.0.0.1:1/files/3.pdf"
    _vorlage(oparl, 5)["mainFile"]["accessUrl"] = f"https://127.0.0.1:{port}/files/5.pdf"
    _vorlage(oparl, 7)["mainFile"]["downloadUrl"] = "http://example.invalid/files/7.pdf"
    anlage = _vorlage(oparl, 9).pop("mainFile")
    anlage["downloadUrl"] = "http://example.invalid/files/9.pdf"
    _vorlage(oparl, 9)["auxiliaryFile"] = [anlage, _datei(oparl, 90, _pdf([KOPF]))]
    tabelle = _vorlage(oparl, 11).pop("mainFile")
    _vorlage(oparl, 11)["auxiliaryFile"] = [dict(tabelle, mimeType="application/vnd.ms-excel")]
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == [] and _statistik()[-1]["anfragen"] == "0"
    ergebnis = _statistik()[-1]["ergebnis"]
    assert "Adresse nicht auf dem Host der OParl-API 5" in ergebnis
    assert "ohne mainFile und ohne PDF-Datei in auxiliaryFile 1" in ergebnis and "Vorlagen ohne PDF-Datei 1" in ergebnis
    assert "1 Verwaltungsvorlagen ohne mainFile und ohne PDF-Datei in auxiliaryFile" in capsys.readouterr().out


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
    """Auswahl ohne Anfrage: nur Dateien von Verwaltungsvorlagen (NNNN/JJJJ, Vorlagenart der Verwaltung; die
    Hauptdatei, ohne sie eine Datei aus auxiliaryFile), nie
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
        # ohne mainFile: die Datei aus auxiliaryFile (PDF nach der Endung, Entscheidung 13.11.2026 (a))
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
    eintraege = {f"{b}/files/{i}": {"file": f"{b}/files/{i}", "quelle": "mainFile",
                                    **{k: je[i]["mainFile"].get(k) for k in dokumente.MERKMALE},
                                    **({"modified": "2026-09-01T00:00:00+02:00"} if i == 18 else {})}
                 for i in (17, 18)}
    for i, n, status in ((22, 1, "abbruch_http_403"), (23, 2, "abbruch_sperre"), (24, 2, "fehler_pruefung")):
        eintraege[f"{b}/files/{i}"] = {"file": f"{b}/files/{i}", "quelle": "mainFile", "status": status,
                                       "fehlversuche": n, **{k: je[i]["mainFile"].get(k) for k in dokumente.MERKMALE}}
    eintraege[f"{b}/files/24"]["size"] = 999
    from unittest import mock
    with mock.patch.object(config, "OPARL_BODY", f"{b}/body"):
        kandidaten, gruende = dokumente.auswahl(roh, [bab], beratungen, eintraege)
    assert [(k["paper"].rsplit("/", 1)[1], k["quelle"], k["_fehlversuche"]) for k in kandidaten] == [
        ("24", "mainFile", 0), ("2", "mainFile", 0), ("18", "mainFile", 0), ("10", "auxiliaryFile", 0),
        ("1", "mainFile", 0), ("21", "mainFile", 0), ("22", "mainFile", 1)]
    assert dict(gruende) == {"drucksache": 1, "vorlagenart": 2, "ohne_hauskoordinate": 5, "nicht_oeffentlich": 3,
                             "kein_pdf": 1, "doppelt": 1, "bekannt": 1, "zu_gross": 1, "fehlversuche": 1}


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


# --- Datei aus auxiliaryFile, wenn mainFile fehlt (Entscheidung des Auftraggebers 13.11.2026 (a)) ---------------------

def _anlage(i, name=None, fileName=None, mime="application/pdf", **felder):
    f = {"id": f"F{i}", "accessUrl": f"http://h.invalid/f/{i}"}
    for k, v in (("name", name), ("fileName", fileName), ("mimeType", mime)):
        if v is not None:
            f[k] = v
    return {**f, **felder}


@pytest.mark.parametrize("aux, erwartet", [
    ([_anlage(1, "Anlage 1 Lageplan"), _anlage(2, "Vorlage"), _anlage(3, "Vorlage 2")], "F2"),   # Wort „Vorlage“
    ([_anlage(1, "Anlage 1"), _anlage(2, "Beschlussvorlage")], "F2"),                            # als Wortteil
    ([_anlage(1, "Anlage 1"), _anlage(2, "VORLAGE")], "F2"),
    ([_anlage(1, "Anlage 1"), _anlage(2, fileName="1234-2026.pdf")], "F2"),                     # Drucksache mit „-“
    ([_anlage(1, "Anlage 1"), _anlage(2, fileName="1234_2026_Text.pdf")], "F2"),                # mit „_“
    ([_anlage(1, "Anlage"), _anlage(2, "Drucksache 1234/2026")], "F2"),                         # mit „/“
    ([_anlage(1, "Anlage"), _anlage(2, "Drucksache 01234/2026")], "F2"),                        # führende Null
    ([_anlage(1, "Anlage"), _anlage(2, "11234/2026"), _anlage(3, "1234/20261")], "F1"),         # andere Zahlen
    ([_anlage(1, "Anlage"), _anlage(2, "1235/2026"), _anlage(3, "1234/2025")], "F1"),
    ([_anlage(1, "Vorlage", mime="application/msword"), _anlage(2, "Anlage")], "F2"),          # nur PDF-Dateien
    ([_anlage(1, "Vorlage", mime=None, fileName="vorlage.docx"), _anlage(2, "Anlage")], "F2"),  # ohne mimeType: .pdf
    ([_anlage(1, "Anlage", mime=None, fileName="anlage.PDF"), _anlage(2, "Vorlage")], "F2"),
    ([_anlage(1, "Anlage", mime=None, fileName="anlage.PDF"), _anlage(2, "Plan")], "F1"),
    ([_anlage(1, "Plan", mime=None, accessUrl="http://h.invalid/f/1.pdf?x=1")], "F1"),
    ([_anlage(1, "Plan", mime=["application/pdf"], fileName="plan.xlsx")], None),             # mimeType in anderer Form
    ([_anlage(1, "Vorlage", deleted=True), _anlage(2, "Anlage")], "F2"),                       # gelöscht
    ([{"accessUrl": "http://h.invalid/f/1.pdf", "name": "Vorlage", "mimeType": "application/pdf"},
      _anlage(2, "Anlage")], "F2"),                                                             # ohne Kennung
    (["http://h.invalid/files/1", _anlage(2, "Anlage")], "F2"),                                 # nur eine Adresse
    ([_anlage(1, "Anlage", mime="Application/PDF; charset=binary")], "F1"),
    ([_anlage(1, "Vorlage", mime="text/html")], None),
    ([], None),
    (None, None),
    (_anlage(1, "Anlage"), "F1"),                                                               # ein Objekt
])
def test_wahl_unter_auxiliaryFile(aux, erwartet):
    """Ohne mainFile höchstens eine Datei aus auxiliaryFile nach Regel B (Entscheidung 17.11.2026 (1)): unter den
    PDF-Dateien (laut mimeType, ohne ihn nur mit der Endung .pdf) in der Reihenfolge der Quelle zuerst die erste, deren
    name oder fileName die eigene Drucksache (1234/2026, 1234-2026, 1234_2026) trägt, sonst die erste mit dem Wort
    „Vorlage“ ohne andere Nummer NNNN/JJJJ, sonst die erste. Orakel: die erwartete Datei je Fall."""
    f, quelle = dokumente.datei_wahl({"id": "P", "reference": "1234/2026", "auxiliaryFile": aux})
    assert (f["id"] if f else None, quelle) == (erwartet, "auxiliaryFile" if erwartet else None)


@pytest.mark.parametrize("namen, erwartet", [
    # die drei Fälle der Prüfung stj nach Regel B (Entscheidung 17.11.2026 (1)), eigene Drucksache 1234/2026
    (["Mitteilung", "Anlage 2 Vorlage 0815/2019 (Ratsbeschluss)"], (0, "erste", {"uebergangen"})),
    (["Anlage 1 zur Vorlage", "1234/2026 Mitteilung"], (1, "drucksache", set())),
    (["Beantwortung", "Anlage Vorlagenbericht"], (1, "vorlage", {"auch_anlage"})),
    (["Vorlage 1234/2026", "Anlage 1"], (0, "drucksache", set())),
    (["Anlage 1", "Beschlussvorlage 1234-2026"], (1, "drucksache", set())),
    (["Anlage 1", "Beschlussvorlage"], (1, "vorlage", set())),
    (["Vorlage Schuljahr 2025/2026", "Plan"], (0, "vorlage", set())),            # Jahresspanne: keine Nummer
    (["Anlage 1", "Vorlage zur Grünanlage"], (1, "vorlage", set())),             # „Grünanlage“: nicht „Anlage“
    (["Plan", "Vorlage AN/1234/2026"], (0, "erste", {"uebergangen"})),           # Antrag mit denselben Ziffern
    (["Vorlage AN/0815/2026", "Beschlussvorlage"], (1, "vorlage", {"uebergangen"})),
    (["Anlage AN_1234_2026", "Plan"], (0, "erste", set())),                      # keine eigene Drucksache
    (["Stellungnahme an/1234/2026", "Plan"], (0, "erste", set())),              # „an/“ klein (Prüfung stk)
    (["Stellungnahme AN 1234/2026", "Beschlussvorlage"], (1, "vorlage", set())),  # „AN “ mit Leerzeichen
    (["Vorlage_AN_1234_2026", "Plan"], (1, "erste", {"uebergangen"})),          # „AN_“ nach „_“
    (["Anlage", "Bebauungsplan 1234/2026"], (1, "drucksache", set())),           # „…plan 1234/2026“: kein „AN“
    (["Plan", "Karte"], (0, "erste", set())),
    # Schritt 3 nur unter den nicht übergangenen PDF-Dateien (Entscheidung 17.11.2026 (6)); bleibt keine, keine Datei
    (["Vorlage 0815/2019", "Anlage 1 Lageplan"], (1, "erste", {"uebergangen"})),
    (["Vorlage 0815/2019"], (None, None, {"uebergangen"})),
    (["Vorlage 0815/2019", "Beschlussvorlage 0816/2019"], (None, None, {"uebergangen"})),
    (["Vorlage 0815/2019", "Vorlage 0816/2019"], (None, None, {"uebergangen"})),
    (["Vorlage 0815/2019", "Stellungnahme 0815/2019"], (1, "erste", {"uebergangen"})),   # ohne „Vorlage“: wählbar
    (["Mitteilung 0815/2019", "Plan"], (0, "erste", set())),                     # wie bisher
    # offen (Entscheidung 17.11.2026 (8)): Monat und Jahr ohne Tag zählen als andere Nummer, allein also keine Datei
    (["Beschlussvorlage Stand 11/2025"], (None, None, {"uebergangen"})),
])
def test_zweig_der_wahl_unter_auxiliaryFile(namen, erwartet):
    """Regel B (Entscheidung 17.11.2026 (1)): eigene Drucksache in irgendeiner PDF-Datei vor dem Wort „Vorlage“; eine
    Datei mit „Vorlage“ und einer anderen Nummer NNNN/JJJJ (auch AN/…, keine Jahresspanne) wird übergangen; sonst die
    erste PDF-Datei, die nicht übergangen wurde, auch mit anderer Nummer, wenn das Wort „Vorlage“ fehlt (17.11.2026
    (6)); bleibt keine, keine Datei (mit dem Hinweis „uebergangen“). Zweig und Hinweise nur zum Zählen; die Wahl selbst
    ist datei_wahl."""
    p = {"reference": "1234/2026", "auxiliaryFile": [_anlage(i, n) for i, n in enumerate(namen)]}
    f, quelle, zweig, hinweise = dokumente.wahl_mit_zweig(p)
    assert (f, quelle) == dokumente.datei_wahl(p)
    datei = None if erwartet[0] is None else f"F{erwartet[0]}"
    assert (f["id"] if f else None, zweig, set(hinweise)) == (datei, erwartet[1], erwartet[2])
    assert quelle == ("auxiliaryFile" if datei else None)
    assert set(hinweise) <= set(dokumente.HINWEISE) and (zweig in dokumente.ZWEIGE or not datei and zweig is None)
    assert dokumente.wahl_mit_zweig({"reference": "1/2026", "mainFile": _anlage(9)})[2:] == ("mainFile", frozenset())
    assert dokumente.wahl_mit_zweig({"reference": "1/2026"}) == (None, None, None, frozenset())


@pytest.mark.parametrize("name, eigen, fremd", [
    ("1234/2026", True, False), ("Drucksache 01234_2026", True, False), ("1234-2026.pdf", True, False),
    ("AN/1234/2026", False, True), ("AN-1234-2026", False, True), ("AN_1234_2026", False, True),
    ("11234/2026", False, False), ("1234/20261", False, False),                   # fünfstellig: keine Nummer
    # „AN“ in beliebiger Schreibung, mit Leerzeichen, nach „_“, aber nicht am Ende eines Wortes (Prüfung stk)
    ("Stellungnahme an/1234/2026", False, True), ("Stellungnahme AN 1234/2026", False, True),
    ("Stellungnahme An /1234/2026", False, True), ("Antrag_an-1234-2026.pdf", False, True),
    ("Bebauungsplan 1234/2026", True, False), ("Plan_1234_2026", True, False)])
def test_eigene_drucksache_nicht_in_einer_an_nummer(name, eigen, fremd):
    """Die eigene Drucksache im Namen (_drucksache_muster, _traegt_drucksache), aber nicht als Teil der Drucksache eines
    Antrags oder einer Anfrage (AN/NNNN/JJJJ), die _fremde_nummer als andere Nummer zählt."""
    assert dokumente._traegt_drucksache(dokumente._drucksache_muster("1234/2026"), [name]) == eigen
    assert dokumente._fremde_nummer([name], "1234/2026") == fremd


@pytest.mark.parametrize("reference, namen, erwartet", [
    # Monat und Jahr eines Datums TT-MM-JJJJ sind keine Nummer NNNN/JJJJ (Prüfung stk)
    ("1234/2026", [_anlage(0, "Plan"), _anlage(1, "Beschlussvorlage", fileName="Vorlage_17-11-2026.pdf")],
     (1, "vorlage", set())),
    ("1234/2026", [_anlage(0, "Plan"), _anlage(1, "Vorlage vom 3_11_2026")], (1, "vorlage", set())),
    ("1234/2026", [_anlage(0, "Plan"), _anlage(1, "Vorlage 17/11/2026")], (1, "vorlage", set())),
    ("0011/2026", [_anlage(0, "Anlage vom 17-11-2026"), _anlage(1, "Beschlussvorlage")], (1, "vorlage", set())),
    ("0011/2026", [_anlage(0, "Anlage"), _anlage(1, "Mitteilung 0011/2026")], (1, "drucksache", set())),
    ("0011/2026", [_anlage(0, "Anlage"), _anlage(1, "Mitteilung 11/2026")], (1, "drucksache", set())),
    # eine vierstellige Nummer nach einem Tag bleibt eine Nummer
    ("1234/2026", [_anlage(0, "Plan"), _anlage(1, "Vorlage 17-0815-2019")], (0, "erste", {"uebergangen"})),
    # offen (TECHNIK.md, Prüfung stk): Monat und Jahr ohne Tag zählen weiter als andere Nummer
    ("1234/2026", [_anlage(0, "Plan"), _anlage(1, "Beschlussvorlage Stand 11/2025")], (0, "erste", {"uebergangen"})),
])
def test_datum_im_namen_ist_keine_nummer(reference, namen, erwartet):
    """Ein Datum wie „17-11-2026“ im Namen ist weder die eigene Drucksache noch eine andere Nummer: Tag, Monat und Jahr
    statt Nummer NNNN/JJJJ (_im_datum). Orakel: Datei, Zweig und Hinweise je Fall."""
    p = {"reference": reference, "auxiliaryFile": namen}
    f, quelle, zweig, hinweise = dokumente.wahl_mit_zweig(p)
    assert (f["id"], zweig, set(hinweise)) == (f"F{erwartet[0]}", erwartet[1], erwartet[2])
    assert (f, quelle) == dokumente.datei_wahl(p)


def test_regel_unter_auxiliaryFile_in_der_abrufstatistik():
    """Log und Abrufstatistik zählen je Zweig und Hinweis (nur Zahlen), in der Auswahl und im Lauf; Hinweise je Vorlage
    (Prüfung stk: die Beschriftung nennt Vorlagen, nicht Dateien)."""
    kandidaten = [{"_zweig": z, "_hinweise": frozenset(h)} for z, h in (
        ("mainFile", ()), ("drucksache", ()), ("vorlage", ("uebergangen", "auch_anlage")),
        ("vorlage", ("auch_anlage",)), ("erste", ("uebergangen",)))]
    lauf = {"zweige": Counter({"vorlage": 2})}
    assert dokumente._regel_text(kandidaten, lauf) == (
        "Regel unter auxiliaryFile: Auswahl mit eigener Drucksache 1, mit dem Wort „Vorlage“ 2, erste PDF-Datei 1 "
        "(Hinweise: Vorlagen mit einer wegen anderer Nummer NNNN/JJJJ übergangenen Datei mit dem Wort „Vorlage“ 2, "
        "über das Wort „Vorlage“ gewählt und auch mit dem Wort „Anlage“ 2); in diesem Lauf mit eigener Drucksache 0, "
        "mit dem Wort „Vorlage“ 2, erste PDF-Datei 0")
    assert "in diesem Lauf" not in dokumente._regel_text(kandidaten)


@pytest.mark.parametrize("wert, grenze", [(None, 300), ("", 300), ("100", 100), ("300", 300), ("301", 300),
                                          ("1000", 300), ("0", 0), ("-5", 0), ("abc", 0)])
def test_variable_senkt_die_obergrenze_nur(monkeypatch, wert, grenze):
    """RATSATLAS_PDF_MAX kann die Grenze von 300 Dateien je Nacht nur senken (Brief an die Stadt, Punkt 4: höchstens
    300 Dokumente je Nacht; Prüfung stj)."""
    if wert is None:
        monkeypatch.delenv("RATSATLAS_PDF_MAX", raising=False)
    else:
        monkeypatch.setenv("RATSATLAS_PDF_MAX", wert)
    assert dokumente.hoechstens() == grenze


def test_hauptdatei_geht_vor():
    """Mit mainFile bleibt es die Wahl, auch wenn sie keine PDF-Datei ist (dann ausgeschlossen, keine Anlage
    ersatzweise); eine gelöschte Hauptdatei fehlt."""
    anlagen = [_anlage(1, "Vorlage")]
    haupt = _anlage(9, "Hauptdokument", mime="application/msword")
    assert dokumente.datei_wahl({"reference": "1/2026", "mainFile": haupt, "auxiliaryFile": anlagen}) == (
        haupt, "mainFile")
    assert dokumente.datei_wahl({"reference": "1/2026", "mainFile": dict(haupt, deleted=True),
                                 "auxiliaryFile": anlagen}) == (anlagen[0], "auxiliaryFile")
    assert dokumente.datei_wahl({"reference": "1/2026", "mainFile": None, "auxiliaryFile": anlagen})[1] == \
        "auxiliaryFile"


def test_anlage_wird_federfuehrung_eine_stufe_niedriger(oparl, monkeypatch):
    """Ende zu Ende gegen den Testserver: Vorlagen ohne mainFile lesen genau eine Datei aus auxiliaryFile (die als
    Vorlage benannte, sonst die erste PDF-Datei; nie eine Tabelle). build übernimmt die Kennung als Methode
    pdf_kopf_anlage mit Konfidenz „niedrig“ (eine Stufe unter der Hauptdatei) und Fundstelle „Kopf der Anlage (S. 1)“;
    die ausgeschriebene Form aus einer Anlage nicht. Abrufstatistik mit Herkunft und Vorlagen ohne PDF-Datei; export
    und check wie bei der Hauptdatei."""
    _mit_dateien(oparl, {1: KOPF})
    _vorlage(oparl, 9)
    _vorlage(oparl, 3)["auxiliaryFile"] = [_datei(oparl, 30, _pdf([["Anlage 1: Lageplan"]]), name="Anlage 1"),
                                           _datei(oparl, 31, _pdf([["Dezernat, Dienststelle", "II/II/2"]]),
                                                  name="Vorlage")]
    _vorlage(oparl, 5)["auxiliaryFile"] = [_datei(oparl, 50, _pdf([["Dezernat VI, 61/2"]]), name="Mitteilung")]
    _vorlage(oparl, 7)["auxiliaryFile"] = [_datei(oparl, 70, b"PK", name="Vorlage",
                                                  mimeType="application/vnd.ms-excel")]
    _vorlage(oparl, 9)["auxiliaryFile"] = [_datei(oparl, 90, b"DOC", name="Vorlage", mimeType="application/msword"),
                                           _datei(oparl, 91, _pdf([KOPF]), name="Anlage 2")]
    # ein Antrag mit der Vorlage der Verwaltung als Anlage: weder gelesen noch mit ihrer Kennung
    _vorlage(oparl, 4)["auxiliaryFile"] = [_vorlage(oparl, 3)["auxiliaryFile"][1]]
    _vorlage(oparl, 9)["date"] = "2026-11-05"   # im Zeitraum des Plans (Stand 01.11.2026, geprüft am 13.11.2026)
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/91.pdf", "/files/50.pdf", "/files/31.pdf", "/files/1.pdf"]
    e = {x["paper"].rsplit("/", 1)[1]: x for x in _eintraege()}
    assert {k: (x["quelle"], x["trefferart"], x["kennung"]) for k, x in e.items()} == {
        "1": ("mainFile", "kennung", "VI/61"), "3": ("auxiliaryFile", "kennung", "II/II/2"),
        "5": ("auxiliaryFile", "dezernat_dienststelle", "VI/61/2"), "9": ("auxiliaryFile", "kennung", "VI/61")}
    assert all(dokumente.eintrag_gueltig(x) for x in e.values())
    ergebnis = _statistik()[-1]["ergebnis"]
    assert ("Herkunft: Auswahl aus mainFile 1, aus auxiliaryFile 3; in diesem Lauf aus mainFile 1, aus "
            "auxiliaryFile 3; Vorlagen ohne PDF-Datei 1; Regel unter auxiliaryFile: Auswahl mit eigener Drucksache 0, "
            "mit dem Wort „Vorlage“ 1, erste PDF-Datei 2 (Hinweise: Vorlagen mit einer wegen anderer Nummer NNNN/JJJJ "
            "übergangenen Datei mit dem Wort „Vorlage“ 0, über das Wort „Vorlage“ gewählt und auch mit dem Wort "
            "„Anlage“ 0); in diesem Lauf mit eigener Drucksache 0, mit dem Wort „Vorlage“ 1, erste PDF-Datei 2"
            ) in ergebnis
    build.build()
    db = sqlite3.connect(config.DB)
    resp = {pid.rsplit("/", 1)[1]: r for pid, *r in db.execute(
        "SELECT paper_id, organization_id, method, evidence, derived, confidence, kennung FROM paper_responsibility")}
    assert resp == {
        "1": [None, "pdf_kopf", "Kopf der Vorlage (S. 1): VI/61", 1, "mittel", "VI/61"],
        "3": [None, "pdf_kopf_anlage", "Kopf der Anlage (S. 1): II/II/2", 1, "niedrig", "II/II/2"],
        "9": [None, "pdf_kopf_anlage", "Kopf der Anlage (S. 1): VI/61", 1, "niedrig", "VI/61"]}
    assert check.federfuehrung_kopf(db) == []
    export.export()
    papers = {p["reference"]: p for f in (config.EXPORT / config.STADT).rglob("*.json") if f.name != "index.json"
              for p in (json.loads(f.read_text()).get("papers") or []) if isinstance(p, dict) and "responsibility" in p}
    # Zuordnung über die Ämtertabelle wie bei der Hauptdatei: vor dem ältesten Plan nur der Status, im Zeitraum des
    # Plans Dezernat und Dienststelle
    assert papers["1003/2026"]["responsibility"] == [{
        "kind": "federfuehrend", "method": "pdf_kopf_anlage", "evidence": "Kopf der Anlage (S. 1): II/II/2",
        "derived": 1, "confidence": "niedrig", "kennung": "II/II/2", "label": None, "name": None,
        "aemtertabelle": {"status": aemter.VOR_PLAN, "methode": "kennung"}}]
    anlage = papers["1009/2026"]["responsibility"][0]
    assert (anlage["method"], anlage["kennung"]) == ("pdf_kopf_anlage", "VI/61")
    assert anlage["aemtertabelle"] == aemter.fuer_export(aemter.zuordnen(kennung="VI/61", datum="2026-11-05"))
    assert anlage["aemtertabelle"]["status"] == aemter.EINDEUTIG
    assert papers["1005/2026"]["responsibility"] == []


def _nacht_mit_aenderung(oparl, monkeypatch, stunden, **vorlagen):
    """Die Stadt ändert Vorlagen (neues modified), Abruf und Dokumentschritt; liefert die Dateianfragen der Nacht."""
    neu = (datetime.now(timezone.utc) + timedelta(hours=stunden)).isoformat(timespec="seconds")
    for i, aendern in vorlagen.items():
        aendern(_vorlage(oparl, int(i.removeprefix("p"))))
        _vorlage(oparl, int(i.removeprefix("p")))["modified"] = neu
    sessionnet.fetch_all()
    oparl.anfragen.clear()
    dokumente.schritt()
    return _dateianfragen(oparl)


def _federfuehrung(pid):
    build.build()
    db = sqlite3.connect(config.DB)
    zeilen = db.execute("SELECT method, confidence, kennung FROM paper_responsibility WHERE paper_id = ?",
                        (pid,)).fetchall()
    assert check.federfuehrung_kopf(db) == []
    return zeilen


def test_hauptdatei_ersetzt_anlage_und_neue_wahl_ersetzt_alte(oparl, monkeypatch):
    """Wird eine gelesene Anlage später zur Hauptdatei (dieselbe Datei), wird sie einmal neu gelesen und gilt dann als
    Hauptdatei (pdf_kopf, mittel); danach nicht wieder. Ändert sich die Wahl unter auxiliaryFile (eine neue Datei mit
    der Drucksache im Namen), wird nur die neue Datei gelesen und ersetzt das alte Ergebnis; kommt später eine
    Hauptdatei, die nicht lesbar ist (404), gilt kein altes Ergebnis einer Anlage mehr."""
    _freigabe(monkeypatch)
    a = _datei(oparl, 10, _pdf([KOPF]), name="Vorlage")
    _vorlage(oparl, 1)["auxiliaryFile"] = [a]
    b = _datei(oparl, 30, _pdf([["Dezernat, Dienststelle", "IV/41"]]), name="Anlage")
    _vorlage(oparl, 3)["auxiliaryFile"] = [b]
    assert _nacht_mit_aenderung(oparl, monkeypatch, 1) == ["/files/30.pdf", "/files/10.pdf"]
    p1, p3 = f"{oparl.b}/papers/1", f"{oparl.b}/papers/3"
    assert _federfuehrung(p1) == [("pdf_kopf_anlage", "niedrig", "VI/61")]
    assert _federfuehrung(p3) == [("pdf_kopf_anlage", "niedrig", "IV/41")]

    def befoerdern(p):
        p["mainFile"], p["auxiliaryFile"] = a, []
    assert _nacht_mit_aenderung(oparl, monkeypatch, 2, p1=befoerdern) == ["/files/10.pdf"]
    assert _federfuehrung(p1) == [("pdf_kopf", "mittel", "VI/61")]
    assert _nacht_mit_aenderung(oparl, monkeypatch, 3) == []

    c = _datei(oparl, 31, _pdf([["Dezernat, Dienststelle", "V/50"]]), fileName="1003-2026.pdf")
    assert _nacht_mit_aenderung(oparl, monkeypatch, 4, p3=lambda p: p.update(auxiliaryFile=[b, c])) == \
        ["/files/31.pdf"]
    assert _federfuehrung(p3) == [("pdf_kopf_anlage", "niedrig", "V/50")]
    d = _datei(oparl, 32, (404, {}, b""))
    assert _nacht_mit_aenderung(oparl, monkeypatch, 5, p3=lambda p: p.update(mainFile=d)) == ["/files/32.pdf"]
    assert _federfuehrung(p3) == []
    e = {x["file"].rsplit("/", 1)[1]: (x["quelle"], x["status"]) for x in _eintraege()}
    assert e == {"10": ("mainFile", "ok"), "30": ("auxiliaryFile", "ok"), "31": ("auxiliaryFile", "ok"),
                 "32": ("mainFile", "http_404")}


def test_datei_einer_ausgeschlossenen_vorlage_wird_nie_gelesen():
    """Eine Datei, die auch bei einer Vorlage ohne Hauskoordinate (hier eine Eingabe) oder einer nicht öffentlich
    beratenen steht, wird über keine andere Vorlage gelesen (etwa als Anlage einer Mitteilung). Eine Datei, die für eine
    Vorlage Hauptdatei und für eine andere Anlage ist, zählt einmal, als Hauptdatei (gleich in welcher Reihenfolge)."""
    b = "http://127.0.0.1:8"

    def datei(i, **felder):
        return {"id": f"{b}/files/{i}", "accessUrl": f"{b}/files/{i}.pdf", "mimeType": "application/pdf",
                "name": "Vorlage", **felder}

    def vorlage(i, art="Beschlussvorlage", **felder):
        return {"id": f"{b}/papers/{i}", "reference": f"{2000 + i}/2026", "paperType": art, "name": f"Vorlage {i}",
                "date": "2026-10-01", "created": f"2026-10-01T10:00:{i:02d}+02:00", "consultation": [], **felder}
    roh = [vorlage(1, auxiliaryFile=[datei(20)]),
           vorlage(2, art="Anregungen und Beschwerden", mainFile=datei(20)),
           vorlage(3, auxiliaryFile=[datei(40)]),
           vorlage(4, consultation=[{"id": f"{b}/c/4"}], mainFile=datei(41), auxiliaryFile=[datei(40)]),
           vorlage(5, auxiliaryFile=[datei(60)]),
           vorlage(6, mainFile=datei(60))]
    beratungen = [{"uri": f"{b}/c/4", "agendaItem": {"public": False}}]
    from unittest import mock
    with mock.patch.object(config, "OPARL_BODY", f"{b}/body"):
        kandidaten, gruende = dokumente.auswahl(roh, [], beratungen, {})
    assert [(k["file"].rsplit("/", 1)[1], k["paper"].rsplit("/", 1)[1], k["quelle"]) for k in kandidaten] == [
        ("60", "6", "mainFile")]
    # die Eingabe zählt als Vorlagenart, die nicht der Verwaltung ist; ihre Datei bleibt trotzdem gesperrt
    assert (gruende["datei_gesperrt"], gruende["doppelt"], gruende["vorlagenart"], gruende["nicht_oeffentlich"]) == (
        2, 1, 1, 1)


# --- Prüfung dok2: Dateien ausgelassener Vorlagen und dieselbe Adresse unter anderer Kennung -------------------------------

B_AUSWAHL = "http://127.0.0.1:8"


def _datei_roh(i, **felder):
    """Erfundenes Dateiobjekt wie in papers.jsonl (Host des Testservers, PDF)."""
    return {"id": f"{B_AUSWAHL}/files/{i}", "accessUrl": f"{B_AUSWAHL}/files/{i}.pdf", "mimeType": "application/pdf",
            "name": "Vorlage", **felder}


def _vorlage_roh(i, art="Beschlussvorlage", **felder):
    """Erfundene Vorlage wie in papers.jsonl (Drucksache 2000+i/2026, ohne Beratung)."""
    return {"id": f"{B_AUSWAHL}/papers/{i}", "reference": f"{2000 + i}/2026", "paperType": art,
            "name": f"Erfundene Vorlage {i}", "date": "2026-10-01", "created": f"2026-10-01T10:00:{i:02d}+02:00",
            "consultation": [], **felder}


def _auswahl(roh, beratungen=()):
    """(gelesene Dateien als [(Datei, Vorlage)], Gründe) ohne Anfrage."""
    from unittest import mock
    with mock.patch.object(config, "OPARL_BODY", f"{B_AUSWAHL}/body"):
        kandidaten, gruende = dokumente.auswahl(roh, [], list(beratungen), {})
    return [(k["file"].rsplit("/", 1)[1], k["paper"].rsplit("/", 1)[1]) for k in kandidaten], gruende


@pytest.mark.parametrize("auslassen", [
    {"reference": None}, {"reference": ""}, {"reference": "   "}, {"reference": ["2002/2026"]}, "ohne_feld",
    {"deleted": True},                                     # mit gültiger Drucksache, aber als gelöscht gemeldet
])
@pytest.mark.parametrize("feld", ["mainFile", "auxiliaryFile"])
@pytest.mark.parametrize("art", ["Anregungen und Beschwerden", "Beschlussvorlage"])
def test_datei_einer_ausgelassenen_vorlage_wird_nie_gelesen(auslassen, feld, art):
    """Prüfung dok2: Eine Vorlage, die build.einlesen auslässt (ohne Drucksachennummer, mit einer Nummer, die keine
    Zeichenkette ist, oder als gelöscht gemeldet), hat keine Erlaubnis (dokumente.gesperrt wie build); ihre Dateien
    werden auch über eine andere Vorlage nie gelesen, gleich welcher Art sie ist und ob die Datei bei ihr Hauptdatei oder
    Anlage ist. Vorher fehlten diese Vorlagen in der Menge der ausgeschlossenen Dateien (nur Vorlagen nach einlesen).
    Gegenprobe: eine Verwaltungsvorlage mit eigener Datei wird gelesen."""
    eingabe = _vorlage_roh(2, art=art, **{feld: _datei_roh(20) if feld == "mainFile" else [_datei_roh(20)]})
    if auslassen == "ohne_feld":
        del eingabe["reference"]
    else:
        eingabe.update(auslassen)
    roh = [_vorlage_roh(1, auxiliaryFile=[_datei_roh(20)]), eingabe, _vorlage_roh(3, auxiliaryFile=[_datei_roh(30)])]
    gelesen, gruende = _auswahl(roh)
    assert gelesen == [("30", "3")]
    assert gruende["datei_gesperrt"] == 1 and sum(gruende.values()) == 1


def test_ausgeschlossene_datei_unter_anderer_kennung_oder_schreibung():
    """Prüfung dok2: Verglichen werden Kennung, downloadUrl und accessUrl in vorsichtig angeglichener Form
    (dokumente._adresse): dieselbe Adresse unter einer anderen Kennung, in anderer Schreibung (Groß- und Kleinschreibung,
    Prozentkodierung, doppelte „/“, „./“, Reihenfolge der Query), ein Verweis als Zeichenkette statt eines Objekts und
    eine zweite Zeile derselben ausgeschlossenen Vorlage mit einer anderen Datei sperren die Datei. Gegenproben: ähnliche,
    aber andere Adressen werden gelesen."""
    b, eingabe = B_AUSWAHL, "Anregungen und Beschwerden"
    roh = [
        # gleiche accessUrl, andere Kennung (der Fall aus der Prüfung)
        _vorlage_roh(1, auxiliaryFile=[_datei_roh(23, accessUrl=f"{b}/files/99.pdf")]),
        _vorlage_roh(2, art=eingabe, mainFile=_datei_roh(99)),
        # downloadUrl der Anlage in anderer Schreibung als die downloadUrl der Eingabe
        _vorlage_roh(3, auxiliaryFile=[_datei_roh(24, downloadUrl="HTTP://127.0.0.1:8//files/./%39%38.PDF")]),
        _vorlage_roh(4, art=eingabe, auxiliaryFile=[_datei_roh(98, downloadUrl=f"{b}/files/98.pdf")]),
        # Verweis als Zeichenkette bei einer Eingabe ohne Drucksachennummer
        _vorlage_roh(5, auxiliaryFile=[_datei_roh(97)]),
        {**_vorlage_roh(6, art=eingabe), "reference": None, "mainFile": f"{b}/files/97"},
        # Query in anderer Reihenfolge
        _vorlage_roh(7, auxiliaryFile=[_datei_roh(25, accessUrl=f"{b}/getfile.pdf?type=do&id=5")]),
        _vorlage_roh(8, art=eingabe, mainFile=_datei_roh(26, accessUrl=f"{b}/getfile.pdf?id=5&type=do")),
        # dieselbe Eingabe zweimal geliefert (seitenweiser Abruf), zuerst mit Datei 80, zuletzt mit Datei 81
        _vorlage_roh(9, auxiliaryFile=[_datei_roh(80)]),
        _vorlage_roh(11, art=eingabe, mainFile=_datei_roh(80)),
        _vorlage_roh(11, art=eingabe, mainFile=_datei_roh(81)),
        # Gegenproben: andere Nummer, anderer Wert in der Query, anderer Host
        _vorlage_roh(12, auxiliaryFile=[_datei_roh(990)]),
        _vorlage_roh(13, auxiliaryFile=[_datei_roh(27, accessUrl=f"{b}/getfile.pdf?id=55&type=do")]),
        _vorlage_roh(14, auxiliaryFile=[_datei_roh(28)]),
        _vorlage_roh(15, art=eingabe, mainFile=_datei_roh(29, accessUrl="http://127.0.0.2:8/files/28.pdf")),
    ]
    gelesen, gruende = _auswahl(roh)
    assert sorted(gelesen) == [("27", "13"), ("28", "14"), ("990", "12")]
    assert (gruende["datei_gesperrt"], gruende["vorlagenart"]) == (5, 5)


@pytest.mark.parametrize("wert, gleich", [
    ("http://127.0.0.1:8/files/1.pdf", ["HTTPS://127.0.0.1/files/1.pdf", "http://user@127.0.0.1.:8/files/1.pdf#x",
                                        "http://127.0.0.1:8/files//1%2Epdf", "http://127.0.0.1:8/a/../files/1.pdf",
                                        " http://127.0.0.1:8/FILES/1.pdf "]),
    ("http://127.0.0.1:8/getfile?id=1&type=do", ["http://127.0.0.1:8/getfile?type=do&id=1&",
                                                  "http://127.0.0.1:8/getfile?type=d%6F&id=1"]),
])
def test_vergleichsform_der_adressen(wert, gleich):
    """dokumente._adresse: Schreibvarianten derselben Adresse ergeben dieselbe Vergleichsform (für den Ausschluss eher
    zu weit als zu eng); andere Dateien bleiben verschieden; anderes als eine nicht leere Zeichenkette ergibt None."""
    assert {dokumente._adresse(w) for w in gleich} == {dokumente._adresse(wert)}
    for anders in ("http://127.0.0.1:8/files/10.pdf", "http://127.0.0.1:8/files/1.pdf/x", "http://127.0.0.2:8/files/1.pdf",
                   "http://127.0.0.1:8/getfile?id=11&type=do", "http://127.0.0.1:8/getfile?id=1"):
        assert dokumente._adresse(anders) != dokumente._adresse(wert)
    for leer in (None, "", "  ", 7, {"id": wert}, ["x"]):
        assert dokumente._adresse(leer) is None


def test_ausgelassene_eingabe_ohne_nummer_im_lauf(oparl, monkeypatch):
    """Ende zu Ende gegen den Testserver (Prüfung dok2): Eine Eingabe ohne Drucksachennummer hat dieselbe Datei als
    Hauptdatei, die eine Verwaltungsvorlage als Anlage führt; eine zweite Verwaltungsvorlage führt eine Datei mit
    derselben Adresse unter anderer Kennung wie eine gelöschte Vorlage. Keine der beiden Dateien wird angefragt; die
    übrige Verwaltungsvorlage wird gelesen."""
    _freigabe(monkeypatch)
    geteilt = _datei(oparl, 10, _pdf([KOPF]), name="Vorlage")
    _vorlage(oparl, 1)["auxiliaryFile"] = [geteilt]
    eingabe = _vorlage(oparl, 2)
    eingabe.update(reference=None, paperType="Anregungen und Beschwerden", mainFile=dict(geteilt))
    _vorlage(oparl, 3)["auxiliaryFile"] = [_datei(oparl, 30, _pdf([KOPF]), accessUrl=f"{oparl.b}/files/40.pdf")]
    _vorlage(oparl, 4).update(deleted=True, mainFile=_datei(oparl, 40, _pdf([KOPF])))
    _mit_dateien(oparl, {5: KOPF})
    sessionnet.fetch_all()
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/5.pdf"]
    assert [x["paper"].rsplit("/", 1)[1] for x in _eintraege()] == ["5"]


@pytest.mark.parametrize("methode, evidenz, konfidenz, doppelt", [
    ("pdf_kopf_anlage", "Kopf der Anlage (S. 1): VI/61", "mittel", False),     # Anlage höchstens „niedrig“
    ("pdf_kopf_anlage", "Kopf der Vorlage (S. 1): VI/61", "niedrig", False),   # Fundstelle der Hauptdatei
    ("pdf_kopf", "Kopf der Anlage (S. 1): VI/61", "mittel", False),
    ("pdf_kopf_anlage", "Kopf der Anlage (S. 1): VI/61", "niedrig", True),     # zwei Zeilen je Vorlage
])
def test_check_meldet_kopf_der_anlage_in_anderer_form(oparl, monkeypatch, methode, evidenz, konfidenz, doppelt):
    """Gegenprobe zu check.federfuehrung_kopf: Fundstelle und Konfidenz müssen zur Methode passen, höchstens eine Zeile
    je Vorlage; die richtige Zeile allein ist kein Befund."""
    sessionnet.fetch_all()
    build.build()
    db = sqlite3.connect(config.DB)
    pid = f"{oparl.b}/papers/1"
    zeile = "INSERT INTO paper_responsibility VALUES (?, NULL, 'federfuehrend', ?, ?, 1, ?, 'VI/61')"
    db.execute(zeile, (pid, "pdf_kopf_anlage", "Kopf der Anlage (S. 1): VI/61", "niedrig"))
    assert check.federfuehrung_kopf(db) == []
    if not doppelt:
        db.execute("DELETE FROM paper_responsibility WHERE paper_id = ?", (pid,))
    db.execute(zeile, (pid, methode, evidenz, konfidenz))
    befunde = check.federfuehrung_kopf(db)
    assert befunde and "1001/2026" in befunde[0]


def test_eintrag_nur_mit_bekannter_herkunft():
    """Einträge der Dokumente nur mit Herkunft mainFile oder auxiliaryFile (sonst verworfen)."""
    e = {"file": "F", "paper": "P", "quelle": "mainFile", "sha256": "", "groesse": None,
         "zeit": "2026-11-13T22:30:00+00:00", "kennung": "VI/61", "trefferart": "kennung", "status": "ok",
         "fehlerart": "", "fehlversuche": 0, "modified": None, "size": None, "accessUrl": None, "downloadUrl": None}
    assert dokumente.eintrag_gueltig(e) and dokumente.eintrag_gueltig(dict(e, quelle="auxiliaryFile"))
    for quelle in ("anlage", "", None, ["mainFile"]):
        assert not dokumente.eintrag_gueltig(dict(e, quelle=quelle))
    assert not dokumente.eintrag_gueltig({k: v for k, v in e.items() if k != "quelle"})


# --- Entscheidung 17.11.2026 (6): Schritt 3 der Regel B ohne übergangene Dateien --------------------------------------

def test_auswahl_zaehlt_vorlagen_nur_mit_uebergangenen_dateien():
    """Entscheidung 17.11.2026 (6): Trägt jede PDF-Datei einer Vorlage das Wort „Vorlage“ und eine andere Nummer, wird
    keine Datei gewählt; die Vorlage zählt unter „nur_uebergangen“, nicht unter „ohne_datei“. Mit einer weiteren
    PDF-Datei ohne das Wort „Vorlage“ wird diese gewählt (Zweig „erste“, Hinweis „uebergangen“ je Vorlage einmal), auch
    wenn sie eine andere Nummer trägt."""
    roh = [_vorlage_roh(1, auxiliaryFile=[_datei_roh(10, name="Vorlage 0815/2019"),
                                          _datei_roh(11, name="Anlage 1 Lageplan")]),
           _vorlage_roh(2, auxiliaryFile=[_datei_roh(20, name="Vorlage 0815/2019")]),
           _vorlage_roh(3, auxiliaryFile=[_datei_roh(30, name="Vorlage 0815/2019"),
                                          _datei_roh(31, name="Beschlussvorlage 0816/2019")]),
           _vorlage_roh(4, auxiliaryFile=[_datei_roh(40, name="Mitteilung 0815/2019")]),
           _vorlage_roh(5)]
    from unittest import mock
    with mock.patch.object(config, "OPARL_BODY", f"{B_AUSWAHL}/body"):
        kandidaten, gruende = dokumente.auswahl(roh, [], [], {})
    gewaehlt = sorted(((k["file"].rsplit("/", 1)[1], k["paper"].rsplit("/", 1)[1], k["_zweig"], set(k["_hinweise"]))
                       for k in kandidaten), key=lambda w: w[0])
    assert gewaehlt == [("11", "1", "erste", {"uebergangen"}), ("40", "4", "erste", set())]
    assert (gruende["nur_uebergangen"], gruende["ohne_datei"], sum(gruende.values())) == (2, 1, 3)


def test_nur_uebergangene_dateien_ohne_anfrage_und_ohne_kopf(oparl, monkeypatch, capsys):
    """Entscheidung 17.11.2026 (6), Ende zu Ende gegen den Testserver: Für eine Vorlage, deren einzige PDF-Datei das
    Wort „Vorlage“ und eine andere Nummer trägt, geht keine Anfrage hinaus; Log und Abrufstatistik zählen sie unter dem
    neuen Grund. Steht daneben eine PDF-Datei ohne das Wort „Vorlage“, wird diese gelesen. build übernimmt für die erste
    Vorlage keine Kennung, auch nicht aus einem Eintrag für die übergangene Datei (etwa nach der Regel vor (6) gelesen):
    Auswahl und Aufbau bleiben über datei_wahl einig."""
    fremd = _pdf([["Stadt Köln", "Beschlussvorlage", "Dezernat, Dienststelle", "II/II/2", "Vorlagen-Nummer 0815/2019"]])
    _vorlage(oparl, 3)["auxiliaryFile"] = [_datei(oparl, 30, fremd, name="Vorlage 0815/2019")]
    _vorlage(oparl, 5)["auxiliaryFile"] = [_datei(oparl, 50, fremd, name="Vorlage 0815/2019"),
                                           _datei(oparl, 51, _pdf([KOPF]), name="Anlage 1 Lageplan")]
    sessionnet.fetch_all()
    _freigabe(monkeypatch)
    dokumente.schritt()
    assert _dateianfragen(oparl) == ["/files/51.pdf"]
    ergebnis = _statistik()[-1]["ergebnis"]
    assert ("ohne mainFile und ohne PDF-Datei in auxiliaryFile 1, nur PDF-Dateien mit dem Wort „Vorlage“ und anderer "
            "Nummer NNNN/JJJJ 1, Datei schon ausgewählt 0") in ergebnis
    assert ("Regel unter auxiliaryFile: Auswahl mit eigener Drucksache 0, mit dem Wort „Vorlage“ 0, erste PDF-Datei 1 "
            "(Hinweise: Vorlagen mit einer wegen anderer Nummer NNNN/JJJJ übergangenen Datei mit dem Wort „Vorlage“ 1, "
            "über das Wort „Vorlage“ gewählt und auch mit dem Wort „Anlage“ 0)") in ergebnis
    log = capsys.readouterr().out
    assert ("1 Verwaltungsvorlagen ohne mainFile und ohne PDF-Datei in auxiliaryFile; 1 Verwaltungsvorlagen ohne "
            "Datei, weil alle PDF-Dateien das Wort „Vorlage“ und eine andere Nummer NNNN/JJJJ tragen") in log
    assert "Datei schon ausgewählt 0" in log   # die Abrufstatistik auch im Log
    # ein Eintrag mit Kennung für die übergangene Datei 30 (wie nach der Regel vor (6) gelesen) gilt beim Aufbau nicht
    e51 = next(x for x in _eintraege() if x["file"].endswith("/files/51"))
    datei30 = _vorlage(oparl, 3)["auxiliaryFile"][0]
    dokumente._anhaengen(dict(e51, file=datei30["id"], paper=f"{oparl.b}/papers/3", kennung="II/II/2",
                              **{m: datei30.get(m) for m in dokumente.MERKMALE}))
    assert datei30["id"] in dokumente.koepfe()
    build.build()
    db = sqlite3.connect(config.DB)
    assert {pid.rsplit("/", 1)[1]: (m, k) for pid, m, k in db.execute(
        "SELECT paper_id, method, kennung FROM paper_responsibility")} == {"5": ("pdf_kopf_anlage", "VI/61")}
    assert check.federfuehrung_kopf(db) == []
