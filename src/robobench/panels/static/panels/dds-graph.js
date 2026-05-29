import { startPolling } from "/static/core/api.js";
import { renderFixes, renderStatusPill } from "/static/core/status.js";

// cytoscape is loaded as a global from /static/lib/cytoscape.min.js.

export function initDdsPanel(root) {
  root.innerHTML = `
    <h3>DDS nodes <span class="pill" id="dds-pill">…</span></h3>
    <div id="dds-graph" class="graph"></div>
    <ul class="fixes" id="dds-fixes"></ul>`;

  const pill = root.querySelector("#dds-pill");
  const fixes = root.querySelector("#dds-fixes");

  // eslint-disable-next-line no-undef
  const cy = cytoscape({
    container: root.querySelector("#dds-graph"),
    style: [
      {
        selector: "node",
        style: {
          label: "data(id)",
          color: "#fff",
          "font-size": 9,
          "text-valign": "center",
          "text-halign": "center",
          width: 90,
          height: 24,
          shape: "round-rectangle",
          "background-color": "#2e7d32",
        },
      },
      {
        selector: "node.missing",
        style: { "background-color": "#c62828", "border-width": 2, "border-color": "#ff8a80" },
      },
    ],
    layout: { name: "grid" },
  });

  // Only rebuild + re-layout when the node set / statuses change; re-running
  // the layout on every poll churns the renderer and can blank it.
  let lastSig = null;

  startPolling("dds", 2000, (data) => {
    renderStatusPill(pill, data.status);
    renderFixes(fixes, data.fixes);

    const sig = JSON.stringify(data.nodes.map((n) => `${n.name}:${n.status}`));
    if (sig === lastSig) {
      return;
    }
    lastSig = sig;

    const els = data.nodes.map((n) => ({
      data: { id: n.name },
      classes: n.status === "missing" ? "missing" : "",
    }));
    cy.elements().remove();
    cy.add(els);
    cy.layout({ name: "grid", animate: false, padding: 20 }).run();
    cy.fit(cy.elements(), 20); // explicit fit — layout fit:true is unreliable here
  });
}
