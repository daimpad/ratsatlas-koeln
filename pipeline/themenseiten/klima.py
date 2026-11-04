"""Themenseite „Klima und Umwelt“ (thema/klima-und-umwelt/). Phase 0 und Entscheidungen: klima/phase0/BERICHT.md;
Prüfbogen im Gespräch geprüft am 26.10.2026, danach Regeln A–E (klima/PRUEFUNG.md).

Eigene Regeln (Entscheidung 26.10.2026): Wörter im Titel für Klimaschutz und Energie, Klimaanpassung, Grün und
Natur, Abfall und Sauberkeit; übrige Vorlagen aus Umweltamt, Umweltausschuss und Naturschutzbeirat nach Stadtbezirk
(darunter Lärm, Luft und Friedhöfe). Vorlagen zum Verkehr bleiben auf der Verkehrsseite, auch Maßnahmen des
Klimaplans. Keine Bewertung, keine Beträge je Vorlage, keine Zitate."""
import re
from datetime import date

from ..dossier import Regel, Thema, Zustaendig
from . import haushalt

UMWELT = "Ausschuss für Umwelt, Klima und Lokale Agenda"
# nicht das Sondervermögen „Infrastruktur und Klimaneutralität“ des Bundes (ein Haushaltsfonds)
KLIMASCHUTZ = re.compile(r"Klimaschutz|Klimaplan|(?<!Infrastruktur und )Klimaneutral|Klimanotstand|Klimabeirat|Klimasteckbrief|CO2|CO₂|"
                         r"Treibhaus|Wärmeplan|Wärmewende|Solar|Photovoltaik|\bPV\b|PV-Anlage|Fernwärme|Windenergie|"
                         r"Windkraft|Energiewende|Energieeinspar|Energiekonzept|Energieeffizien|Energie Agentur", re.I)
ANPASSUNG = re.compile(r"Klimaanpassung|Hitze|Starkregen|Hochwasser|Überschwemm|Schwammstadt|Entsiegel|Trinkbrunnen|"
                       r"Trinkwasserbrunnen|Kühle Orte|Verschattung|Regenwasser", re.I)
# „Baum“ nicht in „Baumaßnahme“ oder „Baumarkt“; nicht „Park“ allein (Parken)
GRUEN = re.compile(r"\bBäume|\bBaum(?!aßnahme|arkt)|Fällgenehm|Fällung|Grünfläche|Grünanlage|Grünzug|Parkanlage|"
                   r"Stadtpark|Naturschutz|Naturpark|Biotop|Landschaftsschutz|\bWald|Kleinstwald|Insekt|Blühwiese|"
                   r"Blühstreifen|Begrünung|Kleingarten|Streuobst|Artenschutz|Biodiversität|Vogelschutz|Freiraumplan|"
                   r"Rheinaue|Neozoen|Neophyt|invasive Arten|heimische (?:Arten|Fauna|Flora)|autochthon", re.I)
# Toiletten in Parks gehören nicht zu Grün und Natur, sondern zu „weitere“ (Prüfung 26.10.2026)
TOILETTE = re.compile(r"Toilette|\bWC\b", re.I)
# „klimagerecht“ u. Ä. erst nach den übrigen Strängen (Prüfung 26.10.2026: Hof- und Fassadenprogramm fehlte)
KLIMAGERECHT = re.compile(r"klimagerecht|klimafreundlich|klimaangepasst", re.I)
LAERM = re.compile(r"Lärm", re.I)  # auch ohne Umweltamt als Federführung (Prüfung 26.10.2026)
ABFALL = re.compile(r"Abfall|Müll|Sauberkeit|Mülleimer|Papierkörbe|Wertstoff|Glascontainer|Altglas|Recycling|"
                    r"Eigenreinigung|Straßenreinigung|Littering|Verpackung|Mehrweg|Sperrmüll|illegal entsorg|bonnorange",
                    re.I)
# Bau-Turbo und Planungsbeschleunigung stehen auf der Seite Wohnen und Bauen (Prüfung 26.10.2026)
AUSSCHLUSS = re.compile(r"Tagesordnungspunkte in nichtöffentlicher Sitzung|Bestellung der Schriftführung|"
                        r"Sitzungstermine|Bau-?Turbo|§ ?36a|Planungsturbo", re.I)
UMWELTAMT = Zustaendig(aemter=("67 ",), gremien=(UMWELT, "Naturschutzbeirat"))
OHNE = "verkehr"  # Verkehr bleibt auf der Verkehrsseite (Entscheidung 26.10.2026)

THEMA = Thema(
    key="klima",
    pfad="thema/klima-und-umwelt/",
    titel="Klima und Umwelt",
    lead="Welche Vorlagen und Verfahren betreffen Klima und Umwelt in Bonn – Klimaschutz und Energie, Anpassung an "
         "Hitze und Starkregen, Bäume und Grün, Abfall und Sauberkeit? Diese Seite ordnet Vorlagen aus dem "
         "Ratsinformationssystem seit Beginn der Wahlperiode ({seit}) und zeigt, wann und wo darüber beraten wird. "
         "Vorlagen zum Verkehr stehen auf der Seite Verkehr und Mobilität.",
    seo_text="Klima und Umwelt in Bonn: {n} Vorlagen aus dem Ratsinformationssystem zu Klimaschutz und Energie, "
             "Klimaanpassung, Bäumen und Grün, Abfall und Sauberkeit, mit den nächsten Sitzungen.",
    seit="2025-11-01",  # Beginn der 12. Wahlperiode (legislative_terms)
    straenge=[
        ("klimaschutz", "Klimaschutz und Energie",
         "Titel nennt Klimaschutz, den Klimaplan, Klimaneutralität, CO2, Wärmeplanung, Solar, Fernwärme, Windenergie "
         "oder Energieeinsparung, dazu „klimagerecht“ und „klimafreundlich“ (nicht Verkehr)"),
        ("anpassung", "Klimaanpassung",
         "Titel nennt Klimaanpassung, Hitze, Starkregen, Hochwasser, Überschwemmung, Entsiegelung, Trinkbrunnen oder "
         "Regenwasser (nicht Verkehr)"),
        ("gruen", "Bäume, Grün und Natur",
         "Titel nennt Bäume, Fällungen, Grünflächen, Parkanlagen, Naturschutz, Biotope, Wald, Kleingärten, Begrünung "
         "oder Artenschutz, auch heimische und invasive Arten (nicht Verkehr, nicht Toiletten)"),
        ("abfall", "Abfall und Sauberkeit",
         "Titel nennt Abfall, Müll, Sauberkeit, Wertstoffe, Glascontainer, Verpackung, Mehrweg oder Straßenreinigung "
         "(nicht Verkehr)"),
        ("weitere", "Weitere Vorlagen zu Umwelt",
         "Amt für Umwelt und Stadtgrün federführend oder Beratung im Umweltausschuss oder Naturschutzbeirat, ohne die "
         "Merkmale der anderen Stränge, dazu Lärm im Titel; ohne Verkehr und ohne „Bau-Turbo“ (darunter Luft, "
         "Friedhöfe und Toiletten in Parks); nach Stadtbezirk"),
    ],
    regeln=[
        Regel("klimaschutz", titel=KLIMASCHUTZ, ohne_thema=OHNE),
        Regel("anpassung", titel=ANPASSUNG, ohne_thema=OHNE),
        Regel("weitere", titel=TOILETTE, bedingung=GRUEN, ohne_thema=OHNE),
        Regel("gruen", titel=GRUEN, ohne_thema=OHNE),
        Regel("abfall", titel=ABFALL, ohne_thema=OHNE),
        Regel("klimaschutz", titel=KLIMAGERECHT, ohne_thema=OHNE),
        Regel("weitere", zustaendig=UMWELTAMT, ohne_thema=OHNE),
        Regel("weitere", titel=LAERM, ohne_thema=OHNE),
    ],
    ausschluss=AUSSCHLUSS,
    nach_bezirk=frozenset({"weitere"}),  # je Stadtbezirk eingeklappt (Entscheidung 26.10.2026)
    punkt_straenge=("klimaschutz", "anpassung", "gruen", "abfall", "weitere"),
    # Punkte im Bild nur mit Beratung in Rat, Hauptausschuss oder Umweltausschuss
    punkt_gremien=("Rat", "Hauptausschuss", UMWELT),
    bahnen=[haushalt.BAHN, ("bv", "Bezirksvertretungen"), ("umwelt", "Umweltausschuss"),
            ("fach", "andere Ausschüsse"), ("finanz", "Finanzausschuss"), ("rat", "Hauptausschuss, Rat")],
    bahn_gremien={"umwelt": (UMWELT,)},
    sitzungen=(UMWELT, "Ausschuss für Finanzen, Beteiligungen und Vergabe", "Hauptausschuss", "Rat"),
    sitzungen_je_gremium=2,
    achse=(date(2025, 11, 1), date(2027, 4, 1), date(2026, 9, 1), 0.42),
    # Haushalt 2027/2028 laut Terminplan in 261064 (themenseiten/haushalt.py)
    terminplan=haushalt.TERMINPLAN,
    phasen=haushalt.phasen("umwelt"),
    phasen_text=haushalt.TEXT,
    fenster_text=haushalt.FENSTER,
    schritte_titel=haushalt.TITEL,
    schritte=haushalt.schritte("für Umwelt und Klima der Ausschuss für Umwelt, Klima und Lokale Agenda"),
    hinweis="Zuordnung zu den Strängen abgeleitet (feste Regeln aus Amt, Gremium und Wörtern im Titel, je Vorlage "
            "mit Grund); Schritte des Haushalts aus Drucksache 261064 zusammengefasst, keine Zitate",
    bild_titel="Zeitleiste: Klima und Umwelt in Rat, Hauptausschuss und Umweltausschuss",
    feed_text="zu Klima und Umwelt",
    pruefung_text="Eine Stichprobe von 30 Vorlagen wurde am 26.10.2026 im Gespräch geprüft (17 passend, 6 teilweise, "
                  "2 unpassend; in der Gegenprobe fehlten 2 von 5), danach wurden die Regeln ergänzt.",
    nicht_gezeigt=[
        "<strong>Beträge:</strong> Kosten und Fördersummen stehen in den Dokumenten der Vorlagen und im Haushaltsplan "
        "der Stadt, nicht in den Daten des Ratsinformationssystems. Die Seite übernimmt keine Beträge je Vorlage; Beträge je Produktbereich stehen im Abschnitt „Haushalt“.",
        "<strong>Hitze und Überschwemmung auf der Karte:</strong> Den Anteil der Einwohner in Flächen mit dringendem "
        "Handlungsbedarf bei Hitze zeigt die <a href=\"../../?flaechen=kontext-hitze\">Karte</a> je Gebiet, die "
        "Überschwemmungsgebiete die <a href=\"../../?ebenen=uesg\">Ebene Überschwemmungsgebiete</a>.",
        "<strong>Vorlagen zum Verkehr</strong>, auch Maßnahmen des Klimaplans wie Radverkehr oder Fahrradmietsystem, "
        "stehen auf der Seite Verkehr und Mobilität. Nichtöffentliche Beratungen fehlen.",
    ],
    # Prüfbogen (einmalig): je Strang einige zugeordnete Vorlagen, dazu eine Gegenprobe nicht zugeordneter
    # Vorlagen mit Bezug zu Klima oder Umwelt im Titel
    stichprobe_je_strang={"klimaschutz": 5, "anpassung": 5, "gruen": 5, "abfall": 5, "weitere": 5},
    stichprobe_ohne=5,
    # nicht „Grün“ allein (Parteiname), nicht „Tier“ in „Quartier“, nicht Ortsnamen wie Wasserland oder Hofgarten
    kandidat=re.compile(r"Klima|Umwelt|Grünfl|Grünanl|Grünpfl|Begrün|Natur|Energie|Gewässer|Grundwasser|Trinkwasser|"
                        r"Lärm|Luftqualität|\bTier|Nachhaltig|Lokale Agenda|Ressourcen", re.I),
    farben=("#047857", "#059669", "#84cc16"),  # Übersicht thema/: Schrift, Verlauf
    symbol='<path d="M5 19C5 10 11 5 20 4c-1 9-6 15-15 15z"/><path d="M5 19 13 11"/>',
    produktbereich="13",  # Haushalt: Ist und Plan dieses Produktbereichs (Entscheidung 27.10.2026)
    fachausschuss=UMWELT,  # Kasten „Wer berät mit“ (Besetzung, Fraktion abgeleitet)
)
