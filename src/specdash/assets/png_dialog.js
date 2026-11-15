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

/*
 * Color pickers for the per-curve color fields ("Curves" group).
 *
 * Dash has no color input, so each hex text field (a dcc.Input inside .png-color) gets a native
 * <input type="color"> swatch in front of it. The two stay in sync; a change made with the picker is
 * written into the text field like typing, so Dash sees it as an ordinary edit.
 */
(function () {
  const HEX6 = /^#[0-9a-f]{6}$/i;
  const HEX3 = /^#[0-9a-f]{3}$/i;
  const setText = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;

  const asHex6 = (text) => {
    const value = text.trim();
    if (HEX3.test(value)) return "#" + Array.from(value.slice(1), (c) => c + c).join("");
    return HEX6.test(value) ? value : null;
  };

  function attach(box) {
    const text = box.querySelector("input");
    if (!text || box.querySelector(".png-swatch")) return;
    const swatch = document.createElement("input");
    swatch.type = "color";
    swatch.className = "png-swatch";
    const sync = () => {
      const hex = asHex6(text.value);
      if (hex) swatch.value = hex.toLowerCase();
    };
    swatch.addEventListener("input", () => {
      setText.call(text, swatch.value);
      text.dispatchEvent(new Event("input", { bubbles: true }));
    });
    text.addEventListener("input", sync);
    box.prepend(swatch);
    sync();
  }

  function attachAll(host) {
    host.querySelectorAll(".png-color").forEach(attach);
  }

  // The rows are rebuilt by Dash whenever the curves change, so watch their container.
  const waitForHost = new MutationObserver(() => {
    const host = document.getElementById("png-curve-rows");
    if (!host) return;
    waitForHost.disconnect();
    new MutationObserver(() => attachAll(host)).observe(host, { childList: true, subtree: true });
    attachAll(host);
  });
  waitForHost.observe(document.documentElement, { childList: true, subtree: true });
})();
