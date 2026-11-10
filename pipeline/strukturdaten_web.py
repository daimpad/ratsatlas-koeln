"""Strukturdaten auf der Seite und im Datenpaket (Phase 3, Datenseite) – nur mit Freigabe
`config.ZUSATZTHEMEN["strukturdaten"]` (Entscheidung des Auftraggebers vom 10.11.2026; Vorgabe aus). Ohne Freigabe
ändert dieses Modul weder Seite noch Datenpaket.

Die Seite liest ausschließlich den Datenvertrag „Strukturdaten“ (data/strukturdaten/, pipeline/strukturdaten.py). Für
die Auslieferung wird er nur mechanisch aufgeteilt, mit unveränderten Spalten und Zeilen (keine neuen Felder, keine
berechneten Werte), unter `data/strukturdaten/` der Seite (`ausliefern`):

- unverändert kopiert: indikatoren.tsv, meta.json, gesamtstadt.tsv, zuordnung.tsv, raum/<raumebene>.geojson;
- raumwerte/<raumebene>/<raum_id>.tsv (gesamtstadt, stadtbezirk, stadtteil): alle Zeilen von werte.tsv dieser Einheit,
  Kopf und Zeilen byte-gleich, Reihenfolge wie in werte.tsv (für das Kontext-Panel);
- karte/<raumebene>/<indikator_id>.tsv (stadtbezirk, stadtteil aus werte.tsv; quartier aus werte_quartier.tsv.gz): alle
  Zeilen eines relativen Indikators (typ in TYPEN_KARTE, auch die abgeleiteten) auf dieser Ebene, byte-gleich, in der
  Reihenfolge der Quelle (für die Flächenfarben);
- anzeige.json: nur Darstellung, keine Werte: Kernauswahl mit Themen und Reihenfolge aus pipeline/strukturdaten_kern.tsv,
  Liste der Indikatoren für die Flächenfarben, Wegweiser-Indikatoren für den Vergleich, Dateischema, Texte, Namen und
  Eltern der Stadtbezirke und Stadtteile aus raum/ (damit das Kontext-Panel keine Geometrie laden muss).

Ausgeliefert wird nur, wenn meta.json `veroeffentlichen` true ist (`veroeffentlichen`; auch für das Datenpaket und
kontext.json), sonst ValueError.

Ohne die Prüfprotokolle (audit_*.tsv) und zurueckgestellt.tsv: sie liegen nur im Datenpaket (`paketdateien`), dort
alle Dateien des Vertrags unverändert unter strukturdaten/, aber nicht die Aufteilung für die Seite.
"""
import csv
import gzip
import json
import re
from pathlib import Path

from . import config

FUNKTION = "strukturdaten"
ORT = "data/strukturdaten"   # Ort auf der Seite (relativ zur Wurzel der Seite)
KOPIEREN = ("indikatoren.tsv", "meta.json", "gesamtstadt.tsv", "zuordnung.tsv", "raum/stadtbezirk.geojson",
            "raum/stadtteil.geojson", "raum/quartier.geojson")
EBENEN_RAUMWERTE = ("gesamtstadt", "stadtbezirk", "stadtteil")
EBENEN_KARTE = ("stadtbezirk", "stadtteil", "quartier")
EBENEN_NAMEN = ("stadtbezirk", "stadtteil")   # Namen und Eltern in anzeige.json (raeume)
KARTE_VORGABE = "stadtteil"
TYPEN_KARTE = ("anteil", "quote", "dichte", "mittelwert")   # nie anzahl oder kategorie (Prompt 5.2)
KERN = Path(__file__).with_name("strukturdaten_kern.tsv")
KOPF_KERN = ["indikator_id", "thema_anzeige", "reihenfolge", "begruendung"]
KERN_ANZAHL = (15, 20)   # Kernauswahl im Panel (Entscheidung 10.11.2026: etwa 15–20)
# Gegenstücke im Wegweiser Kommune (Phase 0, explore/strukturdaten/wegweiser_vorschlag.tsv, zuordnung_art „direkt“):
# Kölner Indikator → Wegweiser-Indikator. Nur zum Nebeneinanderstellen; Definition und Stichtag können abweichen.
WW_GEGENSTUECK = {
    "koeln_A0355A": "ww_bevoelkerung",
    "koeln_A0022S": "ww_durchschnittsalter",
    "koeln_C0007P": "ww_sgb-ii-quote",
    "koeln_D0011P": "ww_beschaeftigungsquote",
    "koeln_A0002P": "ww_auslaenderanteil",
    "koeln_B0022S": "ww_wohnflaeche-pro-person",
}
# Namen der Vergleichskommunen wie in der Kommunenliste des Wegweisers (Feld name)
WW_NAMEN = {"bonn": "Bonn", "koeln": "Köln", "wuppertal": "Wuppertal"}
# Texte für die Anzeige (Prompt 5.1–5.3), sachlich und ohne Wertung
TEXTE = {
    "geheim": "nicht veröffentlicht (statistische Geheimhaltung)",
    "fehlt": "keine Angabe in der Quelle",
    # abgeleitete Anteile mit status fehlt: die Quelle hat Werte, der Anteil ist nur nicht bildbar
    "fehlt_abgeleitet": "kein Anteil berechenbar (ein Eingangswert fehlt in der Quelle oder die Bezugsgröße ist 0)",
    "abgeleitet": "vom Ratsatlas aus veröffentlichten Werten der Stadtstatistik berechnet (abgeleitet)",
    "einordnung": "Zur Einordnung, kein Urteil über das Gebiet.",
    "fehlschluss": "Dass Vorlagen und Strukturmerkmale im selben Gebiet vorkommen, belegt keinen Zusammenhang.",
    "vergleich": ("Gesamtstädtische Werte aus dem Wegweiser Kommune und Werte der Kölner Stadtstatistik können sich in "
                  "Definition und Stichtag unterscheiden; sie werden nicht miteinander verrechnet."),
    "raumebenen": ("Werte stehen je Raumebene so, wie die Stadt sie veröffentlicht; der Ratsatlas rechnet sie nicht "
                   "von einer Raumebene auf eine andere um."),
}
_DATEINAME = re.compile(r"[A-Za-z0-9_-]+")


def an():
    """Freigabe der Strukturdaten auf Seite und im Datenpaket."""
    return bool(config.ZUSATZTHEMEN.get(FUNKTION))


def veroeffentlichen(meta, wo="meta.json"):
    """Vertragsfeld `veroeffentlichen` (meta.json, „Datenstand und Freigabe“): Seite, Datenpaket und kontext.json
    liefern Strukturdaten nur aus, wenn es true ist; sonst ValueError (Freigabe „strukturdaten“ und Vertrag passen nicht
    zusammen, lieber kein Lauf als eine Veröffentlichung gegen den Vertrag)."""
    if meta.get("veroeffentlichen") is not True:
        raise ValueError(f"{wo}: veroeffentlichen ist nicht true – Strukturdaten werden nicht ausgeliefert "
                         "(Freigabe „strukturdaten“ zurücknehmen oder den Datenvertrag prüfen)")


def _meta(src):
    """meta.json des Vertrags in `src`, geprüft mit veroeffentlichen()."""
    pfad = Path(src) / "meta.json"
    meta = json.loads(pfad.read_text(encoding="utf-8"))
    veroeffentlichen(meta, pfad)
    return meta


def quelle():
    """Ordner des Datenvertrags (data/strukturdaten/, überschreibbar mit STRUKTURDATEN_AUS wie im Generator)."""
    from . import strukturdaten
    return strukturdaten.ausgabe()


def _tsv(pfad):
    with open(pfad, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def _lesen(pfad):
    """(Kopfzeile, [Zeilen]) von werte.tsv oder werte_quartier.tsv.gz als unveränderter Text (mit Zeilenende); Kopf wie
    KOPF_WERTE, jede Zeile mit genau so vielen Feldern."""
    from .strukturdaten import KOPF_WERTE
    oeffnen = gzip.open if pfad.suffix == ".gz" else open
    with oeffnen(pfad, "rt", encoding="utf-8", newline="") as fh:
        kopf = fh.readline()
        if kopf != "\t".join(KOPF_WERTE) + "\n":
            raise ValueError(f"{pfad.name}: unerwarteter Kopf {kopf!r}")
        zeilen = []
        for zeile in fh:
            if not zeile.endswith("\n") or zeile.count("\t") != len(KOPF_WERTE) - 1:
                raise ValueError(f"{pfad.name}: unerwartete Zeile {zeile!r}")
            zeilen.append(zeile)
    return kopf, zeilen


def _name(teil, art):
    if not _DATEINAME.fullmatch(teil):
        raise ValueError(f"{art} {teil!r} taugt nicht als Dateiname")
    return teil


def kern(pfad=None, indikatoren=None):
    """Kernauswahl aus pipeline/strukturdaten_kern.tsv, nach reihenfolge: [{indikator_id, thema_anzeige, reihenfolge,
    begruendung}]. Prüft Kopf, Anzahl (KERN_ANZAHL), eindeutige Kennungen und Reihenfolge, Begründung je Zeile und –
    mit `indikatoren` (Kennungen aus indikatoren.tsv) – dass jede Kennung im Vertrag steht; sonst ValueError."""
    pfad = Path(pfad or KERN)
    with open(pfad, encoding="utf-8", newline="") as fh:
        leser = csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        if leser.fieldnames != KOPF_KERN:
            raise ValueError(f"{pfad.name}: Kopf {leser.fieldnames}, erwartet {KOPF_KERN}")
        zeilen = list(leser)
    if not KERN_ANZAHL[0] <= len(zeilen) <= KERN_ANZAHL[1]:
        raise ValueError(f"{pfad.name}: {len(zeilen)} Indikatoren, erwartet {KERN_ANZAHL[0]} bis {KERN_ANZAHL[1]}")
    for z in zeilen:
        if not z["reihenfolge"].isdigit() or not all((z[k] or "").strip() for k in KOPF_KERN):
            raise ValueError(f"{pfad.name}: unvollständige Zeile {z}")
        z["reihenfolge"] = int(z["reihenfolge"])
    for k in ("indikator_id", "reihenfolge"):
        werte = [z[k] for z in zeilen]
        if len(set(werte)) != len(werte):
            raise ValueError(f"{pfad.name}: {k} doppelt")
    if indikatoren is not None:
        fehlen = [z["indikator_id"] for z in zeilen if z["indikator_id"] not in indikatoren]
        if fehlen:
            raise ValueError(f"{pfad.name}: Kennungen nicht in indikatoren.tsv: {fehlen}")
    return sorted(zeilen, key=lambda z: z["reihenfolge"])


def raeume(src):
    """Namen und Eltern der Stadtbezirke und Stadtteile aus raum/<raumebene>.geojson (Properties raum_id, name,
    eltern_id unverändert), für das Kontext-Panel ohne Geometrie: {Ebene: [[raum_id, name, eltern_id]]}."""
    aus = {}
    for ebene in EBENEN_NAMEN:
        geo = json.loads((Path(src) / "raum" / f"{ebene}.geojson").read_text(encoding="utf-8"))
        aus[ebene] = sorted(([str(f["properties"]["raum_id"]), f["properties"]["name"],
                              str(f["properties"].get("eltern_id") or "")] for f in geo["features"]),
                            key=lambda z: int(z[0]))
    return aus


def anzeige(indikatoren, raumwerte, karte, meta, kern_zeilen, namen=None):
    """Inhalt von anzeige.json (nur Darstellung): `indikatoren` Zeilen aus indikatoren.tsv, `raumwerte` {Ebene: [raum_id]},
    `karte` {Ebene: [indikator_id]} der geschriebenen Dateien, `meta` aus meta.json, `kern_zeilen` aus kern(), `namen`
    aus raeume()."""
    from . import strukturdaten
    ind = {i["indikator_id"]: i for i in indikatoren}
    themen = []
    for z in kern_zeilen:
        if not themen or themen[-1]["thema"] != z["thema_anzeige"]:
            if any(t["thema"] == z["thema_anzeige"] for t in themen):
                raise ValueError(f"Kernauswahl: Thema {z['thema_anzeige']!r} nicht zusammenhängend")
            themen.append({"thema": z["thema_anzeige"], "indikatoren": []})
        themen[-1]["indikatoren"].append(z["indikator_id"])
    kern_ids = [z["indikator_id"] for z in kern_zeilen]
    relativ = [i for i in ind if i.startswith("koeln_") and ind[i]["typ"] in TYPEN_KARTE
               and any(i in karte.get(e, ()) for e in EBENEN_KARTE)]
    reihe = [i for i in kern_ids if i in relativ] + sorted(
        (i for i in relativ if i not in kern_ids), key=lambda i: (ind[i]["thema"], i))
    ww = [f"ww_{fu}" for fu in strukturdaten.WW_AUSWAHL if f"ww_{fu}" in ind]
    gegenstueck = {k: w for k, w in WW_GEGENSTUECK.items() if k in ind and w in ind}
    weitere = sorted({ind[i]["thema"] for i in ind if i.startswith("koeln_") and i not in kern_ids})
    return {
        "hinweis": ("Nur Darstellung, keine Werte: Auswahl, Reihenfolge und Gruppen für Kontext-Panel und Karte. Werte "
                    "stehen in raumwerte/ und karte/ (Zeilen und Spalten wie werte.tsv des Datenvertrags), "
                    "Metadaten in indikatoren.tsv und meta.json."),
        "vertrag_version": meta.get("vertrag_version"),
        "datenstand": meta.get("datenstand"),
        "einwohner_indikator": meta.get("einwohner_indikator") or "",
        "dateien": {
            "indikatoren": "indikatoren.tsv", "meta": "meta.json", "gesamtstadt": "gesamtstadt.tsv",
            "zuordnung": "zuordnung.tsv", "raum": "raum/<raumebene>.geojson",
            "raumwerte": "raumwerte/<raumebene>/<raum_id>.tsv", "karte": "karte/<raumebene>/<indikator_id>.tsv",
            "spalten": list(strukturdaten.KOPF_WERTE),
        },
        "raumwerte": {e: raumwerte.get(e, []) for e in EBENEN_RAUMWERTE},
        "raeume": {"hinweis": ("Namen und Eltern aus raum/<raumebene>.geojson (raum_id, name, eltern_id), damit das "
                               "Kontext-Panel ohne Geometrie auskommt"),
                   "spalten": ["raum_id", "name", "eltern_id"], **(namen or {})},
        "kern": {"quelle": "pipeline/strukturdaten_kern.tsv", "themen": themen},
        "weitere": {"hinweis": ("alle übrigen Indikatoren aus indikatoren.tsv mit der Kennung koeln_…, aufklappbar, "
                                "gruppiert nach dem Feld thema"), "themen": weitere},
        "karte": {"ebenen": list(EBENEN_KARTE), "vorgabe_ebene": KARTE_VORGABE, "typen": list(TYPEN_KARTE),
                  "indikatoren": reihe, "dateien": {e: karte.get(e, []) for e in EBENEN_KARTE}},
        "vergleich": {"quelle": "gesamtstadt.tsv",
                      "kommunen": [{"kommune": k, "name": WW_NAMEN.get(k, k)} for k in strukturdaten.WW_KOMMUNEN],
                      "indikatoren": ww, "gegenstueck": gegenstueck,
                      "gegenstueck_hinweis": ("Zuordnung aus Phase 0 (explore/strukturdaten/wegweiser_vorschlag.tsv, "
                                              "Art „direkt“); nur nebeneinander zeigen, nicht verrechnen.")},
        "texte": TEXTE,
    }


def _schreiben(pfad, kopf, zeilen):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="") as fh:
        fh.write(kopf)
        fh.writelines(zeilen)


def ausliefern(ziel, quelle_ordner=None, kern_pfad=None):
    """Datenvertrag aus `quelle_ordner` (Vorgabe data/strukturdaten/) nach `ziel` (auf der Seite data/strukturdaten/)
    aufteilen; Rückgabe {dateien, bytes, groesste: (Pfad, Bytes), raumwerte, karte}."""
    import shutil
    from .strukturdaten import EBENEN_WERTE
    src = Path(quelle_ordner or quelle())
    meta = _meta(src)   # vor dem Löschen des Ziels: ohne veroeffentlichen=true nichts ausliefern
    ziel = Path(ziel)
    shutil.rmtree(ziel, ignore_errors=True)
    for name in KOPIEREN:
        (ziel / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / name, ziel / name)
    indikatoren = _tsv(src / "indikatoren.tsv")
    typ = {i["indikator_id"]: i["typ"] for i in indikatoren}
    kopf, zeilen = _lesen(src / "werte.tsv")
    je_raum, je_karte = {}, {}
    for zeile in zeilen:
        ebene, raum_id, iid, _ = zeile.split("\t", 3)
        if ebene not in EBENEN_WERTE:
            raise ValueError(f"werte.tsv: Raumebene {ebene!r}")
        if iid not in typ:
            raise ValueError(f"werte.tsv: Indikator {iid} fehlt in indikatoren.tsv")
        je_raum.setdefault((ebene, raum_id), []).append(zeile)
        if ebene in EBENEN_KARTE and typ[iid] in TYPEN_KARTE:
            je_karte.setdefault((ebene, iid), []).append(zeile)
    q_kopf, q_zeilen = _lesen(src / "werte_quartier.tsv.gz")
    if q_kopf != kopf:
        raise ValueError("werte_quartier.tsv.gz: Kopf anders als werte.tsv")
    for zeile in q_zeilen:
        ebene, _, iid, _ = zeile.split("\t", 3)
        if ebene != "quartier" or iid not in typ:
            raise ValueError(f"werte_quartier.tsv.gz: unerwartete Zeile {zeile!r}")
        if typ[iid] in TYPEN_KARTE:
            je_karte.setdefault((ebene, iid), []).append(zeile)
    raumwerte, karte = {}, {}
    for (ebene, raum_id), teil in je_raum.items():
        _schreiben(ziel / "raumwerte" / ebene / f"{_name(raum_id, 'raum_id')}.tsv", kopf, teil)
        raumwerte.setdefault(ebene, []).append(raum_id)
    for (ebene, iid), teil in je_karte.items():
        _schreiben(ziel / "karte" / ebene / f"{_name(iid, 'indikator_id')}.tsv", kopf, teil)
        karte.setdefault(ebene, []).append(iid)
    raumwerte = {e: sorted(r, key=int) for e, r in raumwerte.items()}
    karte = {e: sorted(k) for e, k in karte.items()}
    doc = anzeige(indikatoren, raumwerte, karte, meta, kern(kern_pfad, set(typ)), raeume(src))
    (ziel / "anzeige.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    dateien = [p for p in ziel.rglob("*") if p.is_file()]
    groesste = max(dateien, key=lambda p: (p.stat().st_size, p.as_posix()))
    stat = {"dateien": len(dateien), "bytes": sum(p.stat().st_size for p in dateien),
            "groesste": (groesste.relative_to(ziel).as_posix(), groesste.stat().st_size),
            "raumwerte": {e: len(r) for e, r in raumwerte.items()}, "karte": {e: len(k) for e, k in karte.items()}}
    print(f"Strukturdaten → {ziel}: {stat['dateien']} Dateien, {stat['bytes']} Bytes, größte {stat['groesste'][0]} "
          f"({stat['groesste'][1]} Bytes); raumwerte {stat['raumwerte']}, karte {stat['karte']}")
    return stat


def paketdateien(quelle_ordner=None):
    """[(Pfad, Name im Datenpaket unter strukturdaten/)]: alle Dateien des Datenvertrags samt Prüfprotokollen,
    unverändert; nicht die Aufteilung für die Seite."""
    src = Path(quelle_ordner or quelle())
    _meta(src)   # nur mit veroeffentlichen=true
    return [(p, f"strukturdaten/{p.relative_to(src).as_posix()}") for p in sorted(src.rglob("*"))
            if p.is_file() and not p.name.endswith(".tmp")]


def lizenzteile():
    """Teile für DCAT (publish.write_dcat): [(Bezeichnung, Lizenz mit Namensnennung)] der Strukturdaten."""
    from . import strukturdaten, strukturdaten_raum
    return [
        (f"{strukturdaten.KOELN_TITEL} (Strukturdaten)",
         f"dl-de/by 2.0 ({strukturdaten.KOELN_LIZENZ}); Namensnennung: {strukturdaten.KOELN_HERAUSGEBER} "
         f"({strukturdaten.KOELN_TITEL}); Altersanteile vom Ratsatlas abgeleitet"),
        (f"{strukturdaten_raum.QUARTIERE_TITEL} (Flächen)", f"dl-de/zero 2.0; {config.NAMENSNENNUNG}"),
        (f"{strukturdaten.WW_TITEL}, gesamtstädtische Vergleichswerte",
         f"CC0 1.0; Quelle: {strukturdaten.WW_QUELLENANGABE}, Datenhalter je Indikator"),
    ]
