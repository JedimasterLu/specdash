/*
 * Live readout for the detector image (#rows-graph): writes "<nm> nm | row <n> | <value>"
 * into #rows-hover while the cursor is over a pixel and clears it otherwise.
 */
(function () {
  function bind(gd) {
    gd._readoutBound = true;
    gd.on("plotly_hover", (e) => {
      const out = document.getElementById("rows-hover");
      const p = e.points && e.points[0];
      if (out && p) out.textContent = `${p.x.toFixed(1)} nm | row ${p.y} | ${p.z.toFixed(1)}`;
    });
    gd.on("plotly_unhover", () => {
      const out = document.getElementById("rows-hover");
      if (out) out.textContent = "";
    });
  }

  // Capture phase: bind before Plotly handles the first mouse move over the graph.
  document.addEventListener("mousemove", (e) => {
    const gd = e.target.closest && e.target.closest("#rows-graph .js-plotly-plot");
    if (gd && !gd._readoutBound && gd.on) bind(gd);
  }, true);
})();
