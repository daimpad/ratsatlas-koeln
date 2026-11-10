<p align="center"><img src="site/favicon.svg" width="64" height="64" alt=""></p>

<h1 align="center">Ratsatlas Köln</h1>

<p align="center"><strong>Womit befassen sich Rat, Ausschüsse und Bezirksvertretungen der Stadt Köln – wo, wann und wer ist beteiligt?</strong></p>

<p align="center">
  <a href="https://github.com/daimpad/ratsatlas-koeln/actions/workflows/tests.yml"><img src="https://github.com/daimpad/ratsatlas-koeln/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/Code-MIT-2563eb" alt="Code: MIT"></a>
  <a href="data/LICENSE-DATA.md"><img src="https://img.shields.io/badge/Daten-dl--de%2Fzero%20und%20dl--de%2Fby%202.0-15803d" alt="Daten: dl-de/zero 2.0 und dl-de/by 2.0"></a>
  <img src="https://img.shields.io/badge/axe-WCAG%202.1%20AA%20gepr%C3%BCft-5b21b6" alt="Barrierefreiheit: mit axe auf WCAG 2.1 AA geprüft">
</p>

> **Stand:** Kartenvorschau. Die Seite zeigt Stadtteile, Kennzahlen und Kartenebenen aus offenen Daten; die Ratsvorlagen der Stadt Köln folgen nach einem vorsichtig gestuften ersten Abruf.

Der Ratsatlas Köln soll die öffentlichen Vorlagen aus dem Ratsinformationssystem der Stadt Köln auf einer Karte, einer Zeitleiste und als Liste zeigen, täglich aktualisiert. Er richtet sich an Bürgerinnen und Bürger ohne Verwaltungswissen. Jede Angabe führt zum Original; was abgeleitet ist, ist gekennzeichnet.

🌐 **Seite (geplant):** https://koeln.ratsatlas.de/ · Spiegel: https://daimpad.github.io/ratsatlas-koeln/ · 🛠️ **Technik:** [TECHNIK.md](TECHNIK.md)

## Ziel

Die Ratsinformationen werden in drei Richtungen erschlossen:

| | Frage | Was die Seite zeigt |
|---|---|---|
| 🗺️ | **Wo?** | Vorlagen mit Ortsbezug auf der Karte; Auswahl nach 9 Stadtbezirken und 86 Stadtteilen, wo belegbar bis zur Straße. |
| 🕒 | **Wann?** | Je Vorlage eine Prozesslinie: Veröffentlichung, Beratungen mit Gremium, Datum, Tagesordnungspunkt und wörtlichem Ergebnis, Folgevorlagen; kommende Sitzungen als offene Stationen. |
| 👥 | **Wer?** | Befasste Gremien (Rat, Fachausschüsse, Bezirksvertretungen), einreichende Fraktionen und – sobald ermittelbar – die federführende Dienststelle. |

Dazu gibt es eine Suche, Erklärungen der Begriffe, Feeds und einen Sitzungskalender zum Abonnieren sowie ein Datenpaket zum Weiterverwenden. Die Prüfprotokolle (Audits) und Stichproben zur Verortung stehen nur im Datenpaket, nicht als einzelne Dateien auf der Seite.

## Herkunft

Der Ratsatlas Köln beruht auf dem Code des **Ratsatlas Bonn** ([daimpad/ratsatlas-bonn](https://github.com/daimpad/ratsatlas-bonn), damals `allris-test`). Übernommen wurde der Stand von Commit `9eea7eaaba8d822ac6e4b7a96357e64cce406e47` (03.11.2026) als unabhängige Kopie mit eigener Historie, ohne die Bonner Daten (siehe [NOTICE](NOTICE)). Für Köln neu sind der Abruf der Kölner Schnittstelle, die Kölner Gebiets-, Straßen- und Adressdaten und die Regeln der Verortung. Bonner Zusatzthemen wie Haushalt, Themenseiten oder der Ratsassistent sind für Köln noch nicht freigegeben und abgeschaltet.

## Quellen und Lizenzen

| Quelle | Wofür | Lizenz |
|---|---|---|
| Ratsinformationssystem der Stadt Köln (OParl-Schnittstelle) | Vorlagen, Beratungen, Sitzungen, Gremien | laut Katalog dl-de/zero 2.0; Klärung mit der Stadt offen |
| Stadtteile, Stadtbezirke, Straßen und Adressen der Stadt Köln (offenedaten-koeln.de) | Gebiete und Verortung | dl-de/zero 2.0 |
| Bebauungspläne aus der Schnittstelle „Bauleitplanung in NRW“ (MHKBD NRW / IT.NRW) | Verortung über die Plannummer | dl-de/by 2.0 |
| Zensus 2022, BORIS NRW, Klimaanalyse NRW, Überschwemmungs- und Hochwassergefahrenkarten, Kitas und Schulen NRW, VRS-Fahrplan, Schutzgebiete NRW | Kennzahlen je Stadtteil und Kartenebenen | dl-de/zero 2.0 bzw. dl-de/by 2.0 (je Ebene angegeben) |
| Weitere offene Daten der Stadt Köln (Lebenswerte Veedel, Sozialräume, Stimmbezirke, Wohnbaupotenziale, Fahrradstraßen, Denkmalliste) | Kartenebenen | dl-de/zero 2.0 |
| Statistischer Datenkatalog Köln (Stadt Köln, Amt für Stadtentwicklung und Statistik) | Strukturdaten je Stadtteil, Stadtbezirk und für die Gesamtstadt (`data/strukturdaten/`; die Anzeige auf der Seite folgt) | dl-de/by 2.0 |
| Wegweiser Kommune (Bertelsmann Stiftung) | gesamtstädtische Vergleichswerte für Bonn, Köln und Wuppertal | CC0 1.0 (Quellenangabe wird geführt) |
| OpenStreetMap über Protomaps | grauer Kartenhintergrund | ODbL 1.0 |

Die Namensnennung „Datenquelle: Stadt Köln – offenedaten-koeln.de“ steht auf jeder Seite und in jeder JSON-, GeoJSON-, Feed- und Kalenderdatei mit Daten aus dem Ratsinformationssystem oder von offenedaten-koeln.de; für die Tabellen (TSV) im Datenpaket gilt die Lizenzübersicht. Dateien mit Daten von Land und Bund nennen deren Quelle, Lizenz und Namensnennung in der Datei selbst (`meta`, in `ebenen.json` je Ebene). Der Code steht unter der [MIT-Lizenz](LICENSE), die Daten unter den Lizenzen in [data/LICENSE-DATA.md](data/LICENSE-DATA.md), dort mit der Lizenz jeder einzelnen Datei.

## Grenzen

- **Ableitungen:** Orte aus dem Titel, Themen und Fraktionen sind abgeleitet und können falsch sein. Jede Verortung nennt Methode, Konfidenz und Fundstelle. Die Prüfung von Hand an Kölner Vorlagen steht noch aus.
- **Datenschutz:** Wohnadressen von Privatpersonen werden nicht gezeigt. Auf ein einzelnes Haus gesetzt werden nur Vorlagen der Verwaltung sowie politische Anträge und Anfragen, nie Anregungen und Beschwerden nach § 24 GO NRW; ist die Art einer Vorlage nicht erkennbar, zeigt die Karte höchstens die Straße.
- **Volltexte:** Bis die Lizenz geklärt ist, erscheinen keine Volltexte, Zitate oder Dokumente der Stadt; die Seite verlinkt nur auf das Original.
- **Nicht einsehbar:** Nichtöffentliche Beratungen, Arbeit innerhalb der Verwaltung und die Umsetzung von Beschlüssen.
- **Strukturdaten:** Die Werte stehen unverändert wie in der Quelle. Werte, die die Stadt wegen der Geheimhaltung nicht veröffentlicht, bleiben leer. Typ und Einheit der Kennzahlen sind eigene Einordnungen. Vergleichswerte des Wegweisers Kommune und Werte der Kölner Stadtstatistik unterscheiden sich in Definition und Stichtag; sie werden nicht miteinander verrechnet. Dass Vorlagen und Strukturmerkmale im selben Gebiet vorkommen, belegt keinen Zusammenhang.
- **Maßgeblich** ist immer das Original im Ratsinformationssystem.

## Datenstand

Abgerufen wird nachts, mit einer Verbindung und Abstand zwischen den Anfragen; nach dem ersten Lauf nur Geänderte. Fällt der Abruf aus, zeigt die Seite den letzten gültigen Stand und weist darauf hin. Der Datenstand steht auf der Karte unter „Quellen, Lizenzen und Datenstand“. Strukturdaten: Statistischer Datenkatalog Köln mit Stand 15.10.2026 (Angabe in der Datei) und Wegweiser Kommune mit Datenversion vom 15.10.2026, beide abgerufen am 10.11.2026. Neue Abrufe gibt es nur auf Freigabe, nicht im nächtlichen Lauf.

## Mitmachen

Hinweise auf falsche Orte oder Fehler bitte als [Issue](https://github.com/daimpad/ratsatlas-koeln/issues/new/choose); wie man am Code mitarbeitet, steht in [CONTRIBUTING.md](CONTRIBUTING.md).

Kontakt: contact@nozilla.de · [Impressum](https://nozilla.de/impressum/)
