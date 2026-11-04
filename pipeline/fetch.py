"""Abruf der Rohdaten: städtische OParl-API (Primärquelle) und OParl-Lite (Sitzungen, TOPs)."""
import concurrent.futures as cf
import json
import os
from datetime import datetime, timezone

from . import config
from .net import get_json, post_form, post_graphql


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp(key):
    stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
    stand[key] = _now()
    config.STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n")


# Ein neuer Abruf ersetzt den vorhandenen Stand nur, wenn er mindestens diesen Anteil der Objekte enthält; sonst
# bricht der Schritt ab und der letzte Stand (Zwischenspeicher bzw. Repository) bleibt (Code-Prüfung 23.10.2026:
# eine leere Antwort mit Status 200 hätte sonst Vorlagen oder Bebauungspläne für Tage entfernt)
MIN_ANTEIL = 0.9


def _write(path, text):
    """Schreibt erst in eine temporäre Datei und ersetzt dann: ein Abbruch hinterlässt keine halbe Datei."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _jsonl_count(path):
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _guard(label, new, old):
    """Bricht ab, wenn der neue Abruf deutlich weniger Objekte enthält als der vorhandene Stand."""
    if old and new < MIN_ANTEIL * old:
        raise RuntimeError(f"{label}: nur {new} statt bisher {old} – unvollständige Antwort? Vorhandener Stand bleibt.")


def _oparl_list(url, size=100, workers=6):
    first = get_json(f"{url}?page=1&size={size}")
    pages = first["pagination"]["totalPages"]
    total = first["pagination"]["totalElements"]
    print(f"{url}: {total} Objekte, {pages} Seiten", flush=True)
    results = {1: first["data"]}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        fetch = lambda p: (p, get_json(f"{url}?page={p}&size={size}")["data"])
        for p, data in ex.map(fetch, range(2, pages + 1)):
            results[p] = data
    empty = [p for p in sorted(results) if not results[p] and p < pages]
    items = [item for p in sorted(results) for item in results[p]]
    # neue Objekte während des Abrufs verschieben die Seiten etwas; leere Seiten oder große Lücken nicht
    if empty or len(items) < MIN_ANTEIL * total:
        raise RuntimeError(f"{url}: unvollständig ({len(items)} von {total} Objekten, leere Seiten: {empty[:5]})")
    return items


def fetch_papers():
    papers = _oparl_list(f"{config.OPARL_BODY}/papers")
    _guard("Vorlagen", len(papers), _jsonl_count(config.PAPERS))
    _write(config.PAPERS, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in papers))
    _stamp("papers")
    print(f"{len(papers)} Vorlagen → {config.PAPERS}")


def fetch_organizations():
    orgs = _oparl_list(f"{config.OPARL_BODY}/organizations")
    if config.ORGANIZATIONS.exists():
        _guard("Organisationen", len(orgs), len(json.loads(config.ORGANIZATIONS.read_text())))
    _write(config.ORGANIZATIONS, json.dumps(orgs, ensure_ascii=False))
    vb = [o for o in orgs if o.get("organizationType") == "Verwaltungsbereich"]
    _write(config.VERWALTUNGSBEREICHE, json.dumps(vb, ensure_ascii=False))
    _stamp("organizations")
    print(f"{len(orgs)} Organisationen, davon {len(vb)} Verwaltungsbereiche")


def fetch_meetings():
    """Sitzungen (auch künftige) und Wahlperioden aus der städtischen OParl-API."""
    meetings = _oparl_list(f"{config.OPARL_BODY}/meetings")
    if config.MEETINGS.exists():
        _guard("Sitzungen", len(meetings), len(json.loads(config.MEETINGS.read_text())))
    terms = _oparl_list(f"{config.OPARL_BODY}/legislativeTerms", size=10)
    keep = ("id", "name", "meetingState", "cancelled", "start", "end", "organization", "web")
    # Tagesordnung (web) und Einladung erscheinen etwa zwei Wochen vor der Sitzung
    _write(config.MEETINGS, json.dumps(
        [{**{k: m.get(k) for k in keep}, "invitation": (m.get("invitation") or {}).get("accessUrl"),
          "agenda_items": len(m.get("agendaItem") or [])} for m in meetings], ensure_ascii=False))
    _write(config.LEGISLATIVE_TERMS, json.dumps(terms, ensure_ascii=False))
    _stamp("meetings")
    print(f"{len(meetings)} Sitzungen, {len(terms)} Wahlperioden")


CONSULTATION_QUERY = """
query($limit: Int!, $offset: Int!) {
  consultations(limit: $limit, offset: $offset, orderBy: {field: URI, direction: ASC}) {
    totalCount
    items {
      uri
      meeting { uri name startDate cancelled }
      agendaItem { uri number name result public }
    }
  }
}"""


def fetch_consultations_lite(page=100, workers=2):
    """Beratungen mit Sitzung und Tagesordnungspunkt; Verknüpfung über die OParl-URI."""
    run = lambda off: post_graphql(
        config.LITE_GRAPHQL, CONSULTATION_QUERY, {"limit": page, "offset": off}
    )["consultations"]
    first = run(0)
    total = first["totalCount"]
    print(f"OParl-Lite: {total} Beratungen", flush=True)
    items = {0: first["items"]}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for off, res in ex.map(lambda o: (o, run(o)), range(page, total, page)):
            items[off] = res["items"]
    seen, lines = set(), []
    for off in sorted(items):
        for c in items[off]:
            if c["uri"] in seen:
                continue
            seen.add(c["uri"])
            lines.append(json.dumps(c, ensure_ascii=False) + "\n")
    if len(seen) < MIN_ANTEIL * total:
        raise RuntimeError(f"OParl-Lite: unvollständig ({len(seen)} von {total} Beratungen)")
    _guard("Beratungen (OParl-Lite)", len(seen), _jsonl_count(config.CONSULTATIONS_LITE))
    _write(config.CONSULTATIONS_LITE, "".join(lines))
    _stamp("consultations_lite")
    print(f"{len(seen)} Beratungen → {config.CONSULTATIONS_LITE}")


OVERPASS_QUERY = '[out:json][timeout:90];way["highway"]["name"]({s},{w},{n},{e});out tags geom;'


def _overpass(query):
    for url in config.OVERPASS:
        try:
            data = post_form(url, {"data": query}, tries=3)
        except Exception as exc:  # nächster Server
            print(f"  {url}: {exc}", flush=True)
            continue
        # Overpass meldet Zeitüberschreitungen mit Status 200 und einem Vermerk; das Ergebnis ist dann unvollständig
        if "runtime error" in (data.get("remark") or ""):
            print(f"  {url}: {data['remark'][:120]}", flush=True)
            continue
        return data
    raise RuntimeError("Kein Overpass-Server erreichbar oder Antwort unvollständig.")


def _tile_ways(s, w, n, e, depth=0):
    """Ways einer Kachel (zwischengespeichert); schlägt der Abruf fehl, wird die Kachel
    geviertelt. Liefert (Ways, fehlende Kacheln)."""
    cache = config.OSM_TILES / f"{s}_{w}_{n}_{e}.json"
    if cache.exists():
        return json.loads(cache.read_text()), []
    try:
        elements = _overpass(OVERPASS_QUERY.format(s=s, w=w, n=n, e=e))["elements"]
    except RuntimeError:
        if depth >= 2:
            return [], [(s, w, n, e)]
        ms, mw = round((s + n) / 2, 4), round((w + e) / 2, 4)
        ways, missing = [], []
        for q in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
            got, miss = _tile_ways(*q, depth + 1)
            ways += got
            missing += miss
        return ways, missing
    config.OSM_TILES.mkdir(parents=True, exist_ok=True)
    _write(cache, json.dumps(elements, ensure_ascii=False))
    return elements, []


def fetch_streets(step=0.05):
    """Benannte Straßen (OSM-Ways mit `highway` und `name`) im Stadtgebiet, in Kacheln.
    Nicht abrufbare Kacheln werden übersprungen und in der Ausgabe als `missing_tiles`
    vermerkt; ein erneuter Aufruf holt nur diese nach."""
    south, west, north, east = config.BONN_BBOX
    tiles = [(round(s, 2), round(w, 2), round(min(s + step, north), 2), round(min(w + step, east), 2))
             for s in _frange(south, north, step) for w in _frange(west, east, step)]
    ways, missing = {}, []
    for i, tile in enumerate(tiles, 1):
        elements, miss = _tile_ways(*tile)
        missing += miss
        for el in elements:
            if el.get("geometry"):
                ways[el["id"]] = {"id": el["id"], "name": el["tags"]["name"],
                                  "highway": el["tags"].get("highway"),
                                  "coords": [[p["lon"], p["lat"]] for p in el["geometry"]]}
        print(f"Kachel {i}/{len(tiles)}: {len(ways)} Ways, {len(miss)} Teilkacheln fehlen", flush=True)
    _write(config.OSM_STREETS, json.dumps({"ways": list(ways.values()), "missing_tiles": missing}, ensure_ascii=False))
    _stamp("osm_streets")
    print(f"{len(ways)} Ways → {config.OSM_STREETS}; fehlende Teilkacheln: {len(missing)}")


def _frange(start, stop, step):
    x = start
    while x < stop - 1e-9:
        yield x
        x += step


def fetch_plans():
    """Geltungsbereiche der rechtskräftigen Bebauungspläne (Stadt Bonn, CC0); im Repository als
    Rückfall, falls der Dienst nicht antwortet."""
    data = get_json(config.BPLAN_URL)
    rnd = lambda c: [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 6), round(c[1], 6)]
    https = lambda u: (u or "").replace("http://stadtplan.bonn.de/", "https://stadtplan.bonn.de/") or None
    features = [{"type": "Feature",
                 "properties": {"name": f["properties"]["bplan_name"], "inkraft_seit": f["properties"].get("inkraft_seit"),
                                "plan": https(f["properties"].get("pdf_link")),
                                "begruendung": https(f["properties"].get("begruendung_link"))},
                 "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])}}
                for f in data["features"] if f.get("geometry")]
    if config.BPLAN.exists():
        _guard("Bebauungspläne", len(features), len(json.loads(config.BPLAN.read_text())["features"]))
    _plan_changes(features)
    _write(config.BPLAN, json.dumps({
        "type": "FeatureCollection",
        "meta": {"source": config.BPLAN_URL, "license": config.SOURCES["bplan-bonn"]["license"],
                 "retrieved_at": _now()},
        "features": sorted(features, key=lambda f: f["properties"]["name"])},
        ensure_ascii=False, separators=(",", ":")) + "\n")
    _stamp("bplan")
    print(f"{len(features)} Bebauungspläne → {config.BPLAN}")


def fetch_housenumbers():
    """Hausnummern georeferenziert (Stadt Bonn, CC0), reduziert auf Straße → Ortsteil → Nummern ohne Zusatz.
    Der Ortsteil wird per Point-in-Polygon aus den Ortsteilflächen bestimmt (die Angabe im Datensatz fehlt bei
    einigen Adressen oder weicht ab). Koordinaten einzelner Adressen werden nicht gespeichert."""
    from .geo import Ortsteile
    data = get_json(config.HAUSNUMMERN_URL)
    ots = Ortsteile()
    out, n = {}, 0
    for f in data["features"]:
        p, g = f["properties"], f.get("geometry")
        street, nr = (p.get("stassen_langname") or "").strip(), (p.get("hnr_ohne_zusatz") or "").strip()
        ot = ots.locate(*g["coordinates"][:2]) if g and street and nr else None
        if ot:
            out.setdefault(street, {}).setdefault(ot["ortsteil_bez"], set()).add(nr)
            n += 1
    key = lambda x: (int(x) if x.isdigit() else 10**6, x)
    if config.HAUSNUMMERN.exists():
        _guard("Hausnummern", n, json.loads(config.HAUSNUMMERN.read_text())["meta"].get("adressen", 0))
    _write(config.HAUSNUMMERN, json.dumps({
        "meta": {"source": config.HAUSNUMMERN_URL, "license": config.SOURCES["hnr-bonn"]["license"],
                 "retrieved_at": _now(), "adressen": n,
                 "note": "Straße → Ortsteil → Hausnummern ohne Zusatz; Ortsteil per Point-in-Polygon (Ortsteilflächen "
                         "der Stadt Bonn); ohne Koordinaten einzelner Adressen"},
        "strassen": {s: {o: sorted(v, key=key) for o, v in sorted(d.items())} for s, d in sorted(out.items())}},
        ensure_ascii=False, separators=(",", ":")) + "\n")
    _stamp("hausnummern")
    print(f"{n} Adressen in {len(out)} Straßen → {config.HAUSNUMMERN}")


# Gebäude und Anlagen (OSM) für Stufe C: öffentliche Einrichtungen, Grün- und Sportanlagen, Friedhöfe, Bauwerke;
# ohne Kunstwerke, Gedenktafeln, Wegkreuze und soziale Einrichtungen (Wohnheime: Schutz der Bewohner:innen)
OBJEKT_ARTEN = {
    "amenity": {"school": "Schule", "kindergarten": "Kita", "college": "Hochschule", "university": "Hochschule",
                "library": "Bibliothek", "theatre": "Theater", "events_venue": "Veranstaltungsort",
                "conference_centre": "Veranstaltungsort", "arts_centre": "Kulturzentrum",
                "community_centre": "Bürgerhaus", "townhall": "Rathaus", "courthouse": "Gericht",
                "fire_station": "Feuerwache", "police": "Polizei", "hospital": "Krankenhaus",
                "swimming_pool": "Bad", "place_of_worship": "Kirche oder Gebetshaus", "grave_yard": "Friedhof",
                "marketplace": "Marktplatz", "bus_station": "Busbahnhof"},
    "leisure": {"park": "Park", "playground": "Spielplatz", "sports_centre": "Sportanlage", "sports_hall": "Sporthalle",
                "stadium": "Stadion", "swimming_pool": "Bad", "pitch": "Sportplatz", "garden": "Garten",
                "nature_reserve": "Schutzgebiet"},
    "landuse": {"cemetery": "Friedhof"},
    "tourism": {"museum": "Museum", "attraction": "Sehenswürdigkeit"},
    "historic": {"castle": "Bauwerk", "palace": "Bauwerk", "manor": "Bauwerk", "monument": "Bauwerk",
                 "building": "Bauwerk", "city_gate": "Bauwerk", "ruins": "Bauwerk", "church": "Kirche oder Gebetshaus"},
    "building": {"civic": "Öffentliches Gebäude", "public": "Öffentliches Gebäude", "government": "Öffentliches Gebäude",
                 "university": "Hochschule", "school": "Schule", "kindergarten": "Kita", "palace": "Bauwerk",
                 "castle": "Bauwerk", "sports_hall": "Sporthalle", "stadium": "Stadion", "train_station": "Bahnhof",
                 "church": "Kirche oder Gebetshaus", "hospital": "Krankenhaus"},
    "railway": {"station": "Bahnhof"},
}


def fetch_objects():
    """Benannte Gebäude und Anlagen in Bonn aus OSM (ODbL): Name, Art, Ortsteil (Point-in-Polygon), Mittelpunkt."""
    from .geo import Ortsteile
    s, w, n, e = config.BONN_BBOX
    b = f"({s},{w},{n},{e})"
    parts = "".join(f'nwr["{k}"~"^({"|".join(v)})$"]["name"]{b};' for k, v in OBJEKT_ARTEN.items())
    # bekannte Bauwerke sind oft nur als Gebäude erfasst (Beethovenhalle, Post Tower): Gebäude mit Wikidata-Eintrag
    parts += f'nwr["building"]["name"]["wikidata"]{b};'
    elements = _overpass(f"[out:json][timeout:180];({parts});out tags center;")["elements"]
    ots, out = Ortsteile(), {}
    for x in elements:
        t = x["tags"]
        c = x.get("center") or {"lat": x.get("lat"), "lon": x.get("lon")}
        art = next((v[t[k]] for k, v in OBJEKT_ARTEN.items() if t.get(k) in v), None)
        if not art and "building" in t and "wikidata" in t and t.get("amenity") != "social_facility":
            art = "Bauwerk"
        ot = ots.locate(c["lon"], c["lat"]) if c.get("lat") is not None and art else None
        if ot:
            out[f"{x['type']}/{x['id']}"] = {"name": t["name"].strip(), "art": art, "ortsteil": ot["ortsteil_bez"],
                                            "bezirk": ot["bezirk_bez"], "lon": round(c["lon"], 6),
                                            "lat": round(c["lat"], 6)}
    if config.OBJEKTE.exists():
        _guard("Gebäude und Anlagen", len(out), json.loads(config.OBJEKTE.read_text())["meta"].get("objekte", 0))
    _write(config.OBJEKTE, json.dumps({
        "meta": {"source": config.SOURCES["osm"]["url"], "license": config.SOURCES["osm"]["license"],
                 "retrieved_at": _now(), "objekte": len(out),
                 "note": "benannte Gebäude und Anlagen (öffentliche Einrichtungen, Grün- und Sportanlagen, Friedhöfe, "
                         "Bauwerke); Ortsteil per Point-in-Polygon; ohne Kunstwerke, Gedenktafeln, Wegkreuze und "
                         "soziale Einrichtungen"},
        "objekte": dict(sorted(out.items()))}, ensure_ascii=False, separators=(",", ":")) + "\n")
    _stamp("objekte")
    print(f"{len(out)} Gebäude und Anlagen → {config.OBJEKTE}")


TEXT_LIST_QUERY = """query($o:Int){ files(limit:100, offset:$o, where:{name:{equals:"Sammeldokument öffentlich"},
  textExtracted:true}, orderBy:{field:URI, direction:ASC}){ totalCount pageInfo{hasNextPage} items{ uri textSha256 papers{ uri } } } }"""


def fetch_texts(max_files=3000, batch=10, pause=1.0):
    """Texte der Hauptdokumente aus OParl-Lite (Feld `text`; extrahiert aus den PDFs der Stadt): erst die Liste der
    Dateien mit Text, dann nur neue oder geänderte (`textSha256`), höchstens `max_files` je Lauf. Die Texte dienen
    nur der Verarbeitung (Verortung) und werden nicht veröffentlicht; Rahmen: Antwort der Stadt Bonn, keine Zitate."""
    import time
    have = {}
    if config.TEXTE.exists():
        for line in open(config.TEXTE, encoding="utf-8"):
            r = json.loads(line)
            have[r["uri"]] = r
    listing, off = [], 0
    while True:
        page = post_graphql(config.LITE_GRAPHQL, TEXT_LIST_QUERY, {"o": off})["files"]
        listing += page["items"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        off += 100
        time.sleep(pause)
    todo = [f for f in listing if (have.get(f["uri"]) or {}).get("sha") != f["textSha256"]][:max_files]

    def holen(chunk):
        # URIs als GraphQL-Variablen, nicht in den Abfragetext eingesetzt
        head = ", ".join(f"$u{j}: String!" for j in range(len(chunk)))
        body = " ".join(f"f{j}: fileByUri(uri: $u{j}) {{ uri textSha256 text }}" for j in range(len(chunk)))
        return post_graphql(config.LITE_GRAPHQL, f"query({head}) {{ {body} }}",
                            {f"u{j}": f["uri"] for j, f in enumerate(chunk)}, tries=3)

    def sichern():
        _write(config.TEXTE, "".join(json.dumps(have[uri], ensure_ascii=False) + "\n" for uri in sorted(have)))

    # Zwischenstände sichern und einzelne fehlerhafte Dateien überspringen (Code-Prüfung 23.10.2026: bisher
    # ging bei einem Fehler oder bei der Zeitgrenze des Workflows alles verloren, und eine stets fehlerhafte Datei
    # hielt den Abruf jeden Tag an derselben Stelle an)
    neu, fehler = 0, 0
    try:
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            try:
                parts = [(chunk, holen(chunk))]
            except Exception:
                parts = []
                for f in chunk:   # einzeln wiederholen, fehlerhafte Datei überspringen
                    try:
                        parts.append(([f], holen([f])))
                    except Exception as exc:
                        fehler += 1
                        print(f"  Volltext übersprungen: {f['uri']} ({type(exc).__name__})", flush=True)
            for files, data in parts:
                for j, f in enumerate(files):
                    d = data.get(f"f{j}") or {}
                    if d.get("text"):
                        have[f["uri"]] = {"uri": f["uri"], "sha": d.get("textSha256"),
                                          "papers": [p["uri"] for p in f["papers"]], "text": d["text"]}
                        neu += 1
            if (i // batch) % 20 == 19:
                sichern()
            time.sleep(pause)
    finally:
        sichern()
    _stamp("texte")
    print(f"Volltexte: {len(listing)} Hauptdokumente mit Text in OParl-Lite, {neu} von {len(todo)} neuen oder "
          f"geänderten abgerufen, {fehler} übersprungen, {len(have)} lokal → {config.TEXTE}")


def _plan_changes(features):
    """Änderungsprotokoll der Bebauungspläne (der Datensatz hat keine Historie): neue Pläne, entfallene Pläne
    (Kandidaten für Aufhebung) und geänderte Daten des Inkrafttretens, je Abruf an PLAN_LOG angehängt."""
    if not config.BPLAN.exists():
        return
    def index(feats):
        out = {}
        for f in feats:
            out.setdefault(f["properties"]["name"], set()).add(f["properties"].get("inkraft_seit") or "")
        return {k: "; ".join(sorted(v)) for k, v in out.items()}
    old = index(json.loads(config.BPLAN.read_text())["features"])
    new = index(features)
    day = _now()[:10]
    rows = ([(day, n, "neu", "", new[n]) for n in sorted(new.keys() - old.keys())]
            + [(day, n, "entfallen", old[n], "") for n in sorted(old.keys() - new.keys())]
            + [(day, n, "inkraft_geaendert", old[n], new[n]) for n in sorted(old.keys() & new.keys()) if old[n] != new[n]])
    if not rows:
        return
    head = not config.PLAN_LOG.exists()
    with config.PLAN_LOG.open("a", encoding="utf-8") as fh:
        if head:
            fh.write("datum\tplan\tereignis\tinkraft_alt\tinkraft_neu\n")
        fh.writelines("\t".join(r) + "\n" for r in rows)
    print(f"Bebauungspläne: {len(rows)} Änderungen → {config.PLAN_LOG}")


def fetch_all():
    fetch_papers()
    fetch_organizations()
    fetch_consultations_lite()
    fetch_meetings()
    fetch_plans()
    fetch_housenumbers()
    fetch_texts()
    fetch_streets()
