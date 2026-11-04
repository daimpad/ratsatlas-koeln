"""Themenseite „Kunst und Kultur“ (thema/kunst-und-kultur/, bis 02.11.2026 „Kultur und Haushalt“ unter
thema/kultur-und-haushalt/, die alte Adresse leitet weiter): Vorlagen und Verfahren zu Kulturförderung, Bühnen und
Haushalt. Anlass und Prüfung: kultur/phase0/BERICHT.md, kultur/PRUEFUNG.md.

Die Zuordnung der Vorlagen zu den Strängen ist abgeleitet: feste Regeln aus Amt, Gremium, Titel und
Drucksachennummer (REGELN), je Vorlage mit Grund. Keine Bewertung, keine Beträge je Vorlage, keine Zitate aus den
Dokumenten; der Weg des Haushalts ist aus Mitteilungsvorlage 261064 zusammengefasst."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt

BUEHNEN = "260127"     # Stammnummer „Zukunft der Bonner Bühnen“
HAUSHALT = re.compile(r"Haushaltssatzung|Haushaltssperre|haushaltswirtschaftlich|Haushaltskonsolidierung|Konsolidierung|"
                      r"Haushaltssicherung|Eckwert|Haushaltsplan|Doppelhaushalt|Nachtragshaushalt", re.I)
FINANZEN = re.compile(r"Förder|Zuschuss|Zuschüsse|Einspar|Kürzung|Gebühr|Entgelt|Wirtschaftsplan|Festbetrag|"
                      r"Gleichbehandlung|Haushalt|Finanz|Drittmittel|Budget|Kosten|Controlling", re.I)
# Prüfung im Gespräch 25.10.2026 (kultur/PRUEFUNG.md): ein Titeltreffer zieht das ganze Verfahren (Stammnummer) mit
BUEHNEN_TITEL = re.compile(r"Bühnen|Theaterliegenschaft|Schauspiel", re.I)  # „Schauspiel“ seit 25.10.2026
KULTURFEST = re.compile(r"Kulturfest|Kultur- und Begegnungsfest", re.I)
KULTUR = Zustaendig(
    aemter=("41 ", "42 ", "45 ", "46 ", "48 "),  # Kulturamt, Stadtbibliothek, Kunstmuseum, Theater, Beethovenorchester
    # Stabsstelle Beethovenhalle (Prüfung 25.10.2026) nur mit „Beethovenhalle“ im Titel: sie betreut auch den
    # Finanzausschuss (Sitzungstermine, nichtöffentliche Tagesordnungen) und das World Conference Center
    stellen_mit_titel={"II-1 Stabsstelle Konferenzzentrum/Beethovenhalle": re.compile(r"Beethovenhalle")},
    gremien=("Kulturausschuss", "Kulturkommission"))

THEMA = Thema(
    key="kultur",
    # Name wie die anderen Themenseiten (Entscheidung 02.11.2026); der Strang zum Haushalt bleibt
    pfad="thema/kunst-und-kultur/",
    alte_pfade=("thema/kultur-und-haushalt/",),
    titel="Kunst und Kultur",
    lead="Welche Vorlagen und Verfahren betreffen Kunst und Kultur in Bonn – die Kulturförderung, die Bühnen und den "
         "Haushalt der Stadt? "
         "Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, "
         "wann und wo darüber beraten wird.",
    seo_text="Kunst und Kultur in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Kulturförderung, Bühnen und "
             "Haushalt 2027/2028 in vier Strängen, der Weg des Haushalts und die nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("haushalt", "Haushalt und Konsolidierung",
         "Titel nennt Haushaltssatzung, Haushaltssperre, haushaltswirtschaftliche Lage, Konsolidierung, Eckwerte o. Ä."),
        ("buehnen", "Zukunft der Bonner Bühnen",
         f"Drucksache {BUEHNEN} und ihre Folgevorlagen sowie Verfahren, in denen ein Titel „Bühnen“, "
         "„Theaterliegenschaften“ oder „Schauspiel“ nennt"),
        ("kultur_finanzen", "Kulturförderung, Zuschüsse, Gebühren",
         "Kulturamt, Stadtbibliothek, Kunstmuseum, Theater, Beethovenorchester oder Stabsstelle Beethovenhalle "
         "(nur mit „Beethovenhalle“ im Titel) federführend oder Beratung im Kulturausschuss bzw. in der Kulturkommission, und der Titel nennt Förderung, "
         "Zuschüsse, Einsparung, Gebühren, Entgelte, Wirtschaftsplan, Finanzierung, Controlling o. Ä.; dazu Verfahren, "
         "in denen ein Titel ein Kulturfest nennt"),
        ("kultur_weitere", "Weitere Vorlagen aus Kulturamt und Kulturausschuss",
         "wie zuvor, ohne Bezug zu Geld im Titel"),
    ],
    regeln=[
        Regel("buehnen", stammnummer=BUEHNEN),
        Regel("buehnen", verfahren_titel=BUEHNEN_TITEL),
        Regel("kultur_finanzen", verfahren_titel=KULTURFEST),
        Regel("haushalt", titel=HAUSHALT),
        Regel("kultur_finanzen", zustaendig=KULTUR, titel=FINANZEN, sonst="kultur_weitere"),
    ],
    eingeklappt={"kultur_weitere"},  # vollständig, auf der Seite eingeklappt (Entscheidung 25.10.2026)
    punkt_straenge=("haushalt", "buehnen", "kultur_finanzen"),
    # Prozessbild: Bahnen von oben nach unten (Schlüssel, Beschriftung) und die Gremien eigener Bahnen
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("kultur", "Kulturausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"kultur": KULTUR.gremien},
    sitzungen=("Kulturausschuss", "Kulturkommission", "Ausschuss für Finanzen, Beteiligungen und Vergabe",
               "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,  # Bezirksvertretungen: je eine (Haushaltsberatung und Einwohnerfragestunde, GeschO § 26)
    # Zeitachse: der Rückblick gestaucht, die Monate der Haushaltsberatung breiter
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("kultur"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für die Kultur der Kulturausschuss"),
    # Vergleich: Zahl der Vorlagen im Verfahren zur Haushaltssatzung 2025/2026
    vergleich="240986",
    vergleich_text="Zum Vergleich: Zum Doppelhaushalt 2025/2026 ({ref}) gehören im Ratsinformationssystem "
                   "{n} Vorlagen, vor allem Änderungsanträge und Stellungnahmen der Verwaltung.",
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln, je Vorlage mit Grund); Schritte des Haushalts aus "
            "Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Kunst und Kultur in Rat, Ausschüssen und Bezirksvertretungen",
    feed_text="zu Kunst und Kultur",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 25.10.2026 von Hand geprüft (keine unpassend), danach "
                  "wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Zahlen je Einrichtung stehen in den Dokumenten der Vorlagen und im Haushaltsplan "
        "der Stadt (Produktbereich 1.04 Kultur und Wissenschaft, auf bonn.de), nicht in den Daten des "
        "Ratsinformationssystems. Die Seite übernimmt keine Beträge je Vorlage; Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Vorbereitung in der Verwaltung:</strong> Eckwerte, Aufgabenkritik und Beratungen des "
        "Verwaltungsvorstands sind nicht öffentlich.",
        "<strong>Nichtöffentliche Beratungen</strong> und Vorlagen, deren Titel keines der Merkmale nennt, fehlen.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter
    # Vorlagen mit Kulturbezug im Titel; Sportplätze und Straßennamen nicht
    stichprobe_je_strang={"haushalt": 4, "buehnen": 4, "kultur_finanzen": 7, "kultur_weitere": 7},
    stichprobe_ohne=8,
    kandidat=re.compile(r"Kultur|Theater|Museum|Bibliothek|Oper\b|Musik(?!erviertel)|Kunst(?!rasen)|Beethoven|Bühne|"
                        r"Festival|Konzert|Orchester", re.I),
    farben=("#6d28d9", "#7c3aed", "#db2777"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    produktbereich="04",  # Haushalt: Ist und Plan dieses Produktbereichs (Entscheidung 27.10.2026)
    fachausschuss="Kulturausschuss",  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
