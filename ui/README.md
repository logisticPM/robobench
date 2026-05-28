# UI Layer (v0 Baseline)

> **Status: v0 baseline, not yet wired up.** The dashboard and speech UI in this
> directory are imported from upstream as reference. Robobench's own code does
> NOT import or invoke them yet — they are scheduled to be wired into Phase C's
> diagnostic-panel work. Until then, they run independently as documented below.

This directory holds the dashboard and speech web UI imported from the
upstream reference repo. They are the v0 baseline; robobench's planned
diagnostic panels and bring-up wizard (Phase C) will be layered on top of —
or replace parts of — these components.

| Component | Port | Role |
|-----------|------|------|
| `dashboard/` | 8080 | Deploy + map + AMCL covariance + chat + nav state |
| `speech_web_ui/` | 8888 | Browser voice recognition → ROS topic |

See top-level [NOTICE](../NOTICE) for upstream provenance and license terms.
