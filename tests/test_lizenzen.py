"""Runde 19b, Teil L (Lizenzen und Texte): data/LICENSE-DATA.md mit einer Zeile je Art von Export und der Lizenz, die
die Datei selbst nennt; DCAT mit Lizenz und Rechtehinweis je Verteilung aus den enthaltenen Teilen; Namensnennung in
`meta` der Flächen, der Suche und der Kennzahlen; Planchronik, Kartenlegende und Quellenabsatz ohne Bonner Lizenz- und
Zeitangaben. Bau über den lokalen Testserver mit erfundenen Daten, keine Anfragen an Server der Stadt."""
import fnmatch
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from pipeline import build, config, ebenen, export, kontext, paket, publish, sessionnet

ROOT = Path(__file__).resolve().parents[1]
LIZENZDATEI = ROOT / "data" / "LICENSE-DATA.md"
BPLAN = ROOT / "data" / "geo" / "bebauungsplaene_koeln.geojson"
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
BY, ZERO = "dl-de/by 2.0", "dl-de/zero 2.0"

# Exportdatei (Pfad unter data/export/) → Zeile in LICENSE-DATA.md (erster Pfad der ersten Spalte). Eine neue Art von
# Export ohne Eintrag hier lässt den Test scheitern: dann LICENSE-DATA.md und diese Liste ergänzen.
ZEILE_JE_DATEI = (
    (r"koeln/(ortsteile|bezirke|ohne-ortsbezug|feeds)/.+", "export/koeln/"),
    (r"koeln/(index|suche|zeit|prozesse|plaene)\.json|koeln/vorlagen\.geojson|koeln/termine\.ics|koeln/dcat\.jsonld",
     "export/koeln/"),
    (r"(.+/)?audit_(?!kontext\.)[a-z_]+\.tsv|(.+/)?stichprobe_[a-z_]+\.tsv", "export/koeln/"),
    (r"koeln/kontext\.json|audit_kontext\.tsv", "export/koeln/kontext.json"),
    (r"koeln/flaechen/(bodenrichtwerte|klima|ueberschwemmung|punkte_haltestellen)\.json",
     "export/koeln/flaechen/bodenrichtwerte.json"),
    (r"koeln/flaechen/punkte_kitas\.json", "export/koeln/flaechen/punkte_kitas.json"),
    (r"koeln/flaechen/punkte_schulen\.json", "export/koeln/flaechen/punkte_schulen.json"),
    (r"koeln/ebenen\.json|koeln/flaechen/ebene_[a-z_]+\.json", "export/koeln/ebenen.json"),
    (r"koeln/flaechen/(ortsteile|bezirke)\.json", "export/koeln/flaechen/ortsteile.json"),
    (r"koeln/flaechen/bebauungsplaene\.json", "export/koeln/flaechen/bebauungsplaene.json"),
    (r"glossar\.json", "export/glossar.json"),
    (r"abrufstatistik\.tsv", "export/abrufstatistik.tsv"),
)
# Lizenz und Namensnennung je Zeile (Spalten 3 und 4)
ERWARTET = {
    "export/koeln/": ("laut Katalog dl-de/zero 2.0", (config.NAMENSNENNUNG,)),
    "export/koeln/kontext.json": (BY, ("Destatis", "Land NRW", "Ministerium für Schule und Bildung NRW")),
    "export/koeln/flaechen/bodenrichtwerte.json": (ZERO, ()),
    "export/koeln/flaechen/punkte_kitas.json": (BY, ("Land NRW",)),
    "export/koeln/flaechen/punkte_schulen.json": (BY, ("Ministerium für Schule und Bildung NRW",)),
    "export/koeln/ebenen.json": (ZERO, (config.NAMENSNENNUNG,)),
    "export/koeln/flaechen/ortsteile.json": (ZERO, (config.NAMENSNENNUNG,)),
    "export/koeln/flaechen/bebauungsplaene.json": (BY, ("IT.NRW", "Datengrundlage Stadt Köln")),
    "export/glossar.json": ("MIT", ()),
    "export/abrufstatistik.tsv": (ZERO, ()),
}


def _zeilen():
    """Zeilen der Tabelle in LICENSE-DATA.md: erster Pfad der ersten Spalte → (Pfade der ersten Spalte, Spalten)."""
    zeilen = {}
    for z in LIZENZDATEI.read_text(encoding="utf-8").splitlines():
        if not z.startswith("| `"):
            continue
        spalten = [s.strip() for s in z.strip().strip("|").split(" | ")]
        assert len(spalten) == 4, z
        pfade = re.findall(r"`([^`]+)`", spalten[0])
        assert pfade[0] not in zeilen, pfade[0]
        zeilen[pfade[0]] = (pfade, spalten)
    return zeilen


def _zeile_fuer(rel):
    treffer = [z for muster, z in ZEILE_JE_DATEI if re.fullmatch(muster, rel)]
    assert len(treffer) == 1, (rel, treffer)
    return treffer[0]


def _nennt(pfade, rel):
    """Die erste Spalte nennt die Datei: ganzer Pfad, Dateiname, Muster (audit_*.tsv) oder ihr Ordner (ortsteile/)."""
    teile = rel.split("/")
    return any(fnmatch.fnmatchcase(f"export/{rel}", p) or fnmatch.fnmatchcase(teile[-1], p)
               or (p.endswith("/") and p.rstrip("/") in teile[:-1]) for p in pfade)


def _klasse(text):
    return "by" if re.search(r"dl-de/by", text) else "zero" if re.search(r"dl-de/zero", text) else None


def _pipeline(monkeypatch):
    """Abruf vom lokalen Testserver, Aufbereitung, Export, Kennzahlen, Ebenen, Datenpaket; mit den Bebauungsplänen aus
    data/geo (der Testserver-Fixture setzt sonst eine fehlende Datei)."""
    monkeypatch.setattr(config, "BPLAN", BPLAN)
    sessionnet.fetch_all()
    build.build()
    export.export()
    kontext.write()
    ebenen.write()
    return paket.write()


# --- (1) LICENSE-DATA.md: eine Zeile je Art von Export, Lizenz wie in der Datei ------------------------------------

def test_lizenzdatei_je_exportdatei(oparl, monkeypatch):
    """Jede Datei unter data/export/ (außer dem Zip selbst) hat genau eine Zeile in LICENSE-DATA.md, die sie nennt.
    Lizenz und Namensnennung der Zeile stimmen mit ERWARTET und, wo die Datei eine Lizenz nennt (`meta`), mit dieser
    überein: Kitas, Schulen, Kennzahlen und Bebauungspläne nicht unter der Zeile des Ratsinformationssystems."""
    zip_pfad = _pipeline(monkeypatch)
    zeilen = _zeilen()
    assert set(ERWARTET) <= set(zeilen), set(ERWARTET) - set(zeilen)
    dateien = sorted(p.relative_to(config.EXPORT).as_posix() for p in config.EXPORT.rglob("*")
                     if p.is_file() and p != zip_pfad)
    assert {"koeln/kontext.json", "koeln/flaechen/punkte_kitas.json", "koeln/flaechen/punkte_schulen.json",
            "koeln/flaechen/bebauungsplaene.json", "koeln/ebenen.json", "koeln/suche.json"} <= set(dateien)
    for rel in dateien:
        schluessel = _zeile_fuer(rel)
        pfade, spalten = zeilen[schluessel]
        assert _nennt(pfade, rel), (rel, pfade)
        lizenz, namen = ERWARTET[schluessel]
        assert lizenz in spalten[2], (rel, spalten[2])
        assert all(n in spalten[3] for n in namen), (rel, spalten[3])
        if rel.endswith(".json") and "/flaechen/" in rel:
            meta = json.loads((config.EXPORT / rel).read_text(encoding="utf-8"))["meta"]
            assert _klasse(meta["lizenz"]) == _klasse(spalten[2]), (rel, meta["lizenz"], spalten[2])
    # Zeile des Ratsinformationssystems: ohne Kennzahlen und Flächen, mit den Bebauungsplänen als eigener Lizenz
    pfade, spalten = zeilen["export/koeln/"]
    assert not {"kontext.json", "flaechen/", "export/koeln/…"} & set(pfade)
    assert "`geo/bebauungsplaene_koeln.geojson`" in spalten[1] and BY in spalten[2] and "Klärung" in spalten[2]
    assert spalten[3] == config.NAMENSNENNUNG
    # Pfade auf der Seite und im Datenpaket
    text = LIZENZDATEI.read_text(encoding="utf-8")
    assert "data/export/koeln/vorlagen.geojson" in text and "ratsatlas-koeln/koeln/vorlagen.geojson" in text
    with zipfile.ZipFile(zip_pfad) as z:
        namen = set(z.namelist())
        liesmich = z.read(f"{paket.ORDNER}/LIESMICH.txt").decode("utf-8")
    assert f"{paket.ORDNER}/koeln/vorlagen.geojson" in namen and f"{paket.ORDNER}/geo/bebauungsplaene_koeln.geojson" in namen
    assert "bebauungsplaene_koeln.geojson" in liesmich and BY in liesmich and "koeln/… in diesem Paket" in liesmich

    # --- (4) Namensnennung und Lizenz in meta der Flächen, der Suche und der Kennzahlen ---
    for datei in sorted((config.EXPORT / config.STADT / "flaechen").glob("*.json")):
        d = json.loads(datei.read_text(encoding="utf-8"))
        assert d["features"] and {"quelle", "url", "lizenz"} <= set(d["meta"]), datei.name
        assert d["meta"]["lizenz"] and d["meta"]["url"].startswith("https://"), datei.name
    flaechen = config.EXPORT / config.STADT / "flaechen"
    assert config.NAMENSNENNUNG in json.loads((flaechen / "ortsteile.json").read_text())["meta"]["lizenz"]
    assert "IT.NRW" in json.loads((flaechen / "bebauungsplaene.json").read_text())["meta"]["lizenz"]
    assert "Land NRW" in json.loads((flaechen / "punkte_kitas.json").read_text())["meta"]["lizenz"]
    assert config.NAMENSNENNUNG in json.loads((flaechen / "ebene_denkmaeler.json").read_text())["meta"]["lizenz"]
    suche = json.loads((config.EXPORT / config.STADT / "suche.json").read_text(encoding="utf-8"))
    assert config.NAMENSNENNUNG in json.dumps(suche["meta"]["sources"], ensure_ascii=False) and suche["rows"]
    assert not any("retrieved_at" in s for s in suche["meta"]["sources"])   # ändert sich nur mit dem Inhalt
    kx = json.loads((config.EXPORT / config.STADT / "kontext.json").read_text(encoding="utf-8"))
    assert config.NAMENSNENNUNG in kx["meta"]["gebiete"]["lizenz"] and "gebiete" not in kx["meta"]["quellen"]

    # --- (2) DCAT: Lizenz je Verteilung nach dem Inhalt, Rechtehinweis aus den Quellen ---
    dcat = json.loads((config.EXPORT / config.STADT / "dcat.jsonld").read_text(encoding="utf-8"))
    je = {d["dct:title"]["@value"]: d for d in dcat["dcat:distribution"]}
    lizenz = {t: d["dct:license"]["@id"] for t, d in je.items()}
    recht = {t: d["dct:rights"]["rdfs:label"] for t, d in je.items()}
    assert lizenz["Datenpaket (Zip)"] == publish.LICENCE["dl-de-by"]
    assert lizenz["Planregister Bebauungspläne (JSON)"] == publish.LICENCE["dl-de-by"]
    assert lizenz["Kennzahlen je Stadtteil (JSON)"] == publish.LICENCE["dl-de-by"]
    assert lizenz["Kartenebenen (JSON)"] == publish.LICENCE["dl-de-zero"]
    for t in ("Typische Wege je Vorlagenart (JSON)", "Sitzungskalender (iCalendar)", "Zeitleiste: Monatsaggregate (JSON)"):
        assert lizenz[t] == publish.LICENCE["dl-de-zero"], t
        assert "IT.NRW" not in recht[t] and config.NAMENSNENNUNG in recht[t], t
    punkte = json.loads((config.EXPORT / config.STADT / "vorlagen.geojson").read_text(encoding="utf-8"))
    mit_bplan = any(f["properties"]["location_source"] == config.QUELLE_BPLAN for f in punkte["features"])
    assert lizenz["Verortete Vorlagen (GeoJSON)"] == publish.LICENCE["dl-de-by" if mit_bplan else "dl-de-zero"]
    assert ("IT.NRW" in recht["Verortete Vorlagen (GeoJSON)"]) == mit_bplan
    for teil in ("IT.NRW", "Destatis", "Land NRW", "Ministerium für Schule und Bildung NRW", config.NAMENSNENNUNG,
                 "LICENSE-DATA.md"):
        assert teil in recht["Datenpaket (Zip)"], teil
    assert "IT.NRW" in recht["Planregister Bebauungspläne (JSON)"] and "Destatis" in recht["Kennzahlen je Stadtteil (JSON)"]
    beschreibung = je["Planregister Bebauungspläne (JSON)"]["dct:description"]["@value"]
    assert "folgen, sobald" not in beschreibung and "Bauleitplanung in NRW" in beschreibung
    assert "des Bundes" not in je["Kartenebenen (JSON)"]["dct:description"]["@value"]
    # Notizen in vorlagen.geojson und plaene.json: Bebauungspläne mit ihrer Lizenz
    lizenz_bplan = config.SOURCES[config.QUELLE_BPLAN]["license"]
    assert "'bplan-koeln'" in punkte["meta"]["note"] and lizenz_bplan in punkte["meta"]["note"]
    plaene = json.loads((config.EXPORT / config.STADT / "plaene.json").read_text(encoding="utf-8"))
    assert lizenz_bplan in plaene["meta"]["note"] and "(Stadt Köln, Bebauungspläne)" not in plaene["meta"]["note"]


def test_bonner_lizenzzeile_ersetzt():
    """Die Zeile des Ratsinformationssystems umfasst nicht mehr alles unter export/koeln/ („export/koeln/…“)."""
    text = LIZENZDATEI.read_text(encoding="utf-8")
    assert "`export/koeln/…`" not in text
    assert "| `export/koeln/` aus dem Ratsinformationssystem" in text


# --- (2) DCAT ohne Pipeline -------------------------------------------------------------------------------------------

def test_lizenz_der_teile():
    """Die strengste Lizenz der Teile; ein Teil ohne erkannte Lizenz oder eine Verteilung ohne Teile bricht ab. Alle
    Lizenzen aus config.SOURCES, den Kennzahlen und den Ebenen sind bekannt (sonst bräche `export` ab)."""
    zero, by, osm = ("a", "dl-de/zero 2.0"), ("b", "dl-de/by-2.0, Land NRW"), ("c", "ODbL 1.0")
    assert publish.lizenz_der_teile([zero]) == "dl-de-zero"
    assert publish.lizenz_der_teile([zero, by]) == "dl-de-by"
    assert publish.lizenz_der_teile([by, zero, osm]) == "odbl"
    for falsch in ([], [zero, ("d", "unbekannt")]):
        with pytest.raises(ValueError):
            publish.lizenz_der_teile(falsch)
    alle = ([(k, s["license"]) for k, s in config.SOURCES.items()]
            + [(k, q["lizenz"]) for k, q in kontext.QUELLEN.items()] + [(k, q["lizenz"]) for k, q in ebenen.QUELLEN.items()]
            + [(k, q["lizenz"]) for k, q in kontext.quellen_stand().items()])
    for teil in alle:
        publish.lizenz_der_teile([teil])


@pytest.mark.parametrize("orte, erwartet", [({config.QUELLE_GEO}, "dl-de-zero"), ({config.QUELLE_BPLAN}, "dl-de-by"),
                                            ({"osm", config.QUELLE_GEO}, "odbl")])
def test_dcat_vorlagen_nach_ortsquellen(tmp_path, monkeypatch, orte, erwartet):
    """vorlagen.geojson: Lizenz nach den location_source der Punkte; das Datenpaket enthält dieselben Teile."""
    monkeypatch.setattr(config, "BPLAN", BPLAN)
    publish.write_dcat(tmp_path / "dcat.jsonld", None, None, orte=orte)
    je = {d["dct:title"]["@value"]: d for d in json.loads((tmp_path / "dcat.jsonld").read_text())["dcat:distribution"]}
    assert je["Verortete Vorlagen (GeoJSON)"]["dct:license"]["@id"] == publish.LICENCE[erwartet]
    assert ("OpenStreetMap" in je["Verortete Vorlagen (GeoJSON)"]["dct:rights"]["rdfs:label"]) == ("osm" in orte)
    assert ("Kartenhintergrund" not in je["Verortete Vorlagen (GeoJSON)"]["dct:rights"]["rdfs:label"])
    assert je["Datenpaket (Zip)"]["dct:license"]["@id"] == publish.LICENCE["odbl" if "osm" in orte else "dl-de-by"]


def test_dcat_ohne_bebauungsplaene(tmp_path, monkeypatch):
    """Ohne Datei der Bebauungspläne: Planregister unter dl-de/zero, Beschreibung ohne Geltungsbereiche; ohne
    vorlagen.geojson und ohne Angabe gelten die Bebauungspläne nur, wenn es sie gibt."""
    monkeypatch.setattr(config, "BPLAN", tmp_path / "fehlt.geojson")
    publish.write_dcat(tmp_path / "dcat.jsonld", None, None)
    je = {d["dct:title"]["@value"]: d for d in json.loads((tmp_path / "dcat.jsonld").read_text())["dcat:distribution"]}
    plan = je["Planregister Bebauungspläne (JSON)"]
    assert plan["dct:license"]["@id"] == publish.LICENCE["dl-de-zero"] and "IT.NRW" not in plan["dct:rights"]["rdfs:label"]
    assert "ohne Geltungsbereiche" in plan["dct:description"]["@value"]
    assert je["Verortete Vorlagen (GeoJSON)"]["dct:license"]["@id"] == publish.LICENCE["dl-de-zero"]
    monkeypatch.setattr(config, "BPLAN", BPLAN)
    publish.write_dcat(tmp_path / "dcat.jsonld", None, None)
    je = {d["dct:title"]["@value"]: d for d in json.loads((tmp_path / "dcat.jsonld").read_text())["dcat:distribution"]}
    assert je["Verortete Vorlagen (GeoJSON)"]["dct:license"]["@id"] == publish.LICENCE["dl-de-by"]


def test_liesmich_nennt_bebauungsplaene():
    assert "geo/" in paket.LIESMICH and "bebauungsplaene_koeln.geojson" in paket.LIESMICH
    assert "IT.NRW" in paket.LIESMICH and BY in paket.LIESMICH


# --- (3) Seite: Planchronik, Kartenlegende, Quellenabsatz --------------------------------------------------------------

def _node(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _teil(muster):
    m = re.search(muster, APP, re.S | re.M)
    assert m, muster
    return m.group(0)


def _planteile():
    return "".join(_teil(m) for m in (r"^  const ISO_DAY = .*?;\n", r"^  const DATUM = .*?;\n", r"^  const fmtDate = .*?;\n",
                                       r"^  const datenBeginn = .*?;\n", r"^  const seitBeginn = .*?;\n",
                                       r"^  const LIZENZEN_LINK = .*?;\n", r"^  const quelleAus = .*?;\n",
                                       r"^  const quelleText = .*?;\n", r"^  const QUELLE_NAME = .*?;\n"))


def test_planchronik_quellen_aus_den_daten():
    """quelleText: Lizenz und Namensnennung aus plaene.json (meta.sources), sonst aus index.json; ohne Angabe der
    Verweis auf die Lizenzübersicht statt einer Lizenz. seitBeginn: Datum aus zeit.json data_start, sonst neutral."""
    quellen = [{"name": n, "url": config.SOURCES[n]["url"], "license": config.SOURCES[n]["license"]}
               for n in (config.QUELLE_OPARL, config.QUELLE_BPLAN)]
    code = ("const esc = (s) => String(s ?? '').replace(/[&<>\"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "
            "'\"': '&quot;', \"'\": '&#39;' }[c]));\nlet index = null, zeit = null;\n" + _planteile() + f"""
const q = {json.dumps(quellen, ensure_ascii=False)};
const aus = {{}};
aus.reg = quelleText({{ meta: {{ sources: q }} }}, "bplan-koeln");
index = {{ meta: {{ sources: q }} }};
aus.index = quelleText(null, "oparl-koeln");
index = null;
aus.ohne = quelleText({{ meta: {{ sources: [] }} }}, "bplan-koeln");
aus.seitOhne = seitBeginn();
zeit = {{ data_start: "2024-12-05" }};
aus.seit = seitBeginn();
zeit = {{ data_start: "kaputt" }};
aus.seitKaputt = seitBeginn();
console.log(JSON.stringify(aus));
""")
    aus = _node(code)
    assert aus["reg"] == "Bebauungspläne, " + config.SOURCES[config.QUELLE_BPLAN]["license"]
    assert aus["index"].startswith("Ratsinformationssystem, dl-de/zero 2.0") and config.NAMENSNENNUNG in aus["index"]
    assert aus["ohne"] == 'Bebauungspläne, Lizenz siehe <a href="data/LICENSE-DATA.md">Lizenzen der Daten</a>'
    assert aus["seit"] == "seit 05.12.2024"
    assert aus["seitOhne"] == aus["seitKaputt"] == "seit Beginn der Daten"


def test_seite_ohne_bonner_lizenz_und_zeitangaben():
    """Planchronik (showPlan) und Kartenlegende: keine Bonner Angaben (CC0, „seit Oktober 2019“, „seit 2019“, Anteil
    ohne Ortsbezug); Quellen der Planchronik aus quelleText; Bebauungspläne als „Bauleitplanung NRW“ belegt."""
    plan = _teil(r"^  async function showPlan\(key\) \{.*?^  \}\n")
    assert not re.search(r"CC0|2019|Stadt Köln, Lage der Bebauungspläne|belegt, Stadt Köln", plan)
    assert 'quelleText(reg, "bplan-koeln")' in plan and 'quelleText(reg, "oparl-koeln")' in plan
    assert "${LIZENZEN_LINK}" in plan and "datenBeginn()" in plan and plan.count("belegt, Bauleitplanung NRW") == 2
    nav = _teil(r"^  function initNav\(\) \{.*?^  \}\n")
    assert '<optgroup label="Anteil eines Themas (${seitBeginn()})">' in nav and "2019" not in nav
    assert "mehr als die Hälfte" not in APP and "Vorlagen ohne Ortsbezug zählen nicht mit" in APP
    assert not re.search(r"CC0|Oktober 2019|seit 2019", APP)
    assert 'bebauungsplan: "Bebauungsplan-Nummer im Titel, Geltungsbereich laut Bauleitplanung NRW (IT.NRW)"' in APP


def test_quellenabsatz_nennt_bebauungsplaene():
    """index.html, „Quellen, Lizenzen und Datenstand“ und „Über“: Bebauungspläne mit IT.NRW und dl-de/by 2.0; der Teil
    zu Kennzahlen und Ebenen nur mit Freigabe „kontext“ (data-funktion)."""
    quellen = re.search(r'<details class="map-legend map-sources" id="sources">.*?</details>', INDEX, re.S).group(0)
    assert "Bebauungspläne aus der Schnittstelle „Bauleitplanung in NRW“ (MHKBD NRW / IT.NRW, Datengrundlage Stadt Köln; " \
           "dl-de/by 2.0)" in quellen
    assert '<span data-funktion="kontext"> · Kennzahlen und Kartenebenen' in quellen and config.NAMENSNENNUNG in quellen
    about = re.search(r'<dialog id="about".*?</dialog>', INDEX, re.S).group(0)
    assert "die Bebauungspläne aus der Schnittstelle „Bauleitplanung in NRW“ (MHKBD NRW / IT.NRW" in about


def test_readme_namensnennung_genau():
    """README: Die Namensnennung der Stadt gilt für Dateien mit Daten aus dem Ratsinformationssystem oder von
    offenedaten-koeln.de, nicht für „jeden Export“ (Kitas, Schulen, Zensus und Bebauungspläne nennen ihre Quelle)."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "steht auf jeder Seite und in jedem Export." not in text
    assert "mit Daten aus dem Ratsinformationssystem oder von offenedaten-koeln.de" in text
    assert 'alt="Daten: dl-de/zero 2.0 und dl-de/by 2.0"' in text
