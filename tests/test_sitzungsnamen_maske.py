"""Titelmaske für jeden Sitzungsnamen und jedes Gremium aus dem Sitzungsnamen (Entscheidung 19.11.2026 (3) (c)).

Bis dahin liefen Name und Gremium aus dem Namen nur bei einer Sitzung durch die Maske, in der eine Vorlage der Maske
beraten wird (Maske.sitzungen; TECHNIK.md, Offen (9)). Das Gremium aus dem Namen ist der Name selbst, und der ganze Name
steht in zeit.json, in der Beschreibung in termine.ics und in `process[].meeting` der Gebietsdateien daneben; deshalb
läuft jetzt der Name jeder Sitzung durch die Maske (Maske.sitzungsname), ebenso jedes Gremium aus dem Namen, in zeit.json,
termine.ics und index.json („Aktuell in Köln“). check prüft mit derselben Regel (Maske.sitzungsname_offen); ein Befund
bei einer Sitzung ohne Vorlage der Maske nennt nur die Zahl je Datei. Ein Gremium mit dem Namen einer Organisation der
Datenbank stammt nicht aus dem Namen und bleibt. Alle Sitzungen, Vorlagen und Namen sind erfunden (lokaler Testserver
oder direkte Aufrufe); keine Anfragen an die Stadt."""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from pipeline import ausschuesse, build, check, config, export, geocode, maske, sessionnet

OHNE_NR = maske.OHNE_NR
EINGABE = "Anregungen und Beschwerden"
# Namen mit Zahlen, die keine Hausnummer sind: Gremien aus pipeline/ausschuesse.py und geocode.BEZIRKE_KOELN, dazu
# erfundene Sitzungsnamen mit Ordnungszahl, Datum, Uhrzeit, Jahreszahl und Wahlperiode
LEGITIM = ([name for _, name, andere in ausschuesse.AUSSCHUESSE for name in (name, *andere)]
           + [f"Bezirksvertretung {nr} ({name})" for nr, name in geocode.BEZIRKE_KOELN.items()]
           + [f"Sitzung der Bezirksvertretung {nr} ({name})" for nr, name in geocode.BEZIRKE_KOELN.items()]
           + ["3. Sitzung des Ausschusses für Klima, Umwelt und Grün", "Sondersitzung des Rates am 19.11.2026",
              "Rat, 17:00 Uhr", "Konstituierende Sitzung der Wahlperiode 2025–2030",
              "Sitzung des Unterausschusses Kulturbauten", "Arbeitskreis Radverkehr – 2. Sitzung",
              "Sitzung des Rates um 17 Uhr", "Bezirksvertretung 9 (Mülheim) – 12. Sitzung", "Stadtbezirk 5",
              "Sitzung des Hauptausschusses (Wahlperiode 2025–2030)", "Sondersitzung Haushalt 2027"])
# erfundene Sitzungen: Kennung → (Name, Organisation oder None); Beginn am Tag nach heute plus Stelle in der Liste
SITZUNGEN = {
    "ohne": ("Ortstermin Venloer Straße 5", None),        # kein Gremium, keine Vorlage der Maske
    "mit": ("Sitzung am Kiosk Venloer Straße 7", None),   # eine Eingabe wird beraten: Vorlage der Maske
    "org": ("Ortstermin Aachener Straße 12", "rat"),      # Gremium aus der Organisation; eine Beschlussvorlage
    "ak": ("Sitzung des Arbeitskreises", "ak"),           # Organisation, deren Name die Maske ändern würde
    "akname": ("Arbeitskreis 2", None),                   # Name ohne Organisation gleich dem Namen eines Gremiums
    **{f"leg{i}": (name, None) for i, name in enumerate([
        "Bezirksvertretung 1 (Innenstadt)", "Sitzung der Bezirksvertretung 4 (Ehrenfeld)",
        "3. Sitzung des Ausschusses für Klima, Umwelt und Grün", "Sondersitzung des Rates am 19.11.2026",
        "Rat, 17:00 Uhr", "Konstituierende Sitzung der Wahlperiode 2025–2030",
        "Sitzung des Unterausschusses Kulturbauten", "Arbeitskreis Radverkehr – 2. Sitzung"])},
}
# erfundene Vorlagen: Kennung → (Drucksache, Vorlagenart, Titel, Sitzung)
VORLAGEN = {"e1": ("2901/2026", EINGABE, "[Testdaten] Anregung zum Kiosk", "mit"),
            "q1": ("2902/2026", "Beschlussvorlage", "[Testdaten] Sammelvorlage Wege", "org")}
# Wörter aus Sitzungs- und Gremiennamen, die weder im Log noch in einem Befund stehen dürfen
NAMENSTEILE = ("Venloer", "Aachener", "Ortstermin", "Kiosk", "Arbeitskreis")


@pytest.mark.parametrize("name", LEGITIM)
def test_legitime_namen_unveraendert(name):
    """Namen von Gremien und Sitzungen mit Zahlen in bekannten Zusammenhängen (Positivliste der Maske) ändert die Maske
    nicht, und check findet nichts."""
    m = maske.Maske([])
    assert m.sitzungsname(name) == name
    assert not maske.Maske([]).sitzungsname_offen(name)


@pytest.mark.parametrize("name, erwartet", [
    ("Ortstermin Venloer Straße 5", f"Ortstermin Venloer Straße {OHNE_NR}"),
    ("Begehung Aachener Str. 12a", f"Begehung Aachener Str. {OHNE_NR}"),
    ("Ortstermin vor Hausnummer 7", f"Ortstermin vor {OHNE_NR}"),
    ("Sitzung am Kiosk, Hausnummer zwölf", f"Sitzung am Kiosk, {OHNE_NR}"),
])
def test_hausnummer_im_namen_maskiert(name, erwartet):
    """Eine Hausnummer in einem erfundenen Sitzungsnamen fällt weg, ohne Drucksache (keine Vorlage der Maske); eine
    zweite Maske findet im Ergebnis nichts mehr, im ungekürzten Namen schon. Die Maske für Titel bleibt an ihre
    Drucksachen gebunden: Ohne Drucksache der Maske ändert sie den Namen als Titel nicht."""
    m = maske.Maske([])
    assert m.sitzungsname(name) == erwartet
    pruefend = maske.Maske([])
    assert pruefend.sitzungsname_offen(name) and not pruefend.sitzungsname_offen(erwartet)
    assert m(name, "1/2026") == name and not m.offen(name, "1/2026")


def _aufbau(oparl):
    """Sitzungen ab morgen (Kölner Tag des Abrufs heute: alle in termine.ics und die ersten sechs in „Aktuell“), eine
    Eingabe in der Sitzung „mit“, eine Beschlussvorlage in der Sitzung „org“; Abruf, Aufbau, Export. Liefert das Log
    von `export`."""
    b = oparl.b
    oparl.orgs.append({"id": f"{b}/organizations/ak", "name": "Arbeitskreis 2", "organizationType": "Gremium",
                       "modified": "2026-01-01T00:00:00+01:00"})
    for i, (k, (name, org)) in enumerate(SITZUNGEN.items(), 1):
        sitzung = {"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting", "name": name,
                   "start": f"{date.today() + timedelta(days=i)}T16:00:00Z",
                   "web": f"https://example.invalid/sitzung/{k}", "modified": "2026-11-01T08:00:00+01:00"}
        if org:
            sitzung["organization"] = [f"{b}/organizations/{org}"]
        oparl.meetings.append(sitzung)
    for k, (ref, art, titel, sitzung) in VORLAGEN.items():
        oparl.papers.append({**oparl.paper(1), "id": f"{b}/papers/{k}", "reference": ref, "paperType": art,
                             "name": titel, "location": [],
                             "consultation": [{"id": f"{b}/consultations/{k}", "meeting": f"{b}/meetings/{sitzung}",
                                               "role": "Beratung", "authoritative": False}]})
    sessionnet.fetch_all()
    build.build()
    export.export()


def _sitzungen(base):
    zeit = {x["source_object"].rsplit("/", 1)[1]: x for x in json.loads((base / "zeit.json").read_text())["meetings"]}
    ics = {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(base / "termine.ics")}
    aktuell = {x["source_object"].rsplit("/", 1)[1]: x
               for x in json.loads((base / "index.json").read_text())["aktuell"]["sitzungen"]}
    return zeit, ics, aktuell


def test_jede_sitzung_maskiert_im_export(oparl, capsys):
    """Orakel: die Hausnummern 5, 7 und 12 der erfundenen Namen in keiner Datei des Exports; Name und Gremium aus dem
    Namen maskiert in zeit.json, termine.ics und index.json, auch ohne Vorlage der Maske („ohne“) und bei einer
    Sitzung mit Organisation („org“); legitime Namen und Namen von Organisationen unverändert; die Sitzung mit einer
    Vorlage der Maske („mit“) wie bisher. Log von `export` nur mit Zahlen; check ohne Befund."""
    capsys.readouterr()
    _aufbau(oparl)
    log = capsys.readouterr().out
    base = config.EXPORT / config.STADT
    for pfad in config.EXPORT.rglob("*"):
        if pfad.is_file() and pfad.suffix in (".json", ".geojson", ".tsv", ".xml", ".ics", ".csv"):
            text = pfad.read_bytes().decode("utf-8").replace("\r\n ", "")
            for name in ("Venloer Straße 5", "Venloer Straße 7", "Aachener Straße 12"):
                assert name not in text, (pfad, name)
    zeit, ics, aktuell = _sitzungen(base)
    ohne, mit = f"Ortstermin Venloer Straße {OHNE_NR}", f"Sitzung am Kiosk Venloer Straße {OHNE_NR}"
    # ohne Vorlage der Maske: Name und Gremium aus dem Namen überall maskiert
    assert zeit["ohne"]["name"] == zeit["ohne"]["gremium"] == ohne
    assert ics["ohne"]["DESCRIPTION"].split("\n")[0] == ics["ohne"]["SUMMARY"] == ohne
    assert aktuell["ohne"]["gremium"] == ohne
    # mit Organisation: Name maskiert, Gremium aus der Organisation
    assert zeit["org"]["name"] == ics["org"]["DESCRIPTION"].split("\n")[0] == f"Ortstermin Aachener Straße {OHNE_NR}"
    assert zeit["org"]["gremium"] == ics["org"]["SUMMARY"] == aktuell["org"]["gremium"] == "Rat"
    # mit Vorlage der Maske: wie bisher
    assert zeit["mit"]["name"] == zeit["mit"]["gremium"] == ics["mit"]["SUMMARY"] == aktuell["mit"]["gremium"] == mit
    # Namen von Organisationen bleiben, auch wenn die Maske sie ändern würde; ein Name ohne Organisation, der dem Namen
    # eines Gremiums gleicht, ergibt dessen Schreibweise (aus dem ungekürzten Namen), der Name selbst ist maskiert
    assert zeit["ak"]["gremium"] == ics["ak"]["SUMMARY"] == aktuell["ak"]["gremium"] == "Arbeitskreis 2"
    assert zeit["ak"]["name"] == "Sitzung des Arbeitskreises"
    assert zeit["akname"]["gremium"] == aktuell["akname"]["gremium"] == "Arbeitskreis 2"
    assert zeit["akname"]["name"] == ics["akname"]["DESCRIPTION"].split("\n")[0] == f"Arbeitskreis {OHNE_NR}"
    # legitime Namen unverändert, das Gremium wie ohne Maske
    db = sqlite3.connect(config.DB)
    namen = dict(db.execute("SELECT id, name FROM organization"))
    for k, (name, _) in SITZUNGEN.items():
        if k.startswith("leg"):
            gremium = export.gremium_der_sitzung({"name": name, "organization": []}, namen)
            assert zeit[k]["name"] == name and zeit[k]["gremium"] == gremium, k
            assert ics[k]["DESCRIPTION"].split("\n")[0] == name and ics[k]["SUMMARY"] == gremium, k
    assert zeit["leg1"]["gremium"] == "Bezirksvertretung 4 (Ehrenfeld)"   # Name einer Organisation
    # Gebietsdatei: der Name der Sitzung bei der Beschlussvorlage maskiert (Sitzung ohne Vorlage der Maske)
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2902/2026" in f.read_text())
    q = next(p for p in json.loads(gebiet.read_text())["papers"] if p["reference"] == "2902/2026")
    assert [x["meeting"] for x in q["process"]] == [f"Ortstermin Aachener Straße {OHNE_NR}"]
    # Log: Gremium aus dem Namen bei „ohne“, „mit“ und den legitimen Namen außer „leg1“ (9); von der Maske geändert:
    # „ohne“, „mit“, „org“ und „akname“ (4); keine Namen
    assert "Sitzungen: Gremium aus dem Sitzungsnamen 9, Namen oder Gremien von der Maske geändert 4\n" in log
    assert not [t for t in NAMENSTEILE if t in log], log
    capsys.readouterr()
    erg = check.datenschutz(db)
    out = capsys.readouterr().out
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    # je Sitzung in zeit.json und termine.ics eine Zählung, dazu die Sitzungen in den Gebietsdateien
    assert erg["untersucht"]["sitzungen"] >= 2 * len(SITZUNGEN), erg["untersucht"]
    assert not [t for t in NAMENSTEILE if t in out], out


def _befunde_nach(db, pfad, aendern, capsys):
    """Befunde und Ausgabe von check.datenschutz, nachdem `aendern(Text)` den Text von `pfad` geändert hat (Datei danach
    wie vorher)."""
    roh = pfad.read_bytes()
    neu = aendern(roh.decode("utf-8"))
    assert neu != roh.decode("utf-8"), pfad
    pfad.write_bytes(neu.encode("utf-8"))
    try:
        capsys.readouterr()
        befunde = check.datenschutz(db)["befunde"]
        return befunde, capsys.readouterr().out
    finally:
        pfad.write_bytes(roh)


def _json_aendern(aendern):
    def f(text):
        daten = json.loads(text)
        aendern(daten)
        return json.dumps(daten, ensure_ascii=False)
    return f


def _ics_ersetzen(alt, neu):
    """termine.ics entfaltet (wie check liest) und `alt` einmal durch `neu` ersetzt."""
    def f(text):
        text = text.replace("\r\n ", "")
        assert alt in text, alt
        return text.replace(alt, neu, 1)
    return f


def test_check_meldet_ungekuerzte_sitzung(oparl, capsys):
    """Gegenproben: Der ungekürzte Name oder das ungekürzte Gremium aus dem Namen einer Sitzung ohne Vorlage der Maske
    in zeit.json, termine.ics oder index.json ist ein Befund nur mit der Zahl je Datei, ohne Namen und ohne Kennung (im
    Befund und in der Ausgabe von check); in der Gebietsdatei ein Befund unter der Drucksache der zeigenden Vorlage;
    bei einer Sitzung mit Vorlage der Maske wie bisher unter deren Drucksache."""
    _aufbau(oparl)
    base = config.EXPORT / config.STADT
    db = sqlite3.connect(config.DB)
    roh_ohne, roh_mit = SITZUNGEN["ohne"][0], SITZUNGEN["mit"][0]
    ohne = f"Ortstermin Venloer Straße {OHNE_NR}"

    def sitzung(daten, k, feld, wert, liste="meetings"):
        eintraege = daten[liste] if liste == "meetings" else daten["aktuell"]["sitzungen"]
        next(x for x in eintraege if x["source_object"].endswith(f"/meetings/{k}"))[feld] = wert

    faelle = [
        (base / "zeit.json", _json_aendern(lambda d: sitzung(d, "ohne", "name", roh_ohne)), "zeit.json 1"),
        (base / "zeit.json", _json_aendern(lambda d: sitzung(d, "ohne", "gremium", roh_ohne)), "zeit.json 1"),
        (base / "termine.ics", _ics_ersetzen(f"DESCRIPTION:{ohne}", f"DESCRIPTION:{roh_ohne}"), "termine.ics 1"),
        (base / "termine.ics", _ics_ersetzen(f"SUMMARY:{ohne}", f"SUMMARY:{roh_ohne}"), "termine.ics 1"),
        (base / "index.json", _json_aendern(lambda d: sitzung(d, "ohne", "gremium", roh_ohne, "aktuell")),
         "index.json 1"),
    ]
    for pfad, aendern, zahl in faelle:
        befunde, out = _befunde_nach(db, pfad, aendern, capsys)
        assert len(befunde) == 1 and "Sitzungen ohne Vorlage der Titelmaske" in befunde[0], (pfad, befunde)
        assert befunde[0].endswith(f"Sitzungen je Datei: {zahl}"), befunde
        assert not [t for t in NAMENSTEILE if t in out + befunde[0]], (out, befunde)
        assert "/meetings/" not in befunde[0]
    # Gebietsdatei der Beschlussvorlage: Befund unter ihrer Drucksache
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2902/2026" in f.read_text())

    def meeting(d):
        q = next(p for p in d["papers"] if p["reference"] == "2902/2026")
        q["process"][0]["meeting"] = SITZUNGEN["org"][0]
    befunde, out = _befunde_nach(db, gebiet, _json_aendern(meeting), capsys)
    assert len(befunde) == 1 and befunde[0].endswith(": 1, z. B. 2902/2026"), befunde
    assert not [t for t in NAMENSTEILE if t in out + befunde[0]], (out, befunde)
    # Sitzung mit Vorlage der Maske: wie bisher unter der Drucksache der Eingabe
    befunde, _ = _befunde_nach(db, base / "zeit.json", _json_aendern(lambda d: sitzung(d, "mit", "name", roh_mit)),
                               capsys)
    assert len(befunde) == 1 and befunde[0].endswith(": 1, z. B. 2901/2026"), befunde
    # ein Gremium mit dem Namen einer Organisation bleibt ungeprüft, auch wo die Maske es ändern würde
    befunde, _ = _befunde_nach(db, base / "index.json",
                               _json_aendern(lambda d: sitzung(d, "ohne", "gremium", "Arbeitskreis 2", "aktuell")),
                               capsys)
    assert befunde == []
    db.close()
