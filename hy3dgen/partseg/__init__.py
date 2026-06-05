"""
Hunyuan3D-Part integration: P3-SAM part segmentation + XPart decomposition.

Provides a lazy-loading PartSegManager that wraps the two-stage pipeline:
  1. P3-SAM  — segment a mesh into semantic parts, producing face IDs and AABBs.
  2. XPart   — generate completed, separated part meshes from those AABBs.

Usage::

    from hy3dgen.partseg import PartSegManager

    mgr = PartSegManager()
    aabb, face_ids = mgr.segment(mesh)
    parts, bbox_mesh, exploded = mgr.generate_parts(mesh_path, aabb)
"""

import os
import sys
import gc
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Make P3-SAM and XPart importable (they use flat sys.path style)
_PKG_ROOT = Path(__file__).resolve().parents[2]
_P3SAM_PATH = str(_PKG_ROOT / "P3-SAM")
_XPART_PATH = str(_PKG_ROOT / "XPart" / "partgen" / "models")
_XPART_TOP = str(_PKG_ROOT / "XPart")
for _p in (_P3SAM_PATH, _XPART_PATH, _XPART_TOP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class PartSegManager:
    """
    Manages the P3-SAM → XPart two-stage decomposition pipeline.

    Models are downloaded automatically from ``tencent/Hunyuan3D-Part`` on
    first use (lazy loading).
    """

    def __init__(self):
        self._automask = None
        self._pipeline = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self, which="auto_mask"):
        """Import and initialise sub-models on first access.

        Parameters
        ----------
        which : str
            'auto_mask' — load only P3-SAM (for segmentation).
            'pipeline'  — load only XPart (for part generation).
            'all'       — load both (not recommended on 16 GB GPUs).
        """
        if which in ("auto_mask", "all") and self._automask is None:
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # --- P3-SAM ---
            from demo.auto_mask import AutoMask
            self._automask = AutoMask(ckpt_path=None)  # None = auto-download from HF
            logger.info("P3-SAM AutoMask loaded")

        if which in ("pipeline", "all") and self._pipeline is None:
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # --- XPart ---
            from partgen.partformer_pipeline import PartFormerPipeline
            from partgen.utils.misc import get_config_from_file

            cfg_path = str(_PKG_ROOT / "XPart" / "partgen" / "config" / "infer.yaml")
            config = get_config_from_file(cfg_path)
            assert hasattr(config, "ckpt") or hasattr(config, "ckpt_path"), (
                "ckpt or ckpt_path must be specified in infer.yaml"
            )

            self._pipeline = PartFormerPipeline.from_pretrained(
                model_path="tencent/Hunyuan3D-Part",
                verbose=True,
            )
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._pipeline.to(device=device, dtype=torch.float32)
            logger.info("XPart PartFormerPipeline loaded")

        if which == "all":
            self._loaded = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def segment(self, mesh, postprocess: bool = True,
                threshold: float = 0.95, seed: int = 42):
        """
        Run P3-SAM segmentation on a trimesh.

        Parameters
        ----------
        mesh : trimesh.Trimesh
            The input mesh to segment.
        postprocess : bool
            Merge small parts after segmentation.
        threshold : float
            Post-processing threshold (lower = more merging).
        seed : int
            Random seed for reproducibility.

        Returns
        -------
        aabb : trimesh.Trimesh or None
            Axis-aligned bounding boxes of the segmented parts.
        face_ids : np.ndarray
            Per-face part labels.  -1 = unassigned.
        """
        self._ensure_loaded(which="auto_mask")
        import numpy as np

        aabb, face_ids, _ = self._automask.predict_aabb(
            mesh,
            seed=seed,
            is_parallel=False,
            post_process=postprocess,
            threshold=threshold,
        )
        return aabb, face_ids

    def generate_parts(self, mesh_path: str, aabb, seed: int = 42):
        """
        Run XPart decomposition to generate completed part meshes.

        Parameters
        ----------
        mesh_path : str
            Path to a mesh file (.glb, .ply, .obj) used by the pipeline
            (must match the mesh that was segmented).
        aabb :
            AABB bounding-box structure from :meth:`segment`.
        seed : int
            Random seed.

        Returns
        -------
        parts_mesh : trimesh.Trimesh
            The generated combined parts mesh.
        bbox_mesh : trimesh.Trimesh
            Parts displayed with bounding boxes.
        exploded_mesh : trimesh.Trimesh
            Exploded view of the parts.
        """
        self._ensure_loaded(which="pipeline")
        import pytorch_lightning as pl

        pl.seed_everything(int(seed), workers=True)
        additional_params = {"output_type": "trimesh"}
        obj_mesh, (out_bbox, mesh_gt_bbox, explode_object) = self._pipeline(
            mesh_path=mesh_path,
            aabb=aabb,
            octree_resolution=512,
            **additional_params,
        )
        return obj_mesh, out_bbox, explode_object

    @property
    def is_loaded(self) -> bool:
        return self._loaded
