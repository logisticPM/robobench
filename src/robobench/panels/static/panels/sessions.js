import { statusColor } from "/static/core/status.js";

// Flight-recorder session browser: lists past recover/preflight/watch logs,
// click-through to the rendered post-mortem (same text as `robobench report`).

const REFRESH_MS = 10000;

function outcomeStatus(outcome) {
  if (outcome === "CONVERGED") return "OK";
  if (outcome === null || outcome === undefined) return "UNKNOWN";
  return "FAIL"; // STUCK / TIMED_OUT / NEEDS_HUMAN / ERROR
}

function rowLabel(s) {
  const started = (s.started || "").replace("T", " ").slice(0, 19);
  const dur = s.duration_s === null ? "" : ` · ${s.duration_s.toFixed(0)}s`;
  const actions = s.actions ? ` · ${s.actions} action${s.actions === 1 ? "" : "s"}` : "";
  return `${started} · ${s.kind}${actions}${dur}`;
}

export function initSessionsPanel(root) {
  root.innerHTML = `
    <h3>Sessions <span class="metric" id="sessions-count"></span></h3>
    <ul class="sessions-list" id="sessions-list"><li class="muted">loading…</li></ul>
    <pre class="session-report" id="session-report" hidden></pre>`;

  const list = root.querySelector("#sessions-list");
  const count = root.querySelector("#sessions-count");
  const report = root.querySelector("#session-report");
  let selected = null;

  async function showReport(name) {
    if (selected === name) {
      selected = null;
      report.hidden = true;
      return;
    }
    const resp = await fetch(`/api/sessions/${encodeURIComponent(name)}`);
    if (!resp.ok) return;
    const body = await resp.json();
    selected = name;
    report.textContent = body.report;
    report.hidden = false;
  }

  async function refresh() {
    let body;
    try {
      const resp = await fetch("/api/sessions");
      if (!resp.ok) throw new Error(`sessions: HTTP ${resp.status}`);
      body = await resp.json();
    } catch (err) {
      console.error(err);
      return;
    }
    const sessions = body.sessions;
    count.textContent = sessions.length ? `${sessions.length} logged` : "";
    if (sessions.length === 0) {
      list.innerHTML =
        `<li class="muted">no session logs yet — run robobench preflight / recover / watch</li>`;
      return;
    }
    list.innerHTML = "";
    for (const s of sessions) {
      const li = document.createElement("li");
      const pill = document.createElement("span");
      pill.className = "pill";
      pill.textContent = s.outcome || "—";
      pill.style.background = statusColor(outcomeStatus(s.outcome));
      const label = document.createElement("span");
      label.textContent = rowLabel(s);
      li.appendChild(pill);
      li.appendChild(label);
      li.title = s.name;
      li.addEventListener("click", () => showReport(s.name));
      list.appendChild(li);
    }
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
}
