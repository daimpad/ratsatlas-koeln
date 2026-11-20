"""Ordnungszahlen in Sitzungsnamen und Gremium ohne Vorspann (Entscheidung 20.11.2026 (2) (a)).

Im Lauf nach dem Zusammenführen von #40 kürzte die Maske 59 von 3 362 Sitzungsnamen und ein Gremium, jedes Mal eine
Ordnungszahl vor „Sitzung“ oder „Sondersitzung“, die die Positivliste nicht kannte. Seitdem kennt die Positivliste nur
für Sitzungsnamen solche Ordnungszahlen (maske._SITZUNG_BEKANNT, Maske.sitzungsname und Maske.sitzungsname_offen); die
Maske für Titel bleibt unverändert, und eine Straße mit Nummer entfernt weiter die erste Stufe der Maske. Das Gremium
aus einem Namen wie „2. Sondersitzung des Unterausschusses …“ verliert den Vorspann (export.gremium_der_sitzung). Die
Formen der Namen sind die beobachteten, Ausschüsse, Bezirksvertretungen und Zahlen erfunden; lokaler Testserver oder
direkte Aufrufe, keine Anfragen an die Stadt."""
import json
import re
import sqlite3
from datetime import date, timedelta

import pytest

import test_datenschutz_fixpunkt as fixpunkt  # noqa: E402  (vorhandene Titel der Titelmaske)
from pipeline import build, check, config, export, maske, publish, sessionnet

OHNE_NR = maske.OHNE_NR
REF = "1/2026"
A, B = "des Ausschusses für Musterwesen", "des Ausschusses für Beispielfragen"
BV = "der Bezirksvertretung Beispielstadt"
# beobachtete Formen (Lauf 55), mit erfundenen Gremien und Zahlen: der Sitzungsname bleibt unverändert; daneben die
# Ausgabe der Titelmaske für denselben Text, eingefroren aus 859cc57 („#“ für OHNE_NR)
FORMEN = {
    f"2. Sondersitzung {A}": f"#. Sondersitzung {A}",
    f"3. Gemeinsame Sondersitzung {A} und {B}": f"#. Gemeinsame Sondersitzung {A} und {B}",
    f"2. Sondersitzung (14. Sitzung insgesamt) {A}": f"#. Sondersitzung (14. Sitzung insgesamt) {A}",
    f"2. Sondersitzung (14. Sitzung) {A}": f"#. Sondersitzung (14. Sitzung) {A}",
    f"2. Sondersitzung {A} (14. Sitzung insgesamt)": f"#. Sondersitzung {A} (14. Sitzung insgesamt)",
    f"2. Sondersitzung {A} (14.Sitzung)": f"#. Sondersitzung {A} (14.Sitzung)",
    f"14. Sitzung/2. Sondersitzung {A}": f"14. Sitzung/#. Sondersitzung {A}",
    f"2. Sondersitzung/14. Sitzung {A}": f"#. Sondersitzung/14. Sitzung {A}",
    f"14. Sitzung {A} (2. Sondersitzung)": f"14. Sitzung {A} (#. Sondersitzung)",
    f"14. Sitzung (2. Sondersitzung) {A}": f"14. Sitzung (#. Sondersitzung) {A}",
    f"Gemeinsame Sondersitzung {A} (2. Sondersitzung/14. Sitzung) und {BV}":
        f"Gemeinsame Sondersitzung {A} (#. Sondersitzung/14. Sitzung) und {BV}",
    f"3. Gemeinsame Sondersitzung {A} (3.) und {B}": f"#. Gemeinsame Sondersitzung {A} (#.) und {B}",
    f"1. (konstituierende) Sitzung {BV}": f"#. (konstituierende) Sitzung {BV}",
    f"1. Konstituierende Sitzung {A}": f"#. Konstituierende Sitzung {A}",
    f"5 Sitzung {A}": f"# Sitzung {A}",
    f"5, Sitzung {BV}": f"#, Sitzung {BV}",
    f"5.. Sitzung {BV}": f"#.. Sitzung {BV}",
    # Namen mit einer zweiten Zeile: deren Zahlen blieben schon vorher stehen und bleiben es
    f"2. Sondersitzung {BV}\n-Sitzung ist auf den 3. Dezember verschoben worden!-":
        f"#. Sondersitzung {BV}\n-Sitzung ist auf den 3. Dezember verschoben worden!-",
    f"5. Sondersitzung {A}\nACHTUNG: Die Sitzung wird kurzfristig auf Donnerstag, 03.12.2026, verlegt.":
        f"#. Sondersitzung {A}\nACHTUNG: Die Sitzung wird kurzfristig auf Donnerstag, 03.12.2026, verlegt.",
    f"1. Konstituierende Sitzung {A}\nAchtung: Die Sitzung wurde abgesagt und fällt aus!":
        f"#. Konstituierende Sitzung {A}\nAchtung: Die Sitzung wurde abgesagt und fällt aus!",
    "2. Sondersitzung des Unterausschusses Beispielbauten": "#. Sondersitzung des Unterausschusses Beispielbauten",
    # beobachtete Schreibweise ohne Genitiv-s
    "2. Sondersitzung des Unterausschuss Beispielbauten": "#. Sondersitzung des Unterausschuss Beispielbauten",
    # Name eines Stadtbezirks mit Straßen-Endung (im Sitzungsnamen _GEBIET_ERSATZ, ein Teil des Worts vor „(3.)“)
    "1. (konstituierende) Sitzung der Bezirksvertretung Ehrenfeld":
        "#. (konstituierende) Sitzung der Bezirksvertretung Ehrenfeld",
    f"3. Gemeinsame Sondersitzung der Bezirksvertretung Ehrenfeld (3.) und {A}":
        f"#. Gemeinsame Sondersitzung der Bezirksvertretung Ehrenfeld (#.) und {A}",
}
# Hausnummern in Sitzungsnamen (erfunden): Name → Sitzungsname nach der Maske, Titelmaske eingefroren aus 859cc57; „#“
# für OHNE_NR. Eine Straße mit Nummer entfernt die erste Stufe, auch vor „Sitzung“; hinter „Hausnummer“ fällt die Liste
# samt der 2 weg; „(3.)“ hinter einer Zahl und die Formen ohne Punkt oder mit Komma mitten im Namen kennt die
# Positivliste nicht
HAUSNUMMERN = {
    "Ortstermin Venloer Straße 5. Sitzung": ("Ortstermin Venloer Straße #. Sitzung",) * 2,
    "Sondersitzung Venloer Str. 12": ("Sondersitzung Venloer Str. #",) * 2,
    "Neumarkt 3, Sitzung": ("Neumarkt #, Sitzung",) * 2,
    "Ortstermin Ehrenfeld 5": ("Ortstermin Ehrenfeld #",) * 2,
    "Hausnummer 7 – 2. Sondersitzung": ("#. Sondersitzung",) * 2,
    "Haus 12 (3.)": ("Haus # (#.)",) * 2,
    "Ortstermin Kiosk 5, Sitzung": ("Ortstermin Kiosk #, Sitzung",) * 2,
    "Ortstermin Kiosk 5 Sitzung": ("Ortstermin Kiosk # Sitzung",) * 2,
    "Venloer Straße 5, 2. Sondersitzung": ("Venloer Straße #. Sondersitzung",) * 2,
}
# erste Zeile vor einem Namen mit Hausnummer: Die Ordnungszahl darin bleibt, die Hausnummer dahinter fällt weg
VORZEILE = f"2. Sondersitzung {A}\n"
# Grenzen der Regel (Prüfung vor dem Zusammenführen; erfunden): Steht zwischen Straße und Nummer ein anderes Wort oder
# steht eine weitere Nummer einer Liste in einer Form von maske._SITZUNG_BEKANNT, bleibt sie im Sitzungsnamen stehen;
# vor „Sitzung“ war das schon vorher so (_ORDNUNG in _BEKANNT). Name → Sitzungsname nach der Maske, Titelmaske
# eingefroren aus 859cc57; „#“ für OHNE_NR. Ändert sich die Regel, zeigt dieser Test es
GRENZEN = {
    "Ortstermin Venloer Straße am Haus 5. Sondersitzung":
        ("Ortstermin Venloer Straße am Haus 5. Sondersitzung", "Ortstermin Venloer Straße am Haus #. Sondersitzung"),
    "Ortstermin Venloer Straße am Haus 5. Sitzung": ("Ortstermin Venloer Straße am Haus 5. Sitzung",) * 2,
    "Venloer Straße 5 und (7.)": ("Venloer Straße # und (7.)", "Venloer Straße # und (#.)"),
    "Venloer Straße 5 und (7. Sondersitzung)":
        ("Venloer Straße # und (7. Sondersitzung)", "Venloer Straße # und (#. Sondersitzung)"),
    "Venloer Straße 5 und (7. Sitzung)": ("Venloer Straße # und (7. Sitzung)",) * 2,
}


def _ohne(text):
    return text.replace("#", OHNE_NR)


@pytest.fixture(scope="module")
def masken():
    """Drei Masken für viele Namen (eine Maske je Name braucht etwa eine halbe Sekunde): eine für Sitzungsnamen, eine
    prüfende (Maske.sitzungsname vermerkt offen() für das eigene Ergebnis vorab als falsch) und eine für Titel."""
    return maske.Maske([]), maske.Maske([]), maske.Maske([REF])


@pytest.mark.parametrize("name", FORMEN)
def test_beobachtete_formen_bleiben(name, masken):
    """Jede beobachtete Form eines Sitzungsnamens bleibt unverändert, und check findet nichts; die Titelmaske kürzt
    denselben Text wie in 859cc57."""
    m, pruefend, titel = masken
    assert m.sitzungsname(name) == name
    assert not pruefend.sitzungsname_offen(name)
    assert titel(name, REF) == _ohne(FORMEN[name])
    assert not maske.Maske([REF]).offen(titel(name, REF), REF)


@pytest.mark.parametrize("name", HAUSNUMMERN)
def test_hausnummern_im_namen_weiter_maskiert(name, masken):
    """Eine Hausnummer im Sitzungsnamen fällt weiter weg (erste Stufe oder Positivliste), auch hinter einer ersten
    Zeile mit einer Ordnungszahl vor „Sondersitzung“, die stehen bleibt; die Titelmaske wie in 859cc57."""
    m, pruefend, titel = masken
    erwartet, titel_erwartet = map(_ohne, HAUSNUMMERN[name])
    assert m.sitzungsname(name) == erwartet
    assert pruefend.sitzungsname_offen(name) and not pruefend.sitzungsname_offen(erwartet)
    assert m.sitzungsname(VORZEILE + name) == VORZEILE + erwartet
    assert pruefend.sitzungsname_offen(VORZEILE + name) and not pruefend.sitzungsname_offen(VORZEILE + erwartet)
    assert titel(name, REF) == titel_erwartet
    # die Hausnummer steht in keinem der Ergebnisse
    for ergebnis in (erwartet, titel_erwartet):
        assert not re.search(r"(?<!\d)(?:5|12|3|7)(?!\d)", ergebnis.replace(OHNE_NR, "")), ergebnis


def test_grenzen_der_regel(masken):
    """Grenzen der Regel, festgehalten: Eine Nummer, die nicht direkt hinter der Straße steht, bleibt vor
    „Sondersitzung“ und als „(7.)“ stehen wie vor „Sitzung“; export und check folgen derselben Regel (kein Befund für
    das Ergebnis), die Titelmaske wie in 859cc57."""
    m, pruefend, titel = masken
    for name, (erwartet, titel_erwartet) in GRENZEN.items():
        erwartet, titel_erwartet = _ohne(erwartet), _ohne(titel_erwartet)
        assert m.sitzungsname(name) == erwartet, name
        assert pruefend.sitzungsname_offen(name) == (erwartet != name), name
        assert not pruefend.sitzungsname_offen(erwartet), name
        assert titel(name, REF) == titel_erwartet, name


def _titel_der_vorhandenen_tests():
    """Titel aus den Fällen der Titelmaske in tests/test_datenschutz_fixpunkt.py (je Fall der Titel: bei SCHREIBUNGEN
    der zweite Text hinter der Vorlagenart, sonst der erste) und die Texte dieser Datei."""
    titel = []
    for liste in (fixpunkt.SCHREIBUNGEN, fixpunkt.SCHREIBWEISEN_HNR, fixpunkt.SCHREIBWEISEN_R20A2,
                  fixpunkt.OHNE_STRASSE_R20A3, fixpunkt.FUNDSTELLEN_R20A3, fixpunkt.ORDNUNG_R20A3N):
        for fall in liste:
            texte = [fall] if isinstance(fall, str) else [t for t in fall if isinstance(t, str)]
            titel.append(texte[1] if liste is fixpunkt.SCHREIBUNGEN else texte[0])
    return titel + list(FORMEN) + list(HAUSNUMMERN) + [VORZEILE + n for n in HAUSNUMMERN] + list(GRENZEN)


def test_titelmaske_liest_die_liste_fuer_sitzungsnamen_nicht(monkeypatch):
    """Die Maske für Titel bleibt unverändert: Mit einer Liste für Sitzungsnamen, die jede Zahl kennt, liefern
    __call__, offen und ausschnitt für alle vorhandenen Titel dasselbe wie mit der echten Liste; für Sitzungsnamen wirkt
    dieselbe Ersetzung (Gegenprobe)."""
    titel = _titel_der_vorhandenen_tests()
    assert len(titel) > 200

    def lauf():
        m, pruefend = maske.Maske([REF]), maske.Maske([REF])
        return [(m(t, REF), pruefend.offen(t, REF), m.ausschnitt(t[:20], t, REF)) for t in titel]

    vorher = lauf()
    assert maske.Maske([]).sitzungsname("Unterausschuss 1") == f"Unterausschuss {OHNE_NR}"
    monkeypatch.setattr(maske, "_SITZUNG_BEKANNT", re.compile(r"\d+"))
    assert lauf() == vorher
    assert maske.Maske([]).sitzungsname("Unterausschuss 1") == "Unterausschuss 1"
    # restzahlen (Hinweis in check für Titel außerhalb der Maske) ebenso
    assert maske.restzahlen("Unterausschuss 1")


def test_gremium_ohne_vorspann():
    """Gremium einer Sitzung ohne Organisation: Ordnungszahl, „Sondersitzung“, „Gemeinsame Sondersitzung“,
    „(konstituierende) Sitzung“ und „Konstituierende Sitzung“ samt „des“ bzw. „der“ fallen weg wie bisher „Sitzung des“;
    danach die Schreibweise eines bekannten Gremiums wie bisher. Ein Vorspann, der nicht am Anfang steht, bleibt; mit
    Organisation gilt ihr Name."""
    rat = {"https://example.invalid/oparl/organizations/o1": "Rat"}
    faelle = [
        ("2. Sondersitzung des Unterausschusses Beispielbauten", "Unterausschuss Beispielbauten"),
        ("2. Sondersitzung des Unterausschuss Beispielbauten", "Unterausschuss Beispielbauten"),
        ("3. Gemeinsame Sondersitzung des Rates", "Rat"), ("Gemeinsame Sondersitzung des Rates", "Rat"),
        ("Sondersitzung des Rates", "Rat"), ("14. Sitzung des Rates", "Rat"), ("14.Sitzung des Rates", "Rat"),
        ("5 Sitzung des Rates", "Rat"), ("5, Sitzung des Rates", "Rat"), ("5.. Sitzung des Rates", "Rat"),
        (f"1. (konstituierende) Sitzung {BV}", "Bezirksvertretung Beispielstadt"),
        (f"1. Konstituierende Sitzung {A}", "Ausschuss für Musterwesen"),
        # wie bisher
        ("Sitzung des Rates", "Rat"), ("Gemeinsame Sitzung des Rates", "Rat"), ("Rat", "Rat"), ("", "unbekannt"),
        # Vorspann nicht am Anfang: der ganze Name (im Genitiv angeglichen)
        (f"14. Sitzung/2. Sondersitzung {A}", "14. Sitzung/2. Sondersitzung des Ausschuss für Musterwesen"),
    ]
    for sitzung, erwartet in faelle:
        assert export.gremium_der_sitzung({"name": sitzung, "organization": []}, rat) == erwartet, sitzung
        assert export.gremium_der_sitzung({"name": sitzung, "organization": list(rat)}, rat) == "Rat", sitzung
    # Schreibweise eines bekannten Gremiums (breiter Schlüssel, ohne „für“), auch über den Index
    bekannt = {"https://example.invalid/oparl/organizations/u1": "Unterausschuss für Beispielbauten"}
    m = {"name": "2. Sondersitzung des Unterausschusses Beispielbauten", "organization": []}
    assert export.gremium_der_sitzung(m, bekannt) == "Unterausschuss für Beispielbauten"
    assert export.gremium_der_sitzung(m, bekannt, export.gremien_index(bekannt)) == "Unterausschuss für Beispielbauten"


# erfundene Sitzungen für die Kette: Kennung → (Name, Organisation oder None); Beginn am Tag nach heute plus Stelle in
# der Liste (die ersten sechs stehen in „Aktuell“). „u1“: Gremium aus dem Namen gleich einer Organisation der Datenbank
SITZUNGEN = {
    "u1": ("2. Sondersitzung des Unterausschusses Beispielbauten", None),
    "u2": ("2. Sondersitzung des Unterausschusses Probebauten", None),
    "g3": (f"3. Gemeinsame Sondersitzung {A} (3.) und {B}", None),
    "k4": (f"1. (konstituierende) Sitzung {BV}", None),
    "z5": (f"5, Sitzung {BV}", None),
    "o6": (f"14. Sitzung {A} (2. Sondersitzung)", "rat"),
    "a7": (f"2. Sondersitzung {BV}\n-Sitzung ist auf den 3. Dezember verschoben worden!-", None),
    "p8": (f"5.. Sitzung {BV}", None),
    "s9": (f"14. Sitzung/2. Sondersitzung {A}", None),
}


def _aufbau(oparl):
    """Sitzungen ab morgen und eine Beschlussvorlage, beraten in „u2“ und „g3“; Abruf, Aufbau, Export. Liefert das Log
    von `export`."""
    b = oparl.b
    oparl.orgs.append({"id": f"{b}/organizations/ub", "name": "Unterausschuss Beispielbauten",
                       "organizationType": "Gremium", "modified": "2026-01-01T00:00:00+01:00"})
    for i, (k, (name, org)) in enumerate(SITZUNGEN.items(), 1):
        sitzung = {"id": f"{b}/meetings/{k}", "type": "https://schema.oparl.org/1.1/Meeting", "name": name,
                   "start": f"{date.today() + timedelta(days=i)}T16:00:00Z",
                   "web": f"https://example.invalid/sitzung/{k}", "modified": "2026-11-01T08:00:00+01:00"}
        if org:
            sitzung["organization"] = [f"{b}/organizations/{org}"]
        oparl.meetings.append(sitzung)
    oparl.papers.append({**oparl.paper(1), "id": f"{b}/papers/q1", "reference": "2903/2026",
                         "paperType": "Beschlussvorlage", "name": "[Testdaten] Sammelvorlage Ordnungszahlen",
                         "location": [],
                         "consultation": [{"id": f"{b}/consultations/q1{k}", "meeting": f"{b}/meetings/{k}",
                                           "role": "Beratung", "authoritative": False} for k in ("u2", "g3")]})
    sessionnet.fetch_all()
    build.build()
    export.export()


def test_kette_namen_unveraendert(oparl, capsys):
    """Orakel: Name jeder erfundenen Sitzung unverändert in zeit.json, termine.ics und `process[].meeting`, das Gremium
    aus dem Namen ohne Vorspann (export.gremium_der_sitzung) in zeit.json, termine.ics und index.json („Aktuell“);
    nirgends ein Ersatz der Maske. Log von `export`: von der Maske geändert 0; check ohne Befund."""
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
    erwartet = {k: export.gremium_der_sitzung({"name": name, "organization": [f"{oparl.b}/organizations/{org}"]
                                               if org else []}, namen) for k, (name, org) in SITZUNGEN.items()}
    assert erwartet["u1"] == "Unterausschuss Beispielbauten"   # Name einer Organisation der Datenbank
    assert erwartet["u2"] == "Unterausschuss Probebauten"
    assert erwartet["k4"] == erwartet["z5"] == erwartet["p8"] == "Bezirksvertretung Beispielstadt"
    # wie bisher bei „Sitzung der …“: Das Gremium ist der Rest des Namens, samt der zweiten Zeile
    assert erwartet["a7"] == "Bezirksvertretung Beispielstadt\n-Sitzung ist auf den 3. Dezember verschoben worden!-"
    assert erwartet["o6"] == "Rat"
    for k, (name, _) in SITZUNGEN.items():
        assert zeit[k]["name"] == name and zeit[k]["gremium"] == erwartet[k], k
        assert publish.ics_sitzungsname(ics[k]["DESCRIPTION"]) == name and ics[k]["SUMMARY"] == erwartet[k], k
    for k in list(SITZUNGEN)[:6]:
        assert aktuell[k]["gremium"] == erwartet[k], k
    for pfad in (base / "zeit.json", base / "termine.ics"):
        assert OHNE_NR not in pfad.read_text(), pfad
    # Gebietsdatei: die Namen der beiden Sitzungen bei der Beschlussvorlage unverändert
    gebiet = next(f for d in check.GEBIETSDATEIEN for f in (base / d).glob("*.json") if "2903/2026" in f.read_text())
    q = next(p for p in json.loads(gebiet.read_text())["papers"] if p["reference"] == "2903/2026")
    assert sorted(x["meeting"] for x in q["process"]) == sorted(SITZUNGEN[k][0] for k in ("u2", "g3"))
    # Gremium aus dem Namen: alle außer „u1“ (Organisation der Datenbank) und „o6“ (mit Organisation)
    assert "Sitzungen: Gremium aus dem Sitzungsnamen 7, Namen oder Gremien von der Maske geändert 0\n" in log
    capsys.readouterr()
    erg = check.datenschutz(db)
    db.close()
    assert erg["befunde"] == [] and erg["fehlend"] == [], erg
    assert erg["untersucht"]["sitzungen"] >= 2 * len(SITZUNGEN), erg["untersucht"]
