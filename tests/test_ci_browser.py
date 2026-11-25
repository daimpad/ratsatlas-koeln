"""Job „browser“ in .github/workflows/tests.yml (Entscheidungen 19.11.2026 (1) (G) und 24.11.2026 (2) (2) A): Seite
mit Testdaten im Browser, parallel zum Job „test“, mit festen Versionen von Playwright und axe-core und ohne Anfrage an
die Stadt; dazu die Syntaxprüfung aller Skripte im Job „test“ und tools/wcag_pruefen.js (Größe und Port aus der
Umgebung, Exit-Code bei Befund). Themenseiten (Entscheidung 24.11.2026 (3)): zweiter Bau mit tools/testdaten.py
--themen und dem Prüfschalter RATSATLAS_THEMEN_PRUEFUNG (nur in diesem Schritt), Server auf 127.0.0.1:8791 und
tests/browser/themen.js. Der Workflow wird ohne YAML-Bibliothek gelesen (PyYAML steht nicht in
requirements.txt, also nicht in GitHub Actions); wo PyYAML installiert ist, prüft ein Test die Auswertung gegen YAML.
Alle Daten sind erfunden; keine Anfragen nach außen."""
import json
import os
import re
import shutil
import subprocess

import pytest

from pipeline import abruf, config

ROOT = config.ROOT
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
BROWSER = ROOT / "tests" / "browser"
# nur großgeschriebene Namen: GitHub liest die Schlüssel unter env laut actionlint ohne Unterschied der Schreibweise
# (http_proxy neben HTTP_PROXY wäre doppelt); Python (urllib) liest beide Schreibweisen, curl ALL_PROXY
TOTER_PROXY = {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
               "NO_PROXY": "127.0.0.1,localhost"}
SEITE = "http://127.0.0.1:8790/"
KETTE = ["python tools/testdaten.py", "python -m pipeline build", "python -m pipeline export", "python -m pipeline kontext",
         "python -m pipeline ebenen", "python -m pipeline check", "python -m pipeline package",
         "python tools/seite_bauen.py _site", "python tools/linkpruefung.py _site"]
# zweiter Bau mit den Themenseiten (Entscheidung 24.11.2026 (3)): eigene Testdaten, eigener Ordner, eigener Port
SEITE_THEMEN = "http://127.0.0.1:8791/"
KETTE_THEMEN = ["python tools/testdaten.py --themen", *KETTE[1:7], "python tools/seite_bauen.py _site_themen",
                "python tools/linkpruefung.py _site_themen"]
WENN_SEITE = "${{ !cancelled() && steps.seite.outcome == 'success' }}"
WENN_CHROMIUM = "${{ !cancelled() && steps.chromium.outcome == 'success' }}"
WENN_THEMEN = "${{ !cancelled() && steps.themen_seite.outcome == 'success' }}"
GROESSEN = ["1440x900", "1024x768", "390x844", "320x256"]
SHA = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


# --- Workflow lesen (Schreibweise von tests.yml: Jobs mit 2, Job-Schlüssel mit 4, Schritte mit „      - “, deren
# Schlüssel mit 8 und env-Einträge mit 10 Leerzeichen; run als eine Zeile oder als Block „|“) -----------------------

def _wert(v):
    v = re.sub(r"\s+#.*$", "", v.strip())   # Kommentar am Zeilenende (nach Leerraum, wie YAML)
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def _jobs(text):
    teil = text.split("\njobs:\n", 1)[1]
    koepfe = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", teil, re.M))
    return {m.group(1): teil[m.end():koepfe[i + 1].start() if i + 1 < len(koepfe) else len(teil)]
            for i, m in enumerate(koepfe)}


def _job_schluessel(job):
    kopf = job.split("\n    steps:\n", 1)[0]
    return {m.group(1): _wert(m.group(2)) for m in re.finditer(r"^    ([\w-]+):[ \t]*(.*)$", kopf, re.M)}


def _schritte(job):
    teil = job.split("\n    steps:\n", 1)[1]
    schritte = []
    for roh in re.split(r"^      - ", teil, flags=re.M)[1:]:
        zeilen = ("        " + roh).split("\n")
        s, i = {}, 0
        while i < len(zeilen):
            z = zeilen[i]
            i += 1
            m = re.match(r"^        ([\w-]+):[ \t]*(.*)$", z)
            if not m:
                continue   # Kommentare und Leerzeilen zwischen den Schlüsseln, Kommentare vor dem nächsten Schritt
            schluessel, wert = m.group(1), m.group(2)
            if schluessel == "run" and wert.strip() == "|":
                block = []
                while i < len(zeilen) and (not zeilen[i].strip() or zeilen[i].startswith(" " * 10)):
                    block.append(zeilen[i][10:])
                    i += 1
                s["run"] = "\n".join(block).rstrip("\n")
            elif schluessel in ("env", "with") and not wert.strip():
                eintraege = {}
                while i < len(zeilen) and (re.match(r"^ {10}[\w-]+:", zeilen[i]) or zeilen[i].strip().startswith("#")):
                    if not zeilen[i].strip().startswith("#"):
                        k, v = zeilen[i].strip().split(":", 1)
                        eintraege[k] = _wert(v)
                    i += 1
                s[schluessel] = eintraege
            else:
                s[schluessel] = _wert(wert)
        schritte.append(s)
    return schritte


TEXT = WORKFLOW.read_text(encoding="utf-8")
JOBS = _jobs(TEXT)


def _job(name):
    assert name in JOBS, f"Job „{name}“ fehlt in tests.yml"
    return JOBS[name]


def _browser_schritte():
    return _schritte(_job("browser"))


def _schritt(name):
    treffer = [s for s in _browser_schritte() if s.get("name") == name]
    assert len(treffer) == 1, name
    return treffer[0]


def test_auswertung_wie_yaml():
    """Gegenprobe, wo PyYAML installiert ist: Jobs, Job-Schlüssel und Schritte (uses, name, id, if, env, with,
    working-directory, run) lesen die Tests hier so, wie YAML sie liest."""
    yaml = pytest.importorskip("yaml")
    gelesen = yaml.safe_load(TEXT)
    assert set(JOBS) == set(gelesen["jobs"])
    for name, job in gelesen["jobs"].items():
        kopf = _job_schluessel(JOBS[name])
        for k in ("runs-on", "timeout-minutes", "needs", "if"):
            assert (str(job[k]) if k in job else None) == kopf.get(k), (name, k)
        eigene = _schritte(JOBS[name])
        assert len(eigene) == len(job["steps"]), name
        for e, y in zip(eigene, job["steps"]):
            for k in ("uses", "name", "id", "if", "working-directory"):
                assert e.get(k) == y.get(k), (name, k, e.get(k), y.get(k))
            for k in ("env", "with"):
                assert e.get(k) == ({kk: str(v) for kk, v in y[k].items()} if k in y else None), (name, k)
            assert e.get("run") == (y["run"].rstrip("\n") if "run" in y else None), (name, e.get("name"))


def test_browser_job_bei_jedem_pull_request_und_push_auf_main_parallel():
    """24.11.2026 (2) (2) A: Der Job läuft bei jedem Pull Request (ohne Filter nach Pfaden oder Branches) und jedem
    Push auf main, parallel zum Job „test“ (kein needs, kein if), mit Zeitlimit von mindestens 30 Minuten."""
    kopf = TEXT.split("\njobs:\n", 1)[0]
    assert re.search(r"^on:\n  pull_request:\n  push:\n    branches: \[\"main\"\]\n", kopf, re.M), kopf
    assert not re.search(r"paths|paths-ignore|branches-ignore|types:", kopf)
    assert "test" in JOBS
    job = _job_schluessel(_job("browser"))
    assert "needs" not in job and "if" not in job, job
    assert job["runs-on"] == "ubuntu-latest"
    assert int(job["timeout-minutes"]) >= 30


def test_actions_mit_voller_sha_wie_in_pages_und_kacheln():
    """Jede Action in tests.yml ist über die volle SHA festgelegt; der Job „browser“ nutzt nur checkout, setup-python
    und setup-node, mit denselben SHAs wie pages.yml (checkout, setup-python) und kacheln.yml (setup-node)."""
    uses = [_wert(u) for u in re.findall(r"^\s+(?:- )?uses:\s*(.+)$", TEXT, re.M)]
    assert uses and all(SHA.match(u) for u in uses), uses
    andere = "".join((ROOT / ".github" / "workflows" / d).read_text(encoding="utf-8") for d in ("pages.yml", "kacheln.yml"))
    bekannt = {_wert(u) for u in re.findall(r"^\s+(?:- )?uses:\s*(.+)$", andere, re.M)}
    browser = [s["uses"] for s in _browser_schritte() if "uses" in s]
    assert {u.split("@")[0] for u in browser} == {"actions/checkout", "actions/setup-python", "actions/setup-node"}
    assert set(browser) <= bekannt, set(browser) - bekannt


def test_nur_leserechte_keine_geheimnisse_keine_freigaben():
    """permissions nur contents: read (oben, kein Job erweitert sie); keine Secrets, Repository-Variablen oder Token;
    im Job „browser“ keine Freigabe eines Abrufs (RATSATLAS_STADT_INFORMIERT, RATSATLAS_KONTAKT, …_ABRUF); von den
    Variablen RATSATLAS_* nur die Sperrdatei, RATSATLAS_BROWSER (Prüfbogen im Browser) und der Prüfschalter der
    Themenseiten (test_pruefschalter_themen_nur_im_zweiten_bau)."""
    assert re.findall(r"^\s*([\w-]+):\s*(read|write|none)\s*$", TEXT, re.M) == [("contents", "read")]
    assert re.search(r"^permissions:\n  contents: read\n", TEXT, re.M)
    for job in JOBS.values():
        assert "permissions" not in _job_schluessel(job)
    for verboten in ("secrets", "vars.", "GITHUB_TOKEN", "github.token"):
        assert verboten not in TEXT, verboten
    browser = _job("browser")
    assert set(re.findall(r"RATSATLAS_\w+", browser)) == {"RATSATLAS_SPERRE", "RATSATLAS_BROWSER", "RATSATLAS_THEMEN_PRUEFUNG"}
    assert not re.search(r"_ABRUF\b|PDF_FREIGEGEBEN|VOLLABRUF", browser)


def test_keine_adresse_der_stadt_und_kein_abruf():
    """tests.yml nennt keinen Server der Stadt und nicht den Spiegel; jede Adresse ist lokal (abruf.lokal); im Job
    „browser“ laufen nur Schritte der Pipeline ohne Netz, in der Reihenfolge der lokalen Kette (zweimal: Seite und
    Seite mit Themenseiten)."""
    klein = TEXT.lower()
    for host in ("stadt-koeln", "offenedaten-koeln", "buergerinfo", "ratsinformation", "github.io", "ratsatlas.de"):
        assert host not in klein, host
    adressen = re.findall(r"https?://[^\s\"'`)]+", TEXT)
    assert adressen and all(abruf.lokal(a) and not abruf.stadt(a) for a in adressen), adressen
    assert re.findall(r"python -m pipeline ([a-z0-9-]+)", TEXT) == ["build", "export", "kontext", "ebenen", "check", "package"] * 2


def test_ohne_netz_bei_pipeline_server_und_pruefungen():
    """Jeder Schritt, der Pipeline, Seite, Server oder Prüfungen startet, hat den toten Proxy (127.0.0.1:9, nur
    127.0.0.1 und localhost direkt) und RATSATLAS_SPERRE im Temp-Ordner des Läufers; ins Netz gehen nur die
    Installationsschritte, und sie stehen vor allen anderen."""
    schritte = _browser_schritte()
    install = re.compile(r"pip install|npm ci|playwright install")
    arbeit = re.compile(r"python|node |http\.server")
    erster_ohne_netz = None
    for i, s in enumerate(schritte):
        run = s.get("run", "")
        if "uses" in s or install.search(run):
            assert not arbeit.search(re.sub(r"pip install[^\n]*", "", run)), s
            assert erster_ohne_netz is None, f"Installation nach einem Schritt ohne Netz: {s}"
            assert not set(TOTER_PROXY) & set(s.get("env", {})), s
            continue
        assert arbeit.search(run), s
        erster_ohne_netz = i if erster_ohne_netz is None else erster_ohne_netz
        env = s.get("env", {})
        assert {k: env.get(k) for k in TOTER_PROXY} == TOTER_PROXY, s.get("name")
        assert not [k for k in env if k.lower().endswith("_proxy") and k not in TOTER_PROXY], s.get("name")
        assert re.fullmatch(r"\$\{\{ runner\.temp \}\}/[\w-]+", env.get("RATSATLAS_SPERRE", "")), s.get("name")
    assert erster_ohne_netz is not None


def test_env_ohne_doppelte_schluessel():
    """Unter env steht kein Schlüssel zweimal, auch nicht in anderer Schreibweise: GitHub unterscheidet sie laut
    actionlint nicht (actionlint 1.7.12 meldete die erste Fassung mit http_proxy neben HTTP_PROXY als doppelt)."""
    for name, job in JOBS.items():
        for s in _schritte(job):
            schluessel = [k.lower() for k in s.get("env", {})]
            assert len(schluessel) == len(set(schluessel)), (name, s.get("name"))
        roh = re.findall(r"^        env:\n((?: {10}.+\n)+)", job, re.M)
        for block in roh:
            namen = [z.split(":", 1)[0].strip().lower() for z in block.splitlines() if not z.strip().startswith("#")]
            assert len(namen) == len(set(namen)), (name, namen)


def test_kette_server_und_alle_pruefungen_aufgerufen():
    """Die Seite entsteht wie in der lokalen Kette (Testdaten, Pipeline, Seite, Linkprüfung), der Server lauscht nur
    auf 127.0.0.1:8790; jedes Skript unter tests/browser läuft (pruefbogen.js über tests/test_praezision.py, themen.js
    gegen den zweiten Bau auf 127.0.0.1:8791), die WCAG-Prüfung in den vier Größen. Jede Prüfung läuft, solange ihre
    Seite antwortet, auch nach dem Befund einer anderen."""
    bau = _schritt("Seite mit Testdaten bauen")["run"].splitlines()
    assert bau[0] == 'mkdir -p "$RATSATLAS_SPERRE"' and bau[1:] == KETTE
    server = _schritt("Seite unter 127.0.0.1:8790")
    assert server["id"] == "seite"
    assert re.search(r"^nohup python3 -m http\.server --bind 127\.0\.0\.1 8790 -d _site > \"\$RUNNER_TEMP/[\w.]+\" 2>&1 &$",
                     server["run"], re.M)
    assert f"--output /dev/null {SEITE}" in server["run"] and "exit 1" in server["run"]
    aufgerufen = set()
    for s in _browser_schritte():
        run = s.get("run", "")
        for skript in re.findall(r"node (tests/browser/\w+\.js) " + re.escape(SEITE), run):
            aufgerufen.add(skript)
        for skript in re.findall(r"node (tests/browser/\w+\.js) " + re.escape(SEITE_THEMEN), run):
            assert skript == "tests/browser/themen.js" and s["if"] == WENN_THEMEN, s["name"]
            aufgerufen.add(skript)
        if "node tests/browser" in run or "node tools/wcag_pruefen.js" in run or "python -m pytest" in run:
            assert s["if"] in (WENN_SEITE, WENN_CHROMIUM, WENN_THEMEN), s["name"]
            assert s["env"]["NODE_PATH"] == "${{ github.workspace }}/tests/browser/node_modules"
            assert s["env"]["AXE_PFAD"] == "${{ github.workspace }}/tests/browser/node_modules/axe-core/axe.min.js"
        if "python -m pytest" in run:
            assert s["env"]["RATSATLAS_BROWSER"] == "1"
            assert run == "python -m pytest -q tests/test_praezision.py -k test_pruefbogen_im_browser"
            aufgerufen.add("tests/browser/pruefbogen.js")
    assert aufgerufen == {f"tests/browser/{p.name}" for p in BROWSER.glob("*.js")}
    wcag = _schritt("WCAG-Prüfung in vier Größen")
    assert wcag["env"]["PORT"] == "8790"
    assert re.search(r"^for groesse in (.+); do$", wcag["run"], re.M).group(1).split() == GROESSEN
    assert ('BREITE="${groesse%x*}" HOEHE="${groesse#*x}" node tools/wcag_pruefen.js "$RUNNER_TEMP/wcag_$groesse.tsv" '
            '"$RUNNER_TEMP/tastatur_$groesse.txt" || fehler=1') in wcag["run"]
    assert wcag["run"].rstrip().endswith('exit "$fehler"')


PRUEFUNGEN = {"Gremien und Ämter im Browser": ("gremien", SEITE), "Navigation im Browser": ("navigation", SEITE),
              "Bedienung im Browser": ("bedienung", SEITE), "Themenseiten im Browser": ("themen", SEITE_THEMEN)}


def test_befund_laesst_den_job_scheitern():
    """Ein Befund lässt den Job scheitern (Nachprüfung 24.11.2026): kein continue-on-error (Job oder Schritt), die vier
    Browserprüfungen mit genau ihrem Aufruf (kein „|| true“ oder Ähnliches dahinter), im Job „browser“ kein „set +e“
    und als einziges „||“ das „|| fehler=1“ der WCAG-Schleife, die mit exit "$fehler" endet."""
    assert "continue-on-error" not in TEXT
    for name, job in JOBS.items():
        assert "continue-on-error" not in _job_schluessel(job), name
        for s in _schritte(job):
            assert "continue-on-error" not in s, (name, s.get("name"))
    for name, (skript, seite) in PRUEFUNGEN.items():
        assert _schritt(name)["run"] == f'node tests/browser/{skript}.js {seite} "$RUNNER_TEMP/{skript}.json"', name
    runs = [s.get("run", "") for s in _browser_schritte()]
    assert not [r for r in runs if re.search(r"set \+e|\|\|\s*(true|:)\b|;\s*true\s*$", r, re.M)]
    oder = [z.strip() for r in runs for z in r.splitlines() if "||" in z]
    assert len(oder) == 1 and oder[0].endswith('"$RUNNER_TEMP/tastatur_$groesse.txt" || fehler=1'), oder
    # Schritte ohne eigene shell laufen mit „shell: bash“ als bash -eo pipefail: ein Fehler in der Kette bricht ab
    assert re.search(r"^    defaults:\n      run:\n        shell: bash\n", _job("browser"), re.M)


def test_zweiter_bau_mit_themenseiten():
    """Entscheidung 24.11.2026 (3), Antwort 5 A zum Plan vom 25.11.2026: Die Freigabe der Themenseiten bleibt im
    Repository aus; geprüft werden sie in einem zweiten Bau mit Testdaten. Er steht nach allen Prüfungen des ersten
    Baus (dieser, die drei Browserprüfungen, die WCAG-Prüfung und der Prüfbogen bleiben ohne Themenseiten wie die
    veröffentlichte Seite), läuft, solange Chromium installiert ist, mit der lokalen Kette und --themen in den eigenen
    Ordner _site_themen; der Server lauscht nur auf 127.0.0.1:8791 und fragt die Themenseite ab; themen.js läuft, solange
    sie antwortet."""
    namen = [s.get("name") for s in _browser_schritte()]
    neu = ["Seite mit Themenseiten bauen (Testdaten)", "Seite mit Themenseiten unter 127.0.0.1:8791", "Themenseiten im Browser"]
    assert namen[-3:] == neu, namen[-3:]
    for frueher in ("Seite mit Testdaten bauen", *[n for n in PRUEFUNGEN if PRUEFUNGEN[n][1] == SEITE],
                    "WCAG-Prüfung in vier Größen", "Prüfbogen im Browser"):
        assert namen.index(frueher) < namen.index(neu[0]), frueher
    bau = _schritt(neu[0])
    assert bau["id"] == "themen_bau" and bau["if"] == WENN_CHROMIUM
    zeilen = bau["run"].splitlines()
    assert zeilen[0] == 'mkdir -p "$RATSATLAS_SPERRE"' and zeilen[1:] == KETTE_THEMEN
    erster = _schritt("Seite mit Testdaten bauen")
    assert "--themen" not in erster["run"] and "_site_themen" not in erster["run"] and "if" not in erster
    server = _schritt(neu[1])
    assert server["id"] == "themen_seite" and server["if"] == "${{ !cancelled() && steps.themen_bau.outcome == 'success' }}"
    assert re.search(r'^nohup python3 -m http\.server --bind 127\.0\.0\.1 8791 -d _site_themen > "\$RUNNER_TEMP/[\w.]+" 2>&1 &$',
                     server["run"], re.M)
    assert f"--output /dev/null {SEITE_THEMEN}thema/verkehr-und-mobilitaet/" in server["run"] and "exit 1" in server["run"]
    pruefung = _schritt(neu[2])
    assert pruefung["if"] == WENN_THEMEN
    assert "_site_themen/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_pruefschalter_themen_nur_im_zweiten_bau():
    """Der Prüfschalter RATSATLAS_THEMEN_PRUEFUNG umgeht die Freigabe der Themenseiten (pipeline/config.py; er wirkt nur
    mit Testdaten in STAND.json): In tests.yml steht er nur unter env des Schritts „Seite mit Themenseiten bauen
    (Testdaten)“ mit dem Wert „verkehr“, in keinem anderen Schritt (auch nicht im Job „test“) und in keinem anderen
    Workflow, aktiv oder inaktiv (pages.yml, live.yml, kacheln.yml, .github/workflows-inaktiv/)."""
    assert config.THEMEN_PRUEFUNG == "RATSATLAS_THEMEN_PRUEFUNG"
    gefunden = []
    for name, job in JOBS.items():
        for s in _schritte(job):
            if config.THEMEN_PRUEFUNG in s.get("env", {}) or config.THEMEN_PRUEFUNG in s.get("run", ""):
                gefunden.append((name, s.get("name"), s.get("env", {}).get(config.THEMEN_PRUEFUNG)))
    assert gefunden == [("browser", "Seite mit Themenseiten bauen (Testdaten)", "verkehr")], gefunden
    zeilen = [z for z in TEXT.splitlines() if config.THEMEN_PRUEFUNG in z and not z.strip().startswith("#")]
    assert zeilen == ["          RATSATLAS_THEMEN_PRUEFUNG: verkehr"], zeilen
    andere = [p for d in ("workflows", "workflows-inaktiv") for p in sorted((ROOT / ".github" / d).glob("*.y*ml"))
              if p != WORKFLOW]
    assert {p.name for p in andere} >= {"pages.yml", "live.yml", "kacheln.yml"}
    for p in andere:
        assert config.THEMEN_PRUEFUNG not in p.read_text(encoding="utf-8"), p.name


def test_abbruch_anderer_hosts_im_kontext():
    """Die Browserprüfungen brechen Anfragen an andere Hosts im Browserkontext ab (ctx.route), nicht nur in der Seite:
    page.route erfasst neue Fenster nicht, und --no-proxy-server gilt nicht für die Kontexte von Playwright (beides
    nachgestellt am 24.11.2026). Jeder newContext bekommt den Abbruch vor der ersten Seite, die Hilfsseite aus
    browser.newPage() über ihren Kontext; der Prüfbogen bricht im Kontext alles ab, was keine Datei ist."""
    for datei in ("gremien.js", "navigation.js", "bedienung.js", "themen.js"):
        text = (BROWSER / datei).read_text(encoding="utf-8")
        assert not re.search(r"page\.route\(\(u\) => !", text), datei
        kontexte = re.findall(r"const ctx = await browser\.newContext\([^\n]*\);\n\s*(.*)\n\s*const page = await ctx\.newPage\(\);",
                              text)
        assert kontexte and len(kontexte) == text.count("browser.newContext("), datei
        assert all(k.startswith("await ctx.route(") and k.endswith(", (r) => r.abort());") for k in kontexte), (datei, kontexte)
        for hilfe in re.findall(r"const hilfe = await browser\.newPage\(\);\n\s*(.*)", text):
            assert hilfe == "await hilfe.context().route(nichtLokal, (r) => r.abort());", datei
    for datei in ("gremien.js", "navigation.js", "themen.js"):
        text = (BROWSER / datei).read_text(encoding="utf-8")
        assert 'const nichtLokal = (u) => !["127.0.0.1", "localhost"].includes(u.hostname);' in text, datei
    assert "await ctx.route((u) => !u.href.startsWith(BASIS), (r) => r.abort());" in (BROWSER / "bedienung.js").read_text(encoding="utf-8")
    bogen = (BROWSER / "pruefbogen.js").read_text(encoding="utf-8")
    assert bogen.count(".route('**/*', (r) => {") == bogen.count("browser.newContext(") == 2
    assert "startsWith('file:')) return r.continue();" in bogen


def test_wechsel_der_breite_wartet_auf_die_seite():
    """tests/browser/gremien.js: Nach einem Wechsel der Breite warten die Prüfungen, bis die Seite ihn verarbeitet hat
    (Maße im Fenster, zwei Bilder: die Ereignisse „change“ der Media Queries laufen vor requestAnimationFrame), beim
    Wechsel der Darstellung auf den Neuaufbau, und lesen Fokus und Inhalt in einem Schritt. Vorher feste 300 ms und zwei
    getrennte Messungen; unter Last lief der Neuaufbau einmal zwischen beiden (BEDIENUNG.breiteFokus, Nachprüfung
    24.11.2026)."""
    text = (BROWSER / "gremien.js").read_text(encoding="utf-8")
    hilfe = re.search(r"\nconst groesseSetzen = async \(page, groesse\) => \{\n(.*?)\n\};\n", text, re.S).group(1)
    assert "await page.setViewportSize(groesse);" in hilfe
    assert "window.innerWidth === w && window.innerHeight === h" in hilfe
    assert "requestAnimationFrame(() => requestAnimationFrame(" in hilfe and "waitForTimeout" not in hilfe
    assert re.search(r"const fokusUndZustand = \(page\) => page\.evaluate\(`\(\{ f: \(\$\{FOKUS\}\)\(\), z: \(\$\{ZUSTAND\}\)\(\),", text)
    breite = re.search(r"\n  async breiteFokus\(.*?\n  \},\n", text, re.S).group(0)
    telefon = re.search(r"\n  async telefonbreite\(.*?\n  \},\n", text, re.S).group(0)
    wechsel = re.search(r"\n  // Wechsel der Breite: ohne Wahl folgt.*?\n  \}\n", text, re.S).group(0)
    for teil in (breite, telefon, wechsel):
        # vom ersten Wechsel der Breite bis zur Prüfung: nur groesseSetzen, keine feste Wartezeit
        ab = teil[teil.index("await groesseSetzen(s.page, "):teil.index("pruefen(profil, ")]
        assert "setViewportSize" not in ab and "waitForTimeout" not in ab, ab[:80]
    assert breite.count("await fokusUndZustand(s.page)") == 4 and "await fokus(" not in breite and "await zustand(" not in breite
    assert breite.count("await groesseSetzen(") == 4
    assert 'await warten(s.page, () => document.querySelector("#wer-body .org"));\n      const b4 = ' in breite
    assert 'await warten(s.page, () => document.querySelector("#wer-body #wer-liste"));\n      const b3 = ' in breite
    # geprüft wird wie bisher: Knoten, Überschrift im Detail, Eintrag der Liste, Optionsfeld „Schaubild“
    assert ('a4[0].text === "Schaubild" && a4[0].sichtbar && a4[1]') in breite and 'a3[0].tag === "summary"' in breite
    assert "({ z, f } = await fokusUndZustand(s.page));" in telefon


def test_playwright_und_axe_in_festen_versionen():
    """tests/browser/package.json nennt genaue Versionen (Playwright 1.63.0 wie die Arbeitsumgebung, axe-core 4.10.2);
    package-lock.json hält sie mit Prüfsumme und Quelle; der Job installiert mit npm ci ohne Installationsskripte und
    Chromium über die Playwright-Fassung aus dieser Installation; node_modules ist nicht versioniert."""
    paket = json.loads((BROWSER / "package.json").read_text(encoding="utf-8"))
    abh = {**paket.get("dependencies", {}), **paket.get("devDependencies", {})}
    assert abh == {"playwright": "1.63.0", "axe-core": "4.10.2"}
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in abh.values())
    assert paket.get("private") is True and "type" not in paket   # Skripte bleiben CommonJS
    sperre = json.loads((BROWSER / "package-lock.json").read_text(encoding="utf-8"))
    assert sperre["lockfileVersion"] >= 2 and sperre["packages"][""]["dependencies"] == paket["dependencies"]
    pakete = {k: v for k, v in sperre["packages"].items() if k}
    assert {k: v["version"] for k, v in pakete.items()} == {"node_modules/playwright": "1.63.0",
                                                             "node_modules/playwright-core": "1.63.0",
                                                             "node_modules/axe-core": "4.10.2"}
    for name, eintrag in pakete.items():
        assert eintrag["integrity"].startswith("sha512-"), name
        assert eintrag["resolved"].startswith("https://registry.npmjs.org/"), name
    npm = _schritt("Playwright und axe-core")
    assert npm["working-directory"] == "tests/browser"
    assert npm["run"].splitlines()[0] == "npm ci --ignore-scripts --no-audit --no-fund"
    chromium = _schritt("Chromium für Playwright")
    assert chromium["id"] == "chromium" and chromium["working-directory"] == "tests/browser"
    assert chromium["run"] == "./node_modules/.bin/playwright install --with-deps --only-shell chromium"
    assert "npm install" not in TEXT and "npx" not in TEXT
    assert "tests/browser/node_modules" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def _node():
    node = shutil.which("node")
    if not node or not shutil.which("bash"):
        pytest.skip("node oder bash fehlt")
    return node


def _syntax_schritt():
    treffer = [s for s in _schritte(_job("test")) if s.get("name") == "Syntax der Webseite"]
    assert len(treffer) == 1
    return treffer[0]["run"]


def test_syntaxpruefung_erfasst_alle_skripte(tmp_path):
    """Der Schritt „Syntax der Webseite“ im Job „test“ prüft jede .js-Datei unter site (mit Unterordnern),
    tests/browser und tools; ES-Module als Modul. Gegenprobe in einem eigenen Ordner: Ein Syntaxfehler in einem Modul
    mit export und in einem klassischen Skript lässt den Schritt scheitern (`node --check datei.js` allein meldet den im
    Modul in Node 22 nicht)."""
    _node()
    skript = tmp_path / "schritt.sh"
    skript.write_text(_syntax_schritt() + "\n", encoding="utf-8")
    r = subprocess.run(["bash", "-e", str(skript)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    erwartet = sorted(str(p.relative_to(ROOT)) for d in ("site", "tests/browser", "tools") for p in (ROOT / d).rglob("*.js")
                      if "node_modules" not in p.parts)
    assert sorted(r.stdout.split()) == erwartet
    assert {"site/gremien.js", "site/chat/ui.js", "site/strukturdaten/strukturdaten.js", "tests/browser/gremien.js",
            "tools/wcag_pruefen.js"} <= set(erwartet)
    for d in ("site/unter", "tests/browser", "tools"):
        (tmp_path / "probe" / d).mkdir(parents=True)
    probe = tmp_path / "probe"
    (probe / "site" / "klassisch.js").write_text("const a = 1;\n", encoding="utf-8")
    (probe / "site" / "unter" / "modul.js").write_text("import { a } from './b.js';\nexport const b = a;\n", encoding="utf-8")
    lauf = lambda: subprocess.run(["bash", "-e", str(skript)], cwd=probe, capture_output=True, text=True, timeout=60)
    assert lauf().returncode == 0
    for datei, fehler in (("site/unter/kaputt_modul.js", "export const x = ;\n"), ("tools/kaputt.js", "const x = ;\n")):
        (probe / datei).write_text(fehler, encoding="utf-8")
        assert lauf().returncode != 0, datei
        (probe / datei).unlink()


# --- tools/wcag_pruefen.js mit nachgebildetem Playwright ------------------------------------------------------------

PLAYWRIGHT_ATTRAPPE = r"""
const fs = require('fs');
const LOG = process.env.ATTRAPPE_LOG, ART = process.env.ATTRAPPE_ART || 'sauber';
const log = (x) => fs.appendFileSync(LOG, JSON.stringify(x) + '\n');
const seite = {
  route: async () => {}, addInitScript: async (f) => log(['init', String(f)]),
  goto: async (u) => { log(['goto', u]); return { status: () => 200 }; },
  waitForTimeout: async () => {}, addScriptTag: async () => {}, check: async () => {}, waitForSelector: async () => null,
  $: async () => null, click: async (s) => log(['click', s]), keyboard: { press: async () => {} },
  evaluate: async (f) => {
    const s = String(f);
    if (s.includes('axe.run')) return { violations: ART === 'axe' ? [{ id: 'probe', impact: 'serious', help: 'Probe', nodes: [{ target: ['#probe'] }] }] : [] };
    if (s.includes('nav-open')) return false;
    if (s.includes('activeElement')) return { ziel: ART === 'body' ? 'body' : 'button#probe „Probe“', body: ART === 'body', outline: ART !== 'ohne-rahmen' };
    throw new Error('unerwartet: ' + s.slice(0, 80));
  },
};
seite.route = async () => log(['seite-route']);
const kontext = { route: async () => log(['kontext-route']), newPage: async () => { log(['seite']); return seite; }, close: async () => {} };
module.exports = { chromium: { launch: async () => ({ newContext: async (o) => { log(['kontext', o.viewport]); return kontext; },
  newPage: async () => { throw new Error('Seite ohne eigenen Kontext'); }, close: async () => {} }) } };
"""


def _wcag(tmp_path, art="sauber", **umgebung):
    """wcag_pruefen.js in einem eigenen Ordner mit nachgebildetem Playwright (kein Browser, keine Anfrage)."""
    node = _node()
    ordner = tmp_path / art
    (ordner / "tools").mkdir(parents=True)
    (ordner / "node_modules" / "playwright").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "wcag_pruefen.js", ordner / "tools" / "wcag_pruefen.js")
    (ordner / "node_modules" / "playwright" / "index.js").write_text(PLAYWRIGHT_ATTRAPPE, encoding="utf-8")
    (ordner / "axe.min.js").write_text("// Attrappe\n", encoding="utf-8")
    log = ordner / "log.jsonl"
    env = {k: v for k, v in os.environ.items() if k not in ("PORT", "BREITE", "HOEHE", "NODE_PATH")}
    env.update({**TOTER_PROXY, "AXE_PFAD": str(ordner / "axe.min.js"), "ATTRAPPE_LOG": str(log), "ATTRAPPE_ART": art,
                **umgebung})
    r = subprocess.run([node, "tools/wcag_pruefen.js", str(ordner / "e.tsv"), str(ordner / "t.txt")], cwd=ordner, env=env,
                       capture_output=True, text=True, timeout=60)
    eintraege = [json.loads(z) for z in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return r, eintraege


def test_wcag_pruefen_vorgaben_ohne_umgebung(tmp_path):
    """Ohne PORT, BREITE und HOEHE wie bisher: http://127.0.0.1:8765/, 1400 × 900, kein Menü ☰, kein ausgeblendeter
    Hinweis; ohne Befund Exit-Code 0. Der Abbruch anderer Hosts steht im Kontext, vor der Seite (auch neue Fenster)."""
    r, log = _wcag(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert log[:3] == [["kontext", {"width": 1400, "height": 900}], ["kontext-route"], ["seite"]], log[:3]
    assert ["seite-route"] not in log
    zeile = [e[1] for e in log if e[0] == "goto"]
    assert zeile and all(u.startswith("http://127.0.0.1:8765/") for u in zeile)
    assert ["click", "#nav-burger"] not in log and not [e for e in log if e[0] == "init"]


@pytest.mark.parametrize("breite,hoehe,menue,hinweis", [(1440, 900, False, False), (1024, 768, False, False),
                                                       (390, 844, True, False), (320, 256, True, True)])
def test_wcag_pruefen_groesse_und_port_aus_der_umgebung(tmp_path, breite, hoehe, menue, hinweis):
    """PORT, BREITE und HOEHE aus der Umgebung; bis 900 px öffnet die Prüfung das Menü ☰ vor der Liste; unter 400 px
    Höhe blendet sie nur #testdaten-hinweis aus."""
    r, log = _wcag(tmp_path, PORT="8790", BREITE=str(breite), HOEHE=str(hoehe))
    assert r.returncode == 0, r.stdout + r.stderr
    assert ["kontext", {"width": breite, "height": hoehe}] in log
    assert all(e[1].startswith(SEITE) for e in log if e[0] == "goto")
    klicks = [e[1] for e in log if e[0] == "click"]
    liste = klicks.index('.toggle[data-panel="panel-list"]')
    assert (liste > 0 and klicks[liste - 1] == "#nav-burger") == menue, klicks
    init = [e[1] for e in log if e[0] == "init"]
    assert bool(init) == hinweis
    if hinweis:
        assert len(init) == 1 and "testdaten-hinweis" in init[0] and init[0].count("getElementById") == 1


@pytest.mark.parametrize("art", ["axe", "body", "ohne-rahmen"])
def test_wcag_pruefen_exit_code_bei_befund(tmp_path, art):
    """Exit-Code 1 bei einem Verstoß laut axe, bei Fokus auf body und bei einem Ziel ohne sichtbaren Fokus."""
    r, _ = _wcag(tmp_path, art)
    assert r.returncode == 1, r.stdout + r.stderr
    assert re.search(r"[1-9]\d* Befunde", r.stdout)


def test_wahl_beim_laden_wartet_auf_den_zustand():
    """tests/browser/gremien.js, BEDIENUNG.wahlBeimLaden: Der Klick auf „Ämter“ folgt auf die Anfrage nach
    gremien.json (init hat die Bedienung dann angemeldet), deren Antwort bis nach dem Klick zurückgehalten wird; keine
    feste Wartezeit vor dem Klick (vorher 200 ms, dazu 1,5 s Verzögerung der Antwort)."""
    text = (BROWSER / "gremien.js").read_text(encoding="utf-8")
    teil = re.search(r"\n  async wahlBeimLaden\(.*?\n  \},\n", text, re.S).group(0)
    vor_klick = teil.split('click("#tab-wer-aemter")')[0]
    assert "waitForTimeout" not in vor_klick and "setTimeout(ok, 1500)" not in teil
    assert "await freigabe;" in teil and teil.index('click("#tab-wer-aemter")') < teil.index("freigeben();")
    assert "anfragen === 1" in teil and 'beim === "Wird geladen …"' in teil
