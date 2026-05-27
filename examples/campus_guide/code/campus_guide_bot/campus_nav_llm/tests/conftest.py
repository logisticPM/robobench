"""Shared fixtures for all tests."""
import json
import os
import sys
from pathlib import Path

import pytest

# Add the package to the Python path
PKG_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PKG_ROOT))

SEMANTIC_MAP_PATH = PKG_ROOT / "semantic" / "semantic_map.json"
SCHEMA_PATH = PKG_ROOT / "config" / "semantic_map_schema.json"
MAP_YAML_PATH = PKG_ROOT / "maps" / "my_map.yaml"


@pytest.fixture
def semantic_map():
    """Load the semantic map JSON."""
    with open(SEMANTIC_MAP_PATH) as f:
        return json.load(f)


@pytest.fixture
def schema():
    """Load the JSON Schema for validation."""
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture
def sample_semantic_map():
    """Return a minimal semantic map for unit tests (no file dependency)."""
    return {
        "map_metadata": {
            "map_file": "test_map.pgm",
            "resolution": 0.05,
            "origin": [-7.47, -8.74, 1.0],
            "annotated_date": "2026-02-21",
        },
        "locations": {
            "whiteboard": {
                "x": 2.00,
                "y": 3.50,
                "facing_deg": 90,
                "description": "Main whiteboard at the front",
                "aliases": ["board", "front board"],
                "area": "front",
            },
            "desk_1": {
                "x": -1.00,
                "y": 0.00,
                "facing_deg": 0,
                "description": "First student desk, left side",
                "aliases": ["table 1", "left desk"],
                "area": "student_area",
            },
            "entrance": {
                "x": -2.00,
                "y": -3.00,
                "facing_deg": 180,
                "description": "Classroom entrance door",
                "aliases": ["door", "main door", "exit"],
                "area": "entrance",
            },
        },
    }
