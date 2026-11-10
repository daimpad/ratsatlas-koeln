"""Workflows und Technikseite: jede Datei, jeder Schritt und jede Quelle hat eine Erklärung; der Hauptlauf ist bis zur
Information der Stadt gesperrt, veröffentlicht nie Testdaten und sichert den Abrufzustand gleich nach dem Abruf."""
import re
import shutil
import subprocess

import pytest

from pipeline import config, technikseite


def test_erklaerungen_vollstaendig():
    wfs = technikseite.workflows()
    assert {w["datei"] for w in wfs} <= set(technikseite.WORKFLOW_TEXT)
    pages = next(w for w in wfs if w["datei"] == "pages.yml")
    assert pages["schritte"] and set(pages["schritte"]) <= set(technikseite.SCHRITTE)
    assert set(config.SOURCES) <= set(technikseite.QUELLEN)


def test_hauptlauf_gesperrt_und_ohne_testdaten():
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "RATSATLAS_STADT_INFORMIERT: ${{ vars.RATSATLAS_STADT_INFORMIERT }}" in text
    assert ".get(\"testdaten\")" in text and "python tools/testdaten.py" not in text


def test_abhilfen_als_variablen_sicherungen_nicht():
    """Die Abhilfen, die der Abruf in STAND.json und im Log nennt (RATSATLAS_VOLLABRUF, RATSATLAS_KUERZER_ANNEHMEN),
    lassen sich in GitHub Actions setzen (der Zustand liegt im Zwischenspeicher des Workflows, ein Lauf an anderer
    Stelle wirkt nicht); Abstand, Zeitfenster, Seitengröße und Grenzen je Nacht dagegen nicht (Generalprobe
    09.11.2026)."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritt = next(s for s in text.split("\n      - ") if "run: python -m pipeline fetch" in s)
    variablen = set(re.findall(r"^\s+(RATSATLAS_\w+): \$\{\{ vars\.(\w+) \}\}$", schritt, re.M))
    assert variablen == {(v, v) for v in ("RATSATLAS_STADT_INFORMIERT", "RATSATLAS_KONTAKT", "RATSATLAS_VOLLABRUF",
                                          "RATSATLAS_KUERZER_ANNEHMEN")}
    for gesperrt in ("RATSATLAS_ABSTAND", "RATSATLAS_ZEITFENSTER", "RATSATLAS_LIMIT", "RATSATLAS_MAX_OBJEKTE"):
        assert gesperrt not in text


def test_leere_abhilfe_variablen_ohne_wirkung(monkeypatch):
    """Nicht gesetzte Repository-Variablen kommen als leere Umgebungsvariablen an: kein Vollabruf, kein kürzerer Stand,
    kein Einstellungsfehler."""
    from pipeline import sessionnet
    monkeypatch.setattr(config, "KONTAKT", "kontakt@example.invalid")   # Pflicht vor Anfragen an die Stadt
    monkeypatch.setenv("RATSATLAS_VOLLABRUF", "")
    monkeypatch.setenv("RATSATLAS_KUERZER_ANNEHMEN", "")
    assert sessionnet._listen_aus("RATSATLAS_VOLLABRUF", alle=True) == set()
    assert sessionnet._listen_aus("RATSATLAS_KUERZER_ANNEHMEN") == set()
    sessionnet._einstellungen_pruefen()


def test_abrufzustand_gleich_nach_dem_abruf_gesichert():
    """Der Zustand mit der Zählung der Nächte mit möglicher Sperre (zustand_abruf.json), STAND.json und die
    Abrufstatistik werden direkt nach dem Abrufschritt mit actions/cache/save und `if: always()` gesichert, nicht erst
    im Post-Schritt von actions/cache, der nur nach einem erfolgreichen Lauf speichert."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritte = text.split("\n      - ")
    i = next(k for k, s in enumerate(schritte) if "run: python -m pipeline fetch" in s)
    assert "id: abruf" in schritte[i]
    sichern = schritte[i + 1]
    assert re.search(r"^\s+if: always\(\)", sichern, re.M) and "steps.abruf.outcome" in sichern
    save = re.search(r"uses: actions/cache/save@([0-9a-f]{40})", sichern)
    assert save, sichern
    # dieselbe festgenagelte Version wie die Wiederherstellung; kein actions/cache mit Speichern im Post-Schritt
    assert set(re.findall(r"uses: actions/cache(?:/restore|/save)?@([0-9a-f]{40})", text)) == {save.group(1)}
    assert "uses: actions/cache@" not in text and "uses: actions/cache/restore@" in text
    wiederherstellen = next(s for s in schritte if "actions/cache/restore@" in s)
    for pfad in ("data/raw/", "data/export/abrufstatistik.tsv"):         # data/raw/: zustand_abruf.json, STAND.json
        assert pfad in sichern and pfad in wiederherstellen
    assert "key: raw-${{ github.run_id }}-${{ github.run_attempt }}" in sichern
    assert "restore-keys: raw-" in wiederherstellen
    assert config.ZUSTAND.parent == config.STAND.parent == config.RAW


def test_technikseite_ohne_bonn(tmp_path):
    from pipeline.gebietsseiten import _page
    technikseite.write(tmp_path, "https://koeln.ratsatlas.de/", _page)
    html = (tmp_path / "technik" / "index.html").read_text(encoding="utf-8")
    assert "Bonn" not in html and "allris" not in html and "Ratsatlas Köln" in html


def _deploy_schritt():
    """Shell-Text des Schritts „Fertige Seite in den Branch deploy schreiben“ (ohne Einrückung)."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritt = next(s for s in text.split("\n      - ") if "name: Fertige Seite in den Branch deploy schreiben" in s)
    run = schritt.split("        run: |\n", 1)[1]
    return "\n".join(z[10:] for z in run.splitlines())


def test_deploy_ohne_dateien_ueber_95_mb(tmp_path):
    """GitHub nimmt höchstens 100 MB je Datei an (Generalprobe: audit_prozess.tsv 98,3 MB). Der Abschnitt des Schritts
    zwischen dem Entfernen des Datenpakets und der .htaccess läuft hier wie in GitHub Actions (bash -eo pipefail) auf
    einem Ordner _deploy ohne Netz: Dateien über 95 MB fallen mit Warnung (Pfad, Größe) heraus, kleinere und .git
    bleiben, der Schritt läuft weiter."""
    if not shutil.which("bash"):
        pytest.skip("bash fehlt")
    zeilen = _deploy_schritt().splitlines()
    a = next(i for i, z in enumerate(zeilen) if z.startswith("rm -f _deploy/data/export/ratsatlas-koeln-export.zip"))
    b = next(i for i, z in enumerate(zeilen) if z.startswith("cp deploy/htaccess"))
    assert a < b and "git push" in "\n".join(zeilen[b:])
    d = tmp_path / "_deploy"
    groesse = {"data/export/koeln/audit_prozess.tsv": 96_000_000, "data/export/koeln/grenze.tsv": 95_000_000,
               "data/export/ratsatlas-koeln-export.zip": 10, "index.html": 1_000_000,
               ".git/objects/pack/gross.pack": 96_000_000, "ordner mit leerzeichen/gross 2.json": 95_000_001}
    for pfad, n in groesse.items():
        (d / pfad).parent.mkdir(parents=True, exist_ok=True)
        with open(d / pfad, "wb") as f:   # spärlich: belegt kaum Platz
            f.truncate(n)
    skript = "\n".join(zeilen[a:b]) + "\necho weiter\n"

    def lauf():
        return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", skript], cwd=tmp_path,
                              capture_output=True, text=True, timeout=60)

    erg = lauf()
    assert erg.returncode == 0, erg.stderr
    assert erg.stdout.splitlines()[-1] == "weiter"
    hinweis = ("nicht im Branch deploy: GitHub nimmt höchstens 100 MB je Datei an; liegt im Datenpaket und auf dem "
               "Spiegel GitHub Pages")
    assert sorted(z for z in erg.stdout.splitlines() if z.startswith("::warning::")) == [
        f"::warning::data/export/koeln/audit_prozess.tsv (96,0 MB) {hinweis}",
        f"::warning::ordner mit leerzeichen/gross 2.json (95,0 MB) {hinweis}"]
    bleibt = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    assert bleibt == {"data/export/koeln/grenze.tsv", "index.html", ".git/objects/pack/gross.pack"}
    # ohne große Datei: keine Warnung, kein Abbruch
    erg = lauf()
    assert erg.returncode == 0 and erg.stdout == "weiter\n", (erg.stdout, erg.stderr)


def test_deploy_kopfkommentar_zur_historie():
    """Der Branch deploy hat eine Historie (flacher Klon, ein Commit je Lauf); der Kopf sagt nicht mehr „ohne Historie“."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "ohne Historie" not in text
    assert "git clone -q --depth 1 --branch deploy" in _deploy_schritt()
    kopf = " ".join(z.lstrip("# ") for z in text.splitlines()[:4])
    assert "flacher Klon, ein Commit je Lauf" in kopf and "git gc" in kopf
