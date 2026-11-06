/*
 * Bridge between the drop zones and the pywebview window.
 *
 * - Highlights the drop zone under a dragged file (same look as hover).
 * - Remembers which zone received a drop in window.__dropRole; the file paths
 *   themselves arrive in Python through pywebview's native drop handler.
 * - Clicking a zone opens the native file dialog (pywebview.api.browse).
 */
(function () {
  const ACTIVE = "drag-active";
  const zoneOf = (el) => (el && el.closest ? el.closest(".dropzone") : null);
  const roleOf = (zone) => (zone ? zone.id.replace(/^upload-/, "") : null);
  const clearActive = () => document.querySelectorAll("." + ACTIVE).forEach((n) => n.classList.remove(ACTIVE));

  // Capture phase and no stopPropagation: pywebview's own listener must still see the event.
  document.addEventListener(
    "dragover",
    (e) => {
      e.preventDefault(); // required for the drop event to fire
      const zone = zoneOf(e.target);
      document.querySelectorAll("." + ACTIVE).forEach((n) => n !== zone && n.classList.remove(ACTIVE));
      if (zone) zone.classList.add(ACTIVE);
    },
    true
  );
  document.addEventListener("dragleave", (e) => {
    if (!e.relatedTarget) clearActive();
  }, true);
  document.addEventListener(
    "drop",
    (e) => {
      e.preventDefault();
      window.__dropRole = roleOf(zoneOf(e.target)); // null: dropped elsewhere, treated as signal files
      clearActive();
    },
    true
  );

  document.addEventListener(
    "click",
    (e) => {
      const zone = zoneOf(e.target);
      const api = window.pywebview && window.pywebview.api;
      if (zone && api && api.browse) api.browse(roleOf(zone));
    },
    true
  );
})();
