"""Themenseite „Kinder, Jugend und Familie“ (thema/kinder-jugend-und-familie/). Phase 0 und Entscheidungen:
themen/phase0/WEITERE.md, kinder/PHASE1.md; Prüfbogen im Gespräch geprüft am 02.11.2026, danach Regeln A und B
(kinder/PRUEFUNG.md).

Eigene Regeln (Entscheidungen 02.11.2026): Amt für Kinder, Jugend und Familie (51), Ausschuss für Kinder, Jugend und
Familie, Beirat Kinder- und Jugendbeteiligung (nur mit Kindern oder Jugend im Titel) und Wörter im Titel. Spielplätze
stehen hier und auf der Klimaseite; Offener Ganztag und Schulsozialarbeit bleiben auf der Schulseite. Kitas, die nur
als Ort genannt werden (Parken, Querungen), gehören zum Verkehr. Keine Bewertung, keine Beträge je Vorlage, keine
Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt

AUSSCHUSS = "Ausschuss für Kinder, Jugend und Familie"
BEIRAT = "Beirat Kinder- und Jugendbeteiligung"
OHNE = "verkehr"  # Kitas und Spielplätze als bloße Ortsangabe (Parken, Querung, Tempo) bleiben beim Verkehr

KITA = re.compile(r"\bKita|Kindertages|Kindergarten|Kindergärten|KiBiz|Familienzentr|\bU3\b|Kinderbetreuung|"
                  r"Betreuungs(?:lücke|zeiten|reduktion|angebot)|Tagespflege|Elternbeitr|Jugendamtselternbeirat|"
                  r"vorschulisch", re.I)
# Skateanlagen, nicht Wettbewerbe im Skateboarding (vor dem Ziehen des Prüfbogens, 02.11.2026)
SPIEL = re.compile(r"Spielplatz|Spielplätze|Spielfläche|Sandspiel|Bolzplatz|Skateanlage|Skatepark|Pumptrack|Kletterturm|"
                   r"Spielgerät|kinderfreundlich", re.I)
BETEILIGUNG = re.compile(r"Kinder- und Jugendbeteiligung|Jugendbeteiligung|Jugendrat|Jugendparlament|Kinderrechte|"
                         r"Jugendrechte|Weltkindertag", re.I)
JUGEND = re.compile(r"Jugendzentr|Jugendtreff|Jugendarbeit|Jugendförder|Jugendverb|Jugendring|Jugendeinricht|"
                    r"Gewaltprävention|Streetwork|Jugendsozialarbeit|Ferienfreizeit|Ferienangebot|Jugendkultur|"
                    r"Community-Zentr", re.I)
# „Familie“ nicht im Namen des Amts, nicht in „Familienfest“ und nicht in Haustypen (Ausschluss); nicht
# „Elternbefragung“ (meist zu Schulplätzen) – vor dem Ziehen des Prüfbogens, 02.11.2026
FAMILIE = re.compile(r"Frühen? Hilfen|Kinderschutz|Hilfen? zur Erziehung|Jugendhilfe|Inklusionsassistenz|"
                     r"(?<!Jugend und )\bFamilie\b|Familien(?!fest)|Kinderarmut|kinderstark|Unterhaltsvorschuss|Vormund|"
                     r"Pflegekind|Adoption|Kinder- und Jugendgesundheit|Alleinerziehend", re.I)
KINDER_JUGEND = re.compile(r"Kinder|Jugend", re.I)
# Regel B (Prüfung 02.11.2026): Angebote für Kinder und Jugendliche ohne eigenes Fachwort (freier Eintritt in den Bädern)
JUNGE_MENSCHEN = re.compile(r"(?:für|von) Kinder(?:n)? und Jugendliche|junge[nr]? Menschen", re.I)
# Formalien und Sammellisten nichtöffentlicher Punkte; Bauanträge auf Grundstücken; Haustypen; Offener Ganztag und
# Schulsozialarbeit stehen auf der Schulseite (Entscheidung 02.11.2026); Kitas als bloße Ortsangabe bei Parken,
# Winterdienst, Laternen, Abfallbehältern und Wahlwerbung (vor dem Ziehen des Prüfbogens, 02.11.2026)
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte? in nichtöffentlicher Sitzung|Punkte der nichtöffentlichen Sitzung|"
                        r"Bestellung (?:der|zur) Schriftführung|Sitzungstermine|Wahl (?:des|der)[ /].{0,20}Vorsitz|"
                        r"stellvertretenden Vorsitz|Benennung von sachkundigen|Nachbenennung|Ersatzbenennung|"
                        r"Entsendung von|Zuständigkeitsordnung|Grundstück in Bonn|(?:Ein|Zwei|Mehr)familien|"
                        r"Offene[nrs]? Ganztag|\bOGS\b|Schulsozialarbeit|Parksituation|\bParken\b|Halteverbot|"
                        r"Winterdienst|Straßenlatern|Abfallbehälter|Wahlwerbung", re.I)
AMT = Zustaendig(aemter=("51 ",))
# Regel A (Prüfung 02.11.2026): Beratung im Ausschuss allein genügt nicht für Vorlagen zum Bauen (Baulandmodell,
# Berichte des Gebäudemanagements); Vorlagen, die Amt 51 federführend betreut, bleiben alle
AUSSCHUSS_BERATUNG = Zustaendig(gremien=(AUSSCHUSS, "Unterausschuss für Kinder- und Jugendhilfe"))

THEMA = Thema(
    key="kinder",
    pfad="thema/kinder-jugend-und-familie/",
    titel="Kinder, Jugend und Familie",
    lead="Welche Vorlagen und Verfahren betreffen Kinder, Jugendliche und Familien in Bonn – Kitas und "
         "Kindertagespflege, Spielplätze, Jugendarbeit, Hilfen für Familien und die Beteiligung junger Menschen? Diese "
         "Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, wann und "
         "wo darüber beraten wird. Schulen, der Offene Ganztag und die Schulsozialarbeit stehen auf der Seite Schule "
         "und Bildung.",
    seo_text="Kinder, Jugend und Familie in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Kitas, Spielplätzen, "
             "Jugendarbeit, Hilfen für Familien und Beteiligung, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("kita", "Kitas und Kindertagespflege",
         "Titel nennt Kitas, Kindertagesstätten, Kindergärten, Kindertagespflege, Familienzentren, Betreuungszeiten, "
         "Elternbeiträge oder das Kinderbildungsgesetz (KiBiz); nicht Verkehr"),
        ("spiel", "Spielplätze und Freiflächen",
         "Titel nennt Spielplätze, Spielflächen, Bolzplätze, Skate- oder Pumptrack-Anlagen, Spielgeräte oder eine "
         "kinderfreundliche Gestaltung; nicht Verkehr (Spielplätze stehen auch auf der Seite Klima und Umwelt)"),
        ("jugend", "Jugendarbeit und Jugendförderung",
         "Titel nennt Jugendzentren, Jugendtreffs, Jugendarbeit, Jugendförderung, Jugendverbände, Streetwork, "
         "Gewaltprävention oder Ferienangebote"),
        ("familie", "Familie, Kinderschutz und Hilfen",
         "Titel nennt Frühe Hilfen, Kinderschutz, Hilfen zur Erziehung, Jugendhilfe, Inklusionsassistenz, Familien, "
         "Kinderarmut, Pflegekinder oder Alleinerziehende"),
        ("beteiligung", "Beteiligung von Kindern und Jugendlichen",
         "Titel nennt Kinder- und Jugendbeteiligung, einen Jugendrat, Kinderrechte oder den Weltkindertag; dazu "
         "Vorlagen des Beirats Kinder- und Jugendbeteiligung mit Kindern oder Jugend im Titel"),
        ("weitere", "Weitere Vorlagen zu Kindern, Jugend und Familie",
         "Amt für Kinder, Jugend und Familie federführend oder Beratung im Ausschuss für Kinder, Jugend und Familie "
         "(dort ohne Vorlagen zum Bauen), Titel mit „für Kinder und Jugendliche“ oder „junge Menschen“, ohne die "
         "Merkmale der anderen Stränge; ohne Formalien und Sammellisten nichtöffentlicher Punkte"),
    ],
    regeln=[
        Regel("kita", titel=KITA, ohne_thema=OHNE),
        Regel("spiel", titel=SPIEL, ohne_thema=OHNE),
        Regel("beteiligung", titel=BETEILIGUNG),
        Regel("jugend", titel=JUGEND),
        Regel("familie", titel=FAMILIE),
        Regel("weitere", zustaendig=AMT),
        Regel("weitere", zustaendig=AUSSCHUSS_BERATUNG, ohne_thema="bauen"),
        Regel("beteiligung", titel=KINDER_JUGEND, zustaendig=Zustaendig(gremien=(BEIRAT,))),
        Regel("weitere", titel=JUNGE_MENSCHEN, ohne_thema=OHNE),
    ],
    ausschluss=AUSSCHLUSS,
    eingeklappt={"weitere"},
    nach_bezirk=frozenset({"spiel"}),  # Spielplätze je Stadtbezirk (meist in den Bezirksvertretungen beraten)
    punkt_straenge=("kita", "spiel", "jugend", "familie", "beteiligung", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss oder Ausschuss für Kinder, Jugend und Familie
    # (Entscheidung 02.11.2026)
    punkt_gremien=("Rat", "Hauptausschuss", AUSSCHUSS),
    # Beschriftung der Bahn mit dem gesetzlichen Namen (§ 71 SGB VIII), der volle Name passt nicht in die Spalte
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("kinder", "Jugendhilfeausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"kinder": (AUSSCHUSS,)},
    sitzungen=(AUSSCHUSS, BEIRAT, "Ausschuss für Finanzen, Beteiligungen und Vergabe", "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("kinder"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Kinder, Jugend und Familie der gleichnamige Ausschuss"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Gremium und Wörtern im Titel, je Vorlage "
            "mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Kinder, Jugend und Familie in Rat, Hauptausschuss, Ausschuss für Kinder, Jugend und "
               "Familie und Bezirksvertretungen",
    feed_text="zu Kindern, Jugend und Familie",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 02.11.2026 im Gespräch geprüft (23 passend, 1 teilweise, "
                  "1 unpassend; in der Gegenprobe fehlte 1 von 5), danach wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten und Zuschüsse stehen in den Dokumenten der Vorlagen und im Haushaltsplan "
        "der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je Vorlage; "
        "Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Einzelfälle</strong> der Jugendhilfe sind keine Vorlagen und erscheinen nicht. Nichtöffentliche "
        "Beratungen fehlen.",
        "<strong>Schulen</strong>, der Offene Ganztag und die Schulsozialarbeit stehen auf der Seite Schule und "
        "Bildung, Kitas und Spielplätze als bloße Ortsangabe (etwa beim Parken) auf der Seite Verkehr und Mobilität.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter Vorlagen
    # mit Kindern, Jugend, Eltern, Ferien oder Betreuung im Titel
    stichprobe_je_strang={"kita": 5, "spiel": 5, "jugend": 4, "familie": 4, "beteiligung": 3, "weitere": 4},
    stichprobe_ohne=5,
    kandidat=re.compile(r"Kinder|Jugend|Eltern|Schwimm|Ferien|Betreuung", re.I),
    farben=("#0f766e", "#0d9488", "#5eead4"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<circle cx="8" cy="5" r="2.5"/><path d="M8 8v7M5 11h6M8 15l-2 5M8 15l2 5"/><circle cx="17" cy="10" r="2"/>'
           '<path d="M17 12v4M15 14h4M17 16l-1.5 4M17 16l1.5 4"/>',
    produktbereich="06",  # Haushalt: Ist und Plan dieses Produktbereichs (Entscheidung 02.11.2026), Link in Kachel 06
    fachausschuss=AUSSCHUSS,  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
