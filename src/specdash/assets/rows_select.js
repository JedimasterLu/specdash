/*
 * Row selection on the detector image (#rows-graph).
 *
 * Drag on empty space to select rows, drag an edge to resize, drag inside the
 * selection to move it. The outline is the figure's first shape and follows the
 * cursor, snapped to whole rows; on release the range goes to the "rows" store.
 */
(function () {
  const GRAPH_ID = "rows-graph";
  const EDGE_PX = 5;
  let drag = null;

  function geometry(gd) {
    const ya = gd._fullLayout && gd._fullLayout.yaxis;
    const shape = gd.layout && gd.layout.shapes && gd.layout.shapes[0];
    const count = gd.layout && gd.layout.meta && gd.layout.meta.count;
    if (!ya || !shape || !count) return null;
    const box = gd.getBoundingClientRect();
    const [bottom, top] = ya.range; // reversed axis: row 1 is at the top
    return {
      count,
      first: Math.round(shape.y0 + 0.5),
      last: Math.round(shape.y1 - 0.5),
      top: box.top + ya._offset,
      length: ya._length,
      left: box.left + gd._fullLayout.xaxis._offset,
      width: gd._fullLayout.xaxis._length,
      toRow: (clientY) => top + ((clientY - box.top - ya._offset) / ya._length) * (bottom - top),
      toPx: (row) => box.top + ya._offset + ((row - top) / (bottom - top)) * ya._length,
    };
  }

  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  // Row boundaries sit at k + 0.5; this is the index k of the nearest one.
  const boundary = (row, count) => clamp(Math.round(row - 0.5), 0, count);

  function selection(g, e) {
    const row = g.toRow(e.clientY);
    if (drag.mode === "move") {
      const height = drag.last - drag.first + 1;
      const k = clamp(Math.round(row - drag.grab - 0.5), 0, g.count - height);
      return [k + 1, k + height];
    }
    const k = boundary(row, g.count);
    if (k === drag.anchor) {
      const single = clamp(Math.round(row), 1, g.count);
      return [single, single];
    }
    return [Math.min(k, drag.anchor) + 1, Math.max(k, drag.anchor)];
  }

  function show(gd, [first, last]) {
    window.Plotly.relayout(gd, { "shapes[0].y0": first - 0.5, "shapes[0].y1": last + 0.5 });
  }

  function hit(g, e) {
    const inside = e.clientX >= g.left && e.clientX <= g.left + g.width;
    const y = e.clientY;
    if (!inside || y < g.top || y > g.top + g.length) return null;
    const topPx = g.toPx(g.first - 0.5);
    const bottomPx = g.toPx(g.last + 0.5);
    const edge = Math.min(EDGE_PX, (bottomPx - topPx) / 3);
    if (Math.abs(y - topPx) <= edge) return { mode: "resize", anchor: g.last, edge: true };
    if (Math.abs(y - bottomPx) <= edge) return { mode: "resize", anchor: g.first - 1, edge: true };
    const all = g.first === 1 && g.last === g.count;
    if (!all && y > topPx && y < bottomPx) return { mode: "move", grab: g.toRow(y) - (g.first - 0.5) };
    return { mode: "resize", anchor: boundary(g.toRow(y), g.count) };
  }

  function graphOf(e) {
    const wrapper = e.target.closest ? e.target.closest("#" + GRAPH_ID) : null;
    return wrapper && wrapper.querySelector(".js-plotly-plot");
  }

  document.addEventListener(
    "mousedown",
    (e) => {
      const gd = graphOf(e);
      if (!gd || e.button !== 0 || !gd._fullLayout) return;
      const g = geometry(gd);
      const start = g && hit(g, e);
      if (!start) return;
      e.preventDefault();
      drag = { gd, first: g.first, last: g.last, ...start };
      show(gd, selection(g, e));
    },
    true
  );

  document.addEventListener("mousemove", (e) => {
    if (drag) {
      const g = geometry(drag.gd);
      if (g) show(drag.gd, selection(g, e));
      return;
    }
    const gd = graphOf(e);
    const g = gd && gd._fullLayout && geometry(gd);
    const start = g && hit(g, e);
    const layer = e.target;
    if (gd && layer.style) {
      layer.style.cursor = !start ? "default" : start.edge ? "ns-resize" : start.mode === "move" ? "grab" : "crosshair";
    }
  });

  document.addEventListener("mouseup", (e) => {
    if (!drag) return;
    const gd = drag.gd;
    const g = geometry(gd);
    const [first, last] = g ? selection(g, e) : [drag.first, drag.last];
    drag = null;
    show(gd, [first, last]);
    if (g) window.dash_clientside.set_props("rows", { data: { first, last, count: g.count } });
  });
})();
