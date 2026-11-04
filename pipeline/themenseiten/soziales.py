"""Themenseite „Soziales, Gesundheit und Integration“ (thema/soziales-gesundheit-und-integration/). Phase 0 und
Entscheidungen: themen/phase0/WEITERE.md (Abschnitt a), soziales/PHASE1.md; Prüfbogen im Gespräch geprüft am
02.11.2026, danach Regeln A und B (soziales/PRUEFUNG.md).

Eigene Regeln (Entscheidungen 02.11.2026): Amt für Soziales und Wohnen (50, ohne Wohnen), Amt für Integration und
Vielfalt (05), Gesundheitsamt (53), Seniorenzentren, Gleichstellungsbeauftragte (04), Ausschuss für Soziales, Migration,
Gesundheit, Wohnen und Senioren und Ausschuss für Chancengerechtigkeit und Integration sowie Wörter im Titel. Wohnen
bleibt auf der Seite Wohnen und Bauen: Die Regeln über Amt und Ausschuss überspringen Vorlagen, die dort stehen
(Regel-Feld ohne_seite). Wohnungslosigkeit, Housing First und Unterkünfte stehen über Wörter im Titel auf beiden
Seiten. Titel zu Unterkünften stehen wörtlich wie in der Quelle. Keine Bewertung, keine Beträge je Vorlage, keine
Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt, wohnen

SOZIAL = "Ausschuss für Soziales, Migration, Gesundheit, Wohnen und Senioren"
ACI = "Ausschuss für Chancengerechtigkeit und Integration"

# „Unterbringung“ allein nicht (Stadtmuseum, UN-Mitarbeitende; vor dem Ziehen des Prüfbogens, 02.11.2026)
GEFLUECHTET = re.compile(r"Geflüchtete|Geflüchteten|Flüchtling|Asyl|Unterkunft für|Unterkünfte|Übergangswohnheim|"
                         r"Notunterkunft|Erstaufnahme|Landesaufnahme|Zentrale Unterbringung|\bZUE\b|Ukrain|Abschiebung|"
                         r"Rückführung|Bezahlkarte|Schutzsuchend|Sichere[rn]? Häfen", re.I)
# Wohnungslosigkeit steht auch auf der Seite Wohnen und Bauen (Entscheidung 02.11.2026): eigene Regel ohne ohne_seite
WOHNUNGSLOS = re.compile(r"Wohnungslos|Obdachlos|Housing First|Kältehilfe|Wärmestube", re.I)
# „Tafel“ nicht in „Gedenktafel“ oder „Gedenkstein/-tafel“ (vor dem Ziehen des Prüfbogens, 02.11.2026)
ARMUT = re.compile(r"Armut|Bonn-Ausweis|MobilPass|Sozialticket|Sozialpass|Grundsicherung|Bürgergeld|SGB II\b|"
                   r"SGB XII|Sozialhilfe|Bedarfe für Unterkunft|Kosten der Unterkunft|\bKdU\b|Jobcenter|Wohngeld|"
                   r"Schuldnerberatung|(?<![\w/-])Tafel\b|Bildung und Teilhabe|Sozialleistung|Existenzsicherung", re.I)
# „Pflege“ nur in Wörtern der Pflege von Menschen (nicht Grün-, Heimat-, Denkmalpflege, „Pflegearbeiten“, Pflegekinder);
# nicht „inklusive“ (vor dem Ziehen des Prüfbogens, 02.11.2026)
SENIOREN = re.compile(r"Senior|Pflege(?:versicherung|satz|sätze|dienst|heim|einrichtung|stützpunkt|bedürftig|kr[aä]ft|"
                      r"beratung|-?[Ww]ohngeld|infrastruktur|konferenz|bedarf|platz|plätze|angebot|grad|stufe)|"
                      r"pflegebedürftig|Altenpflege|Kurzzeitpflege|Alter und Pflege|in der Pflege\b|Altenhilfe|"
                      r"[Ää]ltere[nr]? Menschen|im Alter\b|Demenz|Inklusion|Behinderung|behindert|Teilhabeplan|"
                      r"Gehörlos|Gebärdensprache|Leichte Sprache|Eingliederungshilfe|Einsamkeit|Hospiz|Palliativ|Beatmung",
                      re.I)
# „barrierefrei“ betrifft meist Haltestellen, Unterführungen und Toiletten: nur mit Amt oder Ausschuss des Themas
BARRIEREFREI = re.compile(r"barrierefrei|Barrierefreiheit", re.I)
# nicht „Klinik“ allein (Zufahrten, Bauvorhaben auf Klinikgelände), nicht „medizinisch“ (Vergabe von Bedarf)
GESUNDHEIT = re.compile(r"Gesundheit|Krankenhaus|Krankenhäuser|Krankenversicherung|ärztlich|Ärzt|Hebamme|"
                        r"Schwangerschaft|Drogen|Sucht|Crack|Konsumraum|Alkohol|Cannabis|Substitution|Methadon|Impf|"
                        r"Infektion|Psychiatr|psychisch|Suizid|Pandemie|Masern", re.I)
# „Migration“ nicht als Umstellung von IT-Verfahren (260142), „Diversität“ nicht in „Biodiversität“, „Integration“
# nicht von Ladesäulen, „Integration“ und „Chancengerechtigkeit“ nicht im Namen des Ausschusses (vor dem Ziehen des
# Prüfbogens, 02.11.2026)
INTEGRATION = re.compile(r"(?<!Chancengerechtigkeit und )Integration(?! von (?:Bordstein|Lade))|Migrant|Migration(?!sunterstützung)|Vielfalt|"
                         r"(?<!Bio)[Dd]iversität|Diskriminierung|Rassismus|Antisemitismus|Muslim|Einbürgerung|Sprachkurs|"
                         r"interkulturell|Zuwander|Zugewandert|(?<!Ausschuss für )(?<!Ausschusses für )Chancengerechtigkeit|"
                         r"Gleichstellung|Frauenhaus|Gewalt gegen Frauen|Istanbul-Konvention|queer|LSBTI|Regenbogen|"
                         r"Ausländer(?:amt|behörde)|Aufenthaltsrecht|AufenthG|Staatsa\w*gehörigkeit|nachzug|"
                         r"ausländischer Berufsabschl|Rechtsextremismus|"
                         # Regel B (Prüfung 02.11.2026): soziales Miteinander und Zusammenhalt (Gegenprobe 253927)
                         r"[Ss]oziale[sn]? Miteinander|sozialen? Zusammenhalt|Zusammenleben",
                         re.I)
# Zuschüsse und Förderung von Trägern und Vereinen aus den Ämtern und Ausschüssen des Themas stehen unter „weitere“
# (Entscheidung 02.11.2026); nicht „Bezuschussung“ von Tickets (Bonn-Ausweis)
ZUSCHUSS = re.compile(r"\bZuschuss (?:an|für)|\bZuschüsse (?:an|für)|\bZuschusses (?:an|für|zur)|\bZuwendung(?:en)? an|"
                      r"Förderung (?:der|des) [^;]{0,120}(?:\be\. ?V\.|Vereins)", re.I)
# Formalien (Besetzung, Benennung, Wahl), Sammellisten nichtöffentlicher Punkte, Straßenbenennungen, Baumfällungen,
# Parken und Halten; Wohnprojekte (auf der Seite Wohnen und Bauen nicht erfasst) und Bauleitplanung außer mit
# Wohnungslosigkeit, Geflüchteten oder Unterkünften (vor dem Ziehen des Prüfbogens, 02.11.2026)
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte? (?:zur Beratung )?in nicht ?öffentlicher Sitzung|Punkte der nichtöffentlichen Sitzung|"
                        r"Bestellung (?:der|zur) Schriftführung|Sitzungstermine|Wahl (?:des|der)[ /].{0,20}Vorsitz|"
                        r"stellvertretenden Vorsitz|Benennung von sachkundigen|Nachbenennung|Ersatzbenennung|"
                        r"Entsendung von|Zuständigkeitsordnung|Bestellung von Mitgliedern|"
                        r"Benennung (?:von|einer|eines|der) (?:\w+ )?(?:Mitglied|Vertret|Delegiert|Jury|Wirtschaftsprüf)|"
                        r"Besetzung der|Neuwahl de[rs]|Wahlausschuss|Gültigkeit der (?:Kommunal)?[Ww]ahl|"
                        r"Straßenbenennung|Fällung|Parkplatz|Parkmöglichkeit|Halteflächen|Halteverbot|\bParken\b|"
                        # Regel A (Prüfung 02.11.2026): Friedhöfe und Bestattungswesen (Seite Klima und Umwelt), auch wenn
                        # der ACI oder der Sozialausschuss mitberät (260145-02 Gebührenkalkulation); muslimische
                        # Bestattungsflächen bleiben bei der Integration
                        r"^(?!.*muslim).*(?:Friedhof|Bestattungswesen)|"
                        r"^(?!.*(?:Wohnungslos|Obdachlos|Housing First|Geflücht|Flüchtling|Unterkunft|Unterkünft))"
                        r".*(?:Wohnprojekt|Bebauungsplan|Baugesetzbuch)", re.I)
ZUST = Zustaendig(aemter=("50 ", "05 ", "53 ", "04 ", "Seniorenzentren"), gremien=(SOZIAL, ACI))

THEMA = Thema(
    key="soziales",
    pfad="thema/soziales-gesundheit-und-integration/",
    titel="Soziales, Gesundheit und Integration",
    lead="Welche Vorlagen und Verfahren betreffen soziale Leistungen, Gesundheit und Integration in Bonn – Geflüchtete "
         "und ihre Unterbringung, Integration und Vielfalt, Armut, Senioren, Pflege und Inklusion, Gesundheit und Sucht? "
         "Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, "
         "wann und wo darüber beraten wird. Wohnen steht auf der Seite Wohnen und Bauen.",
    seo_text="Soziales, Gesundheit und Integration in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Geflüchteten, "
             "Integration, Armut, Senioren, Pflege, Inklusion und Gesundheit, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("gefluechtete", "Geflüchtete und Unterbringung",
         "Titel nennt Geflüchtete, Asyl, Unterkünfte, Unterbringung, Übergangswohnheime, die Aufnahme oder die "
         "Bezahlkarte"),
        ("armut", "Armut und soziale Leistungen",
         "Titel nennt Armut, den Bonn-Ausweis, das Sozialticket, Grundsicherung, Bürgergeld, Sozialhilfe, Kosten der "
         "Unterkunft, Wohngeld, die Tafel oder Wohnungslosigkeit (auch Housing First)"),
        ("senioren", "Senioren, Pflege und Inklusion",
         "Titel nennt Senioren, Pflege, ältere Menschen, Demenz, Inklusion, Behinderung, den Teilhabeplan, "
         "Gebärdensprache oder Leichte Sprache; „barrierefrei“ nur ohne Verkehr"),
        ("gesundheit", "Gesundheit und Sucht",
         "Titel nennt Gesundheit, Krankenhäuser, ärztliche Versorgung, Hebammen, Drogen, Sucht, Alkohol, Impfungen, "
         "Infektionen oder psychische Erkrankungen"),
        ("integration", "Integration und Vielfalt",
         "Titel nennt Integration, Migration (nicht IT), Vielfalt, Diskriminierung, Rassismus, Einbürgerung, "
         "Sprachkurse, Gleichstellung oder Gewalt gegen Frauen"),
        ("weitere", "Weitere Vorlagen zu Soziales, Gesundheit und Integration",
         "Amt für Soziales und Wohnen, Amt für Integration und Vielfalt, Gesundheitsamt, Seniorenzentren oder "
         "Gleichstellungsbeauftragte federführend oder Beratung im Sozialausschuss oder im Ausschuss für "
         "Chancengerechtigkeit und Integration, ohne die Merkmale der anderen Stränge und ohne Vorlagen der Seite "
         "Wohnen und Bauen; dazu Zuschüsse an Träger und Vereine aus diesen Ämtern und Ausschüssen; ohne Formalien "
         "und Sammellisten nichtöffentlicher Punkte"),
    ],
    regeln=[
        Regel("weitere", titel=ZUSCHUSS, zustaendig=ZUST, ohne_seite=wohnen.THEMA),
        Regel("gefluechtete", titel=GEFLUECHTET),
        Regel("armut", titel=WOHNUNGSLOS),
        Regel("armut", titel=ARMUT),
        Regel("senioren", titel=SENIOREN, ohne_thema="verkehr"),
        Regel("senioren", titel=BARRIEREFREI, zustaendig=ZUST),
        Regel("gesundheit", titel=GESUNDHEIT, ohne_thema="verkehr"),
        Regel("integration", titel=INTEGRATION, ohne_thema="verkehr"),
        Regel("weitere", zustaendig=ZUST, ohne_seite=wohnen.THEMA),
    ],
    ausschluss=AUSSCHLUSS,
    eingeklappt={"weitere"},
    punkt_straenge=("gefluechtete", "armut", "senioren", "gesundheit", "integration", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss oder Sozialausschuss (Entscheidung 02.11.2026)
    punkt_gremien=("Rat", "Hauptausschuss", SOZIAL),
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("sozial", "Sozialausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"sozial": (SOZIAL,)},
    sitzungen=(SOZIAL, ACI, "Ausschuss für Finanzen, Beteiligungen und Vergabe", "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("sozial"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Soziales der Ausschuss für Soziales, Migration, Gesundheit, Wohnen und Senioren"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Gremium und Wörtern im Titel, je Vorlage "
            "mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Soziales, Gesundheit und Integration in Rat, Hauptausschuss, Sozialausschuss und "
               "Bezirksvertretungen",
    feed_text="zu Soziales, Gesundheit und Integration",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 02.11.2026 im Gespräch geprüft (24 passend, 0 teilweise, "
                  "1 unpassend; in der Gegenprobe fehlte 1 von 5), danach wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten, Leistungen und Zuschüsse stehen in den Dokumenten der Vorlagen und im "
        "Haushaltsplan der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je "
        "Vorlage; Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Einzelfälle</strong> sozialer Leistungen sind keine Vorlagen und erscheinen nicht. Nichtöffentliche "
        "Beratungen fehlen.",
        "<strong>Wohnen</strong> (Wohnungsbau, Mietspiegel, Handlungskonzept Wohnen) steht auf der Seite Wohnen und "
        "Bauen; Vorlagen zu Wohnungslosigkeit und Unterkünften stehen auf beiden Seiten.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter Vorlagen
    # mit Wörtern des Themas im Titel
    stichprobe_je_strang={"gefluechtete": 4, "armut": 4, "senioren": 4, "gesundheit": 4, "integration": 4,
                          "weitere": 5},
    stichprobe_ohne=5,
    kandidat=re.compile(r"Sozial|Migra|Integra|Flücht|Gesund|Senior|(?<!\w)Pflege|Armut|Behind|Inklus|Sucht|Drogen|"
                        r"Teilhabe|(?<!\w)Frauen|Ausländ|Krank|Hilfen? für", re.I),
    farben=("#86198f", "#a21caf", "#e879f9"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<path d="M12 20s-7-4.4-7-9.6A4 4 0 0 1 12 8a4 4 0 0 1 7 2.4C19 15.6 12 20 12 20z"/><path d="M12 11v4M10 13h4"/>',
    produktbereich="05",  # Haushalt: Soziale Leistungen (Entscheidung 02.11.2026)
    fachausschuss=(SOZIAL, ACI),  # Kasten „Wer berät mit“: beide Ausschüsse (Entscheidung 02.11.2026)
)
