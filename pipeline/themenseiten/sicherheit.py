"""Themenseite „Sicherheit und Ordnung“ (thema/sicherheit-und-ordnung/). Phase 0 und Entscheidungen:
themen/phase0/WEITERE.md (Abschnitt b), sicherheit/PHASE1.md; Prüfbogen im Gespräch geprüft am 02.11.2026, danach
Regel A (sicherheit/PRUEFUNG.md).

Eigene Regeln (Entscheidungen 02.11.2026): Amt 37 Feuerwehr und Rettungsdienst (alle Abteilungen); vom Amt 33
Bürgerdienste nur die Abteilungen 33-2 (Ordnungswidrigkeiten, Stadtordnungsdienst), 33-5 (Veranstaltungskoordination
und Märkte) und das Amt allgemein (Zustaendig.abteilungen), nicht 33-1 Straßenverkehrsbehörde, 33-4
Dienstleistungszentrum, 33-6 Ausländeramt und 33-0 Wahlen; Ausschuss für Sicherheit, Ordnung und Bevölkerungsschutz;
Wörter im Titel. Verkehrssicherheit bleibt auf der Seite Verkehr und Mobilität (Regel-Feld ohne_seite);
Versorgungs-, Informations- und Cybersicherheit gehören nicht zum Thema. Der „Feuerwehrtopf“ (Mittel der
Bezirksvertretungen für Vereine) ist ausgeschlossen. Lärm bei Festen darf auch auf der Klimaseite stehen. Keine
Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt, verkehr

SICHERHEIT = "Ausschuss für Sicherheit, Ordnung und Bevölkerungsschutz"
FINANZ = "Ausschuss für Finanzen, Beteiligungen und Vergabe"

# „Feuerwehrtopf“ (Mittel der Bezirksvertretungen für Vereine) steht im Ausschluss (Entscheidung 4); Waldbrände,
# Brandverhütungsschau, vorbeugender Brandschutz (nicht die Brandschutzsanierung von Gebäuden) und Transporte
# zwischen Kliniken gehören zur Feuerwehr (vor dem Ziehen des Prüfbogens)
FEUERWEHR = re.compile(r"Feuerwehr(?!topf)|Feuerwache|Gerätehaus|Löschzug|Löschgruppe|Löschfahrzeug|Drehleiter|"
                       r"Rettungsdienst|Rettungswache|Rettungswagen|Rettungsmittel|\bRTW\b|Notarzt|Notärzt|"
                       r"Notfallsanität|Krankentransport|Interhospitaltransport|Patiententransport|Leitstelle|"
                       r"Brandschutz(?!sanierung|ertüchtigung|technisch)|Rettungsdienstbedarf|Brandbekämpfung|Brandverhütung|Waldbr[aä]nd|Buschbr[aä]nd|"
                       r"Vegetationsbr[aä]nd", re.I)
# „Katastroph…“ auch in „Katastrophenfälle“, „Katastrophenhilfe“; Business Continuity Management (BCM) als Vorsorge für
# den Betrieb der Stadt (vor dem Ziehen des Prüfbogens)
BEVOELKERUNG = re.compile(r"Bevölkerungsschutz|Schutz der Bevölkerung|Katastroph|Zivilschutz|Zivilverteidigung|"
                          r"zivile[nr]? Verteidigung|Krisenvorsorge|Krisenstab|Krisenmanagement|Krisenfall|Resilienz|"
                          r"Sirene|Warnsystem|Warn-?App|Warntag|Bevölkerungswarnung|Notstrom|Blackout|Stromausfall|"
                          r"Notfalltreffpunkt|Leuchtt[uü]rm|Schutzr[aä]um|Bunker|Großschadens|Schadenslage|"
                          r"Schadensereignis|Extremwetter|Selbstschutz|Notbrunnen|Trinkwassernot|\bBCM\b|"
                          r"Business Continuity", re.I)
# „Sicherheit“ ohne Verkehrs-, Versorgungs-, Informations-, Cyber-, IT-, Daten-, Planungs- und Rechtssicherheit
# (Entscheidung 6): nur als eigenes Wort, nicht „Sicherheit der Strom-/Wasserversorgung“, nicht „Sicherheits-“ in
# Aufzählungen von Kosten (Unterkünfte). Nicht „Bauordnungsamt“, „Gesinnungspolizei“, Graffiti-Wettbewerbe;
# Gewaltprävention an Schulen steht auf der Seite Kinder, Jugend und Familie (vor dem Ziehen des Prüfbogens)
ORDNUNG = re.compile(r"(?<![\w-])Sicherheit(?!s| der \w*[Vv]ersorgung)|(?<![\w-])Sicherheits(?!-,? |überprüfung)|"
                     r"Safe Cit|(?<![\w-])Ordnungsdienst|Stadtordnungsdienst|(?<![\w-])Ordnungsamt|Ordnungspartnerschaft|"
                     r"Ordnungsbehördliche|ordnungsrechtlich|Gefahrenabwehr|Sperrzeit|Sperrstunde|Kriminal|(?<![\w-])Polizei|Kreispolizei|Wache GABI|"
                     r"Videoüberwach|Videobeobacht|Waffenverbot|Messerverbot|Alkoholverbot|Alkoholkonsumverbot|"
                     r"Glasverbot|Glasflaschenverbot|Silvester|Feuerwerk|Böller|Pyrotechnik|Angstr[aä]um|"
                     r"Graffiti(?!-?[Ww]ettbewerb)|Vandalismus|Sachbeschädigung|Ordnungswidrigkeit|Bußgeld|Verwarn|"
                     r"Prostitution|Sperrbezirk|Aggressives Betteln|Wildpinkeln|Taubenfütter|Hundeverordnung|"
                     r"Sicheres Bonn|Kommunaler Ordnungsdienst", re.I)
# Feste allgemein („…fest“), nicht Beethovenfest, Lese-, Film- und Musikfeste (Kultur); Offenhalten von Verkaufsstellen
# aus Anlass von Festen und Märkten (vor dem Ziehen des Prüfbogens)
VERANSTALTUNG = re.compile(r"Kirmes|Pützchens Markt|Marktverzeichnis|Wochenmarkt|Weihnachtsmarkt|Flohmarkt|"
                           r"Trödelmarkt|Bauernmarkt|Krammarkt|Märkte|Marktsatzung|Marktgebühr|Marktordnung|Marktwesen|"
                           r"Volksfest|Stadtfest|Straßenfest|Rhein in Flammen|Karneval|Rosenmontag|Weiberfastnacht|"
                           r"Martinszug|Großveranstaltung|Veranstaltungsfläche|Offenhalten von Verkaufsstellen|"
                           r"verkaufsoffen|\w+(?<!Beethoven)(?<!Lese)(?<!Film)(?<!Musik)fest(?:e|es|s)?\b", re.I)
# Formalien (Schriftführung, Vorsitz, Benennungen, Sachverständige), Sammellisten nichtöffentlicher Punkte, Wahlen
# (33-0, auch wenn das Amt 33 allgemein federführend ist), Ausländeramt und Staatsangehörigkeit, Vereinsförderung
# (Feuerwehrtopf, Heimatpflege und Brauchtum), Aufsichtsräte, Berichte des Gebäudemanagements über alle Projekte;
# Verkehr ohne Kartenthema Verkehr (Bewohnerparken, Parksituation, Brötchentaste, Radfahrer, Zweiräder, Tempo und
# Geschwindigkeit, Stadtbahn) bleibt beim Verkehr (Entscheidung 6; vor dem Ziehen des Prüfbogens)
# Regel A (Prüfung 02.11.2026): Abfallwirtschaft (Altpapier, Wertstoffe, Müllabfuhr) gehört nicht zum Thema, auch wenn
# der Sicherheitsausschuss mitberät (262020); illegale Müllablagerung als Ordnungswidrigkeit bleibt
AUSSCHLUSS = re.compile(r"Altpapier|Wertstoff|Müllabfuhr|Abfallwirtschaft|Abfallgebühr|"
                        r"Feuerwehrtopf|Heimatpflege|Brauchtum|Erbbauzins|Aufsichtsrat|Vertretung der Bundesstadt Bonn in|"
                        r"Projektberichterstattung des Städtischen Gebäudemanagements|"
                        r"Tagesordnungspunkte? (?:zur Beratung )?in nicht ?öffentlicher Sitzung|"
                        r"Punkte der nichtöffentlichen Sitzung|Bestellung (?:der|zur) Schriftführung|Schriftführer|"
                        r"Sitzungstermine|Wahl (?:des|der)[ /].{0,20}Vorsitz|stellvertretenden Vorsitz|"
                        r"Benennung von sachkundigen|Nachbenennung|Ersatzbenennung|Entsendung von|Zuständigkeitsordnung|"
                        r"Benennung (?:von|einer|eines|der) (?:\w+ )?(?:Mitglied|Vertret|Delegiert)|Bestellung von Mitgliedern|"
                        r"Hinzuziehen von (?:Experten|Sachverständigen)|"
                        r"Wahlausschuss|Wahlprüfungsausschuss|Gültigkeit der (?:Kommunal)?[Ww]ahl|Landtagswahl|"
                        r"Bundestagswahl|Europawahl|Kommunalwahlen|Ausländer|Aufenthaltsrecht|Staatsa\w*gehörigkeit|"
                        r"Einbürgerung|Bewohnerpark|Anwohnerpark|Parkausweis|Parksituation|\bParken\b|Parkpl[aä]tz|"
                        r"Halteverbot|Brötchentaste|Radfahr|Zweir[aä]d|Tempo|km/h|Geschwindigkeit|Messanlage|Stadtbahn|"
                        r"Straßenbahn", re.I)
# Amt 37 (alle Abteilungen) gehört zum Strang Feuerwehr und Rettungsdienst; vom Amt 33 nur 33-2, 33-5 und das Amt
# allgemein (Entscheidung 1; Zustaendig.abteilungen)
FEUERWEHR_AMT = Zustaendig(aemter=("37 ",))
MAERKTE = Zustaendig(abteilungen=("33-5 ",))
ORDNUNG_AMT = Zustaendig(abteilungen=("33 ", "33-2 "))
AUSSCHUSS = Zustaendig(gremien=(SICHERHEIT,))
OHNE = verkehr.THEMA  # Verkehrssicherheit und Verkehrsanordnungen bleiben auf der Verkehrsseite (Entscheidung 6)

THEMA = Thema(
    key="sicherheit",
    pfad="thema/sicherheit-und-ordnung/",
    titel="Sicherheit und Ordnung",
    lead="Welche Vorlagen und Verfahren betreffen Sicherheit und Ordnung in Bonn – Feuerwehr und Rettungsdienst, "
         "Bevölkerungsschutz und Krisenvorsorge, Sicherheit im öffentlichen Raum, Veranstaltungen, Märkte und Kirmes? "
         "Diese Seite ordnet Vorlagen aus dem Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, "
         "wann und wo darüber beraten wird. Verkehrssicherheit steht auf der Seite Verkehr und Mobilität.",
    seo_text="Sicherheit und Ordnung in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Feuerwehr und "
             "Rettungsdienst, Bevölkerungsschutz, Sicherheit im öffentlichen Raum, Märkten und Kirmes, mit den "
             "nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("feuerwehr", "Feuerwehr und Rettungsdienst",
         "Titel nennt Feuerwehr, Feuerwachen, Löschzüge, Rettungsdienst, Rettungswagen, Notärzte, Krankentransporte, "
         "die Leitstelle, vorbeugenden Brandschutz oder Waldbrände; dazu Vorlagen, die das Amt Feuerwehr und "
         "Rettungsdienst (37) federführend betreut; nicht der „Feuerwehrtopf“ der Bezirksvertretungen"),
        ("bevoelkerungsschutz", "Bevölkerungsschutz und Krisenvorsorge",
         "Titel nennt Bevölkerungsschutz, Katastrophen, Zivilschutz und zivile Verteidigung, Krisenvorsorge und "
         "Krisenmanagement, Resilienz, Extremwetter, Sirenen, Warnung der Bevölkerung, Notstrom, Stromausfall oder "
         "Schutzräume"),
        ("ordnung", "Sicherheit und Ordnung im öffentlichen Raum",
         "Titel nennt Sicherheit (nicht Verkehrs-, Versorgungs-, Informations- oder Cybersicherheit), den "
         "Ordnungsdienst, ordnungsbehördliche Maßnahmen, Polizei, Kriminalität, Gefahrenabwehr, Videoüberwachung, "
         "Verbote von Waffen, Alkohol oder Glas, Silvester, Feuerwerk, Graffiti oder Ordnungswidrigkeiten; nicht "
         "Vorlagen der Seite Verkehr und Mobilität"),
        ("veranstaltungen", "Veranstaltungen, Märkte und Kirmes",
         "Titel nennt Kirmes, Märkte und Marktverzeichnisse, Feste (nicht Kulturfestivals), „Rhein in Flammen“, "
         "Karneval oder verkaufsoffene Sonntage; dazu Vorlagen der Abteilung Veranstaltungskoordination und Märkte "
         "(33-5); nicht Vorlagen der Seite Verkehr und Mobilität, nicht Vereinsförderung"),
        ("weitere", "Weitere Vorlagen zu Sicherheit und Ordnung",
         "Bürgerdienste allgemein (33) oder die Abteilung Ordnungswidrigkeiten und Stadtordnungsdienst (33-2) "
         "federführend oder Beratung im Ausschuss für Sicherheit, Ordnung und Bevölkerungsschutz, ohne die Merkmale "
         "der anderen Stränge und ohne Vorlagen der Seite Verkehr und Mobilität; ohne Wahlen, Ausländeramt, "
         "Formalien und Sammellisten nichtöffentlicher Punkte"),
    ],
    regeln=[
        Regel("feuerwehr", titel=FEUERWEHR),
        Regel("bevoelkerungsschutz", titel=BEVOELKERUNG),
        Regel("veranstaltungen", titel=VERANSTALTUNG, ohne_seite=OHNE),
        Regel("ordnung", titel=ORDNUNG, ohne_seite=OHNE),
        Regel("feuerwehr", zustaendig=FEUERWEHR_AMT),
        Regel("veranstaltungen", zustaendig=MAERKTE, ohne_seite=OHNE),
        Regel("weitere", zustaendig=ORDNUNG_AMT, ohne_seite=OHNE),
        Regel("weitere", zustaendig=AUSSCHUSS, ohne_seite=OHNE),
    ],
    ausschluss=AUSSCHLUSS,
    eingeklappt={"weitere"},
    nach_bezirk=frozenset({"veranstaltungen"}),  # Märkte, Kirmes und Feste je Stadtbezirk (Entscheidung 3)
    punkt_straenge=("feuerwehr", "bevoelkerungsschutz", "ordnung", "veranstaltungen", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss oder Sicherheitsausschuss (Entscheidung 5)
    punkt_gremien=("Rat", "Hauptausschuss", SICHERHEIT),
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("sicherheit", "Sicherheitsausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"sicherheit": (SICHERHEIT,)},
    sitzungen=(SICHERHEIT, FINANZ, "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("sicherheit"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Sicherheit und Ordnung der Ausschuss für Sicherheit, Ordnung und "
                               "Bevölkerungsschutz"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Abteilung, Gremium und Wörtern im Titel, je "
            "Vorlage mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Sicherheit und Ordnung in Rat, Hauptausschuss, Sicherheitsausschuss und "
               "Bezirksvertretungen",
    feed_text="zu Sicherheit und Ordnung",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 02.11.2026 im Gespräch geprüft (24 passend, 0 teilweise, "
                  "1 unpassend; in der Gegenprobe fehlte keine von 5), danach wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten, Gebühren und Vergaben stehen in den Dokumenten der Vorlagen und im "
        "Haushaltsplan der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je "
        "Vorlage. Der Produktbereich 02 „Sicherheit und Ordnung“ im Abschnitt „Haushalt“ enthält neben Feuerwehr, "
        "Rettungsdienst und Ordnungsdienst auch Einwohnerangelegenheiten, Kfz-Zulassung, Personenstand und Wahlen.",
        "<strong>Einsätze und Einzelfälle</strong> (Brände, Rettungseinsätze, Bußgelder) sind keine Vorlagen und "
        "erscheinen nicht. Nichtöffentliche Beratungen fehlen.",
        "<strong>Verkehrssicherheit</strong> und Verkehrsanordnungen der Straßenverkehrsbehörde stehen auf der Seite "
        "Verkehr und Mobilität; Ausländeramt, Wahlen und Bürgerbüro gehören nicht zum Thema. Lärm bei Festen steht "
        "auch auf der Seite Klima und Umwelt.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter Vorlagen
    # mit Wörtern des Themas im Titel
    stichprobe_je_strang={"feuerwehr": 5, "bevoelkerungsschutz": 4, "ordnung": 6, "veranstaltungen": 5, "weitere": 5},
    stichprobe_ohne=5,
    # Wortanfänge: nicht Verkehrs- oder Cybersicherheit, nicht „Brandengarten“, „Auf dem Brand“ oder „Marktentwicklung“
    kandidat=re.compile(r"(?<![\w-])Sicherheit|(?<![\w-])Ordnung|(?<![\w-])ordnungs|Feuer|(?<![\w-])Brand(?!engarten)"
                        r"(?<!dem Brand)|Rettung|(?<![\w-])Markt(?!entwicklung)|Kirmes|(?<![\w-])Fest\b|Polizei|Notfall|"
                        r"(?<![\w-])Krise|(?<![\w-])Gefahr|Überwach|Kontrolle", re.I),
    farben=("#991b1b", "#dc2626", "#f97316"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
    produktbereich="02",  # Haushalt: Sicherheit und Ordnung (Entscheidung 5)
    fachausschuss=SICHERHEIT,  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
