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
from datetime import datetime
from pathlib import Path

from . import actors, besetzung, config, geocode, kontext, maske, pdfkopf
from .geo import Ortsteile

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
    "sitzungen": "Sitzungsnamen und Gremien aus dem Sitzungsnamen in den Gebietsdateien, zeit.json und termine.ics "
                 "untersucht (alle Sitzungen, Entscheidung 19.11.2026 (3))",
    "feeds": "Einträge in Feeds (*.xml) untersucht",
    "aktuell": "Titel und Gremien in index.json („Aktuell in Köln“) untersucht",
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
        befunde += federfuehrung_kopf(db)
        # Gremien, Ämter und Stationen (Entscheidung 21.11.2026 (2), Pull Request 4a); Kennungen der Gremien in
        # suche.json (Entscheidung 21.11.2026 (3) (G4))
        for pruefung in (gremien, stationen, suche_gremien):
            b, f = pruefung(db)
            befunde += b
            fehlend += f
    finally:
        db.close()
    b, f = aemter_aufbau()
    befunde += b
    fehlend += f
    befunde += ds["befunde"]
    fehlend += ds["fehlend"]
    b, f = hinweise_sitzungen()
    befunde += b
    fehlend += f
    b, f = absagen_kalender()
    befunde += b
    fehlend += f
    befunde += zeitstempel_kalender()
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


def federfuehrung_kopf(db):
    """Federführung aus dem Kopf der Vorlage (pipeline/dokumente.py; Methode „pdf_kopf“ aus mainFile, „pdf_kopf_anlage“
    aus auxiliaryFile, Entscheidung 13.11.2026 (a)): jede Zeile nur mit Kennung nach pdfkopf.KENNUNG_FORM, Fundstelle
    genau „Kopf der Vorlage (S. 1): <Kennung>“ bzw. „Kopf der Anlage (S. 1): <Kennung>“ (kein Text des Dokuments),
    Konfidenz der Methode (pdfkopf.VERWENDUNG: aus einer Anlage nur „niedrig“), ohne Organisation (Dezernat und
    Dienststelle ordnet erst der Export über die Ämtertabelle zu), nur bei Vorlagen ohne underDirectionOf und mit
    Erlaubnis für Hauskoordinaten (erlaubnis, dieselbe Regel wie im Aufbau), höchstens eine Zeile je Vorlage. Liefert
    die Befunde."""
    print("\nFederführung aus dem Kopf der Vorlage (PDF, Seite 1)")
    spalten = {r[1] for r in db.execute("PRAGMA table_info(paper_responsibility)")}
    if not {"confidence", "kennung"} <= spalten:
        print("nicht anwendbar: Datenbank ohne die Spalten confidence und kennung")
        return []
    # Methode → (Fundstelle, zulässige Konfidenzen)
    verwendung = {methode: (evidenz, set(konfidenz.values()))
                  for methode, evidenz, konfidenz in pdfkopf.VERWENDUNG.values()}
    zeilen = db.execute(
        "SELECT r.paper_id, p.reference, r.organization_id, r.kind, r.evidence, r.derived, r.confidence, r.kennung, "
        "p.under_direction_of, r.method FROM paper_responsibility r JOIN paper p ON p.id = r.paper_id "
        f"WHERE r.method IN ({', '.join('?' * len(verwendung))})", tuple(verwendung)).fetchall()
    if not zeilen:
        print("keine (Dokumentschritt abgeschaltet oder ohne erkannte Kennung)")
        return []
    erlaubt = erlaubnis(db)[0]
    je_vorlage = Counter(pid for pid, *_ in zeilen)
    falsch = sorted({ref for pid, ref, org, kind, ev, derived, conf, kennung, udo, methode in zeilen
                     if not (isinstance(kennung, str) and pdfkopf.KENNUNG_FORM.fullmatch(kennung)
                             and ev == f"{verwendung[methode][0]}: {kennung}" and org is None
                             and kind == "federfuehrend" and derived == 1 and conf in verwendung[methode][1]
                             and not udo and erlaubt.get(pid) and je_vorlage[pid] == 1)})
    arten = Counter(z[-1] for z in zeilen)
    print(f"{len(zeilen)} Vorlagen mit Kennung aus dem Kopf (ohne Organisation, Zuordnung zur Ämtertabelle im Export; "
          + ", ".join(f"{m} {arten[m]}" for m in verwendung) + f"); in unerwarteter Form oder ohne Erlaubnis: "
          f"{len(falsch)}")
    return ([f"Federführung aus dem Kopf der Vorlage in unerwarteter Form, bei Vorlagen mit underDirectionOf oder ohne "
             f"Erlaubnis für Hauskoordinaten: {', '.join(falsch[:20])}"] if falsch else [])


def _pct(n, d):
    return f"{n} von {d} ({100 * n / d:.1f} %)" if d else "–"


def beratungen_je_vorlage(db):
    """Beratungen in der Datenbank wie im Log von build (build.beratungen_text; Entscheidungen 17.11.2026 (11) und
    (14)): Einträge (je Eintrag eine Zeile), Kennungen in mehreren Vorlagen mit ihren Einträgen und Vorlagen, Kennungen
    mehrfach in derselben Vorlage mit ihren Einträgen; nur Zahlen. Eine ältere Datenbank, deren Schlüssel `position`
    nicht enthält (eine Zeile je Kennung bzw. je Kennung und Vorlage, wiederholte Einträge zusammengelegt), nennt nur
    die Zeilen."""
    from .build import beratungen_text
    one = lambda sql: db.execute(sql).fetchone()[0]
    zeilen = one("SELECT COUNT(*) FROM consultation")
    if not any(r[1] == "position" and r[5] for r in db.execute("PRAGMA table_info(consultation)")):
        return (f"Beratungen: {zeilen} Zeilen der Datenbank (Einträge nicht erfasst: ältere Datenbank, Schlüssel ohne "
                f"position)")
    mehrere = "SELECT id FROM consultation GROUP BY id HAVING COUNT(DISTINCT paper_id) > 1"
    doppelt = "SELECT COUNT(*) AS n FROM consultation GROUP BY id, paper_id HAVING n > 1"
    return beratungen_text(
        zeilen, one(f"SELECT COUNT(*) FROM ({mehrere})"),
        one(f"SELECT COUNT(*) FROM consultation WHERE id IN ({mehrere})"),
        one(f"SELECT COUNT(DISTINCT paper_id) FROM consultation WHERE id IN ({mehrere})"),
        one(f"SELECT COUNT(*) FROM ({doppelt})"), one(f"SELECT COALESCE(SUM(n), 0) FROM ({doppelt})"))


def _wiederholte_kennungen(db):
    """Einträge jeder Kennung, die in derselben Vorlage mehrfach steht, nach ihrer Stelle in der Beratungsfolge
    (`position`): je Kennung und Vorlage eine Liste aus (Sitzungstag oder None, Sitzung abgesagt). Eine ältere Datenbank
    ohne `position` im Schlüssel: None."""
    if not any(r[1] == "position" and r[5] for r in db.execute("PRAGMA table_info(consultation)")):
        return None
    from .process import local_day

    def tag(start):
        try:
            return local_day(start)
        except (TypeError, ValueError):
            return None

    je_paar = {}
    for cid, pid, start, abgesagt in db.execute(
            "SELECT c.id, c.paper_id, m.start_date, m.cancelled FROM consultation c "
            "LEFT JOIN meeting m ON m.id = c.meeting_id ORDER BY c.paper_id, c.id, c.position"):
        je_paar.setdefault((cid, pid), []).append((tag(start), bool(abgesagt)))
    return [eintraege for eintraege in je_paar.values() if len(eintraege) > 1]


def reihenfolge_wiederholter_kennungen(db):
    """Kennungen mehrfach in derselben Vorlage, deren Einträge nach ihrer Stelle in der Beratungsfolge (`position`) nicht
    nach dem Sitzungstag geordnet sind (ein späterer Eintrag mit früherem Tag; Einträge ohne Sitzung zählen nicht mit):
    (Kennungen mehrfach in derselben Vorlage, davon abweichend geordnet); nur Zahlen. Der Stand einer Vorlage folgt bei
    einer solchen Kennung dem Eintrag mit dem spätesten Sitzungstag, bei gleichem Tag dem späteren; hat der letzte
    Eintrag keinen Sitzungstag, folgt er diesem (process.massgeblich, export._paper_detail; Entscheidung 17.11.2026
    (15), vorher dem letzten Eintrag nach `position`); Einträge abgesagter Sitzungen zählen dabei nicht (Entscheidung
    17.11.2026 (16) (A)), hier aber mit. Die Zahl zeigt, bei wie vielen Kennungen das vom letzten Eintrag abweichen kann
    (Prüfung bs). Eine ältere Datenbank ohne `position` im Schlüssel: None."""
    mehrfach = _wiederholte_kennungen(db)
    if mehrfach is None:
        return None
    mehrfach = [[t for t, _ in eintraege if t] for eintraege in mehrfach]
    return len(mehrfach), sum(tage != sorted(tage) for tage in mehrfach)


def abgesagte_wiederholter_kennungen(db):
    """Kennungen mehrfach in derselben Vorlage, bei denen wegen einer abgesagten Sitzung ein anderer Eintrag für den
    Stand zählt (process.massgeblich mit und ohne Angabe abgesagter Sitzungen, Entscheidung 17.11.2026 (16) (A) und
    (B)): (Kennungen mehrfach in derselben Vorlage, davon mit anderem Eintrag); nur Zahlen. Eine ältere Datenbank ohne
    `position` im Schlüssel: None."""
    mehrfach = _wiederholte_kennungen(db)
    if mehrfach is None:
        return None
    from .process import massgeblich
    return len(mehrfach), sum(massgeblich([t for t, _ in e]) != massgeblich([t for t, _ in e], [a for _, a in e])
                              for e in mehrfach)


def stand_und_ende(db, base=None):
    """Widersprüche zwischen dem Stand im Export und dem Ende des Weges in prozesse.json (Offen (8) in TECHNIK.md,
    Entscheidung 17.11.2026 (16) (B); nur Zahlen, kein Befund). Das Ende wie in export._paths: process.path_key mit den
    Stationen der Vorlage aus den Gebietsdateien des Exports (`base`, Vorgabe config.EXPORT / config.STADT) und den
    Kennungen ihrer Beratungen aus der Datenbank nach `position` (export._kennungen, wie export._paths); jede Vorlage
    einmal, auch wenn sie in mehreren Gebietsdateien steht. prozesse.json zählt alle Vorlagen der Datenbank, die
    Gebietsdateien nicht jede (etwa eine Vorlage ohne Datum und ohne Ortsbezug); solche Vorlagen zählt die fünfte Zahl.
    Liefert (Vorlagen mit Stand „entschieden“ und einem Ergebnis am Ende, das die Beratung nicht abschließt (nicht
    process.is_final); Vorlagen mit anderem Stand und einem Ergebnis am Ende, das als Ergebnis einer entscheidenden
    Beratung „entschieden“ ergibt (process.stand); Vorlagen der Gebietsdateien mit Ergebnis am Ende; Vorlagen, deren
    Zahl der Stationen nicht zur Datenbank passt, ohne Zählung; Vorlagen der Datenbank in keiner Gebietsdatei, ohne
    Zählung; Vorlagen mit Stand „entschieden“ und einem Ergebnis am Ende, das die Beratung abschließt, aber nicht
    entscheidet (process.is_final, nicht process.entscheidet: „ohne Votum“, „nicht abgestimmt“, KEIN_BESCHLUSS), auf
    derselben Grundlage wie die dritte Zahl) oder None ohne Gebietsdateien. Seit der Entscheidung 18.11.2026 (1) folgt
    das Ende dem Stand, seit der Entscheidung 18.11.2026 (2) auch bei einem Ende, das nicht entscheidet ((A2), sechste
    Zahl), und bei einem zählenden Eintrag, der nicht entscheidend ist ((B2), zweite Zahl): Die erste, zweite und
    sechste Zahl sind nach dem Aufbau von process.path_key 0; die Zeilen in kennzahlen bleiben als Schutz (nur Zahlen,
    kein Befund)."""
    from . import export, process as proc
    base = base or config.EXPORT / config.STADT
    dateien = [f for d in GEBIETSDATEIEN for f in sorted((base / d).glob("*.json"))]
    if not dateien:
        return None
    kennungen = export._kennungen(db)
    gesehen, offen_entschieden, entschieden_anders, mit_ergebnis, abweichend, ohne_entscheidung = set(), 0, 0, 0, 0, 0
    for f in dateien:
        for p in json.loads(f.read_text())["papers"]:
            if (p.get("source_object") or p["reference"]) in gesehen:
                continue
            gesehen.add(p.get("source_object") or p["reference"])
            k = kennungen.get(p.get("source_object"), [])
            if len(k) != len(p["process"]):
                abweichend += 1
                continue
            _, ende, art = proc.path_key(p, k)
            if art != "ergebnis":
                continue
            mit_ergebnis += 1
            if p.get("stand") == "entschieden":
                offen_entschieden += not proc.is_final(ende)
                ohne_entscheidung += proc.is_final(ende) and not proc.entscheidet({"authoritative": True,
                                                                                    "result": ende})
            elif proc.stand({"process": [{"authoritative": True, "result": ende}]}) == "entschieden":
                entschieden_anders += 1
    ohne_datei = sum(pid not in gesehen for (pid,) in db.execute("SELECT id FROM paper"))
    return offen_entschieden, entschieden_anders, mit_ergebnis, abweichend, ohne_datei, ohne_entscheidung


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
    print(beratungen_je_vorlage(db))
    reihenfolge = reihenfolge_wiederholter_kennungen(db)
    if reihenfolge:
        print(f"Kennungen mehrfach in derselben Vorlage, deren Einträge nicht nach dem Sitzungstag geordnet sind: "
              f"{reihenfolge[1]} von {reihenfolge[0]} (der Stand folgt dem Eintrag mit dem spätesten Sitzungstag, bei "
              f"gleichem Tag dem späteren; hat der letzte Eintrag keinen Sitzungstag, folgt er diesem; für den Stand "
              f"zählen Einträge abgesagter Sitzungen nicht)")
    # Entscheidung 17.11.2026 (16) (B): Wirkung von (16) (A) und Widersprüche zwischen Stand und Ende des Weges (Offen
    # (8)), nur Zahlen, kein Befund; seit 18.11.2026 (1) und (2) folgt das Ende dem Stand, die Zeile bleibt als Schutz
    abgesagt = abgesagte_wiederholter_kennungen(db)
    if abgesagt:
        print(f"Kennungen mehrfach in derselben Vorlage, bei denen wegen einer abgesagten Sitzung ein anderer Eintrag "
              f"zählt: {abgesagt[1]} von {abgesagt[0]}")
    ende = stand_und_ende(db)
    print("Stand und Ende des Weges (prozesse.json) widersprechen sich: " + (
        "nicht ermittelt (Gebietsdateien des Exports fehlen)" if ende is None else
        f"{ende[0]} Vorlagen mit Stand „entschieden“ und nicht abschließendem Ergebnis am Ende (etwa vertagt), "
        f"{ende[1]} Vorlagen mit Entscheidung am Ende und anderem Stand, von {ende[2]} Vorlagen der Gebietsdateien "
        f"mit Ergebnis am Ende"
        + (f"; {ende[3]} Vorlagen nicht gezählt (Zahl der Stationen passt nicht zur Datenbank)" if ende[3] else "")
        + (f"; {ende[4]} Vorlagen der Datenbank in keiner Gebietsdatei, nicht gezählt" if ende[4] else "")))
    # Nachfrage (a) zur Entscheidung 18.11.2026 (1): erst gezählt; seit 18.11.2026 (2) (A2) zeigt das Ende dort die
    # Entscheidung, die erste Zahl ist also 0; die Zeile bleibt als Schutz, auch bei 0; kein Befund
    if ende is not None:
        print(f"Vorlagen mit Stand „entschieden“ und abschließendem Ergebnis ohne Entscheidung am Ende (etwa ohne "
              f"Votum, nicht abgestimmt; seit der Entscheidung 18.11.2026 (2) zeigt das Ende die Entscheidung, die "
              f"Zeile bleibt als Schutz): {ende[5]} von {ende[2]} Vorlagen der Gebietsdateien mit Ergebnis am Ende")
    # Anteile je Zeile, also je Eintrag der Beratungsfolge einer Vorlage (Entscheidung 17.11.2026 (14))
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


def gebiete(db, base=None):
    """Kölner Gebiete: 86 Stadtteile und 9 Stadtbezirke in den Geodaten (CLAUDE.md 2); jeder Ort in der Datenbank
    liegt in einem davon; ein Punkt aus der Ortsangabe der Stadt gilt nur in einem Kölner Stadtteil als „Ort genau“
    (punkte_der_stadt, `base` wie bei datenschutz). Liefert (Befunde, nicht durchgeführte Prüfungen)."""
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
    if config.ORTSTEILE.exists():   # sonst oben als nicht durchgeführt gemeldet
        befunde += punkte_der_stadt(db, base)
    return befunde, fehlend


def punkte_der_stadt(db, base=None):
    """Schutz für die Entscheidung 19.11.2026 (4) (d): Ein Punkt aus der Ortsangabe der Stadt gilt nur in einem Kölner
    Stadtteil als „Ort genau“, außerhalb aller Stadtteile verwirft build ihn. Jeder Ortsbezug mit Methode
    „oparl_location“ und Konfidenz hoch trägt also einen Stadtteil und einen Punkt in einem Kölner Stadtteil: in der
    Datenbank (je Ortsangabe) und in vorlagen.geojson (je Punkt; die Gebietsdateien tragen dieselben Ortsbezüge aus
    export._locations). Fehlt vorlagen.geojson, meldet das datenschutz. Ausgabe nur Zahlen; liefert die Befunde."""
    base = Path(base) if base else config.EXPORT / config.STADT
    ortsteile = Ortsteile(config.ORTSTEILE)

    def ausserhalb(ortsteil, lon, lat):
        return ortsteil is None or lon is None or lat is None or ortsteile.locate(lon, lat) is None

    def aus_geojson(f):
        lon, lat, *_ = list((f.get("geometry") or {}).get("coordinates") or ()) + [None, None]
        return f["properties"].get("ortsteil"), lon, lat

    orte = db.execute("SELECT DISTINCT l.id, l.ortsteil, l.lon, l.lat FROM paper_location pl JOIN location l "
                      "ON l.id = pl.location_id WHERE pl.method = ? AND pl.confidence = 'hoch'",
                      (OPARL_PUNKT,)).fetchall()
    zahlen = {"Datenbank": (sum(ausserhalb(*r[1:]) for r in orte), len(orte))}
    if (base / "vorlagen.geojson").exists():
        punkte = [aus_geojson(f) for f in json.loads((base / "vorlagen.geojson").read_text())["features"]
                  if f["properties"].get("method") == OPARL_PUNKT and f["properties"].get("confidence") == "hoch"]
        zahlen["vorlagen.geojson"] = (sum(ausserhalb(*x) for x in punkte), len(punkte))
    print("Punkte aus der Ortsangabe der Stadt als „Ort genau“ (oparl_location, hoch) ohne Punkt in einem Kölner "
          "Stadtteil (Entscheidung 19.11.2026 (4) (d)): "
          + ", ".join(f"{k} {n} von {m}" for k, (n, m) in zahlen.items()))
    if not any(n for n, _ in zahlen.values()):
        return []
    return ["Gebiete: Punkt aus der Ortsangabe der Stadt als „Ort genau“ ohne Punkt in einem Kölner Stadtteil (build "
            "verwirft ihn, Entscheidung 19.11.2026 (4) (d)): "
            + ", ".join(f"{k} {n}" for k, (n, _) in zahlen.items() if n)]


def _fehlt(bereich, pfad, schritt):
    text = f"{bereich}: {pfad} fehlt (`python -m pipeline {schritt}`)"
    print(f"NICHT DURCHGEFÜHRT – {text}")
    return text


def _hauskoordinate(level=None, method=None, source=None):
    """Ortsbezug auf einer Hauskoordinate (Ebene „adresse“ aus „Adressen Köln“), auch wenn er vererbt ist."""
    return level == "adresse" or method == PUNKT or source == config.QUELLE_ADRESSEN


# genauer Punkt aus einer Ortsangabe der Stadt (Stufe A, geojson Point): Methode in den Exporten (ohne Erlaubnis führt
# build ihn auf den Stadtteil zurück, Methode „oparl_sublocality“, oder lässt die Koordinate weg; außerhalb aller Kölner
# Stadtteile verwirft build ihn auch mit Erlaubnis, punkte_der_stadt)
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


def _ics_bloecke(pfad):
    """VEVENT-Blöcke einer iCalendar-Datei (publish.write_calendar) als Listen ihrer entfalteten Zeilen, so wie sie in
    der Datei stehen (gleiche Feldnamen mehrfach, Parameter am Feldnamen); für _ics_ereignisse und _dtstamp."""
    text = re.sub(r"\r?\n[ \t]", "", pfad.read_text(encoding="utf-8"))
    return [re.split(r"\r?\n", block.split("END:VEVENT")[0]) for block in text.split("BEGIN:VEVENT")[1:]]


def _ics_ereignisse(pfad):
    """VEVENT-Blöcke einer iCalendar-Datei (publish.write_calendar) als [{Feld: Text}]: Zeilen entfaltet, Text nach
    RFC 5545 zurückgewandelt (\\n, \\, \\; \\\\), Parameter am Feldnamen abgetrennt. Steht ein Feld mehrfach im selben
    Block, bleibt die letzte Zeile; wo das zählt, liest _ics_bloecke die Zeilen selbst (zeitstempel_kalender)."""
    out = []
    for zeilen in _ics_bloecke(pfad):
        felder = {}
        for zeile in zeilen:
            name, trenner, wert = zeile.partition(":")
            if trenner:
                felder[name.split(";")[0].upper()] = re.sub(
                    r"\\([\\;,nN])", lambda x: "\n" if x.group(1) in "nN" else x.group(1), wert)
        out.append(felder)
    return out


def _sitzung_offen(m, sitzung, texte, offen, ohne, datei):
    """Würde die Maske einen der Texte einer Sitzung (Name, Gremium aus dem Namen) noch ändern
    (Maske.sitzungsname_offen, dieselbe Regel wie export._meetings)? Dann ein Befund: unter der Drucksache einer Vorlage
    der Maske, die in der Sitzung beraten wird (Maske.sitzungen; in `offen`), sonst ohne Drucksache als Zahl je Datei
    (`ohne`; datenschutz meldet nur Zahlen, keinen Namen und keine Kennung)."""
    if any(m.sitzungsname_offen(t) for t in texte):
        ref = m.sitzungen.get(sitzung)
        if ref:
            offen.add(ref)
        else:
            ohne[datei] = ohne.get(datei, 0) + 1


def _sitzungen(base, db, m, zahl, ohne):
    """Namen aller Sitzungen in zeit.json (`meetings[].name` und `gremium`) und termine.ics (Name: alle Zeilen der
    Beschreibung vor der Zeile „Tagesordnung …“, publish.ics_sitzungsname, auch bei einem Namen mit Zeilenumbruch;
    Gremium: die Zusammenfassung ohne den Zusatz einer Absage am Ende, publish.ZUSATZ_ABSAGE: „ (abgesagt)“ und, seit
    der Entscheidung 21.11.2026 (1) (c) (9), „ (laut Sitzungsnamen abgesagt)“; ohne diesen zweiten stünde der Zusatz im
    Gremium, und ein Gremium mit dem Namen einer Organisation gälte als Gremium aus dem Namen): export maskiert jeden
    Namen und jedes Gremium, das aus dem Namen stammt (Maske.sitzungsname; Entscheidung 19.11.2026 (3) (c); bis dahin
    nur bei Sitzungen, in denen eine Vorlage der Maske beraten wird, Maske.sitzungen, Offen (9) der Nachprüfung der
    dritten Korrektur). Ein Gremium mit dem Namen einer Organisation der Datenbank stammt nicht aus dem Namen und bleibt
    ungeprüft (export.gremium_aus_namen, wie export._meetings). Liefert die Drucksachen der Befunde bei Sitzungen mit
    einer Vorlage der Maske; Befunde bei Sitzungen ohne eine solche zählt `ohne` je Datei (_sitzung_offen). Zählt die
    Sitzungen in `zahl`."""
    from .export import gremium_aus_namen
    from .publish import ZUSATZ_ABSAGE, ics_sitzungsname
    organisationen = {r[0] for r in db.execute("SELECT name FROM organization") if r[0]}
    offen = set()
    zusatz = re.compile("(?:" + "|".join(map(re.escape, ZUSATZ_ABSAGE.values())) + ")$")

    def pruefen(datei, sitzung, name, gremium):
        zahl["sitzungen"] = zahl.get("sitzungen", 0) + 1
        texte = [name] + ([gremium] if gremium_aus_namen(gremium, organisationen) else [])
        _sitzung_offen(m, sitzung, texte, offen, ohne, datei)

    if (base / "zeit.json").exists():
        for x in json.loads((base / "zeit.json").read_text()).get("meetings") or ():
            pruefen("zeit.json", x.get("source_object"), x.get("name"), x.get("gremium"))
    if (base / "termine.ics").exists():
        for e in _ics_ereignisse(base / "termine.ics"):
            pruefen("termine.ics", e.get("UID"), ics_sitzungsname(e.get("DESCRIPTION")),
                    zusatz.sub("", e.get("SUMMARY") or ""))
    return offen


def _aktuell(index, db, m, zahl, befunde, ohne):
    """„Aktuell in Köln“ in index.json (`aktuell`, export._aktuell; Entscheidung 19.11.2026 (1) (E)): Titel der Vorlagen
    wie in suche.json (Maske.offen mit ihrer Drucksache), das Gremium jeder Sitzung wie in _sitzungen (seit der
    Entscheidung 19.11.2026 (3) (c) bei jeder Sitzung, Maske.sitzungsname_offen; ein Gremium mit dem Namen einer
    Organisation der Datenbank stammt nicht aus dem Sitzungsnamen und bleibt ungeprüft, export.gremium_aus_namen). Ohne
    `aktuell` (Vorschau, keine Karte) nichts zu prüfen. Liefert die Drucksachen mit ungekürztem Text (bei einem Gremium
    die einer Vorlage der Maske in der Sitzung; ohne eine solche zählt `ohne` die Sitzungen, _sitzung_offen); zählt
    Titel und Gremien in `zahl`. Befunde in `befunde`, nur mit Zahl und
    Schlüsselname: eine Karte außerhalb von export.AKTUELL_FELDER, ein Feld außerhalb der festen Liste ihrer Karte
    (etwa ein Sitzungsname, eine Frist oder ein Feld mit Namen von Personen) und das Gebiet „gesamt“ bei einer
    Vorlage (export._heimat)."""
    from .export import AKTUELL_FELDER, gremium_aus_namen
    aktuell = index.get("aktuell") if isinstance(index, dict) else None
    aktuell = aktuell if isinstance(aktuell, dict) else {}
    vorlagen = [v for v in aktuell.get("vorlagen") or () if isinstance(v, dict)]
    sitzungen = [x for x in aktuell.get("sitzungen") or () if isinstance(x, dict)]
    fremd = sorted(map(str, set(aktuell) - set(AKTUELL_FELDER)))
    if fremd:
        befunde.append(f"Datenschutz: index.json „aktuell“ mit Karten außerhalb von export.AKTUELL_FELDER: "
                       f"{len(fremd)}, Schlüssel {', '.join(fremd[:5])}")
    for karte, eintraege in (("sitzungen", sitzungen), ("vorlagen", vorlagen)):
        felder = [set(map(str, e)) - set(AKTUELL_FELDER[karte]) for e in eintraege]
        if any(felder):
            befunde.append(f"Datenschutz: index.json „aktuell“, Karte {karte}: Einträge mit Feldern außerhalb der "
                           f"festen Liste (export.AKTUELL_FELDER): {sum(map(bool, felder))}, Schlüssel "
                           f"{', '.join(sorted(set().union(*felder))[:5])}")
    gesamt = sum(v.get("area") == "gesamt" for v in vorlagen)
    if gesamt:
        befunde.append(f"Datenschutz: index.json „aktuell“: Vorlagen mit dem Gebiet „gesamt“ (export._heimat nennt nie "
                       f"„gesamt“): {gesamt}")
    organisationen = {r[0] for r in db.execute("SELECT name FROM organization") if r[0]}
    offen = {v.get("reference") for v in vorlagen if m.offen(v.get("name"), v.get("reference"))}
    for x in sitzungen:
        if gremium_aus_namen(x.get("gremium"), organisationen):
            _sitzung_offen(m, x.get("source_object"), [x.get("gremium")], offen, ohne, "index.json")
    zahl["aktuell"] = len(vorlagen) + len(sitzungen)
    return offen


def hinweise_sitzungen(base=None):
    """Hinweise zum Stand aus dem Sitzungsnamen (Entscheidung 20.11.2026 (7) (b); export.hinweis_sitzung, dieselbe
    Regel wie export._meetings) im Kölner Export (`base`, Vorgabe config.EXPORT / config.STADT):
    - zeit.json: Jede Sitzung trägt `hinweis` genau dann, wenn die Regel ihn aus ihrem Namen (`name`, nach der Maske)
      ableitet, und mit demselben Wert; ein Feld ohne Hinweis (auch `null`) ist ebenso ein Befund.
    - index.json („Aktuell in Köln“, `aktuell.sitzungen`, ohne Namen): Der Hinweis folgt der Regel über den Namen
      derselben Sitzung in zeit.json (`source_object`); eine Sitzung, die dort fehlt, ist ein Befund. Eine Sitzung,
      deren Name eine Absage nennt, steht dort nicht (export._aktuell lässt sie aus wie eine abgesagte).
    Ohne zeit.json (Kartenvorschau ohne Vorlagen) nichts zu prüfen; nennt index.json dann Sitzungen, fehlt zeit.json
    für die Prüfung. Befunde und Ausgabe nur mit Zahlen, ohne Namen und Kennungen. Liefert (befunde, fehlend)."""
    from .export import hinweis_sitzung
    base = Path(base) if base else config.EXPORT / config.STADT
    befunde, fehlend = [], []
    zeit = json.loads((base / "zeit.json").read_text()) if (base / "zeit.json").exists() else None
    index = json.loads((base / "index.json").read_text()) if (base / "index.json").exists() else {}
    aktuell = index.get("aktuell") if isinstance(index, dict) else None
    aktuell = aktuell if isinstance(aktuell, dict) else {}
    sitzungen = [x for x in aktuell.get("sitzungen") or () if isinstance(x, dict)]
    print("\nHinweise zum Stand aus dem Sitzungsnamen (export.hinweis_sitzung)")
    if zeit is None:
        if sitzungen:
            fehlend.append(_fehlt("Hinweise zum Stand", base / "zeit.json", "export"))
        print("zeit.json fehlt: keine Sitzung zu prüfen")
        return befunde, fehlend
    meetings = [x for x in zeit.get("meetings") or () if isinstance(x, dict)]
    erwartet = [hinweis_sitzung(x.get("name")) for x in meetings]
    abweichend = sum(("hinweis" in x, x.get("hinweis")) != (h is not None, h) for x, h in zip(meetings, erwartet))
    if abweichend:
        befunde.append(f"Hinweise zum Stand: Sitzungen in zeit.json, deren Feld `hinweis` nicht der Regel "
                       f"export.hinweis_sitzung über ihren Namen folgt (fehlt, zu viel oder anderer Wert): "
                       f"{abweichend}")
    je_sitzung = {x.get("source_object"): h for x, h in zip(meetings, erwartet)}
    fehlt = sum(x.get("source_object") not in je_sitzung for x in sitzungen)
    aus_zeit = [je_sitzung.get(x.get("source_object")) for x in sitzungen]
    anders = sum(("hinweis" in x, x.get("hinweis")) != (h is not None, h)
                 for x, h in zip(sitzungen, aus_zeit) if x.get("source_object") in je_sitzung)
    if fehlt or anders:
        befunde.append(f"Hinweise zum Stand: Sitzungen in index.json („Aktuell in Köln“), deren Feld `hinweis` nicht "
                       f"der Regel export.hinweis_sitzung über den Namen derselben Sitzung in zeit.json folgt: "
                       f"{anders}, ohne dieselbe Sitzung in zeit.json: {fehlt}")
    abgesagt = sum(h == "abgesagt" for h in aus_zeit)
    if abgesagt:
        befunde.append(f"Hinweise zum Stand: Sitzungen mit Hinweis „abgesagt“ aus dem Namen in index.json („Aktuell in "
                       f"Köln“; export._aktuell lässt sie aus wie abgesagte): {abgesagt}")
    print(f"Sitzungen in zeit.json: {len(meetings)}, davon mit Hinweis abgesagt "
          f"{sum(h == 'abgesagt' for h in erwartet)}, verschoben {sum(h == 'verschoben' for h in erwartet)}; "
          f"Sitzungen in index.json („Aktuell in Köln“): {len(sitzungen)}")
    return befunde, fehlend


def absagen_kalender(base=None):
    """Absagen in termine.ics (Entscheidung 21.11.2026 (1) (c) (9); publish.write_calendar mit export.absage, derselben
    Regel) im Kölner Export (`base`, Vorgabe config.EXPORT / config.STADT): Jeder Termin (VEVENT) gehört zu einer
    Sitzung in zeit.json (UID = `source_object`). Er trägt STATUS:CANCELLED genau dann, wenn diese Sitzung als abgesagt
    gilt (OParl `cancelled` oder Hinweis „abgesagt“ aus dem Namen), sonst STATUS:CONFIRMED, und am Ende der
    Zusammenfassung den Zusatz ihres Grundes (publish.ZUSATZ_ABSAGE: „ (abgesagt)“ bei OParl `cancelled`, „ (laut
    Sitzungsnamen abgesagt)“ beim Hinweis aus dem Namen), ohne Absage keinen dieser Zusätze. Ohne Termine nichts zu
    prüfen; fehlt zeit.json neben Terminen oder termine.ics neben zeit.json, gilt die Prüfung als nicht durchgeführt.
    Befunde und Ausgabe nur mit Zahlen, ohne Namen und Kennungen; die Ausgabe nennt die Termine und davon die
    abgesagten je Grund nach zeit.json (ohne Befund dieselben Zahlen wie die Zeile von write_calendar im Log von
    `export`). Liefert (befunde, fehlend)."""
    from .export import absage
    from .publish import ZUSATZ_ABSAGE
    base = Path(base) if base else config.EXPORT / config.STADT
    befunde, fehlend = [], []
    termine = _ics_ereignisse(base / "termine.ics") if (base / "termine.ics").exists() else None
    print("\nAbsagen in termine.ics (export.absage)")
    if not (base / "zeit.json").exists():
        if termine:
            fehlend.append(_fehlt("Absagen im Kalender", base / "zeit.json", "export"))
        print("zeit.json fehlt: kein Termin zu prüfen")
        return befunde, fehlend
    if termine is None:
        fehlend.append(_fehlt("Absagen im Kalender", base / "termine.ics", "export"))
        return befunde, fehlend
    zeit = json.loads((base / "zeit.json").read_text())
    grund = {x.get("source_object"): absage(x) for x in zeit.get("meetings") or () if isinstance(x, dict)}
    zusatz = {z: g for g, z in ZUSATZ_ABSAGE.items()}
    ohne = status = anders = 0
    zahl = dict.fromkeys(ZUSATZ_ABSAGE, 0)
    for e in termine:
        if e.get("UID") not in grund:
            ohne += 1
            continue
        g = grund[e["UID"]]
        if g:
            zahl[g] += 1
        status += e.get("STATUS") != ("CANCELLED" if g else "CONFIRMED")
        anders += next((zusatz[z] for z in zusatz if (e.get("SUMMARY") or "").endswith(z)), None) != g
    if ohne:
        befunde.append(f"Kalender: Termine in termine.ics ohne dieselbe Sitzung in zeit.json (UID): {ohne}")
    if status:
        befunde.append(f"Kalender: Termine in termine.ics, deren STATUS nicht der Absage der Sitzung in zeit.json "
                       f"folgt (export.absage; STATUS:CANCELLED genau bei OParl `cancelled` oder Hinweis „abgesagt“ "
                       f"aus dem Namen, sonst STATUS:CONFIRMED): {status}")
    if anders:
        befunde.append(f"Kalender: Termine in termine.ics, deren Zusatz am Ende der Zusammenfassung nicht dem Grund "
                       f"der Absage der Sitzung in zeit.json folgt (publish.ZUSATZ_ABSAGE): {anders}")
    print(f"Termine in termine.ics: {len(termine)}, davon abgesagt laut OParl {zahl['oparl']}, abgesagt laut "
          f"Sitzungsnamen {zahl['name']}")
    return befunde, fehlend


def _utc_zeitpunkt(wert):
    """Ist `wert` ein Zeitpunkt in UTC nach RFC 5545 (DATE-TIME in der Form „JJJJMMTTTHHMMSSZ“, 3.3.5) mit einem Datum
    und einer Uhrzeit, die es gibt? Die Sekunde 60 (Schaltsekunde, 3.3.12) gilt als gültig."""
    if not isinstance(wert, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", wert):
        return False
    try:
        datetime.strptime(wert[:13] + ("59" if wert[13:15] == "60" else wert[13:15]), "%Y%m%dT%H%M%S")
    except ValueError:
        return False
    return True


def _dtstamp(zeilen):
    """DTSTAMP eines Termins aus seinen entfalteten Zeilen (_ics_bloecke): der Wert hinter „DTSTAMP:“, wenn genau eine
    Zeile den Feldnamen DTSTAMP trägt und dieser ohne Parameter steht, sonst None. Den Feldnamen vergleicht die Funktion
    ohne Rücksicht auf Groß- und Kleinschreibung (RFC 5545, 3.1). Eine zweite Zeile DTSTAMP im selben Termin (nach
    3.6.1 höchstens einmal) und ein Parameter am Feldnamen ergeben None: write_calendar schreibt keinen Parameter, und
    TZID ist bei einem Wert in UTC nicht erlaubt (3.2.19)."""
    treffer = [z for z in zeilen if re.split(r"[;:]", z, maxsplit=1)[0].upper() == "DTSTAMP"]
    if len(treffer) != 1 or treffer[0][7:8] != ":":
        return None
    return treffer[0][8:]


def zeitstempel_kalender(base=None):
    """DTSTAMP in termine.ics (Entscheidung 21.11.2026 (3), #47 (2); publish.write_calendar mit publish._zeitstempel) im
    Kölner Export (`base`, Vorgabe config.EXPORT / config.STADT): Jeder Termin trägt genau eine Zeile DTSTAMP ohne
    Parameter (_dtstamp) mit einem gültigen Zeitpunkt in UTC (_utc_zeitpunkt), und alle Termine der Datei tragen
    denselben, den Zeitpunkt des Aufbaus. Ein Termin mit keiner oder mehr als einer solchen Zeile oder mit einem
    Parameter am Feldnamen zählt als ohne gültigen Zeitpunkt; _ics_ereignisse behielte nur die letzte Zeile und schnitte
    Parameter ab, deshalb liest die Prüfung die Zeilen selbst (_ics_bloecke). Bis zum 22.11.2026 stand dort der Beginn
    der Sitzung; mehrere Termine zeigen dann verschiedene Zeitpunkte. Keine Schranke nach unten oder oben: Der
    Erzeugungszeitpunkt des Exports (`meta.generated_at` in index.json, export._meta) entsteht in export erst nach
    termine.ics; als obere Schranke hinge er an der Reihenfolge der Schritte. Ohne termine.ics oder ohne Termine nichts
    zu prüfen (fehlt die Datei neben zeit.json, meldet das absagen_kalender). Befunde und Ausgabe nur mit Zahlen, die
    Ausgabe in einer Zeile nach einer Leerzeile. Liefert die Befunde."""
    base = Path(base) if base else config.EXPORT / config.STADT
    if not (base / "termine.ics").exists():
        print("\nDTSTAMP in termine.ics: keine Datei, nichts zu prüfen")
        return []
    werte = [_dtstamp(zeilen) for zeilen in _ics_bloecke(base / "termine.ics")]
    ungueltig = sum(not _utc_zeitpunkt(w) for w in werte)
    zeitpunkte = len({w for w in werte if _utc_zeitpunkt(w)})
    befunde = []
    if ungueltig:
        befunde.append(f"Kalender: Termine in termine.ics ohne DTSTAMP als gültigen Zeitpunkt in UTC "
                       f"(JJJJMMTTTHHMMSSZ, RFC 5545): {ungueltig}")
    if zeitpunkte > 1:
        befunde.append(f"Kalender: DTSTAMP in termine.ics nicht bei allen Terminen derselbe Zeitpunkt des Aufbaus "
                       f"(verschiedene Zeitpunkte): {zeitpunkte}")
    print(f"\nDTSTAMP in termine.ics (Zeitpunkt des Aufbaus in UTC): {len(werte)} Termine, ohne gültigen Zeitpunkt "
          f"{ungueltig}, verschiedene Zeitpunkte {zeitpunkte}")
    return befunde


# --- Gremien, Ämter und Stationen (Entscheidung 21.11.2026 (2), Pull Request 4a) ------------------------------------

# Feldnamen, die auf Personen, Mitgliedschaften oder Besetzung deuten: in gremien.json und aemter.json nie (keine
# Besetzung, keine Namen von Personen; Entscheidung 19.11.2026 (1) (B))
PERSONENFELD = re.compile(r"person|member|mitglied|besetzung|vorsitz|sprecher|kontakt|email|telefon", re.I)


def _personenfelder(obj):
    """Zahl der Schlüssel in `obj` (rekursiv), deren Name PERSONENFELD trifft."""
    if isinstance(obj, dict):
        return sum(bool(PERSONENFELD.search(str(k))) + _personenfelder(v) for k, v in obj.items())
    if isinstance(obj, list):
        return sum(_personenfelder(v) for v in obj)
    return 0


def _gebietsvorlagen(base):
    """Vorlagen der Gebietsdateien, jede einmal (nach source_object, sonst Drucksache), in der Reihenfolge der Dateien;
    None ohne Gebietsdatei."""
    dateien = [f for d in GEBIETSDATEIEN for f in sorted((base / d).glob("*.json"))]
    if not dateien:
        return None
    gesehen, aus = set(), []
    for f in dateien:
        for p in json.loads(f.read_text()).get("papers") or ():
            k = p.get("source_object") or p.get("reference")
            if k not in gesehen:
                gesehen.add(k)
                aus.append(p)
    return aus


def gremien(db, base=None):
    """gremien.json (pipeline/gremien.py, Freigabe „gremien“) im Kölner Export (`base`, Vorgabe config.EXPORT /
    config.STADT). Erwartet, wenn die Freigabe an ist und der Export Vorlagen hat (zeit.json liegt vor); fehlt sie dann,
    ist die Prüfung nicht durchgeführt. Ohne Freigabe ist eine vorhandene Datei ein Befund. Geprüft:
    - nur die Schlüssel `meta` und `gremien`, in `meta` nur gremien.META_FELDER, je Gremium nur gremien.FELDER (die
      Pflichtfelder gremien.PFLICHT vorhanden), je nächster Sitzung nur gremien.FELDER_SITZUNG; kein Feldname, der auf
      Personen deutet (PERSONENFELD);
    - Gruppe aus gremien.GRUPPEN, `paragraf` genau bei „ausschuss“, `stadtbezirk` nur bei „bezirksvertretung“; Kennungen
      eindeutig; keine Organisation der Klasse „Fraktionen und Gruppen“ und keine, die nicht in der Datenbank steht;
    - Zeitraum nach F7: `meta.datenstand` wie gremien.datenstand, `meta.zeitraum` = {seit: gebietszahlen.window_start,
      bis: Datenstand};
    - jede nächste Sitzung steht in zeit.json, ist nicht abgesagt (export.absage) und liegt nach dem Datenstand;
      ist die Liste der Sitzungen nicht aktuell (gremien.sitzungsliste mit STAND.json), gibt es keine nächste Sitzung;
    - die ganze Datei gleich der Rechnung mit denselben Funktionen (gremien.daten) aus Datenbank, zeit.json,
      meetings.json, den Vorlagen der Gebietsdateien (jede einmal), gremien.sitzungsliste und der Organisation je Station
      (gremien.beratungen, für vorlagen_12m auch aufgelöster Gremien); fehlt meetings.json, nicht durchgeführt.
    Befunde und Ausgabe nur mit Zahlen. Liefert (befunde, fehlend)."""
    from . import gebietszahlen, gremien as gr
    from .export import absage
    base = Path(base) if base else config.EXPORT / config.STADT
    befunde, fehlend = [], []
    pfad = base / gr.DATEI
    print(f"\nGremien ({gr.DATEI}, Freigabe „{gr.FUNKTION}“)")
    if not gr.an():
        if pfad.exists():
            befunde.append(f"Gremien: {gr.DATEI} liegt vor, obwohl die Freigabe „{gr.FUNKTION}“ aus ist: 1")
        print("abgeschaltet (config.ZUSATZTHEMEN) – keine Datei erwartet")
        return befunde, fehlend
    if not (base / "zeit.json").exists():
        print("zeit.json fehlt (Export ohne Vorlagen): keine Datei erwartet")
        return befunde, fehlend
    if not pfad.exists():
        fehlend.append(_fehlt("Gremien", pfad, "export"))
        return befunde, fehlend
    doc = json.loads(pfad.read_text())
    doc = doc if isinstance(doc, dict) else {}
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    eintraege = [e for e in doc.get("gremien") or () if isinstance(e, dict)]
    fehler = Counter()
    fehler["Schlüssel außerhalb von meta und gremien"] = sum(k not in ("meta", "gremien") for k in doc)
    fehler["Felder in meta außerhalb von gremien.META_FELDER"] = sum(k not in gr.META_FELDER for k in meta)
    fehler["Einträge, die kein Objekt sind"] = len(doc.get("gremien") or ()) - len(eintraege)
    fehler["Felder außerhalb von gremien.FELDER"] = sum(k not in gr.FELDER for e in eintraege for k in e)
    fehler["fehlende Pflichtfelder"] = sum(k not in e for e in eintraege for k in gr.PFLICHT)
    naechste = [e["naechste_sitzung"] for e in eintraege if "naechste_sitzung" in e]
    fehler["Felder der nächsten Sitzung außerhalb von gremien.FELDER_SITZUNG"] = sum(
        k not in gr.FELDER_SITZUNG for n in naechste for k in (n if isinstance(n, dict) else {"": 0}))
    fehler["Feldnamen, die auf Personen deuten"] = _personenfelder(doc)
    fehler["Gruppe außerhalb von gremien.GRUPPEN"] = sum(e.get("gruppe") not in gr.GRUPPEN for e in eintraege)
    fehler["Paragraf nicht genau bei Ausschüssen"] = sum(("paragraf" in e) != (e.get("gruppe") == "ausschuss")
                                                         for e in eintraege)
    fehler["Stadtbezirk außerhalb der Bezirksvertretungen"] = sum("stadtbezirk" in e and e.get("gruppe") !=
                                                                  "bezirksvertretung" for e in eintraege)
    keys = Counter(e.get("key") for e in eintraege)
    fehler["Kennungen mehrfach"] = sum(n - 1 for n in keys.values() if n > 1)
    klasse = dict(db.execute("SELECT id, classification FROM organization"))
    fehler["Fraktionen und Gruppen"] = sum(klasse.get(e.get("source_object")) == gr.KLASSE_FRAKTIONEN
                                           for e in eintraege)
    fehler["Organisationen, die nicht in der Datenbank stehen"] = sum(e.get("source_object") not in klasse
                                                                       for e in eintraege)
    stand = gr.datenstand(db)
    fehler["Datenstand anders als gremien.datenstand"] = int(meta.get("datenstand") != stand)
    fehler["Zeitraum nicht 365 Tage vor dem Datenstand (gebietszahlen.window_start)"] = int(
        meta.get("zeitraum") != {"seit": gebietszahlen.window_start(stand), "bis": stand})
    zeit = [m for m in json.loads((base / "zeit.json").read_text()).get("meetings") or () if isinstance(m, dict)]
    je_sitzung = {m.get("source_object"): m for m in zeit}
    n_ohne = n_abgesagt = n_frueh = 0
    for n in naechste:
        m = je_sitzung.get(n.get("source_object")) if isinstance(n, dict) else None
        if m is None:
            n_ohne += 1
        else:
            n_abgesagt += bool(absage(m))
            n_frueh += not ((m.get("date") or "") > stand)
    fehler["nächste Sitzungen ohne dieselbe Sitzung in zeit.json"] = n_ohne
    fehler["nächste Sitzungen, die abgesagt sind (export.absage)"] = n_abgesagt
    fehler["nächste Sitzungen nicht nach dem Datenstand"] = n_frueh
    liste = gr.sitzungsliste()
    fehler["nächste Sitzungen bei nicht aktueller Liste der Sitzungen (gremien.sitzungsliste)"] = (
        len(naechste) if liste else 0)
    orgs_je_sitzung = gr.organisationen_der_sitzungen()
    papers = _gebietsvorlagen(base) or []
    if orgs_je_sitzung is None:
        fehlend.append(_fehlt("Gremien (Sitzungen je Gremium)", config.MEETINGS, "fetch"))
    else:
        quellen = [dict(zip(("name", "url", "license", "retrieved_at"), r))
                   for r in db.execute("SELECT name, url, license, retrieved_at FROM source")]
        erwartet, _ = gr.daten(gr.organisationen(db), zeit, orgs_je_sitzung, papers, stand, quellen, liste,
                               beratungen_je=gr.beratungen(db))
        fehler["meta anders als gremien.daten"] = int(meta != erwartet["meta"])
        soll = {e["key"]: e for e in erwartet["gremien"]}
        ist = {e.get("key"): e for e in eintraege}
        fehler["Gremien fehlen (gremien.daten)"] = sum(k not in ist for k in soll)
        fehler["Gremien zu viel (gremien.daten)"] = sum(k not in soll for k in ist)
        for f in gr.FELDER:
            fehler[f"Feld {f} anders als gremien.daten"] = sum(
                (f in ist[k], ist[k].get(f)) != (f in soll[k], soll[k].get(f)) for k in soll if k in ist)
        fehler["Reihenfolge anders als gremien.daten"] = int(
            [e.get("key") for e in eintraege] != [e["key"] for e in erwartet["gremien"]] and
            set(ist) == set(soll))
    for text, n in fehler.items():
        if n:
            befunde.append(f"Gremien: {text}: {n}")
    je = Counter(e.get("gruppe") for e in eintraege)
    print(f"{gr.DATEI}: {len(eintraege)} Gremien (Rat {je['rat']}, Ausschüsse mit Paragraf {je['ausschuss']}, "
          f"Bezirksvertretungen {je['bezirksvertretung']}, übrige {je['uebrige']}), davon aufgelöst "
          f"{sum(bool(e.get('aufgeloest')) for e in eintraege)}, mit nächster Sitzung {len(naechste)}; Sitzungen in 12 "
          f"Monaten {sum(e.get('sitzungen_12m') or 0 for e in eintraege)}, Vorlagen in 12 Monaten (je Gremium) "
          f"{sum(e.get('vorlagen_12m') or 0 for e in eintraege)}")
    return befunde, fehlend


def aemter_aufbau(base=None):
    """aemter.json (aemter.aufbau, Freigabe „gremien“) im Kölner Export (`base`, Vorgabe config.EXPORT / config.STADT).
    Erwartet wie gremien.json, wenn die Freigabe an ist, der Export Vorlagen hat (zeit.json) und die Ämtertabelle einen
    Plan enthält; ohne Freigabe ist eine vorhandene Datei ein Befund. Geprüft: nur die Schlüssel `meta`, `dezernate` und
    `ohne_zuordnung`; je Dezernat, Eintrag und Eintrag ohne Zuordnung nur die Felder aus aemter.FELDER_DEZERNAT,
    FELDER_EINHEIT bzw. FELDER_OHNE_ZUORDNUNG; keine Untereinheit (weder als Ebene noch als Nummer einer Untereinheit
    des Plans); Einträge ohne Zuordnung nur mit „●“; `meta.quelle` mit Titel, Adresse, Stand und letzter Prüfung des
    jüngsten Plans; kein Feldname, der auf Personen deutet; die ganze Datei gleich aemter.aufbau. Befunde und Ausgabe nur
    mit Zahlen. Liefert (befunde, fehlend)."""
    from . import aemter, gremien as gr
    base = Path(base) if base else config.EXPORT / config.STADT
    befunde, fehlend = [], []
    pfad = base / aemter.DATEI_AUFBAU
    print(f"\nÄmter ({aemter.DATEI_AUFBAU}, Freigabe „{gr.FUNKTION}“)")
    if not gr.an():
        if pfad.exists():
            befunde.append(f"Ämter: {aemter.DATEI_AUFBAU} liegt vor, obwohl die Freigabe „{gr.FUNKTION}“ aus ist: 1")
        print("abgeschaltet (config.ZUSATZTHEMEN) – keine Datei erwartet")
        return befunde, fehlend
    plan = aemter.tabelle().neuester()
    if not (base / "zeit.json").exists() or plan is None:
        print("zeit.json oder Ämtertabelle fehlt: keine Datei erwartet")
        return befunde, fehlend
    if not pfad.exists():
        fehlend.append(_fehlt("Ämter", pfad, "export"))
        return befunde, fehlend
    doc = json.loads(pfad.read_text())
    doc = doc if isinstance(doc, dict) else {}
    dezernate = [d for d in doc.get("dezernate") or () if isinstance(d, dict)]
    einheiten = [e for d in dezernate for e in d.get("einheiten") or () if isinstance(e, dict)]
    ohne = [e for e in doc.get("ohne_zuordnung") or () if isinstance(e, dict)]
    unter = {z["dienststelle"] for z in plan.zeilen if z["ebene"] == "untereinheit"}
    quelle = (doc.get("meta") or {}).get("quelle") or {}
    fehler = Counter({
        "Schlüssel außerhalb von meta, dezernate und ohne_zuordnung": sum(
            k not in ("meta", "dezernate", "ohne_zuordnung") for k in doc),
        "Felder der Dezernate außerhalb von aemter.FELDER_DEZERNAT": sum(
            k not in aemter.FELDER_DEZERNAT for d in dezernate for k in d),
        "Felder der Einträge außerhalb von aemter.FELDER_EINHEIT": sum(
            k not in aemter.FELDER_EINHEIT for e in einheiten for k in e),
        "Felder ohne Zuordnung außerhalb von aemter.FELDER_OHNE_ZUORDNUNG": sum(
            k not in aemter.FELDER_OHNE_ZUORDNUNG for e in ohne for k in e),
        "Untereinheiten": sum(e.get("ebene") == "untereinheit" or e.get("nummer") in unter for e in einheiten + ohne),
        "Einträge ohne Zuordnung ohne „●“": sum(e.get("markierung") != aemter.OHNE_ZUORDNUNG for e in ohne),
        "Quelle ohne Titel, Adresse, Stand oder letzte Prüfung des jüngsten Plans": int(
            (quelle.get("titel"), quelle.get("url"), quelle.get("stand"), quelle.get("geprueft"))
            != (aemter.TITEL, plan.zeilen[0]["quelle"], plan.stand, plan.geprueft)),
        "Feldnamen, die auf Personen deuten": _personenfelder(doc),
        "Inhalt anders als aemter.aufbau": int(doc != aemter.aufbau()),
    })
    for text, n in fehler.items():
        if n:
            befunde.append(f"Ämter: {text}: {n}")
    je = Counter(e.get("ebene") for e in einheiten)
    print(f"{aemter.DATEI_AUFBAU}: Dezernate {len(dezernate)}, Einheiten der Dezernate {je['dezernatseinheit']}, "
          f"Dienststellen {je['dienststelle']}, Punktdienststellen {je['punktdienststelle']}, ohne Zuordnung "
          f"{len(ohne)}; Untereinheiten im Plan (nicht aufgenommen) {len(unter)}")
    return befunde, fehlend


def stationen(db, base=None):
    """Stationen der Prozesslinie in den Gebietsdateien (`process[]`, jede Vorlage einmal; Entscheidung 21.11.2026 (2)
    (F10), (F12)) im Kölner Export (`base`, Vorgabe config.EXPORT / config.STADT):
    - `hinweis` genau dann und mit dem Wert, den export.hinweis_station ergibt (Name der Sitzung an der Station, ohne
      ihn der Name derselben Sitzung in zeit.json); ein Feld ohne Hinweis ist ebenso ein Befund;
    - `gremium_key` genau dann und mit der Kennung, die gremien.kennungen mit dem Datenstand (gremien.datenstand) für die
      Organisation der Beratung ergibt (Datenbank: Vorlage und `position`), nur mit Freigabe „gremien“: Stationen
      aufgelöster Gremien tragen keine Kennung (Entscheidung 21.11.2026 (3) (G6)); jede Kennung steht in gremien.json und
      gehört dort keinem aufgelösten Gremium, wenn die Datei vorliegt.
    Ohne Gebietsdateien nichts zu prüfen (datenschutz meldet sie als fehlend). Befunde und Ausgabe nur mit Zahlen.
    Liefert (befunde, fehlend)."""
    from . import gremien as gr
    from .export import hinweis_station
    base = Path(base) if base else config.EXPORT / config.STADT
    befunde, fehlend = [], []
    print("\nStationen der Prozesslinie (export.hinweis_station, Kennung des Gremiums)")
    papers = _gebietsvorlagen(base)
    if papers is None:
        print("keine Gebietsdateien: keine Station zu prüfen")
        return befunde, fehlend
    namen = {}
    if (base / "zeit.json").exists():
        namen = {m.get("source_object"): m.get("name")
                 for m in json.loads((base / "zeit.json").read_text()).get("meetings") or () if isinstance(m, dict)}
    orgs = gr.organisationen(db)
    stand = gr.datenstand(db)
    keys = gr.kennungen(orgs, stand) if gr.an() else {}
    weg = {o["id"] for o in orgs if gr.aufgenommen(o) and gr.aufgeloest(o, stand)} if gr.an() else set()
    org = gr.beratungen(db)
    datei = base / gr.DATEI
    eintraege = ([e for e in json.loads(datei.read_text()).get("gremien") or () if isinstance(e, dict)]
                 if datei.exists() else None)
    in_datei = {e.get("key") for e in eintraege} if eintraege is not None else None
    aufgeloest = {e.get("key") for e in eintraege or () if e.get("aufgeloest")}
    zahl, hinweise = Counter(), Counter()
    for p in papers:
        for s in p.get("process") or ():
            zahl["stationen"] += 1
            zahl["mit_sitzung"] += bool(s.get("meeting_id"))
            h = hinweis_station(s, namen)
            hinweise[h] += bool(h)
            zahl["hinweis_anders"] += ("hinweis" in s, s.get("hinweis")) != (h is not None, h)
            o = org.get((p.get("source_object"), s.get("position")))
            k = keys.get(o)
            zahl["key_anders"] += ("gremium_key" in s, s.get("gremium_key")) != (k is not None, k)
            zahl["mit_key"] += "gremium_key" in s
            zahl["aufgeloest_ohne_key"] += o in weg and "gremium_key" not in s
            zahl["key_nicht_in_datei"] += ("gremium_key" in s and in_datei is not None
                                          and s["gremium_key"] not in in_datei)
            zahl["key_aufgeloest"] += "gremium_key" in s and s["gremium_key"] in aufgeloest
    if zahl["hinweis_anders"]:
        befunde.append(f"Stationen: Feld `hinweis` folgt nicht export.hinweis_station (fehlt, zu viel oder anderer "
                       f"Wert): {zahl['hinweis_anders']}")
    if zahl["key_anders"]:
        befunde.append(f"Stationen: Feld `gremium_key` folgt nicht der Organisation der Beratung (gremien.kennungen; "
                       f"ohne Freigabe „{gr.FUNKTION}“ kein Feld): {zahl['key_anders']}")
    if zahl["key_nicht_in_datei"]:
        befunde.append(f"Stationen: Kennung des Gremiums ohne Eintrag in {gr.DATEI}: {zahl['key_nicht_in_datei']}")
    if zahl["key_aufgeloest"]:
        befunde.append(f"Stationen: Kennung eines aufgelösten Gremiums aus {gr.DATEI}: {zahl['key_aufgeloest']}")
    print(f"Stationen: {zahl['stationen']}, mit Sitzung {zahl['mit_sitzung']}, mit Hinweis "
          f"{sum(hinweise.values())} (abgesagt {hinweise['abgesagt']}, verschoben {hinweise['verschoben']}), mit "
          f"Kennung des Gremiums {zahl['mit_key']}"
          + (f", Stationen aufgelöster Gremien (ohne Kennung) {zahl['aufgeloest_ohne_key']}" if gr.an() else ""))
    return befunde, fehlend


def suche_gremien(db, base=None):
    """Kennungen der Gremien in suche.json (Entscheidung 21.11.2026 (3) (G4), (G6)) im Kölner Export (`base`, Vorgabe
    config.EXPORT / config.STADT). Ohne Freigabe „gremien“ ist die Liste `gremium_keys` oder eine Spalte
    export.SUCHE_SPALTE_KENNUNGEN ein Befund. Mit Freigabe:
    - die Liste `gremium_keys` liegt vor, ohne doppelte Kennung, jede Zeile hat die Spalte, jeder Verweis ist eine Stelle
      in der Liste (aufsteigend, ohne Doppelte);
    - jede Kennung der Liste steht in gremien.json und gehört dort keinem aufgelösten Gremium (fehlt gremien.json, gilt
      jede Kennung als ohne Eintrag);
    - die Kennungen jeder Zeile sind die an den Stationen der Vorlage (gremien.kennungen_der_vorlage; Vorlagen der
      Gebietsdateien, deren Drucksache in der Datenbank nur einmal vorkommt) und die, die gremien.kennungen mit dem
      Datenstand für die Organisationen ihrer Beratungen in der Datenbank ergibt (alle Zeilen, je Drucksache verglichen).
    Fehlt suche.json, nichts zu prüfen (datenschutz meldet sie als fehlend). Befunde und Ausgabe nur mit Zahlen. Liefert
    (befunde, fehlend)."""
    from . import gremien as gr
    from .export import SUCHE_SPALTE_KENNUNGEN as SPALTE
    base = Path(base) if base else config.EXPORT / config.STADT
    befunde, fehlend = [], []
    print(f"\nKennungen der Gremien in suche.json (Freigabe „{gr.FUNKTION}“)")
    pfad = base / "suche.json"
    if not pfad.exists():
        print("suche.json fehlt: nichts zu prüfen")
        return befunde, fehlend
    doc = json.loads(pfad.read_text())
    doc = doc if isinstance(doc, dict) else {}
    zeilen = [r for r in doc.get("rows") or () if isinstance(r, list)]
    liste = doc.get("gremium_keys")
    if not gr.an():
        n = int(liste is not None) + sum(len(r) > SPALTE for r in zeilen)
        if n:
            befunde.append(f"Suche: Kennungen der Gremien in suche.json, obwohl die Freigabe „{gr.FUNKTION}“ aus ist: {n}")
        print("abgeschaltet (config.ZUSATZTHEMEN) – keine Kennungen erwartet")
        return befunde, fehlend
    liste = liste if isinstance(liste, list) else []
    fehler = Counter()
    fehler["Liste gremium_keys fehlt"] = int(not isinstance(doc.get("gremium_keys"), list))
    fehler["Kennungen in gremium_keys, die kein Text sind"] = sum(not isinstance(k, str) for k in liste)
    liste = [k if isinstance(k, str) else repr(k) for k in liste]
    fehler["Kennungen mehrfach in gremium_keys"] = len(liste) - len(set(liste))
    fehler["Zeilen ohne Spalte der Kennungen"] = sum(len(r) <= SPALTE for r in zeilen)

    def kennungen_der_zeile(r):
        v = r[SPALTE] if len(r) > SPALTE else []
        v = v if isinstance(v, list) else [None]
        gueltig = all(isinstance(i, int) and 0 <= i < len(liste) for i in v) and v == sorted(set(v))
        return tuple(liste[i] for i in v) if gueltig else None
    je_zeile = [kennungen_der_zeile(r) for r in zeilen if len(r) > SPALTE]
    fehler["Zeilen mit ungültigem Verweis auf gremium_keys"] = sum(k is None for k in je_zeile)
    datei = base / gr.DATEI
    eintraege = ([e for e in json.loads(datei.read_text()).get("gremien") or () if isinstance(e, dict)]
                 if datei.exists() else [])
    in_datei = {e.get("key") for e in eintraege}
    fehler[f"Kennungen ohne Eintrag in {gr.DATEI}"] = sum(k not in in_datei for k in liste)
    fehler[f"Kennungen aufgelöster Gremien aus {gr.DATEI}"] = sum(
        k in {e.get("key") for e in eintraege if e.get("aufgeloest")} for k in liste)
    # je Drucksache: Kennungen der Zeilen gegen die Stationen und gegen die Organisationen der Beratungen
    ist = {}
    for r in zeilen:
        if len(r) > SPALTE:
            ist.setdefault(r[0], Counter())[kennungen_der_zeile(r)] += 1
    ref_von = dict(db.execute("SELECT id, reference FROM paper"))
    keys = gr.kennungen(gr.organisationen(db), gr.datenstand(db))
    je_vorlage = {pid: set() for pid in ref_von}
    for pid, o in db.execute("SELECT paper_id, organization_id FROM consultation"):
        if pid in je_vorlage and o in keys:
            je_vorlage[pid].add(keys[o])
    soll = {}
    for pid, ks in je_vorlage.items():
        soll.setdefault(ref_von[pid], Counter())[tuple(sorted(ks))] += 1
    fehler["Zeilen, deren Kennungen nicht den Organisationen der Beratungen folgen (gremien.kennungen)"] = sum(
        sum(((ist.get(ref) or Counter()) - (soll.get(ref) or Counter())).values()) for ref in set(ist) | set(soll))
    einmal = Counter(ref_von.values())
    stationen_je = {p.get("reference"): tuple(gr.kennungen_der_vorlage(p)) for p in _gebietsvorlagen(base) or ()
                    if einmal[p.get("reference")] == 1}
    fehler["Zeilen mit anderen Kennungen als an den Stationen der Vorlage"] = sum(
        ist[ref] != Counter([k]) for ref, k in stationen_je.items() if ref in ist)
    for text, n in fehler.items():
        if n:
            befunde.append(f"Suche: {text}: {n}")
    print(f"suche.json: Zeilen {len(zeilen)}, mit Kennung eines Gremiums {sum(bool(k) for k in je_zeile)}, Kennungen in "
          f"gremium_keys {len(liste)}")
    return befunde, fehlend


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
    gelten bei jeder Vorlage, die ihn zeigt (Maske.tops; Offen (8) der Nachprüfung der dritten Korrektur), und mit ihnen
    alle Ergebnisse dieser Vorlage, wie export sie maskiert (Maske.drucksache_ergebnisse: vorher verglich check jeden
    Eintrag mit dem ungekürzten Ergebnis des Punkts der Maske und meldete denselben Text auf einem zweiten Punkt, den
    export dort zu Recht ungekürzt ließ; ein längerer Text, den die Maske stehen lässt, fällt als Hülle weg). Ein Feed,
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
            # Ergebnisse der Vorlage mit der Drucksache wie in export (Maske.drucksache_ergebnisse: alle, sobald einer
            # ihrer Tagesordnungspunkte zur Maske gehört; bei einer Vorlage der Maske jeder ihrer Punkte)
            ergebnisse = db.execute(
                "SELECT a.result, c.agenda_item_id FROM consultation c JOIN agenda_item a ON a.id = c.agenda_item_id "
                "WHERE c.paper_id = ?", (pid,)).fetchall()
            r_erg = m.drucksache_ergebnisse(ref, [a for _, a in ergebnisse])
            kandidaten = [(r, r_erg) for r, _ in ergebnisse]
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
       Tagesordnungspunkt (alle Ergebnisse einer Vorlage mit einem Punkt der Maske, Maske.drucksache_ergebnisse) und
       Sitzungsnamen je Sitzung der Maske (auch bei Vorlagen außerhalb, _sitzungen für zeit.json
       und termine.ics), ein unlesbarer Feed als Befund, und jede Vorlage ohne Hauskoordinate über Gremium oder
       Vorlagenart ist Ausgangspunkt der Titelmaske (Gegenprobe als Befund, Entscheidung 13.11.2026); seit dem
       19.11.2026 Titel und Gremien in index.json („Aktuell in Köln“, _aktuell; dort auch jedes Feld außerhalb der
       festen Liste export.AKTUELL_FELDER) und, nach der Entscheidung 19.11.2026 (3) (c), der Name jeder Sitzung und
       jedes Gremium aus dem Sitzungsnamen in den Gebietsdateien, zeit.json, termine.ics und index.json
       (Maske.sitzungsname_offen; bei einer Sitzung ohne Vorlage der Maske ein Befund nur mit der Zahl je Datei);
       als Hinweis ohne
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
    # Sitzungen ohne Vorlage der Maske mit einem Namen oder Gremium, das die Maske noch ändern würde: je Datei die Zahl
    # (keine Drucksache; Befund am Ende)
    ohne = {}
    index = lesen("index.json")
    if index is not None:
        offen |= _aktuell(index, db, m, zahl, befunde, ohne)
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
    # Tagesordnungspunkte je Vorlage: Drucksache ihrer Ergebnisse wie in export (Maske.drucksache_ergebnisse; alle
    # Ergebnisse, sobald auf einem ihrer Punkte eine Vorlage der Maske beraten wird, Offen (8))
    tops_je = {}
    for pid, top in db.execute("SELECT paper_id, agenda_item_id FROM consultation WHERE agenda_item_id IS NOT NULL"):
        tops_je.setdefault(pid, []).append(top)
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
            # Ergebnisse einer Vorlage mit einem Tagesordnungspunkt, auf dem eine Vorlage der Maske beraten wird: bei
            # jeder Vorlage, auch außerhalb der Maske (Offen (8); die Ergebnisse in `steps` sind Kopien aus `process`).
            # Name jeder Sitzung (Maske.sitzungsname_offen, wie export; Entscheidung 19.11.2026 (3) (c), vorher nur
            # Sitzungen mit einer Vorlage der Maske, Offen (9)). Befund unter der Drucksache der zeigenden Vorlage
            r_erg = m.drucksache_ergebnisse(p["reference"], tops_je.get(p.get("source_object"), ()))
            bei = [(x.get("result"), r_erg) for k in ("process", "steps") for x in p.get(k) or () if x.get("result")]
            sitzungen = [x.get("meeting") for x in p.get("process") or () if x.get("meeting")]
            zahl["sitzungen"] = zahl.get("sitzungen", 0) + len(sitzungen)
            if any(r and m.offen(t, r) for t, r in bei) or any(m.sitzungsname_offen(t) for t in sitzungen):
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
    offen |= _sitzungen(base, db, m, zahl, ohne)
    offen |= _feeds(base, db, m, zahl, befunde)
    _verstoss(befunde, "Gebietsdateien der Karte", [r for r in auf if not je_ref.get(r)])
    _verstoss_oparl(befunde, "Gebietsdateien der Karte", [r for r in auf_oparl if not je_ref.get(r)])
    if offen:
        befunde.append(f"Datenschutz: Hausnummern in Titeln oder Ortsnamen aus Einwohnerschaft, Bauordnung oder "
                       f"Naturschutz (maske.py): {len(offen)}, z. B. {', '.join(sorted(map(str, offen))[:5])}")
    if any(ohne.values()):
        befunde.append("Datenschutz: Hausnummern in Sitzungsnamen oder Gremien aus dem Sitzungsnamen bei Sitzungen "
                       "ohne Vorlage der Titelmaske (maske.Maske.sitzungsname, Entscheidung 19.11.2026 (3)), Sitzungen "
                       "je Datei: " + ", ".join(f"{k} {v}" for k, v in sorted(ohne.items()) if v))

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
