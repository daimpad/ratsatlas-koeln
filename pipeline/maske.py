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
Karree“).
Ergänzt in der Prüfung r20a (dritte Korrektur): Muster für Hausnummern bleiben lückenhaft (die Prüfung fand weitere
Schreibweisen: Nummer vor der Straße, „am Haus 12“, „vor Nr. 12/14“, „12 bis 14 (gerade) und 13 bis 17“, unbekannte
Straßennamen). Deshalb blendet die Maske in ihren Titeln zuletzt jede Zahl mit bis zu vier Stellen aus, die nicht in
einem bekannten Zusammenhang steht (Positivliste _BEKANNT: Rechtsgrundlage, Drucksache, Bebauungsplan, Jahreszahl,
Datum, Uhrzeit, Ordnungszahl vor einem Wort, Betrag und Menge mit Einheit, „TOP 5“, „Tempo 30“, Straßenklasse,
Kennung wie „U18“). Kölner Hausnummern haben höchstens vier Stellen (data/geo/hausnummern_koeln.json: höchste 1435),
keine liegt zwischen 1900 und 2099. Das kürzt auch Zahlen, die keine Hausnummer sind („Kita [Hausnummer ausgelassen]“);
das Original bleibt über den Link erreichbar. Fundstellen aus dem Titel maskiert die Maske im Zusammenhang des ganzen
Titels (Maske.ausschnitt), Hausnummern in Worten hinter „Hausnummer“ oder „Nummer“ ebenso (ZAHLWORT).
Ergänzt in der Nachprüfung der dritten Korrektur: Ein unsichtbares Zeichen zwischen zwei Ziffern gilt als Bindestrich
(_unsichtbar_trennen); vorher verschmolzen „98\u00ad100“ oder „20\u00ad22“ zu einer Zahl, die die Maske stehen ließ."""
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
# Spalten jeder TSV-Datei unter data/export mit der Spalte „drucksache“, die Titel, Teile des Titels oder Ortsnamen
# tragen: export._tabellen_maskieren maskiert sie, check._tabellen_mit_titel prüft sie (Prüfung r20a: „titel“,
# „fundstelle“, „treffer“; zweite Korrektur: „ort“, „zurueckgestellt“; dritte Korrektur: jede Datei mit „drucksache“,
# auch ohne „titel“, dazu „gebäude oder anlage“ aus audit_objekte_titel.tsv)
TEXTSPALTEN = frozenset({"titel", "fundstelle", "treffer", "ort", "zurueckgestellt", "gebäude oder anlage"})
# Bauordnungsamt und Untere Naturschutzbehörden: Titel nennen oft private Baugrundstücke mit Hausnummer
AMT_PRIVAT = re.compile(r"^(?:63(?:\s|-)|56-3\b|67-6\b)")
_L = r"[^\W\d_]"   # Buchstabe (wie \p{L})
# wie NR und SUFFIX in site/chat/tools.js, aber bis zu vier Ziffern: Kölner Straßen haben vierstellige Hausnummern
# („Aachener Straße 1175“, „Militärringstraße 1000“; geocode.HAUSNUMMER liest sie ebenso; Generalprobe 09.11.2026).
# „Str“ auch ohne Punkt („Aachener Str 12“, Prüfung r20n). Der Assistent (site/chat/tools.js, in Köln abgeschaltet)
# folgt mit seiner Freigabe. Listen auch mit „bzw.“, „oder“, „sowie“, „&“, „+“ und jedem Binde- oder Gedankenstrich
# („12 bzw. 14“, „12 — 14“, „12‑14“ mit geschütztem Bindestrich; vorher blieb die zweite Nummer stehen). Keine Nummer
# vor „.“ oder „:“ mit Ziffer („Musterweg, 12.03.2026“, „1.000 EUR“, „12:30 Uhr“; Prüfung r20a)
# Keine Jahreszahl von 1900 bis 2099: In Köln gibt es keine solche Hausnummer (data/geo/hausnummern_koeln.json, höchste
# 1435; wie geocode._hnr_nummer). Vorher blendete die Maske „Weihnachtsmarkt 2026“ oder „Sommerfest im Park 2026“ aus
# (Prüfung r20a, dritte Korrektur)
_JAHR = r"(?:19|20)\d\d(?!\d)"
_ZIFFERN = rf"(?!{_JAHR})\d{{1,4}}(?![.:]\d)"
# Buchstabe der Hausnummer („12a“, „12 b“), aber nicht das „u“ oder „o“ einer Liste vor einer Ziffer („7 u. 9“,
# „53 u 55“, „12 o. 14“; vorher las die Maske „ u“ als Zusatz, und die zweite Nummer blieb stehen; Prüfung r20a, zweite
# und dritte Korrektur)
_ZUSATZ = rf"(?:\s?(?![uo]\.?\s*\d)[a-zA-Z](?!{_L}))?"
LISTE = rf"(?:[-‐‑‒–—−/,;&+]|bis|und|u\.?(?!{_L})|bzw\.?|oder|sowie)"
# Wörter für die Hausnummer, auch in der Mehrzahl und mit Leerzeichen („Haus-Nrn.“, „Hausnrn.“, „Haus Nummer“, „Häuser“)
_HNR = r"haus(?:-|\s+)?(?:nummern?|nrn?)|hs\.?-?nrn?|h\.?-?nrn?|häusern?"
# vor der Nummer hinter einer Straße und vor jeder weiteren Nummer einer Liste („Nr. 23 und Nr. 25“, „12 bis Nr. 20“)
_NRW = rf"(?:{_HNR}|nrn?|no|nummer|haus|hs)(?!{_L})\.?:?"
# Drucksache „1234/2026“ oder vierstelliger Bebauungsplan „5843/03“: keine weitere Nummer einer Liste und kein bloßes
# „Nr. 1234/2026“ (vorher wurde „(Musterstraße 12) – Nr. 6336/2026“ zu „Nr. [Hausnummer ausgelassen]/…“); „Nr. 12/14“
# ist dagegen eine Hausnummer (Prüfung r20a, dritte Korrektur: vorher galt jedes „Nr. 12/“ als Drucksache)
_DRUCKSACHE = r"\d{4}\s*/\s*(?:(?:19|20)\d\d|\d\d)(?!\d)"
# Zahl mit Einheit („3 Bäume“, „6,5 Mio. €“, „18 Uhr“) und Ordnungszahl vor einem Wort wie „Nachtrag“, „Änderung“ oder
# einem Monat („2. Nachtrag“, „12. März“): keine weitere Nummer einer Liste (vorher wurde „Venloer Straße 123 –
# 2. Änderung“ zu „… [Hausnummer ausgelassen]. Änderung“; Prüfung r20a, dritte Korrektur). Direkt hinter der Straße oder
# einem Wort für die Hausnummer nur Betrag, Prozent und Uhrzeit nicht („Raderberg – 6,5 Mio. €“); „Venloer Straße
# 12. Nachtrag“ oder „… 3 Bäume“ könnte eine Hausnummer sein und fällt weiter weg. Dieselben Wörter in der Positivliste
# (_BEKANNT). Ohne „m“: ein einzelner Buchstabe kann der Zusatz einer Hausnummer sein
_EINHEIT_BETRAG = r"%|prozent|euro|eur|€|mio\.?|mrd\.?|tsd\.?|uhr"
_EINHEIT = (rf"{_EINHEIT_BETRAG}|km/h|km|qm|m²|ha|stunden|std\.?|minuten|min\.?|tag(?:e|en)?|woche(?:n)?"
            r"|monat(?:e|en)?|jahr(?:e|en)?|personen|plätze|stellplätze|parkplätze|bäume|meter|wohnungen|wohneinheiten"
            r"|kinder|stimmen|stück|mal")
_ORDNUNG = (r"nachtrag|änderung|aenderung|ergänzung|ergaenzung|fortschreibung|bauabschnitt|abschnitt|sitzung|lesung"
            r"|satzung|quartal|halbjahr|beratung|version|fassung|stufe|phase|teil|auflage|bericht|sachstand|runde"
            r"|staffel|etappe|preis|ebene|etage|obergeschoss|termin|jahrestag|geburtstag|jubiläum|jubilaeum"
            r"|bürgermeister|buergermeister|stellvertret|vorsitz|beigeordnet|ausschreibung|wahl|legislatur|haushalt"
            r"|nachtragshaushalt|fortsetzung|durchgang|verfahren|offenlage|beteiligung|planänderung|entwurf|vorlage"
            r"|mitteilung|beschluss|kölner|koelner|internationale|deutsche|januar|februar|märz|maerz|april|juni|juli"
            r"|august|september|oktober|november|dezember|(?:los|og|stock|fc|mai|jan|feb|mär|apr|jun|jul|aug|sept?|okt"
            r"|nov|dez)(?![^\W\d_])")
_KEIN_BETRAG = rf"(?!\d+(?:,\d+)?\s*(?:{_EINHEIT_BETRAG})(?![^\W\d_]))"
_KEINE_NR = rf"(?!\d+(?:,\d+)?\s*(?:{_EINHEIT})(?![^\W\d_])|\d{{1,3}}\.\s?(?:{_ORDNUNG}))"
NR = (rf"{_KEIN_BETRAG}{_ZIFFERN}{_ZUSATZ}"
      rf"(?:\s*{LISTE}\s*(?:{_NRW}\s*)?(?!{_DRUCKSACHE}){_KEINE_NR}{_ZIFFERN}{_ZUSATZ})*(?!\d)")
# Straßen-Endung am Anfang eines Worts gebunden (kein Buchstabe, Punkt oder Bindestrich davor): dieselben Treffer, aber
# ohne quadratischen Aufwand bei langen Wörtern (Prüfung r20a, dritte Korrektur: ein Wort aus 5 000 Buchstaben 3 s)
_WORTANFANG = r"(?<![^\W\d_.-])"
SUFFIX = (rf"{_WORTANFANG}(?:{_L}|[.-])*(?:straße|strasse|str(?:\.|(?!{_L}))|weg|platz|gasse|allee|ring|ufer|damm|pfad"
          r"|chaussee|hof|markt|graben|berg|feld)")
# Hausnummer in Worten hinter „Hausnummer“, „Nr.“ oder „Nummer“ („Venloer Straße Hausnummer zwölf“; Prüfung r20a, dritte
# Korrektur); hinter einer Straße ohne solches Wort bleibt sie stehen (TECHNIK.md, offen)
_ZAHLWORT = (r"eins|ein|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|elf|zwölf|zwoelf|dreizehn|vierzehn"
             r"|fünfzehn|fuenfzehn|sechzehn|siebzehn|achtzehn|neunzehn|zwanzig")
ZAHLWORT = re.compile(rf"\b(?:{_HNR}|nrn?|no|nummern?)(?!{_L})\.?:?\s*\(?\s*((?:{_ZAHLWORT})(?!{_L}))", re.I)


# „Hausnummer 82“, „Haus-Nr. 264“, „Haus Nr. 5“, „Hausnummern 36 bis 40“, „(neben Haus-Nr.) 68“ (wie WORT in
# site/chat/tools.js); eine schließende Klammer bleibt stehen. Auch „Hausnummer: 8“, „Haus-Nummer 12“, „Hs.-Nr. 12“,
# „HNr. 12“ und „H.-Nr. 12“ (Prüfung r20a), „Haus-Nrn.“, „Haus Nummer“, „Häuser 300 bis 304“ (zweite Korrektur)
WORT = re.compile(rf"\b(?:{_HNR})(?!{_L})\.?:?\s*(\))?\s*{NR}", re.I)
# bloßes „Nr. 12“ ohne Straße davor („Behindertenparkplatz vor Nr. 12 der Musterstraße“), auch „Nr. 12/14“, aber keine
# Drucksache und kein Bebauungsplan („Nr. 1234/2026“, „Nr. 6158/03“; Prüfung r20a, zweite Korrektur; dritte Korrektur:
# vorher blieb jedes „Nr. 12/…“ stehen)
NUR_NR = re.compile(rf"\b(?:nrn?|no)(?!{_L})\.?:?\s*(?!{_DRUCKSACHE}){NR}", re.I)


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
    """Straße (Name aus dem Verzeichnis am Anfang eines Worts oder Straßen-Endung), Trennzeichen, Lagewort, Wort für die
    Nummer, Nummer. Ohne Buchstaben vor dem Namen: vorher traf „Stadtbezirk 4 (2026)“ den Namen „K 4“ (Prüfung r20a,
    dritte Korrektur)."""
    names = {s for s in strassen if s}
    return re.compile(rf"((?:(?<!{_L})(?:{_namen_muster(names)})|{SUFFIX}){ZWISCHEN}{LAGE}?){NR_WORT}{NR}", re.I)


# Trennzeichen für unsichtbare Zeichen zwischen zwei Ziffern (_angleichen, _falten): Gelöscht verschmolz „98\u00ad100“
# (weiches Trennzeichen U+00AD, Word: Strg+-) oder „20\u200b22“ (Zeichen ohne Breite) zu einer Zahl mit fünf Stellen
# oder einer Jahreszahl, die weder Muster noch Positivliste ausblenden; der Titel blieb unverändert, und check meldete
# nichts (Nachprüfung der dritten Korrektur der Prüfung r20a). Als Bindestrich sehen Muster, Probe und Positivliste
# zwei Nummern einer Liste und ersetzen beide samt dem Zeichen
_ZIFFERNTRENNER = "-"


def _unsichtbar_trennen(text):
    """Je Zeichen des Texts (Stelle, Zeichen nach NFKC oder None für ein unsichtbares Zeichen, das wegfällt): Steht ein
    unsichtbares Zeichen (auch mehrere) zwischen zwei Ziffern, gilt das erste als _ZIFFERNTRENNER."""
    hinter_ziffer, trenner = False, None
    for i, c in enumerate(text):
        if geocode._UNSICHTBAR.match(c):
            if hinter_ziffer and trenner is None:
                trenner = i
            yield i, None
            continue
        n = unicodedata.normalize("NFKC", c)
        if trenner is not None and n[:1].isdecimal():
            yield trenner, _ZIFFERNTRENNER
        trenner, hinter_ziffer = None, n[-1:].isdecimal()
        yield i, n


def _angleichen(titel):
    """Angeglichene Fassung eines Titels für den Abgleich und je Zeichen seine Stelle im Titel: je Zeichen NFKC
    (Vollbreite, „№“ als „No“, geschütztes Leerzeichen), ein folgendes Kombinationszeichen mit dem Buchstaben davor
    zusammengesetzt, ohne weiche Trennzeichen und Zeichen ohne Breite (geocode._UNSICHTBAR; zwischen zwei Ziffern als
    _ZIFFERNTRENNER), jeder Leerraum (auch Zeilenumbruch, doppelt) als ein Leerzeichen. Ersetzt wird über die Stellen im
    gelieferten Titel, der sonst unverändert bleibt."""
    zeichen, stellen = [], []
    for i, n in _unsichtbar_trennen(titel):
        if n is None:
            continue
        for d in n:
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
    Kombinationszeichen mit dem Buchstaben davor zusammengesetzt, ohne unsichtbare Zeichen (zwischen zwei Ziffern als
    _ZIFFERNTRENNER), Leerraum als ein Leerzeichen. Die Stellen braucht das Sicherheitsnetz der Maske (Maske._spannen)."""
    zeichen, stellen = [], []
    for i, n in _unsichtbar_trennen(text or ""):
        if n is None:
            continue
        for d in n:
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
    """Probe der Maske (Sicherheitsnetz in Maske._spannen, seit der zweiten Korrektur der Prüfung r20a Teil der Maske,
    nicht mehr unabhängig): Steht im gefalteten Titel (_falten) eine Ziffernfolge mit bis zu vier Stellen (keine
    Jahreszahl von 1900 bis 2099) hinter einem Straßennamen am Anfang eines Worts oder einem Wort mit Straßen-Endung,
    getrennt durch bis zu drei Zeichen außer Buchstaben, Ziffern, „§“, „€“, „%“ und „*“ (oder ohne, wenn davor keine
    Ziffer steht), wahlweise mit einem Lagewort („vor“, „in Höhe“, „zwischen“) und „Nr“, „Nrn“, „No“, „Nummer“, „Haus“,
    „Hs“ oder einem Wort für die Hausnummer, nicht vor „.“ oder „:“ mit Ziffer? Oder hinter einem Wort für die
    Hausnummer, hinter einem bloßen „Nr.“ (keine Drucksache „1234/2026“), oder hinter einer ausgeblendeten Hausnummer,
    wahlweise einer Klammer, einem Wort oder Zeichen für eine Liste und „Nr.“ („[Hausnummer ausgelassen] bzw. 14“,
    „[Hausnummer ausgelassen]) und Nr. 15“)? Nicht hinter einem bloßen „Haus“ (das erfasst die Positivliste, _BEKANNT).
    So viele Trennzeichen wie die Maske (ZWISCHEN; Prüfung r20a: mit vier und „§“ meldete die Probe „Straße (§ 24 GO
    NRW)“). Was die Probe findet, blendet die Maske aus (Maske._spannen)."""

    def __init__(self, strassen):
        b = r"[^\W\d_]"
        namen = {_falten(s)[0] for s in strassen if s}
        endung = (rf"(?<![^\W\d_.-]){b}*(?:strasse|str(?:\.|(?!{b}))|weg|platz|gasse|allee|ring|ufer|damm|pfad|chaussee"
                  r"|hof|markt|graben|berg|feld)")
        nummer = rf"(?!{_JAHR})\d{{1,4}}(?!\d|[.:]\d)"
        erste, weitere = f"{_KEIN_BETRAG}{nummer}", f"{_KEINE_NR}{nummer}"
        trenn = r"[^\w§€%*]"
        wort = r"haus(?:-|\s)?(?:nummern?|nrn?)|hs\.?-?nrn?|h\.?-?nrn?|häusern?"
        nr_wort = rf"(?:{wort}|nrn?|no|nummer|haus|hs)(?!{b})\.?:?"
        lage = (rf"(?:(?:in\s)?h[öo]he|zwischen|zw\.|gegenüber|ggü\.?|vor|neben|hinter|ecke|ab|bis|bei|nahe)(?!{b})"
                rf"\.?\s?(?:(?:den|dem|der|von|vom)\s)?(?={nr_wort})"
                rf"|(?:(?:in\s)?h[öo]he|zwischen|zw\.|gegenüber|ggü\.?|neben|hinter|ecke)(?!{b})\.?\s?(?=\d)")
        liste = rf"(?:[-‐‑‒–—−/,;&+]|bis|und|u\.?(?!{b})|bzw\.?|oder|sowie)"
        strasse = f"(?<!{b})(?:{_namen_muster(namen)})|{endung}"
        self.rx = re.compile(rf"(?:{strasse})(?:{trenn}{{1,3}}|(?<!\d))(?:{lage})?(?:{nr_wort}{trenn}{{0,3}})?{erste}"
                             rf"|\[hausnummer ausgelassen\]\s*[()]?\s*{liste}\s*(?:{nr_wort}\s*)?"
                             rf"(?!{_DRUCKSACHE}){weitere}"
                             rf"|\b(?:{wort})(?!{b})\.?:?\s*\)?\s*{erste}"
                             rf"|\b(?:nrn?|no)(?!{b})\.?:?\s*(?!{_DRUCKSACHE}){erste}")

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


# Positivliste der Titelmaske (Prüfung r20a, dritte Korrektur; vorher nur grobe zweite Probe für einen Hinweis in
# check): Zusammenhänge, in denen eine Zahl keine Hausnummer ist. Jede andere Zahl mit bis zu vier Stellen blendet die
# Maske in ihren Titeln aus (_restzahl_spannen). Im gefalteten Text (klein, „ß“ als „ss“): Adresse im Netz und
# HTML-Entität, Rechtsgrundlage, Drucksache „1234/2026“ und Bebauungsplan „5843/03“ oder „61589/03“ (nicht „12/14“:
# vorher galt jede Nummer mit „/“ als bekannt, und „Nr. 12/14“ blieb ohne Hinweis stehen), Jahreszahl 1900 bis 2099
# (keine Kölner Hausnummer), Datum, Uhrzeit, Tausenderpunkt und Dezimalzahl, Ordnungszahl vor einem Wort aus _ORDNUNG
# („2. Nachtrag“, „12. März“; vor einem klein geschriebenen Wort auch sonst, _restzahl_spannen; nicht am Ende des Titels
# und nicht vor einem anderen groß geschriebenen Wort: „Einfahrt 12.“, „vor Haus 12. Anwohner …“), Betrag und Menge mit
# Einheit (_EINHEIT), Zahl hinter Wörtern wie „TOP“, „Anlage“, „Tempo“, „Linie“, „Stadtbezirk“, „Bezirksvertretung“ oder
# einer Straßenklasse („A 4“, „L 84“), Kennung aus bis zu drei Buchstaben und Ziffern („U18“, „CO2“, „T1“; nicht „Nr12“
# oder „Hs12“). „Abschnitt“ fehlt („im Abschnitt 12-20“ ist eine Hausnummer)
_BEKANNT = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|&#(?:\d+|x[0-9a-f]+);"
    r"|§+\s*\d+[a-z]?(?:\s*(?:abs\.?|absatz|satz|s\.|nr\.?|ziff\.?|buchst\.?|,|und|bis|-|–)\s*\d+[a-z]?)*"
    r"|(?<!\d)\d{4,6}\s*/\s*(?:(?:19|20)\d\d|\d\d)(?!\d)"
    r"|(?<!\d)(?:19|20)\d{2}(?!\d)"
    r"|(?<!\d)\d+(?:[.:]\d+)+"
    rf"|(?<!\d)\d{{1,3}}\.(?=\s?(?:{_ORDNUNG}))"
    r"|(?:€|\beuro?)\s*\d+(?:[.,]\d+)*"
    rf"|(?<!\d)\d+(?:,\d+)?\s*(?:{_EINHEIT})(?![^\W\d_])"
    r"|\b(?:top|tagesordnungspunkt(?:e|en)?|anlage(?:n)?|tempo|linie(?:n)?|buslinie(?:n)?|stadtbahnlinie(?:n)?|bab"
    r"|[abkl]|art\.?|artikel|kapitel|stufe|phase|bauabschnitt|teil|los|wahlperiode|ziffer|punkt|gruppe|klasse"
    r"|drucksache|nummer der drucksache|stadtbezirk(?:e|en)?|bezirk(?:e|en)?|bezirksvertretung(?:en)?|bv|kw"
    r"|kalenderwoche)\s*\d+[a-z]?(?!\d)"
    r"|\b(?!(?:nrn?|no|hs?|hnr)\d)[^\W\d_]{1,3}\d+")
_ZAHL = re.compile(r"(?<!\d)\d{1,4}(?!\d)")
_ORDNUNGSZAHL = re.compile(r"(?<!\d)\d{1,3}\.\s?(?=[^\W\d_])")
_ZAHL_ZUSATZ = re.compile(r"\s?(?![uo]\.?\s*\d)[a-z](?![^\W\d_])")


def _restzahl_spannen(text):
    """Stellen der Zahlen mit bis zu vier Stellen außerhalb bekannter Zusammenhänge (_BEKANNT) im gelieferten Text, samt
    Buchstabe der Hausnummer („12a“, „12 b“): (von, bis)."""
    gefaltet, stellen = _falten(text)
    # Ordnungszahl vor einem klein geschriebenen Wort im gelieferten Text („2. geänderte Fassung“); vor einem groß
    # geschriebenen nur aus der Liste (_ORDNUNG), sonst könnte es das Ende eines Satzes sein („vor Haus 12. Bitte …“)
    bekannt = []
    for a, e in sorted([(m.start(), m.end()) for m in _BEKANNT.finditer(gefaltet)]
                       + [(m.start(), m.end()) for m in _ORDNUNGSZAHL.finditer(gefaltet)
                          if text[stellen[m.end()]].islower()]):
        if bekannt and a <= bekannt[-1][1]:   # überlappende Zusammenhänge zusammenfassen
            bekannt[-1][1] = max(bekannt[-1][1], e)
        else:
            bekannt.append([a, e])
    teile, i = [], 0
    for m in _ZAHL.finditer(gefaltet):
        while i < len(bekannt) and bekannt[i][1] <= m.start():
            i += 1
        if i < len(bekannt) and bekannt[i][0] <= m.start() and m.end() <= bekannt[i][1]:
            continue
        zusatz = _ZAHL_ZUSATZ.match(gefaltet, m.end())
        teile.append(_im_text(stellen, m.start(), zusatz.end() if zusatz else m.end(), len(text)))
    return teile


def restzahlen(titel):
    """Steht im Text eine Zahl mit bis zu vier Stellen außerhalb bekannter Zusammenhänge (_BEKANNT)? Die Maske blendet
    solche Zahlen in ihren Titeln aus (Positivliste, Prüfung r20a, dritte Korrektur); check zählt damit Titel außerhalb
    der Maske für den Hinweis zu Vorlagen ohne Hauskoordinate."""
    return bool(_restzahl_spannen(titel))


def _rueckfall_spannen(text):
    """Sicherer Rückfall nach RUNDEN Runden: jede Ziffernfolge mit bis zu vier Stellen (im gefalteten Text)."""
    gefaltet, stellen = _falten(text)
    return [_im_text(stellen, m.start(), m.end(), len(text)) for m in _ZAHL.finditer(gefaltet)]


def _ersetzen_herkunft(zeichen, teile):
    """Wie _ersetzen, aber auf Zeichen mit Herkunft (Zeichen, von, bis im ursprünglichen Titel): Der Ersatz trägt die
    Stellen aller Zeichen, die er ersetzt (für Maske.ausschnitt)."""
    gruppen = []
    for von, nach, ersatz in sorted(teile):
        if gruppen and von < gruppen[-1][1]:
            gruppen[-1][1] = max(gruppen[-1][1], nach)
        else:
            gruppen.append([von, nach, ersatz])
    neu, pos = [], 0
    for von, nach, ersatz in gruppen:
        neu += zeichen[pos:von]
        teil = zeichen[von:nach] or zeichen[max(von - 1, 0):von]
        a, b = (min(z[1] for z in teil), max(z[2] for z in teil)) if teil else (0, 0)
        neu += [(c, a, b) for c in ersatz]
        pos = max(pos, nach)
    return neu + zeichen[pos:]


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


# Runden der Maske, danach sicherer Rückfall (jede Ziffernfolge mit bis zu vier Stellen): Bei verketteten Fällen braucht
# die Maske eine Runde je Nummer, jede über den ganzen Text („Musterstraße (1) und 2) und 3) …“ mit 5 kB: 22 s je Titel;
# Prüfung r20a, dritte Korrektur)
RUNDEN = 20
# Fundstellen mit einem Zusatz hinter dem Teil aus dem Titel („… – Antrag der SPD-Fraktion (Vorlagenart: …)“,
# „… (Straßenabschnitt ohne Hausnummer)“): Teil vor „ (“, der im Titel steht
_ZUSATZ_FUNDSTELLE = " ("


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
        self._herkunft = {}   # Herkunft je Zeichen der zuletzt maskierten Titel (ausschnitt; klein gehalten)

    def _betroffen(self, titel, ref):
        # ohne Ziffer und ohne Hausnummer in Worten keine Hausnummer: spart die teure Regex bei den meisten Titeln
        # (gleiche Ergebnisse); Ziffern auch erst nach NFKC („⒓“ ist für isdigit keine Ziffer; Prüfung r20a, zweite
        # Korrektur), Zahlwörter im angeglichenen Titel (dritte Korrektur)
        if not titel or ref not in self.refs:
            return False
        if any(c.isdigit() for c in unicodedata.normalize("NFKC", titel)):
            return True
        return bool(ZAHLWORT.search(titel) or (geocode._UNSICHTBAR.search(titel)
                                               and ZAHLWORT.search(_angleichen(titel)[0])))

    def _stellen(self, angeglichen):
        """Zu ersetzende Stellen im angeglichenen Titel: (Anfang, Ende, Ersatz); Straße, Trennzeichen und Lagewort
        bleiben stehen, „Nr.“ und die Nummer fallen weg; „Hausnummer 5“ samt dem Wort (WORT), eine schließende Klammer
        bleibt; ein bloßes „Nr. 5“ samt „Nr.“ (NUR_NR); „Hausnummer zwölf“ samt dem Wort (ZAHLWORT)."""
        teile = [(m.end(1), m.end(), OHNE_NR) for m in self.rx.finditer(angeglichen)]
        for rx, klammer in ((WORT, True), (NUR_NR, False), (ZAHLWORT, False)):
            for m in rx.finditer(angeglichen):
                if not any(a < m.end() and m.start() < e for a, e, _ in teile):
                    teile.append((m.start(), m.end(), OHNE_NR + ((m.group(1) or "") if klammer else "")))
        return sorted(teile)

    def _spannen(self, text):
        """Was die Maske im Text ersetzt: (von, bis, Ersatz) im gelieferten Text. Zuerst die Muster der Maske; finden sie
        nichts, die Ziffernfolgen, die die Probe meldet (Sicherheitsnetz, Prüfung r20a, zweite Korrektur); findet auch
        sie nichts, jede Zahl außerhalb bekannter Zusammenhänge (Positivliste _BEKANNT, dritte Korrektur)."""
        angeglichen, stellen = _angleichen(text)
        teile = [(*_im_text(stellen, a, e, len(text)), ersatz) for a, e, ersatz in self._stellen(angeglichen)]
        if not teile:
            if self._probe is None:
                self._probe = _Probe(self.strassen)
            teile = [(von, bis, OHNE_NR) for von, bis in self._probe.spannen(text)]
        if not teile:
            teile = [(von, bis, OHNE_NR) for von, bis in _restzahl_spannen(text)]
        return teile

    def _maskieren(self, titel):
        """(Ergebnis, Herkunft): Runden wie in __call__; Herkunft je Zeichen des Ergebnisses (Zeichen, von, bis): die
        Stellen im gelieferten Titel, aus denen es stammt (ein Ersatz trägt die Stellen aller ersetzten Zeichen)."""
        zeichen = [(c, i, i + 1) for i, c in enumerate(titel)]
        aus = titel
        for runde in range(RUNDEN + 1):
            teile = self._spannen(aus) if runde < RUNDEN else [(a, e, OHNE_NR) for a, e in _rueckfall_spannen(aus)]
            if not teile:
                break
            zeichen = _ersetzen_herkunft(zeichen, teile)
            aus = "".join(z[0] for z in zeichen)
        return aus, zeichen

    def __call__(self, titel, ref):
        """Ersetzt in Runden, bis weder die Muster der Maske noch die Probe noch die Positivliste etwas finden: jede
        Runde blendet mindestens eine Ziffernfolge aus; nach RUNDEN Runden blendet der Rückfall jede verbliebene
        Ziffernfolge mit bis zu vier Stellen aus. Danach ist offen() für das Ergebnis falsch. Weil die Positivliste jede
        unbekannte Zahl ausblendet, heißt ein Befund in check: Der Text hat die Maske nicht durchlaufen; eine Hausnummer
        bleibt nur in einem Zusammenhang aus _BEKANNT stehen (TECHNIK.md, offen)."""
        if not self._betroffen(titel, ref):
            return titel
        if (titel, ref) not in self._aus:
            aus, zeichen = self._maskieren(titel)
            if len(self._herkunft) > 256:
                self._herkunft.clear()
            self._herkunft[titel] = zeichen
            self._aus[titel, ref] = aus
            self._offen[aus, ref] = False
        return self._aus[titel, ref]

    def ausschnitt(self, text, titel, ref):
        """Fundstelle `text`, die ein Teil des Titels ist (Einreichende, Bebauungsplan, Ortsbezug), so maskiert wie im
        ganzen Titel: Die Stellen, die die Maske im Titel ersetzt, gelten auch für den Ausschnitt (vorher maskierte
        export den Ausschnitt allein, und „1175, Hinterhof … – Anfrage der Fraktion …“ behielt die Nummer, deren Straße
        vor dem Ausschnitt stand; Prüfung r20a, dritte Korrektur). Ein Zusatz hinter „ (“, der nicht im Titel steht,
        und eine Fundstelle außerhalb des Titels werden für sich maskiert; zuletzt das Ganze noch einmal (offen() ist
        danach falsch, auch wo der Ausschnitt einen bekannten Zusammenhang abschneidet)."""
        if not self._betroffen(text, ref):
            return text
        teil, rest = "", text
        if titel and self._betroffen(titel, ref):
            for k in [len(text)] + [i for i in range(len(text) - 1, 0, -1)
                                    if text.startswith(_ZUSATZ_FUNDSTELLE, i)]:
                if text[:k] and text[:k] in titel:
                    teil, rest = text[:k], text[k:]
                    break
        if teil:
            self(titel, ref)
            zeichen = self._herkunft.get(titel)
            if zeichen is None:
                zeichen = self._maskieren(titel)[1]
            s = titel.index(teil)
            e = s + len(teil)
            teil = "".join(c for c, a, b in zeichen if a < e and b > s)
        return self(teil + rest, ref)

    def offen(self, titel, ref):
        """Würde die Maske den Text noch ändern? (Prüfung in check.py) Mit den Mustern der Maske, der Probe und der
        Positivliste (Maske._spannen); für jedes Ergebnis der Maske falsch."""
        if not titel or ref not in self.refs:
            return False
        if (titel, ref) not in self._offen:
            self._offen[titel, ref] = self._betroffen(titel, ref) and bool(self._spannen(titel))
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
