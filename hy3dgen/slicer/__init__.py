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

"""Slicer module — prepare 3D meshes for FDM printing.

Provides::

    from hy3dgen.slicer import SlicerManager, QIDI_Q2_PROFILE

    slicer = SlicerManager(QIDI_Q2_PROFILE)
    slicer.process(parts_scene, output_dir="./print_parts/")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import trimesh

from .config import (
    ConnectorConfig,
    PrinterProfile,
    QIDI_Q2_PROFILE,
    ENDER3_PROFILE,
    PRUSA_MK4_PROFILE,
    BUILTIN_PROFILES,
    load_profile,
)
from .cutter import MeshCutter, PartInfo
from .connectors import PinHoleGenerator

logger = logging.getLogger(__name__)


class SlicerManager:
    """Orchestrates the 3D-print preparation pipeline.

    Takes semantically-segmented parts (from ``PartSegManager``) and
    prepares them for FDM printing:

    1. **Check sizes** — verify each part fits within the printer bed
       (warns about oversized parts; BSP splitting arrives in Phase 2).
    2. **Generate connectors** — add pin/hole alignment features between
       adjacent parts.
    3. **Export STL** — write individual ``.stl`` files + ``README.txt``.

    Parameters
    ----------
    profile : PrinterProfile
        Target printer profile (default: ``QIDI_Q2_PROFILE``).
    """

    def __init__(
        self, profile: PrinterProfile = QIDI_Q2_PROFILE
    ) -> None:
        self.profile = profile
        self.cutter = MeshCutter(profile)
        self.connector_gen = PinHoleGenerator(profile.connector)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        parts: trimesh.Scene,
        output_dir: Optional[str] = None,
        skip_connectors: bool = False,
    ) -> List[PartInfo]:
        """Run the full preparation pipeline.

        Parameters
        ----------
        parts : trimesh.Scene
            Part meshes (e.g. output of
            :meth:`hy3dgen.partseg.PartSegManager.generate_parts`).
        output_dir : str, optional
            Directory for STL output.  When ``None``, files are **not**
            written (parts are still processed).
        skip_connectors : bool
            Pass ``True`` to skip pin/hole generation (faster, useful
            for testing or when parts don't need alignment aids).

        Returns
        -------
        list[PartInfo]
            Processed parts (meshes have connectors applied).
        """
        # ---- 1. Size check ----
        part_infos = self.cutter.process(parts)
        if not part_infos:
            logger.warning("No valid parts found in input scene")
            return []

        logger.info(
            "Processing %d part(s) | Printer: %s | "
            "Usable bed: %.0f×%.0f×%.0f mm",
            len(part_infos),
            self.profile.name,
            *self.profile.usable_bed,
        )

        oversized = [p for p in part_infos if not p.fits_bed]
        if oversized:
            logger.warning(
                "%d part(s) exceed bed size (BSP splitting in Phase 2): %s",
                len(oversized),
                ", ".join(
                    f"'{p.name}' "
                    f"({p.bbox_size[0]:.0f}×"
                    f"{p.bbox_size[1]:.0f}×"
                    f"{p.bbox_size[2]:.0f} mm)"
                    for p in oversized
                ),
            )

        # ---- 2. Connectors ----
        if not skip_connectors:
            part_infos = self.connector_gen.generate(part_infos)

        # ---- 3. Export ----
        if output_dir is not None:
            self.export_stl(part_infos, output_dir)

        return part_infos

    # ------------------------------------------------------------------
    # STL export
    # ------------------------------------------------------------------

    def export_stl(
        self, parts: List[PartInfo], output_dir: str
    ) -> List[Path]:
        """Export parts as individual STL files.

        Parameters
        ----------
        parts : list[PartInfo]
            Processed parts (with or without connectors).
        output_dir : str
            Directory path.  Created if it doesn't exist.

        Returns
        -------
        list[Path]
            Absolute paths to the saved ``.stl`` files.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        saved: List[Path] = []
        for idx, part in enumerate(parts):
            safe = part.name.replace(" ", "_").replace("/", "_")
            fname = f"part_{idx:03d}_{safe}.stl"
            fpath = out / fname

            try:
                part.mesh.export(str(fpath))
                saved.append(fpath.resolve())
                logger.info("Exported %s", fpath)
            except Exception as exc:
                logger.error("Failed to export '%s': %s", fname, exc)

        # Summary README
        self._write_summary(parts, out / "README.txt")

        logger.info(
            "Exported %d STL file(s) → %s", len(saved), out.resolve()
        )
        return saved

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_summary(
        self,
        parts: List[PartInfo],
        path: Path,
    ) -> None:
        """Write a human-readable summary to *path*."""
        lines = [
            "=" * 50,
            "  3D Print Parts Summary",
            "=" * 50,
            "",
            f"Printer:       {self.profile.name}",
            f"Bed size:      {self.profile.bed_size[0]:.0f} × "
            f"{self.profile.bed_size[1]:.0f} × "
            f"{self.profile.bed_size[2]:.0f} mm",
            f"Usable bed:    {self.profile.usable_bed[0]:.0f} × "
            f"{self.profile.usable_bed[1]:.0f} × "
            f"{self.profile.usable_bed[2]:.0f} mm",
            "",
            f"Pin diameter:  {self.profile.connector.pin_diameter} mm",
            f"Pin depth:     {self.profile.connector.pin_depth} mm",
            f"Tolerance:     {self.profile.connector.pin_tolerance} mm",
            "",
            "-" * 50,
            f"  {'#':<4} {'Name':<30} {'Size (mm)':<25} {'Status'}",
            "-" * 50,
        ]

        for idx, part in enumerate(parts):
            status = "✓ FITS" if part.fits_bed else "⚠ EXCEEDS BED"
            size_str = (
                f"{part.bbox_size[0]:.0f}×"
                f"{part.bbox_size[1]:.0f}×"
                f"{part.bbox_size[2]:.0f}"
            )
            lines.append(
                f"  [{idx:03d}] "
                f"{part.name:<30} "
                f"{size_str:<25} "
                f"{status}"
            )

        lines.extend([
            "",
            "-" * 50,
            "Assembly Notes",
            "-" * 50,
            "• Align parts using the pin/hole connectors as guides.",
            "• Use cyanoacrylate (super glue) for permanent bonding.",
            "• Test-fit all parts before gluing.",
            "• Print orientation is NOT optimized (Phase 2 feature).",
            f"• Generated by hy3dgen.slicer for {self.profile.name}",
        ])

        with open(path, "w") as fh:
            fh.write("\n".join(lines) + "\n")
