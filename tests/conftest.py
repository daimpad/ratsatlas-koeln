"""Gemeinsame Hilfen der Tests: lokaler OParl-Testserver mit synthetischen Daten (keine Daten der Stadt).

Die Objekte sind erfunden und nur strukturell an der Kölner API orientiert (Stichprobe in CLAUDE.md 3.1):
Referenzen „NNNN/JJJJ“ und „AN/NNNN/JJJJ“, `consultation` mit direktem Verweis auf `meeting` und `agendaItem`,
`location` nur mit `subLocality`, Paginierung über `links.next`. `Daten.form = "koeln"` liefert die Listen wie Köln in
Stufe 1 (07.11.2026): neueste zuerst (zuletzt angefügt zuerst), `pagination` nur mit elementsPerPage und currentPage,
`links` nur mit first, self und next. `created` wächst mit der Nummer der Vorlage (neueste zuerst heißt also wie in
Köln `created` absteigend).
Dazu Fabriken für lokale TLS-Server: `tls_server` (selbst signiertes Zertifikat, dem der Client nicht vertraut) und
`abbrechender_server` (Handshake endet unerwartet oder wird zurückgesetzt).
"""
import json
import os
import shutil
import tempfile

# Sperrdatei der Messskripte (explore/abruf.py) während der Tests nie in ~/.cache, sondern in einem Temp-Ordner, der am
# Ende der Testsitzung entfernt wird (nur, wenn er hier angelegt wurde). Gesetzt vor dem Import der Messskripte, die den
# Ort beim Import lesen; Teilprozesse der Tests reichen RATSATLAS_SPERRE weiter.
_SPERRE_TEMP = None
if not os.environ.get("RATSATLAS_SPERRE"):
    _SPERRE_TEMP = tempfile.mkdtemp(prefix="ratsatlas-sperre-")
    os.environ["RATSATLAS_SPERRE"] = _SPERRE_TEMP
import socket
import socketserver
import ssl
import struct
import subprocess
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipeline import config


def pytest_sessionfinish(session, exitstatus):
    if _SPERRE_TEMP:
        shutil.rmtree(_SPERRE_TEMP, ignore_errors=True)


@pytest.fixture
def roher_server():
    """Fabrik für lokale TCP-Server auf 127.0.0.1, die abgeschnittene oder unlesbare Antworten senden: `starten(antwort)`
    liest den Kopf jeder Anfrage, sendet `antwort` (Bytes, unverändert) und schließt die Verbindung. Der Server hat
    `anfragen` (erste Zeile jeder Anfrage) und `url`; am Ende des Tests wird er beendet."""
    gestartet = []

    def starten(antwort):
        anfragen = []

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                daten = b""
                while b"\r\n\r\n" not in daten:
                    teil = self.request.recv(4096)
                    if not teil:
                        break
                    daten += teil
                anfragen.append(daten.split(b"\r\n", 1)[0].decode("latin-1"))
                self.request.sendall(antwort)
                self.request.shutdown(socket.SHUT_WR)

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        server.daemon_threads = True
        server.anfragen, server.url = anfragen, f"http://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        gestartet.append(server)
        return server

    yield starten
    for server in gestartet:
        server.shutdown()
        server.server_close()


@pytest.fixture
def tls_server(tmp_path):
    """HTTPS-Server auf 127.0.0.1 mit selbst signiertem Zertifikat (openssl), dem der Client nicht vertraut: Die
    Zertifikatsprüfung scheitert im Handshake, bevor eine HTTP-Anfrage gesendet ist. `anfragen`: empfangene
    HTTP-Anfragen, `url`, `zertifikat` (zum Gegenversuch mit vertrautem Zertifikat)."""
    if not shutil.which("openssl"):
        pytest.skip("openssl fehlt")
    schluessel, zertifikat = tmp_path / "tls_schluessel.pem", tmp_path / "tls_zertifikat.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-keyout", str(schluessel), "-out", str(zertifikat), "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True, timeout=60)
    anfragen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            anfragen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    kontext.load_cert_chain(zertifikat, schluessel)
    server.socket = kontext.wrap_socket(server.socket, server_side=True)
    server.anfragen, server.zertifikat = anfragen, zertifikat
    server.url = f"https://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def abbrechender_server():
    """Fabrik für TCP-Server auf 127.0.0.1, die den TLS-Handshake abbrechen: `starten(reset)` liest den Beginn des
    Handshakes und schließt die Verbindung (unerwartetes Ende) bzw. setzt sie zurück (`reset`, SO_LINGER 0). Der Server
    hat `verbindungen` und `url` (https)."""
    gestartet = []

    def starten(reset=False):
        verbindungen = []

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                verbindungen.append(self.request.recv(4096)[:1])
                if reset:
                    self.request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                self.request.close()

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        server.daemon_threads = True
        server.verbindungen, server.url = verbindungen, f"https://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        gestartet.append(server)
        return server

    yield starten
    for server in gestartet:
        server.shutdown()
        server.server_close()


class Daten:
    def __init__(self, basis):
        self.b = basis
        self.form = "bisher"   # „koeln“: Listen wie Köln in Stufe 1 (siehe oben)
        self.groesse = 2       # Objekte je Seite
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
            "created": (datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=2))) + timedelta(minutes=i)).isoformat(),
            "location": [{"id": f"{b}/locations/{i}", "subLocality": "Neuehrenfeld"}] if i == 3 else [],
            "consultation": [{"id": f"{b}/consultations/{i}", "meeting": f"{b}/meetings/1",
                              "agendaItem": f"{b}/agendaitems/{i}", "role": "Entscheidung", "authoritative": True}],
        }

    def stoerung(self, pfad, q):
        """Für Tests überschreibbar: True erzeugt HTTP 404 für diese Anfrage."""
        return False

    def body(self):
        b = self.b
        return {"id": f"{b}/body", "name": "Testkörperschaft", "paper": f"{b}/papers", "meeting": f"{b}/meetings",
                "organization": f"{b}/organizations",
                "legislativeTerm": [{"id": f"{b}/terms/1", "name": "2025–2030", "startDate": "2025-11-01"}]}

    def liste(self, objekte, pfad, q, groesse=None):
        groesse = groesse or self.groesse
        seit = q.get("modified_since")
        if seit:
            objekte = [o for o in objekte if o["modified"] >= seit]
        if self.form == "koeln":   # neueste zuerst: zuletzt angefügte Objekte zuerst
            objekte = objekte[::-1]
        seite = int(q.get("page", 1))
        teil = objekte[(seite - 1) * groesse: seite * groesse]
        links = {}

        def adresse(werte):   # wie SessionNet: ohne URL-Kodierung
            return f"{self.b}{pfad}" + ("?" + "&".join(f"{k}={v}" for k, v in werte.items()) if werte else "")
        if seite * groesse < len(objekte):
            links["next"] = adresse({**q, "page": seite + 1})
        if self.form == "koeln":   # ohne Gesamtzahlen; links nur first, self, next
            return {"data": teil, "pagination": {"elementsPerPage": groesse, "currentPage": seite},
                    "links": {"first": adresse({k: v for k, v in q.items() if k != "page"}), "self": adresse(q),
                              **links}}
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
            # wie SessionNet: „+“ bleibt „+“; kodierte Zeitstempel (%3A, %2B) ergeben HTTP 404
            q = dict((k, urllib.parse.unquote(v)) for k, _, v in (x.partition("=") for x in u.query.split("&") if x))
            d.anfragen.append((u.path, q, self.headers.get("User-Agent")))
            if "%3A" in u.query.upper() or "%2B" in u.query.upper() or d.stoerung(u.path, q):
                self.send_response(404)
                self.end_headers()
                return
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
