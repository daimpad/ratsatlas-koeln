"""Datenpaket (Zip) des Ratsatlas Köln: data/export/ratsatlas-koeln-export.zip (CLAUDE.md 2: Ergebnisse als Zip-Paket,
Audit-Protokolle als TSV). Liegt nur auf dem Pages-Spiegel; der Branch deploy verweist dorthin (config.PAKET_URL).

Inhalt: Exporte (ohne Feeds), Audits und Stichproben, Abrufstatistik, Geodaten aus data/geo/ (Gebiete, Straßen und
Hausnummern der Stadt Köln, dl-de/zero 2.0; Bebauungspläne aus „Bauleitplanung in NRW“, dl-de/by 2.0), Lizenzen und
die Berichte der Phasen; Lizenz je Datei in data/LICENSE-DATA.md. Keine Rohdaten der Schnittstelle, keine Volltexte,
keine PDFs (CLAUDE.md 6).
Audits, Stichproben und Abrufstatistik gibt es nur hier, nicht als lose Dateien auf der Seite (tools/seite_bauen.py,
Entscheidung 10.11.2026); das Paket entsteht daher vor dem Zusammenstellen der Seite aus ganz data/export.
Mit Freigabe „strukturdaten“ (config.ZUSATZTHEMEN) liegen zusätzlich alle Dateien des Datenvertrags „Strukturdaten“
unverändert unter strukturdaten/ (samt Prüfprotokollen, ohne die Aufteilung für die Seite), und LIESMICH.txt nennt sie
(`liesmich`); LICENSE-DATA.md steht nach den Freigaben im Paket (pipeline/freigaben.py). Ohne Freigabe bleibt das
Paket wie zuvor."""
import zipfile
from pathlib import Path

from . import config, freigaben, strukturdaten_web

ORDNER = "ratsatlas-koeln"
LIESMICH = f"""Ratsatlas Köln – Datenpaket

Abgeleitet aus dem Ratsinformationssystem der Stadt Köln (OParl-API) und den Geodaten der Stadt Köln.
{config.NAMENSNENNUNG}. Bebauungspläne, Kennzahlen und Kartenebenen stammen zum Teil von Land und Bund
und stehen teils unter dl-de/by 2.0 mit eigener Namensnennung. Dezernat und Bezeichnung der federführenden Dienststelle
(responsibility[].aemtertabelle) sind abgeleitet aus dem Geschäfts- und Dezernatsverteilungsplan der Stadt Köln (im
Plan keine Lizenz angegeben; Stand und letzte Prüfung je Zuordnung). Lizenzen je Datei: LICENSE-DATA.md
(dort stehen die Pfade wie im Repository: export/koeln/… entspricht koeln/… in diesem Paket).

Inhalt
- koeln/: Exporte je Stadtteil, Stadtbezirk und ohne Ortsbezug, Suche, Zeitleiste, GeoJSON, DCAT, Kalender,
  Planregister; Kennzahlen (kontext.json) und Flächen für die Karte (flaechen/) mit Quelle und Lizenz in meta
- audit_*.tsv: Prüfprotokolle (Geokodierung mit Methode, Konfidenz und Fundstelle; Prozess; Zeit; Themen;
  Federführung mit Zuordnung zum Geschäfts- und Dezernatsverteilungsplan)
- stichprobe_*.tsv (auch in Unterordnern): Stichproben je Methode zur Prüfung von Hand
- abrufstatistik.tsv: Anfragen, Fehler und Dauer je Abruf
- geo/: Stadtteile, Stadtbezirke, Straßen- und Hausnummernverzeichnis (abgeleitet, Stadt Köln) und
  bebauungsplaene_koeln.geojson (Bauleitplanung in NRW: MHKBD NRW / IT.NRW, Datengrundlage Stadt Köln; dl-de/by 2.0)
- berichte/: Berichte der Projektphasen

Prüfprotokolle, Stichproben und Abrufstatistik gibt es nur in diesem Paket, nicht als einzelne Dateien auf der Seite.

Maßgeblich ist immer das Original im Ratsinformationssystem. Abgeleitete Angaben sind gekennzeichnet.
Quellcode: https://github.com/daimpad/ratsatlas-koeln (MIT)
"""


# Ergänzung von LIESMICH.txt mit Freigabe „strukturdaten“ (nach dem Eintrag zu geo/)
LIESMICH_STRUKTURDATEN = """- strukturdaten/: Strukturdaten im Datenvertrag „Strukturdaten“ (Werte je Gesamtstadt, Stadtbezirk und Stadtteil in
  werte.tsv, je Statistischem Quartier in werte_quartier.tsv.gz, Indikatoren, Flächen, Zuordnung der Raumeinheiten,
  Vergleichswerte des Wegweisers Kommune, meta.json und Prüfprotokolle, darunter eine Stichprobe gegen die Quelle in
  audit_verifikation.tsv). Statistischer Datenkatalog Köln: dl-de/by 2.0 (https://www.govdata.de/dl-de/by-2-0),
  Namensnennung „Stadt Köln, Amt für Stadtentwicklung und Statistik (Statistischer Datenkatalog Köln)“, Datensatz
  https://open.nrw/dataset/statistischer-datenkatalog-koln-k; in lange Tabellenform umgeformt, Werte unverändert, die
  Anteile unter 18 und ab 65 Jahren vom Ratsatlas aus den Altersgruppen berechnet (status abgeleitet). Flächen der
  Statistischen Quartiere: dl-de/zero 2.0, Datenquelle: Stadt Köln – offenedaten-koeln.de. Wegweiser Kommune
  (Bertelsmann Stiftung, wegweiser-kommune.de): CC0 1.0, Datenhalter je Indikator in indikatoren.tsv. Datenstand und
  Abrufdatum in meta.json
"""


def liesmich():
    """LIESMICH.txt des Pakets: mit Freigabe „strukturdaten“ um deren Eintrag ergänzt, sonst unverändert."""
    if not strukturdaten_web.an():
        return LIESMICH
    anker = "- berichte/: Berichte der Projektphasen\n"
    if LIESMICH.count(anker) != 1:
        raise ValueError("LIESMICH: Eintrag zu berichte/ nicht gefunden")
    return LIESMICH.replace(anker, LIESMICH_STRUKTURDATEN + anker)


def write(target=None):
    target = Path(target or config.EXPORT / "ratsatlas-koeln-export.zip")
    berichte = sorted(config.ROOT.glob("inventur/BERICHT_*.md")) + [config.ROOT / "explore" / "BERICHT_phase1.md"]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{ORDNER}/LIESMICH.txt", liesmich())
        z.writestr(f"{ORDNER}/LICENSE-DATA.md", freigaben.datei(config.ROOT / "data" / "LICENSE-DATA.md"))
        for path in sorted(config.EXPORT.rglob("*")):
            if path.is_file() and path.suffix != ".zip" and not {"feeds", "chat"} & set(path.parts):
                z.write(path, f"{ORDNER}/{path.relative_to(config.EXPORT)}")
        for path in sorted(config.GEO.glob("*")):
            if path.suffix in (".json", ".geojson", ".tsv"):
                z.write(path, f"{ORDNER}/geo/{path.name}")
        for path in berichte:
            if path.exists():
                z.write(path, f"{ORDNER}/berichte/{path.name}")
        if strukturdaten_web.an():   # Datenvertrag unverändert, mit Prüfprotokollen (Entscheidung 10.11.2026)
            for path, name in strukturdaten_web.paketdateien():
                z.write(path, f"{ORDNER}/{name}")
    print(f"Datenpaket → {target} ({target.stat().st_size // 1024} KB)")
    return target
