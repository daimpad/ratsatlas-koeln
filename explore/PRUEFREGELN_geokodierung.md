# Prüfregeln: Stichprobe der Geokodierung

Für `stichprobe_geokodierung.tsv` aus dem Datenpaket (je Methode bis zu 50 Vorlagen, CLAUDE.md 7.3). Beurteilt wird im Prüfbogen `tools/pruefbogen.html` (lokal, ohne Netz), ausgewertet mit `tools/praezision.py` (TECHNIK.md, „Präzision der Geokodierung“). Danke, dass Sie sich die Zeit nehmen: Jede beurteilte Zeile zeigt genauer, wie verlässlich die Karte ist.

## Was beurteilt wird

Eine Zeile ist eine Vorlage mit einer Methode. Beurteilt wird die ganze Zeile: alle Orte, die diese Methode der Vorlage zuordnet (Spalten „ort“, „ebene“, „stadtteil_oder_bezirk“). Maßstab ist der Gegenstand der Vorlage, also das, worüber sie entscheidet, berichtet oder fragt. Er ergibt sich aus dem Titel; reicht der Titel nicht, aus dem Original im Ratsinformationssystem über den Link.

Geprüft wird die Präzision, nicht die Vollständigkeit: Fehlt ein Ort, ändert das das Urteil nicht. Ein Ort stimmt, wenn er auf seiner Ebene stimmt; eine gröbere Ebene als möglich ist kein Fehler. Eine ausgeblendete Hausnummer („[Hausnummer ausgelassen]“) wird nicht herausgesucht.

## Urteile

- **richtig**: Jeder Ort der Zeile ist Gegenstand der Vorlage und auf seiner Ebene richtig aufgelöst.
- **teilweise**: Die Zeile trifft den Gegenstand nur zum Teil, etwa der richtige Stadtbezirk, aber ein falscher Stadtteil; die richtige Straße, aber bei gleichnamigen Straßen der falsche Stadtteil; von mehreren Orten mindestens einer richtig und einer falsch.
- **falsch**: Kein Ort der Zeile ist Gegenstand der Vorlage: nur beiläufig genannt (etwa die Anschrift einer Dienststelle oder ein Sitzungsort) oder falsch aufgelöst (etwa ein Name, der einer Person, einer Firma oder einem anderen Ort gleicht).
- **unklar**: Der Gegenstand lässt sich weder aus dem Titel noch aus dem Original bestimmen, oder das Original ist nicht zugänglich. Die Zeile wird gezählt, geht aber in keine Präzision ein.

Leer heißt: noch nicht beurteilt.

## Je Ebene

- **Adresse (Punkt)**: richtig, wenn Straße und Hausnummer den Ort des Vorhabens treffen; teilweise, wenn die Straße stimmt, die Hausnummer aber ein anderes Grundstück meint.
- **Straße**: richtig, wenn das Vorhaben an dieser Straße im genannten Stadtteil liegt (ein Abschnitt genügt); teilweise bei der richtigen Straße im falschen Stadtteil oder wenn von mehreren gleichnamigen Straßen nur eine gemeint ist.
- **Stadtteil**: richtig, wenn das Vorhaben im Stadtteil liegt oder ihn als Ganzes betrifft; teilweise, wenn es in einem anderen Stadtteil desselben Stadtbezirks liegt oder die Vorlage den gleichnamigen Stadtbezirk meint (etwa Ehrenfeld oder Porz).
- **Stadtbezirk**: richtig, wenn das Vorhaben im Stadtbezirk liegt oder ihn betrifft, auch bei `district_from_committee` (nur eine Bezirksvertretung hat beraten); falsch, wenn die Vorlage die ganze Stadt oder einen anderen Stadtbezirk betrifft.
- **Bebauungsplan**: richtig, wenn die Vorlage diesen Plan behandelt (Aufstellung, Änderung, Satzung, Bericht); falsch, wenn die Nummer nur auf einen anderen Plan verweist oder kein Bebauungsplan ist.
- **Gebäude oder Anlage**: richtig, wenn genau dieses Gebäude oder diese Anlage gemeint ist; falsch bei einem gleichnamigen Objekt an anderer Stelle.

## Anmerkungen

Kurz und sachlich, etwa „Stadtteil falsch, Bezirk richtig“. Keine Namen oder Anschriften von Privatpersonen und keine Zitate aus Dokumenten (CLAUDE.md 2 und 6). Die beurteilte Datei kommt nicht auf die Seite; in den Bericht geht nur die Auswertung mit Zahlen.
