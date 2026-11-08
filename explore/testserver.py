"""Lokaler OParl-Testserver mit erfundenen Daten für Probeläufe der Messstufen (explore/STUFEN.md).

Keine Daten der Stadt Köln: Namen tragen „[Testdaten]“, alle Adressen zeigen auf 127.0.0.1 (in Tests auch eine andere
Loopback-Adresse wie 127.0.0.2, Parameter `host`). Die Struktur folgt der
OParl-Spezifikation 1.1 und dem, was über die Kölner API bekannt ist (CLAUDE.md 3.1,
explore/ergebnisse/sessionnet_befunde.tsv):
- System → Body mit den Listen paper, meeting, organization, person; 25 Objekte je Seite
- Paginierung nur über links.next; Folgeseiten übernehmen alle Parameter ohne URL-Kodierung (wie SessionNet)
- URL-kodierte Parameter (%3A, %2B …) → HTTP 404 (SessionNet in Wuppertal); Seite hinter der letzten → HTTP 401
  (Köln: 401 bei sehr hoher Seitennummer; die genaue Schwelle ist offen)
- Filter created_since/_until und modified_since/_until; `limit` wird ignoriert (die Spezifikation erlaubt das)
- Vorlagen über mehrere Jahre mit Referenzen „NNNN/JJJJ“ und „AN/NNNN/JJJJ“; consultation verweist direkt auf
  meeting und agendaItem; location nur mit subLocality; kein underDirectionOf
- Dateien unter …/downloadfiles/<Nummer>.pdf als kleine PDF-Datei mit erfundenem Kopf
Form „koeln“ (Parameter `form`): wie die Kölner Antwort in Stufe 1 (07.11.2026, explore/BERICHT_phase1.md Abschnitt 5):
- `pagination` nur mit elementsPerPage und currentPage (ohne totalElements, totalPages), `links` nur mit first, self
  und next (ohne last, prev); `license` in System und Body null
- Vorlagen neueste zuerst (created absteigend), die 30 jüngsten in den letzten vier Tagen geändert (modified, je drei
  Stunden auseinander; Stufe 1: erste Seite mit Vorlagen weniger Tage); je Vorlage nur auxiliaryFile (1–3 Dateien),
  body, consultation (genau eine, eingebettet, mit meeting, agendaItem, organization, role), created, date, id,
  modified, name, paperType, reference, type – ohne mainFile, location, underDirectionOf, originatorPerson und
  originatorOrganization
- paperType in Kölner Mustern („Antrag nach § 3 BV2 (CDU)“, „Änderungsantrag BV1 (Grüne)“, „Beschlussvorlage
  Bezirksvertretung“); Fraktionen und Nummern sind erfunden zugeordnet
- Body wie in Köln mit den Listen paper, meeting, organization, person (Adresse …/people) und weiteren Adressen
  (agendaItem, consultation, file, locationList, legislativeTermList, membership; hier nicht bedient) und drei
  Wahlperioden
Welche Felder, Typen und Mengen die Stadt tatsächlich liefert, ist offen; das messen die Stufen.

Aufruf: python3 explore/testserver.py [--port 8765]   (Ende mit Strg+C)
"""
import argparse
import datetime as dt
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

SEITE = 25
JAHRE = range(2015, 2027)
VORLAGEN_JE_JAHR = 110       # > 4 Seiten je Jahr, damit --seiten bis 4 je Jahr volle Seiten liefert
SITZUNGEN_JE_JAHR = 25
ORGANISATIONEN = 140         # 6 Seiten (5 × 25 + 15)
PERSONEN = 210               # 9 Seiten
OPARL = "https://schema.oparl.org/1.1/"
ERGEBNISSE = ("ungeändert beschlossen", "geändert beschlossen", "zur Kenntnis genommen", "vertagt", None)
ORGTYPEN = ("Gremium", "Gremium", "Fraktion", "Verwaltungsbereich", "Sonstiges")
FORMEN = ("bisher", "koeln")
# Kölner Muster der Vorlagenart (Stufe 1); {n} Bezirksvertretung, {f} Fraktion
ARTEN_KOELN_POLITIK = ("Antrag nach § 3 BV{n} ({f})", "Änderungsantrag BV{n} ({f})", "Anfrage nach § 4 BV{n} ({f})",
                       "Antrag nach § 3 der Geschäftsordnung des Rates")
ARTEN_KOELN_VERWALTUNG = ("Beschlussvorlage Bezirksvertretung", "Mitteilung", "Beschlussvorlage")
FRAKTIONEN_KOELN = ("CDU", "SPD", "Grüne", "FDP", "Die Linke", "Volt")


def _zeit(wert):
    return dt.datetime.fromisoformat(wert.replace("Z", "+00:00"))


def pdf(text: str) -> bytes:
    """Kleinste PDF-Datei mit einer Textzeile (Helvetica), lesbar für pypdf."""
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    inhalt = f"BT /F1 11 Tf 56 780 Td ({text}) Tj ET".encode("latin-1")
    objekte = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(inhalt) + inhalt + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    aus, positionen = bytearray(b"%PDF-1.4\n"), []
    for nr, o in enumerate(objekte, 1):
        positionen.append(len(aus))
        aus += b"%d 0 obj\n" % nr + o + b"\nendobj\n"
    xref = len(aus)
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
    for p in positionen:
        aus += b"%010d 00000 n \n" % p
    aus += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, xref)
    return bytes(aus)


class Daten:
    """Erfundene Objekte; deterministisch bis auf wenige Änderungszeitpunkte der letzten Tage (modified_since)."""

    def __init__(self, basis, jahre=JAHRE, je_jahr=VORLAGEN_JE_JAHR, form="bisher"):
        assert form in FORMEN, form
        self.basis, self.form = basis, form
        self.system_url = f"{basis}/oparl/system"
        self.body_url = f"{basis}/oparl/bodies/testkoerperschaft"
        b = self.body_url
        jetzt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        kuerzlich = (jetzt - dt.timedelta(days=2)).isoformat()

        self.organisationen = [{
            "id": f"{b}/organizations/{n}", "type": OPARL + "Organization", "body": b,
            "name": f"[Testdaten] Organisation {n}", "shortName": f"Org {n}",
            "organizationType": ORGTYPEN[n % len(ORGTYPEN)], "classification": "[Testdaten] Klassifikation",
            "startDate": f"{2000 + n % 25}-01-01", "endDate": "2020-10-31" if n % 9 == 0 else None,
            "created": "2016-01-01T08:00:00+01:00", "modified": "2025-11-01T08:00:00+01:00"}
            for n in range(1, ORGANISATIONEN + 1)]
        gremien = [o["id"] for o in self.organisationen if o["organizationType"] == "Gremium"][:30]
        fraktionen = [o["id"] for o in self.organisationen if o["organizationType"] == "Fraktion"][:10]

        self.personen = [{"id": f"{b}/persons/{n}", "type": OPARL + "Person", "body": b,
                          "name": f"[Testdaten] Person {n}", "created": "2016-01-01T08:00:00+01:00",
                          "modified": "2025-11-01T08:00:00+01:00"} for n in range(1, PERSONEN + 1)]

        self.sitzungen, sitzungen_je_jahr, n = [], {}, 0
        for jahr in jahre:
            for i in range(SITZUNGEN_JE_JAHR):
                n += 1
                tag = dt.date(jahr, 1, 10) + dt.timedelta(days=14 * i)
                mid = f"{b}/meetings/{n}"
                tops = [{"id": f"{b}/agendaitems/{n}-{t}", "type": OPARL + "AgendaItem", "meeting": mid,
                         "number": f"{t}", "name": f"[Testdaten] Tagesordnungspunkt {t}", "public": (n + t) % 7 != 0,
                         **({"result": ERGEBNISSE[(n + t) % len(ERGEBNISSE)]}
                            if ERGEBNISSE[(n + t) % len(ERGEBNISSE)] else {})}
                        for t in range(1, 4 + n % 6)]
                m = {"id": mid, "type": OPARL + "Meeting", "name": f"[Testdaten] Sitzung {n}",
                     "start": f"{tag.isoformat()}T17:00:00+01:00", "end": f"{tag.isoformat()}T20:00:00+01:00",
                     "organization": [gremien[n % len(gremien)]], "agendaItem": tops,
                     "created": f"{tag.isoformat()}T08:00:00+01:00", "modified": f"{tag.isoformat()}T21:00:00+01:00"}
                self.sitzungen.append(m)
                sitzungen_je_jahr.setdefault(jahr, []).append(m)

        self.vorlagen, k = [], 0
        heute = jetzt.date()
        for jahr in jahre:
            # im laufenden Jahr nur Erstellungsdaten bis vor zehn Tagen
            spanne = 360 if jahr < heute.year else max((heute - dt.date(jahr, 1, 2)).days - 10, 30)
            for i in range(je_jahr):
                k += 1
                antrag = i % 3 == 2
                tag = dt.date(jahr, 1, 2) + dt.timedelta(days=(i * 3) % spanne)
                created = f"{tag.isoformat()}T10:00:00+01:00"
                modified = kuerzlich if k % 40 == 0 else f"{(tag + dt.timedelta(days=5)).isoformat()}T10:00:00+01:00"
                pid = f"{b}/papers/{k}"
                p = {"id": pid, "type": OPARL + "Paper", "body": b,
                     "name": f"[Testdaten] Vorlage {k}",
                     "reference": f"AN/{1000 + i:04d}/{jahr}" if antrag else f"{1000 + i:04d}/{jahr}",
                     "paperType": ("Antrag nach § 3", "Anfrage nach § 4")[i % 2] if antrag
                     else ("Beschlussvorlage", "Mitteilung")[i % 2],
                     "date": tag.isoformat(), "created": created, "modified": modified}
                if k % 10:
                    p["mainFile"] = self._datei(k, "Vorlage")
                if k % 4 == 0:
                    p["auxiliaryFile"] = [self._datei(100000 + k, "Anlage")]
                if k % 8 == 0:
                    p["location"] = [{"id": f"{b}/locations/{k}", "type": OPARL + "Location",
                                      "subLocality": f"[Testdaten] Stadtteil {k % 86 + 1}"}]
                if antrag:
                    p["originatorOrganization"] = [fraktionen[k % len(fraktionen)]]
                beratungen = []
                for j, m in enumerate(sitzungen_je_jahr.get(jahr, [])[i % SITZUNGEN_JE_JAHR:][:1 + k % 2]):
                    top = m["agendaItem"][k % len(m["agendaItem"])]
                    beratungen.append({"id": f"{b}/consultations/{k}-{j}", "type": OPARL + "Consultation",
                                       "paper": pid, "meeting": m["id"], "agendaItem": top["id"],
                                       "role": ("Vorberatung", "Entscheidung")[j == 0 and k % 2 == 1],
                                       "authoritative": j == 0})
                if beratungen:
                    p["consultation"] = beratungen
                if form == "koeln":
                    p = self._koeln(p, k, i, antrag, sitzungen_je_jahr.get(jahr, []))
                self.vorlagen.append(p)
        for liste in (self.vorlagen, self.sitzungen, self.organisationen, self.personen):
            for o in liste:
                o["_c"], o["_m"] = _zeit(o["created"]), _zeit(o["modified"])
        if form == "koeln":   # neueste zuerst (created absteigend, bei gleichem Zeitpunkt die höhere Nummer)
            self.vorlagen.sort(key=lambda o: (o["_c"], int(o["id"].rsplit("/", 1)[1])), reverse=True)
            for i, o in enumerate(self.vorlagen[:30]):   # die jüngsten Vorlagen kürzlich geändert
                o["modified"] = (jetzt - dt.timedelta(hours=3 * (i + 1))).isoformat()
                o["_m"] = _zeit(o["modified"])

    def _koeln(self, p, k, i, antrag, sitzungen):
        """Vorlage in Kölner Form (Stufe 1): nur die dort gelieferten Felder, eine eingebettete Beratung mit Gremium,
        1–3 Anlagen, Vorlagenart nach Kölner Muster."""
        aus = {f: p[f] for f in ("id", "type", "body", "name", "reference", "date", "created", "modified")}
        if antrag:
            aus["paperType"] = ARTEN_KOELN_POLITIK[k % len(ARTEN_KOELN_POLITIK)].format(
                n=1 + k % 9, f=FRAKTIONEN_KOELN[k % len(FRAKTIONEN_KOELN)])
        else:
            aus["paperType"] = ARTEN_KOELN_VERWALTUNG[k % len(ARTEN_KOELN_VERWALTUNG)]
        aus["auxiliaryFile"] = [self._datei(100000 + 3 * k + j, "Anlage") for j in range(1 + k % 3)]
        m = sitzungen[i % SITZUNGEN_JE_JAHR] if sitzungen else None
        if m:
            top = m["agendaItem"][k % len(m["agendaItem"])]
            aus["consultation"] = [{"id": f"{self.body_url}/consultations/{k}-0", "type": OPARL + "Consultation",
                                    "meeting": m["id"], "agendaItem": top["id"], "organization": m["organization"],
                                    "role": ("Vorberatung", "Entscheidung")[k % 2]}]
        return aus

    def _datei(self, nr, art):
        url = f"{self.body_url}/downloadfiles/{nr}.pdf"
        return {"id": f"{self.body_url}/files/{nr}", "type": OPARL + "File", "name": f"[Testdaten] {art} {nr}",
                "fileName": f"{nr}.pdf", "mimeType": "application/pdf", "accessUrl": url, "downloadUrl": url}

    def system(self):
        return {"id": self.system_url, "type": OPARL + "System", "oparlVersion": OPARL,
                "name": "[Testdaten] Lokaler OParl-Testserver", "body": f"{self.basis}/oparl/bodies",
                "vendor": "", "product": "", "license": None if self.form == "koeln" else ""}

    def personen_url(self):
        return f"{self.body_url}/{'people' if self.form == 'koeln' else 'persons'}"

    def body(self):
        b = self.body_url
        body = {"id": b, "type": OPARL + "Body", "system": self.system_url, "name": "[Testdaten] Körperschaft",
                "shortName": "Test", "license": "", "paper": f"{b}/papers", "meeting": f"{b}/meetings",
                "organization": f"{b}/organizations", "person": self.personen_url(),
                "legislativeTerm": [{"id": f"{b}/legislativeterms/1", "type": OPARL + "LegislativeTerm",
                                     "name": "[Testdaten] 2025–2030", "startDate": "2025-11-01"}],
                "created": "2016-01-01T08:00:00+01:00", "modified": "2026-01-01T08:00:00+01:00"}
        if self.form == "koeln":
            body.update(license=None, licenseValidSince="2017-01-31", oparlSince="2017-01-31",
                        agendaItem=f"{b}/agendaItems", consultation=f"{b}/consultations", file=f"{b}/files",
                        locationList=f"{b}/locations", legislativeTermList=f"{b}/legislativeterms",
                        membership=f"{b}/memberships",
                        legislativeTerm=[{"id": f"{b}/legislativeterms/{n}", "type": OPARL + "LegislativeTerm",
                                          "name": f"[Testdaten] {von[:4]}–{bis[:4]}", "startDate": von, "endDate": bis}
                                         for n, (von, bis) in enumerate((("2014-06-01", "2020-10-31"),
                                                                         ("2020-11-01", "2025-10-31"),
                                                                         ("2025-11-01", "2030-10-31")), 1)])
        return body

    def listen(self):
        b = self.body_url
        return {f"{b}/papers": self.vorlagen, f"{b}/meetings": self.sitzungen,
                f"{b}/organizations": self.organisationen, self.personen_url(): self.personen}


class Testserver:
    """Startet den Server in einem Hintergrund-Thread. `anfragen`: Liste (Pfad, Abfrage, User-Agent, Status);
    `eingang`: Eingangszeit je Anfrage, `ausgang`: Zeit nach dem Senden der Antwort (beide time.monotonic, für alle
    Prozesse derselben Maschine vergleichbar).
    `stoerung(pfad, abfrage)` darf einen Statuscode liefern (z. B. 429); `verzoegerung` in Sekunden je Antwort (oder
    eine Funktion (pfad, abfrage) → Sekunden);
    `weiterleitungen`: Pfad → (Status, Ziel) für Antworten mit Location-Kopf (z. B. 301);
    `ohne_created_filter`: created_since/created_until werden ignoriert (Jahresfilter wirkt nicht);
    `ohne_modified_filter`: modified_since/modified_until werden ignoriert;
    `abschneiden(pfad)`: True sendet nur die Hälfte des Inhalts bei vollem Content-Length und schließt die Verbindung
    (abgeschnittene Antwort). `host`: 127.0.0.1 (Vorgabe) oder eine andere Loopback-Adresse wie 127.0.0.2, die
    oparl_messung.lokal() nicht als lokal ansieht (Tests der Regeln für Anfragen an die Stadt ohne Netz).
    `form`: „bisher“ (Vorgabe) oder „koeln“ (Antwortform aus Stufe 1, siehe oben)."""

    def __init__(self, port=0, host="127.0.0.1", **kw):
        assert host.startswith("127."), "nur Loopback-Adressen"
        self.anfragen = []
        self.eingang = []
        self.ausgang = []
        self.stoerung = lambda pfad, abfrage: None
        self.abschneiden = lambda pfad: False
        self.verzoegerung = 0.0
        self.weiterleitungen = {}
        self.ohne_created_filter = False
        self.ohne_modified_filter = False
        self.server = ThreadingHTTPServer((host, port), self._handler())
        self.basis = f"http://{host}:{self.server.server_address[1]}"
        self.daten = Daten(self.basis, **kw)
        self.system_url, self.body_url = self.daten.system_url, self.daten.body_url
        self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()

    def start(self):
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def antwort(self, pfad, abfrage):
        """(Status, Inhaltstyp, Bytes) für eine Anfrage."""
        d = self.daten
        if "%" in abfrage:      # wie SessionNet: kodierte Parameter ergeben 404 text/html
            return 404, "text/html", b"<html><body>Not Found</body></html>"
        q = dict(x.partition("=")[::2] for x in abfrage.split("&") if x)   # „+“ bleibt „+“
        url = d.basis + pfad
        if url == d.system_url:
            return 200, "application/json", json.dumps(d.system()).encode()
        if url == f"{d.basis}/oparl/bodies":
            return 200, "application/json", json.dumps(self._seite([d.body()], url, q, d.form)).encode()
        if url == d.body_url:
            return 200, "application/json", json.dumps(d.body()).encode()
        if url.startswith(f"{d.body_url}/downloadfiles/") and url.endswith(".pdf"):
            nr = int(url.rsplit("/", 1)[1][:-4])
            kopf = ("[Testdaten] Dezernat, Dienststelle VI/61", "[Testdaten] Dezernat, Dienststelle",
                    "[Testdaten] Mitteilung")[nr % 3]
            return 200, "application/pdf", pdf(kopf)
        objekte = d.listen().get(url)
        if objekte is None:
            return 404, "text/html", b"<html><body>Not Found</body></html>"
        try:
            filter_q = {k: v for k, v in q.items() if not (self.ohne_created_filter and k.startswith("created_"))
                        and not (self.ohne_modified_filter and k.startswith("modified_"))}
            objekte = self._filtern(objekte, filter_q)
            return 200, "application/json", json.dumps(self._seite(objekte, url, q, d.form)).encode()
        except ValueError:
            return 400, "text/html", b"<html><body>Bad Request</body></html>"
        except LookupError:
            return 401, "text/html", b"<html><body>Unauthorized</body></html>"

    @staticmethod
    def _filtern(objekte, q):
        for name, feld, vergleich in (("created_since", "_c", 1), ("created_until", "_c", -1),
                                      ("modified_since", "_m", 1), ("modified_until", "_m", -1)):
            if name in q:
                grenze = _zeit(q[name])
                if grenze.tzinfo is None:
                    raise ValueError(name)
                objekte = [o for o in objekte if (o[feld] >= grenze if vergleich > 0 else o[feld] <= grenze)]
        return objekte

    @staticmethod
    def _seite(objekte, url, q, form="bisher"):
        seite = int(q.get("page", "1"))
        gesamt = max(1, -(-len(objekte) // SEITE))
        if not 1 <= seite <= gesamt:
            raise LookupError(seite)
        rest = {k: v for k, v in q.items() if k != "page"}

        def link(n):   # unverändert, ohne URL-Kodierung
            return url + "?" + "&".join(f"{k}={v}" for k, v in {**rest, "page": n}.items())
        links = {"first": link(1), "last": link(gesamt)}
        if seite > 1:
            links["prev"] = link(seite - 1)
        if seite < gesamt:
            links["next"] = link(seite + 1)
        teil = [{k: v for k, v in o.items() if not k.startswith("_")}
                for o in objekte[(seite - 1) * SEITE: seite * SEITE]]
        if form == "koeln":   # ohne Gesamtzahlen; links nur first, self, next (Stufe 1)
            def adresse(werte):
                return url + ("?" + "&".join(f"{k}={v}" for k, v in werte.items()) if werte else "")
            links = {"first": adresse(rest), "self": adresse(q), **({"next": links["next"]} if "next" in links else {})}
            return {"data": teil, "pagination": {"elementsPerPage": SEITE, "currentPage": seite}, "links": links}
        return {"data": teil, "pagination": {"totalElements": len(objekte), "elementsPerPage": SEITE,
                                             "currentPage": seite, "totalPages": gesamt}, "links": links}

    def _handler(self):
        server = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                teile = urlsplit(self.path)
                status, ziel = server.stoerung(teile.path, teile.query), None
                if teile.path in server.weiterleitungen:
                    status, ziel = server.weiterleitungen[teile.path]
                    typ, inhalt = "text/html", b"<html><body>Moved</body></html>"
                elif status:
                    typ, inhalt = "text/html", b"<html><body>Fehler (Testserver)</body></html>"
                else:
                    status, typ, inhalt = server.antwort(teile.path, teile.query)
                server.anfragen.append((teile.path, teile.query, self.headers.get("User-Agent"), status))
                server.eingang.append(time.monotonic())
                pause = (server.verzoegerung(teile.path, teile.query) if callable(server.verzoegerung)
                         else server.verzoegerung)
                if pause:
                    time.sleep(pause)
                self.send_response(status)
                if ziel:
                    self.send_header("Location", ziel)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Length", str(len(inhalt)))
                self.end_headers()
                if server.abschneiden(teile.path):   # Verbindung mitten im Inhalt schließen
                    inhalt = inhalt[:len(inhalt) // 2]
                    self.close_connection = True
                self.wfile.write(inhalt)
                self.wfile.flush()
                server.ausgang.append(time.monotonic())

        return H


def main():
    ap = argparse.ArgumentParser(description="Lokaler OParl-Testserver mit erfundenen Daten")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--form", choices=FORMEN, default="bisher", help="Antwortform (koeln: wie Stufe 1)")
    a = ap.parse_args()
    s = Testserver(a.port, form=a.form).start()
    print(f"RATSATLAS_OPARL_SYSTEM={s.system_url}\nRATSATLAS_OPARL_BODY={s.body_url}\n(Ende mit Strg+C)",
          file=sys.stderr)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        s.stop()
        print(f"{len(s.anfragen)} Anfragen beantwortet", file=sys.stderr)


if __name__ == "__main__":
    main()
