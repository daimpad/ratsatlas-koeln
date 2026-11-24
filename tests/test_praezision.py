"""Präzisionsprüfung der Geokodierung (Entscheidung 16.11.2026 (5)): Auswertung tools/praezision.py, Prüfregeln
explore/PRUEFREGELN_geokodierung.md und Prüfbogen tools/pruefbogen.html (lokal, ohne Netz). Nur erfundene Stichproben
(„[Testdaten]“, example.invalid); keine Anfrage ins Netz. Der Kern des Prüfbogens (Lesen, Urteile, Schreiben) läuft mit
node, die Prüfung im Browser (tests/browser/pruefbogen.js) nur mit RATSATLAS_BROWSER=1 (lokal und im Job „browser“ von
.github/workflows/tests.yml)."""
import base64
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys

import pytest

from pipeline import config

ROOT = config.ROOT
HTML = ROOT / "tools" / "pruefbogen.html"
REGELN = ROOT / "explore" / "PRUEFREGELN_geokodierung.md"
URTEIL = "urteil (richtig/teilweise/falsch/unklar)"
KOPF = ["methode", "drucksache", "datum", "vorlagenart", "titel", "link", "ort", "ebene", "stadtteil_oder_bezirk",
        "konfidenz", "fundstelle", URTEIL, "anmerkung"]
Z = 1.959963984540054
EBENEN_REGELN = ("Adresse (Punkt)", "Straße", "Stadtteil", "Stadtbezirk", "Bebauungsplan", "Gebäude oder Anlage")
URTEILE = ("richtig", "teilweise", "falsch", "unklar")


def _modul():
    spec = importlib.util.spec_from_file_location("praezision", ROOT / "tools" / "praezision.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.fixture(scope="module")
def pz():
    return _modul()


def _zeile(methode, urteil="", ebene="strasse", nr=1, **mehr):
    z = dict(zip(KOPF, [methode, f"{nr:04d}/2099", "2099-01-01", "Beschlussvorlage", f"[Testdaten] Vorlage {nr}",
                        f"https://example.invalid/vo/{nr}", "Musterweg", ebene, "Musterstadtteil", "mittel",
                        "Musterweg", urteil, ""]))
    z.update({URTEIL if k == "urteil" else k: v for k, v in mehr.items()})
    return [z[k] for k in KOPF]


def _schreiben(pfad, zeilen, kopf=KOPF, **csv_args):
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n", **csv_args)
        w.writerow(kopf)
        w.writerows(zeilen)
    return pfad


def _audit(pfad, je):
    """audit_geokodierung.tsv mit N verschiedenen Drucksachen je Methode (je Drucksache zwei Zeilen wie mehrere Orte)."""
    kopf = ["drucksache", "datum", "vorlagenart", "titel", "stufe", "methode", "ebene", "treffer", "ortsteil",
            "stadtbezirk", "konfidenz", "fundstelle", "quellobjekt", "pruefstatus"]
    zeilen = [[f"{i:04d}/2099", "", "", "", "B", m, "strasse", "", "", "", "", "", "", ""]
              for m, n in je.items() for i in range(1, n + 1) for _ in range(2)]
    return _schreiben(pfad, zeilen, kopf)


def _lauf(pz, capsys, *args):
    rc = pz.main([str(a) for a in args])
    aus = capsys.readouterr()
    return rc, aus.out, aus.err


# --- Rechnen -------------------------------------------------------------------------------------------------------

def test_wilson_gegen_handrechnung(pz):
    """Wilson-Intervall gegen von Hand gerechnete Werte (z = 1,96; vier Stellen) und die zweite Form der Formel."""
    for x, n, unten, oben in [(40, 50, 0.6696, 0.8876), (25, 50, 0.3664, 0.6336), (0, 10, 0.0, 0.2775),
                              (10, 10, 0.7225, 1.0), (1, 1, 0.2065, 1.0), (0, 50, 0.0, 0.0713), (49, 50, 0.8950, 0.9965)]:
        u, o = pz.wilson(x, n)
        assert (round(u, 4), round(o, 4)) == pytest.approx((unten, oben), abs=1.1e-4), (x, n, u, o)
        # zweite Form: (2x + z² ± z·√(z² + 4x(n−x)/n)) / (2(n + z²))
        w = Z * math.sqrt(Z * Z + 4 * x * (n - x) / n)
        assert (u, o) == pytest.approx(((2 * x + Z * Z - w) / (2 * (n + Z * Z)),
                                        min(1.0, (2 * x + Z * Z + w) / (2 * (n + Z * Z)))), abs=1e-12)
    assert pz.wilson(0, 0) is None
    assert pz.Z == pytest.approx(Z, abs=1e-12)


def test_geschichtet_mit_endlichkeitskorrektur(pz):
    """Geschichtete Schätzung gegen eine Rechnung Schritt für Schritt: A (N=100, n=10, x=8), B (N=300, n=20, x=20,
    p=1): W = 0,25 und 0,75, p = 0,95; Varianz mit Agresti–Coull-angepasstem p und Endlichkeitskorrektur."""
    z2 = Z * Z
    pa, pb = (8 + z2 / 2) / (10 + z2), (20 + z2 / 2) / (20 + z2)
    var = 0.25 ** 2 * (1 - 10 / 100) * pa * (1 - pa) / (10 + z2) + 0.75 ** 2 * (1 - 20 / 300) * pb * (1 - pb) / (20 + z2)
    r = pz.geschichtet([(100, 10, 8), (300, 20, 20), (50, 0, 0)])   # Schicht ohne gerechnete Zeile entfällt
    assert r["p"] == pytest.approx(0.95, abs=1e-12)
    assert r["se"] == pytest.approx(math.sqrt(var), abs=1e-12)
    assert r["se"] == pytest.approx(0.04956, abs=1e-4)                 # von Hand: √0,0024561
    # Intervall: Wilson um p mit dem effektiven Umfang n_eff = p̃(1 − p̃)/Var − z², p̃ = Σ W_h p̃_h
    pt = 0.25 * pa + 0.75 * pb
    n_eff = pt * (1 - pt) / var - z2
    assert r["n_eff"] == pytest.approx(n_eff, abs=1e-9) and n_eff >= 10    # mindestens das kleinste n_h
    assert (r["unten"], r["oben"]) == pytest.approx(_wilson_p(0.95, n_eff), abs=1e-12)
    assert r["unten"] < 0.95 < r["oben"] < 1 and r["N"] == 400
    # ohne Endlichkeitskorrektur wäre die Varianz größer; vollständig geprüfte Schicht (n = N): Varianz 0, nur der Punkt
    voll = pz.geschichtet([(20, 20, 17)])
    assert voll["p"] == pytest.approx(0.85) and voll["se"] == 0 and voll["unten"] == voll["oben"] == pytest.approx(0.85)
    assert voll["n_eff"] is None
    # n > N (verschiedene Datenstände): Korrektur höchstens 1, keine negative Varianz
    assert pz.geschichtet([(10, 12, 6)])["se"] == 0
    assert pz.geschichtet([]) is None and pz.geschichtet([(10, 0, 0)]) is None


def _wilson_p(p, n):
    """Wilson-Intervall um p bei Umfang n (Lehrbuchform, unabhängig von tools/praezision.py)."""
    m = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z / (1 + Z * Z / n) * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return max(0.0, m - h), min(1.0, m + h)


def test_geschichtet_eine_schicht_ist_wilson(pz):
    """Eine Schicht ohne Endlichkeitskorrektur: das geschichtete Intervall ist das Wilson-Intervall der Methode
    (n_eff = n). Mit Endlichkeitskorrektur etwas schmaler, aber am Rand nicht mehr so knapp wie vorher p ± z·se
    (50 von 50 bei N = 1000: vorher 95,2–100 %, Wilson 92,9–100 %; 48 von 50: vorher 89,2–100 %, Wilson 86,5–98,9 %)."""
    for x in (0, 1, 25, 48, 50):
        r = pz.geschichtet([(10 ** 15, 50, x)])
        assert r["n_eff"] == pytest.approx(50, abs=1e-6)
        assert (r["unten"], r["oben"]) == pytest.approx(pz.wilson(x, 50), abs=1e-9)
    for x, vorher_unten, wilson_unten in ((50, 0.952, 0.929), (48, 0.892, 0.865)):
        r = pz.geschichtet([(1000, 50, x)])
        assert wilson_unten < r["unten"] < vorher_unten, (x, r)
        assert r["n_eff"] == pytest.approx((50 + Z * Z) / 0.95 - Z * Z, abs=1e-9)
    assert pz.geschichtet([(1000, 50, 48)])["oben"] < 1   # vorher auf 100 % begrenzt


def test_p_null_und_eins(pz):
    """p = 0 und p = 1: Wilson-Grenzen innerhalb [0, 1], geschichtete Varianz über null (Agresti–Coull)."""
    for x in (0, 50):
        u, o = pz.wilson(x, 50)
        assert 0 <= u <= o <= 1 and (u == 0 if x == 0 else o == 1)
        r = pz.geschichtet([(500, 50, x), (200, 50, x)])
        assert r["se"] > 0.005 and 0 <= r["unten"] <= r["p"] <= r["oben"] <= 1
        assert r["p"] == x / 50 and (r["unten"] == 0 if x == 0 else r["oben"] == 1)
    # eine Zeile je Schicht: definiert (bei n − 1 im Nenner nicht)
    assert pz.geschichtet([(30, 1, 1)])["se"] > 0


# --- Auswerten -----------------------------------------------------------------------------------------------------

def _probe(tmp_path):
    zeilen = ([_zeile("strasse", u, nr=i) for i, u in enumerate(["richtig"] * 6 + ["teilweise"] * 2 + ["falsch", "unklar",
                                                                                                         "", ""], 1)]
              + [_zeile("ortsteil_name", u, ebene="ortsteil", nr=20 + i)
                 for i, u in enumerate(["R", " t ", "F", "u", "Richtig", "RICHTIG"])]
              + [_zeile("bebauungsplan", "", ebene="bebauungsplan", nr=40)]
              + [_zeile("strasse_mehrdeutig", "teilweise", ebene="strasse; ortsteil", nr=50)])
    return _schreiben(tmp_path / "stichprobe_geokodierung.tsv", zeilen)


def test_zaehlung_je_methode_unklar_offen(pz, tmp_path):
    zeilen, kodierung = pz.stichprobe_lesen(_probe(tmp_path))
    e = pz.auswerten(zeilen)
    m = {r["methode"]: r for r in e["methoden"]}
    s = m["strasse"]
    assert (s["gezogen"], s["beurteilt"], s["richtig"], s["teilweise"], s["falsch"], s["unklar"], s["offen"],
            s["ungueltig"], s["n"]) == (12, 10, 6, 2, 1, 1, 2, 0, 9)
    assert s["streng"]["p"] == pytest.approx(6 / 9) and s["nachsichtig"]["p"] == pytest.approx(8 / 9)
    assert s["streng"]["ci"] == pz.wilson(6, 9) and s["nachsichtig"]["ci"] == pz.wilson(8, 9)
    o = m["ortsteil_name"]   # Kurzformen und Schreibweisen
    assert (o["richtig"], o["teilweise"], o["falsch"], o["unklar"], o["n"]) == (3, 1, 1, 1, 5)
    b = m["bebauungsplan"]   # nur offen: keine Präzision
    assert b["n"] == 0 and b["streng"]["p"] is None and b["streng"]["ci"] is None
    # Ebenen: nur Zeilen mit genau einer Ebene; strasse_mehrdeutig mit zwei Ebenen nicht aufgeteilt
    assert {(r["methode"], r["ebene"]) for r in e["ebenen"]} == {("strasse", "strasse"), ("ortsteil_name", "ortsteil"),
                                                                  ("bebauungsplan", "bebauungsplan")}
    assert e["ebenen_nicht_aufgeteilt"] == {"mehrere": 1}
    # gepoolt: unklar und offen nicht gerechnet
    g = e["gepoolt"]
    assert g["n"] == 9 + 5 + 1 and g["streng"]["x"] == 6 + 3 and g["nachsichtig"]["x"] == 8 + 4 + 1
    assert e["summe"]["unklar"] == 2 and e["summe"]["offen"] == 3 and kodierung == "UTF-8"


def test_ungueltige_werte_nur_mit_zeilennummer(pz, tmp_path, capsys):
    pfad = _schreiben(tmp_path / "s.tsv", [_zeile("strasse", "richtig"), _zeile("strasse", "GEHEIMWERT ja"),
                                           _zeile("strasse", "x"), _zeile("strasse", "")])
    rc, aus, err = _lauf(pz, capsys, pfad)
    assert rc == 0 and err == ""
    assert "in Zeilen 3, 4:" in aus and "GEHEIMWERT" not in aus
    assert "| `strasse` | 4 | 1 | 1 | 0 | 0 | 0 | 1 | 2 | 1 |" in aus
    # Ebene: Spalte „ungültig“, die Spalten ergeben „gezogen“
    assert "| `strasse` | Straße | 4 | 1 | 0 | 0 | 0 | 1 | 2 | 1 |" in aus
    pfad = _schreiben(tmp_path / "s1.tsv", [_zeile("strasse", "richtig"), _zeile("strasse", "x")])
    rc, aus, err = _lauf(pz, capsys, pfad)
    assert rc == 0 and "in Zeile 3:" in aus and "Stichprobe `s1.tsv`: 2 Zeilen" in aus


def test_bom_crlf_anfuehrungszeichen_utf16(pz, tmp_path):
    """Datei aus einer Tabellenkalkulation: BOM, CRLF, Felder in Anführungszeichen (Tab, Zeilenwechsel, "")."""
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter="\t", lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    w.writerow([k.upper() if k == "methode" else k for k in KOPF])
    w.writerow(_zeile("strasse", "Richtig", titel='[Testdaten] "Zitat"\tmit Tab\r\nzweite Zeile'))
    w.writerow(_zeile("strasse", "f", anmerkung="eins\ntwo"))
    w.writerow([""] * len(KOPF))   # leere Zeile am Ende
    (tmp_path / "bom.tsv").write_bytes(b"\xef\xbb\xbf" + puffer.getvalue().encode("utf-8"))
    (tmp_path / "utf16.tsv").write_bytes(puffer.getvalue().encode("utf-16"))
    (tmp_path / "cp1252.tsv").write_bytes(puffer.getvalue().replace("eins", "Straße").encode("cp1252"))
    for name, kod in (("bom.tsv", "UTF-8"), ("utf16.tsv", "UTF-16"), ("cp1252.tsv", "Windows-1252")):
        zeilen, kodierung = pz.stichprobe_lesen(tmp_path / name)
        assert kodierung == kod and [(z["nr"], z["methode"], pz.urteil_normal(z["urteil"])) for z in zeilen] == [
            (2, "strasse", "richtig"), (3, "strasse", "falsch")], name


def test_schichtung_mit_audit_und_warnungen(pz, tmp_path, capsys):
    stichprobe = _schreiben(tmp_path / "s.tsv",
                            [_zeile("strasse", "richtig", nr=i) for i in range(1, 9)]
                            + [_zeile("strasse", "falsch", nr=9), _zeile("strasse", "teilweise", nr=10)]
                            + [_zeile("ortsteil_name", "richtig", ebene="ortsteil", nr=i) for i in range(1, 4)]
                            + [_zeile("neu_methode", "richtig", nr=1)])
    audit = _audit(tmp_path / "audit_geokodierung.tsv", {"strasse": 100, "ortsteil_name": 2, "vererbt": 50})
    rc, aus, err = _lauf(pz, capsys, stichprobe, "--audit", audit, "--tsv", tmp_path / "aus.tsv")
    assert rc == 0 and err == ""
    # Warnungen: Methode fehlt im Audit; mehr Zeilen als Vorlagen; Drucksache 0003/2099 nicht im Audit bei ortsteil_name
    assert "Methode `neu_methode` steht in der Stichprobe, aber nicht im Audit" in aus
    assert "Methode `ortsteil_name`: mehr Zeilen in der Stichprobe (3, davon gerechnet 3) als Vorlagen im Audit (2)" in aus
    assert "1 Zeile der Stichprobe: Drucksache bei dieser Methode nicht im Audit" in aus
    assert "Methode ohne gerechnete Zeile (nicht im geschichteten Gesamtwert): `vererbt` – zusammen 50 Vorlagen" in aus
    # unabhängige Rechnung: strasse N=100, n=10; ortsteil_name N=2, n=3 (Korrektur 0); vererbt ohne Zeile
    z2 = Z * Z
    for lesart, xs in (("streng", 8), ("nachsichtig", 9)):
        w1, w2 = 100 / 102, 2 / 102
        p = w1 * xs / 10 + w2 * 1.0
        pt = (xs + z2 / 2) / (10 + z2)
        var = w1 ** 2 * 0.9 * pt * (1 - pt) / (10 + z2)
        p_ac = w1 * pt + w2 * (3 + z2 / 2) / (3 + z2)
        unten, oben = _wilson_p(p, p_ac * (1 - p_ac) / var - z2)
        zeile = next(z for z in csv.reader(open(tmp_path / "aus.tsv", encoding="utf-8"), delimiter="\t")
                     if z[0] == "gesamt_geschichtet_gewichtet")
        kopf = next(csv.reader(open(tmp_path / "aus.tsv", encoding="utf-8"), delimiter="\t"))
        werte = dict(zip(kopf, zeile))
        assert float(werte[lesart]) == pytest.approx(p, abs=5e-5)
        assert float(werte[f"{lesart}_unten"]) == pytest.approx(unten, abs=5e-5)
        assert float(werte[f"{lesart}_oben"]) == pytest.approx(oben, abs=5e-5)
        assert werte["vorlagen_im_audit"] == "102"
    assert "Σ N_h = 152, davon in Methoden mit gerechneten Zeilen 102 (67,1 %)" in aus
    assert "| `strasse` | 100 | 10 | 98,0 % | 8 | 9 |" in aus


def test_n_h_kopien_derselben_drucksache(pz, tmp_path, capsys):
    """N_h zählt Drucksache, Datum und Vorlagenart: Kopien mit derselben Drucksache und anderem Datum oder anderer
    Vorlagenart zählen einzeln, mehrere Orte derselben Vorlage einmal, Zeilen ohne Drucksache nicht. Kommt eine
    Drucksache in einer Methode der Stichprobe mehrfach vor, nennt die Ausgabe nur die Anzahl (ohne Drucksache)."""
    kopf = ["drucksache", "datum", "vorlagenart", "titel", "stufe", "methode", "ebene", "treffer", "ortsteil",
            "stadtbezirk", "konfidenz", "fundstelle", "quellobjekt", "pruefstatus"]

    def a(ref, datum, art, m="strasse"):
        return [ref, datum, art, "", "B", m, "strasse", "", "", "", "", "", "", ""]
    audit = _schreiben(tmp_path / "audit.tsv", [
        a("0001/2099", "2099-01-01", "Beschlussvorlage"), a("0001/2099", "2099-01-01", "Beschlussvorlage"),  # zwei Orte
        a("0001/2099", "2099-02-01", "Beschlussvorlage"), a("0001/2099", "2099-01-01", "Mitteilung"),         # Kopien
        a("0002/2099", "2099-01-01", "Beschlussvorlage"), a("", "2099-01-01", "Beschlussvorlage"),            # ohne Nr.
        a("0003/2099", "", "", m="ortsteil_name")], kopf)
    je = pz.audit_lesen(audit)
    assert {m: len(v) for m, v in je.items()} == {"strasse": 4, "ortsteil_name": 1}
    # ohne Spalten „datum“ und „vorlagenart“: nur Drucksachen
    schmal = _schreiben(tmp_path / "schmal.tsv", [["0001/2099", "strasse"], ["0001/2099", "strasse"],
                                                  ["0002/2099", "strasse"]], kopf=["drucksache", "methode"])
    assert {m: len(v) for m, v in pz.audit_lesen(schmal).items()} == {"strasse": 2}
    stichprobe = _schreiben(tmp_path / "s.tsv", [_zeile("strasse", "richtig", nr=1), _zeile("strasse", "falsch", nr=1),
                                                 _zeile("strasse", "richtig", nr=2),
                                                 _zeile("ortsteil_name", "richtig", ebene="ortsteil", nr=3)])
    rc, aus, err = _lauf(pz, capsys, stichprobe, "--audit", audit)
    assert rc == 0 and err == ""
    assert "Methode `strasse`: 1 Drucksache steht mehr als einmal in der Stichprobe" in aus
    assert "`ortsteil_name`: " not in aus.split("### Hinweise", 1)[1]   # keine Kopie, keine Warnung
    assert "| `strasse` | 4 | 3 | 80,0 % | 2 | 2 |" in aus
    assert "0001" not in aus and "2099" not in aus and "nicht im Audit" not in aus
    # ohne Audit: derselbe Hinweis
    assert "1 Drucksache steht mehr als einmal" in _lauf(pz, capsys, stichprobe)[1]


def test_kopfzeile_und_lange_felder(pz, tmp_path, capsys):
    """Kopfzeile: Zeilen mit unlesbarer Methode gesondert, sodass beurteilt, offen und ungültig zur übrigen Zahl
    passen; Ebenen im Singular und Plural. Felder über der Grenze des csv-Moduls (131 072 Zeichen) sind lesbar, die
    Grenze ist danach wieder die alte."""
    grenze = csv.field_size_limit()
    pfad = _schreiben(tmp_path / "s.tsv", [_zeile("strasse", "richtig", titel="[Testdaten] " + "x" * 200_000),
                                           _zeile("strasse", "", nr=2), _zeile("", "falsch", nr=3),
                                           _zeile("strasse", "f", ebene="strasse; ortsteil", nr=4)])
    rc, aus, err = _lauf(pz, capsys, pfad)
    assert rc == 0 and err == "" and csv.field_size_limit() == grenze
    assert ("4 Zeilen (je Zeile eine Vorlage mit einer Methode), Kodierung UTF-8. Davon 1 Zeile mit leerer oder "
            "unlesbarer Methode (nur in der Tabelle je Methode); in den übrigen 3: Beurteilt 2 (davon unklar 0), offen 1, "
            "ungültig 0.") in aus
    assert "Nicht nach Ebene aufgeteilt: 1 Zeile mit mehreren Ebenen." in aus and "xxxx" not in aus
    assert "Methode leer oder unlesbar in Zeile 4:" in aus


def test_ausgabe_ohne_inhalte(pz, tmp_path, capsys):
    """Nur Zahlen: keine Titel, Drucksachen, Orte, Links, Fundstellen, Anmerkungen oder ungültigen Urteile in der
    Ausgabe; eine Methode, die keine ist (verschobene Spalten), erscheint als „(Methode unlesbar)“."""
    marken = dict(titel="TITELMARKE Musterweg 7", drucksache="7777/2099", ort="ORTMARKE 7",
                  link="https://example.invalid/LINKMARKE", stadtteil_oder_bezirk="STADTTEILMARKE",
                  fundstelle="FUNDMARKE", anmerkung="NOTIZMARKE Frau Muster")
    zeilen = [_zeile("strasse", "richtig", **marken), _zeile("strasse", "URTEILMARKE", **marken),
              _zeile("TITELMARKE in falscher Spalte", "richtig", **marken),
              _zeile("strasse", "teilweise", ebene="EBENENMARKE", **marken)]
    pfad = _schreiben(tmp_path / "s.tsv", zeilen)
    audit = _audit(tmp_path / "a.tsv", {"strasse": 5, "TITELMARKE im Audit": 3})
    rc, aus, err = _lauf(pz, capsys, pfad, "--audit", audit, "--tsv", tmp_path / "aus.tsv")
    tsv = (tmp_path / "aus.tsv").read_text(encoding="utf-8")
    assert rc == 0 and "(Methode unlesbar)" in aus and "(Methode unlesbar)" in tsv
    for text in (aus, err, tsv):
        for marke in ("TITELMARKE", "7777", "ORTMARKE", "LINKMARKE", "example.invalid", "STADTTEILMARKE", "FUNDMARKE",
                      "NOTIZMARKE", "Muster", "URTEILMARKE", "EBENENMARKE"):
            assert marke not in text, marke


def test_rueckgabe_bei_unbrauchbarer_eingabe(pz, tmp_path, capsys):
    rc, aus, err = _lauf(pz, capsys, tmp_path / "fehlt.tsv")
    assert rc == 1 and aus == "" and "Datei nicht gefunden" in err
    ohne = _schreiben(tmp_path / "ohne.tsv", [["strasse", "1"]], kopf=["methode", "drucksache"])
    rc, aus, err = _lauf(pz, capsys, ohne)
    assert rc == 1 and "Stichprobe ohne Spalte „urteil“" in err
    ohne = _schreiben(tmp_path / "ohne2.tsv", [["richtig"]], kopf=["urteil"])
    rc, aus, err = _lauf(pz, capsys, ohne)
    assert rc == 1 and "„methode“" in err
    (tmp_path / "leer.tsv").write_text("", encoding="utf-8")
    assert _lauf(pz, capsys, tmp_path / "leer.tsv")[0] == 1
    gut = _probe(tmp_path)
    schlecht = _schreiben(tmp_path / "audit.tsv", [["strasse"]], kopf=["methode"])
    rc, aus, err = _lauf(pz, capsys, gut, "--audit", schlecht)
    assert rc == 1 and "Audit ohne Spalte" in err
    rc, aus, err = _lauf(pz, capsys, gut)   # Warnungen und offene Zeilen: 0
    assert rc == 0 and "(b) **Geschichtet, gewichtet**: entfällt" in aus


def test_kopf_der_stichprobe_im_export():
    """Die Spalte des Urteils in pipeline/export.py nennt alle vier Urteile; die Auswertung findet sie über „urteil“."""
    quelle = (ROOT / "pipeline" / "export.py").read_text(encoding="utf-8")
    assert f'"{URTEIL}"' in quelle and "urteil (richtig/teilweise/falsch)\"" not in quelle


# --- Prüfbogen: Kern mit node --------------------------------------------------------------------------------------

NODE_LAUF = r"""
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
const kern = html.split('// BEGIN kern')[1].split('// END kern')[0];
const ctx = { TextDecoder: TextDecoder, URL: URL }; vm.createContext(ctx); vm.runInContext(kern, ctx);
const auftrag = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const aus = { parse: auftrag.parse.map((t) => ctx.parseTsv(t)), normal: auftrag.normal.map((w) => ctx.urteilNormal(w)),
              namen: auftrag.namen.map((n) => ctx.speichername(n)) };
const d = ctx.dekodieren(new Uint8Array(fs.readFileSync(auftrag.datei)));
const bogen = ctx.bogenLesen(d.text);
aus.nummern = bogen.zeilen.map((z) => z.nr);
aus.kodierung = d.kodierung;
fs.writeFileSync(auftrag.aus, ctx.bogenSchreiben(bogen, auftrag.urteile, auftrag.anmerkungen), 'utf8');
try { ctx.bogenLesen('titel\tlink\nx\ty\n'); } catch (e) { aus.fehler = e.message; }
// Methoden mit Namen von Eigenschaften eines Objekts zählen wie andere; leere Datei; gesetzte Urteile
const namen = ['__proto__', 'constructor', 'toString', 'hasOwnProperty', 'strasse', '__proto__', ''];
const datei = { 1: 'x', 2: 'r', 4: 'r', 6: 'u' };
const proto = ctx.bogenLesen('methode\turteil\n' + namen.map((m, i) => m + '\t' + (datei[i] || '')).join('\n') + '\n');
const c = ctx.zaehlen(proto, { 5: 'falsch', 6: '' });
aus.zaehlung = { je: Object.keys(c.je).sort().map((k) => [k, c.je[k].z, c.je[k].b, c.je[k].x]), gesamt: c.gesamt };
const leer = ctx.bogenLesen('methode\turteil\n');
aus.leer = [leer.zeilen.length, ctx.zaehlen(leer, {}).gesamt];
aus.gesetzt = ctx.urteileGesetzt({ 2: 'richtig', 3: '', 4: 'unklar', 5: 'falsch', 6: '' });
aus.kurz = [ctx.kurz('abc', 3), ctx.kurz('abcd', 3), ctx.kurz('a\uD83D\uDE00b', 2).length, ctx.kurz(null, 3)];
aus.links = ['https://buergerinfo.stadt-koeln.de/vo0050.asp?__kvonr=1', 'https://example.invalid/vo/1',
  'https://buergerinfo.stadt-koeln.de.example.invalid/x', 'https://buergerinfo.stadt-koeln.de@example.invalid/x',
  'http://buergerinfo.stadt-koeln.de/x', 'javascript:alert(1)', 'https://', ' https://ratsinformation.stadt-koeln.de/ ']
  .map((t) => { const l = ctx.originalLink(t); return l && [l.href, l.ris, l.text]; });
process.stdout.write(JSON.stringify(aus));
"""
SCHWIERIG = [
    _zeile("strasse", nr=1, titel='[Testdaten] Umgestaltung "Am Markt"\tmit Tab', fundstelle="a\r\nb"),
    _zeile("strasse", "R", nr=2, titel="[Testdaten] Zwei Zeilen\nÄußere Kanalstraße – Grünfläche ßäöü",
           anmerkung='alt "x"'),
    _zeile("strasse", "vielleicht", nr=3, titel='"', ort=""),
    _zeile("ortsteil_name", nr=4, ebene="ortsteil", titel="<img src=x onerror=alert(1)>", link="javascript:alert(1)"),
    _zeile("ortsteil_name", " t ", nr=5, ebene="ortsteil", titel=" führendes Leerzeichen "),
]
PARSE = ['a\t"b\tc"\t"d""e"\n', '"ab"c\td\n', 'a"b\t"c"\n\nx\n', 'a\r\nb\rc\n', 'x\t\n""\n', 'ohne Ende',
         '"offen\nbis zum Ende']


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node fehlt: Kern des Prüfbogens (JavaScript) nicht prüfbar")
    return node


def test_pruefbogen_kern_rundweg(tmp_path):
    """Python schreibt eine Stichprobe (Tab, Anführungszeichen, Zeilenwechsel und CRLF in Feldern, Umlaute), node liest
    sie mit dem Kern des Prüfbogens, setzt Urteile und Anmerkungen und schreibt sie; Python liest sie zurück: nur die
    Spalten Urteil und Anmerkung unterscheiden sich, und die Datei ist Byte für Byte, was csv.writer schreiben würde.
    Dazu liest der Kern Grenzfälle wie Pythons csv.reader."""
    node = _node()
    ein = _schreiben(tmp_path / "stichprobe_geokodierung.tsv", SCHWIERIG)
    urteile = {"2": "falsch", "3": "teilweise", "5": "", "6": "unklar"}
    anmerkungen = {"2": 'Bezirk richtig, "Stadtteil" falsch\tTab\nzweite Zeile', "4": "Ümlaut ß"}
    auftrag = tmp_path / "auftrag.json"
    auftrag.write_text(json.dumps({"datei": str(ein), "aus": str(tmp_path / "aus.tsv"), "urteile": urteile,
                                   "anmerkungen": anmerkungen, "parse": PARSE,
                                   "normal": ["R", " Richtig ", "TEILWEISE", "u", "", "  ", "ja", None],
                                   "namen": ["stichprobe_geokodierung.tsv", "x_beurteilt.tsv", "a.TXT", ""]}),
                       encoding="utf-8")
    r = subprocess.run([node, "-e", NODE_LAUF, str(HTML), str(auftrag)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    erg = json.loads(r.stdout)
    assert erg["parse"] == [list(csv.reader(io.StringIO(t, newline=""), delimiter="\t")) for t in PARSE]
    assert erg["normal"] == ["richtig", "richtig", "teilweise", "unklar", "", "", None, ""]
    assert erg["namen"] == ["stichprobe_geokodierung_beurteilt.tsv", "x_beurteilt.tsv", "a_beurteilt.tsv",
                            "stichprobe_geokodierung_beurteilt.tsv"]
    assert erg["nummern"] == [2, 3, 4, 5, 6] and erg["kodierung"] == "UTF-8"
    assert "„methode“ und „urteil“ fehlt" in erg["fehler"]
    # Zählung ohne Prototyp: „__proto__“ (zweimal) und „constructor“ wie jede Methode; ungültig je Methode und gesamt
    assert erg["zaehlung"] == {"je": [["(ohne Methode)", 1, 1, 0], ["__proto__", 2, 0, 0], ["constructor", 1, 0, 1],
                                      ["hasOwnProperty", 1, 1, 0], ["strasse", 1, 0, 0], ["toString", 1, 1, 0]],
                               "gesamt": {"z": 7, "b": 3, "x": 1}}
    assert erg["leer"] == [0, {"z": 0, "b": 0, "x": 0}] and erg["gesetzt"] == 3
    assert erg["kurz"] == ["abc", "abc … (gekürzt, vollständig in der Datei)",
                           len("a … (gekürzt, vollständig in der Datei)"), ""]
    ris = "im Ratsinformationssystem öffnen"
    assert erg["links"] == [
        ["https://buergerinfo.stadt-koeln.de/vo0050.asp?__kvonr=1", True, f"{ris} (buergerinfo.stadt-koeln.de, neues Fenster)"],
        ["https://example.invalid/vo/1", False, "Link öffnen (example.invalid, neues Fenster)"],
        ["https://buergerinfo.stadt-koeln.de.example.invalid/x", False,
         "Link öffnen (buergerinfo.stadt-koeln.de.example.invalid, neues Fenster)"],
        ["https://buergerinfo.stadt-koeln.de@example.invalid/x", False, "Link öffnen (example.invalid, neues Fenster)"],
        None, None, None,
        ["https://ratsinformation.stadt-koeln.de/", True, f"{ris} (ratsinformation.stadt-koeln.de, neues Fenster)"]]
    vorher = list(csv.reader(open(ein, encoding="utf-8", newline=""), delimiter="\t"))
    nachher = list(csv.reader(open(tmp_path / "aus.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    iu, ia = KOPF.index(URTEIL), KOPF.index("anmerkung")
    erwartet = [z[:] for z in vorher]
    for nr, z in enumerate(erwartet[1:], start=2):
        alt = z[iu].strip().lower()
        z[iu] = urteile.get(str(nr), {"r": "richtig", "t": "teilweise"}.get(alt, z[iu]))
        z[ia] = anmerkungen.get(str(nr), z[ia])
    assert nachher == erwartet
    assert [[w for i, w in enumerate(z) if i not in (iu, ia)] for z in nachher] == \
        [[w for i, w in enumerate(z) if i not in (iu, ia)] for z in vorher]
    puffer = io.StringIO(newline="")
    csv.writer(puffer, delimiter="\t", lineterminator="\n").writerows(erwartet)
    assert (tmp_path / "aus.tsv").read_bytes() == puffer.getvalue().encode("utf-8")


# --- Prüfbogen: Datei und Prüfregeln -------------------------------------------------------------------------------

def _hash(inhalt):
    return "sha256-" + base64.b64encode(hashlib.sha256(inhalt.encode("utf-8")).digest()).decode()


def test_pruefbogen_ohne_netz_und_mit_csp():
    """Eine Datei ohne Netz: CSP mit default-src 'none' und Hashes, die zu Skript und Stil passen; keine Adresse mit
    http(s), keine Anfrage- oder HTML-Schnittstelle; nicht unter site/ und nicht im Datenpaket."""
    html = HTML.read_text(encoding="utf-8")
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    assert csp and html.index(csp.group(0)) < html.index("<style>") < html.index("<script>")
    regeln = dict(r.strip().split(" ", 1) for r in csp.group(1).split(";"))
    skripte, stile = re.findall(r"<script>(.*?)</script>", html, re.S), re.findall(r"<style>(.*?)</style>", html, re.S)
    assert len(skripte) == len(stile) == 1 and "<script " not in html and "<style " not in html
    assert regeln["default-src"] == "'none'" and regeln["base-uri"] == "'none'" and regeln["form-action"] == "'none'"
    assert regeln["script-src"] == f"'{_hash(skripte[0])}'", f"Hash des Skripts neu eintragen: '{_hash(skripte[0])}'"
    assert regeln["style-src"] == f"'{_hash(stile[0])}'", f"Hash des Stils neu eintragen: '{_hash(stile[0])}'"
    assert not re.search(r"https?:/|//[a-z0-9.-]+\.[a-z]{2,}|@import", html, re.I) and "url(" not in stile[0].lower()
    assert not re.search(r"\bstyle=|\bon[a-z]+=", html)   # keine Stilattribute, keine Ereignisattribute
    for verboten in ("fetch", "XMLHttpRequest", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                     "eval(", "Function(", "WebSocket", "EventSource", "sendBeacon", "import(", "srcdoc"):
        assert verboten not in html, verboten
    assert html.count("// BEGIN kern") == html.count("// END kern") == 1
    assert not re.search("[\u200b-\u200f\u2060\ufeff\u00ad]", html)   # keine unsichtbaren Zeichen im Quelltext
    zugriffe = [z for z in html.splitlines() if "localStorage." in z]
    assert len(zugriffe) == 3 and all("try {" in z and "catch (e)" in z for z in zugriffe)
    assert not list((ROOT / "site").rglob("pruefbogen*"))


def _punkte(text, abschnitt, md):
    """Punkte eines Abschnitts als (Name, Text ohne Auszeichnung)."""
    if md:
        teil = text.split(f"## {abschnitt}\n", 1)[1].split("\n## ", 1)[0]
        punkte = re.findall(r"^- \*\*(.+?)\*\*: (.+)$", teil, re.M)
        return [(n, re.sub(r"`", "", t)) for n, t in punkte]
    teil = text.split(f"<h3>{abschnitt}</h3>", 1)[1].split("<h3>", 1)[0]
    punkte = re.findall(r"<li><strong>(.+?)</strong>: (.+?)</li>", teil, re.S)
    return [(n, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t))) for n, t in punkte]


def test_pruefregeln_gleich_in_markdown_und_pruefbogen():
    """Die vier Urteile und die Regeln je Ebene stehen gleichlautend in explore/PRUEFREGELN_geokodierung.md und im
    Hilfebereich des Prüfbogens; die Prüfregeln bleiben kurz (höchstens etwa 40 Zeilen)."""
    md, html = REGELN.read_text(encoding="utf-8"), HTML.read_text(encoding="utf-8")
    assert len(md.splitlines()) <= 40
    for abschnitt, namen in (("Urteile", URTEILE), ("Je Ebene", EBENEN_REGELN)):
        a, b = _punkte(md, abschnitt, True), _punkte(html, abschnitt, False)
        assert [n for n, _ in a] == [n for n, _ in b] == list(namen), abschnitt
        assert a == b, abschnitt
    for text in (md, html):
        assert "Keine Namen oder Anschriften von Privatpersonen" in text and "keine Zitate aus Dokumenten" in text
    # „Was beurteilt wird“ gleichlautend; Anrede wie auf der Seite mit „Sie“ oder neutral, nie „du“
    teil_md = md.split("## Was beurteilt wird\n", 1)[1].split("\n## ", 1)[0]
    teil_html = html.split("<h3>Was beurteilt wird</h3>", 1)[1].split("<h3>", 1)[0]
    absaetze_md = [re.sub(r"\s+", " ", a).strip() for a in teil_md.split("\n\n") if a.strip()]
    absaetze_html = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", a)).strip()
                     for a in re.findall(r"<p>(.+?)</p>", teil_html, re.S)]
    assert absaetze_md == absaetze_html and len(absaetze_md) == 2
    hilfe = html.split('<details class="karte regeln" id="regeln">', 1)[1].split("</details>", 1)[0]
    for text in (md, hilfe):
        assert not re.search(r"\b(du|dir|dich|dein\w*)\b", text, re.I)
    assert "zeigt genauer, wie verlässlich die Karte ist" in md and "macht die Karte verlässlicher" not in md


# --- Prüfbogen im Browser (lokal und im Job „browser“) -------------------------------------------------------------

@pytest.mark.skipif(os.environ.get("RATSATLAS_BROWSER") != "1",
                    reason="nur mit RATSATLAS_BROWSER=1 (lokal und im Job „browser“; im Job „test“ ist Chromium nicht "
                           "installiert)")
def test_pruefbogen_im_browser(tmp_path):
    """Prüfbogen über file:// mit Playwright (tests/browser/pruefbogen.js): keine Anfrage ins Netz, keine Verstöße gegen
    die CSP, Beurteilen nur mit der Tastatur, gespeicherte Datei unterscheidet sich nur in Urteil und Anmerkung."""
    node = _node()
    ein = _schreiben(tmp_path / "stichprobe_geokodierung.tsv", [
        _zeile("strasse", nr=1, titel="[Testdaten] Umgestaltung\tmit Tab"),
        _zeile("strasse", nr=2, titel='[Testdaten] "Anführungszeichen" und Ümläute ßäöü'),
        _zeile("strasse", nr=3, titel="[Testdaten] Zweizeilig\nzweite Zeile"),
        _zeile("strasse", nr=4, titel="<img src=x onerror=alert(1)>", link="javascript:alert(1)"),
        _zeile("ortsteil_name", nr=5, ebene="ortsteil"),
        _zeile("ortsteil_name", " R ", nr=6, ebene="ortsteil"),
        _zeile("ortsteil_name", "vielleicht", nr=7, ebene="ortsteil"),
        _zeile("stadtbezirk_name", nr=8, ebene="stadtbezirk", fundstelle="a\r\nb")])
    r = subprocess.run([node, str(ROOT / "tests" / "browser" / "pruefbogen.js"), str(ein), str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    erg = json.loads(r.stdout)
    assert erg["netz"] == [] and erg["csp"] == [] and erg["konsole"] == [], erg
    assert all(v == [] for v in erg["axe"].values()), erg["axe"]
    assert erg["img"] == [0, True] and erg["zeile_ohne_link"] == 0 and erg["links"] == [["https:", "_blank", "noopener noreferrer"]]
    assert erg["fokus_sichtbar"] and erg["gedrueckt"] == []
    assert erg["dateiname"] == "stichprobe_geokodierung_beurteilt.tsv"
    # übernommen: nur gesetzte Urteile (fünf; ein entferntes zählt nicht)
    assert "übernommen (5 Urteile)" in erg["wieder"] and erg["nach_loeschen"] == ["1", "0", "0"]
    # nur Kopfzeile: kein Fehler bei N, Pfeilen, R und „TSV speichern“; Datei unverändert gespeichert
    leer = erg["leer"]
    assert leer["fokus"] == "zeile-titel" and leer["titel"] == "Keine Zeile zum Beurteilen" and leer["knoepfe"] == 0
    assert leer["gespeichert"] and leer["speicherstatus"].startswith("Gespeichert als nur_kopf_beurteilt.tsv (0 von 0")
    # Sonderfälle: Fokus nach dem Laden, Tasten im Dateifeld und auf dem Kontrollkästchen, N springt zu ungültig
    so = erg["sonder"]
    assert so["fokus"] == "zeile-titel" and so["erste"] == "Zeile 2 · 1 von 5" and so["nach_datei"] == "Zeile 3 · 2 von 5"
    assert so["nach_kontrollkaestchen"] == "Zeile 2 · 1 von 5" and so["sprung"] == ["Zeile 3 · 2 von 5", "Urteil: ungültig"]
    # Methoden mit Namen von Objekteigenschaften wie andere; lange Namen gekürzt
    gekuerzt = " … (gekürzt, vollständig in der Datei)"
    assert so["filter"] == ["alle Methoden (5)", "__proto__ (1)", "constructor (1)", "m" + "y" * 79 + gekuerzt + " (1)",
                            "strasse (1)", "toString (1)"]
    assert [z[0] for z in so["fortschritt"]] == ["__proto__", "constructor", "m" + "y" * 79 + gekuerzt, "strasse",
                                                  "toString"]
    assert so["fortschritt"][1] == ["constructor", "0", "1", "1"]
    # Felder mit 100 000 Zeichen: gekürzt angezeigt, schnell; keine seitliche Verschiebung bei 320, 375 und 1400 px
    assert max(so["lang"]) == 2000 + len(gekuerzt) and so["lang_ende"].endswith(gekuerzt)
    assert so["laden_ms"] < 3000 and so["lang_ms"] < 3000, so
    assert so["breite"] == {"320": 0, "375": 0, "1400": 0}
    assert so["filter_proto"] == ["Zeile 2 · 1 von 1 (__proto__)", "Link öffnen (example.invalid, neues Fenster)"]
    assert so["csp"] == []
    assert erg["gezogen"] == "gezogen.tsv: 8 Zeilen (UTF-8)."   # gleicher Inhalt, Zwischenstand gelöscht
    assert erg["schritte"][0] == ["r", "Zeile 2: richtig. Weiter mit Zeile 3, 2 von 8 (Methode strasse). Urteil: offen. "
                                       "Beurteilt 2 von 8."]
    vorher = list(csv.reader(open(ein, encoding="utf-8", newline=""), delimiter="\t"))
    nachher = list(csv.reader(open(erg["datei"], encoding="utf-8", newline=""), delimiter="\t"))
    iu, ia = KOPF.index(URTEIL), KOPF.index("anmerkung")
    assert [z[iu] for z in nachher[1:]] == ["richtig", "teilweise", "falsch", "", "richtig", "richtig", "vielleicht",
                                            "richtig"]
    assert [z[ia] for z in nachher[1:]] == ["", "", "", 'Bezirk richtig, „Stadtteil“ "falsch"\tTab\nzweite Zeile',
                                            "", "", "", ""]
    assert [[w for i, w in enumerate(z) if i not in (iu, ia)] for z in nachher] == \
        [[w for i, w in enumerate(z) if i not in (iu, ia)] for z in vorher]
    puffer = io.StringIO(newline="")
    csv.writer(puffer, delimiter="\t", lineterminator="\n").writerows(nachher)
    assert open(erg["datei"], "rb").read() == puffer.getvalue().encode("utf-8")
    print(json.dumps(erg, ensure_ascii=False))   # für den Bericht (pytest -s)
    sys.stdout.flush()
