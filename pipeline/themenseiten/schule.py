"""Themenseite „Schule und Bildung“ (thema/schule-und-bildung/). Phase 0 und Entscheidungen: schule/phase0/BERICHT.md;
Prüfbogen im Gespräch geprüft am 26.10.2026, danach Regeln A–C (schule/PRUEFUNG.md).

Eigene Regeln statt der vorhandenen Themenzuordnung (dort trifft „Bildung“ auch die Bildung von Ausschüssen):
Schulamt, Schulausschuss und Wörter für Schulen im Titel. Nur Schulen, ohne Kitas, Musikschule und Weiterbildung
(Entscheidung 26.10.2026). Keine Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt

# „Schulstraße“ in der Einzahl ist meist ein Straßenname (Prüfung 26.10.2026: Lengsdorf); es zählen nur
# „Schulstraßen“ und „eine(r) Schulstraße“
STRASSENNAME = r"(?!straße\b)"
SCHULSTRASSE = r"Schulstraßen|\beiner? Schulstraße"
# Wörter für Schulen; nicht Volkshochschule, Musikschule, Hochschule, Kunst- oder Tanzschule, nicht „Schulden“,
# nicht „Vorschul…“ (Kinder vor der Einschulung, Prüfung 26.10.2026)
SCHULE = re.compile(SCHULSTRASSE + r"|(?<!volkshoch)(?<!musik)(?<!hoch)(?<!kunst)(?<!tanz)(?<!vor)Schul(?!d)"
                    + STRASSENNAME + r"|Gymnasi|Berufskolleg|Förderzentrum|\bOGS\b|Ganztag|Schüler", re.I)
SCHULWEG = re.compile(SCHULSTRASSE + r"|Schulweg|Elterntaxi|Schülerverkehr|Schüler\S*\s?-?Ticket|Schülerticket|Schulbus|Querung|"
                      r"Ampel|Zebrastreifen|Tempo|Fußgänger|Radweg|Fahrrad|Verkehr|Haltestelle|Parken|Parkpl", re.I)
BAU = re.compile(r"Neubau|Sanierung|saniert|Erweiterung|Umbau|Ausbau|Modulbau|Container|Interim|Turnhalle|"
                 r"Sporthalle|Mensa|Toilette|Schulhof|Brandschutz|Schulbau|Gebäude|Pavillon|Dach", re.I)
# Errichtung und Gründung nur einer Schule (Prüfung 26.10.2026: „Errichtung einer Schranke“)
PLAETZE = re.compile(r"\bOGS\b|Ganztag|Zügigkeit|zügig|Schulplätze|(?:Errichtung|Gründung) (?:einer|eines|der|des) "
                     r"(?:\S+ )?\S*(?:schule|Gymnasium|Berufskolleg|Förderzentrum)|Auflösung|Anmelde|Kapazität|"
                     r"Eingangsklasse|Schulentwicklung|Aufnahme|Schulnetz|Klassenbildung|Betreuung", re.I)
# Sammellisten nichtöffentlicher Punkte und Formalien des Ausschusses
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte in nichtöffentlicher Sitzung|Bestellung der Schriftführung|"
                        r"Volkshochschule|Musikschule|\bKita|Kindertages|Kindergarten|KiBiz", re.I)
SCHULAMT = Zustaendig(aemter=("40 ",), gremien=("Schulausschuss",))
SCHULGREMIEN = ("Schulausschuss",)

THEMA = Thema(
    key="schule",
    pfad="thema/schule-und-bildung/",
    titel="Schule und Bildung",
    lead="Welche Vorlagen und Verfahren betreffen die Schulen in Bonn – Schulbau, Schulplätze, Ganztag und Schulwege? "
         "Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, "
         "wann und wo darüber beraten wird. Kitas und Weiterbildung gehören nicht dazu.",
    seo_text="Schulen in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Schulbau und Sanierung, Schulplätzen "
             "und Ganztag, Schulwegen und Schülerticket, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("schulweg", "Schulweg und Schülerticket",
         "Titel nennt eine Schule und Schulweg, Schulstraßen, Elterntaxi, Schülerticket, Querung, Ampel, Zebrastreifen, Tempo, "
         "Radweg, Haltestelle, Parken o. Ä."),
        ("bau", "Schulbau und Sanierung",
         "Titel nennt eine Schule und Neubau, Sanierung, Erweiterung, Umbau, Interim, Container, Turnhalle, Mensa, "
         "Toiletten, Schulhof, Brandschutz o. Ä."),
        ("plaetze", "Schulplätze und Ganztag",
         "Titel nennt eine Schule und Zügigkeit, Errichtung oder Gründung einer Schule, Anmeldungen, Kapazität, "
         "Schulentwicklung, Betreuung oder den offenen Ganztag (OGS)"),
        ("weitere", "Weitere Vorlagen zu Schulen",
         "Schulamt federführend, Beratung im Schulausschuss oder eine Schule im Titel, ohne die Merkmale der anderen "
         "Stränge; ohne Kitas, Musikschule, Volkshochschule und Sammellisten nichtöffentlicher Punkte"),
    ],
    regeln=[
        Regel("schulweg", titel=SCHULWEG, bedingung=SCHULE),
        Regel("bau", titel=BAU, bedingung=SCHULE),
        Regel("plaetze", titel=PLAETZE, bedingung=SCHULE),
        Regel("weitere", zustaendig=SCHULAMT),
        Regel("weitere", titel=SCHULE),
    ],
    ausschluss=AUSSCHLUSS,
    eingeklappt={"weitere"},
    punkt_straenge=("schulweg", "bau", "plaetze", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss, Schulausschuss oder Betriebsausschuss SGB (Schulbau)
    punkt_gremien=("Rat", "Hauptausschuss", "Betriebsausschuss SGB") + SCHULGREMIEN,
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("schule", "Schulausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"schule": SCHULGREMIEN},
    sitzungen=SCHULGREMIEN + ("Betriebsausschuss SGB", "Ausschuss für Finanzen, Beteiligungen und Vergabe",
                              "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("schule"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für die Schulen der Schulausschuss"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Gremium und Wörtern im Titel, je Vorlage "
            "mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Schulen in Rat, Hauptausschuss, Schulausschuss und Bezirksvertretungen",
    feed_text="zu Schulen",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 26.10.2026 im Gespräch geprüft (18 passend, 3 teilweise, "
                  "3 unpassend; in der Gegenprobe fehlte keine von 6), danach wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten von Schulbau und Sanierung stehen in den Dokumenten der Vorlagen und im "
        "Haushaltsplan der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je Vorlage; Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Kitas und Weiterbildung</strong> gehören nicht zu dieser Seite.",
        "<strong>Nichtöffentliche Beratungen</strong> (etwa Sammellisten des Schulausschusses) und Vorlagen, deren "
        "Titel keine Schule nennt und die weder das Schulamt noch der Schulausschuss behandelt, fehlen.",
    ],
    stichprobe_je_strang={"schulweg": 6, "bau": 6, "plaetze": 6, "weitere": 6},
    stichprobe_ohne=6,
    # Gegenprobe: Titel ohne Schulwort, die Schulen betreffen könnten (Sport- und Turnhallen, Kinder und Jugendliche)
    kandidat=re.compile(r"Sporthalle|Turnhalle|Unterricht|Klasse|Lehrer|Abitur|Bildungszugang|Kindern und Jugendlichen",
                        re.I),
    farben=("#b45309", "#d97706", "#f59e0b"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<path d="M2 9 12 4l10 5-10 5z"/><path d="M6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5M22 9v5"/>',
    produktbereich="03",  # Haushalt: Ist und Plan dieses Produktbereichs (Entscheidung 27.10.2026)
    fachausschuss=SCHULGREMIEN[0],  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
