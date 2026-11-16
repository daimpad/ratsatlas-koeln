"""Workflows und Technikseite: jede Datei, jeder Schritt und jede Quelle hat eine Erklärung; der Hauptlauf ist bis zur
Information der Stadt gesperrt, veröffentlicht nie Testdaten und sichert den Abrufzustand gleich nach dem Abruf."""
import itertools
import os
import re
import shutil
import subprocess
import sys

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
    for gesperrt in ("RATSATLAS_ZEITFENSTER", "RATSATLAS_LIMIT", "RATSATLAS_MAX_OBJEKTE"):
        assert gesperrt not in text
    # Abstand: keine Repository-Variable, nur feste Werte im Abruf- und im Dokumentschritt (je ein eigener Prozess, ohne
    # Angabe gälte dort die Vorgabe von 2 s), nicht unter 20 s (Entscheidung 15.11.2026: vermutete Drosselung nach etwa
    # einer Minute mit 2 s Abstand)
    assert "vars.RATSATLAS_ABSTAND" not in text
    werte = re.findall(r'^\s+RATSATLAS_ABSTAND: "?([0-9.]+)"?$', text, re.M)
    assert len(werte) == 2 and all(float(w) >= 20 for w in werte)
    mit_abstand = [re.search(r"^\s+run: python -m pipeline (\S+)$", s, re.M)
                   for s in text.split("\n      - ") if re.search(r'^\s+RATSATLAS_ABSTAND: "?[0-9.]+"?$', s, re.M)]
    assert sorted(m.group(1) for m in mit_abstand if m) == ["dokumente", "fetch"] and all(mit_abstand)


def test_dokumentschritt_gesperrt_und_ohne_anhalten():
    """Der Dokumentschritt (Entscheidung 13.11.2026) bekommt genau die Freigaben, den Kontakt und die Obergrenze als
    Repository-Variablen, läuft nach dem Abruf (nicht nach einem roten Abrufschritt: kein eigenes `if`), hält die
    Veröffentlichung bei einem Fehler nicht an und hat ein eigenes Zeitlimit (Prüfung dok-f: länger als das Zeitfenster
    von 2 h plus einer Datei, kürzer als das des Jobs); der Kopf erklärt beide neuen Variablen."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritt = next(s for s in text.split("\n      - ") if "run: python -m pipeline dokumente" in s)
    variablen = set(re.findall(r"^\s+(RATSATLAS_\w+): \$\{\{ vars\.(\w+) \}\}$", schritt, re.M))
    assert variablen == {(v, v) for v in ("RATSATLAS_STADT_INFORMIERT", "RATSATLAS_KONTAKT", "RATSATLAS_PDF_FREIGEGEBEN",
                                          "RATSATLAS_PDF_MAX")}
    assert re.search(r"^\s+continue-on-error: true$", schritt, re.M) and not re.search(r"^\s+if:", schritt, re.M)
    limit = re.search(r"^\s+timeout-minutes: (\d+)$", schritt, re.M)
    job = re.search(r"^    timeout-minutes: (\d+)", text, re.M)
    assert limit and 125 <= int(limit.group(1)) < int(job.group(1))
    kopf = text.split("\nname:")[0]
    assert "RATSATLAS_PDF_FREIGEGEBEN" in kopf and "RATSATLAS_PDF_MAX" in kopf


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
    im Post-Schritt von actions/cache, der nur nach einem erfolgreichen Lauf speichert. Der Dokumentschritt folgt erst
    nach ihr und den beiden lesenden Schritten Fortschritt und Feldabdeckung (Prüfung dok-f: sonst hinge die Sicherung
    an seiner Dauer); nach ihm eine zweite Sicherung, nur mit seiner Freigabe, mit eigenem Schlüssel unter demselben
    Präfix (der nächste Lauf nimmt den jüngsten Stand). Reihenfolge: Abruf (i), Sicherung (i+1), Fortschritt (i+2),
    Feldabdeckung (i+3), Dokumente (i+4), zweite Sicherung (i+5)."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritte = text.split("\n      - ")
    i = next(k for k, s in enumerate(schritte) if "run: python -m pipeline fetch" in s)
    assert "id: abruf" in schritte[i]
    sichern = schritte[i + 1]
    assert re.search(r"^\s+if: always\(\)", sichern, re.M) and "steps.abruf.outcome" in sichern
    # danach der Fortschritt (test_fortschritt_gleich_nach_dem_sichern), die Feldabdeckung
    # (test_feldabdeckung_gleich_nach_dem_fortschritt), der Dokumentschritt (pipeline/dokumente.py) und die zweite
    # Sicherung seiner Ergebnisse und Zählungen
    assert "run: python tools/abrufstand.py" in schritte[i + 2]
    assert "run: python tools/feldabdeckung.py" in schritte[i + 3]
    assert "run: python -m pipeline dokumente" in schritte[i + 4] and "id: dokumente" in schritte[i + 4]
    zweite = schritte[i + 5]
    assert zweite.startswith("name: Abrufzustand nach den Dokumenten sichern")
    assert re.search(r"^\s+if: always\(\) && steps\.dokumente\.outcome != 'skipped' && "
                     r"vars\.RATSATLAS_STADT_INFORMIERT == 'ja' && vars\.RATSATLAS_PDF_FREIGEGEBEN == 'ja'$", zweite, re.M)
    assert "key: raw-${{ github.run_id }}-${{ github.run_attempt }}-dokumente" in zweite
    assert re.search(r"uses: actions/cache/save@([0-9a-f]{40})", zweite)
    save = re.search(r"uses: actions/cache/save@([0-9a-f]{40})", sichern)
    assert save, sichern
    # dieselbe festgenagelte Version wie die Wiederherstellung; kein actions/cache mit Speichern im Post-Schritt
    assert set(re.findall(r"uses: actions/cache(?:/restore|/save)?@([0-9a-f]{40})", text)) == {save.group(1)}
    assert "uses: actions/cache@" not in text and "uses: actions/cache/restore@" in text
    wiederherstellen = next(s for s in schritte if "actions/cache/restore@" in s)
    for pfad in ("data/raw/", "data/export/abrufstatistik.tsv"):         # data/raw/: zustand_abruf.json, STAND.json
        assert pfad in sichern and pfad in wiederherstellen and pfad in zweite
    assert "key: raw-${{ github.run_id }}-${{ github.run_attempt }}" in sichern
    assert "restore-keys: raw-" in wiederherstellen
    assert config.ZUSTAND.parent == config.STAND.parent == config.RAW


WAECHTER = "name: Abrufzustand wiederhergestellt? (Wächter vor Abruf und Veröffentlichung)"
# Die einzigen Schritte nach dem Wächter, die auch nach einem Fehler laufen, ohne an einem übersprungenen Schritt zu
# hängen: sie lesen nur (Skript → Name des Schritts)
LESEND = {"tools/abrufstand.py": "name: Fortschritt des Abrufs (Log und Zusammenfassung)",
          "tools/feldabdeckung.py": "name: Feldabdeckung der Rohdaten (nur Zahlen)"}
# Statusfunktionen in GitHub Actions (Namen ohne Rücksicht auf Groß- und Kleinschreibung): Steht eine davon im `if`,
# entfällt das stillschweigende success() davor, und der Schritt kann auch nach einem Fehler laufen, etwa mit
# `if: success() || true` (Prüfung stgf; vorher zählten nur always(), failure() und cancelled())
STATUSFUNKTION = re.compile(r"\b(?:always|success|failure|cancelled)\s*\(", re.I)


def _pages():
    return (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


def _schritte(text=None):
    return (_pages() if text is None else text).split("\n      - ")


def _skript(schritt):
    """Shell-Text eines Schritts mit `run: |` (ohne Einrückung): bis zur ersten Zeile, die weniger als zehn Zeichen
    eingerückt ist (etwa die Kommentare des nächsten Schritts) oder leer ist."""
    zeilen = []
    for z in schritt.split("        run: |\n", 1)[1].splitlines():
        if not z.strip() or len(z) - len(z.lstrip(" ")) < 10:
            break
        zeilen.append(z[10:])
    return "\n".join(zeilen) + "\n"


def _ohne_kommentare(schritt):
    """Zeilen eines Schritts ohne Kommentare und Leerzeilen (die Kommentare des folgenden Schritts stehen am Ende)."""
    return [z.strip() for z in schritt.splitlines() if z.strip() and not z.strip().startswith("#")]


def _lesende_form(schritt, skript):
    """Ein lesender Schritt (LESEND): genau die Schlüssel name, if (always()), continue-on-error (true), höchstens
    timeout-minutes und eine Zeile `run: python tools/….py` ohne Angaben; kein env, keine Ausdrücke (also weder
    secrets noch vars), kein uses, with, shell oder working-directory."""
    zeilen = _ohne_kommentare(schritt)
    assert zeilen[0] == LESEND[skript], zeilen
    schluessel = [re.match(r"([\w-]+): ", z) for z in zeilen]
    assert all(schluessel), zeilen   # jede Zeile ein Schlüssel: kein mehrzeiliges Skript, kein env-Block
    namen = [m.group(1) for m in schluessel]
    assert sorted(namen) in (sorted(["name", "if", "continue-on-error", "run"]),
                             sorted(["name", "if", "continue-on-error", "timeout-minutes", "run"])), namen
    assert "if: always()" in zeilen and "continue-on-error: true" in zeilen
    assert [z for z in zeilen if z.startswith("run:")] == [f"run: python {skript}"]
    assert not any(x in z for z in zeilen for x in ("${{", "secrets", "vars.", "env"))
    assert (config.ROOT / skript).exists()


# Schlüssel `if` in jeder Schreibweise (auch in Anführungszeichen, mit Leerzeichen vor dem Doppelpunkt, nach „- “, „{“,
# „,“ oder „? “) und die einzige Form, die die Prüfungen hier lesen: `if: <Wert>` auf einer Zeile
IF_SCHLUESSEL = re.compile(r"""(?:^|[\s{,?-])["']?if["']?\s*:""")
IF_FORM = re.compile(r"""^(\s*(?:- )?)if: ([^\s|>&*!'"#{\[%@`].*)$""")


def _if_befunde(text):
    """Stellen eines Workflows, an denen ein `if` anders steht, als test_waechter_vor_abruf_und_veroeffentlichung es
    mit `if: (.+)` je Zeile liest (Prüfung feldf, Mutation M8b): als Blockskalar (`if: >-`, `if: |`), mit dem Wert
    erst in der nächsten Zeile, über mehrere Zeilen fortgesetzt, in Anführungszeichen oder mit Leerzeichen vor dem
    Doppelpunkt, als Anker oder Verweis (`&name`, `*name`), dazu YAML-Formen, die Schritte anders gliedern, als der
    Text sie trennt (Schritt in Flussform, Spiegelstrich allein auf einer Zeile, Zusammenführen mit `<<:`, `? `
    als Schlüssel). Kommentarzeilen zählen nicht."""
    befunde = []
    zeilen = text.splitlines()
    for k, z in enumerate(zeilen):
        if not z.strip() or z.strip().startswith("#"):
            continue
        if (re.match(r"^\s*(?:- )?(?:[\w-]+\s*:\s+)?[&*][\w-]+(?:\s|$)", z) or re.search(r"<<\s*:", z)
                or re.match(r"^\s*\?(?:\s|$)", z) or re.match(r"^\s*-\s*(?:[{\[]|$)", z)
                or re.match(r"^\s*steps:\s*[{\[]", z)):
            befunde.append((k + 1, "YAML-Form, die die Schritte anders gliedert"))
        if not IF_SCHLUESSEL.search(z):
            continue
        form = IF_FORM.match(z)
        if not form:
            befunde.append((k + 1, "if nicht als `if: <Wert>` auf einer Zeile"))
            continue
        folgende = next((x for x in zeilen[k + 1:] if x.strip()), "")
        if len(folgende) - len(folgende.lstrip(" ")) > len(form.group(1)):
            befunde.append((k + 1, "if über mehrere Zeilen"))
    return befunde


def test_waechter_vor_abruf_und_veroeffentlichung():
    """Ein Wächter direkt nach dem Wiederherstellen und direkt vor dem Abruf hält den freigegebenen Lauf an, wenn der
    Zustand des Abrufs fehlt (etwa nach einer Störung von actions/cache, einem gelöschten Eintrag oder weil eine neue
    Fassung der Aktion die älteren Einträge nicht findet; Prüfung stapelf). Er hat weder `if` noch `continue-on-error`;
    jeder spätere Schritt, der auch nach einem Fehler liefe (jede Statusfunktion im `if`, STATUSFUNKTION: always(),
    failure(), cancelled() und success(), etwa `success() || true`), hängt an einem übersprungenen Schritt ohne eigenes
    `if` (Abruf, Dokumente) oder ist genau einer der beiden lesenden Schritte (Fortschritt, Feldabdeckung; LESEND, in
    lesender Form), und der Job deploy braucht einen erfolgreichen Job build, ohne Statusfunktion. Ein roter Wächter
    lässt also Abruf, Dokumente, beide Sicherungen und Veröffentlichung aus."""
    _waechter_pruefen(_pages())


def _waechter_pruefen(text):
    """Die Prüfungen von test_waechter_vor_abruf_und_veroeffentlichung auf dem Text eines Workflows (auch geändert,
    test_statusfunktion_laeuft_nach_fehler)."""
    schritte = _schritte(text)
    r = next(k for k, s in enumerate(schritte) if "uses: actions/cache/restore@" in s)
    assert re.search(r"^\s+id: rohdaten$", schritte[r], re.M)
    w = next(k for k, s in enumerate(schritte) if s.startswith(WAECHTER))
    f = next(k for k, s in enumerate(schritte) if "run: python -m pipeline fetch" in s)
    assert r + 1 == w and w + 1 == f
    waechter = schritte[w]
    assert not re.search(r"^\s+(if|continue-on-error):", waechter, re.M)
    variablen = dict(re.findall(r"^\s+(\w+): (\$\{\{ .+ \}\})$", waechter, re.M))
    assert variablen == {"GEFUNDEN": "${{ steps.rohdaten.outputs.cache-matched-key }}",
                         "RATSATLAS_STADT_INFORMIERT": "${{ vars.RATSATLAS_STADT_INFORMIERT }}",
                         "RATSATLAS_VOLLABRUF": "${{ vars.RATSATLAS_VOLLABRUF }}"}
    # dieselbe Datei, aus der der Abruf seinen Zustand liest: kein RATSATLAS_RAW im Wächter, im Abruf oder auf Ebene
    # des Workflows oder Jobs (nur die Kartenvorschau setzt es in ihrem eigenen Schritt), kein anderes
    # Arbeitsverzeichnis – also data/raw im Checkout
    assert "RATSATLAS_RAW" not in schritte[w] and "RATSATLAS_RAW" not in schritte[f]
    assert not re.search(r"^ {0,8}RATSATLAS_RAW:", text, re.M)
    assert "working-directory" not in text and not re.search(r"^\s*defaults:", text, re.M)
    assert f"[ -f {config.ZUSTAND.relative_to(config.ROOT).as_posix()} ]" in _skript(waechter)
    assert not _if_befunde(text)   # jedes `if` so, wie die Schleife unten es liest
    ids = {m.group(1): s for s in schritte[w + 1:] for m in [re.search(r"^\s+id: (\w+)$", s, re.M)] if m}
    lesend = []
    for s in schritte[w + 1:]:
        bedingung = re.search(r"(?:^|\n)\s*if: (.+)", s)   # auch ein Schritt, der mit „- if:“ beginnt
        if bedingung and STATUSFUNKTION.search(bedingung.group(1)):
            skript = re.search(r"^\s+run: python (tools/[\w.]+)", s, re.M)
            if skript and skript.group(1) in LESEND:
                # Fortschritt und Feldabdeckung: lesen nur, schreiben nichts nach data/, halten den Lauf nie an
                _lesende_form(s, skript.group(1))
                lesend.append(skript.group(1))
                continue
            haengt = re.findall(r"steps\.(\w+)\.outcome != 'skipped'", bedingung.group(1))
            assert any(i in ids and not re.search(r"^\s+if:", ids[i], re.M) for i in haengt), s.splitlines()[0]
    assert sorted(lesend) == sorted(LESEND)   # genau diese beiden, je einmal
    # der Dokumentschritt (ohne eigenes `if`, läuft nur nach Erfolg aller Schritte davor) und die beiden Sicherungen,
    # die auch nach einem Fehler laufen: an übersprungenem Abruf bzw. übersprungenen Dokumenten
    assert "dokumente" in ids and not re.search(r"^\s+if:", ids["dokumente"], re.M)
    haengen = {i for s in schritte[w + 1:] if "uses: actions/cache/save@" in s
               for i in re.findall(r"steps\.(\w+)\.outcome != 'skipped'", s)}
    assert haengen == {"abruf", "dokumente"}
    job = text.split("\n  deploy:\n")[1]
    assert re.search(r"^    needs: build$", job, re.M)
    assert not STATUSFUNKTION.search(job)


@pytest.mark.parametrize("bedingung", ["success() || true", "${{ success() || true }}", "Success() || true",
                                       "SUCCESS ( ) || vars.X == 'ja'", "always()", "Always()", "failure() || true",
                                       "!cancelled() && true"])
def test_statusfunktion_laeuft_nach_fehler(bedingung):
    """Jede Statusfunktion im `if` (auch success(), in jeder Groß- und Kleinschreibung) hebt das stillschweigende
    success() auf: Ein schreibender Schritt nach dem Wächter mit `if: success() || true` liefe nach einem roten
    Wächter und fällt auf (Prüfung stgf; vorher bestand er die Prüfung des Wächters), ebenso eine Statusfunktion im
    `if` des Jobs deploy. Ohne Statusfunktion (auch mit dem Text 'success' als Vergleichswert) bleibt es beim
    stillschweigenden success(): kein Befund."""
    text = _pages()
    _waechter_pruefen(text)
    stelle = "      - name: Kartenvorschau (leere Rohdaten in eigenem Verzeichnis)\n"
    assert text.count(stelle) == 1
    if not bedingung.startswith("!"):   # `if: !…` ist ein YAML-Tag, _if_befunde meldet es schon
        schritt = f"      - name: x\n        if: {bedingung}\n        run: python -m pipeline fetch\n"
        with pytest.raises(AssertionError, match="name: x"):
            _waechter_pruefen(text.replace(stelle, schritt + "\n" + stelle))
    kopf = "\n  deploy:\n    needs: build\n    if: needs.build.outputs.daten != ''\n"
    assert text.count(kopf) == 1
    with pytest.raises(AssertionError):
        _waechter_pruefen(text.replace(kopf, kopf.replace("daten != ''", f"daten != '' || {bedingung}")))
    for ohne in ("steps.daten.outputs.da == 'ja'", "steps.abruf.outcome == 'success'", "true"):
        _waechter_pruefen(text.replace(stelle, f"      - name: x\n        if: {ohne}\n        run: python -m pipeline "
                                               f"fetch\n\n" + stelle))


# Schritte, die nach „Gibt es Daten zum Veröffentlichen?“ eingefügt die Prüfung des Wächters umgingen, wenn ihr `if`
# nicht gelesen würde: jeder schreibt (Abruf) und liefe nach einem Fehler (Mutationen aus der Prüfung feldf)
UMGEHUNGEN = {
    "Blockskalar >-": "      - name: x\n        if: >-\n          always()\n        run: python -m pipeline fetch\n",
    "Blockskalar |": "      - name: x\n        if: |\n          always()\n        run: python -m pipeline fetch\n",
    "Wert in der nächsten Zeile": ("      - name: x\n        if:\n          always()\n"
                                   "        run: python -m pipeline fetch\n"),
    "fortgesetzt": ("      - name: x\n        if: steps.daten.outputs.da == 'ja' ||\n          always()\n"
                    "        run: python -m pipeline fetch\n"),
    "beginnt mit if": "      - if: >-\n          always()\n        run: python -m pipeline fetch\n",
    "Leerzeichen vor dem Doppelpunkt": ("      - name: x\n        if : always()\n"
                                        "        run: python -m pipeline fetch\n"),
    "Schlüssel in Anführungszeichen": ("      - name: x\n        \"if\": always()\n"
                                       "        run: python -m pipeline fetch\n"),
    "Wert in Anführungszeichen": "      - name: x\n        if: \"always()\"\n        run: python -m pipeline fetch\n",
    "Verweis": "      - name: x\n        if: *immer\n        run: python -m pipeline fetch\n",
    "Flussform": "      - {name: x, if: always(), run: python -m pipeline fetch}\n",
    "Spiegelstrich allein": "      -\n        name: x\n        if: always()\n        run: python -m pipeline fetch\n",
}


def test_if_nur_einzeilig_in_pages():
    """Jedes `if` in pages.yml steht als `if: <Wert>` auf einer Zeile, wie die Prüfung des Wächters es liest; jede
    andere Schreibweise eines nach einem Fehler laufenden, schreibenden Schritts nach dem Wächter fällt auf (vorher
    bestand ein Schritt mit `if: >-` und `always()` in der nächsten Zeile alle Tests, Mutation M8b)."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert not _if_befunde(text), _if_befunde(text)
    stelle = "      - name: Kartenvorschau (leere Rohdaten in eigenem Verzeichnis)\n"
    assert text.count(stelle) == 1
    for art, schritt in UMGEHUNGEN.items():
        assert _if_befunde(text.replace(stelle, schritt + "\n" + stelle)), art
    # unverändert lesbar: ein einzeiliges if mit Kommentar und ein Schritt, der mit `- if:` beginnt
    for schritt in ("      - name: x\n        if: always()   # Kommentar\n        run: python tools/abrufstand.py\n",
                    "      - if: always()\n        name: x\n        run: python tools/abrufstand.py\n"):
        assert not _if_befunde(text.replace(stelle, schritt + "\n" + stelle)), schritt


def test_if_wie_yaml_es_liest():
    """Gegenprobe, wo PyYAML installiert ist (nicht in requirements.txt, also nicht in GitHub Actions): Die Schritte,
    wie die Tests hier sie aus dem Text trennen, und ihr `if` stimmen mit dem überein, was YAML liest."""
    yaml = pytest.importorskip("yaml")
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    jobs = yaml.safe_load(text)["jobs"]
    gelesen = [schritt.get("if") for job in jobs.values() for schritt in job["steps"]]
    getrennt = []
    for s in _schritte()[1:]:
        # nur die Zeilen des Schritts: bis zur ersten Zeile außer Kommentaren, die weniger als acht Zeichen eingerückt
        # ist (etwa der nächste Job mit eigenem `if`)
        eigene = s.split("\n")[:1] + list(itertools.takewhile(
            lambda z: not z.strip() or z.lstrip().startswith("#") or len(z) - len(z.lstrip(" ")) >= 8,
            s.split("\n")[1:]))
        bedingung = re.search(r"(?:^|\n)\s*if: (.+)", "\n".join(eigene))
        getrennt.append(bedingung.group(1).strip() if bedingung else None)
    assert getrennt == gelesen


@pytest.mark.parametrize("informiert", ["ja", "", "Ja", " ja", "nein"])
def test_waechter_haelt_freigegebenen_lauf_ohne_zustand_an(tmp_path, monkeypatch, informiert):
    """Der Shell-Text des Wächters läuft hier wie in GitHub Actions (bash -e Datei) in einem Arbeitsverzeichnis
    ohne Netz. Er hält genau dann an (Exit-Code 1, ::error:: mit Abhilfe), wenn der Abruf freigegeben ist (dieselbe
    Regel wie abruf.freigegeben für die Kölner Adresse), zustand_abruf.json fehlt und RATSATLAS_VOLLABRUF nicht genau
    „ja“ ist; eine Fundmeldung von actions/cache allein genügt nicht, eine fehlende allein hält nicht an (maßgeblich
    ist die Datei). Mit RATSATLAS_VOLLABRUF=ja läuft er mit Warnung weiter."""
    if not shutil.which("bash"):
        pytest.skip("bash fehlt")
    from pipeline import abruf
    monkeypatch.setenv("RATSATLAS_STADT_INFORMIERT", informiert)
    # die Kölner Adresse (im Workflow ohne RATSATLAS_OPARL_BODY); wird nur verglichen, nicht abgerufen
    freigegeben = abruf.freigegeben("https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
    skript = _skript(next(s for s in _schritte() if s.startswith(WAECHTER)))
    zustand = tmp_path / config.ZUSTAND.relative_to(config.ROOT)
    umgebung = {k: v for k, v in os.environ.items() if not k.startswith("RATSATLAS_") and k != "BASH_ENV"}

    datei = tmp_path / "waechter.sh"   # wie in GitHub Actions ohne `shell:`: bash -e {0}
    datei.write_text(skript, encoding="utf-8")

    def lauf(gefunden, vollabruf):
        return subprocess.run(["bash", "-e", str(datei)], cwd=tmp_path,
                              env={**umgebung, "GEFUNDEN": gefunden, "RATSATLAS_STADT_INFORMIERT": informiert,
                                   "RATSATLAS_VOLLABRUF": vollabruf},
                              capture_output=True, text=True, timeout=60)

    # kein Zwischenspeicher: nichts unter data/raw/
    for vollabruf in ("", "meetings", "papers,meetings,organizations", "Ja", "ja "):
        erg = lauf("", vollabruf)
        assert erg.returncode == (1 if freigegeben else 0), (vollabruf, erg.stdout, erg.stderr)
        assert erg.stdout.splitlines()[0] == "Zwischenspeicher: keiner wiederhergestellt"
        fehler = [z for z in erg.stdout.splitlines() if z.startswith("::error::")]
        assert len(fehler) == (1 if freigegeben else 0)
        if fehler:
            for teil in ("zustand_abruf.json", "Lauf wiederholen", "vorige Fassung", "7 Tage",
                         "RATSATLAS_VOLLABRUF=ja", "Zählung der Dokumente", "keine Dokumente"):
                assert teil in fehler[0]
    erg = lauf("", "ja")
    assert erg.returncode == 0, erg.stderr
    assert any(z.startswith("::warning::") for z in erg.stdout.splitlines()) == freigegeben
    assert "::error::" not in erg.stdout
    # Eintrag gefunden, aber ohne Zustand (etwa ein Stand aus einem Lauf ohne Abrufnacht): hält ebenso an
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "STAND.json").write_text("{}\n", encoding="utf-8")
    erg = lauf("raw-1-1", "")
    assert erg.returncode == (1 if freigegeben else 0) and erg.stdout.startswith("Zwischenspeicher: raw-1-1\n")
    # Zustand vorhanden: weiter ohne Meldung, auch ohne Fundmeldung der Aktion
    zustand.write_text("{}\n", encoding="utf-8")
    for gefunden in ("raw-1-1", ""):
        erg = lauf(gefunden, "")
        assert erg.returncode == 0 and "::" not in erg.stdout, (erg.stdout, erg.stderr)


def test_fortschritt_gleich_nach_dem_sichern(tmp_path):
    """Gleich nach dem Sichern des Abrufzustands, immer und ohne den Lauf anzuhalten: tools/abrufstand.py schreibt den
    Fortschritt ins Log und in die Zusammenfassung; ohne Variablen, Geheimnisse und Abruf. Der Abrufschritt bleibt, wie
    er ist (Variablen und Abstand prüft test_abhilfen_als_variablen_sicherungen_nicht)."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritte = text.split("\n      - ")
    i = next(k for k, s in enumerate(schritte) if "run: python -m pipeline fetch" in s)
    assert "uses: actions/cache/save@" in schritte[i + 1]
    fortschritt = schritte[i + 2]
    assert fortschritt.startswith("name: Fortschritt des Abrufs")
    assert re.search(r"^\s+if: always\(\)$", fortschritt, re.M)
    assert re.search(r"^\s+continue-on-error: true$", fortschritt, re.M)
    assert re.search(r"^\s+run: python tools/abrufstand\.py$", fortschritt, re.M)
    assert "env:" not in fortschritt and "${{" not in fortschritt and "pipeline fetch" not in fortschritt
    assert text.count("python tools/abrufstand.py") == 1 and (config.ROOT / "tools" / "abrufstand.py").exists()
    # wie im Lauf: ohne Dateien (erster Lauf ohne Zwischenspeicher) Exit-Code 0 und eine Zusammenfassung
    zusammenfassung = tmp_path / "summary.md"
    erg = subprocess.run([sys.executable, str(config.ROOT / "tools" / "abrufstand.py"), "--zustand",
                          str(tmp_path / "z.json"), "--stand", str(tmp_path / "s.json"), "--statistik",
                          str(tmp_path / "a.tsv")], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "GITHUB_STEP_SUMMARY": str(zusammenfassung)})
    assert erg.returncode == 0 and "Abrufstand" in erg.stdout and "::warning::" not in erg.stdout, erg
    assert zusammenfassung.read_text(encoding="utf-8").startswith("### Abrufstand")


def test_feldabdeckung_gleich_nach_dem_fortschritt(tmp_path):
    """Feldabdeckung der Rohdaten (Entscheidung 16.11.2026) direkt nach dem Fortschritt und vor dem Dokumentschritt,
    seiner Sicherung und der Entscheidung über die Veröffentlichung: immer, ohne den Lauf anzuhalten (continue-on-error,
    Zeitlimit 10 Minuten), ohne Variablen, Geheimnisse und Abruf; der Abruf, die Sicherungen, der Dokumentschritt und
    der Wächter bleiben, wie sie sind (die übrigen Tests hier). Wie im Lauf ohne Rohdaten: Exit-Code 0 und eine
    Zusammenfassung."""
    text = (config.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    schritte = text.split("\n      - ")
    i = next(k for k, s in enumerate(schritte) if "run: python -m pipeline fetch" in s)
    assert "uses: actions/cache/save@" in schritte[i + 1]
    assert schritte[i + 2].startswith(LESEND["tools/abrufstand.py"])
    feld = schritte[i + 3]
    assert feld.startswith(LESEND["tools/feldabdeckung.py"])
    _lesende_form(feld, "tools/feldabdeckung.py")
    assert "timeout-minutes: 10" in _ohne_kommentare(feld)
    assert "run: python -m pipeline dokumente" in schritte[i + 4] and "id: dokumente" in schritte[i + 4]
    assert schritte[i + 5].startswith("name: Abrufzustand nach den Dokumenten sichern")
    assert schritte[i + 6].startswith("name: Gibt es Daten zum Veröffentlichen?")
    assert text.count("python tools/feldabdeckung.py") == 1
    zusammenfassung = tmp_path / "summary.md"
    erg = subprocess.run([sys.executable, str(config.ROOT / "tools" / "feldabdeckung.py"), "--raw",
                          str(tmp_path / "raw")], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "GITHUB_STEP_SUMMARY": str(zusammenfassung)})
    assert erg.returncode == 0 and "Feldabdeckung der Rohdaten" in erg.stdout and "::warning::" not in erg.stdout, erg
    assert "papers.jsonl fehlt" in erg.stdout and not (tmp_path / "raw").exists()
    assert zusammenfassung.read_text(encoding="utf-8").startswith("### Feldabdeckung der Rohdaten")


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


# Erste Hauptversion je Aktion, die laut ihren Release Notes auf Node.js 24 läuft (gelesen am 16.11.2026):
# checkout v5.0.0 („Update actions checkout to use node 24“), setup-python v6.0.0 („Upgrade to node 24“), setup-node
# v5.0.0 („Upgrade action to use node24“), cache v5.0.0 („runs on the Node.js 24 runtime“), configure-pages v6.0.0
# („upgrade to node 24“), deploy-pages v5.0.0 („Update Node.js version to 24.x“); upload-pages-artifact ist
# zusammengesetzt und nutzt ab v5.0.0 upload-artifact v7 (Node.js 24 seit upload-artifact v6.0.0)
NODE24_AB = {"actions/checkout": 5, "actions/setup-python": 6, "actions/setup-node": 5, "actions/cache/restore": 5,
             "actions/cache/save": 5, "actions/configure-pages": 6, "actions/upload-pages-artifact": 5,
             "actions/deploy-pages": 5}


def test_aktionen_festgenagelt_und_auf_node24():
    """Jede Aktion der aktiven Workflows ist über den vollen Commit-Hash mit Versionskommentar festgenagelt (nie über
    einen Tag oder Branch) und steht in einer Hauptversion, die laut Release Notes auf Node.js 24 läuft (Umstellung
    16.11.2026, TECHNIK.md „Workflows“); eine neue Aktion fällt auf, damit ihre Laufzeit geprüft wird."""
    gesehen = set()
    for datei in sorted((config.ROOT / ".github" / "workflows").glob("*.yml")):
        for zeile in re.findall(r"^\s*(?:- )?uses: (.+)$", datei.read_text(encoding="utf-8"), re.M):
            m = re.fullmatch(r"([\w.-]+/[\w./-]+)@([0-9a-f]{40})  # v(\d+)\.\d+\.\d+", zeile)
            assert m, (datei.name, zeile)
            assert m.group(1) in NODE24_AB, (datei.name, m.group(1))
            assert int(m.group(3)) >= NODE24_AB[m.group(1)], (datei.name, zeile)
            gesehen.add(m.group(1))
    assert gesehen == set(NODE24_AB)
