// Seite technik/ (pipeline/technikseite.py): Ein Klick auf einen Kasten zeigt seine Erklärung unter der Grafik,
// statt zum Eintrag in der zugeklappten Liste zu springen. Ohne Skript führt der Link zum Eintrag der Liste.
(() => {
  "use strict";
  const zeige = (figur, link, fokus) => {
    const ziel = document.getElementById(decodeURIComponent(link.getAttribute("href").slice(1)));
    const feld = figur.querySelector(".tk-detail");
    if (!ziel || !feld) return false;
    figur.querySelectorAll(".tk-box[aria-current]").forEach((a) => a.removeAttribute("aria-current"));
    figur.querySelectorAll(`.tk-box[href="${link.getAttribute("href")}"]`).forEach((a) => a.setAttribute("aria-current", "true"));
    feld.replaceChildren(...[...ziel.childNodes].map((n) => n.cloneNode(true)));
    feld.hidden = false;
    if (fokus) feld.scrollIntoView({ block: "nearest" });
    return true;
  };
  document.querySelectorAll(".tk-grafik").forEach((figur) => {
    figur.addEventListener("click", (e) => {
      const link = e.target.closest(".tk-box");
      if (link && zeige(figur, link, true)) {
        e.preventDefault();
        history.replaceState(null, "", link.getAttribute("href"));
      }
    });
  });
  // Seitenlink mit Kasten (#tk-…): Erklärung unter der zugehörigen Grafik zeigen
  if (location.hash.startsWith("#tk-")) {
    const link = [...document.querySelectorAll(".tk-grafik .tk-box")].find((a) => a.getAttribute("href") === location.hash);
    if (link) zeige(link.closest(".tk-grafik"), link, true);
  }
})();
