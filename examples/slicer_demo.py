#!/usr/bin/env python
"""End-to-end demo: image -> 3D model -> segmented parts -> printable STLs.

This script requires:
- Hunyuan3D-2 shape + texture models to be downloaded
- P3-SAM + XPart models (auto-download via PartSegManager)
- hy3dgen.slicer module (Phase 1 MVP)

Usage:
    python examples/slicer_demo.py --image car.jpg --output ./car_parts/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("slicer_demo")


def main():
    parser = argparse.ArgumentParser(
        description="Image -> 3D printable parts (full pipeline)"
    )
    parser.add_argument(
        "--image", "-i", required=True,
        help="Input image (photo of object to 3D-print)",
    )
    parser.add_argument(
        "--output", "-o", default="./print_parts",
        help="Output directory for STL files",
    )
    parser.add_argument(
        "--profile", "-p", default="qidi_q2",
        help="Printer profile name",
    )
    parser.add_argument(
        "--skip-texture", action="store_true",
        help="Skip texture generation (faster, for testing)",
    )
    parser.add_argument(
        "--skip-connectors", action="store_true",
        help="Skip pin/hole generation",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"Error: image not found: {image_path}", file=sys.stderr)
        return 1

    # ==================================================================
    # Step 1: Shape generation (Hunyuan3D-DiT)
    # ==================================================================
    logger.info("=== Step 1: Shape Generation ===")
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    shape_pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2",
        subfolder="hunyuan3d-dit-v2-0-turbo",
    )
    mesh = shape_pipeline(
        image=str(image_path), num_inference_steps=5
    )[0]
    logger.info("Shape generated: %d vertices, %d faces",
                len(mesh.vertices), len(mesh.faces))

    # Post-process
    from hy3dgen.shapegen import (
        FloaterRemover, DegenerateFaceRemover, FaceReducer
    )
    mesh = FloaterRemover()(mesh)
    mesh = DegenerateFaceRemover()(mesh)
    mesh = FaceReducer()(mesh, max_facenum=40000)
    logger.info("Post-processed: %d vertices, %d faces",
                len(mesh.vertices), len(mesh.faces))

    # ==================================================================
    # Step 2: Texture generation (optional)
    # ==================================================================
    if not args.skip_texture:
        logger.info("=== Step 2: Texture Generation ===")
        from hy3dgen.texgen import Hunyuan3DPaintPipeline

        tex_pipeline = Hunyuan3DPaintPipeline.from_pretrained(
            "tencent/Hunyuan3D-2"
        )
        mesh = tex_pipeline(mesh, image=str(image_path))
        logger.info("Texture applied")
    else:
        logger.info("=== Step 2: Skipped (--skip-texture) ===")

    # Save intermediate mesh
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_glb = out_dir / "_full_mesh.glb"
    mesh.export(str(tmp_glb))
    logger.info("Full mesh saved: %s", tmp_glb)

    # ==================================================================
    # Step 3: Part segmentation (P3-SAM)
    # ==================================================================
    logger.info("=== Step 3: Part Segmentation ===")
    from hy3dgen.partseg import PartSegManager

    part_mgr = PartSegManager()
    aabb, face_ids = part_mgr.segment(mesh, seed=args.seed)
    logger.info("Segmented into %d parts", len(aabb) if aabb is not None
                else 0)

    # ==================================================================
    # Step 4: Part completion (XPart)
    # ==================================================================
    logger.info("=== Step 4: Part Completion ===")
    parts_mesh, bbox_mesh, exploded = part_mgr.generate_parts(
        str(tmp_glb), aabb, seed=args.seed
    )
    logger.info("Parts generated")

    # Save exploded view for reference
    if exploded is not None:
        exploded.export(str(out_dir / "_exploded_view.glb"))

    # ==================================================================
    # Step 5: Slicer -- prepare for printing
    # ==================================================================
    logger.info("=== Step 5: Print Preparation ===")
    from hy3dgen.slicer import SlicerManager
    from hy3dgen.slicer.config import load_profile

    profile = load_profile(args.profile)
    slicer = SlicerManager(profile)

    result = slicer.process(
        parts_mesh,
        output_dir=str(out_dir),
        skip_connectors=args.skip_connectors,
    )

    # ==================================================================
    # Summary
    # ==================================================================
    print("\n" + "=" * 50)
    print("  PIPELINE COMPLETE")
    print("=" * 50)
    print(f"  Output directory: {out_dir.resolve()}")
    print(f"  Parts: {len(result)}")
    fitted = sum(1 for p in result if p.fits_bed)
    print(f"  Fit bed: {fitted}/{len(result)}")
    stl_files = sorted(out_dir.glob("*.stl"))
    print(f"  STL files: {len(stl_files)}")
    for f in stl_files:
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name} ({size_kb:.1f} KB)")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
