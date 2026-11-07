"""Gebietsseiten (pipeline/gebietsseiten.py): je Stadtteil und Stadtbezirk eine statische Seite, auch ohne Vorlagen
(Kartenvorschau), mit Kennzahlen aus kontext.json, Quellen und Lizenzen und Links auf die Kartenebenen (ebenen.json).
Alles mit dem lokalen Testserver bzw. leeren Rohdaten (conftest.py), keine Anfragen an die Stadt."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from pipeline import build, config, ebenen, export, gebietsseiten, kontext, sessionnet, topics

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


class Sichtbar(HTMLParser):
    """Was Leser:innen sehen: Text im Dokument (mit <title>, ohne script/style) und die Beschreibung für Suchmaschinen."""

    def __init__(self, html):
        super().__init__()
        self.teile, self.aus = [], 0
        self.feed(html)
        self.text = " ".join(self.teile)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.aus += 1
        elif tag == "meta" and a.get("name") == "description":
            self.teile.append(a.get("content") or "")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.aus -= 1

    def handle_data(self, data):
        if not self.aus:
            self.teile.append(data)


def _sichtbar_pruefen(html, pfad):
    """Keine internen Feldnamen und „Stadtteil“ statt „Ortsteil“ in allem, was Leser:innen sehen."""
    text = Sichtbar(html).text
    assert "_abdeckung" not in text, pfad
    assert not re.search("ortsteil", text, re.I), (pfad, re.findall(r".{30}ortsteil.{30}", text, re.I))


def _ebene_eintrag(html, art, slug, key):
    """Listeneintrag einer Kartenebene auf der Gebietsseite."""
    m = re.search(r'<li><a href="\.\./\.\./\?gebiet=%s:%s&amp;ebenen=%s">.*?</li>' % (art, slug, key), html, re.S)
    assert m, (slug, key)
    return m.group(0)


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

    # Namen der Gebiete in index.json (Geodaten) und kontext.json stimmen überein, auch der Stadtbezirk je Stadtteil;
    # sonst kündigte eine Seite Kennzahlen an, die sie nicht zeigt
    assert set(kx["ortsteile"]) == {o["name"] for o in index["ortsteile"]}
    assert set(kx["bezirke"]) == {b["name"] for b in index["bezirke"]}
    assert all(kx["stadtbezirk_je_ortsteil"][o["name"]] == o["stadtbezirk"] for o in index["ortsteile"])
    assert "je mit Kennzahlen und Kartenebenen" in hub
    assert not re.search("ortsteil", kx["meta"]["hinweis"], re.I)   # auch in der Karte und im Assistenten sichtbar
    _sichtbar_pruefen(hub, "gebiete/")

    meta = kx["meta"]
    keys = meta["reihenfolge"]
    for pfad, (art, g) in seiten.items():
        html = (site / pfad / "index.html").read_text()
        assert "Ratsvorlagen der Stadt Köln folgen" in html                          # Vorschau
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", html)                    # keine Erzeugungszeitpunkte
        assert "Bonn" not in html and "Ortsteil" not in html
        _sichtbar_pruefen(html, pfad)
        assert "Kennzahlen und Kartenebenen" in re.search(r"<title>(.*?)</title>", html).group(1)
        # Kennzahlentabelle: Kopf mit scope="col", je Kennzahl eine Zeile mit scope="row"
        assert html.count('<th scope="row">') == len(keys) and '<th scope="col">Kennzahl</th>' in html
        assert "Einordnung, kein Urteil" in html and "abgeleitet" in html
        # Hinweis auf die Mindestgröße im Absatz nur bei kleinen Gebieten (hier keines; unten mit gesenkter Zahl)
        assert "Für Gebiete unter" not in re.search(r"<p>Einordnung, kein Urteil.*?</p>", html, re.S).group(0)
        # Überschriften der Gebietsseiten mit eigener Klasse (site/page.css gilt nur für sie)
        assert '<h3 class="gebiet-h3">Quellen und Lizenzen</h3>' in html and "<h3>" not in html
        zeilen = Tabelle(html).zeilen
        werte = kx["ortsteile" if art == "ortsteil" else "bezirke"][g["name"]]
        assert len(zeilen[0]) == (4 if art == "ortsteil" else 3) and zeilen[0][-1] == f"ganz {config.STADT_NAME}"
        assert [z[0] for z in zeilen[1:]] == [meta["kennzahlen"][k]["titel"] for k in keys]
        assert zeilen[1 + keys.index("einwohner")][1] == gebietsseiten._de(werte["einwohner"])
        # Quellen mit Lizenz und Stand
        for q in {meta["kennzahlen"][k]["quelle"] for k in keys}:
            assert escape(meta["quellen"][q]["titel"]) in html and f"Lizenz: {escape(meta['quellen'][q]['lizenz'])}" in html
        # Ebenen: Links in die Karte für dieses Gebiet, mit Quelle und Lizenz; Ebenen mit Mindestzoom mit dem Hinweis,
        # dass sie erst bei näherer Ansicht erscheinen (ob Hineinzoomen nötig ist, hängt von Gebiet, Ebene und Bildschirm ab)
        assert "Ebenen mit vielen Objekten erscheinen erst bei näherer Ansicht" in html
        for e in eb:
            eintrag = _ebene_eintrag(html, art, g["slug"], e["key"])
            assert escape(e["lizenz"]) in eintrag
            assert (gebietsseiten.ZOOM_HINWEIS in eintrag) == bool(e.get("mindestzoom")), (pfad, e["key"])
    _links_pruefen(site, ["gebiete/", *seiten])

    # Mindestgröße: unter meta.mindest_einwohner keine Anteile und Mittelwerte, mit Grund (Werte bleiben in der Datei);
    # ein Stadtteil ohne Eintrag in kontext.json (etwa nach einer Namensänderung): keine Tabelle und keine Ankündigung
    klein, fehlt = index["ortsteile"][0], index["ortsteile"][1]
    kx["ortsteile"][klein["name"]]["einwohner"] = meta["mindest_einwohner"] - 1
    del kx["ortsteile"][fehlt["name"]]
    (base / "kontext.json").write_text(json.dumps(kx, ensure_ascii=False))
    gebietsseiten.write(site, config.SITE_URL)
    html = (site / "ortsteil" / fehlt["slug"] / "index.html").read_text()
    assert '<table class="kennzahlen">' not in html and "Kartenebenen" in html
    sichtbar = Sichtbar(html).text
    assert "Kennzahlen" not in sichtbar, re.findall(r".{40}Kennzahlen.{40}", sichtbar)
    hub = (site / "gebiete" / "index.html").read_text()
    assert "je mit Kartenebenen zur Einordnung" in hub and "Kennzahlen" not in Sichtbar(hub).text
    bezirk = next(b for b in index["bezirke"] if b["name"] == klein["stadtbezirk"])
    html = (site / "stadtbezirk" / bezirk["slug"] / "index.html").read_text()
    assert "Für Gebiete unter" not in re.search(r"<p>Einordnung, kein Urteil.*?</p>", html, re.S).group(0)
    html = (site / "ortsteil" / klein["slug"] / "index.html").read_text()
    absatz = re.search(r"<p>Einordnung, kein Urteil.*?</p>", html, re.S).group(0)
    assert f"Für Gebiete unter {meta['mindest_einwohner']} Einwohnern stehen keine Anteile und Mittelwerte." in absatz
    zeilen = {z[0]: z[1:] for z in Tabelle(html).zeilen[1:]}
    grund = f"keine Angabe (unter {meta['mindest_einwohner']} Einwohnern)"
    for k in keys:
        eigen, *vergleich = zeilen[meta["kennzahlen"][k]["titel"]]
        if k in kontext.ANTEILE:
            assert eigen == grund, k
            assert grund not in vergleich, k                  # Stadtbezirk und ganz Köln sind groß genug
        else:
            assert "keine Angabe" not in eigen, k              # Anzahlen bleiben


def test_gebietsseiten_mit_vorlagen(oparl, tmp_path):
    sessionnet.fetch_all()   # synthetische Vorlagen vom lokalen Testserver
    site = _seite(tmp_path)
    base = site / "data" / "export" / config.STADT
    index = json.loads((base / "index.json").read_text())
    assert not index["meta"]["vorschau"]
    seiten = _seiten(index)
    mit = [p for p, (_, g) in seiten.items() if g["count"]]
    assert mit and len(seiten) == 86 + 9
    hub = (site / "gebiete" / "index.html").read_text()
    assert "Ratsvorlagen nach Gebiet" in hub and re.search(r"\(\d+ Vorlagen?\)", hub)
    _sichtbar_pruefen(hub, "gebiete/")
    for pfad, (art, g) in seiten.items():
        html = (site / pfad / "index.html").read_text()
        assert "Ratsvorlagen der Stadt Köln folgen" not in html
        assert '<table class="kennzahlen">' in html and "Kartenebenen" in html
        _sichtbar_pruefen(html, pfad)
        # Übersicht und Seite nennen dieselbe Zahl
        zahl = gebietsseiten._vorlagen_zahl(g["count"])
        assert (f'{escape(g["name"])}</a> ({zahl})' if art == "ortsteil" else f"({zahl} zum ganzen Stadtbezirk") in hub
        if g["count"]:   # bisheriges Verhalten: jüngste Vorlagen mit Link in die Karte
            if art == "ortsteil":
                assert f"<h1>Ratsvorlagen in {escape(g['name'])}</h1>" in html
            else:   # Stadtbezirk: Vorlagen zum ganzen Stadtbezirk, nicht dieselbe Überschrift wie der gleichnamige Stadtteil
                assert f"<h1>Ratsvorlagen im Stadtbezirk {escape(g['name'])}</h1>" in html
                assert "zum ganzen Stadtbezirk, ohne genaueren Ort" in html
            assert "jüngste" in html and zahl in html
            assert f'href="../../?gebiet={art}:{g["slug"]}#' in html
        else:
            assert "keine Vorlage" in html
    _links_pruefen(site, ["gebiete/", *seiten])


def test_gebietsseiten_byte_gleich(oparl, tmp_path):
    """Gleicher Inhalt → gleiche Bytes, auch mit anderem Hash-Seed (Mengen und Wörterbücher ohne feste Reihenfolge):
    der Branch deploy ändert sich nur bei Inhaltsänderungen. Eine Vorlage mit sechs gleich häufigen Themen in
    Ehrenfeld (Stichworte im Titel); vor der Korrektur wechselte deren Reihenfolge je nach PYTHONHASHSEED."""
    oparl.papers[1] = oparl.paper(2, name="Radweg, Spielplatz, Baumpflanzung, Neubau, Schulhof und Sporthalle in Ehrenfeld")
    sessionnet.fetch_all()
    build.build()
    export.export()
    kontext.write()
    ebenen.write()
    code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + '/tools'); "
            "from pipeline import config; config.EXPORT = Path(sys.argv[2]); import seite_bauen; seite_bauen.main(sys.argv[3])")
    seiten = []
    for seed in ("1", "2", "3"):
        ziel = tmp_path / f"site_{seed}"
        subprocess.run([sys.executable, "-c", code, str(ROOT), str(config.EXPORT), str(ziel)], check=True, cwd=tmp_path,
                       capture_output=True, env={**os.environ, "PYTHONHASHSEED": seed})
        seiten.append({str(p.relative_to(ziel)): p.read_bytes()
                       for d in ("ortsteil", "stadtbezirk", "gebiete") for p in sorted((ziel / d).rglob("index.html"))})
    assert len(seiten[0]) == 86 + 9 + 1
    ehrenfeld = seiten[0]["ortsteil/ehrenfeld/index.html"].decode()
    # sechs Themen je einmal: die ersten fünf nach Schlüssel (ohne „verkehr“), unabhängig vom Hash-Seed
    titel = dict(topics.THEMES)
    assert ", ".join(f"{titel[k]} (1)" for k in ("bauen", "bildung", "kinder", "kultur", "umwelt")) in ehrenfeld
    for andere in seiten[1:]:
        assert sorted(andere) == sorted(seiten[0])
        assert [p for p in seiten[0] if andere[p] != seiten[0][p]] == []


def test_methodentexte_fuer_leser():
    """Titel und Methoden der Kennzahlen erscheinen in Karte und Gebietsseiten: keine internen Feldnamen und „Stadtteile“
    statt „Ortsteile“, auch bei Kennzahlen, die für Köln noch fehlen (Wahlbeteiligung)."""
    for k, (titel, _, _, methode) in kontext.KENNZAHLEN.items():
        for text in (titel, methode):
            assert not re.search(r"[a-z]_[a-z]", text) and not re.search("ortsteil", text, re.I), (k, text)
    assert f"mindestens {kontext.BRW_HINWEIS_OHNE_ZONE} % der Einwohner" in kontext.KENNZAHLEN["bodenrichtwert"][3]


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
