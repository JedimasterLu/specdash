/*
 * Tells the server this tab is open so it can quit when the last one closes.
 * Active only when the layout contains #heartbeat (the windowed build).
 */
(function () {
  const tab = Math.random().toString(36).slice(2);
  const send = (path) => {
    if (!document.getElementById("heartbeat")) return;
    fetch("/_specdash/" + path, { method: "POST", body: tab, keepalive: true }).catch(() => {});
  };
  setInterval(() => send("ping"), 2000);
  send("ping");
  window.addEventListener("pagehide", () => send("bye"));
})();
