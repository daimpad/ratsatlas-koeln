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
„Hausnummer(n)“, „Hausnr.“, „Haus-Nr.“ oder „Haus Nr.“ (ersetzt samt dem Wort) und hinter „Straße Nr.“.
Ergänzt in der Prüfung r20n (Schreibweisen, die die Hausnummer stehen ließen): Abgeglichen wird eine angeglichene
Fassung des Titels (_angleichen: je Zeichen NFKC, ohne weiche Trennzeichen und Zeichen ohne Breite, Leerraum zu einem
Leerzeichen), ersetzt wird im gelieferten Titel (sonst unverändert); zwischen Straße und Nummer bis zu drei Zeichen
außer Buchstaben und Ziffern („Str.12“, „Straße12“, „Straße, 12“, „Straße (Nr. 12)“, „Straße #12“, „Straße № 12“) und
„Nr.“, „No.“, „Nummer“ oder „Haus“; Straßennamen auch mit „ss“ statt „ß“ und umgekehrt. check prüft die Titel zudem
mit einer unabhängig gebauten Probe (Maske.offen, _Probe)."""
import json
import re
import unicodedata

from . import chat, config, geocode

OHNE_NR = "[Hausnummer ausgelassen]"
# Stichproben, die build mit vollem Titel nach data/export schreibt (Weg ab config.EXPORT; Kopf mit „drucksache“ in
# Spalte 2): Spalten, die export.export_audits maskiert und check.datenschutz prüft. Die Stichprobe Volltext nennt
# auch die gefundenen Orte (Prüfung r20)
STICHPROBEN = {("hausnummern", "stichprobe_hausnummern.tsv"): ("titel",),
               ("volltext", "stichprobe_volltext.tsv"): ("titel", "orte (Ortsteil)")}
# Bauordnungsamt und Untere Naturschutzbehörden: Titel nennen oft private Baugrundstücke mit Hausnummer
AMT_PRIVAT = re.compile(r"^(?:63(?:\s|-)|56-3\b|67-6\b)")
_L = r"[^\W\d_]"   # Buchstabe (wie \p{L})
# wie NR und SUFFIX in site/chat/tools.js, aber bis zu vier Ziffern: Kölner Straßen haben vierstellige Hausnummern
# („Aachener Straße 1175“, „Militärringstraße 1000“; geocode.HAUSNUMMER liest sie ebenso; Generalprobe 09.11.2026).
# „Str“ auch ohne Punkt („Aachener Str 12“, Prüfung r20n). Der Assistent (site/chat/tools.js, in Köln abgeschaltet)
# folgt mit seiner Freigabe
NR = (rf"\d{{1,4}}(?:\s?[a-zA-Z](?!{_L}))?(?:\s*(?:-|–|bis|und|u\.|/|,)\s*\d{{1,4}}(?:\s?[a-zA-Z](?!{_L}))?)*(?!\d)")
SUFFIX = (rf"(?:{_L}|[.-])*(?:straße|strasse|str(?:\.|(?!{_L}))|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee|hof"
          r"|markt|graben|berg|feld)")


# „Hausnummer 82“, „Haus-Nr. 264“, „Haus Nr. 5“, „Hausnummern 36 bis 40“, „(neben Haus-Nr.) 68“ (wie WORT in
# site/chat/tools.js); eine schließende Klammer bleibt stehen
WORT = re.compile(rf"\b(?:hausnummern?|hausnr\.?|haus-nr\.?|haus\s+nr\.?)\s*(\))?\s*{NR}", re.I)


# zwischen Straße und Nummer: bis zu drei Zeichen außer Buchstaben und Ziffern (Leerzeichen, Komma, Klammer, „#“, „№“
# nach NFKC „No“), oder keines, wenn die Straße nicht auf eine Ziffer endet („Str.12“, „Straße12“; nicht „L 84“ + „5“);
# danach wahlweise „Nr.“, „No.“, „Nummer“ oder „Haus“ (fallen mit der Nummer weg)
ZWISCHEN = r"(?:[^\w]{1,3}|(?<!\d))"
NR_WORT = rf"(?:(?:nr|no|nummer|haus)(?!{_L})\.?[^\w]{{0,3}})?"


def _name_muster(name):
    """Straßenname als Muster für den angeglichenen Titel: „ß“ und „ss“ gleich („Am Schlossgarten“)."""
    return re.sub("ß|ss", "(?:ß|ss)", re.escape(name))


def _muster(strassen):
    names = sorted({s for s in strassen if s}, key=len, reverse=True)
    return re.compile(rf"((?:{'|'.join([*map(_name_muster, names), SUFFIX])}){ZWISCHEN}){NR_WORT}{NR}", re.I)


def _angleichen(titel):
    """Angeglichene Fassung eines Titels für den Abgleich und je Zeichen seine Stelle im Titel: je Zeichen NFKC
    (Vollbreite, „№“ als „No“, geschütztes Leerzeichen), ein folgendes Kombinationszeichen mit dem Buchstaben davor
    zusammengesetzt, ohne weiche Trennzeichen und Zeichen ohne Breite (geocode._UNSICHTBAR), jeder Leerraum (auch
    Zeilenumbruch, doppelt) als ein Leerzeichen. Ersetzt wird über die Stellen im gelieferten Titel, der sonst
    unverändert bleibt."""
    zeichen, stellen = [], []
    for i, c in enumerate(titel):
        if geocode._UNSICHTBAR.match(c):
            continue
        for d in unicodedata.normalize("NFKC", c):
            if d.isspace():
                if zeichen and zeichen[-1] == " ":
                    continue
                d = " "
            elif zeichen and unicodedata.combining(d):
                z = unicodedata.normalize("NFC", zeichen[-1] + d)
                if len(z) == 1:
                    zeichen[-1] = z
                    continue
            zeichen.append(d)
            stellen.append(i)
    return "".join(zeichen), stellen


def _falten(text):
    """Text für die Probe: NFKC, ohne unsichtbare Zeichen, casefold („ß“ als „ss“), Leerraum als ein Leerzeichen."""
    t = unicodedata.normalize("NFKC", geocode._UNSICHTBAR.sub("", text or "")).casefold()
    return re.sub(r"\s+", " ", t)


class _Probe:
    """Unabhängig gebaute Probe für check (nicht für die Ausgabe): Steht im gefalteten Titel (_falten) eine Ziffernfolge
    mit bis zu vier Stellen hinter einem Straßennamen oder einem Wort mit Straßen-Endung, getrennt durch bis zu vier
    Zeichen außer Buchstaben und Ziffern (oder ohne, wenn davor keine Ziffer steht) und wahlweise „Nr“, „No“, „Nummer“
    oder „Haus“? Nicht hinter einem bloßen „Nr.“ oder „Haus“ (Bebauungsplan-, Drucksachen- und Gebäudenummern; ein
    Befund hielte die Veröffentlichung an)."""

    def __init__(self, strassen):
        namen = sorted({_falten(s) for s in strassen if s}, key=len, reverse=True)
        endung = (r"[^\W\d_]*(?:strasse|str(?:\.|(?![^\W\d_]))|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee"
                  r"|hof|markt|graben|berg|feld)")
        self.rx = re.compile(rf"(?:{'|'.join([*map(re.escape, namen), endung])})(?:[^\w]{{1,4}}|(?<!\d))"
                             rf"(?:(?:nr|no|nummer|haus)\.?[^\w]{{0,4}})?\d{{1,4}}(?!\d)")

    def __call__(self, titel):
        return bool(self.rx.search(_falten(titel)))


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
        self.strassen = list(strassen)
        self.rx = _muster(self.strassen)
        self._probe = None

    def _betroffen(self, titel, ref):
        # ohne Ziffer keine Hausnummer: spart die teure Regex bei den meisten Titeln (gleiche Ergebnisse)
        return bool(titel) and ref in self.refs and any(c.isdigit() for c in titel)

    def _stellen(self, angeglichen):
        """Zu ersetzende Stellen im angeglichenen Titel: (Anfang, Ende, Ersatz); Straße und Trennzeichen bleiben stehen,
        „Nr.“ und die Nummer fallen weg; „Hausnummer 5“ samt dem Wort (WORT), eine schließende Klammer bleibt."""
        teile = [(m.end(1), m.end(), OHNE_NR) for m in self.rx.finditer(angeglichen)]
        for m in WORT.finditer(angeglichen):
            if not any(a < m.end() and m.start() < e for a, e, _ in teile):
                teile.append((m.start(), m.end(), OHNE_NR + (m.group(1) or "")))
        return sorted(teile)

    def __call__(self, titel, ref):
        if not self._betroffen(titel, ref):
            return titel
        angeglichen, stellen = _angleichen(titel)
        aus, bis = [], 0
        for a, e, ersatz in self._stellen(angeglichen):
            von = stellen[a]
            nach = stellen[e] if e < len(stellen) else len(titel)
            aus += [titel[bis:von], ersatz]
            bis = nach
        return "".join(aus) + titel[bis:]

    def offen(self, titel, ref):
        """Bleibt nach dem Ausblenden eine Hausnummer stehen? (Prüfung in check.py) Mit dem Muster der Maske und der
        unabhängig gebauten Probe (_Probe), damit die Regel nicht nur sich selbst prüft (Prüfung r20n)."""
        if not self._betroffen(titel, ref):
            return False
        if self._probe is None:
            self._probe = _Probe(self.strassen)
        angeglichen = _angleichen(titel)[0]
        return bool(self.rx.search(angeglichen) or WORT.search(angeglichen) or self._probe(titel))


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
