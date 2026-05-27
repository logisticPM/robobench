"""Pure Python location resolver for semantic map lookups.

No ROS dependencies — can be tested in any Python environment.
"""
import json
import math
from pathlib import Path
from typing import Optional

import jsonschema


def load_semantic_map(map_path: str, schema_path: Optional[str] = None) -> dict:
    """Load and optionally validate a semantic map JSON file."""
    with open(map_path) as f:
        semantic_map = json.load(f)

    if schema_path:
        with open(schema_path) as f:
            schema = json.load(f)
        jsonschema.validate(semantic_map, schema)

    return semantic_map


class LocationResolver:
    """Resolves location names/aliases to map coordinates.

    Supports exact match, alias match, and partial substring match.
    """

    def __init__(self, semantic_map: dict):
        self._locations = semantic_map.get("locations", {})
        self._metadata = semantic_map.get("map_metadata", {})

    @property
    def location_names(self) -> list[str]:
        return list(self._locations.keys())

    @property
    def metadata(self) -> dict:
        return dict(self._metadata)

    def resolve(self, query: str) -> Optional[tuple[str, dict]]:
        """Look up a location by name, alias, or partial match.

        Returns (canonical_name, location_info) or None.
        """
        q = query.lower().strip()
        if not q:
            return None

        # 1. Exact name match
        for name, info in self._locations.items():
            if q == name.lower():
                return name, dict(info)

        # 2. Alias match
        for name, info in self._locations.items():
            aliases = [a.lower() for a in info.get("aliases", [])]
            if q in aliases:
                return name, dict(info)

        # 3. Partial substring match (last resort)
        for name, info in self._locations.items():
            if q in name.lower():
                return name, dict(info)
            for alias in info.get("aliases", []):
                if q in alias.lower():
                    return name, dict(info)

        return None

    def get_nearby(self, x: float, y: float, radius: float = 3.0) -> list[dict]:
        """Find locations within `radius` meters of (x, y)."""
        nearby = []
        for name, info in self._locations.items():
            d = math.hypot(info["x"] - x, info["y"] - y)
            if d <= radius:
                nearby.append({
                    "name": name,
                    "distance_m": round(d, 2),
                    "description": info["description"],
                })
        nearby.sort(key=lambda loc: loc["distance_m"])
        return nearby

    def get_location(self, name: str) -> Optional[dict]:
        """Get location info by exact canonical name."""
        info = self._locations.get(name)
        return dict(info) if info else None

    def get_all_locations_text(self) -> str:
        """Build a human-readable location summary for the LLM system prompt."""
        lines = []
        for name, info in self._locations.items():
            aliases = info.get("aliases", [])
            alias_str = f" ({', '.join(aliases)})" if aliases else ""
            lines.append(
                f"- {name}{alias_str}: {info['description']} "
                f"at ({info['x']:.2f}, {info['y']:.2f}), "
                f"area={info.get('area', 'unknown')}"
            )
        return "\n".join(lines)
