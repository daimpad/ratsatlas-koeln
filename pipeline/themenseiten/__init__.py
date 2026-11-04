"""Beschreibungen der Themenseiten (thema/<name>/): je Thema eine Datei mit Regeln, Bahnen und Texten.
Daten, Seite, Prozessbild, Kalender, Feed und Bild zum Teilen erzeugen pipeline/dossier.py und
pipeline/prozessbild.py für alle Themen gleich. Ein neues Thema erscheint erst nach Prüfung von Hand
(Phase 0, Regelentwurf, Prüfbogen; Vorgehen wie kultur/)."""
from . import digital, kinder, klima, kultur, schule, sicherheit, soziales, verkehr, wirtschaft, wohnen

ALLE = [kultur.THEMA, verkehr.THEMA, schule.THEMA, wohnen.THEMA, klima.THEMA, kinder.THEMA, soziales.THEMA, sicherheit.THEMA,
        wirtschaft.THEMA, digital.THEMA]
ENTWUERFE = []  # nur Prüfbogen (python -m pipeline <key>-stichprobe), keine Seite, kein Export
