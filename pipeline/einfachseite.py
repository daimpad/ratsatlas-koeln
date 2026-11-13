"""Seite einfach/: Der Ratsatlas Köln in Einfacher Sprache (aus Bonn übernommen, Entscheidungen 02.11.2026; für Köln neu
geschrieben am 13.11.2026, Freigabe „einfache_sprache“ in config.ZUSATZTHEMEN).

Einfache Sprache, nicht Leichte Sprache: keine Prüfgruppe. Kurze Sätze, ein Gedanke je Satz, Fachwörter werden beim
ersten Vorkommen erklärt, keine Abkürzungen im Fließtext (nur in den Zeilen „Für Fachleute“). Jede Aussage zu Rechten
und Abläufen trägt eine Zeile „Für Fachleute“ mit Fundstelle. Die Erklärungen der Wörter sagen dasselbe wie das Glossar
(pipeline/glossar.py), nur einfacher; jedes Wort mit Eintrag im Glossar verweist auf die Seite begriffe/ (Prüfung in
tests/test_einfachseite.py). Keine Bewertung von Politik, Parteien oder Entscheidungen; keine Zusagen zum Erfolg einer
Eingabe. Keine Erzeugungszeitpunkte (stabile Ausgabe).

Quellen der Angaben: Stadtbezirke (Namen, Reihenfolge nach Nummer) und Zahl der Stadtteile aus data/geo; Gremien,
Begriffe und Fundstellen aus dem Glossar; Bedienung, Verlässlichkeit, Datenstand und Datenschutz wie in site/index.html
(Dialog „Über den Ratsatlas Köln“), site/datenschutz.html und README.md. Was dort nicht belegt ist, steht hier nicht
oder ist als offen gekennzeichnet (Link zur Seite der Stadt über Anregungen und Beschwerden: noch nicht geprüft, wie in
site/app.js). Sätze zu abgeschalteten Zusatzthemen (Kurzfassungen, Ebenen ohne „kontext“) nur mit deren Freigabe; in
der Kartenvorschau ohne Ratsvorlagen (index.json meta.vorschau) steht oben ein Hinweis."""
import json
from html import escape

from . import config, glossar

PFAD = "einfach/"
TITEL = "Der Ratsatlas Köln in Einfacher Sprache"

# (Wort, Erklärung, Begriff im Glossar oder None) – gleicher Sinn wie im Glossar; der Begriff ergibt die Sprungmarke auf
# begriffe/ (glossar.anker); Ergebnisse und der Stand stehen dort unter ihren eigenen Sprungmarken
WOERTER = [
    ("Vorlage", "Ein Schreiben, über das ein Gremium berät.", "Vorlage"),
    ("Vorlagennummer", "Die Nummer einer Vorlage. Mit dieser Nummer finden Sie die Vorlage wieder. Vorlagen der "
                       "Verwaltung haben Nummern wie 2250/2025. Anträge und Anfragen haben Nummern wie AN/1756/2026.",
     "Vorlagennummer"),
    ("Gremium", "Eine Gruppe, die berät und entscheidet. Zum Beispiel der Rat, ein Ausschuss oder eine "
                "Bezirksvertretung.", None),
    ("Beschlussvorlage", "Die Verwaltung schlägt etwas vor. Das Gremium soll darüber entscheiden.", "Beschlussvorlage"),
    ("Mitteilung", "Die Verwaltung informiert das Gremium. Eine Entscheidung ist nicht vorgesehen.", "Mitteilung"),
    ("Antrag", "Eine Fraktion, eine Gruppe oder ein Mitglied bittet das Gremium, etwas zu beschließen. In Köln heißt "
               "das oft „Antrag nach § 3“.", "Antrag"),
    ("Anfrage", "Eine Fraktion, eine Gruppe oder ein Mitglied stellt der Verwaltung Fragen. Die Verwaltung antwortet. "
                "In Köln heißt das oft „Anfrage nach § 4“.", "Anfrage"),
    ("§ (Paragraf)", "Eine Regel in einem Gesetz oder in einer Ordnung. „§ 3“ heißt: Regel Nummer 3.", None),
    ("Anregungen und Beschwerden", "Jede Person kann sich schriftlich mit einer Anregung oder einer Beschwerde an den "
                                   "Rat wenden. In Köln berät darüber ein eigener Ausschuss.",
     "Anregungen und Beschwerden"),
    ("Fraktion", "Mitglieder im Rat oder in einer Bezirksvertretung, die sich zu einer Gruppe zusammenschließen.",
     "Fraktion"),
    ("Gruppe", "Einige Mitglieder im Rat schließen sich zusammen. Sie sind aber zu wenige für eine Fraktion. Dann "
               "heißen sie Gruppe.", "Gruppe"),
    ("Beratungsfolge", "Die Reihenfolge der Gremien, die über eine Vorlage beraten.", "Beratungsfolge"),
    ("beschlossen", "Das Gremium hat zugestimmt. Manchmal mit Änderungen.", None),
    ("abgelehnt", "Die Mehrheit im Gremium hat dagegen gestimmt.", "abgelehnt"),
    ("zur Kenntnis genommen", "Das Gremium wurde informiert. Es gab keine Abstimmung über einen Beschluss. Das heißt "
                              "nicht „abgelehnt“.", "zur Kenntnis genommen"),
    ("vertagt", "Die Beratung ist verschoben, auf eine spätere Sitzung.", "vertagt"),
    ("Stand", "Die Karte zeigt, wie weit eine Vorlage ist. Zum Beispiel „entschieden“ oder „in Beratung“. Den Stand "
              "leitet der Ratsatlas aus den Beratungen ab.", "Stand eines Vorgangs"),
]


def sprungmarke(begriff):
    """Sprungmarke eines Worts auf begriffe/ (Begriff, Ergebnis oder None)."""
    return glossar.anker(begriff) if begriff else None


def stadtbezirke():
    """Namen der Stadtbezirke nach ihrer Nummer und Zahl der Stadtteile, aus data/geo."""
    bezirke = json.loads(config.STADTBEZIRKE.read_text(encoding="utf-8"))["features"]
    teile = json.loads(config.ORTSTEILE.read_text(encoding="utf-8"))["features"]
    namen = [f["properties"]["bezirk_bez"] for f in sorted(bezirke, key=lambda f: int(f["properties"]["bezirk"]))]
    return namen, len(teile)


def _aufzaehlung(namen):
    return namen[0] if len(namen) < 2 else ", ".join(namen[:-1]) + " und " + namen[-1]


def _fach(text):
    return f'    <p class="einfach-fach"><strong>Für Fachleute:</strong> {text}</p>'


def _woerter(root):
    zeilen = []
    for wort, text, begriff in WOERTER:
        marke = sprungmarke(begriff)
        dt = f'<a href="{root}begriffe/#{marke}">{escape(wort)}</a>' if marke else escape(wort)
        zeilen.append(f"      <dt>{dt}</dt><dd>{escape(text)}</dd>")
    return "\n".join(zeilen)


def body(root, vorschau=False):
    an = config.ZUSATZTHEMEN.get
    bezirke, n_teile = stadtbezirke()
    n_bezirke = len(bezirke)
    quelle = escape(config.NAMENSNENNUNG)
    hinweis = ("""    <p><strong>Vorschau:</strong> Auf der Karte fehlen noch die Vorlagen der Stadt Köln. Sie kommen, sobald der Abruf eingerichtet ist. Bis dahin zeigt die Karte die Stadtteile und andere offene Daten.</p>
""" if vorschau else "")
    ebenen = ("""      <li>Im Menü „Ebenen“ gibt es noch mehr Daten. Zum Beispiel Schulen, Haltestellen oder Gebiete, die bei Hochwasser überschwemmt werden können. Diese Daten kommen nicht aus dem Ratsinformationssystem. Jede Ebene nennt ihre Quelle.</li>
""" if an("kontext") else "")
    kurz = ("""      <li>Manche Vorlagen haben eine kurze Zusammenfassung. Ein Computerprogramm hat sie geschrieben. Einzelheiten können ungenau sein.</li>
""" if an("kurzfassungen") else "")
    return f"""    <h1>{TITEL}</h1>
    <p class="lead">Auf dieser Seite erklären wir den Ratsatlas Köln in Einfacher Sprache. Sie erfahren: Was zeigt die Karte? Wer entscheidet in Köln? Und wie können Sie mitmachen?</p>
{hinweis}    <nav class="thema-sprung" aria-label="Auf dieser Seite"><span>Auf dieser Seite:</span> <a href="#was">Was ist der Ratsatlas?</a> · <a href="#wer">Wer entscheidet?</a> · <a href="#ablauf">Wie läuft eine Sache ab?</a> · <a href="#woerter">Was bedeuten die Wörter?</a> · <a href="#finden">Wie finde ich eine Vorlage?</a> · <a href="#karte">Was zeigt die Karte?</a> · <a href="#sicher">Wie sicher sind die Angaben?</a> · <a href="#aktuell">Wie aktuell sind die Daten?</a> · <a href="#mitmachen">Wie kann ich mitmachen?</a> · <a href="#datenschutz">Datenschutz</a> · <a href="#grenzen">Was der Ratsatlas nicht kann</a> · <a href="#kontakt">Kontakt</a></nav>
    <div class="einfach">
    <h2 id="was">Was ist der Ratsatlas?</h2>
    <p>In Köln beraten der Rat und andere Gremien über viele Themen. Zum Beispiel über Verkehr, Schulen oder Grünflächen.</p>
    <p>Ein Gremium ist eine Gruppe, die berät und entscheidet.</p>
    <p>Zu jeder Sache gibt es ein Schreiben. Dieses Schreiben heißt Vorlage.</p>
    <p>Die öffentlichen Vorlagen stehen im Ratsinformationssystem der Stadt Köln. Das ist eine Internetseite der Stadt.</p>
    <p>Der Ratsatlas zeigt diese Vorlagen auf einer Karte. Ein Atlas ist eine Sammlung von Karten. So sehen Sie: Worum geht es in meiner Nähe? Wann wurde darüber beraten? Und wer war beteiligt?</p>
    <p>Die Daten kommen von der Stadt Köln.</p>
{_fach(f"Quelle ist die OParl-Schnittstelle des Ratsinformationssystems der Stadt Köln (Lizenz laut Katalog dl-de/zero 2.0, Klärung mit der Stadt offen). {quelle}.")}

    <h2 id="wer">Wer entscheidet in Köln?</h2>
    <ul>
      <li><strong>Der Rat:</strong> Die Menschen in Köln wählen den Rat. Die Wahl ist alle 5 Jahre. Der Rat entscheidet über die wichtigen Fragen der ganzen Stadt.</li>
      <li><strong>Die Bezirksvertretungen:</strong> Köln hat {n_bezirke} Stadtbezirke: {escape(_aufzaehlung(bezirke))}. Jeder Stadtbezirk hat eine Bezirksvertretung. Auch sie wird gewählt. Sie entscheidet über Fragen, die vor allem den eigenen Stadtbezirk betreffen.</li>
      <li><strong>Die Stadtteile:</strong> Die {n_bezirke} Stadtbezirke sind in {n_teile} Stadtteile geteilt. Zum Beispiel Ehrenfeld oder Rath/Heumar. Viele sagen auch Veedel. Ein Veedel ist aber nicht immer genau ein Stadtteil.</li>
      <li><strong>Die Ausschüsse:</strong> Der Rat bildet Ausschüsse. Ein Ausschuss berät über ein Fachthema. Zum Beispiel über Schulen oder Verkehr. Manche Fragen entscheidet ein Ausschuss selbst.</li>
      <li><strong>Der Ausschuss für Anregungen und Beschwerden:</strong> Ein Ausschuss berät über Anregungen und Beschwerden aus der Bevölkerung. In Köln heißt er: Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden.</li>
      <li><strong>Die Verwaltung:</strong> Die Verwaltung arbeitet für die Stadt. Sie schreibt viele Vorlagen. Und sie setzt Beschlüsse um. Die Oberbürgermeisterin oder der Oberbürgermeister leitet die Verwaltung. Die Verwaltung hat viele Ämter. Wenn die Daten es zeigen, nennt der Ratsatlas das zuständige Amt.</li>
    </ul>
{_fach(f"Rat §§ 40–42 GO NRW; Bezirksvertretungen §§ 36, 37 GO NRW und {glossar.HAUPTSATZUNG}; Ausschüsse §§ 57–59 GO NRW; Anregungen und Beschwerden § 24 GO NRW; Leitung der Verwaltung § 62 GO NRW. Stadtbezirke und Stadtteile: {glossar.GEBIETE}.")}

    <h2 id="ablauf">Wie läuft eine Sache ab?</h2>
    <ol class="einfach-weg">
      <li><strong>Anstoß:</strong> Jemand bringt eine Sache ein. Das kann die Verwaltung sein. Oder eine Fraktion. Oder jemand aus der Bevölkerung, mit einer Anregung oder Beschwerde.</li>
      <li><strong>Vorlage:</strong> Die Sache wird aufgeschrieben. Sie bekommt eine Nummer.</li>
      <li><strong>Beratung:</strong> Gremien beraten die Vorlage in einer Sitzung. Oft beraten mehrere Gremien nacheinander.</li>
      <li><strong>Ergebnis:</strong> Am Ende steht ein Ergebnis. Zum Beispiel: beschlossen, abgelehnt oder vertagt.</li>
      <li><strong>Umsetzung:</strong> Danach setzt die Verwaltung den Beschluss um. Ob und wann das passiert, zeigen die öffentlichen Daten meistens nicht.</li>
    </ol>
    <p>Beim Vorgang auf der Karte heißen diese Schritte Prozesslinie.</p>
{_fach("Beratungsfolge und Ergebnisse laut Ratsinformationssystem (OParl: Consultation, AgendaItem); die Umsetzung von Beschlüssen ist nicht öffentlich dokumentiert.")}

    <h2 id="woerter">Was bedeuten die Wörter?</h2>
    <dl class="begriffe">
{_woerter(root)}
    </dl>
    <p>Auf der Karte steht das Ergebnis einer Beratung genau so, wie die Stadt es schreibt. Die Wörter oben sind Beispiele.</p>
    <p>Weitere Wörter stehen unter <a href="{root}begriffe/">Begriffe</a>. Auf der Karte erklärt auch das „?“ neben einem Wort dieses Wort.</p>
{_fach(f"Anregungen und Beschwerden § 24 GO NRW; Fraktion und Gruppe § 56 GO NRW; Antrag und Anfrage §§ 3, 4 der {glossar.GESCHO}. Ergebnisse stehen auf der Karte wörtlich wie im Ratsinformationssystem.")}

    <h2 id="finden">Wie finde ich eine Vorlage?</h2>
    <ol>
      <li>Öffnen Sie die <a href="{root}">Karte</a>. Am Anfang sehen Sie ganz Köln.</li>
      <li>Klicken Sie auf einen Stadtbezirk. Dann klicken Sie auf einen Stadtteil. Oder wählen Sie oben bei „Gebiet wählen“ ein Gebiet aus.</li>
      <li>Die Liste zeigt die Vorlagen in diesem Gebiet. Klicken Sie auf eine Vorlage.</li>
      <li>Dann sehen Sie den Vorgang: Worum geht es? Wer hat beraten? Was ist das Ergebnis?</li>
      <li>Mit „Original im Ratsinformationssystem“ öffnen Sie die Vorlage auf der Internetseite der Stadt Köln.</li>
    </ol>
    <p>Sie kennen ein Stichwort oder die Nummer einer Vorlage? Dann nutzen Sie die Suche oben auf der Karte. Sie sucht in ganz Köln.</p>
    <p>Es gibt auch eine Seite für jeden Stadtteil und jeden Stadtbezirk. Sie finden sie unter <a href="{root}gebiete/">Alle Gebiete</a>.</p>
    <p>Die „Tour durch alle Funktionen“ zeigt alles Schritt für Schritt. Sie finden die Tour auf der Karte im Menü „Verstehen“.</p>

    <h2 id="karte">Was zeigt die Karte?</h2>
    <ul>
      <li>Jeder Punkt ist eine Vorlage mit einem Ort.</li>
      <li>Eine Zahl in einem Kreis fasst mehrere Punkte zusammen. Klicken Sie darauf. Dann zeigt die Karte das Gebiet größer.</li>
      <li>Die Farbe eines Punktes zeigt, wie sicher der Ort ist. Mehr dazu steht unten bei <a href="#sicher">Wie sicher sind die Angaben?</a></li>
      <li>Manche Vorlagen haben keinen genauen Ort. Sie betreffen zum Beispiel einen ganzen Stadtbezirk. Oder die ganze Stadt. Sie finden diese Vorlagen bei „Gebiet wählen“.</li>
      <li>Im Menü „Ebenen“ blendet „Bebauungspläne“ die Gebiete der Bebauungspläne ein. Ein Bebauungsplan ist eine Regel der Stadt. Er legt fest, wie man in einem Gebiet bauen darf.</li>
{ebenen}      <li>Mit der Zeitleiste wählen Sie einen Zeitraum. Dann zeigen Karte und Liste nur Vorlagen aus dieser Zeit.</li>
    </ul>

    <h2 id="sicher">Wie sicher sind die Angaben?</h2>
    <p>Die meisten Angaben kommen unverändert von der Stadt Köln.</p>
    <p>Manche Angaben hat der Ratsatlas selbst erschlossen. Zum Beispiel den Ort oder das Thema einer Vorlage. Diese Angaben heißen „abgeleitet“. Sie können Fehler haben.</p>
    <p>Bei Orten gibt es 3 Stufen. Die Farbe auf der Karte zeigt die Stufe:</p>
    <ul>
      <li><strong>gesichert (grün):</strong> Der Ort ist ein Haus aus dem Adressverzeichnis der Stadt. Oder ein Bebauungsplan passt eindeutig.</li>
      <li><strong>erschlossen (braun):</strong> Im Titel steht der Name einer Straße oder eines Stadtteils. Oder die Stadt nennt den Stadtteil.</li>
      <li><strong>unsicher (violett):</strong> Der Name passt zu mehreren Orten. Oder nur das Gremium deutet auf einen Stadtbezirk. Zum Beispiel, weil nur eine Bezirksvertretung beraten hat.</li>
    </ul>
    <p>Bei jedem Ort steht, woher er kommt.</p>
    <p>Die Orte sind noch nicht von Hand geprüft. Diese Prüfung kommt noch. Die Ergebnisse stehen dann auf der Karte im Menü „Verstehen“ unter „Wie verlässlich sind die Angaben?“.</p>
    <p>Im Zweifel gilt immer das Original bei der Stadt Köln.</p>
{_fach("Verortung in Stufe A (Ortsangabe der Stadt) und Stufe B (Straßen-, Stadtteil- und Bezirksnamen, Hausnummern, Bebauungspläne); jede Verortung nennt Methode, Konfidenz und Fundstelle. Prüfung von Hand: 50 Vorlagen je Methode, noch offen.")}

    <h2 id="aktuell">Wie aktuell sind die Daten?</h2>
    <p>Der Ratsatlas fragt die Daten jede Nacht bei der Stadt Köln ab.</p>
    <p>Er fragt langsam und mit Pausen. So belastet er den Server der Stadt nicht.</p>
    <p>Nach dem ersten Mal holt er nur noch, was sich geändert hat.</p>
    <p>Wann die Daten zuletzt abgefragt wurden, steht auf der Karte bei „Quellen, Lizenzen und Datenstand“.</p>
    <p>Manchmal klappt die Abfrage nicht. Dann zeigt der Ratsatlas die letzten Daten, die er hat. Und er weist darauf hin.</p>
{_fach("Abruf über die OParl-Schnittstelle nachts mit einer Verbindung und Abstand zwischen den Anfragen; nach dem ersten Lauf nur geänderte Objekte, Gremien und Sitzungen jede Nacht vollständig (README, Abschnitt „Datenstand“).")}

    <h2 id="mitmachen">Wie kann ich mitmachen?</h2>
    <ul>
      <li><strong>Sitzungen besuchen:</strong> Die Sitzungen sind in der Regel öffentlich. Dann darf jede Person zuhören. Bei einzelnen Punkten kann ein Gremium die Öffentlichkeit ausschließen. Die Termine finden Sie auf der Karte im Menü „Mitmachen“ bei „Termine anzeigen“.</li>
      <li><strong>Anregungen und Beschwerden:</strong> Sie können sich schriftlich an den Rat wenden. Mit einer Anregung oder mit einer Beschwerde. Darüber berät der Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden. Wie Sie das einreichen, erklärt die Stadt Köln. Einen geprüften Link dazu ergänzen wir noch.</li>
      <li><strong>Informiert bleiben:</strong> Ein Feed meldet neue Vorlagen von selbst. Dafür brauchen Sie ein Programm für Feeds, einen Feed-Reader. <a href="{root}rss/">So geht es</a></li>
    </ul>
    <p>Wichtig: Der Ratsatlas gehört nicht zur Stadt Köln. Anregungen, Beschwerden und Fragen zu einer Vorlage gehen an die Stadt Köln.</p>
{_fach("Öffentlichkeit der Sitzungen § 48 GO NRW; Anregungen und Beschwerden § 24 GO NRW.")}

    <h2 id="datenschutz">Datenschutz</h2>
    <ul>
      <li>Der Ratsatlas setzt keine Cookies. Ein Cookie ist eine kleine Datei, die eine Internetseite auf Ihrem Gerät speichert.</li>
      <li>Nur ein paar Einstellungen merkt sich Ihr Browser. Zum Beispiel, ob die Karte farbig oder grau ist.</li>
      <li>Es gibt keine Anmeldung und keine Werbung. Der Ratsatlas wertet nicht aus, wer die Seite besucht.</li>
      <li>Der Server der Seite speichert, wie jeder Server, ein Protokoll der Aufrufe.</li>
      <li>Was Sie in die Suche eingeben, bleibt auf Ihrem Gerät.</li>
      <li>Der Ratsatlas zeigt keine Wohnadressen von Privatpersonen.</li>
      <li>Anregungen und Beschwerden aus der Bevölkerung zeigt die Karte höchstens mit Straße oder Stadtteil. Nie mit Hausnummer.</li>
    </ul>
    <p>Mehr dazu steht in der <a href="{root}datenschutz.html">Datenschutzerklärung</a>.</p>

    <h2 id="grenzen">Was der Ratsatlas nicht kann</h2>
    <ul>
      <li>Der Ratsatlas gibt keine Rechtsauskunft.</li>
      <li>Manche Sitzungen sind nicht öffentlich. Was dort beraten wird, kann der Ratsatlas nicht zeigen.</li>
      <li>Der Ratsatlas zeigt keine Texte aus den Dokumenten der Stadt. Er verweist auf das Original.</li>
{kurz}      <li>Der Ratsatlas bewertet keine Politik und keine Parteien.</li>
      <li>Im Zweifel gilt immer das Original bei der Stadt Köln.</li>
    </ul>

    <h2 id="kontakt">Kontakt</h2>
    <p>Den Ratsatlas Köln macht Damian Paderta. Er ist ein offenes Projekt. Das heißt: Jede Person kann den Code ansehen und verwenden.</p>
    <p>E-Mail: <a href="mailto:contact@nozilla.de">contact@nozilla.de</a></p>
    <p>Haben Sie einen Fehler gefunden? Schreiben Sie uns. Oder klicken Sie bei einer Vorlage auf „Verortung falsch? Hinweis geben“. Das öffnet ein Formular bei GitHub. Dort ist Ihr Hinweis öffentlich.</p>
    </div>
    <p class="meta">Diese Seite ist in Einfacher Sprache geschrieben, nicht in Leichter Sprache: Eine Prüfgruppe hat sie nicht geprüft. <a href="{root}">Zur Karte</a> · <a href="{root}begriffe/">Begriffe</a></p>"""


def _vorschau(site):
    """Kartenvorschau ohne Ratsvorlagen (index.json meta.vorschau); ohne lesbares index.json keine Vorschau."""
    try:
        meta = json.loads((site / "data" / "export" / "koeln" / "index.json").read_text(encoding="utf-8")).get("meta")
    except (OSError, ValueError):
        return False
    return bool((meta or {}).get("vorschau"))


def write(site, site_url, page):
    """Schreibt einfach/index.html; gibt den Pfad für die Sitemap zurück."""
    out = site / PFAD / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site_url, PFAD, f"{TITEL} – Ratsatlas Köln",
                        "Was zeigt der Ratsatlas Köln, wer entscheidet in Köln und wie können Sie mitmachen? "
                        "Erklärt in Einfacher Sprache.", body("../", _vorschau(site)), "../"), encoding="utf-8")
    return [PFAD]
