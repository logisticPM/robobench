# Campus Guide — Reference Implementation

This directory contains the original `CS5335TurtleBot` codebase, imported as a
runnable end-to-end reference for the robobench platform. It demonstrates a
complete embodied-AI pipeline (speech/text → LLM tool-call → Nav2 →
TurtleBot4) and is the system the robobench diagnostic layer is initially
benchmarked against.

## Provenance

- Upstream: https://github.com/En-PingSu/CS5335TurtleBot
- License of imported code: see top-level [NOTICE](../../NOTICE). The robobench
  Apache-2.0 license applies only to additions made within this fork; original
  files retain their upstream license terms.

## How to run

The original startup guide remains authoritative for running this example:
see `code/STARTUP_GUIDE.md` (if present) and `code/scripts/deploy.sh`.

## Why it lives here

Robobench's diagnostic layer is designed to spot bring-up problems
*before* you reach this kind of full integration. This demo is the
fully-integrated end-state — useful as a smoke test for "did the whole stack
come up correctly?".
