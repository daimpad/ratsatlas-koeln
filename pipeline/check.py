"""Prüfung: Kennzahlen gegen den Phase-0-Bericht, Verknüpfungsquote, Datenschutz."""
import json
import re
import sqlite3

from . import actors, besetzung, config, kontext, maske

# Werte aus phase0/BERICHT_phase0.md (Abruf 17.10.2026)
PHASE0 = {
    "Vorlagen": 24912,
    "Vorlagen mit Koordinate": 1814,
    "Vorlagen mit Koordinate in einem Ortsteil": None,
    f"Vorlagen in {config.PILOT_ORTSTEIL} (Stufe A)": 98,
    "Ortsteile mit mind. einer Vorlage": 50,
}


def check():
    db = sqlite3.connect(config.DB)
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    pct = lambda n, d: f"{n} von {d} ({100 * n / d:.1f} %)" if d else "–"

    found = {
        "Vorlagen": one("SELECT COUNT(*) FROM paper"),
        "Vorlagen mit Koordinate": one(
            "SELECT COUNT(DISTINCT pl.paper_id) FROM paper_location pl "
            "JOIN location l ON l.id = pl.location_id WHERE l.lon IS NOT NULL"),
        "Vorlagen mit Koordinate in einem Ortsteil": one(
            "SELECT COUNT(DISTINCT pl.paper_id) FROM paper_location pl "
            "JOIN location l ON l.id = pl.location_id WHERE l.ortsteil IS NOT NULL"),
        f"Vorlagen in {config.PILOT_ORTSTEIL} (Stufe A)": one(
            "SELECT COUNT(DISTINCT pl.paper_id) FROM paper_location pl JOIN location l "
            "ON l.id = pl.location_id WHERE l.ortsteil = ? AND pl.stage = 'A'", config.PILOT_ORTSTEIL),
        f"Vorlagen in {config.PILOT_ORTSTEIL} (alle Stufen)": one(
            "SELECT COUNT(DISTINCT pl.paper_id) FROM paper_location pl "
            "JOIN location l ON l.id = pl.location_id WHERE l.ortsteil = ?", config.PILOT_ORTSTEIL),
        "Ortsteile mit mind. einer Vorlage": one(
            "SELECT COUNT(DISTINCT ortsteil) FROM location WHERE ortsteil IS NOT NULL"),
    }
    print("Kennzahl\tPhase 0\tjetzt")
    for k, v in found.items():
        print(f"{k}\t{PHASE0.get(k) if PHASE0.get(k) is not None else '–'}\t{v}")

    cons = one("SELECT COUNT(*) FROM consultation")
    print("\nVerknüpfung Beratung ↔ Sitzung (OParl-Lite)")
    print("mit Sitzung:", pct(one("SELECT COUNT(*) FROM consultation WHERE meeting_id IS NOT NULL"), cons))
    print("mit TOP-Ergebnis:", pct(one(
        "SELECT COUNT(*) FROM consultation c JOIN agenda_item a ON a.id = c.agenda_item_id "
        "WHERE a.result IS NOT NULL AND a.result <> ''"), cons))

    politik = tuple(actors.POLITIK_TYPES)
    marks = ",".join("?" * len(politik))
    n_pol = one(f"SELECT COUNT(*) FROM paper WHERE paper_type IN ({marks})", *politik)
    n_pol_orig = one(
        f"SELECT COUNT(DISTINCT p.id) FROM paper p JOIN paper_originator o ON o.paper_id = p.id "
        f"WHERE p.paper_type IN ({marks})", *politik)
    print("\nEinreichende")
    print("Anträge/Anfragen mit abgeleiteten Einreichenden:", pct(n_pol_orig, n_pol))
    print("Vorlagen mit Einreichenden insgesamt:",
          pct(one("SELECT COUNT(DISTINCT paper_id) FROM paper_originator"), found["Vorlagen"]))
    print("davon einer Ratsfraktion/-gruppe zugeordnet:",
          one("SELECT COUNT(*) FROM paper_originator WHERE actor_type IN ('Fraktion/Gruppe', 'Bezirksfraktion') "
              "AND organization_id IS NOT NULL"), "von",
          one("SELECT COUNT(*) FROM paper_originator WHERE actor_type IN ('Fraktion/Gruppe', 'Bezirksfraktion')"),
          "Nennungen")

    n_co = one("SELECT COUNT(*) FROM paper p JOIN organization o ON o.id = p.under_direction_of "
               "WHERE o.classification = ?", actors.CO_DEZERNAT)
    n_co_res = one("SELECT COUNT(DISTINCT paper_id) FROM paper_responsibility WHERE kind = 'fachlich'")
    print("\nCo-Dezernat")
    print("fachliche Zuständigkeit über Stellungnahme abgeleitet:", pct(n_co_res, n_co))

    print("\nGeokodierung")
    for stage in ("A", "B"):
        print(f"Vorlagen mit Ortsbezug Stufe {stage}:", pct(one(
            "SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE stage = ? AND method <> 'vererbt'",
            stage), found["Vorlagen"]))
    print("Vorlagen mit vererbtem Ortsbezug:",
          one("SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE method = 'vererbt'"))
    print("Vorlagen mit Ortsbezug insgesamt:",
          pct(one("SELECT COUNT(DISTINCT paper_id) FROM paper_location"), found["Vorlagen"]))
    # Stufe B gegen Stufe A, für Vorlagen mit beidem. Straßentreffer aus OParl-Locations sind nicht
    # unabhängig von Stufe A (gleiche Punkte) und werden getrennt ausgewiesen.
    n_a = one("SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE stage = 'A' AND method <> 'vererbt'")
    pairs = db.execute(
        "SELECT b.paper_id, lb.level || ' (' || lb.source || ')', (SELECT COUNT(*) FROM paper_location a "
        "JOIN location la ON la.id = a.location_id WHERE a.paper_id = b.paper_id AND a.stage = 'A' "
        "AND la.ortsteil = lb.ortsteil) FROM paper_location b JOIN location lb ON lb.id = b.location_id "
        "WHERE b.stage = 'B' AND b.method <> 'vererbt' AND lb.level <> 'stadtbezirk' AND b.paper_id IN "
        "(SELECT paper_id FROM paper_location WHERE stage = 'A' AND method <> 'vererbt')").fetchall()
    print("Vorlagen mit Stufe A, für die Stufe B einen Ortsteil findet:",
          pct(len({p for p, *_ in pairs}), n_a))
    # je Vorlage: trifft mindestens ein Ortsbezug dieser Art den Ortsteil aus Stufe A?
    for kind in sorted({k for _, k, _ in pairs}):
        hits = {}
        for pid, k, ok in pairs:
            if k == kind:
                hits[pid] = hits.get(pid, False) or bool(ok)
        note = " – nicht unabhängig von Stufe A" if "oparl-bonn" in kind else ""
        print(f"  Vorlagen mit Ortsteil wie Stufe A, Ebene {kind}:",
              pct(sum(hits.values()), len(hits)) + note)

    # Straße und Beschreibung der Orte aus der OParl-API; Postleitzahlen sind keine Hausnummern
    texts = [r[0] for r in db.execute(
        "SELECT street FROM location WHERE street IS NOT NULL AND source = 'oparl-bonn' UNION ALL "
        "SELECT description FROM location WHERE description IS NOT NULL AND source = 'oparl-bonn'")]
    with_number = [s for s in texts if re.search(r"\d", re.sub(r"\b5[0-9]{4}\b", "", s))]
    with_nr = one("SELECT COUNT(DISTINCT paper_id) FROM paper_plan")
    with_area = one("SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE method = 'bebauungsplan'")
    print("\nBebauungspläne")
    print("Vorlagen mit Plannummer im Titel:", with_nr, "· davon mit Geltungsbereich:", pct(with_area, with_nr))

    print("\nDatenschutz")
    print("Orte mit Hausnummer in Straße oder Beschreibung:", len(with_number), with_number[:5])
    offen = titel_mit_hausnummer(maske.aus_db(db))
    print("Titel aus Einwohnerschaft, Bauordnung und Naturschutz mit Hausnummer in Suche und GeoJSON:", len(offen), offen[:5])
    db.close()
    if with_number:
        raise SystemExit("Prüfung fehlgeschlagen: Hausnummern in Ortsangaben (CLAUDE.md 5.2).")
    if offen:
        raise SystemExit("Prüfung fehlgeschlagen: Hausnummern in Titeln aus Einwohnerschaft, Bauordnung oder Naturschutz (maske.py).")

    print("\nBesetzung der Gremien")
    if config.BESETZUNG.exists():
        doc = json.loads(config.BESETZUNG.read_text())
        befunde = besetzung.pruefen_auszug(doc)
        pz = config.EXPORT / "bonn" / "prozessarten.json"
        if pz.exists():
            befunde += [f"prozessarten.json: {b}" for b in besetzung.pruefen_auszug(
                {"mitgliedschaften": [], **{"rest": json.loads(pz.read_text())}})]
        print(f"{len(doc['mitgliedschaften'])} laufende Mitgliedschaften, {len(doc['personen'])} Personen namentlich; "
              f"Befunde: {befunde or 'keine'}")
        if befunde:
            raise SystemExit(f"Prüfung fehlgeschlagen: Besetzung ({'; '.join(befunde)}).")

    print("\nKontextdaten je Ortsteil")
    if befunde := kontext.pruefen():
        raise SystemExit(f"Prüfung fehlgeschlagen: Kontextdaten ({'; '.join(befunde)}).")


def titel_mit_hausnummer(m, base=None):
    """Drucksachen aus der Einwohnerschaft, deren Titel in suche.json oder vorlagen.geojson noch eine Hausnummer
    trägt (Entscheidung des Auftraggebers 24.10.2026: überall ausblenden)."""
    base = base or config.EXPORT / "bonn"
    offen = set()
    if (f := base / "suche.json").exists():
        offen |= {r[0] for r in json.loads(f.read_text())["rows"] if m.offen(r[1], r[0])}
    if (f := base / "vorlagen.geojson").exists():
        offen |= {x["properties"]["reference"] for x in json.loads(f.read_text())["features"]
                  if m.offen(x["properties"].get("name"), x["properties"]["reference"])}
    return sorted(offen)
