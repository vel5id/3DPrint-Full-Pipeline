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
        self._device = None

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
        import torch

        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

        if which in ("auto_mask", "all") and self._automask is None:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info(
                "[MEM] Before loading P3-SAM: GPU %.0f MB free / %.0f MB total",
                (torch.cuda.get_device_properties(0).total_memory
                 - torch.cuda.memory_reserved(0)) / 1e6
                if torch.cuda.is_available() else 0,
                torch.cuda.get_device_properties(0).total_memory / 1e6
                if torch.cuda.is_available() else 0,
            )

            # --- P3-SAM ---
            from demo.auto_mask import AutoMask
            self._automask = AutoMask(ckpt_path=None)  # None = auto-download from HF
            logger.info("P3-SAM AutoMask loaded")

            if torch.cuda.is_available():
                logger.info(
                    "[MEM] After P3-SAM load: GPU %.0f MB used / %.0f MB total",
                    torch.cuda.memory_reserved(0) / 1e6,
                    torch.cuda.get_device_properties(0).total_memory / 1e6,
                )

        if which in ("pipeline", "all") and self._pipeline is None:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info(
                "[MEM] Before loading XPart: GPU %.0f MB used / %.0f MB total",
                torch.cuda.memory_reserved(0) / 1e6
                if torch.cuda.is_available() else 0,
                torch.cuda.get_device_properties(0).total_memory / 1e6
                if torch.cuda.is_available() else 0,
            )

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
            self._pipeline.to(device=self._device, dtype=torch.float32)
            logger.info("XPart PartFormerPipeline loaded")

            if torch.cuda.is_available():
                logger.info(
                    "[MEM] After XPart load: GPU %.0f MB used / %.0f MB total",
                    torch.cuda.memory_reserved(0) / 1e6,
                    torch.cuda.get_device_properties(0).total_memory / 1e6,
                )

        if which == "all":
            self._loaded = True

    # ------------------------------------------------------------------
    # Model unloading (critical for OOM prevention)
    # ------------------------------------------------------------------

    def unload_automask(self):
        """Move P3-SAM model to CPU and free GPU memory.

        Call this after :meth:`segment` before loading XPart, to prevent
        both models from occupying GPU simultaneously.
        """
        if self._automask is None:
            return
        import torch

        logger.info("Moving P3-SAM to CPU and freeing GPU memory...")
        self._automask.model.cpu()
        self._automask.model_parallel.cpu()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        logger.info(
            "[MEM] After P3-SAM unload: GPU %.0f MB free / %.0f MB total",
            (torch.cuda.get_device_properties(0).total_memory
             - torch.cuda.memory_reserved(0)) / 1e6
            if torch.cuda.is_available() else 0,
            torch.cuda.get_device_properties(0).total_memory / 1e6
            if torch.cuda.is_available() else 0,
        )

    def unload_pipeline(self):
        """Move XPart pipeline to CPU and free GPU memory.

        Call this after :meth:`generate_parts` to release GPU for
        subsequent shape/texture operations.
        """
        if self._pipeline is None:
            return
        import torch

        logger.info("Moving XPart pipeline to CPU and freeing GPU memory...")
        self._pipeline.to(device="cpu")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        logger.info(
            "[MEM] After XPart unload: GPU %.0f MB free / %.0f MB total",
            (torch.cuda.get_device_properties(0).total_memory
             - torch.cuda.memory_reserved(0)) / 1e6
            if torch.cuda.is_available() else 0,
            torch.cuda.get_device_properties(0).total_memory / 1e6
            if torch.cuda.is_available() else 0,
        )

    def free_all(self):
        """Unload ALL part-segmentation models from GPU."""
        self.unload_automask()
        self.unload_pipeline()
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("All part-segmentation models freed from GPU")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def segment(self, mesh, postprocess: bool = True,
                threshold: float = 0.95, seed: int = 42,
                prompt_bs: int = 8):
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
        prompt_bs : int
            Prompt batch size for P3-SAM inference. Lower values (4-8)
            reduce peak GPU memory at the cost of speed. Default: 8.

        Returns
        -------
        aabb : trimesh.Trimesh or None
            Axis-aligned bounding boxes of the segmented parts.
        face_ids : np.ndarray
            Per-face part labels.  -1 = unassigned.
        """
        self._ensure_loaded(which="auto_mask")
        import torch
        import numpy as np

        logger.info("[MEM] Starting P3-SAM segmentation (prompt_bs=%d)...", prompt_bs)
        aabb, face_ids, _ = self._automask.predict_aabb(
            mesh,
            seed=seed,
            is_parallel=False,
            post_process=postprocess,
            threshold=threshold,
            prompt_bs=prompt_bs,
        )

        # Free GPU tensors from P3-SAM inference
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info("P3-SAM segmentation complete: %d parts found",
                    len(aabb) if aabb is not None else 0)
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
        import torch
        import pytorch_lightning as pl

        pl.seed_everything(int(seed), workers=True)
        additional_params = {"output_type": "trimesh"}

        logger.info("[MEM] Starting XPart part generation...")
        obj_mesh, (out_bbox, mesh_gt_bbox, explode_object) = self._pipeline(
            mesh_path=mesh_path,
            aabb=aabb,
            octree_resolution=512,
            **additional_params,
        )

        # Free GPU tensors from XPart inference
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info("XPart generation complete")
        return obj_mesh, out_bbox, explode_object

    @property
    def is_loaded(self) -> bool:
        return self._loaded
