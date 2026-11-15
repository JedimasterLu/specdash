/*
 * Row selection on the detector image (#rows-graph).
 *
 * Every selected interval is one of the figure's shapes (an outline in that interval's color);
 * layout.meta.active says which one dragging on empty space edits. Drag an edge to resize that
 * interval, drag inside it to move it, drag on empty space to select a new range for the active
 * interval. The outline follows the cursor, snapped to whole rows; on release all ranges go to
 * the "rows" store.
 */
(function () {
  const GRAPH_ID = "rows-graph";
  const EDGE_PX = 5;
  let drag = null;

  function geometry(gd) {
    const ya = gd._fullLayout && gd._fullLayout.yaxis;
    const shapes = gd.layout && gd.layout.shapes;
    const meta = gd.layout && gd.layout.meta;
    if (!ya || !shapes || !shapes.length || !meta || !meta.count) return null;
    const box = gd.getBoundingClientRect();
    const [bottom, top] = ya.range; // reversed axis: row 1 is at the top
    const toPx = (row) => box.top + ya._offset + ((row - top) / (bottom - top)) * ya._length;
    const active = Math.min(Math.max(meta.active || 0, 0), shapes.length - 1);
    return {
      count: meta.count,
      active,
      ranges: shapes.map((s) => ({ first: Math.round(s.y0 + 0.5), last: Math.round(s.y1 - 0.5) })),
      top: box.top + ya._offset,
      length: ya._length,
      left: box.left + gd._fullLayout.xaxis._offset,
      width: gd._fullLayout.xaxis._length,
      toRow: (clientY) => top + ((clientY - box.top - ya._offset) / ya._length) * (bottom - top),
      toPx,
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

  function show(gd, index, [first, last]) {
    window.Plotly.relayout(gd, { [`shapes[${index}].y0`]: first - 0.5, [`shapes[${index}].y1`]: last + 0.5 });
  }

  // What a mouse press at this point would do: an edge or the inside of an interval (the active one
  // wins where they overlap), or else a new selection for the active interval.
  function hit(g, e) {
    const inside = e.clientX >= g.left && e.clientX <= g.left + g.width;
    const y = e.clientY;
    if (!inside || y < g.top || y > g.top + g.length) return null;
    const order = [g.active, ...g.ranges.keys()].filter((i, n, all) => all.indexOf(i) === n);
    const spans = order.map((index) => {
      const { first, last } = g.ranges[index];
      return { index, first, last, topPx: g.toPx(first - 0.5), bottomPx: g.toPx(last + 0.5) };
    });
    for (const { index, first, last, topPx, bottomPx } of spans) {
      const edge = Math.min(EDGE_PX, (bottomPx - topPx) / 3);
      if (Math.abs(y - topPx) <= edge) return { index, mode: "resize", anchor: last, edge: true };
      if (Math.abs(y - bottomPx) <= edge) return { index, mode: "resize", anchor: first - 1, edge: true };
    }
    for (const { index, first, last, topPx, bottomPx } of spans) {
      const all = first === 1 && last === g.count;
      if (!all && y > topPx && y < bottomPx) return { index, mode: "move", grab: g.toRow(y) - (first - 0.5) };
    }
    return { index: g.active, mode: "resize", anchor: boundary(g.toRow(y), g.count) };
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
      const { first, last } = g.ranges[start.index];
      drag = { gd, first, last, ...start };
      show(gd, drag.index, selection(g, e));
    },
    true
  );

  document.addEventListener("mousemove", (e) => {
    if (drag) {
      const g = geometry(drag.gd);
      if (g) show(drag.gd, drag.index, selection(g, e));
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
    const { gd, index } = drag;
    const g = geometry(gd);
    const final = g && selection(g, e);
    drag = null;
    if (!g) return;
    show(gd, index, final);
    const ranges = g.ranges.map((r) => [r.first, r.last]);
    ranges[index] = final;
    window.dash_clientside.set_props("rows", { data: { count: g.count, ranges, active: index } });
  });
})();
