"""Tests for semantic map schema validation and data integrity."""
import json
from pathlib import Path

import jsonschema
import pytest


class TestSchemaValidation:
    """Validate that semantic_map.json conforms to the JSON Schema."""

    def test_semantic_map_valid(self, semantic_map, schema):
        """The actual semantic_map.json must pass schema validation."""
        jsonschema.validate(semantic_map, schema)

    def test_schema_rejects_missing_locations(self, schema):
        """Schema must reject a map without the 'locations' key."""
        invalid = {
            "map_metadata": {
                "map_file": "x.pgm",
                "resolution": 0.05,
                "origin": [0, 0, 0],
                "annotated_date": "2026-01-01",
            }
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)

    def test_schema_rejects_missing_metadata(self, schema):
        """Schema must reject a map without 'map_metadata'."""
        invalid = {"locations": {}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)

    def test_schema_rejects_location_without_x(self, schema):
        """Each location must have x, y, description."""
        invalid = {
            "map_metadata": {
                "map_file": "x.pgm",
                "resolution": 0.05,
                "origin": [0, 0, 0],
                "annotated_date": "2026-01-01",
            },
            "locations": {
                "bad_loc": {
                    "y": 1.0,
                    "description": "missing x",
                }
            },
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)

    def test_schema_rejects_bad_origin(self, schema):
        """Origin must be exactly 3 numbers."""
        invalid = {
            "map_metadata": {
                "map_file": "x.pgm",
                "resolution": 0.05,
                "origin": [0, 0],  # only 2 elements
                "annotated_date": "2026-01-01",
            },
            "locations": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)


class TestMapDataIntegrity:
    """Check the actual semantic map data makes sense."""

    def test_has_at_least_5_locations(self, semantic_map):
        """Phase 1 requires at least 5 annotated locations."""
        assert len(semantic_map["locations"]) >= 5

    def test_all_locations_have_coordinates(self, semantic_map):
        for name, info in semantic_map["locations"].items():
            assert "x" in info, f"{name} missing 'x'"
            assert "y" in info, f"{name} missing 'y'"
            assert isinstance(info["x"], (int, float)), f"{name}.x not a number"
            assert isinstance(info["y"], (int, float)), f"{name}.y not a number"

    def test_all_locations_have_description(self, semantic_map):
        for name, info in semantic_map["locations"].items():
            assert "description" in info, f"{name} missing 'description'"
            assert len(info["description"]) > 0, f"{name} has empty description"

    def test_coordinates_within_map_bounds(self, semantic_map):
        """Coordinates should be within the map's world bounds."""
        meta = semantic_map["map_metadata"]
        res = meta["resolution"]
        origin = meta["origin"]
        # Approximate bounds (generous)
        for name, info in semantic_map["locations"].items():
            assert -10 <= info["x"] <= 15, f"{name}.x={info['x']} out of bounds"
            assert -10 <= info["y"] <= 15, f"{name}.y={info['y']} out of bounds"

    def test_no_duplicate_coordinates(self, semantic_map):
        """No two locations should be at the exact same position."""
        coords = []
        for name, info in semantic_map["locations"].items():
            coord = (info["x"], info["y"])
            assert coord not in coords, f"{name} duplicates position {coord}"
            coords.append(coord)

    def test_aliases_are_lists(self, semantic_map):
        for name, info in semantic_map["locations"].items():
            if "aliases" in info:
                assert isinstance(info["aliases"], list), f"{name}.aliases not a list"

    def test_metadata_resolution(self, semantic_map):
        assert semantic_map["map_metadata"]["resolution"] == 0.05

    def test_metadata_origin(self, semantic_map):
        origin = semantic_map["map_metadata"]["origin"]
        assert len(origin) == 3
        assert origin[0] == -8.1
        assert origin[1] == -8.64
