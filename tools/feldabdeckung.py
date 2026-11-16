"""Feldabdeckung der Rohdaten für das Log und die Zusammenfassung des Workflows (pages.yml, gleich nach dem Fortschritt
des Abrufs, immer; Entscheidung 16.11.2026 (4)).

Aufruf: python tools/feldabdeckung.py [--raw ORDNER] [--zustand PFAD] [--stadtteile PFAD] [--frist SEKUNDEN]
Zählt, wie vollständig die Felder der OParl-Rohdaten gefüllt sind (CLAUDE.md 7, Phase 1: underDirectionOf,
originator*, mainFile/auxiliaryFile, location, agendaItem.result, Listen der paperType und organizationType), schon
während des Vollabrufs auf dem bisher gelesenen Teil. Liest nur (Vorgaben aus pipeline/config.py):
- Vorlagen: `data/raw/papers.jsonl` und die Teildatei eines laufenden Vollabrufs `papers.teil.jsonl`
  (sessionnet._teil): Bricht ein Vollabruf ab, schreibt der Abruf dorthin alle bisher gelesenen Objekte (jede Kennung
  einmal) und setzt in der nächsten Nacht damit fort; ist er vollständig, ersetzt er die fertige Datei und löscht die
  Teildatei (sessionnet._abruf_liste);
- Sitzungen: `meetings_roh.jsonl` (vollständige Sitzungen mit Tagesordnungspunkten, wie der Abruf sie liest) und
  `meetings_roh.teil.jsonl`; fehlen beide, ersatzweise `meetings.json` (Kurzformat ohne Tagesordnungspunkte, etwa aus
  tools/testdaten.py). Der Abruf liest die Sitzungen nach den Vorlagen: Während des ersten Vollabrufs der Vorlagen gibt
  es sie noch nicht;
- Gremien: `organizations.jsonl` und `organizations.teil.jsonl`; fehlen beide, ersatzweise `organizations.json`;
- `zustand_abruf.json` nur für die Angabe, ob ein Vollabruf einer Liste läuft (`<liste>_fortsetzung`): Dann sind die
  Zahlen ein Zwischenstand;
- `data/geo/stadtteile_koeln.geojson` (offline im Repository) für die 86 Stadtteilnamen: `location.subLocality` wird
  mit pipeline.geo.Ortsteile.by_name abgeglichen, derselben Funktion wie Stufe A in build.
Je Kennung zählt ein Objekt einmal wie in build (build._je_kennung_einmal), über die fertige Datei und die Teildatei
hinweg: die zuletzt gelesene Fassung ohne Löschvermerk (die Teildatei nach der fertigen Datei, eine spätere Zeile nach
einer früheren); als gelöscht (`deleted`) zählt eine Kennung nur, wenn es sie nicht auch ohne Löschvermerk gibt.
Gelöschte Objekte stehen getrennt, Anteile beziehen sich auf die übrigen. Gelesen wird zeilenweise in zwei Durchgängen
(erst die Kennungen, dann die geltenden Fassungen), damit der Speicher nicht mit der Größe der Objekte wächst (je
Kennung ein Hashwert); unlesbare Zeilen, Zeilen ohne Kennung und überlange Zeilen (über 32 MiB) werden gezählt und
übersprungen. Nach der Frist (Vorgabe 7 Minuten; der Schritt hat 10) endet das Lesen mit dem Vermerk „unvollständig“.
Ausgabe nur auf stdout und, in GitHub Actions, als Markdown an `$GITHUB_STEP_SUMMARY`; das Skript schreibt nichts in
data/, veröffentlicht nichts und sendet keine Anfrage. Nur Anzahlen, Anteile und vorsichtig gefilterte Kategorien:
Werte von paperType, mimeType, result (Tagesordnungspunkt), organizationType und classification erscheinen nur, wenn
sie mindestens 5-mal vorkommen, nach Zusammenfassen des Leerraums höchstens 80 Zeichen haben und nur aus Buchstaben
(mit Umlauten und ß), Ziffern, Leerzeichen und . , ; : - / ( ) § & bestehen, mindestens einen Buchstaben enthalten und
keine Merkmale von Adressen, Dateinamen, Drucksachennummern oder Kennungen tragen („://“, „www.“, ein Punkt zwischen
Buchstaben oder Ziffern, Zahl/Jahr, fünf und mehr Ziffern in Folge); mimeType nur in der Form typ/untertyp mit
bekanntem Typ. Alles andere zählt als „sonstige (n Werte, m Objekte)“. Nie Kennungen, Titel, Namen,
Drucksachennummern (nur ihre Form als Klasse), Adressen, Dateinamen, Personenangaben (originatorPerson nur „Liste nicht
leer“, nie aufgelöst), Werte der Ortsangaben oder anderer Freitext. Fehlende oder unlesbare Dateien erscheinen als
„fehlt“ bzw. „unlesbar“; das Skript endet immer mit 0 (auch nach einem unerwarteten Fehler: Warnung mit dem Namen des
Fehlers, ohne Text), damit es den Lauf nie anhält.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import abruf, config, sessionnet  # noqa: E402

FRIST = 420                          # Sekunden für das Lesen insgesamt (der Schritt in pages.yml hat 10 Minuten)
ZEILE_HOECHSTENS = 32 * 1024 * 1024  # längere Zeilen gelten als unlesbar (Speicher)
MIN_ANZAHL = 5                       # Kategorien seltener als das erscheinen nicht einzeln
MAX_LAENGE = 80                      # Zeichen einer Kategorie nach Zusammenfassen des Leerraums
MAX_ANGEZEIGT = 25                   # Werte je Kategorienliste; weitere zählen unter „sonstige“
MAX_GEMERKT = 5000                   # gemerkte anzeigbare Werte je Feld (Speicher); weitere zählen unter „sonstige“
MAX_HASHES = 100_000                 # gemerkte Hashwerte nicht anzeigbarer Werte je Feld (nur für die Zahl der Werte)
KREUZ_ARTEN = 10                     # häufigste Vorlagenarten in der Kreuztabelle
LISTEN = {   # Liste: (fertige Datei, Ersatz als JSON-Liste, nur ohne fertige Datei und Teildatei gelesen)
    "papers": ("papers.jsonl", None),
    "meetings": ("meetings_roh.jsonl", "meetings.json"),
    "organizations": ("organizations.jsonl", "organizations.json"),
}
ERSATZ = {"meetings.json": "Ersatz im Kurzformat ohne Tagesordnungspunkte",
          "organizations.json": "Ersatz ohne gelöschte Gremien"}
NAME = {"papers": "Vorlagen", "meetings": "Sitzungen", "organizations": "Gremien"}

BUCHSTABE = re.compile(r"[A-Za-zÄÖÜäöüß]")
ZEICHEN = re.compile(r"[A-Za-zÄÖÜäöüß0-9 .,;:\-/()§&]+")
VERDAECHTIG = re.compile(r"://|www\.|[A-Za-z0-9]\.[A-Za-z0-9]{2,}|\d+/\d{2,4}(?!\d)|\d{5,}", re.I)
MIME = re.compile(r"(?:application|audio|font|image|message|model|multipart|text|video)/[a-z0-9][a-z0-9.+\-]*")
# Drucksachennummern nur als Klasse (CLAUDE.md 3.1; geocode.REFERENZ_PUNKT lässt 1–4 Ziffern zu)
REFERENZEN = (("AN/NNNN/JJJJ", re.compile(r"AN/\d{4}/\d{4}")), ("NNNN/JJJJ", re.compile(r"\d{4}/\d{4}")),
              ("AN/N/JJJJ oder N/JJJJ mit 1 bis 3 Ziffern", re.compile(r"(?:AN/)?\d{1,3}/\d{4}")))
JAHR = re.compile(r"(\d{4})-\d{2}-\d{2}")
# Felder einer Ortsangabe nach OParl 1.1 (Location), ohne Verweise und Verwaltungsfelder
ORT_FELDER = ("subLocality", "locality", "streetAddress", "postalCode", "room", "description", "geojson")
FORM_FELDER = ("underDirectionOf", "originatorOrganization", "originatorPerson", "mainFile", "auxiliaryFile",
               "location", "consultation", "keyword", "relatedPaper", "superordinatedPaper", "subordinatedPaper")
KREUZ = ("underDirectionOf", "originatorOrganization", "location", "mainFile", "auxiliaryFile")


class Zeitgrenze(Exception):
    pass


# --- Lesen ---------------------------------------------------------------------------------------------------------

def _zeilen(f):
    """Zeilen einer Binärdatei; eine überlange Zeile als None (bis zum nächsten Zeilenumbruch übersprungen)."""
    while True:
        z = f.readline(ZEILE_HOECHSTENS)
        if not z:
            return
        if len(z) == ZEILE_HOECHSTENS and not z.endswith(b"\n"):
            while True:
                rest = f.readline(ZEILE_HOECHSTENS)
                if not rest or rest.endswith(b"\n"):
                    break
            yield None
        else:
            yield z


def _elemente(pfad, art):
    """Rohwerte einer Datei: je Zeile (jsonl) Bytes, je Element einer JSON-Liste (json) der Wert; None für eine
    überlange Zeile. Fehler beim Öffnen und Lesen gehen nach oben."""
    if art == "json":
        werte = json.loads(Path(pfad).read_bytes())
        if not isinstance(werte, list):
            raise ValueError("keine Liste")
        for w in werte:
            yield "wert", w
        return
    with open(pfad, "rb") as f:
        for z in _zeilen(f):
            if z is None or z.strip():
                yield "zeile", z


def _objekte(quellen, frist, dateien, nur=None):
    """(Position, Objekt) über alle Quellen in ihrer Reihenfolge; die Position zählt jede nicht leere Zeile bzw. jedes
    Element (in beiden Durchgängen gleich). `dateien` (Name → Counter) zählt Zeilen, unlesbare und solche ohne Kennung;
    mit `nur` (Menge von Positionen) werden nur diese Zeilen gelesen."""
    pos = -1
    for pfad, art in quellen:
        s = dateien.setdefault(pfad.name, collections.Counter())
        try:
            for i, (typ, roh) in enumerate(_elemente(pfad, art)):
                if i % 256 == 0 and time.monotonic() > frist:
                    raise Zeitgrenze
                pos += 1
                s["zeilen"] += 1
                if nur is not None and pos not in nur:
                    continue
                if roh is None:
                    s["unlesbar"] += 1
                    continue
                if typ == "zeile":
                    try:
                        roh = json.loads(roh)
                    except (ValueError, RecursionError):
                        s["unlesbar"] += 1
                        continue
                if not isinstance(roh, dict) or not isinstance(roh.get("id"), str) or not roh["id"]:
                    s["ohne_kennung"] += 1
                    continue
                yield pos, roh
        except (OSError, ValueError, RecursionError) as e:   # Datei nicht (weiter) lesbar: übrige Quellen weiter
            s["fehler"] = 1
            dateien.setdefault("_fehlerart", {})[pfad.name] = type(e).__name__


def _kennung(text):
    return hashlib.blake2b(text.encode("utf-8", "surrogatepass"), digest_size=16).digest()


def geltende(quellen, frist, dateien):
    """Positionen der geltenden Fassungen, je Kennung einmal wie build._je_kennung_einmal (die zuletzt gelesene
    Fassung ohne Löschvermerk; eine Löschung nur ohne solche), und die Zahl der ersetzten Fassungen."""
    lebend, geloescht, fassungen = {}, {}, 0
    for pos, o in _objekte(quellen, frist, dateien):
        fassungen += 1
        (geloescht if o.get("deleted") else lebend)[_kennung(o["id"])] = pos
    gilt = set(lebend.values()) | {p for k, p in geloescht.items() if k not in lebend}
    return gilt, fassungen - len(gilt)


def json_lesen(pfad):
    """(Objekt, Zustand der Datei): „fehlt“, „unlesbar“ oder „gelesen“ (wie tools/abrufstand.py)."""
    try:
        wert = json.loads(Path(pfad).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "fehlt"
    except (OSError, ValueError, RecursionError):
        return {}, "unlesbar"
    return (wert, "gelesen") if isinstance(wert, dict) else ({}, "unlesbar")


# --- Werte ---------------------------------------------------------------------------------------------------------

def eintraege(wert):
    """Einträge eines listenwertigen Felds; ein einzelner Wert als Liste mit ihm (wie build._als_liste)."""
    if wert is None:
        return []
    return wert if isinstance(wert, list) else [wert]


def brauchbar(x):
    """Verweis oder eingebettetes Objekt: nicht leere Zeichenkette oder nicht leeres Objekt."""
    return bool(x.strip()) if isinstance(x, str) else isinstance(x, dict) and bool(x)


def nicht_leer(wert):
    return any(brauchbar(x) for x in eintraege(wert))


def vorhanden(wert):
    """Feld einer Ortsangabe gefüllt: Text nicht leer, Objekt oder Liste nicht leer, Zahl."""
    if isinstance(wert, str):
        return bool(wert.strip())
    if isinstance(wert, (dict, list)):
        return bool(wert)
    return isinstance(wert, (int, float)) and not isinstance(wert, bool)


def form(objekt, feld):
    """Form eines Felds (nur der Typ, kein Inhalt)."""
    if feld not in objekt:
        return "fehlt"
    w = objekt[feld]
    if w is None:
        return "null"
    if isinstance(w, list):
        if not w:
            return "leere Liste"
        arten = {"o" if isinstance(x, dict) else "z" if isinstance(x, str) else "a" for x in w}
        return {frozenset("o"): "Liste von Objekten", frozenset("z"): "Liste von Zeichenketten"}.get(
            frozenset(arten), "Liste, gemischt oder andere")
    if isinstance(w, dict):
        return "einzelnes Objekt" if w else "leeres Objekt"
    if isinstance(w, str):
        return "einzelne Zeichenkette" if w.strip() else "leere Zeichenkette"
    return "andere Form"


def jahr(wert):
    """Jahr aus einem Datum oder Zeitpunkt (JJJJ-MM-TT…): Zahl, sonst „fehlt“, „unlesbar“ oder „außerhalb“."""
    if wert is None or (isinstance(wert, str) and not wert.strip()):
        return "fehlt"
    m = JAHR.match(wert.strip()) if isinstance(wert, str) else None
    if not m:
        return "unlesbar"
    j = int(m.group(1))
    return j if 1900 <= j <= 2100 else "außerhalb 1900–2100"


def referenzklasse(wert):
    if wert is None or (isinstance(wert, str) and not wert.strip()):
        return "fehlt oder leer"
    if not isinstance(wert, str):
        return "keine Zeichenkette"
    t = wert.strip()
    return next((name for name, muster in REFERENZEN if muster.fullmatch(t)), "andere Form")


def normal(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def zeigbar(text, mime=False):
    """Darf ein (normalisierter) Wert einer Kategorie erscheinen? Nur kurze Werte aus einer vorsichtigen
    Zeichenklasse ohne Merkmale von Adressen, Dateinamen, Drucksachennummern oder Kennungen."""
    if len(text) > MAX_LAENGE:
        return False
    if mime:
        return bool(MIME.fullmatch(text))
    return bool(ZEICHEN.fullmatch(text) and BUCHSTABE.search(text) and not VERDAECHTIG.search(text))


class Kategorien:
    """Häufigkeiten der Werte eines Felds. Gemerkt werden nur Werte, die erscheinen dürften (zeigbar); von den übrigen
    nur ein Hashwert für die Zahl der Werte. Werte unter MIN_ANZAHL und über MAX_ANGEZEIGT zählen unter „sonstige“."""

    def __init__(self, mime=False):
        self.mime = mime
        self.zaehler = collections.Counter()
        self.andere, self.andere_objekte, self.andere_mehr = set(), 0, False
        self.fehlt = self.keine_zeichenkette = 0

    def add(self, wert):
        if wert is None or (isinstance(wert, str) and not wert.strip()):
            self.fehlt += 1
            return
        if not isinstance(wert, str):
            self.keine_zeichenkette += 1
            return
        t = normal(wert)
        if zeigbar(t, self.mime) and (t in self.zaehler or len(self.zaehler) < MAX_GEMERKT):
            self.zaehler[t] += 1
            return
        self.andere_objekte += 1
        if len(self.andere) < MAX_HASHES:
            self.andere.add(_kennung(t))
        else:
            self.andere_mehr = True

    def schluessel(self, wert):
        """Wert, unter dem er in einer Kreuztabelle stehen darf (zeigbar, gemerkt), sonst None."""
        if not isinstance(wert, str):
            return None
        t = normal(wert)
        return t if t in self.zaehler else None

    def ergebnis(self):
        """(angezeigte Werte als [(Wert, Anzahl)], Zahl der übrigen Werte als Text, Objekte der übrigen)."""
        haeufig = sorted(((t, n) for t, n in self.zaehler.items() if n >= MIN_ANZAHL), key=lambda x: (-x[1], x[0]))
        zeigen = haeufig[:MAX_ANGEZEIGT]
        gezeigt = {t for t, _ in zeigen}
        werte = len(self.andere) + sum(1 for t in self.zaehler if t not in gezeigt)
        objekte = self.andere_objekte + sum(n for t, n in self.zaehler.items() if t not in gezeigt)
        return zeigen, ("mindestens " if self.andere_mehr else "") + tausend(werte), objekte

    def gesamt(self):
        return sum(self.zaehler.values()) + self.andere_objekte + self.fehlt + self.keine_zeichenkette


# --- Auswertung je Liste -------------------------------------------------------------------------------------------

class Vorlagen:
    def __init__(self, stadtteil):
        self.stadtteil = stadtteil
        self.n = self.geloescht = 0
        self.jahre = collections.Counter()
        self.art = Kategorien()
        self.referenz = collections.Counter()
        self.feld = collections.Counter()
        self.formen = {f: collections.Counter() for f in FORM_FELDER}
        self.anlagen = collections.Counter()
        self.dateien = collections.Counter()
        self.mime_haupt, self.mime_anlage = Kategorien(mime=True), Kategorien(mime=True)
        self.ort = collections.Counter()
        self.beratung = collections.Counter()
        self.kreuz = {}

    def add(self, p):
        if p.get("deleted"):
            self.geloescht += 1
            return
        self.jahre[jahr(p.get("date"))] += 1
        self.art.add(p.get("paperType"))
        self.referenz[referenzklasse(p.get("reference"))] += 1
        for f in FORM_FELDER:
            self.formen[f][form(p, f)] += 1
        hat = {f: nicht_leer(p.get(f)) for f in FORM_FELDER}
        for f, ja in hat.items():
            self.feld[f] += ja
        self.feld["nur_anlage"] += hat["auxiliaryFile"] and not hat["mainFile"]
        self.feld["ohne_datei"] += not hat["auxiliaryFile"] and not hat["mainFile"]
        anlagen = sum(1 for x in eintraege(p.get("auxiliaryFile")) if brauchbar(x))
        self.anlagen["0" if not anlagen else "1" if anlagen == 1 else "2–5" if anlagen <= 5 else "mehr als 5"] += 1
        for feld, mime, art in (("mainFile", self.mime_haupt, "haupt"), ("auxiliaryFile", self.mime_anlage, "anlage")):
            for x in eintraege(p.get(feld)):
                if isinstance(x, dict) and x:
                    self.dateien[f"{art}_objekt"] += 1
                    mime.add(x.get("mimeType"))
                elif isinstance(x, str) and x.strip():
                    self.dateien[f"{art}_adresse"] += 1
        stadtteil = False
        for x in eintraege(p.get("location")):
            if isinstance(x, dict) and x:
                self.ort["objekt"] += 1
                for f in ORT_FELDER:
                    self.ort[f] += vorhanden(x.get(f))
                g = x.get("geojson")
                if isinstance(g, dict) and isinstance(g.get("geometry"), dict) and g["geometry"].get("type") == "Point":
                    self.ort["punkt"] += 1
                s = x.get("subLocality")
                if isinstance(s, str) and s.strip() and self.stadtteil(s):
                    self.ort["stadtteil"] += 1
                    stadtteil = True
            elif isinstance(x, str) and x.strip():
                self.ort["adresse"] += 1
            else:
                self.ort["andere"] += 1
        self.feld["stadtteil"] += stadtteil
        mit = collections.Counter()
        for c in eintraege(p.get("consultation")):
            if isinstance(c, dict) and c:
                self.beratung["objekt"] += 1
                for f in ("meeting", "agendaItem", "organization"):
                    ja = nicht_leer(c.get(f))
                    self.beratung[f] += ja
                    mit[f] += ja
            elif isinstance(c, str) and c.strip():
                self.beratung["adresse"] += 1
            else:
                self.beratung["andere"] += 1
        self.feld["beratung_meeting"] += mit["meeting"] > 0
        self.feld["beratung_agendaItem"] += mit["agendaItem"] > 0
        k = self.art.schluessel(p.get("paperType"))
        zeile = self.kreuz.setdefault(k, [0] * (len(KREUZ) + 1))
        zeile[0] += 1
        for i, f in enumerate(KREUZ, 1):
            zeile[i] += hat[f]
        self.n += 1   # zuletzt: ein Objekt, das mittendrin scheitert (liste_lesen), zählt nicht mit


class Sitzungen:
    def __init__(self):
        self.n = self.geloescht = 0
        self.kurzformat = 0
        self.jahre = collections.Counter()
        self.feld = collections.Counter()
        self.top_form = collections.Counter()
        self.top_anzahl = collections.Counter()
        self.top = collections.Counter()
        self.ergebnis = Kategorien()

    def add(self, m):
        if m.get("deleted"):
            self.geloescht += 1
            return
        self.jahre[jahr(m.get("start"))] += 1
        self.feld["abgesagt"] += m.get("cancelled") is True
        self.feld["organisation"] += nicht_leer(m.get("organization"))
        if "agendaItem" not in m and isinstance(m.get("agenda_items"), int) and not isinstance(m["agenda_items"], bool):
            self.kurzformat += 1   # meetings.json: nur die Zahl der Tagesordnungspunkte
            anzahl = max(m["agenda_items"], 0)
        else:
            self.top_form[form(m, "agendaItem")] += 1
            anzahl = 0
            for t in eintraege(m.get("agendaItem")):
                if isinstance(t, dict) and t:
                    anzahl += 1
                    self.top["objekt"] += 1
                    oeffentlich = t.get("public")
                    self.top["oeffentlich" if oeffentlich is True else "nicht_oeffentlich" if oeffentlich is False
                             else "oeffentlich_fehlt"] += 1
                    self.top["ergebnis"] += vorhanden(t.get("result"))
                    self.ergebnis.add(t.get("result"))
                    self.top["consultation"] += nicht_leer(t.get("consultation"))
                    self.top["paper"] += nicht_leer(t.get("paper"))
                elif isinstance(t, str) and t.strip():
                    anzahl += 1
                    self.top["adresse"] += 1
                else:
                    self.top["andere"] += 1
        self.top["insgesamt"] += anzahl
        self.feld["mit_top"] += anzahl > 0
        self.top_anzahl["0" if not anzahl else "1–5" if anzahl <= 5 else "6–20" if anzahl <= 20 else "21–50"
                        if anzahl <= 50 else "mehr als 50"] += 1
        self.n += 1


class Gremien:
    def __init__(self):
        self.n = self.geloescht = 0
        self.typ, self.klasse = Kategorien(), Kategorien()

    def add(self, o):
        if o.get("deleted"):
            self.geloescht += 1
            return
        self.typ.add(o.get("organizationType"))
        self.klasse.add(o.get("classification"))
        self.n += 1


def stadtteil_abgleich(pfad):
    """Funktion Name → bool (ein Kölner Stadtteil laut pipeline.geo.Ortsteile.by_name, wie Stufe A in build) und
    Zustand; ohne lesbare Stadtteile (None, Zustand)."""
    try:
        from pipeline import geo
        ortsteile = geo.Ortsteile(Path(pfad))
        anzahl = len(ortsteile.props)
    except Exception as e:   # etwa Datei fehlt, unlesbar oder shapely fehlt
        return None, f"nicht lesbar ({type(e).__name__})"
    gemerkt = {}

    def ist_stadtteil(name):
        if name not in gemerkt:
            if len(gemerkt) >= MAX_GEMERKT:
                return ortsteile.by_name(name) is not None
            gemerkt[name] = ortsteile.by_name(name) is not None
        return gemerkt[name]

    return ist_stadtteil, f"{anzahl} Stadtteile"


def liste_lesen(name, raw, zustand, z_datei, frist, auswertung):
    """Eine Liste lesen und auswerten: dict mit Dateien, Stand (Zwischenstand oder nicht), Fassungen, Vermerken."""
    datei, ersatz = LISTEN[name]
    fertig = raw / datei
    teil = sessionnet._teil(fertig)
    quellen = [(p, "jsonl") for p in (fertig, teil) if p.exists()]
    r = {"name": name, "dateien": {}, "ersatz": None, "ersetzt": 0, "unvollstaendig": False, "auswertung": auswertung,
         "nicht_auswertbar": collections.Counter()}
    if not quellen and ersatz and (raw / ersatz).exists():
        quellen = [(raw / ersatz, "json")]
        r["ersatz"] = ersatz
    r["ohne_dateien"] = not quellen
    fort = zustand.get(f"{name}_fortsetzung")
    if z_datei != "gelesen":
        r["stand"] = f"unbekannt (zustand_abruf.json {z_datei})"
    elif fort is not None:
        r["stand"] = "Zwischenstand: Vollabruf läuft (Fortsetzung steht aus); gezählt " + (
            "die im laufenden Vollabruf bisher gelesenen Objekte und der Stand davor, je Kennung einmal"
            if teil.exists() and fertig.exists() else "die im laufenden Vollabruf bisher gelesenen Objekte"
            if teil.exists() else f"nur der Stand davor ({teil.name} fehlt)")
    elif sessionnet._zeit(zustand.get(name)) is not None:
        t = sessionnet._zeit(zustand.get(name))
        try:
            wann = t.astimezone(abruf.ORTSZEIT).strftime("%d.%m.%Y, %H:%M Uhr")
        except (OverflowError, ValueError, OSError):
            wann = "Zeitpunkt unlesbar"
        r["stand"] = f"kein laufender Vollabruf (Liste zuletzt vollständig aktualisiert im Lauf ab {wann})"
    elif name in zustand:
        r["stand"] = "kein laufender Vollabruf (Zeitpunkt des letzten Abrufs unlesbar)"
    else:
        r["stand"] = "noch kein vollständiger Abruf"
    if teil.exists() and fort is None and z_datei == "gelesen":
        r["stand"] += (f"; {teil.name} ohne Fortsetzung im Zustand (veraltet, der Abruf liest sie nicht mehr; "
                       "mitgezählt)")
    dateien = {}
    try:
        gilt, r["ersetzt"] = geltende(quellen, frist, dateien)
        for _, o in _objekte(quellen, frist, {}, nur=gilt):
            try:
                auswertung.add(o)
            except Exception as e:   # unerwartete Form tief im Objekt: zählen, die übrigen weiter auswerten (das
                # Objekt zählt nicht in n; Felder davor sind womöglich schon gezählt)
                r["nicht_auswertbar"][type(e).__name__] += 1
    except Zeitgrenze:
        r["unvollstaendig"] = True
    fehlerart = dateien.pop("_fehlerart", {})
    for p in (fertig, teil) + ((raw / ersatz,) if ersatz else ()):
        s = dateien.get(p.name)
        if s is None:
            if p.name == ersatz and r["ersatz"] is None:
                continue
            r["dateien"][p.name] = "fehlt" if not p.exists() else "nicht gelesen (Zeitgrenze)"
            continue
        text = f"{tausend(s['zeilen'])} {'Einträge' if p.name == r['ersatz'] else 'Zeilen'}"
        if s["unlesbar"] or s["ohne_kennung"]:
            text += f", davon {tausend(s['unlesbar'])} unlesbar und {tausend(s['ohne_kennung'])} ohne Kennung"
        art = f" ({ERSATZ[p.name]})" if p.name == r["ersatz"] else ""
        vor = "bis zur Zeitgrenze " if r["unvollstaendig"] else ""
        r["dateien"][p.name] = (f"nicht weiter lesbar{art} ({fehlerart.get(p.name, 'Fehler')}), bis dahin {text}"
                                if s["fehler"] else f"{vor}gelesen{art}: {text}")
    return r


def auswerten(raw, zustand_pfad, stadtteile_pfad, frist_sekunden=FRIST):
    """Alles für die Ausgabe (nur Zahlen, Zustände und gefilterte Kategorien)."""
    beginn = time.monotonic()
    frist = beginn + frist_sekunden
    raw = Path(raw)
    zustand, z_datei = json_lesen(zustand_pfad)
    ist_stadtteil, st_datei = stadtteil_abgleich(stadtteile_pfad)
    a = {"zustand": z_datei, "stadtteile": st_datei, "listen": {}}
    for name, auswertung in (("papers", Vorlagen(ist_stadtteil or (lambda _: False))), ("meetings", Sitzungen()),
                             ("organizations", Gremien())):
        a["listen"][name] = liste_lesen(name, raw, zustand, z_datei, frist, auswertung)
    a["abgleich"] = ist_stadtteil is not None
    a["dauer"] = time.monotonic() - beginn
    return a


# --- Ausgabe -------------------------------------------------------------------------------------------------------

def tausend(n):
    return f"{n:,}".replace(",", ".")


def anteil(n, basis):
    return f"{100 * n / basis:.1f} %".replace(".", ",") if basis else "–"


def _zahl_anteil(n, basis):
    return [tausend(n), anteil(n, basis)]


def _kategorien_tabelle(titel, kat, spalte):
    zeigen, werte, objekte = kat.ergebnis()
    basis = kat.gesamt()
    zeilen = [[f"„{t}“", *_zahl_anteil(n, basis)] for t, n in zeigen]
    if objekte:
        zeilen.append([f"sonstige ({werte} Werte, {tausend(objekte)} Objekte)", *_zahl_anteil(objekte, basis)])
    if kat.keine_zeichenkette:
        zeilen.append(["keine Zeichenkette", *_zahl_anteil(kat.keine_zeichenkette, basis)])
    if kat.fehlt:
        zeilen.append(["fehlt oder leer", *_zahl_anteil(kat.fehlt, basis)])
    return ("t", titel, [spalte, "Anzahl", "Anteil"], zeilen)


def _jahre_tabelle(titel, jahre, basis):
    zahlen = sorted(k for k in jahre if isinstance(k, int))
    andere = [k for k in ("außerhalb 1900–2100", "unlesbar", "fehlt") if jahre.get(k)]
    return ("t", titel, ["Jahr", "Anzahl", "Anteil"],
            [[str(k), *_zahl_anteil(jahre[k], basis)] for k in zahlen + andere])


def _formen(r, felder):
    return [[f"`{f}`", ", ".join(f"{k} {tausend(n)}" for k, n in sorted(r[f].items(), key=lambda x: (-x[1], x[0])))]
            for f in felder]


def bloecke(a):
    """Ausgabe als Folge von Blöcken: („h“, Titel), („p“, Text), („t“, Titel, Kopf, Zeilen)."""
    b = [("p", "Nur Anzahlen, Anteile und häufige Kategorien aus den Rohdaten (data/raw); keine Titel, Namen, "
               "Kennungen, Drucksachennummern, Adressen, Dateinamen, Personenangaben oder Werte der Ortsangaben. "
               "Nichts davon wird veröffentlicht."),
         ("p", f"Stadtteile für den Abgleich mit subLocality (data/geo): {a['stadtteile']}")]
    for name in ("papers", "meetings", "organizations"):
        r = a["listen"][name]
        b.append(("h", f"{NAME[name]} (`{name}`)"))
        b.append(("p", "Dateien: " + "; ".join(f"{k} {v}" for k, v in r["dateien"].items())))
        b.append(("p", f"Stand: {r['stand']}"))
        if r["unvollstaendig"]:
            b.append(("p", "Unvollständig: Zeitgrenze des Schritts erreicht, die Zahlen umfassen nur das bis dahin "
                           "Gelesene"))
        if r["ohne_dateien"] and name == "meetings":
            b.append(("p", "Hinweis: Der Abruf liest die Sitzungen nach den Vorlagen; während des ersten Vollabrufs der "
                           "Vorlagen gibt es sie noch nicht"))
        if r["ersetzt"]:
            b.append(("p", f"Fassungen derselben Kennung (je Kennung einmal gezählt): {tausend(r['ersetzt'])} ersetzt"))
        if r["nicht_auswertbar"]:
            b.append(("p", "Nicht auswertbar (unerwartete Form, nicht mitgezählt): " + ", ".join(
                f"{tausend(n)} ({k})" for k, n in sorted(r["nicht_auswertbar"].items()))))
        w = r["auswertung"]
        b.append(("p", f"{NAME[name]} je Kennung: {tausend(w.n)}; als gelöscht gemeldet (deleted, getrennt): "
                       f"{tausend(w.geloescht)}"))
        if not w.n:
            continue
        b += {"papers": _vorlagen, "meetings": _sitzungen, "organizations": _gremien}[name](w, a)
    b.append(("p", f"Dauer der Auswertung: {a['dauer']:.0f} s"))
    return b


def _vorlagen(w, a):
    n = w.n
    out = [_jahre_tabelle("Vorlagen nach Jahr (date)", w.jahre, n),
           _kategorien_tabelle("Vorlagenarten (paperType)", w.art, "paperType"),
           ("t", "Form der Drucksachennummer (reference, nur Klasse)", ["Klasse", "Anzahl", "Anteil"],
            [[k, *_zahl_anteil(w.referenz[k], n)] for k in
             [x for x, _ in REFERENZEN] + ["andere Form", "keine Zeichenkette", "fehlt oder leer"] if w.referenz[k]])]
    stadtteil = ("location mit subLocality = Stadtteil (geo.Ortsteile.by_name)" if a["abgleich"]
                 else f"location mit subLocality = Stadtteil: nicht ermittelt (Stadtteile {a['stadtteile']})")
    zeilen = [("underDirectionOf", "underDirectionOf"), ("originatorOrganization", "originatorOrganization"),
              ("originatorPerson", "originatorPerson (nur: Liste nicht leer)"), ("mainFile", "mainFile"),
              ("auxiliaryFile", "auxiliaryFile"), ("nur_anlage", "ohne mainFile, mit auxiliaryFile"),
              ("ohne_datei", "weder mainFile noch auxiliaryFile"), ("location", "location"),
              ("stadtteil", stadtteil), ("consultation", "consultation"),
              ("beratung_meeting", "consultation mit Verweis auf meeting (mindestens eine)"),
              ("beratung_agendaItem", "consultation mit Verweis auf agendaItem (mindestens eine)"),
              ("keyword", "keyword"), ("relatedPaper", "relatedPaper"),
              ("superordinatedPaper", "superordinatedPaper"), ("subordinatedPaper", "subordinatedPaper")]
    out.append(("t", "Feldabdeckung (Feld nicht leer; Anteil an den Vorlagen ohne gelöschte)",
                ["Feld", "Anzahl", "Anteil"],
                [[text, *_zahl_anteil(w.feld[k], n)] for k, text in zeilen
                 if k != "stadtteil" or a["abgleich"]]))
    if not a["abgleich"]:
        out.append(("p", stadtteil))
    out.append(("t", "Zahl der Anlagen je Vorlage (auxiliaryFile)", ["Anlagen", "Vorlagen", "Anteil"],
                [[k, *_zahl_anteil(w.anlagen[k], n)] for k in ("0", "1", "2–5", "mehr als 5")]))
    d = w.dateien
    out.append(("p", f"Dateien: mainFile eingebettet {tausend(d['haupt_objekt'])}, nur als Adresse "
                     f"{tausend(d['haupt_adresse'])}; auxiliaryFile eingebettet {tausend(d['anlage_objekt'])}, nur als "
                     f"Adresse {tausend(d['anlage_adresse'])} (mimeType nur bei eingebetteten Dateien)"))
    if w.mime_haupt.gesamt():
        out.append(_kategorien_tabelle("mimeType der Hauptdateien (mainFile, eingebettet)", w.mime_haupt, "mimeType"))
    if w.mime_anlage.gesamt():
        out.append(_kategorien_tabelle("mimeType der Anlagen (auxiliaryFile, eingebettet)", w.mime_anlage,
                                       "mimeType"))
    o = w.ort
    ortsangaben = o["objekt"] + o["adresse"] + o["andere"]
    if ortsangaben:
        out.append(("p", f"Ortsangaben (location-Einträge): {tausend(ortsangaben)}; eingebettet {tausend(o['objekt'])}, "
                         f"nur als Adresse (Verweis, Felder nicht eingebettet) {tausend(o['adresse'])}, andere Form "
                         f"{tausend(o['andere'])}"))
        felder = [[f"`{f}`", *_zahl_anteil(o[f], o["objekt"])] for f in ORT_FELDER]
        felder.append(["`geojson` mit Punktgeometrie (geometry.type Point, wie build liest)",
                       *_zahl_anteil(o["punkt"], o["objekt"])])
        if a["abgleich"]:
            felder.append(["`subLocality` = Stadtteil", *_zahl_anteil(o["stadtteil"], o["objekt"])])
        out.append(("t", "Felder der eingebetteten Ortsangaben (OParl 1.1 Location; Anteil an den eingebetteten)",
                    ["Feld", "Anzahl", "Anteil"], felder))
    br = w.beratung
    beratungen = br["objekt"] + br["adresse"] + br["andere"]
    if beratungen:
        out.append(("p", f"Beratungen (consultation-Einträge): {tausend(beratungen)}; eingebettet "
                         f"{tausend(br['objekt'])} (davon mit meeting {tausend(br['meeting'])}, mit agendaItem "
                         f"{tausend(br['agendaItem'])}, mit organization {tausend(br['organization'])}), nur als "
                         f"Adresse {tausend(br['adresse'])}, andere Form {tausend(br['andere'])}"))
    out.append(("t", "Form der Felder (nur Typ)", ["Feld", "Form (Anzahl)"], _formen(w.formen, FORM_FELDER)))
    arten = [k for k, _ in w.art.ergebnis()[0][:KREUZ_ARTEN]]
    zeilen = []
    rest = [0] * (len(KREUZ) + 1)
    for k, z in w.kreuz.items():
        if k not in arten:
            rest = [x + y for x, y in zip(rest, z)]
    for k, z in [(f"„{k}“", w.kreuz[k]) for k in arten] + [("übrige Vorlagenarten", rest)]:
        if z[0]:
            zeilen.append([k, tausend(z[0])] + [anteil(x, z[0]) for x in z[1:]])
    gesamt = [sum(z[i] for z in w.kreuz.values()) for i in range(len(KREUZ) + 1)]
    zeilen.append(["alle", tausend(gesamt[0])] + [anteil(x, gesamt[0]) for x in gesamt[1:]])
    out.append(("t", f"Kreuztabelle: Abdeckung nach Vorlagenart (häufigste {KREUZ_ARTEN}; Anteil je Zeile)",
                ["paperType", "Vorlagen", *KREUZ], zeilen))
    return out


def _sitzungen(w, a):
    n = w.n
    out = [_jahre_tabelle("Sitzungen nach Jahr (start)", w.jahre, n),
           ("t", "Felder der Sitzungen (Anteil an den Sitzungen ohne gelöschte)", ["Feld", "Anzahl", "Anteil"],
            [["abgesagt (cancelled true)", *_zahl_anteil(w.feld["abgesagt"], n)],
             ["Verweis auf Gremium (organization nicht leer)", *_zahl_anteil(w.feld["organisation"], n)],
             ["mit Tagesordnungspunkten (agendaItem nicht leer)", *_zahl_anteil(w.feld["mit_top"], n)]]),
           ("t", "Tagesordnungspunkte je Sitzung", ["Tagesordnungspunkte", "Sitzungen", "Anteil"],
            [[k, *_zahl_anteil(w.top_anzahl[k], n)] for k in ("0", "1–5", "6–20", "21–50", "mehr als 50")])]
    if w.kurzformat:
        out.append(("p", f"Kurzformat (meetings.json): {tausend(w.kurzformat)} Sitzungen nur mit der Zahl der "
                         "Tagesordnungspunkte; deren Felder (public, result, consultation) stehen nur in "
                         "meetings_roh.jsonl"))
    if w.top_form:
        out.append(("t", "Form der Felder (nur Typ)", ["Feld", "Form (Anzahl)"], _formen({"agendaItem": w.top_form},
                                                                                       ["agendaItem"])))
    t = w.top
    if t["objekt"] or t["adresse"] or t["andere"]:
        out.append(("p", f"Tagesordnungspunkte (agendaItem-Einträge): {tausend(t['insgesamt'])}; eingebettet "
                         f"{tausend(t['objekt'])}, nur als Adresse {tausend(t['adresse'])}, andere Form "
                         f"{tausend(t['andere'])}"))
    if t["objekt"]:
        out.append(("t", "Felder der eingebetteten Tagesordnungspunkte (Anteil an den eingebetteten)",
                    ["Feld", "Anzahl", "Anteil"],
                    [["nicht öffentlich (public false)", *_zahl_anteil(t["nicht_oeffentlich"], t["objekt"])],
                     ["öffentlich (public true)", *_zahl_anteil(t["oeffentlich"], t["objekt"])],
                     ["public fehlt oder andere Form", *_zahl_anteil(t["oeffentlich_fehlt"], t["objekt"])],
                     ["result vorhanden", *_zahl_anteil(t["ergebnis"], t["objekt"])],
                     ["Verweis auf Beratung (consultation nicht leer)", *_zahl_anteil(t["consultation"], t["objekt"])],
                     ["Verweis auf Vorlage (paper nicht leer; kein Feld von OParl 1.1)",
                      *_zahl_anteil(t["paper"], t["objekt"])]]))
        out.append(_kategorien_tabelle("Ergebnisse der Tagesordnungspunkte (result)", w.ergebnis, "result"))
    return out


def _gremien(w, a):
    return [_kategorien_tabelle("Arten (organizationType)", w.typ, "organizationType"),
            _kategorien_tabelle("Klassen (classification)", w.klasse, "classification")]


def text(b):
    """Ausgabe für das Log (Klartext)."""
    out = ["Feldabdeckung der Rohdaten (nur Zahlen und häufige Kategorien, keine Inhalte)"]
    for blk in b:
        if blk[0] == "h":
            out.append(f"== {blk[1].replace('`', '')} ==")
        elif blk[0] == "p":
            out.append(blk[1].replace("`", ""))
        else:
            _, titel, kopf, zeilen = blk
            out.append(f"{titel}:")
            for z in zeilen:
                z = [x.replace("`", "") for x in z]
                if kopf[1:] in (["Anzahl", "Anteil"], ["Vorlagen", "Anteil"], ["Sitzungen", "Anteil"]):
                    out.append(f"  {z[0]}: {z[1]} ({z[2]})")
                elif len(kopf) == 2:
                    out.append(f"  {z[0]}: {z[1]}")
                else:
                    out.append(f"  {z[0]}: " + "; ".join(f"{k} {v}" for k, v in zip(kopf[1:], z[1:])))
    return out


def markdown(b):
    """Ausgabe für $GITHUB_STEP_SUMMARY."""
    out = ["### Feldabdeckung der Rohdaten", ""]
    for blk in b:
        if blk[0] == "h":
            out += ["", f"#### {blk[1]}", ""]
        elif blk[0] == "p":
            out.append(f"- {blk[1]}")
        else:
            _, titel, kopf, zeilen = blk
            out += ["", f"**{titel}**", "", "| " + " | ".join(kopf) + " |",
                    "|" + "|".join(["---"] + ["---:" if len(kopf) > 2 else "---"] * (len(kopf) - 1)) + "|"]
            out += ["| " + " | ".join(z) + " |" for z in zeilen]
            out.append("")
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="Feldabdeckung der Rohdaten (nur Zahlen und häufige Kategorien)")
    p.add_argument("--raw", help="Ordner der Rohdaten (Vorgabe aus pipeline/config.py)")
    p.add_argument("--zustand", help="zustand_abruf.json (Vorgabe: im Ordner der Rohdaten)")
    p.add_argument("--stadtteile", help="Stadtteile als GeoJSON (Vorgabe aus pipeline/config.py)")
    p.add_argument("--frist", type=float, default=FRIST, help="Sekunden für das Lesen insgesamt")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:   # --help (0) oder unbekannte Angaben: Hinweis von argparse, der Lauf geht weiter
        if e.code:
            print("::warning::Feldabdeckung: Aufruf unlesbar, nichts ausgegeben", flush=True)
        return 0
    try:
        raw = Path(args.raw) if args.raw else config.RAW
        a = auswerten(raw, args.zustand or raw / config.ZUSTAND.name, args.stadtteile or config.ORTSTEILE,
                      args.frist)
        b = bloecke(a)
        print("\n".join(text(b)), flush=True)
        ziel = os.environ.get("GITHUB_STEP_SUMMARY")
        if ziel:
            try:
                with open(ziel, "a", encoding="utf-8") as f:
                    f.write(markdown(b))
            except OSError as e:
                print(f"::warning::Zusammenfassung nicht geschrieben ({type(e).__name__})", flush=True)
    except Exception as e:   # nie den Lauf anhalten; kein Text des Fehlers (er könnte Inhalte tragen)
        print(f"::warning::Feldabdeckung nicht ermittelt ({type(e).__name__})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
