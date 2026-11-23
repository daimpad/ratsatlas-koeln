"""Kölner Gremien für „Wer entscheidet“ (Entscheidung 21.11.2026 (2), Pull Request 4a): data/export/koeln/gremien.json.

Eigenes Kölner Modul (F4): Aus Bonn übernimmt es nur das Bedienmuster; prozessarten.py, soll.json und besetzung.py
bleiben unter ihren Freigaben abgeschaltet und werden nicht eingebunden. Keine Besetzung, keine Mitglieder, keine Namen
von Personen: Aus OParl ausgewertet werden nur die Organisationen (Kennung, Name, `classification`, `endDate`, `web`),
die Sitzungen (wie in zeit.json, dazu ihr Verweis `organization` aus meetings.json), die Stationen der Prozesslinie und
die Organisation der Beratungen (für vorlagen_12m, auch bei aufgelösten Gremien ohne Kennung an der Station, G6, und für
das Log).
Freigabe „gremien“ (config.ZUSATZTHEMEN); ohne sie schreibt export weder diese Datei noch aemter.json noch die Kennung
des Gremiums an den Stationen und in suche.json.

Aufgenommen (F5) sind Organisationen der Klassen „Rat“, „Fachausschüsse und weitere Gremien“ und „Bezirksvertretungen“
(OParl `classification`; Messung vom 09.11.2026: 1, 63 und 9 von 96 Organisationen). Nicht aufgenommen sind „Fraktionen
und Gruppen“ (gemessen 23) und Organisationen mit anderer oder ohne Klasse (in Köln gemessen keine; in den Testdaten die
erfundenen Dienststellen). Gruppe je Gremium (`gruppe`, F6):
- rat: Klasse „Rat“;
- bezirksvertretung: Klasse „Bezirksvertretungen“; `stadtbezirk` aus dem Namen (build.bv_bezirk), nur wenn er einer der
  neun Kölner Stadtbezirke ist (geocode.BEZIRKE_KOELN);
- ausschuss: Klasse „Fachausschüsse und weitere Gremien“, nicht aufgelöst, und der Name ergibt über ausschuesse.abschnitt
  einen Paragrafen der Zuständigkeitsordnung, den keine andere nicht aufgelöste Organisation dieser Klasse ergibt
  (eindeutiger Treffer); `paragraf` nur hier. Verglichen wird nur der Name, nicht der Kurzname;
- uebrige: die übrigen der Klasse „Fachausschüsse und weitere Gremien“ (ohne Treffer, mehrdeutig oder aufgelöst).
Aufgelöst (F5) ist ein Gremium, dessen `endDate` vor dem Datenstand liegt: Es bleibt in der Datei, mit `end_date` (wie
in der Quelle) und `aufgeloest`, für die Liste „frühere Gremien zeigen“. Ein `endDate` am Datenstand oder danach steht
als `end_date` ohne `aufgeloest` da.

Kennung (`key`, F12): aus der OParl-Kennung der Organisation der Teil nach dem letzten „/organizations/“ (ohne diesen
Teil der letzte Abschnitt des Pfads), kleingeschrieben, jede Folge anderer Zeichen als a–z und 0–9 als „-“ (erfunden:
„…/organizations/gr/12“ ergibt „gr-12“). Ergeben zwei Organisationen der Tabelle dieselbe Kennung, erhalten beide die
ersten 8 Zeichen des SHA-1 ihrer OParl-Kennung als Zusatz. Die Kennung bleibt gleich, solange die Stadt die OParl-Kennung
behält und keine weitere Organisation der Tabelle dieselbe Kennung ergibt: Kommt eine solche hinzu, erhalten beide den
Zusatz, und die bisherige Kennung ändert sich (fällt eine weg, verliert die andere ihn). Dieselbe Kennung steht an den
Stationen der Prozesslinie (`process[].gremium_key`, export._station) und in suche.json (Liste `gremium_keys`, je Zeile
die Spalte export.SUCHE_SPALTE_KENNUNGEN; Entscheidung 21.11.2026 (3) (G4)), dort nur bei Gremien dieser Datei, die am
Datenstand nicht aufgelöst sind (kennungen mit Datenstand; G6: kein Link im Vorgang auf ein aufgelöstes Gremium).

Zeitraum „in 12 Monaten“ (F7): 365 Tage vor dem Datenstand wie gebietszahlen.window_start, also Tage nach `seit` bis
einschließlich `bis` (wie gebietszahlen.recent). Datenstand ist der Stichtag von „Aktuell in Köln“ (export.stichtag: der
spätere der Kölner Tage des Abrufs der Vorlagen und der letzten regulären Aktualisierung der Sitzungen).
- sitzungen_12m: Sitzungen aus zeit.json im Zeitraum, die in meetings.json auf die Organisation verweisen (OParl
  `organization` der Sitzung, jede dort genannte Organisation; nicht über den Gremiennamen), ohne abgesagte
  (export.absage: OParl `cancelled` oder Hinweis „abgesagt“ aus dem Namen);
- vorlagen_12m: verschiedene Vorlagen der Gebietsdateien (jede einmal) mit einer Station dieses Gremiums an einem
  Sitzungstag im Zeitraum, deren Sitzung nicht abgesagt ist (export.absage über die Station, die `cancelled` und
  `hinweis` trägt). Das Gremium der Station ist die Organisation der Beratung (beratungen: Vorlage und `position` in der
  Tabelle consultation), auch bei aufgelösten Gremien, die an der Station keine Kennung tragen (G6); ohne diese Angabe
  (direkter Aufruf von daten) die Kennung `gremium_key` an der Station. Eine Vorlage, die in keiner Gebietsdatei steht
  (etwa ohne Datum und ohne Ortsbezug), zählt nicht (Auslegung von F7, beim Auftraggeber offen); wie viele solche
  Vorlagen eine Beratung eines Gremiums der Datei im Zeitraum haben, zählt das Log (vorlagen_ausserhalb);
- naechste_sitzung: die erste Sitzung ab dem Datenstand (am Tag des Datenstands oder danach), die auf die Organisation
  verweist und nicht abgesagt ist (nach Tag, eine Sitzung ohne Uhrzeit hinter denen mit Uhrzeit am selben Tag, sonst in
  der Reihenfolge von zeit.json): `date`, `time` (Kölner Zeit, wie zeit.json; ohne Uhrzeit null), `hinweis` nur
  „verschoben“, `web`, `source_object`; ohne solche Sitzung fehlt das Feld. Sitzungen am Tag des Datenstands zählen als
  kommend wie in „Aktuell in Köln“ (Entscheidung 21.11.2026 (3) (G7), Pull Request 4b) und zugleich bei sitzungen_12m
  (bis einschließlich Datenstand, F7). Im Sommer beginnt der Lauf um 0:10 Uhr Kölner Zeit; der Datenstand ist dann der
  gerade begonnene Tag, und seine Sitzungen stehen noch bevor. Bis Pull Request 4b zählten Sitzungen am Tag des
  Datenstands als vergangen, und die nächste Sitzung begann am Tag danach;
- folgende_sitzung: nur, wenn die nächste Sitzung am Tag des Datenstands liegt, die erste Sitzung nach diesem Tag mit
  derselben Regel und denselben Feldern (Entscheidung 23.11.2026 (1) (E2)); weitere Sitzungen am Tag des Datenstands
  überspringt sie. Ohne solche Sitzung fehlt das Feld. Der Grund: Der Lauf beginnt im Winter um 22:10 Uhr UTC, also um
  23:10 Uhr Kölner Zeit, und eine Sitzung am Abend des Datenstands ist dann vorbei. Blendet die Seite nach dem Kölner
  Tag der Besucher:innen aus, was vorbei ist, bleibt ihr bis zum nächsten Lauf die folgende Sitzung.
Ist die Liste der Sitzungen beim letzten Abruf nicht aktualisiert worden (export.sitzungsliste_aktuell, dieselbe Regel
wie die Karte „Kommende Sitzungen“ in „Aktuell in Köln“), fehlen naechste_sitzung und folgende_sitzung bei allen
Gremien, und `meta.sitzungsliste_nicht_aktuell` nennt den Stand der Liste (sitzungsliste); die Zahlen in 12 Monaten
bleiben, nach dem Stand der Liste.
Sitzungen ohne Verweis auf ein Gremium dieser Datei und Beratungen ohne solche Organisation zählt das Log von `export`
je Grund (zeilen_log, nur Zahlen), dazu die Sitzungen ohne Verweis auf eine Organisation ab dem Datenstand
(ohne_organisation_kommend): Sie zählen für kein Gremium, auch nicht als nächste oder folgende Sitzung, auch wenn ihr
Gremium aus dem Sitzungsnamen (export.gremium_der_sitzung) dem Namen eines Gremiums der Datei gleicht. check
(check.gremien) rechnet die Datei mit denselben Funktionen nach."""
import hashlib
import json
import re
from collections import Counter

from . import ausschuesse, config, gebietszahlen, process as proc

DATEI = "gremien.json"
FUNKTION = "gremien"
KLASSE_RAT, KLASSE_AUSSCHUESSE, KLASSE_BV = "Rat", "Fachausschüsse und weitere Gremien", "Bezirksvertretungen"
KLASSE_FRAKTIONEN = "Fraktionen und Gruppen"
KLASSEN = (KLASSE_RAT, KLASSE_AUSSCHUESSE, KLASSE_BV)
GRUPPEN = ("rat", "ausschuss", "bezirksvertretung", "uebrige")
GRUPPEN_TEXT = {"rat": "Rat", "ausschuss": "Ausschüsse mit Paragraf der Zuständigkeitsordnung",
                "bezirksvertretung": "Bezirksvertretungen", "uebrige": "übrige Gremien"}
# Felder je Gremium und je nächster und folgender Sitzung, sonst keine (keine Besetzung, keine Namen von Personen);
# check.gremien meldet jedes andere Feld
FELDER = ("key", "name", "gruppe", "stadtbezirk", "paragraf", "end_date", "aufgeloest", "web", "sitzungen_12m",
          "vorlagen_12m", "naechste_sitzung", "folgende_sitzung", "source_object")
PFLICHT = ("key", "name", "gruppe", "sitzungen_12m", "vorlagen_12m", "source_object")
FELDER_SITZUNG = ("date", "time", "hinweis", "web", "source_object")
# `sitzungsliste_nicht_aktuell` nur, wenn die Liste der Sitzungen beim letzten Abruf nicht aktualisiert worden ist
META_FELDER = ("datenstand", "zeitraum", "sources", "namensnennung", "zustaendigkeitsordnung", "sitzungsliste_nicht_aktuell",
               "gruppen", "note")
NOTE = ("Gremien aus der OParl-API der Stadt Köln: Rat, Fachausschüsse und weitere Gremien, Bezirksvertretungen; ohne "
        "Fraktionen und Gruppen, ohne Besetzung und ohne Namen von Personen. Abgeleitet (pipeline/gremien.py): Gruppe, "
        "Stadtbezirk aus dem Namen der Bezirksvertretung, Paragraf der Zuständigkeitsordnung nur bei eindeutigem Treffer "
        "des Namens, aufgelöst bei einem Enddatum vor dem Datenstand, Sitzungen und Vorlagen in 12 Monaten (Zeitraum "
        "nach `seit` bis `bis`) ohne abgesagte Sitzungen (OParl cancelled oder Hinweis „abgesagt“ aus dem Namen), nächste "
        "Sitzung ab dem Datenstand und, wenn sie am Datenstand liegt, die folgende Sitzung danach (keine, wenn die "
        "Liste der Sitzungen beim letzten Abruf nicht aktualisiert worden ist).")
# Aus der Zuständigkeitsordnung stammt nur der Paragraf; der Name jedes Gremiums kommt aus der OParl-API (Nachprüfung 4a)
HINWEIS_ZUSTO = ("Übernommen ist nur der Paragraf eines Ausschusses, zugeordnet über den Namen der Organisation in der "
                 "OParl-API (nur bei eindeutigem Treffer); der Name des Gremiums stammt aus der OParl-API, kein Text der "
                 "Satzung. Die Lizenz der Satzung ist nicht geklärt.")
HINWEIS_SITZUNGSLISTE = ("Die Liste der Sitzungen ist beim letzten Abruf nicht aktualisiert worden (ausgesetzt, Warnung "
                         "oder Fehler): keine nächste Sitzung, wie in „Aktuell in Köln“; Sitzungen in 12 Monaten nach dem "
                         "Stand der Liste.")

_ANDERE = re.compile(r"[^a-z0-9]+")
_DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")


def an():
    """Freigabe „gremien“ (config.ZUSATZTHEMEN)."""
    return bool(config.ZUSATZTHEMEN.get(FUNKTION))


def _rohschluessel(oparl_id):
    teil = (oparl_id.rsplit("/organizations/", 1)[1] if "/organizations/" in oparl_id
            else oparl_id.rstrip("/").rsplit("/", 1)[-1])
    return _ANDERE.sub("-", teil.lower()).strip("-")


def schluessel(ids):
    """{OParl-Kennung: Kennung} für die Organisationen `ids` (alle der Tabelle, damit eine Kennung nicht davon abhängt,
    welche aufgenommen sind); Regel in der Modulbeschreibung."""
    roh = {i: _rohschluessel(i or "") for i in ids}
    zahl = Counter(roh.values())

    def mit_zusatz(i, k):
        return "-".join(x for x in (k, hashlib.sha1((i or "").encode("utf-8")).hexdigest()[:8]) if x)
    return {i: k if k and zahl[k] == 1 else mit_zusatz(i, k) for i, k in roh.items()}


def organisationen(db):
    """Organisationen der Datenbank (Tabelle organization) als dicts mit id, name, classification, end_date, web; nach
    OParl-Kennung sortiert."""
    return [dict(zip(("id", "name", "classification", "end_date", "web"), r)) for r in
            db.execute("SELECT id, name, classification, end_date, web FROM organization ORDER BY id")]


def aufgenommen(o):
    """Steht die Organisation in gremien.json? Nur nach ihrer Klasse (KLASSEN), unabhängig vom Datenstand."""
    return o.get("classification") in KLASSEN


def kennungen(orgs, datenstand=None):
    """{OParl-Kennung: Kennung} der aufgenommenen Organisationen. Mit `datenstand` ohne die an diesem Tag aufgelösten
    (aufgeloest): die Kennungen an den Stationen der Prozesslinie und in suche.json (Entscheidung 21.11.2026 (3) (G6)).
    Die Kennung selbst bildet schluessel über alle Organisationen der Tabelle; sie hängt nicht davon ab, welche aufgelöst
    sind."""
    alle = schluessel([o["id"] for o in orgs])
    return {o["id"]: alle[o["id"]] for o in orgs if aufgenommen(o) and not (datenstand and aufgeloest(o, datenstand))}


def kennungen_der_vorlage(p):
    """Kennungen der Gremien an den Stationen der Vorlage `p` (`process[].gremium_key`), sortiert und ohne Doppelte: die
    Spalte der Kennungen in suche.json (export._search_index, check.suche_gremien)."""
    return sorted({s["gremium_key"] for s in p.get("process") or () if s.get("gremium_key")})


def beratungen(db):
    """{(OParl-Kennung der Vorlage, position): OParl-Kennung der Organisation der Beratung} aus der Tabelle consultation:
    das Gremium jeder Station der Prozesslinie (`source_object` der Vorlage, `position` der Station), auch wenn die
    Station keine Kennung trägt (aufgelöstes Gremium, G6)."""
    return {(pid, pos): o for pid, pos, o in db.execute("SELECT paper_id, position, organization_id FROM consultation")}


def stationen_aufgeloester(db, papers, stand_tag):
    """Für das Log (nur Zahlen): Stationen in `papers`, deren Beratung einem Gremium der Datei gehört, das am Datenstand
    `stand_tag` aufgelöst ist; sie tragen keine Kennung (G6)."""
    weg = {o["id"] for o in organisationen(db) if aufgenommen(o) and aufgeloest(o, stand_tag)}
    org = beratungen(db)
    return sum(org.get((p.get("source_object"), s.get("position"))) in weg
               for p in papers for s in p.get("process") or ())


def aufgeloest(o, datenstand):
    """Aufgelöst: `end_date` ist ein lesbares Datum vor dem Datenstand (Kölner Tag, JJJJ-MM-TT)."""
    ende = (o.get("end_date") or "")[:10]
    return bool(_DATUM.fullmatch(ende)) and ende < datenstand


def einordnen(orgs, datenstand):
    """Gruppe je aufgenommener Organisation ({OParl-Kennung: {"gruppe", "stadtbezirk" oder "paragraf", wo belegt}}),
    die nicht aufgenommenen je Grund (Counter: „fraktionen“, „ohne_klasse“) und je Eintrag in ausschuesse.AUSSCHUESSE
    die Zahl der nicht aufgelösten Organisationen der Klasse „Fachausschüsse und weitere Gremien“ mit diesem Paragrafen
    ({Paragraf: Zahl}; 1 heißt eindeutig)."""
    from .build import bv_bezirk
    from .geocode import BEZIRKE_KOELN
    gruppe, nicht, kandidaten = {}, Counter(), {}
    for o in orgs:
        klasse = o.get("classification")
        if klasse == KLASSE_FRAKTIONEN:
            nicht["fraktionen"] += 1
        elif klasse not in KLASSEN:
            nicht["ohne_klasse"] += 1
        elif klasse == KLASSE_RAT:
            gruppe[o["id"]] = {"gruppe": "rat"}
        elif klasse == KLASSE_BV:
            bezirk = bv_bezirk(o.get("name"))
            gruppe[o["id"]] = {"gruppe": "bezirksvertretung",
                               **({"stadtbezirk": bezirk} if bezirk in BEZIRKE_KOELN.values() else {})}
        else:
            gruppe[o["id"]] = {"gruppe": "uebrige"}
            nr = None if aufgeloest(o, datenstand) else ausschuesse.abschnitt(o.get("name"))
            if nr:
                kandidaten.setdefault(nr, []).append(o["id"])
    for nr, ids in kandidaten.items():
        if len(ids) == 1:
            gruppe[ids[0]] = {"gruppe": "ausschuss", "paragraf": nr}
    return gruppe, nicht, {nr: len(kandidaten.get(nr, ())) for nr, _, _ in ausschuesse.AUSSCHUESSE}


def organisationen_der_sitzungen(pfad=None):
    """{Kennung der Sitzung: [OParl-Kennungen der Organisationen, ohne Doppelte]} aus meetings.json (config.MEETINGS,
    OParl `organization` der Sitzung: alle Einträge, auch eine einzelne Kennung als Text; export.gremium_der_sitzung
    nimmt für zeit.json nur den ersten Eintrag einer Liste); fehlt die Datei, None."""
    pfad = pfad or config.MEETINGS
    if not pfad.exists():
        return None
    aus = {}
    for m in json.loads(pfad.read_text()):
        if not isinstance(m, dict) or not m.get("id"):
            continue
        orgs = m.get("organization") or []
        orgs = [orgs] if isinstance(orgs, str) else orgs
        aus[m["id"]] = list(dict.fromkeys(o for o in orgs if isinstance(o, str) and o))
    return aus


def _grund(refs, alle):
    """Warum eine Sitzung oder Beratung keinem Gremium der Datei zugeordnet ist."""
    if not refs:
        return "ohne Organisation"
    return "Organisation nicht in der Tabelle" if not any(o in alle for o in refs) else "Organisation nicht aufgenommen"


def _reihenfolge(m):
    return (m.get("date") or "", m.get("time") is None, m.get("time") or "")


def sitzungen(meetings, orgs_je_sitzung, ids, alle, seit, bis):
    """Sitzungen je Gremium: (Zahl im Zeitraum je OParl-Kennung, nächste Sitzung je OParl-Kennung, folgende Sitzung
    je OParl-Kennung, Sitzungen ohne Gremium der Datei je Grund). `meetings`: Sitzungen wie in zeit.json
    (export._meetings), `orgs_je_sitzung`: organisationen_der_sitzungen, `ids`: aufgenommene Organisationen, `alle`:
    alle Organisationen der Tabelle, `seit` und `bis`: Zeitraum (`bis` ist der Datenstand). Die nächste Sitzung ist
    die erste ohne Absage ab dem Datenstand (Tag >= `bis`, G7), die folgende nur bei einer nächsten Sitzung am
    Datenstand die erste ohne Absage nach diesem Tag (Tag > `bis`, E2); Reihenfolge nach _reihenfolge, bei Gleichstand
    die Reihenfolge von `meetings`. Eine Sitzung am Datenstand zählt zugleich im Zeitraum (F7)."""
    from .export import absage
    zahl, naechste, danach, ohne = Counter(), {}, {}, Counter()
    for m in meetings:
        refs = orgs_je_sitzung.get(m.get("source_object")) or []
        drin = [o for o in refs if o in ids]
        if not drin:
            ohne[_grund(refs, alle)] += 1
            continue
        if absage(m):
            continue
        tag = m.get("date") or ""
        for o in drin:
            if seit < tag <= bis:
                zahl[o] += 1
            if tag >= bis and (o not in naechste or _reihenfolge(m) < _reihenfolge(naechste[o])):
                naechste[o] = m
            if tag > bis and (o not in danach or _reihenfolge(m) < _reihenfolge(danach[o])):
                danach[o] = m
    folgende = {o: m for o, m in danach.items() if naechste[o].get("date") == bis}
    return zahl, naechste, folgende, ohne


def ohne_organisation_kommend(meetings, orgs_je_sitzung, namen, bis):
    """Für das Log (nur Zahlen): Sitzungen ab dem Datenstand `bis` (am Tag des Datenstands oder danach, wie die nächste
    Sitzung in sitzungen; bis Pull Request 4b nach dem Datenstand) ohne Absage (export.absage), die auf keine
    Organisation verweisen (organisationen_der_sitzungen; sie zählen für kein Gremium, auch nicht als nächste oder
    folgende Sitzung), und davon die, deren Gremium in zeit.json (export.gremium_der_sitzung, aus dem Sitzungsnamen) dem
    Namen genau eines Gremiums der Datei gleicht (`namen`: Counter der Namen der aufgenommenen Organisationen). Liefert
    (Zahl, davon)."""
    from .export import absage
    kommend = [m for m in meetings if not orgs_je_sitzung.get(m.get("source_object")) and (m.get("date") or "") >= bis
               and not absage(m)]
    return len(kommend), sum(namen.get(m.get("gremium")) == 1 for m in kommend)


def vorlagen(papers, seit, bis, kennung=None):
    """Verschiedene Vorlagen je Kennung des Gremiums mit einem Sitzungstag (process.local_day von `start_date`) im
    Zeitraum und ohne Absage der Sitzung (export.absage über die Station). `papers`: Vorlagen der Gebietsdateien, jede
    einmal (für das Log auch die Vorlagen in keiner Gebietsdatei, daten). `kennung(p, s)`: Kennung des Gremiums der
    Station `s` der Vorlage `p`; Vorgabe `gremium_key` der Station (daten übergibt die Kennung aus der Organisation der
    Beratung, damit aufgelöste Gremien ohne Kennung an der Station mitzählen, G6)."""
    from .export import absage
    kennung = kennung or (lambda p, s: s.get("gremium_key"))
    zahl = Counter()
    for p in papers:
        for k in {kennung(p, s) for s in p.get("process") or ()
                  if not absage(s) and seit < (proc.local_day(s.get("start_date")) or "") <= bis}:
            if k:
                zahl[k] += 1
    return zahl


def beratungen_ohne_gremium(db, ids, alle):
    """Einträge der Beratungsfolge (Tabelle consultation) ohne Organisation dieser Datei, je Grund (Counter)."""
    ohne = Counter()
    for (org,) in db.execute("SELECT organization_id FROM consultation"):
        if org not in ids:
            ohne[_grund([org] if org else [], alle)] += 1
    return ohne


def datenstand(db, stand=None):
    """Datenstand der Datei, derselbe Wert wie in export.export_all: export.stichtag mit dem Kölner Tag des Abrufs der
    Vorlagen (export.kalendertag_des_abrufs, retrieved_at der Quelle config.QUELLE_OPARL) und STAND.json (`stand`,
    Vorgabe die Datei)."""
    from .export import _stand, kalendertag_des_abrufs, stichtag
    zeile = db.execute("SELECT retrieved_at FROM source WHERE name = ?", (config.QUELLE_OPARL,)).fetchone()
    return stichtag(kalendertag_des_abrufs(zeile[0] if zeile else None), _stand() if stand is None else stand)


def sitzungsliste(stand=None):
    """None, wenn die Liste der Sitzungen beim letzten Abruf aktualisiert worden ist (export.sitzungsliste_aktuell, mit
    STAND.json `stand`, Vorgabe die Datei); sonst `meta.sitzungsliste_nicht_aktuell` für gremien.json: `stand` (letzte
    reguläre Aktualisierung der Sitzungen, STAND.json `meetings`, wie export._abruf_warnungen; sonst None) und
    `hinweis`. Eine Regel für export und check.gremien."""
    from .export import _stand, sitzungsliste_aktuell
    stand = _stand() if stand is None else stand
    if sitzungsliste_aktuell(stand):
        return None
    letzter = stand.get("meetings")
    return {"stand": letzter if isinstance(letzter, str) else None, "hinweis": HINWEIS_SITZUNGSLISTE}


def _sitzung_kurz(m):
    return {"date": m.get("date"), "time": m.get("time"), **({"hinweis": m["hinweis"]} if m.get("hinweis") else {}),
            "web": m.get("web"), "source_object": m.get("source_object")}


def meta(stand_tag, seit, quellen, liste=None):
    """Metadaten: Datenstand, Zeitraum, Quelle (OParl-API ohne Abrufzeit) mit Namensnennung, Zuständigkeitsordnung
    (ausschuesse.QUELLE: Titel, Stand, Fundstelle, Adresse, Abruf), `sitzungsliste_nicht_aktuell` (nur mit `liste`, aus
    sitzungsliste) und die Gruppen."""
    return {"datenstand": stand_tag, "zeitraum": {"seit": seit, "bis": stand_tag},
            "sources": [{k: v for k, v in s.items() if k != "retrieved_at"} for s in quellen
                        if s.get("name") == config.QUELLE_OPARL],
            "namensnennung": config.NAMENSNENNUNG,
            "zustaendigkeitsordnung": {**{k: ausschuesse.QUELLE[k] for k in ("titel", "stand", "fundstelle", "url",
                                                                             "abgerufen")},
                                       "hinweis": HINWEIS_ZUSTO},
            **({"sitzungsliste_nicht_aktuell": liste} if liste else {}),
            "gruppen": dict(GRUPPEN_TEXT), "note": NOTE}


def daten(orgs, meetings, orgs_je_sitzung, papers, stand_tag, quellen, liste=None, ausserhalb=(), beratungen_je=None):
    """Inhalt von gremien.json ({"meta", "gremien"}) und die Zahlen für das Log. `orgs`: organisationen, `meetings`:
    Sitzungen wie in zeit.json, `orgs_je_sitzung`: organisationen_der_sitzungen, `papers`: Vorlagen der Gebietsdateien
    (jede einmal, mit den Stationen), `stand_tag`: Datenstand, `quellen`: Zeilen der Tabelle source, `liste`:
    sitzungsliste (None: Liste der Sitzungen aktuell; sonst keine nächste und keine folgende Sitzung), `ausserhalb`:
    Vorlagen in keiner Gebietsdatei (nur für das Log, sie zählen nicht), `beratungen_je`: beratungen (Organisation je
    Station; export und check übergeben sie, damit aufgelöste Gremien bei vorlagen_12m mitzählen, G6; ohne sie zählt
    `gremium_key` an der Station). Reihenfolge: Gruppe (GRUPPEN), nicht aufgelöste vor aufgelösten, dann Paragraf bzw.
    Nummer des Stadtbezirks, Name, Kennung."""
    from .export import absage
    from .geocode import BEZIRKE_KOELN
    seit = gebietszahlen.window_start(stand_tag)
    keys = schluessel([o["id"] for o in orgs])
    gruppe, nicht, treffer = einordnen(orgs, stand_tag)
    alle = {o["id"] for o in orgs}
    z_sitzungen, naechste, folgende, ohne_sitzung = sitzungen(meetings, orgs_je_sitzung, set(gruppe), alle, seit,
                                                              stand_tag)
    if liste:
        naechste, folgende = {}, {}
    in_datei = {o: keys[o] for o in gruppe}

    def ueber_beratung(p, s):
        """Kennung aus der Organisation der Beratung (auch aufgelöste Gremien der Datei, G6)."""
        return in_datei.get(beratungen_je.get((p.get("source_object"), s.get("position"))))
    kennung = ueber_beratung if beratungen_je is not None else None
    z_vorlagen = vorlagen(papers, seit, stand_tag, kennung)
    nummer = {name: nr for nr, name in BEZIRKE_KOELN.items()}
    eintraege = []
    for o in orgs:
        if o["id"] not in gruppe:
            continue
        g, k = gruppe[o["id"]], keys[o["id"]]
        e = {"key": k, "name": o.get("name"), **g}
        if o.get("end_date"):
            e["end_date"] = o["end_date"]
        if aufgeloest(o, stand_tag):
            e["aufgeloest"] = True
        if o.get("web"):
            e["web"] = o["web"]
        e["sitzungen_12m"], e["vorlagen_12m"] = z_sitzungen[o["id"]], z_vorlagen[k]
        if o["id"] in naechste:
            e["naechste_sitzung"] = _sitzung_kurz(naechste[o["id"]])
        if o["id"] in folgende:
            e["folgende_sitzung"] = _sitzung_kurz(folgende[o["id"]])
        e["source_object"] = o["id"]
        eintraege.append({f: e[f] for f in FELDER if f in e})
    eintraege.sort(key=lambda e: (GRUPPEN.index(e["gruppe"]), bool(e.get("aufgeloest")),
                                  e.get("paragraf") or nummer.get(e.get("stadtbezirk"), 0),
                                  (e["name"] or "").casefold(), e["key"]))
    namen = Counter(o.get("name") for o in orgs if o["id"] in gruppe)
    zahlen = {"organisationen": len(orgs), "nicht": nicht, "treffer": treffer, "ohne_sitzung": ohne_sitzung,
              "mit_zusatz": sum(keys[o["id"]] != _rohschluessel(o["id"] or "") for o in orgs if o["id"] in gruppe),
              "ohne_organisation_kommend": ohne_organisation_kommend(meetings, orgs_je_sitzung, namen, stand_tag),
              "am_datenstand": sum((m.get("date") or "") == stand_tag and not absage(m) and
                                   any(o in gruppe for o in orgs_je_sitzung.get(m.get("source_object")) or ())
                                   for m in meetings),
              "naechste_am_datenstand": sum(m.get("date") == stand_tag for m in naechste.values()),
              "mit_folgender": len(folgende),
              "vorlagen_ausserhalb": sum(bool(vorlagen([p], seit, stand_tag, kennung)) for p in ausserhalb)}
    return {"meta": meta(stand_tag, seit, quellen, liste), "gremien": eintraege}, zahlen


def zeilen_log(d, zahlen, ohne_beratung):
    """Zeilen im Log von `export`, nur Zahlen: Organisationen und Gruppen, aufgelöste, Kennungen mit Zusatz,
    Ausschüsse mit Paragraf (die Erklärung der Zählung im Kopf der Zeile, dahinter die Nummern der Paragrafen ohne und
    mit mehr als einer Organisation, Entscheidung 21.11.2026 (3) (G5)), Bezirksvertretungen mit Stadtbezirk, Sitzungen
    und Beratungen ohne Gremium der Datei je Grund; Sitzungen ab dem Datenstand ohne Verweis auf eine Organisation
    (ohne_organisation_kommend), Sitzungen von Gremien der Datei am Datenstand (zählen als kommend, G7) und Gremien mit
    nächster Sitzung am Datenstand, davon mit folgender Sitzung (E2); Vorlagen in keiner Gebietsdatei mit Beratung
    eines Gremiums der Datei im Zeitraum (zählen nicht); bei nicht aktueller Liste der Sitzungen eine Zeile dazu."""
    from .geocode import BEZIRKE_KOELN
    g = d["gremien"]
    je = Counter(e["gruppe"] for e in g)
    treffer = zahlen["treffer"]
    kommend, kommend_name = zahlen["ohne_organisation_kommend"]
    bv = [e for e in g if e["gruppe"] == "bezirksvertretung"]
    bezirke = {e["stadtbezirk"] for e in bv if e.get("stadtbezirk")}

    def gruende(c):
        return ", ".join(f"{k} {c.get(k, 0)}" for k in ("ohne Organisation", "Organisation nicht in der Tabelle",
                                                 "Organisation nicht aufgenommen"))

    def paragrafen(auswahl):
        """Nummern der Paragrafen, auf die `auswahl` (je Eintrag von `treffer`) zutrifft, aufsteigend (G5); keine: leer."""
        nrs = sorted(nr for nr, ja in zip(treffer, auswahl) if ja)
        return f" (§ {nrs[0]})" if len(nrs) == 1 else f" (§§ {', '.join(map(str, nrs))})" if nrs else ""
    return [
        f"Gremien ({DATEI}): {zahlen['organisationen']} Organisationen, nicht aufgenommen Fraktionen und Gruppen "
        f"{zahlen['nicht']['fraktionen']}, mit anderer oder ohne Klasse {zahlen['nicht']['ohne_klasse']}; aufgenommen "
        f"{len(g)}: Rat {je['rat']}, Ausschüsse mit Paragraf {je['ausschuss']}, Bezirksvertretungen "
        f"{je['bezirksvertretung']}, übrige {je['uebrige']}; davon aufgelöst {sum(bool(e.get('aufgeloest')) for e in g)}; "
        f"Kennungen mit Zusatz aus dem SHA-1 (gleiche Kennung) {zahlen['mit_zusatz']}",
        f"Ausschüsse laut Zuständigkeitsordnung (ausschuesse.AUSSCHUESSE, {len(treffer)} Einträge; gezählt nicht "
        f"aufgelöste Organisationen der Klasse „{KLASSE_AUSSCHUESSE}“): mit genau einer Organisation "
        f"{sum(n == 1 for n in treffer.values())}, ohne Organisation {sum(n == 0 for n in treffer.values())}"
        f"{paragrafen(n == 0 for n in treffer.values())}, mit mehr als einer Organisation "
        f"{sum(n > 1 for n in treffer.values())}{paragrafen(n > 1 for n in treffer.values())}",
        f"Bezirksvertretungen mit Stadtbezirk: {sum(bool(e.get('stadtbezirk')) for e in bv)} von {len(bv)}, "
        f"Stadtbezirke {len(bezirke)} von {len(BEZIRKE_KOELN)}",
        f"Sitzungen ohne Gremium aus {DATEI}: {sum(zahlen['ohne_sitzung'].values())} ({gruende(zahlen['ohne_sitzung'])}); "
        f"Beratungen ohne Gremium aus {DATEI}: {sum(ohne_beratung.values())} ({gruende(ohne_beratung)})",
        f"Sitzungen ab dem Datenstand ohne Verweis auf eine Organisation (ohne Absage; zählen für kein Gremium, auch "
        f"nicht als nächste oder folgende Sitzung): {kommend}, davon mit Gremium aus dem Sitzungsnamen gleich dem "
        f"Namen genau eines Gremiums aus {DATEI} {kommend_name}; Sitzungen von Gremien aus {DATEI} am Datenstand (ohne "
        f"Absage; zählen als kommend): {zahlen['am_datenstand']}; Gremien mit nächster Sitzung am Datenstand "
        f"{zahlen['naechste_am_datenstand']}, davon mit folgender Sitzung {zahlen['mit_folgender']}",
        f"Vorlagen in keiner Gebietsdatei mit Beratung eines Gremiums aus {DATEI} im Zeitraum (zählen nicht bei "
        f"vorlagen_12m): {zahlen['vorlagen_ausserhalb']}",
    ] + ([f"Liste der Sitzungen beim letzten Abruf nicht aktualisiert: keine nächste Sitzung in {DATEI}"]
         if d["meta"].get("sitzungsliste_nicht_aktuell") else [])


def schreiben(ziel, db, meetings, papers, stand_tag, liste=None, ausserhalb=()):
    """gremien.json nach `ziel` (Pfad der Datei) und die Zeilen im Log; liefert den Inhalt. `liste`: sitzungsliste,
    `ausserhalb`: Vorlagen in keiner Gebietsdatei (nur für das Log). Fehlt meetings.json, zählen keine Sitzungen (wie
    zeit.json ohne Sitzungen)."""
    orgs = organisationen(db)
    quellen = [dict(zip(("name", "url", "license", "retrieved_at"), r))
               for r in db.execute("SELECT name, url, license, retrieved_at FROM source")]
    d, zahlen = daten(orgs, meetings, organisationen_der_sitzungen() or {}, papers, stand_tag, quellen, liste,
                      ausserhalb, beratungen(db))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    ids = {e["source_object"] for e in d["gremien"]}
    for zeile in zeilen_log(d, zahlen, beratungen_ohne_gremium(db, ids, {o["id"] for o in orgs})):
        print(zeile)
    return d


def zeile_stationen(papers, aufgeloeste=None):
    """Zeile im Log von `export`, nur Zahlen: Stationen der Prozesslinie in den Gebietsdateien (jede Vorlage einmal),
    davon mit Sitzung, mit Hinweis aus dem Sitzungsnamen (export.hinweis_station) und mit Kennung des Gremiums; mit
    Freigabe dazu `aufgeloeste`, die Stationen aufgelöster Gremien der Datei, die keine Kennung tragen
    (stationen_aufgeloester; Entscheidung 21.11.2026 (3) (G6)); ohne Freigabe (None) entfällt dieser Teil."""
    st = [s for p in papers for s in p.get("process") or ()]
    hinweis = Counter(s.get("hinweis") for s in st if s.get("hinweis"))
    return (f"Stationen der Prozesslinie in den Gebietsdateien: {len(st)}, mit Sitzung "
            f"{sum(bool(s.get('meeting_id')) for s in st)}, mit Hinweis aus dem Sitzungsnamen "
            f"{sum(hinweis.values())} (abgesagt {hinweis['abgesagt']}, verschoben {hinweis['verschoben']}), mit "
            f"Kennung des Gremiums aus {DATEI} {sum(bool(s.get('gremium_key')) for s in st)}"
            + (f", Stationen aufgelöster Gremien aus {DATEI} (ohne Kennung) {aufgeloeste}"
               if aufgeloeste is not None else ""))

