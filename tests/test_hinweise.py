"""Phase 6 (ohne Abruf): Lizenz- und Datenschutzhinweise vollständig, innere Links der zusammengestellten Seite heil,
Audit-Protokolle im Datenpaket. Lauf über den lokalen Testserver (synthetische Daten)."""
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from pipeline import build, config, export, paket, seo, sessionnet

ROOT = Path(__file__).resolve().parents[1]


def _seite(tmp_path):
    site = tmp_path / "_site"
    shutil.copytree(ROOT / "site", site)
    shutil.copytree(config.EXPORT, site / "data" / "export")
    shutil.copy(ROOT / "data" / "LICENSE-DATA.md", site / "data" / "LICENSE-DATA.md")
    (site / "data" / "geo").mkdir(parents=True)
    for f in (ROOT / "data" / "geo").glob("*.geojson"):
        shutil.copy(f, site / "data" / "geo" / f.name)
    seo.write(site, "https://koeln.ratsatlas.de/")
    return site


def test_hinweise_links_und_paket(oparl, tmp_path):
    sessionnet.fetch_all()
    build.build()
    export.export()
    zip_pfad = paket.write()   # wie im Hauptlauf unter data/export (hier: temporäres Verzeichnis)
    site = _seite(tmp_path)

    # Namensnennung, Lizenzen, Impressum und Datenschutz auf jeder HTML-Seite (außer der Fehlerseite)
    for seite in sorted(site.rglob("*.html")):
        if seite.name == "404.html":
            continue
        html = re.sub(r"<!--.*?-->", "", seite.read_text(encoding="utf-8"), flags=re.S)   # sichtbarer Inhalt
        rel = seite.relative_to(site).as_posix()
        assert config.NAMENSNENNUNG in html, rel
        assert "LICENSE-DATA.md" in html, rel
        assert "datenschutz.html" in html and "impressum" in html.lower(), rel
        # „Bonn“ nur als Herkunft des Codes (Ratsatlas Bonn, Bonner Zusatzthemen) oder in der Anschrift des Verantwortlichen
        rest = html.replace("ratsatlas-bonn", "").replace("Ratsatlas Bonn", "").replace("aus Bonn", "").replace("53111 Bonn", "").replace("Bonner Zusatzthemen", "")
        assert "Bonn" not in rest, rel

    # Canonical der veröffentlichten Startseite auf die Hauptadresse, keine Karten abgeschalteter Zusatzthemen
    index = (site / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://koeln.ratsatlas.de/">' in index
    assert 'href="haushalt/"' not in index and 'href="thema/"' not in index

    # innere Links
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "linkpruefung.py"), str(site)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout

    # Datenpaket: Lizenzen, Audits, Stichprobe, Abrufstatistik; keine Rohdaten der Schnittstelle
    namen = zipfile.ZipFile(zip_pfad).namelist()
    for erwartet in ("LICENSE-DATA.md", "LIESMICH.txt", "audit_geokodierung.tsv", "audit_prozess.tsv", "audit_zeit.tsv",
                     "audit_themen.tsv", "stichprobe_geokodierung.tsv", "abrufstatistik.tsv"):
        assert any(n.endswith("/" + erwartet) for n in namen), erwartet
    assert not any("papers.jsonl" in n or n.endswith(".pdf") for n in namen)
