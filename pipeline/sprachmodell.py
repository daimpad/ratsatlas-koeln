"""Aufruf eines Sprachmodells (Mistral oder Anthropic) für Kurzfassungen und Stufe C.

Anbieter: Umgebungsvariable SPRACHMODELL („mistral“, Standard, oder „anthropic“); Schlüssel MISTRAL_API_KEY bzw.
ANTHROPIC_API_KEY (Secrets im Workflow). Ohne Schlüssel liefert `schluessel()` None und es wird nichts angefragt.
"""
import csv
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

ANBIETER = os.environ.get("SPRACHMODELL", "mistral")
API = {"mistral": "https://api.mistral.ai/v1/chat/completions", "anthropic": "https://api.anthropic.com/v1/messages"}
SCHLUESSEL = {"mistral": "MISTRAL_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def schluessel(anbieter=None):
    return os.environ.get(SCHLUESSEL[anbieter or ANBIETER])


def frage(system, nutzer, modell, schluessel, max_tokens=400, json_antwort=False, anbieter=None, tries=4):
    """(Antworttext, {"ein": Eingabe-Tokens, "aus": Ausgabe-Tokens}); wiederholt bei Netzfehlern."""
    anbieter = anbieter or ANBIETER
    if anbieter == "anthropic":
        body = {"model": modell, "max_tokens": max_tokens, "temperature": 0.1, "system": system,
                "messages": [{"role": "user", "content": nutzer}]}
        headers = {"x-api-key": schluessel, "anthropic-version": "2023-06-01"}
    else:
        body = {"model": modell, "max_tokens": max_tokens, "temperature": 0.1,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": nutzer}]}
        if json_antwort:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {schluessel}"}
    req = urllib.request.Request(API[anbieter], data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
            break
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 2))
    if anbieter == "anthropic":
        text = "".join(c.get("text", "") for c in d.get("content", []))
        u = d.get("usage") or {}
        return text.strip(), {"ein": u.get("input_tokens", 0), "aus": u.get("output_tokens", 0)}
    u = d.get("usage") or {}
    return d["choices"][0]["message"]["content"].strip(), {"ein": u.get("prompt_tokens", 0),
                                                          "aus": u.get("completion_tokens", 0)}


def json_aus(text):
    """Erstes JSON-Objekt einer Antwort (auch in einem Codeblock); None, wenn keines lesbar ist."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def protokoll(verzeichnis, schritt, modell, anfragen, tokens, fehler=0):
    """Eine Zeile je Lauf mit Anfragen in laeufe.tsv (Branch kurzfassungen): Zeitpunkt, Schritt, Modell, Anfragen,
    Tokens, Fehler – zur Abschätzung der Kosten."""
    if not anfragen:
        return
    path = os.path.join(verzeichnis, "laeufe.tsv")
    neu = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        if neu:
            w.writerow(["zeitpunkt", "schritt", "modell", "anfragen", "eingabe_tokens", "ausgabe_tokens", "fehler"])
        w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), schritt, modell, anfragen,
                    tokens.get("ein", 0), tokens.get("aus", 0), fehler])
