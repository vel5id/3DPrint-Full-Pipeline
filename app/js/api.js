/**
 * HTTP REST client + WebSocket manager.
 * All backend communication goes through this module.
 */

const API = (() => {
  const BASE = '';

  let _ws = null;
  let _wsReconnectTimer = null;
  let _wsReconnectDelay = 1000;
  let _wsCallbacks = {
    progress: null,
    error: null,
    complete: null,
    connected: null,
    disconnected: null,
  };

  /* ==================================================================
   *  HTTP Helpers
   * ================================================================*/

  async function _request(method, path, body, isFormData) {
    const url = `${BASE}${path}`;
    const opts = { method };
    if (body) {
      if (isFormData) {
        opts.body = body;
      } else {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
      }
    }
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const err = new Error(data?.detail || `HTTP ${res.status}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function _get(path)           { return _request('GET', path); }
  function _post(path, body, fd) { return _request('POST', path, body, fd); }

  /* ==================================================================
   *  Public REST API
   * ================================================================*/

  /** GET /api/health */
  async function health() {
    const data = await _get('/api/health');
    AppState.setAll({
      'gpu.vramUsedMb': data.vram_used_mb,
      'gpu.vramTotalMb': data.vram_total_mb,
      'gpu.deviceName': data.device_name || '',
    });
    return data;
  }

  /** GET /api/models/status?family= */
  function modelStatus(family) {
    const qs = family ? `?family=${encodeURIComponent(family)}` : '';
    return _get(`/api/models/status${qs}`);
  }

  /** POST /api/models/load */
  function loadModel(family, variant) {
    return _post('/api/models/load', { family, variant });
  }

  /** POST /api/generate/shape */
  async function generateShape() {
    const fd = new FormData();
    fd.append('image', AppState.get('image'));
    fd.append('steps', AppState.get('params.steps'));
    fd.append('guidance_scale', AppState.get('params.guidanceScale'));
    fd.append('octree_resolution', AppState.get('params.octreeResolution'));
    fd.append('num_chunks', AppState.get('params.numChunks'));
    fd.append('remove_bg', AppState.get('params.removeBg'));
    const seed = AppState.get('params.seed');
    fd.append('seed', seed !== null ? seed : Math.floor(Math.random() * 1e7));
    const data = await _post('/api/generate/shape', fd, true);
    AppState.set('activeTaskId', data.task_id);
    return data;
  }

  /** POST /api/generate/textured */
  async function generateTextured() {
    const fd = new FormData();
    fd.append('image', AppState.get('image'));
    fd.append('steps', AppState.get('params.steps'));
    fd.append('guidance_scale', AppState.get('params.guidanceScale'));
    fd.append('octree_resolution', AppState.get('params.octreeResolution'));
    fd.append('num_chunks', AppState.get('params.numChunks'));
    fd.append('remove_bg', AppState.get('params.removeBg'));
    const seed = AppState.get('params.seed');
    fd.append('seed', seed !== null ? seed : Math.floor(Math.random() * 1e7));
    const data = await _post('/api/generate/textured', fd, true);
    AppState.set('activeTaskId', data.task_id);
    return data;
  }

  /** POST /api/parts/segment */
  function segmentParts(meshPath) {
    return _post('/api/parts/segment', { mesh_path: meshPath });
  }

  /** POST /api/parts/generate */
  function generateParts(internalState) {
    return _post('/api/parts/generate', { internal_state: internalState });
  }

  /** POST /api/parts/print */
  function preparePrint(internalState) {
    return _post('/api/parts/print', { internal_state: internalState });
  }

  /** POST /api/export */
  function exportMesh(opts) {
    return _post('/api/export', opts);
  }

  /** GET /api/tasks/{task_id} */
  function taskStatus(taskId) {
    return _get(`/api/tasks/${taskId}`);
  }

  /** POST /api/tasks/{task_id}/cancel */
  function cancelTask(taskId) {
    return _post(`/api/tasks/${taskId}/cancel`);
  }

  /* ==================================================================
   *  WebSocket
   * ================================================================*/

  function _connectWs() {
    if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${location.host}${BASE}/ws/progress`;
    _ws = new WebSocket(wsUrl);

    _ws.onopen = () => {
      _wsReconnectDelay = 1000;
      if (_wsCallbacks.connected) _wsCallbacks.connected();
    };

    _ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case 'progress':
          if (_wsCallbacks.progress) _wsCallbacks.progress(msg);
          break;
        case 'error':
          if (_wsCallbacks.error) _wsCallbacks.error(msg);
          break;
        case 'complete':
          if (_wsCallbacks.complete) _wsCallbacks.complete(msg);
          break;
      }
    };

    _ws.onclose = () => {
      if (_wsCallbacks.disconnected) _wsCallbacks.disconnected();
      _scheduleReconnect();
    };

    _ws.onerror = () => {};
  }

  function _scheduleReconnect() {
    if (_wsReconnectTimer) return;
    _wsReconnectTimer = setTimeout(() => {
      _wsReconnectTimer = null;
      _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, 30000);
      _connectWs();
    }, _wsReconnectDelay);
  }

  function onProgress(cb)   { _wsCallbacks.progress = cb; }
  function onError(cb)      { _wsCallbacks.error = cb; }
  function onComplete(cb)   { _wsCallbacks.complete = cb; }
  function onConnected(cb)  { _wsCallbacks.connected = cb; }
  function onDisconnected(cb) { _wsCallbacks.disconnected = cb; }

  function connect() {
    _connectWs();
    return { onProgress, onError, onComplete, onConnected, onDisconnected };
  }

  return {
    health, modelStatus, loadModel,
    generateShape, generateTextured,
    segmentParts, generateParts, preparePrint,
    exportMesh,
    taskStatus, cancelTask,
    connect,
  };
})();
