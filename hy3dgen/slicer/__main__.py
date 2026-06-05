# Hunyuan 3D is licensed under the TENCENT HUNYUAN NON-COMMERCIAL LICENSE AGREEMENT
# except for the third-party components listed below.
# Hunyuan 3D does not impose any additional limitations beyond what is outlined
# in the repsective licenses of these third-party components.
# Users must comply with all terms and conditions of original licenses of these third-party
# components and must ensure that the usage of the third party components adheres to
# all relevant laws and regulations.

# For avoidance of doubts, Hunyuan 3D means the large language models and
# their software and algorithms, including trained model weights, parameters (including
# optimizer states), machine-learning model code, inference-enabling code, training-enabling code,
# fine-tuning enabling code and other elements of the foregoing made publicly available
# by Tencent in accordance with TENCENT HUNYUAN COMMUNITY LICENSE AGREEMENT.

"""CLI entry point for the slicer module.

Usage::

    python -m hy3dgen.slicer input.glb --profile qidi_q2 -o ./parts/
    python -m hy3dgen.slicer input.glb -p ender3 --skip-connectors -v
    python -m hy3dgen.slicer input_dir/  -p ./my_profile.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns 0 on success, 1 on error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --- Logging ---
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Lazy imports so ``--help`` stays fast
    import trimesh
    from hy3dgen.slicer import SlicerManager
    from hy3dgen.slicer.config import load_profile

    # --- Load profile ---
    try:
        profile = load_profile(args.profile)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Printer: {profile.name}")
    print(
        f"  Bed:       {profile.bed_size[0]:.0f} x "
        f"{profile.bed_size[1]:.0f} x "
        f"{profile.bed_size[2]:.0f} mm"
    )
    print(
        f"  Usable:    {profile.usable_bed[0]:.0f} x "
        f"{profile.usable_bed[1]:.0f} x "
        f"{profile.usable_bed[2]:.0f} mm"
    )
    if not args.skip_connectors:
        print(
            f"  Pin:       {profile.connector.pin_diameter} mm x "
            f"{profile.connector.pin_depth} mm "
            f"(tolerance {profile.connector.pin_tolerance} mm)"
        )

    # --- Load mesh(es) ---
    input_path = Path(args.input)
    scene = trimesh.Scene()

    if input_path.is_dir():
        for fpath in sorted(input_path.glob("*")):
            if fpath.suffix.lower() in (".glb", ".ply", ".obj", ".stl"):
                mesh = trimesh.load(str(fpath), force="mesh")
                if isinstance(mesh, trimesh.Trimesh):
                    scene.add_geometry(mesh, geom_name=fpath.stem)
                elif isinstance(mesh, trimesh.Scene):
                    scene = mesh
    else:
        mesh = trimesh.load(str(input_path), force="mesh")
        if isinstance(mesh, trimesh.Scene):
            scene = mesh
        elif isinstance(mesh, trimesh.Trimesh):
            scene.add_geometry(mesh, geom_name=input_path.stem)
        else:
            print(
                f"Error: could not load mesh from '{input_path}'",
                file=sys.stderr,
            )
            return 1

    print(f"Parts loaded: {len(scene.geometry)}")
    if len(scene.geometry) == 0:
        print("Error: no valid meshes found in input", file=sys.stderr)
        return 1

    # --- Process ---
    slicer = SlicerManager(profile=profile)
    result = slicer.process(
        scene,
        output_dir=args.output,
        skip_connectors=args.skip_connectors,
    )

    # --- Summary ---
    fitted = sum(1 for p in result if p.fits_bed)
    oversized = len(result) - fitted
    print(f"\nDone - {len(result)} part(s) processed:")
    print(f"  {fitted} fit the bed")
    if oversized:
        print(f"  {oversized} exceed bed size (BSP splitting in Phase 2)")
    print(f"  Output -> {Path(args.output).resolve()}")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m hy3dgen.slicer",
        description=(
            "Prepare AI-generated 3D meshes for FDM printing. "
            "Adds pin/hole connectors and exports printable STL files."
        ),
    )
    p.add_argument(
        "input",
        help="Path to input mesh (.glb, .ply, .obj, .stl) or directory.",
    )
    p.add_argument(
        "--profile", "-p",
        default="qidi_q2",
        help=(
            "Printer profile: 'qidi_q2', 'ender3', 'prusa_mk4', "
            "or path to a JSON profile file."
        ),
    )
    p.add_argument(
        "--output", "-o",
        default="./print_parts",
        help="Output directory for STL files (default: ./print_parts).",
    )
    p.add_argument(
        "--skip-connectors",
        action="store_true",
        help="Skip pin/hole generation (plain STL export only).",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return p


if __name__ == "__main__":
    raise SystemExit(main())
