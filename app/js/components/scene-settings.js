/**
 * Scene settings panel — exposure, shadows, environment, wireframe.
 * Appears under Advanced when a mesh is loaded.
 */
var SceneSettings = (function () {
  function init() {
    var panel = document.getElementById('scene-settings');
    if (!panel) return;

    // Show panels when mesh loads, hide when empty
    AppState.subscribe('meshUrl', function (url) {
      if (url) {
        panel.classList.remove('hidden');
        var lp = document.getElementById('lighting-settings');
        if (lp) lp.classList.remove('hidden');
      }
    });

    // Exposure slider
    var expSlider = document.getElementById('scene-exposure');
    var expValue = document.getElementById('scene-exposure-value');
    if (expSlider) {
      expSlider.addEventListener('input', function () {
        var v = parseFloat(expSlider.value);
        if (expValue) expValue.textContent = v.toFixed(1);
        var mv = document.getElementById('model-viewer-3d');
        if (mv) mv.exposure = v;
      });
    }

    // Shadow intensity slider
    var shSlider = document.getElementById('scene-shadow');
    var shValue = document.getElementById('scene-shadow-value');
    if (shSlider) {
      shSlider.addEventListener('input', function () {
        var v = parseFloat(shSlider.value);
        if (shValue) shValue.textContent = v.toFixed(2);
        var mv = document.getElementById('model-viewer-3d');
        if (mv) mv.shadowIntensity = v;
      });
    }

    // Shadow softness slider
    var ssSlider = document.getElementById('scene-softness');
    var ssValue = document.getElementById('scene-softness-value');
    if (ssSlider) {
      ssSlider.addEventListener('input', function () {
        var v = parseFloat(ssSlider.value);
        if (ssValue) ssValue.textContent = v.toFixed(2);
        var mv = document.getElementById('model-viewer-3d');
        if (mv) mv.shadowSoftness = v;
      });
    }

    // Environment rotation slider
    var envSlider = document.getElementById('scene-env-rot');
    var envValue = document.getElementById('scene-env-rot-value');
    if (envSlider) {
      envSlider.addEventListener('input', function () {
        var v = parseInt(envSlider.value, 10);
        if (envValue) envValue.textContent = v + '°';
        var mv = document.getElementById('model-viewer-3d');
        if (mv) mv.setAttribute('environment-rotation', v + 'deg');
      });
    }

    // Wireframe toggle
    var wireCheck = document.getElementById('scene-wireframe');
    if (wireCheck) {
      wireCheck.addEventListener('change', function () {
        var mv = document.getElementById('model-viewer-3d');
        if (mv) {
          mv.setAttribute('variant-name', wireCheck.checked ? 'wireframe' : '');
        }
      });
    }

    // Reset camera button
    var resetBtn = document.getElementById('btn-reset-camera');
    if (resetBtn) {
      resetBtn.addEventListener('click', function () {
        var mv = document.getElementById('model-viewer-3d');
        if (mv) {
          mv.cameraTarget = 'auto auto auto';
          mv.cameraOrbit = '45deg 75deg auto';
        }
      });
    }

    // Sync toggles when a new model loads
    AppState.subscribe('meshUrl', function () {
      if (wireCheck) wireCheck.checked = false;
      var mv = document.getElementById('model-viewer-3d');
      if (mv) mv.setAttribute('variant-name', '');
    });
  }

  return { init: init };
})();
