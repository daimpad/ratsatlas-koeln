"""Seite zusammenstellen wie der künftige Veröffentlichungslauf (Phase 5): site/ + data/export + Geodaten → _site/.

Aufruf: python3 tools/seite_bauen.py [ziel]   (Vorgabe: _site; nicht versioniert)
Danach z. B.: python3 -m http.server -d _site 8000

Audit-Protokolle, Stichproben und die Abrufstatistik (NUR_IM_PAKET) kommen nicht als lose Dateien auf die Seite, also
weder in den Branch deploy noch auf den Spiegel; sie liegen nur im Datenpaket (Entscheidung 10.11.2026). pages.yml
packt das Datenpaket (python -m pipeline package) vor diesem Schritt aus data/export, daher enthält es sie weiter.

data/LICENSE-DATA.md kommt nach den Freigaben auf die Seite (pipeline/freigaben.py: Abschnitte nur mit oder nur ohne
Freigabe). Strukturdaten (data/strukturdaten/, aufgeteilt für die Seite) nur mit Freigabe „strukturdaten“
(pipeline/strukturdaten_web.py); ohne sie gibt es keinen Ordner data/strukturdaten/ auf der Seite.
"""
import fnmatch
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import config, freigaben, seo, strukturdaten_web  # noqa: E402

# Karte im Menü „Daten“ (index.html): Link mit `download` auf eine Datei unter data/export/, Kartentext bis zum Ende
KARTE_DOWNLOAD = re.compile(r'(?P<kopf><a class="card" href="(?P<href>data/export/[^"]+)" download>(?:(?!</a>).)*?'
                            r'<span class="card-text">)(?P<text>[^<]*?)(?P<punkt>\.?)</span></a>', re.S)


# Nur im Datenpaket (pipeline/paket.py), nicht als lose Dateien unter _site/data/export (in jedem Unterordner)
NUR_IM_PAKET = ("audit_*.tsv", "stichprobe_*.tsv", "abrufstatistik.tsv")
# Ordner aus site/, die nur mit Freigabe (config.ZUSATZTHEMEN) auf die Seite kommen: chat/ enthält die Module und den
# Bonner Systemprompt des Ratsassistenten; app.js lädt chat/ui.js nur über dessen Schaltfläche (data-funktion="chat").
# strukturdaten/ enthält Modul und Stile der Strukturdaten (Kontext-Panel, Flächenfarben); app.js lädt sie nur mit
# Freigabe „strukturdaten“ (Entscheidung 10.11.2026). Die Daten liegen getrennt davon unter data/strukturdaten/.
ORDNER_MIT_FREIGABE = {"chat": "chat", "strukturdaten": "strukturdaten"}


def ohne_abgeschaltete_ordner(ziel):
    """Ordner aus ORDNER_MIT_FREIGABE in `ziel` entfernen, wenn die Freigabe fehlt (Entscheidung 10.11.2026)."""
    for funktion, ordner in ORDNER_MIT_FREIGABE.items():
        if not config.ZUSATZTHEMEN.get(funktion):
            shutil.rmtree(Path(ziel) / ordner, ignore_errors=True)


def nur_im_paket(name):
    """True für Dateinamen aus NUR_IM_PAKET (Audit-Protokolle, Stichproben, Abrufstatistik)."""
    return any(fnmatch.fnmatchcase(name, muster) for muster in NUR_IM_PAKET)


def _ohne_paketdateien(ordner, namen):
    """`ignore` für shutil.copytree: Dateien aus NUR_IM_PAKET auslassen."""
    return {n for n in namen if nur_im_paket(n) and (Path(ordner) / n).is_file()}


def exporte_kopieren(quelle, ziel):
    """data/export → ziel ohne die Dateien aus NUR_IM_PAKET; Ordner, die dadurch leer bleiben (etwa hausnummern/ mit
    nur der Stichprobe), entfallen."""
    shutil.copytree(quelle, ziel, ignore=_ohne_paketdateien)
    for ordner in sorted(Path(ziel).rglob("*"), reverse=True):   # Unterordner vor ihren Eltern
        if ordner.is_dir() and not any(ordner.iterdir()) and any((Path(quelle) / ordner.relative_to(ziel)).iterdir()):
            ordner.rmdir()


def groesse_text(n):
    """Dateigröße in Bytes als kurzer deutscher Text (1 MB = 1 000 000 Bytes): „74 MB“, „2,5 MB“, „830 kB“; zwischen
    Zahl und Einheit ein geschütztes Leerzeichen (kein Umbruch in der Karte)."""
    if n >= 9_950_000:
        return f"{round(n / 1_000_000)} MB"
    if n >= 999_500:
        return f"{n / 1_000_000:.1f} MB".replace(".", ",")
    return f"{max(1, round(n / 1000)) if n else 0} kB"


def groessen_eintragen(ziel):
    """Menü „Daten“: Karten zum Herunterladen nennen die Größe der Datei im fertigen Ordner `ziel` im Kartentext
    („Alle Exporte, Audit-Protokolle und Lizenzen (74 MB).“). Fehlt die Datei, bleibt der Text ohne Angabe. Die Adresse
    (href) bleibt unverändert: pages.yml schreibt den Link auf das Datenpaket für den Branch deploy auf den Spiegel um
    (GitHub Pages, gleiche Datei aus demselben Lauf)."""
    seite = Path(ziel) / "index.html"
    html = seite.read_text(encoding="utf-8")

    def eintragen(m):
        datei = Path(ziel) / m["href"]
        if not datei.is_file():
            return m[0]
        return f'{m["kopf"]}{m["text"]} ({groesse_text(datei.stat().st_size)}){m["punkt"]}</span></a>'

    neu = KARTE_DOWNLOAD.sub(eintragen, html)
    if neu != html:
        seite.write_text(neu, encoding="utf-8")


def main(ziel=ROOT / "_site"):
    ziel = Path(ziel)
    shutil.rmtree(ziel, ignore_errors=True)
    shutil.copytree(ROOT / "site", ziel)
    (ziel / "og-image.jpg").unlink(missing_ok=True)       # Bonner Vorschaubild nicht ausliefern (zweiter Lauf)
    ohne_abgeschaltete_ordner(ziel)                       # Ratsassistent nur mit Freigabe
    exporte_kopieren(config.EXPORT, ziel / "data" / "export")   # ohne Audits und Stichproben (nur im Datenpaket)
    (ziel / "data" / "LICENSE-DATA.md").write_bytes(freigaben.datei(ROOT / "data" / "LICENSE-DATA.md"))
    if strukturdaten_web.an():                            # Strukturdaten nur mit Freigabe (Entscheidung 10.11.2026)
        strukturdaten_web.ausliefern(ziel / strukturdaten_web.ORT)
    (ziel / "data" / "geo").mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "data" / "geo").glob("*.geojson"):
        shutil.copy(f, ziel / "data" / "geo" / f.name)
    kacheln = ROOT / "_kacheln" / "kacheln"
    if (kacheln / "stand.json").exists():
        shutil.copytree(kacheln, ziel / "kacheln")
    seo.write(ziel)
    groessen_eintragen(ziel)
    print(f"Seite → {ziel}")


if __name__ == "__main__":
    main(*sys.argv[1:])
