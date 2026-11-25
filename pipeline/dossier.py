"""Themenseiten (thema/<name>/): Vorlagen eines Themas in Strängen, mit Zeitleiste, Sitzungen und Wegen zum Mitwirken.
Die Beschreibung je Thema (Regeln, Bahnen, Texte) steht in pipeline/themenseiten/.

Herkunft: daimpad/ratsatlas-bonn @730d593 (pipeline/dossier.py), Gerüst der Seite und der Übersicht thema/ wie dort.
Kölner Anpassungen (Entscheidung 24.11.2026 (3), Antworten zum Plan vom 25.11.2026; inventur/themenseiten_port.tsv):
- Zuordnung nur über das Gremium (Gremium-Tor: Beratung im Fachausschuss des Themas, Kennung zur Laufzeit aus
  gremien.json über Gruppe und Paragraf der Zuständigkeitsordnung), Wörter im Titel und Folgevorlagen über die
  veröffentlichten Beziehungen superordinated und subordinated (verfahren). Nie über das abgeleitete Thema (topics.py,
  suche.json), die Federführung (amt, responsibility, underDirectionOf), relatedPaper oder Volltexte. zuordnen liest nur
  Felder der Gebietsdateien, damit der Prüfbogen aus dem Datenpaket (tools/themen_pruefbogen.py) dieselbe Zuordnung
  ergibt wie die Seite.
- Bahnen der Zeitleiste und „Nächste Sitzungen“ aus gremien.json (naechste_sitzung, folgende_sitzung): Absagen nach
  export.absage, Datenstand wie gremien.json; die Zeitachse ist aus dem Datenstand berechnet.
- „Wer berät mit“ aus gremien.json ohne Personen; „Mitwirken“ nach „Mitmachen in Köln“ (pipeline/mitwirken.py) ohne
  berechnete Fristen.
- Entfallen: Haushalt, Mitschnitte, berechnete Fristen, Bild zum Teilen und eigenes og:image (es gilt das Kölner
  Vorschaubild, gebietsseiten.teilen_head), Besetzung mit Namen, Seiten je Vorgang, Weiterleitungen.
Die Zuordnung ist abgeleitet: feste Regeln, je Vorlage mit Grund. Keine Bewertung, keine Zitate aus den Dokumenten.
Ausgabe: data/export/koeln/dossiers/<key>.json (export) und die statische Seite (seo), nur für freigegebene Themen
(themenseiten.freigegeben)."""
import csv
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from html import escape
from urllib.parse import quote

from . import actors, akkordeon, begriffsseite, config, geocode, mitwirken, process as proc
from .publish import EXPORT_PFAD

FACH = "fach"   # Bahn für alle Gremien ohne eigene Bahn (auch aufgelöste ohne Kennung); muss in jedem Thema stehen
STADTBEZIRK_GRUPPEN = ("mehrere Stadtbezirke", "ohne Ortsbezug")


@dataclass(frozen=True)
class Auswahl:
    """Gremien aus gremien.json (pipeline/gremien.py) nach Gruppe, Paragraf der Zuständigkeitsordnung und Anfang des
    Namens; jede angegebene Angabe muss passen, aufgelöste Gremien passen nie. Aufgelöst wird die Auswahl bei jedem Lauf
    (gremien_auswahl), nie über eine feste Kennung: Die Kennung kann sich ändern, wenn eine Organisation mit gleicher
    Kennung hinzukommt (gremien.schluessel)."""
    gruppe: str = None
    paragraf: int = None
    anfang: str = None

    def passt(self, e):
        return (not e.get("aufgeloest") and (self.gruppe is None or e.get("gruppe") == self.gruppe)
                and (self.paragraf is None or e.get("paragraf") == self.paragraf)
                and (self.anfang is None or (e.get("name") or "").startswith(self.anfang)))


@dataclass(frozen=True)
class Regel:
    """Eine Regel der Zuordnung; die erste passende gilt (Reihenfolge der Liste).
    - titel: Wort im Titel (re.Pattern); ohne titel gilt die Regel nur mit gremium_tor (nur über das Gremium)
    - bedingung: ein zweites Wort, das der Titel zusätzlich nennen muss
    - gremium_tor: nur für Vorlagen mit Beratung im Fachausschuss des Themas (Thema.fachausschuss; abgesagte Sitzungen
      zählen nicht); ohne titel nur, wenn der Titel Thema.tor_ausschluss nicht trifft"""
    strang: str
    titel: re.Pattern = None
    bedingung: re.Pattern = None
    gremium_tor: bool = False


@dataclass(frozen=True)
class Thema:
    """Beschreibung einer Themenseite (Beispiel: pipeline/themenseiten/verkehr.py)."""
    key: str
    pfad: str
    titel: str                # gleich topics.THEMES[key]
    lead: str                 # mit {seit}
    seo_text: str             # mit {vorlagen} („1 Vorlage“, „n Vorlagen“)
    straenge: list            # (Schlüssel, Titel, Regel in Worten), in der Reihenfolge der Seite
    regeln: list              # Regel, in der Reihenfolge der Prüfung
    punkt_straenge: tuple
    bahnen: list              # (Schlüssel, Beschriftung) von oben nach unten; FACH muss dabei sein
    bahn_regeln: tuple        # (Bahn, Auswahl): erste passende gilt, sonst FACH
    sitzungs_gremien: tuple   # Auswahl je Gruppe von Gremien für „Nächste Sitzungen“, Zeitleiste und Kalender
    punkt_gremien: tuple      # Punkte im Bild nur mit Beratung in diesen Gremien (Auswahl)
    punkt_text: str           # dieselben Gremien in Worten („im Rat, …“)
    sitzungen_text: str       # Satz über die Gremien der Liste „Nächste Sitzungen“
    bild_titel: str
    feed_text: str            # „zu …“
    hinweis: str
    pruefung_text: str        # Ergebnis des Prüfbogens; Pflicht für die Freigabe (themenseiten.freigegeben)
    nicht_gezeigt: list       # HTML
    fachausschuss: Auswahl = None   # Gremium-Tor, „Wer berät mit“ und Kachel; ohne eindeutigen Eintrag kein Tor
    tor_ausschluss: re.Pattern = None   # Titel, die nur über das Gremium nie zugeordnet werden
    folgevorlagen: bool = True
    karten_links: tuple = ()  # (Art, Schlüssel, Text): ("ebene", Schlüssel der Kartenebene, …), ("gremium", None, …)
    pruefung_datum: str = ""  # Tag des Prüfbogens im Gespräch (ISO); Pflicht für die Freigabe
    eingeklappt: frozenset = frozenset()
    leer_ausblenden: frozenset = frozenset()  # diese Stränge erscheinen nicht, solange sie leer sind
    nach_bezirk: frozenset = frozenset()  # Stränge, deren Vorlagen nach Stadtbezirk gegliedert erscheinen
    ausschluss: re.Pattern = None  # Titel, die zu keinem Strang gehören (vor allen Regeln, auch vor Folgevorlagen)
    stichprobe_je_strang: dict = field(default_factory=dict)
    stichprobe_nur_gremium: int = 0   # davon im Strang des Gremium-Tors nur über das Gremium
    stichprobe_folge: int = 0
    stichprobe_ohne: int = 0
    kandidat: re.Pattern = None  # Gegenprobe: Wörter im Titel nicht zugeordneter Vorlagen
    farben: tuple = ("#6d28d9", "#7c3aed", "#a78bfa")  # Übersicht thema/: Schrift, Verlauf von, Verlauf bis
    symbol: str = ""          # Übersicht thema/: Linien-Symbol (SVG-Inhalt, viewBox 0 0 24 24)
    produktbereich: str = None  # nur für die abgeschalteten Module haushaltsseite.py und haushaltsplan.py


@dataclass(frozen=True)
class Lauf:
    """Angaben eines Laufs, die nicht in der Beschreibung stehen: Beginn des Zeitraums (seit, Beginn der laufenden
    Wahlperiode), Kennung und Name des Fachausschusses aus gremien.json (ohne eindeutigen Eintrag None: kein Tor)."""
    seit: str
    tor: str = None
    tor_name: str = None


def gremien_auswahl(gremien_daten, auswahl):
    """Einträge aus gremien.json, auf die `auswahl` passt, in der Reihenfolge der Datei."""
    return [e for e in (gremien_daten or {}).get("gremien") or () if auswahl.passt(e)]


def fachausschuss(t, gremien_daten):
    """Eintrag des Fachausschusses in gremien.json, wenn genau einer passt; sonst None (kein Gremium-Tor; check meldet
    das als Befund, die Seite fällt nicht still auf Wörter im Titel zurück)."""
    treffer = gremien_auswahl(gremien_daten, t.fachausschuss) if t.fachausschuss else []
    return treffer[0] if len(treffer) == 1 else None


def wahlperiode_beginn(terms, heute):
    """Beginn der laufenden Wahlperiode am Tag `heute` aus den Wahlperioden der OParl-API (zeit.json `terms`: start, end;
    die späteste, die begonnen und nicht geendet hat), sonst actors.WAHLPERIODE_2025_BEGINN."""
    laufend = [x["start"][:10] for x in terms or () if isinstance(x, dict) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", (x.get("start") or "")[:10]) and x["start"][:10] <= heute
        and (not x.get("end") or x["end"][:10] >= heute)]
    return max(laufend) if laufend else actors.WAHLPERIODE_2025_BEGINN


def lauf(t, gremien_daten, terms=()):
    """Lauf eines Themas: seit aus den Wahlperioden zum Datenstand von gremien.json, Fachausschuss aus gremien.json."""
    e = fachausschuss(t, gremien_daten)
    return Lauf(seit=wahlperiode_beginn(terms, gremien_daten["meta"]["datenstand"]),
                tor=e and e["key"], tor_name=e and e["name"])


def _wort(m):
    """Ganzes Wort um einen Treffer, z. B. „Förderung“ statt „Förder“."""
    text, a, b = m.string, m.start(), m.end()
    while a and (text[a - 1].isalnum() or text[a - 1] == "-"):
        a -= 1
    while b < len(text) and (text[b].isalnum() or text[b] == "-"):
        b += 1
    return text[a:b].strip("-")


def beraten_in(p, keys):
    """Hat die Vorlage eine Station in einem Gremium mit Kennung aus `keys` (process[].gremium_key), deren Sitzung nicht
    abgesagt ist (export.absage: OParl `cancelled` oder Hinweis „abgesagt“ aus dem Namen)?"""
    from .export import absage   # hier, weil export.py dieses Modul einbindet
    return bool(keys) and any(s.get("gremium_key") in keys and not absage(s) for s in p.get("process") or ())


def _eigen(t, p, lauf_):
    """Zuordnung nur aus der Vorlage selbst (ohne Folgevorlagen): Ausschluss, Zeitraum, Regeln."""
    name = p.get("name") or ""
    if t.ausschluss and t.ausschluss.search(name):
        return None
    if (p.get("date") or "") < lauf_.seit:
        return None
    tor = beraten_in(p, {lauf_.tor} if lauf_.tor else set())
    vor = f"Beratung im {lauf_.tor_name}" if tor else None
    for r in t.regeln:
        if r.gremium_tor and not tor:
            continue
        mb = r.bedingung and r.bedingung.search(name)
        if r.bedingung and not mb:
            continue
        if r.titel is None:
            if r.gremium_tor and not (t.tor_ausschluss and t.tor_ausschluss.search(name)):
                return r.strang, vor
            continue
        m = r.titel.search(name)
        if m:
            woerter = [_wort(m)] + ([_wort(mb)] if mb and _wort(mb) != _wort(m) else [])
            text = "Titel: " + " und ".join(f"„{w}“" for w in woerter)
            return r.strang, f"{vor}; {text}" if vor else text
    return None


def zuordnen(t, p, lauf_, folge=None):
    """(Strang, Grund) einer Vorlage oder None; jede Vorlage gehört zu höchstens einem Strang. Reihenfolge: Ausschluss,
    Folgevorlage (`folge` aus verfahren, Schlüssel source_object), Zeitraum, Regeln."""
    name = p.get("name") or ""
    if t.ausschluss and t.ausschluss.search(name):
        return None
    if folge and p.get("source_object") in folge:
        return folge[p["source_object"]]
    return _eigen(t, p, lauf_)


def verfahren(t, papiere, lauf_):
    """Folgevorlagen (Antwort 1 A zum Plan, 25.11.2026): {source_object: (Strang, „Folgevorlage zu <Drucksache der
    Wurzel>“)} und Zahlen für das Log. Beziehungen aus den veröffentlichten Feldern superordinated und subordinated der
    Vorlagen (`papiere`: {Schlüssel: Vorgang}), beide Richtungen zusammen; jede Beziehung nur, wenn beide Drucksachen
    genau einmal vorkommen (mehrdeutige Drucksache: keine Weitergabe). Wurzel ist eine Vorlage ohne übergeordnete
    Vorlage; hat sie selbst einen Strang (_eigen, also ab Beginn des Zeitraums), erben ihn alle über subordinated
    erreichbaren Vorlagen, nur nach unten und mit Schutz gegen Zyklen. Erreicht eine Vorlage Wurzeln verschiedener
    Stränge oder mehrere Wurzeln, erbt sie nichts (gezählt)."""
    je_ref = defaultdict(list)
    for k, p in papiere.items():
        je_ref[p.get("reference")].append(k)
    eindeutig = {ref: ks[0] for ref, ks in je_ref.items() if ref and len(ks) == 1}
    kinder, eltern = defaultdict(set), defaultdict(set)
    zahl = Counter()
    for k, p in papiere.items():
        ref = p.get("reference")
        for art in ("subordinated", "superordinated"):
            for x in p.get(art) or ():
                r = (x or {}).get("reference")
                if not r or r == ref:
                    continue
                if ref not in eindeutig or r not in eindeutig:
                    zahl["mehrdeutig" if len(je_ref.get(r, ())) > 1 or len(je_ref.get(ref, ())) > 1
                         else "ohne_vorlage"] += 1
                    continue
                oben, unten = (k, eindeutig[r]) if art == "subordinated" else (eindeutig[r], k)
                kinder[oben].add(unten)
                eltern[unten].add(oben)
    wurzeln = sorted((k for k in kinder if not eltern[k]), key=lambda k: papiere[k].get("reference") or "")
    erbe = defaultdict(set)
    for w in wurzeln:
        eigen = _eigen(t, papiere[w], lauf_)
        if not eigen:
            continue
        gesehen, offen = {w}, [w]
        while offen:
            for c in sorted(kinder[offen.pop()]):
                if c not in gesehen:
                    gesehen.add(c)
                    erbe[c].add(w)
                    offen.append(c)
    folge = {}
    for c, ws in erbe.items():
        if len(ws) == 1:
            w = next(iter(ws))
            folge[papiere[c].get("source_object") or c] = (_eigen(t, papiere[w], lauf_)[0],
                                                           f"Folgevorlage zu {papiere[w]['reference']}")
        else:
            zahl["mehrere_wurzeln"] += 1
    zahl["beziehungen"] = sum(len(v) for v in kinder.values())
    zahl["folgevorlagen"] = len(folge)
    return folge, zahl


def _stationen(p, today):
    """Letzte Beratung mit Ergebnis und nächste Beratung einer Vorlage (Stationen der Prozesslinie). Nach dem
    Sitzungstag, nicht nach der Stelle in der Beratungsfolge (Entscheidung 17.11.2026 (15), wie der Stand): die letzte
    nach proc.massgeblich (spätester Tag, bei gleichem Tag die spätere; ohne Tag beim letzten Eintrag dieser; abgesagte
    Sitzungen nicht, außer alle sind abgesagt, Entscheidung 17.11.2026 (16) (A)), die nächste mit dem frühesten
    kommenden Tag, bei gleichem Tag die frühere."""
    beraten = [s for s in p["process"] if s.get("result")]
    kommend = [(proc.local_day(s["start_date"]), i) for i, s in enumerate(p["process"])
               if not s.get("result") and not s.get("cancelled") and s.get("start_date")
               and proc.local_day(s["start_date"]) >= today]
    naechste = p["process"][min(kommend)[1]] if kommend else None
    last = beraten[proc.massgeblich([proc.local_day(s.get("start_date")) for s in beraten],
                                    [s.get("cancelled") for s in beraten])] if beraten else None
    return last, naechste


def _eintrag(p, home, today):
    last, naechste = _stationen(p, today)
    return {
        "reference": p["reference"], "date": p.get("date"), "paper_type": p.get("paper_type"), "name": p.get("name"),
        "stand": p.get("stand"), "web": p.get("web"), "gebiet": home,
        "letzte_beratung": last and {"gremium": last["gremium"], "date": proc.local_day(last["start_date"]),
                                     "result": last["result"]},
        "naechste_beratung": naechste and {"gremium": naechste["gremium"],
                                           "date": proc.local_day(naechste["start_date"])},
    }


def bahn(t, kennung=None, name=None, gremien_je=None):
    """Bahn eines Gremiums: über die Kennung aus gremien.json (Gruppe, Paragraf) die erste passende Regel in
    t.bahn_regeln, sonst FACH; ohne Kennung (aufgelöstes Gremium, Gremium nicht in gremien.json) die Bahn der
    Bezirksvertretungen, wenn der Name mit „Bezirksvertretung“ beginnt, sonst FACH. Immer eine Bahn aus t.bahnen."""
    e = (gremien_je or {}).get(kennung) if kennung else None
    if e:
        b = next((b for b, a in t.bahn_regeln if a.passt(e)), FACH)
    elif (name or "").startswith("Bezirksvertretung"):
        b = next((b for b, a in t.bahn_regeln if a.gruppe == "bezirksvertretung"), FACH)
    else:
        b = FACH
    return b if b in {k for k, _ in t.bahnen} else FACH


VERWALTUNG_PUNKT = re.compile(r"beschlussvorlage|dringlichkeitsentscheidung", re.I)


def punkt_art(art, titel=""):
    """Erscheint eine Vorlage dieser Art als Punkt im Bild (Antwort 2 A zum Plan, 25.11.2026, wie in der Vorlage)? Eingaben nach
    § 24 GO NRW und Einwohnerfragen nie (actors.EINWOHNER_TYPES, geocode.eingabe); politische Arten nur Anträge (auch
    Änderungs- und Dringlichkeitsanträge, nicht Anfragen); Verwaltungsarten nur Beschlussvorlagen und
    Dringlichkeitsentscheidungen (nicht Mitteilungen und Stellungnahmen)."""
    if not isinstance(art, str) or not art or art in actors.EINWOHNER_TYPES or geocode.eingabe(art, titel):
        return False
    if art in actors.POLITIK_TYPES:
        return "antrag" in art.casefold()
    return art in actors.VERWALTUNG_TYPES and bool(VERWALTUNG_PUNKT.search(art))


def _punkt(t, p, e, strang, gremien_je, today):
    """Lage eines Beschlusses oder Antrags im Bild: letzte Beratung mit Ergebnis, sonst die nächste, sonst das erste
    Gremium der Beratungsfolge am Tag der Vorlage. Dazu die Angaben des Detailfelds (Strang mit Grund, Art,
    Beratungsfolge mit Ergebnis wörtlich aus der Quelle und Absage nach export.absage)."""
    from .export import absage
    last, naechste = _stationen(p, today)
    if last:
        st, datum = last, proc.local_day(last.get("start_date")) or e["date"]
    elif naechste:
        st, datum = naechste, proc.local_day(naechste["start_date"])
    else:
        st, datum = next((s for s in p["process"] if s.get("gremium")), None), e["date"]
    gremium = st.get("gremium") if st else None
    art = "entschieden" if e["stand"] == "entschieden" else "offen" if e["stand"] in ("offen", "ohne Beratungsfolge") \
        else "beraten"
    beratungen = [{"gremium": s["gremium"], "date": s.get("start_date") and proc.local_day(s["start_date"]),
                   "result": s.get("result"), **({"abgesagt": absage(s)} if absage(s) else {})}
                  for s in p["process"] if s.get("gremium")]
    return {"reference": e["reference"], "name": e["name"], "date": datum,
            "bahn": bahn(t, st and st.get("gremium_key"), gremium, gremien_je), "gremium": gremium,
            "art": art, "stand": e["stand"], "gebiet": e["gebiet"], "web": e["web"], "strang": strang,
            "grund": e["grund"], "paper_type": e["paper_type"], "beratungen": beratungen}


def bezirk(p):
    """Stadtbezirk einer Vorlage für die Gliederung (aus den Ortsbezügen einschließlich district_from_committee,
    abgeleitet)."""
    bezirke = {x.get("stadtbezirk") for x in p.get("locations") or [] if x.get("stadtbezirk")}
    if len(bezirke) == 1:
        return bezirke.pop()
    return STADTBEZIRK_GRUPPEN[0] if bezirke else STADTBEZIRK_GRUPPEN[1]


def _monat(d, n):
    """Erster Tag des Monats n Monate nach dem Monat von d."""
    m = d.year * 12 + d.month - 1 + n
    return date(m // 12, m % 12 + 1, 1)


def achse(heute, seit, termine=()):
    """Zeitachse aus dem Datenstand (statt fester Daten je Thema): Anfang erster Tag des Monats von `seit`, Knick erster
    Tag des Monats drei Monate vor `heute`, Ende erster Tag des Monats nach `heute` plus sechs Monaten, bis zum Monat
    nach dem spätesten kommenden Termin (`termine`: ISO-Tage), höchstens zwölf Monate nach `heute`. Rückblick 42 Prozent
    der Breite; liegt der Knick nicht nach dem Anfang, ohne Rückblick."""
    h, s = date.fromisoformat(heute), date.fromisoformat(seit)
    von, knick, bis = _monat(s, 0), _monat(h, -3), _monat(h, 7)
    spaet = max((date.fromisoformat(x) for x in termine if x and x > heute), default=None)
    if spaet:
        bis = max(bis, min(_monat(spaet, 1), _monat(h, 13)))
    anteil = 0.42
    if knick <= von:
        knick, anteil = von, 0.0
    return {"von": von.isoformat(), "knick": knick.isoformat(), "bis": bis.isoformat(), "anteil": anteil}


FELDER_SITZUNG = ("date", "time", "hinweis", "web", "source_object")


def sitzungen(t, gremien_daten, gremien_je):
    """Nächste Sitzungen der Gremien aus t.sitzungs_gremien laut gremien.json: naechste_sitzung und, wenn sie am Tag des
    Datenstands liegt, folgende_sitzung (gremien.json führt sie nur dann). Abgesagte fehlen dort schon (export.absage);
    `hinweis` nur „verschoben“. Bei nicht aktueller Liste der Sitzungen keine (gremien.json führt dann keine)."""
    out = []
    for e in gremien_daten["gremien"]:
        if not any(a.passt(e) for a in t.sitzungs_gremien):
            continue
        for feld in ("naechste_sitzung", "folgende_sitzung"):
            s = e.get(feld)
            if isinstance(s, dict) and s.get("date"):
                out.append({**{k: s[k] for k in FELDER_SITZUNG if k in s}, "gremium": e["name"], "key": e["key"],
                            "bahn": bahn(t, e["key"], e["name"], gremien_je)})
    return sorted(out, key=lambda m: (m["date"], m.get("time") is None, m.get("time") or "", m["gremium"]))


def wer_beraet_mit(t, gremien_daten):
    """Kasten „Wer berät mit“: Fachausschuss aus gremien.json ohne Personen (Felder aus gremien.FELDER, dazu Zeitraum
    und Zuständigkeitsordnung aus meta); None ohne eindeutigen Eintrag."""
    e = fachausschuss(t, gremien_daten)
    if not e:
        return None
    meta = gremien_daten["meta"]
    zusto = meta.get("zustaendigkeitsordnung") or {}
    return {**{k: e[k] for k in ("key", "name", "paragraf", "web", "sitzungen_12m", "vorlagen_12m", "naechste_sitzung",
                                 "folgende_sitzung") if k in e},
            "zeitraum": meta.get("zeitraum"), "satzung": {k: zusto.get(k) for k in ("titel", "url")}}


WEITERE_GREMIEN = (("bezirksvertretung", None, "die Bezirksvertretungen"), ("ausschuss", 7, "der Hauptausschuss"),
                   ("rat", None, "der Rat"))


def weitere_gremien(papiere, gremien_je, tor):
    """Welche Gremien Vorlagen des Themas außer dem Fachausschuss beraten (aus den Stationen mit Kennung): Texte aus
    WEITERE_GREMIEN in dieser Reihenfolge, nur die vorkommenden."""
    da = set()
    for p in papiere:
        for s in p.get("process") or ():
            e = gremien_je.get(s.get("gremium_key"))
            if e and e["key"] != tor:
                da.add((e.get("gruppe"), e.get("paragraf") if e.get("gruppe") == "ausschuss" else None))
    return [text for g, nr, text in WEITERE_GREMIEN if (g, nr) in da]


def daten(t, cache, home, gremien_daten, meta, terms=()):
    """Inhalt der Themenseite aus den Vorlagen des Exports (cache: id → Vorgang, home: id → Gebiet) und gremien.json
    (`gremien_daten`, Inhalt der Datei); `terms`: Wahlperioden wie in zeit.json. Datenstand ist der von gremien.json."""
    heute = gremien_daten["meta"]["datenstand"]
    gremien_je = {e["key"]: e for e in gremien_daten["gremien"]}
    lf = lauf(t, gremien_daten, terms)
    folge, zahl = verfahren(t, cache, lf) if t.folgevorlagen else ({}, Counter())
    straenge = {k: [] for k, _, _ in t.straenge}
    for pid, p in cache.items():
        hit = zuordnen(t, p, lf, folge)
        if hit:
            eintrag = {**_eintrag(p, home.get(pid), heute), "grund": hit[1], "_pid": pid}
            if hit[0] in t.nach_bezirk:
                eintrag["bezirk"] = bezirk(p)
            straenge[hit[0]].append(eintrag)
    im_bild = {e["key"] for a in t.punkt_gremien for e in gremien_auswahl(gremien_daten, a)}
    punkte = sorted((_punkt(t, cache[r["_pid"]], r, k, gremien_je, heute) for k in t.punkt_straenge
                     for r in straenge[k] if punkt_art(r["paper_type"], r["name"])
                     and beraten_in(cache[r["_pid"]], im_bild)),
                    key=lambda x: (x["date"] or "", x["reference"]))
    for i, x in enumerate(punkte, 1):
        x["nr"] = i
    zugeordnet = [cache[r["_pid"]] for rows in straenge.values() for r in rows]
    for rows in straenge.values():
        for r in rows:
            del r["_pid"]
        rows.sort(key=lambda r: (r["date"] or "", r["reference"]), reverse=True)
    termine = sitzungen(t, gremien_daten, gremien_je)
    wer = wer_beraet_mit(t, gremien_daten)
    liste = gremien_daten["meta"].get("sitzungsliste_nicht_aktuell")
    gruende = Counter("folge" if r["grund"].startswith("Folgevorlage") else "gremium" if r["grund"].startswith("Beratung")
                      else "titel" for rows in straenge.values() for r in rows)
    print(f"Themenseite {t.titel}: {sum(len(v) for v in straenge.values())} Vorlagen (Grund mit Titel "
          f"{gruende['titel']}, mit Gremium {gruende['gremium']}, Folgevorlage {gruende['folge']}), Punkte {len(punkte)}, "
          f"Sitzungen {len(termine)}; Fachausschuss in gremien.json {'eindeutig' if lf.tor else 'nicht eindeutig: kein Gremium-Tor'}; "
          f"Beziehungen {zahl['beziehungen']}, ausgelassen wegen mehrdeutiger Drucksache {zahl['mehrdeutig']}, ohne "
          f"Vorlage im Export {zahl['ohne_vorlage']}, Folgevorlagen mit mehreren Wurzeln {zahl['mehrere_wurzeln']}")
    return {
        "meta": {**meta, "namensnennung": config.NAMENSNENNUNG, "seit": lf.seit, "hinweis": t.hinweis,
                 **({"sitzungsliste_nicht_aktuell": liste} if liste else {})},
        "straenge": [{"key": k, "titel": ti, "regel": r, "eingeklappt": k in t.eingeklappt, "vorlagen": straenge[k]}
                     for k, ti, r in t.straenge if straenge[k] or k not in t.leer_ausblenden],
        "heute": heute,
        "achse": achse(heute, lf.seit, [m["date"] for m in termine] + [x["date"] for x in punkte if x["date"]]),
        "sitzungen": termine,
        "punkte": punkte,
        **({"wer_beraet_mit": wer} if wer else {}),
        "weitere_gremien": weitere_gremien(zugeordnet, gremien_je, lf.tor),
    }


# --- Seite --------------------------------------------------------------------------------------------

def _date(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else "–"


def _anzahl(n, eins, mehr):
    return f"{n} {eins if n == 1 else mehr}"


def _map(root, gebiet, ref):
    return f"{root}?gebiet={quote(gebiet, safe=':')}#{quote(ref)}" if gebiet else None


def _ref(root, r):
    """Drucksache als Link auf den Vorgang in der Karte (in Köln gibt es keine Seite je Vorgang)."""
    url = _map(root, r.get("gebiet"), r["reference"])
    return f'<a href="{escape(url)}">{escape(r["reference"])}</a>' if url else escape(r["reference"])


def _row(root, r):
    lb, nb = r.get("letzte_beratung"), r.get("naechste_beratung")
    verlauf = []
    if lb:
        verlauf.append(f'{escape(lb["gremium"] or "")} {_date(lb["date"])}: {escape(lb["result"])}')
    if nb:
        verlauf.append(f'als Nächstes: {escape(nb["gremium"] or "")} am {_date(nb["date"])}')
    return (f'      <tr><td data-l="Datum">{_date(r["date"])}</td><td data-l="Drucksache">{_ref(root, r)}</td>'
            f'<td data-l="Titel">{escape(r["name"] or "")}<br><small>{escape(r["paper_type"] or "")}'
            + (f' · <a href="{escape(r["web"])}">Original</a>' if r.get("web") else "")
            + f' · Grund: {escape(r["grund"])}</small></td>'
            f'<td data-l="Stand">{escape(r["stand"] or "")}' + (f'<br><small>{"<br>".join(verlauf)}</small>' if verlauf else "")
            + "</td></tr>")


def _tabelle(rows):
    return f"""    <table class="vorlagen">
      <thead><tr><th scope="col">Datum</th><th scope="col">Drucksache</th><th scope="col">Titel</th><th scope="col">Stand</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>"""


def _nach_bezirk(root, vorlagen):
    """Vorlagen je Stadtbezirk, jeder Abschnitt eingeklappt; zuletzt mehrere Stadtbezirke und ohne Ortsbezug."""
    gruppen = {}
    for r in vorlagen:
        gruppen.setdefault(r["bezirk"], []).append(r)
    folge = sorted(gruppen, key=lambda b: (b in STADTBEZIRK_GRUPPEN, b == STADTBEZIRK_GRUPPEN[1], b))
    teile = [f"    <details>\n      <summary>{escape(b)} ({len(gruppen[b])})</summary>\n"
             + _tabelle("\n".join(_row(root, r) for r in gruppen[b])) + "\n    </details>" for b in folge]
    return "\n".join(teile)


def _wann(m):
    """Tag und Uhrzeit einer Sitzung: „TT.MM.JJJJ, HH:MM Uhr“, ohne Uhrzeit nur der Tag."""
    return f'{_date(m["date"])}{(", " + escape(m["time"]) + " Uhr") if m.get("time") else ""}'


def _zusatz(m):
    """Hinweis „verschoben“ aus dem Sitzungsnamen und Link zur Tagesordnung, sobald die Stadt sie veröffentlicht hat."""
    return ((" <small>(laut Sitzungsnamen verschoben)</small>" if m.get("hinweis") == "verschoben" else "")
            + (f' (<a href="{escape(m["web"])}">Tagesordnung</a>)' if m.get("web")
               else " <small>(Tagesordnung noch nicht veröffentlicht)</small>"))


def _liste_nicht_aktuell(d):
    """Satz bei nicht aktueller Liste der Sitzungen, wie unter „Gremien und Ämter“ (site/gremien.js)."""
    n = d["meta"].get("sitzungsliste_nicht_aktuell")
    if not n:
        return ""
    from .export import berliner_tag
    tag = berliner_tag(n.get("stand"))
    return ("Die Liste der Sitzungen wurde beim letzten Abruf nicht aktualisiert; gezeigt wird "
            + (f"der Stand vom {_date(tag)}" if tag else "der letzte gültige Stand") + "; deshalb fehlen die nächsten Sitzungen.")


def _sitzungen(t, d):
    liste = _liste_nicht_aktuell(d)
    if liste:
        zeilen = f"    <p>{escape(liste)}</p>"
    elif d["sitzungen"]:
        zeilen = "    <ul>\n" + "\n".join(f'      <li>{_wann(m)}: {escape(m["gremium"])}{_zusatz(m)}</li>'
                                           for m in d["sitzungen"]) + "\n    </ul>"
    else:
        zeilen = "    <p>Im Sitzungskalender ist keine kommende Sitzung dieser Gremien eingetragen.</p>"
    return f"""    <h2 id="sitzungen">Nächste Sitzungen</h2>
    <p>{escape(t.sitzungen_text)} Die Sitzungen sind öffentlich; einzelne Punkte werden nichtöffentlich beraten.</p>
{zeilen}
    <p class="meta">Termine laut Sitzungskalender (OParl-API der Stadt Köln); abgesagte Sitzungen fehlen. Maßgeblich ist die Einladung im Ratsinformationssystem.</p>
"""


def _wer_beraet_mit(d, root):
    """Kasten „Wer berät mit“ aus gremien.json: Name, Paragraf mit Link auf die Satzung, Zahlen für 12 Monate, nächste
    Sitzung, Links in die Gremienansicht und auf die Vorlagen des Gremiums; keine Personen."""
    a = d.get("wer_beraet_mit")
    if not a:
        return ""
    name, key = escape(a["name"]), quote(a["key"], safe="")
    satzung = a.get("satzung") or {}
    para = f'§ {escape(str(a["paragraf"]))} der Zuständigkeitsordnung'
    if satzung.get("url"):
        para = (f'<a href="{escape(satzung["url"])}" target="_blank" rel="noopener">{para}'
                f'<span class="visually-hidden"> (PDF, neuer Tab)</span></a>')
    zr = a.get("zeitraum") or {}
    zeitraum = (f"In den 12 Monaten bis {_date(zr['bis'])}" if zr.get("bis") else "In 12 Monaten")
    zeilen = [f"<li>Fachausschuss für dieses Thema laut {para} <small>(abgeleitet, über den Namen des Ausschusses)</small></li>",
              f"<li>{zeitraum}: {_anzahl(a.get('sitzungen_12m') or 0, 'Sitzung', 'Sitzungen')}, "
              f"{_anzahl(a.get('vorlagen_12m') or 0, 'Vorlage', 'Vorlagen')} beraten <small>(abgesagte Sitzungen zählen "
              "nicht)</small></li>"]
    liste = _liste_nicht_aktuell(d)
    naechste = [m for m in (a.get("naechste_sitzung"), a.get("folgende_sitzung")) if isinstance(m, dict)]
    if liste:
        zeilen.append(f"<li>{escape(liste)}</li>")
    elif naechste:
        zeilen.append("<li>Nächste Sitzung: " + "; danach ".join(_wann(m) + _zusatz(m) for m in naechste) + "</li>")
    weitere = d.get("weitere_gremien") or []
    satz = ""
    if weitere:
        aufz = weitere[0] if len(weitere) == 1 else ", ".join(weitere[:-1]) + " und " + weitere[-1]
        satz = f"    <p>Vorlagen dieses Themas beraten außerdem {aufz} (aus der Beratungsfolge).</p>\n"
    return f"""    <h2 id="fachausschuss">Wer berät mit: {name}</h2>
    <ul>
      {chr(10).join("      " + z if i else z for i, z in enumerate(zeilen))}
    </ul>
{satz}    <p><a href="{root}?wer=gremien&amp;kennung={key}">{name} unter „Gremien und Ämter“</a> · <a href="{root}?gremium_filter={key}">Vorlagen dieses Gremiums auf der Karte</a> · <a href="{root}?wer=gremien">Alle Gremien</a></p>
{akkordeon.mehr("Quelle", "<p>Gremien aus dem Ratsinformationssystem der Stadt Köln (OParl-API) wie unter „Gremien und Ämter“, ohne Besetzung und ohne Namen von Personen; der Paragraf ist über den Namen des Ausschusses der Zuständigkeitsordnung zugeordnet. " + escape(config.NAMENSNENNUNG) + ".</p>")}"""


def _quellen(t, root):
    return (f'<p>Quelle: Ratsinformationssystem der Stadt Köln (OParl-API): Vorlagen, Beratungen, Sitzungen und Gremien; '
            f'Gremien, Paragrafen und nächste Sitzungen wie unter „Gremien und Ämter“. {escape(config.NAMENSNENNUNG)}. '
            f'Die Daten als JSON: <a href="{root}{EXPORT_PFAD}/dossiers/{t.key}.json">{t.key}.json</a>.</p>'
            "<p>Stand und letzte Beratung zählen eine Sitzung nur dann nicht mehr, wenn die Stadt sie in der Schnittstelle "
            "absagt; die Liste der Sitzungen, die Zeitleiste und der Kalender lassen auch Sitzungen weg, die laut "
            "Sitzungsnamen abgesagt sind. Das Detailfeld nennt solche Beratungen „laut Sitzungsnamen abgesagt“.</p>"
            "<p>Die Seite beschreibt Verfahren; sie bewertet keine Entscheidungen. Maßgeblich sind die Originale im "
            "Ratsinformationssystem.</p>")


def body(t, d, root, karten=()):
    """HTML der Themenseite; `karten`: Links zur Karte [(Adresse, Text)], nur für Ebenen, die im Bau vorliegen."""
    from . import prozessbild
    straenge = []
    for s in d["straenge"]:
        rows = "\n".join(_row(root, r) for r in s["vorlagen"])
        tabelle = _tabelle(rows) if rows else "    <p>Keine Vorlagen.</p>"
        nach_bezirk = rows and any("bezirk" in r for r in s["vorlagen"])
        if nach_bezirk:
            tabelle = _nach_bezirk(root, s["vorlagen"])
        elif rows and s.get("eingeklappt"):
            tabelle = (f"    <details>\n      <summary>{_anzahl(len(s['vorlagen']), 'Vorlage', 'Vorlagen')} "
                       f"anzeigen</summary>\n{tabelle}\n    </details>")
        regel = (f"<p>Regel (abgeleitet): {escape(s['regel'].rstrip('.'))}."
                 + (" Gliederung nach Stadtbezirk aus den Ortsbezügen (abgeleitet)." if nach_bezirk else "") + "</p>")
        straenge.append(f"""    <h3 id="{s['key']}">{escape(s['titel'])} ({len(s['vorlagen'])})</h3>
{akkordeon.mehr("Wie zugeordnet?", regel, klasse="hh-mehr meta-acc regel-acc")}""" + tabelle)
    inhalt = " · ".join(f'<a href="#{s["key"]}">{escape(s["titel"])}</a>' for s in d["straenge"])
    ziele = ([("fachausschuss", "Wer berät mit")] if d.get("wer_beraet_mit") else []) \
        + [("sitzungen", "Nächste Sitzungen"), ("mitwirken", "Mitwirken"), ("vorlagen", "Vorlagen nach Strang")]
    sprung = " · ".join(f'<a href="#{k}">{x}</a>' for k, x in ziele)
    nicht = "".join(f"<li>{x}</li>" for x in t.nicht_gezeigt)
    # Akkordeon „Begriffe auf dieser Seite“: Vorlagenarten, Stände und Ergebnisse der Seite
    texte = [x for s in d["straenge"] for r in s["vorlagen"]
             for x in (r.get("paper_type"), r.get("stand"), (r.get("letzte_beratung") or {}).get("result"))]
    texte += [b.get("result") for p in d.get("punkte") or [] for b in p.get("beratungen") or []]
    begriffe = begriffsseite.akkordeon(texte, root)
    ink, von, bis = t.farben  # Kopf wie die Kachel der Übersicht thema/ (Symbol und Farbverlauf)
    zuordnung = ("<p>Jede Vorlage steht in höchstens einem Strang. Die Zuordnung folgt festen Regeln: Beratung im "
                 "Fachausschuss, Wörter im Titel und Folgevorlagen über die Beziehungen zwischen Vorlagen; der Grund steht "
                 "je Vorlage dabei. Nicht verwendet werden die abgeleiteten Themen der Karte und die Federführung."
                 + (f" {escape(t.pruefung_text)}" if t.pruefung_text else "")
                 + " Der Stand ist aus der Beratungsfolge abgeleitet, Ergebnisse stehen wörtlich wie in der Quelle.</p>")
    return f"""    <div class="thema-kopf" style="--k-ink:{ink};--k-von:{von};--k-bis:{bis}">
      <div class="kachel-kopf thema-band">{_svg(t.symbol, "kachel-symbol")}<a class="thema-alle" href="{root}{UEBERSICHT}">Alle Themen</a></div>
      <h1>{escape(t.titel)}</h1>
    </div>
    <p class="lead">{escape(t.lead.format(seit=_date(d["meta"]["seit"])))}</p>
    <nav class="thema-sprung" aria-labelledby="sprung-h"><h2 id="sprung-h">Auf dieser Seite</h2><p>{sprung}</p></nav>
{prozessbild.abschnitt(t, d, root, karten)}
{_wer_beraet_mit(d, root)}{_sitzungen(t, d)}{mitwirken.abschnitt(root)}    <h2 id="vorlagen">Vorlagen nach Strang</h2>
    <p>{inhalt}</p>
{akkordeon.mehr("Wie die Vorlagen zugeordnet sind", zuordnung)}{chr(10).join(straenge)}
{begriffe}{akkordeon.mehr("Was diese Seite nicht zeigt", f"<ul>{nicht}</ul>")}{akkordeon.mehr("Quellen und Methode", _quellen(t, root))}"""


def karten_links(t, d, site, root):
    """Links zur Karte (Antwort 3 A zum Plan, 25.11.2026): Ebenen nur, wenn sie im gebauten Ordner `site` vorliegen
    (ebenen.json mit dem Schlüssel; Punkte aus den Kontextdaten mit kontext.json und flaechen/punkte_<schlüssel>.json,
    beides nur mit Freigabe „kontext“), die Vorlagen des Fachausschusses nur mit Kennung. Kein Link auf den Filter
    der abgeleiteten Themen (?thema=)."""
    base = site / "data" / "export" / config.STADT

    def lesen(pfad):
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    kontext = config.ZUSATZTHEMEN.get("kontext")
    eb = (lesen(base / "ebenen.json") or {}) if kontext else {}
    ebenen = {e.get("key") for e in eb.get("ebenen") or () if isinstance(e, dict)}
    kx = (lesen(base / "kontext.json") or {}) if kontext else {}
    out = []
    for art, schluessel, text in t.karten_links:
        if art == "ebene" and (schluessel in ebenen or (isinstance(kx, dict) and kx.get("ortsteile")
                                                        and (base / "flaechen" / f"punkte_{schluessel}.json").exists())):
            out.append((f"{root}?ebenen={quote(schluessel)}", text))
        elif art == "gremium" and d.get("wer_beraet_mit"):
            out.append((f"{root}?gremium_filter={quote(d['wer_beraet_mit']['key'], safe='')}", text))
    return out


def _dossier_pfad(site, t, endung="json"):
    return site / "data" / "export" / config.STADT / "dossiers" / f"{t.key}.{endung}"


def write(t, site, site_url, page):
    """Schreibt die Themenseite nach site; gibt die Pfade relativ zu site_url zurück (für die Sitemap). Ohne eigene
    Angaben zum Teilen: Es gilt das Kölner Vorschaubild (gebietsseiten.teilen_head)."""
    from .gebietsseiten import _vorlagen_zahl, feed_head
    src = _dossier_pfad(site, t)
    if not src.exists():
        return []
    d = json.loads(src.read_text(encoding="utf-8"))
    n = sum(len(s["vorlagen"]) for s in d["straenge"])
    out = site / t.pfad / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    root = "../" * t.pfad.rstrip("/").count("/") + "../"
    head = feed_head(f"dossiers/{t.key}.xml", f"{config.SEITENNAME} – {t.titel}", root)
    out.write_text(page(site_url, t.pfad, f"{t.titel} – {config.SEITENNAME}", t.seo_text.format(vorlagen=_vorlagen_zahl(n)),
                        body(t, d, root, karten_links(t, d, site, root)), root, head), encoding="utf-8")
    print(f"Themenseite {t.titel}: {n} Vorlagen")
    return [t.pfad]


UEBERSICHT = "thema/"


HAND = ('<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11V4.5a1.5 1.5 0 0 1 3 0V12M14 11.5V6a1.5 1.5 0 0 1 3 0v8a7 7 0 '
        '0 1-7 7h-.5a6 6 0 0 1-5.1-2.8L3.3 15a1.5 1.5 0 0 1 2.4-1.8L8 15.5"/>')
WOCHENTAG = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")


def _svg(inhalt, klasse):
    return (f'<svg class="{klasse}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{inhalt}</svg>')


def _kachel(t, d):
    """Kachel der Übersicht: Symbol und Farbverlauf, Zahl der Vorlagen, Stränge mit Zahl, nächste Sitzung des
    Fachausschusses laut gremien.json (ohne Frist)."""
    n = sum(len(s["vorlagen"]) for s in d["straenge"])
    ink, von, bis = t.farben
    straenge = "".join(f'<li>{escape(s["titel"])} <span class="kachel-n">{len(s["vorlagen"])}</span></li>'
                       for s in d["straenge"])
    a = d.get("wer_beraet_mit")
    heute = d.get("heute") or ""
    sitzung = a and next((m for m in (a.get("naechste_sitzung"), a.get("folgende_sitzung"))
                          if isinstance(m, dict) and (m.get("date") or "") >= heute), None)
    if d["meta"].get("sitzungsliste_nicht_aktuell") or not a:
        termin = ""
    elif sitzung:
        tag = WOCHENTAG[date.fromisoformat(sitzung["date"]).weekday()]
        termin = (f'          <p class="kachel-sitzung">{_svg(HAND, "kachel-hand")}<span>Nächste Sitzung: '
                  f'{escape(a["name"])}, <time datetime="{sitzung["date"]}">{tag} {_date(sitzung["date"])}</time>'
                  f'</span></p>\n')
    else:
        termin = (f'          <p class="kachel-sitzung kachel-leise">{_svg(HAND, "kachel-hand")}<span>Keine kommende '
                  f'Sitzung des Gremiums {escape(a["name"])} eingetragen</span></p>\n')
    return (f'      <li class="kachel" style="--k-ink:{ink};--k-von:{von};--k-bis:{bis}">\n'
            f'        <div class="kachel-kopf">{_svg(t.symbol, "kachel-symbol")}</div>\n'
            f'        <div class="kachel-inhalt">\n'
            f'          <h2><a href="../{t.pfad}">{escape(t.titel)}</a></h2>\n'
            f'          <p class="kachel-zahl"><strong>{n}</strong> {"Vorlage" if n == 1 else "Vorlagen"} in '
            f'{_anzahl(len(d["straenge"]), "Strang", "Strängen")}</p>\n'
            f'          <ul class="kachel-straenge" aria-label="Stränge">{straenge}</ul>\n'
            + termin
            + '        </div>\n'
            '      </li>')


def uebersicht(themen, site, site_url, page):
    """Übersicht thema/ über die geschriebenen Themenseiten als Kacheln (Symbol, Farbe, Zahlen, Stränge, nächste
    Sitzung); gibt den Pfad für die Sitemap zurück, ohne Themenseiten keinen. Läuft nach write (prüft die Seiten)."""
    kacheln, refs, stand, titel = [], set(), "", []
    for t in themen:
        src = _dossier_pfad(site, t)
        if not (site / t.pfad / "index.html").exists() or not src.exists():
            continue
        d = json.loads(src.read_text(encoding="utf-8"))
        kacheln.append(_kachel(t, d))
        titel.append(t.titel)
        refs |= {r["reference"] for s in d["straenge"] for r in s["vorlagen"]}
        stand = max(stand, d.get("heute") or "")
    if not kacheln:
        return []
    eins = len(kacheln) == 1
    body = f"""    <div class="themen-kopf">
    <h1>Themen</h1>
    <p class="lead">{"Die Themenseite ordnet" if eins else "Themenseiten ordnen"} Vorlagen aus dem Ratsinformationssystem der Stadt Köln nach Strängen und {"zeigt" if eins else "zeigen"}, wo ein Verfahren steht, was entschieden ist und wo man sich einbringen kann.</p>
    <ul class="themen-zahlen" aria-label="Auf einen Blick">
      <li><strong>{len(refs)}</strong> {"Vorlage" if len(refs) == 1 else "Vorlagen"} seit Beginn der Wahlperiode</li>
      <li><strong>{len(kacheln)}</strong> {"Thema" if eins else "Themen"}</li>
      <li>Stand <strong>{_date(stand)}</strong></li>
    </ul>
{akkordeon.mehr("Wie die Vorlagen zugeordnet sind", "<p>Die Zuordnung ist abgeleitet: feste Regeln (Beratung im Fachausschuss, Wörter im Titel, Folgevorlagen), je Vorlage mit Grund, an einer Stichprobe von Hand geprüft. Maßgeblich sind die Originale im Ratsinformationssystem.</p>")}    </div>
    <ul class="kacheln">
{chr(10).join(kacheln)}
    </ul>
    <p><a href="../">Zur Karte</a></p>"""
    out = site / UEBERSICHT / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = (f"Themenseite des {config.SEITENNAME}: {titel[0]} – Vorlagen und Verfahren mit Zeitleiste, Sitzungen und "
            "Wegen zum Mitwirken." if eins else f"Themenseiten des {config.SEITENNAME}: Vorlagen und Verfahren je Thema "
            "mit Zeitleiste, Sitzungen und Wegen zum Mitwirken.")
    out.write_text(page(site_url, UEBERSICHT, f"Themen – {config.SEITENNAME}", text, body, "../"), encoding="utf-8")
    return [UEBERSICHT]


# --- Prüfbogen zur Prüfung von Hand (ohne Datenbank, ohne Netz) --------------------------------------------------

# Titel mit möglichem Personenbezug: vor der Ziehung aussortiert und nur gezählt (Prüfbogen im Gespräch)
PERSONENBEZUG = re.compile(r"Benennung|Umbenennung|Ehrung|Gedenk|\bWahl\b|Bestellung|Entsendung|Nachbesetzung|"
                           r"Umbesetzung|sachkundig|Mitglied|Herr|Frau|Dr\.|Prof\.", re.I)
DRUCKSACHE = re.compile(r"(?:AN/)?\d{1,6}/\d{2,4}")
SPALTEN_PRUEFBOGEN = ["nr", "monat", "vorlagenart", "titel", "beratende_gremien", "strang", "grund",
                      "urteil (passt/teilweise/passt nicht/unklar; Gegenprobe: fehlt/richtig ausgelassen)",
                      "richtiger strang (falls abweichend)", "anmerkung"]


def stichprobe(t, papiere, gremien_daten, ziel, terms=(), seed=2026, maske_=None):
    """Prüfbogen: geschichtete Ziehung zugeordneter Vorlagen je Strang (davon im Strang des Gremium-Tors einige nur über
    das Gremium), einige Folgevorlagen und eine Gegenprobe nicht zugeordneter Vorlagen mit t.kandidat im Titel oder mit
    Beratung im Fachausschuss. `papiere`: {Schlüssel: Vorgang}, jede Vorlage einmal (Gebietsdateien des Exports);
    `ziel`: Ordner außerhalb des Repositorys und außerhalb von data/export. Schreibt prüfbogen_<key>.tsv (laufende
    Nummer statt Drucksache, Titel nach `maske_` und mit <DS> statt Drucksachen; Eingaben und Einwohnerfragen ohne
    Titel), schluessel_<key>.tsv (Nummer → Drucksache und Link, nur zum Nachschlagen) und zahlen_<key>.tsv (je Strang
    und Grund, ohne Einzelangaben). Titel mit Personenbezug (PERSONENBEZUG) werden vor der Ziehung aussortiert und nur
    gezählt. Fehlt ein Strang, gehen seine Plätze an die übrigen, ohne die Gesamtzahl zu überschreiten."""
    from pathlib import Path
    ziel = Path(ziel)
    if config.ROOT in ziel.resolve().parents or ziel.resolve() == config.ROOT:
        raise SystemExit(f"Prüfbogen nur außerhalb des Repositorys: {ziel}")
    lf = lauf(t, gremien_daten, terms)
    folge, _ = verfahren(t, papiere, lf) if t.folgevorlagen else ({}, Counter())
    zug, ohne = {k: [] for k, _, _ in t.straenge}, []
    aussortiert = 0
    for k in sorted(papiere, key=lambda k: (papiere[k].get("reference") or "", k)):
        p = papiere[k]
        hit = zuordnen(t, p, lf, folge)
        if PERSONENBEZUG.search(p.get("name") or ""):
            aussortiert += 1
            continue
        if hit:
            zug[hit[0]].append((p, hit))
        elif (p.get("date") or "") >= lf.seit and not (t.ausschluss and t.ausschluss.search(p.get("name") or "")) and (
                (t.kandidat and t.kandidat.search(p.get("name") or "")) or beraten_in(p, {lf.tor} if lf.tor else set())):
            ohne.append((p, None))
    rnd = random.Random(seed)
    istfolge = lambda x: x[1][1].startswith("Folgevorlage")
    nurgremium = lambda x: x[1][1].startswith("Beratung") and "Titel:" not in x[1][1]
    rows, gewaehlt = [], set()

    def ziehe(pool, n, art):
        pool = [x for x in pool if id(x[0]) not in gewaehlt]
        for x in rnd.sample(pool, min(n, len(pool))):
            gewaehlt.add(id(x[0]))
            rows.append((x, art))
        return min(n, len(pool))
    tor_strang = next((r.strang for r in t.regeln if r.gremium_tor and r.titel is None), None)
    soll = dict(t.stichprobe_je_strang)
    fehlt = 0
    for k, _, _ in t.straenge:
        n = soll.get(k, 0)
        g = ziehe([x for x in zug[k] if nurgremium(x)], min(t.stichprobe_nur_gremium, n), "strang") \
            if k == tor_strang and t.stichprobe_nur_gremium else 0
        fehlt += n - g - ziehe([x for x in zug[k] if not istfolge(x)], n - g, "strang")
    fehlt += t.stichprobe_folge - ziehe([x for v in zug.values() for x in v if istfolge(x)], t.stichprobe_folge, "folge")
    reihe = [k for k, _, _ in t.straenge]
    while fehlt > 0 and any(x for k in reihe for x in zug[k] if id(x[0]) not in gewaehlt):
        for k in reihe:
            if fehlt and ziehe(zug[k], 1, "strang"):
                fehlt -= 1
    ziehe(ohne, t.stichprobe_ohne, "gegenprobe")
    titel_je = {k: ti for k, ti, _ in t.straenge}
    maskiert = maske_ or (lambda name, ref: name)
    bogen, schluessel = [], []
    for i, ((p, hit), art) in enumerate(rows, 1):
        einwohner = p.get("paper_type") in actors.EINWOHNER_TYPES or geocode.eingabe(p.get("paper_type"), p.get("name"))
        titel = "" if einwohner else DRUCKSACHE.sub("<DS>", maskiert(p.get("name") or "", p.get("reference")))
        gremien = "; ".join(dict.fromkeys(s.get("gremium") for s in p.get("process") or () if s.get("gremium")))
        strang = titel_je[hit[0]] if hit else "nicht zugeordnet (Gegenprobe)"
        grund = DRUCKSACHE.sub("<DS>", hit[1]) if hit else "—"
        bogen.append([i, (p.get("date") or "")[:7], p.get("paper_type") or "", titel, gremien, strang, grund, "", "", ""])
        schluessel.append([i, p.get("reference") or "", p.get("web") or ""])
    zahl = Counter()
    for k, v in zug.items():
        zahl[("strang", titel_je[k])] = len(v)
        for _, hit in v:
            zahl[("grund", "Folgevorlage" if hit[1].startswith("Folgevorlage") else
                  "nur Gremium" if hit[1].startswith("Beratung") and "Titel:" not in hit[1] else
                  "Gremium und Titel" if hit[1].startswith("Beratung") else "Titel")] += 1
    zahl[("gegenprobe", "Kandidaten ohne Zuordnung")] = len(ohne)
    zahl[("aussortiert", "Titel mit Personenbezug")] = aussortiert
    ziel.mkdir(parents=True, exist_ok=True)
    for name, kopf, zeilen in ((f"pruefbogen_{t.key}.tsv", SPALTEN_PRUEFBOGEN, bogen),
                               (f"schluessel_{t.key}.tsv", ["nr", "drucksache", "link"], schluessel),
                               (f"zahlen_{t.key}.tsv", ["art", "wert", "anzahl"],
                                [[a, w, n] for (a, w), n in sorted(zahl.items())])):
        with (ziel / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(kopf)
            w.writerows(zeilen)
    print(f"Prüfbogen {t.titel}: {len(bogen)} Zeilen ({sum(a == 'gegenprobe' for _, a in rows)} Gegenprobe), "
          f"aussortiert mit Personenbezug {aussortiert} → {ziel}")
    return bogen
