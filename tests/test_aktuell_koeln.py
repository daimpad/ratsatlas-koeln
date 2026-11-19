"""„Aktuell in Köln“ in index.json (Entscheidung 19.11.2026 (1) (E), Teil der Pipeline): `export._aktuell` wählt aus dem,
was der Export schon hat, die kommenden Sitzungen (ohne vergangene und abgesagte, höchstens 6, nach Tag und Uhrzeit)
und die neu eingereichten Vorlagen (alle Arten, Datum bis zum Kölner Tag des Abrufs, höchstens 5, Titel maskiert wie in
Liste und Suche). Eine Karte fehlt, wenn ihre Liste ausgesetzt oder nicht aktualisiert ist oder der Abruf fehlschlug,
`aktuell` ganz, wenn beide fehlen, in der Kartenvorschau und ohne Vorlagen. `check` prüft Titel und Gremien darin wie in
suche.json. Alle Vorlagen und Sitzungen sind erfunden (lokaler Testserver oder direkte Aufrufe); keine Anfragen an die
Stadt."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from pipeline import build, check, config, export, sessionnet

ROOT = Path(__file__).resolve().parents[1]
EINGABE = "Anregungen und Beschwerden"
# Abruf der Vorlagen am 19.11.2026 um 23:30 Uhr UTC: in Köln schon der 20.11.2026 (process.local_day)
ABRUF, HEUTE = "2026-11-19T23:30:00+00:00", "2026-11-20"
TITEL_EINGABE = "[Testdaten] Anregung zum Gehweg vor der Venloer Straße 123"
# erfundene Sitzungen: Kennung → (Beginn laut Quelle, abgesagt, Organisation)
SITZUNGEN = {
    "k3": ("2026-11-24T16:00:00Z", False, "rat"),
    "alt": ("2026-11-19T16:00:00Z", False, "bv4"),      # 19.11., 17:00 Uhr: vor dem Kölner Tag des Abrufs
    "h1": ("2026-11-20T16:00:00Z", False, "bv4"),       # 20.11., 17:00 Uhr
    "h0": ("2026-11-19T23:00:00Z", False, "rat"),       # 20.11., 00:00 Uhr in Köln: ohne Uhrzeit
    "h2": ("2026-11-20T14:30:00Z", False, "rat"),       # 20.11., 15:30 Uhr
    "ab": ("2026-11-21T16:00:00Z", True, "rat"),        # abgesagt
    "k1": ("2026-11-22T16:00:00Z", False, "bv4"),
    "k2": ("2026-11-23T16:00:00Z", False, "rat"),
    "k4": ("2026-11-25T16:00:00Z", False, "rat"),       # siebte kommende Sitzung: über der Höchstzahl
}
ERWARTET_SITZUNGEN = [("h2", "2026-11-20", "15:30"), ("h1", "2026-11-20", "17:00"), ("h0", "2026-11-20", None),
                      ("k1", "2026-11-22", "17:00"), ("k2", "2026-11-23", "17:00"), ("k3", "2026-11-24", "17:00")]
# erfundene Vorlagen: Kennung → (Drucksache, Datum, Vorlagenart, Titel, weitere Felder)
VORLAGEN = {
    "n1": ("1101/2026", "2026-11-21", "Beschlussvorlage", "[Testdaten] Vorlage nach dem Tag des Abrufs", {}),
    "n2": ("1102/2026", "2026-11-20", "Beschlussvorlage", "[Testdaten] Spielplatz in Neuehrenfeld", {"ort": True}),
    "n4": ("1104/2026", "2026-11-18", "Mitteilung", "[Testdaten] Mitteilung ohne Ort", {}),
    "n3": ("AN/0103/2026", "2026-11-18", "Antrag nach § 3", "[Testdaten] Antrag in der Bezirksvertretung",
           {"bv4": True}),
    "e5": ("1105/2026", "2026-11-17", EINGABE, TITEL_EINGABE, {"sitzung": "kx"}),
    "n6": ("1106/2026", "2026-11-16", "Mitteilung", "[Testdaten] Zweite Mitteilung ohne Ort", {}),
    "n7": ("1107/2026", "2026-11-15", "Mitteilung", "[Testdaten] Sechste Vorlage bis zum Tag des Abrufs", {}),
}
ERWARTET_VORLAGEN = ["1102/2026", "AN/0103/2026", "1104/2026", "1105/2026", "1106/2026"]


def _einfuegen(oparl):
    b = oparl.b
    for k, (beginn, abgesagt, org) in SITZUNGEN.items():
        oparl.meetings.append({"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting",
                               "name": f"Testsitzung {k}", "start": beginn, "cancelled": abgesagt,
                               "web": f"https://example.invalid/sitzung/{k}",
                               "organization": [f"{b}/organizations/{org}"],
                               "modified": "2026-11-01T08:00:00+01:00"})
    # Sitzung ohne Organisation, in der die Eingabe beraten wird: Gremium aus dem Namen (maskiert wie der Name)
    oparl.meetings.append({"id": f"{b}/meetings/kx", "type": "https://schema.oparl.org/1.1/Meeting",
                           "name": "Ortstermin vor der Venloer Straße 123", "start": "2026-12-01T16:00:00Z",
                           "modified": "2026-11-01T08:00:00+01:00"})
    for k, (ref, datum, art, titel, f) in VORLAGEN.items():
        p = {**oparl.paper(1), "id": f"{b}/papers/{k}", "reference": ref, "date": datum, "paperType": art,
             "name": titel, "location": [], "consultation": []}
        if f.get("ort"):
            p["location"] = [{"id": f"{b}/locations/{k}", "subLocality": "Neuehrenfeld"}]
        if f.get("bv4"):
            p["consultation"] = [{"id": f"{b}/consultations/{k}", "meeting": f"{b}/meetings/k1",
                                  "role": "Entscheidung", "authoritative": True}]
        if f.get("sitzung"):
            p["consultation"] = [{"id": f"{b}/consultations/{k}", "meeting": f"{b}/meetings/{f['sitzung']}",
                                  "role": "Kenntnisnahme", "authoritative": False}]
        oparl.papers.append(p)


def _aufbau(stand_aendern=None):
    sessionnet.fetch_all()
    stand = json.loads(config.STAND.read_text())
    stand["papers"] = ABRUF
    if stand_aendern:
        stand_aendern(stand)
    config.STAND.write_text(json.dumps(stand))
    build.build()
    export.export()
    return json.loads((config.EXPORT / config.STADT / "index.json").read_text())


def test_aktuell_im_export(oparl):
    _einfuegen(oparl)
    index = _aufbau()
    a = index["aktuell"]
    assert set(a) == {"sitzungen", "vorlagen"}
    # kommende Sitzungen ab dem Kölner Tag des Abrufs: ohne vergangene und abgesagte, nach Tag und Uhrzeit, ohne Uhrzeit
    # hinter denen mit Uhrzeit am selben Tag, höchstens 6
    s = a["sitzungen"]
    assert [(x["source_object"].rsplit("/", 1)[1], x["date"], x["time"]) for x in s] == ERWARTET_SITZUNGEN
    assert all(set(x) == {"date", "time", "gremium", "web", "source_object"} for x in s)   # kein Name, keine Frist
    assert {x["gremium"] for x in s} == {"Rat", "Bezirksvertretung 4 (Ehrenfeld)"}
    assert s[0]["web"] == "https://example.invalid/sitzung/h2"
    # neu eingereicht: alle Arten bis zum Kölner Tag des Abrufs, neueste zuerst, bei gleichem Tag die Drucksache
    # absteigend, höchstens 5
    v = a["vorlagen"]
    assert [x["reference"] for x in v] == ERWARTET_VORLAGEN
    assert all(set(x) == {"reference", "date", "paper_type", "name", "area", "ort", "source_object"} for x in v)
    je = {x["reference"]: x for x in v}
    assert (je["1102/2026"]["area"], je["1102/2026"]["ort"]) == ("ortsteil:neuehrenfeld", "Neuehrenfeld")
    assert (je["AN/0103/2026"]["area"], je["AN/0103/2026"]["ort"]) == ("bezirk:ehrenfeld", "Stadtbezirk Ehrenfeld")
    assert (je["1104/2026"]["area"], je["1104/2026"]["ort"]) == ("ohne:2026", "stadtweit / ohne Ortsbezug")
    assert all(x["area"] and x["area"] != "gesamt" for x in v)
    assert je["1104/2026"]["paper_type"] == "Mitteilung" and je["1104/2026"]["source_object"].endswith("/papers/n4")
    # Titel wie in Suche und Liste maskiert: die Hausnummer der Eingabe steht nirgends in index.json
    suche = {r[0]: r[1] for r in json.loads((config.EXPORT / config.STADT / "suche.json").read_text())["rows"]}
    assert all(x["name"] == suche[x["reference"]] for x in v)
    assert "Venloer Straße 123" not in je["1105/2026"]["name"] and "[Hausnummer ausgelassen]" in je["1105/2026"]["name"]
    text = (config.EXPORT / config.STADT / "index.json").read_text()
    assert "Venloer Straße 123" not in text and "Testsitzung" not in text and "frist" not in text


def test_check_meldet_ungekuerzten_titel_und_gremium(oparl, capsys):
    """check prüft index.json „aktuell“: ohne Eingriff kein Befund und eine Zeile nur mit der Zahl; ein ungekürzter Titel
    oder ein ungekürztes Gremium aus dem Sitzungsnamen ist ein Befund unter der Drucksache, ohne den Text im Log."""
    _einfuegen(oparl)
    index = _aufbau()
    pfad = config.EXPORT / config.STADT / "index.json"
    db = sqlite3.connect(config.DB)
    capsys.readouterr()
    erg = check.datenschutz(db)
    out = capsys.readouterr().out
    assert erg["befunde"] == [] and erg["fehlend"] == [] and erg["untersucht"]["aktuell"] == 6 + 5
    assert "Titel und Gremien in index.json („Aktuell in Köln“) untersucht: 11\n" in out

    v = next(x for x in index["aktuell"]["vorlagen"] if x["reference"] == "1105/2026")
    v["name"] = TITEL_EINGABE
    pfad.write_text(json.dumps(index, ensure_ascii=False))
    erg = check.datenschutz(db)
    out = capsys.readouterr().out
    assert [b for b in erg["befunde"] if "Hausnummern in Titeln" in b and "1105/2026" in b], erg["befunde"]
    assert "Venloer Straße 123" not in out and "Venloer Straße 123" not in " ".join(erg["befunde"])

    # Gremium aus dem Namen einer Sitzung, in der die Eingabe beraten wird: export maskiert es wie den Namen
    v["name"] = "[Testdaten] Anregung zum Gehweg vor der Venloer Straße [Hausnummer ausgelassen]"
    index["aktuell"]["sitzungen"].append({"date": "2026-12-01", "time": "17:00",
                                          "gremium": "Ortstermin vor der Venloer Straße 123", "web": None,
                                          "source_object": f"{oparl.b}/meetings/kx"})
    pfad.write_text(json.dumps(index, ensure_ascii=False))
    erg = check.datenschutz(db)
    assert [b for b in erg["befunde"] if "Hausnummern in Titeln" in b and "1105/2026" in b], erg["befunde"]
    zeit = json.loads((config.EXPORT / config.STADT / "zeit.json").read_text())["meetings"]
    kx = next(x for x in zeit if x["source_object"].endswith("/meetings/kx"))
    assert "Venloer Straße 123" not in kx["gremium"]   # so steht es in den Daten (zeit.json), hier wieder eingesetzt
    index["aktuell"]["sitzungen"][-1]["gremium"] = kx["gremium"]
    pfad.write_text(json.dumps(index, ensure_ascii=False))
    assert check.datenschutz(db)["befunde"] == []
    db.close()


def _vorschau():
    spec = importlib.util.spec_from_file_location("vorschau", ROOT / "tools" / "vorschau.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_aktuell_fehlt_in_der_vorschau(oparl):
    _vorschau().main()
    build.build()
    export.export()
    index = json.loads((config.EXPORT / config.STADT / "index.json").read_text())
    assert index["meta"]["vorschau"] and "aktuell" not in index
    # check liest index.json auch hier und findet nichts zu prüfen
    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [] and erg["untersucht"]["aktuell"] == 0


def test_karte_fehlt_bei_ausgesetzter_liste_im_export(oparl):
    _einfuegen(oparl)
    a = _aufbau(lambda s: s.update(abruf_ausgesetzt={"meetings": {"seit": "2026-11-19T22:40:00+00:00"}}))["aktuell"]
    assert set(a) == {"vorlagen"}


# --- export._aktuell direkt -------------------------------------------------------------------------------------------

def _sitzung(k, tag, uhrzeit="17:00", abgesagt=False):
    return {"date": tag, "time": uhrzeit, "gremium": "Rat", "name": f"Testsitzung {k}", "cancelled": abgesagt,
            "state": None, "web": None, "invitation": None, "agenda_items": 0, "start": f"{tag}T{uhrzeit or '00:00'}",
            "end": None, "source_object": f"m/{k}"}


def _vorlage(k, tag):
    return {"reference": f"{k}/2026", "date": tag, "paper_type": "Mitteilung", "name": f"[Testdaten] Vorlage {k}",
            "source_object": f"p/{k}"}


CACHE = {"p/1": _vorlage("1", "2026-11-18"), "p/2": _vorlage("2", None)}
MEETINGS = [_sitzung("1", "2026-11-21")]
OK = "2026-11-10T22:40:00+00:00"


@pytest.mark.parametrize("stand, karten", [
    ({}, {"sitzungen", "vorlagen"}),
    ({"abruf_ausgesetzt": {"meetings": {"seit": OK}}}, {"vorlagen"}),
    ({"abruf_warnungen": {"meetings": {"zeit": OK, "meldung": "nicht aktualisiert"}}}, {"vorlagen"}),
    ({"abruf_ausgesetzt": {"papers": {"seit": OK}}}, {"sitzungen"}),
    ({"abruf_fehler": {"zeit": OK, "meldung": "abgebrochen"}}, None),
    # ein Fehler vor dem letzten vollständigen Abruf gilt nicht mehr (_abruf_fehler)
    ({"abruf_fehler": {"zeit": OK, "meldung": "abgebrochen"}, "abruf_ok": "2026-11-11T22:40:00+00:00"},
     {"sitzungen", "vorlagen"}),
    # eine Warnung der Gremienliste betrifft keine Karte
    ({"abruf_warnungen": {"organizations": {"zeit": OK, "meldung": "nicht aktualisiert"}}}, {"sitzungen", "vorlagen"}),
    ({"abruf_ausgesetzt": {"papers": {"seit": OK}, "meetings": {"seit": OK}}}, None),
    ({"vorschau": OK}, None),
])
def test_karte_fehlt_bei_ausgesetzter_oder_nicht_aktualisierter_liste(stand, karten):
    a = export._aktuell(CACHE, {"p/1": "ohne:2026"}, {"ohne:2026": export.ORT_OHNE}, MEETINGS, "2026-11-20", stand)
    assert (set(a) if a is not None else None) == karten


def test_ohne_daten_und_ohne_eintrag():
    heim, kurz = {"p/1": "ohne:2026"}, {"ohne:2026": export.ORT_OHNE}
    assert export._aktuell({}, {}, {}, MEETINGS, "2026-11-20", {}) is None              # ohne Vorlagen
    # nur vergangene oder abgesagte Sitzungen: Karte fehlt; dazu ohne Vorlage bis heute: aktuell fehlt ganz
    alt = [_sitzung("a", "2026-11-19"), _sitzung("b", "2026-11-22", abgesagt=True)]
    assert set(export._aktuell(CACHE, heim, kurz, alt, "2026-11-20", {})) == {"vorlagen"}
    assert export._aktuell({"p/3": _vorlage("3", "2026-11-21")}, {}, {}, alt, "2026-11-20", {}) is None
    # Vorlage ohne Gebiet (nur „gesamt“): area und ort None, nie „gesamt“
    v = export._aktuell(CACHE, {}, kurz, [], "2026-11-20", {})["vorlagen"]
    assert v == [{"reference": "1/2026", "date": "2026-11-18", "paper_type": "Mitteilung",
                  "name": "[Testdaten] Vorlage 1", "area": None, "ort": None, "source_object": "p/1"}]


def test_hoechstzahlen_und_reihenfolge():
    cache = {f"p/{i}": _vorlage(f"{i:04d}", f"2026-11-{10 + i % 4:02d}") for i in range(1, 9)}
    sitzungen = [_sitzung(str(i), f"2026-11-{20 + i:02d}") for i in range(8, 0, -1)]
    sitzungen += [_sitzung("ohne", "2026-11-21", None), _sitzung("frueh", "2026-11-21", "09:00")]
    a = export._aktuell(cache, {}, {}, sitzungen, "2026-11-20", {})
    assert [x["source_object"] for x in a["sitzungen"]] == ["m/frueh", "m/1", "m/ohne", "m/2", "m/3", "m/4"]
    assert len(a["vorlagen"]) == export.AKTUELL_VORLAGEN == 5 and export.AKTUELL_SITZUNGEN == 6
    assert [x["reference"] for x in a["vorlagen"]] == ["0007/2026", "0003/2026", "0006/2026", "0002/2026",
                                                       "0005/2026"]
