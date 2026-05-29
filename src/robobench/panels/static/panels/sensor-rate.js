import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

// uPlot is loaded as a global from /static/lib/uPlot.iife.min.js.

const MAX_POINTS = 60;

export function initSensorPanel(root) {
  root.innerHTML = `
    <h3>Sensor rate <span class="pill" id="sensor-pill">…</span></h3>
    <div id="sensor-plot" class="graph"></div>
    <div class="metric" id="sensor-metric">waiting…</div>
    <ul class="fixes" id="sensor-fixes"></ul>`;

  const pill = root.querySelector("#sensor-pill");
  const metric = root.querySelector("#sensor-metric");
  const fixes = root.querySelector("#sensor-fixes");
  const plotEl = root.querySelector("#sensor-plot");

  const xs = [];
  const ys = [];
  let t = 0;

  const opts = {
    width: plotEl.clientWidth || 320,
    height: 160,
    scales: { x: { time: false } },
    series: [
      {},
      { label: "scan Hz", stroke: "#64b5f6", width: 2, fill: "rgba(100,181,246,0.1)" },
    ],
    axes: [
      { stroke: "#8a939b", grid: { stroke: "#2a333d" } },
      { stroke: "#8a939b", grid: { stroke: "#2a333d" } },
    ],
  };
  // eslint-disable-next-line no-undef
  const plot = new uPlot(opts, [xs, ys], plotEl);

  startPolling("sensors", 1000, (data) => {
    const scan = data.scan;
    renderStatusPill(pill, scan.status);
    metric.textContent = `${scan.rate_hz.toFixed(1)} Hz`;
    xs.push(t++);
    ys.push(scan.rate_hz);
    if (xs.length > MAX_POINTS) {
      xs.shift();
      ys.shift();
    }
    plot.setData([xs, ys]);
    renderFixes(fixes, scan.fixes);
  });
}
