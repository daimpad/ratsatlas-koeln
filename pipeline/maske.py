"""Hausnummern in Titeln von Vorlagen aus der Einwohnerschaft ausblenden (Datenschutz, CLAUDE.md 5.2).

Gilt für Bürgeranträge, Anregungen und Beschwerden, Einwohnerfragen und Bürgerbriefe sowie alle Vorlagen, die mit
ihnen verbunden sind (kette: über- und untergeordnet und seit Runde 20 auch über relatedPaper, dieselbe Drucksache;
dieselben Beziehungen und dieselbe Funktion geocode.sperrmenge wie für die Hauskoordinaten). Dieselbe Regel wie
`masker()` in site/chat/tools.js: eine Hausnummer hinter einem bekannten Straßennamen oder einer Straßen-Endung wird
durch OHNE_NR ersetzt. Entscheidung des Auftraggebers 24.10.2026: auf Seite, in Feeds, Suche und offenen Daten wie im
Assistenten; das Original bleibt über den Link ins Ratsinformationssystem erreichbar.
Verortung und Audit der Geokodierung arbeiten weiter mit dem vollen Titel aus der Datenbank (die Hausnummer
bestimmt den Ortsteil, angezeigt wird nur die Straße).
Erweitert am 26.10.2026 (Entscheidung des Auftraggebers): auch Vorlagen, die das Bauordnungsamt (63) oder eine Untere
Naturschutzbehörde (56-3, 67-6) federführend betreut (Bauanträge und Fällgenehmigungen auf Grundstücken), und ihre
verbundenen Vorlagen.
Ergänzt am 01.11.2026 (Lücke aus der Phase 0 „Verständlichkeit“: 27 Titel aus 15 Vorgängen): auch eine Nummer hinter
„Hausnummer(n)“, „Hausnr.“, „Haus-Nr.“ oder „Haus Nr.“ (ersetzt samt dem Wort) und hinter „Straße Nr.“."""
import json
import re

from . import chat, config, geocode

OHNE_NR = "[Hausnummer ausgelassen]"
# Bauordnungsamt und Untere Naturschutzbehörden: Titel nennen oft private Baugrundstücke mit Hausnummer
AMT_PRIVAT = re.compile(r"^(?:63(?:\s|-)|56-3\b|67-6\b)")
_L = r"[^\W\d_]"   # Buchstabe (wie \p{L})
# wie NR und SUFFIX in site/chat/tools.js, aber bis zu vier Ziffern: Kölner Straßen haben vierstellige Hausnummern
# („Aachener Straße 1175“, „Militärringstraße 1000“; geocode.HAUSNUMMER liest sie ebenso; Generalprobe 09.11.2026).
# Der Assistent (site/chat/tools.js, in Köln abgeschaltet) folgt mit seiner Freigabe
NR = (rf"\d{{1,4}}(?:\s?[a-zA-Z](?!{_L}))?(?:\s*(?:-|–|bis|und|u\.|/|,)\s*\d{{1,4}}(?:\s?[a-zA-Z](?!{_L}))?)*(?!\d)")
SUFFIX = (rf"(?:{_L}|[.-])*(?:straße|strasse|str\.|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee|hof|markt|"
          r"graben|berg|feld)")


# „Hausnummer 82“, „Haus-Nr. 264“, „Haus Nr. 5“, „Hausnummern 36 bis 40“, „(neben Haus-Nr.) 68“ (wie WORT in
# site/chat/tools.js); eine schließende Klammer bleibt stehen
WORT = re.compile(rf"\b(?:hausnummern?|hausnr\.?|haus-nr\.?|haus\s+nr\.?)\s*(\))?\s*{NR}", re.I)


def _muster(strassen):
    names = sorted({s for s in strassen if s}, key=len, reverse=True)
    return re.compile(rf"((?:{'|'.join([*map(re.escape, names), SUFFIX])})\s+)(?:nr\.?\s*)?{NR}", re.I)


def privat(p):
    """Federführend Bauordnungsamt oder Untere Naturschutzbehörde (Name der Organisationseinheit oder Amtsbezeichnung;
    Datenbank: amt_name, Export: responsibility)."""
    namen = [p.get("amt_name"), p.get("amt")] + [r.get("name") for r in p.get("responsibility") or []
                                                 if r.get("kind") == "federfuehrend"]
    return any(AMT_PRIVAT.match(n or "") for n in namen)


def titel_ohne_hausnummer(paper_type, name, amt_name=None):
    """Ist die Vorlage selbst Ausgangspunkt der Maske (ohne verbundene Vorlagen)? Gleiche Angaben wie aus_db: Art und
    Titel aus der Einwohnerschaft (chat.aus_einwohnerschaft) oder Bauordnung bzw. Naturschutz federführend (privat über
    den Namen der Organisation aus `underDirectionOf`). geocode.punkt_ausschluss gibt solchen Vorlagen keine
    Hauskoordinate, damit neben dem Titel ohne Hausnummer keine Anschrift als Ortsname steht."""
    return chat.aus_einwohnerschaft(paper_type, name) or privat({"amt_name": amt_name})


class Maske:
    """maske(titel, drucksache) → Titel ohne Hausnummer, wenn die Drucksache zur Einwohnerschaft gehört."""

    def __init__(self, refs, strassen=None):
        self.refs = set(refs)
        if strassen is None:
            strassen = json.loads(config.STRASSEN.read_text())["streets"] if config.STRASSEN.exists() else []
        self.rx = _muster(strassen)

    def _betroffen(self, titel, ref):
        # ohne Ziffer keine Hausnummer: spart die teure Regex bei den meisten Titeln (gleiche Ergebnisse)
        return bool(titel) and ref in self.refs and any(c.isdigit() for c in titel)

    def __call__(self, titel, ref):
        if not self._betroffen(titel, ref):
            return titel
        return WORT.sub(lambda m: OHNE_NR + (m.group(1) or ""), self.rx.sub(lambda m: m.group(1) + OHNE_NR, titel))

    def offen(self, titel, ref):
        """Bleibt nach dem Ausblenden eine Hausnummer stehen? (Prüfung in check.py)"""
        return self._betroffen(titel, ref) and bool(self.rx.search(titel) or WORT.search(titel))


def kette(vorlagen, ausgelassen, beziehungen, privat_auch=True):
    """Titelmaske (privat_auch, aus_db) und Volltextkette (ohne Bauordnung und Naturschutz, volltext.einwohner_kette):
    eine Regel, eine Funktion. Ausgangsvorlagen sind die Vorlagen aus der Einwohnerschaft nach Art oder Titel
    (chat.aus_einwohnerschaft), mit `privat_auch` auch die, die Bauordnungsamt oder Untere Naturschutzbehörde
    federführend betreut (privat), und die beim Aufbau ausgelassenen Vorlagen (`ausgelassen`: Kennungen; Art und Titel
    unbekannt, sie gelten wie Eingaben). Dazu kommen als Fixpunkt (geocode.sperrmenge) alle verbundenen Vorlagen und
    alle Vorlagen mit derselben Drucksache. `beziehungen`: dieselben Paare wie für die Hauskoordinaten (über- und
    untergeordnet und relatedPaper, in beiden Richtungen; geocode.beziehungen bzw. geocode.beziehungen_db), damit eine
    Stellungnahme, die nur über relatedPaper mit einer Eingabe verbunden ist, ihre Hausnummer im Titel ebenso verliert
    wie eine untergeordnete (Entscheidung 10.11.2026, Runde 20). Jede Ausgangsvorlage ist auch ohne Erlaubnis für
    Hauskoordinaten (geocode.punkt_ausschluss), die Kette also Teil der Menge ohne Hauskoordinate.
    `vorlagen`: [(ID, Drucksache, Vorlagenart, Titel, Name der federführenden Organisation)]. Liefert {ID: Weg} wie
    geocode.sperrmenge (auch Kennungen ohne Vorlage, über die eine Beziehung läuft)."""
    ausgang = titel_ohne_hausnummer if privat_auch else lambda art, titel, _amt: chat.aus_einwohnerschaft(art, titel)
    drucksachen, start = {}, set(ausgelassen)
    for pid, ref, art, titel, amt_name in vorlagen:
        drucksachen[pid] = ref
        if ausgang(art, titel, amt_name):
            start.add(pid)
    return geocode.sperrmenge(start, beziehungen, drucksachen)


def _tabelle(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()


def aus_db(db, strassen=None):
    """Maske für alle Vorlagen der Datenbank (kette: Einwohnerschaft, Bauordnung, Naturschutz und verbundene Vorlagen
    über paper_relation und relatedPaper aus paper_related, dieselbe Drucksache). Beim Aufbau ausgelassene Vorlagen
    (skipped_paper, ohne Drucksachennummer oder gelöscht; Art und Titel unbekannt) gelten wie Eingaben: Ihre verbundenen
    Vorlagen zeigen keine Hausnummer im Titel (wie ohne Hauskoordinate, check.erlaubnis)."""
    spalten = {r[1] for r in db.execute("PRAGMA table_info(paper)")}
    amt = ("(SELECT name FROM organization o WHERE o.id = paper.under_direction_of)"
           if "under_direction_of" in spalten else "NULL")
    vorlagen = db.execute(f"SELECT id, reference, paper_type, name, {amt} FROM paper").fetchall()
    ausgelassen = ([r[0] for r in db.execute("SELECT id FROM skipped_paper")] if _tabelle(db, "skipped_paper")
                   else [])
    weg = kette(vorlagen, ausgelassen, geocode.beziehungen_db(db))
    return Maske({ref for pid, ref, *_ in vorlagen if pid in weg}, strassen)
