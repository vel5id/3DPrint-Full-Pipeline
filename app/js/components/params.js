/**
 * Parameter panel — compact and advanced modes.
 */
const Params = (() => {
  const SLIDERS = [
    { stateKey: 'params.steps', sliderId: 'param-steps', valueId: 'param-steps-value' },
    { stateKey: 'params.guidanceScale', sliderId: 'param-guidance', valueId: 'param-guidance-value', decimals: 1 },
    { stateKey: 'params.octreeResolution', sliderId: 'param-octree', valueId: 'param-octree-value' },
    { stateKey: 'params.numChunks', sliderId: 'param-chunks', valueId: 'param-chunks-value', format: v => v >= 1000 ? `${Math.round(v/1000)}K` : String(v) },
  ];

  function init() {
    const seedInput = document.getElementById('param-seed');
    const randomCheck = document.getElementById('param-random-seed');
    seedInput?.addEventListener('input', () => {
      AppState.set('params.seed', seedInput.value ? parseInt(seedInput.value, 10) : null);
      AppState.set('params.randomizeSeed', false);
      if (randomCheck) randomCheck.checked = false;
    });
    randomCheck?.addEventListener('change', () => {
      if (seedInput) seedInput.disabled = randomCheck.checked;
      AppState.set('params.randomizeSeed', randomCheck.checked);
    });

    const removeBgCheck = document.getElementById('param-remove-bg');
    removeBgCheck?.addEventListener('change', () => AppState.set('params.removeBg', removeBgCheck.checked));

    document.getElementById('toggle-advanced')?.addEventListener('click', () => setAdvanced(true));
    document.getElementById('toggle-advanced-collapse')?.addEventListener('click', () => setAdvanced(false));

    SLIDERS.forEach(({ stateKey, sliderId, valueId, decimals, format }) => {
      const slider = document.getElementById(sliderId);
      if (!slider) return;
      slider.addEventListener('input', () => {
        const val = decimals ? parseFloat(slider.value) : parseInt(slider.value, 10);
        AppState.set(stateKey, val);
        const display = document.getElementById(valueId);
        if (display) display.textContent = format ? format(val) : String(val);
      });
    });

    AppState.subscribe('preset', () => syncFromState());
  }

  function setAdvanced(show) {
    const adv = document.getElementById('params-advanced');
    const compact = document.getElementById('toggle-advanced');
    if (show) {
      adv?.classList.remove('hidden');
      if (compact) compact.style.display = 'none';
    } else {
      adv?.classList.add('hidden');
      if (compact) compact.style.display = '';
    }
    AppState.set('advancedMode', show);
  }

  function syncFromState() {
    SLIDERS.forEach(({ stateKey, sliderId, valueId, format }) => {
      const val = AppState.get(stateKey);
      const slider = document.getElementById(sliderId);
      const display = document.getElementById(valueId);
      if (slider) slider.value = val;
      if (display) display.textContent = format ? format(val) : String(val);
    });
  }

  return { init, setAdvanced, syncFromState };
})();
