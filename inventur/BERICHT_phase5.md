# Phase 5 – Repository und Deployment (Bericht)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` 7.5 und Entscheidungen in Abschnitt 9

## 1. Umgesetzt

| Teil | Inhalt |
|---|---|
| Dokumentation | `README.md` neu (Ziel, Herkunft aus `daimpad/ratsatlas-bonn` @ `9eea7ea`, Quellen, Lizenzen, Grenzen, Datenstand). Dazu `TECHNIK.md` (Pipeline, Abrufpolitik, Geokodierung, Workflows), `CONTRIBUTING.md`, Issue-Vorlagen für Köln, `NOTICE` mit dem neuen Namen des Bonner Repositorys und `docs/PLESK.md` (Checkliste für GitHub und Plesk). |
| `pages.yml` | Hauptlauf täglich um 1:37 UTC, bei Push auf `main` und auf Knopfdruck. **Der Abruf bleibt gesperrt**, bis die Repository-Variable `RATSATLAS_STADT_INFORMIERT` den Wert `ja` hat; außerhalb von 22–6 Uhr wird er übersprungen. Beides gilt als „übersprungen“, nicht als Fehler. Ohne Daten der Stadt veröffentlicht der Lauf nichts, Testdaten nie. Mit Daten schreibt er Branch `deploy` (ohne Datenpaket, mit `.htaccess`) und den Spiegel auf GitHub Pages; der Canonical zeigt auf `SITE_URL`. |
| `kacheln.yml` | Aktiv: vierteljährlich, auf Knopfdruck und bei Pull Requests zu `pipeline/kacheln/`. Erzeugt die grauen Kacheln für Köln im Branch `kacheln`. Ein lokaler Probelauf ergab 11 216 Kacheln mit 47 MB. |
| `live.yml` | Live-Prüfung für Köln (Hauptadresse, Spiegel, Canonical, Datenstand, Kopfzeilen), vorerst nur auf Knopfdruck. |
| Datenpaket | `pipeline/paket.py` erzeugt `ratsatlas-koeln-export.zip` mit Exporten, Audits, Stichprobe, Abrufstatistik, Geodaten, Lizenzen und Berichten. Rohdaten, Volltexte und PDFs sind nicht enthalten. |
| Technikseite | Neu für Köln: Sie liest Schritte, Workflows und Quellen aus dem Repository und erklärt sie. |
| Korrektur aus Phase 4 | Canonical und `og:url` in `index.html`, `404.html` und `datenschutz.html` verwiesen noch auf den Bonner Spiegel. |

Tests: 38, alle bestanden. Neu ist `tests/test_workflows.py`: Jede Erklärung ist vorhanden, der Hauptlauf ist gesperrt und veröffentlicht keine Testdaten, die Technikseite enthält keine Bonner Texte.

## 2. Für den Auftraggeber (`docs/PLESK.md`)

1. GitHub: Pages auf „GitHub Actions“ stellen; Variablen `SITE_URL` und `RATSATLAS_KONTAKT` anlegen, `RATSATLAS_STADT_INFORMIERT` erst nach der Information der Stadt.
2. Plesk: Subdomain, TLS, Git aus Branch `deploy`, Webhook in GitHub, Behandlung statischer Dateien durch nginx (Kopfzeilen).
3. Nach der ersten Veröffentlichung: `live.yml` von Hand starten, dann dessen Auslöser einschalten.

## 3. Offen

- **Branch `deploy`:** Er entsteht erst mit dem ersten Lauf mit Daten, also erst nach der Information der Stadt. Plesk lässt sich deshalb erst dann vollständig einrichten.
- **Verifikation gegen das Kölner RIS** (Phase 6): `python -m pipeline verify` ist bis dahin abgeschaltet.
