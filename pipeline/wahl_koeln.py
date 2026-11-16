"""Wahlbeteiligung der Ratswahl 2025 je Stadtteil (Köln): Datei der Stadt lesen, mit data/geo abgleichen, ablegen.

Entscheidungen: 27.10.2026 (Bonn: Wahlbeteiligung je Gebiet als Kennzahl der Kontextdaten, nie Ergebnisse der Parteien
je Gebiet) und 16.11.2026 (1) (Köln: eine Datei der Stadt, Lizenz vor dem Einschalten mit der Statistikstelle klären).
Die amtliche Wahlbeteiligung je Stadtteil ersetzt in Köln die Bonner Schätzung über Stimmbezirke
(`kontext.wahlbeteiligung`); angezeigt wird sie nur mit der Freigabe „wahlbeteiligung“ (config.ZUSATZTHEMEN,
`kontext.wahlbeteiligung_koeln`). TECHNIK.md, „Wahlbeteiligung je Stadtteil“.

Kein Abruf: Gelesen wird nur eine Datei, die jemand lokal abgelegt hat (Aufruf über tools/wahlbeteiligung.py). Aus ihr
nur Schlüssel und Name des Stadtteils, Wahlberechtigte und Wähler oder die Wahlbeteiligung in Prozent (Positivliste
`KOPF`); Spalten mit Stimmen für Parteien oder Personen werden nie gelesen. Formate:
- XLSX im Aufbau des Amts für Stadtentwicklung und Statistik: ein Block mit „Stadtteil“ in der ersten Spalte (Zeile
  mit den Überschriften), darunter „Schlüssel | Name | abs | % …“ und je Stadtteil eine Zeile mit dem Schlüssel
  („101“ …). Gemessen am 16.11.2026 an der Arbeitsmappe „Strukturdaten zur Kommunalwahl 2025“ (offenedaten-koeln.de;
  sie enthält keine Ergebnisse der Kommunalwahl 2025, Schlüssel und Namen der 86 Stadtteile gleich data/geo). Ob der
  Excel-Anhang zu KSN 17/2025 so aufgebaut ist, ist ungeprüft.
- Tabelle mit einer Kopfzeile (XLSX, CSV oder TSV), auch die Open-Data-CSV des votemanagers (`gebiet-nr`,
  `gebiet-name`, `A` Wahlberechtigte insgesamt, `B` Wähler laut Feldbeschreibung der Stadt Köln zur Kommunalwahl
  2020); ob es für 2025 eine solche Datei gibt, ist ungeprüft.
Geschrieben (data/kontext/wahl2025_stadtteile.tsv, Eintrag „wahl2025“ in data/kontext/STAND.json) wird nur mit einer
klaren Lizenz (`LIZENZEN`); ohne sie prüft das Werkzeug nur und schreibt nichts.
"""
import csv
import hashlib
import io
import json
import re
from pathlib import Path

from . import config, strukturdaten

SPALTEN = ("stadtteil_id", "stadtteil", "wahlberechtigte", "waehler", "beteiligung_prozent")
TSV = config.ROOT / "data" / "kontext" / "wahl2025_stadtteile.tsv"
STAND = config.ROOT / "data" / "kontext" / "STAND.json"
STAND_SCHLUESSEL = "wahl2025"
WAHLTAG = "2025-09-14"
# Klare Lizenzen (Auftrag 16.11.2026): nur diese erlauben das Schreiben; dl-de/by verlangt eine Namensnennung
LIZENZEN = {"dl-de/zero-2.0": "https://www.govdata.de/dl-de/zero-2-0",
            "dl-de/by-2.0": "https://www.govdata.de/dl-de/by-2-0"}

# Positivliste der Überschriften (verglichen nach _kopf); alles andere wird nicht gelesen
KOPF = {"wahlberechtigte": {"wahlberechtigte", "wahlberechtigte insgesamt"},
        "waehler": {"wähler", "wähler insgesamt", "wählerinnen und wähler", "wählende"},
        "beteiligung": {"wahlbeteiligung", "wahlbeteiligung in %", "wahlbeteiligung (%)"}}
EINHEIT = {"wahlberechtigte": "abs", "waehler": "abs", "beteiligung": "%"}   # Zeile unter den Überschriften (Amt)
SCHLUESSEL = {"schlüssel", "nr", "nr.", "nummer", "stadtteilnummer", "stadtteil-nr", "stadtteil-nr.", "stadtteil_id"}
NAME = {"name", "stadtteil", "stadtteilname"}
VOTEMANAGER = {"a": "wahlberechtigte", "b": "waehler"}   # nur zusammen mit `gebiet-nr` und `gebiet-name`
SUMMENZEILE = {"köln", "stadt köln", "insgesamt", "summe", "gesamt"}
# Prüfung der Wahl: Blattname und Titel (XLSX) bzw. Dateiname, `datum` und `wahl` (CSV) müssen „2025“ und „Rat“ oder
# „Kommunalwahl“ enthalten und dürfen keine andere Wahl nennen
WAHL_JA = re.compile(r"Rat|Kommunalwahl")
WAHL_NEIN = re.compile(r"Oberbürgermeist|Bezirksvertretung|Integrationsrat|Europa|Bundestag|Landtag|Stichwahl|"
                       r"Strukturdaten|2020|2024", re.I)


def _norm(wert):
    """Zelle vergleichbar machen: Kleinschreibung, Leerraum vereinheitlicht, keine Leerzeichen um „/“ und „-“."""
    s = str("" if wert is None else wert).replace(" ", " ").casefold().strip()
    s = re.sub(r"\s*([/-])\s*", r"\1", s)
    return re.sub(r"\s+", " ", s)


def _kopf(wert):
    """Überschrift ohne Gendersuffix („Wähler*innen“, „Wähler -/innen“ → „wähler“)."""
    return re.sub(r"(\*|:|/-?|-/)innen\b", "", _norm(wert))


def _zahl(wert, ort=""):
    """Zahl aus einer Zelle (Zahl oder Text mit Tausenderpunkt bzw. Dezimalkomma); leer oder „-“ → None."""
    if wert is None or isinstance(wert, bool):
        return None
    if isinstance(wert, (int, float)):
        return wert
    s = str(wert).strip().replace(" ", "").replace(" ", "")
    if s in ("", "-", "–", "."):
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        raise ValueError(f"{ort}: Zelle ist keine Zahl".lstrip(": ")) from None


def _ganz(wert, was, ort):
    z = _zahl(wert, f"{ort}: {was}")
    if z is None:
        raise ValueError(f"{ort}: {was} fehlt")
    if isinstance(z, float):
        if not z.is_integer():
            raise ValueError(f"{ort}: {was} nicht ganzzahlig – umgerechnete Werte (etwa die Kommunalwahl 2020 in "
                             "den Strukturdaten) sind keine Ergebnisse der Wahl")
        z = int(z)
    return z


# --- Lesen ----------------------------------------------------------------------------------------------------------

def _blaetter(pfad, blatt=None):
    """[(Blatt, Zeilen)]: XLSX je Blatt (gespeicherte Werte), CSV/TSV als ein Blatt mit dem Dateinamen."""
    pfad = Path(pfad)
    if pfad.suffix.lower() in (".xlsx", ".xlsm"):
        with strukturdaten.arbeitsmappe(pfad) as mappe:
            if blatt is not None and blatt not in mappe.sheetnames:
                raise ValueError(f"Blatt {blatt!r} nicht in der Datei (Blätter: {', '.join(mappe.sheetnames)})")
            return [(n, [tuple(z) for z in mappe[n].iter_rows(values_only=True)])
                    for n in ([blatt] if blatt is not None else mappe.sheetnames)]
    roh = pfad.read_bytes()
    try:
        text = roh.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = roh.decode("cp1252")
    erste = text.split("\n", 1)[0]
    trenner = "\t" if pfad.suffix.lower() == ".tsv" or erste.count("\t") > erste.count(";") else (
        ";" if erste.count(";") >= erste.count(",") else ",")
    return [(pfad.name, [tuple(z) for z in csv.reader(io.StringIO(text), delimiter=trenner)])]


def _metriken(kopf, einheiten=None):
    """{Feld: Spalte} für Wahlberechtigte, Wähler und Wahlbeteiligung aus der Überschriftenzeile; mit `einheiten`
    (Aufbau des Amts) nur Spalten mit der passenden Einheit. Mehrdeutig → Fehler."""
    out = {}
    for j, zelle in enumerate(kopf):
        k = _kopf(zelle)
        for feld, namen in KOPF.items():
            if k in namen and (einheiten is None or (j < len(einheiten) and einheiten[j] == EINHEIT[feld])):
                if feld in out:
                    raise ValueError(f"Spalte „{feld}“ mehrdeutig: {kopf[out[feld]]!r} und {zelle!r}")
                out[feld] = j
    return out


def _tabellen(blatt, zeilen):
    """Tabellen mit Stadtteilen in einem Blatt: [{format, kopfzeile, start, schluessel, name, felder}]."""
    out = []
    for i, z in enumerate(zeilen):
        zellen = [_norm(v) for v in z]
        if not zellen:
            continue
        if zellen[0] == "stadtteil" and i + 1 < len(zeilen) and [_norm(v) for v in zeilen[i + 1][:2]] == ["schlüssel", "name"]:
            einheiten = [_norm(v) for v in zeilen[i + 1]]
            out.append({"format": "amt", "kopfzeile": i, "start": i + 2, "schluessel": 0, "name": 1,
                        "felder": _metriken(z, einheiten)})
        elif "gebiet-nr" in zellen and "gebiet-name" in zellen:
            felder = {feld: zellen.index(k) for k, feld in VOTEMANAGER.items() if k in zellen}
            out.append({"format": "votemanager", "kopfzeile": i, "start": i + 1, "schluessel": zellen.index("gebiet-nr"),
                        "name": zellen.index("gebiet-name"), "felder": felder})
        elif any(_kopf(v) in KOPF["wahlberechtigte"] for v in z):
            s = next((j for j, v in enumerate(zellen) if v in SCHLUESSEL), None)
            n = next((j for j, v in enumerate(zellen) if v in NAME), None)
            if s is None and n is None:
                continue
            out.append({"format": "tabelle", "kopfzeile": i, "start": i + 1, "schluessel": s, "name": n,
                        "felder": _metriken(z)})
    return out


def _kennung(blatt, zeilen, tab):
    """Text für die Prüfung der Wahl: Blattname und Titel (erste Textzelle der ersten drei Zeilen) bzw. bei CSV der
    Dateiname mit `datum` und `wahl` der ersten Datenzeile."""
    teile = [blatt]
    if tab["format"] == "votemanager":
        kopf = [_norm(v) for v in zeilen[tab["kopfzeile"]]]
        erste = zeilen[tab["start"]] if tab["start"] < len(zeilen) else ()
        teile += [str(erste[kopf.index(k)]) for k in ("datum", "wahl") if k in kopf and kopf.index(k) < len(erste)]
    else:
        titel = next((str(v).strip() for z in zeilen[:3] for v in z if isinstance(v, str) and v.strip()), "")
        teile.append(titel)
    return " | ".join(t for t in teile if t)


def wahl_passt(kennung):
    return "2025" in kennung and bool(WAHL_JA.search(kennung)) and not WAHL_NEIN.search(kennung)


def _datenzeilen(zeilen, tab):
    """Zeilen der Tabelle bis zur ersten leeren Zeile (Amt: bis zur ersten Zeile ohne Schlüssel aus Ziffern);
    Summenzeilen („Köln“, „insgesamt“) entfallen. Nur Schlüssel, Name und die Felder der Positivliste."""
    out, summen = [], 0
    for z in zeilen[tab["start"]:]:
        zelle = lambda j: z[j] if j is not None and j < len(z) else None
        s, n = zelle(tab["schluessel"]), zelle(tab["name"])
        if tab["format"] == "amt" and not str(s or "").strip().isdigit():
            break
        if all(v is None or str(v).strip() == "" for v in z):
            break
        if _norm(n if n is not None else s) in SUMMENZEILE:   # Name „Köln“ o. Ä., auch mit Gemeindeschlüssel
            summen += 1
            continue
        out.append({"schluessel": None if s is None else str(s).strip(), "name": None if n is None else str(n).strip(),
                    **{feld: zelle(j) for feld, j in tab["felder"].items()}})
    return out, summen


def lesen(pfad, blatt=None, wahl_pruefen=True):
    """Die eine Tabelle der Ratswahl 2025 je Stadtteil in der Datei: {datei, sha256, format, blatt, kennung, spalten,
    zeilen, summenzeilen}. Fehler, wenn keine oder mehrere Tabellen passen (dann `blatt` angeben)."""
    pfad = Path(pfad)
    kandidaten, ohne_spalten, andere_wahl = [], [], []
    for name, zeilen in _blaetter(pfad, blatt):
        for tab in _tabellen(name, zeilen):
            kennung = _kennung(name, zeilen, tab)
            if "wahlberechtigte" not in tab["felder"] or not ({"waehler", "beteiligung"} & set(tab["felder"])):
                ohne_spalten.append(kennung)
            elif wahl_pruefen and not wahl_passt(kennung):
                andere_wahl.append(kennung)
            else:
                kandidaten.append((name, zeilen, tab, kennung))
    if not kandidaten:
        raise ValueError("keine Tabelle der Ratswahl 2025 je Stadtteil gefunden"
                         + (f"; ohne Spalten Wahlberechtigte und Wähler oder Wahlbeteiligung: {'; '.join(ohne_spalten)}"
                            if ohne_spalten else "")
                         + (f"; verworfen nach der Prüfung der Wahl: {'; '.join(andere_wahl)}" if andere_wahl else ""))
    if len(kandidaten) > 1:
        raise ValueError("mehrere Tabellen passen, Blatt angeben: " + "; ".join(k[3] for k in kandidaten))
    name, zeilen, tab, kennung = kandidaten[0]
    daten, summen = _datenzeilen(zeilen, tab)
    kopf = zeilen[tab["kopfzeile"]]
    return {"datei": pfad.name, "sha256": hashlib.sha256(pfad.read_bytes()).hexdigest(), "format": tab["format"],
            "blatt": name, "kennung": kennung, "wahl_geprueft": bool(wahl_pruefen),
            "spalten": {feld: str(kopf[j]).strip() for feld, j in sorted(tab["felder"].items())},
            "zeilen": daten, "summenzeilen": summen}


# --- Abgleich und Werte ---------------------------------------------------------------------------------------------

def gebiete(pfad=None):
    """{Stadtteil-Nummer: (Name, Stadtbezirk)} aus data/geo."""
    gj = json.loads(Path(pfad or config.ORTSTEILE).read_text(encoding="utf-8"))
    return {int(f["properties"]["ortsteil"]): (f["properties"]["ortsteil_bez"], f["properties"]["bezirk_bez"])
            for f in gj["features"]}


def _werte(z, ort):
    """(Wahlberechtigte, Wähler) einer Zeile; Wähler aus der Wahlbeteiligung, wenn die Datei keine Wähler nennt."""
    a = _ganz(z.get("wahlberechtigte"), "Wahlberechtigte", ort)
    if a <= 0:
        raise ValueError(f"{ort}: keine Wahlberechtigten")
    if z.get("waehler") is not None:
        w = _ganz(z["waehler"], "Wähler", ort)
    else:
        p = _zahl(z.get("beteiligung"), f"{ort}: Wahlbeteiligung")
        if p is None or not 0 <= p <= 100:
            raise ValueError(f"{ort}: Wahlbeteiligung fehlt oder liegt nicht zwischen 0 und 100")
        w = round(a * p / 100)   # abgeleitet; in STAND.json als „waehler_aus“ vermerkt
    if not 0 <= w <= a:
        raise ValueError(f"{ort}: mehr Wähler als Wahlberechtigte oder weniger als null")
    return a, w


def ableiten(gelesen, geb=None):
    """Zeilen je Stadtteil von data/geo (Nummer, Name aus data/geo, Wahlberechtigte, Wähler, Beteiligung in % mit einer
    Nachkommastelle), sortiert nach Nummer. Jeder der Stadtteile genau einmal, Schlüssel und Name wie in data/geo;
    sonst Fehler mit allen Abweichungen."""
    geb = gebiete() if geb is None else geb
    zeilen = gelesen["zeilen"]
    mit_schluessel = bool(zeilen) and all((z["schluessel"] or "").isdigit() for z in zeilen)
    nach_name = {_norm(n): i for i, (n, _) in geb.items()}
    gefunden, fehler = {}, []
    for z in zeilen:
        if mit_schluessel:
            i = int(z["schluessel"])
            if i not in geb:
                fehler.append(f"Schlüssel {z['schluessel']} ({z['name']}) nicht in data/geo")
                continue
            if z["name"] is not None and _norm(z["name"]) != _norm(geb[i][0]):
                fehler.append(f"Schlüssel {i}: Name „{z['name']}“, in data/geo „{geb[i][0]}“")
                continue
        else:
            i = nach_name.get(_norm(z["name"]))
            if i is None:
                fehler.append(f"Name „{z['name']}“ nicht in data/geo")
                continue
        if i in gefunden:
            fehler.append(f"Stadtteil {i} {geb[i][0]} doppelt")
            continue
        gefunden[i] = z
    fehlen = sorted(set(geb) - set(gefunden))
    if fehlen:
        fehler.append("ohne Zeile: " + ", ".join(f"{i} {geb[i][0]}" for i in fehlen))
    if fehler:
        raise ValueError("Abgleich mit data/geo: " + "; ".join(fehler))
    out = []
    for i in sorted(gefunden):
        a, w = _werte(gefunden[i], f"Stadtteil {i} {geb[i][0]}")
        out.append({"stadtteil_id": i, "stadtteil": geb[i][0], "wahlberechtigte": a, "waehler": w,
                    "beteiligung_prozent": round(100 * w / a, 1)})
    return out


def zusammenfassung(gelesen, zeilen):
    """Angaben für Ausgabe und STAND.json, ohne Werte einzelner Stadtteile."""
    a = sum(z["wahlberechtigte"] for z in zeilen)
    w = sum(z["waehler"] for z in zeilen)
    return {"datei": gelesen["datei"], "sha256": gelesen["sha256"], "format": gelesen["format"],
            "blatt": gelesen["blatt"], "kennung": gelesen["kennung"], "wahl_geprueft": gelesen["wahl_geprueft"],
            "spalten": gelesen["spalten"],
            "waehler_aus": "Wähler" if "waehler" in gelesen["spalten"] else "Wahlbeteiligung (Wähler abgeleitet)",
            "stadtteile": len(zeilen), "wahlberechtigte": a, "waehler": w,
            "beteiligung_prozent": round(100 * w / a, 1) if a else None,
            "ausserhalb_20_95": sum(1 for z in zeilen if not 20 <= z["beteiligung_prozent"] <= 95)}


# --- Schreiben (nur mit klarer Lizenz) ------------------------------------------------------------------------------

def lizenz_klar(lizenz, namensnennung=""):
    """Grund, warum nicht geschrieben werden darf, oder None."""
    if lizenz not in LIZENZEN:
        return (f"Lizenz {lizenz!r} nicht klar (erlaubt: {', '.join(LIZENZEN)}); Entscheidung 16.11.2026 (1): "
                "Lizenz vor dem Einschalten mit der Statistikstelle klären")
    if lizenz == "dl-de/by-2.0" and not (namensnennung or "").strip():
        return "dl-de/by-2.0 verlangt eine Namensnennung (--namensnennung)"
    return None


def schreiben(gelesen, zeilen, *, url, titel, lizenz, namensnennung, abgerufen, tsv=None, stand=None):
    """data/kontext/wahl2025_stadtteile.tsv (Spalten SPALTEN) und STAND.json „wahl2025“; nur mit klarer Lizenz."""
    grund = lizenz_klar(lizenz, namensnennung)
    if grund:
        raise ValueError(f"nichts geschrieben: {grund}")
    if not str(url).startswith("https://"):
        raise ValueError(f"Adresse der Quelle ohne https: {url!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(abgerufen)):
        raise ValueError(f"Abrufdatum nicht im Format JJJJ-MM-TT: {abgerufen!r}")
    tsv, stand = Path(tsv or TSV), Path(stand or STAND)
    tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(tsv, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=SPALTEN, delimiter="\t", lineterminator="\n", extrasaction="raise")
        wr.writeheader()
        wr.writerows(zeilen)
    alt = json.loads(stand.read_text(encoding="utf-8")) if stand.exists() else {}
    nennung = (namensnennung or "").strip()
    alt[STAND_SCHLUESSEL] = {"titel": titel, "url": url, "lizenz": f"{lizenz}, {nennung}" if nennung else lizenz,
                             "lizenz_url": LIZENZEN[lizenz], "stand": WAHLTAG, "abgerufen": abgerufen,
                             **zusammenfassung(gelesen, zeilen)}
    stand.write_text(json.dumps(alt, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return tsv, stand
