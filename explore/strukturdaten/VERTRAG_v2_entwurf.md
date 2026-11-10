# Datenvertrag „Strukturdaten“ v2 – Entwurf zur Abstimmung

> Stand 10.11.2026 · Entwurf aus Köln für Bonn, Köln und Wuppertal; der Vertrag ändert sich nur gemeinsam · nicht freigegeben
> Grundlage: Vertrag 1.1 (`data/strukturdaten/meta.json`, TECHNIK.md „Strukturdaten“), Prompt Strukturdaten v0.1 (Abschnitte 3 und 5.2), `data/strukturdaten/zurueckgestellt.tsv`, `explore/strukturdaten/indikatoren_katalog.tsv`, Entscheidung „Datenvertrag v2“ vom 10.11.2026 (TECHNIK.md).

## 1. Ausgangslage

- v1.1 kennt die Typen `anzahl`, `anteil`, `quote`, `dichte`, `mittelwert`, `kategorie`. Flächenfarbe nur für relative Größen, Farbskala sequenziell; Anzahlen nur im Panel.
- Vorhandene Daten betrifft v2 nur an zwei Stellen: `ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre` (vorläufig `quote`, 24 Zeilen in `gesamtstadt.tsv`) und 33 Zellen „k.A.“ im Wegweiser-Export (je Kommune `arbeitslose-an-den-svb` 2006 und `bevoelkerungsentwicklung-…` 2006–2015), die in `gesamtstadt.tsv` fehlen und nur im Metatext stehen.

## 2. Einordnung der 39 Indikatoren

Die 39 Kölner Indikatoren in `zurueckgestellt.tsv` stehen nur im Blatt Katalog (`code_datenblatt` leer), keiner hat Werte im Blatt Daten. Die 2 Wegweiser-Indikatoren dort (Datenhalter Nexiga GmbH, Lizenzfrage) sind nicht Gegenstand von v2. „vermutlich“: Bezug oder Definition steht nicht im Katalog.

| Klasse | n | Indikatoren (`koeln_…`) | Typ in v2 |
|---|---|---|---|
| Wanderungsraten, Bezug nicht benannt (Format „andere“ neben „abs“; vermutlich je 100 Einwohner*innen wie A0282S, A0283S) | 13 | A0005S, A0009S, A0014S, A0018S, A0287S, A0407S–A0414S | `quote` (v1), nach Bestätigung des Bezugs |
| Raten oder Quoten, Bezug unbekannt („andere“ neben „abs“, bei D0028S–D0030S auch „%“) | 5 | B0002S, B0021S, D0028S, D0029S, D0030S | v1-Typ nach Auskunft |
| Veränderungsraten | 3 | A0547S; A0008S (vermutlich, „zum Vorjahr“); A0548S (vermutlich, sonst `saldorate`, Frage 5) | `veraenderung` |
| Salden als Differenz von Anzahlen (nur „andere“) | 3 | A0006S, A0007S, A0016S | `saldo` |
| Saldo je Einwohner*innen (vermutlich) | 1 | A0279S | `saldorate` |
| Indizes (Bezug = 100) | 3 | D0046S und D0053S (Bund = 100), D0058S (Köln = 100) | `index` |
| Messwerte Klima und Rheinpegel (nur Gesamtstadt) | 7 | I0001A–I0007A | `messwert` |
| Geldsumme | 1 | D0054S (Mio. Euro) | `betrag` |
| Jahresdurchschnitt einer Anzahl (nur Gesamtstadt) | 1 | F0014S | `anzahl` (v1), Einheit „Anzahl (Jahresdurchschnitt)“ |
| unklar | 2 | A0012S (Name ohne Muster), A0542S (Billeter-Maß J) | offen |

Außerhalb der 39: `ww_bevoelkerungsentwicklung-ueber-die-letzten-5-jahre` → `veraenderung`, Einheit „% über 5 Jahre (Bezug: Endstand)“ (Nenner laut Wegweiser: aktueller Stand).

## 3. Vorschlag

**Mindestumfang:** `veraenderung` und `status` in `gesamtstadt.tsv`; beide betreffen vorhandene Werte. Die übrigen fünf Typen nur, wenn die Statistikstelle Werte dazu veröffentlicht (Frage 3).

**Neue Typen**

- `veraenderung`: Veränderung eines Bestands zwischen zwei Zeitpunkten in Prozent eines Bezugsstands, `100 × (B(t) − B(t−k)) / B(Bezug)`. Die Einheit nennt Zeitraum k und Bezugsstand (Anfangs- oder Endstand), etwa „% über 5 Jahre (Bezug: Endstand)“; der Metatext erläutert.
- `saldo`: Differenz zweier Anzahlen derselben Raumeinheit und desselben Zeitraums (Zugänge minus Abgänge, etwa Zuzüge − Fortzüge, Geburten − Sterbefälle). Einheit „Anzahl“.
- `saldorate`: Saldo je 100 oder je 1000 einer Bestandsgröße. Einheit „je 100 …“ bzw. „je 1000 …“ mit der Bestandsgröße. `zaehler_id` und `nenner_id` nur, wenn nachgerechnet.
- `index`: Wert im Verhältnis zu einer Bezugsgröße mit dem Wert 100. Die Einheit nennt die Bezugsgröße („Bund = 100“, „Köln = 100“).
- `messwert`: physikalische Messgröße einer Messstelle oder des Stadtgebiets (Jahresmittel, -summe oder Extremwert). Einheit physikalisch (Grad Celsius, cm, Liter pro Quadratmeter, Stunden); kein Bezug auf Bevölkerung oder Fläche.
- `betrag`: Geldsumme einer Raumeinheit. Einheit Währung mit Größenordnung („Mio. Euro“).

**Regeln**

- Aggregation: bei keinem neuen Typ, auch nicht bei `saldo` und `betrag`; Werte nur auf ihrer Originalebene (Summen könnten geheim gehaltene Werte offenlegen, `meta.json` `geheimhaltung_hinweis`).
- Flächenfarbe: `veraenderung` und `saldorate` divergierend mit Mitte 0, `index` divergierend mit Mitte 100. Die Mitte ist immer Klassengrenze; Quantilklassen getrennt unter und über der Mitte (abweichend von Prompt 5.2), je Seite eine Farbfamilie, farbfehlsichtigkeitsgeeignet; Legende mit der Einheit. Keine Flächenfarbe für `saldo` und `betrag` (absolute Größen wie `anzahl`) und `messwert` (gilt für eine Messstelle, nicht für Flächen).
- Panel: Wert mit Einheit; `veraenderung`, `saldo`, `saldorate` mit Vorzeichen, Zeitreihe mit Nulllinie; `index` als „[Wert] ([Bezugsgröße] = 100)“; `messwert` mit Messstelle laut Metatext.
- v1-Typen und ihre Regeln bleiben unverändert.

**Status in `gesamtstadt.tsv`**

- Neue Spalte `status` als letzte Spalte: `ok` (Wert vorhanden) oder `fehlt` (Zelle „k.A.“, `wert` leer). Eine Zeile je Zelle des Exports (Kommune × Indikator × Jahr); in Köln 540 statt 507 Zeilen.
- `jahre` in `indikatoren.tsv`: Jahre mit `status` `ok` (wie bisher). Der Satz „Ohne Angabe im Wegweiser …“ im Metatext und `meta.json` `gesamtstadt_ka` entfallen.

**Version, Kompatibilität, Umstellung**

- `vertrag_version` „2.0“ mit Eintrag in `vertrag_aenderungen`. Hauptversion, weil v1.1 zusagt, dass `gesamtstadt.tsv` nur Zeilen mit Wert enthält (`meta.json` `formate.wert`), und weil `typ` neue Werte erhält.
- Leseregeln, ab sofort auch für v1-Leser (Köln Phase 3, Bonn, Wuppertal): (1) Spalten nach Namen lesen, unbekannte ignorieren; (2) unbekannter `typ`: keine Flächenfarbe, keine Aggregation, im Panel als Text „Wert Einheit“ mit Metatext; (3) leeres `wert` ist kein Wert, nie 0; Anzeige nach `status`, ohne `status` „keine Angabe“; (4) ein Leser ohne (1)–(3) zeigt bei Hauptversion 2 keine Strukturdaten.
- Umstellung Köln nach Freigabe: zuerst die Leseregeln (Phase 3), dann `pipeline/strukturdaten.py` und `meta.json`.
- Die 39 bleiben in `zurueckgestellt.tsv`, bis Werte im Blatt Daten stehen und Typ und Bezug bestätigt sind. Voraussichtlich 19 davon brauchen keinen neuen Typ.
- `gesamtstadt.tsv` in allen drei Instanzen gleichzeitig umstellen, damit der Vergleich Bonn / Köln / Wuppertal übereinstimmt (Prompt Abschnitt 4).

## 4. Offene Fragen, die den Vorschlag blockieren

An Bonn und Wuppertal:

1. Typnamen und Definitionen: Zustimmung oder Gegenvorschlag? Gibt es dort Indikatoren, die weder zu v1 noch zu den neuen Typen passen?
2. Termin der gemeinsamen Umstellung von `gesamtstadt.tsv`: [Datum]

An die Statistikstelle (in die spätere fachliche Anfrage):

3. Werden die 39 Indikatoren im Blatt Daten veröffentlicht? Wenn nicht, genügt der Mindestumfang.
4. Bezug der Varianten „andere“ bei den 18 Indikatoren der ersten beiden Klassen (je 100, je 1000 Einwohner*innen oder andere Bezugsgröße)?
5. Definitionen: A0008S, A0547S, A0548S (Prozent, Zeitraum, Bezugsstand; A0548S Veränderungsrate oder Saldo je Einwohner*innen); A0279S (Bezug); A0006S, A0007S, A0016S (Personen); A0012S; A0542S.
