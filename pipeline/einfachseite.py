"""Seite einfach/: Der Ratsatlas in Einfacher Sprache (Entscheidungen des Auftraggebers 02.11.2026: acht Abschnitte,
überall verlinkt, direkt veröffentlicht, Prüfung danach). Grundlage: verstaendlichkeit/phase0/BERICHT.md, Abschnitt 3.

Einfache Sprache, nicht Leichte Sprache: keine Prüfgruppe. Kurze Sätze, ein Gedanke je Satz. Jede Aussage zu Rechten
und Abläufen trägt eine Zeile „Für Fachleute“ mit Fundstelle. Die Erklärungen der Wörter sagen dasselbe wie das Glossar
(pipeline/glossar.py), nur einfacher. Keine Bewertung von Politik, Parteien oder Entscheidungen; keine Zusagen zum
Erfolg eines Bürgerantrags. Keine Erzeugungszeitpunkte (stabile Ausgabe)."""

PFAD = "einfach/"
BUERGERANTRAG = ("https://www.bonn.de/vv/produkte/buergerantrag-anregungen-und-beschwerden-gemaess-24-gemeindeordnung-"
                 "nrw.php")

# (Wort, Erklärung) – gleicher Sinn wie im Glossar
WOERTER = [
    ("Vorlage", "Ein Schreiben, über das ein Gremium berät."),
    ("Drucksachennummer", "Die Nummer einer Vorlage, zum Beispiel 261798. Mit dieser Nummer finden Sie die Vorlage "
                          "wieder."),
    ("Gremium", "Eine Gruppe, die berät und entscheidet. Zum Beispiel der Rat, ein Ausschuss oder eine "
                "Bezirksvertretung."),
    ("Beschlussvorlage", "Die Verwaltung schlägt etwas vor. Das Gremium soll darüber entscheiden."),
    ("Mitteilungsvorlage", "Die Verwaltung informiert das Gremium. Eine Entscheidung ist nicht vorgesehen."),
    ("Antrag", "Eine Fraktion oder ein Mitglied bittet das Gremium, etwas zu beschließen."),
    ("Stellungnahme der Verwaltung", "Die Verwaltung antwortet schriftlich. Oft auf einen Antrag oder eine Anfrage."),
    ("Bürgerantrag", "Jede Person kann sich mit einer Anregung oder Beschwerde an den Rat oder an eine "
                     "Bezirksvertretung wenden."),
    ("Fraktion", "Mitglieder im Rat oder in einer Bezirksvertretung, die sich zu einer Gruppe zusammenschließen."),
    ("beschlossen", "Das Gremium hat zugestimmt. Manchmal mit Änderungen."),
    ("abgelehnt", "Die Mehrheit im Gremium hat dagegen gestimmt."),
    ("zur Kenntnis genommen", "Das Gremium wurde informiert. Es gab keine Abstimmung über einen Beschluss. Das heißt "
                              "nicht „abgelehnt“."),
    ("vertagt", "Die Beratung ist verschoben, auf eine spätere Sitzung."),
    ("Stand", "Die Karte zeigt, wie weit eine Vorlage ist. Zum Beispiel „entschieden“ oder „in Beratung“. Den Stand "
              "leitet die Karte aus den Beratungen ab."),
]


def _fach(text):
    return f'    <p class="einfach-fach"><strong>Für Fachleute:</strong> {text}</p>'


def body(root):
    woerter = "\n".join(f"      <dt>{w}</dt><dd>{e}</dd>" for w, e in WOERTER)
    return f"""    <h1>Der Ratsatlas in Einfacher Sprache</h1>
    <p class="lead">Auf dieser Seite erklären wir den Ratsatlas in Einfacher Sprache. Sie erfahren: Was zeigt die Karte? Wer entscheidet in Bonn? Und wie können Sie mitmachen?</p>
    <nav class="thema-sprung" aria-label="Auf dieser Seite"><span>Auf dieser Seite:</span> <a href="#was">Was ist der Ratsatlas?</a> · <a href="#wer">Wer entscheidet?</a> · <a href="#ablauf">Wie läuft eine Sache ab?</a> · <a href="#woerter">Was bedeuten die Wörter?</a> · <a href="#benutzen">Wie benutze ich die Karte?</a> · <a href="#mitmachen">Wie kann ich mitmachen?</a> · <a href="#grenzen">Was die Karte nicht kann</a> · <a href="#kontakt">Kontakt</a></nav>
    <div class="einfach">
    <h2 id="was">Was ist der Ratsatlas?</h2>
    <p>Der Rat der Stadt Bonn und andere Gremien beraten über viele Themen. Zum Beispiel über Straßen, Schulen oder Spielplätze.</p>
    <p>Zu jedem Thema gibt es ein Schreiben. Dieses Schreiben heißt Vorlage.</p>
    <p>Alle Vorlagen stehen im Ratsinformationssystem der Stadt Bonn. Die Abkürzung dafür ist RIS.</p>
    <p>Der Ratsatlas zeigt diese Vorlagen auf einer Karte. Ein Atlas ist eine Sammlung von Karten. So sehen Sie: Worum geht es in meiner Nähe? Wann wurde darüber beraten? Und wer war beteiligt?</p>
    <p>Die Daten kommen von der Stadt Bonn. Die Karte holt sie jeden Morgen neu. Sie zeigt Vorlagen ab Oktober 2019.</p>
{_fach("Quelle ist die OParl-Schnittstelle des Ratsinformationssystems der Stadt Bonn (CC0); Sitzungen und Ergebnisse über OParl-Lite (CC BY 4.0).")}

    <h2 id="wer">Wer entscheidet in Bonn?</h2>
    <ul>
      <li><strong>Der Rat:</strong> Die Menschen in Bonn wählen den Rat alle 5 Jahre. Der Rat entscheidet über die wichtigen Fragen der ganzen Stadt.</li>
      <li><strong>Die Bezirksvertretungen:</strong> Bonn hat 4 Stadtbezirke: Bonn, Bad Godesberg, Beuel und Hardtberg. Jeder Stadtbezirk hat eine Bezirksvertretung. Sie entscheidet über Fragen im eigenen Stadtbezirk. Zum Beispiel über einen Spielplatz.</li>
      <li><strong>Die Ausschüsse:</strong> Der Rat bildet Ausschüsse. Sie beraten über ein Fachthema, zum Beispiel über Schulen oder Verkehr. Manche Fragen entscheiden sie selbst.</li>
      <li><strong>Die Verwaltung:</strong> Die Verwaltung arbeitet für die Stadt. Sie schreibt viele Vorlagen. Und sie setzt Beschlüsse um. Die Oberbürgermeisterin oder der Oberbürgermeister leitet die Verwaltung.</li>
    </ul>
{_fach("Rat §§ 40–42 GO NRW; Bezirksvertretungen §§ 36, 37 GO NRW; Ausschüsse §§ 57–59 GO NRW; Leitung der Verwaltung § 62 GO NRW.")}

    <h2 id="ablauf">Wie läuft eine Sache ab?</h2>
    <ol class="einfach-weg">
      <li><strong>Anstoß:</strong> Jemand bringt eine Sache ein. Das kann die Verwaltung sein, eine Fraktion oder eine Person aus Bonn.</li>
      <li><strong>Vorlage:</strong> Die Sache wird aufgeschrieben. Sie bekommt eine Nummer.</li>
      <li><strong>Beratung:</strong> Gremien beraten die Vorlage in einer Sitzung.</li>
      <li><strong>Ergebnis:</strong> Am Ende steht ein Ergebnis. Zum Beispiel: beschlossen, abgelehnt oder vertagt.</li>
      <li><strong>Umsetzung:</strong> Danach setzt die Verwaltung den Beschluss um. Das sieht man auf der Karte meistens nicht.</li>
    </ol>
{_fach("Beratungsfolge und Ergebnisse laut Ratsinformationssystem; die Umsetzung von Beschlüssen ist nicht öffentlich dokumentiert.")}

    <h2 id="woerter">Was bedeuten die Wörter?</h2>
    <dl class="begriffe">
{woerter}
    </dl>
    <p>Weitere Wörter stehen unter <a href="{root}begriffe/">Begriffe</a>. Auf der Karte erklärt auch das „?“ neben einem Wort dieses Wort.</p>
{_fach("Bürgerantrag § 24 GO NRW; Fraktion § 56 GO NRW; Ergebnisse stehen auf der Karte wörtlich wie im Ratsinformationssystem.")}

    <h2 id="benutzen">Wie benutze ich die Karte?</h2>
    <ol>
      <li>Öffnen Sie die <a href="{root}">Karte</a>. Am Anfang sehen Sie ganz Bonn.</li>
      <li>Klicken Sie auf einen Stadtbezirk und dann auf einen Ortsteil. Oder wählen Sie oben ein Gebiet aus.</li>
      <li>Die Liste zeigt die Vorlagen in diesem Gebiet. Klicken Sie auf eine Vorlage.</li>
      <li>Dann sehen Sie den Vorgang: Worum geht es? Wer hat beraten? Was ist das Ergebnis?</li>
      <li>Mit „Original im Ratsinformationssystem“ öffnen Sie die Vorlage bei der Stadt Bonn.</li>
    </ol>
    <p>Die Suche oben findet Vorlagen in ganz Bonn. Die „Tour durch alle Funktionen“ im Startfenster zeigt alles Schritt für Schritt.</p>

    <h2 id="mitmachen">Wie kann ich mitmachen?</h2>
    <ul>
      <li><strong>Sitzungen besuchen:</strong> Die Sitzungen sind meistens öffentlich. Jede Person kann zuhören. Die Termine stehen auf der Karte unter „Mitmachen“.</li>
      <li><strong>Fragen stellen:</strong> In den Bezirksvertretungen gibt es eine Einwohnerfragestunde. Sie können bis zu 2 Fragen stellen. Reichen Sie die Fragen spätestens 21 Tage vor der Sitzung ein.</li>
      <li><strong>Bürgerantrag:</strong> Sie können sich schriftlich mit einer Anregung oder Beschwerde an den Rat oder an Ihre Bezirksvertretung wenden. <a href="{BUERGERANTRAG}">So geht der Bürgerantrag bei der Stadt Bonn</a></li>
      <li><strong>Informiert bleiben:</strong> Mit einem <a href="{root}rss/">Feed</a> erfahren Sie, wenn es Neues gibt.</li>
    </ul>
    <p>Wichtig: Der Ratsatlas ist keine Stelle der Stadt. Fragen und Anträge gehen an die Stadt Bonn.</p>
{_fach("Öffentlichkeit der Sitzungen § 48 GO NRW; Einwohnerfragestunde § 26 der Geschäftsordnung des Rates; Anregungen und Beschwerden § 24 GO NRW.")}

    <h2 id="grenzen">Was die Karte nicht kann</h2>
    <ul>
      <li>Die Karte gibt keine Rechtsauskunft.</li>
      <li>Manche Angaben hat die Karte selbst erschlossen. Zum Beispiel den Ort einer Vorlage. Diese Angaben sind mit „abgeleitet“ markiert. Sie können Fehler haben.</li>
      <li>Manche Vorlagen haben eine kurze Zusammenfassung. Ein Computerprogramm hat sie geschrieben. Einzelheiten können ungenau sein.</li>
      <li>Nichtöffentliche Beratungen kann die Karte nicht zeigen.</li>
      <li>Die Karte bewertet keine Politik und keine Parteien.</li>
      <li>Maßgeblich ist immer das Original bei der Stadt Bonn.</li>
    </ul>

    <h2 id="kontakt">Kontakt</h2>
    <p>Den Ratsatlas hat Damian Paderta beim Hackathon „Hack den Stadtrat“ gemacht.</p>
    <p>E-Mail: <a href="mailto:contact@nozilla.de">contact@nozilla.de</a></p>
    <p>Haben Sie einen Fehler gefunden? Schreiben Sie uns. Oder klicken Sie auf der Karte im Vorgang auf „Verortung falsch? Hinweis geben“.</p>
    </div>
    <p class="meta">Diese Seite ist in Einfacher Sprache geschrieben, nicht in Leichter Sprache: Eine Prüfgruppe hat sie nicht geprüft. <a href="{root}">Zur Karte</a> · <a href="{root}begriffe/">Begriffe</a></p>"""


def write(site, site_url, page):
    """Schreibt einfach/index.html; gibt den Pfad für die Sitemap zurück."""
    out = site / PFAD / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(site_url, PFAD, "Der Ratsatlas in Einfacher Sprache – Ratsatlas Bonn",
                        "Was zeigt der Ratsatlas Bonn, wer entscheidet in Bonn und wie können Sie mitmachen? "
                        "Erklärt in Einfacher Sprache.", body("../"), "../"), encoding="utf-8")
    return [PFAD]
