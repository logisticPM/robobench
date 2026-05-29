import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

// cytoscape is loaded as a global from /static/lib/cytoscape.min.js.

export function initTfPanel(root) {
  root.innerHTML = `
    <h3>TF tree <span class="pill" id="tf-pill">…</span></h3>
    <div id="tf-graph" class="graph"></div>
    <ul class="fixes" id="tf-fixes"></ul>`;

  const pill = root.querySelector("#tf-pill");
  const fixes = root.querySelector("#tf-fixes");

  // eslint-disable-next-line no-undef
  const cy = cytoscape({
    container: root.querySelector("#tf-graph"),
    style: [
      {
        selector: "node",
        style: {
          label: "data(id)",
          "background-color": "#1565c0",
          color: "#fff",
          "font-size": 10,
          "text-valign": "center",
          "text-halign": "center",
          width: 70,
          height: 26,
          shape: "round-rectangle",
        },
      },
      {
        selector: "edge",
        style: {
          width: 2,
          "line-color": "#90a4ae",
          "target-arrow-shape": "triangle",
          "target-arrow-color": "#90a4ae",
          "curve-style": "bezier",
        },
      },
      {
        selector: "edge.stale",
        style: { "line-color": "#c62828", "target-arrow-color": "#c62828", width: 3 },
      },
    ],
    layout: { name: "breadthfirst", directed: true },
  });

  startPolling("tf", 2000, (data) => {
    renderStatusPill(pill, data.status);
    const els = [];
    for (const n of data.nodes) {
      els.push({ data: { id: n } });
    }
    for (const e of data.edges) {
      els.push({
        data: { id: `${e.parent}->${e.child}`, source: e.parent, target: e.child },
        classes: e.stale ? "stale" : "",
      });
    }
    cy.elements().remove();
    cy.add(els);
    cy.layout({ name: "breadthfirst", directed: true }).run();
    renderFixes(fixes, data.fixes);
  });
}
