/* PNG export dialog: Escape closes it (the backdrop click is handled by Dash) and each opening starts at the top. */
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const modal = document.getElementById("png-modal");
  if (modal && modal.classList.contains("open")) {
    const cancel = document.getElementById("png-cancel");
    if (cancel) cancel.click();
  }
});

new MutationObserver(() => {
  const modal = document.getElementById("png-modal");
  if (!modal || !modal.classList.contains("open") || modal.dataset.wasOpen) return;
  modal.dataset.wasOpen = "1";
  const controls = modal.querySelector(".png-controls");
  if (controls) controls.scrollTop = 0;
}).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ["class"] });

new MutationObserver(() => {
  const modal = document.getElementById("png-modal");
  if (modal && !modal.classList.contains("open")) delete modal.dataset.wasOpen;
}).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ["class"] });
