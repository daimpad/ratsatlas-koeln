"""Datenpaket (Zip) des Ratsatlas Köln: data/export/ratsatlas-koeln-export.zip (CLAUDE.md 2: Ergebnisse als Zip-Paket,
Audit-Protokolle als TSV). Liegt nur auf dem Pages-Spiegel; der Branch deploy verweist dorthin (config.PAKET_URL).

Inhalt: Exporte (ohne Feeds), Audits und Stichproben, Abrufstatistik, Kölner Geodaten (abgeleitet, dl-de/zero 2.0),
Lizenzen und die Berichte der Phasen. Keine Rohdaten der Schnittstelle, keine Volltexte, keine PDFs (CLAUDE.md 6)."""
import zipfile
from pathlib import Path

from . import config

ORDNER = "ratsatlas-koeln"
LIESMICH = f"""Ratsatlas Köln – Datenpaket

Abgeleitet aus dem Ratsinformationssystem der Stadt Köln (OParl-API) und den Geodaten der Stadt Köln.
{config.NAMENSNENNUNG}. Lizenzen je Datei: LICENSE-DATA.md.

Inhalt
- koeln/: Exporte je Stadtteil, Stadtbezirk und ohne Ortsbezug, Suche, Zeitleiste, GeoJSON, DCAT, Kalender
- audit_*.tsv: Prüfprotokolle (Geokodierung mit Methode, Konfidenz und Fundstelle; Prozess; Zeit; Themen)
- stichprobe_geokodierung.tsv: Stichprobe je Methode zur Prüfung von Hand
- abrufstatistik.tsv: Anfragen, Fehler und Dauer je Abruf
- geo/: Stadtteile, Stadtbezirke, Straßen- und Hausnummernverzeichnis (abgeleitet)
- berichte/: Berichte der Projektphasen

Maßgeblich ist immer das Original im Ratsinformationssystem. Abgeleitete Angaben sind gekennzeichnet.
Quellcode: https://github.com/daimpad/ratsatlas-koeln (MIT)
"""


def write(target=None):
    target = Path(target or config.EXPORT / "ratsatlas-koeln-export.zip")
    berichte = sorted(config.ROOT.glob("inventur/BERICHT_*.md")) + [config.ROOT / "explore" / "BERICHT_phase1.md"]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{ORDNER}/LIESMICH.txt", LIESMICH)
        z.write(config.ROOT / "data" / "LICENSE-DATA.md", f"{ORDNER}/LICENSE-DATA.md")
        for path in sorted(config.EXPORT.rglob("*")):
            if path.is_file() and path.suffix != ".zip" and not {"feeds", "chat"} & set(path.parts):
                z.write(path, f"{ORDNER}/{path.relative_to(config.EXPORT)}")
        for path in sorted(config.GEO.glob("*")):
            if path.suffix in (".json", ".geojson", ".tsv"):
                z.write(path, f"{ORDNER}/geo/{path.name}")
        for path in berichte:
            if path.exists():
                z.write(path, f"{ORDNER}/berichte/{path.name}")
    print(f"Datenpaket → {target} ({target.stat().st_size // 1024} KB)")
    return target
