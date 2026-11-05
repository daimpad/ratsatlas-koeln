# Entwurf: Anfrage an die Stadt Köln

> Stand 05.11.2026 (ergänzt: Zeitfenster, Dokumentabruf, GitHub Actions, Bebauungspläne) · zur Versendung durch den Auftraggeber · Platzhalter in eckigen Klammern

**An:** e-government@stadt-koeln.de (Open-Data-Redaktion), 12-session@stadt-koeln.de (Fachanwendungsbetreuung Session/SessionNet)
**Betreff:** Nutzung der OParl-Schnittstelle für ein zivilgesellschaftliches Informationsangebot („Ratsatlas Köln“) – Lizenz, Abrufrate und Zeitfenster

Sehr geehrte Damen und Herren,

ich entwickle ehrenamtlich den „Ratsatlas Köln“ (geplante Adresse koeln.ratsatlas.de, Quellcode offen unter https://github.com/daimpad/ratsatlas-koeln). Das Angebot soll Bürger:innen ohne Verwaltungswissen helfen, Vorlagen des Rates und der Bezirksvertretungen räumlich (Stadtteil, Straße), zeitlich (Stand der Beratung) und nach Zuständigkeit zu finden. Jede Angabe verweist auf das Original in Ihrem Ratsinformationssystem. Ein vergleichbares Angebot für Bonn ist bereits in Betrieb.

Bevor ich die OParl-Schnittstelle zum ersten Mal abrufe, möchte ich Sie informieren und fünf Punkte klären:

1. **Lizenz:** Der Katalogeintrag „OParl API Koeln“ nennt die Datenlizenz Deutschland – Zero 2.0. Die Nutzungsbedingungen von offenedaten-koeln.de nennen CC BY 3.0 DE, und das Feld `license` des Body-Objekts ist leer. Gilt dl-de/zero 2.0 für alle OParl-Objekte? Gilt sie auch für die über `accessUrl`/`downloadUrl` verlinkten Dokumente (PDF)? Unabhängig davon werde ich die Quelle immer mit „Datenquelle: Stadt Köln – offenedaten-koeln.de“ angeben.
2. **Abgeleitete Daten:** Darf ich aus den Daten abgeleitete Angaben veröffentlichen? Gemeint sind Ortsbezüge (Stadtteil, Straße), Beratungsverläufe und die federführende Dienststelle. Die Dokumente selbst würde ich nicht spiegeln, sondern nur verlinken. Aus den PDFs würden keine Textauszüge veröffentlicht.
3. **Abrufrate und Zeitfenster:** Geplant sind eine Verbindung zur Zeit, mindestens zwei Sekunden Abstand zwischen zwei Anfragen und Abrufe nur nachts zwischen 23 und 1 Uhr; nach dem ersten Abzug nur geänderte Objekte (`modified_since`). Der erste vollständige Abzug würde sich dadurch auf mehrere Nächte verteilen. Nach Serverfehlern würde mit wachsenden Pausen wiederholt; bei Zeitüberschreitungen oder Verbindungsabbrüchen bricht der Abruf bis zur nächsten Nacht ab und pausiert nach drei solchen Nächten eine Woche. Das Zeitfenster 23 bis 1 Uhr habe ich der Dokumentation eines anderen Projekts entnommen: Entspricht es Ihren Vorgaben, oder bevorzugen Sie ein anderes Zeitfenster oder eine andere Rate? Gibt es für den ersten vollständigen Abzug einen Massenexport?
4. **Absender:** Der Abruf erfolgt aus GitHub Actions, also aus Rechenzentrums-IP-Bereichen, die wechseln und von vielen Nutzern geteilt werden, mit dem User-Agent `ratsatlas-koeln/<Version> (+https://github.com/daimpad/ratsatlas-koeln; [Kontaktadresse])`. Ist das für Sie tragbar, oder wünschen Sie einen Abruf von einer festen Adresse?
5. **Dokumente:** Um die federführende Dienststelle zu erkennen, würde ich gern den Kopf der Verwaltungsvorlagen („Dezernat, Dienststelle“) auswerten. Dafür müsste ich die PDF-Dokumente abrufen: einmalig etwa 100 zur Prüfung, danach nur neue Vorlagen. Veröffentlicht würde nur die erkannte Dienststelle, kein Text. Ist der automatische Abruf von Dokumenten gestattet, und wenn ja, in welchem Umfang?

Außerdem bitte ich, das **Body-Feld `license`** zu prüfen: Wäre es möglich, dieses Feld mit der geltenden Lizenz zu befüllen?

Und eine Rückfrage zu den Bebauungsplänen: Der im Katalog verlinkte Dienst (`geoportal.stadt-koeln.de/arcgis/rest/services/planen_und_bauen/b_plan_uebersicht/MapServer/1?f=pjson`) liefert bei mir statt JSON die Startseite der Stadt. Die rechtsverbindlichen Pläne beziehe ich deshalb über die Schnittstelle „Bauleitplanung in NRW“ des Landes. Gibt es eine Bezugsquelle für die Aufstellungsbeschlüsse, und entspricht die Plannummer `63429.06.000.00` dort der Schreibweise „63429/06“ in Ihren Vorlagen?

Bis zu Ihrer Antwort rufe ich die OParl-Schnittstelle nicht ab. Für Rückfragen stehe ich gern zur Verfügung.

Mit freundlichen Grüßen
[Name]
[Kontaktadresse, ggf. Telefon]
