"""Click-to-label semantic map annotation tool.

Usage:
    python annotate.py [--map MAP_IMAGE] [--yaml MAP_YAML] [--output OUTPUT_JSON]

Left-click on the map to mark a point -> then enter details in the terminal.
Press 'u' to undo the last annotation.
Press 'q' to quit and save.

Design note: mouse clicks are QUEUED and processed in the main loop,
so input() never blocks inside the OpenCV callback. This prevents the
"Not Responding" issue on Windows.
"""
import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import yaml
import jsonschema


def load_schema():
    schema_path = Path(__file__).parent.parent / "config" / "semantic_map_schema.json"
    if schema_path.exists():
        with open(schema_path) as f:
            return json.load(f)
    return None


def draw_all(base_img, semantic_map, origin, resolution):
    """Redraw the display image with all current annotations."""
    h, w = base_img.shape[:2]
    display = base_img.copy()
    for name, info in semantic_map.get("locations", {}).items():
        px = int((info["x"] - origin[0]) / resolution)
        py = int(h - (info["y"] - origin[1]) / resolution)
        if 0 <= px < w and 0 <= py < h:
            cv2.circle(display, (px, py), 6, (0, 0, 255), -1)
            # Black outline + white text for high contrast on any background
            cv2.putText(display, name, (px + 10, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv2.putText(display, name, (px + 10, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    return display


def save_map(semantic_map, output_path):
    with open(output_path, "w") as f:
        json.dump(semantic_map, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Semantic map annotation tool")
    parser.add_argument("--map", default="../maps/my_map.pgm", help="Map image path (.pgm or .png)")
    parser.add_argument("--yaml", default="../maps/my_map.yaml", help="Map YAML metadata")
    parser.add_argument("--output", default="semantic_map.json", help="Output semantic map JSON")
    args = parser.parse_args()

    # Resolve paths relative to this script
    script_dir = Path(__file__).parent
    map_path = (script_dir / args.map).resolve()
    yaml_path = (script_dir / args.yaml).resolve()
    output_path = (script_dir / args.output).resolve()

    # Load map metadata
    with open(yaml_path) as f:
        meta = yaml.safe_load(f)
    resolution = meta["resolution"]
    origin = meta["origin"]

    # Load map image
    map_img = cv2.imread(str(map_path))
    if map_img is None:
        map_img = cv2.imread(str(map_path), cv2.IMREAD_GRAYSCALE)
        if map_img is None:
            print(f"Error: cannot load map image: {map_path}")
            sys.exit(1)
        map_img = cv2.cvtColor(map_img, cv2.COLOR_GRAY2BGR)

    h, w = map_img.shape[:2]
    print(f"Map loaded: {w}x{h} pixels, resolution={resolution} m/px")
    print(f"Origin: {origin}")
    print(f"World range: X=[{origin[0]:.2f}, {origin[0] + w * resolution:.2f}], "
          f"Y=[{origin[1]:.2f}, {origin[1] + h * resolution:.2f}]")

    # Load existing semantic map or create new
    if output_path.exists():
        with open(output_path) as f:
            semantic_map = json.load(f)
        n = len(semantic_map.get("locations", {}))
        print(f"Loaded existing map with {n} locations")
    else:
        semantic_map = {
            "map_metadata": {
                "map_file": meta.get("image", "my_map.pgm"),
                "resolution": resolution,
                "origin": origin,
                "annotated_date": time.strftime("%Y-%m-%d"),
            },
            "locations": {},
        }

    schema = load_schema()

    # ── Click queue: callback only appends, main loop consumes ──
    click_queue = deque()

    def on_click(event, px, py, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            click_queue.append((px, py))

    # Initial display
    display = draw_all(map_img, semantic_map, origin, resolution)
    window_name = "Annotate Map (click=add, u=undo, q=quit)"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(window_name, display)
    cv2.setMouseCallback(window_name, on_click)

    print("\n--- Annotation Mode ---")
    print("  Left-click on map -> enter details in this terminal")
    print("  Press 'u' in the map window to undo last point")
    print("  Press 'q' in the map window to save & quit")
    print()

    running = True
    while running:
        key = cv2.waitKey(50) & 0xFF

        # ── Quit ──
        if key == ord("q"):
            break

        # ── Undo ──
        if key == ord("u"):
            locs = semantic_map.get("locations", {})
            if locs:
                last_key = list(locs.keys())[-1]
                del locs[last_key]
                save_map(semantic_map, output_path)
                display = draw_all(map_img, semantic_map, origin, resolution)
                cv2.imshow(window_name, display)
                print(f"  Undone: removed '{last_key}' ({len(locs)} remaining)")
            else:
                print("  Nothing to undo.")
            continue

        # ── Process queued clicks ──
        if click_queue:
            px, py = click_queue.popleft()
            wx = px * resolution + origin[0]
            wy = (h - py) * resolution + origin[1]

            # Show a green crosshair at the clicked point
            temp = display.copy()
            cv2.drawMarker(temp, (px, py), (0, 255, 0),
                           cv2.MARKER_CROSS, 15, 2)
            cv2.imshow(window_name, temp)
            cv2.waitKey(1)  # force refresh

            print(f"  Clicked pixel ({px}, {py}) -> world ({wx:.2f}, {wy:.2f})")
            print(f"  (Enter details below. Leave Label empty to cancel.)")

            label = input("    Label: ").strip()
            if not label:
                print("    Cancelled.")
                cv2.imshow(window_name, display)
                continue

            desc = input("    Description: ").strip()
            aliases_raw = input("    Aliases (comma-sep, or empty): ").strip()
            aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []
            area = input("    Area (e.g. front, student_area): ").strip()
            facing_str = input("    Facing deg (0=east, 90=north, default 0): ").strip()
            facing = float(facing_str) if facing_str else 0.0

            loc_data = {
                "x": round(wx, 3),
                "y": round(wy, 3),
                "facing_deg": facing,
                "description": desc,
                "aliases": aliases,
                "area": area,
            }

            semantic_map["locations"][label] = loc_data

            # Validate
            if schema:
                try:
                    jsonschema.validate(semantic_map, schema)
                except jsonschema.ValidationError as e:
                    print(f"    WARNING: validation failed: {e.message}")
                    del semantic_map["locations"][label]
                    cv2.imshow(window_name, display)
                    continue

            save_map(semantic_map, output_path)
            display = draw_all(map_img, semantic_map, origin, resolution)
            cv2.imshow(window_name, display)
            print(f"    Saved: '{label}' at ({wx:.2f}, {wy:.2f})"
                  f"  [{len(semantic_map['locations'])} total]\n")

    cv2.destroyAllWindows()
    n = len(semantic_map.get("locations", {}))
    print(f"\nDone. {n} locations saved to {output_path}")


if __name__ == "__main__":
    main()
