"""Aufbau, Export und Prüfung mit unerwarteten Feldformen in den Rohdaten (Gegenprüfung der Generalprobe 09./10.11.2026,
nachgestellt mit tools/testdaten.py und eingefügten erfundenen Vorlagen in den temporären Pfaden der Fixture `oparl`):
listenwertige OParl-Felder als einzelnes Objekt oder null, `paperType` null, Vorlagen ohne Drucksachennummer. build
gleicht die Formen beim Einlesen an (data/raw bleibt unverändert) und lässt Vorlagen ohne `reference` aus (Zählung im
Log von build und in der Ausgabe von check). Keine Anfragen an die Stadt."""
import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from pipeline import build, check, config, export, kontext

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def testdaten(oparl, monkeypatch):
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "60"])
    _tool("testdaten").main()


def _vorlage(nr, **felder):
    """Erfundene Vorlage mit einer Beratung im Rat; `felder` ersetzt oder entfernt (Wert ...) Felder."""
    p = {"id": f"{B}/papers/form-{nr}", "reference": f"{9000 + nr}/2026", "name": f"[Testdaten] Feldform {nr}",
         "paperType": "Beschlussvorlage", "date": "2026-10-01", "web": "https://example.invalid/vorlage",
         "modified": "2026-10-01T10:00:00+02:00", "location": [],
         "consultation": [{"id": f"{B}/consultations/form-{nr}", "organization": [f"{B}/organizations/rat"],
                           "role": "Entscheidung", "authoritative": True}]}
    for k, v in felder.items():
        if v is ...:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def _einfuegen(*papers):
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for p in papers:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return config.PAPERS.read_bytes()


def _alles(capsys):
    """build, export, kontext und check wie in pages.yml; liefert (Datenbank, Ausgabe von build, Ausgabe von check)."""
    build.build()
    aus_build = capsys.readouterr().out
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    aus_check = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in aus_check
    return sqlite3.connect(config.DB), aus_build, aus_check


def test_einzelne_objekte_statt_listen(testdaten, capsys):
    """(a) Listenwertige Felder als einzelnes Objekt bzw. einzelne Adresse werden zur Liste mit diesem Element, auch
    `organization` in der Beratung; die Werte bleiben ganz (keine Zerlegung in Zeichen)."""
    rat = f"{B}/organizations/rat"
    vorher = _einfuegen(
        _vorlage(1, consultation={"id": f"{B}/consultations/form-1", "organization": rat, "role": "Entscheidung",
                                  "authoritative": True},
                 location={"id": f"{B}/locations/form-1", "subLocality": "Ehrenfeld"},
                 auxiliaryFile={"id": f"{B}/files/form-1", "name": "Anlage"}, keyword="Verkehr",
                 underDirectionOf=f"{B}/organizations/amt-66", originatorOrganization=rat,
                 originatorPerson=f"{B}/persons/1", subordinatedPaper=f"{B}/papers/form-2",
                 superordinatedPaper=f"{B}/papers/1", relatedPaper=f"{B}/papers/2"),
        _vorlage(2))
    db, aus_build, _ = _alles(capsys)
    assert config.PAPERS.read_bytes() == vorher   # data/raw bleibt unverändert
    pid = f"{B}/papers/form-1"
    assert db.execute("SELECT under_direction_of FROM paper WHERE id = ?", (pid,)).fetchone() == (
        f"{B}/organizations/amt-66",)
    assert db.execute("SELECT organization_id, role, authoritative FROM consultation WHERE paper_id = ?",
                      (pid,)).fetchall() == [(rat, "Entscheidung", 1)]
    assert db.execute("SELECT method, stage FROM paper_location WHERE paper_id = ? AND stage = 'A'",
                      (pid,)).fetchall() == [("oparl_sublocality", "A")]
    assert set(db.execute("SELECT parent_id, child_id FROM paper_relation WHERE ? IN (parent_id, child_id)",
                          (pid,))) == {(pid, f"{B}/papers/form-2"), (f"{B}/papers/1", pid)}
    assert db.execute("SELECT actor, organization_id, method FROM paper_originator WHERE paper_id = ?",
                      (pid,)).fetchall() == [("Rat", rat, "originatorOrganization")]
    assert "Feldformen angeglichen" in aus_build and "consultation 1" in aus_build


def test_eintraege_ohne_objekt_oder_kennung(testdaten, capsys):
    """(a) In `consultation` und `location` liest build Objekte mit Kennung; ein Eintrag, der nur eine Adresse oder ein
    Objekt ohne `id` ist, fällt heraus (gezählt im Log), die übrigen bleiben."""
    gut = {"id": f"{B}/consultations/form-13", "organization": [f"{B}/organizations/rat"], "role": "Beratung",
           "authoritative": False}
    _einfuegen(_vorlage(13, consultation=[f"{B}/consultations/nur-adresse", {"role": "Beratung"}, gut],
                        location=[f"{B}/locations/nur-adresse", {"id": f"{B}/locations/form-13",
                                                                  "subLocality": "Nippes"}]))
    db, aus_build, _ = _alles(capsys)
    pid = f"{B}/papers/form-13"
    assert db.execute("SELECT id FROM consultation WHERE paper_id = ?", (pid,)).fetchall() == [(gut["id"],)]
    assert db.execute("SELECT location_id FROM paper_location WHERE paper_id = ? AND stage = 'A'", (pid,)
                      ).fetchall() == [(f"{B}/locations/form-13",)]
    assert "consultation (Eintrag ohne Objekt oder Kennung) 2" in aus_build
    assert "location (Eintrag ohne Objekt oder Kennung) 1" in aus_build


def test_null_statt_liste(testdaten, capsys):
    """(a) null in listenwertigen Feldern gilt als leere Liste; die Vorlage bleibt mit ihren übrigen Angaben."""
    felder = ("consultation", "location", "auxiliaryFile", "keyword", "underDirectionOf", "originatorOrganization",
              "originatorPerson", "subordinatedPaper", "superordinatedPaper", "relatedPaper")
    _einfuegen(_vorlage(3, **{f: None for f in felder}),
               _vorlage(4, consultation=[{"id": f"{B}/consultations/form-4", "organization": None,
                                          "role": "Beratung", "authoritative": False}]))
    db, _, _ = _alles(capsys)
    assert db.execute("SELECT reference, under_direction_of FROM paper WHERE id = ?", (f"{B}/papers/form-3",)
                      ).fetchone() == ("9003/2026", None)
    assert db.execute("SELECT COUNT(*) FROM consultation WHERE paper_id = ?", (f"{B}/papers/form-3",)).fetchone() == (0,)
    assert db.execute("SELECT COUNT(*) FROM paper_relation WHERE ? IN (parent_id, child_id) OR parent_id IS NULL "
                      "OR child_id IS NULL", (f"{B}/papers/form-3",)).fetchone() == (0,)
    assert db.execute("SELECT COUNT(*) FROM paper_originator WHERE paper_id = ? AND method = 'originatorOrganization'",
                      (f"{B}/papers/form-3",)).fetchone() == (0,)
    assert db.execute("SELECT organization_id FROM consultation WHERE paper_id = ?", (f"{B}/papers/form-4",)
                      ).fetchall() == [(None,)]


def test_vorlagenart_null_wie_leer(testdaten, capsys):
    """(b) paperType null (oder fehlend): kein Abbruch in build und export (etwa im Prozess-Audit); Anzeige wie bei
    einer leeren Vorlagenart."""
    _einfuegen(_vorlage(5, paperType=None), _vorlage(6, paperType=""), _vorlage(7, paperType=...))
    db, _, _ = _alles(capsys)
    arten = dict(db.execute("SELECT reference, paper_type FROM paper WHERE reference IN (?, ?, ?)",
                            ("9005/2026", "9006/2026", "9007/2026")))
    assert arten == {"9005/2026": "", "9006/2026": "", "9007/2026": ""}
    with open(config.EXPORT / "audit_prozess.tsv", encoding="utf-8", newline="") as f:
        zeilen = [z for z in csv.reader(f, delimiter="\t") if z[0] in arten and z[1] == "initiierung"]
    # gleiche Zeile (Schritt, Bezeichnung, Status, Datum, Quelle) bis auf Drucksache und Quellobjekt
    assert sorted(z[0] for z in zeilen) == sorted(arten) and len({tuple(z[1:7]) for z in zeilen}) == 1
    assert zeilen[0][1:4] == ["initiierung", "", "belegt"]


def test_ohne_drucksachennummer_ausgelassen(testdaten, capsys):
    """(c) Vorlagen ohne `reference` (fehlend, null, leer) werden ausgelassen, gezählt im Log von build und in der
    Ausgabe von check; keine erfundene Drucksachennummer."""
    _einfuegen(_vorlage(8, reference=...), _vorlage(9, reference=None), _vorlage(10, reference=""),
               _vorlage(11, reference="  "), _vorlage(12))
    db, aus_build, aus_check = _alles(capsys)
    ids = {r[0] for r in db.execute("SELECT id FROM paper")}
    assert f"{B}/papers/form-12" in ids
    assert not {f"{B}/papers/form-{n}" for n in (8, 9, 10, 11)} & ids
    assert db.execute("SELECT COUNT(*) FROM paper WHERE reference IS NULL OR TRIM(reference) = ''").fetchone() == (0,)
    ausgelassen = [f"{B}/papers/form-{n}" for n in (8, 9, 10, 11)]
    assert db.execute("SELECT COUNT(*) FROM consultation WHERE paper_id IN (?, ?, ?, ?)", ausgelassen
                      ).fetchone() == (0,)   # auch keine Beratungen der ausgelassenen Vorlagen
    assert sorted(db.execute("SELECT id, reason FROM skipped_paper")) == [(i, "ohne Drucksachennummer")
                                                                          for i in sorted(ausgelassen)]
    assert "4 Vorlagen ohne Drucksachennummer ausgelassen" in aus_build
    assert "Vorlagen ohne Drucksachennummer (beim Aufbau ausgelassen): 4" in aus_check
    suche = json.loads((config.EXPORT / config.STADT / "suche.json").read_text())
    assert "Feldform 8" not in json.dumps(suche, ensure_ascii=False)


def test_check_nennt_null_ausgelassene(testdaten, capsys):
    _, aus_build, aus_check = _alles(capsys)
    assert "ohne Drucksachennummer" not in aus_build
    assert "Vorlagen ohne Drucksachennummer (beim Aufbau ausgelassen): 0" in aus_check
