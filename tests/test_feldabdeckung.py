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

from pipeline import config, sessionnet

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
    out = _aufruf(fa, raw, capsys)
    assert "Stand: Zwischenstand: Vollabruf läuft (Fortsetzung steht aus)" in out
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
                 "1234", "Tab\x00Zeichen", "Bür­gerantrag", "Café"):
        assert not fa.zeigbar(fa.normal(wert)), wert
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
    assert out.count("Unvollständig: Zeitgrenze des Schritts erreicht") == 1   # nur die Liste, die gelesen wurde
    assert "Vorlagen je Kennung: 0;" in out and "meetings_roh.jsonl fehlt" in out
    assert "Dateien: papers.jsonl bis zur Zeitgrenze gelesen: 0 Zeilen;" in out


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
