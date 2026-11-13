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
    "titel_punktregel": "davon über Gremium (Anregungen und Beschwerden) oder nicht erkennbare Vorlagenart "
                        "Ausgangspunkt der Titelmaske (Entscheidung 13.11.2026)",
    "ohne_punkt_ohne_maske": "Vorlagen ohne Hauskoordinate außerhalb der Titelmaske (erwartet nur über eine "
                             "Drucksache in anderem Schema) mit einer Zahl außerhalb bekannter Zusammenhänge im Titel "
                             "(Hinweis, kein Befund; Entscheidung offen, TECHNIK.md)",
    "ortsnamen": "Ortsnamen in vorlagen.geojson und den Gebietsdateien untersucht",
    "geojson": "Punkte in vorlagen.geojson untersucht",
    "geojson_hauskoordinaten": "davon auf einer Hauskoordinate",
    "gebietsdateien": "Vorlagen in den Gebietsdateien der Karte untersucht",
    "gebietsdateien_hauskoordinaten": "davon mit Hauskoordinate",
    "stichprobe_hausnummern": "Titel in der Stichprobe Hausnummern untersucht",
    "stichprobe_volltext": "Titel und Orte in der Stichprobe Volltext untersucht",
    "stichprobe_objekte": "Titel und Orte in der Stichprobe Gebäude und Anlagen untersucht",
    "tabellen_mit_titel": "TSV-Dateien mit Drucksache und Titel, Fundstelle oder Ortsnamen unter data/export "
                          "untersucht (Datenpaket)",
    "tabellen_zeilen": "davon Zeilen",
    "fundstellen": "Fundstellen aus dem Titel in vorlagen.geojson, den Gebietsdateien und plaene.json untersucht",
    "verbundene_titel": "Titel verbundener Vorlagen und Ergebnisse der Beratungen in den Gebietsdateien untersucht",
    "sitzungen": "Sitzungsnamen zu Sitzungen mit einer Vorlage der Titelmaske in den Gebietsdateien, zeit.json und "
                 "termine.ics untersucht",
    "feeds": "Einträge in Feeds (*.xml) untersucht",
}
# Spalten der TSV-Dateien mit Drucksache, die Titel, Teile des Titels oder einen Ortsnamen tragen: geprüft wie der Titel
# (Prüfung r20a; vorher nur „titel“; zweite Korrektur: „ort“, „zurueckgestellt“); export._tabellen_maskieren maskiert
# dieselben Spalten (maske.TEXTSPALTEN; dritte Korrektur: jede Datei mit „drucksache“)
TSV_TEXTSPALTEN = maske.TEXTSPALTEN


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


def erlaubnis(db, nicht_erkannt=None, erkannt=None, gruende=None, punktregel=None):
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
    geocode.punkt_ausschluss aufnimmt (Gegenprobe der Titelmaske in datenschutz). `punktregel`: Menge, die die
    Vorlagen aufnimmt, die über Gremium oder Vorlagenart Ausgangspunkt der Titelmaske sind (maske.ausgang_punktregel,
    Entscheidung 13.11.2026). Gremien, Vorlagenart und federführende Organisation liest dieselbe Funktion wie
    maske.aus_db (geocode.angaben_db). Liefert ({Vorlagen-ID: bool}, {Drucksache: bool}, {Vorlagen-ID: Drucksache})."""
    je_id, je_ref, ref_of, start = {}, {}, {}, set()
    for pid, p, gremien, amt_name in geocode.angaben_db(db):
        ref = p["reference"]
        grund = geocode.punkt_ausschluss(p, gremien, amt_name)
        if punktregel is not None and maske.ausgang_punktregel(p, gremien):
            punktregel.add(pid)
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
    """Titel, Fundstellen und Ortsnamen in TSV-Dateien unter `wurzel` (data/export, auch in Unterordnern; paket.write
    packt sie ins Datenpaket): Jede Datei mit der Spalte „drucksache“ und einer Spalte aus TSV_TEXTSPALTEN (Audits,
    Stichproben, auch abgeschalteter Zusatzthemen) wird gegen die Titelmaske geprüft (maske.Maske.offen), ohne feste
    Liste; in den Stichproben aus maske.STICHPROBEN dazu deren weitere Spalten (gefundene Orte). Vorher nur Dateien mit
    „titel“ (Prüfung r20a, dritte Korrektur: audit_volltext.tsv und audit_objekte_titel.tsv blieben ungeprüft); export
    maskiert dieselben Spalten (export._tabellen_maskieren). Fehlt einer vorhandenen Stichprobe aus maske.STICHPROBEN
    „drucksache“ oder eine ihrer Spalten, ist das ein Befund: export könnte sie nicht maskieren (vorher übersprungen;
    Prüfung r20a).
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
            fehlt = [k for k in ("drucksache", *(maskiert or ())) if k not in kopf]
            if fehlt:
                if maskiert is not None:
                    befunde.append(f"Datenschutz: Stichprobe {pfad.relative_to(wurzel)} ohne Spalte "
                                   f"{', '.join(f'„{k}“' for k in fehlt)} (maske.STICHPROBEN; export maskiert sie "
                                   f"nicht, sie liegt im Datenpaket)")
                continue
            ref = kopf.index("drucksache")
            spalten = [i for i, k in enumerate(kopf) if k in TSV_TEXTSPALTEN | set(maskiert or ())]
            if not spalten:
                continue
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


def _ics_ereignisse(pfad):
    """VEVENT-Blöcke einer iCalendar-Datei (publish.write_calendar) als [{Feld: Text}]: Zeilen entfaltet, Text nach
    RFC 5545 zurückgewandelt (\\n, \\, \\; \\\\), Parameter am Feldnamen abgetrennt."""
    text = re.sub(r"\r?\n[ \t]", "", pfad.read_text(encoding="utf-8"))
    out = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        felder = {}
        for zeile in re.split(r"\r?\n", block.split("END:VEVENT")[0]):
            name, trenner, wert = zeile.partition(":")
            if trenner:
                felder[name.split(";")[0].upper()] = re.sub(
                    r"\\([\\;,nN])", lambda x: "\n" if x.group(1) in "nN" else x.group(1), wert)
        out.append(felder)
    return out


def _sitzungen(base, db, m, zahl):
    """Namen der Sitzungen, in denen eine Vorlage der Maske beraten wird (Maske.sitzungen), in zeit.json
    (`meetings[].name` und `gremium`) und termine.ics (erste Zeile der Beschreibung ist der Name, die Zusammenfassung
    das Gremium): export maskiert den Namen und ein Gremium, das aus dem Namen stammt, mit der Drucksache einer solchen
    Vorlage (Offen (9) der Nachprüfung der dritten Korrektur; vorher weder maskiert noch geprüft). Ein Gremium mit dem
    Namen einer Organisation der Datenbank stammt nicht aus dem Namen und bleibt (wie export.gremium_der_sitzung).
    Liefert die Drucksachen (je Sitzung die der Maske); zählt die Namen in `zahl`."""
    organisationen = {r[0] for r in db.execute("SELECT name FROM organization") if r[0]}
    offen = set()

    def pruefen(sitzung, name, gremium):
        ref = m.sitzungen.get(sitzung)
        if not ref:
            return
        zahl["sitzungen"] = zahl.get("sitzungen", 0) + 1
        if m.offen(name, ref) or (gremium not in organisationen and m.offen(gremium, ref)):
            offen.add(ref)

    if (base / "zeit.json").exists():
        for x in json.loads((base / "zeit.json").read_text()).get("meetings") or ():
            pruefen(x.get("source_object"), x.get("name"), x.get("gremium"))
    if (base / "termine.ics").exists():
        for e in _ics_ereignisse(base / "termine.ics"):
            pruefen(e.get("UID"), (e.get("DESCRIPTION") or "").split("\n")[0],
                    re.sub(r" \(abgesagt\)$", "", e.get("SUMMARY") or ""))
    return offen


def _feeds(base, db, m, zahl, befunde):
    """Feeds (Atom, *.xml unter `base`: je Gebiet, ganz Köln, je Vorlage, Themenseiten): Titel und Zusammenfassung jedes
    Eintrags und der Kopf eines Feeds je Vorlage enthalten keinen Text der Vorlage ungekürzt, den die Maske ändert
    (Titel, Ergebnisse der Beratungen, Titel der Folgevorlagen; Prüfung r20a, dritte Korrektur: Feeds waren ungeprüft).
    Ein Eintrag nennt seine Vorlage in der ID (OParl-Kennung vor „#“, publish.events). Ein Vergleich mit dem
    ungekürzten Text statt der Maske selbst, weil Einträge Gremium und Ergebnis neben dem Titel tragen. Vorher fallen
    die maskierten Texte derselben Vorlage weg, die einen ungekürzten enthalten (Nachprüfung der dritten Korrektur:
    Setzt der Titel einer Folgevorlage den Titel der Eingabe fort, „… Musterpark 2. Nachtrag“, rückt deren letzte Zahl
    in einen bekannten Zusammenhang und bleibt nach der Maske stehen; der ungekürzte Titel der Eingabe stand dann als
    Teil im Eintrag, und check meldete einen Befund, den die Maske nicht beheben konnte). Texte in der Form, die ein
    Feed nach dem Lesen trägt (ohne Zeichen, die XML 1.0 nicht erlaubt: dieselbe Regel publish.xml_text wie beim
    Schreiben; Zeilenende „\\n“). Ergebnisse eines Tagesordnungspunkts, auf dem eine Vorlage der Maske beraten wird,
    gelten bei jeder Vorlage, die ihn zeigt (Maske.tops; Offen (8) der Nachprüfung der dritten Korrektur). Ein Feed,
    den ElementTree nicht lesen kann, ist ein Befund in `befunde` (Offen (6); vorher übergangen, ohne Zählung). Liefert
    die Drucksachen mit ungekürztem Text; zählt die Einträge in `zahl`."""
    import xml.etree.ElementTree as ET
    from .publish import xml_text
    atom = "{http://www.w3.org/2005/Atom}"
    ref_von = dict(db.execute("SELECT id, reference FROM paper"))
    texte = {}

    def wie_im_feed(t):
        return re.sub(r"\r\n?", "\n", xml_text(t))

    def ungekuerzt(pid):
        """(Texte der Vorlage, die die Maske ändert, ungekürzt; maskierte Texte der Vorlage, die einen davon enthalten,
        längere zuerst)."""
        if pid not in texte:
            ref = ref_von.get(pid)
            # Ergebnisse je Tagesordnungspunkt der Maske (bei einer Vorlage der Maske jeder ihrer Punkte)
            kandidaten = [(r, m.tops[a]) for r, a in db.execute(
                "SELECT a.result, c.agenda_item_id FROM consultation c JOIN agenda_item a ON a.id = c.agenda_item_id "
                "WHERE c.paper_id = ?", (pid,)) if a in m.tops]
            if ref in m.refs:
                kandidaten += [(r[0], ref) for r in db.execute("SELECT name FROM paper WHERE id = ?", (pid,))]
                kandidaten += db.execute("SELECT p.name, p.reference FROM paper_relation r JOIN paper p "
                                         "ON p.id = r.child_id WHERE r.parent_id = ?", (pid,)).fetchall()
            # ab sechs Zeichen: ein kurzer Text wie „12“ stünde auch zufällig im Eintrag (Datum der Beratung)
            roh = [wie_im_feed(t) for t, r in kandidaten if t and len(t) >= 6 and m(t, r) != t]
            huellen = {wie_im_feed(m(t, r)) for t, r in kandidaten if t} if roh else set()
            texte[pid] = (roh, sorted((h for h in huellen if any(t in h for t in roh)), key=len, reverse=True))
        return texte[pid]

    offen, n = set(), 0
    for pfad in sorted(p for p in base.rglob("*.xml") if p.is_file()):
        try:
            wurzel = ET.parse(pfad).getroot()
        except ET.ParseError as e:
            befunde.append(f"Datenschutz: Feed {pfad.relative_to(base)} nicht lesbar ({e}), Einträge ungeprüft "
                           f"(publish.xml_text)")
            continue
        kopf = " ".join(wurzel.findtext(f"{atom}{k}") or "" for k in ("title", "subtitle"))
        for e in wurzel.iter(f"{atom}entry"):
            n += 1
            pid = (e.findtext(f"{atom}id") or "").split("#")[0]
            roh, huellen = ungekuerzt(pid)
            if not roh:
                continue
            text = " ".join(e.findtext(f"{atom}{k}") or "" for k in ("title", "summary")) + " " + kopf
            for h in huellen:
                text = text.replace(h, " ")
            if any(t in text for t in roh):
                offen.add(ref_von.get(pid) or pid)
    zahl["feeds"] = n
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
       Einwohnerschaft oder von Privatpersonen (geocode.art_von_personen); Hausnummern mit den Mustern der Maske, ihrer
       Probe und ihrer Positivliste (maske.Maske.offen; Prüfung r20n; seit der zweiten Korrektur der Prüfung r20a
       blendet die Maske aus, was die Probe meldet, seit der dritten jede Zahl außerhalb bekannter Zusammenhänge; ein
       Befund heißt also: Text ohne Maske). Seit der dritten Korrektur auch Titel verbundener Vorlagen, Ergebnisse der
       Beratungen und Feeds (_feeds) und jede TSV-Datei mit „drucksache“; seit dem 13.11.2026 Ergebnisse je
       Tagesordnungspunkt und Sitzungsnamen je Sitzung der Maske (auch bei Vorlagen außerhalb, _sitzungen für zeit.json
       und termine.ics), ein unlesbarer Feed als Befund, und jede Vorlage ohne Hauskoordinate über Gremium oder
       Vorlagenart ist Ausgangspunkt der Titelmaske (Gegenprobe als Befund, Entscheidung 13.11.2026); als Hinweis ohne
       Befund nur noch Vorlagen ohne Hauskoordinate außerhalb der Titelmaske (erwartet: Drucksache in anderem Schema),
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
    # build.ohne_hausnummer, eine Funktion: build.ziffer_ausser_plz; Prüfung r20a, zweite Korrektur: vorher entfernte
    # build nur Zahlen bis vier Stellen, und check meldete den Rest eines Bebauungsplans „61459/“ als Hausnummer; dritte
    # Korrektur: Ziffern auch nach NFKC, „Severinstraße 12½“)
    from .build import ziffer_ausser_plz
    orte = db.execute("SELECT id, street, description FROM location WHERE source = ? "
                      "AND (street IS NOT NULL OR description IS NOT NULL)", (config.QUELLE_OPARL,)).fetchall()
    zahl["ortsangaben"] = sum((s is not None) + (d is not None) for _, s, d in orte)
    mit_nummer = sorted(i for i, *texte in orte if any(t and ziffer_ausser_plz(t) for t in texte))
    if mit_nummer:
        befunde.append(f"Datenschutz: Hausnummern in Ortsangaben der Stadt (CLAUDE.md 5.2): {len(mit_nummer)} Orte, "
                       f"z. B. {', '.join(mit_nummer[:5])}")

    # 3a. Hauskoordinaten in der Datenbank
    nicht_erkannt, erkannt, gruende, punktregel = Counter(), Counter(), {}, set()
    je_id, je_ref, ref_of = erlaubnis(db, nicht_erkannt, erkannt, gruende, punktregel)
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
    # Entscheidung 13.11.2026 (1): Vorlagen ohne Hauskoordinate über das Gremium (Ausschuss für Bürgerbeteiligung,
    # Anregungen und Beschwerden) oder eine nicht erkennbare Vorlagenart sind Ausgangspunkt der Titelmaske (vorher nur
    # ein Hinweis). Gegenprobe wie bei den Eingaben: Grund „gremium“ oder „vorlagenart“ aus geocode.punkt_ausschluss
    # oder maske.ausgang_punktregel (auch bei einer Drucksache in anderem Schema), aber nicht in der Titelmaske
    zahl["titel_punktregel"] = len(punktregel)
    ohne_maske = sorted({str(ref_of.get(pid) or pid) for pid in ref_of
                         if (gruende.get(pid) in ("gremium", "vorlagenart") or pid in punktregel)
                         and ref_of.get(pid) not in m.refs})
    if ohne_maske:
        befunde.append(f"Datenschutz: ohne Hauskoordinate über das Gremium (Anregungen und Beschwerden) oder eine "
                       f"nicht erkennbare Vorlagenart, aber nicht in der Titelmaske (maske.ausgang_punktregel, "
                       f"Entscheidung 13.11.2026; Titelmaske und Hauskoordinaten urteilen verschieden): "
                       f"{len(ohne_maske)}, z. B. {', '.join(ohne_maske[:5])}")
    # Hinweis ohne Befund (Entscheidung des Auftraggebers offen, TECHNIK.md): Übrig bleiben ohne Hauskoordinate und
    # außerhalb der Titelmaske nur Vorlagen mit einer Drucksache in anderem Schema (Grund „drucksache“) und ihre
    # verbundenen Vorlagen; wie viele davon eine Zahl außerhalb bekannter Zusammenhänge im Titel tragen, zeigt diese
    # Zählung (nur Anzahl und Drucksachen)
    titel_von = dict(db.execute("SELECT id, name FROM paper"))
    aussen = sorted({str(ref_of.get(pid) or pid) for pid, ok in je_id.items()
                     if not ok and ref_of.get(pid) not in m.refs and maske.restzahlen(titel_von.get(pid) or "")})
    zahl["ohne_punkt_ohne_maske"] = len(aussen)
    if aussen:
        print(f"Hinweis (kein Befund): Vorlagen ohne Hauskoordinate außerhalb der Titelmaske (erwartet nur über eine "
              f"Drucksache in anderem Schema), mit einer Zahl im Titel: {len(aussen)}, z. B. {', '.join(aussen[:10])}")
    offen = set()
    suche = lesen("suche.json")
    if suche is not None:
        rows = suche["rows"]
        zahl["suche"] = len(rows)
        zahl["titel_geschuetzt"] = sum(r[0] in m.refs for r in rows)
        # seit der dritten Korrektur der Prüfung r20a mit der Positivliste der Maske (Maske.offen): jede Zahl außerhalb
        # bekannter Zusammenhänge ist ein Befund (vorher nur ein Hinweis, maske.restzahlen; die Maske blendet sie aus,
        # ein Befund heißt also: Text ohne Maske)
        offen |= {r[0] for r in rows if m.offen(r[1], r[0])}
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
    # Tagesordnungspunkt je Beratung einer Vorlage (Stelle in der Beratungsfolge, `process[].position` wie in export),
    # soweit dort eine Vorlage der Maske beraten wird (Maske.tops; Offen (8))
    top_ref = {(pid, pos): m.tops[top] for pid, pos, top in db.execute(
        "SELECT paper_id, position, agenda_item_id FROM consultation WHERE agenda_item_id IS NOT NULL")
        if top in m.tops}
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
            # Titel verbundener Vorlagen (je mit ihrer Drucksache) und Ergebnisse der Beratungen (Prüfung r20a, dritte
            # Korrektur: vorher ungeprüft; export maskiert sie wie den Titel)
            verbunden = [(x.get("name"), x.get("reference")) for k in ("superordinated", "subordinated")
                         for x in p.get(k) or ()]
            verbunden += [(x.get("title"), x.get("reference")) for x in p.get("steps") or () if x.get("title")]
            verbunden += [(x.get("result"), p["reference"]) for k in ("process", "steps") for x in p.get(k) or ()
                          if x.get("result")]
            zahl["verbundene_titel"] = zahl.get("verbundene_titel", 0) + len(verbunden)
            offen |= {r for t, r in verbunden if m.offen(t, r)}
            # Ergebnis eines Tagesordnungspunkts, auf dem eine Vorlage der Maske beraten wird, und Name einer Sitzung
            # mit einer Vorlage der Maske: bei jeder Vorlage, auch außerhalb der Maske (Offen (8) und (9); die
            # Ergebnisse in `steps` sind Kopien aus `process`). Befund unter der Drucksache der zeigenden Vorlage
            bei = [(x.get("result"), top_ref.get((p.get("source_object"), x.get("position"))))
                   for x in p.get("process") or () if x.get("result")]
            sitzungen = [(x.get("meeting"), m.sitzungen.get(x.get("meeting_id"))) for x in p.get("process") or ()
                         if x.get("meeting") and x.get("meeting_id") in m.sitzungen]
            zahl["sitzungen"] = zahl.get("sitzungen", 0) + len(sitzungen)
            if any(r and m.offen(t, r) for t, r in bei + sitzungen):
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
    offen |= _sitzungen(base, db, m, zahl)
    offen |= _feeds(base, db, m, zahl, befunde)
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
