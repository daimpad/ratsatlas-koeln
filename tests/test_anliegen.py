"""Mängelmelder (Bonner Zusatzthema, abgeschaltet): Gesamtwerte unter „stadt“, wie die Seite sie liest (site/app.js)."""
import json

from pipeline import anliegen


def test_anliegen_seite_schluessel_stadt(tmp_path):
    archiv = tmp_path / "archiv" / "anliegen"
    archiv.mkdir(parents=True)
    zeilen = [{"nummer": f"{i}-2026", "tag": "2026-10-01", "gruppe": "Abfall", "ortsteil": "Neuehrenfeld",
               "stadtbezirk": "Ehrenfeld"} for i in range(1, 5)]   # erfundene Meldungen
    anliegen.write_state(archiv / "meldungen.tsv", {z["nummer"]: z for z in zeilen})
    (archiv / "STAND.json").write_text(json.dumps({"abruf": "2026-10-02T06:00:00+00:00"}))
    out = tmp_path / "export" / "anliegen.json"
    doc = anliegen.seite(base=tmp_path / "archiv", out=out)
    assert "stadt" in doc and "bonn" not in doc
    assert doc["stadt"]["Abfall"] == 4 and doc["stadt"]["Stadtbild und Grün"] == "unter 3"
    assert json.loads(out.read_text())["stadt"]["gesamt"] == 4
    assert anliegen.pruefen(out) == []
