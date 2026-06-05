#!/usr/bin/env python
"""Test XPart with auto-detected bf16 and CPU offload on 16 GB GPU."""

import gc, os, sys, time, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_xpart")

import torch
import trimesh
import numpy as np
import pickle

MESH_PATH = "/tmp/test_parts_output/01_shape.glb"
OUT_DIR = "/tmp/test_parts_output"
SEED = 42

# Check if we have AABB from a previous segmentation run
aabb_pkl = os.path.join(OUT_DIR, "aabb.pkl")
if not os.path.exists(aabb_pkl):
    logger.info("No cached AABB found, running P3-SAM segmentation first...")

    mesh = trimesh.load(MESH_PATH, force='mesh')
    if isinstance(mesh, trimesh.Scene):
        mesh = list(mesh.geometry.values())[0]

    gc.collect(); torch.cuda.empty_cache()
    free_mb = torch.cuda.mem_get_info()[0] / 1e6
    total_mb = torch.cuda.mem_get_info()[1] / 1e6
    logger.info("GPU before P3-SAM: %.0f / %.0f MB free", free_mb, total_mb)

    from hy3dgen.partseg import PartSegManager
    mgr = PartSegManager()
    aabb, face_ids = mgr.segment(mesh, seed=SEED)

    n_parts = len(aabb) if aabb is not None else 0
    logger.info("Segmented: %d parts", n_parts)

    # Save AABB for reuse
    mgr.unload_automask()

    # Save mesh path for XPart
    with open(aabb_pkl, 'wb') as f:
        pickle.dump({'aabb': aabb, 'mesh_path': MESH_PATH}, f)
    logger.info("AABB saved to %s", aabb_pkl)
else:
    logger.info("Loading cached AABB from %s", aabb_pkl)
    with open(aabb_pkl, 'rb') as f:
        saved = pickle.load(f)
    aabb = saved['aabb']
    n_parts = len(aabb) if aabb is not None else 0
    logger.info("Cached AABB: %d parts", n_parts)

gc.collect(); torch.cuda.empty_cache()
free_mb = torch.cuda.mem_get_info()[0] / 1e6
total_mb = torch.cuda.mem_get_info()[1] / 1e6
logger.info("GPU before XPart: %.0f / %.0f MB free", free_mb, total_mb)

# ==================================================================
# XPart with auto-detected bf16 + CPU offload
# ==================================================================
logger.info("=== XPart Generation (auto bf16 + offload for 16 GB) ===")
from hy3dgen.partseg import PartSegManager

mgr = PartSegManager()

t0 = time.time()
try:
    parts_mesh, bbox_mesh, exploded = mgr.generate_parts(MESH_PATH, aabb, seed=SEED)
    elapsed = time.time() - t0
    logger.info("✅ Parts generated in %.0fs (%.1f min)", elapsed, elapsed/60)

    parts_path = os.path.join(OUT_DIR, "03_parts.glb")
    parts_mesh.export(parts_path)
    logger.info("Saved: %s", parts_path)

    if exploded is not None:
        exp_path = os.path.join(OUT_DIR, "03_exploded.glb")
        exploded.export(exp_path)
        logger.info("Saved: %s", exp_path)

except Exception as e:
    elapsed = time.time() - t0
    logger.error("❌ XPart failed after %.0fs: %s", elapsed, e)
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    mgr.unload_pipeline()
    gc.collect(); torch.cuda.empty_cache()

free_mb = torch.cuda.mem_get_info()[0] / 1e6
logger.info("GPU final: %.0f / %.0f MB free", free_mb, total_mb)

print("\n" + "=" * 50)
print("  XPart TEST COMPLETE")
print("=" * 50)
print(f"  Parts found: {n_parts}")
print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
print(f"  Output: {OUT_DIR}")
for f in sorted(os.listdir(OUT_DIR)):
    size_kb = os.path.getsize(os.path.join(OUT_DIR, f)) / 1024
    print(f"    {f} ({size_kb:.0f} KB)")
print("=" * 50)
