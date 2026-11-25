"""tools/themen_pruefbogen.py: Prüfbogen einer Themenseite aus einem entpackten Datenpaket oder, als Rückfall, aus
suche.json, gremien.json und index.json (Entscheidung 24.11.2026 (3); Plan „pruefbogen_methode“, Antworten vom
25.11.2026). Ohne Netz und ohne Datenbank; Ausgabe nur außerhalb jedes Git-Checkouts; laufende Nummer statt Drucksache,
<DS> in Titel und Grund, Eingaben ohne Titel, Titel mit Personenbezug vor der Ziehung aussortiert und nur gezählt,
Ziehung mit random.Random(2026). Alle Vorlagen, Drucksachen und Gremien sind erfunden; keine Anfragen nach außen."""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import config, dossier

ROOT = Path(__file__).resolve().parents[1]
WERKZEUG = ROOT / "tools" / "themen_pruefbogen.py"
TOTER_PROXY = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
               "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
MOB = ("mob-1a2b3c4d", "Mobilitätsausschuss")
BV = ("bv1", "Bezirksvertretung 1 (Innenstadt)")


def _gremien():
    return {"meta": {"datenstand": "2026-11-21", "zeitraum": {"seit": "2025-11-21", "bis": "2026-11-21"}},
            "gremien": [{"key": "rat", "name": "Rat", "gruppe": "rat"},
                        {"key": MOB[0], "name": MOB[1], "gruppe": "ausschuss", "paragraf": 17},
                        {"key": BV[0], "name": BV[1], "gruppe": "bezirksvertretung"}]}


def _station(gremium, tag="2026-04-01", result=None):
    return {"gremium_key": gremium[0], "gremium": gremium[1], "start_date": f"{tag}T16:00:00+01:00", "cancelled": 0,
            "result": result}


def _vorlage(ref, titel, art="Beschlussvorlage", stationen=(), sup=(), sub=(), tag="2026-03-02"):
    return {"reference": ref, "name": f"[Testdaten] {titel}", "date": tag, "paper_type": art,
            "web": f"https://example.invalid/vorlage/{ref.replace('/', '-')}", "stand": "in Beratung",
            "process": list(stationen), "superordinated": [{"reference": r} for r in sup],
            "subordinated": [{"reference": r} for r in sub], "locations": [],
            "source_object": "https://example.invalid/oparl/papers/" + ref.replace("/", "-")}


VORLAGEN = [
    _vorlage("1/2026", "Radweg an der Probestraße", stationen=[_station(BV)]),
    _vorlage("2/2026", "Radweg an der Probeallee", art="Anregungen und Beschwerden", stationen=[_station(BV)]),
    _vorlage("3/2026", "Taktverdichtung der Linie 13", stationen=[_station(MOB)], sub=["4/2026"]),
    _vorlage("4/2026", "Änderung zu 3/2026", art="Änderungsantrag", stationen=[_station(MOB)], sup=["3/2026"]),
    _vorlage("5/2026", "Bewohnerparken in Probestadt", stationen=[_station(BV)]),
    _vorlage("6/2026", "Tempo 30 vor der Grundschule", stationen=[_station(BV)]),
    _vorlage("7/2026", "Sanierung der Probebrücke", stationen=[_station(BV)]),
    _vorlage("8/2026", "Sachstandsbericht der Verwaltung", art="Mitteilung", stationen=[_station(MOB)]),
    _vorlage("9/2026", "Nachbesetzung eines Mitglieds im Mobilitätsausschuss", stationen=[_station(MOB)]),
    _vorlage("10/2026", "Stadtpark: Pflege", stationen=[_station(BV)]),
    _vorlage("11/2026", "Kita-Neubau in Probestadt", stationen=[_station(BV)]),
]


def _paket(ordner):
    """Entpacktes Datenpaket wie ratsatlas-koeln-export.zip (nur die gelesenen Dateien); 1/2026 steht in zwei
    Gebietsdateien (Stadtteil und Stadtbezirk), wie im Export."""
    base = ordner / "ratsatlas-koeln" / "koeln"
    for d in ("ortsteile", "bezirke", "ohne-ortsbezug"):
        (base / d).mkdir(parents=True)
    (base / "ortsteile" / "probestadt.json").write_text(json.dumps({"papers": VORLAGEN[:6]}), encoding="utf-8")
    (base / "bezirke" / "innenstadt.json").write_text(json.dumps({"papers": [VORLAGEN[0], *VORLAGEN[6:9]]}), encoding="utf-8")
    (base / "ohne-ortsbezug" / "ganz-koeln.json").write_text(json.dumps({"papers": VORLAGEN[9:]}), encoding="utf-8")
    (base / "gremien.json").write_text(json.dumps(_gremien()), encoding="utf-8")
    (base / "zeit.json").write_text(json.dumps({"terms": [{"start": "2025-11-01", "end": None}]}), encoding="utf-8")
    return ordner


def _lauf(quelle, ziel, cwd):
    """Wie im Plan: python -I tools/themen_pruefbogen.py <Ordner> verkehr <Ausgabe>, ohne Netz (toter Proxy)."""
    env = {k: v for k, v in os.environ.items() if k != config.THEMEN_PRUEFUNG}
    env.update(TOTER_PROXY)
    return subprocess.run([sys.executable, "-I", str(WERKZEUG), str(quelle), "verkehr", str(ziel)], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


def _tsv(pfad):
    with pfad.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


def test_pruefbogen_aus_dem_paket(tmp_path):
    """Jede Vorlage einmal (nach source_object), laufende Nummer statt Drucksache, <DS> im Titel und im Grund
    (Folgevorlage), Eingaben ohne Titel, Titel mit Personenbezug aussortiert und gezählt, Gegenprobe mit
    Kandidatenwort; die Schlüsseldatei nennt Drucksache und Link je Nummer; nur die drei Dateien im Ausgabeordner."""
    quelle, ziel = _paket(tmp_path / "paket"), tmp_path / "bogen"
    r = _lauf(quelle, ziel, tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    assert sorted(p.name for p in ziel.iterdir()) == ["pruefbogen_verkehr.tsv", "schluessel_verkehr.tsv", "zahlen_verkehr.tsv"]
    bogen = _tsv(ziel / "pruefbogen_verkehr.tsv")
    assert bogen[0] == dossier.SPALTEN_PRUEFBOGEN
    zeilen = [dict(zip(bogen[0], z)) for z in bogen[1:]]
    schluessel = {z[0]: z[1:] for z in _tsv(ziel / "schluessel_verkehr.tsv")[1:]}
    assert [z["nr"] for z in zeilen] == [str(i) for i in range(1, len(zeilen) + 1)] == list(schluessel)
    refs = [schluessel[z["nr"]][0] for z in zeilen]
    assert len(refs) == len(set(refs)), refs                                   # jede Vorlage höchstens einmal
    text = (ziel / "pruefbogen_verkehr.tsv").read_text(encoding="utf-8")
    assert not [v["reference"] for v in VORLAGEN if v["reference"] in text]     # keine Drucksache im Bogen
    assert all(schluessel[z["nr"]][1] == f"https://example.invalid/vorlage/{schluessel[z['nr']][0].replace('/', '-')}"
               for z in zeilen)
    je = {schluessel[z["nr"]][0]: z for z in zeilen}
    # Folgevorlage: erbt den Strang, Grund und Titel mit <DS>
    assert je["4/2026"]["strang"] == "Bus und Bahn" and je["4/2026"]["grund"] == "Folgevorlage zu <DS>"
    assert je["4/2026"]["titel"] == "[Testdaten] Änderung zu <DS>"
    # Eingabe nach § 24 GO: ohne Titel, mit Art, Strang und Gremien
    assert je["2/2026"]["titel"] == "" and je["2/2026"]["vorlagenart"] == "Anregungen und Beschwerden"
    assert je["2/2026"]["strang"] == "Rad- und Fußverkehr" and je["2/2026"]["beratende_gremien"] == BV[1]
    assert je["1/2026"]["titel"] == "[Testdaten] Radweg an der Probestraße" and je["1/2026"]["monat"] == "2026-03"
    # nur über das Gremium (Mobilitätsausschuss); Gegenprobe mit Kandidatenwort; Personenbezug nie im Bogen
    assert je["8/2026"]["grund"] == "Beratung im Mobilitätsausschuss"
    assert je["10/2026"]["strang"] == "nicht zugeordnet (Gegenprobe)" and je["10/2026"]["grund"] == "—"
    assert "9/2026" not in je and "11/2026" not in je and "Nachbesetzung" not in text
    zahlen = {(z[0], z[1]): z[2] for z in _tsv(ziel / "zahlen_verkehr.tsv")[1:]}
    assert zahlen[("aussortiert", "Titel mit Personenbezug")] == "1"
    assert zahlen[("grund", "Folgevorlage")] == "1" and zahlen[("strang", "Bus und Bahn")] == "2"
    assert zahlen[("gegenprobe", "Kandidaten ohne Zuordnung")] == "1"
    assert not any(k[0] == "hinweis" for k in zahlen)


def test_ziehung_wiederholbar(tmp_path):
    """Gleiche Quelle, gleiche Ziehung (random.Random(2026)): zwei Läufe ergeben dieselben Dateien."""
    quelle = _paket(tmp_path / "paket")
    for ziel in ("a", "b"):
        assert _lauf(quelle, tmp_path / ziel, tmp_path).returncode == 0
    for name in ("pruefbogen_verkehr.tsv", "schluessel_verkehr.tsv", "zahlen_verkehr.tsv"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_ausgabe_nie_im_repository(tmp_path):
    """Ein Ausgabeordner im Repository (etwa data/export, das auf die Seite und ins Paket käme) bricht ab, ohne zu
    schreiben."""
    quelle = _paket(tmp_path / "paket")
    ziel = ROOT / "data" / "export" / "_pruefbogen_test_nie_anlegen"
    r = _lauf(quelle, ziel, tmp_path)
    assert r.returncode != 0 and "außerhalb jedes Git-Checkouts" in r.stderr + r.stdout
    assert not ziel.exists()


@pytest.mark.parametrize("git", ["ordner", "datei"])
def test_ausgabe_nie_in_einem_anderen_checkout(tmp_path, git):
    """Auch nicht in einem anderen Checkout oder Worktree (Ordner oder Datei .git in einem übergeordneten Ordner, etwa
    der Haupt-Checkout, wenn das Werkzeug aus einem Worktree läuft): Abbruch ohne zu schreiben."""
    quelle = _paket(tmp_path / "paket")
    checkout = tmp_path / "anderer-checkout"
    checkout.mkdir()
    if git == "ordner":
        (checkout / ".git").mkdir()
    else:
        (checkout / ".git").write_text("gitdir: /anderswo\n", encoding="utf-8")
    ziel = checkout / "data" / "pb"
    r = _lauf(quelle, ziel, tmp_path)
    assert r.returncode != 0 and "außerhalb jedes Git-Checkouts" in r.stderr + r.stdout
    assert not ziel.exists()
    with pytest.raises(SystemExit):
        dossier.in_keinem_checkout(checkout)
    assert dossier.in_keinem_checkout(tmp_path / "frei" / "pb") == (tmp_path / "frei" / "pb").resolve()


# Titel mit Personenbezug (Namen erfunden): nie mit Text im Bogen, nur gezählt (Prüfung der Daten, 25.11.2026)
PERSONEN = ["Abberufung von Erika Beispiel als Geschäftsführerin der KVB", "Ernennung von Max Beispielmann zum Verkehrsbeauftragten",
            "Wiederwahl der Beigeordneten für Mobilität", "Wahlen zum Mobilitätsausschuss", "Neuwahl im Radverkehrsbeirat",
            "Wahlvorschlag für den Aufsichtsrat der KVB", "Berufung in den Fahrgastbeirat", "Nachruf auf einen Ehrenbürger",
            "Jubiläum der Linie 13", "Vorsitz im Verkehrsbeirat"]


@pytest.mark.parametrize("titel", PERSONEN)
def test_personenbezug_erkannt(titel):
    assert dossier.PERSONENBEZUG.search(titel), titel


def test_personenbezug_nie_im_bogen(tmp_path):
    """Titel mit Personenbezug, auch solche mit Verkehrswort und Strang, stehen nie im Bogen, auch nicht in der
    Gegenprobe; gezählt werden sie."""
    vorlagen = [_vorlage(f"{20 + i}/2026", t, stationen=[_station(MOB)]) for i, t in enumerate(PERSONEN)]
    vorlagen.append(_vorlage("40/2026", "Radweg an der Probestraße", stationen=[_station(BV)]))
    papiere = {v["source_object"]: v for v in vorlagen}
    ziel = tmp_path / "bogen"
    bogen = dossier.stichprobe(dossier_thema(), papiere, _gremien(), ziel, [{"start": "2025-11-01"}])
    text = (ziel / "pruefbogen_verkehr.tsv").read_text(encoding="utf-8")
    assert len(bogen) == 1 and "Radweg" in text
    for t in PERSONEN:
        assert t not in text
    for wort in ("Beispiel", "Wahl", "Ernennung", "Abberufung", "Nachruf", "Jubiläum", "Vorsitz"):
        assert wort not in text, wort
    zahlen = {(z[0], z[1]): z[2] for z in _tsv(ziel / "zahlen_verkehr.tsv")[1:]}
    assert zahlen[("aussortiert", "Titel mit Personenbezug")] == str(len(PERSONEN))


def dossier_thema():
    from pipeline.themenseiten import verkehr
    return verkehr.THEMA


def test_rueckfall_aus_drei_dateien(tmp_path):
    """Ohne Gebietsdateien: suche.json, gremien.json und index.json; Vorgänge ohne Beziehungen, daher keine
    Folgevorlagen; die Zählzeilen sagen das."""
    quelle = tmp_path / "einzeln"
    quelle.mkdir()
    typen = sorted({v["paper_type"] for v in VORLAGEN})
    namen, keys = [MOB[1], BV[1]], [BV[0], MOB[0]]
    zeilen = []
    for v in VORLAGEN:
        g = sorted({namen.index(s["gremium"]) for s in v["process"]})
        k = sorted({keys.index(s["gremium_key"]) for s in v["process"]})
        zeilen.append([v["reference"], v["name"], v["date"], typen.index(v["paper_type"]), 0, -1, [], [], [], -1, g, k])
    (quelle / "suche.json").write_text(json.dumps({"types": typen, "gremien": namen, "gremium_keys": keys, "rows": zeilen}),
                                       encoding="utf-8")
    (quelle / "gremien.json").write_text(json.dumps(_gremien()), encoding="utf-8")
    (quelle / "index.json").write_text(json.dumps({"generated_at": "2026-11-21T03:00:00+00:00"}), encoding="utf-8")
    ziel = tmp_path / "bogen"
    r = _lauf(quelle, ziel, tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    zahlen = _tsv(ziel / "zahlen_verkehr.tsv")
    assert any(z[0] == "hinweis" and "Folgevorlagen nicht prüfbar" in z[1] for z in zahlen)
    assert not [z for z in zahlen if z[:2] == ["grund", "Folgevorlage"] and z[2] != "0"]
    text = (ziel / "pruefbogen_verkehr.tsv").read_text(encoding="utf-8")
    assert not [v["reference"] for v in VORLAGEN if v["reference"] in text] and "Nachbesetzung" not in text


def test_ohne_netz_und_ohne_datenbank():
    """Das Werkzeug liest nur Dateien: kein Abruf (abruf, dienste, urllib, requests, socket) und keine Datenbank."""
    code = WERKZEUG.read_text(encoding="utf-8")
    for verboten in ("import abruf", "dienste", "urllib", "requests", "socket", "sqlite3", "db.connect", "http"):
        assert verboten not in code.replace("https://", ""), verboten


@pytest.mark.parametrize("argumente", [[], ["a", "b"], ["a", "kein-thema", "c"]])
def test_aufruf_falsch(tmp_path, argumente):
    """Falsche Zahl der Angaben oder ein unbekanntes Thema: Abbruch mit Hinweis, keine Ausgabe."""
    env = {**os.environ, **TOTER_PROXY}
    if argumente == ["a", "kein-thema", "c"]:
        argumente = [str(_paket(tmp_path / "paket")), "kein-thema", str(tmp_path / "c")]
    r = subprocess.run([sys.executable, "-I", str(WERKZEUG), *argumente], cwd=tmp_path, env=env, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode != 0 and not (tmp_path / "c").exists()
