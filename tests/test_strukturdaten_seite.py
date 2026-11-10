"""Strukturdaten, Phase 3 (Seite): Modul site/strukturdaten/strukturdaten.js (Kontext-Panel, Flächenfarben, Tabelle)
und seine Anbindung in site/app.js, site/index.html und tools/seite_bauen.py. Die reinen Hilfen des Moduls laufen mit
node (ohne Browser, ohne Anfragen); die Prüfung im Browser (Playwright, axe) beschreibt TECHNIK.md. Ohne Freigabe
„strukturdaten“ bleibt die veröffentlichte Seite ohne Ordner, Texte und Schalter der Strukturdaten."""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import config, seo

ROOT = Path(__file__).resolve().parents[1]
MODUL = ROOT / "site" / "strukturdaten" / "strukturdaten.js"
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def _node_modul(code):
    """`code` als ES-Modul mit `m` = Hilfen aus strukturdaten.js; Ausgabe JSON."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    quelle = f'import * as m from "{MODUL.as_uri()}";\n{code}'
    r = subprocess.run([node, "--input-type=module", "-e", quelle], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _node(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _teil(quelle, muster):
    m = re.search(muster, quelle, re.S | re.M)
    assert m, muster
    return m.group(0)


# --- Hilfen des Moduls -------------------------------------------------------------------------------------------

def test_tsv_nur_mit_den_spalten_des_vertrags():
    """Zeilen aus raumwerte/ und karte/ werden nur mit genau dem Kopf von werte.tsv gelesen; Felder unverändert."""
    aus = _node_modul("""
const sp = ["raumebene", "raum_id", "indikator_id", "jahr", "wert", "status", "quellobjekt"];
const text = sp.join("\\t") + "\\nstadtteil\\t101\\tkoeln_X\\t2025\\t17.934094\\tok\\tDaten!BQ8915\\nstadtteil\\t101\\tkoeln_X\\t2024\\t\\tgeheim\\tDaten!BQ1\\n";
const z = m.tsv(text, sp);
let fehler = null;
try { m.tsv("raum_id\\twert\\n1\\t2\\n", sp); } catch (e) { fehler = e.message; }
console.log(JSON.stringify({ z, fehler }));
""")
    assert aus["z"][0] == {"raumebene": "stadtteil", "raum_id": "101", "indikator_id": "koeln_X", "jahr": "2025",
                           "wert": "17.934094", "status": "ok", "quellobjekt": "Daten!BQ8915"}
    assert aus["z"][1]["wert"] == "" and aus["z"][1]["status"] == "geheim"
    assert aus["fehler"] and "Kopf" in aus["fehler"]


def test_juengstes_jahr_mit_wert_und_status():
    """Angezeigt wird das jüngste Jahr mit Wert (ok oder abgeleitet); geheim und fehlt haben keinen Wert."""
    aus = _node_modul("""
const r = (jahr, wert, status) => ({ jahr, wert, status });
const reihe = [r("2023", "5", "ok"), r("2024", "6.5", "abgeleitet"), r("2025", "", "geheim")];
console.log(JSON.stringify({
  j: m.juengsteMitWert(reihe).jahr, leer: m.juengsteMitWert([r("2025", "", "fehlt")]),
  hat: [r("1", "0", "ok"), r("1", "", "ok"), r("1", "3", "geheim"), r("1", "2", "abgeleitet")].map(m.hatWert),
}));
""")
    assert aus == {"j": "2024", "leer": None, "hat": [True, False, False, True]}


def test_klassen_nach_quantilen():
    """Grenzen: 20-, 40-, 60-, 80-%-Quantil (Index ⌊q·(n−1)⌋), auf eine Stelle gerundet; ein Wert auf der Grenze gehört
    zur oberen Klasse; gleiche Grenzen fallen zusammen, Grenzen am Minimum entfallen (keine leere Klasse „unter …“);
    zwei Stellen nur, wenn sie mehr Grenzen trennen."""
    aus = _node_modul("""
const werte = Array.from({ length: 11 }, (_, i) => i * 10);   // 0, 10, …, 100
const g = m.grenzen(werte);
const nullen = m.grenzen([0, 0, 0, 0, 0, 0, 1.24, 3, 7, 9]);
const eng = m.grenzen([1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09, 1.1, 1.11]);
console.log(JSON.stringify({ g, klassen: [0, 19.9, 20, 39.99, 40, 80, 100].map((v) => m.klasse(v, g.grenzen)),
  nullen, eng, text: m.klassenText(g.grenzen, 1, "%"), lang: m.klassenText([1.5], 1, "je 1000 Einwohner*innen"),
  farben: [1, 2, 3, 4, 5].map((n) => Array.from({ length: n }, (_, k) => m.farbIndex(k, n))) }));
""")
    assert aus["g"] == {"grenzen": [20, 40, 60, 80], "stellen": 1}
    assert aus["klassen"] == [0, 0, 1, 1, 2, 4, 4]
    # Index 1, 3, 5, 7 der sortierten Werte: 0, 0, 0, 3; die Grenze 0 am Minimum entfällt (keine leere Klasse)
    assert aus["nullen"] == {"grenzen": [3], "stellen": 1}
    assert aus["eng"] == {"grenzen": [1.03, 1.05, 1.07, 1.09], "stellen": 2}   # mit einer Stelle nur 1,1
    assert aus["text"] == ["unter 20,0 %", "20,0 bis unter 40,0 %", "40,0 bis unter 60,0 %", "60,0 bis unter 80,0 %",
                           "ab 80,0 %"]
    assert aus["lang"] == ["unter 1,5", "ab 1,5"]   # lange Einheit steht einmal in der Legende
    assert aus["farben"] == [[2], [0, 4], [0, 2, 4], [0, 1, 3, 4], [0, 1, 2, 3, 4]]


def test_klasse_nach_angezeigtem_wert():
    """Befund Prüfung 10.11.2026: Eingeordnet wird der Wert so, wie Tooltip, Tabelle und Info ihn zeigen (gerundet auf
    die Stellen der Grenzen); ein Wert, der gerundet auf der Grenze liegt, gehört zur oberen Klasse, und keine Klasse
    bleibt leer. Beispiel Stadtbezirke koeln_abg_unter18 2025 und Stadtteile koeln_abg_ab65 2012."""
    aus = _node_modul("""
const bezirke = [9.07, 14.79, 15.07, 15.25, 16.13, 17.22, 17.54, 17.90, 19.73];
const g = m.grenzen(bezirke), d = Math.max(g.stellen, 1);
const zaehl = (werte, gg, st) => { const n = new Array(gg.length + 1).fill(0); werte.forEach((v) => n[m.klasse(v, gg, st)]++); return n; };
const t = m.klassenText([16.1, 17.4, 19.6, 21.9], 1, "%");
console.log(JSON.stringify({ g, zaehl: zaehl(bezirke, g.grenzen, d), ehrenfeld: [m.zahl(15.25, d), m.klasse(15.25, g.grenzen, d)],
  ab65: [16.06, 16.07, 19.55].map((v) => [m.zahl(v, 1), m.klasse(v, [16.1, 17.4, 19.6, 21.9], 1)]), t,
  genau: m.klasse(16.06, [16.1], undefined), halb: [m.gerundet(19.55, 1), m.gerundet(0.35, 1), m.gerundet(-2.25, 1), m.zahl(0.35, 1), m.gerundet(2.675, 2), m.zahl(2.675, 2)],
  unten: m.grenzen([14.76, 14.79, 15.07, 15.25, 16.13, 17.22]) }));
""")
    assert aus["g"] == {"grenzen": [14.8, 15.3, 16.1, 17.5], "stellen": 1}
    assert aus["zaehl"] == [1, 2, 1, 2, 3]   # vorher [2, 2, 0, 2, 3] (Wert 15,25 unter der Grenze 15,3)
    assert aus["ehrenfeld"] == ["15,3", 2]
    # angezeigt 16,1 → Klasse „16,1 bis unter 17,4“ (1), nicht „unter 16,1“; 19,6 → „19,6 bis unter 21,9“ (3)
    assert aus["ab65"] == [["16,1", 1], ["16,1", 1], ["19,6", 3]]
    assert aus["t"][1] == "16,1 bis unter 17,4 %" and aus["t"][3] == "19,6 bis unter 21,9 %"
    assert aus["genau"] == 0   # ohne Stellen der genaue Wert (wie bisher)
    assert aus["halb"] == [19.6, 0.4, -2.3, "0,4", 2.68, "2,68"]   # Rundung wie die Anzeige (nicht toFixed: 0,3 und 2,67)
    # Minimum 14,76 wird als 14,8 gezeigt: eine Grenze 14,8 läge auf ihm und ließe „unter 14,8“ leer
    assert 14.8 not in aus["unten"]["grenzen"]


def test_klassen_stimmen_mit_anzeige_und_legende():
    """Zufällige Reihen (fest geseedet) mit 1 bis 3 Nachkommastellen: jede Klasse hat mindestens einen Wert, und der
    angezeigte Wert liegt in den Grenzen der Beschriftung seiner Klasse (als Zahlen verglichen)."""
    aus = _node_modul("""
let s = 42; const r = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
const fehler = [];
for (let lauf = 0; lauf < 400; lauf++) {
  const n = 3 + Math.floor(r() * 120), st = 1 + Math.floor(r() * 3), spanne = [1, 5, 40, 300][Math.floor(r() * 4)];
  const werte = Array.from({ length: n }, () => Number((r() * spanne + (r() < 0.2 ? -spanne / 3 : 0)).toFixed(st)));
  const { grenzen: g, stellen } = m.grenzen(werte), d = Math.max(stellen, 1);
  const zahlen = new Array(g.length + 1).fill(0);
  for (const v of werte) {
    const k = m.klasse(v, g, d), x = Number(m.zahl(v, d).replace(/[.]/g, "").replace(",", ".").replace("−", "-"));
    zahlen[k]++;
    if ((k > 0 && x < g[k - 1]) || (k < g.length && x >= g[k])) fehler.push({ lauf, v, k, g });
  }
  if (zahlen.some((z) => z === 0)) fehler.push({ lauf, leer: zahlen, g, werte: werte.slice(0, 10) });
}
console.log(JSON.stringify(fehler.slice(0, 5)));
""")
    assert aus == []


def test_feste_grenzen_ueber_alle_jahre_vergleichbar():
    """Mit festen Grenzen (alle Jahre einer Raumebene) bedeutet dieselbe Farbe in jedem Jahr dasselbe; mit Quantilen
    dieses Jahres nicht."""
    aus = _node_modul("""
const j2012 = [10, 11, 12, 13, 14], j2025 = [20, 21, 22, 23, 24];
const fest = m.grenzen([...j2012, ...j2025]).grenzen, nur2025 = m.grenzen(j2025).grenzen;
console.log(JSON.stringify({ fest: j2012.concat(j2025).map((v) => m.klasse(v, fest)), quantil: j2025.map((v) => m.klasse(v, nur2025)) }));
""")
    # Grenzen über beide Jahre (Index 1, 3, 5, 7): 11, 13, 20, 22
    assert aus["fest"][:5] == [0, 1, 1, 2, 2] and aus["fest"][5:] == [3, 3, 4, 4, 4]
    # nur 2025 (Index 0, 1, 2, 3): 20 am Minimum entfällt, 21, 22, 23
    assert aus["quantil"] == [0, 1, 2, 3, 3]


def test_tabelle_sortiert_ohne_rangfolge():
    """Sortierung nach Name (deutsches Alphabet), Wert oder Status; Gebiete ohne Wert stehen in beiden Richtungen am
    Ende; die Zeilen erhalten keine Platzziffer."""
    aus = _node_modul("""
const z = [{ name: "Zollstock", wert: 3, statusText: "Wert der Quelle" }, { name: "Ägidienberg", wert: null, statusText: "nicht veröffentlicht" },
  { name: "Altstadt/Nord", wert: 7, statusText: "Wert der Quelle" }, { name: "Bayenthal", wert: 3, statusText: "Wert der Quelle" }];
const n = (l) => l.map((x) => x.name);
console.log(JSON.stringify({ name: n(m.sortiert(z, "name", "aufsteigend")), auf: n(m.sortiert(z, "wert", "aufsteigend")),
  ab: n(m.sortiert(z, "wert", "absteigend")), felder: Object.keys(m.sortiert(z, "wert", "aufsteigend")[0]) }));
""")
    assert aus["name"] == ["Ägidienberg", "Altstadt/Nord", "Bayenthal", "Zollstock"]
    assert aus["auf"] == ["Bayenthal", "Zollstock", "Altstadt/Nord", "Ägidienberg"]
    assert aus["ab"] == ["Altstadt/Nord", "Bayenthal", "Zollstock", "Ägidienberg"]
    assert set(aus["felder"]) == {"name", "wert", "statusText"}


def test_vergleich_im_juengsten_gemeinsamen_jahr():
    """Wegweiser: jüngstes Jahr, für das Bonn, Köln und Wuppertal einen Wert haben."""
    aus = _node_modul("""
const z = [["bonn", "2023"], ["koeln", "2023"], ["wuppertal", "2023"], ["bonn", "2024"], ["koeln", "2024"]].map(([kommune, jahr]) => ({ kommune, jahr }));
console.log(JSON.stringify([m.gemeinsamesJahr(z, ["bonn", "koeln", "wuppertal"]), m.gemeinsamesJahr(z.slice(3), ["bonn", "koeln", "wuppertal"])]));
""")
    assert aus == ["2023", None]


def test_zeitreihe_mit_luecken():
    """Kleine Zeitreihe: keine Linie über Jahre ohne Wert (geheim, fehlt); einzelne Werte als Punkt."""
    aus = _node_modul("""
const r = (jahr, wert, status = "ok") => ({ jahr, wert, status });
const l = m.linie([r("2012", "1"), r("2013", "2"), r("2014", "", "geheim"), r("2015", "3"), r("2016", "", "fehlt"), r("2017", "4"), r("2018", "5")]);
console.log(JSON.stringify({ pfade: l.pfade.length, punkte: l.punkte.length, letzter: Boolean(l.letzter), leer: m.linie([r("2012", "", "geheim")]) }));
""")
    assert aus == {"pfade": 2, "punkte": 1, "letzter": True, "leer": {"pfade": [], "punkte": []}}


def test_modul_liest_nur_den_datenvertrag():
    """Das Modul fragt nur Dateien unter data/strukturdaten/ ab (Datenvertrag und Aufteilung für die Seite), keine
    anderen Adressen; es rechnet keine Werte über Raumebenen zusammen (keine Summen über Zeilen)."""
    text = MODUL.read_text(encoding="utf-8")
    assert re.findall(r"fetch\(", text) == ["fetch("], "nur über holen()"
    assert 'const ORT = "data/strukturdaten/";' in text and "fetch(ORT + pfad)" in text
    dateien = set(re.findall(r'holen\(`?"?([a-z_/.${}]+)', text))
    assert dateien <= {"anzeige.json", "meta.json", "indikatoren.tsv", "gesamtstadt.tsv", "raum/${ebene}.geojson",
                       "raumwerte/${ebene}/${id}.tsv", "karte/${ebene}/${ind}.tsv", "pfad"}, dateien
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), "keine festen Adressen"
    assert ".reduce(" not in text.replace("weitere.reduce((s, x) => s + x.ids.length, 0)", ""), "keine Summen über Werte"


def test_flaechen_ohne_vereinfachung_durch_leaflet():
    """Die Quartiere sind als lückenlose Abdeckung vereinfacht (raum/quartier.geojson, gemeinsame Grenzen); Leaflet
    vereinfacht die Pfade der Flächenfarben nicht noch einmal je Fläche (smoothFactor 0), damit Nachbarn im SVG
    dieselben Grenzstrecken haben und keine Fugen entstehen (Browserprüfung vom 10.11.2026)."""
    text = MODUL.read_text(encoding="utf-8")
    schicht = _teil(text, r"^  schicht = ctx\.L\.geoJSON\(R\.geo, \{\n.*?\n  \}\)\.addTo\(ctx\.karte\(\)\);\n")
    assert 'pane: "strukturdaten", renderer, style: stil, smoothFactor: 0,' in schicht


# --- Freigabe: ohne „strukturdaten“ keine Spuren -------------------------------------------------------------------

def _seite_bauen():
    spec = importlib.util.spec_from_file_location("seite_bauen", ROOT / "tools" / "seite_bauen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ordner_des_moduls_nur_mit_freigabe(monkeypatch, tmp_path):
    """tools/seite_bauen.py: ohne Freigabe fehlt der Ordner strukturdaten/ (Modul und Stile) auf der Seite."""
    assert MODUL.is_file() and (ROOT / "site" / "strukturdaten" / "strukturdaten.css").is_file()
    mod = _seite_bauen()
    for an in (False, True):
        ziel = tmp_path / str(an)
        shutil.copytree(ROOT / "site" / "strukturdaten", ziel / "strukturdaten")
        monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", an)
        mod.ohne_abgeschaltete_ordner(ziel)
        assert (ziel / "strukturdaten" / "strukturdaten.js").exists() == an


def test_texte_der_startseite_nur_mit_freigabe(monkeypatch):
    """index.html: Quellenzeile und „Über“ nennen die Strukturdaten in <span data-funktion="strukturdaten">; ohne
    Freigabe entfernt seo.ohne_abgeschaltete sie, mit Freigabe bleibt die Seite unverändert."""
    teile = re.findall(r'<span data-funktion="strukturdaten">(.*?)</span>', INDEX, re.S)
    assert len(teile) == 2 and "Statistischer Datenkatalog Köln" in teile[0] and "CC0 1.0" in teile[0]
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", False)
    aus = seo.ohne_abgeschaltete(INDEX)
    assert 'data-funktion="strukturdaten"' not in aus and "Strukturdaten" not in aus and "Wegweiser" not in aus
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
    mit = seo.ohne_abgeschaltete(INDEX)
    assert all(f'<span data-funktion="strukturdaten">{t}</span>' in mit for t in teile)
    assert mit.replace("".join(f'<span data-funktion="strukturdaten">{t}</span>' for t in teile[:1]), "").count("Strukturdaten") == 1


def test_app_laedt_das_modul_nur_mit_freigabe():
    """site/app.js: Modul, Schalter auf der Karte und Platz im Vorgang nur mit idx.meta.funktionen.strukturdaten."""
    struktur = _teil(APP, r"^  function struktur\(\) \{\n.*?\n  \}\n")
    assert struktur.startswith("  function struktur() {\n    if (!funktionen.strukturdaten) return Promise.resolve(null);")
    assert 'import("./strukturdaten/strukturdaten.js")' in struktur
    assert "    if (funktionen.strukturdaten) new SdToggle().addTo(map);\n" in APP
    vorgang = _teil(APP, r"^  function sdStadtteil\(p\) \{\n.*?\n  \}\n")
    assert "if (!funktionen.strukturdaten) return null;" in vorgang
    assert APP.count("import(\"./strukturdaten/") == 1


def test_saetze_der_kennzahlen_ohne_freigabe_unveraendert():
    """Steckbrief und Vorgang: ohne Kennzahlen aus der Stadtstatistik (kontext.json ohne Freigabe) die bisherigen
    Sätze; mit Option b nennen sie Einwohnerzahl und Altersanteile als Werte der Stadt mit Jahr (nicht umgerechnet), in
    der Reihenfolge der Tabelle (meta.reihenfolge, nicht der sortierten Schlüssel). Der Wortlaut kommt aus kontext.json
    (meta.nicht_umgerechnet, pipeline/kontext.py); app.js enthält ihn nicht."""
    from pipeline import kontext
    teil = "\n".join(_teil(APP, m) for m in (r"^  const kStat = .*?;\n", r"^  const kStatTitel = .*?;\n",
                                              r"^  function kUmgerechnet\(ebene\) \{\n.*?\n  \}\n",
                                              r"^  function kUmgerechnetVorgang\(keys\) \{\n.*?\n  \}\n"))
    ohne = {"kennzahlen": {"einwohner": {"titel": "Einwohner", "quelle": "zensus"}, "miete": {"titel": "Miete", "quelle": "zensus"}}}
    kennzahlen = {
        "einwohner": {"titel": "Einwohnerinnen und Einwohner mit Hauptwohnsitz", "quelle": "strukturdaten", "jahr": "2025"},
        "unter_18": {"titel": "Anteil unter 18 Jahren", "quelle": "strukturdaten", "jahr": "2025", "abgeleitet": True},
        "ab_65": {"titel": "Anteil ab 65 Jahren", "quelle": "strukturdaten", "jahr": "2025", "abgeleitet": True},
        "miete": {"titel": "Miete", "quelle": "zensus"}}
    mit = {"kennzahlen": dict(sorted(kennzahlen.items())),   # kontext.json schreibt die Schlüssel sortiert
           "nicht_umgerechnet": kontext.nicht_umgerechnet(kennzahlen, ["einwohner", "unter_18", "ab_65", "miete"])}
    aus = _node(f"""
let kontext = {{ meta: {json.dumps(ohne)} }};
{teil}
const ohne = [kUmgerechnet("Stadtteile"), kUmgerechnetVorgang(["einwohner", "miete"])];
kontext = {{ meta: {json.dumps(mit, ensure_ascii=False)} }};
console.log(JSON.stringify({{ ohne, mit: [kUmgerechnet("Stadtbezirke"), kUmgerechnetVorgang(["unter_18", "miete"]), kUmgerechnetVorgang(["unter_18"])] }}));
""")
    assert aus["ohne"] == ["Alle Werte sind auf Stadtteile umgerechnet; Stichtage verschieden.", "Werte auf Stadtteile umgerechnet."]
    assert aus["mit"][0].startswith("Einwohnerinnen und Einwohner mit Hauptwohnsitz (2025), Anteil unter 18 Jahren (2025), "
                                    "Anteil ab 65 Jahren (2025): Werte der Kölner Stadtstatistik für das Gebiet, nicht umgerechnet")
    assert "(abgeleitet)" in aus["mit"][0] and aus["mit"][0].endswith("Alle übrigen Werte sind auf Stadtbezirke umgerechnet; Stichtage verschieden.")
    assert aus["mit"][1] == "Anteil unter 18 Jahren (2025) aus der Kölner Stadtstatistik, nicht umgerechnet (Altersanteile abgeleitet); übrige Werte auf Stadtteile umgerechnet."
    assert aus["mit"][2].endswith("(Altersanteile abgeleitet).")
    for text in kontext.NICHT_UMGERECHNET.values():
        assert text not in APP


def test_kartenschalter_nur_eine_flaechenfarbe():
    """Flächenfarben der Strukturdaten und Bodenrichtwerte bzw. Hitze schließen sich aus; die Ebene „gebiete“ färbt
    nicht, solange die Strukturdaten an sind (updateNav mit flaechenAus)."""
    update = _teil(APP, r"^  function updateNav\(force\) \{\n.*?\n  \}\n")
    assert "    if (flaechenAus) {\n      navOrtsteile.remove(); navBezirke.remove();" in update
    assert 'if (kxOn.has(k) && (k === "brw" || k === "klima") && sdModul && sdModul.an()) sdModul.ebene(false);' in APP
    assert 'kxAus() { for (const k of ["brw", "klima"]) if (kxOn.has(k))' in APP


def _code_zeilen(quelle):
    """Zeilen ohne Kommentare (ganze Kommentarzeilen und „ // …“ am Zeilenende)."""
    return [re.sub(r"\s//\s.*$", "", z) for z in quelle.splitlines() if not z.lstrip().startswith("//")]


def test_tour_nennt_strukturdaten_nur_mit_schalter():
    """site/tour.js: Karte und Liste nennen Zusatzmodule nur über sichtbare Elemente mit data-tour-karte bzw.
    data-tour-liste (das Modul der Strukturdaten setzt sie an seinem Schalter); ohne sie bleiben die Texte, auch die der
    Vorschau, wie bisher. Ohne Freigabe enthalten app.js und tour.js keine Texte der Strukturdaten (Schalter, Tour,
    Hinweise kommen aus dem Modul bzw. aus kontext.json)."""
    tour = (ROOT / "site" / "tour.js").read_text(encoding="utf-8")
    teil = _teil(tour, r"^  const MOBILE = matchMedia.*?\n  \];\n")
    ergebnis = {}
    for an in (False, True):
        el = [{"hidden": False, "a": {"data-tour-karte": "SATZ-KARTE.", "data-tour-liste": "SATZ-LISTE."}},
              {"hidden": True, "a": {"data-tour-karte": "VERBORGEN."}}] if an else []
        code = f"""
const EL = {json.dumps(el)}.map((e) => ({{ hidden: e.hidden, getAttribute: (k) => e.a[k] ?? null, a: e.a }}));
const matchMedia = () => ({{ matches: false }});
const document = {{ documentElement: {{ dataset: {{}} }}, querySelector: () => null,
  querySelectorAll: (sel) => {{ const m = /^\\[(data-tour-[a-z]+)\\]$/.exec(sel); return m ? EL.filter((e) => m[1] in e.a) : []; }} }};
""" + teil + """
const wert = (t) => (typeof t === "function" ? t() : t);
console.log(JSON.stringify(STEPS.filter((s) => s.title === "Die Karte" || s.title === "Die Vorlagen").map((s) => [wert(s.text), wert(s.vorschau)])));
"""
        ergebnis[an] = _node(code)
    texte_aus = " ".join(t for paar in ergebnis[False] for t in paar)
    texte_an = " ".join(t for paar in ergebnis[True] for t in paar)
    assert "SATZ" not in texte_aus and "VERBORGEN" not in texte_an
    assert texte_an.count(" SATZ-KARTE.") == 2 and texte_an.count(" SATZ-LISTE.") == 2
    for (aus_text, aus_vorschau), (an_text, an_vorschau) in zip(ergebnis[False], ergebnis[True]):
        assert an_text.replace(" SATZ-KARTE.", "").replace(" SATZ-LISTE.", "") == aus_text
        assert an_vorschau.replace(" SATZ-KARTE.", "").replace(" SATZ-LISTE.", "") == aus_vorschau
    for name, quelle in (("app.js", APP), ("tour.js", tour)):
        for z in _code_zeilen(quelle):
            assert "Strukturdaten" not in z and "Stadtstatistik" not in z, (name, z)
    modul = MODUL.read_text(encoding="utf-8")
    assert "tourKarte:" in modul and "tourListe:" in modul and "b.dataset.tourKarte" in modul
