"""Wahlbeteiligung der Ratswahl 2025 je Stadtteil aus einer Datei der Stadt Köln – lokal, ohne Netz (pipeline/wahl_koeln.py).

Aufruf (Python isoliert, alle Pfade als Argumente; die Datei legt jemand von Hand ab, nie dieses Skript):
  python -I tools/wahlbeteiligung.py --datei <XLSX|CSV|TSV> [--blatt <Name>] [--ohne-wahlpruefung]
  # Vorgabe: nur prüfen (Abgleich mit den 86 Stadtteilen in data/geo, Summen), nichts schreiben
  python -I tools/wahlbeteiligung.py --datei <Pfad> --schreiben --lizenz dl-de/by-2.0 --namensnennung "<Text>"
                                     --url <Adresse der Datei> --titel "<Titel>" --abgerufen JJJJ-MM-TT

Geschrieben werden data/kontext/wahl2025_stadtteile.tsv (Spalten wahl_koeln.SPALTEN, keine Ergebnisse der Parteien)
und der Eintrag „wahl2025“ in data/kontext/STAND.json, nur mit klarer Lizenz (dl-de/zero-2.0 oder dl-de/by-2.0 mit
Namensnennung); sonst Abbruch ohne Änderung. Angezeigt wird die Kennzahl erst mit der Freigabe „wahlbeteiligung“
(config.ZUSATZTHEMEN; TECHNIK.md, „Wahlbeteiligung je Stadtteil“).

Ausgabe nur Angaben zur Datei, Summen und Zahl der Stadtteile außerhalb von 20–95 % (wie `check`), keine Werte
einzelner Stadtteile. Exit-Code 0 bei Erfolg, 1 bei Fehlern der Datei oder des Abgleichs, 2 ohne klare Lizenz.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import wahl_koeln  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--datei", required=True, type=Path)
    ap.add_argument("--blatt", help="Blatt der XLSX, wenn mehrere Tabellen passen")
    ap.add_argument("--ohne-wahlpruefung", action="store_true",
                    help="Blattname und Titel nicht auf „Ratswahl/Kommunalwahl 2025“ prüfen (in STAND.json vermerkt)")
    ap.add_argument("--summe-wahlberechtigte", type=int, help="Vergleichswert der ganzen Stadt (nur Ausgabe)")
    ap.add_argument("--summe-waehler", type=int, help="Vergleichswert der ganzen Stadt (nur Ausgabe)")
    ap.add_argument("--schreiben", action="store_true")
    ap.add_argument("--lizenz", default="")
    ap.add_argument("--namensnennung", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--titel", default="Kommunalwahl 2025 in Köln, Ratswahl: Wahlberechtigte und Wähler je Stadtteil "
                                        "(Stadt Köln, Amt für Stadtentwicklung und Statistik)")
    ap.add_argument("--abgerufen", default="")
    ap.add_argument("--tsv", type=Path, default=wahl_koeln.TSV)
    ap.add_argument("--stand", type=Path, default=wahl_koeln.STAND)
    a = ap.parse_args(argv)
    try:
        gelesen = wahl_koeln.lesen(a.datei, a.blatt, wahl_pruefen=not a.ohne_wahlpruefung)
        zeilen = wahl_koeln.ableiten(gelesen)
    except (OSError, ValueError) as err:
        print(f"Wahlbeteiligung: {err}", file=sys.stderr)
        return 1
    z = wahl_koeln.zusammenfassung(gelesen, zeilen)
    print(f"Wahlbeteiligung: {z['datei']} (sha256 {z['sha256'][:12]}…), Format {z['format']}, Blatt „{z['blatt']}“, "
          f"Kennung „{z['kennung']}“{'' if z['wahl_geprueft'] else ' (Wahl nicht geprüft)'}")
    print(f"  Spalten: {z['spalten']}; Wähler aus: {z['waehler_aus']}; Summenzeilen übergangen: {gelesen['summenzeilen']}")
    print(f"  {z['stadtteile']} Stadtteile wie data/geo; Summe Wahlberechtigte {z['wahlberechtigte']}, Wähler {z['waehler']}, "
          f"Beteiligung {z['beteiligung_prozent']} %; außerhalb 20–95 %: {z['ausserhalb_20_95']}")
    for was, soll in (("wahlberechtigte", a.summe_wahlberechtigte), ("waehler", a.summe_waehler)):
        if soll is not None:
            print(f"  Vergleich {was}: Datei {z[was]}, angegeben {soll}, Unterschied {z[was] - soll}")
    if not a.schreiben:
        print("  nur geprüft, nichts geschrieben (--schreiben mit --lizenz, --namensnennung, --url, --abgerufen)")
        return 0
    grund = wahl_koeln.lizenz_klar(a.lizenz, a.namensnennung)
    if grund:
        print(f"Wahlbeteiligung: nichts geschrieben: {grund}", file=sys.stderr)
        return 2
    try:
        tsv, stand = wahl_koeln.schreiben(gelesen, zeilen, url=a.url, titel=a.titel, lizenz=a.lizenz,
                                          namensnennung=a.namensnennung, abgerufen=a.abgerufen, tsv=a.tsv, stand=a.stand)
    except ValueError as err:
        print(f"Wahlbeteiligung: {err}", file=sys.stderr)
        return 1
    print(f"  geschrieben: {tsv}, {stand} („{wahl_koeln.STAND_SCHLUESSEL}“)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
