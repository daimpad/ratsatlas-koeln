"""Beratungen je Eintrag (Entscheidungen 17.11.2026 (11) und (14)): Dieselbe Kennung einer Beratung kann in mehreren
Vorlagen stehen und in derselben Vorlage mehrfach, je Eintrag mit eigener Sitzung und eigenem TOP (im Lauf vom
17.11.2026 nur das zweite: 7.562 Kennungen mit 18.882 Einträgen, etwa nach einer Vertagung). Vorher war `id`, dann
(`id`, `paper_id`) der Schlüssel der Tabelle consultation, und nur der letzte Eintrag blieb. Jetzt ist der Schlüssel
(`id`, `paper_id`, `position`): Jeder Eintrag ist eine eigene Zeile und eine eigene Station der Prozesslinie (Datum,
Gremium, TOP und Ergebnis im Export, Zählung in check und verify); der Stand der Vorlage folgt bei einer wiederholten
Kennung ihrem letzten Eintrag. Abruf und Format von beratungen.jsonl bleiben unverändert. Alle Objekte sind erfunden
(lokaler Testserver); keine Anfragen an die Stadt."""
import json
import sqlite3

from pipeline import build, check, config, export, sessionnet, verify

GREMIUM = "Bezirksvertretung 4 (Ehrenfeld)"
BEGINN = "2026-10-01T17:00:00+02:00"
BESCHLOSSEN, KENNTNIS = "ungeändert beschlossen", "Kenntnis genommen"   # Ergebnisse der TOPs des Testservers


def _beratung(oparl, kennung, top, **felder):
    b = oparl.b
    return {"id": f"{b}/consultations/{kennung}", "meeting": f"{b}/meetings/1", "agendaItem": f"{b}/agendaitems/{top}",
            "role": "Entscheidung", "authoritative": True, **felder}


def _aufbauen(oparl, capsys):
    """Abruf gegen den Testserver, build (Log zurück), export."""
    sessionnet.fetch_all()
    capsys.readouterr()
    build.build()
    log = capsys.readouterr().out
    export.export()
    capsys.readouterr()
    return log


def _exportiert():
    """Vorlagen aus den Gebietsdateien des Exports je Drucksache."""
    base, out = config.EXPORT / config.STADT, {}
    for d in check.GEBIETSDATEIEN:
        for f in sorted((base / d).glob("*.json")):
            for p in json.loads(f.read_text(encoding="utf-8"))["papers"]:
                out[p["reference"]] = p
    return out


def _stationen(p):
    """Prozesslinie einer exportierten Vorlage: (Beginn, Gremium, TOP, Ergebnis) je Beratung und je Schritt."""
    return ([(x["start_date"], x["gremium"], x["number"], x["result"]) for x in p["process"]],
            [(s.get("date"), s["label"], s.get("number"), s.get("result")) for s in p["steps"]
             if s["typ"] in ("beratung", "entscheidung")])


def test_gemeinsame_kennung_in_zwei_und_drei_vorlagen(oparl, capsys):
    """Drei Vorlagen teilen eine Beratung (derselbe TOP), zwei weitere eine andere Kennung mit je eigenem TOP: Jede
    behält ihre Station mit Datum, Gremium, TOP und Ergebnis (vor der Entscheidung (11) nur die zuletzt gelesene
    Vorlage), jede mit ihrem eigenen TOP; check zählt jede Zeile; Log von build und Ausgabe von check nennen Einträge
    und Kennungen in mehreren Vorlagen."""
    for i in (0, 1, 2):
        oparl.papers[i]["consultation"] = [_beratung(oparl, "gemeinsam-3", 1)]
    oparl.papers[3]["consultation"] = [_beratung(oparl, "gemeinsam-2", 4)]
    oparl.papers[4]["consultation"] = [_beratung(oparl, "gemeinsam-2", 5)]
    log = _aufbauen(oparl, capsys)
    # Format von beratungen.jsonl unverändert: je Vorlage eine Zeile, ohne Angabe der Vorlage
    zeilen = [json.loads(z) for z in config.BERATUNGEN.read_text(encoding="utf-8").splitlines()]
    assert len(zeilen) == 5 and all(sorted(z) == ["agendaItem", "meeting", "uri"] for z in zeilen)
    erwartet = {"1001/2026": ("8.1", BESCHLOSSEN), "AN/102/2026": ("8.1", BESCHLOSSEN),
                "1003/2026": ("8.1", BESCHLOSSEN), "AN/104/2026": ("8.4", KENNTNIS), "1005/2026": ("8.5", BESCHLOSSEN)}
    vorlagen = _exportiert()
    for ref, (top, ergebnis) in erwartet.items():
        assert _stationen(vorlagen[ref]) == ([(BEGINN, GREMIUM, top, ergebnis)],
                                             [("2026-10-01", GREMIUM, top, ergebnis)]), ref
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT COUNT(*), COUNT(DISTINCT id) FROM consultation").fetchone() == (5, 2)
    check.kennzahlen(db)
    aus = capsys.readouterr().out
    assert "mit Sitzung: 5 von 5 (100.0 %)" in aus and "mit TOP-Ergebnis: 5 von 5 (100.0 %)" in aus
    zeile = ("Beratungen: 5 Einträge (je Eintrag eine Zeile der Datenbank); 2 Kennungen in mehreren Vorlagen (5 "
             "Einträge, 5 Vorlagen); 0-mal eine Kennung mehrfach in derselben Vorlage (0 Einträge, jeder Eintrag eine "
             "eigene Station)")
    assert zeile + "\n" in aus
    assert zeile + ("; 2 Einträge mit einer Kennung, die in beratungen.jsonl mit verschiedener Sitzung oder "
                    "verschiedenem TOP steht (je Eintrag nach seinen eigenen Verweisen zugeordnet); 0 Einträge ohne "
                    "eigene Sitzung oder TOP, Verknüpfung über die Kennung übernommen; 0 Einträge ohne Sitzung und TOP, "
                    "obwohl ihre Kennung in beratungen.jsonl steht (eigene Verweise passen zu keiner Zeile, oder ohne "
                    "eigene Verweise mit verschiedenen Zeilen)\n") in log
    # Zusammenfassung (Entscheidung 17.11.2026 (11) (B)): was gezählt wird; nur TOPs mit Beratung einer Vorlage
    assert "5 Vorlagen, 5 Beratungen (Einträge), 1 Sitzungen und 3 TOPs mit Beratung einer Vorlage, " in log
    db.close()



VERTAGT = "vertagt"
SITZUNGEN = {"v1": "2026-10-08T17:00:00+02:00", "v2": "2026-10-22T17:00:00+02:00", "v3": "2026-11-05T17:00:00+01:00"}


def _sitzungen_mit_vertagung(oparl):
    """Drei weitere Sitzungen der Bezirksvertretung 4 (erfunden): TOPs v1 und w1 vertagt, v2 vertagt, w2 zur Kenntnis
    genommen, v3 beschlossen."""
    b = oparl.b
    tops = {"v1": [("v1", "3.1", VERTAGT), ("w1", "3.2", VERTAGT)],
            "v2": [("v2", "4.2", VERTAGT), ("w2", "4.3", KENNTNIS)],
            "v3": [("v3", "5.3", BESCHLOSSEN)]}
    for m, beginn in SITZUNGEN.items():
        oparl.meetings.append({
            "id": f"{b}/meetings/{m}", "type": "https://schema.oparl.org/1.1/Meeting", "name": GREMIUM, "start": beginn,
            "organization": [f"{b}/organizations/bv4"], "modified": "2026-11-06T08:00:00+01:00",
            "agendaItem": [{"id": f"{b}/agendaitems/{t}", "number": nr, "name": f"TOP {t}", "result": erg,
                            "public": True} for t, nr, erg in tops[m]]})


def _eintrag(oparl, kennung, sitzung=None, top=None, **felder):
    b = oparl.b
    c = {"id": f"{b}/consultations/{kennung}", "organization": [f"{b}/organizations/bv4"], "role": "Entscheidung",
         "authoritative": True, **felder}
    if sitzung:
        c["meeting"] = f"{b}/meetings/{sitzung}"
    if top:
        c["agendaItem"] = f"{b}/agendaitems/{top}"
    return c


def test_dieselbe_kennung_dreimal_jeder_eintrag_eine_station(oparl, capsys, monkeypatch):
    """Entscheidung 17.11.2026 (14): AN/102/2026 trägt dieselbe Kennung dreimal (dieselbe Bezirksvertretung, drei
    Sitzungen: vertagt, vertagt, beschlossen): drei Zeilen, drei Stationen in der Reihenfolge der Beratungsfolge mit
    Datum, Gremium, TOP und Ergebnis, Stand „entschieden“ nach dem letzten Eintrag. AN/104/2026 trägt eine zweite
    Kennung zweimal (vertagt, dann zur Kenntnis genommen, nicht entscheidend): Der Stand folgt dem letzten Eintrag
    („beraten, ohne Entscheidung“, nicht „in Beratung“ wegen der früheren Vertagung). 1005/2026 trägt eine dritte
    Kennung dreimal, der mittlere Eintrag ohne eigene Sitzung und TOP: Er bleibt ohne, weil die Einträge derselben
    Kennung verschiedene Zeilen in beratungen.jsonl haben. Sitzungen und TOPs aller Einträge stehen in der Datenbank;
    Log, check und verify zählen jeden Eintrag; dieselbe Bezirksvertretung in mehreren Einträgen bleibt eine
    (district_from_committee)."""
    b = oparl.b
    _sitzungen_mit_vertagung(oparl)
    oparl.papers[1]["consultation"] = [_eintrag(oparl, "drei", "v1", "v1"), _eintrag(oparl, "drei", "v2", "v2"),
                                       _eintrag(oparl, "drei", "v3", "v3")]
    oparl.papers[3]["consultation"] = [_eintrag(oparl, "zwei", "v1", "w1", role="Beratung", authoritative=False),
                                       _eintrag(oparl, "zwei", "v2", "w2", role="Beratung", authoritative=False)]
    oparl.papers[4]["consultation"] = [_eintrag(oparl, "x", "1", "5"), _eintrag(oparl, "x"),
                                       _eintrag(oparl, "x", "v3", "v3")]
    log = _aufbauen(oparl, capsys)
    vorlagen = _exportiert()
    assert _stationen(vorlagen["AN/102/2026"]) == (
        [(SITZUNGEN["v1"], GREMIUM, "3.1", VERTAGT), (SITZUNGEN["v2"], GREMIUM, "4.2", VERTAGT),
         (SITZUNGEN["v3"], GREMIUM, "5.3", BESCHLOSSEN)],
        [("2026-10-08", GREMIUM, "3.1", VERTAGT), ("2026-10-22", GREMIUM, "4.2", VERTAGT),
         ("2026-11-05", GREMIUM, "5.3", BESCHLOSSEN)])
    assert [x["position"] for x in vorlagen["AN/102/2026"]["process"]] == [0, 1, 2]
    assert vorlagen["AN/102/2026"]["stand"] == "entschieden"
    # Format des Exports unverändert: dieselben Felder je Station, ohne Kennung der Beratung
    assert sorted(vorlagen["AN/102/2026"]["process"][0]) == sorted(vorlagen["1001/2026"]["process"][0])
    assert "beratung" not in vorlagen["AN/102/2026"]["process"][0]
    assert _stationen(vorlagen["AN/104/2026"])[0] == [(SITZUNGEN["v1"], GREMIUM, "3.2", VERTAGT),
                                                      (SITZUNGEN["v2"], GREMIUM, "4.3", KENNTNIS)]
    assert vorlagen["AN/104/2026"]["stand"] == "beraten, ohne Entscheidung"
    assert _stationen(vorlagen["1005/2026"])[0] == [(BEGINN, GREMIUM, "8.5", BESCHLOSSEN), (None, GREMIUM, None, None),
                                                    (SITZUNGEN["v3"], GREMIUM, "5.3", BESCHLOSSEN)]
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT position, meeting_id, agenda_item_id FROM consultation WHERE paper_id = ? "
                      "ORDER BY position", (oparl.papers[1]["id"],)).fetchall() == [
        (i, f"{b}/meetings/v{i + 1}", f"{b}/agendaitems/v{i + 1}") for i in range(3)]
    assert sorted(r[0] for r in db.execute("SELECT id FROM meeting")) == [f"{b}/meetings/{m}" for m in ("1", "v1", "v2",
                                                                                                        "v3")]
    assert sorted(r[0] for r in db.execute("SELECT id FROM agenda_item")) == sorted(
        f"{b}/agendaitems/{t}" for t in ("1", "3", "5", "v1", "w1", "v2", "w2", "v3"))
    assert db.execute("SELECT COUNT(*) FROM agenda_item WHERE id NOT IN (SELECT agenda_item_id FROM consultation "
                      "WHERE agenda_item_id IS NOT NULL)").fetchone()[0] == 0
    # district_from_committee: nur die Bezirksvertretung 4, auch wenn sie in mehreren Einträgen steht
    schwach = db.execute("SELECT pl.paper_id, l.stadtbezirk FROM paper_location pl JOIN location l "
                         "ON l.id = pl.location_id WHERE pl.method = 'district_from_committee'").fetchall()
    assert sorted(schwach) == [(oparl.papers[i]["id"], "Ehrenfeld") for i in (1, 3, 4)]
    zeile = ("Beratungen: 10 Einträge (je Eintrag eine Zeile der Datenbank); 0 Kennungen in mehreren Vorlagen (0 "
             "Einträge, 0 Vorlagen); 3-mal eine Kennung mehrfach in derselben Vorlage (8 Einträge, jeder Eintrag eine "
             "eigene Station)")
    assert check.beratungen_je_vorlage(db) == zeile
    check.kennzahlen(db)
    aus = capsys.readouterr().out
    assert "mit Sitzung: 9 von 10 (90.0 %)" in aus and "mit TOP-Ergebnis: 9 von 10 (90.0 %)" in aus
    # Prüfung bs: alle drei wiederholten Kennungen nach dem Sitzungstag geordnet (der Eintrag ohne Sitzung zählt nicht)
    assert ("Kennungen mehrfach in derselben Vorlage, deren Einträge nicht nach dem Sitzungstag geordnet sind: 0 von 3 "
            "(der Stand folgt dem letzten Eintrag in der Beratungsfolge)\n") in aus
    db.close()
    assert zeile + ("; 8 Einträge mit einer Kennung, die in beratungen.jsonl mit verschiedener Sitzung oder "
                    "verschiedenem TOP steht (je Eintrag nach seinen eigenen Verweisen zugeordnet); 0 Einträge ohne "
                    "eigene Sitzung oder TOP, Verknüpfung über die Kennung übernommen; 1 Einträge ohne Sitzung und TOP, "
                    "obwohl ihre Kennung in beratungen.jsonl steht (") in log
    assert "5 Vorlagen, 10 Beratungen (Einträge), 4 Sitzungen und 8 TOPs mit Beratung einer Vorlage, " in log
    # verify: Zahl der Beratungen je Vorlage gegen die Quelle (hier die Rohdaten statt einer Anfrage)
    roh = {p["id"]: p for p in map(json.loads, config.PAPERS.read_text(encoding="utf-8").splitlines())}
    monkeypatch.setattr(verify, "get_json", lambda pid, tries=3: roh[pid])
    verify.verify(n=5)
    with open(config.EXPORT / "verifikation_oparl.tsv", encoding="utf-8") as f:
        beratungen = [z.rstrip("\n").split("\t") for z in f if "\tberatungen\t" in z]
    assert len(beratungen) == 5 and all(z[-1] == "ok" for z in beratungen), beratungen
    assert {z[0]: z[2] for z in beratungen} == {"1001/2026": "1", "AN/102/2026": "3", "1003/2026": "1",
                                                "AN/104/2026": "2", "1005/2026": "3"}


def test_wiederholte_kennung_reihenfolge_und_feed_ids(oparl, capsys):
    """Prüfung bs: 1001/2026 trägt eine Kennung dreimal, nach der Beratungsfolge zuerst am 05.11. (beschlossen), dann am
    08.10. und 22.10. (vertagt): check zählt sie als nicht nach dem Sitzungstag geordnet (der Stand folgt dem letzten
    Eintrag in der Beratungsfolge; ob er dem spätesten Sitzungstag folgen soll, ist offen). AN/102/2026 trägt eine
    Kennung zweimal in derselben Sitzung unter zwei TOPs: Die Einträge der Feeds haben verschiedene IDs, die erste wie
    bisher aus Datum und Gremium, die zweite mit der TOP-Nummer; kein Feed enthält eine ID doppelt."""
    import xml.etree.ElementTree as ET
    from urllib.parse import quote
    from pipeline import publish
    _sitzungen_mit_vertagung(oparl)
    oparl.papers[0]["consultation"] = [_eintrag(oparl, "r", "v3", "v3"), _eintrag(oparl, "r", "v1", "v1"),
                                       _eintrag(oparl, "r", "v2", "v2")]
    oparl.papers[1]["consultation"] = [_beratung(oparl, "q", 1), _beratung(oparl, "q", 4)]
    _aufbauen(oparl, capsys)
    db = sqlite3.connect(config.DB)
    assert check.reihenfolge_wiederholter_kennungen(db) == (2, 1)
    check.kennzahlen(db)
    assert ("Kennungen mehrfach in derselben Vorlage, deren Einträge nicht nach dem Sitzungstag geordnet sind: 1 von 2 "
            "(der Stand folgt dem letzten Eintrag in der Beratungsfolge)\n") in capsys.readouterr().out
    db.close()
    p = _exportiert()["AN/102/2026"]
    assert _stationen(p)[0] == [(BEGINN, GREMIUM, "8.1", BESCHLOSSEN), (BEGINN, GREMIUM, "8.4", KENNTNIS)]
    basis = f"{oparl.papers[1]['id']}#beratung-2026-10-01-{quote(GREMIUM, safe='')}"
    assert [e["id"] for e in publish.events(p) if "#beratung-" in e["id"]] == [basis, basis + "-top-8.4"]
    atom = "{http://www.w3.org/2005/Atom}"
    feeds = sorted((config.EXPORT / config.STADT / "feeds").rglob("*.xml"))
    assert feeds
    gefunden = set()
    for f in feeds:
        ids = [e.findtext(f"{atom}id") for e in ET.parse(f).getroot().iter(f"{atom}entry")]
        assert len(ids) == len(set(ids)), f.name
        gefunden.update(i for i in ids if i.startswith(basis))
    assert gefunden == {basis, basis + "-top-8.4"}


def test_wiederholte_kennung_erstes_gremium_fuer_datenschutz(oparl, capsys):
    """Entscheidung 17.11.2026 (14): Steht eine Kennung in derselben Vorlage zweimal, zuerst im Ausschuss für
    Anregungen und Beschwerden, zuletzt in einem anderen Gremium, sehen check.erlaubnis und maske.aus_db beide Gremien
    wie build (vorher blieb in der Datenbank nur das letzte, und check hielt die Vorlage für erlaubt)."""
    from pipeline import maske
    b = oparl.b
    oparl.orgs.append({"id": f"{b}/organizations/ab", "name": "Ausschuss für Bürgerbeteiligung, Anregungen und "
                       "Beschwerden", "organizationType": "Gremium", "modified": "2026-01-01T00:00:00+01:00"})
    oparl.papers[0]["consultation"] = [_beratung(oparl, "wdh", 1, organization=[f"{b}/organizations/ab"]),
                                       _beratung(oparl, "wdh", 2, organization=[f"{b}/organizations/rat"])]
    _aufbauen(oparl, capsys)
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT organization_id FROM consultation WHERE paper_id = ? ORDER BY position",
                      (oparl.papers[0]["id"],)).fetchall() == [(f"{b}/organizations/ab",), (f"{b}/organizations/rat",)]
    punktregel = set()
    erlaubt = check.erlaubnis(db, punktregel=punktregel)[0]
    assert erlaubt[oparl.papers[0]["id"]] is False and oparl.papers[0]["id"] in punktregel
    assert "1001/2026" in maske.aus_db(db).refs
    db.close()

def test_wiederholte_kennung_in_derselben_vorlage(oparl, capsys, monkeypatch):
    """Steht eine Kennung in derselben Vorlage zweimal, ist jeder Eintrag eine eigene Zeile und Station (vorher blieb
    nur der letzte); Log, check und verify (Zahl der Beratungen gegen die Quelle) zählen beide Einträge."""
    oparl.papers[0]["consultation"] = [_beratung(oparl, "a", 1, role="Beratung", authoritative=False),
                                       _beratung(oparl, "b", 2, role="Beratung", authoritative=False),
                                       _beratung(oparl, "a", 1)]
    log = _aufbauen(oparl, capsys)
    db = sqlite3.connect(config.DB)
    pid = oparl.papers[0]["id"]
    assert db.execute("SELECT id, position, role FROM consultation WHERE paper_id = ? ORDER BY position",
                      (pid,)).fetchall() == [(f"{oparl.b}/consultations/a", 0, "Beratung"),
                                             (f"{oparl.b}/consultations/b", 1, "Beratung"),
                                             (f"{oparl.b}/consultations/a", 2, "Entscheidung")]
    assert _stationen(_exportiert()["1001/2026"])[0] == [(BEGINN, GREMIUM, "8.1", BESCHLOSSEN),
                                                         (BEGINN, GREMIUM, "8.2", KENNTNIS),
                                                         (BEGINN, GREMIUM, "8.1", BESCHLOSSEN)]
    zeile = ("Beratungen: 7 Einträge (je Eintrag eine Zeile der Datenbank); 0 Kennungen in mehreren Vorlagen (0 "
             "Einträge, 0 Vorlagen); 1-mal eine Kennung mehrfach in derselben Vorlage (2 Einträge, jeder Eintrag eine "
             "eigene Station)")
    assert zeile + "; 0 Einträge mit einer Kennung" in log
    assert check.beratungen_je_vorlage(db) == zeile
    db.close()
    # verify vergleicht die Zahl der Beratungen mit der Quelle (hier die Rohdaten statt einer Anfrage)
    roh = {p["id"]: p for p in map(json.loads, config.PAPERS.read_text(encoding="utf-8").splitlines())}
    monkeypatch.setattr(verify, "get_json", lambda pid, tries=3: roh[pid])
    verify.verify(n=5)
    with open(config.EXPORT / "verifikation_oparl.tsv", encoding="utf-8") as f:
        beratungen = [z.rstrip("\n").split("\t") for z in f if "\tberatungen\t" in z]
    assert len(beratungen) == 5 and all(z[-1] == "ok" for z in beratungen), beratungen
    assert ["1001/2026", "beratungen", "3", "3", "ok"] in beratungen


def test_gremium_der_gemeinsamen_beratung_bleibt_fuer_datenschutz(oparl, capsys):
    """Punktregel und Titelmaske lesen die beratenden Gremien in check und export aus der Datenbank
    (geocode.angaben_db), build aus den Rohdaten. Teilen zwei Vorlagen eine Kennung, behält jede ihr Gremium: Die
    Vorlage, die im Ausschuss für Anregungen und Beschwerden beraten wird, ist auch nach check.erlaubnis ohne
    Hauskoordinate und Ausgangspunkt der Titelmaske, wie in build (vorher fehlte ihr Gremium in der Datenbank, wenn die
    andere Vorlage den Eintrag überschrieb)."""
    from pipeline import maske
    b = oparl.b
    oparl.orgs.append({"id": f"{b}/organizations/ab", "name": "Ausschuss für Bürgerbeteiligung, Anregungen und "
                       "Beschwerden", "organizationType": "Gremium", "modified": "2026-01-01T00:00:00+01:00"})
    oparl.papers[0]["consultation"] = [_beratung(oparl, "gemeinsam", 1, organization=[f"{b}/organizations/ab"])]
    oparl.papers[1]["consultation"] = [_beratung(oparl, "gemeinsam", 1, organization=[f"{b}/organizations/rat"])]
    _aufbauen(oparl, capsys)
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT paper_id, organization_id FROM consultation WHERE id = ? ORDER BY paper_id",
                      (f"{b}/consultations/gemeinsam",)).fetchall() == [
        (oparl.papers[0]["id"], f"{b}/organizations/ab"), (oparl.papers[1]["id"], f"{b}/organizations/rat")]
    punktregel = set()
    erlaubt = check.erlaubnis(db, punktregel=punktregel)[0]
    assert erlaubt[oparl.papers[0]["id"]] is False and oparl.papers[0]["id"] in punktregel
    assert "1001/2026" in maske.aus_db(db).refs
    db.close()


def test_sitzung_und_top_je_vorlage():
    """build._sitzung_und_top: Verweist die Beratung selbst auf Sitzung oder TOP, gilt immer die Zeile, die dazu passt
    (Sitzung und TOP, dann der TOP, dann die Sitzung ohne TOP), auch wenn es nur eine Zeile gibt oder alle gleich sind;
    ohne passende Zeile keine (sessionnet.beratungen schrieb für diese Vorlage keine; Prüfung bk). Ohne eigene Verweise
    (OParl-Lite in Bonn; in Köln eine Beratung ohne Sitzung und TOP) wie bisher die letzte Zeile, wenn alle gleich sind,
    sonst keine."""
    def zeile(m, t, nr=None):
        return {"uri": "c", "meeting": {"uri": m} if m else None,
                "agendaItem": {"uri": t, "number": nr} if t else None}
    wahl = build._sitzung_und_top
    assert wahl([], {"id": "c"}) == {} and wahl([], {"id": "c", "meeting": "m1", "agendaItem": "t1"}) == {}
    einzeln = zeile("m1", "t1")
    assert wahl([einzeln], {"id": "c"}) is einzeln                      # Bonn: Beratung ohne Verweise
    assert wahl([einzeln], {"id": "c", "meeting": "", "agendaItem": ["t1"]}) is einzeln   # leer, keine Zeichenkette
    assert wahl([einzeln], {"id": "c", "meeting": "m1", "agendaItem": "t1"}) is einzeln
    gleich = [zeile("m1", "t1", "1"), zeile("m1", "t1", "2")]
    assert wahl(gleich, {"id": "c", "meeting": "m1", "agendaItem": "t1"}) is gleich[-1]
    assert wahl(gleich, {"id": "c"}) is gleich[-1]
    # eigene Verweise, die sich nicht auflösen ließen: keine Station, auch bei nur einer Zeile oder gleichen Zeilen
    # (vorher die der anderen Vorlage, Prüfung bk)
    assert wahl([zeile("m1", "t3")], {"meeting": "unbekannt", "agendaItem": "unbekannt"}) == {}
    assert wahl([zeile("m1", "t3"), zeile("m2", "t21")], {"meeting": "unbekannt", "agendaItem": "unbekannt"}) == {}
    assert wahl(gleich, {"id": "c", "meeting": "m9", "agendaItem": "t9"}) == {}
    assert wahl(gleich, {"id": "c", "agendaItem": "t9"}) == {} and wahl(gleich, {"meeting": "m1"}) == {}
    verschieden = [zeile("m1", "t1"), zeile("m2", "t2"), zeile("m3", None), zeile("m4", "t2")]
    assert wahl(verschieden, {"meeting": "m2", "agendaItem": "t2"}) is verschieden[1]   # Sitzung und TOP
    assert wahl(verschieden, {"meeting": "m1", "agendaItem": "t1"}) is verschieden[0]
    # Sitzung aus dem TOP (die eigene Sitzung fehlt in der Liste oder kommt nicht als Zeichenkette): der TOP
    assert wahl(verschieden, {"meeting": "fehlt", "agendaItem": "t1"}) is verschieden[0]
    assert wahl(verschieden, {"meeting": ["m1"], "agendaItem": "t2"}) is verschieden[3]
    assert wahl(verschieden, {"meeting": "m3", "agendaItem": "fehlt"}) is verschieden[2]    # Sitzung ohne TOP
    assert wahl(verschieden, {"meeting": "m3"}) is verschieden[2]
    # nichts passt: keine Sitzung und kein TOP einer anderen Vorlage; ohne eigene Verweise bei verschiedenen Zeilen keine
    assert wahl(verschieden, {"meeting": "m9", "agendaItem": "t9"}) == {}
    assert wahl(verschieden, {"meeting": "m1"}) == {} and wahl(verschieden, {}) == {}


def test_eigene_verweise_ohne_aufloesung_keine_fremde_station(oparl, capsys):
    """Prüfung bk: Drei Vorlagen teilen eine Kennung, aber nur 1003/2026 verweist auf Sitzung und TOP, die es gibt (eine
    Zeile in beratungen.jsonl). AN/104/2026 nennt Sitzung und TOP, die sich nicht auflösen lassen: keine Station (vorher
    die von 1003/2026 mit Stand „entschieden“). 1005/2026 verweist auf nichts: Verknüpfung über die Kennung wie
    dokumentiert. Das Log zählt beides; check zählt die Zeilen."""
    b = oparl.b
    rat = [f"{b}/organizations/rat"]
    oparl.papers[2]["consultation"] = [_beratung(oparl, "gemeinsam", 3, organization=rat)]
    oparl.papers[3]["consultation"] = [_beratung(oparl, "gemeinsam", 3, organization=rat,
                                                 meeting=f"{b}/meetings/unbekannt",
                                                 agendaItem=f"{b}/agendaitems/unbekannt")]
    oparl.papers[4]["consultation"] = [{"id": f"{b}/consultations/gemeinsam", "organization": rat,
                                        "role": "Entscheidung", "authoritative": True}]
    log = _aufbauen(oparl, capsys)
    zeilen = [json.loads(z) for z in config.BERATUNGEN.read_text(encoding="utf-8").splitlines()]
    assert [z["uri"] for z in zeilen].count(f"{b}/consultations/gemeinsam") == 1
    vorlagen = _exportiert()
    assert _stationen(vorlagen["1003/2026"]) == ([(BEGINN, "Rat", "8.3", BESCHLOSSEN)],
                                                 [("2026-10-01", "Rat", "8.3", BESCHLOSSEN)])
    assert _stationen(vorlagen["1005/2026"]) == _stationen(vorlagen["1003/2026"])   # über die Kennung
    station, schritte = _stationen(vorlagen["AN/104/2026"])
    assert [x[0] for x in station] == [None] and [x[2:] for x in station] == [(None, None)]
    assert not any(s[0] or s[2] or s[3] for s in schritte), schritte
    assert vorlagen["1003/2026"]["stand"] == vorlagen["1005/2026"]["stand"] == "entschieden"
    assert vorlagen["AN/104/2026"]["stand"] != "entschieden"
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT paper_id, meeting_id IS NOT NULL, agenda_item_id IS NOT NULL FROM consultation "
                      "WHERE id = ? ORDER BY paper_id", (f"{b}/consultations/gemeinsam",)).fetchall() == [
        (oparl.papers[2]["id"], 1, 1), (oparl.papers[3]["id"], 0, 0), (oparl.papers[4]["id"], 1, 1)]
    check.kennzahlen(db)
    aus = capsys.readouterr().out
    assert "mit Sitzung: 4 von 5 (80.0 %)" in aus and "mit TOP-Ergebnis: 4 von 5 (80.0 %)" in aus
    db.close()
    assert ("; 0 Einträge mit einer Kennung, die in beratungen.jsonl mit verschiedener Sitzung oder verschiedenem TOP "
            "steht (je Eintrag nach seinen eigenen Verweisen zugeordnet); 1 Einträge ohne eigene Sitzung oder TOP, "
            "Verknüpfung über die Kennung übernommen; 1 Einträge ohne Sitzung und TOP, obwohl ihre Kennung in "
            "beratungen.jsonl steht (") in log


def test_wiederholte_kennung_mit_verschiedenem_top_jeder_eintrag(oparl, capsys):
    """Steht eine Kennung in derselben Vorlage zweimal mit verschiedenem TOP, ist jeder Eintrag eine Zeile mit seinem
    TOP (Entscheidung 17.11.2026 (14); seit der Prüfung bk bis dahin nur der letzte Eintrag und nur sein TOP), und
    beide TOPs stehen in `agenda_item`: kein TOP ohne Beratung, die auf ihn verweist, die Zusammenfassung im Log zählt
    beide."""
    b = oparl.b
    oparl.papers[0]["consultation"] = [_beratung(oparl, "a", 1, role="Beratung", authoritative=False),
                                       _beratung(oparl, "a", 2)]
    log = _aufbauen(oparl, capsys)
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT agenda_item_id FROM consultation WHERE paper_id = ? ORDER BY position",
                      (oparl.papers[0]["id"],)).fetchall() == [(f"{b}/agendaitems/1",), (f"{b}/agendaitems/2",)]
    assert sorted(r[0] for r in db.execute("SELECT id FROM agenda_item")) == [f"{b}/agendaitems/{i}" for i in range(1, 6)]
    assert db.execute("SELECT COUNT(*) FROM agenda_item WHERE id NOT IN (SELECT agenda_item_id FROM consultation "
                      "WHERE agenda_item_id IS NOT NULL)").fetchone()[0] == 0
    db.close()
    assert "5 Vorlagen, 6 Beratungen (Einträge), 1 Sitzungen und 5 TOPs mit Beratung einer Vorlage, " in log
    assert _stationen(_exportiert()["1001/2026"])[0] == [(BEGINN, GREMIUM, "8.1", BESCHLOSSEN),
                                                         (BEGINN, GREMIUM, "8.2", KENNTNIS)]


def test_beratungen_aeltere_datenbank():
    """check.beratungen_je_vorlage liest eine ältere Datenbank, deren Schlüssel `position` nicht enthält (eine Zeile je
    Kennung, ab der Entscheidung (11) je Kennung und Vorlage mit Spalte `entries`): nur die Zeilen."""
    for schema in ("id TEXT PRIMARY KEY, paper_id TEXT, position INTEGER",
                   "id TEXT, paper_id TEXT, position INTEGER, entries INTEGER, PRIMARY KEY (id, paper_id)"):
        db = sqlite3.connect(":memory:")
        db.execute(f"CREATE TABLE consultation ({schema})")
        db.executemany("INSERT INTO consultation (id, paper_id, position) VALUES (?, ?, ?)",
                       [("c1", "p1", 0), ("c2", "p1", 1), ("c3", "p2", 0)])
        assert check.beratungen_je_vorlage(db) == ("Beratungen: 3 Zeilen der Datenbank (Einträge nicht erfasst: ältere "
                                                   "Datenbank, Schlüssel ohne position)")


def test_beratungen_zeile_zaehlt():
    """build.beratungen_zeile: Kennungen in mehreren Vorlagen (mit ihren Einträgen, auch Wiederholungen darin, und
    Vorlagen) und Wiederholungen in derselben Vorlage, je Paar aus Kennung und Vorlage."""
    cons = [("c1", "p1"), ("c1", "p2"), ("c1", "p2"), ("c1", "p3"), ("c2", "p1"), ("c3", "p4"), ("c3", "p4"),
            ("c3", "p4"), ("c4", "p5"), ("c4", "p6")]
    assert build.beratungen_zeile(cons, 3, 2, 1) == (
        "Beratungen: 10 Einträge (je Eintrag eine Zeile der Datenbank); 2 Kennungen in mehreren Vorlagen (6 Einträge, "
        "5 Vorlagen); 2-mal eine Kennung mehrfach in derselben Vorlage (5 Einträge, jeder Eintrag eine eigene "
        "Station); 3 Einträge mit einer Kennung, die in beratungen.jsonl mit verschiedener "
        "Sitzung oder verschiedenem TOP steht (je Eintrag nach seinen eigenen Verweisen zugeordnet); 2 Einträge ohne "
        "eigene Sitzung oder TOP, Verknüpfung über die Kennung übernommen; 1 Einträge ohne Sitzung und TOP, obwohl "
        "ihre Kennung in beratungen.jsonl steht (eigene Verweise passen zu keiner Zeile, oder ohne eigene Verweise mit "
        "verschiedenen Zeilen)")
