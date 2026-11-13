"""Lückenlose Abdeckung der Stadtteile und Stadtbezirke (Entscheidung 13.11.2026, pipeline/geodaten.abdeckung).

Erfundene Flächen in der Nähe Kölns, Koordinaten in Millionstel Grad (auf dem Gitter von data/geo; 1e-6 Grad sind in
Köln rund 7 cm in Ost-West- und 11 cm in Nord-Süd-Richtung). Die Erwartungen stehen als Flächen im Test (eigenes
Orakel), nicht als Ergebnis der Funktion. Dazu Prüfungen an den ausgelieferten Dateien in data/geo.
"""
import json

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box, shape

from pipeline import config, flaechen, geodaten, strukturdaten_raum

X0, Y0 = 6_950_000, 50_940_000   # Ursprung der erfundenen Flächen (Millionstel Grad)


def rechteck(x1, y1, x2, y2):
    return box((X0 + x1) / 1e6, (Y0 + y1) / 1e6, (X0 + x2) / 1e6, (Y0 + y2) / 1e6)


def vieleck(*punkte):
    return Polygon([((X0 + x) / 1e6, (Y0 + y) / 1e6) for x, y in punkte])


def teile_und_bezirke(flaechen_je_nummer, bezirk_von=lambda n: n // 100):
    """GeoJSON-Features im Format von data/geo: Stadtteile mit Nummer, Name und Stadtbezirk, dazu die Stadtbezirke
    (Geometrie der Stadtbezirke: Vereinigung der Eingaben, nur zum Vergleich)."""
    teile = [{"type": "Feature", "properties": {"ortsteil": n, "ortsteil_bez": f"Teil {n}", "bezirk": bezirk_von(n),
                                                "bezirk_bez": f"Bezirk {bezirk_von(n)}"},
              "geometry": shapely.geometry.mapping(g)} for n, g in flaechen_je_nummer.items()]
    nummern = sorted({bezirk_von(n) for n in flaechen_je_nummer})
    bezirke = [{"type": "Feature", "properties": {"bezirk": b, "bezirk_bez": f"Bezirk {b}"},
                "geometry": shapely.geometry.mapping(shapely.union_all(
                    [g for n, g in flaechen_je_nummer.items() if bezirk_von(n) == b]))} for b in nummern]
    return teile, bezirke


def ergebnis(teile):
    return {f["properties"]["ortsteil"]: shape(f["geometry"]) for f in teile}


def flaeche_m2(g):
    return geodaten._umrechnen(g, geodaten.NACH_UTM).area


def gleich(a, b, m2=1e-4):
    """Gleiche Fläche bis auf m2 Quadratmeter (Rundung der Schnittpunkte auf das Gitter)."""
    return flaeche_m2(shapely.symmetric_difference(a, b)) <= m2


def test_ueberlappung_geht_an_die_kleinere_nummer():
    # 101 und 102 überlappen sich in einem 10 Millionstel Grad (rund 0,7 m) breiten Streifen
    teile, bezirke = teile_und_bezirke({101: rechteck(0, 0, 1000, 1000), 102: rechteck(990, 0, 2000, 1000)})
    aus, _, pruefung = geodaten.abdeckung(teile, bezirke)
    g = ergebnis(aus)
    assert g[101].equals(rechteck(0, 0, 1000, 1000))
    assert g[102].equals(rechteck(1000, 0, 2000, 1000))
    assert pruefung["stadtteile"]["eingabe"]["ueberlappung_paare"] == 1
    assert pruefung["stadtteile"]["ausgabe"] == {"luecken_teile": 0, "luecken_m2": 0, "groesste_luecke_m2": 0.0,
                                                 "ueberlappung_paare": 0, "ueberlappung_m2": 0}


# Lücke 10 Millionstel Grad (0,7 m) breit zwischen 101 und 102, oben und unten von 103 und 104 geschlossen (mit
# Stützpunkten an den Ecken der Lücke, damit sie auch nach der Umrechnung in EPSG 25832 ein Loch ist)
VIER_MIT_LUECKE = {101: rechteck(0, 0, 1000, 1000), 102: rechteck(1010, 0, 2000, 1000),
                   103: vieleck((0, 1000), (1000, 1000), (1010, 1000), (2000, 1000), (2000, 1500), (0, 1500)),
                   104: vieleck((0, -500), (2000, -500), (2000, 0), (1010, 0), (1000, 0), (0, 0))}


def test_schmale_luecke_ganz_an_den_nachbarn_mit_der_laengsten_grenze():
    # 101 und 102 grenzen gleich lang an die Lücke (je 111 m): die kleinere Nummer bekommt sie ganz
    teile, bezirke = teile_und_bezirke(VIER_MIT_LUECKE)
    aus, _, pruefung = geodaten.abdeckung(teile, bezirke)
    g = ergebnis(aus)
    assert g[101].equals(rechteck(0, 0, 1010, 1000))
    assert g[102].equals(rechteck(1010, 0, 2000, 1000))
    assert g[103].equals(VIER_MIT_LUECKE[103]) and g[104].equals(VIER_MIT_LUECKE[104])
    assert pruefung["stadtteile"]["netzflaechen"]["luecke_ganz"] == 1
    assert pruefung["stadtteile"]["eingabe"]["luecken_teile"] == 1


def test_lange_luecke_wird_nach_dem_abstand_geteilt():
    # T-förmige Lücke: waagerecht 10 Millionstel Grad (1,1 m) unter 201 über die ganze Breite, senkrecht 20 Millionstel
    # Grad (1,4 m) zwischen 202 und 203 bis zum Rand von 204. Kein Nachbar ist allen Punkten näher als 2 m: 201 erhält
    # den waagerechten Teil, die Spitze der senkrechten bis 2 m, 202 den Rest; kein Stadtteil verschiebt sich weiter
    # als 2 m (wie die Vereinfachung je Fläche) und keine Fläche wächst in eine fremde Grenze hinein.
    eingabe = {201: rechteck(0, 1010, 4000, 2000), 202: rechteck(0, 0, 1990, 1000), 203: rechteck(2010, 0, 4000, 1000),
               204: rechteck(-1000, -1000, 5000, 0), 205: rechteck(-1000, 0, 0, 2000), 206: rechteck(4000, 0, 5000, 2000)}
    teile, bezirke = teile_und_bezirke(eingabe)
    aus, _, pruefung = geodaten.abdeckung(teile, bezirke)
    g = ergebnis(aus)
    assert pruefung["stadtteile"]["netzflaechen"]["luecke_geteilt"] == 1
    waagerecht, senkrecht = rechteck(0, 1000, 4000, 1010), rechteck(1990, 0, 2010, 1000)
    assert gleich(shapely.intersection(g[201], waagerecht), waagerecht)   # ganz bei 201
    assert flaeche_m2(shapely.intersection(g[203], senkrecht)) < 1e-4      # nichts davon bei 203
    unten = rechteck(1990, 0, 2010, 980)                                    # mehr als 2 m unter 201
    assert gleich(shapely.intersection(g[202], unten), unten)
    for n, q in eingabe.items():
        a, b = geodaten._umrechnen(q, geodaten.NACH_UTM), geodaten._umrechnen(g[n], geodaten.NACH_UTM)
        assert shapely.hausdorff_distance(a, b, densify=0.25) <= geodaten.LUECKE_M + 0.15, n
    assert gleich(shapely.union_all(list(g.values())), rechteck(-1000, -1000, 5000, 2000))


def test_kanal_zum_aussenrand_wird_geschlossen_der_aussenrand_bleibt():
    # Zwischen 301 und 302 läuft ein Kanal 111 m lang vom Außenrand nach innen, an der Mündung 5 Millionstel Grad
    # (0,35 m) breit, an der Spitze 0: Er zählt nicht als Loch, ist aber eine Lücke zwischen Nachbarn. Einbuchtungen
    # einer einzigen Fläche (Kerbe in 303) bleiben.
    kerbe = vieleck((2000, -500), (2000, -100), (1990, -300), (1980, -100), (1980, -500))
    eingabe = {301: rechteck(0, 0, 1000, 1000), 302: vieleck((1000, 0), (2000, 0), (2000, 1000), (1005, 1000)),
               303: shapely.difference(rechteck(0, -500, 2000, 0), kerbe)}
    teile, bezirke = teile_und_bezirke(eingabe)
    aus, _, pruefung = geodaten.abdeckung(teile, bezirke)
    g = ergebnis(aus)
    kanal = vieleck((1000, 0), (1005, 1000), (1000, 1000))
    assert gleich(shapely.union_all(list(g.values())), shapely.difference(rechteck(0, -500, 2000, 1000), kerbe))
    assert gleich(shapely.intersection(g[302], kanal), kanal)   # längere Grenze (schräge Seite)
    assert [k["stadtteile"] for k in pruefung["stadtteile"]["kanaele"]["je_kanal"]] == ["301/302"]
    assert pruefung["stadtteile"]["aussenrand"]["groesste_breite_m"] <= geodaten.AUSSENRAND_BREITE_M


def test_breite_luecke_bricht_ab():
    # ein Loch von 100 × 100 Millionstel Grad (7 × 11 m) in 401: seine Mitte liegt weiter als 2 m vom Rand
    loch = rechteck(450, 450, 550, 550)
    teile, bezirke = teile_und_bezirke({401: shapely.difference(rechteck(0, 0, 1000, 1000), loch),
                                        402: rechteck(1000, 0, 2000, 1000)})
    with pytest.raises(ValueError, match="weiter als 2 m"):
        geodaten.abdeckung(teile, bezirke)


def test_stadtbezirke_sind_die_vereinigung_ihrer_stadtteile():
    eingabe = {101: rechteck(0, 0, 1000, 1000), 102: rechteck(990, 0, 2000, 1000), 201: rechteck(0, 1005, 2000, 2000)}
    teile, bezirke = teile_und_bezirke(eingabe)
    aus_t, aus_b, pruefung = geodaten.abdeckung(teile, bezirke)
    t, b = ergebnis(aus_t), {f["properties"]["bezirk"]: shape(f["geometry"]) for f in aus_b}
    assert [f["properties"] for f in aus_b] == [f["properties"] for f in bezirke]
    assert b[1].equals(shapely.union_all([t[101], t[102]])) and b[2].equals(t[201])
    # dieselben Stützpunkte an der Grenze der Stadtbezirke wie an der der Stadtteile
    assert {tuple(c) for c in shapely.get_coordinates(b[1])} <= {tuple(c) for n in (101, 102)
                                                                for c in shapely.get_coordinates(t[n])}
    assert pruefung["stadtbezirke"]["ausgabe"]["luecken_teile"] == 0


def test_name_des_stadtbezirks_muss_passen():
    teile, bezirke = teile_und_bezirke({101: rechteck(0, 0, 1000, 1000), 201: rechteck(1000, 0, 2000, 1000)})
    bezirke[1]["properties"]["bezirk_bez"] = "anders"
    with pytest.raises(ValueError, match="Stadtbezirk „Bezirk 2“"):
        geodaten.abdeckung(teile, bezirke)


def test_schritt_aendert_bereinigte_dateien_nicht(tmp_path, monkeypatch):
    """`geo-abdeckung` schreibt die Dateien einmal; ein zweiter Lauf lässt sie byte-gleich (die Messung der ersten
    Bereinigung bleibt in meta.abdeckung)."""
    teile, bezirke = teile_und_bezirke(VIER_MIT_LUECKE)
    for name, feats in (("teile.geojson", teile), ("bezirke.geojson", bezirke)):
        (tmp_path / name).write_text(json.dumps({"type": "FeatureCollection", "meta": {"source": "erfunden"},
                                                 "features": feats}), encoding="utf-8")
    monkeypatch.setattr(config, "ORTSTEILE", tmp_path / "teile.geojson")
    monkeypatch.setattr(config, "STADTBEZIRKE", tmp_path / "bezirke.geojson")
    assert geodaten.abdeckung_schreiben() is not None
    vorher = [(tmp_path / n).read_bytes() for n in ("teile.geojson", "bezirke.geojson")]
    meta = json.loads(vorher[0])["meta"]
    assert meta["source"] == "erfunden" and meta["abdeckung"]["eingabe"]["luecken_teile"] == 1
    assert geodaten.abdeckung_schreiben() is None
    assert [(tmp_path / n).read_bytes() for n in ("teile.geojson", "bezirke.geojson")] == vorher


# --- ausgelieferte Dateien ---------------------------------------------------------------------------------------------

def _data_geo():
    teile = json.loads(config.ORTSTEILE.read_text(encoding="utf-8"))
    bezirke = json.loads(config.STADTBEZIRKE.read_text(encoding="utf-8"))
    return teile, bezirke


def test_data_geo_ohne_luecken_und_ueberlappungen():
    """Gemessen wie am 10.11.2026 (EPSG 25832, Lücke = Loch in der Vereinigung, Überlappung = Paar mit gemeinsamer
    Fläche über 0 m²), unabhängig von meta.abdeckung; dazu gültige Abdeckung, alle Koordinaten auf dem Gitter."""
    teile, bezirke = _data_geo()
    for gj, anzahl in ((teile, 86), (bezirke, 9)):
        geoms = [shape(f["geometry"]) for f in gj["features"]]
        assert len(geoms) == anzahl and all(g.is_valid and g.geom_type == "Polygon" for g in geoms)
        utm = [geodaten._umrechnen(g, geodaten.NACH_UTM) for g in geoms]
        vereinigung = shapely.union_all(utm)
        assert vereinigung.geom_type == "Polygon" and len(vereinigung.interiors) == 0
        assert all(shapely.intersection(a, b).area == 0 for i, a in enumerate(utm) for b in utm[i + 1:])
        assert shapely.coverage_is_valid(np.array(geoms, dtype=object))
        koordinaten = np.concatenate([shapely.get_coordinates(g) for g in geoms])
        assert np.abs(koordinaten * 1e6 - np.round(koordinaten * 1e6)).max() < 1e-6


def test_data_geo_stadtbezirke_aus_stadtteilen():
    teile, bezirke = _data_geo()
    for b in bezirke["features"]:
        nr = b["properties"]["bezirk"]
        stadtteile = [shape(f["geometry"]) for f in teile["features"] if f["properties"]["bezirk"] == nr]
        assert {f["properties"]["bezirk_bez"] for f in teile["features"] if f["properties"]["bezirk"] == nr} == {
            b["properties"]["bezirk_bez"]}
        assert shapely.symmetric_difference(shape(b["geometry"]), shapely.union_all(stadtteile)).area == 0


def test_data_geo_messung_in_meta():
    """meta.abdeckung nennt die Messung der Bereinigung vom 13.11.2026 (TECHNIK.md); die Zahlen der Eingabe sind die
    am 10.11.2026 gemessenen Lücken und Überlappungen."""
    teile, bezirke = _data_geo()
    t, b = teile["meta"]["abdeckung"], bezirke["meta"]["abdeckung"]
    assert (t["eingabe"]["luecken_teile"], t["eingabe"]["ueberlappung_paare"]) == (415, 169)
    assert (b["eingabe"]["luecken_teile"], b["eingabe"]["ueberlappung_paare"]) == (161, 14)
    assert t["ausgabe"]["luecken_teile"] == t["ausgabe"]["ueberlappung_paare"] == 0
    assert t["aussenrand"]["groesste_breite_m"] <= geodaten.AUSSENRAND_BREITE_M
    assert set(t["abweichung_von_der_eingabe"]["je_flaeche"]) == {str(f["properties"]["ortsteil"])
                                                                  for f in teile["features"]}
    assert t["abweichung_von_der_eingabe"]["abstand_max_m"] < 2.5
    assert teile["meta"]["vereinfacht_m"] == bezirke["meta"]["vereinfacht_m"] == geodaten.TOLERANZ_M


def test_herkunft_der_bereinigten_fassung():
    """Die Prüfsummen der bereinigten Dateien stehen in strukturdaten_raum.GEO_ABGELEITET (Abrufdatum der Quelle
    bleibt der 04.11.2026); ändert sich data/geo, muss die Herkunft neu belegt werden."""
    erwartet = {strukturdaten_raum.pruefsumme(p): p.name for p in (config.ORTSTEILE, config.STADTBEZIRKE)}
    assert strukturdaten_raum.GEO_ABGELEITET == erwartet
    assert not set(strukturdaten_raum.GEO_ABGELEITET) & set(strukturdaten_raum.GEO_HERKUNFT)


def test_flaechen_fuer_die_karte_ohne_luecken():
    """Die vereinfachten Kopien für die Karte (export/koeln/flaechen) bleiben eine Abdeckung; je Fläche vereinfacht
    entstünden wieder Lücken und Überlappungen."""
    teile, bezirke = _data_geo()
    leicht_t, leicht_b = flaechen.gebiete_fuer_karte(teile, bezirke)
    for fc, quelle in ((leicht_t, teile), (leicht_b, bezirke)):
        assert [f["properties"] for f in fc["features"]] == [f["properties"] for f in quelle["features"]]
        geoms = [shape(f["geometry"]) for f in fc["features"]]
        assert all(g.is_valid for g in geoms) and shapely.coverage_is_valid(np.array(geoms, dtype=object))
        gemessen = geodaten.luecken_ueberlappungen(geoms)
        assert gemessen["luecken_teile"] == gemessen["ueberlappung_paare"] == 0
        koordinaten = np.concatenate([shapely.get_coordinates(g) for g in geoms])
        assert np.abs(koordinaten * 1e5 - np.round(koordinaten * 1e5)).max() < 1e-6
    je_flaeche = [shape(f["geometry"]) for f in flaechen.simplify(teile)["features"]]
    assert geodaten.luecken_ueberlappungen(je_flaeche)["ueberlappung_paare"] > 0   # Gegenprobe
