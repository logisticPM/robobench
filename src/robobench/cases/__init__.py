"""Robobench case library: the data-backed failure catalog.

A *case* is a structured, robot-agnostic record of one failure and its fix.
Cases ship as YAML files under ``robobench/data/cases/`` and load into ``Case``
objects. Pure file reads — no network, SSH, or rclpy.
"""

from __future__ import annotations
