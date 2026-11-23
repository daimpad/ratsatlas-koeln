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
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline import aemter, ausschuesse, build, check, config, export, gebietszahlen, kontext, process, sessionnet

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
    `seit` zählt nicht, am Tag danach und am Datenstand zählt sie. Die Sitzung am Datenstand ist zugleich die nächste
    (G7, Pull Request 4b; vorher die Sitzung danach), die Sitzung nach dem Datenstand die folgende (E2).
    Vorlagen ebenso über die Stationen, jede Vorlage einmal je Gremium, abgesagte Stationen zählen nicht."""
    orgs_je = {f"{M}/{k}": [f"{O}/rat"] for k in ("a", "b", "c", "d")}
    meetings = [_sitzung("a", SEIT), _sitzung("b", "2025-11-22"), _sitzung("c", STAND), _sitzung("d", "2026-11-22")]
    zahl, naechste, folgende, ohne = gremien.sitzungen(meetings, orgs_je, {f"{O}/rat"}, {f"{O}/rat"}, SEIT, STAND)
    assert zahl[f"{O}/rat"] == 2 and naechste[f"{O}/rat"]["source_object"] == f"{M}/c" and not ohne
    assert folgende[f"{O}/rat"]["source_object"] == f"{M}/d"
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
    _, naechste, _, _ = gremien.sitzungen(meetings, orgs_je, {org}, {org}, SEIT, STAND)
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
    zahl, _, _, ohne = gremien.sitzungen(meetings, orgs_je, ids, alle, SEIT, STAND)
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
    # sitzungsliste_nicht_aktuell nur bei nicht aktueller Liste der Sitzungen (test_sitzungsliste_regel)
    assert d["meta"]["namensnennung"] == config.NAMENSNENNUNG
    assert set(d["meta"]) == set(gremien.META_FELDER) - {"sitzungsliste_nicht_aktuell"}
    log = "\n".join(gremien.zeilen_log(d, zahlen, {}))
    assert ("Gremien (gremien.json): 8 Organisationen, nicht aufgenommen Fraktionen und Gruppen 1, mit anderer oder "
            "ohne Klasse 0; aufgenommen 7: Rat 1, Ausschüsse mit Paragraf 2, Bezirksvertretungen 2, übrige 2; davon "
            "aufgelöst 1; Kennungen mit Zusatz aus dem SHA-1 (gleiche Kennung) 0\n") in log + "\n"
    # seit Entscheidung 21.11.2026 (3) (G5) mit den Nummern der Paragrafen ohne Organisation (nur Nummern), die
    # Erklärung der Zählung im Kopf der Zeile (Nachprüfung)
    assert ("Einträge; gezählt nicht aufgelöste Organisationen der Klasse „Fachausschüsse und weitere Gremien“): mit "
            "genau einer Organisation 2, ohne Organisation 15 (§§ 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, "
            "22, 23), mit mehr als einer Organisation 0\n") in log + "\n"
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


def _kette_testserver(oparl, monkeypatch, vorher=None):
    """Testserver mit Gremien in der Kölner Form, einer Fraktion (nicht aufgenommen) und einem aufgelösten Ausschuss
    (aufgenommen, gekennzeichnet); Sitzungen
    des Rates in den kommenden Tagen (abgesagt laut OParl, abgesagt laut Namen, verschoben, ohne Hinweis) und eine
    Sitzung der Fraktion; je Sitzung eine Vorlage mit Beratung. `vorher(oparl)`: weitere erfundene Daten vor dem
    Abruf."""
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
    if vorher:
        vorher(oparl)
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
            "„gremien“ kein Feld): 1",
            # seit E1: Der Schritt dieser Station trägt die eingeschleuste Kennung nicht
            "Schritte: Feld `gremium_key` anders als an der Station des Schritts in process[] (fehlt, zu viel oder "
            "anderer Wert): 1"]
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
                     r"Sitzungsnamen 0 \(abgesagt 0, verschoben 0\), mit Kennung des Gremiums aus gremien\.json \1, "
                     r"Stationen aufgelöster Gremien aus gremien\.json \(ohne Kennung\) 0\n", log), log
    check.check()
    out = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in out
    assert "\nGremien (gremien.json, Freigabe „gremien“)\ngremien.json: 13 Gremien" in out
    assert "\nÄmter (aemter.json, Freigabe „gremien“)\naemter.json: Dezernate " in out


# --- Nachprüfung von Pull Request 4a ----------------------------------------------------------------------------------

def test_kennung_aendert_sich_bei_gleicher_rohkennung():
    """Die Kennung bleibt nur gleich, solange keine weitere Organisation dieselbe Kennung ergibt: Kommt eine hinzu,
    erhalten beide den Zusatz (Modulbeschreibung, Nachprüfung 4a)."""
    vorher = gremien.schluessel([f"{O}/gr/1"])
    nachher = gremien.schluessel([f"{O}/gr/1", f"{O}/GR-1"])
    assert vorher[f"{O}/gr/1"] == "gr-1"
    assert re.fullmatch(r"gr-1-[0-9a-f]{8}", nachher[f"{O}/gr/1"]) and nachher[f"{O}/gr/1"] != nachher[f"{O}/GR-1"]
    assert "behält und keine weitere Organisation der Tabelle dieselbe Kennung ergibt" in gremien.__doc__


def test_aus_der_satzung_nur_der_paragraf():
    """Aus der Zuständigkeitsordnung stammt nur der Paragraf: Der Name im Eintrag ist der Name der Organisation in der
    OParl-API, auch wenn die Satzung den Ausschuss anders schreibt; Hinweis in meta, LICENSE-DATA.md und README sagen
    das so (Nachprüfung 4a: sie nannten auch die Namen der Ausschüsse)."""
    satzung = PARAGRAF[19]
    oparl_name = "Ausschuss für Schule und Weiterbildung"   # Schreibung mit „für“, wie die Überschrift des § 19
    assert oparl_name != satzung and ausschuesse.abschnitt(oparl_name) == 19
    d, _ = gremien.daten([_org("probe1", oparl_name, AUSSCHUSS)], [], {}, [], STAND, [])
    (e,) = d["gremien"]
    assert e["name"] == oparl_name and e["paragraf"] == 19 and e["gruppe"] == "ausschuss"
    hinweis = d["meta"]["zustaendigkeitsordnung"]["hinweis"]
    assert hinweis == gremien.HINWEIS_ZUSTO and "nur der Paragraf" in hinweis and "stammt aus der OParl-API" in hinweis
    assert "Namen der Ausschüsse" not in hinweis
    zeile = next(z for z in (ROOT / "data" / "LICENSE-DATA.md").read_text(encoding="utf-8").splitlines()
                 if z.startswith("| `export/koeln/gremien.json`"))
    assert "nur die Paragrafennummer" in zeile and "Namen der Ausschüsse" not in zeile
    assert "Namen und Paragrafen" not in zeile


def test_zustaendigkeitsordnung_in_den_quellenangaben(monkeypatch):
    """Die Zuständigkeitsordnung steht als Quelle in README (Tabelle „Quellen und Lizenzen“) und, mit Freigabe
    „gremien“, auf der Technikseite (technikseite.weitere_quellen, Adresse aus ausschuesse.QUELLE); beim Plan nennen
    beide auch aemter.json (Nachprüfung 4a). Ohne Freigabe fehlen Eintrag und Zusatz auf der Technikseite."""
    from pipeline import technikseite
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    tabelle = readme.split("## Quellen und Lizenzen", 1)[1].split("\n## ", 1)[0]
    zeile = next(z for z in tabelle.splitlines() if z.startswith("| Zuständigkeitsordnung"))
    assert ausschuesse.QUELLE["titel"] in zeile and "Lizenz nicht geklärt" in zeile and "gremien.json" in zeile
    assert "aemter.json" in next(z for z in tabelle.splitlines() if "Dezernatsverteilungsplan" in z)
    je = {e[0]: e for e in technikseite.weitere_quellen()}
    assert set(je) == {"q-aemter", "q-zustaendigkeitsordnung"}
    assert je["q-zustaendigkeitsordnung"][3] == ausschuesse.QUELLE["url"]
    assert "Lizenz der Satzung ist nicht geklärt" in je["q-zustaendigkeitsordnung"][2]
    assert "aemter.json" in je["q-aemter"][2]
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    je = {e[0]: e for e in technikseite.weitere_quellen()}
    assert set(je) == {"q-aemter"} and "aemter.json" not in je["q-aemter"][2]


def test_dcat_nennt_teile_ohne_geklaerte_lizenz(tmp_path):
    """DCAT: Die Verteilung „Gremien (JSON)“ nennt im Rechtehinweis die Zuständigkeitsordnung als Teil ohne geklärte
    Lizenz, das Datenpaket den Geschäfts- und Dezernatsverteilungsplan und, mit gremien.json, auch die
    Zuständigkeitsordnung; beide mit dem Vermerk, dass die Lizenzangabe der Verteilung für sie nicht gilt. Die Lizenz
    der Verteilungen bleibt die der übrigen Teile (Nachprüfung 4a)."""
    from pipeline import aemter, publish

    def verteilungen():
        publish.write_dcat(tmp_path / "dcat.jsonld", None, STAND, orte=set())
        dcat = json.loads((tmp_path / "dcat.jsonld").read_text(encoding="utf-8"))
        return {d["dct:title"]["@value"]: d for d in dcat["dcat:distribution"]}

    vermerk = "ohne geklärte Lizenz (die Lizenzangabe dieser Verteilung gilt für diese Teile nicht)"
    je = verteilungen()
    assert "Gremien (JSON)" not in je
    paket = je["Datenpaket (Zip)"]["dct:rights"]["rdfs:label"]
    assert vermerk in paket and aemter.TITEL in paket and aemter.namensnennung() in paket
    assert ausschuesse.QUELLE["titel"] not in paket
    (tmp_path / "gremien.json").write_text("{}")
    je = verteilungen()
    gr = je["Gremien (JSON)"]
    recht = gr["dct:rights"]["rdfs:label"]
    assert gr["dct:license"]["@id"] == publish.LICENCE["dl-de-zero"]
    assert vermerk in recht and f"Namensnennung: {ausschuesse.QUELLE['titel']}" in recht and "Lizenz nicht geklärt" in recht
    assert config.NAMENSNENNUNG in recht and aemter.TITEL not in recht
    assert recht.index(vermerk) > recht.index(config.NAMENSNENNUNG)   # nach den Teilen mit Lizenz
    paket = je["Datenpaket (Zip)"]["dct:rights"]["rdfs:label"]
    assert ausschuesse.QUELLE["titel"] in paket and aemter.TITEL in paket
    # Verteilungen ohne solche Teile bleiben ohne Vermerk
    assert vermerk not in je["Typische Wege je Vorlagenart (JSON)"]["dct:rights"]["rdfs:label"]


def test_log_sitzungen_ohne_organisation_und_vorlagen_ausserhalb():
    """Log (nur Zahlen): Sitzungen ab dem Datenstand ohne Verweis auf eine Organisation (ohne Absage), davon mit
    Gremium aus dem Sitzungsnamen gleich dem Namen genau eines Gremiums der Datei; Sitzungen am Datenstand (seit G7
    kommend) und Gremien mit nächster Sitzung am Datenstand, davon mit folgender Sitzung (E2); Vorlagen in keiner
    Gebietsdatei mit Beratung im Zeitraum. Diese zählen weiter für kein Gremium (Nachprüfung 4a)."""
    orgs = [_org("gr/1", "[Testdaten] Probeausschuss", AUSSCHUSS), _org("rat", "Rat", "Rat"),
            _org("doppelt1", "[Testdaten] Probebeirat", AUSSCHUSS), _org("doppelt2", "[Testdaten] Probebeirat", AUSSCHUSS)]
    meetings = [{**_sitzung("o1", "2026-11-25"), "gremium": "[Testdaten] Probeausschuss"},   # ohne Organisation
                {**_sitzung("o2", "2026-11-26"), "gremium": "[Testdaten] Probebeirat"},     # Name zweimal vergeben
                {**_sitzung("o3", "2026-11-27"), "gremium": "[Testdaten] Probebeirat - Sondersitzung"},
                {**_sitzung("o4", "2026-11-28", hinweis="abgesagt"), "gremium": "[Testdaten] Probeausschuss"},
                {**_sitzung("o5", "2026-10-01"), "gremium": "[Testdaten] Probeausschuss"},   # vergangen
                _sitzung("m1", "2027-01-20"), _sitzung("m2", STAND), _sitzung("m3", STAND, cancelled=True)]
    orgs_je = {f"{M}/m1": [f"{O}/gr/1"], f"{M}/m2": [f"{O}/rat"], f"{M}/m3": [f"{O}/rat"], f"{M}/o2": []}
    station = {"meeting_id": f"{M}/m2", "start_date": f"{STAND}T17:00:00+01:00", "cancelled": 0, "gremium_key": "rat"}
    ausserhalb = [{"process": [station]}, {"process": [{**station, "start_date": "2025-01-01T17:00:00+01:00"}]}]
    d, zahlen = gremien.daten(orgs, meetings, orgs_je, [], STAND, [], ausserhalb=ausserhalb)
    keys = {e["key"]: e for e in d["gremien"]}
    assert keys["gr-1"]["naechste_sitzung"]["source_object"] == f"{M}/m1"   # die Sitzung o1 zählt weiter nicht
    assert keys["rat"]["sitzungen_12m"] == 1 and keys["rat"]["vorlagen_12m"] == 0
    # seit G7 ist die Sitzung am Datenstand die nächste; eine spätere Sitzung des Rates gibt es nicht
    assert keys["rat"]["naechste_sitzung"]["source_object"] == f"{M}/m2" and "folgende_sitzung" not in keys["rat"]
    assert zahlen["ohne_organisation_kommend"] == (3, 1) and zahlen["am_datenstand"] == 1
    assert zahlen["naechste_am_datenstand"] == 1 and zahlen["mit_folgender"] == 0
    assert zahlen["vorlagen_ausserhalb"] == 1
    log = "\n".join(gremien.zeilen_log(d, zahlen, {}))
    assert ("Sitzungen ab dem Datenstand ohne Verweis auf eine Organisation (ohne Absage; zählen für kein Gremium, "
            "auch nicht als nächste oder folgende Sitzung): 3, davon mit Gremium aus dem Sitzungsnamen gleich dem "
            "Namen genau eines Gremiums aus gremien.json 1; Sitzungen von Gremien aus gremien.json am Datenstand (ohne "
            "Absage; zählen als kommend): 1; Gremien mit nächster Sitzung am Datenstand 1, davon mit folgender "
            "Sitzung 0") in log
    assert "Vorlagen in keiner Gebietsdatei mit Beratung eines Gremiums aus gremien.json im Zeitraum (zählen nicht bei " \
           "vorlagen_12m): 1" in log
    assert "Probe" not in log and O not in log and M not in log and "Liste der Sitzungen" not in log


def test_sitzung_am_datenstand_gilt_als_kommend_auch_im_sommer():
    """Entscheidung 21.11.2026 (3) (G7), umgesetzt mit Pull Request 4b: Sitzungen am Tag des Datenstands zählen als
    kommend wie in „Aktuell in Köln“ (bis dahin als vergangen; der Test hieß
    test_sitzung_am_datenstand_gilt_als_vergangen_auch_im_sommer). Im Sommer beginnt der Lauf um 0:10 Uhr Kölner Zeit;
    der Datenstand ist dann der gerade begonnene Tag, und die Sitzung am Abend dieses Tages ist die nächste Sitzung, die
    spätere die folgende (E2); bei sitzungen_12m zählt die Sitzung am Datenstand weiter (F7). Die Modulbeschreibung
    nennt die Regel nicht mehr als offen (erfundene Daten)."""
    stand = export.kalendertag_des_abrufs("2027-07-01T22:15:00Z")
    assert stand == "2027-07-02"
    assert export.kalendertag_des_abrufs("2026-12-01T22:15:00Z") == "2026-12-01"   # Winter: Abend des Laufs
    org = f"{O}/probe"
    meetings = [_sitzung("abend", stand, time="17:00"), _sitzung("spaeter", "2027-07-20")]
    orgs_je = {m["source_object"]: [org] for m in meetings}
    zahl, naechste, folgende, _ = gremien.sitzungen(meetings, orgs_je, {org}, {org}, gebietszahlen.window_start(stand),
                                                     stand)
    assert zahl[org] == 1 and naechste[org]["source_object"] == f"{M}/abend"
    assert folgende[org]["source_object"] == f"{M}/spaeter"
    doc = " ".join(gremien.__doc__.split())
    assert "Im Sommer beginnt der Lauf um 0:10 Uhr Kölner Zeit" in doc and "beim Auftraggeber offen (TECHNIK" not in doc
    assert "Sitzungen am Tag des Datenstands zählen als kommend" in doc


def test_sitzungsliste_regel(monkeypatch):
    """export.sitzungsliste_aktuell: nicht aktuell bei Warnung oder Aussetzen der Sitzungen oder Fehler des Abrufs;
    gremien.sitzungsliste nennt dann den Stand der Liste; gremien.daten ohne nächste Sitzung, mit
    meta.sitzungsliste_nicht_aktuell (Nachprüfung 4a)."""
    alt = "2026-11-10T22:30:00+00:00"
    warnung = {"meetings": alt, "abruf_warnungen": {"meetings": {"zeit": "2026-11-21T22:20:00+00:00",
                                                                "meldung": "nicht aktualisiert"}}}
    ausgesetzt = {"meetings": alt, "abruf_ausgesetzt": {"meetings": {"seit": "2026-11-21T22:20:00+00:00"}}}
    fehler = {"meetings": alt, "abruf_fehler": {"zeit": "2026-11-21T22:20:00+00:00", "meldung": "Abbruch"}}
    nur_vorlagen = {"meetings": alt, "abruf_ausgesetzt": {"papers": {"seit": "2026-11-21T22:20:00+00:00"}}}
    assert export.sitzungsliste_aktuell({}) and export.sitzungsliste_aktuell(nur_vorlagen)
    for stand in (warnung, ausgesetzt, fehler):
        assert not export.sitzungsliste_aktuell(stand)
        assert gremien.sitzungsliste(stand) == {"stand": alt, "hinweis": gremien.HINWEIS_SITZUNGSLISTE}
    assert gremien.sitzungsliste({}) is None and gremien.sitzungsliste(nur_vorlagen) is None
    org = f"{O}/bv4"
    meetings = [_sitzung("v", "2026-10-01"), _sitzung("k", "2026-12-01")]
    orgs_je = {m["source_object"]: [org] for m in meetings}
    o = [_org("bv4", "Bezirksvertretung 4 (Ehrenfeld)", "Bezirksvertretungen")]
    d, _ = gremien.daten(o, meetings, orgs_je, [], STAND, [])
    assert "naechste_sitzung" in d["gremien"][0] and "sitzungsliste_nicht_aktuell" not in d["meta"]
    d, zahlen = gremien.daten(o, meetings, orgs_je, [], STAND, [], gremien.sitzungsliste(warnung))
    assert "naechste_sitzung" not in d["gremien"][0] and d["gremien"][0]["sitzungen_12m"] == 1
    assert d["meta"]["sitzungsliste_nicht_aktuell"]["stand"] == alt and set(d["meta"]) <= set(gremien.META_FELDER)
    assert gremien.zeilen_log(d, zahlen, {})[-1] == \
        "Liste der Sitzungen beim letzten Abruf nicht aktualisiert: keine nächste Sitzung in gremien.json"


def test_kette_sitzungsliste_nicht_aktuell(oparl, monkeypatch, capsys):
    """Kette mit dem Testserver und einer Warnung zu den Sitzungen in STAND.json: gremien.json ohne nächste Sitzung,
    mit dem Stand der Liste in meta, „Aktuell in Köln“ ohne Sitzungen (dieselbe Regel); check ohne Befund, eine
    eingeschleuste nächste Sitzung ist ein Befund (nur Zahlen)."""
    _kette_testserver(oparl, monkeypatch)
    stand = json.loads(config.STAND.read_text())
    stand["abruf_warnungen"] = {"meetings": {"zeit": "2099-01-01T00:00:00+00:00", "meldung": "nicht aktualisiert"}}
    config.STAND.write_text(json.dumps(stand))
    capsys.readouterr()
    export.export()
    log = capsys.readouterr().out
    base = config.EXPORT / config.STADT
    g = json.loads((base / "gremien.json").read_text())
    assert not any("naechste_sitzung" in e for e in g["gremien"])
    assert g["meta"]["sitzungsliste_nicht_aktuell"] == {"stand": stand.get("meetings"),
                                                        "hinweis": gremien.HINWEIS_SITZUNGSLISTE}
    assert "sitzungen" not in (json.loads((base / "index.json").read_text()).get("aktuell") or {})
    assert "Liste der Sitzungen beim letzten Abruf nicht aktualisiert: keine nächste Sitzung in gremien.json" in log
    db = sqlite3.connect(config.DB)
    try:
        assert check.gremien(db) == ([], [])
        zeit = json.loads((base / "zeit.json").read_text())["meetings"]
        k4 = next(m for m in zeit if m["source_object"].endswith("/meetings/k4"))
        for e in g["gremien"]:
            if e["key"] == "rat":
                e["naechste_sitzung"] = {"date": k4["date"], "time": k4["time"], "web": k4["web"],
                                         "source_object": k4["source_object"]}
        (base / "gremien.json").write_text(json.dumps(g, ensure_ascii=False))
        befunde, _ = check.gremien(db)
    finally:
        db.close()
    assert "Gremien: nächste Sitzungen bei nicht aktueller Liste der Sitzungen (gremien.sitzungsliste): 1" in befunde
    assert "Gremien: Feld naechste_sitzung anders als gremien.daten: 1" in befunde
    for x in befunde:
        assert "Testdaten" not in x and oparl.b not in x and re.search(r": \d+$", x), x


# --- Entscheidung 21.11.2026 (3): (G4) Kennungen in suche.json, (G5) Paragrafen im Log, (G6) aufgelöste Gremien ------

def _suche(base):
    return json.loads((base / "suche.json").read_text())


def _zeile(suche, ref):
    (r,) = [r for r in suche["rows"] if r[0] == ref]
    return r


def _kennungen_je_drucksache(base):
    """Kennungen an den Stationen je Drucksache aus den Gebietsdateien (jede Vorlage einmal)."""
    aus = {}
    for d in ("ortsteile", "bezirke", "ohne-ortsbezug"):
        for f in sorted((base / d).glob("*.json")):
            for p in json.loads(f.read_text())["papers"]:
                aus[p["reference"]] = sorted({s["gremium_key"] for s in p["process"] if s.get("gremium_key")})
    return aus


def test_suche_kennungen_der_gremien_und_freigabe_aus(oparl, monkeypatch, capsys):
    """(G4) suche.json führt mit Freigabe die Liste `gremium_keys` (nur Kennungen aus gremien.json) und je Zeile die
    Spalte export.SUCHE_SPALTE_KENNUNGEN mit den Kennungen an den Stationen der Vorlage; die Spalten 0–10 bleiben
    unverändert. Ohne Freigabe weder Liste noch Spalte (wie vor G4); check.suche_gremien ohne Befund, eine Liste ohne
    Freigabe ist ein Befund (nur Zahlen)."""
    _kette_testserver(oparl, monkeypatch)
    export.export()
    base = config.EXPORT / config.STADT
    s = _suche(base)
    spalte = export.SUCHE_SPALTE_KENNUNGEN
    assert spalte == 11 and all(len(r) == 12 for r in s["rows"])
    keys_in_datei = {e["key"] for e in json.loads((base / "gremien.json").read_text())["gremien"]}
    assert s["gremium_keys"] == ["bv4", "rat"] and set(s["gremium_keys"]) <= keys_in_datei
    stationen = _kennungen_je_drucksache(base)
    for r in s["rows"]:
        assert [s["gremium_keys"][i] for i in r[spalte]] == stationen[r[0]], r[0]
        assert r[spalte] == sorted(set(r[spalte]))
    # die Fraktion (Sitzung k5) steht nicht in gremien.json: ihre Vorlage hat keine Kennung, behält aber den Namen
    fr = _zeile(s, "1105/2026")
    assert fr[spalte] == [] and fr[10] and s["meta"]["note"] == export.SUCHE_NOTE + export.SUCHE_NOTE_KENNUNGEN
    assert list(s)[-2:] == ["gremium_keys", "rows"]
    mit = s
    db = sqlite3.connect(config.DB)
    try:
        assert check.suche_gremien(db) == ([], [])
        monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
        export.export()
        ohne = _suche(base)
        assert "gremium_keys" not in ohne and all(len(r) == 11 for r in ohne["rows"])
        assert ohne["meta"]["note"] == export.SUCHE_NOTE
        assert [r[:spalte] for r in mit["rows"]] == ohne["rows"]
        assert {k: v for k, v in mit.items() if k not in ("gremium_keys", "rows", "meta")} == \
            {k: v for k, v in ohne.items() if k not in ("rows", "meta")}
        capsys.readouterr()
        assert check.suche_gremien(db) == ([], [])
        assert "abgeschaltet (config.ZUSATZTHEMEN) – keine Kennungen erwartet" in capsys.readouterr().out
        # eine Liste und eine Spalte ohne Freigabe: Befund mit Zahl
        (base / "suche.json").write_text(json.dumps(mit, ensure_ascii=False))
        assert check.suche_gremien(db)[0] == [
            f"Suche: Kennungen der Gremien in suche.json, obwohl die Freigabe „gremien“ aus ist: {1 + len(mit['rows'])}"]
    finally:
        db.close()


def _alt_mit_beratung(oparl):
    """Der aufgelöste Probeausschuss (erfunden) endet vor 10 Tagen; 30 Tage vorher hatte er eine Sitzung, in der eine
    erfundene Vorlage beraten wurde, die danach auch der Rat berät (Sitzung k4)."""
    b = oparl.b
    heute = date.today()
    alt = next(o for o in oparl.orgs if o["id"] == f"{b}/organizations/alt")
    alt["endDate"] = (heute - timedelta(days=10)).isoformat()
    tag = (heute - timedelta(days=30)).isoformat()
    oparl.meetings.append({"id": f"{b}/meetings/k6", "type": "https://schema.oparl.org/1.1/Meeting",
                           "name": "[Testdaten] Probeausschuss", "start": f"{tag}T17:00:00+01:00", "cancelled": False,
                           "organization": [f"{b}/organizations/alt"], "modified": "2026-11-01T08:00:00+01:00",
                           "agendaItem": [{"id": f"{b}/agendaitems/k6", "number": "1", "name": "TOP", "public": True}]})
    p = oparl.paper(106, name="[Testdaten] Probevorlage 6")
    p["consultation"] = [{"id": f"{b}/consultations/k6", "meeting": f"{b}/meetings/k6",
                          "agendaItem": f"{b}/agendaitems/k6", "role": "Vorberatung", "authoritative": False},
                         {"id": f"{b}/consultations/k6r", "meeting": f"{b}/meetings/k4",
                          "agendaItem": f"{b}/agendaitems/k4", "role": "Entscheidung", "authoritative": True}]
    oparl.papers.append(p)


def test_kennungen_ohne_aufgeloeste_und_zaehlung_ueber_die_beratung():
    """(G6) gremien.kennungen mit Datenstand ohne aufgelöste Gremien (die Kennung selbst bleibt gleich); vorlagen_12m
    zählt ein aufgelöstes Gremium über die Organisation der Beratung (gremien.beratungen), auch ohne Kennung an der
    Station; ohne diese Angabe nur über `gremium_key`."""
    orgs = [_org("rat", "Rat", "Rat"), _org("alt", "[Testdaten] Probeausschuss", AUSSCHUSS, ende="2026-11-11"),
            _org("fr", "[Testdaten] Probefraktion", "Fraktionen und Gruppen")]
    assert gremien.kennungen(orgs) == {f"{O}/rat": "rat", f"{O}/alt": "alt"}
    assert gremien.kennungen(orgs, STAND) == {f"{O}/rat": "rat"}
    assert gremien.kennungen(orgs, "2026-11-11") == {f"{O}/rat": "rat", f"{O}/alt": "alt"}
    station = {"position": 0, "meeting_id": f"{M}/a", "start_date": "2026-10-01T17:00:00+02:00", "cancelled": 0}
    papers = [{"source_object": "https://example.invalid/oparl/papers/1", "process": [station]}]
    beratungen = {("https://example.invalid/oparl/papers/1", 0): f"{O}/alt"}
    d, _ = gremien.daten(orgs, [], {}, papers, STAND, [], beratungen_je=beratungen)
    alt = next(e for e in d["gremien"] if e["key"] == "alt")
    assert alt["aufgeloest"] is True and alt["vorlagen_12m"] == 1
    d, _ = gremien.daten(orgs, [], {}, papers, STAND, [])
    assert next(e for e in d["gremien"] if e["key"] == "alt")["vorlagen_12m"] == 0


def test_aufgeloestes_gremium_ohne_kennung_an_stationen_und_in_suche(oparl, monkeypatch, capsys):
    """(G6) Die Station in der Sitzung eines aufgelösten Gremiums trägt keine Kennung, die Station des Rates derselben
    Vorlage schon; in suche.json fehlt die Kennung des aufgelösten Gremiums; gremien.json zählt seine Sitzung und
    Vorlage in 12 Monaten weiter; das Log von export und die Ausgabe von check zählen die Stationen aufgelöster
    Gremien; check ohne Befund."""
    _kette_testserver(oparl, monkeypatch, _alt_mit_beratung)
    capsys.readouterr()
    export.export()
    log = capsys.readouterr().out
    base = config.EXPORT / config.STADT
    st = _stationen(base)
    assert "gremium_key" not in st["k6"] and st["k6"]["gremium"] == "[Testdaten] Probeausschuss"
    g = {e["key"]: e for e in json.loads((base / "gremien.json").read_text())["gremien"]}
    assert g["alt"]["aufgeloest"] is True and g["alt"]["sitzungen_12m"] == 1 and g["alt"]["vorlagen_12m"] == 1
    s = _suche(base)
    assert "alt" not in s["gremium_keys"]
    assert [s["gremium_keys"][i] for i in _zeile(s, "AN/206/2026")[export.SUCHE_SPALTE_KENNUNGEN]] == ["rat"]
    assert ("mit Kennung des Gremiums aus gremien.json 10, Stationen aufgelöster Gremien aus gremien.json (ohne "
            "Kennung) 1\n") in log
    db = sqlite3.connect(config.DB)
    try:
        capsys.readouterr()
        assert check.gremien(db) == ([], []) and check.stationen(db) == ([], [])
        assert check.suche_gremien(db) == ([], [])
        out = capsys.readouterr().out
        assert "mit Kennung des Gremiums 10, Stationen aufgelöster Gremien (ohne Kennung) 1\n" in out
    finally:
        db.close()


def test_check_meldet_falsche_kennungen_in_suche_und_aufgeloeste_an_stationen(oparl, monkeypatch):
    """check.suche_gremien meldet eingeschleuste Kennungen in suche.json (eine ohne Eintrag in gremien.json, eine eines
    aufgelösten Gremiums, ein Verweis außerhalb der Liste) und check.stationen die Kennung eines aufgelösten Gremiums an
    einer Station; Befunde nur mit Zahlen."""
    _kette_testserver(oparl, monkeypatch, _alt_mit_beratung)
    export.export()
    base = config.EXPORT / config.STADT
    s = _suche(base)
    spalte = export.SUCHE_SPALTE_KENNUNGEN
    alt_liste = s["gremium_keys"]
    neu = sorted(alt_liste + ["alt", "gibt-es-nicht"])
    for r in s["rows"]:
        r[spalte] = [neu.index(alt_liste[i]) for i in r[spalte]]
    s["gremium_keys"] = neu
    _zeile(s, "AN/206/2026")[spalte] = sorted([neu.index("alt"), neu.index("rat")])   # aufgelöst
    _zeile(s, "1101/2026")[spalte] = [neu.index("gibt-es-nicht")]                      # ohne Eintrag
    _zeile(s, "AN/202/2026")[spalte] = [99]                                            # außerhalb der Liste
    (base / "suche.json").write_text(json.dumps(s, ensure_ascii=False))
    f = next(x for x in sorted((base / "ohne-ortsbezug").glob("*.json"))
             if any((st.get("meeting_id") or "").endswith("/meetings/k6") for p in json.loads(x.read_text())["papers"]
                    for st in p["process"]))
    d = json.loads(f.read_text())
    for p in d["papers"]:
        for st in p["process"]:
            if (st.get("meeting_id") or "").endswith("/meetings/k6"):
                st["gremium_key"] = "alt"
    f.write_text(json.dumps(d, ensure_ascii=False))
    db = sqlite3.connect(config.DB)
    try:
        b_suche, fehlend = check.suche_gremien(db)
        b_st, _ = check.stationen(db)
    finally:
        db.close()
    assert fehlend == []
    assert sorted(b_suche) == sorted([
        "Suche: Zeilen mit ungültigem Verweis auf gremium_keys: 1",
        "Suche: Kennungen ohne Eintrag in gremien.json: 1",
        "Suche: Kennungen aufgelöster Gremien aus gremien.json: 1",
        "Suche: Zeilen, deren Kennungen nicht den Organisationen der Beratungen folgen (gremien.kennungen): 3",
        "Suche: Zeilen mit anderen Kennungen als an den Stationen der Vorlage: 2"]), b_suche
    assert "Stationen: Kennung eines aufgelösten Gremiums aus gremien.json: 1" in b_st
    assert any(x.startswith("Stationen: Feld `gremium_key` folgt nicht der Organisation der Beratung") for x in b_st)
    for x in b_suche + b_st:   # nur Zahlen: keine Namen, keine Kennungen, keine Drucksachen
        assert "Testdaten" not in x and "Probe" not in x and oparl.b not in x and "gibt-es-nicht" not in x, x
        assert "/2026" not in x and re.search(r": \d+$", x), x


def test_log_nennt_paragrafen_ohne_und_mit_mehreren_organisationen():
    """(G5) Die Zeile zu den Ausschüssen nennt die Nummern der Paragrafen ohne Organisation und mit mehr als einer
    (aufsteigend, nur Nummern); ein aufgelöstes Gremium zählt nicht; ohne solche Paragrafen keine Klammer. Die Erklärung
    der Zählung steht im Kopf der Zeile, nicht als zweite Klammer hinter der letzten Zahl (Nachprüfung)."""
    orgs = [_org("h", PARAGRAF[7], AUSSCHUSS), _org("s1", PARAGRAF[19], AUSSCHUSS), _org("s2", PARAGRAF[19], AUSSCHUSS),
            _org("f-alt", PARAGRAF[11], AUSSCHUSS, ende="2025-10-31")]
    d, zahlen = gremien.daten(orgs, [], {}, [], STAND, [])
    zeilen = gremien.zeilen_log(d, zahlen, {})
    assert ("Ausschüsse laut Zuständigkeitsordnung (ausschuesse.AUSSCHUESSE, 17 Einträge; gezählt nicht aufgelöste "
            "Organisationen der Klasse „Fachausschüsse und weitere Gremien“): mit genau einer Organisation 1, ohne "
            "Organisation 15 (§§ 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 21, 22, 23), mit mehr als einer "
            "Organisation 1 (§ 19)") in zeilen
    alle = [_org(f"a{nr}", name, AUSSCHUSS) for nr, name in PARAGRAF.items() if nr != 23]
    d, zahlen = gremien.daten(alle, [], {}, [], STAND, [])
    zeilen += gremien.zeilen_log(d, zahlen, {})
    assert any(z.endswith("mit genau einer Organisation 16, ohne Organisation 1 (§ 23), mit mehr als einer "
                          "Organisation 0") for z in zeilen)
    ausschuesse_zeilen = [z for z in zeilen if z.startswith("Ausschüsse laut Zuständigkeitsordnung")]
    assert len(ausschuesse_zeilen) == 2 and not any(") (" in z for z in ausschuesse_zeilen), ausschuesse_zeilen
    assert all("Probe" not in z and O not in z for z in zeilen)


def test_anfrage_punkt_7_nennt_alles_aus_plan_und_satzung():
    """Nachprüfung zu (G2), (G3): Punkt 7 der Anfrage an die Stadt nennt alles, was das Repository aus dem Plan und
    der Zuständigkeitsordnung enthält: Stand des jüngsten Plans, die vom Projekt gebildete Kennung, die vollständige
    Tabelle mit den Untereinheiten (data/aemter/aemter_koeln.tsv, solange sie welche hat) und ihren Zweck, das Datum der
    Satzung, den Paragrafen in gremien.json und die Namen der Ausschüsse im Quellcode (ausschuesse.AUSSCHUESSE)."""
    text = (ROOT / "explore" / "ANFRAGE_stadt_koeln.md").read_text(encoding="utf-8")
    assert "Offen sind noch acht Punkte:" in text
    punkt = re.search(r"^7\. \*\*Geschäfts- und Dezernatsverteilungsplan und Zuständigkeitsordnung:\*\* (.+)$", text,
                      re.M)
    assert punkt, "Punkt 7 fehlt"
    p7 = punkt.group(1)
    plan = aemter.tabelle().neuester()
    assert f"(Stand {'.'.join(reversed(plan.stand.split('-')))})" in p7
    assert "aus Dezernat und Nummer bilde (etwa „VI/61“) und die keine Schreibweise des Plans ist" in p7
    if any(z["ebene"] == "untereinheit" for z in plan.zeilen):
        assert "vollständige Tabelle der Dezernate und Dienststellen mit ihren Untereinheiten" in p7
        assert "federführende Dienststelle einer Vorlage ihrem Dezernat zu" in p7
    assert p7.index("Untereinheiten") < p7.index("Namen von Personen übernehme ich nicht")
    assert f"Zuständigkeitsordnung vom {'.'.join(reversed(ausschuesse.QUELLE['stand'].split('-')))}" in p7
    assert "je Ausschuss nur die Nummer seines Paragrafen" in p7
    assert f"Namen der {len(ausschuesse.AUSSCHUESSE)} Ausschüsse mit ihrem Paragrafen" in p7
    assert "andere Schreibungen derselben Ausschüsse aus der Satzung" in p7
    assert "Veröffentlichungen" not in p7 and "zwei Dokumenten der Stadt" in p7


# --- Entscheidung 23.11.2026 (1), Pull Request 4b (Pipeline): (E1) Schritte, (G7, E2) nächste und folgende Sitzung ---

def _station_voll(tag, gremium, **felder):
    """Erfundene Station der Prozesslinie in der Form der Gebietsdateien (ohne Sitzung, wenn `tag` None ist)."""
    return {"position": 0, "role": "Beratung", "authoritative": False,
            "meeting_id": f"{M}/{tag}" if tag else None, "gremium": gremium,
            "meeting": f"[Testdaten] {gremium}" if tag else None,
            "start_date": f"{tag}T17:00:00+01:00" if tag else None, "cancelled": 0, "number": "1" if tag else None,
            "result": None, "public": 1, "status": "terminiert", **felder}


def _vorlage_mit_stationen():
    """Erfundene Vorlage: drei Stationen in der Beratungsfolge, deren Tage nicht aufsteigen (process.steps ordnet die
    Schritte nach Datum), eine Station ohne Sitzung und eine Folgevorlage."""
    return {"paper_type": "[Testdaten] Probeart", "source_object": "https://example.invalid/oparl/papers/1",
            "originators": [], "date": "2026-10-01", "subordinated": [
                {"reference": "9002/2026", "paper_type": "[Testdaten] Probeart", "name": "[Testdaten] Folge",
                 "date": "2026-12-01"}],
            "process": [_station_voll("2026-11-10", "Rat", hinweis="abgesagt", gremium_key="rat"),
                        _station_voll("2026-10-05", "Bezirksvertretung 1 (Innenstadt)", gremium_key="bv1"),
                        _station_voll("2026-10-20", "[Testdaten] Probebeirat", hinweis="verschoben"),
                        _station_voll(None, "[Testdaten] Probeausschuss")]}


def test_schritte_tragen_hinweis_und_kennung_ihrer_station():
    """(E1) Jeder Schritt aus einer Station trägt `hinweis` und `gremium_key` mit dem Wert seiner Station, am Ende des
    Schritts; fehlt der Wert an der Station, fehlt das Feld; Schritte, die nicht aus einer Station stammen, tragen
    keines der beiden Felder. process.stationen_der_schritte nennt je Schritt die Stelle seiner Station (die Schritte
    stehen nach Datum, nicht in der Reihenfolge der Beratungsfolge)."""
    p = _vorlage_mit_stationen()
    schritte = process.steps(p)
    stellen = process.stationen_der_schritte(p)
    assert len(stellen) == len(schritte)
    # nach Datum; die Station ohne Sitzung folgt der vorigen Station der Beratungsfolge (Stelle 2)
    assert [stellen[i] for i, s in enumerate(schritte) if s["typ"] in ("beratung", "entscheidung")] == [1, 2, 3, 0]
    for s, i in zip(schritte, stellen):
        station = p["process"][i] if i is not None else {}
        for f in process.FELDER_AUS_STATION:
            assert (f in s, s.get(f)) == (f in station, station.get(f)), (s["typ"], f)
        if i is not None:
            assert s["label"] == station["gremium"]
    rat = next(s for s in schritte if s["label"] == "Rat")
    assert list(rat)[-2:] == ["hinweis", "gremium_key"] and rat["hinweis"] == "abgesagt"
    beirat = next(s for s in schritte if s["label"] == "[Testdaten] Probebeirat")
    assert beirat["hinweis"] == "verschoben" and "gremium_key" not in beirat
    ohne = next(s for s in schritte if s["label"] == "[Testdaten] Probeausschuss")
    assert "hinweis" not in ohne and "gremium_key" not in ohne
    assert not any(f in s for s, i in zip(schritte, stellen) if i is None for f in process.FELDER_AUS_STATION)
    # Stand, Ergebnis und übrige Felder der Schritte hängen nicht an den beiden Feldern
    ohne_felder = {**p, "process": [{k: v for k, v in s.items() if k not in process.FELDER_AUS_STATION}
                                    for s in p["process"]]}
    assert [{k: v for k, v in s.items() if k not in process.FELDER_AUS_STATION} for s in schritte] == \
        process.steps(ohne_felder)


def _gebietsdateien(base):
    return [f for d in ("ortsteile", "bezirke", "ohne-ortsbezug") for f in sorted((base / d).glob("*.json"))]


def _vorlagen_aendern(base, aendern):
    """`aendern(p)` auf jede Vorlage jeder Gebietsdatei anwenden (eine Vorlage kann in mehreren Dateien stehen)."""
    for f in _gebietsdateien(base):
        d = json.loads(f.read_text())
        for p in d["papers"]:
            aendern(p)
        f.write_text(json.dumps(d, ensure_ascii=False))


def _schritt_der_sitzung(p, sitzung):
    """Der Schritt der Station mit der Sitzung `sitzung` (letzter Teil der Kennung) oder None."""
    for s, i in zip(p["steps"], process.stationen_der_schritte(p)):
        if i is not None and (p["process"][i]["meeting_id"] or "").endswith(f"/meetings/{sitzung}"):
            return s
    return None


def test_kette_schritte_wie_stationen_und_check(oparl, monkeypatch, capsys):
    """(E1) Abruf, Aufbau und Export mit dem Testserver: Die Schritte in den Gebietsdateien tragen Hinweis und Kennung
    ihrer Station (abgesagt und verschoben laut Sitzungsnamen, Kennung nur für Gremien aus gremien.json); check ohne
    Befund, mit den Zahlen der Schritte. Eingeschleust: ein fehlender Hinweis, eine andere Kennung, eine Kennung an
    einem Schritt ohne Station, ein fehlender Schritt und eine Vorlage ohne Vorlagenart; Befunde nur mit Zahlen."""
    _kette_testserver(oparl, monkeypatch)
    export.export()
    base = config.EXPORT / config.STADT
    vorlagen = {p["reference"]: p for f in _gebietsdateien(base) for p in json.loads(f.read_text())["papers"]}
    je_sitzung = {}
    for p in vorlagen.values():
        for s in p["process"]:
            je_sitzung[(s["meeting_id"] or "").rsplit("/", 1)[-1]] = (_schritt_der_sitzung(p, (s["meeting_id"] or "")
                                                                                         .rsplit("/", 1)[-1]), s)
    assert je_sitzung["k2"][0]["hinweis"] == "abgesagt" and je_sitzung["k2"][0]["gremium_key"] == "rat"
    assert je_sitzung["k3"][0]["hinweis"] == "verschoben" and "hinweis" not in je_sitzung["k4"][0]
    assert "gremium_key" not in je_sitzung["k5"][0] and je_sitzung["1"][0]["gremium_key"] == "bv4"
    for schritt, station in je_sitzung.values():
        assert {f: schritt.get(f) for f in process.FELDER_AUS_STATION} == \
            {f: station.get(f) for f in process.FELDER_AUS_STATION}
    db = sqlite3.connect(config.DB)
    try:
        capsys.readouterr()
        assert check.stationen(db) == ([], [])
        assert "Schritte aus Stationen (steps): 10, mit Hinweis 2, mit Kennung des Gremiums 9\n" in \
            capsys.readouterr().out

        def aendern(p):
            for k in ("k2", "k4"):
                s = _schritt_der_sitzung(p, k)
                if s is not None and k == "k2":
                    s.pop("hinweis")
                elif s is not None:
                    s["gremium_key"] = "bv4"
            if p["reference"] == "1001/2026":   # der Schritt „Datum der Vorlage“ stammt aus keiner Station
                next(s for s in p["steps"] if s["typ"] == "veroeffentlichung")["gremium_key"] = "rat"
            if p["reference"] == "1003/2026":
                p["steps"].pop()
            if p["reference"] == "1005/2026":
                del p["paper_type"]
        _vorlagen_aendern(base, aendern)
        befunde, fehlend = check.stationen(db)
    finally:
        db.close()
    assert fehlend == []
    assert befunde == [
        "Schritte: Vorlagen, deren Schritte sich nicht nach process.steps ihren Stationen zuordnen lassen (andere "
        "Zahl von Schritten oder Angaben fehlen; nicht verglichen): 2",
        "Schritte: Feld `hinweis` anders als an der Station des Schritts in process[] (fehlt, zu viel oder anderer "
        "Wert): 1",
        "Schritte: Feld `gremium_key` anders als an der Station des Schritts in process[] (fehlt, zu viel oder anderer "
        "Wert): 2"], befunde
    for x in befunde:   # nur Zahlen: keine Namen, keine Kennungen, keine Drucksachen
        assert "Testdaten" not in x and oparl.b not in x and "/2026" not in x and re.search(r": \d+$", x), x


def test_naechste_ab_dem_datenstand_und_folgende_sitzung():
    """(G7) Die nächste Sitzung ist die erste ohne Absage am Tag des Datenstands oder danach; (E2) liegt sie am
    Datenstand, ist die folgende die erste ohne Absage nach diesem Tag: Eine zweite Sitzung am Datenstand und
    abgesagte Sitzungen überspringt sie, eine Sitzung ohne Uhrzeit steht hinter einer mit Uhrzeit am selben Tag. Liegt
    die nächste Sitzung nach dem Datenstand oder gibt es danach keine, fehlt die folgende."""
    a, b, c = f"{O}/a", f"{O}/b", f"{O}/c"
    meetings = [_sitzung("a1", STAND, time="10:00"), _sitzung("a2", STAND, time="17:00"),
                _sitzung("a3", "2026-11-22", hinweis="abgesagt"), _sitzung("a4", "2026-11-23", cancelled=True),
                _sitzung("a5", "2026-11-24", time=None), _sitzung("a6", "2026-11-24", time="18:00"),
                _sitzung("b1", "2026-11-22"), _sitzung("b2", "2026-11-30"),
                _sitzung("c1", STAND, hinweis="verschoben")]
    orgs_je = {m["source_object"]: [{"a": a, "b": b, "c": c}[m["source_object"].rsplit("/", 1)[1][0]]]
               for m in meetings}
    zahl, naechste, folgende, _ = gremien.sitzungen(meetings, orgs_je, {a, b, c}, {a, b, c}, SEIT, STAND)
    assert naechste[a]["source_object"] == f"{M}/a1" and folgende[a]["source_object"] == f"{M}/a6"
    assert naechste[b]["source_object"] == f"{M}/b1" and b not in folgende
    assert naechste[c]["source_object"] == f"{M}/c1" and c not in folgende
    assert zahl[a] == 2 and zahl[c] == 1 and b not in zahl   # am Datenstand weiter im Zeitraum (F7)
    orgs = [_org("a", "[Testdaten] Probeausschuss", AUSSCHUSS), _org("b", "[Testdaten] Probebeirat", AUSSCHUSS),
            _org("c", "Rat", "Rat")]
    d, zahlen = gremien.daten(orgs, meetings, orgs_je, [], STAND, [])
    e = {x["key"]: x for x in d["gremien"]}
    assert e["a"]["folgende_sitzung"] == {"date": "2026-11-24", "time": "18:00",
                                          "web": "https://example.invalid/sitzung/a6", "source_object": f"{M}/a6"}
    assert e["c"]["naechste_sitzung"]["hinweis"] == "verschoben" and "folgende_sitzung" not in e["c"]
    assert "folgende_sitzung" not in e["b"]
    assert list(e["a"])[-3:] == ["naechste_sitzung", "folgende_sitzung", "source_object"]
    assert set(e["a"]["folgende_sitzung"]) <= set(gremien.FELDER_SITZUNG)
    assert zahlen["naechste_am_datenstand"] == 2 and zahlen["mit_folgender"] == 1
    assert "Gremien mit nächster Sitzung am Datenstand 2, davon mit folgender Sitzung 1" in \
        "\n".join(gremien.zeilen_log(d, zahlen, {}))
    assert "folgende Sitzung" in d["meta"]["note"] and "nächste Sitzung ab dem Datenstand" in d["meta"]["note"]
    # Liste der Sitzungen nicht aktuell: weder nächste noch folgende Sitzung
    liste = {"stand": None, "hinweis": gremien.HINWEIS_SITZUNGSLISTE}
    d, zahlen = gremien.daten(orgs, meetings, orgs_je, [], STAND, [], liste)
    assert not any("naechste_sitzung" in x or "folgende_sitzung" in x for x in d["gremien"])
    assert zahlen["naechste_am_datenstand"] == 0 and zahlen["mit_folgender"] == 0


def test_ohne_organisation_kommend_ab_dem_datenstand():
    """(G7) Für das Log zählen Sitzungen ohne Verweis auf eine Organisation ab dem Tag des Datenstands (vorher erst
    danach); abgesagte und vergangene nicht."""
    meetings = [{**_sitzung("o1", STAND), "gremium": "Rat"}, {**_sitzung("o2", STAND, hinweis="abgesagt")},
                {**_sitzung("o3", "2026-11-20")}, {**_sitzung("o4", "2026-11-22")}]
    assert gremien.ohne_organisation_kommend(meetings, {}, {"Rat": 1}, STAND) == (2, 1)


def _sitzung_am_datenstand(oparl):
    """Eine Sitzung des Rates am heutigen Kölner Tag um 12:00 Uhr (der Datenstand der Kette ist der Kölner Tag des
    Abrufs), ohne Beratung; die Sitzungen k1 bis k5 liegen danach."""
    b = oparl.b
    mittag = datetime.now(ZoneInfo("Europe/Berlin")).replace(hour=12, minute=0, second=0, microsecond=0)
    oparl.meetings.append({"id": f"{b}/meetings/k7", "type": "https://schema.oparl.org/1.1/Meeting", "name": "Rat",
                           "start": mittag.isoformat(), "cancelled": False,
                           "organization": [f"{b}/organizations/rat"], "modified": "2026-11-01T08:00:00+01:00",
                           "agendaItem": []})


def test_kette_folgende_sitzung_und_check(oparl, monkeypatch, capsys):
    """(G7, E2) Kette mit dem Testserver und einer Sitzung des Rates am Datenstand: nächste Sitzung ist diese, folgende
    die verschobene (k1 und k2 sind abgesagt); Log von export und Ausgabe von check mit den Zahlen, check ohne Befund.
    Eingeschleust: eine abgesagte folgende Sitzung, eine folgende Sitzung ohne nächste Sitzung am Datenstand, eine
    folgende Sitzung am Datenstand mit einem Feld außerhalb von gremien.FELDER_SITZUNG und eine nächste Sitzung vor
    dem Datenstand; Befunde nur mit Zahlen."""
    _kette_testserver(oparl, monkeypatch, _sitzung_am_datenstand)
    capsys.readouterr()
    export.export()
    log = capsys.readouterr().out
    base = config.EXPORT / config.STADT
    pfad = base / "gremien.json"
    g = json.loads(pfad.read_text())
    keys = {e["key"]: e for e in g["gremien"]}
    stand = g["meta"]["datenstand"]
    assert keys["rat"]["naechste_sitzung"]["source_object"].endswith("/meetings/k7")
    assert keys["rat"]["naechste_sitzung"]["date"] == stand
    assert keys["rat"]["folgende_sitzung"]["source_object"].endswith("/meetings/k3")
    assert keys["rat"]["folgende_sitzung"]["hinweis"] == "verschoben" and keys["rat"]["sitzungen_12m"] == 1
    assert "folgende_sitzung" not in keys["bv4"]
    assert ("Sitzungen von Gremien aus gremien.json am Datenstand (ohne Absage; zählen als kommend): 1; Gremien mit "
            "nächster Sitzung am Datenstand 1, davon mit folgender Sitzung 1") in log
    db = sqlite3.connect(config.DB)
    try:
        capsys.readouterr()
        assert check.gremien(db) == ([], [])
        assert "mit nächster Sitzung 1 (davon am Datenstand 1), mit folgender Sitzung 1;" in capsys.readouterr().out
        zeit = {m["source_object"].rsplit("/", 1)[1]: m
                for m in json.loads((base / "zeit.json").read_text())["meetings"]}

        def kurz(k, **mehr):
            return {"date": zeit[k]["date"], "time": zeit[k]["time"], "web": zeit[k]["web"],
                    "source_object": zeit[k]["source_object"], **mehr}
        keys["rat"]["folgende_sitzung"] = kurz("k2")                       # abgesagt laut Sitzungsnamen
        keys["bv4"]["naechste_sitzung"] = kurz("1")                        # vor dem Datenstand
        keys["bv4"]["folgende_sitzung"] = kurz("k4")                       # ohne nächste Sitzung am Datenstand
        keys["alt"]["naechste_sitzung"] = kurz("k7")
        keys["alt"]["folgende_sitzung"] = kurz("k7", mitglieder=["[Testdaten] Person"])   # am Datenstand
        pfad.write_text(json.dumps(g, ensure_ascii=False))
        befunde, fehlend = check.gremien(db)
    finally:
        db.close()
    assert fehlend == []
    for erwartet in ("Gremien: Felder der folgenden Sitzung außerhalb von gremien.FELDER_SITZUNG: 1",
                     "Gremien: Feldnamen, die auf Personen deuten: 1",
                     "Gremien: folgende Sitzungen, die abgesagt sind (export.absage): 1",
                     "Gremien: nächste Sitzungen vor dem Datenstand: 1",
                     "Gremien: folgende Sitzungen nicht nach dem Datenstand: 1",
                     "Gremien: folgende Sitzungen ohne nächste Sitzung am Datenstand: 1",
                     "Gremien: Feld naechste_sitzung anders als gremien.daten: 2",
                     "Gremien: Feld folgende_sitzung anders als gremien.daten: 3"):
        assert erwartet in befunde, (erwartet, befunde)
    for x in befunde:
        assert "Testdaten" not in x and "Probe" not in x and oparl.b not in x and re.search(r": \d+$", x), x


def test_kette_sitzungsliste_nicht_aktuell_ohne_folgende(oparl, monkeypatch):
    """(E2) Ist die Liste der Sitzungen nicht aktuell, fehlt auch die folgende Sitzung; eine eingeschleuste folgende
    Sitzung ist ein Befund (nur Zahlen)."""
    _kette_testserver(oparl, monkeypatch, _sitzung_am_datenstand)
    stand = json.loads(config.STAND.read_text())
    stand["abruf_warnungen"] = {"meetings": {"zeit": "2099-01-01T00:00:00+00:00", "meldung": "nicht aktualisiert"}}
    config.STAND.write_text(json.dumps(stand))
    export.export()
    base = config.EXPORT / config.STADT
    g = json.loads((base / "gremien.json").read_text())
    assert not any("naechste_sitzung" in e or "folgende_sitzung" in e for e in g["gremien"])
    zeit = {m["source_object"].rsplit("/", 1)[1]: m for m in json.loads((base / "zeit.json").read_text())["meetings"]}
    for e in g["gremien"]:
        if e["key"] == "rat":
            e["folgende_sitzung"] = {"date": zeit["k4"]["date"], "time": zeit["k4"]["time"], "web": zeit["k4"]["web"],
                                     "source_object": zeit["k4"]["source_object"]}
    (base / "gremien.json").write_text(json.dumps(g, ensure_ascii=False))
    db = sqlite3.connect(config.DB)
    try:
        befunde, _ = check.gremien(db)
    finally:
        db.close()
    assert "Gremien: folgende Sitzungen bei nicht aktueller Liste der Sitzungen (gremien.sitzungsliste): 1" in befunde
    assert "Gremien: folgende Sitzungen ohne nächste Sitzung am Datenstand: 1" in befunde
