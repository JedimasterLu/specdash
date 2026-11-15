/*
 * Centered "loading" dialog shown while files are read and the plots are redrawn.
 *
 * Driven from Python (desktop.ingest) through window.__busy, not through Dash
 * callbacks: reading happens in a Python thread, and the callback chain that
 * redraws the plots is exactly the slow part this dialog covers for.
 *
 *   expect(text) files were just dropped on the window: show the dialog before Python even hears about it
 *   show(text)   a load starts (counts as one job); the dialog appears at once. Adopts the job of expect().
 *   rendering()  the files are parsed and handed to the page: wait for the result plot to finish drawing
 *   done()       the job is over (also called by rendering() once the plot has drawn, or after a timeout)
 *   cancel()     drop the job of expect() when Python found nothing to load
 *
 * window.__busyTrace holds Date.now() stamps (drop, shown, painted) for desktop.py's SPECDASH_TRACE output.
 */
(function () {
  const EXPECT_MS = 20000; // fallback if Python never answers a drop (it normally answers or cancels within ms)
  const FAILSAFE_MS = 15000; // never leave the window blocked if the plot never redraws
  const PLOT_ID = "result-graph";

  let jobs = 0;
  let root = null;
  let label = null;
  let t0 = 0;
  let expected = false;
  let expectTimer = null;
  const trace = (window.__busyTrace = {});

  function build() {
    root = document.createElement("div");
    root.className = "busy";
    root.setAttribute("role", "alertdialog");
    root.setAttribute("aria-live", "polite");
    root.innerHTML =
      '<div class="modal-backdrop"></div>' +
      '<div class="busy-card"><div class="busy-spinner"></div><div class="busy-text"></div></div>';
    label = root.querySelector(".busy-text");
    document.body.appendChild(root);
  }

  function open(text) {
    if (jobs === 0) {
      t0 = performance.now();
      trace.shown = Date.now();
      trace.painted = null;
      requestAnimationFrame(() => requestAnimationFrame(() => (trace.painted = Date.now())));
    }
    jobs += 1;
    if (!root) build();
    label.textContent = text || "Loading…";
    // No delay: redrawing the plots blocks the page's main thread, so a timer set now
    // would only fire after the redraw, when the dialog is no longer needed.
    root.classList.add("open");
  }

  function expect(text) {
    if (expected) return;
    expected = true;
    trace.drop = Date.now();
    open(text);
    expectTimer = setTimeout(cancel, EXPECT_MS);
  }

  function cancel() {
    if (!expected) return;
    expected = false;
    clearTimeout(expectTimer);
    done();
  }

  function show(text) {
    if (expected) {
      expected = false;
      clearTimeout(expectTimer);
      if (label) label.textContent = text || "Loading…";
      return;
    }
    open(text);
  }

  function done() {
    if (jobs === 0) return;
    jobs -= 1;
    if (jobs > 0) return;
    if (root) root.classList.remove("open");
    console.info("[busy] load finished in " + Math.round(performance.now() - t0) + " ms");
  }

  // Resolves after the next time the result plot has been drawn and painted.
  function afterNextPlot(callback) {
    const holder = document.getElementById(PLOT_ID);
    const gd = holder && holder.querySelector(".js-plotly-plot");
    if (!gd || !gd.on) {
      setTimeout(callback, 300); // the plot is not there (yet): nothing better to wait for
      return;
    }
    const handler = () => {
      gd.removeListener("plotly_afterplot", handler);
      // Two frames: let the browser paint the new traces before the dialog goes away.
      requestAnimationFrame(() => requestAnimationFrame(callback));
    };
    gd.on("plotly_afterplot", handler);
  }

  function rendering() {
    if (label) label.textContent = "Drawing plots…";
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      done();
    };
    const timer = setTimeout(finish, FAILSAFE_MS);
    afterNextPlot(finish);
  }

  window.__busy = { expect, show, rendering, done, cancel };
})();
