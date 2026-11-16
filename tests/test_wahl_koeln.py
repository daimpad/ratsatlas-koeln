"""Wahlbeteiligung je Stadtteil (pipeline/wahl_koeln.py, tools/wahlbeteiligung.py, kontext.wahlbeteiligung_koeln) mit
erfundenen Zahlen: Dateien in den Formaten, die der Adapter liest, Abgleich mit den 86 Stadtteilen in data/geo,
Positivliste der Spalten (nie Ergebnisse der Parteien), Schreiben nur mit klarer Lizenz, Freigabe „wahlbeteiligung“
(aus: kontext.json unverändert). Keine Daten der Stadt, kein Netz."""
import csv
import importlib.util
import json
import re
import shutil
from pathlib import Path

import openpyxl
import pytest

from pipeline import config, kontext, wahl_koeln

ROOT = Path(__file__).resolve().parents[1]
GEB = wahl_koeln.gebiete()
PARTEIEN = ("SPD", "CDU", "GRÜNE")   # Spalten, die nie gelesen werden dürfen
NENNUNG = "Datenquelle: Stadt Köln – Amt für Stadtentwicklung und Statistik (Testdaten)"


def _tool():
    spec = importlib.util.spec_from_file_location("wahlbeteiligung", ROOT / "tools" / "wahlbeteiligung.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _zahlen(k):
    """Erfundene Wahlberechtigte und Wähler für den k-ten Stadtteil (ganze Zahlen, Beteiligung 30–79 %)."""
    a = 2000 + 37 * k
    return a, a * (30 + k % 50) // 100


def _blatt_amt(ws, titel, zahl=_zahlen):
    """Ein Blatt im Aufbau des Amts: Titel, Block Stadt, Block Kommunalwahlbezirk, Block Stadtteil, mit Parteien."""
    kopf = ["Wahlberechtigte", "Wähler -/innen", None, "Wahlbeteiligung"] + [p for p in PARTEIEN for p in (p, None)]
    einheiten = ["abs", "abs", "%", "%"] + ["abs", "%"] * len(PARTEIEN)
    ws.append([titel])
    ws.append([])
    ws.append(["Stadt Köln", None] + kopf)
    ws.append(["Schlüssel", "Name"] + einheiten)
    ws.append(["05315000", "Köln", 999999, 1, 0.1, 0.1, 1, 1, 1, 1, 1, 1])
    ws.append([])
    ws.append(["Kommunalwahlbezirk", None] + kopf)
    ws.append(["Schlüssel", "Name"] + einheiten)
    ws.append(["01", "Innenstadt 1", 5000, 2500, 50.0, 50.0, 900, 36.0, 800, 32.0, 700, 28.0])
    ws.append([])
    ws.append(["Stadtteil", None] + kopf)
    ws.append(["Schlüssel", "Name"] + einheiten)
    for k, (i, (name, _)) in enumerate(sorted(GEB.items())):
        a, w = zahl(k)
        ws.append([str(i), name, a, w, 100 * w / a, 100 * w / a, w // 3, 33.3, w // 3, 33.3, w - 2 * (w // 3), 33.4])
    ws.append([])
    ws.append(["Quelle: erfundene Testdaten"])


@pytest.fixture
def xlsx(tmp_path):
    pfad = tmp_path / "anhang.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Impressum"
    wb.active.append(["Erfundene Testdaten für den Ratsatlas Köln"])
    _blatt_amt(wb.create_sheet("Ratswahl"), "Kommunalwahl 2025 – Ratswahl (Testdaten)")
    _blatt_amt(wb.create_sheet("OB"), "Kommunalwahl 2025 – Wahl der Oberbürgermeisterin/des Oberbürgermeisters")
    wb.save(pfad)
    return pfad


def test_aufbau_des_amts_nur_positivliste(xlsx, tmp_path):
    gelesen = wahl_koeln.lesen(xlsx)
    assert (gelesen["format"], gelesen["blatt"]) == ("amt", "Ratswahl")   # das Blatt der OB-Wahl ist verworfen
    assert gelesen["spalten"] == {"beteiligung": "Wahlbeteiligung", "waehler": "Wähler -/innen",
                                  "wahlberechtigte": "Wahlberechtigte"}
    assert len(gelesen["zeilen"]) == 86   # nur der Block „Stadtteil“
    assert {k for z in gelesen["zeilen"] for k in z} == {"schluessel", "name", "wahlberechtigte", "waehler", "beteiligung"}
    zeilen = wahl_koeln.ableiten(gelesen)
    assert [z["stadtteil_id"] for z in zeilen] == sorted(GEB)
    for k, z in enumerate(zeilen):
        a, w = _zahlen(k)
        assert (z["stadtteil"], z["wahlberechtigte"], z["waehler"]) == (GEB[z["stadtteil_id"]][0], a, w)
        assert z["beteiligung_prozent"] == round(100 * w / a, 1)

    stand = tmp_path / "STAND.json"
    stand.write_text(json.dumps({"zensus": {"lizenz": "x"}}), encoding="utf-8")
    tsv, _ = wahl_koeln.schreiben(gelesen, zeilen, url="https://example.invalid/anhang.xlsx", titel="Testdaten",
                                  lizenz="dl-de/by-2.0", namensnennung=NENNUNG, abgerufen="2026-11-16",
                                  tsv=tmp_path / "w.tsv", stand=stand)
    text = tsv.read_text(encoding="utf-8")
    assert text.splitlines()[0].split("\t") == list(wahl_koeln.SPALTEN) and len(text.splitlines()) == 87
    eintrag = json.loads(stand.read_text(encoding="utf-8"))
    assert set(eintrag) == {"zensus", "wahl2025"}   # andere Quellen bleiben
    w = eintrag["wahl2025"]
    assert w["lizenz"] == f"dl-de/by-2.0, {NENNUNG}" and w["stand"] == "2025-09-14" and w["stadtteile"] == 86
    assert w["wahlberechtigte"] == sum(_zahlen(k)[0] for k in range(86))
    for p in PARTEIEN:   # keine Ergebnisse der Parteien, weder in der Tabelle noch im Vermerk
        assert p not in text and p not in json.dumps(eintrag, ensure_ascii=False)


def test_pruefung_der_wahl_und_umgerechnete_werte(tmp_path):
    """Die Strukturdaten der Stadt enthalten Blätter früherer Wahlen (Kommunalwahl 2020 auf den neuen Zuschnitt
    umgerechnet, nicht ganzzahlig): Sie passen nicht, auch nicht mit abgeschalteter Prüfung der Wahl."""
    pfad = tmp_path / "strukturdaten.xlsx"
    wb = openpyxl.Workbook()
    _blatt_amt(wb.active, "Kommunalwahl 2020", zahl=lambda k: (1000.4 + k, 500.2 + k))
    wb.active.title = "Kommunalwahl 2020"
    _blatt_amt(wb.create_sheet("Europawahl 2024"), "Ergebnisse Europawahl 2024")
    wb.save(pfad)
    with pytest.raises(ValueError, match="keine Tabelle der Ratswahl 2025.*Kommunalwahl 2020.*Europawahl 2024"):
        wahl_koeln.lesen(pfad)
    with pytest.raises(ValueError, match="mehrere Tabellen passen"):
        wahl_koeln.lesen(pfad, wahl_pruefen=False)
    gelesen = wahl_koeln.lesen(pfad, "Kommunalwahl 2020", wahl_pruefen=False)
    with pytest.raises(ValueError, match="nicht ganzzahlig"):
        wahl_koeln.ableiten(gelesen)


def _csv(pfad, kopf, zeilen, trenner=";"):
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter=trenner)
        wr.writerow(kopf)
        wr.writerows(zeilen)
    return pfad


def test_votemanager_csv(tmp_path):
    """Open-Data-CSV des votemanagers (Feldnamen laut Feldbeschreibung der Stadt Köln 2020): nur gebiet-nr,
    gebiet-name, A und B; die Stimmen (D1, D2) und eine Summenzeile mit Gemeindeschlüssel bleiben außen vor."""
    kopf = ["datum", "wahl", "ags", "gebiet-nr", "gebiet-name", "A1", "A2", "A3", "A", "B", "B1", "C", "D", "D1", "D2"]
    zeilen = [["14.09.2025", "Ratswahl", "05315000", "05315000", "Köln", 1, 1, 1, 999999, 1, 1, 0, 1, 1, 0]]
    for k, (i, (name, _)) in enumerate(sorted(GEB.items())):
        a, w = _zahlen(k)
        zeilen.append(["14.09.2025", "Ratswahl", "05315000", str(i), name, a, 0, 0, a, w, w // 2, 0, w, w // 2, w - w // 2])
    gelesen = wahl_koeln.lesen(_csv(tmp_path / "Open-Data-Ratswahl.csv", kopf, zeilen))
    assert gelesen["format"] == "votemanager" and gelesen["summenzeilen"] == 1
    assert gelesen["spalten"] == {"waehler": "B", "wahlberechtigte": "A"}
    assert "Ratswahl" in gelesen["kennung"] and "14.09.2025" in gelesen["kennung"]
    zeilen_aus = wahl_koeln.ableiten(gelesen)
    assert [(z["wahlberechtigte"], z["waehler"]) for z in zeilen_aus] == [_zahlen(k) for k in range(86)]
    # eine andere Wahl in derselben Form wird verworfen
    for z in zeilen:
        z[1] = "Oberbürgermeisterwahl"
    with pytest.raises(ValueError, match="Prüfung der Wahl"):
        wahl_koeln.lesen(_csv(tmp_path / "Open-Data-OB.csv", kopf, zeilen))


def test_nur_wahlbeteiligung_in_prozent(tmp_path):
    """Tabelle mit einer Kopfzeile, Schlüssel und Name, Wahlberechtigte und Wahlbeteiligung in %: Wähler abgeleitet."""
    zeilen = []
    for k, (i, (name, _)) in enumerate(sorted(GEB.items())):
        a, w = _zahlen(k)
        zeilen.append([str(i), name, f"{a:,}".replace(",", "."), f"{100 * w / a:.1f}".replace(".", ",")])
    pfad = _csv(tmp_path / "Ratswahl_2025_Stadtteile.csv", ["Stadtteil-Nr.", "Stadtteil", "Wahlberechtigte",
                                                             "Wahlbeteiligung in %"], zeilen)
    gelesen = wahl_koeln.lesen(pfad)
    assert gelesen["format"] == "tabelle"
    zeilen_aus = wahl_koeln.ableiten(gelesen)
    assert wahl_koeln.zusammenfassung(gelesen, zeilen_aus)["waehler_aus"].startswith("Wahlbeteiligung")
    for k, z in enumerate(zeilen_aus):
        a, w = _zahlen(k)
        assert z["wahlberechtigte"] == a and abs(z["waehler"] - w) <= a * 0.0005 + 1


def test_abgleich_meldet_alle_abweichungen(xlsx):
    gelesen = wahl_koeln.lesen(xlsx)
    z = gelesen["zeilen"]
    z[1] = dict(z[1], name="Neustadt-Süd erfunden")    # Name passt nicht zur Nummer
    z.append(dict(z[2]))                                # doppelt
    z.append(dict(z[3], schluessel="999"))              # unbekannte Nummer
    del z[0]                                            # fehlt
    with pytest.raises(ValueError) as e:
        wahl_koeln.ableiten(gelesen)
    text = str(e.value)
    for teil in ("Neustadt-Süd erfunden", "doppelt", "Schlüssel 999", "ohne Zeile: 101 Altstadt/Süd"):
        assert teil in text
    gelesen = wahl_koeln.lesen(xlsx)
    gelesen["zeilen"][5]["waehler"] = gelesen["zeilen"][5]["wahlberechtigte"] + 1
    with pytest.raises(ValueError, match="mehr Wähler als Wahlberechtigte"):
        wahl_koeln.ableiten(gelesen)


@pytest.mark.parametrize("lizenz,nennung", [("", ""), ("CC BY 3.0 DE", NENNUNG), ("dl-de/by-2.0", " ")])
def test_schreiben_nur_mit_klarer_lizenz(xlsx, tmp_path, lizenz, nennung, capsys):
    gelesen = wahl_koeln.lesen(xlsx)
    zeilen = wahl_koeln.ableiten(gelesen)
    tsv, stand = tmp_path / "w.tsv", tmp_path / "STAND.json"
    with pytest.raises(ValueError, match="nichts geschrieben"):
        wahl_koeln.schreiben(gelesen, zeilen, url="https://example.invalid/x.xlsx", titel="T", lizenz=lizenz,
                             namensnennung=nennung, abgerufen="2026-11-16", tsv=tsv, stand=stand)
    args = ["--datei", str(xlsx), "--schreiben", "--lizenz", lizenz, "--namensnennung", nennung, "--url",
            "https://example.invalid/x.xlsx", "--abgerufen", "2026-11-16", "--tsv", str(tsv), "--stand", str(stand)]
    assert _tool().main(args) == 2
    assert not tsv.exists() and not stand.exists()
    # nur prüfen: keine Werte einzelner Stadtteile in der Ausgabe
    assert _tool().main(["--datei", str(xlsx)]) == 0
    aus = re.sub(r"sha256 [0-9a-f]+", "", capsys.readouterr().out)
    assert "86 Stadtteile wie data/geo" in aus and "nichts geschrieben" in aus
    assert str(_zahlen(0)[0]) not in aus and "Altstadt/Süd" not in aus


# --- Kontextdaten ---------------------------------------------------------------------------------------------------

@pytest.fixture
def wahldaten(xlsx, tmp_path, monkeypatch):
    """Erfundene Werte in data/kontext-Form (TSV und STAND.json) in tmp_path; Export nach tmp_path/export."""
    stand = tmp_path / "STAND.json"
    shutil.copy(kontext.STAND, stand)
    gelesen = wahl_koeln.lesen(xlsx)
    wahl_koeln.schreiben(gelesen, wahl_koeln.ableiten(gelesen), url="https://example.invalid/anhang.xlsx",
                         titel="Testdaten", lizenz="dl-de/by-2.0", namensnennung=NENNUNG, abgerufen="2026-11-16",
                         tsv=tmp_path / "wahl2025_stadtteile.tsv", stand=stand)
    monkeypatch.setattr(config, "EXPORT", tmp_path / "export")
    return tmp_path / "wahl2025_stadtteile.tsv", stand


def _kontext_json():
    kontext.write()
    return (config.EXPORT / config.STADT / kontext.OUT).read_bytes()


def test_kontext_ohne_freigabe_unveraendert(wahldaten, monkeypatch):
    """Ohne Freigabe „wahlbeteiligung“ ist kontext.json byte-gleich, ob die Wahldaten vorliegen oder nicht: keine
    Kennzahl, keine Quelle „wahl2025“, kein Audit."""
    assert config.ZUSATZTHEMEN["wahlbeteiligung"] is False
    vorher = _kontext_json()
    tsv, stand = wahldaten
    monkeypatch.setattr(kontext, "WAHL_STADTTEILE", tsv)
    monkeypatch.setattr(kontext, "STAND", stand)
    assert _kontext_json() == vorher
    doc = json.loads(vorher)
    assert "wahlbeteiligung" not in doc["meta"]["kennzahlen"] and "wahl2025" not in doc["meta"]["quellen"]
    assert not (config.EXPORT / kontext.AUDIT_WAHL).exists()


def test_kontext_mit_freigabe(wahldaten, monkeypatch):
    tsv, stand = wahldaten
    monkeypatch.setattr(kontext, "WAHL_STADTTEILE", tsv)
    monkeypatch.setattr(kontext, "STAND", stand)
    monkeypatch.setitem(config.ZUSATZTHEMEN, "wahlbeteiligung", True)
    doc = json.loads(_kontext_json())
    with open(tsv, encoding="utf-8") as f:
        werte = {r["stadtteil"]: (int(r["wahlberechtigte"]), int(r["waehler"])) for r in csv.DictReader(f, delimiter="\t")}
    for name, (a, w) in werte.items():
        if doc["ortsteile"][name]["einwohner"] >= kontext.MIN_EINWOHNER:
            assert doc["ortsteile"][name]["wahlbeteiligung"] == round(100 * w / a, 1)   # amtlich: eine Nachkommastelle
    bezirk = doc["stadtbezirk_je_ortsteil"]
    for b, v in doc["bezirke"].items():
        a = sum(x[0] for n, x in werte.items() if bezirk[n] == b)
        w = sum(x[1] for n, x in werte.items() if bezirk[n] == b)
        assert v["wahlbeteiligung"] == round(100 * w / a, 1)
    a, w = map(sum, zip(*werte.values()))
    assert doc["stadt"]["wahlbeteiligung"] == round(100 * w / a, 1)
    k = doc["meta"]["kennzahlen"]["wahlbeteiligung"]
    assert k["titel"] == "Wahlbeteiligung Ratswahl 2025" and k["amtlich"] is True and "ohne_wert" not in k
    assert "geschätzt" not in k["methode"] and "wahlbeteiligung" in doc["meta"]["reihenfolge"]
    assert doc["meta"]["quellen"]["wahl2025"]["lizenz"] == f"dl-de/by-2.0, {NENNUNG}"
    audit = (config.EXPORT / kontext.AUDIT_WAHL).read_text(encoding="utf-8").splitlines()
    assert audit[0].split("\t") == kontext.AUDIT_WAHL_KOPF["amtlich"] and len(audit) == 87
    assert kontext.pruefen() == []
    # unklare Lizenz im Ergebnis: Befund
    pfad = config.EXPORT / config.STADT / kontext.OUT
    doc["meta"]["quellen"]["wahl2025"]["lizenz"] = "Nutzungsbedingungen des Statistik-Atlas"
    pfad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert any("Lizenz" in b and "nicht klar" in b for b in kontext.pruefen())


def test_kontext_positivliste_der_spalten(wahldaten, monkeypatch):
    """Eine Spalte außerhalb von wahl_koeln.SPALTEN (etwa Stimmen einer Partei) bricht ab."""
    tsv, stand = wahldaten
    zeilen = tsv.read_text(encoding="utf-8").splitlines()
    tsv.write_text("\n".join([zeilen[0] + "\tSPD"] + [z + "\t1" for z in zeilen[1:]]) + "\n", encoding="utf-8")
    monkeypatch.setattr(kontext, "WAHL_STADTTEILE", tsv)
    monkeypatch.setitem(config.ZUSATZTHEMEN, "wahlbeteiligung", True)
    with pytest.raises(ValueError, match="erlaubt nur"):
        kontext.wahlbeteiligung_koeln()


def test_freigabe_aus_und_stand_passend():
    """Im Repository: Freigabe aus; die Tabelle liegt genau dann vor, wenn STAND.json die Quelle nennt."""
    assert config.ZUSATZTHEMEN["wahlbeteiligung"] is False
    stand = json.loads(kontext.STAND.read_text(encoding="utf-8"))
    assert kontext.WAHL_STADTTEILE.exists() == ("wahl2025" in stand)


def test_texte_fuer_leser():
    """Titel und Methode der amtlichen Kennzahl wie die übrigen (tests/test_gebietsseiten.py): keine internen Feldnamen,
    „Stadtteile“ statt „Ortsteile“, kein „geschätzt“."""
    titel, einheit, quelle, methode = kontext.KENNZAHL_WAHL_AMTLICH
    assert (einheit, quelle) == ("%", wahl_koeln.STAND_SCHLUESSEL)
    for text in (titel, methode):
        assert not re.search(r"[a-z]_[a-z]", text) and not re.search("ortsteil|geschätzt", text, re.I), text
