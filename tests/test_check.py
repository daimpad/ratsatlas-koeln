"""Prüfung (pipeline/check.py) mit erfundenen Testdaten (tools/testdaten.py, darunter Anregungen nach § 24 GO NRW mit
Hausnummer im Titel) in den temporären Pfaden der Fixture `oparl`: Die Datenschutzprüfung untersucht den Kölner Export
(config.EXPORT / config.STADT), meldet fehlende Dateien und eingeschleuste Verstöße. Keine Anfragen an die Stadt."""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from pipeline import build, check, config, export, kontext

ROOT = Path(__file__).resolve().parents[1]
EINGABE = "Anregungen und Beschwerden"   # Vorlagenart der Eingaben in tools/testdaten.py


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def testdaten(oparl, monkeypatch):
    """300 erfundene Vorlagen in den umgelenkten Rohdaten; Hauskoordinaten aus data/geo wie im Aufbau (conftest.py
    lenkt sie sonst auf eine fehlende Datei)."""
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    _tool("testdaten").main()


def _aufbauen():
    build.build()
    export.export()
    return sqlite3.connect(config.DB)


def _eingaben(db):
    return {r[0] for r in db.execute("SELECT reference FROM paper WHERE paper_type = ?", (EINGABE,))}


def test_datenschutz_untersucht_koelner_export(testdaten):
    db = _aufbauen()
    base = config.EXPORT / config.STADT
    assert (base / "suche.json").exists() and not (config.EXPORT / "bonn").exists()
    eingaben = _eingaben(db)
    # Testdaten: Eingaben mit Straße und Hausnummer im Titel, die Hausnummer bestimmt höchstens den Straßenabschnitt
    assert eingaben and db.execute(
        "SELECT COUNT(*) FROM paper p JOIN paper_location pl ON pl.paper_id = p.id WHERE p.paper_type = ? "
        "AND pl.method = 'strasse+hausnummer'", (EINGABE,)).fetchone()[0] > 0
    erg = check.datenschutz(db)
    z = erg["untersucht"]
    assert erg["befunde"] == [] and erg["fehlend"] == []
    assert z["vorlagen"] == z["suche"] == z["gebietsdateien"] == 300
    assert z["ohne_hauskoordinate"] >= len(eingaben)
    assert z["titel_geschuetzt"] >= len(eingaben)
    assert z["geojson"] > 0
    # erlaubte Hauskoordinaten (Verwaltungsvorlagen, politische Anträge) werden gezählt, aber nicht beanstandet
    assert z["hauskoordinaten"] > 0 and z["geojson_hauskoordinaten"] > 0 and z["gebietsdateien_hauskoordinaten"] > 0


def test_check_besteht_mit_testdaten(testdaten, capsys):
    _aufbauen().close()
    kontext.write()
    check.check()
    out = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    assert f"{config.EXPORT / config.STADT}" in out and "Titel in suche.json untersucht: 300" in out
    assert "Stadtteile in den Geodaten: 86" in out and "Stadtbezirke in den Geodaten: 9" in out
    # Bonner Vergleichswerte und Bonner Zusatzthemen: ausgewiesen statt still übergangen
    assert "Bonner Werte gelten nicht" in out and "Pilot-Stadtteil: keiner" in out
    assert "Zusatzthema „besetzung“)\nabgeschaltet" in out


def test_eingeschleuster_punkt_auf_hausnummer(testdaten, monkeypatch, capsys):
    """Ein Fehler im Aufbau setzt Eingaben auf die Hauskoordinate: Datenbank, GeoJSON und Gebietsdateien melden ihn."""
    monkeypatch.setattr(build, "hausnummer_punkt_erlaubt", lambda *a: True)
    db = _aufbauen()
    verstoss = {r[0] for r in db.execute(
        "SELECT p.reference FROM paper p JOIN paper_location pl ON pl.paper_id = p.id JOIN location l "
        "ON l.id = pl.location_id WHERE p.paper_type = ? AND l.level = 'adresse'", (EINGABE,))}
    assert verstoss   # mindestens eine Eingabe liegt jetzt auf einer Hauskoordinate
    titel = [r[0] for r in db.execute("SELECT name FROM paper WHERE paper_type = ?", (EINGABE,))]
    erg = check.datenschutz(db)
    db.close()
    for wo in ("Datenbank", "vorlagen.geojson", "Gebietsdateien der Karte"):
        b = [x for x in erg["befunde"] if f"Hauskoordinate bei Vorlagen ohne Erlaubnis ({wo};" in x]
        assert len(b) == 1 and f": {len(verstoss)}, z. B. {sorted(verstoss)[0]}" in b[0], (wo, erg["befunde"])
    # Kontextdaten abgeschaltet: als abgeschaltet ausgewiesen, nicht als fehlend
    monkeypatch.setitem(config.ZUSATZTHEMEN, "kontext", False)
    with pytest.raises(SystemExit) as e:
        check.check()
    assert "Hauskoordinate bei Vorlagen ohne Erlaubnis" in str(e.value) and "nicht durchgeführt" not in str(e.value)
    out = capsys.readouterr().out
    assert "Zusatzthema „kontext“)\nabgeschaltet" in out
    # die Ausgabe nennt Drucksachen, keine Titel mit Hausnummer (Protokolle der Workflows sind öffentlich)
    assert all(r in out for r in sorted(verstoss)[:5]) and not any(t in out for t in titel)


def test_einwohneranfrage_und_beantwortung_ohne_hauskoordinate(testdaten):
    """Kölner Einwohneranfrage (natürliche Person) mit Straße und Hausnummer im Titel und ihre Beantwortung, die weder
    Art noch Wort einer Eingabe trägt (Generalprobe 09.11.2026: beide lagen auf der Hauskoordinate, die Prüfung bestand):
    keine Hauskoordinate, Hausnummer in den Titeln der Suche ausgeblendet, die Prüfung besteht."""
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    lage = next(iter(hnr[strasse]))
    nr = sorted(hnr[strasse][lage], key=lambda n: (len(n), n))[0]
    b = "https://example.invalid/oparl/papers"
    neu = [{"id": f"{b}/ew1", "reference": "AN/0901/2026", "paperType": "Einwohneranfrage nach § 39 Abs. 6",
            "name": f"[Testdaten] Zustand des Gehwegs vor {strasse} {nr}", "date": "2026-10-01",
            "subordinatedPaper": [f"{b}/ew2"], "consultation": []},
           {"id": f"{b}/ew2", "reference": "0902/2026", "paperType": "Beantwortung einer Anfrage",
            "name": f"[Testdaten] Gehweg vor {strasse} {nr}", "date": "2026-10-20",
            "superordinatedPaper": [f"{b}/ew1"], "consultation": []}]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.write("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in neu))
    db = _aufbauen()
    refs = ("AN/0901/2026", "0902/2026")
    ebenen = {r for r in db.execute(
        "SELECT p.reference, l.level FROM paper p JOIN paper_location pl ON pl.paper_id = p.id JOIN location l "
        "ON l.id = pl.location_id WHERE p.reference IN (?, ?)", refs)}
    assert {r for r, _ in ebenen} == set(refs), ebenen   # beide verortet (Straße), keine auf der Hauskoordinate
    assert all(lvl != "adresse" for _, lvl in ebenen), ebenen
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == []
    titel = {r[0]: r[1] for r in json.loads((config.EXPORT / config.STADT / "suche.json").read_text())["rows"]}
    assert all(f"{strasse} {nr}" not in titel[r] and "[Hausnummer ausgelassen]" in titel[r] for r in refs), titel


def test_maske_vierstellige_hausnummer():
    """Kölner Straßen haben vierstellige Hausnummern; die Maske ließ sie stehen (Generalprobe 09.11.2026)."""
    from pipeline import maske
    m = maske.Maske({"0001/2026"}, strassen=["Aachener Straße"])
    assert m("Lärm Aachener Straße 1175", "0001/2026") == "Lärm Aachener Straße [Hausnummer ausgelassen]"
    assert m("Zufahrt Militärringstraße 1000a", "0001/2026") == "Zufahrt Militärringstraße [Hausnummer ausgelassen]"
    assert m("Haus-Nr. 1234", "0001/2026") == "[Hausnummer ausgelassen]"
    assert m("Aachener Straße 12-14", "0001/2026") == "Aachener Straße [Hausnummer ausgelassen]"
    assert m("Lärm Aachener Straße 1175", "0002/2026") == "Lärm Aachener Straße 1175"   # nicht aus der Einwohnerschaft
    assert m.offen("Lärm Aachener Straße 1175", "0001/2026")
    assert not m.offen("Lärm Aachener Straße [Hausnummer ausgelassen]", "0001/2026")


def test_stichprobe_hausnummern_ohne_hausnummer_aus_eingaben(testdaten):
    """Die Stichprobe Hausnummern (data/export/hausnummern, also auf der Seite und im Datenpaket) trug den vollen Titel
    (Generalprobe 09.11.2026: Eingaben nach § 24 GO NRW mit Hausnummer). Der Export blendet die Hausnummer aus wie in
    der Suche; steht sie trotzdem dort, meldet die Prüfung es."""
    db = _aufbauen()
    ref, titel = next(r for r in db.execute("SELECT reference, name FROM paper WHERE paper_type = ? ORDER BY reference",
                                            (EINGABE,)) if any(c.isdigit() for c in r[1].split(":")[-1]))
    pfad = config.EXPORT / "hausnummern" / "stichprobe_hausnummern.tsv"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    kopf = "nr\tdrucksache\ttitel\tlink\tstrasse\tortsteile_ohne_hausnummer\tortsteil_der_hausnummer\twirkung\turteil\tanmerkung\n"
    pfad.write_text(kopf + f"1\t{ref}\t{titel}\t\tX\tA; B\tA\teindeutig\t\t\n", encoding="utf-8")
    befunde = check.datenschutz(db)["befunde"]
    assert len(befunde) == 1 and "Titeln aus Einwohnerschaft" in befunde[0] and befunde[0].endswith(f"z. B. {ref}")
    export.export_audits()
    zeile = pfad.read_text(encoding="utf-8").splitlines()[1].split("\t")
    assert zeile[1] == ref and "[Hausnummer ausgelassen]" in zeile[2] and zeile[2] != titel
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["untersucht"]["stichprobe_hausnummern"] == 1


def test_verstoss_nur_im_export(testdaten):
    """Exportdateien, die nach dem Aufbau verändert wurden: Punkt auf Hausnummer im GeoJSON, Titel mit Hausnummer in
    der Suche. Die Datenbank ist in Ordnung, gemeldet werden die Dateien."""
    db = _aufbauen()
    base = config.EXPORT / config.STADT
    titel = {r[0]: r[1] for r in db.execute("SELECT reference, name FROM paper WHERE paper_type = ?", (EINGABE,))}
    geo = json.loads((base / "vorlagen.geojson").read_text())
    ziel = next(f["properties"] for f in geo["features"] if f["properties"]["paper_type"] == EINGABE)
    ziel.update(method=check.PUNKT, location_source=config.QUELLE_ADRESSEN)
    (base / "vorlagen.geojson").write_text(json.dumps(geo, ensure_ascii=False))
    suche = json.loads((base / "suche.json").read_text())
    zeile = next(r for r in suche["rows"] if r[0] in titel and r[0] != ziel["reference"])
    zeile[1] = titel[zeile[0]]   # Originaltitel mit Hausnummer
    (base / "suche.json").write_text(json.dumps(suche, ensure_ascii=False))
    befunde = check.datenschutz(db)["befunde"]
    db.close()
    assert len(befunde) == 2, befunde
    assert "(vorlagen.geojson;" in befunde[0] and befunde[0].endswith(f": 1, z. B. {ziel['reference']}")
    assert "Titeln aus Einwohnerschaft" in befunde[1] and befunde[1].endswith(f": 1, z. B. {zeile[0]}")


def test_fehlende_dateien_werden_gemeldet(testdaten, monkeypatch, capsys):
    db = _aufbauen()
    base = config.EXPORT / config.STADT
    (base / "suche.json").unlink()
    erg = check.datenschutz(db)
    db.close()
    assert erg["fehlend"] == [f"Datenschutz: {base / 'suche.json'} fehlt (`python -m pipeline export`)"]
    assert "suche" not in erg["untersucht"] and erg["befunde"] == []
    # ohne `python -m pipeline kontext`: Kontextdaten (freigegeben) gelten als nicht durchgeführt
    with pytest.raises(SystemExit) as e:
        check.check()
    msg = str(e.value)
    assert "nicht durchgeführt (Datei fehlt)" in msg and "suche.json" in msg and kontext.OUT in msg
    assert "NICHT DURCHGEFÜHRT – Kontextdaten" in capsys.readouterr().out
    # ohne Datenbank: Abbruch statt leerer Prüfung
    monkeypatch.setattr(config, "DB", config.BUILD / "fehlt.sqlite")
    with pytest.raises(SystemExit, match="Datenbank .* fehlt"):
        check.check()
    assert not (config.BUILD / "fehlt.sqlite").exists()


def test_fremde_gebiete_werden_gemeldet(testdaten):
    db = _aufbauen()
    assert check.gebiete(db) == ([], [])
    db.execute("UPDATE location SET ortsteil = 'Teststadtteil' WHERE id = (SELECT MIN(id) FROM location "
               "WHERE ortsteil IS NOT NULL)")
    befunde, fehlend = check.gebiete(db)
    db.close()
    assert fehlend == [] and befunde == ["Gebiete: Orte mit Stadtteil außerhalb der Kölner Geodaten: Teststadtteil"]


def test_check_in_der_kartenvorschau(oparl, capsys):
    """Kartenvorschau ohne Ratsvorlagen (pages.yml): die Prüfung läuft durch und sagt, dass keine Vorlage zu prüfen
    war; ohne Vermerk „vorschau“ wäre eine leere Datenbank ein Befund."""
    _tool("vorschau").main()
    db = _aufbauen()
    kontext.write()
    check.check()
    out = capsys.readouterr().out
    assert "Kartenvorschau ohne Ratsvorlagen" in out and "Vorlagen in der Datenbank untersucht: 0" in out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    config.STAND.write_text(json.dumps({"abruf_ok": True}))
    befunde = check.datenschutz(db)["befunde"]
    db.close()
    assert befunde == ["Datenschutz: keine Vorlage in der Datenbank, aber keine Kartenvorschau (STAND.json) – die "
                       "Prüfung hätte keine Vorlage untersucht"]
