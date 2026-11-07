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


def test_vorlagenart_nennt_fraktion():
    assert einreichende("Sitzbänke", NEUE_WP, "FDP/KSG Antrag nach § 3") == ["FDP/KSG"]
    assert einreichende("Sitzbänke", NEUE_WP, "FDP Antrag nach § 3") == ["FDP"]


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
    ("Ausschuss für Wirtschaft und Digitalisierung", "wirtschaft"), ("Finanzausschuss", "wirtschaft"),
    ("Liegenschaftsausschuss", "wirtschaft"), ("Rechnungsprüfungsausschuss", "wirtschaft"),
    ("Ausschuss für Chancengerechtigkeit und Integration", "beteiligung"), ("Integrationsrat", "beteiligung"),
    ("Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden", "beteiligung"),
    ("Ausschuss für Klima, Umwelt und Grün", "umwelt"), ("Ausschuss für Schule und Weiterbildung", "bildung"),
    ("Jugendhilfeausschuss", "kinder"), ("Ausschuss für Kunst und Kultur", "kultur"), ("Sportausschuss", "kultur"),
    ("Betriebsausschuss Gebäudewirtschaft", "bauen"),
    ("Rat der Stadt Köln", None), ("Hauptausschuss", None), ("Bezirksvertretung 1 (Innenstadt)", None),
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
