# Phase 3 – Geokodierung (Teil ohne Abrufe)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` 5.2, 7.3 und Entscheidungen in Abschnitt 9

## 1. Umgesetzt

| Regel | Methode (`method`) | Ebene | Konfidenz |
|---|---|---|---|
| Stufe A: `location.subLocality` → Stadtteilfläche, auch bei abweichender Schreibweise („Altstadt-Nord“) | `oparl_sublocality` | Stadtteil | mittel |
| Doppelnamen mit Schrägstrich auch mit Bindestrich oder Leerzeichen („Rath-Heumar“) | `ortsteil_name` | Stadtteil | mittel |
| Teilnamen von Doppelnamen („Heumar“ → Rath/Heumar), ausgenommen „Altstadt“, „Neustadt“, „Weiler“, „Humboldt“ | `ortsteil_teilname` | Stadtteil | mittel |
| Stadtbezirk nur in eindeutiger Form: „Stadtbezirk Porz“, „Bezirk Porz“, „Bezirksvertretung 7 (Porz)“, „BV 7“; ein bloßes „Porz“ meint den Stadtteil | `stadtbezirk_name` | Stadtbezirk | mittel |
| Hausnummer bestimmt den Stadtteil einer Straße, die durch mehrere Stadtteile läuft (Bonner Regel, jetzt mit „Adressen Köln“) | `strasse+hausnummer` | Straße | mittel |
| **Hauskoordinate** nur bei Verwaltungsvorlagen und politischen Anträgen (`NNNN/JJJJ`, `AN/NNNN/JJJJ`); nie bei Hinweisen auf § 24 GO, Anregung, Beschwerde, Eingabe, Bürger- oder Einwohnerantrag oder bei einer Beratung im Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden; nur wenn die Nummer in genau einem der möglichen Stadtteile vorkommt | `strasse+hausnummer_punkt` | Adresse | hoch |
| Gleichnamige Straßen nach Eingemeindungen: Auflösung über Stadtteil im Titel oder beratende Bezirksvertretung, sonst „mehrdeutig“ | `strasse+bezirk`, `strasse_mehrdeutig` | Straße | mittel bzw. niedrig |
| Bezirksvertretung aus dem Kölner Gremiennamen („Bezirksvertretung 3 (Lindenthal)“) | – | – | – |
| Schwache Evidenz: ohne sonstigen Ortsbezug und nur in einer Bezirksvertretung beraten | `district_from_committee` | Stadtbezirk | niedrig |

Neue Daten: `data/geo/hausnummern_koeln.json`. Es enthält 161 531 Adressen in 4 787 Straßen und ist 4,6 MB groß. In einer Stichprobe von 2 000 Adressen stimmt das Stadtteilfeld in allen Fällen mit der Fläche überein.

Tests: 30, alle bestanden. Davon prüfen 20 die Geokodierung mit erfundenen Titeln und den Kölner Geodaten.

## 2. Offen bis nach der Information der Stadt

1. **Präzision je Methode:** Die manuelle Prüfung von 50 Vorlagen je Methode und `audit_geokodierung.tsv` mit Kölner Daten erfordern echte Vorlagen.
2. **Vorlagentypen:** Die Regel für Hauskoordinaten stützt sich bisher auf das Referenzschema und Textmuster. Sobald die `paperType`-Liste vorliegt, wird sie auf die Typen umgestellt.
3. **Volltexte:** Die Verortung aus Volltexten (Bonner Methode `volltext_…`) und Stufe C setzen den Abruf der PDFs voraus.
4. **Bebauungspläne:** Bezugsquelle und Nummernschema fehlen weiterhin.
5. **Frontend:** Die Seite kennt die neue Ebene „adresse“ noch nicht (Phase 4).
