# Checkliste Veröffentlichung (für den Auftraggeber)

Stand 04.11.2026. Zugangsdaten zu Netcup und Plesk bleiben beim Auftraggeber und gehören nicht ins Repository (CLAUDE.md 6).

## A. GitHub (einmalig)

1. **GitHub Pages** – Repository → Settings → Pages → Source: „GitHub Actions“.
2. **Variablen** – Settings → Secrets and variables → Actions → Variables:
   - `SITE_URL` = `https://koeln.ratsatlas.de/`
   - `RATSATLAS_KONTAKT` = Kontaktadresse für den User-Agent (z. B. eine Projekt-Mailadresse)
   - `RATSATLAS_STADT_INFORMIERT` = `ja` – **erst, wenn die Stadt informiert ist** (Anfrage `explore/ANFRAGE_stadt_koeln.md`). Vorher endet der tägliche Lauf ohne Abruf und ohne Veröffentlichung.
3. **Benachrichtigung** – Profil → Settings → Notifications → Actions: „Notify on failed workflows“.

Der Branch `deploy` entsteht erst mit dem ersten erfolgreichen Lauf von `pages.yml` mit Daten; erst danach lässt sich Schritt B.3 abschließen.

## B. Netcup / Plesk

1. **Domain** – Subdomain `koeln.ratsatlas.de` anlegen; DNS (A/AAAA) auf das Webhosting zeigen lassen.
2. **TLS** – SSL/TLS-Zertifikate → Let's Encrypt für `koeln.ratsatlas.de`; „HTTP auf HTTPS umleiten“ einschalten.
3. **Git** – Websites & Domains → Git → Repository hinzufügen:
   - Remote-Repository: `https://github.com/daimpad/ratsatlas-koeln.git`, Branch `deploy`
   - Bereitstellungsmodus: automatisch; Zielverzeichnis: Dokumentstamm (`httpdocs`)
   - keine zusätzlichen Bereitstellungsaktionen (die Seite ist fertig gebaut)
4. **Webhook** – die von Plesk angezeigte Webhook-Adresse in GitHub eintragen: Repository → Settings → Webhooks → Add webhook, Content type `application/json`, Ereignis „Just the push event“.
5. **Apache und `.htaccess`** – Der Branch enthält `.htaccess` (Komprimierung, Zwischenspeicher, Sicherheitskopfzeilen, CORS für Feeds und JSON). In Bonn lieferte nginx statische Dateien an Apache vorbei aus, ohne diese Kopfzeilen. Deshalb unter „Apache & nginx-Einstellungen“ entweder „Intelligente Verarbeitung statischer Dateien“ ausschalten oder die Kopfzeilen als zusätzliche nginx-Direktiven setzen.

## C. Nach der ersten Veröffentlichung

1. Workflow **Live-Prüfung** (`live.yml`) auf Knopfdruck starten: Er prüft Hauptadresse, Spiegel, Canonical, Datenstand und Kopfzeilen.
2. Wenn alles grün ist: in `live.yml` die Auslöser `workflow_run` und `schedule` einschalten (Pull Request).
3. Datenschutzerklärung und Impressum für die Hauptadresse prüfen (`site/datenschutz.html`).
