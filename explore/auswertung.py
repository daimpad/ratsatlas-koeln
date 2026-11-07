"""Auswertung der Messstufen (explore/STUFEN.md) als Markdown auf stdout – ohne Netzzugriff.

Liest das Abrufprotokoll _cache/abrufe.tsv und die TSVs in ergebnisse/ (oparl_laeufe.tsv, oparl_listen.tsv,
oparl_test.tsv, oparl_kennzahlen.tsv, oparl_organisationstypen.tsv, oparl_stichprobe_*.tsv, oparl_papertypen.tsv,
oparl_referenzschema.tsv, oparl_top_ergebnisse.tsv, pdf_koepfe.tsv). Fehlende Dateien werden übersprungen.
Je Stufe: Anfragen (Netz, Cache), Statuscodes, mittlere und höchste Antwortzeit, Bytes, Ergebnis; dazu Kennwerte
(totalElements, Seitengröße, Form von links.next, Parametertests, Feldabdeckung, Regel Stufe 3/5) und Auffälligkeiten
nach den Abbruchkriterien in STUFEN.md. Fehlt das Abrufprotokoll für einen Lauf (z. B. andere Arbeitsumgebung), gelten
Statuscodes und Antwortzeiten als „nicht prüfbar (Protokoll fehlt)“.
Aufruf: python3 explore/auswertung.py [--cache VERZ] [--ergebnisse VERZ] [--stufe S]
"""
import argparse
import collections
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

HIER = Path(__file__).resolve().parent
GRENZE_DAUER = 5.0     # Sekunden, Abbruchkriterium aus STUFEN.md
NICHT_PRUEFBAR = "nicht prüfbar (Protokoll fehlt)"


def lies(datei):
    if not Path(datei).exists():
        return []
    with open(datei, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def zahl(x, standard=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return standard


def statistik(zeilen):
    """Kennzahlen über Protokollzeilen: Netz, Cache, Statuscodes, Antwortzeit Ø und max, Bytes."""
    netz = [z for z in zeilen if z.get("quelle") == "netz"]
    dauer = [zahl(z.get("dauer_s")) for z in netz]
    status = collections.Counter(z.get("status") for z in netz)
    return {"netz": len(netz), "cache": sum(1 for z in zeilen if z.get("quelle") == "cache"),
            "status": ", ".join(f"{k}×{v}" for k, v in sorted(status.items())) or "–",
            "status_roh": status, "mittel": sum(dauer) / len(dauer) if dauer else None,
            "max": max(dauer) if dauer else None, "bytes": sum(int(zahl(z.get("bytes"))) for z in netz)}


def anteil(teil, ganz):
    return f"{100 * zahl(teil) / zahl(ganz):.0f} %" if zahl(ganz) else "–"


def sekunden(x):
    return "–" if x is None else f"{x:.2f}"


def form_next(nxt, liste=None):
    """Form von links.next: Pfad gleich der Liste?, Parameter, URL-Kodierung."""
    if not nxt:
        return "fehlt"
    t = urlsplit(nxt)
    namen = [x.partition("=")[0] for x in t.query.split("&") if x]
    teile = [f"Parameter {', '.join(namen) or '–'}", f"URL-kodiert {'ja' if '%' in t.query else 'nein'}"]
    if "+" in t.query:
        teile.append("„+“ unverändert")
    if liste:
        l = urlsplit(liste)
        teile.insert(0, "gleicher Pfad" if (l.netloc, l.path) == (t.netloc, t.path) else f"anderer Pfad {t.path}")
    return "; ".join(teile)


def lokal(url):
    t = urlsplit(url)
    return t.scheme == "http" and t.hostname in ("127.0.0.1", "localhost")


def tabelle(kopf, zeilen):
    aus = ["| " + " | ".join(kopf) + " |", "|" + "---|" * len(kopf)]
    aus += ["| " + " | ".join(str(x).replace("|", "/") for x in z) + " |" for z in zeilen]
    return aus


def status_hinweise(zeilen, kommando):
    """Antworten ans Netz außer 200, gezählt je (Status, Hinweis). Der Hinweis „erwartet“ gilt nur für eine 404 auf
    eine URL mit URL-Kodierung (%) im Kommando kennzahlen; Weiterleitungen nennen ihr Ziel."""
    aus = collections.Counter()
    for z in zeilen:
        code = z.get("status") or ""
        if z.get("quelle") != "netz" or code == "200":
            continue
        if code == "404" and kommando == "kennzahlen" and "%" in (z.get("url") or ""):
            hinweis = " (erwartet: Test mit URL-kodiertem Parameter)"
        elif code.startswith("3"):
            hinweis = f" (Weiterleitung nach {z.get('ziel') or '(ohne Ziel)'}, nicht verfolgt: stoppen)"
        elif not code.isdigit() or code in ("403", "429") or code.startswith("5"):
            hinweis = " (mögliche Sperre: stoppen)"
        else:
            hinweis = ""
        aus[(code, hinweis)] += 1
    return aus


def laeufe_abschnitt(laeufe, protokoll, stufe=None):
    aus, zugeordnet, auffaellig = [], set(), []
    vollstaendig = bool(protokoll)
    je_lauf, je_stufe = [], collections.OrderedDict()
    for l in laeufe:
        von, bis = int(zahl(l.get("protokoll_von"))), int(zahl(l.get("protokoll_bis")))
        zugeordnet.update(range(von, bis))
        if stufe and l.get("stufe") != stufe:
            continue
        zz = protokoll[von:bis] if vollstaendig and bis <= len(protokoll) else None
        if zz is not None:
            s = statistik(zz)
        else:   # Protokoll fehlt (z. B. andere Arbeitsumgebung): nur die Zähler aus dem Lauf
            s = {"netz": l.get("netz"), "cache": l.get("cache"), "status": NICHT_PRUEFBAR,
                 "status_roh": {}, "mittel": None, "max": None, "bytes": "–"}
        je_lauf.append((l, s))
        g = je_stufe.setdefault(l.get("stufe") or "–", {"kommandos": [], "zeilen": [], "laeufe": [], "ergebnisse": []})
        g["kommandos"].append(l.get("kommando"))
        g["laeufe"].append(l)
        g["ergebnisse"].append(l.get("ergebnis"))
        if zz is not None:
            g["zeilen"] += zz
        # Auffälligkeiten nach den Abbruchkriterien
        if l.get("ergebnis") != "ok":
            auffaellig.append(f"Lauf {l['lauf']} ({l['kommando']}): {l.get('ergebnis')} – {l.get('meldung', '')[:200]}")
        if zz is None:
            if str(l.get("netz")) != "0":
                auffaellig.append(f"Lauf {l['lauf']} ({l['kommando']}): Statuscodes und Antwortzeiten "
                                  f"{NICHT_PRUEFBAR}")
            continue
        for (code, hinweis), n in sorted(status_hinweise(zz, l.get("kommando")).items()):
            auffaellig.append(f"Lauf {l['lauf']} ({l['kommando']}): Status {code} × {n}{hinweis}")
        if s["max"] is not None and s["max"] > GRENZE_DAUER:
            auffaellig.append(f"Lauf {l['lauf']} ({l['kommando']}): Antwortzeit bis {s['max']:.1f} s "
                              f"(Grenze {GRENZE_DAUER:g} s)")

    aus.append("## Je Stufe\n")
    zeilen = []
    for st, g in je_stufe.items():
        if g["zeilen"]:
            s = statistik(g["zeilen"])
        else:
            s = {"netz": sum(int(zahl(l.get("netz"))) for l in g["laeufe"]),
                 "cache": sum(int(zahl(l.get("cache"))) for l in g["laeufe"]), "status": NICHT_PRUEFBAR,
                 "mittel": None, "max": None, "bytes": "–"}
        ergebnis = "ok" if all(e == "ok" for e in g["ergebnisse"]) else "; ".join(sorted(set(g["ergebnisse"])))
        zeilen.append([st, ", ".join(dict.fromkeys(g["kommandos"])), s["netz"], s["cache"], s["status"],
                       sekunden(s["mittel"]), sekunden(s["max"]), s["bytes"], ergebnis])
    aus += tabelle(["Stufe", "Kommandos", "Netz", "Cache", "Status", "Ø s", "max s", "Bytes", "Ergebnis"], zeilen)

    aus.append("\n## Läufe\n")
    zeilen = [[l["lauf"], l.get("stufe") or "–", l["kommando"], l.get("parameter") or "–", l.get("start", ""),
               f"{l.get('dauer_s', '')} s", s["netz"], s["cache"], l.get("obergrenze") or "–", s["status"],
               sekunden(s["mittel"]), sekunden(s["max"]), s["bytes"], l.get("ergebnis")] for l, s in je_lauf]
    aus += tabelle(["Lauf", "Stufe", "Kommando", "Parameter", "Start", "Dauer", "Netz", "Cache", "Obergrenze",
                    "Status", "Ø s", "max s", "Bytes", "Ergebnis"], zeilen)

    rest = [z for i, z in enumerate(protokoll) if i not in zugeordnet]
    if rest and not stufe:
        hosts = collections.Counter(urlsplit(z.get("url", "")).hostname for z in rest)
        aus.append(f"\nWeitere Zeilen im Abrufprotokoll ohne Lauf (z. B. geodaten.py): {len(rest)} "
                   f"({', '.join(f'{h} × {n}' for h, n in hosts.most_common())})")
    aus.append("\n## Auffälligkeiten\n")
    aus += [f"- {a}" for a in auffaellig] or ["- keine (Ergebnis ok, kein 429/5xx, keine Weiterleitung, keine "
                                              f"Antwort über {GRENZE_DAUER:g} s, kein Verbindungsabbruch)"]
    return aus


def kennwerte(erg):
    aus = ["\n## Kennwerte\n"]
    test, kz = lies(erg / "oparl_test.tsv"), lies(erg / "oparl_kennzahlen.tsv")
    werte = collections.defaultdict(dict)
    for z in test + kz:            # Kennzahlen überschreiben den Test (neuerer Stand)
        werte[z["objekt"]][z["feld"]] = z["wert"]
    if werte:
        if any(lokal(werte.get(o, {}).get("id") or werte.get(o, {}).get("url") or "") for o in ("system", "body", "paper")):
            aus.append("**Hinweis: Ergebnisse vom lokalen Testserver mit erfundenen Daten (Probelauf), nicht aus Köln.**\n")
        for objekt, felder in (("system", ("oparlVersion", "vendor", "product", "license")),
                               ("body", ("name", "license", "modified"))):
            if objekt in werte:
                aus.append(f"- {objekt}: " + "; ".join(f"{f} = {werte[objekt].get(f) or '(leer)'}"
                                                         for f in felder if f in werte[objekt]))
        zeilen = []
        for liste in ("paper", "meeting", "organization", "person"):
            w = werte.get(liste)
            if not w:
                continue
            zeilen.append([liste, w.get("pagination.totalElements") or "–", w.get("pagination.elementsPerPage") or "–",
                           w.get("pagination.totalPages") or "–", w.get("objekte_erste_seite") or "–",
                           w.get("links.schluessel") or "–", form_next(w.get("links.next"), w.get("url"))])
        if zeilen:
            aus.append("")
            aus += tabelle(["Liste", "totalElements", "elementsPerPage", "totalPages", "Objekte 1. Seite",
                            "links", "links.next"], zeilen)
        if werte.get("paper", {}).get("felder_erstes_objekt"):
            aus.append(f"\nFelder des ersten Objekts der Vorlagenliste: {werte['paper']['felder_erstes_objekt']}")
        tests = [(f, w) for f, w in werte.get("paper", {}).items() if f.startswith("test ")]
        if tests:
            aus.append("\nParametertests (Vorlagen):\n")
            aus += tabelle(["Test", "Antwort"], [[f[5:], w] for f, w in tests])
        if "abbruch" in werte.get("lauf", {}):
            aus.append(f"\nTest/Kennzahlen abgebrochen: {werte['lauf']['abbruch']}")

    listen = lies(erg / "oparl_listen.tsv")
    if listen:
        aus.append("\nDurchlaufene Listen (oparl_listen.tsv):\n")
        je = collections.OrderedDict()
        for z in listen:
            je.setdefault(z["lauf"], []).append(z)
        zeilen = []
        for lauf, zz in je.items():
            enden = collections.Counter(z["ende"] for z in zz)
            zeilen.append([lauf, ", ".join(dict.fromkeys(z["liste"].split(" ")[0] for z in zz)), len(zz),
                           sum(int(zahl(z["seiten"])) for z in zz), sum(int(zahl(z["objekte"])) for z in zz),
                           "; ".join(f"{k} × {v}" for k, v in enden.items()),
                           form_next(next((z["erstes_next"] for z in zz if z["erstes_next"]), ""), zz[0]["url"])])
        aus += tabelle(["Lauf", "Liste", "Listen", "Seiten", "Objekte", "Ende", "links.next"], zeilen)

    typen = lies(erg / "oparl_organisationstypen.tsv")
    if typen:
        aus.append(f"\nOrganisationen: {sum(int(zahl(z['anzahl'])) for z in typen)} erfasst; organizationType: "
                   + ", ".join(f"{z['organizationType']} {z['anzahl']}" for z in typen))

    bed = lies(erg / "oparl_stichprobe_bedeckung.tsv")
    if bed:
        aus.append("\nStichprobe – Feldabdeckung:\n")
        aus += tabelle(["Feld", "vorhanden", "von", "Anteil"],
                       [[z["feld"], z["vorhanden"], z["von"], anteil(z["vorhanden"], z["von"])] for z in bed])
        regel = [z for z in bed if z["feld"].startswith(("created außerhalb", "doppelte Kennungen"))]
        if regel:   # Regel in STUFEN.md, Stufe 3 und 5
            erfuellt = all(int(zahl(z["vorhanden"])) == 0 for z in regel)
            aus.append("\nRegel Stufe 3/5 (Jahresfilter wirkt, keine Doppelungen): "
                       + ("erfüllt" if erfuellt else "nicht erfüllt – nicht weiter, berichten"))
    jahre = lies(erg / "oparl_stichprobe_jahre.tsv")
    if jahre:
        aus.append("\nStichprobe – Jahre: " + "; ".join(
            f"{z['jahr']}: {z['objekte']} von {z.get('totalElements') or '?'}" for z in jahre))
    for datei, schluessel, titel in (("oparl_papertypen.tsv", "paperType", "paperType"),
                                     ("oparl_referenzschema.tsv", "schema", "Referenzschema"),
                                     ("oparl_top_ergebnisse.tsv", "result", "TOP-Ergebnisse (agendaItem.result)")):
        zz = lies(erg / datei)
        if zz:
            aus.append(f"\n{titel}: " + "; ".join(f"{z[schluessel]} {z['anzahl']}" for z in zz[:15])
                       + (f"; … ({len(zz) - 15} weitere)" if len(zz) > 15 else ""))
    pdf = lies(erg / "pdf_koepfe.tsv")
    if pdf:
        treffer = collections.Counter(z.get("treffer") or "keine_datei" for z in pdf)
        mit = sum(v for k, v in treffer.items() if k not in ("keine_datei", "nicht abgerufen"))
        jahre_pdf = collections.Counter(z.get("jahr") or "?" for z in pdf)
        aus.append(f"\nPDF-Köpfe: {len(pdf)} Verwaltungsvorlagen, {mit} Dateien ausgewertet; "
                   + ", ".join(f"{k} {v}" for k, v in treffer.most_common())
                   + "; je Jahr: " + ", ".join(f"{j} {n}" for j, n in sorted(jahre_pdf.items()))
                   + (f"; Erkennungsquote „Dezernat, Dienststelle“ mit Kennung: {100 * treffer['kennung'] / mit:.0f} %"
                      if mit else ""))
    return aus


def auswertung(cache, erg, stufe=None):
    cache, erg = Path(cache), Path(erg)
    protokoll = lies(cache / "abrufe.tsv")
    laeufe = lies(erg / "oparl_laeufe.tsv")
    aus = ["# Auswertung der Messstufen", "",
           f"Quellen: {cache / 'abrufe.tsv'} ({len(protokoll)} Zeilen), {erg / 'oparl_laeufe.tsv'} "
           f"({len(laeufe)} Läufe)", ""]
    if laeufe:
        aus += laeufe_abschnitt(laeufe, protokoll, stufe)
    elif protokoll:
        s = statistik(protokoll)
        aus += ["## Abrufprotokoll (ohne Laufzuordnung)", "",
                f"Netz {s['netz']}, Cache {s['cache']}, Status {s['status']}, Ø {sekunden(s['mittel'])} s, "
                f"max {sekunden(s['max'])} s, {s['bytes']} Bytes"]
    else:
        aus.append("Noch keine Läufe.")
    return "\n".join(aus + kennwerte(erg)) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Auswertung der Messstufen (Markdown)")
    ap.add_argument("--cache", default=os.environ.get("RATSATLAS_CACHE", HIER / "_cache"))
    ap.add_argument("--ergebnisse", default=os.environ.get("RATSATLAS_ERGEBNISSE", HIER / "ergebnisse"))
    ap.add_argument("--stufe", help="nur diese Stufe in den Tabellen der Läufe")
    a = ap.parse_args()
    sys.stdout.write(auswertung(a.cache, a.ergebnisse, a.stufe))


if __name__ == "__main__":
    main()
