# Phase 2 – Datenpipeline (vorbereitet, ohne Abrufe)

Stand 04.11.2026 · Grundlage: `CLAUDE.md` 5.1, 7.2 und Entscheidungen in Abschnitt 9

## 1. Umgesetzt

| Teil | Datei | Inhalt |
|---|---|---|
| Abrufpolitik | `pipeline/abruf.py` | eine Verbindung, Abstand 2 s, Zeitfenster 22–6 Uhr, wachsende Pausen von 1 min bis 3 h, Beachtung von `Retry-After`, sofortiger Abbruch bei 401/403/404, User-Agent mit Projektadresse; **Sperre** ohne `RATSATLAS_STADT_INFORMIERT=ja` |
| SessionNet-Adapter | `pipeline/sessionnet.py` | Listen nur über `links.next`; ab dem zweiten Lauf inkrementell über `modified_since`, mit einem Tag Überlappung; Zusammenführung über die ID; Prüfung je Lauf, ob der Server den Filter anwendet; Abrufstatistik `data/export/abrufstatistik.tsv` |
| Bonner Datenmodell | wie oben | dieselben Rohdateien wie in Bonn. Die Beratungsdetails, die Bonn aus OParl-Lite bezog, werden aus den Kölner Sitzungen abgeleitet (Sitzung → TOP mit Nummer, Ergebnis, Öffentlichkeit). Fehlt in einer Beratung das Gremium, wird es aus der Sitzung übernommen und als `_organization_quelle: sitzung` markiert |
| Ausfall | wie oben | Ein Abbruch behält den letzten gültigen Stand und vermerkt den Fehler in `STAND.json` (`abruf_fehler`). Ein Vollabruf ersetzt den Stand nur, wenn er mindestens 90 % der bisherigen Objekte enthält (Bonner Regel) |
| Gebiete | `pipeline/geodaten.py` → `data/geo/` | 86 Stadtteile und 9 Stadtbezirke in WGS84, um 2 m vereinfacht; die Eigenschaften heißen wie in Bonn (`ortsteil`, `ortsteil_bez`, `bezirk`, `bezirk_bez`) |
| Straßenverzeichnis | wie oben | 5 162 Straßennamen, davon 360 mit mehreren getrennten Lagen (z. B. „Aachener Straße“ in Porz und in der Innenstadt), dazu 11 548 Kreuzungen; Namen ausgeschrieben („Str.“ → „Straße“) |
| Konfiguration | `pipeline/config.py` | Köln-Endpunkte, Quellenkennungen `oparl-koeln`, `geo-koeln`, `strassen-koeln`; `SITE_URL` koeln.ratsatlas.de; Schalter `ZUSATZTHEMEN`, alle aus; Bonner Abrufschritte melden ihren Kölner Ersatz |
| Tests | `tests/` | 10 Tests mit synthetischen Daten gegen einen lokalen Testserver: Paginierung, Inkrement, Zusammenführung, abgeleitete Beratungen, Sperre, Abbruch, Zeitfenster, `build.py` auf Kölner Rohdaten, Geodaten. Alle bestanden |

## 2. Grenzen und offene Punkte

1. **Nicht gemessen:** Ob Köln `modified_since` und `limit` unterstützt, ist noch offen (Phase-1-Messung nach Information der Stadt). Der Adapter funktioniert auch ohne Filter, ruft dann aber jedes Mal alles ab. Die Abrufstatistik zeigt das in der Spalte `filter_wirksam`.
2. **Gelöschte Objekte:** Sie bleiben mit `deleted` im Rohstand, `build.py` filtert sie heraus. Ob SessionNet gelöschte Objekte überhaupt meldet, ist offen.
3. **Stufe A:** `location.subLocality` wird übernommen, aber noch nicht auf die Stadtteilfläche abgebildet (Phase 3).
4. **Stufe B, vorläufig:**
   - Stadtbezirke werden im Titel nicht erkannt, weil acht Bezirksnamen zugleich Stadtteilnamen sind.
   - Bebauungsplan-Nummern werden nicht erkannt, bis Geltungsbereiche und Nummernschema vorliegen.
   - Vier Straßen fehlen im Verzeichnis, weil ihre Abschnitte unter den Mindestlängen liegen.
5. **Noch auf Bonn ausgerichtet:** Export, Prüfung (`check`), Verifikation und Seite (Phase 3/4). `python -m pipeline all` führt deshalb vorerst nur `fetch` und `build` aus.
6. **Workflows:** Sie bleiben inaktiv. Der tägliche Lauf entsteht in Phase 5.
