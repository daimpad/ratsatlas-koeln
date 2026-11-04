"""Glossar für Seite und Ratsassistent (data/export/glossar.json, eine Quelle für beide).

- ergebnisse: Ergebnistexte und Rollen der Beratung, wie sie wörtlich in den Quellen stehen
- hinweise: Erläuterungen zu Prozessschritten (Schlüssel `note` in den Exporten, process.NOTES)
- schritte, evidenz, staende: Bezeichnungen der Prozessebene (process.py)
- themen: Bezeichnungen der abgeleiteten Themen (topics.py)
- begriffe: allgemeine Begriffe mit Fundstelle (Gemeindeordnung NRW bzw. Datenfeld), je mit Gruppe und Sprungmarke
  für die Seite begriffe/; allgemeine Erklärungen, keine Rechtsberatung
- arten, kuerzel: Vorlagenart bzw. Kürzel der Drucksachennummer → Sprungmarke des Begriffs (Erklärung im Vorgang)

Ergänzt am 02.11.2026 (Phase 0 „Verständlichkeit“, Entscheidungen des Auftraggebers): alle Vorlagenarten der Daten,
Kürzel, Haushalt und Bebauungsplan; einfachere Wörter für eigene Bezeichnungen der Seite („Anstoß“ statt
„Initiierung“, „Umsetzung“ statt „Vollzug“). Wo eine Vorlagenart in keinem Regelwerk beschrieben ist, ist die
Erklärung aus Titeln und Beratungsfolge erschlossen und so gekennzeichnet."""
import re

from . import process as proc, topics

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
    "initiierung": "Wie das Verfahren angestoßen wurde, etwa durch einen Antrag, eine Anfrage, einen Bürgerantrag oder eine "
                   "Vorlage der Verwaltung.",
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
    "abgeleitet": "Aus Quelldaten erschlossen (z. B. Verknüpfung mit OParl-Lite, Titelmuster).",
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

DATENFELD = "Ratsinformationssystem der Stadt Bonn (OParl-API)"
ALLGEMEIN = "allgemeine Erklärung"
ERSCHLOSSEN = "Vorlagenart im Ratsinformationssystem der Stadt Bonn; Erklärung aus Titeln und Beratungsfolge erschlossen"
GESCHO = "Geschäftsordnung des Rates der Stadt Bonn"
HAUSHALT = "Haushaltspläne der Stadt Bonn"
# Gruppen der Seite begriffe/ in dieser Reihenfolge
GRUPPEN = [("vorlagen", "Vorlagen und Vorlagenarten"), ("gremium", "Gremien und Beteiligung"),
           ("verfahren", "Verfahren und Sitzungen"), ("kuerzel", "Kürzel"), ("haushalt", "Haushalt"),
           ("planung", "Planung")]
BEGRIFFE = [
    ("Vorlage", "Schriftstück, über das Rat, Bezirksvertretungen oder Ausschüsse beraten, etwa ein Antrag, eine "
                "Beschlussvorlage oder ein Bürgerantrag.", DATENFELD + ", Objekt „Paper“"),
    ("Drucksachennummer", "Kennung einer Vorlage, z. B. 261798. Zusätze wie „-01“ kennzeichnen zugehörige "
                          "Folgevorlagen.", DATENFELD + ", Feld „reference“"),
    ("Beschlussvorlage", "Vorlage der Verwaltung mit einem Beschlussvorschlag, über den ein Gremium entscheidet.",
     ALLGEMEIN),
    ("Mitteilungsvorlage", "Vorlage, mit der die Verwaltung ein Gremium informiert; ein Beschluss ist nicht vorgesehen.",
     ALLGEMEIN),
    ("Antrag", "Vorlage einer Fraktion, Gruppe oder eines Mitglieds, mit der ein Gremium um einen Beschluss gebeten "
               "wird.", ALLGEMEIN),
    ("Änderungsantrag", "Antrag, der eine andere Vorlage oder einen anderen Antrag ändern will.", ALLGEMEIN),
    ("Stellungnahme der Verwaltung", "Schriftliche Antwort der Verwaltung, meist auf einen Antrag oder eine Anfrage.",
     ALLGEMEIN),
    ("Anfrage", "Fragen einer Fraktion oder eines Mitglieds an die Verwaltung (Kleine oder Große Anfrage); die "
                "Verwaltung antwortet schriftlich oder in der Sitzung.", ALLGEMEIN),
    ("Anregungen und Beschwerden (Bürgerantrag)", "Jede Person kann sich schriftlich mit Anregungen oder Beschwerden "
     "in Angelegenheiten der Gemeinde an den Rat oder die Bezirksvertretung wenden, allein oder gemeinsam mit "
     "anderen. Unterschriften weiterer Personen sind dafür nicht nötig. Nicht zu verwechseln mit dem "
     "Einwohnerantrag.", "§ 24 GO NRW"),
    ("Einwohnerantrag", "Einwohnerinnen und Einwohner können beantragen, dass der Rat über eine bestimmte "
     "Angelegenheit berät und entscheidet. Der Antrag braucht die Unterschriften einer Mindestzahl von "
     "Einwohnerinnen und Einwohnern; Einzelheiten regelt die Gemeindeordnung. Nicht zu verwechseln mit dem "
     "Bürgerantrag (Anregungen und Beschwerden).", "§ 25 GO NRW"),
    ("Einwohnerfragestunde", "Zeit in einer Sitzung, in der Einwohnerinnen und Einwohner Fragen stellen können; "
                             "Einzelheiten regelt die Geschäftsordnung.", "Geschäftsordnung des Rates der Stadt Bonn"),
    ("Rat", "Gewählte Vertretung der Bürgerinnen und Bürger; er ist für alle Angelegenheiten der Gemeinde zuständig, "
            "soweit nichts anderes bestimmt ist.", "§ 41 GO NRW"),
    ("Bezirksvertretung", "Gewählte Vertretung eines Stadtbezirks in kreisfreien Städten; Bonn hat vier "
     "(Bonn, Bad Godesberg, Beuel, Hardtberg). Sie entscheidet über Angelegenheiten, deren Bedeutung nicht "
     "wesentlich über den Stadtbezirk hinausgeht.", "§§ 36, 37 GO NRW"),
    ("Ausschuss", "Vom Rat gebildetes Gremium, das Beschlüsse vorbereitet oder in übertragenen Angelegenheiten "
                  "selbst entscheidet.", "§§ 41, 57 GO NRW"),
    ("Hauptausschuss", "Pflichtausschuss des Rates; er stimmt die Arbeit der Ausschüsse ab und kann in dringenden "
                       "Fällen anstelle des Rates entscheiden.", "§§ 59, 60 GO NRW"),
    ("Dringlichkeitsentscheidung", "Entscheidung in dringenden Fällen ohne Sitzung des zuständigen Gremiums; sie wird "
     "dem Gremium nachträglich zur Genehmigung vorgelegt.", "§ 60 GO NRW (Rat), § 36 GO NRW (Bezirksvertretung)"),
    ("Fraktion", "Zusammenschluss von Mitgliedern des Rates oder einer Bezirksvertretung.", "§ 56 GO NRW"),
    ("Öffentlichkeit von Sitzungen", "Sitzungen des Rates sind grundsätzlich öffentlich; für einzelne Angelegenheiten "
     "kann die Öffentlichkeit ausgeschlossen werden. Inhalte nichtöffentlicher Beratungen sind nicht einsehbar.",
     "§ 48 GO NRW"),
    ("Federführendes Amt", "Amt der Verwaltung, das eine Vorlage verantwortet.", DATENFELD + ", Feld „underDirectionOf“"),
    ("Beratungsfolge", "Reihenfolge der Gremien, die eine Vorlage beraten, jeweils mit Rolle (Entscheidung, Empfehlung, "
                       "Anhörung, Kenntnisnahme).", DATENFELD + ", Objekt „Consultation“"),
    ("Tagesordnungspunkt", "Punkt der Tagesordnung einer Sitzung; über ihn wird beraten und gegebenenfalls "
                           "abgestimmt. Das Ergebnis stammt aus OParl-Lite.", DATENFELD + ", Objekt „AgendaItem“"),
    # ergänzt 02.11.2026: Vorlagenarten ohne eigenen Eintrag
    ("Dringlichkeitsantrag", "Antrag, der ohne die übliche Frist auf die Tagesordnung kommen soll, weil die "
     "Angelegenheit keinen Aufschub duldet; ob er behandelt wird, entscheidet das Gremium.", GESCHO),
    ("Informationsbrief", "Schreiben der Verwaltung, mit dem sie Rat, Hauptausschuss oder Bezirksvertretungen über "
     "ein Vorhaben informiert, etwa eine Baumaßnahme; die Gremien nehmen es zur Kenntnis.", ERSCHLOSSEN),
    ("Bürgerbrief", "Schreiben der Verwaltung, das sich laut den Titeln an Anwohnerinnen und Anwohner richtet, etwa zu "
     "einer Baumaßnahme oder einer Bürgerbeteiligung; die Gremien nehmen es zur Kenntnis.", ERSCHLOSSEN),
    ("Einwohnerfrage", "Frage einer Einwohnerin oder eines Einwohners für die Einwohnerfragestunde; in den Daten meist "
     "an eine Bezirksvertretung gerichtet.", GESCHO),
    ("Tagesordnungspunkte in nichtöffentlicher Sitzung", "Sammelvorlage mit den Punkten einer Sitzung, die ohne "
     "Öffentlichkeit beraten werden; ihr Inhalt ist nicht einsehbar.", "§ 48 GO NRW"),
    ("Beschlussvorlage: Einleitung", "Beschlussvorlage, mit der die Verwaltung ein Verfahren einleiten will, laut den "
     "Titeln meist ein Vergabeverfahren (Ausschreibung).", ERSCHLOSSEN),
    ("Beschlussvorlage: Auftrag", "Beschlussvorlage, die laut den Titeln auf einen Antrag oder Auftrag eines Gremiums "
     "zurückgeht.", ERSCHLOSSEN),
    ("Eilentscheidung (Hauptausschuss)", "Entscheidung des Hauptausschusses anstelle des Rates in einer Angelegenheit, "
     "die keinen Aufschub duldet; der Rat genehmigt sie nachträglich.", "§ 60 Abs. 1 GO NRW"),
    ("Stand eines Vorgangs", "Vom Ratsatlas aus der Beratungsfolge abgeleitet: entschieden, beraten ohne "
     "Entscheidung, in Beratung, offen oder ohne Beratungsfolge. Maßgeblich ist das Original.", "abgeleitet (Ratsatlas)"),
    # Kürzel
    ("ST", "Kürzel an der Drucksachennummer: Stellungnahme der Verwaltung zu der Vorlage mit derselben Nummer davor, "
     "z. B. 261088-01 ST zu 261088.", DATENFELD + ", Feld „reference“; Bedeutung aus der Vorlagenart erschlossen"),
    ("AA", "Kürzel an der Drucksachennummer: Änderungsantrag zu der Vorlage mit derselben Nummer davor.",
     DATENFELD + ", Feld „reference“; Bedeutung aus der Vorlagenart erschlossen"),
    ("DA", "Kürzel an der Drucksachennummer: Dringlichkeitsantrag zu der Vorlage mit derselben Nummer davor.",
     DATENFELD + ", Feld „reference“; Bedeutung aus der Vorlagenart erschlossen"),
    ("TOP", "Tagesordnungspunkt einer Sitzung.", ALLGEMEIN),
    ("GO NRW", "Gemeindeordnung für das Land Nordrhein-Westfalen; sie regelt Aufgaben und Arbeit von Rat, Ausschüssen "
               "und Bezirksvertretungen.", "Gemeindeordnung NRW"),
    ("OB", "Oberbürgermeisterin oder Oberbürgermeister; leitet die Verwaltung und führt den Vorsitz im Rat.",
     "§§ 40, 62 GO NRW"),
    ("BV", "Bezirksvertretung.", "§ 36 GO NRW"),
    ("HA", "Hauptausschuss.", "§ 59 GO NRW"),
    # Haushalt und Planung
    ("Produktbereich", "Gliederung des Haushalts nach Aufgaben; Bonn hat 17 Produktbereiche, z. B. 06 Kinder-, "
     "Jugend- und Familienhilfe. Darunter stehen Produktgruppen.", HAUSHALT),
    ("Ansatz", "Betrag, den der Haushaltsplan für ein Jahr vorsieht (Plan). Was tatsächlich anfällt, heißt Ist.",
     HAUSHALT),
    ("Ordentliche Aufwendungen", "Laufende Aufwendungen eines Jahres ohne Investitionen, etwa für Personal, "
     "Sachaufwand und Transferleistungen.", HAUSHALT + ", Teilergebnispläne Zeile 17"),
    ("Bebauungsplan", "Satzung der Gemeinde, die festlegt, wie Grundstücke in einem Gebiet bebaut und genutzt werden "
     "dürfen.", "§§ 8, 10 BauGB"),
]
GRUPPE = {"Rat": "gremium", "Bezirksvertretung": "gremium", "Ausschuss": "gremium", "Hauptausschuss": "gremium",
          "Fraktion": "gremium", "Anregungen und Beschwerden (Bürgerantrag)": "gremium", "Einwohnerantrag": "gremium",
          "Einwohnerfragestunde": "gremium", "Einwohnerfrage": "gremium",
          "Dringlichkeitsentscheidung": "verfahren", "Eilentscheidung (Hauptausschuss)": "verfahren",
          "Öffentlichkeit von Sitzungen": "verfahren", "Federführendes Amt": "verfahren", "Beratungsfolge": "verfahren",
          "Tagesordnungspunkt": "verfahren", "Stand eines Vorgangs": "verfahren",
          "ST": "kuerzel", "AA": "kuerzel", "DA": "kuerzel", "TOP": "kuerzel", "GO NRW": "kuerzel", "OB": "kuerzel",
          "BV": "kuerzel", "HA": "kuerzel",
          "Produktbereich": "haushalt", "Ansatz": "haushalt", "Ordentliche Aufwendungen": "haushalt",
          "Bebauungsplan": "planung"}  # übrige: vorlagen
# Vorlagenart in den Daten → Begriff (alle Arten, Prüfung in tests/test_chat.py)
ARTEN = {
    "Stellungnahme der Verwaltung": "Stellungnahme der Verwaltung", "Beschlussvorlage": "Beschlussvorlage",
    "Mitteilungsvorlage": "Mitteilungsvorlage", "Änderungsantrag": "Änderungsantrag", "Antrag": "Antrag",
    "Große Anfrage": "Anfrage", "Kleine Anfrage": "Anfrage",
    "Bürgerantrag § 24 GO - Öffentlich": "Anregungen und Beschwerden (Bürgerantrag)",
    "Anregungen und Beschwerden": "Anregungen und Beschwerden (Bürgerantrag)",
    "Tagesordnungspunkte in nichtöffentlicher Sitzung": "Tagesordnungspunkte in nichtöffentlicher Sitzung",
    "Beschlussvorlage: Einleitung": "Beschlussvorlage: Einleitung", "Beschlussvorlage: Auftrag": "Beschlussvorlage: Auftrag",
    "Dringlichkeitsantrag": "Dringlichkeitsantrag", "Informationsbrief": "Informationsbrief", "Bürgerbrief": "Bürgerbrief",
    "Einwohnerfrage": "Einwohnerfrage", "Dringlichkeitsentscheidung OB": "Dringlichkeitsentscheidung",
    "Dringlichkeitsentscheidung BV": "Dringlichkeitsentscheidung", "Eilentscheidung HA": "Eilentscheidung (Hauptausschuss)",
}
KUERZEL = {"ST": "ST", "AA": "AA", "DA": "DA"}


def anker(begriff):
    """Sprungmarke auf begriffe/: „Stellungnahme der Verwaltung“ → „stellungnahme-der-verwaltung“."""
    s = begriff.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


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
        "begriffe": [{"begriff": b, "erklaerung": e, "fundstelle": f, "gruppe": GRUPPE.get(b, "vorlagen"), "anker": anker(b)}
                     for b, e, f in BEGRIFFE],
        "gruppen": dict(GRUPPEN),
        "arten": {art: anker(b) for art, b in ARTEN.items()},
        "kuerzel": {k: anker(b) for k, b in KUERZEL.items()},
    }
