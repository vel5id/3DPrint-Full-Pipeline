# Texture Model Restoration — Design Spec

**Date:** 2026-06-06
**Context:** Hunyuan3D-2 fork with slicer/part segmentation additions

## Problem

`Hunyuan3DPaintPipeline` fails to load in the current environment. The texture
generation pipeline has never been functional in this fork.

Root cause: `Multiview_Diffusion_Net.__init__()` calls
`DiffusionPipeline.from_pretrained(custom_pipeline=...)` without
`trust_remote_code=True`. Diffusers 0.38.0 requires this parameter for any
custom pipeline code. The local `hy3dgen/texgen/hunyuanpaint/` directory
contains `HunyuanPaintPipeline`, a custom pipeline that inherits from
`StableDiffusionPipeline` — diffusers detects it as remote code and rejects
it without the trust flag.

## Design

### Fix

**File:** `hy3dgen/texgen/utils/multiview_utils.py`, line 34

**Change:** Add `trust_remote_code=True` to the `DiffusionPipeline.from_pretrained()` call.

```diff
 pipeline = DiffusionPipeline.from_pretrained(
     multiview_ckpt_path,
-    custom_pipeline=custom_pipeline_path, torch_dtype=torch.float16)
+    custom_pipeline=custom_pipeline_path,
+    trust_remote_code=True,
+    torch_dtype=torch.float16)
```

**Why this is the only change needed:**

- `Light_Shadow_Remover` uses `StableDiffusionInstructPix2PixPipeline` —
  a standard diffusers pipeline, no custom code involved.
- `Image_Super_Net` uses `StableDiffusionUpscalePipeline` — also standard.
- The `custom_rasterizer` and `differentiable_renderer` C++ extensions are
  already compiled and import correctly via
  `from hy3dgen.texgen.differentiable_renderer.mesh_render import MeshRender`.
- The model weights for `hunyuan3d-paint-v2-0-turbo` and `hunyuan3d-delight-v2-0`
  are already cached in `~/.cache/huggingface/hub/`.

### Scope

The fix is confined to `multiview_utils.py`. No other files change.

## Verification Plan

### Stage 1: Import and model loading
```python
from hy3dgen.texgen import Hunyuan3DPaintPipeline
pipeline = Hunyuan3DPaintPipeline.from_pretrained(
    'tencent/Hunyuan3D-2', subfolder='hunyuan3d-paint-v2-0-turbo'
)
assert 'delight_model' in pipeline.models
assert 'multiview_model' in pipeline.models
```

### Stage 2: Full texture generation cycle
```bash
python examples/textured_shape_gen.py
```
Confirm `demo.glb` is exported with UV textures.

### Stage 3: Gradio UI integration
```bash
python gradio_app.py
```
Verify in browser:
- Texture model loads (status bar shows "Paint v2-0 Turbo")
- Switching between texture models works (Turbo / Standard / PBR)
- Textured mesh generation produces valid textured GLB output
- Shape + Texture pipeline works end-to-end

### Stage 4: Model switching
- Switch between `paint-turbo`, `paint`, and `paintpbr-v2-1`
- Verify each loads without errors
- Verify `unload_tex_model()` frees VRAM correctly

## Edge Cases

- **GPU OOM on 16 GB cards:** `ModelManager.load_tex_model()` already supports
  `low_vram_mode` → `pipeline.enable_model_cpu_offload()`.
- **Missing C++ extensions:** `load_tex_model()` catches exceptions and sets
  `has_texgen = False`, which the Gradio UI already handles gracefully
  (texture dropdown shown as "Unavailable").
- **Missing model weights:** `from_pretrained()` falls back to HuggingFace
  download via `huggingface_hub.snapshot_download()`.
