"""aemter.json: Aufbau der Verwaltung für „Wer entscheidet“ (Entscheidung 21.11.2026 (2) (F8), Pull Request 4a).

Nur Dezernate und Einträge auf der Ebene der Dienststellen (Einheiten der Dezernate, Dienststellen, Punktdienststellen
mit „•“), ohne Untereinheiten; Einträge mit „●“ als eigene Gruppe ohne Zuordnung; Quelle, Stand und letzte Prüfung in
`meta`, keine Zahlen von Vorlagen. Die Regeln laufen an einer erfundenen Tabelle (tmp_path), dazu Gegenproben an der
Tabelle im Repository nur mit Zahlen, die aus ihr selbst gezählt werden. check.aemter_aufbau meldet eingeschleuste
Abweichungen nur mit Zahlen."""
import csv
import json
import re

from pipeline import aemter, check, config

ABRUF = "2026-11-13T22:00:00Z"


def _zeile(dez, code, ebene, name, ober="", kurz="", markierung="", ebe=""):
    return {"gueltig_ab": "2026-11-01", "dezernat": dez, "dienststelle": code,
            "kennung": f"{dez}/{code}" if code else dez, "ebene": ebene, "uebergeordnet": ober, "name": name,
            "kurzname": kurz, "eigenbetriebsaehnlich": ebe, "markierung": markierung,
            "fundstelle": f"Seite 1, Spalte Dezernat {dez}", "quelle": "https://example.invalid/plan",
            "abgerufen": ABRUF, "sha256": "0" * 64}


ERFUNDEN = [
    _zeile("VI", "", "dezernat", "Probebereich"),
    _zeile("VI", "VI/1", "dezernatseinheit", "Probebüro"),
    _zeile("VI", "61", "dienststelle", "Probeamt", kurz="PA", ebe="ja"),
    _zeile("VI", "610", "untereinheit", "Probeabteilung", "61"),
    _zeile("VI", "61/1", "untereinheit", "Probestelle", "61"),
    _zeile("VI", "6100", "punktdienststelle", "Probepunkt", "61", markierung="•"),
    _zeile("VI", "6199", "punktdienststelle", "Probeeinrichtung", "61", markierung="●"),
    _zeile("OB", "", "dezernat", ""),
    _zeile("OB", "01", "dienststelle", "Probeamt des Oberbürgermeisters"),
]


def _tabelle(tmp_path, zeilen=ERFUNDEN, name="aemter.tsv"):
    """Erfundene Tabelle als TSV; je Inhalt ein eigener Dateiname (aemter.tabelle merkt sich die Tabelle je Pfad)."""
    pfad = tmp_path / name
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=aemter.SPALTEN, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(zeilen)
    return pfad


def test_ebenen_ohne_untereinheiten_und_eigene_gruppe(tmp_path):
    """Dezernate in der Reihenfolge der Tabelle, je mit Einheit des Dezernats, Dienststelle und Punktdienststelle
    („•“); keine Untereinheit; der Eintrag mit „●“ ohne Dezernat, Kennung und Ebene in `ohne_zuordnung`; die abgeleitete
    übergeordnete Dienststelle steht nirgends."""
    d = aemter.aufbau(_tabelle(tmp_path))
    assert [x["dezernat"] for x in d["dezernate"]] == ["VI", "OB"]
    vi, ob = d["dezernate"]
    assert vi["label"] == "Dezernat VI – Probebereich" and ob["label"] == "Dezernat OB" and ob["name"] == ""
    assert [(e["nummer"], e["ebene"]) for e in vi["einheiten"]] == [
        ("VI/1", "dezernatseinheit"), ("61", "dienststelle"), ("6100", "punktdienststelle")]
    amt = vi["einheiten"][1]
    assert amt == {"nummer": "61", "kennung": "VI/61", "name": "Probeamt", "kurzname": "PA", "label": "61 Probeamt",
                   "ebene": "dienststelle", "eigenbetriebsaehnlich": True, "fundstelle": "Seite 1, Spalte Dezernat VI"}
    assert d["ohne_zuordnung"] == [{"nummer": "6199", "name": "Probeeinrichtung", "label": "6199 Probeeinrichtung",
                                    "markierung": "●", "fundstelle": "Seite 1, Spalte Dezernat VI"}]
    text = json.dumps(d, ensure_ascii=False)
    assert "untereinheit" not in text and "Probeabteilung" not in text and "Probestelle" not in text
    assert "uebergeordnet" not in text
    for x in d["dezernate"]:
        assert set(x) <= set(aemter.FELDER_DEZERNAT)
        assert all(set(e) <= set(aemter.FELDER_EINHEIT) for e in x["einheiten"])
    assert all(set(e) <= set(aemter.FELDER_OHNE_ZUORDNUNG) for e in d["ohne_zuordnung"])


def test_meta_quelle_stand_pruefung_ohne_zahlen(tmp_path):
    """meta nennt Titel, Adresse, Stand, letzte Prüfung und Prüfsumme des jüngsten Plans, Quellenangabe und Lizenz; das
    Log nennt nur Zahlen, auch die nicht aufgenommenen Untereinheiten."""
    pfad = _tabelle(tmp_path)
    d = aemter.aufbau(pfad)
    assert d["meta"]["quelle"] == {"titel": aemter.TITEL, "url": "https://example.invalid/plan", "stand": "2026-11-01",
                                   "geprueft": "2026-11-13", "sha256": "0" * 64}
    assert d["meta"]["quellenangabe"] == "Stadt Köln, Geschäfts- und Dezernatsverteilungsplan, Stand 01.11.2026"
    assert "keine Lizenz angegeben" in d["meta"]["lizenz"]
    assert not re.search(r"vorlage", json.dumps({k: v for k, v in d.items() if k != "meta"}), re.I)
    assert aemter.zeile_aufbau(d, pfad) == ("Ämter (aemter.json, Stand 2026-11-01): Dezernate 2, Einheiten der Dezernate "
                                            "1, Dienststellen 2, Punktdienststellen 1, ohne Zuordnung („●“) 1, "
                                            "Untereinheiten nicht aufgenommen 2")
    assert aemter.aufbau(_tabelle(tmp_path, [], "leer.tsv")) is None


def test_tabelle_im_repository_zahlen_aus_der_tabelle():
    """An der Tabelle im Repository: je Ebene so viele Einträge, wie die Tabelle ohne „●“ führt, alle „●“ in der eigenen
    Gruppe, keine Untereinheit (Zahlen aus der Tabelle gezählt, nicht vorgegeben)."""
    plan = aemter.tabelle().neuester()
    d = aemter.aufbau()
    einheiten = [e for x in d["dezernate"] for e in x["einheiten"]]
    for ebene in aemter.EBENEN_AUFBAU:
        assert sum(e["ebene"] == ebene for e in einheiten) == sum(
            z["ebene"] == ebene and z["markierung"] != "●" for z in plan.zeilen), ebene
    assert len(d["dezernate"]) == sum(z["ebene"] == "dezernat" for z in plan.zeilen)
    assert len(d["ohne_zuordnung"]) == sum(z["markierung"] == "●" for z in plan.zeilen) > 0
    unter = {z["dienststelle"] for z in plan.zeilen if z["ebene"] == "untereinheit"}
    assert unter and not any(e["nummer"] in unter for e in einheiten + d["ohne_zuordnung"])


def test_check_aemter_ohne_befund_und_mit_eingeschleusten_abweichungen(tmp_path, monkeypatch, capsys):
    """check.aemter_aufbau: die Datei aus aemter.aufbau ohne Befund; eine Untereinheit, ein Feld mit Zahl der Vorlagen,
    ein Feld mit Personenbezug, ein Eintrag ohne Zuordnung ohne „●“ und eine fehlende Prüfung sind Befunde, nur mit
    Zahlen; ohne Freigabe ist die Datei ein Befund, ohne zeit.json wird keine erwartet."""
    base = tmp_path / "koeln"
    base.mkdir()
    (base / "zeit.json").write_text("{}")
    capsys.readouterr()
    assert check.aemter_aufbau(base) == ([], ["Ämter: " + str(base / "aemter.json") + " fehlt (`python -m pipeline "
                                              "export`)"])
    d = aemter.aufbau()
    (base / "aemter.json").write_text(json.dumps(d, ensure_ascii=False))
    assert check.aemter_aufbau(base) == ([], [])
    plan = aemter.tabelle().neuester()
    unter = next(z for z in plan.zeilen if z["ebene"] == "untereinheit")
    d["dezernate"][0]["einheiten"].append({"nummer": unter["dienststelle"], "kennung": unter["kennung"],
                                           "name": "[Testdaten] Probeabteilung", "ebene": "untereinheit"})
    d["dezernate"][1]["vorlagen"] = 12
    d["dezernate"][1]["einheiten"][0]["leitung_person"] = "[Testdaten] Name"
    d["ohne_zuordnung"][0]["markierung"] = "•"
    del d["meta"]["quelle"]["geprueft"]
    (base / "aemter.json").write_text(json.dumps(d, ensure_ascii=False))
    befunde, fehlend = check.aemter_aufbau(base)
    assert fehlend == []
    for erwartet in ("Ämter: Felder der Dezernate außerhalb von aemter.FELDER_DEZERNAT: 1",
                     "Ämter: Felder der Einträge außerhalb von aemter.FELDER_EINHEIT: 1",
                     "Ämter: Untereinheiten: 1", "Ämter: Einträge ohne Zuordnung ohne „●“: 1",
                     "Ämter: Quelle ohne Titel, Adresse, Stand oder letzte Prüfung des jüngsten Plans: 1",
                     "Ämter: Feldnamen, die auf Personen deuten: 1", "Ämter: Inhalt anders als aemter.aufbau: 1"):
        assert erwartet in befunde, (erwartet, befunde)
    assert all(re.search(r": \d+$", x) and "Testdaten" not in x for x in befunde), befunde
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", False)
    assert check.aemter_aufbau(base) == (["Ämter: aemter.json liegt vor, obwohl die Freigabe „gremien“ aus ist: 1"], [])
    monkeypatch.setitem(config.ZUSATZTHEMEN, "gremien", True)
    (base / "zeit.json").unlink()
    (base / "aemter.json").unlink()
    assert check.aemter_aufbau(base) == ([], [])


def test_meta_vermerkt_kennung_des_projekts(tmp_path):
    """Entscheidung 21.11.2026 (3) (G5): `meta.note` vermerkt, dass das Feld `kennung` vom Projekt aus Dezernat und
    Nummer gebildet ist und keine Schreibweise des Plans; die Kennungen folgen dieser Regel (erfundene Tabelle)."""
    d = aemter.aufbau(_tabelle(tmp_path))
    assert d["meta"]["note"].endswith(" " + aemter.NOTE_KENNUNG)
    assert "„kennung“ bildet das Projekt aus Dezernat und Nummer" in d["meta"]["note"]
    assert "keine Schreibweise des Plans" in d["meta"]["note"]
    vi = d["dezernate"][0]
    assert vi["kennung"] == "VI" and [e["kennung"] for e in vi["einheiten"]] == ["VI/VI/1", "VI/61", "VI/6100"]
