// Seite rss/ (pipeline/rssseite.py): Feed-Adresse und Beispiele kopieren, mit Rückmeldung. Ohne Skript bleiben die
// Knöpfe verborgen und die Adresse ist ein markierbares Feld. Schlägt das Kopieren fehl, ist der Text markiert und die
// Meldung nennt die Tastenkombination.
(() => {
  const taste = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘+C" : "Strg+C";

  function markieren(el) {
    if (el instanceof HTMLInputElement) { el.focus(); el.select(); return; }
    const r = document.createRange();
    r.selectNodeContents(el);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }

  async function kopieren(text, quelle) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* weiter mit dem Ausweichweg */ }
    if (!quelle) return false;
    markieren(quelle);
    try { return document.execCommand("copy"); } catch (e) { return false; }
  }

  // Meldung je Knopf: vorhandenes Statusfeld oder eines direkt hinter dem Knopf
  function feld(knopf) {
    if (knopf.dataset.kopieren === "#rss-url" && knopf.closest(".rss-cta")) return document.getElementById("rss-meldung");
    let f = knopf.nextElementSibling;
    if (!f || !f.classList.contains("rss-meldung")) {
      f = document.createElement("span");
      f.className = "rss-meldung";
      f.setAttribute("role", "status");
      knopf.after(f);
    }
    return f;
  }

  async function los(knopf) {
    const quelle = knopf.dataset.kopieren ? document.querySelector(knopf.dataset.kopieren) : null;
    const text = knopf.dataset.text || (quelle ? (quelle.value ?? quelle.textContent).trim() : "");
    const meldung = feld(knopf);
    const ok = text && await kopieren(text, quelle);
    meldung.classList.toggle("rss-fehler", !ok);
    meldung.textContent = ok
      ? (knopf.dataset.kopieren === "#rss-url" || knopf.dataset.text ? "Adresse kopiert. Jetzt im Feed-Reader einfügen." : "Kopiert.")
      : `Kopieren hat nicht geklappt. Der Text ist markiert: bitte mit ${taste} kopieren.`;
    if (!ok && quelle) markieren(quelle);
    clearTimeout(meldung.zeit);
    meldung.zeit = setTimeout(() => { meldung.textContent = ""; }, 8000);
  }

  // Kopierknöpfe zeigen; je Feed der Liste ein kleiner Knopf
  document.querySelectorAll("button[data-kopieren]").forEach((b) => { b.hidden = false; });
  document.querySelectorAll("a[data-feed]").forEach((a) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "rss-kopie";
    b.textContent = "kopieren";
    b.dataset.text = a.href;
    b.setAttribute("aria-label", `Adresse kopieren: ${a.textContent}`);
    a.after(b);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-kopieren], button.rss-kopie");
    if (b) los(b);
    const weiter = e.target.closest('a[href="#weitere"]');
    if (weiter) document.getElementById("weitere").open = true;
  });
  // Feld: ein Klick markiert die ganze Adresse (Ausweichweg ohne Kopierknopf)
  const url = document.getElementById("rss-url");
  if (url) url.addEventListener("focus", () => url.select());
  if (location.hash === "#weitere") document.getElementById("weitere").open = true;
})();
