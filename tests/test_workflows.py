"""Workflows und Technikseite: jede Datei, jeder Schritt und jede Quelle hat eine Erklärung; der Hauptlauf ist bis zur
Information der Stadt gesperrt und veröffentlicht nie Testdaten."""
from pipeline import config, technikseite


def test_erklaerungen_vollstaendig():
    wfs = technikseite.workflows()
    assert {w["datei"] for w in wfs} <= set(technikseite.WORKFLOW_TEXT)
    pages = next(w for w in wfs if w["datei"] == "pages.yml")
    assert pages["schritte"] and set(pages["schritte"]) <= set(technikseite.SCHRITTE)
    assert set(config.SOURCES) <= set(technikseite.QUELLEN)


def test_hauptlauf_gesperrt_und_ohne_testdaten():
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "RATSATLAS_STADT_INFORMIERT: ${{ vars.RATSATLAS_STADT_INFORMIERT }}" in text
    assert ".get(\"testdaten\")" in text and "python tools/testdaten.py" not in text


def test_technikseite_ohne_bonn(tmp_path):
    from pipeline.gebietsseiten import _page
    technikseite.write(tmp_path, "https://koeln.ratsatlas.de/", _page)
    html = (tmp_path / "technik" / "index.html").read_text(encoding="utf-8")
    assert "Bonn" not in html and "allris" not in html and "Ratsatlas Köln" in html
