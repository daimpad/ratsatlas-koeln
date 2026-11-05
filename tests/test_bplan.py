"""Bebauungspläne Köln: Nummernschema der Landesschnittstelle, Erkennung in erfundenen Titeln, Zuordnung zu Flächen."""
import json

from pipeline import bplan, config, geocode, plans
from pipeline.geo import Ortsteile


def test_name_aus_landesnummer():
    assert bplan.name("63429.06.000.00") == "63429/06"
    assert bplan.name("5843.03.000.00") == "5843/03"
    assert bplan.name("67457.03.001.00") == "67457/03 (67457.03.001.00)"
    assert bplan.name("60537.02.000.00.A") == "60537/02 (60537.02.000.00.A)"
    assert bplan.name("76380.003.00.eA1") is None


def test_plannummer_im_titel_nicht_drucksache(monkeypatch, tmp_path):
    datei = tmp_path / "bplan.geojson"
    datei.write_text('{"type":"FeatureCollection","features":[]}')
    monkeypatch.setattr(config, "BPLAN", datei)
    assert geocode.plan_numbers("Bebauungsplan 63429/06 Testplatz – Teilaufhebung")[0][0] == "63429/06"
    assert geocode.plan_numbers("Bebauungsplan, Drucksache 1234/2025") == []
    assert geocode.plan_numbers("Antrag zu 63429/06 ohne Stichwort") == []


def test_ohne_plandaten_keine_erkennung(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BPLAN", tmp_path / "fehlt.geojson")
    assert geocode.plan_numbers("Bebauungsplan 63429/06") == []


def _plaene(tmp_path, namen):
    quadrat = {"type": "Polygon", "coordinates": [[[6.92, 50.92], [6.921, 50.92], [6.921, 50.921], [6.92, 50.921], [6.92, 50.92]]]}
    datei = tmp_path / "bplan.geojson"
    datei.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": quadrat, "properties": {"name": n}} for n in namen]}))
    return plans.Plans(datei)


def test_klassen(tmp_path):
    p = _plaene(tmp_path, ["11111/01", "22222/02 (22222.02.001.00)", "22222/02 (22222.02.002.00)"])
    assert p.classify("11111/01")[0] == "eindeutig"
    assert p.classify("22222/02")[0] == "mehrdeutig"
    assert p.classify("33333/03")[0] == "nicht_im_datensatz"


def test_flaeche_im_stadtteil(tmp_path):
    p = _plaene(tmp_path, ["11111/01"])
    orte, zeilen = plans.plan_locations([("p1", "11111/01", "Bebauungsplan 11111/01")], Ortsteile(), p)
    assert zeilen and zeilen[0][3] == "bebauungsplan" and zeilen[0][4] == "hoch"
    assert next(iter(orte.values()))[4] == "Bebauungsplan 11111/01"


def test_datensatz_im_repository():
    d = json.loads(config.BPLAN.read_text())
    assert len(d["features"]) > 1000
    assert "dl-de/by 2.0" in d["meta"]["license"]
    assert all(geocode.re.fullmatch(r"\d{4,6}/\d{2}(?: \(.+\))?", f["properties"]["name"]) for f in d["features"])
