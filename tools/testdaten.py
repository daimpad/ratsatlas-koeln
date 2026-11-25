"""Synthetische Testdaten für Entwicklung und Prüfung der Seite, solange die Kölner OParl-API nicht abgerufen wird.

Aufruf: python3 tools/testdaten.py [--anzahl 300] [--themen]
Schreibt Rohdateien im Format des SessionNet-Adapters nach data/raw/ (nicht versioniert). Alle Vorlagen sind erfunden;
jeder Titel beginnt mit „[Testdaten]“, die IDs zeigen auf https://example.invalid/. Straßen- und Stadtteilnamen stammen
aus den Kölner Geodaten in data/geo, damit die Verortung realistisch geprüft werden kann. Nie veröffentlichen.

--themen (Themenseiten, Prüfung im Browser): ergänzt nach den übrigen Testdaten, mit eigenem Zufallsgenerator, den
Mobilitätsausschuss (§ 17 der Zuständigkeitsordnung) und den Hauptausschuss (§ 7), erfundene Vorlagen zum Verkehr mit
Fallen, Folgen über Bezirksvertretung, Ausschuss und Rat, Eingaben nach § 24 GO NRW, zwei Ketten mit sub- und
superordinatedPaper, eine Beratung in einem aufgelösten Gremium und Sitzungen relativ zum heutigen Tag (je eine mit
„entfällt“ und „verschoben“ im Namen). Ohne die Option bleiben die Testdaten unverändert; mit ihr ändern sie sich mit
dem Tag (Sitzungen relativ zu heute).
"""
import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import config, sessionnet  # noqa: E402
from pipeline.fetch import _write  # noqa: E402
from pipeline.geocode import BEZIRKE_KOELN  # noqa: E402
from pipeline.process import BERLIN  # noqa: E402

B = "https://example.invalid/oparl"
VORHABEN = ["Umgestaltung der {s}", "Sanierung der Fahrbahn {s}", "Neue Fahrradabstellanlagen an der {s}",
            "Verkehrsberuhigung {s} in {t}", "Baumpflanzungen in der {s}", "Spielplatz in {t}",
            "Sanierung der Grundschule in {t}", "Bürgerhaus {t}: Erweiterung", "Parkraumkonzept {t}",
            "Barrierefreie Haltestelle {s}", "Kita-Neubau {s} {nr}", "Radverkehrskonzept Stadtbezirk {b}",
            "Haushaltssatzung 2027", "Bericht zur Luftqualität", "Digitalisierung der Schulen"]
ERGEBNISSE = ["ungeändert beschlossen", "geändert beschlossen", "Kenntnis genommen", "vertagt", "abgelehnt",
              "zurückgezogen"]
FRAKTIONEN = ["SPD", "CDU", "GRÜNE", "FDP", "Die Linke", "Volt"]
# Federführende Dienststellen (underDirectionOf) für einen Teil der Verwaltungsvorlagen, in verschiedenen Schreibweisen
# des Namens, damit die Zuordnung zur Ämtertabelle (pipeline/aemter.py) alle Fälle durchläuft: Nummer und Name, Name
# allein, Kennung und Name, mehrdeutiger Name, Nummer mit anderem Namen, unbekannte Dienststelle. Köln füllt
# underDirectionOf nicht (vollständiger Abruf zum 17.11.2026: bei keiner Vorlage); die Testdaten weichen hier und bei
# auxiliaryFile bewusst ab (TECHNIK.md, „Dokumente (PDF-Köpfe)“, zurückgestellt aus der Prüfung stj). Die Dienststellen
# haben weder organizationType noch classification und stehen deshalb nicht in gremien.json
DIENSTSTELLEN = ["61 Stadtplanungsamt", "Amt für Straßen und Radwegebau", "Amt für Kinder, Jugend und Familie",
                 "Umwelt- und Verbraucherschutzamt", "VIII/67 Amt für Landschaftspflege und Grünflächen", "Verwaltung",
                 "52 Kulturamt", "[Testdaten] Dienststelle ohne Eintrag"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anzahl", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261104)
    ap.add_argument("--themen", action="store_true", help="Vorlagen und Gremien für die Themenseiten ergänzen")
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    strassen = json.loads(config.STRASSEN.read_text())["streets"]
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    teile = [f["properties"] for f in json.loads(config.ORTSTEILE.read_text())["features"]]
    mit_nr = [s for s in strassen if s in hnr]
    # Plannummern aus data/geo (Landesschnittstelle); eigener Zufallsgenerator, damit die übrigen Titel gleich bleiben
    rp = random.Random(a.seed + 1)
    plaene = sorted({f["properties"]["name"].split(" ")[0] for f in json.loads(config.BPLAN.read_text())["features"]}
                    if config.BPLAN.exists() else set())

    # Gremien in der Kölner Form (Stufe 3, 09.11.2026): `classification` statt organizationType, das in Köln bei allen
    # fehlt (pipeline/gremien.py). Der Ausschuss für Verkehr und Mobilität hat keinen Paragrafen der
    # Zuständigkeitsordnung (übrige Gremien), der für Bürgerbeteiligung den des § 10. Dazu zwei erfundene Organisationen
    # ohne Sitzung und ohne Beratung: eine Fraktion (nicht in gremien.json) und ein Ausschuss der früheren Wahlperiode
    # mit endDate (aufgelöst)
    ausschuss = "Fachausschüsse und weitere Gremien"
    orgs = [{"id": f"{B}/organizations/rat", "name": "Rat", "classification": "Rat"},
            {"id": f"{B}/organizations/avr", "name": "Ausschuss für Verkehr und Mobilität", "classification": ausschuss},
            {"id": f"{B}/organizations/bab", "name": "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden",
             "classification": ausschuss}]
    orgs += [{"id": f"{B}/organizations/bv{nr}", "name": f"Bezirksvertretung {nr} ({name})",
              "classification": "Bezirksvertretungen"} for nr, name in BEZIRKE_KOELN.items()]
    orgs += [{"id": f"{B}/organizations/fr1", "name": "[Testdaten] Probefraktion", "classification": "Fraktionen und Gruppen"},
             {"id": f"{B}/organizations/alt1", "name": "[Testdaten] Probeausschuss der früheren Wahlperiode",
              "classification": ausschuss, "startDate": "2020-11-01", "endDate": "2025-10-31"}]
    verwaltung = [{"id": f"{B}/organizations/dst{k}", "name": name} for k, name in enumerate(DIENSTSTELLEN, 1)]
    orgs += verwaltung
    # eigener Zufallsgenerator (wie rp), damit die übrigen Testdaten gleich bleiben
    ra = random.Random(a.seed + 2)
    heute = date(2026, 11, 4)
    meetings = {}

    def sitzung(org, tag):
        mid = f"{B}/meetings/{org['id'].rsplit('/', 1)[1]}-{tag.isoformat()}"
        if mid not in meetings:
            # Beginn um 17:00 Uhr Kölner Zeit mit dem Versatz des Tages, im Sommer +02:00
            # (Entscheidung 19.11.2026 (2) (b))
            beginn = datetime(tag.year, tag.month, tag.day, 17, 0, tzinfo=BERLIN).isoformat()
            meetings[mid] = {"id": mid, "name": org["name"], "start": beginn,
                             "organization": [org["id"]], "agendaItem": [], "web": "https://example.invalid/sitzung",
                             "modified": f"{tag.isoformat()}T08:00:00+01:00"}
        return meetings[mid]

    papers = []
    for i in range(1, a.anzahl + 1):
        tag = heute - timedelta(days=rnd.randint(-20, 700))
        teil = rnd.choice(teile)
        s = rnd.choice(mit_nr)
        lage = rnd.choice(list(hnr[s]))
        nr = rnd.choice(list(hnr[s][lage]))
        vorlage = rnd.choice(VORHABEN)
        politisch = rnd.random() < 0.35
        eingabe = not politisch and rnd.random() < 0.08
        titel = vorlage.format(s=s, t=teil["ortsteil_bez"], b=teil["bezirk_bez"], nr=nr)
        if plaene and not politisch and not eingabe and rp.random() < 0.06:
            titel = f"Bebauungsplan {rp.choice(plaene)}: {rp.choice(['Satzungsbeschluss', 'Aufstellungsbeschluss zur Änderung', 'Teilaufhebung'])}"
        if eingabe:
            titel = f"Anregung nach § 24 GO NRW: {s} {nr}"
        if politisch:
            titel = f"Antrag der {rnd.choice(FRAKTIONEN)}-Fraktion betreffend {titel}"
        bezirk = next(t["bezirk_bez"] for t in teile if t["ortsteil_bez"] == lage)
        bv = next(o for o in orgs if o["name"].endswith(f"({bezirk})"))
        folge = [bv] + ([orgs[1], orgs[0]] if rnd.random() < 0.5 else [orgs[0]])
        if eingabe:
            folge = [orgs[2]]
        cons = []
        for k, org in enumerate(folge):
            t = tag + timedelta(days=14 + 21 * k)
            m = sitzung(org, t)
            top_id = f"{m['id']}/top/{len(m['agendaItem']) + 1}"
            ergebnis = rnd.choice(ERGEBNISSE) if t <= heute else None
            m["agendaItem"].append({"id": top_id, "number": f"{len(m['agendaItem']) + 1}", "name": titel[:80],
                                    "result": ergebnis, "public": True})
            cons.append({"id": f"{B}/consultations/{i}-{k}", "meeting": m["id"], "agendaItem": top_id,
                         "organization": [org["id"]], "role": "Entscheidung" if k == len(folge) - 1 else "Beratung",
                         "authoritative": k == len(folge) - 1})
        federfuehrend = ra.choice(verwaltung) if ra.random() < 0.5 and not politisch and not eingabe else None
        papers.append({
            **({"underDirectionOf": [federfuehrend["id"]]} if federfuehrend else {}),
            "id": f"{B}/papers/{i}", "reference": (f"AN/{1000 + i}/{tag.year}" if politisch else f"{2000 + i}/{tag.year}"),
            "name": f"[Testdaten] {titel}", "date": tag.isoformat(),
            "paperType": ("Antrag nach § 3 der Geschäftsordnung des Rates" if politisch
                          else "Anregungen und Beschwerden" if eingabe else rnd.choice(["Beschlussvorlage", "Mitteilung"])),
            "web": "https://example.invalid/vorlage", "modified": f"{tag.isoformat()}T10:00:00+01:00",
            "location": [{"id": f"{B}/locations/{i}", "subLocality": teil["ortsteil_bez"]}] if rnd.random() < 0.12 else [],
            "consultation": cons})

    if a.themen:
        themen(random.Random(a.seed + 3), orgs, meetings, papers, mit_nr, teile)

    config.RAW.mkdir(parents=True, exist_ok=True)
    meetings = list(meetings.values())
    _write(config.PAPERS, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in papers))
    _write(config.ORGANIZATIONS, json.dumps(orgs, ensure_ascii=False))
    keep = ("id", "name", "meetingState", "cancelled", "start", "end", "organization", "web")
    _write(config.MEETINGS, json.dumps([{**{k: m.get(k) for k in keep}, "agenda_items": len(m["agendaItem"])}
                                        for m in meetings], ensure_ascii=False))
    _write(config.LEGISLATIVE_TERMS, json.dumps([{"id": f"{B}/terms/1", "name": "2025–2030", "startDate": "2025-11-01"}]))
    if config.BERATUNGEN.exists():
        config.BERATUNGEN.unlink()
    sessionnet.beratungen(papers, meetings)
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write(config.STAND, json.dumps({"papers": jetzt, "meetings": jetzt, "organizations": jetzt, "testdaten": True},
                                    indent=1) + "\n")
    print(f"Testdaten: {len(papers)} Vorlagen, {len(meetings)} Sitzungen → {config.RAW}")


# Vorlagen für die Themenseiten (--themen): (Titel, Vorlagenart, Folge der Gremien je Sitzung, Kennung der Kette).
# Folge: Schlüssel der Sitzungen aus THEMEN_SITZUNGEN; Titel mit {s} (Straße), {t} (Stadtteil), {b} (Stadtbezirk).
# Fallen ohne Zuordnung: Ausschluss, Wörter ohne Verkehrsbezug, Adresse mit „Straße“, mehrdeutige Wörter ohne
# Mobilitätsausschuss, Haushalt und Personalien nur im Ausschuss, abgesagte Sitzung als einzige Beratung
BV_A, BV_B = "bv1", "bv2"
THEMEN_SITZUNGEN = {
    # Schlüssel: (Organisation, Tage relativ zu heute, Zusatz im Namen)
    "mob_a": ("mob", -60, ""), "mob_b": ("mob", -20, ""), "mob_c": ("mob", 7, ""),
    "mob_x": ("mob", 14, " - Sitzung entfällt"), "mob_d": ("mob", 35, ""),
    "ha_a": ("ha", -30, ""), "ha_b": ("ha", 10, " - verschoben"),
    "rat_a": ("rat", -25, ""), "rat_b": ("rat", 17, ""),
    "bv_a1": (BV_A, -45, ""), "bv_a2": (BV_A, 5, ""), "bv_b1": (BV_B, -40, ""), "bv_b2": (BV_B, 12, ""),
    "bab_a": ("bab", -35, ""), "alt_a": ("alt1", -70, ""),
}
VERWALTUNG, MITTEILUNG = "Beschlussvorlage", "Mitteilung"
ANTRAG, ANFRAGE = "Antrag nach § 3 der Geschäftsordnung des Rates", "Anfrage nach § 4 der Geschäftsordnung des Rates"
EINGABE = "Anregungen und Beschwerden"
THEMEN_VORLAGEN = [
    ("Bewohnerparken in {t}", VERWALTUNG, ["bv_a1", "mob_b", "rat_b"], None),
    ("Parkraumbewirtschaftung an der {s}", ANTRAG, ["bv_b1", "mob_c"], None),
    ("Barrierefreier Ausbau der Haltestelle {s}", VERWALTUNG, ["bv_a1", "mob_b", "rat_a"], None),
    ("Taktverdichtung der Linie 13", ANTRAG, ["mob_b", "ha_b"], None),
    ("Stadtbahn: Planung der Verlängerung nach {t}", VERWALTUNG, ["mob_a", "ha_a", "rat_a"], None),
    ("Fahrradabstellanlagen am Bahnhof {t}", VERWALTUNG, ["bv_b1", "mob_c"], None),
    ("Radweg an der {s}", ANTRAG, ["bv_a1", "mob_b", "rat_b"], None),
    ("Neuer Zebrastreifen an der {s}", VERWALTUNG, ["bv_b2"], None),
    ("Gehweg an der {s}: Sanierung", MITTEILUNG, ["bv_a2"], None),
    ("Tempo 30 vor der Grundschule in {t}", ANTRAG, ["bv_b1", "mob_b", "rat_a"], None),
    ("Verkehrsberuhigung in {t}", VERWALTUNG, ["bv_a1", "mob_x", "mob_d"], None),
    ("Schulwegsicherung in {t}", ANFRAGE, ["mob_c"], None),
    ("Kreisverkehr an der {s}", VERWALTUNG, ["bv_b1", "mob_b", "ha_b", "rat_b"], None),
    ("Fahrbahnerneuerung der {s}", MITTEILUNG, ["bv_a1"], None),
    ("Brücke über die {s}: Prüfbericht", VERWALTUNG, ["alt_a", "mob_a", "rat_a"], None),
    ("Mobilitätskonzept für {t}", VERWALTUNG, ["bv_b1", "mob_c", "rat_b"], None),
    ("Ladeinfrastruktur im Stadtbezirk {b}", ANTRAG, ["bv_a2"], None),
    ("Umgestaltung des Platzes an der {s}", VERWALTUNG, ["bv_a1", "mob_b"], None),
    ("Umgestaltung des Platzes vor der Kirche in {t}", VERWALTUNG, ["bv_b1"], None),
    ("Sachstand der Planung", MITTEILUNG, ["mob_c"], None),
    ("Sachstand der Planung im Stadtbezirk {b}", MITTEILUNG, ["mob_x"], None),
    ("Haushaltsplanentwurf 2027: Teilplan des Ausschusses", VERWALTUNG, ["mob_b", "rat_b"], None),
    ("Umbesetzung in Ausschüssen", ANTRAG, ["mob_c", "rat_b"], None),
    ("Verkehrswertgutachten für ein Grundstück in {t}", VERWALTUNG, ["bv_a1", "rat_a"], None),
    ("Mobilfunkmast an der {s}", MITTEILUNG, ["bv_b2"], None),
    ("Fußballplatz in {t}: Kunstrasen", VERWALTUNG, ["bv_b1", "rat_a"], None),
    ("Bahnhofsmission: Zuschuss", VERWALTUNG, ["rat_a"], None),
    ("Richtlinie zur Förderung der Kultur", VERWALTUNG, ["rat_a"], None),
    ("Riesenrad auf dem Weihnachtsmarkt in {t}", MITTEILUNG, ["bv_a1"], None),
    ("Kita-Neubau an der {s}", VERWALTUNG, ["bv_b1", "rat_a"], None),
    ("Anregung nach § 24 GO NRW: Tempo 30 in der {s}", EINGABE, ["bab_a", "bv_a2"], None),
    ("Anregung nach § 24 GO NRW: Radweg im Stadtteil {t}", EINGABE, ["bab_a"], None),
    ("Radverkehrskonzept für den Stadtbezirk {b}", VERWALTUNG, ["bv_a1", "mob_a", "rat_a"], "k1"),
    ("Ergänzung zur Vorlage: Zeitplan", VERWALTUNG, ["mob_b", "rat_b"], "k1"),
    ("Stellungnahme der Verwaltung zum Zeitplan", "Stellungnahme der Verwaltung", ["mob_c"], "k1"),
    ("Antrag betreffend Lieferzonen in {t}", ANTRAG, ["bv_b1", "mob_b"], "k2"),
    ("Änderung zum Antrag", "Änderungsantrag", ["mob_c", "ha_b"], "k2"),
]


def themen(rt, orgs, meetings, papers, strassen, teile):
    """Testdaten für die Themenseiten (Option --themen), an die übrigen angehängt: zwei Ausschüsse mit Paragrafen,
    Sitzungen relativ zu heute (THEMEN_SITZUNGEN), Vorlagen aus THEMEN_VORLAGEN mit Beratungen und Ergebnissen, Ketten
    über sub- und superordinatedPaper (k1 mit beiden Richtungen, k2 nur mit superordinatedPaper)."""
    ausschuss = "Fachausschüsse und weitere Gremien"
    orgs += [{"id": f"{B}/organizations/mob", "name": "Mobilitätsausschuss", "classification": ausschuss},
             {"id": f"{B}/organizations/ha", "name": "Hauptausschuss", "classification": ausschuss}]
    je_org = {o["id"].rsplit("/", 1)[1]: o for o in orgs}
    hier = date.today()
    sitzungen = {}
    for k, (org, tage, zusatz) in THEMEN_SITZUNGEN.items():
        tag = hier + timedelta(days=tage)
        beginn = datetime(tag.year, tag.month, tag.day, 16, 30, tzinfo=BERLIN).isoformat()
        mid = f"{B}/meetings/th-{k}-{tag.isoformat()}"
        sitzungen[k] = meetings[mid] = {"id": mid, "name": je_org[org]["name"] + zusatz, "start": beginn,
                                        "organization": [je_org[org]["id"]], "agendaItem": [],
                                        "web": "https://example.invalid/sitzung",
                                        "modified": f"{hier.isoformat()}T08:00:00+01:00", "_tag": tag}
    erste, ketten = len(papers) + 1, {}
    for j, (titel, art, folge, kette) in enumerate(THEMEN_VORLAGEN):
        i = erste + j
        teil = rt.choice(teile)
        name = "[Testdaten] " + titel.format(s=rt.choice(strassen), t=teil["ortsteil_bez"], b=teil["bezirk_bez"])
        tag = min(sitzungen[k]["_tag"] for k in folge) - timedelta(days=rt.randint(8, 20))
        politisch = "antrag" in art.lower() or "anfrage" in art.lower()
        cons = []
        for n, k in enumerate(folge):
            m = sitzungen[k]
            top_id = f"{m['id']}/top/{len(m['agendaItem']) + 1}"
            m["agendaItem"].append({"id": top_id, "number": f"{len(m['agendaItem']) + 1}", "name": name[:80],
                                    "result": rt.choice(ERGEBNISSE[:3]) if m["_tag"] <= hier else None, "public": True})
            cons.append({"id": f"{B}/consultations/th-{i}-{n}", "meeting": m["id"], "agendaItem": top_id,
                         "organization": list(m["organization"]), "role": "Entscheidung" if n == len(folge) - 1
                         else "Beratung", "authoritative": n == len(folge) - 1})
        p = {"id": f"{B}/papers/{i}", "reference": f"{'AN/' if politisch else ''}{5000 + j}/{tag.year}", "name": name,
             "date": tag.isoformat(), "paperType": art, "web": "https://example.invalid/vorlage",
             "modified": f"{tag.isoformat()}T10:00:00+01:00",
             "location": [{"id": f"{B}/locations/{i}", "subLocality": teil["ortsteil_bez"]}] if rt.random() < 0.3 else [],
             "consultation": cons}
        if kette:
            vorher = ketten.get(kette)
            if vorher:   # untergeordnet unter die vorige Vorlage der Kette; k1 in beiden Richtungen, k2 nur von unten
                p["superordinatedPaper"] = [vorher["id"]]
                if kette == "k1":
                    vorher.setdefault("subordinatedPaper", []).append(p["id"])
            ketten[kette] = p
        papers.append(p)
    for m in sitzungen.values():
        del m["_tag"]


if __name__ == "__main__":
    main()
