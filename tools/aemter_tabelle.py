"""Ämtertabelle aus dem Geschäfts- und Dezernatsverteilungsplan der Stadt Köln (PDF) – einmalig je Plan, lokal, ohne Netz.

Aufruf (Python isoliert, alle Pfade als Argumente; das PDF lädt ein freigegebener Abruf, nie dieses Skript):
  python -I tools/aemter_tabelle.py --pdf <Pfad> --url <Adresse des PDFs> --abgerufen <Zeitpunkt ISO 8601>
                                    [--tabelle data/aemter/aemter_koeln.tsv]

Ergebnis: data/aemter/aemter_koeln.tsv (Spalten pipeline.aemter.SPALTEN). Zeilen anderer Pläne (anderes `gueltig_ab`)
bleiben stehen, die des gelesenen Plans werden ersetzt; derselbe PDF ergibt byte-gleich dieselbe Datei.
Erneute Prüfung: Dasselbe PDF (gleiche Prüfsumme) mit einem neuen `--abgerufen` ändert nur die Abrufzeit und verlängert
damit die Zeit, für die der Plan belegt ist (pipeline/aemter.py). Liefert die Stadt unter demselben Stand ein anderes PDF
(andere Prüfsumme), bricht das Skript ab: Ob der Inhalt auch für Vorlagen vor dem neuen Abruf gilt, ist dann offen und
wird von Hand entschieden (`--ersetzen` übernimmt den neuen Inhalt für den ganzen Stand).

Verfahren (Plan vom Stand 01.11.2026: eine Seite A3 quer, je Dezernat eine Spalte):
1. Wortkoordinaten mit `pdftotext -bbox` (poppler-utils), in Leserichtung der gedrehten Seite.
2. Kopf: Titel „Geschäfts- und Dezernatsverteilungsplan der Stadt Köln“ und „Stand: TT.MM.JJJJ“ (→ `gueltig_ab`); je
   Spalte „Dezernat <OB|I…IX>“. Der Bereich des Dezernats ist der unterste Block in Schrift 7,5 pt über den Einträgen
   (Zeilen höchstens 12 pt auseinander); darüber stehen Funktion und Name der Person, die nicht übernommen werden.
3. Spalten: linker Rand je Spalte = kleinstes x der Nummern im Bereich ihres Kopfes; ein Wort gehört zur Spalte, deren
   Rand (minus 2 pt) links von ihm liegt.
4. Einträge: Zeilen (gleiches y, ± 1 pt) mit Schrift unter 7 pt zwischen Kopf und Fußzeile. Eine Zeile am linken Rand
   beginnt einen Eintrag und muss mit einer Nummer beginnen (sonst Abbruch); eingerückte Zeilen setzen ihn fort. Ein
   Punkt „•“ steht als eigenes Wort knapp über seiner Zeile, „●“ in der Zeile. Bereiche wie „46/0 - 46/2“ bleiben eine
   Nummer („46/0-46/2“).
5. Ebene aus der Form der Nummer, gegengeprüft mit der Schriftgröße (sonst Abbruch): „VI/2“ Einheit des Dezernats
   (5,6 pt), „61“ und „02-1“ Dienststelle (6,5 pt), „612“, „64/1“, „02-6/4“ Untereinheit (5,2 pt, die Dienststelle
   davor muss in derselben Spalte stehen), vierstellig mit Punkt (5,6 pt). Übergeordnet ist die Dienststelle mit den
   ersten Ziffern; bei vierstelligen Nummern nur, wenn sie in derselben Spalte steht.
6. Name: Zeilen verbunden; Trennstrich am Zeilenende vor kleinem Buchstaben entfällt („Unternehmens-“ + „recht“), vor
   „und“, „oder“, „bzw.“, „sowie“ bleibt er mit Leerzeichen („Wasser- und …“), nach „/“ ohne Leerzeichen; kein
   Leerzeichen innen an Klammern. Kurzname = Abkürzung in Klammern am Ende („(DigIT)“, „(AWB)“), `eigenbetriebsaehnlich`
   = „e. E.“ im Namen (Legende: eigenbetriebsähnliche Einrichtung).
7. Prüfungen (sonst Abbruch): jede Nummer im Plan einmal, Einheiten des Dezernats mit dem Dezernat ihrer Spalte, alle
   Spalten mit Einträgen, Marker nur vor einer Zeile mit Nummer.
`kennung` = Dezernat/Nummer („VI/61“, „II/II/2“) in der Form der Beispiele für den Kopf der Verwaltungsvorlagen
(CLAUDE.md 5.3); an Köpfen echter Vorlagen ist die Form noch nicht gemessen.
"""
import argparse
import csv
import hashlib
import html
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import aemter  # noqa: E402

WORT = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
MARKER = ("•", "●")
DEZ_EINHEIT = re.compile(r"^(?P<dez>OB|[IVX]+)/\d{1,2}$")
DIENSTSTELLE = re.compile(r"^\d{2}(?:-\d)?$")
UNTER = re.compile(r"^(?:\d{3}|\d{2}/\d{1,2}(?:-\d{1,2})?|\d{2}-\d/\d{1,2})$")
VIERSTELLIG = re.compile(r"^\d{4}$")
# Schriftgröße (Höhe der Wortbox in pt) je Ebene, Abweichung bis 0,3 pt
HOEHE = {"dezernatseinheit": 5.6, "dienststelle": 6.5, "untereinheit": 5.2, "punktdienststelle": 5.6}
HOEHE_TOL = 0.3
INHALT_MAX = 7.0      # Einträge: Schrift unter 7 pt; Kopf, Bereich, Fußzeile und Legende darüber
BEREICH = (7.3, 7.7)  # Bereich des Dezernats im Kopf
ERGAENZUNG = ("und", "oder", "bzw.", "sowie")


def woerter(bbox):
    """Wörter je Seite aus der Ausgabe von pdftotext -bbox: [[(x0, y0, x1, y1, Text)]]."""
    return [[(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in WORT.findall(seite)]
            for seite in bbox.split("<page ")[1:]]


def _zeilen(ws, tol=1.0):
    """Wörter zu Zeilen nach y0: [[Wort nach x]] von oben nach unten."""
    zl = []
    for w in sorted(ws, key=lambda w: (w[1], w[0])):
        if zl and abs(zl[-1][0][1] - w[1]) <= tol:
            zl[-1].append(w)
        else:
            zl.append([w])
    return [sorted(z, key=lambda w: w[0]) for z in zl]


def _hoehe(w):
    return w[3] - w[1]


def verbinden(teile):
    """Zeilen eines Namens zu einem Text (Regeln 6 im Modultext)."""
    text = ""
    for t in teile:
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        if not text:
            text = t
        elif re.search(r"\w-$", text):
            erstes = t.split(" ")[0]
            if t[0].islower() and erstes not in ERGAENZUNG:
                text = text[:-1] + t
            elif t[0].islower():
                text += " " + t
            else:
                text += t
        elif text.endswith("/"):
            text += t
        else:
            text += " " + t
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", text))


def _ebene(code, marker):
    if marker:
        return "punktdienststelle" if VIERSTELLIG.match(code) else None
    if DEZ_EINHEIT.match(code):
        return "dezernatseinheit"
    if DIENSTSTELLE.match(code):
        return "dienststelle"
    if UNTER.match(code) or re.match(r"^\d{2}/\d{1,2}-\d{2}/\d{1,2}$", code):
        return "untereinheit"
    return None


def _code(tokens):
    """(Nummer, übrige Wörter) einer Zeile; Bereiche „46/0 - 46/2“ als eine Nummer."""
    code = tokens[0]
    if len(tokens) >= 3 and tokens[1] in ("-", "–") and re.match(r"^\d{2}/\d{1,2}$", code) \
            and re.match(r"^\d{2}/\d{1,2}$", tokens[2]) and tokens[2][:2] == code[:2]:
        return f"{code}-{tokens[2]}", tokens[3:]
    return code, tokens[1:]


def kopf(ws):
    """(Stand ISO, Spaltenköpfe [(Dezernat, Mitte x, y1)]) einer Seite; Abbruch ohne Titel oder Stand."""
    gross = " ".join(w[4] for z in _zeilen([w for w in ws if _hoehe(w) >= 12]) for w in z)
    if aemter.TITEL not in gross:
        raise ValueError(f"Titel „{aemter.TITEL}“ nicht gefunden")
    stand = None
    for z in _zeilen(ws):
        for i, w in enumerate(z[:-1]):
            if w[4] == "Stand:" and (m := re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", z[i + 1][4])):
                stand = f"{m[3]}-{m[2]}-{m[1]}"
    if not stand:
        raise ValueError("„Stand: TT.MM.JJJJ“ nicht gefunden")
    koepfe = []
    for z in _zeilen(ws):
        for i, w in enumerate(z[:-1]):
            if w[4] == "Dezernat" and aemter.DEZERNAT_ID.match(z[i + 1][4]) and abs(_hoehe(w) - 6.5) <= HOEHE_TOL:
                koepfe.append((z[i + 1][4], (w[0] + z[i + 1][2]) / 2, max(w[3], z[i + 1][3])))
    if not koepfe:
        raise ValueError("keine Spaltenköpfe „Dezernat …“")
    return stand, sorted(koepfe, key=lambda k: k[1])


def seite_lesen(ws, seite=1):
    """Einträge einer Seite: (Stand, [Zeile ohne Quelle, Abrufzeit und Prüfsumme])."""
    stand, koepfe = kopf(ws)
    kopf_unten = max(k[2] for k in koepfe)
    nummer = lambda t: bool(_ebene(t, None)) or VIERSTELLIG.match(t)
    inhalt = [w for w in ws if w[1] > kopf_unten and (_hoehe(w) < INHALT_MAX or w[4] in MARKER)]
    # Fußzeile und Legende: erste Zeile mit größerer Schrift unterhalb der ersten Nummer (ohne Marker)
    start = min(w[1] for w in inhalt if nummer(w[4]))
    fuss = min((w[1] for w in ws if w[1] > start and _hoehe(w) >= INHALT_MAX and w[4] not in MARKER), default=1e9)
    inhalt = [w for w in inhalt if start - 3 <= w[1] < fuss]
    raender = []
    for k, (dez, mitte, _) in enumerate(koepfe):
        links = koepfe[k - 1][1] if k else -1e9
        xs = [w[0] for w in inhalt if nummer(w[4]) and max(links, mitte - 80) < w[0] <= mitte]
        if not xs:
            raise ValueError(f"Spalte Dezernat {dez}: kein linker Rand gefunden")
        raender.append(min(xs))
    spalten = [[] for _ in koepfe]
    for w in inhalt:
        k = max((i for i, r in enumerate(raender) if w[0] >= r - 2), default=None)
        if k is None:
            raise ValueError(f"Wort links der ersten Spalte: {w}")
        spalten[k].append(w)

    zeilen = []
    for k, (dez, mitte, _) in enumerate(koepfe):
        zeilen.append(_dezernat(ws, dez, raender, k, kopf_unten, start, stand, seite))
        zeilen += _spalte(spalten[k], dez, raender[k], stand, seite)
    return stand, zeilen


def _dezernat(ws, dez, raender, k, kopf_unten, start, stand, seite):
    """Zeile des Dezernats: Bereich aus dem untersten Block in Schrift 7,5 pt zwischen Spaltenkopf und Einträgen."""
    rechts = raender[k + 1] - 2 if k + 1 < len(raender) else 1e9
    block = [w for w in ws if kopf_unten < w[1] < start and BEREICH[0] <= _hoehe(w) <= BEREICH[1]
             and raender[k] - 2 <= w[0] < rechts]
    zl = _zeilen(block)
    unten = []
    for z in reversed(zl):
        if unten and unten[0][0][1] - z[0][1] > 12:
            break
        unten.insert(0, z)
    name = verbinden([" ".join(w[4] for w in z) for z in unten])
    return _zeile(stand, dez, "", dez, "dezernat", "", name, "", f"Seite {seite}, Kopf der Spalte Dezernat {dez}")


def _zeile(stand, dez, code, kennung, ebene, ober, name, marker, fund):
    kurz = re.search(r"\(([A-ZÄÖÜ][A-Za-zÄÖÜäöü]*[A-Z][A-Za-z]*)\)\.?$", name)
    return {"gueltig_ab": stand, "dezernat": dez, "dienststelle": code, "kennung": kennung, "ebene": ebene,
            "uebergeordnet": ober, "name": name, "kurzname": kurz[1] if kurz else "",
            "eigenbetriebsaehnlich": "ja" if re.search(r"(?<!\w)e\.\s?E\b", name) else "",
            "markierung": marker, "fundstelle": fund}


def _spalte(ws, dez, rand, stand, seite):
    """Einträge einer Spalte in der Reihenfolge des Plans."""
    eintraege, offen_marker = [], None
    for z in _zeilen(ws):
        if len(z) == 1 and z[0][4] in MARKER:
            if offen_marker:
                raise ValueError(f"Dezernat {dez}: zwei Marker ohne Eintrag ({z[0]})")
            offen_marker = z[0]
            continue
        marker, x = "", z[0][0]
        if offen_marker:
            if not (0 < z[0][1] - offen_marker[1] < 4):
                raise ValueError(f"Dezernat {dez}: Marker ohne folgende Zeile ({offen_marker})")
            marker, x, offen_marker = offen_marker[4], offen_marker[0], None
        woerter_ = [w for w in z if w[4] not in MARKER]
        if any(w[4] in MARKER for w in z):
            marker = next(w[4] for w in z if w[4] in MARKER)
        h, y = max(_hoehe(w) for w in woerter_), woerter_[0][1]
        code, rest = _code([w[4] for w in woerter_])
        ebene = _ebene(code, marker)
        if x <= rand + 1.5 and ebene:
            if abs(h - HOEHE[ebene]) > HOEHE_TOL:
                raise ValueError(f"Dezernat {dez}: {code} mit Schrift {h:.1f} pt passt nicht zur Ebene {ebene}")
            eintraege.append({"code": code, "ebene": ebene, "marker": marker, "teile": [" ".join(rest)], "h": h,
                              "y": y})
            continue
        # Fortsetzung: eingerückt oder (wie „Versicherungen“ unter „30 Amt für Recht, Vergabe und“) am Rand ohne
        # Nummer, dann in derselben Schrift und höchstens 10 pt unter der vorigen Zeile
        letzte = eintraege[-1] if eintraege else None
        if not letzte or marker or (x <= rand + 1.5 and (abs(h - letzte["h"]) > HOEHE_TOL or y - letzte["y"] > 10)):
            raise ValueError(f"Dezernat {dez}: Zeile ohne Eintrag: {' '.join(w[4] for w in z)}")
        letzte["teile"].append(" ".join(w[4] for w in woerter_))
        letzte["y"] = y
    if offen_marker:
        raise ValueError(f"Dezernat {dez}: Marker am Ende der Spalte")
    if not eintraege:
        raise ValueError(f"Dezernat {dez}: keine Einträge")
    dienststellen = {e["code"] for e in eintraege if e["ebene"] == "dienststelle"}
    zeilen = []
    for n, e in enumerate(eintraege, 1):
        code, ober = e["code"], ""
        if e["ebene"] == "dezernatseinheit" and DEZ_EINHEIT.match(code)["dez"] != dez:
            raise ValueError(f"Dezernat {dez}: Einheit {code} eines anderen Dezernats")
        if e["ebene"] == "untereinheit":
            ober = re.match(r"^\d{2}(?:-\d(?=/))?", code)[0]
            if ober not in dienststellen:
                raise ValueError(f"Dezernat {dez}: {code} ohne Dienststelle {ober} in der Spalte")
        elif e["ebene"] == "punktdienststelle" and code[:2] in dienststellen:
            ober = code[:2]
        zeilen.append(_zeile(stand, dez, code, f"{dez}/{code}", e["ebene"], ober, verbinden(e["teile"]), e["marker"],
                             f"Seite {seite}, Spalte Dezernat {dez}, Eintrag {n}"))
    return zeilen


def plan_lesen(seiten):
    """(Stand, Zeilen) aller Seiten; jede Seite mit demselben Stand, jede Nummer einmal."""
    stand, zeilen = None, []
    for i, ws in enumerate(seiten, 1):
        s, z = seite_lesen(ws, i)
        if stand and s != stand:
            raise ValueError(f"Seite {i}: Stand {s} statt {stand}")
        stand = s
        zeilen += z
    nummern = [z["dienststelle"] for z in zeilen if z["ebene"] != "dezernat"]
    doppelt = sorted({n for n in nummern if nummern.count(n) > 1})
    if doppelt:
        raise ValueError(f"Nummern doppelt: {doppelt}")
    return stand, zeilen


def zusammenfuehren(alt, neu, ersetzen=False):
    """Zeilen anderer Pläne bleiben, die des neuen Plans ersetzen seine bisherigen; sortiert nach Stand, im Plan in der
    Reihenfolge des Plans. Hat derselbe Stand bisher eine andere Prüfsumme, Abbruch (außer mit ersetzen)."""
    stand = neu[0]["gueltig_ab"]
    bisher = {z.get("sha256") for z in alt if z["gueltig_ab"] == stand}
    if bisher and bisher != {neu[0].get("sha256")} and not ersetzen:
        raise ValueError(f"Plan Stand {aemter.stand_text(stand)}: anderes PDF (Prüfsumme {sorted(map(str, bisher))} → "
                         f"{neu[0].get('sha256')}); Übernahme nur mit --ersetzen")
    # sorted ist stabil: innerhalb eines Plans bleibt die Reihenfolge
    return sorted([z for z in alt if z["gueltig_ab"] != stand] + neu, key=lambda z: z["gueltig_ab"])


def schreiben(pfad, zeilen):
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(aemter.SPALTEN)
        w.writerows([[z[s] for s in aemter.SPALTEN] for z in zeilen])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--abgerufen", required=True, help="Zeitpunkt des Abrufs (ISO 8601, aus dem Abrufprotokoll)")
    ap.add_argument("--tabelle", default=str(aemter.TABELLE))
    ap.add_argument("--ersetzen", action="store_true",
                    help="anderes PDF unter demselben Stand übernehmen (nach Entscheidung von Hand)")
    a = ap.parse_args(argv)
    daten = Path(a.pdf).read_bytes()
    if not daten.startswith(b"%PDF-"):
        raise SystemExit(f"{a.pdf}: keine PDF-Datei")
    bbox = subprocess.run(["pdftotext", "-bbox", "-", "-"], input=daten, capture_output=True, check=True).stdout
    stand, zeilen = plan_lesen(woerter(bbox.decode("utf-8")))
    sha = hashlib.sha256(daten).hexdigest()
    zeilen = [{**z, "quelle": a.url, "abgerufen": a.abgerufen, "sha256": sha} for z in zeilen]
    alle = zusammenfuehren(aemter.lesen(a.tabelle), zeilen, a.ersetzen)
    schreiben(a.tabelle, alle)
    je = {e: sum(z["ebene"] == e for z in zeilen) for e in aemter.EBENEN}
    print(f"Plan Stand {aemter.stand_text(stand)}: {len(zeilen)} Zeilen ("
          + ", ".join(f"{e} {n}" for e, n in je.items()) + f"), sha256 {sha[:12]}… → {a.tabelle} "
          f"({len(alle)} Zeilen, {len({z['gueltig_ab'] for z in alle})} Pläne)")


if __name__ == "__main__":
    main()
