# Entwurf: Anfrage an die Stadt Köln

> Stand 04.11.2026 · zur Versendung durch den Auftraggeber · Platzhalter in eckigen Klammern

**An:** e-government@stadt-koeln.de (Open-Data-Redaktion), 12-session@stadt-koeln.de (Fachanwendungsbetreuung Session/SessionNet)
**Betreff:** Nutzung der OParl-Schnittstelle für ein zivilgesellschaftliches Informationsangebot („Ratsatlas Köln“) – Lizenz und Abrufrate

Sehr geehrte Damen und Herren,

ich entwickle ehrenamtlich den „Ratsatlas Köln“ (geplante Adresse koeln.ratsatlas.de, Quellcode offen unter https://github.com/daimpad/ratsatlas-koeln). Das Angebot soll Bürger:innen ohne Verwaltungswissen helfen, Vorlagen des Rates und der Bezirksvertretungen räumlich (Stadtteil, Straße), zeitlich (Stand der Beratung) und nach Zuständigkeit zu finden. Jede Angabe verweist auf das Original in Ihrem Ratsinformationssystem. Ein vergleichbares Angebot für Bonn ist bereits in Betrieb.

Bevor ich die OParl-Schnittstelle zum ersten Mal abrufe, möchte ich Sie informieren und vier Punkte klären:

1. **Lizenz:** Der Katalogeintrag „OParl API Koeln“ nennt die Datenlizenz Deutschland – Zero 2.0. Die Nutzungsbedingungen von offenedaten-koeln.de nennen CC BY 3.0 DE, und das Feld `license` des Body-Objekts ist leer. Gilt dl-de/zero 2.0 für alle OParl-Objekte? Gilt sie auch für die über `accessUrl`/`downloadUrl` verlinkten Dokumente (PDF)? Unabhängig davon werde ich die Quelle immer mit „Datenquelle: Stadt Köln – offenedaten-koeln.de“ angeben.
2. **Abgeleitete Daten:** Darf ich aus den Daten abgeleitete Angaben veröffentlichen? Gemeint sind Ortsbezüge (Stadtteil, Straße), Beratungsverläufe und die federführende Dienststelle. Die Dokumente selbst würde ich nicht spiegeln, sondern nur verlinken. Aus den PDFs würden keine Textauszüge veröffentlicht.
3. **Abrufrate:** Geplant sind eine Verbindung zur Zeit, mindestens zwei Sekunden Abstand zwischen zwei Anfragen, Abrufe nachts und nach dem ersten Abzug nur geänderte Objekte (`modified_since`). Nach Fehlern würde der Abruf mit wachsenden Pausen von bis zu mehreren Stunden wiederholt. Der Abruf erfolgt aus GitHub Actions, also aus Rechenzentrums-IP-Bereichen, mit dem User-Agent `ratsatlas-koeln/<Version> (+https://github.com/daimpad/ratsatlas-koeln; [Kontaktadresse])`. Ist das für Sie tragbar? Welche Rate und welches Zeitfenster bevorzugen Sie? Gibt es für den ersten vollständigen Abzug einen Massenexport?
4. **Body-Feld `license`:** Wäre es möglich, dieses Feld mit der geltenden Lizenz zu befüllen?

Außerdem eine technische Rückfrage: Der im Katalog verlinkte Dienst für Bebauungspläne (`geoportal.stadt-koeln.de/arcgis/rest/services/planen_und_bauen/b_plan_uebersicht/MapServer/1?f=pjson`) liefert bei mir statt JSON die Startseite der Stadt. Gibt es eine andere Bezugsquelle für die Geltungsbereiche mit Plannummern?

Bis zu Ihrer Antwort rufe ich die OParl-Schnittstelle nicht ab. Für Rückfragen stehe ich gern zur Verfügung.

Mit freundlichen Grüßen
[Name]
[Kontaktadresse, ggf. Telefon]
