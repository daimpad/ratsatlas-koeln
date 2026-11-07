"""Statische Seiten je Stadtteil und Stadtbezirk sowie eine Übersicht (gebiete/), damit Suchmaschinen
die Inhalte der Karte finden. Grundlage sind die Gebietsdateien in _site/data/export/koeln/.

Seiten entstehen für alle Stadtteile und Stadtbezirke, auch ohne Vorlagen (etwa in der Kartenvorschau). Je Seite:
- mit Vorlagen: Überblick, Themen, die 20 jüngsten Vorlagen mit Stand und Links (Karte, Original);
- Kennzahlen aus kontext.json (pipeline/kontext.py) im Vergleich Stadtteil – Stadtbezirk – ganz Köln, mit Quellen,
  Lizenzen, Stand und Methode; unter der Mindestgröße keine Anteile und Mittelwerte;
- Links auf die Kartenebenen aus ebenen.json (pipeline/ebenen.py) mit Quelle und Lizenz.
Kennzahlen und Ebenen nur, wenn das Zusatzthema „kontext“ freigegeben ist (config.ZUSATZTHEMEN, wie die Karte).
Keine Erzeugungszeitpunkte, damit sich der Branch deploy nur bei Inhaltsänderungen ändert."""
import json
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from urllib.parse import quote

from . import begriffsseite, config, topics
from .kontext import ANTEILE

LATEST = 20
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'none'")
VORSCHAU = (f"<p><strong>Vorschau:</strong> Die Ratsvorlagen der Stadt {config.STADT_NAME} folgen, sobald der Abruf "
            "aus dem Ratsinformationssystem eingerichtet ist.</p>")


def _date(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else "–"


def _stand(text):
    """Stand einer Quelle: ISO-Datum als TT.MM.JJJJ, sonst unverändert (z. B. „laufend aktualisiert, Abruf …“)."""
    return _date(text) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or "") else (text or "")


def _de(v, min_stellen=0, max_stellen=0):
    """Zahl in deutscher Schreibweise wie in der Karte (Tausenderpunkt, Dezimalkomma, kaufmännisch gerundet)."""
    d = Decimal(str(v)).quantize(Decimal(1).scaleb(-max_stellen), ROUND_HALF_UP)
    ganz, _, nach = f"{d:,.{max_stellen}f}".partition(".")
    nach = nach.rstrip("0").ljust(min_stellen, "0")
    return ganz.replace(",", ".") + ("," + nach if nach else "")


def _sortname(name):
    return name.lower().translate(str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}))


def _vorlagen_zahl(n):
    return f"{n} Vorlage" if n == 1 else f"{n} Vorlagen"


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


def _map_url(root, key):
    return f"{root}?gebiet={quote(key, safe=':')}"




def _area_body(kind_label, name, where, key, papers, root):
    """Vorlagen eines Gebiets: Überblick, jüngste Vorlagen, Begriffe; where ist bereits HTML (Name, Stadtbezirk)."""
    stand = Counter(p["stand"] for p in papers)
    # alle Themen einer Vorlage zählen, wie die Karte (gebietszahlen.shares); das erste Thema folgt nur der
    # Reihenfolge in topics.THEMES und bevorzugte Verkehr (Code-Prüfung 24.10.2026)
    themes = Counter(th for p in papers for th in {t["theme"] for t in (p.get("themes") or [])})
    dates = sorted(p["date"] for p in papers if p.get("date"))
    latest = sorted(papers, key=lambda p: (p.get("date") or "", p["reference"]), reverse=True)[:LATEST]
    map_url = _map_url(root, key)
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
    <p class="lead">{escape(kind_label)} {where}: Vorlagen aus dem Ratsinformationssystem der Stadt Köln mit Ortsbezug – auf der Karte, mit Verfahrensstand, Gremien und Quellen.</p>
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


def _ohne_vorlagen(titel, lead, map_url, map_text, leer):
    """Kopf einer Gebietsseite ohne Vorlagen (Kartenvorschau oder Gebiet ohne verortete Vorlage)."""
    return f"""    <h1>{titel}</h1>
    <p class="lead">{lead}</p>
    {leer}
    <p><a class="page-back" href="{map_url}">{map_text}</a></p>"""


def _zelle(key, werte, meta, anteile):
    """Wert einer Kennzahl wie in der Karte (site/app.js, kCell); unter der Mindestgröße keine Anteile und Mittelwerte."""
    d = meta["kennzahlen"][key]
    mindest = meta.get("mindest_einwohner") or 0
    if key in anteile and werte.get("einwohner") is not None and werte["einwohner"] < mindest:
        return f"keine Angabe (unter {_de(mindest)} Einwohnern)"
    v = werte.get(key)
    if v is None:
        return f"keine Angabe ({escape(d['ohne_wert'])})" if d.get("ohne_wert") else "keine Angabe"
    einheit = d.get("einheit")
    text = (f"{_de(v, 0, 1)} %" if einheit == "%" else
            f"{_de(v, 2 if key == 'miete' else 0, 2)} €/m²" if einheit == "€/m²" else _de(v))
    # Bodenrichtwert: Hinweis, wenn viele Einwohner außerhalb von Zonen für Wohnbauland wohnen (Schwelle aus kontext.json)
    cov, ab = werte.get("bodenrichtwert_abdeckung"), meta.get("bodenrichtwert_hinweis_ohne_zone")
    if key == "bodenrichtwert" and cov is not None and ab is not None and 100 - cov >= ab:
        text += f"<br><small>gilt für {_de(cov)} % der Einwohner</small>"   # Erklärung unter „Methode“
    return text


def _quelle(key, q):
    """Listeneintrag einer Quelle: Titel (verlinkt), Lizenz, Stand."""
    if not q:
        return f"<li>{escape(key)}: Angaben zur Quelle fehlen (ungeprüft)</li>"
    titel = escape(q.get("titel") or key)
    if re.match(r"https?://", q.get("url") or ""):
        titel = f'<a href="{escape(q["url"])}">{titel}</a>'
    teile = [f"Lizenz: {escape(q['lizenz'])}" if q.get("lizenz") else "Lizenz: nicht angegeben"]
    if q.get("stand"):
        teile.append(f"Stand: {escape(_stand(q['stand']))}")
    if q.get("uebergang"):
        teile.append(escape(q["uebergang"]))
    return f"<li>{titel} – {'; '.join(teile)}</li>"


def _kennzahlen(kx, spalten):
    """Vergleichstabelle (spalten: [(Überschrift, Werte)], zuerst das Gebiet der Seite), Quellen und Methode."""
    meta = kx.get("meta") or {}
    kz = meta.get("kennzahlen") or {}
    keys = [k for k in (meta.get("reihenfolge") or kz) if k in kz]
    if not keys or not spalten:
        return ""
    # Anteile und Mittelwerte: wie pipeline/kontext.py, dazu jede Kennzahl in % oder €/m²
    anteile = set(ANTEILE) | {k for k, d in kz.items() if d.get("einheit") in ("%", "€/m²")}
    mindest = meta.get("mindest_einwohner") or 0
    klein = any(w.get("einwohner") is not None and w["einwohner"] < mindest for _, w in spalten)
    # Umbruch nach „/“ erlauben (Altstadt/Nord), damit schmale Spalten auf dem Telefon nicht mitten im Wort brechen
    kopf = "".join(f'<th scope="col">{escape(t).replace("/", "/<wbr>")}</th>' for t, _ in spalten)
    zeilen = "\n".join(
        f'        <tr><th scope="row">{escape(kz[k]["titel"])}</th>'
        + "".join(f"<td>{_zelle(k, w, meta, anteile)}</td>" for _, w in spalten) + "</tr>"
        for k in keys)
    vergleich = " und ".join(t for t, _ in spalten[1:])
    caption = f"Kennzahlen für {spalten[0][0]}" + (f" im Vergleich mit {vergleich}" if vergleich else "")
    alle_quellen = meta.get("quellen") or {}
    quellen = "\n".join(f"      {_quelle(q, alle_quellen.get(q))}" for q in dict.fromkeys(kz[k]["quelle"] for k in keys))
    methoden = "\n".join(
        f'      <li><strong>{escape(kz[k]["titel"])}</strong> ({escape(kz[k].get("einheit") or "")}): '
        f'{escape(kz[k].get("methode") or "Methode nicht angegeben")}</li>' for k in keys)
    regel = f"Für Gebiete unter {_de(mindest)} Einwohnern stehen keine Anteile und Mittelwerte." if mindest else ""
    ab = meta.get("bodenrichtwert_hinweis_ohne_zone")
    if "bodenrichtwert" in keys and ab is not None:
        methoden += (f"\n      <li><strong>Hinweis zum Bodenrichtwert:</strong> Wohnen mindestens {_de(ab)} % der Einwohner "
                     "außerhalb von Zonen für Wohnbauland, nennt die Tabelle den Anteil der Einwohner, für den der Wert gilt.</li>")
    return f"""    <h2>Kennzahlen zur Einordnung</h2>
    <p>Einordnung, kein Urteil über das Gebiet. Alle Werte sind auf Stadtteile und Stadtbezirke umgerechnet und damit abgeleitet; die Stichtage der Quellen sind verschieden.{" " + regel if klein and regel else ""}</p>
    <table class="kennzahlen">
      <caption>{escape(caption)}</caption>
      <thead><tr><th scope="col">Kennzahl</th>{kopf}</tr></thead>
      <tbody>
{zeilen}
      </tbody>
    </table>
    <h3>Quellen und Lizenzen</h3>
    <ul>
{quellen}
    </ul>
    <h3>Methode</h3>
    <ul>
{methoden}{f"{chr(10)}      <li><strong>Mindestgröße:</strong> {regel}</li>" if regel else ""}
    </ul>"""


def _ebenen(ebenen, map_url, fuer):
    """Hinweis auf die Kartenebenen (ebenen.json) mit Links in die Karte für dieses Gebiet."""
    if not ebenen:
        return ""
    items = []
    for e in ebenen:
        kurz = e.get("kurz") or e.get("titel") or e["key"]
        link = f'<a href="{map_url}&amp;ebenen={quote(e["key"])}">{escape(kurz)} auf der Karte</a>'
        if e.get("titel") and e["titel"] != kurz:
            link += f": {escape(e['titel'])}"
        quelle = escape(e.get("quelle") or "nicht angegeben")
        if re.match(r"https?://", e.get("url") or ""):
            quelle = f'<a href="{escape(e["url"])}">{quelle}</a>'
        angaben = f"Quelle: {quelle}; Lizenz: {escape(e.get('lizenz') or 'nicht angegeben')}"
        if e.get("stand"):   # ebenen.json: Tag des Abrufs (data/ebenen/STAND.json)
            angaben += f"; abgerufen am {escape(_stand(e['stand']))}"
        items.append(f"      <li>{link}<br><small>{angaben}</small></li>")
    return f"""    <h2>Kartenebenen</h2>
    <p>Auf der Karte lassen sich {escape(fuer)} weitere Ebenen aus offenen Daten zuschalten. Jeder Link öffnet die Karte mit dieser Ebene. Die Ebenen dienen der Einordnung; maßgeblich sind die Quellen.</p>
    <ul>
{chr(10).join(items)}
    </ul>"""


def _stadtteile(name, ortsteile, root, mit_zahl):
    """Liste der Stadtteile eines Stadtbezirks mit Links auf ihre Seiten."""
    items = "\n".join(
        f'      <li><a href="{root}ortsteil/{o["slug"]}/">{escape(o["name"])}</a>'
        + (f' ({_vorlagen_zahl(o["count"])})' if mit_zahl else "") + "</li>"
        for o in sorted(ortsteile, key=lambda o: _sortname(o["name"])))
    return f"""    <h2>Stadtteile im Stadtbezirk {escape(name)}</h2>
    <ul>
{items}
    </ul>"""


def _laden(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _schreiben(site, site_url, path, title, description, body, head):
    out = site / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page(site_url, path, title, description, body, "../../", head), encoding="utf-8")


def write(site, site_url):
    """Schreibt die Gebietsseiten nach site; gibt die Pfade relativ zu site_url zurück (für die Sitemap)."""
    base = site / "data" / "export" / "koeln"
    index = _laden(base / "index.json")
    if not index:
        return []
    vorschau = bool((index.get("meta") or {}).get("vorschau"))
    kontext_an = config.ZUSATZTHEMEN.get("kontext")   # wie die Karte: Kennzahlen und Ebenen nur bei Freigabe
    kx = _laden(base / "kontext.json") if kontext_an else None
    ebenen = ((_laden(base / "ebenen.json") or {}).get("ebenen") or []) if kontext_an else []
    stadt = f"ganz {config.STADT_NAME}"
    root = "../../"
    zusatz = [t for t, da in (("Kennzahlen", kx), ("Kartenebenen", ebenen)) if da]
    zusatz_text = " und ".join(zusatz)
    bezirk_slug = {b["name"]: b["slug"] for b in index["bezirke"]}
    leer_satz = VORSCHAU if vorschau else ""
    paths = []

    def head(datei, titel):
        return feed_head(datei, titel, root) if (base / datei).exists() else ""

    for o in index["ortsteile"]:
        name, bz, key = o["name"], o["stadtbezirk"], f"ortsteil:{o['slug']}"
        data_file = base / "ortsteile" / f"{o['slug']}.json"
        papers = json.loads(data_file.read_text(encoding="utf-8"))["papers"] if o["count"] and data_file.exists() else []
        bz_html = (f'<a href="{root}stadtbezirk/{bezirk_slug[bz]}/">{escape(bz)}</a>' if bz in bezirk_slug else escape(bz))
        map_url = _map_url(root, key)
        teile = []
        if papers:
            teile.append(_area_body("Stadtteil", name, f"{escape(name)} (Stadtbezirk {bz_html})", key, papers, root))
        else:
            leer = leer_satz or f"<p>Im Ratsatlas ist derzeit keine Vorlage mit Ortsbezug zu {escape(name)} verzeichnet.</p>"
            teile.append(_ohne_vorlagen(
                f"Stadtteil {escape(name)}",
                f"Stadtteil im Stadtbezirk {bz_html} der Stadt {config.STADT_NAME}."
                + (f" Auf dieser Seite: {zusatz_text} zur Einordnung, mit Quellen." if zusatz else ""),
                map_url, f"{escape(name)} auf der Karte öffnen", leer))
        if kx and name in (kx.get("ortsteile") or {}):
            spalten = [(name, kx["ortsteile"][name])]
            if bz in (kx.get("bezirke") or {}):
                spalten.append((f"Stadtbezirk {bz}", kx["bezirke"][bz]))
            if kx.get("stadt"):
                spalten.append((stadt, kx["stadt"]))
            teile.append(_kennzahlen(kx, spalten))
        teile.append(_ebenen(ebenen, map_url, f"für {name}"))
        path = f"ortsteil/{o['slug']}/"
        if papers:
            title = f"Ratsvorlagen in {name} – Ratsatlas Köln"
            description = (f"Was berät die Politik in {name} (Köln)? {len(papers)} Vorlagen aus dem "
                           "Ratsinformationssystem mit Ort, Stand und Gremien.")
        else:
            title = f"Stadtteil {name}" + (f": {zusatz_text}" if zusatz else "") + " – Ratsatlas Köln"
            description = (f"Stadtteil {name} im Stadtbezirk {bz} (Köln)"
                           + (": Kennzahlen im Vergleich mit dem Stadtbezirk und ganz Köln, mit Quellen und Lizenzen" if kx else "")
                           + ("; Kartenebenen aus offenen Daten" if ebenen else "") + "."
                           + (" Die Ratsvorlagen folgen." if vorschau else ""))
        _schreiben(site, site_url, path, title, description, "\n".join(t for t in teile if t),
                   head(f"feeds/ortsteil-{o['slug']}.xml", f"Ratsatlas Köln – {name}"))
        paths.append(path)

    for b in index["bezirke"]:
        name, key = b["name"], f"bezirk:{b['slug']}"
        data_file = base / "bezirke" / f"{b['slug']}.json"
        papers = json.loads(data_file.read_text(encoding="utf-8"))["papers"] if b["count"] and data_file.exists() else []
        ortsteile = [o for o in index["ortsteile"] if o["stadtbezirk"] == name]
        map_url = _map_url(root, key)
        teile = []
        if papers:
            teile.append(_area_body("Stadtbezirk", name, escape(name), key, papers, root))
        else:
            leer = leer_satz or ("<p>Derzeit ist keine Vorlage verzeichnet, die sich auf den ganzen Stadtbezirk ohne "
                                 "genaueren Ort bezieht; Vorlagen zu einzelnen Stadtteilen stehen auf deren Seiten.</p>")
            teile.append(_ohne_vorlagen(
                f"Stadtbezirk {escape(name)}",
                f"Einer von {len(index['bezirke'])} Stadtbezirken der Stadt {config.STADT_NAME}; er umfasst "
                f"{len(ortsteile)} Stadtteile." + (f" Auf dieser Seite: {zusatz_text} zur Einordnung, mit Quellen." if zusatz else ""),
                map_url, f"Stadtbezirk {escape(name)} auf der Karte öffnen", leer))
        teile.append(_stadtteile(name, ortsteile, root, not vorschau))
        if kx and name in (kx.get("bezirke") or {}):
            spalten = [(f"Stadtbezirk {name}", kx["bezirke"][name])] + ([(stadt, kx["stadt"])] if kx.get("stadt") else [])
            teile.append(_kennzahlen(kx, spalten))
        teile.append(_ebenen(ebenen, map_url, f"für den Stadtbezirk {name}"))
        path = f"stadtbezirk/{b['slug']}/"
        if papers:
            title = f"Ratsvorlagen im Stadtbezirk {name} – Ratsatlas Köln"
            description = (f"Vorlagen aus dem Ratsinformationssystem mit Bezug zum ganzen Stadtbezirk {name} (Köln), "
                           "ohne genaueren Ort.")
        else:
            title = f"Stadtbezirk {name}" + (f": {zusatz_text}" if zusatz else "") + " – Ratsatlas Köln"
            description = (f"Stadtbezirk {name} (Köln) mit {len(ortsteile)} Stadtteilen"
                           + (": Kennzahlen im Vergleich mit ganz Köln, mit Quellen und Lizenzen" if kx else "")
                           + ("; Kartenebenen aus offenen Daten" if ebenen else "") + "."
                           + (" Die Ratsvorlagen folgen." if vorschau else ""))
        _schreiben(site, site_url, path, title, description, "\n".join(t for t in teile if t),
                   head(f"feeds/bezirk-{b['slug']}.xml", f"Ratsatlas Köln – Stadtbezirk {name}, ohne genaueren Ort"))
        paths.append(path)

    sections = []
    for b in index["bezirke"]:
        ortsteile = sorted((o for o in index["ortsteile"] if o["stadtbezirk"] == b["name"]), key=lambda o: _sortname(o["name"]))
        items = "\n".join(f'      <li><a href="../ortsteil/{o["slug"]}/">{escape(o["name"])}</a>'
                          + ("" if vorschau else f' ({_vorlagen_zahl(o["count"])})') + "</li>" for o in ortsteile)
        sections.append(
            f'    <h2>Stadtbezirk {escape(b["name"])}</h2>\n'
            f'    <p><a href="../stadtbezirk/{b["slug"]}/">Stadtbezirk {escape(b["name"])} im Überblick</a>'
            + ("" if vorschau else f' ({_vorlagen_zahl(b["count"])} zum ganzen Stadtbezirk, ohne genaueren Ort)') + "</p>\n"
            f"    <ul>\n{items}\n    </ul>")
    anzahl = f"{len(index['bezirke'])} Stadtbezirke und {len(index['ortsteile'])} Stadtteile der Stadt {config.STADT_NAME}"
    extra = f"{zusatz_text} zur Einordnung" if zusatz else ""
    if vorschau:
        h1 = "Stadtteile und Stadtbezirke"
        lead = f"Alle {anzahl}" + (f", je mit {extra}" if extra else "") + "."
    else:
        h1 = "Ratsvorlagen nach Gebiet"
        lead = (f"Alle {anzahl} mit den Vorlagen aus dem Ratsinformationssystem, die sich auf sie beziehen"
                + (f", und mit {extra}" if extra else "") + ".")
    hub = f"""    <h1>{h1}</h1>
    <p class="lead">{escape(lead)}</p>
{("    " + VORSCHAU + chr(10)) if vorschau else ""}{chr(10).join(sections)}"""
    inhalt = ([] if vorschau else ["ihren Vorlagen aus dem Ratsinformationssystem"]) + zusatz
    (site / "gebiete").mkdir(parents=True, exist_ok=True)
    (site / "gebiete" / "index.html").write_text(
        _page(site_url, "gebiete/", f"{h1} – Ratsatlas Köln",
              "Übersicht der Kölner Stadtteile und Stadtbezirke"
              + (" mit " + ", ".join(inhalt[:-1]) + (" und " if len(inhalt) > 1 else "") + inhalt[-1] if inhalt else "") + ".",
              hub, "../"),
        encoding="utf-8")
    print(f"Gebietsseiten: {len(paths)} ({len(index['ortsteile'])} Stadtteile, {len(index['bezirke'])} Stadtbezirke) und Übersicht")
    return ["gebiete/", *paths]
