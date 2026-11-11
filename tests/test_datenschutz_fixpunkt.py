"""Menge ohne Hauskoordinate als Fixpunkt (Prüfung r19, Runde 19b): eine Funktion (geocode.sperrmenge) für den Aufbau
(build.build) und die Prüfung (check.erlaubnis), abwechselnd über Beziehungen (über- und untergeordnet, relatedPaper)
und dieselbe Drucksache, bis nichts mehr hinzukommt; keine vererbte Hauskoordinate bei gesperrten Vorlagen
(build._inherited), kein genauer Punkt aus OParl-Ortsangaben gesperrter Vorlagen (Stufe A), keine Hauskoordinate neben
einem Titel, den maske.py ohne Hausnummer zeigt (Bauordnung, Naturschutz, Einwohnerschaft), und die Prüfung meldet
OParl-Punkte und Ortsnamen mit Hausnummer. Prüfung r19b: Fixpunkt in linearer Zeit, Straßen, die nur aus der
Ortsangabe einer anderen Vorlage bekannt sind, Ortsangaben ausgelassener Vorlagen und gelöschte Vorlagen. Runde 20:
Titelmaske und Volltextkette (maske.kette) folgen denselben Beziehungen samt relatedPaper über dieselbe Funktion. Erfundene
Vorlagen (tools/testdaten.py und eingefügte Vorlagen in den temporären Pfaden der Fixture `oparl`); keine Anfragen an
die Stadt."""
import importlib.util
import json
import random
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from shapely.geometry import Point

from pipeline import build, chat, check, config, export, geocode, kontext, maske, volltext

ROOT = Path(__file__).resolve().parents[1]
B = "https://example.invalid/oparl"
PUNKT, STRASSE_HNR = "strasse+hausnummer_punkt", "strasse+hausnummer"
EINGABE = "Anregungen und Beschwerden"
OHNE_ORT = "[Testdaten] Ergänzung ohne Ort"
UNBEKANNT = "Erfundener Prüfweg"   # nicht im Straßenverzeichnis (geprüft in _lage)
UNBEKANNT2 = "Erfundener Prüfgartenweg"   # ebenso; Ortsangabe einer erlaubten Vorlage (Prüfung r19b)
# Fälle mit Erlaubnis für Hauskoordinaten (_einfuegen)
ERLAUBT = ("kontrolle", "g2", "g3", "g5", "fs_a", "fs_c", "sk_a")


# --- geocode.sperrmenge -----------------------------------------------------------------------------------------------

def test_sperrmenge_fixpunkt():
    """Abwechselnd Beziehungen und dieselbe Drucksache, bis nichts mehr hinzukommt; der Weg je Vorlage."""
    drucksachen = {"e": "1/2026", "x": "1/2026", "c": "2/2026", "y": "3/2026", "z": "3/2026", "frei": "4/2026",
                   "p": "5/2026"}
    rel = [("x", "c"), ("c", "y"), ("p", "frei2")]
    weg = geocode.sperrmenge({"e"}, rel, drucksachen)
    # e → (Drucksache) x → (Beziehung) c → y → (Drucksache) z; „frei“ und „p“ bleiben erlaubt
    assert weg == {"e": "start", "x": "drucksache", "c": "beziehung", "y": "beziehung", "z": "drucksache"}
    # Beziehungen in beiden Richtungen, auch zu Kennungen ohne Drucksache (ausgelassene Vorlagen)
    assert geocode.sperrmenge({"ohne-nummer"}, [("ohne-nummer", "frei")], drucksachen) == {
        "ohne-nummer": "start", "frei": "beziehung"}
    assert geocode.sperrmenge({"frei2"}, rel, drucksachen) == {"frei2": "start", "p": "beziehung"}
    assert geocode.sperrmenge(set(), rel, drucksachen) == {}
    # ein Generator als Beziehungen (check liest aus der Datenbank) wird nur einmal gelesen
    assert set(geocode.sperrmenge({"e"}, iter(rel), drucksachen)) == {"e", "x", "c", "y", "z"}


def _verbunden(ohne, beziehungen):
    """Bezugsfassung (Stand Runde 19b vor der Prüfung r19b): alle über Beziehungen erreichbaren Vorlagen."""
    nachbarn = {}
    for a, b in beziehungen:
        nachbarn.setdefault(a, set()).add(b)
        nachbarn.setdefault(b, set()).add(a)
    gesehen, offen = set(ohne), list(ohne)
    while offen:
        for n in nachbarn.get(offen.pop(), ()):
            if n not in gesehen:
                gesehen.add(n)
                offen.append(n)
    return gesehen


def _gleiche_drucksache(gesperrt, drucksachen):
    refs = {drucksachen[i] for i in gesperrt if i in drucksachen}
    return {i for i, r in drucksachen.items() if r in refs} - set(gesperrt)


def _sperrmenge_in_runden(start, beziehungen, drucksachen):
    """Bezugsfassung des Fixpunkts in Runden (Runde 19b): je Runde alle Beziehungen, dann dieselbe Drucksache."""
    beziehungen = list(beziehungen)
    weg = dict.fromkeys(start, "start")
    neu = set(weg)
    while neu:
        for i in _verbunden(neu, beziehungen):
            weg.setdefault(i, "beziehung")
        neu = _gleiche_drucksache(weg, drucksachen)
        weg.update(dict.fromkeys(neu, "drucksache"))
    return weg


def test_sperrmenge_wie_runden_und_linear():
    """Prüfung r19b: sperrmenge rechnet in linearer Zeit dieselbe Menge mit denselben Wegen wie der Fixpunkt in Runden
    (zufällige Bestände mit Zyklen, Schleifen, Kennungen ohne Drucksache und Drucksache None) und bleibt bei einer
    langen Kette, die abwechselnd über eine Beziehung und dieselbe Drucksache läuft, schnell (vorher je Wechsel ein
    Durchlauf über alle Vorlagen; Messung der Prüfung: 1600 Glieder neben 135 000 Vorlagen 48 s)."""
    for seed in range(400):
        r = random.Random(seed)
        ids = [f"v{i}" for i in range(r.randint(1, 30))] + ["ohne-nummer"]
        drucksachen = {i: f"{r.randint(0, len(ids) // 2)}/2026" for i in ids[:-1] if r.random() < 0.9}
        if r.random() < 0.2:
            drucksachen[ids[0]] = None
        rel = [(r.choice(ids), r.choice(ids)) for _ in range(r.randint(0, len(ids)))]
        start = set(r.sample(ids, r.randint(0, min(3, len(ids)))))
        assert geocode.sperrmenge(start, rel, drucksachen) == _sperrmenge_in_runden(start, rel, drucksachen), seed
    # Kette k0 –Beziehung– k1 =Drucksache= k2 –Beziehung– k3 … neben 20 000 weiteren Vorlagen
    n = 4000
    drucksachen = {f"h{i}": f"{i}/2020" for i in range(20_000)}
    drucksachen.update({f"k{i}": f"K{(i + 1) // 2}/2026" for i in range(n)})
    rel = [(f"h{i}", f"h{i + 1}") for i in range(0, 20_000, 3)] + [(f"k{i}", f"k{i + 1}") for i in range(0, n - 1, 2)]
    t = time.perf_counter()
    weg = geocode.sperrmenge({"k0"}, rel, drucksachen)
    dauer = time.perf_counter() - t
    assert set(weg) == {f"k{i}" for i in range(n)}
    assert [weg[f"k{i}"] for i in range(5)] == ["start", "beziehung", "drucksache", "beziehung", "drucksache"]
    assert dauer < 2, dauer


# --- Titelmaske und Volltextkette (maske.kette, Runde 20) ------------------------------------------------------------

EINWOHNERANFRAGE = "Einwohneranfrage nach § 39 Abs. 6"
MUSTER = "Musterstraße"   # erfundene Straße für die Maske (strassen=[MUSTER])


def _titel(n):
    return f"[Testdaten] Bank an der {MUSTER} {n}"


# (ID, Drucksache, Vorlagenart, Titel, federführende Organisation) wie in maske.kette
KETTE_VORLAGEN = [
    # relatedPaper von der Eingabe zur Stellungnahme
    ("e1", "2001/2026", EINGABE, "[Testdaten] Eingabe", None),
    ("s1", "2002/2026", "Stellungnahme der Verwaltung", _titel(1), None),
    # relatedPaper von der Stellungnahme zur Einwohneranfrage (andere Richtung)
    ("s2", "2003/2026", "Stellungnahme der Verwaltung", _titel(2), None),
    ("a2", "2004/2026", EINWOHNERANFRAGE, "[Testdaten] Einwohneranfrage", None),
    # gemischt: Eingabe –untergeordnet– m3 =Drucksache= k3 –relatedPaper– r3 –übergeordnet– u3 =Drucksache= d3
    ("e3", "2010/2026", EINGABE, "[Testdaten] Eingabe", None),
    ("m3", "2011/2026", "Mitteilung", _titel(3), None),
    ("k3", "2011/2026", "Mitteilung", _titel(3), None),
    ("r3", "2012/2026", "Beschlussvorlage", _titel(4), None),
    ("u3", "2013/2026", "Beschlussvorlage", _titel(5), None),
    ("d3", "2013/2026", "Beschlussvorlage", _titel(5), None),
    # relatedPaper einer ausgelassenen Vorlage (x4, ohne Drucksachennummer)
    ("s4", "2020/2026", "Mitteilung", _titel(6), None),
    # Bauordnung federführend: Titelmaske ja, Volltextkette nein (wie bisher)
    ("b5", "2030/2026", "Beschlussvorlage", _titel(7), "63 Bauaufsicht"),
    ("n5", "2031/2026", "Mitteilung", _titel(8), None),
    # ohne Verbindung zu einer Eingabe: nie in der Maske
    ("f6", "2040/2026", "Beschlussvorlage", _titel(9), None),
    ("g6", "2041/2026", "Beschlussvorlage", _titel(10), None),
    ("h6", "2042/2026", "Antrag nach § 3 der GeschO des Rates", _titel(11), None),
    ("j6", "2043/2026", "Mitteilung", _titel(12), None),
]
KETTE_REL = [("e3", "m3"), ("u3", "r3"), ("j6", "unbekannt")]
KETTE_RELATED = [("e1", "s1"), ("s2", "a2"), ("k3", "r3"), ("x4", "s4"), ("b5", "n5"), ("g6", "h6")]
NUR_RELATED = {"s1", "s2", "r3", "u3", "d3", "s4", "n5"}


def test_kette_folgt_related_in_beiden_richtungen():
    """Titelmaske: relatedPaper in beiden Richtungen, Ketten aus untergeordnet, relatedPaper und derselben Drucksache,
    ausgelassene Vorlagen als Ausgangspunkt; keine Vorlage ohne Verbindung zu einer Eingabe (auch nicht über eine
    Kennung ohne Vorlage). Volltextkette ohne Bauordnung als Ausgangspunkt. Beides ist Teil der Menge ohne
    Hauskoordinate (geocode.sperrmenge mit denselben Beziehungen)."""
    paare = KETTE_REL + KETTE_RELATED
    weg = maske.kette(KETTE_VORLAGEN, ["x4"], paare)
    erwartet = {"e1", "s1", "s2", "a2", "e3", "m3", "k3", "r3", "u3", "d3", "x4", "s4", "b5", "n5"}
    assert set(weg) == erwartet
    assert (weg["s1"], weg["a2"], weg["k3"], weg["r3"], weg["d3"], weg["x4"]) == (
        "beziehung", "start", "drucksache", "beziehung", "drucksache", "start")
    # ohne relatedPaper (Stand vor Runde 20) fehlen genau die Vorlagen, die nur darüber verbunden sind
    assert erwartet - set(maske.kette(KETTE_VORLAGEN, ["x4"], KETTE_REL)) == NUR_RELATED
    # Volltextkette: ohne Bauordnung und Naturschutz als Ausgangsvorlagen, sonst gleich
    assert set(maske.kette(KETTE_VORLAGEN, ["x4"], paare, privat_auch=False)) == erwartet - {"b5", "n5"}
    # Teil der Menge ohne Hauskoordinate: gleiche Beziehungen, Startmenge nach geocode.punkt_ausschluss
    start = {i for i, ref, art, titel, amt in KETTE_VORLAGEN
             if geocode.punkt_ausschluss({"reference": ref, "paperType": art, "name": titel}, (), amt)} | {"x4"}
    gesperrt = geocode.sperrmenge(start, paare, {i: ref for i, ref, *_ in KETTE_VORLAGEN})
    assert set(weg) <= set(gesperrt)
    # Maske wie in maske.aus_db: Hausnummer nur in den Titeln der Kette ausgeblendet
    refs = {ref for i, ref, *_ in KETTE_VORLAGEN if i in weg}
    m = maske.Maske(refs, strassen=[MUSTER])
    for i, ref, _, titel, _ in KETTE_VORLAGEN:
        if i in ("s1", "s2", "r3", "u3", "s4", "n5"):
            assert m(titel, ref) == f"[Testdaten] Bank an der {MUSTER} {maske.OHNE_NR}", i
        if i in ("f6", "g6", "h6", "j6"):
            assert m(titel, ref) == titel, i


def test_volltextkette_folgt_related():
    """volltext.einwohner_kette auf Rohdaten (build.einlesen): relatedPaper in beiden Richtungen, auch bei ausgelassenen
    Vorlagen; gleich maske.kette ohne Bauordnung mit den Beziehungen aus geocode.beziehungen."""
    felder = {"e1": {"relatedPaper": ["s1"]}, "s2": {"relatedPaper": ["a2"]}, "e3": {"subordinatedPaper": ["m3"]},
              "k3": {"relatedPaper": ["r3"]}, "r3": {"superordinatedPaper": ["u3"]}, "b5": {"relatedPaper": ["n5"]},
              "g6": {"relatedPaper": ["h6"]}, "j6": {"subordinatedPaper": ["unbekannt"]}}
    papers = [{"id": i, "reference": ref, "paperType": art, "name": titel, **felder.get(i, {})}
              for i, ref, art, titel, _ in KETTE_VORLAGEN]
    ausgelassen = [{"id": "x4", "subordinatedPaper": [], "superordinatedPaper": [], "relatedPaper": ["s4"]}]
    rel, related = geocode.beziehungen([*papers, *ausgelassen])
    assert sorted(rel) == sorted(KETTE_REL) and sorted(related) == sorted(KETTE_RELATED)
    kette = volltext.einwohner_kette(papers, ausgelassen)
    assert kette == {"e1", "s1", "s2", "a2", "e3", "m3", "k3", "r3", "u3", "d3", "s4"}
    assert kette == volltext.einwohner_kette(papers, ausgelassen, rel + related)
    # ohne relatedPaper (übergebene Paare wie vor Runde 20) fehlen die Vorlagen, die nur darüber verbunden sind
    assert kette - volltext.einwohner_kette(papers, ausgelassen, rel) == NUR_RELATED - {"n5"}


def _kette_db(mit_related=True):
    """Datenbank mit dem Schema von build und den Fällen aus KETTE_VORLAGEN (maske.aus_db, check.erlaubnis)."""
    db = sqlite3.connect(":memory:")
    db.executescript(build.SCHEMA)
    db.execute("INSERT INTO organization (id, name, org_type) VALUES ('amt63', '63 Bauaufsicht', 'Verwaltungsbereich')")
    db.executemany("INSERT INTO paper (id, reference, name, paper_type, under_direction_of) VALUES (?,?,?,?,?)",
                   [(i, ref, titel, art, "amt63" if amt else None) for i, ref, art, titel, amt in KETTE_VORLAGEN])
    db.executemany("INSERT INTO paper_relation (parent_id, child_id) VALUES (?,?)", KETTE_REL)
    db.executemany("INSERT INTO paper_related (paper_id, related_id) VALUES (?,?)", KETTE_RELATED)
    db.execute("INSERT INTO skipped_paper (id, reason) VALUES ('x4', ?)", (build.OHNE_NUMMER,))
    if not mit_related:   # Datenbank von vor Runde 19b ohne paper_related
        db.execute("DROP TABLE paper_related")
    return db


def test_titelmaske_aus_db_wie_hauskoordinaten():
    """maske.aus_db liest dieselben Beziehungen wie check.erlaubnis (geocode.beziehungen_db, samt paper_related): jede
    Drucksache der Maske ist ohne Erlaubnis für Hauskoordinaten; eine ältere Datenbank ohne paper_related bleibt
    lesbar (dann ohne relatedPaper, in Maske und Prüfung gleich)."""
    db = _kette_db()
    m = maske.aus_db(db, strassen=[MUSTER])
    refs = {ref for i, ref, *_ in KETTE_VORLAGEN if i not in ("f6", "g6", "h6", "j6")}
    assert m.refs == refs
    assert m(_titel(1), "2002/2026") == f"[Testdaten] Bank an der {MUSTER} {maske.OHNE_NR}"
    assert m(_titel(9), "2040/2026") == _titel(9)
    je_ref = check.erlaubnis(db)[1]
    assert not [r for r in m.refs if je_ref[r]]
    assert {r for r, ok in je_ref.items() if ok} >= {"2040/2026", "2041/2026", "2042/2026"}
    alt = _kette_db(mit_related=False)
    nur_related = {ref for i, ref, *_ in KETTE_VORLAGEN if i in NUR_RELATED}
    assert maske.aus_db(alt, strassen=[MUSTER]).refs == refs - nur_related
    assert not [r for r in maske.aus_db(alt).refs if check.erlaubnis(alt)[1][r]]


def test_kette_linear_grosser_bestand():
    """Titelmaske und Volltextkette bleiben bei einem großen Bestand schnell (geocode.sperrmenge, linear): eine Kette aus
    4000 Vorlagen, die abwechselnd über relatedPaper (in beiden Richtungen), untergeordnet und dieselbe Drucksache läuft,
    neben 135 000 weiteren Vorlagen, von denen keine in die Kette gerät."""
    n_frei, n = 135_000, 4000
    papers = [{"id": f"h{i}", "reference": f"{i}/2020", "paperType": "Beschlussvorlage", "name": _titel(i),
               "subordinatedPaper": [f"h{i + 1}"] if i % 3 == 0 else [],
               "relatedPaper": [f"h{i + 2}"] if i % 5 == 0 else []} for i in range(n_frei)]
    kette = [{"id": f"k{i}", "reference": f"K{(i + 1) // 2}/2026", "paperType": "Mitteilung", "name": _titel(i)}
             for i in range(n)]
    kette[0].update(paperType=EINGABE)
    # k0 –relatedPaper→ k1 =Drucksache= k2 ←relatedPaper– k3 =Drucksache= k4 –untergeordnet– k5 =Drucksache= k6 …
    for i in range(0, n - 1, 2):
        art = (i // 2) % 3
        if art == 0:
            kette[i]["relatedPaper"] = [kette[i + 1]["id"]]
        elif art == 1:
            kette[i + 1]["relatedPaper"] = [kette[i]["id"]]
        else:
            kette[i]["subordinatedPaper"] = [kette[i + 1]["id"]]
    alle = papers + kette
    rel, related = geocode.beziehungen(alle)
    vorlagen = [(p["id"], p["reference"], p["paperType"], p["name"], None) for p in alle]
    t = time.perf_counter()
    weg = maske.kette(vorlagen, [], rel + related)
    dauer_maske = time.perf_counter() - t
    t = time.perf_counter()
    voll = volltext.einwohner_kette(alle)
    dauer_voll = time.perf_counter() - t
    assert set(weg) == voll == {f"k{i}" for i in range(n)}
    # gemessen etwa 1 s je Aufruf (davon das meiste für die Ausgangsvorlagen); quadratisch wären es Minuten
    assert dauer_maske < 6 and dauer_voll < 6, (dauer_maske, dauer_voll)


# --- build._inherited ----------------------------------------------------------------------------------------------

class _Gaz:
    """Straßenverzeichnis-Ersatz für _strassenabschnitt und _add_location (erfundene Lage)."""
    streets = {"Musterstraße": [{"ortsteil": "Seeberg", "bezirk": "Chorweiler", "lon": 6.9, "lat": 51.0,
                                 "source": "strassen-koeln"},
                                {"ortsteil": "Heimersdorf", "bezirk": "Chorweiler", "lon": 6.8, "lat": 51.0,
                                 "source": "strassen-koeln"}]}
    ot_by_name = {"Seeberg": {"ortsteil": 601}, "Heimersdorf": {"ortsteil": 602}}


def _vererbung(gesperrt, strasse="Musterstraße"):
    adresse = f"adresse:{strasse} 12a|Seeberg"
    locations = {adresse: (adresse, f"{strasse} 12a", None, None, f"{strasse} 12a", 6.91, 51.01, "Seeberg", 601,
                           "Chorweiler", "adresse", config.QUELLE_ADRESSEN),
                 "ortsteil:Seeberg": ("ortsteil:Seeberg", None, None, None, "Seeberg", 6.9, 51.0, "Seeberg", 601,
                                      "Chorweiler", "ortsteil", config.QUELLE_GEO)}
    papers = [{"id": "p", "reference": "1/2026"}, {"id": "k", "reference": "2/2026", "superordinatedPaper": ["p"]}]
    own = [("p", adresse, "B", PUNKT, "hoch", "Musterstraße", "p"),
           ("p", "ortsteil:Seeberg", "B", "ortsteil_name", "mittel", "Seeberg", "p")]
    rows = build._inherited(papers, {p["id"]: p for p in papers}, own, locations, _Gaz(), gesperrt)
    return {(r[0], locations[r[1]][10], r[1], r[3], r[4]) for r in rows}, rows


def test_vererbung_ohne_hauskoordinate_bei_gesperrter_vorlage():
    """Eine gesperrte Vorlage erbt statt der Hauskoordinate den Straßenabschnitt im Stadtteil der Hausnummer (nicht
    den gleichnamigen Abschnitt in einem anderen Stadtteil); übrige Ortsbezüge erbt sie wie bisher."""
    ebenen, rows = _vererbung({"k"})
    assert ebenen == {("k", "strasse", "strasse:Musterstraße|Seeberg", "vererbt", "mittel"),
                      ("k", "ortsteil", "ortsteil:Seeberg", "vererbt", "mittel")}
    assert any("Straßenabschnitt ohne Hausnummer" in r[5] for r in rows)
    # Gegenprobe: erlaubt → die Hauskoordinate wird vererbt (wie bisher)
    assert ("k", "adresse", "adresse:Musterstraße 12a|Seeberg", "vererbt", "mittel") in _vererbung(set())[0]


def test_vererbung_ohne_strassenabschnitt_entfaellt_der_ort():
    """Kennt das Straßenverzeichnis die Straße im Stadtteil nicht, entfällt dieser Ortsbezug (kein Punkt)."""
    ebenen, _ = _vererbung({"k"}, strasse="Unbekannte Straße")
    assert ebenen == {("k", "ortsteil", "ortsteil:Seeberg", "vererbt", "mittel")}


# --- Straßen, die nur aus der Ortsangabe einer anderen Vorlage bekannt sind (Prüfung r19b) ---------------------------

class _GazStadtteil(_Gaz):
    ot_point = {"Seeberg": Point(6.9001234, 51.0004321)}


def _stadtpunkt(**felder):
    return {**dict(level="strasse", name=UNBEKANNT2, ortsteil="Seeberg", bezirk="Chorweiler", lon=6.91, lat=51.01,
                   method="strasse", confidence="mittel", evidence=UNBEKANNT2, source=config.QUELLE_OPARL), **felder}


def test_stadtteil_statt_stadtpunkt():
    """Eine Straße, die nur aus dem Punkt der Ortsangabe einer anderen Vorlage bekannt ist (Quelle oparl-koeln), gilt
    für eine gesperrte Vorlage nur als Stadtteil des Punkts; ohne Stadtteil entfällt sie; Straßen aus dem
    Verzeichnis und Stadtteile bleiben."""
    verzeichnis = dict(_stadtpunkt(), name="Musterstraße", source="strassen-koeln")
    stadtteil = dict(level="ortsteil", name="Seeberg", ortsteil="Seeberg", bezirk="Chorweiler", lon=6.9, lat=51.0,
                     method="ortsteil_name", confidence="mittel", evidence="Seeberg")
    rows = build._stadtteil_statt_stadtpunkt([_stadtpunkt(), _stadtpunkt(ortsteil=None, name="Ohne Lage"), verzeichnis,
                                              stadtteil], _GazStadtteil())
    assert rows == [dict(_stadtpunkt(), level="ortsteil", name="Seeberg", lon=6.900123, lat=51.000432,
                         source=config.QUELLE_GEO,
                         evidence=f"{UNBEKANNT2} (Straße nur aus einer Ortsangabe der Stadt bekannt: Stadtteil)"),
                    verzeichnis, stadtteil]


def test_volltext_ohne_stadtpunkt_bei_gesperrter_vorlage(tmp_path, monkeypatch):
    """Auch die Verortung aus dem Volltext setzt eine gesperrte Vorlage nicht auf den Punkt aus der Ortsangabe einer
    anderen Vorlage (nur Stadtteil); eine erlaubte Vorlage behält ihn."""
    from pipeline import volltext
    monkeypatch.setattr(config, "EXPORT", tmp_path)
    monkeypatch.setattr(volltext, "load_texts", lambda: {"datei": "erfundener Text"})
    monkeypatch.setattr(volltext, "locate", lambda gaz, text, bv=(): (
        [_stadtpunkt(method="volltext_strasse", teil="Hauptteil", nennungen=2)], {"befund": "verortet", "teil": "Hauptteil"}))
    papers = [{"id": k, "reference": f"{i}/2026", "name": "[Testdaten] Vorlage", "paperType": "Beschlussvorlage",
               "mainFile": {"id": "datei"}} for i, k in enumerate(("gesperrt", "erlaubt"), 1)]
    locations = {}
    rows = build._fulltext(papers, {}, locations, _GazStadtteil(), set(), (), {"gesperrt"})
    orte = {pid: (locations[loc][10], locations[loc][5], locations[loc][6], locations[loc][11]) for pid, loc, *_ in rows}
    assert orte == {"gesperrt": ("ortsteil", 6.900123, 51.000432, config.QUELLE_GEO),
                    "erlaubt": ("strasse", 6.91, 51.01, config.QUELLE_OPARL)}


def test_einlesen_geloeschte_vorlagen_und_ortsangaben():
    """Als gelöscht gemeldete Vorlagen (`deleted`) und Vorlagen ohne Drucksachennummer werden ausgelassen; für den
    Datenschutz bleiben Kennung, Beziehungen und die Kennungen ihrer Ortsangaben (Prüfung r19b)."""
    leer = {"subordinatedPaper": [], "superordinatedPaper": [], "relatedPaper": [], "location": []}
    papers, ausgelassen, _ = build.einlesen([
        {"id": "a", "reference": "1/2026", "location": [{"id": "L1"}]},
        {"id": "s", "reference": None, "subordinatedPaper": ["a"], "location": [{"id": "L2"}, "L3", {"name": "x"}]},
        {"id": "d", "type": "https://schema.oparl.org/1.1/Paper", "deleted": True},
        {"id": "d2", "reference": "2/2026", "deleted": True, "superordinatedPaper": "a"}])
    assert [p["id"] for p in papers] == ["a"]
    assert ausgelassen == [{"id": "s", "grund": build.OHNE_NUMMER, **leer, "subordinatedPaper": ["a"],
                            "location": ["L2", "L3"]},
                           {"id": "d", "grund": build.GELOESCHT, **leer},
                           {"id": "d2", "grund": build.GELOESCHT, **leer, "superordinatedPaper": ["a"]}]


# --- Aufbau, Export, Prüfung --------------------------------------------------------------------------------------

def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def testdaten(oparl, monkeypatch):
    monkeypatch.setattr(config, "HAUSNUMMERN", config.GEO / "hausnummern_koeln.json")
    monkeypatch.setattr(sys, "argv", ["testdaten.py", "--anzahl", "60"])
    _tool("testdaten").main()


def _lage():
    """Straße mit genau einer Lage, drei Hausnummern und ihre Hauskoordinaten (wie in test_vorlagenart_punkt)."""
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    strasse = next(s for s in sorted(hnr) if s.endswith("straße") and len(hnr[s]) == 1)
    lage = next(iter(hnr[strasse]))
    nummern = sorted(hnr[strasse][lage], key=lambda n: (len(n), n))[:3]
    assert UNBEKANNT not in json.loads(config.STRASSEN.read_text())["streets"]
    return strasse, nummern, [tuple(hnr[strasse][lage][n]) for n in nummern]


def _zweite_lage(strasse):
    """Zwei Hauskoordinaten einer anderen Straße mit genau einer Lage (Punkte für Ortsangaben der Stadt)."""
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    zweite = next(s for s in sorted(hnr) if s != strasse and len(hnr[s]) == 1 and len(next(iter(hnr[s].values()))) > 1)
    punkte = next(iter(hnr[zweite].values()))
    assert UNBEKANNT2 not in json.loads(config.STRASSEN.read_text())["streets"]
    return [tuple(punkte[n]) for n in sorted(punkte, key=lambda n: (len(n), n))[:2]]


def _vorlage(key, ref, titel, art="Beschlussvorlage", **felder):
    p = {"id": f"{B}/papers/fp-{key}", "reference": ref, "name": titel, "paperType": art, "date": "2026-10-01",
         "web": "https://example.invalid/vorlage", "modified": "2026-10-01T10:00:00+02:00", "location": [],
         "consultation": [{"id": f"{B}/consultations/fp-{key}", "role": "Entscheidung",
                           "organization": [f"{B}/organizations/rat"], "authoritative": True}]}
    for k, v in felder.items():
        if v is ...:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def _ort(key, strasse, punkt):
    return {"id": f"{B}/locations/fp-{key}", "streetAddress": strasse,
            "geojson": {"type": "Feature", "geometry": {"type": "Point", "coordinates": list(punkt)}}}


def _id(key):
    return f"{B}/papers/fp-{key}"


REFS = {}   # Schlüssel → Drucksache der eingefügten Fälle (_einfuegen)
PUNKTE_R19B = {}


def _einfuegen():
    """Erfundene Fälle; liefert (Straße, Hausnummern, Hauskoordinaten, erwartete Ebene je Schlüssel). Die Punkte der
    Fälle aus der Prüfung r19b (Ortsangaben fs und sk) stehen in PUNKTE_R19B."""
    strasse, nr, xy = _lage()
    xy_fs, xy_sk = _zweite_lage(strasse)
    PUNKTE_R19B.update(fs=xy_fs, sk=xy_sk)
    ort_sk = _ort("sk", "Andere Straße 3", xy_sk)
    titel = f"[Testdaten] Sitzbänke an der {strasse} {nr[0]}"
    amt = {"id": f"{B}/organizations/fp-amt63", "name": "63 Bauaufsicht", "organizationType": "Verwaltungsbereich"}
    orgs = json.loads(config.ORGANIZATIONS.read_text())
    config.ORGANIZATIONS.write_text(json.dumps(orgs + [amt], ensure_ascii=False))
    ort_g1 = _ort("g1", f"{strasse} {nr[1]}", xy[1])
    faelle = [
        ("kontrolle", "1601/2026", titel, {}, "adresse"),
        # x10: Kopie mit derselben Drucksache wie eine Eingabe erbt von ihrer übergeordneten Vorlage
        ("p10", "1610/2026", titel, {"subordinatedPaper": [_id("x10")]}, "strasse"),
        ("e10", "1611/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("x10", "1611/2026", OHNE_ORT, {"superordinatedPaper": [_id("p10")]}, "strasse"),
        # c9: verbunden mit einer Kopie (dieselbe Drucksache wie eine Eingabe)
        ("e9", "1620/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("x9", "1620/2026", OHNE_ORT, {"subordinatedPaper": [_id("c9")]}, None),
        ("c9", "1621/2026", titel, {}, "strasse"),
        # zwei Runden: Eingabe → Drucksache → Beziehung → Drucksache
        ("e20", "1630/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("x20", "1630/2026", OHNE_ORT, {"subordinatedPaper": [_id("y20")]}, None),
        ("y20", "1631/2026", OHNE_ORT, {"paperType": "Mitteilung"}, None),
        ("z20", "1631/2026", titel, {}, "strasse"),
        # relatedPaper in beiden Richtungen, auch bei einer ausgelassenen Eingabe (ohne Drucksachennummer)
        ("e3", "1640/2026", OHNE_ORT, {"paperType": EINGABE, "relatedPaper": [_id("s3")]}, None),
        ("s3", "1641/2026", titel, {"paperType": "Mitteilung"}, "strasse"),
        ("s3b", "1642/2026", titel, {"paperType": "Mitteilung", "relatedPaper": [_id("e3b")]}, "strasse"),
        ("e3b", "1643/2026", OHNE_ORT, {"paperType": EINGABE}, None),
        ("skip5", None, OHNE_ORT, {"paperType": EINGABE, "reference": ..., "relatedPaper": [_id("s5")]}, None),
        ("s5", "1650/2026", titel, {"paperType": "Mitteilung"}, "strasse"),
        # Titel ohne Hausnummer (maske.py): Bauordnungsamt federführend, „Einwohner“ im Titel
        ("bau", "1660/2026", titel, {"underDirectionOf": [amt["id"]]}, "strasse"),
        ("ew", "1661/2026", f"[Testdaten] Einwohnerversammlung an der {strasse} {nr[0]}", {"paperType": "Mitteilung"},
         "strasse"),
        # OParl-Ortsangabe mit Punkt: Eingabe, eine erlaubte Vorlage mit derselben Ortsangabe, eine erlaubte mit eigener
        ("g1", "1670/2026", OHNE_ORT, {"paperType": EINGABE, "location": [ort_g1]}, "ortsteil"),
        ("g2", "1671/2026", OHNE_ORT, {"location": [ort_g1]}, "ortsteil"),
        ("g3", "1672/2026", OHNE_ORT, {"location": [_ort("g3", f"{strasse} {nr[2]}", xy[2])]}, "strasse"),
        # Straße nur aus der Ortsangabe einer Eingabe bekannt: kein Straßenpunkt für andere Vorlagen
        ("g4", "1673/2026", OHNE_ORT, {"paperType": EINGABE, "location": [_ort("g4", f"{UNBEKANNT} 5", xy[1])]},
         "ortsteil"),
        ("g5", "1674/2026", f"[Testdaten] {UNBEKANNT}: neue Bank", {}, None),
        # vererbter Stadtteil aus der OParl-Ortsangabe der Eingabe g1: kein genauer Punkt, kein Befund
        ("g1k", "1675/2026", OHNE_ORT, {"paperType": "Mitteilung", "superordinatedPaper": [_id("g1")]}, None),
        # Prüfung r19b: Straße nur aus der Ortsangabe einer erlaubten Vorlage bekannt; eine Eingabe, die sie mit
        # Hausnummer nennt, steht nur im Stadtteil des Punkts, eine erlaubte Vorlage weiter auf dem Punkt
        ("fs_a", "1680/2026", OHNE_ORT, {"location": [_ort("fs", f"{UNBEKANNT2} 7", xy_fs)]}, None),
        ("fs_g", "1681/2026", f"[Testdaten] Anregung zum {UNBEKANNT2} 7", {"paperType": EINGABE}, None),
        ("fs_c", "1682/2026", f"[Testdaten] Bank am {UNBEKANNT2} 7", {}, None),
        # Prüfung r19b: ausgelassene Eingabe (ohne Drucksachennummer) teilt ihre Ortsangabe mit einer erlaubten Vorlage
        ("sk_g", None, OHNE_ORT, {"paperType": EINGABE, "reference": ..., "location": [ort_sk]}, None),
        ("sk_a", "1683/2026", OHNE_ORT, {"location": [ort_sk]}, None),
        # Prüfung r19b: von der Stadt gelöschte Vorlage (Löschvermerk) mit verbundener Mitteilung
        ("del_m", "1684/2026", titel, {"paperType": "Mitteilung", "superordinatedPaper": [_id("del")]}, "strasse"),
    ]
    REFS.clear()
    REFS.update({key: ref for key, ref, *_ in faelle})
    REFS["del"] = None
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        for key, ref, t, felder, _ in faelle:
            f.write(json.dumps(_vorlage(key, ref, t, **felder), ensure_ascii=False) + "\n")
        # Löschvermerke: „del“ gibt es nur so, „kontrolle“ auch ohne (dann gilt die Vorlage)
        for key in ("del", "kontrolle"):
            f.write(json.dumps({"id": _id(key), "type": "https://schema.oparl.org/1.1/Paper", "deleted": True}) + "\n")
    return strasse, nr, xy, {key: ebene for key, *_, ebene in faelle}


def _orte(db, key):
    return {r for r in db.execute("SELECT l.level, pl.method, l.lon, l.lat, l.street FROM paper_location pl "
                                  "JOIN location l ON l.id = pl.location_id WHERE pl.paper_id = ?", (_id(key),))}


def _punkte_im_export():
    """(Drucksache, lon, lat) aller Punkte in vorlagen.geojson und den Gebietsdateien."""
    base = config.EXPORT / config.STADT
    out = {(f["properties"]["reference"], *f["geometry"]["coordinates"])
           for f in json.loads((base / "vorlagen.geojson").read_text())["features"]}
    for d in check.GEBIETSDATEIEN:
        for datei in (base / d).glob("*.json"):
            out |= {(p["reference"], x["lon"], x["lat"]) for p in json.loads(datei.read_text())["papers"]
                    for x in p.get("locations") or () if x.get("lon") is not None}
    return out


def test_fixpunkt_aufbau_und_pruefung(testdaten, capsys):
    """Alle Fälle in einem Aufbau: keine Hauskoordinate und kein genauer OParl-Punkt bei gesperrten Vorlagen (in keiner
    Datei), Rückfall auf den Straßenabschnitt bzw. den Stadtteil; Aufbau und check.erlaubnis urteilen gleich, check
    besteht ohne Befund; relatedPaper steht in paper_related (nicht in paper_relation) und im Log von build."""
    strasse, nr, xy, erwartet = _einfuegen()
    build.build()
    aus_build = capsys.readouterr().out
    export.export()
    kontext.write()
    capsys.readouterr()
    check.check()
    aus_check = capsys.readouterr().out
    assert "Alle Prüfungen durchgeführt, keine Befunde." in aus_check
    db = sqlite3.connect(config.DB)
    je_id = check.erlaubnis(db)[0]
    for key, ebene in erwartet.items():
        orte = _orte(db, key)
        if REFS[key] is None:
            continue
        # erlaubt: Kontrolle, g2 (teilt nur die Ortsangabe mit der Eingabe g1, keine Beziehung), g3, g5, fs_a, fs_c,
        # sk_a (teilt nur die Ortsangabe mit einer ausgelassenen Eingabe)
        assert je_id[_id(key)] is (key in ERLAUBT), key
        if ebene == "adresse":
            assert {(lvl, m) for lvl, m, *_ in orte} == {("adresse", PUNKT)}, key
        elif ebene == "strasse" and key != "g3":
            assert orte and {lvl for lvl, *_ in orte} == {"strasse"}, (key, orte)
            assert {m for _, m, *_ in orte} <= {STRASSE_HNR, "vererbt"}, (key, orte)
        elif ebene == "ortsteil":   # OParl-Punkt einer gesperrten Vorlage → Stadtteil (wie subLocality)
            assert {(lvl, m) for lvl, m, *_ in orte} == {("ortsteil", "oparl_sublocality")}, (key, orte)
            assert not any((lon, lat) == xy[1] for _, _, lon, lat, _ in orte), key
    assert _orte(db, "x10") and {m for _, m, *_ in _orte(db, "x10")} == {"vererbt"}
    # erlaubte Vorlage mit eigener OParl-Ortsangabe behält den genauen Punkt; die Straße der gesperrten Ortsangabe
    # (nur dort bekannt) liefert anderen Vorlagen keinen Punkt
    assert {(lvl, m, lon, lat) for lvl, m, lon, lat, _ in _orte(db, "g3")} == {("strasse", "oparl_location", *xy[2])}
    assert not any(s == UNBEKANNT for *_, s in _orte(db, "g5")), _orte(db, "g5")
    # Prüfung r19b: Straße nur aus der Ortsangabe der erlaubten Vorlage fs_a bekannt – fs_a und die erlaubte fs_c auf
    # dem Punkt, die Eingabe fs_g nur im Stadtteil des Punkts
    xy_fs, xy_sk = PUNKTE_R19B["fs"], PUNKTE_R19B["sk"]
    assert {(lvl, m, lon, lat) for lvl, m, lon, lat, _ in _orte(db, "fs_a")} == {("strasse", "oparl_location", *xy_fs)}
    assert {(lvl, m, lon, lat) for lvl, m, lon, lat, _ in _orte(db, "fs_c")} == {("strasse", "strasse", *xy_fs)}
    assert {(lvl, m) for lvl, m, *_ in _orte(db, "fs_g")} == {("ortsteil", "strasse")}, _orte(db, "fs_g")
    assert not any((lon, lat) == xy_fs for _, _, lon, lat, _ in _orte(db, "fs_g"))
    # Prüfung r19b: Ortsangabe einer ausgelassenen Eingabe auch bei der erlaubten Vorlage sk_a nur als Stadtteil
    assert {(lvl, m) for lvl, m, *_ in _orte(db, "sk_a")} == {("ortsteil", "oparl_sublocality")}, _orte(db, "sk_a")
    assert not any((lon, lat) == xy_sk for _, _, lon, lat, _ in _orte(db, "sk_a"))
    assert set(db.execute("SELECT paper_id, location_id FROM skipped_location")) == {(_id("sk_g"), f"{B}/locations/fp-sk")}
    # Prüfung r19b: gelöschte Vorlage in skipped_paper (Startmenge), die verbundene Mitteilung ohne Hauskoordinate; ein
    # Löschvermerk neben derselben Vorlage ohne Vermerk ändert nichts
    ausgelassen = set(db.execute("SELECT id, reason FROM skipped_paper"))
    assert (_id("del"), build.GELOESCHT) in ausgelassen and _id("kontrolle") not in {i for i, _ in ausgelassen}
    assert {(lvl, m) for lvl, m, *_ in _orte(db, "del_m")} == {("strasse", STRASSE_HNR)}, _orte(db, "del_m")
    assert {(lvl, m) for lvl, m, *_ in _orte(db, "g1k")} == {("ortsteil", "vererbt")}, _orte(db, "g1k")
    # relatedPaper: eigene Tabelle, in beiden Richtungen ausgewertet; paper_relation (Export, maske) unverändert
    assert set(db.execute("SELECT paper_id, related_id FROM paper_related")) == {
        (_id("e3"), _id("s3")), (_id("s3b"), _id("e3b")), (_id("skip5"), _id("s5"))}
    assert not db.execute("SELECT COUNT(*) FROM paper_relation WHERE ? IN (parent_id, child_id)",
                          (_id("s3"),)).fetchone()[0]
    db.close()
    assert ("relatedPaper: 2 Vorlagen mit relatedPaper (3 Verweise); ohne Hauskoordinate nur über relatedPaper: "
            "3 Vorlagen\n") in aus_build
    assert "Titel ohne Hausnummer (Einwohnerschaft, Bauordnung, Naturschutz) 2," in aus_build
    assert ("„Einwohner“ im Titel einer erkannten Vorlage (Grund Titel ohne Hausnummer, nicht Bauordnung oder "
            "Naturschutz; Entscheidung offen): 1 Vorlagen; ohne Hauskoordinate nur darüber: 1 Vorlagen\n") in aus_build
    assert "1 Vorlagen als gelöscht gemeldet (OParl deleted) ausgelassen\n" in aus_build
    # Runde 20: Titelmaske folgt relatedPaper (s3, s3b, s5); das Log nennt nur Zahlen
    zeile = next(z for z in aus_build.splitlines() if z.startswith("Titelmaske (maske.py"))
    assert zeile.endswith("; nur über relatedPaper: 3 Vorlagen, davon 3 mit gekürztem Titel"), zeile
    assert strasse not in zeile and "[Testdaten]" not in zeile
    assert "Vorlagen als gelöscht gemeldet (OParl deleted) (beim Aufbau ausgelassen): 1\n" in aus_check
    # keine Hauskoordinate und kein genauer OParl-Punkt einer gesperrten Vorlage in einer Exportdatei (Drucksachen der
    # eingefügten Fälle; die Testdaten nutzen andere Nummern)
    gesperrt = {ref for key, ref in REFS.items() if ref and key not in ERLAUBT}
    punkte = {(r, *p) for r, *p in _punkte_im_export() if r in REFS.values()}
    assert {r for r, *p in punkte if tuple(p) == xy[0]} == {"1601/2026"}
    assert not {r for r, *p in punkte if tuple(p) == xy[1]}
    assert {r for r, *p in punkte if tuple(p) == xy[2]} == {"1672/2026"}
    assert {r for r, *p in punkte if tuple(p) == xy_fs} == {"1680/2026", "1682/2026"}
    assert not {r for r, *p in punkte if tuple(p) == xy_sk}
    geo = [f["properties"] for f in json.loads((config.EXPORT / config.STADT / "vorlagen.geojson").read_text())[
        "features"]]
    assert {p["reference"] for p in geo} >= gesperrt - {"1611/2026", "1620/2026", "1630/2026", "1631/2026",
                                                        "1640/2026", "1643/2026"}   # verortete gesperrte Fälle
    assert not [p for p in geo if p["reference"] in gesperrt and p["method"] in (PUNKT, "oparl_location")]
    # Titel und Ortsname ohne Hausnummer bei Bauordnung und „Einwohner“ im Titel, ebenso bei Vorlagen, die nur über
    # relatedPaper mit einer Eingabe verbunden sind (Runde 20), auch in der Suche; die Kontrolle behält ihre Hausnummer
    nur_related = {"1641/2026", "1642/2026", "1650/2026"}
    geprueft = set()
    for p in geo:
        if p["reference"] in {"1660/2026", "1661/2026"} | nur_related:
            assert f"{strasse} {nr[0]}" not in p["name"] + p["place"], p
            geprueft.add(p["reference"])
    assert geprueft >= nur_related
    suche = {r[0]: r[1] for r in json.loads((config.EXPORT / config.STADT / "suche.json").read_text())["rows"]}
    for ref in nur_related:
        assert suche[ref] == f"[Testdaten] Sitzbänke an der {strasse} {maske.OHNE_NR}", (ref, suche[ref])
    assert suche["1601/2026"] == f"[Testdaten] Sitzbänke an der {strasse} {nr[0]}"


def test_pruefung_meldet_fehler_im_aufbau(testdaten, monkeypatch, capsys):
    """Fehler im Aufbau, die check meldet: der frühere einstufige Ablauf (Beziehungen, dann einmal dieselbe Drucksache),
    relatedPaper nicht ausgewertet, Titel ohne Hausnummer nicht gesperrt."""
    _einfuegen()
    echt = geocode.sperrmenge

    def einstufig(start, beziehungen, drucksachen):   # Fehler: Stand vor Runde 19b
        verbunden = _verbunden(start, beziehungen)
        return dict.fromkeys(verbunden | _gleiche_drucksache(verbunden, drucksachen), "start")

    nur_related = {(_id("e3"), _id("s3")), (_id("s3b"), _id("e3b")), (_id("skip5"), _id("s5"))}
    faelle = [("sperrmenge", einstufig, {"1610/2026", "1621/2026", "1631/2026"}),
              ("sperrmenge", lambda s, b, d: echt(s, [x for x in b if x not in nur_related], d),
               {"1641/2026", "1642/2026", "1650/2026"}),
              ("punkt_ausschluss", lambda p, g=(), amt=None: (lambda r: None if r == "maske" else r)(
                  geocode.punkt_ausschluss(p, g, amt)), {"1660/2026", "1661/2026"})]
    for name, fehler, verstoss in faelle:
        with monkeypatch.context() as mp:
            mp.setattr(build, name, fehler)
            build.build()
        export.export()
        capsys.readouterr()
        db = sqlite3.connect(config.DB)
        erg = check.datenschutz(db)
        db.close()
        b = [x for x in erg["befunde"] if "Hauskoordinate bei Vorlagen ohne Erlaubnis (Datenbank;" in x]
        assert len(b) == 1 and f": {len(verstoss)}, z. B. {', '.join(sorted(verstoss))}" in b[0], (name, erg)
        if name == "punkt_ausschluss":   # Ortsname mit Hausnummer neben dem Titel ohne Hausnummer
            assert any("Titeln oder Ortsnamen" in x and "1660/2026, 1661/2026" in x for x in erg["befunde"]), erg


def test_pruefung_titelmaske_mit_relatedpaper(testdaten, monkeypatch, capsys):
    """Runde 20: check urteilt über die Titel wie der Export mit relatedPaper. Folgt die Maske beim Export nur
    paper_relation (Stand vor Runde 20), meldet check die Hausnummern in den Titeln der Vorlagen, die nur über
    relatedPaper mit einer Eingabe verbunden sind. Urteilt die Prüfung der Hauskoordinaten über den Grund „Titel ohne
    Hausnummer“ anders als die Maske, meldet check die Drucksachen der Maske mit Erlaubnis."""
    _einfuegen()
    build.build()
    with monkeypatch.context() as mp:
        mp.setattr(geocode, "beziehungen_db",
                   lambda db: db.execute("SELECT parent_id, child_id FROM paper_relation").fetchall())
        export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    b = [x for x in erg["befunde"] if "Hausnummern in Titeln oder Ortsnamen" in x]
    assert len(b) == 1 and b[0].endswith(": 3, z. B. 1641/2026, 1642/2026, 1650/2026"), erg["befunde"]
    assert not [x for x in erg["befunde"] if "aber Erlaubnis" in x], erg["befunde"]
    echt = geocode.punkt_ausschluss
    with monkeypatch.context() as mp:   # Fehler: Prüfung ohne den Grund „Titel ohne Hausnummer“
        mp.setattr(geocode, "punkt_ausschluss",
                   lambda p, g=(), amt=None: (lambda r: None if r == "maske" else r)(echt(p, g, amt)))
        erg = check.datenschutz(db)
    db.close()
    b = [x for x in erg["befunde"] if "Titel ohne Hausnummer (maske.py), aber Erlaubnis für Hauskoordinaten" in x]
    assert len(b) == 1 and b[0].endswith(": 2, z. B. 1660/2026, 1661/2026"), erg["befunde"]


def test_pruefung_meldet_stadtpunkt_bei_gesperrter_vorlage(testdaten, monkeypatch, capsys):
    """Prüfung r19b: Setzt der Aufbau eine gesperrte Vorlage auf den Punkt einer Straße, die nur aus der Ortsangabe
    einer anderen Vorlage bekannt ist (Stufe B, Quelle oparl-koeln), meldet check das in Datenbank, vorlagen.geojson
    und Gebietsdateien (vorher nur Ortsangaben der Stufe A)."""
    _einfuegen()
    monkeypatch.setattr(build, "_stadtteil_statt_stadtpunkt", lambda rows, gaz: rows)   # Fehler
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    db.close()
    for wo in ("Datenbank", "vorlagen.geojson", "Gebietsdateien der Karte"):
        assert any("genauer Punkt aus der Ortsangabe der Stadt (OParl)" in x and f"({wo};" in x
                   and x.endswith(": 1, z. B. 1681/2026") for x in erg["befunde"]), (wo, erg["befunde"])


def test_pruefung_meldet_oparl_punkt_und_ortsnamen(testdaten, tmp_path, capsys):
    """Genauer OParl-Punkt bei einer gesperrten Vorlage (Datenbank, vorlagen.geojson, Gebietsdateien) und Ortsname mit
    Hausnummer neben einem Titel ohne Hausnummer (place, locations[].name): check meldet jede Stelle."""
    strasse, nr, xy, _ = _einfuegen()
    build.build()
    export.export()
    capsys.readouterr()
    base = config.EXPORT / config.STADT

    def pruefen(aendern):
        kopie, db_kopie = tmp_path / "exp", tmp_path / "db.sqlite"
        shutil.rmtree(kopie, ignore_errors=True)
        shutil.copytree(base, kopie)
        shutil.copy(config.DB, db_kopie)
        db = sqlite3.connect(db_kopie)
        aendern(db, kopie)
        db.commit()
        erg = check.datenschutz(db, kopie)
        db.close()
        return erg["befunde"]

    assert pruefen(lambda db, k: None) == []

    def db_punkt(db, _):   # Ortsangabe der Eingabe g1 wieder mit genauem Punkt
        db.execute("UPDATE location SET level = 'strasse', lon = ?, lat = ? WHERE id = ?", (*xy[1], f"{B}/locations/fp-g1"))

    b = pruefen(db_punkt)
    assert len(b) == 1 and "genauer Punkt aus der Ortsangabe der Stadt (OParl)" in b[0] and "(Datenbank;" in b[0]
    # g2 (1671/2026) ist erlaubt, ihr Punkt gilt nicht als Verstoß; g1k (1675/2026) erbt die Ortsangabe von g1
    assert b[0].endswith(": 2, z. B. 1670/2026, 1675/2026"), b

    def json_aendern(datei, aendern):
        doc = json.loads(datei.read_text())
        aendern(doc)
        datei.write_text(json.dumps(doc, ensure_ascii=False))

    def geo_methode(db, k):
        json_aendern(k / "vorlagen.geojson", lambda g: [f["properties"].update(method="oparl_location")
                                                        for f in g["features"]
                                                        if f["properties"]["reference"] == "1670/2026"])

    b = pruefen(geo_methode)
    assert len(b) == 1 and "OParl" in b[0] and "(vorlagen.geojson;" in b[0] and b[0].endswith(": 1, z. B. 1670/2026")

    def gebiet(feld, wert, ref):
        def aendern(db, k):
            for datei in k.glob("ortsteile/*.json"):
                json_aendern(datei, lambda d: [x.update({feld: wert}) for p in d["papers"] if p["reference"] == ref
                                               for x in p.get("locations") or ()])
        return aendern

    b = pruefen(gebiet("method", "oparl_location", "1670/2026"))
    assert len(b) == 1 and "OParl" in b[0] and "(Gebietsdateien der Karte;" in b[0], b

    # Prüfung r19b: Ort mit Quelle der Stadt und Koordinate bei einer gesperrten Vorlage, auch ohne Methode
    # „oparl_location“ (Straße nur aus einer Ortsangabe bekannt): fs_g liegt nach dem Aufbau im Stadtteil
    def geo_quelle(db, k):
        json_aendern(k / "vorlagen.geojson", lambda g: [f["properties"].update(location_source=config.QUELLE_OPARL)
                                                        for f in g["features"]
                                                        if f["properties"]["reference"] == "1681/2026"])

    b = pruefen(geo_quelle)
    assert len(b) == 1 and "OParl" in b[0] and "(vorlagen.geojson;" in b[0] and b[0].endswith(": 1, z. B. 1681/2026"), b

    def gebiet_quelle(db, k):
        gebiet("source", config.QUELLE_OPARL, "1681/2026")(db, k)
        gebiet("level", "strasse", "1681/2026")(db, k)

    b = pruefen(gebiet_quelle)
    assert len(b) == 1 and "OParl" in b[0] and "(Gebietsdateien der Karte;" in b[0] and b[0].endswith(
        ": 1, z. B. 1681/2026"), b

    def db_quelle(db, _):   # fs_g wieder auf der Straße, die nur aus der Ortsangabe von fs_a bekannt ist (Stufe B)
        db.execute("INSERT INTO location (id, street, lon, lat, level, source) VALUES ('strasse:fehler', ?, ?, ?, "
                   "'strasse', ?)", (UNBEKANNT2, *PUNKTE_R19B["fs"], config.QUELLE_OPARL))
        db.execute("UPDATE paper_location SET location_id = 'strasse:fehler' WHERE paper_id = ?", (_id("fs_g"),))

    b = pruefen(db_quelle)
    assert len(b) == 1 and "OParl" in b[0] and "(Datenbank;" in b[0] and b[0].endswith(": 1, z. B. 1681/2026"), b

    def db_ausgelassen(db, _):   # Ortsangabe der ausgelassenen Eingabe sk_g wieder mit genauem Punkt
        db.execute("UPDATE location SET level = 'strasse', lon = ?, lat = ? WHERE id = ?",
                   (*PUNKTE_R19B["sk"], f"{B}/locations/fp-sk"))

    b = pruefen(db_ausgelassen)
    assert b == ["Datenschutz: genauer Punkt aus einer Ortsangabe der Stadt (OParl), die auch eine beim Aufbau "
                 "ausgelassene Vorlage nennt (Datenbank; höchstens Stadtteil, CLAUDE.md 2 und 9): 1, z. B. 1683/2026"], b

    def geo_ort(db, k):
        json_aendern(k / "vorlagen.geojson", lambda g: [f["properties"].update(place=f"{strasse} {nr[0]}")
                                                        for f in g["features"]
                                                        if f["properties"]["reference"] == "1660/2026"])

    for aendern in (geo_ort, gebiet("name", f"{strasse} {nr[0]}", "1660/2026")):
        b = pruefen(aendern)
        assert len(b) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b[0] and b[0].endswith(": 1, z. B. 1660/2026")


# --- Prüfung r20: Eingaben in anderer Schreibung in Titelmaske und Volltextkette, Gegenprobe in check, Stichproben ----

# Schreibungen, die die Punktregel über die Vergleichstexte als Eingabe erkennt (geocode._vergleichstexte); vorher
# erkannte chat.aus_einwohnerschaft sie nicht (gelieferte Schreibung), die Titel zeigten ihre Hausnummer
SCHREIBUNGEN = [("Buergerantrag", "[Testdaten] Bank an der Musterstraße 10"),
                ("Bür\u00adgerantrag", "[Testdaten] Bank an der Musterstraße 10"),
                ("Antrag nach Paragraf 24 GO NRW", "[Testdaten] Bank an der Musterstraße 10"),
                ("Mitteilung", "[Testdaten] Ein\u00adgabe: Bank an der Musterstraße 10"),
                ("Mitteilung", "[Testdaten] Buergerantrag zur Musterstraße 10"),
                ("Buergerbrief", "[Testdaten] Bank an der Musterstraße 10"),
                ("Ｂｕｅｒｇｅｒａｎｔｒａｇ", "[Testdaten] Bank an der Musterstraße 10")]


@pytest.mark.parametrize("art, titel", SCHREIBUNGEN)
def test_eingabe_in_anderer_schreibung_in_titelmaske_und_volltextkette(art, titel):
    """Prüfung r20: Titelmaske und Volltextkette (chat.aus_einwohnerschaft) gleichen wie die Punktregel über die
    Vergleichstexte ab; eine Eingabe ohne Hauskoordinate zeigt ihre Hausnummer auch nicht im Titel, und eine Vorlage
    über relatedPaper ebenso nicht."""
    p = {"reference": "10/2026", "paperType": art, "name": titel}
    assert geocode.punkt_ausschluss(p)   # ohne Hauskoordinate („eingabe“, „Buergerbrief“: „vorlagenart“)
    assert chat.aus_einwohnerschaft(art, titel) and maske.titel_ohne_hausnummer(art, titel)
    vorlagen = [("e", "10/2026", art, titel, None), ("s", "11/2026", "Stellungnahme der Verwaltung", titel, None)]
    for privat_auch in (True, False):
        assert set(maske.kette(vorlagen, (), [("s", "e")], privat_auch)) == {"e", "s"}
    assert volltext.einwohner_kette([{"id": "e", "reference": "10/2026", "paperType": art, "name": titel},
                                     {"id": "s", "reference": "11/2026", "paperType": "Mitteilung", "name": titel,
                                      "relatedPaper": ["e"]}]) >= {"e", "s"}


def test_eingabe_und_titelmaske_eine_regel():
    """Jede Vorlage mit Grund „eingabe“ ist Ausgangspunkt der Titelmaske (eine Funktion geocode.eingabe); ohne
    Hinweis auf eine Eingabe bleibt der Titel unverändert (erfundene Titel)."""
    arten = ["Beschlussvorlage", "Mitteilung", "Anregungen und Beschwerden", "ANREGUNGEN UND BESCHWERDEN",
             "Einwohnerfrage", "Einwohneranfrage nach § 39 Abs. 6", "Antrag nach § 3 der GeschO des Rates", None, "",
             "Bürgerbrief", "Petition"]
    titel = ["[Testdaten] Bank an der Musterstraße 10", "[Testdaten] Beschwerde zur Musterstraße 10",
             "[Testdaten] Paragraph 24: Musterstraße 10", "[Testdaten] Neue Bänke", None]
    for art in arten:
        for t in titel:
            if geocode.punkt_ausschluss({"reference": "10/2026", "paperType": art, "name": t}) == "eingabe":
                assert chat.aus_einwohnerschaft(art, t), (art, t)
    assert not chat.aus_einwohnerschaft("Mitteilung", "[Testdaten] Bank an der Musterstraße 10")
    assert not chat.aus_einwohnerschaft("Beschlussvorlage", "[Testdaten] Bürgermeisterin besucht die Musterstraße 10")


def _alt_aus_einwohnerschaft(paper_type, name):
    """chat.aus_einwohnerschaft vor der Prüfung r20 (gelieferte Schreibung)."""
    return bool(paper_type in chat.EINWOHNER or chat.EINWOHNER_TITEL.search(name or "")
                or geocode.EINGABE.search(paper_type or "") or geocode.EINGABE.search(name or ""))


def test_eingabe_in_anderer_schreibung_ende_zu_ende(testdaten, monkeypatch, capsys):
    """Prüfung r20, Ende zu Ende mit erfundenen Vorlagen: „Buergerantrag“, eine Stellungnahme dazu über relatedPaper,
    „Ein\u00adgabe:“ im Titel einer Mitteilung und „Paragraf 24“ in der Art zeigen ihre Hausnummer weder in
    suche.json noch in vorlagen.geojson oder den Gebietsdateien; check meldet nichts. Urteilt die Titelmaske wieder
    nach der gelieferten Schreibung, meldet check die Eingaben ohne Hauskoordinate außerhalb der Maske (Gegenrichtung)."""
    strasse, nr, _, _ = _einfuegen()
    t = f"[Testdaten] Sitzbänke an der {strasse} {nr[0]}"
    faelle = [_vorlage("bu", "1697/2026", t, art="Buergerantrag"),
              _vorlage("bu_s", "1698/2026", t, art="Stellungnahme der Verwaltung", relatedPaper=[_id("bu")]),
              _vorlage("eg", "1701/2026", f"[Testdaten] Ein\u00adgabe: Sitzbänke an der {strasse} {nr[0]}",
                       art="Mitteilung"),
              _vorlage("pa", "1702/2026", t, art="Antrag nach Paragraf 24 GO NRW")]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in faelle)
    build.build()
    export.export()
    capsys.readouterr()
    base, hnr = config.EXPORT / config.STADT, f"{strasse} {nr[0]}"
    refs = {"1697/2026", "1698/2026", "1701/2026", "1702/2026"}
    titel = [r[1] for r in json.loads((base / "suche.json").read_text())["rows"] if r[0] in refs]
    titel += [f["properties"].get(k) for f in json.loads((base / "vorlagen.geojson").read_text())["features"]
              if f["properties"]["reference"] in refs for k in ("name", "place")]
    for d in check.GEBIETSDATEIEN:
        for datei in (base / d).glob("*.json"):
            titel += [p["name"] for p in json.loads(datei.read_text())["papers"] if p["reference"] in refs]
    assert len([x for x in titel if x]) >= 4 and not [x for x in titel if x and hnr in x], titel
    db = sqlite3.connect(config.DB)
    assert refs <= maske.aus_db(db).refs
    erg = check.datenschutz(db)
    assert erg["befunde"] == [], erg["befunde"]
    monkeypatch.setattr(chat, "aus_einwohnerschaft", _alt_aus_einwohnerschaft)   # Fehler: alte Schreibung
    erg = check.datenschutz(db)
    db.close()
    b = [x for x in erg["befunde"] if "Eingabe oder Einwohneranfrage ohne Hauskoordinate" in x]
    assert len(b) == 1 and b[0].endswith(": 3, z. B. 1697/2026, 1701/2026, 1702/2026"), erg["befunde"]


def test_stichprobe_volltext_maskiert_und_geprueft(testdaten, capsys):
    """Prüfung r20: Die Stichprobe Volltext (build._fulltext_sample, im Datenpaket) trug den vollen Titel und die
    gefundenen Orte; die Volltextkette lässt Bauordnung und Naturschutz als Ausgangsvorlagen aus. export blendet die
    Hausnummer in Titel und Orten aus wie in der Suche, check prüft beide Spalten."""
    strasse, nr, _, _ = _einfuegen()
    build.build()
    export.export()
    capsys.readouterr()
    titel = f"[Testdaten] Sitzbänke an der {strasse} {nr[0]}"   # Vorlage „bau“ (1660/2026): Bauordnungsamt
    pfad = config.EXPORT / "volltext" / "stichprobe_volltext.tsv"
    pfad.parent.mkdir(parents=True, exist_ok=True)
    kopf = ["nr", "drucksache", "titel", "link", "orte (Ortsteil)", "konfidenz", "teil",
            "urteil (richtig/falsch/unklar)", "anmerkung"]
    zeilen = [["1", "1660/2026", titel, "", f"{strasse} {nr[0]} (Erfunden)", "hoch", "Hauptteil", "", ""],
              ["2", "1601/2026", titel, "", f"{strasse} {nr[0]} (Erfunden)", "hoch", "Hauptteil", "", ""]]
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, *zeilen]) + "\n", encoding="utf-8")
    db = sqlite3.connect(config.DB)
    befunde = check.datenschutz(db)["befunde"]
    assert len(befunde) == 1 and "Hausnummern in Titeln oder Ortsnamen" in befunde[0] and befunde[0].endswith(
        ": 1, z. B. 1660/2026"), befunde
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, zeilen[0][:4] + ["Erfunden"] + zeilen[0][5:]]) + "\n",
                    encoding="utf-8")
    assert check.datenschutz(db)["befunde"], "nur der Titel"
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, *zeilen]) + "\n", encoding="utf-8")
    export.export_audits()
    neu = [z.split("\t") for z in pfad.read_text(encoding="utf-8").splitlines()]
    assert neu[0] == kopf and neu[2] == zeilen[1]                         # erlaubte Vorlage unverändert
    assert neu[1][1] == "1660/2026" and hnr_aus(neu[1][2], strasse, nr) and hnr_aus(neu[1][4], strasse, nr)
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["untersucht"]["stichprobe_volltext"] == 2


def hnr_aus(text, strasse, nr):
    return f"{strasse} {maske.OHNE_NR}" in text and f"{strasse} {nr[0]}" not in text


# --- Prüfung r20n: Vorlagenarten aus der Einwohnerschaft in anderer Schreibung, Hausnummern in anderen Schreibweisen,
# unabhängige Probe in check -------------------------------------------------------------------------------------------

# Vorlagenarten, die die Punktregel als Vorlage aus der Einwohnerschaft oder von Privatpersonen ausschließt (Grund
# „eingabe“ oder „vorlagenart“), die Titelmaske aber nicht erkannte (Prüfung r20n: Hausnummer im Titel)
ARTEN_R20N = ["Einwohner-Anfrage", "Einwohner*innenanfrage", "Einwohner_innenanfrage", "Bürger*innenantrag",
              "Bürger:innenantrag", "Bürgerinnenantrag", "Bürger-Antrag", "Bürger‑Antrag", "Bürger-\nantrag",
              "Bürgeranfrage", "Bürgerfrage", "Bürgerfragestunde", "Fragen von Einwohnerinnen und Einwohnern",
              "Anfrage von Bürgerinnen und Bürgern", "Vorlage aus der Einwohnerschaft", "Anwohnerantrag",
              "Privatantrag", "Bürgerbrief ", "Bürgerbriefe"]


@pytest.mark.parametrize("art", ARTEN_R20N)
def test_vorlagenart_aus_der_einwohnerschaft_in_titelmaske(art):
    """Prüfung r20n: Jede Vorlagenart, die die Punktregel als Vorlage aus der Einwohnerschaft oder von Privatpersonen
    ausschließt, ist Ausgangspunkt der Titelmaske und der Volltextkette (geocode.art_von_personen, dieselbe Regel wie in
    VORLAGENART_PUNKT), auch mit Bindestrich, Genderform oder Leerraum am Ende; verbundene Vorlagen ebenso."""
    titel = f"[Testdaten] Bank an der {MUSTER} 10"
    p = {"reference": "10/2026", "paperType": art, "name": titel}
    assert geocode.punkt_ausschluss(p) in ("eingabe", "vorlagenart") and geocode.art_von_personen(art)
    assert chat.aus_einwohnerschaft(art, titel) and maske.titel_ohne_hausnummer(art, titel)
    vorlagen = [("e", "10/2026", art, titel, None), ("s", "11/2026", "Stellungnahme der Verwaltung", titel, None)]
    for privat_auch in (True, False):
        assert set(maske.kette(vorlagen, (), [("s", "e")], privat_auch)) == {"e", "s"}
    m = maske.Maske({"10/2026", "11/2026"}, strassen=[MUSTER])
    assert m(titel, "10/2026") == m(titel, "11/2026") == f"[Testdaten] Bank an der {MUSTER} {maske.OHNE_NR}"


@pytest.mark.parametrize("titel", ["[Testdaten] Bürger-Antrag: Bank an der Musterstraße 10",
                                   "[Testdaten] Einwohner*innenanfrage zur Musterstraße 10",
                                   "[Testdaten] Bürgeranfrage zur Musterstraße 10"])
def test_eingabe_im_titel_mit_trennzeichen_und_genderform(titel):
    """Prüfung r20n: geocode.EINGABE erkennt Bürger- und Einwohneranträge und -anfragen auch mit Trennzeichen und in
    Genderform im Titel einer Mitteilung (Punktregel und Titelmaske, eine Funktion)."""
    assert geocode.punkt_ausschluss({"reference": "10/2026", "paperType": "Mitteilung", "name": titel}) == "eingabe"
    assert chat.aus_einwohnerschaft("Mitteilung", titel)


@pytest.mark.parametrize("art, titel", [
    ("Beschlussvorlage", "[Testdaten] Bürgermeisterin besucht die Musterstraße 10"),
    ("Beschlussvorlage", "[Testdaten] Neues Bürgerhaus an der Musterstraße 10"),
    ("Mitteilung", "[Testdaten] Bürgersteig an der Musterstraße 10"),
    ("Beschlussvorlage", "[Testdaten] Bürgerbeteiligung zur Musterstraße 10"),
    ("Dringlichkeitsentscheidung des Oberbürgermeisters", "[Testdaten] Musterstraße 10")])
def test_verwaltungsvorlage_mit_buerger_im_titel_bleibt(art, titel):
    """„Bürgermeister“, „Bürgerhaus“, „Bürgersteig“ und „Bürgerbeteiligung“ machen eine Verwaltungsvorlage nicht zur
    Eingabe (Hauskoordinate erlaubt, Titel unverändert)."""
    assert geocode.punkt_ausschluss({"reference": "10/2026", "paperType": art, "name": titel}) is None
    assert not chat.aus_einwohnerschaft(art, titel) and not geocode.art_von_personen(art)


def test_vergleichstexte_leerraum():
    """Leerraum am Rand fällt weg, mehrfacher Leerraum (auch Zeilenumbruch, geschütztes Leerzeichen) wird ein
    Leerzeichen: „Bürgerbrief “ ist „Bürgerbrief“, „Anregungen  und Beschwerden“ das Gremium für Eingaben."""
    assert geocode._vergleichstexte(" Bürgerbrief \n")[0] == "bürgerbrief"
    assert chat.aus_einwohnerschaft("Bürgerbrief ", None)
    assert geocode.punkt_ausschluss({"reference": "10/2026", "paperType": "Mitteilung", "name": "Musterstraße 10"},
                                    ["Ausschuss für Anregungen  und\nBeschwerden"]) == "gremium"


# Schreibweisen der Hausnummer, die die Maske stehen ließ (Prüfung r20n); erwartet: Titel bis auf die Nummer gleich
SCHREIBWEISEN_HNR = [
    ("Aachener Str.12", "Aachener Str.{o}"), ("Aachener Straße12", "Aachener Straße{o}"),
    ("Aachener Str 12", "Aachener Str {o}"), ("Aachener Straße, Nr. 12", "Aachener Straße, {o}"),
    ("Aachener Straße (Nr. 12)", "Aachener Straße ({o})"), ("Aachener Straße, 12", "Aachener Straße, {o}"),
    ("Aachener Straße, Haus 12", "Aachener Straße, {o}"), ("Aachener Straße #12", "Aachener Straße #{o}"),
    ("Aachener Straße № 12", "Aachener Straße {o}"), ("Aachener Straße ​12", "Aachener Straße ​{o}"),
    ("Aachener Stra­ße 12", "Aachener Stra­ße {o}"), ("Am  Leystapel 3", "Am  Leystapel {o}"),
    ("Am Leystapel 3", "Am Leystapel {o}"), ("Am\nLeystapel 3", "Am\nLeystapel {o}"),
    ("Am Schlossgarten 4", "Am Schlossgarten {o}"), ("Auf dem  Berlich 7a", "Auf dem  Berlich {o}"),
    ("Aachener Straße Nummer 12", "Aachener Straße {o}"), ("AACHENER STRASSE 12-14", "AACHENER STRASSE {o}"),
    ("Mülheimer Straße 3", "Mülheimer Straße {o}"),
    # unverändert wie bisher
    ("Lärm Aachener Straße 1175", "Lärm Aachener Straße {o}"), ("Haus-Nr. 1234", "{o}"),
    ("(neben Haus-Nr.) 68", "(neben {o})"), ("Straße Nr. 5", "Straße {o}")]


@pytest.mark.parametrize("titel, erwartet", SCHREIBWEISEN_HNR)
def test_maske_andere_schreibweisen_der_hausnummer(titel, erwartet):
    """Prüfung r20n: Die Maske gleicht eine angeglichene Fassung des Titels ab (Leerraum, unsichtbare Zeichen, NFKC) und
    ersetzt im gelieferten Titel; zwischen Straße und Nummer auch kein Leerzeichen, Komma, Klammer, „#“, „№“, „Nr.“,
    „Haus“; Straßennamen ohne Endung auch mit „ss“ statt „ß“. Die Prüfung (offen) findet danach nichts mehr, vorher
    schon."""
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "Am Leystapel", "Am Schloßgarten", "Auf dem Berlich",
                                          "Mülheimer Straße"])
    assert m.offen(titel, "1/2026")
    aus = m(titel, "1/2026")
    assert aus == erwartet.format(o=maske.OHNE_NR), aus
    assert not m.offen(aus, "1/2026") and m(titel, "2/2026") == titel


@pytest.mark.parametrize("titel", ["Ausbau L 845", "BAB 57 Lärmschutz", "Aachener Straße, 50931 Köln",
                                   "Bebauungsplan Nr. 6158/03", "Haus 2 der Gesamtschule", "Aachener Straße Nord 12"])
def test_maske_laesst_andere_nummern_stehen(titel):
    """Nummern, die keine Hausnummer hinter einer Straße sind (Straßenname mit Ziffer, Postleitzahl, Bebauungsplan,
    bloßes „Haus“), bleiben stehen, und die Prüfung meldet sie nicht (ein Befund hielte die Veröffentlichung an)."""
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "L 84", "BAB 57"])
    assert m(titel, "1/2026") == titel and not m.offen(titel, "1/2026")


def test_probe_unabhaengig_von_der_maske(monkeypatch):
    """Die Probe in check (Maske.offen) ist unabhängig gebaut: Fehlt der Maske eine Schreibweise (hier: altes Muster mit
    Leerraum zwischen Straße und Nummer, ohne Angleichung), meldet die Probe die stehengebliebene Hausnummer trotzdem."""
    def alt(strassen):
        names = sorted({s for s in strassen if s}, key=len, reverse=True)
        return re.compile(rf"((?:{'|'.join([*map(re.escape, names), maske.SUFFIX])})\s+)(?:nr\.?\s*)?{maske.NR}",
                          re.I)
    monkeypatch.setattr(maske, "_muster", alt)
    monkeypatch.setattr(maske, "_angleichen", lambda t: (t, list(range(len(t)))))
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "Am Schloßgarten"])
    for titel in ("Aachener Straße12", "Aachener Str.12", "Am Schlossgarten 4", "Aachener Straße, Nr. 12",
                  "Ａａｃｈｅｎｅｒ Ｓｔｒａßｅ １２"):
        assert m(titel, "1/2026") == titel                                 # die alte Maske lässt sie stehen
        assert m.offen(titel, "1/2026"), titel                             # die Probe findet sie
        assert not m.rx.search(titel) and not maske.WORT.search(titel)


def test_vorlagenart_und_schreibweise_ende_zu_ende(testdaten, monkeypatch, capsys):
    """Prüfung r20n, Ende zu Ende mit erfundenen Vorlagen: Vorlagenarten aus der Einwohnerschaft in anderer Schreibung
    („Einwohner-Anfrage“, „Anwohnerantrag“, „Bürgerbrief “ mit Leerzeichen, „Bürger‑Antrag“ mit geschütztem
    Bindestrich), eine Stellungnahme dazu über relatedPaper und Hausnummern in anderer Schreibweise („…str.5“,
    „…straße, Nr. 5“, „…straße (Nr. 5)“, „…straße, Haus 5“) erscheinen ohne Hausnummer in suche.json, vorlagen.geojson
    und den Gebietsdateien; check meldet nichts. Fehlt der Titelmaske die Regel nach der Vorlagenart, meldet check die
    Vorlage (Gegenprobe); fehlen der Maske die Schreibweisen, meldet es die unabhängige Probe."""
    strasse, nr, _, _ = _einfuegen()
    kurz = strasse.removesuffix("straße") + "str."
    faelle = [_vorlage("ea", "1801/2026", f"[Testdaten] Sitzbänke an der {kurz}{nr[0]}", art="Einwohner-Anfrage"),
              _vorlage("aw", "1802/2026", f"[Testdaten] Sitzbänke an der {strasse}, Nr. {nr[0]}",
                       art="Anwohnerantrag"),
              _vorlage("bb", "1803/2026", f"[Testdaten] Sitzbänke an der {strasse} (Nr. {nr[0]})", art="Bürgerbrief "),
              _vorlage("bs", "1804/2026", f"[Testdaten] Sitzbänke an der {kurz}{nr[0]}",
                       art="Stellungnahme der Verwaltung", relatedPaper=[_id("aw")]),
              _vorlage("ba", "1805/2026", f"[Testdaten] Sitzbänke an der {strasse}, Haus {nr[0]}",
                       art="Bürger\u2011Antrag")]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in faelle)
    build.build()
    export.export()
    capsys.readouterr()
    base = config.EXPORT / config.STADT
    refs = {"1801/2026", "1802/2026", "1803/2026", "1804/2026", "1805/2026"}

    def titel_im_export():
        titel = [r[1] for r in json.loads((base / "suche.json").read_text())["rows"] if r[0] in refs]
        titel += [f["properties"].get(k) for f in json.loads((base / "vorlagen.geojson").read_text())["features"]
                  if f["properties"]["reference"] in refs for k in ("name", "place")]
        for d in check.GEBIETSDATEIEN:
            for datei in (base / d).glob("*.json"):
                titel += [p["name"] for p in json.loads(datei.read_text())["papers"] if p["reference"] in refs]
        return [x for x in titel if x]

    titel = titel_im_export()
    assert len(titel) >= 5 and not [x for x in titel if nr[0] in x], titel
    assert all(maske.OHNE_NR in x for x in titel if x.startswith("[Testdaten] Sitzbänke")), titel
    db = sqlite3.connect(config.DB)
    assert refs <= maske.aus_db(db).refs
    assert check.datenschutz(db)["befunde"] == []
    with monkeypatch.context() as mp:   # Fehler: Titelmaske ohne die Regel nach der Vorlagenart
        mp.setattr(chat, "art_von_personen", lambda art: False)
        erg = check.datenschutz(db)
    db.close()
    # „Einwohner-Anfrage“ und „Bürger‑Antrag“ erkennt geocode.EINGABE, „Bürgerbrief “ chat.EINWOHNER (ohne Leerraum)
    b = [x for x in erg["befunde"] if "Eingabe oder Einwohneranfrage ohne Hauskoordinate" in x]
    assert len(b) == 1 and b[0].endswith(": 1, z. B. 1802/2026"), erg["befunde"]
    altes_suffix = maske.SUFFIX.replace(r"str(?:\.|(?!" + maske._L + "))", r"str\.")
    assert altes_suffix != maske.SUFFIX

    def altes_muster(strassen):   # Muster von 5decb33: Leerraum zwischen Straße und Nummer, „ß“ wie geliefert
        namen = sorted({s for s in strassen if s}, key=len, reverse=True)
        return re.compile(rf"((?:{'|'.join([*map(re.escape, namen), altes_suffix])})\s+)(?:nr\.?\s*)?{maske.NR}",
                          re.I)

    with monkeypatch.context() as mp:   # Fehler: Maske ohne die neuen Schreibweisen, auch in der Prüfung
        mp.setattr(maske, "_muster", altes_muster)
        export.export()
        capsys.readouterr()
        assert [x for x in titel_im_export() if nr[0] in x]
        db = sqlite3.connect(config.DB)
        erg = check.datenschutz(db)
        db.close()
    b = [x for x in erg["befunde"] if "Hausnummern in Titeln oder Ortsnamen" in x]
    assert len(b) == 1 and b[0].endswith(": 5, z. B. 1801/2026, 1802/2026, 1803/2026, 1804/2026, 1805/2026"), b


# --- Prüfung r20a: „§24GO“ und abgekürzte Paragrafen, Stichprobe Gebäude und Anlagen, jede TSV-Datei mit Titel -------

# Vorlagenarten mit „§ 24“ ohne Leerzeichen bzw. abgekürzt: vorher keine Eingabe (EINGABE verlangte eine Wortgrenze
# hinter der 24, der Vergleichstext kannte „Par.“ und „Paragr.“ nicht), sondern ein erkannter „Antrag“ mit Hauskoordinate
PARAGRAF_24 = [("p24a", "1901/2026", "Antrag nach §24GO NRW"), ("p24b", "1902/2026", "Antrag nach § 24GO NRW"),
               ("p24c", "1903/2026", "Antrag nach Par. 24 GO NRW"), ("p24d", "1904/2026", "Antrag nach Paragr. 24 GO NRW")]


def test_paragraf_24_ohne_leerzeichen_ende_zu_ende(testdaten, capsys):
    """Prüfung r20a, Ende zu Ende mit erfundenen Vorlagen: „Antrag nach §24GO NRW“ (und „§ 24GO“, „Par. 24“,
    „Paragr. 24“) mit Hausnummer im Titel bekommt keine Hauskoordinate (höchstens den Straßenabschnitt, Grund
    „eingabe“), der Titel erscheint in suche.json, vorlagen.geojson und den Gebietsdateien ohne Hausnummer, und check
    meldet nichts (Titelmaske und Hauskoordinaten urteilen gleich). Die erlaubte Kontrollvorlage behält ihre
    Hauskoordinate."""
    alt = re.compile(r"(?i)§\s*24\b")
    for _, _, art in PARAGRAF_24:   # Regel vor der Prüfung r20a: keine Eingabe, Vorlagenart erkannt
        assert not alt.search(art.lower()) and geocode.VORLAGENART_PUNKT.search(art.lower())
    strasse, nr, xy, _ = _einfuegen()
    titel = f"[Testdaten] Sitzbänke an der {strasse} {nr[0]}"
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(_vorlage(k, ref, titel, art=art), ensure_ascii=False) + "\n"
                     for k, ref, art in PARAGRAF_24)
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    assert {o[0] for o in _orte(db, "kontrolle")} == {"adresse"}
    for k, ref, art in PARAGRAF_24:
        orte = _orte(db, k)
        assert {o[0] for o in orte} == {"strasse"} and {o[1] for o in orte} == {STRASSE_HNR}, (art, orte)
    gruende = {}
    _, je_ref, _ = check.erlaubnis(db, gruende=gruende)
    refs = {ref for _, ref, _ in PARAGRAF_24}
    assert {gruende.get(_id(k)) for k, _, _ in PARAGRAF_24} == {"eingabe"}
    assert not any(je_ref[r] for r in refs) and je_ref["1601/2026"]
    assert refs <= maske.aus_db(db).refs
    base = config.EXPORT / config.STADT
    gezeigt = [r[1] for r in json.loads((base / "suche.json").read_text())["rows"] if r[0] in refs]
    gezeigt += [f["properties"].get("name") for f in json.loads((base / "vorlagen.geojson").read_text())["features"]
                if f["properties"]["reference"] in refs]
    for d in check.GEBIETSDATEIEN:
        for datei in (base / d).glob("*.json"):
            gezeigt += [p["name"] for p in json.loads(datei.read_text())["papers"] if p["reference"] in refs]
    assert len(gezeigt) >= 2 * len(refs) and all(hnr_aus(x, strasse, nr) for x in gezeigt), gezeigt
    punkte = {(r, *p) for r, *p in _punkte_im_export()}
    assert ("1601/2026", *xy[0]) in punkte and not {(r, *p) for r in refs for p in xy} & punkte
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg


OBJEKT = "Prüfhaus Erfundenhausen"     # erfundenes Gebäude für das Verzeichnis (config.OBJEKTE)
OBJEKT_WEG = "Erfundener Probeweg"     # nicht im Straßenverzeichnis: die Vorlage bleibt ohne eigenen Ortsbezug


def _objekt_verzeichnis():
    """Erfundenes Verzeichnis der Gebäude und Anlagen in der umgelenkten Datei (conftest: config.OBJEKTE) mit einem
    Gebäude in einem Kölner Stadtteil; liefert den Stadtteil."""
    from shapely.geometry import shape
    f = json.loads(config.ORTSTEILE.read_text())["features"][0]
    pt = shape(f["geometry"]).representative_point()
    ot, bz = f["properties"]["ortsteil_bez"], f["properties"]["bezirk_bez"]
    config.OBJEKTE.write_text(json.dumps({"objekte": {"way/1": {
        "name": OBJEKT, "art": "Gebäude", "ortsteil": ot, "bezirk": bz, "lon": round(pt.x, 6),
        "lat": round(pt.y, 6)}}}, ensure_ascii=False))
    assert OBJEKT_WEG not in json.loads(config.STRASSEN.read_text())["streets"]
    return ot


def _tsv(pfad):
    return [z.split("\t") for z in pfad.read_text(encoding="utf-8").splitlines()]


def test_stichprobe_objekte_maskiert_geprueft_und_im_paket(testdaten, capsys):
    """Prüfung r20a: build._objects_in_titles schreibt die Stichprobe Gebäude und Anlagen
    (objekte/stichprobe_objekte.tsv, im Datenpaket) mit vollem Titel. Sie steht in maske.STICHPROBEN: export blendet die
    Hausnummer einer erfundenen Eingabe in Titel und Orten aus wie in der Suche, eine erlaubte Vorlage bleibt
    unverändert; check prüft beide Spalten, meldet den vollen Titel und eine fehlende Spalte; das Datenpaket
    (paket.write aus data/export) enthält nur den gekürzten Titel."""
    from pipeline import paket
    import zipfile
    ot = _objekt_verzeichnis()
    eingabe = f"[Testdaten] Anregung zum {OBJEKT}, {OBJEKT_WEG} 5"
    erlaubt = f"[Testdaten] Neubau {OBJEKT}, {OBJEKT_WEG} 7"
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.write(json.dumps(_vorlage("ob_e", "1910/2026", eingabe, art=EINGABE), ensure_ascii=False) + "\n")
        f.write(json.dumps(_vorlage("ob_v", "1911/2026", erlaubt), ensure_ascii=False) + "\n")
    build.build()
    pfad = config.EXPORT / "objekte" / "stichprobe_objekte.tsv"
    roh = {z[1]: z for z in _tsv(pfad)[1:]}
    assert roh["1910/2026"][2] == eingabe and roh["1911/2026"][2] == erlaubt   # build: voller Titel
    assert roh["1910/2026"][4] == f"{OBJEKT} ({ot})"
    export.export()
    capsys.readouterr()
    kopf, *zeilen = _tsv(pfad)
    neu = {z[1]: z for z in zeilen}
    assert kopf[1:3] == ["drucksache", "titel"] and set(neu) == {"1910/2026", "1911/2026"}
    assert neu["1910/2026"][2] == f"[Testdaten] Anregung zum {OBJEKT}, {OBJEKT_WEG} {maske.OHNE_NR}"
    assert neu["1911/2026"] == roh["1911/2026"]
    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["untersucht"]["stichprobe_objekte"] == 2, erg
    assert erg["untersucht"]["tabellen_mit_titel"] >= 4   # Audits, Stichprobe je Methode, Stichprobe Gebäude

    # voller Titel bzw. Ort mit Hausnummer in der Stichprobe (etwa aus einem früheren Lauf): Befund
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, list(roh["1910/2026"]), list(roh["1911/2026"])]) + "\n",
                    encoding="utf-8")
    b = check.datenschutz(db)["befunde"]
    assert len(b) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b[0] and b[0].endswith(": 1, z. B. 1910/2026"), b
    ort = list(neu["1910/2026"])
    ort[4] = f"{OBJEKT_WEG} 5 ({ot})"
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, ort]) + "\n", encoding="utf-8")
    b = check.datenschutz(db)["befunde"]
    assert len(b) == 1 and b[0].endswith(": 1, z. B. 1910/2026"), "Spalte der Orte"

    # Stichprobe ohne eine ihrer Spalten: Befund statt stillem Überspringen; export lässt sie unverändert
    ohne = [[w for i, w in enumerate(z) if i != 2] for z in [kopf, list(roh["1910/2026"])]]
    pfad.write_text("\n".join("\t".join(z) for z in ohne) + "\n", encoding="utf-8")
    b = check.datenschutz(db)["befunde"]
    assert b == ["Datenschutz: Stichprobe objekte/stichprobe_objekte.tsv ohne Spalte „titel“ (maske.STICHPROBEN; "
                 "export maskiert sie nicht, sie liegt im Datenpaket)"], b
    export.export_audits()
    assert _tsv(pfad) == ohne and "ohne Spalte titel" in capsys.readouterr().out

    # wieder mit vollem Titel; export maskiert, das Datenpaket enthält nur den gekürzten Titel
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, *roh.values()]) + "\n", encoding="utf-8")
    export.export_audits()
    assert {z[1]: z for z in _tsv(pfad)[1:]} == neu
    assert check.datenschutz(db)["befunde"] == []
    db.close()
    zip_pfad = paket.write(config.BUILD / "paket.zip")
    with zipfile.ZipFile(zip_pfad) as z:
        tsv = {n: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".tsv")}
    assert neu["1910/2026"][2] in tsv[f"{paket.ORDNER}/objekte/stichprobe_objekte.tsv"]
    assert [n for n, text in tsv.items() if f"{OBJEKT_WEG} 5" in text] == []
    assert [n for n, text in tsv.items() if erlaubt in text]   # erlaubte Vorlage mit Hausnummer (Gegenprobe)


def test_jede_tsv_datei_mit_titel_geprueft(testdaten, capsys):
    """Prüfung r20a: check prüft jede TSV-Datei unter data/export (auch in Unterordnern, ohne feste Liste) mit den
    Spalten „drucksache“ und „titel“ gegen die Titelmaske, unabhängig von der Reihenfolge der Spalten; Dateien ohne
    diese Spalten bleiben ungeprüft. Erfundene Datei mit dem vollen Titel einer erfundenen Eingabe."""
    strasse, nr, _, _ = _einfuegen()
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    vorher = check.datenschutz(db)
    assert vorher["befunde"] == []
    titel = f"[Testdaten] Anregung zum {UNBEKANNT2} 7"   # Eingabe fs_g (1681/2026), Titel mit Hausnummer
    assert "1681/2026" in maske.aus_db(db).refs
    datei = config.EXPORT / "zusatz" / "unter" / "stichprobe_erfunden.tsv"
    datei.parent.mkdir(parents=True)
    datei.write_text(f"titel\turteil\tdrucksache\n{titel}\t\t1681/2026\n[Testdaten] {strasse} {nr[0]}\t\t1601/2026\n",
                     encoding="utf-8")
    ohne_spalte = config.EXPORT / "zusatz" / "liste.tsv"   # ohne „titel“: keine Tabelle mit Titel
    ohne_spalte.write_text(f"drucksache\tbezeichnung\n1681/2026\t{titel}\n", encoding="utf-8")
    erg = check.datenschutz(db)
    b = erg["befunde"]
    assert len(b) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b[0] and b[0].endswith(": 1, z. B. 1681/2026"), b
    z, z0 = erg["untersucht"], vorher["untersucht"]
    assert z["tabellen_mit_titel"] == z0["tabellen_mit_titel"] + 1 and z["tabellen_zeilen"] == z0["tabellen_zeilen"] + 2
    datei.write_text(f"titel\turteil\tdrucksache\n{titel.replace(' 7', ' ' + maske.OHNE_NR)}\t\t1681/2026\n",
                     encoding="utf-8")
    assert check.datenschutz(db)["befunde"] == []
    db.close()
