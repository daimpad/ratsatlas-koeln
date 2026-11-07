"""Gebietsseiten (pipeline/gebietsseiten.py): je Stadtteil und Stadtbezirk eine statische Seite, auch ohne Vorlagen
(Kartenvorschau), mit Kennzahlen aus kontext.json, Quellen und Lizenzen und Links auf die Kartenebenen (ebenen.json).
Alles mit dem lokalen Testserver bzw. leeren Rohdaten (conftest.py), keine Anfragen an die Stadt."""
import importlib.util
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from pipeline import build, config, ebenen, export, gebietsseiten, kontext, sessionnet

ROOT = Path(__file__).resolve().parents[1]


def _modul(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seite(tmp_path):
    """Aufbau, Export, Kennzahlen und Ebenen in die umgelenkten Pfade, dann die Seite wie tools/seite_bauen.py."""
    build.build()
    export.export()
    kontext.write()     # schreibt nach config.EXPORT (in der Fixture umgelenkt)
    ebenen.write()
    site = tmp_path / "_site"
    _modul("seite_bauen").main(site)
    return site


class Tabelle(HTMLParser):
    """Zellen der Tabelle class="kennzahlen" als Text: [[Zelle, …] je Zeile], die erste Zeile ist der Kopf."""

    def __init__(self, html):
        super().__init__()
        self.zeilen, self.an, self.zelle = [], False, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "table" and ("class", "kennzahlen") in attrs:
            self.an = True
        elif self.an and tag == "tr":
            self.zeilen.append([])
        elif self.an and tag in ("th", "td"):
            self.zelle = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self.an = False
        elif self.an and tag in ("th", "td"):
            self.zeilen[-1].append(self.zelle.strip())
            self.zelle = None

    def handle_data(self, data):
        if self.zelle is not None:
            self.zelle += data


def _seiten(index):
    return {**{f"ortsteil/{o['slug']}/": ("ortsteil", o) for o in index["ortsteile"]},
            **{f"stadtbezirk/{b['slug']}/": ("bezirk", b) for b in index["bezirke"]}}


def _links_pruefen(site, pfade):
    """Innere Links der Gebietsseiten wie tools/linkpruefung.py: jedes Ziel existiert als Datei oder Verzeichnis."""
    lp = _modul("linkpruefung")
    for pfad in pfade:
        seite = site / pfad / "index.html"
        for _, _, url in lp.lesen(seite).links:
            if re.match(r"^(https?:|mailto:)", url):
                continue
            ziel, _ = lp.ziel_datei(site, seite, url)
            assert ziel.exists(), (pfad, url)


def test_gebietsseiten_vorschau(oparl, tmp_path):
    _modul("vorschau").main()
    site = _seite(tmp_path)
    base = site / "data" / "export" / config.STADT
    index = json.loads((base / "index.json").read_text())
    kx = json.loads((base / "kontext.json").read_text())
    eb = json.loads((base / "ebenen.json").read_text())["ebenen"]
    assert index["meta"]["vorschau"] and eb and not any(o["count"] for o in index["ortsteile"])
    seiten = _seiten(index)
    assert len(seiten) == 86 + 9

    # alle Seiten und die Übersicht in der Sitemap
    sitemap = (site / "sitemap.xml").read_text()
    for pfad in ["gebiete/", *seiten]:
        assert (site / pfad / "index.html").exists(), pfad
        assert f"<loc>{config.SITE_URL}{pfad}</loc>" in sitemap, pfad
    hub = (site / "gebiete" / "index.html").read_text()
    assert all(f'href="../{p}"' in hub for p in seiten)
    assert "Ratsvorlagen der Stadt Köln folgen" in hub

    meta = kx["meta"]
    keys = meta["reihenfolge"]
    for pfad, (art, g) in seiten.items():
        html = (site / pfad / "index.html").read_text()
        assert "Ratsvorlagen der Stadt Köln folgen" in html                          # Vorschau
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", html)                    # keine Erzeugungszeitpunkte
        assert "Bonn" not in html and "Ortsteil" not in html
        # Kennzahlentabelle: Kopf mit scope="col", je Kennzahl eine Zeile mit scope="row"
        assert html.count('<th scope="row">') == len(keys) and '<th scope="col">Kennzahl</th>' in html
        assert "Einordnung, kein Urteil" in html and "abgeleitet" in html
        zeilen = Tabelle(html).zeilen
        werte = kx["ortsteile" if art == "ortsteil" else "bezirke"][g["name"]]
        assert len(zeilen[0]) == (4 if art == "ortsteil" else 3) and zeilen[0][-1] == f"ganz {config.STADT_NAME}"
        assert [z[0] for z in zeilen[1:]] == [meta["kennzahlen"][k]["titel"] for k in keys]
        assert zeilen[1 + keys.index("einwohner")][1] == gebietsseiten._de(werte["einwohner"])
        # Quellen mit Lizenz und Stand
        for q in {meta["kennzahlen"][k]["quelle"] for k in keys}:
            assert escape(meta["quellen"][q]["titel"]) in html and f"Lizenz: {escape(meta['quellen'][q]['lizenz'])}" in html
        # Ebenen: Links in die Karte für dieses Gebiet, mit Quelle und Lizenz
        for e in eb:
            assert f'href="../../?gebiet={art}:{g["slug"]}&amp;ebenen={e["key"]}"' in html
            assert escape(e["lizenz"]) in html
    _links_pruefen(site, ["gebiete/", *seiten])

    # Mindestgröße: unter meta.mindest_einwohner keine Anteile und Mittelwerte, mit Grund (Werte bleiben in der Datei)
    klein = index["ortsteile"][0]
    kx["ortsteile"][klein["name"]]["einwohner"] = meta["mindest_einwohner"] - 1
    (base / "kontext.json").write_text(json.dumps(kx, ensure_ascii=False))
    gebietsseiten.write(site, config.SITE_URL)
    html = (site / "ortsteil" / klein["slug"] / "index.html").read_text()
    zeilen = {z[0]: z[1:] for z in Tabelle(html).zeilen[1:]}
    grund = f"keine Angabe (unter {meta['mindest_einwohner']} Einwohnern)"
    for k in keys:
        eigen, *vergleich = zeilen[meta["kennzahlen"][k]["titel"]]
        if k in kontext.ANTEILE:
            assert eigen == grund, k
            assert grund not in vergleich, k                  # Stadtbezirk und ganz Köln sind groß genug
        else:
            assert "keine Angabe" not in eigen, k              # Anzahlen bleiben
    assert f"Unter {meta['mindest_einwohner']} Einwohnern" in html or f"unter {meta['mindest_einwohner']} Einwohnern" in html


def test_gebietsseiten_mit_vorlagen(oparl, tmp_path):
    sessionnet.fetch_all()   # synthetische Vorlagen vom lokalen Testserver
    site = _seite(tmp_path)
    base = site / "data" / "export" / config.STADT
    index = json.loads((base / "index.json").read_text())
    assert not index["meta"]["vorschau"]
    seiten = _seiten(index)
    mit = [p for p, (_, g) in seiten.items() if g["count"]]
    assert mit and len(seiten) == 86 + 9
    for pfad, (art, g) in seiten.items():
        html = (site / pfad / "index.html").read_text()
        assert "Ratsvorlagen der Stadt Köln folgen" not in html
        assert '<table class="kennzahlen">' in html and "Kartenebenen" in html
        if g["count"]:   # bisheriges Verhalten: jüngste Vorlagen mit Link in die Karte
            assert f"Ratsvorlagen in {escape(g['name'])}" in html and "jüngsten Vorlagen" in html
            assert f'href="../../?gebiet={art}:{g["slug"]}#' in html
        else:
            assert "keine Vorlage" in html
    hub = (site / "gebiete" / "index.html").read_text()
    assert "Ratsvorlagen nach Gebiet" in hub and re.search(r"\(\d+ Vorlagen?\)", hub)
    _links_pruefen(site, ["gebiete/", *seiten])


def test_zahlen_und_zellen():
    assert gebietsseiten._de(1017271) == "1.017.271"
    assert gebietsseiten._de(16.1, 0, 1) == "16,1" and gebietsseiten._de(17.0, 0, 1) == "17"
    assert gebietsseiten._de(11.6, 2, 2) == "11,60" and gebietsseiten._de(12.5) == "13"
    meta = {"mindest_einwohner": 100, "bodenrichtwert_hinweis_ohne_zone": 33,
            "kennzahlen": {"miete": {"titel": "Miete", "einheit": "€/m²"}, "kitas": {"titel": "Kitas", "einheit": "Anzahl"},
                           "wahlbeteiligung": {"titel": "Wahl", "einheit": "%", "ohne_wert": "ohne eigenen Stimmbezirk"},
                           "bodenrichtwert": {"titel": "BRW", "einheit": "€/m²"}}}
    anteile = {"miete", "wahlbeteiligung", "bodenrichtwert"}
    klein = {"einwohner": 20, "miete": 9.5, "kitas": 2}
    assert gebietsseiten._zelle("miete", klein, meta, anteile) == "keine Angabe (unter 100 Einwohnern)"
    assert gebietsseiten._zelle("kitas", klein, meta, anteile) == "2"
    gross = {"einwohner": 5000, "miete": 9.5, "bodenrichtwert": 1850, "bodenrichtwert_abdeckung": 12.5}
    assert gebietsseiten._zelle("miete", gross, meta, anteile) == "9,50 €/m²"
    assert gebietsseiten._zelle("wahlbeteiligung", gross, meta, anteile) == "keine Angabe (ohne eigenen Stimmbezirk)"
    assert gebietsseiten._zelle("bodenrichtwert", gross, meta, anteile).startswith("1.850 €/m²<br><small>gilt für 13 %")
