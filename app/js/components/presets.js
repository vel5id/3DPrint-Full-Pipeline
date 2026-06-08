/**
 * Fast / Balanced / Quality preset buttons.
 */
const Presets = (() => {
  function init() {
    document.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', () => select(btn.dataset.preset));
    });
  }

  function select(name) {
    AppState.applyPreset(name);
    document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    const active = document.querySelector(`[data-preset="${name}"]`);
    if (active) active.classList.add('active');
    Params.syncFromState();
  }

  return { init, select };
})();
