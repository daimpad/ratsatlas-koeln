"""Prüfbogen einer Themenseite aus dem Datenpaket, ohne Datenbank, ohne Netz und ohne Freigabe (Entscheidung 24.11.2026
(3); Vorgehen im Plan der Kölner Themenseiten, „pruefbogen_methode“).

Aufruf: python3 -I tools/themen_pruefbogen.py <Ordner> <thema> <Ausgabeordner>

<Ordner>: ein entpacktes Datenpaket (ratsatlas-koeln-export.zip; gelesen wird nur ratsatlas-koeln/koeln/ bzw. koeln/)
oder ein Ordner wie data/export/koeln. Gelesen werden die Gebietsdateien (ortsteile/, bezirke/, ohne-ortsbezug/; jede
Vorlage einmal nach source_object), gremien.json und zeit.json (Wahlperioden). Fehlen die Gebietsdateien, baut das
Werkzeug die Vorgänge aus suche.json (Drucksache, Titel, Datum, Art, Kennungen der beratenden Gremien) ohne Beziehungen
und ohne Sitzungstage: Folgevorlagen sind dann nicht prüfbar, und abgesagte Sitzungen zählen für das Gremium-Tor mit;
der Bogen sagt das in seinen Zählzeilen.
Dieselbe Zuordnung wie die Seite (dossier.verfahren, dossier.zuordnen), dazu die Ziehung dossier.stichprobe: Titel nach
der Titelmaske für alle Drucksachen (maske.Maske), Drucksachen im Titel und im Grund als <DS>, Eingaben ohne Titel,
Titel mit Personenbezug nur gezählt. Schreibt nur in <Ausgabeordner> (außerhalb des Repositorys): pruefbogen_<thema>.tsv
(laufende Nummer statt Drucksache), schluessel_<thema>.tsv (Nummer → Drucksache und Link, nur zum Nachschlagen) und
zahlen_<thema>.tsv. Testdaten nie als echte Vorlagen zeigen.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import dossier, maske, themenseiten  # noqa: E402

GEBIETE = ("ortsteile", "bezirke", "ohne-ortsbezug")


def ordner_koeln(pfad):
    """Ordner mit den Kölner Exporten unter `pfad` (entpacktes Paket oder Exportordner)."""
    for kandidat in (pfad / "ratsatlas-koeln" / "koeln", pfad / "koeln", pfad):
        if (kandidat / "gremien.json").exists():
            return kandidat
    raise SystemExit(f"gremien.json nicht gefunden unter {pfad}")


def vorlagen(base):
    """{source_object: Vorgang} aus den Gebietsdateien (jede Vorlage einmal), sonst aus suche.json ohne Beziehungen;
    dazu, ob die Beziehungen vorliegen."""
    dateien = [f for d in GEBIETE for f in sorted((base / d).glob("*.json"))]
    if dateien:
        aus = {}
        for f in dateien:
            for p in json.loads(f.read_text(encoding="utf-8")).get("papers") or ():
                aus.setdefault(p.get("source_object") or p.get("reference"), p)
        return aus, True
    s = json.loads((base / "suche.json").read_text(encoding="utf-8"))
    aus = {}
    for i, row in enumerate(s.get("rows") or ()):
        keys = [s["gremium_keys"][k] for k in (row[11] if len(row) > 11 else [])]
        namen = [s["gremien"][k] for k in (row[10] if len(row) > 10 else [])]
        aus[f"suche:{i}"] = {"reference": row[0], "name": row[1], "date": row[2], "paper_type": s["types"][row[3]],
                             "source_object": f"suche:{i}", "superordinated": [], "subordinated": [],
                             "process": [{"gremium": n} for n in namen] + [{"gremium_key": k} for k in keys]}
    return aus, False


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__)
    quelle, key, ziel = Path(argv[0]), argv[1], Path(argv[2])
    t = themenseiten.JE_SCHLUESSEL.get(key)
    if not t:
        raise SystemExit(f"Kein Thema „{key}“ in pipeline/themenseiten ({', '.join(themenseiten.JE_SCHLUESSEL)})")
    base = ordner_koeln(quelle)
    papiere, mit_beziehungen = vorlagen(base)
    gremien_daten = json.loads((base / "gremien.json").read_text(encoding="utf-8"))
    zeit = base / "zeit.json"
    terms = json.loads(zeit.read_text(encoding="utf-8")).get("terms") or [] if zeit.exists() else []
    m = maske.Maske({p.get("reference") for p in papiere.values() if p.get("reference")})
    dossier.stichprobe(t, papiere, gremien_daten, ziel, terms, maske_=m)
    if not mit_beziehungen:
        with (ziel / f"zahlen_{t.key}.tsv").open("a", encoding="utf-8") as f:
            f.write("hinweis\tohne Gebietsdateien (aus suche.json): Folgevorlagen nicht prüfbar, abgesagte Sitzungen "
                    "zählen für das Gremium-Tor mit\t0\n")


if __name__ == "__main__":
    main(sys.argv[1:])
