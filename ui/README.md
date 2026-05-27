# UI Layer (v0 Baseline)

This directory holds the dashboard and speech web UI imported from the
upstream reference repo. They are the v0 baseline; robobench's planned
diagnostic panels and bring-up wizard (Phase C) will be layered on top of —
or replace parts of — these components.

| Component | Port | Role |
|-----------|------|------|
| `dashboard/` | 8080 | Deploy + map + AMCL covariance + chat + nav state |
| `speech_web_ui/` | 8888 | Browser voice recognition → ROS topic |

See top-level [NOTICE](../NOTICE) for upstream provenance and license terms.
