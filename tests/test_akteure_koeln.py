"""Einreichende im Kölner Rat (pipeline/actors.py) und Kölner Gremiennamen – mit ERFUNDENEN Titeln, nicht aus echten
Vorlagen. Grundlage der Namen: explore/ergebnisse/fraktionen_rat.tsv, fraktionen_bv.tsv, gremien_koeln.tsv."""
import pytest

from pipeline import glossar, topics
from pipeline.actors import originators
from pipeline.build import bv_bezirk
from pipeline.geocode import hausnummer_punkt_erlaubt

ANTRAG = "Antrag nach § 3 der Geschäftsordnung des Rates"
ANFRAGE = "Anfrage nach § 4 der Geschäftsordnung des Rates"
VOR_WAHL, UEBERGANG, NEUE_WP = "2024-05-02", "2025-10-01", "2026-01-15"


def einreichende(titel, datum, art=ANTRAG, orgs=(), bezirke=()):
    return [r["actor"] for r in originators({"paperType": art, "date": datum, "name": titel}, list(orgs), bezirke)]


@pytest.mark.parametrize("titel, datum, erwartet", [
    # FDP/KSG: Schreibweise „FDP/KSG“ ab 17.09.2025, nie zusätzlich FDP oder KSG
    ("Antrag der FDP/KSG-Fraktion betreffend Sitzbänke am Musterweg", NEUE_WP, ["FDP/KSG"]),
    ("Antrag der Fraktion FDP / KSG betreffend Sitzbänke am Musterweg", "2025-09-20", ["FDP/KSG"]),
    ("Antrag der FDP/KSG-Fraktion betreffend Sitzbänke am Musterweg", VOR_WAHL, []),  # gab es noch nicht
    # „FDP-Fraktion“: bis zum Ende der Wahlperiode 2020–2025 die FDP-Fraktion, danach die Fraktion FDP/KSG
    ("Antrag der FDP-Fraktion betreffend Sitzbänke am Musterweg", VOR_WAHL, ["FDP"]),
    ("Antrag der FDP-Fraktion betreffend Sitzbänke am Musterweg", UEBERGANG, ["FDP"]),
    ("Antrag der FDP-Fraktion betreffend Sitzbänke am Musterweg", NEUE_WP, ["FDP/KSG"]),
    ("Antrag der FDP-Fraktion betreffend Sitzbänke am Musterweg", "", ["FDP"]),  # ohne Datum keine Umdeutung
    # „FDP“ ohne „Fraktion“ bleibt FDP (auch ein Mitglied einer Bezirksvertretung möglich)
    ("Anfrage der FDP betreffend Sitzbänke am Musterweg", NEUE_WP, ["FDP"]),
    # KSG allein erst ab der Kommunalwahl 14.09.2025
    ("Antrag der KSG betreffend Sitzbänke am Musterweg", NEUE_WP, ["Kölner Stadtgesellschaft"]),
    ("Antrag der Kölner Stadtgesellschaft (KSG) betreffend Sitzbänke", "2025-09-20", ["Kölner Stadtgesellschaft"]),
    ("Antrag der KSG betreffend Sitzbänke am Musterweg", "2025-09-10", []),
    # Gruppen und mehrere Fraktionen
    ("Anfrage der Gruppe BSW betreffend Öffnungszeiten im Musterbad", NEUE_WP, ["BSW"]),
    ("Antrag der Fraktionen SPD, GRÜNE und Volt betreffend Spielgeräte im Musterpark", NEUE_WP,
     ["SPD", "Grüne", "Volt"]),
    ("Antrag der Fraktionen Bündnis 90/Die Grünen, CDU und Volt betreffend Spielgeräte", VOR_WAHL,
     ["Grüne", "CDU", "Volt"]),
    ("Gemeinsamer Antrag von Die PARTEI und GUT & KLIMA FREUNDE betreffend Sitzbänke", NEUE_WP,
     ["Die PARTEI", "GUT & KLIMA FREUNDE"]),
    ("Antrag der Fraktion Die Linke betreffend Mieten am Musterweg", NEUE_WP, ["Die Linke"]),
    ("Antrag der Grünen-Fraktion zum Musterpark", VOR_WAHL, ["Grüne"]),
    # Bezeichnungen nur der Wahlperiode 2020–2025
    ("Antrag der Fraktion Die FRAKTION betreffend Sitzbänke", "2022-03-01", ["Die PARTEI"]),
    ("Antrag der Fraktion Die FRAKTION betreffend Sitzbänke", NEUE_WP, []),
    ("Antrag der Gruppe Die PARTEI im Rat betreffend Sitzbänke", "2025-03-01", ["Die PARTEI"]),
    ("Antrag der Ratsgruppe GUT betreffend Sitzbänke", "2021-03-01", ["GUT Köln"]),
    ("Antrag der Ratsgruppe GUT betreffend Sitzbänke", NEUE_WP, []),
    ("Antrag der Ratsgruppe Klima Freunde & Gut betreffend Sitzbänke", VOR_WAHL, ["Klima Freunde"]),
    ("Antrag der Klima Freunde betreffend Sitzbänke", NEUE_WP, []),
    ("Anfrage der Freien Wähler Köln betreffend Sitzbänke", "2022-03-01", ["Freie Wähler Köln"]),
    ("Anfrage von FWK betreffend Sitzbänke", NEUE_WP, []),
    # „GUT & KLIMA FREUNDE“ erst nach der Fusion (29.09.2024); vorher weder GUT noch Klima Freunde
    ("Gemeinsamer Antrag von Die PARTEI und GUT & KLIMA FREUNDE betreffend Sitzbänke", "2023-03-01", ["Die PARTEI"]),
])
def test_einreichende_nach_datum_und_schreibweise(titel, datum, erwartet):
    art = ANFRAGE if titel.startswith("Anfrage") else ANTRAG
    assert einreichende(titel, datum, art) == erwartet


@pytest.mark.parametrize("titel, erwartet", [
    ("Umgestaltung Linkes Rheinufer: Antrag der CDU-Fraktion", ["CDU"]),
    ("Antrag der CDU-Fraktion Umgestaltung Linkes Rheinufer", ["CDU"]),
    ("Antrag der SPD-Fraktion Beleuchtung am Linken Rheinufer und Linke Rheinseite", ["SPD"]),
    ("Neugestaltung Voltaplatz: Anfrage der SPD-Fraktion", ["SPD"]),
    ("Antrag der AfD-Fraktion Pflaster am Voltaplatz", ["AfD"]),
    ("Anfrage zur Parteienfinanzierung", []),
    ("Antrag der Volt-Fraktion Parteienfinanzierung in Köln", ["Volt"]),
    ("Antrag Grüne Welle auf dem Musterring", []),
    ("Antrag der CDU-Fraktion Gutachten zum Gut Musterhof", ["CDU"]),
    ("Antrag der SPD-Fraktion Nutzung KSG-Gelände", ["SPD"]),
])
def test_keine_fehltreffer(titel, erwartet):
    for datum in (VOR_WAHL, NEUE_WP):
        assert einreichende(titel, datum) == erwartet, datum


@pytest.mark.parametrize("titel, datum, erwartet", [
    # „Die Linke“, „Grüne“ nach „Die“, „der“, „Fraktion“, „Gruppe“ auch vor einem anderen Wort (Titel ohne „betreffend“)
    ("Antrag der Fraktion Die Linke Mieten am Musterweg", NEUE_WP, ["Die Linke"]),
    ("Antrag der Fraktion Die Linke Ehrenfeld betreffend Sitzbänke", NEUE_WP, ["Die Linke"]),
    ("Antrag der Grünen Sitzbänke am Musterweg", NEUE_WP, ["Grüne"]),
    ("Antrag der Grünen Porz betreffend Sitzbänke", NEUE_WP, ["Grüne"]),
    # Name in Anführungszeichen nach „Fraktion“ oder „…gruppe“
    ("Antrag der Gruppe „Die PARTEI“ betreffend Sitzbänke", NEUE_WP, ["Die PARTEI"]),
    ('Antrag der Fraktion "Die Linke" betreffend Sitzbänke', NEUE_WP, ["Die Linke"]),
    ("Antrag der Wählergruppe „GUT & KLIMA FREUNDE“ betreffend Sitzbänke", NEUE_WP, ["GUT & KLIMA FREUNDE"]),
    ("Antrag der Gruppe „Die PARTEI“ und der Fraktion „Die Linke“ betreffend Sitzbänke", NEUE_WP,
     ["Die PARTEI", "Die Linke"]),
    # Thema in Anführungszeichen beendet die Einreichenden weiterhin
    ("Antrag der SPD-Fraktion „Sitzbänke wie bei der CDU“", NEUE_WP, ["SPD"]),
    # Aufzählungen mit Schrägstrich
    ("Antrag der Fraktionen CDU/FDP betreffend Sitzbänke", VOR_WAHL, ["CDU", "FDP"]),
    ("Antrag der Fraktionen GRÜNE/CDU/FDP betreffend Sitzbänke", VOR_WAHL, ["Grüne", "CDU", "FDP"]),
    # „Fraktion FDP“ wie „Fraktion der FDP“ (Regel 2)
    ("Antrag der Fraktion FDP betreffend Sitzbänke", NEUE_WP, ["FDP/KSG"]),
    ("Antrag der Fraktion FDP betreffend Sitzbänke", VOR_WAHL, ["FDP"]),
    ("Antrag der Fraktion der FDP betreffend Sitzbänke", NEUE_WP, ["FDP/KSG"]),
    # Kette der Einreichenden: Verbindungswörter zwischen zwei Fraktionen
    ("Antrag der Kölner Stadtgesellschaft (KSG) und der SPD-Fraktion betreffend Sitzbänke", NEUE_WP,
     ["Kölner Stadtgesellschaft", "SPD"]),
    ("Antrag der SPD-Fraktion und der Fraktion Die Linke betreffend Sitzbänke", NEUE_WP, ["SPD", "Die Linke"]),
    ("Antrag der CDU-Fraktion im Rat der Stadt Köln und der FDP/KSG-Fraktion betreffend Sitzbänke", NEUE_WP,
     ["CDU", "FDP/KSG"]),
    ("Antrag der SPD-Fraktion gemeinsam mit der CDU-Fraktion betreffend Sitzbänke", NEUE_WP, ["SPD", "CDU"]),
    ("Antrag der Fraktionen SPD, GRÜNE, Die Linke sowie der Gruppe BSW betreffend Sitzbänke", NEUE_WP,
     ["SPD", "Grüne", "Die Linke", "BSW"]),
    ("Antrag der Ratsgruppe GUT und der Ratsgruppe Klima Freunde betreffend Sitzbänke", "2021-03-01",
     ["GUT Köln", "Klima Freunde"]),
    # Koalition und interfraktionell vor, in oder direkt nach der Kette
    ("Antrag der Koalition aus GRÜNEN, CDU und Volt betreffend Sitzbänke", VOR_WAHL,
     ["Grüne", "CDU", "Volt", "Koalition"]),
    ("Antrag der Koalitionsfraktionen betreffend Sitzbänke", VOR_WAHL, ["Koalition"]),
    ("Interfraktioneller Antrag der Fraktionen SPD und CDU betreffend Sitzbänke", NEUE_WP,
     ["SPD", "CDU", "interfraktionell"]),
])
def test_einreichende_treffer(titel, datum, erwartet):
    assert einreichende(titel, datum) == erwartet


@pytest.mark.parametrize("titel, erwartet", [
    # Parteien und Wörter im Thema zählen nicht als Einreichende (Titel ohne „betreffend“)
    ("Antrag der SPD-Fraktion Umsetzung des Koalitionsvertrags im Bund prüfen", ["SPD"]),
    ("Antrag der SPD-Fraktion Bruch der Koalition im Bund", ["SPD"]),
    ("Anfrage der AfD-Fraktion Stellungnahme der Fraktion Die Linke zum Musterpark", ["AfD"]),
    ("Anfrage der AfD-Fraktion Stellungnahme der Fraktion Die Linke betreffend Musterpark", ["AfD"]),
    ("Antrag der SPD-Fraktion Neugestaltung Musterpark u.a. mit CDU", ["SPD"]),
    # Grüne/Linke als Adjektiv
    ("Antrag der CDU-Fraktion Grüne Infrastruktur im Veedel", ["CDU"]),
    ("Antrag der CDU-Fraktion Erhalt der Grünen Lunge am Musterweg", ["CDU"]),
    ("Antrag der CDU-Fraktion Grünen Pfeil für Radfahrende am Musterring", ["CDU"]),
    ("Antrag der Grünen Jugend betreffend Sitzbänke", []),
    ("Anfrage Linke Spur auf der Musterbrücke", []),
])
def test_keine_fehltreffer_im_thema(titel, erwartet):
    for datum in (VOR_WAHL, NEUE_WP):
        assert einreichende(titel, datum) == erwartet, datum


@pytest.mark.parametrize("art, erwartet", [
    ("FDP/KSG Antrag nach § 3", ["FDP/KSG"]), ("FDP Antrag nach § 3", ["FDP"]),
    ("Die Linke Antrag nach § 3", ["Die Linke"]), ("DIE LINKE Antrag nach § 3", ["Die Linke"]),
    ("Grüne Antrag nach § 3", ["Grüne"]), ("Grüne Anfrage nach § 4", ["Grüne"]),
    ("Die Linke Anfrage nach § 4", ["Die Linke"]), ("Bündnis 90/Die Grünen Antrag nach § 3", ["Grüne"]),
])
def test_vorlagenart_nennt_fraktion(art, erwartet):
    assert einreichende("Sitzbänke", NEUE_WP, art) == erwartet


def test_stadtbezirke_wie_geocode():
    from pipeline.actors import STADTBEZIRKE
    from pipeline.geocode import BEZIRKE_KOELN
    assert set(STADTBEZIRKE) == set(BEZIRKE_KOELN.values())


def test_bezirksfraktion():
    r = originators({"paperType": ANTRAG, "date": NEUE_WP, "name": "Antrag der KSG-Bezirksfraktion betreffend Sitzbänke"},
                    [], {"Rodenkirchen"})
    assert [(x["actor"], x["actor_type"]) for x in r] == [
        ("Kölner Stadtgesellschaft-Bezirksfraktion Rodenkirchen", "Bezirksfraktion")]
    assert topics.party(r[0]["actor"], r[0]["actor_type"]) == "Kölner Stadtgesellschaft"


ORGS = [
    {"id": "o-fdp", "name": "FDP-Fraktion im Rat", "classification": "Fraktion", "endDate": "2025-10-31"},
    {"id": "o-fdpksg", "name": "FDP/KSG-Fraktion im Rat", "classification": "Fraktion", "startDate": "2025-11-01"},
    {"id": "o-gkf", "name": "GUT & KLIMA FREUNDE", "classification": "Einzelmandate", "startDate": "2025-11-01"},
    {"id": "o-gut", "name": "Ratsgruppe GUT", "classification": "Gruppen", "endDate": "2025-10-31"},
    {"id": "o-partei", "name": "Ratsgruppe Die PARTEI", "classification": "Gruppen", "startDate": "2025-11-01"},
    {"id": "o-fraktion", "name": "Die FRAKTION", "classification": "Fraktion", "endDate": "2025-10-31"},
]


def test_organisation_nach_datum():
    def org(titel, datum):
        r = originators({"paperType": ANTRAG, "date": datum, "name": titel}, ORGS)
        return [(x["actor"], x["organization_id"], x["method"]) for x in r]
    assert org("Antrag der FDP-Fraktion betreffend Sitzbänke", VOR_WAHL) == [("FDP", "o-fdp", "title")]
    assert org("Antrag der FDP-Fraktion betreffend Sitzbänke", NEUE_WP) == [("FDP/KSG", "o-fdpksg", "title")]
    assert org("Antrag der FDP/KSG-Fraktion betreffend Sitzbänke", NEUE_WP) == [("FDP/KSG", "o-fdpksg", "title")]
    assert org("Antrag von GUT & KLIMA FREUNDE betreffend Sitzbänke", NEUE_WP) == [
        ("GUT & KLIMA FREUNDE", "o-gkf", "title")]
    assert org("Antrag der Ratsgruppe GUT betreffend Sitzbänke", "2021-03-01") == [("GUT Köln", "o-gut", "title")]


@pytest.mark.parametrize("org_name, anzeige", [
    ("FDP/KSG-Fraktion im Rat", "FDP/KSG"), ("FDP-Fraktion im Rat", "FDP"), ("GUT & KLIMA FREUNDE", "GUT & KLIMA FREUNDE"),
    ("Ratsgruppe GUT", "GUT Köln"), ("Ratsgruppe Die PARTEI", "Die PARTEI"), ("Die FRAKTION", "Die PARTEI"),
    ("Gruppe BSW", "BSW"), ("Fraktion Bündnis 90/Die Grünen", "Grüne"), ("Fraktion Die Linke", "Die Linke"),
])
def test_originator_organization(org_name, anzeige):
    """Belegt aus `originatorOrganization`: Anzeigename aus dem Organisationsnamen, ohne Datumsregel."""
    paper = {"paperType": ANTRAG, "date": NEUE_WP, "name": "Sitzbänke", "originatorOrganization": ["o1"]}
    r = originators(paper, [{"id": "o1", "name": org_name}])
    assert (r[0]["actor"], r[0]["method"], r[0]["evidence"]) == (anzeige, "originatorOrganization", org_name)


@pytest.mark.parametrize("gremium, thema", [
    # 2025–2030 und 2020–2025 (gremien_koeln.tsv, Zeilen „belegt“)
    ("Ausschuss für Stadtentwicklung und regionale Zusammenarbeit", "bauen"), ("Stadtentwicklungsausschuss", "bauen"),
    ("Ausschuss für Bauen und Wohnen", "bauen"), ("Bauausschuss", "bauen"),
    ("Mobilitätsausschuss", "verkehr"), ("Verkehrsausschuss", "verkehr"),
    ("Ausschuss für Soziales, Gesundheit, Seniorinnen und Senioren", "soziales"), ("Gesundheitsausschuss", "soziales"),
    ("Ausschuss für Wirtschaft und Digitalisierung", "wirtschaft"), ("Wirtschaftsausschuss", "wirtschaft"),
    ("Digitalisierungsausschuss", "wirtschaft"), ("Finanzausschuss", "wirtschaft"),
    ("Liegenschaftsausschuss", "wirtschaft"), ("Rechnungsprüfungsausschuss", "wirtschaft"),
    ("Ausschuss für Chancengerechtigkeit und Integration", "beteiligung"), ("Integrationsrat", "beteiligung"),
    ("Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden", "beteiligung"),
    ("Ausschuss für Klima, Umwelt und Grün", "umwelt"), ("Ausschuss für Schule und Weiterbildung", "bildung"),
    ("Jugendhilfeausschuss", "kinder"), ("Ausschuss für Kunst und Kultur", "kultur"), ("Sportausschuss", "kultur"),
    ("Betriebsausschuss Gebäudewirtschaft", "bauen"),
    ("Rat der Stadt Köln", None), ("Hauptausschuss", None), ("Bezirksvertretung 1 (Innenstadt)", None),
    # Bonner Sonderfälle entfernt (keine Kölner Gremien dieses Namens belegt)
    ("Betriebsausschuss SGB", None), ("Bau- und Vergabeausschuss", None),
])
def test_gremium_thema(gremium, thema):
    assert topics._gremium_theme(gremium) == thema


@pytest.mark.parametrize("name, bezirk", [
    ("BV Innenstadt", "Innenstadt"), ("BV Mülheim", "Mülheim"), ("Bezirksvertretung 9 (Mülheim)", "Mülheim"),
    ("BVG", None)])
def test_bezirksvertretung_kurzform(name, bezirk):
    assert bv_bezirk(name) == bezirk


def test_beschwerdeausschuss_ohne_hauskoordinate():
    vv = {"reference": "1234/2026", "paperType": "Beschlussvorlage", "name": "Sanierung Musterweg 3"}
    assert hausnummer_punkt_erlaubt(vv, ["Bezirksvertretung 1 (Innenstadt)"])
    assert not hausnummer_punkt_erlaubt(vv, ["Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden"])


def test_glossar_gruppe():
    g = {b["begriff"]: b for b in glossar.glossar()["begriffe"]}
    assert g["Gruppe"]["gruppe"] == "gremium" and "§ 56 GO NRW" in g["Gruppe"]["fundstelle"]
    # keine Liste Kölner Gruppen, solange der Abgleich mit dem Ratsinformationssystem fehlt
    text = " ".join(str(v) for v in g["Gruppe"].values())
    assert "BSW" not in text and "PARTEI" not in text


def test_kurzfassung_parteien_wie_actors():
    from pipeline import kurzfassung
    from pipeline.actors import PARTIES
    assert set(kurzfassung.PARTEIEN) == {p.name for p in PARTIES} and "BBB" not in kurzfassung.PARTEIEN
    fremd = kurzfassung.fremder_akteur
    assert fremd("Die Fraktion FDP/KSG beantragt neue Sitzbänke.", "Antrag der SPD-Fraktion") == "FDP/KSG"
    assert fremd("Die Grünen beantragen neue Sitzbänke.", "Antrag der Fraktion Bündnis 90/Die Grünen") is None
    assert fremd("Es geht um Bänke am Linken Rheinufer.", "Antrag der CDU-Fraktion") is None


# Kölner Vorlagenart „… BV<n> (<Fraktion>)“ (Stufe 1, 07.11.2026) als strukturierte Quelle – ERFUNDENE Titel in genau
# diesen Mustern
@pytest.mark.parametrize("art, erwartet", [
    ("Antrag nach § 3 BV2 (CDU)", ["CDU-Bezirksfraktion Rodenkirchen"]),
    ("Änderungsantrag BV1 (Grüne)", ["Grüne-Bezirksfraktion Innenstadt"]),
    ("Anfrage nach § 4 BV9 (Die Linke)", ["Die Linke-Bezirksfraktion Mülheim"]),
    ("Antrag nach § 3 BV7 (SPD, Volt)", ["SPD-Bezirksfraktion Porz", "Volt-Bezirksfraktion Porz"]),
    ("Antrag nach § 3 BV4 (FDP/KSG)", ["FDP/KSG-Bezirksfraktion Ehrenfeld"]),
])
def test_bezirksfraktion_aus_der_vorlagenart(art, erwartet):
    # der Titel nennt eine andere Fraktion: die strukturierte Vorlagenart gilt
    r = originators({"paperType": art, "date": NEUE_WP, "name": "Antrag der SPD-Fraktion betreffend Sitzbänke"}, [],
                    {"Kalk"})
    assert [x["actor"] for x in r] == erwartet
    assert all((x["actor_type"], x["method"], x["evidence"]) == ("Bezirksfraktion", "paper_type", art) for x in r)
    assert topics.party(r[0]["actor"], r[0]["actor_type"]) == erwartet[0].split("-Bezirksfraktion")[0]


@pytest.mark.parametrize("art, titel, datum, erwartet", [
    # nicht erkannte Angabe in Klammern (etwa ein Name): keine Übernahme, sonst wie bisher (Titel, dann Vorlagenart)
    ("Antrag nach § 3 BV3 (Testperson Musterfrau)", "Sitzbänke am Musterweg", NEUE_WP, []),
    ("Antrag nach § 3 BV3 (Testperson Musterfrau)", "Antrag der CDU-Fraktion betreffend Sitzbänke", NEUE_WP, ["CDU"]),
    # Datumsregel: „FDP/KSG“ gab es vor dem 17.09.2025 nicht
    ("Antrag nach § 3 BV4 (FDP/KSG)", "Sitzbänke am Musterweg", VOR_WAHL, []),
    # keine Bezirksvertretung 10; Verwaltungsvorlagen bleiben Verwaltung
    ("Antrag nach § 3 BV10 (CDU)", "Sitzbänke am Musterweg", NEUE_WP, ["CDU"]),
    ("Beschlussvorlage Bezirksvertretung", "Sitzbänke am Musterweg", NEUE_WP, ["Verwaltung"]),
])
def test_vorlagenart_ohne_erkannte_bezirksfraktion(art, titel, datum, erwartet):
    r = originators({"paperType": art, "date": datum, "name": titel}, [])
    assert [x["actor"] for x in r] == erwartet and all(x["actor_type"] != "Bezirksfraktion" for x in r)


def test_vorlagenart_bezirksvertretung_nummern_wie_hauptsatzung():
    from pipeline.actors import STADTBEZIRKE, bv_vorlagenart
    from pipeline.geocode import BEZIRKE_KOELN
    assert STADTBEZIRKE == tuple(BEZIRKE_KOELN[n] for n in range(1, 10))
    assert bv_vorlagenart("Antrag nach § 3 BV2 (CDU)") == (2, "Rodenkirchen", "CDU")
    assert bv_vorlagenart("Änderungsantrag BV 8 (Grüne)") == (8, "Kalk", "Grüne")
    for art in ("Antrag nach § 3 BV10 (CDU)", "Antrag nach § 3 der Geschäftsordnung des Rates", "BVG (CDU)", None):
        assert bv_vorlagenart(art) is None, art
    orgs = [{"id": "o-bv2-cdu", "name": "CDU-Bezirksfraktion Rodenkirchen", "classification": "Bezirksfraktionen (intern)"},
            {"id": "o-bv3-cdu", "name": "CDU-Bezirksfraktion Lindenthal", "classification": "Bezirksfraktionen (intern)"}]
    r = originators({"paperType": "Antrag nach § 3 BV2 (CDU)", "date": NEUE_WP, "name": "Sitzbänke"}, orgs)
    assert [x["organization_id"] for x in r] == ["o-bv2-cdu"]
