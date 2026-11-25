"""Themenseite „Verkehr und Mobilität“ (thema/verkehr-und-mobilitaet/), Pilot der Kölner Themenseiten (Entscheidung
24.11.2026 (3); Antworten zum Plan vom 25.11.2026, 1 A bis 5 A).

Zuordnung nur über
- die Beratung im Mobilitätsausschuss (Gremium-Tor: Eintrag in gremien.json mit Gruppe „ausschuss“ und § 17 der
  Zuständigkeitsordnung, Kennung zur Laufzeit; abgesagte Sitzungen zählen nicht),
- Wörter im Titel (Wortlisten unten, in der Reihenfolge der Regeln geprüft) und
- Folgevorlagen über die veröffentlichten Beziehungen superordinated und subordinated (dossier.verfahren).
Nie über das abgeleitete Thema (topics.py, suche.json), die Federführung, relatedPaper oder Volltexte. Zeitraum ab
Beginn der laufenden Wahlperiode; deshalb ist das Verkehrsgremium der Wahlperiode 2020–2025 für das Tor nicht nötig.
Die Wortlisten sind eng, weil Kölner Titel oft Adressen und mehrdeutige Wörter enthalten; geprüft sind sie bisher nur
mit erfundenen Titeln (tests/test_themenseiten_koeln.py). Den Nachweis mit echten Titeln liefert der Prüfbogen
(tools/themen_pruefbogen.py); danach folgen pruefung_text und pruefung_datum und erst dann die Freigabe.
Farben und Symbol wie die Verkehrsseite in daimpad/ratsatlas-bonn (nur Gestaltung)."""
import re

from ..dossier import Auswahl, Regel, Thema
from ..topics import THEMES

# vor allen Regeln, auch vor Folgevorlagen: Verkehrswert, Verkehrssicherungspflicht (Bäume), Grünpflege an Straßen,
# Straßenreinigung, Benennungen (auch nach Personen: Datenschutz), Straßenfeste und Ähnliches, Mobilfunk, Abwasser, Abfall;
# dazu Personalien und Sitzungsorganisation (PERSONALIEN), auch wenn der Titel den Ausschuss oder ein Verkehrswort nennt
# („Wahlen zum Mobilitätsausschuss“, „Wiederwahl der Beigeordneten für Mobilität“): Solche Titel können Namen von Personen
# enthalten, und die Titelmaske erkennt keine Namen. Nicht „Bestellung“ (auch Fahrzeuge) und nicht „Geschäftsordnung“
# (auch in Titeln von Anträgen): beide nur im TOR_AUSSCHLUSS
PERSONALIEN = (r"(?<![a-zäöüß])(?:Neu|Wieder|Ab|Nach)?[Ww]ahl(?:en|vorschlag|vorschläge)?\b|Ernennung|Abberufung|"
               r"Entsendung|(?:Um|Nach|Neu)besetzung|Nach-besetzung|sachkundig|Vorsitz|Geschäftsführer|"
               r"Sitzungs(?:kalender|plan|termin)|Termin(?:plan(?:ung)?|e)\s+(?:der|für\s+die)\s+Sitzung|Niederschrift|"
               r"Protokoll\b")
AUSSCHLUSS = re.compile(r"Verkehrswert|Verkehrssicherungspflicht|Verkehrssicherung(?:smaßnahme|en)?\b|Verkehrsgrün|"
                        r"Straßenbegleitgrün|Straßenreinigung|Straßenbenennung|Straßenname|(?:Um)?[Bb]enennung|"
                        r"Straßen(?:fest|musik|kunst|strich|sozialarbeit|zeitung|kinder)|Mobilfunk|Abwasser|Abfall|"
                        + PERSONALIEN, re.I)
# nicht „Park“ allein (Stadtpark, Gewerbepark, Parkpflege), nicht Fahrradparken, nicht Parkentwicklung
PARKEN = re.compile(r"(?<!fahrrad)(?<!rad)(?<!rad-)park(?:en(?!twickl)|platz|plätze|raum|haus|häuser|gebühr|schein|verbot|druck|"
                    r"situation|möglichkeit|zone|deck|leitsystem|ausweis|bewirtschaftung|suchverkehr)|Bewohnerpark|"
                    r"Anwohnerpark|Halteverbot|Parkverbot|P ?\+ ?R\b|Park ?(?:&|and|\+) ?Ride|"
                    r"(?<!rad)(?<!rad-)(?<!fahrrad)(?<!auf)Stellpl(?:atz|ätz)|Ladezone|Lieferzone", re.I)
# nicht Business, Kegelbahn, Bahnhofsmission, Richtlinie (nur „Linie <Zahl>“), Taktik, Kontakt; „Bahnhof“ nicht in den
# Kölner Straßennamen Bahnhofstraße, Bahnhofplatz, Bahnhofsvorplatz, „Am Bahnhof“ und „Am Alten Güterbahnhof“
# (Straßenverzeichnis data/geo/strassen_koeln.json; Adressen in Titeln)
BUS_BAHN = re.compile(r"ÖPNV|Nahverkehr|\bKVB\b|Stadtbahn|Straßenbahn|\b[SU]-Bahn|Seilbahn|Regionalbahn|Hochbahnsteig|"
                      r"Bahnsteig|Bahnübergang|(?<!(?-i:Am) )(?<!Alten Güter)Bahnhof(?!smission|str(?:aße|\.)|s?(?:vor)?platz)|"
                      r"Haltestelle|"
                      r"\bBus(?:se|sen|linien?|spur(?:en)?|bahnhof|verkehr|netz|beschleunigung)?\b|"
                      r"(?:Schnell|Ruf|Nacht|Linien|E-)bus|\bLinie\s?\d+|Linienweg|Fahrplan|\bTakt(?:ung|verdichtung|e|en)?\b|"
                      r"Deutschlandticket|Jobticket|Schülerticket|On-Demand|Mobilstation", re.I)
# nicht Grad, Radius, Riesenrad, Zahnrad, Fußball
RAD_FUSS = re.compile(r"\bRad(?:verkehr|wege?|fahr\w*|streifen|schnellweg|station|abstell\w*|bügel|route|netz|parken|"
                      r"pendler|vorrang\w*|spur)|\bRad- und|Fahrrad|Lastenrad|Fußverkehr|Fußgänger|Fußweg|Gehweg|"
                      r"Bürgersteig|Zebrastreifen|Querungshilfe|E-Scooter|\bScooter|Leihr[aä]d|Bikesharing", re.I)
# Unfall nur als Verkehrsunfall, Unfallschwerpunkt und Ähnliches (nicht „Gedenkstele für Opfer des Unfalls“)
TEMPO = re.compile(r"Tempo[- ]?(?:\d|limit|zone|reduz|beschränk)|Geschwindigkeit|km/h|"
                   r"Verkehrssicherheit(?! (?:von|städtischer|der) Bäume)|Verkehrsberuhig|Verkehrsversuch|Schulweg|"
                   r"Verkehrsunf[aä]ll|Unfall(?:schwerpunkt|häufung|stelle|gefahr|risiko|zahl|statistik|lage|kommission|"
                   r"verhütung|vermeidung|prävention)|(?<!Arbeits)Unfälle|Blitzer|Einbahn|Durchfahrt|Anlieger|Modalfilter|"
                   r"Verkehrszeichen", re.I)
# Poller, Markierung und Beschilderung nur zusammen mit einem Wort zum Verkehrsraum (ZEICHEN_BEZUG): nicht Grabfelder,
# Wanderwege oder Hochwasserschutz; „Poller“ nicht als Adjektiv zum Stadtteil Poll (Poller Damm, Poller Wiesen: danach
# ein großgeschriebenes Wort)
ZEICHEN = re.compile(r"Markierung|Beschilderung|(?<![a-zäöüß])Poller(?!\s+(?-i:[A-ZÄÖÜ]))", re.I)
ZEICHEN_BEZUG = re.compile(r"Fahrbahn|Straße|Str\.|\bRad|Fußg|Fußweg|Gehweg|Verkehr|Kreuzung|Tempo|Halte|Schulweg|"
                           r"Zufahrt|Durchfahrt|Einfahrt|Parkpl|Parkfl", re.I)
# nie „Straße“ allein (Adressen in Titeln); nicht Brückentag, Ampelkoalition, Tunnelblick
STRASSEN = re.compile(r"Straßen(?:bau|ausbau|raum|umbau|verkehr|querschnitt|sanierung)|Fahrbahn|Brücken?\b|"
                      r"(?<=[a-zäöü])brücke\b|Brücken(?:sanierung|bauwerk|prüfung)|Tunnel(?!blick)|Unterführung|Kreuzung|"
                      r"Kreisverkehr|Knotenpunkt|Ampelanlage|Ampelschaltung|Fußgängerampel|Lichtsignal|Deckenerneuerung",
                      re.I)
# nicht Geschäfts-, Zahlungs-, Schrift-, Daten-, Publikums- oder Rechtsverkehr, nicht Mobilfunk, mobile Jugendarbeit;
# „Verkehrsfläche“ nur mit Beratung im Mobilitätsausschuss (MEHRDEUTIG)
WEITERE = re.compile(r"(?<![a-zäöüß])Verkehr(?!swert|ssicherung|sgrün|sverein|sfläche)|(?:Rad|Fuß|Auto|Liefer|Durchgangs|"
                     r"Schwerlast|Lkw-|LKW-|Güter|Wirtschafts|Individual|Kfz-|Parksuch|Schienen|Bus)verkehr|"
                     r"mobilität(?!shilfe)|Carsharing|Car-Sharing|Ladesäule|Ladeinfrastruktur|Ladestation|Taxi", re.I)
# mehrdeutige Wörter: nur zusammen mit der Beratung im Mobilitätsausschuss
MEHRDEUTIG = re.compile(r"Umgestaltung|Platz|Ticket|Gleis|Hafen|Luftverkehr|Verkehrsfläche", re.I)
# nur über das Gremium nie (weder ohne Wort noch mit einem mehrdeutigen Wort): Haushalt und Wirtschaftspläne, dazu
# Bestellung und Geschäftsordnung (Personalien und Sitzungsorganisation schließt schon AUSSCHLUSS aus)
TOR_AUSSCHLUSS = re.compile(r"Haushalt|Stellenplan|Jahresabschluss|Wirtschaftsplan|Beteiligungsbericht|"
                            r"Geschäftsordnung|Bestellung", re.I)

MOBIL = Auswahl(gruppe="ausschuss", paragraf=17)        # Mobilitätsausschuss, § 17 der Zuständigkeitsordnung
HAUPT = Auswahl(gruppe="ausschuss", paragraf=7)         # Hauptausschuss, § 7
RAT = Auswahl(gruppe="rat")
BV = Auswahl(gruppe="bezirksvertretung")

THEMA = Thema(
    key="verkehr",
    pfad="thema/verkehr-und-mobilitaet/",
    titel=dict(THEMES)["verkehr"],
    lead="Welche Vorlagen betreffen Bus und Bahn, Rad- und Fußverkehr, Parken, Verkehrsregeln sowie Straßen und "
         "Brücken in Köln? Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem der Stadt seit Beginn der "
         "Wahlperiode ({seit}) und zeigt, wo die Verfahren stehen und wann darüber beraten wird.",
    seo_text="Verkehr und Mobilität in Köln: {vorlagen} aus dem Ratsinformationssystem zu Bus und Bahn, Rad- und "
             "Fußverkehr, Parken, Verkehrsregeln, Straßen und Brücken, mit den nächsten Sitzungen.",
    straenge=[
        ("bus_bahn", "Bus und Bahn",
         "Der Titel nennt ÖPNV, Nahverkehr, KVB, Stadtbahn, Straßenbahn, S- oder U-Bahn, Seilbahn, Bahnhof (nicht in "
         "Straßennamen wie Bahnhofstraße), Bahnsteig, Haltestelle, Bus, Linie mit Nummer, Fahrplan, Takt, "
         "Deutschlandticket, Jobticket oder Mobilstation, aber kein Wort zum Parken"),
        ("rad_fuss", "Rad- und Fußverkehr",
         "Der Titel nennt Radverkehr, Radwege, Fahrrad, Lastenrad, Fußverkehr, Fußgänger, Gehweg, Zebrastreifen, "
         "Querungshilfe, E-Scooter oder Leihräder, aber kein Wort zum Parken und keines zu Bus und Bahn"),
        ("parken", "Parken",
         "Der Titel nennt Parken, Parkplätze, Parkraum, Parkhaus, Parkgebühren, Bewohnerparken, Halteverbot, "
         "Stellplätze, Park and Ride, Lade- oder Lieferzonen (nicht Fahrradparken und nicht „Park“ allein)"),
        ("tempo", "Tempo, Verkehrsregeln und Sicherheit",
         "Der Titel nennt Tempo, Geschwindigkeit, km/h, Verkehrssicherheit, Verkehrsberuhigung, Verkehrsversuch, "
         "Schulweg, Verkehrsunfälle oder Unfallschwerpunkte, Einbahnstraße, Durchfahrt, Anlieger, Modalfilter oder "
         "Verkehrszeichen, oder Poller, Markierung oder Beschilderung zusammen mit einem Wort zu Fahrbahn, Straße, "
         "Kreuzung oder Verkehr, aber keines der Wörter zu Parken, Bus und Bahn oder Rad- und Fußverkehr"),
        ("strassen", "Straßen und Brücken",
         "Der Titel nennt Straßenbau, Straßenausbau, Straßenraum, Straßenumbau oder Straßensanierung, Fahrbahn, Brücke, "
         "Tunnel, Unterführung, Kreuzung, Kreisverkehr, Knotenpunkt, Ampelanlage, Lichtsignal oder Deckenerneuerung "
         "(nicht „Straße“ allein, etwa in einer Adresse), aber keines der Wörter der Stränge davor"),
        ("weitere", "Weitere Vorlagen zu Verkehr und Mobilität",
         "Der Titel nennt Verkehr, Mobilität, Carsharing, Ladesäulen, Ladeinfrastruktur oder Taxi, aber keines der "
         "Wörter der anderen Stränge; dazu Vorlagen mit Beratung im Mobilitätsausschuss: mit Umgestaltung, Platz, "
         "Ticket, Gleis, Hafen, Luftverkehr oder Verkehrsfläche im Titel oder ohne passendes Wort, beides nicht zu "
         "Haushalt und Wirtschaftsplänen; nach Stadtbezirk"),
    ],
    regeln=[
        Regel("parken", titel=PARKEN),
        Regel("bus_bahn", titel=BUS_BAHN),
        Regel("rad_fuss", titel=RAD_FUSS),
        Regel("tempo", titel=TEMPO),
        Regel("tempo", titel=ZEICHEN, bedingung=ZEICHEN_BEZUG),
        Regel("strassen", titel=STRASSEN),
        Regel("weitere", titel=WEITERE),
        Regel("weitere", titel=MEHRDEUTIG, gremium_tor=True),
        Regel("weitere", gremium_tor=True),
    ],
    ausschluss=AUSSCHLUSS,
    tor_ausschluss=TOR_AUSSCHLUSS,
    fachausschuss=MOBIL,
    nach_bezirk=frozenset({"weitere"}),
    leer_ausblenden=frozenset({"bus_bahn", "rad_fuss", "parken", "tempo", "strassen", "weitere"}),
    punkt_straenge=("bus_bahn", "rad_fuss", "parken", "tempo", "strassen", "weitere"),
    # Punkte nur mit Beratung in Rat, Hauptausschuss oder Mobilitätsausschuss (Antwort 2 A zum Plan, 25.11.2026)
    punkt_gremien=(RAT, HAUPT, MOBIL),
    punkt_text="im Rat, im Hauptausschuss oder im Mobilitätsausschuss",
    # Beschriftung der Bahnen (Spalte neben der Zeitleiste) mit weichen Trennstellen für die schmale Spalte auf dem
    # Telefon (site/page.css, .pb-bahn)
    bahnen=[("bv", "Bezirks\u00advertretungen"), ("mobil", "Mobilitäts\u00adausschuss"),
            ("fach", "andere Ausschüsse und Gremien"), ("rat", "Haupt\u00adausschuss und Rat")],
    bahn_regeln=(("bv", BV), ("mobil", MOBIL), ("rat", RAT), ("rat", HAUPT)),
    sitzungs_gremien=(MOBIL, HAUPT, RAT, BV),
    sitzungen_text="Die nächste Sitzung des Mobilitätsausschusses, des Hauptausschusses, des Rates und jeder "
                   "Bezirksvertretung laut Sitzungskalender der Stadt.",
    karten_links=(("ebene", "fahrradstrassen", "Fahrradstraßen"), ("ebene", "haltestellen", "Haltestellen"),
                  ("gremium", None, "Vorlagen des Mobilitätsausschusses")),
    hinweis="Zuordnung zu den Strängen abgeleitet: feste Regeln aus der Beratung im Mobilitätsausschuss, Wörtern im "
            "Titel und Folgevorlagen, je Vorlage mit Grund; keine Zitate",
    bild_titel="Zeitleiste: Verkehr und Mobilität in Bezirksvertretungen, Mobilitätsausschuss, Hauptausschuss und Rat",
    feed_text="zu Verkehr und Mobilität",
    pruefung_text="",
    pruefung_datum="",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten von Maßnahmen stehen in den Dokumenten der Vorlagen, nicht in den Daten des "
        "Ratsinformationssystems; die Seite nennt keine Beträge und keine Haushaltsdaten.",
        "<strong>Keine Verortung auf Hausnummern:</strong> Örtliche Vorgänge stehen nach Stadtbezirk; Straßen und Orte "
        "zeigt die Karte. Titel stehen wie im Ratsinformationssystem, bei Vorlagen aus der Einwohnerschaft (etwa "
        "Eingaben nach § 24 GO NRW) ohne Hausnummer.",
        "<strong>Personalien und Sitzungsorganisation:</strong> Wahlen, Besetzungen, Sitzungskalender und Niederschriften "
        "ordnet die Seite keinem Strang zu, auch wenn der Titel den Mobilitätsausschuss nennt.",
        "<strong>Nichtöffentliche Beratungen.</strong>",
        "<strong>Federführende Dienststelle:</strong> Sie steht in den Kölner Daten des Ratsinformationssystems nicht.",
        "<strong>Vorlagen nur in Bezirksvertretungen</strong> ohne Wort zum Verkehr im Titel.",
        "<strong>Inhalte der Dokumente:</strong> keine Zitate und keine Auszüge.",
        "<strong>Namen von Personen.</strong>",
    ],
    # Prüfbogen (tools/themen_pruefbogen.py): je Strang einige zugeordnete Vorlagen, im Strang „weitere“ davon zwei nur
    # über das Gremium, dazu Folgevorlagen und eine Gegenprobe nicht zugeordneter Vorlagen mit Verkehrsbezug im Titel
    # oder mit Beratung im Mobilitätsausschuss
    stichprobe_je_strang={"bus_bahn": 4, "rad_fuss": 4, "parken": 4, "tempo": 4, "strassen": 4, "weitere": 4},
    stichprobe_nur_gremium=2,
    stichprobe_folge=2,
    stichprobe_ohne=6,
    kandidat=re.compile(r"Verkehr|Mobilität|Straße|\bRad|Fahrrad|Gehweg|\bBus|Bahn|Haltestelle|Park|Ampel|Kreuzung|"
                        r"Tempo|KVB", re.I),
    farben=("#1d4ed8", "#2563eb", "#0891b2"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<circle cx="5.5" cy="17" r="3.5"/><circle cx="18.5" cy="17" r="3.5"/>'
           '<path d="M5.5 17 9.5 9h6l3 8M9.5 9l3 8h-7M13.5 6H17"/>',
)
