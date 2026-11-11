"""SessionNet-Adapter: Abruf der Kölner OParl-API ins Bonner Rohdatenformat (CLAUDE.md 5.1).

Erzeugt dieselben Rohdateien wie der Bonner Abruf, damit build.py, Export und Seite unverändert bleiben:
- `papers.jsonl`      Vorlagen (OParl-Objekte), zusammengeführt über die ID; gelöschte bleiben mit `deleted`
- `organizations.json` und `verwaltungsbereiche.json`
- `meetings.json`     Sitzungen im Bonner Kurzformat; vollständige Sitzungen mit TOPs in `meetings_roh.jsonl`
- `legislative_terms.json`
- `beratungen.jsonl`  Beratung → Sitzung und TOP (in Bonn aus OParl-Lite; in Köln abgeleitet, weil `consultation`
                      direkt auf `meeting` und `agendaItem` verweist und die Sitzungen ihre TOPs enthalten)

Abruf: Listen nur über `links.next`, nach dem ersten Lauf inkrementell über `modified_since` (Zustand in
`zustand_abruf.json`, mit einem Tag Überlappung). Parameter werden URL-kodiert gesendet (`quote(wert, safe="")`): Köln
übergeht Zeitwerte unkodiert („+“ wird dort zum Leerzeichen, gleiche Seite wie ohne Filter) und wendet sie kodiert an
(Stufe 2, 08.11.2026, explore/BERICHT_phase1.md Abschnitt 6); das ersetzt für Köln die Annahme „Parameter ohne
URL-Kodierung“ vom 05.11.2026 (aus anderen SessionNet-Installationen: HTTP 404 bei %3A/%2B). links.next gibt den
Filterwert unkodiert zurück (`…?page=2&modified_since=2026-11-05T11:29:44+00:00`) und wird daher vor dem Folgen
normalisiert (folgeadresse(): Query-Teil je Parameter kodiert neu aufgebaut, Schema, Host und Pfad unverändert, ein
anderer Host als der der Liste wird nicht gesendet). Offen (ungemessen): ob Köln auf Seite 2 mit kodiertem Filter
weiter filtert; die Abrufstatistik prüft je Lauf über alle Seiten, ob der Filter wirkt (`filter_wirksam`).
Seitengröße: `limit=100` (`config.ABRUF_SEITENGROESSE`, RATSATLAS_LIMIT; Köln, Stufe 2: 100 Vorlagen in 5,07 s, `next`
mit `limit=100`) an der ersten Listenadresse; trägt links.next ihn nicht, wird er angehängt. Alle seitenbezogenen
Grenzen gelten in Objekten und werden mit der tatsächlichen Seitengröße g des Laufs (größte gelesene Seite) in Seiten
umgerechnet; liefert der Server weniger als verlangt, gilt das.
Schutz gegen Endlosschleifen: Abbruch, wenn links.next auf eine in diesem Lauf gelesene Seite zeigt (normalisierte
Adresse), eine Seite nur Kennungen bringt, die in diesem Lauf schon kamen, eine Seite keine neuen Kennungen bringt (in
einer Fortsetzung bis zur erlaubten Seitenverschiebung, siehe unten), ein inkrementeller Lauf mehr als
`config.ABRUF_MAX_OBJEKTE` / g Seiten liest oder ein Vollabruf über seine Fortsetzungen hinweg mehr als
`config.ABRUF_MAX_OBJEKTE_GESAMT` / g Seiten erreicht (Art `liste`). Erreicht ein Vollabruf `config.ABRUF_MAX_OBJEKTE` /
g Seiten in einem Lauf (Höflichkeitsgrenze je Nacht; eine Fortsetzung zählt neu), endet der Lauf wie am Ende des
Zeitfensters mit Fortsetzung in der nächsten Nacht (Art `obergrenze`, kein Listenfehler, kein Sperrverdacht; in
derselben Nacht kein weiterer Lauf), sofern er über die wiederholte Seite einer Fortsetzung hinaus neue Objekte gelesen
hat (sonst Art `liste`: die Fortsetzung käme nie voran).
Ende der Liste: `links` oder `links.next` fehlt oder ist leer (null, "", [], {}; SessionNet ist PHP). Ob der Server
den Filter anwendet, wird je Lauf geprüft und in der Abrufstatistik vermerkt (auch bei einem Abbruch, aus den bis dahin
gelesenen Seiten). Ein inkrementeller Lauf prüft jede Seite: Enthält sie Objekte mit lesbarem `modified` vor
modified_since (die Überlappung von einem Tag ist dort schon abgezogen; Löschungen mit `deleted: true` ausgenommen, sie
können ein altes `modified` tragen), wendet der Server den Filter nicht an. Je Liste:
- papers: Abbruch nach dieser Seite (Art `filter`, „Zeitfilter auf Seite N nicht angewandt“; zählt wie ein
  Listenfehler), statt bis zum Fensterende die ganze Liste zu lesen. Seite 1 der Vorlagen in Kölner Form löst das nicht
  aus (Stufe 2: kodiert keine Vorlage unter der Grenze); Folgeseiten sind ungemessen.
- meetings (Entscheidung 10.11.2026: „Ignoriert der Server den Zeitfilter, werden alle Sitzungen jede Nacht neu
  gelesen“, Runde 20): Der Lauf liest die Sitzungen nach dieser Seite im selben Lauf vollständig, neu ab Seite 1 ohne
  modified_since (eine Anfrage mehr). Er folgt nicht links.next der gefilterten Seite: Ob Köln den Filter auf
  Folgeseiten ebenso übergeht und die Seitengrenzen mit und ohne Filter gleich sind, ist ungemessen, und ein
  unbemerkt doch gefilterter „Vollabruf“ ersetzte den Stand durch einen Teil (unter 90 % fiele es auf, darüber nicht).
  Der Neustart sendet dieselben Anfragen wie ein Vollabruf dieser Liste (RATSATLAS_VOLLABRUF=meetings) und gilt wie
  einer: 90-%-Regel gegenüber dem Stand (Art `leer`, Abbruch des Laufs; Meldung mit Anlass und Abhilfe
  RATSATLAS_KUERZER_ANNEHMEN=meetings), der Stand wird ersetzt, nicht zusammengeführt; beenden ihn das Zeitfenster
  oder die Grenze je Lauf, folgt die Fortsetzung in der nächsten Nacht. Die Seiten mit Zeitfilter zählen zur Grenze je
  Lauf (höchstens config.ABRUF_MAX_OBJEKTE / g Seiten je Liste und Nacht; ist sie mit ihnen schon erreicht, Art
  `obergrenze` ohne weitere Anfrage und ohne Fortsetzung), nicht zu den Seiten des Vollabrufs (Gesamtgrenze,
  Fortsetzung). Jede Nacht, nicht jeder Lauf: Sind die Sitzungen in dieser Nacht schon gelesen (Zustand `meetings`,
  Beginn des letzten erfolgreichen Lesens, oder `meetings` in STAND.json, sein Ende, auch das einer Fortsetzung;
  weniger als SPERRE_GLEICHE_NACHT zurück; nicht für lokale Testserver; _in_dieser_nacht_gelesen), liest ein weiterer
  Lauf (Push auf main im Zeitfenster, Knopfdruck) sie nicht noch einmal vollständig: mit Vermerk
  ohne Anfrage, sonst nach dem Befund (k Seiten); letzter gültiger Stand, Zeile `übersprungen` in der Abrufstatistik,
  keine Warnung in STAND.json (_schon_gelesen). Kein Listenfehler, keine Pause, keine
  Warnung in `abruf_warnungen` (die Sitzungen sind aktualisiert); Warnung „Zeitfilter bei Sitzungen nicht angewandt,
  Sitzungen vollständig gelesen“ im Log und in der Abrufstatistik (`ok; …`, modus „voll, Zeitfilter nicht
  angewandt“, filter_wirksam „nein“ aus den Seiten mit Zeitfilter, `anfragen` mit ihnen). Der Befund steht im Zustand
  (`meetings_ohne_zeitfilter` mit `zeit` und `meldung`, wie bis Runde 19), wird aber nur noch vermerkt, nicht
  ausgewertet: Jede Nacht beginnt die Liste wieder mit Zeitfilter. Wendet der Server ihn wieder an, bleibt der Lauf
  inkrementell und der Vermerk entfällt (ebenso nach einem vollständigen Abruf, auch einer Fortsetzung). Ein Vermerk
  aus älterem Code (bis Runde 19 übersprangen die Folgenächte die Liste ohne Anfrage) ändert nichts mehr; eine
  Warnung „Sitzungen nicht aktualisiert“ in STAND.json entfällt mit der nächsten Aktualisierung der Sitzungen.
  Mehranfragen je Nacht, solange der Server den Filter übergeht: ⌈M / g⌉ Seiten ohne Filter zusätzlich zu den k
  Seiten mit Filter bis zum Befund (meist k = 1; M Sitzungen insgesamt, ungemessen; g Objekte je Seite, 100); ein
  weiterer Lauf in derselben Nacht 0 (mit Vermerk) bzw. k.
- organizations: immer ohne Zeitfilter, vollständig (kleine Liste; Münster lehnt modified_since bei organization mit
  HTTP 401 ab, explore/ergebnisse/sessionnet_befunde.tsv; Umfang in Köln misst Stufe 3), keine Filterprüfung. Weil sie
  vor den Vorlagen kommen, beendet ein Vollabruf unter 90 % des Stands (Art `leer`) dort nur diese Liste: letzter
  gültiger Stand, Warnung in `abruf_warnungen`, die Vorlagen laufen weiter. Abhilfe, wenn die kürzere Liste stimmt:
  ein Lauf mit RATSATLAS_KUERZER_ANNEHMEN=organizations (Komma-Liste aus LISTEN; nimmt für die genannten Listen in
  diesem Lauf einen kürzeren Vollabruf an, vermerkt im Log und in der Abrufstatistik; ausdrücklich, nie Vorgabe; einen
  Vollabruf ohne Objekte nie, auch keinen nur mit gelöschten Objekten). Die 90-%-Prüfung der daraus abgeleiteten
  Beratungen entfällt nur, wenn für papers oder meetings tatsächlich ein kürzerer Stand angenommen wurde, nicht schon,
  weil die Liste genannt ist: in diesem Lauf oder in einem früheren, der vor den Beratungen abbrach (Vermerk
  `beratungen_kuerzer_erlaubt` im Zustand mit Zeit und Listen; entfernt erst, wenn beratungen.jsonl geschrieben ist).
  Einen leeren Beratungsstand nimmt sie bei einem bisherigen Stand über 0 nie an.
Warnungen der Nebenlisten stehen in STAND.json unter `abruf_warnungen` je Liste (`{"meetings": {"zeit", "meldung"},
"organizations": {…}}`), nicht in `abruf_hinweis`: Ein Abbruch einer anderen Liste (_abbruch_vermerken) und ein
vollständiger Lauf lassen sie stehen; entfernt wird die Warnung einer Liste erst, wenn diese Liste wieder regulär
aktualisiert wurde. export.py übernimmt sie in index.json (`meta.abruf_warnungen`), die Seite zeigt sie im Datenstand.
Seit Runde 20 schreibt nur noch die Liste der Organisationen eine Warnung (Art `leer`); eine Warnung der Sitzungen aus
älterem Code bleibt lesbar und entfällt mit ihrer nächsten Aktualisierung.
Offen: Lehnt ein Server modified_since mit HTTP 401 ab (Münster bei organization und agendaitem), wertet die Pipeline
das als Nacht mit möglicher Sperre (Art `http`, SPERRE_HTTP); bei den Sitzungen hieße das jede Nacht einen Abbruch auf
ihrer ersten Seite (die Vorlagen sind dann schon gelesen, die Beratungen nicht abgeleitet) und nach drei Nächten sieben
Tage Pause, auch für die Vorlagen (nicht umgebaut; vor der Freigabe messen).

Ein Vollabruf, der am Ende des Zeitfensters oder durch einen Fehler abbricht, wird in der nächsten Nacht fortgesetzt
(`<liste>_fortsetzung` im Zustand mit dem Zeitpunkt `gespeichert` und der normalisierten Folgeadresse, Teilstand in
`<datei>.teil.jsonl`), und zwar eine Seite vor der Stelle, an der er abbrach (eine Anfrage mehr): Wurden zwischen den
Nächten bis zu einer Seite (g, bei 100 je Seite 100) gelesener Vorlagen gelöscht, rücken die folgenden nach vorn und
gingen sonst verloren; bei mehr Löschungen können Vorlagen bis zum nächsten Vollabruf fehlen. Köln liefert die Vorlagen
neueste zuerst und ohne Gesamtzahlen (Stufe 1, 07.11.2026): Neue Vorlagen zwischen zwei Nächten verschieben die Seiten
nach hinten, Seiten der Fortsetzung bringen dann schon gelesene Vorlagen (zusammengeführt über die Kennung; die
wiederholte Seite zählt ebenso). Solche Seiten gelten bis zur erlaubten Seitenverschiebung nicht als Schleife: 100
Vorlagen je angefangenem Tag seit `gespeichert`, höchstens 1000 (`verschiebung_erlaubt`; nach ausgelassenen Nächten,
sieben Tagen Pause oder einem Retry-After entsprechend mehr), aufgerundet auf Seiten zu g (bei 25 je Seite 4 Seiten je
Tag, bei 100 eine), also bis zu 99 neue Vorlagen je Tag (die wiederholte Seite zählt mit). Bricht eine Fortsetzung
ab, bevor sie die verschobene Zone verlassen hat, bleibt `gespeichert` (die Verschiebung seit dann besteht weiter;
ein künftiger Wert gilt als jetzt), sonst gilt der neue Zeitpunkt. Verlassen ist die Zone erst mit einer ungelesenen
Vorlage, deren `created` nicht jünger ist als die Grenze: das `created` der g-ältesten gelesenen Vorlage (eine Seite;
bei weniger gelesenen das der jüngsten). Gleich alt genügt (Massenimport mit gleichem `created`); bis zu g − 1
Ausreißer unter den gelesenen (etwa ein Platzhalterdatum, viel zu alt) verschieben die Grenze nicht, und eine
ungelesene Vorlage an oder hinter der Grenze liegt höchstens eine Seite vor dem Ende der Zone. Annahme: Köln sortiert
die Liste streng nach `created` absteigend (neue Vorlagen sind jünger, der ungelesene Rest ist älter, Platzhalterdaten
stehen am Ende); belegt ist das für die ersten 100 Vorlagen (Stufe 2), nicht über mehrere Seiten. Trifft die Annahme
nicht zu, gilt die Zone zu früh als verlassen (in der Folgenacht womöglich ein Listenfehler, der Vollabruf beginnt von
vorn), etwa wenn eine neue Vorlage ein Platzhalterdatum trägt, oder nie (die erlaubte Verschiebung wächst bis 1000
Vorlagen, ein schwächerer Schutz gegen Schleifen), etwa wenn g oder mehr gelesene eines tragen. So zählen
nach langer Pause auch zwei Strecken gelesener Seiten (aus der Vornacht und aus der ersten Nacht, dazwischen neue
Vorlagen) zur Zone, und überwiegen Löschungen die neuen Vorlagen, ist sie gleich mit der ersten Seite verlassen. Ohne
lesbares `created` (mit Zone) bleibt `gespeichert`. Die neuen Vorlagen am Listenanfang holt der nächste inkrementelle
Lauf (modified_since ab dem Start des Vollabrufs).
Zwischen den Nächten gelöschte, schon gelesene Vorlagen bleiben bis zum nächsten Vollabruf bzw. bis zu ihrem Eintrag
mit `deleted` aus modified_since im Stand. Keine
Fortsetzung nach einem Abbruch der Art `liste` (Schleife in links.next), `weiterleitung`, `proxy` oder `adresse`
(ungültige Adresse, auch links.next auf einen anderen Host): Der nächste Lauf beginnt von vorn. Eine unlesbare
Fortsetzung (auch eine fehlende oder unlesbare Teildatei) wird verworfen und gemeldet; der Vollabruf beginnt dann von
vorn.

Nacht mit möglicher Sperre (`moegliche_sperre`, Zähler `sperre_verdacht` im Zustand): Zeitüberschreitung,
Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht (Art `sperre`), HTTP 401,
403 oder 429 (Art `http`), `aufgegeben` nach 429, 5xx, unlesbarer Antwort oder CONNECT-Antwort 429/503 (auch sofort,
wenn die Pause nicht mehr ins Zeitfenster passt oder Retry-After zu lang oder unlesbar ist, abruf.py), außerdem
vorsichtshalber eine Weiterleitung (etwa auf die Sperrseite einer Firewall) und gültiges JSON in unerwarteter Form
(Art `unlesbar`: kein Objekt, Body ohne Listen, Seite ohne Liste `data` oder mit einem nicht leeren `links`, das kein
Objekt ist). Nach drei solchen Nächten ohne vollständigen Lauf dazwischen pausiert der Abruf sieben Tage; ein
vollständiger Lauf setzt den Zähler zurück. Nicht: Ablehnung durch den Proxy der Ausführungsumgebung (`proxy`),
ungültige Adressen (`adresse`) und eine gescheiterte Zertifikatsprüfung (`tls`, vermutlich eine Einstellung der
Ausführungsumgebung; ein Zertifikat der Gegenseite oder eine Sperrseite ist nicht ausgeschlossen), denn diese Anfragen
haben die Stadt nicht als HTTP-Anfrage erreicht, sowie ein Vollabruf deutlich kleiner als der vorhandene Stand (Art
`leer`, Regel aus Bonn: weniger als 90 %). Nächte mit `tls` zählt `tlsfehler` (wie `listenfehler`, Warnung im Log):
nach drei solchen Nächten ohne vollständigen Lauf dazwischen sieben Tage Pause.
Nach jedem Abbruch außer dem Ende des Zeitfensters (auch nach `obergrenze`, `proxy`, `adresse`, Programm- und
Einstellungsfehlern)
folgt in derselben Nacht (12 Stunden, `SPERRE_GLEICHE_NACHT`) kein weiterer Lauf, etwa nach einem Push oder auf
Knopfdruck (`letzter_abbruch` im Zustand; nicht für lokale Testserver).
Retry-After über die Nacht hinaus: Gibt abruf.py wegen eines Retry-After auf, steht `nicht_vor` im Zustand (höchstens
30 Tage, unlesbarer Retry-After 7 Tage); bis dahin wird jeder Lauf übersprungen.
Abbrüche der Art `liste` oder `adresse` (dauerhaft ungültiges links.next oder Schleife: jede Nacht ein Vollabruf bis
zur selben Stelle) und `filter` (Zeitfilter nicht angewandt) zählt `listenfehler` im Zustand (Nächte, nicht Läufe: ein
weiterer Abbruch innerhalb von 12 Stunden zählt nicht noch einmal): Hinweis in STAND.json (`abruf_hinweis`) und
Warnung im Log des Workflows; nach drei solchen Nächten ohne vollständigen Lauf dazwischen sieben Tage Pause. Wie es
in der nächsten Nacht weitergeht, steht im Hinweis und wird aus dem Zustand abgeleitet (_weiter): steht eine
`<liste>_fortsetzung` aus, „Fortsetzung in der nächsten Nacht“, sonst beginnt der (inkrementelle) Abruf erneut; ein
inkrementeller Lauf an der Grenze je Lauf bekommt den Hinweis auf RATSATLAS_VOLLABRUF=ja.
Der Zustand wird vor der ersten Anfrage geprüft: Ist die Datei oder ein Zeitpunkt des letzten Abrufs einer Liste
unlesbar, bricht der Lauf ohne Anfrage laut ab (`ZustandUnlesbar`; so jeder Lauf, bis die Datei geprüft ist). Ein
unlesbarer, zonenloser oder künftiger Zeitpunkt des letzten Sperrverdachts, Listenfehlers oder Abbruchs gilt als
„jetzt“ (in dieser Nacht kein Abruf), eine unlesbare Zahl der Nächte als drei, ein unlesbares `nicht_vor` als jetzt +
7 Tage, eines mehr als 30 Tage voraus als jetzt + 30 Tage; alles wird neu geschrieben und gemeldet. Eine unlesbare
STAND.json wird als `STAND.json.defekt` beiseitegelegt.
Programm- und Einstellungsfehler (etwa eine unerwartete Form tief in einem Objekt, ein RuntimeError ohne Art, ein
Zeilenumbruch im User-Agent; vor der ersten Anfrage geprüft: RATSATLAS_MAX_OBJEKTE unter max_objekte_mindestens(),
RATSATLAS_LIMIT keine positive ganze Zahl, unbekannte Listen in RATSATLAS_KUERZER_ANNEHMEN oder RATSATLAS_VOLLABRUF)
zählen nicht als Sperrverdacht: Sie stehen in STAND.json und brechen den Lauf mit Traceback ab.
Fällt der Abruf aus, bleibt der letzte gültige Stand; der Fehler steht in `STAND.json` (`abruf_fehler`). Ein
vollständiger Lauf entfernt `abruf_fehler`, `abruf_hinweis` und `abruf_uebersprungen`. Das Ende des Zeitfensters
und die Obergrenze je Nacht (etwa bei einem Vollabruf über mehrere Nächte) sind kein Fehler: neutraler Hinweis in
`abruf_hinweis` (wie es weitergeht, aus dem Zustand, siehe oben), ein älteres `abruf_fehler` entfällt. Den Zustand
sichert pages.yml gleich nach dem Abrufschritt, auch wenn ein späterer Schritt scheitert.

Abrufstatistik (`abrufstatistik.tsv`, Spalten STAT_SPALTEN): je Liste eine Zeile und eine Zeile `body` für den Abruf
des Bodys; Zähler aus abruf.statistik() als Differenz je Zeile, darunter `weiterleitungen` und `proxy`.
"""
import csv
import json
import math
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import abruf, config
from .fetch import MIN_ANTEIL, _guard, _jsonl_count, _now, _write

UEBERLAPPUNG = timedelta(days=1)
SPERRE_NAECHTE = 3                 # Nächte in Folge mit möglicher Sperre (moegliche_sperre), danach Pause
SPERRE_PAUSE = timedelta(days=7)
SPERRE_GLEICHE_NACHT = timedelta(hours=12)   # nach einem Verdacht kein weiterer Lauf in derselben Nacht
# HTTP-Antworten, nach denen die Nacht als Nacht mit möglicher Sperre zählt (Art `http`; 429 endet sonst als
# `aufgegeben`, das ebenfalls zählt)
SPERRE_HTTP = (401, 403, 429)
# HTTP-Codes, die eine gespeicherte Fortsetzung als veraltet verwerfen, wenn schon ihre erste Seite sie liefert
VERALTET_HTTP = (404, 410)
STAT_SPALTEN = ["datum", "liste", "modus", "seiten", "objekte", "neu", "geaendert", "geloescht", "filter_wirksam",
                "anfragen", "fehler", "wiederholungen", "weiterleitungen", "proxy", "bytes", "sekunden", "ergebnis"]
# Zähler aus abruf.statistik(), je Zeile der Abrufstatistik als Differenz
STAT_ZAEHLER = ("anfragen", "fehler", "wiederholungen", "weiterleitungen", "proxy", "bytes", "sekunden")
# Abbruchsarten, nach denen ein Vollabruf nicht fortgesetzt wird (der nächste Lauf beginnt von vorn)
OHNE_FORTSETZUNG = ("liste", "weiterleitung", "proxy", "adresse")
# Abbruchsarten, die auf eine dauerhaft fehlerhafte Liste deuten (Zähler `listenfehler`), und deren Grenze; `filter`:
# ein inkrementeller Lauf erhielt Objekte vor modified_since (der Server wendet den Zeitfilter nicht an)
LISTENFEHLER = ("liste", "adresse", "filter")
LISTENFEHLER_NAECHTE = 3
LISTENFEHLER_PAUSE = timedelta(days=7)
# Nächte mit gescheiterter Zertifikatsprüfung (Zähler `tlsfehler`), danach Pause
TLS_NAECHTE = 3
TLS_PAUSE = timedelta(days=7)
# Listen mit Zeitpunkt des letzten Abrufs im Zustand
LISTEN = ("organizations", "papers", "meetings")
# Seitenverschiebung in einer Fortsetzung (neueste zuerst), in Vorlagen: je angefangenem Tag seit dem Speichern der
# Fortsetzung 100 neue Vorlagen (Stufe 1: auf der ersten Seite 25 Vorlagen mit Datum 03. bis 06.11.2026), höchstens
# 1000; ohne lesbaren Zeitpunkt 100. In Seiten mit der tatsächlichen Seitengröße g des Laufs aufgerundet (Vorlagen / g:
# bei 25 je Seite 4 Seiten je Tag und höchstens 40, bei 100 je Seite 1 und höchstens 10); so viele Seiten ohne neue
# Kennungen gelten als Verschiebung, danach als Schleife. Die wiederholte Seite zählt mit, es sind also bis zu 99 neue
# Vorlagen je Tag (Vorlagen − 1).
VERSCHIEBUNG_JE_TAG = 100
VERSCHIEBUNG_HOECHSTENS = 1000
# Seitengröße für max_objekte_mindestens(), wenn RATSATLAS_LIMIT leer ist (Vorgabe des Servers, in Köln 25)
SEITENGROESSE_OHNE_LIMIT = 100
# Listen, aus denen beratungen() die Beratungen ableitet; ein angenommener kürzerer Stand einer dieser Listen lockert
# die 90-%-Prüfung der Beratungen, bis sie geschrieben sind (Vermerk KUERZER_VERMERK im Zustand)
BERATUNGEN_AUS = ("papers", "meetings")
KUERZER_VERMERK = "beratungen_kuerzer_erlaubt"
# Abhilfe je Art einer Warnung (_nur_warnung), `{liste}` wird ersetzt
ABHILFE = {
    "leer": ("Abhilfe, wenn der kürzere Stand stimmt (nicht bei 0 Objekten): ein Lauf mit "
             "RATSATLAS_KUERZER_ANNEHMEN={liste}"),
}


def _seitengroesse():
    """Eingestellte Seitengröße g (RATSATLAS_LIMIT) als Zahl; leer: SEITENGROESSE_OHNE_LIMIT. Keine positive ganze
    Zahl: ValueError (Einstellungsfehler vor der ersten Anfrage)."""
    g = config.ABRUF_SEITENGROESSE
    if not g:
        return SEITENGROESSE_OHNE_LIMIT
    if not str(g).isdigit() or int(g) < 1:
        raise ValueError(f"RATSATLAS_LIMIT={g!r} ist keine positive ganze Zahl; keine Anfrage gesendet")
    return int(g)


def max_objekte_mindestens():
    """Kleinste zulässige Grenze je Lauf (RATSATLAS_MAX_OBJEKTE): (ceil(VERSCHIEBUNG_HOECHSTENS / g) + 2) · g mit der
    eingestellten Seitengröße g (_seitengroesse), also die größte Seitenverschiebung in Seiten plus zwei Seiten (die
    wiederholte Seite einer Fortsetzung und eine neue); darunter käme eine Fortsetzung nie voran. Bei 100 je Seite 1200,
    bei 150 1350. Annahme: Der Server liefert g Objekte je Seite wie verlangt."""
    g = _seitengroesse()
    return (math.ceil(VERSCHIEBUNG_HOECHSTENS / g) + 2) * g


def _listen_aus(variable, alle=False):
    """Listen aus einer Komma-Liste in der Umgebung (RATSATLAS_KUERZER_ANNEHMEN, RATSATLAS_VOLLABRUF); `alle`: „ja“
    steht für alle Listen."""
    wert = os.environ.get(variable, "")
    if alle and wert == "ja":
        return set(LISTEN)
    return {x.strip() for x in wert.split(",") if x.strip()}


class ZustandUnlesbar(RuntimeError):
    """zustand_abruf.json oder ein Zeitpunkt darin ist unlesbar: keine Anfrage, bis die Datei geprüft ist."""


def moegliche_sperre(fehler):
    """Zählt dieser Abbruch als Nacht mit möglicher Sperre? Art `sperre` (Zeitüberschreitung, Verbindungsabbruch,
    abgeschnittene oder unlesbare Antwort, Proxy erreicht die Stadt nicht), `aufgegeben` (nach 429, 5xx, unlesbarer
    Antwort oder CONNECT-Antwort 429/503) und `http` mit 401, 403 oder 429. Nicht: proxy (Ablehnung in der
    Ausführungsumgebung), tls (Zertifikatsprüfung gescheitert), liste, adresse, filter, obergrenze, andere HTTP-Codes
    (z. B. 404). Eine Weiterleitung (etwa auf die Sperrseite einer vorgeschalteten Firewall) und eine unerwartete
    Antwortform (`unlesbar`) zählen vorsichtshalber mit."""
    art = getattr(fehler, "art", "")
    return art in ("sperre", "aufgegeben", "weiterleitung", "unlesbar") or (
        art == "http" and getattr(fehler, "code", None) in SPERRE_HTTP)


def _warnung(text):
    """Warnung auf stderr; in GitHub Actions als Anmerkung (::warning::), damit sie im Workflow sichtbar wird."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{text}", file=sys.stderr, flush=True)
    else:
        print(f"Warnung: {text}", file=sys.stderr, flush=True)


def _zeit(wert):
    """Zeitpunkt mit Zone aus einem ISO-Text; None, wenn kein Text, unlesbar oder ohne Zone."""
    if not isinstance(wert, str):
        return None
    try:
        t = datetime.fromisoformat(wert)
    except ValueError:
        return None
    return t if t.utcoffset() is not None else None


def _zustand():
    """Zustand des Abrufs; unlesbare Datei: ZustandUnlesbar (der Lauf bricht ohne Anfrage ab)."""
    if not config.ZUSTAND.exists():
        return {}
    try:
        z = json.loads(config.ZUSTAND.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as e:   # auch UnicodeDecodeError und zu tief verschachtelt
        raise ZustandUnlesbar(f"{config.ZUSTAND.name} unlesbar ({e}); keine Anfrage an die Stadt, bis die Datei geprüft "
                              "oder entfernt ist (ohne Datei: Vollabruf, Zähler der Nächte verloren)") from e
    if not isinstance(z, dict):
        raise ZustandUnlesbar(f"{config.ZUSTAND.name} ist kein JSON-Objekt; keine Anfrage an die Stadt, bis die Datei "
                              "geprüft ist")
    return z


def _zustand_aendern(**werte):
    """Setzt Werte im Zustand (ein Schreibvorgang); None entfernt den Schlüssel."""
    z = _zustand()
    for schluessel, wert in werte.items():
        if wert is None:
            z.pop(schluessel, None)
        else:
            z[schluessel] = wert
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.ZUSTAND, json.dumps(z, ensure_ascii=False, indent=1) + "\n")


def _zustand_setzen(schluessel, wert):
    _zustand_aendern(**{schluessel: wert})


def _zaehler_pruefen(z, schluessel, grenze, jetzt):
    """Zähler der Nächte (`sperre_verdacht`, `listenfehler`) und den letzten Abbruch (`letzter_abbruch`, `grenze`
    None: ohne Zahl der Nächte) vorsichtig lesen: unlesbarer, zonenloser oder künftiger Zeitpunkt `zuletzt` → jetzt (in
    dieser Nacht kein Abruf); unlesbare Zahl der Nächte → `grenze` (Pause). Liefert den Eintrag und die Meldungen zu
    ersetzten Werten."""
    v = z.get(schluessel)
    if not v:
        return {}, []
    meldungen = []
    if not isinstance(v, dict):
        meldungen.append(f"{schluessel} ist kein Objekt ({v!r})")
        v = {}
    v = dict(v)
    n = v.get("naechte")
    if grenze is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 0):
        meldungen.append(f"{schluessel}.naechte unlesbar ({n!r}), gilt als {grenze}")
        v["naechte"] = grenze
    zuletzt = _zeit(v.get("zuletzt"))
    if zuletzt is None or zuletzt > jetzt:
        grund = "in der Zukunft" if zuletzt is not None else "unlesbar oder ohne Zone"
        meldungen.append(f"{schluessel}.zuletzt {grund} ({v.get('zuletzt')!r}), gilt als jetzt")
        v["zuletzt"] = jetzt.isoformat(timespec="seconds")
    return v, meldungen


def _nicht_vor_pruefen(wert, jetzt):
    """Zeitpunkt aus einem Retry-After (`nicht_vor`) vorsichtig lesen: unlesbar, ohne Zone oder Zahl → jetzt + 7 Tage;
    mehr als 30 Tage in der Zukunft → jetzt + 30 Tage (wie beim Speichern begrenzt). Liefert (Wert, Meldung)."""
    if wert is None:
        return None, ""
    t = _zeit(wert)
    if t is None:
        neu = (jetzt + abruf.RETRY_AFTER_UNLESBAR).isoformat(timespec="seconds")
        return neu, f"nicht_vor unlesbar oder ohne Zone ({wert!r}), gilt als {neu}"
    if t > jetzt + abruf.RETRY_AFTER_HOECHSTENS:
        neu = (jetzt + abruf.RETRY_AFTER_HOECHSTENS).isoformat(timespec="seconds")
        return neu, (f"nicht_vor mehr als {abruf.RETRY_AFTER_HOECHSTENS.days} Tage in der Zukunft ({wert!r}), gilt "
                     f"als {neu}")
    return wert, ""


def _zustand_pruefen():
    """Vor der ersten Anfrage: Zustand lesen und prüfen (siehe Moduldoku). Liefert den Zustand mit geprüften Zählern."""
    z = _zustand()
    for liste in LISTEN:
        if liste in z and _zeit(z[liste]) is None:
            raise ZustandUnlesbar(f"Zeitpunkt des letzten Abrufs von {liste} in {config.ZUSTAND.name} unlesbar oder "
                                  f"ohne Zone ({z[liste]!r}); keine Anfrage an die Stadt, bis der Wert geprüft ist")
    jetzt = abruf.uhr()
    neu, meldungen = {}, []
    for schluessel, grenze in (("sperre_verdacht", SPERRE_NAECHTE), ("listenfehler", LISTENFEHLER_NAECHTE),
                               ("tlsfehler", TLS_NAECHTE), ("letzter_abbruch", None)):
        v, m = _zaehler_pruefen(z, schluessel, grenze, jetzt)
        if m:
            neu[schluessel] = v
            meldungen += m
    v, m = _nicht_vor_pruefen(z.get("nicht_vor"), jetzt)
    if m:
        neu["nicht_vor"] = v
        meldungen.append(m)
    if neu:
        z.update(neu)
        _zustand_aendern(**neu)
        _warnung(f"{config.ZUSTAND.name}: " + "; ".join(meldungen) + " (neu geschrieben)")
    return z


def _pause_grund(z, lokal):
    """Grund, den Lauf ohne Anfrage zu überspringen (12-Stunden-Regel nach jedem Abbruch, Retry-After über die Nacht
    hinaus, Pausen nach drei Nächten), sonst None. 12-Stunden-Regel und Retry-After gelten nicht für lokale Testserver."""
    jetzt = abruf.uhr()
    verdacht = z.get("sperre_verdacht") or {}
    if verdacht and not lokal:
        # nach einer Nacht mit möglicher Sperre in derselben Nacht kein weiterer Lauf (z. B. Push oder Knopfdruck)
        seit = jetzt - _zeit(verdacht["zuletzt"])
        if seit < SPERRE_GLEICHE_NACHT:
            return (f"möglicher Sperrverdacht vor {int(seit.total_seconds() // 60)} Minuten; in derselben Nacht kein "
                    "weiterer Abruf")
    letzter = z.get("letzter_abbruch") or {}
    if letzter and not lokal:
        # nach jedem anderen Abbruch (außer dem Ende des Zeitfensters), auch nach einem Programmfehler, ebenso
        seit = jetzt - _zeit(letzter["zuletzt"])
        if seit < SPERRE_GLEICHE_NACHT:
            return (f"Abbruch ({letzter.get('art') or 'unbekannt'}) vor {int(seit.total_seconds() // 60)} Minuten; in "
                    "derselben Nacht kein weiterer Abruf")
    nicht_vor = _zeit(z.get("nicht_vor"))
    if nicht_vor is not None and not lokal and jetzt < nicht_vor:
        return (f"Retry-After der Stadt: kein Abruf vor {nicht_vor.isoformat(timespec='minutes')} "
                f"(höchstens {abruf.RETRY_AFTER_HOECHSTENS.days} Tage)")
    if verdacht.get("naechte", 0) >= SPERRE_NAECHTE:
        bis = _zeit(verdacht["zuletzt"]) + SPERRE_PAUSE
        if jetzt < bis:
            return (f"Abruf pausiert bis {bis.date().isoformat()}: {verdacht['naechte']} Nächte in Folge mit möglicher "
                    "Sperre (Verbindungsabbruch, abgeschnittene oder unlesbare Antwort, HTTP 401/403/429, Weiterleitung "
                    "oder aufgegeben nach 429/5xx); bitte Kontakt zur Stadt aufnehmen")
    for schluessel, grenze, pause, grund in (
            ("listenfehler", LISTENFEHLER_NAECHTE, LISTENFEHLER_PAUSE, "Abbruch wegen einer fehlerhaften Liste "
             "(ungültige Folgeadresse in links.next, Schleife oder Zeitfilter nicht angewandt); bitte die Liste "
             "prüfen"),
            ("tlsfehler", TLS_NAECHTE, TLS_PAUSE, "Zertifikatsprüfung fehlgeschlagen (vermutlich Einstellung der "
             "Ausführungsumgebung; Zertifikat der Gegenseite oder Sperrseite nicht ausgeschlossen); bitte prüfen")):
        fehler = z.get(schluessel) or {}
        if fehler.get("naechte", 0) >= grenze:
            bis = _zeit(fehler["zuletzt"]) + pause
            if jetzt < bis:
                return f"Abruf pausiert bis {bis.date().isoformat()}: {fehler['naechte']} Nächte in Folge {grund}"
    return None


def _stand():
    """STAND.json; eine unlesbare Datei wird als STAND.json.defekt beiseitegelegt (mit Warnung) und neu begonnen."""
    if not config.STAND.exists():
        return {}
    try:
        s = json.loads(config.STAND.read_text(encoding="utf-8"))
        if isinstance(s, dict):
            return s
        grund = "kein JSON-Objekt"
    except (ValueError, RecursionError) as e:
        grund = str(e)
    defekt = config.STAND.with_name(config.STAND.name + ".defekt")
    os.replace(config.STAND, defekt)
    _warnung(f"{config.STAND.name} unlesbar ({grund}); beiseitegelegt als {defekt.name}, neu begonnen")
    return {}


def _stand_setzen(**werte):
    s = _stand()
    s.update(werte)
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.STAND, json.dumps(s, ensure_ascii=False, indent=1) + "\n")


def _stand_entfernen(*schluessel):
    """Entfernt Einträge aus STAND.json (etwa `abruf_fehler` nach einem vollständigen Lauf)."""
    s = _stand()
    if any(k in s for k in schluessel):
        for k in schluessel:
            s.pop(k, None)
        _write(config.STAND, json.dumps(s, ensure_ascii=False, indent=1) + "\n")


def _stamp(schluessel):
    _stand_setzen(**{schluessel: _now()})


def _warnung_vermerken(liste, meldung):
    """Warnung einer Nebenliste in STAND.json unter `abruf_warnungen` (je Liste `zeit` und `meldung`); `meldung` None
    entfernt sie (nur, wenn diese Liste wieder regulär aktualisiert wurde, _abruf_liste). Ein Abbruch einer anderen
    Liste und ein vollständiger Lauf lassen sie stehen."""
    s = _stand()
    warnungen = dict(s["abruf_warnungen"]) if isinstance(s.get("abruf_warnungen"), dict) else {}
    if meldung is None and liste not in warnungen:
        return
    if meldung is None:
        warnungen.pop(liste)
    else:
        warnungen[liste] = {"zeit": _now(), "meldung": meldung[:800]}
    s["abruf_warnungen"] = warnungen
    if not warnungen:
        s.pop("abruf_warnungen")
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.STAND, json.dumps(s, ensure_ascii=False, indent=1) + "\n")


def _mit_parametern(url, **params):
    """Hängt Parameter URL-kodiert an (`quote(wert, safe="")`, etwa „:“ → %3A, „+“ → %2B): Köln übergeht Zeitwerte
    unkodiert und wendet sie kodiert an (Stufe 2, 08.11.2026)."""
    params = {k: v for k, v in params.items() if v}
    if not params:
        return url
    return url + ("&" if "?" in url else "?") + "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())


def _limit(url):
    """Wert des Parameters `limit` in einer Adresse (roh), sonst None."""
    for teil in urllib.parse.urlsplit(url).query.split("&"):
        k, gleich, v = teil.partition("=")
        if k == "limit" and gleich:
            return v
    return None


def _port(teile):
    """Port einer zerlegten Adresse; der ausdrückliche Standardport (http 80, https 443) gilt wie keine Angabe (None).
    Ein unlesbarer Port: ValueError."""
    port = teile.port
    return None if (teile.scheme, port) in (("http", 80), ("https", 443)) else port


def folgeadresse(naechste, liste_url, limit=None):
    """links.next vor dem Folgen: Schema, Host und Pfad bleiben, der Query-Teil wird je Parameter `k=v` als
    `k=quote(unquote(v), safe="")` neu aufgebaut (Reihenfolge, `page` und `limit` unverändert; idempotent: ein schon
    kodierter Wert bleibt gleich). `unquote`, nicht `unquote_plus`: Köln liefert „+“ als wörtliches Plus (Stufe 2:
    `…?page=2&modified_since=2026-11-05T11:29:44+00:00`), unverändert gesendet wäre es ein Leerzeichen und der Filter
    übergangen. Trägt die erste Adresse des Laufs `limit`, links.next aber nicht, wird `limit` angehängt (sonst
    wechselte die Seitengröße mitten in der Liste). Zeigt links.next auf ein anderes Schema, einen anderen Host oder
    einen anderen Port als die Liste: Abbruch der Art `adresse` (nicht gesendet); der ausdrückliche Standardport
    (http …:80, https …:443) gilt wie keine Angabe. Adressen außerhalb von ASCII oder unlesbare bleiben unverändert
    (abruf.get_json lehnt sie ab, Art `adresse`)."""
    if not naechste.isascii():
        return naechste
    try:
        teile, liste = urllib.parse.urlsplit(naechste), urllib.parse.urlsplit(liste_url)
        anders = (teile.scheme, teile.hostname, _port(teile)) != (liste.scheme, liste.hostname, _port(liste))
    except ValueError:
        return naechste
    if anders:
        raise abruf.Abbruch(f"links.next zeigt auf einen anderen Host als die Liste, nicht gesendet: {naechste}",
                            "adresse")
    neu = []
    for teil in teile.query.split("&") if teile.query else []:
        k, gleich, v = teil.partition("=")
        neu.append(f"{k}={urllib.parse.quote(urllib.parse.unquote(v), safe='')}" if gleich else teil)
    if limit and not any(t.partition("=")[0] == "limit" for t in neu):
        neu.append(f"limit={limit}")
    return urllib.parse.urlunsplit(teile._replace(query="&".join(neu)))


class Teilabbruch(abruf.Abbruch):
    """Abbruch mitten in einer Liste; trägt den gelesenen Teil für die Fortsetzung (`zuletzt`: die zuletzt gelesene
    Seite, dort beginnt die Fortsetzung; `verlassen`: eine Fortsetzung hat die verschobene Zone verlassen, also eine
    ungelesene Vorlage gelesen, die nicht jünger ist als die Grenze, siehe liste())."""

    def __init__(self, ursache, objekte, naechste, seiten, zuletzt=None, verlassen=False):
        super().__init__(str(ursache), getattr(ursache, "art", ""), getattr(ursache, "ziel", ""),
                         getattr(ursache, "code", None), getattr(ursache, "nicht_vor", None))
        self.objekte, self.naechste, self.seiten, self.zuletzt = objekte, naechste, seiten, zuletzt
        self.verlassen = verlassen
        self.grenze_je_lauf = getattr(ursache, "grenze_je_lauf", False)   # inkrementell an der Grenze je Lauf


def verschiebung_erlaubt(gespeichert, jetzt=None):
    """Seitenverschiebung in Vorlagen, die eine Fortsetzung hinnimmt (liste() rechnet sie mit der tatsächlichen
    Seitengröße in Seiten um): VERSCHIEBUNG_JE_TAG je angefangenem Tag seit `gespeichert` (Zeitpunkt der Fortsetzung),
    höchstens VERSCHIEBUNG_HOECHSTENS; fehlt der Zeitpunkt, ist er unlesbar oder künftig: VERSCHIEBUNG_JE_TAG."""
    t, jetzt = _zeit(gespeichert), jetzt or abruf.uhr()
    if t is None or t > jetzt:
        return VERSCHIEBUNG_JE_TAG
    tage = max(1, math.ceil((jetzt - t) / timedelta(days=1)))
    return min(VERSCHIEBUNG_JE_TAG * tage, VERSCHIEBUNG_HOECHSTENS)


def _erstellt(objekt):
    """`created` eines Objekts als Zeitpunkt mit Zone; None, wenn es fehlt, unlesbar oder ohne Zone ist."""
    return _zeit(objekt.get("created"))


def _leer(wert):
    """Leerer Wert (null, "", [], {}): SessionNet ist in PHP geschrieben, ein leeres Objekt kann als [] ankommen."""
    return wert is None or (isinstance(wert, (str, list, dict)) and not wert)


def _seite_pruefen(seite, url):
    """Form einer Listenseite, geprüft dort, wo sie ankommt: `data` ist eine Liste von Objekten mit Kennung (Text),
    `links` fehlt, ist leer (wie fehlend) oder ein Objekt, `links.next` fehlt, ist leer (Ende der Liste) oder Text.
    Liefert die Folgeadresse oder None (Ende). Sonst Abbruch der Art `unlesbar` (gültiges JSON in unerwarteter Form,
    etwa ein nicht leeres links, das kein Objekt ist: keine Wiederholung, zählt als Nacht mit möglicher Sperre)."""
    daten, links = seite.get("data"), seite.get("links")
    if not isinstance(daten, list) or not all(isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"]
                                              for o in daten):
        grund = "data ist keine Liste von Objekten mit Kennung"
    elif _leer(links):
        return None
    elif not isinstance(links, dict):
        grund = "links ist kein Objekt"
    elif _leer(links.get("next")):
        return None
    elif isinstance(links["next"], str):
        return links["next"]
    else:
        grund = "links.next ist kein Text"
    raise abruf.Abbruch(f"unerwartete Antwortform ({grund}): {url}", "unlesbar")


def liste(url, seit=None, start=None, objekte=None, seiten=0, verschiebung=VERSCHIEBUNG_JE_TAG, im_lauf=0):
    """Alle Objekte einer OParl-Liste über links.next (vor dem Folgen normalisiert, folgeadresse()); `seit` setzt
    modified_since, `config.ABRUF_SEITENGROESSE` den Parameter limit. `start`, `objekte` und `seiten` setzen einen
    abgebrochenen Vollabruf fort. Liefert (Objekte, Seiten); ein Abbruch kommt als Teilabbruch. Seitengröße g ist die
    tatsächliche des Laufs (größte gelesene Seite). `seiten` zählt die Seiten insgesamt (Statistik, Fortsetzung); die
    Grenze von `config.ABRUF_MAX_OBJEKTE` / g Seiten gilt je Lauf (Höflichkeitsgrenze je Nacht): Ein Vollabruf endet
    dort mit Art `obergrenze` (Fortsetzung in der nächsten Nacht, wie am Ende des Zeitfensters), sofern der Lauf über
    die wiederholte Seite einer Fortsetzung hinaus neue Objekte gelesen hat (sonst käme die Fortsetzung nie voran: Art
    `liste`), ein inkrementeller Lauf mit Art `liste` (`grenze_je_lauf`). Über die Fortsetzungen hinweg gilt die
    Gesamtgrenze `config.ABRUF_MAX_OBJEKTE_GESAMT` / g
    Seiten (Liste, die endlos neue Kennungen erzeugt; Art `liste`), geprüft vor der Grenze je Lauf und ab der zweiten
    Anfrage eines Laufs (vorher ist g unbekannt; eine gespeicherte Fortsetzung liegt stets unter der Grenze ihrer
    Seitengröße). Mit `seit` wird jede Seite geprüft: Objekte mit lesbarem `modified` vor `seit` (ohne `deleted: true`,
    eine Löschung kann ein altes `modified` tragen) heißen, der Server wendet den Zeitfilter nicht an; Abbruch nach
    dieser Seite (Art `filter`, ohne Fortsetzung). In einer Fortsetzung
    (`start`) gelten Seiten ohne neue Kennungen bis zur Seitenverschiebung von `verschiebung` Vorlagen (aufgerundet auf
    Seiten zu g) als Verschiebung (neue Vorlagen am Listenanfang, wiederholte erste Seite), nicht als Schleife; eine
    Seite, deren Kennungen alle schon in diesem Lauf kamen, und eine wiederholte (normalisierte) Adresse bleiben eine
    Schleife. Ein Teilabbruch vermerkt, ob die Fortsetzung die verschobene Zone
    verlassen hat (`verlassen`, für `gespeichert`): erst mit einer ungelesenen Vorlage, deren `created` nicht jünger
    ist als das der g-ältesten gelesenen (eine Seite; ohne lesbares `created` nie). `im_lauf`: Seiten, die dieser Lauf
    an derselben Liste schon gelesen hat (die Seiten mit Zeitfilter vor einem Neustart ohne modified_since,
    _abruf_liste); sie zählen zur Grenze je Lauf, nicht zu `seiten`."""
    naechste = start or _mit_parametern(url, modified_since=seit, limit=config.ABRUF_SEITENGROESSE)
    limit = _limit(naechste)
    objekte = list(objekte or [])
    ids, gesehen, dieser_lauf = {o.get("id") for o in objekte}, set(), set()
    verschoben, zuletzt = 0, None   # Seiten ohne neue Kennungen in einer Fortsetzung; zuletzt gelesene Seite
    # Fortsetzung: Grenze der verschobenen Zone ist das created der g-ältesten gelesenen Vorlage (eine Seite); eine
    # ungelesene Vorlage, die nicht jünger ist, liegt an oder hinter ihr
    aelteste = sorted(t for t in map(_erstellt, objekte) if t is not None) if start else []
    groesse, verlassen = 0, False   # tatsächliche Seitengröße dieses Laufs (größte gelesene Seite)
    fortschritt = False   # neue Objekte über die wiederholte Seite (erste Seite einer Fortsetzung) hinaus gelesen
    filtergrenze = datetime.fromisoformat(seit) if seit else None
    while naechste:
        try:
            naechste = folgeadresse(naechste, url, limit)
            if naechste in gesehen:   # Schutz gegen zyklische Verweise
                raise abruf.Abbruch(f"links.next zeigt auf eine bereits gelesene Seite: {naechste}", "liste")
            # vor der ersten Seite ist g unbekannt (als 1 gerechnet: die Grenzen greifen dann nicht)
            gesamt = math.ceil(config.ABRUF_MAX_OBJEKTE_GESAMT / max(groesse, 1))
            if seiten >= gesamt:   # Seiten insgesamt, auch aus früheren Läufen (Fortsetzung)
                raise abruf.Abbruch(f"mehr als {gesamt} Seiten insgesamt über Fortsetzungen hinweg "
                                    f"({config.ABRUF_MAX_OBJEKTE_GESAMT} Objekte bei {groesse} je Seite); die Liste "
                                    "erzeugt womöglich endlos neue Kennungen", "liste")
            je_lauf = math.ceil(config.ABRUF_MAX_OBJEKTE / max(groesse, 1))
            if len(gesehen) + im_lauf >= je_lauf:   # Seiten dieses Laufs an dieser Liste
                grenze_text = f"{config.ABRUF_MAX_OBJEKTE} Objekte bei {groesse} je Seite, RATSATLAS_MAX_OBJEKTE"
                if seit:   # inkrementell: so viele Änderungen an einem Tag sind keine Höflichkeitsfrage
                    fehler = abruf.Abbruch(f"mehr als {je_lauf} Seiten in einem inkrementellen Lauf ({grenze_text}); "
                                           "wirkt der Zeitfilter?", "liste")
                    fehler.grenze_je_lauf = True
                    raise fehler
                if not fortschritt:   # nur die wiederholte Seite und Verschiebung: die Fortsetzung käme nie voran
                    raise abruf.Abbruch(f"Grenze je Lauf erreicht ({je_lauf} Seiten, {grenze_text}), ohne neue Objekte "
                                        "über die wiederholte Seite hinaus; keine Fortsetzung", "liste")
                raise abruf.Abbruch(f"Obergrenze je Nacht erreicht: {je_lauf} Seiten in diesem Lauf ({grenze_text}); "
                                    "Fortsetzung in der nächsten Nacht", "obergrenze")
            gesehen.add(naechste)
            seite = abruf.get_json(naechste)
            weiter = _seite_pruefen(seite, naechste)
        except abruf.Abbruch as e:
            raise Teilabbruch(e, objekte, naechste, seiten, zuletzt, verlassen) from e
        seiten += 1
        daten = seite["data"]
        groesse = max(groesse, len(daten))
        kennungen = {o["id"] for o in daten}
        neu = [o for o in daten if o["id"] not in ids]
        grenze = aelteste[min(groesse, len(aelteste)) - 1] if aelteste and groesse else None
        if daten and not neu:
            erlaubt = math.ceil(verschiebung / groesse)   # Seiten zu g
            if not start or kennungen <= dieser_lauf:   # dieselben Objekte mit neuem links.next (SessionNet-Sammelserver)
                grund = f"Seite ohne neue Kennungen, links.next läuft im Kreis: {naechste}"
            elif verschoben >= erlaubt:
                grund = (f"mehr als {erlaubt} Seiten ohne neue Kennungen in der Fortsetzung (erlaubte "
                         f"Seitenverschiebung {verschiebung} Vorlagen bei {groesse} je Seite): {naechste}")
            else:
                grund = None
                verschoben += 1   # Fortsetzung: die Seiten sind durch neue Vorlagen am Listenanfang verschoben
            if grund:
                raise Teilabbruch(abruf.Abbruch(grund, "liste"), objekte, None, seiten, zuletzt, verlassen)
        elif grenze is not None and any((t := _erstellt(o)) is not None and t <= grenze for o in neu):
            verlassen = True
        dieser_lauf |= kennungen
        ids.update(o.get("id") for o in neu)
        objekte += neu
        if neu and (not start or len(gesehen) > 1):
            fortschritt = True
        # Löschungen (deleted: true) können ein altes modified tragen: nicht geprüft
        vor = sorted(t for o in daten if not o.get("deleted") and (t := _zeit(o.get("modified"))) is not None
                     and t < filtergrenze) if filtergrenze else []
        if vor:   # der Server wendet modified_since auf dieser Seite nicht an: nicht bis zum Fensterende weiterlesen
            fehler = Teilabbruch(abruf.Abbruch(
                f"Zeitfilter auf Seite {seiten} nicht angewandt: {len(vor)} von {len(daten)} Objekten mit modified vor "
                f"modified_since={seit} (frühestes {vor[0].isoformat()}); Abbruch nach dieser Seite: {naechste}",
                "filter"), objekte, None, seiten, naechste, verlassen)
            fehler.groesse = groesse   # Seitengröße g dieses Laufs: Grenze je Lauf vor einem Neustart (_abruf_liste)
            raise fehler
        zuletzt, naechste = naechste, weiter
    return objekte, seiten


def _seit(schluessel):
    """modified_since für den nächsten Lauf: letzter Stand minus Überlappung; None = vollständiger Abruf (auch mit
    RATSATLAS_VOLLABRUF=ja für alle Listen oder einer Komma-Liste, etwa „meetings“, nur für diese)."""
    letzter = _zustand().get(schluessel)
    if not letzter or schluessel in _listen_aus("RATSATLAS_VOLLABRUF", alle=True):
        return None
    t = _zeit(letzter)
    if t is None:   # vor der ersten Anfrage geprüft (_zustand_pruefen); hier nur zur Sicherheit
        raise ZustandUnlesbar(f"Zeitpunkt des letzten Abrufs von {schluessel} unlesbar: {letzter!r}")
    t = t.astimezone(timezone.utc) - UEBERLAPPUNG
    return t.strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0000", "+00:00")


def _filter_wirksam(objekte, seit):
    """Prüft, ob der Server modified_since anwendet: keine Objekte mit älterem Änderungszeitpunkt (Löschungen mit
    `deleted: true` ausgenommen, wie in liste()). Ein unlesbares oder zonenloses `modified` (Angabe der Quelle) wird
    gezählt, nicht als Fehler behandelt."""
    if not seit:
        return ""
    grenze = datetime.fromisoformat(seit)
    aelter = unlesbar = 0
    for o in objekte:
        if o.get("modified") in (None, "") or o.get("deleted"):
            continue
        t = _zeit(o["modified"])
        if t is None:
            unlesbar += 1
        elif t < grenze:
            aelter += 1
    ergebnis = "ja" if not aelter else f"nein ({aelter} ältere)"
    return ergebnis + (f"; {unlesbar} mit unlesbarem modified" if unlesbar else "")


def _vorhanden(pfad):
    """Vorhandener Stand einer Liste (JSONL) als Kennung → Objekt; ohne Datei leer."""
    if not pfad.exists():
        return {}
    with open(pfad, encoding="utf-8") as f:
        return {o["id"]: o for o in map(json.loads, f) if o.get("id")}


def _zusammenfuehren(pfad, neu_objekte, voll, kuerzer_annehmen=False):
    """Führt Objekte über die ID mit dem vorhandenen Stand zusammen; liefert (alle, neu, geändert, gelöscht, Vermerk).
    Ein Vollabruf unter 90 % des Stands bricht ab (Art `leer`), außer mit `kuerzer_annehmen`
    (RATSATLAS_KUERZER_ANNEHMEN): dann gilt er, Vermerk im Log und für die Abrufstatistik (ein Vermerk heißt, dieser
    Lauf hat einen kürzeren Stand angenommen). Ein Vollabruf ohne Objekte gilt nie, auch nicht mit `kuerzer_annehmen`
    (Art `leer`); dabei zählen nur nicht gelöschte Objekte (einer nur mit `deleted: true` gilt als leer)."""
    alt = _vorhanden(pfad)
    vermerk = ""
    if voll:
        lebend = sum(1 for o in neu_objekte if not o.get("deleted"))
        try:
            _guard(pfad.name, len(neu_objekte) if lebend else 0, len(alt))
        except RuntimeError as e:   # Vollabruf deutlich kleiner als der vorhandene Stand: Abbruch, keine Sperre
            text = str(e) + (f" Geliefert: nur gelöschte Objekte ({len(neu_objekte)})." if neu_objekte and not lebend
                             else "")
            if not kuerzer_annehmen:
                raise abruf.Abbruch(text, "leer") from e
            if not lebend:
                raise abruf.Abbruch(f"{text} Ein leerer Vollabruf wird nie angenommen, auch nicht mit "
                                    "RATSATLAS_KUERZER_ANNEHMEN.", "leer") from e
            vermerk = (f"kürzerer Stand angenommen: {len(neu_objekte)} statt bisher {len(alt)} "
                       "(RATSATLAS_KUERZER_ANNEHMEN)")
            _warnung(f"{pfad.name}: {vermerk}")
    neu = sum(1 for o in neu_objekte if o["id"] not in alt)
    geaendert = sum(1 for o in neu_objekte if o["id"] in alt and o != alt[o["id"]])
    geloescht = sum(1 for o in neu_objekte if o.get("deleted"))
    stand = {} if voll else dict(alt)
    stand.update({o["id"]: o for o in neu_objekte if o.get("id")})
    return list(stand.values()), neu, geaendert, geloescht, vermerk


def _statistik_sicher(zeile):
    """Wie _statistik, aber ein Schreibfehler (OSError) verdrängt nicht den eigentlichen Abbruch (der sonst nicht als
    Nacht mit möglicher Sperre gezählt würde): nur eine Warnung."""
    try:
        _statistik(zeile)
    except OSError as e:
        _warnung(f"Abrufstatistik nicht geschrieben ({e}); Zeile: {zeile}")


def _statistik(zeile):
    """Hängt eine Zeile an die Abrufstatistik an. Eine ältere Datei mit anderem Kopf (z. B. ohne `weiterleitungen` und
    `proxy`) wird zuvor auf STAT_SPALTEN umgestellt; fehlende Werte bleiben leer."""
    config.EXPORT.mkdir(parents=True, exist_ok=True)
    zeilen, modus = [zeile], "a"
    if not config.ABRUFSTATISTIK.exists():
        modus = "w"
    else:
        with open(config.ABRUFSTATISTIK, encoding="utf-8", newline="") as f:
            r = csv.DictReader(f, delimiter="\t")
            if r.fieldnames != STAT_SPALTEN:   # ältere Datei: neu schreiben, Werte nach Spaltennamen übernehmen
                zeilen, modus = [*r, zeile], "w"
    with open(config.ABRUFSTATISTIK, modus, encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, STAT_SPALTEN, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        if modus == "w":
            w.writeheader()
        w.writerows(zeilen)


def _differenz(zeile, vorher):
    """Trägt die Zähler aus abruf.statistik() seit `vorher` in die Zeile ein."""
    nachher = abruf.statistik()
    zeile.update({k: (round(nachher[k] - vorher[k], 1) if k == "sekunden" else nachher[k] - vorher[k])
                  for k in STAT_ZAEHLER})


def _teil(pfad):
    return pfad.with_name(pfad.name.split(".")[0] + ".teil.jsonl")


def _fortsetzung(schluessel, pfad):
    """Gespeicherte Fortsetzung eines Vollabrufs und der gelesene Teil: (Fortsetzung, Objekte, Meldung). Ist sie
    unlesbar (Form, Zeitpunkt, fehlende oder unlesbare Teildatei), wird sie verworfen: (None, None, Meldung)."""
    fort = _zustand().get(f"{schluessel}_fortsetzung")
    if fort is None:
        return None, None, ""
    teil, grund, bisher = _teil(pfad), "", []
    seiten = fort.get("seiten", 0) if isinstance(fort, dict) else None
    if not isinstance(fort, dict):
        grund = "kein Objekt"
    elif not isinstance(fort.get("naechste"), str) or not fort["naechste"]:
        grund = "Folgeadresse fehlt"
    elif isinstance(seiten, bool) or not isinstance(seiten, int) or seiten < 0:
        grund = f"Seitenzahl unlesbar ({seiten!r})"
    elif _zeit(fort.get("start")) is None:
        grund = f"Startzeitpunkt unlesbar ({fort.get('start')!r})"
    elif seiten and not teil.exists():
        grund = f"Teildatei {teil.name} fehlt"
    elif teil.exists():
        try:
            bisher = [json.loads(z) for z in teil.read_text(encoding="utf-8").splitlines() if z.strip()]
            if not all(isinstance(o, dict) and isinstance(o.get("id"), str) for o in bisher):
                grund = f"Teildatei {teil.name} enthält Zeilen ohne Kennung"
        except (ValueError, RecursionError) as e:
            grund = f"Teildatei {teil.name} unlesbar ({e})"
    if not grund:
        return fort, bisher, ""
    meldung = f"Fortsetzung von {schluessel} verworfen ({grund}); der Vollabruf beginnt von vorn"
    _warnung(meldung)
    _zustand_setzen(f"{schluessel}_fortsetzung", None)
    teil.unlink(missing_ok=True)
    return None, None, meldung


def _nur_warnung(text, e, zeile, objekte, seiten, seit, pfad, schluessel):
    """Nur diese Liste endet, ohne Listenfehler und ohne Pause: Der letzte gültige Stand bleibt (nichts zusammengeführt,
    Zeitpunkt nicht weitergesetzt, eine Fortsetzung verworfen), Warnung mit Abhilfe (ABHILFE) im Log, in STAND.json
    (`abruf_warnungen`, gleich hier: ein späterer Abbruch einer anderen Liste verdrängt sie nicht) und in der
    Abrufstatistik (`warnung: …`). Heute nur die Organisationen mit Art `leer` (bis Runde 19 auch die Sitzungen mit Art
    `filter`; seit Runde 20 liest _abruf_liste sie dann vollständig). Liefert (letzter gültiger Stand, nicht die
    gelesenen Objekte; Meldung)."""
    art = getattr(e, "art", "")
    meldung = f"{text} (letzter gültiger Stand bleibt, kein Listenfehler): {e}"
    if art in ABHILFE:
        meldung += " – " + ABHILFE[art].format(liste=schluessel)
    _warnung(meldung)
    _zustand_setzen(f"{schluessel}_fortsetzung", None)
    _teil(pfad).unlink(missing_ok=True)
    _warnung_vermerken(schluessel, meldung)
    zeile.update(seiten=seiten, objekte=len(objekte), filter_wirksam=_filter_wirksam(objekte, seit),
                 ergebnis=f"warnung: {meldung}"[:300])
    return list(_vorhanden(pfad).values()), meldung


def _stand_zeit(schluessel):
    """Zeitpunkt aus STAND.json (etwa `meetings`, von fetch_meetings erst nach dem Schreiben gesetzt), ohne Nebenwirkung
    (anders als _stand legt eine unlesbare Datei hier nichts beiseite); None, wenn fehlend oder unlesbar."""
    try:
        s = json.loads(config.STAND.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return _zeit(s.get(schluessel)) if isinstance(s, dict) else None


def _in_dieser_nacht_gelesen(schluessel):
    """Zeitpunkt, zu dem die Liste in dieser Nacht zuletzt erfolgreich gelesen wurde, sonst None. Belege sind der
    Zustand `<liste>` (Beginn jenes Lesens; nach einer Fortsetzung der Beginn in der Vornacht) und der Zeitpunkt der
    Liste in STAND.json (_stamp nach dem Schreiben, also das Ende des Lesens, auch einer Fortsetzung; Prüfung r20n):
    Es gilt der spätere der Belege, die weniger als SPERRE_GLEICHE_NACHT zurückliegen (dieselbe Nacht); ein künftiger
    oder unlesbarer Zeitpunkt zählt nicht. So gilt eine Liste, deren Fortsetzung in dieser Nacht fertig wurde, als in
    dieser Nacht gelesen. Liest nur, schreibt keinen neuen Schlüssel (Vollabrufnächte schreiben denselben Zustand wie
    90928bc). Nicht für lokale Testserver (wie die 12-Stunden-Regel)."""
    if abruf.lokal(config.OPARL_BODY):
        return None
    jetzt = abruf.uhr()
    belege = [t for t in (_zeit(_zustand().get(schluessel)), _stand_zeit(schluessel))
              if t is not None and timedelta(0) <= jetzt - t < SPERRE_GLEICHE_NACHT]
    return max(belege) if belege else None


def _schon_gelesen(name, zuletzt, befund, zeile, pfad, seiten=0, filter_wirksam=""):
    """Zweiter Lauf in derselben Nacht (etwa nach einem Push auf main im Zeitfenster oder auf Knopfdruck), Sitzungen
    ohne angewandten Zeitfilter: Sie sind in dieser Nacht schon gelesen (`zuletzt`, _in_dieser_nacht_gelesen), also kein
    erneutes vollständiges Lesen (Entscheidung 10.11.2026: jede Nacht, nicht jeder Lauf). Letzter gültiger Stand,
    Zeitpunkt und Datei unverändert, keine Warnung in STAND.json, Zeile `übersprungen` in der Abrufstatistik. `befund`:
    Meldung des Befunds in diesem Lauf (nach den Seiten mit Zeitfilter) oder "" (ohne Anfrage, Vermerk aus einem
    früheren Lauf). Liefert (letzter gültiger Stand, Meldung) wie eine Warnung, damit fetch_meetings Datei und Zeitpunkt
    nicht neu schreibt."""
    meldung = (f"{name}: in dieser Nacht schon gelesen (zuletzt {zuletzt.isoformat(timespec='seconds')}), "
               f"{'Zeitfilter nicht angewandt' if befund else 'ohne Anfrage'}, nicht erneut vollständig gelesen; "
               "letzter gültiger Stand bleibt" + (f"; Befund: {befund}" if befund else ""))
    (_warnung if befund else print)(meldung)
    alle = list(_vorhanden(pfad).values())
    zeile.update(modus="übersprungen" if not befund else zeile["modus"], seiten=seiten, objekte=len(alle),
                 filter_wirksam=filter_wirksam, ergebnis=f"übersprungen: {meldung}"[:300])
    return alle, meldung


def _abruf_liste(name, url, pfad, schluessel, zeitfilter=True, warnungen=None, angenommen=None, voll_ohne_filter=""):
    """Inkrementeller Abruf einer Liste mit Statistik; schreibt die zusammengeführten Objekte als JSONL. Nimmt der Lauf
    für diese Liste einen kürzeren Stand an (RATSATLAS_KUERZER_ANNEHMEN, _zusammenfuehren), kommt `schluessel` in die
    Menge `angenommen` (für beratungen(); None: ohne Beratungen in diesem Aufruf, nichts vermerkt), bei papers und
    meetings (BERATUNGEN_AUS) auch in den Vermerk KUERZER_VERMERK im Zustand, damit ein Abbruch vor beratungen() die
    Beratungen nicht dauerhaft blockiert.
    Ein abgebrochener Vollabruf wird beim nächsten Lauf an der gelesenen Stelle fortgesetzt. `zeitfilter=False`: immer
    vollständig, ohne modified_since (organizations). `warnungen` (Art → Text): Ein Abbruch dieser Art beendet nur diese
    Liste (_nur_warnung; organizations: `leer`); die übrigen Listen laufen weiter.
    `voll_ohne_filter` (Text für Log und Abrufstatistik; meetings): Wendet der Server modified_since nicht an (Art
    `filter` im inkrementellen Lauf, nach der Seite mit dem Befund), liest der Lauf die Liste gleich vollständig, neu ab
    Seite 1 ohne modified_since (nicht über links.next der gefilterten Seite, siehe Moduldoku), und behandelt sie wie
    einen Vollabruf: 90-%-Regel, Stand ersetzt, Fortsetzung nach einem Abbruch; die Seiten mit Zeitfilter zählen zur
    Grenze je Lauf (liste(), `im_lauf`; schon mit ihnen erreicht: Art `obergrenze` ohne weitere Anfrage). Der Befund
    steht im Zustand (`<liste>_ohne_zeitfilter` mit `zeit` und `meldung`); ein Lauf, der die Liste ohne Befund liest
    (inkrementell mit wirksamem Filter oder vollständig, auch als Fortsetzung), entfernt ihn. Ist die Liste in dieser
    Nacht schon gelesen (_in_dieser_nacht_gelesen), liest ein weiterer Lauf sie nicht noch einmal vollständig: mit
    Vermerk ohne Anfrage, sonst nach dem Befund (_schon_gelesen). Endet das vollständige Lesen nach dem Befund unter 90 %
    des Stands (Art `leer`), nennt die Meldung den Anlass und die Abhilfe. Ohne `voll_ohne_filter` (papers) bricht der
    Lauf bei Art `filter` ab. Jede reguläre Aktualisierung einer Liste mit `warnungen` oder `voll_ohne_filter` entfernt
    ihre Warnung in STAND.json. Liefert (Objekte, Warnung): den zusammengeführten Stand und "", nach einer Warnung oder
    ohne erneutes Lesen in derselben Nacht den letzten gültigen Stand und die Meldung (fetch_meetings schreibt dann
    weder meetings.json noch ihren Zeitpunkt neu)."""
    warnungen = warnungen or {}
    objekte, seiten = [], 0
    vorher = abruf.statistik()
    start = datetime.now(timezone.utc)
    fort, bisher, verworfen = _fortsetzung(schluessel, pfad)
    seit = None if fort or not zeitfilter else _seit(schluessel)
    befund = None   # Zeitfilter in diesem Lauf nicht angewandt (voll_ohne_filter): Vermerk und Seiten mit Filter
    zeile = {"datum": _now(), "liste": name, "modus": "voll, fortgesetzt" if fort else "inkrementell" if seit else
             "voll, Fortsetzung verworfen" if verworfen else "voll"}
    try:
        if fort:
            start = _zeit(fort["start"])
            objekte, seiten = liste(url, start=fort["naechste"], objekte=bisher, seiten=fort.get("seiten", 0),
                                    verschiebung=verschiebung_erlaubt(fort.get("gespeichert")))
        else:
            # zweiter Lauf in derselben Nacht nach einem Befund (Vermerk) und erfolgreichem Lesen: ohne Anfrage
            vermerk = _zustand().get(f"{schluessel}_ohne_zeitfilter") if voll_ohne_filter and seit else None
            zuletzt = _in_dieser_nacht_gelesen(schluessel) if isinstance(vermerk, dict) else None
            if zuletzt:
                return _schon_gelesen(name, zuletzt, "", zeile, pfad)
            try:
                objekte, seiten = liste(url, seit)
            except Teilabbruch as e:
                if not (voll_ohne_filter and seit and e.art == "filter"):
                    raise
                # Zeitfilter nicht angewandt: dieselbe Liste in diesem Lauf vollständig, neu ab Seite 1 ohne Filter
                befund = {"vermerk": {"zeit": abruf.uhr().isoformat(timespec="seconds"), "meldung": str(e)[:300]},
                          "seiten": e.seiten, "filter_wirksam": _filter_wirksam(e.objekte, seit)}
                _zustand_setzen(f"{schluessel}_ohne_zeitfilter", befund["vermerk"])
                zuletzt = _in_dieser_nacht_gelesen(schluessel)
                if zuletzt:   # in dieser Nacht schon gelesen (vollständig oder inkrementell): nicht noch einmal
                    return _schon_gelesen(name, zuletzt, befund["vermerk"]["meldung"], zeile, pfad, e.seiten,
                                          befund["filter_wirksam"])
                # Grenze je Lauf: die Seiten mit Zeitfilter zählen mit; schon erreicht, folgt keine Anfrage mehr (vor
                # der ersten Seite ohne Filter kennt liste() die Seitengröße noch nicht)
                g = getattr(e, "groesse", 0)
                je_lauf = math.ceil(config.ABRUF_MAX_OBJEKTE / max(g, 1))
                if g and e.seiten >= je_lauf:
                    raise Teilabbruch(abruf.Abbruch(
                        f"Obergrenze je Nacht erreicht: {je_lauf} Seiten mit Zeitfilter in diesem Lauf "
                        f"({config.ABRUF_MAX_OBJEKTE} Objekte bei {g} je Seite, RATSATLAS_MAX_OBJEKTE); kein "
                        "vollständiges Lesen ohne modified_since in dieser Nacht", "obergrenze"),
                        e.objekte, None, e.seiten) from e
                print(f"{name}: {e}; die Liste wird in diesem Lauf vollständig ohne modified_since gelesen, neu ab "
                      "Seite 1", flush=True)
                seit = None
                zeile.update(modus="voll, Zeitfilter nicht angewandt", filter_wirksam=befund["filter_wirksam"])
                objekte, seiten = liste(url, im_lauf=e.seiten)
        alle, neu, geaendert, geloescht, kuerzer = _zusammenfuehren(
            pfad, objekte, voll=not seit, kuerzer_annehmen=schluessel in _listen_aus("RATSATLAS_KUERZER_ANNEHMEN"))
        _write(pfad, "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in alle))
        aenderung = {schluessel: start.isoformat(timespec="seconds"), f"{schluessel}_fortsetzung": None}
        if kuerzer and angenommen is not None:
            angenommen.add(schluessel)
            if schluessel in BERATUNGEN_AUS:   # gilt über einen Abbruch vor beratungen() hinaus
                aenderung[KUERZER_VERMERK] = {"zeit": abruf.uhr().isoformat(timespec="seconds"),
                                              "listen": sorted(_kuerzer_vermerkt() | {schluessel})}
        if not seit or voll_ohne_filter:
            # ohne Befund gelesen (vollständig, oder inkrementell mit wirksamem Filter): ein früherer Befund gilt nicht
            # mehr; nach einem Befund in diesem Lauf bleibt er vermerkt
            aenderung[f"{schluessel}_ohne_zeitfilter"] = befund and befund["vermerk"]
        _zustand_aendern(**aenderung)
        _teil(pfad).unlink(missing_ok=True)
        if warnungen or voll_ohne_filter:   # wieder regulär aktualisiert: Warnung dieser Liste entfällt
            _warnung_vermerken(schluessel, None)
        ergebnis = ["ok"] + ([kuerzer] if kuerzer else [])
        if befund:   # Log und Abrufstatistik: wie gelesen und warum
            wie = f"{voll_ohne_filter} ({seiten} Seiten ohne modified_since nach {befund['seiten']} mit Zeitfilter)"
            _warnung(f"{wie}; Befund: {befund['vermerk']['meldung']}")
            ergebnis[1:1] = [wie]
            ergebnis.append(f"Befund: {befund['vermerk']['meldung']}")
        zeile.update(seiten=seiten, objekte=len(alle), neu=neu, geaendert=geaendert, geloescht=geloescht,
                     filter_wirksam=befund["filter_wirksam"] if befund else _filter_wirksam(objekte, seit),
                     ergebnis="; ".join(ergebnis)[:300])
        return alle, ""
    except Teilabbruch as e:
        if e.art in warnungen:   # nur diese Liste beenden, die übrigen laufen weiter
            return _nur_warnung(warnungen[e.art], e, zeile, e.objekte, e.seiten, seit, pfad, schluessel)
        # Vollabruf: gelesenen Teil sichern und morgen eine Seite zurück fortsetzen (fängt bis zu einer Seite
        # Löschungen ab); eine veraltete Folgeseite (HTTP 404 oder 410 gleich zu Beginn der Fortsetzung, VERALTET_HTTP)
        # oder ein Abbruch aus OHNE_FORTSETZUNG (Schleife, Weiterleitung, Proxy, Adresse) verwirft die Fortsetzung,
        # dann beginnt der nächste Lauf von vorn. 401, 403 und andere Codes behalten sie (401/403 zählen weiter als
        # mögliche Sperre, moegliche_sperre)
        veraltet = (fort and e.art == "http" and getattr(e, "code", None) in VERALTET_HTTP
                    and e.seiten == fort.get("seiten", 0))
        verwerfen = veraltet or e.art in OHNE_FORTSETZUNG
        e.inkrementell = bool(seit)   # für den Hinweis am Ende des Zeitfensters (_abbruch_vermerken)
        if not seit and e.naechste and e.seiten and not verwerfen:
            config.RAW.mkdir(parents=True, exist_ok=True)
            _write(_teil(pfad), "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in e.objekte))
            # `gespeichert` bleibt, solange eine Fortsetzung die verschobene Zone nicht verlassen hat (keine ungelesene
            # Vorlage, nicht jünger als die Grenze, liste()): Die Verschiebung seit der ersten Speicherung besteht
            # weiter; ein künftiger Wert gilt als jetzt
            jetzt = abruf.uhr()
            alt = _zeit(fort.get("gespeichert")) if fort else None
            gespeichert = fort["gespeichert"] if alt is not None and alt <= jetzt and not e.verlassen else (
                jetzt.isoformat(timespec="seconds"))
            _zustand_setzen(f"{schluessel}_fortsetzung", {
                "naechste": e.zuletzt or e.naechste, "seiten": e.seiten, "start": start.isoformat(timespec="seconds"),
                "gespeichert": gespeichert})
            zeile["ergebnis"] = f"unterbrochen nach {e.seiten} Seiten, Fortsetzung im nächsten Lauf: {e}"[:300]
        else:
            if verwerfen:
                _zustand_setzen(f"{schluessel}_fortsetzung", None)
                _teil(pfad).unlink(missing_ok=True)
            zeile["ergebnis"] = f"abbruch: {e}"[:300]
        zeile.update(seiten=e.seiten, objekte=len(e.objekte),
                     filter_wirksam=befund["filter_wirksam"] if befund else _filter_wirksam(e.objekte, seit))
        raise
    except abruf.Abbruch as e:
        if e.art in warnungen:   # etwa `leer` aus _zusammenfuehren, nachdem die Liste vollständig gelesen ist
            return _nur_warnung(warnungen[e.art], e, zeile, objekte, seiten, seit, pfad, schluessel)
        if befund and e.art == "leer":
            # vollständiges Lesen nach dem Befund unter 90 % des Stands: Abbruch wie bei einem Vollabruf (Entscheidung
            # offen, TECHNIK.md), aber mit Anlass und Abhilfe in STAND.json und Seiten und Objekten in der Statistik
            zeile.update(seiten=seiten, objekte=len(objekte))
            neu = abruf.Abbruch(f"{e} (vollständiges Lesen nach nicht angewandtem Zeitfilter) – "
                                + ABHILFE["leer"].format(liste=schluessel), "leer")
            zeile["ergebnis"] = f"abbruch: {neu}"[:300]
            raise neu from e
        zeile["ergebnis"] = f"abbruch: {e}"[:300]
        raise
    except Exception as e:
        zeile["ergebnis"] = f"programmfehler: {type(e).__name__}: {e}"[:300]
        raise
    finally:
        _differenz(zeile, vorher)
        _statistik_sicher(zeile)


def _abruf_body():
    """Abruf des Bodys mit eigener Zeile `body` in der Abrufstatistik. Der Body muss die Listen `paper`, `meeting` und
    `organization` als Adressen nennen, sonst Abbruch der Art `unlesbar`."""
    vorher = abruf.statistik()
    zeile = {"datum": _now(), "liste": "body"}
    try:
        body = abruf.get_json(config.OPARL_BODY)
        fehlt = [f for f in ("paper", "meeting", "organization") if not isinstance(body.get(f), str) or not body[f]]
        if fehlt:
            raise abruf.Abbruch(f"unerwartete Antwortform (Body ohne Liste {', '.join(fehlt)}): {config.OPARL_BODY}",
                                "unlesbar")
        zeile.update(objekte=1, ergebnis="ok")
        return body
    except abruf.Abbruch as e:
        zeile["ergebnis"] = f"abbruch: {e}"[:300]
        raise
    except Exception as e:
        zeile["ergebnis"] = f"programmfehler: {type(e).__name__}: {e}"[:300]
        raise
    finally:
        _differenz(zeile, vorher)
        _statistik_sicher(zeile)


def fetch_organizations(body, angenommen=None):
    """Organisationen immer vollständig, ohne modified_since (auch im inkrementellen Lauf): eine kleine Liste (den
    Umfang in Köln misst Stufe 3), und Münster lehnt modified_since bei organization mit HTTP 401 ab
    (explore/ergebnisse/sessionnet_befunde.tsv; mandari ruft sie dann ohne Filter ab). So kann ein übergangener oder
    abgelehnter Zeitfilter hier die Vorlagen nicht blockieren; keine Filterprüfung. Ein Vollabruf unter 90 % des Stands
    (Art `leer`) beendet nur diese Liste (letzter gültiger Stand, Warnung in STAND.json `abruf_warnungen` mit der
    Abhilfe RATSATLAS_KUERZER_ANNEHMEN=organizations), damit er die Vorlagen nicht jede Nacht blockiert. `angenommen`:
    siehe _abruf_liste. Liefert (Organisationen, Warnung oder "")."""
    alle, warnung = _abruf_liste(
        "organizations", body["organization"], config.RAW / "organizations.jsonl", "organizations", zeitfilter=False,
        warnungen={"leer": "Organisationen unvollständig (unter 90 % des Stands), nicht aktualisiert"},
        angenommen=angenommen)
    orgs = [o for o in alle if not o.get("deleted")]
    vb = [o for o in orgs if o.get("organizationType") == "Verwaltungsbereich"]
    if not warnung:
        _write(config.ORGANIZATIONS, json.dumps(orgs, ensure_ascii=False))
        _write(config.VERWALTUNGSBEREICHE, json.dumps(vb, ensure_ascii=False))
        _stamp("organizations")
    print(f"{len(orgs)} Organisationen{' (letzter gültiger Stand)' if warnung else ''}, davon {len(vb)} "
          "Verwaltungsbereiche")
    return orgs, warnung


def _einladung(m):
    inv = m.get("invitation")
    return inv.get("accessUrl") if isinstance(inv, dict) else None


def _kennung(wert):
    """Verweis als Schlüssel: nur Text (eine Liste oder ein Objekt an dieser Stelle ergibt keinen Treffer)."""
    return wert if isinstance(wert, str) else None


def fetch_meetings(body, angenommen=None):
    """Sitzungen; ob Köln modified_since hier anwendet, ist ungemessen. Wendet der Server ihn nicht an, liest der Lauf
    die Sitzungen gleich vollständig (_abruf_liste mit `voll_ohne_filter`; Entscheidung 10.11.2026, jede Nacht neu, bis
    der Server den Filter wieder anwendet): meetings.json und ihr Zeitstempel aktualisiert, kein Listenfehler; in einem
    weiteren Lauf derselben Nacht nicht noch einmal (_schon_gelesen: letzter gültiger Stand, Datei und Zeitstempel
    unverändert). `angenommen`: siehe _abruf_liste. Liefert (Sitzungen, Warnung oder "")."""
    alle, warnung = _abruf_liste(
        "meetings", body["meeting"], config.RAW / "meetings_roh.jsonl", "meetings",
        voll_ohne_filter="Zeitfilter bei Sitzungen nicht angewandt, Sitzungen vollständig gelesen",
        angenommen=angenommen)
    meetings = [m for m in alle if not m.get("deleted")]
    keep = ("id", "name", "meetingState", "cancelled", "start", "end", "organization", "web")
    if not warnung:
        _write(config.MEETINGS, json.dumps(
            [{**{k: m.get(k) for k in keep}, "invitation": _einladung(m),
              "agenda_items": len(m.get("agendaItem") or [])} for m in meetings], ensure_ascii=False))
    terms = body.get("legislativeTerm") or []
    terms = [t for t in terms if isinstance(t, dict)]
    _write(config.LEGISLATIVE_TERMS, json.dumps(terms, ensure_ascii=False))
    if not warnung:
        _stamp("meetings")
    print(f"{len(meetings)} Sitzungen{' (letzter gültiger Stand)' if warnung else ''}, {len(terms)} Wahlperioden")
    return meetings, warnung


def fetch_papers(body, angenommen=None):
    """Vorlagen; `angenommen`: siehe _abruf_liste."""
    papers = _abruf_liste("papers", body["paper"], config.PAPERS, "papers", angenommen=angenommen)[0]
    _stamp("papers")
    print(f"{len(papers)} Vorlagen → {config.PAPERS}")
    return papers


def _kuerzer_vermerkt():
    """Listen aus dem Vermerk KUERZER_VERMERK im Zustand (nur papers und meetings; ein unlesbarer Vermerk lockert
    nichts)."""
    eintrag = _zustand().get(KUERZER_VERMERK)
    listen = eintrag.get("listen") if isinstance(eintrag, dict) else None
    return {x for x in listen if x in BERATUNGEN_AUS} if isinstance(listen, list) else set()


def beratungen(papers, meetings, angenommen=()):
    """Beratung → Sitzung und TOP im Format, das build.py aus OParl-Lite kennt. Fehlt in der Beratung die
    Organisation, wird sie aus der Sitzung übernommen und als abgeleitet markiert (`_organization_quelle`). Weniger als
    90 % der bisherigen Beratungen: Abbruch (Art `leer`), außer für papers oder meetings wurde tatsächlich ein kürzerer
    Stand angenommen: in diesem Lauf (`angenommen`, gesammelt von _abruf_liste) oder in einem früheren, der vor den
    Beratungen abbrach (Vermerk KUERZER_VERMERK im Zustand); dass die Liste in RATSATLAS_KUERZER_ANNEHMEN steht, genügt
    nicht. Ein leerer Stand (0 Beratungen) gilt bei einem bisherigen Stand über 0 nie. Der Vermerk wird erst nach dem
    Schreiben von beratungen.jsonl entfernt."""
    sitzung = {m["id"]: m for m in meetings}
    top = {}
    for m in meetings:
        for t in m.get("agendaItem") or []:
            if isinstance(t, dict) and _kennung(t.get("id")):
                top[t["id"]] = (t, m)
    zeilen, ohne_sitzung, ergaenzt = [], 0, 0
    for p in papers:
        for c in p.get("consultation") or []:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            t, m_top = top.get(_kennung(c.get("agendaItem")), (None, None))
            m = sitzung.get(_kennung(c.get("meeting"))) or m_top
            if not c.get("organization") and m and m.get("organization"):
                c["organization"] = list(m["organization"]) if isinstance(m["organization"], list) else [m["organization"]]
                c["_organization_quelle"] = "sitzung"
                ergaenzt += 1
            if not m and not t:
                ohne_sitzung += 1
                continue
            zeilen.append({
                "uri": c["id"],
                "meeting": {"uri": m["id"], "name": m.get("name"), "startDate": m.get("start"),
                            "cancelled": bool(m.get("cancelled"))} if m else None,
                "agendaItem": {"uri": t["id"], "number": t.get("number"), "name": t.get("name"),
                               "result": t.get("result"), "public": t.get("public")} if t else None,
            })
    bisher = _jsonl_count(config.BERATUNGEN)
    if len(zeilen) < MIN_ANTEIL * bisher:   # unvollständig: Abbruch, keine Sperre
        im_lauf = set(BERATUNGEN_AUS) & set(angenommen)
        erlaubt = im_lauf | _kuerzer_vermerkt()
        if not erlaubt or not zeilen:   # leer nie, auch nicht gelockert
            raise abruf.Abbruch(f"Beratungen: nur {len(zeilen)} statt bisher {bisher}" + (
                " (ein leerer Stand wird nie angenommen, auch nicht mit RATSATLAS_KUERZER_ANNEHMEN)" if erlaubt else ""),
                "leer")
        herkunft = "" if im_lauf else f"; Vermerk {KUERZER_VERMERK} eines früheren Laufs: {', '.join(sorted(erlaubt))}"
        _warnung(f"Beratungen: kürzerer Stand angenommen: {len(zeilen)} statt bisher {bisher} "
                 f"(RATSATLAS_KUERZER_ANNEHMEN{herkunft})")
    _write(config.BERATUNGEN, "".join(json.dumps(z, ensure_ascii=False) + "\n" for z in zeilen))
    # Ergänzte Organisationen in papers.jsonl übernehmen, damit build.py sie liest
    _write(config.PAPERS, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in papers))
    if KUERZER_VERMERK in _zustand():   # erst jetzt: die Beratungen sind auf dem angenommenen Stand
        _zustand_setzen(KUERZER_VERMERK, None)
    _stamp("consultations_lite")
    print(f"{len(zeilen)} Beratungen mit Sitzung oder TOP, {ohne_sitzung} ohne, {ergaenzt} Gremien aus der Sitzung")


def fetch_all():
    """Vollständiger bzw. inkrementeller Lauf. Ein Abbruch (abruf.Abbruch) hält den letzten gültigen Stand und vermerkt
    den Fehler; Abbrüche nach `moegliche_sperre` zählen als Nacht mit möglicher Sperre, Abbrüche der Art `liste`,
    `adresse` oder `filter` als Nacht mit fehlerhafter Liste, das Ende des Zeitfensters und die Obergrenze je Nacht
    nur als Hinweis. Alles andere (auch ein
    RuntimeError ohne Art) ist ein Programm- oder Einstellungsfehler: vermerkt, laut mit Traceback, kein Sperrverdacht.
    Nach jedem Abbruch außer dem Ende des Zeitfensters folgt in derselben Nacht kein weiterer Lauf (`letzter_abbruch`).
    Endet nur eine Nebenliste mit Warnung (_nur_warnung: unvollständige Organisationen), gilt der Lauf als
    vollständig; die Warnung steht in STAND.json unter `abruf_warnungen` (dort schon bei ihrem Auftreten vermerkt, ein
    vollständiger Lauf entfernt sie nicht). Sitzungen ohne angewandten Zeitfilter liest der Lauf vollständig
    (_abruf_liste, `voll_ohne_filter`)."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    # Sperre und Zeitfenster sind kein Ausfall: der Lauf wird übersprungen, ohne den Stand als fehlgeschlagen zu markieren
    lokal = abruf.lokal(config.OPARL_BODY)
    grund = ("Abruf gesperrt: Die Stadt Köln ist noch nicht informiert (RATSATLAS_STADT_INFORMIERT)"
             if not abruf.freigegeben(config.OPARL_BODY) else
             f"außerhalb des Zeitfensters {config.ABRUF_ZEITFENSTER} Uhr" if not lokal and not abruf.im_zeitfenster()
             else None)
    zustand, pause = {}, False
    if not grund:
        try:
            zustand = _zustand_pruefen()
        except ZustandUnlesbar as e:   # keine Anfrage; laut, bis jemand die Datei prüft (jeder Lauf bricht so ab)
            _stand_setzen(abruf_fehler={"zeit": _now(), "meldung": str(e)[:300]})
            raise
        grund = _pause_grund(zustand, lokal)
        pause = bool(grund)
    if grund:
        _stand_setzen(abruf_uebersprungen={"zeit": _now(), "grund": grund})
        if pause:   # 12-Stunden-Regel, Retry-After, Pause nach drei Nächten: als Warnung im Workflow sichtbar
            _warnung(f"Abruf übersprungen ({grund}); letzter Stand bleibt.")
        else:       # gesperrt oder außerhalb des Zeitfensters (etwa ein Push tagsüber): kein Befund
            print(f"Abruf übersprungen ({grund}); letzter Stand bleibt.")
        return
    try:
        _einstellungen_pruefen()
        body = _abruf_body()
        angenommen = set()   # Listen mit in diesem Lauf angenommenem kürzerem Stand (RATSATLAS_KUERZER_ANNEHMEN)
        fetch_organizations(body, angenommen)
        papers = fetch_papers(body, angenommen)
        meetings, _ = fetch_meetings(body, angenommen)
        beratungen(papers, meetings, angenommen)
        _stamp("abruf_ok")
        _zustand_aendern(sperre_verdacht=None, listenfehler=None, tlsfehler=None, letzter_abbruch=None, nicht_vor=None)
        # Meldungen früherer Läufe gelten nicht mehr (die Seite zeigte sonst dauerhaft „fehlgeschlagen“)
        _stand_entfernen("abruf_fehler", "abruf_hinweis", "abruf_uebersprungen")
    except abruf.Abbruch as e:
        _abbruch_vermerken(e, zustand)
    except Exception as e:
        # Programm- oder Einstellungsfehler (auch eine unerwartete Form tief in einem Objekt, ein RuntimeError ohne Art
        # wie RecursionError oder ZustandUnlesbar mitten im Lauf): kein Sperrverdacht; vermerken und mit Traceback
        # abbrechen, damit der Fehler im Workflow sichtbar wird. In derselben Nacht kein weiterer Lauf.
        try:
            _zustand_setzen("letzter_abbruch", {"zuletzt": abruf.uhr().isoformat(timespec="seconds"),
                                                "art": "programmfehler", "code": None,
                                                "meldung": f"{type(e).__name__}: {e}"[:300]})
        except Exception as f:   # z. B. Zustand unlesbar: den eigentlichen Fehler nicht verdrängen
            _warnung(f"Abbruch nicht im Zustand vermerkt ({type(f).__name__}: {f})")
        _stand_setzen(abruf_fehler={"zeit": _now(), "meldung": f"Programmfehler ({type(e).__name__}: {e})"[:300]})
        raise


def _einstellungen_pruefen():
    """Einstellungsfehler vor der ersten Anfrage laut ablehnen (ValueError wie andere Einstellungsfehler, kein
    Sperrverdacht): RATSATLAS_LIMIT keine positive ganze Zahl, RATSATLAS_MAX_OBJEKTE unter max_objekte_mindestens() (0,
    negativ oder so klein, dass eine Fortsetzung nicht über die wiederholte Seite und die Seitenverschiebung
    hinauskäme), unbekannte Listen in RATSATLAS_KUERZER_ANNEHMEN oder RATSATLAS_VOLLABRUF (außer „ja“), leerer Kontakt
    (RATSATLAS_KONTAKT) bei einem Ziel, das kein lokaler Testserver ist: Der User-Agent nennt den Kontakt (CLAUDE.md
    5.1), auch vor der Anfrage des Bodys."""
    if not abruf.lokal(config.OPARL_BODY) and not config.KONTAKT:
        raise ValueError("RATSATLAS_KONTAKT fehlt (Kontakt im User-Agent ist Pflicht, CLAUDE.md 5.1; in GitHub Actions "
                         "als Repository-Variable setzen); keine Anfrage gesendet")
    mindestens, g = max_objekte_mindestens(), _seitengroesse()
    if config.ABRUF_MAX_OBJEKTE < mindestens:
        limit = "" if config.ABRUF_SEITENGROESSE else f" leer, gerechnet mit {g}"
        raise ValueError(f"RATSATLAS_MAX_OBJEKTE={config.ABRUF_MAX_OBJEKTE} liegt unter {mindestens} (zwei Seiten zu "
                         f"{g} plus die größte Seitenverschiebung von {VERSCHIEBUNG_HOECHSTENS} Objekten, aufgerundet "
                         f"auf Seiten zu {g}; Annahme: der Server liefert {g} Objekte je Seite wie verlangt, "
                         f"RATSATLAS_LIMIT{limit}); keine Anfrage gesendet")
    for variable, alle in (("RATSATLAS_KUERZER_ANNEHMEN", False), ("RATSATLAS_VOLLABRUF", True)):
        unbekannt = sorted(_listen_aus(variable, alle) - set(LISTEN))
        if unbekannt:
            raise ValueError(f"{variable}: unbekannte Liste {', '.join(unbekannt)} (erlaubt: {', '.join(LISTEN)}"
                             f"{', oder ja' if alle else ''}); keine Anfrage gesendet")


def _weiter(e):
    """Wie der Abruf in der nächsten Nacht weitergeht, aus dem Zustand nach dem Abbruch (nicht aus der abbrechenden
    Liste): Steht eine Fortsetzung aus, wird sie fortgesetzt, sonst beginnt der Abruf erneut."""
    if any(k.endswith("_fortsetzung") for k in _zustand()):
        return "Fortsetzung in der nächsten Nacht"
    if getattr(e, "inkrementell", False):
        return ("der inkrementelle Abruf beginnt in der nächsten Nacht erneut (ein inkrementeller Lauf speichert keine "
                "Fortsetzung)")
    return "der Abruf beginnt in der nächsten Nacht erneut"


def _naechte_zaehlen(zustand, schluessel, jetzt, eintrag, neu):
    """Nächte zählen, nicht Läufe (`listenfehler`, `tlsfehler`): Ein weiterer Abbruch innerhalb von 12 Stunden zählt
    nicht noch einmal. Setzt beim Zählen neu[schluessel]; liefert die Zahl der Nächte."""
    bisher = zustand.get(schluessel) or {}
    zuletzt = _zeit(bisher.get("zuletzt"))
    if zuletzt is not None and jetzt - zuletzt < SPERRE_GLEICHE_NACHT:
        return bisher.get("naechte", 1)
    neu[schluessel] = {"naechte": bisher.get("naechte", 0) + 1, **eintrag}
    return neu[schluessel]["naechte"]


def _abbruch_vermerken(e, zustand):
    """Abbruch vermerken: zuerst den Zustand (letzter Abbruch für die 12-Stunden-Regel, Nacht mit möglicher Sperre nach
    `moegliche_sperre`, Retry-After über die Nacht hinaus, Nacht mit fehlerhafter Liste nach LISTENFEHLER), dann
    STAND.json. Das Ende des Zeitfensters und die Obergrenze je Nacht (etwa bei einem Vollabruf über mehrere Nächte)
    sind kein Fehler: nur ein neutraler Hinweis, wie es weitergeht (_weiter, aus dem Zustand); nach der Obergrenze gilt
    die 12-Stunden-Regel (höchstens einmal je Nacht bis zur Grenze), nach dem Ende des Zeitfensters nicht. Jeder andere
    Abbruch erscheint als Warnung (_warnung, in GitHub Actions ::warning::; der Abrufschritt bleibt grün), bei möglicher
    Sperre mit der Zahl der Nächte."""
    jetzt = abruf.uhr()
    zeit = jetzt.isoformat(timespec="seconds")
    art = getattr(e, "art", "")
    if art in ("zeitfenster", "obergrenze"):
        weiter = _weiter(e)
        grund = "Das Zeitfenster endete während des Abrufs" if art == "zeitfenster" else "Obergrenze je Nacht erreicht"
        if art == "obergrenze":
            _zustand_setzen("letzter_abbruch", {"zuletzt": zeit, "art": art, "code": None, "meldung": str(e)[:300]})
        _stand_entfernen("abruf_fehler")
        _stand_setzen(abruf_hinweis={"zeit": _now(), "meldung": f"{grund}, {weiter}. {e}"[:400]})
        print(f"Abruf unterbrochen ({grund}), {weiter}: {e}")
        return
    neu = {"letzter_abbruch": {"zuletzt": zeit, "art": art, "code": getattr(e, "code", None),
                               "meldung": str(e)[:300]}}
    eintrag = {"zuletzt": zeit, "art": art, "meldung": str(e)[:300]}
    if art == "tls":   # vermutlich Einstellung der Ausführungsumgebung, keine Sperrnacht: laut, damit sie behoben wird
        naechte = _naechte_zaehlen(zustand, "tlsfehler", jetzt, eintrag, neu)
        _warnung(f"Zertifikatsprüfung fehlgeschlagen ({naechte}. Nacht ohne vollständigen Lauf; nach {TLS_NAECHTE} "
                 f"Nächten {TLS_PAUSE.days} Tage Pause); vermutlich eine Einstellung der Ausführungsumgebung (CA eines "
                 f"Proxys), Zertifikat der Gegenseite oder Sperrseite nicht ausgeschlossen; in derselben Nacht kein "
                 f"weiterer Lauf. {e}"[:500])
    if moegliche_sperre(e):
        verdacht = zustand.get("sperre_verdacht") or {}
        neu["sperre_verdacht"] = {"naechte": verdacht.get("naechte", 0) + 1, "zuletzt": zeit, "art": art,
                                  "code": getattr(e, "code", None), "meldung": str(e)[:300]}
    nicht_vor = getattr(e, "nicht_vor", None)
    if nicht_vor is not None:   # Retry-After über die Nacht hinaus; ein späterer gespeicherter Zeitpunkt bleibt
        alt = _zeit(zustand.get("nicht_vor"))
        if alt is None or nicht_vor > alt:
            neu["nicht_vor"] = nicht_vor.isoformat(timespec="seconds")
    hinweis = None
    if art in LISTENFEHLER:
        naechte = _naechte_zaehlen(zustand, "listenfehler", jetzt, eintrag, neu)
        if getattr(e, "grenze_je_lauf", False):   # inkrementeller Lauf an der Grenze je Lauf: erreicht sie jede Nacht
            folge = ("ein inkrementeller Lauf erreichte die Grenze je Lauf (RATSATLAS_MAX_OBJEKTE) und beginnt jede "
                     "Nacht erneut; Abhilfe: einmal mit RATSATLAS_VOLLABRUF=ja (Vollabruf, über Nächte fortgesetzt)")
        else:
            folge = ("Zeitfilter nicht angewandt, Abbruch nach der ersten ungefilterten Seite; " if art == "filter"
                     else "keine Fortsetzung dieser Liste; ") + _weiter(e)
        hinweis = (f"Abbruch wegen einer fehlerhaften Liste ({art}), {naechte}. Nacht ohne vollständigen Lauf; "
                   f"{folge}. Nach {LISTENFEHLER_NAECHTE} Nächten {LISTENFEHLER_PAUSE.days} Tage Pause. {e}")[:400]
        _warnung(hinweis)
    _zustand_aendern(**neu)
    werte = {"abruf_fehler": {"zeit": _now(), "meldung": str(e)[:300]}}
    if hinweis:
        werte["abruf_hinweis"] = {"zeit": _now(), "meldung": hinweis}
    _stand_setzen(**werte)
    if hinweis or art == "tls":   # schon oben als Warnung gemeldet
        print(f"Abruf abgebrochen, letzter gültiger Stand bleibt: {e}")
    else:   # sonst bliebe der Abbruch im grünen Abrufschritt unbemerkt (Generalprobe 09.11.2026)
        sperre = neu.get("sperre_verdacht")
        zusatz = (f" Nacht mit möglicher Sperre ({sperre['naechte']}. ohne vollständigen Lauf; nach {SPERRE_NAECHTE} "
                  f"Nächten {SPERRE_PAUSE.days} Tage Pause)." if sperre else "")
        _warnung(f"Abruf abgebrochen, letzter gültiger Stand bleibt; in derselben Nacht kein weiterer Lauf.{zusatz} "
                 f"{e}"[:600])
    if os.environ.get("RATSATLAS_STRENG") == "ja":
        raise e
