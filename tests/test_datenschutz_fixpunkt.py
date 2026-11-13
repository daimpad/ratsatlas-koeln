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
            # seit der dritten Korrektur der Prüfung r20a maskiert export auch die Ortsnamen der Vorlagen der Maske:
            # Die Hauskoordinate meldet check (oben), der Ortsname zeigt die Hausnummer nicht mehr
            assert not any("Titeln oder Ortsnamen" in x for x in erg["befunde"]), erg
            geo = json.loads((config.EXPORT / config.STADT / "vorlagen.geojson").read_text())["features"]
            orte = [f["properties"]["place"] for f in geo if f["properties"]["reference"] in {"1660/2026", "1661/2026"}]
            assert orte and all(maske.OHNE_NR in o for o in orte), orte


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
    nach der gelieferten Schreibung, meldet check die Eingaben ohne Hauskoordinate außerhalb der Maske (Gegenrichtung);
    seit der Entscheidung vom 13.11.2026 bleibt „Buergerantrag“ als nicht erkennbare Vorlagenart trotzdem in der Maske
    (maske.ausgang_punktregel), gemeldet werden die beiden übrigen."""
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
    assert len(b) == 1 and b[0].endswith(": 2, z. B. 1701/2026, 1702/2026"), erg["befunde"]
    assert not [x for x in erg["befunde"] if "Gremium" in x], erg["befunde"]


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
    ("(neben Haus-Nr.) 68", "(neben {o})"), ("Straße Nr. 5", "Straße {o}"),
    # Prüfung r20a (Fix): andere Wörter für die Nummer, zweite Nummer einer Liste, Steuerzeichen der Schreibrichtung
    ("Aachener Straße, Hausnummer: 8", "Aachener Straße, {o}"), ("Aachener Straße Hs.-Nr. 12", "Aachener Straße {o}"),
    ("Aachener Straße HNr. 12", "Aachener Straße {o}"), ("Aachener Straße H.-Nr. 12", "Aachener Straße {o}"),
    ("Aachener Straße Haus-Nummer 12", "Aachener Straße {o}"), ("Aachener Straße Nrn. 12-14", "Aachener Straße {o}"),
    ("Aachener Straße 12 bzw. 14", "Aachener Straße {o}"), ("Aachener Straße 12 oder 14", "Aachener Straße {o}"),
    ("Aachener Straße 12 sowie 14", "Aachener Straße {o}"), ("Aachener Straße 12 & 14", "Aachener Straße {o}"),
    ("Aachener Straße 12 + 14", "Aachener Straße {o}"), ("Aachener Straße 12 — 14", "Aachener Straße {o}"),
    ("Aachener Straße 12 − 14", "Aachener Straße {o}"), ("Aachener Straße 12\u201114", "Aachener Straße {o}"),
    ("Aachener Straße 1\u20662", "Aachener Straße {o}"), ("Aachener Straße 12 bzw. 14a, Ende", "Aachener Straße {o}, Ende")]


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
    assert not _pruefend(m).offen(aus, "1/2026") and m(titel, "2/2026") == titel


@pytest.mark.parametrize("titel", ["Ausbau L 845", "BAB 57 Lärmschutz", "Aachener Straße, 50931 Köln",
                                   "Bebauungsplan Nr. 6158/03",
                                   # Prüfung r20a (Fix): Rechtsgrundlage, Beträge und Zeichen, Datum, Uhrzeit
                                   "Musterstraße (§ 24 GO NRW)", "Musterstraße, § 24 GO", "Musterstraße § 24 GO NRW",
                                   "Sperrung der Aachener Straße (§ 24 GO NRW)", "Musterstraße §24 GO",
                                   "Neumarkt (€ 1.000)", "Neumarkt € 1.000",
                                   "Musterweg – „2. Bauabschnitt“", "Musterweg, 12.03.2026", "Musterweg (12.03.2026)",
                                   "Musterweg, 1.000 EUR", "Aachener Straße 12:30 Uhr", "Tagesordnungspunkt 5",
                                   "TOP 5", "Anlage 1"])
def test_maske_laesst_andere_nummern_stehen(titel):
    """Nummern in bekannten Zusammenhängen (Straßenname mit Ziffer, Postleitzahl, Bebauungsplan, Rechtsgrundlage,
    Betrag, Datum, Uhrzeit, Ordnungszahl, „TOP“, „Anlage“) bleiben stehen, und die Prüfung meldet sie nicht (ein Befund
    hielte die Veröffentlichung an). Prüfung r20a (Fix): „§“, „€“, „%“ und „*“ trennen Straße und Nummer weder in der
    Maske noch in der Probe (vorher meldete die Probe „Straße (§ 24 GO NRW)“ mit bis zu vier Trennzeichen, die Maske ließ
    den Titel stehen, und check hielt die Veröffentlichung an); vor „.“ oder „:“ mit Ziffer steht keine Hausnummer
    (Datum, Tausenderpunkt, Uhrzeit). Seit der dritten Korrektur blendet die Maske jede andere Zahl aus („Raum 12“,
    „Haus 2 der Gesamtschule“; test_maske_positivliste)."""
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "L 84", "BAB 57"])
    assert m(titel, "1/2026") == titel and not _pruefend(m).offen(titel, "1/2026")


def test_probe_unabhaengig_von_der_maske(monkeypatch):
    """Die Probe in check (Maske.offen) ist unabhängig gebaut: Fehlt der Maske eine Schreibweise (hier: altes Muster mit
    Leerraum zwischen Straße und Nummer, ohne Angleichung), meldet die Probe die stehengebliebene Hausnummer trotzdem.
    Seit der Prüfung r20a (zweite Korrektur) blendet die Maske aus, was die Probe meldet (Sicherheitsnetz): Die Nummer
    fehlt im Ergebnis, und offen() meldet danach nichts (vorher blieb sie stehen, und check hielt die Veröffentlichung
    an, ohne dass die Maske den Befund beheben konnte)."""
    def alt(strassen):
        names = sorted({s for s in strassen if s}, key=len, reverse=True)
        return re.compile(rf"((?:{'|'.join([*map(re.escape, names), maske.SUFFIX])})\s+)(?:nr\.?\s*)?{maske.NR}",
                          re.I)
    monkeypatch.setattr(maske, "_muster", alt)
    monkeypatch.setattr(maske, "_angleichen", lambda t: (t, list(range(len(t)))))
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "Am Schloßgarten"])
    pruefend = maske.Maske(m.refs, strassen=m.strassen)   # zweite Maske mit denselben (alten) Mustern
    for titel in ("Aachener Straße12", "Aachener Str.12", "Am Schlossgarten 4", "Aachener Straße, Nr. 12",
                  "Ａａｃｈｅｎｅｒ Ｓｔｒａßｅ １２"):
        assert not m.rx.search(titel) and not maske.WORT.search(titel)     # die alten Muster finden sie nicht
        assert m.offen(titel, "1/2026"), titel                             # die Probe findet sie
        aus = m(titel, "1/2026")                                           # und die Maske blendet sie aus
        assert maske.OHNE_NR in aus and not re.search(r"[0-9０-９]", aus) and not pruefend.offen(aus, "1/2026"), aus


def test_probe_findet_zweite_nummer_einer_liste(monkeypatch):
    """Prüfung r20a (Fix): Liest die Maske ein Listenwort nicht (hier: Muster vor dem Fix ohne „bzw.“, „oder“, „&“),
    bleibt nach den Mustern die zweite Nummer hinter der ausgeblendeten stehen; die Probe meldet sie (Ziffernfolge hinter
    „[Hausnummer ausgelassen]“ und einem Listenwort oder -zeichen), und seit der zweiten Korrektur blendet die Maske sie
    darüber aus (Sicherheitsnetz). Mit der Maske nach dem Fix fehlt die Nummer schon nach den Mustern."""
    alt = (rf"\d{{1,4}}(?:\s?[a-zA-Z](?!{maske._L}))?(?:\s*(?:-|–|bis|und|u\.|/|,)\s*\d{{1,4}}"
           rf"(?:\s?[a-zA-Z](?!{maske._L}))?)*(?!\d)")
    neu = maske.Maske({"1/2026"}, strassen=["Aachener Straße"])
    with monkeypatch.context() as mp:
        mp.setattr(maske, "NR", alt)
        m = maske.Maske({"1/2026"}, strassen=["Aachener Straße"])
    for wort in ("bzw.", "oder", "sowie", "&", "+", "—"):
        titel = f"Aachener Straße 12 {wort} 14"
        rest = f"Aachener Straße {maske.OHNE_NR} {wort} 14"   # nach den alten Mustern
        assert m.offen(rest, "1/2026") and not m.rx.search(rest) and not maske.WORT.search(rest), rest
        assert m(titel, "1/2026") == f"Aachener Straße {maske.OHNE_NR} {wort} {maske.OHNE_NR}"
        assert neu(titel, "1/2026") == f"Aachener Straße {maske.OHNE_NR}"
    # keine Liste: eine Zahl mit fünf Stellen oder ein Datum danach meldet die Probe nicht
    for aus in (f"Aachener Straße {maske.OHNE_NR} und 50931 Köln", f"Aachener Straße {maske.OHNE_NR} bis 12.03.2026"):
        assert not neu.offen(aus, "1/2026") and neu(aus, "1/2026") == aus, aus


def test_offen_rechnet_jeden_text_einmal(monkeypatch):
    """Prüfung r20a (Fix, Laufzeit von check): Maske.offen rechnet je (Text, Drucksache) einmal; derselbe Titel in
    Suche, GeoJSON, Gebietsdateien und Tabellen kostet danach nur einen Blick in den Zwischenspeicher."""
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße"])
    gerufen = []
    echt = maske._angleichen
    monkeypatch.setattr(maske, "_angleichen", lambda t: gerufen.append(t) or echt(t))
    for _ in range(3):
        assert m.offen("Aachener Straße 12", "1/2026") and not m.offen("Aachener Straße, 50931 Köln", "1/2026")
    assert len(gerufen) == 2
    assert not m.offen("Aachener Straße 12", "2/2026") and len(gerufen) == 2   # andere Drucksache: nicht betroffen


def test_vorlagenart_und_schreibweise_ende_zu_ende(testdaten, monkeypatch, capsys):
    """Prüfung r20n, Ende zu Ende mit erfundenen Vorlagen: Vorlagenarten aus der Einwohnerschaft in anderer Schreibung
    („Einwohner-Anfrage“, „Anwohnerantrag“, „Bürgerbrief “ mit Leerzeichen, „Bürger‑Antrag“ mit geschütztem
    Bindestrich), eine Stellungnahme dazu über relatedPaper und Hausnummern in anderer Schreibweise („…str.5“,
    „…straße, Nr. 5“, „…straße (Nr. 5)“, „…straße, Haus 5“) erscheinen ohne Hausnummer in suche.json, vorlagen.geojson
    und den Gebietsdateien; check meldet nichts. Fehlen der Titelmaske die Regel nach der Vorlagenart und die
    Punktregel (Entscheidung 13.11.2026), meldet check die Vorlage (Gegenprobe); fehlen der Maske die Schreibweisen,
    meldet es die unabhängige Probe."""
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
        # seit der Entscheidung vom 13.11.2026 hält die Punktregel „Anwohnerantrag“ (Vorlagenart nicht erkennbar)
        # trotzdem in der Maske (maske.ausgang_punktregel): kein Befund
        assert check.datenschutz(db)["befunde"] == []
        mp.setattr(maske, "ausgang_punktregel", lambda p, gremien=(): False)   # Fehler: auch ohne die Punktregel
        erg = check.datenschutz(db)
    db.close()
    # „Einwohner-Anfrage“ und „Bürger‑Antrag“ erkennt geocode.EINGABE, „Bürgerbrief “ chat.EINWOHNER (ohne Leerraum);
    # „Anwohnerantrag“ melden beide Gegenproben (Vorlagenart von Personen, Grund „vorlagenart“)
    b = [x for x in erg["befunde"] if "Eingabe oder Einwohneranfrage ohne Hauskoordinate" in x]
    assert len(b) == 1 and b[0].endswith(": 1, z. B. 1802/2026"), erg["befunde"]
    b = [x for x in erg["befunde"] if "nicht in der Titelmaske" in x and "Gremium" in x]
    assert len(b) == 1 and b[0].endswith(": 1, z. B. 1802/2026"), erg["befunde"]
    altes_suffix = maske.SUFFIX.replace(r"str(?:\.|(?!" + maske._L + "))", r"str\.")
    assert altes_suffix != maske.SUFFIX

    def altes_muster(strassen):   # Muster von 5decb33: Leerraum zwischen Straße und Nummer, „ß“ wie geliefert
        namen = sorted({s for s in strassen if s}, key=len, reverse=True)
        return re.compile(rf"((?:{'|'.join([*map(re.escape, namen), altes_suffix])})\s+)(?:nr\.?\s*)?{maske.NR}",
                          re.I)

    with monkeypatch.context() as mp:   # Maske ohne die neuen Schreibweisen: das Sicherheitsnetz (Probe) blendet aus
        mp.setattr(maske, "_muster", altes_muster)
        export.export()
        capsys.readouterr()
        titel = titel_im_export()
        assert len(titel) >= 5 and not [x for x in titel if nr[0] in x], titel

    def ohne_sicherheitsnetz(self, titel, ref):   # Maske vor der zweiten Korrektur der Prüfung r20a: nur die Muster
        if not self._betroffen(titel, ref):
            return titel
        angeglichen, stellen = maske._angleichen(titel)
        return maske._ersetzen(titel, [(*maske._im_text(stellen, a, e, len(titel)), x)
                                       for a, e, x in self._stellen(angeglichen)])

    with monkeypatch.context() as mp:   # Fehler: Maske ohne die neuen Schreibweisen und ohne Sicherheitsnetz
        mp.setattr(maske, "_muster", altes_muster)
        mp.setattr(maske.Maske, "__call__", ohne_sicherheitsnetz)
        export.export()
        capsys.readouterr()
        assert [x for x in titel_im_export() if nr[0] in x]
        db = sqlite3.connect(config.DB)
        erg = check.datenschutz(db)
        db.close()
    # „…straße, Nr. 5“ und „…straße (Nr. 5)“ blendet auch ohne die neuen Schreibweisen das bloße „Nr.“ aus (NUR_NR);
    # 1660/2026 (Bauordnungsamt): Fundstelle „63 Bauaufsicht“ im Audit der Themen, die die Maske ohne Positivliste
    # stehen lässt (dritte Korrektur)
    b = [x for x in erg["befunde"] if "Hausnummern in Titeln oder Ortsnamen" in x]
    assert len(b) == 1 and b[0].endswith(": 4, z. B. 1660/2026, 1801/2026, 1804/2026, 1805/2026"), b


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


def test_fundstelle_bebauungsplan_maskiert_und_geprueft(testdaten, monkeypatch, capsys):
    """Prüfung r20a (Fix), Ende zu Ende mit erfundenen Eingaben: Die Fundstelle eines Bebauungsplans (Text zwischen
    „Bebauungsplan“ und der Plannummer, geocode.PLAN) nennt die Hausnummer aus dem Titel. export blendet sie wie im
    Titel aus: in vorlagen.geojson (evidence), den Gebietsdateien (plans[].evidence, locations[].evidence), plaene.json
    (vorlagen[].fundstelle) und den Spalten „fundstelle“ der Audits und der Stichprobe je Methode; die Datenbank behält
    die volle Fundstelle (Verortung und Audit arbeiten mit dem vollen Titel). check meldet nichts und meldet die
    ungekürzte Fundstelle in jeder dieser Dateien. Dazu eine Eingabe, die ihre Rechtsgrundlage in Klammern hinter der
    Straße nennt („(§ 24 GO NRW)“): Titel unverändert, kein Befund (vorher hielt die Probe die Veröffentlichung an)."""
    monkeypatch.setattr(config, "BPLAN", config.GEO / "bebauungsplaene_koeln.geojson")
    monkeypatch.setattr(export, "_PLANS", None)
    strasse, nr, _ = _lage()
    titel = f"[Testdaten] Bebauungsplan für das Grundstück {strasse} {nr[0]} (57450/02)"
    paragraf = f"[Testdaten] Sperrung der {strasse} (§ 24 GO NRW)"
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.write(json.dumps(_vorlage("bp_e", "1950/2026", titel, art=EINGABE), ensure_ascii=False) + "\n")
        f.write(json.dumps(_vorlage("bp_p", "1951/2026", paragraf, art=EINGABE), ensure_ascii=False) + "\n")
    build.build()
    export.export()
    capsys.readouterr()
    voll = f"{strasse} {nr[0]}"
    db = sqlite3.connect(config.DB)
    assert {"1950/2026", "1951/2026"} <= maske.aus_db(db).refs
    roh = db.execute("SELECT evidence FROM paper_plan WHERE paper_id = ?", (_id("bp_e"),)).fetchone()[0]
    assert voll in roh and roh.startswith("Bebauungsplan")   # Datenbank: volle Fundstelle

    base = config.EXPORT / config.STADT
    geo = json.loads((base / "vorlagen.geojson").read_text())
    fund = [f["properties"]["evidence"] for f in geo["features"] if f["properties"]["reference"] == "1950/2026"]
    gebiete = [p for d in check.GEBIETSDATEIEN for datei in (base / d).glob("*.json")
               for p in json.loads(datei.read_text())["papers"] if p["reference"] == "1950/2026"]
    fund += [x["evidence"] for p in gebiete for k in ("plans", "locations") for x in p[k]]
    plaene = json.loads((base / "plaene.json").read_text())
    fund += [v["fundstelle"] for e in plaene["plaene"] for v in e["vorlagen"] if v["drucksache"] == "1950/2026"]
    tabellen = {}
    for pfad in (config.EXPORT / "audit_geokodierung.tsv", config.EXPORT / "audit_bebauungsplaene.tsv",
                 config.EXPORT / "stichprobe_geokodierung.tsv"):
        kopf, *zeilen = _tsv(pfad)
        tabellen[pfad] = [z[kopf.index("fundstelle")] for z in zeilen if z[kopf.index("drucksache")] == "1950/2026"]
        fund += tabellen[pfad]
    gekuerzt = roh.replace(voll, f"{strasse} {maske.OHNE_NR}")
    assert gebiete and all(tabellen.values()) and gekuerzt in fund, fund
    assert not [x for x in fund if x and nr[0] in x.replace("57450/02", "")], fund
    assert [r[1] for r in json.loads((base / "suche.json").read_text())["rows"] if r[0] == "1951/2026"] == [paragraf]
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["untersucht"]["fundstellen"] >= len(fund) - 3, erg

    # Gegenprobe: die ungekürzte Fundstelle in einer der Dateien meldet check (je Datei einzeln)
    def ungekuerzt(text):
        return text.replace(gekuerzt, roh) if isinstance(text, str) else text

    def json_datei(pfad):
        return pfad, lambda d: json.loads(ungekuerzt(json.dumps(d, ensure_ascii=False)))

    dateien = [json_datei(base / "vorlagen.geojson"), json_datei(base / "plaene.json")]
    dateien += [json_datei(datei) for d in check.GEBIETSDATEIEN for datei in (base / d).glob("*.json")
                if "1950/2026" in datei.read_text()][:1]
    for pfad, aendern in dateien:
        alt = pfad.read_text()
        pfad.write_text(json.dumps(aendern(json.loads(alt)), ensure_ascii=False))
        b = check.datenschutz(db)["befunde"]
        pfad.write_text(alt)
        assert len(b) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b[0] and b[0].endswith(
            ": 1, z. B. 1950/2026"), (pfad, b)
    for pfad in tabellen:
        alt = pfad.read_text(encoding="utf-8")
        pfad.write_text(alt.replace(gekuerzt, roh), encoding="utf-8")
        b = check.datenschutz(db)["befunde"]
        pfad.write_text(alt, encoding="utf-8")
        assert len(b) == 1 and b[0].endswith(": 1, z. B. 1950/2026"), (pfad, b)
    assert check.datenschutz(db)["befunde"] == []
    db.close()


# --- Prüfung r20a, zweite Korrektur: Sicherheitsnetz der Maske, Listen, Lagewörter, Wörter, Straßennamen --------------

# echte Namen aus dem Kölner Straßenverzeichnis ohne Straßen-Endung, wie dort geschrieben („St.“ ohne Leerzeichen)
NAMEN_R20A2 = ["Aachener Straße", "Venloer Straße", "An St. Heinrich", "An St.Katharinen", "An Groß St.Martin",
               "An St.Agatha", "Bertha-Benz-Karree", "Maler-Bock-Gäßchen"]
# (Titel, erwartet); erwartet mit {o} für OHNE_NR
SCHREIBWEISEN_R20A2 = [
    # „)“ und ein Listenwort hinter der Nummer: vorher meldete check den Titel, und die Maske konnte ihn nicht beheben;
    # eine Ordnungszahl vor „Nachtrag“, „Beratung“ oder „Ergänzung“ bleibt seit der dritten Korrektur stehen
    ("Eingabe nach § 24 GO NRW (Venloer Straße 12/14) – 2. Nachtrag",
     "Eingabe nach § 24 GO NRW (Venloer Straße {o}) – 2. Nachtrag"),
    ("Einwohneranfrage (Venloer Straße 5), 2. Beratung", "Einwohneranfrage (Venloer Straße {o}), 2. Beratung"),
    ("Anregung gemäß § 24 GO NRW (Venloer Straße 300) und 2 weitere Eingaben",
     "Anregung gemäß § 24 GO NRW (Venloer Straße {o}) und {o} weitere Eingaben"),
    ("Tempo 30 Aachener Straße (Hausnummer: 27) – 2. Ergänzung", "Tempo 30 Aachener Straße ({o}) – 2. Ergänzung"),
    ("Aachener Straße (Haus-Nr. 9) und 15", "Aachener Straße ({o}) und {o}"),
    ("Aachener Straße (22) und 28", "Aachener Straße ({o}) und {o}"),
    ("Aachener Straße 16 (und 18)", "Aachener Straße {o} (und {o})"),
    # „u.“ und „u“: vorher las die Maske das „u“ als Zusatz der Hausnummer, die zweite Nummer blieb ohne Befund stehen
    ("Aachener Straße 7 u. 9", "Aachener Straße {o}"), ("Aachener Straße 53 u 55", "Aachener Straße {o}"),
    ("Aachener Straße, Hausnummern 22 u. 24", "Aachener Straße, {o}"), ("Venloer Str. 300 u. 302a", "Venloer Str. {o}"),
    ("Hausnummer 12 u. 14", "{o}"), ("Aachener Straße 12a u. 14", "Aachener Straße {o}"),
    # „Nr.“ vor einer weiteren Nummer und „;“
    ("Aachener Straße Nr. 23 und Nr. 25", "Aachener Straße {o}"), ("Aachener Straße 228 und Nr. 230", "Aachener Straße {o}"),
    ("Aachener Straße 12 bis Nr. 20", "Aachener Straße {o}"), ("Aachener Straße 12 – Nr. 20", "Aachener Straße {o}"),
    ("Aachener Straße 12, Nr. 14", "Aachener Straße {o}"), ("Aachener Straße 12 bzw. Nr. 14", "Aachener Straße {o}"),
    ("Aachener Straße Nr. 300 sowie Nr. 302", "Aachener Straße {o}"),
    ("Aachener Straße Nr. 300/Nr. 302", "Aachener Straße {o}"),
    ("Aachener Straße Hausnummer 300 und Nr. 302", "Aachener Straße {o}"), ("Aachener Straße 300; 302", "Aachener Straße {o}"),
    # Lagewort zwischen Straße und Nummer, bloßes „Nr.“
    ("Behindertenparkplatz Venloer Straße vor Nr. 300", "Behindertenparkplatz Venloer Straße vor {o}"),
    ("in der Venloer Straße in Höhe Nr. 300", "in der Venloer Straße in Höhe {o}"),
    ("Venloer Straße, Höhe Nr. 300", "Venloer Straße, Höhe {o}"), ("Venloer Straße gegenüber Nr. 300", "Venloer Straße gegenüber {o}"),
    ("Venloer Straße neben Nr. 300", "Venloer Straße neben {o}"), ("Venloer Straße hinter Nr. 300", "Venloer Straße hinter {o}"),
    ("Venloer Straße ab Nr. 12", "Venloer Straße ab {o}"), ("Venloer Straße Ecke Nr. 300", "Venloer Straße Ecke {o}"),
    ("Venloer Straße zwischen Nr. 12 und 20", "Venloer Straße zwischen {o}"),
    ("Venloer Straße zwischen 300 und 320", "Venloer Straße zwischen {o}"), ("Venloer Straße Höhe 12", "Venloer Straße Höhe {o}"),
    ("Venloer Straße, vor Haus 2", "Venloer Straße, vor {o}"),
    ("Venloer Straße gegenüber dem Haus 300", "Venloer Straße gegenüber dem {o}"),
    ("Poller vor Nr. 12 der Venloer Straße", "Poller vor {o} der Venloer Straße"),
    # Wörter für die Hausnummer: Mehrzahl, Leerzeichen, „Häuser“, hinter der Straße „Hs.“
    ("Venloer Straße Haus-Nrn. 300 bis 304", "Venloer Straße {o}"), ("Venloer Straße Hausnrn. 300-304", "Venloer Straße {o}"),
    ("Venloer Straße Hs.-Nrn. 300-304", "Venloer Straße {o}"), ("Venloer Straße HNrn. 300-304", "Venloer Straße {o}"),
    ("Venloer Straße Haus Nummer 300", "Venloer Straße {o}"), ("Venloer Straße Häuser 300 bis 304", "Venloer Straße {o}"),
    ("Venloer Straße Hs. 300", "Venloer Straße {o}"),
    ("vor Haus Nummer 300 in der Venloer Straße", "vor {o} in der Venloer Straße"),
    ("Venloer Straße zwischen den Häusern 300 und 302", "Venloer Straße zwischen den {o}"),
    # Straßennamen ohne Endung in anderer Schreibung als im Verzeichnis
    ("Lärm An St. Katharinen 5", "Lärm An St. Katharinen {o}"), ("An Groß St. Martin 5", "An Groß St. Martin {o}"),
    ("An Sankt Agatha 5", "An Sankt Agatha {o}"), ("An St.Heinrich 4", "An St.Heinrich {o}"),
    ("Bertha Benz Karree 3", "Bertha Benz Karree {o}"), ("Maler Bock Gäßchen 2", "Maler Bock Gäßchen {o}"),
    # Ziffer erst nach NFKC (isdigit kennt „⒓“ nicht)
    ("Venloer Straße ⒓", "Venloer Straße {o}")]


@pytest.mark.parametrize("titel, erwartet", SCHREIBWEISEN_R20A2)
def test_maske_r20a_zweite_korrektur(titel, erwartet):
    """Prüfung r20a, zweite Korrektur: Hausnummern, die die Maske stehen ließ (ohne Befund in check: „u.“, „Nr.“ vor einer
    weiteren Nummer, Lagewörter, Mehrzahl des Worts, „St. “ und „Sankt“, „⒓“), oder die check meldete, ohne dass die Maske
    sie beheben konnte (Klammer und Listenwort hinter der Nummer: hätte die erste Veröffentlichung angehalten). Danach
    meldet offen() nichts; andere Drucksachen bleiben unverändert."""
    m = maske.Maske({"1/2026"}, strassen=NAMEN_R20A2)
    assert m.offen(titel, "1/2026")
    aus = m(titel, "1/2026")
    assert aus == erwartet.format(o=maske.OHNE_NR), aus
    assert not _pruefend(m).offen(aus, "1/2026") and m(aus, "1/2026") == aus and m(titel, "2/2026") == titel


@pytest.mark.parametrize("titel", ["Musterstraße ab 2027", "Sperrung der Musterstraße bis 2030",
                                   "Drucksache Nr. 1234/2026", "Bebauungsplan Nr. 70459",
                                   "Musterweg, 50931 Köln", "Musterweg (§ 24 GO NRW) – Vorlage 1234/2026"])
def test_maske_r20a_zweite_korrektur_laesst_stehen(titel):
    """Jahreszahlen hinter „ab“ und „bis“, Drucksachen mit „/“ und fünfstellige Nummern bleiben stehen, auch mit dem
    Sicherheitsnetz und der Positivliste („Haus 2 der Gesamtschule“ blendet die Maske seit der dritten Korrektur aus)."""
    m = maske.Maske({"1/2026"}, strassen=NAMEN_R20A2)
    assert m(titel, "1/2026") == titel and not _pruefend(m).offen(titel, "1/2026")


def _verzeichnis():
    return sorted(json.loads((ROOT / "data" / "geo" / "strassen_koeln.json").read_text())["streets"])


def test_maske_fixpunkt_viele_schreibweisen():
    """Prüfung r20a, zweite Korrektur: 3 000 erfundene Titel aus Namen des Kölner Straßenverzeichnisses (auch mit
    „St. “ und Leerzeichen statt Bindestrich), Trennzeichen, Lagewörtern, Wörtern für die Hausnummer, Listen,
    Klammern und Anhängen wie „– 2. Nachtrag“: Die Hausnummern fehlen danach, und offen() meldet für kein Ergebnis etwas
    (ein Befund hielte die Veröffentlichung an). Vorher blieben in dieser Menge Nummern ohne Befund stehen, und check
    meldete Titel, die die Maske nicht beheben konnte."""
    namen = [n for n in _verzeichnis() if not re.search(r"\d", n)]
    m = maske.Maske({"1/2026"}, strassen=namen)
    pruefend = _pruefend(m)
    rnd = random.Random(2026)
    anfang = ["Anregung gemäß § 24 GO NRW: Verkehrsberuhigung ", "Einwohneranfrage zur Baustelle ", "Tempo 30 ",
              "Eingabe nach § 24 GO NRW (", "", "Behindertenparkplatz in der "]
    vor = [(" ", ""), (", ", ""), (" (", ""), ("", ""), (" #", ""), (", Höhe ", ""), (" zwischen ", ""),
           (" vor ", "Nr. "), (" gegenüber ", "Haus "), (" ", "Nr. "), (" ", "Haus "), (" ", "Hausnummer "),
           (" ", "Haus-Nrn. "), (" ", "Hs. "), (", ", "Hausnummer: "), (" ", "Häuser "), (" in Höhe ", "Nr. ")]
    liste = ["", " u. {m}", " u {m}", " und Nr. {m}", "-{m}", "; {m}", " bis {m}", " (und {m})", " bzw. {m}a", "/{m}"]
    ende = ["", " – 2. Nachtrag", ", 2. Beratung", " und 2 weitere Eingaben", " – 1. Ergänzung", " (§ 24 GO NRW)"]
    gesehen = 0
    for _ in range(3000):
        name = rnd.choice(namen)
        if rnd.random() < 0.3:
            name = re.sub(r"St\.(?=\w)", "St. ", name).replace("-", " ")
        n, k = rnd.sample(range(100, 1000), 2)
        start = rnd.choice(anfang)
        trenn, wort = rnd.choice(vor)
        titel = (f"{start}{name}{trenn}{wort}{n}{rnd.choice(['', 'a', ' b'])}{rnd.choice(liste).format(m=k)}"
                 f"{')' if '(' in start + trenn else ''}{rnd.choice(ende)}")
        aus = m(titel, "1/2026")
        assert str(n) not in aus and str(k) not in aus, (titel, aus)
        assert not pruefend.offen(aus, "1/2026"), (titel, aus)
        gesehen += aus != titel
    assert gesehen == 3000


def test_maske_sicherheitsnetz_beliebige_texte():
    """Prüfung r20a, zweite Korrektur: Für jeden Text endet die Maske, und offen() meldet für das Ergebnis nichts (Texte
    aus Straßen, Wörtern, Listen, Klammern, Ziffern auch in Vollbreite und mit Zeichen ohne Breite, ausgeblendeten
    Hausnummern): Ein Befund in check kann seither nur einen Text betreffen, der die Maske nicht durchlaufen hat."""
    m = maske.Maske({"1/2026"}, strassen=NAMEN_R20A2)
    pruefend = _pruefend(m)
    rnd = random.Random(20)
    teile = ["Aachener Straße", "Musterweg", " ", ", ", "(", ")", "Nr. ", "Haus ", "Hausnummer ", " u. ", " und ", "-",
             "/", ";", "12", "7", "１２", "3a", "​", "⒓", "§ 24", "2.", "50931", "12.03.2026", maske.OHNE_NR,
             " vor ", " Höhe ", "Häuser ", "St.", "An St. Katharinen", "–"]
    for _ in range(4000):
        titel = "".join(rnd.choice(teile) for _ in range(rnd.randint(1, 12)))
        aus = m(titel, "1/2026")
        assert not pruefend.offen(aus, "1/2026"), (titel, aus)


def test_maske_rechnet_jeden_titel_einmal(monkeypatch):
    """Prüfung r20a, zweite Korrektur (Laufzeit von export): Maske.__call__ rechnet je (Titel, Drucksache) einmal;
    derselbe Titel in Suche, GeoJSON, Gebietsdateien, Audits und Stichproben kostet danach nur einen Blick in den
    Zwischenspeicher. offen() für das Ergebnis ist dabei schon bekannt."""
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße"])
    gerufen = []
    echt = maske._angleichen
    monkeypatch.setattr(maske, "_angleichen", lambda t: gerufen.append(t) or echt(t))
    for _ in range(3):
        aus = m("Aachener Straße 12", "1/2026")
    n = len(gerufen)
    assert aus == f"Aachener Straße {maske.OHNE_NR}" and n == 2   # eine Runde mit Treffer, eine ohne
    assert not m.offen(aus, "1/2026") and len(gerufen) == n   # Vermerk derselben Instanz, ohne Rechnung
    assert not _pruefend(m).offen(aus, "1/2026")   # zweite Maske: das Ergebnis ist wirklich ohne Befund


def test_maske_name_in_baumform_wie_alternative():
    """Das Muster der Straßennamen in Baumform (_namen_muster) findet jeden Namen des Verzeichnisses vor einer
    Hausnummer wie die einfache Alternative vorher, auch längere Namen mit gleichem Anfang („Am Hof“, „Am Hofgarten“)."""
    namen = [n for n in _verzeichnis() if not re.search(r"\d", n)]
    rx = re.compile(rf"(?:{maske._namen_muster(namen)})(?= 12$)", re.I)
    for name in namen:
        assert rx.match(f"{name} 12") and rx.match(f"{name} 12").group() == name, name
    assert maske._namen_muster([]) == "(?!)"


@pytest.mark.parametrize("text, erwartet", [
    ("Bebauungsplan 61459/04", "Bebauungsplan"), ("Flurstück 12345/6", "Flurstück"), ("50823Köln", "Köln"),
    ("Venloer Straße 300, 50823 Köln", "Venloer Straße, 50823 Köln"), ("Venloer Straße 12-14", "Venloer Straße"),
    ("Gemarkung Müngersdorf, Flur 12, Flurstück 345/6", "Gemarkung Müngersdorf, Flur, Flurstück"),
    ("50823 Köln-Ehrenfeld", "50823 Köln-Ehrenfeld"), ("Aachener Straße 1175 a", "Aachener Straße"),
    # dritte Korrektur: Ziffern erst nach NFKC (vorher „Severinstraße ½“, und check hielt die Veröffentlichung an)
    ("Severinstraße 12½", "Severinstraße"), ("Am Hof ⒓", "Am Hof"), ("Venloer Straße 3¹", "Venloer Straße"),
    ("Venloer Straße ²", "Venloer Straße")])
def test_ortsangabe_ohne_hausnummer_wie_pruefung(text, erwartet):
    """Prüfung r20a, zweite Korrektur: build.ohne_hausnummer entfernt jede Ziffernfolge außer einer Postleitzahl als
    ganzem Wort (build.PLZ), dieselbe Regel, mit der check die Ortsangaben der Stadt prüft (build.ziffer_ausser_plz).
    Vorher blieben fünf- und mehrstellige Nummern stehen („Bebauungsplan 61459/“), und check meldete sie als Hausnummer.
    Dritte Korrektur: Zeichen, deren NFKC-Form eine Ziffer enthält („½“, „¹“, „⒓“), zählen als Ziffern."""
    assert build.ohne_hausnummer(text) == erwartet
    assert not re.search(r"\d", build.PLZ.sub("", erwartet)) and not build.ziffer_ausser_plz(erwartet)
    assert build.ziffer_ausser_plz(text) == (text != erwartet)


def test_ortsangabe_ohne_hausnummer_beliebige_texte():
    """Für jeden Text lässt build.ohne_hausnummer nur Ziffern in Postleitzahlen stehen (die Prüfung in check findet
    nichts)."""
    rnd = random.Random(24)
    teile = ["Straße", " ", ",", "-", "/", "12", "61459", "50823", "5082", "a", "Köln", "(", ")", "bis", "٣", "x", "_",
             "½", "¹", "⒓", "１２"]
    for _ in range(5000):
        text = "".join(rnd.choice(teile) for _ in range(rnd.randint(1, 10)))
        aus = build.ohne_hausnummer(text) or ""
        assert not build.ziffer_ausser_plz(aus), (text, aus)
        assert not [z for z in _zahlen(aus) if not re.fullmatch(r"5\d{4}", z)], (text, aus)   # wie die Titelmaske


def test_ortsangabe_mit_plannummer_ende_zu_ende(testdaten, capsys):
    """Prüfung r20a, zweite Korrektur, Ende zu Ende mit einer erfundenen Ortsangabe der Stadt: Straße „Bebauungsplan
    61459/04“, Beschreibung „Flurstück 12345/6, 50823Köln“. build speichert sie ohne Nummern, check meldet nichts
    (vorher: „Hausnummern in Ortsangaben der Stadt“)."""
    xy = _zweite_lage(_lage()[0])
    ort = {**_ort("plan", "Bebauungsplan 61459/04", xy[0]), "description": "Flurstück 12345/6, 50823Köln"}
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.write(json.dumps(_vorlage("plan_o", "1970/2026", "[Testdaten] Mitteilung zum Bebauungsplan", location=[ort]),
                           ensure_ascii=False) + "\n")
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    assert db.execute("SELECT street, description FROM location WHERE id = ?", (ort["id"],)).fetchone() == (
        "Bebauungsplan", "Flurstück, Köln")
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg


def test_neue_schreibweisen_ende_zu_ende(testdaten, capsys):
    """Prüfung r20a, zweite Korrektur, Ende zu Ende mit erfundenen Eingaben nach § 24 GO NRW: „u.“, „Nr. … und Nr. …“,
    „vor Nr.“, „Haus-Nrn.“ und „(Straße 5) – 2. Nachtrag“. In keiner Datei unter data/export (Suche, GeoJSON,
    Gebietsdateien, Feeds, Audits, Stichproben) steht eine dieser Hausnummern; check meldet nichts. Die Stichprobe je
    Methode maskiert auch die Spalte „ort“, check prüft sie (und „zurueckgestellt“); eine ungekürzte Spalte „ort“ meldet
    check als Befund. Dritte Korrektur: Eine Zahl ohne Straße („Pavillon 7“) und eine Hausnummer in Worten („Nummer
    zwölf“) blendet die Maske aus (vorher nur ein Hinweis in check); „2. Nachtrag“ bleibt stehen."""
    strasse, nr, _ = _lage()
    a, b = nr[0], nr[1]
    faelle = [("ng_u", "1981/2026", f"[Testdaten] Poller {strasse} {a} u. {b}"),
              ("ng_nr", "1982/2026", f"[Testdaten] Halteverbot {strasse} Nr. {a} und Nr. {b}"),
              ("ng_vor", "1983/2026", f"[Testdaten] Behindertenparkplatz {strasse} vor Nr. {a}"),
              ("ng_hn", "1984/2026", f"[Testdaten] Lärm {strasse} Haus-Nrn. {a} bis {b}"),
              ("ng_kl", "1985/2026", f"[Testdaten] Eingabe ({strasse} {a}) – 2. Nachtrag"),
              ("ng_rest", "1986/2026", "[Testdaten] Lärm am Kiosk Nummer zwölf, Pavillon 7")]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(_vorlage(k, ref, titel, art=EINGABE), ensure_ascii=False) + "\n"
                     for k, ref, titel in faelle)
    build.build()
    export.export()
    capsys.readouterr()
    roh = [f"{a} u. {b}", f"Nr. {a} und Nr. {b}", f"vor Nr. {a}", f"Haus-Nrn. {a}", f"{strasse} {a}", "Pavillon 7",
           "Nummer zwölf"]
    dateien = [p for p in config.EXPORT.rglob("*") if p.is_file() and p.suffix in (".json", ".geojson", ".tsv", ".xml",
                                                                                    ".ics", ".csv")]
    assert any(p.suffix == ".xml" for p in dateien) and any(p.suffix == ".tsv" for p in dateien)
    for p in dateien:
        text = p.read_text(encoding="utf-8")
        assert not [r for r in roh if r in text], p
    db = sqlite3.connect(config.DB)
    assert {ref for _, ref, _ in faelle} <= maske.aus_db(db).refs
    erg = check.datenschutz(db)
    aus = capsys.readouterr().out
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    assert "Titel der Maske" not in aus and strasse not in aus
    suche = {r[0]: r[1] for r in json.loads((config.EXPORT / config.STADT / "suche.json").read_text())["rows"]}
    assert suche["1985/2026"].endswith(f"({strasse} {maske.OHNE_NR}) – 2. Nachtrag"), suche["1985/2026"]
    assert suche["1986/2026"] == f"[Testdaten] Lärm am Kiosk {maske.OHNE_NR}, Pavillon {maske.OHNE_NR}"
    assert {"ort", "zurueckgestellt"} <= check.TSV_TEXTSPALTEN
    # Stichprobe je Methode: Ort ungekürzt (etwa aus einem früheren Lauf) meldet check
    pfad = config.EXPORT / "stichprobe_geokodierung.tsv"
    kopf, *zeilen = _tsv(pfad)
    i, j = kopf.index("drucksache"), kopf.index("ort")
    zeile = next(z for z in zeilen if z[i] in maske.aus_db(db).refs)
    zeile[j] = f"{strasse} {a}"
    pfad.write_text("\n".join("\t".join(z) for z in [kopf, zeile]) + "\n", encoding="utf-8")
    b_ = check.datenschutz(db)["befunde"]
    db.close()
    assert len(b_) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b_[0] and b_[0].endswith(f"z. B. {zeile[i]}"), b_


# --- Prüfung r20a, dritte Korrektur: Positivliste, Fundstellen im Zusammenhang, Ortsnamen, Feeds, Ergebnisse ----------

def _zahlen(text):
    """Ziffernfolgen eines Texts nach NFKC (unabhängig von der Maske: Orakel der Tests)."""
    import unicodedata
    return set(re.findall(r"\d+", unicodedata.normalize("NFKC", text)))


# (Titel, Nummern, die danach fehlen müssen): Schreibweisen aus der Prüfung der zweiten Korrektur, die Maske und Probe
# stehen ließen, ohne Befund in check (Nummer mit „/“ ohne Straße, Listen mit Klammer oder Zwischenwort, Lage- und
# Bezugswörter, Nummer vor der Straße, unbekannte Straßennamen, Flurstück, Zahl am Titelende)
OHNE_STRASSE_R20A3 = [
    ("Anregung: Parkplätze vor Nr. 12/14 der Venloer Straße", "12 14"), ("Mülltonnen vor Nr. 7/9", "7 9"),
    ("Nr. 7 / 9 Venloer Straße", "7 9"), ("Baum vor Haus 12/14 in der Venloer Straße", "12 14"),
    ("Venloer Straße, Einfahrt 12/14", "12 14"), ("Venloer Straße im Bereich 12/14", "12 14"),
    ("Venloer Straße, vor der 12/14", "12 14"), ("Parkverbot vor Nr. 12 / Ecke Gutenbergstraße", "12"),
    ("Poller vor Nr. 12/14 der Venloer Straße", "12 14"),
    ("Venloer Straße 12 bis 14 (gerade) und 13 bis 17 (ungerade)", "12 14 13 17"),
    ("Hausnummern 2 bis 10 (gerade) und 1 bis 9 (ungerade) der Venloer Straße", "2 10 1 9"),
    ("Venloer Straße 12 bis einschließlich 20", "12 20"), ("Venloer Straße 12 und gegenüberliegende 13", "12 13"),
    ("Venloer Straße 12 sowie gegenüber 13", "12 13"), ("Venloer Straße 12 / gegenüber 15", "12 15"),
    ("Venloer Straße 12, ferner 14", "12 14"), ("Venloer Straße 12 oder ggf. 14", "12 14"),
    ("Venloer Straße 12 und die Nummer 14", "12 14"), ("Venloer Straße 12 [14]", "12 14"),
    ("Venloer Straße 12 ... 14", "12 14"), ("Venloer Straße 12 … 14", "12 14"),
    ("Venloer Straße 12 (Ehrenfeld) und 14", "12 14"), ("Venloer Straße 12 (Ecke Gürtel) bis 20", "12 20"),
    ("Venloer Straße 12 bis 14 und gegenüberliegende Seite 13 bis 17", "12 14 13 17"),
    ("Venloer Straße am Haus 12", "12"), ("Venloer Straße beim Haus 12", "12"), ("Venloer Straße an 12", "12"),
    ("Venloer Straße auf Höhe 12", "12"), ("Venloer Straße auf Höhe von 12", "12"), ("Venloer Straße Höhe der 12", "12"),
    ("Venloer Straße vor 12", "12"), ("Venloer Straße vor der 12", "12"), ("Venloer Straße neben der 12", "12"),
    ("Venloer Straße gegenüber der 12", "12"), ("Venloer Straße an der 12", "12"), ("Venloer Straße bei 12", "12"),
    ("Venloer Straße bei der 12", "12"), ("Venloer Straße nahe 12", "12"), ("Venloer Straße in der Nähe von 12", "12"),
    ("Venloer Straße ab der 12", "12"), ("Venloer Straße Einmündung 12", "12"), ("Venloer Straße Eingang 12", "12"),
    ("Venloer Straße Hauseingang 12", "12"), ("Venloer Straße Einfahrt 12", "12"), ("Venloer Straße Grundstück 12", "12"),
    ("Venloer Straße Gebäude 12", "12"), ("Venloer Straße Wohnhaus 12", "12"),
    ("Venloer Straße Mehrfamilienhaus 12", "12"), ("Venloer Straße Objekt 12", "12"),
    ("Venloer Straße Liegenschaft 12", "12"), ("Venloer Straße Hinterhaus 3", "3"), ("Venloer Straße Hof der 12", "12"),
    ("Venloer Straße im Bereich 12-20", "12 20"), ("Venloer Straße von 12 bis 20", "12 20"),
    ("Venloer Straße im Abschnitt 12-20", "12 20"), ("Venloer Straße Abschnitt zwischen 12 und 20", "12 20"),
    ("Aachener Straße von 1175 bis 1181", "1175 1181"), ("Grundstück Nummer 12 an der Venloer Straße", "12"),
    ("vor dem Haus mit der Nummer 12", "12"), ("Nummer 12 Venloer Straße", "12"),
    ("an der Hausnummer (12) der Venloer Straße", "12"), ("Eingabe: 12 Venloer Straße", "12"),
    ("Parkverbot 12, Venloer Straße", "12"), ("Haus 12, Venloer Straße", "12"),
    ("Baumfällung vor Haus 12 in der Venloer Straße", "12"), ("Neubau Venloer Straße 12 in Köln, Haus 2", "12 2"),
    ("Venloer Straße, Einfahrt 12.", "12"), ("Venloer Straße, am Haus 12.", "12"),
    ("Poller vor Haus 12. Anwohner beschweren sich", "12"),
    ("Ebertpl. 12", "12"), ("Rathenaupl. 12", "12"), ("Mediapark 5", "5"), ("Rinkenpfuhl 12", "12"),
    ("Malzbüchel 3", "3"), ("Zuelpicher Wall 12", "12"), ("Am Hoefchen 3", "3"), ("Achtergaesschen 3", "3"),
    ("Ehrenfeld-Gürtel 12", "12"), ("Severins-Wall 12", "12"), ("An Groß-St.-Martin 5", "5"),
    ("An Gr. St. Martin 5", "5"), ("Venloer Stra-\nße 12", "12"), ("Venloer Stra&szlig;e 12", "12"),
    ("Venloer Straße 12 &amp; 14", "12 14"),
    ("Bauvorhaben Gemarkung Ehrenfeld, Flur 12, Flurstück 345", "12 345"),
    ("Venloer Straße, auf Höhe Haus 12", "12"), ("Venloer Straße in Höhe des Hauses 12", "12"),
    ("Venloer Straße vor dem Hause 12", "12"), ("Venloer Straße, Nummern 12 bis 16", "12 16"),
    ("Venloer Straße Hoehe 12", "12"), ("Venloer Straße (12) (und 14)", "12 14"), ("Venloer Straße (12), (14)", "12 14"),
    ("Venloer Straße 12 o. 14", "12 14"), ("Venloer Straße 12 resp. 14", "12 14"), ("Venloer Straße 12 –– 14", "12 14"),
    ("Venloer Straße 12 bis einschl. 16", "12 16"), ("An St Katharinen 5", "5")]


@pytest.mark.parametrize("titel, nummern", OHNE_STRASSE_R20A3)
def test_maske_dritte_korrektur_keine_nummer(titel, nummern):
    """Prüfung r20a, dritte Korrektur: In jedem dieser Titel (Kölner Straßenverzeichnis) fehlt danach jede genannte
    Nummer; Orakel ist die Ziffernfolge selbst, nicht die Probe der Maske. Vorher blieben sie stehen, und check meldete
    nichts. offen() meldet für das Ergebnis nichts, eine andere Drucksache bleibt unverändert."""
    m = maske.Maske({"1/2026"}, strassen=_verzeichnis())
    aus = m(titel, "1/2026")
    assert not _zahlen(aus) & set(nummern.split()), aus
    assert maske.OHNE_NR in aus and not _pruefend(m).offen(aus, "1/2026") and m(titel, "2/2026") == titel


@pytest.mark.parametrize("titel", ["Venloer Straße Hausnummer zwölf", "Lärm an der Venloer Straße, Nummer zwölf",
                                   "Venloer Straße Nr. elf", "Venloer Straße, Hausnummer (drei)"])
def test_maske_hausnummer_in_worten(titel):
    """Prüfung r20a, dritte Korrektur: eine Hausnummer in Worten hinter „Hausnummer“, „Nr.“ oder „Nummer“ fehlt danach
    (vorher unverändert, ohne Befund und ohne Hinweis)."""
    m = maske.Maske({"1/2026"}, strassen=["Venloer Straße"])
    aus = m(titel, "1/2026")
    assert maske.OHNE_NR in aus and not re.search(r"zwölf|elf|drei", aus), aus
    assert not _pruefend(m).offen(aus, "1/2026") and _pruefend(m).offen(titel, "1/2026")


@pytest.mark.parametrize("titel", [
    "Anregung nach § 24 GO NRW", "§§ 24, 25 GO", "Einwohneranfrage nach § 39 Abs. 6", "TOP 5", "Tagesordnungspunkt 5",
    "Tempo 30 auf der Venloer Straße", "Linie 13", "Kosten 1.000 EUR", "Sitzung 12:30 Uhr", "Drucksache 1234/2026",
    "AN/1234/2026", "(Venloer Straße) – Nr. 6336/2026", "2. Nachtrag", "2. geänderte Fassung", "am 12.03.2026",
    "12. März 2026", "Bebauungsplan 5843/03", "Bebauungsplan 61589/03 (61589.03.000.00.T1)", "Ausbau L 84",
    "BAB 57 Lärmschutz", "Aachener Straße, 50931 Köln", "3,5 Mio. €", "500 €", "€ 500", "18 Uhr", "U18-Haltestelle",
    "CO2-Bilanz", "Stadtbezirk 4 (2026)", "Bezirksvertretung 4 (Ehrenfeld)", "Straße des 17. Juni", "Anlage 3",
    "Sanierung 2026-2028", "Haushaltsjahr 2026/27", "https://example.invalid/papers/123", "Stra&#223;e",
    "Weihnachtsmarkt 2026", "Sommerfest im Park 2026", "Spielplatz 2026", "Radweg 2025", "Monitoring 2025",
    "Maßnahmen in Raderberg – 6,5 Mio. €", "Sperrung der Venloer Straße zwischen 2026 und 2028", "12 Bäume",
    "Bürgeranfrage zum 1. FC Köln", "Abstimmung 12:3"])
def test_maske_positivliste_laesst_bekanntes_stehen(titel):
    """Prüfung r20a, dritte Korrektur: Zahlen in bekannten Zusammenhängen (_BEKANNT) bleiben stehen, auch hinter
    Straßennamen und Wörtern mit Straßen-Endung: Jahreszahlen sind in Köln keine Hausnummer (vorher wurde
    „Weihnachtsmarkt 2026“ und „Stadtbezirk 4 (2026)“ gekürzt), Beträge ebenso; eine Menge mit Einheit direkt hinter
    der Straße („Raderberg – 3 Bäume“) könnte eine Hausnummer sein und fällt weiter weg."""
    m = maske.Maske({"1/2026"}, strassen=_verzeichnis())
    assert m(titel, "1/2026") == titel and not _pruefend(m).offen(titel, "1/2026")


@pytest.mark.parametrize("titel", ["Raum 12", "Az. 12", "Haus 2 der Gesamtschule", "Aachener Straße Nord 12",
                                   "Neumarkt (% 20)", "Musterweg (* 12)", "Kita 3", "Handlungsfeld 3",
                                   "Raderberg – 3 Bäume", "Venloer Straße 2. Nachtrag"])
def test_maske_positivliste(titel):
    """Prüfung r20a, dritte Korrektur: In Titeln der Maske fällt jede Zahl außerhalb bekannter Zusammenhänge weg, auch
    wo sie keine Hausnummer ist (Abwägung zugunsten des Datenschutzes; das Original bleibt über den Link erreichbar)."""
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "L 84", "BAB 57"])
    aus = m(titel, "1/2026")
    assert maske.OHNE_NR in aus and not _zahlen(aus) and m(titel, "2/2026") == titel, aus


@pytest.mark.parametrize("titel, erwartet", [
    ("Venloer Straße 123 – 2. Änderung", "Venloer Straße {o} – 2. Änderung"),
    ("(Venloer Straße 12) – Nr. 6336/2026", "(Venloer Straße {o}) – Nr. 6336/2026"),
    ("Im Park 114 + 78 – Nr. 3033/2029 – 32 Bäume", "Im Park {o} – Nr. 3033/2029 – 32 Bäume"),
    ("Venloer Straße 12 – 3,5 Mio. €", "Venloer Straße {o} – 3,5 Mio. €"),
    ("Venloer Straße 12, 18 Uhr", "Venloer Straße {o}, 18 Uhr"),
    ("Venloer Straße 12 o. 14", "Venloer Straße {o} o. {o}")])
def test_maske_weniger_ueberkuerzung(titel, erwartet):
    """Prüfung r20a, dritte Korrektur: Hinter einer Hausnummer setzt sich die Liste nicht in eine Ordnungszahl, einen
    Betrag oder eine Menge mit Einheit oder eine Drucksache fort (vorher „… [Hausnummer ausgelassen]. Änderung“, „Nr.
    [Hausnummer ausgelassen]/[Hausnummer ausgelassen]“); „o.“ ist kein Zusatz der Hausnummer."""
    m = maske.Maske({"1/2026"}, strassen=_verzeichnis())
    assert m(titel, "1/2026") == erwartet.format(o=maske.OHNE_NR)


FUNDSTELLEN_R20A3 = [
    "Beschwerden über Lärm Aachener Straße 1175, Hinterhof der großen Wohnanlage – Anfrage der Fraktion Die Linke",
    "Parksituation Venloer Straße 12 (Wohnanlage mit Tiefgarage und Hof) – Antrag der SPD-Fraktion",
    "[Testdaten] Lärmschutz Aachener Straße 5, 7, 8, 5a, 7a, 8a, 5b, 7b und 8b – Antrag der SPD-Fraktion"]


@pytest.mark.parametrize("titel", FUNDSTELLEN_R20A3)
def test_fundstelle_im_zusammenhang_des_titels(titel):
    """Prüfung r20a, dritte Korrektur: Die Fundstelle der Einreichenden (actors._segments: 40 Zeichen vor „Antrag“ oder
    „Anfrage“) beginnt hinter der Straße; allein maskiert blieb die Nummer stehen. Maske.ausschnitt überträgt die
    Ersetzungen des ganzen Titels: Der Ausschnitt ist ein Teil des maskierten Titels und ohne Nummer, auch mit einem
    Zusatz wie „ (Vorlagenart: …)“."""
    from pipeline import actors
    m = maske.Maske({"1/2026"}, strassen=["Aachener Straße", "Venloer Straße"])
    voll = m(titel, "1/2026")
    nummern = _zahlen(titel)
    segmente = [titel[a:b].strip() for a, _, b in actors._segments(titel)]
    assert segmente and any(_zahlen(s) for s in segmente)
    for seg in segmente:
        aus = m.ausschnitt(seg, titel, "1/2026")
        assert aus in voll and not _zahlen(aus) & nummern, (seg, aus)
        mit = m.ausschnitt(f"{seg} (Vorlagenart: Antrag nach § 3 der Geschäftsordnung)", titel, "1/2026")
        assert mit.startswith(aus) and mit.endswith("(Vorlagenart: Antrag nach § 3 der Geschäftsordnung)"), mit
        assert m.ausschnitt(seg, titel, "2/2026") == seg
    # Ausschnitt außerhalb des Titels: für sich maskiert
    assert m.ausschnitt("vor Haus 12", titel, "1/2026") == f"vor Haus {maske.OHNE_NR}"


def test_maske_laufzeit_ungewoehnliche_titel():
    """Prüfung r20a, dritte Korrektur: Verkettete Fälle enden nach höchstens RUNDEN Runden (danach blendet der Rückfall
    jede Ziffernfolge mit bis zu vier Stellen aus), Straßen-Endung und Positivliste sind an den Wortanfang gebunden
    (vorher 22 s für „Musterstraße (1) und 2) und 3) …“ mit 5 kB, 3 s für ein Wort aus 5 000 Buchstaben)."""
    m = maske.Maske({"1/2026"}, strassen=_verzeichnis())
    pruefend = _pruefend(m)
    for titel in ["Musterstraße (1) und " + " und ".join(f"{i})" for i in range(2, 900)), "a" * 5000 + "straße 12",
                  "straße" * 800 + " 12", "1" * 5000, "1." * 2500, "Venloer Straße " + "12 " * 1500]:
        start = time.perf_counter()
        aus = m(titel, "1/2026")
        assert time.perf_counter() - start < 3, titel[:40]
        assert not pruefend.offen(aus, "1/2026") and not maske.restzahlen(aus)


def test_maske_zufall_mit_orakel():
    """Prüfung r20a, dritte Korrektur (Testqualität): erfundene Titel aus Namen des Straßenverzeichnisses, Lagewörtern,
    Listen, Klammern, Nummer vor oder hinter der Straße und bekannten Zusammenhängen. Orakel unabhängig von der Maske:
    Jede eingesetzte Hausnummer (dreistellig, keine Jahreszahl) fehlt danach als Ziffernfolge, jeder bekannte
    Zusammenhang („§ 24“, „1234/2026“, „12.03.2026“, nicht direkt hinter der Straße auch „2. Nachtrag“) steht
    unverändert darin."""
    namen = [n for n in _verzeichnis() if not re.search(r"\d", n)]
    m = maske.Maske({"1/2026"}, strassen=namen)
    pruefend = _pruefend(m)
    rnd = random.Random(2027)
    lage = ["", "vor ", "am Haus ", "Höhe ", "in der Nähe von ", "Einfahrt ", "Nr. ", "Hausnummer ", "bei der ",
            "Grundstück ", "im Bereich "]
    liste = ["", " und {k}", " bis {k}", "/{k}", " (gerade) und {k}", ", {k}", " o. {k}", " [{k}]", " … {k}"]
    bekannt = ["", " (§ 24 GO NRW)", " – Drucksache 1234/2026", ", Sitzung am 12.03.2026", " – 2. Nachtrag"]
    for _ in range(3000):
        name = rnd.choice(namen)
        n, k = (str(x) for x in rnd.sample(range(100, 1000), 2))
        nummer = f"{rnd.choice(lage)}{n}{rnd.choice(liste).format(k=k)}"
        kern = rnd.choice([f"{name} {nummer}", f"{nummer} {name}", f"{nummer} der {name}", f"{name}, {nummer}",
                           f"({name} {nummer})", f"{nummer}, {name}"])
        # direkt hinter dem Straßennamen kann „2. Nachtrag“ eine Hausnummer sein (fällt weg, test_maske_positivliste)
        zusatz = rnd.choice(bekannt[:3] if kern.endswith(name) else bekannt)
        titel = f"Eingabe: {kern}{zusatz}"
        aus = m(titel, "1/2026")
        assert not _zahlen(aus) & {n, k}, (titel, aus)
        assert aus.endswith(zusatz) and not pruefend.offen(aus, "1/2026"), (titel, aus)


def test_maske_name_in_baumform_wie_einfache_alternative():
    """Prüfung r20a, dritte Korrektur (Testqualität): Das Muster in Baumform (_namen_muster) urteilt wie eine einfache
    Alternative derselben Namensteile (längere Namen zuerst), für Treffer und für Nicht-Treffer: Namen vor einer Zahl,
    abgeschnittene und verlängerte Namen, Namen in anderer Schreibung."""
    namen = [n for n in _verzeichnis() if not re.search(r"\d", n)]
    baum = re.compile(rf"(?:{maske._namen_muster(namen)})", re.I)
    alternative = re.compile("|".join("".join(maske._name_atome(n))
                                      for n in sorted(set(namen), key=len, reverse=True)), re.I)
    rnd = random.Random(5)
    proben = []
    for name in rnd.sample(namen, 1500):
        proben += [f"{name} 12", name[:-1], name[:max(1, len(name) // 2)] + " 12", name + "x 12",
                   name.replace("-", " ") + " 12", name.replace("St.", "St. ") + " 12", name.upper() + " 12"]
    for probe in proben:
        a, b = baum.match(probe), alternative.match(probe)
        assert (a and a.group()) == (b and b.group()), probe


def _r20a3_einfuegen():
    """Erfundene Eingaben und verbundene Vorlagen der dritten Korrektur; liefert (Straße, Fälle, ungekürzte Texte)."""
    strasse, nr, xy = _lage()
    a, b = nr[0], nr[1]
    eingabe = _vorlage("r3e", "2900/2026", OHNE_ORT, art=EINGABE)
    faelle = [("r3a", "2901/2026", f"[Testdaten] Poller vor Nr. {a}/{b} in der {strasse}", EINGABE, {}),
              ("r3b", "2902/2026", f"[Testdaten] {strasse}, vor der {a}", EINGABE, {}),
              ("r3c", "2903/2026", f"[Testdaten] {strasse} im Bereich {a}-{b}", EINGABE, {}),
              ("r3d", "2904/2026", f"[Testdaten] {strasse} am Haus {a}", EINGABE, {}),
              ("r3f", "2905/2026", f"[Testdaten] Parkverbot {a}, {strasse}", EINGABE, {}),
              ("r3g", "2906/2026", f"[Testdaten] Lärm {strasse} {a} (gerade) und {b}", EINGABE, {}),
              ("r3h", "2907/2026", f"[Testdaten] Lärmschutz {strasse} {a}, {b}, 8, 5a, 7a, 8a, 5b, 7b und 8b – Antrag "
                                   f"der SPD-Fraktion", "Antrag nach § 3 der Geschäftsordnung des Rates",
               {"relatedPaper": [_id("r3e")]}),
              ("r3i", "2908/2026", "[Testdaten] Lärm am Kiosk, Hausnummer zwölf", EINGABE,
               {"location": [{**_ort("r3i", f"{strasse} {a}½", xy[0]), "description": "Am Hof ⒓, Venloer Straße 3¹"}]}),
              ("r3j", "2909/2026", "[Testdaten] Stellungnahme der Verwaltung", "Stellungnahme der Verwaltung",
               {"superordinatedPaper": [_id("r3i")]}),
              ("r3k", "2910/2026", f"[Testdaten] Mitteilung zur Eingabe {strasse}", "Mitteilung",
               {"superordinatedPaper": [_id("r3a")]})]
    vorlagen = [eingabe] + [_vorlage(k, ref, t, art=art, **f) for k, ref, t, art, f in faelle]
    vorlagen[1]["subordinatedPaper"] = [_id("r3k")]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in vorlagen)
    # Ergebnis der Beratung mit Anschrift (wörtlich aus agendaItem.result, bisher weder maskiert noch geprüft)
    with open(config.BERATUNGEN, "a", encoding="utf-8") as f:
        f.write(json.dumps({"uri": f"{B}/consultations/fp-r3a",
                            "meeting": {"uri": f"{B}/meetings/fp-r3", "name": "Rat", "cancelled": False,
                                        "startDate": "2026-10-20T17:00:00+02:00"},
                            "agendaItem": {"uri": f"{B}/meetings/fp-r3/top/1", "number": "1", "name": "Poller",
                                           "result": f"Ortstermin vor Haus {b} beschlossen", "public": True}},
                           ensure_ascii=False) + "\n")
    roh = [f"Nr. {a}/{b}", f"vor der {a}", f"Bereich {a}-{b}", f"am Haus {a}", f"Parkverbot {a}", f"{a} (gerade)",
           f"(gerade) und {b}", f"{b}, 8, 5a", "zwölf", f"Haus {b} beschlossen", "½", "⒓", "¹"]
    return strasse, {ref: t for _, ref, t, _, _ in faelle}, roh


def test_dritte_korrektur_ende_zu_ende(testdaten, monkeypatch, capsys):
    """Prüfung r20a, dritte Korrektur, Ende zu Ende mit erfundenen Vorlagen (wie die Prüfung: 2901 bis 2907/2026):
    „vor Nr. 5/7“, „vor der 5“, „im Bereich 5-7“, „am Haus 5“, „Parkverbot 5, …straße“, „5 (gerade) und 7“, ein Antrag
    über relatedPaper zu einer Eingabe mit Fundstelle der Einreichenden hinter der Straße, eine Hausnummer in Worten, eine
    Ortsangabe der Stadt mit „½“, „⒓“ und „¹“ samt vererbender Stellungnahme, ein Ergebnis der Beratung mit Anschrift und
    eine Folgevorlage. In keiner Datei unter data/export (Suche, GeoJSON, Gebietsdateien, Feeds, Audits, Stichproben)
    steht eine dieser Nummern; check meldet nichts. Gegenprobe: dieselben Texte ungekürzt in Suche, Gebietsdatei
    (Fundstelle, Titel der Folgevorlage, Ergebnis) oder Feed meldet check (vorher kein Befund)."""
    strasse, titel, roh = _r20a3_einfuegen()
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    assert set(titel) <= maske.aus_db(db).refs
    assert db.execute("SELECT street, description FROM location WHERE id = ?", (f"{B}/locations/fp-r3i",)).fetchone() \
        == (strasse, "Am Hof, Venloer Straße")
    base = config.EXPORT / config.STADT
    dateien = [p for p in config.EXPORT.rglob("*") if p.is_file() and p.suffix in (".json", ".geojson", ".tsv", ".xml",
                                                                                    ".ics", ".csv")]
    assert any(p.suffix == ".xml" for p in dateien)
    for p in dateien:
        text = p.read_text(encoding="utf-8")
        assert not [r for r in roh if r in text], (p, [r for r in roh if r in text])
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2907/2026" in f.read_text())
    antrag = next(p for p in json.loads(gebiet.read_text())["papers"] if p["reference"] == "2907/2026")
    fund = [o["evidence"] for o in antrag["originators"] if o.get("evidence")]
    assert fund and all(x in antrag["name"] for x in fund), fund
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    assert erg["untersucht"]["feeds"] > 0 and erg["untersucht"]["verbundene_titel"] > 0

    def befund(pfad, alt, neu):
        text = pfad.read_text(encoding="utf-8")
        assert alt in text, (pfad, alt)
        pfad.write_text(text.replace(alt, neu), encoding="utf-8")
        b = check.datenschutz(db)["befunde"]
        pfad.write_text(text, encoding="utf-8")
        return b

    a = _lage()[1][0]
    gekuerzt = f"{strasse} am Haus {maske.OHNE_NR}"
    for pfad in (base / "suche.json", base / "vorlagen.geojson"):   # Zahl ohne Straße davor: vorher kein Befund
        b = befund(pfad, gekuerzt, f"{strasse} am Haus {a}")
        assert len(b) == 1 and "Hausnummern in Titeln oder Ortsnamen" in b[0] and b[0].endswith("z. B. 2904/2026"), b
    b = befund(gebiet, json.dumps(fund[0], ensure_ascii=False)[1:-1],
               json.dumps(fund[0].replace(maske.OHNE_NR, a, 1), ensure_ascii=False)[1:-1])
    assert len(b) == 1 and "2907/2026" in b[0], b
    gebiet_a = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2901/2026" in f.read_text())
    b = befund(gebiet_a, f"Ortstermin vor Haus {maske.OHNE_NR}", f"Ortstermin vor Haus {_lage()[1][1]}")
    assert len(b) == 1 and "2901/2026" in b[0], b
    feed = base / "feeds" / "vorlagen" / f"{export.slug('2901/2026')}.xml"
    b = befund(feed, f"Ortstermin vor Haus {maske.OHNE_NR}", f"Ortstermin vor Haus {_lage()[1][1]}")
    assert len(b) == 1 and "2901/2026" in b[0], b
    # Maske ohne Positivliste (Stand der zweiten Korrektur): die Nummern bleiben stehen, check meldet sie jetzt
    with monkeypatch.context() as mp:
        mp.setattr(maske, "_restzahl_spannen", lambda text: [])
        export.export()
        capsys.readouterr()
        zeilen = json.loads((base / "suche.json").read_text())["rows"]
        assert f"am Haus {a}" in " ".join(r[1] for r in zeilen)
    erg = check.datenschutz(db)
    m = maske.aus_db(db)
    db.close()
    b = [x for x in erg["befunde"] if "Hausnummern in Titeln oder Ortsnamen" in x]
    assert len(b) == 1, erg["befunde"]
    assert {"2902/2026", "2903/2026", "2904/2026", "2905/2026", "2906/2026"} <= {r[0] for r in zeilen
                                                                                 if m.offen(r[1], r[0])}


# --- Entscheidung 13.11.2026 (1): Gremium und Vorlagenart als Ausgangspunkt der Titelmaske ---------------------------

def _bab(p):
    """Vorlage nur im Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden beraten (Organisation der Testdaten)."""
    p["consultation"][0]["organization"] = [f"{B}/organizations/bab"]
    return p


def test_titelmaske_ueber_gremium_und_vorlagenart(testdaten, monkeypatch, capsys):
    """Entscheidung 13.11.2026 (1): Vorlagen ohne Hauskoordinate nur über das Gremium (Ausschuss für Bürgerbeteiligung,
    Anregungen und Beschwerden) oder eine nicht erkennbare Vorlagenart sind Ausgangspunkte der Titelmaske, samt
    verbundenen Vorlagen; auch bei einer Drucksache in anderem Schema (Gründe unabhängig von ihrer Reihenfolge in
    geocode.punkt_ausschluss). Vorher nur ein Hinweis in check („ohne_punkt_ohne_maske“), die Hausnummer stand im Titel.
    Orakel: die Ziffernfolge selbst in jeder Datei unter data/export. Übrig bleibt als Hinweis nur eine Drucksache in
    anderem Schema mit erkannter Vorlagenart außerhalb des Ausschusses (Entscheidung offen). Das Log von build nennt die
    zusätzlichen Vorlagen und gekürzten Titel. Gegenprobe: Folgt die Maske der Regel nicht, meldet check die Vorlagen
    mit Grund „gremium“ oder „vorlagenart“ außerhalb der Titelmaske (Fehler im Aufbau)."""
    strasse, nr, _ = _lage()
    a, b, c = nr
    faelle = {
        "2950/2026": _bab(_vorlage("gm", "2950/2026", f"[Testdaten] Sachstand {strasse} am Haus {a}", art="Mitteilung",
                                   subordinatedPaper=[_id("gmf")])),
        "2951/2026": _vorlage("va", "2951/2026", f"[Testdaten] Bank an der {strasse} {a}", art="Bekanntmachung"),
        "2952/2026": _vorlage("vl", "2952/2026", f"[Testdaten] Poller in der {strasse} {b}", art=""),
        "2953/2026": _vorlage("gmf", "2953/2026", f"[Testdaten] Stellungnahme zur {strasse} {b}",
                              art="Stellungnahme der Verwaltung", superordinatedPaper=[_id("gm")]),
        "2954-2026": _bab(_vorlage("dg", "2954-2026", f"[Testdaten] Hinweis zur {strasse} {a}", art="Mitteilung")),
    }
    aussen = _vorlage("dd", "2955-2026", f"[Testdaten] Anlage an der {strasse} {c}", art="Beschlussvorlage")
    kontrolle = _vorlage("ko", "2956/2026", f"[Testdaten] Sitzbänke an der {strasse} {c}")
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in [*faelle.values(), aussen, kontrolle])
    build.build()
    log = capsys.readouterr().out
    zeile = next(z for z in log.splitlines() if z.startswith("Titelmaske über Gremium oder Vorlagenart"))
    assert zeile.endswith(": 5 Vorlagen zusätzlich, davon 5 mit gekürztem Titel"), zeile
    assert strasse not in zeile
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    m = maske.aus_db(db)
    assert set(faelle) <= m.refs and not {"2955-2026", "2956/2026"} & m.refs
    erg = check.datenschutz(db)
    aus = capsys.readouterr().out
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    hinweis = next(z for z in aus.splitlines() if z.startswith("Hinweis (kein Befund): Vorlagen ohne Hauskoordinate"))
    assert "2955-2026" in hinweis and not set(faelle) & set(re.findall(r"\S+/2026|\S+-2026", hinweis)), hinweis
    assert strasse not in hinweis and erg["untersucht"]["ohne_punkt_ohne_maske"] >= 1
    verboten = [f"{strasse} am Haus {a}", f"{strasse} {a}", f"{strasse} {b}"]
    gesehen = {r: 0 for r in faelle}
    for p in config.EXPORT.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".geojson", ".tsv", ".xml", ".ics", ".csv"):
            text = p.read_text(encoding="utf-8")
            assert not [v for v in verboten if v in text], (p, [v for v in verboten if v in text])
            for r in faelle:
                gesehen[r] += r in text
    assert all(gesehen.values()), gesehen
    suche = {r[0]: r[1] for r in json.loads((config.EXPORT / config.STADT / "suche.json").read_text())["rows"]}
    assert suche["2956/2026"].endswith(f"{strasse} {c}") and suche["2955-2026"].endswith(f"{strasse} {c}")
    assert suche["2950/2026"] == f"[Testdaten] Sachstand {strasse} am Haus {maske.OHNE_NR}"
    # Gegenprobe: Maske ohne die Regel (Stand vor dem 13.11.2026) – check meldet die Vorlagen mit Grund „gremium“
    # oder „vorlagenart“ außerhalb der Titelmaske (die Titelprüfung allein sähe sie nicht: nicht in der Maske)
    monkeypatch.setattr(maske, "ausgang_punktregel", lambda p, gremien=(): False)
    export.export()
    capsys.readouterr()
    erg = check.datenschutz(db)
    db.close()
    b_ = [x for x in erg["befunde"] if "nicht in der Titelmaske" in x and "Gremium" in x]
    assert len(b_) == 1 and b_[0].endswith(": 3, z. B. 2950/2026, 2951/2026, 2952/2026"), erg["befunde"]


# --- Nachprüfung der dritten Korrektur: unsichtbare Zeichen zwischen Ziffern, Feeds mit fortgesetztem Titel ----------

def _sichtbar(text):
    """Text, wie Leser:innen ihn sehen (Orakel der Tests, unabhängig von der Maske): ohne weiche Trennzeichen und
    Zeichen ohne Breite, NFKC."""
    import unicodedata
    return unicodedata.normalize("NFKC", re.sub("[\u00ad\u200b-\u200f\u2060-\u2064\ufeff]", "", text))


_MASKEN = []


def _zwei_masken():
    """Zwei Masken mit dem Kölner Verzeichnis: eine maskiert, die andere prüft (offen() auf derselben Instanz ist für
    jedes ihrer Ergebnisse vorab falsch)."""
    if not _MASKEN:
        _MASKEN.extend(maske.Maske({"1/2026"}, strassen=_verzeichnis()) for _ in range(2))
    return _MASKEN


_PRUEFMASKEN = {}


def _pruefend(m):
    """Zweite Maske mit denselben Drucksachen und Straßen wie `m` (Offen (10) der Nachprüfung der dritten Korrektur:
    Maske.__call__ vermerkt offen() für das eigene Ergebnis vorab als falsch; offen(m(x)) auf derselben Instanz sicherte
    nichts zu). Je Drucksachen und Straßen einmal gebaut; in Tests mit geänderten Mustern (monkeypatch) direkt bauen."""
    schluessel = (frozenset(m.refs), tuple(m.strassen))
    if schluessel not in _PRUEFMASKEN:
        _PRUEFMASKEN[schluessel] = maske.Maske(m.refs, strassen=m.strassen)
    return _PRUEFMASKEN[schluessel]


@pytest.mark.parametrize("titel, nummern", [
    ("Venloer Straße 20\u00ad22", "20 22"), ("Eingabe nach § 24 GO NRW: Wupperstraße 98\u00ad100", "98 100"),
    ("Einwohneranfrage: Ampel Im Fichtenhain 20\u00ad22", "20 22"),
    ("Bürgerantrag: Parkverbot Godorfer Hauptstraße 124\u00ad126", "124 126"),
    ("Aachener Straße 1175\u200b1177", "1175 1177"), ("Anregung: Lärm vor Haus 120\u2060122", "120 122"),
    ("Venloer Straße 19\u00ad\u200b21", "19 21"), ("Venloer Straße 12\ufeff14", "12 14"),
    ("Severinstraße 3\u200c5a", "3 5"), ("Lärm 1175\u200d1177 Venloer Straße", "1175 1177")])
def test_maske_unsichtbares_zeichen_zwischen_ziffern(titel, nummern):
    """Nachprüfung der dritten Korrektur: Ein weiches Trennzeichen oder Zeichen ohne Breite zwischen zwei Zifferngruppen
    (Word: Strg+-, kopierter Webtext) ließ beide Gruppen zu einer Zahl verschmelzen; mit fünf und mehr Stellen oder als
    Jahreszahl („98\u00ad100“, „20\u00ad22“) blieb der Titel unverändert, und offen() meldete nichts. Orakel: Weder die einzelnen
    Gruppen noch die verschmolzene Zahl stehen danach im Titel, roh oder so, wie Leser:innen ihn sehen; eine zweite
    Maske meldet den rohen Titel und nicht das Ergebnis."""
    maskierend, pruefend = _zwei_masken()
    aus = maskierend(titel, "1/2026")
    verboten = set(nummern.split()) | {"".join(nummern.split())}
    assert maske.OHNE_NR in aus and not (_zahlen(aus) | _zahlen(_sichtbar(aus))) & verboten, aus
    assert pruefend.offen(titel, "1/2026") and not pruefend.offen(aus, "1/2026"), aus
    assert maskierend(titel, "2/2026") == titel


def test_feed_folgevorlage_setzt_titel_fort(testdaten, capsys):
    """Nachprüfung der dritten Korrektur, Ende zu Ende: Setzt der Titel einer Folgevorlage den Titel der Eingabe fort,
    rückt deren letzte Zahl in einen bekannten Zusammenhang („2. Nachtrag“, „7 Uhr“, „12. hier: …“) und bleibt im Titel
    der Folgevorlage stehen; der ungekürzte Titel der Eingabe steht dann als Teil darin. check._feeds meldete das als
    Befund, den die Maske nicht beheben konnte (Veröffentlichung angehalten). Jetzt kein Befund, auch mit Zeilenende
    und Steuerzeichen im Titel der Folgevorlage (im Feed nach dem Lesen anders geschrieben); die Eingabe selbst
    zeigt ihre Nummer in keinem eigenen Eintrag. Gegenprobe: der ungekürzte Titel in einem eigenen Eintrag oder neben
    einem veränderten Titel der Folgevorlage ist ein Befund. Dazu Eingaben mit weichem Trennzeichen zwischen zwei
    Hausnummern („98\u00ad100“, „20\u00ad22“): in keiner Datei unter data/export stehen die Nummern."""
    strasse = _lage()[0]
    paare = [("n1", "9001/2026", "9002/2026", "[Testdaten] Eingabe: Spielplatz im Musterpark 2", ". Nachtrag"),
             ("n3", "9003/2026", "9004/2026", "[Testdaten] Anregung: Lärm am Kiosk 7", " Uhr morgens – Stellungnahme"),
             ("n5", "9005/2026", "9006/2026", "[Testdaten] Anregung: Halteverbot vor Haus 12",
              ". hier: Stellungnahme der Verwaltung"),
             # Zeilenende und Steuerzeichen im Titel der Folgevorlage: im Feed nach dem Lesen „\n“ und ohne „\x01“
             ("n7", "9007/2026", "9008/2026", "[Testdaten] Anregung: Bank am Brunnen 5",
              ". Nachtrag\r\nStellungnahme\x01 der Verwaltung")]
    vorlagen = []
    for k, ref, folge, titel, fortsetzung in paare:
        vorlagen += [_vorlage(k, ref, titel, art=EINGABE, subordinatedPaper=[_id(f"{k}f")]),
                     _vorlage(f"{k}f", folge, titel + fortsetzung, art="Stellungnahme der Verwaltung",
                              superordinatedPaper=[_id(k)])]
    weich = {"9011/2026": f"[Testdaten] Eingabe nach § 24 GO NRW: {strasse} 98\u00ad100",
             "9012/2026": f"[Testdaten] Einwohneranfrage: Ampel {strasse} 20\u00ad22"}
    vorlagen += [_vorlage(f"w{i}", ref, t, art=EINGABE) for i, (ref, t) in enumerate(weich.items())]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in vorlagen)
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    m = maske.aus_db(db)
    assert {r for _, ref, folge, _, _ in paare for r in (ref, folge)} | set(weich) <= m.refs
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    base = config.EXPORT / config.STADT
    feeds = base / "feeds" / "vorlagen"
    for _, ref, _, titel, fortsetzung in paare[:3]:
        text = (feeds / f"{export.slug(ref)}.xml").read_text(encoding="utf-8")
        gekuerzt = titel[:titel.rindex(" ") + 1] + maske.OHNE_NR
        assert f"Neue Vorlage {ref}: {gekuerzt}" in text and titel + fortsetzung in text, ref
        assert text.count(titel) == text.count(titel + fortsetzung), ref   # nur im Titel der Folgevorlage
    gekuerzt = 0
    for p in config.EXPORT.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".geojson", ".tsv", ".xml", ".ics", ".csv"):
            text = p.read_text(encoding="utf-8")
            sichtbar = _sichtbar(text)
            assert not [r for r in (f"{strasse} 98100", f"{strasse} 2022", "98\u00ad100", "20\u00ad22")
                        if r in sichtbar or r in text], p
            gekuerzt += f"Ampel {strasse} {maske.OHNE_NR}" in sichtbar
    assert gekuerzt >= 3   # Suche, GeoJSON, Gebietsdatei, Feeds: das Orakel sieht die Texte

    def befund(pfad, alt, neu):
        text = pfad.read_text(encoding="utf-8")
        assert alt in text, (pfad, alt)
        pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
        b = check.datenschutz(db)["befunde"]
        pfad.write_text(text, encoding="utf-8")
        return b

    feed = feeds / f"{export.slug('9001/2026')}.xml"
    titel = paare[0][3]
    b = befund(feed, f"Neue Vorlage 9001/2026: {titel[:-1]}{maske.OHNE_NR}", f"Neue Vorlage 9001/2026: {titel}")
    assert len(b) == 1 and "9001/2026" in b[0], b
    b = befund(feed, f"{titel}. Nachtrag", f"{titel}, Nachtrag")
    assert len(b) == 1 and "9001/2026" in b[0], b
    db.close()


# --- Offen (6)–(12) aus der Nachprüfung der dritten Korrektur -------------------------------------------------------

def test_feed_ohne_ungueltige_xml_zeichen():
    """Offen (6): Zeichen, die XML 1.0 nicht erlaubt (Steuerzeichen, U+FFFE, U+FFFF, einzelne Ersatzzeichen U+D800 bis
    U+DFFF), entfernt publish._atom; vorher machte U+FFFE oder U+FFFF in einem Titel den Feed unlesbar und damit für
    check ungeprüft. Orakel: ElementTree liest den Feed, der Text ist ohne diese Zeichen, erlaubte bleiben."""
    import xml.etree.ElementTree as ET
    from pipeline import publish
    roh = "Titel￾ mit￿ Zeichen\ud800 und\udfff\x01 Tab\tEnde é 😀 \u0085 �"
    feed = publish._atom("tag:x", roh, roh, "https://example.invalid/f.xml", "https://example.invalid/",
                         [{"date": "2026-11-01", "id": "x#1", "title": roh, "summary": roh, "link": "https://example.invalid/"}])
    wurzel = ET.fromstring(feed.encode("utf-8"))
    titel = wurzel.findtext("{http://www.w3.org/2005/Atom}title")
    assert titel == "Titel mit Zeichen und Tab\tEnde é 😀 \u0085 �", repr(titel)
    assert publish.xml_text(roh) == titel


def _befund_nach(db, pfad, alt, neu):
    """Befunde von check.datenschutz, nachdem `alt` in `pfad` einmal durch `neu` ersetzt ist (Datei danach wie vorher)."""
    text = pfad.read_text(encoding="utf-8")
    assert alt in text, (pfad, alt)
    pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
    try:
        return check.datenschutz(db)["befunde"]
    finally:
        pfad.write_text(text, encoding="utf-8")


def test_feed_mit_ungueltigem_zeichen_ende_zu_ende(testdaten, capsys):
    """Offen (6), Ende zu Ende: Eine Eingabe mit U+FFFE und U+FFFF im Titel ergibt lesbare Feeds ohne die Zeichen und
    ohne Hausnummer; check meldet nichts. Gegenprobe: der ungekürzte Titel im Feed ist ein Befund (vorher in derselben
    Form verglichen: dieselbe Regel publish.xml_text), ein unlesbarer Feed ebenso (vorher übergangen, ohne Zählung)."""
    import xml.etree.ElementTree as ET
    strasse, nr, _ = _lage()
    titel = f"[Testdaten] Anregung: Bank an der￾ {strasse} {nr[0]}￿"
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.write(json.dumps(_vorlage("xf", "2970/2026", titel, art=EINGABE), ensure_ascii=False) + "\n")
    build.build()
    export.export()
    capsys.readouterr()
    feeds = sorted((config.EXPORT / config.STADT).rglob("*.xml"))
    for p in feeds:
        ET.parse(p)   # jeder Feed lesbar
        text = p.read_text(encoding="utf-8")
        assert "￾" not in text and "￿" not in text and f"{strasse} {nr[0]}" not in text, p
    feed = config.EXPORT / config.STADT / "feeds" / "vorlagen" / f"{export.slug('2970/2026')}.xml"
    gekuerzt = f"Bank an der {strasse} {maske.OHNE_NR}"
    assert gekuerzt in feed.read_text(encoding="utf-8")
    db = sqlite3.connect(config.DB)
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["untersucht"]["feeds"] > 0, erg
    b = _befund_nach(db, feed, gekuerzt, f"Bank an der {strasse} {nr[0]}")
    assert len(b) == 1 and "2970/2026" in b[0], b
    b = _befund_nach(db, feed, "</feed>", "</fee")
    db.close()
    assert len(b) == 1 and "nicht lesbar" in b[0] and "2970-2026.xml" in b[0], b


@pytest.mark.parametrize("titel, ausschnitt", [
    ("Lärm Venloer Straße Hausnummer zwölf – Antrag der SPD-Fraktion", "zwölf – Antrag der SPD-Fraktion"),
    ("Lärm Venloer Straße Hausnummer zwölf – Antrag der SPD-Fraktion", "zwölf"),
    ("Lärm am Kiosk, Nr. elf – Anfrage der Fraktion Die Linke", "elf – Anfrage der Fraktion Die Linke"),
    ("Venloer Straße, Hausnummer (drei) – Antrag der FDP-Fraktion", "drei) – Antrag der FDP-Fraktion")])
def test_ausschnitt_ohne_ziffer_im_titel_der_maske(titel, ausschnitt):
    """Offen (7): Eine Fundstelle ohne Ziffer und ohne Wort wie „Hausnummer“ gab Maske.ausschnitt unverändert zurück,
    bevor die Ersetzungen des ganzen Titels übertragen wurden; begann sie zwischen „Hausnummer“ und einer Hausnummer in
    Worten, blieb das Zahlwort stehen. Jetzt gilt die Übertragung für jede Fundstelle eines Titels der Maske. Orakel:
    das Zahlwort selbst; andere Drucksachen und Teile ohne Ersetzung bleiben unverändert."""
    m = maske.Maske({"1/2026"}, strassen=["Venloer Straße"])
    zahlwort = re.compile(r"(?i)\b(?:zwölf|elf|drei)\b")
    assert zahlwort.search(ausschnitt) and ausschnitt in titel
    aus = m.ausschnitt(ausschnitt, titel, "1/2026")
    assert not zahlwort.search(aus) and maske.OHNE_NR in aus and aus in m(titel, "1/2026"), aus
    assert m.ausschnitt(ausschnitt, titel, "2/2026") == ausschnitt
    assert m.ausschnitt(titel.split(" – ")[1], titel, "1/2026") == titel.split(" – ")[1]


ORDNUNG_R20A3N = [
    # (Titel, Nummern, die danach fehlen müssen, Teile, die stehen bleiben)
    ("Poller vor Haus 12. Teilweise gesperrt", "12", ""), ("Einfahrt 12. Termine folgen", "12", ""),
    ("Kiosk Nummer 12. Preise zu hoch", "12", ""), ("vor Haus 12. Vorlagen fehlen", "12", ""),
    ("Venloer Straße, am Haus 12. Phasenweise Sperrung", "12", ""), ("vor Haus 12. Teile der Hecke", "12", ""),
    ("Venloer Straße 123 – 2. Teilweise", "123 2", ""),
    ("vor Haus 12 – 2. Nachtrag", "12", "2. Nachtrag"), ("vor Haus 12 – Sitzung am 12. März 2026", "", "12. März"),
    ("vor Haus 7 – des 2. Nachtrags", "7", "2. Nachtrags"), ("vor Haus 7 – 3. Nachträge", "7", "3. Nachträge"),
    ("vor Haus 7 – 2. Änderungen", "7", "2. Änderungen"), ("vor Haus 7 – 5. Sitzungen", "7", "5. Sitzungen"),
    ("vor Haus 7 – 1. Änderungssatzung", "7", "1. Änderungssatzung"),
    ("vor Haus 7 – 18. Wahlperiode", "7", "18. Wahlperiode"), ("vor Haus 7 – 1. FC Köln", "7", "1. FC"),
    ("Venloer Straße 123 – 2. Änderungen", "123", "2. Änderungen")]


@pytest.mark.parametrize("titel, weg, bleibt", ORDNUNG_R20A3N)
def test_ordnungswort_am_wortende(titel, weg, bleibt):
    """Offen (11): Die Wörter aus maske._ORDNUNG galten auch als Wortanfang („Teilweise“, „Termine“, „Preise“,
    „Vorlagen“): Eine Nummer mit Punkt vor einem solchen Wort blieb in Titeln der Maske stehen. Jetzt am Wortende
    gebunden, mit den nötigen Formen (Genitiv, Mehrzahl wie „Änderungen“, „Sitzungen“, „Nachträge“, Zusammensetzungen mit
    Fugen-s wie „Änderungssatzung“). Orakel: die Ziffernfolgen selbst und die Teile, die stehen bleiben."""
    m = maske.Maske({"1/2026"}, strassen=["Venloer Straße"])
    aus = m(titel, "1/2026")
    assert not _zahlen(aus) & set(weg.split()), aus
    assert bleibt in aus and not _pruefend(m).offen(aus, "1/2026"), aus


def test_strassen_endung_am_wortanfang():
    """Offen (12): _WORTANFANG schloss nur einen Buchstaben davor aus (Punkt und Bindestrich gehören zu \\W), anders als
    der Kommentar sagte; jede Stelle hinter „-“ oder „.“ war ein neuer Anfang, und Wörter aus vielen Teilen kosteten
    quadratisch Zeit („a-a-a-…“ mit 5 000 Zeichen 0,8 s je Durchlauf). Jetzt wie im Kommentar: kein Buchstabe, Punkt oder
    Bindestrich davor. Dieselben Hausnummern fallen weg (die Straßen-Endung darf Punkt und Bindestrich enthalten,
    beginnt also am Anfang des ganzen Worts); die Probe (nur Buchstaben im Wort) bleibt bei „kein Buchstabe davor“."""
    rx = re.compile(maske.SUFFIX, re.I)
    for text, start in (("Konrad-Adenauer-Straße", 0), ("St.-Apern-Str.", 0), ("x Musterweg", 2), ("(Neumarkt", 1)):
        assert [mt.start() for mt in rx.finditer(text)] == [start], text
    assert not rx.match("Konrad-Adenauer-Straße", 7) and not rx.match("St.-Apern-Str.", 4)
    m = maske.Maske({"1/2026"}, strassen=[])
    for titel, nummern in (("Konrad-Adenauer-Straße 12", "12"), ("St.-Apern-Str. 5", "5"),
                           ("Musterweg 12a-Hauptstraße 5", "12 5"), ("Anregung: Pkw-Parkplatz 7 und 9", "7 9")):
        aus = m(titel, "1/2026")
        assert not _zahlen(aus) & set(nummern.split()), (titel, aus)
    for titel in ("a-" * 2500 + "straße 12", "a." * 2500 + "weg 12", "Ab-" * 1700 + "Platz 3"):
        t = time.perf_counter()
        aus = m(titel, "1/2026")
        assert time.perf_counter() - t < 1, titel[:20]
        assert not _zahlen(aus) and not _pruefend(m).offen(aus, "1/2026"), titel[:20]


def _beratung(cons, sitzung, top, nummer="1", ergebnis=None, name="Rat", start="2026-10-20T17:00:00+02:00"):
    """Zeile in beratungen.jsonl (Beratung → Sitzung und Tagesordnungspunkt, wie sessionnet.beratungen)."""
    return {"uri": cons, "meeting": {"uri": sitzung, "name": name, "startDate": start, "cancelled": False},
            "agendaItem": {"uri": top, "number": nummer, "name": "Punkt", "result": ergebnis, "public": True}}


def test_ergebnis_je_tagesordnungspunkt(testdaten, capsys):
    """Offen (8): Ergebnisse wurden je Vorlage maskiert, nicht je Tagesordnungspunkt; beriet eine Vorlage außerhalb der
    Maske (ohne Beziehung, ohne Stichwort im Titel) denselben Punkt wie eine Eingabe, zeigte sie das Ergebnis ungekürzt
    (Gebietsdatei, Feed, Datenpaket). Jetzt gilt: Ist eine Vorlage eines Tagesordnungspunkts in der Maske, wird sein
    Ergebnis bei jeder Vorlage maskiert, die ihn zeigt, und mit ihm jedes andere Ergebnis dieser Vorlage
    (Maske.drucksache_ergebnisse; vorher blieb ein anderer Punkt unverändert, siehe
    test_ergebnis_gleicher_text_auf_zweitem_punkt). Orakel: die Ziffernfolge in jeder Datei. Gegenprobe: das ungekürzte
    Ergebnis in Gebietsdatei oder Feed der Vorlage außerhalb der Maske ist ein Befund (vorher prüfte check Ergebnisse
    nur mit der Drucksache der Vorlage selbst)."""
    strasse, nr, _ = _lage()
    a, b = nr[0], nr[1]
    s, top1, top2 = f"{B}/meetings/fp-t", f"{B}/meetings/fp-t/top/1", f"{B}/meetings/fp-t/top/2"
    eingabe = _vorlage("te", "2980/2026", OHNE_ORT, art=EINGABE)
    andere = _vorlage("tq", "2981/2026", "[Testdaten] Sammelvorlage Verkehr", art="Beschlussvorlage")
    andere["consultation"].insert(0, {"id": f"{B}/consultations/fp-tq2", "role": "Beratung",
                                      "organization": [f"{B}/organizations/avr"], "authoritative": False})
    ergebnis1, ergebnis2 = f"Ortstermin vor Haus {a} beschlossen", f"Ortstermin vor Haus {b} vertagt"
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in (eingabe, andere))
    with open(config.BERATUNGEN, "a", encoding="utf-8") as f:
        for z in (_beratung(f"{B}/consultations/fp-te", s, top1, "1", ergebnis1),
                  _beratung(f"{B}/consultations/fp-tq", s, top1, "1", ergebnis1),
                  _beratung(f"{B}/consultations/fp-tq2", s, top2, "2", ergebnis2)):
            f.write(json.dumps(z, ensure_ascii=False) + "\n")
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    m = maske.aus_db(db)
    assert "2980/2026" in m.refs and "2981/2026" not in m.refs and m.tops.get(top1) == "2980/2026"
    base = config.EXPORT / config.STADT
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2981/2026" in f.read_text())
    q = next(p for p in json.loads(gebiet.read_text())["papers"] if p["reference"] == "2981/2026")
    assert {x["result"] for x in q["process"]} == {f"Ortstermin vor Haus {maske.OHNE_NR} beschlossen",
                                                   f"Ortstermin vor Haus {maske.OHNE_NR} vertagt"}
    assert "agenda_item_id" not in q["process"][0]   # Datenmodell unverändert
    for p in config.EXPORT.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".geojson", ".tsv", ".xml", ".ics", ".csv"):
            text = p.read_text(encoding="utf-8")
            assert f"vor Haus {a} beschlossen" not in text and f"vor Haus {b} vertagt" not in text, p
    feed = base / "feeds" / "vorlagen" / f"{export.slug('2981/2026')}.xml"
    assert f"Ortstermin vor Haus {maske.OHNE_NR} vertagt" in feed.read_text(encoding="utf-8")
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    b_ = _befund_nach(db, feed, f"Ortstermin vor Haus {maske.OHNE_NR} beschlossen", ergebnis1)
    assert len(b_) == 1 and "2981/2026" in b_[0], b_
    # in der Gebietsdatei nur bei der Vorlage außerhalb der Maske (die Eingabe steht in derselben Datei)
    daten = json.loads(gebiet.read_text())
    for x in next(p for p in daten["papers"] if p["reference"] == "2981/2026")["process"]:
        x["result"] = ergebnis1 if x["result"].endswith("beschlossen") else x["result"]
    b_ = _befund_nach(db, gebiet, gebiet.read_text(), json.dumps(daten, ensure_ascii=False, separators=(",", ":")))
    assert len(b_) == 1 and b_[0].endswith(": 1, z. B. 2981/2026"), b_
    db.close()


def test_ergebnis_gleicher_text_auf_zweitem_punkt(testdaten, capsys):
    """Fehlalarm aus Offen (8): Eine Vorlage außerhalb der Maske berät denselben Tagesordnungspunkt wie eine Eingabe
    und einen zweiten Punkt allein, mit demselben Ergebnis (oder einem längeren, das es enthält). Vorher maskierte export
    nur das Ergebnis des gemeinsamen Punkts, check verglich aber jeden Eintrag der Vorlage mit dem ungekürzten Text und
    meldete den zweiten Punkt als Befund, den die Maske nicht beheben konnte (hielt die Veröffentlichung an). Jetzt
    laufen alle Ergebnisse einer Vorlage mit einem Tagesordnungspunkt der Maske durch die Maske
    (Maske.drucksache_ergebnisse, eine Funktion für export und check). Orakel: die Ziffernfolge „3 und 4“ in jeder Datei
    und die Befunde von check. Gegenproben: eine Vorlage ohne Punkt der Maske behält das Ergebnis ungekürzt; das
    ungekürzte Ergebnis des zweiten Punkts in Feed oder Gebietsdatei ist ein Befund."""
    beratungen = []
    vorlagen = [_vorlage("ge", "2880/2026", OHNE_ORT, art=EINGABE)]
    roh, laenger, ordnung = ("Beschluss gemäß Anlagen 3 und 4", "Beschluss gemäß Anlagen 3 und 4 mit Änderungen",
                             "Beschluss gemäß Anlagen 3 und 4. Änderung abgelehnt")
    # 2881: derselbe Text auf beiden Punkten; 2883: ein längerer auf dem zweiten; 2885: ein längerer, in dem die 4 vor
    # „Änderung“ in einem bekannten Zusammenhang steht (die Maske lässt ihn stehen, wie Offen (1))
    for key, ref, zweites in (("g1", "2881/2026", roh), ("g3", "2883/2026", laenger), ("g5", "2885/2026", ordnung)):
        v = _vorlage(key, ref, f"[Testdaten] Sammelvorlage {key}", art="Beschlussvorlage")
        v["consultation"].append({"id": f"{B}/consultations/fp-{key}b", "role": "Beratung",
                                  "organization": [f"{B}/organizations/avr"], "authoritative": False})
        vorlagen.append(v)
        beratungen += [_beratung(f"{B}/consultations/fp-{key}", f"{B}/meetings/fp-g", f"{B}/meetings/fp-g/top/1",
                                 "1", roh),
                       _beratung(f"{B}/consultations/fp-{key}b", f"{B}/meetings/fp-g{key}",
                                 f"{B}/meetings/fp-g{key}/top/1", "1", zweites, name="Ausschuss für Verkehr",
                                 start="2026-10-27T17:00:00+01:00")]
    beratungen.append(_beratung(f"{B}/consultations/fp-ge", f"{B}/meetings/fp-g", f"{B}/meetings/fp-g/top/1", "1",
                                roh))
    # Gegenprobe: dasselbe Ergebnis bei einer Vorlage ohne Tagesordnungspunkt der Maske
    vorlagen.append(_vorlage("g7", "2887/2026", "[Testdaten] Sammelvorlage Grünflächen", art="Beschlussvorlage"))
    beratungen.append(_beratung(f"{B}/consultations/fp-g7", f"{B}/meetings/fp-g7", f"{B}/meetings/fp-g7/top/1", "1",
                                roh))
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in vorlagen)
    with open(config.BERATUNGEN, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(z, ensure_ascii=False) + "\n" for z in beratungen)
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    m = maske.aus_db(db)
    assert "2880/2026" in m.refs and not {"2881/2026", "2883/2026", "2885/2026", "2887/2026"} & m.refs
    base = config.EXPORT / config.STADT
    maskiert = f"Beschluss gemäß Anlagen 3 und {maske.OHNE_NR}"
    feeds = {r: base / "feeds" / "vorlagen" / f"{export.slug(r)}.xml"
             for r in ("2881/2026", "2883/2026", "2885/2026", "2887/2026")}
    # Orakel: „3 und 4“ ungekürzt nur bei der Vorlage ohne Punkt der Maske und im längeren Text mit „4. Änderung“
    for r in ("2881/2026", "2883/2026"):
        text = feeds[r].read_text(encoding="utf-8")
        assert "3 und 4" not in text and text.count(maskiert) == 2, (r, text)
    assert "3 und 4." in feeds["2885/2026"].read_text(encoding="utf-8")
    assert roh in feeds["2887/2026"].read_text(encoding="utf-8")
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2881/2026" in f.read_text())
    daten = json.loads(gebiet.read_text())
    ergebnisse = {p["reference"]: [x["result"] for x in p["process"]] for p in daten["papers"]
                  if p["reference"] in feeds}
    assert ergebnisse["2881/2026"] == [maskiert, maskiert], ergebnisse
    assert ergebnisse["2883/2026"] == [maskiert, f"{maskiert} mit Änderungen"], ergebnisse
    assert ergebnisse["2885/2026"] == [maskiert, ordnung] and ergebnisse["2887/2026"] == [roh], ergebnisse
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    # Gegenproben: das ungekürzte Ergebnis des zweiten Punkts im Feed bzw. in der Gebietsdatei ist ein Befund
    for r, zweites in (("2881/2026", roh), ("2883/2026", laenger)):
        alt = maskiert if r == "2881/2026" else f"{maskiert} mit Änderungen"
        b_ = _befund_nach(db, feeds[r], alt, zweites)
        assert len(b_) == 1 and b_[0].endswith(f": 1, z. B. {r}"), (r, b_)
        neu = json.loads(gebiet.read_text())
        next(p for p in neu["papers"] if p["reference"] == r)["process"][1]["result"] = zweites
        b_ = _befund_nach(db, gebiet, gebiet.read_text(), json.dumps(neu, ensure_ascii=False, separators=(",", ":")))
        assert len(b_) == 1 and b_[0].endswith(f": 1, z. B. {r}"), (r, b_)
    db.close()


def _ics_ereignisse(pfad):
    """VEVENT-Blöcke von termine.ics als {UID: {Feld: Text}} (Zeilen entfaltet, Text nach RFC 5545 zurückgewandelt;
    eigener Leser des Tests, Zeilenenden „\\r\\n“ wie geschrieben)."""
    text = pfad.read_bytes().decode("utf-8").replace("\r\n ", "")
    out = {}
    for block in text.split("BEGIN:VEVENT")[1:]:
        felder = dict(z.split(":", 1) for z in block.split("END:VEVENT")[0].split("\r\n") if ":" in z)
        out[felder["UID"]] = {k: re.sub(r"\\(.)", lambda x: "\n" if x.group(1) == "n" else x.group(1), v)
                              for k, v in felder.items()}
    return out


def test_sitzungsname_maskiert(testdaten, capsys):
    """Offen (9): Sitzungsnamen standen ungekürzt in Gebietsdateien und Datenpaket (`process[].meeting`), in zeit.json
    (`meetings[].name`) und termine.ics (Beschreibung; Zusammenfassung, wenn das Gremium aus dem Namen stammt), auch
    neben einer Eingabe. Jetzt läuft der Name jeder Sitzung, in der eine Vorlage der Maske beraten wird, durch die Maske,
    überall und bei jeder Vorlage dieser Sitzung; check prüft diese Felder. Orakel: die Ziffernfolge in jeder Datei; eine
    Sitzung ohne Vorlage der Maske bleibt unverändert. Gegenprobe: der ungekürzte Name in zeit.json, termine.ics oder der
    Gebietsdatei einer Vorlage außerhalb der Maske ist ein Befund."""
    from datetime import date, timedelta
    strasse, nr, _ = _lage()
    a, b, c = nr
    tag = (date.today() + timedelta(days=10)).isoformat()
    start = f"{tag}T17:00:00+01:00"
    s1, s2, s3 = (f"{B}/meetings/fp-sn{i}" for i in (1, 2, 3))
    namen = {s1: f"Ortstermin {strasse} {a}", s2: f"Sitzung am Kiosk {strasse} {b}", s3: f"Ortstermin {strasse} {c}"}
    vorlagen = [_bab(_vorlage("se1", "2990/2026", OHNE_ORT, art=EINGABE)),
                _vorlage("sq1", "2991/2026", "[Testdaten] Sammelvorlage Grün", art="Beschlussvorlage"),
                _vorlage("se2", "2992/2026", OHNE_ORT, art=EINGABE),
                _vorlage("sq3", "2993/2026", "[Testdaten] Sammelvorlage Wege", art="Beschlussvorlage")]
    with open(config.PAPERS, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in vorlagen)
    with open(config.BERATUNGEN, "a", encoding="utf-8") as f:
        for k, sitzung in (("se1", s1), ("sq1", s1), ("se2", s2), ("sq3", s3)):
            f.write(json.dumps(_beratung(f"{B}/consultations/fp-{k}", sitzung, f"{sitzung}/top/{k}",
                                         name=namen[sitzung], start=start), ensure_ascii=False) + "\n")
    sitzungen = json.loads(config.MEETINGS.read_text())
    sitzungen += [{"id": s1, "name": namen[s1], "start": start, "organization": [f"{B}/organizations/bab"],
                   "web": "https://example.invalid/sitzung", "agenda_items": 2},
                  {"id": s2, "name": namen[s2], "start": start, "web": "https://example.invalid/sitzung"},   # ohne Gremium
                  {"id": s3, "name": namen[s3], "start": start, "organization": [f"{B}/organizations/rat"]}]
    config.MEETINGS.write_text(json.dumps(sitzungen, ensure_ascii=False))
    build.build()
    export.export()
    capsys.readouterr()
    db = sqlite3.connect(config.DB)
    m = maske.aus_db(db)
    assert {s1, s2} <= set(m.sitzungen) and s3 not in m.sitzungen
    base = config.EXPORT / config.STADT
    for p in config.EXPORT.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".geojson", ".tsv", ".xml", ".ics", ".csv"):
            text = p.read_bytes().decode("utf-8").replace("\r\n ", "")
            assert namen[s1] not in text and namen[s2] not in text, p
    zeit = {x["source_object"]: x for x in json.loads((base / "zeit.json").read_text())["meetings"]}
    assert zeit[s1]["name"] == f"Ortstermin {strasse} {maske.OHNE_NR}" and zeit[s3]["name"] == namen[s3]
    assert zeit[s1]["gremium"] == "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden"
    assert maske.OHNE_NR in zeit[s2]["gremium"] and str(b) not in zeit[s2]["gremium"]   # Gremium aus dem Namen
    ics = _ics_ereignisse(base / "termine.ics")
    assert ics[s1]["DESCRIPTION"].startswith(f"Ortstermin {strasse} {maske.OHNE_NR}\n")
    assert maske.OHNE_NR in ics[s2]["SUMMARY"] and ics[s3]["DESCRIPTION"].startswith(namen[s3] + "\n")
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2991/2026" in f.read_text())
    q = next(p for p in json.loads(gebiet.read_text())["papers"] if p["reference"] == "2991/2026")
    assert [x["meeting"] for x in q["process"]] == [f"Ortstermin {strasse} {maske.OHNE_NR}"]
    erg = check.datenschutz(db)
    assert erg["befunde"] == [] and erg["fehlend"] == [] and erg["untersucht"]["sitzungen"] >= 4, erg
    maskiert = json.dumps(f"Ortstermin {strasse} {maske.OHNE_NR}", ensure_ascii=False)[1:-1]
    for pfad, alt, neu in ((base / "zeit.json", maskiert, namen[s1]), (gebiet, maskiert, namen[s1])):
        b_ = _befund_nach(db, pfad, alt, neu)
        assert len(b_) == 1 and ("2990/2026" in b_[0] or "2991/2026" in b_[0]), (pfad, b_)
    ics_pfad = base / "termine.ics"
    roh = ics_pfad.read_bytes()
    entfaltet = roh.decode("utf-8").replace("\r\n ", "")
    try:
        for alt, neu in ((f"DESCRIPTION:Ortstermin {strasse} {maske.OHNE_NR}", f"DESCRIPTION:{namen[s1]}"),
                         (f"SUMMARY:Sitzung am Kiosk {strasse} {maske.OHNE_NR}", f"SUMMARY:Sitzung am Kiosk {strasse} {b}")):
            assert alt in entfaltet, alt
            ics_pfad.write_bytes(entfaltet.replace(alt, neu, 1).encode("utf-8"))
            b_ = check.datenschutz(db)["befunde"]
            assert len(b_) == 1 and ("2990/2026" in b_[0] or "2992/2026" in b_[0]), b_
    finally:
        ics_pfad.write_bytes(roh)
    db.close()
