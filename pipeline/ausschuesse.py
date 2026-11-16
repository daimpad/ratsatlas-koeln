"""Ausschüsse des Rates der Stadt Köln laut Zuständigkeitsordnung (§§ 7–23) und Abgleich mit den Gremiennamen.

Quelle: Zuständigkeitsordnung der Stadt Köln vom 02.06.2026 (ABl StK 2026, S. 173; öffentliche Bekanntmachung vom
16.06.2026), eine Satzung der Stadt (QUELLE; heruntergeladen am 16.11.2026, nur lokal gelesen, nicht im Repository).
Übernommen sind nur die Namen der Ausschüsse mit ihrem Paragrafen und andere Schreibungen desselben Ausschusses in
der Satzung (Inhaltsübersicht, Überschrift, Text); keine Auszüge. § 2 (Zuständigkeiten der Bezirksvertretungen) nennt
keine einzelne Bezirksvertretung; deren Namen stehen in geocode.BEZIRKE_KOELN (Hauptsatzung).

Die Namen der Organisationen in der OParl-API (SessionNet) können von der Satzung abweichen und sind erst nach dem
Vollabruf geprüft. Die Regeln, die Gremiennamen auswerten (Thema: topics.GREMIUM; Hauskoordinate und Titelmaske:
geocode.GREMIUM), behalten deshalb alle bisherigen Schreibweisen; Tests in tests/test_ausschuesse.py prüfen, dass
Name laut Satzung und bisherige Schreibweisen gleich behandelt werden. `python -m pipeline ausschuesse` vergleicht nach
dem Vollabruf die Organisationen der Datenbank mit dieser Liste (ohne Anfrage an die Stadt; schreibt nur
data/build/abgleich_ausschuesse.tsv). Fundstellen im Code und Texte: inventur/ausschuesse_zusto.tsv."""
import csv
import re
import sqlite3
import unicodedata

from . import config

QUELLE = {
    "titel": "Zuständigkeitsordnung der Stadt Köln vom 02.06.2026",
    "fundstelle": "ABl StK 2026, S. 173; öffentliche Bekanntmachung vom 16.06.2026",
    "url": "https://www.stadt-koeln.de/mediaasset/content/satzungen/zustaendigkeitsordnung_2026-06-02.pdf",
    "abgerufen": "2026-11-16",
    "sha256": "8804bd89c498321ca01540f4def0797a727f0cdcf9b319cf7f089bc39fd40ba6",
}

# (Paragraf, Name laut Inhaltsübersicht, andere Schreibungen desselben Ausschusses). Andere Schreibungen stehen in der
# Satzung selbst, mit Fundstelle im Kommentar; nur die Teile des Doppelnamens in § 13 sind abgeleitet.
AUSSCHUESSE = (
    (7, "Hauptausschuss", ()),
    (8, "Ausschuss Allgemeine Verwaltung und Rechtsfragen / Vergabe / Internationales",
     ("Ausschuss Allgemeine Verwaltung und Rechtsfragen",   # § 4 Abs. 3
      "Ausschuss AVR")),                                     # § 8 Abs. 2
    (9, "Ausschuss für Bauen und Wohnen", ()),
    (10, "Ausschuss Bürgerbeteiligung, Anregungen und Beschwerden", ()),
    (11, "Finanzausschuss", ()),
    (12, "Ausschuss für die Gleichstellung von Frauen und Männern", ()),
    (13, "Jugendhilfeausschuss - Ausschuss für Kinder, Jugend und Familie",
     ("Jugendhilfeausschuss", "Ausschuss für Kinder, Jugend und Familie")),   # Teile des Doppelnamens (abgeleitet)
    (14, "Ausschuss Klima, Umwelt und Grün", ("Ausschuss für Klima, Umwelt und Grün",)),   # Überschrift des § 14
    (15, "Ausschuss Kunst und Kultur", ()),
    (16, "Liegenschaftsausschuss", ()),
    (17, "Mobilitätsausschuss", ()),
    (18, "Rechnungsprüfungsausschuss", ()),
    (19, "Ausschuss Schule und Weiterbildung", ("Ausschuss für Schule und Weiterbildung",)),   # Überschrift des § 19
    (20, "Ausschuss Soziales, Gesundheit, Seniorinnen und Senioren", ()),
    (21, "Sportausschuss", ()),
    (22, "Ausschuss für Stadtentwicklung und regionale Zusammenarbeit", ()),
    (23, "Ausschuss für Wirtschaft und Digitalisierung", ()),
)


def schluessel(name):
    """Vergleichsschlüssel eines Gremiennamens: Unicode-Normalform NFKC, kleingeschrieben, Leerraum, Komma,
    Schrägstrich, Binde- und Gedankenstrich als ein Leerzeichen („Kinder-, Jugend“ wie „Kinder, Jugend“), ohne das Wort
    „für“: Die Satzung schreibt die Ausschüsse der §§ 14 und 19 in der Überschrift mit „für“, in Inhaltsübersicht und
    Text ohne. Für export.gremium_der_sitzung und abschnitt."""
    t = unicodedata.normalize("NFKC", name or "").lower()
    return " ".join(w for w in re.split(r"[\s,/\-‐-―]+", t) if w and w != "für")


_ABSCHNITT = {schluessel(n): nr for nr, name, andere in AUSSCHUESSE for n in (name, *andere)}


def abschnitt(name):
    """Paragraf der Zuständigkeitsordnung für einen Gremiennamen (Name laut Satzung oder andere Schreibung, gleicher
    Vergleichsschlüssel), sonst None."""
    return _ABSCHNITT.get(schluessel(name))


def abgleich(organisationen):
    """Abgleich der Organisationen (dicts mit id, name, short_name, classification) mit §§ 7–23. Je Ausschuss der
    Satzung eine Zeile je passender Organisation (Name oder Kurzname mit gleichem Vergleichsschlüssel): Befund „gleich“
    (Name wie in der Satzung, Leerraum zusammengefasst) oder „Schreibvariante“; ohne passende Organisation eine Zeile
    „fehlt in OParl“. Dazu jede Organisation mit „ausschuss“ im Namen ohne Paragrafen: „nur in OParl“ (etwa
    Unterausschüsse, Betriebsausschüsse, frühere Ausschüsse). Nur Namen von Gremien, keine Personen."""
    def eng(s):
        return re.sub(r"\s+", " ", s or "").strip()

    zeilen, zugeordnet = [], set()
    for nr, name, _ in AUSSCHUESSE:
        passend = [o for o in organisationen
                   if abschnitt(o.get("name")) == nr or (o.get("short_name") and abschnitt(o["short_name"]) == nr)]
        for o in sorted(passend, key=lambda o: (o.get("name") or "", o.get("id") or "")):
            zugeordnet.add(o.get("id"))
            befund = "gleich" if eng(o.get("name")) == name else "Schreibvariante"
            zeilen.append([f"§ {nr}", name, o.get("name") or "", o.get("short_name") or "",
                           o.get("classification") or "", o.get("id") or "", befund])
        if not passend:
            zeilen.append([f"§ {nr}", name, "", "", "", "", "fehlt in OParl"])
    for o in sorted(organisationen, key=lambda o: (o.get("name") or "", o.get("id") or "")):
        if o.get("id") not in zugeordnet and "ausschuss" in (o.get("name") or "").lower():
            zeilen.append(["", "", o.get("name") or "", o.get("short_name") or "", o.get("classification") or "",
                           o.get("id") or "", "nur in OParl"])
    return zeilen


SPALTEN = ["paragraf", "name_zusto", "name_oparl", "kurzname_oparl", "classification", "id", "befund"]


def abgleich_schreiben(db_pfad=None, ziel=None):
    """Schritt `ausschuesse` (nach build, ohne Netz): Organisationen der Datenbank gegen §§ 7–23 als TSV nach
    data/build/abgleich_ausschuesse.tsv (nicht veröffentlicht); Zählung der Befunde im Log."""
    db_pfad, ziel = db_pfad or config.DB, ziel or config.BUILD / "abgleich_ausschuesse.tsv"
    if not db_pfad.exists():
        raise SystemExit(f"{db_pfad} fehlt: zuerst `python -m pipeline build`.")
    with sqlite3.connect(db_pfad) as db:
        orgs = [dict(zip(("id", "name", "short_name", "classification"), r))
                for r in db.execute("SELECT id, name, short_name, classification FROM organization")]
    zeilen = abgleich(orgs)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(SPALTEN)
        w.writerows(zeilen)
    zahl = {}
    for z in zeilen:
        zahl[z[-1]] = zahl.get(z[-1], 0) + 1
    print(f"Ausschüsse laut {QUELLE['titel']} gegen {len(orgs)} Organisationen: "
          + ", ".join(f"{k} {v}" for k, v in sorted(zahl.items())) + f" → {ziel}")
    return zeilen
