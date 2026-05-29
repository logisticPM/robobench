import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

export function initClockPanel(root) {
  root.innerHTML = `
    <h3>Clock offset <span class="pill" id="clock-pill">…</span></h3>
    <div class="metric" id="clock-offset">waiting…</div>
    <ul class="fixes" id="clock-fixes"></ul>`;

  const pill = root.querySelector("#clock-pill");
  const offset = root.querySelector("#clock-offset");
  const fixes = root.querySelector("#clock-fixes");

  startPolling("clock", 2000, (data) => {
    renderStatusPill(pill, data.status);
    offset.textContent =
      data.offset_seconds === null
        ? "no data (robot not reachable?)"
        : `offset: ${data.offset_seconds.toFixed(2)} s`;
    renderFixes(fixes, data.fixes);
  });
}
