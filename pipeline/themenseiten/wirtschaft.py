"""Themenseite „Wirtschaft und Wissenschaft“ (thema/wirtschaft-und-wissenschaft/). Phase 0 und Entscheidungen:
themen/phase0/WEITERE.md (Abschnitt c), wirtschaft/PHASE1.md; Prüfbogen im Gespräch geprüft am 02.11.2026, Regeln
unverändert (wirtschaft/PRUEFUNG.md).

Eigene Regeln (Entscheidungen 02.11.2026): Amt für Wirtschaftsförderung (03, mit der Abteilung 03-4 Liegenschaften),
Amt für Internationales und globale Nachhaltigkeit (02), Ausschuss für Wirtschaft, Liegenschaften und Arbeit und
Ausschuss für Wissenschaft, Europa und Internationales sowie Wörter im Titel. Digitalisierung und Verwaltung stehen auf
der Seite Digitale Verwaltung. Liegenschaften, die auf der Seite Wohnen und Bauen stehen, bleiben dort (Regel-Feld
ohne_seite). Mehrdeutige Wörter: „Wirtschaft“ nicht in Wirtschaftsplan, haushaltswirtschaftlich, Parkraumbewirtschaftung
oder Organen wirtschaftlicher Unternehmen; „Liegenschaften“ nicht in Theaterliegenschaften oder beim Energieverbrauch
kommunaler Liegenschaften. Keine Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt, kinder, klima, kultur, schule, sicherheit, soziales, verkehr, wohnen

WIRTSCHAFT = "Ausschuss für Wirtschaft, Liegenschaften und Arbeit"
WISSENSCHAFT = "Ausschuss für Wissenschaft, Europa und Internationales"
FINANZ = "Ausschuss für Finanzen, Beteiligungen und Vergabe"

# „Wirtschaft“ nur in eindeutigen Wörtern (nicht Wirtschaftsplan, haushaltswirtschaftlich, Bewirtschaftung,
# wirtschaftliche Unternehmen, Landwirtschaft); Unternehmen nicht als kommunale Unternehmen oder Beteiligungen
# (Ausschluss); Gründung nur von Unternehmen; Glasfaser nur als Ausbau (nicht ein Verteiler als Ortsangabe); die Region
# Bonn als Standort für Cybersicherheit und „Hightech Spaces“ gehören hierher, nicht zur digitalen Verwaltung (vor dem
# Ziehen des Prüfbogens, 02.11.2026)
WIRTSCHAFT_ARBEIT = re.compile(
    r"Wirtschaftsförder|Wirtschaftsbericht|Wirtschaftsgespräch|Wirtschaftsdelegation|Wirtschaftsstandort|"
    r"Wirtschaftsraum|Wirtschaftsfläche|Service Center Wirtschaft|(?:die|der) Wirtschaft\b|"
    r"(?<![\w-])Unternehme[nr](?!.{0,3}Mobilitätsmanagement)|Unternehmens(?:betreuung|ansiedlung|service)|"
    r"Gründungstätigkeit|Gründer|Existenzgründ|Start-?ups?\b|Start-?up-|Digital Hub|Gewerbegebiet|Gewerbefläche|"
    r"Gewerbestandort|Gewerbepark|Gewerbehof|(?<![\w-])Industrie|Handwerk|Mittelstand|Büromarkt|Arbeitsmarkt|"
    r"Ausbildungsmarkt|Fachkräfte|Beschäftigungsförder|Arbeitsplätze|Langzeitarbeitslos|Region Köln/Bonn|"
    r"Glasfaserausbau|Breitband|Klimaschutzangebote für die Wirtschaft|Region Bonn als Zentrum|Hightech", re.I)
# Zentren, Einzelhandel, Tourismus und Stadtmarketing; die Beethovenhalle steht auf der Kulturseite; nicht
# „Congress“ allein (UCLG World Congress gehört zu Internationales) und nicht die Beherbergungssteuer (vor dem Ziehen
# des Prüfbogens, 02.11.2026)
ZENTREN = re.compile(r"Touris|Bonn-Information|Stadtmarketing|Marketingkonzept|Imagekampagne|Image- und Marketing|"
                     r"Kommunikationskampagne|Nachtbürgermeister|Nachtleben|Nachtökonomie|Einzelhandel|Zentrenkonzept|"
                     r"Zentrenmanagement|Innenstadtmanagement|City-?Marketing|Kongressstandort|WorldCCBonn|\bWCCB\b|"
                     r"Stadtrundfahrt|Stadtführung|Lagebild Innenstadt|Runder Tisch Innenstadt|Erreichbarkeit der Stadt|"
                     r"Geschäftssituation|Geschäftsstraße|Gewerbetreibende", re.I)
# Grundstücke und Gebäude der Stadt; nicht Theaterliegenschaften (Kultur), Energieverbrauch und Photovoltaik
# kommunaler Liegenschaften (Klima), Bauanträge auf Grundstücken (Ausschluss)
LIEGENSCHAFTEN = re.compile(r"(?<![\w-])Liegenschaft(?!en und Arbeit)|Grundstücksgeschäft|Ankaufsrecht|Ankaufsbemüh|"
                            r"Veräußerung|Verpachtung|Erbbaurecht|Zwischennutzung|Amerikanische[nr]? Club|"
                            r"Open Embassy|Viktoriabad|Stadthalle|Leerstand von Infrastruktur", re.I)
# Wissenschaft (nicht „wissenschaftlich“), Hochschulen, Vereinte Nationen, Europa, Städtepartnerschaften und
# internationale Zusammenarbeit; nicht Sportturniere, Universitätsklinikum, Haltestellen und Campus-Bauprojekte, nicht
# „EU-“ in Verordnungen und Richtlinien (Kunstrasen, Luftqualität), nicht „Partnerschaften“ allein (Verband binationaler
# Familien und Partnerschaften) – vor dem Ziehen des Prüfbogens, 02.11.2026
WISSENSCHAFT_INTERNATIONAL = re.compile(
    r"(?-i:Wissenschaft)(?!lich)|Hochschul|Universität(?!sklinik|/Markt|s-Campus)|(?<![\w-])Forschung|"
    r"Studierende(?!nwohnheim)|(?-i:\bUN\b(?! Campus)|UN-(?!Campus)|\bVN-)|Vereinte[nr]? Nationen|"
    r"Internationales\b|internationale[nrsm]? (?:Konferenz|Veranstaltung|Bezug|Wissenschaft|Demokratiepreis|"
    r"Strafgerichtshof|Studierende|Zusammenarbeit|Friendship)|Demokratiepreis|Völkerrecht|"
    r"Europäische[nr]? Union|Europas\b|Eurocities|eumayors|\bEZMW\b|ECMWF|Europäisches Zentrum|"
    r"Städtepartnerschaft|städtepartnerschaftlich|Partnerst[aä]dt|Jahrespartnerschaft|Projekt-?\)? ?Partnerschaft|"
    r"gesamtstädtischer Partnerschaft|"
    r"Berlin/Bonn|Bonn-Berlin|Bonn/Berlin|Zusatzvereinbarung|(?<![\w-])Delegation|\bUCLG\b|Weltverband|"
    r"World Urban Forum|\bAWEI\b|globale Nachhaltigkeit|Entwicklungszusammenarbeit|Eine Welt", re.I)
# Formalien (Schriftführung, Sitzungstermine, Vorsitz, Benennungen, Vertretung in Organen und Aufsichtsräten),
# Sammellisten nichtöffentlicher Punkte, Wirtschaftspläne, Jahresabschlüsse und Entlastungen von Eigenbetrieben und
# Beteiligungen, Haushaltslage, Theaterliegenschaften (Kultur), Energieverbrauch und Photovoltaik kommunaler
# Liegenschaften (Klima), Parken und Bewirtschaftung von Parkraum (Verkehr), Bauanträge und Fällgenehmigungen auf
# Grundstücken; vor dem Ziehen des Prüfbogens (02.11.2026): Vergütung in kommunalen Unternehmen, Lieferungen für die
# Liegenschaften der Verwaltung, „Feuerwehrtopf“ (Sicherheit), Anfragen zur Beethovenhalle (Kultur; eine Veranstaltung
# „in der Beethovenhalle“ bleibt), Projektbeiräte („Bildung und Besetzung“, auch „nicht-öffentlicher Sitzung“)
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte? (?:zur Beratung )?in nicht[- ]?öffentlicher Sitzung|"
                        r"Punkte der nicht[- ]?öffentlichen Sitzung|Bildung und Besetzung|"
                        r"Bestellung (?:der|zur) Schriftführung|Sitzungstermine|"
                        r"Wahl (?:des|der)[ /].{0,20}Vorsitz|stellvertretenden Vorsitz|Benennung|Nachbenennung|"
                        r"Ersatzbenennung|Ersatzbestellung|Entsendung von|Zuständigkeitsordnung|Bestellung von Mitgliedern|"
                        r"Vertretung der (?:Bundes)?[Ss]tadt Bonn in|Vertretung der Stadt Bonn im|Vertreter/-innen für|"
                        r"Aufsichtsrat|Gesellschafterversammlung|Wirtschaftsplan|Jahresabschluss|Wirtschaftsjahr|"
                        r"Wirtschaftsprüf|Entlastung de|haushaltswirtschaftlich|personalwirtschaftlich|Bewirtschaftung|"
                        r"Theaterliegenschaft|Energieverbrauch|Photovoltaik|\bParken\b|Parkpl[aä]tz|Wirtschaftsparkpl|"
                        r"Mobilitätsmanagement|Grundstück(?: in |: )|Baugrundstück|Fällgenehmigung|kommunalen Unternehmen|"
                        r"Beteiligungsunternehmen|Feuerwehrtopf|Lieferung von|(?<!in der )Beethovenhalle", re.I)
AEMTER = Zustaendig(aemter=("03 ",))
LIEGENSCHAFTEN_ABT = Zustaendig(abteilungen=("03-4 ",))
INTERNATIONAL_AMT = Zustaendig(aemter=("02 ",))
AUSSCHUESSE = Zustaendig(gremien=(WIRTSCHAFT, WISSENSCHAFT))
# „weitere“: Vorlagen des Amts 03 oder der Ausschüsse, die auf einer veröffentlichten Themenseite stehen, bleiben dort
# (z. B. Mitberatung von „Rhein in Flammen“, Handlungskonzept Wohnen, Abfallvermeidung)
ANDERE = (kultur.THEMA, verkehr.THEMA, schule.THEMA, wohnen.THEMA, klima.THEMA, kinder.THEMA, soziales.THEMA,
          sicherheit.THEMA)

THEMA = Thema(
    key="wirtschaft",
    pfad="thema/wirtschaft-und-wissenschaft/",
    titel="Wirtschaft und Wissenschaft",
    lead="Welche Vorlagen und Verfahren betreffen Wirtschaft, Arbeit und Wissenschaft in Bonn – Wirtschaftsförderung "
         "und Arbeitsmarkt, Tourismus und Innenstädte, Grundstücke und Gebäude der Stadt, Hochschulen, die UN-Stadt und "
         "internationale Beziehungen? Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der "
         "Wahlperiode ({seit}) und zeigt, wann und wo darüber beraten wird. Digitalisierung steht auf der Seite "
         "Digitale Verwaltung.",
    seo_text="Wirtschaft und Wissenschaft in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Wirtschaftsförderung, "
             "Arbeit, Tourismus, Liegenschaften, Wissenschaft und Internationalem, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("wirtschaft", "Wirtschaftsförderung und Arbeit",
         "Titel nennt Wirtschaftsförderung, den Wirtschaftsbericht, Unternehmen, Gründungen und Start-ups, "
         "Gewerbeflächen, Industrie und Handwerk, den Arbeits- und Ausbildungsmarkt, Fachkräfte oder den Glasfaserausbau"),
        ("zentren", "Tourismus, Zentren und Stadtmarketing",
         "Titel nennt Tourismus, die Bonn-Information, Stadtmarketing und Imagekampagnen, Einzelhandel und Zentren, "
         "Kongresse oder den Nachtbürgermeister"),
        ("liegenschaften", "Liegenschaften",
         "Titel nennt Liegenschaften, Grundstücksgeschäfte, Verkauf, Verpachtung oder Zwischennutzung städtischer "
         "Flächen und Gebäude (z. B. Amerikanischer Club, Viktoriabad, Stadthalle Bad Godesberg); dazu Vorlagen der "
         "Abteilung Liegenschaften (03-4); nicht Theaterliegenschaften und nicht Vorlagen der Seite Wohnen und Bauen"),
        ("wissenschaft", "Wissenschaft und Internationales",
         "Titel nennt Wissenschaft, Hochschulen, Forschung, Studierende, die Vereinten Nationen, Europa, "
         "Städtepartnerschaften, das Berlin/Bonn-Gesetz oder internationale Konferenzen; dazu Vorlagen, die das Amt für "
         "Internationales und globale Nachhaltigkeit (02) federführend betreut"),
        ("weitere", "Weitere Vorlagen zu Wirtschaft und Wissenschaft",
         "Amt für Wirtschaftsförderung (03) federführend oder Beratung im Wirtschaftsausschuss oder im "
         "Wissenschaftsausschuss, ohne die Merkmale der anderen Stränge und ohne Vorlagen, die auf einer anderen "
         "Themenseite stehen; ohne Formalien und Sammellisten nichtöffentlicher Punkte"),
    ],
    regeln=[
        Regel("liegenschaften", titel=LIEGENSCHAFTEN, ohne_seite=wohnen.THEMA),
        Regel("wirtschaft", titel=WIRTSCHAFT_ARBEIT),
        Regel("zentren", titel=ZENTREN),
        Regel("wissenschaft", titel=WISSENSCHAFT_INTERNATIONAL),
        Regel("liegenschaften", zustaendig=LIEGENSCHAFTEN_ABT, ohne_seite=wohnen.THEMA),
        Regel("wissenschaft", zustaendig=INTERNATIONAL_AMT),
        Regel("weitere", zustaendig=AEMTER, ohne_seite=ANDERE),
        Regel("weitere", zustaendig=AUSSCHUESSE, ohne_seite=ANDERE),
    ],
    ausschluss=AUSSCHLUSS,
    eingeklappt={"weitere"},
    punkt_straenge=("wirtschaft", "zentren", "liegenschaften", "wissenschaft", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss, Wirtschafts- oder Wissenschaftsausschuss
    # (Entscheidung 02.11.2026)
    punkt_gremien=("Rat", "Hauptausschuss", WIRTSCHAFT, WISSENSCHAFT),
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("wirtschaft", "Wirtschaftsausschuss"),
            ("wissenschaft", "Wissenschaftsausschuss"), ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"),
            ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"wirtschaft": (WIRTSCHAFT,), "wissenschaft": (WISSENSCHAFT,)},
    sitzungen=(WIRTSCHAFT, WISSENSCHAFT, FINANZ, "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("wirtschaft") + [("wissenschaft", "2026-10-01", "2026-11-30", "Beratung des Haushalts",
                                             False)],
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Wirtschaft und Wissenschaft der Ausschuss für Wirtschaft, Liegenschaften und "
                               "Arbeit und der Ausschuss für Wissenschaft, Europa und Internationales"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Abteilung, Gremium und Wörtern im Titel, je "
            "Vorlage mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Wirtschaft und Wissenschaft in Rat, Hauptausschuss, Wirtschaftsausschuss, "
               "Wissenschaftsausschuss und Bezirksvertretungen",
    feed_text="zu Wirtschaft und Wissenschaft",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 02.11.2026 geprüft (Vorschlag einer KI, im Gespräch von "
                  "Hand bestätigt: 21 passend, 3 teilweise, 1 unpassend; in der Gegenprobe fehlte keine von 5); die "
                  "Regeln blieben unverändert.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten, Erlöse, Mieten und Zuschüsse stehen in den Dokumenten der Vorlagen und im "
        "Haushaltsplan der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je "
        "Vorlage. Der Produktbereich 15 „Wirtschaft und Tourismus“ im Abschnitt „Haushalt“ besteht im Plan 2026 zum "
        "größten Teil aus dem World Conference Center Bonn (21,1 Mio. €) und der Beethovenhalle (6,0 Mio. €; sie steht "
        "auf der Seite Kunst und Kultur); auf die Wirtschaftsförderung entfallen 4,0 Mio. €, auf den Tourismus "
        "2,0 Mio. €. Wissenschaft und Internationales gehören nicht zu diesem Produktbereich.",
        "<strong>Einzelne Grundstücksgeschäfte</strong> werden meist nichtöffentlich beraten und erscheinen nicht. "
        "Nichtöffentliche Beratungen fehlen.",
        "<strong>Digitalisierung</strong> der Verwaltung steht auf der Seite Digitale Verwaltung. Liegenschaften mit "
        "Wohnbezug (Wohnraum, Bebauungspläne) stehen auf der Seite Wohnen und Bauen, Theaterliegenschaften und die "
        "Beethovenhalle auf der Seite Kunst und Kultur, Parken auf der Seite Verkehr und Mobilität.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter Vorlagen
    # mit Wörtern des Themas am Wortanfang
    stichprobe_je_strang={"wirtschaft": 5, "zentren": 5, "liegenschaften": 5, "wissenschaft": 5, "weitere": 5},
    stichprobe_ohne=5,
    # Wortanfänge: nicht Landwirtschaft, Parkraumbewirtschaftung, haushaltswirtschaftlich, Beteiligungsunternehmen,
    # Theaterliegenschaften, naturwissenschaftlich, Einzelhandel; nicht „Arbeit“ allein (Arbeitsprogramm,
    # Arbeiterwohlfahrt), nicht der Europaring
    kandidat=re.compile(r"(?<![\w-])Wirtschaft|(?<![\w-])Unternehm|(?<![\w-])Gewerbe|"
                        r"(?<![\w-])Arbeit(?:smarkt|splätze|slos|geber|skräfte|sförder)|(?<![\w-])Liegenschaft|"
                        r"(?<![\w-])Grundst[uü]ck|(?<![\w-])Wissenschaft|(?<![\w-])Hochschul|(?<![\w-])Internationa|"
                        r"(?<![\w-])Europ(?!aring)|(?<![\w-])Touris|(?<![\w-])Handel|(?<![\w-])Stadtmarketing", re.I),
    farben=("#3730a3", "#4f46e5", "#818cf8"),  # Übersicht thema/: Schrift, Verlauf (Indigo)
    symbol='<path d="M3 20h18"/><path d="M6 16v-3M10.5 16V9M15 16v-5M19.5 16V5"/><path d="M5 9l5-4 4 3 6-5"/>',
    produktbereich="15",  # Haushalt: Wirtschaft und Tourismus (Entscheidung 02.11.2026)
    fachausschuss=(WIRTSCHAFT, WISSENSCHAFT),  # Kasten „Wer berät mit“: beide Ausschüsse (Entscheidung 02.11.2026)
)
