# Hunyuan3D-2 UI Redesign — Design Spec

**Date:** 2026-06-06
**Status:** Approved
**Approach:** Full rewrite — Custom SPA frontend + FastAPI REST/WebSocket backend (Approach 2)

## 1. Goals & Scope

Replace the existing Gradio-based UI with a custom single-page application that provides:

- Modern, visually appealing interface with two themes (Dark Industrial + Clean Minimal)
- Intuitive tabbed workflow with contextual progression (Generate → Texture → Parts → Export)
- Real-time progress feedback via WebSocket
- Advanced user mode toggle for full parameter control
- GPU-aware error handling with actionable recovery suggestions

### Out of scope
- Modifying ModelManager or GPU lifecycle logic (these are untouchable)
- Modifying ML pipelines (shapegen, texgen, partseg, slicer)
- Adding new ML capabilities
- Backend deployment/infrastructure changes

## 2. Architecture

```
┌─────────────────────────────────────┐
│  SPA Frontend (app/)                 │
│  Static HTML/CSS/JS                  │
│  Custom routing, components, themes  │
│  WebSocket for real-time progress    │
└──────────────┬──────────────────────┘
               │ HTTP REST + WebSocket
┌──────────────▼──────────────────────┐
│  FastAPI Backend (api_server.py)     │
│  ├─ /api/health      (GET)          │
│  ├─ /api/models/     (load, status) │
│  ├─ /api/generate/   (shape, textured)│
│  ├─ /api/parts/      (segment, gen, print)│
│  ├─ /api/export/     (POST)         │
│  ├─ /api/tasks/{id}  (GET, cancel)  │
│  └─ /ws/progress     (WebSocket)    │
├──────────────────────────────────────┤
│  ModelManager (UNTOUCHED)            │
│  shapegen / texgen / partseg / slicer│
└──────────────────────────────────────┘
```

### Key principles
1. ModelManager API is sacred — wrap, don't modify
2. FastAPI is the single entry point — no Gradio in production
3. WebSocket for live multi-phase progress (replaces Gradio generators)
4. GPU lifecycle managed through REST endpoints
5. One generation at a time — concurrent requests get 409 Conflict

## 3. UI Layout

**Layout: Sidebar Panel + 3D Viewer (Variant 1)**

```
┌──────────┬───────────────────────────────┐
│ Sidebar  │                               │
│ 280px    │                               │
│          │       3D Viewport             │
│ [Tabs]   │    (model-viewer)             │
│ [Input]  │                               │
│ [Params] │                               │
│ [Actions]│                               │
│          │                               │
│ [Status] ├───────────────────────────────┤
│          │       Status Bar              │
└──────────┴───────────────────────────────┘
```

### Tabs (contextual availability)
- **Generate** — always available. Image upload + parameters + generate buttons
- **Texture** — unlocked after successful mesh generation. Texture model selection + apply
- **Parts** — unlocked after mesh exists. 3-step process: Segment → Generate Parts → Prepare Print
- **Export** — always available. Format selection + download

Tabs after the current one are visible but dimmed. Completing a step auto-advances.

### Generate tab — two modes
- **Compact (default):** image drag-drop zone, steps slider, seed toggle, Generate/Generate+Texture buttons
- **Advanced (toggle):** all sliders (steps, guidance, octree, chunks, seed field), model selector, presets (Fast/Balanced/Quality), remove bg checkbox

## 4. Visual Design

### Dark Industrial (default)
- Background: `#0d1117` → `#161b22` → `#21262d`
- Accent: `#7ee787` (green neon)
- Font: SF Mono for UI chrome, Inter for content
- Border radius: 4px (sharp, technical)
- Inspired by GitHub dark theme, terminal aesthetics

### Clean Minimal (light)
- Background: `#ffffff` → `#fafafa` → `#f3f4f6`
- Accent: `#111827` (near-black)
- Font: Inter throughout
- Border radius: 8px (softer, modern)
- Inspired by Linear, Figma, Apple design

### Theme switching
- CSS custom properties on `:root` / `[data-theme="light"]`
- `transition: background-color 0.2s, color 0.2s` for smooth switch
- localStorage key `theme`, defaults to `prefers-color-scheme`

## 5. Component Architecture

```
app/
├── index.html
├── css/
│   ├── themes.css      # CSS custom properties for both themes
│   └── app.css         # Layout, components, utilities
├── js/
│   ├── app.js          # Entry point, init, global state
│   ├── api.js          # HTTP client + WebSocket manager
│   ├── state.js        # Centralized AppState store
│   ├── components/
│   │   ├── tabs.js          # TabBar with contextual activation
│   │   ├── upload.js        # Drag-drop + paste image upload
│   │   ├── params.js        # Compact & advanced parameter panels
│   │   ├── presets.js       # Fast/Balanced/Quality presets
│   │   ├── viewer.js        # model-viewer wrapper with controls
│   │   ├── progress.js      # Multi-phase progress bar
│   │   ├── statusbar.js     # Bottom status bar (model, VRAM, GPU)
│   │   ├── modal.js         # Modal system (errors, confirmations)
│   │   ├── theme.js         # Theme toggle, localStorage, system preference
│   │   └── model-select.js  # Model family/variant/tex selectors
│   └── lib/              # Vendor libraries
└── assets/               # Icons, fonts
```

### State management
- Single `AppState` object
- Components READ from state, WRITE through `state.set(key, val)` which triggers subscribers
- Components communicate via events, not direct references

### API client
- `api.*` methods for all REST endpoints
- `ws.*` for WebSocket events (progress, error, complete)
- Automatic reconnection with exponential backoff (1s→2s→4s→8s→max 30s)

## 6. Data Flow

### Generation flow
```
User drops image → upload component fires 'image-selected'
  → state.image = file → preview shown
User clicks "Generate"
  → POST /api/generate/shape (FormData: image + params)
  → { task_id: "abc-123" }
  → WS progress events: {phase: "rembg", percent: 20} → {phase: "shape", percent: 60} → ...
  → WS complete: {task_id, result: {mesh_url, stats}}
  → viewer.load(mesh_url) → 3D model displayed
  → Texture tab auto-activated
```

### Error states
| State | UI Response |
|-------|------------|
| VRAM low | Yellow warning in status bar + "Free GPU" button |
| CUDA OOM | Modal with actionable suggestions (free texture model, reduce chunks, switch to mini) |
| Empty mesh | Banner with "Retry with steps=30" button |
| WS disconnected | "Reconnecting..." indicator in status bar, auto-reconnect |
| Long operation (>30s) | Progress bar with phase label + Cancel button |
| Concurrent request | 409 → notification "Generation already in progress" |

## 7. API Endpoints

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/api/health` | — | `{gpu, models_loaded, vram}` |
| POST | `/api/generate/shape` | FormData(image, steps, seed, ...) | `{task_id}` |
| POST | `/api/generate/textured` | FormData(image, steps, seed, ...) | `{task_id}` |
| POST | `/api/parts/segment` | JSON(mesh_url, seed) | `{task_id}` |
| POST | `/api/parts/generate` | JSON(part_state) | `{task_id}` |
| POST | `/api/parts/print` | JSON(parts_path) | `{task_id}` |
| POST | `/api/export` | JSON(mesh_url, format, reduce_faces, ...) | `{file_url}` |
| GET | `/api/models/status` | — | `{shape_model, tex_model}` |
| POST | `/api/models/load` | JSON(family, variant) | `{status, model_display}` |
| GET | `/api/tasks/{task_id}` | — | `{phase, percent, done, result?}` |
| POST | `/api/tasks/{task_id}/cancel` | — | `{cancelled: true}` |
| WS | `/ws/progress` | — | `{task_id, phase, percent, message}` |

## 8. Migration Strategy

Parallel development — Gradio and SPA coexist:

1. **Phase 1:** Build `api_server.py` with all endpoints. Test with `httpx`.
2. **Phase 2:** Build SPA frontend (`app/`). Test against API on port 8081.
3. **Phase 3:** Switch production port. Old Gradio remains as fallback.

Both can run simultaneously — SPA on 8081, Gradio on 8080.

### Untouched files
- `gradio_model_manager.py` — ModelManager class
- `hy3dgen/shapegen/*` — shape pipelines
- `hy3dgen/texgen/*` — texture pipelines
- `hy3dgen/partseg/*` — P3-SAM, XPart
- `hy3dgen/slicer/*` — print preparation
- `hy3dgen/rembg.py` — background removal

### Modified files
- `api_server.py` — rewritten from scratch (REST + WS)
- `app/*` — entirely new directory

### Removed (after migration)
- `gradio_app.py` — replaced by api_server + SPA
- All `gradio_cache/` references moved to standard cache dir

## 9. Testing

| Level | Tool | Scope |
|-------|------|-------|
| API unit | pytest + httpx | All endpoints, mocked ModelManager |
| WebSocket | pytest-asyncio + websockets | Progress events, reconnect, timeouts |
| GPU integration | pytest (GPU required) | Load/unload, OOM handling, concurrency |
| Frontend | Manual + browser screenshots | Component rendering, theme switching |
| E2E | Playwright | Full pipeline: upload → generate → texture → parts → export |

## 10. File Structure (final)

```
Hunyuan3D-2/
├── api_server.py              # ✦ Rewritten: FastAPI REST + WebSocket
├── gradio_app.py              # Kept as fallback during migration
├── gradio_model_manager.py    # UNTOUCHED
├── app/                       # ✦ New: SPA frontend
│   ├── index.html
│   ├── css/
│   │   ├── themes.css
│   │   └── app.css
│   ├── js/
│   │   ├── app.js
│   │   ├── api.js
│   │   ├── state.js
│   │   └── components/
│   │       ├── tabs.js
│   │       ├── upload.js
│   │       ├── params.js
│   │       ├── presets.js
│   │       ├── viewer.js
│   │       ├── progress.js
│   │       ├── statusbar.js
│   │       ├── modal.js
│   │       ├── theme.js
│   │       └── model-select.js
│   └── assets/
├── hy3dgen/                   # UNTOUCHED
├── tests/
│   └── test_api.py            # ✦ New: API tests
└── ...
```
