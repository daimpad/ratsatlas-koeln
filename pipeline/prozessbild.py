"""Zeitleiste der Themenseiten („Auf einen Blick“): Bahnen je Gruppe von Gremien (SVG, ohne Skript), Stand je Strang als
Balken und Karten zum Mitwirken. Grundlage sind dossier.daten() und die Beschreibung des Themas
(pipeline/themenseiten/); erzeugt im seo-Schritt.

Herkunft: daimpad/ratsatlas-bonn @730d593 (pipeline/prozessbild.py). Kölner Anpassungen (inventur/themenseiten_port.tsv):
- Achse aus dem Datenstand berechnet (dossier.achse, Feld `achse` der Daten) statt fester Daten je Thema;
- Bahnnamen nicht im Bild, sondern als HTML-Spalte neben dem verschiebbaren Rahmen (bahnen_spalte): Sie bleiben beim
  Verschieben stehen; gleiche Zeilenhöhe BAHN, Abstand oben OBEN (CSS-Variablen am Rahmen der Zeitleiste);
- Legende als HTML unter dem Bild (legende), nicht im Bild; feste Pixelmaße des Bildes (width und height wie viewBox);
- ohne Phasen, Beratungsfenster, Fristlinien und Bild zum Teilen;
- Karten: Kalender, Feed, Sitzung besuchen (Livestream des Rates), Frage oder Anregung (pipeline/mitwirken.py), Links zur
  Karte (nur für Ebenen, die im Bau vorliegen).
Beschlüsse und Anträge erscheinen als nummerierte Punkte (entschieden, beraten, offen), die nächsten Sitzungen mit
Hand-Symbol. Die nummerierte Liste unter dem Bild ist die Textfassung. Auf der Seite sind Punkte und Sitzungen Links
(Vorgang auf der Karte, Tagesordnung); mit Skript (site/thema.js) öffnet ein Klick stattdessen das Detailfeld unter dem
Bild, Schalter blenden Stränge aus."""
import json
from datetime import date, timedelta
from html import escape
from urllib.parse import quote

from . import akkordeon, dossier, mitwirken
from .publish import EXPORT_PFAD

W, LINKS, RECHTS, OBEN, BAHN = 960, 14, 16, 62, 52
UNTEN = 16   # Abstand unter der letzten Bahn
MONATE = "Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez".split()
MONATE_LANG = ("Januar Februar März April Mai Juni Juli August September Oktober November Dezember").split()
ART = {"entschieden": "entschieden", "beraten": "beraten, ohne abschließende Entscheidung", "offen": "offen"}
ICON = {
    "hand": '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11V4.5a1.5 1.5 0 0 1 3 0V12M14 11.5V6a1.5 1.5 0 0 1 3 0v8a7 7 0 '
            '0 1-7 7h-.6a6 6 0 0 1-4.5-2.1L2.6 16a1.5 1.5 0 0 1 2.2-2L8 16"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "rss": '<path d="M5 11a8 8 0 0 1 8 8M5 4.5A14.5 14.5 0 0 1 19.5 19"/><circle cx="6" cy="18" r="1.4"/>',
    "people": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.5-3.6 3.2-6 6.5-6s6 2.4 6.5 6"/>'
              '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.6c1.8.9 3 2.7 3.2 5.4"/>',
    "map": '<path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4z"/><path d="M9 4v14M15 6v14"/>',
}
TEXT, LILA, LILA_HELL, GRAU, BERNSTEIN = "#0f0f14", "#6d28d9", "#c4b5fd", "#5a5a68", "#f59e0b"
PUNKT_FARBEN = {"entschieden": (LILA, LILA, "#fff"), "beraten": (LILA_HELL, LILA, TEXT), "offen": ("#fff", LILA, TEXT)}


def _d(iso):
    return date.fromisoformat(iso[:10])


class Achse:
    """Zeitachse in zwei Abschnitten (dossier.achse: Anfang, Knick, Ende, Anteil des Rückblicks): der Rückblick
    gestaucht, die kommenden Monate breiter. Ohne Rückblick (Anteil 0) linear. Daten außerhalb stehen am Rand."""

    def __init__(self, d):
        a = d["achse"]
        self.t0, self.knick, self.t1, self.anteil = _d(a["von"]), _d(a["knick"]), _d(a["bis"]), a["anteil"]

    def innen(self, iso):
        return self.t0 <= _d(iso) <= self.t1

    def x(self, iso):
        d, breite = min(max(_d(iso), self.t0), self.t1), W - LINKS - RECHTS
        if self.anteil and d <= self.knick:
            return LINKS + breite * self.anteil * (d - self.t0).days / (self.knick - self.t0).days
        start = self.knick if self.anteil else self.t0
        return LINKS + breite * (self.anteil + (1 - self.anteil) * (d - start).days / max(1, (self.t1 - start).days))

    def monat(self, d):
        return f"{MONATE_LANG[d.month - 1]} {d.year}"


def hoehe(t):
    return OBEN + len(t.bahnen) * BAHN + UNTEN


def _kurz(iso):
    return f"{iso[8:10]}.{iso[5:7]}."


def _datum(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso else "–"


def _icon(name, size=18, farbe=LILA):
    return (f'<svg class="icon" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="{farbe}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{ICON[name]}</svg>')


def _zeile(t, b):
    return OBEN + [k for k, _ in t.bahnen].index(b) * BAHN


def _ziel(href, titel, inneres, kennung=""):
    """Element mit Kurztext; mit Adresse als Link (Name für Screenreader aus dem Kurztext), sonst als Gruppe.
    kennung: Attribute für das Detailfeld (data-ziel, data-strang)."""
    if not href:
        return f'<g><title>{titel}</title>{inneres}</g>'
    return (f'<a class="pb-ziel" href="{escape(href)}" aria-label="{titel}"{kennung}><title>{titel}</title>'
            f'{inneres}</a>')


def _hand(x, y, groesse=14):
    return (f'<use href="#pb-hand" x="{x - groesse / 2:.1f}" y="{y - groesse / 2:.1f}" width="{groesse}" '
            f'height="{groesse}" fill="none" stroke="{TEXT}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round"/>')


def svg(t, d, root=None):
    """Zeitleiste mit Bahnen als SVG-Zeichenkette; mit root (Pfad zur Startseite) sind die Elemente Links. Ohne
    Bahnnamen und Legende (beide als HTML neben bzw. unter dem Bild)."""
    heute, a = d["heute"], Achse(d)
    _x = a.x
    h_bahnen, h = len(t.bahnen) * BAHN, hoehe(t)
    # mit Links ohne role="img" (Standardrolle graphics-document): Kinder eines Bildes wären für Screenreader
    # nicht erreichbar
    rolle = 'role="img" ' if root is None else ""
    out = [f'<svg class="pb-svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" {rolle}'
           f'aria-labelledby="pb-titel pb-text" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Inter, system-ui, sans-serif">',
           f'<title id="pb-titel">{escape(t.bild_titel)}</title>',
           f'<desc id="pb-text">{escape(_beschreibung(t, d))}</desc>',
           f'<defs><symbol id="pb-hand" viewBox="0 0 24 24">{ICON["hand"]}</symbol></defs>']
    # Bahnen (Namen in der Spalte daneben, bahnen_spalte)
    for i, (key, _) in enumerate(t.bahnen):
        out.append(f'<rect x="0" y="{_zeile(t, key)}" width="{W}" height="{BAHN}" '
                   f'fill="{"#f7f5ff" if i % 2 == 0 else "#ffffff"}"/>')
    # Monate
    m = date(a.t0.year, a.t0.month, 1)
    while m < a.t1:
        x = _x(m.isoformat())
        out.append(f'<line x1="{x:.1f}" y1="{OBEN - 6}" x2="{x:.1f}" y2="{OBEN + h_bahnen}" stroke="#e4e2ee"/>')
        out.append(f'<text x="{x + 3:.1f}" y="{OBEN - 10}" font-size="11" fill="{GRAU}">{MONATE[m.month - 1]}</text>')
        if m.month == 1 or m == date(a.t0.year, a.t0.month, 1):
            out.append(f'<text x="{x + 3:.1f}" y="{OBEN - 26}" font-size="12" font-weight="600" fill="{TEXT}">'
                       f'{m.year}</text>')
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    # nächste Sitzungen
    zuletzt = {}
    for i, s in sorted(enumerate(d["sitzungen"]), key=lambda x: x[1]["date"]):
        x = _x(s["date"])
        # dicht folgende Sitzungen derselben Bahn abwechselnd oben und unten
        vorher = zuletzt.get(s["bahn"])
        oben = bool(vorher) and x - vorher[0] < 26 and not vorher[1]
        zuletzt[s["bahn"]] = (x, oben)
        yc = _zeile(t, s["bahn"]) + BAHN / 2 + (-11 if oben else 0)
        # Tagesordnung, sobald die Stadt sie veröffentlicht hat, sonst die Terminliste der Seite
        ziel = None if root is None else s.get("web") or "#sitzungen"
        out.append(_ziel(ziel, f'{escape(s["gremium"])}, {_datum(s["date"])}: öffentliche Sitzung'
                         + (", laut Sitzungsnamen verschoben" if s.get("hinweis") == "verschoben" else "")
                         + (", Tagesordnung" if root is not None and s.get("web") else ""),
                         f'<circle cx="{x:.1f}" cy="{yc:.1f}" r="10.5" fill="#fff" stroke="{BERNSTEIN}" stroke-width="2"/>'
                         + _hand(x, yc),
                         f' data-ziel="sitzung-{i}"'))
    # Beschlüsse und Anträge
    belegt = {}
    for p in d["punkte"]:
        if not p["date"]:
            continue
        x, y = _x(p["date"]), _zeile(t, p["bahn"]) + BAHN / 2
        for dy in (0, -11, 11, -5, 5):
            if all(abs(x - bx) > 18 or abs(y + dy - by) > 17 for bx, by in belegt.get(p["bahn"], [])):
                break
        else:
            dy = 0
            while any(abs(x - bx) <= 18 and abs(y - by) <= 17 for bx, by in belegt.get(p["bahn"], [])):
                x += 6
        belegt.setdefault(p["bahn"], []).append((x, y + dy))
        fill, stroke, farbe = PUNKT_FARBEN[p["art"]]
        ziel = None if root is None else dossier._map(root, p.get("gebiet"), p["reference"]) or p.get("web")
        out.append(_ziel(ziel, f'{p["nr"]}: {escape(p["reference"])} {escape(p["name"] or "")} – {escape(p["stand"] or "")}'
                         f' ({escape(p["gremium"] or "")}, {_datum(p["date"])})',
                         f'<circle cx="{x:.1f}" cy="{y + dy:.1f}" r="9" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
                         f'<text x="{x:.1f}" y="{y + dy + 3.6:.1f}" font-size="10" font-weight="700" '
                         f'text-anchor="middle" fill="{farbe}">{p["nr"]}</text>',
                         f' data-ziel="punkt-{p["nr"]}" data-strang="{escape(p.get("strang") or "")}"'))
    # heute
    xh = _x(heute)
    out.append(f'<line x1="{xh:.1f}" y1="{OBEN - 44}" x2="{xh:.1f}" y2="{OBEN + h_bahnen}" stroke="{TEXT}" '
               f'stroke-width="2" pointer-events="none"/>')  # liegt über den Punkten
    out.append(f'<text x="{xh + 5:.1f}" y="{OBEN - 40}" font-size="12" font-weight="700" fill="{TEXT}">'
               f'Stand {_kurz(heute)}</text>')
    out.append("</svg>")
    return "".join(out)


def bahnen_spalte(t):
    """Namen der Bahnen als HTML neben dem verschiebbaren Rahmen (bleiben beim Verschieben stehen); für Screenreader
    ausgeblendet, die Textfassung nennt die Gremien je Punkt."""
    namen = "".join(f'<span class="pb-bahn">{escape(label)}</span>' for _, label in t.bahnen)
    return f'<div class="pb-bahnen" aria-hidden="true">{namen}</div>'


def _zeichen(art):
    """Kleines Zeichen der Legende (SVG, für Screenreader ausgeblendet)."""
    kopf = '<svg class="pb-zeichen" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">'
    if art in PUNKT_FARBEN:
        fill, stroke, _ = PUNKT_FARBEN[art]
        inner = f'<circle cx="10" cy="10" r="7" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
    elif art == "sitzung":
        inner = (f'<circle cx="10" cy="10" r="8.5" fill="#fff" stroke="{BERNSTEIN}" stroke-width="2"/>'
                 f'<g transform="translate(4 4) scale(.5)" fill="none" stroke="{TEXT}" stroke-width="3.6" '
                 f'stroke-linecap="round" stroke-linejoin="round">{ICON["hand"]}</g>')
    else:
        inner = f'<line x1="10" y1="1" x2="10" y2="19" stroke="{TEXT}" stroke-width="2"/>'
    return f"{kopf}{inner}</svg>"


def legende():
    """Legende der Zeitleiste als HTML unter dem Bild."""
    eintraege = [("entschieden", "entschieden"), ("beraten", "beraten, ohne abschließende Entscheidung"),
                 ("offen", "offen"), ("sitzung", "nächste öffentliche Sitzung"), ("heute", "Datenstand")]
    return ('    <ul class="pb-legende-bild" aria-label="Legende der Zeitleiste">'
            + "".join(f"<li>{_zeichen(a)}{escape(text)}</li>" for a, text in eintraege) + "</ul>")


def _beschreibung(t, d):
    a = Achse(d)
    n = {k: sum(1 for p in d["punkte"] if p["art"] == k) for k in ART}
    naechste = ", ".join(f"{s['gremium']} am {_datum(s['date'])}" for s in d["sitzungen"][:4])
    aussen = sum(1 for x in [*d["punkte"], *d["sitzungen"]] if x.get("date") and not a.innen(x["date"]))
    return (f"Zeitleiste von {a.monat(a.t0)} bis {a.monat(a.t1 - timedelta(days=1))}, Datenstand {_datum(d['heute'])}. "
            f"{len(d['punkte'])} Beschlüsse und Anträge: {n['entschieden']} entschieden, {n['beraten']} beraten ohne "
            f"abschließende Entscheidung, {n['offen']} offen. "
            + (f"Nächste öffentliche Sitzungen: {naechste}." if naechste else "Keine kommende Sitzung eingetragen.")
            + (f" {aussen} {'Angabe liegt' if aussen == 1 else 'Angaben liegen'} außerhalb des Zeitraums und "
               f"{'steht' if aussen == 1 else 'stehen'} am Rand des Bildes." if aussen else ""))


def stand_balken(d):
    """Stand je Strang als gestapelte Balken in HTML (skaliert mit der Seite; Zahlen sichtbar, Wörter für Screenreader)."""
    teile = [("entschieden", "entschieden", "pb-s1"), ("in Beratung", "in Beratung", "pb-s2"),
             ("beraten, ohne Entscheidung", "zur Kenntnis genommen oder ohne Votum", "pb-s3"),
             ("offen", "offen", "pb-s4")]
    groesste = max((len(s["vorlagen"]) for s in d["straenge"]), default=1) or 1
    zeilen = []
    for s in d["straenge"]:
        segmente = []
        for k, text, cls in teile:
            n = sum(1 for r in s["vorlagen"] if r["stand"] == k)
            if n:
                segmente.append(f'<span class="pb-seg {cls}" style="flex-grow:{n}" title="{n} {escape(text)}">{n}'
                                f'<span class="pb-sr"> {escape(text)}</span></span>')
        breite = 100 * len(s["vorlagen"]) / groesste
        zeilen.append(f'      <li><span class="pb-name">{escape(s["titel"])}</span><span class="pb-bar" '
                      f'style="width:{breite:.1f}%">{"".join(segmente)}</span></li>')
    legende_ = "".join(f'<span><i class="pb-seg {cls}"></i>{escape(text)}</span>' for _, text, cls in teile)
    return ('    <ul class="pb-balken">\n' + "\n".join(zeilen) + f'\n    </ul>\n    <p class="pb-legende">{legende_}</p>')


def _karte(icon, titel, text, aktionen):
    return (f'      <div class="pb-karte">{_icon(icon, 22)}<h3>{escape(titel)}</h3><p>{text}</p>'
            f'<p class="pb-aktionen">{aktionen}</p></div>')


def aufrufe(t, d, root, karten=()):
    """Karten zum Handeln: Kalender, Feed, Sitzung besuchen, Frage oder Anregung, Links zur Karte (`karten`:
    [(Adresse, Text)] aus dossier.karten_links, nur für Ebenen im Bau)."""
    liste = [
        _karte("calendar", "Termine in den Kalender",
               "Die Sitzungen der Gremien dieser Seite als Kalenderdatei, mit Link zur Tagesordnung, sobald sie erscheint.",
               f'<a class="pb-knopf" href="{root}{EXPORT_PFAD}/dossiers/{t.key}.ics" download>Kalender (.ics)</a>'),
        _karte("rss", "Informiert bleiben",
               f"Neue Vorlagen und Beratungsergebnisse {escape(t.feed_text)} im Feed-Reader.",
               f'<a class="pb-knopf" href="{root}{EXPORT_PFAD}/dossiers/{t.key}.xml">Feed abonnieren</a>'),
        _karte("people", "Sitzung besuchen",
               "Rat, Ausschüsse und Bezirksvertretungen tagen öffentlich; Ratssitzungen überträgt die Stadt live im "
               "Internet.",
               f'<a class="pb-knopf" href="#sitzungen">Alle Termine</a> {mitwirken.link("ratLive", "pb-knopf pb-knopf-leise")}'),
        _karte("hand", mitwirken.KARTE_TITEL, escape(mitwirken.KARTE_TEXT), mitwirken.karte_aktionen(root)),
    ]
    if karten:
        liste.append(_karte("map", "Auf der Karte", "Passende Ebenen und Vorlagen auf der Karte des Ratsatlas.",
                            " ".join(f'<a class="pb-knopf pb-knopf-leise" href="{escape(href)}">{escape(text)}</a>'
                                     for href, text in karten)))
    return '    <div class="pb-karten">\n' + "\n".join(liste) + "\n    </div>"


def liste(d, root):
    zeilen = []
    for p in d["punkte"]:
        ref = escape(p["reference"])
        link = (f'<a href="{root}?gebiet={quote(p["gebiet"], safe=":")}#{quote(p["reference"])}">{ref}</a>'
                if p.get("gebiet") else ref)
        zeilen.append(f'        <li value="{p["nr"]}" data-ziel="punkt-{p["nr"]}" data-strang="{escape(p.get("strang") or "")}">'
                      f'<span class="pb-nr pb-{p["art"]}">{p["nr"]}</span> {link} '
                      f'{escape(p["name"] or "")} <small>– {escape(p["stand"] or "")}; {escape(p["gremium"] or "")} '
                      f'{_datum(p["date"])}</small></li>')
    n = len(d["punkte"])
    if not n:
        return "    <p>Im Bild stehen keine Beschlüsse und Anträge.</p>"
    kopf = "Ein Beschluss oder Antrag im Bild" if n == 1 else f"Die {n} Beschlüsse und Anträge im Bild"
    return (f'    <details class="pb-liste">\n      <summary>{kopf}'
            f'</summary>\n      <ol>\n' + "\n".join(zeilen) + "\n      </ol>\n    </details>")


def schalter(t, d):
    """Schalter zum Ein- und Ausblenden der Stränge im Bild; ohne Skript verborgen."""
    titel = {s["key"]: s["titel"] for s in d["straenge"]}
    knoepfe = "".join(f'<button type="button" class="pb-schalter" data-strang="{k}" aria-pressed="true">'
                      f'{escape(titel.get(k, k))}</button>' for k in t.punkt_straenge
                      if any(p.get("strang") == k for p in d["punkte"]))
    return (f'    <div class="pb-filter" role="group" aria-label="Stränge im Bild ein- und ausblenden" hidden>'
            f'<h3 class="pb-filter-text">Stränge im Bild</h3>{knoepfe}</div>')


def detaildaten(t, d, root):
    """Angaben für das Detailfeld (JSON in der Seite, nicht ausgeführt); Adressen fertig gebildet. Ohne Fristen und
    ohne Federführung; je Beratung die Absage nach export.absage („oparl“ oder „name“)."""
    titel = {s["key"]: s["titel"] for s in d["straenge"]}
    daten = {
        "heute": d["heute"],
        "kalender": f"{root}{EXPORT_PFAD}/dossiers/{t.key}.ics",
        "mitmachen": f"{root}?mitmachen=1",
        "punkte": {str(p["nr"]): {
            "nr": p["nr"], "reference": p["reference"], "name": p["name"], "paper_type": p.get("paper_type"),
            "stand": p["stand"], "strang": titel.get(p.get("strang"), ""), "grund": p.get("grund"),
            "beratungen": p.get("beratungen", []), "web": p.get("web"),
            "karte": dossier._map(root, p.get("gebiet"), p["reference"])} for p in d["punkte"]},
        "sitzungen": [{k: s.get(k) for k in ("gremium", "date", "time", "hinweis", "web")} for s in d["sitzungen"]],
    }
    # „</“ maskieren, damit kein Titel das Skript-Element beendet
    return json.dumps(daten, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def abschnitt(t, d, root, karten=()):
    """HTML-Abschnitt für die Themenseite: Schalter, Bahnen und Bild, Legende, Detailfeld, Liste, Karten und Stand je
    Strang."""
    a = Achse(d)
    knick = f" Die Monate ab {a.monat(a.knick)} sind breiter gezeichnet." if a.anteil else ""
    text = (f"<p>Punkte: Beschlussvorlagen, Dringlichkeitsentscheidungen und Anträge mit Beratung {escape(t.punkt_text)}; "
            "Lage nach der letzten Beratung mit Ergebnis, sonst nach der nächsten (abgeleitet). Beratungen in den "
            "Bezirksvertretungen stehen in der Liste und im Detailfeld. Hand-Symbole: die nächsten Sitzungen laut "
            f"Sitzungskalender. Das Bild beginnt mit der Wahlperiode ({_datum(d['meta']['seit'])}).{knick}</p>")
    return f"""    <h2>Auf einen Blick</h2>
    <p>Wo steht das Verfahren, was ist entschieden, wann wird beraten? Punkte und Sitzungen lassen sich anklicken, auch mit der Tabulatortaste.</p>
{akkordeon.mehr("So ist das Bild gezeichnet", text)}
{schalter(t, d)}
    <div class="pb-zeitleiste" style="--pb-oben:{OBEN}px;--pb-bahn:{BAHN}px;--pb-hoehe:{hoehe(t)}px">
      {bahnen_spalte(t)}
      <div class="pb-rahmen pb-breit" tabindex="0" role="region" aria-label="Zeitleiste, waagerecht verschiebbar" data-start="{a.x(d["heute"]) / W:.3f}">
        {svg(t, d, root)}
      </div>
    </div>
{legende()}
    <div class="pb-detail" id="pb-detail" role="region" aria-label="Angaben zur Auswahl im Bild" hidden></div>
    <p class="pb-sr" id="pb-ansage" aria-live="polite"></p>
    <script type="application/json" id="pb-daten">{detaildaten(t, d, root)}</script>
{liste(d, root)}
{aufrufe(t, d, root, karten)}
    <h3>Stand der Vorlagen je Strang</h3>
{stand_balken(d)}
    <script src="{root}thema.js" defer></script>"""
