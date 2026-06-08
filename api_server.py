# Hunyuan 3D is licensed under the TENCENT HUNYUAN NON-COMMERCIAL LICENSE AGREEMENT
# except for the third-party components listed below.
# Hunyuan 3D does not impose any additional limitations beyond what is outlined
# in the repsective licenses of these third-party components.
# Users must comply with all terms and conditions of original licenses of these third-party
# components and must ensure that the usage of the third party components adheres to
# all relevant laws and regulations.

"""
Hunyuan3D-2 API Server — FastAPI backend with REST + WebSocket.
Replaces the Gradio UI with a programmatic API for the SPA frontend.
"""

import argparse
import asyncio
import gc
import json
import logging
import os
import pickle
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import trimesh
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image

from hy3dgen.shapegen.utils import logger
from hy3dgen.rembg import BackgroundRemover
from hy3dgen.shapegen import (
    Hunyuan3DDiTFlowMatchingPipeline,
    FloaterRemover,
    DegenerateFaceRemover,
    FaceReducer,
)
from hy3dgen.texgen import Hunyuan3DPaintPipeline
from hy3dgen.text2image import HunyuanDiTPipeline
from gradio_model_manager import (
    ModelManager,
    SHAPE_MODEL_CONFIGS,
    TEX_MODEL_CONFIGS,
    get_available_variants,
)

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
SAVE_DIR = 'gradio_cache'
os.makedirs(SAVE_DIR, exist_ok=True)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

_active_tasks: dict = {}
_task_lock = asyncio.Lock()

_generation_busy = False
_gen_lock = asyncio.Lock()

model_mgr: ModelManager = None

_cpu_executor = ThreadPoolExecutor(max_workers=2)

_ws_connections: list[WebSocket] = []

_partseg_mgr = None
_PARTSEG_AVAILABLE = False

_log = logging.getLogger("api_server")


# ---------------------------------------------------------------------------
# Task helpers
# ---------------------------------------------------------------------------

async def _create_task() -> str:
    task_id = str(uuid.uuid4())
    async with _task_lock:
        _active_tasks[task_id] = {
            'phase': 'starting',
            'percent': 0,
            'done': False,
            'result': None,
            'error': None,
            'cancelled': False,
            'created_at': time.time(),
        }
    return task_id


async def _update_task(task_id: str, phase: str, percent: float, step: int = None, total: int = None):
    async with _task_lock:
        if task_id in _active_tasks:
            _active_tasks[task_id]['phase'] = phase
            _active_tasks[task_id]['percent'] = percent
            if step is not None:
                _active_tasks[task_id]['step'] = step
            if total is not None:
                _active_tasks[task_id]['total'] = total

    payload = {
        'type': 'progress',
        'task_id': task_id,
        'phase': phase,
        'percent': percent,
    }
    if step is not None:
        payload['step'] = step
    if total is not None:
        payload['total'] = total
    msg = json.dumps(payload)
    dead = []
    for ws in _ws_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections.remove(ws)


async def _complete_task(task_id: str, result: dict):
    async with _task_lock:
        if task_id in _active_tasks:
            _active_tasks[task_id]['done'] = True
            _active_tasks[task_id]['percent'] = 100
            _active_tasks[task_id]['phase'] = 'complete'
            _active_tasks[task_id]['result'] = result

    msg = json.dumps({
        'type': 'complete',
        'task_id': task_id,
        'result': result,
    })
    dead = []
    for ws in _ws_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections.remove(ws)


async def _fail_task(task_id: str, code: str, message: str, suggestions: list = None):
    async with _task_lock:
        if task_id in _active_tasks:
            _active_tasks[task_id]['done'] = True
            _active_tasks[task_id]['error'] = {'code': code, 'message': message, 'suggestions': suggestions or []}

    msg = json.dumps({
        'type': 'error',
        'task_id': task_id,
        'code': code,
        'message': message,
        'suggestions': suggestions or [],
    })
    dead = []
    for ws in _ws_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections.remove(ws)


def _gen_save_folder(max_size=200):
    os.makedirs(SAVE_DIR, exist_ok=True)
    dirs = [f for f in Path(SAVE_DIR).iterdir() if f.is_dir()]
    if len(dirs) >= max_size:
        oldest_dir = min(dirs, key=lambda x: x.stat().st_ctime)
        shutil.rmtree(oldest_dir)
        _log.info(f"Removed oldest folder: {oldest_dir}")
    new_folder = os.path.join(SAVE_DIR, str(uuid.uuid4()))
    os.makedirs(new_folder, exist_ok=True)
    return new_folder


def _export_mesh(mesh, save_folder, textured=False, fmt='glb'):
    if textured:
        path = os.path.join(save_folder, f'textured_mesh.{fmt}')
    else:
        path = os.path.join(save_folder, f'white_mesh.{fmt}')
    if fmt not in ('glb', 'obj'):
        mesh.export(path)
    else:
        mesh.export(path, include_normals=True)
    return path


def _build_model_viewer_html(save_folder, height=650, width=500, textured=False):
    if textured:
        related_path = "./textured_mesh.glb"
        template_name = os.path.join(CURRENT_DIR, 'assets', 'modelviewer-textured-template.html')
        output_html_path = os.path.join(save_folder, 'textured_mesh.html')
    else:
        related_path = "./white_mesh.glb"
        template_name = os.path.join(CURRENT_DIR, 'assets', 'modelviewer-template.html')
        output_html_path = os.path.join(save_folder, 'white_mesh.html')
    offset = 50 if textured else 10
    with open(template_name, 'r', encoding='utf-8') as f:
        template_html = f.read()
    with open(output_html_path, 'w', encoding='utf-8') as f:
        template_html = template_html.replace('#height#', f'{height - offset}')
        template_html = template_html.replace('#width#', f'{width}')
        template_html = template_html.replace('#src#', f'{related_path}/')
        f.write(template_html)
    return output_html_path


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _log.info("API server starting...")
    yield
    _log.info("API server shutting down...")
    _cpu_executor.shutdown(wait=False)

app = FastAPI(title="Hunyuan3D-2 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health & Status
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    gpu_info = {}
    if torch.cuda.is_available():
        free_mb, total_mb = torch.cuda.mem_get_info()
        gpu_info = {
            'device_name': torch.cuda.get_device_name(0),
            'vram_used_mb': round((total_mb - free_mb) / 1e6, 1),
            'vram_total_mb': round(total_mb / 1e6, 1),
            'vram_free_mb': round(free_mb / 1e6, 1),
        }
    else:
        gpu_info = {
            'device_name': 'CPU',
            'vram_used_mb': 0,
            'vram_total_mb': 0,
            'vram_free_mb': 0,
        }

    return {
        'status': 'ok',
        'gpu': gpu_info,
        'models_loaded': {
            'shape': model_mgr.current_model_display if model_mgr.shape_pipeline else 'none',
            'texture': model_mgr.current_tex_display if model_mgr.has_texgen else 'unavailable',
        },
        'generation_busy': _generation_busy,
    }


@app.get("/api/models/status")
async def model_status(family: Optional[str] = None):
    query_family = family or model_mgr.shape_family
    return {
        'shape_family': model_mgr.shape_family,
        'shape_variant': model_mgr.shape_variant,
        'shape_display': model_mgr.current_model_display,
        'tex_key': model_mgr.tex_key,
        'tex_display': model_mgr.current_tex_display,
        'has_texgen': model_mgr.has_texgen,
        'is_mv': model_mgr.is_mv_mode,
        'is_turbo': model_mgr.is_turbo,
        'families': [{'key': k, 'display': v['display']} for k, v in SHAPE_MODEL_CONFIGS.items()],
        'variants': [{'key': k, 'display': k.capitalize()} for k in get_available_variants(query_family)],
        'tex_models': [{'key': k, 'display': v['display']} for k, v in TEX_MODEL_CONFIGS.items()],
    }


@app.post("/api/models/load")
async def load_model(data: dict):
    family = data.get('family', model_mgr.shape_family)
    variant = data.get('variant', model_mgr.shape_variant)
    try:
        info = model_mgr.load_shape_model(family, variant)
        return {
            'status': 'ok',
            'model_display': info['model_display'],
            'is_mv': info['is_mv'],
            'default_steps': info['default_steps'],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/models/unload")
async def unload_models(data: dict = None):
    target = data.get('target', 'all') if data else 'all'
    unloaded = []
    if target in ('shape', 'all'):
        model_mgr.unload_shape_model()
        unloaded.append('shape')
    if target in ('texture', 'all'):
        if hasattr(model_mgr, 'unload_tex_model'):
            model_mgr.unload_tex_model()
            unloaded.append('texture')
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    return {'status': 'ok', 'unloaded': unloaded}


# ---------------------------------------------------------------------------
# Generate Endpoints
# ---------------------------------------------------------------------------

async def _run_shape_generation(
    task_id: str, image: Image.Image, steps: int, guidance_scale: float,
    seed: int, octree_resolution: int, num_chunks: int, remove_bg: bool,
):
    global _generation_busy
    try:
        model_mgr.ensure_shape_loaded()

        # Step 1/6 — Remove background
        await _update_task(task_id, 'rembg', 5, step=1, total=6)
        if remove_bg or image.mode == "RGB":
            image = model_mgr.rmbg_worker(image.convert('RGB'))

        # Step 2/6 — Encode image + prepare tensors
        await _update_task(task_id, 'encode', 10, step=2, total=6)

        # Step 3/6 — Diffusion + VAE decode (bulk of GPU work)
        await _update_task(task_id, 'generate', 15, step=3, total=6)
        generator = torch.Generator()
        generator = generator.manual_seed(int(seed))

        t0 = time.time()

        if model_mgr.is_omni:
            outputs = model_mgr.shape_pipeline(
                image=image,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                generator=generator,
                octree_resolution=octree_resolution,
                num_chunks=num_chunks,
                output_type='trimesh',
            )
            mesh = outputs['shapes'][0]
        else:
            from hy3dgen.shapegen.pipelines import export_to_trimesh
            outputs = model_mgr.shape_pipeline(
                image=image,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                generator=generator,
                octree_resolution=octree_resolution,
                num_chunks=num_chunks,
                output_type='mesh',
            )
            mesh = export_to_trimesh(outputs)[0]

        shape_time = time.time() - t0

        if mesh is None:
            await _fail_task(task_id, 'empty_mesh',
                "Surface extraction failed — the model was unable to generate a valid 3D surface.",
                ["Try a different image", "Increase steps to 30", "Change the seed"])
            return

        # Step 4/6 — Surface extraction + decode
        await _update_task(task_id, 'decode', 75, step=4, total=6)

        # Step 5/6 — Post-process mesh (clean up, reduce faces)
        await _update_task(task_id, 'postprocess', 85, step=5, total=6)
        mesh = model_mgr.floater_remover(mesh)
        mesh = model_mgr.degenerate_face_remover(mesh)
        mesh = model_mgr.face_reducer(mesh)

        # Step 6/6 — Save to disk
        await _update_task(task_id, 'save', 95, step=6, total=6)
        save_folder = _gen_save_folder()
        path = _export_mesh(mesh, save_folder, textured=False)

        stats = {
            'verts': len(mesh.vertices),
            'faces': len(mesh.faces),
            'time_shape': round(shape_time, 1),
            'seed': seed,
            'model': model_mgr.current_model_display,
        }

        result = {
            'mesh_path': path,
            'mesh_url': f'/static/{os.path.relpath(path, SAVE_DIR)}',
            'save_folder': save_folder,
            'stats': stats,
        }

        await _complete_task(task_id, result)
    except torch.cuda.OutOfMemoryError:
        await _fail_task(task_id, 'cuda_oom',
            "Out of GPU memory. The model requires more VRAM than is currently available.",
            ["Free texture model via POST /api/models/unload", "Reduce num_chunks to 4000", "Switch to 2mini model"])
    except Exception as e:
        await _fail_task(task_id, 'generation_failed', str(e))
    finally:
        _generation_busy = False
        if model_mgr.low_vram_mode:
            torch.cuda.empty_cache()


async def _run_textured_generation(
    task_id: str, image: Image.Image, steps: int, guidance_scale: float,
    seed: int, octree_resolution: int, num_chunks: int, remove_bg: bool,
):
    global _generation_busy
    try:
        model_mgr.ensure_shape_loaded()

        # Step 1/8 — Remove background
        await _update_task(task_id, 'rembg', 5, step=1, total=8)
        if remove_bg or image.mode == "RGB":
            image = model_mgr.rmbg_worker(image.convert('RGB'))

        # Step 2/8 — Encode image
        await _update_task(task_id, 'encode', 8, step=2, total=8)

        # Step 3/8 — Generate 3D shape (diffusion + VAE)
        await _update_task(task_id, 'generate', 12, step=3, total=8)
        generator = torch.Generator()
        generator = generator.manual_seed(int(seed))

        t0 = time.time()

        if model_mgr.is_omni:
            outputs = model_mgr.shape_pipeline(
                image=image, num_inference_steps=steps,
                guidance_scale=guidance_scale, generator=generator,
                octree_resolution=octree_resolution, num_chunks=num_chunks,
                output_type='trimesh',
            )
            mesh = outputs['shapes'][0]
        else:
            from hy3dgen.shapegen.pipelines import export_to_trimesh
            outputs = model_mgr.shape_pipeline(
                image=image, num_inference_steps=steps,
                guidance_scale=guidance_scale, generator=generator,
                octree_resolution=octree_resolution, num_chunks=num_chunks,
                output_type='mesh',
            )
            mesh = export_to_trimesh(outputs)[0]

        shape_time = time.time() - t0

        if mesh is None:
            await _fail_task(task_id, 'empty_mesh',
                "Surface extraction failed.", ["Try a different image", "Increase steps"])
            return

        # Step 4/8 — Decode surface
        await _update_task(task_id, 'decode', 45, step=4, total=8)

        # Step 5/8 — Post-process mesh
        await _update_task(task_id, 'postprocess', 52, step=5, total=8)
        mesh = model_mgr.floater_remover(mesh)
        mesh = model_mgr.degenerate_face_remover(mesh)
        mesh = model_mgr.face_reducer(mesh)

        # Step 6/8 — Generate texture (multiview diffusion)
        await _update_task(task_id, 'texture', 58, step=6, total=8)
        t1 = time.time()
        textured_mesh = model_mgr.tex_pipeline(mesh, image)
        tex_time = time.time() - t1

        # Step 7/8 — Bake texture + UV
        await _update_task(task_id, 'texture_bake', 85, step=7, total=8)

        # Step 8/8 — Save results
        await _update_task(task_id, 'save', 95, step=8, total=8)
        save_folder = _gen_save_folder()
        white_path = _export_mesh(mesh, save_folder, textured=False)
        tex_path = _export_mesh(textured_mesh, save_folder, textured=True)

        stats = {
            'verts': len(mesh.vertices),
            'faces': len(mesh.faces),
            'time_shape': round(shape_time, 1),
            'time_texture': round(tex_time, 1),
            'time_total': round(shape_time + tex_time, 1),
            'seed': seed,
            'model': model_mgr.current_model_display,
        }

        result = {
            'mesh_path': white_path,
            'mesh_url': f'/static/{os.path.relpath(white_path, SAVE_DIR)}',
            'textured_mesh_path': tex_path,
            'textured_mesh_url': f'/static/{os.path.relpath(tex_path, SAVE_DIR)}',
            'save_folder': save_folder,
            'stats': stats,
        }

        await _complete_task(task_id, result)
    except torch.cuda.OutOfMemoryError:
        await _fail_task(task_id, 'cuda_oom',
            "Out of GPU memory during textured generation.",
            ["Free texture model first", "Use shape-only generation", "Switch to 2mini model"])
    except Exception as e:
        await _fail_task(task_id, 'generation_failed', str(e))
    finally:
        _generation_busy = False
        if model_mgr.low_vram_mode:
            torch.cuda.empty_cache()


@app.post("/api/generate/shape")
async def generate_shape(
    image: UploadFile = File(...),
    steps: int = Form(15),
    guidance_scale: float = Form(5.0),
    seed: Optional[int] = Form(None),
    octree_resolution: int = Form(256),
    num_chunks: int = Form(8000),
    remove_bg: bool = Form(True),
):
    global _generation_busy

    if _generation_busy:
        raise HTTPException(status_code=409, detail="Generation already in progress")

    _generation_busy = True
    task_id = await _create_task()

    import io as _io
    contents = await image.read()
    pil_image = Image.open(_io.BytesIO(contents))

    if seed is None:
        import random
        seed = random.randint(0, int(1e7))

    asyncio.create_task(_run_shape_generation(
        task_id, pil_image, steps, guidance_scale, seed, octree_resolution, num_chunks, remove_bg,
    ))

    return {'task_id': task_id, 'seed': seed}


@app.post("/api/generate/textured")
async def generate_textured(
    image: UploadFile = File(...),
    steps: int = Form(15),
    guidance_scale: float = Form(5.0),
    seed: Optional[int] = Form(None),
    octree_resolution: int = Form(256),
    num_chunks: int = Form(8000),
    remove_bg: bool = Form(True),
):
    global _generation_busy

    if not model_mgr.has_texgen:
        raise HTTPException(status_code=400, detail="Texture generation is not available")

    if _generation_busy:
        raise HTTPException(status_code=409, detail="Generation already in progress")

    _generation_busy = True
    task_id = await _create_task()

    import io as _io
    contents = await image.read()
    pil_image = Image.open(_io.BytesIO(contents))

    if seed is None:
        import random
        seed = random.randint(0, int(1e7))

    asyncio.create_task(_run_textured_generation(
        task_id, pil_image, steps, guidance_scale, seed, octree_resolution, num_chunks, remove_bg,
    ))

    return {'task_id': task_id, 'seed': seed}


# ---------------------------------------------------------------------------
# Part Decomposition Endpoints
# ---------------------------------------------------------------------------

def _init_partseg():
    global _partseg_mgr, _PARTSEG_AVAILABLE
    if _partseg_mgr is not None:
        return
    try:
        from hy3dgen.partseg import PartSegManager
        _partseg_mgr = PartSegManager()
        _PARTSEG_AVAILABLE = True
        _log.info("PartSegManager initialized")
    except Exception as e:
        _log.warning(f"Part segmentation unavailable: {e}")
        _PARTSEG_AVAILABLE = False


async def _run_segment_parts(task_id: str, mesh_path: str, seed: int):
    global _generation_busy
    try:
        if not _PARTSEG_AVAILABLE:
            await _fail_task(task_id, 'partseg_unavailable',
                "Part segmentation dependencies are not installed (spconv, torch_scatter).")
            return

        await _update_task(task_id, 'cleanup', 2)
        model_mgr.unload_shape_model()
        if hasattr(model_mgr, 'unload_tex_model'):
            try: model_mgr.unload_tex_model()
            except Exception: pass
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

        await _update_task(task_id, 'load_mesh', 5)
        mesh = trimesh.load(mesh_path, force='mesh', process=False)

        await _update_task(task_id, 'segment', 15)
        t0 = time.time()
        aabb, face_ids = _partseg_mgr.segment(mesh, seed=seed)
        elapsed = time.time() - t0

        unique_ids = np.unique(face_ids)
        n_parts = len(unique_ids) - (1 if -1 in unique_ids else 0)

        await _update_task(task_id, 'color', 80)
        color_map = {}
        for i in unique_ids:
            if i == -1: continue
            color_map[i] = np.random.RandomState(int(i)).randint(0, 255, 3)
        face_colors = np.array(
            [color_map.get(i, [0, 0, 0]) for i in face_ids]
        ).astype(np.uint8)
        mesh_save = mesh.copy()
        mesh_save.visual.face_colors = face_colors

        await _update_task(task_id, 'save', 90)
        save_folder = _gen_save_folder()
        segmented_path = os.path.join(save_folder, 'segmented.glb')
        mesh_save.export(segmented_path)
        face_id_path = os.path.join(save_folder, 'face_ids.npy')
        np.save(face_id_path, face_ids)
        aabb_pkl_path = os.path.join(save_folder, 'aabb.pkl')
        with open(aabb_pkl_path, 'wb') as f:
            pickle.dump({'aabb': aabb, 'mesh_path': mesh_path}, f)

        try: _partseg_mgr.unload_automask()
        except Exception: pass

        del mesh, mesh_save, face_colors
        gc.collect()

        result = {
            'segmented_mesh_url': f'/static/{os.path.relpath(segmented_path, SAVE_DIR)}',
            'face_id_path': face_id_path,
            'n_parts': n_parts,
            'time_segment': round(elapsed, 1),
            'internal_state': {
                'aabb_pkl': aabb_pkl_path,
                'mesh_path': mesh_path,
                'face_id_path': face_id_path,
            },
        }
        await _complete_task(task_id, result)
    except Exception as e:
        await _fail_task(task_id, 'segment_failed', str(e))
    finally:
        _generation_busy = False


async def _run_generate_parts(task_id: str, internal_state: dict, seed: int):
    global _generation_busy
    try:
        aabb_pkl = internal_state.get('aabb_pkl')
        mesh_path = internal_state.get('mesh_path')
        if not aabb_pkl or not os.path.exists(aabb_pkl):
            await _fail_task(task_id, 'invalid_state', "Segmentation data not found. Re-run segment first.")
            return

        with open(aabb_pkl, 'rb') as f:
            saved = pickle.load(f)
        aabb = saved['aabb']

        await _update_task(task_id, 'cleanup', 2)
        model_mgr.unload_shape_model()
        if hasattr(model_mgr, 'unload_tex_model'):
            try: model_mgr.unload_tex_model()
            except Exception: pass
        try: _partseg_mgr.unload_automask()
        except Exception: pass
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

        await _update_task(task_id, 'xpart', 20)
        t0 = time.time()
        obj_mesh, bbox_mesh, explode_mesh = _partseg_mgr.generate_parts(
            mesh_path, aabb, seed=seed
        )
        elapsed = time.time() - t0

        await _update_task(task_id, 'unload_xpart', 80)
        try: _partseg_mgr.unload_pipeline()
        except Exception: pass
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        await _update_task(task_id, 'save', 90)
        save_folder = _gen_save_folder()
        parts_path = os.path.join(save_folder, 'parts.glb')
        explode_path = os.path.join(save_folder, 'exploded.glb')
        obj_mesh.export(parts_path)
        explode_mesh.export(explode_path)

        internal_state['parts_path'] = parts_path
        internal_state['explode_path'] = explode_path

        result = {
            'parts_mesh_url': f'/static/{os.path.relpath(parts_path, SAVE_DIR)}',
            'exploded_mesh_url': f'/static/{os.path.relpath(explode_path, SAVE_DIR)}',
            'time_generate': round(elapsed, 1),
            'internal_state': internal_state,
        }
        await _complete_task(task_id, result)
    except Exception as e:
        await _fail_task(task_id, 'xpart_failed', str(e))
    finally:
        _generation_busy = False


async def _run_prepare_print(task_id: str, internal_state: dict):
    global _generation_busy
    try:
        parts_path = internal_state.get('parts_path')
        if not parts_path or not os.path.exists(parts_path):
            await _fail_task(task_id, 'invalid_state', "Parts mesh not found. Re-run generate parts first.")
            return

        await _update_task(task_id, 'load_parts', 10)
        parts_mesh = trimesh.load(parts_path, force='mesh')
        if isinstance(parts_mesh, trimesh.Trimesh):
            scene = trimesh.Scene()
            scene.add_geometry(parts_mesh, geom_name='generated_parts')
        else:
            scene = parts_mesh

        await _update_task(task_id, 'slice', 30)
        t0 = time.time()
        from hy3dgen.slicer import SlicerManager
        slicer = SlicerManager()
        save_folder = _gen_save_folder()
        stl_dir = os.path.join(save_folder, 'stl')
        os.makedirs(stl_dir, exist_ok=True)
        slice_result = slicer.process(scene, output_dir=stl_dir, skip_connectors=False)
        elapsed = time.time() - t0

        await _update_task(task_id, 'zip', 70)
        zip_path = os.path.join(save_folder, 'print_parts.zip')
        stl_count = 0
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(stl_dir)):
                if fname.endswith('.stl') or fname.endswith('.txt'):
                    zf.write(os.path.join(stl_dir, fname), fname)
                    if fname.endswith('.stl'):
                        stl_count += 1

        n_parts = len(slice_result)
        fitted = sum(1 for p in slice_result if p.fits_bed)

        del parts_mesh, scene
        gc.collect()

        result = {
            'zip_url': f'/static/{os.path.relpath(zip_path, SAVE_DIR)}',
            'stl_count': stl_count,
            'parts_total': n_parts,
            'parts_fit_bed': fitted,
            'time_slice': round(elapsed, 1),
        }
        await _complete_task(task_id, result)
    except Exception as e:
        await _fail_task(task_id, 'slicer_failed', str(e))
    finally:
        _generation_busy = False


@app.post("/api/parts/segment")
async def segment_parts(data: dict):
    global _generation_busy

    mesh_path = data.get('mesh_path')
    if not mesh_path:
        raise HTTPException(status_code=422, detail="mesh_path is required")

    _init_partseg()
    if not _PARTSEG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Part segmentation not available")

    if _generation_busy:
        raise HTTPException(status_code=409, detail="Another operation is in progress")

    _generation_busy = True
    task_id = await _create_task()
    seed = data.get('seed', 0)
    asyncio.create_task(_run_segment_parts(task_id, mesh_path, seed))
    return {'task_id': task_id}


@app.post("/api/parts/generate")
async def generate_parts(data: dict):
    global _generation_busy

    internal_state = data.get('internal_state')
    if not internal_state:
        raise HTTPException(status_code=422, detail="internal_state from segment result is required")

    _init_partseg()
    if not _PARTSEG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Part generation not available")

    if _generation_busy:
        raise HTTPException(status_code=409, detail="Another operation is in progress")

    _generation_busy = True
    task_id = await _create_task()
    seed = data.get('seed', 0)
    asyncio.create_task(_run_generate_parts(task_id, internal_state, seed))
    return {'task_id': task_id}


@app.post("/api/parts/print")
async def prepare_print(data: dict):
    global _generation_busy

    internal_state = data.get('internal_state')
    if not internal_state:
        raise HTTPException(status_code=422, detail="internal_state from generate parts result is required")

    if _generation_busy:
        raise HTTPException(status_code=409, detail="Another operation is in progress")

    _generation_busy = True
    task_id = await _create_task()
    asyncio.create_task(_run_prepare_print(task_id, internal_state))
    return {'task_id': task_id}


# ---------------------------------------------------------------------------
# Export Endpoint
# ---------------------------------------------------------------------------

@app.post("/api/export")
async def export_mesh(data: dict):
    mesh_path = data.get('mesh_path')
    fmt = data.get('format', 'glb')
    reduce_faces = data.get('reduce_faces', False)
    target_face_count = data.get('target_face_count', 10000)
    include_texture = data.get('include_texture', False)

    if not mesh_path or not os.path.exists(mesh_path):
        raise HTTPException(status_code=404, detail=f"Mesh not found: {mesh_path}")

    mesh = trimesh.load(mesh_path)

    if not include_texture:
        mesh = model_mgr.floater_remover(mesh)
        mesh = model_mgr.degenerate_face_remover(mesh)
        if reduce_faces:
            mesh = model_mgr.face_reducer(mesh, target_face_count)

    save_folder = _gen_save_folder()
    path = _export_mesh(mesh, save_folder, textured=include_texture, fmt=fmt)

    return {
        'file_url': f'/static/{os.path.relpath(path, SAVE_DIR)}',
        'file_path': path,
        'format': fmt,
        'verts': len(mesh.vertices),
        'faces': len(mesh.faces),
    }


# ---------------------------------------------------------------------------
# Task Status & Cancellation
# ---------------------------------------------------------------------------

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    async with _task_lock:
        task = _active_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        'task_id': task_id,
        'phase': task['phase'],
        'percent': task['percent'],
        'done': task['done'],
        'result': task.get('result'),
        'error': task.get('error'),
    }


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    async with _task_lock:
        task = _active_tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task['done']:
            raise HTTPException(status_code=400, detail="Task already completed")
        task['cancelled'] = True

    global _generation_busy
    _generation_busy = False
    await _update_task(task_id, 'cancelled', 0)

    return {'cancelled': True, 'task_id': task_id}


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/progress")
async def websocket_progress(ws: WebSocket):
    await ws.accept()
    _ws_connections.append(ws)
    _log.info(f"WebSocket connected ({len(_ws_connections)} total)")
    try:
        while True:
            data = await ws.receive_text()
            if data == 'ping':
                await ws.send_text('pong')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in _ws_connections:
            _ws_connections.remove(ws)
        _log.info(f"WebSocket disconnected ({len(_ws_connections)} remaining)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--model_path", type=str, default='tencent/Hunyuan3D-2mini')
    parser.add_argument("--subfolder", type=str, default='hunyuan3d-dit-v2-mini-turbo')
    parser.add_argument("--texgen_model_path", type=str, default='tencent/Hunyuan3D-2')
    parser.add_argument("--device", type=str, default='cuda')
    parser.add_argument("--mc_algo", type=str, default='mc')
    parser.add_argument("--cache_path", type=str, default='gradio_cache')
    parser.add_argument("--enable_flashvdm", action='store_true')
    parser.add_argument("--low_vram_mode", action='store_true')
    parser.add_argument("--enable_t23d", action='store_true', help="Enable text-to-3D via HunyuanDiT")
    parser.add_argument("--disable_tex", action='store_true', help="Disable texture generation")
    args = parser.parse_args()

    SAVE_DIR = args.cache_path
    os.makedirs(SAVE_DIR, exist_ok=True)

    _log.info(f"Initializing ModelManager...")
    _log.info(f"  Model: {args.model_path}/{args.subfolder}")
    _log.info(f"  Texture: {args.texgen_model_path}")
    _log.info(f"  Device: {args.device}")
    _log.info(f"  Low VRAM: {args.low_vram_mode}")

    model_mgr = ModelManager(
        device=args.device,
        cli_model_path=args.model_path,
        cli_subfolder=args.subfolder,
        cli_texgen_path=args.texgen_model_path,
        enable_flashvdm_flag=args.enable_flashvdm,
        mc_algo=args.mc_algo,
        low_vram_mode=args.low_vram_mode,
    )

    model_mgr.load_shape_model(model_mgr.shape_family, model_mgr.shape_variant)

    model_mgr.floater_remover = FloaterRemover()
    model_mgr.degenerate_face_remover = DegenerateFaceRemover()
    model_mgr.face_reducer = FaceReducer()
    model_mgr.rmbg_worker = BackgroundRemover()

    if not args.disable_tex:
        try:
            model_mgr.load_tex_model(model_mgr.tex_key)
            _log.info(f"Texture model loaded: {model_mgr.current_tex_display}")
        except Exception as e:
            _log.warning(f"Texture generation unavailable: {e}")

    if args.enable_t23d:
        try:
            model_mgr.t2i_worker = HunyuanDiTPipeline(
                'Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled', device=args.device
            )
            _log.info("Text-to-image worker loaded")
        except Exception as e:
            _log.warning(f"Text-to-image unavailable: {e}")

    static_dir = Path(SAVE_DIR).absolute()
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")

    app_dir = Path(CURRENT_DIR) / 'app'
    if app_dir.exists():
        app.mount("/", StaticFiles(directory=app_dir, html=True), name="spa")
        _log.info(f"SPA frontend mounted from {app_dir}")

    env_maps_src = os.path.join(CURRENT_DIR, 'assets', 'env_maps')
    env_maps_dst = os.path.join(static_dir, 'env_maps')
    if os.path.exists(env_maps_src) and not os.path.exists(env_maps_dst):
        shutil.copytree(env_maps_src, env_maps_dst, dirs_exist_ok=True)

    _log.info(f"Starting API server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
