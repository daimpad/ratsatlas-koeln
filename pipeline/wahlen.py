"""Kommunalwahl 2025 in Bonn: Abruf der Quelldateien (Phase 1, Schritt 1).

Phase 0 (wahlen/phase0/BERICHT.md): Die Ergebnisse der Stadt nach Stimmbezirk (votemanager, wahlen.bonn.de) und die
Flächen der Wahl- und Stimmbezirke 2025 (stadtplan.bonn.de) waren aus der Arbeitsumgebung nicht erreichbar, aus dem
täglichen Workflow dagegen ist stadtplan.bonn.de erreichbar. Der Schritt `wahlen-rohdaten` läuft deshalb im Workflow
`quellen.yml` (auf Knopfdruck) und legt die Dateien unverändert mit Abrufstand im Branch `quellen` ab
(Ordner wahlen2025/). Daraus entsteht nach Prüfung ein fester Ausschnitt in data/kontext/ (Entscheidung 27.10.2026:
Wahlbeteiligung je Ortsteil als Kennzahl der Kontextdaten, ohne Ergebnisse der Parteien je Gebiet).

Übergang (Entscheidung 27.10.2026, wahlen/PHASE1.md): `wahlen-ausschnitt` legt Wahlberechtigte und Wähler je Stimmbezirk
von IT.NRW und die Zuordnung zum Ortsteil über das Straßenverzeichnis 2020 in data/kontext/ ab.

Lizenz laut opendata.bonn.de: CC0 (Datensätze „Kommunalwahl und Integrationsratswahl 2025 Wahlergebnisse“ und
„Wahl- und Stimmbezirke“); die Stadtseite nennt dl-de/zero-2.0."""
import csv
import hashlib
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import config

VOTEMANAGER = "https://wahlen.bonn.de/wahlen/KW2025/05314000/praesentation/opendata.html"
FLAECHEN = {"wahlbezirke": "https://stadtplan.bonn.de/geojson?OD=4873",
            "stimmbezirke": "https://stadtplan.bonn.de/geojson?OD=4874"}
DATENSAETZE = ["https://opendata.bonn.de/dataset/c6a47ff2-f49c-455e-a7a0-455247539956",   # Wahlergebnisse
               "https://opendata.bonn.de/dataset/3af508a5-4016-4c8d-9828-c84f0630efa1"]   # Wahl- und Stimmbezirke
ENDUNGEN = (".csv", ".json", ".geojson", ".zip", ".xlsx")


def _laden(url, tries=4, pause=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read(), r.geturl(), r.headers.get("Content-Type", "")
        except Exception as err:   # Verbindungsabbrüche kommen vor
            last = err
            time.sleep(pause * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def _links(seite, basis):
    """Links auf Dateien (CSV, JSON, GeoJSON, ZIP, XLSX) in einer HTML-Seite, absolut."""
    out = []
    for href in re.findall(r'href="([^"]+)"', seite):
        u = urllib.parse.urljoin(basis, html.unescape(href))
        if urllib.parse.urlparse(u).path.lower().endswith(ENDUNGEN) or "geojson" in u.lower() or "download" in u.lower():
            out.append(u)
    return list(dict.fromkeys(out))


def _dateiname(url, typ):
    teil = urllib.parse.urlparse(url)
    name = Path(teil.path).name or "datei"
    if teil.query:
        name += "_" + re.sub(r"[^\w]+", "_", teil.query)
    if "." not in name:
        name += ".json" if "json" in typ else ".html" if "html" in typ else ".bin"
    return re.sub(r"[^\w.\-]+", "_", name)[:120]


def rohdaten(ziel=None):
    """Pipeline-Schritt `wahlen-rohdaten`: Quelldateien in ziel (Standard _quellen/wahlen2025) mit STAND.json."""
    ziel = Path(ziel or config.ROOT / "_quellen" / "wahlen2025")
    ziel.mkdir(parents=True, exist_ok=True)
    stand = {"abruf": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dateien": [], "fehler": []}

    def ablegen(url, inhalt, typ, rolle):
        name = _dateiname(url, typ)
        (ziel / name).write_bytes(inhalt)
        stand["dateien"].append({"rolle": rolle, "url": url, "datei": name, "bytes": len(inhalt), "typ": typ,
                                 "sha256": hashlib.sha256(inhalt).hexdigest()})

    for rolle, url in FLAECHEN.items():
        try:
            inhalt, echt, typ = _laden(url)
            ok = json.loads(inhalt).get("features")
            if not ok:
                raise RuntimeError("keine Flächen in der Antwort")
            ablegen(echt, inhalt, typ, rolle)
        except Exception as err:
            stand["fehler"].append({"url": url, "fehler": str(err)})
    # Seiten mit Links: votemanager (offene Daten) und die Datensätze auf opendata.bonn.de (Ressourcen)
    seiten = [(u, 0) for u in [VOTEMANAGER] + DATENSAETZE]
    gesehen = set()
    while seiten:
        url, tiefe = seiten.pop(0)
        if url in gesehen or len(gesehen) >= 60:
            continue
        gesehen.add(url)
        try:
            inhalt, echt, typ = _laden(url)
        except Exception as err:
            stand["fehler"].append({"url": url, "fehler": str(err)})
            continue
        if "html" in typ:
            ablegen(echt, inhalt, typ, "seite")
            if tiefe < 2:   # Startseiten und Ressourcen-Seiten des Katalogs; nicht weiter
                text = inhalt.decode("utf-8", "replace")
                ziele = _links(text, echt) + [urllib.parse.urljoin(echt, h)
                                               for h in re.findall(r'href="(/dataset/[^"]+/resource/[^"/]+)"', text)]
                seiten += [(u, tiefe + 1) for u in ziele if "wahl" in u.lower() or "/resource/" in u or "stadtplan" in u]
        else:
            ablegen(echt, inhalt, typ, "datei")
        time.sleep(1)
    (ziel / "STAND.json").write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(1 for d in stand["dateien"] if d["rolle"] != "seite")
    print(f"Wahlen 2025: {n} Dateien, {len(stand['fehler'])} Fehler → {ziel}")
    for f in stand["fehler"]:
        print("  Fehler:", f["url"], f["fehler"][:200])
    if not n:
        raise SystemExit("Wahlen 2025: keine Datei abrufbar")


# --- Ausschnitt als Übergang (Entscheidung 27.10.2026) ------------------------------------------------------------
# Solange wahlen.bonn.de und stadtplan.bonn.de nicht antworten: Wahlberechtigte und Wähler der Ratswahl nach
# Stimmbezirk aus der Datei von IT.NRW (dieselben amtlichen Ergebnisse wie bei der Stadt; Summen gleich Heft 3), die
# Zuordnung Stimmbezirk → Ortsteil über das Straßenverzeichnis zur Kommunalwahl 2020 der Stadt (CC0) und die
# Hausnummern (data/geo/hausnummern_bonn.json), gewichtet nach Adressen. Ohne Stimmen der Parteien. Aus dem
# Straßenverzeichnis werden nur Straße, Hausnummernbereich und Stimmbezirk gelesen (ab Spalte 19 stehen Namen und
# Telefonnummern von Wahlvorständen). Sobald die Dateien der Stadt vorliegen, werden Zahlen und Flächen 2025
# gegengeprüft und die Quelle getauscht (wahlen/PHASE1.md).
ITNRW = "https://www.wahlergebnisse.nrw/kommunalwahlen/2025/KW25_Stimmbezirke.csv"
STRASSEN_2020 = ("https://opendata.bonn.de/sites/default/files/"
                 "05314000%2013.09.2020%20Kommunalwahlen%20-%20Integrationsratswahl%20Strassen.csv")
GKZ_BONN = "314000"
STIMMBEZIRKE = config.ROOT / "data" / "kontext" / "wahl2025_stimmbezirke.tsv"
ZUORDNUNG = config.ROOT / "data" / "kontext" / "wahl2025_zuordnung.tsv"
WAHL_QUELLE = {
    "titel": "Kommunalwahl 2025, Ratswahl nach Stimmbezirken (amtliches Endergebnis, IT.NRW; Zuordnung zum Ortsteil "
             "über das Straßenverzeichnis zur Kommunalwahl 2020 der Stadt Bonn)",
    "url": "https://www.wahlergebnisse.nrw/kommunalwahlen/2025/",
    "lizenz": "amtliches Wahlergebnis (bei der Stadt Bonn CC0, derzeit nicht erreichbar; IT.NRW ohne Lizenzangabe); "
              "Straßenverzeichnis 2020 CC0",
    "stand": "2025-09-14",
    "uebergang": "Übergang, bis die Dateien der Stadt (wahlen.bonn.de, Flächen der Stimmbezirke 2025) wieder erreichbar sind",
}


def _norm_strasse(s):
    s = s.strip()
    s = re.sub(r"([Ss])tr\.(?=$|[ -])", r"\1traße", s)
    return s


def _nummer(x):
    m = re.match(r"(\d+)", x)
    return int(m.group(1)) if m else None


def zuordnung(strassen_csv, hausnummern):
    """{Stimmbezirk-Gruppe des Straßenverzeichnisses (z. B. „11“ oder „11/12“): {Ortsteil: Adressen}} und
    (zugeordnet, ohne Straße, ohne Nummer). Nur die Spalten Straße, Hausnummernbereich, gerade/ungerade, Stimmbezirk."""
    regeln = defaultdict(list)
    for r in list(csv.reader(io.StringIO(strassen_csv), delimiter=";"))[1:]:
        if len(r) < 9 or not r[0].strip():
            continue
        von = int(r[3]) if r[3].strip().isdigit() else None
        bis = int(r[5]) if r[5].strip().isdigit() else None
        regeln[_norm_strasse(r[0])].append((von, bis, r[7].strip(), r[8].strip()))
    out = defaultdict(lambda: defaultdict(int))
    treffer = ohne_str = ohne_nr = 0
    for strasse, ots in hausnummern.items():
        rg = regeln.get(strasse)
        for ot, nrs in ots.items():
            for x in nrs:
                if not rg:
                    ohne_str += 1
                    continue
                k, sb = _nummer(x), None
                for von, bis, gu, nr in rg:
                    if von is None and bis is None:
                        sb = nr
                        break
                    if k is None or not ((von or 0) <= k <= (bis or 10 ** 6)):
                        continue
                    if (gu == "ger." and k % 2) or (gu == "ung." and not k % 2):
                        continue
                    sb = nr
                    break
                if sb is None:
                    ohne_nr += 1
                    continue
                treffer += 1
                out[sb][ot] += 1
    return out, (treffer, ohne_str, ohne_nr)


def stimmbezirke(itnrw_csv):
    """Zeilen der Ratswahl in Bonn: Stimmbezirk, Art (Urne/Brief), Wahlbezirk, Wahlberechtigte (A), davon mit
    Sperrvermerk „W“ (A2), Wähler (B). Ohne Stimmen der Parteien."""
    rows = list(csv.reader(io.StringIO(itnrw_csv), delimiter=";"))
    codes = next(r for r in rows if r[:4] == ["KRS", "GKZ_Gemeinde", "Gemeindenname", "Nr"])
    ix = {c: i for i, c in enumerate(codes) if c}
    out = []
    for r in rows:
        if len(r) <= ix["B"] or r[ix["GKZ_Gemeinde"]] != GKZ_BONN:
            continue
        nr, art = r[ix["Nr"]].strip(), r[ix["Briefwahl"]].strip()
        out.append({"stimmbezirk": nr, "art": art, "wahlbezirk": int(nr.split()[0]) // 10,
                    "wahlberechtigte": int(r[ix["A"]] or 0), "sperrvermerk_w": int(r[ix["A2"]] or 0),
                    "waehler": int(r[ix["B"]] or 0)})
    return out


def ausschnitt():
    """Pipeline-Schritt `wahlen-ausschnitt` (einmalig, lokal): data/kontext/wahl2025_stimmbezirke.tsv und
    wahl2025_zuordnung.tsv, Vermerk in data/kontext/STAND.json."""
    sb = stimmbezirke(_laden(ITNRW)[0].decode("utf-8-sig"))
    urne = [r for r in sb if r["art"] == "Urne"]
    if len(urne) < 150 or not any(r["art"] == "Brief" for r in sb):
        raise SystemExit(f"Wahlen 2025: nur {len(urne)} Urnenstimmbezirke für Bonn – Datei unvollständig")
    hn = json.loads(config.HAUSNUMMERN.read_text(encoding="utf-8"))["strassen"]
    zu, (treffer, ohne_str, ohne_nr) = zuordnung(_laden(STRASSEN_2020)[0].decode("latin-1"), hn)
    nummern = {int(r["stimmbezirk"]) for r in urne}
    gruppen = {int(t) for g in zu for t in g.split("/")}
    if nummern - gruppen:
        raise SystemExit(f"Wahlen 2025: Stimmbezirke ohne Adressen im Straßenverzeichnis 2020: {sorted(nummern - gruppen)}")
    with open(STIMMBEZIRKE, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(sb[0]), delimiter="\t", lineterminator="\n")
        wr.writeheader()
        wr.writerows(sb)
    with open(ZUORDNUNG, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(["stimmbezirke", "ortsteil", "adressen"])
        for g in sorted(zu, key=lambda g: [int(t) for t in g.split("/")]):
            for ot, n in sorted(zu[g].items()):
                wr.writerow([g, ot, n])
    stand_path = config.ROOT / "data" / "kontext" / "STAND.json"
    stand = json.loads(stand_path.read_text()) if stand_path.exists() else {}
    stand["wahl2025"] = {**WAHL_QUELLE, "abgerufen": datetime.now(timezone.utc).date().isoformat(),
                         "stimmbezirke": len(urne), "briefwahlbezirke": len(sb) - len(urne),
                         "adressen_zugeordnet": treffer, "adressen_ohne_strasse": ohne_str, "adressen_ohne_nummer": ohne_nr}
    stand_path.write_text(json.dumps(stand, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    alle = treffer + ohne_str + ohne_nr
    print(f"Wahlen 2025: {len(urne)} Urnen- und {len(sb) - len(urne)} Briefwahlbezirke, "
          f"Wahlberechtigte {sum(r['wahlberechtigte'] for r in sb)}, Wähler {sum(r['waehler'] for r in sb)}; "
          f"Adressen zugeordnet {treffer} von {alle} ({100 * treffer / alle:.1f} %) → {STIMMBEZIRKE.name}, {ZUORDNUNG.name}")
