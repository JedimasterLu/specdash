/*
 * X-region masks on the peak fit plot (#fit-graph), edited like the row intervals on the detector image.
 *
 * Every mask is three shapes (fill, left edge, right edge; see figures.mask_shapes) and layout.meta.active
 * says which mask a drag on empty space replaces. Drag an edge to resize a mask, drag inside it to move it,
 * drag on empty space to select a new X range for the active mask. On release all ranges go to the "fit-masks" store.
 */
(function () {
  const GRAPH_ID = "fit-graph";
  const EDGE_PX = 5;
  const MIN_PX = 3;
  let drag = null;

  function geometry(gd) {
    const layout = gd._fullLayout;
    const xa = layout && layout.xaxis;
    if (!xa || !gd.data || !gd.data.length) return null;
    const shapes = (gd.layout && gd.layout.shapes) || [];
    const box = gd.getBoundingClientRect();
    const [r0, r1] = xa.range;
    const count = Math.floor(shapes.length / 3);
    const left = box.left + xa._offset;
    const lo = Math.min(r0, r1);
    const hi = Math.max(r0, r1);
    return {
      count,
      active: Math.min(Math.max((gd.layout.meta && gd.layout.meta.active) || 0, 0), Math.max(count - 1, 0)),
      ranges: Array.from({ length: count }, (_, i) => [shapes[3 * i].x0, shapes[3 * i].x1]),
      left,
      width: xa._length,
      top: box.top + layout._size.t,
      height: layout._size.h,
      lo,
      hi,
      toX: (clientX) => Math.min(Math.max(r0 + ((clientX - left) / xa._length) * (r1 - r0), lo), hi),
      toPx: (x) => left + ((x - r0) / (r1 - r0)) * xa._length,
    };
  }

  function selection(g, e) {
    const x = g.toX(e.clientX);
    if (drag.mode === "move") {
      const width = drag.last - drag.first;
      const start = Math.min(Math.max(x - drag.grab, g.lo), g.hi - width);
      return [start, start + width];
    }
    return [Math.min(x, drag.anchor), Math.max(x, drag.anchor)];
  }

  function show(gd, index, g, [a, b]) {
    if (index >= g.count) {
      // No mask yet: a temporary band until the store (and so the figure) is updated on release.
      window.Plotly.relayout(gd, {
        shapes: [{ type: "rect", xref: "x", yref: "paper", x0: a, x1: b, y0: 0, y1: 1, fillcolor: "rgba(42,120,214,0.2)", line: { width: 0 } }],
      });
      return;
    }
    const i = 3 * index;
    window.Plotly.relayout(gd, {
      [`shapes[${i}].x0`]: a, [`shapes[${i}].x1`]: b,
      [`shapes[${i + 1}].x0`]: a, [`shapes[${i + 1}].x1`]: a,
      [`shapes[${i + 2}].x0`]: b, [`shapes[${i + 2}].x1`]: b,
    });
  }

  // What a mouse press here would do: an edge or the inside of a mask (the active one wins where they overlap),
  // or else a new range for the active mask.
  function hit(g, e) {
    const y = e.clientY;
    if (e.clientX < g.left || e.clientX > g.left + g.width || y < g.top || y > g.top + g.height) return null;
    const order = [g.active, ...g.ranges.keys()].filter((i, n, all) => i < g.count && all.indexOf(i) === n);
    const spans = order.map((index) => {
      const [first, last] = g.ranges[index];
      return { index, first, last, a: g.toPx(first), b: g.toPx(last) };
    });
    for (const { index, first, last, a, b } of spans) {
      const edge = Math.min(EDGE_PX, (b - a) / 3);
      if (Math.abs(e.clientX - a) <= edge) return { index, mode: "resize", anchor: last, edge: true };
      if (Math.abs(e.clientX - b) <= edge) return { index, mode: "resize", anchor: first, edge: true };
    }
    for (const { index, first, a, b } of spans) {
      if (e.clientX > a && e.clientX < b) return { index, mode: "move", grab: g.toX(e.clientX) - first };
    }
    return { index: g.count ? g.active : 0, mode: "new", anchor: g.toX(e.clientX) };
  }

  function graphOf(e) {
    const wrapper = e.target.closest ? e.target.closest("#" + GRAPH_ID) : null;
    return wrapper && wrapper.querySelector(".js-plotly-plot");
  }

  document.addEventListener(
    "mousedown",
    (e) => {
      const gd = graphOf(e);
      if (!gd || e.button !== 0) return;
      const g = geometry(gd);
      const start = g && hit(g, e);
      if (!start) return;
      e.preventDefault();
      const [first, last] = g.ranges[start.index] || [start.anchor, start.anchor];
      drag = { gd, first, last, startPx: e.clientX, ...start };
      show(gd, drag.index, g, selection(g, e));
    },
    true
  );

  document.addEventListener("mousemove", (e) => {
    if (drag) {
      const g = geometry(drag.gd);
      if (g) show(drag.gd, drag.index, g, selection(g, e));
      return;
    }
    const gd = graphOf(e);
    const g = gd && geometry(gd);
    const start = g && hit(g, e);
    if (gd && e.target.style) {
      e.target.style.cursor = !start ? "default" : start.edge ? "ew-resize" : start.mode === "move" ? "grab" : "crosshair";
    }
  });

  document.addEventListener("mouseup", (e) => {
    if (!drag) return;
    const { gd, index, mode, startPx, first, last } = drag;
    const g = geometry(gd);
    const final = g && selection(g, e);
    drag = null;
    if (!g) return;
    if (mode === "new" && Math.abs(e.clientX - startPx) < MIN_PX) {
      // A plain click selects nothing: put the band back (or remove the temporary one).
      if (index >= g.count) window.Plotly.relayout(gd, { shapes: [] });
      else show(gd, index, g, [first, last]);
      return;
    }
    show(gd, index, g, final);
    const ranges = g.ranges.map((r) => [...r]);
    ranges[index] = final;
    window.dash_clientside.set_props("fit-masks", { data: { ranges, active: index } });
  });
})();
