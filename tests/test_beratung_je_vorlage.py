"""Beratungen je Eintrag (Entscheidungen 17.11.2026 (11) und (14)): Dieselbe Kennung einer Beratung kann in mehreren
Vorlagen stehen und in derselben Vorlage mehrfach, je Eintrag mit eigener Sitzung und eigenem TOP (im Lauf vom
17.11.2026 nur das zweite: 7.562 Kennungen mit 18.882 Einträgen, etwa nach einer Vertagung). Vorher war `id`, dann
(`id`, `paper_id`) der Schlüssel der Tabelle consultation, und nur der letzte Eintrag blieb. Jetzt ist der Schlüssel
(`id`, `paper_id`, `position`): Jeder Eintrag ist eine eigene Zeile und eine eigene Station der Prozesslinie (Datum,
Gremium, TOP und Ergebnis im Export, Zählung in check und verify); der Stand der Vorlage folgt bei einer wiederholten
Kennung ihrem Eintrag mit dem spätesten Sitzungstag, bei gleichem Tag dem späteren, ohne Sitzungstag beim letzten
Eintrag diesem (Entscheidung 17.11.2026 (15); vorher dem letzten Eintrag), ohne Einträge abgesagter Sitzungen, außer
alle sind abgesagt (Entscheidung 17.11.2026 (16)). Abruf und Format von beratungen.jsonl bleiben unverändert. Alle
Objekte sind erfunden (lokaler Testserver); keine Anfragen an die Stadt."""
import json
import sqlite3

from pipeline import build, check, config, export, sessionnet, verify

GREMIUM = "Bezirksvertretung 4 (Ehrenfeld)"
BEGINN = "2026-10-01T17:00:00+02:00"
BESCHLOSSEN, KENNTNIS = "ungeändert beschlossen", "Kenntnis genommen"   # Ergebnisse der TOPs des Testservers
# Regel für den Stand im Text von check (Entscheidungen 17.11.2026 (15) und (16))
REGEL = ("(der Stand folgt dem Eintrag mit dem spätesten Sitzungstag, bei gleichem Tag dem späteren; hat der letzte "
         "Eintrag keinen Sitzungstag, folgt er diesem; für den Stand zählen Einträge abgesagter Sitzungen nicht)")


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


def _enden(p):
    """Enden der Wege in prozesse.json mit derselben Vorlagenart und denselben Stationen wie p (Ende, Art des Endes)."""
    wege = json.loads((config.EXPORT / config.STADT / "prozesse.json").read_text(encoding="utf-8"))["types"]
    stationen = [f"{x['gremium'] or '?'} ({x['role'] or '?'})" for x in p["process"]]
    return [(w["final"], w["final_kind"]) for t in wege if t["paper_type"] == p["paper_type"] for w in t["paths"]
            if w["stations"] == stationen]


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
    Datum, Gremium, TOP und Ergebnis, Stand „entschieden“ nach dem letzten Eintrag (zugleich dem spätesten
    Sitzungstag). AN/104/2026 trägt eine zweite Kennung zweimal (vertagt, dann zur Kenntnis genommen, nicht
    entscheidend): Der Stand folgt dem letzten Eintrag („beraten, ohne Entscheidung“, nicht „in Beratung“ wegen der
    früheren Vertagung). 1005/2026 trägt eine dritte Kennung dreimal, der mittlere Eintrag ohne eigene Sitzung und
    TOP: Er bleibt ohne, weil die Einträge derselben Kennung verschiedene Zeilen in beratungen.jsonl haben. Sitzungen
    und TOPs aller Einträge stehen in der Datenbank; Log, check und verify zählen jeden Eintrag; dieselbe
    Bezirksvertretung in mehreren Einträgen bleibt eine (district_from_committee)."""
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
            + REGEL + "\n") in aus
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
    08.10. und 22.10. (vertagt): check zählt sie als nicht nach dem Sitzungstag geordnet, und der Stand folgt dem
    Beschluss am spätesten Sitzungstag („entschieden“, Entscheidung 17.11.2026 (15); vorher „in Beratung“ nach dem
    letzten Eintrag), ebenso das Ende ihres Weges in prozesse.json (der Beschluss, vorher „vertagt“). AN/102/2026
    trägt eine Kennung zweimal in derselben Sitzung unter zwei TOPs: Die Einträge der Feeds haben verschiedene IDs, die
    erste wie bisher aus Datum und Gremium, die zweite mit der TOP-Nummer; kein Feed enthält eine ID doppelt."""
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
            + REGEL + "\n") in capsys.readouterr().out
    db.close()
    assert _stationen(_exportiert()["1001/2026"])[0] == [(SITZUNGEN["v3"], GREMIUM, "5.3", BESCHLOSSEN),
                                                         (SITZUNGEN["v1"], GREMIUM, "3.1", VERTAGT),
                                                         (SITZUNGEN["v2"], GREMIUM, "4.2", VERTAGT)]
    assert _exportiert()["1001/2026"]["stand"] == "entschieden"
    # Ende des Weges in prozesse.json wie der Stand: der Beschluss am spätesten Sitzungstag (vorher „vertagt“)
    assert _enden(_exportiert()["1001/2026"]) == [(BESCHLOSSEN, "ergebnis")]
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


OFFEN = "Noch keine Beratung mit abschließendem Ergebnis; nach einer Vertagung zählt der neue Termin."


def test_stand_nach_dem_spaetesten_sitzungstag(oparl, capsys):
    """Entscheidung 17.11.2026 (15) (A): Bei einer Kennung mehrfach in derselben Vorlage folgt der Stand ihrem Eintrag
    mit dem spätesten Sitzungstag. AN/102/2026 (geordnet: vertagt 08.10., vertagt 22.10., beschlossen 05.11.) bleibt
    „entschieden“. 1003/2026 (vertagt 08.10., vertagt 22.10., dann ein Eintrag ohne Sitzung, etwa ein neuer Termin,
    der noch nicht feststeht): Der letzte Eintrag zählt wie bisher, „offen“ (nach dem spätesten Tag wäre es „in
    Beratung“). Gleicher Tag (22.10., zwei TOPs derselben Sitzung): der spätere Eintrag, also AN/104/2026 (zur Kenntnis
    genommen, dann vertagt) „in Beratung“ und 1005/2026 (vertagt, dann zur Kenntnis genommen) „entschieden“. Das
    Glossar im Export erklärt „offen“ mit dem Text aus (15) (B)."""
    _sitzungen_mit_vertagung(oparl)
    oparl.papers[1]["consultation"] = [_eintrag(oparl, "g", "v1", "v1"), _eintrag(oparl, "g", "v2", "v2"),
                                       _eintrag(oparl, "g", "v3", "v3")]
    oparl.papers[2]["consultation"] = [_eintrag(oparl, "u", "v1", "v1"), _eintrag(oparl, "u", "v2", "v2"),
                                       _eintrag(oparl, "u")]
    oparl.papers[3]["consultation"] = [_eintrag(oparl, "t", "v2", "w2"), _eintrag(oparl, "t", "v2", "v2")]
    oparl.papers[4]["consultation"] = [_eintrag(oparl, "s", "v2", "v2"), _eintrag(oparl, "s", "v2", "w2")]
    _aufbauen(oparl, capsys)
    vorlagen = _exportiert()
    assert _stationen(vorlagen["1003/2026"])[0] == [(SITZUNGEN["v1"], GREMIUM, "3.1", VERTAGT),
                                                    (SITZUNGEN["v2"], GREMIUM, "4.2", VERTAGT),
                                                    (None, GREMIUM, None, None)]
    assert _stationen(vorlagen["AN/104/2026"])[0] == [(SITZUNGEN["v2"], GREMIUM, "4.3", KENNTNIS),
                                                      (SITZUNGEN["v2"], GREMIUM, "4.2", VERTAGT)]
    assert _stationen(vorlagen["1005/2026"])[0] == [(SITZUNGEN["v2"], GREMIUM, "4.2", VERTAGT),
                                                    (SITZUNGEN["v2"], GREMIUM, "4.3", KENNTNIS)]
    assert {ref: vorlagen[ref]["stand"] for ref in ("AN/102/2026", "1003/2026", "AN/104/2026", "1005/2026")} == {
        "AN/102/2026": "entschieden", "1003/2026": "offen", "AN/104/2026": "in Beratung", "1005/2026": "entschieden"}
    # Ende des Weges in prozesse.json wie bisher: geordnet der Beschluss, ohne Sitzungstag zuletzt das letzte Ergebnis
    assert _enden(vorlagen["AN/102/2026"]) == [(BESCHLOSSEN, "ergebnis")]
    assert _enden(vorlagen["1003/2026"]) == [(VERTAGT, "ergebnis")]
    db = sqlite3.connect(config.DB)
    assert check.reihenfolge_wiederholter_kennungen(db) == (4, 0)
    db.close()
    assert json.loads((config.EXPORT / "glossar.json").read_text(encoding="utf-8"))["staende"]["offen"] == OFFEN


def test_massgeblich_und_dossier():
    """process.massgeblich (Entscheidung 17.11.2026 (15) (A)) und dieselbe Regel in dossier._eintrag (Themenseiten,
    abgeschaltet): die letzte Beratung mit Ergebnis nach dem spätesten Sitzungstag (bei gleichem Tag die spätere, ohne
    Sitzungstag beim letzten Eintrag dieser), die nächste nach dem frühesten kommenden Tag (bei gleichem Tag die
    frühere), nicht nach der Stelle in der Beratungsfolge. Erfundene Einträge."""
    from pipeline import dossier, glossar, process
    m = process.massgeblich
    assert m([]) is None and m([None]) == 0 and m([None, None]) == 1
    assert m(["2026-10-08", "2026-10-22", "2026-11-05"]) == 2       # geordnet: der letzte, wie bisher
    assert m(["2026-11-05", "2026-10-08", "2026-10-22"]) == 0       # Beschluss am spätesten Tag an erster Stelle
    assert m(["2026-10-08", "2026-10-22", None]) == 2               # der letzte ohne Sitzungstag zählt, wie bisher
    assert m(["2026-11-05", None, "2026-10-22"]) == 0               # ein früherer ohne Sitzungstag zählt nicht mit
    assert m(["2026-10-22", "2026-10-22"]) == 1                     # gleicher Tag: der spätere

    def b(gremium, start, result=None, cancelled=False):
        return {"gremium": gremium, "start_date": start, "result": result, "cancelled": cancelled}

    p = {"reference": "1001/2026", "process": [
        b("A", "2026-11-05T17:00:00+01:00", BESCHLOSSEN), b("B", "2026-10-08T17:00:00+02:00", VERTAGT),
        b("C", "2026-10-22T17:00:00+02:00", VERTAGT), b("D", "2026-12-10T17:00:00+01:00"),
        b("E", "2026-11-20T17:00:00+01:00"), b("F", "2026-11-20T17:00:00+01:00"),
        b("G", "2026-11-18T17:00:00+01:00", cancelled=True), b("H", "2026-11-01T17:00:00+01:00")]}
    e = dossier._eintrag(p, None, "2026-11-17")
    assert e["letzte_beratung"] == {"gremium": "A", "date": "2026-11-05", "result": BESCHLOSSEN}   # vorher C
    assert e["naechste_beratung"] == {"gremium": "E", "date": "2026-11-20"}                       # vorher D
    gleich = {"reference": "1001/2026", "process": [b("A", "2026-10-22T17:00:00+02:00", KENNTNIS),
                                                    b("B", "2026-10-22T18:00:00+02:00", VERTAGT)]}
    assert dossier._eintrag(gleich, None, "2026-11-17")["letzte_beratung"]["gremium"] == "B"
    ohne_tag = {"reference": "1001/2026", "process": [b("A", "2026-11-05T17:00:00+01:00", BESCHLOSSEN),
                                                      b("B", None, VERTAGT)]}
    assert dossier._eintrag(ohne_tag, None, "2026-11-17")["letzte_beratung"] == {"gremium": "B", "date": None,
                                                                                  "result": VERTAGT}
    assert glossar.STAENDE["offen"] == glossar.glossar()["staende"]["offen"] == OFFEN


def test_ende_des_weges_wie_der_stand():
    """process.path_key (prozesse.json, „Typische Wege je Vorlagenart“): Steht die Kennung des letzten entscheidenden
    Eintrags mit Ergebnis mehrfach in der Vorlage, ist das Ende das Ergebnis ihres Eintrags, der für den Stand zählt
    (Entscheidung 17.11.2026 (15) (A)), nicht mehr das des letzten nach der Stelle; Stand und Ende widersprechen sich
    nicht. Ein früherer Eintrag ohne Sitzungstag zählt nicht mit; zwei wiederholte Kennungen; Sitzungstag nach Kölner
    Zeit (23:30 Uhr UTC am 22.10. ist der 23.10.). Wie bisher: geordnete Einträge, ein letzter Eintrag ohne Sitzungstag
    und ohne Ergebnis (der Stand folgt ihm, das Ende dem letzten Ergebnis), verschiedene Kennungen nach der Stelle,
    Einträge, die nicht entscheiden. Erfundene Einträge."""
    from pipeline import process

    def b(kennung, start, result, authoritative=True):
        return kennung, {"gremium": "Bezirksvertretung", "role": "Entscheidung", "authoritative": authoritative,
                         "start_date": start, "result": result}

    def stand_und_ende(*eintraege):
        """Stand wie export._paper_detail, Ende wie export._paths."""
        kennungen, schritte = [k for k, _ in eintraege], [s for _, s in eintraege]
        zaehlt = set(process.zaehlende(kennungen, [process.local_day(s["start_date"]) for s in schritte]).values())
        stand = process.stand({"process": [s for i, s in enumerate(schritte) if i in zaehlt]})
        return (stand,) + process.path_key({"process": schritte, "stand": stand}, kennungen)[1:]

    v1, v2, v3 = SITZUNGEN["v1"], SITZUNGEN["v2"], SITZUNGEN["v3"]   # 08.10., 22.10., 05.11.
    entschieden = ("entschieden", BESCHLOSSEN, "ergebnis")
    # Einträge einer Kennung nicht nach dem Sitzungstag geordnet (vorher jeweils Ende „vertagt“ bei „entschieden“)
    assert stand_und_ende(b("a", v3, BESCHLOSSEN), b("a", v1, VERTAGT), b("a", v2, VERTAGT)) == entschieden
    assert stand_und_ende(b("a", v3, BESCHLOSSEN), b("a", None, None), b("a", v2, VERTAGT)) == entschieden
    assert stand_und_ende(b("a", v3, BESCHLOSSEN), b("b", v3, BESCHLOSSEN), b("a", v1, VERTAGT),
                          b("b", v2, VERTAGT)) == entschieden
    assert stand_und_ende(b("a", "2026-10-22T23:30:00Z", BESCHLOSSEN), b("a", v2, VERTAGT)) == entschieden
    # wie bisher
    assert stand_und_ende(b("a", v1, VERTAGT), b("a", v2, VERTAGT), b("a", v3, BESCHLOSSEN)) == entschieden
    assert stand_und_ende(b("a", v1, VERTAGT), b("a", v2, VERTAGT), b("a", None, None)) == ("offen", VERTAGT,
                                                                                             "ergebnis")
    assert stand_und_ende(b("a", v3, BESCHLOSSEN), b("a", v1, VERTAGT), b("a", None, None)) == ("offen", VERTAGT,
                                                                                                "ergebnis")
    assert stand_und_ende(b("a", v3, BESCHLOSSEN), b("b", v1, VERTAGT)) == ("entschieden", VERTAGT, "ergebnis")
    assert stand_und_ende(b("a", v2, BESCHLOSSEN), b("b", v3, KENNTNIS, authoritative=False)) == entschieden
    assert stand_und_ende(b("a", v2, None), b("b", v3, KENNTNIS, authoritative=False)) == ("in Beratung",
                                                                                           "in Beratung", "stand")


# Entscheidung 17.11.2026 (16): Einträge abgesagter Sitzungen zählen für den Stand nicht (außer alle Einträge der
# Kennung sind abgesagt); check zählt die Wirkung und Widersprüche zwischen Stand und Ende des Weges
ABGESAGT = {"abg0": "2026-10-15T17:00:00+02:00", "abg": "2026-11-12T17:00:00+01:00"}


def _abgesagte_sitzungen(oparl):
    """Wie _sitzungen_mit_vertagung, dazu (erfunden) ein Beschluss am 22.10. (TOP b2) und zwei abgesagte Sitzungen der
    Bezirksvertretung 4: am 15.10. mit den TOPs a0 und a5 (vertagt), am 12.11. ohne TOP."""
    b = oparl.b
    _sitzungen_mit_vertagung(oparl)
    next(m for m in oparl.meetings if m["id"] == f"{b}/meetings/v2")["agendaItem"].append(
        {"id": f"{b}/agendaitems/b2", "number": "4.4", "name": "TOP b2", "result": BESCHLOSSEN, "public": True})
    tops = {"abg0": [("a0", "3.8"), ("a5", "3.9")], "abg": []}
    for m, beginn in ABGESAGT.items():
        oparl.meetings.append({
            "id": f"{b}/meetings/{m}", "type": "https://schema.oparl.org/1.1/Meeting", "name": GREMIUM, "start": beginn,
            "cancelled": True, "organization": [f"{b}/organizations/bv4"], "modified": "2026-11-13T08:00:00+01:00",
            "agendaItem": [{"id": f"{b}/agendaitems/{t}", "number": nr, "name": f"TOP {t}", "result": VERTAGT,
                            "public": True} for t, nr in tops[m]]})


def test_abgesagte_sitzung_zaehlt_nicht_fuer_den_stand(oparl, capsys, monkeypatch):
    """Entscheidung 17.11.2026 (16) (A): 1001/2026 (vertagt 08.10., Sitzung am 12.11. abgesagt, beschlossen 22.10.) und
    AN/102/2026 (geordnet: beschlossen 05.11., Sitzung am 12.11. abgesagt) sind „entschieden“, vorher „offen“ nach dem
    Eintrag der abgesagten Sitzung; die abgesagte Sitzung bleibt eine Station. 1003/2026 (alle Einträge abgesagt: 12.11.
    ohne Ergebnis, dann 15.10. vertagt) wie in (15) nach dem spätesten Tag „offen“. AN/104/2026 (beschlossen 05.11.,
    ein Eintrag ohne Sitzungstag, Sitzung am 12.11. abgesagt): Der letzte Eintrag ohne abgesagte Sitzung hat keinen
    Sitzungstag und zählt, „offen“. 1005/2026 (eine Kennung, ein Eintrag, Sitzung abgesagt, vertagt) unverändert „in
    Beratung“. AN/106/2026 (zwei Kennungen: beschlossen 05.11., danach im Rat vertagt 08.10.) „entschieden“.
    (16) (B): check zählt die Kennungen, bei denen wegen einer abgesagten Sitzung ein anderer Eintrag zählt (1001/2026,
    AN/102/2026, AN/104/2026), und die Widersprüche zwischen Stand und Ende des Weges in prozesse.json: AN/106/2026
    („entschieden“, Ende „vertagt“, Offen (8)) und AN/104/2026 („offen“, Ende der Beschluss). Die Zeilen sind keine
    Befunde: check endet ohne Befund, wenn die übrigen Prüfungen keinen haben."""
    b = oparl.b
    _abgesagte_sitzungen(oparl)
    oparl.papers.append(oparl.paper(6))
    oparl.papers[0]["consultation"] = [_eintrag(oparl, "k", "v1", "v1"), _eintrag(oparl, "k", "abg"),
                                       _eintrag(oparl, "k", "v2", "b2")]
    oparl.papers[1]["consultation"] = [_eintrag(oparl, "i", "v3", "v3"), _eintrag(oparl, "i", "abg")]
    oparl.papers[2]["consultation"] = [_eintrag(oparl, "c", "abg"), _eintrag(oparl, "c", "abg0", "a0")]
    oparl.papers[3]["consultation"] = [_eintrag(oparl, "u", "v3", "v3"), _eintrag(oparl, "u"),
                                       _eintrag(oparl, "u", "abg")]
    oparl.papers[4]["consultation"] = [_eintrag(oparl, "e", "abg0", "a5")]
    oparl.papers[5]["consultation"] = [_eintrag(oparl, "x", "v3", "v3"),
                                       _eintrag(oparl, "y", "v1", "w1", organization=[f"{b}/organizations/rat"])]
    _aufbauen(oparl, capsys)
    vorlagen = _exportiert()
    assert _stationen(vorlagen["1001/2026"])[0] == [(SITZUNGEN["v1"], GREMIUM, "3.1", VERTAGT),
                                                    (ABGESAGT["abg"], GREMIUM, None, None),
                                                    (SITZUNGEN["v2"], GREMIUM, "4.4", BESCHLOSSEN)]
    assert [x["status"] for x in vorlagen["1001/2026"]["process"]] == ["beraten", "abgesagt", "beraten"]
    assert _stationen(vorlagen["AN/104/2026"])[0] == [(SITZUNGEN["v3"], GREMIUM, "5.3", BESCHLOSSEN),
                                                      (None, GREMIUM, None, None),
                                                      (ABGESAGT["abg"], GREMIUM, None, None)]
    assert {ref: p["stand"] for ref, p in vorlagen.items()} == {
        "1001/2026": "entschieden", "AN/102/2026": "entschieden", "1003/2026": "offen", "AN/104/2026": "offen",
        "1005/2026": "in Beratung", "AN/106/2026": "entschieden"}
    # Ende des Weges in prozesse.json
    assert _enden(vorlagen["1001/2026"]) == _enden(vorlagen["AN/104/2026"]) == [(BESCHLOSSEN, "ergebnis")]
    assert _enden(vorlagen["1003/2026"]) == _enden(vorlagen["AN/106/2026"]) == [(VERTAGT, "ergebnis")]
    db = sqlite3.connect(config.DB)
    assert check.reihenfolge_wiederholter_kennungen(db) == (4, 2)
    assert check.abgesagte_wiederholter_kennungen(db) == (4, 3)
    assert check.stand_und_ende(db) == (1, 1, 6, 0, 0)
    db.close()
    for name, leer in (("gebiete", ([], [])), ("datenschutz", {"befunde": [], "fehlend": []}),
                       ("federfuehrung_kopf", []), ("zusatzthemen", ([], []))):
        monkeypatch.setattr(check, name, lambda *a, leer=leer: leer)
    check.check()
    aus = capsys.readouterr().out
    assert ("Kennungen mehrfach in derselben Vorlage, deren Einträge nicht nach dem Sitzungstag geordnet sind: 2 von 4 "
            + REGEL + "\nKennungen mehrfach in derselben Vorlage, bei denen wegen einer abgesagten Sitzung ein anderer "
            "Eintrag zählt: 3 von 4\nStand und Ende des Weges (prozesse.json) widersprechen sich: 1 Vorlagen mit Stand "
            "„entschieden“ und nicht abschließendem Ergebnis am Ende (etwa vertagt), 1 Vorlagen mit Entscheidung am "
            "Ende und anderem Stand, von 6 Vorlagen der Gebietsdateien mit Ergebnis am Ende\n") in aus
    assert aus.endswith("\nErgebnis\nAlle Prüfungen durchgeführt, keine Befunde.\n")


def test_abgesagte_sitzungen_massgeblich_weg_und_dossier(tmp_path):
    """Entscheidung 17.11.2026 (16) (A) mit erfundenen Einträgen: process.massgeblich und process.zaehlende mit Angabe
    abgesagter Sitzungen, das Ende des Weges (process.path_key) und die letzte Beratung in dossier._eintrag; vorher
    (Regel aus (15) ohne diese Angabe) zum Vergleich. Ohne Gebietsdateien ermittelt check.stand_und_ende nichts."""
    from pipeline import dossier, process
    m = process.massgeblich
    assert m(["2026-10-08", "2026-11-12", "2026-10-22"], [False, True, False]) == 2      # vorher 1
    assert m(["2026-11-05", "2026-11-12"], [0, 1]) == 0                                   # geordnet, vorher 1
    assert m(["2026-11-05", None, "2026-11-12"], [False, False, True]) == 1             # ohne Sitzungstag, vorher 2
    assert m(["2026-11-05", None, "2026-11-12"]) == 2
    assert m(["2026-11-12", "2026-10-15"], [True, True]) == m(["2026-11-12", "2026-10-15"]) == 0   # alle abgesagt
    assert m(["2026-10-15", None], [True, True]) == 1
    assert m(["2026-11-12"], [True]) == 0                                                 # ein Eintrag
    assert m(["2026-11-05", "2026-10-08"], [None, None]) == m(["2026-11-05", "2026-10-08"]) == 0
    assert m([], []) is None
    tage = ["2026-10-08", "2026-11-05", "2026-11-12", "2026-11-12"]
    assert process.zaehlende(["a", "b", "a", "b"], tage, [False, False, True, True]) == {"a": 0, "b": 1}
    assert process.zaehlende(["a", "b", "a", "b"], tage) == {"a": 2, "b": 3}

    def b(kennung, start, result, abgesagt=False):
        return kennung, {"gremium": "Bezirksvertretung", "role": "Entscheidung", "authoritative": True,
                         "start_date": start, "result": result, "cancelled": abgesagt}

    def stand_und_ende(*eintraege, absagen=True):
        """Stand wie export._paper_detail, Ende wie export._paths; ohne `absagen` nach der Regel aus (15)."""
        kennungen = [k for k, _ in eintraege]
        schritte = [s if absagen else {**s, "cancelled": False} for _, s in eintraege]
        zaehlt = set(process.zaehlende(kennungen, [process.local_day(s["start_date"]) for s in schritte],
                                       [s["cancelled"] for s in schritte]).values())
        stand = process.stand({"process": [s for i, s in enumerate(schritte) if i in zaehlt]})
        return (stand,) + process.path_key({"process": schritte, "stand": stand}, kennungen)[1:]

    v1, v2, abg, abg0 = SITZUNGEN["v1"], SITZUNGEN["v2"], ABGESAGT["abg"], ABGESAGT["abg0"]
    # Ende des Weges folgt dem Eintrag, der zählt: vorher die Vertagung der abgesagten Sitzung
    folge = (b("a", v2, BESCHLOSSEN), b("a", abg, VERTAGT, True))
    assert stand_und_ende(*folge) == ("entschieden", BESCHLOSSEN, "ergebnis")
    assert stand_und_ende(*folge, absagen=False) == ("in Beratung", VERTAGT, "ergebnis")
    # vertagt 08.10., abgesagt 12.11. ohne Ergebnis, beschlossen 22.10.: vorher „offen“ mit Beschluss am Ende
    folge = (b("a", v1, VERTAGT), b("a", abg, None, True), b("a", v2, BESCHLOSSEN))
    assert stand_und_ende(*folge) == ("entschieden", BESCHLOSSEN, "ergebnis")
    assert stand_und_ende(*folge, absagen=False) == ("offen", BESCHLOSSEN, "ergebnis")
    # alle abgesagt: wie (15)
    folge = (b("a", abg, None, True), b("a", abg0, VERTAGT, True))
    assert stand_und_ende(*folge) == stand_und_ende(*folge, absagen=False) == ("offen", VERTAGT, "ergebnis")

    def s(gremium, start, result, abgesagt=False):
        return {"gremium": gremium, "start_date": start, "result": result, "cancelled": abgesagt}

    p = {"reference": "1001/2026", "process": [s("A", v2, BESCHLOSSEN), s("B", abg, VERTAGT, True)]}
    assert dossier._eintrag(p, None, "2026-11-17")["letzte_beratung"] == {"gremium": "A", "date": "2026-10-22",
                                                                         "result": BESCHLOSSEN}   # vorher B
    p = {"reference": "1001/2026", "process": [s("A", abg, VERTAGT, True), s("B", abg0, VERTAGT, True)]}
    assert dossier._eintrag(p, None, "2026-11-17")["letzte_beratung"]["gremium"] == "A"   # alle abgesagt: wie (15)
    db = sqlite3.connect(":memory:")
    assert check.stand_und_ende(db, base=tmp_path) is None
    db.close()


def test_stand_und_ende_aus_den_gebietsdateien(tmp_path, oparl, capsys, monkeypatch):
    """Entscheidung 17.11.2026 (16) (B1), Wege von check.stand_und_ende mit erfundenen Gebietsdateien: Eine Vorlage in
    zwei Gebietsdateien zählt einmal (Stand „entschieden“, Ende „vertagt“), zwei Vorlagen mit derselben Drucksache
    zählen je für sich (nach source_object), eine Vorlage ohne Einträge in der Datenbank wird nicht gezählt, ebenso eine
    Vorlage der Datenbank in keiner Gebietsdatei. Dazu die Zeile von check.kennzahlen mit einer Vorlage ohne Datum und
    ohne Ortsbezug (sie steht in keiner Gebietsdatei, prozesse.json zählt sie mit) und ohne Export."""
    def station(start, result):
        return {"gremium": "Bezirksvertretung", "role": "Entscheidung", "authoritative": True, "start_date": start,
                "result": result, "cancelled": False}

    def vorlage(pid, ref, stand, *stationen):
        return {"reference": ref, "source_object": pid, "paper_type": "Antrag", "stand": stand,
                "process": list(stationen)}

    v1, v3 = SITZUNGEN["v1"], SITZUNGEN["v3"]
    zwei = vorlage("p/1", "AN/1/2026", "entschieden", station(v3, BESCHLOSSEN), station(v1, VERTAGT))
    gleiche_nummer = vorlage("p/2", "AN/1/2026", "entschieden", station(v3, BESCHLOSSEN))
    ohne_tag = vorlage("p/3", "AN/3/2026", "offen", station(v3, BESCHLOSSEN), station(None, None))
    ohne_db = vorlage("p/4", "AN/4/2026", "entschieden", station(v3, BESCHLOSSEN))
    for datei, vorlagen in (("ortsteile/a.json", [zwei, gleiche_nummer]), ("bezirke/x.json", [zwei, ohne_tag]),
                            ("ohne-ortsbezug/2026.json", [ohne_db])):
        (tmp_path / "gebiete" / datei).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "gebiete" / datei).write_text(json.dumps({"papers": vorlagen}), encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE paper (id TEXT)")
    db.execute("CREATE TABLE consultation (id TEXT, paper_id TEXT, position INTEGER)")
    db.executemany("INSERT INTO paper VALUES (?)", [("p/1",), ("p/2",), ("p/3",), ("p/4",), ("p/5",)])
    db.executemany("INSERT INTO consultation VALUES (?, ?, ?)", [("y", "p/1", 1), ("x", "p/1", 0), ("z", "p/2", 0),
                                                                 ("a", "p/3", 0), ("a", "p/3", 1)])
    assert check.stand_und_ende(db, base=tmp_path / "gebiete") == (1, 1, 3, 1, 1)
    db.close()

    # AN/104/2026: ohne Datum und ohne Ortsbezug (im Rat beraten, also auch kein Stadtbezirk über die Bezirksvertretung)
    oparl.papers[3].pop("date")
    oparl.papers[3]["consultation"] = [_beratung(oparl, 4, 4, organization=[f"{oparl.b}/organizations/rat"])]
    _aufbauen(oparl, capsys)
    assert "AN/104/2026" not in _exportiert()
    wege = json.loads((config.EXPORT / config.STADT / "prozesse.json").read_text(encoding="utf-8"))["types"]
    assert sum(t["count"] for t in wege) == 5
    db = sqlite3.connect(config.DB)
    check.kennzahlen(db)
    assert ("Stand und Ende des Weges (prozesse.json) widersprechen sich: 0 Vorlagen mit Stand „entschieden“ und nicht "
            "abschließendem Ergebnis am Ende (etwa vertagt), 0 Vorlagen mit Entscheidung am Ende und anderem Stand, "
            "von 4 Vorlagen der Gebietsdateien mit Ergebnis am Ende; 1 Vorlagen der Datenbank in keiner Gebietsdatei, "
            "nicht gezählt\n") in capsys.readouterr().out
    monkeypatch.setattr(config, "EXPORT", tmp_path / "ohne-export")
    check.kennzahlen(db)
    assert ("Stand und Ende des Weges (prozesse.json) widersprechen sich: nicht ermittelt (Gebietsdateien des Exports "
            "fehlen)\n") in capsys.readouterr().out
    db.close()


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
