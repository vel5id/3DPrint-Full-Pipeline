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

"""Mesh size checker — validates parts against printer bed dimensions.

Phase 1 (MVP): pass-through — checks if each part fits, logs warnings for
oversized parts.  BSP splitting will be added in Phase 2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

import numpy as np
import trimesh

from .config import PrinterProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PartInfo — shared data object
# ---------------------------------------------------------------------------

@dataclass
class PartInfo:
    """Lightweight descriptor for a part travelling through the pipeline."""

    mesh: trimesh.Trimesh
    name: str
    bbox_min: np.ndarray   # (3,) world-space minimum corner
    bbox_max: np.ndarray   # (3,) world-space maximum corner
    bbox_size: np.ndarray  # (3,) extent = bbox_max - bbox_min

    # Set by MeshCutter.check_part()
    fits_bed: bool = True


# ---------------------------------------------------------------------------
# MeshCutter
# ---------------------------------------------------------------------------

class MeshCutter:
    """Validates part dimensions against printer bed size.

    Parameters
    ----------
    profile : PrinterProfile
        The target printer profile.
    """

    def __init__(self, profile: PrinterProfile) -> None:
        self.profile = profile

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_part(
        self, mesh: trimesh.Trimesh, name: str = "part"
    ) -> PartInfo:
        """Check whether a single mesh fits within the usable bed.

        Parameters
        ----------
        mesh : trimesh.Trimesh
            The part mesh.
        name : str
            Human-readable part identifier.

        Returns
        -------
        PartInfo

        Raises
        ------
        ValueError
            If *mesh* is ``None`` or has zero vertices.
        """
        if mesh is None or len(mesh.vertices) == 0:
            raise ValueError(f"Part '{name}' is empty or has no vertices.")

        bbox_min = np.asarray(mesh.bounds[0], dtype=np.float64)
        bbox_max = np.asarray(mesh.bounds[1], dtype=np.float64)
        bbox_size = bbox_max - bbox_min

        info = PartInfo(
            mesh=mesh,
            name=name,
            bbox_min=bbox_min,
            bbox_max=bbox_max,
            bbox_size=bbox_size,
        )
        info.fits_bed = self.profile.part_fits(tuple(bbox_size))

        if not info.fits_bed:
            logger.warning(
                "Part '%s' (%.0f×%.0f×%.0f mm) exceeds usable bed "
                "(%.0f×%.0f×%.0f mm). BSP splitting will be "
                "available in Phase 2.",
                name,
                *bbox_size,
                *self.profile.usable_bed,
            )

        return info

    def process(self, parts: trimesh.Scene | None) -> List[PartInfo]:
        """Process every ``trimesh.Trimesh`` geometry in a scene.

        Parameters
        ----------
        parts : trimesh.Scene or None
            Scene containing part meshes (e.g. from PartSegManager).

        Returns
        -------
        list[PartInfo]
            One entry per valid ``Trimesh``, in scene-iteration order.
        """
        if parts is None:
            return []

        results: List[PartInfo] = []
        for geom_name, geom in parts.geometry.items():
            if not isinstance(geom, trimesh.Trimesh):
                continue
            try:
                label = geom_name if geom_name else f"part_{len(results):03d}"
                info = self.check_part(geom, label)
                results.append(info)
            except ValueError as exc:
                logger.warning("Skipping geometry '%s': %s", geom_name, exc)

        return results
