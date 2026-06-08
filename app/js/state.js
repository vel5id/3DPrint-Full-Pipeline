/**
 * Centralized application state store with subscriber pattern.
 * Components read directly, write via set(), subscribe for updates.
 */

const AppState = (() => {
  const _subscribers = {};
  const _state = {
    /* ---- UI State ---- */
    activeTab: 'generate',       // 'generate' | 'texture' | 'parts' | 'export'
    theme: 'dark',               // 'dark' | 'light'
    advancedMode: false,         // compact vs full parameter panel
    preset: null,                // 'fast' | 'balanced' | 'quality' | null

    /* ---- Input ---- */
    image: null,                 // File object
    imagePreview: null,          // blob URL string
    imageDataUrl: null,          // base64 data URL for API

    /* ---- Parameters ---- */
    params: {
      seed: null,                // null = random
      steps: 15,
      guidanceScale: 5.0,
      octreeResolution: 256,
      numChunks: 8000,
      removeBg: true,
      randomizeSeed: true,
    },

    /* ---- Model ---- */
    model: {
      family: 'hunyuan3d-2mini',
      variant: 'turbo',
      texKey: 'paint-turbo',
      familyDisplay: 'Hunyuan3D-2 mini (0.6B)',
      variantDisplay: 'Turbo',
      texDisplay: 'Paint v2-0 Turbo',
    },

    /* ---- Generation Results ---- */
    meshPath: null,              // server file path for white mesh
    meshUrl: null,               // URL to .glb for viewer
    texturedMeshPath: null,
    texturedMeshUrl: null,
    meshStats: null,             // { verts, faces, size_mb, time_shape, time_texture }

    /* ---- Parts State ---- */
    segmentedMeshUrl: null,
    generatedPartsUrl: null,
    explodedPartsUrl: null,
    printZipUrl: null,
    partsInternalState: null,    // opaque state passed between parts API calls

    /* ---- GPU ---- */
    gpu: {
      vramUsedMb: 0,
      vramTotalMb: 0,
      busy: false,
      currentOp: null,           // 'shape' | 'texture' | 'segment' | 'xpart' | 'slicer' | null
      deviceName: '',
    },

    /* ---- Tasks ---- */
    activeTaskId: null,
  };

  /**
   * Deep-read a dotted path: state.get('gpu.vramUsedMb')
   */
  function get(path) {
    const keys = path.split('.');
    let val = _state;
    for (const k of keys) {
      if (val == null) return undefined;
      val = val[k];
    }
    return val;
  }

  /**
   * Deep-set a dotted path, shallow-clone intermediate objects so
   * === comparisons fail and subscribers fire correctly.
   */
  function set(path, value) {
    const keys = path.split('.');
    let target = _state;

    for (let i = 0; i < keys.length - 1; i++) {
      const k = keys[i];
      if (target[k] === null || typeof target[k] !== 'object') {
        target[k] = {};
      } else {
        target[k] = { ...target[k] };
      }
      target = target[k];
    }

    const lastKey = keys[keys.length - 1];
    if (target[lastKey] === value) return;
    target[lastKey] = value;

    _notify(path, value);
  }

  /**
   * Bulk-update from a flat object: setAll({ 'params.steps': 30, 'theme': 'light' })
   */
  function setAll(updates) {
    for (const [path, value] of Object.entries(updates)) {
      set(path, value);
    }
  }

  /**
   * Reset parameters to defaults for a given preset.
   */
  function applyPreset(name) {
    const presets = {
      fast:   { steps: 5,  guidanceScale: 3.0, octreeResolution: 196, numChunks: 4000 },
      balanced: { steps: 15, guidanceScale: 5.0, octreeResolution: 256, numChunks: 8000 },
      quality:{ steps: 30, guidanceScale: 7.5, octreeResolution: 384, numChunks: 200000 },
    };
    const p = presets[name];
    if (!p) return;
    setAll(Object.entries(p).reduce((acc, [k, v]) => {
      acc[`params.${k}`] = v;
      return acc;
    }, {}));
    set('preset', name);
  }

  /**
   * Subscribe to changes on a path prefix.
   * Returns unsubscribe function.
   */
  function subscribe(pathPrefix, callback) {
    if (!_subscribers[pathPrefix]) _subscribers[pathPrefix] = [];
    _subscribers[pathPrefix].push(callback);
    return () => {
      _subscribers[pathPrefix] = _subscribers[pathPrefix].filter(cb => cb !== callback);
    };
  }

  function _notify(path, value) {
    if (_subscribers[path]) {
      _subscribers[path].forEach(cb => cb(value));
    }
    for (const [prefix, cbs] of Object.entries(_subscribers)) {
      if (path !== prefix && path.startsWith(prefix + '.')) {
        cbs.forEach(cb => cb(path, value));
      }
    }
    if (_subscribers['*']) {
      _subscribers['*'].forEach(cb => cb(path, value));
    }
  }

  return { get, set, setAll, applyPreset, subscribe };
})();
