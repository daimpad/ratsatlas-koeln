"""HTTP-Abruf mit Wiederholung; nur Standardbibliothek."""
import json
import time
import urllib.parse
import urllib.request

from .config import USER_AGENT


def _open(req, tries):
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def get_json(url, tries=5):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return _open(req, tries)


def post_graphql(url, query, variables=None, tries=6):
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
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    return _open(req, tries)
