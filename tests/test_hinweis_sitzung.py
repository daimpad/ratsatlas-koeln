"""Hinweis zum Stand aus dem Sitzungsnamen (Entscheidung 20.11.2026 (7) (b), Teil der Pipeline).

Die Stadt setzt OParl `cancelled` bei keiner Sitzung; dass eine Sitzung ausfällt oder verschoben ist, steht nur im
Namen. `export.hinweis_sitzung` leitet daraus nach einer festen Wortliste ein kleines Feld ab: „abgesagt“ bei „fällt
aus“, „entfällt“, „enfällt“ (Schreibweise der Quelle) oder „abgesagt“, sonst „verschoben“ bei „verschoben“ oder
„vertagt“, sonst keines; nur ganze Wörter, Groß- und Kleinschreibung gleich, aus dem Namen nach der Maske. Das Feld
`hinweis` steht in zeit.json (`meetings`) und in index.json („Aktuell in Köln“, `aktuell.sitzungen`, weiter ohne Namen);
dort fehlen Sitzungen mit Hinweis „abgesagt“ wie abgesagte. `export` schreibt eine Zeile nur mit Zahlen, `check` prüft
das Feld mit derselben Funktion. Alle Gremien, Sitzungen und Namen sind erfunden (lokaler Testserver oder direkte
Aufrufe); keine Anfragen an die Stadt."""
import importlib.util
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import build, check, config, export, kontext, maske, sessionnet

ROOT = Path(__file__).resolve().parents[1]
G = "Beispielbeirat"
ABGESAGT = ("fällt aus", "entfällt", "enfällt", "abgesagt")
VERSCHOBEN = ("verschoben", "vertagt")


def _formen(wort):
    """Schreibweisen eines Worts der Liste: wie in der Liste, mit großem Anfang, ganz groß."""
    return (wort, wort[0].upper() + wort[1:], wort.upper())


@pytest.mark.parametrize("wort, erwartet", [(w, "abgesagt") for w in ABGESAGT]
                         + [(w, "verschoben") for w in VERSCHOBEN])
def test_jede_wortform(wort, erwartet):
    """Jede Form der Liste in jeder Schreibweise, an jeder Stelle des Namens und zwischen Satzzeichen."""
    for form in _formen(wort):
        for name in (f"{G} - {form}", f"{G} – Sitzung {form}!", f"{form}: {G}", f"{G} ({form})", f"-{form}-",
                     f"Sitzung des {G}es {form}, neuer Termin folgt", f"{G}\n{form}"):
            assert export.hinweis_sitzung(name) == erwartet, name
    # „fällt aus“ auch mit anderem Leerraum dazwischen
    assert export.hinweis_sitzung(f"{G} fällt  aus") == export.hinweis_sitzung(f"{G} fällt\taus") == "abgesagt"


@pytest.mark.parametrize("name", [
    f"Achtung: Die Sitzung des {G}es wurde abgesagt und fällt aus!",
    f"{G} - verschoben, entfällt",
    f"{G} – vertagt\nAchtung: Die Sitzung wurde abgesagt und fällt aus!",
    f"{G} - Sitzung enfällt, vertagt auf einen späteren Zeitpunkt",
    f"Verschoben: {G} – Abgesagt",
])
def test_abgesagt_geht_vor(name):
    """Nennt der Name eine Absage und eine Verschiebung, gilt „abgesagt“."""
    assert export.hinweis_sitzung(name) == "abgesagt"


@pytest.mark.parametrize("name", [
    "Ausschuss für verschobene Projekte", "Arbeitskreis vertagte Fragen", "Arbeitskreis für Vertagtes",
    "Beirat für abgesagte Termine", f"{G} gefällt aus Prinzip", f"{G} fällt ausnahmsweise kürzer",
    "Unverschobener Arbeitskreis", f"{G} entfällte", f"{G} – Abgesagtes", f"{G}_abgesagt", f"{G} 3verschoben",
    f"{G} verschoben2", f"{G} - verlegt", f"{G} - ausgefallen", f"{G} - fällt weg", f"{G} - Sitzung",
    f"Sitzung des {G}es", "Bezirksvertretung 4 (Ehrenfeld)",
])
def test_nur_ganze_woerter_der_liste(name):
    """Andere Formen, Wörter mit Buchstaben, Ziffern oder „_“ davor oder dahinter und Wörter außerhalb der Liste ergeben
    keinen Hinweis."""
    assert export.hinweis_sitzung(name) is None


@pytest.mark.parametrize("name, erwartet", [
    (f"Sitzung des {G}es\n-Sitzung ist auf den 3. Dezember verschoben worden!-", "verschoben"),
    (f"{G}\r\nAchtung: Die Sitzung wurde abgesagt und fällt aus!", "abgesagt"),
    (f"{G}\nACHTUNG: Die Sitzung wird kurzfristig auf Donnerstag, 03.12.2026, verlegt.", None),
    (f"\n  \nSitzung des {G}es \n-Sitzung ist auf den 3. Dezember verschoben worden!-", "verschoben"),
])
def test_hinweis_auf_der_zweiten_zeile(name, erwartet):
    """Der ganze Name zählt, auch eine zweite Zeile (beobachtete Formen eines Hinweises, erfundenes Gremium und Datum);
    „verlegt“ steht nicht in der Liste."""
    assert export.hinweis_sitzung(name) == erwartet


def test_unicode_form_und_ohne_namen():
    """Ein zerlegtes „ä“ (Unicode-Form NFD) gilt wie ein ganzes; ohne Namen kein Hinweis."""
    for wort in ("fällt aus", "entfällt", "enfällt"):
        assert export.hinweis_sitzung(unicodedata.normalize("NFD", f"{G} - {wort}")) == "abgesagt"
        assert export.hinweis_sitzung(unicodedata.normalize("NFD", f"{G} - {wort.upper()}")) == "abgesagt"
    for leer in (None, "", "   ", 17, ["abgesagt"]):
        assert export.hinweis_sitzung(leer) is None


def test_maskierte_namen():
    """Der Hinweis entsteht aus dem Namen nach der Maske (Maske.sitzungsname), wie er in zeit.json steht: Die Maske
    kürzt die Hausnummer, nicht die Wörter der Liste; ihr Platzhalter selbst ergibt keinen Hinweis. Erfundene
    Straßen."""
    m = maske.Maske(set(), strassen=[])
    for roh, erwartet in [("Ortstermin Musterstraße 12 - verschoben", "verschoben"),
                          ("Ortstermin Musterweg 7 – entfällt", "abgesagt"),
                          ("Ortstermin Beispielallee 3\nAchtung: Die Sitzung wurde abgesagt und fällt aus!",
                           "abgesagt"),
                          ("Ortstermin Musterweg 7", None)]:
        name = m.sitzungsname(roh)
        assert maske.OHNE_NR in name and not re.search(r"\d", name), name
        assert export.hinweis_sitzung(name) == export.hinweis_sitzung(roh) == erwartet, name
    assert export.hinweis_sitzung(maske.OHNE_NR) is None


def test_hinweis_unabhaengig_vom_gremium():
    """Der Zusatz zum Stand fällt aus dem Gremium weg (export._ZUSATZ_STAND), der Hinweis bleibt aus dem Namen; auch
    eine Sitzung mit Organisation erhält ihn."""
    org = "https://example.invalid/oparl/organizations/o1"
    sitzung = {"name": f"{G} - Sitzung enfällt", "organization": []}
    assert export.gremium_der_sitzung(sitzung, {}) == G and export.hinweis_sitzung(sitzung["name"]) == "abgesagt"
    sitzung = {"name": "Rat - vertagt auf einen späteren Zeitpunkt", "organization": [org]}
    assert export.gremium_der_sitzung(sitzung, {org: "Rat"}) == "Rat"
    assert export.hinweis_sitzung(sitzung["name"]) == "verschoben"


def test_zeile_im_log_nur_zahlen():
    sitzungen = [{"hinweis": "abgesagt"}, {"hinweis": "verschoben"}, {"hinweis": "abgesagt"}, {}]
    assert export.zeile_hinweise(sitzungen) == "Sitzungen mit Hinweis zum Stand aus dem Namen: abgesagt 2, verschoben 1"
    assert export.zeile_hinweise([]) == "Sitzungen mit Hinweis zum Stand aus dem Namen: abgesagt 0, verschoben 0"


# --- export._aktuell direkt -------------------------------------------------------------------------------------------

def _sitzung(k, tag, hinweis=None, abgesagt=False):
    m = {"date": tag, "time": "17:00", "gremium": "Rat", "name": f"Testsitzung {k}", "cancelled": abgesagt,
         "state": None, "web": None, "invitation": None, "agenda_items": 0, "start": f"{tag}T17:00", "end": None,
         "source_object": f"m/{k}"}
    return {**m, "hinweis": hinweis} if hinweis else m


def test_aktuell_ohne_abgesagte_aus_dem_namen():
    """„Aktuell in Köln“: Eine Sitzung mit Hinweis „abgesagt“ fehlt wie eine abgesagte und belegt keinen Platz; eine
    mit Hinweis „verschoben“ steht dort mit dem Feld, ohne Hinweis fehlt das Feld; nie ein Name."""
    cache = {"p/1": {"reference": "1/2026", "date": "2026-11-18", "paper_type": "Mitteilung",
                     "name": "[Testdaten] Vorlage 1", "source_object": "p/1"}}
    sitzungen = [_sitzung("a1", "2026-11-21", "abgesagt"), _sitzung("v1", "2026-11-22", "verschoben"),
                 _sitzung("c1", "2026-11-22", "verschoben", abgesagt=True)]
    sitzungen += [_sitzung(f"o{t}", f"2026-11-{t}") for t in range(23, 29)]
    a = export._aktuell(cache, {}, {}, sitzungen, "2026-11-20", {})["sitzungen"]
    assert [x["source_object"] for x in a] == ["m/v1"] + [f"m/o{t}" for t in range(23, 28)]
    assert a[0] == {"date": "2026-11-22", "time": "17:00", "gremium": "Rat", "hinweis": "verschoben", "web": None,
                    "source_object": "m/v1"}
    assert all(set(x) == {"date", "time", "gremium", "web", "source_object"} for x in a[1:])
    assert "hinweis" in export.AKTUELL_FELDER["sitzungen"] and "name" not in export.AKTUELL_FELDER["sitzungen"]
    # nur abgesagte Sitzungen: Karte fehlt
    a = export._aktuell(cache, {}, {}, sitzungen[:1], "2026-11-20", {})
    assert set(a) == {"vorlagen"}


# --- Kette auf dem lokalen Testserver ---------------------------------------------------------------------------------

# erfundene Sitzungen: Kennung → (Name oder None, Organisation oder None, abgesagt laut OParl, erwarteter Hinweis);
# Beginn am Tag nach heute plus Stelle in der Liste. Ohne die Sitzungen mit Hinweis „abgesagt“ und die abgesagte
# bleiben sechs kommende, alle in „Aktuell“; zählten „a1“, „a2“ und „a3“ mit, fehlten dort „o2“, „v3“ und „nn“
SITZUNGEN = {
    "a1": (f"{G} - Sitzung enfällt", None, False, "abgesagt"),
    "v1": ("Sitzung des Probebeirates\n-Sitzung ist auf den 3. Dezember verschoben worden!-", None, False,
           "verschoben"),
    "a2": ("Sitzung des Probebeirates\nAchtung: Die Sitzung wurde abgesagt und fällt aus!", None, False, "abgesagt"),
    "o1": ("Ausschuss für verschobene Projekte", None, False, None),
    "a3": ("Rat - ENTFÄLLT", "rat", False, "abgesagt"),
    "v2": ("Musterkreis - vertagt auf einen späteren Zeitpunkt", None, False, "verschoben"),
    "c1": ("Musterkreis - verschoben", None, True, "verschoben"),
    "o2": ("Arbeitskreis vertagte Fragen", None, False, None),
    "v3": ("Ortstermin Musterstraße 12 - verschoben", None, False, "verschoben"),
    "nn": (None, None, False, None),
}
IN_AKTUELL = ["v1", "o1", "v2", "o2", "v3", "nn"]
# Teile der Namen, die nicht im Gremium stehen und deshalb nirgends in index.json stehen dürfen
NAMENSTEILE = ("Sitzung ist auf den", "Achtung", "vertagt auf", "Sitzung enfällt", "ENTFÄLLT", "Musterstraße 12",
               "Testsitzung")


def _aufbau(oparl):
    b = oparl.b
    for i, (k, (name, org, abgesagt, _)) in enumerate(SITZUNGEN.items(), 1):
        sitzung = {"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting",
                   "start": f"{date.today() + timedelta(days=i)}T16:00:00Z", "cancelled": abgesagt,
                   "web": f"https://example.invalid/sitzung/{k}", "modified": "2026-11-01T08:00:00+01:00"}
        if name is not None:
            sitzung["name"] = name
        if org:
            sitzung["organization"] = [f"{b}/organizations/{org}"]
        oparl.meetings.append(sitzung)
    sessionnet.fetch_all()
    build.build()
    export.export()


def _lesen(name):
    return json.loads((config.EXPORT / config.STADT / name).read_text())


def test_kette_zeit_json_index_json_log_und_check(oparl, capsys):
    """Orakel: In zeit.json trägt jede Sitzung den erwarteten Hinweis (ohne Hinweis kein Feld), aus dem Namen nach der
    Maske, auch neben `cancelled` und bei einer Sitzung mit Organisation; in index.json („Aktuell“) stehen die sechs
    Sitzungen ohne Hinweis „abgesagt“ und ohne `cancelled`, mit dem Hinweis „verschoben“ wo erwartet, ohne Namen;
    Zeile im Log nur mit Zahlen; check ohne Befund."""
    capsys.readouterr()
    _aufbau(oparl)
    log = capsys.readouterr().out
    zeit = {x["source_object"].rsplit("/", 1)[1]: x for x in _lesen("zeit.json")["meetings"]}
    for k, (name, _, abgesagt, hinweis) in SITZUNGEN.items():
        assert zeit[k].get("hinweis") == hinweis and ("hinweis" in zeit[k]) == bool(hinweis), k
        assert zeit[k]["cancelled"] == abgesagt and export.hinweis_sitzung(zeit[k]["name"]) == hinweis, k
    assert "hinweis" not in zeit["1"]   # Sitzung des Testservers („Bezirksvertretung 4 (Ehrenfeld)“)
    assert zeit["a3"]["gremium"] == "Rat" and zeit["a1"]["gremium"] == G
    assert zeit["v3"]["name"] == f"Ortstermin Musterstraße {maske.OHNE_NR} - verschoben"
    assert re.search(r"Sitzungen mit Hinweis zum Stand aus dem Namen: abgesagt 3, verschoben 4\n", log), log
    zeilen = [z for z in log.splitlines() if z.startswith("Sitzungen mit Hinweis zum Stand")]
    assert len(zeilen) == 1 and re.fullmatch(r"Sitzungen mit Hinweis zum Stand aus dem Namen: abgesagt \d+, "
                                             r"verschoben \d+", zeilen[0]), zeilen

    index = _lesen("index.json")
    aktuell = index["aktuell"]["sitzungen"]
    assert [x["source_object"].rsplit("/", 1)[1] for x in aktuell] == IN_AKTUELL
    for x in aktuell:
        k = x["source_object"].rsplit("/", 1)[1]
        assert x.get("hinweis") == SITZUNGEN[k][3] and ("hinweis" in x) == bool(SITZUNGEN[k][3]), k
        assert "name" not in x and set(x) <= set(export.AKTUELL_FELDER["sitzungen"]), k
        assert x["gremium"] == zeit[k]["gremium"], k
    text = (config.EXPORT / config.STADT / "index.json").read_text()
    for teil in NAMENSTEILE:
        assert teil not in text, teil

    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    capsys.readouterr()
    assert check.hinweise_sitzungen() == ([], [])
    out = capsys.readouterr().out
    assert (f"Sitzungen in zeit.json: {len(zeit)}, davon mit Hinweis abgesagt 3, verschoben 4; Sitzungen in "
            f"index.json („Aktuell in Köln“): 6\n") in out


def test_check_meldet_abweichungen_nur_mit_zahlen(oparl, capsys):
    """check meldet in zeit.json jedes fehlende, überzählige oder falsche Feld `hinweis` (auch `null`), in index.json
    („Aktuell“) jedes Feld, das nicht dem Namen derselben Sitzung in zeit.json folgt, jede Sitzung, die dort fehlt,
    und jede Sitzung mit Hinweis „abgesagt“; nur mit Zahlen, ohne Namen und Kennungen."""
    _aufbau(oparl)
    base = config.EXPORT / config.STADT
    zeit = _lesen("zeit.json")
    je = {x["source_object"].rsplit("/", 1)[1]: x for x in zeit["meetings"]}
    del je["v1"]["hinweis"]                  # fehlt
    je["o1"]["hinweis"] = "verschoben"       # zu viel
    je["a1"]["hinweis"] = "verschoben"       # anderer Wert
    je["o2"]["hinweis"] = None               # Feld ohne Hinweis
    (base / "zeit.json").write_text(json.dumps(zeit, ensure_ascii=False))
    index = _lesen("index.json")
    s = {x["source_object"].rsplit("/", 1)[1]: x for x in index["aktuell"]["sitzungen"]}
    del s["v2"]["hinweis"]                   # fehlt
    s["nn"]["hinweis"] = "abgesagt"          # zu viel
    index["aktuell"]["sitzungen"] += [
        {"date": "2026-12-01", "time": "17:00", "gremium": G, "hinweis": "abgesagt", "web": None,
         "source_object": f"{oparl.b}/meetings/a1"},
        {"date": "2026-12-02", "time": "17:00", "gremium": "Rat", "web": None,
         "source_object": f"{oparl.b}/meetings/unbekannt"}]
    (base / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    capsys.readouterr()
    befunde, fehlend = check.hinweise_sitzungen()
    out = capsys.readouterr().out
    assert fehlend == []
    assert befunde == [
        "Hinweise zum Stand: Sitzungen in zeit.json, deren Feld `hinweis` nicht der Regel export.hinweis_sitzung über "
        "ihren Namen folgt (fehlt, zu viel oder anderer Wert): 4",
        "Hinweise zum Stand: Sitzungen in index.json („Aktuell in Köln“), deren Feld `hinweis` nicht der Regel "
        "export.hinweis_sitzung über den Namen derselben Sitzung in zeit.json folgt: 2, ohne dieselbe Sitzung in "
        "zeit.json: 1",
        "Hinweise zum Stand: Sitzungen mit Hinweis „abgesagt“ aus dem Namen in index.json („Aktuell in Köln“; "
        "export._aktuell lässt sie aus wie abgesagte): 1"]
    for teil in ("Probebeirat", "Musterkreis", "Musterstraße", G, "Arbeitskreis", "Ausschuss", "meetings/"):
        assert teil not in out and teil not in " ".join(befunde), teil


def test_check_ohne_zeit_json(tmp_path, capsys):
    """Ohne zeit.json (Kartenvorschau ohne Vorlagen) und ohne Sitzungen in index.json nichts zu prüfen; nennt index.json
    Sitzungen, fehlt zeit.json für die Prüfung (nicht durchgeführt statt still bestanden)."""
    (tmp_path / "index.json").write_text(json.dumps({"meta": {}}))
    assert check.hinweise_sitzungen(tmp_path) == ([], [])
    (tmp_path / "index.json").write_text(json.dumps({"aktuell": {"sitzungen": [
        {"date": "2026-12-01", "time": None, "gremium": "Rat", "web": None, "source_object": "m/1"}]}}))
    befunde, fehlend = check.hinweise_sitzungen(tmp_path)
    assert befunde == [] and len(fehlend) == 1 and "zeit.json fehlt" in fehlend[0]


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_mit_testdaten(oparl, monkeypatch, capsys):
    """Die ganze Prüfung (`python -m pipeline check`) enthält die Prüfung der Hinweise: mit den Testdaten
    (tools/testdaten.py, Sitzungen heißen wie ihr Gremium) ohne Hinweis und ohne Befund; ein eingeschleustes Feld in
    zeit.json ist ein Befund."""
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    _tool("testdaten").main()
    build.build()
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    out = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    assert re.search(r"Sitzungen in zeit.json: \d+, davon mit Hinweis abgesagt 0, verschoben 0; Sitzungen in "
                     r"index.json \(„Aktuell in Köln“\): \d+\n", out), out
    zeit = _lesen("zeit.json")
    zeit["meetings"][0]["hinweis"] = "abgesagt"
    (config.EXPORT / config.STADT / "zeit.json").write_text(json.dumps(zeit, ensure_ascii=False))
    with pytest.raises(SystemExit) as e:
        check.check()
    assert ("Hinweise zum Stand: Sitzungen in zeit.json, deren Feld `hinweis` nicht der Regel export.hinweis_sitzung "
            "über ihren Namen folgt (fehlt, zu viel oder anderer Wert): 1") in str(e.value)
