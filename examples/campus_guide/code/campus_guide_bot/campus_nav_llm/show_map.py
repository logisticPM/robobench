"""Preview the map with existing annotations marked."""
import json
import cv2
import yaml
import numpy as np
from pathlib import Path

script_dir = Path(__file__).parent

# Load map
map_path = script_dir / "maps" / "my_map.pgm"
yaml_path = script_dir / "maps" / "my_map.yaml"
smap_path = script_dir / "semantic" / "semantic_map.json"

with open(yaml_path) as f:
    meta = yaml.safe_load(f)
res = meta["resolution"]
origin = meta["origin"]

img = cv2.imread(str(map_path), cv2.IMREAD_GRAYSCALE)
h, w = img.shape
display = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

# Draw existing annotations
with open(smap_path) as f:
    smap = json.load(f)

print(f"Map: {w}x{h} px, resolution={res} m/px")
print(f"Origin: {origin}")
print(f"\nExisting {len(smap['locations'])} locations:")
for name, info in smap["locations"].items():
    px = int((info["x"] - origin[0]) / res)
    py = int(h - (info["y"] - origin[1]) / res)
    print(f"  {name:20s} → world ({info['x']:7.2f}, {info['y']:7.2f}) → pixel ({px:4d}, {py:4d})")

    if 0 <= px < w and 0 <= py < h:
        cv2.circle(display, (px, py), 6, (0, 0, 255), -1)
        cv2.putText(display, name, (px + 10, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

# Save preview
preview_path = script_dir / "maps" / "map_preview.png"
cv2.imwrite(str(preview_path), display)
print(f"\nPreview saved: {preview_path}")
