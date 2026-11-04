"""Aufruf: python -m pipeline {fetch|geo-koeln|fetch-papers|fetch-organizations|fetch-besetzung|fetch-lite|fetch-meetings|fetch-plans|fetch-housenumbers|fetch-objects|fetch-texts|fetch-streets|gazetteer|build|export|check|verify|package|seo|baustellen|anliegen|anliegen-seite|kandidaten|baustellen-seite|kurzfassungen|stufe-c|soll|kontext-ausschnitte|wahlen-rohdaten|wahlen-ausschnitt|haushalt-ausschnitt|haushalt-pruefbogen|haushalt-ebenen|haushalt-pruefbogen-ebenen|haushalt-ist2024|haushalt-investitionen|haushalt-pruefbogen-erweiterung|haushalt-ist2024-investitionen|haushalt-pruefbogen-erweiterung-finanz|haushalt-ertragsarten|haushalt-pruefbogen-ertragsarten|fetch-haltestellen|kontext|kultur-stichprobe|verkehr-stichprobe|schule-stichprobe|wohnen-stichprobe|klima-stichprobe|kinder-stichprobe|soziales-stichprobe|sicherheit-stichprobe|wirtschaft-stichprobe|digital-stichprobe|all}"""
import sys

from . import anliegen, baustellen, besetzung, build, check, config, dossier, export, fetch, geodaten, kandidaten, kontext, haushaltsplan, kurzfassung, seo, sessionnet, soll, stufe_c, verify, wahlen
from .themenseiten import digital, kinder, klima, kultur, schule, sicherheit, soziales, verkehr, wirtschaft, wohnen

def _ersetzt(durch):
    def schritt():
        raise SystemExit(f"In Köln ersetzt durch `{durch}` (Bonner Quelle, Inventur Phase 0).")
    return schritt


STEPS = {
    "fetch": sessionnet.fetch_all,  # SessionNet-Adapter Köln (Abrufpolitik, inkrementell, Abrufstatistik)
    "geo-koeln": geodaten.write,  # Stadtteile, Stadtbezirke und Straßenverzeichnis aus den Kölner Geodaten
    "fetch-papers": _ersetzt("fetch"),
    "fetch-organizations": _ersetzt("fetch"),
    "fetch-besetzung": besetzung.fetch,  # laufende Mitgliedschaften (Auszug ohne Kontaktdaten), nach fetch-organizations
    "fetch-lite": _ersetzt("fetch"),
    "fetch-meetings": _ersetzt("fetch"),
    "fetch-plans": _ersetzt("geo-koeln (Bebauungspläne: Bezugsquelle offen)"),
    "fetch-housenumbers": _ersetzt("geo-koeln (Phase 3)"),
    "fetch-objects": fetch.fetch_objects,
    "fetch-texts": _ersetzt("Volltexte aus PDFs (Phase 3)"),
    "fetch-streets": _ersetzt("geo-koeln"),
    "gazetteer": geodaten.write,
    "build": build.build,
    "export": export.export,
    "check": check.check,
    "verify": verify.verify,
    "package": verify.package,
    "seo": seo.write,  # nach dem Zusammenstellen der Seite in _site
    "baustellen": baustellen.archive,  # Archiv der Baustellen (eigener Workflow, Branch archiv)
    "anliegen": anliegen.archive,  # Archiv des Mängelmelders (Workflow baustellen.yml, Branch archiv, Ordner anliegen)
    "anliegen-seite": anliegen.seite,  # Zahlen je Ortsteil für den Steckbrief (nach dem Auschecken des Archivs)
    "kandidaten": kandidaten.write,  # Kandidaten Beschluss ↔ Baustelle (Audit, Stichprobe)
    "baustellen-seite": kandidaten.write_site,
    "kurzfassungen": kurzfassung.erzeugen,  # Kurzfassungen mit Mistral (Secret MISTRAL_API_KEY), Branch kurzfassungen
    "stufe-c": stufe_c.schritt,  # Stufe C (Sprachmodell, nach build, vor export): Anfragen, Gegenprüfung, Audit
    "haushalt-ausschnitt": haushaltsplan.ausschnitt,  # einmalig, lokal (pdftotext): Beträge je Produktbereich aus den PDFs
    "haushalt-pruefbogen": haushaltsplan.pruefbogen,  # einmalig: Prüfbogen der Werte der Themenseiten
    "haushalt-ebenen": haushaltsplan.ebenen,  # einmalig, lokal (pdftotext -bbox): Aufwandsarten und Produktgruppen
    "haushalt-pruefbogen-ebenen": haushaltsplan.pruefbogen_ebenen,  # einmalig: Prüfbogen der Ebenen 2 und 3
    "haushalt-ist2024": haushaltsplan.ist2024,  # einmalig, lokal (pdftotext -bbox): Ist 2024 aus dem Jahresabschluss 2024
    "haushalt-investitionen": haushaltsplan.investitionen,  # einmalig, lokal (pdftotext -bbox): Teilfinanzplan A
    "haushalt-pruefbogen-erweiterung": haushaltsplan.pruefbogen_erweiterung,  # einmalig: Prüfbogen Ist 2024 und Investitionen
    "haushalt-ist2024-investitionen": haushaltsplan.ist2024_investitionen,  # einmalig, lokal: Ist 2024 der Investitionen
    "haushalt-pruefbogen-erweiterung-finanz": haushaltsplan.pruefbogen_erweiterung_finanz,  # einmalig: Ergänzung des Prüfbogens
    "haushalt-ertragsarten": haushaltsplan.ertragsarten,  # einmalig, lokal (pdftotext -bbox): Ertragsarten (Zeilen 1–10)
    "haushalt-pruefbogen-ertragsarten": haushaltsplan.pruefbogen_ertragsarten,  # einmalig: Prüfbogen der Ertragsarten
    "wahlen-rohdaten": wahlen.rohdaten,  # auf Knopfdruck (quellen.yml): Quelldateien der Wahl 2025 in den Branch quellen
    "wahlen-ausschnitt": wahlen.ausschnitt,  # einmalig: Wahl 2025 je Stimmbezirk und Zuordnung zum Ortsteil (Übergang)
    "kontext-ausschnitte": kontext.ausschnitte,  # einmalig: Ausschnitte für Bonn (Zensus, Bodenrichtwerte, Klima, ...)
    "fetch-haltestellen": kontext.fetch_haltestellen,  # monatlich: Haltestellen (VRS-GTFS)
    "kontext": kontext.write,  # Kontextdaten je Ortsteil (nach export)
    "kultur-stichprobe": lambda: dossier.stichprobe(kultur.THEMA),  # einmalig: Prüfbogen zur Themenseite (nach export)
    "verkehr-stichprobe": lambda: dossier.stichprobe(verkehr.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "schule-stichprobe": lambda: dossier.stichprobe(schule.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "wohnen-stichprobe": lambda: dossier.stichprobe(wohnen.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "klima-stichprobe": lambda: dossier.stichprobe(klima.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "kinder-stichprobe": lambda: dossier.stichprobe(kinder.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "soziales-stichprobe": lambda: dossier.stichprobe(soziales.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "sicherheit-stichprobe": lambda: dossier.stichprobe(sicherheit.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "wirtschaft-stichprobe": lambda: dossier.stichprobe(wirtschaft.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "digital-stichprobe": lambda: dossier.stichprobe(digital.THEMA),  # einmalig: Prüfbogen (Entwurf, aus der Datenbank)
    "soll": soll.write,  # Soll-Modell der Prozessebene: Verfahren je Vorgang, Abgleich mit den Beratungen (Audit)  # Baustellen und mögliche Umsetzungen (hoch) für die Seite
}


# Schritte der Bonner Zusatzthemen: nur, wenn das Thema in config.ZUSATZTHEMEN freigegeben ist (CLAUDE.md 5.4)
THEMA_JE_SCHRITT = {
    "baustellen": "baustellen", "kandidaten": "baustellen", "baustellen-seite": "baustellen",
    "anliegen": "anliegen", "anliegen-seite": "anliegen", "kurzfassungen": "kurzfassungen",
    "fetch-besetzung": "besetzung", "soll": "soll", "kontext": "kontext", "kontext-ausschnitte": "kontext",
    "fetch-haltestellen": "kontext", "wahlen-rohdaten": "wahlen", "wahlen-ausschnitt": "wahlen",
}
THEMA_JE_SCHRITT.update({k: "haushalt" for k in STEPS if k.startswith("haushalt-")})
THEMA_JE_SCHRITT.update({k: "themenseiten" for k in STEPS if k.endswith("-stichprobe")})


def main(argv):
    if len(argv) != 1 or argv[0] not in (*STEPS, "all"):
        raise SystemExit(__doc__)
    for step in (["fetch", "build"] if argv[0] == "all" else argv):  # export, check, verify folgen ab Phase 3/4
        thema = THEMA_JE_SCHRITT.get(step)
        if thema and not config.ZUSATZTHEMEN.get(thema):
            raise SystemExit(f"Schritt „{step}“ gehört zum Zusatzthema „{thema}“ und ist deaktiviert (config.ZUSATZTHEMEN).")
        print(f"== {step}", flush=True)
        STEPS[step]()


main(sys.argv[1:])
