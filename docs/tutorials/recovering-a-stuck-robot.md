# Recovering a stuck robot

When bring-up hangs — no topics, dead odom, Discovery Server zombie — robobench
can drive the robot back to health automatically, trying the cheapest fix
first and only escalating if needed.

## See what's wrong (no changes)

```bash
robobench preflight --robot turtlebot4 --config ./config.yaml
```
```json
{
  "healthy": false,
  "failing_aspect": "odom_publishing",
  "would_try": ["restart_create3_app"],
  "state": { "rpi_reachable": true, "discovery_server_ok": true, "...": "..." }
}
```

`preflight` only reads — it never touches the robot.

## Preview the recovery plan

```bash
robobench recover --robot turtlebot4 --config ./config.yaml --dry-run
```
Prints the actions the engine *would* apply from the current state, without
applying any.

## Run the recovery

```bash
robobench recover --robot turtlebot4 --config ./config.yaml --deadline 180
```

The engine loops: read state → fix the most-upstream failing thing with the
cheapest action → re-read → repeat, until healthy or the deadline. It never
repeats an action and reports every step:

```
recovery outcome: CONVERGED
  applied: restart_local_daemon
  applied: restart_create3_app
```

## The nuclear option is opt-in

A full Create3 reboot (~3 min, re-randomizes DDS GUIDs) is **off by default**.
If cheaper fixes can't clear a GUID mismatch, recovery stops as `STUCK` and
tells you. To permit the reboot:

```bash
robobench recover --robot turtlebot4 --config ./config.yaml --allow-reboot --deadline 360
```

## Why this is different from a recovery *script*

robobench's engine is a convergence loop, not a fixed sequence:
- It diagnoses the **root** (most-upstream failing aspect), not the symptom.
- It applies the **cheapest sufficient** fix and re-checks — no blind 6-step chain.
- It treats "odom" as healthy only after **two consecutive** good samples.
- It never reboots hardware without `--allow-reboot`.

## Outcomes

| Outcome | Meaning |
|---------|---------|
| `CONVERGED` | Robot is healthy. |
| `STUCK` | Ran out of allowed fixes (e.g. needs `--allow-reboot`). |
| `TIMED_OUT` | Hit `--deadline` still unhealthy. |
| `NEEDS_HUMAN` | Robot unreachable — power/network, can't fix remotely. |
