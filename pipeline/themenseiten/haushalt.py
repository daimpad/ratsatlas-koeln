"""Haushalt 2027/2028 für alle Themenseiten: Phasen laut Terminplan in Mitteilungsvorlage 261064 (geplant,
abgeleitet) und der Weg des Haushalts, zusammengefasst aus 261064 und ihrer Anlage, selbst formuliert, ohne
Zitate (Rahmen der Stadt Bonn vom 19.10.2026). Jeder Fachausschuss berät den Entwurf einmal."""

TERMINPLAN = "261064"
BAHN = ("plan", "Haushalt 2027/2028")
TEXT = ("Der Haushalt 2027/2028 wird laut Terminplan von Oktober bis Dezember 2026 beraten und im Dezember "
        "im Rat beschlossen.")
FENSTER = "Zeitraum der Haushaltsberatung"
TITEL = "So entsteht der Haushalt 2027/2028"


def phasen(fachbahn):
    """Oben der Ablauf im Ganzen, darunter die Gremien (Bahn, von, bis, Beschriftung, nicht öffentlich);
    fachbahn: die Bahn des Fachausschusses des Themas."""
    return [("plan", "2026-02-27", "2026-09-30", "Aufstellung in der Verwaltung", True),
            ("plan", "2026-10-01", "2026-11-30", "Einbringung, Beratung", False),
            ("plan", "2026-12-01", "2026-12-31", "Beschluss", False),
            ("plan", "2027-01-01", "2027-03-31", "Genehmigung", False),
            ("bv", "2026-10-01", "2026-11-30", "Beratung des Haushalts", False),
            (fachbahn, "2026-10-01", "2026-11-30", "Beratung des Haushalts", False),
            ("fach", "2026-10-01", "2026-11-30", "Beratung des Haushalts", False),
            ("finanz", "2026-11-01", "2026-11-30", "Vorberatung für den Rat", False),
            ("rat", "2026-10-01", "2026-11-15", "Einbringung des Entwurfs", False),
            ("rat", "2026-12-01", "2026-12-31", "Beschluss der Haushaltssatzung", False)]


def schritte(fachgremium):
    """fachgremium: „für die Kultur der Kulturausschuss“ o. Ä."""
    return [
        ("Aufstellung in der Verwaltung", "Frühjahr und Sommer 2026",
         "Die Ämter melden ihren Bedarf im Rahmen von Eckwerten je Amt und Dezernat; Mehrbedarf ist innerhalb des "
         "Dezernats auszugleichen. Der Verwaltungsvorstand bespricht Härtefälle. Dieser Teil ist nicht öffentlich."),
        ("Einbringung des Entwurfs", "Herbst 2026",
         "Die Verwaltung legt dem Rat den Entwurf des Haushaltsplans vor; die Mitglieder der Ausschüsse erhalten die Unterlagen."),
        ("Beratung in den Fachausschüssen und Bezirksvertretungen", "Oktober und November 2026",
         f"Jedes Fachgremium berät den Entwurf einmal, {fachgremium}. Fraktionen können Änderungsanträge stellen."),
        ("Ausschuss für Finanzen, Beteiligungen und Vergabe", "November 2026",
         "Er tagt nach den Fachgremien und bereitet den Beschluss des Rates vor."),
        ("Beschluss im Rat", "Dezember 2026",
         "Etwa zwei Wochen nach dem Finanzausschuss beschließt der Rat die Haushaltssatzung."),
        ("Kommunalaufsicht", "Anfang 2027",
         "Die Satzung geht an die Bezirksregierung Köln; die Genehmigung erwartet die Verwaltung im ersten Quartal 2027."),
    ]
