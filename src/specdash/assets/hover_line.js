/*
 * Vertical cursor line on the line plots (#result-graph, #inputs-graph).
 *
 * Plotly throttles its own spike lines, so this draws the line itself on every
 * mouse move. The hover labels are still Plotly's (the unified label is the
 * "g.legend" in the hover layer), but they are placed right of the line by
 * re-applying the position as a CSS transform, which style.css can ease.
 */
(function () {
  const GAP_PX = 8;
  const BOTTOM_TRIM_PX = 2;
  const ENTER_PX = 12;
  const GRAPH_IDS = ["result-graph", "inputs-graph"];
  // An SVG line placed just before the hover layer, so the label is always drawn above it.
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("style", "stroke:#8a8f98;stroke-width:1;opacity:0.8;pointer-events:none");

  let mouseX = 0;
  new MutationObserver((records) => {
    for (const { target } of records) {
      const m = target.matches(".hoverlayer > g.legend") && /translate\(([^,)\s]+)[,\s]+([^)\s]+)\)/.exec(target.getAttribute("transform"));
      if (!m) continue;
      // Sit just right of the cursor line, flipping left near the plot's right edge.
      const svg = target.ownerSVGElement.getBoundingClientRect();
      const width = target.getBBox().width;
      let x = mouseX - svg.left + GAP_PX;
      if (x + width > svg.width) x -= width + 2 * GAP_PX;
      // Trim the bottom padding; skip if Plotly has not rewritten the height since.
      const bg = target.querySelector("rect.bg");
      if (bg && bg.getAttribute("height") !== bg.dataset.trimmed) {
        bg.dataset.trimmed = String(bg.getAttribute("height") - BOTTOM_TRIM_PX);
        bg.setAttribute("height", bg.dataset.trimmed);
      }
      const place = `translate(${x}px, ${m[2]}px)`;
      if (target.style.transform) {
        target.style.transform = place;
        continue;
      }
      // First frame: start above the final spot and transparent, then ease in.
      target.style.transition = "none";
      target.style.opacity = "0";
      target.style.transform = `translate(${x}px, ${m[2] - ENTER_PX}px)`;
      target.getBoundingClientRect();
      target.style.transition = "";
      target.style.opacity = "1";
      target.style.transform = place;
    }
  }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["transform"] });

  // Capture phase: record the cursor before Plotly's handler repositions the label.
  document.addEventListener("mousemove", (e) => {
    mouseX = e.clientX;
    const gd = e.target.closest && e.target.closest(".js-plotly-plot");
    const layout = gd && GRAPH_IDS.includes(gd.parentElement.id) && gd._fullLayout;
    const hover = layout && layout.xaxis && gd.data.length && gd.querySelector(".hoverlayer");
    if (!hover) {
      line.remove();
      return;
    }
    const box = hover.ownerSVGElement.getBoundingClientRect();
    const { xaxis, yaxis } = layout;
    const x = e.clientX - box.left;
    const y = e.clientY - box.top - yaxis._offset;
    if (x < xaxis._offset || x > xaxis._offset + xaxis._length || y < 0 || y > yaxis._length) {
      line.remove();
      return;
    }
    if (line.nextSibling !== hover) hover.parentNode.insertBefore(line, hover);
    line.setAttribute("x1", x);
    line.setAttribute("x2", x);
    line.setAttribute("y1", yaxis._offset);
    line.setAttribute("y2", yaxis._offset + yaxis._length);
  }, true);
})();
