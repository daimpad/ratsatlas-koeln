"""Kölner Gremien für „Wer entscheidet“ (Entscheidung 21.11.2026 (2), Pull Request 4a): gremien.json, Hinweis und
Kennung des Gremiums je Station der Prozesslinie, Prüfung in check, Freigabe „gremien“.

Alle Organisationen, Sitzungen, Kennungen und Vorlagen sind erfunden (direkte Aufrufe, lokaler OParl-Testserver oder
tools/testdaten.py); keine Anfragen an die Stadt. Namen von Ausschüssen stammen, wo ein Paragraf getroffen werden soll,
aus ausschuesse.AUSSCHUESSE (Namen der Satzung, keine Personen). Befunde von check enthalten nur Zahlen: Die Tests
prüfen, dass weder Namen noch Kennungen darin stehen."""
import importlib.util
import json
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from pipeline import ausschuesse, build, check, config, export, kontext, sessionnet

try:   # auf dem Stand vor Pull Request 4a fehlt das Modul; jeder Test schlägt dann einzeln fehl
    from pipeline import gremien
except ImportError:
    gremien = None

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"
O, M = f"{B}/organizations", f"{B}/meetings"
PARAGRAF = {nr: name for nr, name, _ in ausschuesse.AUSSCHUESSE}
AUSSCHUSS = "Fachausschüsse und weitere Gremien"
STAND = "2026-11-21"
SEIT = "2025-11-21"


def _org(k, name, klasse, ende=None, web=None):
    return {"id": f"{O}/{k}", "name": name, "classification": klasse, "end_date": ende, "web": web}


def _sitzung(k, tag, time="17:00", cancelled=False, hinweis=None, name=None):
    """Erfundene Sitzung in der Form von zeit.json (export._meetings ohne start/end)."""
    m = {"date": tag, "time": time, "gremium": "Probegremium", "name": name or "[Testdaten] Probegremium",
         "cancelled": cancelled, "state": None, "web": f"https://example.invalid/sitzung/{k}", "invitation": None,
         "agenda_items": 0, "source_object": f"{M}/{k}"}
    return {**m, "hinweis": hinweis} if hinweis else m


# --- Kennung ---------------------------------------------------------------------------------------------------------

def test_kennung_aus_der_oparl_kennung():
    """Teil nach dem letzten „/organizations/“, kleingeschrieben, andere Zeichen als „-“; ohne diesen Teil der letzte
    Abschnitt; bei gleicher Kennung beide mit den ersten 8 Zeichen des SHA-1 der OParl-Kennung."""
    ids = [f"{O}/gr/12", f"{O}/BV4", "https://example.invalid/anders/x7", f"{O}/a_b", f"{O}/A-B"]
    k = gremien.schluessel(ids)
    assert k[f"{O}/gr/12"] == "gr-12" and k[f"{O}/BV4"] == "bv4" and k["https://example.invalid/anders/x7"] == "x7"
    assert k[f"{O}/a_b"] != k[f"{O}/A-B"]
    assert all(re.fullmatch(r"a-b-[0-9a-f]{8}", k[i]) for i in (f"{O}/a_b", f"{O}/A-B"))
    assert gremien.schluessel(ids) == k   # stabil
    assert len(set(k.values())) == len(ids)
    # das Log zählt die aufgenommenen Gremien mit Zusatz
    orgs = [_org(i.rsplit("/", 1)[1], "[Testdaten] Probegremium", AUSSCHUSS) for i in ids[3:]]
    _, zahlen = gremien.daten(orgs, [], {}, [], STAND, [])
    assert zahlen["mit_zusatz"] == 2


# --- Gruppen -----------------------------------------------------------------------------------------------------------

def test_gruppen_fraktion_paragraf_und_stadtbezirk():
    """Rat, Bezirksvertretung mit Stadtbezirk (nur einer der neun), Ausschuss mit eindeutigem Paragrafen, mehrdeutiger
    Paragraf und ohne Treffer als übrige; Fraktionen und Organisationen ohne Klasse nicht aufgenommen; ein aufgelöstes
    Gremium zählt beim Paragrafen nicht mit."""
    orgs = [_org("rat", "Rat", "Rat"),
            _org("bv4", "Bezirksvertretung 4 (Ehrenfeld)", "Bezirksvertretungen"),
            _org("bvx", "Bezirksvertretung Probedorf", "Bezirksvertretungen"),
            _org("ha", PARAGRAF[7], AUSSCHUSS),
            _org("ha-alt", PARAGRAF[7], AUSSCHUSS, ende="2025-10-31"),
            _org("s1", "Ausschuss für Schule und Weiterbildung", AUSSCHUSS),
            _org("s2", PARAGRAF[19], AUSSCHUSS),
            _org("probe", "[Testdaten] Probeausschuss", AUSSCHUSS),
            _org("fr", "[Testdaten] Probefraktion", "Fraktionen und Gruppen"),
            _org("dst", "[Testdaten] Probedienststelle", None)]
    gruppe, nicht, treffer = gremien.einordnen(orgs, STAND)
    g = {k.rsplit("/", 1)[1]: v for k, v in gruppe.items()}
    assert g["rat"] == {"gruppe": "rat"}
    assert g["bv4"] == {"gruppe": "bezirksvertretung", "stadtbezirk": "Ehrenfeld"}
    assert g["bvx"] == {"gruppe": "bezirksvertretung"}
    assert g["ha"] == {"gruppe": "ausschuss", "paragraf": 7}
    assert g["ha-alt"] == {"gruppe": "uebrige"}
    assert g["s1"] == g["s2"] == g["probe"] == {"gruppe": "uebrige"}
    assert "fr" not in g and "dst" not in g
    assert nicht == {"fraktionen": 1, "ohne_klasse": 1}
    assert treffer[7] == 1 and treffer[19] == 2 and len(treffer) == 17 and sum(n == 0 for n in treffer.values()) == 15


def test_aufgeloest_am_rand():
    """Aufgelöst nur bei einem lesbaren Enddatum vor dem Datenstand; am Datenstand oder danach nicht."""
    assert gremien.aufgeloest({"end_date": "2026-11-20"}, STAND)
    assert not gremien.aufgeloest({"end_date": STAND}, STAND)
    assert not gremien.aufgeloest({"end_date": "2027-01-01"}, STAND)
    assert not gremien.aufgeloest({"end_date": "kaputt"}, STAND) and not gremien.aufgeloest({}, STAND)


# --- Zählung -----------------------------------------------------------------------------------------------------------

def _station(tag, key, cancelled=0, hinweis=None):
    s = {"meeting_id": f"{M}/{tag}", "start_date": f"{tag}T17:00:00+01:00", "cancelled": cancelled,
         "gremium_key": key}
    return {**s, "hinweis": hinweis} if hinweis else s


def test_zwoelf_monate_an_den_raendern():
    """Zeitraum nach `seit` bis einschließlich Datenstand (gebietszahlen.window_start, 365 Tage): eine Sitzung am Tag
    `seit` zählt nicht, am Tag danach und am Datenstand zählt sie; eine Sitzung nach dem Datenstand ist die nächste.
    Vorlagen ebenso über die Stationen, jede Vorlage einmal je Gremium, abgesagte Stationen zählen nicht."""
    orgs_je = {f"{M}/{k}": [f"{O}/rat"] for k in ("a", "b", "c", "d")}
    meetings = [_sitzung("a", SEIT), _sitzung("b", "2025-11-22"), _sitzung("c", STAND), _sitzung("d", "2026-11-22")]
    zahl, naechste, ohne = gremien.sitzungen(meetings, orgs_je, {f"{O}/rat"}, {f"{O}/rat"}, SEIT, STAND)
    assert zahl[f"{O}/rat"] == 2 and naechste[f"{O}/rat"]["source_object"] == f"{M}/d" and not ohne
    papers = [{"process": [_station(SEIT, "rat")]},
              {"process": [_station("2025-11-22", "rat"), _station(STAND, "rat")]},
              {"process": [_station(STAND, "rat", cancelled=1)]},
              {"process": [_station(STAND, "rat", hinweis="abgesagt")]},
              {"process": [_station(STAND, "rat", hinweis="verschoben"), _station(STAND, "bv4")]},
              {"process": [_station("2026-11-22", "rat")]},
              {"process": [{"meeting_id": None, "start_date": None, "cancelled": None}]}]
    assert gremien.vorlagen(papers, SEIT, STAND) == {"rat": 2, "bv4": 1}


def test_naechste_sitzung_ueberspringt_absagen_und_traegt_verschoben():
    """Die nächste Sitzung ist nicht abgesagt (weder OParl `cancelled` noch Hinweis „abgesagt“ aus dem Namen); eine
    Sitzung ohne Uhrzeit steht hinter einer mit Uhrzeit am selben Tag; „verschoben“ bleibt als Hinweis."""
    org = f"{O}/bv4"
    meetings = [_sitzung("x1", "2026-11-23", cancelled=True), _sitzung("x2", "2026-11-24", hinweis="abgesagt"),
                _sitzung("x3", "2026-11-25", time=None), _sitzung("x4", "2026-11-25", hinweis="verschoben"),
                _sitzung("x5", "2026-12-01")]
    orgs_je = {m["source_object"]: [org] for m in meetings}
    _, naechste, _ = gremien.sitzungen(meetings, orgs_je, {org}, {org}, SEIT, STAND)
    assert naechste[org]["source_object"] == f"{M}/x4"
    d, _ = gremien.daten([_org("bv4", "Bezirksvertretung 4 (Ehrenfeld)", "Bezirksvertretungen")], meetings, orgs_je,
                         [], STAND, [])
    assert d["gremien"][0]["naechste_sitzung"] == {"date": "2026-11-25", "time": "17:00", "hinweis": "verschoben",
                                                   "web": "https://example.invalid/sitzung/x4",
                                                   "source_object": f"{M}/x4"}
    # nur abgesagte danach: kein Feld
    d, _ = gremien.daten([_org("bv4", "Bezirksvertretung 4 (Ehrenfeld)", "Bezirksvertretungen")], meetings[:2],
                         orgs_je, [], STAND, [])
    assert "naechste_sitzung" not in d["gremien"][0]


def test_zuordnung_ueber_die_oparl_organisation():
    """Eine Sitzung zählt für jede Organisation, auf die sie in meetings.json verweist, nicht über den Gremiennamen;
    ohne Verweis, mit unbekannter oder nicht aufgenommener Organisation zählt sie je Grund unter „ohne Gremium“."""
    ids, alle = {f"{O}/rat", f"{O}/bv4"}, {f"{O}/rat", f"{O}/bv4", f"{O}/fr"}
    meetings = [_sitzung("g", "2026-10-01", name="Rat"), _sitzung("o", "2026-10-02", name="Rat"),
                _sitzung("u", "2026-10-03"), _sitzung("f", "2026-10-04")]
    orgs_je = {f"{M}/g": [f"{O}/rat", f"{O}/bv4"], f"{M}/o": [], f"{M}/u": [f"{O}/unbekannt"], f"{M}/f": [f"{O}/fr"]}
    zahl, _, ohne = gremien.sitzungen(meetings, orgs_je, ids, alle, SEIT, STAND)
    assert zahl == {f"{O}/rat": 1, f"{O}/bv4": 1}
    assert ohne == {"ohne Organisation": 1, "Organisation nicht in der Tabelle": 1,
                    "Organisation nicht aufgenommen": 1}


def test_daten_felder_reihenfolge_und_log():
    """Nur die Felder aus gremien.FELDER; Reihenfolge Rat, Ausschüsse (nach Paragraf), Bezirksvertretungen (nach
    Nummer), übrige, aufgelöste je Gruppe zuletzt; das Log nennt nur Zahlen."""
    orgs = [_org("z", "[Testdaten] Probebeirat", AUSSCHUSS, web="https://example.invalid/g/z"),
            _org("alt", "[Testdaten] Probeausschuss", AUSSCHUSS, ende="2020-10-31"),
            _org("bv9", "Bezirksvertretung 9 (Mülheim)", "Bezirksvertretungen"),
            _org("bv1", "Bezirksvertretung 1 (Innenstadt)", "Bezirksvertretungen"),
            _org("f", PARAGRAF[11], AUSSCHUSS), _org("h", PARAGRAF[7], AUSSCHUSS),
            _org("rat", "Rat", "Rat"), _org("fr", "[Testdaten] Probefraktion", "Fraktionen und Gruppen")]
    quellen = [{"name": config.QUELLE_OPARL, "url": "u", "license": "l", "retrieved_at": "2026-11-21T22:00:00Z"}]
    d, zahlen = gremien.daten(orgs, [], {}, [], STAND, quellen)
    assert [e["key"] for e in d["gremien"]] == ["rat", "h", "f", "bv1", "bv9", "z", "alt"]
    assert all(set(e) <= set(gremien.FELDER) for e in d["gremien"])
    assert d["gremien"][-1]["aufgeloest"] is True and d["gremien"][-1]["end_date"] == "2020-10-31"
    assert d["gremien"][-2]["web"] == "https://example.invalid/g/z" and "aufgeloest" not in d["gremien"][-2]
    assert d["meta"]["zeitraum"] == {"seit": SEIT, "bis": STAND} and d["meta"]["datenstand"] == STAND
    assert d["meta"]["sources"] == [{"name": config.QUELLE_OPARL, "url": "u", "license": "l"}]
    assert d["meta"]["zustaendigkeitsordnung"]["url"] == ausschuesse.QUELLE["url"]
    assert d["meta"]["namensnennung"] == config.NAMENSNENNUNG and set(d["meta"]) == set(gremien.META_FELDER)
    log = "\n".join(gremien.zeilen_log(d, zahlen, {}))
    assert ("Gremien (gremien.json): 8 Organisationen, nicht aufgenommen Fraktionen und Gruppen 1, mit anderer oder "
            "ohne Klasse 0; aufgenommen 7: Rat 1, Ausschüsse mit Paragraf 2, Bezirksvertretungen 2, übrige 2; davon "
            "aufgelöst 1; Kennungen mit Zusatz aus dem SHA-1 (gleiche Kennung) 0\n") in log + "\n"
    assert ("mit genau einer Organisation 2, ohne Organisation 15, mit mehr als einer Organisation 0") in log
    assert "Bezirksvertretungen mit Stadtbezirk: 2 von 2, Stadtbezirke 2 von 9" in log
    assert "Probe" not in log and O not in log


# --- Stationen ---------------------------------------------------------------------------------------------------------

def test_hinweis_station_eine_regel():
    """export.hinweis_station: der Name der Station, ohne ihn der Name derselben Sitzung in zeit.json; ohne Sitzung
    kein Hinweis."""
    namen = {f"{M}/1": "[Testdaten] Probebeirat - Sitzung fällt aus"}
    assert export.hinweis_station({"meeting_id": f"{M}/1", "meeting": None}, namen) == "abgesagt"
    assert export.hinweis_station({"meeting_id": f"{M}/1", "meeting": "Probebeirat - verschoben"}, namen) == "verschoben"
    assert export.hinweis_station({"meeting_id": f"{M}/2", "meeting": "Probebeirat"}, namen) is None
    assert export.hinweis_station({"meeting_id": None, "meeting": "Probebeirat - abgesagt"}, namen) is None


def _kette_testserver(oparl, monkeypatch):
    """Testserver mit Gremien in der Kölner Form, einer Fraktion und einer nicht aufgenommenen Organisation; Sitzungen
    des Rates in den kommenden Tagen (abgesagt laut OParl, abgesagt laut Namen, verschoben, ohne Hinweis) und eine
    Sitzung der Fraktion; je Sitzung eine Vorlage mit Beratung."""
    b = oparl.b
    oparl.orgs[0]["classification"] = "Bezirksvertretungen"
    oparl.orgs[1]["classification"] = "Rat"
    for o in oparl.orgs:
        o.pop("organizationType", None)
    oparl.orgs += [{"id": f"{b}/organizations/fr", "name": "[Testdaten] Probefraktion",
                    "classification": "Fraktionen und Gruppen", "modified": "2026-01-01T00:00:00+01:00"},
                   {"id": f"{b}/organizations/alt", "name": "[Testdaten] Probeausschuss", "classification": AUSSCHUSS,
                    "endDate": "2025-10-31", "modified": "2026-01-01T00:00:00+01:00"}]
    heute = date.today()
    namen = {"k1": ("Rat", True, "rat"), "k2": ("Rat - Sitzung fällt aus", False, "rat"),
             "k3": ("Rat\nTermin verschoben", False, "rat"), "k4": ("Rat", False, "rat"),
             "k5": ("[Testdaten] Probefraktion", False, "fr")}
    for i, (k, (name, cancelled, org)) in enumerate(namen.items(), 1):
        tag = (heute + timedelta(days=10 + i)).isoformat()
        oparl.meetings.append({"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting", "name": name,
                               "start": f"{tag}T17:00:00+01:00", "cancelled": cancelled,
                               "organization": [f"{b}/organizations/{org}"], "modified": "2026-11-01T08:00:00+01:00",
                               "agendaItem": [{"id": f"{b}/agendaitems/{k}", "number": "1", "name": "TOP",
                                               "public": True}]})
        p = oparl.paper(100 + i, name=f"[Testdaten] Probevorlage {i}")
        p["consultation"] = [{"id": f"{b}/consultations/{k}", "meeting": f"{b}/meetings/{k}",
                              "agendaItem": f"{b}/agendaitems/{k}", "role": "Entscheidung", "authoritative": True}]
        oparl.papers.append(p)
    sessionnet.fetch_all()
    build.build()


def _stationen(base):
    aus = {}
    for d in ("ortsteile", "bezirke", "ohne-ortsbezug"):
        for f in sorted((base / d).glob("*.json")):
            for p in json.loads(f.read_text())["papers"]:
                for s in p["process"]:
                    aus[(s["meeting_id"] or "").rsplit("/", 1)[-1]] = s
    return aus


def test_kette_stationen_gremien_json_und_check(oparl, monkeypatch, capsys):
    """Abruf, Aufbau und Export mit dem Testserver: Stationen tragen den Hinweis aus dem Sitzungsnamen (abgesagt,
    verschoben) und die Kennung des Gremiums nur für Gremien aus gremien.json (nicht für die Fraktion); Stand der
    Vorlage zählt weiter nur OParl `cancelled`. gremien.json ohne Fraktion, mit nächster Sitzung des Rates (die
    verschobene, weil die beiden davor abgesagt sind); check ohne Befund."""
    _kette_testserver(oparl, monkeypatch)
    capsys.readouterr()
    export.export()
    log = capsys.readouterr().out
    base = config.EXPORT / config.STADT
    st = _stationen(base)
    assert st["k1"].get("hinweis") is None and st["k1"]["cancelled"] == 1 and st["k1"]["gremium_key"] == "rat"
    assert st["k2"]["hinweis"] == "abgesagt" and st["k2"]["gremium_key"] == "rat"
    assert st["k3"]["hinweis"] == "verschoben" and st["k4"].get("hinweis") is None
    assert "gremium_key" not in st["k5"] and st["1"]["gremium_key"] == "bv4"
    # Felder am Ende der Station, die bisherigen unverändert in ihrer Reihenfolge
    assert list(st["k2"])[-2:] == ["hinweis", "gremium_key"]
    assert list(st["k4"])[:12] == ["position", "role", "authoritative", "meeting_id", "gremium", "meeting", "start_date",
                                   "cancelled", "number", "result", "public", "status"]
    g = json.loads((base / "gremien.json").read_text())
    keys = {e["key"]: e for e in g["gremien"]}
    assert set(keys) == {"rat", "bv4", "alt"} and keys["alt"]["aufgeloest"] is True
    assert keys["rat"]["naechste_sitzung"]["source_object"].endswith("/meetings/k3")
    assert keys["rat"]["naechste_sitzung"]["hinweis"] == "verschoben"
    assert keys["bv4"]["stadtbezirk"] == "Ehrenfeld" and keys["bv4"]["sitzungen_12m"] == 1
    assert keys["bv4"]["vorlagen_12m"] == 5
    assert "Stationen der Prozesslinie in den Gebietsdateien: 10, mit Sitzung 10, mit Hinweis aus dem Sitzungsnamen 2 " \
           "(abgesagt 1, verschoben 1), mit Kennung des Gremiums aus gremien.json 9" in log
    assert "Gremien (gremien.json): 4 Organisationen, nicht aufgenommen Fraktionen und Gruppen 1, mit anderer oder " \
           "ohne Klasse 0; aufgenommen 3: Rat 1, Ausschüsse mit Paragraf 0, Bezirksvertretungen 1, übrige 1; davon " \
           "aufgelöst 1; Kennungen mit Zusatz aus dem SHA-1 (gleiche Kennung) 0\n" in log
    assert "Sitzungen ohne Gremium aus gremien.json: 1 (ohne Organisation 0, Organisation nicht in der Tabelle 0, " \
           "Organisation nicht aufgenommen 1); Beratungen ohne Gremium aus gremien.json: 1 (ohne Organisation 0, " \
           "Organisation nicht in der Tabelle 0, Organisation nicht aufgenommen 1)" in log
    assert (base / "aemter.json").exists()
    db = sqlite3.connect(config.DB)
    try:
        assert check.gremien(db) == ([], []) and check.stationen(db) == ([], [])
    finally:
        db.close()
    assert check.aemter_aufbau() == ([], [])
    dcat = (base / "dcat.jsonld").read_text()
    assert f"{config.STADT}/gremien.json" in dcat and "aemter.json" not in dcat


def test_freigabe_aus_keine_dateien_keine_kennung(oparl, monkeypatch, capsys):
    """Ohne Freigabe „gremien“: weder gremien.json noch aemter.json, keine Kennung an den Stationen, der Hinweis aus dem
    Sitzungsnamen bleibt; index.json nennt die Freigabe als aus; check erwartet keine Datei und meldet eine vorhandene."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    _kette_testserver(oparl, monkeypatch)
    export.export()
    base = config.EXPORT / config.STADT
    assert not (base / "gremien.json").exists() and not (base / "aemter.json").exists()
    st = _stationen(base)
    assert not any("gremium_key" in s for s in st.values()) and st["k2"]["hinweis"] == "abgesagt"
    assert json.loads((base / "index.json").read_text())["meta"]["funktionen"]["gremien"] is False
    assert "gremien.json" not in (base / "dcat.jsonld").read_text()
    db = sqlite3.connect(config.DB)
    try:
        capsys.readouterr()
        assert check.gremien(db) == ([], []) and check.stationen(db) == ([], [])
        assert "abgeschaltet (config.ZUSATZTHEMEN) – keine Datei erwartet" in capsys.readouterr().out
        (base / "gremien.json").write_text('{"meta": {}, "gremien": []}')
        assert check.gremien(db)[0] == ["Gremien: gremien.json liegt vor, obwohl die Freigabe „gremien“ aus ist: 1"]
        # eine Kennung an einer Station ohne Freigabe ist ein Befund
        (base / "gremien.json").unlink()
        f = next(x for x in sorted((base / "ohne-ortsbezug").glob("*.json")) if json.loads(x.read_text())["papers"])
        d = json.loads(f.read_text())
        d["papers"][0]["process"][0]["gremium_key"] = "rat"
        f.write_text(json.dumps(d))
        assert check.stationen(db)[0] == [
            "Stationen: Feld `gremium_key` folgt nicht der Organisation der Beratung (gremien.kennungen; ohne Freigabe "
            "„gremien“ kein Feld): 1"]
    finally:
        db.close()
    assert check.aemter_aufbau() == ([], [])


def test_check_meldet_eingeschleuste_abweichungen_nur_mit_zahlen(oparl, monkeypatch, capsys):
    """check.gremien und check.stationen melden eingeschleuste Abweichungen nur mit Zahlen: ein Feld mit Personenbezug,
    eine geänderte Zahl, eine Fraktion, ein Paragraf bei einer Bezirksvertretung, eine abgesagte nächste Sitzung, ein
    falscher Zeitraum, ein fehlender Hinweis und eine falsche Kennung an Stationen."""
    _kette_testserver(oparl, monkeypatch)
    export.export()
    base = config.EXPORT / config.STADT
    pfad = base / "gremien.json"
    g = json.loads(pfad.read_text())
    keys = {e["key"]: e for e in g["gremien"]}
    keys["rat"]["mitglieder"] = ["[Testdaten] Person"]
    keys["rat"]["sitzungen_12m"] += 3
    keys["bv4"]["paragraf"] = 2
    k2 = next(m for m in json.loads((base / "zeit.json").read_text())["meetings"]
              if m["source_object"].endswith("/meetings/k2"))
    keys["rat"]["naechste_sitzung"] = {"date": k2["date"], "time": k2["time"], "web": k2["web"],
                                       "source_object": k2["source_object"]}
    g["gremien"].append({"key": "fr", "name": "[Testdaten] Probefraktion", "gruppe": "uebrige", "sitzungen_12m": 0,
                         "vorlagen_12m": 0, "source_object": f"{oparl.b}/organizations/fr"})
    g["meta"]["zeitraum"]["seit"] = "2025-01-01"
    pfad.write_text(json.dumps(g, ensure_ascii=False))
    f = next(x for x in sorted((base / "ohne-ortsbezug").glob("*.json")) + sorted((base / "ortsteile").glob("*.json"))
             if any(s.get("hinweis") for p in json.loads(x.read_text())["papers"] for s in p["process"]))
    d = json.loads(f.read_text())
    for p in d["papers"]:
        for s in p["process"]:
            s.pop("hinweis", None)
            if s.get("gremium_key") == "rat":
                s["gremium_key"] = "bv4"
    f.write_text(json.dumps(d, ensure_ascii=False))
    db = sqlite3.connect(config.DB)
    try:
        befunde, fehlend = check.gremien(db)
        b_st, _ = check.stationen(db)
    finally:
        db.close()
    assert fehlend == []
    for erwartet in ("Gremien: Felder außerhalb von gremien.FELDER: 1",
                     "Gremien: Feldnamen, die auf Personen deuten: 1",
                     "Gremien: Paragraf nicht genau bei Ausschüssen: 1",
                     "Gremien: Fraktionen und Gruppen: 1",
                     "Gremien: Zeitraum nicht 365 Tage vor dem Datenstand (gebietszahlen.window_start): 1",
                     "Gremien: nächste Sitzungen, die abgesagt sind (export.absage): 1",
                     "Gremien: Gremien zu viel (gremien.daten): 1",
                     "Gremien: Feld sitzungen_12m anders als gremien.daten: 1",
                     "Gremien: Feld paragraf anders als gremien.daten: 1",
                     "Gremien: Feld naechste_sitzung anders als gremien.daten: 1",
                     "Gremien: meta anders als gremien.daten: 1"):
        assert erwartet in befunde, (erwartet, befunde)
    assert any(x.startswith("Stationen: Feld `hinweis` folgt nicht export.hinweis_station") for x in b_st), b_st
    assert any(x.startswith("Stationen: Feld `gremium_key` folgt nicht der Organisation der Beratung") for x in b_st)
    for x in befunde + b_st:   # nur Zahlen: keine Namen, keine Kennungen
        assert "Testdaten" not in x and "Probe" not in x and oparl.b not in x and "example" not in x, x
        assert re.search(r": \d+$", x), x


def test_check_ohne_datei_nicht_durchgefuehrt(oparl, monkeypatch, capsys):
    """Mit Freigabe und Export mit Vorlagen fehlt gremien.json bzw. aemter.json: nicht durchgeführt; ohne meetings.json
    die Nachrechnung der Gremien ebenso."""
    _kette_testserver(oparl, monkeypatch)
    export.export()
    base = config.EXPORT / config.STADT
    db = sqlite3.connect(config.DB)
    try:
        config.MEETINGS.rename(config.MEETINGS.with_suffix(".weg"))
        befunde, fehlend = check.gremien(db)
        assert befunde == [] and len(fehlend) == 1 and "meetings.json fehlt" in fehlend[0]
        (base / "gremien.json").unlink()
        befunde, fehlend = check.gremien(db)
        assert befunde == [] and len(fehlend) == 1 and "gremien.json fehlt" in fehlend[0]
    finally:
        db.close()
    (base / "aemter.json").unlink()
    befunde, fehlend = check.aemter_aufbau()
    assert befunde == [] and len(fehlend) == 1 and "aemter.json fehlt" in fehlend[0]


def test_liesmich_nur_mit_freigabe(monkeypatch):
    """LIESMICH.txt des Datenpakets nennt gremien.json und aemter.json nur mit Freigabe „gremien“, vor den
    Prüfprotokollen; ohne Freigabe (und ohne Strukturdaten) der bisherige Text."""
    from pipeline import paket
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", False)
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    assert paket.liesmich() == paket.LIESMICH and "gremien.json" not in paket.LIESMICH
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", True)
    text = paket.liesmich()
    assert text == paket.LIESMICH.replace("- audit_*.tsv:", paket.LIESMICH_GREMIEN + "- audit_*.tsv:")
    assert "koeln/gremien.json" in text and "koeln/aemter.json" in text and "keine Lizenz angegeben" in text


# --- Kette mit den Testdaten -------------------------------------------------------------------------------------------

def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_testdaten_koelner_form_und_ganze_pruefung(oparl, monkeypatch, capsys):
    """tools/testdaten.py liefert Gremien in der Kölner Form (classification, ohne organizationType), eine Fraktion und
    ein aufgelöstes Gremium; die ganze Prüfung (`python -m pipeline check`) ohne Befund, mit den Zeilen der Gremien,
    Stationen und Ämter (nur Zahlen)."""
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "300"])
    _tool("testdaten").main()
    orgs = json.loads(config.ORGANIZATIONS.read_text())
    assert not any("organizationType" in o for o in orgs)
    assert sum(o.get("classification") == "Fraktionen und Gruppen" for o in orgs) == 1
    assert sum(bool(o.get("endDate")) for o in orgs) == 1
    build.build()
    capsys.readouterr()
    export.export()
    kontext.write()
    log = capsys.readouterr().out
    assert re.search(r"Gremien \(gremien\.json\): 22 Organisationen, nicht aufgenommen Fraktionen und Gruppen 1, mit "
                     r"anderer oder ohne Klasse 8; aufgenommen 13: Rat 1, Ausschüsse mit Paragraf 1, "
                     r"Bezirksvertretungen 9, übrige 2; davon aufgelöst 1; Kennungen mit Zusatz aus dem SHA-1 "
                     r"\(gleiche Kennung\) 0\n", log), log
    assert "Bezirksvertretungen mit Stadtbezirk: 9 von 9, Stadtbezirke 9 von 9" in log
    assert re.search(r"Stationen der Prozesslinie in den Gebietsdateien: (\d+), mit Sitzung \1, mit Hinweis aus dem "
                     r"Sitzungsnamen 0 \(abgesagt 0, verschoben 0\), mit Kennung des Gremiums aus gremien\.json \1\n",
                     log), log
    check.check()
    out = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    assert "\nGremien (gremien.json, Freigabe „gremien“)\ngremien.json: 13 Gremien" in out
    assert "\nÄmter (aemter.json, Freigabe „gremien“)\naemter.json: Dezernate " in out
