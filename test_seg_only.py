#!/usr/bin/env python
"""Quick test: P3-SAM segmentation only, using an existing mesh."""

import gc, os, sys, time, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_seg")

import torch
import trimesh
import numpy as np

MESH_PATH = "/tmp/test_parts_output/01_shape.glb"
OUT_DIR = "/tmp/test_parts_output"
SEED = 42

# Load mesh
mesh = trimesh.load(MESH_PATH, force='mesh')
if isinstance(mesh, trimesh.Scene):
    # Take the first geometry
    geom = list(mesh.geometry.values())[0]
    logger.info("Loaded scene with %d geometries, using first one", len(mesh.geometry))
    mesh = geom
logger.info("Mesh: %d verts, %d faces", len(mesh.vertices), len(mesh.faces))

# Free GPU
gc.collect(); torch.cuda.empty_cache(); gc.collect()
free_mb = torch.cuda.mem_get_info()[0] / 1e6
total_mb = torch.cuda.mem_get_info()[1] / 1e6
logger.info("GPU before P3-SAM: %.0f / %.0f MB free", free_mb, total_mb)

# ==================================================================
# Part Segmentation (P3-SAM)
# ==================================================================
logger.info("=== Part Segmentation (P3-SAM) ===")
from hy3dgen.partseg import PartSegManager

t0 = time.time()
part_mgr = PartSegManager()
aabb, face_ids = part_mgr.segment(mesh, seed=SEED)
elapsed = time.time() - t0

unique_ids = np.unique(face_ids)
n_parts = len(unique_ids) - (1 if -1 in unique_ids else 0)
logger.info("Segmented: %d parts in %.0fs (%.1f min)", n_parts, elapsed, elapsed/60)

# Color segmented mesh
color_map = {}
for i in unique_ids:
    if i == -1: continue
    color_map[i] = np.random.RandomState(int(i)).randint(0, 255, 3)
face_colors = np.array([color_map.get(i, [0, 0, 0]) for i in face_ids]).astype(np.uint8)
seg_mesh = mesh.copy()
seg_mesh.visual.face_colors = face_colors
seg_path = os.path.join(OUT_DIR, "02_segmented.glb")
seg_mesh.export(seg_path)
logger.info("Saved segmented: %s", seg_path)

# Cleanup P3-SAM
part_mgr.unload_automask()
gc.collect(); torch.cuda.empty_cache()
free_mb = torch.cuda.mem_get_info()[0] / 1e6
logger.info("GPU after P3-SAM unload: %.0f / %.0f MB free", free_mb, total_mb)

# ==================================================================
# Part Generation (XPart)
# ==================================================================
logger.info("=== Part Generation (XPart) ===")

t0 = time.time()
parts_mesh, bbox_mesh, exploded = part_mgr.generate_parts(MESH_PATH, aabb, seed=SEED)
elapsed = time.time() - t0
logger.info("Parts generated in %.0fs (%.1f min)", elapsed, elapsed/60)

parts_path = os.path.join(OUT_DIR, "03_parts.glb")
parts_mesh.export(parts_path)
logger.info("Saved: %s", parts_path)

if exploded is not None:
    exp_path = os.path.join(OUT_DIR, "03_exploded.glb")
    exploded.export(exp_path)
    logger.info("Saved: %s", exp_path)

# Cleanup
part_mgr.unload_pipeline()
gc.collect(); torch.cuda.empty_cache()
free_mb = torch.cuda.mem_get_info()[0] / 1e6
logger.info("GPU final: %.0f / %.0f MB free", free_mb, total_mb)

# ==================================================================
# Summary
# ==================================================================
print("\n" + "=" * 50)
print("  SEGMENTATION TEST COMPLETE")
print("=" * 50)
print(f"  Parts found: {n_parts}")
print(f"  Output: {OUT_DIR}")
for f in sorted(os.listdir(OUT_DIR)):
    size_kb = os.path.getsize(os.path.join(OUT_DIR, f)) / 1024
    print(f"    {f} ({size_kb:.0f} KB)")
print("=" * 50)
