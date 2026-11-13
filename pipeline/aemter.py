"""Ämtertabelle der Stadt Köln: Dezernate und Dienststellen aus dem Geschäfts- und Dezernatsverteilungsplan,
versioniert mit Gültigkeitsdatum (CLAUDE.md 3.2), und Zuordnung der Federführung (CLAUDE.md 5.3).

Tabelle `data/aemter/aemter_koeln.tsv`, erzeugt ohne Netz mit `tools/aemter_tabelle.py` aus dem PDF der Stadt. Je Plan
eine Gruppe von Zeilen mit demselben `gueltig_ab` (der „Stand“, den der Plan nennt); ein neuer Plan kommt als weitere
Gruppe dazu. Jede Zeile nennt ihre Fundstelle (Seite, Spalte, Eintrag), die Adresse, die Abrufzeit und die Prüfsumme
des PDFs. Übernommen sind nur Kennungen und Bezeichnungen von Dezernaten und Dienststellen, keine Namen von Personen und
kein weiterer Text.

Zuordnung (`zuordnen`): Ein Plan gilt ab seinem Stand bis zum Stand des nächsten Plans in der Tabelle; eine Vorlage wird
mit dem Plan verglichen, der an ihrem Datum gilt. Vorlagen vor dem ältesten Plan und Vorlagen ohne Datum bleiben ohne
Zuordnung, der Status nennt den Grund: Zuschnitt und Bezeichnungen ändern sich (CLAUDE.md 3.2 nennt den Stand
01.10.2026, die geladene Fassung den Stand 01.11.2026), ein jüngerer Plan belegt den früheren Zuschnitt nicht.
Verglichen wird
- eine Kennung wie im Kopf der Verwaltungsvorlage („Dezernat, Dienststelle“, z. B. „VI/61“, „II/II/2“; auch „II/2“ und
  „VI/61/612“): Dezernat und Dienststelle müssen im Plan zusammenpassen, sonst „Dezernat weicht ab“;
- der Name der Organisation aus `underDirectionOf`: Nummer und Name („61 Stadtplanungsamt“, „61 - Stadtplanungsamt“),
  Nummer allein („Amt 61“), Kennung („VI/61“) oder Name allein („Stadtplanungsamt“, auch ohne Klammerzusatz wie
  „(e. E.)“ oder mit dem Kurznamen „DigIT“). Tragen mehrere Einträge des Plans denselben Namen („Verwaltung“), gilt das
  als mehrdeutig, ohne Zuordnung.
Nur eindeutige Treffer zählen (ZUGEORDNET); alles andere bleibt wie zuvor und trägt nur den Status (Export
`responsibility[].aemtertabelle`, `audit_federfuehrung.tsv`).

Schnittstelle für den Schritt „Dokumente“ (PDF-Köpfe, eigener Branch): Er legt die erkannte Kennung je Vorlage in
`paper_responsibility.kennung` ab; `export` ordnet sie über `zuordnen(kennung=…, datum=…)` zu, sobald die Spalte da ist
(`zuordnung_federfuehrung`). Wer die Kennung anders weiterreicht, ruft `zuordnen` direkt auf.
"""
import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import config

TABELLE = config.ROOT / "data" / "aemter" / "aemter_koeln.tsv"
SPALTEN = ("gueltig_ab", "dezernat", "dienststelle", "kennung", "ebene", "uebergeordnet", "name", "kurzname",
           "eigenbetriebsaehnlich", "markierung", "fundstelle", "quelle", "abgerufen", "sha256")
# Ebenen nach der Form der Nummer im Plan (tools/aemter_tabelle.py): Dezernat (Spaltenkopf), Einheit des Dezernats
# („VI/2“), Dienststelle („61“, Bürgerämter „02-1“), Untereinheit einer Dienststelle („612“, „64/1“, „02-6/4“),
# vierstellige Nummer mit Punkt („4511“; die Legende erklärt „•“ als Punktdienststelle)
EBENEN = ("dezernat", "dezernatseinheit", "dienststelle", "untereinheit", "punktdienststelle")
TITEL = "Geschäfts- und Dezernatsverteilungsplan der Stadt Köln"
METHODE = "aemtertabelle"

EINDEUTIG = "eindeutig"
NUR_DIENSTSTELLE = "eindeutig bis zur Dienststelle"   # Kennung genauer als der Plan („VI/61/9“): zugeordnet ist „61“
MEHRDEUTIG = "mehrdeutig"
KEIN_TREFFER = "kein Treffer"
DEZERNAT_WEICHT_AB = "Dezernat weicht ab"
NAME_WEICHT_AB = "Name weicht ab"
VOR_PLAN = "vor dem ältesten Plan"
OHNE_DATUM = "ohne Datum"
OHNE_ANGABE = "ohne Angabe"
ZUGEORDNET = (EINDEUTIG, NUR_DIENSTSTELLE)
STATUS = (EINDEUTIG, NUR_DIENSTSTELLE, MEHRDEUTIG, KEIN_TREFFER, DEZERNAT_WEICHT_AB, NAME_WEICHT_AB, VOR_PLAN,
          OHNE_DATUM, OHNE_ANGABE)

DEZERNAT_ID = re.compile(r"^(?:OB|[IVX]+)$")
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STRICHE = re.compile(r"[‐‑‒–—−]")
_KLAMMER_AM_ENDE = re.compile(r"\s*\([^()]*\)\.?$")
# Name einer Organisation: Nummer der Dienststelle vorn („61 Stadtplanungsamt“, „61 - Stadtplanungsamt“, „612: …“)
_NUMMER_NAME = re.compile(r"^(?P<code>\d{2}(?:-\d)?(?:/\d{1,2})?|\d{3,4})(?:\s*[-:]\s*|\s+)(?P<rest>\S.*)$")
_NUMMER = re.compile(r"^(?:(?:Amt|Dienststelle)\s+)?(?P<code>\d{2}(?:-\d)?(?:/\d{1,2})?|\d{3,4})$")
_KENNUNG_NAME = re.compile(r"^(?P<code>(?:OB|[IVX]+)(?:\s*/\s*[0-9A-Z][0-9A-Z-]*)+)(?:(?:\s*[-:]\s*|\s+)(?P<rest>\S.*))?$")
_DEZERNAT = re.compile(r"^Dezernat\s+(?P<code>OB|[IVX]+)$")


def norm(text):
    """Vergleichsform eines Namens: Unicode NFC, Binde- und Gedankenstriche als „-“, Leerraum zusammengefasst, ohne
    Groß- und Kleinschreibung."""
    t = _STRICHE.sub("-", unicodedata.normalize("NFC", text or ""))
    return re.sub(r"\s+", " ", t).strip().casefold()


def lesen(pfad=None):
    """Zeilen der Tabelle als Dicts (Spalten SPALTEN); fehlt die Datei, eine leere Liste."""
    pfad = Path(pfad or TABELLE)
    if not pfad.exists():
        return []
    with open(pfad, encoding="utf-8", newline="") as f:
        zeilen = list(csv.DictReader(f, delimiter="\t"))
    if zeilen and tuple(zeilen[0]) != SPALTEN:
        raise ValueError(f"{pfad}: Spalten {tuple(zeilen[0])} statt {SPALTEN}")
    return zeilen


def label(eintrag):
    """Anzeige eines Eintrags: „61 Stadtplanungsamt“, „VI/2 Stabsstelle Wirtschaftsförderung“, „Dezernat VI –
    Stadtentwicklung, Wirtschaft, Planen und Bauen“ (Dezernat ohne Bereich im Plan: „Dezernat OB“)."""
    if eintrag["ebene"] == "dezernat":
        return f"Dezernat {eintrag['dezernat']}" + (f" – {eintrag['name']}" if eintrag["name"] else "")
    return f"{eintrag['dienststelle']} {eintrag['name']}".strip()


def stand_text(iso):
    """„2026-11-01“ → „01.11.2026“."""
    j, m, t = iso.split("-")
    return f"{t}.{m}.{j}"


class Plan:
    """Ein Plan (Zeilen mit demselben gueltig_ab): Einträge nach Nummer der Dienststelle (im Plan eindeutig), Dezernate
    und Namen (Vergleichsform → Einträge)."""

    def __init__(self, stand, zeilen):
        self.stand, self.zeilen = stand, zeilen
        self.dezernate = {z["dezernat"]: z for z in zeilen if z["ebene"] == "dezernat"}
        self.nummern, self.namen = {}, {}
        for i, z in enumerate(zeilen):
            if z["ebene"] != "dezernat":
                if z["dienststelle"] in self.nummern:
                    raise ValueError(f"Plan {stand}: Nummer {z['dienststelle']} doppelt")
                self.nummern[z["dienststelle"]] = z
            for n in self._namen(z):
                self.namen.setdefault(n, {})[i] = z

    @staticmethod
    def _namen(z):
        """Vergleichsformen, unter denen ein Eintrag gefunden wird: Name, Name ohne Klammerzusätze am Ende („(e. E.)“,
        „(DigIT)“), Kurzname; beim Dezernat „Dezernat VI“ und sein Bereich."""
        namen = set()
        if z["name"]:
            namen.add(norm(z["name"]))
            ohne = z["name"]
            while _KLAMMER_AM_ENDE.search(ohne):
                ohne = _KLAMMER_AM_ENDE.sub("", ohne)
            if ohne:
                namen.add(norm(ohne))
        if z["kurzname"]:
            namen.add(norm(z["kurzname"]))
        if z["ebene"] == "dezernat":
            namen.add(norm(f"Dezernat {z['dezernat']}"))
        return namen

    def nach_name(self, name):
        treffer = list((self.namen.get(norm(name)) or {}).values())
        if len(treffer) == 1:
            return EINDEUTIG, treffer[0]
        return (MEHRDEUTIG if treffer else KEIN_TREFFER), None

    def nach_kennung(self, kennung):
        """(Status, Eintrag) für eine Kennung wie im Kopf der Vorlage."""
        k = re.sub(r"\s+", "", kennung).upper()
        teile = k.split("/")
        dez = teile[0]
        if dez not in self.dezernate or "" in teile:
            return KEIN_TREFFER, None
        if len(teile) == 1:
            return EINDEUTIG, self.dezernate[dez]

        def passt(z, status=EINDEUTIG):
            return (status, z) if z["dezernat"] == dez else (DEZERNAT_WEICHT_AB, None)

        ganz = self.nummern.get(k)   # Einheit des Dezernats in der Schreibweise des Plans („II/2“)
        if ganz and ganz["ebene"] == "dezernatseinheit":
            return passt(ganz)
        rest = self.nummern.get("/".join(teile[1:]))   # „VI/61“, „II/II/2“, „IV/51/1“
        if rest:
            return passt(rest)
        if len(teile) >= 3:
            unter = self.nummern.get("/".join(teile[2:]))   # „VI/61/612“
            if unter and unter["uebergeordnet"] == teile[1]:
                return passt(unter)
            ds = self.nummern.get(teile[1])
            if ds and ds["ebene"] == "dienststelle":
                return passt(ds, NUR_DIENSTSTELLE)
        return KEIN_TREFFER, None

    def nach_organisation(self, name):
        """(Status, Eintrag) für den Namen einer Organisation (Formen siehe Modulbeschreibung)."""
        s = re.sub(r"\s+", " ", _STRICHE.sub("-", unicodedata.normalize("NFC", name))).strip()
        if m := _DEZERNAT.match(s):
            return self.nach_kennung(m["code"])
        if m := _NUMMER.match(s):
            z = self.nummern.get(m["code"])
            return (EINDEUTIG, z) if z else (KEIN_TREFFER, None)
        for muster, nach in ((_KENNUNG_NAME, self.nach_kennung), (_NUMMER_NAME, self._nach_nummer)):
            if m := muster.match(s):
                status, z = nach(m["code"])
                if z is None or not m["rest"]:
                    return status, z
                return (status, z) if norm(m["rest"]) in self._namen(z) else (NAME_WEICHT_AB, None)
        return self.nach_name(s)

    def _nach_nummer(self, code):
        z = self.nummern.get(code)
        return (EINDEUTIG, z) if z else (KEIN_TREFFER, None)


class Tabelle:
    """Alle Pläne der Tabelle, nach Stand sortiert."""

    def __init__(self, zeilen):
        gruppen = {}
        for z in zeilen:
            gruppen.setdefault(z["gueltig_ab"], []).append(z)
        self.plaene = [Plan(s, gruppen[s]) for s in sorted(gruppen)]

    def plan(self, datum):
        """Plan, der am Datum gilt (Stand ≤ Datum, der jüngste davon), sonst None."""
        tag = (datum or "")[:10]
        gilt = [p for p in self.plaene if p.stand <= tag]
        return gilt[-1] if gilt else None

    def zuordnen(self, name=None, kennung=None, datum=None):
        """Zuordnung einer Federführung: {status, methode („kennung“ oder „name“), stand (gueltig_ab des Plans oder
        None), eintrag (Zeile der Tabelle oder None)}. Hat die Angabe eine Kennung, zählt sie vor dem Namen."""
        methode = "kennung" if kennung else "name" if name else None
        aus = {"status": OHNE_ANGABE, "methode": methode, "stand": None, "eintrag": None}
        if not methode:
            return aus
        tag = (datum or "")[:10]
        if not _DATUM.match(tag):
            return {**aus, "status": OHNE_DATUM}
        plan = self.plan(tag)
        if plan is None:
            return {**aus, "status": VOR_PLAN}
        status, z = plan.nach_kennung(kennung) if kennung else plan.nach_organisation(name)
        return {**aus, "status": status, "stand": plan.stand, "eintrag": z}

    def dezernat(self, stand, dez):
        return next(p for p in self.plaene if p.stand == stand).dezernate[dez]


@lru_cache(maxsize=4)
def tabelle(pfad=None):
    """Tabelle aus data/aemter/aemter_koeln.tsv (einmal je Pfad gelesen)."""
    return Tabelle(lesen(pfad))


def zuordnen(name=None, kennung=None, datum=None, pfad=None):
    """Zuordnung mit der Tabelle aus dem Repository (Tabelle.zuordnen)."""
    return tabelle(pfad).zuordnen(name=name, kennung=kennung, datum=datum)


def fundstelle(eintrag):
    """„Geschäfts- und Dezernatsverteilungsplan der Stadt Köln, Stand 01.11.2026, Seite 1, Spalte Dezernat VI,
    Eintrag 12“."""
    return f"{TITEL}, Stand {stand_text(eintrag['gueltig_ab'])}, {eintrag['fundstelle']}"


def fuer_export(ergebnis, pfad=None):
    """Angaben einer Zuordnung für den Export (`responsibility[].aemtertabelle`): bei einem Treffer Kennung, Dezernat
    (mit Bereich), Dienststelle, Name, Ebene, übergeordnete Dienststelle, Fundstelle und Adresse des Plans; sonst nur
    Status, Methode und – falls ein Plan galt – sein Stand."""
    aus = {"status": ergebnis["status"], "methode": ergebnis["methode"]}
    if ergebnis["stand"]:
        aus["stand"] = ergebnis["stand"]
    z = ergebnis["eintrag"]
    if ergebnis["status"] not in ZUGEORDNET or z is None:
        return aus
    t = tabelle(pfad)
    dez = t.dezernat(z["gueltig_ab"], z["dezernat"])
    plan = next(p for p in t.plaene if p.stand == z["gueltig_ab"])
    ober = plan.nummern.get(z["uebergeordnet"]) if z["uebergeordnet"] else None
    aus.update({"kennung": z["kennung"], "dezernat": z["dezernat"], "dezernat_name": dez["name"],
                "dienststelle": z["dienststelle"], "name": z["name"], "ebene": z["ebene"], "label": label(z),
                "dezernat_label": label(dez), "fundstelle": fundstelle(z), "quelle": z["quelle"]})
    if ober:
        aus["uebergeordnet"] = {"dienststelle": ober["dienststelle"], "name": ober["name"], "label": label(ober)}
    return aus


def zuordnung_federfuehrung(r, datum, pfad=None):
    """Zuordnung einer Zeile der Federführung (kind „federfuehrend“) aus dem Export: Kennung aus dem Kopf der Vorlage
    (Spalte `kennung`, Schritt „Dokumente“), sonst der Name der Organisation aus `underDirectionOf` (`name`)."""
    return zuordnen(name=r.get("name"), kennung=r.get("kennung"), datum=datum, pfad=pfad)
