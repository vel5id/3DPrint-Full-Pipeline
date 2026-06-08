/**
 * Multi-phase progress bar + WebSocket event handling.
 * Shows "Step X/Y: Description" during generation, transitions smoothly to viewer.
 *
 * Viewer loading is triggered via AppState meshUrl subscriber — no explicit
 * Viewer.load() calls needed here.  We only set state and update the UI.
 */
const Progress = (() => {
  function init() {
    const ws = API.connect();
    ws.onProgress(update);
    ws.onComplete(handleComplete);
    ws.onError(handleError);
    ws.onDisconnected(function () { StatusBar.setWsStatus('reconnecting'); });
    ws.onConnected(function () { StatusBar.setWsStatus('connected'); });
  }

  function update(msg) {
    const phaseEl = document.getElementById('loading-phase-text');
    const fillEl = document.getElementById('loading-progress-fill');
    const pctEl = document.getElementById('loading-progress-text');

    const step = msg.step;
    const total = msg.total;
    const prefix = (step && total) ? 'Step ' + step + '/' + total + ': ' : '';

    if (phaseEl) phaseEl.textContent = prefix + formatPhase(msg.phase);
    if (fillEl) {
      fillEl.style.transition = 'width 0.6s ease';
      fillEl.style.width = msg.percent + '%';
    }
    if (pctEl) pctEl.textContent = Math.round(msg.percent) + '%';
    StatusBar.setGpuBusy(msg.phase);
    Viewer.setLoading(true);
  }

  function handleComplete(msg) {
    var result = msg.result || {};

    var fillEl = document.getElementById('loading-progress-fill');
    var pctEl = document.getElementById('loading-progress-text');
    var phaseEl = document.getElementById('loading-phase-text');
    if (fillEl) { fillEl.style.transition = 'width 0.3s ease'; fillEl.style.width = '100%'; }
    if (pctEl) pctEl.textContent = '100%';
    if (phaseEl) phaseEl.textContent = 'Complete ✓';

    // -- Shape / Textured mesh -------------------------------------------
    if (result.mesh_url) {
      AppState.setAll({
        meshPath: result.mesh_path,
        meshUrl: result.mesh_url,
        meshStats: result.stats,
        activeTaskId: null
      });
      if (result.textured_mesh_url) {
        AppState.set('texturedMeshUrl', result.textured_mesh_url);
        AppState.set('texturedMeshPath', result.textured_mesh_path);
      }
      StatusBar.setGpuIdle();
      StatusBar.updateMeshStats(result.stats);
      Tabs.unlockAfterGenerate();
      // AppState subscriber in Viewer picks up meshUrl and calls load()
    }

    // -- Parts -----------------------------------------------------------
    if (result.segmented_mesh_url) {
      AppState.set('segmentedMeshUrl', result.segmented_mesh_url);
      AppState.set('partsInternalState', result.internal_state || result.segmented_mesh_url);
      StatusBar.setGpuIdle();
      Tabs.switchTo('parts');
    }
    if (result.parts_mesh_url) {
      AppState.set('generatedPartsUrl', result.parts_mesh_url);
      AppState.set('explodedPartsUrl', result.exploded_mesh_url);
      AppState.set('partsInternalState', result.internal_state);
      StatusBar.setGpuIdle();
    }
    if (result.zip_url) {
      AppState.set('printZipUrl', result.zip_url);
      StatusBar.setGpuIdle();
      window.open(result.zip_url, '_blank');
    }
  }

  function handleError(msg) {
    StatusBar.setGpuIdle();
    Viewer.setLoading(false);
    var title = msg.code === 'cuda_oom' ? 'GPU Out of Memory'
      : msg.code === 'empty_mesh' ? 'Empty Mesh Generated'
      : 'Generation Failed';
    Modal.show({
      title: title,
      body: msg.message,
      actions: (msg.suggestions || []).map(function (s) { return { label: s }; }),
      footer: [{ label: 'Close', type: 'primary' }]
    });
  }

  function formatPhase(phase) {
    var labels = {
      rembg:         'Remove background',
      encode:        'Encode image…',
      generate:      'Generate 3D shape…',
      decode:        'Decode surface…',
      postprocess:   'Clean up mesh…',
      texture:       'Generate texture…',
      texture_bake:  'Bake texture map…',
      save:          'Save to disk…',
      starting:      'Initializing…',
      cleanup:       'Free GPU memory…',
      load_mesh:     'Loading mesh…',
      segment:       'Segment parts (GPU)…',
      color:         'Color segments…',
      xpart:         'Generate parts (XPart)…',
      unload_xpart:  'Unload XPart…',
      slice:         'Slice for printing…',
      zip:           'Create ZIP archive…',
      complete:      'Complete ✓',
      cancelled:     'Cancelled'
    };
    return labels[phase] || phase;
  }

  return { init: init, update: update };
})();
