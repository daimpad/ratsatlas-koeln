"""Gremium aus dem Sitzungsnamen ohne zweite Zeile und ohne Zusatz zum Stand (Entscheidung 20.11.2026 (4) (b)).

Fehlt einer Sitzung die Organisation, ist ihr Gremium seitdem die erste Zeile des Namens mit Text, ohne Vorspann
(export._VORSPANN_SITZUNG) und ohne einen Zusatz zum Stand aus einer festen Liste hinter „ - “ oder „ – “
(export._ZUSATZ_STAND: „Sitzung fällt aus“, „fällt aus“, „Sitzung entfällt“, „entfällt“, „Sitzung enfällt“, „enfällt“,
„abgesagt“, „vertagt …“, „verschoben …“), danach wie bisher in der Schreibweise eines bekannten Gremiums. Vorher behielt
das Gremium eine zweite Zeile und einen solchen Zusatz; im Lauf 57 stand so ein Beirat als drei Gremien in zeit.json.
Der Name der Sitzung bleibt überall unverändert, ebenso der Name einer Organisation. Alle Gremien, Sitzungen und Namen
sind erfunden (lokaler Testserver oder direkte Aufrufe); keine Anfragen an die Stadt."""
import json
import re
import sqlite3
from datetime import date, timedelta

import pytest

from pipeline import build, check, config, export, maske, publish, sessionnet

G = "Beispielbeirat"
ORG = "https://example.invalid/oparl/organizations/o1"


def gremium(name, names=None, org=False):
    """Gremium einer erfundenen Sitzung, ohne und mit dem Index der bekannten Gremien (beide gleich)."""
    names = names or {}
    m = {"name": name, "organization": list(names) if org else []}
    erg = export.gremium_der_sitzung(m, names)
    assert export.gremium_der_sitzung(m, names, export.gremien_index(names)) == erg, name
    return erg


@pytest.mark.parametrize("zusatz", [
    "Sitzung fällt aus", "fällt aus", "Sitzung entfällt", "entfällt", "Sitzung enfällt", "enfällt", "abgesagt",
    "vertagt", "vertagt auf einen späteren Zeitpunkt", "verschoben", "verschoben auf den 3. Dezember",
])
def test_jede_form_der_liste_faellt_weg(zusatz):
    """Jede Form der Liste fällt hinter „ - “ und „ – “ weg, auch mit „ -“, „!“ und Leerraum dahinter, auch hinter einem
    Vorspann; „vertagt“ und „verschoben“ samt dem Rest der Zeile. Ohne bekanntes Gremium bleibt der Rest des Namens."""
    for strich in ("-", "–"):
        for ende in ("", " -", "!", "! -", "  ", " – "):
            assert gremium(f"{G} {strich} {zusatz}{ende}") == G, (strich, zusatz, ende)
    assert gremium(f"Sitzung des {G}es - {zusatz}") == G
    assert gremium(f"2. Sondersitzung des {G}es – {zusatz} -") == G


@pytest.mark.parametrize("name", [
    f"Sitzung des {G}es\n-Sitzung ist auf den 3. Dezember verschoben worden!-",
    f"{G}\nACHTUNG: Die Sitzung wird kurzfristig auf Donnerstag, 03.12.2026, verlegt.",
    f"{G}\r\nAchtung: Die Sitzung wurde abgesagt und fällt aus!",
    f"\n  \nSitzung des {G}es \nAchtung: Die Sitzung wurde abgesagt und fällt aus!",
    f"{G} - Sitzung enfällt\nAchtung: Die Sitzung wurde abgesagt und fällt aus!",
    f"2. Sondersitzung des {G}es – vertagt auf einen späteren Zeitpunkt\nzweite Zeile",
])
def test_nur_die_erste_zeile(name):
    """Eine zweite Zeile (beobachtete Formen eines Hinweises, erfundenes Gremium) fällt weg; es zählt die erste Zeile
    mit Text, ohne Leerraum am Ende; auf ihr fallen Vorspann und Zusatz wie sonst weg. Ein Name nur aus Leerraum ergibt
    wie ein leerer Name „unbekannt“."""
    assert gremium(name) == G
    assert gremium(" \n\n") == gremium("") == "unbekannt"


def test_schreibweise_eines_bekannten_gremiums_nach_dem_kuerzen():
    """Erst fallen zweite Zeile, Vorspann und Zusatz weg, dann folgt der Vergleich mit den bekannten Gremien: Der Name
    mit Zusatz findet die Schreibweise eines bekannten Gremiums über den strengen und über den breiten Schlüssel (ohne
    „für“). So stammt das Gremium nicht mehr aus dem Namen (export.gremium_aus_namen), und die Zeile im Log von
    `export` zählt es dort nicht mehr."""
    names = {ORG: G, "https://example.invalid/oparl/organizations/o2": "Ausschuss für Probewesen"}
    organisationen = set(names.values())
    for name, erwartet in [
        (f"{G} - Sitzung enfällt", G), (f"{G.lower()} – entfällt!", G),
        (f"Sitzung des {G}es - vertagt auf einen späteren Zeitpunkt", G),
        (f"Sitzung des {G}es\n-Sitzung ist auf den 3. Dezember verschoben worden!-", G),
        ("Sitzung des Ausschusses Probewesen – verschoben auf den 3. Dezember", "Ausschuss für Probewesen"),
        ("Sitzung des Ausschusses Probewesen\nACHTUNG: Die Sitzung wird verlegt.", "Ausschuss für Probewesen"),
    ]:
        assert gremium(name, names) == erwartet, name
        assert not export.gremium_aus_namen(erwartet, organisationen), name


def test_zeilenumbruch_im_namen_eines_bekannten_gremiums():
    """Hat der Name mehrere Zeilen mit Text, gilt vor dem Treffer der ersten Zeile der Treffer des ganzen Namens (ohne
    Vorspann und ohne Zusatz am Ende, strenger oder breiter Schlüssel): Ein Zeilenumbruch mitten im Namen eines
    bekannten Gremiums ergibt so kein gekürztes Gremium (bis ab3fff9 traf der ganze Name), auch nicht neben einem
    bekannten Gremium mit dem Namen der ersten Zeile. Text der zweiten Zeile kommt nie ins Gremium: Trifft der ganze
    Name nichts, gilt die erste Zeile wie sonst."""
    lang, kurz = "Ausschuss für Musterwesen und Probefragen", "Ausschuss für Musterwesen"
    names = {ORG: lang, "https://example.invalid/oparl/organizations/o2": "Bezirksvertretung Probedorf"}
    for name, erwartet in [
        ("Sitzung des Ausschusses für Musterwesen\nund Probefragen", lang),
        ("Sitzung des Ausschusses Musterwesen\nund Probefragen – entfällt", lang),
        ("Sitzung der Bezirksvertretung\nProbedorf", "Bezirksvertretung Probedorf"),
        ("Sitzung der Bezirksvertretung\r\nProbedorf - Sitzung fällt aus -", "Bezirksvertretung Probedorf"),
        ("Sitzung der Bezirksvertretung\nAchtung: Die Sitzung wurde abgesagt und fällt aus!", "Bezirksvertretung"),
        ("Sitzung des Ausschusses für Musterwesen\nACHTUNG: Die Sitzung wird verlegt.", "Ausschuss für Musterwesen"),
    ]:
        assert gremium(name, names) == erwartet, name
    names["https://example.invalid/oparl/organizations/o3"] = kurz
    assert gremium("Sitzung des Ausschusses für Musterwesen\nund Probefragen", names) == lang
    assert gremium("Sitzung des Ausschusses für Musterwesen\nACHTUNG: Die Sitzung wird verlegt.", names) == kurz


def test_name_einer_organisation_unveraendert():
    """Der Name einer Organisation bleibt, auch wenn er ein Wort der Liste trägt; derselbe Name ohne Organisation
    verliert den Zusatz."""
    for org in ("Probekreis - Sitzung entfällt", "Musterkreis – vertagt auf einen späteren Zeitpunkt",
                "Probekreis - abgesagt!"):
        names = {ORG: org}
        assert gremium(f"{G} - Sitzung enfällt", names, org=True) == org
        assert gremium(f"{G}\nAchtung: Die Sitzung wurde abgesagt und fällt aus!", names, org=True) == org
        assert gremium(org) == org.split(" ")[0]


@pytest.mark.parametrize("name", [
    "Ausschuss Probewesen und Rechtsfragen / Vergabe / Beispielfragen",
    "Rahmenplanungsbeirat Probedorf / Musterfeld / Beispielheim",
    "Ausschuss für Kinder, Probe und Muster",
    "Betriebsausschuss Beispiel-Probe-Museum & Fondation Muster",
    f"{G} - Haushalt", f"{G} – Arbeitsgruppe Verkehr", f"{G} - Unterausschuss Probe-Planung",
])
def test_legitime_namen_bleiben(name):
    """Namen mit „ / “, Komma, Bindestrich im Wort oder „ - “ vor einem anderen Wort als denen der Liste bleiben
    unverändert (keine allgemeine Kürzung hinter „ - “); mit einem Zusatz der Liste oder einer zweiten Zeile dahinter
    ergeben sie wieder genau diesen Namen."""
    assert gremium(name) == name
    assert gremium(f"{name} - Sitzung entfällt") == name
    assert gremium(f"{name} – vertagt auf einen späteren Zeitpunkt") == name
    assert gremium(f"{name}\nAchtung: Die Sitzung wurde abgesagt und fällt aus!") == name


def test_grenzen_der_liste():
    """Nur die Formen der Liste, am Ende der Zeile, in der Schreibweise der Liste und hinter „ - “ oder „ – “ mit
    Leerraum auf beiden Seiten; „vertagt“ und „verschoben“ samt dem Rest der Zeile, wenn das Wort dort endet, auch vor
    einem Satzzeichen; daneben je die Form, die wegfällt."""
    for name, erwartet in [
        (f"{G} - entfällt wegen Krankheit", f"{G} - entfällt wegen Krankheit"), (f"{G} - entfällt", G),
        (f"{G} - Abgesagt", f"{G} - Abgesagt"), (f"{G} - abgesagt", G),
        (f"{G} - Sitzung verschoben", f"{G} - Sitzung verschoben"), (f"{G} - verschoben", G),
        (f"{G} - Sitzung abgesagt", f"{G} - Sitzung abgesagt"), (f"{G} - Sitzung fällt aus", G),
        (f"{G} -entfällt", f"{G} -entfällt"), (f"{G}-entfällt", f"{G}-entfällt"), (f"{G} – entfällt", G),
        (f"{G} - vertagte Sitzung", f"{G} - vertagte Sitzung"), (f"{G} - vertagt", G),
        (f"{G} - verschobene Projekte", f"{G} - verschobene Projekte"), (f"{G} - vertagt.", G),
        (f"{G} - verschoben, neuer Termin folgt", G), (f"{G} - vertagt: neuer Termin", G),
        (f"{G} - entfällt - Haushalt", f"{G} - entfällt - Haushalt"), (f"{G} - Haushalt - entfällt", f"{G} - Haushalt"),
    ]:
        assert gremium(name) == erwartet, name


# erfundene Sitzungen für die Kette: Kennung → (Name, Organisation oder None); Beginn am Tag nach heute plus Stelle in
# der Liste (in „Aktuell“ alle ohne Absage im Namen, Entscheidung 20.11.2026 (7) (b); vorher die ersten sechs). Bekannte
# Gremien der Datenbank: „Beispielbeirat“ (bb), „Probekreis - abgesagt“ (pk) und „Ausschuss für Musterwesen und
# Probefragen“ (mu), dazu die des Testservers
SITZUNGEN = {
    "z1": (f"{G} - Sitzung enfällt", None),
    "z2": ("Sitzung des Probebeirates – vertagt auf einen späteren Zeitpunkt", None),
    "z3": ("Musterkreis Probe - Sitzung fällt aus -", None),
    "z4": ("2. Sondersitzung des Probebeirates\nAchtung: Die Sitzung wurde abgesagt und fällt aus!", None),
    "z5": (f"{G} - verschoben auf den 3. Dezember!", None),
    "z6": (f"{G} - abgesagt", "pk"),
    "z7": ("Ausschuss Probewesen / Vergabe / Beispielfragen - Haushalt", None),
    "z8": ("Betriebsausschuss Beispiel-Probe-Museum & Fondation Muster", None),
    "z9": ("Sitzung des Ausschusses für Musterwesen\nund Probefragen", None),
}
ERWARTET = {"z1": G, "z2": "Probebeirat", "z3": "Musterkreis Probe", "z4": "Probebeirat", "z5": G,
            "z6": "Probekreis - abgesagt", "z7": "Ausschuss Probewesen / Vergabe / Beispielfragen - Haushalt",
            "z8": "Betriebsausschuss Beispiel-Probe-Museum & Fondation Muster",
            "z9": "Ausschuss für Musterwesen und Probefragen"}


def _aufbau(oparl):
    """Sitzungen ab morgen und eine Beschlussvorlage, beraten in „z1“ und „z4“; Abruf, Aufbau, Export."""
    b = oparl.b
    for k, name in (("bb", G), ("pk", "Probekreis - abgesagt"), ("mu", "Ausschuss für Musterwesen und Probefragen")):
        oparl.orgs.append({"id": f"{b}/organizations/{k}", "name": name, "organizationType": "Gremium",
                           "modified": "2026-01-01T00:00:00+01:00"})
    for i, (k, (name, org)) in enumerate(SITZUNGEN.items(), 1):
        sitzung = {"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting", "name": name,
                   "start": f"{date.today() + timedelta(days=i)}T16:00:00Z",
                   "web": f"https://example.invalid/sitzung/{k}", "modified": "2026-11-01T08:00:00+01:00"}
        if org:
            sitzung["organization"] = [f"{b}/organizations/{org}"]
        oparl.meetings.append(sitzung)
    oparl.papers.append({**oparl.paper(1), "id": f"{b}/papers/q1", "reference": "2904/2026",
                         "paperType": "Beschlussvorlage", "name": "[Testdaten] Sammelvorlage Zusätze",
                         "location": [],
                         "consultation": [{"id": f"{b}/consultations/q1{k}", "meeting": f"{b}/meetings/{k}",
                                           "role": "Beratung", "authoritative": False} for k in ("z1", "z4")]})
    sessionnet.fetch_all()
    build.build()
    export.export()


def test_kette_gremium_ohne_zusatz(oparl, capsys):
    """Orakel: In zeit.json, in der Zusammenfassung in termine.ics und in index.json („Aktuell“) steht das Gremium ohne
    zweite Zeile und ohne Zusatz, bei „z1“ und „z5“ in der Schreibweise der Organisation „Beispielbeirat“, bei „z9“
    (Zeilenumbruch mitten im Namen) in der Schreibweise „Ausschuss für Musterwesen und Probefragen“; der Name
    jeder Sitzung steht unverändert in zeit.json, in der Beschreibung in termine.ics und in `process[].meeting`; die
    Organisation „Probekreis - abgesagt“ bleibt. Zeile im Log von `export`: Gremium aus dem Sitzungsnamen bei „z2“,
    „z3“, „z4“, „z7“ und „z8“ (5; mit dem Code von ab3fff9 auch „z1“ und „z5“, „z9“ in beiden Ständen nicht), gleich
    der Zahl in zeit.json nach export.gremium_aus_namen; check ohne Befund."""
    capsys.readouterr()
    _aufbau(oparl)
    log = capsys.readouterr().out
    base = config.EXPORT / config.STADT
    zeit = {x["source_object"].rsplit("/", 1)[1]: x for x in json.loads((base / "zeit.json").read_text())["meetings"]}
    ics = {e["UID"].rsplit("/", 1)[1]: e for e in check._ics_ereignisse(base / "termine.ics")}
    aktuell = {x["source_object"].rsplit("/", 1)[1]: x
               for x in json.loads((base / "index.json").read_text())["aktuell"]["sitzungen"]}
    db = sqlite3.connect(config.DB)
    namen = dict(db.execute("SELECT id, name FROM organization"))
    organisationen = {n for n in namen.values() if n}
    for k, (name, org) in SITZUNGEN.items():
        assert export.gremium_der_sitzung({"name": name, "organization": [f"{oparl.b}/organizations/{org}"]
                                           if org else []}, namen) == ERWARTET[k], k
        assert zeit[k]["name"] == name and zeit[k]["gremium"] == ERWARTET[k], k
        assert publish.ics_sitzungsname(ics[k]["DESCRIPTION"]) == name and ics[k]["SUMMARY"] == ERWARTET[k], k
        assert ics[k]["STATUS"] == "CONFIRMED" and not zeit[k]["cancelled"], k
    # „Aktuell“ ohne die Sitzungen, deren Name eine Absage nennt (export.hinweis_sitzung, Entscheidung 20.11.2026 (7)
    # (b): „z1“, „z3“, „z4“, „z6“); vorher standen dort die ersten sechs
    assert set(aktuell) == {"z2", "z5", "z7", "z8", "z9"}, sorted(aktuell)
    for k in aktuell:
        assert aktuell[k]["gremium"] == ERWARTET[k] and "name" not in aktuell[k], k
    for pfad in (base / "zeit.json", base / "termine.ics"):
        assert maske.OHNE_NR not in pfad.read_text(), pfad
    # Gebietsdatei: die Namen der beiden Sitzungen bei der Beschlussvorlage unverändert, samt zweiter Zeile
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2904/2026" in f.read_text())
    q = next(p for p in json.loads(gebiet.read_text())["papers"] if p["reference"] == "2904/2026")
    assert sorted(x["meeting"] for x in q["process"]) == sorted(SITZUNGEN[k][0] for k in ("z1", "z4"))
    # Zeile im Log: dieselbe Zahl wie export.gremium_aus_namen über alle Sitzungen in zeit.json
    aus_namen = sum(export.gremium_aus_namen(x["gremium"], organisationen) for x in zeit.values())
    zeile = re.search(r"Sitzungen: Gremium aus dem Sitzungsnamen (\d+), Namen oder Gremien von der Maske geändert "
                      r"(\d+)\n", log)
    assert zeile and (int(zeile[1]), int(zeile[2])) == (aus_namen, 0) == (5, 0), log
    capsys.readouterr()
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    assert erg["untersucht"]["sitzungen"] >= 2 * len(SITZUNGEN), erg["untersucht"]
