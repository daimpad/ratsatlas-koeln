"""Themenseiten (thema/<name>/) für Köln: je Thema eine Datei mit Regeln, Bahnen und Texten; Daten, Seite, Zeitleiste,
Kalender und Feed erzeugen pipeline/dossier.py und pipeline/prozessbild.py für alle Themen gleich.

Vorgehen je Thema (Entscheidung 24.11.2026 (3)): Kölner Datei mit Regeln nur über das Gremium (Paragraf der
Zuständigkeitsordnung aus gremien.json), Wörter im Titel und Folgevorlagen; Prüfbogen mit echten Vorlagen aus dem
Datenpaket (tools/themen_pruefbogen.py, ohne Datenbank und ohne Netz); Ergebnis in pruefung_text und pruefung_datum;
dann Freigabe durch den Auftraggeber in config.THEMENSEITEN_FREIGEGEBEN. Ein Thema mit Datei, aber ohne Freigabe ist
ein Entwurf (entwuerfe): nur Prüfbogen, kein Export, keine Seite. Die Themendateien der Vorlage (daimpad/ratsatlas-bonn)
sind nicht übernommen (Antwort 4 A zum Plan, 25.11.2026); die übrigen Kölner Themen entstehen einzeln als neue Dateien.
"""
from .. import config
from . import verkehr

ALLE = [verkehr.THEMA]
JE_SCHLUESSEL = {t.key: t for t in ALLE}


def freigegeben():
    """Freigegebene Themen in der Reihenfolge von config.THEMENSEITEN_FREIGEGEBEN, nur mit der Freigabe
    ZUSATZTHEMEN["themenseiten"]; sonst eine leere Liste. Ein Schlüssel ohne Themendatei bricht ab. Dass jedes
    freigegebene Thema geprüft ist (pruefung_text, pruefung_datum), prüfen Test und check (check.dossiers)."""
    if not config.ZUSATZTHEMEN.get("themenseiten"):
        return []
    fremd = [k for k in config.THEMENSEITEN_FREIGEGEBEN if k not in JE_SCHLUESSEL]
    if fremd:
        raise SystemExit(f"config.THEMENSEITEN_FREIGEGEBEN nennt Themen ohne Datei in pipeline/themenseiten: {fremd}")
    return [JE_SCHLUESSEL[k] for k in dict.fromkeys(config.THEMENSEITEN_FREIGEGEBEN)]


def entwuerfe():
    """Themen mit Datei, die nicht freigegeben sind: nur Prüfbogen."""
    an = {t.key for t in freigegeben()}
    return [t for t in ALLE if t.key not in an]


def geprueft(t):
    """Ist das Thema von Hand geprüft (Prüfbogen im Gespräch: pruefung_text und pruefung_datum)?"""
    return bool(t.pruefung_text.strip() and t.pruefung_datum.strip())
