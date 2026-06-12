import { startPolling } from "/static/core/api.js";

// uPlot is loaded as a global from /static/lib/uPlot.iife.min.js.

export function initTrendsPanel(root) {
  root.innerHTML = `
    <h3>Trends (2h)</h3>
    <div id="trends-plot" class="graph"></div>
    <div class="metric" id="trends-metric">collecting samples…</div>`;

  const plotEl = root.querySelector("#trends-plot");
  const metric = root.querySelector("#trends-metric");

  const opts = {
    width: plotEl.clientWidth || 320,
    height: 200,
    scales: { x: { time: true }, s: {}, hz: {} },
    series: [
      {},
      { label: "clock offset (s)", scale: "s", stroke: "#f9a825", width: 2 },
      { label: "scan Hz", scale: "hz", stroke: "#64b5f6", width: 2 },
    ],
    axes: [
      { stroke: "#8a939b", grid: { stroke: "#2a333d" } },
      { scale: "s", stroke: "#f9a825", grid: { stroke: "#2a333d" } },
      { scale: "hz", side: 1, stroke: "#64b5f6", grid: { show: false } },
    ],
  };
  // eslint-disable-next-line no-undef
  const plot = new uPlot(opts, [[], [], []], plotEl);

  startPolling("history", 10000, (data) => {
    const samples = data.samples;
    if (samples.length === 0) return;
    plot.setData([
      samples.map((s) => s.ts),
      samples.map((s) => s.clock_offset),
      samples.map((s) => s.scan_hz),
    ]);
    const last = samples[samples.length - 1];
    const clock = last.clock_offset === null ? "?" : last.clock_offset.toFixed(2);
    metric.textContent =
      `${samples.length} samples · latest: clock ${clock} s, scan ${last.scan_hz.toFixed(1)} Hz`;
  });
}
