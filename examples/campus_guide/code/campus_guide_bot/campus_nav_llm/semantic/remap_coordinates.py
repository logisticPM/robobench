"""Remap semantic map coordinates from old map to new map.

Uses ORB feature matching between the old and new PGM images
to compute a rigid transformation, then applies it to convert
old semantic coordinates to the new map's coordinate frame.

Generates a preview image showing the remapped locations.
"""
import json
import cv2
import numpy as np
from pathlib import Path

# ── Paths ──
script_dir = Path(__file__).parent
old_pgm = Path("/home/khouryloaner/robotic_llm/campus_guide_bot/campus_nav_llm/maps/my_map.pgm")
new_pgm = script_dir.parent / "maps" / "my_map.pgm"
semantic_path = script_dir / "semantic_map.json"

# ── Map metadata ──
old_origin = [-7.47, -8.74]
old_yaw = 1.0  # radians (but annotate.py ignored this)
old_res = 0.05

new_origin = [-8.1, -8.64]
new_yaw = 0.0
new_res = 0.05

# ── Load images ──
old_img = cv2.imread(str(old_pgm), cv2.IMREAD_GRAYSCALE)
new_img = cv2.imread(str(new_pgm), cv2.IMREAD_GRAYSCALE)
old_h, old_w = old_img.shape
new_h, new_w = new_img.shape
print(f"Old map: {old_w}x{old_h} px")
print(f"New map: {new_w}x{new_h} px")

# ── Feature matching (ORB + BFMatcher) ──
orb = cv2.ORB_create(nfeatures=2000)
kp1, des1 = orb.detectAndCompute(old_img, None)
kp2, des2 = orb.detectAndCompute(new_img, None)
print(f"Features: old={len(kp1)}, new={len(kp2)}")

bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
matches = bf.match(des1, des2)
matches = sorted(matches, key=lambda m: m.distance)

# Use top matches
n_matches = min(50, len(matches))
good = matches[:n_matches]
print(f"Using top {n_matches} matches (best distance: {good[0].distance})")

src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

# Estimate affine transformation (rigid: rotation + translation)
M, inliers = cv2.estimateAffinePartial2D(src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=5.0)
n_inliers = int(inliers.sum()) if inliers is not None else 0
print(f"Affine transform inliers: {n_inliers}/{n_matches}")
print(f"Transform matrix:\n{M}")

# Extract rotation and translation from the affine matrix
cos_a = M[0, 0]
sin_a = M[1, 0]
angle_deg = np.degrees(np.arctan2(sin_a, cos_a))
scale = np.sqrt(cos_a**2 + sin_a**2)
tx, ty = M[0, 2], M[1, 2]
print(f"Rotation: {angle_deg:.2f} deg, Scale: {scale:.4f}, Translation: ({tx:.1f}, {ty:.1f}) px")

# ── Load existing semantic map ──
with open(semantic_path) as f:
    smap = json.load(f)

# ── Convert and remap each location ──
print(f"\n{'Location':<15} {'Old World':>20} {'Old Pixel':>15} {'New Pixel':>15} {'New World':>20}")
print("-" * 90)

new_locations = {}
for name, info in smap["locations"].items():
    old_wx, old_wy = info["x"], info["y"]

    # Old world -> old pixel (using annotate.py formula, which ignores yaw)
    old_px = (old_wx - old_origin[0]) / old_res
    old_py = old_h - (old_wy - old_origin[1]) / old_res

    # Apply affine transform to get new pixel coords
    old_pt = np.array([[old_px, old_py]], dtype=np.float32).reshape(1, 1, 2)
    new_pt = cv2.transform(old_pt, M)
    new_px, new_py = new_pt[0, 0]

    # New pixel -> new world (yaw=0, so simple formula)
    new_wx = new_px * new_res + new_origin[0]
    new_wy = (new_h - new_py) * new_res + new_origin[1]

    new_locations[name] = {
        "x": round(float(new_wx), 2),
        "y": round(float(new_wy), 2),
        "facing_deg": info["facing_deg"],
        "description": info["description"],
        "aliases": info["aliases"],
        "area": info["area"],
    }

    print(f"{name:<15} ({old_wx:7.2f}, {old_wy:7.2f}) "
          f"({old_px:6.1f}, {old_py:6.1f}) "
          f"({new_px:6.1f}, {new_py:6.1f}) "
          f"({new_wx:7.2f}, {new_wy:7.2f})")

# ── Build updated semantic map ──
new_smap = {
    "map_metadata": {
        "map_file": "my_map.pgm",
        "resolution": new_res,
        "origin": [new_origin[0], new_origin[1], new_yaw],
        "annotated_date": "2026-03-03",
    },
    "locations": new_locations,
}

# ── Save ──
output_path = script_dir / "semantic_map_remapped.json"
with open(output_path, "w") as f:
    json.dump(new_smap, f, indent=2)
print(f"\nRemapped semantic map saved to: {output_path}")

# ── Generate preview image ──
preview = cv2.cvtColor(new_img, cv2.COLOR_GRAY2BGR)
for name, info in new_locations.items():
    px = int((info["x"] - new_origin[0]) / new_res)
    py = int(new_h - (info["y"] - new_origin[1]) / new_res)
    if 0 <= px < new_w and 0 <= py < new_h:
        cv2.circle(preview, (px, py), 6, (0, 0, 255), -1)
        cv2.putText(preview, name, (px + 10, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
        cv2.putText(preview, name, (px + 10, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

preview_path = script_dir.parent / "maps" / "map_preview_remapped.png"
cv2.imwrite(str(preview_path), preview)
print(f"Preview image saved to: {preview_path}")
