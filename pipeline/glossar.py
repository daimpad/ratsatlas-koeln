"""Glossar für Seite und Ratsassistent (data/export/glossar.json, eine Quelle für beide).

- ergebnisse: Ergebnistexte und Rollen der Beratung, wie sie wörtlich in den Quellen stehen
- hinweise: Erläuterungen zu Prozessschritten (Schlüssel `note` in den Exporten, process.NOTES)
- schritte, evidenz, staende: Bezeichnungen der Prozessebene (process.py)
- themen: Bezeichnungen der abgeleiteten Themen (topics.py)
- begriffe: allgemeine Begriffe mit Fundstelle (Gemeindeordnung NRW bzw. Datenfeld), je mit Gruppe und Sprungmarke
  für die Seite begriffe/; allgemeine Erklärungen, keine Rechtsberatung
- arten, kuerzel: Vorlagenart bzw. Kürzel der Drucksachennummer → Sprungmarke des Begriffs (Erklärung im Vorgang)

Köln (04.11.2026): Begriffe und Fundstellen auf Köln umgestellt, Gruppe „Gebiete“ ergänzt; Bonner Vorlagenarten,
Kürzel und Haushaltsbegriffe entfernt. Aus Bonn übernommen (02.11.2026): einfachere Wörter für eigene Bezeichnungen der Seite („Anstoß“ statt
„Initiierung“, „Umsetzung“ statt „Vollzug“). Wo eine Vorlagenart in keinem Regelwerk beschrieben ist, ist die
Erklärung aus Titeln und Beratungsfolge erschlossen und so gekennzeichnet."""
import re

from . import config, process as proc, topics

ERGEBNISSE = {
    "ungeändert beschlossen": "Das Gremium hat dem Vorschlag in der vorgelegten Fassung zugestimmt.",
    "geändert beschlossen": "Das Gremium hat zugestimmt, aber mit Änderungen, etwa aus Änderungsanträgen.",
    "zur Kenntnis genommen": "Das Gremium wurde informiert; über einen Beschluss wurde nicht abgestimmt.",
    "abgelehnt": "Die Mehrheit des Gremiums hat dagegen gestimmt.",
    "vertagt": "Die Beratung wurde auf eine spätere Sitzung verschoben.",
    "zurückgezogen": "Die Einreichenden haben die Vorlage zurückgenommen.",
    "verwiesen": "Die Vorlage wurde zur Beratung an ein anderes Gremium weitergegeben.",
    "nicht abgestimmt": "In dieser Sitzung fand keine Abstimmung statt.",
    "ohne Votum": "Das Gremium hat keine Empfehlung abgegeben.",
    "erledigt durch Stellungnahme der Verwaltung": "Der Antrag gilt als erledigt, weil die Verwaltung schriftlich "
                                                   "Stellung genommen hat.",
    "wg. Sitzungsabbruch nicht behandelt (vertagt)": "Die Sitzung wurde abgebrochen, bevor der Punkt beraten wurde; "
                                                      "er gilt als vertagt.",
    "weitere Lesung erforderlich": "Das Gremium hat beraten, aber noch nicht abschließend; der Punkt soll in einer "
                                   "weiteren Sitzung erneut beraten werden.",
    "weitere Lesung": "Das Gremium hat beraten, aber noch nicht abschließend; der Punkt soll in einer weiteren Sitzung "
                      "erneut beraten werden.",
    "bei Anerkennung der Tagesordnung nicht aufgenommen oder vertagt": "Der Punkt wurde zu Beginn der Sitzung von der "
                                                                       "Tagesordnung genommen oder verschoben.",
    "mit Protokollnotiz": "Zusätzlich wurde eine Anmerkung ins Protokoll aufgenommen.",
    "mit Maßgabe": "Der Beschluss gilt mit einer zusätzlichen Bedingung oder Vorgabe.",
    "Entscheidung": "Dieses Gremium entscheidet abschließend.",
    "Empfehlung": "Das Gremium berät vor und gibt eine Empfehlung an das entscheidende Gremium.",
    "Anhörung": "Das Gremium wird angehört; seine Stellungnahme ist nicht bindend.",
    "Kenntnisnahme": "Das Gremium wird informiert.",
    "Genehmigung": "Das Gremium genehmigt nachträglich eine Dringlichkeits- oder Eilentscheidung.",
    "Eilentscheidung": "Der Hauptausschuss entscheidet anstelle des Rates, weil die Angelegenheit keinen Aufschub duldet.",
}

SCHRITTE = {
    "initiierung": "Anstoß", "vorbereitung": "Vorbereitung", "veroeffentlichung": "Datum der Vorlage",
    "beratung": "Beratung", "entscheidung": "Entscheidung", "folgevorlage": "Folgevorlage", "vollzug": "Umsetzung",
}

SCHRITTE_TEXT = {
    "initiierung": "Wie das Verfahren angestoßen wurde, etwa durch einen Antrag, eine Anfrage, eine Anregung oder Beschwerde "
                   "nach § 24 GO NRW oder eine Vorlage der Verwaltung.",
    "vorbereitung": "Arbeit der Verwaltung, bevor eine Vorlage erscheint; von außen nicht einsehbar.",
    "veroeffentlichung": "Datum, unter dem die Vorlage im Ratsinformationssystem steht.",
    "beratung": "Ein Gremium berät die Vorlage; das Ergebnis steht wörtlich wie in der Quelle.",
    "entscheidung": "Beratung in dem Gremium, das abschließend entscheidet.",
    "folgevorlage": "Spätere Vorlage zum selben Vorgang, etwa eine Stellungnahme der Verwaltung oder ein Änderungsantrag.",
    "vollzug": "Umsetzung eines Beschlusses durch die Verwaltung; ob und wann sie geschieht, lässt sich aus öffentlichen "
               "Quellen nicht bestimmen.",
}
ROLLEN = ("Entscheidung", "Empfehlung", "Anhörung", "Kenntnisnahme", "Genehmigung", "Eilentscheidung")

EVIDENZ = {  # Wortlaut wie in der Legende der Seite
    "belegt": "Als Datenobjekt in der Quelle vorhanden.",
    "abgeleitet": "Aus Quelldaten erschlossen (z. B. Verknüpfung von Beratung und Sitzung, Titelmuster).",
    "nicht_öffentlich": "Findet regelmäßig statt, ist von außen aber nicht einsehbar.",
    "unklar": "Ob und wann der Schritt stattfindet, lässt sich aus öffentlichen Quellen nicht bestimmen.",
    "soll": "Nach Regelwerk zu erwarten (vereinfachtes Modell aus Gemeindeordnung, Geschäftsordnung, Satzungen, "
            "Zuständigkeitsordnung und Baugesetzbuch), in den Daten nicht dokumentiert. Das heißt nicht, dass der Schritt fehlt.",
}

STAENDE = {
    "entschieden": "Eine entscheidende Beratung hat ein abschließendes Ergebnis.",
    "beraten, ohne Entscheidung": "Alle Beratungen sind abgeschlossen, keine davon war entscheidend "
                                  "(z. B. Mitteilungen, die zur Kenntnis genommen wurden).",
    "in Beratung": "Mindestens eine Beratung hat ein Ergebnis, andere stehen aus oder wurden vertagt.",
    "offen": "Noch keine Beratung mit Ergebnis.",
    "ohne Beratungsfolge": "Für die Vorlage ist keine Beratung in einem Gremium erfasst.",
}

DATENFELD = "Ratsinformationssystem der Stadt Köln (OParl-API)"
ALLGEMEIN = "allgemeine Erklärung"
GESCHO = "Geschäftsordnung des Rates der Stadt Köln"
HAUPTSATZUNG = "Hauptsatzung der Stadt Köln"
GEBIETE = "Kommunale Gebietsgliederung der Stadt Köln (offenedaten-koeln.de)"
# Gruppen der Seite begriffe/ in dieser Reihenfolge (Köln, 04.11.2026: ohne die Bonner Gruppe „Haushalt“ und ohne
# Bonner Kürzel der Drucksachennummer; Vorlagenarten werden nach der Messung der Kölner API ergänzt)
GRUPPEN = [("vorlagen", "Vorlagen und Vorlagenarten"), ("gremium", "Gremien und Beteiligung"),
           ("verfahren", "Verfahren und Sitzungen"), ("gebiete", "Gebiete"), ("kuerzel", "Kürzel"),
           ("planung", "Planung")]
BEGRIFFE = [
    ("Vorlage", "Schriftstück, über das Rat, Bezirksvertretungen oder Ausschüsse beraten, etwa ein Antrag, eine "
                "Beschlussvorlage oder eine Mitteilung der Verwaltung.", DATENFELD + ", Objekt „Paper“"),
    ("Vorlagennummer", "Kennung einer Vorlage, in Köln z. B. 2250/2025 für Vorlagen der Verwaltung und AN/1756/2026 "
                       "für Anträge und Anfragen.", DATENFELD + ", Feld „reference“"),
    ("Beschlussvorlage", "Vorlage der Verwaltung mit einem Beschlussvorschlag, über den ein Gremium entscheidet.",
     ALLGEMEIN),
    ("Mitteilung", "Vorlage, mit der die Verwaltung ein Gremium informiert; ein Beschluss ist nicht vorgesehen.",
     ALLGEMEIN),
    ("Antrag", "Vorlage einer Fraktion, Gruppe oder eines Mitglieds, mit der ein Gremium um einen Beschluss gebeten "
               "wird. In Köln heißen solche Vorlagen „Antrag nach § 3“ der Geschäftsordnung.", GESCHO),
    ("Änderungsantrag", "Antrag, der eine andere Vorlage oder einen anderen Antrag ändern will.", ALLGEMEIN),
    ("Anfrage", "Fragen einer Fraktion, Gruppe oder eines Mitglieds an die Verwaltung; die Verwaltung antwortet "
                "schriftlich oder in der Sitzung. In Köln heißen solche Vorlagen „Anfrage nach § 4“ der "
                "Geschäftsordnung.", GESCHO),
    ("Dringlichkeitsantrag", "Antrag, der ohne die übliche Frist auf die Tagesordnung kommen soll, weil die "
     "Angelegenheit keinen Aufschub duldet; ob er behandelt wird, entscheidet das Gremium.", ALLGEMEIN),
    ("Anregungen und Beschwerden", "Jede Person kann sich schriftlich mit Anregungen oder Beschwerden in "
     "Angelegenheiten der Gemeinde an den Rat wenden, allein oder gemeinsam mit anderen. In Köln berät darüber der "
     "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden. Der Ratsatlas zeigt solche Eingaben höchstens auf "
     "Straßen- oder Stadtteilebene. Nicht zu verwechseln mit dem Einwohnerantrag.", "§ 24 GO NRW; " + HAUPTSATZUNG),
    ("Einwohnerantrag", "Einwohnerinnen und Einwohner können beantragen, dass der Rat über eine bestimmte "
     "Angelegenheit berät und entscheidet. Der Antrag braucht die Unterschriften einer Mindestzahl von "
     "Einwohnerinnen und Einwohnern; Einzelheiten regelt die Gemeindeordnung.", "§ 25 GO NRW"),
    ("Einwohnerfragestunde", "Zeit in einer Sitzung, in der Einwohnerinnen und Einwohner Fragen stellen können; "
                             "Einzelheiten regelt die Geschäftsordnung.", GESCHO),
    ("Rat", "Gewählte Vertretung der Bürgerinnen und Bürger; er ist für alle Angelegenheiten der Gemeinde zuständig, "
            "soweit nichts anderes bestimmt ist.", "§ 41 GO NRW"),
    ("Bezirksvertretung", "Gewählte Vertretung eines Stadtbezirks in kreisfreien Städten. Köln hat neun Stadtbezirke "
     "und damit neun Bezirksvertretungen (Innenstadt, Rodenkirchen, Lindenthal, Ehrenfeld, Nippes, Chorweiler, Porz, "
     "Kalk, Mülheim). Sie entscheidet über Angelegenheiten, deren Bedeutung nicht wesentlich über den Stadtbezirk "
     "hinausgeht.", "§§ 36, 37 GO NRW; " + HAUPTSATZUNG),
    ("Ausschuss", "Vom Rat gebildetes Gremium, das Beschlüsse vorbereitet oder in übertragenen Angelegenheiten "
                  "selbst entscheidet.", "§§ 41, 57 GO NRW"),
    ("Hauptausschuss", "Pflichtausschuss des Rates; er stimmt die Arbeit der Ausschüsse ab und kann in dringenden "
                       "Fällen anstelle des Rates entscheiden.", "§§ 59, 60 GO NRW"),
    ("Dringlichkeitsentscheidung", "Entscheidung in dringenden Fällen ohne Sitzung des zuständigen Gremiums; sie wird "
     "dem Gremium nachträglich zur Genehmigung vorgelegt.", "§ 60 GO NRW (Rat), § 36 GO NRW (Bezirksvertretung)"),
    ("Fraktion", "Zusammenschluss von Mitgliedern des Rates oder einer Bezirksvertretung.", "§ 56 GO NRW"),
    # Ohne Liste der Kölner Gruppen: Gebildete Gruppen sind bis zum Abgleich mit dem Ratsinformationssystem nicht belegt
    # (fraktionen_rat.tsv stützt BSW nur auf das Wahlergebnis).
    ("Gruppe", "Zusammenschluss von Ratsmitgliedern, die zusammen zu wenige Sitze für eine Fraktion haben. Als "
               "Einreichende zeigt der Ratsatlas Fraktionen und Gruppen, meist aus dem Titel der Vorlage abgeleitet.",
     "§ 56 GO NRW"),
    ("Öffentlichkeit von Sitzungen", "Sitzungen des Rates sind grundsätzlich öffentlich; für einzelne Angelegenheiten "
     "kann die Öffentlichkeit ausgeschlossen werden. Inhalte nichtöffentlicher Beratungen sind nicht einsehbar.",
     "§ 48 GO NRW"),
    ("Federführende Dienststelle", "Dezernat und Amt der Verwaltung, die eine Vorlage verantworten; in Köln im Kopf der "
     "Verwaltungsvorlage als „Dezernat, Dienststelle“ angegeben (z. B. „II/II/2“). Dezernat und Bezeichnung ergänzt der "
     "Ratsatlas aus dem Geschäfts- und Dezernatsverteilungsplan der Stadt, wenn der Plan am Datum der Vorlage galt und "
     "die Angabe eindeutig passt (abgeleitet, mit Fundstelle im Plan).",
     DATENFELD + ", Feld „underDirectionOf“ bzw. Kopf der Vorlage; Geschäfts- und Dezernatsverteilungsplan der Stadt "
     "Köln"),
    ("Beratungsfolge", "Reihenfolge der Gremien, die eine Vorlage beraten, jeweils mit Rolle (Entscheidung, Empfehlung, "
                       "Anhörung, Kenntnisnahme).", DATENFELD + ", Objekt „Consultation“"),
    ("Tagesordnungspunkt", "Punkt der Tagesordnung einer Sitzung; über ihn wird beraten und gegebenenfalls "
                           "abgestimmt. Das Ergebnis steht wörtlich wie im Ratsinformationssystem.",
     DATENFELD + ", Objekt „AgendaItem“"),
    ("Stand eines Vorgangs", "Vom Ratsatlas aus der Beratungsfolge abgeleitet: entschieden, beraten ohne "
     "Entscheidung, in Beratung, offen oder ohne Beratungsfolge. Maßgeblich ist das Original.", "abgeleitet (Ratsatlas)"),
    # Gebiete
    ("Stadtteil", "Amtliche Gliederung der Stadt in 86 Stadtteile, z. B. Ehrenfeld oder Rath/Heumar. Im Alltag sagt man "
                  "oft „Veedel“; Veedel und Stadtteil sind nicht immer dasselbe Gebiet.", GEBIETE),
    ("Stadtbezirk", "Die 86 Stadtteile gehören zu neun Stadtbezirken; jeder hat eine Bezirksvertretung. Acht "
                    "Stadtbezirke tragen den Namen eines Stadtteils, etwa Porz oder Kalk.", GEBIETE + "; " + HAUPTSATZUNG),
    ("Verortung", "Zuordnung einer Vorlage zu einem Ort: aus der Ortsangabe der Stadt (Stufe A) oder aus Straßen-, "
                  "Stadtteil- und Bezirksnamen im Titel (Stufe B). Jede Verortung nennt Methode, Konfidenz und "
                  "Fundstelle. Auf ein einzelnes Haus gesetzt werden nur Vorlagen der Verwaltung sowie politische "
                  "Anträge und Anfragen, nie Eingaben von Einwohnerinnen und Einwohnern; ist die Art einer Vorlage nicht erkennbar, "
                  "zeigt die Karte höchstens die Straße.", "abgeleitet (Ratsatlas)"),
    # Kürzel
    ("TOP", "Tagesordnungspunkt einer Sitzung.", ALLGEMEIN),
    ("GO NRW", "Gemeindeordnung für das Land Nordrhein-Westfalen; sie regelt Aufgaben und Arbeit von Rat, Ausschüssen "
               "und Bezirksvertretungen.", "Gemeindeordnung NRW"),
    ("OB", "Oberbürgermeisterin oder Oberbürgermeister; leitet die Verwaltung und führt den Vorsitz im Rat.",
     "§§ 40, 62 GO NRW"),
    ("BV", "Bezirksvertretung.", "§ 36 GO NRW"),
    ("AN", "Vorsilbe der Vorlagennummer bei Anträgen und Anfragen, z. B. AN/1756/2026.",
     DATENFELD + ", Feld „reference“; Bedeutung aus den Vorlagenarten erschlossen"),
    # Planung
    ("Bebauungsplan", "Satzung der Gemeinde, die festlegt, wie Grundstücke in einem Gebiet bebaut und genutzt werden "
     "dürfen.", "§§ 8, 10 BauGB"),
]
# Strukturdaten (nur mit Freigabe „strukturdaten“, config.ZUSATZTHEMEN; Entscheidung 10.11.2026): eigene Gruppe auf der
# Seite begriffe/ und in glossar.json; ohne Freigabe erscheinen Gruppe und Begriffe nicht
GRUPPE_STRUKTURDATEN = ("strukturdaten", "Strukturdaten")
STATISTIK = "Statistischer Datenkatalog Köln (Stadt Köln, Amt für Stadtentwicklung und Statistik)"
BEGRIFFE_STRUKTURDATEN = [
    ("Statistisches Quartier", "Kleinste Raumeinheit der Kölner Stadtstatistik. Köln ist in 570 Statistische "
     "Quartiere gegliedert; jedes liegt in einem Stadtteil. Quartiere dienen der Statistik und sind weder Veedel noch "
     "Verwaltungsbezirke.", STATISTIK + "; Datensatz „Statistische Quartiere Köln“ (offenedaten-koeln.de)"),
    ("Statistische Geheimhaltung", "Damit sich aus Zahlen keine Rückschlüsse auf einzelne Menschen ziehen lassen, "
     "veröffentlicht die Stadt sehr kleine Werte nicht: Werte zwischen 1 und 4 und die zugehörigen Anteile sind mit "
     "„*“ gekennzeichnet. Der Ratsatlas zeigt dort „nicht veröffentlicht (statistische Geheimhaltung)“ und rechnet "
     "solche Werte nicht aus anderen Zahlen nach.", STATISTIK + ", Blatt Info („Geheimhaltung“)"),
    ("Ökologischer Fehlschluss", "Schluss von Merkmalen eines Gebiets auf einzelne Menschen oder auf einen "
     "Zusammenhang. Wenn in einem Stadtteil viele Vorlagen zu einem Thema und zugleich ein hoher Anteil einer "
     "Bevölkerungsgruppe vorkommen, folgt daraus nicht, dass beides zusammenhängt oder dass es auf einzelne "
     "Bewohnerinnen und Bewohner zutrifft.", ALLGEMEIN),
]

GRUPPE = {"Rat": "gremium", "Bezirksvertretung": "gremium", "Ausschuss": "gremium", "Hauptausschuss": "gremium",
          "Fraktion": "gremium", "Gruppe": "gremium", "Anregungen und Beschwerden": "gremium",
          "Einwohnerantrag": "gremium", "Einwohnerfragestunde": "gremium",
          "Dringlichkeitsentscheidung": "verfahren", "Öffentlichkeit von Sitzungen": "verfahren",
          "Federführende Dienststelle": "verfahren", "Beratungsfolge": "verfahren",
          "Tagesordnungspunkt": "verfahren", "Stand eines Vorgangs": "verfahren",
          "Stadtteil": "gebiete", "Stadtbezirk": "gebiete", "Verortung": "gebiete",
          "TOP": "kuerzel", "GO NRW": "kuerzel", "OB": "kuerzel", "BV": "kuerzel", "AN": "kuerzel",
          "Bebauungsplan": "planung"}  # übrige: vorlagen
# Vorlagenart in den Daten → Begriff. Köln: vorläufig nach den aus der Oberfläche belegten Arten (Recherche
# 04.11.2026); vollständige Liste nach der Messung der API (explore/oparl_messung.py)
ARTEN = {
    "Beschlussvorlage": "Beschlussvorlage", "Beschlussvorlage Rat": "Beschlussvorlage",
    "Beschlussvorlage Ausschuss": "Beschlussvorlage", "Mitteilung": "Mitteilung", "Mitteilung Ausschuss": "Mitteilung",
    "Antrag nach § 3 der Geschäftsordnung des Rates": "Antrag", "Antrag nach § 3": "Antrag",
    "Anfrage nach § 4 der Geschäftsordnung des Rates": "Anfrage", "Anfrage nach § 4": "Anfrage",
    "Änderungsantrag": "Änderungsantrag", "Dringlichkeitsantrag": "Dringlichkeitsantrag",
    "Anregungen und Beschwerden": "Anregungen und Beschwerden",
}
KUERZEL = {}

def anker(begriff):
    """Sprungmarke auf begriffe/: „Stellungnahme der Verwaltung“ → „stellungnahme-der-verwaltung“."""
    s = begriff.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _strukturdaten():
    return bool(config.ZUSATZTHEMEN.get("strukturdaten"))


def gruppen():
    """Gruppen der Seite begriffe/ in ihrer Reihenfolge; die Strukturdaten nur mit Freigabe."""
    return GRUPPEN + ([GRUPPE_STRUKTURDATEN] if _strukturdaten() else [])


def begriffe():
    """(Begriff, Erklärung, Fundstelle, Gruppe) aller Begriffe; die Strukturdaten nur mit Freigabe."""
    return ([(b, e, f, GRUPPE.get(b, "vorlagen")) for b, e, f in BEGRIFFE]
            + ([(b, e, f, GRUPPE_STRUKTURDATEN[0]) for b, e, f in BEGRIFFE_STRUKTURDATEN] if _strukturdaten() else []))


def glossar():
    return {
        "meta": {"note": "Allgemeine Erklärungen ohne Rechtsberatung; Fundstelle je Begriff. Ergebnistexte erscheinen "
                         "wörtlich wie in den Quellen."},
        "ergebnisse": ERGEBNISSE,
        "hinweise": proc.NOTES,
        "schritte": SCHRITTE,
        "evidenz": EVIDENZ,
        "staende": STAENDE,
        "themen": dict(topics.THEMES),
        "begriffe": [{"begriff": b, "erklaerung": e, "fundstelle": f, "gruppe": g, "anker": anker(b)}
                     for b, e, f, g in begriffe()],
        "gruppen": dict(gruppen()),
        "arten": {art: anker(b) for art, b in ARTEN.items()},
        "kuerzel": {k: anker(b) for k, b in KUERZEL.items()},
    }
