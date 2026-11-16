"""Feldabdeckung der Rohdaten (tools/feldabdeckung.py, Schritt in pages.yml gleich nach dem Fortschritt des Abrufs):
nur Anzahlen, Anteile und vorsichtig gefilterte Kategorien aus data/raw, auch als Zwischenstand eines laufenden
Vollabrufs (fertige Datei und Teildatei, je Kennung einmal wie build); fehlende oder unlesbare Dateien halten den Lauf
nie an. Alle Objekte sind erfunden (Test oder lokaler Testserver); keine Anfragen an die Stadt."""
import importlib.util
import json
import os
import subprocess
import sys
import time

import pytest

from pipeline import abruf, build, config, sessionnet

ROOT = config.ROOT
B = "https://oparl.example.invalid/oparl"


def _modul():
    spec = importlib.util.spec_from_file_location("feldabdeckung", ROOT / "tools" / "feldabdeckung.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture
def fa(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return _modul()


def _jsonl(pfad, zeilen):
    """Schreibt Objekte (als JSON) und Texte (unverändert, etwa kaputte Zeilen) zeilenweise."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        for z in zeilen:
            f.write((z if isinstance(z, str) else json.dumps(z, ensure_ascii=False)) + "\n")


def _vorlage(i, **felder):
    return {"id": f"{B}/papers/{i}", "reference": f"{1000 + i}/2026", "name": f"Erfundene Vorlage {i}",
            "paperType": "Beschlussvorlage", "date": "2026-10-01", **felder}


def _aufruf(fa, raw, capsys, *weitere, zusammenfassung=None, monkeypatch=None):
    if zusammenfassung is not None:
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(zusammenfassung))
    assert fa.main(["--raw", str(raw), *weitere]) == 0
    return capsys.readouterr().out


def test_fertige_datei_und_teildatei_je_kennung_einmal(fa, tmp_path, capsys):
    """Zwischenstand eines laufenden Vollabrufs: fertige Datei und Teildatei zusammen, je Kennung die zuletzt gelesene
    Fassung ohne Löschvermerk (wie build._je_kennung_einmal); eine Löschung zählt nur ohne eine solche Fassung.
    Kaputte Zeilen, Zeilen ohne Kennung und Leerzeilen werden gezählt bzw. übergangen."""
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [
        _vorlage(1), _vorlage(2), {"id": f"{B}/papers/3", "deleted": True}, "{kaputt", "", [1, 2],
        {"name": "ohne Kennung"}, _vorlage(4, date=None)])
    _jsonl(sessionnet._teil(raw / "papers.jsonl"), [
        _vorlage(1, underDirectionOf=[f"{B}/organizations/amt"]), _vorlage(5, reference="AN/0105/2025",
                                                                         date="2025-03-01"),
        {"id": f"{B}/papers/2", "deleted": True}, _vorlage(6, reference="AN/7/2026")])
    (raw / "zustand_abruf.json").write_text(json.dumps({"papers_fortsetzung": {
        "naechste": f"{B}/papers?page=3", "seiten": 2, "start": "2026-11-15T22:10:00+00:00"}}), encoding="utf-8")
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    r = a["listen"]["papers"]
    w = r["auswertung"]
    assert (w.n, w.geloescht, r["ersetzt"]) == (5, 1, 2)   # 1, 2, 4, 5, 6; gelöscht nur 3; 1 und 2 doppelt
    assert w.feld["underDirectionOf"] == 1                    # die jüngere Fassung von 1 gilt
    assert w.jahre == {2026: 3, 2025: 1, "fehlt": 1}
    assert w.referenz == {"NNNN/JJJJ": 3, "AN/NNNN/JJJJ": 1, "AN/N/JJJJ oder N/JJJJ mit 1 bis 3 Ziffern": 1}
    assert r["stand"].startswith("Zwischenstand: Vollabruf läuft") and "und der Stand davor" in r["stand"]
    assert r["dateien"]["papers.jsonl"] == "gelesen: 7 Zeilen, davon 1 unlesbar und 2 ohne Kennung"
    assert r["dateien"]["papers.teil.jsonl"] == "gelesen: 4 Zeilen"
    # was der fertige Vollabruf aus der Teildatei behält (sessionnet._zusammenfuehren mit voll=True): 1, 5, 2
    # (gelöscht, obwohl es 2 im Stand davor ohne Löschvermerk gibt), 6; 3 und 4 aus dem Stand davor fallen weg
    assert r["nur_teil"] == {"kennungen": 4, "geloescht": 1}
    out = _aufruf(fa, raw, capsys)
    assert "Stand: Zwischenstand: Vollabruf läuft (Fortsetzung steht aus)" in out
    assert ("Nur aus der Teildatei: 4 Kennungen, davon 1 zuletzt als gelöscht gemeldet. Der fertige Vollabruf behält "
            "nur die darin und auf den übrigen Seiten gelesenen Objekte") in out
    assert "Vorlagen je Kennung: 5; als gelöscht gemeldet (deleted, getrennt): 1" in out
    assert "Fassungen derselben Kennung (je Kennung einmal gezählt): 2 ersetzt" in out
    assert "  underDirectionOf: 1 (20,0 %)" in out
    # Sitzungen und Gremien fehlen: gesagt, kein Fehler
    assert "Dateien: meetings_roh.jsonl fehlt; meetings_roh.teil.jsonl fehlt" in out
    assert "Dateien: organizations.jsonl fehlt; organizations.teil.jsonl fehlt" in out
    assert "liest die Sitzungen nach den Vorlagen" in out


@pytest.mark.parametrize("zustand, erwartet", [
    (None, "unbekannt (zustand_abruf.json fehlt)"),
    ("{kaputt", "unbekannt (zustand_abruf.json unlesbar)"),
    ({}, "noch kein vollständiger Abruf; papers.teil.jsonl ohne Fortsetzung im Zustand (veraltet"),
    ({"papers": "2026-11-12T22:10:00+00:00"}, "kein laufender Vollabruf (Liste zuletzt vollständig aktualisiert im "
                                              "Lauf ab 12.11.2026, 23:10 Uhr)"),
    ({"papers": "gestern"}, "kein laufender Vollabruf (Zeitpunkt des letzten Abrufs unlesbar)"),
])
def test_stand_nur_aus_dem_zustand(fa, tmp_path, zustand, erwartet):
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [_vorlage(1)])
    _jsonl(raw / "papers.teil.jsonl", [_vorlage(2)])
    if zustand is not None:
        (raw / "zustand_abruf.json").write_text(zustand if isinstance(zustand, str) else json.dumps(zustand),
                                                encoding="utf-8")
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    assert a["listen"]["papers"]["stand"].startswith(erwartet), a["listen"]["papers"]["stand"]
    assert a["listen"]["papers"]["auswertung"].n == 2   # die Teildatei zählt immer mit


def test_felder_der_vorlagen(fa, tmp_path, capsys):
    """Ortsangaben eingebettet und als Adresse, Abgleich mit den Stadtteilen wie Stufe A (geo.Ortsteile.by_name),
    Dateien, Anlagen je Vorlage, Beratungen mit Verweisen, Form der Felder, Kreuztabelle."""
    raw = tmp_path / "raw"
    punkt = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [6.95, 50.94]}}
    datei = {"id": f"{B}/files/1", "mimeType": "application/pdf"}
    papers = [
        _vorlage(1, location=[{"id": f"{B}/locations/1", "subLocality": "Altstadt-Nord", "geojson": punkt,
                               "postalCode": 50667}], mainFile=datei, auxiliaryFile=[datei, datei]),
        _vorlage(2, location=[f"{B}/locations/2"], auxiliaryFile=[f"{B}/files/2"]),
        _vorlage(3, location={"id": f"{B}/locations/3", "subLocality": "Erfundenes Viertel", "streetAddress": " "}),
        _vorlage(4, location=[7], mainFile=f"{B}/files/4", originatorPerson=[f"{B}/persons/1"],
                 originatorOrganization=[{"id": f"{B}/organizations/f"}], keyword=["erfunden"],
                 consultation=[{"id": f"{B}/c/1", "meeting": f"{B}/meetings/1", "agendaItem": f"{B}/a/1",
                                "organization": [f"{B}/organizations/rat"]}, f"{B}/c/2", None]),
        _vorlage(5, paperType="Antrag nach § 3 der Geschäftsordnung des Rates", relatedPaper=[f"{B}/papers/1"],
                 auxiliaryFile=[datei] * 6, consultation=[{"id": f"{B}/c/3", "meeting": f"{B}/meetings/1"}]),
    ]
    papers += [_vorlage(10 + i, paperType="Mitteilung", underDirectionOf=f"{B}/organizations/amt") for i in range(5)]
    _jsonl(raw / "papers.jsonl", papers)
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    w = a["listen"]["papers"]["auswertung"]
    assert a["abgleich"] and a["stadtteile"] == "86 Stadtteile"
    assert w.n == 10
    assert (w.ort["objekt"], w.ort["adresse"], w.ort["andere"]) == (2, 1, 1)
    assert (w.ort["subLocality"], w.ort["postalCode"], w.ort["streetAddress"], w.ort["geojson"], w.ort["punkt"],
            w.ort["stadtteil"]) == (2, 1, 0, 1, 1, 1)
    assert (w.feld["location"], w.feld["stadtteil"]) == (3, 1)   # [7] ist keine Ortsangabe
    assert (w.feld["mainFile"], w.feld["auxiliaryFile"], w.feld["nur_anlage"], w.feld["ohne_datei"]) == (2, 3, 2, 6)
    assert w.anlagen == {"0": 7, "2–5": 1, "1": 1, "mehr als 5": 1}
    assert (w.dateien["haupt_objekt"], w.dateien["haupt_adresse"], w.dateien["anlage_objekt"],
            w.dateien["anlage_adresse"]) == (1, 1, 8, 1)
    assert w.mime_anlage.zaehler == {"application/pdf": 8}
    assert (w.feld["originatorPerson"], w.feld["originatorOrganization"], w.feld["keyword"],
            w.feld["relatedPaper"], w.feld["underDirectionOf"]) == (1, 1, 1, 1, 5)
    assert (w.feld["consultation"], w.feld["beratung_meeting"], w.feld["beratung_agendaItem"]) == (2, 2, 1)
    assert (w.beratung["objekt"], w.beratung["adresse"], w.beratung["andere"], w.beratung["organization"]) == (
        2, 1, 1, 1)
    assert w.formen["location"] == {"Liste von Objekten": 1, "Liste von Zeichenketten": 1, "einzelnes Objekt": 1,
                                    "Liste, gemischt oder andere": 1, "fehlt": 6}
    assert w.formen["underDirectionOf"] == {"einzelne Zeichenkette": 5, "fehlt": 5}
    out = _aufruf(fa, raw, capsys)
    assert "  location mit subLocality = Stadtteil (geo.Ortsteile.by_name): 1 (10,0 %)" in out
    # Beschlussvorlage nur 4-mal, die Antragsart einmal: beide unter „sonstige“, auch in der Kreuztabelle
    assert "  „Mitteilung“: 5 (50,0 %)" in out and "Beschlussvorlage" not in out and "Antrag nach" not in out
    assert "  sonstige (2 Werte, 5 Objekte): 5 (50,0 %)" in out
    kreuz = out.split("Kreuztabelle")[1]
    assert "  „Mitteilung“: Vorlagen 5; underDirectionOf 100,0 %; originatorOrganization 0,0 %" in kreuz
    assert ("  übrige Vorlagenarten: Vorlagen 5; underDirectionOf 0,0 %; originatorOrganization 20,0 %; location "
            "60,0 %; mainFile 40,0 %; auxiliaryFile 60,0 %") in kreuz
    assert "  alle: Vorlagen 10; underDirectionOf 50,0 %" in kreuz


def test_sitzungen_und_gremien(fa, tmp_path, capsys):
    """Sitzungen mit eingebetteten Tagesordnungspunkten (public, result, Verweise) und als Adressen; Gremien mit
    Arten und Klassen; gelöschte getrennt."""
    raw = tmp_path / "raw"
    tops = [{"id": f"{B}/a/{i}", "public": i != 0, "result": "ungeändert beschlossen" if i < 5 else None,
             "consultation": f"{B}/c/{i}" if i < 3 else None} for i in range(7)]
    tops.append({"id": f"{B}/a/9", "public": None, "result": "Kenntnis genommen", "paper": f"{B}/papers/1"})
    meetings = [{"id": f"{B}/meetings/1", "start": "2026-10-01T17:00:00+02:00", "organization": [f"{B}/o/1"],
                 "agendaItem": tops},
                {"id": f"{B}/meetings/2", "start": "2025-02-01T17:00:00+01:00", "cancelled": True,
                 "agendaItem": [f"{B}/a/20", f"{B}/a/21"]},
                {"id": f"{B}/meetings/3", "agendaItem": None},
                {"id": f"{B}/meetings/4", "deleted": True}]
    _jsonl(raw / "meetings_roh.jsonl", meetings)
    orgs = [{"id": f"{B}/o/{i}", "organizationType": "Gremium", "classification": "Ausschuss" if i < 5 else None}
            for i in range(6)] + [{"id": f"{B}/o/9", "deleted": True}]
    _jsonl(raw / "organizations.jsonl", orgs)
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    s = a["listen"]["meetings"]["auswertung"]
    assert (s.n, s.geloescht, s.feld["abgesagt"], s.feld["organisation"], s.feld["mit_top"]) == (3, 1, 1, 1, 2)
    assert s.jahre == {2026: 1, 2025: 1, "fehlt": 1}
    assert s.top_anzahl == {"6–20": 1, "1–5": 1, "0": 1}
    assert (s.top["insgesamt"], s.top["objekt"], s.top["adresse"]) == (10, 8, 2)
    assert (s.top["nicht_oeffentlich"], s.top["oeffentlich"], s.top["oeffentlich_fehlt"]) == (1, 6, 1)
    assert (s.top["ergebnis"], s.top["consultation"], s.top["paper"]) == (6, 3, 1)
    assert s.top_form == {"Liste von Objekten": 1, "Liste von Zeichenketten": 1, "null": 1}
    g = a["listen"]["organizations"]["auswertung"]
    assert (g.n, g.geloescht) == (6, 1)
    out = _aufruf(fa, raw, capsys)
    assert "  nicht öffentlich (public false): 1 (12,5 %)" in out
    assert "  „ungeändert beschlossen“: 5 (62,5 %)" in out          # mindestens 5-mal: erscheint
    assert "  sonstige (1 Werte, 1 Objekte): 1 (12,5 %)" in out     # „Kenntnis genommen“ nur einmal
    assert "  fehlt oder leer: 2 (25,0 %)" in out
    assert "  „Gremium“: 6 (100,0 %)" in out and "  „Ausschuss“: 5 (83,3 %)" in out
    assert "Sitzungen je Kennung: 3; als gelöscht gemeldet (deleted, getrennt): 1" in out


def test_ersatz_im_kurzformat(fa, tmp_path, capsys):
    """Ohne meetings_roh.jsonl und organizations.jsonl (etwa mit tools/testdaten.py): meetings.json und
    organizations.json als Ersatz, gekennzeichnet; neben der fertigen Datei nie."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "meetings.json").write_text(json.dumps([{"id": f"{B}/m/1", "start": "2026-01-01T10:00:00+01:00",
                                                    "organization": [f"{B}/o/1"], "agenda_items": 3}]),
                                       encoding="utf-8")
    (raw / "organizations.json").write_text(json.dumps([{"id": f"{B}/o/1", "organizationType": "Gremium"}]),
                                            encoding="utf-8")
    out = _aufruf(fa, raw, capsys)
    assert ("Dateien: meetings_roh.jsonl fehlt; meetings_roh.teil.jsonl fehlt; meetings.json gelesen (Ersatz im "
            "Kurzformat ohne Tagesordnungspunkte): 1 Einträge") in out
    assert "organizations.json gelesen (Ersatz ohne gelöschte Gremien): 1 Einträge" in out
    assert "Kurzformat (meetings.json): 1 Sitzungen nur mit der Zahl der Tagesordnungspunkte" in out
    assert "  1–5: 1 (100,0 %)" in out
    _jsonl(raw / "organizations.jsonl", [{"id": f"{B}/o/1"}, {"id": f"{B}/o/2"}])
    out = _aufruf(fa, raw, capsys)
    assert "Dateien: organizations.jsonl gelesen: 2 Zeilen; organizations.teil.jsonl fehlt\n" in out
    assert "Gremien je Kennung: 2;" in out


def test_kategorien_nur_haeufig_kurz_und_unbedenklich(fa):
    """Werte erscheinen erst ab 5 Vorkommen, mit höchstens 80 Zeichen, aus der vorsichtigen Zeichenklasse und ohne
    Merkmale von Adressen, Dateinamen, Drucksachen oder Kennungen; mimeType nur als typ/untertyp."""
    for wert in ("Beschlussvorlage", "Antrag nach § 3 der Geschäftsordnung des Rates", "Mitteilung BV (Innenstadt)",
                 "Anfrage; Antwort: Verwaltung & Rat", "Kenntnis genommen, vertagt", "Änderungsantrag BV1/BV2"):
        assert fa.zeigbar(fa.normal(wert)), wert
    for wert in ("https://example.invalid/typ", "www.example.invalid", "vorlage.pdf", "Drucksache 1234/2026",
                 "AN/0123/2026 Antrag", "Kennung 123456", "a" * 81, "Antrag!", "Name@example.invalid", "„Zitat“",
                 "1234", "Tab\x00Zeichen", "Bür­gerantrag", "Café",
                 # Personen, Anschriften, Rufnummern (Prüfung feldf); bloße Namen ohne Anrede bleiben offen (TECHNIK.md)
                 "Musterweg 12, Köln-Ehrenfeld", "Tel. 0221-221-1234", "DE89 3704 0044 0532 0130 00",
                 "Anregung nach § 24 GO von Herrn Max Mustermann, Musterstr. 3", "Herr Müller", "frau Muster",
                 "Dr. Muster", "Prof Muster", "Musterstraße 3", "Musterstrasse 3", "Am Gürtel 7", "Musterplatz 1a",
                 "M&uuml;ller", "Anfrage &quot;Muster&quot;", "0221 221 12 34"):
        assert not fa.zeigbar(fa.normal(wert)), wert
    for wert in ("Antrag nach § 3 Abs. 1 Satz 2 GO", "Frauen und Gleichstellung", "Wegweiser 2",
                 "Bezirksvertretung 2 (Rodenkirchen)", "Beschluss & Rat; Verwaltung", "Anfrage nach § 4"):
        assert fa.zeigbar(fa.normal(wert)), wert
    assert fa.zeigbar("application/pdf", mime=True) and fa.zeigbar("application/vnd.ms-excel", mime=True)
    for wert in ("pdf", "vorlage.pdf", "x/pdf", "Application/PDF", "application/pdf; name=a.pdf", "text/"):
        assert not fa.zeigbar(wert, mime=True), wert
    k = fa.Kategorien()
    for wert, n in (("Vier", 4), ("Fünf", 5), ("  Fünf\n", 1), ("Lang " * 20, 9), ("Adresse www.x.de", 7)):
        for _ in range(n):
            k.add(wert)
    k.add(None)
    k.add(["Liste"])
    zeigen, werte, objekte = k.ergebnis()
    assert zeigen == [("Fünf", 6)] and (werte, objekte) == ("3", 20)
    assert (k.fehlt, k.keine_zeichenkette, k.gesamt()) == (1, 1, 28)
    viele = fa.Kategorien()
    for i in range(fa.MAX_ANGEZEIGT + 3):
        for _ in range(5):
            viele.add(f"Art {chr(65 + i % 26)}{chr(97 + i // 26)}")
    zeigen, werte, objekte = viele.ergebnis()
    assert len(zeigen) == fa.MAX_ANGEZEIGT and (werte, objekte) == ("3", 15)


def test_referenzklassen(fa):
    assert [fa.referenzklasse(x) for x in ("AN/0123/2026", "1234/2026", " 1234/2026 ", "AN/12/2026", "7/2025",
                                           "12345/2026", "AN/1234/26", "", None, 1234)] == [
        "AN/NNNN/JJJJ", "NNNN/JJJJ", "NNNN/JJJJ", "AN/N/JJJJ oder N/JJJJ mit 1 bis 3 Ziffern",
        "AN/N/JJJJ oder N/JJJJ mit 1 bis 3 Ziffern", "andere Form", "andere Form", "fehlt oder leer",
        "fehlt oder leer", "keine Zeichenkette"]
    assert [fa.jahr(x) for x in ("2026-11-16", "2026-11-16T23:10:00+01:00", "1899-01-01", "16.11.2026", None, 2026,
                                 " ")] == [2026, 2026, "außerhalb 1900–2100", "unlesbar", "fehlt", "unlesbar", "fehlt"]


MARKER = "zqmarker"


def test_keine_inhalte_in_der_ausgabe(fa, tmp_path, capsys, monkeypatch):
    """Eindeutige Marken in Titeln, Namen, Drucksachennummern, Dateinamen, Adressen, Kennungen, Personenfeldern,
    Werten der Ortsangaben, Freitext in Kategorien (einmalig, oder häufig, aber mit Adresse, Dateiname, Drucksache,
    unzulässigen Zeichen oder zu lang) und Meldungen im Zustand: keine erscheint im Log oder in der Zusammenfassung.
    Die Kategorien selbst werden gezählt (unter „sonstige“)."""
    m = MARKER
    raw = tmp_path / "raw"
    art_haeufig = [f"Art {m}@example.invalid", f"https://{m}.example.invalid/art", f"Drucksache {m} 4711/2026",
                   f"Art {m} " + "x" * 80, f"Art {m}!", f"Anlage {m}.pdf"]

    def vorlage(i, art):
        return {
            "id": f"https://{m}-id.example.invalid/papers/{i}", "name": f"Titel {m}titel Musterstraße 12",
            "reference": f"AN/9876/20{30 + i % 9}", "paperType": art, "date": "2026-11-16",
            "web": f"https://{m}web.example.invalid/{i}",
            "mainFile": {"id": f"https://{m}-file.example.invalid/{i}", "name": f"Datei {m}dateiname",
                         "fileName": f"{m}datei.pdf", "accessUrl": f"https://{m}access.example.invalid/a.pdf",
                         "mimeType": f"application/{m}{i}"},
            "auxiliaryFile": [{"fileName": f"{m}anlage.docx", "mimeType": f"{m.upper()}/xyz"},
                              f"https://{m}-anlage.example.invalid/{i}"],
            "originatorPerson": [{"id": f"https://{m}-person.example.invalid/1", "name": f"Erika {m}person",
                                  "familyName": f"{m}familie", "email": [f"{m}@example.invalid"]},
                                 f"https://{m}-personurl.example.invalid/p/1"],
            "originatorOrganization": [{"id": f"https://{m}-org.example.invalid/1", "name": f"Fraktion {m}"}],
            "underDirectionOf": [f"https://{m}amt.example.invalid/org/1"],
            "location": [{"id": f"https://{m}-loc.example.invalid/{i}", "description": f"{m}ort Beschreibung",
                          "streetAddress": f"{m}straße 7", "postalCode": "50999", "subLocality": f"{m}viertel",
                          "locality": f"{m}stadt", "room": f"{m}raum",
                          "geojson": {"type": "Feature", "properties": {"name": f"{m}geo"},
                                      "geometry": {"type": "Point", "coordinates": [6.9, 50.9]}}},
                         f"https://{m}-locurl.example.invalid/{i}"],
            "keyword": [f"{m}schlagwort"],
            "consultation": [{"id": f"https://{m}-c.example.invalid/{i}", "meeting": f"https://{m}-m.example.invalid",
                              "agendaItem": f"https://{m}-a.example.invalid", "role": f"{m}rolle"}],
            "relatedPaper": [f"https://{m}-rel.example.invalid/1"],
        }
    papers = [vorlage(0, f"Freitext {m} einmalig")]
    papers += [vorlage(1 + k * 10 + j, art) for k, art in enumerate(art_haeufig) for j in range(6)]
    _jsonl(raw / "papers.jsonl", papers[:20])
    _jsonl(raw / "papers.teil.jsonl", papers[20:] + [f'{{"id": "{m}-kaputt", "name": "{m}'])
    tops = [{"id": f"https://{m}-top.example.invalid/{i}", "name": f"TOP {m}topname", "number": f"{m}nr",
             "public": False, "resolutionText": f"{m}beschluss",
             "result": f"Beschluss {m} einmalig" if i == 0 else f"laut Anlage {m}anlage.pdf"} for i in range(6)]
    _jsonl(raw / "meetings_roh.jsonl", [{
        "id": f"https://{m}-meeting.example.invalid/1", "name": f"Sitzung {m}sitzungsname",
        "start": "2026-11-16T17:00:00+01:00", "location": {"description": f"{m}raum"},
        "organization": [f"https://{m}-org.example.invalid/1"], "agendaItem": tops}])
    _jsonl(raw / "organizations.jsonl", [
        {"id": f"https://{m}-org.example.invalid/{i}", "name": f"Ausschuss {m}ausschuss", "shortName": f"{m}kurz",
         "organizationType": f"Typ {m}!", "classification": f"{m}klasse einmalig {i}",
         "website": f"https://{m}website.example.invalid"} for i in range(6)])
    (raw / "zustand_abruf.json").write_text(json.dumps({
        "papers_fortsetzung": {"naechste": f"https://{m}.example.invalid/papers?page=3&token={m}token", "seiten": 2,
                               "start": "2026-11-15T22:10:00+00:00"},
        "letzter_abbruch": {"art": "http", "meldung": f"{m}meldung"}}), encoding="utf-8")
    zusammenfassung = tmp_path / "summary.md"
    out = _aufruf(fa, raw, capsys, zusammenfassung=zusammenfassung, monkeypatch=monkeypatch)
    md = zusammenfassung.read_text(encoding="utf-8")
    for text in (out, md):
        assert MARKER not in text.lower(), [z for z in text.splitlines() if MARKER in z.lower()]
        for geheim in ("9876", "50999", "Musterstraße", "example.invalid", "@", "Erika", ".pdf", "://"):
            assert geheim not in text, geheim
    # gezählt, aber nicht gezeigt
    assert "Vorlagen je Kennung: 37;" in out and "1 unlesbar" in out
    assert "  sonstige (7 Werte, 37 Objekte): 37 (100,0 %)" in out          # paperType
    assert "  sonstige (2 Werte, 6 Objekte): 6 (100,0 %)" in out            # result
    assert "  location mit subLocality = Stadtteil (geo.Ortsteile.by_name): 0 (0,0 %)" in out
    assert "  originatorPerson (nur: Liste nicht leer): 37 (100,0 %)" in out
    assert "Zwischenstand: Vollabruf läuft" in out


def test_garbage_endet_mit_0(tmp_path):
    """Unlesbare Dateien jeder Art, ein Verzeichnis statt einer Datei, unlesbare Stadtteile: Exit-Code 0, Ausgabe und
    Zusammenfassung trotzdem (wie im Lauf als eigener Prozess)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "papers.jsonl").write_bytes(b"\xff\xfe\x00garbage\n{\"id\": 5}\n[]\n\"text\"\n{\"id\": \"\"}\n" * 3)
    (raw / "papers.teil.jsonl").mkdir()
    (raw / "meetings.json").write_text("{kaputt", encoding="utf-8")
    (raw / "organizations.json").write_text(json.dumps({"keine": "Liste"}), encoding="utf-8")
    (raw / "zustand_abruf.json").write_bytes(b"\xff\xfe")
    (tmp_path / "stadtteile.geojson").write_text("kein json", encoding="utf-8")
    _jsonl(raw / "meetings_roh.teil.jsonl", [{"id": "m1", "agendaItem": "keine Liste", "start": 2026},
                                            {"id": "m2", "agendaItem": [None, 3, {}], "cancelled": "ja"},
                                            {"id": "m3", "agendaItem": {"id": "a"}}])
    zusammenfassung = tmp_path / "summary.md"
    for weitere in ([], ["--unbekannt"], ["--frist", "keine Zahl"]):
        erg = subprocess.run([sys.executable, str(ROOT / "tools" / "feldabdeckung.py"), "--raw", str(raw),
                              "--stadtteile", str(tmp_path / "stadtteile.geojson"), *weitere],
                             capture_output=True, text=True, timeout=120,
                             env={**os.environ, "GITHUB_STEP_SUMMARY": str(zusammenfassung)})
        assert erg.returncode == 0, erg
    erg = subprocess.run([sys.executable, str(ROOT / "tools" / "feldabdeckung.py"), "--raw", str(raw),
                          "--stadtteile", str(tmp_path / "stadtteile.geojson")], capture_output=True, text=True,
                         timeout=120, env={**os.environ, "GITHUB_STEP_SUMMARY": str(zusammenfassung)})
    out = erg.stdout
    assert erg.returncode == 0 and "::warning::" not in out, erg
    assert "papers.jsonl gelesen: 15 Zeilen, davon 3 unlesbar und 12 ohne Kennung" in out
    assert "papers.teil.jsonl nicht weiter lesbar (IsADirectoryError)" in out
    assert "meetings.json fehlt" not in out and "Sitzungen je Kennung: 3;" in out
    assert "organizations.json nicht weiter lesbar (Ersatz ohne gelöschte Gremien) (ValueError)" in out
    assert "Stand: unbekannt (zustand_abruf.json unlesbar)" in out
    assert "Stadtteile für den Abgleich mit subLocality (data/geo): nicht lesbar (JSONDecodeError)" in out
    assert zusammenfassung.read_text(encoding="utf-8").count("### Feldabdeckung der Rohdaten") == 2


def test_unerwarteter_fehler_haelt_nicht_an(fa, tmp_path, capsys, monkeypatch):
    """Ein Objekt, das die Auswertung nicht versteht, wird gezählt und übersprungen; ein Fehler außerhalb der Objekte
    endet mit einer Warnung (nur der Name des Fehlers) und Exit-Code 0."""
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [_vorlage(1), _vorlage(2, date="kaputt"), _vorlage(3)])
    jahr = fa.jahr

    def kaputt(wert):
        if wert == "kaputt":
            raise TypeError("zqgeheim")
        return jahr(wert)
    monkeypatch.setattr(fa, "jahr", kaputt)
    out = _aufruf(fa, raw, capsys)
    assert "Nicht auswertbar (unerwartete Form, nicht mitgezählt): 1 (TypeError)" in out and "zqgeheim" not in out
    assert "Vorlagen je Kennung: 2;" in out
    monkeypatch.setattr(fa, "bloecke", lambda a: 1 / 0)
    out = _aufruf(fa, raw, capsys)
    assert out == "::warning::Feldabdeckung nicht ermittelt (ZeroDivisionError)\n"


def test_ueberlange_zeile_und_zeitgrenze(fa, tmp_path, capsys, monkeypatch):
    """Eine überlange Zeile gilt als unlesbar, die folgenden werden gelesen; nach der Frist endet das Lesen mit dem
    Vermerk „unvollständig“, ohne Fehler."""
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [_vorlage(1), {"id": "lang", "name": "x" * 500}, _vorlage(3)])
    monkeypatch.setattr(fa, "ZEILE_HOECHSTENS", 200)
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    assert a["listen"]["papers"]["auswertung"].n == 2
    assert a["listen"]["papers"]["dateien"]["papers.jsonl"] == "gelesen: 3 Zeilen, davon 1 unlesbar und 0 ohne Kennung"
    out = _aufruf(fa, raw, capsys, "--frist", "-1")
    # nur die Liste, die gelesen wurde; im ersten Durchgang keine Zahlen statt „0“ (Prüfung feldf)
    assert out.count("Nicht ausgewertet: Zeitgrenze im ersten Durchgang (Kennungen) erreicht") == 1
    assert "Vorlagen je Kennung" not in out and "Unvollständig" not in out and "meetings_roh.jsonl fehlt" in out
    assert "Dateien: papers.jsonl bis zur Zeitgrenze gelesen: 0 Zeilen;" in out


class _Uhr:
    """Uhr für die Frist: steht still, bis ein Test sie stellt."""
    def __init__(self):
        self.jetzt = 0.0

    def monotonic(self):
        return self.jetzt


def _uhr_springt(fa, monkeypatch, datei, durchgang, nach, auf):
    """Die Uhr springt auf `auf`, sobald im Durchgang `durchgang` (1 oder 2) der Datei `datei` das Element `nach`
    gelesen ist: wie eine Liste, die für ihren Anteil an der Frist zu lange braucht."""
    uhr, elemente, aufrufe = _Uhr(), fa._elemente, {}
    monkeypatch.setattr(fa, "time", uhr)

    def langsam(pfad, art):
        aufrufe[pfad.name] = aufrufe.get(pfad.name, 0) + 1
        for i, e in enumerate(elemente(pfad, art)):
            if pfad.name == datei and aufrufe[pfad.name] == durchgang and i == nach:
                uhr.jetzt = auf
            yield e
    monkeypatch.setattr(fa, "_elemente", langsam)


def test_zeitgrenze_je_liste_im_ersten_durchgang(fa, tmp_path, capsys, monkeypatch):
    """Braucht die Liste der Vorlagen im ersten Durchgang länger als ihr Anteil an der Frist (ANTEIL_FRIST), erscheint
    sie als „nicht ausgewertet“ ohne irreführende Zahlen; Sitzungen und Gremien bekommen ihren Anteil am Rest und
    werden ausgewertet (Prüfung feldf)."""
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [_vorlage(i) for i in range(2000)])
    _jsonl(raw / "meetings_roh.jsonl", [{"id": f"{B}/m/{i}", "start": "2026-01-01T10:00:00+01:00"} for i in range(3)])
    _jsonl(raw / "organizations.jsonl", [{"id": f"{B}/o/{i}", "organizationType": "Gremium"} for i in range(5)])
    assert fa.ANTEIL_FRIST["papers"] < 1
    frist = 100
    _uhr_springt(fa, monkeypatch, "papers.jsonl", 1, 300, frist * fa.ANTEIL_FRIST["papers"] + 1)
    out = _aufruf(fa, raw, capsys, "--frist", str(frist))
    vorlagen, rest = out.split("== Sitzungen")
    assert "Dateien: papers.jsonl bis zur Zeitgrenze gelesen: 512 Zeilen;" in vorlagen
    assert ("Nicht ausgewertet: Zeitgrenze im ersten Durchgang (Kennungen) erreicht; zu dieser Liste keine "
            "Zahlen") in vorlagen
    assert "Vorlagen je Kennung" not in vorlagen and "Unvollständig" not in vorlagen
    assert "Sitzungen je Kennung: 3;" in rest and "Gremien je Kennung: 5;" in rest
    assert "Zeitgrenze" not in rest and "„Gremium“: 5 (100,0 %)" in rest


def test_zeitgrenze_im_zweiten_durchgang(fa, tmp_path, capsys, monkeypatch):
    """Endet die Frist erst im zweiten Durchgang, umfassen die Zahlen die bis dahin ausgewerteten Kennungen, mit
    deren Anzahl; die Dateien sind ganz gelesen (erster Durchgang)."""
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [_vorlage(i) for i in range(2000)])
    _uhr_springt(fa, monkeypatch, "papers.jsonl", 2, 300, 1000)
    out = _aufruf(fa, raw, capsys, "--frist", "100")
    assert "Dateien: papers.jsonl gelesen: 2.000 Zeilen;" in out
    assert ("Unvollständig: Zeitgrenze im zweiten Durchgang erreicht; die Zahlen umfassen nur die bis dahin "
            "ausgewerteten 512 von 2.000 Kennungen") in out
    assert "Vorlagen je Kennung: 512;" in out
    # danach ist die Frist für alle aufgebraucht: die folgenden Listen haben keine Dateien und bleiben ohne Vermerk
    assert out.count("Zeitgrenze") == 1


def test_beratungen_mit_organization_aus_der_sitzung_getrennt(fa, tmp_path, capsys):
    """Gremien, die der Abruf selbst aus der Sitzung in die Beratung schreibt (sessionnet.beratungen,
    `_organization_quelle`), zählen nicht als organization aus den Rohdaten der Stadt, sondern getrennt (Prüfung
    feldf)."""
    raw = tmp_path / "raw"
    _jsonl(raw / "papers.jsonl", [
        _vorlage(1, consultation=[{"id": f"{B}/c/1", "meeting": f"{B}/m/1", "organization": [f"{B}/o/1"]},
                                  {"id": f"{B}/c/2", "meeting": f"{B}/m/1", "organization": [f"{B}/o/2"],
                                   "_organization_quelle": "sitzung"}]),
        _vorlage(2, consultation=[{"id": f"{B}/c/3", "meeting": f"{B}/m/2", "organization": [f"{B}/o/2"],
                                   "_organization_quelle": "sitzung"}])])
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    w = a["listen"]["papers"]["auswertung"]
    assert (w.beratung["objekt"], w.beratung["meeting"], w.beratung["organization"],
            w.beratung["organization_ergaenzt"]) == (3, 3, 1, 2)
    out = _aufruf(fa, raw, capsys)
    assert ("mit organization aus den Rohdaten der Stadt 1; organization vom Abruf aus der Sitzung ergänzt, nicht "
            "mitgezählt: 2)") in out
    assert "sitzung" not in out


def test_beratungen_wie_der_abruf_sie_ergaenzt(oparl, monkeypatch, capsys):
    """Mit dem Abruf gegen den lokalen Testserver: Beratungen ohne organization, die sessionnet.beratungen aus der
    Sitzung ergänzt und in papers.jsonl schreibt, zählen getrennt."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    fa = _modul()
    sessionnet.fetch_all()
    ergaenzt = sum(1 for z in config.PAPERS.read_text(encoding="utf-8").splitlines() if z.strip()
                   for c in json.loads(z).get("consultation") or []
                   if isinstance(c, dict) and c.get("_organization_quelle"))
    assert ergaenzt >= 1   # der Testserver liefert mindestens eine Beratung ohne organization (test_sessionnet)
    assert fa.main([]) == 0
    out = capsys.readouterr().out
    assert f"organization vom Abruf aus der Sitzung ergänzt, nicht mitgezählt: {ergaenzt})" in out


def test_laufzeit_einige_tausend_vorlagen(fa, tmp_path):
    """Einige tausend Vorlagen und Sitzungen (fertige Datei und Teildatei mit Überschneidung) in wenigen Sekunden."""
    raw = tmp_path / "raw"
    beratung = [{"id": f"{B}/c/{k}", "meeting": f"{B}/m/{k}", "agendaItem": f"{B}/a/{k}",
                 "organization": [f"{B}/o/1"]} for k in range(3)]
    ort = [{"id": f"{B}/l/1", "subLocality": "Ehrenfeld"}]
    datei = {"id": f"{B}/f/1", "mimeType": "application/pdf", "name": "y" * 200}
    papers = [_vorlage(i, paperType=f"Art {i % 7}", consultation=beratung, location=ort if i % 3 else [],
                       mainFile=datei, auxiliaryFile=[datei] * (i % 4), name="z" * 300) for i in range(6000)]
    _jsonl(raw / "papers.jsonl", papers[:4000])
    _jsonl(raw / "papers.teil.jsonl", papers[3000:])
    tops = [{"id": f"{B}/a/{k}", "public": True, "result": "ungeändert beschlossen", "name": "t" * 200}
            for k in range(15)]
    _jsonl(raw / "meetings_roh.jsonl", [{"id": f"{B}/m/{i}", "start": "2026-01-01T10:00:00+01:00",
                                         "agendaItem": tops} for i in range(1500)])
    beginn = time.monotonic()
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    dauer = time.monotonic() - beginn
    p = a["listen"]["papers"]
    assert (p["auswertung"].n, p["ersetzt"], p["unvollstaendig"]) == (6000, 1000, False)
    assert p["auswertung"].feld["stadtteil"] == 4000
    assert a["listen"]["meetings"]["auswertung"].top["insgesamt"] == 22500
    assert dauer < 30, dauer
    assert fa.text(fa.bloecke(a)) and fa.markdown(fa.bloecke(a)).startswith("### Feldabdeckung der Rohdaten")


def test_mit_dem_abruf_gegen_den_testserver(oparl, monkeypatch, capsys):
    """Dateien, wie der Abruf sie schreibt (lokaler Testserver, erfundene Objekte): Ein Vollabruf bricht auf Seite 3
    der Vorlagen ab (Teildatei papers.teil.jsonl, Fortsetzung im Zustand): Zwischenstand mit den bisher gelesenen
    Vorlagen, Gremien aus organizations.jsonl, noch keine Sitzungen. Nach dem vollständigen Lauf alle Vorlagen,
    Sitzungen aus meetings_roh.jsonl mit eingebetteten Tagesordnungspunkten; keine Titel, Kennungen oder Namen."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    fa = _modul()
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: pfad == "/papers" and q.get("page") == "3")
    sessionnet.fetch_all()
    assert sessionnet._teil(config.PAPERS).exists() and not config.PAPERS.exists()
    assert fa.main([]) == 0
    out = capsys.readouterr().out
    inhalte = ([p["name"] for p in oparl.papers] + [p["reference"] for p in oparl.papers] + [o["name"] for o in oparl.orgs]
               + [oparl.meetings[0]["name"], "Testkörperschaft", oparl.b, "Neuehrenfeld"])
    assert not any(x in out for x in inhalte), out
    assert "Dateien: papers.jsonl fehlt; papers.teil.jsonl gelesen: 4 Zeilen" in out
    assert ("Stand: Zwischenstand: Vollabruf läuft (Fortsetzung steht aus); gezählt die im laufenden Vollabruf "
            "bisher gelesenen Objekte") in out
    assert "Vorlagen je Kennung: 4;" in out and "Gremien je Kennung: 2;" in out
    assert "Dateien: meetings_roh.jsonl fehlt; meetings_roh.teil.jsonl fehlt" in out
    monkeypatch.setattr(oparl, "stoerung", lambda pfad, q: False)
    sessionnet.fetch_all()
    assert not sessionnet._teil(config.PAPERS).exists()
    assert fa.main([]) == 0
    out = capsys.readouterr().out
    assert not any(x in out for x in inhalte), out
    assert "Dateien: papers.jsonl gelesen: 5 Zeilen; papers.teil.jsonl fehlt" in out
    assert "Stand: kein laufender Vollabruf (Liste zuletzt vollständig aktualisiert im Lauf ab " in out
    assert "Vorlagen je Kennung: 5;" in out and "Sitzungen je Kennung: 1;" in out
    assert "  location mit subLocality = Stadtteil (geo.Ortsteile.by_name): 1 (20,0 %)" in out
    assert "  consultation mit Verweis auf agendaItem (mindestens eine): 5 (100,0 %)" in out
    assert "Tagesordnungspunkte (agendaItem-Einträge): 5; eingebettet 5" in out
    assert "  result vorhanden: 5 (100,0 %)" in out


# --- Aussetzen (90-%-Regel, sessionnet.AUSSETZEN) und Dokumentschritt im Stapel --------------------------------------

def _ausgesetzt_roh(raw, eintrag, fortsetzung=True, liste="papers"):
    """Letzter gültiger Stand (3 Vorlagen), stehen gebliebene Teildatei (2, davon eine jüngere Fassung) und Zustand mit
    dem Eintrag `<liste>_ausgesetzt` (und der Fortsetzung, die beim Aussetzen stehen bleibt)."""
    _jsonl(raw / "papers.jsonl", [_vorlage(1), _vorlage(2), _vorlage(3)])
    _jsonl(sessionnet._teil(raw / "papers.jsonl"), [_vorlage(1, underDirectionOf=[f"{B}/organizations/amt"]),
                                                    _vorlage(4)])
    zustand = {"papers": "2026-11-12T22:20:00+00:00", f"{liste}_ausgesetzt": eintrag}
    if fortsetzung:
        zustand["papers_fortsetzung"] = {"naechste": f"{B}/papers?page=2", "seiten": 1,
                                         "start": "2026-11-14T22:10:00+00:00"}
    (raw / "zustand_abruf.json").write_text(json.dumps(zustand), encoding="utf-8")


def _nur_teil_absatz(teil, n):
    """Anfang des Absatzes zu den Kennungen nur aus der stehen gebliebenen Teildatei einer ausgesetzten Liste mit
    Fortsetzung: nur die Seiten bis zur letzten Unterbrechung, also eine Untergrenze (Prüfung hf)."""
    return (f"Kennungen nur aus der stehen gebliebenen Teildatei des abgelehnten Vollabrufs ({teil}; nur die Seiten bis "
            "zur letzten Unterbrechung, was er danach las, ist nicht gespeichert, also eine Untergrenze; nicht gezählt, "
            f"ohne Feldabdeckung): {n}; ")


@pytest.mark.parametrize("eintrag, erwartet", [
    ({"seit": "2026-11-15T22:15:00+00:00", "objekte": 8, "bisher": 10, "anlass": "fortgesetzter Vollabruf",
      "vollabruf_seit_beginn": False, "meldung": "MELDUNG-MARKE papers.jsonl: nur 8 statt bisher 10"},
     "ausgesetzt seit 15.11.2026, 23:15 Uhr (fortgesetzter Vollabruf unter 90 % des Stands): der Abruf liest die "
     "Liste nur, wenn RATSATLAS_KUERZER_ANNEHMEN oder RATSATLAS_VOLLABRUF sie nennt"),
    ({"seit": "2026-11-15T22:15:00+00:00", "anlass": "vollständiges Lesen nach nicht angewandtem Zeitfilter"},
     "ausgesetzt seit 15.11.2026, 23:15 Uhr (vollständiges Lesen nach nicht angewandtem Zeitfilter unter 90 % des "
     "Stands)"),
    ({"seit": "gestern", "anlass": "ANLASS-MARKE frei erfunden"}, "ausgesetzt seit unbekannt (Anlass unbekannt)"),
    ({"seit": "0001-01-01T00:00:00+14:00", "anlass": "wiederholter Vollabruf"},
     "ausgesetzt seit unlesbar (wiederholter Vollabruf unter 90 % des Stands)"),
    ("EINTRAG-MARKE unlesbar", "ausgesetzt (Eintrag unlesbar; gilt im Abruf als ausgesetzt)"),
    ({}, "ausgesetzt seit unbekannt (Anlass unbekannt)"),
])
def test_ausgesetzte_liste_kein_zwischenstand(fa, tmp_path, capsys, eintrag, erwartet):
    """Eine ausgesetzte Liste (Eintrag `<liste>_ausgesetzt`, jeder Wert außer null wie sessionnet._ausgesetzt) hat
    Vorrang vor der Fortsetzung, die beim Aussetzen stehen bleibt: kein „Zwischenstand: Vollabruf läuft“, sondern
    „ausgesetzt“ wie in tools/abrufstand.py, nur mit Zeitpunkt und festem Anlass (nie `meldung`, kein freier Anlass).
    Gezählt wird wie veröffentlicht nur der letzte gültige Stand (Entscheidung 16.11.2026 (6); bis dahin zählte die
    stehen gebliebene Teildatei mit, hier 4 statt 3 Vorlagen); von der Teildatei steht nur die Zahl der Kennungen
    allein aus ihr da (Vorlage 4). Der Absatz zum fertigen Vollabruf („Nur aus der Teildatei“) entfällt, denn es läuft
    keiner."""
    raw = tmp_path / "raw"
    _ausgesetzt_roh(raw, eintrag)
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)
    r = a["listen"]["papers"]
    assert r["stand"].startswith(erwartet), r["stand"]
    assert r["stand"].endswith("gezählt wie veröffentlicht nur der letzte gültige Stand (papers.jsonl), nicht die "
                               "stehen gebliebene Teildatei des abgelehnten Vollabrufs (papers.teil.jsonl)"), r["stand"]
    assert r["ausgesetzt"] and not r["vollabruf_laeuft"]
    # die jüngere Fassung von Vorlage 1 (mit underDirectionOf) steht nur in der Teildatei und zählt nicht
    assert (r["auswertung"].n, r["ersetzt"], r["auswertung"].feld["underDirectionOf"]) == (3, 0, 0)
    assert r["nur_teil"] == {"kennungen": 1}
    out = _aufruf(fa, raw, capsys)
    assert f"Stand: {erwartet}" in out
    assert "Zwischenstand" not in out and "Vollabruf läuft" not in out and "Nur aus der Teildatei" not in out
    assert "MARKE" not in out and "nur 8 statt bisher 10" not in out
    assert "Vorlagen je Kennung: 3;" in out
    assert _nur_teil_absatz("papers.teil.jsonl", 1) + "Zeilen mit Löschvermerk übergangen" in out


def test_ausgesetzt_ohne_fortsetzung_und_andere_listen(fa, tmp_path):
    """Ohne Fortsetzung (etwa ein wiederholter Vollabruf in einer Nacht) ist eine übrig gebliebene Teildatei veraltet;
    bei ausgesetzter Liste zählt auch sie nicht (Entscheidung 16.11.2026 (6): wie veröffentlicht nur der letzte gültige
    Stand; bis dahin zählte sie mit, Prüfung stgf). Der Stand nennt sie als nicht gezählt, die Kennungen allein aus ihr
    stehen als eine Zahl da, ohne den Hinweis auf RATSATLAS_KUERZER_ANNEHMEN als Weg zu ihnen (ohne Fortsetzung liest
    der Abruf die Liste dann ab Seite 1). Ohne fertige Datei: gezählt nichts. Ein Eintrag null gilt nicht als
    Aussetzen (Zwischenstand wie bisher), Gremien setzen nie aus (nicht in sessionnet.AUSSETZEN), Sitzungen schon."""
    raw = tmp_path / "raw"
    eintrag = {"seit": "2026-11-15T22:15:00+00:00", "anlass": "wiederholter Vollabruf"}
    _ausgesetzt_roh(raw, eintrag, fortsetzung=False)
    r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    vorspann = ("ausgesetzt seit 15.11.2026, 23:15 Uhr (wiederholter Vollabruf unter 90 % des Stands): der Abruf liest "
                "die Liste nur, wenn RATSATLAS_KUERZER_ANNEHMEN oder RATSATLAS_VOLLABRUF sie nennt, sonst bleibt ihr "
                "letzter gültiger Stand (Abhilfe im Fortschritt des Abrufs); gezählt ")
    veraltet = (", nicht die veraltete Teildatei ohne Fortsetzung im Zustand (papers.teil.jsonl; der Abruf liest sie "
                "nicht mehr)")
    assert r["stand"] == vorspann + "wie veröffentlicht nur der letzte gültige Stand (papers.jsonl)" + veraltet, \
        r["stand"]
    assert (r["auswertung"].n, r["auswertung"].feld["underDirectionOf"], r["nur_teil"]) == (3, 0, {"kennungen": 1})
    text = "\n".join(fa.text(fa.bloecke(fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE))))
    assert ("Kennungen nur aus der veralteten Teildatei ohne Fortsetzung (papers.teil.jsonl; nicht gezählt, ohne "
            "Feldabdeckung): 1; Zeilen mit Löschvermerk übergangen. Der Abruf liest sie nicht mehr, auch nicht mit "
            "RATSATLAS_KUERZER_ANNEHMEN=papers (liest die Liste dann ab Seite 1)") in text
    assert "abgelehnten" not in text and "Zwischenstand" not in text
    # ohne fertige Datei: gezählt nichts, beide Kennungen der veralteten Teildatei nur als Zahl
    (raw / "papers.jsonl").unlink()
    r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    assert r["stand"] == vorspann + "nichts (papers.jsonl fehlt)" + veraltet, r["stand"]
    assert (r["auswertung"].n, r["kennungen"], r["nur_teil"]) == (0, 0, {"kennungen": 2})
    assert "mitgezählt" not in r["stand"]
    _ausgesetzt_roh(raw, None)
    r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    assert r["stand"].startswith("Zwischenstand: Vollabruf läuft") and r["vollabruf_laeuft"] and not r["ausgesetzt"]
    for liste, ausgesetzt in (("organizations", False), ("meetings", True)):
        _ausgesetzt_roh(raw, eintrag, liste=liste)
        a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]
        assert a["papers"]["stand"].startswith("Zwischenstand: Vollabruf läuft")
        assert a[liste]["ausgesetzt"] is ausgesetzt
        assert a[liste]["stand"].startswith("ausgesetzt seit") is ausgesetzt, a[liste]["stand"]
    assert a["meetings"]["stand"].endswith("gezählt nichts (meetings_roh.jsonl fehlt)")   # keine Sitzungen


# --- Ausgesetzte Liste wie veröffentlicht (Entscheidung 16.11.2026 (6)) ----------------------------------------------

AUSGESETZT = {"seit": "2026-11-15T22:15:00+00:00", "objekte": 8, "bisher": 10, "anlass": "fortgesetzter Vollabruf",
              "vollabruf_seit_beginn": False, "meldung": "erfundene Meldung"}
FORTSETZUNG = {"naechste": f"{B}/papers?page=3", "seiten": 2, "start": "2026-11-14T22:10:00+00:00"}
AMT = [f"{B}/organizations/amt"]


def _gezaehlt(auswertung):
    """Alle Zahlen einer Auswertung (Vorlagen, Sitzungen, Gremien) zum Vergleich; Kategorien mit ihren Zählern, ohne
    die Funktion für den Stadtteilabgleich."""
    out = {}
    for k, v in vars(auswertung).items():
        if callable(v):
            continue
        out[k] = vars(v) if hasattr(v, "zaehler") else v
    return out


def _letzter_gueltiger_stand(raw):
    """Vorlagen: Fassungen im letzten gültigen Stand (papers.jsonl) und in der Teildatei des abgelehnten Vollabrufs.
    In der Teildatei: eine jüngere Fassung von 1 mit Feldern, die es im letzten gültigen Stand nicht gibt; neue
    Vorlagen 7, 8 (zweimal) und 9 (dann gelöscht); Löschvermerke für 2 (im Stand) und 10 (nur hier); eine Fassung von
    3 ohne Löschvermerk (im Stand gelöscht)."""
    fertig = [_vorlage(1), _vorlage(2), _vorlage(2, underDirectionOf=AMT, paperType="Mitteilung"),
              {"id": f"{B}/papers/3", "deleted": True},
              _vorlage(5, location=[{"id": f"{B}/locations/5", "subLocality": "Ehrenfeld"}], date="2025-05-05")]
    teil = [_vorlage(1, underDirectionOf=AMT, mainFile={"id": f"{B}/files/1", "mimeType": "application/pdf"},
                     keyword=["erfunden"], date="2024-01-01"),
            _vorlage(7), _vorlage(8), _vorlage(8, paperType="Mitteilung"), {"id": f"{B}/papers/2", "deleted": True},
            {"id": f"{B}/papers/10", "deleted": True}, _vorlage(3), _vorlage(9),
            {"id": f"{B}/papers/9", "deleted": True}]
    _jsonl(raw / "papers.jsonl", fertig)
    _jsonl(sessionnet._teil(raw / "papers.jsonl"), teil)
    return fertig, teil


def _zustand(raw, **eintraege):
    (raw / "zustand_abruf.json").write_text(json.dumps({"papers": "2026-11-12T22:20:00+00:00", **eintraege}),
                                            encoding="utf-8")


def _nur_fertig(fa, tmp_path, fertig, name="papers.jsonl"):
    """Unabhängige Zählung des letzten gültigen Stands: dieselben Zeilen allein in einem eigenen Ordner, ohne
    Teildatei und ohne Zustand."""
    raw = tmp_path / "nur_fertig"
    _jsonl(raw / name, fertig)
    return fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)


def test_ausgesetzt_zaehlt_wie_veroeffentlicht(fa, tmp_path, capsys):
    """Ausgesetzte Liste mit Fortsetzung und Teildatei: Die Zahlen gleichen einer unabhängigen Zählung nur der fertigen
    Datei (dieselben Zeilen allein, und je Kennung einmal wie build._je_kennung_einmal); die jüngere Fassung von 1 in
    der Teildatei ändert keine Feldabdeckung. Die Kennungen nur aus der Teildatei (7, 8, 9; nicht 3, die es im Stand
    gelöscht gibt, und nicht 10, nur mit Löschvermerk) stehen als eine Zahl da, ohne Felder, mit dem Hinweis auf
    RATSATLAS_KUERZER_ANNEHMEN und RATSATLAS_VOLLABRUF."""
    raw = tmp_path / "raw"
    fertig, _ = _letzter_gueltiger_stand(raw)
    _zustand(raw, papers_fortsetzung=FORTSETZUNG, papers_ausgesetzt=AUSGESETZT)
    r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    erwartet = _nur_fertig(fa, tmp_path, fertig)["listen"]["papers"]
    assert _gezaehlt(r["auswertung"]) == _gezaehlt(erwartet["auswertung"])
    assert (r["kennungen"], r["ersetzt"]) == (erwartet["kennungen"], erwartet["ersetzt"]) == (4, 1)
    w = r["auswertung"]
    je_kennung = build._je_kennung_einmal(fertig)
    assert (w.n, w.geloescht) == (sum(not p.get("deleted") for p in je_kennung),
                                  sum(bool(p.get("deleted")) for p in je_kennung)) == (3, 1)
    assert (w.feld["underDirectionOf"], w.feld["mainFile"], w.feld["keyword"], w.feld["stadtteil"]) == (1, 0, 0, 1)
    assert w.jahre == {2026: 2, 2025: 1}
    assert r["nur_teil"] == {"kennungen": 3}
    out = _aufruf(fa, raw, capsys)
    vorlagen = out.split("== Vorlagen (papers) ==")[1].split("== Sitzungen")[0]
    assert "Dateien: papers.jsonl gelesen: 5 Zeilen; papers.teil.jsonl gelesen: 9 Zeilen" in vorlagen
    assert ("gezählt wie veröffentlicht nur der letzte gültige Stand (papers.jsonl), nicht die stehen gebliebene "
            "Teildatei des abgelehnten Vollabrufs (papers.teil.jsonl)\n") in vorlagen
    assert (_nur_teil_absatz("papers.teil.jsonl", 3) + "Zeilen mit Löschvermerk übergangen, sie ändern den "
            "gezählten Stand nicht. Den kürzeren Stand nimmt nur RATSATLAS_KUERZER_ANNEHMEN=papers an (liest die Liste "
            "zu Ende), sonst nach Prüfung ein neuer Vollabruf "
            "mit RATSATLAS_VOLLABRUF=papers (ab Seite 1); Abhilfe im Fortschritt des Abrufs\n") in vorlagen
    assert vorlagen.count("Kennungen nur aus") == 1   # eine Zahl, keine Tabelle dazu
    assert "Vorlagen je Kennung: 3; als gelöscht gemeldet (deleted, getrennt): 1" in vorlagen
    assert "Fassungen derselben Kennung (je Kennung einmal gezählt): 1 ersetzt" in vorlagen
    assert "Zwischenstand" not in out and "Nur aus der Teildatei:" not in out
    # bis auf die Absätze zum Stand und zur Teildatei dieselbe Ausgabe wie die unabhängige Zählung
    ohne = out.split("== Vorlagen (papers) ==")[1].split("Vorlagen je Kennung")[1].split("== Sitzungen")[0]
    allein = _aufruf(fa, tmp_path / "nur_fertig", capsys)
    assert ohne == allein.split("Vorlagen je Kennung")[1].split("== Sitzungen")[0]


def test_ausgesetzt_loeschvermerke_der_teildatei_aendern_nichts(fa, tmp_path):
    """Zeilen mit Löschvermerk in der Teildatei (für eine Vorlage des Stands, für eine nur aus der Teildatei und nach
    einer Fassung ohne Löschvermerk) ändern weder die gezählten Zahlen noch die Zahl der Kennungen allein aus der
    Teildatei: ohne sie dasselbe Ergebnis."""
    raw = tmp_path / "raw"
    _, teil = _letzter_gueltiger_stand(raw)
    _zustand(raw, papers_fortsetzung=FORTSETZUNG, papers_ausgesetzt=AUSGESETZT)
    mit = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    assert sum(bool(o.get("deleted")) for o in teil) == 3
    _jsonl(sessionnet._teil(raw / "papers.jsonl"), [o for o in teil if not o.get("deleted")])
    ohne = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    assert _gezaehlt(mit["auswertung"]) == _gezaehlt(ohne["auswertung"])
    assert (mit["kennungen"], mit["ersetzt"], mit["nur_teil"]) == (ohne["kennungen"], ohne["ersetzt"],
                                                                   ohne["nur_teil"]) == (4, 1, {"kennungen": 3})
    # nur Löschvermerke in der Teildatei: gezählt wie ohne Teildatei, keine Kennung allein aus ihr
    _jsonl(sessionnet._teil(raw / "papers.jsonl"), [o for o in teil if o.get("deleted")])
    nur = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    assert _gezaehlt(nur["auswertung"]) == _gezaehlt(mit["auswertung"]) and nur["nur_teil"] == {"kennungen": 0}


@pytest.mark.parametrize("fortsetzung", [None, FORTSETZUNG])
def test_ausgesetzt_ohne_teildatei(fa, tmp_path, capsys, fortsetzung):
    """Ausgesetzt ohne Teildatei (etwa ein wiederholter Vollabruf, dessen Objekte nirgends stehen; oder eine
    Fortsetzung ohne Teildatei): gezählt wie die fertige Datei allein, keine Zahl zur Teildatei, keine Erwähnung der
    Teildatei im Stand."""
    raw = tmp_path / "raw"
    fertig, _ = _letzter_gueltiger_stand(raw)
    sessionnet._teil(raw / "papers.jsonl").unlink()
    _zustand(raw, papers_ausgesetzt=dict(AUSGESETZT, anlass="wiederholter Vollabruf"),
             **({"papers_fortsetzung": fortsetzung} if fortsetzung else {}))
    r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
    erwartet = _nur_fertig(fa, tmp_path, fertig)["listen"]["papers"]
    assert _gezaehlt(r["auswertung"]) == _gezaehlt(erwartet["auswertung"])
    assert (r["kennungen"], r["ersetzt"], r["nur_teil"]) == (4, 1, None)
    assert r["stand"].endswith("; gezählt wie veröffentlicht nur der letzte gültige Stand (papers.jsonl)"), r["stand"]
    out = _aufruf(fa, raw, capsys)
    assert "Dateien: papers.jsonl gelesen: 5 Zeilen; papers.teil.jsonl fehlt" in out
    assert "Kennungen nur aus" not in out and "Teildatei" not in out.split("== Sitzungen")[0]
    assert "Vorlagen je Kennung: 3;" in out


def test_nicht_ausgesetzt_unveraendert_zwischenstand(fa, tmp_path, capsys):
    """Ohne Aussetzen (kein Eintrag oder null) bleibt alles wie bisher: Während eines laufenden Vollabruf zählen
    fertige Datei und Teildatei zusammen, je Kennung einmal wie build über beide (auch die jüngere Fassung von 1 und
    die Vorlage 3, die in der Teildatei ohne Löschvermerk steht), mit dem Absatz zum fertigen Vollabruf."""
    raw = tmp_path / "raw"
    fertig, teil = _letzter_gueltiger_stand(raw)
    for zustand in ({"papers_fortsetzung": FORTSETZUNG}, {"papers_fortsetzung": FORTSETZUNG, "papers_ausgesetzt": None}):
        _zustand(raw, **zustand)
        r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["papers"]
        w = r["auswertung"]
        je_kennung = build._je_kennung_einmal(fertig + teil)
        assert (w.n, w.geloescht) == (sum(not p.get("deleted") for p in je_kennung),
                                      sum(bool(p.get("deleted")) for p in je_kennung)) == (7, 1)
        assert (w.feld["underDirectionOf"], w.feld["mainFile"]) == (2, 1)
        # wie am Ende des Vollabrufs (voll=True): 1, 7, 8, 2 (gelöscht), 10 (gelöscht), 3, 9 (gelöscht)
        assert r["nur_teil"] == {"kennungen": 7, "geloescht": 3}
        assert not r["ausgesetzt"] and r["vollabruf_laeuft"]
        out = _aufruf(fa, raw, capsys)
        assert "Stand: Zwischenstand: Vollabruf läuft" in out and "Nur aus der Teildatei: 7 Kennungen" in out
        assert "Kennungen nur aus" not in out and "ausgesetzt" not in out


def test_ausgesetzte_sitzungen_wie_veroeffentlicht(fa, tmp_path, capsys):
    """Sitzungen (meetings_roh.jsonl, Teildatei meetings_roh.teil.jsonl) ebenso: gezählt wie die fertige Datei allein,
    die jüngere Fassung mit Tagesordnungspunkten aus der Teildatei zählt nicht, eine Sitzung nur aus ihr als Zahl."""
    raw = tmp_path / "raw"
    tops = [{"id": f"{B}/a/{k}", "public": True, "result": "ungeändert beschlossen"} for k in range(6)]
    fertig = [{"id": f"{B}/meetings/1", "start": "2026-10-01T17:00:00+02:00"},
              {"id": f"{B}/meetings/2", "start": "2026-10-02T17:00:00+02:00", "cancelled": True}]
    _jsonl(raw / "meetings_roh.jsonl", fertig)
    _jsonl(raw / "meetings_roh.teil.jsonl", [dict(fertig[0], agendaItem=tops),
                                             {"id": f"{B}/meetings/3", "start": "2026-11-01T17:00:00+01:00"}])
    (raw / "zustand_abruf.json").write_text(json.dumps({
        "meetings_fortsetzung": dict(FORTSETZUNG, naechste=f"{B}/meetings?page=3"),
        "meetings_ausgesetzt": dict(AUSGESETZT, anlass="fortgesetzter Vollabruf")}), encoding="utf-8")
    r = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)["listen"]["meetings"]
    erwartet = _nur_fertig(fa, tmp_path, fertig, "meetings_roh.jsonl")["listen"]["meetings"]
    assert _gezaehlt(r["auswertung"]) == _gezaehlt(erwartet["auswertung"])
    assert (r["auswertung"].n, r["auswertung"].top["insgesamt"], r["nur_teil"]) == (2, 0, {"kennungen": 1})
    out = _aufruf(fa, raw, capsys)
    assert _nur_teil_absatz("meetings_roh.teil.jsonl", 1) in out
    assert "RATSATLAS_KUERZER_ANNEHMEN=meetings an (liest die Liste zu Ende)" in out
    assert "Sitzungen je Kennung: 2;" in out and "ungeändert beschlossen" not in out


@pytest.mark.parametrize("nach, zeilen", [(0, "0"), (300, "512")])
def test_ausgesetzt_zeitgrenze_in_der_teildatei(fa, tmp_path, monkeypatch, nach, zeilen):
    """Endet die Frist beim Lesen der Teildatei einer ausgesetzten Liste, bleiben die Zahlen des letzten gültigen Stands
    (gleich der unabhängigen Zählung nur der fertigen Datei), und für die Teildatei steht „Zahl nicht ermittelt
    (Zeitgrenze)“: Sie wird erst nach dem zweiten Durchgang gelesen (Prüfung hf; vorher im ersten Durchgang, dann stand
    die ganze Liste als „nicht ausgewertet“ da, obwohl der veröffentlichte Stand schon vollständig erfasst war)."""
    raw = tmp_path / "raw"
    fertig, teil = _letzter_gueltiger_stand(raw)
    _jsonl(sessionnet._teil(raw / "papers.jsonl"), teil + [_vorlage(i) for i in range(100, 700)])
    _zustand(raw, papers_fortsetzung=FORTSETZUNG, papers_ausgesetzt=AUSGESETZT)
    erwartet = _nur_fertig(fa, tmp_path, fertig)["listen"]["papers"]
    _uhr_springt(fa, monkeypatch, "papers.teil.jsonl", 1, nach, 1000)
    reihenfolge, gelesen = [], fa._elemente

    def merken(pfad, art):
        reihenfolge.append(pfad.name)
        return gelesen(pfad, art)
    monkeypatch.setattr(fa, "_elemente", merken)
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE, 100)
    r = a["listen"]["papers"]
    # beide Durchgänge über den letzten gültigen Stand, erst dann die Teildatei
    assert reihenfolge == ["papers.jsonl", "papers.jsonl", "papers.teil.jsonl"]
    assert r["zeitgrenze"] is None and not r["unvollstaendig"]
    assert _gezaehlt(r["auswertung"]) == _gezaehlt(erwartet["auswertung"])
    assert (r["kennungen"], r["ersetzt"]) == (erwartet["kennungen"], erwartet["ersetzt"]) == (4, 1)
    assert r["nur_teil"] is None and r["nur_teil_zeitgrenze"]
    assert r["dateien"] == {"papers.jsonl": "gelesen: 5 Zeilen",
                            "papers.teil.jsonl": f"bis zur Zeitgrenze gelesen: {zeilen} Zeilen"}
    text = "\n".join(fa.text(fa.bloecke(a)))
    assert _nur_teil_absatz("papers.teil.jsonl", "Zahl nicht ermittelt (Zeitgrenze)") in text
    assert "Vorlagen je Kennung: 3; als gelöscht gemeldet (deleted, getrennt): 1" in text
    assert "Nicht ausgewertet" not in text and "Unvollständig" not in text


@pytest.mark.parametrize("durchgang", [1, 2])
def test_ausgesetzt_zeitgrenze_vor_der_teildatei(fa, tmp_path, monkeypatch, durchgang):
    """Endet die Frist schon im letzten gültigen Stand (erster Durchgang: nicht ausgewertet; zweiter: unvollständig),
    bleibt die Teildatei ungelesen, und ihre Zahl heißt „nicht ermittelt (Zeitgrenze)“ (Prüfung hf)."""
    raw = tmp_path / "raw"
    _letzter_gueltiger_stand(raw)
    _jsonl(raw / "papers.jsonl", [_vorlage(i) for i in range(600)])
    _zustand(raw, papers_fortsetzung=FORTSETZUNG, papers_ausgesetzt=AUSGESETZT)
    _uhr_springt(fa, monkeypatch, "papers.jsonl", durchgang, 300, 1000)
    a = fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE, 100)
    r = a["listen"]["papers"]
    assert r["zeitgrenze"] == ("erster Durchgang", "zweiter Durchgang")[durchgang - 1]
    assert r["nur_teil"] is None and r["nur_teil_zeitgrenze"]
    assert r["dateien"]["papers.teil.jsonl"] == "nicht gelesen (Zeitgrenze)"
    text = "\n".join(fa.text(fa.bloecke(a)))
    assert _nur_teil_absatz("papers.teil.jsonl", "Zahl nicht ermittelt (Zeitgrenze)") in text
    assert ("Nicht ausgewertet: Zeitgrenze im ersten Durchgang (Kennungen) erreicht" in text) is (durchgang == 1)
    assert ("Unvollständig: Zeitgrenze im zweiten Durchgang erreicht; die Zahlen umfassen nur die bis dahin "
            "ausgewerteten 512 von 600 Kennungen" in text) is (durchgang == 2)


@pytest.mark.parametrize("liste", sessionnet.AUSSETZEN)
def test_hinweis_wie_die_feste_abhilfe(fa, tmp_path, liste):
    """Der Hinweis zur Teildatei einer ausgesetzten Liste ist von Hand umschrieben (im Stil von tools/abrufstand.py),
    nicht aus sessionnet.ABHILFE_AUSGESETZT gebildet: Die Einstellungen und Angaben darin müssen auch in der festen
    Abhilfe des Abrufs stehen, damit er bei deren Änderung nicht unbemerkt abweicht (Prüfung hf)."""
    abhilfe = sessionnet.ABHILFE_AUSGESETZT.format(liste=liste)
    raw = tmp_path / "raw"
    datei = fa.LISTEN[liste][0]
    _jsonl(raw / datei, [{"id": f"{B}/{liste}/1", "start": "2026-10-01T17:00:00+02:00", "date": "2026-10-01"}])
    _jsonl(sessionnet._teil(raw / datei), [{"id": f"{B}/{liste}/2", "start": "2026-10-02T17:00:00+02:00",
                                            "date": "2026-10-02"}])
    for fortsetzung, angaben in ((True, [f"RATSATLAS_KUERZER_ANNEHMEN={liste}", f"RATSATLAS_VOLLABRUF={liste}",
                                         "liest die Liste zu Ende", "nach Prüfung", "ab Seite 1"]),
                                 (False, [f"RATSATLAS_KUERZER_ANNEHMEN={liste}"])):
        zustand = {f"{liste}_ausgesetzt": AUSGESETZT}
        if fortsetzung:
            zustand[f"{liste}_fortsetzung"] = FORTSETZUNG
        (raw / "zustand_abruf.json").write_text(json.dumps(zustand), encoding="utf-8")
        text = fa.text(fa.bloecke(fa.auswerten(raw, raw / "zustand_abruf.json", config.ORTSTEILE)))
        absatz = [z for z in text if z.startswith("Kennungen nur aus")]
        assert len(absatz) == 1 and absatz[0].split("): ")[1].startswith("1; "), absatz
        for angabe in angaben:
            assert angabe in absatz[0] and angabe in abhilfe, angabe


def test_dateien_des_dokumentschritts_nicht_gelesen(fa, tmp_path, capsys):
    """Was der Dokumentschritt schreibt (pipeline/dokumente.py: data/raw/dokumente_koepfe.jsonl, Eintrag `dokumente`
    im Zustand; in pages.yml nach diesem Schritt, im nächsten Lauf aus dem Zwischenspeicher da), ändert die Ausgabe
    nicht und erscheint nicht darin."""
    raw = tmp_path / "raw"
    _ausgesetzt_roh(raw, None, fortsetzung=False)
    vorher = _aufruf(fa, raw, capsys)
    _jsonl(raw / config.DOKUMENTE.name, [
        {"file": f"{B}/files/DATEI-MARKE", "paper": f"{B}/papers/1", "kennung": "KENNUNG-MARKE", "status": "ok"},
        "{kaputt DOK-MARKE"])
    zustand = json.loads((raw / "zustand_abruf.json").read_text(encoding="utf-8"))
    zustand["dokumente"] = {"nacht": "2026-11-15", "dateien": 7, "verdacht": {"naechte": 1, "art": "VERDACHT-MARKE"},
                            "papers_ausgesetzt": {"seit": "2026-11-15T22:15:00+00:00"}}
    (raw / "zustand_abruf.json").write_text(json.dumps(zustand), encoding="utf-8")
    nachher = _aufruf(fa, raw, capsys)
    ohne_dauer = [[z for z in t.splitlines() if not z.startswith("Dauer der Auswertung")] for t in (vorher, nachher)]
    assert ohne_dauer[0] == ohne_dauer[1]
    assert "MARKE" not in nachher and "dokumente" not in nachher


def test_aussetzen_mit_dem_abruf_gegen_den_testserver(oparl, monkeypatch, capsys):
    """Dateien und Zustand, wie der Abruf des Stapels sie beim Aussetzen schreibt (lokaler Testserver, erfundene
    Vorlagen, wie tests/test_aussetzen.py): Nacht 0 liest 10 Vorlagen; Nacht 1 (RATSATLAS_VOLLABRUF=papers) liest
    nur noch 8 angebotene, das Zeitfenster endet vor Seite 3 (Fortsetzung, Teildatei); Nacht 2 liest die Fortsetzung zu
    Ende, 8 von 10, die Vorlagen setzen aus (Fortsetzung und Teildatei bleiben). Die Feldabdeckung sagt „ausgesetzt“
    wie tools/abrufstand.py, nicht „Zwischenstand“, und zählt wie veröffentlicht nur den letzten gültigen Stand (10
    Vorlagen, wie build sie liest); die Teildatei hat keine Kennung, die es dort nicht gibt (0). Mit
    RATSATLAS_KUERZER_ANNEHMEN=papers endet das Aussetzen: 8 Vorlagen, kein Vollabruf läuft."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    fa = _modul()
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    sessionnet.fetch_all()
    oparl.papers = oparl.papers[:8]
    echt = abruf.get_json

    def fenster_vor_seite_3(url, pausen=None):
        if "/papers" in url and "page=3" in url:
            raise abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster")
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", fenster_vor_seite_3)
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    sessionnet.fetch_all()
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    monkeypatch.setattr(abruf, "get_json", echt)
    assert "papers_fortsetzung" in sessionnet._zustand() and sessionnet._teil(config.PAPERS).exists()
    sessionnet.fetch_all()
    zustand = sessionnet._zustand()
    assert zustand["papers_ausgesetzt"]["anlass"] == "fortgesetzter Vollabruf"
    assert "papers_fortsetzung" in zustand and sessionnet._teil(config.PAPERS).exists()
    capsys.readouterr()
    assert fa.main([]) == 0
    out = capsys.readouterr().out
    inhalte = ([p["name"] for p in oparl.papers] + [p["reference"] for p in oparl.papers] + [o["name"] for o in oparl.orgs]
               + [oparl.b, "Testkörperschaft", zustand["papers_ausgesetzt"]["meldung"], "unvollständige Antwort",
                  "nur 8 statt bisher 10"])
    assert not any(x in out for x in inhalte), out
    stand = next(z for z in out.splitlines() if z.startswith("Stand: ausgesetzt"))
    assert stand.endswith("(fortgesetzter Vollabruf unter 90 % des Stands): der Abruf liest die Liste nur, wenn "
                          "RATSATLAS_KUERZER_ANNEHMEN oder RATSATLAS_VOLLABRUF sie nennt, sonst bleibt ihr letzter "
                          "gültiger Stand (Abhilfe im Fortschritt des Abrufs); gezählt wie veröffentlicht nur der letzte "
                          "gültige Stand (papers.jsonl), nicht die stehen gebliebene Teildatei des abgelehnten "
                          "Vollabrufs (papers.teil.jsonl)")
    assert "Zwischenstand" not in out and "Nur aus der Teildatei" not in out
    assert "Dateien: papers.jsonl gelesen: 10 Zeilen; papers.teil.jsonl gelesen: 4 Zeilen" in out
    # die Teildatei hat nur die Seiten bis zur Unterbrechung in Nacht 1 (4 Vorlagen); was die Fortsetzung in Nacht 2
    # danach las (insgesamt 8), speichert das Aussetzen nicht: Die Zahl der Kennungen allein aus ihr ist eine
    # Untergrenze (Prüfung hf)
    assert zustand["papers_ausgesetzt"]["objekte"] == 8
    # dieselbe Zahl wie build (je Kennung einmal aus papers.jsonl)
    roh = [json.loads(z) for z in config.PAPERS.read_text(encoding="utf-8").splitlines() if z.strip()]
    assert len(build._je_kennung_einmal(roh)) == 10
    assert "Vorlagen je Kennung: 10;" in out
    assert (_nur_teil_absatz("papers.teil.jsonl", 0) + "Zeilen mit Löschvermerk übergangen, sie ändern den "
            "gezählten Stand nicht. Den kürzeren Stand nimmt nur RATSATLAS_KUERZER_ANNEHMEN=papers an (liest die Liste "
            "zu Ende), sonst nach Prüfung ein neuer Vollabruf "
            "mit RATSATLAS_VOLLABRUF=papers (ab Seite 1); Abhilfe im Fortschritt des Abrufs") in out
    # derselbe Zeitpunkt wie im Fortschritt des Abrufs (tools/abrufstand.py, Vorrang des Aussetzens dort ebenso)
    spec = importlib.util.spec_from_file_location("abrufstand", ROOT / "tools" / "abrufstand.py")
    abrufstand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(abrufstand)
    seit = abrufstand.wann(sessionnet._zeit(zustand["papers_ausgesetzt"]["seit"]))
    assert stand.startswith(f"Stand: ausgesetzt seit {seit} (")
    assert abrufstand.ausgesetzt_text(zustand["papers_ausgesetzt"]).startswith(f"ausgesetzt seit {seit} (")
    # RATSATLAS_KUERZER_ANNEHMEN=papers: Fortsetzung zu Ende gelesen, kürzerer Stand angenommen, Aussetzen beendet
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "papers")
    sessionnet.fetch_all()
    monkeypatch.delenv("RATSATLAS_KUERZER_ANNEHMEN")
    assert "papers_ausgesetzt" not in sessionnet._zustand() and not sessionnet._teil(config.PAPERS).exists()
    assert fa.main([]) == 0
    out = capsys.readouterr().out
    assert "Stand: kein laufender Vollabruf (Liste zuletzt vollständig aktualisiert im Lauf ab " in out
    assert "Dateien: papers.jsonl gelesen: 8 Zeilen; papers.teil.jsonl fehlt" in out
    assert "Vorlagen je Kennung: 8;" in out and "ausgesetzt" not in out
