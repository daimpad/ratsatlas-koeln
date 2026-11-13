# Strukturdaten – Phase 0 (Exploration, 10.11.2026)

Bericht und Anlagen der Exploration zum Prompt „Strukturdaten als Kontext- und Kartenebene“ v0.1. Die Ergebnisse von Phase 1 (Datenvertrag „Strukturdaten v1“) stehen in `data/strukturdaten/`, der Code in `pipeline/strukturdaten.py`.

- `BERICHT_strukturdaten_phase0.md`: Bericht mit den Entscheidungen des Auftraggebers vom 10.11.2026 (Abschnitt 9).
- `audit_quellen.tsv`: Quellen und Prüfstand; `audit_abruf.tsv`: alle Abrufe der Phase (Adresse, Zeit, Status, Größe, SHA-256).
- `NACHRICHT_wegweiser.md`: Entwurf vom 10.11.2026, Versand durch den Auftraggeber.
- Ein Hinweis an die Statistikstelle zur Geheimhaltung liegt außerhalb des Repositorys (Versand durch den Auftraggeber).
- `laden.py`: gedrosselter Einzelabruf über `explore/abruf.py` (Freigabe vom 10.11.2026: höchstens 3 Anfragen an offenedaten-koeln.de, 15 an wegweiser-kommune.de; genutzt 3 und 7).
- `verifikation.py`: Strukturdaten Phase 4 (13.11.2026), Stichprobe von 20 veröffentlichten Werten und 6 Werten des Wegweisers gegen die Quelle (ohne Netz, ohne Import der Pipeline; Aufruf im Kopf der Datei); Ergebnis `data/strukturdaten/audit_verifikation.tsv`, Bericht Abschnitt 11.
- `VERTRAG_v2_entwurf.md`: Entwurf Datenvertrag v2 zur Abstimmung mit Bonn und Wuppertal (10.11.2026, nicht freigegeben).
- übrige TSV-Dateien: Anlagen des Berichts (Abschnitt 10). Die heruntergeladenen Rohdateien liegen nicht im Repository.

Quellen der Anlagen: Statistischer Datenkatalog Köln, Stadt Köln, Amt für Stadtentwicklung und Statistik, Datenlizenz Deutschland – Namensnennung – Version 2.0 (https://www.govdata.de/dl-de/by-2-0), Datensatz https://open.nrw/dataset/statistischer-datenkatalog-koln-k, Stand 15.10.2026 – Werte unverändert, Auswertungen abgeleitet; Zensus 2022, © Statistisches Bundesamt (Destatis), dl-de/by 2.0 (Vergleich je Stadtteil); Wegweiser Kommune, Bertelsmann Stiftung, wegweiser-kommune.de, CC0 1.0; Stadtteile und Stadtbezirke: Datenquelle: Stadt Köln – offenedaten-koeln.de, dl-de/zero 2.0.
