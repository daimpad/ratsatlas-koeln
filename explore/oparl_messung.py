"""Messung der Kölner OParl-API (Phase 1) – NUR nach Information der Stadt ausführen.

Aufruf (Reihenfolge):
  RATSATLAS_STADT_INFORMIERT=ja RATSATLAS_KONTAKT=<mail> python3 explore/oparl_messung.py kennzahlen
  ... python3 explore/oparl_messung.py organisationen
  ... python3 explore/oparl_messung.py stichprobe [--seiten 3] [--von 2019] [--bis 2026]
  ... python3 explore/oparl_messung.py sitzungen [--seiten 2]
  ... python3 explore/oparl_messung.py pdf-koepfe [--anzahl 100]
Ohne RATSATLAS_STADT_INFORMIERT=ja bricht jedes Kommando vor der ersten Anfrage ab (Entscheidung 04.11.2026).
Abruf über explore/abruf.py (eine Verbindung, Abstand ≥ 2 s, Backoff, Cache, Protokoll).
Paginierung nur über links.next, nie über konstruierte Seitennummern (HTTP 401 bei hohen Seitenzahlen).
Ergebnisse als TSV unter explore/ergebnisse/; Rohdaten und PDFs bleiben im Cache (nicht im Repository).
Aus PDFs werden nur abgeleitete Kennungen (Dezernat/Dienststelle) und Trefferarten gespeichert, keine Textauszüge.
"""
import argparse
import collections
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from abruf import Abbruch, hole  # noqa: E402

SYSTEM = os.environ.get("RATSATLAS_OPARL_SYSTEM", "https://buergerinfo.stadt-koeln.de/oparl/system")
BODY = os.environ.get("RATSATLAS_OPARL_BODY", "https://buergerinfo.stadt-koeln.de/oparl/bodies/stadtverwaltung_koeln")
ERG = Path(os.environ.get("RATSATLAS_ERGEBNISSE", Path(__file__).resolve().parent / "ergebnisse"))

RE_AN = re.compile(r"^AN/\d{1,4}/\d{4}$")
RE_VV = re.compile(r"^\d{1,4}/\d{4}$")
# Kopf der Verwaltungsvorlagen: „Dezernat, Dienststelle“ gefolgt von einer Kennung wie „II/II/2“ oder „VI/61“
RE_DEZ = re.compile(r"Dezernat\s*,\s*Dienststelle\s*[:\s]*([IVX]+(?:\s*/\s*[0-9IVX]+){0,3}(?:\s*/\s*\d+)?)")
RE_DEZ_LOSE = re.compile(r"Dezernat\s*,?\s*Dienststelle", re.I)


def _json(url, **params):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    return json.loads(hole(url, ".json"))


def _wert(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _schreibe(name, zeilen):
    ERG.mkdir(parents=True, exist_ok=True)
    spalten = list(dict.fromkeys(k for z in zeilen for k in z))
    with (ERG / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, spalten, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for z in zeilen:
            w.writerow({k: str(v).replace("\t", " ").replace("\n", " ") for k, v in z.items()})
    print(f"→ {ERG / name} ({len(zeilen)} Zeilen)")


def _seiten(url, max_seiten=None, **params):
    """Folgt links.next; liefert (seite_nr, antwort)."""
    seite, nr = _json(url, **params), 1
    while True:
        yield nr, seite
        nxt = (seite.get("links") or {}).get("next")
        if not nxt or (max_seiten and nr >= max_seiten):
            return
        seite, nr = json.loads(hole(nxt, ".json")), nr + 1


def kennzahlen(_):
    system, body = _json(SYSTEM), _json(BODY)
    zeilen = [{"objekt": "system", "feld": k, "wert": _wert(system.get(k))[:200]}
              for k in ("oparlVersion", "name", "vendor", "product", "license", "website", "contactEmail")]
    zeilen += [{"objekt": "body", "feld": k, "wert": _wert(body.get(k))[:200]}
               for k in ("name", "license", "licenseValidSince", "oparlSince", "contactEmail", "contactName",
                         "legislativeTerm", "modified")]
    listen = {k: body.get(k) for k in ("paper", "meeting", "organization", "person")}
    vor7 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S%z")
    for name, url in listen.items():
        if not url:
            zeilen.append({"objekt": name, "feld": "url", "wert": "fehlt im Body"})
            continue
        basis = _json(url)
        pag = basis.get("pagination") or {}
        zeilen.append({"objekt": name, "feld": "url", "wert": url})
        for k in ("totalElements", "elementsPerPage", "currentPage", "totalPages"):
            zeilen.append({"objekt": name, "feld": f"pagination.{k}", "wert": pag.get(k)})
        zeilen.append({"objekt": name, "feld": "objekte_erste_seite", "wert": len(basis.get("data", []))})
        zeilen.append({"objekt": name, "feld": "links", "wert": json.dumps(basis.get("links"))[:200]})
        if name != "paper":
            continue
        # Verhalten von limit und den Zeitfiltern (OParl 1.1: created_since/_until, modified_since/_until)
        for params in ({"limit": 100}, {"modified_since": vor7}, {"created_since": "2025-01-01T00:00:00+01:00",
                                                                  "created_until": "2025-12-31T23:59:59+01:00"}):
            try:
                a = _json(url, **params)
                zeilen.append({"objekt": name, "feld": "test " + urllib.parse.urlencode(params),
                               "wert": f"objekte={len(a.get('data', []))}; totalElements="
                                       f"{(a.get('pagination') or {}).get('totalElements')}"})
            except Abbruch as e:
                zeilen.append({"objekt": name, "feld": "test " + urllib.parse.urlencode(params), "wert": str(e)})
    _schreibe("oparl_kennzahlen.tsv", zeilen)


def organisationen(_):
    body = _json(BODY)
    typen, zeilen, n = collections.Counter(), [], 0
    for nr, seite in _seiten(body["organization"]):
        for o in seite.get("data", []):
            n += 1
            typen[o.get("organizationType") or "(leer)"] += 1
            zeilen.append({"id": o.get("id"), "name": o.get("name"), "kurz": o.get("shortName"),
                           "organizationType": o.get("organizationType"), "classification": o.get("classification"),
                           "startDate": o.get("startDate"), "endDate": o.get("endDate")})
        letzte = nr
    _schreibe("oparl_organisationen.tsv", zeilen)
    _schreibe("oparl_organisationstypen.tsv", [{"organizationType": k, "anzahl": v} for k, v in typen.most_common()])
    print(f"{n} Organisationen auf {letzte} Seiten; Ende von links.next erreicht")


def _bedeckung(papers):
    felder = ["underDirectionOf", "originatorPerson", "originatorOrganization", "mainFile", "auxiliaryFile",
              "location", "consultation", "relatedPaper", "superordinatedPaper", "subordinatedPaper", "date"]
    n = len(papers)
    zeilen = [{"feld": f, "vorhanden": sum(1 for p in papers if p.get(f)), "von": n} for f in felder]
    loc = collections.Counter()
    for p in papers:
        for l in p.get("location") or []:
            l = l if isinstance(l, dict) else {}
            for k in ("description", "streetAddress", "postalCode", "subLocality", "locality", "room", "geojson"):
                if l.get(k):
                    loc[k] += 1
    zeilen += [{"feld": f"location.{k}", "vorhanden": v, "von": n} for k, v in sorted(loc.items())]
    return zeilen


def stichprobe(a):
    body = _json(BODY)
    papers = []
    for jahr in range(a.von, a.bis + 1):
        params = {"created_since": f"{jahr}-01-01T00:00:00+01:00", "created_until": f"{jahr}-12-31T23:59:59+01:00"}
        for nr, seite in _seiten(body["paper"], a.seiten, **params):
            tot = (seite.get("pagination") or {}).get("totalElements")
            for p in seite.get("data", []):
                p["_jahr_filter"], p["_total"] = jahr, tot
                papers.append(p)
    # Prüfen, ob der Zeitfilter wirkt: Erstellungsdaten außerhalb des Jahres?
    ausser = sum(1 for p in papers if (p.get("created") or "")[:4] and int(p["created"][:4]) != p["_jahr_filter"])
    typen = collections.Counter(p.get("paperType") or "(leer)" for p in papers)
    ref = collections.Counter("AN/NNNN/JJJJ" if RE_AN.match(p.get("reference") or "") else
                              "NNNN/JJJJ" if RE_VV.match(p.get("reference") or "") else "anderes"
                              for p in papers)
    with (ERG / "_stichprobe_papers.jsonl").open("w", encoding="utf-8") as f:  # nur Metadaten, für pdf-koepfe
        for p in papers:
            f.write(json.dumps({k: p.get(k) for k in ("id", "reference", "paperType", "date", "mainFile",
                                                      "auxiliaryFile")}, ensure_ascii=False) + "\n")
    _schreibe("oparl_stichprobe_bedeckung.tsv", _bedeckung(papers) + [
        {"feld": "created außerhalb des Filterjahres", "vorhanden": ausser, "von": len(papers)}])
    _schreibe("oparl_papertypen.tsv", [{"paperType": k, "anzahl": v} for k, v in typen.most_common()])
    _schreibe("oparl_referenzschema.tsv", [{"schema": k, "anzahl": v} for k, v in ref.most_common()])
    _schreibe("oparl_stichprobe_jahre.tsv", [{"jahr": j, "objekte": sum(1 for p in papers if p["_jahr_filter"] == j),
                                              "totalElements": next((p["_total"] for p in papers
                                                                     if p["_jahr_filter"] == j), "")}
                                             for j in range(a.von, a.bis + 1)])


def sitzungen(a):
    body = _json(BODY)
    ergebnisse, n_top, oeff = collections.Counter(), 0, collections.Counter()
    for _, seite in _seiten(body["meeting"], a.seiten):
        for m in seite.get("data", []):
            for t in m.get("agendaItem") or []:
                if not isinstance(t, dict):
                    continue
                n_top += 1
                ergebnisse[(t.get("result") or "(leer)").strip()] += 1
                oeff[str(t.get("public"))] += 1
    _schreibe("oparl_top_ergebnisse.tsv", [{"result": k, "anzahl": v} for k, v in ergebnisse.most_common()]
              + [{"result": f"public={k}", "anzahl": v} for k, v in oeff.items()]
              + [{"result": "TOPs insgesamt", "anzahl": n_top}])


def _datei_url(p):
    for f in [p.get("mainFile")] + list(p.get("auxiliaryFile") or []):
        if isinstance(f, dict) and (f.get("accessUrl") or f.get("downloadUrl")):
            return f.get("downloadUrl") or f.get("accessUrl"), "mainFile" if f is p.get("mainFile") else "auxiliaryFile"
    return None, None


def pdf_koepfe(a):
    from pypdf import PdfReader

    quelle = ERG / "_stichprobe_papers.jsonl"
    if not quelle.exists():
        sys.exit("zuerst: stichprobe")
    papers = [json.loads(z) for z in quelle.open(encoding="utf-8")]
    vv = [p for p in papers if RE_VV.match(p.get("reference") or "")][: a.anzahl]
    zeilen = []
    for p in vv:
        url, art = _datei_url(p)
        z = {"id": p["id"], "reference": p["reference"], "paperType": p.get("paperType"), "datei": art or "keine"}
        if url:
            try:
                r = PdfReader(io.BytesIO(hole(url, ".pdf")))
                text = r.pages[0].extract_text() or "" if r.pages else ""
                m = RE_DEZ.search(text)
                z["treffer"] = "kennung" if m else ("nur_bezeichnung" if RE_DEZ_LOSE.search(text) else
                                                    "kein_text" if not text.strip() else "nein")
                z["kennung"] = re.sub(r"\s+", "", m.group(1)) if m else ""
            except Exception as e:  # einzelne defekte Dateien sollen die Messung nicht abbrechen
                z["treffer"] = f"fehler: {type(e).__name__}"
        zeilen.append(z)
    _schreibe("pdf_koepfe.tsv", zeilen)
    quote = collections.Counter(z.get("treffer", "keine_datei") for z in zeilen)
    print(dict(quote))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kommando", choices=["kennzahlen", "organisationen", "stichprobe", "sitzungen", "pdf-koepfe"])
    ap.add_argument("--seiten", type=int, default=3, help="Seiten je Jahr (stichprobe) bzw. insgesamt (sitzungen)")
    ap.add_argument("--von", type=int, default=2019)
    ap.add_argument("--bis", type=int, default=2026)
    ap.add_argument("--anzahl", type=int, default=100)
    a = ap.parse_args()
    if os.environ.get("RATSATLAS_STADT_INFORMIERT") != "ja":
        sys.exit("Abbruch: Die Stadt Köln ist noch nicht informiert (CLAUDE.md, Abschnitt 9). "
                 "Erst nach Freigabe mit RATSATLAS_STADT_INFORMIERT=ja ausführen.")
    {"kennzahlen": kennzahlen, "organisationen": organisationen, "stichprobe": stichprobe,
     "sitzungen": sitzungen, "pdf-koepfe": pdf_koepfe}[a.kommando](a)


if __name__ == "__main__":
    main()
