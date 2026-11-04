# Phase 0 – Kopie und Inventur (Bericht)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` (Prompt v0.1), Abschnitt 7.0 · Noch keine Köln-Logik

## 1. Durchgeführt

- Kopie aus `daimpad/allris-test` @ `9eea7ea` (03.11.2026) per `git archive`, ohne Historie und ohne `data/`. Übernommen wurden `pipeline/`, `site/`, `deploy/`, `.github/`, `.claude/` sowie README, TECHNIK, CONTRIBUTING, LICENSE und requirements. Die Bonner Berichts-, Phasen-, Test- und Evaluationsverzeichnisse wurden nicht übernommen (Entscheidung vom 04.11.2026).
- Alle Workflows liegen in `.github/workflows-inaktiv/` und laufen deshalb nicht. Das gilt auch für `static.yml`, das das ganze Repository auf Pages veröffentlicht hätte.
- `CLAUDE.md` enthält jetzt den Kölner Prompt v0.1 mit den Entscheidungen (Abschnitt 9). `NOTICE` dokumentiert die Herkunft.
- Inventur und Fundstellen sind reproduzierbar über `inventur/skripte/` und `inventur/*.tsv`.

## 2. Zahlen

| Einordnung | Dateien | davon Code-Zeilen in `pipeline/` und `site/`¹ |
|---|---|---|
| generisch | 35 | 1 566 (9 Dateien) |
| Bonn-spezifisch, anpassen | 58 | 10 893 (45 Dateien) |
| Bonn-Zusatzthema, deaktivieren | 39 | 9 994 (37 Dateien) |
| entfernen | 2 | – (`static.yml`, Bonner `CLAUDE.md`, bereits ersetzt) |

¹ ohne `site/vendor/`. Die Fundstellenliste umfasst 1 217 Zeilen in 95 Dateien. Darunter sind 105 Bezüge auf OParl-Lite und 29 auf `SITE_URL`/`PAKET_URL`. Die übrigen Treffer sind Bonner URLs, Ortsteil- und Bezirksnamen sowie der Name „Bonn“ selbst. Etwa die Hälfte aller Treffer liegt in zehn Dateien: `site/app.js`, `site/index.html`, `TECHNIK.md`, `pipeline/publish.py`, `pipeline/verify.py`, `site/chat/tools.js`, `pipeline/config.py`, `README.md`, `live.yml` und `pipeline/kontext.py`.

## 3. Strukturelle Befunde

1. **Konfiguration:** Quellen, Lizenzen, Pfade, `SITE_URL` und Pilot-Ortsteil liegen gebündelt in `pipeline/config.py`. Daneben gibt es feste Bonner Werte in `site/app.js`, `site/timeline.js` (`PILOT_GREMIEN`) und den Workflows.
2. **Abhängigkeit von OParl-Lite:** `fetch.py`, `build.py`, `process.py` und `volltext.py` beziehen Beratungen, TOPs, Ergebnisse und Volltexte aus OParl-Lite. In Köln kommen diese Angaben direkt aus der OParl-API, die Volltexte nur aus PDFs. Der SessionNet-Adapter muss deshalb dieselben Rohdateien erzeugen (Prompt 5.1: Bonner Modell unverändert).
3. **Gebietsbegriff:** „Ortsteil“ kommt in Pipeline und Seite 475-mal vor. Die Eigenschaften `ortsteil_bez` und `bezirk_bez` sind in `site/app.js` fest verdrahtet, der Exportpfad heißt `data/export/bonn/`. Für Köln schlage ich vor, die interne Benennung zu behalten und die Anzeige auf „Stadtteil“ umzustellen. Die Kölner Geodaten würden dafür beim Laden auf diese Eigenschaften abgebildet. Das hält die Änderungen im Frontend klein.
4. **Keine Schalter für Zusatzthemen:** Der Code hat keinen Mechanismus, um Zusatzthemen abzuschalten. Prompt 5.4 verlangt „per Konfiguration abschaltbar“. Ein solcher Schalter muss also neu entstehen, in `config.py` und als Angabe im Export für die Seite.
5. **Keine Tests:** Mit den Bonner Tests (Bonner Fixtures) fehlt jede Testbasis. Kölner Tests müssen ab Phase 2 mitwachsen.
6. **Soll-Modell:** `soll.py`, `prozessarten.py`, `mitwirken.js` und `prozesse.js` hängen an der Bonner Zuständigkeitsordnung (`data/soll/`, nicht übernommen). Sie sind deshalb als „deaktivieren“ eingeordnet, nicht als „anpassen“.

## 4. Offene Einordnungen (Ihre Entscheidung)

Diese fünf Funktionen nennt Prompt 5.4 nicht ausdrücklich. Ich habe sie vorläufig als „anpassen“ eingeordnet:

- `einfachseite.py`: Seite in Einfacher Sprache
- `kurzfassung.py`: Kurzfassungen per Sprachmodell; nach Abschnitt 2 zulässig, braucht aber Volltexte
- `site/beteiligung.js`: „Mitmachen“; in Köln wären das § 24 GO, Einwohnerfragestunde und „Meinung für Köln“
- `besetzung.py`: Gremienbesetzung; erzeugt zusätzliche Abrufe
- `site/og-image.jpg`: Inhalt prüfen und für Köln neu erstellen

## 5. Vorschlag Phase 1 (Exploration, nur `explore/`)

Die Stadt ist noch nicht informiert. Deshalb schlage ich vor:

1. Ich schreibe die Messskripte (API-Kennzahlen, Stichprobe ≥ 500, PDF-Köpfe) mit Drossel, User-Agent und Cache, führe sie aber **nicht** aus.
2. Ich entwerfe die Anfrage an die Stadt (Lizenz, Abrufrate, Massenexport) zur Versendung durch Sie.
3. Die Geodaten liegen laut mandari im selben Netz wie die OParl-API (194.8.223.0/24). Ich würde sie deshalb nur nach Ihrer Freigabe einmalig laden; es sind wenige Dateien.
