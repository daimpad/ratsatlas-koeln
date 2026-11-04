"""Seite begriffe/: Begriffe des Ratsatlas in einfachen Worten (Entscheidung des Auftraggebers 02.11.2026), dazu das
Akkordeon „Begriffe auf dieser Seite“ für Themen- und Gebietsseiten.

Quelle ist das Glossar (pipeline/glossar.py, auch glossar.json für Karte und Ratsassistent). Die Erklärungen sind
allgemein und keine Rechtsberatung; je Begriff steht die Fundstelle. Ergebnistexte erscheinen in den Daten wörtlich wie
in der Quelle, die Erklärung daneben ist selbst formuliert. Keine Erzeugungszeitpunkte (stabile Ausgabe)."""
from html import escape

from . import glossar

PFAD = "begriffe/"


def _dl(eintraege):
    """eintraege: (Begriff, Erklärung, Fundstelle oder None, Sprungmarke)"""
    zeilen = []
    for begriff, text, fundstelle, anker in eintraege:
        quelle = f' <span class="meta">Fundstelle: {escape(fundstelle)}</span>' if fundstelle else ""
        zeilen.append(f'      <dt id="{escape(anker)}">{escape(begriff)}</dt><dd>{escape(text)}{quelle}</dd>')
    return "    <dl class=\"begriffe\">\n" + "\n".join(zeilen) + "\n    </dl>"


def abschnitte():
    """(Sprungmarke, Überschrift, Einleitung, Einträge) in der Reihenfolge der Seite."""
    g = glossar.glossar()
    out = []
    for key, titel in glossar.GRUPPEN:
        eintraege = [(b["begriff"], b["erklaerung"], b["fundstelle"], b["anker"]) for b in g["begriffe"] if b["gruppe"] == key]
        if eintraege:
            out.append((key, titel, "", eintraege))
    ergebnisse = [(k, v, None, glossar.anker(k)) for k, v in glossar.ERGEBNISSE.items() if k not in glossar.ROLLEN]
    rollen = [(k, glossar.ERGEBNISSE[k], None, glossar.anker("rolle " + k)) for k in glossar.ROLLEN]
    out.append(("ergebnisse", "Ergebnisse der Beratung",
                "Die Ergebnisse stehen in der Prozesslinie wörtlich wie im Ratsinformationssystem (über OParl-Lite); die "
                "Erklärung daneben ist allgemein formuliert.", ergebnisse))
    out.append(("rollen", "Rollen in der Beratungsfolge", "Jedes Gremium der Beratungsfolge hat eine Rolle.", rollen))
    out.append(("stand", "Stand eines Vorgangs",
                "Der Stand ist vom Ratsatlas aus der Beratungsfolge abgeleitet.",
                [(k, v, None, glossar.anker("stand " + k)) for k, v in glossar.STAENDE.items()]))
    out.append(("schritte", "Schritte der Prozesslinie", "",
                [(glossar.SCHRITTE[k], v, None, glossar.anker("schritt " + k)) for k, v in glossar.SCHRITTE_TEXT.items()]))
    sicher = [("belegt", glossar.EVIDENZ["belegt"]), ("abgeleitet", glossar.EVIDENZ["abgeleitet"]),
              ("nicht öffentlich", glossar.EVIDENZ["nicht_öffentlich"]), ("unklar", glossar.EVIDENZ["unklar"]),
              ("soll", glossar.EVIDENZ["soll"]),
              ("Ort gesichert", "Die Stadt gibt den Ort mit einer Koordinate an."),
              ("Ort erschlossen", "Der Ort ist nach festen Regeln aus dem Titel oder dem Text eines Dokuments erschlossen, "
                                  "etwa aus einem Straßen- oder Ortsteilnamen."),
              ("Ort unsicher", "Der Ort ist erschlossen, aber nicht eindeutig, etwa bei Namen von Gebäuden oder Anlagen.")]
    out.append(("sicherheit", "Wie sicher eine Angabe ist", "",
                [(k, v, None, glossar.anker("angabe " + k)) for k, v in sicher]))
    return out


def body(root):
    teile = abschnitte()
    sprung = " · ".join(f'<a href="#{k}">{escape(t)}</a>' for k, t, _, _ in teile)
    html = [f"""    <h1>Begriffe</h1>
    <p class="lead">Was bedeuten die Wörter im Ratsatlas? Hier stehen Vorlagenarten, Gremien, Ergebnisse und Kürzel in einfachen Worten, jeweils mit Fundstelle.</p>
    <p class="meta">Die Erklärungen sind allgemein und keine Rechtsberatung. Maßgeblich sind die Gemeindeordnung NRW, die Geschäftsordnung des Rates und die Originale im Ratsinformationssystem. Wo eine Vorlagenart in keinem Regelwerk beschrieben ist, ist die Erklärung aus den Daten erschlossen; das steht bei der Fundstelle.</p>
    <nav class="thema-sprung" aria-label="Auf dieser Seite"><span>Auf dieser Seite:</span> {sprung}</nav>"""]
    for key, titel, einleitung, eintraege in teile:
        html.append(f'    <h2 id="{key}">{escape(titel)}</h2>')
        if einleitung:
            html.append(f"    <p>{escape(einleitung)}</p>")
        html.append(_dl(eintraege))
    html.append(f'    <p class="meta">Quelle: Glossar des Ratsatlas (<a href="{root}data/export/glossar.json">glossar.json</a>), '
                "das auch der Ratsassistent nutzt. <a href=\"" + root + "\">Zur Karte</a> · <a href=\"" + root
                + "thema/\">Themenseiten</a></p>")
    return "\n".join(html)


def akkordeon(texte, root):
    """Eingeklapptes Akkordeon „Begriffe auf dieser Seite“: Vorlagenarten, Ergebnisse und Stände, die in texte
    vorkommen (Entscheidung 02.11.2026), mit Link auf begriffe/. Ohne Treffer leer."""
    g = glossar.glossar()
    begriffe = {b["anker"]: b for b in g["begriffe"]}
    texte = {t for t in texte if t}
    eintraege, gesehen = [], set()

    def neu(anker, begriff, text, ziel):
        if anker not in gesehen and text:
            gesehen.add(anker)
            eintraege.append((begriff, text, ziel))
    for t in sorted(texte):
        if t in g["arten"]:
            b = begriffe[g["arten"][t]]
            neu(b["anker"], t, b["erklaerung"], b["anker"])
    for t in sorted(texte):
        for teil in (x.strip() for x in t.split(" - ")):
            if teil in glossar.ERGEBNISSE and teil not in glossar.ROLLEN:
                neu(glossar.anker(teil), teil, glossar.ERGEBNISSE[teil], glossar.anker(teil))
    for t in sorted(texte):
        if t in glossar.STAENDE:
            neu(glossar.anker("stand " + t), f"Stand: {t}", glossar.STAENDE[t], glossar.anker("stand " + t))
    if not eintraege:
        return ""
    zeilen = "\n".join(f'        <dt><a href="{root}{PFAD}#{escape(z)}">{escape(b)}</a></dt><dd>{escape(e)}</dd>'
                       for b, e, z in eintraege)
    return f"""    <details class="begriffe-acc">
      <summary>Begriffe auf dieser Seite</summary>
      <dl class="begriffe">
{zeilen}
      </dl>
      <p class="meta">Erklärungen allgemein; Ergebnisse stehen wörtlich wie in der Quelle. <a href="{root}{PFAD}">Alle Begriffe</a></p>
    </details>
"""


def write(site, site_url, page):
    """Schreibt begriffe/index.html; gibt den Pfad für die Sitemap zurück."""
    out = site / PFAD / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site_url, PFAD, "Begriffe – Ratsatlas Bonn",
                        "Was bedeuten Beschlussvorlage, Stellungnahme der Verwaltung, „zur Kenntnis genommen“ oder ST? "
                        "Begriffe aus dem Ratsinformationssystem der Stadt Bonn in einfachen Worten, mit Fundstelle.",
                        body("../"), "../"), encoding="utf-8")
    return [PFAD]
