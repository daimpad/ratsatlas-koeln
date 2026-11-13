"""Strukturdaten Phase 4: Verifikation veröffentlichter Werte gegen die Quelle (13.11.2026).

Zieht eine reproduzierbare Stichprobe von 20 Werten aus data/strukturdaten/ (je 5 aus gesamtstadt, stadtbezirk und
stadtteil in werte.tsv und aus quartier in werte_quartier.tsv.gz), sucht jede Zelle unabhängig von
pipeline/strukturdaten.py in der XLSX des Statistischen Datenkatalogs Köln und vergleicht Wert, Status, Indikator,
Einheit, Jahr und Raumeinheit; dazu die Werte eines Wegweiser-Exports für Köln mit gesamtstadt.tsv. Ergebnis:
audit_verifikation.tsv (Spalten unter meta.json, audit_verifikation_spalten). Ohne Netz, nur lesend; der Code der
Pipeline wird nicht importiert.

Aufruf (Pfade als Argumente, Python isoliert):
    python3 -I explore/strukturdaten/verifikation.py --xlsx <XLSX> --wegweiser <CSV> --daten data/strukturdaten \
        --aus data/strukturdaten/audit_verifikation.tsv

Ziehung (nur aus den veröffentlichten Dateien, Startwert STARTWERT, random.Random): Je Raumebene werden die Plätze aus
PLAN der Reihe nach besetzt; je Platz wird aus dem Vorrat (Zeilen in Dateireihenfolge) gezogen, bis eine Zeile passt:
Indikator in der ganzen Stichprobe noch nicht gezogen, Jahr in dieser Raumebene noch nicht gezogen. Vorräte:
- ok: Kölner Indikatoren der Quelle (koeln_…, ohne die abgeleiteten koeln_abg_…) mit status ok;
- abgeleitet: Zeilen des genannten abgeleiteten Indikators mit status abgeleitet;
- fehlt: Kölner Indikatoren der Quelle mit status fehlt;
- geheim: Kölner Indikatoren der Quelle mit status geheim, nur Indikatoren, die keine Anzahl sind und an keiner in
  indikatoren.tsv genannten Beziehung beteiligt sind (zaehler_id und nenner_id leer, nicht als Zähler oder Nenner eines
  anderen genannt). Von geheim gehaltenen Zellen wird nur der Status verglichen; die Datei enthält keinen Wert dazu.

Prüfung je Zelle: Spalte nach dem Code im Kopf des Blatts Daten („<Code> - <Name>“), Zeile nach Jahr (Spalte A) und
Raum (Spalte B „<Nummer> / <Name>“, Spalte C Raumebene); Wert (Zahl unverändert, „*“ = geheim, leer = fehlt), Fundstelle
gleich quellobjekt, Name des Indikators gleich indikatoren.tsv, Einheit passend zur Endung des Codes und zum Formatfeld
im Blatt Katalog (A: abs und Anzahl, P: % und %, S: andere), Name der Raumeinheit gleich raum/<raumebene>.geojson,
Stadtbezirk eines Stadtteils und Stadtteil eines Quartiers nach zuordnung.tsv gleich der Nummer und eltern_id.
Abgeleitete Anteile (meta.json, abgeleitet): aus den veröffentlichten Eingangswerten derselben Zeile dezimal
nachgerechnet und kaufmännisch gerundet (ROUND_HALF_UP), Eingangszellen ebenso in der XLSX geprüft.
"""
import argparse
import csv
import gzip
import hashlib
import json
import random
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

STARTWERT = 20261113
EBENEN = ("gesamtstadt", "stadtbezirk", "stadtteil", "quartier")
# Plätze je Raumebene (Schichtung): mindestens 2 abgeleitete Anteile, 1 geheim gehaltene und 2 fehlende Zellen
PLAN = {
    "gesamtstadt": ("abgeleitet:koeln_abg_unter18", "ok", "ok", "ok", "ok"),
    "stadtbezirk": ("fehlt", "ok", "ok", "ok", "ok"),
    "stadtteil": ("abgeleitet:koeln_abg_ab65", "ok", "ok", "ok", "ok"),
    "quartier": ("geheim", "fehlt", "ok", "ok", "ok"),
}
EBENE_IM_BLATT = {"Gesamtstadt": "gesamtstadt", "Stadtbezirke": "stadtbezirk", "Stadtteile": "stadtteil",
                  "Statistische Quartiere": "quartier"}
ENDUNG = {"A": ("abs", "Anzahl"), "P": ("%", "%"), "S": ("andere", None)}
KOMMUNE = {"Köln": "koeln"}   # Name im Wegweiser-Export → kommune in gesamtstadt.tsv
KOPF = ["nr", "pruefung", "ebene", "raum_id", "raum_name", "indikator", "einheit", "jahr", "wert_veroeffentlicht",
        "status_veroeffentlicht", "quelle", "fundstelle", "wert_quelle", "ergebnis", "bemerkung"]
QUELLE_XLSX = "Statistischer Datenkatalog Köln, XLSX vom 13.11.2026"
QUELLE_ABGELEITET = "eigene Nachrechnung aus werte.tsv; Eingangswerte: " + QUELLE_XLSX
QUELLE_WW = "Wegweiser Kommune, CSV-Export vom 13.11.2026"
_SPALTE = re.compile(r"([A-Z]\d{4}[APS]) - (.+)", re.S)
_RAUM = re.compile(r"(\d+) / (.+)")


def tsv(pfad):
    with open(pfad, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def werte_zeilen(daten):
    """Zeilen von werte.tsv und werte_quartier.tsv.gz als Tupel (Kopf wie werte.tsv), in Dateireihenfolge."""
    kopf = None
    for pfad, oeffnen in ((daten / "werte.tsv", open), (daten / "werte_quartier.tsv.gz", gzip.open)):
        with oeffnen(pfad, "rt", encoding="utf-8", newline="") as fh:
            k = fh.readline().rstrip("\n").split("\t")
            if kopf is None:
                kopf = k
            elif k != kopf:
                raise ValueError(f"{pfad.name}: Kopf anders als werte.tsv")
            for zeile in fh:
                yield tuple(zeile.rstrip("\n").split("\t"))


def zahl_text(wert):
    """Zahl einer XLSX-Zelle als Text: ganze Zahlen unverändert, sonst die kürzeste Schreibweise mit Punkt, ohne
    Exponent (Schreibweise laut meta.json, formate.wert)."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise TypeError(f"keine Zahl: {wert!r}")
    if isinstance(wert, int):
        return str(wert)
    text = repr(wert)
    return format(Decimal(text), "f") if "e" in text.lower() else text


def de_zahl(text):
    """„1.084.831“ → „1084831“, „42,1“ → „42.1“ (Wegweiser-Export)."""
    text = text.strip()
    if not re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", text):
        raise ValueError(f"unerwarteter Wert im Wegweiser-Export: {text!r}")
    return text.replace(".", "").replace(",", ".")


def ziehen(daten, indikatoren, rng):
    """Stichprobe nach PLAN: [(Platz, Zeile)] mit Zeile = (raumebene, raum_id, indikator_id, jahr, wert, status,
    quellobjekt)."""
    bezogen = {i[k] for i in indikatoren.values() for k in ("zaehler_id", "nenner_id") if i[k]}
    geheim_erlaubt = {iid for iid, i in indikatoren.items()
                      if not i["zaehler_id"] and not i["nenner_id"] and iid not in bezogen and i["typ"] != "anzahl"}
    vorrat = {}
    for z in werte_zeilen(daten):
        ebene, _, iid, _, _, status, _ = z
        quelle = iid.startswith("koeln_") and not iid.startswith("koeln_abg_")
        if status == "abgeleitet":
            platz = f"abgeleitet:{iid}"
        elif status in ("ok", "fehlt") and quelle:
            platz = status
        elif status == "geheim" and quelle and iid in geheim_erlaubt:
            platz = "geheim"
        else:
            continue
        vorrat.setdefault((ebene, platz), []).append(z)
    stichprobe, indikatoren_gezogen = [], set()
    for ebene in EBENEN:
        jahre = set()
        for platz in PLAN[ebene]:
            zeilen = vorrat.get((ebene, platz), [])
            if not zeilen:
                raise ValueError(f"kein Vorrat für {ebene}/{platz}")
            for _ in range(100_000):
                z = zeilen[rng.randrange(len(zeilen))]
                if z[2] not in indikatoren_gezogen and z[3] not in jahre:
                    break
            else:
                raise ValueError(f"keine passende Zeile für {ebene}/{platz}")
            indikatoren_gezogen.add(z[2])
            jahre.add(z[3])
            stichprobe.append((platz, z))
    return stichprobe


class Blatt:
    """Blatt Daten der XLSX: Spalte je Code, Zeile je (Raumebene, Raum, Jahr), gelesene Zellen; dazu das Formatfeld
    des Blatts Katalog je ID."""

    def __init__(self, pfad):
        with open(pfad, "rb") as fh:
            mappe = openpyxl.load_workbook(fh, read_only=True, data_only=True)
            try:
                daten = mappe["Daten"]
                kopf = next(daten.iter_rows(min_row=1, max_row=1, values_only=True))
                if tuple(kopf[:3]) != ("Jahr", "Raum", "Raumebene"):
                    raise ValueError(f"Blatt Daten: unerwarteter Kopf {kopf[:3]!r}")
                self.spalte, self.name = {}, {}
                for nr, text in enumerate(kopf, 1):
                    m = _SPALTE.fullmatch(str(text or ""))
                    if m:
                        self.spalte[m.group(1)] = nr
                        self.name[m.group(1)] = m.group(2)
                self.zeilen, self.zellen = {}, {}
                for nr, z in enumerate(daten.iter_rows(min_row=2, values_only=True), 2):
                    if z[0] is None:
                        continue
                    m = _RAUM.fullmatch(str(z[1]))
                    if not m:
                        raise ValueError(f"Blatt Daten, Zeile {nr}: Raum {z[1]!r}")
                    schluessel = (z[2], m.group(1), str(z[0]))
                    if schluessel in self.zeilen:
                        raise ValueError(f"Blatt Daten: Zeile doppelt {schluessel}")
                    self.zeilen[schluessel] = (nr, m.group(2))
                    self.zellen[nr] = z
                katalog = mappe["Katalog"]
                k2 = next(katalog.iter_rows(min_row=2, max_row=2, values_only=True))
                if tuple(k2[2:7]) != ("ID", "Name", "abs", "%", "andere"):
                    raise ValueError(f"Blatt Katalog: unerwarteter Kopf {k2[2:7]!r}")
                self.format = {}
                for z in katalog.iter_rows(min_row=3, values_only=True):
                    if z[2]:
                        self.format.setdefault(str(z[2]), set()).update(
                            f for f, x in zip(("abs", "%", "andere"), z[4:7]) if x)
            finally:
                mappe.close()

    def zelle(self, ebene, raum_id, jahr, code):
        """(Fundstelle, Wert, Name der Raumeinheit im Blatt)."""
        label = next(k for k, v in EBENE_IM_BLATT.items() if v == ebene)
        nr, raum_name = self.zeilen[(label, raum_id, jahr)]
        sp = self.spalte[code]
        return f"Daten!{get_column_letter(sp)}{nr}", self.zellen[nr][sp - 1], raum_name


def status_der_quelle(wert):
    if wert is None or (isinstance(wert, str) and not wert.strip()):
        return "fehlt", ""
    if isinstance(wert, str) and wert.strip() == "*":
        return "geheim", ""
    return "ok", zahl_text(wert)


def raum_pruefen(ebene, raum_id, raum_name, raeume, zuordnung):
    """Abweichungen der Raumeinheit (Name laut Geometrie, Zuordnung laut zuordnung.tsv, Nummer und eltern_id)."""
    fehler = []
    if ebene == "gesamtstadt":
        if raum_id != "0":
            fehler.append(f"Gesamtstadt mit Nummer {raum_id}")
        return fehler
    props = raeume[ebene].get(raum_id)
    if props is None:
        return [f"Raumeinheit {raum_id} fehlt in raum/{ebene}.geojson"]
    if props["name"] != raum_name:
        fehler.append(f"Name laut Geometrie {props['name']!r}")
    if ebene == "stadtbezirk":
        teile = [z for z in zuordnung if z["nach_ebene"] == "stadtbezirk" and z["nach_id"] == raum_id]
        if not teile or any(z["von_id"][0] != raum_id for z in teile):
            fehler.append("Stadtteile in zuordnung.tsv passen nicht zur Nummer")
    else:
        nach = {"stadtteil": ("stadtbezirk", 1), "quartier": ("stadtteil", 3)}[ebene]
        ziele = [z for z in zuordnung if z["von_ebene"] == ebene and z["von_id"] == raum_id]
        if [z["nach_id"] for z in ziele] != [raum_id[:nach[1]]] or ziele[0]["nach_ebene"] != nach[0]:
            fehler.append(f"zuordnung.tsv nennt {[z['nach_id'] for z in ziele]}")
        if props.get("eltern_id") != raum_id[:nach[1]]:
            fehler.append(f"eltern_id {props.get('eltern_id')!r}")
    return fehler


def einheit_pruefen(code, einheit, blatt):
    fmt, erwartet = ENDUNG[code[-1]]
    fehler = []
    if fmt not in blatt.format.get(code[:-1], set()):
        fehler.append(f"Blatt Katalog ohne Format {fmt} für {code[:-1]}")
    if erwartet is not None and einheit != erwartet:
        fehler.append(f"Einheit {einheit!r} statt {erwartet!r}")
    if erwartet is None and einheit in ("Anzahl", "%"):
        fehler.append(f"Einheit {einheit!r} bei Endung S")
    return fehler


def wegweiser(pfad, indikatoren, gesamt):
    """Zeilen für die Werte des Wegweiser-Exports (Köln) im Vergleich mit gesamtstadt.tsv."""
    text = Path(pfad).read_text(encoding="utf-8-sig")
    zeilen = list(csv.reader(text.splitlines(keepends=True), delimiter=";"))
    kopf_nr = next(n for n, z in enumerate(zeilen) if z and z[0] == "Indikatoren")
    kopf = zeilen[kopf_nr]
    spalten = []
    for zelle in kopf[1:]:
        jahr, kommune = zelle.split("\n")
        spalten.append((jahr.strip(), kommune.strip()))
    nach_name = {(i["name"], i["einheit"]): iid for iid, i in indikatoren.items() if iid.startswith("ww_")}
    aus = []
    for z in zeilen[kopf_nr + 1:]:
        if not z or not z[0].strip():
            break
        m = re.fullmatch(r"(.+) \((.+)\)", z[0])
        iid = nach_name.get((m.group(1), m.group(2))) if m else None
        for (jahr, kommune), roh in zip(spalten, z[1:]):
            k = KOMMUNE.get(kommune)
            fehler = [] if iid else [f"Indikator {z[0]!r} nicht in indikatoren.tsv (Name und Einheit)"]
            if k is None:
                fehler.append(f"Kommune {kommune!r} unbekannt")
            veroeff = gesamt.get((k, iid, jahr))
            wert_quelle = de_zahl(roh)
            if veroeff is None:
                fehler.append("keine Zeile in gesamtstadt.tsv")
            elif Decimal(veroeff) != Decimal(wert_quelle) or veroeff != wert_quelle:
                fehler.append("Wert abweichend")
            aus.append({
                "pruefung": "wegweiser", "ebene": "gesamtstadt", "raum_id": k or "", "raum_name": kommune,
                "indikator": iid or "", "einheit": indikatoren[iid]["einheit"] if iid else "", "jahr": jahr,
                "wert_veroeffentlicht": veroeff or "", "status_veroeffentlicht": "", "quelle": QUELLE_WW,
                "fundstelle": f"Zeile „{z[0]}“, Spalte „{jahr} {kommune}“", "wert_quelle": wert_quelle,
                "ergebnis": "abweichend" if fehler else "gleich",
                "bemerkung": "; ".join(fehler) if fehler else
                f"im Export {roh}; gleich gesamtstadt.tsv (kommune {k}, {iid}, {jahr}); Indikator und Einheit laut "
                "Zeilenkopf gleich indikatoren.tsv"})
    return aus


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--xlsx", required=True, type=Path)
    ap.add_argument("--wegweiser", required=True, type=Path)
    ap.add_argument("--daten", required=True, type=Path)
    ap.add_argument("--aus", required=True, type=Path)
    a = ap.parse_args(argv)
    daten = a.daten
    indikatoren = {i["indikator_id"]: i for i in tsv(daten / "indikatoren.tsv")}
    meta = json.loads((daten / "meta.json").read_text(encoding="utf-8"))
    abgeleitet = meta["abgeleitet"]["indikatoren"]
    zuordnung = tsv(daten / "zuordnung.tsv")
    raeume = {e: {str(f["properties"]["raum_id"]): f["properties"] for f in
                  json.loads((daten / "raum" / f"{e}.geojson").read_text(encoding="utf-8"))["features"]}
              for e in ("stadtbezirk", "stadtteil", "quartier")}
    gesamt = {(g["kommune"], g["indikator_id"], g["jahr"]): g["wert"] for g in tsv(daten / "gesamtstadt.tsv")}

    stichprobe = ziehen(daten, indikatoren, random.Random(STARTWERT))
    # Eingangswerte der abgeleiteten Anteile: veröffentlichte Zeilen derselben Raumeinheit und desselben Jahres
    benoetigt = {}
    for platz, (ebene, raum_id, iid, jahr, *_) in stichprobe:
        if platz.startswith("abgeleitet:"):
            f = abgeleitet[iid]
            for code in [*f["zaehler"], f["nenner"]]:
                benoetigt[(ebene, raum_id, code, jahr)] = None
    for z in werte_zeilen(daten):
        if z[:4] in benoetigt:
            benoetigt[z[:4]] = z

    # nur gegen die Datei, aus der die veröffentlichten Werte stammen (Prüfsumme in meta.json, quellen)
    soll = next(q["sha256"] for q in meta["quellen"] if q["kennung"] == "statistischer-datenkatalog-koeln")
    ist = hashlib.sha256(a.xlsx.read_bytes()).hexdigest()
    if ist != soll:
        raise SystemExit(f"{a.xlsx}: Prüfsumme {ist} ungleich meta.json ({soll}); Stichprobe nicht vergleichbar")
    print(f"XLSX sha256 {ist} (gleich meta.json); Wegweiser-Export sha256 "
          f"{hashlib.sha256(a.wegweiser.read_bytes()).hexdigest()}")
    blatt = Blatt(a.xlsx)
    aus = []
    for platz, (ebene, raum_id, iid, jahr, wert, status, quellobjekt) in stichprobe:
        ind = indikatoren[iid]
        fehler = []
        if platz.startswith("abgeleitet:"):
            f = abgeleitet[iid]
            codes = [c.removeprefix("koeln_") for c in [*f["zaehler"], f["nenner"]]]
            zellen, eingaenge = [], []
            raum_name = ""
            for code in codes:
                z = benoetigt[(ebene, raum_id, "koeln_" + code, jahr)]
                ref, w, raum_name = blatt.zelle(ebene, raum_id, jahr, code)
                zellen.append(ref)
                st, wq = status_der_quelle(w)
                if z is None or z[5] != "ok" or st != "ok" or Decimal(z[4]) != Decimal(wq) or z[6] != ref:
                    fehler.append(f"Eingangswert {code} weicht ab oder fehlt")
                eingaenge.append(Decimal(z[4]) if z else Decimal(0))
            *zaehler, nenner = eingaenge
            nach = (sum(zaehler) / nenner * f["faktor"]).quantize(Decimal(1).scaleb(-f["stellen"]), ROUND_HALF_UP)
            fundstelle = f"({'+'.join(zellen[:-1])})/{zellen[-1]}*{f['faktor']}"
            wert_quelle = str(nach)
            if status != "abgeleitet" or wert != wert_quelle:
                fehler.append("Wert abweichend")
            if quellobjekt != fundstelle:
                fehler.append(f"quellobjekt {quellobjekt}")
            if ind["einheit"] != "%" or ind["typ"] != "anteil":
                fehler.append("Einheit oder Typ abweichend")
            quelle = QUELLE_ABGELEITET
            gleich_text = ("aus den veröffentlichten Eingangswerten derselben Zeile nachgerechnet (Formel unter meta.json "
                           "abgeleitet), kaufmännisch auf 2 Stellen gerundet; Eingangszellen in der XLSX gleich; "
                           "Fundstelle gleich quellobjekt")
        else:
            code = iid.removeprefix("koeln_")
            fundstelle, w, raum_name = blatt.zelle(ebene, raum_id, jahr, code)
            st, wert_quelle = status_der_quelle(w)
            if st != status:
                fehler.append(f"Status der Quelle {st}")
            elif st == "ok" and (Decimal(wert) != Decimal(wert_quelle) or wert != wert_quelle):
                fehler.append("Wert abweichend")
            elif st != "ok" and wert:
                fehler.append("Wert ohne Zahl in der Quelle")
            if quellobjekt != fundstelle:
                fehler.append(f"quellobjekt {quellobjekt}")
            if blatt.name[code] != ind["name"]:
                fehler.append("Name des Indikators abweichend")
            fehler += einheit_pruefen(code, ind["einheit"], blatt)
            quelle = QUELLE_XLSX
            gleich_text = {
                "ok": "Wert, Indikator (Kopf der Spalte), Einheit, Jahr und Raumeinheit gleich; Fundstelle gleich "
                      "quellobjekt",
                "fehlt": "Zelle in der Quelle leer, status fehlt; Indikator, Einheit, Jahr und Raumeinheit gleich; "
                         "Fundstelle gleich quellobjekt",
                "geheim": "Zelle in der Quelle als geheim gekennzeichnet; nur der Status verglichen; Indikator, "
                          "Einheit, Jahr und Raumeinheit gleich; Fundstelle gleich quellobjekt"}[status]
        fehler += raum_pruefen(ebene, raum_id, raum_name, raeume, zuordnung)
        if status == "geheim":
            ergebnis = "abweichend" if fehler else "nur_status"
            wert_quelle = ""
        else:
            ergebnis = "abweichend" if fehler else "gleich"
        aus.append({"pruefung": "stichprobe", "ebene": ebene, "raum_id": raum_id, "raum_name": raum_name,
                    "indikator": iid, "einheit": ind["einheit"], "jahr": jahr, "wert_veroeffentlicht": wert,
                    "status_veroeffentlicht": status, "quelle": quelle, "fundstelle": fundstelle,
                    "wert_quelle": wert_quelle, "ergebnis": ergebnis,
                    "bemerkung": "; ".join(fehler) if fehler else gleich_text})
    aus += wegweiser(a.wegweiser, indikatoren, gesamt)
    for nr, z in enumerate(aus, 1):
        z["nr"] = str(nr)
        for k, v in z.items():
            if "\t" in v or "\n" in v:
                raise ValueError(f"Zeile {nr}, {k}: Tabulator oder Zeilenumbruch")
    a.aus.parent.mkdir(parents=True, exist_ok=True)
    with open(a.aus, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(KOPF) + "\n")
        for z in aus:
            fh.write("\t".join(z[k] for k in KOPF) + "\n")
    zaehlung = {}
    for z in aus:
        zaehlung[z["ergebnis"]] = zaehlung.get(z["ergebnis"], 0) + 1
    print(f"{a.aus}: {len(aus)} Zeilen, {dict(sorted(zaehlung.items()))}")
    return 1 if zaehlung.get("abweichend") else 0


if __name__ == "__main__":
    sys.exit(main())
