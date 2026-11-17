"""Beratungen je Beratung und Vorlage (Entscheidung 17.11.2026 (11)): Dieselbe Kennung einer Beratung kann in mehreren
Vorlagen stehen (etwa mehrere Vorlagen unter einem Tagesordnungspunkt). Vorher war `id` der einzige Schlüssel der
Tabelle consultation, und die Vorlage, deren Eintrag überschrieben wurde, verlor die Station still. Jetzt behält jede
Vorlage ihre Station (Prozesslinie mit Datum, Gremium, TOP und Ergebnis im Export, Zählung in check); eine Kennung, die
in derselben Vorlage mehrfach steht, bleibt dort eine Zeile wie bisher und wird gezählt. Abruf und Format von
beratungen.jsonl bleiben unverändert. Alle Objekte sind erfunden (lokaler Testserver); keine Anfragen an die Stadt."""
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
    behält ihre Station mit Datum, Gremium, TOP und Ergebnis (vorher nur die zuletzt gelesene Vorlage), jede mit ihrem
    eigenen TOP (vorher hätten beide den TOP der zuletzt gelesenen Zeile von beratungen.jsonl bekommen); check zählt
    jede Zeile; Log von build und Ausgabe von check nennen Einträge, Zeilen und Kennungen in mehreren Vorlagen."""
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
    assert db.execute("SELECT COUNT(*), COUNT(DISTINCT id), SUM(entries) FROM consultation").fetchone() == (5, 2, 5)
    check.kennzahlen(db)
    aus = capsys.readouterr().out
    assert "mit Sitzung: 5 von 5 (100.0 %)" in aus and "mit TOP-Ergebnis: 5 von 5 (100.0 %)" in aus
    zeile = ("Beratungen: 5 Einträge in 5 Zeilen der Datenbank (je Beratung und Vorlage eine); 2 Kennungen in mehreren "
             "Vorlagen (5 Einträge, 5 Vorlagen, je Vorlage eine Zeile); 0-mal eine Kennung mehrfach in derselben Vorlage "
             "(0 Einträge, dort je eine Zeile)")
    assert zeile + "\n" in aus
    assert zeile + ("; 2 Einträge mit einer Kennung, die in beratungen.jsonl mit verschiedener Sitzung oder "
                    "verschiedenem TOP steht (je Vorlage nach ihren eigenen Verweisen zugeordnet)\n") in log
    # Zusammenfassung (Entscheidung 17.11.2026 (11) (B)): was gezählt wird; nur TOPs mit Beratung einer Vorlage
    assert "5 Vorlagen, 5 Beratungen (Einträge), 1 Sitzungen und 3 TOPs mit Beratung einer Vorlage, " in log
    db.close()


def test_wiederholte_kennung_in_derselben_vorlage(oparl, capsys, monkeypatch):
    """Steht eine Kennung in derselben Vorlage zweimal, bleibt dort wie bisher eine Zeile (der letzte Eintrag) mit
    `entries` 2; Log, check und verify (Zahl der Beratungen gegen die Quelle) zählen beide Einträge."""
    oparl.papers[0]["consultation"] = [_beratung(oparl, "a", 1, role="Beratung", authoritative=False),
                                       _beratung(oparl, "b", 2, role="Beratung", authoritative=False),
                                       _beratung(oparl, "a", 1)]
    log = _aufbauen(oparl, capsys)
    db = sqlite3.connect(config.DB)
    pid = oparl.papers[0]["id"]
    assert db.execute("SELECT id, position, role, entries FROM consultation WHERE paper_id = ? ORDER BY position",
                      (pid,)).fetchall() == [(f"{oparl.b}/consultations/b", 1, "Beratung", 1),
                                             (f"{oparl.b}/consultations/a", 2, "Entscheidung", 2)]
    assert _stationen(_exportiert()["1001/2026"])[0] == [(BEGINN, GREMIUM, "8.2", KENNTNIS),
                                                         (BEGINN, GREMIUM, "8.1", BESCHLOSSEN)]
    zeile = ("Beratungen: 7 Einträge in 6 Zeilen der Datenbank (je Beratung und Vorlage eine); 0 Kennungen in mehreren "
             "Vorlagen (0 Einträge, 0 Vorlagen, je Vorlage eine Zeile); 1-mal eine Kennung mehrfach in derselben Vorlage "
             "(2 Einträge, dort je eine Zeile)")
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
    """build._sitzung_und_top: gleiche Zeilen (oder eine, wie aus OParl-Lite in Bonn) wie bisher die letzte; sonst die
    Zeile, die zu den eigenen Verweisen der Beratung passt (Sitzung und TOP, dann der TOP, dann die Sitzung ohne TOP),
    und ohne passende Zeile keine (sessionnet.beratungen schrieb für diese Vorlage keine)."""
    def zeile(m, t, nr=None):
        return {"uri": "c", "meeting": {"uri": m} if m else None,
                "agendaItem": {"uri": t, "number": nr} if t else None}
    wahl = build._sitzung_und_top
    assert wahl([], {"id": "c"}) == {}
    einzeln = zeile("m1", "t1")
    assert wahl([einzeln], {"id": "c"}) is einzeln                      # Bonn: Beratung ohne Verweise
    gleich = [zeile("m1", "t1", "1"), zeile("m1", "t1", "2")]
    assert wahl(gleich, {"id": "c", "meeting": "m9", "agendaItem": "t9"}) is gleich[-1]
    verschieden = [zeile("m1", "t1"), zeile("m2", "t2"), zeile("m3", None), zeile("m4", "t2")]
    assert wahl(verschieden, {"meeting": "m2", "agendaItem": "t2"}) is verschieden[1]   # Sitzung und TOP
    assert wahl(verschieden, {"meeting": "m1", "agendaItem": "t1"}) is verschieden[0]
    # Sitzung aus dem TOP (die eigene Sitzung fehlt in der Liste oder kommt nicht als Zeichenkette): der TOP
    assert wahl(verschieden, {"meeting": "fehlt", "agendaItem": "t1"}) is verschieden[0]
    assert wahl(verschieden, {"meeting": ["m1"], "agendaItem": "t2"}) is verschieden[3]
    assert wahl(verschieden, {"meeting": "m3", "agendaItem": "fehlt"}) is verschieden[2]    # Sitzung ohne TOP
    assert wahl(verschieden, {"meeting": "m3"}) is verschieden[2]
    # nichts passt: keine Sitzung und kein TOP einer anderen Vorlage
    assert wahl(verschieden, {"meeting": "m9", "agendaItem": "t9"}) == {}
    assert wahl(verschieden, {"meeting": "m1"}) == {} and wahl(verschieden, {}) == {}


def test_beratungen_aeltere_datenbank():
    """check.beratungen_je_vorlage liest eine ältere Datenbank ohne Spalte `entries` (eine Zeile je Kennung)."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE consultation (id TEXT PRIMARY KEY, paper_id TEXT)")
    db.executemany("INSERT INTO consultation VALUES (?, ?)", [("c1", "p1"), ("c2", "p1"), ("c3", "p2")])
    assert check.beratungen_je_vorlage(db) == ("Beratungen: 3 Zeilen der Datenbank (Einträge nicht erfasst: Datenbank "
                                               "ohne Spalte entries)")


def test_beratungen_zeile_zaehlt():
    """build.beratungen_zeile: Kennungen in mehreren Vorlagen (mit ihren Einträgen, auch Wiederholungen darin, und
    Vorlagen) und Wiederholungen in derselben Vorlage, je Paar aus Kennung und Vorlage."""
    cons = [("c1", "p1"), ("c1", "p2"), ("c1", "p2"), ("c1", "p3"), ("c2", "p1"), ("c3", "p4"), ("c3", "p4"),
            ("c3", "p4"), ("c4", "p5"), ("c4", "p6")]
    assert build.beratungen_zeile(cons, 3) == (
        "Beratungen: 10 Einträge in 7 Zeilen der Datenbank (je Beratung und Vorlage eine); 2 Kennungen in mehreren "
        "Vorlagen (6 Einträge, 5 Vorlagen, je Vorlage eine Zeile); 2-mal eine Kennung mehrfach in derselben Vorlage "
        "(5 Einträge, dort je eine Zeile); 3 Einträge mit einer Kennung, die in beratungen.jsonl mit verschiedener "
        "Sitzung oder verschiedenem TOP steht (je Vorlage nach ihren eigenen Verweisen zugeordnet)")
