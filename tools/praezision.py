"""Präzision der Geokodierung aus der von Hand beurteilten Stichprobe (CLAUDE.md 7.3: 50 Vorlagen je Methode,
Präzision im Bericht; Entscheidung 16.11.2026 (5)).

Aufruf: python tools/praezision.py <stichprobe.tsv> [--audit <audit_geokodierung.tsv>] [--tsv <ausgabe.tsv>]

Eingabe ist `stichprobe_geokodierung.tsv` aus dem Datenpaket (pipeline/export.py `_sample_methods`: je Methode bis zu
50 Vorlagen, eine Zeile je Vorlage und Methode), beurteilt im Prüfbogen `tools/pruefbogen.html` oder in einer
Tabellenkalkulation nach `explore/PRUEFREGELN_geokodierung.md`. Gelesen wird tolerant: UTF-8 mit oder ohne BOM, UTF-16
mit BOM (Unicode-Text aus Tabellenkalkulationen), sonst Windows-1252; Zeilenenden LF, CRLF oder CR; Felder in
Anführungszeichen, wie Pythons csv-Modul sie schreibt; Trennzeichen Tabulator (Semikolon oder Komma nur, wenn die
Kopfzeile keinen Tabulator hat). Pflichtspalten: „methode“ und die Spalte des Urteils (die erste, deren Kopf mit
„urteil“ beginnt); „ebene“ und „drucksache“ werden genutzt, wenn vorhanden. Urteile ohne Rücksicht auf Groß- und
Kleinschreibung und Leerraum: richtig, teilweise, falsch, unklar oder kurz r, t, f, u; leer heißt offen (noch nicht
beurteilt). Andere Werte sind ungültig: Sie werden nur mit der Zeilennummer genannt (Kopf = Zeile 1, wie in einer
Tabellenkalkulation; ganz leere Zeilen werden mitgezählt, aber nicht ausgewertet) und nicht gerechnet.

Zählung je Methode: gezogen (Zeilen), beurteilt (richtig + teilweise + falsch + unklar), die vier Urteile, offen,
ungültig; gerechnet n = richtig + teilweise + falsch. „unklar“ wird gezählt, geht aber in keine Präzision ein.
Zwei Lesarten von „teilweise“ nebeneinander: streng (Treffer x = richtig) und nachsichtig (x = richtig + teilweise);
Präzision p = x / n.

Intervall je Methode und Ebene: Wilson, 95 % (z = 1,95996):
    Mitte = (p + z²/(2n)) / (1 + z²/n),  halbe Breite = z / (1 + z²/n) · √(p(1−p)/n + z²/(4n²)).
Aufgeteilt nach Ebene nur Zeilen mit genau einer Ebene (Spalte „ebene“ ohne „;“); Zeilen mit mehreren Ebenen zählt
die Ausgabe gesondert.

Gesamt:
(a) gepoolt, ungewichtet: x und n über alle gerechneten Zeilen, Wilson-Intervall. Jede Zeile zählt gleich; weil je
    Methode höchstens 50 Vorlagen gezogen werden, sind seltene Methoden darin überrepräsentiert. Kein Schätzwert für
    alle Vorlagen.
(b) geschichtet, gewichtet (nur mit --audit): Schicht h = Methode, Umfang N_h = Vorlagen der Methode im Audit
    `audit_geokodierung.tsv` desselben Datenpakets, gezählt als verschiedene Kombinationen aus Drucksache, Datum und
    Vorlagenart (Zeilen ohne Drucksache zählen nicht). Einheit ist Vorlage × Methode: Eine Vorlage, die mehrere
    Methoden verortet haben, zählt in jeder dieser Schichten (N = Σ N_h ist daher größer als die Zahl der verorteten
    Vorlagen). Gerechnet werden die Schichten mit n_h > 0; W_h = N_h / Σ N_h über diese Schichten (ihr Anteil an allen
    N_h steht in der Ausgabe).
        p_st = Σ W_h · p_h
        Var(p_st) = Σ W_h² · (1 − f_h) · p̃_h (1 − p̃_h) / ñ_h,  f_h = n_h / N_h (Endlichkeitskorrektur, höchstens 1),
        p̃_h = (x_h + z²/2) / (n_h + z²),  ñ_h = n_h + z²  (Agresti–Coull)
        95-%-Intervall: Wilson um p_st mit dem effektiven Umfang n_eff = p̃_st (1 − p̃_st) / Var(p_st) − z²,
        p̃_st = Σ W_h · p̃_h; bei Var(p_st) = 0 (jede gerechnete Methode vollständig geprüft) nur der Punkt p_st.
    Die Agresti–Coull-Anpassung hält die Varianz auch bei p_h = 0 oder 1 über null (die übliche Schätzung
    p_h(1 − p_h)/(n_h − 1) wäre dort null und bei n_h = 1 nicht definiert); die Endlichkeitskorrektur setzt sie für
    eine vollständig geprüfte Methode (n_h = N_h) auf null. Der Schätzwert selbst nutzt das unangepasste p_h. Mit einer
    einzigen Schicht ohne Endlichkeitskorrektur ist n_eff = n und das Intervall genau das Wilson-Intervall der Methode;
    sonst ist n_eff mindestens das kleinste n_h. Vorher (bis 16.11.2026) p_st ± z·√Var (Wald-Typ): am Rand zu schmal
    (eine Schicht 50 von 50 bei N = 1000: 95,2–100 % gegen Wilson 92,9–100 %; Überdeckung 0,92 bei p = 0,95 im
    Monte-Carlo-Versuch mit Ziehen ohne Zurücklegen, mit n_eff 0,97; über elf Aufteilungen mit p von 0,5 bis 0,99
    Überdeckung 0,92–1,00 gegen 0,94–0,98).
    Grenze von N_h: Kopien einer Vorlage mit derselben Drucksache, demselben Datum und derselben Vorlagenart zählen im
    Audit als eine Vorlage, in der Stichprobe (gezogen über die Kennung der Vorlage) einzeln; dann kann N_h zu klein
    sein. Die Ausgabe nennt die Zahl der Drucksachen, die in einer Methode der Stichprobe mehrfach vorkommen.
Warnungen (kein Abbruch): Methode der Stichprobe fehlt im Audit (nicht in (b)); mehr Zeilen in der Stichprobe als
Vorlagen im Audit (n_h > N_h, Endlichkeitskorrektur dann 0); Zeilen der Stichprobe, deren Drucksache im Audit bei
dieser Methode fehlt (nur Anzahl). Beides deutet auf Stichprobe und Audit aus verschiedenen Datenständen. Ohne
--audit nur der Hinweis auf mehrfach vorkommende Drucksachen (Anzahl je Methode). Den Datenstand nennt die Ausgabe,
wenn neben der Stichprobe oder dem Audit `koeln/index.json` liegt (meta.generated_at).

Ausgabe: Markdown-Tabellen auf stdout (für den Bericht), mit --tsv dieselben Zahlen als TSV (Anteile als Dezimalzahl
mit Punkt). Nur Zahlen: keine Titel, Drucksachen, Orte, Links oder Anmerkungen; Methoden nur, wenn der Name wie eine
Methode aussieht (sonst „(Methode unlesbar)“), Ebenen nur aus der festen Liste. Nur Standardbibliothek, keine Anfrage
ins Netz, schreibt nichts außer der Datei von --tsv.
Rückgabe 0, auch mit Warnungen; 1 nur bei unbrauchbarer Eingabe (Datei fehlt oder unlesbar, Pflichtspalte fehlt)
oder wenn die Datei von --tsv nicht geschrieben werden kann.
"""
import argparse
import csv
import io
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import NormalDist

Z = NormalDist().inv_cdf(0.975)   # 1,959963984540054
URTEILE = ("richtig", "teilweise", "falsch", "unklar")
KURZ = {"r": "richtig", "t": "teilweise", "f": "falsch", "u": "unklar"}
KATEGORIEN = URTEILE + ("offen", "ungueltig")
LESARTEN = (("streng", ("richtig",)), ("nachsichtig", ("richtig", "teilweise")))
# Ebenen der Ortstabelle (pipeline/build.py, Spalte level) und ihre Namen in der Ausgabe
EBENEN = {"adresse": "Adresse (Punkt)", "strasse": "Straße", "ortsteil": "Stadtteil", "stadtbezirk": "Stadtbezirk",
          "bebauungsplan": "Bebauungsplan", "objekt": "Gebäude oder Anlage"}
METHODE = re.compile(r"[a-z][a-z0-9_+]{0,63}")   # wie die Methoden der Pipeline (etwa „strasse+hausnummer_punkt“)
UNLESBAR = "(Methode unlesbar)"
MAX_NUMMERN = 40   # Zeilennummern je Hinweis


class Unbrauchbar(Exception):
    """Eingabe, mit der sich nichts auswerten lässt (Rückgabe 1)."""


def urteil_normal(wert):
    """„richtig“, „teilweise“, „falsch“, „unklar“, „“ (offen) oder None (ungültig)."""
    w = (wert or "").strip().casefold()
    if not w:
        return ""
    w = KURZ.get(w, w)
    return w if w in URTEILE else None


# --- Lesen ---------------------------------------------------------------------------------------------------------

def _text(pfad):
    """Inhalt als Text und die erkannte Kodierung."""
    try:
        roh = Path(pfad).read_bytes()
    except FileNotFoundError:
        raise Unbrauchbar(f"Datei nicht gefunden: {pfad}") from None
    except OSError as e:
        raise Unbrauchbar(f"Datei nicht lesbar: {pfad} ({type(e).__name__})") from None
    if roh.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return roh.decode("utf-16"), "UTF-16"
        except UnicodeDecodeError:
            raise Unbrauchbar(f"Datei nicht lesbar (UTF-16 fehlerhaft): {pfad}") from None
    try:
        return roh.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        return roh.decode("cp1252", errors="replace"), "Windows-1252"


def tabelle_lesen(pfad):
    """(Kopf, [(Zeilennummer, Felder)], Kodierung); ganz leere Zeilen entfallen, zählen aber für die Nummern. Felder
    dürfen so lang sein wie die Datei (die Grenze des csv-Moduls, 131 072 Zeichen, gilt nur während des Lesens nicht)."""
    text, kodierung = _text(pfad)
    erste = text.split("\n", 1)[0]
    trenner = "\t" if "\t" in erste else ";" if ";" in erste else "," if "," in erste else "\t"
    grenze = csv.field_size_limit()
    try:
        csv.field_size_limit(max(grenze, len(text) + 1))
        datensaetze = list(csv.reader(io.StringIO(text, newline=""), delimiter=trenner))
    except (csv.Error, OverflowError):
        raise Unbrauchbar(f"Datei nicht als Tabelle lesbar: {pfad}") from None
    finally:
        csv.field_size_limit(grenze)
    if not datensaetze:
        raise Unbrauchbar(f"Datei ist leer: {pfad}")
    kopf = [k.strip().lstrip("\ufeff").strip().casefold() for k in datensaetze[0]]
    zeilen = [(i, z) for i, z in enumerate(datensaetze[1:], start=2) if any(f.strip() for f in z)]
    return kopf, zeilen, kodierung


def _spalte(kopf, name, praefix=False):
    for i, k in enumerate(kopf):
        if k == name or (praefix and k.startswith(name)):
            return i
    return None


def stichprobe_lesen(pfad):
    kopf, zeilen, kodierung = tabelle_lesen(pfad)
    sp = {"methode": _spalte(kopf, "methode"), "urteil": _spalte(kopf, "urteil", praefix=True),
          "ebene": _spalte(kopf, "ebene"), "drucksache": _spalte(kopf, "drucksache")}
    fehlt = [n for n in ("methode", "urteil") if sp[n] is None]
    if fehlt:
        raise Unbrauchbar(f"Stichprobe ohne Spalte {' und '.join('„' + n + '“' for n in fehlt)} "
                          f"(die Spalte des Urteils beginnt mit „urteil“): {pfad}")

    def feld(z, name):
        i = sp[name]
        return z[i] if i is not None and i < len(z) else ""
    return [{"nr": nr, "methode": feld(z, "methode").strip(), "urteil": feld(z, "urteil"),
             "ebene": feld(z, "ebene"), "drucksache": feld(z, "drucksache").strip()} for nr, z in zeilen], kodierung


def audit_lesen(pfad):
    """Vorlagen je Methode aus audit_geokodierung.tsv als Menge von (Drucksache, Datum, Vorlagenart); so zählen Kopien
    mit derselben Drucksache, aber anderem Datum oder anderer Vorlagenart einzeln. Zeilen ohne Drucksache entfallen;
    fehlen die Spalten „datum“ oder „vorlagenart“, zählen nur die Drucksachen. Methode, die nicht wie eine aussieht:
    „(Methode unlesbar)“."""
    kopf, zeilen, _ = tabelle_lesen(pfad)
    i, j = _spalte(kopf, "methode"), _spalte(kopf, "drucksache")
    if i is None or j is None:
        raise Unbrauchbar(f"Audit ohne Spalte „methode“ oder „drucksache“: {pfad}")
    weitere = [_spalte(kopf, "datum"), _spalte(kopf, "vorlagenart")]
    je = {}
    for _, z in zeilen:
        if max(i, j) < len(z) and z[i].strip() and z[j].strip():
            m = z[i].strip()
            schluessel = (z[j].strip(), *(z[k].strip() if k is not None and k < len(z) else "" for k in weitere))
            je.setdefault(m if METHODE.fullmatch(m) else UNLESBAR, set()).add(schluessel)
    return je


def datenstand(*pfade):
    """meta.generated_at aus koeln/index.json neben den Dateien (Datenpaket), je gefundener Datei einmal."""
    stände = []
    for pfad in pfade:
        if not pfad:
            continue
        index = Path(pfad).resolve().parent / "koeln" / "index.json"
        try:
            wert = json.loads(index.read_text(encoding="utf-8"))["meta"]["generated_at"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(wert, str) and re.fullmatch(r"[0-9T:+\-.Z ]{10,40}", wert) and wert not in stände:
            stände.append(wert)
    return stände


# --- Rechnen -------------------------------------------------------------------------------------------------------

def _wilson_p(p, n, z=Z):
    """Wilson-Intervall um den Anteil p bei (auch nicht ganzzahligem) Umfang n > 0; bei p = 0 unten genau 0, bei p = 1
    oben genau 1."""
    z2 = z * z
    nenner = 1 + z2 / n
    mitte = (p + z2 / (2 * n)) / nenner
    halb = z / nenner * math.sqrt(max(0.0, p * (1 - p)) / n + z2 / (4 * n * n))
    return (0.0 if p <= 0 else max(0.0, mitte - halb)), (1.0 if p >= 1 else min(1.0, mitte + halb))


def wilson(x, n, z=Z):
    """Wilson-Intervall (unten, oben) für x Treffer unter n; None ohne gerechnete Zeile."""
    if n <= 0:
        return None
    return _wilson_p(x / n, n, z)


def geschichtet(schichten, z=Z):
    """Geschichtete Schätzung aus [(N_h, n_h, x_h)]; Schichten mit n_h = 0 oder N_h = 0 entfallen.
    Ergebnis: p, se, n_eff (None bei Varianz 0), unten, oben (Wilson um p mit n_eff), N (gerechnete Schichten) oder
    None."""
    s = [(N, n, x) for N, n, x in schichten if n > 0 and N > 0]
    gesamt = sum(N for N, _, _ in s)
    if not gesamt:
        return None
    z2, p, p_ac, var = z * z, 0.0, 0.0, 0.0
    for N, n, x in s:
        w = N / gesamt
        p += w * x / n
        pt = (x + z2 / 2) / (n + z2)
        p_ac += w * pt
        var += w * w * max(0.0, 1 - n / N) * pt * (1 - pt) / (n + z2)
    if var <= 0:
        return {"p": p, "se": 0.0, "n_eff": None, "unten": p, "oben": p, "N": gesamt}
    n_eff = p_ac * (1 - p_ac) / var - z2
    unten, oben = _wilson_p(p, n_eff, z)
    return {"p": p, "se": math.sqrt(var), "n_eff": n_eff, "unten": unten, "oben": oben, "N": gesamt}


def _ebene(wert):
    teile = {t.strip().casefold() for t in (wert or "").split(";") if t.strip()}
    if len(teile) > 1:
        return "mehrere"
    if not teile:
        return "ohne"
    e = teile.pop()
    return e if e in EBENEN else "unbekannt"


def _lesarten(c):
    n = c["richtig"] + c["teilweise"] + c["falsch"]
    out = {"n": n}
    for name, zaehlt in LESARTEN:
        x = sum(c[k] for k in zaehlt)
        out[name] = {"x": x, "p": x / n if n else None, "ci": wilson(x, n)}
    return out


def _anzahl(n, einzahl, mehrzahl):
    """„1 Zeile“, „2 Zeilen“."""
    return f"{n} {einzahl if n == 1 else mehrzahl}"


def _nummern(nummern):
    """„Zeile 3“, „Zeilen 3, 4“, „Zeilen 3, 4, … und 5 weitere“."""
    text = ", ".join(map(str, nummern[:MAX_NUMMERN]))
    return ("Zeile " if len(nummern) == 1 else "Zeilen ") + text + (
        f" und {len(nummern) - MAX_NUMMERN} weitere" if len(nummern) > MAX_NUMMERN else "")


def auswerten(zeilen, audit=None):
    je, ebenen, mehr = {}, {}, Counter()
    ungueltig, unlesbar = [], []
    drucksachen = {}   # Methode → Zähler der Drucksachen (nur für den Hinweis auf mehrfach vorkommende)
    for z in zeilen:
        m = z["methode"] if METHODE.fullmatch(z["methode"]) else UNLESBAR
        if m == UNLESBAR:
            unlesbar.append(z["nr"])
        elif z["drucksache"]:
            drucksachen.setdefault(m, Counter())[z["drucksache"]] += 1
        u = urteil_normal(z["urteil"])
        k = "offen" if u == "" else "ungueltig" if u is None else u
        if u is None:
            ungueltig.append(z["nr"])
        je.setdefault(m, Counter())[k] += 1
        e = _ebene(z["ebene"])
        if e in EBENEN:
            ebenen.setdefault((m, e), Counter())[k] += 1
        else:
            mehr[e] += 1
    methoden = sorted(m for m in je if m != UNLESBAR) + ([UNLESBAR] if UNLESBAR in je else [])
    zeilen_m = []
    for m in methoden:
        c = je[m]
        zeilen_m.append({"methode": m, "gezogen": sum(c.values()), "beurteilt": sum(c[k] for k in URTEILE),
                         **{k: c[k] for k in KATEGORIEN}, **_lesarten(c)})
    zeilen_e = [{"methode": m, "ebene": e, "gezogen": sum(c.values()), "beurteilt": sum(c[k] for k in URTEILE),
                 **{k: c[k] for k in KATEGORIEN}, **_lesarten(c)}
                for (m, e), c in sorted(ebenen.items(), key=lambda t: (methoden.index(t[0][0]), list(EBENEN).index(t[0][1])))]
    lesbar = [r for r in zeilen_m if r["methode"] != UNLESBAR]
    summe = Counter()
    for r in lesbar:
        summe.update({k: r[k] for k in KATEGORIEN})
    e = {"methoden": zeilen_m, "ebenen": zeilen_e, "ebenen_nicht_aufgeteilt": dict(mehr), "zeilen": len(zeilen),
         "unlesbar": len(unlesbar), "summe": dict(summe), "gepoolt": _lesarten(summe), "hinweise": [],
         "geschichtet": None}
    if ungueltig:
        e["hinweise"].append(f"Ungültige Urteile (weder richtig, teilweise, falsch, unklar noch leer) in "
                             f"{_nummern(ungueltig)}: nicht gerechnet, bitte korrigieren.")
    if unlesbar:
        e["hinweise"].append(f"Methode leer oder unlesbar in {_nummern(unlesbar)}: in der Tabelle je Methode "
                             f"gesondert, nicht im Gesamtwert.")
    for m in sorted(drucksachen):
        mehrfach = sum(1 for k in drucksachen[m].values() if k > 1)
        if mehrfach:
            e["hinweise"].append(
                f"Methode `{m}`: {_anzahl(mehrfach, 'Drucksache steht', 'Drucksachen stehen')} mehr als einmal in der "
                f"Stichprobe (Kopien einer Vorlage mit derselben Drucksache); jede Zeile zählt einzeln. N_h im Audit "
                f"zählt Drucksache, Datum und Vorlagenart und kann solche Kopien zusammenfassen (dann zu klein).")
    if audit is not None:
        e["geschichtet"] = _geschichtet(lesbar, zeilen, audit, e["hinweise"])
    return e


def _geschichtet(lesbar, zeilen, audit, hinweise):
    alle = {}
    for r in lesbar:
        N = len(audit.get(r["methode"], ()))
        alle[r["methode"]] = N
        if not N:
            hinweise.append(f"Methode `{r['methode']}` steht in der Stichprobe, aber nicht im Audit: ohne Gewicht, "
                            f"nicht im geschichteten Gesamtwert.")
            continue
        if r["gezogen"] > N:
            hinweise.append(f"Methode `{r['methode']}`: mehr Zeilen in der Stichprobe ({r['gezogen']}, davon "
                            f"gerechnet {r['n']}) als Vorlagen im Audit ({N}); f_h = n_h/N_h höchstens 1 "
                            f"(Stichprobe und Audit aus verschiedenen Datenständen?).")
    im_audit = {m: {k[0] for k in schluessel} for m, schluessel in audit.items()}
    fremd = sum(1 for z in zeilen if z["drucksache"] and METHODE.fullmatch(z["methode"])
                and z["methode"] in im_audit and z["drucksache"] not in im_audit[z["methode"]])
    if fremd:
        hinweise.append(f"{_anzahl(fremd, 'Zeile', 'Zeilen')} der Stichprobe: Drucksache bei dieser Methode nicht im "
                        f"Audit (Stichprobe und Audit aus verschiedenen Datenständen?).")
    for m in sorted(set(audit) - set(alle)):
        alle[m] = len(audit[m])
    gesamt = sum(alle.values())
    zeilen_s, ergebnis = [], {}
    for m in sorted(alle):
        r = next((x for x in lesbar if x["methode"] == m), None)
        n = r["n"] if r else 0
        zeilen_s.append({"methode": m, "N": alle[m], "n": n, "in_stichprobe": r is not None,
                         **{name: (r[name]["x"] if r else 0) for name, _ in LESARTEN}})
    gerechnet = {s["methode"] for s in zeilen_s if s["n"] > 0 and s["N"] > 0}
    N_ger = sum(s["N"] for s in zeilen_s if s["methode"] in gerechnet)
    for s in zeilen_s:
        s["gewicht"] = s["N"] / N_ger if s["methode"] in gerechnet else None
    for name, _ in LESARTEN:
        ergebnis[name] = geschichtet([(s["N"], s["n"], s[name]) for s in zeilen_s])
    ohne = [s for s in zeilen_s if s["methode"] not in gerechnet and s["N"] > 0]
    if ohne:
        anteil = sum(s["N"] for s in ohne) / gesamt if gesamt else 0
        hinweise.append(f"{'Methode' if len(ohne) == 1 else 'Methoden'} ohne gerechnete Zeile (nicht im geschichteten "
                        f"Gesamtwert): {', '.join(_m(s['methode']) for s in ohne)} – zusammen "
                        f"{_anzahl(sum(s['N'] for s in ohne), 'Vorlage', 'Vorlagen')} ({_prozent(anteil)} von Σ N_h).")
    return {"schichten": zeilen_s, "N_gesamt": gesamt, "N_gerechnet": N_ger, **ergebnis}


# --- Ausgabe -------------------------------------------------------------------------------------------------------

def _prozent(p):
    return "–" if p is None else f"{100 * p:.1f}".replace(".", ",") + " %"


def _punkte(x):
    return f"{100 * x:.1f}".replace(".", ",")


def _zahl(x):
    return f"{x:.1f}".replace(".", ",")


def _intervall(ci):
    if ci is None:
        return "–"
    return f"{100 * ci[0]:.1f}–{100 * ci[1]:.1f} %".replace(".", ",")


def _kennzahlen(r):
    return [_prozent(r["streng"]["p"]), _intervall(r["streng"]["ci"]),
            _prozent(r["nachsichtig"]["p"]), _intervall(r["nachsichtig"]["ci"])]


def _m(name):
    return name if name == UNLESBAR else f"`{name}`"


def markdown(e, name="", kodierung="UTF-8", stand=()):
    s = e["summe"]
    z = ["## Präzision der Geokodierung (Prüfung von Hand)", ""]
    unlesbar = e.get("unlesbar", 0)
    z.append(f"Stichprobe{' `' + name + '`' if name else ''}: {_anzahl(e['zeilen'], 'Zeile', 'Zeilen')} (je Zeile "
             f"eine Vorlage mit einer Methode), Kodierung {kodierung}."
             + (f" Davon {_anzahl(unlesbar, 'Zeile', 'Zeilen')} mit leerer oder unlesbarer Methode (nur in der Tabelle "
                f"je Methode); in den übrigen {e['zeilen'] - unlesbar}:" if unlesbar else "")
             + f" Beurteilt {sum(s.get(k, 0) for k in URTEILE)} (davon unklar {s.get('unklar', 0)}), offen "
             f"{s.get('offen', 0)}, ungültig {s.get('ungueltig', 0)}.")
    z.append("Datenstand des Pakets (`koeln/index.json`, meta.generated_at): "
             + (", ".join(stand) if stand else "nicht ermittelt – im Bericht angeben") + ".")
    z += ["", "Lesarten: **streng** = nur „richtig“ zählt als Treffer; **nachsichtig** = „richtig“ und „teilweise“. "
          "„unklar“ wird gezählt, geht aber in keine Präzision ein; leer = offen. Intervalle: Wilson, 95 %.", ""]
    z += ["### Je Methode", "",
          "| Methode | gezogen | beurteilt | richtig | teilweise | falsch | unklar | offen | ungültig | gerechnet "
          "| streng | 95-%-Intervall | nachsichtig | 95-%-Intervall |",
          "|---|" + "---:|" * 9 + "---:|---|---:|---|"]
    for r in e["methoden"]:
        z.append("| " + " | ".join([_m(r["methode"]), *(str(r[k]) for k in ("gezogen", "beurteilt", *KATEGORIEN, "n")),
                                    *_kennzahlen(r)]) + " |")
    z += ["", "### Je Methode und Ebene (nur Zeilen mit genau einer Ebene)", "",
          "| Methode | Ebene | gezogen | richtig | teilweise | falsch | unklar | offen | ungültig | gerechnet | streng "
          "| 95-%-Intervall | nachsichtig | 95-%-Intervall |",
          "|---|---|" + "---:|" * 8 + "---:|---|---:|---|"]
    for r in e["ebenen"]:
        z.append("| " + " | ".join([_m(r["methode"]), EBENEN[r["ebene"]],
                                    *(str(r[k]) for k in ("gezogen", *KATEGORIEN, "n")), *_kennzahlen(r)]) + " |")
    na = e["ebenen_nicht_aufgeteilt"]
    if na:
        teile = [f"{_anzahl(na[k], 'Zeile', 'Zeilen')} mit {t}"
                 for k, t in (("mehrere", "mehreren Ebenen"), ("ohne", "leerer Ebene"),
                              ("unbekannt", "unbekannter Ebene")) if na.get(k)]
        z += ["", "Nicht nach Ebene aufgeteilt: " + ", ".join(teile) + "."]
    g = e["gepoolt"]
    z += ["", "### Gesamt", "", "(a) **Gepoolt, ungewichtet** über alle gerechneten Zeilen: Jede Zeile zählt gleich. "
          "Je Methode werden höchstens 50 Vorlagen gezogen, seltene Methoden sind darin also überrepräsentiert; "
          "kein Schätzwert für alle Vorlagen.", "",
          "| Lesart | Treffer | gerechnet | Präzision | 95-%-Intervall (Wilson) |", "|---|---:|---:|---:|---|"]
    for name, _ in LESARTEN:
        z.append(f"| {name} | {g[name]['x']} | {g['n']} | {_prozent(g[name]['p'])} | {_intervall(g[name]['ci'])} |")
    z.append("")
    st = e["geschichtet"]
    if st is None:
        z.append("(b) **Geschichtet, gewichtet**: entfällt (ohne `--audit` keine Zahl der Vorlagen je Methode).")
    else:
        z += [f"(b) **Geschichtet, gewichtet nach Vorlagen je Methode** (N_h = Vorlagen der Methode im Audit, gezählt "
              f"nach Drucksache, Datum und Vorlagenart). Einheit Vorlage × Methode: Eine Vorlage mit mehreren Methoden "
              f"zählt in jeder. Σ N_h = {st['N_gesamt']}, davon in Methoden mit gerechneten Zeilen {st['N_gerechnet']} "
              f"({_prozent(st['N_gerechnet'] / st['N_gesamt'] if st['N_gesamt'] else None)}). Varianz mit "
              f"Endlichkeitskorrektur und Agresti–Coull-angepasstem p je Methode, Intervall nach Wilson mit dem "
              f"effektiven Umfang (Formel: Kopf von `tools/praezision.py`, TECHNIK.md).", "",
              "| Methode | N_h (Audit) | n_h (gerechnet) | Gewicht W_h | Treffer streng | Treffer nachsichtig |",
              "|---|---:|---:|---:|---:|---:|"]
        for s in st["schichten"]:
            z.append(f"| {_m(s['methode'])}{'' if s['in_stichprobe'] else ' (nicht in der Stichprobe)'} | {s['N']} | "
                     f"{s['n']} | {_prozent(s['gewicht'])} | {s['streng']} | {s['nachsichtig']} |")
        z += ["", "| Lesart | Schätzwert | 95-%-Intervall (Wilson, effektiver Umfang) | Standardfehler "
              "| effektiver Umfang |", "|---|---:|---|---:|---:|"]
        for name, _ in LESARTEN:
            r = st[name]
            z.append(f"| {name} | – | – | – | – |" if r is None else
                     f"| {name} | {_prozent(r['p'])} | {_intervall((r['unten'], r['oben']))} | "
                     f"{_punkte(r['se'])} Prozentpunkte | "
                     f"{'– (alle vollständig geprüft)' if r['n_eff'] is None else _zahl(r['n_eff'])} |")
    if e["hinweise"]:
        z += ["", "### Hinweise", ""] + [f"- {h}" for h in e["hinweise"]]
    return "\n".join(z) + "\n"


TSV_SPALTEN = ["bereich", "methode", "ebene", "vorlagen_im_audit", "gezogen", "beurteilt", *KATEGORIEN, "gerechnet",
               "streng", "streng_unten", "streng_oben", "nachsichtig", "nachsichtig_unten", "nachsichtig_oben",
               "gewicht"]


def _z(x):
    return "" if x is None else f"{x:.4f}"


def tsv_zeilen(e):
    st = e["geschichtet"]
    N = {s["methode"]: s for s in st["schichten"]} if st else {}

    def zeile(bereich, r, ebene=""):
        s = N.get(r.get("methode"), {})
        return [bereich, r.get("methode", ""), ebene, s.get("N", ""), r.get("gezogen", ""), r.get("beurteilt", ""),
                *(r.get(k, "") for k in KATEGORIEN), r["n"],
                *(v for name, _ in LESARTEN for v in (_z(r[name]["p"]), *(_z(c) for c in (r[name]["ci"] or (None, None))))),
                _z(s.get("gewicht"))]
    out = [zeile("methode", r) for r in e["methoden"]]
    out += [zeile("methode_ebene", r, r["ebene"]) for r in e["ebenen"]]
    s = e["summe"]
    gepoolt = {**e["gepoolt"], "gezogen": sum(s.get(k, 0) for k in KATEGORIEN),
               "beurteilt": sum(s.get(k, 0) for k in URTEILE), **{k: s.get(k, 0) for k in KATEGORIEN}}
    out.append(zeile("gesamt_gepoolt_ungewichtet", gepoolt))
    if st:
        werte = []
        for name, _ in LESARTEN:
            r = st[name]
            werte += [_z(r["p"]), _z(r["unten"]), _z(r["oben"])] if r else ["", "", ""]
        out.append(["gesamt_geschichtet_gewichtet", "", "", st["N_gerechnet"], "", "", *([""] * len(KATEGORIEN)),
                    sum(x["n"] for x in st["schichten"] if x["gewicht"] is not None), *werte, ""])
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Präzision der Geokodierung aus der beurteilten Stichprobe (nur Zahlen)")
    p.add_argument("stichprobe", help="beurteilte stichprobe_geokodierung.tsv")
    p.add_argument("--audit", help="audit_geokodierung.tsv aus demselben Datenpaket (für den gewichteten Gesamtwert)")
    p.add_argument("--tsv", help="dieselben Zahlen zusätzlich als TSV in diese Datei")
    args = p.parse_args(argv)
    try:
        zeilen, kodierung = stichprobe_lesen(args.stichprobe)
        audit = audit_lesen(args.audit) if args.audit else None
    except Unbrauchbar as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1
    e = auswerten(zeilen, audit)
    print(markdown(e, Path(args.stichprobe).name, kodierung, datenstand(args.stichprobe, args.audit)), end="")
    if args.tsv:
        try:
            with open(args.tsv, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, delimiter="\t", lineterminator="\n")
                w.writerow(TSV_SPALTEN)
                w.writerows(tsv_zeilen(e))
        except OSError as fehler:
            print(f"Fehler: TSV nicht geschrieben: {args.tsv} ({type(fehler).__name__})", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
