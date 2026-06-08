/**
 * Studio lighting via dynamic environment map.
 * Generates a lat-long canvas with bright spots at light positions.
 * Applied as model-viewer environment-image data URL.
 */
var Lighting = (function () {
  var _mv = null;
  var _canvas = null;
  var _ctx = null;
  var W = 512, H = 256;

  var _cfg = {
    count: 2,
    preset: 'lr',
    color: '#ffcc88',
    intensity: 4.0,
    distance: 3.5
  };

  // Light position presets as lat-long coordinates
  // Each entry: { phi: azimuth-deg, theta: elevation-deg }
  //   phi=0     front,   phi=90   right,   phi=180  back,    phi=270  left
  //   theta=0   horizon, theta=+90 top,      theta=-90 bottom
  var PRESETS = {
    front:    [{ phi: 0,   theta: 15 }],
    lr:       [{ phi: 315, theta: 20 }, { phi: 45, theta: 20 }],
    triangle: [{ phi: 0,   theta: 50 },
               { phi: 120, theta: -10 },
               { phi: 240, theta: -10 }],
    quad:     [{ phi: 0,   theta: 25 },
               { phi: 90,  theta: 25 },
               { phi: 180, theta: 25 },
               { phi: 270, theta: 25 }]
  };

  function _hexToRGB(hex) {
    return {
      r: parseInt(hex.slice(1, 3), 16),
      g: parseInt(hex.slice(3, 5), 16),
      b: parseInt(hex.slice(5, 7), 16)
    };
  }

  function _initCanvas() {
    if (_canvas) return;
    _canvas = document.createElement('canvas');
    _canvas.width = W;
    _canvas.height = H;
    _ctx = _canvas.getContext('2d');
  }

  function _renderEnvMap() {
    _initCanvas();
    var ctx = _ctx;
    var w = W, h = H;

    // Dark ambient base
    ctx.fillStyle = 'rgb(5,5,7)';
    ctx.fillRect(0, 0, w, h);

    var positions = PRESETS[_cfg.preset] || PRESETS['lr'];
    var limit = Math.min(_cfg.count, positions.length);
    var rgb = _hexToRGB(_cfg.color);
    var baseIntensity = _cfg.intensity;
    var dist = _cfg.distance;

    for (var i = 0; i < limit; i++) {
      var p = positions[i];
      // phi: azimuth (0=front, 90=right, 180=back, 270=left)
      // On lat-long canvas: x = (phi/360) * width
      var cx = ((p.phi / 360) % 1.0) * w;
      if (cx < 0) cx += w;

      // theta: elevation (-90=bottom, +90=top)
      // Map theta [-90, 90] to y [H, 0]
      var cy = h - ((p.theta + 90) / 180) * h;
      cy = Math.max(4, Math.min(h - 4, cy));

      // Spot size based on distance (farther = tighter spot)
      var spotRadius = Math.max(40, 100 - dist * 6);

      // Draw radial gradient spot
      var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, spotRadius);
      var r = rgb.r, g = rgb.g, b = rgb.b;
      // Intensity scales the center brightness
      var bright = Math.min(255, Math.round(baseIntensity * 45));
      var alpha = Math.min(1.0, baseIntensity / 8);

      grad.addColorStop(0, 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')');
      grad.addColorStop(0.15, 'rgba(' + r + ',' + g + ',' + b + ',' + (alpha * 0.85) + ')');
      grad.addColorStop(0.4, 'rgba(' + Math.round(r * 0.7) + ',' + Math.round(g * 0.7) + ',' + Math.round(b * 0.7) + ',' + (alpha * 0.4) + ')');
      grad.addColorStop(0.7, 'rgba(15,15,20,0.1)');
      grad.addColorStop(1, 'rgba(5,5,7,0)');

      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
    }

    // Apply distance effect: closer = larger, wider lit area
    // Simulated by adjusting overall scene fill
    var fillAlpha = Math.max(0.01, 0.06 - dist * 0.01);
    ctx.fillStyle = 'rgba(' + Math.round(rgb.r * 0.15) + ',' + Math.round(rgb.g * 0.15) + ',' + Math.round(rgb.b * 0.15) + ',' + fillAlpha + ')';
    ctx.fillRect(0, 0, w, h);

    // Update model-viewer with canvas as data URL
    if (_mv && _mv.src) {
      var dataUrl = _canvas.toDataURL('image/png');
      _mv.environmentImage = dataUrl;
    }
  }

  // ── Public ──────────────────────────────────────────────────────

  function init() {
    _mv = document.getElementById('model-viewer-3d');
    if (!_mv) return;
    _initCanvas();
    _wireUI();
    _syncFromUI();

    // Apply lighting after each model load
    _mv.addEventListener('load', function () {
      setTimeout(_renderEnvMap, 200);
    });
  }

  function _wireUI() {
    var countSelect = document.getElementById('light-count');
    var presetSelect = document.getElementById('light-preset');
    var colorInput = document.getElementById('light-color');
    var intSlider = document.getElementById('light-intensity');
    var distSlider = document.getElementById('light-distance');
    var intVal = document.getElementById('light-intensity-value');
    var distVal = document.getElementById('light-distance-value');

    function update() {
      _syncFromUI();
      _renderEnvMap();
    }

    if (countSelect) countSelect.addEventListener('change', update);
    if (presetSelect) presetSelect.addEventListener('change', update);
    if (colorInput) colorInput.addEventListener('input', update);
    if (intSlider) {
      intSlider.addEventListener('input', function () {
        intVal.textContent = parseFloat(this.value).toFixed(1);
        update();
      });
    }
    if (distSlider) {
      distSlider.addEventListener('input', function () {
        distVal.textContent = parseFloat(this.value).toFixed(1) + 'u';
        update();
      });
    }
  }

  function _syncFromUI() {
    var countSelect = document.getElementById('light-count');
    var presetSelect = document.getElementById('light-preset');
    var colorInput = document.getElementById('light-color');
    var intSlider = document.getElementById('light-intensity');
    var distSlider = document.getElementById('light-distance');
    if (countSelect) _cfg.count = parseInt(countSelect.value, 10);
    if (presetSelect) _cfg.preset = presetSelect.value;
    if (colorInput) _cfg.color = colorInput.value;
    if (intSlider) _cfg.intensity = parseFloat(intSlider.value);
    if (distSlider) _cfg.distance = parseFloat(distSlider.value);
  }

  function refresh() { _renderEnvMap(); }

  return { init: init, refresh: refresh };
})();
