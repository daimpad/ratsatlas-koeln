"""Geokodierung Köln (Stufe B, Titel) mit erfundenen Titeln gegen die Kölner Geodaten in data/geo."""
import pytest

from pipeline.build import bv_bezirk
from pipeline.geocode import Gazetteer, hausnummer_punkt_erlaubt, punkt_ausschluss


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


def test_punktregel_einwohneranfrage():
    """Kölner Einwohneranfrage (natürliche Person, Stufe 2: „Einwohneranfrage nach § 39 Abs. 6“, Drucksache wie
    Anträge): keine Hauskoordinate, auch ohne Hinweis im Titel. Die Einwohnerbefragung der Verwaltung gilt nicht als
    Eingabe, bekommt aber seit Runde 19b ebenfalls keine Hauskoordinate: maske.py blendet die Hausnummer in Titeln mit
    „Einwohner“ aus, und neben einem Titel ohne Hausnummer steht keine Anschrift mit Hauskoordinate."""
    ew = {"reference": "AN/0012/2026", "name": "Zustand des Gehwegs vor Musterweg 3",
          "paperType": "Einwohneranfrage nach § 39 Abs. 6"}
    assert not hausnummer_punkt_erlaubt(ew)
    assert not hausnummer_punkt_erlaubt({"reference": "1234/2026", "paperType": "Mitteilung",
                                         "name": "Beantwortung einer Einwohnerfrage: Musterweg 3"})
    befragung = {"reference": "1234/2026", "paperType": "Beschlussvorlage",
                 "name": "Einwohnerbefragung zur Umgestaltung Musterweg 3"}
    assert punkt_ausschluss(befragung) == "maske" and not hausnummer_punkt_erlaubt(befragung)


def test_ohne_hauskoordinate_verbundene_vorlagen():
    """Verbundene Vorlagen über mehrere Stufen und in beiden Richtungen (geocode.sperrmenge ohne Drucksachen)."""
    from pipeline.geocode import sperrmenge
    rel = [("anfrage", "antwort"), ("antwort", "nachtrag"), ("vorlage", "aenderung")]
    assert set(sperrmenge({"anfrage"}, rel, {})) == {"anfrage", "antwort", "nachtrag"}
    assert set(sperrmenge({"nachtrag"}, rel, {})) == {"anfrage", "antwort", "nachtrag"}
    assert set(sperrmenge({"einzeln"}, rel, {})) == {"einzeln"}
    assert set(sperrmenge(set(), rel, {})) == set()


@pytest.mark.parametrize("name, bezirk", [
    ("Bezirksvertretung 3 (Lindenthal)", "Lindenthal"), ("Bezirksvertretung 7", "Porz"),
    ("Bezirksvertretung Mülheim", "Mülheim"), ("Rat", None), ("Ausschuss für Umwelt", None)])
def test_bezirksvertretung(name, bezirk):
    assert bv_bezirk(name) == bezirk


def test_einreichende_koeln():
    from pipeline.actors import originators
    titel = {"paperType": "Antrag nach § 3 der Geschäftsordnung des Rates", "date": "2026-01-01",
             "name": "Antrag der CDU-Fraktion betreffend Radweg"}
    assert [r["actor"] for r in originators(titel, [])] == ["CDU"]
    art = {"paperType": "FDP Antrag nach § 3", "date": "2026-01-01", "name": "Radweg"}
    assert [r["actor"] for r in originators(art, [])] == ["FDP"]
    eingabe = {"paperType": "Anregungen und Beschwerden", "date": "2026-01-01", "name": "Anregung: Musterweg 3"}
    assert [r["actor_type"] for r in originators(eingabe, [])] == ["Einwohner:in"]
    belegt = {"paperType": "Antrag nach § 3", "date": "2026-01-01", "name": "x", "originatorOrganization": ["o1"]}
    r = originators(belegt, [{"id": "o1", "name": "SPD-Fraktion im Rat"}])
    assert (r[0]["actor"], r[0]["method"]) == ("SPD", "originatorOrganization")
