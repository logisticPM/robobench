"""Tests for LocationResolver — name/alias resolution, nearby search."""
import pytest

from campus_nav_llm.location_resolver import LocationResolver, load_semantic_map


class TestExactNameResolution:
    """Test resolving locations by their canonical name."""

    def test_exact_name(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("whiteboard")
        assert result is not None
        name, info = result
        assert name == "whiteboard"
        assert info["x"] == 2.00
        assert info["y"] == 3.50

    def test_exact_name_case_insensitive(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("Whiteboard")
        assert result is not None
        assert result[0] == "whiteboard"

    def test_exact_name_with_spaces(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("  desk_1  ")
        assert result is not None
        assert result[0] == "desk_1"


class TestAliasResolution:
    """Test resolving locations by alias."""

    def test_alias_match(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("board")
        assert result is not None
        assert result[0] == "whiteboard"

    def test_alias_case_insensitive(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("Front Board")
        assert result is not None
        assert result[0] == "whiteboard"

    def test_alias_door(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("door")
        assert result is not None
        assert result[0] == "entrance"

    def test_alias_exit(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("exit")
        assert result is not None
        assert result[0] == "entrance"

    def test_alias_table_1(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("table 1")
        assert result is not None
        assert result[0] == "desk_1"


class TestPartialMatch:
    """Test partial substring matching (fallback)."""

    def test_partial_name(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("desk")
        assert result is not None
        assert result[0] == "desk_1"  # first match

    def test_partial_alias(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("left")
        assert result is not None
        assert result[0] == "desk_1"


class TestUnknownLocation:
    """Test behavior when location cannot be found."""

    def test_unknown_returns_none(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        result = resolver.resolve("cafeteria")
        assert result is None

    def test_empty_query_returns_none(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        assert resolver.resolve("") is None
        assert resolver.resolve("   ") is None


class TestNearbySearch:
    """Test get_nearby() spatial queries."""

    def test_nearby_from_whiteboard(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        # Standing at whiteboard (2.0, 3.5)
        nearby = resolver.get_nearby(2.0, 3.5, radius=5.0)
        names = [loc["name"] for loc in nearby]
        assert "whiteboard" in names  # itself, distance ~0

    def test_nearby_sorted_by_distance(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        nearby = resolver.get_nearby(0.0, 0.0, radius=10.0)
        distances = [loc["distance_m"] for loc in nearby]
        assert distances == sorted(distances)

    def test_nearby_respects_radius(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        # Very small radius from entrance (-2, -3)
        nearby = resolver.get_nearby(-2.0, -3.0, radius=0.5)
        names = [loc["name"] for loc in nearby]
        assert "entrance" in names
        assert "whiteboard" not in names

    def test_nearby_empty_when_far(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        nearby = resolver.get_nearby(100.0, 100.0, radius=1.0)
        assert len(nearby) == 0


class TestLocationNames:
    """Test location_names property."""

    def test_location_names_list(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        names = resolver.location_names
        assert "whiteboard" in names
        assert "desk_1" in names
        assert "entrance" in names


class TestGetAllLocationsText:
    """Test the text summary for LLM system prompt."""

    def test_text_contains_all_locations(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        text = resolver.get_all_locations_text()
        assert "whiteboard" in text
        assert "desk_1" in text
        assert "entrance" in text

    def test_text_contains_aliases(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        text = resolver.get_all_locations_text()
        assert "board" in text
        assert "door" in text

    def test_text_contains_coordinates(self, sample_semantic_map):
        resolver = LocationResolver(sample_semantic_map)
        text = resolver.get_all_locations_text()
        assert "2.00" in text  # whiteboard x
        assert "3.50" in text  # whiteboard y


class TestLoadSemanticMap:
    """Test loading and validating from real files."""

    def test_load_real_map(self):
        from tests.conftest import SEMANTIC_MAP_PATH
        smap = load_semantic_map(str(SEMANTIC_MAP_PATH))
        assert "locations" in smap
        assert "map_metadata" in smap

    def test_load_and_validate(self):
        from tests.conftest import SEMANTIC_MAP_PATH, SCHEMA_PATH
        smap = load_semantic_map(str(SEMANTIC_MAP_PATH), str(SCHEMA_PATH))
        assert len(smap["locations"]) >= 5
