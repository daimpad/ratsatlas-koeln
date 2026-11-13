"""Kopf „Dezernat, Dienststelle“ auf Seite 1 einer Verwaltungsvorlage (PDF): Erkennung und Prüfprozess.

Zwei Verwendungen:
- als Modul (`pipeline.pdfkopf`): `kopf_erkennen(text)` und die Muster, für pipeline/dokumente.py und die Tests;
- als eigener Prozess (`python -I pipeline/pdfkopf.py <Speicher> <CPU-Sekunden>`; nur Standardbibliothek und pypdf,
  keine Importe aus `pipeline`): liest die PDF-Datei von der Standardeingabe, setzt Grenzen für Speicher, Rechenzeit,
  Dateigröße (0: schreibt keine Datei) und Speicherabzüge (keine), liest nur Seite 1 mit pypdf (reines Python, keine
  externen Werkzeuge; Skripte, Formulare, Anhänge und eingebettete Dateien werden nicht angefasst, nur der Text der
  ersten Seite extrahiert) und schreibt auf die Standardausgabe nur ein JSON-Objekt {status, trefferart, kennung,
  fehlerart}. Der Text der Seite verlässt diesen Prozess nie; Fehlermeldungen von pypdf (sie können Teile der Datei
  enthalten) ebenso wenig, nur der Name der Fehlerklasse. Der aufrufende Prozess wirft die Standardfehlerausgabe weg.

Muster (abgeleitet aus explore/oparl_messung.py, RE_DEZ und RE_DEZ_LOSE, und dem Beispiel in CLAUDE.md 5.3 „II/II/2“):
- `kennung`: Bezeichnung „Dezernat, Dienststelle“ (Groß- und Kleinschreibung beliebig, auch „DEZERNAT,
  DIENSTSTELLE“; Komma und Doppelpunkt mit beliebigem Leerraum, auch Zeilenumbruch) gefolgt von einer Kennung aus einer
  gültigen römischen Zahl (I bis XXXIX; nicht „VIIII“ oder „IVX“) und bis zu vier weiteren Teilen nach „/“ (Ziffern
  oder eine gültige römische Zahl), etwa „II/II/2“, „VI/61“, „VI / 61 / 2“ (Leerraum entfällt). Die Kennung selbst
  nur in Großbuchstaben. Mit mindestens einem Teil nach „/“ endet sie nicht vor einem Kleinbuchstaben oder einer
  Ziffer; ein unmittelbar folgender Großbuchstabe ist erlaubt (pypdf setzt Zeilen mitunter ohne Leerraum aneinander:
  „VI/61Beschlussvorlage“). Ohne Teil nach „/“ (nur das Dezernat, etwa „VI“) zählt sie nur vor Leerraum oder am Ende
  des Textes und nicht vor „/“: So wird weder „V“ aus „VORLAGE“, „III“ aus „III. Quartal“, „X“ aus „X-Ring“, „I“ aus
  „Integrationsrat“ noch „VI“ aus „VI / 61abc“ eine Kennung (Prüfung dok-f).
- `dezernat_dienststelle`: ausgeschriebene Form „Dezernat VI, 61“ oder „Dezernat VI, Dienststelle 61/2“ (gültige
  römische Zahl des Dezernats, Komma, Nummer der Dienststelle mit zwei oder drei Ziffern und weiteren Teilen), normiert
  wie oben („VI/61“, „VI/61/2“). Schwächer: Sie kann auch im Fließtext stehen.
- ohne Kennung: `nur_bezeichnung` (die Bezeichnung steht da, die Kennung hat eine andere Form, etwa „OB/01“ oder
  Kleinbuchstaben), `kein_text` (kein Text auf Seite 1, etwa ein Scan), `nein` (Text ohne Bezeichnung).
Welche Formen Köln tatsächlich verwendet, zeigt erst der erste Lauf (Test mit 100 Köpfen); die Muster werden danach
geprüft (TECHNIK.md, „Dokumente (PDF-Köpfe)“).
"""
import importlib
import io
import json
import re
import sys

# gültige römische Zahl von I bis XXXIX, nicht von einer weiteren römischen Ziffer gefolgt („VIIII“, „IVX“: keine)
_ROEMISCH = r"(?=[IVX])X{0,3}(?:IX|IV|V?I{0,3})(?![IVX])"
# weiterer Teil nach „/“: höchstens sechs Ziffern oder eine gültige römische Zahl
_TEIL = r"(?:[0-9]{1,6}(?![0-9])|" + _ROEMISCH + r")"
# Kennung (nur Großbuchstaben, Ziffern und „/“):
# - mit mindestens einem Teil nach „/“, atomar, damit eine nicht passende Fortsetzung („VI/61abc“) nicht zu einer
#   kürzeren Kennung zurückweicht; danach kein Kleinbuchstabe und keine Ziffer, ein Großbuchstabe schon
#   („VI/61Beschlussvorlage“);
# - nur die römische Zahl (das Dezernat): nur vor Leerraum oder am Ende, und kein „/“ dahinter (auch nicht nach
#   Leerraum: sonst würde aus „VI / 61abc“ „VI“)
_KENNUNG = (r"(?>" + _ROEMISCH + r"(?:\s*/\s*" + _TEIL + r"){1,4})(?![a-zäöüß0-9])"
            r"|" + _ROEMISCH + r"(?=\s|\Z)(?!\s*/)")
_BEZEICHNUNG = r"Dezernat\s*,\s*Dienststelle"
# die Bezeichnung ohne Rücksicht auf Groß- und Kleinschreibung, die Kennung nicht
RE_KENNUNG = re.compile(r"(?i:" + _BEZEICHNUNG + r")\s*:?\s*(" + _KENNUNG + r")")
RE_AUSGESCHRIEBEN = re.compile(r"(?<![A-Za-zÄÖÜäöüß])Dezernat\s+(" + _ROEMISCH + r")\s*,\s*(?:Dienststelle\s*:?\s*)?"
                               r"(?>(\d{2,3}(?:\s*/\s*\d{1,4}){0,3}))(?![0-9a-zäöüß])")
RE_BEZEICHNUNG = re.compile(r"Dezernat\s*,?\s*Dienststelle", re.I)
# zulässige Form einer gespeicherten Kennung (gültige römische Zahl, dann bis zu vier Teile nach „/“ aus Ziffern oder
# einer gültigen römischen Zahl; fullmatch): Was nicht passt, wird verworfen (Einträge, Aufbau, check)
KENNUNG_FORM = re.compile(_ROEMISCH + r"(?:/(?:[0-9]{1,6}|" + _ROEMISCH + r")){0,4}")
# Trefferarten mit Kennung (Federführung: Konfidenz) und ohne
MIT_KENNUNG = {"kennung": "mittel", "dezernat_dienststelle": "niedrig"}
OHNE_KENNUNG = ("nur_bezeichnung", "kein_text", "nein")
TREFFERARTEN = (*MIT_KENNUNG, *OHNE_KENNUNG)
# Ergebnis des Prüfprozesses (status); dazu Fehlerklasse nur als Name
STATUS = ("ok", "verschluesselt", "keine_seite", "fehler_pdf", "speicher")
FEHLERART = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,59}")
# Federführung aus dem Kopf (actors.responsibilities): Methode und Fundstelle (ohne Text des Dokuments)
METHODE = "pdf_kopf"
EVIDENZ = "Kopf der Vorlage (S. 1)"
# Grenzen für pypdf (Byte je entpacktem Datenstrom; pypdf selbst erlaubt 75 MB)
PYPDF_GRENZE = 30_000_000


def _normiert(kennung):
    return re.sub(r"\s+", "", kennung)


def kopf_erkennen(text):
    """(Trefferart, Kennung) aus dem Text von Seite 1: zuerst die Bezeichnung mit Kennung (`kennung`), dann die
    ausgeschriebene Form (`dezernat_dienststelle`), sonst ohne Kennung (`nur_bezeichnung`, `kein_text`, `nein`).
    Eine Kennung, die nicht KENNUNG_FORM entspricht, zählt nicht."""
    text = text or ""
    m = RE_KENNUNG.search(text)
    if m and KENNUNG_FORM.fullmatch(_normiert(m.group(1))):
        return "kennung", _normiert(m.group(1))
    m = RE_AUSGESCHRIEBEN.search(text)
    if m:
        kennung = f"{m.group(1)}/{_normiert(m.group(2))}"
        if KENNUNG_FORM.fullmatch(kennung):
            return "dezernat_dienststelle", kennung
    if RE_BEZEICHNUNG.search(text):
        return "nur_bezeichnung", ""
    return ("kein_text" if not text.strip() else "nein"), ""


def ergebnis_pruefen(roh):
    """Ausgabe des Prüfprozesses (Bytes) lesen und prüfen: nur bekannte Schlüssel und Werte (status aus STATUS,
    trefferart aus TREFFERARTEN, kennung nach KENNUNG_FORM und nur mit einer Trefferart mit Kennung, fehlerart als
    Klassenname); sonst None. So kann auch ein fehlerhafter Prüfprozess keinen Text weitergeben."""
    try:
        e = json.loads(roh[:4096].decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(e, dict) or set(e) != {"status", "trefferart", "kennung", "fehlerart"}:
        return None
    status, art, kennung, fehlerart = e["status"], e["trefferart"], e["kennung"], e["fehlerart"]
    if status not in STATUS or not all(isinstance(x, str) for x in (art, kennung, fehlerart)):
        return None
    if status == "ok" and art not in TREFFERARTEN or status != "ok" and art:
        return None
    if (kennung and (art not in MIT_KENNUNG or not KENNUNG_FORM.fullmatch(kennung))
            or art in MIT_KENNUNG and not kennung):
        return None
    if fehlerart and not FEHLERART.fullmatch(fehlerart):
        return None
    return {"status": status, "trefferart": art, "kennung": kennung, "fehlerart": fehlerart}


def _grenzen(speicher, cpu):
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))          # kein Speicherabzug (enthielte die Datei)
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))         # keine Datei schreiben
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))       # Rechenzeit (danach SIGXCPU bzw. SIGKILL)
    resource.setrlimit(resource.RLIMIT_AS, (speicher, speicher))


def _pruefen(daten):
    """Seite 1 lesen und erkennen; liefert das Ergebnis ohne Text."""
    import pypdf
    import pypdf.filters
    from pypdf.errors import FileNotDecryptedError
    for name in ("ZLIB_MAX_OUTPUT_LENGTH", "LZW_MAX_OUTPUT_LENGTH", "RUN_LENGTH_MAX_OUTPUT_LENGTH",
                 "JBIG2_MAX_OUTPUT_LENGTH", "MAX_DECLARED_STREAM_LENGTH", "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
                 "FLATE_MAX_BUFFER_SIZE"):
        if hasattr(pypdf.filters, name):
            setattr(pypdf.filters, name, min(getattr(pypdf.filters, name), PYPDF_GRENZE))
    ergebnis = {"status": "ok", "trefferart": "", "kennung": "", "fehlerart": ""}
    try:
        reader = pypdf.PdfReader(io.BytesIO(daten))   # versucht bei Verschlüsselung nur das leere Kennwort
        if not len(reader.pages):
            return {**ergebnis, "status": "keine_seite"}
        text = reader.pages[0].extract_text() or ""
    except FileNotDecryptedError:
        return {**ergebnis, "status": "verschluesselt"}
    except MemoryError:
        return {**ergebnis, "status": "speicher"}
    except Exception as e:   # unlesbare Datei: nur der Name der Fehlerklasse, nie die Meldung (enthält ggf. Inhalt)
        name = type(e).__name__
        return {**ergebnis, "status": "fehler_pdf", "fehlerart": name if FEHLERART.fullmatch(name) else ""}
    art, kennung = kopf_erkennen(text)
    del text
    return {**ergebnis, "trefferart": art, "kennung": kennung}


def main(argv):
    speicher, cpu = int(argv[0]), int(argv[1])
    daten = sys.stdin.buffer.read()
    importlib.import_module("pypdf.filters")   # vor den Grenzen laden (der Import selbst braucht Speicher und Dateien)
    _grenzen(speicher, cpu)
    try:
        ergebnis = _pruefen(daten)
    except MemoryError:
        ergebnis = {"status": "speicher", "trefferart": "", "kennung": "", "fehlerart": ""}
    sys.stdout.write(json.dumps(ergebnis))
    sys.stdout.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
