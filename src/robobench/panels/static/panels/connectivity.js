// src/robobench/panels/static/panels/connectivity.js
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

export function initConnectivityPanel(root) {
  root.innerHTML = `
    <h3>Connectivity (SSH) <span class="pill" id="conn-pill">…</span></h3>
    <ul class="ladder" id="conn-ladder"></ul>
    <ul class="fixes" id="conn-fixes"></ul>`;

  const pill = root.querySelector("#conn-pill");
  const ladder = root.querySelector("#conn-ladder");
  const fixes = root.querySelector("#conn-fixes");

  startPolling("connectivity", 5000, (data) => {
    renderStatusPill(pill, data.status);
    if (data.status === "UNKNOWN" || data.layers.length === 0) {
      ladder.innerHTML = `<li class="muted">waiting for SSH probe…</li>`;
    } else {
      ladder.innerHTML = data.layers
        .map((layer) => {
          const broken = layer.name === data.first_broken;
          const mark = layer.ok ? "✓" : "✗";
          const cls = layer.ok ? "ok" : broken ? "broken" : "down";
          return `<li class="layer ${cls}"><span class="mark">${mark}</span>${layer.label}</li>`;
        })
        .join("");
    }
    renderFixes(fixes, data.fixes);
  });
}
