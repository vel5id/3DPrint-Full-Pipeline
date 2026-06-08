/**
 * Tab bar with contextual activation.
 */
const Tabs = (() => {
  let _tabs = {};

  function init() {
    document.querySelectorAll('#tab-bar .tab').forEach(btn => {
      const name = btn.dataset.tab;
      _tabs[name] = btn;
      btn.addEventListener('click', () => switchTo(name));
    });
    AppState.subscribe('meshUrl', (url) => { if (url) unlockAfterGenerate(); });
  }

  function switchTo(name) {
    const btn = _tabs[name];
    if (!btn || btn.disabled) return;
    Object.values(_tabs).forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const panel = document.querySelector(`[data-panel="${name}"]`);
    if (panel) panel.classList.add('active');
    AppState.set('activeTab', name);
  }

  function unlockAfterGenerate() {
    ['texture', 'parts'].forEach(name => {
      const btn = _tabs[name];
      if (btn) btn.disabled = false;
    });
  }

  return { init, switchTo, unlockAfterGenerate };
})();
