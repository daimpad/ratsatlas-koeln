"""Beträge je Produktbereich aus den Haushaltsplänen der Stadt Bonn (PDF), für die Themenseiten.

Phase 0 (haushalt/phase0/BERICHT.md): Offene Tabellen gibt es nur bis zum Entwurf 2021/22; die Haushaltspläne
2023/24 und 2025/26 liegen auf bonn.de als PDF je Produktbereich mit Textebene. Entscheidung 27.10.2026: Beträge aus
den PDFs, je Themenseite ein Produktbereich, Ist und Plan getrennt, ohne Finanzplanung ab 2027.

Einmaliger Schritt `haushalt-ausschnitt` (lokal, braucht pdftotext aus poppler-utils): lädt je Ausgabe die 17
Teilergebnispläne der Produktbereiche und den Gesamtergebnisplan, liest die Zeilen 10 (ordentliche Erträge),
17 (ordentliche Aufwendungen) und 18 (ordentliches Ergebnis) mit den Spalten des Tabellenkopfs und prüft je Spalte,
dass die Summe der Produktbereiche den Gesamtergebnisplan trifft. Ergebnis: data/haushalt/produktbereiche.tsv mit
Fundstelle (Datei, Seite) und data/haushalt/STAND.json. Die PDFs selbst kommen nicht ins Repository.

Ebenen 2 und 3 (haushalt/phase0/EBENE2.md, Entscheidung 28.10.2026): einmaliger Schritt `haushalt-ebenen` liest aus
denselben PDF die Aufwandsarten (Zeilen 11–16) der 17 Produktbereiche und die Teilergebnispläne der Produktgruppen
(Zeilen 11–17) über die Wortkoordinaten (pdftotext -bbox), weil teilweise gefüllte Zeilen das Lesen der Reihe nach
brechen. Leere Zellen zählen als 0. Prüfsummen je Spalte: Aufwandsarten = Zeile 17 (Produktbereich und Produktgruppe),
Summe der Produktgruppen = Zeile 17 des Produktbereichs aus produktbereiche.tsv. Ergebnis: data/haushalt/aufwandsarten.tsv
und produktgruppen.tsv, Vermerk in STAND.json. Aus dem Kopf der Produktgruppe werden nur Nummer, Name und
Organisationseinheit übernommen, nicht die verantwortliche Person.

Erweiterung (haushalt/phase0/ERWEITERUNG.md, Entscheidungen 03.11.2026; haushalt/PHASE5.md), nur mit
ERWEITERUNG_FREIGEGEBEN auf der Seite:
- `haushalt-ist2024` (einmalig, lokal): Teilergebnisrechnungen des festgestellten Jahresabschlusses 2024 (Teil 2) je
  Produktbereich und Produktgruppe, Zeilen 10–18, alle sechs Spalten (Ergebnis 2023, fortgeschriebener Ansatz 2024,
  davon Ermächtigungsübertragungen aus dem Vorjahr, Ist 2024, Vergleich Ansatz/Ist, Ermächtigungsübertragungen in das
  Folgejahr). Der Jahresabschluss hat keine Spaltennummern; die Spalten folgen aus Wörtern des Kopfs (koordinaten_ja).
  Beträge in Cent. Prüfsummen je Spalte: Zeilen 11–16 = 17, 10 − 17 = 18, Summe der Produktgruppen = Produktbereich,
  Summe der 17 Produktbereiche = Gesamtergebnisrechnung (mit einer im PDF belegten Abweichung, JA_ABWEICHUNG_GESAMT),
  Ergebnis 2023 = Ist 2023 des Haushaltsplans 2025/2026. Ergebnis: data/haushalt/jahresabschluss.tsv.
- `haushalt-investitionen` (einmalig, lokal): Teilfinanzplan A (S. 3 jedes Produktbereichs und je Produktgruppe),
  Zeilen 1–14, beide Ausgaben, ohne Verpflichtungsermächtigungen und Finanzplanung. Prüfsummen je Spalte: 1–5 = 6,
  7–12 = 13, 6 − 13 = 14, Summe der Produktgruppen = Produktbereich, Summe der 17 Produktbereiche = Gesamtfinanzplan
  (Zeilen 18–31). Ergebnis: data/haushalt/investitionen.tsv.
- `haushalt-pruefbogen-erweiterung` (einmalig, wird nicht überschrieben): data/export/haushalt/
  pruefbogen_haushalt_erweiterung.tsv.
- `haushalt-ist2024-investitionen` (einmalig, lokal): Teilfinanzrechnungen, Teil A: Zahlungsnachweis, des
  Jahresabschlusses 2024 je Produktbereich (16; PB 17 hat keine) und Produktgruppe, Zeilen 1–14 wie im Teilfinanzplan A
  (leere Zeilen druckt der Jahresabschluss nicht), Spalten 1, 2, 4, 5 in Cent, ohne die Ermächtigungsübertragungen.
  Prüfsummen wie beim Teilfinanzplan A, dazu Spalte 5 = 4 − 2, Summe = Gesamtfinanzrechnung (Zeilen 18–31, mit einer
  im PDF belegten Abweichung, JA_ABWEICHUNG_GESAMTFINANZ) und Ergebnis 2023 = Ist 2023 aus investitionen.tsv.
  Ergebnis: data/haushalt/jahresabschluss_investitionen.tsv; Prüfbogen-Ergänzung `haushalt-pruefbogen-erweiterung-finanz`
  (data/export/haushalt/pruefbogen_haushalt_erweiterung_finanz.tsv, wird nicht überschrieben).
Lokal liegende PDF nennt die Umgebungsvariable HAUSHALT_PDF (Ordner); sie werden über die SHA-256 erkannt.

Lizenz: Die Seiten der Stadt nennen keine Lizenz. Der Haushaltsplan ist Teil der Haushaltssatzung; als amtliches Werk
(§ 5 UrhG) dürfte er frei sein – eine Einschätzung, keine gesicherte Auskunft. Quelle und Stand werden genannt."""
import csv
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import config

BASIS = "https://www.bonn.de/medien-global/amt-20-und-21/haushaltsdaten/"
AUSGABEN = {
    "2023/2024": {"seite": "https://www.bonn.de/service-bieten/aktuelles-zahlen-fakten/haushaltsplan-2023-2024.php",
                  "gesamt": BASIS + "haushaltsplan-2023-24/gepp.pdf",
                  "pb": BASIS + "haushaltsplan-2023-24/produktbereiche/pb{:02d}.pdf"},
    "2025/2026": {"seite": "https://www.bonn.de/service-bieten/aktuelles-zahlen-fakten/haushaltsplan-2025-2026.php",
                  "gesamt": BASIS + "haushaltsplan-2025-2026/gepp.pdf",
                  "pb": BASIS + "haushaltsplan-2025-2026/produktbereiche/PB{:02d}.pdf"},
}
ZEILEN = {10: "Ordentliche Erträge", 17: "Ordentliche Aufwendungen", 18: "Ordentliches Ergebnis"}
ORDNER = config.ROOT / "data" / "haushalt"
TSV = ORDNER / "produktbereiche.tsv"
STAND = ORDNER / "STAND.json"
KOPF = ["ausgabe", "produktbereich", "name", "zeile", "zeile_name", "jahr", "art", "betrag", "datei", "seite"]
TOLERANZ = 1_500   # Euro je Spalte (Rundung in den Teilplänen)
AB_JAHR = 2022     # Themenseiten: Ist ab 2022 und Plan 2023–2026 (Entscheidung 27.10.2026; die Datei enthält mehr)
FREIGEGEBEN = True    # Prüfbogen im Gespräch vorgelegt und freigegeben am 27.10.2026 (haushalt/PHASE1.md)
PRUEFBOGEN = config.EXPORT / "haushalt" / "pruefbogen_haushalt.tsv"
# Ebenen 2 und 3: Aufwandsarten und Produktgruppen, Namen wie in den Teilergebnisplänen
AUFWANDSARTEN = {11: "Personalaufwendungen", 12: "Versorgungsaufwendungen",
                 13: "Aufwendungen für Sach- und Dienstleistungen", 14: "Bilanzielle Abschreibungen",
                 15: "Transferaufwendungen", 16: "Sonstige ordentliche Aufwendungen"}
AUFWANDSARTEN_TSV = ORDNER / "aufwandsarten.tsv"
AUFWANDSARTEN_KOPF = KOPF + ["leer"]
PRODUKTGRUPPEN_TSV = ORDNER / "produktgruppen.tsv"
PRODUKTGRUPPEN_KOPF = ["ausgabe", "produktbereich", "produktgruppe", "name", "einheit", "zeile", "zeile_name", "jahr",
                       "art", "betrag", "datei", "seite", "leer"]
EBENEN_FREIGEGEBEN = True   # Ebenen 2 und 3: Prüfbogen im Gespräch freigegeben 28.10.2026 (haushalt/PHASE3.md)
EBENEN_PRUEFBOGEN = config.EXPORT / "haushalt" / "pruefbogen_haushalt_ebenen.tsv"
SPALTE_PT = 4   # pt: größter Abstand des rechten Rands einer Zahl von der Lage, die ihre Spalte erwarten lässt
ARTEN = ("Ergebnis", "Ansatz", "Planung")   # Spaltenarten im Kopf der Teilergebnispläne
ARTEN_FINANZ = ARTEN + ("VE",)              # Teilfinanzplan A: dazu Verpflichtungsermächtigungen
WORT = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')


def _laden(url, versuche=3):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    for i in range(versuche):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except OSError:   # Abbruch der Verbindung (auch über einen Proxy): wiederholen
            if i == versuche - 1:
                raise
            time.sleep(5 * (i + 1))


def _pdf(url, sha256=None):
    """PDF aus dem Ordner der Umgebungsvariable HAUSHALT_PDF (rekursiv nach dem Dateinamen der Adresse, bei gleichem
    Namen entscheidet die SHA-256) oder von bonn.de. Mit sha256 bricht das Lesen ab, wenn die Datei abweicht."""
    ordner = os.environ.get("HAUSHALT_PDF")
    for p in sorted(Path(ordner).rglob(Path(url).name)) if ordner else []:
        b = p.read_bytes()
        if sha256 is None or hashlib.sha256(b).hexdigest() == sha256:
            return b
    b = _laden(url)
    if sha256 and hashlib.sha256(b).hexdigest() != sha256:
        raise ValueError(f"PDF weicht von STAND.json ab: {url}")
    return b


def _text(pdf, seiten=3):
    """Seiten 1–n als Text mit Layout (pdftotext); gibt Liste der Seitentexte zurück."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.pdf"
        p.write_bytes(pdf)
        out = subprocess.run(["pdftotext", "-layout", "-f", "1", "-l", str(seiten), str(p), "-"],
                             capture_output=True, check=True, text=True).stdout
    return out.split("\f")


ZAHL = re.compile(r"-?\d{1,3}(?:\.\d{3})*")


def spalten(seite):
    """Spalten des Tabellenkopfs: [(Art, Jahr)], z. B. („Ergebnis“, 2022), („Ansatz“, 2025), („Planung“, 2027)."""
    # ohne die erste Zeile („Haushaltsplan 2025/2026“) und ohne die Tabellenzeilen ab Zeile 1
    kopf = re.split(r"^\s*1\s+\S", seite.split("\n", 1)[-1], maxsplit=1, flags=re.M)[0]
    arten = re.findall(r"\b(Ergebnis|Ansatz|Planung)\b", kopf)
    # Spalten sind chronologisch; die Jahreszahlen stehen im Kopf teils in verschobenen Zeilen (Gesamtplan)
    jahre = sorted({int(j) for j in re.findall(r"\b(20[1-3]\d)\b", kopf)})
    if len(arten) != len(jahre) or len(arten) < 5:
        raise ValueError(f"Tabellenkopf nicht erkannt: {arten} {jahre}")
    return list(zip(arten, jahre))


def zeile(seite, nr, n):
    """Beträge einer Zeile (n Spalten) aus der Zeile mit ihrer Nummer; bei zweizeiliger Bezeichnung stehen die Werte
    in der Zeile mit der Nummer. Bricht ab, wenn die Zahl der Werte nicht passt (leere Zellen)."""
    m = re.search(rf"^\s*{nr}\s+[=+\-/]+\s*(.*)$", seite, re.M)
    if not m:
        return None
    werte = [int(x.replace(".", "")) for x in ZAHL.findall(m.group(1))]
    if not werte:
        return None
    if len(werte) != n:
        raise ValueError(f"Zeile {nr}: {len(werte)} statt {n} Werte")
    return werte


def auslesen(pdf):
    """(Name des Produktbereichs, Spalten, {Zeile: Werte}, Seite) aus einem Teilergebnisplan."""
    for i, seite in enumerate(_text(pdf), 1):
        if "ergebnisplan" not in seite.lower():
            continue
        cols = spalten(seite)
        m = re.search(r"(?:Produktbereich|Gesamtergebnisplan)\s*\n.*?(\d\.\d{2})\s+([^\n]+)", seite)
        name = m.group(2).strip() if m else ""
        werte = {nr: zeile(seite, nr, len(cols)) for nr in ZEILEN}
        if werte[17] is not None:
            return name, cols, werte, i
    raise ValueError("keine Seite mit Zeile 17 gefunden")


def ausschnitt():
    """Pipeline-Schritt `haushalt-ausschnitt` (einmalig): data/haushalt/produktbereiche.tsv und STAND.json."""
    ORDNER.mkdir(parents=True, exist_ok=True)
    rows, stand = [], {"abruf": datetime.now(timezone.utc).date().isoformat(), "ausgaben": {}}
    for ausgabe, q in AUSGABEN.items():
        gesamt_pdf = _laden(q["gesamt"])
        _, gcols, gwerte, _ = auslesen(gesamt_pdf)
        summe = {nr: [0] * len(gcols) for nr in ZEILEN}
        dateien = {"gesamt": {"url": q["gesamt"], "sha256": hashlib.sha256(gesamt_pdf).hexdigest()}}
        for pb in range(1, 18):
            url = q["pb"].format(pb)
            pdf = _laden(url)
            name, cols, werte, seite = auslesen(pdf)
            if cols != gcols:
                raise ValueError(f"{ausgabe} PB {pb:02d}: Spalten {cols} weichen vom Gesamtplan ab")
            dateien[f"{pb:02d}"] = {"url": url, "sha256": hashlib.sha256(pdf).hexdigest(), "name": name}
            for nr, ws in werte.items():
                for k, w in enumerate(ws or [0] * len(cols)):
                    summe[nr][k] += w
                    if ws is None:
                        continue
                    art, jahr = cols[k]
                    if art == "Planung":   # Finanzplanung ab dem dritten Jahr: nicht übernommen (Entscheidung 27.10.2026)
                        continue
                    rows.append([ausgabe, f"{pb:02d}", name, nr, ZEILEN[nr], jahr, art, w, Path(url).name, seite])
        abweichung = {nr: [s - (g or 0) for s, g in zip(summe[nr], gwerte[nr] or [0] * len(gcols))] for nr in ZEILEN}
        schlecht = {nr: a for nr, a in abweichung.items() if any(abs(x) > TOLERANZ for x in a)}
        if schlecht:
            raise ValueError(f"{ausgabe}: Summe der Produktbereiche trifft den Gesamtplan nicht: {schlecht}")
        stand["ausgaben"][ausgabe] = {"seite": q["seite"], "spalten": [f"{a} {j}" for a, j in gcols],
                                      "pruefsumme_abweichung_euro": {str(k): v for k, v in abweichung.items()},
                                      "dateien": dateien}
    with open(TSV, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(KOPF)
        wr.writerows(rows)
    stand["lizenz"] = ("Keine Lizenzangabe der Stadt Bonn; Haushaltsplan als Teil der Haushaltssatzung, amtliches Werk "
                       "nach § 5 UrhG (Einschätzung)")
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Haushalt: {len(rows)} Werte aus {len(AUSGABEN)} Ausgaben, Prüfsumme je Spalte innerhalb {TOLERANZ} € → {TSV}")


def lesen(path=TSV):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def reihe(pb, rows=None, zeile_nr=17, feld="produktbereich"):
    """Ist und Plan eines Produktbereichs (oder mit feld="produktgruppe" einer Produktgruppe): Ist aus der jüngsten
    Ausgabe, Plan (Ansatz des Haushaltsjahres) aus der Ausgabe des jeweiligen Doppelhaushalts. Gibt [(Jahr, Ist, Plan)]
    zurück (Euro)."""
    rows = lesen() if rows is None else rows
    sel = [r for r in rows if r[feld] == pb and int(r["zeile"]) == zeile_nr]
    ist, plan = {}, {}
    for r in sorted(sel, key=lambda r: r["ausgabe"]):   # spätere Ausgabe überschreibt Ist-Werte
        j, b = int(r["jahr"]), int(r["betrag"])
        if r["art"] == "Ergebnis":
            ist[j] = (b, r)
        elif r["art"] == "Ansatz" and j in {int(x) for x in r["ausgabe"].split("/")}:   # Ansatz des Haushaltsjahres
            plan[j] = (b, r)
    return [(j, ist.get(j), plan.get(j)) for j in sorted(set(ist) | set(plan))]


def pruefbogen(themen=None):
    """Pipeline-Schritt `haushalt-pruefbogen` (einmalig): je Themenseite die gezeigten Werte mit Fundstelle zur
    Prüfung von Hand gegen das PDF. Wird nicht überschrieben."""
    from .themenseiten import ALLE
    if PRUEFBOGEN.exists():
        print(f"Prüfbogen besteht bereits: {PRUEFBOGEN}")
        return
    rows, stand = lesen(), json.loads(STAND.read_text(encoding="utf-8"))
    out = []
    for t in themen or ALLE:
        if not t.produktbereich:
            continue
        for j, ist, plan in reihe(t.produktbereich, rows):
            if j < AB_JAHR:
                continue
            for art, x in (("Ergebnis (Ist)", ist), ("Ansatz (Plan)", plan)):
                if not x:
                    continue
                b, r = x
                url = stand["ausgaben"][r["ausgabe"]]["dateien"][t.produktbereich]["url"]
                out.append([t.titel, f"{t.produktbereich} {r['name']}", j, art, b, f"{b / 1e6:.1f}".replace(".", ","),
                            r["ausgabe"], f"{url}#page={r['seite']}", "", ""])
    PRUEFBOGEN.parent.mkdir(parents=True, exist_ok=True)
    with open(PRUEFBOGEN, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["thema", "produktbereich", "jahr", "art", "betrag_euro", "mio_euro", "ausgabe", "fundstelle",
                     "urteil", "bemerkung"])
        wr.writerows(out)
    print(f"Prüfbogen Haushalt: {len(out)} Werte → {PRUEFBOGEN}")


# --- Ebenen 2 und 3: Aufwandsarten und Produktgruppen über die Wortkoordinaten ---

def woerter(bbox):
    """Wörter je Seite aus der HTML-Ausgabe von pdftotext -bbox: [[(x0, y0, x1, y1, Text)]] in Punkt."""
    return [[(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in WORT.findall(seite)]
            for seite in bbox.split("<page ")[1:]]


def _seiten(pdf):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.pdf"
        p.write_bytes(pdf)
        out = subprocess.run(["pdftotext", "-bbox", str(p), "-"], capture_output=True, check=True, text=True).stdout
    return woerter(out)


def _textzeilen(ws, tol=2.5):
    """Wörter nach ihrer Mitte in y zu Zeilen: [(y, [Wörter nach x])]."""
    zl = []
    for w in sorted(ws, key=lambda w: (w[1] + w[3]) / 2):
        y = (w[1] + w[3]) / 2
        if zl and abs(zl[-1][0] - y) <= tol:
            zl[-1][1].append(w)
        else:
            zl.append([y, [w]])
    return [(y, sorted(z, key=lambda w: w[0])) for y, z in zl]


def _gruppen(z, luecke=15):
    """Wörter einer Zeile in Gruppen, getrennt an Lücken über luecke pt (Spalten des Seitenkopfs)."""
    out = []
    for w in z:
        if out and w[0] - out[-1][-1][2] <= luecke:
            out[-1].append(w)
        else:
            out.append([w])
    return [[w[4] for w in g] for g in out]


def kopf(ws):
    """(Produktbereich, Produktgruppe, Name, Organisationseinheit) aus dem Seitenkopf; Produktgruppe None auf Seiten des
    Produktbereichs. Die Gruppe „verantwortlich: …“ links im Kopf nennt eine Person und wird nicht gelesen."""
    pb = pg = name = einheit = None
    for _, z in _textzeilen(ws)[:4]:
        gruppen = _gruppen(z)
        for i, g in enumerate(gruppen):
            if re.fullmatch(r"1\.\d{2}", g[0]):
                pb = g[0][2:]
                if i + 1 < len(gruppen):
                    einheit = " ".join(gruppen[i + 1])
            elif re.fullmatch(r"1\.\d{2}\.\d{2}", g[0]):   # Name bis vor „Nr. Profitcenter“
                pg, name = g[0], " ".join(g[1:g.index("Nr.")] if "Nr." in g else g[1:])
    return pb, pg, name, einheit


def _tabelle(zl, y_start, ist_betrag, naehe=None, werte_daneben=False):
    """Tabellenzeilen ab y_start: ({Nummer: (y, Wörter)}, {Nummer: [(y, x, Wort)] der Bezeichnung}).

    Tabellenzeilen beginnen links mit ihrer Nummer; Zeilen ohne Nummer (mehrzeilige Bezeichnung) gehören zur
    nächstgelegenen nummerierten Zeile. Mit naehe (pt) zählen Zeilen ohne Nummer weiter weg nicht (Seitenfuß,
    Zwischenüberschriften wie „Einzahlungen“ im Teilfinanzplan); enthalten sie einen Betrag, bricht das Lesen ab.
    Mit werte_daneben zählen Beträge in einer Zeile ohne Nummer zur nächstgelegenen nummerierten Zeile (in den
    Teilfinanzrechnungen des Jahresabschlusses steht die Nummer teils mittig neben einer zweizeiligen Bezeichnung, die
    Beträge in deren zweiter Zeile)."""
    tabelle = [(y, z) for y, z in zl if y > y_start]
    nummeriert = {}
    for y, z in tabelle:
        if re.fullmatch(r"\d{1,2}", z[0][4]) and z[0][0] <= 100:
            if int(z[0][4]) in nummeriert:
                raise ValueError(f"Zeile {z[0][4]} doppelt")
            nummeriert[int(z[0][4])] = (y, z)
    if not nummeriert:
        raise ValueError("keine Tabellenzeilen gefunden")
    bezeichnung = defaultdict(list)   # Zeile → [(y, x, Wort)] ohne Beträge, Nummer und Rechenzeichen
    daneben = defaultdict(list)       # Zeile → Beträge aus Zeilen ohne Nummer (nur mit werte_daneben)
    for y, z in tabelle:
        nr = min(nummeriert, key=lambda n: abs(nummeriert[n][0] - y))
        eigene = z is nummeriert[nr][1]
        if not eigene and naehe is not None and abs(nummeriert[nr][0] - y) > naehe:
            if any(ist_betrag(w) for w in z):
                raise ValueError(f"Betrag außerhalb der Tabellenzeilen: {' '.join(w[4] for w in z)}")
            continue
        for w in z[1:] if eigene else z:
            if not ist_betrag(w) and not (eigene and re.fullmatch(r"[=+\-/]+", w[4])):
                bezeichnung[nr].append((y, w[0], w[4]))
            elif werte_daneben and not eigene and ist_betrag(w):
                daneben[nr].append(w)
    for nr, ws in daneben.items():
        y, z = nummeriert[nr]
        nummeriert[nr] = (y, z + ws)
    return nummeriert, bezeichnung


def _werte(nummeriert, bezeichnung, nummern, n, spalte, ist_betrag, zahl):
    """{Zeile: [Betrag oder None je Spalte]} der erwarteten Zeilen; die Bezeichnung jeder Zeile (auch mehrzeilig) muss
    dem erwarteten Namen entsprechen. spalte(Wort) gibt die Spalte des Betrags oder None."""
    werte = {}
    for nr, name in nummern.items():
        if nr not in nummeriert:
            raise ValueError(f"Zeile {nr} nicht gefunden")
        gelesen = " ".join(t for *_, t in sorted(bezeichnung[nr]))
        if gelesen not in ((name,) if isinstance(name, str) else name):   # mehrere zulässige Schreibweisen als Tupel
            raise ValueError(f"Zeile {nr}: Bezeichnung „{gelesen}“ statt „{name}“")
        werte[nr] = [None] * n
        for w in nummeriert[nr][1]:
            if not ist_betrag(w):
                continue
            k = spalte(w)
            if k is None:
                raise ValueError(f"Zeile {nr}: Wert {w[4]} keiner Spalte zuzuordnen")
            if werte[nr][k] is not None:
                raise ValueError(f"Zeile {nr}: zwei Werte in Spalte {k + 1}")
            werte[nr][k] = zahl(w[4])
    return werte


def koordinaten(ws, nummern=None, arten=ARTEN, naehe=None):
    """Spalten [(Art, Jahr)] und {Zeile: [Betrag oder None je Spalte]} einer Seite des Teilergebnisplans (mit
    arten=ARTEN_FINANZ und naehe=NAEHE_PT auch des Teilfinanzplans A, siehe _tabelle).

    Die Spalten stehen in der Zeile mit den Spaltennummern 1 … n, Art und Jahr darüber. Die Beträge sind rechtsbündig,
    ihr rechter Rand liegt in festem Abstand rechts der Mitte der Spaltennummer (meist 31–32 pt); der häufigste Abstand
    der Seite bestimmt die Spalte jedes Betrags. So bleibt die Spalte auch bei teilweise gefüllten Zeilen eindeutig. Die
    Bezeichnung jeder gelesenen Zeile (auch zweizeilig) muss dem erwarteten Namen entsprechen. Bricht ab, wenn etwas
    nicht passt."""
    nummern = AUFWANDSARTEN if nummern is None else nummern
    zl = _textzeilen(ws)
    kopf_ = next((z for _, z in zl if len(z) >= 5 and [w[4] for w in z] == [str(i) for i in range(1, len(z) + 1)]), None)
    if not kopf_:
        raise ValueError("Zeile mit den Spaltennummern nicht gefunden")
    y_kopf, mitten = (kopf_[0][1] + kopf_[0][3]) / 2, [(w[0] + w[2]) / 2 for w in kopf_]
    abstand = (mitten[-1] - mitten[0]) / (len(mitten) - 1)
    arten_, jahre = [None] * len(mitten), [None] * len(mitten)
    oben = min((y for y, z in zl if any(w[4] in arten for w in z)), default=y_kopf)
    for y, z in zl:
        if not oben <= y < y_kopf - 1:   # nur der Tabellenkopf über den Spaltennummern
            continue
        for w in z:
            k = min(range(len(mitten)), key=lambda i: abs(mitten[i] - (w[0] + w[2]) / 2))
            if abs(mitten[k] - (w[0] + w[2]) / 2) > abstand / 2:
                continue
            if w[4] in arten:
                arten_[k] = arten_[k] or w[4]
            elif re.fullmatch(r"20[1-3]\d", w[4]):
                jahre[k] = int(w[4])
    if None in arten_ or None in jahre:
        raise ValueError(f"Tabellenkopf nicht erkannt: {arten_} {jahre}")
    ist_betrag = lambda w: ZAHL.fullmatch(w[4]) and w[2] > mitten[0]   # rechter Rand rechts der ersten Spaltenmitte
    nummeriert, bezeichnung = _tabelle(zl, y_kopf + 1, ist_betrag, naehe)
    # je Betrag genau eine Spaltenmitte im Fenster einer Spaltenbreite; der häufigste Abstand gilt für die ganze Seite
    abstaende = Counter(round(w[2] - c) for _, z in nummeriert.values() for w in z if ist_betrag(w)
                        for c in mitten if -10 <= w[2] - c < abstand - 10)
    anker = [c + (abstaende.most_common(1)[0][0] if abstaende else 0) for c in mitten]

    def spalte(w):
        k = min(range(len(anker)), key=lambda i: abs(anker[i] - w[2]))
        return k if abs(anker[k] - w[2]) <= SPALTE_PT else None

    werte = _werte(nummeriert, bezeichnung, nummern, len(anker), spalte, ist_betrag, lambda t: int(t.replace(".", "")))
    return list(zip(arten_, jahre)), werte


def pruefsumme(teile, ganze, was, toleranz=TOLERANZ, ziel="Zeile 17", bekannt=None):
    """Summe der Teile [(Schlüssel, Betrag)] gegen das Ganze {Schlüssel: Betrag} je Schlüssel (Ausgabe, Einheit, Jahr,
    Art). Gibt (Zahl der Spalten, größte Abweichung) zurück; bricht ab, wenn eine Spalte fehlt oder mehr als die
    Toleranz abweicht. Betrag und Toleranz in derselben Einheit (Euro oder Cent).

    bekannt {Schlüssel: Abweichung}: im PDF selbst belegte Abweichungen (mit Fundstelle im Bericht). Sie zählen nur
    in genau dieser Höhe (± Toleranz) und nicht zur größten Abweichung; tritt eine nicht mehr auf, bricht die Prüfung
    ebenfalls ab."""
    bekannt = bekannt or {}
    summe = defaultdict(int)
    for k, b in teile:
        summe[k] += b
    if set(summe) != set(ganze):
        raise ValueError(f"{was}: Spalten passen nicht zu {ziel}: {sorted(set(summe) ^ set(ganze))[:5]}")
    if set(bekannt) - set(ganze):
        raise ValueError(f"{was}: bekannte Abweichung ohne Spalte: {sorted(set(bekannt) - set(ganze))}")
    abweichung = {k: summe[k] - ganze[k] - bekannt.get(k, 0) for k in ganze}
    weg = {k: a for k, a in bekannt.items() if abs(summe[k] - ganze[k]) <= toleranz}
    if weg:
        raise ValueError(f"{was}: bekannte Abweichung tritt nicht mehr auf: {weg}")
    schlecht = {k: a for k, a in abweichung.items() if abs(a) > toleranz}
    if schlecht:
        raise ValueError(f"{was}: Summe trifft {ziel} nicht: {dict(list(schlecht.items())[:10])}")
    return len(abweichung), max((abs(a) for a in abweichung.values()), default=0)


def pruefsummen(aufwand, gruppen, produktbereiche):
    """Die drei Prüfsummen der Ebenen 2 und 3 je Spalte; bricht bei Abweichung ab. Gibt {Prüfung: (Spalten, größte
    Abweichung)} zurück."""
    ausgaben = {r["ausgabe"] for r in aufwand + gruppen}
    pb = lambda r: (r["ausgabe"], r["produktbereich"], int(r["jahr"]), r["art"])
    pg = lambda r: (r["ausgabe"], r["produktgruppe"], int(r["jahr"]), r["art"])
    z17 = {pb(r): int(r["betrag"]) for r in produktbereiche if int(r["zeile"]) == 17 and r["ausgabe"] in ausgaben}
    teile = [r for r in gruppen if int(r["zeile"]) != 17]
    summen = [r for r in gruppen if int(r["zeile"]) == 17]
    return {
        "aufwandsarten_produktbereich": pruefsumme([(pb(r), int(r["betrag"])) for r in aufwand], z17,
                                                   "Aufwandsarten der Produktbereiche"),
        "aufwandsarten_produktgruppe": pruefsumme([(pg(r), int(r["betrag"])) for r in teile],
                                                  {pg(r): int(r["betrag"]) for r in summen}, "Aufwandsarten der Produktgruppen"),
        "produktgruppen_produktbereich": pruefsumme([(pb(r), int(r["betrag"])) for r in summen], z17,
                                                    "Summe der Produktgruppen"),
    }


def _zellen(kopf_, cols, werte, ausgabe, datei, seite, namen=None):
    """TSV-Zeilen je Zeile und Spalte ohne Finanzplanung; leere Zellen als 0 mit Vermerk."""
    namen = namen or {**AUFWANDSARTEN, 17: ZEILEN[17]}
    for nr, ws in werte.items():
        for (art, jahr), w in zip(cols, ws):
            if art == "Planung":   # Finanzplanung ab dem dritten Jahr: nicht übernommen (wie Zeile 17)
                continue
            yield {"ausgabe": ausgabe, **kopf_, "zeile": nr, "zeile_name": namen[nr], "jahr": jahr, "art": art,
                   "betrag": w or 0, "datei": Path(datei["url"]).name, "seite": seite, "leer": "ja" if w is None else ""}


def teilergebnisplaene(stand):
    """Erste Seite jedes Teilergebnisplans (Produktbereich auf S. 1, danach die Produktgruppen) beider Ausgaben:
    (Ausgabe, Produktbereich, Produktgruppe oder None, Name, Organisationseinheit, Datei, Seite, Wörter). Bricht ab,
    wenn eine Seite nicht passt."""
    for ausgabe in AUSGABEN:
        st, gesehen = stand["ausgaben"][ausgabe], set()
        for pb in (f"{i:02d}" for i in range(1, 18)):
            datei = st["dateien"][pb]
            seiten = _seiten(_pdf(datei["url"], datei["sha256"]))
            if kopf(seiten[0])[:2] != (pb, None) or "Teilergebnisplan" not in {w[4] for w in seiten[0]}:
                raise ValueError(f"{ausgabe} PB {pb}: Seite 1 ist nicht der Teilergebnisplan des Produktbereichs")
            for s, ws in enumerate(seiten, 1):
                texte = {w[4] for w in ws}
                if not {"Teilergebnisplan", "Personalaufwendungen"} <= texte:   # erste Seite eines Teilergebnisplans
                    continue
                _, pg, name, einheit = kopf(ws)
                if s > 1 and not pg:
                    raise ValueError(f"{ausgabe} PB {pb} S. {s}: Teilergebnisplan ohne Produktgruppe")
                if pg and (not pg.startswith(f"1.{pb}.") or pg in gesehen):
                    raise ValueError(f"{ausgabe} PB {pb} S. {s}: Produktgruppe {pg} unerwartet oder doppelt")
                gesehen.add(pg)
                yield ausgabe, pb, pg, name, einheit, datei, s, ws


def _spalten_wie_stand(cols, stand, ausgabe, pb, s):
    if [f"{a} {j}" for a, j in cols] != stand["ausgaben"][ausgabe]["spalten"]:
        raise ValueError(f"{ausgabe} PB {pb} S. {s}: Spalten {cols} weichen von STAND.json ab")


def ebenen():
    """Pipeline-Schritt `haushalt-ebenen` (einmalig, lokal): data/haushalt/aufwandsarten.tsv (Zeilen 11–16 je
    Produktbereich, S. 1) und produktgruppen.tsv (Zeilen 11–17 je Produktgruppe), Vermerk in STAND.json. Liest dieselben
    PDF wie `haushalt-ausschnitt` (SHA-256 laut STAND.json)."""
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    aufwand, gruppen, zahl = [], [], {}
    for ausgabe, pb, pg, name, einheit, datei, s, ws in teilergebnisplaene(stand):
        cols, werte = koordinaten(ws, AUFWANDSARTEN if s == 1 else {**AUFWANDSARTEN, 17: ZEILEN[17]})
        _spalten_wie_stand(cols, stand, ausgabe, pb, s)
        if s == 1:
            aufwand += _zellen({"produktbereich": pb, "name": datei["name"]}, cols, werte, ausgabe, datei, s)
        else:
            zahl[ausgabe] = zahl.get(ausgabe, 0) + 1
            gruppen += _zellen({"produktbereich": pb, "produktgruppe": pg, "name": name, "einheit": einheit or ""},
                               cols, werte, ausgabe, datei, s)
    pruefung = pruefsummen(aufwand, gruppen, lesen())
    for path, kopf_, rows in ((AUFWANDSARTEN_TSV, AUFWANDSARTEN_KOPF, aufwand),
                              (PRODUKTGRUPPEN_TSV, PRODUKTGRUPPEN_KOPF, gruppen)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, kopf_, delimiter="\t", lineterminator="\n")
            wr.writeheader()
            wr.writerows(rows)
    stand.pop("aufwandsarten", None)
    stand["ebenen"] = {"abruf": datetime.now(timezone.utc).date().isoformat(),
                       "zeilen": {str(k): v for k, v in AUFWANDSARTEN.items()}, "produktgruppen": zahl,
                       "pruefsummen": {k: {"spalten": n, "groesste_abweichung_euro": a} for k, (n, a) in pruefung.items()},
                       "toleranz_euro": TOLERANZ,
                       "leere_zellen": {"produktbereiche": sum(r["leer"] == "ja" for r in aufwand),
                                        "produktgruppen": sum(r["leer"] == "ja" for r in gruppen)}}
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Ebenen: {len(aufwand)} Werte der Produktbereiche, {len(gruppen)} der Produktgruppen ({zahl}); Prüfsummen "
          + ", ".join(f"{k} {n} Spalten bis {a} €" for k, (n, a) in pruefung.items()))


def pruefbogen_ebenen():
    """Pipeline-Schritt `haushalt-pruefbogen-ebenen` (einmalig): etwa 30 Zellen der Ebenen 2 und 3 zur Prüfung von Hand
    gegen das PDF. Darunter die Sonderfälle (negative Werte, teilweise gefüllte Zeilen, umbenannte Produktgruppen,
    0 € im Plan, größte Produktgruppe) und eine Stichprobe der Werte der Seite haushalt/. Wird nicht überschrieben."""
    if EBENEN_PRUEFBOGEN.exists():
        print(f"Prüfbogen besteht bereits: {EBENEN_PRUEFBOGEN}")
        return
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    zellen = {}
    for ebene, path, feld in (("Produktbereich", AUFWANDSARTEN_TSV, "produktbereich"),
                              ("Produktgruppe", PRODUKTGRUPPEN_TSV, "produktgruppe")):
        for r in lesen(path):
            zellen[(ebene, r["ausgabe"], r[feld], int(r["zeile"]), int(r["jahr"]), r["art"])] = r
    neu, alt = max(AUSGABEN), min(AUSGABEN)
    ist = max(k[4] for k in zellen if k[1] == neu and k[5] == "Ergebnis")
    ansichten = [(int(j), "Ansatz") for j in reversed(neu.split("/"))] + [(ist, "Ergebnis")]   # wie haushalt/
    gezeigt = lambda k: k[1] == neu and k[4:] in ansichten
    erst_gezeigt = lambda k: (not gezeigt(k), k)
    auswahl = defaultdict(list)
    # negative Werte der Seite (Ebenen 2 und 3); Zeile 17 einer Produktgruppe auch außerhalb der Ansichten
    for k, r in sorted(zellen.items()):
        if int(r["betrag"]) < 0 and k[1] == neu and (gezeigt(k) or k[0] == "Produktbereich" or k[3] == 17):
            auswahl[k].append("negativer Wert")
    # teilweise gefüllte Zeilen: alle der Produktbereiche, zwei der Produktgruppen; je eine gefüllte und eine leere Zelle
    zeilen = defaultdict(list)
    for k in sorted(zellen):
        zeilen[k[:4]].append(k)
    teilweise = [ks for ks in zeilen.values() if {zellen[k]["leer"] for k in ks} == {"", "ja"}]
    for ks in [ks for ks in teilweise if ks[0][0] == "Produktbereich"] + \
              [ks for ks in teilweise if ks[0][0] == "Produktgruppe" and ks[0][1] == neu][:2]:
        for k in (min((k for k in ks if zellen[k]["leer"] == ""), key=erst_gezeigt),
                  min((k for k in ks if zellen[k]["leer"] == "ja"), key=erst_gezeigt)):
            auswahl[k].append("teilweise gefüllte Zeile")
    # umbenannte Produktgruppen: Zeile 17 im Ansatz des ersten Haushaltsjahres beider Ausgaben
    namen = defaultdict(dict)
    for k, r in zellen.items():
        if k[0] == "Produktgruppe":
            namen[k[2]][k[1]] = r["name"]
    for pg, n in sorted(namen.items()):
        if len(set(n.values())) > 1:
            for a in (alt, neu):
                auswahl[("Produktgruppe", a, pg, 17, int(a.split("/")[0]), "Ansatz")].append("Name geändert")
    # Produktgruppen mit 0 € im Plan eines Haushaltsjahres (nur in der Tabelle), die erste davon
    null = sorted(k for k, r in zellen.items() if k[0] == "Produktgruppe" and k[3] == 17 and gezeigt(k)
                  and k[5] == "Ansatz" and int(r["betrag"]) == 0)
    if null:
        auswahl[null[0]].append("0 € im Plan")
    # größte Produktgruppe im ersten Plan der Seite
    gross = max((k for k in zellen if k[0] == "Produktgruppe" and k[3] == 17 and k[1] == neu and k[4:] == ansichten[0]),
                key=lambda k: int(zellen[k]["betrag"]))
    auswahl[gross].append("größte Produktgruppe")
    # Stichprobe in jedem zweiten Produktbereich, abwechselnd eine Produktgruppe (Zeile 17, Ebene 2) und eine
    # Aufwandsart einer Produktgruppe (Ebene 3); Produktgruppe, Ansicht und Zeile wechseln
    gruppen = sorted({k[2] for k in zellen if k[0] == "Produktgruppe" and k[1] == neu})
    for i, pb in enumerate(f"{n:02d}" for n in range(1, 18, 2)):
        pgs = [g for g in gruppen if g.startswith(f"1.{pb}.")]
        nr, grund = (17, "Stichprobe Ebene 2") if i % 2 == 0 else (11 + (i // 2) % 6, "Stichprobe Ebene 3")
        auswahl[("Produktgruppe", neu, pgs[i % len(pgs)], nr, *ansichten[i % 3])].append(grund)
    out = []
    for k, gruende in sorted(auswahl.items()):
        r = zellen[k]
        url = stand["ausgaben"][r["ausgabe"]]["dateien"][r["produktbereich"]]["url"]
        einheit = f"{k[2]} {r['name']}" if k[0] == "Produktgruppe" else f"{r['produktbereich']} {r['name']}"
        out.append([k[0], einheit, f"{r['zeile']} {r['zeile_name']}", r["jahr"], r["art"], r["betrag"], r["leer"],
                    r["ausgabe"], f"{url}#page={r['seite']}", r["seite"], ", ".join(gruende), ""])
    EBENEN_PRUEFBOGEN.parent.mkdir(parents=True, exist_ok=True)
    with open(EBENEN_PRUEFBOGEN, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["ebene", "einheit", "zeile", "jahr", "art", "betrag_euro", "leer", "ausgabe", "datei", "seite",
                     "auswahl", "pruefung"])
        wr.writerows(out)
    print(f"Prüfbogen Ebenen: {len(out)} Zellen → {EBENEN_PRUEFBOGEN}")



# --- Erweiterung: Ist 2024 aus dem Jahresabschluss 2024 und Investitionen aus dem Teilfinanzplan A ---

JAHRESABSCHLUSS = {
    "seite": "https://www.bonn.de/service-bieten/aktuelles-zahlen-fakten/jahresabschluesse.php",
    "url": "https://www.bonn.de/medien-global/amt-20-und-21/jahresabschluesse/Jahresabschluss-2024_Teil-2.pdf",
    "sha256": "254b1b5f5bc0da943cb70b66ab3e94de70a93b24982a8d7da8d7e22e3c3d9609",   # Last-Modified 16.03.2026
    "quelle": "Jahresabschluss 2024",
}
# Spalten der Teilergebnisrechnung (ohne Spaltennummern im PDF): Wort im Kopf, das die Spalte kennzeichnet, und Art
JA_SPALTEN = (("Vorjahres", "Ergebnis"),                                     # 1 Ergebnis des Vorjahres
              ("fortgeschriebener", "Ansatz fortgeschrieben"),               # 2 fortgeschriebener Ansatz des Haushaltsjahres
              ("davon", "davon Ermächtigungsübertragung aus dem Vorjahr"),   # 3 Teil von Spalte 2
              ("Ist-Ergebnis", "Ergebnis"),                                  # 4 Ist-Ergebnis des Haushaltsjahres
              ("Vergleich", "Vergleich Ansatz/Ist"),                         # 5 Spalte 4 minus Spalte 2
              ("Folgejahr", "Ermächtigungsübertragung in das Folgejahr"))    # 6
JA_KOPF = ("Ergebnis des Vorjahres", "fortgeschriebener Ansatz des Haushaltsjahres",
           "davon Ermächtigungsübertragungen aus dem Vorjahr", "Ist-Ergebnis des Haushaltsjahres",
           "Vergleich Ansatz/Ist (Sp. 4 ./. Sp. 2)", "Ermächtigungsübertragungen in das Folgejahr")   # Wortlaut im Kopf
JA_ZEILEN = {10: ZEILEN[10], **AUFWANDSARTEN, 17: ZEILEN[17],
             18: "Ergebnis der laufenden Verwaltungstätigkeit (Zeilen 10 und 17)"}   # im Plan „Ordentliches Ergebnis“
ZAHL_CENT = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|0")   # in der Gesamtrechnung steht 0 teils ohne Cent
JAHRESABSCHLUSS_TSV = ORDNER / "jahresabschluss.tsv"
JAHRESABSCHLUSS_KOPF = ["quelle", "ebene", "produktbereich", "produktgruppe", "name", "einheit", "zeile", "zeile_name",
                        "spalte", "jahr", "art", "betrag_cent", "datei", "seite", "leer"]
TOLERANZ_CENT = 2      # Cent je Spalte innerhalb des Jahresabschlusses (Beträge mit Cent)
TOLERANZ_EURO = 9      # Euro je Spalte gegen den Haushaltsplan (ganze Euro) und im Teilfinanzplan A
NAEHE_PT = 12          # pt: Zeilen ohne Nummer weiter weg von jeder Tabellenzeile gehören nicht zur Tabelle (Seitenfuß)
# Teilfinanzplan A (Haushaltsplan): Zeilen 1–14, ohne VE und Finanzplanung
INVESTITIONEN = {1: "Einzahlungen aus Zuwendungen für Investitionsmaßnahmen",
                 2: "Einzahlungen aus der Veräußerung von Sachanlagen",
                 3: "Einzahlungen aus der Veräußerung von Finanzanlagen",
                 4: "Einzahlungen aus Beiträgen und ähnlichen Entgelten",
                 5: "sonstige Investitionseinzahlungen",
                 6: "Summe der investiven Einzahlungen",
                 7: "Auszahlungen für den Erwerb von Grundstücken und Gebäuden",
                 8: "Auszahlungen für Baumaßnahmen",
                 9: "Auszahlungen für den Erwerb von beweglichem Anlagevermögen",
                 10: "Auszahlungen für den Erwerb von Finanzanlagen",
                 11: "Auszahlungen von aktivierbaren Zuwendungen",
                 12: "sonstige Investitionsauszahlungen",
                 13: "Summe der investiven Auszahlungen",
                 14: "Saldo der Investitionstätigkeit (= Zeilen 6 und 13)"}
INVESTITIONEN_TSV = ORDNER / "investitionen.tsv"
INVESTITIONEN_KOPF = ["quelle", "ausgabe", "ebene", "produktbereich", "produktgruppe", "name", "einheit", "zeile",
                      "zeile_name", "spalte", "jahr", "art", "betrag", "datei", "seite", "leer"]
ERWEITERUNG_FREIGEGEBEN = True   # Ist 2024 und Investitionen: Prüfbögen im Gespräch bestätigt, freigegeben 03.11.2026 (haushalt/PHASE5.md)
ERWEITERUNG_PRUEFBOGEN = config.EXPORT / "haushalt" / "pruefbogen_haushalt_erweiterung.tsv"


def erweiterung_an():
    """Ist 2024 und Investitionen zeigen: nach Freigabe oder als Vorschau (HAUSHALT_ERWEITERUNG=vorschau)."""
    return ERWEITERUNG_FREIGEGEBEN or os.environ.get("HAUSHALT_ERWEITERUNG") == "vorschau"


def ist_2024(ebene, nr, zeile=17):
    """Ist 2024 laut Jahresabschluss (Spalte 4) einer Einheit und Zeile, auf Euro gerundet: {betrag, ausgabe, datei, seite}
    oder None (ohne Freigabe, ohne Datei oder ohne Wert)."""
    if not erweiterung_an() or not JAHRESABSCHLUSS_TSV.exists():
        return None
    spalte = "produktgruppe" if ebene == "Produktgruppe" else "produktbereich"
    for r in lesen(JAHRESABSCHLUSS_TSV):
        if r["ebene"] == ebene and r[spalte] == nr and r["zeile"] == str(zeile) and r["spalte"] == "4":
            c = int(r["betrag_cent"])
            return {"betrag": (abs(c) + 50) // 100 * (1 if c >= 0 else -1), "ausgabe": "Jahresabschluss 2024",
                    "datei": r["datei"], "seite": int(r["seite"])}
    return None


def _cent(text):
    """„-1.234,56“ → -123456 (Cent als ganze Zahl); „0“ → 0."""
    return int(text.replace(".", "").replace(",", "")) if "," in text else int(text) * 100


def koordinaten_ja(ws, nummern=None, nur_vorhandene=False, jahre=None, vermerke=None):
    """Spalten [(Art, Jahr)] und {Zeile: [Cent oder None je Spalte]} einer Seite der Teilergebnis- oder
    Teilfinanzrechnung (Jahresabschluss).

    Der Jahresabschluss hat keine Zeile mit Spaltennummern. Die sechs Spalten folgen aus je einem Wort des Kopfs
    (JA_SPALTEN), die Jahre aus den Jahreszahlen darunter (Vorjahr in Spalte 1, Haushaltsjahr in Spalte 4 und, wenn
    angegeben, in Spalte 2). Beträge sind rechtsbündig mit Cent; ein Betrag gehört zu der Spalte, deren Kopf links von
    seinem rechten Rand liegt und deren nächster Kopf rechts davon. Der häufigste rechte Rand je Spalte gilt als ihre
    Lage; jeder Betrag muss auf SPALTE_PT an ihr liegen. Bezeichnungen wie in koordinaten(); Beträge in einer Zeile der
    Bezeichnung zählen zur Zeile (_tabelle). Mit nur_vorhandene dürfen Zeilen fehlen (die Teilfinanzrechnungen
    drucken leere Zeilen nicht); sie sind dann ganz leer, eine Zeile außerhalb von nummern bricht ab. jahre (Vorjahr,
    Haushaltsjahr) gilt nur, wenn im Kopf einer Spalte gar kein Jahr steht (Jahresabschluss S. 608: „-1“ statt 2023,
    Jahr der Spalte 4 fehlt); das wird in vermerke (Liste) festgehalten. Bricht ab, wenn etwas nicht passt."""
    nummern = JA_ZEILEN if nummern is None else nummern
    zl = _textzeilen(ws)
    y_vj = next((y for y, z in zl if any(w[4] == "Vorjahres" for w in z)), None)
    erste = next((y for y, z in zl if y_vj is not None and y > y_vj and re.fullmatch(r"\d{1,2}", z[0][4])
                  and z[0][0] <= 100), None)
    if erste is None:
        raise ValueError("erste Tabellenzeile nicht gefunden")
    kopfw = [w for y, z in zl if y < erste - 1 for w in z]
    mitten = []
    for wort_, _ in JA_SPALTEN:
        xs = [(w[0] + w[2]) / 2 for w in kopfw if w[4] == wort_]
        if len(xs) != 1:
            raise ValueError(f"Tabellenkopf: „{wort_}“ {len(xs)}-mal")
        mitten.append(xs[0])
    if mitten != sorted(mitten):
        raise ValueError(f"Tabellenkopf: Spalten nicht in der erwarteten Reihenfolge {mitten}")
    abstand = (mitten[-1] - mitten[0]) / (len(mitten) - 1)

    def jahr(k, frei=False, vorgabe=None):
        js = {int(w[4]) for w in kopfw if re.fullmatch(r"20[1-3]\d", w[4]) and abs((w[0] + w[2]) / 2 - mitten[k]) <= abstand / 2}
        if frei and not js:
            return None
        if not js and vorgabe is not None:
            if vermerke is not None:
                vermerke.append(f"kein Jahr im Kopf der Spalte {k + 1}, {vorgabe} angenommen")
            return vorgabe
        if len(js) != 1:
            raise ValueError(f"Tabellenkopf: Jahr der Spalte {k + 1} nicht eindeutig {sorted(js)}")
        return js.pop()
    vorjahr, haushaltsjahr = jahr(0, vorgabe=jahre and jahre[0]), jahr(3, vorgabe=jahre and jahre[1])
    if jahr(1, True) not in (None, haushaltsjahr) or vorjahr != haushaltsjahr - 1:
        raise ValueError(f"Tabellenkopf: Jahre {vorjahr}, {jahr(1, True)}, {haushaltsjahr} passen nicht")
    cols = [(art, vorjahr if k == 0 else haushaltsjahr) for k, (_, art) in enumerate(JA_SPALTEN)]
    ist_betrag = lambda w: ZAHL_CENT.fullmatch(w[4]) and w[2] > mitten[0]
    nummeriert, bezeichnung = _tabelle(zl, erste - 8, ist_betrag, naehe=NAEHE_PT, werte_daneben=True)
    if nur_vorhandene:
        if set(nummeriert) - set(nummern):
            raise ValueError(f"unerwartete Zeilen {sorted(set(nummeriert) - set(nummern))}")
        gesucht = {nr: n for nr, n in nummern.items() if nr in nummeriert}
    else:
        gesucht = nummern
    grenzen = mitten + [mitten[-1] + abstand]
    bereich = lambda w: next((k for k in range(len(mitten)) if grenzen[k] < w[2] < grenzen[k + 1]), None)
    raender = defaultdict(Counter)
    for _, z in nummeriert.values():
        for w in z:
            if ist_betrag(w) and bereich(w) is not None:
                raender[bereich(w)][round(w[2])] += 1
    anker = {k: c.most_common(1)[0][0] for k, c in raender.items()}

    def spalte(w):
        k = bereich(w)
        return k if k is not None and abs(anker[k] - w[2]) <= SPALTE_PT else None

    werte = _werte(nummeriert, bezeichnung, gesucht, len(mitten), spalte, ist_betrag, _cent)
    return cols, {nr: werte.get(nr, [None] * len(mitten)) for nr in nummern}


def _pb_name(ws):
    """Name des Produktbereichs aus dem Seitenkopf („1.04 Kultur und Wissenschaft“ → „Kultur und Wissenschaft“)."""
    for _, z in _textzeilen(ws)[:4]:
        for g in _gruppen(z):
            if re.fullmatch(r"1\.\d{2}", g[0]):
                return " ".join(g[1:])
    return None


JA_ZEILEN_GESAMT = {**JA_ZEILEN, 18: "Ordentliches Ergebnis (Zeilen 10 und 17)"}   # so in der Gesamtergebnisrechnung
# Im PDF belegt (haushalt/PHASE5.md): Der fortgeschriebene Ansatz 2024 der Personalaufwendungen ist in der
# Gesamtergebnisrechnung (S. 2) um 28.806,75 € höher als die Summe der 17 Teilergebnisrechnungen; Zeilen 17 und 18 und
# der Vergleich (Spalte 5) folgen daraus. Gelesen auch über pdftotext -layout. Schlüssel (Zeile, Spalte), Summe der
# Produktbereiche minus Gesamtrechnung in Cent.
JA_ABWEICHUNG_GESAMT = {(11, 2): -2880675, (17, 2): -2880675, (18, 2): 2880675,
                        (11, 5): 2880675, (17, 5): 2880675, (18, 5): -2880675}


def _ja_zellen(kopf_, cols, werte, seite, namen=None):
    """TSV-Zeilen des Jahresabschlusses je Zeile und Spalte; leere Zellen als 0 mit Vermerk."""
    namen = namen or JA_ZEILEN
    for nr, ws in werte.items():
        for k, ((art, jahr), w) in enumerate(zip(cols, ws), 1):
            yield {"quelle": JAHRESABSCHLUSS["quelle"], **kopf_, "zeile": nr,
                   "zeile_name": namen[nr].replace(" (Zeilen 10 und 17)", ""), "spalte": k, "jahr": jahr, "art": art,
                   "betrag_cent": w or 0, "datei": Path(JAHRESABSCHLUSS["url"]).name, "seite": seite,
                   "leer": "ja" if w is None else ""}


def jahresabschluss_lesen(seiten, nummern=None):
    """(Zeilen der Produktbereiche und Produktgruppen, Zeilen der Gesamtergebnisrechnung) aus den Seiten des
    Jahresabschlusses 2024 Teil 2 (Wortlisten). Liest die erste Seite jeder Teilergebnisrechnung (Zeilen 10–18). Mit
    nummern andere Zeilen der Teilergebnisrechnungen (Ertragsarten); die Gesamtergebnisrechnung bleibt dann leer."""
    rows, gesamt, gesehen, cols0 = [], [], set(), None
    pb_aktuell = None
    for s, ws in enumerate(seiten, 1):
        texte = {w[4] for w in ws}
        if "Personalaufwendungen" not in texte:
            continue
        if "Gesamtergebnisrechnung" in texte and nummern:
            continue
        if "Gesamtergebnisrechnung" in texte:
            if gesamt:
                raise ValueError(f"S. {s}: zweite Gesamtergebnisrechnung")
            cols, werte = koordinaten_ja(ws, JA_ZEILEN_GESAMT)
            gesamt = list(_ja_zellen({"ebene": "Gesamt", "produktbereich": "", "produktgruppe": "", "name": "",
                                      "einheit": ""}, cols, werte, s))
        elif "Teilergebnisrechnung" in texte:
            pb, pg, name, einheit = kopf(ws)
            if pb is None:
                raise ValueError(f"S. {s}: Teilergebnisrechnung ohne Produktbereich im Kopf")
            if pg is None:
                if pb in gesehen:
                    raise ValueError(f"S. {s}: Produktbereich {pb} doppelt")
                pb_aktuell, name, einheit = pb, _pb_name(ws), ""
            elif pb != pb_aktuell or not pg.startswith(f"1.{pb}.") or pg in gesehen:
                raise ValueError(f"S. {s}: Produktgruppe {pg} unerwartet oder doppelt")
            gesehen.add(pg or pb)
            cols, werte = koordinaten_ja(ws, nummern or JA_ZEILEN)
            rows += _ja_zellen({"ebene": "Produktgruppe" if pg else "Produktbereich", "produktbereich": pb,
                                "produktgruppe": pg or "", "name": name or "", "einheit": einheit or ""}, cols, werte, s,
                               nummern)
        else:
            raise ValueError(f"S. {s}: Seite mit Personalaufwendungen weder Teil- noch Gesamtergebnisrechnung")
        if cols0 is None:
            cols0 = cols
        elif cols != cols0:
            raise ValueError(f"S. {s}: Spalten {cols} weichen von {cols0} ab")
    if not gesamt and not nummern:
        raise ValueError("Gesamtergebnisrechnung nicht gefunden")
    return rows, gesamt


def pruefsummen_ja(rows, gesamt, plan_pb, plan_aufwand, plan_pg, bekannt=None):
    """Prüfsummen des Jahresabschlusses je Spalte; bricht bei Abweichung ab. Gibt {Prüfung: (Spalten, größte Abweichung,
    Einheit)} zurück. Gegen den Haushaltsplan 2025/2026 wird die Vorjahresspalte (Ergebnis 2023, Spalte 1) auf ganze
    Euro gerundet verglichen. bekannt: belegte Abweichungen der Gesamtrechnung (Vorgabe JA_ABWEICHUNG_GESAMT)."""
    bekannt = JA_ABWEICHUNG_GESAMT if bekannt is None else bekannt
    alle = rows + gesamt
    einheit = lambda r: (r["ebene"], r["produktgruppe"] or r["produktbereich"])
    k = lambda r: (*einheit(r), int(r["spalte"]))
    zeile = lambda nr: {k(r): int(r["betrag_cent"]) for r in alle if int(r["zeile"]) == nr}
    z10, z17, z18 = zeile(10), zeile(17), zeile(18)
    out = {}
    out["aufwandsarten_17"] = pruefsumme([(k(r), int(r["betrag_cent"])) for r in alle if 11 <= int(r["zeile"]) <= 16],
                                         z17, "Jahresabschluss: Zeilen 11–16", TOLERANZ_CENT)
    out["ergebnis_18"] = pruefsumme([(x, b) for x, b in z10.items()] + [(x, -b) for x, b in z17.items()], z18,
                                    "Jahresabschluss: Zeile 10 − 17", TOLERANZ_CENT, "Zeile 18")
    pb = lambda r: (r["produktbereich"], int(r["zeile"]), int(r["spalte"]))
    ganze_pb = {pb(r): int(r["betrag_cent"]) for r in rows if r["ebene"] == "Produktbereich"}
    mit_pg = {r["produktbereich"] for r in rows if r["ebene"] == "Produktgruppe"}
    out["produktgruppen_produktbereich"] = pruefsumme(
        [(pb(r), int(r["betrag_cent"])) for r in rows if r["ebene"] == "Produktgruppe"],
        {x: b for x, b in ganze_pb.items() if x[0] in mit_pg}, "Jahresabschluss: Summe der Produktgruppen",
        TOLERANZ_CENT, "Produktbereich")
    g = lambda r: (int(r["zeile"]), int(r["spalte"]))
    out["produktbereiche_gesamt"] = pruefsumme([(g(r), int(r["betrag_cent"])) for r in rows if r["ebene"] == "Produktbereich"],
                                               {g(r): int(r["betrag_cent"]) for r in gesamt},
                                               "Jahresabschluss: Summe der 17 Produktbereiche", TOLERANZ_CENT,
                                               "Gesamtergebnisrechnung", bekannt)
    # Vorjahresspalte gegen den Haushaltsplan 2025/2026 (Ergebnis 2023, ganze Euro)
    neu = max(AUSGABEN)
    vj = int(neu.split("/")[0]) - 2
    plan = {}
    for r in plan_pb + plan_aufwand:
        if r["ausgabe"] == neu and r["art"] == "Ergebnis" and int(r["jahr"]) == vj:
            plan[("Produktbereich", r["produktbereich"], int(r["zeile"]))] = int(r["betrag"])
    for r in plan_pg:
        if r["ausgabe"] == neu and r["art"] == "Ergebnis" and int(r["jahr"]) == vj:
            plan[("Produktgruppe", r["produktgruppe"], int(r["zeile"]))] = int(r["betrag"])
    ja = {(*einheit(r), int(r["zeile"])): int(r["betrag_cent"]) for r in rows
          if int(r["spalte"]) == 1 and int(r["jahr"]) == vj}
    gemeinsam = set(plan) & set(ja)
    out["vorjahr_haushaltsplan"] = pruefsumme([(x, round(ja[x] / 100)) for x in gemeinsam], {x: plan[x] for x in gemeinsam},
                                              f"Jahresabschluss: Ergebnis {vj} gegen Haushaltsplan {neu}", TOLERANZ_EURO,
                                              f"Ergebnis {vj} im Haushaltsplan")
    return {x: (*v, "Euro" if x == "vorjahr_haushaltsplan" else "Cent") for x, v in out.items()}


def _schreiben(path, kopf_, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, kopf_, delimiter="\t", lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)


def _pruefung_json(pruefung):
    return {k: {"spalten": n, f"groesste_abweichung_{e.lower()}": a} for k, (n, a, e) in pruefung.items()}


def ist2024():
    """Pipeline-Schritt `haushalt-ist2024` (einmalig, lokal): data/haushalt/jahresabschluss.tsv (Teilergebnisrechnungen
    der 17 Produktbereiche und der Produktgruppen, Zeilen 10–18, alle sechs Spalten, Cent) aus dem festgestellten
    Jahresabschluss 2024 Teil 2, Vermerk in STAND.json. Die PDF kommt nicht ins Repository."""
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    rows, gesamt = jahresabschluss_lesen(_seiten(_pdf(JAHRESABSCHLUSS["url"], JAHRESABSCHLUSS["sha256"])))
    plan_pg = lesen(PRODUKTGRUPPEN_TSV)
    pruefung = pruefsummen_ja(rows, gesamt, lesen(), lesen(AUFWANDSARTEN_TSV), plan_pg)
    neu = max(AUSGABEN)
    im_plan = {r["produktgruppe"]: r["name"] for r in plan_pg if r["ausgabe"] == neu}
    im_ja = {r["produktgruppe"]: r["name"] for r in rows if r["ebene"] == "Produktgruppe"}
    namen_pb = {r["produktbereich"]: r["name"] for r in rows if r["ebene"] == "Produktbereich"}
    _schreiben(JAHRESABSCHLUSS_TSV, JAHRESABSCHLUSS_KOPF, rows)
    seite_g = gesamt[0]["seite"]
    stand["jahresabschluss"] = {
        "abruf": datetime.now(timezone.utc).date().isoformat(), "seite": JAHRESABSCHLUSS["seite"],
        "datei": {"url": JAHRESABSCHLUSS["url"], "sha256": JAHRESABSCHLUSS["sha256"]},
        "feststellung": "Rat 12.03.2026 (haushalt/phase0/ERWEITERUNG.md)",
        "gesamtergebnisrechnung_seite": seite_g,
        "spalten": [{"spalte": k, "art": r["art"], "jahr": r["jahr"], "kopf": JA_KOPF[k - 1]}
                    for k, r in enumerate((r for r in gesamt if int(r["zeile"]) == 10), 1)],
        "zeilen": {str(k): v.replace(" (Zeilen 10 und 17)", "") for k, v in JA_ZEILEN.items()},
        "produktbereiche": len(namen_pb), "produktgruppen": len(im_ja),
        "produktgruppen_nur_im_haushaltsplan": {pg: im_plan[pg] for pg in sorted(set(im_plan) - set(im_ja))},
        "produktgruppen_nur_im_jahresabschluss": {pg: im_ja[pg] for pg in sorted(set(im_ja) - set(im_plan))},
        "namen_abweichend_vom_haushaltsplan": {pg: {"jahresabschluss": im_ja[pg], "haushaltsplan": im_plan[pg]}
                                               for pg in sorted(set(im_ja) & set(im_plan)) if im_ja[pg] != im_plan[pg]},
        "pruefsummen": _pruefung_json(pruefung), "toleranz_cent": TOLERANZ_CENT, "toleranz_euro_haushaltsplan": TOLERANZ_EURO,
        "bekannte_abweichung_gesamtrechnung_cent": {f"{z}/{s}": a for (z, s), a in JA_ABWEICHUNG_GESAMT.items()},
        "leere_zellen": {"produktbereiche": sum(r["leer"] == "ja" for r in rows if r["ebene"] == "Produktbereich"),
                         "produktgruppen": sum(r["leer"] == "ja" for r in rows if r["ebene"] == "Produktgruppe")}}
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Jahresabschluss 2024: {len(rows)} Werte ({len(namen_pb)} Produktbereiche, {len(im_ja)} Produktgruppen); "
          "Prüfsummen " + ", ".join(f"{k} {n} Spalten bis {a} {e}" for k, (n, a, e) in pruefung.items())
          + f" → {JAHRESABSCHLUSS_TSV}")


# Gesamtfinanzplan (gepp.pdf): Zeilen 18–31 entsprechen den Zeilen 1–14 des Teilfinanzplans A
GESAMTFINANZPLAN = {18: "Zuwendungen für Investitionsmaßnahmen", 19: "Einzahlungen aus der Veräußerung von Sachanlagen",
                    20: "Einzahlungen aus der Veräußerung von Finanzanlagen",
                    21: "Einzahlungen aus Beiträgen u. ä. Entgelten", 22: "sonstige Investitionseinzahlungen",
                    23: "Einzahlungen aus Investitionstätigkeit",
                    24: "Auszahlungen für den Erwerb von Grundstücken und Gebäuden", 25: "Auszahlungen für Baumaßnahmen",
                    26: "Auszahlungen für den Erwerb von beweglichem Anlagevermögen",
                    27: "Auszahlungen für den Erwerb von Finanzanlagen", 28: "Auszahlungen von aktivierbaren Zuwendungen",
                    29: "Sonstige Investitionsauszahlungen", 30: "Auszahlungen aus Investitionstätigkeiten",
                    31: "Saldo aus Investitionstätigkeit (Zeilen 23 und 30)"}


def _finanz_zellen(kopf_, cols, werte, ausgabe, datei, seite):
    """TSV-Zeilen des Teilfinanzplans A ohne VE und ohne Finanzplanung; leere Zellen als 0 mit Vermerk."""
    for nr, ws in werte.items():
        for k, ((art, jahr), w) in enumerate(zip(cols, ws), 1):
            if art in ("VE", "Planung"):   # Entscheidung 03.11.2026: ohne Verpflichtungsermächtigungen und Finanzplanung
                continue
            yield {"quelle": f"Haushaltsplan {ausgabe}", "ausgabe": ausgabe, **kopf_, "zeile": nr,
                   "zeile_name": INVESTITIONEN[nr], "spalte": k, "jahr": jahr, "art": art, "betrag": w or 0,
                   "datei": Path(datei["url"]).name, "seite": seite, "leer": "ja" if w is None else ""}


def teilfinanzplaene(ausgabe, st, pdfs):
    """Zeilen des Teilfinanzplans A je Produktbereich (S. 3) und Produktgruppe einer Ausgabe; pdfs {PB: Wortlisten}."""
    rows, gesehen, spalten_ = [], set(), None
    for pb, seiten in sorted(pdfs.items()):
        datei, auf_pb = st["dateien"][pb], 0
        for s, ws in enumerate(seiten, 1):
            texte = {w[4] for w in ws}
            if not {"Teilfinanzplan", "Zahlungsübersicht"} <= texte:   # Teil A; Teil B heißt „Investitionseinzelmaßnahmen“
                continue
            pb_, pg, name, einheit = kopf(ws)
            if pb_ != pb:
                raise ValueError(f"{ausgabe} PB {pb} S. {s}: Kopf nennt Produktbereich {pb_}")
            if pg is None:
                auf_pb += 1
                if s != 3:
                    raise ValueError(f"{ausgabe} PB {pb}: Teilfinanzplan A des Produktbereichs auf S. {s} statt S. 3")
            elif not pg.startswith(f"1.{pb}.") or pg in gesehen:
                raise ValueError(f"{ausgabe} PB {pb} S. {s}: Produktgruppe {pg} unerwartet oder doppelt")
            gesehen.add(pg)
            cols, werte = koordinaten(ws, INVESTITIONEN, ARTEN_FINANZ, NAEHE_PT)
            if spalten_ is None:
                spalten_ = cols
            elif cols != spalten_:
                raise ValueError(f"{ausgabe} PB {pb} S. {s}: Spalten {cols} weichen von {spalten_} ab")
            k = {"ebene": "Produktgruppe" if pg else "Produktbereich", "produktbereich": pb, "produktgruppe": pg or "",
                 "name": name if pg else datei["name"], "einheit": (einheit or "") if pg else ""}
            rows += _finanz_zellen(k, cols, werte, ausgabe, datei, s)
        if auf_pb != 1:
            raise ValueError(f"{ausgabe} PB {pb}: {auf_pb} Teilfinanzpläne A des Produktbereichs")
    return rows, spalten_


def gesamtfinanzplan(seiten):
    """Spalten und {Zeile 18–31: Werte} des Gesamtfinanzplans (über zwei Seiten)."""
    cols, werte = None, {}
    for ws in seiten:
        if "Gesamtfinanzplan" not in {w[4] for w in ws}:
            continue
        zl = _textzeilen(ws)
        nummern = {z[0][4] for _, z in zl if z[0][0] <= 100}
        hier = {nr: n for nr, n in GESAMTFINANZPLAN.items() if str(nr) in nummern and nr not in werte}
        if not hier:
            continue
        c, w = koordinaten(ws, hier, ARTEN, NAEHE_PT)
        if cols is not None and c != cols:
            raise ValueError(f"Gesamtfinanzplan: Spalten {c} weichen von {cols} ab")
        cols = c
        werte.update(w)
    if set(werte) != set(GESAMTFINANZPLAN):
        raise ValueError(f"Gesamtfinanzplan: Zeilen {sorted(set(GESAMTFINANZPLAN) - set(werte))} fehlen")
    return cols, werte


def pruefsummen_investitionen(rows, gesamt):
    """Prüfsummen des Teilfinanzplans A je Spalte (Euro); gesamt {Ausgabe: (Spalten, Werte des Gesamtfinanzplans)}.
    Gibt {Prüfung: (Spalten, größte Abweichung, "Euro")} zurück; bricht bei Abweichung ab."""
    e = lambda r: (r["ausgabe"], r["ebene"], r["produktgruppe"] or r["produktbereich"], int(r["spalte"]))
    zeile = lambda nr: {e(r): int(r["betrag"]) for r in rows if int(r["zeile"]) == nr}
    z6, z13, z14 = zeile(6), zeile(13), zeile(14)
    nur = lambda von, bis: [(e(r), int(r["betrag"])) for r in rows if von <= int(r["zeile"]) <= bis]
    out = {"zeilen_1_5_gleich_6": pruefsumme(nur(1, 5), z6, "Teilfinanzplan A: Zeilen 1–5", TOLERANZ_EURO, "Zeile 6"),
           "zeilen_7_12_gleich_13": pruefsumme(nur(7, 12), z13, "Teilfinanzplan A: Zeilen 7–12", TOLERANZ_EURO, "Zeile 13"),
           "saldo_6_minus_13_gleich_14": pruefsumme(list(z6.items()) + [(x, -b) for x, b in z13.items()], z14,
                                                    "Teilfinanzplan A: Zeile 6 − 13", TOLERANZ_EURO, "Zeile 14")}
    pb = lambda r: (r["ausgabe"], r["produktbereich"], int(r["zeile"]), int(r["spalte"]))
    mit_pg = {(r["ausgabe"], r["produktbereich"]) for r in rows if r["ebene"] == "Produktgruppe"}
    out["produktgruppen_produktbereich"] = pruefsumme(
        [(pb(r), int(r["betrag"])) for r in rows if r["ebene"] == "Produktgruppe"],
        {pb(r): int(r["betrag"]) for r in rows if r["ebene"] == "Produktbereich" and (r["ausgabe"], r["produktbereich"]) in mit_pg},
        "Teilfinanzplan A: Summe der Produktgruppen", TOLERANZ_EURO, "Produktbereich")
    teile, ganze = [], {}
    for ausgabe, (gcols, gwerte) in gesamt.items():
        for r in rows:
            if r["ausgabe"] == ausgabe and r["ebene"] == "Produktbereich":
                teile.append(((ausgabe, int(r["zeile"]), r["art"], int(r["jahr"])), int(r["betrag"])))
        for nr, ws in gwerte.items():
            for (art, jahr), w in zip(gcols, ws):
                if art != "Planung":
                    ganze[(ausgabe, nr - 17, art, int(jahr))] = w or 0
    out["produktbereiche_gesamtfinanzplan"] = pruefsumme(teile, ganze, "Teilfinanzplan A: Summe der 17 Produktbereiche",
                                                         TOLERANZ_EURO, "Gesamtfinanzplan, Zeilen 18–31")
    return {k: (*v, "Euro") for k, v in out.items()}


def investitionen():
    """Pipeline-Schritt `haushalt-investitionen` (einmalig, lokal): data/haushalt/investitionen.tsv (Teilfinanzplan A,
    Zeilen 1–14, je Produktbereich und Produktgruppe, ohne VE und Finanzplanung) aus denselben PDF wie
    `haushalt-ausschnitt` (SHA-256 laut STAND.json), Vermerk in STAND.json. Eine Ausgabe wird nur übernommen, wenn alle
    17 PDF der Produktbereiche lesbar sind und alle Prüfsummen aufgehen."""
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    rows, gesamt, spalten_, zahl, dateien = [], {}, {}, {}, {}
    for ausgabe in AUSGABEN:
        st = stand["ausgaben"][ausgabe]
        pdfs = {pb: _seiten(_pdf(st["dateien"][pb]["url"], st["dateien"][pb]["sha256"]))
                for pb in (f"{i:02d}" for i in range(1, 18))}
        neu, spalten_[ausgabe] = teilfinanzplaene(ausgabe, st, pdfs)
        gesamt[ausgabe] = gesamtfinanzplan(_seiten(_pdf(st["dateien"]["gesamt"]["url"], st["dateien"]["gesamt"]["sha256"])))
        rows += neu
        zahl[ausgabe] = len({r["produktgruppe"] for r in neu if r["produktgruppe"]})
        dateien[ausgabe] = {k: {"url": d["url"], "sha256": d["sha256"]} for k, d in st["dateien"].items()}   # geprüft
    pruefung = pruefsummen_investitionen(rows, gesamt)
    _schreiben(INVESTITIONEN_TSV, INVESTITIONEN_KOPF, rows)
    stand["investitionen"] = {
        "abruf": datetime.now(timezone.utc).date().isoformat(), "dateien": dateien,
        "seite_produktbereich": 3, "zeilen": {str(k): v for k, v in INVESTITIONEN.items()},
        "spalten_im_pdf": {a: [f"{k} {x} {j}" for k, (x, j) in enumerate(c, 1)] for a, c in spalten_.items()},
        "spalten_uebernommen": "Ergebnis und Ansatz; ohne VE (Verpflichtungsermächtigungen) und Planung (Entscheidung 03.11.2026)",
        "gesamtfinanzplan_zeilen": "18–31 = Teilfinanzplan A 1–14", "produktgruppen": zahl,
        "pruefsummen": _pruefung_json(pruefung), "toleranz_euro": TOLERANZ_EURO,
        "leere_zellen": {a: {"produktbereiche": sum(r["leer"] == "ja" for r in rows if r["ausgabe"] == a and r["ebene"] == "Produktbereich"),
                             "produktgruppen": sum(r["leer"] == "ja" for r in rows if r["ausgabe"] == a and r["ebene"] == "Produktgruppe")}
                         for a in AUSGABEN}}
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Investitionen: {len(rows)} Werte ({zahl} Produktgruppen mit Teilfinanzplan A); Prüfsummen "
          + ", ".join(f"{k} {n} Spalten bis {a} €" for k, (n, a, _) in pruefung.items()) + f" → {INVESTITIONEN_TSV}")


def _wie_im_pdf(betrag, cent):
    """Betrag in der Schreibweise des PDF: 1.234.567,89 (Jahresabschluss) oder 1.234.567 (Haushaltsplan)."""
    e, c = divmod(abs(betrag), 100) if cent else (abs(betrag), None)
    t = f"{e:,}".replace(",", ".") + (f",{c:02d}" if cent else "")
    return ("-" if betrag < 0 else "") + t


def pruefbogen_erweiterung():
    """Pipeline-Schritt `haushalt-pruefbogen-erweiterung` (einmalig): etwa 30 Zellen aus jahresabschluss.tsv und
    investitionen.tsv zur Prüfung von Hand gegen das PDF, mit Link auf die Seite. Darunter Sonderfälle (negative Werte,
    teilweise gefüllte Zeilen, größte Werte, Finanzanlagen, PB 03, fortgeschriebener Ansatz, Ermächtigungsübertragungen)
    und eine Stichprobe über mehrere Produktbereiche. Wird nicht überschrieben."""
    if ERWEITERUNG_PRUEFBOGEN.exists():
        print(f"Prüfbogen besteht bereits: {ERWEITERUNG_PRUEFBOGEN}")
        return
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    einheit = lambda r: r["produktgruppe"] or r["produktbereich"]
    ja = {(r["ebene"], einheit(r), int(r["zeile"]), int(r["spalte"])): r for r in lesen(JAHRESABSCHLUSS_TSV)}
    neu, alt = max(AUSGABEN), min(AUSGABEN)
    inv = {(r["ausgabe"], r["ebene"], einheit(r), int(r["zeile"]), int(r["spalte"])): r for r in lesen(INVESTITIONEN_TSV)}
    b = lambda r, feld="betrag_cent": int(r[feld])
    auswahl = defaultdict(list)
    # Jahresabschluss: negative Aufwendungen im Ist 2024 (Spalte 4), im Produktbereich und der kleinste Ansatz
    aufwand = [k for k in ja if 11 <= k[2] <= 17]
    for k in sorted(k for k in aufwand if k[3] == 4 and b(ja[k]) < 0):
        auswahl[("J", *k)].append("negativer Wert, Ist 2024")
    for k in sorted(k for k in aufwand if k[0] == "Produktbereich" and k[3] in (1, 2, 4) and b(ja[k]) < 0)[:1]:
        auswahl[("J", *k)].append("negativer Wert im Produktbereich")
    k = min((k for k in aufwand if k[3] == 2), key=lambda k: b(ja[k]))
    auswahl[("J", *k)].append("kleinster fortgeschriebener Ansatz (negativ)")
    # teilweise gefüllte Zeile (Spalten 1, 2, 4): je eine gefüllte und eine leere Zelle, im Produktbereich und einer PG
    zeilen = defaultdict(list)
    for k in sorted(ja):
        if k[3] in (1, 2, 4):
            zeilen[k[:3]].append(k)
    for ebene in ("Produktbereich", "Produktgruppe"):
        ks = next(ks for z, ks in zeilen.items() if z[0] == ebene and {ja[k]["leer"] for k in ks} == {"", "ja"})
        for k in (next(k for k in ks if not ja[k]["leer"]), next(k for k in ks if ja[k]["leer"])):
            auswahl[("J", *k)].append("teilweise gefüllte Zeile")
    k = max((k for k in ja if k[0] == "Produktgruppe" and k[2] == 17 and k[3] == 4), key=lambda k: b(ja[k]))
    auswahl[("J", *k)].append("größte Produktgruppe, Ist 2024")
    for nr in (17, 18):
        auswahl[("J", "Produktbereich", "03", nr, 4)].append("PB 03, Ist 2024")
    # fortgeschriebener Ansatz gegen den Ansatz 2024 des Haushaltsplans: größter Unterschied (Zeile 17)
    plan24 = {r["produktbereich"]: int(r["betrag"]) * 100 for r in lesen() if r["ausgabe"] == neu and r["art"] == "Ansatz"
              and int(r["jahr"]) == int(neu.split("/")[0]) - 1 and int(r["zeile"]) == 17}
    k = max((k for k in ja if k[0] == "Produktbereich" and k[2] == 17 and k[3] == 2),
            key=lambda k: abs(b(ja[k]) - plan24[k[1]]))
    auswahl[("J", *k)].append("fortgeschriebener Ansatz weicht am stärksten vom Ansatz des Haushaltsplans ab")
    for sp, grund in ((3, "größte Ermächtigungsübertragung aus dem Vorjahr (PG)"), (5, "größter Vergleich Ansatz/Ist (PB)")):
        ebene = "Produktgruppe" if sp == 3 else "Produktbereich"
        k = max((k for k in ja if k[0] == ebene and k[2] == 17 and k[3] == sp), key=lambda k: abs(b(ja[k])))
        auswahl[("J", *k)].append(grund)
    # Stichprobe: jeder vierte Produktbereich, eine Produktgruppe; Zeile und Spalte wechseln
    gruppen = sorted({k[1] for k in ja if k[0] == "Produktgruppe"})
    for i, pb in enumerate(f"{n:02d}" for n in range(1, 18, 4)):
        pgs = [g for g in gruppen if g.startswith(f"1.{pb}.")]
        auswahl[("J", "Produktgruppe", pgs[i % len(pgs)], (10, 11, 13, 15, 18)[i], (4, 1, 2, 4, 6)[i])].append("Stichprobe")
    # Investitionen (Haushaltsplan): Finanzanlagen, PB 03, negative Werte, teilweise gefüllt, größter Wert
    plan26 = lambda r: r["ausgabe"] == neu and r["art"] == "Ansatz" and int(r["jahr"]) == int(neu.split("/")[1])
    sp = lambda ausgabe, art, jahr: next(int(r["spalte"]) for r in inv.values() if (r["ausgabe"], r["art"], int(r["jahr"])) == (ausgabe, art, jahr))
    s26, s25, s23 = sp(neu, "Ansatz", int(neu.split("/")[1])), sp(neu, "Ansatz", int(neu.split("/")[0])), sp(neu, "Ergebnis", int(neu.split("/")[0]) - 2)
    for pg in ("1.01.29", "1.16.04"):
        auswahl[("I", neu, "Produktgruppe", pg, 10, s26)].append("Finanzanlagen, Plan 2026")
    auswahl[("I", alt, "Produktgruppe", "1.01.29", 10, sp(alt, "Ansatz", int(alt.split("/")[1])))].append(
        "Finanzanlagen, Haushaltsplan 2023/2024")
    for nr in (13, 14):
        auswahl[("I", neu, "Produktbereich", "03", nr, s26)].append("PB 03, Plan 2026")
    negativ = sorted((k for k, r in inv.items() if b(r, "betrag") < 0 and k[3] not in (6, 13, 14)), key=lambda k: (k[0] != neu, k))
    for k in [k for k in negativ if k[0] == neu] + [k for k in negativ if k[0] != neu][:1]:   # ohne Summenzeilen
        auswahl[("I", *k)].append("negativer Wert")
    teil = defaultdict(list)
    for k in sorted(inv):
        teil[k[:4]].append(k)
    for ausgabe, ebene in ((neu, "Produktbereich"), (neu, "Produktgruppe")):
        ks = next(ks for z, ks in teil.items() if z[:2] == (ausgabe, ebene) and {inv[k]["leer"] for k in ks} == {"", "ja"})
        for k in (next(k for k in ks if not inv[k]["leer"]), next(k for k in ks if inv[k]["leer"])):
            auswahl[("I", *k)].append("teilweise gefüllte Zeile")
    k = max((k for k, r in inv.items() if plan26(r) and k[1] == "Produktbereich" and k[3] == 13), key=lambda k: b(inv[k], "betrag"))
    auswahl[("I", *k)].append("größte investive Auszahlungen, Plan 2026")
    pos = sorted(k for k, r in inv.items() if r["ausgabe"] == neu and r["art"] == "Ansatz" and k[3] == 14 and b(r, "betrag") > 0)
    if pos:
        auswahl[("I", *pos[0])].append("positiver Saldo im Plan")
    gruppen = sorted({k[2] for k in inv if k[0] == neu and k[1] == "Produktgruppe"})
    for i, pb in enumerate(f"{n:02d}" for n in range(3, 18, 4)):
        pgs = [g for g in gruppen if g.startswith(f"1.{pb}.")]
        if pgs:
            auswahl[("I", neu, "Produktgruppe", pgs[i % len(pgs)], (13, 8, 6, 9)[i], (s26, s25, s23, s26)[i])].append("Stichprobe")
    out = []
    for k, gruende in sorted(auswahl.items()):
        if k[0] == "J":
            r, quelle, url, cent = ja[k[1:]], JAHRESABSCHLUSS["quelle"], JAHRESABSCHLUSS["url"], True
            betrag = b(r)
        else:
            r, quelle, cent = inv[k[1:]], f"Haushaltsplan {k[1]}", False
            url, betrag = stand["ausgaben"][k[1]]["dateien"][r["produktbereich"]]["url"], b(r, "betrag")
        out.append([r["ebene"], f"{einheit(r)} {r['name']}", f"{r['zeile']} {r['zeile_name']}", r["jahr"], r["art"],
                    r["spalte"], _wie_im_pdf(betrag, cent), r["leer"], quelle, f"{url}#page={r['seite']}", r["seite"],
                    ", ".join(gruende), ""])
    ERWEITERUNG_PRUEFBOGEN.parent.mkdir(parents=True, exist_ok=True)
    with open(ERWEITERUNG_PRUEFBOGEN, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["ebene", "einheit", "zeile", "jahr", "art", "spalte", "betrag", "leer", "quelle", "datei", "seite",
                     "auswahl", "pruefung"])
        wr.writerows(out)
    print(f"Prüfbogen Erweiterung: {len(out)} Zellen → {ERWEITERUNG_PRUEFBOGEN}")


# --- Erweiterung: Ist 2024 der Investitionen aus den Teilfinanzrechnungen des Jahresabschlusses 2024 (Teil A) ---

# Zeilen der Teilfinanzrechnung, Teil A: Zahlungsnachweis (Wortlaut im Jahresabschluss; Nummern wie im Teilfinanzplan A).
# Leere Zeilen druckt der Jahresabschluss nicht; Zeile 12 kommt 2024 nirgends vor, ihr Wortlaut ist erschlossen.
JA_INVESTITIONEN = {1: "aus Zuwendungen für Investitionsmaßnahmen", 2: "aus der Veräußerung von Sachanlagen",
                    3: "aus der Veräußerung von Finanzanlagen", 4: "aus Beiträgen u. ä. Entgelten",
                    5: "Sonstige Investitionseinzahlungen", 6: "Summe: (invest. Einzahlungen)",
                    7: "für den Erwerb von Grundstücken und Gebäuden", 8: "für Baumaßnahmen",
                    9: "für den Erwerb von beweglichem Anlagevermögen", 10: "für den Erwerb von Finanzanlagen",
                    11: "von aktivierbaren Zuwendungen", 12: ("Sonstige Investitionsauszahlungen", "sonstige Investitionsauszahlungen"),
                    13: "Summe: (invest. Auszahlungen)",
                    14: "Saldo: der Investitionstätigkeit (Einzahlungen ./. Auszahlungen)"}
# Gesamtfinanzrechnung (S. 6): Zeilen 18–31 entsprechen den Zeilen 1–14
JA_GESAMTFINANZ = {18: "Zuwendungen für Investitionsmaßnahmen", 19: "Einzahlungen aus der Veräuß. von Sachanlagen",
                   20: "Einzahlungen aus der Veräuß. von Finanzanlagen", 21: "Einzahlungen aus Beiträgen u. ä. Entgelten",
                   22: "sonstige Investitionseinzahlungen", 23: "Einzahlungen aus Investitionstätigkeit",
                   24: "Auszahlungen für den Erwerb von Grundstücken und Gebäuden", 25: "Auszahlungen für Baumaßnahmen",
                   26: "Auszahlungen für den Erwerb von beweglichem Anlagevermögen",
                   27: "Auszahlungen für den Erwerb von Finanzanlagen", 28: "Auszahlungen von aktivierbaren Zuwendungen",
                   29: "Sonstige Investitionsauszahlungen", 30: "Auszahlungen aus Investitionstätigkeit",
                   31: "Saldo aus Investitionstätigkeit (Zeilen 23 und 30)"}
# Im PDF belegt (haushalt/PHASE5.md): Der fortgeschriebene Ansatz 2024 der Baumaßnahmen ist in der
# Gesamtfinanzrechnung (S. 6, Zeile 25) um 10.000,00 € niedriger als die Summe der Teilfinanzrechnungen; Zeilen 13, 14
# und der Vergleich (Spalte 5) folgen daraus. Gelesen auch über pdftotext -layout. Schlüssel (Zeile 1–14, Spalte),
# Summe der Produktbereiche minus Gesamtrechnung in Cent.
JA_ABWEICHUNG_GESAMTFINANZ = {(8, 2): 1000000, (13, 2): 1000000, (14, 2): -1000000,
                              (8, 5): -1000000, (13, 5): -1000000, (14, 5): 1000000}
JA_FINANZ_SPALTEN = (1, 2, 4, 5)   # ohne die Ermächtigungsübertragungen (Spalten 3 und 6) als eigene Werte
JA_INVESTITIONEN_TSV = ORDNER / "jahresabschluss_investitionen.tsv"
JA_INVESTITIONEN_KOPF = JAHRESABSCHLUSS_KOPF
ERWEITERUNG_PRUEFBOGEN_FINANZ = config.EXPORT / "haushalt" / "pruefbogen_haushalt_erweiterung_finanz.tsv"


def _ja_finanz_zellen(kopf_, cols, werte, seite):
    for nr, ws in werte.items():
        for k, ((art, jahr), w) in enumerate(zip(cols, ws), 1):
            if k not in JA_FINANZ_SPALTEN:
                continue
            yield {"quelle": JAHRESABSCHLUSS["quelle"], **kopf_, "zeile": nr, "zeile_name": INVESTITIONEN[nr],
                   "spalte": k, "jahr": jahr, "art": art, "betrag_cent": w or 0,
                   "datei": Path(JAHRESABSCHLUSS["url"]).name, "seite": seite, "leer": "ja" if w is None else ""}


def jahresabschluss_investitionen_lesen(seiten):
    """(Zeilen der Produktbereiche und Produktgruppen, Zeilen der Gesamtfinanzrechnung in den Nummern 1–14, {Seite:
    Vermerke}) aus den Teilfinanzrechnungen, Teil A: Zahlungsnachweis, des Jahresabschlusses 2024 Teil 2 (Wortlisten).
    Die Jahre einer Seite ohne Jahr im Kopf kommen von der ersten gelesenen Seite (Gesamtfinanzrechnung)."""
    rows, gesamt, gesehen, cols0, pb_aktuell, vermerke = [], [], set(), None, None, {}
    for s, ws in enumerate(seiten, 1):
        texte = {w[4] for w in ws}
        if "Gesamtfinanzrechnung" in texte and "Investitionstätigkeit" in texte and "18" in texte:
            if gesamt:
                raise ValueError(f"S. {s}: zweite Seite der Gesamtfinanzrechnung mit Zeile 18")
            nummern = {**JA_GESAMTFINANZ, 32: "Finanzmittelüberschuss / -fehlbetrag (Zeilen 17 und 31)"}
            cols, werte = koordinaten_ja(ws, nummern)
            werte = {nr - 17: werte[nr] for nr in JA_GESAMTFINANZ}
            gesamt = list(_ja_finanz_zellen({"ebene": "Gesamt", "produktbereich": "", "produktgruppe": "", "name": "",
                                             "einheit": ""}, cols, werte, s))
        elif "Teilfinanzrechnung" in texte and "Zahlungsnachweis" in texte:   # Teil B heißt „Investitionseinzelmaßnahmen“
            pb, pg, name, einheit = kopf(ws)
            if pb is None:
                raise ValueError(f"S. {s}: Teilfinanzrechnung ohne Produktbereich im Kopf")
            if pg is None:
                if pb in gesehen:
                    raise ValueError(f"S. {s}: Produktbereich {pb} doppelt")
                pb_aktuell, name, einheit = pb, _pb_name(ws), ""
            elif pb != pb_aktuell or not pg.startswith(f"1.{pb}.") or pg in gesehen:
                raise ValueError(f"S. {s}: Produktgruppe {pg} unerwartet oder doppelt")
            gesehen.add(pg or pb)
            vermerk = []
            cols, werte = koordinaten_ja(ws, JA_INVESTITIONEN, nur_vorhandene=True, jahre=cols0 and (cols0[0][1], cols0[3][1]),
                                         vermerke=vermerk)
            if vermerk:
                vermerke[s] = vermerk
            rows += _ja_finanz_zellen({"ebene": "Produktgruppe" if pg else "Produktbereich", "produktbereich": pb,
                                       "produktgruppe": pg or "", "name": name or "", "einheit": einheit or ""}, cols, werte, s)
        else:
            continue
        if cols0 is None:
            cols0 = cols
        elif cols != cols0:
            raise ValueError(f"S. {s}: Spalten {cols} weichen von {cols0} ab")
    if not gesamt:
        raise ValueError("Gesamtfinanzrechnung (Investitionstätigkeit) nicht gefunden")
    return rows, gesamt, vermerke


def pruefsummen_ja_investitionen(rows, gesamt, plan, bekannt=None):
    """Prüfsummen der Teilfinanzrechnungen je Spalte (Cent); plan: Zeilen aus investitionen.tsv. Gibt {Prüfung: (Spalten,
    größte Abweichung, Einheit)} zurück; bricht bei Abweichung ab. Produktbereiche ohne Teilfinanzrechnung (PB 17)
    zählen in der Summe mit 0. bekannt: belegte Abweichungen der Gesamtrechnung (Vorgabe JA_ABWEICHUNG_GESAMTFINANZ)."""
    bekannt = JA_ABWEICHUNG_GESAMTFINANZ if bekannt is None else bekannt
    alle = rows + gesamt
    e = lambda r: (r["ebene"], r["produktgruppe"] or r["produktbereich"], int(r["spalte"]))
    zeile = lambda nr: {e(r): int(r["betrag_cent"]) for r in alle if int(r["zeile"]) == nr}
    z6, z13, z14 = zeile(6), zeile(13), zeile(14)
    nur = lambda von, bis: [(e(r), int(r["betrag_cent"])) for r in alle if von <= int(r["zeile"]) <= bis]
    out = {"zeilen_1_5_gleich_6": pruefsumme(nur(1, 5), z6, "Teilfinanzrechnung: Zeilen 1–5", TOLERANZ_CENT, "Zeile 6"),
           "zeilen_7_12_gleich_13": pruefsumme(nur(7, 12), z13, "Teilfinanzrechnung: Zeilen 7–12", TOLERANZ_CENT, "Zeile 13"),
           "saldo_6_minus_13_gleich_14": pruefsumme(list(z6.items()) + [(x, -b) for x, b in z13.items()], z14,
                                                    "Teilfinanzrechnung: Zeile 6 − 13", TOLERANZ_CENT, "Zeile 14")}
    v = {(*e(r), int(r["zeile"])): int(r["betrag_cent"]) for r in alle}
    out["vergleich_4_minus_2"] = pruefsumme([(k, b) for k, b in v.items() if k[2] == 4] +
                                            [(k[:2] + (4,) + k[3:], -b) for k, b in v.items() if k[2] == 2],
                                            {k[:2] + (4,) + k[3:]: b for k, b in v.items() if k[2] == 5},
                                            "Teilfinanzrechnung: Spalte 4 − 2", TOLERANZ_CENT, "Spalte 5")
    pb = lambda r: (r["produktbereich"], int(r["zeile"]), int(r["spalte"]))
    mit_pg = {r["produktbereich"] for r in rows if r["ebene"] == "Produktgruppe"}
    out["produktgruppen_produktbereich"] = pruefsumme(
        [(pb(r), int(r["betrag_cent"])) for r in rows if r["ebene"] == "Produktgruppe"],
        {pb(r): int(r["betrag_cent"]) for r in rows if r["ebene"] == "Produktbereich" and r["produktbereich"] in mit_pg},
        "Teilfinanzrechnung: Summe der Produktgruppen", TOLERANZ_CENT, "Produktbereich")
    g = lambda r: (int(r["zeile"]), int(r["spalte"]))
    out["produktbereiche_gesamt"] = pruefsumme([(g(r), int(r["betrag_cent"])) for r in rows if r["ebene"] == "Produktbereich"],
                                               {g(r): int(r["betrag_cent"]) for r in gesamt},
                                               "Teilfinanzrechnung: Summe der Produktbereiche", TOLERANZ_CENT,
                                               "Gesamtfinanzrechnung, Zeilen 18–31", bekannt)
    # Ergebnis 2023 (Spalte 1) gegen das Ist 2023 des Teilfinanzplans A 2025/2026; fehlt eine Einheit, gilt 0
    neu = max(AUSGABEN)
    vj = int(neu.split("/")[0]) - 2
    p = {(r["ebene"], r["produktgruppe"] or r["produktbereich"], int(r["zeile"])): int(r["betrag"]) for r in plan
         if r["ausgabe"] == neu and r["art"] == "Ergebnis" and int(r["jahr"]) == vj}
    j = {(r["ebene"], r["produktgruppe"] or r["produktbereich"], int(r["zeile"])): round(int(r["betrag_cent"]) / 100)
         for r in rows if int(r["spalte"]) == 1}
    alle_k = set(p) | set(j)
    out["vorjahr_haushaltsplan"] = pruefsumme([(k, j.get(k, 0)) for k in alle_k], {k: p.get(k, 0) for k in alle_k},
                                              f"Teilfinanzrechnung: Ergebnis {vj} gegen Teilfinanzplan A {neu}",
                                              TOLERANZ_EURO, f"Ergebnis {vj} im Haushaltsplan")
    return {k: (*x, "Euro" if k == "vorjahr_haushaltsplan" else "Cent") for k, x in out.items()}


def ist2024_investitionen():
    """Pipeline-Schritt `haushalt-ist2024-investitionen` (einmalig, lokal): data/haushalt/jahresabschluss_investitionen.tsv
    (Teilfinanzrechnungen, Teil A: Zahlungsnachweis, je Produktbereich und Produktgruppe, Zeilen 1–14 wie im
    Teilfinanzplan A, Spalten 1, 2, 4, 5 in Cent) aus dem Jahresabschluss 2024 Teil 2, Vermerk in STAND.json. Eigene
    Datei, weil sich die Zeilennummern 10–14 mit denen der Ergebnisrechnung überschneiden und die Spalten der
    Ermächtigungsübertragungen fehlen; so bleibt jahresabschluss.tsv einheitlich."""
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    rows, gesamt, vermerke = jahresabschluss_investitionen_lesen(_seiten(_pdf(JAHRESABSCHLUSS["url"], JAHRESABSCHLUSS["sha256"])))
    plan = lesen(INVESTITIONEN_TSV)
    pruefung = pruefsummen_ja_investitionen(rows, gesamt, plan)
    neu = max(AUSGABEN)
    im_plan = {r["produktgruppe"]: r["name"] for r in plan if r["ausgabe"] == neu and r["produktgruppe"]}
    im_ja = {r["produktgruppe"]: r["name"] for r in rows if r["ebene"] == "Produktgruppe"}
    pbs = sorted({r["produktbereich"] for r in rows if r["ebene"] == "Produktbereich"})
    _schreiben(JA_INVESTITIONEN_TSV, JA_INVESTITIONEN_KOPF, rows)
    stand["jahresabschluss_investitionen"] = {
        "abruf": datetime.now(timezone.utc).date().isoformat(), "datei": "wie jahresabschluss → datei (SHA-256 geprüft)",
        "teil": "Teilfinanzrechnung, Teil A: Zahlungsnachweis (Investitionstätigkeit); Teil B (Investitionseinzelmaßnahmen) nicht gelesen",
        "gesamtfinanzrechnung_seite": gesamt[0]["seite"],
        "spalten_uebernommen": [{"spalte": k, "art": r["art"], "jahr": r["jahr"], "kopf": JA_KOPF[k - 1]}
                                for k, r in ((int(r["spalte"]), r) for r in gesamt if int(r["zeile"]) == 1)],
        "spalten_weggelassen": {"3": JA_KOPF[2], "6": JA_KOPF[5]},
        "zeilen_im_jahresabschluss": {str(k): v if isinstance(v, str) else v[0] for k, v in JA_INVESTITIONEN.items()},
        "zeilen_gesamtfinanzrechnung": "18–31 = Zeilen 1–14",
        "zeile_12": "kommt in keiner Teilfinanzrechnung vor; Wortlaut erschlossen",
        "leere_zeilen": "Der Jahresabschluss druckt leere Zeilen nicht; sie stehen als 0 mit leer = ja",
        "produktbereiche": pbs, "ohne_teilfinanzrechnung": sorted({f"{i:02d}" for i in range(1, 18)} - set(pbs)),
        "produktgruppen": len(im_ja),
        "produktgruppen_nur_im_haushaltsplan": {pg: im_plan[pg] for pg in sorted(set(im_plan) - set(im_ja))},
        "produktgruppen_nur_im_jahresabschluss": {pg: im_ja[pg] for pg in sorted(set(im_ja) - set(im_plan))},
        "seiten_mit_vermerk": {str(k): v for k, v in vermerke.items()},
        "pruefsummen": _pruefung_json(pruefung), "toleranz_cent": TOLERANZ_CENT, "toleranz_euro_haushaltsplan": TOLERANZ_EURO,
        "bekannte_abweichung_gesamtrechnung_cent": {f"{z}/{s}": a for (z, s), a in JA_ABWEICHUNG_GESAMTFINANZ.items()},
        "hinweis_ermaechtigungsuebertragungen": ("nicht übernommen; in der Gesamtfinanzrechnung (S. 6) hat Zeile 31 in den "
                                                 "Spalten 3 und 6 das Vorzeichen von Zeile 30, nicht 23 − 30 wie in den "
                                                 "Teilfinanzrechnungen"),
        "leere_zellen": {"produktbereiche": sum(r["leer"] == "ja" for r in rows if r["ebene"] == "Produktbereich"),
                         "produktgruppen": sum(r["leer"] == "ja" for r in rows if r["ebene"] == "Produktgruppe")}}
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Jahresabschluss 2024, Investitionen: {len(rows)} Werte ({len(pbs)} Produktbereiche, {len(im_ja)} Produktgruppen); "
          "Prüfsummen " + ", ".join(f"{k} {n} Spalten bis {a} {e}" for k, (n, a, e) in pruefung.items())
          + f" → {JA_INVESTITIONEN_TSV}")


def pruefbogen_erweiterung_finanz():
    """Pipeline-Schritt `haushalt-pruefbogen-erweiterung-finanz` (einmalig): etwa 8 Zellen aus
    jahresabschluss_investitionen.tsv zur Prüfung von Hand, Spalten wie pruefbogen_erweiterung(). Wird nicht
    überschrieben."""
    if ERWEITERUNG_PRUEFBOGEN_FINANZ.exists():
        print(f"Prüfbogen besteht bereits: {ERWEITERUNG_PRUEFBOGEN_FINANZ}")
        return
    einheit = lambda r: r["produktgruppe"] or r["produktbereich"]
    z = {(r["ebene"], einheit(r), int(r["zeile"]), int(r["spalte"])): r for r in lesen(JA_INVESTITIONEN_TSV)}
    b = lambda k: int(z[k]["betrag_cent"])
    auswahl = defaultdict(list)
    for pg in ("1.01.29", "1.16.04"):
        if ("Produktgruppe", pg, 10, 4) in z:
            auswahl[("Produktgruppe", pg, 10, 4)].append("Finanzanlagen, Ist 2024")
    auswahl[("Produktbereich", "03", 13, 4)].append("PB 03, Ist 2024")
    k = max((k for k in z if k[0] == "Produktbereich" and k[2] == 13 and k[3] == 4), key=b)
    auswahl[k].append("größte investive Auszahlungen, Ist 2024")
    neg = sorted(k for k in z if b(k) < 0 and k[2] not in (6, 13, 14) and k[3] in (1, 4))
    if neg:
        auswahl[neg[0]].append("negativer Wert")
    k = max((k for k in z if k[0] == "Produktgruppe" and k[2] == 1 and k[3] == 4), key=b)
    auswahl[k].append("größte Zuwendungen für Investitionen (PG), Ist 2024; Nummer neben zweizeiliger Bezeichnung")
    auswahl[("Produktbereich", "16", 14, 4)].append("Seite ohne Jahr im Kopf (S. 608)")
    auswahl[("Produktbereich", "15", 8, 2)].append("fortgeschriebener Ansatz Baumaßnahmen (Abweichung der Gesamtrechnung)")
    out = []
    for k, gruende in sorted(auswahl.items()):
        r = z[k]
        out.append([r["ebene"], f"{einheit(r)} {r['name']}", f"{r['zeile']} {r['zeile_name']}", r["jahr"], r["art"],
                    r["spalte"], _wie_im_pdf(b(k), True), r["leer"], JAHRESABSCHLUSS["quelle"],
                    f"{JAHRESABSCHLUSS['url']}#page={r['seite']}", r["seite"], ", ".join(gruende), ""])
    ERWEITERUNG_PRUEFBOGEN_FINANZ.parent.mkdir(parents=True, exist_ok=True)
    with open(ERWEITERUNG_PRUEFBOGEN_FINANZ, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["ebene", "einheit", "zeile", "jahr", "art", "spalte", "betrag", "leer", "quelle", "datei", "seite",
                     "auswahl", "pruefung"])
        wr.writerows(out)
    print(f"Prüfbogen Erweiterung (Finanzrechnung): {len(out)} Zellen → {ERWEITERUNG_PRUEFBOGEN_FINANZ}")


# --- Ertragsarten (Option 5, Entscheidungen 03.11.2026; haushalt/PHASE6.md) ---------------------------------------
ERTRAGSARTEN = {1: "Steuern und ähnliche Abgaben", 2: "Zuwendungen und allgemeine Umlagen", 3: "Sonstige Transfererträge",
                4: "Öffentlich-rechtliche Leistungsentgelte", 5: "Privatrechtliche Leistungsentgelte",
                6: "Kostenerstattungen und Kostenumlagen", 7: "Sonstige ordentliche Erträge", 8: "Aktivierte Eigenleistungen",
                9: "Bestandsveränderungen"}
ERTRAGSARTEN_TSV = ORDNER / "ertragsarten.tsv"
ERTRAGSARTEN_KOPF = ["ebene", "ausgabe", "produktbereich", "produktgruppe", "name", "einheit", "zeile", "zeile_name",
                     "jahr", "art", "betrag", "datei", "seite", "leer"]
JA_ERTRAGSARTEN_TSV = ORDNER / "jahresabschluss_ertragsarten.tsv"
ERTRAGSARTEN_FREIGEGEBEN = True   # Prüfbogen im Gespräch bestätigt, freigegeben 03.11.2026 (haushalt/PHASE6.md)
ERTRAGSARTEN_PRUEFBOGEN = config.EXPORT / "haushalt" / "pruefbogen_haushalt_ertragsarten.tsv"


def ertragsarten_an():
    return ERTRAGSARTEN_FREIGEGEBEN or os.environ.get("HAUSHALT_ERTRAGSARTEN") == "vorschau"


def pruefsummen_ertragsarten(plan, ja, produktbereiche, ja_rows):
    """Prüfsummen der Ertragsarten je Spalte; bricht bei Abweichung ab: Zeilen 1–9 = Zeile 10 (Produktbereich und
    Produktgruppe), Zeile 10 = Zeile 10 aus produktbereiche.tsv bzw. jahresabschluss.tsv, Summe der Produktgruppen =
    Produktbereich (Zeile 10)."""
    einheit = lambda r: r["produktgruppe"] if r["ebene"] == "Produktgruppe" else r["produktbereich"]
    k_plan = lambda r: (r["ebene"], r["ausgabe"], einheit(r), int(r["jahr"]), r["art"])
    k_ja = lambda r: (r["ebene"], einheit(r), int(r["spalte"]))
    out = {}
    for name, rows, key, wert, tol in (("Haushaltsplan", plan, k_plan, lambda r: int(r["betrag"]), TOLERANZ),
                                       ("Jahresabschluss", ja, k_ja, lambda r: int(r["betrag_cent"]), TOLERANZ_CENT)):
        z10 = {key(r): wert(r) for r in rows if int(r["zeile"]) == 10}
        out[f"ertragsarten_{name.lower()}"] = pruefsumme([(key(r), wert(r)) for r in rows if int(r["zeile"]) != 10], z10,
                                                         f"Ertragsarten {name}", tol, "Zeile 10")
        # Summe der Produktgruppen = Produktbereich; Schlüssel ohne Ebene, Einheit → Produktbereich (1.04.07 → 04)
        pb_key = (lambda k: (k[1], k[2][2:4] if k[0] == "Produktgruppe" else k[2]) + k[3:]) if name == "Haushaltsplan" \
            else (lambda k: (k[1][2:4] if k[0] == "Produktgruppe" else k[1],) + k[2:])
        gruppen = [(pb_key(k), v) for k, v in z10.items() if k[0] == "Produktgruppe"]
        mit_pg = {k for k, _ in gruppen}
        out[f"produktgruppen_{name.lower()}"] = pruefsumme(
            gruppen, {pb_key(k): v for k, v in z10.items() if k[0] == "Produktbereich" and pb_key(k) in mit_pg},
            f"Produktgruppen {name}", tol, "Zeile 10 des Produktbereichs")
    ref = {("Produktbereich", r["ausgabe"], r["produktbereich"], int(r["jahr"]), r["art"]): int(r["betrag"])
           for r in produktbereiche if int(r["zeile"]) == 10}
    gelesen = {k_plan(r): int(r["betrag"]) for r in plan if int(r["zeile"]) == 10 and r["ebene"] == "Produktbereich"}
    out["zeile10_produktbereiche_tsv"] = pruefsumme(list(gelesen.items()), {k: v for k, v in ref.items() if k in gelesen},
                                                    "Zeile 10 gegen produktbereiche.tsv", 0, "produktbereiche.tsv")
    ref_ja = {k_ja(r): int(r["betrag_cent"]) for r in ja_rows if int(r["zeile"]) == 10}
    gelesen_ja = {k_ja(r): int(r["betrag_cent"]) for r in ja if int(r["zeile"]) == 10}
    out["zeile10_jahresabschluss_tsv"] = pruefsumme(list(gelesen_ja.items()), ref_ja, "Zeile 10 gegen jahresabschluss.tsv",
                                                    0, "jahresabschluss.tsv")
    return out


def ertragsarten():
    """Pipeline-Schritt `haushalt-ertragsarten` (einmalig, lokal, pdftotext -bbox): data/haushalt/ertragsarten.tsv
    (Zeilen 1–10 je Produktbereich und Produktgruppe aus beiden Haushaltsplänen, Euro, ohne Finanzplanung) und
    jahresabschluss_ertragsarten.tsv (dieselben Zeilen aus den Teilergebnisrechnungen des Jahresabschlusses 2024, alle
    sechs Spalten, Cent); Prüfsummen und Vermerk in STAND.json."""
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    nummern = {**ERTRAGSARTEN, 10: ZEILEN[10]}
    plan = []
    for ausgabe, pb, pg, name, einheit, datei, s, ws in teilergebnisplaene(stand):
        cols, werte = koordinaten(ws, nummern)
        _spalten_wie_stand(cols, stand, ausgabe, pb, s)
        kopf_ = {"ebene": "Produktgruppe" if pg else "Produktbereich", "produktbereich": pb, "produktgruppe": pg or "",
                 "name": name if pg else datei["name"], "einheit": (einheit or "") if pg else ""}
        plan += _zellen(kopf_, cols, werte, ausgabe, datei, s, nummern)
    ja, _ = jahresabschluss_lesen(_seiten(_pdf(JAHRESABSCHLUSS["url"], JAHRESABSCHLUSS["sha256"])), nummern)
    pruefung = pruefsummen_ertragsarten(plan, ja, lesen(), lesen(JAHRESABSCHLUSS_TSV))
    _schreiben(ERTRAGSARTEN_TSV, ERTRAGSARTEN_KOPF, plan)
    _schreiben(JA_ERTRAGSARTEN_TSV, JAHRESABSCHLUSS_KOPF, ja)
    stand["ertragsarten"] = {
        "abruf": datetime.now(timezone.utc).date().isoformat(), "zeilen": {str(k): v for k, v in ERTRAGSARTEN.items()},
        "haushaltsplan": {"werte": len(plan), "leere_zellen": sum(r["leer"] == "ja" for r in plan)},
        "jahresabschluss": {"werte": len(ja), "leere_zellen": sum(r["leer"] == "ja" for r in ja),
                            "datei": "wie jahresabschluss → datei (SHA-256 geprüft)"},
        "pruefsummen": {k: {"spalten": n, "groesste_abweichung": a} for k, (n, a) in pruefung.items()},
        "toleranz_euro": TOLERANZ, "toleranz_cent": TOLERANZ_CENT}
    STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Ertragsarten: {len(plan)} Werte aus den Haushaltsplänen, {len(ja)} aus dem Jahresabschluss; Prüfsummen "
          + ", ".join(f"{k} {n} Spalten bis {a}" for k, (n, a) in pruefung.items()))


def pruefbogen_ertragsarten():
    """Pipeline-Schritt `haushalt-pruefbogen-ertragsarten` (einmalig): etwa 30 Zellen aus ertragsarten.tsv und
    jahresabschluss_ertragsarten.tsv zur Prüfung von Hand gegen das PDF, mit Link auf die Seite: negative Werte,
    teilweise gefüllte Zeilen, größte Werte (Steuern, Zuwendungen), aktivierte Eigenleistungen, PB 03 und eine
    Stichprobe über die Produktbereiche, je aus Plan 2026, Plan 2025, Ist 2023 und Ist 2024. Wird nicht überschrieben."""
    if ERTRAGSARTEN_PRUEFBOGEN.exists():
        print(f"Prüfbogen besteht bereits: {ERTRAGSARTEN_PRUEFBOGEN}")
        return
    stand = json.loads(STAND.read_text(encoding="utf-8"))
    einheit = lambda r: r["produktgruppe"] or r["produktbereich"]
    neu = max(AUSGABEN)
    j26, j25 = int(neu.split("/")[1]), int(neu.split("/")[0])
    gezeigt = {(j26, "Ansatz"), (j25, "Ansatz"), (j25 - 2, "Ergebnis")}   # wie haushalt/ (Ist 2023 aus 2025/2026)
    plan = {(r["ebene"], einheit(r), int(r["zeile"]), int(r["jahr"]), r["art"]): r for r in lesen(ERTRAGSARTEN_TSV)
            if r["ausgabe"] == neu and (int(r["jahr"]), r["art"]) in gezeigt and int(r["zeile"]) <= 9}
    ja = {(r["ebene"], einheit(r), int(r["zeile"]), 2024, "Ergebnis"): r for r in lesen(JA_ERTRAGSARTEN_TSV)
          if r["spalte"] == "4" and int(r["zeile"]) <= 9}
    b = lambda q, k: int(q[k]["betrag"]) if q is plan else int(q[k]["betrag_cent"])
    auswahl = {}
    def nimm(q, k, grund):
        auswahl.setdefault((id(q) == id(ja), k), [q, []])[1].append(grund)
    for q, name in ((plan, "Haushaltsplan"), (ja, "Jahresabschluss")):
        neg = sorted(k for k in q if b(q, k) < 0)
        for k in [k for k in neg if k[0] == "Produktbereich"][:2] + [k for k in neg if k[0] == "Produktgruppe"][:2]:
            nimm(q, k, f"negativer Wert ({name})")
        for nr, grund in ((1, "größte Steuern"), (2, "größte Zuwendungen"), (4, "größte öffentlich-rechtliche Leistungsentgelte")):
            k = max((k for k in q if k[0] == "Produktgruppe" and k[2] == nr), key=lambda k: b(q, k))
            nimm(q, k, f"{grund} ({name})")
        k = next((k for k in sorted(q) if k[2] == 8 and b(q, k) > 0), None)
        if k:
            nimm(q, k, f"aktivierte Eigenleistungen ({name})")
        zeilen = defaultdict(list)
        for k in sorted(q):
            zeilen[k[:3]].append(k)
        ks = next(ks for z, ks in zeilen.items() if z[0] == "Produktgruppe" and len({q[k]["leer"] for k in ks}) == 2) if q is plan else []
        for k in (ks and (next(k for k in ks if not q[k]["leer"]), next(k for k in ks if q[k]["leer"])) or ()):
            nimm(q, k, "teilweise gefüllte Zeile")
    for nr in (4, 6):
        nimm(plan, ("Produktbereich", "03", nr, j26, "Ansatz"), "PB 03, Plan 2026")
        nimm(ja, ("Produktbereich", "03", nr, 2024, "Ergebnis"), "PB 03, Ist 2024")
    gruppen = sorted({k[1] for k in plan if k[0] == "Produktgruppe"})
    for i, pb in enumerate(f"{n:02d}" for n in range(2, 18, 3)):
        pgs = [g for g in gruppen if g.startswith(f"1.{pb}.")]
        jahr, art = sorted(gezeigt)[i % 3]
        k = ("Produktgruppe", pgs[i % len(pgs)], (2, 4, 5, 6, 7, 3)[i], jahr, art)
        if k in plan:
            nimm(plan, k, "Stichprobe")
    out = []
    for (aus_ja, k), (q, gruende) in sorted(auswahl.items(), key=lambda x: (x[0][0], x[0][1])):
        r = q[k]
        if aus_ja:
            quelle, url, betrag = JAHRESABSCHLUSS["quelle"], JAHRESABSCHLUSS["url"], _wie_im_pdf(int(r["betrag_cent"]), True)
            spalte = r["spalte"]
        else:
            quelle, betrag = f"Haushaltsplan {neu}", _wie_im_pdf(int(r["betrag"]), False)
            url = stand["ausgaben"][neu]["dateien"][r["produktbereich"]]["url"]
            spalte = stand["ausgaben"][neu]["spalten"].index(f'{r["art"]} {r["jahr"]}') + 1
        out.append([r["ebene"], f"{einheit(r)} {r['name']}", f"{r['zeile']} {r['zeile_name']}", r["jahr"], r["art"],
                    spalte, betrag, r["leer"], quelle, f"{url}#page={r['seite']}", r["seite"], ", ".join(gruende), ""])
    ERTRAGSARTEN_PRUEFBOGEN.parent.mkdir(parents=True, exist_ok=True)
    with open(ERTRAGSARTEN_PRUEFBOGEN, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["ebene", "einheit", "zeile", "jahr", "art", "spalte", "betrag", "leer", "quelle", "datei", "seite",
                     "auswahl", "pruefung"])
        wr.writerows(out)
    print(f"Prüfbogen Ertragsarten: {len(out)} Zellen → {ERTRAGSARTEN_PRUEFBOGEN}")
