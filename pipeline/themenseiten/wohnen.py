"""Themenseite „Wohnen und Bauen“ (thema/wohnen-und-bauen/). Phase 0 und Entscheidungen: wohnen/phase0/BERICHT.md;
Prüfbogen im Gespräch geprüft am 26.10.2026, danach Regeln A–C (wohnen/PRUEFUNG.md).

Eigene Regeln statt der Themenzuordnung „Bauen“ (dort stehen auch Schulen, Bühnen und Sporthallen des
Gebäudemanagements; Wohnen liegt oft beim Thema Soziales): Wörter im Titel für Bauleitplanung, „Bau-Turbo“,
Wohnraum und Denkmalschutz, übrige Vorlagen aus Stadtplanungsamt, Bodenmanagement, Bauordnungsamt und
Planungsausschuss nach Stadtbezirk (Entscheidung 26.10.2026). Keine Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt

PLANUNG = "Ausschuss für Planen, Bauen und Denkmalschutz"
SOZIAL = "Ausschuss für Soziales, Migration, Gesundheit, Wohnen und Senioren"
# „Bau-Turbo“ (§ 246e BauGB, Zustimmung nach § 36a) und Beschleunigung der Bauleitplanung; vor Bebauungsplänen
TURBO = re.compile(r"Bau-?Turbo|§ ?36a|§ ?246e|Planungsturbo|Verfahrensbeschleunigung", re.I)
# Fluchtlinienpläne als Vorläufer der Bebauungspläne (Prüfung 26.10.2026)
PLAN = re.compile(r"Bebauungsplan|Flächennutzungsplan|Veränderungssperre|Bauleitplan|vorhabenbezogene|"
                  r"Fluchtlinienplan", re.I)
# Wohnraum einschließlich Wohnungslosigkeit (Entscheidung 26.10.2026); nicht „Miet…“ allein (Fahrradmietsystem,
# Anmietung), nicht „Wohngebiet“ (Tempo 30 u. Ä.)
WOHNRAUM = re.compile(r"Wohnungsbau|Wohnraum|geförderte[nmrs]? Wohn|Sozialwohnung|bezahlbare[nmrs]? Wohn|VEBOWAG|"
                      r"Vereinigte Bonner Wohnungs|Wohnungsbaugenossenschaft|wohnbaulich|Wohnungsmarkt|Mietspiegel|"
                      r"Mietpreis|Mietwohn|Leerstand|Zweckentfremd|Wohnungslos|Obdachlos|Housing First|Wohnungsnot|"
                      r"Wohnbau|Wohnquartier|Wohnungen|Wohnheim|Handlungskonzept Wohnen|Wohnen in Bonn", re.I)
DENKMAL = re.compile(r"(?<!Bauen und )Denkmal", re.I)  # nicht der Name des Planungsausschusses
# Stadtentwicklung und Städtebauförderung auch außerhalb der Ämter (Prüfung 26.10.2026: Quartiersmanagement fehlte)
STADTENTWICKLUNG = re.compile(r"Quartiersmanagement|\bISEK\b|Integriertes? (?:städtebauliche|Stadtentwicklung)|"
                              r"Soziale Stadt|Stadterneuerung|Städtebauförderung|Sanierungsgebiet", re.I)
# Sammellisten nichtöffentlicher Punkte, Formalien; „Miet…“ ohne Wohnbezug; Gebäude der Stadt, die auf der
# Kulturseite stehen (Bühnen, Beethovenhalle); Straßenbenennungen (Prüfung 26.10.2026)
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte in nichtöffentlicher Sitzung|Bestellung der Schriftführung|"
                        r"Sitzungstermine|Fahrradmiet|Anmietung|Mietzuschuss|mietzinsfrei|Wohnmobil|Bonner Bühnen|"
                        r"Theaterliegenschaft|Beethovenhalle|Straßenbenennung|Umbenennung der Straße|"
                        r"Benennung (?:einer|von|der) Straße", re.I)
# Stadtplanungsamt (ohne Abteilung Stadtverkehr, siehe ohne_thema), Bodenmanagement, Bauordnungsamt, Planungsausschuss
BAUEN = Zustaendig(aemter=("61 ", "62 ", "63 "), gremien=(PLANUNG,))

THEMA = Thema(
    key="wohnen",
    pfad="thema/wohnen-und-bauen/",
    titel="Wohnen und Bauen",
    lead="Welche Vorlagen und Verfahren betreffen Wohnen und Bauen in Bonn – Bebauungspläne, Wohnraum, den "
         "„Bau-Turbo“ und Denkmalschutz? Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der "
         "Wahlperiode ({seit}) und zeigt, wann und wo darüber beraten wird. Gebäude der Stadt wie Schulen und "
         "Bühnen gehören nicht dazu.",
    seo_text="Wohnen und Bauen in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Bebauungsplänen, Wohnraum, "
             "„Bau-Turbo“ und Denkmalschutz, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("turbo", "„Bau-Turbo“ und schnellere Planung",
         "Titel nennt den „Bau-Turbo“, § 36a oder § 246e BauGB, den „Planungsturbo“ oder eine Verfahrensbeschleunigung"),
        ("bebauungsplan", "Bebauungspläne",
         "Titel nennt einen Bebauungsplan, den Flächennutzungsplan, eine Veränderungssperre, einen Fluchtlinienplan "
         "oder die Bauleitplanung"),
        ("wohnraum", "Wohnraum",
         "Titel nennt Wohnungsbau, Wohnraum, geförderte oder bezahlbare Wohnungen, die VEBOWAG, Mietspiegel, "
         "Leerstand, Zweckentfremdung, das Handlungskonzept Wohnen oder Wohnungslosigkeit (auch Housing First)"),
        ("denkmal", "Denkmalschutz",
         "Titel nennt Denkmalschutz, ein Denkmal oder eine Denkmalbereichssatzung (nicht Verkehr)"),
        ("weitere", "Weitere Vorlagen zu Planen und Bauen",
         "Stadtplanungsamt (ohne Verkehr), Bodenmanagement oder Bauordnungsamt federführend oder Beratung im "
         "Ausschuss für Planen, Bauen und Denkmalschutz, dazu Quartiersmanagement, ISEK und Städtebauförderung, "
         "ohne die Merkmale der anderen Stränge und ohne Straßenbenennungen; nach Stadtbezirk"),
    ],
    regeln=[
        Regel("turbo", titel=TURBO),
        Regel("bebauungsplan", titel=PLAN),
        Regel("wohnraum", titel=WOHNRAUM),
        Regel("denkmal", titel=DENKMAL, ohne_thema="verkehr"),  # nicht Tempo 30 an einem Denkmal
        Regel("weitere", zustaendig=BAUEN, ohne_thema="verkehr"),
        Regel("weitere", titel=STADTENTWICKLUNG),
    ],
    ausschluss=AUSSCHLUSS,
    nach_bezirk=frozenset({"weitere"}),  # je Stadtbezirk eingeklappt (Entscheidung 26.10.2026)
    punkt_straenge=("turbo", "bebauungsplan", "wohnraum", "denkmal", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss, Planungsausschuss oder Sozialausschuss (Wohnen)
    punkt_gremien=("Rat", "Hauptausschuss", PLANUNG, SOZIAL),
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("planung", "Planungsausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"planung": (PLANUNG,)},
    sitzungen=(PLANUNG, SOZIAL, "Ausschuss für Finanzen, Beteiligungen und Vergabe", "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("planung"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Planen und Bauen der Ausschuss für Planen, Bauen und Denkmalschutz"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Gremium und Wörtern im Titel, je Vorlage "
            "mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Wohnen und Bauen in Rat, Hauptausschuss, Planungs- und Sozialausschuss",
    feed_text="zu Wohnen und Bauen",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 26.10.2026 im Gespräch geprüft (19 passend, 5 teilweise, "
                  "1 unpassend; in der Gegenprobe fehlte 1 von 5), danach wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge und Mieten:</strong> Kosten, Fördersummen und Mietpreise stehen in den Dokumenten der "
        "Vorlagen, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je Vorlage; Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Bebauungspläne auf der Karte:</strong> Geltungsbereich und Planchronik rechtskräftiger Pläne zeigt "
        "die Ebene „Bebauungspläne“ der <a href=\"../../?plaene=1\">Karte</a>.",
        "<strong>Gebäude der Stadt</strong> (Schulen, Bühnen, Sporthallen) und Vorlagen zum Verkehr stehen auf den "
        "jeweiligen Themenseiten. Nichtöffentliche Beratungen fehlen.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter
    # Vorlagen mit Bezug zu Wohnen oder Bauen im Titel
    stichprobe_je_strang={"turbo": 5, "bebauungsplan": 5, "wohnraum": 5, "denkmal": 5, "weitere": 5},
    stichprobe_ohne=5,
    kandidat=re.compile(r"Wohn|Bauvor|Bauantrag|Baugenehmigung|Grundstück|Quartier|Städtebau|Stadtentwicklung|"
                        r"Rahmenplan|Nachverdichtung|Baulücke|Erhaltungssatzung|Gestaltungssatzung|Neubaugebiet", re.I),
    farben=("#be123c", "#e11d48", "#fb7185"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<path d="M3 11 12 4l9 7"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-6h4v6"/>',
    produktbereich="10",  # Haushalt: Ist und Plan dieses Produktbereichs (Entscheidung 27.10.2026)
    fachausschuss=PLANUNG,  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
