"""Themenseite „Digitale Verwaltung“ (thema/digitale-verwaltung/). Phase 0 und Entscheidungen:
themen/phase0/WEITERE.md (Abschnitt c), digital/PHASE1.md; Prüfbogen im Gespräch geprüft am 02.11.2026, Regeln
unverändert, „weitere“ ausgeblendet, solange leer (digital/PRUEFUNG.md).

Eigene Regeln (Entscheidungen 02.11.2026): Digitalisierung, IT, Verwaltungsmodernisierung und Dienstleistung
(Bürgerdienste als Online-Angebote). Stabsstelle CDO (Dezernat OB) und die Abteilung IT des Personal- und
Organisationsamts (10-2) über die Federführung; vom Amt 10 sonst nur Vorlagen mit Wörtern des Themas im Titel, keine
Personalangelegenheiten (Wahl von Beigeordneten, Stellenplan, Personalberichte) und keine Beschaffungen von Büromöbeln
und Material. Einziger Fachausschuss: Ausschuss für Digitalisierung, Dienstleistung und Verwaltungsmodernisierung.
Vorlagen der Seite Wirtschaft und Wissenschaft (Digital Hub, Wirtschaftsstandort für Cybersicherheit) stehen nur dort
(Regel-Feld ohne_seite). Kein Haushaltsabschnitt: Digitalisierung gehört zum Produktbereich 01 Innere Verwaltung, der
fast die ganze Verwaltung umfasst. Keine Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt, kinder, klima, kultur, schule, sicherheit, soziales, verkehr, wirtschaft, wohnen

DIGITAL = "Ausschuss für Digitalisierung, Dienstleistung und Verwaltungsmodernisierung"
FINANZ = "Ausschuss für Finanzen, Beteiligungen und Vergabe"

# Strategie und Steuerung: Digitalisierungsstrategie, Dachstrategie Digitale Transformation (261619), Bestandsaufnahme,
# Daten der Stadt (Urban Data Platform, Open Data), Regeln für algorithmische Systeme
STRATEGIE = re.compile(r"Digitalisierungsstrategie|Dachstrategie|Digitale[nr]? Transformation|"
                       r"Aktivitäten zur Digitalisierung|Binnendigitalisierung|Smart City|Chief Digital|\bCDO\b|"
                       r"Urban Data|\bUDP\b|\bUDM\b|Open Data|Offene Daten|Datenstrategie|Datenplattform|"
                       r"algorithmische[nr]? System|Digitalisierungsbericht", re.I)
# Online-Dienste und Bürgerservice: Website, Termine, Online-Anträge, Bezahlen, Dienstleistungszentrum, Zugang ohne
# Internet; nicht Inhalte einzelner Internetseiten (Stadttauben, Ausschluss)
ONLINE = re.compile(r"(?<![\w-])Online|Onlinezugang|\bOZG\b|Terminbuchung|Terminvergabe|Terminportal|"
                    r"Website|Webseite|Internetauftritt|Internetseite|Homepage|Bonn-App|Bürgerservice|Bürgerwabe|"
                    r"Dienstleistungszentrum|\bDLZ\b|Bezahldienst|E-Payment|\bWero\b|digitalen? Verwaltung|"
                    r"analoge[ns]? Leben|Informationsfreiheit|\bIFG\b|Dokumentenausgabe|Bezirksverwaltungsstelle|"
                    r"Servicequalität|Erreichbarkeit der Verwaltung", re.I)
# IT, Software und Sicherheit: Betrieb, Software und Lizenzen, Open Source, IT-Sicherheit, Fachverfahren und digitale
# Projekte der Ämter; „IT“ nur in Großbuchstaben (nicht „Zweit-“, „Kurzzeit-“)
IT = re.compile(r"(?-i:\bIT\b|IT-|RegioIT)|Software|Open.?Source|(?<![\w-])Lizenz|Cyber|Informationssicherheit|"
                r"Penetrationstest|Webcheck|\bODF\b|offene[nr]? Standard|Microsoft|LOGINEO|digitale[nr]? Souveränität|"
                r"Rechenzentrum|Fachverfahren|Ticketsystem|-App\b|BlackBerry|Civitas|KI-gestützt|"
                r"Künstliche[nr]? Intelligenz|(?-i:\bKI\b)|Digitalisierungsprojekt|Automatisierung|Abstimmungstool|"
                r"Streaming", re.I)
# Verwaltungsmodernisierung und Organisation: Organisation der Verwaltung, Bürokratieabbau, Neuordnung von Dezernaten,
# Umzug der Verwaltung; nicht Personalangelegenheiten (Ausschluss); „Stadthaus“ nur als Umzug der Verwaltung (nicht
# das Stadthaus-Areal und Großbaustellen), nicht die SPNV-Strukturreform (vor dem Ziehen des Prüfbogens, 02.11.2026)
ORGANISATION = re.compile(r"Verwaltungsmodernisierung|Verwaltungsreform|Modernisierung der Verwaltung|"
                          r"Organisationsuntersuchung|Organisationsentwicklung|organisatorische[nr]? Leistungsfähigkeit|"
                          r"Neuorganisation|Aufgabenkritik|Prozessoptimierung|Bürokratieabbau|Entbürokratisierung|"
                          r"Dezernatsneuverteilung|Dezernatsverteilung|Verwaltungsstruktur|(?<!SPNV-)Strukturreform|"
                          r"Steuerungsfähigkeit|Umzug vom Stadthaus|Auszug aus dem Stadthaus|Verwaltungsgebührenordnung|"
                          r"Zentralisierung", re.I)
# Digitalisierung allgemein (Fachämter); nicht Fahrgastanzeigen (Verkehr) und digitale Lehrpfade
DIGITAL_ALLG = re.compile(r"[Dd]igital", re.I)
# Formalien und Sammellisten nichtöffentlicher Punkte; Personalangelegenheiten (Beigeordnete, Stellen und Stellenplan,
# Personalberichte, Gesundheit der Beschäftigten); Beschaffung von Büromaterial und Möbeln, Aktenvernichtung,
# Geldtransporte, Beflaggung; Inhalte einzelner Internetseiten (Stadttauben); Parken und Bewohnerparkausweise;
# Fahrgastanzeigen und digitale Lehrpfade; Vertretung im Aufsichtsrat („AR der Digital Hub AG“) – vor dem Ziehen des
# Prüfbogens, 02.11.2026
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte? (?:zur Beratung )?in nicht[- ]?öffentlicher Sitzung|"
                        r"Punkte der nicht[- ]?öffentlichen Sitzung|Bestellung (?:der|zur) Schriftführung|Sitzungstermine|"
                        r"Wahl (?:des|der)[ /].{0,20}Vorsitz|stellvertretenden Vorsitz|Benennung|Nachbenennung|"
                        r"Ersatzbenennung|Entsendung von|Zuständigkeitsordnung|Bestellung von Mitgliedern|"
                        r"Vertretung der (?:Bundes)?[Ss]tadt Bonn i[nm]|Aufsichtsrat|\bAR der|Verbandsversammlung|Jahresabschluss|"
                        r"Beigeordnete|Stellenplan|personalwirtschaftlich|Ausschreibung der Stelle|Wiederwahl|"
                        r"Gesundheitsbericht|Firmenfitness|Vergütung|Besoldung|"
                        r"Büromaterial|Bürostühle|Bürodrehstühle|Lieferung von|Aktenvernichtung|Geldtransport|"
                        r"Frankier|Beflaggung|Stadttauben|Bewohnerpark|Parkausweis|\bParken\b|Fahrgastanzeige|"
                        r"Lehr- und Wanderpfad", re.I)
CDO = Zustaendig(abteilungen=("Stabsstelle CDO",))
IT_ABT = Zustaendig(abteilungen=("10-2 ",))
AUSSCHUSS = Zustaendig(gremien=(DIGITAL,))
WIRTSCHAFT = wirtschaft.THEMA  # Digital Hub, Cybersicherheit als Wirtschaftsstandort: nur auf der Wirtschaftsseite
# „weitere“: Vorlagen, die der Ausschuss nur mitberät und die auf einer anderen Themenseite stehen, bleiben dort
ANDERE = (kultur.THEMA, verkehr.THEMA, schule.THEMA, wohnen.THEMA, klima.THEMA, kinder.THEMA, soziales.THEMA,
          sicherheit.THEMA, wirtschaft.THEMA)

THEMA = Thema(
    key="digital",
    pfad="thema/digitale-verwaltung/",
    titel="Digitale Verwaltung",
    lead="Welche Vorlagen und Verfahren betreffen die Digitalisierung der Stadtverwaltung Bonn – die digitale Strategie, "
         "IT und Software, Online-Dienste und Bürgerservice, die Modernisierung und Organisation der Verwaltung? Diese "
         "Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, wann und "
         "wo darüber beraten wird. Wirtschaftsförderung und der Wirtschaftsstandort stehen auf der Seite Wirtschaft "
         "und Wissenschaft.",
    seo_text="Digitale Verwaltung in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Digitalisierungsstrategie, "
             "IT und Software, Online-Diensten, Bürgerservice und Verwaltungsmodernisierung, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("strategie", "Digitale Strategie und Steuerung",
         "Titel nennt die Digitalisierungsstrategie, die Dachstrategie Digitale Transformation, die Bestandsaufnahme "
         "der Digitalisierung, Smart City, Daten der Stadt (Urban Data Platform, Open Data) oder Regeln für "
         "algorithmische Systeme; dazu Vorlagen, die die Stabsstelle CDO federführend betreut"),
        ("online", "Online-Dienste und Bürgerservice",
         "Titel nennt Online-Angebote, die Website der Stadt, Terminbuchung, digitale Bezahlung, den Bürgerservice, "
         "das Dienstleistungszentrum, die Teilhabe an der digitalen Verwaltung oder den Zugang ohne Internet"),
        ("it", "IT, Software und Sicherheit",
         "Titel nennt IT, Software und Lizenzen, Open Source, IT-Sicherheit und Cyberangriffe, Fachverfahren, Apps, "
         "künstliche Intelligenz oder Digitalisierungsprojekte der Ämter; dazu Vorlagen, die die Abteilung IT (10-2) "
         "federführend betreut; nicht Vorlagen der Seite Wirtschaft und Wissenschaft"),
        ("organisation", "Verwaltungsmodernisierung und Organisation",
         "Titel nennt Verwaltungsmodernisierung, Organisationsuntersuchungen, Bürokratieabbau, die Neuverteilung der "
         "Dezernate, den Umzug aus dem Stadthaus oder die Verwaltungsgebührenordnung; keine Personalangelegenheiten"),
        ("weitere", "Weitere Vorlagen zur digitalen Verwaltung",
         "Beratung im Ausschuss für Digitalisierung, Dienstleistung und Verwaltungsmodernisierung, ohne die Merkmale "
         "der anderen Stränge und ohne Vorlagen, die auf einer anderen Themenseite stehen; ohne Formalien, "
         "Personalangelegenheiten und Sammellisten nichtöffentlicher Punkte"),
    ],
    regeln=[
        Regel("strategie", titel=STRATEGIE, ohne_seite=WIRTSCHAFT),
        Regel("online", titel=ONLINE, ohne_seite=WIRTSCHAFT),
        Regel("it", titel=IT, ohne_seite=WIRTSCHAFT),
        Regel("organisation", titel=ORGANISATION, ohne_seite=WIRTSCHAFT),
        Regel("it", titel=DIGITAL_ALLG, ohne_seite=WIRTSCHAFT, ohne_thema="verkehr"),
        Regel("strategie", zustaendig=CDO, ohne_seite=WIRTSCHAFT),
        Regel("it", zustaendig=IT_ABT, ohne_seite=WIRTSCHAFT),
        Regel("weitere", zustaendig=AUSSCHUSS, ohne_seite=ANDERE),
    ],
    ausschluss=AUSSCHLUSS,
    eingeklappt={"weitere"},
    leer_ausblenden={"weitere"},  # derzeit leer; erscheint, sobald er Vorlagen enthält (Entscheidung 02.11.2026)
    punkt_straenge=("strategie", "online", "it", "organisation", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss oder Digitalisierungsausschuss
    punkt_gremien=("Rat", "Hauptausschuss", DIGITAL),
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("digital", "Digitalisierungsausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"digital": (DIGITAL,)},
    sitzungen=(DIGITAL, FINANZ, "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py); die Seite zeigt keinen Produktbereich
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("digital"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für die Digitalisierung der Ausschuss für Digitalisierung, Dienstleistung und "
                               "Verwaltungsmodernisierung"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Abteilung, Gremium und Wörtern im Titel, je Vorlage "
            "mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Digitale Verwaltung in Rat, Hauptausschuss, Digitalisierungsausschuss und "
               "Bezirksvertretungen",
    feed_text="zur digitalen Verwaltung",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 02.11.2026 geprüft (Vorschlag einer KI, im Gespräch von "
                  "Hand bestätigt: 24 passend, 1 teilweise, 0 unpassend; in der Gegenprobe fehlte keine von 5); die "
                  "Regeln blieben unverändert.",
    nicht_gezeigt=[
        "<strong>Beträge und Haushalt:</strong> Kosten, Lizenzen und Vergaben stehen in den Dokumenten der Vorlagen und "
        "im Haushaltsplan der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge "
        "je Vorlage und zeigt keinen Produktbereich: Digitalisierung und IT gehören zum Produktbereich 01 „Innere "
        "Verwaltung“, der fast die ganze Verwaltung umfasst (Plan 2026: 304,1 Mio. €). Die Beträge aller "
        "Produktbereiche stehen auf der Seite <a href=\"../../haushalt/\">Haushalt auf einen Blick</a>.",
        "<strong>Personalangelegenheiten</strong> (Wahl von Beigeordneten, Stellenplan, Personalberichte) und "
        "Beschaffungen von Büromaterial gehören nicht zum Thema. Nichtöffentliche Beratungen fehlen.",
        "<strong>Digitale Wirtschaft</strong> (Digital Hub, Start-ups, Cybersicherheit als Wirtschaftsstandort) steht auf "
        "der Seite Wirtschaft und Wissenschaft. Digitale Projekte einzelner Ämter (z. B. Rettungsdienst, Wohngeld, "
        "Spielplätze) können auch auf der Seite des Fachthemas stehen.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter Vorlagen
    # mit Wörtern des Themas am Wortanfang
    # „weitere“ ist beim Ziehen leer (alle übrigen Vorlagen des Ausschusses stehen in einem Strang oder auf einer
    # anderen Themenseite)
    stichprobe_je_strang={"strategie": 6, "online": 6, "it": 7, "organisation": 6},
    stichprobe_ohne=5,
    # Wortanfänge: nicht „Zweit-“ oder „Kurzzeit-“ (IT nur groß), nicht „Stellungnahme der Verwaltung“ (nur
    # Verwaltungsprozess, -modernisierung u. Ä.), nicht „Serviceweg“
    kandidat=re.compile(r"(?<![\w-])[Dd]igital|(?-i:\bIT\b|IT-)|(?<![\w-])Software|(?<![\w-])Online|"
                        r"(?<![\w-])Verwaltungs(?:prozess|modern|reform|verfahren|leistung|struktur)|"
                        r"(?<![\w-])Organisation|(?<![\w-])Daten(?!basis)|(?<![\w-])Internet|(?<![\w-])Portal|"
                        r"(?<![\w-])Service(?!weg)|(?<![\w-])Bürokratie|(?<![\w-])E-(?:Mail|Akte|Government)", re.I),
    farben=("#334155", "#475569", "#38bdf8"),  # Übersicht thema/: Schrift, Verlauf (Schiefer zu Himmelblau)
    symbol='<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M10 8l-2 2 2 2M14 8l2 2-2 2"/>',
    produktbereich=None,  # kein Haushaltsabschnitt (Entscheidung 02.11.2026): Produktbereich 01 umfasst fast alles
    fachausschuss=DIGITAL,  # Kasten „Wer berät mit“
)
