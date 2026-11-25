"""Wege zum Mitwirken auf den Themenseiten (Abschnitt „Mitwirken“ und Karte „Frage oder Anregung einreichen“).

Kölner Texte, zusammengefasst nach der Fläche „Mitmachen in Köln“ (site/beteiligung.js, Quellen am 13.11.2026 geprüft;
TECHNIK.md, „Mitmachen in Köln“): Gemeindeordnung NRW (Fassung ab 01.01.2026) und Geschäftsordnung des Rates und der
Bezirksvertretungen der Stadt Köln vom 19.03.2026. Fristen stehen als Regel da, ohne berechnetes Datum (Arbeitstage
hängen von Feiertagen ab). Adressen nur aus QUELLEN, gleich den Einträgen in site/beteiligung.js
(tests/test_themenseiten_koeln.py vergleicht beide). Die Seite der Stadt zur
Einwohnerfragestunde ist nicht verlinkt: Sie beschreibt noch die Geschäftsordnung von 2020 (beteiligung.js,
FRAGESTUNDE_HINWEIS); maßgeblich ist die verlinkte Geschäftsordnung.
"""
from html import escape

STADT = "Seite der Stadt Köln"
# Schlüssel wie in site/beteiligung.js QUELLEN: (Beschriftung, Anbieter für Screenreader, Adresse)
QUELLEN = {
    "ausschuss": ("Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden", STADT,
                  "https://www.stadt-koeln.de/politik-und-verwaltung/mitwirkung-von-buergerinnen/anregungenbeschwerden"),
    "geschaeftsstelle": ("Geschäftsstelle für Anregungen und Beschwerden", STADT,
                         "https://www.stadt-koeln.de/service/adressen/geschaeftsstelle-fuer-anregungen-und-beschwerden-rat-und-bez"),
    "einwohnerantrag": ("Einwohnerantrag", STADT,
                        "https://www.stadt-koeln.de/politik-und-verwaltung/mitwirkung-von-buergerinnen/einwohnerantrag"),
    "ratLive": ("Ratssitzung online", STADT, "https://www.stadt-koeln.de/rat-live/"),
    "gescho": ("Geschäftsordnung des Rates und der Bezirksvertretungen (19.03.2026, PDF)", STADT,
               "https://www.stadt-koeln.de/mediaasset/content/satzungen/geschaeftsordnung-rat-und-bezirksvertretungen_20260319.pdf"),
    "go": ("Gemeindeordnung NRW", "recht.nrw.de",
           "https://recht.nrw.de/lrgv/gesetz/01012026-gemeindeordnung-fuer-das-land-nordrhein-westfalen-bekanntmachung-der/"),
}
STAND = "13.11.2026"   # Stand der Quellen, wie site/beteiligung.js


def link(key, klasse=None):
    """Link auf eine Seite aus QUELLEN, im neuen Tab, mit Anbieter für Screenreader."""
    label, wo, url = QUELLEN[key]
    k = f' class="{klasse}"' if klasse else ""
    return (f'<a{k} href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}'
            f'<span class="visually-hidden"> ({escape(wo)}, neuer Tab)</span></a>')


def abschnitt(root):
    """Abschnitt „Mitwirken“ der Themenseite (h2#mitwirken)."""
    return f"""    <h2 id="mitwirken">Mitwirken</h2>
    <ul>
      <li><strong>Zuhören und zuschauen:</strong> Die Sitzungen des Rates, der Ausschüsse und der Bezirksvertretungen sind öffentlich; einzelne Punkte werden nichtöffentlich beraten (§ 48 Abs. 2, § 36 Abs. 5 und § 58 Abs. 2 GO NRW; § 2 Abs. 4 der Geschäftsordnung). Ratssitzungen überträgt die Stadt live im Internet: {link("ratLive")}.</li>
      <li><strong>Einwohnerfragestunde:</strong> Jede Sitzung einer Bezirksvertretung beginnt mit der Einwohnerfragestunde. Wer im Stadtbezirk wohnt, kann eine Frage mit höchstens fünf Unterfragen stellen, schriftlich spätestens am fünften Arbeitstag vor der Sitzung bis 12 Uhr; die Verwaltung antwortet schriftlich (§ 39 der Geschäftsordnung: {link("gescho")}).</li>
      <li><strong>Anregungen und Beschwerden (§ 24 GO NRW):</strong> Wer seit mindestens drei Monaten in Köln wohnt, kann sich in Textform, etwa per Brief oder E-Mail, an den Rat oder an eine Bezirksvertretung wenden. Die Eingaben bearbeitet die {link("geschaeftsstelle")}; beraten werden sie im {link("ausschuss")} oder in der zuständigen Bezirksvertretung.</li>
      <li><strong>Einwohnerantrag (§ 25 GO NRW):</strong> Einwohnerinnen und Einwohner ab 14 Jahren können verlangen, dass der Rat oder die zuständige Bezirksvertretung über ein Anliegen berät und entscheidet: {link("einwohnerantrag")}.</li>
      <li><a href="{root}?mitmachen=1">Alle Wege und die nächsten Sitzungen je Stadtbezirk: Mitmachen in Köln</a></li>
    </ul>
    <p class="meta">Zusammengefasst aus der Gemeindeordnung NRW ({link("go")}) und der Geschäftsordnung des Rates und der Bezirksvertretungen der Stadt Köln vom 19.03.2026, Stand {STAND}. Keine Rechtsauskunft; maßgeblich sind Gesetz, Geschäftsordnung und die Angaben der Stadt.</p>
"""


# Karte „Frage oder Anregung einreichen“ im Abschnitt „Auf einen Blick“ (prozessbild.aufrufe)
KARTE_TITEL = "Frage oder Anregung einreichen"
KARTE_TEXT = ("Eine Frage in der Einwohnerfragestunde einer Bezirksvertretung (§ 39 der Geschäftsordnung) oder eine "
              "Anregung oder Beschwerde an Rat oder Bezirksvertretung (§ 24 GO NRW).")


def karte_aktionen(root):
    return (link("geschaeftsstelle", "pb-knopf")
            + f' <a class="pb-knopf pb-knopf-leise" href="{root}?mitmachen=1">Alle Wege</a>')
