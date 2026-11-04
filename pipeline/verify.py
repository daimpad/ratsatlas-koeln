"""Verifikation: Stichprobe exportierter Vorlagen gegen die OParl-API der Stadt abgleichen, und
Datenpaket (Zip) mit Exporten, Audit-Protokollen und Lizenzen erzeugen."""
import random
import sqlite3
import zipfile
from pathlib import Path

from . import config, maske
from .export import _meetings, _paper_detail, _write_tsv
from .net import get_json

# Feld im Export → Feld im OParl-Objekt
FIELDS = {"reference": "reference", "name": "name", "date": "date", "paper_type": "paperType"}


def verify(n=50, seed=2026):
    """Lädt n zufällig gewählte Vorlagen (die Hälfte aus dem Pilot-Ortsteil) erneut aus der
    OParl-API und vergleicht Stammdaten, Federführung, Zahl der Beratungen und Ortsangaben."""
    db = sqlite3.connect(config.DB)
    db.row_factory = sqlite3.Row
    rnd = random.Random(seed)
    pilot = [r[0] for r in db.execute(
        "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "WHERE l.ortsteil = ? ORDER BY 1", (config.PILOT_ORTSTEIL,))]
    rest = [r[0] for r in db.execute("SELECT id FROM paper ORDER BY id")]
    ids = rnd.sample(pilot, min(n // 2, len(pilot)))
    ids += rnd.sample([i for i in rest if i not in set(ids)], n - len(ids))
    rows, ok_papers = [], 0
    m = maske.aus_db(db)   # Titel aus der Einwohnerschaft ohne Hausnummer (verglichen wird der volle Titel)
    for pid in ids:
        p = db.execute("SELECT * FROM paper WHERE id = ?", (pid,)).fetchone()
        try:
            src = get_json(pid, tries=3)
        except Exception as exc:
            rows.append([p["reference"], "abruf", "", str(exc), "fehler"])
            continue
        checks = [(f, p[f], src.get(o)) for f, o in FIELDS.items()]
        checks.append(("under_direction_of", p["under_direction_of"], (src.get("underDirectionOf") or [None])[0]))
        n_cons = db.execute("SELECT COUNT(*) FROM consultation WHERE paper_id = ?", (pid,)).fetchone()[0]
        checks.append(("beratungen", n_cons, len(src.get("consultation") or [])))
        a_locs = sorted(r[0] for r in db.execute(
            "SELECT location_id FROM paper_location WHERE paper_id = ? AND stage = 'A' AND method <> 'vererbt'",
            (pid,)))
        checks.append(("orte_stufe_a", ";".join(a_locs), ";".join(sorted(l["id"] for l in src.get("location") or []))))
        all_ok = True
        for field, mine, theirs in checks:
            same = str(mine or "") == str(theirs or "")
            all_ok &= same
            if field == "name":
                mine, theirs = m(mine, p["reference"]), m(theirs, p["reference"])
            rows.append([p["reference"], field, mine, theirs, "ok" if same else "abweichend"])
        ok_papers += all_ok
    db.close()
    _write_tsv(config.EXPORT / "verifikation_oparl.tsv",
               ["drucksache", "feld", "export", "oparl_api", "ergebnis"], rows)
    print(f"Verifikation: {ok_papers} von {len(ids)} Vorlagen stimmen in allen Feldern mit der "
          f"OParl-API überein → {config.EXPORT / 'verifikation_oparl.tsv'}")
    verify_time()


def verify_time(n=20, seed=2026):
    """Zeitleiste: n Vorlagen des Pilot-Ortsteils mit datierten Beratungen. Geprüft werden das
    Datum der Vorlage und die Zahl der Beratungen (erneuter Abruf aus der OParl-API) sowie, ob es
    zu jedem aus OParl-Lite abgeleiteten Beratungsdatum eine Sitzung desselben Gremiums in der
    Sitzungsliste der Stadt gibt."""
    db = sqlite3.connect(config.DB)
    db.row_factory = sqlite3.Row
    ids = [r[0] for r in db.execute(
        "SELECT DISTINCT pl.paper_id FROM paper_location pl JOIN location l ON l.id = pl.location_id "
        "JOIN consultation c ON c.paper_id = pl.paper_id "
        "WHERE l.ortsteil = ? AND c.meeting_id IS NOT NULL ORDER BY 1", (config.PILOT_ORTSTEIL,))]
    ids = random.Random(seed).sample(ids, min(n, len(ids)))
    held = {(m["gremium"], m["date"]) for m in _meetings(db) if not m["cancelled"]}
    rows, ok_papers = [], 0
    for pid in ids:
        p = _paper_detail(db, pid)
        try:
            src = get_json(pid, tries=3)
        except Exception as exc:
            rows.append([p["reference"], "abruf", "", str(exc), "fehler"])
            continue
        dated = [st for st in p["steps"] if st["typ"] in ("beratung", "entscheidung") and st.get("role")]
        checks = [("datum_vorlage", p["date"], src.get("date")),
                  ("beratungen", len(dated), len(src.get("consultation") or []))]
        for st in dated:
            if st.get("date"):
                checks.append((f"sitzung {st['label']}", st["date"],
                               st["date"] if (st["label"], st["date"]) in held else "keine Sitzung"))
        all_ok = True
        for field, mine, theirs in checks:
            same = str(mine or "") == str(theirs or "")
            all_ok &= same
            rows.append([p["reference"], field, mine, theirs, "ok" if same else "abweichend"])
        ok_papers += all_ok
    db.close()
    _write_tsv(config.EXPORT / "verifikation_zeit.tsv",
               ["drucksache", "pruefung", "export", "oparl_api", "ergebnis"], rows)
    print(f"Zeitleiste: {ok_papers} von {len(ids)} Vorlagen ohne Abweichung "
          f"→ {config.EXPORT / 'verifikation_zeit.tsv'}")


PACKAGE_README = """allris-bonn – Datenpaket

Inhalt
- endenich/: Pilot-Ortsteil Endenich – vorlagen.json, vorlagen.geojson, audit_geokodierung.tsv,
  stichprobe_pruefung.tsv (Prüfung von Hand)
- bonn/: ganz Bonn – index.json, ortsteile/<ortsteil>.json, bezirke/<bezirk>.json,
  ohne-ortsbezug/<jahr>.json
- audit_geokodierung_bonn.tsv: Audit aller Ortsbezüge (Stufe, Methode, Treffer, Konfidenz,
  Fundstelle, Prüfstatus)
- endenich/audit_prozess.tsv: Prozessschritte je Vorlage mit Evidenzstatus (belegt, abgeleitet,
  nicht_öffentlich, unklar), Quelle, Fundstelle und Prüfvermerk
- endenich/audit_zeit.tsv: Herkunft jedes Datums der Zeitleiste; abgeleitete Beratungsdaten mit
  Abgleich gegen die Sitzungsliste der Stadt
- bonn/zeit.json: Monatsaggregate je Gebiet und Vorlagenart, Sitzungen, Wahlperioden
- bonn/prozesse.json: typische Wege (Folge der Beratungen) je Vorlagenart
- bonn/vorlagen.geojson: alle verorteten Vorlagen (ein Punkt je Vorlage und Straße)
- bonn/termine.ics: Sitzungskalender (iCalendar); bonn/dcat.jsonld: Beschreibung nach DCAT-AP
- bonn/kontext.json: Kontextdaten je Ortsteil, Stadtbezirk und ganz Bonn (Zensus 2022, Bodenrichtwerte,
  Haltestellen, Kitas, Hitze, Überschwemmungsgebiete, Wahlbeteiligung 2025; abgeleitet, je Kennzahl mit Quelle,
  Lizenz und Stand); audit_kontext.tsv: Umrechnung je Gebiet; audit_wahlbeteiligung.tsv: Schätzung je Stimmbezirk
  und Ortsteil; kontext/STAND.json: Quellen der Ausschnitte
- glossar.json: Ergebnistexte, Evidenzstatus, Stände und Begriffe mit Fundstelle
- (nicht im Paket: Atom-Feeds unter bonn/feeds/ und Daten des Ratsassistenten unter bonn/chat/ auf
  der Seite; sie wiederholen die Gebietsdateien)
- verifikation_oparl.tsv, verifikation_zeit.tsv: Abgleich von Stichproben mit der OParl-API
- prozess/: Bericht zur Exploration der Prozessebene und Stichprobe Endenich
- strassen_bonn.json: Straßenverzeichnis (OSM) mit Ortsteilen je Straße
- geo/hausnummern_bonn.json: Hausnummern je Straße und Ortsteil (Stadt Bonn, CC0, ohne Koordinaten);
  audit_hausnummern.tsv: Wirkung der Regel „strasse+hausnummer“ je Vorlage und Straße;
  hausnummern/stichprobe_hausnummern.tsv (30 Vorgänge zur Prüfung von Hand), vorpruefung_hausnummern.tsv
  (Abgleich mit der Ortsteil-Angabe der Stadt und KI-Vorprüfung, gekennzeichnet)
- audit_volltext.tsv: Orte aus dem Text der Hauptdokumente je Vorlage (Befund, Methode, Ort, Ortsteil,
  Konfidenz, Nennungen; keine Textauszüge); volltext/stichprobe_volltext.tsv (30 Vorgänge zur Prüfung).
  Die Texte selbst sind nicht im Paket.
- geo/objekte_bonn.json: benannte Gebäude und Anlagen in Bonn aus OpenStreetMap (ODbL; Name, Art, Ortsteil,
  Mittelpunkt) für Stufe B (Namen im Titel, audit_objekte_titel.tsv, objekte/stichprobe_objekte.tsv und
  vorpruefung_objekte.tsv) und Stufe C (audit_stufe_c_objekte.tsv: Abgleich mit dem Verzeichnis, nur Namen aus dem Verzeichnis)
- audit_stufe_c.tsv: Gegenprüfung der Orte, die ein Sprachmodell im Text der Hauptdokumente erkannt hat (Stufe C;
  Aktion bestätigt/herabgestuft/neu, Methode, Ort, Ortsteil, Konfidenz, Modell; keine Textauszüge). Übernommen
  werden die Orte erst nach Prüfung einer Stichprobe von Hand.
- bonn/kurzfassungen.tsv (erst nach Freigabe): KI-Kurzfassungen je Drucksache mit Modell, Datum und Kennzeichnung;
  abgeleitet, kein Zitat. Prüfungen: kurzfassungen/vorpruefung_kurzfassungen_v*.tsv (KI-Vorprüfung, gekennzeichnet)
- LICENSE-DATA.md: Quellen und Lizenzen je Datei

Bebauungspläne
- geo/bebauungsplaene_bonn.geojson: Geltungsbereiche der rechtskräftigen Pläne (Stadt Bonn, CC0)
- geo/bebauungsplaene_protokoll.tsv: Änderungen am Planbestand zwischen zwei Abrufen
- bonn/plaene.json: Planregister – je Plannummer aus Vorlagentiteln die Pläne (belegt), Ortsteile und
  die Vorlagen chronologisch mit den im Titel genannten Verfahrensschritten nach BauGB (abgeleitet)
- audit_bebauungsplaene.tsv, endenich/audit_bebauungsplaene.tsv: Zuordnung Vorlage ↔ Plan (Methode
  B3, Treffer, Konfidenz, Fundstelle, zurückgestellte Straßen-Ortsbezüge)

Baustellen
- bonn/baustellen.json: Baustellen der Stadt für die Seite (Adresse ohne Hausnummer, Termine
  unverbindlich) mit möglichen Umsetzungen nur der Konfidenz „hoch“ (vorläufig)
- baustellen_kandidaten.tsv: Audit aller Kandidaten Beschluss ↔ Baustelle mit den Kriterien
  räumlich (≤ 150 m), zeitlich, gleiche Straße, Amt/Thema, Bau-Stichwort, Begründung und Prüfvermerk;
  Konfidenz hoch, mittel, niedrig, „fremd“ für andere Träger
- baustellen/stichprobe_kandidaten.tsv: Stichprobe (30) zur Prüfung von Hand;
  baustellen/vorpruefung_kandidaten.tsv: Vorprüfung durch KI, gekennzeichnet, ersetzt sie nicht
- baustellen_archiv/protokoll.tsv, baustellen_archiv/STAND.json: Ereignisse des täglichen Archivs
  (neu, geändert, entfallen) und letzter Abruf je Feed, falls das Archiv vorlag
- berichte/: Berichte der Phasen 0 bis 5 (Bebauungspläne und Baustellen)

Soll-Modell der Prozessebene
- soll/: Verfahrensmodell und Zuständigkeitsordnung aus „Bonn entscheidet“ (feste Kopie, MIT) mit eigenen
  Ergänzungen und Korrekturen (ergaenzungen.json) und Quelle (QUELLE.md)
- audit_soll.tsv: Verfahren je Vorgang (Stammnummer), Sicherheit, Grund, beratende Gremien Ist und Soll, Passung
- bonn/prozessarten.json: Reiter „Prozesse“: Zahl der Vorgänge und Beispiele je Verfahren (Zuordnung abgeleitet),
  Gremien mit Art, Beratungen, letzter und nächster Sitzung und Abschnitt der Zuständigkeitsordnung; Ämter mit
  Abteilungen, federführenden Vorlagen und beratenden Gremien (Gruppen nach Amtsnummer abgeleitet)
- bonn/soll.json: Verfahren mit Schritten und Rechtsgrundlagen, Fristen, Zuständigkeit für die Seite; je Vorlage
  das Feld soll (Zuordnung abgeleitet; Abweichungen sind Befunde, keine Bewertung; keine Rechtsauskunft)
- soll/stichprobe_soll.tsv: Stichprobe (30 Vorgänge) zur Prüfung von Hand (Zuordnung, Befund, Mitwirkung;
  Spalten pruef_*); soll/vorpruefung_soll.tsv: Vorprüfung durch KI, gekennzeichnet, ersetzt sie nicht
- soll/pruefung/belege_ergaenzungen.tsv: Belege der eigenen Ergänzungen mit Wortlaut der Fundstelle,
  KI-Vorprüfung und Prüfvermerk von Hand
- berichte/soll/: Berichte der Phasen 1 bis 4

Grenzen: Eine Baustelle ist kein Beleg für die Umsetzung eines Beschlusses. Termine sind laut Quelle
unverbindlich; die Historie der Baustellen beginnt mit dem Archiv (19.10.2026). Pläne im Verfahren
sind im Datensatz der Stadt nicht enthalten.

Abgeleitete Angaben (Einreichende, fachliche Zuständigkeit, Ortsbezüge der Stufe B und
„vererbt“) sind in den Feldern method, confidence und evidence gekennzeichnet.
Quellcode und Dokumentation: https://github.com/daimpad/allris-test
"""


def package(target=None, archive=None):
    """Zip-Paket der Ergebnisse unter data/export/allris-bonn-export.zip."""
    target = Path(target or config.EXPORT / "allris-bonn-export.zip")
    archive = Path(archive or config.BAUSTELLEN_ARCHIV)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("allris-bonn/LIESMICH.txt", PACKAGE_README)
        z.write(config.ROOT / "data" / "LICENSE-DATA.md", "allris-bonn/LICENSE-DATA.md")
        z.write(config.STRASSEN, "allris-bonn/strassen_bonn.json")
        for path in sorted(config.EXPORT.rglob("*")):
            if path.is_file() and path.suffix != ".zip" and not {"feeds", "chat"} & set(path.parts):
                z.write(path, "allris-bonn/" + str(path.relative_to(config.EXPORT)))
        for path in sorted((config.ROOT / "prozess").glob("*")):
            if path.suffix in (".md", ".tsv"):
                z.write(path, "allris-bonn/prozess/" + path.name)
        for path in sorted((config.ROOT / "data" / "soll").glob("*")):
            z.write(path, "allris-bonn/soll/" + path.name)
        # Bebauungspläne und Baustellen: Flächen, Protokolle, Berichte
        for name in ("bebauungsplaene_bonn.geojson", "bebauungsplaene_protokoll.tsv", "hausnummern_bonn.json", "objekte_bonn.json"):
            if (config.GEO / name).exists():
                z.write(config.GEO / name, "allris-bonn/geo/" + name)
        for name in ("protokoll.tsv", "STAND.json"):
            if (archive / name).exists():
                z.write(archive / name, "allris-bonn/baustellen_archiv/" + name)
        reports = [config.ROOT / "baustellen" / "phase0" / "BERICHT.md", *sorted((config.ROOT / "baustellen").glob("PHASE*.md"))]
        for path in reports:
            if path.exists():
                z.write(path, "allris-bonn/berichte/" + ("PHASE0.md" if path.name == "BERICHT.md" else path.name))
        # Kontextdaten: Quellen der Ausschnitte und Bericht der Prüfung
        for path in (config.ROOT / "data" / "kontext" / "STAND.json", config.ROOT / "data" / "kontext" / "haltestellen_stand.json", config.ROOT / "kontext" / "phase0" / "BERICHT.md",
                     config.ROOT / "kontext" / "PHASE1.md"):
            if path.exists():
                z.write(path, "allris-bonn/kontext/" + ("PHASE0.md" if path.name == "BERICHT.md" else path.name))
        for path in sorted((config.ROOT / "soll").glob("PHASE*.md")):
            z.write(path, "allris-bonn/berichte/soll/" + path.name)
        for path in sorted((config.ROOT / "soll" / "pruefung").glob("*.tsv")):
            z.write(path, "allris-bonn/soll/pruefung/" + path.name)
    print(f"Datenpaket → {target} ({target.stat().st_size // 1024} KB)")
