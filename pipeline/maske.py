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
mit einer unabhängig gebauten Probe (Maske.offen, _Probe).
Ergänzt in der Prüfung r20a (Fix): „§“, „€“, „%“ und „*“ trennen Straße und Nummer nicht („Straße (§ 24 GO NRW)“ bleibt,
in der Probe vorher bis zu vier Trennzeichen und ein Befund, den die Maske nicht beheben konnte); Listen auch mit „bzw.“,
„oder“, „sowie“, „&“, „+“ und jedem Binde- oder Gedankenstrich; „Hausnummer:“, „Haus-Nummer“, „Hs.-Nr.“, „HNr.“,
„H.-Nr.“ und hinter der Straße „Nrn.“; keine Nummer vor „.“ oder „:“ mit Ziffer (Datum, Tausenderpunkt, Uhrzeit).
Ergänzt in der Prüfung r20a (zweite Korrektur): Was die Probe meldet, blendet die Maske selbst aus (Sicherheitsnetz in
Maske.__call__: nach den Mustern die Ziffernfolgen, die die Probe findet, bis nichts mehr übrig ist; offen heißt „die
Maske würde den Text noch ändern“). Vorher konnte check einen Titel melden, den die Maske nicht beheben konnte
(„(Musterstraße 12) – 2. Nachtrag“), und hätte die Veröffentlichung angehalten. Dazu „u“ und „u.“ in Listen („7 u. 9“;
vorher las die Maske das „u“ als Zusatz der Hausnummer), „;“ und „Nr.“ vor jeder weiteren Nummer („Nr. 23 und Nr. 25“),
Lagewörter zwischen Straße und Nummer („vor Nr. 300“, „in Höhe Haus 12“, „zwischen 300 und 320“), ein bloßes „Nr. 12“
ohne folgendes „/“, Mehrzahl und Leerzeichen im Wort („Haus-Nrn.“, „Haus Nummer“, „Häuser“, hinter der Straße „Hs.“) und
Straßennamen mit „St.“, „St. “ oder „Sankt“ und mit Leerzeichen statt Bindestrich („An St. Katharinen“, „Bertha Benz
Karree“)."""
import json
import re
import unicodedata

from . import chat, config, geocode

OHNE_NR = "[Hausnummer ausgelassen]"
# Stichproben, die build mit vollem Titel nach data/export und damit ins Datenpaket schreibt (Weg ab config.EXPORT;
# Kopf mit der Spalte „drucksache“): Spalten, die export.export_audits maskiert und check.datenschutz prüft; fehlt einer
# vorhandenen Stichprobe eine dieser Spalten oder „drucksache“, meldet check das. Die Stichproben Volltext und Gebäude
# und Anlagen nennen auch die gefundenen Orte (Prüfung r20, r20a). Daneben prüft check jede TSV-Datei unter
# data/export mit den Spalten „drucksache“ und „titel“ (Prüfung r20a)
STICHPROBEN = {("hausnummern", "stichprobe_hausnummern.tsv"): ("titel",),
               ("volltext", "stichprobe_volltext.tsv"): ("titel", "orte (Ortsteil)"),
               ("objekte", "stichprobe_objekte.tsv"): ("titel", "gebäude oder anlage (Ortsteil)")}
# Bauordnungsamt und Untere Naturschutzbehörden: Titel nennen oft private Baugrundstücke mit Hausnummer
AMT_PRIVAT = re.compile(r"^(?:63(?:\s|-)|56-3\b|67-6\b)")
_L = r"[^\W\d_]"   # Buchstabe (wie \p{L})
# wie NR und SUFFIX in site/chat/tools.js, aber bis zu vier Ziffern: Kölner Straßen haben vierstellige Hausnummern
# („Aachener Straße 1175“, „Militärringstraße 1000“; geocode.HAUSNUMMER liest sie ebenso; Generalprobe 09.11.2026).
# „Str“ auch ohne Punkt („Aachener Str 12“, Prüfung r20n). Der Assistent (site/chat/tools.js, in Köln abgeschaltet)
# folgt mit seiner Freigabe. Listen auch mit „bzw.“, „oder“, „sowie“, „&“, „+“ und jedem Binde- oder Gedankenstrich
# („12 bzw. 14“, „12 — 14“, „12‑14“ mit geschütztem Bindestrich; vorher blieb die zweite Nummer stehen). Keine Nummer
# vor „.“ oder „:“ mit Ziffer („Musterweg, 12.03.2026“, „1.000 EUR“, „12:30 Uhr“; Prüfung r20a)
_ZIFFERN = r"\d{1,4}(?![.:]\d)"
# Buchstabe der Hausnummer („12a“, „12 b“), aber nicht das „u“ einer Liste vor einer Ziffer („7 u. 9“, „53 u 55“; vorher
# las die Maske „ u“ als Zusatz, und die zweite Nummer blieb stehen; Prüfung r20a, zweite Korrektur)
_ZUSATZ = rf"(?:\s?(?!u\.?\s*\d)[a-zA-Z](?!{_L}))?"
LISTE = rf"(?:[-‐‑‒–—−/,;&+]|bis|und|u\.?(?!{_L})|bzw\.?|oder|sowie)"
# Wörter für die Hausnummer, auch in der Mehrzahl und mit Leerzeichen („Haus-Nrn.“, „Hausnrn.“, „Haus Nummer“, „Häuser“)
_HNR = r"haus(?:-|\s+)?(?:nummern?|nrn?)|hs\.?-?nrn?|h\.?-?nrn?|häusern?"
# vor der Nummer hinter einer Straße und vor jeder weiteren Nummer einer Liste („Nr. 23 und Nr. 25“, „12 bis Nr. 20“)
_NRW = rf"(?:{_HNR}|nrn?|no|nummer|haus|hs)(?!{_L})\.?:?"
NR = rf"{_ZIFFERN}{_ZUSATZ}(?:\s*{LISTE}\s*(?:{_NRW}\s*)?{_ZIFFERN}{_ZUSATZ})*(?!\d)"
SUFFIX = (rf"(?:{_L}|[.-])*(?:straße|strasse|str(?:\.|(?!{_L}))|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee|hof"
          r"|markt|graben|berg|feld)")


# „Hausnummer 82“, „Haus-Nr. 264“, „Haus Nr. 5“, „Hausnummern 36 bis 40“, „(neben Haus-Nr.) 68“ (wie WORT in
# site/chat/tools.js); eine schließende Klammer bleibt stehen. Auch „Hausnummer: 8“, „Haus-Nummer 12“, „Hs.-Nr. 12“,
# „HNr. 12“ und „H.-Nr. 12“ (Prüfung r20a), „Haus-Nrn.“, „Haus Nummer“, „Häuser 300 bis 304“ (zweite Korrektur)
WORT = re.compile(rf"\b(?:{_HNR})(?!{_L})\.?:?\s*(\))?\s*{NR}", re.I)
# bloßes „Nr. 12“ ohne Straße davor („Behindertenparkplatz vor Nr. 12 der Musterstraße“), aber nicht vor „/“
# (Drucksache „Nr. 1234/2026“, Bebauungsplan „Nr. 6158/03“; Prüfung r20a, zweite Korrektur)
NUR_NR = re.compile(rf"\b(?:nrn?|no)(?!{_L})\.?:?\s*(?!\d{{1,4}}{_ZUSATZ}\s*/){NR}", re.I)


# zwischen Straße und Nummer: bis zu drei Zeichen außer Buchstaben und Ziffern (Leerzeichen, Komma, Klammer, „#“, „№“
# nach NFKC „No“), oder keines, wenn die Straße nicht auf eine Ziffer endet („Str.12“, „Straße12“; nicht „L 84“ + „5“);
# danach wahlweise „Nr.“, „Nrn.“, „No.“, „Nummer“, „Haus“, „Hs.“ oder ein Wort aus _HNR (fallen mit der Nummer weg).
# „§“, „€“, „%“ und „*“ trennen nicht: „Straße (§ 24 GO NRW)“, „Straße § 24 GO“, „Neumarkt € 1.000“ bleiben (Prüfung
# r20a; die Probe zählt gleich)
TRENN = r"[^\w§€%*]"
ZWISCHEN = rf"(?:{TRENN}{{1,3}}|(?<!\d))"
NR_WORT = rf"(?:{_NRW}{TRENN}{{0,3}})?"
# Lage zwischen Straße und Nummer (bleibt stehen): vor „Nr.“, „Haus“ usw. („vor Nr. 300“, „in Höhe Haus 12“, „gegenüber
# dem Haus 5“), vor einer bloßen Zahl nur Wörter, die keine Jahreszahl einleiten („Höhe 12“, „zwischen 300 und 320“;
# „ab 2027“ bleibt; Prüfung r20a, zweite Korrektur)
_LAGE_NR = r"(?:in\s)?h[öo]he|zwischen|zw\.|gegenüber|ggü\.?|vor|neben|hinter|ecke|ab|bis|bei|nahe"
_LAGE_ZAHL = r"(?:in\s)?h[öo]he|zwischen|zw\.|gegenüber|ggü\.?|neben|hinter|ecke"
LAGE = (rf"(?:(?:{_LAGE_NR})(?!{_L})\.?\s?(?:(?:den|dem|der|von|vom)\s)?(?={_NRW})"
        rf"|(?:{_LAGE_ZAHL})(?!{_L})\.?\s?(?=\d))")
# Teile eines Straßennamens, die Titel anders schreiben: „St.“ und „Sankt“ mit und ohne Leerzeichen („An St.Katharinen“
# im Verzeichnis, „An St. Katharinen“ im Titel), Punkt mit und ohne Leerzeichen, Bindestrich und Leerzeichen
_NAMENSTEILE = re.compile(rf"(\bst\.\s?|\bsankt(?!{_L})\s?|\.\s?|[-\s]+)", re.I)


def _name_atome(name):
    """Straßenname als Folge von Teilmustern für den angeglichenen Titel: „ß“ und „ss“ gleich („Am Schlossgarten“), „St.“
    wie „Sankt“ mit und ohne Leerzeichen, Punkt mit und ohne Leerzeichen, Bindestrich wie Leerzeichen („Bertha Benz
    Karree“; Prüfung r20a, zweite Korrektur). Buchstaben klein (re.I bzw. casefold in der Probe)."""
    atome = []
    for i, t in enumerate(_NAMENSTEILE.split(name)):
        if i % 2 == 0:
            atome += ["(?:ß|ss)" if x in ("ß", "ss") else re.escape(x.lower()) for x in re.findall("ß|ss|.", t, re.S)]
        elif t[:1] in "sS":
            atome.append(r"(?:st\.\s?|sankt[-\s]?)")
        elif t[:1] == ".":
            atome.append(r"\.\s?")
        else:
            atome.append(r"[-\s]")
    return atome


def _namen_muster(namen):
    """Alle Straßennamen als ein Muster in Baumform (gemeinsame Anfänge einmal): Ein Muster mit 5 000 Namen als einfache
    Alternative brauchte etwa 5 ms je Titel, die Maske prüft seit dem Sicherheitsnetz jeden Titel zweimal (Prüfung r20a,
    zweite Korrektur). Längere Namen gehen vor (wahlweises Ende hinter den Fortsetzungen, wie vorher die Sortierung nach
    Länge)."""
    baum = {}
    for name in namen:
        knoten = baum
        for atom in _name_atome(name):
            knoten = knoten.setdefault(atom, {})
        knoten[""] = {}

    def muster(knoten):
        zweige = [atom + muster(knoten[atom]) for atom in sorted(a for a in knoten if a)]
        if not zweige:
            return ""
        teil = zweige[0] if len(zweige) == 1 else f"(?:{'|'.join(zweige)})"
        return f"(?:{teil})?" if "" in knoten else teil

    return muster(baum) or r"(?!)"


def _muster(strassen):
    names = {s for s in strassen if s}
    return re.compile(rf"((?:{_namen_muster(names)}|{SUFFIX}){ZWISCHEN}{LAGE}?){NR_WORT}{NR}", re.I)


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
    """Text für die Probe und je Zeichen seine Stelle im Text: je Zeichen NFKC und casefold („ß“ als „ss“), ein folgendes
    Kombinationszeichen mit dem Buchstaben davor zusammengesetzt, ohne unsichtbare Zeichen, Leerraum als ein Leerzeichen.
    Die Stellen braucht das Sicherheitsnetz der Maske (Maske._spannen)."""
    zeichen, stellen = [], []
    for i, c in enumerate(text or ""):
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
            for f in d.casefold():
                zeichen.append(f)
                stellen.append(i)
    return "".join(zeichen), stellen


def _im_text(stellen, a, e, laenge):
    """Stellen a bis e einer angeglichenen oder gefalteten Fassung als Stellen im gelieferten Text; endet der Treffer
    mitten in einem Zeichen, das NFKC erweitert („⒓“ als „12.“), fällt das ganze Zeichen weg."""
    if e >= len(stellen):
        return stellen[a], laenge
    return stellen[a], (stellen[e - 1] + 1 if stellen[e] == stellen[e - 1] else stellen[e])


def _ersetzen(text, teile):
    """Ersetzt (von, bis, Ersatz) im Text; überlappende Teile (nach dem Runden auf ganze Zeichen) bilden einen."""
    aus, bis = [], 0
    for von, nach, ersatz in sorted(teile):
        if von < bis:
            bis = max(bis, nach)
            continue
        aus += [text[bis:von], ersatz]
        bis = nach
    return "".join(aus) + text[bis:]


class _Probe:
    """Unabhängig gebaute Probe für check und Sicherheitsnetz der Maske: Steht im gefalteten Titel (_falten) eine
    Ziffernfolge mit bis zu vier Stellen hinter einem Straßennamen oder einem Wort mit Straßen-Endung, getrennt durch bis
    zu drei Zeichen außer Buchstaben, Ziffern, „§“, „€“, „%“ und „*“ (oder ohne, wenn davor keine Ziffer steht), wahlweise
    mit einem Lagewort („vor“, „in Höhe“, „zwischen“) und „Nr“, „Nrn“, „No“, „Nummer“, „Haus“, „Hs“ oder einem Wort für
    die Hausnummer, nicht vor „.“ oder „:“ mit Ziffer? Oder hinter einem Wort für die Hausnummer, hinter einem bloßen „Nr.“
    ohne folgendes „/“, oder hinter einer ausgeblendeten Hausnummer, wahlweise einer Klammer, einem Wort oder Zeichen für
    eine Liste und „Nr.“ („[Hausnummer ausgelassen] bzw. 14“, „[Hausnummer ausgelassen]) und Nr. 15“)? Nicht hinter einem
    bloßen „Haus“ (Gebäudenummern). So viele Trennzeichen wie die Maske (ZWISCHEN; Prüfung r20a: mit vier und „§“
    meldete die Probe „Straße (§ 24 GO NRW)“). Was die Probe findet, blendet die Maske aus (Maske._spannen): Ein Befund
    in check heißt seither, dass ein Text die Maske nicht durchlaufen hat, nie, dass die Maske ihn nicht beheben kann
    (Prüfung r20a, zweite Korrektur)."""

    def __init__(self, strassen):
        b = r"[^\W\d_]"
        namen = {_falten(s)[0] for s in strassen if s}
        endung = (rf"{b}*(?:strasse|str(?:\.|(?!{b}))|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee|hof|markt"
                  r"|graben|berg|feld)")
        nummer = r"\d{1,4}(?!\d|[.:]\d)"
        trenn = r"[^\w§€%*]"
        wort = r"haus(?:-|\s)?(?:nummern?|nrn?)|hs\.?-?nrn?|h\.?-?nrn?|häusern?"
        nr_wort = rf"(?:{wort}|nrn?|no|nummer|haus|hs)(?!{b})\.?:?"
        lage = (rf"(?:(?:in\s)?h[öo]he|zwischen|zw\.|gegenüber|ggü\.?|vor|neben|hinter|ecke|ab|bis|bei|nahe)(?!{b})"
                rf"\.?\s?(?:(?:den|dem|der|von|vom)\s)?(?={nr_wort})"
                rf"|(?:(?:in\s)?h[öo]he|zwischen|zw\.|gegenüber|ggü\.?|neben|hinter|ecke)(?!{b})\.?\s?(?=\d)")
        liste = rf"(?:[-‐‑‒–—−/,;&+]|bis|und|u\.?(?!{b})|bzw\.?|oder|sowie)"
        strasse = f"{_namen_muster(namen)}|{endung}"
        self.rx = re.compile(rf"(?:{strasse})(?:{trenn}{{1,3}}|(?<!\d))(?:{lage})?(?:{nr_wort}{trenn}{{0,3}})?{nummer}"
                             rf"|\[hausnummer ausgelassen\]\s*[()]?\s*{liste}\s*(?:{nr_wort}\s*)?{nummer}"
                             rf"|\b(?:{wort})(?!{b})\.?:?\s*\)?\s*{nummer}"
                             rf"|\b(?:nrn?|no)(?!{b})\.?:?\s*(?!\d{{1,4}}\s?[a-z]?\s*/){nummer}")

    def __call__(self, titel):
        return bool(self.rx.search(_falten(titel)[0]))

    def spannen(self, titel):
        """Stellen der gemeldeten Ziffernfolgen im gelieferten Titel: (von, bis); jeder Treffer endet mit der Nummer."""
        gefaltet, stellen = _falten(titel)
        teile = []
        for m in self.rx.finditer(gefaltet):
            a = m.end()
            while a > m.start() and gefaltet[a - 1].isdigit():
                a -= 1
            teile.append(_im_text(stellen, a, m.end(), len(titel)))
        return teile


# Zusammenhänge, in denen eine Zahl keine Hausnummer ist (grobe zweite Probe, restzahlen): Rechtsgrundlage, Nummer mit
# „/“ (Drucksache, Bebauungsplan), Jahreszahl, Datum, Uhrzeit und Tausenderpunkt, Ordnungszahl, Zahl mit Einheit oder
# hinter einem Wort wie „TOP“, „Anlage“, „Tempo“, „Linie“ oder einer Straßenklasse („A 4“, „L 84“)
_BEKANNT = re.compile(
    r"§+\s*\d+[a-z]?(?:\s*(?:abs\.?|absatz|satz|s\.|nr\.?|ziff\.?|buchst\.?)\s*\d+[a-z]?)*"
    r"|\d+[a-z]?\s*/\s*\d+(?:\s*/\s*\d+)*"
    r"|(?<!\d)(?:19|20)\d{2}(?!\d)"
    r"|\d+(?:[.:]\d+)+"
    r"|(?<!\d)\d{1,3}\.(?=\s|$)"
    r"|\d+(?:,\d+)?\s*(?:km/h|km|m|qm|m²|ha|%|prozent|euro|eur|€|mio\.?|stunden|std\.?|minuten|min\.?|tage[n]?"
    r"|wochen|monate[n]?|jahre[n]?|personen|plätze|stellplätze|parkplätze|bäume|meter|wohnungen|wohneinheiten|kinder)"
    r"(?![^\W\d_])"
    r"|\b(?:top|anlage|anlagen|tempo|linie|linien|buslinie|stadtbahnlinie|bab|[abkl]|art\.?|artikel|kapitel|stufe|phase"
    r"|bauabschnitt|abschnitt|teil|los|wahlperiode|ziffer|punkt|gruppe|klasse|nummer der drucksache)\s*\d+[a-z]?(?!\d)")


def restzahlen(titel):
    """Grobe zweite Probe für check (nur Hinweis, kein Befund; Prüfung r20a, zweite Korrektur): Steht nach dem Ausblenden
    noch eine Zahl mit bis zu vier Stellen außerhalb bekannter Zusammenhänge (_BEKANNT) im Titel? Gedacht für die
    Durchsicht von Hand nach dem ersten Vollabruf, nicht als Sperre."""
    rest = _BEKANNT.sub(" ", _falten(titel)[0])
    return bool(re.search(r"(?<!\d)\d{1,4}(?!\d)", rest))


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
        self._offen = {}   # check prüft denselben Titel je Datei und Ortsbezug: je (Text, Drucksache) einmal rechnen
        self._aus = {}     # export maskiert denselben Titel je Datei, Audit und Ortsbezug: ebenso (Prüfung r20a)

    def _betroffen(self, titel, ref):
        # ohne Ziffer keine Hausnummer: spart die teure Regex bei den meisten Titeln (gleiche Ergebnisse); Ziffern auch
        # erst nach NFKC („⒓“ ist für isdigit keine Ziffer; Prüfung r20a, zweite Korrektur)
        return (bool(titel) and ref in self.refs
                and any(c.isdigit() for c in unicodedata.normalize("NFKC", titel)))

    def _stellen(self, angeglichen):
        """Zu ersetzende Stellen im angeglichenen Titel: (Anfang, Ende, Ersatz); Straße, Trennzeichen und Lagewort
        bleiben stehen, „Nr.“ und die Nummer fallen weg; „Hausnummer 5“ samt dem Wort (WORT), eine schließende Klammer
        bleibt; ein bloßes „Nr. 5“ samt „Nr.“ (NUR_NR)."""
        teile = [(m.end(1), m.end(), OHNE_NR) for m in self.rx.finditer(angeglichen)]
        for rx, klammer in ((WORT, True), (NUR_NR, False)):
            for m in rx.finditer(angeglichen):
                if not any(a < m.end() and m.start() < e for a, e, _ in teile):
                    teile.append((m.start(), m.end(), OHNE_NR + ((m.group(1) or "") if klammer else "")))
        return sorted(teile)

    def _spannen(self, text):
        """Was die Maske im Text ersetzt: (von, bis, Ersatz) im gelieferten Text. Zuerst die Muster der Maske; finden sie
        nichts, die Ziffernfolgen, die die Probe meldet (Sicherheitsnetz, Prüfung r20a, zweite Korrektur)."""
        angeglichen, stellen = _angleichen(text)
        teile = [(*_im_text(stellen, a, e, len(text)), ersatz) for a, e, ersatz in self._stellen(angeglichen)]
        if not teile:
            if self._probe is None:
                self._probe = _Probe(self.strassen)
            teile = [(von, bis, OHNE_NR) for von, bis in self._probe.spannen(text)]
        return teile

    def __call__(self, titel, ref):
        """Ersetzt, bis weder die Muster der Maske noch die Probe etwas finden: jede Runde blendet mindestens eine
        Ziffernfolge aus, also endet die Schleife. Danach ist offen() für das Ergebnis immer falsch; ein Befund in check
        kann also nur einen Text betreffen, der die Maske nicht durchlaufen hat (vorher meldete check etwa
        „(Musterstraße 12) – 2. Nachtrag“, die Maske ließ die 2 stehen, und die Veröffentlichung hätte angehalten)."""
        if not self._betroffen(titel, ref):
            return titel
        if (titel, ref) not in self._aus:
            aus = titel
            for _ in range(len(titel) + 1):
                teile = self._spannen(aus)
                if not teile:
                    break
                aus = _ersetzen(aus, teile)
            self._aus[titel, ref] = aus
            self._offen[aus, ref] = bool(teile)
        return self._aus[titel, ref]

    def offen(self, titel, ref):
        """Bleibt eine Hausnummer stehen, würde die Maske den Text also noch ändern? (Prüfung in check.py) Mit den Mustern
        der Maske und der unabhängig gebauten Probe (_Probe; Prüfung r20n)."""
        if not self._betroffen(titel, ref):
            return False
        if (titel, ref) not in self._offen:
            self._offen[titel, ref] = bool(self._spannen(titel))
        return self._offen[titel, ref]


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
