"""Leere Rohdaten für die Kartenvorschau (Entscheidung 07.11.2026): Karte, Gebiete und Ebenen ohne Ratsvorlagen.

Aufruf: python3 tools/vorschau.py
Schreibt leere Rohdateien im Format des SessionNet-Adapters nach data/raw/ und vermerkt „vorschau“ in STAND.json.
Die Seite zeigt dann einen Hinweis „Vorschau – noch keine Ratsvorlagen“. Sobald der Abruf der Stadt Daten liefert,
ersetzt pages.yml die Vorschau durch die vollständige Seite. Überschreibt nie vorhandene Daten der Stadt.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import config  # noqa: E402
from pipeline.fetch import _write  # noqa: E402


def main():
    if config.PAPERS.exists() and config.PAPERS.stat().st_size:
        stand = json.loads(config.STAND.read_text()) if config.STAND.exists() else {}
        if not stand.get("vorschau") and not stand.get("testdaten"):
            raise SystemExit("data/raw enthält Daten der Stadt – keine Vorschau.")
    config.RAW.mkdir(parents=True, exist_ok=True)
    _write(config.PAPERS, "")
    _write(config.ORGANIZATIONS, "[]")
    _write(config.MEETINGS, "[]")
    _write(config.LEGISLATIVE_TERMS, "[]")
    _write(config.BERATUNGEN, "")
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write(config.STAND, json.dumps({"vorschau": jetzt}, indent=1) + "\n")
    print(f"Vorschau: leere Rohdaten → {config.RAW}")


if __name__ == "__main__":
    main()
