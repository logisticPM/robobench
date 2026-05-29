// Shared status-color + fix-rendering helpers.

const COLORS = {
  OK: "var(--ok)",
  WARN: "var(--warn)",
  FAIL: "var(--fail)",
  UNKNOWN: "var(--unknown)",
};

export function statusColor(status) {
  return COLORS[status] || COLORS.UNKNOWN;
}

// Render a status string into a .pill element (text + background color).
export function renderStatusPill(el, status) {
  el.textContent = status;
  el.style.background = statusColor(status);
}

// Render an array of {cause, fix, link} into a <ul class="fixes">.
export function renderFixes(el, fixes) {
  el.innerHTML = "";
  for (const f of fixes || []) {
    const li = document.createElement("li");
    const link = f.link
      ? ` <a href="${f.link}" target="_blank" rel="noopener">docs</a>`
      : "";
    li.innerHTML = `<strong>${f.cause}</strong><br>${f.fix}${link}`;
    el.appendChild(li);
  }
}
