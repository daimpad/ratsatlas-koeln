"""Geokodierung Köln (Stufe B, Titel) mit erfundenen Titeln gegen die Kölner Geodaten in data/geo."""
import pytest

from pipeline.build import bv_bezirk
from pipeline.geocode import Gazetteer, hausnummer_punkt_erlaubt


@pytest.fixture(scope="module")
def gaz():
    return Gazetteer()


def kurz(rows):
    return [(r["level"], r["ortsteil"] or r["bezirk"], r["method"], r["confidence"]) for r in rows]


def test_strasse_mit_stadtteil(gaz):
    assert kurz(gaz.locate("Umgestaltung der Venloer Straße in Ehrenfeld")) == [
        ("strasse", "Ehrenfeld", "strasse+ortsteil", "mittel")]


def test_hausnummer_punkt_nur_wenn_erlaubt(gaz):
    punkt = gaz.locate("Sanierung Wilhelm-David-Str. 56", punkt_erlaubt=True)
    assert kurz(punkt) == [("adresse", "Holweide", "strasse+hausnummer_punkt", "hoch")]
    assert punkt[0]["hausnummer"] == "56"
    # ohne Erlaubnis: Hausnummer bestimmt nur den Stadtteil, angezeigt wird der Straßenabschnitt
    assert kurz(gaz.locate("Sanierung Wilhelm-David-Str. 56")) == [("strasse", "Holweide", "strasse+hausnummer", "mittel")]


def test_gleichnamige_strasse_braucht_kontext(gaz):
    # „Aachener Straße 2“ gibt es in Porz und in der Neustadt/Süd: ohne Kontext kein Punkt
    ohne = gaz.locate("Umbau Aachener Straße 2", punkt_erlaubt=True)
    assert {r["method"] for r in ohne} == {"strasse_mehrdeutig"} and {"Porz", "Neustadt/Süd"} <= {r["ortsteil"] for r in ohne}
    # beratende Bezirksvertretung Porz entscheidet
    assert kurz(gaz.locate("Umbau Aachener Straße 2", ("Porz",), punkt_erlaubt=True)) == [
        ("adresse", "Porz", "strasse+hausnummer_punkt", "hoch")]


@pytest.mark.parametrize("titel, stadtteil, methode", [
    ("Neuer Spielplatz in Rath/Heumar", "Rath/Heumar", "ortsteil_name"),
    ("Spielplatz Rath-Heumar", "Rath/Heumar", "ortsteil_name"),
    ("Grünpflege in Heumar", "Rath/Heumar", "ortsteil_teilname"),
    ("Verkehr in Altstadt-Nord", "Altstadt/Nord", "ortsteil_name"),
    ("Bürgerhaus in Köln-Kalk", "Kalk", "ortsteil_name"),
    ("Neue Bänke in Porz", "Porz", "ortsteil_name"),
])
def test_stadtteilnamen_und_doppelnamen(gaz, titel, stadtteil, methode):
    assert kurz(gaz.locate(titel)) == [("ortsteil", stadtteil, methode, "mittel")]


@pytest.mark.parametrize("titel", ["Schulweg in der Altstadt", "Humboldt-Gymnasium Sanierung"])
def test_mehrdeutige_teilnamen_werden_nicht_verortet(gaz, titel):
    assert gaz.locate(titel) == []


@pytest.mark.parametrize("titel, bezirk", [
    ("Radverkehrskonzept Stadtbezirk Porz", "Porz"),
    ("Bezirksvertretung 3 (Lindenthal): Sitzungstermine", "Lindenthal"),
    ("Spielplätze im Bezirk Innenstadt", "Innenstadt"),
])
def test_bezirk_nur_in_eindeutiger_form(gaz, titel, bezirk):
    assert kurz(gaz.locate(titel)) == [("stadtbezirk", bezirk, "stadtbezirk_name", "mittel")]


def test_punktregel():
    vv = {"reference": "1234/2026", "name": "Sanierung Musterweg 3", "paperType": "Beschlussvorlage"}
    assert hausnummer_punkt_erlaubt(vv)
    assert hausnummer_punkt_erlaubt({"reference": "AN/1756/2026", "name": "Antrag", "paperType": "Antrag nach § 3"})
    assert not hausnummer_punkt_erlaubt({**vv, "name": "Anregung nach § 24 GO: Musterweg 3"})
    assert not hausnummer_punkt_erlaubt({**vv, "name": "Beschwerde Musterweg 3"})
    assert not hausnummer_punkt_erlaubt(vv, ["Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden"])
    assert not hausnummer_punkt_erlaubt({**vv, "reference": "AZ 191/21"})


@pytest.mark.parametrize("name, bezirk", [
    ("Bezirksvertretung 3 (Lindenthal)", "Lindenthal"), ("Bezirksvertretung 7", "Porz"),
    ("Bezirksvertretung Mülheim", "Mülheim"), ("Rat", None), ("Ausschuss für Umwelt", None)])
def test_bezirksvertretung(name, bezirk):
    assert bv_bezirk(name) == bezirk
