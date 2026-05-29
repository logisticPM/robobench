// Fetch + polling helpers for the diagnostic panels.

export async function fetchPanel(name) {
  const resp = await fetch(`/api/panels/${name}`);
  if (!resp.ok) {
    throw new Error(`panel ${name}: HTTP ${resp.status}`);
  }
  return resp.json();
}

// Poll a panel endpoint every intervalMs, calling onData(payload) each time.
// Fires a window "robobench:ok" event on the first successful fetch so the
// header can flip to "connected". Returns the interval id.
export function startPolling(name, intervalMs, onData) {
  let announced = false;
  async function tick() {
    try {
      const data = await fetchPanel(name);
      if (!announced) {
        announced = true;
        window.dispatchEvent(new CustomEvent("robobench:ok"));
      }
      onData(data);
    } catch (err) {
      console.error(err);
    }
  }
  tick();
  return setInterval(tick, intervalMs);
}
