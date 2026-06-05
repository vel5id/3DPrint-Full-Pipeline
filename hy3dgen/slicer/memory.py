"""Memory monitoring utilities for GPU and CPU.

Provides functions to track memory usage, free GPU memory, and estimate
mesh memory footprint — essential for OOM prevention on 6-16 GB GPUs.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
from functools import wraps
from typing import Any, Callable, Dict

import numpy as np

try:
    import trimesh
    _HAS_TRIMESH = True
except ImportError:
    _HAS_TRIMESH = False

try:
    import torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GPU memory
# ---------------------------------------------------------------------------

def gpu_available() -> bool:
    """Return ``True`` if CUDA is available and a GPU device is present."""
    if not _HAS_TORCH:
        return False
    return torch.cuda.is_available()


def get_gpu_memory_info(device_id: int = 0) -> Dict[str, float]:
    """Return GPU memory info for *device_id*.

    Returns
    -------
    dict
        ``total_mb``, ``used_mb``, ``free_mb``, ``utilization_pct``.
        Returns zeros when CUDA is unavailable.
    """
    if not gpu_available():
        return {"total_mb": 0.0, "used_mb": 0.0, "free_mb": 0.0,
                "utilization_pct": 0.0}

    try:
        total = torch.cuda.get_device_properties(device_id).total_mem
        reserved = torch.cuda.memory_reserved(device_id)
        allocated = torch.cuda.memory_allocated(device_id)
        total_mb = total / (1024.0 * 1024.0)
        used_mb = reserved / (1024.0 * 1024.0)
        free_mb = total_mb - used_mb
        util_pct = (allocated / total) * 100.0 if total > 0 else 0.0
        return {
            "total_mb": round(total_mb, 1),
            "used_mb": round(used_mb, 1),
            "free_mb": round(free_mb, 1),
            "utilization_pct": round(util_pct, 1),
        }
    except Exception:
        return {"total_mb": 0.0, "used_mb": 0.0, "free_mb": 0.0,
                "utilization_pct": 0.0}


# ---------------------------------------------------------------------------
# CPU memory
# ---------------------------------------------------------------------------

def get_cpu_memory_info() -> Dict[str, float]:
    """Return CPU memory info for the current process.

    Returns
    -------
    dict
        ``rss_mb`` — resident set size of this process.
        ``vms_mb`` — virtual memory size.
        ``system_total_mb``, ``system_free_mb`` — when readable.
    """
    info: Dict[str, float] = {}

    # -- RSS / VMS --
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux ru_maxrss is KiB; on macOS it's bytes
        if sys.platform == "darwin":
            rss /= 1024.0
        info["rss_mb"] = round(rss / 1024.0, 1)
    except Exception:
        info["rss_mb"] = -1.0

    # -- /proc/meminfo (Linux) --
    try:
        with open("/proc/meminfo", "r") as fh:
            meminfo = {}
            for line in fh:
                parts = line.split(":")
                if len(parts) >= 2:
                    key = parts[0].strip()
                    val_str = parts[1].strip().split()[0]
                    try:
                        meminfo[key] = int(val_str) / 1024.0  # kB → MB
                    except ValueError:
                        pass
        info["system_total_mb"] = round(meminfo.get("MemTotal", 0.0), 1)
        info["system_free_mb"] = round(
            meminfo.get("MemFree", 0.0) + meminfo.get("Cached", 0.0), 1
        )
    except Exception:
        info.setdefault("system_total_mb", -1.0)
        info.setdefault("system_free_mb", -1.0)

    return info


# ---------------------------------------------------------------------------
# Convenience logging
# ---------------------------------------------------------------------------

def log_memory_usage(logger_instance: logging.Logger, tag: str = "") -> None:
    """Log GPU + CPU memory usage with an optional *tag* for context.

    Parameters
    ----------
    logger_instance : logging.Logger
        Logger to use (e.g. ``logging.getLogger(__name__)``).
    tag : str
        Label to identify this measurement (e.g. ``"after_shape_gen"``).
    """
    prefix = f"[MEM] {tag}: " if tag else "[MEM] "

    gpu = get_gpu_memory_info()
    cpu = get_cpu_memory_info()

    parts = [
        f"GPU: {gpu['used_mb']:.0f}/{gpu['total_mb']:.0f} MB "
        f"({gpu['utilization_pct']:.0f}% used, {gpu['free_mb']:.0f} MB free)",
    ]
    if cpu.get("rss_mb", -1) > 0:
        parts.append(f"RSS: {cpu['rss_mb']:.0f} MB")
    if cpu.get("system_free_mb", -1) > 0:
        parts.append(
            f"SysFree: {cpu['system_free_mb']:.0f} MB"
        )

    logger_instance.info(prefix + " | ".join(parts))


# ---------------------------------------------------------------------------
# Memory cleanup
# ---------------------------------------------------------------------------

def free_gpu_memory() -> None:
    """Release unused GPU memory and run garbage collector."""
    gc.collect()
    if gpu_available():
        torch.cuda.empty_cache()
        gc.collect()


def free_memory(
    logger_instance: logging.Logger | None = None,
    tag: str = "",
) -> Dict[str, float]:
    """Run full memory cleanup + log before/after.

    Returns GPU usage **after** cleanup.
    """
    if logger_instance is not None:
        prefix = f"*** Memory cleanup {tag} ***" if tag else "*** Memory cleanup ***"
        logger_instance.info(prefix)
        log_memory_usage(logger_instance, f"{'before_cleanup' if not tag else tag + '/before'}")

    free_gpu_memory()

    gpu = get_gpu_memory_info()
    if logger_instance is not None:
        logger_instance.info(
            "After cleanup — GPU: %.0f MB free / %.0f MB total",
            gpu["free_mb"], gpu["total_mb"],
        )

    return gpu


# ---------------------------------------------------------------------------
# Decorator for tracking
# ---------------------------------------------------------------------------

def track_memory(tag: str = ""):
    """Decorator: log memory before and after the decorated function."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            label = tag or func.__qualname__
            log_memory_usage(logger, f"{label}/enter")
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                log_memory_usage(logger, f"{label}/exit")
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Mesh memory estimation
# ---------------------------------------------------------------------------

def estimate_mesh_memory(mesh) -> float:
    """Estimate memory footprint of a trimesh in MB.

    Parameters
    ----------
    mesh : trimesh.Trimesh
        The mesh to estimate.

    Returns
    -------
    float
        Estimated memory in MB.
    """
    if not _HAS_TRIMESH:
        return 0.0

    if not isinstance(mesh, trimesh.Trimesh):
        return 0.0

    n_verts = len(mesh.vertices) if mesh.vertices is not None else 0
    n_faces = len(mesh.faces) if mesh.faces is not None else 0

    # vertices: (N,3) float64 = 24 bytes per vertex
    # faces: (M,3) int64 = 24 bytes per face
    # normals, colors, uv — optional, can double the vertex data
    vert_bytes = n_verts * 24 * 2  # 2x for attributes
    face_bytes = n_faces * 24
    total_mb = (vert_bytes + face_bytes) / (1024.0 * 1024.0)

    return round(total_mb, 2)


def warn_if_large_mesh(mesh, logger_instance, name: str = "mesh",
                        threshold_mb: float = 200.0) -> bool:
    """Log a warning if *mesh* exceeds *threshold_mb*.

    Returns True if the mesh is large.
    """
    est_mb = estimate_mesh_memory(mesh)
    is_large = est_mb > threshold_mb
    if is_large:
        logger_instance.warning(
            "Large mesh '%s': %.0f MB estimated (%.0fK verts, %.0fK faces). "
            "Boolean operations may be slow or run out of memory.",
            name, est_mb,
            len(mesh.vertices) / 1000 if mesh.vertices is not None else 0,
            len(mesh.faces) / 1000 if mesh.faces is not None else 0,
        )
    return is_large
