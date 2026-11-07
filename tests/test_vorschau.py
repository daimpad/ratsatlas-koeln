"""Kartenvorschau ohne Ratsvorlagen (tools/vorschau.py): Aufbau und Export laufen mit leeren Rohdaten."""
import importlib.util
import json
from pathlib import Path

from pipeline import build, config, ebenen, export

ROOT = Path(__file__).resolve().parents[1]


def _vorschau():
    spec = importlib.util.spec_from_file_location("vorschau", ROOT / "tools" / "vorschau.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vorschau_ohne_vorlagen(oparl):
    _vorschau().main()
    build.build()
    export.export()
    out = config.EXPORT / config.STADT
    index = json.loads((out / "index.json").read_text())
    assert index["meta"]["vorschau"] is True and not index["meta"]["testdaten"]
    assert len(index["ortsteile"]) == 86 and not (out / "zeit.json").exists()
    assert "temporal" not in (out / "dcat.jsonld").read_text()


def test_vorschau_ueberschreibt_keine_daten_der_stadt(oparl):
    from pipeline import sessionnet
    sessionnet.fetch_all()   # Testserver: „Daten der Stadt“
    try:
        _vorschau().main()
    except SystemExit as e:
        assert "Daten der Stadt" in str(e)
    else:
        raise AssertionError("Vorschau hätte abbrechen müssen")


def test_ebenen_verzeichnis(oparl):
    ebenen.write()
    d = json.loads((config.EXPORT / config.STADT / "ebenen.json").read_text())
    keys = {e["key"] for e in d["ebenen"]}
    assert {"lebenswerte_veedel", "naturschutz", "denkmaeler"} <= keys
    for e in d["ebenen"]:
        assert e["quelle"] and e["lizenz"] and e["stand"] and (config.EXPORT / config.STADT / e["datei"]).exists()
        props = json.dumps(json.loads((config.EXPORT / config.STADT / e["datei"]).read_text()))
        assert "Flurstück" not in props and "Eigentum" not in props   # keine Flurstücke und Eigentumsangaben
        # Mindestzoom je Quelle (pipeline/ebenen.py) steht in ebenen.json; die Karte liest ihn von dort
        assert e.get("mindestzoom") == ebenen.QUELLEN[e["key"]].get("mindestzoom"), e["key"]
    zoom = {e["key"]: e["mindestzoom"] for e in d["ebenen"] if "mindestzoom" in e}
    assert zoom.get("denkmaeler") == 14 and zoom.get("baupotenziale") == 13 and zoom.get("stimmbezirke") == 12
    assert "EX[k].mindestzoom ||" in (ROOT / "site" / "app.js").read_text()
