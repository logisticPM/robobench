// src/robobench/panels/static/panels/connectivity.js
import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

async function postRecover(mode) {
  const resp = await fetch("/api/recover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  return { status: resp.status, body: await resp.json().catch(() => ({})) };
}

function renderJob(out, job) {
  const lines = (job.steps || []).map((s) => {
    if (s.event === "action") return `→ ${s.data.name} (for ${s.data.aspect})`;
    if (s.event === "probe") return "· probed";
    if (s.event === "outcome") return `outcome: ${s.data.outcome}`;
    return `· ${s.event}`;
  });
  if (job.status === "done") {
    lines.push(job.error ? `ERROR: ${job.error}` : `done: ${job.outcome}`);
  }
  out.textContent = lines.join("\n");
}

export function initConnectivityPanel(root) {
  root.innerHTML = `
    <h3>Connectivity (SSH) <span class="pill" id="conn-pill">…</span></h3>
    <ul class="ladder" id="conn-ladder"></ul>
    <ul class="fixes" id="conn-fixes"></ul>
    <div class="recover">
      <button id="conn-preview" disabled>Preview recovery</button>
      <button id="conn-apply" disabled>Apply</button>
      <div class="recover-out" id="conn-recover-out"></div>
    </div>`;

  const pill = root.querySelector("#conn-pill");
  const ladder = root.querySelector("#conn-ladder");
  const fixes = root.querySelector("#conn-fixes");
  const previewBtn = root.querySelector("#conn-preview");
  const applyBtn = root.querySelector("#conn-apply");
  const out = root.querySelector("#conn-recover-out");

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

  let statusTimer = null;
  function pollStatus() {
    fetch("/api/recover/status")
      .then((r) => r.json())
      .then((job) => {
        renderJob(out, job);
        if (job.status === "done") {
          clearInterval(statusTimer);
          statusTimer = null;
          previewBtn.disabled = false;
        }
      })
      .catch((e) => console.error(e));
  }

  // Availability gate: disable the buttons in demo / no-SSH.
  fetch("/api/recover/status")
    .then((r) => r.json())
    .then((job) => {
      if (job.available === false) {
        out.textContent = "Recover needs a real robot (SSH).";
      } else {
        previewBtn.disabled = false;
      }
    })
    .catch((e) => console.error(e));

  previewBtn.addEventListener("click", async () => {
    const { body } = await postRecover("preview");
    if (!body.would_try || body.would_try.length === 0) {
      out.textContent = body.failing_layer
        ? `No web-safe fix for: ${body.failing_layer}`
        : "Nothing to recover (healthy or no diagnosis yet).";
      applyBtn.disabled = true;
    } else {
      out.textContent = `Will try: ${body.would_try.join(" → ")}`;
      applyBtn.disabled = false;
    }
  });

  applyBtn.addEventListener("click", async () => {
    applyBtn.disabled = true;
    previewBtn.disabled = true;
    const { status } = await postRecover("apply");
    if (status === 409) out.textContent = "A recovery is already running.";
    if (statusTimer === null) statusTimer = setInterval(pollStatus, 1500);
    pollStatus();
  });
}
