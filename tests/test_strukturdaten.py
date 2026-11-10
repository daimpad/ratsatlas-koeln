"""Strukturdaten (pipeline/strukturdaten.py): Normalisierung in den Datenvertrag „Strukturdaten v1“ und Abruf.

Alle Eingaben sind erfunden: eine XLSX-Datei mit dem Aufbau des Statistischen Datenkatalogs Köln (Blätter Info, Daten,
Quellen, Katalog) und ein Wegweiser-Export im Format der echten CSV, mit ausgedachten Zahlen. Der Abruf läuft nur gegen
einen lokalen Testserver (127.0.0.1); Adressen der Stadt werden vor dem Senden abgewiesen."""
import csv
import hashlib
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

openpyxl = pytest.importorskip("openpyxl")

from pipeline import abruf, config, strukturdaten  # noqa: E402

GEHEIM = "Werte zwischen 1 und 4 und zugehörige Anteilswerte werden nicht veröffentlicht (*). [Testdaten]"
SPALTEN = ["A0025A - Einwohner*innen, gesamt", "A0355A - Einwohner*innen, mit Hauptwohnsitz",
           "A0359A - Einwohner*innen, mit Nebenwohnsitz", "A0109A - Einwohner, männlich",
           "A0109P - Anteil männlicher Einwohner an allen Einwohnern",
           "A0022S - Durchschnittsalter der Gesamtbevölkerung",
           "A0008S - Einwohner*innenentwicklung (zum Vorjahr)", "Z9999A - Neue Spalte ohne Klassifikation"]
RAEUME = [("0 / Stadt Köln", "Gesamtstadt"), ("1 / Innenstadt", "Stadtbezirke"), ("2 / Rodenkirchen", "Stadtbezirke"),
          ("10001 / Testsozialraum", "Sozialräume"), ("101 / Teststadtteil A", "Stadtteile"),
          ("102 / Teststadtteil B", "Stadtteile"), ("201 / Teststadtteil C", "Stadtteile"),
          ("101010001 / Testquartier", "Statistische Quartiere")]

WW_LISTE = [
    ("bevoelkerung", "Bevölkerung", "Anzahl", "Statistische Ämter der Länder"),
    ("bevoelkerungsentwicklung-ueber-die-letzten-5-jahre", "Bevölkerungsentwicklung über die letzten 5 Jahre", "%",
     "Statistische Ämter der Länder, ZEFIR, eigene Berechnungen"),
    ("durchschnittsalter", "Durchschnittsalter", "Jahre", "Statistische Ämter der Länder, ZEFIR, eigene Berechnungen"),
    ("jugendquotient", "Jugendquotient", "unter 20-Jährige je 100 Pers. der AG 20-64", "Testdatenhalter"),
    ("altenquotient", "Altenquotient", "ab 65-Jährige je 100 Pers. der AG 20-64", "Testdatenhalter"),
    ("sgb-ii-quote", "SGB II-Quote", "%", "Testdatenhalter"),
    ("arbeitslose-an-den-svb", "Arbeitslose an den SvB", "%", "Testdatenhalter"),
    ("beschaeftigungsquote", "Beschäftigungsquote", "%", "Testdatenhalter"),
    ("auslaenderanteil", "Anteil Ausländer:innen", "%", "Testdatenhalter"),
    ("wohnflaeche-pro-person", "Wohnfläche pro Person", "m²", "Testdatenhalter"),
]


def _werte(raum, jahr):
    """Erfundene Werte einer Zeile; Gesamt = Haupt + Neben, Anteil = 100 × Männer / Gesamt (6 Stellen)."""
    nummer = int(raum.split(" / ")[0]) % 1000
    haupt, neben = 1000 + 37 * nummer + jahr % 10, 11 + nummer % 7
    gesamt = haupt + neben
    maenner = gesamt // 2 + nummer % 5
    return [gesamt, haupt, neben, maenner, round(100 * maenner / gesamt, 6), 40.5 + nummer / 1000, 3, 7]


def xlsx_bauen(pfad, aendern=None):
    mappe = openpyxl.Workbook()
    info = mappe.active
    info.title = "Info"
    for text in ("#VALUE!", "Statistischer Datenkatalog Köln [Testdaten]", "Auswertung erstellt am", "15.10.2026",
                 "Geheimhaltung", GEHEIM, "Kontakt", "test@example.invalid"):
        info.append([text])
    daten = mappe.create_sheet("Daten")
    daten.append(["Jahr", "Raum", "Raumebene", *SPALTEN])
    for jahr in (2025, 2024):
        for raum, ebene in RAEUME:
            daten.append([str(jahr), raum, ebene, *_werte(raum, jahr)])
    # Zeilen: 2–9 Jahr 2025, 10–17 Jahr 2024, je in der Reihenfolge von RAEUME (0, 1, 2, 10001, 101, 102, 201, Quartier)
    # Sonderfälle: geheim („*“), leer (leere Zeichenkette und fehlende Zelle), Gleitkommazahlen
    daten["G6"], daten["H6"] = "*", "*"                # 101 / 2025: Männer und Anteil geheim
    daten["I9"] = ""                                    # Quartier 2025 (nicht übernommen)
    daten["I16"] = ""                                   # 201 / 2024: leere Zeichenkette
    daten["F16"] = None                                 # 201 / 2024: fehlende Zelle
    daten["I2"] = 0.1234567890123456                    # Gesamtstadt 2025: 16 Stellen (openpyxl schreibt %.16g)
    daten["I3"] = 1e-05                                 # Bezirk 1 / 2025: ohne Exponent schreiben
    if aendern:
        aendern(daten)
    quellen = mappe.create_sheet("Quellen")
    quellen.append(["Indikator", "Quellenangabe", "Anmerkung"])
    for s in SPALTEN:
        quellen.append([s, "Stadt Köln - Testamt (eigene Berechnung)",
                        "Testanmerkung zur Berechnung." if s.startswith("A0022S") else None])
    katalog = mappe.create_sheet("Katalog")
    katalog.append(["Indikator", None, None, None, "Formate", None, None, "Verfügbarkeit"])
    katalog.append(["THEMA", "UNTERTHEMA", "ID", "Name", "abs", "%", "andere", *range(2010, 2026)])
    for kennung, name, formate in (("A0025", "Einwohner*innen, gesamt", "X//"),
                                   ("A0355", "Einwohner*innen, mit Hauptwohnsitz", "X//"),
                                   ("A0359", "Einwohner*innen, mit Nebenwohnsitz", "X//"),
                                   ("A0109", "Einwohner, männlich", "XX/"), ("A0022", "Durchschnittsalter", "//X"),
                                   ("A0008", "Einwohner*innenentwicklung (zum Vorjahr)", "X/X"),
                                   ("A0547", "Bevölkerungsentwicklung (Veränderungsrate)", "//X")):
        katalog.append(["Bevölkerung und Haushalte", "Bevölkerung", kennung, name,
                        *[("X" if f == "X" else None) for f in formate.split("/")], *["3"] * 16])
    katalog.append(["Testthema", "Test", "Z9999", "Neue Spalte", "X", None, None, *["2"] * 16])
    mappe.save(pfad)


def export_text(zeilen=None):
    kopf = ";".join(["Indikatoren"] + [f'"{j}\n{k}"' for j in (2022, 2023) for k in ("Bonn", "Köln", "Wuppertal")])
    zeilen = zeilen or {
        "bevoelkerung": ["335.789", "1.087.353", "358.938", "336.001", "1.090.002", "359.003"],
        "bevoelkerungsentwicklung-ueber-die-letzten-5-jahre": ["k.A.", "k.A.", "k.A.", "1,5", "-0,3", "0,2"],
    }
    text = ("Bevölkerung, Bevölkerungsentwicklung über die letzten 5 Jahre und 8 weitere\n"
            "Bonn, kreisfreie Stadt, Köln, kreisfreie Stadt, ...\n\n" + kopf + "\n")
    for fu, name, einheit, _ in WW_LISTE:
        werte = zeilen.get(fu, ["10,0", "11,1", "12,2", "13,3", "14,4", "15,5"])
        text += f"{name} ({einheit});" + ";".join(werte) + "\n"
    return text + ('\n"k.A. = keine Angaben [Testdaten]"\n"Lizenz: Creative Commons Zero 1.0 (CC0 1.0)\n'
                   'https://creativecommons.org/publicdomain/zero/1.0/deed.de"\n')


def indikatorliste():
    liste = [{"id": i, "friendlyUrl": fu, "name": name, "unit": einheit, "source": quelle, "topics": ["Testthema"],
              "explanation": f"Erläuterung {name} [Testdaten]", "calculation": "Zähler / Nenner * 100", "hint": "",
              "years": [2022, 2023], "type": "COMMUNAL_DATA"} for i, (fu, name, einheit, quelle) in enumerate(WW_LISTE)]
    liste += [{"id": 90, "friendlyUrl": "einpersonen-haushalte", "name": "Einpersonen-Haushalte", "unit": "%",
               "source": "Nexiga GmbH, ZEFIR, eigene Berechnungen"},
              {"id": 91, "friendlyUrl": "haushalte-mit-kindern", "name": "Haushalte mit Kindern", "unit": "%",
               "source": "Nexiga GmbH, ZEFIR, eigene Berechnungen"},
              # gleicher Name und gleiche Einheit wie altenquotient (im Wegweiser gibt es solche Doppel)
              {"id": 92, "friendlyUrl": "altenquotient-prognose", "name": "Altenquotient",
               "unit": "ab 65-Jährige je 100 Pers. der AG 20-64", "source": "Test"}]
    return liste


REGIONEN = [{"friendlyUrl": "bonn", "name": "Bonn"}, {"friendlyUrl": "koeln", "name": "Köln"},
            {"friendlyUrl": "wuppertal", "name": "Wuppertal"}, {"friendlyUrl": "testhausen", "name": "Testhausen"}]


def dateien_schreiben(ordner, openapi="3.12.0"):
    """Eingaben mit den Standardnamen des Zwischenspeichers; liefert {Schlüssel: Pfad}."""
    ordner.mkdir(parents=True, exist_ok=True)
    p = {k: ordner / name for k, (name, _) in strukturdaten.DATEIEN.items()}
    xlsx_bauen(p["xlsx"])
    p["ww_export"].write_text(export_text(), encoding="utf-8")
    p["ww_indikatoren"].write_text(json.dumps(indikatorliste(), ensure_ascii=False), encoding="utf-8")
    p["ww_regionen"].write_text(json.dumps(REGIONEN, ensure_ascii=False), encoding="utf-8")
    p["ww_version"].write_text("2026-10-15T08:45:18.099083Z-test", encoding="utf-8")
    p["ww_openapi"].write_text(json.dumps({"openapi": "3.0.3", "info": {"version": openapi}}), encoding="utf-8")
    return p


def protokoll_schreiben(ordner, pfade, weglassen=()):
    zeilen = ["\t".join(strukturdaten.KOPF_PROTOKOLL)]
    for k, url, quelle in strukturdaten.ABRUFE:
        if k in weglassen:
            continue
        summe = hashlib.sha256(pfade[k].read_bytes()).hexdigest()
        zeilen.append("\t".join([quelle, url, "2026-11-10T10:45:58+01:00", "200", "", summe, ""]))
    (ordner / "audit_abruf.tsv").write_text("\n".join(zeilen) + "\n", encoding="utf-8")


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    dl, aus = tmp_path / "dl", tmp_path / "aus"
    monkeypatch.setenv("STRUKTURDATEN_DL", str(dl))
    monkeypatch.setenv("STRUKTURDATEN_AUS", str(aus))
    for _, variable in (*strukturdaten.DATEIEN.values(), strukturdaten.PROTOKOLL):
        monkeypatch.delenv(variable, raising=False)
    for variable in ("STRUKTURDATEN_ABRUF", "RATSATLAS_STADT_INFORMIERT", "STRUKTURDATEN_OPENAPI_BESTAETIGT"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(config, "ABRUF_ABSTAND", 0.0)
    return dl, aus


def _lesen(pfad):
    with open(pfad, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def _normalisieren(dl, aus):
    pfade = dateien_schreiben(dl)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    return pfade, {n: _lesen(aus / n) for n in ("indikatoren.tsv", "werte.tsv", "gesamtstadt.tsv",
                                                "zurueckgestellt.tsv", "audit_abruf.tsv")}


# --- Hilfen -----------------------------------------------------------------------------------------------------------

def test_zahlen_unveraendert():
    assert strukturdaten.zahl(1100076) == "1100076"
    assert strukturdaten.zahl(48.861624) == "48.861624"
    assert strukturdaten.zahl(0.1 + 0.2) == "0.30000000000000004"   # kürzeste Schreibweise desselben Werts
    assert strukturdaten.zahl(1e-05) == "0.00001" and strukturdaten.zahl(-0.0) == "-0.0"
    with pytest.raises(TypeError):
        strukturdaten.zahl(True)
    assert strukturdaten.de_zahl("1.087.353") == "1087353"
    assert strukturdaten.de_zahl("-0,3") == "-0.3" and strukturdaten.de_zahl("5,0") == "5.0"
    for unlesbar in ("1.08", "k.A.", "", "1,2,3", "12.3456"):
        with pytest.raises(ValueError):
            strukturdaten.de_zahl(unlesbar)


def test_jahre_als_bereiche():
    assert strukturdaten.jahre_text(["2025", "2024", "2023"]) == "2023-2025"
    assert strukturdaten.jahre_text([2012, 2013, 2015, 2017, 2018]) == "2012-2013;2015;2017-2018"
    assert strukturdaten.jahre_text([2012, 2013, 2015], "–") == "2012–2013;2015"   # Fließtext im Metatext
    assert strukturdaten.jahre_text([]) == ""


def test_adressen_der_quellen():
    """Die Datei des Katalogs liegt auf einem Server der Stadt (Schutz wie pipeline/abruf.py), der Wegweiser nicht; je
    Quelldatei eine Anfrage und eine für die OpenAPI-Beschreibung."""
    assert abruf.stadt(strukturdaten.XLSX_URL)
    assert not any(abruf.stadt(u) for k, u, _ in strukturdaten.ABRUFE if k != "xlsx")
    assert strukturdaten.MAX_ANFRAGEN == 6 == len(strukturdaten.DATEIEN)
    assert strukturdaten.ABRUFE[0][0] == "ww_openapi"   # Versionsprüfung vor allen Daten des Wegweisers
    assert strukturdaten.WW_EXPORT_URL == (
        "https://www.wegweiser-kommune.de/data-api/rest/export/bevoelkerung+bevoelkerungsentwicklung-ueber-die-"
        "letzten-5-jahre+durchschnittsalter+jugendquotient+altenquotient+sgb-ii-quote+arbeitslose-an-den-svb+"
        "beschaeftigungsquote+auslaenderanteil+wohnflaeche-pro-person+bonn+koeln+wuppertal+2006-2023+tabelle.csv"
        "?charset=UTF-8")


def test_klassifikation_aus_phase0():
    k = strukturdaten.klassifikation()
    assert len(k) == 211 and sum(z["typ_sicherheit"] == "unsicher" for z in k.values()) == 39
    assert sum(bool(z["zaehler_id"]) for z in k.values()) == 34
    assert all(z["beleg_zaehler_nenner"].startswith("Phase 0 (10.11.2026), numerisch geprüft")
               for z in k.values() if z["zaehler_id"])


# --- Normalisierung ---------------------------------------------------------------------------------------------------

def test_werte_status_und_quellobjekt(umgebung):
    dl, aus = umgebung
    _, t = _normalisieren(dl, aus)
    werte = {(w["raumebene"], w["raum_id"], w["indikator_id"], w["jahr"]): w for w in t["werte.tsv"]}
    # nur Gesamtstadt, Stadtbezirke, Stadtteile; keine Quartiere, keine Sozialräume
    assert {w["raumebene"] for w in t["werte.tsv"]} == {"gesamtstadt", "stadtbezirk", "stadtteil"}
    assert {w["raum_id"] for w in t["werte.tsv"]} == {"0", "1", "2", "101", "102", "201"}
    # 6 Räume × 2 Jahre × 6 übernommene Indikatoren, je Kombination genau eine Zeile
    assert len(t["werte.tsv"]) == len(werte) == 6 * 2 * 6
    w = werte[("gesamtstadt", "0", "koeln_A0025A", "2025")]
    assert (w["wert"], w["status"], w["quellobjekt"]) == (str(_werte("0 / Stadt Köln", 2025)[0]), "ok", "Daten!D2")
    assert werte[("gesamtstadt", "0", "koeln_A0022S", "2025")]["wert"] == "0.1234567890123456"
    assert werte[("stadtbezirk", "1", "koeln_A0022S", "2025")]["wert"] == "0.00001"
    g = werte[("stadtteil", "101", "koeln_A0109P", "2025")]
    assert (g["wert"], g["status"], g["quellobjekt"]) == ("", "geheim", "Daten!H6")
    assert werte[("stadtteil", "101", "koeln_A0109A", "2025")]["status"] == "geheim"
    f = werte[("stadtteil", "201", "koeln_A0022S", "2024")]
    assert (f["wert"], f["status"], f["quellobjekt"]) == ("", "fehlt", "Daten!I16")
    f = werte[("stadtteil", "201", "koeln_A0359A", "2024")]
    assert (f["wert"], f["status"], f["quellobjekt"]) == ("", "fehlt", "Daten!F16")
    from collections import Counter
    assert Counter(w["status"] for w in t["werte.tsv"]) == {"ok": 68, "geheim": 2, "fehlt": 2}
    assert werte[("stadtbezirk", "2", "koeln_A0109P", "2024")]["wert"] == repr(_werte("2 / Rodenkirchen", 2024)[4])
    # Reihenfolge: Ebene, Raum, Indikator, Jahr
    schluessel = [(w["raumebene"], int(w["raum_id"]), w["indikator_id"], w["jahr"]) for w in t["werte.tsv"]]
    ordnung = {"gesamtstadt": 0, "stadtbezirk": 1, "stadtteil": 2}
    assert schluessel == sorted(schluessel, key=lambda s: (ordnung[s[0]], *s[1:]))


def test_indikatoren_und_zurueckgestellte(umgebung):
    dl, aus = umgebung
    pfade, t = _normalisieren(dl, aus)
    ind = {i["indikator_id"]: i for i in t["indikatoren.tsv"]}
    assert list(t["indikatoren.tsv"][0]) == strukturdaten.KOPF_INDIKATOREN
    assert set(ind) == {f"koeln_{c}" for c in ("A0025A", "A0355A", "A0359A", "A0109A", "A0109P", "A0022S")} | {
        f"ww_{fu}" for fu, *_ in WW_LISTE}
    a = ind["koeln_A0109P"]
    assert (a["typ"], a["einheit"], a["zaehler_id"], a["nenner_id"]) == ("anteil", "%", "koeln_A0109A", "koeln_A0025A")
    assert "Haupt- und Nebenwohnsitz" in a["metatext"] and a["thema"] == "Bevölkerung und Haushalte"
    assert (a["raumebenen"], a["jahre"], a["abrufdatum"]) == ("gesamtstadt;stadtbezirk;stadtteil", "2024-2025",
                                                               "2026-11-10")
    assert a["geheimhaltung"] == GEHEIM and a["quell_url"] == strukturdaten.DATENSATZ_URL
    assert a["datenhalter"] == "Stadt Köln - Testamt (eigene Berechnung)"
    assert "Nebenwohnsitz (koeln_A0359A)" in ind["koeln_A0025A"]["metatext"]
    assert "Anmerkung der Quelle: Testanmerkung zur Berechnung." in ind["koeln_A0022S"]["metatext"]
    assert "Schätz" not in " ".join(i["metatext"] for i in ind.values())   # die Quelle sagt dazu nichts
    for i in ind.values():
        assert i["typ"] in strukturdaten.TYPEN and i["lizenz"] and i["lizenz_url"] and i["namensnennung"]
    zur = {z["indikator_id"]: z for z in t["zurueckgestellt.tsv"]}
    assert "Werte im Blatt Daten vorhanden" in zur["koeln_A0008S"]["grund"]
    assert "ohne Klassifikation" in zur["koeln_Z9999A"]["grund"]
    assert "ohne Werte (nur im Katalog)" in zur["koeln_A0547S"]["grund"]
    assert zur["koeln_A0547S"]["name"] == "Bevölkerungsentwicklung (Veränderungsrate)"
    unsicher = {k for k, z in strukturdaten.klassifikation().items() if z["typ_sicherheit"] == "unsicher"}
    assert unsicher <= set(zur) and len(unsicher) == 39
    assert {"ww_einpersonen-haushalte", "ww_haushalte-mit-kindern"} <= set(zur)
    assert not set(zur) & set(ind)
    assert not {w["indikator_id"] for w in t["werte.tsv"]} & set(zur)


def test_verhaeltnis_das_nicht_gilt_entfaellt(umgebung):
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)

    def falsch(daten):
        daten["H3"] = 12.5   # Anteil passt nicht zu Männer / Gesamt
    xlsx_bauen(pfade["xlsx"], falsch)
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    a = next(i for i in _lesen(aus / "indikatoren.tsv") if i["indikator_id"] == "koeln_A0109P")
    assert (a["zaehler_id"], a["nenner_id"]) == ("", "") and "Zähler" not in a["metatext"]


def test_gesamtstadt_und_ka(umgebung):
    dl, aus = umgebung
    _, t = _normalisieren(dl, aus)
    g = t["gesamtstadt.tsv"]
    assert list(g[0]) == strukturdaten.KOPF_GESAMTSTADT
    zeile = {(z["kommune"], z["indikator_id"], z["jahr"]): z for z in g}
    k = zeile[("koeln", "ww_bevoelkerung", "2022")]
    assert (k["wegweiser_friendly_url"], k["wert"], k["abrufdatum"]) == ("bevoelkerung", "1087353", "2026-11-10")
    assert zeile[("koeln", "ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre", "2023")]["wert"] == "-0.3"
    assert zeile[("wuppertal", "ww_durchschnittsalter", "2023")]["wert"] == "15.5"
    # „k.A.“: keine Zeile (der Vertrag kennt in gesamtstadt.tsv keinen Status), im Metatext genannt
    assert ("bonn", "ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre", "2022") not in zeile
    assert len(g) == 10 * 6 - 3 and all(z["wert"] for z in g)
    assert {z["kommune"] for z in g} == {"bonn", "koeln", "wuppertal"}
    ind = {i["indikator_id"]: i for i in t["indikatoren.tsv"]}
    e = ind["ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"]
    assert "„k.A.“, nicht übernommen): 2022 (Bonn, Köln, Wuppertal)" in e["metatext"]
    assert (e["jahre"], e["raumebenen"], e["typ"]) == ("2023", "gesamtstadt", "quote")
    b = ind["ww_bevoelkerung"]
    assert (b["typ"], b["einheit"], b["datenhalter"], b["lizenz_url"]) == (
        "anzahl", "Anzahl", "Statistische Ämter der Länder", strukturdaten.WW_LIZENZ_URL)
    assert b["namensnennung"].startswith("Bertelsmann Stiftung, wegweiser-kommune.de")


def test_meta_und_audit(umgebung):
    dl, aus = umgebung
    pfade, t = _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert meta["vertrag_version"] == "1" and meta["datenstand"] == "2026-10-15"
    assert meta["abrufdatum"] == "2026-11-10" and meta["veroeffentlichen"] is True
    assert meta["lizenzstatus"] == "geklärt" and meta["einwohner_indikator"] == "koeln_A0355A"
    assert meta["raumebenen"] == ["gesamtstadt", "stadtbezirk", "stadtteil"]
    summen = {q["kennung"]: q for q in meta["quellen"]}
    assert summen["statistischer-datenkatalog-koeln"]["sha256"] == hashlib.sha256(
        pfade["xlsx"].read_bytes()).hexdigest()
    assert summen["statistischer-datenkatalog-koeln"]["lizenz_url"] == "https://www.govdata.de/dl-de/by-2-0"
    assert summen["wegweiser-openapi"]["openapi_version"] == "3.12.0"
    assert all(q["url"] and q["lizenz"] and q["namensnennung"] and len(q["sha256"]) == 64 for q in meta["quellen"])
    audit = t["audit_abruf.tsv"]
    assert list(audit[0]) == strukturdaten.KOPF_AUDIT and len(audit) == 6
    text = (aus / "audit_abruf.tsv").read_text(encoding="utf-8")
    assert str(dl) not in text and "/tmp" not in text   # ohne lokale Pfade
    zeilen = {a["url"]: a for a in audit}
    assert zeilen[strukturdaten.XLSX_URL]["zeilen"] == str(2 * len(RAEUME))
    assert zeilen[strukturdaten.WW_EXPORT_URL]["zeilen"] == "10"
    assert "info.version 3.12.0" in {a["hinweis"] for a in audit}


def test_ausgabe_deterministisch(umgebung):
    dl, aus = umgebung
    _normalisieren(dl, aus)
    erst = {p.name: p.read_bytes() for p in aus.iterdir()}
    strukturdaten.write()
    assert {p.name: p.read_bytes() for p in aus.iterdir()} == erst
    assert set(erst) == {"indikatoren.tsv", "werte.tsv", "gesamtstadt.tsv", "zurueckgestellt.tsv", "audit_abruf.tsv",
                         "meta.json"}


def test_eingabe_ohne_protokoll_abgelehnt(umgebung):
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    protokoll_schreiben(dl, pfade, weglassen={"ww_export"})
    with pytest.raises(ValueError, match="nicht im Abrufprotokoll"):
        strukturdaten.write()
    assert not (aus / "werte.tsv").exists()


def test_protokoll_der_exploration_lesbar(umgebung, monkeypatch):
    """Das Protokoll aus Phase 0 hat die Spalten zeit, status, sha256 (und pfad); die Ausgabe enthält keine Pfade."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    zeilen = ["quelle\turl\tzeit\tstatus\tbytes\tsha256\tpfad"]
    for k, url, quelle in strukturdaten.ABRUFE:
        zeilen.append("\t".join([quelle, url, "2026-11-10T10:46:28+01:00", "200", "1",
                                 hashlib.sha256(pfade[k].read_bytes()).hexdigest(), str(pfade[k])]))
    (dl / "phase0.tsv").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    monkeypatch.setenv("STRUKTURDATEN_PROTOKOLL", str(dl / "phase0.tsv"))
    strukturdaten.write()
    audit = _lesen(aus / "audit_abruf.tsv")
    assert {a["zeitstempel"] for a in audit} == {"2026-11-10T10:46:28+01:00"} and len(audit) == 6
    assert "pfad" not in audit[0] and str(dl) not in (aus / "audit_abruf.tsv").read_text(encoding="utf-8")


def test_unerwarteter_wert_bricht_ab(umgebung):
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    xlsx_bauen(pfade["xlsx"], lambda d: d.__setitem__("D4", "12,5"))
    protokoll_schreiben(dl, pfade)
    with pytest.raises(ValueError, match=r"Daten!D4"):
        strukturdaten.write()


# --- Abruf (nur lokaler Testserver) -----------------------------------------------------------------------------------

PFADE = {"ww_openapi": "/openapi", "ww_version": "/version", "ww_indikatoren": "/indikatoren",
         "ww_regionen": "/regionen", "ww_export": "/export.csv", "xlsx": "/katalog.xlsx"}


@pytest.fixture
def server(tmp_path, umgebung, monkeypatch):
    """Lokaler Server mit den erfundenen Dateien; `status` je Pfad überschreibbar, `anfragen` = (Pfad, User-Agent)."""
    inhalt = {PFADE[k]: p.read_bytes() for k, p in dateien_schreiben(tmp_path / "quelle").items()}
    zustand = {"anfragen": [], "status": {}, "inhalt": inhalt}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            zustand["anfragen"].append((self.path, self.headers.get("User-Agent")))
            status = zustand["status"].get(self.path, 200)
            if status != 200:
                self.send_response(status)
                if 300 <= status < 400:
                    self.send_header("Location", "/anderswo")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            daten = zustand["inhalt"][self.path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    basis = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(strukturdaten, "ABRUFE", [(k, basis + PFADE[k], q) for k, _, q in strukturdaten.ABRUFE])
    zustand["basis"] = basis
    yield zustand
    srv.shutdown()
    srv.server_close()


def _protokoll(dl):
    return _lesen(dl / "audit_abruf.tsv")


def test_abruf_vollstaendig_und_danach_normalisierbar(server, umgebung):
    dl, aus = umgebung
    lauf = strukturdaten.abruf_lauf()
    assert lauf.anfragen == 6 == len(server["anfragen"])
    assert [p for p, _ in server["anfragen"]] == [PFADE[k] for k, *_ in strukturdaten.ABRUFE]
    assert {ua for _, ua in server["anfragen"]} == {config.USER_AGENT}
    zeilen = _protokoll(dl)
    assert [z["http_status"] for z in zeilen] == ["200"] * 6 and list(zeilen[0]) == strukturdaten.KOPF_PROTOKOLL
    for k, (name, _) in strukturdaten.DATEIEN.items():
        inhalt = server["inhalt"][PFADE[k]]
        assert (dl / name).read_bytes() == inhalt
        assert next(z for z in zeilen if z["url"].endswith(PFADE[k]))["pruefsumme"] == hashlib.sha256(
            inhalt).hexdigest()
    assert next(z for z in zeilen if z["url"].endswith("/katalog.xlsx"))["zeilen"] == str(2 * len(RAEUME))
    strukturdaten.write()   # die geladenen Dateien stehen mit Prüfsumme im Protokoll
    assert (aus / "werte.tsv").exists()


def test_obergrenze_der_anfragen(server, umgebung, monkeypatch):
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "MAX_ANFRAGEN", 3)
    with pytest.raises(SystemExit, match="obergrenze"):
        strukturdaten.abruf_lauf()
    assert len(server["anfragen"]) == 3
    status = [z["http_status"] for z in _protokoll(dl)]
    # danach die drei geladenen Wegweiser-Dateien als verworfen (nur gemeinsam mit allen fünf übernommen)
    assert status == ["200"] * 3 + ["nicht gesendet (obergrenze)"] + [strukturdaten.VERWORFEN] * 3
    assert not any((dl / name).exists() for name, _ in strukturdaten.DATEIEN.values())


def test_keine_wiederholung_nach_503(server, umgebung):
    dl, _ = umgebung
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "wegweiser_export.csv").write_text("vorher", encoding="utf-8")
    server["status"]["/export.csv"] = 503
    with pytest.raises(SystemExit, match="HTTP 503"):
        strukturdaten.abruf_lauf()
    pfade = [p for p, _ in server["anfragen"]]
    assert pfade.count("/export.csv") == 1 and "/katalog.xlsx" not in pfade   # keine Wiederholung, Lauf beendet
    assert (dl / "wegweiser_export.csv").read_text(encoding="utf-8") == "vorher"   # vorige Datei bleibt
    assert [z["http_status"] for z in _protokoll(dl)][4:] == ["503"] + [strukturdaten.VERWORFEN] * 4
    assert not (dl / "wegweiser_version.txt").exists()   # Wegweiser-Dateien nur gemeinsam übernommen


def test_weiterleitung_nicht_verfolgt(server, umgebung):
    dl, _ = umgebung
    server["status"]["/openapi"] = 302
    with pytest.raises(SystemExit, match="weiterleitung"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]


def test_versionswechsel_bricht_ab(server, umgebung, monkeypatch):
    dl, aus = umgebung
    aus.mkdir(parents=True)
    (aus / "meta.json").write_text(json.dumps({"quellen": [{"openapi_version": "3.11.0"}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="info.version der Wegweiser-OpenAPI ist 3.12.0, zuletzt 3.11.0"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]   # keine weitere Anfrage
    assert (dl / "wegweiser_openapi.neu.json").exists() and not (dl / "wegweiser_openapi.json").exists()
    assert "zuletzt 3.11.0" in _protokoll(dl)[-1]["hinweis"]
    # nach Prüfung bestätigt: Lauf geht weiter
    monkeypatch.setenv("STRUKTURDATEN_OPENAPI_BESTAETIGT", "3.12.0")
    assert strukturdaten.abruf_lauf().anfragen == 6


class _KeinNetz:
    def open(self, *a, **k):
        raise AssertionError("keine Anfrage erwartet")


def test_stadt_und_freigabe_ohne_anfrage(server, umgebung, monkeypatch):
    """Die echte Adresse der Stadt wird ohne RATSATLAS_STADT_INFORMIERT und außerhalb des Zeitfensters nicht gesendet;
    Wegweiser-Adressen (nicht lokal) nicht ohne STRUKTURDATEN_ABRUF. Kein Versuch einer Verbindung."""
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "_OEFFNER", _KeinNetz())
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("xlsx", strukturdaten.XLSX_URL, "offenedaten-koeln")])
    monkeypatch.setenv("STRUKTURDATEN_ABRUF", "ja")
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    strukturdaten.abruf_lauf()
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc))   # 12 Uhr in Köln
    strukturdaten.abruf_lauf()
    monkeypatch.delenv("STRUKTURDATEN_ABRUF")
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("ww_openapi", strukturdaten.WW + "/openapi?format=JSON",
                                                   "wegweiser-kommune")])
    strukturdaten.abruf_lauf()
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status[0].startswith("nicht gesendet (gesperrt: Server der Stadt Köln")
    assert status[1].startswith("nicht gesendet (außerhalb des Zeitfensters 23-1 Uhr")
    assert status[2] == "nicht gesendet (ohne Freigabe (STRUKTURDATEN_ABRUF=ja))"
    assert not server["anfragen"]


def test_stadtschutz_mit_lokalem_server(server, umgebung, monkeypatch):
    """Der lokale Server gilt als Server der Stadt: gesendet nur mit RATSATLAS_STADT_INFORMIERT=ja im Zeitfenster."""
    dl, _ = umgebung
    monkeypatch.setattr(abruf, "STADT_DOMAINS", ("127.0.0.1",))
    monkeypatch.setattr(abruf, "MINDESTABSTAND", 0.0)
    monkeypatch.setattr(config, "KONTAKT", "test@example.invalid")   # Pflicht für Server der Stadt
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("xlsx", server["basis"] + "/katalog.xlsx", "offenedaten-koeln")])
    assert abruf.stadt(server["basis"] + "/katalog.xlsx")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc))   # 23:30 in Köln
    strukturdaten.abruf_lauf()
    assert not server["anfragen"]
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))
    strukturdaten.abruf_lauf()
    assert not server["anfragen"]
    monkeypatch.setattr(abruf, "uhr", lambda: datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc))
    assert strukturdaten.abruf_lauf().anfragen == 1 and len(server["anfragen"]) == 1
    assert [z["http_status"][:14] for z in _protokoll(dl)] == ["nicht gesendet"] * 2 + ["200"]


# --- Prüfung r1 (10.11.2026): Kontakt, Abstand, Zeitfenster, Version, Größe, unlesbare Antwort, gemischter Stand -----

KONTAKT = "test@example.invalid"


def _als_stadt(server, monkeypatch, abrufe, kontakt=KONTAKT):
    """Der lokale Server gilt als Server der Stadt (Freigabe gesetzt, 23:30 Uhr in Köln, Zeitfenster 23–1 Uhr);
    `abrufe`: Schlüssel, deren Pfade der Lauf lädt. `kontakt` leer: User-Agent ohne Kontakt."""
    monkeypatch.setattr(abruf, "STADT_DOMAINS", ("127.0.0.1",))
    monkeypatch.setattr(config, "ABRUF_ZEITFENSTER", "23-1")
    monkeypatch.setattr(config, "KONTAKT", kontakt)
    monkeypatch.setattr(config, "USER_AGENT", "ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln"
                        + (f"; {kontakt}" if kontakt else "") + ")")
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", "ja")
    uhr = {"jetzt": datetime(2026, 11, 10, 22, 30, tzinfo=timezone.utc)}   # 23:30 in Köln
    monkeypatch.setattr(abruf, "uhr", lambda: uhr["jetzt"])
    quelle = dict((k, q) for k, _, q in strukturdaten.ABRUFE)
    monkeypatch.setattr(strukturdaten, "ABRUFE", [(k, server["basis"] + PFADE[k], quelle[k]) for k in abrufe])
    return uhr


def test_ohne_kontakt_keine_anfrage(server, umgebung, monkeypatch):
    """Ohne RATSATLAS_KONTAKT geht keine Anfrage an einen Server der Stadt (CLAUDE.md 5.1, wie sessionnet): laut als
    Einstellungsfehler (ValueError, Ausstieg 2), nicht gezählt, im Protokoll vermerkt. Mit Kontakt steht er im
    User-Agent."""
    dl, _ = umgebung
    _als_stadt(server, monkeypatch, ["xlsx"], kontakt="")
    with pytest.raises(ValueError, match="RATSATLAS_KONTAKT fehlt"):
        strukturdaten.abruf_lauf()
    with pytest.raises(SystemExit) as aus:
        strukturdaten.abruf_schritt()
    assert aus.value.code == 2 and not server["anfragen"]
    assert [z["http_status"] for z in _protokoll(dl)] == ["nicht gesendet (einstellung)"] * 2
    _als_stadt(server, monkeypatch, ["xlsx"])
    assert strukturdaten.abruf_lauf().anfragen == 1
    assert server["anfragen"] == [("/katalog.xlsx", f"ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; "
                                                     f"{KONTAKT})")]


def test_ohne_kontakt_auch_nicht_an_den_wegweiser(umgebung, monkeypatch):
    """Auch nicht lokale Adressen außerhalb der Stadt (Wegweiser) nur mit Kontakt; kein Versuch einer Verbindung."""
    monkeypatch.setattr(strukturdaten, "_OEFFNER", _KeinNetz())
    monkeypatch.setattr(config, "KONTAKT", "")
    monkeypatch.setenv("STRUKTURDATEN_ABRUF", "ja")
    with pytest.raises(ValueError, match="RATSATLAS_KONTAKT fehlt"):
        strukturdaten.abruf_lauf()
    assert [z["http_status"] for z in _protokoll(umgebung[0])] == ["nicht gesendet (einstellung)"]


def test_mindestabstand_zwischen_anfragen(server, umgebung, monkeypatch):
    """Zwischen zwei Anfragen an die Stadt liegen mindestens abruf.MINDESTABSTAND Sekunden, auch mit
    RATSATLAS_ABSTAND=0 (time.sleep protokolliert statt gewartet)."""
    _als_stadt(server, monkeypatch, ["ww_openapi", "ww_version"])
    pausen = []
    monkeypatch.setattr(strukturdaten.time, "sleep", pausen.append)
    assert strukturdaten.abruf_lauf().anfragen == 2 and len(server["anfragen"]) == 2
    assert len(pausen) == 1 and abruf.MINDESTABSTAND - 0.5 < pausen[0] <= abruf.MINDESTABSTAND


def test_zeitfenster_endet_beim_warten(server, umgebung, monkeypatch):
    """Endet das Zeitfenster während des Wartens auf den Abstand, wird die Anfrage nicht gesendet (Prüfung unmittelbar
    vor dem Senden)."""
    dl, _ = umgebung
    uhr = _als_stadt(server, monkeypatch, ["ww_openapi", "ww_version"])

    def warten(sekunden):
        uhr["jetzt"] = datetime(2026, 11, 11, 0, 0, 1, tzinfo=timezone.utc)   # 01:00:01 in Köln
    monkeypatch.setattr(strukturdaten.time, "sleep", warten)
    assert strukturdaten.abruf_lauf().anfragen == 1
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]
    assert _protokoll(dl)[1]["http_status"].startswith("nicht gesendet (außerhalb des Zeitfensters 23-1 Uhr")


def test_wegweiser_nur_nach_versionspruefung(server, umgebung, monkeypatch):
    """Ohne geprüfte info.version keine Anfrage an den Wegweiser; die Datei der Stadt (hier lokal) bleibt unberührt."""
    dl, _ = umgebung
    monkeypatch.setattr(strukturdaten, "ABRUFE", [a for a in strukturdaten.ABRUFE if a[0] != "ww_openapi"])
    assert strukturdaten.abruf_lauf().anfragen == 1
    assert [p for p, _ in server["anfragen"]] == ["/katalog.xlsx"]
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status == ["nicht gesendet (info.version der Wegweiser-OpenAPI nicht geprüft)"] * 4 + ["200"]


def test_groessenobergrenze(server, umgebung, monkeypatch):
    dl, _ = umgebung
    dl.mkdir(parents=True, exist_ok=True)
    (dl / "wegweiser_openapi.json").write_text("vorher", encoding="utf-8")
    monkeypatch.setattr(strukturdaten, "MAX_BYTES", 10)
    with pytest.raises(SystemExit, match=r"abgebrochen \(unlesbar\).*größer als 10 Bytes"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]] == ["/openapi"]
    assert (dl / "wegweiser_openapi.json").read_text(encoding="utf-8") == "vorher"
    assert not list(dl.rglob("*.tmp")) and _protokoll(dl)[-1]["http_status"] == "abbruch (unlesbar)"


@pytest.mark.parametrize("schluessel", ["ww_export", "xlsx"])
def test_unlesbare_antwort_vorige_datei_bleibt(server, umgebung, monkeypatch, schluessel):
    """Eine Webseite statt der Daten: Lauf endet (unlesbar), die vorige Datei bleibt, keine weitere Anfrage."""
    dl, _ = umgebung
    dl.mkdir(parents=True, exist_ok=True)
    name, pfad = strukturdaten.DATEIEN[schluessel][0], PFADE[schluessel]
    (dl / name).write_text("vorher", encoding="utf-8")
    server["inhalt"][pfad] = b"<!DOCTYPE html><html><body>Wartung</body></html>"
    if schluessel == "xlsx":
        monkeypatch.setattr(strukturdaten, "ABRUFE", [a for a in strukturdaten.ABRUFE if a[0] == "xlsx"])
    with pytest.raises(SystemExit, match=r"abgebrochen \(unlesbar\)"):
        strukturdaten.abruf_lauf()
    assert [p for p, _ in server["anfragen"]][-1] == pfad
    assert (dl / name).read_text(encoding="utf-8") == "vorher" and not list(dl.rglob("*.tmp"))
    zeilen = [z for z in _protokoll(dl) if z["url"].endswith(pfad)]
    assert zeilen[0]["hinweis"].startswith("unlesbar: Webseite statt Daten") and len(zeilen) == 1


def test_unternehmen_als_datenhalter_abgelehnt(tmp_path):
    pfade = dateien_schreiben(tmp_path)
    liste = indikatorliste()
    liste[3]["source"] = "Nexiga GmbH, ZEFIR, eigene Berechnungen"   # jugendquotient
    pfade["ww_indikatoren"].write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="jugendquotient hat ein Unternehmen als Datenhalter"):
        strukturdaten.Wegweiser(pfade["ww_export"], pfade["ww_indikatoren"], pfade["ww_regionen"],
                                pfade["ww_version"], pfade["ww_openapi"])


@pytest.mark.parametrize("pfad", ["/kätalog.xlsx", "ftp://127.0.0.1/katalog.xlsx"])
def test_ungueltige_adresse_nicht_gesendet(server, umgebung, monkeypatch, pfad):
    dl, _ = umgebung
    url = pfad if "://" in pfad else server["basis"] + pfad
    monkeypatch.setattr(strukturdaten, "ABRUFE", [("xlsx", url, "offenedaten-koeln")])
    with pytest.raises(SystemExit, match=r"abgebrochen \(adresse\)"):
        strukturdaten.abruf_lauf()
    assert not server["anfragen"] and _protokoll(dl)[-1]["http_status"] == "nicht gesendet (adresse)"


def test_abgebrochener_lauf_mischt_keine_staende(server, umgebung, monkeypatch):
    """Die Wegweiser-Dateien eines Laufs ersetzen die vorigen nur gemeinsam: Bricht der Lauf vor dem Export ab, bleiben
    Datenversion, Listen und Export aus dem vorigen vollständigen Lauf; meta.json nennt die passende Datenversion."""
    dl, aus = umgebung
    uhr = {"jetzt": datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(abruf, "uhr", lambda: uhr["jetzt"])
    strukturdaten.abruf_lauf()
    uhr["jetzt"] = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    vorher = {name: (dl / name).read_bytes() for name, _ in strukturdaten.DATEIEN.values()}
    server["inhalt"]["/version"] = b"2027-05-01T00:00:00Z-neu"
    server["status"]["/export.csv"] = 503
    with pytest.raises(SystemExit, match="HTTP 503"):
        strukturdaten.abruf_lauf()
    assert {name: (dl / name).read_bytes() for name in vorher} == vorher
    assert not (dl / strukturdaten.STUFE).exists()
    status = [z["http_status"] for z in _protokoll(dl)]
    assert status[6:] == ["200", "200", "200", "200", "503"] + [strukturdaten.VERWORFEN] * 4
    meta = strukturdaten.write()
    assert "Datenversion 2026-10-15T08:45:18.099083Z-test" in meta["datenstand_hinweis"]
    beleg = {q["kennung"]: q for q in meta["quellen"]}["wegweiser-openapi"]
    erster = next(z for z in _protokoll(dl) if z["url"].endswith("/openapi"))
    assert beleg["abgerufen"] == erster["zeitstempel"]   # nicht der verworfene Abruf mit gleichem Inhalt
    # vollständiger Lauf: alle fünf Dateien neu, die XLSX unabhängig davon
    del server["status"]["/export.csv"]
    server["status"]["/katalog.xlsx"] = 503
    uhr["jetzt"] = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)
    with pytest.raises(SystemExit, match="HTTP 503"):
        strukturdaten.abruf_lauf()
    assert (dl / "wegweiser_version.txt").read_bytes() == b"2027-05-01T00:00:00Z-neu"
    assert (dl / "statistischer_datenkatalog_koeln.xlsx").read_bytes() == vorher[
        "statistischer_datenkatalog_koeln.xlsx"]
    assert "Datenversion 2027-05-01T00:00:00Z-neu" in strukturdaten.write()["datenstand_hinweis"]


# --- Prüfung r1: Kennzeichnung eigener Einordnungen, Formate, Metatext A0025A ------------------------------------------

def test_eigene_einordnungen_und_formate_gekennzeichnet(umgebung):
    dl, aus = umgebung
    _, t = _normalisieren(dl, aus)
    meta = json.loads((aus / "meta.json").read_text(encoding="utf-8"))
    assert "eigene Einordnung" in meta["typ_einordnung"] and "strukturdaten_koeln.tsv" in meta["typ_einordnung"]
    vorl = meta["typ_vorlaeufig"]
    assert set(vorl) == {"ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"}
    assert "Veränderungsrate" in vorl["ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"]
    ind = {i["indikator_id"]: i for i in t["indikatoren.tsv"]}
    e = ind["ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre"]
    assert e["typ"] == "quote" and "vorläufig" in e["metatext"] and "Veränderungsrate" in e["metatext"]
    assert "vorläufig" not in ind["ww_altenquotient"]["metatext"]
    assert set(meta["formate"]) >= {"jahre", "raumebenen", "wert", "dateien"}
    assert "2012-2014;2016" in meta["formate"]["jahre"]
    assert "geheim" in meta["geheimhaltung_hinweis"]
    assert all(i["jahre"].isascii() for i in t["indikatoren.tsv"])
    assert ind["koeln_A0109P"]["jahre"] == "2024-2025"


def test_metatext_summe_nennt_nicht_pruefbare_zeilen(umgebung):
    """A0025A = A0355A + A0359A: der Metatext nennt geprüfte und nicht prüfbare Zeilen (Testdaten: A0359A fehlt für
    201/2024, für 102/2025 geheim)."""
    dl, aus = umgebung
    pfade = dateien_schreiben(dl)
    xlsx_bauen(pfade["xlsx"], lambda d: d.__setitem__("F7", "*"))
    protokoll_schreiben(dl, pfade)
    strukturdaten.write()
    a = next(i for i in _lesen(aus / "indikatoren.tsv") if i["indikator_id"] == "koeln_A0025A")
    assert ("nachgerechnet in 10 von 12 Zeilen; nicht prüfbar: 1 Zeile mit geheim gehaltenem Wert, 1 Zeile mit "
            "fehlendem Wert") in a["metatext"]
