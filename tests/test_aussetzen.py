"""Aussetzen einer Liste nach einem fortgesetzten Vollabruf unter 90 % des Stands (Entscheidung des Auftraggebers vom
13.11.2026, pipeline/sessionnet.py): gegen den lokalen OParl-Testserver (127.0.0.1), mit erfundenen Vorlagen und
Sitzungen. Dazu: Nächte ohne kurze Liste senden dieselben Anfragen und hinterlassen denselben Zustand wie 78de995
(Prüfsummen mit jenem Stand erzeugt), Export und Seite nennen das Aussetzen."""
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipeline import abruf, build, config, sessionnet


def _zustand():
    return json.loads(config.ZUSTAND.read_text(encoding="utf-8"))


def _stand():
    return json.loads(config.STAND.read_text(encoding="utf-8"))


def _zeile(liste):
    with open(config.ABRUFSTATISTIK, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f, delimiter="\t") if r["liste"] == liste][-1]


def _anfragen(oparl, pfad):
    """Anfragen an eine Liste: (Seite, mit modified_since)."""
    return [(q.get("page", "1"), "modified_since" in q) for p, q, _ in oparl.anfragen if p == pfad]


def _fenster_vor(monkeypatch, pfad, seite):
    """Das Zeitfenster endet vor Seite `seite` der Liste `pfad` (einmal, ohne Anfrage); liefert die echte Funktion."""
    echt, einmal = abruf.get_json, []

    def get_json(url, pausen=None):
        if pfad in url and f"page={seite}" in url and not einmal:
            einmal.append(url)
            raise abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster")
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", get_json)
    return echt


# --- Nächte ohne kurze Liste wie 78de995 -------------------------------------------------------------------------------

START = datetime(2026, 11, 13, 22, 15, tzinfo=timezone.utc)


class _Naechte:
    """Abrufnächte mit fester Uhr (abruf.uhr, sessionnet._now und datetime.now in sessionnet), je Nacht eine
    Prüfsumme über Anfragen (Pfad und Query-Teil roh), alle Dateien in data/raw (zustand_abruf.json, STAND.json,
    Rohdaten, Teildateien) und die Abrufstatistik ohne die Spalten `bytes` und `sekunden` (Port des Testservers,
    Laufzeit); die Adresse des Testservers ist durch BASE ersetzt."""

    def __init__(self, oparl, monkeypatch):
        self.oparl, self.mp, self.summen, self.t = oparl, monkeypatch, [], START
        uhr = self

        class Fest(datetime):
            @classmethod
            def now(cls, tz=None):
                return uhr.t if tz else uhr.t.replace(tzinfo=None)
        monkeypatch.setattr(abruf, "uhr", lambda: uhr.t)
        monkeypatch.setattr(sessionnet, "_now", lambda: uhr.t.isoformat(timespec="seconds"))
        monkeypatch.setattr(sessionnet, "datetime", Fest)
        self.echt = abruf.get_json

    def nacht(self, vorbereiten=None, **umgebung):
        self.mp.setattr(abruf, "get_json", self.echt)
        for k in ("RATSATLAS_VOLLABRUF", "RATSATLAS_KUERZER_ANNEHMEN"):
            self.mp.delenv(k, raising=False)
        for k, v in umgebung.items():
            self.mp.setenv(k, v)
        if vorbereiten:
            vorbereiten()
        self.oparl.roh.clear()
        sessionnet.fetch_all()
        teile = [p + ("?" + q if q else "") for p, q in self.oparl.roh]
        teile += [f"{f.name}\n{f.read_text(encoding='utf-8')}" for f in sorted(config.RAW.iterdir()) if f.is_file()]
        for zeile in config.ABRUFSTATISTIK.read_text(encoding="utf-8").splitlines():
            spalten = zeile.split("\t")
            teile.append("\t".join(spalten[:14] + spalten[16:]))
        text = "\n\0".join(teile).replace(self.oparl.b, "BASE")
        self.summen.append(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])
        self.t += timedelta(days=1)

    def fenster_vor(self, pfad, seite):
        return lambda: _fenster_vor(self.mp, pfad, seite)


def _sitzungen(oparl, anzahl):
    m = oparl.meetings[-1]
    return [dict(m, id=f"{oparl.b}/meetings/{i}", name=f"Sitzung {i}") for i in range(2, anzahl + 1)] + [m]


def _ohne_zeitfilter(oparl, monkeypatch, *pfade):
    """Der Server übergeht modified_since für diese Listen; liefert die echte Liste zurück."""
    echt = oparl.liste

    def liste(objekte, pfad, q, groesse=None):
        if pfad in pfade:
            q = {k: v for k, v in q.items() if k != "modified_since"}
        return echt(objekte, pfad, q, groesse)
    monkeypatch.setattr(oparl, "liste", liste)
    return echt


def _koeln(oparl, monkeypatch):
    oparl.form, oparl.limit_wirkt = "koeln", True
    monkeypatch.setattr(config, "ABRUF_SEITENGROESSE", "3")
    oparl.papers = [oparl.paper(i) for i in range(1, 9)]
    oparl.meetings = _sitzungen(oparl, 7)


def _fall_vollabrufnaechte(n, oparl, mp):
    """Vollabruf über Nächte (Fenster in Vorlagen und Sitzungen), Fortsetzungen, RATSATLAS_VOLLABRUF=meetings mit
    Vermerk aus älterem Code, =ja, Obergrenze je Lauf, Fortsetzung, =papers."""
    _koeln(oparl, mp)

    def grenze():
        mp.setattr(config, "ABRUF_MAX_OBJEKTE", 6)
        mp.setattr(sessionnet, "max_objekte_mindestens", lambda: 6)
    n.nacht(n.fenster_vor("/papers", 2))
    n.nacht(n.fenster_vor("/meetings", 2))
    n.nacht()
    n.nacht(lambda: sessionnet._zustand_setzen("meetings_ohne_zeitfilter", {"zeit": "2026-11-11T22:16:40+00:00",
                                                                            "meldung": "alt"}),
            RATSATLAS_VOLLABRUF="meetings")
    n.nacht(RATSATLAS_VOLLABRUF="ja")
    n.nacht(grenze, RATSATLAS_VOLLABRUF="meetings")
    n.nacht()
    n.nacht(RATSATLAS_VOLLABRUF="papers")


def _fall_sitzungen_ohne_zeitfilter(n, oparl, mp):
    """Sitzungen ohne angewandten Zeitfilter jede Nacht vollständig (eine neue Sitzung, Fenster mitten im Lesen,
    Fortsetzung), danach wirkt der Filter wieder."""
    _koeln(oparl, mp)
    n.nacht()
    echt = _ohne_zeitfilter(oparl, mp, "/meetings")
    n.nacht()
    oparl.meetings = oparl.meetings + [dict(oparl.meetings[0], id=f"{oparl.b}/meetings/20")]
    n.nacht()
    n.nacht(n.fenster_vor("/meetings", 2))
    n.nacht()
    mp.setattr(oparl, "liste", echt)
    n.nacht()


def _fall_organisationen(n, oparl, mp):
    """Organisationen unter 90 % (Warnung), mit RATSATLAS_KUERZER_ANNEHMEN angenommen, wieder vollständig."""
    alle = oparl.orgs + [dict(oparl.orgs[1], id=f"{oparl.b}/organizations/{i}", name=f"Gremium {i}") for i in range(8)]
    oparl.orgs = list(alle)
    n.nacht()
    oparl.orgs = alle[:8]
    n.nacht()
    n.nacht(RATSATLAS_KUERZER_ANNEHMEN="organizations")
    oparl.orgs = alle
    n.nacht()


def _fall_filter_und_sperre(n, oparl, mp):
    """Zeitfilter der Vorlagen nicht angewandt (Listenfehler), HTTP 401 bei den Sitzungen, wieder vollständig."""
    n.nacht()
    echt = _ohne_zeitfilter(oparl, mp, "/papers")
    n.nacht()
    mp.setattr(oparl, "liste", echt)
    mp.setattr(oparl, "stoerung", lambda pfad, q: 401 if pfad == "/meetings" else False)
    n.nacht()
    mp.setattr(oparl, "stoerung", lambda pfad, q: False)
    n.nacht()


def _fall_kuerzer_fortgesetzt_angenommen(n, oparl, mp):
    """Kürzere Vorlagen in einem fortgesetzten Vollabruf mit RATSATLAS_KUERZER_ANNEHMEN angenommen (wie bisher)."""
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    n.nacht()
    oparl.papers = oparl.papers[:8]
    n.nacht(n.fenster_vor("/papers", 3), RATSATLAS_VOLLABRUF="papers")
    n.nacht(RATSATLAS_KUERZER_ANNEHMEN="papers")
    n.nacht()


def _fall_vollabruf_einer_nacht_kuerzer(n, oparl, mp):
    """Ein Vollabruf, der in derselben Nacht beginnt und endet (RATSATLAS_VOLLABRUF), unter 90 %: Abbruch `leer` wie
    bisher, auch zweimal; ohne die Einstellung wieder inkrementell."""
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    n.nacht()
    oparl.papers = oparl.papers[:8]
    n.nacht(RATSATLAS_VOLLABRUF="papers")
    n.nacht(RATSATLAS_VOLLABRUF="papers")
    n.nacht()
    n.nacht(RATSATLAS_VOLLABRUF="meetings")


def _fall_leer_nie_angenommen(n, oparl, mp):
    """Vollabruf nur mit gelöschten Vorlagen und RATSATLAS_KUERZER_ANNEHMEN: nie angenommen, Abbruch wie bisher."""
    n.nacht()
    echt = list(oparl.papers)
    oparl.papers = [dict(p, deleted=True) for p in oparl.papers]
    n.nacht(RATSATLAS_VOLLABRUF="papers", RATSATLAS_KUERZER_ANNEHMEN="papers")
    oparl.papers = echt
    n.nacht()


# Prüfsummen je Nacht, erzeugt mit demselben Test gegen den Stand 78de995 (vor dem Aussetzen)
WIE_78DE995 = {
    _fall_vollabrufnaechte: [
        "4b2fcacbf0e4afd0", "36535072f089f096", "d0037e659ed13bf4", "6957eb055eb7c6e0", "4f01c60c52f700eb",
        "2dfc31af82493d3f", "4f5fb8468e68d061", "2f2efe6bd37c54ab"
    ],
    _fall_sitzungen_ohne_zeitfilter: [
        "02224142f3cc1e3c", "4f6ebfc6008d328f", "6639ccce601424d5", "b84f7b3078a13fe1", "30fb4a730bcf4bae",
        "26280f3746621549"
    ],
    _fall_organisationen: ["ea4386f3843b5a3f", "e0645442b2996d3a", "6836a27420280b26", "265e84c6604a3447"],
    _fall_filter_und_sperre: ["b998794c220d3693", "ff4b93e9dfbd8083", "c50521c41dd30a7c", "e148379ad957c4b2"],
    _fall_kuerzer_fortgesetzt_angenommen: [
        "6090639c4cda4ab5", "6eea281e9f1af3c0", "7e54f72c6e0f926e", "5050082d6733112c"
    ],
    _fall_vollabruf_einer_nacht_kuerzer: [
        "6090639c4cda4ab5", "0f179e7126a25dc7", "381b0755435748ec", "17fba264c11ffbcb", "8ab923bd400a3ec3"
    ],
    _fall_leer_nie_angenommen: ["b998794c220d3693", "a2cae88263423e03", "1056a4b622bb0580"],
}


@pytest.mark.parametrize("fall", list(WIE_78DE995), ids=lambda f: f.__name__.removeprefix("_fall_"))
def test_naechte_ohne_aussetzen_wie_78de995(oparl, monkeypatch, fall):
    """Nächte, in denen keine Liste aussetzt, senden dieselben Anfragen in derselben Reihenfolge und hinterlassen
    byte-gleich denselben Zustand, dieselbe STAND.json, dieselben Rohdaten und dieselbe Abrufstatistik wie 78de995
    (Stand des ersten Vollabrufs aus GitHub Actions; dieser Zweig wird erst nach ihm zusammengeführt). Dazu gehören ein
    Vollabruf über Nächte mit Fortsetzungen, RATSATLAS_VOLLABRUF, die Sitzungen ohne Zeitfilter, die Warnung der
    Organisationen, Listenfehler und Sperrnacht, ein mit RATSATLAS_KUERZER_ANNEHMEN angenommener kürzerer Stand und
    ein Vollabruf, der in derselben Nacht unter 90 % endet (Abbruch wie bisher: er wiederholt sich nicht von selbst)."""
    n = _Naechte(oparl, monkeypatch)
    fall(n, oparl, monkeypatch)
    assert n.summen == WIE_78DE995[fall]


# --- Aussetzen der Vorlagen nach einem fortgesetzten Vollabruf unter 90 % --------------------------------------------

def _jsonl(pfad):
    return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]


def _vorlagen_ausgesetzt(oparl, monkeypatch):
    """Nacht 0: 10 Vorlagen vollständig (5 Seiten zu 2). Nacht 1: RATSATLAS_VOLLABRUF=papers, die Stadt liefert nur
    noch 8, das Zeitfenster endet vor Seite 3 (Fortsetzung ab Seite 2). Nacht 2: die Fortsetzung liest bis zum Ende,
    8 von 10, die Vorlagen setzen aus. Liefert (Rohdaten der Vorlagen nach Nacht 0, Zeitpunkt der Vorlagen in
    STAND.json, Fortsetzung)."""
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    sessionnet.fetch_all()
    zeit = "2026-11-12T22:20:00+00:00"                                    # Zeitpunkt der Vorlagen, unterscheidbar
    sessionnet._stand_setzen(papers=zeit)
    roh = config.PAPERS.read_bytes()
    oparl.papers = oparl.papers[:8]
    echt = _fenster_vor(monkeypatch, "/papers", 3)
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/papers") == [("1", False), ("2", False)]
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    monkeypatch.setattr(abruf, "get_json", echt)
    fort = _zustand()["papers_fortsetzung"]
    assert fort["seiten"] == 2 and "page=2" in fort["naechste"]
    sessionnet._stand_setzen(abruf_ok="2026-11-01T00:00:00+00:00")       # erkennbar, ob der Lauf ihn erneuert
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    return roh, zeit, fort


def test_fortgesetzter_vollabruf_der_vorlagen_setzt_aus(oparl, monkeypatch, capsys):
    """Endet ein fortgesetzter Vollabruf der Vorlagen unter 90 % des Stands (8 von 10, ohne
    RATSATLAS_KUERZER_ANNEHMEN), setzt die Liste aus (Entscheidung 13.11.2026), statt jede Nacht die Fortsetzung bis zum
    Listenende zu lesen und abzubrechen: letzter gültiger Stand (Rohdaten und Zeitpunkt unverändert), Fortsetzung und
    Teildatei bleiben, Eintrag mit Zeit, Zahlen, Anlass und Abhilfe in Zustand und STAND.json, Warnung im Log, Zeile in
    der Abrufstatistik. Kein Abbruch: Sitzungen und Beratungen laufen in derselben Nacht, `abruf_ok` wird erneuert, kein
    Fehler, kein Listenfehler, keine 12-Stunden-Regel. In den Folgenächten keine Anfrage an die Vorlagen (eine Änderung
    der Stadt kommt nicht an); der Hinweis am Ende des Zeitfensters zählt die Fortsetzung der ausgesetzten Liste nicht.
    RATSATLAS_KUERZER_ANNEHMEN=papers setzt die Fortsetzung fort, nimmt den kürzeren Stand an und beendet das
    Aussetzen; danach wieder inkrementell."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    capsys.readouterr()
    roh, zeit, fort = _vorlagen_ausgesetzt(oparl, monkeypatch)
    # Nacht 2: Fortsetzung ab Seite 2 bis zum Ende, Aussetzen, die Sitzungen laufen weiter
    assert _anfragen(oparl, "/papers") == [("2", False), ("3", False), ("4", False)]
    assert _anfragen(oparl, "/meetings") == [("1", True)]
    zustand, stand = _zustand(), _stand()
    a = zustand["papers_ausgesetzt"]
    assert (a["objekte"], a["bisher"], a["anlass"]) == (8, 10, "fortgesetzter Vollabruf") and sessionnet._zeit(a["seit"])
    assert a["meldung"].startswith("Vorlagen ausgesetzt (fortgesetzter Vollabruf unter 90 % des Stands): papers.jsonl: "
                                   "nur 8 statt bisher 10 – unvollständige Antwort? Vorhandener Stand bleibt. Keine "
                                   "Anfrage an diese Liste")
    assert "RATSATLAS_KUERZER_ANNEHMEN=papers" in a["meldung"] and "RATSATLAS_VOLLABRUF=papers" in a["meldung"]
    assert zustand["papers_fortsetzung"] == fort and (config.RAW / "papers.teil.jsonl").exists()
    assert not {"letzter_abbruch", "listenfehler", "sperre_verdacht"} & set(zustand)
    assert config.PAPERS.read_bytes() == roh and stand["papers"] == zeit
    assert stand["abruf_ausgesetzt"] == {"papers": a}
    assert not {"abruf_fehler", "abruf_hinweis"} & set(stand) and stand["abruf_ok"] != "2026-11-01T00:00:00+00:00"
    z = _zeile("papers")
    assert (z["modus"], z["seiten"], z["objekte"], z["anfragen"]) == ("voll, fortgesetzt", "5", "8", "3")
    assert z["ergebnis"].startswith("ausgesetzt: Vorlagen ausgesetzt (fortgesetzter Vollabruf")
    assert _zeile("meetings")["ergebnis"] == "ok" and len(_jsonl(config.BERATUNGEN)) == 10
    assert "Warnung: Vorlagen ausgesetzt (fortgesetzter Vollabruf" in capsys.readouterr().err
    # Nacht 3: eine Vorlage geändert, das Zeitfenster endet vor den Sitzungen; keine Anfrage an die Vorlagen
    oparl.papers[0] = dict(oparl.papers[0], name="geändert", modified=datetime.now(timezone.utc).isoformat())
    echt = abruf.get_json

    def ende_vor_sitzungen(url, pausen=None):
        if "/meetings" in url:
            raise abruf.Abbruch("außerhalb des Zeitfensters 23-1 Uhr", "zeitfenster")
        return echt(url, pausen)
    monkeypatch.setattr(abruf, "get_json", ende_vor_sitzungen)
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    monkeypatch.setattr(abruf, "get_json", echt)
    assert _anfragen(oparl, "/papers") == [] and config.PAPERS.read_bytes() == roh
    hinweis = _stand()["abruf_hinweis"]["meldung"]
    assert "der inkrementelle Abruf beginnt in der nächsten Nacht erneut" in hinweis
    assert "Fortsetzung in der nächsten Nacht" not in hinweis
    z = _zeile("papers")
    assert (z["modus"], z["seiten"], z["objekte"], z["anfragen"]) == ("ausgesetzt", "0", "10", "0")
    assert z["ergebnis"].startswith(f"ausgesetzt: papers: Abruf ausgesetzt seit {a['seit']} (fortgesetzter Vollabruf: 8 "
                                    "statt bisher 10); keine Anfrage, letzter gültiger Stand bleibt – Abhilfe: ")
    assert "Warnung: papers: Abruf ausgesetzt seit" in capsys.readouterr().err
    # Nacht 4: weiter ohne Anfrage an die Vorlagen, der Lauf ist vollständig
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/papers") == [] and _anfragen(oparl, "/meetings") == [("1", True)]
    assert _zustand()["papers_ausgesetzt"] == a and _stand()["abruf_ausgesetzt"] == {"papers": a}
    assert "abruf_hinweis" not in _stand() and config.PAPERS.read_bytes() == roh and _stand()["papers"] == zeit
    # Nacht 5: RATSATLAS_KUERZER_ANNEHMEN=papers: Fortsetzung ab Seite 2, kürzerer Stand angenommen, Aussetzen endet
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "papers")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/papers") == [("2", False), ("3", False), ("4", False)]
    assert len(_jsonl(config.PAPERS)) == 8 and len(_jsonl(config.BERATUNGEN)) == 8
    zustand, stand = _zustand(), _stand()
    assert not {"papers_ausgesetzt", "papers_fortsetzung", sessionnet.KUERZER_VERMERK} & set(zustand)
    assert zustand["papers"] == fort["start"] and not (config.RAW / "papers.teil.jsonl").exists()
    assert "abruf_ausgesetzt" not in stand and stand["papers"] != zeit
    assert _zeile("papers")["ergebnis"] == (
        f"ok; kürzerer Stand angenommen: 8 statt bisher 10 (RATSATLAS_KUERZER_ANNEHMEN); Aussetzen seit {a['seit']} "
        "(fortgesetzter Vollabruf: 8 statt bisher 10) aufgehoben (RATSATLAS_KUERZER_ANNEHMEN)")
    # Nacht 6: wieder inkrementell, die Änderung aus Nacht 3 kommt an
    monkeypatch.delenv("RATSATLAS_KUERZER_ANNEHMEN")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/papers") == [("1", True)]
    assert sum(p["name"] == "geändert" for p in _jsonl(config.PAPERS)) == 1


@pytest.mark.parametrize("fall", ["wieder vollständig", "kürzer über zwei Nächte", "kürzer in einer Nacht"])
def test_vollabruf_hebt_das_aussetzen_auf(oparl, monkeypatch, capsys, fall):
    """RATSATLAS_VOLLABRUF=papers hebt das Aussetzen vor der ersten Anfrage auf, verwirft die alte Fortsetzung und
    beginnt einen neuen Vollabruf ab Seite 1. Liefert die Stadt wieder alle Vorlagen, gilt der neue Stand. Ist die Liste
    weiter kürzer, gilt die Regel erneut: über zwei Nächte fortgesetzt setzt sie wieder aus (die Fortsetzung braucht die
    Einstellung nicht); in derselben Nacht fertig bricht der Lauf wie bisher ab (Art `leer`, kein Aussetzen), und die
    nächste Nacht läuft ohne die Einstellung inkrementell."""
    _vorlagen_ausgesetzt(oparl, monkeypatch)
    a = _zustand()["papers_ausgesetzt"]
    if fall == "wieder vollständig":
        oparl.papers = [oparl.paper(i) for i in range(1, 11)]
    if fall == "kürzer über zwei Nächte":
        echt = _fenster_vor(monkeypatch, "/papers", 3)
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    oparl.anfragen.clear()
    capsys.readouterr()
    sessionnet.fetch_all()
    monkeypatch.delenv("RATSATLAS_VOLLABRUF")
    vermerk = f"Aussetzen seit {a['seit']} (fortgesetzter Vollabruf: 8 statt bisher 10) aufgehoben (RATSATLAS_VOLLABRUF)"
    assert f"papers: {vermerk}, neuer Vollabruf" in capsys.readouterr().out
    zustand, stand = _zustand(), _stand()
    assert "papers_ausgesetzt" not in zustand and "abruf_ausgesetzt" not in stand
    if fall == "wieder vollständig":
        assert _anfragen(oparl, "/papers") == [(str(s), False) for s in range(1, 6)]
        assert len(_jsonl(config.PAPERS)) == 10 and "papers_fortsetzung" not in zustand
        assert _zeile("papers")["ergebnis"] == f"ok; {vermerk}, neuer Vollabruf"
    elif fall == "kürzer über zwei Nächte":
        assert _anfragen(oparl, "/papers") == [("1", False), ("2", False)]
        assert zustand["papers_fortsetzung"]["seiten"] == 2
        assert "Fortsetzung in der nächsten Nacht" in stand["abruf_hinweis"]["meldung"]
        monkeypatch.setattr(abruf, "get_json", echt)
        oparl.anfragen.clear()
        sessionnet.fetch_all()                                             # ohne Einstellung fortgesetzt, wieder kürzer
        assert _anfragen(oparl, "/papers") == [("2", False), ("3", False), ("4", False)]
        neu = _zustand()["papers_ausgesetzt"]
        assert (neu["objekte"], neu["bisher"], neu["anlass"]) == (8, 10, "fortgesetzter Vollabruf")
        assert _stand()["abruf_ausgesetzt"] == {"papers": neu}
    else:
        assert _anfragen(oparl, "/papers") == [(str(s), False) for s in range(1, 5)]
        assert _anfragen(oparl, "/meetings") == []                         # Abbruch des Laufs wie bisher
        assert zustand["letzter_abbruch"]["art"] == "leer" and "papers_fortsetzung" not in zustand
        assert stand["abruf_fehler"]["meldung"] == ("papers.jsonl: nur 8 statt bisher 10 – unvollständige Antwort? "
                                                    "Vorhandener Stand bleibt.")
        assert not (config.RAW / "papers.teil.jsonl").exists() and len(_jsonl(config.PAPERS)) == 10
        oparl.anfragen.clear()
        sessionnet.fetch_all()
        assert _anfragen(oparl, "/papers") == [("1", True)] and "papers_ausgesetzt" not in _zustand()


@pytest.mark.parametrize("wert", ["kaputt", 7, ["x"], {}])
def test_unlesbarer_eintrag_gilt_als_ausgesetzt(oparl, monkeypatch, capsys, wert):
    """Jeder Eintrag `<liste>_ausgesetzt` außer null gilt als Aussetzen, auch ein unlesbarer (im Zweifel keine Anfrage
    an die Stadt); Log und Abrufstatistik nennen ihn, STAND.json erhält ihn aus dem Zustand (auch nach einer
    beiseitegelegten STAND.json). Null gilt nicht. RATSATLAS_VOLLABRUF hebt ihn auf."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    sessionnet.fetch_all()
    z = _zustand()
    z["meetings_ausgesetzt"] = None
    z["papers_ausgesetzt"] = wert
    config.ZUSTAND.write_text(json.dumps(z), encoding="utf-8")
    config.STAND.write_text("{kaputt", encoding="utf-8")                  # beiseitegelegt, neu begonnen
    oparl.anfragen.clear()
    capsys.readouterr()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/papers") == [] and _anfragen(oparl, "/meetings") == [("1", True)]
    erwartet = wert if isinstance(wert, dict) else {"meldung": f"Eintrag papers_ausgesetzt unlesbar ({wert!r})"}
    assert _stand()["abruf_ausgesetzt"] == {"papers": erwartet}
    z = _zeile("papers")
    assert (z["modus"], z["anfragen"]) == ("ausgesetzt", "0")
    assert z["ergebnis"].startswith("ausgesetzt: papers: Abruf ausgesetzt seit unbekannt (Anlass unbekannt); keine "
                                    "Anfrage")
    err = capsys.readouterr().err
    assert "Warnung: papers: Abruf ausgesetzt seit unbekannt" in err
    assert (f"unlesbar ({wert!r})" in err) is (not isinstance(wert, dict)) and "(None)" not in err
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/papers") == [("1", False), ("2", False), ("3", False)]
    assert "papers_ausgesetzt" not in _zustand() and "abruf_ausgesetzt" not in _stand()


# --- Export und Seite ------------------------------------------------------------------------------------------------

def test_export_nennt_ausgesetzte_listen(oparl, monkeypatch):
    """index.json (meta.abruf_ausgesetzt) aus STAND.json: je ausgesetzter Liste der Beginn und der Stand der Liste
    (letzte reguläre Aktualisierung). Nur Vorlagen und Sitzungen, nur Objekte; ein Eintrag vor der letzten regulären
    Aktualisierung der Liste entfällt, ein unlesbarer Zeitpunkt wird gezeigt (seit None). Ohne ausgesetzte Liste fehlt
    der Schlüssel (index.json bleibt sonst gleich)."""
    from pipeline import export
    a = {"seit": "2026-11-15T22:40:00+00:00", "objekte": 8, "bisher": 10, "anlass": "x", "meldung": "y"}
    stand = {"papers": "2026-11-12T22:20:00+00:00", "meetings": "2026-11-16T22:40:00+00:00",
             "abruf_ausgesetzt": {"papers": a, "meetings": dict(a), "organizations": dict(a), "x": "kaputt"}}
    assert export._abruf_ausgesetzt(stand) == {"papers": {"seit": a["seit"], "stand": "2026-11-12T22:20:00+00:00"}}
    assert export._abruf_ausgesetzt({"abruf_ausgesetzt": {"meetings": {"seit": "gestern"}, "papers": {"seit": 5}}}) == {
        "meetings": {"seit": "gestern", "stand": None}, "papers": {"seit": None, "stand": None}}
    assert export._abruf_ausgesetzt({}) == {} and export._abruf_ausgesetzt({"abruf_ausgesetzt": []}) == {}
    _vorlagen_ausgesetzt(oparl, monkeypatch)
    build.build()
    export.export()
    index = config.EXPORT / config.STADT / "index.json"
    meta = json.loads(index.read_text())["meta"]
    assert meta["abruf_ausgesetzt"] == {"papers": {"seit": _zustand()["papers_ausgesetzt"]["seit"],
                                                   "stand": _stand()["papers"]}}
    assert meta["abruf_fehler"] is None and meta["abruf_warnungen"] == {}
    oparl.papers = [oparl.paper(i) for i in range(1, 11)]                 # wieder vollständig, Aussetzen aufgehoben
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "papers")
    sessionnet.fetch_all()
    build.build()
    export.export()
    assert "abruf_ausgesetzt" not in json.loads(index.read_text())["meta"]


def test_seite_nennt_ausgesetzte_listen_im_datenstand():
    """site/app.js (standAusgesetzt, standText): je ausgesetzter Liste ein Satz in einfacher Sprache im Datenstand, mit
    dem Beginn der Pause und dem gezeigten Stand (Datum des vollen Zeitstempels in Europe/Berlin, 23:30 UTC am 15.11.
    → 16.11.2026); ohne lesbaren Beginn „derzeit“, ohne Stand „der letzte gültige Stand“; ohne Eintrag nichts.
    Ausgeführt mit node (Rechnerzone UTC und Tokio)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt")
    js = (Path(__file__).resolve().parents[1] / "site" / "app.js").read_text(encoding="utf-8")
    teile = [re.search(m, js, re.S | re.M) for m in (r"^  const QUELLE_NAME = .*?;\n",
                                                     r"^  const ISO_DAY = .*?\n  const standText = .*?\n  };\n")]
    assert all(teile), "standAusgesetzt oder standText fehlt in site/app.js"
    faelle = [None, {}, {"organizations": {"seit": "2026-11-15T22:40:00+00:00"}},
              {"papers": {"seit": "2026-11-15T23:30:00+00:00", "stand": "2026-11-12T22:20:00+00:00"}},
              {"meetings": {"seit": None, "stand": None}},
              {"meetings": {"seit": "kaputt", "stand": "2026-11-12"},
               "papers": {"seit": "2026-11-15", "stand": "2026-11-12T23:30:00+00:00"}}]
    m = {"sources": [{"name": "oparl-koeln", "retrieved_at": "2026-11-12T22:20:00+00:00"}],
         "generated_at": "2026-11-16T22:40:00+00:00"}
    code = ("".join(t.group(0) for t in teile) + f"console.log(JSON.stringify([{json.dumps(faelle)}.map(standAusgesetzt), "
            f"standText({json.dumps(m)}, {{abruf_ausgesetzt: {json.dumps(faelle[3])}}})]));")
    vorlagen = " · Der Abruf der Vorlagen ruht seit dem "
    grund_v = ": Die Stadt lieferte zuletzt deutlich weniger Vorlagen als bisher, das wird geprüft. Gezeigt wird "
    sitzungen = (" · Der Abruf der Sitzungstermine ruht derzeit: Die Stadt lieferte zuletzt deutlich weniger Sitzungen als "
                 "bisher, das wird geprüft. Gezeigt wird ")
    for zone in ("UTC", "Asia/Tokyo"):
        r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "TZ": zone})
        assert r.returncode == 0, r.stderr
        saetze, text = json.loads(r.stdout)
        assert saetze == ["", "", "", f"{vorlagen}16.11.2026{grund_v}der Stand vom 12.11.2026.",
                          f"{sitzungen}der letzte gültige Stand.",
                          f"{vorlagen}15.11.2026{grund_v}der Stand vom 13.11.2026."
                          f"{sitzungen}der Stand vom 12.11.2026."], zone
        assert text == ("Datenstand: Ratsinformationssystem: 12.11.2026 · erzeugt 16.11.2026" + saetze[3]), zone


def test_zustand_nach_abbruch_leer_aus_78de995(oparl, monkeypatch):
    """Zustand, den 78de995 nach dem vollständigen Lesen der Sitzungen unter 90 % hinterließ (Abbruch `leer`:
    `letzter_abbruch`, `abruf_fehler` mit Anlass und Abhilfe, Vermerk ohne Zeitfilter; so geprüft in
    test_sitzungen_ohne_zeitfilter_90_prozent_regel bis zum 13.11.2026): Die nächste Nacht mit diesem Stand liest die
    Sitzungen wie bisher vollständig, setzt sie aus und beendet den Lauf vollständig; der alte Fehler entfällt."""
    oparl.meetings = _sitzungen(oparl, 10)
    sessionnet.fetch_all()
    sessionnet._zustand_aendern(
        letzter_abbruch={"zuletzt": "2026-11-14T22:40:00+00:00", "art": "leer", "code": None,
                         "meldung": "meetings_roh.jsonl: nur 8 statt bisher 10 – unvollständige Antwort?"},
        meetings_ohne_zeitfilter={"zeit": "2026-11-14T22:30:00+00:00", "meldung": "Zeitfilter auf Seite 1 nicht "
                                  "angewandt"})
    sessionnet._stand_setzen(abruf_fehler={"zeit": "2026-11-14T22:40:00+00:00", "meldung": (
        "meetings_roh.jsonl: nur 8 statt bisher 10 – unvollständige Antwort? Vorhandener Stand bleibt. (vollständiges "
        "Lesen nach nicht angewandtem Zeitfilter) – Abhilfe, wenn der kürzere Stand stimmt (nicht bei 0 Objekten): ein "
        "Lauf mit RATSATLAS_KUERZER_ANNEHMEN=meetings")})
    oparl.meetings = oparl.meetings[2:]
    _ohne_zeitfilter(oparl, monkeypatch, "/meetings")
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/meetings") == [("1", True), ("1", False), ("2", False), ("3", False), ("4", False)]
    zustand, stand = _zustand(), _stand()
    assert zustand["meetings_ausgesetzt"]["anlass"] == "vollständiges Lesen nach nicht angewandtem Zeitfilter"
    assert "letzter_abbruch" not in zustand and "abruf_fehler" not in stand and "meetings" in stand["abruf_ausgesetzt"]
    oparl.anfragen.clear()
    sessionnet.fetch_all()
    assert _anfragen(oparl, "/meetings") == []
