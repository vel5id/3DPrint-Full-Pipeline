/**
 * 3D Viewer wrapper around <model-viewer>.
 *
 * Lighting is driven by a custom studio environment map (assets/studio-env.png)
 * — warm hemisphere left, cool hemisphere right, brighter ceiling.
 * No JS light injection needed.
 */
const Viewer = (() => {
  let _viewer, _emptyEl, _loadingEl, _toolbar;
  let _loadTimer = null;
  let _loaded = false;
  let _lastUrl = '';

  function init() {
    _viewer = document.getElementById('model-viewer-3d');
    _emptyEl = document.getElementById('viewer-empty');
    _loadingEl = document.getElementById('viewer-loading');
    _toolbar = document.getElementById('viewer-toolbar');

    document.querySelectorAll('.toolbar-btn[data-mode]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('.toolbar-btn[data-mode]').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        _viewer.setAttribute('variant-name', btn.dataset.mode === 'wireframe' ? 'wireframe' : '');
      });
    });

    document.getElementById('viewer-reset') && document.getElementById('viewer-reset').addEventListener('click', function () {
      _viewer.cameraOrbit = '45deg 75deg auto';
    });
    document.getElementById('viewer-fullscreen') && document.getElementById('viewer-fullscreen').addEventListener('click', function () {
      var c = document.getElementById('viewer-container');
      document.fullscreenElement ? document.exitFullscreen() : c.requestFullscreen();
    });

    _viewer.addEventListener('load', _onLoaded);
    _viewer.addEventListener('error', _onError);

    AppState.subscribe('meshUrl', function (url) { if (url) load(url); });
  }

  function _onLoaded() {
    if (_loadTimer) { clearTimeout(_loadTimer); _loadTimer = null; }
    _loaded = true;
    _setLoadingVisible(false);
    if (_toolbar) _toolbar.classList.remove('hidden');
    _updateLoadingText('Model ready', '100%');

    setTimeout(function () {
      _viewer.cameraTarget = 'auto auto auto';
      _viewer.cameraOrbit = '30deg 75deg auto';
    }, 100);
  }

  function _onError() {
    if (_loadTimer) { clearTimeout(_loadTimer); _loadTimer = null; }
    _loaded = false;
    _setLoadingVisible(false);
    _showEmpty();
    Modal.show({
      title: 'Failed to Load Model',
      body: 'The 3D model could not be loaded.',
      footer: [{ label: 'OK', type: 'primary' }]
    });
  }

  function _showEmpty() {
    if (_emptyEl) _emptyEl.classList.add('visible');
    if (_loadingEl) _loadingEl.classList.remove('visible');
    if (_viewer) _viewer.classList.remove('visible');
    if (_toolbar) _toolbar.classList.add('hidden');
  }

  function _setLoadingVisible(show) {
    if (!_loadingEl) return;
    if (show) _loadingEl.classList.add('visible');
    else _loadingEl.classList.remove('visible');
  }

  function _updateLoadingText(phase, pct) {
    var phaseEl = document.getElementById('loading-phase-text');
    var fillEl = document.getElementById('loading-progress-fill');
    var pctEl = document.getElementById('loading-progress-text');
    if (phaseEl) phaseEl.textContent = phase;
    if (fillEl) { fillEl.style.transition = 'width 0.5s ease'; fillEl.style.width = pct; }
    if (pctEl) pctEl.textContent = pct;
  }

  function load(url) {
    if (!url) return;
    if (url === _lastUrl) return;  // already loading/loaded this URL
    _lastUrl = url;
    _loaded = false;
    if (_loadTimer) { clearTimeout(_loadTimer); _loadTimer = null; }

    _viewer.classList.add('visible');
    if (_emptyEl) _emptyEl.classList.remove('visible');
    _setLoadingVisible(true);
    _updateLoadingText('Loading 3D model…', '100%');
    if (_toolbar) _toolbar.classList.add('hidden');

    _viewer.src = '';
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        _viewer.src = url;
        _loadTimer = setTimeout(function () {
          if (!_loaded) {
            _loaded = true;
            _setLoadingVisible(false);
            if (_toolbar) _toolbar.classList.remove('hidden');
            _viewer.cameraTarget = 'auto auto auto';
            _viewer.cameraOrbit = '45deg 75deg auto';
          }
        }, 12000);
      });
    });
  }

  function setLoading(show) {
    _setLoadingVisible(show);
    if (!show && !_viewer.src) _showEmpty();
    else if (!show) _viewer.classList.add('visible');
  }

  function clear() {
    _loaded = false;
    if (_loadTimer) { clearTimeout(_loadTimer); _loadTimer = null; }
    _viewer.src = '';
    _showEmpty();
  }

  return { init: init, load: load, clear: clear, setLoading: setLoading };
})();
