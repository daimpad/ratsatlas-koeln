"""Statische Seiten je Stadtteil und Stadtbezirk sowie eine Übersicht (gebiete/), damit Suchmaschinen
die Inhalte der Karte finden. Grundlage sind die Gebietsdateien in _site/data/export/koeln/.

Je Seite: Kennzahlen, Themen, die 20 jüngsten Vorlagen mit Stand und Links (Karte, Original).
Keine Erzeugungszeitpunkte, damit sich der Branch deploy nur bei Inhaltsänderungen ändert."""
import json
import re
from collections import Counter
from html import escape
from urllib.parse import quote

from . import begriffsseite, config, topics

LATEST = 20
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'none'")


def _date(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else "–"


# Externe Links öffnen in einem neuen Tab (Entscheidung des Auftraggebers 28.10.2026), z. B. die PDF der Stadt
EIGENE = ("koeln.ratsatlas.de", "daimpad.github.io/ratsatlas-koeln")
_EXTERN = re.compile(r'<a\s(?![^>]*\btarget=)([^>]*\bhref="https?://(?!(?:%s))[^"]*"[^>]*)>' % "|".join(re.escape(h) for h in EIGENE))


def neuer_tab(html):
    """Ergänzt target="_blank" (und rel="noopener", falls kein rel gesetzt ist) an externen Links ohne target."""
    return _EXTERN.sub(lambda m: f'<a {m.group(1)} target="_blank"' + ("" if " rel=" in m.group(0) else ' rel="noopener"') + ">", html)


def feed_head(datei, titel, root):
    """Verweis für die automatische Feed-Erkennung im Kopf (zusätzlich zum Feed über ganz Köln, den _page setzt)."""
    return (f'\n  <link rel="alternate" type="application/atom+xml" title="{escape(titel)}" '
            f'href="{root}data/export/koeln/{datei}">')


def _page(site_url, path, title, description, body, root, head=""):
    return neuer_tab(f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CSP}">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(description)}">
  <link rel="canonical" href="{escape(site_url + path)}">
  <link rel="icon" href="{root}favicon.ico" sizes="32x32">
  <link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="{root}page.css">{head}
  <link rel="alternate" type="application/atom+xml" title="Ratsatlas Köln – ganz Köln" href="{root}data/export/koeln/feeds/ganz-koeln.xml">
</head>
<body>
  <header class="page-head">
    <a class="page-brand" href="{root}"><img src="{root}favicon.svg" width="32" height="32" alt="">Ratsatlas <span>Köln</span></a>
    <a class="page-back" href="{root}">Zur Karte</a>
  </header>
  <main class="page">
{body}
  </main>
  <footer class="page-foot">
    <a href="{root}gebiete/">Alle Gebiete</a> · <a href="{root}begriffe/">Begriffe</a> · <a href="{root}rss/">Abonnieren (RSS)</a> · <a href="https://nozilla.de/impressum/">Impressum</a> · <a href="{root}datenschutz.html">Datenschutz</a> · <a href="mailto:contact@nozilla.de">Kontakt</a>
    <br>{escape(config.NAMENSNENNUNG)} · <a href="{root}data/LICENSE-DATA.md">Lizenzen der Daten</a>
  </footer>
</body>
</html>
""")


def _area_body(kind_label, name, bezirk, key, papers, root):
    stand = Counter(p["stand"] for p in papers)
    # alle Themen einer Vorlage zählen, wie die Karte (gebietszahlen.shares); das erste Thema folgt nur der
    # Reihenfolge in topics.THEMES und bevorzugte Verkehr (Code-Prüfung 24.10.2026)
    themes = Counter(th for p in papers for th in {t["theme"] for t in (p.get("themes") or [])})
    dates = sorted(p["date"] for p in papers if p.get("date"))
    latest = sorted(papers, key=lambda p: (p.get("date") or "", p["reference"]), reverse=True)[:LATEST]
    map_url = f"{root}?gebiet={quote(key, safe=':')}"
    where = f"{name}" + (f" (Stadtbezirk {bezirk})" if bezirk else "")
    rows = "\n".join(
        f'      <tr><td>{_date(p.get("date"))}</td><td><a href="{map_url}#{quote(p["reference"])}">{escape(p["reference"])}</a></td>'
        f'<td>{escape(p["name"])}<br><small>{escape(p["paper_type"])}'
        + (f' · <a href="{escape(p["web"])}">Original</a>' if p.get("web") else "")
        + f'</small></td><td>{escape(p["stand"])}</td></tr>'
        for p in latest)
    theme_list = ", ".join(f"{escape(dict(topics.THEMES).get(k, k))} ({n})" for k, n in themes.most_common(5))
    stand_list = ", ".join(f"{escape(k)}: {n}" for k, n in stand.most_common())
    begriffe = begriffsseite.akkordeon([*stand, *(p["paper_type"] for p in latest)], root)   # Entscheidung 02.11.2026
    return f"""    <h1>Ratsvorlagen in {escape(name)}</h1>
    <p class="lead">{escape(kind_label)} {escape(where)}: Vorlagen aus dem Ratsinformationssystem der Stadt Köln mit Ortsbezug – auf der Karte, mit Verfahrensstand, Gremien und Quellen.</p>
    <p><a class="page-back" href="{map_url}">Alle {len(papers)} Vorlagen auf der Karte öffnen</a></p>
    <h2>Überblick</h2>
    <ul>
      <li>{len(papers)} Vorlagen{f" von {_date(dates[0])} bis {_date(dates[-1])}" if dates else ""}</li>
      <li>Stand: {stand_list or "–"}</li>
      <li>Häufigste Themen (abgeleitet; eine Vorlage kann mehrere haben): {theme_list or "–"}</li>
    </ul>
    <h2>Die {len(latest)} jüngsten Vorlagen</h2>
    <table>
      <thead><tr><th scope="col">Datum</th><th scope="col">Drucksache</th><th scope="col">Titel</th><th scope="col">Stand</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
{begriffe}    <p class="meta">Quelle: Ratsinformationssystem der Stadt Köln (OParl-API). Datenquelle: Stadt Köln – offenedaten-koeln.de. Der Ortsbezug ist teils aus dem Titel erschlossen; Einzelheiten und Fundstellen stehen im Vorgang auf der Karte. Maßgeblich ist das Original im Ratsinformationssystem.</p>"""


def write(site, site_url):
    """Schreibt die Gebietsseiten nach site; gibt die Pfade relativ zu site_url zurück (für die Sitemap)."""
    base = site / "data" / "export" / "koeln"
    index_file = base / "index.json"
    if not index_file.exists():
        return []
    index = json.loads(index_file.read_text(encoding="utf-8"))
    paths, groups = [], {}
    root = "../../"
    for o in index["ortsteile"]:
        data_file = base / "ortsteile" / f"{o['slug']}.json"
        if not data_file.exists() or not o["count"]:
            continue
        papers = json.loads(data_file.read_text(encoding="utf-8"))["papers"]
        path = f"ortsteil/{o['slug']}/"
        body = _area_body("Stadtteil", o["name"], o["stadtbezirk"], f"ortsteil:{o['slug']}", papers, root)
        out = site / path / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_page(site_url, path, f"Ratsvorlagen in {o['name']} – Ratsatlas Köln",
                             f"Was berät die Politik in {o['name']} (Köln)? {len(papers)} Vorlagen aus dem Ratsinformationssystem mit Ort, Stand und Gremien.",
                             body, root, feed_head(f"feeds/ortsteil-{o['slug']}.xml", f"Ratsatlas Köln – {o['name']}", root)),
                       encoding="utf-8")
        paths.append(path)
        groups.setdefault(o["stadtbezirk"], []).append((o["name"], path, len(papers)))
    for b in index["bezirke"]:
        data_file = base / "bezirke" / f"{b['slug']}.json"
        if not data_file.exists() or not b["count"]:
            continue
        papers = json.loads(data_file.read_text(encoding="utf-8"))["papers"]
        path = f"stadtbezirk/{b['slug']}/"
        body = _area_body("Stadtbezirk", b["name"], None, f"bezirk:{b['slug']}", papers, root)
        out = site / path / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_page(site_url, path, f"Ratsvorlagen im Stadtbezirk {b['name']} – Ratsatlas Köln",
                             f"Vorlagen aus dem Ratsinformationssystem mit Bezug zum ganzen Stadtbezirk {b['name']} (Köln), ohne genaueren Ort.",
                             body, root, feed_head(f"feeds/bezirk-{b['slug']}.xml",
                                                   f"Ratsatlas Köln – Stadtbezirk {b['name']}, ohne genaueren Ort", root)),
                       encoding="utf-8")
        paths.append(path)
        groups.setdefault(b["name"], []).append((f"ganzer Stadtbezirk {b['name']}", path, len(papers)))
    sections = "\n".join(
        f'    <h2>Stadtbezirk {escape(bz)}</h2>\n    <ul>\n'
        + "\n".join(f'      <li><a href="../{p}">{escape(n)}</a> ({c} Vorlagen)</li>' for n, p, c in sorted(items))
        + "\n    </ul>"
        for bz, items in sorted(groups.items()))
    hub = f"""    <h1>Ratsvorlagen nach Gebiet</h1>
    <p class="lead">Alle Stadtteile und Stadtbezirke der Stadt Köln mit den Vorlagen aus dem Ratsinformationssystem, die sich auf sie beziehen.</p>
{sections}"""
    (site / "gebiete").mkdir(parents=True, exist_ok=True)
    (site / "gebiete" / "index.html").write_text(
        _page(site_url, "gebiete/", "Ratsvorlagen nach Gebiet – Ratsatlas Köln",
              "Übersicht der Kölner Stadtteile und Stadtbezirke mit ihren Vorlagen aus dem Ratsinformationssystem.", hub, "../"),
        encoding="utf-8")
    print(f"Gebietsseiten: {len(paths)} und Übersicht")
    return ["gebiete/", *paths]
