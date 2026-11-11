"""Runde 20, „Aufräumen“ (Entscheidung 10.11.2026): Content-Security-Policy ohne Anbieter von Sprachmodellen und
localhost, solange „chat“ abgeschaltet ist (beim Bau, die Quelle in site/ bleibt vollständig); Flächen „Ratsassistent“
und „Mitmachen in Köln“ nur mit ihrer Freigabe im veröffentlichten HTML; Kommentare ohne OParl-Lite; Blatt „Karte“ auf
dem Telefon und Spalte „Ebenen“ auf niedrigen Bildschirmen (style.css). Ohne Anfragen nach außen."""
import inspect
import re
from pathlib import Path

import pytest

from pipeline import config, gebietsseiten, seo

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
CHAT_QUELLEN = ("https://api.anthropic.com", "https://api.mistral.ai", "https://openrouter.ai", "http://localhost:*",
                "http://127.0.0.1:*")
CHAT_HOSTS = ("api.anthropic.com", "api.mistral.ai", "openrouter.ai", "localhost", "127.0.0.1")


def _freigaben(monkeypatch, **an):
    for k in ("chat", "mitmachen"):
        monkeypatch.setitem(config.ZUSATZTHEMEN, k, an.get(k, False))


def _connect_src(html):
    (richtlinie,) = seo.csp_richtlinien(html)
    (d,) = [d.split() for d in richtlinie.split(";") if d.split() and d.split()[0] == "connect-src"]
    return d[1:]


# --- (1) Content-Security-Policy -------------------------------------------------------------------------------------

def test_quelle_fuehrt_die_volle_liste():
    """site/index.html behält alle Quellen des Ratsassistenten für eine spätere Freigabe; seo.py nennt dieselben."""
    assert seo.CSP_NUR_MIT_FREIGABE == {"chat": CHAT_QUELLEN}
    assert _connect_src(INDEX) == ["'self'", *CHAT_QUELLEN]


def test_csp_deckt_die_anbieter_des_assistenten():
    """Jeder Anbieter in site/chat/providers.js (Adresse der Anfrage und Modellliste) steht in CSP_NUR_MIT_FREIGABE,
    damit die Freigabe „chat“ später ohne Lücke in connect-src auskommt."""
    providers = (ROOT / "site" / "chat" / "providers.js").read_text(encoding="utf-8")
    hosts = set(re.findall(r'(?:url|modelsUrl): "https?://([^/:"]+)', providers))
    assert hosts == {"api.anthropic.com", "api.mistral.ai", "openrouter.ai", "localhost"}
    assert hosts <= {seo._host(q) for q in seo.CSP_NUR_MIT_FREIGABE["chat"]}
    assert "127\\.0\\.0\\.1" in providers   # lokale Modelle auch unter 127.0.0.1 (LOCAL)


def test_csp_ohne_chat(monkeypatch):
    """Ohne Freigabe „chat“: connect-src nur 'self'; alle übrigen Direktiven und der Rest der Seite unverändert; kein
    Host des Assistenten mehr in der Richtlinie. Mit Freigabe bleibt die Seite unverändert."""
    _freigaben(monkeypatch)
    aus = seo.csp_ohne_abgeschaltete(INDEX)
    assert _connect_src(aus) == ["'self'"]
    (vorher,), (nachher,) = seo.csp_richtlinien(INDEX), seo.csp_richtlinien(aus)
    assert [d for d in vorher.split(";") if "connect-src" not in d] == [d for d in nachher.split(";") if "connect-src" not in d]
    assert "; connect-src 'self'; object-src 'none';" in nachher
    assert not [h for h in CHAT_HOSTS if h in nachher]
    assert aus.replace(nachher, "") == INDEX.replace(vorher, "")
    _freigaben(monkeypatch, chat=True)
    assert seo.csp_ohne_abgeschaltete(INDEX) == INDEX
    _freigaben(monkeypatch, mitmachen=True)   # andere Freigaben ändern nichts an der CSP
    assert seo.csp_ohne_abgeschaltete(INDEX) == aus


def test_csp_formen(monkeypatch):
    """Bleibt in connect-src keine Quelle, gilt 'none'; Seiten ohne connect-src oder ohne CSP bleiben unverändert; ein
    Host des Assistenten in anderer Direktive, Schreibweise oder Form des meta-Elements bricht den Bau ab."""
    _freigaben(monkeypatch)
    meta = '<meta http-equiv="Content-Security-Policy" content="{}">'
    nur = meta.format("default-src 'self'; connect-src https://api.mistral.ai http://localhost:*")
    assert seo.csp_ohne_abgeschaltete(nur) == meta.format("default-src 'self'; connect-src 'none'")
    for gleich in (meta.format(gebietsseiten.CSP), "<p>ohne Richtlinie</p>",
                   meta.format("default-src 'self'; connect-src 'self' https://tile.openstreetmap.org")):
        assert seo.csp_ohne_abgeschaltete(gleich) == gleich
    for falsch in (meta.format("default-src 'self'; img-src https://api.anthropic.com"),
                   meta.format("connect-src 'self' https://API.Anthropic.com"),
                   meta.format("connect-src 'self' http://127.0.0.1:11434"),
                   "<meta content=\"connect-src 'self' https://openrouter.ai\" http-equiv='content-security-policy'>"):
        with pytest.raises(ValueError, match="abgeschalteten Funktion"):
            seo.csp_ohne_abgeschaltete(falsch)
        _freigaben(monkeypatch, chat=True)
        assert seo.csp_ohne_abgeschaltete(falsch) == falsch
        _freigaben(monkeypatch)


def test_csp_auf_allen_seiten(monkeypatch, tmp_path):
    """seo.csp_alle wendet die Regel auf jede HTML-Datei unter der Seite an (auch Unterordner) und schreibt nur
    geänderte Dateien."""
    _freigaben(monkeypatch)
    (tmp_path / "a" / "b").mkdir(parents=True)
    unter = '<meta http-equiv="Content-Security-Policy" content="connect-src \'self\' https://openrouter.ai">'
    ohne = '<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">'
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "a" / "b" / "index.html").write_text(unter, encoding="utf-8")
    (tmp_path / "a" / "ohne.html").write_text(ohne, encoding="utf-8")
    (tmp_path / "a" / "daten.json").write_text('{"x": "https://openrouter.ai"}', encoding="utf-8")
    assert seo.csp_alle(tmp_path) == 2
    assert _connect_src((tmp_path / "index.html").read_text(encoding="utf-8")) == ["'self'"]
    assert (tmp_path / "a" / "b" / "index.html").read_text(encoding="utf-8") == unter.replace(
        "'self' https://openrouter.ai", "'self'")
    assert (tmp_path / "a" / "ohne.html").read_text(encoding="utf-8") == ohne
    assert seo.csp_alle(tmp_path) == 0


def test_write_ruft_csp_fuer_alle_seiten():
    """seo.write wendet die CSP-Regel zuletzt auf alle Seiten an (nach den erzeugten Gebiets- und Themenseiten)."""
    quelle = inspect.getsource(seo.write)
    assert quelle.index("csp_alle(site)") > quelle.index('(site / "sitemap.xml").write_text')


# --- (2) Flächen nur mit Freigabe ------------------------------------------------------------------------------------

FLAECHEN = {"panel-assistent": "chat", "panel-mitmachen": "mitmachen"}


def _ids(html):
    return set(re.findall(r'\bid="([^"]+)"', html))


@pytest.mark.parametrize("chat,mitmachen", [(False, False), (True, False), (False, True), (True, True)])
def test_flaechen_nur_mit_freigabe(monkeypatch, chat, mitmachen):
    """index.html: Fläche „Ratsassistent“ samt Schaltfläche in der Leiste nur mit „chat“, „Mitmachen in Köln“ nur mit
    „mitmachen“; alle übrigen Flächen bleiben; die Seite bleibt wohlgeformt (section und button geschlossen). Mit beiden
    Freigaben entfernt ohne_abgeschaltete_bereiche nichts."""
    _freigaben(monkeypatch, chat=chat, mitmachen=mitmachen)
    aus = seo.ohne_abgeschaltete(INDEX)
    an = {"chat": chat, "mitmachen": mitmachen}
    for flaeche, funktion in FLAECHEN.items():
        assert (flaeche in _ids(aus)) == an[funktion], flaeche
        assert (flaeche in aus) == an[funktion], flaeche   # auch kein data-panel, aria-controls oder data-close
    assert ('class="toggle toggle-ai"' in aus) == chat
    for bleibt in ("panel-list", "panel-detail", "panel-auswertung", "panel-termine", "panel-prozesse", "timeline-wrap",
                   "cta-mitmachen", "mega-mitmachen", "sources", "map"):
        assert bleibt in _ids(aus), bleibt
    for tag in ("section", "button", "form", "details", "div"):
        assert aus.count(f"<{tag} ") + aus.count(f"<{tag}>") == aus.count(f"</{tag}>"), tag
    assert aus.count("\n\n\n") == INDEX.count("\n\n\n")   # keine zusätzlichen Leerzeilen
    assert ("data-freigabe" in re.sub(r"<!--.*?-->", "", aus, flags=re.S)) == (chat or mitmachen)
    if chat and mitmachen:
        assert seo.ohne_abgeschaltete_bereiche(INDEX) == INDEX


def test_flaechen_quelle():
    """Die Quelle markiert genau diese Elemente mit data-freigabe: die beiden Flächen und die Schaltfläche des
    Assistenten; Flächen tragen kein data-funktion (app.js würde sie sonst bei Freigabe öffnen, style.css sie mit
    display: none ohne Bewegung schließen)."""
    gefunden = [(f, INDEX[a:INDEX.index(">", a) + 1]) for f, a, _ in seo.bereiche_mit_freigabe(INDEX)]
    assert [f for f, _ in gefunden] == ["chat", "chat", "mitmachen"]
    assert 'data-panel="panel-assistent"' in gefunden[0][1]
    assert 'id="panel-assistent"' in gefunden[1][1] and 'id="panel-mitmachen"' in gefunden[2][1]
    assert all("data-funktion" not in tag for _, tag in gefunden[1:])


def test_bereiche_formen(monkeypatch):
    """ohne_abgeschaltete_bereiche: gleichnamige Elemente im Inneren, Element im Fließtext, ohne Leerzeile davor,
    Kommentar; ein Element ohne schließendes Tag bricht den Bau ab; mit Freigabe unverändert."""
    _freigaben(monkeypatch)
    beispiele = {
        '<main>\n  <section data-freigabe="chat" hidden>\n    <section>innen</section>\n  </section>\n  <p>B</p>\n</main>':
            "<main>\n  <p>B</p>\n</main>",
        '<p>A<span data-freigabe="chat">x</span>B</p>': "<p>AB</p>",
        "<div>\n\n  <section data-freigabe='mitmachen'>\n  </section>\n\n  <p>B</p>\n</div>": "<div>\n\n  <p>B</p>\n</div>",
        '<!-- <section data-freigabe="chat"> --><p>B</p>': '<!-- <section data-freigabe="chat"> --><p>B</p>',
        '<section data-freigabe="chat"><section data-freigabe="mitmachen">x</section></section><p>B</p>': "<p>B</p>",
        '<p>A<img alt="a>b" data-freigabe="chat"/>B</p>': "<p>AB</p>",
    }
    for html, erwartet in beispiele.items():
        assert seo.ohne_abgeschaltete_bereiche(html) == erwartet, html
    with pytest.raises(ValueError, match="ohne schließendes Tag"):
        seo.ohne_abgeschaltete_bereiche('<section data-freigabe="chat"><p>B</p>')
    _freigaben(monkeypatch, chat=True, mitmachen=True)
    for html in beispiele:
        assert seo.ohne_abgeschaltete_bereiche(html) == html
    _freigaben(monkeypatch, chat=True)
    assert seo.ohne_abgeschaltete_bereiche(
        '<section data-freigabe="chat"><section data-freigabe="mitmachen">x</section></section>') == \
        '<section data-freigabe="chat"></section>'


def test_app_kommt_ohne_flaechen_aus():
    """site/app.js: Listen der Flächen nur mit vorhandenen Elementen; setPanel und focusPanel übergehen fehlende
    Flächen; kein ungeschützter Zugriff auf die beiden Flächen (Adresse ?mitmachen=1, Abstand der Karte, Adresse
    der Seite)."""
    for liste in ("SHEETS", "LEFT", "OVERLAYS"):
        assert re.search(rf"const {liste} = \[[^\]]*\]\.filter\(vorhanden\);", APP), liste
    for funktion in ("setPanel", "focusPanel"):
        kopf = re.search(rf"function {funktion}\(id(?:, open)?\) {{\n    const el = document.getElementById\(id\);\n"
                         r"    if \(!el\) return;", APP)
        assert kopf, funktion
    for flaeche in FLAECHEN:
        for zugriff in re.finditer(rf'\$\("#{flaeche}"\)\.hidden', APP):
            zeile = APP[APP.rfind("\n", 0, zugriff.start()):APP.find("\n", zugriff.end())]
            assert f'vorhanden("{flaeche}")' in zeile, zeile
    assert 'params.get("mitmachen") === "1" && vorhanden("panel-mitmachen")' in APP
    assert "if (t && vorhanden(t.dataset.panel))" in APP


# --- (3) Kommentare ohne OParl-Lite -----------------------------------------------------------------------------------

def test_kommentare_ohne_oparl_lite():
    """site/app.js und site/mitwirken.js nennen OParl-Lite und machdenstaat nicht mehr; Köln: OParl von SessionNet."""
    for name in ("app.js", "mitwirken.js"):
        text = (ROOT / "site" / name).read_text(encoding="utf-8")
        assert "OParl-Lite" not in text and "machdenstaat" not in text, name
        assert "SessionNet" in text, name


# --- (4) und (5) Blatt „Karte“ und Spalte „Ebenen“ --------------------------------------------------------------------

def test_blatt_karte_nicht_unter_einer_flaeche():
    """Telefon: Das Blatt „Karte“ liegt in #map (z-index 0) unter jeder Fläche; daher schließt es beim Öffnen die
    Flächen (wie die Mega-Menüs), und eine Fläche, die aufgeht, schließt das Blatt."""
    assert re.search(r"if \(open && MOBILE\.matches\) SHEETS\.forEach\(\(s\) => !document\.getElementById\(s\)\.hidden "
                     r"&& setPanel\(s, false\)\);\n        \};\n        setMapMenu = set;", APP)
    teil = APP[APP.index("  function setPanel(id, open) {"):APP.index("  function focusPanel(id) {")]
    assert teil.index("if (!open) return;") < teil.index("if (MOBILE.matches) setMapMenu(false);")
    layout = APP[APP.index("  function applyLayout() {"):APP.index("  // --- Mega-Menüs")]
    assert "if (open.length) setMapMenu(false);" in layout   # Wechsel auf Telefonbreite bei offener Fläche
    assert "#map { position: fixed; inset: 0; z-index: 0;" in STYLE


def _block(css, kopf):
    i = css.index(kopf)
    return css[i:css.index("\n}\n", i)]


def test_ebenen_und_kopf_in_style_css():
    """style.css: Spalte „Ebenen“ auf niedrigen Bildschirmen enger (Stufen bis 1000 und 800 px mit den Werten, die bis
    Runde 20 nur in strukturdaten.css standen, neu bis 660 px); Kopf des Blatts „Karte“ über dem Stapel der Legenden
    (Leaflet-Steuerelement, z-index 800). strukturdaten.css enthält diese Regeln nicht mehr doppelt."""
    stufe1 = _block(STYLE, "@media (min-width: 901px) and (max-height: 1000px) {")
    assert ".leaflet-container.map-menu-open .leaflet-right .map-style:not(.map-menu) { padding: 5px 10px; }" in stufe1
    assert ".leaflet-container.map-menu-open .leaflet-bottom.leaflet-right .leaflet-control { margin-bottom: 5px; }" in stufe1
    stufe2 = _block(STYLE, "@media (min-width: 901px) and (max-height: 800px) {")
    assert "{ padding: 3px 8px; font-size: 12px; }" in stufe2 and "{ margin-bottom: 3px; }" in stufe2
    stufe3 = _block(STYLE, "@media (min-width: 901px) and (max-height: 660px) {")
    assert "{ padding: 2px 8px; }" in stufe3 and "{ margin-bottom: 2px; }" in stufe3
    telefon = _block(STYLE, "@media (max-width: 900px) {\n  .leaflet-container.map-menu-open .map-sheet {")
    (z,) = re.findall(r"\.map-sheet-kopf \{[^}]*z-index: (\d+);", telefon)
    assert int(z) > 800
    sd = (ROOT / "site" / "strukturdaten" / "strukturdaten.css").read_text(encoding="utf-8")
    assert "map-menu-open" not in sd and "map-sheet-kopf" not in sd
