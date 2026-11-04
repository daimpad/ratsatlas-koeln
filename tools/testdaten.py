"""Synthetische Testdaten für Entwicklung und Prüfung der Seite, solange die Kölner OParl-API nicht abgerufen wird.

Aufruf: python3 tools/testdaten.py [--anzahl 300]
Schreibt Rohdateien im Format des SessionNet-Adapters nach data/raw/ (nicht versioniert). Alle Vorlagen sind erfunden;
jeder Titel beginnt mit „[Testdaten]“, die IDs zeigen auf https://example.invalid/. Straßen- und Stadtteilnamen stammen
aus den Kölner Geodaten in data/geo, damit die Verortung realistisch geprüft werden kann. Nie veröffentlichen.
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

B = "https://example.invalid/oparl"
VORHABEN = ["Umgestaltung der {s}", "Sanierung der Fahrbahn {s}", "Neue Fahrradabstellanlagen an der {s}",
            "Verkehrsberuhigung {s} in {t}", "Baumpflanzungen in der {s}", "Spielplatz in {t}",
            "Sanierung der Grundschule in {t}", "Bürgerhaus {t}: Erweiterung", "Parkraumkonzept {t}",
            "Barrierefreie Haltestelle {s}", "Kita-Neubau {s} {nr}", "Radverkehrskonzept Stadtbezirk {b}",
            "Haushaltssatzung 2027", "Bericht zur Luftqualität", "Digitalisierung der Schulen"]
ERGEBNISSE = ["ungeändert beschlossen", "geändert beschlossen", "Kenntnis genommen", "vertagt", "abgelehnt",
              "zurückgezogen"]
FRAKTIONEN = ["SPD", "CDU", "GRÜNE", "FDP", "Die Linke", "Volt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anzahl", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261104)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    strassen = json.loads(config.STRASSEN.read_text())["streets"]
    hnr = json.loads(config.HAUSNUMMERN.read_text())["punkte"]
    teile = [f["properties"] for f in json.loads(config.ORTSTEILE.read_text())["features"]]
    mit_nr = [s for s in strassen if s in hnr]

    orgs = [{"id": f"{B}/organizations/rat", "name": "Rat", "organizationType": "Gremium"},
            {"id": f"{B}/organizations/avr", "name": "Ausschuss für Verkehr und Mobilität", "organizationType": "Gremium"},
            {"id": f"{B}/organizations/bab", "name": "Ausschuss für Bürgerbeteiligung, Anregungen und Beschwerden",
             "organizationType": "Gremium"}]
    orgs += [{"id": f"{B}/organizations/bv{nr}", "name": f"Bezirksvertretung {nr} ({name})", "organizationType": "Gremium"}
             for nr, name in BEZIRKE_KOELN.items()]
    heute = date(2026, 11, 4)
    meetings = {}

    def sitzung(org, tag):
        mid = f"{B}/meetings/{org['id'].rsplit('/', 1)[1]}-{tag.isoformat()}"
        if mid not in meetings:
            meetings[mid] = {"id": mid, "name": org["name"], "start": f"{tag.isoformat()}T17:00:00+01:00",
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
        papers.append({
            "id": f"{B}/papers/{i}", "reference": (f"AN/{1000 + i}/{tag.year}" if politisch else f"{2000 + i}/{tag.year}"),
            "name": f"[Testdaten] {titel}", "date": tag.isoformat(),
            "paperType": ("Antrag nach § 3 der Geschäftsordnung des Rates" if politisch
                          else "Anregungen und Beschwerden" if eingabe else rnd.choice(["Beschlussvorlage", "Mitteilung"])),
            "web": "https://example.invalid/vorlage", "modified": f"{tag.isoformat()}T10:00:00+01:00",
            "location": [{"id": f"{B}/locations/{i}", "subLocality": teil["ortsteil_bez"]}] if rnd.random() < 0.12 else [],
            "consultation": cons})

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


if __name__ == "__main__":
    main()
