"""Texte mit Abschnitten, die nur mit oder nur ohne Freigabe eines Zusatzthemas gelten (config.ZUSATZTHEMEN).

Für Markdown-Dateien, die auf die Seite und ins Datenpaket gehen (data/LICENSE-DATA.md): Ein Abschnitt steht zwischen
zwei Markierungszeilen, jede allein auf ihrer Zeile:

    <!-- nur-mit: strukturdaten -->
    … gilt nur mit Freigabe …
    <!-- ende -->
    <!-- nur-ohne: strukturdaten -->
    … gilt nur ohne Freigabe …
    <!-- ende -->

`text()` entfernt die Markierungszeilen immer und die Abschnitte, die nach der Freigabe nicht gelten. Ohne Abschnitte
mit Freigabe ergibt das genau den Text, der vor dem Einfügen der Abschnitte galt (die Seite ändert sich durch einen
abgeschalteten Abschnitt nicht). Im Repository zeigt GitHub beide Fassungen (die Markierungen sind HTML-Kommentare);
die Abschnitte sind daher so geschrieben, dass sie auch hintereinander gelesen stimmen. Abschnitte lassen sich nicht
verschachteln; eine unbekannte Funktion, ein offener Abschnitt oder ein `ende` ohne Anfang brechen ab.
"""
import re

from . import config

_ANFANG = re.compile(r"<!-- nur-(mit|ohne): ([a-z_]+) -->")
_ENDE = "<!-- ende -->"


def text(quelle, freigaben=None):
    """`quelle` ohne Markierungszeilen und ohne die Abschnitte, die nach `freigaben` (Vorgabe config.ZUSATZTHEMEN)
    nicht gelten."""
    freigaben = config.ZUSATZTHEMEN if freigaben is None else freigaben
    aus, offen = [], None   # offen: (gilt, Zeilennummer) des laufenden Abschnitts
    for nr, zeile in enumerate(quelle.splitlines(keepends=True), start=1):
        inhalt = zeile.rstrip("\r\n")
        m = _ANFANG.fullmatch(inhalt)
        if m:
            if offen:
                raise ValueError(f"Zeile {nr}: Abschnitt in Abschnitt (begonnen in Zeile {offen[1]})")
            art, funktion = m.groups()
            if funktion not in freigaben:
                raise ValueError(f"Zeile {nr}: unbekannte Funktion {funktion!r} (nicht in config.ZUSATZTHEMEN)")
            offen = (bool(freigaben.get(funktion)) == (art == "mit"), nr)
            continue
        if inhalt == _ENDE:
            if not offen:
                raise ValueError(f"Zeile {nr}: „ende“ ohne Anfang")
            offen = None
            continue
        if "<!-- nur-" in inhalt:
            raise ValueError(f"Zeile {nr}: Markierung nicht allein auf ihrer Zeile: {inhalt!r}")
        if offen is None or offen[0]:
            aus.append(zeile)
    if offen:
        raise ValueError(f"Abschnitt aus Zeile {offen[1]} nicht geschlossen")
    return "".join(aus)


def datei(pfad, freigaben=None):
    """Inhalt der Datei `pfad` (UTF-8) nach den Freigaben als Bytes, Zeilenenden unverändert."""
    with open(pfad, encoding="utf-8", newline="") as fh:
        return text(fh.read(), freigaben).encode("utf-8")
