"""Strukturdaten Phase 0: einzelne Dateien gedrosselt laden (freigegeben am 10.11.2026).

Freigabe: höchstens 3 Anfragen an offenedaten-koeln.de (Datensatzbeschreibung, XLSX und CSV des Statistischen
Datenkatalogs) und höchstens 15 an wegweiser-kommune.de (OpenAPI, Datenseite, Testexporte für Bonn, Köln und
Wuppertal). Die OParl-API der Stadt wird nicht berührt.

Aufruf (je Datei ein Lauf, damit über jede weitere Anfrage nach Sicht der vorigen entschieden wird):
    RATSATLAS_CACHE=<ordner> RATSATLAS_SPERRE=<ordner> RATSATLAS_MAX_ANFRAGEN=1 \
        python3 explore/strukturdaten/laden.py <quelle> <url> <endung>

Abruf über explore/abruf.py mit denselben Mindestwerten wie explore/geodaten.py (vorgaben(): mindestens 2 s Abstand,
keine Wiederholung, Obergrenze Pflicht; Weiterleitungen werden nicht verfolgt). Die Antwort liegt im Cache
(RATSATLAS_CACHE, außerhalb des Repositorys); eine Zeile je Anfrage kommt nach audit_abruf.tsv im Cache-Ordner
(Quelle, URL, Zeit, Status, Bytes, SHA-256, Pfad). Ein Abbruch (Weiterleitung, HTTP-Fehler, Proxy, mögliche Sperre)
endet mit Rückgabewert 2 und wird ebenso protokolliert. Nur Standardbibliothek.
"""
import csv
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))
import abruf  # noqa: E402
from geodaten import vorgaben  # noqa: E402

SPALTEN = ("quelle", "url", "zeit", "status", "bytes", "sha256", "pfad")
ERLAUBT = {"offenedaten-koeln": "https://www.offenedaten-koeln.de/",
           "wegweiser-kommune": "https://www.wegweiser-kommune.de/"}


def protokoll(zeile):
    datei = abruf.CACHE / "audit_abruf.tsv"
    neu = not datei.exists()
    datei.parent.mkdir(parents=True, exist_ok=True)
    with datei.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, SPALTEN, delimiter="\t", lineterminator="\n")
        if neu:
            w.writeheader()
        w.writerow(zeile)


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 1
    quelle, url, endung = argv[1:]
    if quelle not in ERLAUBT or not url.startswith(ERLAUBT[quelle]):
        print(f"nicht freigegeben: {quelle} {url}")
        return 1
    _, fehler = vorgaben()
    if fehler:
        print("; ".join(fehler))
        return 1
    if "RATSATLAS_CACHE" not in os.environ or "RATSATLAS_SPERRE" not in os.environ:
        print("RATSATLAS_CACHE und RATSATLAS_SPERRE setzen (außerhalb des Repositorys)")
        return 1
    zeit = datetime.now(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")
    try:
        daten = abruf.hole(url, endung)
    except abruf.Abbruch as e:
        protokoll({"quelle": quelle, "url": url, "zeit": zeit, "status": f"abbruch {e.art}: {e}", "bytes": "",
                   "sha256": "", "pfad": ""})
        print(f"Abbruch ({e.art}): {e}")
        return 2
    pfad = abruf._cachepfad(url, endung)
    protokoll({"quelle": quelle, "url": url, "zeit": zeit, "status": "200", "bytes": len(daten),
               "sha256": hashlib.sha256(daten).hexdigest(), "pfad": str(pfad)})
    print(f"ok {len(daten)} Bytes → {pfad}  Anfragen {abruf.zaehler()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
