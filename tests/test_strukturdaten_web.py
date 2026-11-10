"""Strukturdaten Phase 3, Datenseite (Entscheidungen des Auftraggebers vom 10.11.2026): abgeleitete Altersanteile im
Datenvertrag (pipeline/strukturdaten.py), Auslieferung auf Seite und im Datenpaket hinter der Freigabe „strukturdaten“
(pipeline/strukturdaten_web.py, pipeline/paket.py, tools/seite_bauen.py), Kennzahlen nach Option (b)
(pipeline/kontext.py), Texte nach Freigabe (pipeline/freigaben.py, data/LICENSE-DATA.md, pipeline/glossar.py).

Eingaben der Normalisierung sind erfunden (Aufbau wie tests/test_strukturdaten.py, dazu die elf Altersgruppen); der
Seitenbau läuft über den lokalen OParl-Testserver. Die Prüfungen am echten Datenvertrag lesen nur data/strukturdaten/
und data/kontext/ aus dem Repository; keine Anfragen an Server der Stadt oder andere Adressen. Die Freigabe wird nur in
Tests umgeschaltet (monkeypatch.setitem auf config.ZUSATZTHEMEN), nie über die Umgebung."""
import csv
import gzip
import importlib.util
import json
import re
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")
pytest.importorskip("shapefile")

import test_strukturdaten as ts  # noqa: E402  (Hilfen der Normalisierung: erfundene XLSX, Geometrien, Protokoll)

from pipeline import (build, config, ebenen, export, freigaben, glossar, kontext, paket, publish,  # noqa: E402
                      sessionnet, strukturdaten, strukturdaten_web)

ROOT = Path(__file__).resolve().parents[1]
VERTRAG = ROOT / "data" / "strukturdaten"

# Altersgruppen wie im Blatt Daten (Code, Name); Spalten L bis V nach den acht Spalten aus test_strukturdaten.SPALTEN
ALTER = [("A0029A", "Einwohner*innen, 00 < 03 Jahre"), ("A0035A", "Einwohner*innen, 03 < 06 Jahre"),
         ("A0291A", "Einwohner*innen, 06 < 15 Jahre"), ("A0043A", "Einwohner*innen, gesamt, 15 < 18 Jahre"),
         ("A0292A", "Einwohner*innen, gesamt, 18 < 21 Jahre"), ("A0293A", "Einwohner*innen, gesamt, 21 < 35 Jahre"),
         ("A0294A", "Einwohner*innen, gesamt, 35 < 60 Jahre"), ("A0060A", "Einwohner*innen, gesamt, 60 < 65 Jahre"),
         ("A0295A", "Einwohner*innen, gesamt, 65 < 75 Jahre"), ("A0065A", "Einwohner*innen, gesamt, 75 < 80 Jahre"),
         ("A0027A", "Einwohner*innen, gesamt, 80 Jahre und älter")]
SPALTE = {code: chr(ord("L") + i) for i, (code, _) in enumerate(ALTER)}
SPALTE["A0025A"] = "D"
ANTEILE = (3, 3, 9, 3, 3, 21, 33, 7, 9, 4)   # Prozent der ersten zehn Gruppen; die elfte erhält den Rest


def _werte_alter(raum, jahr):
    """Erfundene Werte wie test_strukturdaten._werte, dazu Altersgruppen, die zusammen A0025A ergeben."""
    basis = ts._werte_orig(raum, jahr)
    gesamt = basis[0]
    gruppen = [gesamt * a // 100 for a in ANTEILE]
    return basis + gruppen + [gesamt - sum(gruppen)]


def _sonderfaelle(daten):
    daten["M6"] = "*"                      # 101 / 2025: Altersgruppe 3–6 geheim → unter 18 geheim
    daten["L7"], daten["T7"] = "*", None   # 102 / 2025: unter 18 geheim, ab 65 fehlt (leere Zelle)
    daten["N3"], daten["O3"] = "*", None   # Bezirk 1 / 2025: geheim und fehlt in derselben Formel → geheim
    daten["U16"] = None                    # 201 / 2024: Altersgruppe 75–80 fehlt → ab 65 fehlt
    # Quartier 101010003 / 2025 (Zeile 19): alle Einwohnerzahlen 0 → Anteil nicht definiert (fehlt)
    for buchstabe in "DEFG" + "".join(SPALTE[c] for c, _ in ALTER):
        daten[f"{buchstabe}19"] = 0
    # Quartier 102010001 / 2025 (Zeile 20): 1 von 32 unter 18 → 3,125 % (kaufmännisch 3.13), ab 65 6 von 32 → 18.75
    for buchstabe, wert in zip("DEFGH", (32, 30, 2, 16, 50.0)):
        daten[f"{buchstabe}20"] = wert
    for (code, _), wert in zip(ALTER, (1, 0, 0, 0, 0, 10, 10, 5, 3, 2, 1)):
        daten[f"{SPALTE[code]}20"] = wert


@pytest.fixture
def ts_umgebung(tmp_path, monkeypatch):
    """Wie `umgebung` in tests/test_strukturdaten.py: Zwischenspeicher und Ausgabe im Temp-Ordner, erfundene Stadtteile
    und Stadtbezirke, keine Freigabe für Abrufe."""
    dl, aus = tmp_path / "dl", tmp_path / "aus"
    monkeypatch.setenv("STRUKTURDATEN_DL", str(dl))
    monkeypatch.setenv("STRUKTURDATEN_AUS", str(aus))
    for _, variable in (*strukturdaten.DATEIEN.values(), strukturdaten.PROTOKOLL):
        monkeypatch.delenv(variable, raising=False)
    for variable in ("STRUKTURDATEN_ABRUF", "RATSATLAS_STADT_INFORMIERT", "STRUKTURDATEN_OPENAPI_BESTAETIGT"):
        monkeypatch.delenv(variable, raising=False)
    for ebene, pfad in ts.geo_schreiben(tmp_path / "geo").items():
        monkeypatch.setenv(strukturdaten.GEO[ebene][1], str(pfad))
    return dl, aus


@pytest.fixture
def mit_alter(monkeypatch):
    """test_strukturdaten.xlsx_bauen mit den Altersgruppen (Spalten L bis V)."""
    monkeypatch.setattr(ts, "_werte_orig", ts._werte, raising=False)
    monkeypatch.setattr(ts, "SPALTEN", ts.SPALTEN + [f"{c} - {n}" for c, n in ALTER])
    monkeypatch.setattr(ts, "_werte", _werte_alter)


def _normalisieren(dl, aendern=_sonderfaelle):
    pfade = ts.dateien_schreiben(dl)
    ts.xlsx_bauen(pfade["xlsx"], aendern)
    ts.protokoll_schreiben(dl, pfade)
    return strukturdaten.write()


def _lesen(pfad):
    with open(pfad, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def _quartier(aus):
    with gzip.open(aus / "werte_quartier.tsv.gz", "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def _anteil(zaehler, nenner):
    return str((Decimal(zaehler) * 100 / Decimal(nenner)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _formel(codes, nr):
    *z, n = codes
    return f"({'+'.join(f'Daten!{SPALTE[c]}{nr}' for c in z)})/Daten!{SPALTE[n]}{nr}*100"


UNTER18 = ("A0029A", "A0035A", "A0291A", "A0043A", "A0025A")
AB65 = ("A0295A", "A0065A", "A0027A", "A0025A")


# --- (1) Abgeleitete Altersanteile im Datenvertrag ---------------------------------------------------------------------

def test_altersgruppen_aus_den_namen():
    assert strukturdaten.altersgruppe("Einwohner*innen, 00 < 03 Jahre") == (0, 3)
    assert strukturdaten.altersgruppe("Einwohner*innen, gesamt, 15 < 18 Jahre") == (15, 18)
    assert strukturdaten.altersgruppe("Einwohner*innen, gesamt, 80 Jahre und älter") == (80, None)
    for name in ("Einwohner, männlich, 06 < 15 Jahre", "Einwohner*innen, mit Migrationshintergrund, 00 < 18 Jahre",
                 "Einwohner*innen, gesamt"):
        assert strukturdaten.altersgruppe(name) is None


def test_ableitung_rundung_und_status():
    """Dezimal gerechnet, kaufmännisch gerundet (3,125 → 3.13, nicht 3.12 wie round()); geheim vor fehlt; Nenner 0 →
    fehlt; quellobjekt nennt alle Zellen."""
    spalte = {c: i for i, c in enumerate(("A0029A", "A0035A", "A0291A", "A0043A", "A0025A"))}
    buchstabe = dict(zip(spalte, "EFGHD"))
    f = strukturdaten.ableitung("koeln_abg_unter18", spalte, buchstabe)
    assert f(7, [1, 0, 0, 0, 32]) == ("3.13", "abgeleitet", "(Daten!E7+Daten!F7+Daten!G7+Daten!H7)/Daten!D7*100")
    assert round(3.125, 2) == 3.12   # Gegenprobe: binäres round() rundet hier ab
    assert f(2, [1, 1, 1, 1, 8])[:2] == ("50.00", "abgeleitet")
    assert f(2, [1.0, 2, 3, 4, 300])[:2] == ("3.33", "abgeleitet")
    assert f(2, ["*", None, 1, 1, 10])[:2] == ("", "geheim")
    assert f(2, [1, "", 1, 1, 10])[:2] == ("", "fehlt")
    assert f(2, [1, 1, 1, 1, "*"])[:2] == ("", "geheim")
    assert f(2, [0, 0, 0, 0, 0])[:2] == ("", "fehlt")


def test_abgeleitete_indikatoren_und_werte(ts_umgebung, mit_alter):
    dl, aus = ts_umgebung
    _normalisieren(dl)
    ind = {i["indikator_id"]: i for i in _lesen(aus / "indikatoren.tsv")}
    for iid, name in (("koeln_abg_unter18", "0 bis unter 18"), ("koeln_abg_ab65", "ab 65")):
        i = ind[iid]
        assert (i["typ"], i["einheit"], i["zaehler_id"], i["nenner_id"]) == ("anteil", "%", "", "")
        assert name in i["name"] and i["name"].endswith("(abgeleitet)")
        assert i["thema"] == ind["koeln_A0025A"]["thema"] and i["lizenz"] == strukturdaten.KOELN_LIZENZ
        assert "abgeleitet" in i["namensnennung"] and "Werte unverändert" not in i["namensnennung"]
        assert "/ koeln_A0025A × 100" in i["metatext"] and "Haupt- und Nebenwohnsitz" in i["metatext"]
        assert "Kein Wert (status geheim), wenn eine der Altersgruppen" in i["metatext"]
        assert "kaufmännisch auf 2 Nachkommastellen" in i["metatext"]
        assert "Die 11 Altersgruppen des Datenkatalogs ergeben zusammen koeln_A0025A" in i["metatext"]
        assert i["raumebenen"] == "gesamtstadt;stadtbezirk;stadtteil;quartier" and i["jahre"] == "2024-2025"
    werte = {(w["raumebene"], w["raum_id"], w["indikator_id"], w["jahr"]): w for w in _lesen(aus / "werte.tsv")}
    abg = [w for w in werte.values() if w["indikator_id"].startswith("koeln_abg_")]
    assert len(abg) == 6 * 2 * 2   # sechs Räume, zwei Jahre, zwei Anteile; keine Sozialräume
    g = _werte_alter("0 / Stadt Köln", 2025)
    w = werte[("gesamtstadt", "0", "koeln_abg_unter18", "2025")]
    assert (w["wert"], w["status"], w["quellobjekt"]) == (_anteil(sum(g[8:12]), g[0]), "abgeleitet", _formel(UNTER18, 2))
    w = werte[("gesamtstadt", "0", "koeln_abg_ab65", "2025")]
    assert (w["wert"], w["status"], w["quellobjekt"]) == (_anteil(sum(g[16:19]), g[0]), "abgeleitet", _formel(AB65, 2))
    assert re.fullmatch(r"\d+\.\d\d", w["wert"])
    for schluessel, status in ((("stadtteil", "101", "koeln_abg_unter18", "2025"), "geheim"),
                               (("stadtteil", "101", "koeln_abg_ab65", "2025"), "abgeleitet"),
                               (("stadtteil", "102", "koeln_abg_unter18", "2025"), "geheim"),
                               (("stadtteil", "102", "koeln_abg_ab65", "2025"), "fehlt"),
                               (("stadtbezirk", "1", "koeln_abg_unter18", "2025"), "geheim"),
                               (("stadtteil", "201", "koeln_abg_ab65", "2024"), "fehlt"),
                               (("stadtteil", "201", "koeln_abg_unter18", "2024"), "abgeleitet")):
        w = werte[schluessel]
        assert w["status"] == status, schluessel
        assert (w["wert"] == "") == (status != "abgeleitet"), schluessel
    assert werte[("stadtteil", "102", "koeln_abg_ab65", "2025")]["quellobjekt"] == _formel(AB65, 7)
    q = {(w["raum_id"], w["indikator_id"], w["jahr"]): w for w in _quartier(aus)}
    assert (q[("102010001", "koeln_abg_unter18", "2025")]["wert"], q[("102010001", "koeln_abg_ab65", "2025")]["wert"]) \
        == ("3.13", "18.75")
    assert q[("102010001", "koeln_abg_unter18", "2025")]["quellobjekt"] == _formel(UNTER18, 20)
    for iid in ("koeln_abg_unter18", "koeln_abg_ab65"):
        assert (q[("101010003", iid, "2025")]["wert"], q[("101010003", iid, "2025")]["status"]) == ("", "fehlt")
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    a = meta["abgeleitet"]
    assert set(a["indikatoren"]) == {"koeln_abg_unter18", "koeln_abg_ab65"}
    assert a["indikatoren"]["koeln_abg_unter18"]["zaehler"] == [f"koeln_{c}" for c in UNTER18[:-1]]
    assert a["indikatoren"]["koeln_abg_ab65"]["altersgruppen"]["koeln_A0027A"] == "80 Jahren und älter"
    assert a["altersgruppen_summe"]["gilt"] is True and meta["vertrag_version"] == "1.1"
    assert "abgeleitet" in meta["formate"]["wert"] and "2 Nachkommastellen" in meta["formate"]["wert"]
    assert "status ok, geheim oder abgeleitet" in meta["formate"]["jahre"]
    assert a["beispiel_quellobjekt"] in meta["quellobjekt"]


def test_vorhandene_zeilen_bleiben_byte_gleich(ts_umgebung, mit_alter, monkeypatch):
    """Dieselben Eingaben ohne Ableitungen (ABGELEITET leer): werte.tsv, werte_quartier.tsv.gz und indikatoren.tsv
    unterscheiden sich nur um die hinzugefügten Zeilen der abgeleiteten Indikatoren; zwei Läufe sind byte-gleich."""
    dl, aus = ts_umgebung
    _normalisieren(dl)
    mit = {n: (aus / n).read_bytes() for n in ("werte.tsv", "werte_quartier.tsv.gz", "indikatoren.tsv")}
    strukturdaten.write()
    assert {n: (aus / n).read_bytes() for n in mit} == mit   # deterministisch
    monkeypatch.setattr(strukturdaten, "ABGELEITET", {})
    strukturdaten.write()
    ohne = {n: (aus / n).read_bytes() for n in mit}
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert "abgeleitet" not in meta and "abgeleitet" not in meta["formate"]["wert"]

    def zeilen(name, daten):
        text = gzip.decompress(daten) if name.endswith(".gz") else daten
        return text.decode("utf-8").splitlines(keepends=True)
    for name in mit:
        neu, alt = zeilen(name, mit[name]), zeilen(name, ohne[name])
        assert [z for z in neu if "koeln_abg_" not in z.split("\t", 3)[:3][-1] and not z.startswith("koeln_abg_")] \
            == alt, name
        assert len(neu) > len(alt), name


def test_altersgrenzen_geaendert_bricht_ab(ts_umgebung, mit_alter, monkeypatch):
    """Weichen die Altersgrenzen der Gruppen ab (hier 6 bis unter 16 statt 15), gilt die Formel nicht mehr: Abbruch
    statt eines falschen Anteils."""
    dl, aus = ts_umgebung
    spalten = [s.replace("A0291A - Einwohner*innen, 06 < 15 Jahre", "A0291A - Einwohner*innen, 06 < 16 Jahre")
               for s in ts.SPALTEN]
    monkeypatch.setattr(ts, "SPALTEN", spalten)
    with pytest.raises(ValueError, match="nicht lückenlos"):
        _normalisieren(dl)


def test_ohne_altersgruppen_keine_ableitung(ts_umgebung):
    """Testdaten ohne Altersgruppen (wie tests/test_strukturdaten.py): keine abgeleiteten Indikatoren, kein Eintrag in
    meta.json, Status nur ok, geheim, fehlt."""
    dl, aus = ts_umgebung
    pfade = ts.dateien_schreiben(dl)
    ts.protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    assert not [i for i in _lesen(aus / "indikatoren.tsv") if i["indikator_id"].startswith("koeln_abg_")]
    assert "abgeleitet" not in json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert {w["status"] for w in _lesen(aus / "werte.tsv")} <= {"ok", "geheim", "fehlt"}


def test_vertrag_im_repository_mit_ableitungen():
    """data/strukturdaten: die abgeleiteten Anteile stehen auf jeder Raumebene, nur mit status abgeleitet, geheim oder
    fehlt; jeder Wert hat 2 Nachkommastellen; Stadtteilwerte stimmen mit der Vergleichstabelle aus Phase 0 überein."""
    werte = [w for w in _lesen(VERTRAG / "werte.tsv") if w["indikator_id"].startswith("koeln_abg_")]
    assert {w["raumebene"] for w in werte} == {"gesamtstadt", "stadtbezirk", "stadtteil"}
    assert {w["status"] for w in werte} <= {"abgeleitet", "geheim", "fehlt"}
    assert all(re.fullmatch(r"\d{1,3}\.\d\d", w["wert"]) for w in werte if w["status"] == "abgeleitet")
    stadt = {(w["raum_id"], w["indikator_id"], w["jahr"]): w["wert"] for w in werte if w["raumebene"] == "stadtteil"}
    ids = {"unter_18": "koeln_abg_unter18", "ab_65": "koeln_abg_ab65"}
    n = 0
    with open(ROOT / "explore" / "strukturdaten" / "vergleich_zensus_stadtstatistik.tsv", encoding="utf-8") as fh:
        for z in csv.DictReader(fh, delimiter="\t"):
            if z["kennzahl"] in ids:
                assert Decimal(stadt[(z["nummer"], ids[z["kennzahl"]], z["stadt_jahr"])]) == Decimal(z["stadt_wert"])
                n += 1
    assert n >= 10


def test_schaetz_und_verfahrenswerte_im_metatext():
    """Prompt „Strukturdaten“ Abschnitt 2: Angaben zum Migrationshintergrund (Schätzwerte) und zu Haushalten
    (Verfahrenswerte, Haushaltegenerierung) sind im Metatext gekennzeichnet, Zuordnung nach dem Namen der Spalte;
    meta.json nennt die Kennungen. Übrige Metatexte ohne diesen Satz; Werte unverändert."""
    art = lambda name: [a for a, _ in strukturdaten.schaetz_verfahren(name)]  # noqa: E731
    assert art("Anteil Einpersonenhaushalte an allen Haushalten") == ["Verfahrenswert"]
    assert art("Haushalte") == ["Verfahrenswert"]
    assert art("Anteil Einwohner*innen mit Migrationshintergrund an allen Einwohner*innen") == ["Schätzwert"]
    assert art("Einwohner*innen, gesamt") == [] and art("Durchschnittsalter der Gesamtbevölkerung") == []
    ind = {i["indikator_id"]: i for i in _lesen(VERTRAG / "indikatoren.tsv")}
    meta = json.loads((VERTRAG / "meta.json").read_text(encoding="utf-8"))
    erwartet = {k: ("Schätzwert" if "Migrationshintergrund" in i["name"] else "Verfahrenswert") for k, i in ind.items()
                if k.startswith("koeln_") and re.search(r"Migrationshintergrund|haushalt", i["name"], re.I)}
    assert meta["schaetz_verfahrenswerte"]["indikatoren"] == erwartet
    assert {"koeln_A0153P", "koeln_A0157P", "koeln_A0267A", "koeln_A0273P", "koeln_A0275P", "koeln_A0269P"} <= set(erwartet)
    for k, i in ind.items():
        assert ("laut Datensatzbeschreibung des Statistischen Datenkatalogs" in i["metatext"]) == (k in erwartet), k
        if k in erwartet:
            assert i["metatext"].startswith(f"Statistischer Datenkatalog Köln, Spalte {k[6:]}; Werte unverändert "
                                            f"übernommen. {erwartet[k]}: ")


# --- (2) Freigabe und Texte --------------------------------------------------------------------------------------------

def test_freigabe_aus_als_vorgabe():
    assert config.ZUSATZTHEMEN["strukturdaten"] is False
    assert not strukturdaten_web.an()
    for datei in ("pipeline/config.py", "pipeline/strukturdaten_web.py", "pipeline/kontext.py", "pipeline/paket.py"):
        text = (ROOT / datei).read_text(encoding="utf-8")
        assert not re.search(r"environ[^\n]*(strukturdaten_an|FREIGABE|ZUSATZTHEMEN)", text, re.I), datei


def test_abschnitte_nach_freigabe():
    quelle = ("a\n<!-- nur-mit: strukturdaten -->\nmit\n<!-- ende -->\n<!-- nur-ohne: strukturdaten -->\nohne\n"
              "<!-- ende -->\nz\n")
    assert freigaben.text(quelle, {"strukturdaten": False}) == "a\nohne\nz\n"
    assert freigaben.text(quelle, {"strukturdaten": True}) == "a\nmit\nz\n"
    for fehler in ("<!-- nur-mit: unbekannt -->\nx\n<!-- ende -->\n", "<!-- nur-mit: strukturdaten -->\nx\n",
                   "x\n<!-- ende -->\n", "<!-- nur-mit: strukturdaten -->\n<!-- nur-ohne: strukturdaten -->\n",
                   "x <!-- nur-mit: strukturdaten -->\n"):
        with pytest.raises(ValueError):
            freigaben.text(fehler, {"strukturdaten": False})


def test_lizenzdatei_nach_freigabe():
    """data/LICENSE-DATA.md: ohne Freigabe ohne Markierungen und ohne die Angaben zur Auslieferung; mit Freigabe mit
    den abgeleiteten Anteilen, den Auszügen der Seite und anzeige.json, jeweils als Tabellenzeile mit vier Spalten."""
    aus = freigaben.datei(ROOT / "data" / "LICENSE-DATA.md", {**config.ZUSATZTHEMEN, "strukturdaten": False}).decode()
    an = freigaben.datei(ROOT / "data" / "LICENSE-DATA.md", {**config.ZUSATZTHEMEN, "strukturdaten": True}).decode()
    assert "<!--" not in aus and "<!--" not in an
    assert "koeln_abg_unter18" not in aus and "raumwerte" not in aus and "anzeige.json" not in aus
    assert "liegen bisher nur im Repository" in aus and "liegen bisher nur im Repository" not in an
    for erwartet in ("`koeln_abg_unter18`", "`strukturdaten/raumwerte/`", "`strukturdaten/anzeige.json`",
                     "ratsatlas-koeln/strukturdaten/", "Stadt Köln, Amt für Stadtentwicklung und Statistik"):
        assert erwartet in an, erwartet
    for z in an.splitlines():
        if z.startswith("| `"):
            assert len(z.strip().strip("|").split(" | ")) == 4, z


def test_begriffe_nur_mit_freigabe(monkeypatch):
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", False)
    g = glossar.glossar()
    assert "strukturdaten" not in g["gruppen"] and list(g["gruppen"].items()) == glossar.GRUPPEN
    assert not {"Statistisches Quartier", "Statistische Geheimhaltung", "Ökologischer Fehlschluss"} & {
        b["begriff"] for b in g["begriffe"]}
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
    g = glossar.glossar()
    neu = {b["begriff"]: b for b in g["begriffe"] if b["gruppe"] == "strukturdaten"}
    assert set(neu) == {"Statistisches Quartier", "Statistische Geheimhaltung", "Ökologischer Fehlschluss"}
    assert g["gruppen"]["strukturdaten"] == "Strukturdaten" and all(b["fundstelle"] for b in neu.values())
    text = " ".join(b["erklaerung"] for b in neu.values())
    assert not re.search(r"Problem|Brennpunkt|benachteiligt|schlecht|beste|Rang", text)
    # Entscheidung 10.11.2026 („nur zählen, ohne Formel“): kein Begriff nennt einen Rechenweg zu geheimen Werten
    assert not [s for s in ts._json_texte(g) if ts._nennt_rechenweg(s)]


def test_dcat_mit_strukturdaten(tmp_path, monkeypatch):
    """Datenpaket mit Freigabe: Teile des Datenkatalogs (dl-de/by mit Namensnennung), der Quartiersflächen und des
    Wegweisers (CC0); Lizenz der Datei bleibt die strengste. Ohne Freigabe kein Hinweis auf Strukturdaten."""
    def paket_dist(an):
        monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", an)
        publish.write_dcat(tmp_path / "dcat.jsonld", None, None)
        doc = json.loads((tmp_path / "dcat.jsonld").read_text(encoding="utf-8"))
        (d,) = [d for d in doc["dcat:distribution"] if d["dct:title"]["@value"] == "Datenpaket (Zip)"]
        return d
    d = paket_dist(False)
    assert "Strukturdaten" not in json.dumps(d, ensure_ascii=False)
    d = paket_dist(True)
    recht = d["dct:rights"]["rdfs:label"]
    assert d["dct:license"]["@id"] == publish.LICENCE["dl-de-by"]
    for teil in ("Statistischer Datenkatalog Köln (Strukturdaten): dl-de/by 2.0",
                 "Namensnennung: Stadt Köln, Amt für Stadtentwicklung und Statistik", "CC0 1.0",
                 "Bertelsmann Stiftung, wegweiser-kommune.de", "Statistische Quartiere Köln (Flächen): dl-de/zero 2.0"):
        assert teil in recht, teil
    assert "Strukturdaten" in d["dct:description"]["@value"]
    assert publish.lizenz_der_teile([("Wegweiser", "CC0 1.0")]) == "cc0"
    assert publish.lizenz_der_teile([("a", "CC0 1.0"), ("b", "dl-de/zero 2.0")]) == "dl-de-zero"


# --- (3) Auslieferung auf der Seite ------------------------------------------------------------------------------------

def _werte_zeilen(pfad):
    oeffnen = gzip.open if pfad.suffix == ".gz" else open
    with oeffnen(pfad, "rt", encoding="utf-8", newline="") as fh:
        return fh.read().splitlines(keepends=True)


def _pruefe_aufteilung(src, ziel):
    """Aufteilung gegen den Vertrag in `src`: raumwerte hintereinander = werte.tsv, karte = alle Zeilen der relativen
    Indikatoren je Ebene, Kopf überall wie werte.tsv, Kopien byte-gleich. Liefert anzeige.json."""
    kopf, *zeilen = _werte_zeilen(src / "werte.tsv")
    q_kopf, *q_zeilen = _werte_zeilen(src / "werte_quartier.tsv.gz")
    assert q_kopf == kopf
    for name in strukturdaten_web.KOPIEREN:
        assert (ziel / name).read_bytes() == (src / name).read_bytes(), name
    assert not (ziel / "werte.tsv").exists() and not list(ziel.rglob("audit_*.tsv"))
    assert not (ziel / "zurueckgestellt.tsv").exists()
    doc = json.loads((ziel / "anzeige.json").read_text(encoding="utf-8"))
    teile = []
    for ebene in strukturdaten_web.EBENEN_RAUMWERTE:
        ids = sorted((p.stem for p in (ziel / "raumwerte" / ebene).glob("*.tsv")), key=int)
        assert ids == doc["raumwerte"][ebene]
        for raum_id in ids:
            k, *t = _werte_zeilen(ziel / "raumwerte" / ebene / f"{raum_id}.tsv")
            assert k == kopf and {z.split("\t")[:2] == [ebene, raum_id] for z in t} == {True}
            teile += t
    assert teile == zeilen   # hintereinander gelesen genau werte.tsv (Bytes und Reihenfolge)
    typ = {i["indikator_id"]: i["typ"] for i in _lesen(src / "indikatoren.tsv")}
    relativ = {i for i, t in typ.items() if t in ("anteil", "quote", "dichte", "mittelwert")}
    for ebene in strukturdaten_web.EBENEN_KARTE:
        erwartet = [z for z in (q_zeilen if ebene == "quartier" else zeilen)
                    if z.split("\t")[0] == ebene and z.split("\t")[2] in relativ]
        gelesen = []
        for p in sorted((ziel / "karte" / ebene).glob("*.tsv")):
            assert typ[p.stem] in strukturdaten_web.TYPEN_KARTE, p   # nie anzahl oder kategorie
            k, *t = _werte_zeilen(p)
            assert k == kopf and {z.split("\t")[2] for z in t} == {p.stem} and t == [
                z for z in erwartet if z.split("\t")[2] == p.stem]   # Reihenfolge der Quelle
            gelesen += t
        assert sorted(gelesen) == sorted(erwartet), ebene
        assert sorted(p.stem for p in (ziel / "karte" / ebene).glob("*.tsv")) == doc["karte"]["dateien"][ebene]
    return doc, typ


def _anzeige_pruefen(doc, typ):
    """anzeige.json verweist nur auf vorhandene Indikatoren und enthält keine Werte."""
    kern = [i for t in doc["kern"]["themen"] for i in t["indikatoren"]]
    assert set(kern) <= set(typ) and len(kern) == len(set(kern))
    assert set(doc["karte"]["indikatoren"]) <= set(typ)
    assert all(typ[i] in strukturdaten_web.TYPEN_KARTE for i in doc["karte"]["indikatoren"])
    assert set(doc["vergleich"]["indikatoren"]) <= set(typ)
    assert all(k in typ and w in typ for k, w in doc["vergleich"]["gegenstueck"].items())
    assert doc["karte"]["vorgabe_ebene"] == "stadtteil" and "quartier" in doc["karte"]["ebenen"]

    def schluessel(x):
        if isinstance(x, dict):
            return set(x) | {s for v in x.values() for s in schluessel(v)}
        return {s for v in x for s in schluessel(v)} if isinstance(x, list) else set()
    assert not {"wert", "status", "quellobjekt"} & schluessel(doc)


def test_aufteilung_synthetisch(ts_umgebung, mit_alter, tmp_path, monkeypatch):
    dl, aus = ts_umgebung
    _normalisieren(dl)
    kern = tmp_path / "kern.tsv"
    ids = ["koeln_A0355A", "koeln_abg_unter18", "koeln_abg_ab65", "koeln_A0109P", "koeln_A0022S"]
    kern.write_text("indikator_id\tthema_anzeige\treihenfolge\tbegruendung\n" + "".join(
        f"{iid}\tTest\t{n}\t[Testdaten]\n" for n, iid in enumerate(ids, start=1)), encoding="utf-8")
    monkeypatch.setattr(strukturdaten_web, "KERN_ANZAHL", (5, 5))
    ziel = tmp_path / "_site" / strukturdaten_web.ORT
    stat = strukturdaten_web.ausliefern(ziel, aus, kern)
    doc, typ = _pruefe_aufteilung(aus, ziel)
    _anzeige_pruefen(doc, typ)
    assert doc["kern"]["themen"] == [{"thema": "Test", "indikatoren": ids}]
    assert doc["karte"]["indikatoren"][:4] == ["koeln_abg_unter18", "koeln_abg_ab65", "koeln_A0109P", "koeln_A0022S"]
    assert "koeln_A0355A" not in doc["karte"]["indikatoren"]   # Anzahl: nur im Panel
    dateien = [p for p in ziel.rglob("*") if p.is_file()]
    assert stat["dateien"] == len(dateien) and stat["bytes"] == sum(p.stat().st_size for p in dateien)
    assert stat["groesste"][1] == max(p.stat().st_size for p in dateien)
    erst = {p: p.read_bytes() for p in dateien}
    strukturdaten_web.ausliefern(ziel, aus, kern)
    assert {p: p.read_bytes() for p in ziel.rglob("*") if p.is_file()} == erst   # deterministisch


def test_nur_mit_veroeffentlichen(tmp_path, monkeypatch, kontext_export):
    """meta.json veroeffentlichen (Vertrag, „Datenstand und Freigabe“): ist es nicht true, liefern Seite, Datenpaket
    und kontext.json die Strukturdaten auch mit Freigabe nicht aus (ValueError), und ein vorhandenes Ziel bleibt."""
    kopie = tmp_path / "vertrag"
    kopie.mkdir()
    for name in ("meta.json", "indikatoren.tsv", "werte.tsv"):
        (kopie / name).write_bytes((VERTRAG / name).read_bytes())
    meta = json.loads((kopie / "meta.json").read_text(encoding="utf-8"))
    assert meta["veroeffentlichen"] is True
    for wert in (False, None, "true"):
        meta["veroeffentlichen"] = wert
        (kopie / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        ziel = tmp_path / "ziel"
        ziel.mkdir(exist_ok=True)
        (ziel / "vorher.txt").write_text("x")
        with pytest.raises(ValueError, match="veroeffentlichen"):
            strukturdaten_web.ausliefern(ziel, kopie)
        assert (ziel / "vorher.txt").exists()
        with pytest.raises(ValueError, match="veroeffentlichen"):
            strukturdaten_web.paketdateien(kopie)
        monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
        monkeypatch.setenv("STRUKTURDATEN_AUS", str(kopie))
        with pytest.raises(ValueError, match="veroeffentlichen"):
            kontext.stadtstatistik()
    assert strukturdaten_web.paketdateien(VERTRAG)   # der echte Vertrag: true


def test_kernauswahl_geprueft(tmp_path):
    zeilen = strukturdaten_web.kern(indikatoren={i["indikator_id"] for i in _lesen(VERTRAG / "indikatoren.tsv")})
    assert 15 <= len(zeilen) <= 20 and [z["reihenfolge"] for z in zeilen] == sorted(z["reihenfolge"] for z in zeilen)
    ids = [z["indikator_id"] for z in zeilen]
    assert {"koeln_A0355A", "koeln_abg_unter18", "koeln_abg_ab65"} <= set(ids)
    assert all(z["begruendung"].strip() and z["thema_anzeige"].strip() for z in zeilen)
    assert not re.search(r"Problem|Brennpunkt|sozial schwach|benachteiligt",
                         " ".join(z["begruendung"] + z["thema_anzeige"] for z in zeilen))
    kopf = "indikator_id\tthema_anzeige\treihenfolge\tbegruendung\n"
    for inhalt, fehler in ((kopf + "koeln_A0355A\tA\t1\tx\n", "erwartet 15 bis 20"),
                           (kopf + "".join(f"koeln_A0355A\tA\t{n}\tx\n" for n in range(16)), "doppelt"),
                           (kopf + "".join(f"koeln_X{n}\tA\t{n}\tx\n" for n in range(16)), "nicht in indikatoren"),
                           (kopf + "".join(f"koeln_X{n}\tA\t{n}\t\n" for n in range(16)), "unvollständig")):
        p = tmp_path / "kern.tsv"
        p.write_text(inhalt, encoding="utf-8")
        with pytest.raises(ValueError, match=fehler):
            strukturdaten_web.kern(p, indikatoren={"koeln_A0355A"})


def test_gegenstuecke_aus_phase0():
    """WW_GEGENSTUECK entspricht den Zuordnungen der Art „direkt“ aus Phase 0."""
    direkt = {}
    with open(ROOT / "explore" / "strukturdaten" / "wegweiser_vorschlag.tsv", encoding="utf-8") as fh:
        for z in csv.DictReader(fh, delimiter="\t"):
            if z["zuordnung_art"] == "direkt" and re.fullmatch(r"[A-Z]\d{4}[APS]", z["koeln_datensatz_spalte"]):
                direkt[f"koeln_{z['koeln_datensatz_spalte']}"] = f"ww_{z['wegweiser_friendly_url']}"
    assert strukturdaten_web.WW_GEGENSTUECK == direkt


def test_aufteilung_des_vertrags_im_repository(tmp_path):
    """Echter Datenvertrag: Aufteilung byte-gleich (wie oben), anzeige.json nur mit vorhandenen Kennungen, Umfang
    gemeldet und begrenzt (Branch deploy: keine Datei nahe 95 MB)."""
    ziel = tmp_path / "strukturdaten"
    stat = strukturdaten_web.ausliefern(ziel, VERTRAG)
    doc, typ = _pruefe_aufteilung(VERTRAG, ziel)
    _anzeige_pruefen(doc, typ)
    assert stat["raumwerte"] == {"gesamtstadt": 1, "stadtbezirk": 9, "stadtteil": 86}
    assert stat["karte"]["quartier"] == stat["karte"]["stadtteil"] >= 50
    assert stat["groesste"][1] < 5_000_000 and stat["bytes"] < 80_000_000
    assert doc["einwohner_indikator"] == "koeln_A0355A" and doc["vertrag_version"] == "1.1"
    # Namen und Eltern ohne Geometrie: genau die Properties aus raum/<ebene>.geojson
    for ebene, n in (("stadtbezirk", 9), ("stadtteil", 86)):
        geo = json.loads((VERTRAG / "raum" / f"{ebene}.geojson").read_text(encoding="utf-8"))
        props = sorted(([str(f["properties"]["raum_id"]), f["properties"]["name"], str(f["properties"]["eltern_id"] or "")]
                        for f in geo["features"]), key=lambda z: int(z[0]))
        assert doc["raeume"][ebene] == props and len(props) == n
    assert doc["raeume"]["spalten"] == ["raum_id", "name", "eltern_id"] and "quartier" not in doc["raeume"]
    assert "fehlt_abgeleitet" in doc["texte"]
    assert set(doc["vergleich"]["gegenstueck"]) <= {i for t in doc["kern"]["themen"] for i in t["indikatoren"]}
    # Entscheidung 10.11.2026 („nur zählen, ohne Formel“): die Texte für Panel und Karte nennen keinen Rechenweg zu
    # geheimen Werten (meta.json, indikatoren.tsv und site/ prüft test_strukturdaten.py)
    assert not [s for s in ts._json_texte(doc) if ts._nennt_rechenweg(s)]


# --- (4) Kennzahlen nach Option (b) ------------------------------------------------------------------------------------

@pytest.fixture
def kontext_export(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPORT", tmp_path / "export")
    monkeypatch.delenv("STRUKTURDATEN_AUS", raising=False)
    return tmp_path / "export" / config.STADT / kontext.OUT


def test_kontext_ohne_freigabe_unveraendert(kontext_export, monkeypatch, tmp_path):
    """Ohne Freigabe hängt kontext.json nicht vom Datenvertrag ab (byte-gleich mit und ohne data/strukturdaten) und
    nennt ihn nicht: Einwohner und Altersanteile aus dem Zensus wie zuvor."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", False)
    kontext.write()
    erst = kontext_export.read_bytes()
    monkeypatch.setenv("STRUKTURDATEN_AUS", str(tmp_path / "leer"))   # Vertrag fehlt
    kontext.write()
    assert kontext_export.read_bytes() == erst
    doc = json.loads(erst)
    assert "strukturdaten" not in erst.decode("utf-8") and "koeln_A0355A" not in erst.decode("utf-8")
    assert doc["meta"]["kennzahlen"]["einwohner"]["quelle"] == "zensus"
    assert doc["meta"]["hinweis"] == ("Einordnung, kein Urteil. Alle Werte sind auf Stadtteile und Stadtbezirke "
                                      "umgerechnet (abgeleitet).")
    assert kontext.pruefen(kontext_export) == []


def test_kontext_option_b(kontext_export, monkeypatch):
    """Mit Freigabe: Einwohner aus koeln_A0355A, Altersanteile aus den abgeleiteten Indikatoren, je Gebiet aus der
    eigenen Zeile des jüngsten Jahres mit Wert für ganz Köln; Quelle, Jahr, Lizenz und Kennzeichnung in meta; übrige
    Kennzahlen wie ohne Freigabe; Prüfung ohne Befund."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", False)
    kontext.write()
    ohne = json.loads(kontext_export.read_text(encoding="utf-8"))
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
    kontext.write()
    doc = json.loads(kontext_export.read_text(encoding="utf-8"))
    werte = {(w["raumebene"], w["raum_id"], w["indikator_id"], w["jahr"]): w for w in _lesen(VERTRAG / "werte.tsv")}
    jahr = max(j for (e, r, i, j), w in werte.items() if (e, r, i) == ("gesamtstadt", "0", "koeln_A0355A"))
    nummer = {f["properties"]["ortsteil_bez"]: str(f["properties"]["ortsteil"])
              for f in json.loads(config.ORTSTEILE.read_text(encoding="utf-8"))["features"]}
    for name, v in doc["ortsteile"].items():
        assert v["einwohner"] == int(werte[("stadtteil", nummer[name], "koeln_A0355A", jahr)]["wert"]), name
        w = werte[("stadtteil", nummer[name], "koeln_abg_unter18", jahr)]
        assert v["unter_18"] == (float(w["wert"]) if w["status"] == "abgeleitet" else None), name
        for k in ("miete", "bodenrichtwert", "hitze", "kitas", "haltestellen"):
            assert v.get(k) == ohne["ortsteile"][name].get(k), (name, k)
    assert doc["stadt"]["einwohner"] == int(werte[("gesamtstadt", "0", "koeln_A0355A", jahr)]["wert"])
    k = doc["meta"]["kennzahlen"]
    assert (k["einwohner"]["quelle"], k["einwohner"]["jahr"], k["einwohner"]["indikator_id"]) == (
        "strukturdaten", jahr, "koeln_A0355A")
    assert k["unter_18"]["abgeleitet"] is True and k["ab_65"]["indikator_id"] == "koeln_abg_ab65"
    assert "abgeleitet" in k["unter_18"]["methode"] and "koeln_A0025A" in k["unter_18"]["methode"]
    # Bezugsgröße im Wortlaut der Metatexte; kein Text von kontext.json nennt einen Rechenweg zu geheimen Werten
    # (Entscheidung 10.11.2026, „nur zählen, ohne Formel“)
    assert all(kontext.BEZUGSGROESSE in k[a]["methode"] for a in ("unter_18", "ab_65"))
    assert not [s for s in ts._json_texte(doc) if ts._nennt_rechenweg(s)]
    assert k["miete"]["quelle"] == "zensus" and "zensus" in doc["meta"]["quellen"]
    q = doc["meta"]["quellen"]["strukturdaten"]
    assert q["lizenz"].startswith("dl-de/by") and "Amt für Stadtentwicklung und Statistik" in q["lizenz"]
    assert q["stand"] == json.loads((VERTRAG / "meta.json").read_text(encoding="utf-8"))["datenstand"]
    assert "Stadtstatistik" in doc["meta"]["hinweis"]
    # Hinweise für app.js: Reihenfolge der Tabelle, Wortlaut aus kontext.py; Altersanteile mit fester Stelle
    nu = doc["meta"]["nicht_umgerechnet"]
    assert nu["kennzahlen"] == ["einwohner", "unter_18", "ab_65"] and nu["liste"] == kontext.NICHT_UMGERECHNET["liste"]
    assert k["unter_18"]["stellen"] == k["ab_65"]["stellen"] == 1 and "stellen" not in k["einwohner"]
    assert "(" not in k["unter_18"]["ohne_wert"]   # Steckbrief und Gebietsseite setzen die Klammer selbst
    assert "nicht_umgerechnet" not in ohne["meta"] and "stellen" not in ohne["meta"]["kennzahlen"]["unter_18"]
    assert kontext.pruefen(kontext_export) == []


def test_kontext_mindestgroesse_nach_einwohnern_der_stadt(kontext_export, monkeypatch):
    """Die Mindestgröße gilt mit Freigabe für die angezeigte Einwohnerzahl (Hauptwohnsitz): Gebiete darunter ohne
    Anteile, die Prüfung bleibt ohne Befund."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
    monkeypatch.setattr(kontext, "MIN_EINWOHNER", 2000)
    kontext.write()
    doc = json.loads(kontext_export.read_text(encoding="utf-8"))
    klein = [n for n, v in doc["ortsteile"].items() if v["einwohner"] < 2000]
    assert klein and all(not kontext.ANTEILE & set(doc["ortsteile"][n]) for n in klein)
    assert all("unter_18" in v for v in doc["ortsteile"].values() if v["einwohner"] >= 2000)
    assert kontext.pruefen(kontext_export) == []
    # eine veränderte Zahl fällt auf
    doc["ortsteile"][next(n for n in doc["ortsteile"] if n not in klein)]["einwohner"] += 1
    kontext_export.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert [b for b in kontext.pruefen(kontext_export) if "laut Datenvertrag" in b]


def test_kontext_mit_freigabe_ohne_vertrag_bricht_ab(kontext_export, monkeypatch, tmp_path):
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
    monkeypatch.setenv("STRUKTURDATEN_AUS", str(tmp_path / "leer"))
    with pytest.raises((OSError, ValueError)):
        kontext.write()


# --- (5) Seite und Datenpaket ohne und mit Freigabe ----------------------------------------------------------------------

def _seite_bauen():
    spec = importlib.util.spec_from_file_location("seite_bauen", ROOT / "tools" / "seite_bauen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seite_und_paket_ohne_und_mit_freigabe(oparl, tmp_path, monkeypatch):
    """Ohne Freigabe: kein Ordner data/strukturdaten auf der Seite, keine Dateien unter strukturdaten/ im Paket,
    LIESMICH und index.json ohne Strukturdaten, LICENSE-DATA.md ohne Markierungen. Mit Freigabe: Aufteilung auf der
    Seite, alle Vertragsdateien unverändert im Paket, LIESMICH und LICENSE-DATA.md mit Lizenz und Namensnennung."""
    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", False)
    sessionnet.fetch_all()
    build.build()
    export.export()
    kontext.write()
    ebenen.write()
    zip_aus = paket.write()
    site = tmp_path / "_site"
    _seite_bauen().main(site)
    assert not (site / "data" / "strukturdaten").exists()
    assert not [p for p in site.rglob("*") if "koeln_abg_" in p.name or p.name == "anzeige.json"]
    idx = json.loads((site / "data" / "export" / config.STADT / "index.json").read_text(encoding="utf-8"))
    assert "strukturdaten" not in idx["meta"]["funktionen"]
    lizenz = (site / "data" / "LICENSE-DATA.md").read_bytes()
    assert lizenz == freigaben.datei(ROOT / "data" / "LICENSE-DATA.md") and b"<!--" not in lizenz
    with zipfile.ZipFile(zip_aus) as z:
        namen = z.namelist()
        assert not [n for n in namen if "/strukturdaten/" in n]
        assert z.read(f"{paket.ORDNER}/LIESMICH.txt").decode("utf-8") == paket.LIESMICH
        assert z.read(f"{paket.ORDNER}/LICENSE-DATA.md") == lizenz
    for seite in ("begriffe/index.html", "datenschutz.html", "index.html"):
        html = (site / seite).read_text(encoding="utf-8")
        assert "Statistisches Quartier" not in html and "Ökologischer Fehlschluss" not in html, seite
    gebiet = (site / "stadtbezirk" / "innenstadt" / "index.html").read_text(encoding="utf-8")
    assert "Alle Werte sind auf Stadtteile und Stadtbezirke umgerechnet" in gebiet and "Stadtstatistik" not in gebiet
    assert "Rechnet Kennzahlen je Stadtteil aus Zensus" in (site / "technik" / "index.html").read_text(encoding="utf-8")

    monkeypatch.setitem(config.ZUSATZTHEMEN, "strukturdaten", True)
    export.export()
    kontext.write()
    zip_an = paket.write()
    site_an = tmp_path / "_site_an"
    _seite_bauen().main(site_an)
    ziel = site_an / strukturdaten_web.ORT
    assert (ziel / "anzeige.json").is_file() and (ziel / "raumwerte" / "stadtteil" / "101.tsv").is_file()
    assert (ziel / "karte" / "quartier" / "koeln_abg_unter18.tsv").is_file()
    assert not list(ziel.rglob("audit_*.tsv"))
    idx = json.loads((site_an / "data" / "export" / config.STADT / "index.json").read_text(encoding="utf-8"))
    assert idx["meta"]["funktionen"]["strukturdaten"] is True
    assert "Statistisches Quartier" in (site_an / "begriffe" / "index.html").read_text(encoding="utf-8")
    gebiet = (site_an / "stadtbezirk" / "innenstadt" / "index.html").read_text(encoding="utf-8")
    assert "Werte der Kölner Stadtstatistik je Gebiet" in gebiet and "Alle Werte sind" not in gebiet
    assert "Statistischer Datenkatalog Köln" in gebiet   # Quelle der Kennzahlen mit Lizenz
    technik = (site_an / "technik" / "index.html").read_text(encoding="utf-8")
    assert "Einwohnerzahl und Altersanteile aus der Kölner Stadtstatistik" in technik
    with zipfile.ZipFile(zip_an) as z:
        im_paket = {n.split("/strukturdaten/", 1)[1]: z.read(n) for n in z.namelist() if "/strukturdaten/" in n}
        liesmich = z.read(f"{paket.ORDNER}/LIESMICH.txt").decode("utf-8")
        lizenz_an = z.read(f"{paket.ORDNER}/LICENSE-DATA.md").decode("utf-8")
    assert im_paket == {p.relative_to(VERTRAG).as_posix(): p.read_bytes() for p in VERTRAG.rglob("*") if p.is_file()}
    assert "raumwerte" not in " ".join(im_paket) and "anzeige.json" not in im_paket
    assert "strukturdaten/" in liesmich and "dl-de/by 2.0" in liesmich and "CC0 1.0" in liesmich
    assert "Stadt Köln, Amt für Stadtentwicklung und Statistik" in liesmich
    assert "`koeln_abg_unter18`" in lizenz_an and "<!--" not in lizenz_an
