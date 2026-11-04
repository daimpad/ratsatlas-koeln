"""Kölner Geodaten in data/geo (abgeleitet mit `python -m pipeline geo-koeln`)."""
import json

from pipeline import config
from pipeline.geo import Ortsteile
from pipeline.geodaten import strassenname


def test_strassenname():
    assert strassenname("Aachener Str.") == "Aachener Straße"
    assert strassenname("Edisonstr.") == "Edisonstraße"
    assert strassenname("Straße des 17. Juni") == "Straße des 17. Juni"
    assert strassenname("An St. Heinrich") == "An St. Heinrich"


def test_gebiete_vollstaendig_und_im_bonner_format():
    teile = json.loads(config.ORTSTEILE.read_text())["features"]
    bezirke = json.loads(config.STADTBEZIRKE.read_text())["features"]
    assert len(teile) == 86 and len(bezirke) == 9
    assert set(teile[0]["properties"]) == {"ortsteil", "ortsteil_bez", "bezirk", "bezirk_bez"}
    assert {f["properties"]["bezirk_bez"] for f in teile} == {f["properties"]["bezirk_bez"] for f in bezirke}


def test_punkt_im_stadtteil():
    o = Ortsteile()
    assert o.locate(6.9583, 50.9413)["ortsteil_bez"] == "Altstadt/Nord"     # Domumgebung
    assert o.locate(7.0, 50.0) is None                                     # außerhalb Kölns


def test_gleichnamige_strassen_bleiben_getrennt():
    s = json.loads(config.STRASSEN.read_text())["streets"]
    lagen = s["Dauner Straße"]
    assert {e["ortsteil"] for e in lagen} == {"Immendorf", "Sülz"}
    assert len({e["component"] for e in lagen}) == 2
