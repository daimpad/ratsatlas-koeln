"""Kennzahlen je Gebiet für die Übersichtskarte (index.json): Vorlagen der letzten zwölf Monate und ein
auffälliges Thema, das im Gebiet deutlich häufiger vorkommt als in ganz Bonn.

Gezählt werden Vorlagen mit Ortsbezug im Gebiet (Verortung teils abgeleitet, siehe geocode.py); Themen sind
abgeleitet (topics.py). Vergleichsbasis für „auffällig“ sind alle Vorlagen mit Ortsbezug in Bonn."""
import datetime

from . import topics

MIN_VORLAGEN = 5      # mindestens so viele Vorlagen des Themas im Gebiet
MIN_ANTEIL = 0.10     # mindestens dieser Anteil an den Vorlagen des Gebiets
MIN_FAKTOR = 1.25     # mindestens so viel häufiger als in ganz Bonn
MIN_THEMEN = 20       # Themenebene: Anteile erst ab so vielen Vorlagen im Gebiet (alle seit 2019)


def window_start(stand):
    """Beginn des Zwölfmonatszeitraums (ISO-Datum) zum Datenstand."""
    return (datetime.date.fromisoformat(stand[:10]) - datetime.timedelta(days=365)).isoformat()


def recent(ids, papers, since):
    return sum((papers[i].get("date") or "") > since for i in ids)


def shares(ids, papers):
    """Anteil der Vorlagen je Thema (eine Vorlage kann mehrere Themen haben)."""
    counts = {}
    for i in ids:
        for t in {t["theme"] for t in papers[i].get("themes") or []}:
            counts[t] = counts.get(t, 0) + 1
    n = len(ids) or 1
    return {t: (c, c / n) for t, c in counts.items()}


def auffaellig(ids, papers, base):
    """Thema mit dem größten Faktor gegenüber ganz Bonn, sofern es die Mindestwerte erfüllt; sonst None.
    `base`: Anteile in ganz Bonn aus shares()."""
    label = dict(topics.THEMES)
    best = None
    for t, (c, share) in shares(ids, papers).items():
        city = base.get(t, (0, 0))[1]
        if c < MIN_VORLAGEN or share < MIN_ANTEIL or not city:
            continue
        factor = share / city
        if factor >= MIN_FAKTOR and (not best or factor > best[0]):
            best = (factor, t, share, city)
    if not best:
        return None
    _, t, share, city = best
    return {"thema": t, "label": label.get(t, t), "anteil": round(share * 100), "anteil_bonn": round(city * 100)}


def theme_shares(ids, papers):
    """Themenebene der Karte: je Thema [Zahl, Anteil in %] aller Vorlagen des Gebiets seit Beginn der Daten;
    None unter MIN_THEMEN Vorlagen (Anteile zu unsicher)."""
    if len(ids) < MIN_THEMEN:
        return None
    return {t: [c, round(share * 100, 1)] for t, (c, share) in sorted(shares(ids, papers).items())}


def annotate(index, areas, papers, stand):
    """Ergänzt index.json: je Ortsteil `jahr` und `auffaellig`; je Stadtbezirk `alle` (ohne Doppelte aus
    Ortsteilen und Bezirksebene), `jahr` und `auffaellig`; dazu `meta_zahlen` mit Zeitraum und Regeln."""
    since = window_start(stand)
    placed = {i for k, ids in areas.items() if k.startswith(("ortsteil:", "bezirk:")) for i in ids}
    base = shares(placed, papers)
    for o in index["ortsteile"]:
        ids = areas[f"ortsteil:{o['slug']}"]
        o["jahr"] = recent(ids, papers, since)
        o["auffaellig"] = auffaellig(ids, papers, base)
        o["themen"] = theme_shares(ids, papers)
    for b in index["bezirke"]:
        ids = set(areas.get(f"bezirk:{b['slug']}", []))
        for o in index["ortsteile"]:
            if o["stadtbezirk"] == b["name"]:
                ids.update(areas[f"ortsteil:{o['slug']}"])
        b["alle"] = len(ids)
        b["jahr"] = recent(ids, papers, since)
        b["auffaellig"] = auffaellig(ids, papers, base)
        b["themen"] = theme_shares(ids, papers)
    index["zahlen"] = {"seit": since, "bis": stand[:10],
                       "themen_bonn": {t: round(share * 100, 1) for t, (_, share) in sorted(base.items())},
                       "themen_min": MIN_THEMEN,
                       "hinweis": "Vorlagen mit Ortsbezug im Gebiet (Verortung teils abgeleitet); Themen abgeleitet. "
                                  f"Auffällig: mindestens {MIN_VORLAGEN} Vorlagen und {round(MIN_ANTEIL * 100)} % im Gebiet, "
                                  f"mindestens {MIN_FAKTOR:g}-mal so häufig wie in ganz Bonn."}
    return index
