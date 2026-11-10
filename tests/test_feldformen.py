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
    assert "ohne Drucksachennummer" not in aus_build and "unerwarteter Form" not in aus_build
    assert "Vorlagen ohne Drucksachennummer (beim Aufbau ausgelassen): 0" in aus_check
    assert "Vorlagen mit Drucksachennummer in unerwarteter Form (beim Aufbau ausgelassen): 0" in aus_check


# --- Nachbesserung Runde 18a: Datenschutz trotz ausgelassener Vorlagen, Vorlagenart in anderer Form, Adresslisten ---

EINGABE_ART = "Anregung nach § 24 GO NRW"
EINWOHNERANFRAGE = "Einwohneranfrage nach § 39 Abs. 6"
# Drucksachennummer einer ausgelassenen Vorlage: fehlend, null, leer, nur Leerraum, in unerwarteter Form
OHNE_REF = [..., None, "", "  ", 1234]


def _adresse():
    """Straße mit genau einer Lage und eine Hausnummer dort (Hauskoordinate eindeutig; wie in test_check)."""
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    lage = next(iter(hnr[strasse]))
    return strasse, sorted(hnr[strasse][lage], key=lambda n: (len(n), n))[0]


def _ebenen(db, pid):
    return {r[0] for r in db.execute("SELECT l.level FROM paper_location pl JOIN location l ON l.id = pl.location_id "
                                     "WHERE pl.paper_id = ?", (pid,))}


def _titel_suche():
    return {r[0]: r[1] for r in json.loads((config.EXPORT / config.STADT / "suche.json").read_text())["rows"]}


def test_ausgelassene_eingabe_sperrt_verbundene_hauskoordinate(testdaten, capsys):
    """Eine Eingabe oder Einwohneranfrage ohne Drucksachennummer wird ausgelassen, bleibt aber in der Datenschutzregel:
    Die mit ihr verbundene Verwaltungsvorlage (Straße und Hausnummer im Titel) bekommt keine Hauskoordinate, und die
    Hausnummer ist im Titel ausgeblendet; Aufbau (build) und Prüfung (check.erlaubnis) urteilen gleich. Die Beziehung
    steht einmal nur bei der ausgelassenen Vorlage (subordinatedPaper), einmal nur bei der verbundenen
    (superordinatedPaper). Gegenprobe: dieselbe Vorlage ohne Beziehung liegt auf der Hauskoordinate."""
    strasse, nr = _adresse()
    titel = f"[Testdaten] Stellungnahme der Verwaltung: Sitzbänke an der {strasse} {nr}"
    neu, faelle = [], {}
    kombinationen = [(a, r, s) for a in (EINGABE_ART, EINWOHNERANFRAGE) for r in OHNE_REF
                     for s in ("ausgelassene", "verbundene")]
    for i, (art, ref, seite) in enumerate(kombinationen):
        eid, mid = f"{B}/papers/eingabe-{i}", f"{B}/papers/form-{20 + i}"
        neu.append(_vorlage(100 + i, id=eid, reference=ref, paperType=art, name=f"[Testdaten] {art}",
                            consultation=[], **({"subordinatedPaper": [mid]} if seite == "ausgelassene" else {})))
        neu.append(_vorlage(20 + i, reference=f"{1200 + i}/2026", paperType="Mitteilung", name=titel,
                            **({"superordinatedPaper": [eid]} if seite == "verbundene" else {})))
        faelle[mid] = (art, ref, seite, eid, f"{1200 + i}/2026")
    kontrolle = f"{B}/papers/form-90"
    neu.append(_vorlage(90, reference="1290/2026", paperType="Mitteilung", name=titel))
    _einfuegen(*neu)
    db, aus_build, aus_check = _alles(capsys)
    assert _ebenen(db, kontrolle) == {"adresse"}, "Gegenprobe: ohne Beziehung auf der Hauskoordinate"
    je_id = check.erlaubnis(db)[0]
    titel_suche = _titel_suche()
    assert je_id[kontrolle] is True and titel_suche["1290/2026"] == titel
    for mid, (art, ref, seite, eid, drucksache) in faelle.items():
        fall = (art, ref, seite)
        assert db.execute("SELECT COUNT(*) FROM paper WHERE id = ?", (eid,)).fetchone() == (0,), fall
        assert _ebenen(db, mid) == {"strasse"}, fall   # Straße ja, Hauskoordinate nein
        assert je_id[mid] is False, fall
        assert f"{strasse} {nr}" not in titel_suche[drucksache], fall
        assert "[Hausnummer ausgelassen]" in titel_suche[drucksache], fall
        # die Beziehung steht in paper_relation (für check.erlaubnis); der Export zeigt sie nicht (Vorlage fehlt)
        assert db.execute("SELECT COUNT(*) FROM paper_relation WHERE parent_id = ? AND child_id = ?",
                          (eid, mid)).fetchone() == (1,), fall
    assert "16 Vorlagen ohne Drucksachennummer ausgelassen" in aus_build
    assert "4 Vorlagen mit Drucksachennummer in unerwarteter Form ausgelassen" in aus_build
    assert "Vorlagen ohne Drucksachennummer (beim Aufbau ausgelassen): 16" in aus_check
    assert "Vorlagen mit Drucksachennummer in unerwarteter Form (beim Aufbau ausgelassen): 4" in aus_check
    db.close()


def test_pruefung_meldet_hauskoordinate_neben_ausgelassener_vorlage(testdaten, monkeypatch, capsys):
    """Setzt ein Fehler im Aufbau die mit einer ausgelassenen Eingabe verbundene Vorlage doch auf die Hauskoordinate,
    meldet check es (Startmenge aus skipped_paper, Beziehungen aus paper_relation), je Seite der Beziehung."""
    strasse, nr = _adresse()
    titel = f"[Testdaten] Stellungnahme der Verwaltung: Sitzbänke an der {strasse} {nr}"
    _einfuegen(_vorlage(101, id=f"{B}/papers/eingabe-a", reference=None, paperType=EINGABE_ART, consultation=[],
                        subordinatedPaper=[f"{B}/papers/form-31"]),
               _vorlage(31, reference="1331/2026", paperType="Mitteilung", name=titel),
               _vorlage(102, id=f"{B}/papers/eingabe-b", reference="", paperType=EINGABE_ART, consultation=[]),
               _vorlage(32, reference="1332/2026", paperType="Mitteilung", name=titel,
                        superordinatedPaper=[f"{B}/papers/eingabe-b"]))
    # Fehler: ohne Verbundene (nur die Startmenge statt des Fixpunkts)
    monkeypatch.setattr(build, "sperrmenge", lambda start, beziehungen, drucksachen: dict.fromkeys(start, "start"))
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    assert _ebenen(db, f"{B}/papers/form-31") == _ebenen(db, f"{B}/papers/form-32") == {"adresse"}
    befunde = [b for b in check.datenschutz(db)["befunde"] if "(Datenbank;" in b]
    db.close()
    assert len(befunde) == 1 and ": 2, z. B. 1331/2026, 1332/2026" in befunde[0], befunde


def test_einwohner_kette_mit_ausgelassenen():
    """Volltext: Vorlagen, die mit einer ausgelassenen Vorlage verbunden sind (auch über mehrere Stufen), werden wie die
    Kette der Einwohnerschaft nicht aus dem Volltext verortet; die Beziehung kann auf jeder Seite stehen."""
    from pipeline import volltext
    papers = [{"id": "m1", "reference": "0001/2026", "paperType": "Mitteilung", "name": "x",
               "superordinatedPaper": ["a1"]},
              {"id": "m2", "reference": "0002/2026", "paperType": "Mitteilung", "name": "x"},
              {"id": "m3", "reference": "0003/2026", "paperType": "Mitteilung", "name": "x",
               "superordinatedPaper": ["m2"]},
              {"id": "m4", "reference": "0004/2026", "paperType": "Mitteilung", "name": "x"}]
    ausgelassen = [{"id": "a1", "subordinatedPaper": [], "superordinatedPaper": []},
                   {"id": "a2", "subordinatedPaper": ["m2"], "superordinatedPaper": []}]
    assert volltext.einwohner_kette(papers) == set()
    assert volltext.einwohner_kette(papers, ausgelassen) == {"m1", "m2", "m3"}


@pytest.mark.parametrize("art", [[EINGABE_ART], {"name": EINGABE_ART},
                                 {"id": f"{B}/paperTypes/39", "name": [EINWOHNERANFRAGE]}])
def test_vorlagenart_als_liste_oder_objekt(testdaten, capsys, art):
    """(b) Eine Vorlagenart, die keine Zeichenkette ist (Liste, Objekt), wird zu Text aus ihren Zeichenkettenteilen,
    damit die Regel für Eingaben greift: keine Hauskoordinate, Hausnummer im Titel ausgeblendet, gezählt im Log."""
    strasse, nr = _adresse()
    titel = f"[Testdaten] Sitzbänke an der {strasse} {nr}"
    _einfuegen(_vorlage(41, reference="AN/1251/2026", paperType=art, name=titel),
               _vorlage(42, reference="AN/1252/2026", paperType="Antrag nach § 3 der Geschäftsordnung", name=titel))
    db, aus_build, _ = _alles(capsys)
    pid = f"{B}/papers/form-41"
    typ = db.execute("SELECT paper_type FROM paper WHERE id = ?", (pid,)).fetchone()[0]
    assert (EINGABE_ART in typ or EINWOHNERANFRAGE in typ) and not set("[]{}\"") & set(typ), typ
    assert _ebenen(db, pid) == {"strasse"}
    assert _ebenen(db, f"{B}/papers/form-42") == {"adresse"}   # Gegenprobe: Antrag, Vorlagenart als Zeichenkette
    assert check.erlaubnis(db)[0][pid] is False
    db.close()
    t = _titel_suche()["AN/1251/2026"]
    assert f"{strasse} {nr}" not in t and "[Hausnummer ausgelassen]" in t
    assert "paperType (keine Zeichenkette) 1" in aus_build


def test_objekte_in_adresslisten(testdaten, capsys):
    """Listen von Adressen (Beziehungen, originator*, underDirectionOf, in Beratungen organization) mit eingebetteten
    Objekten: das Objekt zählt mit seiner `id`, Einträge ohne Kennung fallen heraus (gezählt); mainFile, das kein Objekt
    ist, gilt als fehlend (gezählt). Kein Abbruch in build, export und check."""
    rat, amt = f"{B}/organizations/rat", f"{B}/organizations/amt-66"
    _einfuegen(_vorlage(51, underDirectionOf=[{"id": amt, "name": "Amt 66"}], originatorOrganization={"id": rat},
                        subordinatedPaper=[{"id": f"{B}/papers/form-52"}, {"name": "ohne Kennung"}, 7, ""],
                        superordinatedPaper={"id": f"{B}/papers/1"}, relatedPaper=[{"id": f"{B}/papers/2"}],
                        originatorPerson=[{"id": f"{B}/persons/1"}],
                        mainFile=[{"id": f"{B}/files/51", "accessUrl": "https://example.invalid/51.pdf"}],
                        consultation=[{"id": f"{B}/consultations/form-51", "organization": {"id": rat},
                                       "role": "Entscheidung", "authoritative": True},
                                      {"id": f"{B}/consultations/form-51b", "organization": [{"id": rat}],
                                       "role": "Beratung", "authoritative": False}]),
               _vorlage(52, mainFile="https://example.invalid/52.pdf"))
    db, aus_build, _ = _alles(capsys)
    pid = f"{B}/papers/form-51"
    assert db.execute("SELECT under_direction_of, main_file_url FROM paper WHERE id = ?", (pid,)).fetchone() == (
        amt, None)
    assert db.execute("SELECT main_file_url FROM paper WHERE id = ?", (f"{B}/papers/form-52",)).fetchone() == (None,)
    assert db.execute("SELECT organization_id FROM consultation WHERE paper_id = ? ORDER BY position",
                      (pid,)).fetchall() == [(rat,), (rat,)]
    assert set(db.execute("SELECT parent_id, child_id FROM paper_relation WHERE ? IN (parent_id, child_id)",
                          (pid,))) == {(pid, f"{B}/papers/form-52"), (f"{B}/papers/1", pid)}
    assert db.execute("SELECT actor, organization_id FROM paper_originator WHERE paper_id = ?",
                      (pid,)).fetchall() == [("Rat", rat)]
    db.close()
    for teil in ("underDirectionOf (Objekt statt Adresse) 1", "subordinatedPaper (Objekt statt Adresse) 1",
                 "subordinatedPaper (Eintrag ohne Kennung) 3", "consultation/organization (Objekt statt Adresse) 2",
                 "mainFile (kein Objekt) 2"):
        assert teil in aus_build, teil
