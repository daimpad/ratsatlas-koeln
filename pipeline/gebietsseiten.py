"""Statische Seiten je Stadtteil und Stadtbezirk sowie eine Übersicht (gebiete/), damit Suchmaschinen
die Inhalte der Karte finden. Grundlage sind die Gebietsdateien in _site/data/export/koeln/.

Seiten entstehen für alle Stadtteile und Stadtbezirke, auch ohne Vorlagen (etwa in der Kartenvorschau). Je Seite:
- mit Vorlagen: Überblick, Themen, die 20 jüngsten Vorlagen mit Stand und Links (Karte, Original);
- Kennzahlen aus kontext.json (pipeline/kontext.py) im Vergleich Stadtteil – Stadtbezirk – ganz Köln, mit Quellen,
  Lizenzen, Stand und Methode; unter der Mindestgröße keine Anteile und Mittelwerte;
- Links auf die Kartenebenen aus ebenen.json (pipeline/ebenen.py) mit Quelle und Lizenz.
Kennzahlen und Ebenen nur, wenn das Zusatzthema „kontext“ freigegeben ist (config.ZUSATZTHEMEN, wie die Karte); Titel,
Einleitung und Beschreibung nennen nur, was die einzelne Seite tatsächlich enthält.
Keine Erzeugungszeitpunkte und feste Reihenfolgen (auch bei gleich häufigen Themen), damit die Seiten bei gleichem Inhalt
byte-gleich bleiben und sich der Branch deploy nur bei Inhaltsänderungen ändert (tests/test_gebietsseiten.py, zwei Läufe
mit verschiedenem PYTHONHASHSEED)."""
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
ZOOM_HINWEIS = "Viele Objekte: erscheint erst bei näherer Ansicht, falls nötig hineinzoomen"
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




def _haeufigste(zaehler, n=None):
    """Einträge nach Häufigkeit, bei gleicher Zahl nach Schlüssel: feste Reihenfolge unabhängig von der Zählreihenfolge
    (Counter.most_common ordnet Gleichstände nach dem Einfügen, und das hing an der Reihenfolge einer Menge)."""
    return sorted(zaehler.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def _area_body(bezirk, name, where, key, papers, root):
    """Vorlagen eines Gebiets: Überblick, jüngste Vorlagen, Begriffe; where ist bereits HTML (Name, Stadtbezirk).
    bezirk: Seite eines Stadtbezirks (Vorlagen zum ganzen Stadtbezirk, ohne genaueren Ort), sonst eines Stadtteils."""
    stand = Counter(p["stand"] for p in papers)
    # alle Themen einer Vorlage zählen, wie die Karte (gebietszahlen.shares); das erste Thema folgt nur der
    # Reihenfolge in topics.THEMES und bevorzugte Verkehr (Code-Prüfung 24.10.2026)
    themes = Counter(th for p in papers for th in {t["theme"] for t in (p.get("themes") or [])})
    dates = sorted(p["date"] for p in papers if p.get("date"))
    latest = sorted(papers, key=lambda p: (p.get("date") or "", p["reference"]), reverse=True)[:LATEST]
    map_url = _map_url(root, key)
    alle = "Die Vorlage" if len(papers) == 1 else f"Alle {len(papers)} Vorlagen"
    if bezirk:
        h1 = f"Ratsvorlagen im Stadtbezirk {escape(name)}"
        lead = (f"Stadtbezirk {where}: Vorlagen aus dem Ratsinformationssystem der Stadt Köln zum ganzen Stadtbezirk, ohne "
                "genaueren Ort – auf der Karte, mit Verfahrensstand, Gremien und Quellen. Vorlagen zu einzelnen Stadtteilen "
                "stehen auf deren Seiten.")
        karte = f"{alle} zum ganzen Stadtbezirk auf der Karte öffnen"
    else:
        h1 = f"Ratsvorlagen in {escape(name)}"
        lead = (f"Stadtteil {where}: Vorlagen aus dem Ratsinformationssystem der Stadt Köln mit Ortsbezug – auf der Karte, "
                "mit Verfahrensstand, Gremien und Quellen.")
        karte = f"{alle} auf der Karte öffnen"
    rows = "\n".join(
        f'      <tr><td>{_date(p.get("date"))}</td><td><a href="{map_url}#{quote(p["reference"])}">{escape(p["reference"])}</a></td>'
        f'<td>{escape(p["name"])}<br><small>{escape(p["paper_type"])}'
        + (f' · <a href="{escape(p["web"])}">Original</a>' if p.get("web") else "")
        + f'</small></td><td>{escape(p["stand"])}</td></tr>'
        for p in latest)
    theme_list = ", ".join(f"{escape(dict(topics.THEMES).get(k, k))} ({n})" for k, n in _haeufigste(themes, 5))
    stand_list = ", ".join(f"{escape(k)}: {n}" for k, n in _haeufigste(stand))
    begriffe = begriffsseite.akkordeon([*stand, *(p["paper_type"] for p in latest)], root)   # Entscheidung 02.11.2026
    return f"""    <h1>{h1}</h1>
    <p class="lead">{lead}</p>
    <p><a class="page-back" href="{map_url}">{karte}</a></p>
    <h2>Überblick</h2>
    <ul>
      <li>{_vorlagen_zahl(len(papers))}{f" von {_date(dates[0])} bis {_date(dates[-1])}" if dates else ""}</li>
      <li>Stand: {stand_list or "–"}</li>
      <li>Häufigste Themen (abgeleitet; eine Vorlage kann mehrere haben): {theme_list or "–"}</li>
    </ul>
    <h2>{"Die jüngste Vorlage" if len(latest) == 1 else f"Die {len(latest)} jüngsten Vorlagen"}</h2>
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
    # der Hinweis zum Bodenrichtwert (Anteil der Einwohner, für den der Wert gilt) steht in dessen Methode (kontext.KENNZAHLEN)
    regel = f"Für Gebiete unter {_de(mindest)} Einwohnern stehen keine Anteile und Mittelwerte." if mindest else ""
    # Kennzahlen aus der Stadtstatistik (Freigabe „strukturdaten“, pipeline/kontext.py Option b) sind nicht umgerechnet
    stadt = [kz[k]["titel"] for k in keys if kz[k].get("quelle") == "strukturdaten"]
    abgeleitet = [kz[k]["titel"] for k in keys if kz[k].get("quelle") == "strukturdaten" and kz[k].get("abgeleitet")]
    aufzaehlen = lambda t: ", ".join(t[:-1]) + " und " + t[-1] if len(t) > 1 else "".join(t)
    umgerechnet = ("Alle Werte sind auf Stadtteile und Stadtbezirke umgerechnet und damit abgeleitet" if not stadt else
                   f"{aufzaehlen(stadt)}: Werte der Kölner Stadtstatistik je Gebiet"
                   + (f" ({aufzaehlen(abgeleitet)} vom Ratsatlas aus den Altersgruppen berechnet)" if abgeleitet else "")
                   + "; die übrigen Werte sind auf Stadtteile und Stadtbezirke umgerechnet und damit abgeleitet")
    return f"""    <h2>Kennzahlen zur Einordnung</h2>
    <p>Einordnung, kein Urteil über das Gebiet. {escape(umgerechnet)}; die Stichtage der Quellen sind verschieden.{" " + regel if klein and regel else ""}</p>
    <table class="kennzahlen">
      <caption>{escape(caption)}</caption>
      <thead><tr><th scope="col">Kennzahl</th>{kopf}</tr></thead>
      <tbody>
{zeilen}
      </tbody>
    </table>
    <h3 class="gebiet-h3">Quellen und Lizenzen</h3>
    <ul>
{quellen}
    </ul>
    <h3 class="gebiet-h3">Methode</h3>
    <ul>
{methoden}{f"{chr(10)}      <li><strong>Mindestgröße:</strong> {regel}</li>" if regel else ""}
    </ul>"""


def _ebenen(ebenen, map_url, fuer):
    """Hinweis auf die Kartenebenen (ebenen.json) mit Links in die Karte für dieses Gebiet. Ebenen mit Mindestzoom
    (ebenen.json „mindestzoom“) zeichnet die Karte erst bei näherer Ansicht; ob dafür Hineinzoomen nötig ist, hängt
    von Gebiet, Ebene und Bildschirm ab."""
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
        if e.get("mindestzoom"):
            angaben = f"{ZOOM_HINWEIS}. {angaben}"
        items.append(f"      <li>{link}<br><small>{angaben}</small></li>")
    zoom = (" Ebenen mit vielen Objekten erscheinen erst bei näherer Ansicht; sie sind vermerkt."
            if any(e.get("mindestzoom") for e in ebenen) else "")
    return f"""    <h2>Kartenebenen</h2>
    <p>Auf der Karte lassen sich {escape(fuer)} weitere Ebenen aus offenen Daten zuschalten. Jeder Link öffnet die Karte und schaltet die Ebene ein.{zoom} Die Ebenen dienen der Einordnung; maßgeblich sind die Quellen.</p>
    <ul>
{chr(10).join(items)}
    </ul>"""


def _stadtteile(name, ortsteile, root, zahlen):
    """Liste der Stadtteile eines Stadtbezirks mit Links auf ihre Seiten; zahlen: Vorlagen je slug (None: ohne Zahl)."""
    items = "\n".join(
        f'      <li><a href="{root}ortsteil/{o["slug"]}/">{escape(o["name"])}</a>'
        + (f' ({_vorlagen_zahl(zahlen[o["slug"]])})' if zahlen is not None else "") + "</li>"
        for o in sorted(ortsteile, key=lambda o: _sortname(o["name"])))
    return f"""    <h2>Stadtteile im Stadtbezirk {escape(name)}</h2>
    <ul>
{items}
    </ul>"""


def _laden(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _vorlagen(base, ordner, g):
    """Vorlagen eines Gebiets aus seiner Datei. Fehlt sie trotz count, bleibt das Gebiet ohne Vorlagen (mit Meldung);
    Übersicht, Stadtteilliste und Seite nennen dann übereinstimmend dieselbe Zahl."""
    if not g["count"]:
        return []
    datei = base / ordner / f"{g['slug']}.json"
    if not datei.exists():
        print(f"Gebietsseiten: {ordner}/{datei.name} fehlt ({g['count']} Vorlagen laut index.json) – Seite ohne Vorlagen")
        return []
    return json.loads(datei.read_text(encoding="utf-8"))["papers"]


def _zusatz(kennzahlen, ebenen):
    """Was die Seite neben den Vorlagen enthält, für Titel und Einleitung, z. B. „Kennzahlen und Kartenebenen“."""
    return " und ".join(t for t, da in (("Kennzahlen", kennzahlen), ("Kartenebenen", ebenen)) if da)


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
    kx = (_laden(base / "kontext.json") or {}) if kontext_an else {}
    ebenen = ((_laden(base / "ebenen.json") or {}).get("ebenen") or []) if kontext_an else []
    stadt = f"ganz {config.STADT_NAME}"
    root = "../../"
    bezirk_slug = {b["name"]: b["slug"] for b in index["bezirke"]}
    leer_satz = VORSCHAU if vorschau else ""
    # Vorlagen je Gebiet einmal laden: Seiten, Stadtteillisten und Übersicht nennen dieselbe Zahl
    ot_vorlagen = {o["slug"]: _vorlagen(base, "ortsteile", o) for o in index["ortsteile"]}
    bz_vorlagen = {b["slug"]: _vorlagen(base, "bezirke", b) for b in index["bezirke"]}
    ot_zahl = {k: len(v) for k, v in ot_vorlagen.items()}
    paths, mit_kennzahlen = [], []

    def head(datei, titel):
        return feed_head(datei, titel, root) if (base / datei).exists() else ""

    def vergleich(spalten):
        """Vergleichsspalten für die Beschreibung: „dem Stadtbezirk und ganz Köln“."""
        return " und ".join("dem Stadtbezirk" if t.startswith("Stadtbezirk ") else t for t, _ in spalten[1:])

    for o in index["ortsteile"]:
        name, bz, key = o["name"], o["stadtbezirk"], f"ortsteil:{o['slug']}"
        papers = ot_vorlagen[o["slug"]]
        bz_html = (f'<a href="{root}stadtbezirk/{bezirk_slug[bz]}/">{escape(bz)}</a>' if bz in bezirk_slug else escape(bz))
        map_url = _map_url(root, key)
        # Kennzahlen nur, wenn das Gebiet in kontext.json steht (sonst nennen Titel und Einleitung sie auch nicht)
        spalten, kennzahlen = [], ""
        if name in (kx.get("ortsteile") or {}):
            spalten = [(name, kx["ortsteile"][name])]
            if bz in (kx.get("bezirke") or {}):
                spalten.append((f"Stadtbezirk {bz}", kx["bezirke"][bz]))
            if kx.get("stadt"):
                spalten.append((stadt, kx["stadt"]))
            kennzahlen = _kennzahlen(kx, spalten)
        mit_kennzahlen.append(bool(kennzahlen))
        zusatz = _zusatz(kennzahlen, ebenen)
        teile = []
        if papers:
            teile.append(_area_body(False, name, f"{escape(name)} (Stadtbezirk {bz_html})", key, papers, root))
        else:
            leer = leer_satz or f"<p>Im Ratsatlas ist derzeit keine Vorlage mit Ortsbezug zu {escape(name)} verzeichnet.</p>"
            teile.append(_ohne_vorlagen(
                f"Stadtteil {escape(name)}",
                f"Stadtteil im Stadtbezirk {bz_html} der Stadt {config.STADT_NAME}."
                + (f" Auf dieser Seite: {zusatz} zur Einordnung, mit Quellen." if zusatz else ""),
                map_url, f"{escape(name)} auf der Karte öffnen", leer))
        teile.append(kennzahlen)
        teile.append(_ebenen(ebenen, map_url, f"für {name}"))
        path = f"ortsteil/{o['slug']}/"
        if papers:
            title = f"Ratsvorlagen in {name} – Ratsatlas Köln"
            description = (f"Was berät die Politik in {name} (Köln)? {_vorlagen_zahl(len(papers))} aus dem "
                           "Ratsinformationssystem mit Ort, Stand und Gremien.")
        else:
            title = f"Stadtteil {name}" + (f": {zusatz}" if zusatz else "") + " – Ratsatlas Köln"
            description = (f"Stadtteil {name} im Stadtbezirk {bz} (Köln)"
                           + (f": Kennzahlen im Vergleich mit {vergleich(spalten)}, mit Quellen und Lizenzen"
                              if kennzahlen and len(spalten) > 1 else ": Kennzahlen mit Quellen und Lizenzen" if kennzahlen else "")
                           + ("; Kartenebenen aus offenen Daten" if ebenen else "") + "."
                           + (" Die Ratsvorlagen folgen." if vorschau else ""))
        _schreiben(site, site_url, path, title, description, "\n".join(t for t in teile if t),
                   head(f"feeds/ortsteil-{o['slug']}.xml", f"Ratsatlas Köln – {name}"))
        paths.append(path)

    for b in index["bezirke"]:
        name, key = b["name"], f"bezirk:{b['slug']}"
        papers = bz_vorlagen[b["slug"]]
        ortsteile = [o for o in index["ortsteile"] if o["stadtbezirk"] == name]
        map_url = _map_url(root, key)
        spalten, kennzahlen = [], ""
        if name in (kx.get("bezirke") or {}):
            spalten = [(f"Stadtbezirk {name}", kx["bezirke"][name])] + ([(stadt, kx["stadt"])] if kx.get("stadt") else [])
            kennzahlen = _kennzahlen(kx, spalten)
        mit_kennzahlen.append(bool(kennzahlen))
        zusatz = _zusatz(kennzahlen, ebenen)
        teile = []
        if papers:
            teile.append(_area_body(True, name, escape(name), key, papers, root))
        else:
            leer = leer_satz or ("<p>Derzeit ist keine Vorlage verzeichnet, die sich auf den ganzen Stadtbezirk ohne "
                                 "genaueren Ort bezieht; Vorlagen zu einzelnen Stadtteilen stehen auf deren Seiten.</p>")
            teile.append(_ohne_vorlagen(
                f"Stadtbezirk {escape(name)}",
                f"Einer von {len(index['bezirke'])} Stadtbezirken der Stadt {config.STADT_NAME}; er umfasst "
                f"{len(ortsteile)} Stadtteile." + (f" Auf dieser Seite: {zusatz} zur Einordnung, mit Quellen." if zusatz else ""),
                map_url, f"Stadtbezirk {escape(name)} auf der Karte öffnen", leer))
        teile.append(_stadtteile(name, ortsteile, root, None if vorschau else ot_zahl))
        teile.append(kennzahlen)
        teile.append(_ebenen(ebenen, map_url, f"für den Stadtbezirk {name}"))
        path = f"stadtbezirk/{b['slug']}/"
        if papers:
            title = f"Ratsvorlagen im Stadtbezirk {name} – Ratsatlas Köln"
            description = (f"Vorlagen aus dem Ratsinformationssystem mit Bezug zum ganzen Stadtbezirk {name} (Köln), "
                           "ohne genaueren Ort.")
        else:
            title = f"Stadtbezirk {name}" + (f": {zusatz}" if zusatz else "") + " – Ratsatlas Köln"
            description = (f"Stadtbezirk {name} (Köln) mit {len(ortsteile)} Stadtteilen"
                           + (f": Kennzahlen im Vergleich mit {vergleich(spalten)}, mit Quellen und Lizenzen"
                              if kennzahlen and len(spalten) > 1 else ": Kennzahlen mit Quellen und Lizenzen" if kennzahlen else "")
                           + ("; Kartenebenen aus offenen Daten" if ebenen else "") + "."
                           + (" Die Ratsvorlagen folgen." if vorschau else ""))
        _schreiben(site, site_url, path, title, description, "\n".join(t for t in teile if t),
                   head(f"feeds/bezirk-{b['slug']}.xml", f"Ratsatlas Köln – Stadtbezirk {name}, ohne genaueren Ort"))
        paths.append(path)

    sections = []
    for b in index["bezirke"]:
        ortsteile = sorted((o for o in index["ortsteile"] if o["stadtbezirk"] == b["name"]), key=lambda o: _sortname(o["name"]))
        items = "\n".join(f'      <li><a href="../ortsteil/{o["slug"]}/">{escape(o["name"])}</a>'
                          + ("" if vorschau else f' ({_vorlagen_zahl(ot_zahl[o["slug"]])})') + "</li>" for o in ortsteile)
        sections.append(
            f'    <h2>Stadtbezirk {escape(b["name"])}</h2>\n'
            f'    <p><a href="../stadtbezirk/{b["slug"]}/">Stadtbezirk {escape(b["name"])} im Überblick</a>'
            + ("" if vorschau else f' ({_vorlagen_zahl(len(bz_vorlagen[b["slug"]]))} zum ganzen Stadtbezirk, ohne genaueren Ort)')
            + "</p>\n"
            f"    <ul>\n{items}\n    </ul>")
    anzahl = f"{len(index['bezirke'])} Stadtbezirke und {len(index['ortsteile'])} Stadtteile der Stadt {config.STADT_NAME}"
    # „je mit Kennzahlen“ nur, wenn jede Gebietsseite sie enthält
    hub_zusatz = [t for t, da in (("Kennzahlen", mit_kennzahlen and all(mit_kennzahlen)), ("Kartenebenen", ebenen)) if da]
    zusatz = " und ".join(hub_zusatz)
    extra = f"{zusatz} zur Einordnung" if zusatz else ""
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
    inhalt = ([] if vorschau else ["ihren Vorlagen aus dem Ratsinformationssystem"]) + hub_zusatz
    (site / "gebiete").mkdir(parents=True, exist_ok=True)
    (site / "gebiete" / "index.html").write_text(
        _page(site_url, "gebiete/", f"{h1} – Ratsatlas Köln",
              "Übersicht der Kölner Stadtteile und Stadtbezirke"
              + (" mit " + ", ".join(inhalt[:-1]) + (" und " if len(inhalt) > 1 else "") + inhalt[-1] if inhalt else "") + ".",
              hub, "../"),
        encoding="utf-8")
    print(f"Gebietsseiten: {len(paths)} ({len(index['ortsteile'])} Stadtteile, {len(index['bezirke'])} Stadtbezirke) und Übersicht")
    return ["gebiete/", *paths]
