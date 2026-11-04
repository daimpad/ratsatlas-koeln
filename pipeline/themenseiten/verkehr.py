"""Themenseite „Verkehr und Mobilität“ (thema/verkehr-und-mobilitaet/). Phase 0 und Entscheidungen:
verkehr/phase0/BERICHT.md; Prüfbogen im Gespräch geprüft am 26.10.2026, danach Regeln ergänzt (verkehr/PRUEFUNG.md).
Ergänzung 02.11.2026: Strang „Tempo, Verkehrsregeln und Sicherheit“ und Vorlagen der Straßenverkehrsbehörde mit
Verkehrswort im Titel, eigener Prüfbogen (verkehr/ERGAENZUNG.md).

Grundlage ist die abgeleitete Themenzuordnung „Verkehr und Mobilität“ (topics.py: Amt 61-3 Stadtverkehr und 66,
Ausschuss für Mobilität und Verkehr, Stichwörter). Stränge nach Wörtern im Titel, die Sperrung der Nordbrücke als
ganzes Verfahren; alle übrigen Vorlagen des Themas nach Stadtbezirk. Keine Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt

# Vergabe der Grünpflege an Straßen („Verkehrsgrün“) gehört nicht zum Thema (Phase 0: 7 Vorlagen); Abwasser und
# Abfall ebenso (Prüfung 26.10.2026: Abwasserbeseitigungskonzept, Altglascontainer an einer Haltestelle)
AUSSCHLUSS = re.compile(r"Verkehrsgrün|Straßenbegleitgrün|Landschaftsgärtnerische Pflege|Verkehrssicherung und "
                        r"Unterhalt|Abwasser|Altglas|Glascontainer|Abfall|Müll", re.I)
NORDBRUECKE = re.compile(r"Nordbrücke", re.I)  # auch „Nordbrückensperrung“, „Nordbrücken-Sperrung“
BUS_BAHN = re.compile(r"ÖPNV|ÖSPV|Nahverkehr|\bBus(?!iness)|Busse|Haltestelle|Stadtbahn|Straßenbahn|Seilbahn|S-Bahn|"
                      r"Regionalbahn|Bahnhof|Schienen|Fahrplan|\bTakt|\bLinie|\bSB ?\d|Ticket|Rufbus|On-Demand|"
                      r"Stadtwerke|SWB", re.I)
# Parken vor Bus und Bahn (Parkplätze am Bahnhof) und vor Rad und Fuß (Gehwegparken), aber nicht Fahrradparken
# und nicht Fahrrad- oder Lastenradstellplätze; „Park- und …“ mit Ergänzungsstrich zählt (Prüfung 26.10.2026)
PARKEN = re.compile(r"(?<!fahrrad)(?<!rad)park(?:en|platz|plätz|raum|haus|häus|gebühr|schein|verbot|druck|situation|"
                    r"möglichkeit|zone)|\bPark- |Park ?(?:&|\+|and) ?Ride|\bP\+R\b|Bewohnerpark|Anwohnerpark|Halteverbot|"
                    r"(?<!rad)(?<!rad-)(?<!ab)Stellpl(?:atz|ätz)|Ladezone|Lieferzone|"
                    # Regel A (Prüfung 02.11.2026, verkehr/ERGAENZUNG.md): Kfz-Stellflächen und Brötchentaste
                    r"(?<!rad)(?<!rad-)(?<!auf)Stellfläch|Brötchentaste", re.I)  # nicht „Aufstellflächen für Fahrräder“
RAD_FUSS = re.compile(r"\bRad(?:verkehr|weg|fahr|streifen|schnell|spur|station|abstell|bügel|route|netz|parken|achse|"
                      r"pendler|wege)|Fahrrad|Lastenrad|Fußverkehr|Fußgänger|Fußweg|Gehweg|Zebrastreifen|Querung|"
                      r"Bürgersteig|Gehsteig|E-Scooter|Scooter", re.I)
# Auch außerhalb der Themenzuordnung (Prüfung 26.10.2026: Gegenprobe, 3 von 6 fehlten)
EINSPURIG = re.compile(r"einspurig", re.I)  # Überholverbot für einspurige Fahrzeuge (Radverkehr)
ZUSATZ = re.compile(r"Beschilderung|Verkehrszeichen|Überhol|Fahrbeziehung|Fahrstreifen|Autobahn", re.I)
# Strang „Tempo, Verkehrsregeln und Sicherheit“ (Entscheidungen 02.11.2026, verkehr/ERGAENZUNG.md): Tempo und
# Geschwindigkeit auch außerhalb der Themenzuordnung (nicht „Tempo erhöhen“ im übertragenen Sinn); dieselbe Vorlage darf
# auch auf der Klimaseite stehen (Tempo 30 wegen Lärm); nicht die Verkehrssicherheit von Bäumen (Baumkontrolle)
TEMPO = re.compile(r"Tempo[- ]?(?:\d|limit|zone|reduz|beschränk)|Geschwindigkeit|km/h|Verkehrssicherheit(?! städtischer Bäume)|"
                   r"Verkehrsberuhig|Blitzer|Radarkontroll|Unfall", re.I)
# Vorlagen der Straßenverkehrsbehörde (33-1) nur mit einem Verkehrswort im Titel (Entscheidung 02.11.2026); ohne
# Ordnungsthemen der Abteilung (Schiedsperson, Rauchen, Ratten, Werbesatzung, Tauben, Verkaufsstellen, Feuerwerk)
STVB = Zustaendig(abteilungen=("33-1",))
REGELN = re.compile(r"Vorfahrt|rechts vor links|Anlieger|Einfahrt|Durchfahrt|Zufahrt|Poller|Grün(?:e |e-)?[Pp]feil|"
                    r"Taxi|Hol- und Bringzone|Einbahn|Modalfilter|Fußgängerzone|Ausschilderung|Schild|Markierung|"
                    r"Zweiräder|Ampel|Lichtsignal", re.I)
FGUE = re.compile(r"\bFGÜ\b")  # „Fußgänger…“ steht schon in RAD_FUSS
MOBIL = ("Ausschuss für Mobilität und Verkehr",)

THEMA = Thema(
    key="verkehr",
    pfad="thema/verkehr-und-mobilitaet/",
    titel="Verkehr und Mobilität",
    lead="Welche Vorlagen und Verfahren betreffen Verkehr und Mobilität in Bonn, darunter die Sperrung der "
         "Nordbrücke? Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode "
         "({seit}) und zeigt, wann und wo darüber beraten wird.",
    seo_text="Verkehr und Mobilität in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zur Sperrung der "
             "Nordbrücke, zu Bus und Bahn, Rad- und Fußverkehr und Parken, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("nordbruecke", "Sperrung der Nordbrücke",
         "Vorlagen, deren Titel die Nordbrücke nennt, und ganze Verfahren, deren Stammvorlage sie nennt (auch "
         "außerhalb der Themenzuordnung)"),
        ("bus_bahn", "Bus und Bahn",
         "Thema Verkehr und Mobilität, und der Titel nennt ÖPNV, Nahverkehr, Bus, Haltestelle, Stadtbahn, Seilbahn, "
         "Bahnhof, Fahrplan, Takt, Linie, Ticket o. Ä. (nicht Parken)"),
        ("parken", "Parken",
         "Thema Verkehr und Mobilität, und der Titel nennt Parken, Parkplätze, Parkraum, Parkgebühren, "
         "Bewohnerparken, Halteverbot, Stellplätze o. Ä. (nicht Fahrradparken, nicht Fahrrad- oder "
         "Lastenradstellplätze)"),
        ("rad_fuss", "Rad- und Fußverkehr",
         "Thema Verkehr und Mobilität, und der Titel nennt Radverkehr, Radwege, Fahrrad, Fußverkehr, Gehwege, "
         "Zebrastreifen, Querungen, E-Scooter o. Ä.; dazu Titel mit einspurigen Fahrzeugen"),
        ("tempo", "Tempo, Verkehrsregeln und Sicherheit",
         "Titel mit Tempo, Geschwindigkeit, km/h, Verkehrssicherheit, Verkehrsberuhigung oder Unfall (auch außerhalb "
         "der Themenzuordnung); dazu Vorlagen der Straßenverkehrsbehörde mit Vorfahrt, Anliegern, Zufahrten, Pollern, "
         "Grünpfeilen, Taxi, Schildern, Markierungen o. Ä. im Titel"),
        ("weitere", "Weitere Vorlagen zu Verkehr und Mobilität",
         "Thema Verkehr und Mobilität ohne die Merkmale der anderen Stränge, dazu Titel mit Beschilderung, "
         "Verkehrszeichen, Überholen, Fahrbeziehung, Fahrstreifen oder Autobahn; ohne Abwasser, Abfall und "
         "Grünpflege; nach Stadtbezirk"),
    ],
    regeln=[
        # ganzes Verfahren nur, wenn die Stammvorlage die Nordbrücke nennt (sonst zöge ein Änderungsantrag zum
        # Nahverkehrsplan das ganze Verfahren mit); einzelne Vorlagen über den Titel
        Regel("nordbruecke", verfahren_titel=NORDBRUECKE, nur_stammvorlage=True),
        Regel("nordbruecke", titel=NORDBRUECKE),
        Regel("parken", thema="verkehr", titel=PARKEN),
        Regel("bus_bahn", thema="verkehr", titel=BUS_BAHN),
        Regel("rad_fuss", thema="verkehr", titel=RAD_FUSS),
        Regel("tempo", thema="verkehr", titel=TEMPO),
        Regel("weitere", thema="verkehr"),
        Regel("rad_fuss", titel=EINSPURIG),
        # außerhalb der Themenzuordnung (Entscheidungen 02.11.2026): Tempo im Titel; Straßenverkehrsbehörde nur mit
        # Verkehrswort, zuerst in die Stränge Parken und Rad- und Fußverkehr
        Regel("tempo", titel=TEMPO),
        Regel("parken", zustaendig=STVB, titel=PARKEN),
        Regel("rad_fuss", zustaendig=STVB, titel=RAD_FUSS),
        Regel("rad_fuss", zustaendig=STVB, titel=FGUE),
        Regel("tempo", zustaendig=STVB, titel=REGELN),
        Regel("weitere", titel=ZUSATZ),
    ],
    ausschluss=AUSSCHLUSS,
    nach_bezirk=frozenset({"weitere"}),  # vollständig, je Stadtbezirk eingeklappt (Entscheidung 26.10.2026)
    punkt_straenge=("nordbruecke", "bus_bahn", "parken", "rad_fuss", "tempo", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss oder Mobilitätsausschuss (Entscheidung 26.10.2026)
    punkt_gremien=("Rat", "Hauptausschuss") + MOBIL,
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("mobil", "Mobilitätsausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"mobil": MOBIL},
    sitzungen=MOBIL + ("Ausschuss für Finanzen, Beteiligungen und Vergabe", "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py; Entscheidung 26.10.2026)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("mobil"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Verkehr der Ausschuss für Mobilität und Verkehr"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus der Themenzuordnung und Wörtern im Titel, je "
            "Vorlage mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Verkehr und Mobilität in Rat, Hauptausschuss und Mobilitätsausschuss",
    feed_text="zu Verkehr und Mobilität",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 26.10.2026 im Gespräch geprüft (16 passend, 3 teilweise, "
                  "5 unpassend; in der Gegenprobe fehlten 3 von 6), danach wurden die Regeln ergänzt. Der Strang „Tempo, "
                  "Verkehrsregeln und Sicherheit“ kam am 02.11.2026 dazu; seine Stichprobe von 30 Vorlagen wurde geprüft "
                  "(Vorschlag einer KI, im Gespräch von Hand bestätigt: 24 passend, 1 teilweise, 0 unpassend; in der "
                  "Gegenprobe fehlte 1 von 5), danach wurde die Regel zum Parken ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten von Maßnahmen stehen in den Dokumenten der Vorlagen und im Haushaltsplan "
        "der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je Vorlage; Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Örtliche Vorgänge</strong> stehen nach Stadtbezirk, ohne Hausnummern; einzelne Straßen und Orte "
        "zeigt die Karte.",
        "<strong>Nichtöffentliche Beratungen</strong> und Vorlagen außerhalb der Themenzuordnung fehlen, außer zur "
        "Nordbrücke.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter
    # Vorlagen mit Verkehrsbezug im Titel
    stichprobe_je_strang={"nordbruecke": 4, "bus_bahn": 5, "parken": 5, "rad_fuss": 5, "weitere": 5},
    stichprobe_ohne=6,
    kandidat=re.compile(r"Verkehr|Mobilität|Straße|Radweg|Fahrrad|Gehweg|\bBus|Bahn|Haltestelle|Parken|Parkpl|Ampel|"
                        r"Kreuzung|Tempo", re.I),
    farben=("#1d4ed8", "#2563eb", "#0891b2"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<circle cx="5.5" cy="17" r="3.5"/><circle cx="18.5" cy="17" r="3.5"/>'
           '<path d="M5.5 17 9.5 9h6l3 8M9.5 9l3 8h-7M13.5 6H17"/>',
    produktbereich="12",  # Haushalt: Ist und Plan dieses Produktbereichs (Entscheidung 27.10.2026)
    fachausschuss=MOBIL[0],  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
