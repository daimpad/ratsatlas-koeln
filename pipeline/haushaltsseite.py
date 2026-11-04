"""Seite haushalt/: Treemap der ordentlichen Aufwendungen je Produktbereich (Schritt 1, Entscheidung 28.10.2026).

Vorbild ist die Treemap der Berliner Haushaltsdaten (ODIS, github.com/berlin/haushaltsdaten). Ebene 1: die 17
Produktbereiche aus den geprüften Teilergebnisplänen (data/haushalt/produktbereiche.tsv, Zeile 17,
pipeline/haushaltsplan.py). Je Ansicht (Plan der beiden Haushaltsjahre, jüngstes Ist) eine Treemap als SVG, für breite
und schmale Bildschirme getrennt gelegt; der Wechsel braucht kein Skript (Auswahlknöpfe und CSS). Eine Tabelle unter der
Treemap nennt alle Werte mit Fundstelle. Nominal, ohne Wertung, ohne Finanzplanung ab 2027.

Ebenen 2 und 3 (haushalt/PHASE3.md, nur mit haushaltsplan.EBENEN_FREIGEGEBEN): Ein Klick auf einen Produktbereich führt
auf das Sprungziel #zoom-XX mit der Treemap seiner Produktgruppen, den Aufwandsarten des Produktbereichs als Balken und
einer Tabelle der Produktgruppen (data/haushalt/aufwandsarten.tsv, produktgruppen.tsv). Ein Klick auf eine
Produktgruppe führt auf #pg-1-XX-YY mit ihren Aufwandsarten als Balken und Tabelle. Auch das geht ohne Skript (:target);
alle Abschnitte liegen in .hh-karten, damit die Auswahlknöpfe überall wirken. Für die Browser-Prüfung vor der Freigabe
zeigt die Umgebungsvariable HAUSHALT_EBENEN=vorschau die Ebenen beim Erzeugen der Seite.

Mit Skript (site/haushalt.js, Entscheidung 28.10.2026) wächst die angeklickte Kachel auf die ganze Fläche und zeigt ihre
Unterteilung; Ebene 3 zeichnet es als Kacheln aus den Beträgen der Balken (data-b), damit die Seite klein bleibt.
Erklärungen stehen einmal im Akkordeon „So lesen Sie die Zahlen“, Grenzen und Quellen in zugeklappten Akkordeons.

Erträge und Ergebnis (Erweiterung Phase 1, Entscheidungen 02.11.2026; haushalt/phase0/ERWEITERUNG.md): ordentliche
Erträge (Zeile 10) und Ergebnis vor internen Leistungen (Zeile 18) je Produktbereich, dazu je Einwohner (abgeleitet,
IT.NRW, Fortschreibung auf Basis des Zensus 2022 zum 31.12.; Ist mit dem Stand seines Jahres, Plan mit dem jüngsten
Stand). Eine Treemap zeigt den Zuschussbedarf (negatives Ergebnis); Überschüsse stehen nur in der Tabelle.

Ist 2024, Veränderung und Investitionen (Erweiterung Phase 5, Entscheidungen 03.11.2026; haushalt/PHASE5.md; nur mit
haushaltsplan.ERWEITERUNG_FREIGEGEBEN, vor der Freigabe mit HAUSHALT_ERWEITERUNG=vorschau): Ist 2024 aus dem
festgestellten Jahresabschluss 2024 als vierte Ansicht auf allen Ebenen (data/haushalt/jahresabschluss.tsv, Spalte 4,
auf Euro gerundet); Veränderung nur zwischen gleichartigen Werten (Ist zu Ist, Ist 2024 zum Ansatz der Satzung 2024,
Plan zu Plan), ohne Prozent bei Ausgangswerten bis 0 €; Investitionen aus Teilfinanzplan A und Teilfinanzrechnung
(investitionen.tsv, jahresabschluss_investitionen.tsv), ohne Verpflichtungsermächtigungen und Finanzplanung.
"""
import json
import os
from collections import defaultdict
from html import escape

from . import haushaltsplan
from .dossier import _date, _mio
from .themenseiten import ALLE as THEMEN

PFAD = "haushalt/"
ZEILE = 17
# Farbe der Flächen (Ebenen 1 und 2): eine Farbe in fünf Stufen nach dem Anteil an der Ebene darüber, je dunkler, desto
# größer (Entscheidung des Auftraggebers 28.10.2026; Klassen s1 … s5 an den Flächen, hh-s1 … hh-s5 in der Legende, page.css;
# Schrift je Stufe mit Kontrast ≥ 4,5)
STUFEN = (2, 5, 10, 20)   # Grenzen in Prozent
STUFEN_TEXT = ("unter 2 %", "2 bis 5 %", "5 bis 10 %", "10 bis 20 %", "ab 20 %")
FORMATE = {"breit": (1000, 560), "hoch": (340, 640)}   # hoch: etwa in Bildschirmgröße eines Telefons
# Aufwandsarten: feste, nominale Farben als Klassen hh-f11 … hh-f16 (Balken) und hh-z11 … hh-z16 (Tabelle) in page.css
HINWEIS = ("Aufwandsarten sind Kontenarten, keine Aufgaben: Sie zeigen, wofür das Geld der Art nach verbucht ist, etwa "
           "für Personal oder für Transfers. Bilanzielle Abschreibungen verteilen den Wertverlust von Gebäuden und "
           "Anlagen auf die Jahre; sie fließen nicht als Geld ab.")
BEGRIFFE = "Begriffe oben unter „So lesen Sie die Zahlen“."   # kein Link: ein Sprung verließe die Ebene (:target)
# Einwohner zum 31.12. (IT.NRW, Kommunalprofil Bonn, Stand 15.01.2026, S. 5; Fortschreibung auf Basis des Zensus 2022;
# dl-de/by-2.0). Ist mit dem Stand seines Jahres, Plan mit dem jüngsten Stand (Entscheidung 02.11.2026).
EINWOHNER = {2022: 322_221, 2023: 321_680, 2024: 323_336}
EINWOHNER_QUELLE = ("IT.NRW, Kommunalprofil Bonn (Stand 15.01.2026), Bevölkerung zum 31.12., Fortschreibung auf Basis "
                    "des Zensus 2022; Datenlizenz Deutschland – Namensnennung – Version 2.0")
ZAHLWORT = {2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs", 7: "sieben", 8: "acht", 9: "neun", 10: "zehn"}


def _prozent(x):
    return f"{x:.1f}".replace(".", ",") + " %"


def _euro(x):
    return f"{x:,}".replace(",", ".").replace("-", "−") + " €"


def _betrag(x):
    """Wie _mio; Beträge unter 0,05 Mio. € in Euro, damit sie nicht als 0,0 Mio. € erscheinen."""
    return _euro(x) if abs(x) < 50_000 else _mio(x)


def _mio_v(x):
    """Wie _mio, mit typografischem Minus."""
    return _mio(x).replace("-", "−")


def einwohner(art, jahr):
    """Einwohnerzahl für eine Ansicht: Ist mit dem 31.12. seines Jahres, Plan mit dem jüngsten Stand."""
    return EINWOHNER.get(jahr) if art == "ist" else EINWOHNER[max(EINWOHNER)]


def _je_ew(x, art, jahr):
    ew = einwohner(art, jahr)
    return f"{round(x / ew):,}".replace(",", ".").replace("-", "−") + " € je Einwohner" if ew else ""


JA = "Jahresabschluss 2024"


def erweiterung_an():
    return haushaltsplan.erweiterung_an()


def _euro_cent(c):
    """Cent → Euro, kaufmännisch gerundet (auch negativ)."""
    return (abs(c) + 50) // 100 * (1 if c >= 0 else -1)


def _ja_index(path, spalte="4"):
    """{(Ebene, Produktbereich oder Produktgruppe, Zeile): Wert} einer Spalte einer Datei des Jahresabschlusses."""
    out = {}
    for r in haushaltsplan.lesen(path):
        if r["spalte"] == spalte:
            key = r["produktgruppe"] if r["ebene"] == "Produktgruppe" else r["produktbereich"]
            out[(r["ebene"], key, int(r["zeile"]))] = {"betrag": _euro_cent(int(r["betrag_cent"])), "ausgabe": JA,
                                                       "datei": r["datei"], "seite": int(r["seite"]), "leer": r["leer"] == "ja"}
    return out


def _quelle(a):
    return a if a.startswith("Jahresabschluss") else f"Haushaltsplan {a}"


def _plan_ausgaben(d):
    return sorted(a for a in d["ausgaben"] if "/" in a)


def ebenen_an():
    return haushaltsplan.EBENEN_FREIGEGEBEN or os.environ.get("HAUSHALT_EBENEN") == "vorschau"


def _anker(pg):
    return "pg-" + pg.replace(".", "-")


def squarify(werte, x, y, w, h):
    """Squarified Treemap (Bruls, Huizing, van Wijk 2000): [(x, y, w, h)] in der Reihenfolge der Werte, die absteigend
    sortiert sein müssen. Die Flächen sind proportional zu den Werten und füllen das Rechteck."""
    gesamt = sum(werte)
    if not werte or gesamt <= 0:
        return []
    flaechen = [v * w * h / gesamt for v in werte]
    out = []

    def schlechteste(reihe, seite):
        s = sum(reihe)
        return max(max(seite * seite * r / (s * s), s * s / (seite * seite * r)) for r in reihe)

    i = 0
    while i < len(flaechen):
        seite = min(w, h)
        reihe = [flaechen[i]]
        j = i + 1
        while j < len(flaechen) and schlechteste(reihe + [flaechen[j]], seite) <= schlechteste(reihe, seite):
            reihe.append(flaechen[j])
            j += 1
        s = sum(reihe)
        if w >= h:   # Spalte am linken Rand
            breite, yy = s / h, y
            for r in reihe:
                out.append((x, yy, breite, r / breite))
                yy += r / breite
            x, w = x + breite, w - breite
        else:        # Zeile am oberen Rand
            hoehe, xx = s / w, x
            for r in reihe:
                out.append((xx, y, r / hoehe, hoehe))
                xx += r / hoehe
            y, h = y + hoehe, h - hoehe
        i = j
    return out


def _wert(x):
    return x and {"betrag": x[0], "ausgabe": x[1]["ausgabe"], "datei": x[1]["datei"], "seite": int(x[1]["seite"]),
                  "leer": x[1].get("leer") == "ja"}


def _ist_plan(reihe):
    return {"ist": {j: _wert(i) for j, i, _ in reihe if i}, "plan": {j: _wert(x) for j, _, x in reihe if x}}


def _arten(schluessel, rows, feld, arten=None):
    return [{"zeile": nr, "name": name, **_ist_plan(haushaltsplan.reihe(schluessel, rows, nr, feld))}
            for nr, name in (arten or haushaltsplan.AUFWANDSARTEN).items()]


def daten(rows=None, aufwand=None, gruppen=None):
    """Produktbereiche mit Ist und Plan (Zeile 17), mit den Ebenen 2 und 3 auch Aufwandsarten und Produktgruppen, und
    die Ansichten: Plan der beiden jüngsten Haushaltsjahre und das jüngste Ist. None ohne Freigabe oder ohne Daten."""
    if not haushaltsplan.FREIGEGEBEN:
        return None
    rows = haushaltsplan.lesen() if rows is None else rows
    if not rows:
        return None
    an = ebenen_an()
    aufwand = (haushaltsplan.lesen(haushaltsplan.AUFWANDSARTEN_TSV) if an else []) if aufwand is None else aufwand
    gruppen = (haushaltsplan.lesen(haushaltsplan.PRODUKTGRUPPEN_TSV) if an else []) if gruppen is None else gruppen
    je_pg, namen = defaultdict(list), defaultdict(dict)
    for r in gruppen:
        je_pg[r["produktgruppe"]].append(r)
        namen[r["produktgruppe"]][r["ausgabe"]] = (r["name"], r["einheit"])
    neu = max((r["ausgabe"] for r in gruppen), default=None)
    themen = {t.produktbereich: t for t in THEMEN if t.produktbereich}
    # Ertragsarten (Zeilen 1–9, Option 5; nur mit Freigabe oder HAUSHALT_ERTRAGSARTEN=vorschau)
    mit_ertragsarten = bool(aufwand and gruppen) and haushaltsplan.ertragsarten_an() and haushaltsplan.ERTRAGSARTEN_TSV.exists()
    er_pb, er_pg = [], defaultdict(list)
    for r in haushaltsplan.lesen(haushaltsplan.ERTRAGSARTEN_TSV) if mit_ertragsarten else []:
        (er_pg[r["produktgruppe"]] if r["ebene"] == "Produktgruppe" else er_pb).append(r)
    pbs = []
    for pb, name in sorted({(r["produktbereich"], r["name"]) for r in rows}):
        t = themen.get(pb)
        p = {"pb": pb, "name": name, **_ist_plan(haushaltsplan.reihe(pb, rows, ZEILE)),
             "ertrag": _ist_plan(haushaltsplan.reihe(pb, rows, 10)), "ergebnis": _ist_plan(haushaltsplan.reihe(pb, rows, 18)),
             **({"thema": {"titel": t.titel, "pfad": t.pfad, "farben": t.farben}} if t else {})}
        if aufwand and gruppen:
            p["aufwandsarten"] = _arten(pb, aufwand, "produktbereich")
            p["produktgruppen"] = []
            for pg in sorted(g for g in je_pg if g.startswith(f"1.{pb}.") and neu in namen[g]):
                n, einheit = namen[pg][neu]
                alt = sorted((a, v[0]) for a, v in namen[pg].items() if v[0] != n)   # andere Namen älterer Ausgaben
                p["produktgruppen"].append({"nr": pg, "name": n, "einheit": einheit, "alt": alt,
                                            **_ist_plan(haushaltsplan.reihe(pg, je_pg[pg], ZEILE, "produktgruppe")),
                                            "aufwandsarten": _arten(pg, je_pg[pg], "produktgruppe"),
                                            **({"ertragsarten": _arten(pg, er_pg[pg], "produktgruppe", haushaltsplan.ERTRAGSARTEN),
                                                "ertrag": _ist_plan(haushaltsplan.reihe(pg, er_pg[pg], 10, "produktgruppe"))}
                                               if mit_ertragsarten else {})})
            if mit_ertragsarten:
                p["ertragsarten"] = _arten(pb, er_pb, "produktbereich", haushaltsplan.ERTRAGSARTEN)
        pbs.append(p)
    erweitert = erweiterung_an() and haushaltsplan.JAHRESABSCHLUSS_TSV.exists()
    if erweitert:   # Ist 2024 aus dem Jahresabschluss auf allen Ebenen
        ja = _ja_index(haushaltsplan.JAHRESABSCHLUSS_TSV)
        setze = lambda ziel, ebene, key, nr: ja.get((ebene, key, nr)) and ziel["ist"].__setitem__(2024, ja[(ebene, key, nr)])
        for p in pbs:
            for ziel, nr in ((p, ZEILE), (p["ertrag"], 10), (p["ergebnis"], 18)):
                setze(ziel, "Produktbereich", p["pb"], nr)
            for t in p.get("aufwandsarten", []):
                setze(t, "Produktbereich", p["pb"], t["zeile"])
            for g in p.get("produktgruppen", []):
                setze(g, "Produktgruppe", g["nr"], ZEILE)
                for t in g["aufwandsarten"]:
                    setze(t, "Produktgruppe", g["nr"], t["zeile"])
        if mit_ertragsarten and haushaltsplan.JA_ERTRAGSARTEN_TSV.exists():   # Ist 2024 der Ertragsarten
            ja = _ja_index(haushaltsplan.JA_ERTRAGSARTEN_TSV)
            for p in pbs:
                for t in p["ertragsarten"]:
                    setze(t, "Produktbereich", p["pb"], t["zeile"])
                for g in p["produktgruppen"]:
                    setze(g["ertrag"], "Produktgruppe", g["nr"], 10)
                    for t in g["ertragsarten"]:
                        setze(t, "Produktgruppe", g["nr"], t["zeile"])
    plan_jahre = sorted({j for p in pbs for j in p["plan"]})[-2:]
    ist_jahre = sorted({j for p in pbs for j in p["ist"]})[-(2 if erweitert else 1):]
    ansichten = [{"key": f"plan{j}", "art": "plan", "jahr": j, "titel": f"Plan {j}"} for j in reversed(plan_jahre)] \
        + [{"key": f"ist{j}", "art": "ist", "jahr": j, "titel": f"Ist {j}"} for j in reversed(ist_jahre)]
    for a in ansichten:
        a["summe"] = sum(p[a["art"]][a["jahr"]]["betrag"] for p in pbs if a["jahr"] in p[a["art"]])
        for k in ("ertrag", "ergebnis"):
            a[k] = sum(p[k][a["art"]][a["jahr"]]["betrag"] for p in pbs if a["jahr"] in p[k][a["art"]])
    stand = json.loads(haushaltsplan.STAND.read_text(encoding="utf-8"))
    ausgaben = {a: {"seite": v["seite"], "dateien": {k: d["url"] for k, d in v["dateien"].items()}}
                for a, v in stand["ausgaben"].items()}
    out = {"produktbereiche": pbs, "ansichten": ansichten, "abruf": stand["abruf"], "lizenz": stand["lizenz"],
           "zoom": bool(aufwand and gruppen), "ausgaben": ausgaben}
    if erweitert:
        url = stand["jahresabschluss"]["datei"]["url"]
        ausgaben[JA] = {"seite": stand["jahresabschluss"]["seite"], "dateien": {p["pb"]: url for p in pbs}}
        out["erweiterung"] = {"investitionen": investitionen_daten(pbs),
                              "fortgeschrieben": _ja_summe(_ja_index(haushaltsplan.JAHRESABSCHLUSS_TSV, "2"), ZEILE),
                              "abruf_ja": stand["jahresabschluss"]["abruf"]}
    return out


def _ja_summe(idx, nr):
    return sum(v["betrag"] for (ebene, _, z), v in idx.items() if ebene == "Produktbereich" and z == nr)


INVEST_ZEILEN = {6: "Investive Einzahlungen", 10: "davon Finanzanlagen", 13: "Investive Auszahlungen", 14: "Saldo"}


def investitionen_daten(pbs):
    """Je Produktbereich Zeilen 6, 10, 13, 14 des Teilfinanzplans A (Ist 2023, Ansatz 2024 der Satzung, Plan 2025 und
    2026) und der Teilfinanzrechnung (Ist 2024): {pb: {zeile: {(art, jahr): Wert}}}."""
    out = {p["pb"]: {nr: {} for nr in INVEST_ZEILEN} for p in pbs}
    for r in haushaltsplan.lesen(haushaltsplan.INVESTITIONEN_TSV):
        nr, j = int(r["zeile"]), int(r["jahr"])
        if r["ebene"] != "Produktbereich" or nr not in INVEST_ZEILEN or r["produktbereich"] not in out:
            continue
        art = "ist" if r["art"] == "Ergebnis" else "plan"
        if (art == "ist" and r["ausgabe"] == "2025/2026") or (art == "plan" and str(j) in r["ausgabe"].split("/")):
            out[r["produktbereich"]][nr][(art, j)] = {"betrag": int(r["betrag"]), "ausgabe": r["ausgabe"],
                                                      "datei": r["datei"], "seite": int(r["seite"]), "leer": r["leer"] == "ja"}
    for (ebene, pb, nr), v in _ja_index(haushaltsplan.JA_INVESTITIONEN_TSV).items():
        if ebene == "Produktbereich" and nr in INVEST_ZEILEN and pb in out:
            out[pb][nr][("ist", 2024)] = v
    return out


def _zeilen(text, max_zeichen):
    """Bricht einen Namen an Leerzeichen in Zeilen von höchstens max_zeichen Zeichen; None, wenn ein Wort nicht passt."""
    zeilen = []
    for wort in text.split():
        if len(wort) > max_zeichen:
            return None
        if zeilen and len(zeilen[-1]) + 1 + len(wort) <= max_zeichen:
            zeilen[-1] += " " + wort
        else:
            zeilen.append(wort)
    return zeilen


def _text(x, y, rw, rh, name, marke, betrag):
    """Beschriftung einer Fläche (Klassen hh-n, hh-b, hh-m, hh-k in page.css): Name umbrochen mit Betrag; passt er
    nicht, Marke (Nummer) und Betrag oder nur die Marke; bei sehr kleinen Flächen nichts."""
    groesse = 15
    zeichen = int((rw - 12) / (0.62 * groesse))   # mittlere Zeichenbreite von Inter, halbfett
    platz = int((rh - 8) // (groesse * 1.2)) - 1   # eine Zeile bleibt für den Betrag
    zeilen = _zeilen(name, zeichen) if rw >= 70 else None
    if zeilen and len(zeilen) <= platz and len(betrag) <= zeichen + 2:
        return "".join(f'<text x="{x + 6:.0f}" y="{y + 6 + groesse * (1 + 1.2 * k):.0f}" class="hh-n">{escape(z)}</text>'
                       for k, z in enumerate(zeilen)) \
            + f'<text x="{x + 6:.0f}" y="{y + 6 + groesse * (1 + 1.2 * len(zeilen)):.0f}" class="hh-b">{escape(betrag)}</text>'
    if rw >= 0.6 * 13 * max(len(marke), len(betrag)) + 12 and rh >= 2.6 * 13:   # Name passt nicht
        return (f'<text x="{x + 5:.0f}" y="{y + 18:.0f}" class="hh-m">{escape(marke)}</text>'
                f'<text x="{x + 5:.0f}" y="{y + 5 + 13 * 2.2:.0f}" class="hh-k">{escape(betrag)}</text>')
    if rw >= max(30, 0.62 * 13 * len(marke) + 8) and rh >= groesse + 6:
        return f'<text x="{x + 4:.0f}" y="{y + 3 + groesse:.0f}" class="hh-m">{escape(marke)}</text>'
    return ""


def _stufe(anteil):
    """Farbstufe 1–5 nach dem Anteil in Prozent (STUFEN)."""
    return 1 + sum(anteil >= g for g in STUFEN)


def legende(bezug):
    """Legende der Farbstufen; die Beschriftung steht in Textfarbe, die Farbe nur im Feld davor."""
    return (f'<p class="hh-legende">Anteil {escape(bezug)}:'
            + "".join(f'<i class="hh-s{k}"></i>{t}' for k, t in enumerate(STUFEN_TEXT, 1)) + "</p>")


def _svg_gruppen(flaechen, format_, label):
    """Treemap der Produktgruppen als SVG, knapp gehalten (viele Flächen): flaechen absteigend nach Betrag als
    (Betrag, Ziel, Beschreibung, Name, Marke, Betragstext, Anteil). Jede Fläche trägt die Klasse ihrer Farbstufe (Fläche
    und Schrift in page.css); Koordinaten ganzzahlig, der weiße Rand deckt die Rundung. Jede Fläche ist ein Link mit
    Titel (Hinweis beim Überfahren, zugleich Name des Links); _text setzt nur Beschriftungen, die passen."""
    w, h = FORMATE[format_]
    teile = []
    for (b, ziel, beschreibung, name, marke, text, anteil), (x, y, rw, rh) in zip(flaechen, squarify([f[0] for f in flaechen], 0, 0, w, h)):
        teile.append(f'<a href="#{ziel}" class="s{_stufe(anteil)}"><title>{escape(beschreibung)}</title>'
                     f'<rect x="{x:.0f}" y="{y:.0f}" width="{rw:.0f}" height="{rh:.0f}" rx="3"/>{_text(x, y, rw, rh, name, marke, text)}</a>')
    return (f'<svg class="hh-svg hh-{format_} hh-pgs" viewBox="0 0 {w} {h}" role="group" aria-label="{escape(label)}">'
            + "".join(teile) + "</svg>")


def treemap(d, ansicht, format_):
    """SVG einer Ansicht der Produktbereiche; jede Fläche verweist auf Ebene 2 oder (ohne Ebenen) auf die Zeile der
    Tabelle. Die Farbstufe folgt dem Anteil an der Summe der Ansicht."""
    a = ansicht
    items = sorted(((p, p[a["art"]][a["jahr"]]["betrag"]) for p in d["produktbereiche"] if a["jahr"] in p[a["art"]]),
                   key=lambda x: (-x[1], x[0]["pb"]))
    w, h = FORMATE[format_]
    teile = []
    for (p, b), (x, y, rw, rh) in zip(items, squarify([b for _, b in items], 0, 0, w, h)):
        ziel = f'{"zoom" if d.get("zoom") else "pb"}-{p["pb"]}'
        label = f'{p["pb"]} {p["name"]}: {_mio(b)}, {_prozent(100 * b / a["summe"])} ({a["titel"]})'
        r = f'x="{x:.1f}" y="{y:.1f}" width="{rw:.1f}" height="{rh:.1f}"'
        clip = f"hh-{a['key']}-{format_}-{p['pb']}"
        teile.append(f'<a href="#{ziel}" class="s{_stufe(100 * b / a["summe"])}" aria-label="{escape(label)}"><title>{escape(label)}</title>'
                     f'<clipPath id="{clip}"><rect {r}/></clipPath><rect {r} rx="3"/>'
                     f'<g clip-path="url(#{clip})">{_text(x, y, rw, rh, p["name"], p["pb"], _mio(b))}</g></a>')
    return (f'<svg class="hh-svg hh-{format_}" viewBox="0 0 {w} {h}" role="group" '
            f'aria-label="{escape(a["titel"])}: ordentliche Aufwendungen je Produktbereich, zusammen {escape(_mio(a["summe"]))}">'
            + "".join(teile) + "</svg>")


def treemap_zuschuss(d, ansicht, format_):
    """SVG des Zuschussbedarfs (negatives Ergebnis, Zeile 18) je Produktbereich in einer Ansicht; Produktbereiche mit
    Überschuss haben keine Fläche. Jede Fläche verweist auf die Zeile der Ergebnistabelle (#erg-XX)."""
    a = ansicht
    items = sorted(((p, -p["ergebnis"][a["art"]][a["jahr"]]["betrag"]) for p in d["produktbereiche"]
                    if a["jahr"] in p["ergebnis"][a["art"]] and p["ergebnis"][a["art"]][a["jahr"]]["betrag"] < 0),
                   key=lambda x: (-x[1], x[0]["pb"]))
    gesamt = sum(b for _, b in items)
    w, h = FORMATE[format_]
    teile = []
    for (p, b), (x, y, rw, rh) in zip(items, squarify([b for _, b in items], 0, 0, w, h)):
        label = f'{p["pb"]} {p["name"]}: Zuschussbedarf {_mio(b)}, {_prozent(100 * b / gesamt)} ({a["titel"]})'
        r = f'x="{x:.1f}" y="{y:.1f}" width="{rw:.1f}" height="{rh:.1f}"'
        clip = f"hh-erg-{format_}-{p['pb']}"
        teile.append(f'<a href="#erg-{p["pb"]}" class="s{_stufe(100 * b / gesamt)}" aria-label="{escape(label)}"><title>{escape(label)}</title>'
                     f'<clipPath id="{clip}"><rect {r}/></clipPath><rect {r} rx="3"/>'
                     f'<g clip-path="url(#{clip})">{_text(x, y, rw, rh, p["name"], p["pb"], _mio(b))}</g></a>')
    return (f'<svg class="hh-svg hh-{format_}" viewBox="0 0 {w} {h}" role="group" '
            f'aria-label="{escape(a["titel"])}: Zuschussbedarf je Produktbereich, zusammen {escape(_mio(gesamt))}">'
            + "".join(teile) + "</svg>")


def _zelle_ew(x, art, jahr):
    if not x:
        return "–"
    return f'{_mio_v(x["betrag"])}<br><small>{_je_ew(x["betrag"], art, jahr)}</small>'


def ergebnis(d, root):
    """Abschnitt „Erträge und Ergebnis“: Treemap des Zuschussbedarfs (erste Ansicht) und zwei Tabellen mit je Einwohner."""
    ansichten = d["ansichten"]
    ref = ansichten[0]
    spalten = [(a["art"], a["jahr"], a["titel"]) for a in reversed(ansichten)]
    kopf = "".join(f'<th scope="col">{escape(t)}</th>' for *_, t in spalten)
    pbs = sorted(d["produktbereiche"], key=lambda p: ((p["ergebnis"]["plan"].get(ref["jahr"]) or {"betrag": 0})["betrag"], p["pb"]))
    ueberschuss = sorted((p for p in pbs if (p["ergebnis"]["plan"].get(ref["jahr"]) or {"betrag": 0})["betrag"] > 0),
                         key=lambda p: p["pb"])
    def tabelle(k, anker, titel, summe_text):
        zeilen = [f'        <tr{f' id="{anker}-{p["pb"]}"' if anker else ""}><th scope="row">{escape(p["pb"])} {escape(p["name"])}</th>'
                  + "".join(_td(_zelle_ew(p[k][art].get(j), art, j), t) for art, j, t in spalten) + "</tr>"
                  for p in pbs]
        summe = "".join(_td(f'{_mio_v(a[k])}<br><small>{_je_ew(a[k], a["art"], a["jahr"])}</small>', a["titel"]) for a in reversed(ansichten))
        return (f'    <table class="hh-tabelle">\n      <caption>{escape(titel)}</caption>\n'
                f'      <thead><tr><th scope="col">Produktbereich</th>{kopf}</tr></thead>\n      <tbody>\n'
                + "\n".join(zeilen) + f'\n        <tr class="hh-summe"><th scope="row">{summe_text}</th>{summe}</tr>\n      </tbody>\n    </table>')
    ew_plan = EINWOHNER[max(EINWOHNER)]
    ew = lambda n: f"{n:,}".replace(",", ".")
    ist = [a["jahr"] for a in reversed(ansichten) if a["art"] == "ist"]
    ew_ist = " und ".join(f"{ew(einwohner('ist', j))} (31.12.{j})" for j in ist)
    namen = ", ".join(f'{p["pb"]} {escape(p["name"])}' for p in ueberschuss)
    return f"""    <h2 id="ergebnis">Erträge und Ergebnis</h2>
    <p>Ein Produktbereich hat Erträge, etwa Gebühren, Zuweisungen und Steuern, und Aufwendungen. Das Ergebnis ist die Differenz. Ist es negativ, nennt die Stadt es Zuschussbedarf: Diesen Teil der Aufwendungen decken Erträge anderer Bereiche, vor allem die Steuern im Produktbereich 16.</p>
    <figure class="hh-erg">{treemap_zuschuss(d, ref, "breit")}{treemap_zuschuss(d, ref, "hoch")}
      <figcaption>Zuschussbedarf je Produktbereich, {escape(ref["titel"])}. Jede Fläche ist ein Produktbereich mit negativem Ergebnis; ein Klick führt zur Zeile der Tabelle. Einen Überschuss haben {namen}; sie stehen nur in der Tabelle.</figcaption>
    </figure>
    {legende("am Zuschussbedarf")}
{tabelle("ergebnis", "erg", "Ordentliches Ergebnis vor internen Leistungen (Zeile 18); negativ heißt Zuschussbedarf, positiv Überschuss", "Zusammen (ordentliches Ergebnis)")}
{tabelle("ertrag", None, "Ordentliche Erträge (Zeile 10)", "Zusammen")}
    <p class="meta">Je Einwohner ist abgeleitet: Betrag geteilt durch die Einwohnerzahl laut IT.NRW, für das Ist {ew_ist}, für den Plan der jüngste Stand {ew(ew_plan)} (31.12.{max(EINWOHNER)}). Die Haushaltssatzung nennt mit der Fortschreibung der Stadt 340.226 Einwohner (31.12.2024); damit wären die Werte je Einwohner rund 5 % kleiner. Bei Steuern und Transfers an bestimmte Gruppen ist „je Einwohner“ keine Last je Person.</p>"""


def _td(inhalt, spalte):
    """Zelle mit Spaltennamen für das Telefon, wo die Tabellen zu Listen werden (page.css, td[data-l]::before)."""
    return f'<td data-l="{escape(spalte)}">{inhalt}</td>'


def _delta(neu, alt):
    """Veränderung in Mio. € mit Vorzeichen und, bei einem Ausgangswert über 0 €, in Prozent."""
    if not neu or not alt:
        return "–"
    diff = neu["betrag"] - alt["betrag"]
    text = ("+" if diff > 0 else "") + _betrag(diff).replace("-", "−")
    if alt["betrag"] > 0:
        text += "<br><small>" + ("+" if diff > 0 else "") + _prozent(100 * diff / alt["betrag"]).replace("-", "−") + "</small>"
    return text


def _summe(pbs, wert):
    werte = [wert(p) for p in pbs]
    return {"betrag": sum(w["betrag"] for w in werte if w)} if any(werte) else None


def veraenderung(d):
    """Abschnitt „Veränderung“: ordentliche Aufwendungen (Zeile 17) nur zwischen gleichartigen Werten."""
    pbs = d["produktbereiche"]
    plan = sorted({j for p in pbs for j in p["plan"]})[-2:]
    paare = [("Ist 2024 zu Ist 2023", lambda p: p["ist"].get(2024), lambda p: p["ist"].get(2023)),
             ("Ist 2024 zum Ansatz 2024", lambda p: p["ist"].get(2024), lambda p: p["plan"].get(2024)),
             (f"Plan {plan[1]} zu Plan {plan[0]}", lambda p: p["plan"].get(plan[1]), lambda p: p["plan"].get(plan[0]))]
    kopf = "".join(f'<th scope="col">{t}</th>' for t, *_ in paare)
    zeilen = "\n".join(f'        <tr><th scope="row">{escape(p["pb"])} {escape(p["name"])}</th>'
                       + "".join(_td(_delta(neu(p), alt(p)), t) for t, neu, alt in paare) + "</tr>" for p in pbs)
    summe = "".join(_td(_delta(_summe(pbs, neu), _summe(pbs, alt)), t) for t, neu, alt in paare)
    fort = d["erweiterung"]["fortgeschrieben"]
    satzung = _summe(pbs, lambda p: p["plan"].get(2024))
    return f"""    <h2 id="veraenderung">Veränderung</h2>
    <p>Wie haben sich die ordentlichen Aufwendungen (Zeile 17) verändert? Verglichen werden nur Werte gleicher Art: Ist mit Ist, Plan mit Plan und das Ist 2024 mit dem Ansatz, den die Haushaltssatzung für 2024 vorsah.</p>
    <table class="hh-tabelle">
      <caption>Veränderung der ordentlichen Aufwendungen in Mio. €, darunter in Prozent</caption>
      <thead><tr><th scope="col">Produktbereich</th>{kopf}</tr></thead>
      <tbody>
{zeilen}
        <tr class="hh-summe"><th scope="row">Zusammen</th>{summe}</tr>
      </tbody>
    </table>
    <p class="meta">Abgeleitet aus den Beträgen oben. Alle Werte sind nominal, ohne Ausgleich der Preissteigerung. Der Ansatz 2024 ist der Betrag der Satzung (Haushaltsplan 2023/2024, zusammen {escape(_mio(satzung["betrag"]))}); der Jahresabschluss nennt einen fortgeschriebenen Ansatz mit Übertragungen aus dem Vorjahr ({escape(_mio(fort))}). Umgliederungen zwischen Produktbereichen und der globale Minderaufwand können Veränderungen einzelner Bereiche erklären, die keine Änderung der Aufgabe sind. Ohne Prozent, wenn der Ausgangswert 0 € oder negativ ist.</p>"""


def investitionen(d):
    """Abschnitt „Investitionen“: Auszahlungen (Zeile 13) und davon Finanzanlagen (Zeile 10) je Produktbereich, dazu
    die Summen der Stadt mit Einzahlungen und Saldo."""
    inv = d["erweiterung"]["investitionen"]
    plan = sorted({j for z in inv.values() for (art, j) in z[13] if art == "plan"})[-2:]
    spalten = [("ist", 2023, "Ist 2023"), ("ist", 2024, "Ist 2024"), *[("plan", j, f"Plan {j}") for j in plan]]
    pbs = [p for p in d["produktbereiche"] if inv[p["pb"]][13]]
    ohne = [p for p in pbs if ("ist", 2024) not in inv[p["pb"]][13]]
    def zelle(pb, art, j):
        aus, fin = inv[pb][13].get((art, j)), inv[pb][10].get((art, j))
        if not aus:
            return "–"
        text = _betrag(aus["betrag"]).replace("-", "−")
        if fin and fin["betrag"]:
            text += f'<br><small>davon Finanzanlagen {_betrag(fin["betrag"]).replace("-", "−")}</small>'
        url = d["ausgaben"][aus["ausgabe"]]["dateien"][pb]
        return text + f'<br><small><a href="{escape(url)}#page={aus["seite"]}">{escape(_quelle(aus["ausgabe"]))}, S. {aus["seite"]}</a></small>'
    kopf = "".join(f'<th scope="col">{t}</th>' for *_, t in spalten)
    zeilen = "\n".join(f'        <tr><th scope="row">{escape(p["pb"])} {escape(p["name"])}</th>'
                       + "".join(_td(zelle(p['pb'], art, j), t) for art, j, t in spalten) + "</tr>" for p in pbs)
    gesamt_spalten = spalten[:2] + [("plan", 2024, "Ansatz 2024")] + spalten[2:]
    def summe(nr, art, j):
        werte = [z[nr].get((art, j)) for z in inv.values()]
        return _mio_v(sum(w["betrag"] for w in werte if w)) if any(werte) else "–"
    gkopf = "".join(f'<th scope="col">{t}</th>' for *_, t in gesamt_spalten)
    gzeilen = "\n".join(f'        <tr><th scope="row">{name}</th>' + "".join(_td(summe(nr, art, j), t) for art, j, t in gesamt_spalten) + "</tr>"
                        for nr, name in ((6, "Investive Einzahlungen (Zeile 6)"), (13, "Investive Auszahlungen (Zeile 13)"),
                                         (10, "davon Finanzanlagen (Zeile 10)"), (14, "Saldo (Zeile 14)")))
    ohne_text = ", ".join(f'{p["pb"]} {escape(p["name"])}' for p in ohne)
    return f"""    <h2 id="investitionen">Investitionen</h2>
    <p>Investitionen sind Auszahlungen für Grundstücke, Gebäude, Bauten, Ausstattung und Beteiligungen. Sie stehen nicht in den ordentlichen Aufwendungen, sondern in den Teilfinanzplänen. Einzahlungen, etwa Fördermittel, mindern den Betrag, den die Stadt selbst aufbringt.</p>
    <table class="hh-tabelle">
      <caption>Investitionen der Stadt Bonn in Mio. €</caption>
      <thead><tr><th scope="col">Summe aller Produktbereiche</th>{gkopf}</tr></thead>
      <tbody>
{gzeilen}
      </tbody>
    </table>
    <table class="hh-tabelle">
      <caption>Investive Auszahlungen je Produktbereich in Mio. € (Zeile 13), darunter der Anteil für Finanzanlagen (Zeile 10)</caption>
      <thead><tr><th scope="col">Produktbereich</th>{kopf}</tr></thead>
      <tbody>
{zeilen}
      </tbody>
    </table>
    <p class="meta">Das Ist liegt oft deutlich unter dem Ansatz, weil Maßnahmen später beginnen oder länger dauern; nicht verbrauchte Mittel kann die Stadt in das Folgejahr übertragen. Finanzanlagen sind Auszahlungen etwa für Beteiligungen und Ausleihungen; die größten Beträge stehen bei den Produktgruppen 1.01.29 Gebäudemanagement (SGB) und 1.16.04 Forderungsverwaltung. Die Bauten des Städtischen Gebäudemanagements stehen in seinem eigenen Wirtschaftsplan. Verpflichtungsermächtigungen und die Finanzplanung ab 2027 sind nicht übernommen.{f" Ohne Teilfinanzrechnung im Jahresabschluss 2024: {ohne_text}." if ohne else ""}</p>"""


def treemap_gruppen(p, ansicht, format_):
    """SVG der Produktgruppen eines Produktbereichs in einer Ansicht; Produktgruppen mit 0 € oder negativem Wert haben
    keine Fläche (nur in der Tabelle). Anteile an Zeile 17 des Produktbereichs."""
    a = ansicht
    gesamt = p[a["art"]].get(a["jahr"])
    if not gesamt:
        return ""
    items = sorted(((g, g[a["art"]][a["jahr"]]["betrag"]) for g in p["produktgruppen"]
                    if a["jahr"] in g[a["art"]] and g[a["art"]][a["jahr"]]["betrag"] > 0), key=lambda x: (-x[1], x[0]["nr"]))
    flaechen = [(b, _anker(g["nr"]), f'{g["nr"]} {g["name"]}: {_betrag(b)}, {_prozent(100 * b / gesamt["betrag"])} ({a["titel"]})',
                 g["name"], g["nr"], _betrag(b), 100 * b / gesamt["betrag"]) for g, b in items]
    return _svg_gruppen(flaechen, format_, f'{a["titel"]}: Produktgruppen im Produktbereich {p["pb"]} {p["name"]}, '
                                           f'zusammen {_mio(gesamt["betrag"])}')


def _balken(arten, ansichten, betraege=False, marke="f", klasse=""):
    """Gestapelter Balken der Aufwandsarten je Ansicht (HTML, Breite anteilig an der Summe der positiven Werte). Die
    Tabelle darunter nennt dieselben Werte; der Balken ist für Vorleseprogramme ausgeblendet. Mit betraege trägt jedes
    Stück seinen Betrag (data-b), aus dem site/haushalt.js die Kacheln der Ebene 3 zeichnet."""
    out = []
    for k, a in enumerate(ansichten):
        werte = [(t["zeile"], t[a["art"]][a["jahr"]]["betrag"]) for t in arten if a["jahr"] in t[a["art"]]]
        positiv = sum(b for _, b in werte if b > 0)
        teile = "".join(f'<i class="hh-{marke}{nr}" style="width:{100 * b / positiv:.1f}%"{f' data-b="{b}"' if betraege else ""}></i>'
                        for nr, b in werte
                        if positiv and 100 * b / positiv >= 0.05)   # unter 0,05 % unsichtbar
        out.append(f'<div class="hh-ansicht hh-v{k} hh-balken{klasse}" aria-hidden="true">{teile}</div>')
    return "".join(out)


def _zelle(x):
    return f'{_mio(x["betrag"])}<br><small>{escape(_quelle(x["ausgabe"]))}, S. {x["seite"]}</small>' if x else "–"


def _zelle_art(x):
    if not x:
        return "–"
    if x["leer"]:
        return "leer"
    if x["betrag"] < 0:
        return f'{_euro(x["betrag"])}<br><small>negativ, ohne Fläche</small>'
    return _betrag(x["betrag"])


def _fundstelle(d, pb, werte, datei=False, ausgabe=None):
    """Links auf die Seiten im PDF; aus der Ausgabe `ausgabe` (im Spaltenkopf genannt) nur die Seite."""
    orte = sorted({(x["ausgabe"], x["datei"], x["seite"]) for x in werte if x})
    return "; ".join(f'<a href="{escape(d["ausgaben"][a]["dateien"][pb])}#page={s}">'
                     + (f"S. {s}" if a == ausgabe else f'{escape(_quelle(a))}{", " + escape(f) if datei else ""}, S. {s}')
                     + "</a>" for a, f, s in orte)


def _negativ(name, spalten, werte):
    return [f'{escape(name)} im {titel} ({_euro(x["betrag"])})' for (_, _, titel), x in zip(spalten, werte) if x and x["betrag"] < 0]


def _mit_werten(g, ansichten):
    """Produktgruppe mit einem Betrag ungleich 0 in einer Ansicht (sonst ohne Ebene 3, nur in der Tabelle)."""
    return any(x.get(a["jahr"]) and x[a["jahr"]]["betrag"] for t in [g, *g["aufwandsarten"]] for a in ansichten
               for x in [t[a["art"]]])


def _pfad(*teile):
    """Brotkrumen: Links auf die übergeordneten Ebenen, die aktuelle Ebene als Text."""
    *links, aktuell = teile
    return ('<nav class="hh-pfad" aria-label="Ebenen des Haushalts">'
            + "".join(f'<a href="#{ziel}">{escape(text)}</a> › ' for ziel, text in links)
            + f'<span aria-current="location">{escape(aktuell)}</span></nav>')


ERTRAG_TEXT = ("Erträge nach ihrer Art, etwa Steuern, Zuwendungen oder Gebühren (öffentlich-rechtliche "
               "Leistungsentgelte); zusammen ergeben sie die ordentlichen Erträge (Zeile 10).")


def ertragsarten(t, ansichten, spalten, ref, tabelle, anteil_spalte=True):
    """Unterabschnitt „Woher kommt das Geld?“ einer Ebene: Balken (Klasse hh-eb, ohne Kacheln) und Tabelle der
    Ertragsarten; Zeilen ohne Betrag in allen Ansichten nur als Liste darunter. Leer ohne Ertragsarten."""
    if not t.get("ertragsarten"):
        return "", []
    summe = t["ertrag"]
    ref_summe = summe["plan"].get(ref["jahr"])
    anteil = lambda x: _prozent(100 * x["betrag"] / ref_summe["betrag"]) if x and x["betrag"] > 0 and ref_summe and ref_summe["betrag"] > 0 else "–"
    zeilen, negativ, ohne, werte_alle = [], [], [], []
    for e in t["ertragsarten"]:
        werte = [e[art].get(j) for art, j, _ in spalten]
        if not any(x and x["betrag"] for x in werte):
            ohne.append(e["name"])
            continue
        werte_alle += werte
        negativ += _negativ(e["name"], spalten, werte)
        zeilen.append(f'<tr class="hh-e{e["zeile"]}"><th scope="row">{escape(e["name"])}</th>'
                      + "".join(f"<td>{_zelle_art(x)}</td>" for x in werte)
                      + (f"<td>{anteil(e['plan'].get(ref['jahr']))}</td>" if anteil_spalte else "") + "</tr>")
    werte_summe = [summe[art].get(j) for art, j, _ in spalten]
    zeilen.append('<tr class="hh-summe"><th scope="row">Ordentliche Erträge (Zeile 10)</th>'
                  + "".join(f"<td>{_zelle_art(x)}</td>" for x in werte_summe)
                  + ("<td>100,0 %</td>" if anteil_spalte and ref_summe and ref_summe["betrag"] > 0 else "<td>–</td>" if anteil_spalte else "") + "</tr>")
    kopf = "".join(f'<th scope="col">{escape(x)}</th>' for *_, x in spalten)
    kopf += f'<th scope="col">Anteil {escape(ref["titel"])}</th>' if anteil_spalte else ""
    hinweis = [f'Ohne Betrag in allen Ansichten: {", ".join(escape(n) for n in ohne)}.'] if ohne else []
    if negativ:
        hinweis.append(f'Negativ sind: {"; ".join(negativ)}.')
    html = f"""
          <h3>Woher kommt das Geld? Ertragsarten</h3>
          <p class="meta">{ERTRAG_TEXT}</p>
          {_balken([e for e in t["ertragsarten"] if e["name"] not in ohne], ansichten, marke="e", klasse=" hh-eb")}
          <table class="hh-tabelle {tabelle}">
            <thead><tr><th scope="col">Ertragsart</th>{kopf}</tr></thead>
            <tbody>{"".join(zeilen)}</tbody>
          </table>{f'<p class="meta">{" ".join(hinweis)}</p>' if hinweis else ""}"""
    return html, werte_alle + werte_summe


def zoom(d, p):
    """Ebene 2, Abschnitt #zoom-XX: Treemap der Produktgruppen je Ansicht, Aufwandsarten des Produktbereichs als Balken
    und Tabelle, Tabelle der Produktgruppen mit Fundstelle."""
    pb, ansichten, neu = p["pb"], d["ansichten"], _plan_ausgaben(d)[-1]
    ref = ansichten[0]
    spalten = [(a["art"], a["jahr"], a["titel"]) for a in reversed(ansichten)]
    kopf = "".join(f'<th scope="col">{escape(t)}</th>' for *_, t in spalten)
    karten = "".join(f'<figure class="hh-ansicht hh-v{k}">{treemap_gruppen(p, a, "breit")}{treemap_gruppen(p, a, "hoch")}</figure>'
                     for k, a in enumerate(ansichten))
    summe_ref = p["plan"].get(ref["jahr"])
    anteil = lambda x: _prozent(100 * x["betrag"] / summe_ref["betrag"]) if x and x["betrag"] > 0 and summe_ref else "–"
    zelle = lambda inhalt: f'<td>{inhalt}</td>'   # Spaltennamen auf dem Telefon über stil()
    summe = [p[art].get(j) for art, j, _ in spalten]
    summenzeile = ('<tr class="hh-summe"><th scope="row">Ordentliche Aufwendungen (Zeile 17)</th>'
                   + "".join(zelle(_mio(x["betrag"]) if x else "–") for x in summe)
                   + zelle("100,0 %"))
    # Aufwandsarten des Produktbereichs
    arten, negativ = [], []
    for t in p["aufwandsarten"]:
        werte = [t[art].get(j) for art, j, _ in spalten]
        negativ += _negativ(t["name"], spalten, werte)
        arten.append(f'<tr class="hh-z{t["zeile"]}"><th scope="row">{escape(t["name"])}</th>'
                     + "".join(zelle(_zelle_art(x)) for x in werte)
                     + zelle(anteil(t["plan"].get(ref["jahr"]))) + "</tr>")
    # Produktgruppen
    gruppen = []
    for g in p["produktgruppen"]:
        werte = [g[art].get(j) for art, j, _ in spalten]
        negativ += _negativ(f'{g["nr"]} {g["name"]}', spalten, werte)
        name = f'<a href="#{_anker(g["nr"])}">{escape(g["name"])}</a>' if _mit_werten(g, ansichten) else escape(g["name"])
        zusatz = "".join(f'<br><small>Name in Haushaltsplan {escape(a)}: {escape(n)}</small>' for a, n in g["alt"])
        gruppen.append(f'<tr><th scope="row">{escape(g["nr"])} {name}'
                       + (f'<br><small>{escape(g["einheit"])}</small>' if g["einheit"] else "") + zusatz + "</th>"
                       + "".join(zelle(_zelle_art(x)) for x in werte)
                       + zelle(anteil(g["plan"].get(ref["jahr"])))
                       + zelle(_fundstelle(d, pb, werte, ausgabe=neu)) + "</tr>")
    hinweise = [f'Negativ sind: {"; ".join(negativ)}.'] if negativ else []
    hinweise.append(BEGRIFFE)
    t_ = f"zoom-{pb}-t"
    return f"""        <section id="zoom-{pb}" class="hh-ebene" aria-labelledby="{t_}">
          {_pfad(("produktbereiche", "Alle Produktbereiche"), f'{pb} {p["name"]}')}
          <h2 id="{t_}">Produktbereich {escape(pb)} {escape(p["name"])}</h2>
          <p class="meta">Jede Fläche ist eine Produktgruppe; ein Klick zeigt ihre Aufwandsarten.</p>
          {karten}
          {legende("am Produktbereich")}
          <h3>Aufwandsarten des Produktbereichs</h3>
          {_balken(p["aufwandsarten"], ansichten)}
          <table class="hh-tabelle hh-zoom-tabelle">
            <thead><tr><th scope="col">Aufwandsart</th>{kopf}<th scope="col">Anteil {escape(ref["titel"])}</th></tr></thead>
            <tbody>{"".join(arten)}{summenzeile}</tr></tbody>
          </table>{ertragsarten({**p, "ertrag": p["ertrag"]}, ansichten, spalten, ref, "hh-zoom-tabelle")[0]}
          <h3>Produktgruppen</h3>
          <table class="hh-tabelle hh-zoom-tabelle">
            <thead><tr><th scope="col">Produktgruppe</th>{kopf}<th scope="col">Anteil {escape(ref["titel"])}</th><th scope="col">Seite im Haushaltsplan {escape(neu)}</th></tr></thead>
            <tbody>{"".join(gruppen)}{summenzeile}{zelle(_fundstelle(d, pb, summe, ausgabe=neu))}</tr></tbody>
          </table>
          <p class="meta">{" ".join(hinweise)}</p>
        </section>"""


def gruppe(d, p, g):
    """Ebene 3, Abschnitt #pg-1-XX-YY: Aufwandsarten einer Produktgruppe als Balken je Ansicht und Tabelle; mit Skript
    zeichnet site/haushalt.js aus den Balken Kacheln (keine Treemap im HTML, damit die Seite klein bleibt)."""
    ansichten = d["ansichten"]
    spalten = [(a["art"], a["jahr"], a["titel"]) for a in reversed(ansichten)]
    zeilen, negativ, alle = [], [], []
    for t in g["aufwandsarten"]:
        werte = [t[art].get(j) for art, j, _ in spalten]
        negativ += _negativ(t["name"], spalten, werte)
        alle += werte
        zeilen.append(f'<tr class="hh-z{t["zeile"]}"><th scope="row">{escape(t["name"])}</th>'
                      + "".join(f"<td>{_zelle_art(x)}</td>" for x in werte) + "</tr>")
    summe = [g[art].get(j) for art, j, _ in spalten]
    zeilen.append('<tr class="hh-summe"><th scope="row">Ordentliche Aufwendungen (Zeile 17)</th>'
                  + "".join(f"<td>{_zelle_art(x)}</td>" for x in summe) + "</tr>")
    kopf = "".join(f'<th scope="col">{escape(t)}</th>' for *_, t in spalten)
    angaben = [escape(g["einheit"])] if g["einheit"] else []
    angaben += [f"Name in Haushaltsplan {escape(a)}: {escape(n)}" for a, n in g["alt"]]
    hinweis = f' Negativ sind: {"; ".join(negativ)}.' if negativ else ""
    ertrag_html, ertrag_werte = ertragsarten(g, ansichten, spalten, ansichten[0], "hh-pg-tabelle", anteil_spalte=False)
    t_ = f"{_anker(g['nr'])}-t"
    return f"""        <section id="{_anker(g["nr"])}" class="hh-ebene hh-pg" aria-labelledby="{t_}">
          {_pfad(("produktbereiche", "Alle Produktbereiche"), (f"zoom-{p['pb']}", f'{p["pb"]} {p["name"]}'), f'{g["nr"]} {g["name"]}')}
          <h2 id="{t_}">Produktgruppe {escape(g["nr"])} {escape(g["name"])}</h2>
          {f'<p class="meta">{" · ".join(angaben)}</p>' if angaben else ""}
          {_balken(g["aufwandsarten"], ansichten, betraege=True)}
          <table class="hh-tabelle hh-pg-tabelle"><thead><tr><th scope="col">Aufwandsart</th>{kopf}</tr></thead><tbody>{"".join(zeilen)}</tbody></table>{ertrag_html}
          <p class="meta">Fundstelle: {_fundstelle(d, p["pb"], alle + summe + ertrag_werte, datei=True)}.{hinweis}</p>
        </section>"""


def body(d, root):
    ansichten = d["ansichten"]
    wahl = "\n".join(
        f'      <input type="radio" name="hh-ansicht" id="hh-{a["key"]}" class="hh-radio"{" checked" if k == 0 else ""}>'
        f'<label for="hh-{a["key"]}">{escape(a["titel"])} <small>{escape(_mio(a["summe"]))}</small></label>'
        for k, a in enumerate(ansichten))
    karten = "\n".join(f'          <figure class="hh-ansicht hh-v{k}">{treemap(d, a, "breit")}{treemap(d, a, "hoch")}</figure>'
                       for k, a in enumerate(ansichten))
    ebenen = []
    if d.get("zoom"):
        for p in d["produktbereiche"]:
            ebenen.append(zoom(d, p))
            ebenen += [gruppe(d, p, g) for g in p["produktgruppen"] if _mit_werten(g, ansichten)]
    ref = ansichten[0]
    pbs = sorted(d["produktbereiche"], key=lambda p: (-(p["plan"].get(ref["jahr"]) or {"betrag": 0})["betrag"], p["pb"]))
    spalten = [(a["art"], a["jahr"], a["titel"]) for a in reversed(ansichten)]
    def zeile(p):
        thema = (f'<br><small>Themenseite <a href="{root}{p["thema"]["pfad"]}">{escape(p["thema"]["titel"])}</a></small>'
                 if p.get("thema") else "")
        tiefer = f'<br><small><a href="#zoom-{p["pb"]}">Produktgruppen und Aufwandsarten</a></small>' if d.get("zoom") else ""
        anteil = p["plan"].get(ref["jahr"])
        quelle = next((d["ausgaben"][a]["dateien"][p["pb"]] for a in reversed(_plan_ausgaben(d)) if p["pb"] in d["ausgaben"][a]["dateien"]), None)
        name = f'<a href="{escape(quelle)}">{escape(p["name"])}</a>' if quelle else escape(p["name"])
        return (f'        <tr id="pb-{p["pb"]}"><th scope="row">{escape(p["pb"])} {name}{thema}{tiefer}</th>'
                + "".join(_td(_zelle(p[art].get(j)), t) for art, j, t in spalten)
                + _td(_prozent(100 * anteil["betrag"] / ref["summe"]) if anteil else "–", f'Anteil {ref["titel"]}') + "</tr>")
    kopf = "".join(f'<th scope="col">{escape(t)}</th>' for *_, t in spalten)
    summe = "".join(_td(escape(_mio(a['summe'])), a["titel"]) for a in reversed(ansichten))
    mit_thema = [p for p in d["produktbereiche"] if p.get("thema")]
    themen = ", ".join(f'<a href="{root}{p["thema"]["pfad"]}">{escape(p["thema"]["titel"])}</a> ({p["pb"]})'
                       for p in mit_thema)
    zahl = ZAHLWORT.get(len(mit_thema), str(len(mit_thema)))
    dateien = ", ".join(f'<a href="{escape(d["ausgaben"][a]["seite"])}">{escape(_quelle(a))}</a>' for a in _plan_ausgaben(d) + ([JA] if JA in d["ausgaben"] else []))
    ist_quelle = (" laut Haushaltsplan, für 2024 laut festgestelltem Jahresabschluss" if d.get("erweiterung")
                  else " laut Haushaltsplan")
    mit_er = any(p.get("ertragsarten") for p in d["produktbereiche"])
    ertrag_grenze = ("Ertragsarten stehen je Produktbereich und Produktgruppe; einzelne Steuern, Gebühren oder Zuweisungen "
                     "zeigt die Seite nicht." if mit_er else
                     "Erträge und Ergebnis stehen nur je Produktbereich, ohne Aufteilung nach Ertragsarten und Produktgruppen.")
    invest_grenze = ("Investitionen stehen nur je Produktbereich, ohne einzelne Maßnahmen und ohne Verpflichtungsermächtigungen."
                     if d.get("erweiterung") else "Investitionen stehen getrennt in den Teilfinanzplänen.")
    abweichung = ("" if not d.get("erweiterung") else
                  "\n        <li><strong>Abweichungen im Jahresabschluss:</strong> Zwei Summen im Jahresabschluss 2024 weichen von "
                  "der Summe ihrer Teile ab: in der Gesamtergebnisrechnung der fortgeschriebene Ansatz des Personalaufwands um "
                  "28.806,75 € (S. 186), in der Gesamtfinanzrechnung die Auszahlungen für Baumaßnahmen um 10.000 € (S. 6). "
                  "Die Seite übernimmt die Werte der Produktbereiche.</li>")
    if d.get("zoom"):
        klick = ("Ein Klick auf eine Fläche zeigt ihre Unterteilung: erst die Produktgruppen, dann die Aufwandsarten. "
                 "Die Flächen zeigen Anteile, keine Bewertung.")
        umfang = ("Die Seite zeigt drei Ebenen: Produktbereiche, Produktgruppen und je Bereich und Gruppe die sechs "
                  "Aufwandsarten. Produkte und Konten enthalten die Haushaltspläne nicht.")
        pruefung = (" Je Produktbereich und Spalte ergeben die Produktgruppen und die Aufwandsarten (Zeilen 11–16) die "
                    "ordentlichen Aufwendungen, ebenso je Produktgruppe; leere Zellen zählen als 0. Ein Prüfbogen mit 33 "
                    "Zellen wurde mit einem zweiten Leseweg gegengeprüft (KI-gestützt, 33 von 33 gleich) und vor der "
                    "Veröffentlichung freigegeben."
                    + (" Für das Ist 2024 und die Investitionen gilt dasselbe mit zwei Prüfbögen mit zusammen 44 Zellen "
                       "(44 von 44 gleich, freigegeben 03.11.2026); die Prüfsummen von Jahresabschluss und Teilfinanzplänen "
                       "gehen bis auf die zwei unter „Was diese Seite nicht zeigt“ genannten Abweichungen auf."
                       if d.get("erweiterung") else ""))
        begriffe = f"""
        <dt>Ebenen</dt><dd>Produktbereich, Produktgruppe, Aufwandsart. Die Produktgruppen eines Bereichs ergeben zusammen seine ordentlichen Aufwendungen, ebenso seine sechs Aufwandsarten.</dd>
        <dt>Aufwandsarten</dt><dd>{HINWEIS}</dd>
        <dt>„leer“ und 0 €</dt><dd>Eine leere Zelle im Haushaltsplan zählt als 0 €. Produktgruppen mit 0 € in einer Ansicht haben keine Fläche und stehen nur in der Tabelle.</dd>
        <dt>Negative Werte</dt><dd>Sie kommen nur im Ist vor und haben keine Fläche; die übrigen Flächen zeigen dann zusammen etwas mehr als die Summe.</dd>"""
    else:
        klick = "Ein Klick auf eine Fläche führt zur Zeile in der Tabelle. Die Flächen zeigen Anteile, keine Bewertung."
        umfang = "Die Seite zeigt eine Ebene, die 17 Produktbereiche. Produktgruppen, Produkte und Konten stehen in den Haushaltsplänen."
        pruefung = begriffe = ""
    return f"""    <h1>Haushalt auf einen Blick</h1>
    <p class="lead">Wofür plant die Stadt Bonn Geld ein? Jede Fläche ist ein Produktbereich des Haushalts; je größer die Fläche, desto höher die ordentlichen Aufwendungen.</p>
    <details class="hh-mehr" id="lesen">
      <summary>So lesen Sie die Zahlen</summary>
      <dl>
        <dt>Betrag</dt><dd>Ordentliche Aufwendungen (Zeile 17 der Teilergebnispläne), nominal in Mio. €, ohne Investitionen.</dd>
        <dt>Plan und Ist</dt><dd>Plan ist der Ansatz, also der Betrag, den der Haushaltsplan für das Jahr vorsieht; Ist ist das Ergebnis{ist_quelle}. Beide weichen oft voneinander ab. <a href="{root}begriffe/#haushalt">Weitere Begriffe</a></dd>{begriffe}
        <dt>Farben</dt><dd>Je dunkler eine Fläche, desto größer ihr Anteil an der Summe der Ansicht (Produktbereiche) oder am Produktbereich (Produktgruppen), in fünf Stufen. Die Aufwandsarten haben je eine eigene Farbe.</dd>
        <dt>Ergebnis</dt><dd>Ordentliche Erträge minus ordentliche Aufwendungen (Zeile 18), vor internen Leistungen. Negativ heißt Zuschussbedarf, positiv Überschuss.</dd>
        <dt>Produktbereich 16</dt><dd>Allgemeine Finanzwirtschaft: Hier stehen die Steuern und allgemeinen Zuweisungen. Sein Überschuss zeigt vor allem, wie der Haushalt finanziert wird, nicht eine Aufgabe.</dd>
        <dt>Interne Leistungen</dt><dd>Leistungen, die Bereiche der Verwaltung untereinander verrechnen, etwa für Gebäude oder Personalverwaltung. Sie verschieben Beträge zwischen den Produktbereichen und sind im Ergebnis hier nicht enthalten.</dd>
        <dt>Je Einwohner</dt><dd>Abgeleitet: Betrag geteilt durch die Einwohnerzahl laut IT.NRW (Angaben unter der Tabelle „Erträge und Ergebnis“).</dd>
        <dt>Themenseiten</dt><dd>Zu {zahl} Produktbereichen gibt es eine Themenseite: {themen}.</dd>
      </dl>
    </details>
    <div class="hh-wahl" id="produktbereiche">
      <p class="hh-wahl-titel" id="hh-wahl-titel">Ansicht:</p>
{wahl}
      <div class="hh-karten">
        <div class="hh-haupt">
{karten}
          {legende("an der Summe")}
          <p class="meta">{klick}</p>
        </div>
{chr(10).join(ebenen)}
      </div>
    </div>
    <h2 id="tabelle">Alle Produktbereiche</h2>
    <p>Sortiert nach dem {escape(ref["titel"])}; der Name führt zum Teilergebnisplan (PDF).</p>
    <table class="hh-tabelle">
      <thead><tr><th scope="col">Produktbereich</th>{kopf}<th scope="col">Anteil {escape(ref["titel"])}</th></tr></thead>
      <tbody>
{chr(10).join(zeile(p) for p in pbs)}
        <tr class="hh-summe"><th scope="row">Zusammen</th>{summe}{_td("100,0 %", f'Anteil {ref["titel"]}')}</tr>
      </tbody>
    </table>
{ergebnis(d, root)}
{veraenderung(d) + chr(10) + investitionen(d) if d.get("erweiterung") else ""}
    <details class="hh-mehr">
      <summary>Was diese Seite nicht zeigt</summary>
      <ul>
        <li><strong>Einzelne Posten:</strong> {umfang}</li>
        <li><strong>Erträge und Investitionen:</strong> {ertrag_grenze} {invest_grenze}</li>{abweichung}
        <li><strong>Ausgegliederte Bereiche:</strong> Eigenbetriebe und das Städtische Gebäudemanagement haben eigene Wirtschaftspläne. Interne Leistungen, Umgliederungen und der globale Minderaufwand verschieben Summen zwischen den Bereichen.</li>
        <li><strong>Künftige Jahre:</strong> Die Finanzplanung ab 2027 ist nicht übernommen. Der Entwurf des Haushalts 2027/2028 ist noch nicht eingebracht.</li>
        <li><strong>Vorlagen:</strong> Einzelnen Vorlagen ordnet die Seite keine Beträge zu.</li>
      </ul>
    </details>
    <details class="hh-mehr">
      <summary>Quellen, Prüfung und Lizenz</summary>
      <p>Stadt Bonn, {dateien} (PDF, Teilergebnispläne{" und Teilfinanzpläne, im Jahresabschluss Teilergebnis- und Teilfinanzrechnungen" if d.get("erweiterung") else ""} je Produktbereich; Abruf {_date(d["abruf"])}{f', Jahresabschluss {_date(d["erweiterung"]["abruf_ja"])}' if d.get("erweiterung") else ""}).</p>
      <p>Ausgelesen mit pipeline/haushaltsplan.py; die Summe aller Produktbereiche trifft je Spalte den Gesamtergebnisplan.{pruefung}</p>
      <p>Lizenz: {escape(d["lizenz"])}.</p>
      <p>Einwohnerzahlen für „je Einwohner“: {EINWOHNER_QUELLE}.</p>
      <p>Gestaltung nach dem Vorbild der <a href="https://haushaltsdaten.odis-berlin.de/visualisierung/">Berliner Haushaltsdaten</a> (ODIS, Technologiestiftung Berlin).</p>
    </details>
    <p><a href="{root}thema/">Alle Themenseiten</a> · <a href="{root}">Zur Karte</a></p>"""


def stil(d):
    """Spaltennamen der Tabellen der Ebenen 2 und 3 auf dem Telefon, wo die Tabellen zu Listen werden; die Jahre kommen aus den
    Daten, daher als Stilblock der Seite statt als Attribut an jeder Zelle. Dazu das Skript für Zoom und Kacheln."""
    if not d.get("zoom"):
        return ""
    titel = [a["titel"] for a in reversed(d["ansichten"])] + [f'Anteil {d["ansichten"][0]["titel"]}', "Fundstelle"]
    regeln = " ".join(f'.page table:is(.hh-zoom-tabelle, .hh-pg-tabelle) td:nth-of-type({k})::before {{ content: "{t}: "; }}'
                      for k, t in enumerate(titel, 1))
    return (f"\n  <style>@media (max-width: 600px) {{ {regeln} }}</style>"
            f'\n  <script src="../haushalt.js" defer></script>')


def write(site, site_url, page):
    """Schreibt haushalt/index.html; gibt den Pfad für die Sitemap zurück (ohne Daten keinen)."""
    d = daten()
    if not d:
        return []
    out = site / PFAD / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site_url, PFAD, "Haushalt auf einen Blick – Ratsatlas Bonn",
                        "Ordentliche Aufwendungen, Erträge und Ergebnis der Stadt Bonn je Produktbereich: Plan und Ist "
                        "aus den Haushaltsplänen, mit Fundstelle und je Einwohner.", body(d, "../"), "../", stil(d)), encoding="utf-8")
    return [PFAD]
