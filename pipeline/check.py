"""Prüfung der aufbereiteten Daten (Ratsatlas Köln): Kennzahlen, Gebiete, Datenschutz, Zusatzthemen.

Aufruf: `python -m pipeline check` nach `build`, `export` und `kontext`. Liest die Datenbank (config.DB) und die Exporte
unter config.EXPORT / config.STADT (data/export/koeln). Fehlt eine Datei, die eine Prüfung braucht, gilt die Prüfung als
nicht durchgeführt: `check` meldet das und schlägt fehl, statt still zu bestehen.
Die Bonner Vergleichswerte (Phase-0-Bericht Bonn, Pilot-Ortsteil) gelten für Köln nicht und sind entfernt; Kölner
Vergleichswerte folgen mit der Messung der OParl-API (CLAUDE.md 7.1 und 9). Zusatzthemen werden nur geprüft, wenn sie in
config.ZUSATZTHEMEN freigegeben sind; abgeschaltete weist die Ausgabe als solche aus.
"""
import csv
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from . import actors, besetzung, config, geocode, kontext, maske

# Gebiete laut CLAUDE.md 2: ganz Köln mit 86 Stadtteilen und 9 Stadtbezirken
STADTTEILE, STADTBEZIRKE = 86, 9
# Hauskoordinate: Ebene „adresse“, Methode und Quelle wie in geocode.Gazetteer._adresspunkt
PUNKT = "strasse+hausnummer_punkt"
# Gebietsdateien des Exports (Vorlagen mit Ortsbezügen für Karte und Liste der Seite); „ohne-ortsbezug“ fehlt zu Recht,
# wenn jede Vorlage einen Ortsbezug hat
GEBIETSDATEIEN = ("ortsteile", "bezirke", "ohne-ortsbezug")
GEBIETSDATEIEN_PFLICHT = ("ortsteile", "bezirke")
# Zählungen der Datenschutzprüfung: Schlüssel → Bezeichnung in der Ausgabe
ZAEHLUNG = {
    "ortsangaben": "Ortsangaben der OParl-API (Straße, Beschreibung) untersucht",
    "vorlagen": "Vorlagen in der Datenbank untersucht",
    "ohne_hauskoordinate": "davon ohne Erlaubnis für Hauskoordinaten (§ 24 GO NRW, natürliche Personen, Ausschuss "
                           "für Anregungen und Beschwerden, Vorlagenart nicht erkennbar, Titel ohne Hausnummer, "
                           "verbundene Vorlagen auch über relatedPaper, dieselbe Drucksache)",
    "vorlagenart_nicht_erkennbar": "davon mit leerer oder nicht erkennbarer Vorlagenart (Entscheidung 10.11.2026)",
    "hauskoordinaten": "Vorlagen mit Hauskoordinate in der Datenbank",
    "oparl_punkte": "Vorlagen mit genauem Punkt aus der Ortsangabe der Stadt (OParl) in der Datenbank",
    "suche": "Titel in suche.json untersucht",
    "titel_geschuetzt": "davon aus Einwohnerschaft, Bauordnung oder Naturschutz samt verbundenen Vorlagen (auch über "
                        "relatedPaper) und derselben Drucksache (Hausnummer ausgeblendet)",
    "titel_restzahlen": "davon mit einer Zahl außerhalb bekannter Zusammenhänge (grobe zweite Probe, maske.restzahlen; "
                        "nur Hinweis, von Hand prüfen)",
    "ortsnamen": "Ortsnamen in vorlagen.geojson und den Gebietsdateien untersucht",
    "geojson": "Punkte in vorlagen.geojson untersucht",
    "geojson_hauskoordinaten": "davon auf einer Hauskoordinate",
    "gebietsdateien": "Vorlagen in den Gebietsdateien der Karte untersucht",
    "gebietsdateien_hauskoordinaten": "davon mit Hauskoordinate",
    "stichprobe_hausnummern": "Titel in der Stichprobe Hausnummern untersucht",
    "stichprobe_volltext": "Titel und Orte in der Stichprobe Volltext untersucht",
    "stichprobe_objekte": "Titel und Orte in der Stichprobe Gebäude und Anlagen untersucht",
    "tabellen_mit_titel": "TSV-Dateien mit Drucksache und Titel unter data/export untersucht (Datenpaket)",
    "tabellen_zeilen": "davon Zeilen",
    "fundstellen": "Fundstellen aus dem Titel in vorlagen.geojson, den Gebietsdateien und plaene.json untersucht",
}
# Spalten der TSV-Dateien mit Drucksache und Titel, die Teile des Titels oder einen Ortsnamen tragen (Fundstelle,
# Treffer): geprüft wie der Titel (Prüfung r20a; vorher nur „titel“); dazu der Ort der Stichprobe je Methode und die
# zurückgestellten Ortsbezüge im Audit der Bebauungspläne (zweite Korrektur)
TSV_TEXTSPALTEN = {"titel", "fundstelle", "treffer", "ort", "zurueckgestellt"}


def check():
    """Alle Prüfungen nacheinander; am Ende Abbruch mit allen Befunden und nicht durchgeführten Prüfungen."""
    if not config.DB.exists():
        raise SystemExit(f"Prüfung nicht durchgeführt: Datenbank {config.DB} fehlt "
                         "(zuerst `python -m pipeline build`).")
    db = sqlite3.connect(config.DB)
    try:
        kennzahlen(db)
        befunde, fehlend = gebiete(db)
        ds = datenschutz(db)
    finally:
        db.close()
    befunde += ds["befunde"]
    fehlend += ds["fehlend"]
    b, f = zusatzthemen()
    befunde += b
    fehlend += f

    print("\nErgebnis")
    for x in fehlend:
        print(f"NICHT DURCHGEFÜHRT – {x}")
    for x in befunde:
        print(f"BEFUND – {x}")
    if befunde or fehlend:
        teile = ([f"Befunde: {'; '.join(befunde)}"] if befunde else []) + \
                ([f"nicht durchgeführt (Datei fehlt): {'; '.join(fehlend)}"] if fehlend else [])
        raise SystemExit("Prüfung fehlgeschlagen – " + " | ".join(teile))
    print("Alle Prüfungen durchgeführt, keine Befunde.")


def _pct(n, d):
    return f"{n} von {d} ({100 * n / d:.1f} %)" if d else "–"


def kennzahlen(db):
    """Kennzahlen zur Übersicht. Ohne Vergleichswerte: die Kölner OParl-API ist noch nicht gemessen (CLAUDE.md 9); die
    Werte des Bonner Phase-0-Berichts und der Bonner Pilot-Ortsteil gelten für Köln nicht."""
    def one(sql, *a):
        return db.execute(sql, a).fetchone()[0]

    n = one("SELECT COUNT(*) FROM paper")
    print("Kennzahlen (Vergleichswerte: keine – Kölner OParl-API noch nicht gemessen; Bonner Werte gelten nicht)")
    print("Pilot-Stadtteil: keiner (ganz Köln, CLAUDE.md 2)")
    print("Vorlagen:", n)
    # build lässt Vorlagen ohne `reference` oder mit einer, die keine Zeichenkette ist, aus (build.einlesen), statt eine
    # Nummer zu erfinden; je Grund eine Zeile
    from .build import AUSLASSUNG
    for grund, text in AUSLASSUNG.items():
        print(f"Vorlagen {text} (beim Aufbau ausgelassen):",
              one("SELECT COUNT(*) FROM skipped_paper WHERE reason = ?", grund) if _hat_ausgelassene(db)
              else "nicht erfasst (Datenbank ohne Tabelle skipped_paper)")
    print("Vorlagen mit Koordinate:", one(
        "SELECT COUNT(DISTINCT pl.paper_id) FROM paper_location pl "
        "JOIN location l ON l.id = pl.location_id WHERE l.lon IS NOT NULL"))
    print("Vorlagen mit Koordinate in einem Stadtteil:", one(
        "SELECT COUNT(DISTINCT pl.paper_id) FROM paper_location pl "
        "JOIN location l ON l.id = pl.location_id WHERE l.ortsteil IS NOT NULL"))
    print("Stadtteile mit mind. einer Vorlage:", _pct(one(
        "SELECT COUNT(DISTINCT ortsteil) FROM location WHERE ortsteil IS NOT NULL"), STADTTEILE))

    cons = one("SELECT COUNT(*) FROM consultation")
    print("\nVerknüpfung Beratung ↔ Sitzung (OParl-API Köln: consultation verweist auf meeting und agendaItem)")
    print("mit Sitzung:", _pct(one("SELECT COUNT(*) FROM consultation WHERE meeting_id IS NOT NULL"), cons))
    print("mit TOP-Ergebnis:", _pct(one(
        "SELECT COUNT(*) FROM consultation c JOIN agenda_item a ON a.id = c.agenda_item_id "
        "WHERE a.result IS NOT NULL AND a.result <> ''"), cons))

    typen = sorted({r[0] for r in db.execute("SELECT DISTINCT paper_type FROM paper") if r[0] in actors.POLITIK_TYPES})
    marks = ",".join("?" * len(typen))
    n_pol = one(f"SELECT COUNT(*) FROM paper WHERE paper_type IN ({marks})", *typen) if typen else 0
    n_pol_orig = one(
        f"SELECT COUNT(DISTINCT p.id) FROM paper p JOIN paper_originator o ON o.paper_id = p.id "
        f"WHERE p.paper_type IN ({marks})", *typen) if typen else 0
    print("\nEinreichende")
    print("Anträge/Anfragen mit abgeleiteten Einreichenden:", _pct(n_pol_orig, n_pol))
    print("Vorlagen mit Einreichenden insgesamt:",
          _pct(one("SELECT COUNT(DISTINCT paper_id) FROM paper_originator"), n))
    print("davon einer Ratsfraktion/-gruppe zugeordnet:",
          one("SELECT COUNT(*) FROM paper_originator WHERE actor_type IN ('Fraktion/Gruppe', 'Bezirksfraktion') "
              "AND organization_id IS NOT NULL"), "von",
          one("SELECT COUNT(*) FROM paper_originator WHERE actor_type IN ('Fraktion/Gruppe', 'Bezirksfraktion')"),
          "Nennungen")

    n_co = one("SELECT COUNT(*) FROM paper p JOIN organization o ON o.id = p.under_direction_of "
               "WHERE o.classification = ?", actors.CO_DEZERNAT)
    print("\nCo-Dezernat (Einstufung der Bonner Verwaltungsbereiche)")
    if n_co:
        print("fachliche Zuständigkeit über Stellungnahme abgeleitet:", _pct(one(
            "SELECT COUNT(DISTINCT paper_id) FROM paper_responsibility WHERE kind = 'fachlich'"), n_co))
    else:
        print("nicht anwendbar: keine Vorlage mit federführendem „Co-Dezernat“ (ob die Kölner API diese Einstufung "
              "kennt, ist ungemessen)")

    print("\nGeokodierung")
    for stage in ("A", "B"):
        print(f"Vorlagen mit Ortsbezug Stufe {stage}:", _pct(one(
            "SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE stage = ? AND method <> 'vererbt'", stage), n))
    print("Vorlagen mit vererbtem Ortsbezug:",
          one("SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE method = 'vererbt'"))
    print("Vorlagen mit Ortsbezug insgesamt:", _pct(one("SELECT COUNT(DISTINCT paper_id) FROM paper_location"), n))
    # Stufe B gegen Stufe A, für Vorlagen mit beidem. Straßentreffer aus OParl-Locations sind nicht
    # unabhängig von Stufe A (gleiche Punkte) und werden getrennt ausgewiesen.
    n_a = one("SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE stage = 'A' AND method <> 'vererbt'")
    pairs = db.execute(
        "SELECT b.paper_id, lb.level || ' (' || lb.source || ')', (SELECT COUNT(*) FROM paper_location a "
        "JOIN location la ON la.id = a.location_id WHERE a.paper_id = b.paper_id AND a.stage = 'A' "
        "AND la.ortsteil = lb.ortsteil) FROM paper_location b JOIN location lb ON lb.id = b.location_id "
        "WHERE b.stage = 'B' AND b.method <> 'vererbt' AND lb.level <> 'stadtbezirk' AND b.paper_id IN "
        "(SELECT paper_id FROM paper_location WHERE stage = 'A' AND method <> 'vererbt')").fetchall()
    print("Vorlagen mit Stufe A, für die Stufe B einen Stadtteil findet:", _pct(len({p for p, *_ in pairs}), n_a))
    # je Vorlage: trifft mindestens ein Ortsbezug dieser Art den Stadtteil aus Stufe A?
    for kind in sorted({k for _, k, _ in pairs}):
        hits = {}
        for pid, k, ok in pairs:
            if k == kind:
                hits[pid] = hits.get(pid, False) or bool(ok)
        note = " – nicht unabhängig von Stufe A" if config.QUELLE_OPARL in kind else ""
        print(f"  Vorlagen mit Stadtteil wie Stufe A, Ebene {kind}:", _pct(sum(hits.values()), len(hits)) + note)

    with_nr = one("SELECT COUNT(DISTINCT paper_id) FROM paper_plan")
    with_area = one("SELECT COUNT(DISTINCT paper_id) FROM paper_location WHERE method = 'bebauungsplan'")
    print("\nBebauungspläne")
    print("Vorlagen mit Plannummer im Titel:", with_nr, "· davon mit Geltungsbereich:", _pct(with_area, with_nr))


def gebiete(db):
    """Kölner Gebiete: 86 Stadtteile und 9 Stadtbezirke in den Geodaten (CLAUDE.md 2); jeder Ort in der Datenbank
    liegt in einem davon. Liefert (Befunde, nicht durchgeführte Prüfungen)."""
    befunde, fehlend = [], []
    print("\nGebiete")
    for art, einzahl, pfad, feld, spalte, soll in (
            ("Stadtteile", "Stadtteil", config.ORTSTEILE, "ortsteil_bez", "ortsteil", STADTTEILE),
            ("Stadtbezirke", "Stadtbezirk", config.STADTBEZIRKE, "bezirk_bez", "stadtbezirk", STADTBEZIRKE)):
        if not pfad.exists():
            fehlend.append(_fehlt("Gebiete", pfad, "geo-koeln"))
            continue
        namen = {f["properties"][feld] for f in json.loads(pfad.read_text())["features"]}
        fremd = sorted({r[0] for r in db.execute(
            f"SELECT DISTINCT {spalte} FROM location WHERE {spalte} IS NOT NULL")} - namen)
        print(f"{art} in den Geodaten: {len(namen)} (CLAUDE.md 2: {soll}); "
              f"Orte mit einem {einzahl} außerhalb dieser Liste: {len(fremd)}")
        if len(namen) != soll:
            befunde.append(f"Gebiete: {len(namen)} {art} in {pfad.name}, erwartet {soll} (CLAUDE.md 2)")
        if fremd:
            befunde.append(f"Gebiete: Orte mit {einzahl} außerhalb der Kölner Geodaten: {', '.join(fremd[:5])}")
    return befunde, fehlend


def _fehlt(bereich, pfad, schritt):
    text = f"{bereich}: {pfad} fehlt (`python -m pipeline {schritt}`)"
    print(f"NICHT DURCHGEFÜHRT – {text}")
    return text


def _hauskoordinate(level=None, method=None, source=None):
    """Ortsbezug auf einer Hauskoordinate (Ebene „adresse“ aus „Adressen Köln“), auch wenn er vererbt ist."""
    return level == "adresse" or method == PUNKT or source == config.QUELLE_ADRESSEN


# genauer Punkt aus einer Ortsangabe der Stadt (Stufe A, geojson Point): Methode in den Exporten (ohne Erlaubnis führt
# build ihn auf den Stadtteil zurück, Methode „oparl_sublocality“, oder lässt die Koordinate weg)
OPARL_PUNKT = "oparl_location"
OPARL_STADTTEIL = "oparl_sublocality"


def _oparl_punkt(method=None, lon=None, source=None, level=None):
    """Ortsbezug auf dem genauen Punkt einer Ortsangabe der Stadt (Exporte): Methode „oparl_location“ (Stufe A) oder
    ein Ort mit Quelle der Stadt (location_source bzw. source „oparl-koeln“) auf Ebene „strasse“, etwa eine Straße, die
    nur aus der Ortsangabe einer anderen Vorlage bekannt ist (Stufe B), oder ein vererbter Punkt. Ohne Ebene
    (vorlagen.geojson) jede Methode außer dem Stadtteil („oparl_sublocality“) und vererbten Ortsbezügen, deren Ebene dort
    fehlt; vererbte Punkte erkennen die Prüfung der Datenbank und der Gebietsdateien."""
    if lon is None:
        return False
    if method == OPARL_PUNKT:
        return True
    if source != config.QUELLE_OPARL:
        return False
    return level == "strasse" if level is not None else method not in (OPARL_STADTTEIL, "vererbt")


def _hat_tabelle(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def _hat_ausgelassene(db):
    return _hat_tabelle(db, "skipped_paper")


def erlaubnis(db, nicht_erkannt=None, erkannt=None, gruende=None):
    """Drucksache → darf ihr Ortsbezug auf einer Hauskoordinate liegen? Gleiche Regel, Eingaben und Funktion wie im
    Aufbau (build._ohne_hauskoordinate): Startmenge nach geocode.punkt_ausschluss mit Drucksache, Vorlagenart und Titel
    aus der Datenbank, Namen der beratenden Gremien, Name der federführenden Organisation (under_direction_of, wie
    maske.aus_db) und Vorlagenart in anderer Form (paper_type_other_form, gilt als nicht erkennbar), dazu die beim Aufbau
    ausgelassenen Vorlagen (skipped_paper, ohne Drucksachennummer also ohne Erlaubnis); daraus der Fixpunkt
    geocode.sperrmenge über die Beziehungen (geocode.beziehungen_db: paper_relation und relatedPaper aus paper_related,
    dieselben wie für die Titelmaske maske.aus_db) und dieselbe Drucksache.
    Gibt es eine Drucksache mehrfach, muss jede die Erlaubnis haben. `nicht_erkannt`, `erkannt`: Counter, die je nicht
    erkannter bzw. erkannter Vorlagenart (geocode.vorlagenart_bezeichnung) die Vorlagen zählen (erkannt: Erlaubnis nach
    eigener Angabe, geocode.erkannte_arten). `gruende`: dict, das je Vorlage der Startmenge den Grund aus
    geocode.punkt_ausschluss aufnimmt (Gegenprobe der Titelmaske in datenschutz). Liefert ({Vorlagen-ID: bool},
    {Drucksache: bool}, {Vorlagen-ID: Drucksache})."""
    gremien = {}
    for pid, name in db.execute(
            "SELECT c.paper_id, o.name FROM consultation c LEFT JOIN organization o ON o.id = c.organization_id "
            "ORDER BY c.paper_id, c.position"):
        gremien.setdefault(pid, []).append(name or "")
    andere_form = ({r[0] for r in db.execute("SELECT paper_id FROM paper_type_other_form")}
                   if _hat_tabelle(db, "paper_type_other_form") else set())
    amt = ("(SELECT name FROM organization o WHERE o.id = paper.under_direction_of)"
           if "under_direction_of" in {r[1] for r in db.execute("PRAGMA table_info(paper)")} else "NULL")
    je_id, je_ref, ref_of, start = {}, {}, {}, set()
    for pid, ref, typ, name, amt_name in db.execute(f"SELECT id, reference, paper_type, name, {amt} FROM paper"):
        p = {"reference": ref, "paperType": typ, "name": name, geocode.ANDERE_FORM: pid in andere_form}
        grund = geocode.punkt_ausschluss(p, gremien.get(pid, ()), amt_name)
        if grund:
            start.add(pid)
            if gruende is not None:
                gruende[pid] = grund
        if grund == "vorlagenart" and nicht_erkannt is not None:
            nicht_erkannt[geocode.vorlagenart_bezeichnung(p)] += 1
        if grund is None and erkannt is not None:
            erkannt[geocode.vorlagenart_bezeichnung(p)] += 1
        ref_of[pid] = ref
    start |= {r[0] for r in db.execute("SELECT id FROM skipped_paper")} if _hat_ausgelassene(db) else set()
    gesperrt = geocode.sperrmenge(start, geocode.beziehungen_db(db), ref_of)
    je_id = {pid: pid not in gesperrt for pid in ref_of}
    for pid, ok in je_id.items():
        je_ref[ref_of[pid]] = je_ref.get(ref_of[pid], True) and ok
    return je_id, je_ref, ref_of


def _verstoss(befunde, wo, refs):
    refs = sorted({str(r) for r in refs})   # Drucksachen; ohne Drucksache die Vorlagen-ID
    if refs:
        befunde.append(f"Datenschutz: Hauskoordinate bei Vorlagen ohne Erlaubnis ({wo}; Eingaben nach § 24 GO NRW, "
                       f"Vorlagen natürlicher Personen, Ausschuss für Anregungen und Beschwerden, Vorlagenart nicht "
                       f"erkennbar; CLAUDE.md 2 und 9): "
                       f"{len(refs)}, z. B. {', '.join(refs[:5])}")


def _verstoss_oparl(befunde, wo, refs):
    refs = sorted({str(r) for r in refs})
    if refs:
        befunde.append(f"Datenschutz: genauer Punkt aus der Ortsangabe der Stadt (OParl) bei Vorlagen ohne Erlaubnis "
                       f"für Hauskoordinaten ({wo}; höchstens Stadtteil, CLAUDE.md 2 und 9): "
                       f"{len(refs)}, z. B. {', '.join(refs[:5])}")


def _tabellen_mit_titel(wurzel, m, zahl, befunde):
    """Titel in TSV-Dateien unter `wurzel` (data/export, auch in Unterordnern; paket.write packt sie ins Datenpaket):
    Jede Datei mit den Spalten „drucksache“ und „titel“ (Audits, Stichproben, auch abgeschalteter Zusatzthemen) wird
    gegen die Titelmaske geprüft (maske.Maske.offen), ohne feste Liste, mit den Spalten aus TSV_TEXTSPALTEN (Fundstelle
    und Ortsnamen, Prüfung r20a); in den Stichproben aus maske.STICHPROBEN dazu deren weitere Spalten (gefundene Orte).
    Fehlt einer vorhandenen Stichprobe aus maske.STICHPROBEN „drucksache“ oder eine ihrer Spalten, ist das ein Befund:
    export könnte sie nicht maskieren (vorher übersprungen; Prüfung r20a).
    Liefert die Drucksachen mit Hausnummer; zählt Dateien und Zeilen in `zahl`, nennt nur Pfade und Spaltennamen."""
    konfiguriert = {wurzel.joinpath(*teile): maskiert for teile, maskiert in maske.STICHPROBEN.items()}
    offen, dateien, n, gesehen = set(), 0, 0, {}

    def hat_nummer(text, ref):   # Titel wiederholen sich (je Ortsbezug, je Thema): jede Kombination einmal prüfen
        if ref not in m.refs:
            return False
        if (text, ref) not in gesehen:
            gesehen[text, ref] = m.offen(text, ref)
        return gesehen[text, ref]

    for pfad in sorted(p for p in wurzel.rglob("*.tsv") if p.is_file()):
        maskiert = konfiguriert.get(pfad)
        with open(pfad, encoding="utf-8", newline="") as f:
            leser = csv.reader(f, delimiter="\t")
            kopf = next(leser, [])
            fehlt = [k for k in ("drucksache", *(maskiert or ("titel",))) if k not in kopf]
            if fehlt:
                if maskiert is not None:
                    befunde.append(f"Datenschutz: Stichprobe {pfad.relative_to(wurzel)} ohne Spalte "
                                   f"{', '.join(f'„{k}“' for k in fehlt)} (maske.STICHPROBEN; export maskiert sie "
                                   f"nicht, sie liegt im Datenpaket)")
                continue
            ref = kopf.index("drucksache")
            spalten = [i for i, k in enumerate(kopf) if k in TSV_TEXTSPALTEN | set(maskiert or ())]
            zeilen = 0
            for z in leser:
                zeilen += 1
                if len(z) > ref and any(i < len(z) and hat_nummer(z[i], z[ref]) for i in spalten):
                    offen.add(z[ref])
        dateien, n = dateien + 1, n + zeilen
        if maskiert is not None:
            zahl[pfad.name.removesuffix(".tsv")] = zeilen
    zahl["tabellen_mit_titel"], zahl["tabellen_zeilen"] = dateien, n
    return offen


def datenschutz(db, base=None):
    """Datenschutzprüfung (CLAUDE.md 2 und 9) über Datenbank und Kölner Export (`base`, Vorgabe
    config.EXPORT / config.STADT):
    1. Ortsangaben der OParl-API ohne Hausnummer (build.ohne_hausnummer; Postleitzahlen 5xxxx sind keine),
    2. Titel aus Einwohnerschaft, Bauordnung und Naturschutz ohne Hausnummer in suche.json, vorlagen.geojson und den
       Gebietsdateien (maske.aus_db, samt verbundenen Vorlagen auch über relatedPaper und derselben Drucksache;
       Entscheidung des Auftraggebers 24.10.2026: überall ausblenden), ebenso ihre Ortsnamen (`place` in
       vorlagen.geojson, `locations[].name` in den Gebietsdateien) und in jeder TSV-Datei unter data/export mit den
       Spalten „drucksache“ und „titel“ (Audits und Stichproben im Datenpaket, _tabellen_mit_titel; in den Stichproben
       aus maske.STICHPROBEN auch die gefundenen Orte, eine fehlende Spalte dort ist ein Befund; Prüfung r20a); keine
       Drucksache der Titelmaske mit Erlaubnis für
       Hauskoordinaten (Titelmaske und Hauskoordinaten folgen denselben Beziehungen, Runde 20) und keine Eingabe ohne
       Hauskoordinate (Grund „eingabe“) außerhalb der Titelmaske (Prüfung r20), ebenso keine Vorlagenart aus der
       Einwohnerschaft oder von Privatpersonen (geocode.art_von_personen); Hausnummern mit dem Muster der Maske und
       einer unabhängig gebauten Probe (maske.Maske.offen; Prüfung r20n; seit der zweiten Korrektur der Prüfung r20a
       blendet die Maske aus, was die Probe meldet, ein Befund heißt also: Text ohne Maske), dazu als Hinweis ohne
       Befund Titel der Maske mit einer Zahl außerhalb bekannter Zusammenhänge (maske.restzahlen),
    3. Hauskoordinaten nur bei Verwaltungsvorlagen sowie politischen Anträgen und Anfragen (Entscheidungen 04. und 10.11.2026): nie bei Eingaben
       nach § 24 GO NRW, Vorlagen natürlicher Personen oder einer Beratung im Ausschuss für Bürgerbeteiligung,
       Anregungen und Beschwerden, nie bei leerer oder nicht erkennbarer Vorlagenart (Entscheidung 10.11.2026; die
       erkannten und nicht erkannten Arten stehen mit Anzahl in der Ausgabe), nie neben einem Titel ohne Hausnummer und
       nie bei damit verbundenen Vorlagen (check.erlaubnis) – in der Datenbank, in vorlagen.geojson und in den
       Gebietsdateien der Karte; ebenso kein genauer Punkt aus einer Ortsangabe der Stadt (OParl: Stufe A, vererbt oder
       als Straße, die nur aus der Ortsangabe einer anderen Vorlage bekannt ist) bei diesen Vorlagen und bei
       Ortsangaben, die auch eine beim Aufbau ausgelassene Vorlage nennt.
    Ausgaben nennen nur Drucksachen und Orts-IDs, keine Titel oder Hausnummern (Protokolle der Workflows sind
    öffentlich). Liefert {"untersucht": {Schlüssel aus ZAEHLUNG: Anzahl}, "befunde": [...], "fehlend": [...]}."""
    base = Path(base) if base else config.EXPORT / config.STADT
    zahl, befunde, fehlend = {}, [], []
    print(f"\nDatenschutz (Export {base})")

    def lesen(name):
        f = base / name
        if f.exists():
            return json.loads(f.read_text())
        fehlend.append(_fehlt("Datenschutz", f, "export"))
        return None

    # 1. Straße und Beschreibung der Orte aus der OParl-API: jede Ziffer außer in einer Postleitzahl (dieselbe Regel wie
    # build.ohne_hausnummer, build.PLZ; Prüfung r20a, zweite Korrektur: vorher entfernte build nur Zahlen bis vier
    # Stellen, und check meldete den Rest eines Bebauungsplans „61459/“ als Hausnummer)
    from .build import PLZ
    orte = db.execute("SELECT id, street, description FROM location WHERE source = ? "
                      "AND (street IS NOT NULL OR description IS NOT NULL)", (config.QUELLE_OPARL,)).fetchall()
    zahl["ortsangaben"] = sum((s is not None) + (d is not None) for _, s, d in orte)
    mit_nummer = sorted(i for i, *texte in orte
                        if any(t and re.search(r"\d", PLZ.sub("", t)) for t in texte))
    if mit_nummer:
        befunde.append(f"Datenschutz: Hausnummern in Ortsangaben der Stadt (CLAUDE.md 5.2): {len(mit_nummer)} Orte, "
                       f"z. B. {', '.join(mit_nummer[:5])}")

    # 3a. Hauskoordinaten in der Datenbank
    nicht_erkannt, erkannt, gruende = Counter(), Counter(), {}
    je_id, je_ref, ref_of = erlaubnis(db, nicht_erkannt, erkannt, gruende)
    zahl["vorlagen"] = len(je_id)
    zahl["ohne_hauskoordinate"] = sum(not ok for ok in je_id.values())
    zahl["vorlagenart_nicht_erkennbar"] = sum(nicht_erkannt.values())
    punkte = {r[0] for r in db.execute(
        "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "WHERE l.level = 'adresse' OR pl.method = ? OR l.source = ?", (PUNKT, config.QUELLE_ADRESSEN))}
    zahl["hauskoordinaten"] = len(punkte)
    _verstoss(befunde, "Datenbank", [ref_of.get(p) or p for p in punkte if not je_id.get(p)])
    # 3c. genaue Punkte aus Ortsangaben der Stadt (Ort der Quelle oparl-koeln mit Koordinate auf Ebene „strasse“): aus
    # der eigenen Ortsangabe (Stufe A), vererbt oder als Straße, die nur aus der Ortsangabe einer anderen Vorlage bekannt
    # ist (Stufe B, Prüfung r19b): bei Vorlagen ohne Erlaubnis nie (build führt sie auf den Stadtteil zurück)
    oparl = {r[0] for r in db.execute(
        "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "WHERE l.source = ? AND l.level = 'strasse' AND l.lon IS NOT NULL", (config.QUELLE_OPARL,))}
    zahl["oparl_punkte"] = len(oparl)
    _verstoss_oparl(befunde, "Datenbank", [ref_of.get(p) or p for p in oparl if not je_id.get(p)])
    # Ortsangaben ausgelassener Vorlagen (skipped_location): auch bei anderen Vorlagen mit derselben Ortsangabe kein
    # genauer Punkt (build: grob; Prüfung r19b)
    if _hat_tabelle(db, "skipped_location"):
        geteilt = sorted({str(ref_of.get(r[0]) or r[0]) for r in db.execute(
            "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
            "WHERE l.source = ? AND l.level = 'strasse' AND l.lon IS NOT NULL AND l.id IN "
            "(SELECT location_id FROM skipped_location)", (config.QUELLE_OPARL,))})
        if geteilt:
            befunde.append(f"Datenschutz: genauer Punkt aus einer Ortsangabe der Stadt (OParl), die auch eine beim "
                           f"Aufbau ausgelassene Vorlage nennt (Datenbank; höchstens Stadtteil, CLAUDE.md 2 und 9): "
                           f"{len(geteilt)}, z. B. {', '.join(geteilt[:5])}")
    stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
    if not je_id:
        if stand.get("vorschau"):
            print("Kartenvorschau ohne Ratsvorlagen (STAND.json): keine Vorlage zu prüfen, geprüft werden die "
                  "Exportdateien.")
        else:
            befunde.append("Datenschutz: keine Vorlage in der Datenbank, aber keine Kartenvorschau (STAND.json) – "
                           "die Prüfung hätte keine Vorlage untersucht")

    # 2. und 3b. Export: Titel und Punkte; unbekannte Drucksachen gelten als nicht erlaubt
    m = maske.aus_db(db)
    # Titelmaske und Menge ohne Hauskoordinate folgen denselben Beziehungen (geocode.beziehungen_db, geocode.sperrmenge),
    # jede Ausgangsvorlage der Maske ist ohne Erlaubnis (geocode.punkt_ausschluss): eine Drucksache der Maske mit
    # Erlaubnis heißt, dass Maske und Hauskoordinaten nicht mehr nach denselben Regeln urteilen
    widerspruch = sorted(r for r in m.refs if je_ref.get(r))
    if widerspruch:
        befunde.append(f"Datenschutz: Titel ohne Hausnummer (maske.py), aber Erlaubnis für Hauskoordinaten "
                       f"(check.erlaubnis; Titelmaske und Hauskoordinaten urteilen verschieden): {len(widerspruch)}, "
                       f"z. B. {', '.join(widerspruch[:5])}")
    # Gegenrichtung (Prüfung r20): jede Eingabe oder Einwohneranfrage nach der Punktregel (Grund „eingabe“) ist
    # Ausgangspunkt der Titelmaske, auch in anderer Schreibung (geocode.eingabe in punkt_ausschluss und
    # chat.aus_einwohnerschaft); sonst zeigte sie ihre Hausnummer im Titel. Ebenso jede Vorlage, deren Vorlagenart die
    # Punktregel als Vorlage aus der Einwohnerschaft oder von Privatpersonen ausschließt (geocode.art_von_personen,
    # meist Grund „vorlagenart“: „Bürger-Antrag“, „Einwohner*innenanfrage“, „Anwohnerantrag“; Prüfung r20n)
    personen = {pid for pid, typ in db.execute("SELECT id, paper_type FROM paper") if geocode.art_von_personen(typ)}
    ungeschuetzt = sorted({str(ref_of.get(pid) or pid) for pid in ref_of
                           if (gruende.get(pid) == "eingabe" or pid in personen) and ref_of.get(pid) not in m.refs})
    if ungeschuetzt:
        befunde.append(f"Datenschutz: Eingabe oder Einwohneranfrage ohne Hauskoordinate (geocode.punkt_ausschluss; "
                       f"auch nach der Vorlagenart, geocode.art_von_personen), aber nicht in der Titelmaske (maske.py; "
                       f"Titelmaske und Hauskoordinaten urteilen verschieden): "
                       f"{len(ungeschuetzt)}, z. B. {', '.join(ungeschuetzt[:5])}")
    offen = set()
    suche = lesen("suche.json")
    if suche is not None:
        rows = suche["rows"]
        zahl["suche"] = len(rows)
        zahl["titel_geschuetzt"] = sum(r[0] in m.refs for r in rows)
        offen |= {r[0] for r in rows if m.offen(r[1], r[0])}
        # grobe zweite Probe (Prüfung r20a, zweite Korrektur): Probe und Maske kennen dieselben Schreibweisen; was beide
        # nicht kennen, zeigt sich hier als verbliebene Zahl. Nur ein Hinweis mit Drucksachen zur Prüfung von Hand, kein
        # Befund (Zahlen wie „Tempo 30“ oder „3 Bäume“ hielten sonst die Veröffentlichung an)
        rest = sorted({str(r[0]) for r in rows if r[0] in m.refs and maske.restzahlen(r[1])})
        zahl["titel_restzahlen"] = len(rest)
        if rest:
            print(f"Hinweis (kein Befund): Titel der Maske mit einer Zahl außerhalb bekannter Zusammenhänge, von Hand "
                  f"prüfen: {len(rest)}, z. B. {', '.join(rest[:10])}")
        if len(rows) != len(je_id):
            befunde.append(f"Datenschutz: suche.json nennt {len(rows)} Vorlagen, die Datenbank {len(je_id)} – "
                           "Export und Datenbank passen nicht zusammen (`python -m pipeline export`)")
    geo = lesen("vorlagen.geojson")
    if geo is not None:
        props = [x["properties"] for x in geo["features"]]
        zahl["geojson"] = len(props)
        zahl["ortsnamen"] = zahl.get("ortsnamen", 0) + sum(bool(p.get("place")) for p in props)
        offen |= {p["reference"] for p in props
                  if m.offen(p.get("name"), p["reference"]) or m.offen(p.get("place"), p["reference"])
                  or m.offen(p.get("evidence"), p["reference"])}
        zahl["fundstellen"] = zahl.get("fundstellen", 0) + sum(bool(p.get("evidence")) for p in props)
        auf = [p["reference"] for p in props
               if _hauskoordinate(method=p.get("method"), source=p.get("location_source"))]
        zahl["geojson_hauskoordinaten"] = len(auf)
        _verstoss(befunde, "vorlagen.geojson", [r for r in auf if not je_ref.get(r)])
        _verstoss_oparl(befunde, "vorlagen.geojson",
                        [p["reference"] for p, f in zip(props, geo["features"])
                         if _oparl_punkt(p.get("method"), ((f.get("geometry") or {}).get("coordinates") or [None])[0],
                                         p.get("location_source"))
                         and not je_ref.get(p["reference"])])
    for d in GEBIETSDATEIEN_PFLICHT:
        if not (base / d).is_dir():
            fehlend.append(_fehlt("Datenschutz", base / d, "export"))
    dateien = [f for d in GEBIETSDATEIEN for f in sorted((base / d).glob("*.json"))]
    refs, auf, auf_oparl = set(), set(), set()
    for f in dateien:
        for p in json.loads(f.read_text())["papers"]:
            refs.add(p["reference"])
            orte = p.get("locations") or ()
            zahl["ortsnamen"] = zahl.get("ortsnamen", 0) + sum(bool(x.get("name")) for x in orte)
            # Fundstellen: Teile des Titels (Bebauungsplan, Einreichende) und Ortsbezüge (Prüfung r20a)
            fund = [x.get("evidence") for k in ("locations", "plans", "originators", "responsibility")
                    for x in p.get(k) or ()]
            zahl["fundstellen"] = zahl.get("fundstellen", 0) + sum(bool(x) for x in fund)
            if (m.offen(p.get("name"), p["reference"]) or any(m.offen(x.get("name"), p["reference"]) for x in orte)
                    or any(m.offen(x, p["reference"]) for x in fund)):
                offen.add(p["reference"])
            if any(_hauskoordinate(x.get("level"), x.get("method"), x.get("source")) for x in orte):
                auf.add(p["reference"])
            if any(_oparl_punkt(x.get("method"), x.get("lon"), x.get("source"), x.get("level")) for x in orte):
                auf_oparl.add(p["reference"])
    zahl["gebietsdateien"] = len(refs)
    zahl["gebietsdateien_hauskoordinaten"] = len(auf)
    # Planregister (plaene.json, Planchronik): Titel und Fundstelle je Vorlage (Prüfung r20a); ohne die Datei (ältere
    # Exporte) nichts zu prüfen
    if (base / "plaene.json").exists():
        for v in (v for e in json.loads((base / "plaene.json").read_text()).get("plaene") or ()
                  for v in e.get("vorlagen") or ()):
            zahl["fundstellen"] = zahl.get("fundstellen", 0) + bool(v.get("fundstelle"))
            if m.offen(v.get("titel"), v.get("drucksache")) or m.offen(v.get("fundstelle"), v.get("drucksache")):
                offen.add(v.get("drucksache"))
    offen |= _tabellen_mit_titel(base.parent, m, zahl, befunde)
    _verstoss(befunde, "Gebietsdateien der Karte", [r for r in auf if not je_ref.get(r)])
    _verstoss_oparl(befunde, "Gebietsdateien der Karte", [r for r in auf_oparl if not je_ref.get(r)])
    if offen:
        befunde.append(f"Datenschutz: Hausnummern in Titeln oder Ortsnamen aus Einwohnerschaft, Bauordnung oder "
                       f"Naturschutz (maske.py): {len(offen)}, z. B. {', '.join(sorted(map(str, offen))[:5])}")

    for k, text in ZAEHLUNG.items():
        if k in zahl:
            print(f"{text}: {zahl[k]}")
    # nicht erkannte und erkannte Vorlagenarten mit Anzahl (nur die Art), wie im Log von build
    print(geocode.nicht_erkannte_arten(nicht_erkannt))
    print(geocode.erkannte_arten(erkannt))
    return {"untersucht": zahl, "befunde": befunde, "fehlend": fehlend}


def zusatzthemen():
    """Prüfungen der Zusatzthemen, nur wenn freigegeben (config.ZUSATZTHEMEN; abgeschaltete werden ausgewiesen).
    Liefert (Befunde, nicht durchgeführte Prüfungen)."""
    befunde, fehlend = [], []
    an = config.ZUSATZTHEMEN.get
    base = config.EXPORT / config.STADT

    print("\nBesetzung der Gremien (Zusatzthema „besetzung“)")
    if not an("besetzung"):
        print("abgeschaltet (config.ZUSATZTHEMEN, zweiter Lauf) – nicht geprüft")
    elif not config.BESETZUNG.exists():
        fehlend.append(_fehlt("Besetzung", config.BESETZUNG, "fetch-besetzung"))
    else:
        doc = json.loads(config.BESETZUNG.read_text())
        b = besetzung.pruefen_auszug(doc)
        print(f"{len(doc['mitgliedschaften'])} laufende Mitgliedschaften, {len(doc['personen'])} Personen namentlich; "
              f"Befunde: {b or 'keine'}")
        befunde += [f"Besetzung: {x}" for x in b]

    print("\nProzessarten (Zusatzthema „soll“)")
    pz = base / "prozessarten.json"
    if not an("soll"):
        print("abgeschaltet (config.ZUSATZTHEMEN) – nicht geprüft")
    elif not pz.exists():
        fehlend.append(_fehlt("Prozessarten", pz, "export"))
    else:
        b = besetzung.pruefen_auszug({"mitgliedschaften": [], "rest": json.loads(pz.read_text())})
        print(f"prozessarten.json: Befunde: {b or 'keine'}")
        befunde += [f"prozessarten.json: {x}" for x in b]

    print("\nKontextdaten je Stadtteil (Zusatzthema „kontext“)")
    kx = base / kontext.OUT
    if not an("kontext"):
        print("abgeschaltet (config.ZUSATZTHEMEN) – nicht geprüft")
    elif not kx.exists():
        fehlend.append(_fehlt("Kontextdaten", kx, "kontext"))
    else:
        befunde += [f"Kontextdaten: {x}" for x in kontext.pruefen(kx)]
    return befunde, fehlend
