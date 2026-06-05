#!/usr/bin/env python
"""Quick test: shape gen → part segmentation (P3-SAM) → part generation (XPart).

Usage:
    conda run -n hunyuan3d python test_parts.py
"""

import gc, os, sys, time, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_parts")

import torch
import trimesh
import numpy as np

TEST_IMAGE = "assets/demo.png"
OUT_DIR = "/tmp/test_parts_output"
SEED = 42

def free_gpu():
    gc.collect()
    torch.cuda.empty_cache()
    gc.collect()
    free_mb = torch.cuda.mem_get_info()[0] / 1e6
    total_mb = torch.cuda.mem_get_info()[1] / 1e6
    logger.info("GPU: %.0f / %.0f MB free", free_mb, total_mb)

os.makedirs(OUT_DIR, exist_ok=True)
free_gpu()

# ==================================================================
# Step 1: Shape Generation
# ==================================================================
logger.info("=== Step 1: Shape Generation ===")
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline, FloaterRemover, DegenerateFaceRemover, FaceReducer

t0 = time.time()
pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    'tencent/Hunyuan3D-2mini',
    subfolder='hunyuan3d-dit-v2-mini-turbo',
)
mesh = pipeline(image=TEST_IMAGE, num_inference_steps=5)[0]
logger.info("Shape: %d verts, %d faces (%.0fs)", len(mesh.vertices), len(mesh.faces), time.time() - t0)

# Post-process
mesh = FloaterRemover()(mesh)
mesh = DegenerateFaceRemover()(mesh)
mesh = FaceReducer()(mesh, max_facenum=40000)
logger.info("After cleanup: %d verts, %d faces", len(mesh.vertices), len(mesh.faces))

# Save
shape_path = os.path.join(OUT_DIR, "01_shape.glb")
mesh.export(shape_path)
logger.info("Saved: %s", shape_path)

# CRITICAL: move shape pipeline to CPU to free VRAM for P3-SAM
pipeline.to('cpu')
del pipeline
free_gpu()

# ==================================================================
# Step 2: Part Segmentation (P3-SAM)
# ==================================================================
logger.info("=== Step 2: Part Segmentation (P3-SAM) ===")
from hy3dgen.partseg import PartSegManager

t0 = time.time()
part_mgr = PartSegManager()
aabb, face_ids = part_mgr.segment(mesh, seed=SEED)
elapsed = time.time() - t0

unique_ids = np.unique(face_ids)
n_parts = len(unique_ids) - (1 if -1 in unique_ids else 0)
logger.info("Segmented: %d parts (%.0fs)", n_parts, elapsed)

# Color and save segmented mesh
color_map = {}
for i in unique_ids:
    if i == -1: continue
    color_map[i] = np.random.RandomState(int(i)).randint(0, 255, 3)
face_colors = np.array([color_map.get(i, [0, 0, 0]) for i in face_ids]).astype(np.uint8)
seg_mesh = mesh.copy()
seg_mesh.visual.face_colors = face_colors
seg_path = os.path.join(OUT_DIR, "02_segmented.glb")
seg_mesh.export(seg_path)
logger.info("Saved: %s", seg_path)
free_gpu()

# ==================================================================
# Step 3: Part Generation (XPart)
# ==================================================================
logger.info("=== Step 3: Part Generation (XPart) ===")

t0 = time.time()
parts_mesh, bbox_mesh, exploded = part_mgr.generate_parts(shape_path, aabb, seed=SEED)
elapsed = time.time() - t0
logger.info("Parts generated (%.0fs)", elapsed)

# Save
parts_path = os.path.join(OUT_DIR, "03_parts.glb")
parts_mesh.export(parts_path)
logger.info("Saved: %s", parts_path)

if exploded is not None:
    exp_path = os.path.join(OUT_DIR, "03_exploded.glb")
    exploded.export(exp_path)
    logger.info("Saved: %s", exp_path)

free_gpu()

# ==================================================================
# Summary
# ==================================================================
print("\n" + "=" * 50)
print("  TEST COMPLETE")
print("=" * 50)
print(f"  Parts found: {n_parts}")
print(f"  Output: {OUT_DIR}")
for f in sorted(os.listdir(OUT_DIR)):
    size_kb = os.path.getsize(os.path.join(OUT_DIR, f)) / 1024
    print(f"    {f} ({size_kb:.0f} KB)")
print("=" * 50)
