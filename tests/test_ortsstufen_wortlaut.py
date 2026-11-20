"""Wortlaut der Ortsstufen (Entscheidung 19.11.2026 (1) (C)): „Ort genau (Hausnummer oder Bebauungsplan im Titel)“,
„Ort erkannt (Name im Titel oder Stadtteil laut Stadt)“, „Ort unklar (mehrdeutig oder nur über das Gremium)“, Überschrift
der Legende „Punkte: Wie der Ort bestimmt ist“; derselbe Wortlaut in Legende, Filter, Tour, Dialog „Über“, Seite
„Begriffe“ und Einfacher Sprache. Die Werte hoch/mittel/niedrig in den Daten bleiben. Die früheren Namen („gesichert“,
„erschlossen“, „unsicher“, „Wie sicher …“) stehen nirgends mehr in site/ und in den erzeugten Seiten; Wörter wie
„nach festen Regeln erschlossen“ (Herkunft eines Orts) oder „vorläufig gesichert“ (Überschwemmungsgebiete) sind keine
Ortsstufen und bleiben. Keine Anfragen an Server der Stadt."""
import colorsys
import json
import re
import shutil
import subprocess
from html import unescape
from pathlib import Path

import pytest

from pipeline import begriffsseite, einfachseite

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
APP = (SITE / "app.js").read_text(encoding="utf-8")
TOUR = (SITE / "tour.js").read_text(encoding="utf-8")
INDEX = (SITE / "index.html").read_text(encoding="utf-8")
CSS = (SITE / "style.css").read_text(encoding="utf-8")

# (Wert in den Daten, Name, Kurzform im Filter und in Einfacher Sprache, Klammer, Farbe, Sprungmarke auf begriffe/)
STUFEN = [("hoch", "Ort genau", "genau", "Hausnummer oder Bebauungsplan im Titel", "grün", "angabe-ort-gesichert"),
          ("mittel", "Ort erkannt", "erkannt", "Name im Titel oder Stadtteil laut Stadt", "braun",
           "angabe-ort-erschlossen"),
          ("niedrig", "Ort unklar", "unklar", "mehrdeutig oder nur über das Gremium", "violett", "angabe-ort-unsicher")]
UEBERSCHRIFT = "Wie verlässlich sind die Angaben?"
# Frühere Namen der Ortsstufen und Überschriften (bis 19.11.2026); Sprungmarken wie „angabe-ort-gesichert“ bleiben
ALT = [r"Ort (gesichert|erschlossen|unsicher)\b", r"Sicherheit (des Orts|der Ortsangabe|der Angaben)",
       r"[Ww]ie sicher\b", r">\s*(gesichert|erschlossen|unsicher)\s*<", r"<strong>(gesichert|erschlossen|unsicher)\b",
       r"\b(gesichert|erschlossen|unsicher) \((grün|braun|violett|Koordinate|Hauskoordinate|Name im Titel|mehrdeutig)",
       r"\b(grün|braun|violett) (gesichert|erschlossen|unsicher)\b"]


def _text(html):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _alte_namen(text):
    return [m.group(0) for muster in ALT for m in re.finditer(muster, text)]


def _seiten():
    return {"begriffe": begriffsseite.body("../"), "einfach": einfachseite.body("../"),
            "einfach (Vorschau)": einfachseite.body("../", vorschau=True)}


def test_keine_alten_namen_in_site_und_erzeugten_seiten():
    funde = {}
    for datei in sorted(SITE.rglob("*")):
        if datei.is_file() and datei.suffix in (".js", ".html", ".css", ".md", ".json", ".txt"):
            treffer = _alte_namen(datei.read_text(encoding="utf-8"))
            if treffer:
                funde[str(datei.relative_to(ROOT))] = treffer
    for name, html in _seiten().items():
        treffer = _alte_namen(html) + _alte_namen(_text(html))
        if treffer:
            funde[name] = treffer
    assert funde == {}


def test_namen_in_der_datenansicht():
    """CONF (Vorgang, Liste, Legende): die drei Namen zu den Werten der Daten."""
    m = re.search(r'^  const CONF = \{ hoch: "([^"]+)", mittel: "([^"]+)", niedrig: "([^"]+)" \};$', APP, re.M)
    assert m and list(m.groups()) == [name for _, name, *_ in STUFEN]


def _farben():
    """Farbe je Stufe aus den Tokens in site/style.css (:root), wie color() in site/app.js sie liest."""
    return {wert: re.search(rf"^\s*--{wert}:\s*(#[0-9a-fA-F]{{6}});", CSS, re.M).group(1) for wert, *_ in STUFEN}


def _farbwort(hexwert):
    r, g, b = (int(hexwert[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, _ = colorsys.rgb_to_hls(r, g, b)
    h *= 360
    if 90 <= h < 180:
        return "grün"
    if 15 <= h < 50 and l < 0.45:
        return "braun"
    if 250 <= h < 300:
        return "violett"
    return hexwert


def test_farbwoerter_passen_zu_den_tokens():
    """Tour und Einfache Sprache nennen die Farben der Punkte mit Namen; sie passen zu den Tokens in site/style.css."""
    farben = _farben()
    assert {wert: _farbwort(farben[wert]) for wert, *_ in STUFEN} == {wert: farbe for wert, _, _, _, farbe, _ in STUFEN}


def _legende(color_by):
    """drawLegend aus site/app.js mit nachgebildetem Element; Ebenen aus, keine Vorschau."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    teil = (re.search(r"^  const esc = .*?;\n", APP, re.M).group(0)
            + re.search(r"^  const THEMES = \{.*?\n  \};\n", APP, re.S | re.M).group(0)
            + re.search(r"^  function drawLegend\(\) \{\n.*?\n  \}\n", APP, re.S | re.M).group(0))
    code = f"""
const FARBEN = {json.dumps(_farben())};
const color = (c) => FARBEN[c];
let colorBy = {json.dumps(color_by)}, planOn = false, bauOn = false, bau = null, vorschau = false;
const THEME_COLOR = {{}}, NO_THEME = "#888888";
const kxLegend = () => "", planIndexUrl = () => null, fmtDate = (d) => d;
const legendEl = {{ hidden: false, innerHTML: "", querySelector: () => null }};
""" + teil + """
drawLegend();
console.log(JSON.stringify(legendEl.innerHTML));
"""
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_legende_der_punkte():
    html = _legende("sicherheit")
    farben = _farben()
    assert re.search(r"<summary>(.*?)</summary>", html).group(1) == "Punkte: Wie der Ort bestimmt ist"
    zeilen = re.findall(r'<li><span class="swatch" style="background:(#[0-9a-fA-F]{6})" aria-hidden="true"></span>'
                        r"(.*?)</li>", html)
    assert zeilen == [(farben[wert], f"{name} ({klammer})") for wert, name, _, klammer, *_ in STUFEN]
    assert re.search(r"<summary>(.*?)</summary>", _legende("thema")).group(1) == "Punkte: Thema"


def test_filter_ortsangabe():
    feld = re.search(r'<fieldset id="f-conf">(.*?)</fieldset>', INDEX, re.S).group(1)
    assert re.search(r"<legend>(.*?)</legend>", feld).group(1) == "Ortsangabe"
    labels = [(wert, _text(inhalt)) for wert, inhalt in
              re.findall(r'<label class="check"><input type="checkbox" value="(\w+)" checked>(.*?)</label>', feld)]
    assert labels == [(wert, f"{kurz} ({klammer})") for wert, _, kurz, klammer, *_ in STUFEN]


def test_tour_nennt_namen_klammern_und_farben():
    schritt = re.search(r'title: "Die Karte",\n      text: \(\) => "(.*?)"\n', TOUR).group(1)
    assert ("Die Farbe zeigt, wie der Ort bestimmt ist: "
            + ", ".join(f"{farbe} {name} ({klammer})" for _, name, _, klammer, farbe, _ in STUFEN) + ".") in schritt
    assert "unter „Weitere Filter“ nach Amt, Gremium und Ortsangabe." in TOUR


def test_dialog_ueber():
    abschnitt = re.search(r'<h3 id="about-pruefung" tabindex="-1">(.*?)</h3>(.*?)<h3', INDEX, re.S)
    assert abschnitt.group(1) == UEBERSCHRIFT
    text = _text(abschnitt.group(2))
    (genau, k1), (erkannt, k2), (unklar, k3) = [(name, klammer) for _, name, _, klammer, *_ in STUFEN]
    assert f"Bei Orten unterscheiden wir: {genau} ({k1}), {erkannt} ({k2}) und {unklar} ({k3})." in text
    assert "„abgeleitet“" in text
    for _, name, *_ in STUFEN:
        assert f"<strong>{name}</strong>" in abschnitt.group(2)
    # die Karte im Menü „Über“ öffnet diesen Abschnitt und trägt dieselbe Überschrift
    assert 'data-about="pruefung">' in INDEX and f'<span class="card-title">{UEBERSCHRIFT}</span>' in INDEX


def test_seite_begriffe():
    """Abschnitt „Wie verlässlich eine Angabe ist“ (Sprungmarke sicherheit wie bisher): je Stufe der Name, die Erklärung
    beginnt mit der Klammer; die Sprungmarken der Einträge bleiben die der früheren Namen."""
    html = begriffsseite.body("../")
    assert '<h2 id="sicherheit">Wie verlässlich eine Angabe ist</h2>' in html
    assert '<a href="#sicherheit">Wie verlässlich eine Angabe ist</a>' in html
    for _, name, _, klammer, _, anker in STUFEN:
        assert f'<dt id="{anker}">{name}</dt><dd>{klammer[0].upper()}{klammer[1:]}. ' in html
    # Köln: nicht der Bonner Satz zur Koordinate der Stadt, keine Gebäude aus OpenStreetMap, kein Volltext
    stufen = _text(html.split('<h2 id="sicherheit">', 1)[1])
    for veraltet in ("Die Stadt gibt den Ort mit einer Koordinate an", "Gebäuden oder Anlagen", "Text eines Dokuments"):
        assert veraltet not in stufen
    # Sonderfälle (Entscheidung 19.11.2026 (3) (b): die Klammern bleiben, die Seite „Begriffe“ erklärt sie): Punkt aus
    # der Ortsangabe der Stadt hoch, nur in einem Kölner Stadtteil (Entscheidung 19.11.2026 (4) (d)) und nur bei
    # Erlaubnis für einen Punkt auf einem Haus (build: Punkt außerhalb von `grob`, oparl_location); Stadtteil auch aus
    # einem Punkt der Stadt (build: oparl_sublocality, etwa ohne diese Erlaubnis) und Stadtteil laut Stadt neben einem
    # verworfenen Punkt ((4) (e)); Widerspruch zu einer anderen Angabe und Ortsangabe ohne Kölner Stadtteil niedrig
    # (build: oparl_location ohne Punkt, auch neben einem verworfenen Punkt)
    erklaerung = {name: text for name, text, _ in begriffsseite.ORTSSTUFEN}
    assert erklaerung["Ort genau"].endswith(
        " Gibt die Ortsangabe der Stadt selbst einen Punkt in einem Kölner Stadtteil an, gilt der Ort ebenfalls als "
        "genau; auch das nur bei Vorlagen, bei denen ein Punkt auf einem Haus erlaubt ist.")
    assert ("Gibt die Ortsangabe der Stadt selbst einen Punkt in einem Kölner Stadtteil an, gilt der Ort ebenfalls als "
            "genau" in stufen)
    assert ("oder der Ort widerspricht einer anderen Angabe, etwa weil die Straße nicht im Stadtbezirk der beratenden "
            "Bezirksvertretung liegt." in erklaerung["Ort unklar"])
    assert "Oder die Ortsangabe der Stadt nennt den Stadtteil oder einen Punkt in ihm." in erklaerung["Ort erkannt"]
    assert ("Oder die Ortsangabe der Stadt nennt einen Ort, den der Ratsatlas keinem Kölner Stadtteil zuordnen kann."
            in erklaerung["Ort unklar"])
    # Stadtbezirk aus der Bezirksvertretung auch bei nur einer Ortsangabe der Stadt ohne Kölner Stadtteil (Entscheidung
    # 20.11.2026 (5), build._from_committee mit build._nur_unklarer_ort); der frühere Satz steht nicht mehr da
    satz = ("Oder nur das Gremium deutet auf einen Stadtbezirk: Die Vorlage nennt keinen Ort, den der Ratsatlas "
            "zuordnen kann, und wurde nur in einer Bezirksvertretung beraten.")
    assert satz in erklaerung["Ort unklar"] and satz in stufen
    assert "nennt keinen Ort und wurde nur" not in erklaerung["Ort unklar"] + stufen


def test_einfache_sprache():
    html = einfachseite.body("../")
    assert f'<h2 id="sicher">{UEBERSCHRIFT}</h2>' in html
    assert html.count(f'<a href="#sicher">{UEBERSCHRIFT}</a>') == 2
    assert "Die Farbe eines Punktes zeigt, wie der Ort bestimmt ist." in html
    for _, _, kurz, _, farbe, _ in STUFEN:
        assert f"<li><strong>{kurz} ({farbe}):</strong> " in html
    # ein Haus nur, wenn es eindeutig im Verzeichnis steht, und nur bei Vorlagen der Verwaltung und der Politik
    # (geocode.Gazetteer._adresspunkt, geocode.hausnummer_punkt_erlaubt)
    genau = re.search(r"<li><strong>genau \(grün\):</strong> (.*?)</li>", html).group(1)
    assert genau == ("Im Titel steht eine Straße mit Hausnummer. Und das Haus steht eindeutig im Adressverzeichnis "
                     "der Stadt. Das gilt nur für Vorlagen der Verwaltung und für Anträge und Anfragen der Politik. "
                     "Oder im Titel steht ein Bebauungsplan, und er passt eindeutig.")
