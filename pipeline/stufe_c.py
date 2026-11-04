"""Stufe C: Orte aus dem Volltext mit einem Sprachmodell, gegengeprüft mit den Regeln der Stufe B (CLAUDE.md 5.2).

Für Vorlagen ohne eigenen Ortsbezug aus Titel, Ort der Stadt oder Bebauungsplan (dieselben wie bei volltext.py).
1. Erzeugen (`erzeugen`, nur mit Schlüssel, höchstens MAX_JE_LAUF je Lauf, je Datei-Hash einmal): Das Modell nennt
   aus dem bereinigten Hauptteil je Ort Name, Art und Rolle („gegenstand“ oder „erwähnt“). Gespeichert werden nur
   Namen aus den Verzeichnissen (`verzeichnisnamen`), nie die Wortfolge des Modells und nie Text (Rahmen laut
   Antwort der Stadt Bonn vom 19.10.2026: keine Zitate, keine Auszüge; Code-Prüfung 23.10.2026).
   Ablage: orte_stufe_c.jsonl im Branch `kurzfassungen` (Verzeichnis KURZFASSUNGEN).
2. Gegenprüfen (`pruefen`): Ein Ort zählt nur, wenn sein Name im Hauptteil steht und das Verzeichnis der Stufe B ihn
   einer Straße, einem Ortsteil oder einem Stadtbezirk zuordnet; Gattungsnamen („Markt“) und Listen mit mehr als
   volltext.MAX_ORTSTEILE Ortsteilen zählen nicht.
   - Ort aus Stufe B, vom Modell als Gegenstand bestätigt: Konfidenz „mittel“, wenn die Regel „mittel“ erlaubt.
   - Ort aus Stufe B, vom Modell als nur erwähnt eingestuft: Konfidenz „niedrig“ (nichts wird gelöscht).
   - Neuer Ort, nur vom Modell als Gegenstand genannt: Methode `llm_…`, Konfidenz „niedrig“.
3. Anwenden (`anwenden`, nach `build`, vor `export`): erst wenn FREIGEGEBEN gesetzt ist (nach Prüfung der Stichprobe
   von Hand); bis dahin nur Audit (audit_stufe_c.tsv) und einmalig eine Stichprobe von 30 im Branch.
"""
import csv
import json
import os
import random
import re
import sqlite3
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import config, sprachmodell, volltext
from .geocode import Gazetteer
from .objekte import Objekte

MODELL = os.environ.get("STUFE_C_MODELL",
                        {"anthropic": "claude-sonnet-5-5"}.get(sprachmodell.ANBIETER, "mistral-large-latest"))
MAX_JE_LAUF = int(os.environ.get("STUFE_C_MAX", "50"))   # zuerst klein, um Kosten und Güte zu messen
MAX_ZEICHEN = 16000
MAX_TOKENS = 1200     # erster Lauf (21.10.2026, 600): zwei Antworten ohne lesbares JSON, vermutlich abgeschnitten
MAX_NEUE_OBJEKTE = 4   # mehr neue Gebäude und Anlagen in einer Vorlage gelten als Aufzählung
MAX_VERSUCHE = 3      # gescheiterte Anfragen werden in späteren Läufen wiederholt
FASSUNG = 2           # Fassung der Anweisung; ältere Antworten werden neu angefragt (2: KI-Vorprüfung 21.10.2026)
# Freigabe nach Prüfung der Stichprobe von Hand: False (nur Audit), "herabstufen" (nur Orte, die das Modell als
# „erwähnt“ einstuft, werden auf „niedrig“ gesetzt; nichts wird bestätigt oder neu verortet) oder True (alles).
# Empfehlung (22.10.2026): keine Freigabe; auch Herabstufungen waren in der KI-Vorprüfung nur 19 von 31 richtig
FREIGEGEBEN = False
AKTIONEN = {False: set(), "herabstufen": {"herabgestuft"}, True: {"neu", "bestätigt", "herabgestuft"}}
VERZEICHNIS = Path(os.environ.get("KURZFASSUNGEN", config.ROOT / "_kurzfassungen"))
DATEI = "orte_stufe_c.jsonl"
ARTEN = {"strasse", "ortsteil", "stadtbezirk", "objekt", "kreuzung"}
ROLLEN = {"gegenstand", "erwähnt"}
ZIFFERN = re.compile(r"\s*\d+\s*[a-zA-Z]?\b")

ANWEISUNG = """Du liest Vorlagen des Rates der Stadt Bonn und bestimmst die Orte in Bonn, die darin vorkommen.
Antworte nur mit JSON der Form {"orte": [{"name": "...", "art": "...", "rolle": "...", "ortsteil": "..."}]}.
- name: der Ort, wie er im Text steht (Straße, Platz, Ortsteil, Stadtbezirk, Gebäude oder Anlage), ohne Hausnummer.
- art: "strasse", "ortsteil", "stadtbezirk", "objekt" (Gebäude, Schule, Park, Anlage) oder "kreuzung".
- rolle: "gegenstand", wenn die Vorlage diesen Ort betrifft (dort wird gebaut, geplant, geändert, gefragt);
  "erwähnt", wenn er nur nebenbei vorkommt (Anschrift einer Stelle, Vergleich, Aufzählung, Sitzungsort).
  Betrifft die Vorlage die ganze Stadt (Konzept, Satzung, Haushalt, Personal), sind Orte, die nur als Beispiel oder
  in einer Teilfrage vorkommen, "erwähnt". Eine Einrichtung, die nur als Träger, Absender oder Antragsteller
  vorkommt (ein Museum, ein Verein), ist kein Ort der Vorlage; nenne sie nur, wenn an ihrem Gebäude etwas geschieht.
- ortsteil: Ortsteil, wenn der Text ihn für diesen Ort nennt, sonst "".
Nenne nicht die Stadt Bonn als Ganzes („Bonn“, „Bundesstadt Bonn“, „Stadtgebiet“) und keine Orte außerhalb
Bonns. Nenne keine Personen und keine Hausnummern. Nenne nur Orte, die wörtlich im Text stehen. Gibt es keinen Ort,
antworte {"orte": []}."""


def _anfrage(titel, text, schluessel):
    return sprachmodell.frage(ANWEISUNG, f"Titel: {titel}\n\nText der Vorlage:\n{text}", MODELL, schluessel,
                              max_tokens=MAX_TOKENS, json_antwort=True)


def bereinigen(antwort):
    """Gültige Orte aus der Antwort des Modells: bekannte Art und Rolle, ohne Ziffern (Hausnummern)."""
    d = sprachmodell.json_aus(antwort) or {}
    out = []
    for o in d.get("orte") or []:
        if not isinstance(o, dict):
            continue
        name = ZIFFERN.sub(" ", str(o.get("name") or "")).strip(" ,;")
        art, rolle = str(o.get("art") or "").lower(), str(o.get("rolle") or "").lower()
        if len(name) >= 3 and art in ARTEN and rolle in ROLLEN:
            out.append({"name": name[:80], "art": art, "rolle": rolle,
                        "ortsteil": ZIFFERN.sub(" ", str(o.get("ortsteil") or "")).strip()[:40]})
    return out


def verzeichnisnamen(orte, gaz, objekte=None, text=None):
    """Orte des Modells → nur Namen aus den Verzeichnissen: Straßen, Ortsteile und Stadtbezirke (mehrere in einem Namen
    mit „ / “ verbunden, etwa bei Kreuzungen), Gebäude und Anlagen mit OSM-Kennung. Die Wortfolge des Modells steht
    wörtlich im Text und wird darum nicht aufbewahrt (keine Auszüge). Was nicht wörtlich im Hauptteil steht oder in
    keinem Verzeichnis vorkommt, entfällt; bei Gebäuden ohne Treffer bleibt nur der Befund für das Audit. Ohne text
    entfällt die Prüfung „wörtlich im Hauptteil“ (dann nur Namen aus den Verzeichnissen)."""
    low = re.sub(r"\s+", " ", volltext.clean(text)[0]).lower() if text is not None else None
    out = []
    for o in orte:
        if o.get("verzeichnis"):
            out.append(o)
            continue
        if low is not None and o["name"].lower() not in low:
            continue
        hint = o["ortsteil"] if o["ortsteil"] in gaz.ot_by_name else ""
        neu = {"art": o["art"], "rolle": o["rolle"], "ortsteil": hint, "verzeichnis": True}
        if o["art"] == "objekt" and objekte is not None:
            obj, befund = objekte.finden(o["name"], hint if low is not None and hint.lower() in low else "")
            if obj:
                out.append(dict(neu, name=obj["name"], osm=obj["osm"], befund=befund))
                continue
            neu["befund"] = befund
        rows = gaz.locate(f"{o['name']}, {hint}" if hint else o["name"])
        names = list(dict.fromkeys(r["name"] for r in rows if r["name"] not in volltext.GATTUNG))
        if names or "befund" in neu:
            out.append(dict(neu, name=" / ".join(names)))
    return out


def laden(verzeichnis=None):
    path = Path(verzeichnis or VERZEICHNIS) / DATEI
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["sha"]: r for r in map(json.loads, f)}


def _schreiben(base, have):
    tmp = base / (DATEI + ".tmp")   # erst vollständig schreiben, dann ersetzen (wie kurzfassung._schreiben)
    with open(tmp, "w", encoding="utf-8") as f:
        for sha in sorted(have):
            f.write(json.dumps(have[sha], ensure_ascii=False) + "\n")
    tmp.replace(base / DATEI)


def nur_verzeichnis(verzeichnis=None):
    """Bestand bereinigen: Antworten, deren Orte noch die Wortfolge des Modells tragen (vor dem 23.10.2026), auf Namen
    aus den Verzeichnissen zurückführen. Liefert die Zahl der geänderten Antworten."""
    base = Path(verzeichnis or VERZEICHNIS)
    have = laden(base)
    alt = [r for r in have.values() if any(not o.get("verzeichnis") for o in r["orte"])]
    if not alt:
        return 0
    texte, gaz, objekte = _texte(), Gazetteer(), Objekte()
    for r in alt:
        t = texte.get(r["datei"])
        r["orte"] = verzeichnisnamen(r["orte"], gaz, objekte, t["text"] if t and t["sha"] == r["sha"] else None)
    _schreiben(base, have)
    print(f"Stufe C: {len(alt)} Antworten auf Namen aus den Verzeichnissen zurückgeführt → {base / DATEI}")
    return len(alt)


def kandidaten(db):
    """Drucksache → Vorlage (id, reference, name, paper_type, main_file) ohne eigenen Ortsbezug: alle Ortsbezüge
    stammen aus dem Volltext oder sind vererbt (oder es gibt keinen)."""
    own = {r[0] for r in db.execute("SELECT DISTINCT paper_id FROM paper_location "
                                    "WHERE method NOT LIKE 'volltext_%' AND method <> 'vererbt'")}
    out = {}
    with open(config.PAPERS, encoding="utf-8") as f:
        papers = [json.loads(line) for line in f]
    for p in papers:
        main = (p.get("mainFile") or {}).get("id")
        if p["id"] not in own and main and volltext.allowed(p.get("paperType")) and not volltext.titel_ohne_ort(p.get("name")):
            out.setdefault(p["reference"], {"id": p["id"], "reference": p["reference"], "name": p.get("name"),
                                            "paperType": p.get("paperType"), "main_file": main, "web": p.get("web")})
    return out


def _texte():
    if not config.TEXTE.exists():
        return {}
    with open(config.TEXTE, encoding="utf-8") as f:
        return {r["uri"]: r for r in map(json.loads, f)}


def erzeugen(db, verzeichnis=None, anfrage=_anfrage):
    """Neue Antworten des Modells für Kandidaten mit Text (höchstens MAX_JE_LAUF); ohne Schlüssel nichts."""
    if MAX_JE_LAUF <= 0:   # nicht freigegeben (22.10.2026): weder Texte noch Bestand laden, nichts schreiben
        print("Stufe C: keine neuen Anfragen (STUFE_C_MAX = 0).")
        return
    schluessel = sprachmodell.schluessel()
    if not schluessel:
        print(f"Stufe C: {sprachmodell.SCHLUESSEL[sprachmodell.ANBIETER]} fehlt – nichts angefragt.")
        return
    base = Path(verzeichnis or VERZEICHNIS)
    base.mkdir(parents=True, exist_ok=True)
    have, texte = laden(base), _texte()
    def offen(sha):
        r = have.get(sha)
        if r is None or r.get("fassung", 1) < FASSUNG:
            return True
        return bool(r.get("fehler")) and r.get("versuche", 1) < MAX_VERSUCHE
    todo = [(ref, p) for ref, p in sorted(kandidaten(db).items())
            if p["main_file"] in texte and offen(texte[p["main_file"]]["sha"])][:MAX_JE_LAUF]
    tokens = {"ein": 0, "aus": 0}
    gaz, objekte = (Gazetteer(), Objekte()) if todo else (None, None)
    for ref, p in todo:
        t = texte[p["main_file"]]
        main = re.sub(r"\s+", " ", volltext.clean(t["text"])[0]).strip()[:MAX_ZEICHEN]
        try:
            antwort, usage = anfrage(p["name"] or "", main, schluessel)
            orte, fehler = verzeichnisnamen(bereinigen(antwort), gaz, objekte, t["text"]), None
            if sprachmodell.json_aus(antwort) is None:
                fehler = ("Antwort abgeschnitten" if usage.get("aus", 0) >= MAX_TOKENS
                          else "Antwort ohne lesbares JSON")
        except Exception as e:  # ein Fehler beim Anbieter hält den Lauf nicht auf
            usage, orte, fehler = {}, [], f"Anfrage gescheitert: {type(e).__name__}"
        for k in tokens:
            tokens[k] += usage.get(k, 0)
        alt = have.get(t["sha"]) or {}
        versuche = alt.get("versuche", 0) + 1 if alt.get("fassung", 1) == FASSUNG else 1
        have[t["sha"]] = {"sha": t["sha"], "datei": p["main_file"], "drucksache": ref, "orte": orte, "fehler": fehler,
                          "versuche": versuche, "fassung": FASSUNG, "anbieter": sprachmodell.ANBIETER, "modell": MODELL,
                          "erzeugt": datetime.now(timezone.utc).date().isoformat()}
    _schreiben(base, have)
    sprachmodell.protokoll(base, "stufe-c", MODELL, len(todo), tokens,
                           sum(1 for ref, p in todo if have[texte[p["main_file"]]["sha"]]["fehler"]))
    print(f"Stufe C: {len(todo)} neu ({tokens['ein']} Eingabe-, {tokens['aus']} Ausgabe-Tokens, {MODELL}), "
          f"{len(have)} vorhanden → {base / DATEI}")


def pruefen(gaz, text, orte, b_rows, bv_bezirke=(), objekte=None, objekt_befunde=None):
    """Gegenprüfung eines Ergebnisses. b_rows: Ortsbezüge aus volltext.locate; objekte: Verzeichnis der Gebäude und
    Anlagen (objekte.Objekte). Liefert (Änderungen, Befund): Änderungen als Zeilen mit aktion („bestätigt“,
    „herabgestuft“, „neu“) und den Feldern von Gazetteer.locate. objekt_befunde sammelt (Name im Verzeichnis, Befund)
    je Objekt; der Name des Modells steht wörtlich im Text und wird darum nicht gesammelt (keine Auszüge)."""
    main = volltext.clean(text)[0]
    low = re.sub(r"\s+", " ", main).lower()
    found = []
    for o in orte:
        # Namen aus den Verzeichnissen (verzeichnisnamen) wurden beim Ablegen gegen den Hauptteil geprüft
        verz = o.get("verzeichnis")
        if not verz and o["name"].lower() not in low:
            continue   # nicht wörtlich im Hauptteil: nicht übernommen
        hint = o["ortsteil"] if o["ortsteil"] in gaz.ot_by_name else ""
        if o["art"] == "objekt" and objekte is not None:
            if verz:
                obj = objekte.by_osm.get(o.get("osm"))
                befund = o.get("befund", "") if obj or not o.get("osm") else "nicht mehr im Verzeichnis"
            else:
                # Ortsteil des Modells nur, wenn er im Text steht
                obj, befund = objekte.finden(o["name"], hint if hint.lower() in low else "")
            if objekt_befunde is not None:
                objekt_befunde.append(("", befund) if obj is None else (f"{obj['name']} ({obj['ortsteil']})", befund))
            if obj:
                found.append((o, dict(level="objekt", name=obj["name"], ortsteil=obj["ortsteil"], bezirk=obj["bezirk"],
                                      lon=obj["lon"], lat=obj["lat"], confidence="niedrig", method="objekt",
                                      objektart=obj["art"], osm=obj["osm"])))
                continue
        if not o["name"]:
            continue   # Gebäude ohne Treffer im Verzeichnis: nur der Befund
        rows = gaz.locate(f"{o['name']}, {hint}" if hint else o["name"], bv_bezirke)
        rows = [r for r in rows if r["name"] not in volltext.GATTUNG and (not hint or r["level"] != "ortsteil"
                                                                          or r["name"] == hint)]
        found += [(o, r) for r in rows]
    neu_ot = {r["ortsteil"] for o, r in found if o["rolle"] == "gegenstand" and r["ortsteil"]}
    if len(neu_ot) > volltext.MAX_ORTSTEILE:
        return [], f"Liste ({len(neu_ot)} Ortsteile), nicht verortet"
    # Abgleich über Ebene und Namen: ohne den Zusammenhang des Textes ordnet das Verzeichnis eine Straße womöglich
    # einem anderen Ortsteil zu als Stufe B; es gilt dann der Ortsteil aus Stufe B
    b_by_name = {}
    for b in b_rows:
        b_by_name.setdefault((b["level"], b["name"]), []).append(b)
    out, done = [], set()
    for o, r in found:
        for b in b_by_name.get((r["level"], r["name"]), []):
            key = (b["level"], b["name"], b["ortsteil"])
            if key in done:
                continue
            done.add(key)
            if o["rolle"] == "erwähnt" and b["confidence"] != "niedrig":
                out.append(dict(b, aktion="herabgestuft", confidence="niedrig", art=o["art"]))
            elif o["rolle"] == "gegenstand":
                conf = "mittel" if r["confidence"] == "mittel" else b["confidence"]
                out.append(dict(b, aktion="bestätigt", confidence=conf, art=o["art"]))
        key = (r["level"], r["name"], r["ortsteil"])
        if (r["level"], r["name"]) in b_by_name or key in done:
            continue
        done.add(key)
        # ein Ortsteil, in dem schon ein Ort aus Stufe B liegt, kommt nicht als eigene Fläche hinzu
        if o["rolle"] == "gegenstand" and r["level"] != "stadtbezirk" and not (
                r["level"] == "ortsteil" and r["ortsteil"] in {b["ortsteil"] for b in b_rows}):
            lage = f"; Lage laut OpenStreetMap ({r['objektart']}, {r['osm']})" if r["level"] == "objekt" else ""
            out.append(dict(r, aktion="neu", method=f"llm_{r['level']}", confidence="niedrig", art=o["art"],
                            evidence=f"mit Sprachmodell im Hauptteil des Hauptdokuments erkannt: {r['name']}{lage}"))
    # Aufzählungen von Gebäuden in vielen Ortsteilen (alle Gesamtschulen, Denkmäler der Stadt) sind kein Ort der
    # Vorlage (KI-Vorprüfung der ersten Stichprobe, 21.10.2026)
    neu_obj = [r for r in out if r["aktion"] == "neu" and r["level"] == "objekt"]
    if len(neu_obj) > MAX_NEUE_OBJEKTE:
        out = [r for r in out if r not in neu_obj]
        if not out:
            return [], f"Aufzählung von Gebäuden ({len(neu_obj)}), nicht verortet"
    return out, "geändert" if out else "keine Änderung"


def _ortsbezuege(db, verzeichnis=None):
    """(Kandidaten, Ergebnisse je Drucksache, Texte, Gazetteer) für Prüfung und Anwendung."""
    kand, texte, have = kandidaten(db), _texte(), laden(verzeichnis)
    by_ref = {r["drucksache"]: r for r in have.values()
              if r["drucksache"] in kand and texte.get(kand[r["drucksache"]]["main_file"], {}).get("sha") == r["sha"]}
    return kand, by_ref, texte


def anwenden(verzeichnis=None, db_path=None):
    """Gegenprüfung aller vorhandenen Ergebnisse; Audit; Übernahme in die Datenbank nur nach Freigabe."""
    base = Path(verzeichnis or VERZEICHNIS)
    db = sqlite3.connect(db_path or config.DB)
    kand, by_ref, texte = _ortsbezuege(db, base)
    if not by_ref:
        print("Stufe C: keine Ergebnisse des Sprachmodells – nichts zu prüfen.")
        db.close()
        return
    gaz, objekte = Gazetteer(), Objekte()
    bv = {}
    for pid, bez in db.execute("SELECT c.paper_id, o.name FROM consultation c JOIN organization o "
                               "ON o.id = c.organization_id WHERE o.name LIKE 'Bezirksvertretung %'"):
        bv.setdefault(pid, set()).add(bez.replace("Bezirksvertretung ", ""))
    audit, changes, objekt_audit = [], {}, []
    for ref, res in sorted(by_ref.items()):
        p, text = kand[ref], texte[kand[ref]["main_file"]]["text"]
        b_rows, _ = volltext.locate(gaz, text, bv.get(p["id"], ()))
        obj_befunde = []
        rows, befund = pruefen(gaz, text, res["orte"], b_rows, bv.get(p["id"], ()), objekte, obj_befunde)
        objekt_audit += [(ref, name, b) for name, b in obj_befunde]
        if res.get("fehler"):
            befund = res["fehler"]
        changes[ref] = rows
        if not rows:
            audit.append((ref, befund, "", "", "", "", "", res["modell"]))
        for r in rows:
            audit.append((ref, befund, r["aktion"], r["method"], r["name"], r["ortsteil"] or "", r["confidence"],
                          res["modell"]))
    with open(config.EXPORT / "audit_stufe_c.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["drucksache", "befund", "aktion", "methode", "ort", "ortsteil", "konfidenz", "modell"])
        w.writerows(audit)
    with open(config.EXPORT / "audit_stufe_c_objekte.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["drucksache", "gebäude oder anlage (Verzeichnis)", "befund"])
        w.writerows(objekt_audit)
    n = {a: sum(1 for rs in changes.values() for r in rs if r["aktion"] == a) for a in ("neu", "bestätigt", "herabgestuft")}
    print(f"Stufe C: {len(by_ref)} Vorlagen geprüft; {n} → audit_stufe_c.tsv"
          f"{ {True: '', 'herabstufen': ' (nur Herabstufungen übernommen)'}.get(FREIGEGEBEN, ' (nicht übernommen)')}")
    _stichprobe(base, kand, changes)
    if AKTIONEN[FREIGEGEBEN]:
        _uebernehmen(db, kand, freigegeben(changes), gaz)
    db.close()


def freigegeben(changes, modus=None):
    """Änderungen, die nach der Freigabe (FREIGEGEBEN) übernommen werden."""
    erlaubt = AKTIONEN[FREIGEGEBEN if modus is None else modus]
    return {ref: [r for r in rows if r["aktion"] in erlaubt] for ref, rows in changes.items()}


def _uebernehmen(db, kand, changes, gaz):
    from .build import _add_location
    locations = {}
    for ref, rows in changes.items():
        pid = kand[ref]["id"]
        for r in rows:
            loc_id = _add_location(r, locations, gaz)
            if r["aktion"] == "neu":
                db.execute("INSERT OR IGNORE INTO paper_location VALUES (?,?,?,?,?,?,?)",
                           (pid, loc_id, "C", r["method"], r["confidence"], r["evidence"], pid))
            else:
                note = "; Sprachmodell: " + ("Gegenstand der Vorlage" if r["aktion"] == "bestätigt" else "nur erwähnt")
                db.execute("UPDATE paper_location SET confidence = ?, evidence = evidence || ? "
                           "WHERE paper_id = ? AND location_id = ? AND method LIKE 'volltext_%'",
                           (r["confidence"], note, pid, loc_id))
    db.executemany("INSERT OR IGNORE INTO location VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", locations.values())
    db.commit()


def _stichprobe(base, kand, changes):
    """30 Vorlagen mit Änderung zur Prüfung von Hand (einmalig, im Branch; wird nie überschrieben)."""
    path = base / "stichprobe_stufe_c.tsv"
    refs = sorted(ref for ref, rows in changes.items() if rows)
    if path.exists() or len(refs) < 30:
        return
    pick = sorted(random.Random(20261021).sample(refs, 30))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["nr", "drucksache", "titel", "link", "änderungen (Aktion: Ort, Ortsteil, Konfidenz)",
                    "urteil (richtig/teilweise/falsch)", "anmerkung"])
        for i, ref in enumerate(pick, 1):
            w.writerow([i, ref, kand[ref]["name"], kand[ref]["web"] or "",
                        "; ".join(f"{r['aktion']}: {r['name']}" + (f" ({r['ortsteil']})" if r["ortsteil"] and r["level"] == "strasse" else "")
                                  + f", {r['confidence']}" for r in changes[ref]), "", ""])
    print(f"Stichprobe Stufe C: 30 → {path}")


def schritt():
    """Pipeline-Schritt `stufe-c` (nach build, vor export): neue Anfragen, dann Gegenprüfung und Audit."""
    try:
        nur_verzeichnis()
    except Exception:   # der Bestand bleibt dann unverändert; neue Antworten tragen trotzdem nur Verzeichnisnamen
        traceback.print_exc()
    db = sqlite3.connect(config.DB)
    try:
        erzeugen(db)
    except Exception as e:   # Anbieter oder Netz: Seite wird trotzdem gebaut
        print(f"Stufe C: Erzeugen gescheitert ({type(e).__name__}); weiter mit dem Bestand.")
    db.close()
    try:
        anwenden()
    except Exception:   # ein Fehler hier darf die Seite nicht aufhalten; Stufe C fehlt dann in diesem Lauf
        traceback.print_exc()
        print("Stufe C: Gegenprüfung gescheitert – ohne Stufe C weiter.")
