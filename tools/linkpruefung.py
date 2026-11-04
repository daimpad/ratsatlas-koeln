"""Linkprüfung der zusammengestellten Seite (Phase 6): innere Links und Sprungmarken, auf Wunsch äußere Links.

Aufruf: python3 tools/linkpruefung.py [_site] [--extern] [--tsv ergebnis.tsv]
- innere Links (href, src) aller HTML-Seiten: Ziel muss als Datei oder Verzeichnis mit index.html existieren;
  Sprungmarken (#…) auf derselben oder einer anderen Seite müssen als id vorhanden sein
- --extern: äußere Links mit HEAD (Rückfall GET) prüfen, je Adresse einmal, mit 1 s Abstand; Server der Stadt Köln und
  example.invalid werden nicht abgefragt (Abrufpolitik, CLAUDE.md 9), sondern nur gelistet
Ergebnis: Zusammenfassung auf der Konsole, je Fund eine Zeile im TSV; Exit-Code 1 bei defekten inneren Links.
"""
import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

NICHT_ABFRAGEN = ("stadt-koeln.de", "offenedaten-koeln.de", "example.invalid", "127.0.0.1", "localhost")
UA = "ratsatlas-koeln-linkpruefung/0.1 (+https://github.com/daimpad/ratsatlas-koeln)"


class Sammler(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        for k in ("href", "src"):
            if a.get(k) and not (tag == "link" and a.get("rel") in ("preconnect", "dns-prefetch")):
                self.links.append((tag, k, a[k]))


def lesen(pfad):
    s = Sammler()
    s.feed(pfad.read_text(encoding="utf-8", errors="replace"))
    return s


def ziel_datei(site, seite, url):
    teil = urllib.parse.urlparse(url)
    pfad = urllib.parse.unquote(teil.path)
    basis = site if pfad.startswith("/") else seite.parent
    z = (basis / pfad.lstrip("/")).resolve() if pfad else seite
    if z.is_dir():
        z = z / "index.html"
    return z, teil.fragment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site", nargs="?", default="_site")
    ap.add_argument("--extern", action="store_true")
    ap.add_argument("--tsv")
    a = ap.parse_args()
    site = Path(a.site).resolve()
    seiten = sorted(site.rglob("*.html"))
    cache, funde, extern = {}, [], {}
    for seite in seiten:
        s = cache.setdefault(seite, lesen(seite))
        for tag, attr, url in s.links:
            if url.startswith(("mailto:", "tel:", "data:", "javascript:")) or "${" in url:
                continue
            if re.match(r"^https?://", url):
                extern.setdefault(url, seite.relative_to(site).as_posix())
                continue
            z, anker = ziel_datei(site, seite, url)
            rel = seite.relative_to(site).as_posix()
            if not z.exists():
                funde.append(("intern", "fehlt", rel, url, ""))
            elif anker and z.suffix == ".html" and "?" not in url:   # „?gebiet=…#Vorlage“ ist ein Zustand der Karte
                ids = cache.setdefault(z, lesen(z)).ids
                if anker not in ids:
                    funde.append(("anker", "fehlt", rel, url, ""))
    geprueft = 0
    if a.extern:
        for url, von in sorted(extern.items()):
            host = urllib.parse.urlparse(url).hostname or ""
            if any(host == h or host.endswith("." + h) for h in NICHT_ABFRAGEN):
                funde.append(("extern", "nicht abgefragt", von, url, "Server der Stadt oder Platzhalter"))
                continue
            status = ""
            for methode in ("HEAD", "GET"):
                try:
                    req = urllib.request.Request(url, method=methode, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        status = str(r.status)
                    break
                except urllib.error.HTTPError as e:
                    status = str(e.code)
                except Exception as e:  # Netzfehler: als Befund festhalten
                    status = type(e).__name__
            geprueft += 1
            if not status.startswith(("2", "3")):
                funde.append(("extern", status, von, url, ""))
            time.sleep(1)
    if a.tsv:
        with open(a.tsv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(["art", "befund", "seite", "link", "anmerkung"])
            w.writerows(funde)
    defekt = [f for f in funde if f[0] in ("intern", "anker")]
    print(f"{len(seiten)} Seiten, {len(extern)} äußere Adressen ({geprueft} geprüft), "
          f"{len(defekt)} defekte innere Links oder Sprungmarken, "
          f"{sum(1 for f in funde if f[0] == 'extern' and f[1] != 'nicht abgefragt')} auffällige äußere Links")
    for f in defekt[:30]:
        print("  ", *f)
    sys.exit(1 if defekt else 0)


if __name__ == "__main__":
    main()
