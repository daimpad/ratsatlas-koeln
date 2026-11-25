"""Eingeklappte Akkordeons für Metaangaben auf den statischen Seiten: Quellen, Lizenzen, Regeln, Methode, Grenzen.

Herkunft: daimpad/ratsatlas-bonn @730d593 (pipeline/akkordeon.py), inhaltlich unverändert. Metaangaben sind weniger
wichtig als der Inhalt und stehen daher eingeklappt; kurze Markierungen „abgeleitet“ direkt an einzelnen Werten bleiben
sichtbar. Gestaltung über die Klassen `hh-mehr` und `meta-acc` (site/page.css).
"""


def mehr(titel, inhalt, einzug="    ", klasse="hh-mehr meta-acc"):
    """<details> mit Überschrift titel (HTML) und Inhalt (HTML, ein oder mehrere Absätze)."""
    return (f'{einzug}<details class="{klasse}">\n{einzug}  <summary>{titel}</summary>\n'
            f'{einzug}  {inhalt}\n{einzug}</details>\n')


def absatz(text):
    return f"<p>{text}</p>"
