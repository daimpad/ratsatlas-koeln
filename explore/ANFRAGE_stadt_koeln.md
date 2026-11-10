# Entwurf: Anfrage an die Stadt Köln

> **Versand erst nach Zusammenführung von Runde 20 (Sitzungen)**

> Stand 10.11.2026 (aktualisiert: mündliche Zustimmung und Bitte um schriftliche Bestätigung, Probeabrufe, Vollabruf, Kartendatensätze; vorher 05.11.2026) · zur Versendung durch den Auftraggeber · Platzhalter in eckigen Klammern

**An:** e-government@stadt-koeln.de (Open-Data-Redaktion), 12-session@stadt-koeln.de (Fachanwendungsbetreuung Session/SessionNet)
**Betreff:** Nutzung der OParl-Schnittstelle für ein zivilgesellschaftliches Informationsangebot („Ratsatlas Köln“) – Bestätigung, Lizenz und Abrufrate

Sehr geehrte Damen und Herren,

ich entwickle ehrenamtlich den „Ratsatlas Köln“ (Adresse koeln.ratsatlas.de, derzeit als Vorschau; Quellcode offen unter https://github.com/daimpad/ratsatlas-koeln). Das Angebot soll Bürger:innen ohne Verwaltungswissen helfen, Vorlagen des Rates und der Bezirksvertretungen räumlich (Stadtteil, Straße), zeitlich (Stand der Beratung) und nach Zuständigkeit zu finden. Jede Angabe verweist auf das Original in Ihrem Ratsinformationssystem. Ein vergleichbares Angebot für Bonn ist bereits in Betrieb.

Für Ihre mündliche Zustimmung ([Datum], [Gesprächspartner:in, Stelle]) zum Abruf der OParl-Schnittstelle, auch zum ersten vollständigen Abruf aus GitHub Actions, danke ich Ihnen. Ich bitte Sie, diese Zustimmung kurz schriftlich zu bestätigen. Zum Stand:

- **Probeabrufe:** am 07., 08. und 09.11.2026 jeweils kurz nach 23 Uhr mit 3, 7 und 4 Anfragen; alle Antworten mit Status 200, ohne Weiterleitung und ohne Fehlermeldung.
- **Erster vollständiger Abruf:** ab dem 10.11.2026, 23:10 Uhr, aus GitHub Actions, mit rund 900 Anfragen je Nacht, voraussichtlich in zwei bis drei Nächten. Danach liest der Abruf jede Nacht nur geänderte Objekte (`modified_since`); die Gremienliste (96 Organisationen) und, falls der Zeitfilter dort nicht wirkt, die Sitzungen liest er vollständig.
- **Abrufpolitik:** eine Verbindung, mindestens 2 s Abstand zwischen zwei Anfragen, nur zwischen 23 und 1 Uhr, 100 Objekte je Seite. Nach 429 oder Serverfehlern (5xx) wartet der Abruf mit wachsenden Pausen oder setzt erst in einer späteren Nacht fort (`Retry-After` wird eingehalten); bei 401, 403 und 404 bricht er sofort ab. Zeitüberschreitungen und Verbindungsabbrüche gelten als mögliche Sperre: Abbruch ohne Wiederholung und ohne weiteren Lauf in derselben Nacht, nach drei solchen Nächten sieben Tage Pause. User-Agent: `ratsatlas-koeln/0.1 (+https://github.com/daimpad/ratsatlas-koeln; [Kontaktadresse])`.

Offen sind noch fünf Punkte:

1. **Lizenz:** Der Katalogeintrag „OParl API Koeln“ nennt die Datenlizenz Deutschland – Zero 2.0. Die Nutzungsbedingungen von offenedaten-koeln.de nennen CC BY 3.0 DE, und das Feld `license` des Body-Objekts ist leer. Gilt dl-de/zero 2.0 für alle OParl-Objekte? Gilt sie auch für die über `accessUrl`/`downloadUrl` verlinkten Dokumente (PDF)? Unabhängig davon werde ich die Quelle immer mit „Datenquelle: Stadt Köln – offenedaten-koeln.de“ angeben.
2. **Abgeleitete Daten:** Darf ich aus den Daten abgeleitete Angaben veröffentlichen? Gemeint sind Ortsbezüge (Stadtteil, Straße), Beratungsverläufe und die federführende Dienststelle. Die Dokumente selbst würde ich nicht spiegeln, sondern nur verlinken. Aus den PDFs würden keine Textauszüge veröffentlicht.
3. **Abrufrate:** Ist der nächtliche Abruf aus den wechselnden IP-Bereichen von GitHub Actions für Sie auch auf Dauer tragbar, oder wünschen Sie eine andere Rate oder eine feste Absenderadresse? Das Zeitfenster 23 bis 1 Uhr habe ich der Dokumentation eines anderen Projekts entnommen: Entspricht es Ihren Vorgaben? Gibt es für spätere vollständige Abzüge einen Massenexport?
4. **Dokumente:** Um die federführende Dienststelle zu erkennen, würde ich gern den Kopf der Verwaltungsvorlagen („Dezernat, Dienststelle“) auswerten. Dafür müsste ich die PDF-Dokumente abrufen: einmalig etwa 100 zur Prüfung, danach nur neue Vorlagen. Veröffentlicht würde nur die erkannte Dienststelle, kein Text. Ist der automatische Abruf von Dokumenten gestattet, und wenn ja, in welchem Umfang? Bis zu Ihrer Antwort rufe ich keine Dokumente ab.
5. **Datensätze für die Karte:** Für vier Kartenebenen fehlen mir Bezugsweg und Lizenz: Lärm (keine Landesdatei für Köln gefunden), Starkregen (nur ein Kartenbild gefunden), Sanierungsgebiete und Aufstellungsbeschlüsse (der ArcGIS-Dienst der Stadt war nicht abrufbar). Gibt es diese Daten als offene Daten, und unter welcher Lizenz?

Außerdem bitte ich, das **Body-Feld `license`** zu prüfen: Wäre es möglich, dieses Feld mit der geltenden Lizenz zu befüllen?

Und eine Rückfrage zu den Bebauungsplänen: Der im Katalog verlinkte Dienst (`geoportal.stadt-koeln.de/arcgis/rest/services/planen_und_bauen/b_plan_uebersicht/MapServer/1?f=pjson`) liefert bei mir statt JSON die Startseite der Stadt. Die rechtsverbindlichen Pläne beziehe ich deshalb über die Schnittstelle „Bauleitplanung in NRW“ des Landes. Entspricht die Plannummer `63429.06.000.00` dort der Schreibweise „63429/06“ in Ihren Vorlagen?

Wünschen Sie Änderungen am Abruf, passe ich ihn an. Für Rückfragen stehe ich gern zur Verfügung.

Mit freundlichen Grüßen
[Name]
[Kontaktadresse, ggf. Telefon]
