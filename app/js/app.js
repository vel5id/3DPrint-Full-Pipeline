/**
 * Hunyuan3D-2 SPA — Application entry point.
 */
(function () {
  'use strict';

  function init() {
    Theme.init();
    StatusBar.init();
    Tabs.init();
    Upload.init();
    Presets.init();
    Params.init();
    Modal.init();
    ModelSelect.init();
    Progress.init();
    Viewer.init();
    SceneSettings.init();
    Lighting.init();

    // ── Generate Shape ──────────────────────────────────────────

    document.getElementById('btn-generate-shape').addEventListener('click', async () => {
      if (!AppState.get('image')) {
        Modal.show({ title: 'No Image', body: 'Please upload an image first.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      if (AppState.get('gpu.busy')) {
        Modal.show({ title: 'GPU Busy', body: 'A generation is already in progress. Please wait or cancel it.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      try {
        Viewer.setLoading(true);
        StatusBar.setGpuBusy('shape');
        await API.generateShape();
      } catch (e) {
        StatusBar.setGpuIdle();
        Modal.show({ title: 'Request Failed', body: e.message || 'Could not start generation.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    // ── Generate + Texture ──────────────────────────────────────

    document.getElementById('btn-generate-textured').addEventListener('click', async () => {
      if (!AppState.get('image')) {
        Modal.show({ title: 'No Image', body: 'Please upload an image first.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      if (AppState.get('gpu.busy')) {
        Modal.show({ title: 'GPU Busy', body: 'A generation is already in progress.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      try {
        Viewer.setLoading(true);
        StatusBar.setGpuBusy('textured');
        await API.generateTextured();
      } catch (e) {
        StatusBar.setGpuIdle();
        Modal.show({ title: 'Request Failed', body: e.message || 'Could not start textured generation.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    // ── Texture Tab — Apply Texture ─────────────────────────────

    document.getElementById('btn-apply-texture').addEventListener('click', async () => {
      const image = AppState.get('image');
      if (!image) {
        Modal.show({ title: 'No Image', body: 'Please upload an image in the Generate tab first.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      if (AppState.get('gpu.busy')) {
        Modal.show({ title: 'GPU Busy', body: 'A generation is already in progress.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      try {
        Viewer.setLoading(true);
        StatusBar.setGpuBusy('texture');
        await API.generateTextured();
      } catch (e) {
        StatusBar.setGpuIdle();
        Modal.show({ title: 'Texture Failed', body: e.message || 'Could not start texture generation.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    document.getElementById('btn-download-textured').addEventListener('click', () => {
      const url = AppState.get('texturedMeshUrl');
      if (url) window.open(url, '_blank');
    });

    // ── Parts Tab ───────────────────────────────────────────────

    document.getElementById('btn-segment-parts').addEventListener('click', async () => {
      const meshPath = AppState.get('meshPath') || AppState.get('texturedMeshPath');
      if (!meshPath) {
        Modal.show({ title: 'No Mesh', body: 'Generate a mesh first before segmenting.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      if (AppState.get('gpu.busy')) {
        Modal.show({ title: 'GPU Busy', body: 'Wait for the current operation to finish.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      try {
        Viewer.setLoading(true);
        StatusBar.setGpuBusy('segment');
        await API.segmentParts(meshPath);
        document.getElementById('parts-state-label').textContent = 'Segmenting...';
        document.getElementById('parts-status').classList.remove('hidden');
      } catch (e) {
        StatusBar.setGpuIdle();
        Modal.show({ title: 'Segmentation Failed', body: e.message || 'Could not start segmentation.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    document.getElementById('btn-generate-parts').addEventListener('click', async () => {
      const state = AppState.get('partsInternalState');
      if (!state) {
        Modal.show({ title: 'No Segmentation', body: 'Run segmentation first.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      if (AppState.get('gpu.busy')) {
        Modal.show({ title: 'GPU Busy', body: 'Wait for the current operation to finish.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      try {
        Viewer.setLoading(true);
        StatusBar.setGpuBusy('xpart');
        await API.generateParts(state);
        document.getElementById('parts-state-label').textContent = 'Generating parts...';
        document.getElementById('parts-status').classList.remove('hidden');
      } catch (e) {
        StatusBar.setGpuIdle();
        Modal.show({ title: 'Part Generation Failed', body: e.message || 'Could not start part generation.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    document.getElementById('btn-prepare-print').addEventListener('click', async () => {
      const state = AppState.get('partsInternalState');
      if (!state) {
        Modal.show({ title: 'No Parts', body: 'Generate parts first.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      if (AppState.get('gpu.busy')) {
        Modal.show({ title: 'GPU Busy', body: 'Wait for the current operation to finish.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      try {
        StatusBar.setGpuBusy('slicer');
        await API.preparePrint(state);
        document.getElementById('parts-state-label').textContent = 'Preparing print...';
        document.getElementById('parts-status').classList.remove('hidden');
      } catch (e) {
        StatusBar.setGpuIdle();
        Modal.show({ title: 'Print Prep Failed', body: e.message || 'Could not start print preparation.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    // Enable parts buttons once mesh is available
    AppState.subscribe('meshUrl', (url) => {
      if (url) {
        document.getElementById('btn-segment-parts').disabled = false;
        document.getElementById('btn-apply-texture').disabled = false;
      }
    });

    // Enable generate-parts after segmentation
    AppState.subscribe('segmentedMeshUrl', (url) => {
      if (url) {
        document.getElementById('btn-generate-parts').disabled = false;
        document.getElementById('parts-state-label').textContent = 'Segmentation complete ✓';
      }
    });

    // Enable print-prep after part generation
    AppState.subscribe('generatedPartsUrl', (url) => {
      if (url) {
        document.getElementById('btn-prepare-print').disabled = false;
        document.getElementById('parts-state-label').textContent = 'Parts generated ✓';
      }
    });

    AppState.subscribe('texturedMeshUrl', (url) => {
      if (url) {
        document.getElementById('btn-download-textured').classList.remove('hidden');
        document.getElementById('btn-download-textured').disabled = false;
      }
    });

    // ── Export ───────────────────────────────────────────────────

    document.getElementById('btn-export').addEventListener('click', async () => {
      const meshPath = AppState.get('meshPath') || AppState.get('texturedMeshPath');
      if (!meshPath) {
        Modal.show({ title: 'No Mesh', body: 'Please generate a mesh first.', footer: [{ label: 'OK', type: 'primary' }] });
        return;
      }
      const format = document.getElementById('export-format').value;
      const simplify = document.getElementById('export-simplify').checked;
      const faceCount = parseInt(document.getElementById('export-face-count').value, 10) || 10000;
      try {
        const result = await API.exportMesh({ mesh_path: meshPath, format, reduce_faces: simplify, target_face_count: faceCount, include_texture: !!AppState.get('texturedMeshUrl') });
        window.open(result.file_url, '_blank');
      } catch (e) {
        Modal.show({ title: 'Export Failed', body: e.message || 'Could not export mesh.', footer: [{ label: 'OK', type: 'primary' }] });
      }
    });

    document.getElementById('export-simplify').addEventListener('change', (e) => {
      document.getElementById('export-face-count').disabled = !e.target.checked;
    });

    console.log('Hunyuan3D-2 SPA initialized');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
