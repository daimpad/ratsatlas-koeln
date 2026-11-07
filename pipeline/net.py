"""HTTP-Abruf mit Wiederholung (aus dem Ratsatlas Bonn); nur Standardbibliothek.

Nicht für Server der Stadt Köln: Diese Funktionen halten die Abrufpolitik (CLAUDE.md 5.1) nicht ein (Wiederholungen
ohne Pause nach Stunden, mehrere Verbindungen in fetch._oparl_list, kein Zeitfenster, keine Freigabe). Anfragen an
Adressen der Stadt (`abruf.stadt`: stadt-koeln.de, offenedaten-koeln.de, Host der eingestellten OParl-API) werden vor
dem Senden abgelehnt (`AbrufVerweigert`, ohne Wiederholung), auch als Ziel einer Weiterleitung (Öffner `_OEFFNER` mit
`_PruefendeWeiterleitung`); solche Abrufe gehören auf pipeline/abruf.py umgestellt. Betroffen ist etwa
`python -m pipeline fetch-besetzung` (Personen der OParl-API, Zusatzthema „besetzung“, abgeschaltet). Module, die
direkt über urllib abrufen (geodaten.py, ebenen.py, kontext.py u. a.), erfasst dieser Schutz nicht."""
import json
import time
import urllib.parse
import urllib.request

from . import abruf
from .config import USER_AGENT


class AbrufVerweigert(RuntimeError):
    """Anfrage an einen Server der Stadt Köln über dieses Modul: nicht gesendet."""


def _pruefen(url):
    """Vor jeder Anfrage (außerhalb der Wiederholung in _open): keine Adresse der Stadt."""
    if abruf.stadt(url):
        raise AbrufVerweigert(f"Anfrage an einen Server der Stadt Köln über pipeline/net.py verweigert: {url}. "
                              "Dieses Modul hält die Abrufpolitik nicht ein (CLAUDE.md 5.1); den Abruf auf "
                              "pipeline/abruf.py umstellen.")


class _PruefendeWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Folgt einer Weiterleitung nur, wenn ihr Ziel keine Adresse der Stadt ist (`_pruefen` vor dem Senden)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _pruefen(newurl)
        except AbrufVerweigert:
            fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _oeffner(proxies=None):
    """Öffner wie urllib.request.urlopen, aber mit `_PruefendeWeiterleitung`; `proxies` None = aus der Umgebung."""
    return urllib.request.build_opener(_PruefendeWeiterleitung, urllib.request.ProxyHandler(proxies))


_OEFFNER = _oeffner()


def _open(req, tries):
    for i in range(tries):
        try:
            with _OEFFNER.open(req, timeout=90) as r:
                return json.load(r)
        except AbrufVerweigert:   # Weiterleitung an die Stadt: nicht wiederholen
            raise
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def get_json(url, tries=5):
    _pruefen(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return _open(req, tries)


def post_graphql(url, query, variables=None, tries=6):
    _pruefen(url)
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    data = _open(req, tries)
    if data.get("errors"):
        raise RuntimeError(f"GraphQL-Fehler: {data['errors'][:2]}")
    return data["data"]


def post_form(url, fields, tries=4):
    _pruefen(url)
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    return _open(req, tries)
