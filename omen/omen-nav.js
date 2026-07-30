/* OMEN — the mobile nav drawer.
 *
 * Below 760px the nav's link row moves out of the bar and becomes a panel under it. The
 * styling is in omen.css; this file only owns the open/closed state, so the five pages
 * that carry the nav share one implementation instead of five inline copies.
 *
 * Kept out of omen-common.js on purpose: that file is read and eval'd by the node test
 * suites and is documented as free of DOM access at load time. This one is nothing but
 * DOM access at load time.
 */
(function () {
  "use strict";
  if (typeof document === "undefined") return;

  function mount() {
    var btn = document.querySelector(".navtoggle");
    var links = document.getElementById("navlinks");
    if (!btn || !links) return;

    function set(open) {
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) links.setAttribute("data-open", "");
      else links.removeAttribute("data-open");
    }

    btn.addEventListener("click", function () {
      set(btn.getAttribute("aria-expanded") !== "true");
    });

    // Same-page anchors (the nav is sticky, so the drawer would otherwise sit open over
    // whatever the link just scrolled to) and cross-page links both want it shut.
    links.addEventListener("click", function (e) {
      if (e.target.closest("a")) set(false);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") set(false);
    });

    // Rotating past the breakpoint must not strand the desktop link row in drawer state.
    window.addEventListener("resize", function () {
      if (window.innerWidth > 760) set(false);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
