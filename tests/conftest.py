"""Gemeinsame Hilfen der Tests: lokaler OParl-Testserver mit synthetischen Daten (keine Daten der Stadt).

Die Objekte sind erfunden und nur strukturell an der Kölner API orientiert (Stichprobe in CLAUDE.md 3.1):
Referenzen „NNNN/JJJJ“ und „AN/NNNN/JJJJ“, `consultation` mit direktem Verweis auf `meeting` und `agendaItem`,
`location` nur mit `subLocality`, Paginierung über `links.next`.
"""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipeline import config


class Daten:
    def __init__(self, basis):
        self.b = basis
        self.anfragen = []
        self.papers = [self.paper(i) for i in range(1, 6)]
        self.meetings = [{
            "id": f"{basis}/meetings/1", "type": "https://schema.oparl.org/1.1/Meeting",
            "name": "Bezirksvertretung 4 (Ehrenfeld)", "start": "2026-10-01T17:00:00+02:00",
            "organization": [f"{basis}/organizations/bv4"], "modified": "2026-10-02T08:00:00+02:00",
            "agendaItem": [{"id": f"{basis}/agendaitems/{i}", "number": f"8.{i}", "name": f"TOP {i}",
                            "result": "ungeändert beschlossen" if i % 2 else "Kenntnis genommen", "public": True}
                           for i in range(1, 6)]}]
        self.orgs = [{"id": f"{basis}/organizations/bv4", "name": "Bezirksvertretung 4 (Ehrenfeld)",
                      "organizationType": "Gremium", "modified": "2026-01-01T00:00:00+01:00"},
                     {"id": f"{basis}/organizations/rat", "name": "Rat", "organizationType": "Gremium",
                      "modified": "2026-01-01T00:00:00+01:00"}]

    def paper(self, i, name=None, modified="2026-10-01T10:00:00+02:00"):
        b = self.b
        return {
            "id": f"{b}/papers/{i}", "type": "https://schema.oparl.org/1.1/Paper",
            "reference": f"{1000 + i}/2026" if i % 2 else f"AN/{100 + i}/2026",
            "name": name or ("Umgestaltung der Venloer Straße in Ehrenfeld" if i == 1 else f"Synthetische Vorlage {i}"),
            "paperType": "Beschlussvorlage" if i % 2 else "Antrag nach § 3",
            "date": "2026-09-20", "modified": modified,
            "location": [{"id": f"{b}/locations/{i}", "subLocality": "Neuehrenfeld"}] if i == 3 else [],
            "consultation": [{"id": f"{b}/consultations/{i}", "meeting": f"{b}/meetings/1",
                              "agendaItem": f"{b}/agendaitems/{i}", "role": "Entscheidung", "authoritative": True}],
        }

    def body(self):
        b = self.b
        return {"id": f"{b}/body", "name": "Testkörperschaft", "paper": f"{b}/papers", "meeting": f"{b}/meetings",
                "organization": f"{b}/organizations",
                "legislativeTerm": [{"id": f"{b}/terms/1", "name": "2025–2030", "startDate": "2025-11-01"}]}

    def liste(self, objekte, pfad, q, groesse=2):
        seit = q.get("modified_since")
        if seit:
            objekte = [o for o in objekte if o["modified"] >= seit]
        seite = int(q.get("page", 1))
        teil = objekte[(seite - 1) * groesse: seite * groesse]
        links = {}
        if seite * groesse < len(objekte):
            nq = {**q, "page": seite + 1}
            links["next"] = f"{self.b}{pfad}?" + urllib.parse.urlencode(nq)
        return {"data": teil, "pagination": {"totalElements": len(objekte)}, "links": links}


@pytest.fixture
def oparl(tmp_path, monkeypatch):
    """Startet den Testserver und lenkt alle Pfade der Pipeline in ein temporäres Verzeichnis."""
    daten = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            d = daten["d"]
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            d.anfragen.append((u.path, q, self.headers.get("User-Agent")))
            antwort = {"/body": d.body,
                       "/papers": lambda: d.liste(d.papers, "/papers", q),
                       "/meetings": lambda: d.liste(d.meetings, "/meetings", q),
                       "/organizations": lambda: d.liste(d.orgs, "/organizations", q)}.get(u.path)
            if not antwort:
                self.send_response(404)
                self.end_headers()
                return
            b = json.dumps(antwort()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    basis = f"http://127.0.0.1:{server.server_address[1]}"
    daten["d"] = Daten(basis)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    raw, build, export = tmp_path / "raw", tmp_path / "build", tmp_path / "export"
    for name, wert in {"RAW": raw, "BUILD": build, "EXPORT": export, "DB": build / "allris.sqlite",
                       "PAPERS": raw / "papers.jsonl", "ORGANIZATIONS": raw / "organizations.json",
                       "VERWALTUNGSBEREICHE": raw / "verwaltungsbereiche.json", "MEETINGS": raw / "meetings.json",
                       "LEGISLATIVE_TERMS": raw / "legislative_terms.json", "BERATUNGEN": raw / "beratungen.jsonl",
                       "CONSULTATIONS_LITE": raw / "beratungen.jsonl", "STAND": raw / "STAND.json",
                       "ZUSTAND": raw / "zustand_abruf.json", "ABRUFSTATISTIK": export / "abrufstatistik.tsv",
                       "TEXTE": raw / "texte.jsonl", "OPARL_BODY": f"{basis}/body", "ABRUF_ABSTAND": 0.0,
                       "BPLAN": tmp_path / "fehlt.geojson", "OBJEKTE": tmp_path / "fehlt.json",
                       "HAUSNUMMERN": tmp_path / "fehlt_hnr.json"}.items():
        monkeypatch.setattr(config, name, wert)
    monkeypatch.delenv("RATSATLAS_STADT_INFORMIERT", raising=False)
    monkeypatch.delenv("RATSATLAS_VOLLABRUF", raising=False)
    yield daten["d"]
    server.shutdown()
