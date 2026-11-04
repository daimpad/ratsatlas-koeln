# Phase 4 – Frontend (Bericht)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` 5.4, 7.4 und Entscheidungen in Abschnitt 9 · Prüfung mit synthetischen Testdaten (`tools/testdaten.py`, gekennzeichnet „[Testdaten]“), keine Daten der Stadt

## 1. Umgesetzt

| Teil | Inhalt |
|---|---|
| Export (4a) | Die Exporte liegen in `data/export/koeln/`: je Stadtteil, je Stadtbezirk und ohne Ortsbezug, dazu Suche, Zeitleiste, Feeds, Kalender, GeoJSON und DCAT. Stadtweit kommen Audits hinzu (Geokodierung, Prozess, Zeit, Themen, Bebauungspläne) und `stichprobe_geokodierung.tsv` mit bis zu 50 Vorlagen je Methode. Bonner Zusatzthemen entstehen nur nach Freigabe. `index.json` meldet Stadt, Funktionen, Testdaten und Abruffehler. |
| Texte und Lizenzen | Feeds, Kalender, DCAT, Glossar, Gebiets-, Begriffs- und Feedseite sowie Datenschutz, Tour und Fehlerseite sind auf Köln umgestellt. Die Namensnennung „Datenquelle: Stadt Köln – offenedaten-koeln.de“ steht überall. Es gibt keine Verweise auf OParl-Lite oder auf Bonner Dienste mehr; ein Test prüft das für Feeds, Suche, Zeitleiste, GeoJSON und DCAT. |
| Webseite (4b) | Marke „Ratsatlas Köln“. Die Startansicht zeigt ganz Köln mit 9 anklickbaren Stadtbezirken und dann den Stadtteilen. Die Anzeige sagt „Stadtteil“ statt „Ortsteil“ sowie „Vorlage“ und „Dienststelle“. Die Kölner Methoden sind in einfachen Worten erklärt. Ein Hinweis erscheint bei Testdaten und, falls der Abruf ausfällt, beim Datenstand. |
| Zusatzthemen | Haushalt, Themenseiten, Prozesse/Soll, Ratsassistent, Einfache Sprache, „Alle Wege“, Volltextsuche und die Technikseite sind per `data-funktion` und `config.ZUSATZTHEMEN` ausgeblendet. Sie bleiben im Code und erzeugen keine Anfragen. |
| Akteure | Für die Kölner Vorlagenarten gibt es vorläufige Muster. `originatorOrganization` gilt als belegt, wo vorhanden. Sonst wird die Partei aus dem Titel („Antrag der …-Fraktion“) oder aus der Vorlagenart („FDP Antrag nach § 3“) abgeleitet. Bonner Wählergruppen sind entfernt. |
| Kartenkacheln (4c) | Rahmen auf das Kölner Stadtgebiet (`rahmen.py`, `app.js`, Test). Der OSM-Ausschnitt aus Protomaps wurde einmal geladen (3 652 Vektorkacheln, 85 Anfragen, 105 MB) und lokal zu grauen Kacheln gezeichnet, aber nicht ins Repository übernommen. Im Betrieb entstehen sie mit `kacheln.yml` im Branch `kacheln` (Phase 5). |
| WCAG 2.1 AA (4d) | axe-core 4.10.2 (Regeln wcag2a/aa, wcag21a/aa) auf Start, Gebiet, Vorgang, Zeitleiste, Über-Dialog, Menü „Mitmachen“, Gebiete, Stadtteilseite, Begriffe, Feeds, Datenschutz und 404: **0 Verstöße**; in Handy-Breite (Pixel 7) ebenso 0. Tastatur: Die Tab-Reihenfolge der Startseite ist logisch, jedes Ziel hat einen sichtbaren Fokus, ausgeblendete Funktionen sind nicht erreichbar. Protokolle liegen in `inventur/phase4/`. |

Tests: 34, alle bestanden.

## 2. Grenzen der Prüfung

- **Umfang von axe:** axe prüft nur automatisierbare Kriterien. Nicht geprüft habe ich die Bedienung mit Bildschirmleser, die Vergrößerung auf 400 % und die Verständlichkeit der Texte. Bonn hatte das geprüft; für Köln steht es noch aus.
- **Testdaten:** Die Prüfung lief mit synthetischen Daten. Länge, Vielfalt und Sonderfälle echter Kölner Vorlagen fehlen.

## 3. Offen

1. **Federführende Dienststelle:** Sie wird noch nicht ermittelt; die Seite zeigt „noch nicht ermittelt“. Dafür braucht es `underDirectionOf` oder den PDF-Kopf, also den Abruf.
2. **Nach der Messung der API:**
   - Vorlagenarten und Fraktionsliste der Wahlperiode ab 2025
   - Gremienbahnen der Zeitleiste (vorläufig nur Rat und Hauptausschuss)
3. **Ohne Link:** Für die Seite der Stadt zu Anregungen und Beschwerden fehlt noch ein Link; ich nenne ihn erst, wenn er geprüft ist.
4. **Zweiter Lauf:** Vorschaubild für soziale Netzwerke; dafür wird das Bonner Bild nicht ausgeliefert.
5. **Phase 5:** Technikseite, Workflows und Plesk.
6. **Bonner Bezeichnungen intern:** Interne Namen wie `BONN` (Pfadkonstante), `anteil_bonn` und `ganz-…` sind aus Bonn übernommen. Sichtbar ist davon nichts, umbenannt werden sie mit dem gemeinsamen Kern.
